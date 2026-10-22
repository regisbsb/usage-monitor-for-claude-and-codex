"""
Notification Identity
=====================

Registers a fixed toast-notification identity (name and logo) for the process.

Windows shows the process's app icon in the header of a tray notification.
Without an explicit identity that icon is the live tray icon, which reflects
the most-exhausted quota - so a "quota reset" or "50% used" toast would carry
the exhausted glyph and contradict its own text.  WinRT toasts explicitly name the combined ``AppUserModelID`` and neutral
logo. Tray balloons remain the fallback when registration or delivery fails.
"""
from __future__ import annotations

import ctypes
import html
import logging
import winreg
from pathlib import Path
from typing import Any

__all__ = ['register_notification_identity', 'show_notification']

log = logging.getLogger(__name__)
_WINRT_TYPE_QUALIFIER = ', Windows, ContentType=WindowsRuntime'
_TOAST_LIFETIME_SECONDS = 300

# Both provider monitors share one product identity and neutral logo.
APP_USER_MODEL_ID = 'UsageMonitorForClaudeAndCodex'
DISPLAY_NAME = 'Usage Monitor for Claude and Codex'

# Neutral branded logo (empty usage bars) shown as the notification icon.
# A multi-size .ico (16-256 px) so Windows picks a crisp frame for the small
# toast header instead of downscaling a single large image.
_NOTIFICATION_LOGO = Path(__file__).resolve().parent / 'notification_logo.ico'

# HKCU key the shell reads to resolve the identity's display name and icon.
# A registry entry is enough - no Start Menu shortcut is required.
_REG_PATH = r'Software\Classes\AppUserModelId\{}'.format(APP_USER_MODEL_ID)


def register_notification_identity() -> bool:
    """Adopt a fixed notification identity for this process.

    Writes the ``DisplayName`` and ``IconUri`` registration to ``HKCU`` and,
    only if that succeeds, sets the process ``AppUserModelID`` so toasts use
    the registered name and logo.  Re-run on every startup because a frozen
    build extracts the logo to a fresh temporary directory each run, changing
    its path.

    On any failure - a missing logo file, a registry write error or a
    rejected ``AppUserModelID`` - the process keeps its default identity.
    This is never fatal: a notification icon must not stop the app from
    starting.

    Returns
    -------
    bool
        True when the identity is registered and adopted, which is what
        :func:`show_notification` needs before it may post a toast under it.
    """
    if not _NOTIFICATION_LOGO.is_file():
        return False

    try:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, _REG_PATH) as key:
            winreg.SetValueEx(key, 'DisplayName', 0, winreg.REG_SZ, DISPLAY_NAME)
            winreg.SetValueEx(key, 'IconUri', 0, winreg.REG_EXPAND_SZ, str(_NOTIFICATION_LOGO))
    except OSError:
        return False

    hresult = ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(ctypes.c_wchar_p(APP_USER_MODEL_ID))

    return hresult == 0


def show_notification(icon: Any, message: str, title: str, identity_registered: bool) -> None:
    """Show a notification under the app's own identity.

    A tray balloon (``icon.notify()``) is not reliably attributed to the
    process ``AppUserModelID``: on some Windows builds its header shows the
    live tray icon instead of the registered logo, and the tray icon reflects
    the most-exhausted quota.  A toast posted through the Windows Runtime
    names the identity explicitly, so its header always shows the registered
    name and logo.

    The balloon stays the fallback: without a registered identity a toast
    could be dropped without an error, and a toast that fails is logged without its content and
    then shown as a balloon so the message is never lost.

    Parameters
    ----------
    icon : pystray.Icon
        The tray icon, used for the balloon fallback.
    message : str
        Notification body.
    title : str
        Notification title.
    identity_registered : bool
        Result of :func:`register_notification_identity`.
    """
    if not identity_registered:
        icon.notify(message, title)
        return

    try:
        _show_toast(message, title)
    except Exception:
        log.warning('Windows toast failed; using tray balloon')
        icon.notify(message, title)


def _show_toast(message: str, title: str) -> None:
    """Post a text-only toast that expires after ``_TOAST_LIFETIME_SECONDS``.

    Runs through pythonnet's .NET Framework runtime, which pywebview's
    WinForms host already loads, so no Windows Runtime binding package is
    needed.
    """
    import clr  # type: ignore[import-untyped]  # .NET bridge via pythonnet

    clr.AddReference('System.Runtime.WindowsRuntime')
    from System import Activator, DateTimeOffset, TimeSpan  # type: ignore[import-untyped]  # .NET import via pythonnet

    document = Activator.CreateInstance(_winrt_type('Windows.Data.Xml.Dom.XmlDocument'))
    document.LoadXml(_toast_xml(message, title))

    toast = Activator.CreateInstance(_winrt_type('Windows.UI.Notifications.ToastNotification'), document)
    toast.ExpirationTime = DateTimeOffset.Now.Add(TimeSpan.FromSeconds(_TOAST_LIFETIME_SECONDS))

    create_notifier = _winrt_type('Windows.UI.Notifications.ToastNotificationManager').GetMethod('CreateToastNotifier', [clr.GetClrType(str)])
    create_notifier.Invoke(None, [APP_USER_MODEL_ID]).Show(toast)


def _winrt_type(name: str) -> Any:
    """Resolve a Windows Runtime type by its full name, raising when it is unavailable."""
    from System import Type  # type: ignore[import-untyped]  # .NET import via pythonnet

    resolved = Type.GetType(name + _WINRT_TYPE_QUALIFIER)
    if resolved is None:
        raise RuntimeError(f'Windows Runtime type not available: {name}')

    return resolved


def _toast_xml(message: str, title: str) -> str:
    """Build the toast payload with title and message escaped as XML text."""
    return (
        '<toast><visual><binding template="ToastGeneric">'
        f'<text>{html.escape(title)}</text>'
        f'<text>{html.escape(message)}</text>'
        '</binding></visual></toast>'
    )
