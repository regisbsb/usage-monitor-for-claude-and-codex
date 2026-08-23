"""Tests for process-wide dual-provider lifecycle coordination."""
from __future__ import annotations

import threading
import unittest
from dataclasses import dataclass
from unittest.mock import patch

from usage_monitor.application import AppSupervisor


@dataclass
class _Settings:
    enabled: bool = True


class _Provider:
    def __init__(self, provider_id: str, *, fail_start: bool = False) -> None:
        self.provider_id = provider_id
        self.fail_start = fail_start
        self.shutdown_calls = 0

    def shutdown(self) -> None:
        self.shutdown_calls += 1


class _Monitor:
    def __init__(self, provider: _Provider, settings: _Settings, supervisor: AppSupervisor) -> None:
        del settings
        self.provider = provider
        self.supervisor = supervisor
        self.running = True
        self.started = threading.Event()
        self.stop_calls = 0

    def start_detached(self) -> None:
        if self.provider.fail_start:
            raise RuntimeError('icon start failed')
        self.started.set()

    def stop(self) -> None:
        self.stop_calls += 1
        self.running = False


class TestAppSupervisor(unittest.TestCase):
    @patch('usage_monitor.application.ProviderMonitor', _Monitor)
    def test_quit_stops_both_icons_and_providers(self) -> None:
        claude = _Provider('claude')
        codex = _Provider('codex')
        supervisor = AppSupervisor([(claude, _Settings()), (codex, _Settings())])
        thread = threading.Thread(target=supervisor.run)
        thread.start()
        self.assertTrue(all(monitor.started.wait(1) for monitor in supervisor.monitors))

        supervisor.monitors[0].supervisor.request_quit()
        thread.join(2)

        self.assertFalse(thread.is_alive())
        self.assertEqual([monitor.stop_calls for monitor in supervisor.monitors], [1, 1])
        self.assertEqual([claude.shutdown_calls, codex.shutdown_calls], [1, 1])

    @patch('usage_monitor.application.ProviderMonitor', _Monitor)
    def test_restart_is_process_wide_and_idempotent(self) -> None:
        providers = [_Provider('claude'), _Provider('codex')]
        supervisor = AppSupervisor((provider, _Settings()) for provider in providers)
        thread = threading.Thread(target=supervisor.run)
        thread.start()
        self.assertTrue(all(monitor.started.wait(1) for monitor in supervisor.monitors))

        supervisor.request_restart()
        supervisor.request_restart()
        thread.join(2)
        supervisor.stop()

        self.assertTrue(supervisor.restart_requested)
        self.assertEqual([monitor.stop_calls for monitor in supervisor.monitors], [1, 1])
        self.assertEqual([provider.shutdown_calls for provider in providers], [1, 1])

    @patch('usage_monitor.application.crash_log')
    @patch('usage_monitor.application.ProviderMonitor', _Monitor)
    def test_partial_icon_start_failure_cleans_up_every_provider(self, crash_log) -> None:
        providers = [_Provider('claude'), _Provider('codex', fail_start=True)]
        supervisor = AppSupervisor([(provider, _Settings()) for provider in providers])

        supervisor.run()

        crash_log.assert_called_once()
        self.assertEqual([monitor.stop_calls for monitor in supervisor.monitors], [1, 1])
        self.assertEqual([provider.shutdown_calls for provider in providers], [1, 1])

    @patch('usage_monitor.application.ProviderMonitor', _Monitor)
    def test_disabled_provider_is_not_constructed(self) -> None:
        claude = _Provider('claude')
        codex = _Provider('codex')
        supervisor = AppSupervisor([(claude, _Settings()), (codex, _Settings(enabled=False))])

        self.assertEqual([monitor.provider.provider_id for monitor in supervisor.monitors], ['claude'])
        self.assertEqual(supervisor.providers, [claude])


if __name__ == '__main__':
    unittest.main()
