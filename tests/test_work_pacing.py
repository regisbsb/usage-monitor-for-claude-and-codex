"""Work schedules pace only the configured provider and eligible quotas."""
from __future__ import annotations

import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from usage_monitor import settings
from usage_monitor.formatting import PERIOD_5H, PERIOD_7D, divider_positions, elapsed_fraction
from usage_monitor.pacing import parse_work_schedule
from usage_monitor.popup import _snapshot_to_dict
from usage_monitor.providers.claude.cache import CacheSnapshot


def _local(day: int, hour: int) -> datetime:
    return datetime(2026, 11, day, hour).astimezone(timezone.utc)


class TestWorkPacing(unittest.TestCase):
    def test_weekend_and_lunch_pause_the_marker(self) -> None:
        schedule = parse_work_schedule({'mon': [[9, 12], [13, 16]], 'fri': [9, 15]})
        reset = _local(16, 20).isoformat()
        fraction = elapsed_fraction(reset, PERIOD_7D, field='seven_day', work_schedule=schedule)
        assert fraction is not None
        self.assertAlmostEqual(fraction(_local(14, 12)), 0.5)
        self.assertAlmostEqual(fraction(_local(16, 12)), 0.75)
        self.assertAlmostEqual(fraction(_local(16, 13)), 0.75)
        self.assertEqual(divider_positions(reset, PERIOD_7D, field='seven_day', work_schedule=schedule), [0.5])

    def test_overlapping_overnight_slots_are_counted_once(self) -> None:
        schedule = parse_work_schedule({'sun': [22.5, 4], 'mon': [[1, 5], [8, 10]]})
        reset = _local(16, 20).isoformat()
        fraction = elapsed_fraction(reset, 86400, work_schedule=schedule)
        assert fraction is not None
        self.assertAlmostEqual(fraction(_local(16, 5)), 6.5 / 8.5)
        self.assertEqual(fraction(_local(16, 10)), 1.0)

    def test_unmatched_short_and_empty_schedules_keep_existing_guides(self) -> None:
        reset = _local(16, 20).isoformat()
        schedule = parse_work_schedule({'mon': [9, 17]}, ('seven_day_*',))
        self.assertEqual(divider_positions(reset, PERIOD_7D, 5, field='seven_day', work_schedule=schedule), [0.2, 0.4, 0.6, 0.8])
        self.assertEqual(divider_positions(reset, PERIOD_5H, field='seven_day_variant', work_schedule=schedule), [0.2, 0.4, 0.6, 0.8])
        self.assertEqual(divider_positions(reset, PERIOD_7D, 5, work_schedule=parse_work_schedule({})), [0.2, 0.4, 0.6, 0.8])
        matched = elapsed_fraction(reset, PERIOD_7D, field='seven_day_variant', work_schedule=schedule)
        assert matched is not None
        self.assertEqual(matched(_local(16, 9)), 0.0)

    def test_provider_overrides_feed_independent_popup_pacing(self) -> None:
        with patch.object(settings, '_S', {'active_schedule': {'mon': [9, 17]}}), patch.object(
            settings, '_PROVIDER_SECTIONS', {'codex': {'active_schedule': {}}},
        ):
            claude = settings.get_provider_settings('claude')
            codex = settings.get_provider_settings('codex')
        snapshot = CacheSnapshot(
            usage={'seven_day': {'utilization': 25, 'resets_at': _local(16, 20).isoformat()}}, profile=None,
            last_success_time=None, refreshing=False, last_error=None, version=0,
        )
        with patch('usage_monitor.formatting.datetime', wraps=datetime) as clock:
            clock.now.return_value = _local(14, 12)
            claude_bar = _snapshot_to_dict(snapshot, installations=[], work_schedule=claude.work_schedule)['usage'][0]
            codex_bar = _snapshot_to_dict(snapshot, installations=[], work_schedule=codex.work_schedule)['usage'][0]
        self.assertEqual(claude_bar['marker_rel'], 0.0)
        self.assertTrue(claude_bar['warn'])
        self.assertGreater(codex_bar['marker_rel'], 0.25)
        self.assertFalse(codex_bar['warn'])

    def test_bad_schedule_does_not_remove_other_settings(self) -> None:
        for schedule in ({'mon': [False, 17]}, {'fri': [9, float('nan')]}, {'sat': [24, 3]}, {'sun': [5, 5]}, {'funday': []}):
            with self.subTest(schedule=schedule), patch.object(settings, 'ctypes') as native:
                data = settings._validate({'active_schedule': schedule, 'active_schedule_fields': ['seven_day_*'], 'poll_fast': 60}, Path('test.json'))
                self.assertEqual(data, {'active_schedule_fields': ['seven_day_*'], 'poll_fast': 60})
                native.windll.user32.MessageBoxW.assert_called_once()
