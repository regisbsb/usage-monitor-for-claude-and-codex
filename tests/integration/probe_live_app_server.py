"""
Live App-Server Probe
=====================

Opt-in integration probe: spawns the real ``codex app-server``, performs the
handshake, reads account and rate limits, and prints sanitized JSON shapes.
Run explicitly: ``python tests/integration/probe_live_app_server.py``.
Never run by unittest discovery (filename does not match ``test*.py``).
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any


REQUESTS = [
    ('account/read', {'refreshToken': False}),
    ('account/rateLimits/read', {}),
]
SENSITIVE_KEY_PARTS = ('authorization', 'credential', 'secret', 'token')
PRIVATE_VALUE_KEYS = frozenset({
    'balance', 'email', 'hasCredits', 'limitId', 'limitName', 'name',
    'planType', 'rateLimitReachedType', 'resetsAt', 'unlimited', 'usedPercent',
})


def _redact_user_paths(value: str) -> str:
    """Redact home-directory prefixes from arbitrary diagnostic strings."""
    home = str(Path.home())
    if home:
        value = re.sub(re.escape(home), '~', value, flags=re.IGNORECASE)
    value = re.sub(r'(?i)[A-Z]:[\\/]Users[\\/][^\\/\s"\']+', '~', value)
    value = re.sub(r'(?i)/mnt/[a-z]/Users/[^/\s"\']+', '~', value)
    return re.sub(r'/home/[^/\s"\']+', '~', value)


def sanitize(value: Any, key: str = '') -> Any:
    """Replace personal and credential-shaped response values.

    Parameters
    ----------
    value
        JSON-compatible value to sanitize.
    key
        Dictionary key associated with ``value``.

    Returns
    -------
    Any
        A recursively sanitized copy.
    """
    if any(part in key.casefold() for part in SENSITIVE_KEY_PARTS):
        return '<redacted>'
    if key in PRIVATE_VALUE_KEYS:
        return '<redacted>'
    if any(part in key.casefold() for part in ('path', 'directory', 'codexhome', 'cwd')):
        return '<redacted-path>'
    if isinstance(value, dict):
        return {item_key: sanitize(item_value, item_key) for item_key, item_value in value.items()}
    if isinstance(value, list):
        return [sanitize(item) for item in value]
    if isinstance(value, str):
        return _redact_user_paths(value)
    return value


def main() -> int:
    """Run the live app-server wire probe.

    Returns
    -------
    int
        Process exit code: zero on success, nonzero on discovery or timeout
        failure.
    """
    codex = shutil.which('codex')
    if not codex:
        print('codex CLI not found on PATH', file=sys.stderr)
        return 1

    proc = subprocess.Popen(
        [codex, 'app-server'],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        encoding='utf-8',
    )
    assert proc.stdin is not None and proc.stdout is not None

    def send(message: dict[str, Any]) -> None:
        proc.stdin.write(json.dumps(message) + '\n')
        proc.stdin.flush()

    responses: dict[int, dict[str, Any]] = {}
    arrived = threading.Condition()

    def reader() -> None:
        for line in proc.stdout:
            try:
                message = json.loads(line)
            except ValueError:
                print(f'NON-JSON LINE: {line[:80]!r}')
                continue
            if 'id' in message and ('result' in message or 'error' in message):
                with arrived:
                    responses[message['id']] = message
                    arrived.notify_all()
            else:
                print(f'SERVER MESSAGE: method={message.get("method")!r} has_id={"id" in message}')

    def wait_for(request_id: int) -> bool:
        with arrived:
            return arrived.wait_for(lambda: request_id in responses, timeout=30)

    try:
        threading.Thread(target=reader, daemon=True).start()

        send({'id': 0, 'method': 'initialize', 'params': {'clientInfo': {'name': 'usage-monitor-probe', 'version': '0.0.0'}}})
        if not wait_for(0):
            print('initialize timed out', file=sys.stderr)
            return 1
        send({'method': 'initialized', 'params': {}})

        for request_id, (method, params) in enumerate(REQUESTS, start=1):
            send({'id': request_id, 'method': method, 'params': params})
            if not wait_for(request_id):
                print(f'{method} timed out', file=sys.stderr)
                return 1

        for request_id in sorted(responses):
            print(f'--- response {request_id} ---')
            print(json.dumps(sanitize(responses[request_id]), indent=2))
        return 0
    finally:
        proc.kill()
        proc.wait(timeout=5)


if __name__ == '__main__':
    raise SystemExit(main())


