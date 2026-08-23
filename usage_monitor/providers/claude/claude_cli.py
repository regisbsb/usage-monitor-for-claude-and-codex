"""Claude Code installation discovery and native token refresh."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

CHANGELOG_URL = "https://github.com/anthropics/claude-code/blob/main/CHANGELOG.md"
PROJECT_URL = "https://github.com/jens-duttke/usage-monitor-for-claude"
_CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
_EXTENSION_PREFIX = "anthropic.claude-code-"

__all__ = [
    "CHANGELOG_URL",
    "PROJECT_URL",
    "ClaudeCLI",
    "ClaudeInstallation",
    "RefreshResult",
]


@dataclass(frozen=True)
class ClaudeInstallation:
    name: str
    version: str
    path: Path


@dataclass(frozen=True)
class RefreshResult:
    success: bool
    updated: bool
    old_version: str
    new_version: str
    error: str


class ClaudeCLI:
    """Provider-local CLI facade.

    A configured command (for example a WSL installation) is display-only.
    Token refresh always uses the native CLI because only it rotates the
    credentials file supplied to :class:`ClaudeProvider`.
    """

    def __init__(self, settings: Any) -> None:
        self.path = _discover_cli_path()
        self._commands = _setting(settings, "cli_command", {})
        if not isinstance(self._commands, Mapping):
            self._commands = {}
        self._version_cache: dict[Path, tuple[float, str]] = {}
        self._command_version_cache: dict[tuple[str, ...], str] = {}

    def native_version(self) -> str:
        return self.cli_version(self.path)

    def cli_version(self, path: Path) -> str:
        try:
            modified = path.stat().st_mtime
            cached = self._version_cache.get(path)
            if cached and cached[0] == modified:
                return cached[1]
            process = _run_cli([str(path), "--version"], timeout=10)
            version = _parse_version(process.stdout)
            self._version_cache[path] = (modified, version)
            return version
        except Exception:
            return ""

    def refresh_token(self) -> RefreshResult:
        if not self.path.is_file():
            return RefreshResult(False, False, "", "", "CLI not found")
        try:
            process = _run_cli([str(self.path), "update"], timeout=60)
        except subprocess.TimeoutExpired:
            return RefreshResult(False, False, "", "", "Timeout")
        except OSError as error:
            return RefreshResult(False, False, "", "", str(error))

        output = process.stdout + process.stderr
        updated = re.search(r"updated from (\S+) to (?:version )?(\S+)", output)
        if updated:
            return RefreshResult(True, True, updated.group(1), updated.group(2), "")
        current = re.search(r"up to date \((\S+)\)", output)
        if current:
            return RefreshResult(True, False, current.group(1), current.group(1), "")
        if process.returncode == 0:
            return RefreshResult(True, False, "", "", "")
        return RefreshResult(False, False, "", "", output.strip()[:200])

    def find_installations(self) -> list[ClaudeInstallation]:
        results: list[ClaudeInstallation] = []
        if self.path.is_file():
            version = self.cli_version(self.path)
            if version:
                results.append(ClaudeInstallation("CLI", version, self.path))

        for name, command in self._commands.items():
            if not isinstance(name, str) or not _valid_command(command):
                continue
            version = self._command_version(command)
            if version:
                results.append(ClaudeInstallation(name, version, Path(command[-1])))

        for ide_name, extension_dir in _extension_dirs():
            try:
                entries = extension_dir.iterdir() if extension_dir.is_dir() else ()
                best: tuple[tuple[int, ...], str, Path] | None = None
                for entry in entries:
                    if not entry.name.startswith(_EXTENSION_PREFIX):
                        continue
                    match = re.match(r"(\d+\.\d+\.\d+)", entry.name[len(_EXTENSION_PREFIX):])
                    if match:
                        version = match.group(1)
                        candidate = (tuple(int(part) for part in version.split(".")), version, entry)
                        if best is None or candidate[0] > best[0]:
                            best = candidate
                if best:
                    results.append(ClaudeInstallation(ide_name, best[1], best[2]))
            except OSError:
                continue
        return results

    def _command_version(self, command: list[str]) -> str:
        key = tuple(command)
        cached = self._command_version_cache.get(key)
        if cached is not None:
            return cached
        try:
            process = _run_cli([*command, "--version"], timeout=10)
            version = _parse_version(process.stdout)
            self._command_version_cache[key] = version
            return version
        except Exception:
            return ""


def _discover_cli_path() -> Path:
    found = shutil.which("claude")
    if found:
        path = Path(found)
        if path.suffix.lower() == ".ps1":
            for extension in (".cmd", ".exe"):
                alternative = path.with_suffix(extension)
                if alternative.is_file():
                    return alternative
        return path
    appdata = os.environ.get("APPDATA")
    if appdata:
        for name in ("claude.cmd", "claude.exe"):
            candidate = Path(appdata) / "npm" / name
            if candidate.is_file():
                return candidate
    return Path.home() / ".local" / "bin" / "claude.exe"


def _extension_dirs() -> list[tuple[str, Path]]:
    home = Path.home()
    return [
        ("VS Code", home / ".vscode" / "extensions"),
        ("VS Code Insiders", home / ".vscode-insiders" / "extensions"),
        ("Cursor", home / ".cursor" / "extensions"),
        ("Windsurf", home / ".windsurf" / "extensions"),
    ]


def _run_cli(command: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
    """Run the Node-based CLI with explicit, loss-tolerant UTF-8 decoding."""
    process = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        creationflags=_CREATE_NO_WINDOW,
    )
    if process.stdout is None or process.stderr is None:
        raise OSError("CLI output could not be captured")
    return process


def _parse_version(output: str) -> str:
    match = re.match(r"(\d+\.\d+\.\d+)", output.strip())
    return match.group(1) if match else ""


def _valid_command(value: Any) -> bool:
    return isinstance(value, list) and bool(value) and all(isinstance(part, str) and part for part in value)


def _setting(settings: Any, name: str, default: Any) -> Any:
    if isinstance(settings, Mapping):
        return settings.get(name, settings.get(name.upper(), default))
    return getattr(settings, name, getattr(settings, name.upper(), default))
