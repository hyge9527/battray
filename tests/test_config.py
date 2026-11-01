from contextlib import redirect_stdout
from dataclasses import replace
import copy
import io
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import my_devices
from keyboard_power.application.service import Target
from keyboard_power.application.targets import targets_for_args
from keyboard_power.application.onboarding import assess
from keyboard_power.config.bindings import bindings_document, load_bindings, parse_bindings
from keyboard_power.config.store import load, update
from keyboard_power.platform.installation import F98_ACCESS, render_rule, select_access


def document():
    return bindings_document([Target(name='AULA F98Pro')])


class ConfigTests(unittest.TestCase):
    def test_binding_roundtrip_and_no_protocol_commands_in_schema(self):
        self.assertEqual(bindings_document(parse_bindings(document())), document())
        for key in ('request_buffer_hex', 'python', 'codec', 'command'):
            candidate = document()
            candidate['devices'][0][key] = 'arbitrary'
            with self.subTest(key=key), self.assertRaises(ValueError):
                parse_bindings(candidate)
        with self.assertRaises(ValueError):
            parse_bindings({'version': 1, 'report_id': 0})

    def test_duplicate_or_overlapping_targets_and_invalid_identity_are_rejected(self):
        original = document()
        for changes in ({'binding_id': 'debug:arbitrary'}, {'vid': '05ac'}, {'pid': 591},
                        {'usb_path': '/dev/hidraw7'}, {'usb_path': '/sys/../dev/test'}, {'name': 'bad\nname'}):
            candidate = copy.deepcopy(original)
            candidate['devices'][0].update(changes)
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                parse_bindings(candidate)
        candidate = copy.deepcopy(original)
        candidate['devices'].append({**candidate['devices'][0], 'binding_id': 'second', 'usb_path': '/sys/usb2'})
        with self.assertRaises(ValueError):
            parse_bindings(candidate)
        candidate['devices'][0]['usb_path'] = '/sys/usb1'
        self.assertEqual(len(parse_bindings(candidate)), 2)

    def test_read_legacy_never_migrates_write_preserves_original_and_unknown_data(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'settings.json'
            original = b'{"interval":90,"custom":{"keep":true}}\n'
            path.write_bytes(original)
            self.assertEqual(load(path)['interval'], 90)
            self.assertEqual(path.read_bytes(), original)
            self.assertFalse(path.with_name('settings.before-v2.json').exists())
            update(path, interval=120)
            result = json.loads(path.read_text())
            self.assertEqual(result['version'], 2)
            self.assertEqual(result['custom'], {'keep': True})
            self.assertEqual(path.with_name('settings.before-v2.json').read_bytes(), original)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_explicit_binding_writes_preserve_interval_and_clear_only_bindings(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'settings.json'
            update(path, interval=120)
            update(path, targets=parse_bindings(document()))
            self.assertEqual(load(path)['interval'], 120)
            self.assertIn('bindings', load(path))
            update(path, clear_bindings=True)
            self.assertNotIn('bindings', load(path))
            self.assertEqual(load(path)['interval'], 120)

    def test_future_or_corrupt_settings_cannot_be_overwritten(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'settings.json'
            for data in ('{"kind":"keyboard-power-settings","version":99}', '{broken', '[]'):
                path.write_text(data)
                with self.assertRaises(ValueError):
                    update(path, interval=120)
                self.assertEqual(path.read_text(), data)
            path.write_text('{"kind":"keyboard-power-settings","version":99}')
            with self.assertRaises(ValueError):
                load(path)

    def test_failed_atomic_replace_keeps_original_and_cleans_temporary_file(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'settings.json'
            update(path, interval=60)
            before = path.read_bytes()
            with patch('keyboard_power.config.store.os.replace', side_effect=OSError('failure')):
                with self.assertRaises(OSError):
                    update(path, interval=90)
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(list(Path(directory).glob('*.tmp')), [])

    def test_saved_targets_are_used_only_without_explicit_cli_selection(self):
        args = SimpleNamespace(vid='05AC', pid='024F', usb_path=None, use_saved_targets=True,
                               selection_explicit=False, targets_config=None)
        saved = [Target(binding_id='saved', name='alias', usb_path='/sys/usb1')]
        with patch('keyboard_power.settings.load_settings', return_value={'bindings': bindings_document(saved)['devices']}):
            self.assertEqual(targets_for_args(args)[0].binding_id, 'saved')
            args.selection_explicit = True
            self.assertEqual(targets_for_args(args)[0].binding_id, 'default')

    def test_check_config_is_offline_and_never_writes_user_settings(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'targets.json'
            path.write_text(json.dumps(document()))
            output = io.StringIO()
            with patch('my_devices.snapshot', side_effect=AssertionError('hardware')), \
                    patch('keyboard_power.settings.settings_path', side_effect=AssertionError('settings write')), \
                    redirect_stdout(output):
                self.assertEqual(my_devices.main(['--check-config', str(path)]), 0)
            self.assertEqual(json.loads(output.getvalue()), document())

    def test_once_all_is_explicit_versioned_output_and_uses_service(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'targets.json'
            path.write_text(json.dumps(document()))
            output = io.StringIO()
            with patch('keyboard_power.application.service.ApplicationService.read_once', return_value={'status': 'ok', 'percent': 39}) as read, redirect_stdout(output):
                self.assertEqual(my_devices.main(['--once-all', '--targets', str(path)]), 0)
            self.assertEqual(json.loads(output.getvalue()), {'version': 2, 'devices': {'default': {'status': 'ok', 'percent': 39}}})
            read.assert_called_once()


class InstallationPlanTests(unittest.TestCase):
    def test_rendered_policy_exactly_matches_existing_packaged_rule(self):
        source = Path(__file__).resolve().parent.parent / 'packaging/70-keyboard-power.rules'
        self.assertEqual(render_rule(F98_ACCESS), source.read_text())

    def test_policy_cannot_expand_to_globs_and_unknown_revision_does_not_install(self):
        with self.assertRaises(ValueError):
            render_rule(replace(F98_ACCESS, profile=replace(F98_ACCESS.profile, product='*')))
        profile = F98_ACCESS.profile
        device = dict(vid=profile.vid, pid=profile.pid, product=profile.product, interface=profile.interface,
                      descriptor_hex=profile.descriptor_hex, bcd_device='0122')
        with self.assertRaises(ValueError):
            select_access([device])
        device['bcd_device'] = '0121'
        self.assertIs(select_access([device])[1], device)

    def test_onboarding_refuses_unknown_commands_without_device_access(self):
        facts = dict(target={'vid': 'FFFF', 'pid': 'FFFF'}, devices=[])
        with patch('keyboard_power.aula.query', side_effect=AssertionError('unexpected query')):
            result = assess(facts)
        self.assertFalse(result['matches'][0]['automatic_read_allowed'])
        self.assertIsNone(result['matches'][0]['rule'])
