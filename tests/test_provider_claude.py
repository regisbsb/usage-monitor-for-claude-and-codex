"""Focused contract and regression tests for the Claude provider package."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from usage_monitor.providers.claude import ClaudeProvider
from usage_monitor.providers.claude.api import API_URL_USAGE
from usage_monitor.providers.claude.cache import UsageCache
from usage_monitor.providers.claude.claude_cli import RefreshResult, _run_cli


class ClaudeProviderContractTests(unittest.TestCase):
    def test_contract_and_provider_local_cache(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            provider = ClaudeProvider(Path(temporary), {})
            first = provider.create_cache()
            second = provider.create_cache()

        self.assertEqual(provider.provider_id, "claude")
        self.assertEqual(provider.display_name, "Claude")
        self.assertEqual(provider.icon_name, "usage_monitor_claude")
        self.assertEqual(provider.auth_error_glyph, "C!")
        self.assertIs(first, second)
        self.assertEqual(first.snapshot.usage, {})
        provider.shutdown()
        provider.shutdown()

    def test_auth_revision_changes_without_exposing_token(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            config_dir = Path(temporary)
            credentials = config_dir / ".credentials.json"
            credentials.write_text(json.dumps({"claudeAiOauth": {"accessToken": "first"}}), encoding="utf-8")
            provider = ClaudeProvider(config_dir, {})
            first = provider.auth_revision()
            credentials.write_text(json.dumps({"claudeAiOauth": {"accessToken": "second"}}), encoding="utf-8")
            second = provider.auth_revision()

        self.assertNotEqual(first, second)
        self.assertNotIn("first", first or "")
        self.assertNotIn("second", second or "")

    def test_authentication_check_is_read_only_and_recycle_is_noop(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            config_dir = Path(temporary)
            provider = ClaudeProvider(config_dir, {})
            with patch.object(provider._cli, "native_version") as version:
                self.assertFalse(provider.has_authentication())
                (config_dir / ".credentials.json").write_text(
                    json.dumps({"claudeAiOauth": {"accessToken": "token"}}),
                    encoding="utf-8",
                )
                self.assertTrue(provider.has_authentication())
                provider.recycle_transport()
            version.assert_not_called()

    def test_accepts_combined_nested_settings(self) -> None:
        provider = ClaudeProvider(
            Path("unused"),
            {"providers": {"claude": {"poll_fast": 7, "notify_claude_update": False}}},
        )
        cache = provider.create_cache()
        self.assertEqual(cache._poll_fast, 7)


class ClaudeApiBoundaryTests(unittest.TestCase):
    def test_redirect_is_not_followed_outside_anthropic(self) -> None:
        provider = ClaudeProvider(Path("unused"), {})
        response = MagicMock(status_code=302, headers={"Location": "https://example.test/token"})
        response.json.return_value = {}
        with patch("usage_monitor.providers.claude.api.requests.get", return_value=response) as get:
            result = provider._api.fetch_usage("secret")

        self.assertEqual(result["error"], "API request failed (HTTP 302).")
        get.assert_called_once_with(
            API_URL_USAGE,
            headers=provider._api.api_headers("secret"),
            timeout=10,
            allow_redirects=False,
        )


class _FakeApi:
    def __init__(self, token: str = "old") -> None:
        self.token = token
        self.fetches: list[str | None] = []
        self.profiles: dict[str | None, dict] = {}

    def read_access_token(self) -> str | None:
        return self.token

    def fetch_usage(self, token: str | None) -> dict:
        self.fetches.append(token)
        if token == "old":
            return {"error": "expired", "auth_error": True}
        return {"five_hour": {"utilization": 12}}

    def fetch_profile(self, token: str | None) -> dict | None:
        return self.profiles.get(token)


class _FakeCli:
    def __init__(self, api: _FakeApi) -> None:
        self.api = api

    def refresh_token(self) -> RefreshResult:
        self.api.token = "new"
        return RefreshResult(True, True, "1.0.0", "1.0.1", "")


class ClaudeCacheTests(unittest.TestCase):
    def test_401_refreshes_native_token_and_retries_once(self) -> None:
        api = _FakeApi()
        cache = UsageCache(api, _FakeCli(api), {})  # type: ignore[arg-type]
        result = cache.update()

        self.assertEqual(api.fetches, ["old", "new"])
        self.assertEqual(result.data, {"five_hour": {"utilization": 12}})
        self.assertTrue(result.token_refresh and result.token_refresh.updated)
        self.assertEqual(result.token, "new")

    def test_new_account_usage_cannot_pair_with_old_profile(self) -> None:
        api = _FakeApi()
        api.profiles["old"] = {"account": {"uuid": "old-account"}}
        cache = UsageCache(api, _FakeCli(api), {})  # type: ignore[arg-type]
        cache.ensure_profile()
        self.assertEqual(cache.profile, {"account": {"uuid": "old-account"}})

        api.token = "new"
        result = cache.update(force=True)

        self.assertIsNotNone(result.data)
        self.assertIsNone(cache.snapshot.profile)
        self.assertEqual(cache.snapshot.usage["five_hour"]["utilization"], 12)

    def test_profile_result_is_discarded_if_credentials_change_in_flight(self) -> None:
        api = _FakeApi()

        def switching_profile(_token: str | None) -> dict:
            api.token = "new"
            return {"account": {"uuid": "old-account"}}

        api.fetch_profile = switching_profile  # type: ignore[method-assign]
        cache = UsageCache(api, _FakeCli(api), {})  # type: ignore[arg-type]
        cache.refresh_profile()
        self.assertIsNone(cache.profile)


class ClaudeCliEncodingTests(unittest.TestCase):
    def test_cli_output_is_decoded_as_utf8(self) -> None:
        child = (
            "import sys;"
            "sys.stdout.buffer.write('✓ ok\\n'.encode('utf-8'));"
            "sys.stderr.buffer.write('• note\\n'.encode('utf-8'))"
        )
        process = _run_cli([sys.executable, "-c", child], timeout=30)
        self.assertEqual(process.stdout, "✓ ok\n")
        self.assertEqual(process.stderr, "• note\n")

    @patch("usage_monitor.providers.claude.claude_cli.subprocess.run")
    def test_lost_stream_is_an_io_failure(self, run: MagicMock) -> None:
        run.return_value = SimpleNamespace(stdout=None, stderr="", returncode=0)
        with self.assertRaises(OSError):
            _run_cli(["claude", "--version"], timeout=10)
        self.assertEqual(run.call_args.kwargs["encoding"], "utf-8")
        self.assertEqual(run.call_args.kwargs["errors"], "replace")


if __name__ == "__main__":
    unittest.main()
