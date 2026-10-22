"""V2.0.0 workbench: immutable inputs, one owned job, durable records."""
from __future__ import annotations

import copy
import csv
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import threading
import time
import uuid
from datetime import datetime, timezone

from winprocess import Job

VERSION = '0.1.0-dev'
BASE_COMMIT = '58f44e5013b7b1ffe105107cfa2a27f8d557e45d'
MAX_STL = 50 * 1024 * 1024
ACTIVE = {'validating', 'starting', 'running', 'cancelling'}
WORKBENCH = Path(__file__).resolve().parents[1]


class Problem(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def now():
    return datetime.now(timezone.utc).isoformat()


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def atomic_json(path, value):
    path = Path(path)
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        with temporary.open('w', encoding='utf-8', newline='\n') as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def inside(root, relative):
    """Reject traversal, absolute paths, NTFS streams, and existing link aliases."""
    if not isinstance(relative, str) or not relative or '\\' in relative or ':' in relative:
        raise Problem('无效的相对路径')
    parts = relative.split('/')
    if any(part in ('', '.', '..') for part in parts):
        raise Problem('路径必须位于当前工作台中')
    base = Path(root).resolve()
    path = base.joinpath(*parts)
    if not path.resolve().is_relative_to(base):
        raise Problem('不能访问工作台之外的文件', 403)
    current = path
    while current != base:
        if current.is_symlink() or (hasattr(current, 'is_junction') and current.is_junction()):
            raise Problem('不允许通过文件链接访问资源', 403)
        current = current.parent
    return path


def asset_paths(config):
    if not isinstance(config, dict) or config.get('schema_version') != 1:
        raise Problem('需要 schema_version=1 的算例对象')
    if any(k in config for k in ('refinement', 'refinement_draft', 'study', 'scan')):
        raise Problem('局部加密与参数扫描不能写入 V2.0.0 算例')
    if not isinstance(config.get('domain'), dict) or 'refinement' in config['domain']:
        raise Problem('无效的 domain 字段')
    if not isinstance(config.get('run'), dict) or any(k not in ('steps', 'duration', 'monitor_every') for k in config['run']):
        raise Problem('V2.0.0 的 run 仅接受 steps/duration/monitor_every；不支持续算')
    paths = []
    for item in config.get('geometry', []):
        paths.append(item.get('file'))
    for item in config.get('initial', {}).get('liquid_regions', []):
        if item.get('shape') == 'stl':
            paths.append(item.get('file'))
    for path in paths:
        if not isinstance(path, str) or not re.fullmatch(r'assets/[a-zA-Z0-9._-]+\.stl', path):
            raise Problem('STL 必须先上传到工作台，file 使用返回的 assets/ 路径')
    return sorted(set(paths))


def stl_info(data):
    if len(data) < 84 or len(data) > MAX_STL:
        raise Problem('二进制 STL 大小必须在 84 B 到 50 MiB 之间')
    count = struct.unpack_from('<I', data, 80)[0]
    if not count or len(data) != 84 + count * 50:
        raise Problem('需要完整的二进制 STL 文件')
    lo, hi = [math.inf] * 3, [-math.inf] * 3
    for index in range(count):
        vertices = struct.unpack_from('<9f', data, 84 + index * 50 + 12)
        for i, value in enumerate(vertices):
            if not math.isfinite(value):
                raise Problem('STL 中存在非有限顶点坐标')
            lo[i % 3] = min(lo[i % 3], value)
            hi[i % 3] = max(hi[i % 3], value)
    if max(b - a for a, b in zip(lo, hi)) <= 0:
        raise Problem('STL 包围盒退化')
    return {'triangles': count, 'min': lo, 'max': hi}


class Package:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.executable = self.root / 'bin/Solver-IBM.exe'
        self.verify()

    def verify(self):
        manifest = read_json(self.root / 'manifest.json')
        build = read_json(self.root / 'bin/build.json')
        entries = [f for f in manifest.get('files', []) if f['path'] == 'bin/Solver-IBM.exe']
        digest = sha(self.executable)
        if (manifest.get('product') != 'Solver-IBM' or manifest.get('version') != '2.0.0'
                or build.get('status') != 'succeeded' or build.get('productVersion') != '2.0.0'
                or build.get('productName') != 'Solver-IBM'
                or manifest.get('source_tree') != build.get('sourceTree')
                or len(entries) != 1 or digest != entries[0]['sha256']
                or digest != build.get('executableSha256')
                or self.executable.stat().st_size != entries[0]['bytes']):
            raise Problem('V2.0.0 正式包、构建身份与 EXE 校验值不一致', 503)
        self.identity = {'product': 'Solver-IBM', 'version': '2.0.0', 'sha256': digest,
                         'build_commit': build['gitCommit'], 'source_tree': build['sourceTree'],
                         'web_version': VERSION, 'web_base_commit': BASE_COMMIT}
        return self.identity


class Solver:
    """Only this class starts processes. Never instantiate it to run on a Mac."""
    def __init__(self, package):
        if os.name != 'nt':
            raise Problem('执行服务必须在 Windows 上运行；Mac 仅运行浏览器', 503)
        self.package = package
        result = subprocess.run([str(package.executable), '--version'], capture_output=True,
                                timeout=15, stdin=subprocess.DEVNULL)
        if result.returncode or result.stdout.decode('utf-8', 'replace').strip() != 'Solver-IBM 2.0.0':
            raise Problem('实际程序版本不是 Solver-IBM 2.0.0', 503)
        probe = package.root / 'source/scripts/get-opencl-devices.ps1'
        result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-ExecutionPolicy',
                                 'Bypass', '-File', str(probe)], capture_output=True, timeout=30,
                                stdin=subprocess.DEVNULL)
        if result.returncode:
            raise Problem('OpenCL 设备枚举失败：' + result.stderr.decode('utf-8', 'replace'), 503)
        self.devices = json.loads(result.stdout.decode('utf-8-sig'))
        if not isinstance(self.devices, list) or not self.devices:
            raise Problem('没有检测到 OpenCL 设备', 503)

    def execute(self, executable, args, directory, cancel, timeout, on_start):
        job, process = Job(), None
        out_path, err_path = directory / 'stdout.log', directory / 'stderr.log'
        started, outcome = time.monotonic(), None
        try:
            with out_path.open('wb') as out, err_path.open('wb') as err:
                process = subprocess.Popen([str(executable), *map(str, args)], cwd=directory,
                                           stdout=out, stderr=err, stdin=subprocess.DEVNULL,
                                           creationflags=subprocess.CREATE_NO_WINDOW)
                job.assign(process)
                on_start(process.pid)
                while process.poll() is None:
                    if cancel.wait(.15):
                        outcome = 'cancelled'
                        break
                    if time.monotonic() - started >= timeout:
                        outcome = 'timed_out'
                        break
                if outcome:
                    job.terminate()
                process.wait(timeout=15)
            return {'exit_code': process.returncode, 'outcome': outcome,
                    'stdout': tail(out_path), 'stderr': tail(err_path)}
        finally:
            job.close()  # terminates the owned process tree on every exceptional path
            if process is not None:
                process.wait(timeout=15)


def tail(path, maximum=32768):
    if not path.exists():
        return ''
    with path.open('rb') as stream:
        stream.seek(max(0, path.stat().st_size - maximum))
        return stream.read(maximum).decode('utf-8-sig', 'replace')


def parse_resolved(text):
    begin = text.find('{')
    if begin < 0:
        raise Problem('求解器未返回配置解析结果', 502)
    try:
        return json.JSONDecoder().raw_decode(text[begin:])[0]
    except ValueError as exc:
        raise Problem('无法解析求解器配置校验结果', 502) from exc


class Workbench:
    def __init__(self, root, package, runner):
        self.root = Path(root).resolve()
        if self.root.is_relative_to(package.root) or package.root.is_relative_to(self.root):
            raise Problem('工作台数据目录必须与不可变发布包分离')
        self.package, self.runner = package, runner
        self.lock = threading.RLock()
        self.operation = threading.Lock()
        self.active, self.cancel, self.worker = None, threading.Event(), None
        for folder in ['assets', 'runs', 'validation']:
            (self.root / folder).mkdir(parents=True, exist_ok=True)
        self.data_lock = (self.root / '.service.lock').open('a+b')
        self.data_lock.seek(0)
        if self.data_lock.read(1) == b'':
            self.data_lock.write(b'0')
            self.data_lock.flush()
        self.data_lock.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(self.data_lock.fileno(), msvcrt.LK_NBLCK, 1)
            else:  # Only used by isolated tests with a fake runner.
                import fcntl
                fcntl.flock(self.data_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            self.data_lock.close()
            raise Problem('此数据目录已有执行服务占用', 409) from exc
        self.draft_path = self.root / 'draft.json'
        if not self.draft_path.exists():
            default = read_json(WORKBENCH / 'default-case.json')
            source = WORKBENCH.parent / 'configs/assets/unit-cube-binary.stl'
            shutil.copyfile(source, self.root / 'assets/unit-cube-binary.stl')
            atomic_json(self.draft_path, {'revision': 1, 'config': default, 'refinement': None})
        for path in (self.root / 'runs').glob('*/run.json'):
            record = read_json(path)
            if record['status'] in ACTIVE:
                record.update(status='interrupted', completed_at=now(),
                              failure='执行服务已重启；旧任务不会自动续算。')
                atomic_json(path, record)

    def draft(self):
        with self.lock:
            return read_json(self.draft_path)

    def save_draft(self, payload):
        with self.lock:
            old = self.draft()
            if payload.get('revision') != old['revision']:
                raise Problem('服务端草稿已在另一个窗口更新，请先重新加载；本地修改仍保留。', 409)
            if not isinstance(payload.get('config'), dict):
                raise Problem('草稿 config 必须为 JSON 对象')
            result = {'revision': old['revision'] + 1, 'saved_at': now(),
                      'config': payload['config'], 'refinement': payload.get('refinement')}
            atomic_json(self.draft_path, result)
            return result

    def upload(self, filename, data):
        info = stl_info(data)
        name = re.sub(r'[^a-zA-Z0-9._-]', '-', filename.rsplit('/', 1)[-1]).strip('.')[:70]
        if not name.lower().endswith('.stl'):
            raise Problem('文件名必须以 .stl 结尾')
        digest = hashlib.sha256(data).hexdigest()
        relative = 'assets/' + digest[:20] + '-' + name[:-4] + '.stl'
        path = inside(self.root, relative)
        with self.lock:
            if not path.exists():
                with path.open('xb') as stream:
                    stream.write(data)
            elif sha(path) != digest:
                raise Problem('同名资源校验冲突', 409)
        return {'path': relative, 'sha256': digest, 'bytes': len(data), **info}

    def snapshot(self, config, folder):
        paths = asset_paths(config)
        for relative in paths:
            if not inside(self.root, relative).is_file():
                raise Problem('STL 资源尚未上传：' + relative)
        folder.mkdir(parents=True, exist_ok=False)
        (folder / 'assets').mkdir()
        assets = []
        for relative in paths:
            source = inside(self.root, relative)
            destination = inside(folder, relative)
            shutil.copyfile(source, destination)
            assets.append({'path': relative, 'sha256': sha(destination), 'bytes': destination.stat().st_size})
        atomic_json(folder / 'case.json', config)
        atomic_json(folder / 'inputs.json', {'config_sha256': sha(folder / 'case.json'), 'assets': assets})

    def validate(self, config):
        if not self.operation.acquire(blocking=False):
            raise Problem('已有任务正在校验或运行，请等待完成。', 409)
        folder = self.root / 'validation' / uuid.uuid4().hex
        try:
            self.package.verify()
            self.snapshot(config, folder)
            result = self.runner.execute(self.package.executable, ['--config', folder / 'case.json', '--validate'],
                                         folder, threading.Event(), 60, lambda pid: None)
            if result['exit_code'] or result['outcome']:
                raise Problem(result['stderr'] or result['stdout'] or '配置校验失败', 422)
            # Read full JSON rather than the bounded diagnostic tail.
            resolved = parse_resolved((folder / 'stdout.log').read_text(encoding='utf-8-sig'))
            return {'valid': True, 'resolved': resolved, 'solver': self.package.identity}
        finally:
            shutil.rmtree(folder, ignore_errors=True)
            self.operation.release()

    def submit(self, payload):
        config = copy.deepcopy(payload.get('config'))
        paths = asset_paths(config)
        for relative in paths:
            if not inside(self.root, relative).is_file():
                raise Problem('STL 资源尚未上传：' + relative)
        device, timeout = payload.get('device_id'), payload.get('timeout_seconds', 900)
        if type(device) is not int or device not in [d['id'] for d in self.runner.devices]:
            raise Problem('请选择当前 Windows 服务提供的 OpenCL 设备')
        if type(timeout) is not int or not 1 <= timeout <= 86400:
            raise Problem('任务超时必须在 1–86400 秒之间')
        if not self.operation.acquire(blocking=False):
            raise Problem('当前服务一次仅执行一个任务', 409)
        try:
            self.package.verify()
            ident = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ-') + uuid.uuid4().hex[:12]
            folder = self.root / 'runs' / ident
            folder.mkdir()
            self.snapshot(config, folder / 'inputs')
            (folder / 'runtime').mkdir()
            executable = folder / 'runtime/Solver-IBM.exe'
            shutil.copyfile(self.package.executable, executable)
            if sha(executable) != self.package.identity['sha256']:
                raise Problem('运行快照 SHA256 不一致', 503)
            shutil.copyfile(self.package.root / 'bin/build.json', folder / 'build.json')
            atomic_json(folder / 'refinement-draft.json', {'applied': False, 'draft': payload.get('refinement')})
            (folder / 'logs').mkdir()
            record = {'id': ident, 'case_name': config.get('case', {}).get('name', ''),
                      'status': 'validating', 'created_at': now(), 'completed_at': None,
                      'device_id': device, 'timeout_seconds': timeout,
                      'solver': dict(self.package.identity), 'process_id': None, 'exit_code': None,
                      'requested_steps': config['run'].get('steps'), 'failure': None,
                      'results_path': str(folder / 'results'), 'refinement_applied': False}
            atomic_json(folder / 'run.json', record)
            with self.lock:
                self.active, self.cancel = ident, threading.Event()
            self.worker = threading.Thread(target=self._run, args=(ident,), name='solver-run', daemon=False)
            self.worker.start()
            return record
        except BaseException:
            self.operation.release()
            raise

    def record_path(self, ident):
        if not re.fullmatch(r'\d{8}T\d{6}Z-[a-f0-9]{12}', ident):
            raise Problem('无效任务编号', 404)
        path = inside(self.root / 'runs', ident + '/run.json')
        if not path.is_file():
            raise Problem('任务不存在', 404)
        return path

    def record(self, ident):
        with self.lock:
            return read_json(self.record_path(ident))

    def update(self, ident, **values):
        with self.lock:
            path = self.record_path(ident)
            record = read_json(path)
            record.update(values)
            atomic_json(path, record)

    def _run(self, ident):
        folder = self.record_path(ident).parent
        executable = folder / 'runtime/Solver-IBM.exe'
        record = self.record(ident)
        try:
            validation = folder / 'logs/validation'
            validation.mkdir()
            result = self.runner.execute(executable, ['--config', folder / 'inputs/case.json', '--validate'],
                                         validation, self.cancel, 60,
                                         lambda pid: self.update(ident, process_id=pid))
            if result['outcome']:
                self.update(ident, status=result['outcome'], exit_code=result['exit_code'])
                return
            if result['exit_code']:
                self.update(ident, exit_code=result['exit_code'])
                raise Problem(result['stderr'] or result['stdout'] or '配置校验失败')
            resolved = parse_resolved((validation / 'stdout.log').read_text(encoding='utf-8-sig'))
            atomic_json(folder / 'validated-config.json', resolved)
            if self.cancel.is_set():
                self.update(ident, status='cancelled')
                return
            result = self.runner.execute(executable,
                                         ['--config', folder / 'inputs/case.json', '--device', str(record['device_id']),
                                          '--output', folder / 'results'], folder / 'logs', self.cancel,
                                         record['timeout_seconds'],
                                         lambda pid: self.update(ident, process_id=pid, status='running', started_at=now()))
            self.update(ident, exit_code=result['exit_code'])
            if result['outcome']:
                self.update(ident, status=result['outcome'], exit_code=result['exit_code'])
                return
            if result['exit_code']:
                self.update(ident, exit_code=result['exit_code'])
                raise Problem(result['stderr'] or result['stdout'] or '求解器运行失败')
            completion = read_json(folder / 'results/completion.json')
            if (completion.get('product') != 'Solver-IBM' or completion.get('status') != 'succeeded' or completion.get('version') != '2.0.0'
                    or completion.get('steps') != completion.get('requested_steps')):
                raise Problem('进程已退出，但 completion.json 未确认请求步数完成')
            for required in ['manifest.json', 'resolved-config.json', 'effective-config.json', 'monitor.csv']:
                if not (folder / 'results' / required).is_file():
                    raise Problem('缺少运行结果：' + required)
            self.update(ident, status='succeeded', exit_code=0, completion=completion,
                        requested_steps=completion['requested_steps'])
        except BaseException as exc:
            self.update(ident, status='failed', failure=str(exc))
        finally:
            self.update(ident, completed_at=now(), process_id=None)
            with self.lock:
                self.active = None
            self.operation.release()

    def stop(self, ident):
        with self.lock:
            record = self.record(ident)
            if ident != self.active or record['status'] not in ACTIVE:
                raise Problem('该任务已经结束，不能终止其他进程', 409)
            self.cancel.set()
            self.update(ident, status='cancelling')
            return self.record(ident)

    def jobs(self):
        with self.lock:
            paths = sorted((self.root / 'runs').glob('*/run.json'), reverse=True)[:200]
            return [read_json(path) for path in paths]

    def files(self, ident):
        folder = self.record_path(ident).parent
        result = []
        for path in folder.rglob('*'):
            relative = path.relative_to(folder).as_posix()
            if path.is_file() and not relative.startswith('runtime/'):
                inside(folder, relative)
                result.append({'path': relative, 'bytes': path.stat().st_size})
        return sorted(result, key=lambda f: f['path'])

    def logs(self, ident):
        folder = self.record_path(ident).parent / 'logs'
        return {name: tail(folder / relative) for name, relative in
                [('stdout', 'stdout.log'), ('stderr', 'stderr.log'),
                 ('validation', 'validation/stdout.log'), ('validation_error', 'validation/stderr.log')]}

    def series(self, ident, filename):
        if filename not in ['monitor.csv', 'probes.csv', 'analysis.csv', 'forces.csv', 'free-surface.csv',
                            'conservation-budget.csv', 'boundary-flux.csv', 'surface-levels.csv', 'object-motion.csv']:
            raise Problem('未知监测文件')
        path = self.record_path(ident).parent / 'results' / filename
        if not path.exists():
            return {'columns': [], 'rows': [], 'total_rows': 0}
        # Keep at most 32 MiB of recent data; incomplete trailing records are never parsed.
        with path.open('rb') as stream:
            header = stream.readline()
            size = path.stat().st_size
            clipped = size > 32 * 1024 * 1024
            if clipped:
                stream.seek(size - 32 * 1024 * 1024)
                stream.readline()
            data = stream.read(32 * 1024 * 1024)
        if not data.endswith(b'\n'):
            data = data.rsplit(b'\n', 1)[0] + b'\n' if b'\n' in data else b''
        reader = csv.DictReader(io.StringIO((header + data).decode('utf-8-sig', 'replace')))
        rows = []
        for row in reader:
            if None in row or any(v is None for v in row.values()):
                continue
            converted = {}
            for key, value in row.items():
                if key in ('id', 'geometry_id', 'boundary_id', 'boundary_type'):
                    converted[key] = value
                    continue
                try:
                    number = float(value)
                    converted[key] = number if math.isfinite(number) else None
                except ValueError:
                    converted[key] = value
            rows.append(converted)
        total = len(rows)
        # Sample each object independently so interleaved probes cannot disappear.
        groups = {}
        for row in rows:
            key = row.get('id', row.get('geometry_id', row.get('boundary_id', 'global')))
            groups.setdefault(key, []).append(row)
        quota = max(2, 4000 // max(1, len(groups)))
        sampled, stride = [], 1
        for group in groups.values():
            local_stride = max(1, math.ceil(len(group) / quota))
            stride = max(stride, local_stride)
            picked = group[::local_stride]
            if picked[-1] is not group[-1]:
                picked.append(group[-1])
            sampled.extend(picked)
        sampled.sort(key=lambda row: row.get('step', 0))
        return {'columns': reader.fieldnames or [], 'rows': sampled,
                'total_rows': total, 'clipped_to_recent': clipped, 'stride': stride}

    def shutdown(self):
        self.cancel.set()
        if self.worker is not None:
            self.worker.join(timeout=30)
        self.data_lock.close()
