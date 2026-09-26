"""Verify an immutable Solver-IBM release package and run NUC-only acceptance."""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
import time

sys.dont_write_bytecode = True

SUITES = [
    ('p1', 'test-config-runner.py', 'config-validation', True),
    ('p2', 'test-config-p2.py', 'p2-validation', False),
    ('storage', 'test-runtime-storage.py', 'storage-validation', True),
    ('p3', 'test-config-p3.py', 'p3-validation', True),
    ('study', 'test-parameter-study.py', 'study-validation', False),
]


def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def write(path, value):
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + '\n', encoding='utf-8')
    temporary.replace(path)


def sha(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def inside(path, parent):
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def verify_inventory(package):
    manifest = read(package / 'manifest.json')
    require(manifest['schema_version'] == 1 and manifest['product'] == 'Solver-IBM', 'Unsupported release manifest')
    require(re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+', manifest['version']), 'Invalid release version')
    require(manifest['release_tag'] == 'v' + manifest['version'], 'Release tag/version mismatch')
    require(re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}', manifest['source_commit']), 'Invalid source commit')
    expected, folded = {}, set()
    for entry in manifest['files']:
        name = entry['path']
        require(isinstance(name, str) and name and '\\' not in name and ':' not in name,
                f'Invalid package path: {name!r}')
        path = PurePosixPath(name)
        require(not path.is_absolute() and str(path) == name and '..' not in path.parts and name != 'manifest.json',
                f'Unsafe or noncanonical package path: {name}')
        require(name.casefold() not in folded, f'Duplicate package path: {name}')
        require(type(entry['bytes']) is int and entry['bytes'] >= 0 and
                re.fullmatch(r'[0-9a-f]{64}', entry['sha256']), f'Invalid inventory entry: {name}')
        folded.add(name.casefold())
        expected[name] = entry
    actual = {}
    for path in package.rglob('*'):
        require(not path.is_symlink() and not bool(getattr(path.lstat(), 'st_file_attributes', 0) & 0x400),
                f'Package contains a symlink or reparse point: {path}')
        if path.is_file():
            name = path.relative_to(package).as_posix()
            if name != 'manifest.json':
                actual[name] = path
    require(set(actual) == set(expected), 'Inventory mismatch: missing=' + str(sorted(set(expected) - set(actual))) +
            '; unexpected=' + str(sorted(set(actual) - set(expected))))
    total = 0
    for name, entry in expected.items():
        path = actual[name]
        require(path.stat().st_size == entry['bytes'] and sha(path) == entry['sha256'], 'File differs: ' + name)
        total += entry['bytes']
    require(manifest['file_count'] == len(expected) and manifest['total_bytes'] == total,
            'Manifest file_count/total_bytes does not match the file inventory')
    fingerprint = {'manifest.json': sha(package / 'manifest.json')}
    fingerprint.update({name: entry['sha256'] for name, entry in expected.items()})
    return manifest, fingerprint, total


def identity(package, manifest, report_root):
    exe = package / 'bin' / 'Solver-IBM.exe'
    build = read(exe.parent / 'build.json')
    require(build == manifest['build'], 'Packaged build.json differs from manifest.build')
    require(build['status'] == 'succeeded' and build['schemaVersion'] == 1, 'Build was not successful')
    require(build['productName'] == manifest['product'] and build['productVersion'] == manifest['version'],
            'Build product/version mismatch')
    require(build['sourceTree'] == manifest['source_tree'], 'Numerical source tree mismatch')
    require(sha(exe) == build['executableSha256'], 'Executable differs from verified build')
    header = (package / 'source' / 'src' / 'version.hpp').read_text(encoding='utf-8')
    parts = [re.search(r'^#define SOLVER_IBM_VERSION_' + part + r' ([0-9]+)$', header, re.M).group(1)
             for part in ('MAJOR', 'MINOR', 'PATCH')]
    require('.'.join(parts) == manifest['version'] and '#define SOLVER_IBM_NAME "Solver-IBM"' in header,
            'Source release version differs from manifest')
    version = subprocess.check_output([str(exe), '--version'], cwd=report_root, timeout=60).decode('utf-8').strip()
    require(version == manifest['product'] + ' ' + manifest['version'], 'Executable --version mismatch')
    capabilities = json.loads(subprocess.check_output([str(exe), '--capabilities'], cwd=report_root, timeout=60))
    require(capabilities['product'] == manifest['product'] and capabilities['version'] == manifest['version'],
            'Executable capabilities identity mismatch')
    return build, capabilities


def execute(command, log, cwd, timeout=None):
    print('RUN ' + subprocess.list2cmdline([str(x) for x in command]), flush=True)
    start = time.monotonic()
    with log.open('wb') as output:
        with subprocess.Popen([str(x) for x in command], cwd=cwd, stdout=output, stderr=subprocess.STDOUT,
                              env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1', PYTHONUNBUFFERED='1')) as process:
            while True:
                remaining = None if timeout is None else timeout - (time.monotonic() - start)
                if remaining is not None and remaining <= 0:
                    process.kill()
                    process.wait()
                    raise subprocess.TimeoutExpired(command, timeout)
                try:
                    code = process.wait(timeout=30 if remaining is None else min(30, remaining))
                    break
                except subprocess.TimeoutExpired:
                    print(f'RUNNING {log.name}: {time.monotonic() - start:.0f}s; progress log: {log}', flush=True)
    return {'command': [str(x) for x in command], 'exit_code': code,
            'elapsed_seconds': round(time.monotonic() - start, 3), 'log': str(log)}


def smoke(package, root, device, manifest, prepare):
    name = 'wrapper-prepare' if prepare else 'wrapper-run'
    workspace = root / name
    workspace.mkdir()
    command = ['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File',
               package / 'source' / 'scripts' / 'run-package.ps1', '-PackageRoot', package,
               '-WorkspaceRoot', workspace, '-CaseName', name, '-DeviceId', device]
    if prepare:
        command += ['-ConfigPath', package / 'cases' / 'configs' / 'ahmed-smoke.json', '-PrepareOnly']
    invocation = execute(command, root / (name + '.log'), workspace, timeout=960)
    require(invocation['exit_code'] == 0, f'{name} failed; inspect {invocation["log"]}')
    records = list((workspace / 'workingdir' / name).glob('*/run.json'))
    require(len(records) == 1, f'{name}: expected one isolated run record')
    record = read(records[0])
    require(record['status'] == 'succeeded' and record['exitCode'] == 0, f'{name}: run failed')
    require(record['build']['executableSha256'] == manifest['build']['executableSha256'], f'{name}: wrong executable')
    results = Path(record['paths']['results'])
    require(not inside(results, package), 'Wrapper wrote results into the package')
    completion = read(results / 'completion.json')
    require(completion['status'] == ('prepared' if prepare else 'succeeded'), f'{name}: completion mismatch')
    require(completion['steps'] == (0 if prepare else completion['requested_steps']), f'{name}: steps mismatch')
    for filename in ('completion.json', 'resolved-config.json', 'manifest.json'):
        metadata = read(results / filename)
        require(metadata['product'] == manifest['product'] and metadata['version'] == manifest['version'],
                f'{name}: {filename} identity mismatch')
    if prepare:
        require(read(results / 'resolved-config.json')['solid_cells'] > 0, 'Prepared STL contains no solid cells')
    invocation.update(status='succeeded', run_record=str(records[0]), run_record_sha256=sha(records[0]),
                      results=str(results))
    return invocation


def suite(package, root, device, spec):
    name, filename, category, needs_reference = spec
    workspace = root / ('suite-' + name)
    workspace.mkdir()
    command = [sys.executable, '-B', package / 'source' / 'scripts' / filename,
               '--workspace-root', workspace, '--repository-root', package / 'source',
               '--configs-root', package / 'cases' / 'configs', '--executable', package / 'bin' / 'Solver-IBM.exe',
               '--device', device]
    if needs_reference:
        command += ['--reference-root', package / 'tests' / 'reference']
    invocation = execute(command, root / ('suite-' + name + '.log'), workspace)
    reports = list((workspace / 'workingdir' / category).glob('*/report.json'))
    invocation['name'] = name
    require(len(reports) == 1, f'{name}: expected one suite report; inspect {invocation["log"]}')
    report = read(reports[0])
    invocation.update(status=report['status'], report=str(reports[0]), report_sha256=sha(reports[0]),
                      counts={key: len(report[key]) for key in
                              ('tests', 'checks', 'profiles', 'matrix', 'comparisons', 'allocations', 'performance')
                              if isinstance(report.get(key), list)})
    if isinstance(report.get('batch'), dict):
        invocation['counts']['batch_cases'] = len(report['batch'].get('cases', []))
    print(('PASS ' if invocation['exit_code'] == 0 and report['status'] == 'succeeded' else 'FAIL ') +
          name + ' ' + json.dumps(invocation['counts']), flush=True)
    return invocation


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package-root', required=True, type=Path)
    parser.add_argument('--workspace-root', required=True, type=Path)
    parser.add_argument('--device', default='0')
    parser.add_argument('--skip-suites', action='store_true',
                        help='Verify inventory/identity and run two wrapper checks; explicitly skip all numerical suites')
    args = parser.parse_args()
    if os.name != 'nt':
        parser.error('Execute package acceptance on the Windows NUC only')
    if not re.fullmatch(r'[0-9]+', args.device) or int(args.device) > 2147483647:
        parser.error('--device must be an integer in 0..2147483647')
    package, workspace = args.package_root.resolve(), args.workspace_root.resolve()
    if any(inside(path, package) for path in
           (workspace, workspace / 'workingdir', workspace / 'workingdir' / 'package-validation')):
        parser.error('--workspace-root and generated outputs must stay outside the immutable package')
    timestamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    root = workspace / 'workingdir' / 'package-validation' / timestamp
    root.mkdir(parents=True, exist_ok=False)
    report_path = root / 'report.json'
    report = {'status': 'running', 'package_root': str(package), 'workspace_root': str(workspace),
              'started_at_utc': timestamp, 'device': args.device, 'suites': [], 'wrapper_checks': [],
              'suites_skipped': args.skip_suites,
              'suite_status': 'skipped' if args.skip_suites else 'pending',
              'skipped_suites': [s[0] for s in SUITES] if args.skip_suites else []}
    before = None
    print('Package acceptance report: ' + str(report_path), flush=True)
    write(report_path, report)
    try:
        manifest, before, total = verify_inventory(package)
        report.update(product=manifest['product'], version=manifest['version'], source_commit=manifest['source_commit'],
                      source_tree=manifest['source_tree'], executable_sha256=manifest['build']['executableSha256'],
                      inventory_files=len(before) - 1, inventory_bytes=total, manifest_sha256=before['manifest.json'],
                      verification_inputs={name: digest for name, digest in before.items() if
                                           name.startswith(('source/src/', 'source/scripts/', 'cases/', 'tests/reference/'))})
        print(f'PASS inventory: {len(before) - 1} files, {total} bytes', flush=True)
        _, report['capabilities'] = identity(package, manifest, root)
        write(report_path, report)
        for prepare in (False, True):
            report['wrapper_checks'].append(smoke(package, root, args.device, manifest, prepare))
            write(report_path, report)
        if not args.skip_suites:
            report['suite_status'] = 'running'
            for spec in SUITES:
                result = suite(package, root, args.device, spec)
                report['suites'].append(result)
                write(report_path, report)
                require(result['exit_code'] == 0 and result['status'] == 'succeeded',
                        f'{spec[0]}: acceptance failed; inspect {result["report"]}')
            report['suite_status'] = 'succeeded'
        report['status'] = 'succeeded'
    except Exception as error:
        report['status'] = 'failed'
        if report['suite_status'] == 'running':
            report['suite_status'] = 'failed'
        report['error'] = repr(error)
        print('FAIL ' + repr(error), flush=True)
    finally:
        if before is not None:
            try:
                _, after, _ = verify_inventory(package)
                require(after == before, 'Package contents changed during acceptance')
                report['package_unchanged'] = True
            except Exception as error:
                report['status'] = 'failed'
                report['package_unchanged'] = False
                report['integrity_error'] = repr(error)
        report['completed_at_utc'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        write(report_path, report)
        print('Package acceptance ' + report['status'] + ': ' + str(report_path), flush=True)
    return 0 if report['status'] == 'succeeded' else 1


if __name__ == '__main__':
    sys.exit(main())
