"""Claude provider adapter for the combined usage monitor."""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Any, Mapping

from .api import ClaudeAPI
from .cache import UsageCache
from .claude_cli import CHANGELOG_URL, PROJECT_URL, ClaudeCLI, RefreshResult

__all__ = ["ClaudeProvider"]


class ClaudeProvider:
    """Provider facade consumed by the shared application supervisor."""

    provider_id = "claude"
    display_name = "Claude"
    cli_display_name = "Claude Code"
    icon_name = "usage_monitor_claude"
    auth_error_glyph = "C!"
    zero_state_glyph = "C"
    project_url = PROJECT_URL
    changelog_url = CHANGELOG_URL

    def __init__(self, config_dir: Path, settings: Any) -> None:
        self.config_dir = Path(config_dir)
        self.custom_config = self.config_dir.resolve() != (Path.home() / '.claude').resolve()
        self.settings = _provider_settings(settings)
        self._cli = ClaudeCLI(self.settings)
        self._api = ClaudeAPI(self.config_dir, self._cli)
        self._shutdown_lock = threading.RLock()
        self._shutdown = False
        self._cache: UsageCache | None = None

    def create_cache(self) -> UsageCache:
        """Return the single cache owned by this provider instance."""
        with self._shutdown_lock:
            if self._cache is None:
                self._cache = UsageCache(self._api, self._cli, self.settings)
            return self._cache

    def auth_revision(self) -> str | None:
        return self._api.auth_revision()

    def has_authentication(self) -> bool:
        """Check for a current OAuth token without spawning the CLI."""
        return self._api.read_access_token() is not None

    def refresh_profile(self, cache: UsageCache) -> None:
        with self._shutdown_lock:
            if not self._shutdown:
                cache.refresh_profile()

    def result_is_current(self, result: Any) -> bool:
        """Whether a successful result belongs to the credentials still active."""
        return getattr(result, "token", None) == self._api.read_access_token()

    def run_maintenance(self) -> RefreshResult | None:
        """Claude has no periodic maintenance; 401 refresh results ride on updates."""
        return None

    def find_installations(self) -> list[Any]:
        return self._cli.find_installations()

    def recycle_transport(self) -> None:
        """Claude uses stateless HTTPS requests and has no transport to recycle."""
        return None

    def shutdown(self) -> None:
        """Release provider resources; safe to call repeatedly."""
        with self._shutdown_lock:
            if self._shutdown:
                return
            self._shutdown = True


def _provider_settings(settings: Any) -> Any:
    """Accept either provider-scoped settings or the combined root object."""
    providers = _setting(settings, "providers", None)
    if isinstance(providers, Mapping):
        return providers.get("claude", settings)
    if providers is not None:
        return getattr(providers, "claude", settings)
    return settings


def _setting(settings: Any, name: str, default: Any) -> Any:
    if isinstance(settings, Mapping):
        return settings.get(name, settings.get(name.upper(), default))
    return getattr(settings, name, getattr(settings, name.upper(), default))
