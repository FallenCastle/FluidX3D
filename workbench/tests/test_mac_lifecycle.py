"""Lifecycle safety checks with fake transport; no SSH connections or solver runs."""
from contextlib import redirect_stdout
import importlib.util
import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

if os.name == 'nt':
    raise unittest.SkipTest('Mac lifecycle controller uses POSIX sockets and file locks')

spec = importlib.util.spec_from_file_location('mac_workbench', Path(__file__).resolve().parents[1] / 'scripts/mac-workbench.py')
mac = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mac)


class LifecycleTest(unittest.TestCase):
    def setUp(self):
        self.app = mac.Controller()
        for method in ('remote', 'connected', 'port_open', 'start_tunnel', 'stop_tunnel', 'wait_ready'):
            setattr(self.app, method, Mock())
        self.app.connected.return_value = False
        self.app.port_open.return_value = False
        self.output = redirect_stdout(io.StringIO())
        self.output.__enter__()

    def tearDown(self):
        self.output.__exit__(None, None, None)

    def test_active_job_preserves_service_and_tunnel(self):
        self.app.remote.return_value = {'result': 'blocked', 'active_job': {
            'id': 'test-job', 'case_name': 'test-only', 'status': 'running'}, 'solver_processes': []}
        with self.assertRaises(mac.LifecycleError):
            self.app.stop()
        self.app.stop_tunnel.assert_not_called()
        self.app.remote.assert_called_once_with('stop')

    def test_orphan_or_external_solver_blocks_close(self):
        self.app.remote.return_value = {'result': 'blocked', 'solver_processes': [
            {'Name': 'Solver-IBM.exe', 'ProcessId': 123}]}
        with self.assertRaises(mac.LifecycleError):
            self.app.stop()
        self.app.stop_tunnel.assert_not_called()

    def test_network_failure_preserves_tunnel(self):
        self.app.remote.side_effect = mac.LifecycleError('offline')
        with self.assertRaises(mac.LifecycleError):
            self.app.stop()
        self.app.stop_tunnel.assert_not_called()

    def test_stop_only_closes_tunnel_after_confirmed_remote_stop(self):
        calls = []
        self.app.remote.side_effect = lambda _: calls.append('confirmed stopped') or {'result': 'stopped'}
        self.app.stop_tunnel.side_effect = lambda: calls.append('close tunnel')
        self.app.stop()
        self.assertEqual(calls, ['confirmed stopped', 'close tunnel'])

    def test_foreign_local_port_prevents_remote_mutation(self):
        self.app.port_open.return_value = True
        with self.assertRaises(mac.LifecycleError):
            self.app.start(False)
        self.app.remote.assert_not_called()
        self.app.start_tunnel.assert_not_called()

    def test_repeated_start_reuses_tunnel_and_opens_browser_after_ready(self):
        self.app.connected.return_value = True
        self.app.remote.return_value = {'result': 'running', 'started': False, 'solver': {'version': '2.0.0'}}
        with patch.object(mac.subprocess, 'run') as run:
            self.app.start()
        self.app.start_tunnel.assert_not_called()
        self.app.wait_ready.assert_called_once_with({'version': '2.0.0'})
        run.assert_called_once_with(['/usr/bin/open', self.app.url], check=True)

    def test_failed_tunnel_rolls_back_only_new_service(self):
        self.app.remote.side_effect = [{'result': 'running', 'started': True, 'solver': {}}, {'result': 'stopped'}]
        self.app.start_tunnel.side_effect = mac.LifecycleError('bind failed')
        with self.assertRaises(mac.LifecycleError):
            self.app.start(False)
        self.assertEqual([call.args[0] for call in self.app.remote.call_args_list], ['start', 'stop'])
        self.app.stop_tunnel.assert_called_once()

    def test_failed_connection_keeps_preexisting_service(self):
        self.app.remote.return_value = {'result': 'running', 'started': False, 'solver': {}}
        self.app.wait_ready.side_effect = mac.LifecycleError('not ready')
        with self.assertRaises(mac.LifecycleError):
            self.app.start(False)
        self.app.remote.assert_called_once_with('start')

    def test_simultaneous_actions_are_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            self.app.runtime = Path(folder)
            with self.app.lock():
                with self.assertRaises(mac.LifecycleError):
                    with self.app.lock():
                        self.fail('second action acquired lock')

    def test_private_directory_and_port_validation(self):
        with tempfile.TemporaryDirectory() as folder:
            self.app.runtime = Path(folder)
            self.app.runtime.chmod(0o755)
            with self.assertRaises(mac.LifecycleError):
                with self.app.lock():
                    self.fail('insecure directory accepted')
        with patch.dict(os.environ, {'SOLVER_WEB_PORT': '70000'}):
            with self.assertRaises(mac.LifecycleError):
                mac.Controller()


if __name__ == '__main__':
    unittest.main()
