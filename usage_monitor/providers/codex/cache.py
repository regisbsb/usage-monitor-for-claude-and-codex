"""Thread-safe, provider-local cache for Codex account and quota state."""
from __future__ import annotations

import logging
import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from ...forecast import record_samples
from ...refresh import ManualRefreshPolicy
from .api import ProviderFetchResult

__all__ = ['CacheSnapshot', 'UpdateResult', 'UsageCache']

log = logging.getLogger(__name__)


def _setting(settings: Any, name: str, default: Any) -> Any:
    """Read a provider setting from mapping or attribute based settings."""
    candidate = settings
    if isinstance(candidate, Mapping):
        providers = candidate.get('providers')
        if isinstance(providers, Mapping):
            candidate = providers.get('codex', candidate)
        if isinstance(candidate, Mapping):
            return candidate.get(name.lower(), candidate.get(name, default))
    return getattr(candidate, name.lower(), getattr(candidate, name, default))


@dataclass(frozen=True)
class CacheSnapshot:
    """Immutable, generation-consistent cache state for one provider."""

    usage: dict[str, Any]
    profile: dict[str, Any] | None
    last_success_time: float | None
    refreshing: bool
    last_error: str | None
    version: int
    history: dict[str, dict[str, Any]] = field(default_factory=dict)
    manual_refresh_reason: str | None = None
    manual_refresh_retry_at: float | None = None


@dataclass(frozen=True)
class UpdateResult:
    """Result of an update, with ``None`` when the request was skipped."""

    data: dict[str, Any] | None


class UsageCache:
    """Serialize Codex refreshes and atomically publish account plus quota data."""

    def __init__(self, provider: Any, settings: Any) -> None:
        self._provider = provider
        self._poll_interval = _setting(settings, 'POLL_INTERVAL', 180)
        self._poll_fast = _setting(settings, 'POLL_FAST', 120)
        self._max_backoff = _setting(settings, 'MAX_BACKOFF', 900)
        self._forecast_chart = _setting(settings, 'FORECAST_CHART', False) is True

        self._lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._profile_lock = threading.Lock()
        self._usage: dict[str, Any] = {}
        self._history: dict[str, dict[str, Any]] = {}
        self._profile: dict[str, Any] | None = None
        self._last_success_time: float | None = None
        self._refreshing = False
        self._last_error: str | None = None
        self._version = 0
        self._consecutive_errors = 0
        self._recovery_attempted = False
        self._rate_limit_until = 0.0
        self._manual_refresh = ManualRefreshPolicy()

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
            reason, retry_at = self._manual_refresh_wait(time.time())
            return CacheSnapshot(
                usage=self._usage,
                profile=self._profile,
                last_success_time=self._last_success_time,
                refreshing=self._refreshing,
                last_error=self._last_error,
                version=self._version,
                history=self._history,
                manual_refresh_reason=reason,
                manual_refresh_retry_at=retry_at,
            )

    def ensure_profile(self, *, bypass_rate_limit: bool = False) -> None:
        """Fetch account state once, without racing a combined update."""
        if self._profile is not None:
            return
        with self._profile_lock:
            if self._profile is not None:
                return
            if not bypass_rate_limit and time.time() < self._rate_limit_until:
                return
            with self._lock:
                if self._profile is None:
                    self._store_profile(self._provider._read_profile())

    def refresh_profile(self) -> None:
        """Refresh account state independently of usage cooldowns."""
        with self._profile_lock:
            with self._lock:
                self._store_profile(self._provider._read_profile())

    def update_codex_cli(self) -> Any:
        """Compatibility hook delegating maintenance to the owning provider."""
        with self._lock:
            return self._provider.run_maintenance()

    def update(self, *, force: bool = False, manual: bool = False) -> UpdateResult:
        """Refresh usage, allowing manual requests to wait for a running poll.

        Forced updates are reserved for confirmed account switches. Manual
        refreshes may skip the scheduled cooldown, but recheck their own
        limits and the provider backoff after acquiring the update lock.
        """
        if force and manual:
            raise ValueError('Manual refresh cannot force an update')
        if not self._lock.acquire(blocking=manual):
            return UpdateResult(data=None)
        try:
            return self._update_locked(force=force, manual=manual)
        finally:
            self._lock.release()

    def _manual_refresh_wait(self, now: float) -> tuple[str | None, float | None]:
        """Read the refresh gate while holding the state lock."""
        return self._manual_refresh.wait(
            self._usage, now=now, monotonic_now=time.monotonic(), poll_fast=self._poll_fast, backoff_until=self._rate_limit_until,
        )

    def _finish_update_locked(self) -> None:
        """Publish the end of a usage operation while holding the state lock."""
        self._manual_refresh.last_completion = time.monotonic()
        self._refreshing = False
        self._version += 1

    def _update_locked(self, *, force: bool, manual: bool) -> UpdateResult:
        now = time.time()
        if self._last_success_time is not None and now < self._last_success_time:
            self._last_success_time = now - self._poll_fast
        if self._rate_limit_until - now > self._max_backoff:
            self._rate_limit_until = now + self._max_backoff

        if not (force or manual) and self._last_success_time is not None and time.time() - self._last_success_time < self._poll_fast:
            return UpdateResult(data=None)
        if not force and time.time() < self._rate_limit_until:
            return UpdateResult(data=None)

        if manual:
            with self._state_lock:
                reason, _retry_at = self._manual_refresh_wait(now)
                if reason is not None:
                    return UpdateResult(data=None)

        with self._state_lock:
            if manual:
                # The combined account and quota operation goes through app-server.
                self._manual_refresh.last_manual_attempt = time.monotonic()
            self._refreshing = True
            self._version += 1

        try:
            return self._fetch_and_process()
        except Exception:
            log.exception('unexpected Codex provider update failure')
            data = {'error': 'Could not communicate with the Codex app-server.'}
            self._record_error_state(data, None, False)
            return UpdateResult(data=data)

    def _fetch_and_process(self) -> UpdateResult:
        with self._state_lock:
            allow_recovery = not self._recovery_attempted
        result: ProviderFetchResult = self._provider.fetch_provider_data(allow_recovery=allow_recovery)
        data = result.usage
        if 'error' in data:
            self._record_error_state(data, result.profile, result.recovery_attempted)
            return UpdateResult(data=data)

        self._record_success(data, result.profile, recovery_attempted=result.recovery_attempted)
        return UpdateResult(data=data)

    def _record_error_state(
        self,
        data: dict[str, Any],
        profile: dict[str, Any] | None,
        recovery_attempted: bool,
    ) -> None:
        with self._state_lock:
            self._consecutive_errors += 1
            error = str(data['error'])
            server_message = data.get('server_message')
            if server_message:
                error += f'\n{server_message}'
            self._last_error = error

            if data.get('rate_limited'):
                retry_after = data.get('retry_after')
                if isinstance(retry_after, (int, float)) and retry_after > 0:
                    delay = min(max(retry_after, self._poll_interval), self._max_backoff)
                else:
                    delay = min(self._poll_interval * (2 ** max(self._consecutive_errors - 1, 0)), self._max_backoff)
                self._rate_limit_until = time.time() + delay

            self._store_profile_locked(profile)
            if recovery_attempted or data.get('auth_error') or data.get('no_auth'):
                self._history = {}
            if recovery_attempted:
                self._recovery_attempted = True
            self._finish_update_locked()

    def _record_success(self, data: dict[str, Any], profile: dict[str, Any] | None, *, recovery_attempted: bool = False) -> None:
        with self._state_lock:
            self._consecutive_errors = 0
            self._last_error = None
            self._last_success_time = time.time()
            self._rate_limit_until = 0
            self._recovery_attempted = False
            self._store_profile_locked(profile)
            # Recovery can preserve the pre-refresh profile when the account
            # read after reauthentication is inconclusive. Only a normal
            # cycle with fresh identity can attribute its quota samples.
            if self._forecast_chart and not recovery_attempted and _account_uuid(profile):
                self._history = record_samples(self._history, data, self._last_success_time)
            else:
                self._history = {}
            self._usage = data
            self._finish_update_locked()

    def _store_profile(self, profile: dict[str, Any] | None) -> None:
        with self._state_lock:
            if profile is None and not self._history:
                return
            self._store_profile_locked(profile)
            self._version += 1

    def _store_profile_locked(self, profile: dict[str, Any] | None) -> None:
        previous_uuid = _account_uuid(self._profile)
        new_uuid = _account_uuid(profile)
        if new_uuid is None or new_uuid != previous_uuid:
            self._history = {}
        if profile is None:
            return
        if new_uuid != previous_uuid:
            self._recovery_attempted = False
        self._profile = profile


def _account_uuid(profile: dict[str, Any] | None) -> str | None:
    """Return the confirmed account fingerprint from the normalized profile."""
    account = profile.get('account') if isinstance(profile, dict) else None
    uuid = account.get('uuid') if isinstance(account, dict) else None
    return uuid if isinstance(uuid, str) and uuid.strip() else None
