from contextlib import redirect_stdout
import io
import json
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import my_devices
from keyboard_power.application.targets import selectors, targets_for_args
from keyboard_power.panel import Panel, run_panel
from keyboard_power.presentation.card import BatteryCard
from keyboard_power.tray import Tray


class PresentationTests(unittest.TestCase):
    def test_cards_do_not_share_progress_styles_and_colors_follow_reading_quality(self):
        for value, status, color in ((60, 'ok', '#42d785'), (30, 'ok', '#ffca3a'),
                                     (0, 'ok', '#ff6170'), (39, 'stale', '#94a3b8')):
            card = Mock()
            card.progress = {}
            card.style_name = 'Battery1.Horizontal.TProgressbar'
            BatteryCard.render(card, dict(device='other', percent=value, status=status,
                                          reason='', source='test', updated_at=None))
            card.number.config.assert_called_once_with(text=f'{value}%', fg=color)
            self.assertEqual(card.progress['value'], value)
            card.style.configure.assert_called_once_with(card.style_name, background=color)

    def test_secondary_device_renders_without_overwriting_legacy_primary_or_tray(self):
        panel = Mock()
        panel.primary = 'one'
        panel.cards = {'one': Mock(), 'two': Mock()}
        panel.devices_data = {'one': {'percent': 39}}
        panel.data = panel.devices_data['one']
        second = dict(percent=70, status='ok', device='second')
        Panel._result(panel, second, 'two')
        self.assertEqual(panel.data['percent'], 39)
        panel.cards['two'].render.assert_called_once_with(second)
        panel.tray.send.assert_not_called()
        panel.root.after.assert_not_called()

    def test_refresh_interval_and_close_are_commands_to_service(self):
        panel = Mock()
        panel.closing = False
        panel.interval_var.get.return_value = '120'
        Panel.refresh(panel)
        panel.service.refresh.assert_called_once_with()
        with patch('keyboard_power.panel.save_interval') as save:
            Panel.set_interval(panel)
        save.assert_called_once_with(120)
        panel.service.set_interval.assert_called_once_with(120)
        panel.root.after.assert_not_called()
        Panel.close(panel)
        panel.service.close.assert_called_once_with(wait=False)
        panel.tray.stop.assert_called_once_with()
        panel._finish.assert_called_once_with()

    def test_once_does_not_do_an_extra_cli_snapshot_and_keeps_json_shape(self):
        expected = dict(device='test', percent=39, status='ok', reason='', source='fake',
                        updated_at=100, checked_at=100)
        output = io.StringIO()
        with patch('my_devices.snapshot', side_effect=AssertionError('duplicate discovery')), \
                patch('my_devices.read_battery', return_value=expected) as read, redirect_stdout(output):
            self.assertEqual(my_devices.main(['--once', '--json']), 0)
        self.assertEqual(json.loads(output.getvalue()), expected)
        read.assert_called_once()

    def test_duplicate_start_rejects_mismatched_selection(self):
        args = SimpleNamespace(vid='05AC', pid='024F', usb_path='/sys/other', interval=None, debug_panel=False)
        with patch('keyboard_power.panel.os.geteuid', return_value=1000), \
                patch('keyboard_power.panel.Instance', side_effect=BlockingIOError()), \
                patch('keyboard_power.panel.command', return_value={'error': 'selection differs'}) as command:
            with self.assertRaisesRegex(RuntimeError, 'selection differs'):
                run_panel(args)
        self.assertEqual(command.call_args.kwargs['targets'][0]['usb_path'], '/sys/other')

    def test_tray_metadata_comes_from_snapshot_and_is_variant_escaped(self):
        tray = Mock()
        tray.data = dict(device="Other ' keyboard", percent=39, status='ok', updated_at=100)
        Tray._property(tray, None, None, None, b'org.kde.StatusNotifierItem', b'Title', None, None)
        title = tray._variant.call_args.args[0]
        self.assertIn('Other', title)
        self.assertNotIn('AULA', title)
        tray._variant.reset_mock()
        Tray._property(tray, None, None, None, b'org.kde.StatusNotifierItem', b'ToolTip', None, None)
        self.assertIn('39%', tray._variant.call_args.args[0])

    def test_default_target_metadata_is_selected_from_registry(self):
        args = SimpleNamespace(vid='05AC', pid='024F', usb_path=None)
        targets = targets_for_args(args)
        self.assertEqual(targets[0].name, 'AULA F98Pro')
        self.assertEqual(selectors(targets)[0]['binding_id'], 'default')
