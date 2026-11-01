"""Application-owned discovery, state and refresh lifecycle; no Tk calls."""

from dataclasses import dataclass, replace
import threading
import re
import time
import uuid

from .reader import read_snapshot
from .scheduler import Cancellation, Scheduler
from ..adapters.base import BackendResult, ReadContext
from ..domain.identity import Connection
from ..domain.readings import ReadAttempt
from ..domain.state import DeviceState, reduce_attempt


@dataclass(frozen=True)
class Target:
    binding_id: str = 'default'
    vid: str = '05AC'
    pid: str = '024F'
    usb_path: str | None = None
    name: str = '无线键盘'

    def __post_init__(self):
        if not isinstance(self.binding_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', self.binding_id):
            raise ValueError('设备绑定 ID 须为 1～64 位字母、数字、下划线或短横线')
        if any(not isinstance(value, str) or not re.fullmatch(r'[0-9A-F]{4}', value) for value in (self.vid, self.pid)):
            raise ValueError('VID/PID 须为四位大写十六进制字符串')
        if not isinstance(self.name, str) or not 1 <= len(self.name) <= 100 or any(ord(c) < 32 for c in self.name):
            raise ValueError('设备名称无效')
        if self.usb_path is not None and (not isinstance(self.usb_path, str) or not self.usb_path.startswith('/sys/')
                                          or '..' in self.usb_path.split('/') or any(ord(c) < 32 for c in self.usb_path)):
            raise ValueError('usb_path 须为枚举结果中的绝对 /sys/ 路径')

    @property
    def resource(self):
        return self.usb_path or f'selector:{self.vid}:{self.pid}'


@dataclass
class Entry:
    target: Target
    state: DeviceState
    fingerprint: tuple | None = None
    sequence: int = 0
    result: BackendResult | None = None
    stale_after: float = 180


def discover(target):
    from ..diagnostics import snapshot
    return snapshot(target.vid, target.pid, target.usb_path)


def connection_fingerprint(info):
    return tuple(sorted(tuple(d.get(k) or '' for k in
                       ('usb_path', 'hid_path', 'node', 'vid', 'pid', 'product', 'interface', 'bcd_device', 'descriptor_hex'))
                        for d in info['devices']))


class ApplicationService:
    def __init__(self, inventory=discover, reader=read_snapshot, clock=time.time,
                 monotonic=time.monotonic):
        self.inventory, self.reader = inventory, reader
        self.clock, self.monotonic = clock, monotonic
        self.lock = threading.RLock()
        self.entries = {}
        self.scheduler = None
        self.closing = False

    def _entry(self, target):
        entry = Entry(target, DeviceState(Connection(uuid.uuid4().hex, 0, target.resource)))
        entry.result = BackendResult('unknown', '正在读取…', int(self.clock()), target.name)
        return entry

    def read_once(self, target=Target(), cancel_fd=None, trace=None):
        """Same discovery/reader contract as watched reads; no thread startup."""
        with self.lock:
            if self.closing:
                raise RuntimeError('service is closing')
        info = self.inventory(target)
        return self.reader(info, ReadContext(cancel_fd, trace, self.clock)).to_legacy()

    def run_lab_once(self, operation):
        """Synchronous explicit CLI operation, with an owned cancellation fd.

        Protocol-specific lab code still owns its complete cross-process
        transaction; offline decode does not enter this execution path.
        """
        with self.lock:
            if self.closing:
                raise RuntimeError('service is closing')
        cancel = Cancellation()
        try:
            return operation(cancel)
        finally:
            cancel.cancel()
            cancel.close()

    def watch(self, target, callback, interval=60, trace=None):
        if type(interval) is not int or not 30 <= interval <= 1800:
            raise ValueError('刷新间隔必须为 30～1800 秒')
        with self.lock:
            if self.closing:
                raise RuntimeError('service is closing')
            if target.binding_id in self.entries:
                raise ValueError('重复设备绑定')
            entry = self._entry(target)
            entry.stale_after = max(180, interval * 2)
            self.entries[target.binding_id] = entry
            if self.scheduler is None:
                self.scheduler = Scheduler(clock=self.monotonic)
            self.scheduler.add(target.binding_id, target.resource,
                               lambda cancel: self._read(entry, cancel, trace),
                               lambda result, error: self._complete(entry, result, error, callback), interval)

    def _read(self, entry, cancel, trace):
        info = self.inventory(entry.target)
        fingerprint = connection_fingerprint(info)
        with self.lock:
            if self.closing or self.entries.get(entry.target.binding_id) is not entry:
                raise InterruptedError('cancelled')
            if entry.fingerprint != fingerprint:
                connection = replace(entry.state.connection, generation=entry.state.connection.generation + 1)
                # A missing receiver can retain stale history; a newly connected
                # receiver must never inherit a previous physical device's value.
                reading = entry.state.reading if not fingerprint else None
                entry.state = DeviceState(connection, reading)
                entry.fingerprint = fingerprint
            entry.sequence += 1
            connection, sequence = entry.state.connection, entry.sequence
        if cancel.event.is_set():
            raise InterruptedError('cancelled')
        result = self.reader(info, ReadContext(cancel.read_fd, trace, self.clock))
        return connection, sequence, result

    def _complete(self, entry, payload, error, callback):
        with self.lock:
            if self.closing or self.entries.get(entry.target.binding_id) is not entry:
                return
            if isinstance(error, InterruptedError):
                return
            if error is not None:
                connection, sequence = entry.state.connection, entry.sequence + 1
                entry.sequence = sequence
                result = BackendResult('read_failed', str(error), int(self.clock()), entry.target.name)
            else:
                connection, sequence, result = payload
            if result.status == 'busy':
                # Contention is not a failed battery observation.
                entry.result = replace(entry.result, reason=result.reason, checked_at=result.checked_at)
                reading = entry.state.reading
                if reading is not None and reading.expired(self.monotonic(), entry.stale_after):
                    reading = replace(reading, fresh=False)
                    entry.state = replace(entry.state, reading=reading)
                    entry.result = replace(entry.result, status='stale', reading=reading)
            else:
                reading = result.reading
                if reading is not None:
                    reading = replace(reading, received_monotonic=self.monotonic())
                attempt = ReadAttempt(connection.connection_id, connection.generation, sequence,
                                      result.status, result.reason, result.checked_at, reading)
                state = reduce_attempt(entry.state, attempt)
                if state is entry.state:
                    return
                entry.state = state
                name = entry.target.name
                entry.result = replace(result, device=name, status=state.status, reading=state.reading)
            snapshot = entry.result.to_legacy()
        callback(entry.target.binding_id, snapshot)

    def snapshot(self, binding_id):
        with self.lock:
            return self.entries[binding_id].result.to_legacy()

    def refresh(self, binding_id=None):
        with self.lock:
            if self.scheduler is None or self.closing:
                return False
            ids = [binding_id] if binding_id else list(self.entries)
            return any([self.scheduler.refresh(key) for key in ids])

    def set_interval(self, interval):
        if type(interval) is not int or not 30 <= interval <= 1800:
            raise ValueError('刷新间隔必须为 30～1800 秒')
        with self.lock:
            for entry in self.entries.values():
                entry.stale_after = max(180, interval * 2)
            if self.scheduler is not None:
                self.scheduler.set_interval(interval)

    def busy(self, binding_id=None):
        return self.scheduler is not None and self.scheduler.busy(binding_id)

    def debug(self, operation, callback):
        """Drain automatic reads before an explicit lab operation, then resume."""
        with self.lock:
            if self.closing:
                raise RuntimeError('service is closing')
            if self.scheduler is None:
                self.scheduler = Scheduler(clock=self.monotonic)
            self.scheduler.add('debug:' + uuid.uuid4().hex, 'debug', operation,
                               lambda result, error: callback(result, error), exclusive=True)

    def close(self, wait=True):
        with self.lock:
            self.closing = True
            scheduler = self.scheduler
        if scheduler is not None:
            scheduler.close(wait)

    @property
    def is_alive(self):
        return self.scheduler is not None and self.scheduler.thread.is_alive()
