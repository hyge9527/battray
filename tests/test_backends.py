import copy
from dataclasses import replace
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from keyboard_power.adapters.base import ReadContext
from keyboard_power.adapters.aula_f98pro import AulaF98ProAdapter
from keyboard_power.adapters.profiles import F98PRO
from keyboard_power.adapters.standard_hid import decode_feature_battery, feature_diagnostic
from keyboard_power.adapters.system_power import read_system_power
from keyboard_power.application.reader import read_snapshot
from keyboard_power.application.registry import select_adapter
from keyboard_power.transport import output_buffer


def inventory():
    device = dict(vid=F98PRO.vid, pid=F98PRO.pid, product=F98PRO.product,
                  interface=F98PRO.interface, bcd_device='0121',
                  descriptor_hex=F98PRO.descriptor_hex, node='/dev/test',
                  access='read_write', battery_fields=[])
    return dict(target=dict(vid='05AC', pid='024F'), devices=[device],
                physical_target_count=1, target_interface_count=1,
                power_supplies=[], upower=dict(devices=[]))


def upower(age, **changes):
    return dict(path='/upower/test', Percentage=40, BatteryLevel=1,
                IsPresent=True, matches_target=True, UpdateTime=1000-age, **changes)


class BackendTests(unittest.TestCase):
    def setUp(self):
        self.info = inventory()
        self.context = ReadContext(clock=lambda: 1000)

    def test_system_only_preserves_output_keys_and_unknown_sampling_time(self):
        self.info['power_supplies'] = [dict(path='/sys/test', capacity='0')]
        original = copy.deepcopy(self.info)
        result = read_system_power(self.info, self.context).to_legacy()
        self.assertEqual(result, dict(device='无线键盘', percent=0, source='/sys/test/capacity',
                                     updated_at=None, checked_at=1000, status='ok',
                                     reason='内核公开值；驱动未提供采样时间，checked_at 仅表示读取时间'))
        self.assertEqual(self.info, original)

    def test_fresh_system_read_avoids_vendor_hardware_access(self):
        self.info['upower']['devices'] = [upower(10)]
        with patch('keyboard_power.aula.query', side_effect=AssertionError('unexpected HID')):
            result = read_snapshot(self.info, self.context)
        self.assertEqual((result.status, result.reading.percent), ('ok', 40))

    def test_stale_system_read_allows_supported_vendor_fallback(self):
        self.info['upower']['devices'] = [upower(200)]
        with patch('keyboard_power.aula.query', return_value={'percent': 38}) as query:
            result = read_snapshot(self.info, self.context)
        query.assert_called_once_with(self.info['devices'], cancel_fd=None, trace=None)
        self.assertEqual((result.status, result.reading.percent, result.device), ('ok', 38, 'AULA F98Pro'))
        self.assertEqual(result.reading.observed_at, 1000)

    def test_failed_fallback_preserves_stale_observation_and_reports_failure(self):
        self.info['upower']['devices'] = [upower(200)]
        for error in (TimeoutError('sleeping'), PermissionError(), FileNotFoundError(), OSError('disconnected')):
            with self.subTest(error=error), patch('keyboard_power.aula.query', side_effect=error):
                result = read_snapshot(self.info, self.context)
            self.assertEqual((result.status, result.reading.percent, result.reading.observed_at), ('stale', 40, 800))
            self.assertFalse(result.reading.fresh)
            self.assertIn('后备读取', result.reason)

    def test_zero_sample_stays_unverified_and_does_not_erase_stale_system_reading(self):
        with patch('keyboard_power.aula.query', return_value={'percent': 0}):
            result = read_snapshot(self.info, self.context)
            self.assertEqual(result.status, 'zero_unverified')
            self.assertIsNone(result.reading)
            self.info['upower']['devices'] = [upower(200)]
            result = read_snapshot(self.info, self.context)
        self.assertEqual((result.status, result.reading.percent), ('stale', 40))

    def test_absent_ambiguous_or_unsupported_never_send(self):
        for mutate, expected in ((lambda i: i.update(target_interface_count=0), 'not_detected'),
                                 (lambda i: i.update(physical_target_count=2), 'ambiguous_device'),
                                 (lambda i: i['devices'][0].update(bcd_device='0122'), 'protocol_unverified')):
            info = inventory()
            mutate(info)
            with patch('keyboard_power.aula.query', side_effect=AssertionError('unexpected HID')):
                result = read_snapshot(info, self.context)
            self.assertEqual(result.status, expected)

    def test_unknown_adapter_retains_stale_data_without_guessing_commands(self):
        self.info['devices'][0]['pid'] = 'FFFF'
        self.info['target']['pid'] = 'FFFF'
        self.info['upower']['devices'] = [upower(200)]
        with patch('keyboard_power.aula.query', side_effect=AssertionError('unexpected HID')):
            result = read_snapshot(self.info, self.context)
        self.assertEqual((result.status, result.reading.percent), ('stale', 40))

    def test_cancellation_and_trace_are_forwarded_and_cancellation_propagates(self):
        context = replace(self.context, cancel_fd=12, trace=Mock())
        with patch('keyboard_power.aula.query', side_effect=InterruptedError('cancelled')) as query:
            with self.assertRaises(InterruptedError):
                read_snapshot(self.info, context)
        query.assert_called_once_with(self.info['devices'], cancel_fd=12, trace=context.trace)

    def test_adapter_error_contract_without_a_cached_reading(self):
        for error, status in ((PermissionError(), 'permission_denied'), (FileNotFoundError(), 'missing_node'),
                              (TimeoutError('sleep'), 'timeout'), (ValueError('bad checksum'), 'read_failed')):
            with self.subTest(status=status), patch('keyboard_power.aula.query', side_effect=error):
                result = read_snapshot(self.info, self.context).to_legacy()
            self.assertEqual(result['status'], status)
            self.assertIsNone(result['percent'])
            self.assertEqual(result['checked_at'], 1000)

    def test_direct_adapter_call_revalidates_identity(self):
        self.info['devices'][0]['bcd_device'] = '0122'
        with patch('keyboard_power.aula.query') as query, self.assertRaises(ValueError):
            AulaF98ProAdapter().read(self.info['devices'], self.context)
        query.assert_not_called()

    def test_registry_refuses_overlapping_adapters_and_unreviewed_profiles(self):
        adapter = AulaF98ProAdapter()
        result = select_adapter(self.info['devices'], (adapter, adapter))
        self.assertIsNone(result.adapter)
        self.assertEqual(result.match.status, 'ambiguous')
        from keyboard_power.domain.matching import match_profile
        candidate = SimpleNamespace(match=lambda devices: match_profile(replace(F98PRO, reviewed=False), devices))
        self.assertIsNone(select_adapter(self.info['devices'], (candidate,)).adapter)
        self.assertIsNone(select_adapter(self.info['devices'], ()).match)

    def test_malformed_system_numbers_are_ignored(self):
        for changes in ({'Percentage': True}, {'Percentage': float('nan')}, {'UpdateTime': 'unknown'},
                        {'UpdateTime': float('inf')}, {'UpdateTime': True}):
            self.info['upower']['devices'] = [{**upower(10), **changes}]
            self.assertIsNone(read_system_power(self.info, self.context).reading)


class StandardFeatureTests(unittest.TestCase):
    # Synthetic descriptors, not captures or claims of a supported device.
    UNNUMBERED = '05060901a10109201500256475089501b102c0'
    NUMBERED = '05060901a101850709201500256475089501b102c0'

    def test_unnumbered_feature_ioctl_zero_is_not_part_of_payload(self):
        result = decode_feature_battery(self.UNNUMBERED, 0, b'\x00\x27')
        self.assertEqual(result[0]['percent'], 39)
        self.assertEqual(result[0]['status'], 'unverified_sample')
        self.assertFalse(result[0]['scaled'])

    def test_numbered_feature_and_scaled_logical_range(self):
        self.assertEqual(decode_feature_battery(self.NUMBERED, 7, b'\x07\x32')[0]['percent'], 50)
        scaled = self.UNNUMBERED.replace('2564', '25ff')
        result = decode_feature_battery(scaled, 0, b'\x00\xff')[0]
        self.assertEqual(result['percent'], 100)
        self.assertTrue(result['scaled'])

    def test_missing_feature_wrong_id_length_and_range_are_rejected(self):
        for descriptor, rid, report in ((F98PRO.descriptor_hex, 0, b'\x00'),
                                        (self.UNNUMBERED, 0, b'\x27'),
                                        (self.NUMBERED, 7, b'\x08\x32'),
                                        (self.UNNUMBERED, 0, b'\x00\xff'),
                                        (self.UNNUMBERED, 0, b'\x00\x32\x00'),
                                        (self.UNNUMBERED, True, b'\x00\x32')):
            with self.subTest(report=report), self.assertRaises(ValueError):
                decode_feature_battery(descriptor, rid, report)

    def test_diagnostic_annotates_offline_without_querying_hardware(self):
        with patch('keyboard_power.debug.read_feature', side_effect=AssertionError('unexpected query')):
            text = feature_diagnostic({'descriptor_hex': self.UNNUMBERED}, 0, '00 27')
        self.assertIn('Feature: 00 27', text)
        self.assertIn('unverified_sample', text)
        self.assertIn('不加入后台', text)

    def test_output_framing_is_explicit_and_strict(self):
        self.assertEqual(output_buffer(b'\x20\x01'), b'\x00\x20\x01')
        self.assertEqual(output_buffer(b'\x20\x01', 7), b'\x07\x20\x01')
        for payload, rid in ((b'', 0), ('2001', 0), (b'x', True), (b'x', 256), (b'x', -1)):
            with self.subTest(payload=payload, rid=rid), self.assertRaises(ValueError):
                output_buffer(payload, rid)
