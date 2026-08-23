"""
Provider Contracts
==================

Structural protocols shared by independently scheduled provider monitors.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

__all__ = ['Provider', 'ProviderCache']


class ProviderCache(Protocol):
    """Cache surface consumed by the shared popup and monitor."""

    @property
    def profile(self) -> dict[str, Any] | None: ...

    @property
    def last_success_time(self) -> float | None: ...

    @property
    def consecutive_errors(self) -> int: ...

    @property
    def rate_limit_remaining(self) -> float: ...

    @property
    def snapshot(self) -> Any: ...

    def ensure_profile(self, *, bypass_rate_limit: bool = False) -> None: ...

    def refresh_profile(self) -> None: ...

    def update(self, *, force: bool = False) -> Any: ...


class Provider(Protocol):
    """Instance-owned authentication, transport, cache, and maintenance boundary."""

    provider_id: str
    display_name: str
    icon_name: str
    auth_error_glyph: str
    zero_state_glyph: str
    project_url: str
    changelog_url: str
    config_dir: Path
    custom_config: bool

    def create_cache(self) -> Any: ...

    def auth_revision(self) -> object: ...

    def has_authentication(self) -> bool: ...

    def refresh_profile(self, cache: Any) -> None: ...

    def result_is_current(self, result: Any) -> bool: ...

    def run_maintenance(self) -> Any | None: ...

    def find_installations(self) -> list[Any]: ...

    def recycle_transport(self) -> None: ...

    def shutdown(self) -> None: ...
