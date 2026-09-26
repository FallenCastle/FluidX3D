"""Generate reproducible Cartesian studies; execute sequentially through run-nuc.ps1."""
import argparse
import copy
import csv
import datetime
import hashlib
import itertools
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import uuid


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda: f.read(1024 * 1024), b''):
            h.update(b)
    return h.hexdigest()


def read(path):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError(f'Duplicate key: {key}')
            result[key] = value
        return result
    return json.loads(path.read_text(encoding='utf-8-sig'), object_pairs_hook=pairs,
                      parse_constant=lambda x: (_ for _ in ()).throw(ValueError(x)))


def write(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False), encoding='utf-8')


def tokens(pointer):
    if not isinstance(pointer, str) or not pointer.startswith('/') or re.search(r'~(?![01])', pointer):
        raise ValueError(f'Invalid JSON Pointer: {pointer}')
    return [x.replace('~1', '/').replace('~0', '~') for x in pointer[1:].split('/')]


def key(obj, token):
    if isinstance(obj, list):
        if not re.fullmatch(r'0|[1-9][0-9]*', token) or int(token) >= len(obj):
            raise ValueError(f'Invalid array index: {token}')
        return int(token)
    if not isinstance(obj, dict) or token not in obj:
        raise ValueError(f'Parameter path does not exist: {token}')
    return token


def replace(obj, path, value):
    for token in path[:-1]:
        obj = obj[key(obj, token)]
    obj[key(obj, path[-1])] = copy.deepcopy(value)


def generate(args):
    spec_path = args.spec.resolve()
    spec = read(spec_path)
    if set(spec) != {'schema_version', 'base_config', 'parameters'} or type(spec['schema_version']) is not int or spec['schema_version'] != 1:
        raise ValueError('Study requires schema_version=1, base_config and parameters only')
    base_path = (spec_path.parent / spec['base_config']).resolve()
    base = read(base_path)
    axes = spec['parameters']
    if not isinstance(axes, list) or not axes:
        raise ValueError('Nonempty parameter axes required')
    paths = []
    for axis in axes:
        if set(axis) != {'path', 'values'} or not isinstance(axis['values'], list) or not axis['values']:
            raise ValueError('Each axis requires path and nonempty values')
        path = tokens(axis['path'])
        # Asset substitution would change the meaning of these paths.
        if path[0] in ('schema_version',) or path[0] == 'geometry' and (len(path) < 3 or path[2] in ('file', 'id')):
            raise ValueError('Scan geometry transforms, not asset paths/IDs or schema_version')
        if any(path[:len(p)] == p or p[:len(path)] == path for p in paths):
            raise ValueError('Duplicate or overlapping parameter paths')
        replace(copy.deepcopy(base), path, axis['values'][0])
        paths.append(path)
    combinations = math.prod(len(axis['values']) for axis in axes)
    if combinations > 10000:
        raise ValueError('Study exceeds 10000 combinations')
    root = args.output.resolve()
    if root.exists() and (not root.is_dir() or any(root.iterdir())):
        raise ValueError('Study output must be empty')
    root.mkdir(parents=True, exist_ok=True)
    (root / 'configs').mkdir()
    (root / 'assets').mkdir()
    shutil.copyfile(spec_path, root / 'study-original.json')
    shutil.copyfile(base_path, root / 'base-original.json')
    for i, g in enumerate(base['geometry']):
        asset = (base_path.parent / g['file']).resolve()
        dest = root / 'assets' / f'{i:04d}.stl'
        shutil.copyfile(asset, dest)
        g['file'] = f'../assets/{dest.name}'
    manifest = {'schema_version': 1, 'cases': [], 'files': {}}
    for i, values in enumerate(itertools.product(*(a['values'] for a in axes))):
        config = copy.deepcopy(base)
        for path, value in zip(paths, values):
            replace(config, path, value)
        name = f'{i:05d}'
        rel = f'configs/{name}.json'
        write(root / rel, config)
        manifest['cases'].append({'id': name, 'config': rel,
                                 'parameters': {a['path']: v for a, v in zip(axes, values)}})
    for file in sorted(root.rglob('*')):
        if file.is_file():
            manifest['files'][file.relative_to(root).as_posix()] = sha(file)
    write(root / 'study.json', manifest)
    print(root / 'study.json')
    return 0


def run(args):
    if os.name != 'nt':
        raise ValueError('Execute studies on the Windows NUC only')
    root = args.study.resolve()
    manifest = read(root / 'study.json')
    for rel, expected in manifest['files'].items():
        path = (root / rel).resolve()
        if not path.is_relative_to(root) or sha(path) != expected:
            raise ValueError(f'Study snapshot mismatch: {rel}')
    workspace = args.workspace_root.resolve()
    exe = (args.executable or workspace / 'bin' / args.build_name / 'Solver-IBM.exe').resolve()
    expected = sha(exe)
    build = read(exe.parent / 'build.json')
    if expected != build['executableSha256']:
        raise ValueError('Build executable hash mismatch')
    run_id = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid.uuid4().hex[:8]
    output = root / 'runs' / run_id
    output.mkdir(parents=True)
    report = {'status': 'running', 'build': build, 'study_sha256': sha(root / 'study.json'), 'cases': []}
    script = Path(__file__).with_name('run-nuc.ps1')
    for item in manifest['cases']:
        row = dict(item, status='failed', run_directory=None, results=None, steps=None, elapsed_seconds=None)
        name = 'study-' + run_id + '-' + item['id']
        try:
            if sha(exe) != expected:
                raise ValueError('Build changed during study')
            config = (root / item['config']).resolve()
            if not config.is_relative_to(root) or item['config'] not in manifest['files'] or sha(config) != manifest['files'][item['config']]:
                raise ValueError('Config snapshot mismatch')
            command = ['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(script),
                       '-WorkspaceRoot', str(workspace), '-BuildName', args.build_name, '-ExecutablePath', str(exe), '-CaseName', name,
                       '-ConfigPath', str(config), '-DeviceId', str(args.device), '-TimeoutSeconds', str(args.timeout)]
            with (output / (item['id'] + '.log')).open('wb') as log:
                result = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT)
            runs = list((workspace / 'workingdir' / name).glob('*/run.json'))
            if len(runs) != 1:
                raise ValueError('Expected exactly one run manifest')
            record = read(runs[0])
            row.update(run_directory=str(runs[0].parent), results=record['paths']['results'],
                       elapsed_seconds=record['elapsedSeconds'], exit_code=result.returncode)
            if result.returncode != 0 or record['status'] != 'succeeded':
                raise ValueError(record.get('failureReason') or 'Solver failed')
            if record['build']['executableSha256'] != expected:
                raise ValueError('Run binary changed')
            row.update(status='succeeded', steps=record['validation']['completion']['steps'],
                       statistics=(str(Path(row['results']) / 'statistics.json')
                                   if (Path(row['results']) / 'statistics.json').is_file() else None))
        except Exception as error:
            row['error'] = str(error)
        report['cases'].append(row)
        write(output / 'summary.json', report)
    report['status'] = 'succeeded' if all(x['status'] == 'succeeded' for x in report['cases']) else 'failed'
    write(output / 'summary.json', report)
    columns = ['id', 'parameters', 'status', 'steps', 'elapsed_seconds', 'results', 'statistics', 'error']
    with (output / 'summary.csv').open('w', newline='', encoding='utf-8') as file:
        writer = csv.DictWriter(file, fieldnames=columns, extrasaction='ignore')
        writer.writeheader()
        for row in report['cases']:
            writer.writerow(dict(row, parameters=json.dumps(row['parameters'], ensure_ascii=False)))
    print(output / 'summary.json')
    return 0 if report['status'] == 'succeeded' else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    gen = commands.add_parser('generate')
    gen.add_argument('--spec', type=Path, required=True)
    gen.add_argument('--output', type=Path, required=True)
    exe = commands.add_parser('run')
    exe.add_argument('--study', type=Path, required=True)
    exe.add_argument('--workspace-root', type=Path, required=True)
    exe.add_argument('--build-name', default='solver-ibm-v1.0.0')
    exe.add_argument('--executable', type=Path, help='Relocated Solver-IBM.exe with adjacent build.json')
    exe.add_argument('--device', type=int, default=0)
    exe.add_argument('--timeout', type=int, default=900)
    args = parser.parse_args()
    try:
        return generate(args) if args.command == 'generate' else run(args)
    except Exception as error:
        print(f'Error: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
