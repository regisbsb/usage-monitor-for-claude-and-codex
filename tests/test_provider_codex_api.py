"""
Provider Adapter Tests
======================

Tests for Codex app-server normalization, classification, recovery, and
profile semantics.
"""
from __future__ import annotations

import json
import math
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from usage_monitor.providers.codex import api as api_module
from usage_monitor.providers.codex.api import (
    _model_slug, _normalize_rate_limits, _parse_account, _profile_from_account,
    fetch_provider_data, refresh_profile,
)
from usage_monitor.providers.codex.app_server import AppServerTransport, CodexCliNotFound, RpcError, TransportError

FIXTURES = Path(__file__).parent / 'fixtures' / 'codex'
FAKE_APP_SERVER = str(Path(__file__).parent / 'fake_app_server.py')


def _load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding='utf-8'))


def _rpc_error_fixture(name: str) -> RpcError:
    payload = _load_fixture(name)
    return RpcError(payload.get('code'), str(payload.get('message', '')), payload.get('data'))


class TestModelSlug(unittest.TestCase):
    def test_words_digits_and_punctuation(self):
        self.assertEqual(_model_slug('GPT 5-Pro'), 'gpt_5_pro')


class TestNormalizeRateLimits(unittest.TestCase):
    def test_five_hour_plus_weekly(self):
        result = _normalize_rate_limits(_load_fixture('01_five_hour_plus_weekly.json'))
        self.assertEqual(set(result), {'five_hour', 'seven_day'})
        self.assertEqual(result['five_hour']['utilization'], 12.0)
        self.assertEqual(result['seven_day']['utilization'], 29.0)

    def test_used_percent_not_inverted(self):
        result = _normalize_rate_limits(_load_fixture('02_weekly_only_primary.json'))
        self.assertEqual(result['seven_day']['utilization'], 29.0)

    def test_weekly_only_primary_named_by_duration(self):
        self.assertEqual(list(_normalize_rate_limits(_load_fixture('02_weekly_only_primary.json'))), ['seven_day'])

    def test_null_secondary_skipped(self):
        self.assertEqual(list(_normalize_rate_limits(_load_fixture('03_secondary_null.json'))), ['five_hour'])

    def test_epoch_converts_to_aware_utc_iso(self):
        result = _normalize_rate_limits(_load_fixture('01_five_hour_plus_weekly.json'))
        self.assertEqual(result['five_hour']['resets_at'], '2025-07-15T17:20:00+00:00')

    def test_keyed_source_ignores_snapshot(self):
        result = _normalize_rate_limits(_load_fixture('04_multi_bucket.json'))
        self.assertEqual(set(result), {'five_hour', 'seven_day', 'seven_day_gpt_5_pro'})

    def test_keyed_model_limit_preserves_friendly_name(self):
        payload = {'rateLimitsByLimitId': {'codex_bengalfox': {
            'limitName': 'gpt-5.2-codex-sonic',
            'primary': {'usedPercent': 5, 'windowDurationMins': 10080},
            'secondary': None,
        }}}
        result = _normalize_rate_limits(payload)
        self.assertEqual(result['seven_day_codex_bengalfox']['limit_name'], 'gpt-5.2-codex-sonic')

    def test_default_codex_limit_does_not_override_generic_label(self):
        payload = {'rateLimitsByLimitId': {'codex': {
            'limitName': 'gpt-5.6-sol',
            'primary': {'usedPercent': 5, 'windowDurationMins': 10080},
            'secondary': None,
        }}}
        result = _normalize_rate_limits(payload)
        self.assertNotIn('limit_name', result['seven_day'])

    def test_invalid_friendly_name_is_ignored(self):
        payload = {'rateLimitsByLimitId': {'codex_bengalfox': {
            'limitName': {'unexpected': 'object'},
            'primary': {'usedPercent': 5, 'windowDurationMins': 10080},
            'secondary': None,
        }}}
        result = _normalize_rate_limits(payload)
        self.assertNotIn('limit_name', result['seven_day_codex_bengalfox'])

    def test_empty_keyed_map_falls_back_to_snapshot(self):
        payload = _load_fixture('01_five_hour_plus_weekly.json')
        payload['rateLimitsByLimitId'] = {}
        self.assertEqual(set(_normalize_rate_limits(payload)), {'five_hour', 'seven_day'})
        payload['rateLimitsByLimitId'] = None
        self.assertEqual(set(_normalize_rate_limits(payload)), {'five_hour', 'seven_day'})

    def test_unknown_durations(self):
        self.assertEqual(set(_normalize_rate_limits(_load_fixture('05_unknown_durations.json'))), {'90_minute', '30_day'})

    def test_word_and_digit_duration_forms(self):
        one_day = {'rateLimits': {'primary': {'usedPercent': 1, 'windowDurationMins': 1440}, 'secondary': None}}
        thirteen_hour = {'rateLimits': {'primary': {'usedPercent': 1, 'windowDurationMins': 780}, 'secondary': None}}
        self.assertEqual(list(_normalize_rate_limits(one_day)), ['one_day'])
        self.assertEqual(list(_normalize_rate_limits(thirteen_hour)), ['13_hour'])

    def test_missing_duration_snapshot_uses_slot_name(self):
        result = _normalize_rate_limits(_load_fixture('06_missing_duration.json'))
        self.assertEqual(list(result), ['primary'])

    def test_missing_reset_becomes_empty_string(self):
        payload = {'rateLimits': {'primary': {'usedPercent': 40, 'windowDurationMins': 300}, 'secondary': None}}
        self.assertEqual(_normalize_rate_limits(payload)['five_hour']['resets_at'], '')

    def test_missing_duration_keyed_uses_slug(self):
        payload = {'rateLimitsByLimitId': {'codex': {'primary': {'usedPercent': 5}, 'secondary': None}}}
        self.assertEqual(list(_normalize_rate_limits(payload)), ['codex'])

    def test_empty_slug_with_duration_uses_period_limit(self):
        payload = {'rateLimitsByLimitId': {'--': {
            'primary': {'usedPercent': 5, 'windowDurationMins': 10080}, 'secondary': None,
        }}}
        self.assertEqual(list(_normalize_rate_limits(payload)), ['seven_day_limit'])

    def test_snapshot_collision_appends_slot(self):
        payload = {'rateLimits': {
            'primary': {'usedPercent': 1, 'windowDurationMins': 10080, 'resetsAt': 1},
            'secondary': {'usedPercent': 2, 'windowDurationMins': 10080, 'resetsAt': 2},
        }}
        self.assertEqual(set(_normalize_rate_limits(payload)), {'seven_day', 'seven_day_secondary'})

    def test_keyed_collision_appends_counter(self):
        payload = {'rateLimitsByLimitId': {'codex': {
            'primary': {'usedPercent': 1}, 'secondary': {'usedPercent': 2},
        }}}
        self.assertEqual(set(_normalize_rate_limits(payload)), {'codex', 'codex_2'})

    def test_credits_metadata_ignored(self):
        result = _normalize_rate_limits(_load_fixture('09_credits_metadata.json'))
        self.assertEqual(set(result), {'five_hour'})
        self.assertNotIn('extra_usage', result)


class TestProfileNormalization(unittest.TestCase):
    def test_chatgpt_account(self):
        profile = _profile_from_account(_parse_account(_load_fixture('12_chatgpt_account.json')))
        self.assertEqual(profile['account']['email'], 'User@Example.com')
        self.assertEqual(profile['account']['uuid'], 'chatgpt:user@example.com')
        self.assertEqual(profile['organization']['organization_type'], 'plus')

    def test_signed_out_is_empty_dict(self):
        self.assertEqual(_profile_from_account(_parse_account(_load_fixture('07_signed_out_account.json'))), {})

    def test_missing_email_gives_none_fingerprint(self):
        profile = _profile_from_account(_parse_account(_load_fixture('08_api_key_account.json')))
        self.assertIsNone(profile['account']['uuid'])
        self.assertEqual(profile['account']['email'], '')

    def test_missing_plan_normalizes_to_empty_string(self):
        profile = _profile_from_account(_parse_account({'account': {'type': 'chatgpt', 'email': 'a@b.c'}}))
        self.assertEqual(profile['organization']['organization_type'], '')

    def test_auth_type_is_normalized_for_classification_and_fingerprint(self):
        account = _parse_account({'account': {
            'type': 'ChatGPT', 'email': 'User@Example.com', 'planType': 'plus',
        }})
        self.assertEqual(account['type'], 'chatgpt')
        profile = _profile_from_account(account)
        self.assertEqual(profile['account']['uuid'], 'chatgpt:user@example.com')

    def test_unusable_payload_is_unknown(self):
        for payload in (None, {'requiresOpenaiAuth': True}, {'account': []}, {'account': {}}, {'account': {'type': 123}}):
            with self.subTest(payload=payload):
                self.assertIs(_parse_account(payload), api_module._UNKNOWN)
        self.assertIsNone(_profile_from_account(api_module._UNKNOWN))


class _FakeOperation:
    def __init__(self, script):
        self.script = list(script)
        self.calls = []

    def request(self, method, params):
        refresh = bool(params.get('refreshToken')) if method == 'account/read' else None
        self.calls.append((method, refresh))
        outcome = self.script.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class _FakeTransport:
    def __init__(self, script):
        self.operation = _FakeOperation(script)

    def run_operation(self, body):
        return body(self.operation)


def _run_adapter(script, allow_recovery=False):
    transport = _FakeTransport(script)
    result = fetch_provider_data(transport, allow_recovery=allow_recovery)
    return result, transport.operation.calls


CHATGPT_ACCOUNT = _load_fixture('12_chatgpt_account.json')
SIGNED_OUT_ACCOUNT = _load_fixture('07_signed_out_account.json')
API_KEY_ACCOUNT = _load_fixture('08_api_key_account.json')
BEDROCK_ACCOUNT = _load_fixture('08b_bedrock_account.json')
RATE_LIMITS_OK = _load_fixture('01_five_hour_plus_weekly.json')


class TestAuthEvidenceDefaults(unittest.TestCase):
    def test_production_auth_codes_are_empty_and_minus_32001_is_transient(self):
        self.assertEqual(api_module.AUTH_ERROR_CODES, frozenset())
        result, _ = _run_adapter([CHATGPT_ACCOUNT, _rpc_error_fixture('10_auth_error.json')])
        self.assertEqual(result.usage['error'], api_module._MESSAGES['connection_error'])
        self.assertNotIn('auth_error', result.usage)


class TestClassification(unittest.TestCase):
    def setUp(self):
        auth_codes = patch.object(api_module, 'AUTH_ERROR_CODES', frozenset({-32001}))
        auth_codes.start()
        self.addCleanup(auth_codes.stop)

    def test_success_carries_usage_and_profile(self):
        result, _ = _run_adapter([CHATGPT_ACCOUNT, RATE_LIMITS_OK])
        self.assertIn('five_hour', result.usage)
        self.assertEqual(result.profile['organization']['organization_type'], 'plus')
        self.assertFalse(result.recovery_attempted)

    def _assert_no_recovery(self, account, expected_error):
        result, calls = _run_adapter([account, _rpc_error_fixture('10_auth_error.json')], allow_recovery=True)
        self.assertEqual(result.usage['error'], expected_error)
        self.assertFalse(result.recovery_attempted)
        self.assertEqual(calls, [('account/read', False), ('account/rateLimits/read', None)])
        return result

    def test_signed_out_never_attempts_recovery(self):
        result = self._assert_no_recovery(SIGNED_OUT_ACCOUNT, api_module._MESSAGES['no_token'])
        self.assertEqual(result.profile, {})
        self.assertTrue(result.usage['no_auth'])

    def test_api_key_never_attempts_recovery(self):
        result = self._assert_no_recovery(API_KEY_ACCOUNT, api_module._MESSAGES['not_chatgpt_auth'])
        self.assertNotIn('auth_error', result.usage)

    def test_bedrock_never_attempts_recovery(self):
        self._assert_no_recovery(BEDROCK_ACCOUNT, api_module._MESSAGES['not_chatgpt_auth'])

    def test_chatgpt_auth_classification_is_case_insensitive(self):
        account = {'account': {'type': 'ChatGPT', 'email': 'User@Example.com'}}
        result, _ = _run_adapter([account, _rpc_error_fixture('10_auth_error.json')])
        self.assertEqual(result.usage['error'], api_module._MESSAGES['auth_expired'])
        self.assertTrue(result.usage['auth_error'])

    def test_method_not_found_on_required_methods_is_too_old(self):
        result, _ = _run_adapter([CHATGPT_ACCOUNT, _rpc_error_fixture('11_method_not_found.json')])
        self.assertEqual(result.usage['error'], api_module._MESSAGES['codex_cli_too_old'])
        result, calls = _run_adapter([_rpc_error_fixture('11_method_not_found.json')])
        self.assertEqual(result.usage['error'], api_module._MESSAGES['codex_cli_too_old'])
        self.assertEqual(calls, [('account/read', False)])

    def test_no_recovery_without_permission(self):
        result, calls = _run_adapter([CHATGPT_ACCOUNT, _rpc_error_fixture('10_auth_error.json')])
        self.assertEqual(result.usage['error'], api_module._MESSAGES['auth_expired'])
        self.assertTrue(result.usage['auth_error'])
        self.assertFalse(result.recovery_attempted)
        self.assertEqual(len(calls), 2)

    def test_recovery_sequence_success(self):
        result, calls = _run_adapter(
            [CHATGPT_ACCOUNT, _rpc_error_fixture('10_auth_error.json'), CHATGPT_ACCOUNT, RATE_LIMITS_OK], True,
        )
        self.assertIn('five_hour', result.usage)
        self.assertTrue(result.recovery_attempted)
        self.assertEqual(calls, [
            ('account/read', False), ('account/rateLimits/read', None),
            ('account/read', True), ('account/rateLimits/read', None),
        ])

    def test_recovery_retry_classifies_actual_error(self):
        result, _ = _run_adapter([
            CHATGPT_ACCOUNT, _rpc_error_fixture('10_auth_error.json'), CHATGPT_ACCOUNT,
            _rpc_error_fixture('10b_transient_error.json'),
        ], True)
        self.assertEqual(result.usage['error'], api_module._MESSAGES['connection_error'])
        self.assertNotIn('auth_error', result.usage)

    def test_signed_out_during_recovery_replaces_stale_profile(self):
        result, calls = _run_adapter([
            CHATGPT_ACCOUNT, _rpc_error_fixture('10_auth_error.json'), SIGNED_OUT_ACCOUNT,
            _rpc_error_fixture('10_auth_error.json'),
        ], True)
        self.assertEqual(result.profile, {})
        self.assertTrue(result.recovery_attempted)
        self.assertEqual(calls.count(('account/read', True)), 1)

    def test_account_read_error_uses_rate_limits_error(self):
        result, calls = _run_adapter([
            _rpc_error_fixture('10b_transient_error.json'), _rpc_error_fixture('10b_transient_error.json'),
        ], True)
        self.assertEqual(result.usage['error'], api_module._MESSAGES['connection_error'])
        self.assertIsNone(result.profile)
        self.assertEqual(len(calls), 2)

    def test_transport_and_cli_failures_map_to_messages(self):
        class BrokenTransport:
            def run_operation(self, body):
                raise TransportError('down')

        class MissingTransport:
            def run_operation(self, body):
                raise CodexCliNotFound('missing')

        self.assertEqual(fetch_provider_data(BrokenTransport()).usage['error'], api_module._MESSAGES['connection_error'])
        self.assertEqual(fetch_provider_data(MissingTransport()).usage['error'], api_module._MESSAGES['codex_cli_not_found'])

    def test_malformed_rate_limit_envelopes_become_connection_errors(self):
        malformed = (
            None,
            [],
            {},
            {'rateLimits': ['not', 'a', 'mapping']},
            {'rateLimitsByLimitId': {'codex': 'not a bucket'}},
            {'rateLimitsByLimitId': {1: {'primary': {'usedPercent': 1}}}},
            {'rateLimits': {'primary': {'usedPercent': 'abc'}}},
            {'rateLimits': {'primary': {'usedPercent': {}}}},
        )
        for payload in malformed:
            with self.subTest(payload=payload):
                result, _ = _run_adapter([CHATGPT_ACCOUNT, payload])
                self.assertEqual(result.usage, {'error': api_module._MESSAGES['connection_error']})
                self.assertEqual(result.profile['account']['uuid'], 'chatgpt:user@example.com')

    def test_malformed_window_is_skipped_when_another_window_is_valid(self):
        payload = {'rateLimits': {
            'primary': {'usedPercent': 'bad'},
            'secondary': {'usedPercent': 25, 'windowDurationMins': 10080},
        }}
        result, _ = _run_adapter([CHATGPT_ACCOUNT, payload])
        self.assertEqual(set(result.usage), {'seven_day'})
        self.assertEqual(result.usage['seven_day']['utilization'], 25.0)

    def test_invalid_reset_is_discarded_without_losing_utilization(self):
        for reset in (True, -1, 1e300, 'not-a-timestamp'):
            with self.subTest(reset=reset):
                payload = {'rateLimits': {'primary': {
                    'usedPercent': 25,
                    'windowDurationMins': 300,
                    'resetsAt': reset,
                }}}
                result, _ = _run_adapter([CHATGPT_ACCOUNT, payload])
                self.assertEqual(result.usage['five_hour'], {'utilization': 25.0, 'resets_at': ''})

    def test_non_finite_utilization_becomes_connection_error(self):
        for percent in (float('nan'), float('inf'), float('-inf')):
            with self.subTest(percent=percent):
                self.assertFalse(math.isfinite(percent))
                payload = {'rateLimits': {'primary': {'usedPercent': percent}}}
                result, _ = _run_adapter([CHATGPT_ACCOUNT, payload])
                self.assertEqual(result.usage, {'error': api_module._MESSAGES['connection_error']})


class TestRecoveryLatchAcrossGenerations(unittest.TestCase):
    def test_single_refresh_read_across_operation_retry(self):
        with TemporaryDirectory() as tmp:
            log_path = str(Path(tmp) / 'log.jsonl')
            transport = AppServerTransport(
                command=[sys.executable, FAKE_APP_SERVER, '--scenario', 'die-after-refresh', '--log', log_path],
                init_timeout=10,
                rpc_timeout=3,
            )
            self.addCleanup(transport.shutdown)
            result = fetch_provider_data(transport, allow_recovery=True)
            self.assertTrue(result.recovery_attempted)
            entries = [json.loads(line) for line in Path(log_path).read_text(encoding='utf-8').splitlines()]
            refresh_reads = [
                entry for entry in entries
                if entry.get('method') == 'account/read' and (entry.get('params') or {}).get('refreshToken')
            ]
            self.assertEqual(len(refresh_reads), 1)


class TestRefreshProfile(unittest.TestCase):
    def test_refresh_profile_returns_normalized_profile(self):
        profile = refresh_profile(_FakeTransport([CHATGPT_ACCOUNT]))
        self.assertEqual(profile['account']['uuid'], 'chatgpt:user@example.com')

    def test_refresh_profile_signed_out_is_empty_dict(self):
        self.assertEqual(refresh_profile(_FakeTransport([SIGNED_OUT_ACCOUNT])), {})

    def test_refresh_profile_none_on_failure(self):
        class BrokenTransport:
            def run_operation(self, body):
                raise TransportError('down')

        self.assertIsNone(refresh_profile(BrokenTransport()))


if __name__ == '__main__':
    unittest.main()


