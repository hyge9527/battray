import queue
import unittest
from unittest.mock import Mock, patch

from keyboard_power.tray import Tray, icon_pixels, TRAY_BUS_NAME


class TrayTests(unittest.TestCase):
    def test_stale_value_keeps_digits_in_grey_rather_than_question_mark(self):
        fresh = icon_pixels(39, 32)
        stale = icon_pixels(39, 32, stale=True)
        unknown = icon_pixels(None, 32)
        self.assertEqual(fresh[::4], stale[::4])
        self.assertNotEqual(stale[::4], unknown[::4])
        self.assertEqual(set(tuple(stale[i+1:i+4]) for i in range(0, len(stale), 4) if stale[i]), {(160, 174, 192)})

    def test_property_keeps_stale_zero_and_tooltip_explains_history(self):
        tray = Mock()
        tray.data = dict(device='test', percent=0, status='stale', updated_at=100, reason='sleeping')
        with patch('keyboard_power.tray.icon_pixels', return_value=b'') as pixels:
            Tray._property(tray, None, None, None, b'org.kde.StatusNotifierItem', b'IconPixmap', None, None)
        self.assertEqual([c.kwargs for c in pixels.call_args_list], [{'stale': True}, {'stale': True}])
        self.assertEqual(pixels.call_args_list[0].args, (0, 32))
        Tray._property(tray, None, None, None, b'org.kde.StatusNotifierItem', b'ToolTip', None, None)
        text = tray._variant.call_args.args[0]
        self.assertIn('上次 0%', text)
        self.assertIn('已过期', text)
        self.assertIn('sleeping', text)

    def test_refresh_only_emits_changed_properties_and_never_registers_again(self):
        tray = Mock()
        tray.data = dict(device='test', percent=39, status='ok', checked_at=100)
        tray.commands = queue.Queue()
        tray.commands.put(('update', {**tray.data, 'checked_at': 200}))
        tray.bus.gio.g_dbus_connection_emit_signal.return_value = True
        Tray._flush(tray, None)
        self.assertEqual([c.args[4] for c in tray.bus.gio.g_dbus_connection_emit_signal.call_args_list], [b'NewToolTip'])
        tray._register.assert_not_called()

    def test_stale_transition_updates_icon_without_changing_identity_or_registration(self):
        tray = Mock()
        tray.data = dict(device='test', percent=39, status='ok')
        tray.commands = queue.Queue()
        tray.commands.put(('update', {**tray.data, 'status': 'stale'}))
        tray.bus.gio.g_dbus_connection_emit_signal.return_value = True
        Tray._flush(tray, None)
        self.assertEqual([c.args[4] for c in tray.bus.gio.g_dbus_connection_emit_signal.call_args_list], [b'NewToolTip', b'NewIcon'])
        tray._register.assert_not_called()

    def test_register_uses_stable_service_instead_of_connection_id(self):
        tray = Mock()
        Tray._register(tray)
        self.assertEqual(tray._variant.call_args.args[0], f"('{TRAY_BUS_NAME}',)")
