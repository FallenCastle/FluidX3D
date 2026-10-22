"""Service contract tests. FakeRunner never starts Solver-IBM or any executable."""
import copy
import json
from pathlib import Path
import struct
import sys
import tempfile
import threading
import time
import unittest
from urllib.request import Request, urlopen
from urllib.error import HTTPError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'service'))
from core import WORKBENCH, Problem, Workbench, asset_paths, atomic_json, inside, read_json, sha, stl_info
from server import make_server


class FakePackage:
    def __init__(self, root):
        self.root = root
        (root / 'bin').mkdir(parents=True)
        self.executable = root / 'bin/Solver-IBM.exe'
        self.executable.write_bytes(b'FAKE TEST FILE: NEVER EXECUTED')
        atomic_json(root / 'bin/build.json', {'test_only': True})
        self.identity = {'sha256': sha(self.executable), 'version': '2.0.0'}

    def verify(self):
        return self.identity


class FakeRunner:
    devices = [{'id': 0, 'name': 'TEST ONLY'}]
    delay = 0
    fail = False

    def execute(self, executable, args, directory, cancel, timeout, on_start):
        on_start(123)
        if '--validate' in args:
            atomic_json(directory / 'stdout.log', {'domain': {'cells': [64, 16, 16]}})
            return {'exit_code': 0, 'outcome': None, 'stdout': '{}', 'stderr': ''}
        started = time.monotonic()
        while time.monotonic() - started < self.delay:
            if cancel.wait(.01):
                return {'exit_code': 1, 'outcome': 'cancelled', 'stdout': '', 'stderr': ''}
            if time.monotonic() - started >= timeout:
                return {'exit_code': 1, 'outcome': 'timed_out', 'stdout': '', 'stderr': ''}
        if self.fail:
            return {'exit_code': 2, 'outcome': None, 'stdout': '', 'stderr': 'test solver failure'}
        output = Path(args[args.index('--output') + 1])
        output.mkdir()
        atomic_json(output / 'completion.json', {'product': 'Solver-IBM', 'status': 'succeeded', 'version': '2.0.0', 'steps': 23, 'requested_steps': 23})
        for name in ['manifest.json', 'resolved-config.json', 'effective-config.json']:
            atomic_json(output / name, {'test_only': True})
        (output / 'monitor.csv').write_text('step,time,mass_lattice\n0,0,10\n23,.069,10\n')
        return {'exit_code': 0, 'outcome': None, 'stdout': '', 'stderr': ''}


class ServiceTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.package = FakePackage(self.root / 'package')
        self.runner = FakeRunner()
        self.app = Workbench(self.root / 'data', self.package, self.runner)
        self.config = read_json(WORKBENCH / 'default-case.json')

    def tearDown(self):
        self.app.shutdown()
        self.temp.cleanup()

    def wait(self):
        self.app.worker.join(4)
        self.assertFalse(self.app.worker.is_alive())

    def submit(self):
        return self.app.submit({'config': self.config, 'device_id': 0, 'timeout_seconds': 1,
                                'refinement': {'regions': [{'level': 2}]}})

    def test_snapshot_and_completion(self):
        record = self.submit()
        self.config['domain']['dx'] = 99
        self.wait()
        record = self.app.record(record['id'])
        self.assertEqual(record['status'], 'succeeded')
        self.assertEqual(record['exit_code'], 0)
        run = self.app.record_path(record['id']).parent
        self.assertEqual(read_json(run / 'inputs/case.json')['domain']['dx'], .01)
        self.assertNotIn('refinement', read_json(run / 'inputs/case.json'))
        self.assertFalse(read_json(run / 'refinement-draft.json')['applied'])
        self.assertEqual(sha(run / 'runtime/Solver-IBM.exe'), self.package.identity['sha256'])

    def test_history_orders_runs_within_one_second(self):
        first = self.submit()
        self.wait()
        second = self.submit()
        self.wait()
        self.app.update(first['id'], created_at='2026-10-22T10:00:00.100000+00:00')
        self.app.update(second['id'], created_at='2026-10-22T10:00:00.200000+00:00')
        self.assertEqual([job['id'] for job in self.app.jobs()], [second['id'], first['id']])

    def test_busy_stop_and_own_job_only(self):
        self.runner.delay = 5
        record = self.submit()
        with self.assertRaises(Problem):
            self.submit()
        self.app.stop(record['id'])
        self.wait()
        self.assertEqual(self.app.record(record['id'])['status'], 'cancelled')
        with self.assertRaises(Problem):
            self.app.stop(record['id'])

    def test_timeout_and_failure(self):
        self.runner.delay = 5
        record = self.submit()
        self.wait()
        self.assertEqual(self.app.record(record['id'])['status'], 'timed_out')
        self.runner.delay, self.runner.fail = 0, True
        record = self.submit()
        self.wait()
        self.assertEqual(self.app.record(record['id'])['status'], 'failed')
        self.assertEqual(self.app.record(record['id'])['exit_code'], 2)

    def test_validation_cleanup_and_lock(self):
        self.assertTrue(self.app.validate(self.config)['valid'])
        self.assertEqual(list((self.app.root / 'validation').iterdir()), [])
        with self.assertRaises(Problem):
            Workbench(self.app.root, self.package, self.runner)

    def test_revision_conflict(self):
        draft = self.app.draft()
        self.app.save_draft(draft)
        with self.assertRaises(Problem):
            self.app.save_draft(draft)

    def test_paths_and_unsupported_features(self):
        for path in ['../secret', '/secret', 'assets/../../secret', 'C:/secret', 'assets/a.stl:stream', 'assets\\a.stl']:
            with self.assertRaises(Problem):
                inside(self.app.root, path)
        for key in ['checkpoint_every', 'restart', 'scan']:
            config = copy.deepcopy(self.config)
            config['run'][key] = 100
            with self.assertRaises(Problem):
                asset_paths(config)
        self.config['geometry'][0]['file'] = '../private.stl'
        with self.assertRaises(Problem):
            asset_paths(self.config)

    def test_stl_upload(self):
        data = (WORKBENCH.parent / 'configs/assets/unit-cube-binary.stl').read_bytes()
        result = self.app.upload('a cube.stl', data)
        self.assertEqual(result['triangles'], 12)
        self.assertEqual(stl_info(data)['triangles'], 12)
        self.assertTrue(inside(self.app.root, result['path']).exists())
        with self.assertRaises(Problem):
            self.app.upload('broken.stl', data[:-1])
        bad = bytearray(data)
        struct.pack_into('<f', bad, 96, float('nan'))
        with self.assertRaises(Problem):
            stl_info(bad)

    def test_csv_interleaved_and_partial_line(self):
        record = self.submit()
        self.wait()
        path = self.app.record_path(record['id']).parent / 'results/probes.csv'
        path.write_text('step,time,id,speed\n'+''.join(f'{i},{i},0,{i}\n{i},{i},1,{i+1}\n' for i in range(9000))+'9000,9000,0,')
        result = self.app.series(record['id'], 'probes.csv')
        self.assertEqual({r['id'] for r in result['rows']}, {'0', '1'})
        self.assertEqual(result['rows'][-1]['step'], 8999)
        self.assertLessEqual(len(result['rows']), 4002)

    def test_http_origin_token_and_no_arbitrary_command(self):
        server = make_server(self.app, 0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        url = f'http://127.0.0.1:{server.server_port}'
        try:
            session = json.load(urlopen(url+'/api/session'))
            with self.assertRaises(HTTPError) as error:
                urlopen(Request(url+'/api/jobs', data=b'{}', headers={'Content-Type': 'application/json'}))
            self.assertEqual(error.exception.code, 403)
            with self.assertRaises(HTTPError):
                urlopen(Request(url+'/api/session', headers={'Origin': 'http://evil.test'}))
            with self.assertRaises(HTTPError):
                urlopen(Request(url+'/api/session', headers={'Host': 'evil.test'}))
            request = Request(url+'/api/build', data=b'{}', headers={'Content-Type': 'application/json', 'X-Workbench-Token': session['token']})
            with self.assertRaises(HTTPError) as error:
                urlopen(request)
            self.assertEqual(error.exception.code, 404)
            draft = self.app.draft()
            request = Request(url+'/api/draft', data=json.dumps(draft).encode(), method='PUT',
                              headers={'Content-Type':'application/json','X-Workbench-Token':session['token']})
            self.assertEqual(json.load(urlopen(request))['revision'], 2)
        finally:
            server.shutdown()
            server.server_close()


if __name__ == '__main__':
    unittest.main()
