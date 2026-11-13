"""Forecasts stay on the quota's pacing scale and current window."""
from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from usage_monitor.forecast import record_samples, usage_forecast
from usage_monitor.pacing import parse_work_schedule
from usage_monitor.popup import _snapshot_to_dict
from usage_monitor.providers.claude.cache import CacheSnapshot


def _entry(reset: datetime, pct: float) -> dict:
    return {'resets_at': reset.isoformat(), 'utilization': pct}


class TestForecast(unittest.TestCase):
    def test_new_minute_window_and_decreasing_usage_discard_history(self) -> None:
        reset = datetime(2026, 11, 16, tzinfo=timezone.utc)
        name = 'one_minute'
        history = record_samples({}, {name: _entry(reset, 10)}, reset.timestamp() - 30)
        jitter = reset + timedelta(milliseconds=200)
        history = record_samples(history, {name: _entry(jitter, 20)}, reset.timestamp() - 20)
        self.assertEqual(len(history[name]['samples']), 2)
        history = record_samples(history, {name: _entry(reset + timedelta(minutes=1), 25)}, reset.timestamp() + 20)
        self.assertEqual(history[name]['samples'], ((reset.timestamp() + 20, 25.0),))
        dropped = record_samples(history, {name: _entry(reset + timedelta(minutes=1), 1)}, reset.timestamp() + 30)
        self.assertEqual(dropped[name]['samples'], ((reset.timestamp() + 30, 1.0),))

    def test_samples_are_bounded_and_bad_values_are_ignored(self) -> None:
        reset = datetime(2026, 11, 16, tzinfo=timezone.utc)
        history = {}
        with patch('usage_monitor.forecast.MAX_SAMPLES', 3):
            for index in range(8):
                history = record_samples(history, {'one_hour': _entry(reset, index)}, reset.timestamp() - 30 + index)
        self.assertEqual([pct for _, pct in history['one_hour']['samples']], [5, 6, 7])
        for value in (True, float('nan'), float('inf'), -1, '50'):
            usage = {'one_hour': _entry(reset, value)}
            self.assertEqual(record_samples(history, usage, reset.timestamp() - 1), {})
            self.assertIsNone(usage_forecast('one_hour', usage, history, reset - timedelta(minutes=10)))

    def test_schedule_projection_pauses_on_weekend_and_uses_calendar_ticks(self) -> None:
        local = lambda day, hour: datetime(2026, 11, day, hour).astimezone(timezone.utc)
        reset = local(16, 18)
        now = local(14, 12)
        usage = {'seven_day': _entry(reset, 30)}
        schedule = parse_work_schedule({'fri': [9, 17], 'mon': [9, 17]})
        chart = usage_forecast('seven_day', usage, {}, now, work_schedule=schedule)
        assert chart is not None
        self.assertFalse(chart['runs_out'])
        self.assertEqual(chart['projection'][0][1], 30.0)
        self.assertEqual(chart['projection'][1][1], 30.0)
        self.assertAlmostEqual(chart['projection'][-1][1], 60.0)
        self.assertEqual(len(chart['ticks']), 7)

    def test_popup_uses_the_actual_top_tray_quota_and_respects_exclusions(self) -> None:
        now = datetime(2026, 11, 16, tzinfo=timezone.utc)
        usage = {'one_hour': _entry(now + timedelta(minutes=30), 80), 'seven_day': _entry(now + timedelta(days=3), 25)}
        snapshot = CacheSnapshot(usage, None, now.timestamp(), False, None, 1, record_samples({}, usage, now.timestamp()))
        icon_fields = ['five_hour', 'seven_day:overage']
        with patch('usage_monitor.popup.datetime', wraps=datetime) as clock:
            clock.now.return_value = now
            entries = _snapshot_to_dict(snapshot, installations=[], forecast_icon_fields=icon_fields)['usage']
            excluded = _snapshot_to_dict(snapshot, installations=[], popup_fields=['*', '-seven_day'], forecast_icon_fields=icon_fields)['usage']
            disabled = _snapshot_to_dict(snapshot, installations=[])['usage']
        self.assertEqual([entry['key'] for entry in entries if 'forecast' in entry], ['seven_day'])
        self.assertFalse(any('forecast' in entry for entry in excluded + disabled))
