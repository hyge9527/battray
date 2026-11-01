import copy
import unittest

from keyboard_power.aula import DESCRIPTOR
from keyboard_power.debug import calibration_template, decode_calibrated, validate_calibration, validate_write, vendor_only
from keyboard_power.hid import parse_descriptor


def device():
    return {'vid': '05AC', 'pid': '024F', 'interface': '03', 'product': '2.4G Dongle',
            'bcd_device': '0121', 'descriptor_hex': DESCRIPTOR.hex(), **parse_descriptor(DESCRIPTOR).summary()}


class DebugTests(unittest.TestCase):
    def test_invalid_json_field_types_produce_user_facing_value_errors(self):
        for key in ('reply_prefix_hex', 'request_buffer_hex', 'descriptor_sha256'):
            for invalid in (None, 42, [], {}):
                config = calibration_template(device())
                config[key] = invalid
                with self.subTest(key=key, invalid=invalid), self.assertRaises(ValueError):
                    validate_calibration(config)

    def test_optional_empty_prefix_is_consistent_between_validation_and_decode(self):
        config = calibration_template(device())
        del config['reply_prefix_hex']
        del config['request_buffer_hex']
        sample = bytes.fromhex('2001002700000000000000000000000000000000000000000000000000000048')
        self.assertEqual(decode_calibrated(config, sample)['percent'], 39)

    def test_hid_transactions_are_exclusive_and_release_after_error(self):
        import os
        from tempfile import TemporaryDirectory
        from unittest.mock import patch
        from keyboard_power.debug import transaction
        with TemporaryDirectory() as directory, patch.dict(os.environ, {'XDG_RUNTIME_DIR': directory}):
            with transaction():
                with self.assertRaises(RuntimeError):
                    with transaction():
                        self.fail('concurrent HID operation was allowed')
            with transaction():
                pass

    def test_actual_local_39_percent_reply_and_bad_checksum(self):
        config = calibration_template(device())
        reply = bytes.fromhex('2001002700000000000000000000000000000000000000000000000000000048')
        self.assertEqual(decode_calibrated(config, reply)['percent'], 39)
        with self.assertRaises(ValueError):
            decode_calibrated(config, reply[:-1] + b'\x00')
        with self.assertRaises(ValueError):
            decode_calibrated(config, bytes(32))

    def test_big_endian_and_non_byte_aligned_little_endian_fields(self):
        config = calibration_template(device())
        config.update(report_bytes=2, bit_offset=0, bit_size=16, byte_order='big', reply_prefix_hex='', checksum='none')
        self.assertEqual(decode_calibrated(config, b'\x00\x32')['percent'], 50)
        config.update(bit_size=5, bit_offset=3, byte_order='little', raw_min=0, raw_max=31, scale=100/31)
        self.assertAlmostEqual(decode_calibrated(config, b'\xf8\x00')['percent'], 100)

    def test_invalid_calibration_cannot_produce_unchecked_percentages(self):
        original = calibration_template(device())
        for changes in ({'bit_size': 1000}, {'bit_offset': 256}, {'report_bytes': True},
                        {'scale': float('nan')}, {'offset': float('inf')}, {'scale': 0},
                        {'byte_order': 'big', 'bit_offset': 3}, {'checksum': 'eval'},
                        {'descriptor_sha256': ''}, {'device': {}}, {'raw_min': 101, 'raw_max': 100}):
            config = copy.deepcopy(original)
            config.update(changes)
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                validate_calibration(config)

    def test_no_aula_command_in_other_device_template(self):
        other = {**device(), 'vid': '3151'}
        template = calibration_template(other)
        self.assertEqual(template['request_buffer_hex'], '')
        self.assertEqual(template['checksum'], 'none')

    def test_manual_write_requires_vendor_interface_and_exact_buffer(self):
        target = device()
        self.assertTrue(vendor_only(target))
        validate_write(target, bytes.fromhex(calibration_template(target)['request_buffer_hex']))
        for buffer in (bytes(32), b'\x01' + bytes(32)):
            with self.assertRaises(ValueError):
                validate_write(target, buffer)
        keyboard = {**target, 'descriptor_hex': '05010906a101050719e029e715002501750195088102c0'}
        with self.assertRaises(ValueError):
            validate_write(keyboard, bytes(33))
