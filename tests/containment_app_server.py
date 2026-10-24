"""Synthetic app-server and independently sleeping descendant for Job tests.

PID manifests identify the real Python processes even when a Windows venv
redirector or Store activation inserts a launcher. This fixture never invokes
Codex, reads provider state, or makes network requests.
"""
from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

__all__ = ['main']

_READY_TIMEOUT = 5.0
_DESCENDANT_LIFETIME = 30.0
_LIMITS = {
    'rateLimits': {
        'primary': {'usedPercent': 12, 'windowDurationMins': 300, 'resetsAt': 1752600000},
    },
}
_kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
_kernel32.GetCurrentProcess.argtypes = []
_kernel32.GetCurrentProcess.restype = ctypes.wintypes.HANDLE
_kernel32.GetProcessTimes.argtypes = [
    ctypes.wintypes.HANDLE,
    ctypes.POINTER(ctypes.wintypes.FILETIME),
    ctypes.POINTER(ctypes.wintypes.FILETIME),
    ctypes.POINTER(ctypes.wintypes.FILETIME),
    ctypes.POINTER(ctypes.wintypes.FILETIME),
]
_kernel32.GetProcessTimes.restype = ctypes.wintypes.BOOL


def _creation_time(handle: int) -> int:
    """Return an exact native process creation FILETIME for ownership checks."""
    created = ctypes.wintypes.FILETIME()
    exited = ctypes.wintypes.FILETIME()
    kernel = ctypes.wintypes.FILETIME()
    user = ctypes.wintypes.FILETIME()
    if not _kernel32.GetProcessTimes(handle, ctypes.byref(created), ctypes.byref(exited), ctypes.byref(kernel), ctypes.byref(user)):
        raise OSError(ctypes.get_last_error(), 'Could not read fixture process creation time')
    return (created.dwHighDateTime << 32) | created.dwLowDateTime


def _process_record() -> dict[str, int]:
    """Identify the actual interpreter independently of its launcher."""
    return {
        'pid': os.getpid(),
        'parent_pid': os.getppid(),
        'creation_time': _creation_time(_kernel32.GetCurrentProcess()),
    }


def _publish(state_dir: Path, name: str, record: dict[str, int]) -> None:
    """Atomically publish one process record in the test-owned directory."""
    target = state_dir / name
    temporary = target.with_suffix('.tmp')
    temporary.write_text(json.dumps(record), encoding='utf-8')
    temporary.replace(target)


def _wait_for_descendant(state_dir: Path, process: subprocess.Popen[bytes]) -> None:
    """Require the direct interpreter to acknowledge its identity before serving RPCs."""
    path = state_dir / 'descendant.json'
    deadline = time.monotonic() + _READY_TIMEOUT
    while time.monotonic() < deadline:
        if path.is_file():
            record = json.loads(path.read_text(encoding='utf-8'))
            if (
                record.get('pid') != process.pid
                or record.get('parent_pid') != os.getpid()
                or record.get('creation_time') != _creation_time(int(process._handle))  # type: ignore[attr-defined]
            ):
                raise RuntimeError('Descendant identity does not match its direct interpreter')
            return
        if process.poll() is not None:
            raise RuntimeError('Descendant exited before reporting readiness')
        time.sleep(0.01)
    raise TimeoutError('Descendant did not report readiness')


def _serve() -> None:
    """Answer only the fixed handshake and rate-limit methods needed by the tests."""
    for line in sys.stdin:
        try:
            message = json.loads(line)
        except ValueError:
            continue
        if not isinstance(message, dict) or 'id' not in message:
            continue

        request_id = message['id']
        method = message.get('method')
        if method == 'initialize':
            response = {'id': request_id, 'result': {'serverInfo': {'name': 'containment-fixture'}}}
        elif method == 'account/rateLimits/read':
            response = {'id': request_id, 'result': _LIMITS}
        else:
            response = {'id': request_id, 'error': {'code': -32601, 'message': 'method not found'}}
        sys.stdout.write(json.dumps(response) + '\n')
        sys.stdout.flush()


def main() -> int:
    """Run a synthetic JSONL server or its bounded-lifetime descendant.

    Returns
    -------
    int
        Zero after EOF or the descendant watchdog expires.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state-dir', type=Path, required=True, help='Test-owned root, or the generation directory in descendant mode')
    parser.add_argument('--descendant', action='store_true')
    args = parser.parse_args()
    record = _process_record()

    if args.descendant:
        _publish(args.state_dir, 'descendant.json', record)
        time.sleep(_DESCENDANT_LIFETIME)
        return 0

    state_dir = Path(tempfile.mkdtemp(prefix=f'server-{os.getpid()}-', dir=args.state_dir))
    _publish(state_dir, 'server.json', record)
    process = subprocess.Popen(
        [sys._base_executable, str(Path(__file__).resolve()), '--state-dir', str(state_dir), '--descendant'],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    try:
        _publish(state_dir, 'descendant-launcher.json', {
            'pid': process.pid,
            'creation_time': _creation_time(int(process._handle)),  # type: ignore[attr-defined]  # Trusted Popen process handle.
        })
        _wait_for_descendant(state_dir, process)
    except BaseException:
        if process.poll() is None:
            process.kill()
        process.wait(timeout=_READY_TIMEOUT)
        raise

    # Deliberately leave normal retirement to the transport's Job. The test
    # owns independent process handles and cleans up even after a red assertion.
    _serve()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
