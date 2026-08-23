"""
Internationalization
=====================

Loads translations for the detected system language with English fallback.
"""
from __future__ import annotations

import json
import locale
from pathlib import Path
from typing import Any

__all__ = ['LOCALE_DIR', 'detect_lang_code', 'load_translations', 'T']

LOCALE_DIR = Path(__file__).parent.parent / 'locale'


def detect_lang_code(lang: str) -> str:
    """Detect locale file code from system locale string using convention-based lookup.

    Lookup chain: ``{lang}-{REGION}.json`` → ``{lang}.json`` → ``en.json``.
    No mapping required - the locale directory structure *is* the configuration.

    Parameters
    ----------
    lang : str
        System locale string, e.g. ``'de_DE'`` or ``'German_Germany'``.

    Returns
    -------
    str
        Locale file code (without ``.json``).
    """
    normalized = locale.normalize(lang).split('.')[0]
    parts = normalized.split('_', 1)
    base = parts[0].lower()

    # On Windows, os.getlocale() returns e.g. 'German_Germany', and locale.normalize() fails to rewrite it to an ISO code,
    # so base becomes 'german'. Re-split using 'german' to hopefully trigger a match.
    if len(base) > 3:
        base = locale.normalize(parts[0]).split('.')[0].split('_')[0].lower()

    # Manual overrides for Windows locales that do not normalize cleanly to ISO codes.
    region_override = ''
    if base == 'ukrainian':
        base = 'uk'
    elif base == 'hindi':
        base = 'hi'
    elif base == 'indonesian':
        base = 'id'
    elif base.startswith('chinese'):
        # Windows reports Chinese as e.g. 'Chinese (Simplified)_China' or
        # 'Chinese (Traditional)_Hong Kong SAR'.  The script variant picks
        # between the shipped zh files; the English region name from the
        # original split can never match an ISO region code, so it is only
        # used to infer the script when the name carries none.
        original_region = parts[1] if len(parts) > 1 else ''
        traditional = 'traditional' in base or original_region in ('Taiwan', 'Hong Kong SAR', 'Macao SAR')
        base = 'zh'
        region_override = 'TW' if traditional else 'CN'

    region = region_override or (parts[1] if len(parts) > 1 and len(base) <= 3 else '')

    if region and (LOCALE_DIR / f'{base}-{region}.json').exists():
        return f'{base}-{region}'
    if (LOCALE_DIR / f'{base}.json').exists():
        return base

    return 'en'


def load_translations() -> dict[str, Any]:
    """Load translations for the configured or detected system language, fallback to English."""
    from .settings import LANGUAGE

    if LANGUAGE:
        lang_file = LOCALE_DIR / f'{LANGUAGE}.json'
        if lang_file.exists():
            return json.loads(lang_file.read_text(encoding='utf-8'))

    lang = locale.getlocale()[0] or ''
    lang_code = detect_lang_code(lang)

    return json.loads((LOCALE_DIR / f'{lang_code}.json').read_text(encoding='utf-8'))


T: dict[str, Any] = load_translations()
