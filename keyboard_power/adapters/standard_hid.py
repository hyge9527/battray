"""Experimental standard Feature decoding, only for explicitly requested samples.

No registration for automatic reads: a descriptor declares a field, but does not
verify the device's battery semantics. Never listens to keyboard Input Reports.
The existing lab owns the isolated Feature ioctl and its timeout/identity check.
"""

from ..hid import extract_battery, parse_descriptor


def decode_feature_battery(descriptor_hex, report_id, report):
    if type(report_id) is not int or not 0 <= report_id <= 255:
        raise ValueError('Report ID 必须为 0～255 的整数')
    parsed = parse_descriptor(bytes.fromhex(descriptor_hex))
    bits = parsed.report_bits.get(('feature', report_id))
    if bits is None:
        raise ValueError('该 Report ID 未声明 Feature Report')
    if len(report) != (bits + 7) // 8 + 1 or report[0] != report_id:
        raise ValueError('Feature Report ID 或长度不匹配描述符')
    # ioctl buffers always carry ID 0; extract_battery expects the input shape,
    # where unnumbered payloads do not include that extra byte.
    payload = report if report_id else report[1:]
    samples = []
    for field in parsed.fields:
        if field.kind != 'feature' or field.report_id != report_id:
            continue
        for offset in field.battery_offsets():
            percent, scaled, raw = extract_battery(field, offset, payload)
            samples.append(dict(percent=percent, scaled=scaled, raw=raw,
                                bit_offset=offset, report_id=report_id,
                                status='unverified_sample'))
    return samples


def feature_diagnostic(device, report_id, raw_hex):
    """Add offline interpretation without issuing an additional device request."""
    samples = decode_feature_battery(device['descriptor_hex'], report_id, bytes.fromhex(raw_hex))
    if not samples:
        return 'Feature: ' + raw_hex
    import json
    return ('Feature: ' + raw_hex + '\n标准电量字段候选（需对照设备确认，不加入后台）：'
            + json.dumps(samples, ensure_ascii=False))
