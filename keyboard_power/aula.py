"""Battery-only exchange for AULA's 32-byte FF60 channel.

Source: Ghost-CR/F75_Initializer, aula_hacky/protocol_core.py
SESSION_QUERY_OUT / SESSION_QUERY_IN. The local F98Pro was checked against its
screen at 39%; the shared profile matcher gates use on its measured USB revision.
This low-level query still returns a raw sample, not a universal device claim.
No session init/config/reset commands are sent.
"""

import os
import selectors
import time


from .adapters.profiles import F98PRO, match_f98pro
from .transport import output_buffer

DESCRIPTOR = bytes.fromhex(F98PRO.descriptor_hex)


def battery_request():
    body = bytes([0x20, 0x01]) + bytes(29)
    return body + bytes([sum(body) & 255])


def parse_reply(data):
    if len(data) != 32 or data[:3] != b'\x20\x01\x00':
        raise ValueError('reply length/header does not match battery query')
    if sum(data[:-1]) & 255 != data[-1]:
        raise ValueError('reply checksum mismatch')
    if data[3] > 100:
        raise ValueError('battery percentage outside 0..100')
    return data[3]


def select_interface(devices):
    match = match_f98pro(devices)
    if not match.automatic_read_allowed:
        raise ValueError(match.reason)
    return devices[match.index]


def verify_opened_identity(fd, device):
    from pathlib import Path
    from .hid import read_text
    stat = os.fstat(fd)
    opened = Path(f'/sys/dev/char/{os.major(stat.st_rdev)}:{os.minor(stat.st_rdev)}').resolve()
    if opened != Path(device['hid_path']) / 'hidraw' / Path(device['node']).name:
        raise ValueError('设备身份在打开期间变化，拒绝发送')
    current = read_text(Path(device['hid_path']) / 'uevent')
    if 'HID_ID=0003:000005AC:0000024F' not in current:
        raise ValueError('设备标识已变化，拒绝发送')
    if (Path(device['hid_path']) / 'report_descriptor').read_bytes() != DESCRIPTOR:
        raise ValueError('设备描述符已变化，拒绝发送')


def query(devices, timeout=2.0, trace=None, cancel_fd=None):
    from .transport import receiver_key, transaction
    device = select_interface(devices)
    with transaction(receiver_key(device)):
        return _query(devices, timeout, trace, cancel_fd)


def _query(devices, timeout=2.0, trace=None, cancel_fd=None):
    if not 0.1 <= timeout <= 10:
        raise ValueError('timeout must be between 0.1 and 10 seconds')
    device = select_interface(devices)
    # Fresh discovery immediately before open; do not hardcode a hidraw index.
    fd = os.open(device['node'], os.O_RDWR | os.O_NONBLOCK | os.O_CLOEXEC)
    try:
        # Check the opened node's sysfs identity against the selected interface,
        # so removal/reuse between enumeration and open cannot target another HID.
        verify_opened_identity(fd, device)
        deadline = time.monotonic() + timeout
        with selectors.DefaultSelector() as selector:
            selector.register(fd, selectors.EVENT_WRITE, 'device')
            if cancel_fd is not None:
                selector.register(cancel_fd, selectors.EVENT_READ, 'cancel')
            ready = selector.select(max(0, deadline - time.monotonic()))
            if any(key.data == 'cancel' for key, _ in ready):
                raise InterruptedError('cancelled')
            if not ready:
                raise TimeoutError('等待设备可写超时')
            request = battery_request()
            # Linux hidraw write requires a leading zero for unnumbered reports.
            # The device receives the following 32 bytes, not a 33-byte payload.
            written = os.write(fd, output_buffer(request))
            if trace:
                trace('TX payload', request)
            if written != 33:
                raise OSError('short HID write')
            selector.modify(fd, selectors.EVENT_READ, 'device')
            rejected = 0
            while time.monotonic() < deadline:
                ready = selector.select(max(0, deadline - time.monotonic()))
                if any(key.data == 'cancel' for key, _ in ready):
                    raise InterruptedError('cancelled')
                if not ready:
                    break
                try:
                    data = os.read(fd, 33)
                except BlockingIOError:
                    continue
                if not data:
                    raise OSError('设备已断开')
                if trace:
                    trace('RX payload', data)
                try:
                    value = parse_reply(data)
                except ValueError:
                    rejected += 1
                    if rejected >= 32:
                        raise ValueError('收到过多不匹配报告，停止探测') from None
                    continue
                return {'percent': value, 'node': device['node'], 'reply_hex': data.hex(),
                        'request_hex': request.hex(), 'status': 'unverified_sample',
                        'reason': '校验匹配的候选协议样本；请与键盘屏幕电量对照，尚未证明 F98Pro 字段含义'}
            raise TimeoutError('电量查询无匹配回复；可能休眠、未连接或协议不兼容')
    finally:
        os.close(fd)
