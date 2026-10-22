"""Mac lifecycle controller. Never runs a solver or kills a process by PID/name."""
import argparse
import base64
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import socket
import stat
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.request import ProxyHandler, build_opener


class LifecycleError(Exception):
    pass


def ps_literal(value):
    return "'" + value.replace("'", "''") + "'"


class Controller:
    def __init__(self):
        self.host = os.environ.get('SOLVER_WEB_HOST', 'desktop-msi')
        if not self.host or self.host.startswith('-') or any(c.isspace() for c in self.host):
            raise LifecycleError('SOLVER_WEB_HOST 必须为 SSH 主机别名。')
        try:
            self.port = int(os.environ.get('SOLVER_WEB_PORT', '8765'))
            if not 1024 <= self.port <= 65535:
                raise ValueError()
        except ValueError as exc:
            raise LifecycleError('SOLVER_WEB_PORT 必须为 1024–65535 的整数。') from exc
        self.root = os.environ.get('SOLVER_WEB_ROOT', r'F:\01-Project\Opensource\01-FluidX3D')
        self.checkout = os.environ.get('SOLVER_WEB_CHECKOUT', self.root + r'\web-src')
        self.data = os.environ.get('SOLVER_WEB_DATA', self.root + r'\workingdir\web-workbench')
        self.url = f'http://127.0.0.1:{self.port}'
        key = hashlib.sha256(f'{self.host}:{self.port}'.encode()).hexdigest()[:12]
        # macOS Unix sockets need a short path; only this user may control this connection.
        self.runtime = Path(f'/tmp/solver-ibm-{os.getuid()}-{key}')
        self.control = self.runtime / 'ssh.sock'
        self.log = self.runtime / 'ssh.log'
        self.ssh = ['/usr/bin/ssh', '-nT', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10',
                    '-o', 'ServerAliveInterval=15', '-o', 'ServerAliveCountMax=3',
                    '-o', 'ForwardAgent=no']

    @contextmanager
    def lock(self):
        self.runtime.mkdir(mode=0o700, exist_ok=True)
        info = self.runtime.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise LifecycleError(f'连接状态目录权限不正确：{self.runtime}')
        with (self.runtime / 'action.lock').open('a') as stream:
            try:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise LifecycleError('另一个启动/关闭操作正在执行，请稍后重试。') from exc
            yield

    def remote(self, action):
        path = self.checkout + r'\workbench\scripts\manage-windows.ps1'
        script = ("$ErrorActionPreference='Stop'; "
                  "[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new($false); "
                  f"& {ps_literal(path)} -Action {ps_literal(action)} "
                  f"-WorkspaceRoot {ps_literal(self.root)} -DataRoot {ps_literal(self.data)} -Port {self.port}")
        encoded = base64.b64encode(script.encode('utf-16le')).decode('ascii')
        result = subprocess.run(self.ssh + ['-o', 'ControlMaster=no', '-o', 'ControlPath=none',
                                '-o', 'ClearAllForwardings=yes', self.host,
                                'powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass '
                                '-EncodedCommand ' + encoded],
                                capture_output=True, text=True, errors='replace', timeout=120)
        if result.returncode:
            detail = (result.stderr or result.stdout).strip()
            raise LifecycleError('Windows 操作失败，未强制关闭任何进程。\n' + detail)
        for line in reversed(result.stdout.splitlines()):
            if line.startswith('SOLVER_WORKBENCH_STATE='):
                return json.loads(line.split('=', 1)[1])
        raise LifecycleError('Windows 未返回可确认的状态，请检查服务日志。')

    def control_command(self, action):
        return subprocess.run(self.ssh + ['-S', str(self.control), '-O', action, self.host],
                              capture_output=True, text=True, errors='replace', timeout=15)

    def connected(self):
        return self.control.exists() and self.control_command('check').returncode == 0

    def port_open(self):
        try:
            with socket.create_connection(('127.0.0.1', self.port), timeout=1):
                return True
        except OSError:
            return False

    def start_tunnel(self):
        self.control.unlink(missing_ok=True)
        with self.log.open('a') as log:
            result = subprocess.run(self.ssh + ['-M', '-S', str(self.control),
                                    '-o', 'ControlPersist=no', '-o', 'ExitOnForwardFailure=yes',
                                    '-o', 'PermitLocalCommand=no', '-fN',
                                    '-L', f'127.0.0.1:{self.port}:127.0.0.1:{self.port}', self.host],
                                    stdout=log, stderr=log, timeout=30)
        if result.returncode or not self.connected():
            raise LifecycleError(f'SSH 隧道启动失败，日志：{self.log}')

    def stop_tunnel(self):
        if self.connected():
            result = self.control_command('exit')
            if result.returncode:
                raise LifecycleError('Windows 已停止，但后台隧道关闭失败：' + result.stderr.strip())
            for _ in range(40):
                if not self.connected():
                    break
                time.sleep(.1)
            else:
                raise LifecycleError('隧道尚未退出，请稍后重试关闭。')
        if self.control.exists():
            self.control.unlink()

    def wait_ready(self, expected):
        client = build_opener(ProxyHandler({}))
        for _ in range(20):
            try:
                with client.open(self.url + '/api/session', timeout=2) as response:
                    identity = json.load(response)['solver']
                if any(identity.get(k) != expected.get(k) for k in ('product', 'version', 'sha256')):
                    raise LifecycleError('Mac 端口返回了不同的服务，未打开网页。')
                return
            except (URLError, OSError, ValueError, KeyError):
                time.sleep(.5)
        raise LifecycleError('隧道已建立，但工作台未就绪。')

    def start(self, open_browser=True):
        owned = self.connected()
        if not owned and self.port_open():
            raise LifecycleError(f'Mac 端口 {self.port} 已被其他程序或手动隧道占用；请先关闭该连接后重试。')
        print('正在启动或连接 Windows 执行服务…', flush=True)
        state = self.remote('start')
        created_tunnel = False
        try:
            if not owned:
                self.start_tunnel()
                created_tunnel = True
            self.wait_ready(state['solver'])
        except (LifecycleError, subprocess.TimeoutExpired, KeyboardInterrupt):
            if not owned:
                self.stop_tunnel()
            if state.get('started'):
                try:
                    rollback = self.remote('stop')
                    print('启动未完成；新建服务已关闭。' if rollback['result'] == 'stopped'
                          else '启动未完成；Windows 出现计算任务，已保留执行服务。')
                except (LifecycleError, subprocess.TimeoutExpired) as exc:
                    print(f'新建服务状态需复查，请运行关闭脚本：{exc}', file=sys.stderr)
            raise
        print(f'工作台已就绪：{self.url}')
        print('已建立后台 SSH 隧道。' if created_tunnel else '已复用现有后台 SSH 隧道。')
        print('可关闭此终端和浏览器；需要停止服务时双击“关闭工作台.command”。')
        if open_browser:
            subprocess.run(['/usr/bin/open', self.url], check=True)

    def stop(self):
        print('正在检查 Windows 活动任务和实际计算进程…', flush=True)
        state = self.remote('stop')
        if state['result'] != 'stopped':
            job = state.get('active_job')
            if job:
                print(f"活动任务：{job.get('case_name', '')} [{job['id']}]，状态：{job['status']}")
            for process in state.get('solver_processes', []):
                print(f"计算进程：{process['Name']}，PID {process['ProcessId']}")
            raise LifecycleError('当前仍有计算或校验任务，已取消关闭并保留连接。请等待完成，或在工作台终止任务后再次关闭。')
        self.stop_tunnel()
        print('Windows 执行服务已停止，已确认没有 Solver-IBM / FluidX3D 计算进程。')
        if self.port_open():
            print(f'本脚本的隧道已退出；Mac 端口 {self.port} 仍被其他连接占用，请检查手动建立的隧道。')
        else:
            print('SSH 隧道已关闭，Mac 和 Windows 的工作台端口均已释放。')
        print('算例、结果文件和日志均保留。')


def main():
    parser = argparse.ArgumentParser(description='Solver-IBM Mac 一键启动/关闭')
    parser.add_argument('action', choices=['start', 'stop', 'status'])
    parser.add_argument('--no-browser', action='store_true', help='启动时不打开浏览器（供终端检查）')
    args = parser.parse_args()
    try:
        controller = Controller()
        with controller.lock():
            if args.action == 'start':
                controller.start(not args.no_browser)
            elif args.action == 'stop':
                controller.stop()
            else:
                state = controller.remote('status')
                state['managed_tunnel'] = controller.connected()
                print(json.dumps(state, ensure_ascii=False, indent=2))
        return 0
    except (LifecycleError, OSError, subprocess.SubprocessError, ValueError) as exc:
        print(f'操作未完成：{exc}', file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print('操作已中断，请运行关闭脚本检查当前状态。', file=sys.stderr)
        return 130


if __name__ == '__main__':
    sys.exit(main())
