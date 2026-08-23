"""
Provider Adapter
================

Normalizes account and rate-limit data obtained from the local Codex
app-server. Together with ``app_server.py``, this module is the provider
boundary; it never accesses credential stores or makes network requests.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from .app_server import AppServerTransport, CodexCliNotFound, RpcError, TransportError

__all__ = [
    'METHOD_ACCOUNT_READ', 'METHOD_RATE_LIMITS_READ', 'PARAM_REFRESH_TOKEN',
    'ProviderFetchResult', 'fetch_provider_data', 'refresh_profile',
]

# Codex app-server wire methods, pinned by tests/fixtures/codex/WIRE_NOTES.md.
METHOD_ACCOUNT_READ = 'account/read'
METHOD_RATE_LIMITS_READ = 'account/rateLimits/read'
PARAM_REFRESH_TOKEN = 'refreshToken'
METHOD_NOT_FOUND_CODE = -32601

# Populate only from exact code/data evidence captured in WIRE_NOTES.md. The
# live probe observed no auth-shaped error, and -32001 is also used for server
# overload, so production intentionally ships with no auth classification.
AUTH_ERROR_CODES: frozenset[int] = frozenset()

_KNOWN_DURATION_NAMES = {300: 'five_hour', 10080: 'seven_day'}
_NUMBER_TO_WORD = {
    1: 'one', 2: 'two', 3: 'three', 4: 'four', 5: 'five', 6: 'six',
    7: 'seven', 8: 'eight', 9: 'nine', 10: 'ten', 11: 'eleven', 12: 'twelve',
}

_UNKNOWN = object()
log = logging.getLogger(__name__)

_MESSAGES = {
    'auth_expired': 'Codex authentication expired.',
    'codex_cli_not_found': 'Codex CLI not found - install Codex and sign in.',
    'codex_cli_too_old': 'Codex CLI is too old for this monitor - please update Codex.',
    'connection_error': 'Could not communicate with the Codex app-server.',
    'no_token': "Not signed in to Codex. Run 'codex login' first.",
    'not_chatgpt_auth': 'Signed in without a ChatGPT plan - plan usage requires ChatGPT sign-in.',
}


class _MalformedProviderData(ValueError):
    """Structurally invalid but successfully decoded provider response."""


@dataclass(frozen=True)
class ProviderFetchResult:
    """One poll cycle's combined provider result.

    Attributes
    ----------
    usage : dict
        Normalized quota fields, or an ``error`` response.
    profile : dict or None
        Fresh normalized profile, ``{}`` for authoritative signed-out, or
        ``None`` when account state was unavailable this cycle.
    recovery_attempted : bool
        Whether the refresh-enabled recovery sequence ran.
    """

    usage: dict[str, Any]
    profile: dict[str, Any] | None
    recovery_attempted: bool = False


def fetch_provider_data(transport: AppServerTransport, allow_recovery: bool = False) -> ProviderFetchResult:
    """Read account and rate limits as one generation-atomic provider operation."""
    recovery_latch = {'attempted': False}
    try:
        def operation_body(operation: Any) -> ProviderFetchResult:
            try:
                account_info = _read_account(operation, refresh=False)
            except RpcError:
                return ProviderFetchResult(
                    usage={'error': _MESSAGES['codex_cli_too_old']},
                    profile=None,
                    recovery_attempted=recovery_latch['attempted'],
                )

            profile = _profile_from_account(account_info)
            try:
                usage = _normalize_rate_limits(operation.request(METHOD_RATE_LIMITS_READ, {}))
                return ProviderFetchResult(usage=usage, profile=profile, recovery_attempted=recovery_latch['attempted'])
            except _MalformedProviderData as error:
                log.warning('malformed rate-limit response: %s', error)
                return ProviderFetchResult(
                    usage={'error': _MESSAGES['connection_error']},
                    profile=profile,
                    recovery_attempted=recovery_latch['attempted'],
                )
            except RpcError as error:
                return _classify_and_recover(operation, error, account_info, allow_recovery, recovery_latch)

        return transport.run_operation(operation_body)
    except CodexCliNotFound:
        return ProviderFetchResult(
            usage={'error': _MESSAGES['codex_cli_not_found']},
            profile=None,
            recovery_attempted=recovery_latch['attempted'],
        )
    except TransportError:
        return ProviderFetchResult(
            usage={'error': _MESSAGES['connection_error']},
            profile=None,
            recovery_attempted=recovery_latch['attempted'],
        )


def refresh_profile(transport: AppServerTransport) -> dict[str, Any] | None:
    """Read and normalize the current account independently of usage cooldowns."""
    try:
        def operation_body(operation: Any) -> dict[str, Any] | None:
            return _profile_from_account(_read_account(operation, refresh=False))

        return transport.run_operation(operation_body)
    except (TransportError, RpcError):
        return None


# Helpers


def _read_account(operation: Any, *, refresh: bool) -> Any:
    """Read account state, preserving method-not-found as an incompatibility."""
    try:
        payload = operation.request(METHOD_ACCOUNT_READ, {PARAM_REFRESH_TOKEN: refresh})
        return _parse_account(payload)
    except RpcError as error:
        if error.code == METHOD_NOT_FOUND_CODE:
            raise
        return _UNKNOWN


def _classify_and_recover(operation: Any, error: RpcError, account_info: Any,
                          allow_recovery: bool, recovery_latch: dict[str, bool]) -> ProviderFetchResult:
    """Classify a rate-limit error and run at most one recovery sequence."""
    profile = _profile_from_account(account_info)

    if error.code == METHOD_NOT_FOUND_CODE:
        return ProviderFetchResult(
            usage={'error': _MESSAGES['codex_cli_too_old']},
            profile=profile,
            recovery_attempted=recovery_latch['attempted'],
        )
    if account_info is None:
        return ProviderFetchResult(
            usage={'error': _MESSAGES['no_token'], 'no_auth': True},
            profile={},
            recovery_attempted=recovery_latch['attempted'],
        )
    if account_info is _UNKNOWN:
        return ProviderFetchResult(
            usage=_classify_error(error),
            profile=None,
            recovery_attempted=recovery_latch['attempted'],
        )
    if account_info['type'] != 'chatgpt':
        return ProviderFetchResult(
            usage={'error': _MESSAGES['not_chatgpt_auth']},
            profile=profile,
            recovery_attempted=recovery_latch['attempted'],
        )

    if allow_recovery and not recovery_latch['attempted']:
        # Set before the refresh-enabled write so a generation retry cannot
        # issue a second proactive refresh in the same logical operation.
        recovery_latch['attempted'] = True
        try:
            refreshed_info = _read_account(operation, refresh=True)
        except RpcError:
            return ProviderFetchResult(
                usage={'error': _MESSAGES['codex_cli_too_old']},
                profile=profile,
                recovery_attempted=True,
            )

        refreshed_profile = _profile_from_account(refreshed_info)
        if refreshed_profile is not None:
            profile = refreshed_profile
        try:
            usage = _normalize_rate_limits(operation.request(METHOD_RATE_LIMITS_READ, {}))
            return ProviderFetchResult(usage=usage, profile=profile, recovery_attempted=True)
        except _MalformedProviderData as malformed:
            log.warning('malformed rate-limit response after recovery: %s', malformed)
            return ProviderFetchResult(usage={'error': _MESSAGES['connection_error']}, profile=profile, recovery_attempted=True)
        except RpcError as retry_error:
            return ProviderFetchResult(usage=_classify_error(retry_error), profile=profile, recovery_attempted=True)

    return ProviderFetchResult(
        usage=_classify_error(error),
        profile=profile,
        recovery_attempted=recovery_latch['attempted'],
    )


def _is_auth_error(error: RpcError) -> bool:
    """Return whether an error exactly matches verified authentication evidence."""
    return error.code in AUTH_ERROR_CODES


def _classify_error(error: RpcError) -> dict[str, Any]:
    """Map an RPC error to the usage response contract."""
    if error.code == METHOD_NOT_FOUND_CODE:
        return {'error': _MESSAGES['codex_cli_too_old']}
    if _is_auth_error(error):
        return {'error': _MESSAGES['auth_expired'], 'auth_error': True}
    return {'error': _MESSAGES['connection_error']}


def _parse_account(payload: Any) -> Any:
    """Extract account data; distinguish signed-out from unavailable state."""
    if not isinstance(payload, dict) or 'account' not in payload:
        return _UNKNOWN

    account = payload['account']
    if account is None:
        return None
    if not isinstance(account, dict):
        return _UNKNOWN

    account_type = account.get('type')
    if not isinstance(account_type, str) or not account_type.strip():
        return _UNKNOWN

    return {
        # Treat the protocol discriminator case-insensitively.  The current
        # wire values are lower/camel case, but classification and account
        # fingerprints must not change if a CLI version changes only casing.
        'type': account_type.strip().casefold(),
        'email': str(account.get('email') or ''),
        'plan': str(account.get('planType') or ''),
    }


def _profile_from_account(account_info: Any) -> dict[str, Any] | None:
    """Build the existing profile shape from normalized account state."""
    if account_info is _UNKNOWN:
        return None
    if account_info is None:
        return {}

    display_email = account_info['email'].strip()
    normalized_email = display_email.lower()
    fingerprint = f"{account_info['type']}:{normalized_email}" if normalized_email else None
    return {
        'account': {'email': display_email, 'uuid': fingerprint},
        'organization': {'organization_type': account_info['plan']},
    }


def _normalize_rate_limits(payload: Any) -> dict[str, Any]:
    """Normalize one app-server rate-limit response into quota fields."""
    if not isinstance(payload, dict):
        raise _MalformedProviderData('response is not an object')
    if 'rateLimitsByLimitId' not in payload and 'rateLimits' not in payload:
        raise _MalformedProviderData('response has no rate-limit source')

    candidates: list[tuple[str, bool, str]] = []
    entries: list[dict[str, Any]] = []
    malformed = False

    keyed = payload.get('rateLimitsByLimitId')
    if keyed is not None and not isinstance(keyed, dict):
        malformed = True
        keyed = None

    if isinstance(keyed, dict) and keyed:
        limit_ids = sorted(limit_id for limit_id in keyed if isinstance(limit_id, str))
        if len(limit_ids) != len(keyed):
            malformed = True
        for limit_id in limit_ids:
            bucket = keyed[limit_id]
            if not isinstance(bucket, dict):
                malformed = True
                continue
            limit_name = bucket.get('limitName')
            if limit_id == 'codex' or not isinstance(limit_name, str) or not limit_name.strip():
                limit_name = None
            else:
                limit_name = limit_name.strip()
            for slot in ('primary', 'secondary'):
                window = bucket.get(slot)
                try:
                    entry = _window_entry(window, limit_name)
                except _MalformedProviderData:
                    malformed = True
                    continue
                if entry is None:
                    continue
                duration = window.get('windowDurationMins') if isinstance(window, dict) else None
                candidates.append((_field_name(duration, limit_id, None), True, slot))
                entries.append(entry)
    else:
        snapshot = payload.get('rateLimits')
        if snapshot is None:
            snapshot = {}
        if not isinstance(snapshot, dict):
            raise _MalformedProviderData('rateLimits is not an object')
        for slot in ('primary', 'secondary'):
            window = snapshot.get(slot)
            try:
                entry = _window_entry(window)
            except _MalformedProviderData:
                malformed = True
                continue
            if entry is None:
                continue
            duration = window.get('windowDurationMins') if isinstance(window, dict) else None
            candidates.append((_field_name(duration, None, slot), False, slot))
            entries.append(entry)

    if malformed and not entries:
        raise _MalformedProviderData('response contains no usable rate-limit windows')

    result: dict[str, Any] = {}
    for (candidate, is_keyed, slot), entry in zip(candidates, entries):
        name = candidate
        if name in result and not is_keyed:
            name = f'{candidate}_{slot}'
        if name in result:
            counter = 2
            while f'{candidate}_{counter}' in result:
                counter += 1
            name = f'{candidate}_{counter}'
        result[name] = entry

    return result


def _window_entry(window: Any, limit_name: str | None = None) -> dict[str, Any] | None:
    """Convert one wire window into a quota entry with optional display metadata."""
    if window is None:
        return None
    if not isinstance(window, dict):
        raise _MalformedProviderData('rate-limit window is not an object')
    percent = window.get('usedPercent')
    if percent is None:
        return None

    if isinstance(percent, bool) or not isinstance(percent, (int, float, str)):
        raise _MalformedProviderData('usedPercent is not numeric')
    try:
        utilization = float(percent)
    except (TypeError, ValueError) as error:
        raise _MalformedProviderData('usedPercent is not numeric') from error
    if not math.isfinite(utilization):
        raise _MalformedProviderData('usedPercent is not finite')

    resets = window.get('resetsAt')
    resets_at = ''
    if resets is not None and not isinstance(resets, bool) and isinstance(resets, (int, float, str)):
        try:
            timestamp = float(resets)
            if math.isfinite(timestamp) and timestamp > 0:
                resets_at = datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()
        except (OSError, OverflowError, TypeError, ValueError):
            resets_at = ''
    entry = {'utilization': utilization, 'resets_at': resets_at}
    if limit_name:
        entry['limit_name'] = limit_name
    return entry


def _field_name(minutes: Any, limit_id: str | None, slot: str | None) -> str:
    """Derive a collision-ready field name for one quota window."""
    duration_name = _duration_field_name(minutes)
    if limit_id is not None:
        slug = _model_slug(limit_id)
        if duration_name is None:
            return slug or 'limit'
        if limit_id == 'codex':
            return duration_name
        return f'{duration_name}_{slug or "limit"}'
    return duration_name if duration_name is not None else (slot or 'limit')


def _duration_field_name(minutes: Any) -> str | None:
    """Map a positive minute duration to a parseable quota field prefix."""
    if not isinstance(minutes, int) or isinstance(minutes, bool) or minutes <= 0:
        return None
    if minutes in _KNOWN_DURATION_NAMES:
        return _KNOWN_DURATION_NAMES[minutes]
    if minutes % 1440 == 0:
        days = minutes // 1440
        return f'{_NUMBER_TO_WORD[days]}_day' if days in _NUMBER_TO_WORD else f'{days}_day'
    if minutes % 60 == 0:
        hours = minutes // 60
        return f'{_NUMBER_TO_WORD[hours]}_hour' if hours in _NUMBER_TO_WORD else f'{hours}_hour'
    return f'{minutes}_minute'


def _model_slug(display_name: str) -> str:
    """Convert a model display name into a field-name suffix (e.g. ``'Fable'`` -> ``'fable'``)."""
    cleaned = ''.join(char if char.isalnum() else ' ' for char in display_name.lower())
    return '_'.join(cleaned.split())
