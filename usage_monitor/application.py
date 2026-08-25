"""
Application Supervisor
======================

Coordinates provider monitors and the process-wide pywebview lifecycle.
"""
from __future__ import annotations

import threading
import traceback
from typing import Any, Iterable

import logging

from .monitor import ProviderMonitor, crash_log
from .providers.base import Provider
from .settings import STATUS_SERVER_ENABLED, STATUS_SERVER_PORT, ProviderSettings
from .status_server import StatusServer

__all__ = ['AppSupervisor']

log = logging.getLogger(__name__)


class AppSupervisor:
    """Own every tray icon and guarantee process-wide quit and restart."""

    def __init__(self, providers: Iterable[tuple[Provider, ProviderSettings]]) -> None:
        provider_pairs = list(providers)
        self._stop_event = threading.Event()
        self._lifecycle_lock = threading.Lock()
        self._stopped = False
        self.restart_requested = False
        self._status_server: StatusServer | None = None
        self.providers = [provider for provider, settings in provider_pairs if settings.enabled]
        enabled_pairs = [(provider, settings) for provider, settings in provider_pairs if settings.enabled]
        self.monitors = [ProviderMonitor(provider, settings, self) for provider, settings in enabled_pairs]

        if not self.monitors:
            raise ValueError('At least one provider must be enabled')

    def request_quit(self) -> None:
        """Request a process-wide stop from either provider icon."""
        self._stop_event.set()

    def request_restart(self) -> None:
        """Request one process-wide restart after both monitors stop."""
        self.restart_requested = True
        self._stop_event.set()

    def refresh_menus(self) -> None:
        """Re-render every provider menu after shared process state changes."""
        for monitor in self.monitors:
            try:
                monitor.icon.update_menu()
            except Exception:
                pass

    def run(self) -> None:
        """Start every icon detached and wait until quit or restart is requested."""
        started: list[ProviderMonitor] = []
        try:
            for monitor in self.monitors:
                monitor.start_detached()
                started.append(monitor)
            self._start_status_server()
            self._stop_event.wait()
        except Exception:
            crash_log(traceback.format_exc())
            self._stop_event.set()
        finally:
            self.stop()

    def _start_status_server(self) -> None:
        """Start the optional loopback status endpoint if enabled.

        The endpoint is a best-effort convenience for local integrations; a
        bind failure (e.g. the port already in use) is logged and the app
        keeps running without it, never fatally.
        """
        if not STATUS_SERVER_ENABLED:
            return
        server = StatusServer(self.monitors, STATUS_SERVER_PORT)
        try:
            server.start()
        except OSError as exc:
            log.warning('status server disabled (bind failed on port %d): %s', STATUS_SERVER_PORT, exc)
            return
        except Exception:
            log.exception('status server failed to start')
            return
        self._status_server = server

    def stop(self) -> None:
        """Stop every icon and provider exactly once, including partial startup."""
        with self._lifecycle_lock:
            if self._stopped:
                return
            self._stopped = True
            self._stop_event.set()
            if self._status_server is not None:
                try:
                    self._status_server.shutdown()
                except Exception:
                    pass
                self._status_server = None
            for monitor in self.monitors:
                try:
                    monitor.stop()
                except Exception:
                    pass
            for provider in self.providers:
                try:
                    provider.shutdown()
                except Exception:
                    pass
