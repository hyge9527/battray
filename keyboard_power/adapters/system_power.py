"""Evaluate already-associated kernel/UPower facts; never opens an HID node."""

from dataclasses import replace
import math

from .base import BackendResult, ReadContext
from ..domain.readings import Reading


def read_system_power(info, context: ReadContext):
    now = int(context.clock())
    base = BackendResult('unknown', '', now)
    if info['physical_target_count'] > 1:
        return replace(base, status='ambiguous_device', reason='发现多个同 VID/PID 接收器，请用 --usb-path 选择目标')
    if not info['target_interface_count']:
        return replace(base, status='not_detected', reason='未枚举到目标接收器；不能确认键盘连接状态')
    for supply in info['power_supplies']:
        if supply.get('present') == '0':
            continue
        try:
            value = int(supply['capacity'])
        except (ValueError, KeyError, TypeError):
            continue
        if 0 <= value <= 100:
            return replace(base, status='ok',
                           reading=Reading(value, supply['path'] + '/capacity', None, now),
                           reason='内核公开值；驱动未提供采样时间，checked_at 仅表示读取时间')
    for device in info['upower']['devices']:
        if not device.get('matches_target') or not device.get('IsPresent'):
            continue
        # BatteryLevel NONE (1) is a numeric percentage, not an estimated bucket.
        value = device.get('Percentage')
        updated = device.get('UpdateTime', 0)
        if (device.get('BatteryLevel') != 1 or type(value) not in (int, float)
                or type(updated) not in (int, float)):
            continue
        if math.isfinite(value) and 0 <= value <= 100 and 0 < updated <= now + 5:
            stale = now - updated > 180
            return replace(base, status='stale' if stale else 'ok',
                           reading=Reading(value, device['path'], updated, now, fresh=not stale),
                           reason='UPower 缓存超过 180 秒' if stale else '')
    devices = [d for d in info['devices'] if d['vid'] == info['target']['vid'] and d['pid'] == info['target']['pid']]
    fields = [field for d in devices for field in d.get('battery_fields', [])]
    errors = [d.get('descriptor_error') for d in devices if d.get('descriptor_error')]
    if fields:
        reason = '描述符有标准电量字段，尚需验证对应报告读取及实际数值'
        status = 'standard_report_pending'
    elif errors:
        reason, status = '部分描述符无法解析，标准电量检查尚不完整', 'descriptor_inconclusive'
    else:
        reason = '已解析接口中没有标准 Battery Strength 字段；厂商电量协议待键盘型号确认'
        status = 'protocol_unverified'
    access = sorted({d['access'] for d in devices})
    return replace(base, status=status, reason=reason + '；设备节点状态：' + ', '.join(access))
