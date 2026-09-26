"""Assemble and seal a versioned Solver-IBM release on Windows NUC (standard library)."""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import tempfile


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def git(repo, *args):
    return subprocess.check_output(['git', '-C', str(repo), *args], text=True, encoding='utf-8').strip()


def copy_file(source, target):
    if not source.is_file():
        raise ValueError(f'Required file missing: {source}')
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    if sha(source) != sha(target):
        raise ValueError(f'Copy changed bytes: {source}')


def copy_tree(source, target):
    if not source.is_dir():
        raise ValueError(f'Required directory missing: {source}')
    for path in sorted(source.rglob('*')):
        if path.is_file() and path.name not in ('.DS_Store',) and '__pycache__' not in path.parts:
            copy_file(path, target / path.relative_to(source))


def version(repo):
    header = (repo / 'src' / 'version.hpp').read_text(encoding='utf-8')
    values = [re.search(r'^#define\s+SOLVER_IBM_VERSION_' + part + r'\s+(\d+)\s*$', header, re.M)
              for part in ('MAJOR', 'MINOR', 'PATCH')]
    if not all(values):
        raise ValueError('Missing authoritative numeric version definitions')
    return '.'.join(v.group(1) for v in values)


def list_files(root):
    return [{'path': p.relative_to(root).as_posix(), 'bytes': p.stat().st_size, 'sha256': sha(p)}
            for p in sorted(root.rglob('*')) if p.is_file() and p != root / 'manifest.json']


def refresh(root, manifest):
    manifest['files'] = list_files(root)
    manifest['file_count'] = len(manifest['files'])
    manifest['total_bytes'] = sum(f['bytes'] for f in manifest['files'])
    write(root / 'manifest.json', manifest)


def check(root):
    manifest = read(root / 'manifest.json')
    actual = {x['path']: x for x in list_files(root)}
    expected = {x['path']: x for x in manifest['files']}
    if len(expected) != len(manifest['files']) or actual != expected:
        raise ValueError('Package inventory/hash/size mismatch')
    return manifest


def archive_source(repo, root, commit):
    # Keep the tracked snapshot untouched; the bundle supplies Git history for rebuilding.
    with tempfile.TemporaryDirectory(prefix='solver-ibm-archive-') as temp:
        archive = Path(temp) / 'source.tar'
        subprocess.run(['git', '-C', str(repo), 'archive', '--format=tar', '-o', str(archive), commit], check=True)
        source = root / 'source'
        source.mkdir()
        with tarfile.open(archive) as tar:
            for member in tar.getmembers():
                target = (source / member.name).resolve()
                if not target.is_relative_to(source.resolve()) or member.issym() or member.islnk():
                    raise ValueError(f'Unsafe source archive member: {member.name}')
            tar.extractall(source)
    subprocess.run(['git', '-C', str(repo), 'bundle', 'create', str(root / 'source.git.bundle'), '--all'], check=True)
    subprocess.run(['git', '-C', str(repo), 'bundle', 'verify', str(root / 'source.git.bundle')], check=True,
                   stdout=subprocess.DEVNULL)


def examples(repo, workspace, root):
    catalog_root = workspace / 'workingdir' / '_case-assets'
    catalog = read(catalog_root / 'catalog.json')
    names = [c['case'] for c in catalog['cases']]
    for name in names:
        copy_tree(workspace / 'workingdir' / name / 'assets', root / 'cases' / 'models' / name)
    for name in ('catalog.json', 'inventory.json', 'README.md', 'transfer-manifest.json'):
        copy_file(catalog_root / name, root / 'cases' / 'models' / name)
    # Verify the retained external input set against the prior transfer hashes.
    transfers = read(catalog_root / 'transfer-manifest.json')
    for item in transfers['files']:
        parts = Path(item['path']).parts
        if len(parts) > 2 and parts[1] == 'assets':
            target = root / 'cases' / 'models' / parts[0] / Path(*parts[2:])
            if sha(target) != item['sha256']:
                raise ValueError(f'External model differs from recorded source: {item["path"]}')
    rewritten = []
    for source in sorted((repo / 'configs').glob('*.json')):
        target = root / 'cases' / 'configs' / source.name
        config = read(source)
        for geometry in config.get('geometry', []):
            original = (source.parent / geometry['file']).resolve()
            relative = original.relative_to(workspace / 'workingdir')
            if len(relative.parts) < 3 or relative.parts[1] != 'assets':
                raise ValueError(f'Unmapped example geometry: {original}')
            model = root / 'cases' / 'models' / relative.parts[0] / Path(*relative.parts[2:])
            if sha(model) != sha(original):
                raise ValueError(f'Example model hash mismatch: {original}')
            geometry['file'] = Path(os.path.relpath(model, target.parent)).as_posix()
            rewritten.append({'config': source.name, 'original_path': str(original),
                              'package_path': geometry['file'], 'sha256': sha(model)})
        write(target, config)
    write(root / 'cases' / 'index.json', {
        'model_families': names, 'example_count': len(list((repo / 'configs').glob('*.json'))),
        'path_rewrites': rewritten,
        'note': 'Models include historical source assets and unfinished preparation; inclusion is not CFD acceptance.'})
    return names


def references(workspace, root, fp16):
    reference = root / 'tests' / 'reference'
    for build_name, target_name in [('config-runner', 'p1-build'), ('config-runner-p2', 'p2-build'),
                                    ('config-runner-p2-fp32-diagnostic', 'fp32-diagnostic-build')]:
        source = workspace / 'bin' / build_name
        build = read(source / 'build.json')
        exe = source / 'FluidX3D.exe'
        if sha(exe) != build['executableSha256']:
            raise ValueError(f'Historical binary hash mismatch: {exe}')
        for filename in ('FluidX3D.exe', 'build.json'):
            copy_file(source / filename, reference / target_name / filename)
    baseline_runs = sorted((workspace / 'workingdir' / 'config-baseline-boeing').glob('*/run.json'))
    if not baseline_runs:
        raise ValueError('Boeing baseline missing')
    baseline = baseline_runs[-1].parent
    if read(baseline / 'run.json')['status'] != 'succeeded':
        raise ValueError('Boeing baseline was not successful')
    copy_file(baseline / 'run.json', reference / 'boeing-baseline' / 'run.json')
    for step in (0, 1000):
        for field in ('rho', 'u', 'flags'):
            filename = f'{field}-{step:09d}.vtk'
            copy_file(baseline / 'results' / filename, reference / 'boeing-baseline' / 'results' / filename)
    copy_file(fp16 / 'report.json', reference / 'fp16-reference' / 'report.json')
    # This one small result set is required for fixed-FP16 regression, including snapshot STL.
    copy_tree(fp16 / 'geometry-force', reference / 'fp16-reference' / 'geometry-force')
    write(reference / 'README.json', {'purpose': 'Historical comparison only; names and bytes unchanged.',
        'boeing_source': str(baseline), 'fixed_fp16_source': str(fp16),
        'vtk_policy': 'Only required Boeing and fixed-FP16 reference fields are retained.'})


def historical_inputs(workspace, root):
    # Preserve invalid/duplicate-key JSON byte-for-byte. Never parse-and-rewrite evidence.
    work = workspace / 'workingdir'
    omitted = {'resolved-config.json', 'completion.json', 'manifest.json', 'statistics.json'}
    records = []
    reports = []
    for directory, dirs, files in os.walk(work, followlinks=False):
        relative_dir = Path(directory).relative_to(work)
        dirs[:] = [d for d in dirs if d not in ('bin', 'temp', '__pycache__', '.git')
                   and not (len(relative_dir.parts) == 1 and d == 'assets')
                   and not (not relative_dir.parts and d in ('_builds', '_case-assets'))]
        for name in sorted(files):
            source = Path(directory) / name
            relative = source.relative_to(work)
            if source.suffix.lower() == '.stl' or (source.suffix.lower() == '.json' and name not in omitted):
                is_report = name in ('report.json', 'summary.json', 'baseline-comparison.json', 'run.json', 'build.json')
                category = 'reports/history' if is_report else 'historical-inputs'
                target = root / 'tests' / category / relative
                copy_file(source, target)
                row = {'source': str(source), 'path': target.relative_to(root).as_posix(), 'sha256': sha(target)}
                (reports if is_report else records).append(row)
    write(root / 'tests' / 'historical-inputs' / 'index.json', {
        'note': 'Byte-exact historical inputs, including intended errors and original absolute paths. '
                'Use packaged test scripts to regenerate portable validation; use cases/configs for direct runs.',
        'files': records})
    write(root / 'tests' / 'reports' / 'history-index.json', {'files': reports})
    return len(records), len(reports)


def create(args):
    repo = args.repository_root.resolve()
    workspace = args.workspace_root.resolve()
    root = args.output.resolve()
    if root.exists():
        raise ValueError('Candidate directory already exists; never overwrite a release or candidate')
    if git(repo, 'status', '--porcelain', '--untracked-files=all'):
        raise ValueError('Commit and synchronize source before packaging')
    ver = version(repo)
    build_dir = workspace / 'bin' / args.build_name
    build = read(build_dir / 'build.json')
    binary = build_dir / 'Solver-IBM.exe'
    commit = git(repo, 'rev-parse', 'HEAD')
    source_tree = git(repo, 'rev-parse', 'HEAD:src')
    if build['status'] != 'succeeded' or sha(binary) != build['executableSha256'] or build['sourceTree'] != source_tree:
        raise ValueError('Source tree / successful build / binary hash do not agree')
    if build['projectBlob'] != git(repo, 'rev-parse', 'HEAD:FluidX3D.vcxproj'):
        raise ValueError('Build project differs from packaged source project')
    identity = subprocess.check_output([str(binary), '--version'], text=True).strip()
    if identity != 'Solver-IBM ' + ver:
        raise ValueError('Binary version differs from source')
    root.mkdir(parents=True)
    archive_source(repo, root, commit)
    for name in ('Solver-IBM.exe', 'build.json'):
        copy_file(build_dir / name, root / 'bin' / name)
    copy_tree(repo / 'docs', root / 'docs')
    # Current package documentation links point at source/ and portable case copies.
    for doc in (root / 'docs').rglob('*.md'):
        value = doc.read_text(encoding='utf-8')
        if doc.parent == root / 'docs':
            for old, new in (('../src/', '../source/src/'), ('../scripts/', '../source/scripts/'),
                             ('../configs/', '../cases/configs/'), ('../schemas/', '../source/schemas/')):
                value = value.replace('](' + old, '](' + new)
            doc.write_text(value, encoding='utf-8')
    copy_tree(repo / 'scripts', root / 'tests' / 'scripts')
    for name in ('run-package.ps1', 'test-package.py', 'package-release.py'):
        copy_file(repo / 'scripts' / name, root / name)
    copy_file(repo / 'LICENSE.md', root / 'LICENSE.md')
    copy_file(workspace / 'AGENTS.md', root / 'docs' / 'AGENTS-release-snapshot.md')
    build_evidence = Path(build['buildLog']).parent
    copy_tree(build_evidence, root / 'tests' / 'reports' / 'build')
    names = examples(repo, workspace, root)
    references(workspace, root, args.fp16_reference.resolve())
    inputs, reports = historical_inputs(workspace, root)
    if args.additional_evidence:
        copy_tree(args.additional_evidence.resolve(), root / 'tests' / 'reports' / 'supplementary')
    (root / 'README.md').write_text(
        '# Solver-IBM V' + ver + '\n\n'
        '使用说明见 [用户手册](docs/user-manual-zh.md)，交接见 [交接文档](docs/handoff-v' + ver + '.md)。\n\n'
        '当前程序为 `bin/Solver-IBM.exe`。算例从 `cases/configs/` 选择；通过 `run-package.ps1` '
        '指定 PackageRoot 和包外 WorkspaceRoot 运行。正式目录不保存计算输出。\n\n'
        '`source/` 是原样 Git 源码快照；需要构建时，在包外执行 `git clone source.git.bundle <新目录>`，'
        '然后 checkout `manifest.json` 中的 source_commit，再运行其中 scripts/build-nuc.ps1。'
        '归档中的源码模板保留原路径，直接运行请用 cases/configs 中的便携副本。\n\n'
        'tests/reference 保留必要旧版 EXE 和基准 VTK；tests/historical-inputs 保留原始错误输入及历史路径，'
        '不能全部当作正常示例运行。' + str(len(names)) + ' 类外部模型包括未完成制备的素材，不代表均已通过 CFD 验收。\n\n'
        '完整性检查：`python package-release.py verify --package-root <本目录>`。'
        '完整复验：`python test-package.py --package-root <本目录> --workspace-root <包外目录> --device <OpenCL编号>`。\n',
        encoding='utf-8')
    manifest = {'schema_version': 1, 'product': 'Solver-IBM', 'version': ver, 'status': 'candidate',
                'release_tag': 'v' + ver, 'source_commit': commit, 'source_tree': source_tree,
                'build': build, 'created_at_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
                'inventory': {'model_families': len(names), 'historical_input_files': inputs,
                              'historical_report_files': reports},
                'policy': 'Full source, inputs, scripts and reports; only necessary reference VTK. No historical bulk fields.'}
    refresh(root, manifest)
    check(root)
    print(json.dumps({'package': str(root), 'files': manifest['file_count'], 'bytes': manifest['total_bytes']}, indent=2))


def seal(args):
    root = args.package_root.resolve()
    manifest = check(root)
    if manifest['status'] != 'candidate':
        raise ValueError('Only candidates may be sealed')
    verification = read(args.verification)
    suites = read(args.suite_evidence)
    for evidence in (verification, suites):
        if evidence['status'] != 'succeeded' or evidence['executable_sha256'] != manifest['build']['executableSha256']:
            raise ValueError('Successful verification for the exact binary is required')
        for path, expected in evidence['verification_inputs'].items():
            if sha(root / path) != expected:
                raise ValueError(f'Acceptance input changed: {path}')
    if suites.get('suites_skipped', True) or len(suites.get('suites', [])) != 5:
        raise ValueError('All five acceptance suites must have executed')
    if {s['name'] for s in suites['suites']} != {'p1', 'p2', 'p3', 'storage', 'study'}:
        raise ValueError('Acceptance suite names are incomplete')
    for result in suites['suites']:
        report = Path(result['report'])
        if result['status'] != 'succeeded' or result['exit_code'] != 0 or sha(report) != result['report_sha256']:
            raise ValueError(f'Failed or altered suite evidence: {result["name"]}')
        target = root / 'tests' / 'reports' / 'release' / 'suites' / result['name']
        copy_file(report, target / 'report.json')
        comparison = report.parent / 'baseline-comparison.json'
        if comparison.is_file():
            copy_file(comparison, target / comparison.name)
    repo = args.repository_root.resolve()
    if git(repo, 'rev-parse', manifest['release_tag'] + '^{commit}') != manifest['source_commit']:
        raise ValueError('Release tag must identify the packaged source commit')
    destination = args.destination.resolve()
    if destination.name != 'V' + manifest['version'] or destination.exists():
        raise ValueError('Destination must be a new V<version> directory')
    copy_file(args.verification, root / 'tests' / 'reports' / 'release' / 'package-verification.json')
    copy_file(args.suite_evidence, root / 'tests' / 'reports' / 'release' / 'full-acceptance.json')
    # Candidate bundles predate the formal tag; regenerate only after that tag is verified.
    subprocess.run(['git', '-C', str(repo), 'bundle', 'create', str(root / 'source.git.bundle'), '--all'], check=True)
    subprocess.run(['git', '-C', str(repo), 'bundle', 'verify', str(root / 'source.git.bundle')],
                   check=True, stdout=subprocess.DEVNULL)
    manifest['status'] = 'released'
    manifest['released_at_utc'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    refresh(root, manifest)
    check(root)
    root.rename(destination)
    print(json.dumps({'released': str(destination), 'manifest_sha256': sha(destination / 'manifest.json'),
                      'files': manifest['file_count'], 'bytes': manifest['total_bytes']}, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    create_parser = sub.add_parser('create')
    create_parser.add_argument('--repository-root', type=Path, required=True)
    create_parser.add_argument('--workspace-root', type=Path, required=True)
    create_parser.add_argument('--output', type=Path, required=True)
    create_parser.add_argument('--build-name', default='solver-ibm-v1.0.0')
    create_parser.add_argument('--fp16-reference', type=Path, required=True)
    create_parser.add_argument('--additional-evidence', type=Path)
    verify_parser = sub.add_parser('verify')
    verify_parser.add_argument('--package-root', type=Path, required=True)
    seal_parser = sub.add_parser('seal')
    for name in ('package-root', 'repository-root', 'verification', 'suite-evidence', 'destination'):
        seal_parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    if os.name != 'nt' and args.command != 'verify':
        parser.error('Create and seal releases on Windows NUC only')
    if args.command == 'create':
        create(args)
    elif args.command == 'seal':
        seal(args)
    else:
        manifest = check(args.package_root.resolve())
        print(f"Verified {manifest['product']} {manifest['version']}: {manifest['file_count']} files")


if __name__ == '__main__':
    main()
