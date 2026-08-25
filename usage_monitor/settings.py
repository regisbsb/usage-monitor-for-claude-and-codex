"""
Settings
=========

Centralizes all user-tunable constants.  Structural constants (API URLs,
registry keys, file paths) remain in their respective modules.

Loads an optional ``usage-monitor-settings.json`` to let users override
application and provider settings. Search order:

1. ``$USAGE_MONITOR_CONFIG_DIR/usage-monitor-settings.json`` when set
2. Next to the executable (frozen) or project root (source)
3. ``~/.usage-monitor/usage-monitor-settings.json``
4. Provider-specific legacy locations

The app never creates this file - users place it manually.
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes
import json
import locale as _locale
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .instance_id import effective_config_dir, is_default_config_dir

__all__ = [
    'ALERT_EXTRA_USAGE_SPENT', 'ALERT_TIME_AWARE', 'ALERT_TIME_AWARE_BELOW',
    'BAR_BG', 'BAR_DIVIDER', 'BAR_FG', 'BAR_FG_WARN', 'BAR_MARKER', 'BG',
    'CLI_COMMAND', 'COMPACT_HIDE', 'CURRENCY_SYMBOL',
    'FG', 'FG_DIM', 'FG_HEADING', 'FG_LINK',
    'ICON_DARK', 'ICON_FIELDS', 'ICON_LIGHT', 'ICON_STYLE', 'IDLE_PAUSE',
    'LANGUAGE', 'MAX_BACKOFF', 'NOTIFY_CLAUDE_UPDATE',
    'ON_DOUBLE_CLICK_COMMAND', 'ON_RESET_COMMAND', 'ON_STARTUP_COMMAND', 'ON_THRESHOLD_COMMAND',
    'POLL_ERROR', 'POLL_FAST', 'POLL_FAST_EXTRA', 'POLL_INTERVAL',
    'POPUP_FIELDS', 'SETTINGS_FILENAME',
    'STATUS_SERVER_ENABLED', 'STATUS_SERVER_PORT',
    'TIME_FORMAT', 'TOOLTIP_FIELDS',
    'ProviderSettings', 'get_alert_thresholds', 'get_provider_settings',
]

SETTINGS_FILENAME = 'usage-monitor-settings.json'
LEGACY_CODEX_SETTINGS_FILENAME = 'usage-monitor-for-codex-settings.json'
_LOADED_LEGACY_PROVIDER: str | None = None

_NUMERIC_BOUNDS: dict[str, int] = {
    'poll_interval': 1,
    'poll_fast': 1,
    'poll_fast_extra': 1,
    'poll_error': 1,
    'max_backoff': 1,
    'idle_pause': 0,
    'codex_update_interval': 60,
    'log_max_bytes': 1024,
    'log_backup_count': 0,
    'status_server_port': 1024,
}
_COLOR_KEYS = frozenset({'bg', 'fg', 'fg_dim', 'fg_heading', 'fg_link', 'bar_bg', 'bar_fg', 'bar_fg_warn', 'bar_divider', 'bar_marker'})
_ICON_KEYS = frozenset({'icon_light', 'icon_dark'})
_THRESHOLD_KEY_PREFIX = 'alert_thresholds_'
_PERCENT_KEYS = frozenset({'alert_time_aware_below'})
_STRING_KEYS = frozenset({'currency_symbol', 'language'})
_VALID_TIME_FORMATS = frozenset({'24h', '12h'})
_VALID_ICON_STYLES = frozenset({'number+bars', 'numbers'})
_COMMAND_KEYS = frozenset({'on_double_click_command', 'on_reset_command', 'on_startup_command', 'on_threshold_command'})
_BOOL_KEYS = frozenset({
    'alert_time_aware', 'auto_update_codex_cli', 'enabled',
    'notify_claude_update', 'notify_codex_update', 'status_server_enabled',
})
_STRING_LIST_KEYS = frozenset({'tooltip_fields', 'compact_hide'})
_WILDCARD_STRING_LIST_KEYS = frozenset({'popup_fields'})
_VALID_BAR_MODES = frozenset({'utilization', 'overage'})


def _load_settings() -> dict:
    """Read the combined settings file or a provider-specific legacy fallback."""
    global _LOADED_LEGACY_PROVIDER

    _LOADED_LEGACY_PROVIDER = None
    if getattr(sys, 'frozen', False):
        app_dir = Path(sys.executable).parent
    else:
        app_dir = Path(__file__).resolve().parent.parent

    home = Path.home()
    home_claude = home / '.claude'
    home_codex = home / '.codex'
    combined_config_dir = Path(os.environ['USAGE_MONITOR_CONFIG_DIR']).expanduser() if os.environ.get('USAGE_MONITOR_CONFIG_DIR') else None

    # An explicit combined config root overrides the standard combined
    # locations. Provider-specific locations are migration fallbacks only.
    search_paths: list[tuple[Path, str | None]] = []
    if combined_config_dir is not None:
        search_paths.append((combined_config_dir / SETTINGS_FILENAME, None))
    search_paths.extend([
        (app_dir / SETTINGS_FILENAME, None),
        (home / '.usage-monitor' / SETTINGS_FILENAME, None),
    ])
    if not is_default_config_dir():
        search_paths.append((effective_config_dir() / SETTINGS_FILENAME, 'claude'))
    search_paths.append((home_claude / SETTINGS_FILENAME, 'claude'))
    codex_home = Path(os.environ.get('CODEX_HOME', home_codex)).expanduser()
    search_paths.append((codex_home / LEGACY_CODEX_SETTINGS_FILENAME, 'codex'))

    for path, legacy_provider in search_paths:
        if path.is_file():
            try:
                # utf-8-sig reads BOM-less UTF-8 identically and strips a BOM
                # when present (written by e.g. PowerShell 5 or legacy Notepad).
                text = path.read_text(encoding='utf-8-sig').strip()
                if not text:
                    return {}
                data = json.loads(text)
                if not isinstance(data, dict):
                    raise ValueError(f'Expected a JSON object, got {type(data).__name__}')
                validated = _validate_combined(data, path)
                if legacy_provider is not None:
                    _LOADED_LEGACY_PROVIDER = legacy_provider
                return validated
            except (json.JSONDecodeError, ValueError) as exc:
                ctypes.windll.user32.MessageBoxW(
                    0, f'Invalid JSON in settings file:\n{path}\n\n{exc}',
                    'Usage Monitor for Claude and Codex - Settings Error', 0x30,
                )
                return {}
            except OSError:
                return {}

    return {}


def _valid_rgba(value: object) -> bool:
    """Return True if *value* is a list of exactly 4 integers in 0\u2013255."""
    return (
        isinstance(value, list) and len(value) == 4
        and all(isinstance(c, int) and not isinstance(c, bool) and 0 <= c <= 255 for c in value)
    )


def _validate_combined(data: dict[str, Any], path: Path) -> dict[str, Any]:
    """Validate shared and provider sections without mixing their values."""
    if 'application' not in data and 'providers' not in data:
        return _validate(data, path)

    result = dict(data)
    application = result.get('application')
    if application is not None:
        if isinstance(application, dict):
            result['application'] = _validate(dict(application), path)
        else:
            ctypes.windll.user32.MessageBoxW(
                0, f'Invalid values in settings file:\n{path}\n\n  application: expected an object',
                'Usage Monitor for Claude and Codex - Settings Error', 0x30,
            )
            result.pop('application', None)

    providers = result.get('providers')
    if providers is not None:
        if isinstance(providers, dict):
            validated_providers: dict[str, dict[str, Any]] = {}
            for provider_id in ('claude', 'codex'):
                section = providers.get(provider_id)
                if isinstance(section, dict):
                    validated_providers[provider_id] = _validate(dict(section), path)
            result['providers'] = validated_providers
        else:
            ctypes.windll.user32.MessageBoxW(
                0, f'Invalid values in settings file:\n{path}\n\n  providers: expected an object',
                'Usage Monitor for Claude and Codex - Settings Error', 0x30,
            )
            result.pop('providers', None)

    shared = {key: value for key, value in result.items() if key not in {'application', 'providers'}}
    shared = _validate(shared, path)
    if 'application' in result:
        shared['application'] = result['application']
    if 'providers' in result:
        shared['providers'] = result['providers']
    return shared


def _validate(data: dict, path: Path) -> dict:
    """Drop entries with invalid types or values and show a MessageBox listing errors."""
    errors: list[str] = []
    drop: list[str] = []

    for key, value in data.items():
        if key in _NUMERIC_BOUNDS:
            min_val = _NUMERIC_BOUNDS[key]
            if isinstance(value, bool) or not isinstance(value, int):
                errors.append(f'  {key}: expected an integer, got {type(value).__name__}')
                drop.append(key)
            elif value < min_val:
                errors.append(f'  {key}: must be >= {min_val}, got {value}')
                drop.append(key)

        elif key in _COLOR_KEYS:
            if not isinstance(value, str):
                errors.append(f'  {key}: expected a color string, got {type(value).__name__}')
                drop.append(key)

        elif key.startswith(_THRESHOLD_KEY_PREFIX):
            if not isinstance(value, list):
                errors.append(f'  {key}: expected an array, got {type(value).__name__}')
                drop.append(key)
            else:
                bad = [v for v in value if isinstance(v, bool) or not isinstance(v, (int, float)) or not (1 <= v <= 100)]
                if bad:
                    errors.append(f'  {key}: all values must be numbers between 1 and 100')
                    drop.append(key)
                else:
                    data[key] = sorted(set(value))

        elif key == 'alert_extra_usage_spent':
            if not isinstance(value, list):
                errors.append(f'  {key}: expected an array, got {type(value).__name__}')
                drop.append(key)
            else:
                bad = [v for v in value if isinstance(v, bool) or not isinstance(v, (int, float)) or v <= 0]
                if bad:
                    errors.append(f'  {key}: all values must be numbers greater than 0')
                    drop.append(key)
                else:
                    data[key] = sorted(set(value))

        elif key in _PERCENT_KEYS:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                errors.append(f'  {key}: expected a number, got {type(value).__name__}')
                drop.append(key)
            elif not (1 <= value <= 100):
                errors.append(f'  {key}: must be between 1 and 100, got {value}')
                drop.append(key)

        elif key in _STRING_KEYS:
            if not isinstance(value, str):
                errors.append(f'  {key}: expected a string, got {type(value).__name__}')
                drop.append(key)

        elif key == 'time_format':
            if value not in _VALID_TIME_FORMATS:
                errors.append(f'  {key}: must be "24h" or "12h", got {value!r}')
                drop.append(key)

        elif key == 'icon_style':
            if value not in _VALID_ICON_STYLES:
                errors.append(f'  {key}: must be "number+bars" or "numbers", got {value!r}')
                drop.append(key)

        elif key in _COMMAND_KEYS:
            if isinstance(value, str):
                # An empty or whitespace-only string means "not set" (like [])
                # so it never activates the command machinery, e.g. the
                # double-click handler with its deferred single click.
                data[key] = [value] if value.strip() else []
            elif isinstance(value, list):
                if any(not isinstance(item, str) or not item.strip() for item in value):
                    errors.append(f'  {key}: all items must be non-empty strings')
                    drop.append(key)
            else:
                errors.append(f'  {key}: expected a string or array of strings, got {type(value).__name__}')
                drop.append(key)

        elif key in _BOOL_KEYS:
            if not isinstance(value, bool):
                errors.append(f'  {key}: expected true or false, got {type(value).__name__}')
                drop.append(key)

        elif key in _STRING_LIST_KEYS:
            if not isinstance(value, list):
                errors.append(f'  {key}: expected an array, got {type(value).__name__}')
                drop.append(key)
            elif any(not isinstance(item, str) or not item for item in value):
                errors.append(f'  {key}: all entries must be non-empty strings')
                drop.append(key)
            else:
                seen: set[str] = set()
                deduped: list[str] = []
                for item in value:
                    if item not in seen:
                        seen.add(item)
                        deduped.append(item)
                data[key] = deduped

        elif key in _WILDCARD_STRING_LIST_KEYS:
            if not isinstance(value, list):
                errors.append(f'  {key}: expected an array, got {type(value).__name__}')
                drop.append(key)
            elif any(not isinstance(item, str) or not item for item in value):
                errors.append(f'  {key}: all entries must be non-empty strings')
                drop.append(key)
            elif value.count('*') > 1:
                errors.append(f'  {key}: "*" may appear at most once')
                drop.append(key)
            else:
                seen_wc: set[str] = set()
                deduped_wc: list[str] = []
                for item in value:
                    if item == '*' or item not in seen_wc:
                        seen_wc.add(item)
                        deduped_wc.append(item)
                data[key] = deduped_wc

        elif key == 'icon_fields':
            if not isinstance(value, list):
                errors.append(f'  {key}: expected an array, got {type(value).__name__}')
                drop.append(key)
            elif len(value) != 2:
                errors.append(f'  {key}: expected exactly 2 entries, got {len(value)}')
                drop.append(key)
            elif any(not isinstance(item, str) or not item for item in value):
                errors.append(f'  {key}: all entries must be non-empty strings')
                drop.append(key)
            else:
                invalid_modes = [
                    item for item in value
                    if ':' in item and item.split(':', 1)[1] not in _VALID_BAR_MODES
                ]
                if invalid_modes:
                    errors.append(
                        f'  {key}: unknown bar mode in: {", ".join(invalid_modes)}'
                        f' (valid: {", ".join(sorted(_VALID_BAR_MODES))})'
                    )
                    drop.append(key)

        elif key in _ICON_KEYS:
            if not isinstance(value, dict):
                errors.append(f'  {key}: expected an object, got {type(value).__name__}')
                drop.append(key)
            else:
                bad = [k for k, v in value.items() if not _valid_rgba(v)]
                for k in bad:
                    errors.append(f'  {key}.{k}: expected [R, G, B, A] with integers 0\u2013255')
                    del value[k]

        elif key == 'cli_command':
            # An empty object is valid and means "not set" - the native CLI
            # auto-detection stays active.
            if not isinstance(value, dict):
                errors.append(f'  {key}: expected an object mapping a name to a command array, got {type(value).__name__}')
                drop.append(key)
            else:
                invalid = False
                for name, command in value.items():
                    if not name.strip():
                        errors.append(f'  {key}: names must be non-empty strings')
                        invalid = True
                        break
                    if not isinstance(command, list) or not command or any(not isinstance(item, str) or not item.strip() for item in command):
                        errors.append(f'  {key}.{name}: expected a non-empty array of non-empty strings')
                        invalid = True
                        break
                if invalid:
                    drop.append(key)

    for key in drop:
        del data[key]

    if errors:
        ctypes.windll.user32.MessageBoxW(
            0, f'Invalid values in settings file:\n{path}\n\n' + '\n'.join(errors),
            'Usage Monitor for Claude and Codex - Settings Error', 0x30,
        )

    return data


def _icon_colors(key: str, defaults: dict[str, tuple]) -> dict[str, tuple]:
    """Merge icon color overrides from settings, converting JSON arrays to tuples."""
    overrides = _S.get(key, {})
    return {k: tuple(overrides[k]) if k in overrides else v for k, v in defaults.items()}


_LOADED_SETTINGS = _load_settings()
_RAW_SETTINGS = (
    {'providers': {_LOADED_LEGACY_PROVIDER: _LOADED_SETTINGS}}
    if _LOADED_LEGACY_PROVIDER is not None
    else _LOADED_SETTINGS
)


def _string_keyed_dict(value: object) -> dict[str, Any]:
    """Return string-keyed mapping entries from a decoded settings object."""
    if not isinstance(value, dict):
        return {}
    return {key: entry for key, entry in value.items() if isinstance(key, str)}


_provider_sections_value = _RAW_SETTINGS.get('providers')
_application_section_value = _RAW_SETTINGS.get('application')
_PROVIDER_SECTIONS = _string_keyed_dict(_provider_sections_value)
_APPLICATION_SECTION = _string_keyed_dict(_application_section_value)
_S: dict[str, Any] = {
    **{key: value for key, value in _RAW_SETTINGS.items() if key not in {'application', 'providers'}},
    **_APPLICATION_SECTION,
}

# Polling intervals (seconds)
POLL_INTERVAL = _S.get('poll_interval', 180)
POLL_FAST = _S.get('poll_fast', 120)
POLL_FAST_EXTRA = _S.get('poll_fast_extra', 2)
POLL_ERROR = _S.get('poll_error', 30)
MAX_BACKOFF = _S.get('max_backoff', 900)
IDLE_PAUSE = _S.get('idle_pause', 300)

# Popup theme
BG = _S.get('bg', '#1e1e1e')
FG = _S.get('fg', '#cccccc')
FG_DIM = _S.get('fg_dim', '#888888')
FG_HEADING = _S.get('fg_heading', '#ffffff')
FG_LINK = _S.get('fg_link', '#4a9eff')
BAR_BG = _S.get('bar_bg', '#333333')
BAR_FG = _S.get('bar_fg', '#4a9eff')
BAR_FG_WARN = _S.get('bar_fg_warn', '#e05050')
BAR_DIVIDER = _S.get('bar_divider', '#000c')
BAR_MARKER = _S.get('bar_marker', '#fffc')

# Tray icon colors
ICON_LIGHT = _icon_colors('icon_light', {
    'fg': (255, 255, 255, 255),
    'fg_half': (255, 255, 255, 80),
    'fg_dim': (255, 255, 255, 140),
    'fg_warn': (224, 80, 80, 255),
})
ICON_DARK = _icon_colors('icon_dark', {
    'fg': (0, 0, 0, 255),
    'fg_half': (0, 0, 0, 80),
    'fg_dim': (0, 0, 0, 140),
    'fg_warn': (224, 80, 80, 255),
})

# Tray icon fields
ICON_FIELDS: list[str] = _S.get('icon_fields', ['five_hour', 'seven_day'])

# Tray icon layout: 'number+bars' shows the top field's percentage above two
# usage bars, 'numbers' shows both fields as two stacked percentages
ICON_STYLE: str = _S.get('icon_style', 'number+bars')

# Tooltip fields
TOOLTIP_FIELDS: list[str] = _S.get('tooltip_fields', ['five_hour', 'seven_day'])

# Popup fields
POPUP_FIELDS: list[str] = _S.get('popup_fields', ['*'])

# Sections and usage bars hidden while the popup is pinned (compact view)
COMPACT_HIDE: list[str] = _S.get('compact_hide', [])

# Alert thresholds
ALERT_TIME_AWARE: bool = _S.get('alert_time_aware', True)
ALERT_TIME_AWARE_BELOW: float = _S.get('alert_time_aware_below', 90)

# Notify when a background token refresh installs a new Claude CLI version
NOTIFY_CLAUDE_UPDATE: bool = _S.get('notify_claude_update', True)

# Currency

def _detect_currency_symbol() -> str:
    """Detect the system locale currency symbol for monetary formatting."""
    try:
        _locale.setlocale(_locale.LC_MONETARY, '')
        return _locale.localeconv().get('currency_symbol', '') or ''
    except _locale.Error:
        return ''


_SYSTEM_CURRENCY_SYMBOL = _detect_currency_symbol()
# None when the user set no override: presence must be explicit, because an
# override that happens to equal the system symbol still has to win over the
# API billing currency.
CURRENCY_SYMBOL: str | None = _S.get('currency_symbol')

# Language override
LANGUAGE: str = _S.get('language', '')

# Clock format for reset times: '24h' (e.g. 14:30) or '12h' (e.g. 2:30 PM)

def _detect_system_time_format() -> str:
    """Detect whether the Windows clock uses a 24-hour or 12-hour format.

    Reads ``LOCALE_ITIME`` for the current user locale, which returns ``1``
    for a 24-hour clock and ``0`` for a 12-hour (AM/PM) clock and honors any
    regional customizations.  Falls back to ``'24h'`` if the query fails.
    """
    LOCALE_NAME_USER_DEFAULT = None  # NULL selects the current user locale
    LOCALE_ITIME = 0x00000023
    LOCALE_RETURN_NUMBER = 0x20000000
    value = ctypes.wintypes.DWORD()
    chars = ctypes.windll.kernel32.GetLocaleInfoEx(
        LOCALE_NAME_USER_DEFAULT, LOCALE_ITIME | LOCALE_RETURN_NUMBER,
        ctypes.cast(ctypes.byref(value), ctypes.c_wchar_p), 2,
    )
    if chars == 0:
        return '24h'
    return '24h' if value.value == 1 else '12h'


_SYSTEM_TIME_FORMAT = _detect_system_time_format()
TIME_FORMAT: str = _S.get('time_format', _SYSTEM_TIME_FORMAT)

# Extra Claude CLI command(s) to report a version for - name -> base command
# (e.g. run the version check inside WSL).  Display only: these are listed in
# addition to the auto-detected native binary and the IDE extensions, and never
# take part in authentication (see claude_cli.py).
CLI_COMMAND: dict[str, list[str]] = _S.get('cli_command', {})

# Event commands
ON_DOUBLE_CLICK_COMMAND: list[str] = _S.get('on_double_click_command', [])
ON_RESET_COMMAND: list[str] = _S.get('on_reset_command', [])
ON_STARTUP_COMMAND: list[str] = _S.get('on_startup_command', [])
ON_THRESHOLD_COMMAND: list[str] = _S.get('on_threshold_command', [])

_ALERT_THRESHOLDS: dict[str, list[float]] = {
    'five_hour': [50, 80, 95],
    'seven_day': [95],
    'extra_usage': [50, 80, 95],
}

# Absolute extra-usage spending amounts (in major currency units, e.g. dollars)
# that trigger a notification.  Complements the percentage thresholds and is
# the only alert that can fire when extra usage has no monthly limit.  Empty
# by default - sensible amounts depend on the account's currency and budget.
ALERT_EXTRA_USAGE_SPENT: list[float] = _S.get('alert_extra_usage_spent', [])

LOG_MAX_BYTES: int = _S.get('log_max_bytes', 2 * 1024 * 1024)
LOG_BACKUP_COUNT: int = _S.get('log_backup_count', 3)

# Local loopback-only JSON status endpoint (see docs/status-endpoint.md).
# Read-only and optional: a bind failure never stops the app.
STATUS_SERVER_ENABLED: bool = _S.get('status_server_enabled', True)
STATUS_SERVER_PORT: int = _S.get('status_server_port', 45455)


def get_alert_thresholds(variant_key: str) -> list[float]:
    """Return the alert thresholds for a usage variant.

    Uses a fallback chain: exact user override, built-in default for
    the exact key, user override for the base period, built-in default
    for the base period, then empty list (alerts disabled).

    Parameters
    ----------
    variant_key : str
        API variant key, e.g. ``'five_hour'``, ``'seven_day_sonnet'``,
        or ``'extra_usage'``.
    """
    exact_settings_key = f'{_THRESHOLD_KEY_PREFIX}{variant_key}'
    if exact_settings_key in _S:
        return _S[exact_settings_key]

    if variant_key in _ALERT_THRESHOLDS:
        return _ALERT_THRESHOLDS[variant_key]

    # Fallback to base period (strip variant suffix)
    parts = variant_key.split('_', 2)
    if len(parts) >= 3:
        base_key = f'{parts[0]}_{parts[1]}'
        base_settings_key = f'{_THRESHOLD_KEY_PREFIX}{base_key}'
        if base_settings_key in _S:
            return _S[base_settings_key]
        if base_key in _ALERT_THRESHOLDS:
            return _ALERT_THRESHOLDS[base_key]

    return []


@dataclass(frozen=True)
class ProviderSettings:
    """Immutable settings for one independently scheduled provider monitor."""

    provider_id: str
    enabled: bool
    poll_interval: int
    poll_fast: int
    poll_fast_extra: int
    poll_error: int
    max_backoff: int
    idle_pause: int
    icon_fields: list[str]
    icon_style: str
    tooltip_fields: list[str]
    popup_fields: list[str]
    compact_hide: list[str]
    alert_time_aware: bool
    alert_time_aware_below: float
    notify_update: bool
    cli_command: dict[str, list[str]]
    on_double_click_command: list[str]
    on_reset_command: list[str]
    on_startup_command: list[str]
    on_threshold_command: list[str]
    alert_extra_usage_spent: list[float]
    auto_update_cli: bool
    update_interval: int
    values: dict[str, Any]

    def alert_thresholds(self, variant_key: str) -> list[float]:
        """Return provider-specific thresholds with the shared fallback chain."""
        exact_key = f'{_THRESHOLD_KEY_PREFIX}{variant_key}'
        if exact_key in self.values:
            return self.values[exact_key]
        if variant_key in _ALERT_THRESHOLDS:
            return _ALERT_THRESHOLDS[variant_key]

        parts = variant_key.split('_', 2)
        if len(parts) >= 3:
            base_key = f'{parts[0]}_{parts[1]}'
            configured_key = f'{_THRESHOLD_KEY_PREFIX}{base_key}'
            if configured_key in self.values:
                return self.values[configured_key]
            return _ALERT_THRESHOLDS.get(base_key, [])
        return []


def get_provider_settings(provider_id: str) -> ProviderSettings:
    """Return settings for ``claude`` or ``codex`` with shared defaults overlaid."""
    if provider_id not in {'claude', 'codex'}:
        raise ValueError(f'Unknown provider: {provider_id}')

    section = _PROVIDER_SECTIONS.get(provider_id, {})
    values = {**_S, **section} if isinstance(section, dict) else dict(_S)
    return ProviderSettings(
        provider_id=provider_id,
        enabled=values.get('enabled', True),
        poll_interval=values.get('poll_interval', POLL_INTERVAL),
        poll_fast=values.get('poll_fast', POLL_FAST),
        poll_fast_extra=values.get('poll_fast_extra', POLL_FAST_EXTRA),
        poll_error=values.get('poll_error', POLL_ERROR),
        max_backoff=values.get('max_backoff', MAX_BACKOFF),
        idle_pause=values.get('idle_pause', IDLE_PAUSE),
        icon_fields=list(values.get('icon_fields', ICON_FIELDS)),
        icon_style=values.get('icon_style', ICON_STYLE),
        tooltip_fields=list(values.get('tooltip_fields', TOOLTIP_FIELDS)),
        popup_fields=list(values.get('popup_fields', POPUP_FIELDS)),
        compact_hide=list(values.get('compact_hide', COMPACT_HIDE)),
        alert_time_aware=values.get('alert_time_aware', ALERT_TIME_AWARE),
        alert_time_aware_below=values.get('alert_time_aware_below', ALERT_TIME_AWARE_BELOW),
        notify_update=values.get(
            'notify_claude_update' if provider_id == 'claude' else 'notify_codex_update',
            True,
        ),
        cli_command=dict(values.get('cli_command', CLI_COMMAND)) if provider_id == 'claude' else {},
        on_double_click_command=list(values.get('on_double_click_command', ON_DOUBLE_CLICK_COMMAND)),
        on_reset_command=list(values.get('on_reset_command', ON_RESET_COMMAND)),
        on_startup_command=list(values.get('on_startup_command', ON_STARTUP_COMMAND)),
        on_threshold_command=list(values.get('on_threshold_command', ON_THRESHOLD_COMMAND)),
        alert_extra_usage_spent=list(values.get('alert_extra_usage_spent', ALERT_EXTRA_USAGE_SPENT)),
        auto_update_cli=provider_id == 'codex' and values.get('auto_update_codex_cli', True),
        update_interval=values.get('codex_update_interval', 86400),
        values=values,
    )
