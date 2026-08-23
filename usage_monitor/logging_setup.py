"""Always-on rotating application logging."""
from __future__ import annotations

import logging
import re
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from .instance_id import combined_instance_suffix

__all__ = ['LOG_FILENAME', 'application_directory', 'application_log_filename', 'configure_logging']

LOG_FILENAME = 'usage-monitor-for-claude-and-codex.log'
_HANDLER_MARKER = '_usage_monitor_handler'


def _redact_home_paths(text: str) -> str:
    home = str(Path.home())
    variants = {home, home.replace('\\', '/'), home.replace('\\', '\\\\')}
    for variant in sorted(variants, key=len, reverse=True):
        if variant:
            text = re.sub(re.escape(variant), '~', text, flags=re.IGNORECASE)
    return text


class _RedactingFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return _redact_home_paths(super().format(record))


def application_directory() -> Path:
    """Return the directory containing the EXE, or the project root in source mode."""
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def application_log_filename() -> str:
    """Return a collision-free log filename for the effective Codex home."""
    suffix = combined_instance_suffix()
    return f'usage-monitor-for-claude-and-codex{suffix}.log' if suffix else LOG_FILENAME


def _remove_owned_handlers(root: logging.Logger) -> None:
    for handler in list(root.handlers):
        if getattr(handler, _HANDLER_MARKER, False):
            root.removeHandler(handler)
            handler.close()


def configure_logging(
    *,
    verbose: bool,
    max_bytes: int,
    backup_count: int,
    path: Path | None = None,
    disable: bool = False,
) -> Path:
    """Configure the root logger with a rotating file and optional console output.

    The file is opened immediately so startup fails visibly if the executable
    directory is not writable. Repeated calls replace only handlers installed
    by this module, leaving handlers owned by embedding applications untouched.
    """
    log_path = Path(path) if path is not None else application_directory() / application_log_filename()
    root = logging.getLogger()
    _remove_owned_handlers(root)
    if disable:
        return log_path

    formatter = _RedactingFormatter(
        '%(asctime)s %(levelname)-5s %(name)s: %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
    )
    file_handler = RotatingFileHandler(
        log_path,
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding='utf-8',
        delay=False,
    )
    setattr(file_handler, _HANDLER_MARKER, True)
    file_handler.setFormatter(formatter)
    file_handler.setLevel(logging.INFO)
    root.addHandler(file_handler)

    if verbose:
        console_handler = logging.StreamHandler()
        setattr(console_handler, _HANDLER_MARKER, True)
        console_handler.setFormatter(formatter)
        console_handler.setLevel(logging.INFO)
        root.addHandler(console_handler)

    root.setLevel(logging.INFO)
    root.info(
        'application log started (file=%s, max_bytes=%s, backups=%s)',
        log_path.name,
        max_bytes,
        backup_count,
    )
    return log_path
