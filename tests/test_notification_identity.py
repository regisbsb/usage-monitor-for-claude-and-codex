"""
Notification Identity Tests
===========================

Unit tests for the toast-notification identity registration.
"""
from __future__ import annotations

import sys
import unittest
from unittest.mock import MagicMock, patch

import usage_monitor.notification_identity as ni


class TestRegisterNotificationIdentity(unittest.TestCase):
    """Tests for register_notification_identity()."""

    @patch.object(ni, 'ctypes')
    @patch.object(ni, 'winreg')
    def test_registers_name_icon_and_sets_aumid(self, mock_winreg, mock_ctypes):
        """A present logo writes DisplayName + IconUri (the logo path) and then adopts the AUMID."""
        mock_ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID.return_value = 0
        logo = MagicMock()
        logo.is_file.return_value = True
        logo.__str__.return_value = r'C:\fake\notification_logo.ico'

        with patch.object(ni, '_NOTIFICATION_LOGO', logo):
            registered = ni.register_notification_identity()

        self.assertIs(registered, True)
        mock_winreg.CreateKey.assert_called_once_with(mock_winreg.HKEY_CURRENT_USER, ni._REG_PATH)
        writes = {c.args[1]: c.args[4] for c in mock_winreg.SetValueEx.call_args_list}
        self.assertEqual(list(writes), ['DisplayName', 'IconUri'])
        self.assertEqual(writes['IconUri'], r'C:\fake\notification_logo.ico')
        mock_ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID.assert_called_once()

    @patch.object(ni, 'ctypes')
    @patch.object(ni, 'winreg')
    def test_writes_configured_display_name(self, mock_winreg, mock_ctypes):
        """DisplayName is written with the module's brand name."""
        mock_ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID.return_value = 0
        logo = MagicMock()
        logo.is_file.return_value = True

        with patch.object(ni, '_NOTIFICATION_LOGO', logo):
            registered = ni.register_notification_identity()

        display_call = next(c for c in mock_winreg.SetValueEx.call_args_list if c.args[1] == 'DisplayName')
        self.assertEqual(display_call.args[4], ni.DISPLAY_NAME)

    @patch.object(ni, 'ctypes')
    @patch.object(ni, 'winreg')
    def test_skips_everything_when_logo_missing(self, mock_winreg, mock_ctypes):
        """A missing logo leaves the default identity (tray icon) untouched."""
        mock_ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID.return_value = 0
        logo = MagicMock()
        logo.is_file.return_value = False

        with patch.object(ni, '_NOTIFICATION_LOGO', logo):
            registered = ni.register_notification_identity()

        self.assertIs(registered, False)
        mock_winreg.CreateKey.assert_not_called()
        mock_ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID.assert_not_called()

    @patch.object(ni, 'ctypes')
    @patch.object(ni, 'winreg')
    def test_does_not_adopt_aumid_when_registry_fails(self, mock_winreg, mock_ctypes):
        """A registry write failure keeps the tray icon rather than an empty one."""
        mock_winreg.CreateKey.side_effect = OSError('access denied')
        mock_ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID.return_value = 0
        logo = MagicMock()
        logo.is_file.return_value = True

        with patch.object(ni, '_NOTIFICATION_LOGO', logo):
            registered = ni.register_notification_identity()

        self.assertIs(registered, False)
        mock_ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID.assert_not_called()

    @patch.object(ni, 'ctypes')
    @patch.object(ni, 'winreg')
    def test_rejected_aumid_disables_toasts(self, mock_winreg, mock_ctypes):
        mock_ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID.return_value = -1
        with patch.object(ni, '_NOTIFICATION_LOGO') as logo:
            logo.is_file.return_value = True
            self.assertIs(ni.register_notification_identity(), False)

    def test_registry_path_matches_aumid(self):
        """The registry path targets the same AUMID the process adopts."""
        self.assertTrue(ni._REG_PATH.endswith(ni.APP_USER_MODEL_ID))
        self.assertIn(r'Software\Classes\AppUserModelId', ni._REG_PATH)


class TestShowNotification(unittest.TestCase):
    """Tests for show_notification(): toast under the identity, balloon as fallback."""

    def test_uses_balloon_without_identity(self):
        """Without a registered identity a toast could be dropped silently, so the balloon is used."""
        icon = MagicMock()

        with patch.object(ni, '_show_toast') as mock_toast:
            ni.show_notification(icon, 'message', 'title', identity_registered=False)

        mock_toast.assert_not_called()
        icon.notify.assert_called_once_with('message', 'title')

    def test_posts_toast_with_identity(self):
        """With a registered identity the toast replaces the balloon."""
        icon = MagicMock()

        with patch.object(ni, '_show_toast') as mock_toast:
            ni.show_notification(icon, 'message', 'title', identity_registered=True)

        mock_toast.assert_called_once_with('message', 'title')
        icon.notify.assert_not_called()

    def test_failed_toast_is_reported_and_falls_back(self):
        """Toast failures log no exception or notification content and fall back to a balloon."""
        icon = MagicMock()

        with patch.object(ni, '_show_toast', side_effect=OSError('sensitive exception text')), \
             patch.object(ni.log, 'warning') as mock_warning:
            ni.show_notification(icon, 'message', 'title', identity_registered=True)

        mock_warning.assert_called_once_with('Windows toast failed; using tray balloon')
        icon.notify.assert_called_once_with('message', 'title')


class TestShowToast(unittest.TestCase):
    """Tests for _show_toast() with the .NET bridge stubbed out.

    ``clr`` and ``System`` are replaced through ``sys.modules`` so the tests
    exercise the call sequence without loading a .NET runtime.
    """

    def setUp(self):
        self.clr = MagicMock()
        self.system = MagicMock()
        self.winrt_types = {}

        def get_type(qualified_name):
            return self.winrt_types.setdefault(qualified_name, MagicMock(name=qualified_name))

        self.system.Type.GetType.side_effect = get_type
        self.document = MagicMock(name='document')
        self.toast = MagicMock(name='toast')
        self.system.Activator.CreateInstance.side_effect = lambda winrt_type, *args: self.toast if args else self.document

        modules = patch.dict(sys.modules, {'clr': self.clr, 'System': self.system})
        modules.start()
        self.addCleanup(modules.stop)

    def _winrt(self, name):
        return self.winrt_types[name + ni._WINRT_TYPE_QUALIFIER]

    def test_posts_escaped_toast_under_app_identity(self):
        """The payload is escaped XML, and the notifier is created for the app's AUMID."""
        ni._show_toast('usage <100%> & more', 'Title "quoted"')

        payload = self.document.LoadXml.call_args.args[0]
        self.assertIn('<text>Title &quot;quoted&quot;</text>', payload)
        self.assertIn('<text>usage &lt;100%&gt; &amp; more</text>', payload)

        create_notifier = self._winrt('Windows.UI.Notifications.ToastNotificationManager').GetMethod.return_value
        create_notifier.Invoke.assert_called_once_with(None, [ni.APP_USER_MODEL_ID])
        create_notifier.Invoke.return_value.Show.assert_called_once_with(self.toast)

    def test_toast_expires(self):
        """A stored toast pins the resolved IconUri, so every toast must carry an expiration time."""
        ni._show_toast('message', 'title')

        self.system.TimeSpan.FromSeconds.assert_called_once_with(ni._TOAST_LIFETIME_SECONDS)
        self.system.DateTimeOffset.Now.Add.assert_called_once_with(self.system.TimeSpan.FromSeconds.return_value)
        self.assertIs(self.toast.ExpirationTime, self.system.DateTimeOffset.Now.Add.return_value)

    def test_lifetime_is_bounded(self):
        """The lifetime is the window in which a restart can leave a toast without its icon."""
        self.assertGreater(ni._TOAST_LIFETIME_SECONDS, 0)
        self.assertLessEqual(ni._TOAST_LIFETIME_SECONDS, 600)

    def test_missing_runtime_type_raises(self):
        """An unresolvable type raises, which show_notification turns into the balloon fallback."""
        self.system.Type.GetType.side_effect = None
        self.system.Type.GetType.return_value = None

        with self.assertRaises(RuntimeError):
            ni._show_toast('message', 'title')


if __name__ == '__main__':
    unittest.main()
