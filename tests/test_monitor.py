"""Tests for shared dual-provider monitor orchestration."""
from __future__ import annotations

import threading
import unittest
from dataclasses import replace
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pystray  # type: ignore[import-untyped]

from usage_monitor.i18n import T
from usage_monitor.monitor import ProviderMonitor
from usage_monitor.settings import get_provider_settings


def _make_monitor(provider_id: str = 'claude') -> ProviderMonitor:
    """Create a provider monitor without starting its tray message pump."""
    provider = MagicMock()
    provider.provider_id = provider_id
    provider.icon_name = f'usage-monitor-{provider_id}'
    provider.display_name = provider_id.title()
    provider.cli_display_name = 'Claude Code' if provider_id == 'claude' else 'Codex'
    provider.project_url = 'https://example.invalid'
    provider.custom_config = False
    provider.create_cache.return_value = MagicMock()
    settings = replace(get_provider_settings(provider_id), on_double_click_command=[])
    icon = MagicMock()

    def create_icon(*args: object, **kwargs: object) -> MagicMock:
        del args
        icon.menu = kwargs['menu']
        return icon

    with patch('usage_monitor.monitor.pystray.Icon', side_effect=create_icon), \
         patch('usage_monitor.monitor.create_icon_image'), \
         patch('usage_monitor.monitor.taskbar_uses_light_theme', return_value=False):
        return ProviderMonitor(provider, settings, MagicMock())


class TestManualRefresh(unittest.TestCase):
    """Tests for the provider-scoped asynchronous manual refresh path."""

    def test_menu_places_localized_refresh_below_restart(self) -> None:
        monitor = _make_monitor()
        items = monitor.icon.menu.items
        restart_index = next(index for index, item in enumerate(items) if item is not pystray.Menu.SEPARATOR and item.text == T['restart'])

        self.assertEqual(items[restart_index + 1].text, T['refresh'])
        self.assertIs(items[restart_index + 2], pystray.Menu.SEPARATOR)

    @patch('usage_monitor.monitor.threading.Thread')
    def test_menu_action_starts_daemon_worker(self, thread: MagicMock) -> None:
        monitor = _make_monitor()

        monitor.on_refresh()

        thread.assert_called_once_with(target=monitor.refresh_now, daemon=True)
        thread.return_value.start.assert_called_once_with()

    def test_worker_forwards_force_to_update(self) -> None:
        monitor = _make_monitor()

        with patch.object(monitor, 'update') as update:
            self.assertTrue(monitor.refresh_now())

        update.assert_called_once_with(force=True)
        self.assertFalse(monitor._manual_refresh_active)

    def test_duplicate_requests_coalesce_per_provider(self) -> None:
        claude = _make_monitor('claude')
        codex = _make_monitor('codex')
        release = threading.Event()
        claude_started = threading.Event()
        codex_started = threading.Event()
        claude_waiting = threading.Event()
        codex_waiting = threading.Event()
        duplicate_results: list[bool] = []

        def blocked_refresh(started: threading.Event, *, force: bool) -> None:
            self.assertTrue(force)
            started.set()
            self.assertTrue(release.wait(2))

        claude_wait = claude._manual_refresh_condition.wait
        codex_wait = codex._manual_refresh_condition.wait

        def observed_wait(waiting: threading.Event, wait: Any) -> bool:
            waiting.set()
            return wait()

        with patch.object(claude, 'update', side_effect=lambda *, force: blocked_refresh(claude_started, force=force)) as claude_update, \
             patch.object(codex, 'update', side_effect=lambda *, force: blocked_refresh(codex_started, force=force)) as codex_update, \
             patch.object(claude._manual_refresh_condition, 'wait', side_effect=lambda: observed_wait(claude_waiting, claude_wait)), \
             patch.object(codex._manual_refresh_condition, 'wait', side_effect=lambda: observed_wait(codex_waiting, codex_wait)):
            claude_worker = threading.Thread(target=claude.refresh_now)
            claude_worker.start()
            self.assertTrue(claude_started.wait(1))
            claude_duplicate = threading.Thread(target=lambda: duplicate_results.append(claude.refresh_now()))
            claude_duplicate.start()

            codex_worker = threading.Thread(target=codex.refresh_now)
            codex_worker.start()
            self.assertTrue(codex_started.wait(1))
            codex_duplicate = threading.Thread(target=lambda: duplicate_results.append(codex.refresh_now()))
            codex_duplicate.start()
            self.assertTrue(claude_waiting.wait(1))
            self.assertTrue(codex_waiting.wait(1))
            release.set()
            claude_worker.join(2)
            codex_worker.join(2)
            claude_duplicate.join(2)
            codex_duplicate.join(2)
            self.assertFalse(claude_worker.is_alive())
            self.assertFalse(codex_worker.is_alive())
            self.assertFalse(claude_duplicate.is_alive())
            self.assertFalse(codex_duplicate.is_alive())

        claude_update.assert_called_once_with(force=True)
        codex_update.assert_called_once_with(force=True)
        self.assertEqual(duplicate_results, [False, False])


class TestProjectMenu(unittest.TestCase):
    """Tests for combined and provider-upstream project links."""

    def test_project_submenu_lists_combined_then_original(self) -> None:
        monitor = _make_monitor()
        project_item = next(item for item in monitor.icon.menu.items if item is not pystray.Menu.SEPARATOR and item.text == T['menu_project'])

        self.assertIsNotNone(project_item.submenu)
        self.assertEqual(
            [item.text for item in project_item.submenu.items],
            [T['menu_combined_project'], T['menu_original_project']],
        )

    @patch('usage_monitor.monitor.webbrowser.open')
    def test_project_submenu_opens_combined_and_provider_urls(self, open_url: MagicMock) -> None:
        monitor = _make_monitor('codex')
        project_item = next(item for item in monitor.icon.menu.items if item is not pystray.Menu.SEPARATOR and item.text == T['menu_project'])

        project_item.submenu.items[0](monitor.icon)
        project_item.submenu.items[1](monitor.icon)

        self.assertEqual(open_url.call_args_list[0].args, ('https://github.com/regisbsb/usage-monitor-for-claude-and-codex',))
        self.assertEqual(open_url.call_args_list[1].args, ('https://example.invalid',))


class TestSharedAutostartMenu(unittest.TestCase):
    """Tests for synchronizing the process-wide autostart checkmark."""

    @patch('usage_monitor.monitor.set_autostart')
    @patch('usage_monitor.monitor.is_autostart_enabled', return_value=False)
    def test_toggle_refreshes_both_provider_menus(self, _is_enabled: MagicMock, set_autostart: MagicMock) -> None:
        monitor = _make_monitor()

        monitor.on_toggle_autostart()

        set_autostart.assert_called_once_with(True)
        monitor.supervisor.refresh_menus.assert_called_once_with()


class TestProviderNotificationText(unittest.TestCase):
    """Tests for provider names in shared notification templates."""

    def test_reset_notification_names_codex(self) -> None:
        monitor = _make_monitor('codex')

        self.assertIn('Codex', monitor._notification_text('notify_reset_provider'))
        self.assertNotIn('Claude', monitor._notification_text('notify_reset_provider'))

    def test_update_notification_names_each_cli(self) -> None:
        claude = _make_monitor('claude')
        codex = _make_monitor('codex')

        self.assertEqual(claude._notification_text('notify_update_provider_title'), 'Claude Code Updated')
        self.assertEqual(codex._notification_text('notify_update_provider_title'), 'Codex Updated')
        self.assertIn('Codex updated from 1.0 to 1.1', codex._notification_text('notify_update_provider', old='1.0', new='1.1'))

    def test_codex_reset_path_emits_codex_message(self) -> None:
        monitor = _make_monitor('codex')
        monitor.cache.profile = {'account': {'uuid': 'same-account'}}
        monitor.cache.update.return_value = SimpleNamespace(
            data={'five_hour': {'utilization': 0.0, 'resets_at': ''}},
            token_refresh=None,
        )
        monitor.provider.result_is_current.return_value = True
        monitor._prev_account_uuid = 'same-account'
        monitor._prev_utilization = {'five_hour': 99.0}

        with patch.object(monitor, '_render_tray'), patch.object(monitor, '_is_user_away', return_value=False):
            monitor.update()

        message, title = monitor.icon.notify.call_args.args
        self.assertEqual(title, T['notify_reset_title'])
        self.assertIn('Codex', message)
        self.assertNotIn('Claude', message)

    def test_codex_maintenance_path_emits_codex_update(self) -> None:
        monitor = _make_monitor('codex')
        monitor.provider.run_maintenance.return_value = SimpleNamespace(updated=True, old_version='1.0', new_version='1.1')

        def stop_after_update(*, force: bool = False) -> None:
            self.assertFalse(force)
            monitor.running = False

        with patch.object(monitor, 'update', side_effect=stop_after_update):
            monitor.poll_loop()

        monitor.icon.notify.assert_called_once_with('Codex updated from 1.0 to 1.1.', 'Codex Updated')


if __name__ == '__main__':
    unittest.main()
