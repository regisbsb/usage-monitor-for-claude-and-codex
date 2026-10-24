"""Verify native Job containment before testing Codex child retirement.

The current venv launcher is deliberately preserved as a separate regression.
Store-backed Python can create its real interpreter outside the transport Job;
that case must remain an ordinary failing test until containment is resolved.
All subprocesses are synthetic and cleanup retains exact process identities.
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes
import json
import sys
import tempfile
import time
import unittest
from dataclasses import dataclass, field
from pathlib import Path

from usage_monitor.providers.codex.app_server import AppServerTransport

__all__: list[str] = []

_FIXTURE = Path(__file__).with_name('containment_app_server.py')
_PROCESS_ACCESS = 0x00101001  # SYNCHRONIZE | QUERY_LIMITED_INFORMATION | TERMINATE
_WAIT_OBJECT_0 = 0
_WAIT_TIMEOUT = 258
_kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
_kernel32.OpenProcess.argtypes = [ctypes.wintypes.DWORD, ctypes.wintypes.BOOL, ctypes.wintypes.DWORD]
_kernel32.OpenProcess.restype = ctypes.wintypes.HANDLE
_kernel32.GetProcessTimes.argtypes = [ctypes.wintypes.HANDLE, *([ctypes.POINTER(ctypes.wintypes.FILETIME)] * 4)]
_kernel32.GetProcessTimes.restype = ctypes.wintypes.BOOL
_kernel32.IsProcessInJob.argtypes = [ctypes.wintypes.HANDLE, ctypes.wintypes.HANDLE, ctypes.POINTER(ctypes.wintypes.BOOL)]
_kernel32.IsProcessInJob.restype = ctypes.wintypes.BOOL
_kernel32.WaitForSingleObject.argtypes = [ctypes.wintypes.HANDLE, ctypes.wintypes.DWORD]
_kernel32.WaitForSingleObject.restype = ctypes.wintypes.DWORD
_kernel32.TerminateProcess.argtypes = [ctypes.wintypes.HANDLE, ctypes.wintypes.UINT]
_kernel32.TerminateProcess.restype = ctypes.wintypes.BOOL
_kernel32.CloseHandle.argtypes = [ctypes.wintypes.HANDLE]
_kernel32.CloseHandle.restype = ctypes.wintypes.BOOL


def _creation_time(handle: int) -> int:
    """Return a retained process handle's exact native creation FILETIME."""
    created, exited, kernel, user = (ctypes.wintypes.FILETIME() for _ in range(4))
    if not _kernel32.GetProcessTimes(handle, ctypes.byref(created), ctypes.byref(exited), ctypes.byref(kernel), ctypes.byref(user)):
        raise ctypes.WinError(ctypes.get_last_error())
    return created.dwHighDateTime << 32 | created.dwLowDateTime


def _wait(handle: int, timeout_ms: int = 0) -> int:
    """Return a native process wait result, rejecting unexpected OS errors."""
    result = _kernel32.WaitForSingleObject(handle, timeout_ms)
    if result not in (_WAIT_OBJECT_0, _WAIT_TIMEOUT):
        raise ctypes.WinError(ctypes.get_last_error())
    return result


@dataclass
class _OwnedProcess:
    """Own a separate handle for one verified fixture process identity."""

    pid: int
    creation_time: int
    handle: int
    roles: set[str] = field(default_factory=set)


class TestCodexProcessContainment(unittest.TestCase):
    """Use real Windows processes without launching Codex or reading credentials."""

    def setUp(self) -> None:
        self._directory = tempfile.TemporaryDirectory(prefix='codex-containment-')
        self.addCleanup(self._directory.cleanup)
        self._state_root = Path(self._directory.name)
        self._processes: dict[tuple[int, int], _OwnedProcess] = {}
        self._transports: list[AppServerTransport] = []
        self.addCleanup(self._cleanup_processes)

    def _retain(self, pid: int, created: int, role: str, *, required: bool) -> _OwnedProcess | None:
        """Retain only the exact process recorded by the fixture, never a reused PID."""
        identity = (pid, created)
        owned = self._processes.get(identity)
        if owned is not None:
            owned.roles.add(role)
            return owned
        handle = _kernel32.OpenProcess(_PROCESS_ACCESS, False, pid)
        if not handle:
            error = ctypes.get_last_error()
            if error == 87 and not required:  # ERROR_INVALID_PARAMETER: already gone.
                return None
            raise ctypes.WinError(error)
        try:
            matches = _creation_time(handle) == created
        except BaseException:
            _kernel32.CloseHandle(handle)
            raise
        if not matches:
            _kernel32.CloseHandle(handle)
            if required:
                self.fail(f'{role} PID {pid} was reused before its handle could be retained')
            return None
        owned = _OwnedProcess(pid, created, int(handle), {role})
        self._processes[identity] = owned
        return owned

    def _collect_manifest_handles(self, *, required: bool = False) -> None:
        """Retain fixture records from every generation, including failed startup."""
        for name in ('server.json', 'descendant-launcher.json', 'descendant.json'):
            for path in self._state_root.glob(f'*/{name}'):
                record = json.loads(path.read_text(encoding='utf-8'))
                self._retain(record['pid'], record['creation_time'], path.stem, required=required)

    def _start(self, executable: str, *, child_ttl: int = 600) -> AppServerTransport:
        """Launch the ready fixture and retain all identities before assertions."""
        transport = AppServerTransport(
            command=[executable, str(_FIXTURE), '--state-dir', str(self._state_root)],
            child_ttl=child_ttl,
            init_timeout=10,
            rpc_timeout=5,
        )
        self._transports.append(transport)
        result = transport.run_operation(lambda operation: operation.request('account/rateLimits/read', {}))
        self._collect_manifest_handles(required=True)
        self.assertIsNotNone(transport._proc)
        process = transport._proc
        self._retain(process.pid, _creation_time(int(process._handle)), 'launcher', required=True)
        self.assertIn('rateLimits', result)
        self._assert_readiness()
        return transport

    def _assert_readiness(self) -> None:
        """Require actual server and child records, with acknowledged parentage."""
        generations = list(self._state_root.glob('*/server.json'))
        self.assertTrue(generations, 'fixture never published its actual server PID')
        for path in generations:
            server = json.loads(path.read_text(encoding='utf-8'))
            descendant = json.loads(path.with_name('descendant.json').read_text(encoding='utf-8'))
            launcher = json.loads(path.with_name('descendant-launcher.json').read_text(encoding='utf-8'))
            self.assertEqual(descendant['parent_pid'], server['pid'])
            self.assertEqual(descendant['pid'], launcher['pid'])
            self.assertEqual(descendant['creation_time'], launcher['creation_time'])

    def _assert_contained(self, transport: AppServerTransport) -> None:
        """Check launcher, actual server, and descendant before any retirement."""
        self.assertIsNotNone(transport._job_handle)
        outside: list[str] = []
        for owned in self._processes.values():
            self.assertEqual(_wait(owned.handle), _WAIT_TIMEOUT, f'fixture PID {owned.pid} exited before containment was checked')
            in_job = ctypes.wintypes.BOOL()
            if not _kernel32.IsProcessInJob(owned.handle, transport._job_handle, ctypes.byref(in_job)):
                raise ctypes.WinError(ctypes.get_last_error())
            if not in_job.value:
                outside.append(f'{sorted(owned.roles)} PID {owned.pid}')
        self.assertEqual(outside, [], f'fixture processes outside the transport Job: {outside}')

    def _assert_exited(self, processes: list[_OwnedProcess], *, timeout: float = 0) -> None:
        """Verify retained process handles signal within one shared deadline."""
        deadline = time.monotonic() + timeout
        for owned in processes:
            remaining_ms = max(0, int((deadline - time.monotonic()) * 1000))
            self.assertEqual(_wait(owned.handle, remaining_ms), _WAIT_OBJECT_0, f'fixture {sorted(owned.roles)} PID {owned.pid} is alive')

    def _cleanup_processes(self) -> None:
        """Reap and close only retained fixture identities even after a red assertion."""
        errors: list[Exception] = []
        try:
            self._collect_manifest_handles()
        except Exception as error:
            errors.append(error)
        for transport in self._transports:
            try:
                transport.shutdown()
            except Exception as error:
                errors.append(error)
        for owned in self._processes.values():
            try:
                if _wait(owned.handle, 100) == _WAIT_TIMEOUT:
                    terminated = _kernel32.TerminateProcess(owned.handle, 1)
                    error_code = ctypes.get_last_error() if not terminated else 0
                    # A process already terminating may reject TerminateProcess
                    # before its handle signals. The final native wait decides.
                    if _wait(owned.handle, 5000) != _WAIT_OBJECT_0:
                        if error_code:
                            raise ctypes.WinError(error_code)
                        raise AssertionError(f'owned fixture PID {owned.pid} did not exit during test cleanup')
            except Exception as error:
                errors.append(error)
            finally:
                if not _kernel32.CloseHandle(owned.handle):
                    errors.append(ctypes.WinError(ctypes.get_last_error()))
        self._processes.clear()
        if errors:
            raise AssertionError(f'fixture cleanup failed: {errors}')

    def test_direct_native_server_and_descendant_are_contained_before_shutdown(self) -> None:
        transport = self._start(sys._base_executable)
        self._assert_contained(transport)

    def test_current_venv_launcher_preserves_store_backed_containment_regression(self) -> None:
        transport = self._start(sys.executable)
        self._assert_contained(transport)

    def test_direct_native_shutdown_reaps_verified_processes(self) -> None:
        transport = self._start(sys._base_executable)
        self._assert_contained(transport)
        processes = list(self._processes.values())

        transport.shutdown()

        self._assert_exited(processes, timeout=5)

    def test_direct_native_old_generation_is_gone_before_replacement(self) -> None:
        transport = self._start(sys._base_executable, child_ttl=0)
        self._assert_contained(transport)
        old_processes = list(self._processes.values())
        old_pid = transport._proc.pid

        transport.run_operation(lambda operation: operation.request('account/rateLimits/read', {}))
        self._collect_manifest_handles(required=False)
        self._assert_readiness()

        self.assertNotEqual(transport._proc.pid, old_pid)
        self._assert_exited(old_processes)


if __name__ == '__main__':
    unittest.main()
