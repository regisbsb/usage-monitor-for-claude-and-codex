"""Instance-oriented Codex provider backed by the local Codex app-server."""
from __future__ import annotations

import threading
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from . import api
from .app_server import AppServerTransport
from .cache import UsageCache, _setting
from .codex_cli import CHANGELOG_URL, PROJECT_URL, find_installations, update_cli

__all__ = ['CodexProvider']


class CodexProvider:
    """Own all transport, cache, and maintenance state for one Codex home."""

    provider_id = 'codex'
    display_name = 'Codex'
    cli_display_name = 'Codex'
    icon_name = 'usage_monitor_codex'
    auth_error_glyph = '>!'
    zero_state_glyph = '>_'
    no_auth_message = 'Codex is signed out. Run codex login, then wait for the next refresh.'
    auth_error_label = 'Codex Session Expired'
    auth_error_short = 'Run codex login to sign in again.'
    project_url = PROJECT_URL
    changelog_url = CHANGELOG_URL

    def __init__(self, config_dir: Path, settings: Any) -> None:
        self.config_dir = Path(config_dir)
        self.settings = _provider_settings(settings)
        self._transport = AppServerTransport(codex_home=str(self.config_dir))
        self._provider_lock = threading.RLock()
        self._cache: UsageCache | None = None
        self._closed = False
        self._last_maintenance_check: float | None = None
        self.custom_config = self.config_dir.resolve() != (Path.home() / '.codex').resolve()

    def create_cache(self) -> UsageCache:
        """Return this provider's cache, creating it once."""
        with self._provider_lock:
            if self._cache is None:
                self._cache = UsageCache(self, self.settings)
            return self._cache

    def auth_revision(self) -> int:
        """Return the monotonic account-change revision from app-server notifications."""
        with self._provider_lock:
            return self._transport.auth_revision()

    def fetch_provider_data(self, *, allow_recovery: bool = False) -> api.ProviderFetchResult:
        """Fetch account and quota state in one provider generation."""
        with self._provider_lock:
            if self._closed:
                return api.ProviderFetchResult(
                    usage={'error': 'Could not communicate with the Codex app-server.'},
                    profile=None,
                )
            return api.fetch_provider_data(self._transport, allow_recovery=allow_recovery)

    def refresh_profile(self, cache: Any) -> None:
        """Refresh account state through the cache's serialization boundary."""
        cache.refresh_profile()

    def _read_profile(self) -> dict[str, Any] | None:
        """Read current account state for the provider-local cache."""
        with self._provider_lock:
            if self._closed:
                return None
            return api.refresh_profile(self._transport)

    def run_maintenance(self) -> Any | None:
        """Serialize the official Codex updater against all provider operations."""
        enabled = _setting(
            self.settings,
            'auto_update_cli',
            _setting(self.settings, 'auto_update_codex_cli', True),
        )
        if not enabled:
            return None
        with self._provider_lock:
            if self._closed:
                return None
            now = time.monotonic()
            interval = _setting(
                self.settings,
                'update_interval',
                _setting(self.settings, 'codex_update_interval', 86400),
            )
            if self._last_maintenance_check is not None and now - self._last_maintenance_check < interval:
                return None
            self._last_maintenance_check = now
            self._transport.force_restart()
            return update_cli()

    def find_installations(self) -> list[Any]:
        return find_installations()

    def has_authentication(self) -> bool:
        """Avoid credential-store inspection; account state arrives from app-server."""
        return True

    def result_is_current(self, result: Any) -> bool:
        return True

    def recycle_transport(self) -> None:
        """Discard the child so the next operation starts a fresh generation."""
        with self._provider_lock:
            if not self._closed:
                self._transport.force_restart()

    def shutdown(self) -> None:
        """Stop local child resources; repeated calls are safe."""
        with self._provider_lock:
            if self._closed:
                return
            self._closed = True
            self._transport.shutdown()


def _provider_settings(settings: Any) -> Any:
    """Accept either provider-scoped settings or the combined root object."""
    if isinstance(settings, Mapping):
        providers = settings.get('providers')
    else:
        providers = getattr(settings, 'providers', None)
    if isinstance(providers, Mapping):
        return providers.get('codex', settings)
    if providers is not None:
        return getattr(providers, 'codex', settings)
    return settings
