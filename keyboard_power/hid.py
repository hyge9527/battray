"""Read-only HID enumeration and a bounded HID report-descriptor parser.

Offsets exclude a numbered report's ID byte. No device commands are sent here.
"""

from dataclasses import asdict, dataclass, field
from pathlib import Path
import os
import re


class DescriptorError(ValueError):
    pass


@dataclass
class ReportField:
    kind: str
    report_id: int
    bit_offset: int
    bit_size: int
    count: int
    flags: int
    usages: list[int]
    logical_min: int
    logical_max: int
    collections: list[int]

    def battery_offsets(self):
        # Battery Strength is a scalar, not an index into an array of usages.
        if self.flags & 1 or not self.flags & 2:
            return []
        return [self.bit_offset + i * self.bit_size
                for i, usage in enumerate(self.usages)
                if usage == 0x00060020]


@dataclass
class Descriptor:
    fields: list[ReportField] = field(default_factory=list)
    report_bits: dict[tuple[str, int], int] = field(default_factory=dict)
    collections: list[int] = field(default_factory=list)

    def summary(self):
        reports = []
        for (kind, rid), bits in sorted(self.report_bits.items()):
            report = {"type": kind, "report_id": rid, "payload_bytes": (bits + 7) // 8}
            buffer_key = {'input': 'hidraw_read_bytes', 'output': 'hidraw_write_bytes',
                          'feature': 'ioctl_request_bytes'}[kind]
            report[buffer_key] = (bits + 7) // 8 + (bool(rid) if kind == 'input' else 1)
            reports.append(report)
        return {"collections": [f"{u >> 16:04X}:{u & 65535:04X}" for u in self.collections],
                "reports": reports,
                "battery_fields": [asdict(f) for f in self.fields if f.battery_offsets()]}


def parse_descriptor(data: bytes) -> Descriptor:
    state = dict(page=0, size=0, count=0, rid=0, minimum=0, maximum=0)
    stack, collections, usages = [], [], []
    usage_min = None
    result = Descriptor()
    position = 0
    while position < len(data):
        prefix = data[position]
        position += 1
        if prefix == 0xFE:
            raise DescriptorError("long HID items are not supported; inspection inconclusive")
        length = (0, 1, 2, 4)[prefix & 3]
        if position + length > len(data):
            raise DescriptorError("truncated HID item")
        raw = data[position:position + length]
        position += length
        value = int.from_bytes(raw, "little")
        signed = int.from_bytes(raw, "little", signed=True)
        typ, tag = (prefix >> 2) & 3, prefix >> 4
        if typ == 1:
            if tag == 0:
                state['page'] = value
            elif tag == 1:
                state['minimum'] = signed
            elif tag == 2:
                state['maximum'] = signed if state['minimum'] < 0 else value
            elif tag == 7:
                state['size'] = value
            elif tag == 8:
                if not 1 <= value <= 255:
                    raise DescriptorError("invalid Report ID")
                state['rid'] = value
            elif tag == 9:
                state['count'] = value
            elif tag == 10:
                stack.append(state.copy())
            elif tag == 11:
                if not stack:
                    raise DescriptorError("POP without PUSH")
                state = stack.pop()
        elif typ == 2:
            usage = value if length == 4 else (state['page'] << 16) | value
            if tag == 0:
                usages.append(usage)
            elif tag == 1:
                usage_min = usage
            elif tag == 2:
                if usage_min is None or not 0 <= usage - usage_min <= 4095:
                    raise DescriptorError("invalid or excessive usage range")
                usages.extend(range(usage_min, usage + 1))
                usage_min = None
            elif tag == 10:
                raise DescriptorError("usage delimiters unsupported; inspection inconclusive")
        elif typ == 0:
            if tag == 10:
                usage = usages[0] if usages else 0
                if not collections:
                    result.collections.append(usage)
                collections.append(usage)
            elif tag == 12:
                if not collections:
                    raise DescriptorError("END_COLLECTION without COLLECTION")
                collections.pop()
            elif tag in (8, 9, 11):
                if not collections:
                    raise DescriptorError("report outside collection")
                kind = {8: 'input', 9: 'output', 11: 'feature'}[tag]
                size, count, rid = state['size'], state['count'], state['rid']
                if not 1 <= size <= 65536 or not 1 <= count <= 4096:
                    raise DescriptorError("invalid/excessive report size/count")
                key = kind, rid
                offset = result.report_bits.get(key, 0)
                bits = offset + size * count
                if bits > 65536:
                    raise DescriptorError("report exceeds parser limit")
                assigned = (usages + [usages[-1]] * max(0, count - len(usages)))[:count] if usages else []
                result.fields.append(ReportField(kind, rid, offset, size, count, value,
                                                assigned, state['minimum'], state['maximum'],
                                                collections.copy()))
                result.report_bits[key] = bits
            usages, usage_min = [], None
    if collections or stack:
        raise DescriptorError("unbalanced HID collections or global stack")
    if any(rid for _, rid in result.report_bits) and any(rid == 0 for _, rid in result.report_bits):
        raise DescriptorError("mixed numbered and unnumbered reports")
    return result


def read_text(path: Path) -> str:
    try:
        return path.read_text(errors='replace').strip()
    except OSError:
        return ''


def device_access(path: Path) -> str:
    if not path.exists():
        return 'missing_node'
    if not os.access(path, os.R_OK):
        return 'permission_denied'
    return 'read_write' if os.access(path, os.W_OK) else 'read_only'


def enumerate_hid(sys_root=Path('/sys'), dev_root=Path('/dev')):
    devices = []
    for entry in sorted((sys_root / 'class/hidraw').glob('*')):
        parent = entry.resolve().parent.parent
        properties = dict(line.split('=', 1) for line in read_text(parent / 'uevent').splitlines() if '=' in line)
        match = re.fullmatch(r'([0-9A-Fa-f]+):([0-9A-Fa-f]+):([0-9A-Fa-f]+)', properties.get('HID_ID', ''))
        if not match:
            continue
        bus, vid, pid = (int(x, 16) for x in match.groups())
        interface = next((p for p in parent.parents if (p / 'bInterfaceNumber').is_file()), None)
        usb = next((p for p in parent.parents if (p / 'idVendor').is_file()), None)
        node = dev_root / entry.name
        item = dict(node=str(node), access=device_access(node), bus=bus,
                    vid=f'{vid:04X}', pid=f'{pid:04X}', name=properties.get('HID_NAME', ''),
                    phys=properties.get('HID_PHYS', ''), hid_path=str(parent),
                    usb_path=str(usb) if usb else None,
                    interface=read_text(interface / 'bInterfaceNumber') if interface else None,
                    manufacturer=read_text(usb / 'manufacturer') if usb else '',
                    product=read_text(usb / 'product') if usb else '',
                    bcd_device=read_text(usb / 'bcdDevice') if usb else '')
        try:
            raw = (parent / 'report_descriptor').read_bytes()
            item['descriptor_hex'] = raw.hex()
            item['descriptor_size'] = len(raw)
            item.update(parse_descriptor(raw).summary())
        except (OSError, DescriptorError) as error:
            item['descriptor_error'] = str(error)
        devices.append(item)
    return devices


def extract_battery(field: ReportField, offset: int, report: bytes):
    if field.report_id:
        if not report or report[0] != field.report_id:
            raise ValueError('unexpected Report ID')
        report = report[1:]
    if field.bit_size > 32 or offset + field.bit_size > len(report) * 8:
        raise ValueError('invalid or truncated battery field')
    raw = (int.from_bytes(report, 'little') >> offset) & ((1 << field.bit_size) - 1)
    if field.logical_min < 0 and raw & (1 << (field.bit_size - 1)):
        raw -= 1 << field.bit_size
    if not field.logical_min <= raw <= field.logical_max:
        raise ValueError('battery field outside logical range')
    if field.logical_max <= field.logical_min:
        raise ValueError('invalid logical range')
    percent = (raw - field.logical_min) * 100 / (field.logical_max - field.logical_min)
    return round(percent), (field.logical_min, field.logical_max) != (0, 100), raw
