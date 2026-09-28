"""Regression coverage for selectively ported upstream behavior."""
from __future__ import annotations

import io
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import requests

from test_monitor import _make_monitor
from usage_monitor.formatting import expand_popup_fields, is_active_quota, resolve_display_fields
from usage_monitor.providers.claude.api import ClaudeAPI, merge_scoped_limits
from usage_monitor.verbose import _redact_home, setup_console


class TestIdlePolling(unittest.TestCase):
    """Each provider retains its own cadence and reset schedule while idle."""

    def test_only_away_provider_slows(self) -> None:
        claude = _make_monitor('claude')
        codex = _make_monitor('codex')
        claude.settings = replace(claude.settings, idle_interval=900)
        codex.settings = replace(codex.settings, idle_interval=900)
        with patch.object(claude, '_polling_throttled', return_value=True), \
             patch.object(codex, '_polling_throttled', return_value=False):
            self.assertEqual(claude._calculate_poll_interval(), 900)
            self.assertEqual(codex._calculate_poll_interval(), codex.settings.poll_interval)

    def test_overdue_reset_keeps_normal_cadence(self) -> None:
        monitor = _make_monitor()
        past = (datetime.now(timezone.utc) - timedelta(seconds=10)).isoformat()
        monitor._last_response = {'five_hour': {'utilization': 0, 'resets_at': past}}
        with patch.object(monitor, '_polling_throttled', return_value=True):
            self.assertTrue(monitor._reset_overdue())
            self.assertEqual(monitor._calculate_poll_interval(), monitor.settings.poll_interval)

    def test_visible_popup_preserves_normal_cadence(self) -> None:
        monitor = _make_monitor()
        monitor._popup_open = True
        with patch('usage_monitor.monitor.is_workstation_locked', return_value=False), \
             patch('usage_monitor.monitor.is_screensaver_running', return_value=False), \
             patch('usage_monitor.monitor.get_idle_seconds', return_value=9999):
            self.assertFalse(monitor._polling_throttled())


class TestEventResetValues(unittest.TestCase):
    """Null reset windows must remain valid subprocess environment values."""

    def test_reset_and_threshold_commands_receive_empty_reset(self) -> None:
        monitor = _make_monitor()
        monitor.settings = replace(monitor.settings, on_reset_command=['reset'], on_threshold_command=['threshold'])
        monitor._first_update_done = True
        with patch('usage_monitor.monitor.run_event_command') as run:
            monitor._run_reset_command('five_hour', 0, 95, data={}, entry={'resets_at': None})
            monitor._run_threshold_command('five_hour', 90, 80, {'resets_at': None}, 'title', 'message')
        self.assertEqual([call.args[1]['USAGE_MONITOR_RESETS_AT'] for call in run.call_args_list], ['', ''])


class TestActiveQuotas(unittest.TestCase):
    """Announced code names stay hidden until active; scoped limits remain visible."""

    def test_inactive_code_name_hidden_from_display_and_icons(self) -> None:
        data = {
            'nimbus_quill': {'utilization': 0, 'resets_at': None},
            'five_hour': {'utilization': 0, 'resets_at': None},
            'future_code': {'utilization': 0, 'resets_at': '2026-10-01T00:00:00+00:00'},
        }
        self.assertEqual(expand_popup_fields(['*'], data), ['five_hour', 'future_code'])
        self.assertEqual(resolve_display_fields([], data, 3), ['five_hour', 'future_code', None])

    def test_account_limit_marker_preserves_unparseable_inactive_field(self) -> None:
        entry = {'utilization': 0, 'resets_at': None, 'from_account_limits': True}
        self.assertTrue(is_active_quota('monthly_model', entry))
        self.assertFalse(is_active_quota('monthly_model', {'utilization': 0, 'resets_at': None}))

    def test_filter_also_applies_to_event_variables(self) -> None:
        monitor = _make_monitor()
        data = {
            'announced_code': {'utilization': 0, 'resets_at': None},
            'five_hour': {'utilization': 0, 'resets_at': None},
        }
        env = monitor._quota_snapshot_env(data)
        self.assertNotIn('USAGE_MONITOR_UTILIZATION_ANNOUNCED_CODE', env)
        self.assertEqual(env['USAGE_MONITOR_RESETS_AT_FIVE_HOUR'], '')

    def test_merged_scoped_limit_gets_origin_marker(self) -> None:
        data = {
            'five_hour': {'utilization': 10, 'resets_at': '2026-10-01T00:00:00+00:00'},
            'limits': [
                {'group': 'base', 'resets_at': '2026-10-01T00:00:00+00:00'},
                {'group': 'base', 'scope': {'model': {'display_name': 'Sonnet'}}, 'percent': 0, 'resets_at': None},
            ],
        }
        merged = merge_scoped_limits(data)
        self.assertTrue(merged['five_hour_sonnet']['from_account_limits'])


class TestClaudeCertificates(unittest.TestCase):
    """Claude classifies certificate failures before generic connection failures."""

    def test_certificate_error_is_distinct(self) -> None:
        with TemporaryDirectory() as tmp:
            api = ClaudeAPI(Path(tmp), object())
            with patch.object(api, 'api_headers', return_value={'Authorization': 'Bearer hidden'}), \
                 patch.object(api, '_get', side_effect=requests.exceptions.SSLError('certificate failed')):
                result = api.fetch_usage()
        self.assertEqual(result['error'], 'Could not verify the Anthropic API certificate.')


class TestVerboseOutput(unittest.TestCase):
    """Redirected streams and alternate home spellings remain safe to share."""

    def test_redirected_streams_do_not_open_console(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with patch('usage_monitor.verbose._redirected_handle', side_effect=[11, 12]), \
             patch('usage_monitor.verbose._stream_from_handle', side_effect=[stdout, stderr]), \
             patch('usage_monitor.verbose.sys'), \
             patch('usage_monitor.verbose.ctypes') as ctypes, \
             patch('builtins.open') as opened:
            setup_console()
        opened.assert_not_called()
        ctypes.windll.kernel32.AttachConsole.assert_not_called()

    def test_resolved_home_spelling_is_redacted(self) -> None:
        with patch('usage_monitor.verbose._home_spellings', return_value=(r'C:\Users\regis', r'D:\profiles\regis')):
            self.assertEqual(_redact_home(r'D:\profiles\regis\.claude\.credentials.json'), r'~\.claude\.credentials.json')


if __name__ == '__main__':
    unittest.main()
