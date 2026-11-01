"""Explicit HID lab actions and offline calibration helpers."""

import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import selectors
import subprocess
import sys
import time

from .hid import enumerate_hid, parse_descriptor
from .transport import output_buffer, receiver_key, transaction  # Compatibility export for existing callers.


def find_device(node):
    devices = [d for d in enumerate_hid() if d['node'] == node]
    if len(devices) != 1 or devices[0].get('descriptor_error'):
        raise ValueError('设备未连接或描述符无法完整解析')
    return devices[0]


def vendor_only(device):
    collections = parse_descriptor(bytes.fromhex(device['descriptor_hex'])).collections
    return bool(collections) and all((usage >> 16) >= 0xff00 for usage in collections)


def validate_write(device, buffer):
    if not vendor_only(device):
        raise ValueError('只允许向纯厂商集合手动发送，不向普通键盘/鼠标集合发送')
    if not buffer:
        raise ValueError('写缓冲区为空')
    parsed = parse_descriptor(bytes.fromhex(device['descriptor_hex']))
    bits = parsed.report_bits.get(('output', buffer[0]))
    if bits is None or len(buffer) != (bits + 7) // 8 + 1:
        raise ValueError('Report ID 或长度不匹配描述符；缓冲区首字节须为 Report ID，未编号时为 00')


def exchange(node, buffer=None, duration=2.0, cancel_fd=None):
    if not 0.1 <= duration <= 10:
        raise ValueError('监听时间必须在 0.1～10 秒')
    device = find_device(node)
    if not vendor_only(device):
        raise ValueError('只允许监听纯厂商接口，不捕获普通按键或鼠标报告')
    if buffer is not None:
        validate_write(device, buffer)
    maximum = max((r['hidraw_read_bytes'] for r in device['reports'] if r['type'] == 'input'), default=0)
    if maximum == 0:
        raise ValueError('该接口没有 Input Report')
    with transaction(receiver_key(device)):
        fd = os.open(node, (os.O_RDWR if buffer is not None else os.O_RDONLY) | os.O_NONBLOCK | os.O_CLOEXEC)
        try:
            verify_identity(fd, device)
            reports = []
            deadline = time.monotonic() + duration
            with selectors.DefaultSelector() as selector:
                selector.register(fd, selectors.EVENT_WRITE if buffer is not None else selectors.EVENT_READ, 'device')
                if cancel_fd is not None:
                    selector.register(cancel_fd, selectors.EVENT_READ, 'cancel')
                while time.monotonic() < deadline and len(reports) < 32:
                    ready = selector.select(max(0, deadline - time.monotonic()))
                    if any(key.data == 'cancel' for key, _ in ready):
                        raise InterruptedError('cancelled')
                    if not ready:
                        break
                    if buffer is not None:
                        if os.write(fd, buffer) != len(buffer):
                            raise OSError('short HID write')
                        buffer = None
                        selector.modify(fd, selectors.EVENT_READ, 'device')
                        continue
                    try:
                        raw = os.read(fd, maximum + 1)
                    except BlockingIOError:
                        continue
                    if not raw:
                        raise OSError('设备已断开')
                    reports.append(raw.hex(' '))
            return reports
        finally:
            os.close(fd)


def verify_identity(fd, device):
    metadata = os.fstat(fd)
    opened = Path(f'/sys/dev/char/{os.major(metadata.st_rdev)}:{os.minor(metadata.st_rdev)}').resolve()
    expected = Path(device['hid_path']) / 'hidraw' / Path(device['node']).name
    if opened != expected or (Path(device['hid_path']) / 'report_descriptor').read_bytes().hex() != device['descriptor_hex']:
        raise ValueError('设备身份或描述符已变化，拒绝操作')


def feature_child(node, report_id):
    device = find_device(node)
    parsed = parse_descriptor(bytes.fromhex(device['descriptor_hex']))
    bits = parsed.report_bits.get(('feature', report_id))
    if bits is None:
        raise ValueError('该 Report ID 没有声明 Feature Report，不发送试探请求')
    length = (bits + 7) // 8 + 1
    if length > 8192:
        raise ValueError('Feature Report 超过工具支持的长度')
    with transaction(receiver_key(device)):
        fd = os.open(node, os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC)
        try:
            verify_identity(fd, device)
            buffer = bytearray(length)
            buffer[0] = report_id
            result = fcntl.ioctl(fd, (3 << 30) | (length << 16) | (ord('H') << 8) | 7, buffer, True)
            return bytes(buffer[:result if result > 0 else length]).hex(' ')
        finally:
            os.close(fd)


def read_feature(node, report_id=0):
    if not 0 <= report_id <= 255:
        raise ValueError('Report ID 必须在 0～255')
    # Isolate potentially blocking synchronous driver ioctl from the GUI.
    try:
        run = subprocess.run([sys.executable, '-B', '-m', 'keyboard_power.debug', node, str(report_id)],
                             cwd=Path(__file__).resolve().parent.parent, capture_output=True, timeout=4)
    except subprocess.TimeoutExpired:
        raise RuntimeError('Feature 读取超时，子进程已收尾') from None
    if run.returncode:
        raise RuntimeError(run.stderr.decode().strip() or 'Feature 读取失败')
    return run.stdout.decode().strip()


def calibration_template(device):
    from .aula import battery_request
    from .adapters.profiles import match_f98pro
    config = {'version': 1, 'device': {key: device[key] for key in ('vid', 'pid', 'product', 'interface', 'bcd_device')},
            'descriptor_sha256': hashlib.sha256(bytes.fromhex(device['descriptor_hex'])).hexdigest(),
            'report_id': 0, 'report_bytes': 32, 'bit_offset': 24, 'bit_size': 8,
            'byte_order': 'little', 'raw_min': 1, 'raw_max': 100, 'scale': 1, 'offset': 0,
            'reply_prefix_hex': '20 01 00', 'checksum': 'sum8_last_byte',
            'request_buffer_hex': output_buffer(battery_request()).hex(' '),
            'note': 'F98Pro 当前接口模板；偏移从完整 hidraw 输入报告首字节开始。修改后用真实样本验证。'}
    if not match_f98pro([device]).automatic_read_allowed:
        length = max((r['hidraw_read_bytes'] for r in device.get('reports', []) if r['type'] == 'input'), default=1)
        config.update(report_bytes=length, bit_offset=0, raw_min=0, request_buffer_hex='', reply_prefix_hex='',
                      checksum='none', note='空白标定模板；并非已知电量协议，不会自动发送请求。')
    return config


def validate_calibration(config):
    if not isinstance(config, dict) or config.get('version') != 1:
        raise ValueError('标定配置版本须为 1')
    for name, low, high in [('report_id', 0, 255), ('report_bytes', 1, 8192),
                            ('bit_offset', 0, 65535), ('bit_size', 1, 32),
                            ('raw_min', 0, 2**32 - 1), ('raw_max', 0, 2**32 - 1)]:
        value = config.get(name)
        if type(value) is not int or not low <= value <= high:
            raise ValueError('标定字段无效：' + name)
    if config['raw_min'] > config['raw_max'] or config['bit_offset'] + config['bit_size'] > config['report_bytes'] * 8:
        raise ValueError('标定范围或位偏移超出报告长度')
    if config.get('byte_order') not in ('little', 'big'):
        raise ValueError('byte_order 必须为 little 或 big')
    if config['byte_order'] == 'big' and (config['bit_offset'] % 8 or config['bit_size'] % 8):
        raise ValueError('大端字段必须按整字节对齐')
    for key in ('scale', 'offset'):
        if type(config.get(key)) not in (int, float) or not math.isfinite(config[key]):
            raise ValueError('倍率和偏移必须为有限数值')
    if config['scale'] <= 0:
        raise ValueError('倍率必须大于 0')
    if config.get('checksum') not in ('none', 'sum8_last_byte'):
        raise ValueError('不支持的校验方式')
    for key in ('reply_prefix_hex', 'request_buffer_hex'):
        if not isinstance(config.get(key, ''), str):
            raise ValueError(key + ' 必须为十六进制字符串')
    prefix = bytes.fromhex(config.get('reply_prefix_hex', ''))
    if len(prefix) > config['report_bytes']:
        raise ValueError('回复前缀超出报告长度')
    request = bytes.fromhex(config.get('request_buffer_hex', ''))
    if len(request) > 8193:
        raise ValueError('请求缓冲区过长')
    match = config.get('device')
    if not isinstance(match, dict) or not all(isinstance(match.get(k), str) for k in ('vid', 'pid', 'product', 'interface', 'bcd_device')):
        raise ValueError('缺少设备匹配信息')
    digest = config.get('descriptor_sha256', '')
    if not isinstance(digest, str) or len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest):
        raise ValueError('缺少有效的描述符 SHA256')
    return config


def decode_calibrated(config, report):
    validate_calibration(config)
    if len(report) != config['report_bytes'] or not report.startswith(bytes.fromhex(config.get('reply_prefix_hex', ''))):
        raise ValueError('报告长度或前缀不匹配标定')
    if config['report_id'] and report[0] != config['report_id']:
        raise ValueError('Report ID 不匹配')
    if config['checksum'] == 'sum8_last_byte' and sum(report[:-1]) & 255 != report[-1]:
        raise ValueError('报告校验失败')
    if config['byte_order'] == 'big':
        start = config['bit_offset'] // 8
        raw = int.from_bytes(report[start:start + config['bit_size'] // 8], 'big')
    else:
        raw = (int.from_bytes(report, 'little') >> config['bit_offset']) & ((1 << config['bit_size']) - 1)
    value = raw * config['scale'] + config['offset']
    if not config['raw_min'] <= raw <= config['raw_max'] or not 0 <= value <= 100:
        raise ValueError('原始值或换算百分比超出标定范围')
    return {'raw': raw, 'percent': value, 'source': '手动标定（需用户对照验证）'}


if __name__ == '__main__':
    try:
        print(feature_child(sys.argv[1], int(sys.argv[2])))
    except Exception as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(2)
