#!/usr/bin/env python3
"""Verify actual host udev authorization and desktop links without changing them."""

import ctypes as C
import argparse
from ctypes.util import find_library
import json
import os
import shlex
from pathlib import Path
import subprocess
import sys

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT))
from keyboard_power.platform.installation import render_rule, select_access
from keyboard_power.hid import enumerate_hid
from keyboard_power.settings import APP_ID, autostart_status, desktop_directory


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--launch', action='store_true', help='通过 GIO 实际启动桌面入口并验证')
    parser.add_argument('--leave-running', action='store_true', help='启动验证后保留用户应用运行')
    args = parser.parse_args()
    policy, device = select_access(enumerate_hid())
    rule = Path('/etc/udev/rules.d') / policy.filename
    assert rule.read_text() == (PROJECT / 'packaging' / policy.filename).read_text() == render_rule(policy), 'installed rule differs'
    assert device['access'] == 'read_write', device['access']
    sys_path = str(Path(device['hid_path']) / 'hidraw' / Path(device['node']).name)
    result = subprocess.run(['/usr/bin/udevadm', 'info', '--query=property', '--path', sys_path],
                            capture_output=True, text=True, check=True)
    properties = dict(line.split('=', 1) for line in result.stdout.splitlines() if '=' in line)
    assert properties.get('KEYBOARD_POWER_RECEIVER') == policy.marker, properties
    assert 'uaccess' in properties.get('CURRENT_TAGS', properties.get('TAGS', '')), properties
    directory = desktop_directory()
    targets = {'键盘电量项目': PROJECT, 'my_devices.py': PROJECT / 'my_devices.py',
               '键盘电量.desktop': PROJECT / (APP_ID + '.desktop')}
    for name, target in targets.items():
        link = directory / name
        assert link.is_symlink() and link.resolve() == target, str(link)
    gio, obj = C.CDLL(find_library('gio-2.0')), C.CDLL(find_library('gobject-2.0'))
    gio.g_desktop_app_info_new_from_filename.restype = C.c_void_p
    gio.g_desktop_app_info_new_from_filename.argtypes = [C.c_char_p]
    gio.g_app_info_get_executable.restype, gio.g_app_info_get_executable.argtypes = C.c_char_p, [C.c_void_p]
    gio.g_desktop_app_info_get_boolean.restype, gio.g_desktop_app_info_get_boolean.argtypes = C.c_int, [C.c_void_p, C.c_char_p]
    obj.g_object_unref.restype, obj.g_object_unref.argtypes = None, [C.c_void_p]
    app = gio.g_desktop_app_info_new_from_filename(str(directory / '键盘电量.desktop').encode())
    assert app, 'GIO rejected desktop launcher'
    try:
        # GIO preserves the quoting of the executable token in this accessor.
        assert shlex.split(gio.g_app_info_get_executable(app).decode()) == [sys.executable]
        assert not gio.g_desktop_app_info_get_boolean(app, b'Terminal')
    finally:
        obj.g_object_unref(app)
    print(json.dumps({'udev_rule': 'matches_installed_source', 'uaccess_tag': True,
                      'node': device['node'], 'access': device['access'], 'desktop_links': '3 verified',
                      'launcher': 'GIO parsed; Terminal=false', 'autostart': autostart_status()[1]}, ensure_ascii=False))
    if args.launch:
        from keyboard_power.runtime import command
        from tools.verify_desktop import wait_for, status_ready
        try:
            previous = command('status')
        except (OSError, RuntimeError):
            previous = None
        subprocess.run(['/usr/bin/gio', 'launch', str(directory / '键盘电量.desktop')],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True, timeout=5)
        status = wait_for(status_ready)
        print('desktop launch OK; pid=' + str(status['pid']))
        if args.leave_running:
            command('show')
        elif previous is None:
            command('quit')
            wait_for(lambda: not Path(f"/proc/{status['pid']}").exists())


if __name__ == '__main__':
    main()
