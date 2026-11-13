"""Forecast samples stay with the provider and account that produced them."""
from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import Mock, patch

from usage_monitor.providers.claude import cache as claude_cache
from usage_monitor.providers.claude.api import ClaudeAPI
from usage_monitor.providers.claude.claude_cli import ClaudeCLI
from usage_monitor.providers.codex import cache as codex_cache
from usage_monitor.providers.codex.api import ProviderFetchResult

_START = datetime(2026, 11, 13, 12, tzinfo=timezone.utc)
_FIRST = _START.timestamp()
_FIELD = 'five_hour'
_RESET = (_START + timedelta(hours=3)).isoformat()


def _usage(utilization: float) -> dict[str, Any]:
    return {_FIELD: {'utilization': utilization, 'resets_at': _RESET}}


def _profile(account: str) -> dict[str, Any]:
    return {'account': {'uuid': account}}


class TestClaudeForecastHistory(unittest.TestCase):
    def setUp(self) -> None:
        self.api = Mock(spec=ClaudeAPI)
        self.api.read_access_token.return_value = 'token-a'
        self.api.fetch_profile.return_value = _profile('account-a')
        self.cache = claude_cache.UsageCache(self.api, Mock(spec=ClaudeCLI), {'forecast_chart': True})

    def _update(self, utilization: float, offset: int = 0) -> None:
        self.api.fetch_usage.return_value = _usage(utilization)
        with patch.object(claude_cache.time, 'time', return_value=_FIRST + offset):
            self.cache.update(force=True)

    def test_only_confirmed_profile_can_accumulate_samples(self) -> None:
        self._update(11)
        self.assertEqual(self.cache.snapshot.history, {})
        self.cache.ensure_profile()
        self._update(20, 60)
        earlier = self.cache.snapshot
        self._update(25, 120)
        self.assertEqual(earlier.history[_FIELD]['samples'], ((_FIRST + 60, 20),))
        self.assertEqual(self.cache.snapshot.history[_FIELD]['samples'], ((_FIRST + 60, 20), (_FIRST + 120, 25)))

    def test_new_credentials_clear_history_even_before_new_profile_is_known(self) -> None:
        self.cache.ensure_profile()
        self._update(12)
        self.api.read_access_token.return_value = 'token-b'
        self._update(30, 60)
        unknown = self.cache.snapshot
        self.assertEqual(unknown.history, {})
        self.assertIsNone(unknown.profile)
        self.assertEqual(unknown.usage, _usage(30))
        self.api.fetch_profile.return_value = _profile('account-b')
        self.cache.ensure_profile()
        self._update(40, 120)
        self.assertEqual(self.cache.snapshot.history[_FIELD]['samples'], ((_FIRST + 120, 40),))

    def test_profile_refresh_with_new_identity_drops_old_samples_immediately(self) -> None:
        self.cache.ensure_profile()
        self._update(12)
        self.api.fetch_profile.return_value = _profile('account-b')
        self.cache.refresh_profile()
        self.assertEqual(self.cache.snapshot.profile, _profile('account-b'))
        self.assertEqual(self.cache.snapshot.history, {})

    def test_signed_out_or_failed_profile_clears_existing_history(self) -> None:
        for profile in ({}, None):
            with self.subTest(profile=profile):
                self.api.fetch_profile.return_value = _profile('account-a')
                self.cache.refresh_profile()
                self._update(12)
                self.api.fetch_profile.return_value = profile
                self.cache.refresh_profile()
                self.assertEqual(self.cache.snapshot.history, {})


class TestCodexForecastHistory(unittest.TestCase):
    def setUp(self) -> None:
        self.provider = Mock()
        self.cache = codex_cache.UsageCache(self.provider, {'forecast_chart': True})

    def _update(self, utilization: float, profile: dict[str, Any] | None, offset: int = 0, *, recovery: bool = False) -> None:
        self.provider.fetch_provider_data.return_value = ProviderFetchResult(_usage(utilization), profile, recovery)
        with patch.object(codex_cache.time, 'time', return_value=_FIRST + offset):
            self.cache.update(force=True)

    def test_account_switch_publishes_new_usage_and_history_together(self) -> None:
        first = _profile('account-a')
        self._update(10, first)
        self._update(25, first, 60)
        old = self.cache.snapshot
        self.assertEqual(old.history[_FIELD]['samples'], ((_FIRST, 10), (_FIRST + 60, 25)))
        second = _profile('account-b')
        self._update(30, second, 120)
        new = self.cache.snapshot
        self.assertEqual(new.profile, second)
        self.assertEqual(new.usage, _usage(30))
        self.assertEqual(new.history[_FIELD]['samples'], ((_FIRST + 120, 30),))

    def test_profile_none_keeps_profile_but_never_associates_new_samples(self) -> None:
        first = _profile('account-a')
        self._update(10, first)
        self._update(15, None, 60)
        self.assertEqual(self.cache.snapshot.profile, first)
        self.assertEqual(self.cache.snapshot.history, {})
        self._update(20, first, 120)
        self.assertEqual(self.cache.snapshot.history[_FIELD]['samples'], ((_FIRST + 120, 20),))

    def test_successful_recovery_with_potentially_stale_identity_records_no_samples(self) -> None:
        first = _profile('account-a')
        self._update(10, first)
        self._update(20, first, 60, recovery=True)
        self.assertEqual(self.cache.snapshot.profile, first)
        self.assertEqual(self.cache.snapshot.usage, _usage(20))
        self.assertEqual(self.cache.snapshot.history, {})

    def test_profile_only_changes_and_signed_out_usage_clear_samples(self) -> None:
        first = _profile('account-a')
        self._update(10, first)
        self.provider._read_profile.return_value = _profile('account-b')
        self.cache.refresh_profile()
        self.assertEqual(self.cache.snapshot.history, {})
        self._update(20, _profile('account-b'), 60)
        self._update(25, {}, 120)
        self.assertEqual(self.cache.snapshot.profile, {})
        self.assertEqual(self.cache.snapshot.history, {})

    def test_history_is_opt_in_and_each_cache_owns_its_samples(self) -> None:
        first = _profile('account-a')
        self._update(20, first)
        disabled = codex_cache.UsageCache(self.provider, {})
        disabled.update(force=True)
        self.assertEqual(disabled.snapshot.history, {})
        another = codex_cache.UsageCache(self.provider, {'forecast_chart': True})
        self.provider.fetch_provider_data.return_value = ProviderFetchResult(_usage(80), first)
        with patch.object(codex_cache.time, 'time', return_value=_FIRST + 60):
            another.update(force=True)
        self.assertEqual(self.cache.snapshot.history[_FIELD]['samples'], ((_FIRST, 20),))
        self.assertEqual(another.snapshot.history[_FIELD]['samples'], ((_FIRST + 60, 80),))


if __name__ == '__main__':
    unittest.main()
