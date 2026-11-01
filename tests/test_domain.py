from dataclasses import replace
import unittest
from unittest.mock import Mock, patch

from keyboard_power.adapters.profiles import F98PRO, match_f98pro
from keyboard_power.domain.identity import Connection
from keyboard_power.domain.matching import MatchStatus, match_profile
from keyboard_power.domain.readings import Reading, ReadAttempt
from keyboard_power.domain.state import DeviceState, reduce_attempt
from keyboard_power.debug import calibration_template


def device(**changes):
    return dict(vid=F98PRO.vid, pid=F98PRO.pid, product=F98PRO.product,
                interface=F98PRO.interface, descriptor_hex=F98PRO.descriptor_hex,
                bcd_device='0121', **changes)


class MatchingTests(unittest.TestCase):
    def test_revision_and_identity_gate_all_automatic_presets(self):
        original = device()
        self.assertTrue(match_f98pro([original]).automatic_read_allowed)
        for changes in ({'bcd_device': '0122'}, {'bcd_device': ''},
                        {'interface': '04'}, {'descriptor_hex': '00'},
                        {'pid': '0000'}, {'product': 'Other'}):
            candidate = {**original, **changes}
            with self.subTest(changes=changes):
                self.assertFalse(match_f98pro([candidate]).automatic_read_allowed)
                self.assertEqual(calibration_template(candidate)['request_buffer_hex'], '')
        self.assertEqual(match_f98pro([{**original, 'bcd_device': '0122'}]).status,
                         MatchStatus.UNSUPPORTED_VERSION)
        self.assertEqual(original, device())

    def test_duplicate_receivers_and_unreviewed_profiles_never_auto_read(self):
        self.assertEqual(match_f98pro([device(), device()]).status, MatchStatus.AMBIGUOUS)
        candidate = match_profile(replace(F98PRO, reviewed=False), [device()])
        self.assertEqual(candidate.status, MatchStatus.CANDIDATE)
        self.assertFalse(candidate.automatic_read_allowed)
        self.assertIsNone(candidate.index)

    def test_unsupported_revision_is_rejected_before_opening_any_node(self):
        from keyboard_power.aula import query
        from contextlib import nullcontext
        candidate = {**device(), 'bcd_device': '0122', 'node': '/dev/never-open'}
        with patch('keyboard_power.transport.transaction', return_value=nullcontext()), \
                patch('keyboard_power.aula.os.open') as opened:
            with self.assertRaises(ValueError):
                query([candidate])
            opened.assert_not_called()


class StateTests(unittest.TestCase):
    def setUp(self):
        self.connection = Connection('receiver', 2, '/sys/usb/1-2')

    def attempt(self, sequence, reading=None, **changes):
        args = dict(connection_id='receiver', generation=2, sequence=sequence,
                    status='ok' if reading else 'timeout', reason='', checked_at=300,
                    reading=reading)
        return ReadAttempt(**{**args, **changes})

    def test_newer_stale_observation_replaces_older_value(self):
        old = Reading(25, 'old', 100, 101)
        new = Reading(30, 'new', 200, 300, fresh=False)
        result = reduce_attempt(DeviceState(self.connection, old), self.attempt(1, new, status='stale'))
        self.assertIs(result.reading, new)
        self.assertEqual(result.status, 'stale')

    def test_failed_read_retains_history_and_marks_stale(self):
        reading = Reading(39, 'aula', 100, 101)
        result = reduce_attempt(DeviceState(self.connection, reading), self.attempt(1))
        self.assertIs(result.reading, reading)
        self.assertEqual(result.status, 'stale')

    def test_old_connections_and_out_of_order_completions_are_ignored(self):
        state = reduce_attempt(DeviceState(self.connection), self.attempt(2, Reading(39, 'aula', 100, 101)))
        for attempt in (self.attempt(1), self.attempt(2), self.attempt(3, generation=1),
                        self.attempt(3, connection_id='other')):
            self.assertIs(reduce_attempt(state, attempt), state)

    def test_older_sample_does_not_replace_newer_sample(self):
        reading = Reading(38, 'new', 200, 201)
        state = reduce_attempt(DeviceState(self.connection, reading),
                               self.attempt(1, Reading(39, 'old', 100, 300, fresh=False), status='stale'))
        self.assertIs(state.reading, reading)
        self.assertEqual(state.status, 'stale')

    def test_reducer_keeps_previous_state_immutable(self):
        reading = Reading(25, 'old', 100, 101)
        original = DeviceState(self.connection, reading)
        incoming = Reading(30, 'new', 200, 300, fresh=False)
        updated = reduce_attempt(original, self.attempt(1, incoming, status='stale'))
        self.assertIs(original.reading, reading)
        self.assertIsNone(original.attempt)
        self.assertIs(updated.reading, incoming)

    def test_zero_and_unknown_sample_time_are_preserved(self):
        reading = Reading.from_legacy(dict(percent=0, status='ok', source='sysfs'))
        self.assertEqual(reading.percent, 0)
        self.assertIsNone(reading.observed_at)
        for invalid in (-1, 101, True, float('nan'), float('inf')):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                Reading(invalid, None, None, None)

    def test_expiry_uses_monotonic_receipt_time(self):
        reading = Reading(39, 'aula', 9999999999, 1, received_monotonic=100)
        self.assertFalse(reading.expired(110, 60))
        self.assertTrue(reading.expired(161, 60))
        self.assertTrue(replace(reading, fresh=False).expired(100, 60))

    def test_panel_renders_service_snapshot_without_rescheduling(self):
        from keyboard_power.panel import Panel
        from keyboard_power.presentation.card import BatteryCard
        panel = Mock()
        panel.primary = 'default'
        card = Mock()
        card.progress = {}
        card.style_name = 'Battery0.Horizontal.TProgressbar'
        panel.cards = {'default': card}
        panel.devices_data = {}
        incoming = dict(device='test', percent=30, status='stale', updated_at=200,
                        source='new', reason='expired', checked_at=300)
        Panel._result(panel, incoming)
        self.assertEqual(panel.data, incoming)
        card.render.assert_called_once_with(incoming)
        BatteryCard.render(card, incoming)
        card.number.config.assert_called_once_with(text='30%', fg='#94a3b8')
        panel.tray.send.assert_called_once_with('update', incoming)
        panel.root.after.assert_not_called()
