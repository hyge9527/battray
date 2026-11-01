"""Coordination shared by production HID reads and explicit lab operations.

The packet exchanges remain protocol-specific; only lock ownership lives here.
"""

from contextlib import contextmanager
import fcntl
import hashlib
import os

from .runtime import runtime_directory


def output_buffer(payload, report_id=0):
    """Linux hidraw output always includes an ID byte, including unnumbered 0."""
    if type(report_id) is not int or not 0 <= report_id <= 255:
        raise ValueError('Report ID must be an integer in 0..255')
    if not isinstance(payload, bytes) or not payload:
        raise ValueError('payload must be nonempty bytes')
    return bytes([report_id]) + payload


class ResourceBusy(RuntimeError):
    pass


def receiver_key(device):
    # Never use reusable hidrawN as the resource identity. Legacy callers
    # without physical sysfs evidence conservatively acquire the global gate.
    return device.get('usb_path') or device.get('hid_path') or None


@contextmanager
def transaction(resource=None):
    directory = runtime_directory()
    paths = [(directory / 'local.keyboard-power.io.lock', fcntl.LOCK_SH if resource else fcntl.LOCK_EX)]
    if resource:
        digest = hashlib.sha256(resource.encode()).hexdigest()
        paths.append((directory / ('local.keyboard-power.io.' + digest + '.lock'), fcntl.LOCK_EX))
    descriptors = []
    try:
        for path, mode in paths:
            fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_CLOEXEC | os.O_NOFOLLOW, 0o600)
            descriptors.append(fd)
            try:
                fcntl.flock(fd, mode | fcntl.LOCK_NB)
            except BlockingIOError:
                raise ResourceBusy('另一项 HID 操作正在进行，请稍后重试') from None
        yield
    finally:
        for fd in reversed(descriptors):
            os.close(fd)
