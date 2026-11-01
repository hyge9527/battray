from pathlib import Path
from tempfile import TemporaryDirectory
import time
import unittest

from keyboard_power.diagnostics import battery_result, power_supplies, read_battery, related


def info():
    device = {'vid': '05AC', 'pid': '024F', 'hid_path': '/sys/devices/usb1/1-2/1-2:1.0/hid',
              'usb_path': '/sys/devices/usb1/1-2', 'battery_fields': [], 'access': 'permission_denied'}
    return {'target': {'vid': '05AC', 'pid': '024F'}, 'devices': [device],
            'physical_target_count': 1, 'target_interface_count': 1,
            'power_supplies': [], 'upower': {'status': 'ok', 'devices': []}}


class PowerTests(unittest.TestCase):
    def test_validated_profile_and_revision_guard(self):
        from unittest.mock import patch
        from keyboard_power.aula import DESCRIPTOR
        data = info()
        data['devices'][0].update(product='2.4G Dongle', interface='03', bcd_device='0121',
                                  descriptor_hex=DESCRIPTOR.hex(), node='/dev/hidraw7')
        with patch('keyboard_power.diagnostics.snapshot', return_value=data), patch('keyboard_power.aula.query', return_value={'percent': 38}) as query:
            self.assertEqual(read_battery()['percent'], 38)
            query.assert_called_once()
            query.reset_mock()
            data['devices'][0]['bcd_device'] = '0122'
            self.assertIsNone(read_battery()['percent'])
            query.assert_not_called()

    def test_unrelated_or_host_battery_never_used(self):
        data = info()
        for native in ('/sys/devices/usb1', '/sys/devices/usb1/1-20', 'hidpp_battery_0', ''):
            self.assertFalse(related(native, data['devices']))
        self.assertTrue(related('/sys/devices/usb1/1-2/1-2:1.0/hid/power_supply/battery', data['devices']))
        data['upower']['devices'] = [{'matches_target': False, 'Percentage': 88, 'IsPresent': True}]
        self.assertIsNone(battery_result(data)['percent'])

    def test_ambiguous_and_absent_receiver_never_get_value(self):
        data = info()
        data['power_supplies'] = [{'capacity': '70'}]
        data['physical_target_count'] = 2
        self.assertEqual(battery_result(data)['status'], 'ambiguous_device')
        data['physical_target_count'] = 0
        data['target_interface_count'] = 0
        self.assertEqual(battery_result(data)['status'], 'not_detected')

    def test_invalid_absent_or_level_only_sysfs_not_a_percentage(self):
        for supply in ({'capacity': '-1'}, {'capacity': '101'}, {'capacity': 'nan'},
                       {'capacity': '99', 'present': '0'}, {'capacity_level': 'Full'}):
            data = info()
            data['power_supplies'] = [supply]
            self.assertIsNone(battery_result(data)['percent'])

    def test_zero_is_valid_percentage_but_has_no_fake_sample_time(self):
        data = info()
        data['power_supplies'] = [{'path': '/sys/test', 'capacity': '0'}]
        result = battery_result(data)
        self.assertEqual((result['status'], result['percent']), ('ok', 0))
        self.assertIsNone(result['updated_at'])

    def test_upower_stale_levels_unknown_time_and_nan(self):
        for percent, level, age, expected in ((30, 1, 10, 'ok'), (30, 1, 200, 'stale'),
                                             (30, 0, 10, 'protocol_unverified'),
                                             (100, 8, 10, 'protocol_unverified'),
                                             (float('nan'), 1, 10, 'protocol_unverified'),
                                             (40, 1, -500, 'protocol_unverified')):
            data = info()
            data['upower']['devices'] = [{'path': '/test', 'matches_target': True, 'IsPresent': True,
                                         'Percentage': percent, 'BatteryLevel': level,
                                         'UpdateTime': int(time.time()) - age}]
            self.assertEqual(battery_result(data)['status'], expected)

    def test_descriptor_failure_is_inconclusive_not_unsupported(self):
        data = info()
        data['devices'][0]['descriptor_error'] = 'truncated'
        self.assertEqual(battery_result(data)['status'], 'descriptor_inconclusive')

    def test_power_supply_mapping_uses_real_device_ancestry(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            supplies = root / 'class/power_supply'
            supplies.mkdir(parents=True)
            target = root / 'devices/usb1/1-2'
            battery = target / 'hid/power_supply/keyboard'
            battery.mkdir(parents=True)
            (battery / 'capacity').write_text('61')
            (supplies / 'keyboard').symlink_to(battery)
            (supplies / 'laptop').mkdir()
            (supplies / 'laptop/capacity').write_text('99')
            data = info()
            data['devices'][0]['usb_path'] = str(target)
            # related() deliberately requires /sys for UPower input. Patch only
            # the sysfs namespace in this filesystem fixture, not ancestry.
            from unittest.mock import patch
            from keyboard_power.diagnostics import related as real_related
            def test_related(path, devices):
                mapped = path.replace(str(root), '/sys')
                mapped_devices = [{**d, 'usb_path': d['usb_path'].replace(str(root), '/sys')} for d in devices]
                return real_related(mapped, mapped_devices)
            with patch('keyboard_power.diagnostics.related', side_effect=test_related):
                found = power_supplies(data['devices'], supplies)
            self.assertEqual([s['capacity'] for s in found], ['61'])


if __name__ == '__main__':
    unittest.main()
