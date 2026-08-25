"""
Status Server
=============

A tiny loopback-only HTTP endpoint that exposes the current usage snapshot
as JSON so local integrations (e.g. an OpenPets plugin) can poll it without
touching the provider APIs themselves.

The server binds ``127.0.0.1`` only, serves from a daemon thread, reads only
the in-memory cache snapshots (no network or disk IO in the request path),
and swallows and logs any request-handling error so a malformed request can
never crash the tray application. The endpoint is optional: a bind failure
(e.g. the port already in use) is logged and the app continues without it.

Frozen JSON contract (``GET /usage`` or ``GET /``)::

    {
      "schema": 1,
      "generated_at": "2026-08-25T12:34:56Z",
      "providers": {
        "claude": {
          "display_name": "Claude",
          "stale": false,
          "error": null,
          "windows": {
            "five_hour": {"utilization": 42, "resets_at": "..."},
            "seven_day": {"utilization": 7,  "resets_at": "..."}
          }
        },
        "codex": {"display_name": "Codex", "stale": false, "error": null, "windows": {}}
      }
    }

Any other path returns 404. Only GET is supported.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Iterable

from .settings import POLL_INTERVAL

__all__ = ['SCHEMA_VERSION', 'build_snapshot', 'StatusServer']

log = logging.getLogger(__name__)

# Report a provider as ``stale`` once its last successful fetch is older than
# this many poll intervals. A small multiple absorbs normal jitter, adaptive
# backoff, and idle pauses without flapping.
STALE_INTERVAL_MULTIPLIER = 3

SCHEMA_VERSION = 1


def _window_entries(usage: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Project the raw usage dict into the contract's ``windows`` mapping.

    Mirrors ``ProviderMonitor._quota_snapshot_env``: every dict entry that
    carries a ``utilization`` field becomes a window; ``extra_usage`` (a
    differently shaped entry) is skipped. Utilization is rounded to an int
    (0 when missing/None) and ``resets_at`` is passed through raw (may be an
    empty string).
    """
    windows: dict[str, dict[str, Any]] = {}
    for key, entry in usage.items():
        if key == 'extra_usage' or not isinstance(entry, dict) or 'utilization' not in entry:
            continue
        windows[key] = {
            'utilization': round(entry.get('utilization', 0) or 0),
            'resets_at': entry.get('resets_at') or '',
        }
    return windows


def _is_stale(last_success_time: float | None, now: float) -> bool | None:
    """Return the staleness flag for a provider.

    ``None`` when the provider has never succeeded (no baseline to compare),
    otherwise ``True`` once the last success is older than the staleness
    threshold.
    """
    if last_success_time is None:
        return None
    threshold = POLL_INTERVAL * STALE_INTERVAL_MULTIPLIER
    return (now - last_success_time) > threshold


def build_snapshot(monitors: Iterable[Any]) -> dict[str, Any]:
    """Build the JSON-serializable status dict from live provider monitors.

    Pure and side-effect free: each monitor's ``cache.snapshot`` is read once
    and the returned structure never references the live cache objects, so it
    is safe to serialize outside any lock. See the module docstring for the
    exact contract.
    """
    now = time.time()
    providers: dict[str, Any] = {}
    for monitor in monitors:
        provider = monitor.provider
        snapshot = monitor.cache.snapshot
        usage = snapshot.usage if isinstance(snapshot.usage, dict) else {}
        providers[provider.provider_id] = {
            'display_name': provider.display_name,
            'stale': _is_stale(snapshot.last_success_time, now),
            'error': snapshot.last_error,
            'windows': _window_entries(usage),
        }

    return {
        'schema': SCHEMA_VERSION,
        'generated_at': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'providers': providers,
    }


class _StatusRequestHandler(BaseHTTPRequestHandler):
    """Serve the in-memory usage snapshot as JSON; never touch the network."""

    # Trim the advertised server banner; the real version lives elsewhere.
    server_version = 'UsageMonitorStatus'
    sys_version = ''

    def do_GET(self) -> None:  # noqa: N802 - name fixed by BaseHTTPRequestHandler
        """Answer ``/`` and ``/usage`` with the JSON snapshot, else 404."""
        try:
            path = self.path.split('?', 1)[0].rstrip('/') or '/'
            if path not in ('/', '/usage'):
                self._send_json(404, {'error': 'not found'})
                return

            snapshot = build_snapshot(self.server.monitors)  # type: ignore[attr-defined]
            self._send_json(200, snapshot)
        except Exception:
            log.exception('status request failed')
            try:
                self._send_json(500, {'error': 'internal error'})
            except Exception:
                # The connection may already be broken; nothing more to do.
                pass

    def _send_json(self, status: int, payload: dict[str, Any]) -> None:
        """Serialize *payload* and write it with a JSON content type."""
        body = json.dumps(payload).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 - signature fixed by base class
        """Silence the default stderr access log; route to the module logger."""
        log.debug('status %s - %s', self.address_string(), format % args)


class StatusServer:
    """Loopback-only JSON status endpoint served from a daemon thread."""

    def __init__(self, monitors: Iterable[Any], port: int) -> None:
        self._monitors = list(monitors)
        self._port = port
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """Bind ``127.0.0.1:<port>`` and start serving in the background.

        Raises ``OSError`` on a bind failure (e.g. port in use); the caller
        decides whether that is fatal (it is not - the endpoint is optional).
        """
        # Bind loopback only - never 0.0.0.0/"" - so the endpoint is never
        # reachable from other machines on the network.
        httpd = ThreadingHTTPServer(('127.0.0.1', self._port), _StatusRequestHandler)
        httpd.monitors = self._monitors  # type: ignore[attr-defined]
        httpd.daemon_threads = True
        thread = threading.Thread(
            target=httpd.serve_forever,
            name='status-server',
            daemon=True,
        )
        thread.start()
        self._httpd = httpd
        self._thread = thread
        log.info('status server listening on http://127.0.0.1:%d/usage', self._port)

    def shutdown(self) -> None:
        """Stop serving and release the socket; safe to call more than once."""
        httpd, self._httpd = self._httpd, None
        thread, self._thread = self._thread, None
        if httpd is not None:
            try:
                httpd.shutdown()
                httpd.server_close()
            except Exception:
                log.exception('status server shutdown failed')
        if thread is not None:
            thread.join(timeout=2)
