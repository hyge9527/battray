#!/usr/bin/env python3
"""Explicit desktop acceptance check. Launches and closes only this application.

Run on the host with the same Python/Tk and desktop session as the application.
No autostart/udev settings are changed. Output is console-only.
"""

import argparse
import ctypes as C
from ctypes.util import find_library
import os
from pathlib import Path
import struct
import subprocess
import sys
import time
import zlib

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from keyboard_power.bus import Bus
from keyboard_power.runtime import command

PROJECT = Path(__file__).resolve().parent.parent


def wait_for(predicate, timeout=8):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            value = predicate()
            if value:
                return value
        except (OSError, RuntimeError):
            pass
        time.sleep(0.05)
    raise AssertionError('condition timed out')


def status_ready():
    status = command('status')
    return status if status['tray_available'] and not status['reading'] else None


def cpu_seconds(pid):
    fields = Path(f'/proc/{pid}/stat').read_text().split(') ', 1)[1].split()
    return sum(int(fields[i]) for i in (11, 12, 13, 14)) / os.sysconf('SC_CLK_TCK')


def capture_window(status, path):
    x11 = C.CDLL(find_library('X11'))
    functions = [
        ('XOpenDisplay', C.c_void_p, [C.c_char_p]),
        ('XGetImage', C.c_void_p, [C.c_void_p, C.c_ulong, C.c_int, C.c_int, C.c_uint, C.c_uint, C.c_ulong, C.c_int]),
        ('XGetPixel', C.c_ulong, [C.c_void_p, C.c_int, C.c_int]),
        ('XDestroyImage', C.c_int, [C.c_void_p]),
        ('XCloseDisplay', C.c_int, [C.c_void_p]),
    ]
    for name, result, arguments in functions:
        func = getattr(x11, name)
        func.restype, func.argtypes = result, arguments
    class XImage(C.Structure):
        _fields_ = [('width', C.c_int), ('height', C.c_int), ('xoffset', C.c_int), ('format', C.c_int),
                    ('data', C.c_void_p), ('byte_order', C.c_int), ('bitmap_unit', C.c_int),
                    ('bitmap_bit_order', C.c_int), ('bitmap_pad', C.c_int), ('depth', C.c_int),
                    ('bytes_per_line', C.c_int), ('bits_per_pixel', C.c_int),
                    ('red_mask', C.c_ulong), ('green_mask', C.c_ulong), ('blue_mask', C.c_ulong)]
    display = x11.XOpenDisplay(None)
    if not display:
        raise RuntimeError('cannot open X11 display')
    image = None
    try:
        width, height = status['window_size']
        image = x11.XGetImage(display, status['window_id'], 0, 0, width, height, C.c_ulong(-1).value, 2)
        if not image:
            raise RuntimeError('cannot capture application window')
        metadata = C.cast(image, C.POINTER(XImage)).contents
        masks = [metadata.red_mask, metadata.green_mask, metadata.blue_mask]
        shifts = [(mask & -mask).bit_length() - 1 for mask in masks]
        rows = bytearray()
        for y in range(height):
            rows.append(0)
            for x in range(width):
                pixel = x11.XGetPixel(image, x, y)
                for mask, shift in zip(masks, shifts):
                    rows.append(round(((pixel & mask) >> shift) * 255 / (mask >> shift)))
        def chunk(kind, data):
            return struct.pack('!I', len(data)) + kind + data + struct.pack('!I', zlib.crc32(kind + data))
        Path(path).write_bytes(b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('!2I5B', width, height, 8, 2, 0, 0, 0))
                               + chunk(b'IDAT', zlib.compress(rows)) + chunk(b'IEND', b''))
    finally:
        if image:
            x11.XDestroyImage(image)
        x11.XCloseDisplay(display)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--cpu-seconds', type=int, default=75)
    parser.add_argument('--screenshot', default='/tmp/f98pro-panel.png')
    args = parser.parse_args()
    try:
        old = command('quit')
        wait_for(lambda: not Path(f"/proc/{old['pid']}").exists())
    except (OSError, RuntimeError):
        pass
    for cycle in range(3):
        process = subprocess.Popen([sys.executable, '-B', str(PROJECT / 'my_devices.py'), '--tray'],
                                   cwd=PROJECT, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            status = wait_for(status_ready)
            assert status['pid'] == process.pid and not status['visible'], status
            # A sleeping physical keyboard need not reply during every run.
            # Timeouts must remain explicit and must never be displayed as 0%.
            assert status['battery']['status'] in ('ok', 'timeout', 'stale'), status
            if status['battery']['status'] != 'ok':
                print('device state:', status['battery']['status'], status['battery']['reason'], flush=True)
                assert status['battery']['percent'] is None or status['battery']['status'] == 'stale'
            name = status['tray_bus_name']
            with Bus() as bus:
                properties = bus.call(name, '/StatusNotifierItem', 'org.freedesktop.DBus.Properties',
                                      'GetAll', "('org.kde.StatusNotifierItem',)")[0]
                assert len(properties['IconPixmap']) == 2
                assert properties['IconPixmap'][0][:2] == [32, 32]
                assert len(properties['IconPixmap'][0][2]) == 32 * 32 * 4
                assert 'AULA F98Pro' in properties['ToolTip'][3]
                layout = bus.call(name, '/MenuBar', 'com.canonical.dbusmenu', 'GetLayout', '(0, -1, @as [])')
                assert len(layout[1][2]) == 3
                bus.call(name, '/StatusNotifierItem', 'org.kde.StatusNotifierItem', 'ContextMenu', '(0, 0)')
                wait_for(lambda: command('status')['visible'])
                if cycle == 0:
                    time.sleep(0.2)
                    capture_window(command('status'), args.screenshot)
                    print('panel screenshot:', args.screenshot, flush=True)
                    status = command('debug')
                    time.sleep(0.2)
                    status = command('status')
                    capture_window({**status, 'window_id': status['debug_window_id'],
                                    'window_size': status['debug_window_size']}, '/tmp/f98pro-debug.png')
                    print('debug screenshot: /tmp/f98pro-debug.png', flush=True)
                bus.call(name, '/StatusNotifierItem', 'org.kde.StatusNotifierItem', 'Activate', '(0, 0)')
                wait_for(status_ready)
                duplicate = subprocess.run([sys.executable, '-B', str(PROJECT / 'my_devices.py'), '--panel'],
                                           cwd=PROJECT, capture_output=True, timeout=5)
                assert duplicate.returncode == 0, duplicate.stderr.decode()
                assert command('status')['pid'] == process.pid
                if cycle == 1 and args.cpu_seconds:
                    # Minimize via X11 WM_DELETE_WINDOW, equivalent to closing
                    # the panel while keeping the registered tray alive.
                    from ctypes import c_void_p, c_char_p, c_ulong, c_int, c_long
                    x11 = C.CDLL(find_library('X11'))
                    x11.XOpenDisplay.restype, x11.XOpenDisplay.argtypes = c_void_p, [c_char_p]
                    x11.XInternAtom.restype, x11.XInternAtom.argtypes = c_ulong, [c_void_p, c_char_p, c_int]
                    class ClientMessage(C.Structure):
                        _fields_ = [('type', c_int), ('serial', c_ulong), ('send_event', c_int),
                                    ('display', c_void_p), ('window', c_ulong), ('message_type', c_ulong),
                                    ('format', c_int), ('data', c_long * 5)]
                    class XEvent(C.Union):
                        _fields_ = [('client', ClientMessage), ('pad', c_long * 24)]
                    x11.XSendEvent.argtypes = [c_void_p, c_ulong, c_int, c_long, C.POINTER(XEvent)]
                    x11.XSendEvent.restype = c_int
                    x11.XFlush.argtypes, x11.XFlush.restype = [c_void_p], c_int
                    x11.XCloseDisplay.argtypes, x11.XCloseDisplay.restype = [c_void_p], c_int
                    display = x11.XOpenDisplay(None)
                    try:
                        # Tk exposes an inner window; get the WM wrapper using
                        # XQueryTree instead of assuming a numeric ID offset.
                        x11.XQueryTree.argtypes = [c_void_p, c_ulong, C.POINTER(c_ulong), C.POINTER(c_ulong), C.POINTER(C.POINTER(c_ulong)), C.POINTER(C.c_uint)]
                        x11.XQueryTree.restype = c_int
                        x11.XFree.argtypes, x11.XFree.restype = [c_void_p], c_int
                        root, parent, children, count = c_ulong(), c_ulong(), C.POINTER(c_ulong)(), C.c_uint()
                        window = command('status')['window_id']
                        assert x11.XQueryTree(display, window, C.byref(root), C.byref(parent), C.byref(children), C.byref(count))
                        if children:
                            x11.XFree(children)
                        event = XEvent()
                        event.client.type, event.client.display, event.client.window = 33, display, parent.value
                        event.client.message_type = x11.XInternAtom(display, b'WM_PROTOCOLS', False)
                        event.client.format = 32
                        event.client.data[0] = x11.XInternAtom(display, b'WM_DELETE_WINDOW', False)
                        x11.XSendEvent(display, parent.value, False, 0, C.byref(event))
                        x11.XFlush(display)
                    finally:
                        x11.XCloseDisplay(display)
                    wait_for(lambda: not command('status')['visible'])
                    baseline = cpu_seconds(process.pid)
                    print(f'measuring hidden-panel CPU for {args.cpu_seconds}s…', flush=True)
                    time.sleep(args.cpu_seconds)
                    used = cpu_seconds(process.pid) - baseline
                    print(f'CPU: {used:.3f}s / {args.cpu_seconds}s', flush=True)
                    assert used < 0.5, used
                if cycle == 2:
                    # Closing during a refresh exercises the cancellation path.
                    command('refresh')
                bus.call(name, '/MenuBar', 'com.canonical.dbusmenu', 'Event', "(3, 'clicked', <int32 0>, uint32 0)")
                stdout, stderr = process.communicate(timeout=8)
                assert process.returncode == 0, stderr.decode()
                assert not stdout and not stderr, (stdout, stderr)
                wait_for(lambda: not bus.has_owner(name))
                assert not Path(f"/proc/{process.pid}").exists()
                print(f'cycle {cycle + 1}: battery, pixmaps, menu, single instance, clean exit OK', flush=True)
        finally:
            if process.poll() is None:
                try:
                    command('quit')
                    process.wait(timeout=8)
                except Exception:
                    process.terminate()
                    process.wait(timeout=5)
    print('desktop verification PASS', flush=True)


if __name__ == '__main__':
    main()
