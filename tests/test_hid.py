import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from keyboard_power.hid import DescriptorError, enumerate_hid, extract_battery, parse_descriptor


class DescriptorTests(unittest.TestCase):
    def test_enumeration_preserves_usb_revision_and_interface_identity(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            usb = root / 'devices/usb1/1-1'
            interface = usb / '1-1:1.3'
            hid = interface / '0003:05AC:024F.0001'
            entry = hid / 'hidraw/hidraw7'
            entry.mkdir(parents=True)
            (root / 'class/hidraw').mkdir(parents=True)
            (root / 'class/hidraw/hidraw7').symlink_to(entry)
            for key, value in {'idVendor': '05ac', 'idProduct': '024f', 'bcdDevice': '0121', 'product': '2.4G Dongle'}.items():
                (usb / key).write_text(value)
            (interface / 'bInterfaceNumber').write_text('03')
            (hid / 'uevent').write_text('HID_ID=0003:000005AC:0000024F\nHID_NAME=2.4G Dongle\n')
            from keyboard_power.aula import DESCRIPTOR
            (hid / 'report_descriptor').write_bytes(DESCRIPTOR)
            device = enumerate_hid(root, root / 'dev')[0]
            self.assertEqual(device['bcd_device'], '0121')
            self.assertEqual(device['interface'], '03')
            self.assertEqual(device['usb_path'], str(usb))
            self.assertEqual(device['reports'][1]['hidraw_write_bytes'], 33)

    def test_target_vendor_interfaces_have_no_standard_battery_or_feature(self):
        for count in (32, 64):
            raw = bytes.fromhex('0660ff0961a1010962150026ff0095') + bytes([count]) + bytes.fromhex(
                '750881020963150026ff0095') + bytes([count]) + bytes.fromhex('75089102c0')
            descriptor = parse_descriptor(raw)
            self.assertEqual(descriptor.collections, [0xFF600061])
            self.assertEqual(descriptor.report_bits, {('input', 0): 8 * count, ('output', 0): 8 * count})
            self.assertFalse(descriptor.summary()['battery_fields'])

    def test_bit_offset_padding_numbered_report_and_scale(self):
        raw = bytes.fromhex('05060901a1018507750395018101750509201500251f8102c0')
        descriptor = parse_descriptor(raw)
        battery = descriptor.fields[1]
        self.assertEqual(battery.battery_offsets(), [3])
        self.assertEqual(extract_battery(battery, 3, bytes([7, 31 << 3])), (100, True, 31))
        with self.assertRaises(ValueError):
            extract_battery(battery, 3, bytes([8, 255]))

    def test_signed_minimum_and_maximum(self):
        raw = bytes.fromhex('05060901a1010920159c256475089501b102c0')
        battery = parse_descriptor(raw).fields[0]
        self.assertEqual(extract_battery(battery, 0, b'\x00'), (50, True, 0))
        self.assertEqual(extract_battery(battery, 0, b'\x9c'), (0, True, -100))

    def test_constant_or_array_not_mistaken_for_scalar_battery(self):
        for flags in (0, 1, 3):
            raw = bytes.fromhex('05060901a1010920150025647508950181') + bytes([flags]) + b'\xc0'
            self.assertFalse(parse_descriptor(raw).summary()['battery_fields'])

    def test_unsigned_maximum_not_sign_extended(self):
        raw = bytes.fromhex('05060901a1010920150025ff75089501b102c0')
        battery = parse_descriptor(raw).fields[0]
        self.assertEqual(battery.logical_max, 255)
        self.assertEqual(extract_battery(battery, 0, b'\xff'), (100, True, 255))

    def test_global_push_pop_and_separate_report_offsets(self):
        raw = bytes.fromhex('05060901a10185017508950115002564a485020920b102b40920b102c0')
        parsed = parse_descriptor(raw)
        self.assertEqual(parsed.report_bits, {('feature', 2): 8, ('feature', 1): 8})
        self.assertEqual([f.battery_offsets() for f in parsed.fields], [[0], [0]])

    def test_usage_range_and_extended_usage(self):
        raw = bytes.fromhex('05060901a101191f29211500256475089503b102c0')
        self.assertEqual(parse_descriptor(raw).fields[0].battery_offsets(), [8])
        raw = bytes.fromhex('05010906a1010b200006001500256475089501b102c0')
        self.assertEqual(parse_descriptor(raw).fields[0].battery_offsets(), [0])

    def test_truncated_out_of_range_or_wrong_id_report_rejected(self):
        raw = bytes.fromhex('05060901a101850109201500256475089501b102c0')
        battery = parse_descriptor(raw).fields[0]
        for report in (b'', b'\x01', b'\x02\x32', b'\x01\xff'):
            with self.subTest(report=report), self.assertRaises(ValueError):
                extract_battery(battery, 0, report)

    def test_malformed_or_unsupported_descriptors_fail_closed(self):
        cases = ('06ff', 'b4', 'c0', '05060901a101', 'fe0000',
                 '05060901a1010920750895018102850109208102c0',
                 '05060901a101750895ff95008102c0')
        for case in cases:
            with self.subTest(case=case), self.assertRaises(DescriptorError):
                parse_descriptor(bytes.fromhex(case))


if __name__ == '__main__':
    unittest.main()
