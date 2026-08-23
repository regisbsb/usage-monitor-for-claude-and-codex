"""
Codex CLI Tests
===============

Unit tests for _discover_cli_path(), find_installations(), and cli_version().
"""
from __future__ import annotations

import os
import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch

from usage_monitor.providers.codex import codex_cli
from usage_monitor.providers.codex.codex_cli import (
    CliUpdateResult,
    CodexInstallation,
    cli_version,
    find_installations,
    update_cli,
)


# ---------------------------------------------------------------------------
# _discover_cli_path
# ---------------------------------------------------------------------------

class TestDiscoverCliPath(unittest.TestCase):
    """Tests for _discover_cli_path()."""

    @patch('usage_monitor.providers.codex.codex_cli.shutil.which')
    def test_uses_which_when_found(self, mock_which):
        """shutil.which hit returns the discovered path directly."""
        with TemporaryDirectory() as tmp:
            fake = Path(tmp) / 'codex.cmd'
            fake.touch()
            mock_which.return_value = str(fake)
            self.assertEqual(codex_cli._discover_cli_path(), fake)

    @patch('usage_monitor.providers.codex.codex_cli.shutil.which')
    def test_substitutes_cmd_for_ps1(self, mock_which):
        """When which returns a .ps1 shim, sibling .cmd is preferred."""
        with TemporaryDirectory() as tmp:
            ps1 = Path(tmp) / 'codex.ps1'
            cmd = Path(tmp) / 'codex.cmd'
            ps1.touch()
            cmd.touch()
            mock_which.return_value = str(ps1)
            self.assertEqual(codex_cli._discover_cli_path(), cmd)

    @patch('usage_monitor.providers.codex.codex_cli.shutil.which')
    def test_substitutes_exe_for_ps1_when_no_cmd(self, mock_which):
        """When which returns .ps1 with no .cmd sibling, .exe is preferred."""
        with TemporaryDirectory() as tmp:
            ps1 = Path(tmp) / 'codex.ps1'
            exe = Path(tmp) / 'codex.exe'
            ps1.touch()
            exe.touch()
            mock_which.return_value = str(ps1)
            self.assertEqual(codex_cli._discover_cli_path(), exe)

    @patch('usage_monitor.providers.codex.codex_cli.shutil.which')
    def test_ps1_without_sibling_falls_through_to_installer(self, mock_which):
        with TemporaryDirectory() as tmp:
            ps1 = Path(tmp) / 'codex.ps1'
            installer = Path(tmp) / 'Programs' / 'OpenAI' / 'Codex' / 'bin' / 'codex.exe'
            installer.parent.mkdir(parents=True)
            installer.touch()
            ps1.touch()
            mock_which.return_value = str(ps1)
            with patch.dict(os.environ, {'LOCALAPPDATA': tmp, 'APPDATA': tmp}):
                self.assertEqual(codex_cli._discover_cli_path(), installer)

    @patch('usage_monitor.providers.codex.codex_cli.shutil.which', return_value=None)
    def test_falls_back_to_appdata_npm(self, _mock_which):
        """When which finds nothing, use the standard npm location."""
        with TemporaryDirectory() as tmp:
            npm_dir = Path(tmp) / 'npm'
            npm_dir.mkdir()
            cmd = npm_dir / 'codex.cmd'
            cmd.touch()
            with patch.dict(os.environ, {'LOCALAPPDATA': str(tmp), 'APPDATA': str(tmp)}):
                self.assertEqual(codex_cli._discover_cli_path(), cmd)

    @patch('usage_monitor.providers.codex.codex_cli.shutil.which', return_value=None)
    def test_appdata_npm_prefers_cmd_over_exe(self, _mock_which):
        """When both .cmd and .exe exist in npm dir, .cmd is preferred (typical npm shim)."""
        with TemporaryDirectory() as tmp:
            npm_dir = Path(tmp) / 'npm'
            npm_dir.mkdir()
            cmd = npm_dir / 'codex.cmd'
            exe = npm_dir / 'codex.exe'
            cmd.touch()
            exe.touch()
            with patch.dict(os.environ, {'LOCALAPPDATA': str(tmp), 'APPDATA': str(tmp)}):
                self.assertEqual(codex_cli._discover_cli_path(), cmd)

    @patch('usage_monitor.providers.codex.codex_cli.shutil.which', return_value=None)
    def test_last_resort_returns_default_when_nothing_found(self, _mock_which):
        """No CLI anywhere -> return the default path so callers fail gracefully."""
        with TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {'LOCALAPPDATA': str(tmp), 'APPDATA': str(tmp)}):
                result = codex_cli._discover_cli_path()
            self.assertEqual(result, Path(tmp) / 'Programs' / 'OpenAI' / 'Codex' / 'bin' / 'codex.exe')
            self.assertFalse(result.is_file())


# ---------------------------------------------------------------------------
# cli_version
# ---------------------------------------------------------------------------

class TestCliVersion(unittest.TestCase):
    """Tests for cli_version()."""

    def setUp(self):
        codex_cli._version_cache.clear()

    @patch('usage_monitor.providers.codex.codex_cli.subprocess.run')
    @patch('pathlib.Path.stat', return_value=MagicMock(st_mtime=1000.0))
    def test_parses_version_string(self, _mock_stat, mock_run):
        """Extracts the version from the verified Codex CLI format."""
        mock_run.return_value = MagicMock(stdout='codex-cli 0.140.0\n', returncode=0)
        self.assertEqual(cli_version(Path('/fake/codex.exe')), '0.140.0')

    @patch('usage_monitor.providers.codex.codex_cli.subprocess.run')
    @patch('pathlib.Path.stat', return_value=MagicMock(st_mtime=1000.0))
    def test_version_only(self, _mock_stat, mock_run):
        """Handles bare version string without suffix."""
        mock_run.return_value = MagicMock(stdout='3.0.0\n', returncode=0)
        self.assertEqual(cli_version(Path('/fake/codex.exe')), '3.0.0')

    @patch('usage_monitor.providers.codex.codex_cli.subprocess.run')
    @patch('pathlib.Path.stat', return_value=MagicMock(st_mtime=1000.0))
    def test_empty_output(self, _mock_stat, mock_run):
        """Returns empty string when output is empty."""
        mock_run.return_value = MagicMock(stdout='', returncode=0)
        self.assertEqual(cli_version(Path('/fake/codex.exe')), '')

    @patch('usage_monitor.providers.codex.codex_cli.subprocess.run')
    @patch('pathlib.Path.stat', return_value=MagicMock(st_mtime=1000.0))
    def test_non_version_output(self, _mock_stat, mock_run):
        """Returns empty string for non-version output."""
        mock_run.return_value = MagicMock(stdout='error: something wrong', returncode=1)
        self.assertEqual(cli_version(Path('/fake/codex.exe')), '')

    @patch('usage_monitor.providers.codex.codex_cli.subprocess.run')
    @patch('pathlib.Path.stat', return_value=MagicMock(st_mtime=1000.0))
    def test_timeout_returns_empty(self, _mock_stat, mock_run):
        """Returns empty string on timeout."""
        mock_run.side_effect = subprocess.TimeoutExpired(cmd='codex', timeout=10)
        self.assertEqual(cli_version(Path('/fake/codex.exe')), '')

    @patch('usage_monitor.providers.codex.codex_cli.subprocess.run')
    @patch('pathlib.Path.stat', return_value=MagicMock(st_mtime=1000.0))
    def test_os_error_returns_empty(self, _mock_stat, mock_run):
        """Returns empty string on OSError (binary not found)."""
        mock_run.side_effect = OSError('not found')
        self.assertEqual(cli_version(Path('/fake/codex.exe')), '')

    @patch('usage_monitor.providers.codex.codex_cli.subprocess.run')
    @patch('pathlib.Path.stat', return_value=MagicMock(st_mtime=1000.0))
    def test_passes_correct_args(self, _mock_stat, mock_run):
        """Calls subprocess with correct arguments."""
        mock_run.return_value = MagicMock(stdout='2.1.69\n', returncode=0)
        path = Path('/fake/codex.exe')
        cli_version(path)
        mock_run.assert_called_once_with(
            [str(path), '--version'],
            capture_output=True, text=True, timeout=10, creationflags=subprocess.CREATE_NO_WINDOW,
        )

    @patch('usage_monitor.providers.codex.codex_cli.subprocess.run')
    @patch('pathlib.Path.stat', return_value=MagicMock(st_mtime=1000.0))
    def test_cache_hit_skips_subprocess(self, _mock_stat, mock_run):
        """Second call with same mtime returns cached version without subprocess."""
        mock_run.return_value = MagicMock(stdout='2.1.69\n', returncode=0)
        path = Path('/fake/codex.exe')
        self.assertEqual(cli_version(path), '2.1.69')
        self.assertEqual(cli_version(path), '2.1.69')
        mock_run.assert_called_once()

    @patch('usage_monitor.providers.codex.codex_cli.subprocess.run')
    def test_cache_invalidated_on_mtime_change(self, mock_run):
        """Changed mtime triggers a new subprocess call."""
        mock_run.return_value = MagicMock(stdout='2.1.69\n', returncode=0)
        path = Path('/fake/codex.exe')
        with patch('pathlib.Path.stat', return_value=MagicMock(st_mtime=1000.0)):
            self.assertEqual(cli_version(path), '2.1.69')
        mock_run.return_value = MagicMock(stdout='3.0.0\n', returncode=0)
        with patch('pathlib.Path.stat', return_value=MagicMock(st_mtime=2000.0)):
            self.assertEqual(cli_version(path), '3.0.0')
        self.assertEqual(mock_run.call_count, 2)

    def test_stat_failure_returns_empty(self):
        """Returns empty string when stat() fails (file deleted)."""
        with patch('pathlib.Path.stat', side_effect=OSError('not found')):
            self.assertEqual(cli_version(Path('/fake/codex.exe')), '')


class TestUpdateCli(unittest.TestCase):
    def test_missing_cli(self):
        with TemporaryDirectory() as tmp, \
             patch.object(codex_cli, 'CODEX_CLI_PATH', Path(tmp) / 'missing.exe'):
            self.assertEqual(
                update_cli(),
                CliUpdateResult(False, False, '', '', 'CLI not found'),
            )

    @patch('usage_monitor.providers.codex.codex_cli.subprocess.run')
    @patch('usage_monitor.providers.codex.codex_cli.cli_version', side_effect=['0.140.0', '0.144.5'])
    def test_successful_update_detects_version_change(self, _version, run):
        run.return_value = MagicMock(returncode=0, stdout='updated', stderr='')
        with TemporaryDirectory() as tmp:
            cli = Path(tmp) / 'codex.exe'
            cli.touch()
            with patch.object(codex_cli, 'CODEX_CLI_PATH', cli):
                result = update_cli()

        self.assertEqual(result, CliUpdateResult(True, True, '0.140.0', '0.144.5', ''))
        run.assert_called_once_with(
            [str(cli), 'update'], capture_output=True, text=True, timeout=120,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )

    @patch('usage_monitor.providers.codex.codex_cli.subprocess.run')
    @patch('usage_monitor.providers.codex.codex_cli.cli_version', side_effect=['0.144.5', '0.144.5'])
    def test_up_to_date_is_success_without_update(self, _version, run):
        run.return_value = MagicMock(returncode=0, stdout='already current', stderr='')
        with TemporaryDirectory() as tmp:
            cli = Path(tmp) / 'codex.exe'
            cli.touch()
            with patch.object(codex_cli, 'CODEX_CLI_PATH', cli):
                result = update_cli()
        self.assertEqual(result, CliUpdateResult(True, False, '0.144.5', '0.144.5', ''))

    @patch('usage_monitor.providers.codex.codex_cli.subprocess.run', side_effect=subprocess.TimeoutExpired('codex update', 120))
    @patch('usage_monitor.providers.codex.codex_cli.cli_version', return_value='0.140.0')
    def test_timeout(self, _version, _run):
        with TemporaryDirectory() as tmp:
            cli = Path(tmp) / 'codex.exe'
            cli.touch()
            with patch.object(codex_cli, 'CODEX_CLI_PATH', cli):
                result = update_cli()
        self.assertEqual(result, CliUpdateResult(False, False, '0.140.0', '0.140.0', 'Timeout'))

    @patch('usage_monitor.providers.codex.codex_cli.subprocess.run')
    @patch('usage_monitor.providers.codex.codex_cli.cli_version', return_value='0.140.0')
    def test_nonzero_exit_is_sanitized(self, _version, run):
        run.return_value = MagicMock(returncode=7, stdout='private output', stderr='secret detail')
        with TemporaryDirectory() as tmp:
            cli = Path(tmp) / 'codex.exe'
            cli.touch()
            with patch.object(codex_cli, 'CODEX_CLI_PATH', cli):
                result = update_cli()
        self.assertEqual(result.error, 'codex update exited with code 7')
        self.assertNotIn('private', result.error)
        self.assertNotIn('secret', result.error)


# ---------------------------------------------------------------------------
# find_installations
# ---------------------------------------------------------------------------

class TestFindInstallations(unittest.TestCase):
    """Tests for find_installations()."""

    @patch('usage_monitor.providers.codex.codex_cli.cli_version', return_value='')
    @patch('usage_monitor.providers.codex.codex_cli.CODEX_CLI_PATH')
    @patch('usage_monitor.providers.codex.codex_cli._EXTENSION_DIRS', [])
    def test_no_installations_found(self, mock_cli_path, _mock_version):
        """Returns empty list when nothing is installed."""
        mock_cli_path.is_file.return_value = False
        result = find_installations()
        self.assertEqual(result, [])

    @patch('usage_monitor.providers.codex.codex_cli.cli_version', return_value='2.1.69')
    @patch('usage_monitor.providers.codex.codex_cli.CODEX_CLI_PATH')
    @patch('usage_monitor.providers.codex.codex_cli._EXTENSION_DIRS', [])
    def test_cli_only(self, mock_cli_path, _mock_version):
        """Returns CLI installation when binary exists."""
        mock_cli_path.is_file.return_value = True
        result = find_installations()
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].name, 'CLI')
        self.assertEqual(result[0].version, '2.1.69')

    @patch('usage_monitor.providers.codex.codex_cli.cli_version', return_value='')
    @patch('usage_monitor.providers.codex.codex_cli.CODEX_CLI_PATH')
    @patch('usage_monitor.providers.codex.codex_cli._EXTENSION_DIRS', [])
    def test_cli_exists_but_version_fails(self, mock_cli_path, _mock_version):
        """CLI binary exists but version command fails - not included."""
        mock_cli_path.is_file.return_value = True
        result = find_installations()
        self.assertEqual(result, [])

    @patch('usage_monitor.providers.codex.codex_cli.cli_version', return_value='')
    @patch('usage_monitor.providers.codex.codex_cli.CODEX_CLI_PATH')
    def test_vscode_extension(self, mock_cli_path, _mock_version):
        """Finds VS Code extension and extracts version from directory name."""
        mock_cli_path.is_file.return_value = False
        with TemporaryDirectory() as tmp:
            ext_dir = Path(tmp)
            (ext_dir / 'openai.chatgpt-2.1.69-win32-x64').mkdir()
            with patch('usage_monitor.providers.codex.codex_cli._EXTENSION_DIRS', [('VS Code', ext_dir)]):
                result = find_installations()
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].name, 'VS Code')
        self.assertEqual(result[0].version, '2.1.69')

    @patch('usage_monitor.providers.codex.codex_cli.cli_version', return_value='')
    @patch('usage_monitor.providers.codex.codex_cli.CODEX_CLI_PATH')
    def test_unreadable_extension_dir_skipped(self, mock_cli_path, _mock_version):
        """An unreadable extension directory must not break popup discovery."""
        mock_cli_path.is_file.return_value = False
        denied_dir = MagicMock()
        denied_dir.is_dir.return_value = True
        denied_dir.iterdir.side_effect = PermissionError(13, 'Access is denied')

        with TemporaryDirectory() as tmp:
            ext_dir = Path(tmp)
            (ext_dir / 'openai.chatgpt-2.1.69-win32-x64').mkdir()
            with patch('usage_monitor.providers.codex.codex_cli._EXTENSION_DIRS', [('VS Code', denied_dir), ('Cursor', ext_dir)]):
                result = find_installations()

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].name, 'Cursor')

    @patch('usage_monitor.providers.codex.codex_cli.cli_version', return_value='')
    @patch('usage_monitor.providers.codex.codex_cli.CODEX_CLI_PATH')
    def test_picks_highest_version(self, mock_cli_path, _mock_version):
        """When multiple extension versions exist, picks the highest."""
        mock_cli_path.is_file.return_value = False
        with TemporaryDirectory() as tmp:
            ext_dir = Path(tmp)
            (ext_dir / 'openai.chatgpt-2.1.63-win32-x64').mkdir()
            (ext_dir / 'openai.chatgpt-2.1.69-win32-x64').mkdir()
            (ext_dir / 'openai.chatgpt-2.1.66-win32-x64').mkdir()
            with patch('usage_monitor.providers.codex.codex_cli._EXTENSION_DIRS', [('VS Code', ext_dir)]):
                result = find_installations()
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].version, '2.1.69')

    @patch('usage_monitor.providers.codex.codex_cli.cli_version', return_value='')
    @patch('usage_monitor.providers.codex.codex_cli.CODEX_CLI_PATH')
    def test_ignores_non_codex_extensions(self, mock_cli_path, _mock_version):
        """Ignore directories that do not match the Codex extension prefix."""
        mock_cli_path.is_file.return_value = False
        with TemporaryDirectory() as tmp:
            ext_dir = Path(tmp)
            (ext_dir / 'some-other-extension-1.0.0').mkdir()
            (ext_dir / 'openai.chatgpt-2.1.69-win32-x64').mkdir()
            with patch('usage_monitor.providers.codex.codex_cli._EXTENSION_DIRS', [('VS Code', ext_dir)]):
                result = find_installations()
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].version, '2.1.69')

    @patch('usage_monitor.providers.codex.codex_cli.cli_version', return_value='')
    @patch('usage_monitor.providers.codex.codex_cli.CODEX_CLI_PATH')
    def test_matching_regular_file_is_not_an_installation(self, mock_cli_path, _mock_version):
        mock_cli_path.is_file.return_value = False
        with TemporaryDirectory() as tmp:
            extension_directory = Path(tmp)
            (extension_directory / 'openai.chatgpt-26.707.71524-win32-x64').touch()
            with patch('usage_monitor.providers.codex.codex_cli._EXTENSION_DIRS', [('VS Code', extension_directory)]):
                result = find_installations()
        self.assertEqual(result, [])

    @patch('usage_monitor.providers.codex.codex_cli.cli_version', return_value='')
    @patch('usage_monitor.providers.codex.codex_cli.CODEX_CLI_PATH')
    def test_nonexistent_extension_dir_skipped(self, mock_cli_path, _mock_version):
        """Extension directories that don't exist are silently skipped."""
        mock_cli_path.is_file.return_value = False
        with patch('usage_monitor.providers.codex.codex_cli._EXTENSION_DIRS', [('VS Code', Path('/nonexistent'))]):
            result = find_installations()
        self.assertEqual(result, [])

    @patch('usage_monitor.providers.codex.codex_cli.cli_version', return_value='2.1.69')
    @patch('usage_monitor.providers.codex.codex_cli.CODEX_CLI_PATH')
    def test_cli_and_extensions_combined(self, mock_cli_path, _mock_version):
        """Returns both CLI and extension installations."""
        mock_cli_path.is_file.return_value = True
        with TemporaryDirectory() as tmp:
            ext_dir = Path(tmp)
            (ext_dir / 'openai.chatgpt-2.1.68-win32-x64').mkdir()
            with patch('usage_monitor.providers.codex.codex_cli._EXTENSION_DIRS', [('VS Code', ext_dir)]):
                result = find_installations()
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0].name, 'CLI')
        self.assertEqual(result[1].name, 'VS Code')


