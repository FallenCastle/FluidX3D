"""NUC acceptance of one executable's FP16S/FP32 paths and retained baselines."""
import argparse
import copy
import datetime
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import subprocess
import sys

sys.dont_write_bytecode = True
_spec = importlib.util.spec_from_file_location('p1', Path(__file__).with_name('test-config-runner.py'))
p1 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(p1)


def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def write(path, data):
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding='utf-8')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--workspace-root', type=Path, required=True)
    parser.add_argument('--build-name', default='solver-ibm-v1.0.0')
    parser.add_argument('--diagnostic-build', default='config-runner-p2-fp32-diagnostic')
    parser.add_argument('--reference-root', type=Path, help='Reference bundle containing fp16-reference and fp32-diagnostic-build')
    parser.add_argument('--fp16-reference', type=Path,
                        help='Retained fixed-FP16 P2 validation directory containing geometry-force')
    parser.add_argument('--repository-root', type=Path)
    parser.add_argument('--configs-root', type=Path)
    parser.add_argument('--executable', type=Path)
    parser.add_argument('--device', default='0')
    args = parser.parse_args()
    if os.name != 'nt':
        parser.error('Run on Windows NUC only')
    if args.reference_root:
        args.reference_root = args.reference_root.resolve()
        if args.fp16_reference is None:
            args.fp16_reference = args.reference_root/'fp16-reference'
    if args.fp16_reference is None:
        parser.error('Provide --reference-root or --fp16-reference')
    args.fp16_reference = args.fp16_reference.resolve()
    workspace = args.workspace_root.resolve()
    repo = (args.repository_root or workspace / 'src').resolve()
    configs = (args.configs_root or repo/'configs').resolve()
    exe = (args.executable or workspace / 'bin' / args.build_name / 'Solver-IBM.exe').resolve()
    diagnostic = (args.reference_root/'fp32-diagnostic-build' if args.reference_root else workspace/'bin'/args.diagnostic_build)/'FluidX3D.exe'
    root = workspace / 'workingdir' / 'storage-validation' / datetime.datetime.now(
        datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    root.mkdir(parents=True)
    report = {'status': 'running', 'build': read(exe.parent/'build.json'),
              'executable_sha256': sha(exe), 'tests': [], 'comparisons': [], 'allocations': []}
    print(root, flush=True)

    def invoke(name, config, *, binary=exe, prepare=False, invalid=False, source=None):
        directory = root / name
        directory.mkdir()
        write(directory/'case.json', config)
        options = ['--validate'] if invalid else (['--prepare-only'] if prepare else [])
        before = sha(binary)
        with (directory/'stdout.log').open('wb') as stdout, (directory/'stderr.log').open('wb') as stderr:
            result = subprocess.run([str(binary), '--config', str(source or directory/'case.json'),
                                     '--device', args.device, '--output', str(directory/'results'), *options],
                                    cwd=directory, stdout=stdout, stderr=stderr, timeout=240)
        assert sha(binary) == before
        if binary == exe:
            assert before == report['executable_sha256']
        report['tests'].append({'name': name, 'exit_code': result.returncode,
                                'expected_failure': invalid, 'executable_sha256': before})
        write(root/'report.json', report)
        if invalid:
            assert result.returncode != 0 and 'storage' in (directory/'stderr.log').read_text(encoding='utf-8')
            return None
        assert result.returncode == 0, name
        output = directory/'results'
        completion = read(output/'completion.json')
        assert completion['status'] == ('prepared' if prepare else 'succeeded')
        if binary == exe:
            resolved = read(output/'resolved-config.json')
            storage = config.get('solver', {}).get('storage', 'FP16S')
            width = 2 if storage == 'FP16S' else 4
            count = math.prod(resolved['cells'])
            expected = count*19*width
            assert resolved['storage'] == completion['storage'] == storage
            assert resolved['distribution_bytes_per_value'] == width
            assert resolved['distribution_buffer_bytes'] == resolved['actual_distribution_buffer_bytes'] == expected
            assert resolved['device_field_bytes'] == count*(19*width+29)
            assert resolved['host_field_and_union_bytes'] == count*30
            assert f'Storage = {storage}' in (output/'status.txt').read_text()
            assert f'FP32/{storage}' in (directory/'stdout.log').read_text(encoding='utf-8', errors='replace')
            if 'storage' in config.get('solver', {}):
                assert read(output/'effective-config.json')['solver']['storage'] == storage
            report['allocations'].append({'name': name, 'storage': storage, 'cells': resolved['cells'],
                                          'distribution_bytes': expected, 'device_field_bytes': resolved['device_field_bytes']})
        print(name, 'passed', flush=True)
        return output

    def compare(name, left, right):
        files = sorted(p.name for p in left.glob('*.vtk'))
        assert files and files == sorted(p.name for p in right.glob('*.vtk'))
        for filename in files:
            a, b = p1.vtk(left/filename), p1.vtk(right/filename)
            for key in ['dimensions', 'origin', 'spacing', 'payload']:
                assert a[key] == b[key], (name, filename, key)
        assert read(left/'statistics.json') == read(right/'statistics.json'), name
        report['comparisons'].append({'name': name, 'vtk_arrays_byte_identical': len(files),
                                      'statistics_identical': True, 'left': str(left), 'right': str(right)})

    try:
        assert report['build']['executableSha256'] == sha(exe)
        capabilities = json.loads(subprocess.check_output([str(exe), '--capabilities'], cwd=workspace))
        assert capabilities['storage'] == ['FP16S', 'FP32']
        assert capabilities['default_storage'] == 'FP16S' and capabilities['arithmetic'] == 'FP32'
        assert capabilities['device_bytes_per_cell'] == {'FP16S': 67, 'FP32': 105}
        report['capabilities'] = capabilities
        base = read(configs/'probes-periodic.json')
        base['initial']['regions'] = [{'box_min': [0,0,0], 'box_max': [8,16,16],
                                       'rho': 1.001, 'velocity': [.01,0,0]}]
        outputs = []
        for name, storage in [('default', None), ('explicit16', 'FP16S'), ('explicit32', 'FP32'), ('repeat16', 'FP16S')]:
            c = copy.deepcopy(base)
            c['solver'] = {} if storage is None else {'storage': storage}
            outputs.append(invoke(name, c))
        compare('default equals explicit16', outputs[0], outputs[1])
        compare('16 unchanged after 32', outputs[1], outputs[3])
        for value in ['FP16C', 'fp32', 1, None]:
            c = copy.deepcopy(base); c['solver']['storage'] = value
            invoke('invalid-'+str(value), c, invalid=True)
        for storage, cells in [('FP16S', [25]*3), ('FP32', [22]*3)]:
            c = copy.deepcopy(base)
            c['solver']['storage'] = storage
            c['domain'] = {'aspect_ratio': [1,1,1], 'memory_budget_mb': 1}
            r = invoke('budget-'+storage, c, prepare=True)
            assert read(r/'resolved-config.json')['cells'] == cells
        reference = read(args.fp16_reference/'report.json')
        report['fixed_fp16_reference_build'] = reference['build']
        snapshot = args.fp16_reference/'geometry-force'/'results'/'effective-config.json'
        input_path = snapshot if snapshot.is_file() else args.fp16_reference/'geometry-force'/'case.json'
        c = read(input_path)
        for geometry in c['geometry']:
            geometry['file'] = str((input_path.parent/geometry['file']).resolve())
        c['solver'] = {'storage': 'FP16S'}
        r = invoke('fixed16-geometry-replay', c)
        compare('fixed FP16 geometry baseline', args.fp16_reference/'geometry-force'/'results', r)

        # Combined odd-step case exercises both streaming parities, voxelization,
        # body force, moving-wall correction and diagnostic kernels in FP32.
        mesh = root/'cube.stl'; p1.cube(mesh)
        c = read(configs/'couette.json')
        c['domain']['cells'] = [16,18,16]
        c['fluid']['body_force'] = [.0001,0,0]
        c['boundaries'][2]['velocity'] = [.03,0,0]
        c['geometry'] = [{'id': 'cube', 'file': str(mesh),
                          'transform': {'mode': 'scale', 'factor': 3, 'translation': [6,6,6]}}]
        c['run'] = {'steps': 37, 'monitor_every': 7}
        c['output']['vtk_every'] = 7
        c['analysis'].update(start_step=0, every=7)
        c['analysis']['forces'].append({'id': 'cube', 'target': 'geometry:cube'})
        diagnostic_build = read(diagnostic.parent/'build.json')
        assert diagnostic_build['executableSha256'] == sha(diagnostic)
        report['diagnostic_build'] = diagnostic_build
        r = invoke('runtime32-combined', c)
        reference32 = invoke('fixed32-combined', c, binary=diagnostic)
        compare('runtime32 equals independently compiled32', reference32, r)
        # Replay the exact archived input snapshot from a different working directory.
        repeated = invoke('snapshot32-replay', read(r/'effective-config.json'), source=r/'effective-config.json')
        compare('FP32 snapshot replay', r, repeated)
        study = root/'study-storage'
        script = repo/'scripts'/'parameter-study.py'
        subprocess.run([sys.executable, str(script), 'generate', '--spec', str(configs/'study-storage.json'),
                        '--output', str(study)], check=True)
        subprocess.run([sys.executable, str(script), 'run', '--study', str(study), '--workspace-root', str(workspace),
                        '--build-name', args.build_name, '--executable', str(exe), '--device', args.device], check=True)
        summary = read(next((study/'runs').glob('*/summary.json')))
        assert summary['status'] == 'succeeded' and len(summary['cases']) == 2
        for row, storage in zip(summary['cases'], ['FP16S', 'FP32']):
            assert read(Path(row['results'])/'resolved-config.json')['storage'] == storage
            assert read(Path(row['run_directory'])/'run.json')['build']['executableSha256'] == report['executable_sha256']
        report['batch'] = summary
        report['status'] = 'succeeded'
    except Exception as error:
        report['status'] = 'failed'; report['error'] = repr(error)
        raise
    finally:
        write(root/'report.json', report)
        print(root/'report.json', flush=True)


if __name__ == '__main__':
    main()
