from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import my_devices
from keyboard_power.aula import DESCRIPTOR
from keyboard_power.debug import calibration_template


class OfflineCliTests(unittest.TestCase):
    def profile(self):
        return calibration_template({'vid': '05AC', 'pid': '024F', 'product': '2.4G Dongle',
                                     'interface': '03', 'bcd_device': '0121', 'descriptor_hex': DESCRIPTOR.hex()})

    def test_decode_stays_offline_and_keeps_result_contract(self):
        with TemporaryDirectory() as directory:
            profile = Path(directory) / 'profile.json'
            profile.write_text(json.dumps(self.profile()))
            output = io.StringIO()
            sample = '2001002700000000000000000000000000000000000000000000000000000048'
            with patch('my_devices.snapshot', side_effect=AssertionError('unexpected enumeration')), \
                 patch('my_devices.read_battery', side_effect=AssertionError('unexpected hardware access')), \
                 redirect_stdout(output):
                code = my_devices.main(['--decode-report', sample, '--profile', str(profile)])
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(output.getvalue()),
                             {'raw': 39, 'percent': 39, 'source': '手动标定（需用户对照验证）'})

    def test_invalid_profile_exits_cleanly_without_debug_traceback(self):
        with TemporaryDirectory() as directory:
            profile = Path(directory) / 'profile.json'
            config = self.profile()
            config['reply_prefix_hex'] = None
            profile.write_text(json.dumps(config))
            result = subprocess.run([sys.executable, '-B', str(Path(my_devices.__file__).resolve()),
                                     '--decode-report', '00', '--profile', str(profile)],
                                    capture_output=True, text=True, timeout=5)
            self.assertEqual(result.returncode, 2)
            self.assertEqual(result.stdout, '')
            self.assertIn('reply_prefix_hex 必须为十六进制字符串', result.stderr)
            self.assertNotIn('Traceback', result.stderr)

    def test_explicit_listener_uses_service_cancellation_and_preserves_raw_output(self):
        output = io.StringIO()
        with patch('keyboard_power.debug.exchange', return_value=['20 01']) as exchange, redirect_stdout(output):
            self.assertEqual(my_devices.main(['--listen', '/dev/mock', '--duration', '0.1']), 0)
        self.assertEqual(output.getvalue(), '20 01\n')
        self.assertEqual(exchange.call_args.args, ('/dev/mock', None, 0.1))
        with self.assertRaises(OSError):
            os.fstat(exchange.call_args.kwargs['cancel_fd'])

    def test_explicit_feature_keeps_raw_output_and_does_not_enumerate_from_cli(self):
        output = io.StringIO()
        with patch('my_devices.snapshot', side_effect=AssertionError('extra discovery')), \
                patch('keyboard_power.debug.read_feature', return_value='00 27') as read, redirect_stdout(output):
            self.assertEqual(my_devices.main(['--read-feature', '/dev/mock']), 0)
        read.assert_called_once_with('/dev/mock', 0)
        self.assertEqual(output.getvalue(), '00 27\n')
