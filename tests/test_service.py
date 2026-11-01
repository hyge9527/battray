from dataclasses import replace
import os
from pathlib import Path
import selectors
import threading
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from keyboard_power.adapters.base import BackendResult
from keyboard_power.application.scheduler import Scheduler
from keyboard_power.application.service import ApplicationService, Target
from keyboard_power.domain.readings import Reading
from keyboard_power.transport import ResourceBusy, transaction


def info(node='a'):
    return {'devices': [{'usb_path': '/sys/usb/1', 'hid_path': '/sys/hid/' + node, 'node': '/dev/' + node}]}


class SchedulerTests(unittest.TestCase):
    def test_independent_receivers_run_concurrently_and_shutdown_joins(self):
        scheduler = Scheduler()
        started = [threading.Event(), threading.Event()]
        release = threading.Event()
        try:
            for i in range(2):
                scheduler.add(str(i), str(i), lambda cancel, i=i: (started[i].set(), release.wait(2)), lambda *_: None)
            self.assertTrue(all(event.wait(1) for event in started))
        finally:
            release.set()
            scheduler.close()
        self.assertFalse(scheduler.thread.is_alive())
        self.assertFalse(scheduler.busy())

    def test_same_receiver_is_serial_and_work_exceptions_release_it(self):
        scheduler = Scheduler()
        first, second, release = threading.Event(), threading.Event(), threading.Event()
        errors = []
        def fail(cancel):
            first.set()
            release.wait(2)
            raise ValueError('sample failure')
        try:
            scheduler.add('a', 'same', fail, lambda result, error: errors.append(error))
            self.assertTrue(first.wait(1))
            scheduler.add('b', 'same', lambda cancel: second.set(), lambda *_: None)
            self.assertFalse(second.wait(0.05))
            release.set()
            self.assertTrue(second.wait(1))
        finally:
            release.set()
            scheduler.close()
        self.assertIsInstance(errors[0], ValueError)

    def test_repeated_refreshes_coalesce_to_one_followup(self):
        scheduler = Scheduler()
        started, second, release = threading.Event(), threading.Event(), threading.Event()
        calls = []
        def work(cancel):
            calls.append(1)
            if len(calls) == 1:
                started.set()
                release.wait(2)
            else:
                second.set()
        try:
            scheduler.add('a', 'a', work, lambda *_: None, interval=60)
            self.assertTrue(started.wait(1))
            for _ in range(20):
                scheduler.refresh('a')
            release.set()
            self.assertTrue(second.wait(1))
        finally:
            release.set()
            scheduler.close()
        self.assertEqual(len(calls), 2)

    def test_fake_monotonic_deadline_wakes_without_polling(self):
        now = [100]
        scheduler = Scheduler(clock=lambda: now[0])
        first, second = threading.Event(), threading.Event()
        calls = []
        def done(*_):
            calls.append(1)
            (first if len(calls) == 1 else second).set()
        try:
            scheduler.add('a', 'a', lambda cancel: None, done, interval=60)
            self.assertTrue(first.wait(1))
            # Synchronize on completion bookkeeping, not a guessed sleep.
            with scheduler.condition:
                scheduler.condition.wait_for(lambda: not scheduler.busy(), timeout=1)
            now[0] = 159
            scheduler.wake()
            self.assertFalse(second.wait(0.03))
            now[0] = 160
            scheduler.wake()
            self.assertTrue(second.wait(1))
        finally:
            scheduler.close()

    def test_close_wakes_selector_cancellation_and_closes_fds(self):
        scheduler = Scheduler()
        started = threading.Event()
        woke = threading.Event()
        fds = []
        def work(cancel):
            fds.extend([cancel.read_fd, cancel.write_fd])
            with selectors.DefaultSelector() as selector:
                selector.register(cancel.read_fd, selectors.EVENT_READ)
                started.set()
                if selector.select(2):
                    woke.set()
        scheduler.add('a', 'a', work, lambda *_: self.fail('cancelled callback ran'))
        self.assertTrue(started.wait(1))
        scheduler.close()
        self.assertTrue(woke.is_set())
        for fd in fds:
            with self.assertRaises(OSError):
                os.fstat(fd)
        with self.assertRaises(RuntimeError):
            scheduler.add('b', 'b', work, lambda *_: None)

    def test_debug_barrier_drains_active_work_before_lab(self):
        scheduler = Scheduler()
        started, lab, release = threading.Event(), threading.Event(), threading.Event()
        try:
            scheduler.add('read', 'receiver', lambda cancel: (started.set(), release.wait(2)), lambda *_: None)
            self.assertTrue(started.wait(1))
            scheduler.add('lab', 'other', lambda cancel: lab.set(), lambda *_: None, exclusive=True)
            self.assertFalse(lab.wait(0.03))
            release.set()
            self.assertTrue(lab.wait(1))
        finally:
            release.set()
            scheduler.close()


class ServiceTests(unittest.TestCase):
    def test_read_once_has_no_thread_start_and_forwards_context(self):
        seen = []
        def reader(facts, context):
            seen.append((facts, context.cancel_fd, context.clock()))
            return BackendResult('ok', '', 100, 'test', Reading(39, 'fake', None, 100))
        service = ApplicationService(inventory=lambda target: info(), reader=reader, clock=lambda: 100)
        self.assertEqual(service.read_once(cancel_fd=12)['percent'], 39)
        self.assertEqual(seen[0][1:], (12, 100))
        self.assertIsNone(service.scheduler)
        service.close()
        with self.assertRaises(RuntimeError):
            service.read_once()

    def test_explicit_lab_operation_cleans_owned_pipe_on_failure(self):
        service = ApplicationService(inventory=lambda target: self.fail('unexpected discovery'))
        fds = []
        def operation(cancel):
            fds.extend([cancel.read_fd, cancel.write_fd])
            raise ValueError('failure')
        with self.assertRaises(ValueError):
            service.run_lab_once(operation)
        for fd in fds:
            with self.assertRaises(OSError):
                os.fstat(fd)
        self.assertIsNone(service.scheduler)
        service.close()

    def test_state_is_service_owned_failure_stales_history_and_busy_does_not(self):
        results = [BackendResult('ok', '', 100, 'test', Reading(39, 'fake', 100, 100)),
                   BackendResult('busy', 'lab', 101), BackendResult('timeout', 'sleep', 102)]
        service = ApplicationService(inventory=lambda target: info(), reader=lambda *args: results.pop(0))
        event = threading.Event()
        snapshots = []
        def done(key, result):
            snapshots.append(result)
            event.set()
        try:
            service.watch(Target(), done)
            for i in range(3):
                if i:
                    event.clear()
                    service.refresh()
                self.assertTrue(event.wait(1))
                self.assertEqual(snapshots[-1]['percent'], 39)
            self.assertEqual([x['status'] for x in snapshots], ['ok', 'ok', 'stale'])
            self.assertEqual(service.snapshot('default')['reason'], 'sleep')
        finally:
            service.close()

    def test_reconnection_generation_clears_old_device_value(self):
        facts = [info('a')]
        outcomes = [BackendResult('ok', '', 100, 'test', Reading(39, 'fake', 100, 100))]
        service = ApplicationService(inventory=lambda target: facts[0], reader=lambda *args: outcomes[0])
        event = threading.Event()
        try:
            service.watch(Target(), lambda *_: event.set())
            self.assertTrue(event.wait(1))
            generation = service.entries['default'].state.connection.generation
            facts[0] = info('b')
            outcomes[0] = BackendResult('timeout', 'new device asleep', 101)
            event.clear()
            service.refresh()
            self.assertTrue(event.wait(1))
            self.assertIsNone(service.snapshot('default')['percent'])
            self.assertGreater(service.entries['default'].state.connection.generation, generation)
        finally:
            service.close()

    def test_close_cancels_watched_read_and_suppresses_late_callback(self):
        started = threading.Event()
        callbacks = []
        def reader(facts, context):
            with selectors.DefaultSelector() as selector:
                selector.register(context.cancel_fd, selectors.EVENT_READ)
                started.set()
                selector.select(2)
            raise InterruptedError('cancelled')
        service = ApplicationService(inventory=lambda target: info(), reader=reader)
        service.watch(Target(), lambda *args: callbacks.append(args))
        self.assertTrue(started.wait(1))
        service.close()
        self.assertFalse(service.is_alive)
        self.assertEqual(callbacks, [])

    def test_persistent_busy_eventually_expires_history_using_monotonic_time(self):
        now = [0]
        outcome = [BackendResult('ok', '', 100, 'test', Reading(39, 'fake', 100, 100))]
        service = ApplicationService(inventory=lambda target: info(), reader=lambda *args: outcome[0],
                                     monotonic=lambda: now[0])
        event = threading.Event()
        try:
            service.watch(Target(), lambda *_: event.set())
            self.assertTrue(event.wait(1))
            now[0] = 181
            outcome[0] = BackendResult('busy', 'external lab lock', 101)
            event.clear()
            service.refresh()
            self.assertTrue(event.wait(1))
            result = service.snapshot('default')
            self.assertEqual((result['status'], result['percent']), ('stale', 39))
            self.assertEqual(result['reason'], 'external lab lock')
        finally:
            service.close()


class ReceiverLockTests(unittest.TestCase):
    def test_receiver_scopes_and_legacy_global_gate_release_after_error(self):
        with TemporaryDirectory() as directory, patch.dict(os.environ, XDG_RUNTIME_DIR=directory):
            with transaction('/sys/one'):
                with transaction('/sys/two'):
                    pass
                for key in ('/sys/one', None):
                    with self.assertRaises(ResourceBusy), transaction(key):
                        pass
            with transaction():
                with self.assertRaises(ResourceBusy), transaction('/sys/two'):
                    pass
            with self.assertRaises(ValueError), transaction('/sys/one'):
                raise ValueError('failure')
            with transaction('/sys/one'):
                pass
