"""Single-user loopback HTTP service; reach it from Mac through SSH forwarding."""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
import os
from pathlib import Path
import secrets
import signal
import threading
from urllib.parse import parse_qs, unquote, urlsplit

from core import MAX_STL, VERSION, WORKBENCH, Package, Problem, Solver, Workbench, inside


def make_server(workbench, port=8765):
    token = secrets.token_urlsafe(32)

    class Handler(BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'

        def setup(self):
            super().setup()
            self.connection.settimeout(65)

        def reply(self, data, status=200):
            body = json.dumps(data, ensure_ascii=False, allow_nan=False).encode('utf-8')
            self.send_response(status)
            self.headers_out('application/json; charset=utf-8', len(body))
            self.end_headers()
            self.wfile.write(body)

        def headers_out(self, content_type, size):
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(size))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('Content-Security-Policy',
                             "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
                             "img-src 'self' blob: data:; connect-src 'self'; object-src 'none'; "
                             "base-uri 'none'; frame-ancestors 'none'")

        def origin_check(self):
            host = self.headers.get('Host', '')
            parsed = urlsplit('http://' + host)
            if parsed.hostname not in ('127.0.0.1', 'localhost', '::1') or parsed.username:
                raise Problem('仅允许通过本机地址访问工作台', 403)
            origin = self.headers.get('Origin')
            if origin and origin != 'http://' + host:
                raise Problem('拒绝跨站请求', 403)
            if self.headers.get('Sec-Fetch-Site') == 'cross-site':
                raise Problem('拒绝跨站请求', 403)
            if self.command != 'GET' and not secrets.compare_digest(
                    self.headers.get('X-Workbench-Token', ''), token):
                raise Problem('页面连接已过期，请刷新工作台', 403)

        def body(self, maximum=2 * 1024 * 1024, raw=False):
            if self.headers.get('Transfer-Encoding'):
                raise Problem('不支持分块请求', 400)
            try:
                size = int(self.headers.get('Content-Length', '-1'))
            except ValueError as exc:
                raise Problem('无效的 Content-Length') from exc
            if not 0 <= size <= maximum:
                raise Problem('请求体为空或超过大小限制', 413)
            data = self.rfile.read(size)
            if len(data) != size:
                raise Problem('请求未完整接收')
            if raw:
                return data
            if self.headers.get_content_type() != 'application/json':
                raise Problem('需要 application/json 请求')
            def invalid(value):
                raise ValueError('不允许非有限数值：' + value)
            result = json.loads(data.decode('utf-8'), parse_constant=invalid)
            if not isinstance(result, dict):
                raise Problem('请求必须为 JSON 对象')
            return result

        def file(self, path, download=False):
            if not path.is_file():
                raise Problem('文件不存在', 404)
            content_type = mimetypes.guess_type(str(path))[0] or 'application/octet-stream'
            if path.suffix == '.js':
                content_type = 'text/javascript; charset=utf-8'
            with path.open('rb') as stream:
                size = os.fstat(stream.fileno()).st_size
                self.send_response(200)
                self.headers_out(content_type, size)
                if download:
                    self.send_header('Content-Disposition', 'attachment; filename="' +
                                     path.name.encode('ascii', 'replace').decode().replace('"', '-') + '"')
                self.end_headers()
                remaining = size
                while remaining:
                    chunk = stream.read(min(1024 * 1024, remaining))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)

        def route(self):
            workbench = self.server.workbench
            self.origin_check()
            url = urlsplit(self.path)
            path, query = unquote(url.path), parse_qs(url.query)
            if path == '/api/session' and self.command == 'GET':
                return self.reply({'token': token, 'version': VERSION, 'solver': workbench.package.identity,
                                   'devices': workbench.runner.devices, 'active_job': workbench.active})
            if path == '/api/draft':
                if self.command == 'GET':
                    return self.reply(workbench.draft())
                if self.command == 'PUT':
                    return self.reply(workbench.save_draft(self.body()))
            if path == '/api/assets' and self.command == 'POST':
                name = query.get('name', ['upload.stl'])[0]
                return self.reply(workbench.upload(name, self.body(MAX_STL, raw=True)), 201)
            if path.startswith('/api/assets/') and self.command == 'GET':
                return self.file(inside(workbench.root, 'assets/' + path[len('/api/assets/'):]))
            if path == '/api/validate' and self.command == 'POST':
                return self.reply(workbench.validate(self.body().get('config')))
            if path == '/api/jobs':
                if self.command == 'GET':
                    return self.reply({'jobs': workbench.jobs(), 'active_job': workbench.active})
                if self.command == 'POST':
                    return self.reply(workbench.submit(self.body()), 202)
            if path.startswith('/api/jobs/'):
                parts = path.split('/')
                ident = parts[3]
                if len(parts) == 4 and self.command == 'GET':
                    return self.reply(workbench.record(ident))
                if len(parts) == 5:
                    action = parts[4]
                    if action == 'stop' and self.command == 'POST':
                        self.body()
                        return self.reply(workbench.stop(ident))
                    if self.command == 'GET':
                        if action == 'logs':
                            return self.reply(workbench.logs(ident))
                        if action == 'series':
                            return self.reply(workbench.series(ident, query.get('file', ['monitor.csv'])[0]))
                        if action == 'files':
                            return self.reply({'files': workbench.files(ident)})
                        if action == 'download':
                            relative = query.get('path', [''])[0]
                            if relative.startswith('runtime/'):
                                raise Problem('程序快照不通过浏览器下载', 403)
                            return self.file(inside(workbench.record_path(ident).parent, relative), True)
            if path.startswith('/api/'):
                raise Problem('接口不存在或此操作不在首版范围内', 404)
            if self.command == 'GET':
                return self.file(inside(WORKBENCH / 'web', path.lstrip('/') or 'index.html'))
            raise Problem('不支持此请求', 405)

        def dispatch(self):
            try:
                self.route()
            except (BrokenPipeError, ConnectionResetError):
                pass
            except Problem as exc:
                self.close_connection = True
                self.reply({'error': str(exc)}, exc.status)
            except (ValueError, TypeError, KeyError, AttributeError) as exc:
                self.close_connection = True
                self.reply({'error': '请求格式无效：' + str(exc)}, 400)
            except Exception as exc:
                self.close_connection = True
                self.log_error('Request failed: %s', exc)
                self.reply({'error': '服务处理失败：' + str(exc)}, 500)

        do_GET = do_POST = do_PUT = dispatch

    class Server(ThreadingHTTPServer):
        daemon_threads = True
        allow_reuse_address = False

    server = Server(('127.0.0.1', port), Handler)
    server.workbench = workbench
    return server


def main():
    parser = argparse.ArgumentParser(description='Solver-IBM Workbench Windows execution service')
    parser.add_argument('--package', required=True, type=Path)
    parser.add_argument('--data', required=True, type=Path)
    parser.add_argument('--port', type=int, default=8765)
    args = parser.parse_args()
    if os.name != 'nt':
        parser.error('真实执行服务仅能在 Windows 启动；Mac 使用连接脚本。')
    package = Package(args.package)
    runner = Solver(package)
    # Bind before opening the data store: a duplicate service must not mark live runs interrupted.
    server = make_server(None, args.port)
    try:
        workbench = Workbench(args.data, package, runner)
        server.workbench = workbench
    except BaseException:
        server.server_close()
        raise
    def shutdown(signum, frame):
        threading.Thread(target=server.shutdown, daemon=True).start()
    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)
    print(f'Solver-IBM Workbench {VERSION} http://127.0.0.1:{args.port}', flush=True)
    try:
        server.serve_forever(poll_interval=.2)
    finally:
        workbench.shutdown()
        server.server_close()


if __name__ == '__main__':
    main()
