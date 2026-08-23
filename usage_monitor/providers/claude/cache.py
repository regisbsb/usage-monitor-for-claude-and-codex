"""Thread-safe, token-atomic cache for the Claude provider."""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Any, Mapping

from .api import ClaudeAPI
from .claude_cli import ClaudeCLI, RefreshResult

log = logging.getLogger(__name__)

__all__ = ["CacheSnapshot", "UpdateResult", "UsageCache"]


@dataclass(frozen=True)
class CacheSnapshot:
    usage: dict[str, Any]
    profile: dict[str, Any] | None
    last_success_time: float | None
    refreshing: bool
    last_error: str | None
    version: int


@dataclass(frozen=True)
class UpdateResult:
    data: dict[str, Any] | None
    token_refresh: RefreshResult | None = None
    token: str | None = None


class UsageCache:
    """Cache whose committed profile and usage always belong to one token."""

    def __init__(self, api: ClaudeAPI, cli: ClaudeCLI, settings: Any) -> None:
        self._api = api
        self._cli = cli
        self._poll_interval = _positive_setting(settings, "poll_interval", 180)
        self._poll_fast = _positive_setting(settings, "poll_fast", 120)
        self._max_backoff = _positive_setting(settings, "max_backoff", 900)
        self._lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._profile_lock = threading.Lock()
        self._usage: dict[str, Any] = {}
        self._usage_token: str | None = None
        self._profile: dict[str, Any] | None = None
        self._profile_token: str | None = None
        self._last_success_time: float | None = None
        self._refreshing = False
        self._last_error: str | None = None
        self._version = 0
        self._consecutive_errors = 0
        self._last_failed_token: str | None = None
        self._rate_limit_until = 0.0

    @property
    def usage(self) -> dict[str, Any]:
        return self._usage

    @property
    def profile(self) -> dict[str, Any] | None:
        return self._profile

    @property
    def last_success_time(self) -> float | None:
        return self._last_success_time

    @property
    def refreshing(self) -> bool:
        return self._refreshing

    @property
    def last_error(self) -> str | None:
        return self._last_error

    @property
    def version(self) -> int:
        return self._version

    @property
    def consecutive_errors(self) -> int:
        return self._consecutive_errors

    @property
    def rate_limit_remaining(self) -> float:
        return max(self._rate_limit_until - time.time(), 0)

    @property
    def snapshot(self) -> CacheSnapshot:
        with self._state_lock:
            return CacheSnapshot(
                usage=self._usage,
                profile=self._profile,
                last_success_time=self._last_success_time,
                refreshing=self._refreshing,
                last_error=self._last_error,
                version=self._version,
            )

    def ensure_profile(self, *, bypass_rate_limit: bool = False) -> None:
        token = self._api.read_access_token()
        if self._profile is not None and self._profile_token == token:
            return
        with self._profile_lock:
            token = self._api.read_access_token()
            if self._profile is not None and self._profile_token == token:
                return
            if not bypass_rate_limit and time.time() < self._rate_limit_until:
                return
            with self._lock:
                self._fetch_and_store_profile(token)

    def refresh_profile(self) -> None:
        """Fetch fresh identity independently of usage cooldowns."""
        with self._profile_lock:
            with self._lock:
                self._fetch_and_store_profile(self._api.read_access_token())

    def update(self, *, force: bool = False) -> UpdateResult:
        if not self._lock.acquire(blocking=False):
            return UpdateResult(data=None)
        try:
            return self._update_locked(force=force)
        finally:
            self._lock.release()

    def _fetch_and_store_profile(self, token: str | None) -> None:
        profile = self._api.fetch_profile(token)
        # A credential rewrite during the HTTP request makes the result stale.
        if self._api.read_access_token() != token:
            return
        with self._state_lock:
            if profile is not None:
                if self._usage and self._usage_token != token:
                    self._usage = {}
                    self._usage_token = None
                    self._last_success_time = None
                self._profile = profile
                self._profile_token = token
            elif self._profile_token != token:
                self._profile = None
                self._profile_token = None
            self._version += 1

    def _update_locked(self, *, force: bool) -> UpdateResult:
        now = time.time()
        if self._last_success_time is not None and now < self._last_success_time:
            self._last_success_time = now - self._poll_fast
        if self._rate_limit_until - now > self._max_backoff:
            self._rate_limit_until = now + self._max_backoff
        if not force and self._last_success_time is not None and now - self._last_success_time < self._poll_fast:
            return UpdateResult(data=None)
        if not force and now < self._rate_limit_until:
            return UpdateResult(data=None)

        token = self._api.read_access_token()
        if self._last_failed_token is not None:
            if token == self._last_failed_token:
                return UpdateResult(data=None)
            self._last_failed_token = None

        with self._state_lock:
            self._refreshing = True
            self._version += 1
        try:
            return self._fetch_and_process(token)
        except Exception:
            with self._state_lock:
                self._refreshing = False
                self._version += 1
            raise

    def _fetch_and_process(self, token: str | None) -> UpdateResult:
        data = self._api.fetch_usage(token)
        if "error" in data:
            self._record_error(data)
            if data.get("rate_limited"):
                self._apply_rate_limit_backoff(data)
            token_refresh = None
            if data.get("auth_error"):
                token_refresh, retry_data, retry_token = self._try_token_refresh(token)
                if retry_data is not None:
                    data = retry_data
                if retry_data is not None and "error" not in retry_data:
                    return UpdateResult(retry_data, token_refresh, retry_token)
                if token_refresh is None:
                    self._last_failed_token = token
            with self._state_lock:
                self._refreshing = False
                self._version += 1
            return UpdateResult(data, token_refresh)

        # Never publish data for credentials that changed while in flight.
        if self._api.read_access_token() != token:
            with self._state_lock:
                self._refreshing = False
                self._version += 1
            return UpdateResult(data=None, token=token)
        self._record_success(data, token)
        return UpdateResult(data=data, token=token)

    def _try_token_refresh(
        self, token_before: str | None
    ) -> tuple[RefreshResult | None, dict[str, Any] | None, str | None]:
        result = RefreshResult(True, False, "", "", "")
        current_token = self._api.read_access_token()
        if current_token in (token_before, None):
            result = self._cli.refresh_token()
            if not result.success:
                return None, None, None
            current_token = self._api.read_access_token()
            if current_token == token_before:
                return None, None, None

        data = self._api.fetch_usage(current_token)
        if "error" not in data:
            if self._api.read_access_token() != current_token:
                return result, None, current_token
            self._record_success(data, current_token)
            return result, data, current_token

        self._record_error(data, count=False)
        if data.get("rate_limited"):
            self._apply_rate_limit_backoff(data)
        return result, data, current_token

    def _record_error(self, data: dict[str, Any], *, count: bool = True) -> None:
        with self._state_lock:
            if count:
                self._consecutive_errors += 1
            error = str(data["error"])
            if data.get("server_message"):
                error += f"\n{data['server_message']}"
            self._last_error = error

    def _apply_rate_limit_backoff(self, data: dict[str, Any]) -> None:
        retry_after = data.get("retry_after")
        if isinstance(retry_after, (int, float)) and retry_after > 0:
            delay = min(max(retry_after, self._poll_interval), self._max_backoff)
        else:
            delay = min(
                self._poll_interval * (2 ** max(self._consecutive_errors - 1, 0)),
                self._max_backoff,
            )
        self._rate_limit_until = time.time() + delay

    def _record_success(self, data: dict[str, Any], token: str | None) -> None:
        with self._state_lock:
            self._consecutive_errors = 0
            self._last_error = None
            self._last_success_time = time.time()
            self._rate_limit_until = 0
            self._last_failed_token = None
            if self._profile_token != token:
                self._profile = None
                self._profile_token = None
            self._usage = data
            self._usage_token = token
            self._refreshing = False
            self._version += 1


def _setting(settings: Any, name: str, default: Any) -> Any:
    if isinstance(settings, Mapping):
        return settings.get(name, settings.get(name.upper(), default))
    return getattr(settings, name, getattr(settings, name.upper(), default))


def _positive_setting(settings: Any, name: str, default: int) -> int:
    value = _setting(settings, name, default)
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else default
