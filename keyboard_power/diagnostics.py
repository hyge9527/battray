from pathlib import Path
import importlib.util
import os
import platform

from .bus import Bus, BusError, upower_devices
from .hid import enumerate_hid, read_text


def target_devices(devices, vid='05AC', pid='024F', usb_path=None):
    return [d for d in devices if d['vid'] == vid and d['pid'] == pid
            and (usb_path is None or d['usb_path'] == usb_path)]


def related(native_path, devices):
    if not native_path or not str(native_path).startswith('/sys/'):
        return False
    native = Path(native_path).resolve()
    for device in devices:
        for candidate in (device['hid_path'], device['usb_path']):
            if candidate:
                root = Path(candidate).resolve()
                if native == root or root in native.parents:
                    return True
    return False


def power_supplies(devices, root=Path('/sys/class/power_supply')):
    entries = []
    for path in sorted(root.glob('*')):
        if related(str(path.resolve()), devices) or related(str((path / 'device').resolve()), devices):
            entries.append({'path': str(path), **{name: read_text(path / name) for name in
                           ('capacity', 'capacity_level', 'status', 'present', 'type')}})
    return entries


def environment():
    session = {}
    try:
        with Bus() as bus:
            session = {'status': 'ok', 'status_notifier_watcher': bus.has_owner('org.kde.StatusNotifierWatcher')}
    except (BusError, OSError) as error:
        session = {'status': 'unavailable', 'reason': str(error)}
    return {'os': read_text(Path('/etc/os-release')), 'kernel': platform.release(),
            'python': platform.python_version(), 'interpreter': os.sys.executable,
            'desktop': os.environ.get('XDG_CURRENT_DESKTOP'),
            'session_type': os.environ.get('XDG_SESSION_TYPE'),
            'display_configured': bool(os.environ.get('DISPLAY')),
            'tkinter_importable': importlib.util.find_spec('tkinter') is not None,
            'session_bus': session}


def snapshot(vid='05AC', pid='024F', usb_path=None, all_devices=False):
    devices = enumerate_hid()
    targets = target_devices(devices, vid, pid, usb_path)
    try:
        power = upower_devices()
    except (BusError, OSError) as error:
        power = {'status': 'unavailable', 'reason': str(error), 'devices': []}
    for device in power['devices']:
        device['matches_target'] = related(device.get('NativePath'), targets)
    supplies = power_supplies(targets)
    return {'target': {'vid': vid, 'pid': pid, 'usb_path': usb_path},
            'devices': devices if all_devices else targets,
            'target_interface_count': len(targets),
            'physical_target_count': len({d['usb_path'] or d['hid_path'] for d in targets}),
            'power_supplies': supplies, 'upower': power}


def battery_result(info):
    """Compatibility entry for a system-only diagnostic result; no HID writes."""
    from .adapters.base import ReadContext
    from .adapters.system_power import read_system_power
    return read_system_power(info, ReadContext()).to_legacy()


def read_battery(vid='05AC', pid='024F', usb_path=None, cancel_fd=None, trace=None):
    """Discover once and delegate source selection to the application layer."""
    from .application.service import ApplicationService, Target
    service = ApplicationService(inventory=lambda target: snapshot(target.vid, target.pid, target.usb_path))
    return service.read_once(Target(vid=vid, pid=pid, usb_path=usb_path), cancel_fd, trace)
