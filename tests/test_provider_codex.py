"""Focused tests for the instance-oriented Codex provider boundary."""
from __future__ import annotations

import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from usage_monitor.providers.codex import CodexProvider
from usage_monitor.providers.codex import api
from usage_monitor.providers.codex.app_server import AppServerTransport
from usage_monitor.providers.codex.codex_cli import CliUpdateResult

FAKE_SERVER = Path(__file__).with_name('fake_app_server.py')


class _Settings:
    POLL_FAST = 0
    POLL_INTERVAL = 1
    MAX_BACKOFF = 10
    AUTO_UPDATE_CODEX_CLI = True


class _StubTransport:
    def __init__(self) -> None:
        self.events: list[str] = []
        self.revision = 0

    def auth_revision(self) -> int:
        return self.revision

    def force_restart(self) -> None:
        self.events.append('restart')

    def shutdown(self) -> None:
        self.events.append('shutdown')


class TestCodexProviderContract(unittest.TestCase):
    def test_identity_and_cache_are_provider_local(self) -> None:
        first = CodexProvider(Path('first-home'), _Settings())
        second = CodexProvider(Path('second-home'), _Settings())
        try:
            self.assertEqual(first.provider_id, 'codex')
            self.assertEqual(first.display_name, 'Codex')
            self.assertTrue(first.icon_name)
            self.assertIs(first.create_cache(), first.create_cache())
            self.assertIsNot(first.create_cache(), second.create_cache())
            self.assertEqual(first._transport._codex_home, 'first-home')
            self.assertEqual(second._transport._codex_home, 'second-home')
        finally:
            first.shutdown()
            second.shutdown()

    def test_combined_settings_are_scoped_to_codex(self) -> None:
        provider = CodexProvider(
            Path('unused'),
            {'providers': {'codex': {'poll_fast': 7, 'auto_update_cli': False}}},
        )
        try:
            self.assertEqual(provider.settings['poll_fast'], 7)
            self.assertEqual(provider.create_cache()._poll_fast, 7)
            self.assertIsNone(provider.run_maintenance())
        finally:
            provider.shutdown()

    def test_shutdown_is_idempotent_and_terminal(self) -> None:
        provider = CodexProvider(Path('unused'), _Settings())
        transport = _StubTransport()
        provider._transport = transport

        provider.shutdown()
        provider.shutdown()
        provider.recycle_transport()

        self.assertEqual(transport.events, ['shutdown'])
        self.assertIn('error', provider.fetch_provider_data().usage)

    def test_maintenance_recycles_before_fixed_updater(self) -> None:
        provider = CodexProvider(Path('unused'), _Settings())
        transport = _StubTransport()
        provider._transport = transport
        expected = CliUpdateResult(True, True, '1.0.0', '1.1.0', '')
        try:
            with patch('usage_monitor.providers.codex.update_cli', side_effect=lambda: transport.events.append('update') or expected):
                result = provider.run_maintenance()
            self.assertEqual(result, expected)
            self.assertEqual(transport.events, ['restart', 'update'])
        finally:
            provider.shutdown()

    def test_refresh_profile_updates_the_supplied_cache(self) -> None:
        provider = CodexProvider(Path('unused'), _Settings())
        cache = provider.create_cache()
        profile = {
            'account': {'email': 'user@example.com', 'uuid': 'chatgpt:user@example.com'},
            'organization': {'organization_type': 'plus'},
        }
        try:
            with patch.object(provider, '_read_profile', return_value=profile):
                self.assertIsNone(provider.refresh_profile(cache))
            self.assertEqual(cache.profile, profile)
        finally:
            provider.shutdown()

    def test_maintenance_is_serialized_against_provider_fetch(self) -> None:
        provider = CodexProvider(Path('unused'), _Settings())
        provider._transport = _StubTransport()
        entered = threading.Event()
        release = threading.Event()

        def slow_fetch(_transport: object, allow_recovery: bool = False) -> api.ProviderFetchResult:
            del allow_recovery
            entered.set()
            release.wait(timeout=5)
            return api.ProviderFetchResult({}, {})

        with patch('usage_monitor.providers.codex.api.fetch_provider_data', side_effect=slow_fetch), \
             patch('usage_monitor.providers.codex.update_cli', return_value=CliUpdateResult(True, False, '', '', '')):
            fetch_thread = threading.Thread(target=provider.fetch_provider_data)
            maintenance_thread = threading.Thread(target=provider.run_maintenance)
            fetch_thread.start()
            self.assertTrue(entered.wait(timeout=2))
            maintenance_thread.start()
            self.assertEqual(provider._transport.events, [])
            release.set()
            fetch_thread.join(timeout=5)
            maintenance_thread.join(timeout=5)

        self.assertFalse(fetch_thread.is_alive())
        self.assertFalse(maintenance_thread.is_alive())
        self.assertEqual(provider._transport.events, ['restart'])
        provider.shutdown()


class TestCodexProviderIntegration(unittest.TestCase):
    def test_fake_app_server_combines_profile_and_usage_in_one_generation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            provider = CodexProvider(Path(directory), _Settings())
            provider._transport = AppServerTransport(
                [sys.executable, str(FAKE_SERVER), '--scenario', 'normal'],
                codex_home=directory,
            )
            try:
                result = provider.fetch_provider_data()
                self.assertEqual(result.profile['account']['email'], 'user@example.com')
                self.assertEqual(result.usage['five_hour']['utilization'], 12.0)
                self.assertEqual(result.usage['seven_day']['utilization'], 29.0)

                cache = provider.create_cache()
                updated = cache.update(force=True)
                self.assertEqual(updated.data, cache.snapshot.usage)
                self.assertEqual(cache.snapshot.profile['account']['email'], 'user@example.com')
            finally:
                provider.shutdown()
                provider.shutdown()


if __name__ == '__main__':
    unittest.main()
