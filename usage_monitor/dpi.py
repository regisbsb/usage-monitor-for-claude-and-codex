"""
DPI Awareness
=============

Configures process DPI awareness before pywebview initializes.
"""
from __future__ import annotations

import ctypes

__all__ = ['set_process_dpi_awareness']


def set_process_dpi_awareness() -> None:
    """Request Per-Monitor V2 awareness when the Windows API is available."""
    try:
        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_ssize_t(-4))
    except AttributeError:
        pass
