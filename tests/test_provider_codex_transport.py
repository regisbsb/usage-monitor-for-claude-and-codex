"""
App-Server Transport Tests
===========================

Unit tests for the Codex app-server transport: CLI discovery, child
lifecycle, JSON-RPC correlation, and atomic provider operations. All
child-process tests run against ``tests/fake_app_server.py``.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import usage_monitor.providers.codex.app_server as app_server_mod
from usage_monitor.providers.codex.app_server import AppServerTransport, CodexCliNotFound, RpcError, TransportError, discover_codex_command

FAKE_APP_SERVER = str(Path(__file__).parent / 'fake_app_server.py')


class TestDiagnosticRedaction(unittest.TestCase):
    def test_home_redaction_is_case_and_separator_insensitive(self):
        home = str(Path.home())
        forward_home = home.replace('\\', '/')
        line = f'{home.lower()} {forward_home} token-safe'
        redacted = app_server_mod._redact(line)
        self.assertNotIn(home.casefold(), redacted.casefold())
        self.assertNotIn(home.replace('\\', '/').casefold(), redacted.casefold())
        self.assertIn('~', redacted)

    def test_old_generation_stderr_is_not_mixed_into_current_ring(self):
        transport = AppServerTransport(command=['unused'])
        old_process = MagicMock()
        old_process.stderr = iter(['old generation diagnostic\n'])
        with transport._state_lock:
            transport._proc = MagicMock()
            transport._generation = 2

        transport._drain_stderr(old_process, 1)

        self.assertEqual(transport.stderr_tail(), [])


def fake_command(scenario: str = 'normal', log: str = '', state: str = '') -> list[str]:
    command = [sys.executable, FAKE_APP_SERVER, '--scenario', scenario]
    if log:
        command += ['--log', log]
    if state:
        command += ['--state', state]
    return command


def simple_body(operation):
    return operation.request('account/rateLimits/read', {})


class TestDiscoverCodexCommand(unittest.TestCase):
    """CLI discovery order: which -> LOCALAPPDATA installer -> npm -> error."""

    def test_which_hit_wins(self):
        with patch('usage_monitor.providers.codex.app_server.shutil.which', return_value=r'C:\bin\codex.cmd'):
            self.assertEqual(discover_codex_command(), [r'C:\bin\codex.cmd', 'app-server'])

    def test_ps1_shim_substituted_with_cmd_sibling(self):
        with patch('usage_monitor.providers.codex.app_server.shutil.which', return_value=r'C:\bin\codex.ps1'), \
             patch.object(Path, 'is_file', lambda self: self.suffix.lower() == '.cmd'):
            self.assertEqual(discover_codex_command(), [r'C:\bin\codex.cmd', 'app-server'])

    def test_ps1_without_executable_sibling_falls_through(self):
        installer = r'C:\Users\u\AppData\Local\Programs\OpenAI\Codex\bin\codex.exe'
        with patch('usage_monitor.providers.codex.app_server.shutil.which', return_value=r'C:\bin\codex.ps1'), \
             patch.dict('os.environ', {'LOCALAPPDATA': r'C:\Users\u\AppData\Local', 'APPDATA': r'C:\Users\u\AppData\Roaming'}), \
             patch.object(Path, 'is_file', lambda self: str(self) == installer):
            self.assertEqual(discover_codex_command(), [installer, 'app-server'])

    def test_localappdata_installer_fallback(self):
        installer = r'C:\Users\u\AppData\Local\Programs\OpenAI\Codex\bin\codex.exe'
        with patch('usage_monitor.providers.codex.app_server.shutil.which', return_value=None), \
             patch.dict('os.environ', {'LOCALAPPDATA': r'C:\Users\u\AppData\Local', 'APPDATA': r'C:\Users\u\AppData\Roaming'}), \
             patch.object(Path, 'is_file', lambda self: str(self) == installer):
            self.assertEqual(discover_codex_command(), [installer, 'app-server'])

    def test_npm_fallback(self):
        npm_cmd = r'C:\Users\u\AppData\Roaming\npm\codex.cmd'
        with patch('usage_monitor.providers.codex.app_server.shutil.which', return_value=None), \
             patch.dict('os.environ', {'LOCALAPPDATA': r'C:\Users\u\AppData\Local', 'APPDATA': r'C:\Users\u\AppData\Roaming'}), \
             patch.object(Path, 'is_file', lambda self: str(self) == npm_cmd):
            self.assertEqual(discover_codex_command(), [npm_cmd, 'app-server'])

    def test_not_found_raises(self):
        with patch('usage_monitor.providers.codex.app_server.shutil.which', return_value=None), \
             patch.dict('os.environ', {'LOCALAPPDATA': r'C:\x', 'APPDATA': r'C:\y'}), \
             patch.object(Path, 'is_file', lambda self: False):
            with self.assertRaises(CodexCliNotFound):
                discover_codex_command()

    def test_exception_hierarchy(self):
        self.assertTrue(issubclass(CodexCliNotFound, TransportError))
        err = RpcError(-32601, 'method not found')
        self.assertEqual((err.code, err.message, err.data), (-32601, 'method not found', None))


class TestTransportCore(unittest.TestCase):
    """Child lifecycle, correlation, and protocol handling against the fake child."""

    def _transport(self, scenario: str = 'normal', log: str = '', state: str = '', **kwargs) -> AppServerTransport:
        kwargs.setdefault('init_timeout', 10)
        kwargs.setdefault('rpc_timeout', 3)
        transport = AppServerTransport(command=fake_command(scenario, log, state), **kwargs)
        self.addCleanup(transport.shutdown)
        return transport

    def test_handshake_and_simple_operation(self):
        result = self._transport().run_operation(simple_body)
        self.assertEqual(result['rateLimits']['primary']['usedPercent'], 12)

    def test_handshake_order_and_no_jsonrpc_header(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            log = str(Path(temporary_directory) / 'log.jsonl')
            transport = self._transport(log=log)
            transport.run_operation(simple_body)
            transport.shutdown()
            lines = [json.loads(line) for line in Path(log).read_text(encoding='utf-8').splitlines()]
            self.assertEqual(lines[0]['method'], 'initialize')
            self.assertEqual(lines[1], {'method': 'initialized', 'params': {}})
            self.assertNotIn('jsonrpc', Path(log).read_text(encoding='utf-8'))

    def test_rpc_error_raises_rpc_error_not_transport_error(self):
        with self.assertRaises(RpcError) as context:
            self._transport('synthetic-rpc-error').run_operation(simple_body)
        self.assertEqual(context.exception.code, -32001)

    def test_timeout_raises_transport_error(self):
        transport = self._transport('slow', rpc_timeout=0.2)
        started = time.monotonic()
        with self.assertRaises(TransportError):
            transport.run_operation(simple_body)
        self.assertLess(time.monotonic() - started, 10)

    def test_invalid_json_is_fatal_protocol_error(self):
        with self.assertRaisesRegex(TransportError, 'protocol|child died'):
            self._transport('malformed').run_operation(simple_body)

    def test_non_object_json_is_fatal_protocol_error(self):
        with self.assertRaisesRegex(TransportError, 'protocol|child died'):
            self._transport('non-object').run_operation(simple_body)

    def test_malformed_error_envelope_is_fatal_protocol_error(self):
        with self.assertRaisesRegex(TransportError, 'protocol|child died'):
            self._transport('malformed-envelope').run_operation(simple_body)

    def test_server_request_answered_while_client_request_outstanding(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            log = str(Path(temporary_directory) / 'log.jsonl')
            result = self._transport('server-request', log=log).run_operation(simple_body)
            self.assertIn('rateLimits', result)
            entries = [json.loads(line) for line in Path(log).read_text(encoding='utf-8').splitlines()]
            replies = [entry for entry in entries if 'reply_to_999' in entry]
            self.assertEqual(len(replies), 1)
            self.assertEqual(replies[0]['reply_to_999']['error']['code'], -32601)
            self.assertEqual(replies[0]['reply_to_999']['id'], 999)

    def test_reverse_order_responses_are_correlated_by_id(self):
        transport = self._transport('reverse-responses')

        def body(operation):
            results = {}
            failures = []

            def request(method):
                try:
                    results[method] = operation.request(method, {})
                except Exception as exc:  # pragma: no cover - assertion reports worker failures
                    failures.append(exc)

            workers = [threading.Thread(target=request, args=(method,)) for method in ('test/first', 'test/second')]
            for worker in workers:
                worker.start()
            for worker in workers:
                worker.join(timeout=5)
            if failures:
                raise failures[0]
            self.assertTrue(all(not worker.is_alive() for worker in workers))
            return results

        results = transport.run_operation(body)
        self.assertEqual(results['test/first'], {'method': 'test/first'})
        self.assertEqual(results['test/second'], {'method': 'test/second'})

    def test_account_updated_increments_auth_revision(self):
        transport = self._transport('notify')
        before = transport.auth_revision()
        transport.run_operation(simple_body)
        deadline = time.monotonic() + 2
        while transport.auth_revision() == before and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertEqual(transport.auth_revision(), before + 1)

    def test_stderr_ring_buffer_is_redacted(self):
        transport = self._transport('stderr')
        transport.run_operation(simple_body)
        deadline = time.monotonic() + 2
        while not transport.stderr_tail() and time.monotonic() < deadline:
            time.sleep(0.05)
        tail = '\n'.join(transport.stderr_tail())
        self.assertNotIn(str(Path.home()), tail)
        self.assertNotIn('abcdefghijklmnopqrstuvwxyz012345', tail)
        self.assertIn('~', tail)

    def test_cli_not_found_propagates(self):
        transport = AppServerTransport(command=None, init_timeout=2, rpc_timeout=2)
        self.addCleanup(transport.shutdown)
        with patch('usage_monitor.providers.codex.app_server.discover_codex_command', side_effect=CodexCliNotFound('missing')):
            with self.assertRaises(CodexCliNotFound):
                transport.run_operation(simple_body)

    def test_job_object_failure_terminates_child_and_fails_startup(self):
        spawned = []
        real_popen = subprocess.Popen

        def recording_popen(*args, **kwargs):
            process = real_popen(*args, **kwargs)
            spawned.append(process)
            return process

        transport = self._transport()
        with patch('usage_monitor.providers.codex.app_server.subprocess.Popen', side_effect=recording_popen), \
             patch('usage_monitor.providers.codex.app_server._assign_kill_on_close_job', side_effect=TransportError('job object failed')):
            with self.assertRaises(TransportError):
                transport.run_operation(simple_body)
        self.assertEqual(len(spawned), 1)
        deadline = time.monotonic() + 5
        while spawned[0].poll() is None and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertIsNotNone(spawned[0].poll())
        for stream in (spawned[0].stdin, spawned[0].stdout, spawned[0].stderr):
            self.assertTrue(stream is None or stream.closed)

    def test_spurious_response_with_unknown_id_is_ignored(self):
        result = self._transport('noise').run_operation(simple_body)
        self.assertIn('rateLimits', result)

    def test_stale_reader_cannot_route_response_or_reply_to_new_child(self):
        transport = self._transport()
        current_process = object()
        stale_process = object()
        pending = app_server_mod._Pending()
        with transport._state_lock:
            transport._proc = current_process
            transport._generation = 2
            transport._dead = False
            transport._pending[17] = pending
        with patch.object(transport, '_write_line') as write_line:
            transport._dispatch_message(stale_process, 1, {'id': 17, 'result': {'stale': True}})
            transport._dispatch_message(stale_process, 1, {'id': 99, 'method': 'tools/confirm', 'params': {}})
        self.assertFalse(pending.event.is_set())
        self.assertIsNone(pending.response)
        write_line.assert_not_called()
        with transport._state_lock:
            transport._proc = None
            transport._dead = True
            transport._pending.clear()

    def test_shutdown_terminates_child_and_is_idempotent(self):
        transport = self._transport()
        transport.run_operation(simple_body)
        process = transport._proc
        transport.shutdown()
        transport.shutdown()
        self.assertIsNotNone(process)
        self.assertIsNotNone(process.poll())


class TestAtomicOperations(unittest.TestCase):
    """Whole-operation retry, generation pinning, recovery latch, and TTL boundaries."""

    def _transport(self, scenario: str = 'normal', log: str = '', state: str = '', **kwargs) -> AppServerTransport:
        kwargs.setdefault('init_timeout', 10)
        kwargs.setdefault('rpc_timeout', 3)
        transport = AppServerTransport(command=fake_command(scenario, log, state), **kwargs)
        self.addCleanup(transport.shutdown)
        return transport

    def test_first_generation_dies_after_partial_then_whole_operation_succeeds_once(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            log = str(Path(temporary_directory) / 'log.jsonl')
            state = str(Path(temporary_directory) / 'generation.marker')
            transport = self._transport('die-after-account-first-generation', log=log, state=state)
            body_calls = []

            def body(operation):
                body_calls.append('attempt')
                account = operation.request('account/read', {'refreshToken': False})
                limits = operation.request('account/rateLimits/read', {})
                return account, limits

            account, limits = transport.run_operation(body)
            self.assertEqual(len(body_calls), 2)
            self.assertEqual(account['account']['email'], 'user@example.com')
            self.assertEqual(limits['rateLimits']['primary']['usedPercent'], 12)
            entries = [json.loads(line) for line in Path(log).read_text(encoding='utf-8').splitlines()]
            methods = [entry.get('method') for entry in entries]
            self.assertEqual(methods.count('account/read'), 2)
            self.assertEqual(methods.count('account/rateLimits/read'), 1)

    def test_child_death_in_both_generations_fails_after_exactly_two_attempts(self):
        transport = self._transport('die-on-first-request')
        body_calls = []

        def body(operation):
            body_calls.append('attempt')
            return operation.request('account/rateLimits/read', {})

        with self.assertRaises(TransportError):
            transport.run_operation(body)
        self.assertEqual(len(body_calls), 2)
        self.assertIsNone(transport._proc)
        self.assertIsNone(transport._job_handle)

    def test_refresh_latch_survives_transport_retry(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            log = str(Path(temporary_directory) / 'log.jsonl')
            transport = self._transport('die-after-refresh', log=log)
            recovery_consumed = False
            body_calls = []

            def body(operation):
                nonlocal recovery_consumed
                body_calls.append('attempt')
                operation.request('account/read', {'refreshToken': False})
                if not recovery_consumed:
                    recovery_consumed = True
                    operation.request('account/read', {'refreshToken': True})
                return operation.request('account/rateLimits/read', {})

            with self.assertRaises(RpcError):
                transport.run_operation(body)
            self.assertEqual(len(body_calls), 2)
            entries = [json.loads(line) for line in Path(log).read_text(encoding='utf-8').splitlines()]
            account_reads = [entry for entry in entries if entry.get('method') == 'account/read']
            refresh_reads = [entry for entry in account_reads if (entry.get('params') or {}).get('refreshToken')]
            self.assertEqual(len(account_reads), 3)
            self.assertEqual(len(refresh_reads), 1)

    def test_ttl_recycles_only_at_next_operation_boundary(self):
        transport = self._transport(child_ttl=0)

        def body(operation):
            first = operation.request('account/rateLimits/read', {})
            time.sleep(0.1)
            second = operation.request('account/rateLimits/read', {})
            return first, second

        first, second = transport.run_operation(body)
        self.assertEqual(first, second)
        generation_after_first_operation = transport._generation
        transport.run_operation(simple_body)
        self.assertGreater(transport._generation, generation_after_first_operation)

    def test_rpc_error_does_not_trigger_operation_retry(self):
        transport = self._transport('synthetic-rpc-error')
        body_calls = []

        def body(operation):
            body_calls.append('attempt')
            return operation.request('account/rateLimits/read', {})

        with self.assertRaises(RpcError):
            transport.run_operation(body)
        self.assertEqual(len(body_calls), 1)

    def test_force_restart_spawns_new_generation(self):
        transport = self._transport()
        transport.run_operation(simple_body)
        generation = transport._generation
        transport.force_restart()
        transport.run_operation(simple_body)
        self.assertGreater(transport._generation, generation)

    def test_stale_operation_handle_from_previous_generation_is_rejected(self):
        transport = self._transport()
        captured = {}

        def body(operation):
            captured['operation'] = operation
            return operation.request('account/rateLimits/read', {})

        transport.run_operation(body)
        transport.force_restart()
        transport.run_operation(simple_body)
        with self.assertRaises(TransportError):
            captured['operation'].request('account/rateLimits/read', {})

    def test_operation_handle_cannot_escape_its_operation(self):
        transport = self._transport()
        captured = {}

        def body(operation):
            captured['operation'] = operation
            return operation.request('account/rateLimits/read', {})

        transport.run_operation(body)
        with self.assertRaisesRegex(TransportError, 'already finished'):
            captured['operation'].request('account/rateLimits/read', {})


if __name__ == '__main__':
    unittest.main()


