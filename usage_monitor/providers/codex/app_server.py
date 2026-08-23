"""
App-Server Transport
=====================

Owns the single long-lived ``codex app-server`` child process and speaks
JSON-RPC 2.0 semantics over newline-delimited JSON (the ``jsonrpc`` version
header is omitted on the wire, per the official app-server protocol).

Security-critical module: together with ``api.py`` it forms the provider
boundary. It never accesses credential files and never logs payloads,
tokens, or email - only method names, durations, and error codes.
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes
import json
import logging
import os
import re
import shutil
import subprocess
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any, Callable, TypeVar

__all__ = ['CHILD_TTL', 'INIT_TIMEOUT', 'RPC_TIMEOUT', 'AppServerTransport', 'CodexCliNotFound', 'RpcError', 'TransportError', 'discover_codex_command']

CHILD_TTL = 600
INIT_TIMEOUT = 30
RPC_TIMEOUT = 10

log = logging.getLogger(__name__)

STDERR_RING_SIZE = 20
_JOB_KILL_ON_CLOSE = 0x00002000
T_ = TypeVar('T_')


class TransportError(Exception):
    """Transport-level failure: spawn, handshake, timeout, child death, or protocol violation."""


class CodexCliNotFound(TransportError):
    """The codex CLI binary could not be located."""


class RpcError(Exception):
    """A JSON-RPC error response from the app-server."""

    def __init__(self, code: int | None, message: str, data: Any = None) -> None:
        super().__init__(f'{code}: {message}')
        self.code = code
        self.message = message
        self.data = data


def discover_codex_command() -> list[str]:
    """Locate the codex CLI and return the app-server launch command.

    Search order: PATH (with ``.ps1`` shim substituted by a ``.cmd``/``.exe``
    sibling), the native installer under ``%LOCALAPPDATA%``, then the npm
    global directory under ``%APPDATA%``.

    Returns
    -------
    list[str]
        The full argv, e.g. ``['C:\\...\\codex.exe', 'app-server']``.

    Raises
    ------
    CodexCliNotFound
        If no codex binary exists in any known location.
    """
    found = shutil.which('codex')
    if found:
        path = Path(found)
        if path.suffix.lower() == '.ps1':
            for extension in ('.cmd', '.exe'):
                executable_sibling = path.with_suffix(extension)
                if executable_sibling.is_file():
                    return [str(executable_sibling), 'app-server']
        else:
            return [str(path), 'app-server']

    localappdata = os.environ.get('LOCALAPPDATA')
    if localappdata:
        candidate = Path(localappdata) / 'Programs' / 'OpenAI' / 'Codex' / 'bin' / 'codex.exe'
        if candidate.is_file():
            return [str(candidate), 'app-server']

    appdata = os.environ.get('APPDATA')
    if appdata:
        for name in ('codex.cmd', 'codex.exe'):
            candidate = Path(appdata) / 'npm' / name
            if candidate.is_file():
                return [str(candidate), 'app-server']

    raise CodexCliNotFound('codex CLI not found')


class _JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
    class _BASIC(ctypes.Structure):
        _fields_ = [
            ('PerProcessUserTimeLimit', ctypes.c_int64),
            ('PerJobUserTimeLimit', ctypes.c_int64),
            ('LimitFlags', ctypes.wintypes.DWORD),
            ('MinimumWorkingSetSize', ctypes.c_size_t),
            ('MaximumWorkingSetSize', ctypes.c_size_t),
            ('ActiveProcessLimit', ctypes.wintypes.DWORD),
            ('Affinity', ctypes.c_size_t),
            ('PriorityClass', ctypes.wintypes.DWORD),
            ('SchedulingClass', ctypes.wintypes.DWORD),
        ]

    class _COUNTERS(ctypes.Structure):
        _fields_ = [
            ('ReadOperationCount', ctypes.c_uint64),
            ('WriteOperationCount', ctypes.c_uint64),
            ('OtherOperationCount', ctypes.c_uint64),
            ('ReadTransferCount', ctypes.c_uint64),
            ('WriteTransferCount', ctypes.c_uint64),
            ('OtherTransferCount', ctypes.c_uint64),
        ]

    _fields_ = [
        ('BasicLimitInformation', _BASIC),
        ('IoInfo', _COUNTERS),
        ('ProcessMemoryLimit', ctypes.c_size_t),
        ('JobMemoryLimit', ctypes.c_size_t),
        ('PeakProcessMemoryUsed', ctypes.c_size_t),
        ('PeakJobMemoryUsed', ctypes.c_size_t),
    ]


# Without explicit signatures, ctypes truncates HANDLEs to c_int on 64-bit
# Windows and can corrupt the process or Job-object handles.
_kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
_kernel32.CreateJobObjectW.argtypes = [ctypes.wintypes.LPVOID, ctypes.wintypes.LPCWSTR]
_kernel32.CreateJobObjectW.restype = ctypes.wintypes.HANDLE
_kernel32.SetInformationJobObject.argtypes = [ctypes.wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, ctypes.wintypes.DWORD]
_kernel32.SetInformationJobObject.restype = ctypes.wintypes.BOOL
_kernel32.AssignProcessToJobObject.argtypes = [ctypes.wintypes.HANDLE, ctypes.wintypes.HANDLE]
_kernel32.AssignProcessToJobObject.restype = ctypes.wintypes.BOOL
_kernel32.CloseHandle.argtypes = [ctypes.wintypes.HANDLE]
_kernel32.CloseHandle.restype = ctypes.wintypes.BOOL


def _assign_kill_on_close_job(process_handle: int) -> int:
    """Create a kill-on-close Job object and assign the child to it."""
    job = _kernel32.CreateJobObjectW(None, None)
    if not job:
        raise TransportError(f'CreateJobObjectW failed ({ctypes.get_last_error()})')

    information = _JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
    information.BasicLimitInformation.LimitFlags = _JOB_KILL_ON_CLOSE
    job_object_extended_limit_information = 9
    configured = _kernel32.SetInformationJobObject(
        job,
        job_object_extended_limit_information,
        ctypes.byref(information),
        ctypes.sizeof(information),
    )
    if not configured:
        error_code = ctypes.get_last_error()
        _kernel32.CloseHandle(job)
        raise TransportError(f'SetInformationJobObject failed ({error_code})')

    if not _kernel32.AssignProcessToJobObject(job, process_handle):
        error_code = ctypes.get_last_error()
        _kernel32.CloseHandle(job)
        raise TransportError(f'AssignProcessToJobObject failed ({error_code})')

    return int(job)


def _close_job_handle(job: int) -> None:
    if not _kernel32.CloseHandle(job):
        log.warning('CloseHandle(job) failed with error %s', ctypes.get_last_error())


def _redact(line: str) -> str:
    """Strip the home directory and token-shaped runs from a diagnostic line."""
    home = str(Path.home())
    redacted = line
    variants = {home, home.replace('\\', '/'), home.replace('\\', '\\\\')}
    for variant in sorted(variants, key=len, reverse=True):
        if variant:
            redacted = re.sub(re.escape(variant), '~', redacted, flags=re.IGNORECASE)
    return re.sub(r'[A-Za-z0-9_\-\.=\/+]{24,}', '***', redacted.rstrip('\n'))


def _terminate_uninstalled_child(process: subprocess.Popen) -> None:
    """Fully reap a child that failed before installation on the transport."""
    try:
        if process.poll() is None:
            process.kill()
    except OSError:
        pass
    try:
        process.wait(timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        pass
    for stream in (process.stdin, process.stdout, process.stderr):
        if stream is not None:
            try:
                stream.close()
            except OSError:
                pass


class _Pending:
    __slots__ = ('event', 'response')

    def __init__(self) -> None:
        self.event = threading.Event()
        self.response: dict[str, Any] | None = None


class _OperationHandle:
    """Request interface handed to an operation body and pinned to one generation."""

    def __init__(self, transport: AppServerTransport, generation: int) -> None:
        self._transport = transport
        self._generation = generation
        self._active = True

    def request(self, method: str, params: dict[str, Any]) -> Any:
        if not self._active:
            raise TransportError('provider operation already finished')
        return self._transport._request(self._generation, method, params)

    def _invalidate(self) -> None:
        self._active = False


class AppServerTransport:
    """Own one ``codex app-server`` child and execute atomic provider operations."""

    def __init__(self, command: list[str] | None = None, *, child_ttl: int = CHILD_TTL,
                 init_timeout: float = INIT_TIMEOUT, rpc_timeout: float = RPC_TIMEOUT,
                 codex_home: str | None = None) -> None:
        self._command = command
        self._child_ttl = child_ttl
        self._init_timeout = init_timeout
        self._rpc_timeout = rpc_timeout
        self._codex_home = codex_home

        self._op_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._stdin_lock = threading.Lock()

        self._proc: subprocess.Popen | None = None
        self._job_handle: int | None = None
        self._generation = 0
        self._dead = True
        self._child_started_at = 0.0
        self._next_id = 0
        self._pending: dict[int | str, _Pending] = {}
        self._auth_revision = 0
        self._stderr_ring: deque[str] = deque(maxlen=STDERR_RING_SIZE)

    def run_operation(self, body: Callable[[_OperationHandle], T_]) -> T_:
        """Run one generation-atomic provider operation, retrying once after transport failure."""
        with self._op_lock:
            self._ensure_child()
            for attempt in (0, 1):
                with self._state_lock:
                    generation = self._generation
                operation = _OperationHandle(self, generation)
                try:
                    return body(operation)
                except TransportError:
                    self._kill_child()
                    if attempt == 1:
                        raise
                    self._ensure_child()
                finally:
                    operation._invalidate()
            raise TransportError('unreachable')  # pragma: no cover

    def auth_revision(self) -> int:
        with self._state_lock:
            return self._auth_revision

    def force_restart(self) -> None:
        """Terminate the child so the next operation creates a fresh generation."""
        with self._op_lock:
            self._kill_child()

    def shutdown(self) -> None:
        with self._op_lock:
            self._kill_child()

    def stderr_tail(self) -> list[str]:
        with self._state_lock:
            return list(self._stderr_ring)

    def _ensure_child(self) -> None:
        with self._state_lock:
            alive = self._proc is not None and not self._dead and self._proc.poll() is None
            expired = alive and time.monotonic() - self._child_started_at > self._child_ttl
        if alive and not expired:
            return
        self._kill_child()
        self._spawn()

    def _spawn(self) -> None:
        command = self._command or discover_codex_command()
        environment = dict(os.environ)
        if self._codex_home:
            environment['CODEX_HOME'] = self._codex_home

        creationflags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
        try:
            process = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding='utf-8',
                errors='replace',
                env=environment,
                creationflags=creationflags,
            )
        except OSError as exc:
            raise TransportError(f'spawn failed: {exc}') from exc

        try:
            job = _assign_kill_on_close_job(int(process._handle))  # type: ignore[attr-defined]  # AssignProcessToJobObject needs Popen's Win32 handle
        except TransportError:
            _terminate_uninstalled_child(process)
            raise

        with self._state_lock:
            self._proc = process
            self._job_handle = job
            self._generation += 1
            self._dead = False
            self._child_started_at = time.monotonic()
            generation = self._generation

        threading.Thread(target=self._reader, args=(process, generation), daemon=True).start()
        threading.Thread(target=self._drain_stderr, args=(process, generation), daemon=True).start()

        from ... import __version__
        try:
            initialize_result = self._request(
                generation,
                'initialize',
                {'clientInfo': {'name': 'usage-monitor-for-codex', 'title': 'Usage Monitor for Codex', 'version': __version__}},
                timeout=self._init_timeout,
            )
            log.info('initialize -> OK (%s)', type(initialize_result).__name__)
            self._write_line(json.dumps({'method': 'initialized', 'params': {}}), generation, process)
        except (TransportError, RpcError) as exc:
            self._kill_child()
            raise TransportError(f'handshake failed: {exc}') from exc

    def _kill_child(self) -> None:
        with self._state_lock:
            process = self._proc
            job = self._job_handle
            self._proc = None
            self._job_handle = None
            self._dead = True
            pending_requests = list(self._pending.values())
            self._pending.clear()
        for pending in pending_requests:
            pending.response = None
            pending.event.set()

        if job is not None:
            _close_job_handle(job)
        if process is None:
            return

        try:
            if process.poll() is None:
                process.kill()
        except OSError:
            pass
        try:
            process.wait(timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            pass
        with self._stdin_lock:
            streams = (process.stdin, process.stdout, process.stderr)
            for stream in streams:
                if stream is not None:
                    try:
                        stream.close()
                    except OSError:
                        pass

    def _write_line(self, line: str, generation: int, process: subprocess.Popen) -> None:
        with self._stdin_lock:
            with self._state_lock:
                if generation != self._generation or process is not self._proc or self._dead:
                    raise TransportError('child generation changed')
                stdin = process.stdin
            if stdin is None:
                raise TransportError('child stdin unavailable')
            try:
                stdin.write(line + '\n')
                stdin.flush()
            except (OSError, ValueError) as exc:
                raise TransportError(f'write failed: {exc}') from exc

    def _request(self, generation: int, method: str, params: dict[str, Any], timeout: float | None = None) -> Any:
        pending = _Pending()
        with self._state_lock:
            if generation != self._generation or self._dead or self._proc is None:
                raise TransportError('child generation changed')
            process = self._proc
            self._next_id += 1
            request_id = self._next_id
            self._pending[request_id] = pending

        started = time.monotonic()
        try:
            self._write_line(json.dumps({'id': request_id, 'method': method, 'params': params}), generation, process)
        except TransportError:
            with self._state_lock:
                self._pending.pop(request_id, None)
            raise
        if not pending.event.wait(timeout if timeout is not None else self._rpc_timeout):
            with self._state_lock:
                self._pending.pop(request_id, None)
            log.warning('%s -> timeout after %.1fs', method, time.monotonic() - started)
            self._kill_child()
            raise TransportError(f'{method} timed out')

        response = pending.response
        if response is None:
            raise TransportError('child died during request or sent a protocol error')
        if 'error' in response:
            error = response['error']
            assert isinstance(error, dict)
            log.warning('%s -> rpc error %s', method, error.get('code'))
            raise RpcError(error.get('code'), error.get('message', ''), error.get('data'))
        log.info('%s -> OK (%.2fs)', method, time.monotonic() - started)
        return response['result']

    def _reader(self, process: subprocess.Popen, generation: int) -> None:
        assert process.stdout is not None
        for line in process.stdout:
            if not line.strip():
                continue
            try:
                message = json.loads(line)
                if not isinstance(message, dict):
                    raise TransportError('protocol message is not an object')
                self._dispatch_message(process, generation, message)
            except (ValueError, TransportError):
                log.warning('malformed protocol message from child')
                self._fail_generation(process, generation)
                return
        self._fail_generation(process, generation)

    def _dispatch_message(self, process: subprocess.Popen, generation: int, message: dict[str, Any]) -> None:
        with self._state_lock:
            if generation != self._generation or process is not self._proc or self._dead:
                return

        has_id = 'id' in message
        has_result = 'result' in message
        has_error = 'error' in message
        if has_result or has_error:
            if not has_id or has_result == has_error:
                raise TransportError('malformed response envelope')
            response_id = message['id']
            if isinstance(response_id, bool) or not isinstance(response_id, (int, str)):
                raise TransportError('malformed response id')
            if has_error:
                error = message['error']
                if not isinstance(error, dict) or not isinstance(error.get('message', ''), str):
                    raise TransportError('malformed error envelope')
                if error.get('code') is not None and not isinstance(error.get('code'), int):
                    raise TransportError('malformed error code')
            with self._state_lock:
                if generation != self._generation or process is not self._proc or self._dead:
                    return
                pending = self._pending.pop(response_id, None)
            if pending is not None:
                pending.response = message
                pending.event.set()
            return

        if has_id:
            method = message.get('method')
            if not isinstance(method, str):
                raise TransportError('malformed server request')
            response = {'id': message['id'], 'error': {'code': -32601, 'message': 'method not supported'}}
            self._write_line(json.dumps(response), generation, process)
            return

        method = message.get('method')
        if not isinstance(method, str):
            raise TransportError('malformed notification')
        if method == 'account/updated':
            with self._state_lock:
                if generation == self._generation and process is self._proc and not self._dead:
                    self._auth_revision += 1

    def _fail_generation(self, process: subprocess.Popen, generation: int) -> None:
        with self._state_lock:
            if generation != self._generation or process is not self._proc:
                return
            self._dead = True
            job = self._job_handle
            self._job_handle = None
            pending_requests = list(self._pending.values())
            self._pending.clear()
        for pending in pending_requests:
            pending.response = None
            pending.event.set()
        if job is not None:
            _close_job_handle(job)
        try:
            if process.poll() is None:
                process.kill()
        except OSError:
            pass

    def _drain_stderr(self, process: subprocess.Popen, generation: int) -> None:
        assert process.stderr is not None
        for line in process.stderr:
            with self._state_lock:
                if generation != self._generation or process is not self._proc:
                    return
                self._stderr_ring.append(_redact(line))

