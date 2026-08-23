"""Entry point for ``python -m usage_monitor``."""
from __future__ import annotations

import ctypes
import os
import subprocess
import sys
import traceback
from pathlib import Path

from usage_monitor.instance_id import parse_claude_config_dir, parse_codex_home


def _selected_directory(value: str | None, default: Path, flag: str) -> Path:
    """Resolve a provider directory or terminate with a visible error."""
    selected = Path(value).resolve() if value is not None else default.resolve()
    if selected.is_dir():
        return selected
    ctypes.windll.user32.MessageBoxW(
        0,
        f'{flag} directory does not exist:\n{selected}',
        'Usage Monitor for Claude and Codex - Error',
        0x10,
    )
    raise SystemExit(1)


def _restart_process(claude_dir: Path, codex_home: Path, verbose: bool) -> None:
    """Start one replacement process while preserving selected provider homes."""
    args = [
        f'--claude-config-dir={claude_dir}',
        f'--codex-home={codex_home}',
    ]
    if verbose:
        args.append('--verbose')

    if getattr(sys, 'frozen', False):
        env = {key: value for key, value in os.environ.items() if not key.startswith(('_PYI_', '_MEI'))}
        command = [sys.executable, *args]
    else:
        env = os.environ.copy()
        command = [sys.executable, '-m', 'usage_monitor', *args]
    subprocess.Popen(command, env=env, creationflags=subprocess.CREATE_NO_WINDOW)


def main() -> int:
    """Run the dual-provider monitor and return its process exit code."""
    claude_value = parse_claude_config_dir(sys.argv)
    codex_value = parse_codex_home(sys.argv)
    claude_dir = _selected_directory(claude_value, Path.home() / '.claude', '--claude-config-dir')
    codex_home = _selected_directory(codex_value, Path.home() / '.codex', '--codex-home')
    os.environ['CLAUDE_CONFIG_DIR'] = str(claude_dir)
    os.environ['CODEX_HOME'] = str(codex_home)

    verbose = '--verbose' in sys.argv
    if verbose:
        from usage_monitor.verbose import print_startup_diagnostics, setup_console
        if getattr(sys, 'frozen', False):
            setup_console()
        print_startup_diagnostics()

    from usage_monitor.dpi import set_process_dpi_awareness
    set_process_dpi_awareness()

    from usage_monitor.logging_setup import configure_logging
    from usage_monitor.settings import LOG_BACKUP_COUNT, LOG_MAX_BYTES
    try:
        configure_logging(verbose=verbose, max_bytes=LOG_MAX_BYTES, backup_count=LOG_BACKUP_COUNT)
    except OSError as exc:
        ctypes.windll.user32.MessageBoxW(
            0,
            f'Cannot create the application log next to the executable:\n{exc}',
            'Usage Monitor for Claude and Codex - Logging Error',
            0x10,
        )
        return 1

    import webview  # type: ignore[import-untyped]  # no type stubs available

    from usage_monitor.application import AppSupervisor
    from usage_monitor.monitor import crash_log
    from usage_monitor.notification_identity import register_notification_identity
    from usage_monitor.providers import ClaudeProvider, CodexProvider
    from usage_monitor.settings import get_provider_settings
    from usage_monitor.single_instance import ensure_single_instance, release_instance_lock

    if not ensure_single_instance():
        return 0
    register_notification_identity()

    claude_settings = get_provider_settings('claude')
    codex_settings = get_provider_settings('codex')
    supervisor = AppSupervisor([
        (ClaudeProvider(claude_dir, claude_settings), claude_settings),
        (CodexProvider(codex_home, codex_settings), codex_settings),
    ])

    def run_supervisor() -> None:
        try:
            if verbose:
                from usage_monitor.verbose import print_runtime_diagnostics
                print_runtime_diagnostics()
            supervisor.run()
        except Exception:
            crash_log(traceback.format_exc())
        finally:
            for window in list(webview.windows):
                try:
                    window.destroy()
                except Exception:
                    pass

    try:
        webview.create_window('', html='', hidden=True)
        webview.start(func=run_supervisor)
        if supervisor.restart_requested:
            release_instance_lock()
            _restart_process(claude_dir, codex_home, verbose)
        return 0
    except Exception:
        crash_log(traceback.format_exc())
        return 1
    finally:
        supervisor.stop()
        release_instance_lock()


if __name__ == '__main__':
    raise SystemExit(main())
