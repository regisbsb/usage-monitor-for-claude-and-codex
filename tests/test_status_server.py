"""Tests for the loopback JSON status snapshot builder."""
from __future__ import annotations

import time
import unittest
from dataclasses import dataclass, field
from typing import Any

from usage_monitor import status_server
from usage_monitor.settings import POLL_INTERVAL
from usage_monitor.status_server import SCHEMA_VERSION, build_snapshot


@dataclass
class _Snapshot:
    usage: dict[str, Any] = field(default_factory=dict)
    last_success_time: float | None = None
    last_error: str | None = None


class _Cache:
    def __init__(self, snapshot: _Snapshot) -> None:
        self._snapshot = snapshot

    @property
    def snapshot(self) -> _Snapshot:
        return self._snapshot


class _Provider:
    def __init__(self, provider_id: str, display_name: str) -> None:
        self.provider_id = provider_id
        self.display_name = display_name


class _Monitor:
    def __init__(self, provider_id: str, display_name: str, snapshot: _Snapshot) -> None:
        self.provider = _Provider(provider_id, display_name)
        self.cache = _Cache(snapshot)


def _monitor(provider_id: str, display_name: str, **snapshot: Any) -> _Monitor:
    return _Monitor(provider_id, display_name, _Snapshot(**snapshot))


class TestBuildSnapshot(unittest.TestCase):
    def test_envelope_shape(self) -> None:
        result = build_snapshot([_monitor('claude', 'Claude', last_success_time=time.time())])

        self.assertEqual(result['schema'], SCHEMA_VERSION)
        self.assertTrue(result['generated_at'].endswith('Z'))
        self.assertIn('claude', result['providers'])

    def test_dynamic_window_keys_included_and_extra_usage_skipped(self) -> None:
        usage = {
            'five_hour': {'utilization': 42, 'resets_at': '2026-08-25T15:00:00Z'},
            'seven_day': {'utilization': 7, 'resets_at': '2026-08-30T00:00:00Z'},
            'seven_day_sonnet': {'utilization': 3, 'resets_at': ''},
            'extra_usage': {'is_enabled': True, 'used_credits': 100},
            'not_a_window': 'ignored',
            'no_utilization': {'resets_at': 'x'},
        }
        result = build_snapshot([_monitor('claude', 'Claude', usage=usage, last_success_time=time.time())])
        windows = result['providers']['claude']['windows']

        self.assertEqual(set(windows), {'five_hour', 'seven_day', 'seven_day_sonnet'})
        self.assertNotIn('extra_usage', windows)
        self.assertEqual(windows['five_hour'], {'utilization': 42, 'resets_at': '2026-08-25T15:00:00Z'})

    def test_utilization_rounded_to_int_and_none_becomes_zero(self) -> None:
        usage = {
            'five_hour': {'utilization': 42.7, 'resets_at': 'x'},
            'seven_day': {'utilization': None, 'resets_at': ''},
        }
        result = build_snapshot([_monitor('claude', 'Claude', usage=usage, last_success_time=time.time())])
        windows = result['providers']['claude']['windows']

        self.assertEqual(windows['five_hour']['utilization'], 43)
        self.assertIsInstance(windows['five_hour']['utilization'], int)
        self.assertEqual(windows['seven_day']['utilization'], 0)

    def test_resets_at_passthrough_defaults_to_empty_string(self) -> None:
        usage = {'five_hour': {'utilization': 10}}
        result = build_snapshot([_monitor('claude', 'Claude', usage=usage, last_success_time=time.time())])

        self.assertEqual(result['providers']['claude']['windows']['five_hour']['resets_at'], '')

    def test_provider_with_no_data_has_empty_windows(self) -> None:
        result = build_snapshot([_monitor('codex', 'Codex')])
        provider = result['providers']['codex']

        self.assertEqual(provider['display_name'], 'Codex')
        self.assertEqual(provider['windows'], {})

    def test_stale_is_none_when_never_succeeded(self) -> None:
        result = build_snapshot([_monitor('claude', 'Claude', last_success_time=None)])

        self.assertIsNone(result['providers']['claude']['stale'])

    def test_stale_false_for_recent_success(self) -> None:
        result = build_snapshot([_monitor('claude', 'Claude', last_success_time=time.time())])

        self.assertFalse(result['providers']['claude']['stale'])

    def test_stale_true_for_old_success(self) -> None:
        old = time.time() - (POLL_INTERVAL * status_server.STALE_INTERVAL_MULTIPLIER) - 60
        result = build_snapshot([_monitor('claude', 'Claude', last_success_time=old)])

        self.assertTrue(result['providers']['claude']['stale'])

    def test_error_passthrough(self) -> None:
        result = build_snapshot([
            _monitor('claude', 'Claude', last_error='boom', last_success_time=time.time()),
            _monitor('codex', 'Codex', last_success_time=time.time()),
        ])

        self.assertEqual(result['providers']['claude']['error'], 'boom')
        self.assertIsNone(result['providers']['codex']['error'])


if __name__ == '__main__':
    unittest.main()
