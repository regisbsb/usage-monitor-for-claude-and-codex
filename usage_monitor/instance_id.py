"""
Instance Identity
==================

Derives a per-instance identifier from the effective Claude config
directory so multiple monitor instances (one per Claude account) can
coexist, each guarding its own single-instance mutex and autostart
registry entry.

This module must stay free of imports from ``api`` or ``settings`` -
it is used before ``CLAUDE_CONFIG_DIR`` is finalized in ``__main__``.
"""
from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path

__all__ = [
    'combined_instance_suffix', 'config_dir_suffix', 'effective_codex_home',
    'effective_config_dir', 'is_default_codex_home', 'is_default_config_dir',
    'parse_claude_config_dir', 'parse_codex_home', 'parse_config_dir',
]


def _parse_path_flag(argv: list[str], flags: tuple[str, ...]) -> str | None:
    """Extract and normalize the last value for any flag in *flags*."""
    value = None
    for index, arg in enumerate(argv):
        for flag in flags:
            if arg.startswith(f'{flag}='):
                value = arg.split('=', 1)[1]
            elif arg == flag and index + 1 < len(argv):
                value = argv[index + 1]

    if value is None:
        return None
    value = value.strip().strip('"').rstrip('\\/')
    if not value:
        return None
    if re.fullmatch(r'[A-Za-z]:', value):
        value += '\\'
    return str(Path(os.path.expandvars(value)).expanduser())


def parse_config_dir(argv: list[str]) -> str | None:
    """Extract the ``--config-dir`` value from command-line arguments.

    Supports both ``--config-dir=PATH`` and ``--config-dir PATH`` forms.
    Surrounding quotes and a stray trailing quote (left by cmd.exe when
    the path ends with a backslash, e.g. ``--config-dir="C:\\dir\\"``)
    are stripped.  Environment variables (``%USERPROFILE%``) and a
    leading ``~`` are expanded, so the flag works the same from cmd.exe,
    PowerShell, and shortcut targets.

    Parameters
    ----------
    argv : list[str]
        Argument list, typically ``sys.argv``.

    Returns
    -------
    str | None
        The cleaned path value, or ``None`` if the flag is absent or
        has no value.
    """
    return _parse_path_flag(argv, ('--config-dir',))


def parse_claude_config_dir(argv: list[str]) -> str | None:
    """Extract ``--claude-config-dir`` while accepting the legacy alias."""
    return _parse_path_flag(argv, ('--config-dir', '--claude-config-dir'))


def parse_codex_home(argv: list[str]) -> str | None:
    """Extract the ``--codex-home`` path from command-line arguments."""
    return _parse_path_flag(argv, ('--codex-home',))


def effective_config_dir() -> Path:
    """Return the resolved Claude config directory currently in effect."""
    custom = os.environ.get('CLAUDE_CONFIG_DIR')
    base = Path(custom) if custom else Path.home() / '.claude'
    return base.resolve()


def is_default_config_dir() -> bool:
    """Return True when the effective config dir is the default ``~/.claude``."""
    default = (Path.home() / '.claude').resolve()
    return os.path.normcase(str(effective_config_dir())) == os.path.normcase(str(default))


def effective_codex_home() -> Path:
    """Return the resolved Codex home currently in effect."""
    custom = os.environ.get('CODEX_HOME')
    base = Path(custom) if custom else Path.home() / '.codex'
    return base.resolve()


def is_default_codex_home() -> bool:
    """Return True when the effective Codex home is ``~/.codex``."""
    default = (Path.home() / '.codex').resolve()
    return os.path.normcase(str(effective_codex_home())) == os.path.normcase(str(default))


def combined_instance_suffix() -> str:
    """Hash the ordered Claude/Codex directory pair for product identities."""
    if is_default_config_dir() and is_default_codex_home():
        return ''
    normalized = '|'.join((
        os.path.normcase(str(effective_config_dir())),
        os.path.normcase(str(effective_codex_home())),
    ))
    return '_' + hashlib.sha1(normalized.encode('utf-8')).hexdigest()[:12]


def config_dir_suffix() -> str:
    """Return a per-instance suffix for kernel object and registry names.

    Empty for the default ``~/.claude`` directory (preserving the legacy
    names so older versions are still detected), otherwise an underscore
    plus a short hash of the resolved, case-normalized directory path.
    Hashing keeps the names free of characters that are invalid in Win32
    kernel object names (e.g. backslashes).
    """
    if is_default_config_dir():
        return ''

    normalized = os.path.normcase(str(effective_config_dir()))
    return '_' + hashlib.sha1(normalized.encode('utf-8')).hexdigest()[:12]
