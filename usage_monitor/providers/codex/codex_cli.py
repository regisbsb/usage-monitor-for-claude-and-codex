"""
Codex CLI
=========

Discovers Codex installations on the system. Does not handle credentials.
"""
from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

__all__ = [
    'CHANGELOG_URL', 'CODEX_CLI_PATH', 'PROJECT_URL', 'CliUpdateResult',
    'CodexInstallation', 'cli_version', 'find_installations', 'update_cli',
]

log = logging.getLogger(__name__)

CHANGELOG_URL = 'https://github.com/openai/codex/releases'
PROJECT_URL = 'https://github.com/ihor-sokoliuk/usage-monitor-for-codex'

_EXTENSION_DIRS: list[tuple[str, Path]] = [
    ('VS Code', Path.home() / '.vscode' / 'extensions'),
    ('VS Code Insiders', Path.home() / '.vscode-insiders' / 'extensions'),
    ('Cursor', Path.home() / '.cursor' / 'extensions'),
    ('Windsurf', Path.home() / '.windsurf' / 'extensions'),
]
_EXTENSION_PREFIX = 'openai.chatgpt-'
_version_cache: dict[Path, tuple[float, str]] = {}


def _discover_cli_path() -> Path:
    """Discover the Codex CLI binary path without accessing credentials."""
    found = shutil.which('codex')
    if found:
        path = Path(found)
        if path.suffix.lower() == '.ps1':
            for extension in ('.cmd', '.exe'):
                executable_sibling = path.with_suffix(extension)
                if executable_sibling.is_file():
                    return executable_sibling
        else:
            return path

    localappdata = Path(os.environ.get('LOCALAPPDATA', Path.home() / 'AppData' / 'Local'))
    installer_path = localappdata / 'Programs' / 'OpenAI' / 'Codex' / 'bin' / 'codex.exe'
    if installer_path.is_file():
        return installer_path

    appdata = os.environ.get('APPDATA')
    if appdata:
        for name in ('codex.cmd', 'codex.exe'):
            candidate = Path(appdata) / 'npm' / name
            if candidate.is_file():
                return candidate

    return installer_path


CODEX_CLI_PATH = _discover_cli_path()


@dataclass
class CodexInstallation:
    """A discovered Codex installation."""

    name: str
    version: str
    path: Path


@dataclass(frozen=True)
class CliUpdateResult:
    """Outcome of a ``codex update`` invocation."""

    success: bool
    updated: bool
    old_version: str
    new_version: str
    error: str


def find_installations() -> list[CodexInstallation]:
    """Discover the native Codex CLI and common IDE extension installations."""
    results: list[CodexInstallation] = []
    if CODEX_CLI_PATH.is_file():
        version = cli_version(CODEX_CLI_PATH)
        if version:
            results.append(CodexInstallation('CLI', version, CODEX_CLI_PATH))

    for ide_name, extension_directory in _EXTENSION_DIRS:
        try:
            if not extension_directory.is_dir():
                continue

            best_version = ''
            best_parts: tuple[int, ...] = ()
            best_path = None
            for entry in extension_directory.iterdir():
                if not entry.is_dir() or not entry.name.startswith(_EXTENSION_PREFIX):
                    continue
                remainder = entry.name[len(_EXTENSION_PREFIX):]
                match = re.match(r'(\d+\.\d+\.\d+)', remainder)
                if not match:
                    continue
                version = match.group(1)
                parts = tuple(int(part) for part in version.split('.'))
                if parts > best_parts:
                    best_version = version
                    best_parts = parts
                    best_path = entry
        except OSError:
            continue

        if best_version and best_path:
            results.append(CodexInstallation(ide_name, best_version, best_path))

    return results


def cli_version(path: Path) -> str:
    """Run ``codex --version`` and return the semantic version, or ``''``."""
    try:
        modified_time = path.stat().st_mtime
        cached = _version_cache.get(path)
        if cached and cached[0] == modified_time:
            return cached[1]

        process = subprocess.run(
            [str(path), '--version'],
            capture_output=True,
            text=True,
            timeout=10,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        match = re.search(r'(\d+\.\d+\.\d+)', process.stdout.strip())
        version = match.group(1) if match else ''
        _version_cache[path] = (modified_time, version)
        return version
    except Exception:
        return ''


def update_cli() -> CliUpdateResult:
    """Ask the installed Codex CLI to apply its latest supported update."""
    if not CODEX_CLI_PATH.is_file():
        return CliUpdateResult(False, False, '', '', 'CLI not found')

    old_version = cli_version(CODEX_CLI_PATH)
    log.info('codex update started (installed: %s)', old_version or '?')
    try:
        process = subprocess.run(
            [str(CODEX_CLI_PATH), 'update'],
            capture_output=True,
            text=True,
            timeout=120,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except subprocess.TimeoutExpired:
        log.warning('codex update -> timeout')
        return CliUpdateResult(False, False, old_version, old_version, 'Timeout')
    except OSError as error:
        code = getattr(error, 'winerror', None) or getattr(error, 'errno', None) or '?'
        log.warning('codex update -> OS error %s', code)
        return CliUpdateResult(False, False, old_version, old_version, f'OS error {code}')

    if process.returncode != 0:
        log.warning('codex update -> exit code %s', process.returncode)
        return CliUpdateResult(
            False, False, old_version, old_version,
            f'codex update exited with code {process.returncode}',
        )

    _version_cache.pop(CODEX_CLI_PATH, None)
    new_version = cli_version(CODEX_CLI_PATH)
    updated = bool(old_version and new_version and new_version != old_version)
    log.info('codex update -> OK (installed: %s, updated: %s)', new_version or '?', updated)
    return CliUpdateResult(True, updated, old_version, new_version or old_version, '')


