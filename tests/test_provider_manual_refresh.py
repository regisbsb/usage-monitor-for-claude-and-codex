"""Manual refresh timing and serialization tests for both active caches."""
from __future__ import annotations

import threading
import unittest
from datetime import datetime, timezone
from typing import Any
from unittest.mock import Mock, patch

from usage_monitor.providers.claude import cache as claude_cache
from usage_monitor.providers.codex import cache as codex_cache
from usage_monitor.providers.codex.api import ProviderFetchResult


def _quota(reset: float | None = None) -> dict[str, Any]:
    reset_text = datetime.fromtimestamp(reset, timezone.utc).isoformat() if reset is not None else ''
    return {'seven_day': {'utilization': 12, 'resets_at': reset_text}}


class _Clock:
    wall = 1_800_000_000.0
    elapsed = 500.0

    def time(self) -> float:
        return self.wall

    def monotonic(self) -> float:
        return self.elapsed

    def advance(self, seconds: float) -> None:
        self.wall += seconds
        self.elapsed += seconds


class TestManualRefresh(unittest.TestCase):
    def _cache(self, module: Any, *, poll_fast: int = 120) -> tuple[Any, Mock, _Clock, Any]:
        clock = _Clock()
        fetch = Mock(return_value=_quota())
        settings = {'poll_fast': poll_fast}
        if module is claude_cache:
            api = Mock()
            api.read_access_token.return_value = 'synthetic-token'
            api.fetch_usage = fetch
            cache = module.UsageCache(api, Mock(), settings)
        else:
            provider = Mock()
            provider.fetch_provider_data.side_effect = lambda **_: ProviderFetchResult(fetch(), None)
            cache = module.UsageCache(provider, settings)
        return cache, fetch, clock, patch.object(module, 'time', clock)

    def test_manual_limits_follow_elapsed_time_and_actual_attempts(self) -> None:
        for module in (claude_cache, codex_cache):
            with self.subTest(provider=module.__name__):
                cache, fetch, clock, mock_time = self._cache(module)
                with mock_time:
                    self.assertIsNotNone(cache.update().data)
                    clock.wall += 3600  # Wall-clock changes cannot clear either cooldown.
                    self.assertIsNone(cache.update(manual=True).data)
                    self.assertEqual(cache.snapshot.manual_refresh_reason, 'cooldown')
                    clock.advance(15)
                    self.assertIsNotNone(cache.update(manual=True).data)
                    clock.advance(119)
                    self.assertIsNone(cache.update(manual=True).data)
                    self.assertEqual(fetch.call_count, 2)
                    clock.advance(1)
                    self.assertIsNotNone(cache.update(manual=True).data)
                    self.assertEqual(fetch.call_count, 3)

    def test_floor_starts_when_a_failed_operation_completes(self) -> None:
        for module in (claude_cache, codex_cache):
            with self.subTest(provider=module.__name__):
                cache, fetch, clock, mock_time = self._cache(module)

                def fail_after_wait(*args: Any) -> dict[str, Any]:
                    clock.advance(20)
                    return {'error': 'synthetic transient failure'}

                fetch.side_effect = fail_after_wait
                with mock_time:
                    self.assertIn('error', cache.update().data)
                    clock.advance(14)
                    self.assertIsNone(cache.update(manual=True).data)
                    self.assertEqual(fetch.call_count, 1)
                    clock.advance(1)
                    self.assertIn('error', cache.update(manual=True).data)
                    self.assertEqual(fetch.call_count, 2)

    def test_manual_wait_preserves_backoff_and_force_still_bypasses(self) -> None:
        for module in (claude_cache, codex_cache):
            with self.subTest(provider=module.__name__):
                cache, fetch, clock, mock_time = self._cache(module)
                fetch.return_value = {'error': 'synthetic limit', 'rate_limited': True, 'retry_after': 230}
                with mock_time:
                    self.assertIn('error', cache.update().data)
                    clock.advance(16)
                    self.assertIsNone(cache.update(manual=True).data)
                    self.assertEqual(cache.snapshot.manual_refresh_reason, 'backoff')
                    self.assertEqual(cache.snapshot.manual_refresh_retry_at, clock.wall + 214)
                    self.assertEqual(fetch.call_count, 1)
                    fetch.return_value = _quota()
                    self.assertIsNotNone(cache.update(force=True).data)
                    self.assertEqual(fetch.call_count, 2)

    def test_reset_protection_skips_bad_values_and_keeps_the_manual_allowance(self) -> None:
        for module in (claude_cache, codex_cache):
            with self.subTest(provider=module.__name__):
                cache, fetch, clock, mock_time = self._cache(module)
                reset = clock.wall + 50
                fetch.return_value = {
                    **_quota(reset), 'null': None, 'empty': {'resets_at': ''},
                    'malformed': {'resets_at': ['bad']}, 'naive': {'resets_at': '2026-01-01T00:00:00'},
                }
                with mock_time:
                    cache.update()
                    clock.advance(20)
                    self.assertIsNone(cache.update(manual=True).data)
                    self.assertEqual(cache.snapshot.manual_refresh_reason, 'reset')
                    clock.advance(34)
                    self.assertIsNone(cache.update(manual=True).data)
                    self.assertEqual(cache.snapshot.manual_refresh_retry_at, reset + 5)
                    self.assertEqual(fetch.call_count, 1)
                    clock.advance(1)
                    self.assertIsNotNone(cache.update(manual=True).data)
                    self.assertEqual(fetch.call_count, 2)

    def test_signed_out_claude_does_not_consume_the_manual_allowance(self) -> None:
        cache, fetch, clock, mock_time = self._cache(claude_cache)
        cache._api.read_access_token.return_value = None
        fetch.return_value = {'error': 'synthetic signed-out result'}
        with mock_time:
            self.assertIn('error', cache.update(manual=True).data)
            cache._api.read_access_token.return_value = 'synthetic-token'
            fetch.return_value = _quota()
            clock.advance(15)
            self.assertIsNotNone(cache.update(manual=True).data)
        self.assertEqual(fetch.call_count, 2)

    def test_pending_manual_request_coalesces_with_scheduled_poll_per_provider(self) -> None:
        for module, other in ((claude_cache, codex_cache), (codex_cache, claude_cache)):
            with self.subTest(provider=module.__name__):
                cache, fetch, clock, mock_time = self._cache(module)
                other_cache, other_fetch, _, other_mock_time = self._cache(other)
                fetch_started = threading.Event()
                release = threading.Event()
                waiting = threading.Event()
                lock = cache._lock

                def slow_fetch(*args: Any) -> dict[str, Any]:
                    fetch_started.set()
                    if not release.wait(3):
                        raise TimeoutError('test did not release the blocked fetch')
                    clock.advance(30)
                    return _quota()

                def observe_acquire(*, blocking: bool) -> bool:
                    if blocking:
                        waiting.set()
                    return lock.acquire(blocking=blocking)

                fetch.side_effect = slow_fetch
                cache._lock = Mock(acquire=observe_acquire, release=lock.release)
                results: list[Any] = []
                scheduled = threading.Thread(target=cache.update)
                manual = threading.Thread(target=lambda: results.append(cache.update(manual=True)))
                with mock_time, other_mock_time:
                    scheduled.start()
                    try:
                        self.assertTrue(fetch_started.wait(1))
                        manual.start()
                        self.assertTrue(waiting.wait(1))
                        self.assertIsNotNone(other_cache.update(manual=True).data)
                        other_fetch.assert_called_once()
                    finally:
                        release.set()
                        scheduled.join(3)
                        if manual.ident is not None:
                            manual.join(3)
                self.assertFalse(scheduled.is_alive())
                self.assertFalse(manual.is_alive())
                self.assertEqual([result.data for result in results], [None])
                fetch.assert_called_once()


if __name__ == '__main__':
    unittest.main()
