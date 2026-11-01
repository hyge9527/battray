#!/usr/bin/env python3
"""Private session bus + mock hardware, real Tk/SNI, temporary settings/IPC.

Run with dbus-run-session. Uses the current display for a short test window;
never opens HID, installs rules, or sends commands to the user's running app.
"""

import ctypes as C
import json
import os
from pathlib import Path
import sys
import subprocess
from tempfile import TemporaryDirectory
import threading
import time
from types import SimpleNamespace
from unittest.mock import patch

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT))
from keyboard_power.adapters.base import BackendResult
from keyboard_power.application.service import ApplicationService, Target
from keyboard_power.bus import Bus, GError
from keyboard_power.config.bindings import bindings_document
from keyboard_power.domain.readings import Reading
from keyboard_power.panel import Panel
from keyboard_power.runtime import Instance, command
from keyboard_power.tray import Tray, icon_pixels, TRAY_BUS_NAME
from tools.verify_desktop import capture_window

WATCHER_XML = '''<node><interface name="org.kde.StatusNotifierWatcher">
<method name="RegisterStatusNotifierItem"><arg type="s" direction="in"/></method>
</interface></node>'''


class Watcher(Tray):
    """Minimal test host, on the private bus only; no desktop host interaction."""
    def __init__(self):
        self.errors, self.items = [], []
        super().__init__(lambda *args: self.errors.append(args))

    def _method(self, connection, sender, path, interface, method, parameters, invocation, user_data):
        self.items.append((sender.decode(), self.bus._decode(parameters)[0]))
        self.bus.gio.g_dbus_method_invocation_return_value(invocation, self._variant('()'))

    def _run(self):
        context, loop, node, registration = None, None, None, 0
        try:
            self.bus = Bus(connect=False)
            self._bind_native()
            context = self.bus.glib.g_main_context_new()
            self.bus.glib.g_main_context_push_thread_default(context)
            error = C.POINTER(GError)()
            self.bus.connection = self.bus.gio.g_bus_get_sync(2, None, C.byref(error))
            if not self.bus.connection:
                self.bus._raise(error)
            loop = self.bus.glib.g_main_loop_new(context, False)
            self.loop = loop
            node = self.bus.gio.g_dbus_node_info_new_for_xml(WATCHER_XML.encode(), C.byref(error))
            if not node:
                self.bus._raise(error)
            iface = self.bus.gio.g_dbus_node_info_lookup_interface(node, b'org.kde.StatusNotifierWatcher')
            registration = self.bus.gio.g_dbus_connection_register_object(
                self.bus.connection, b'/StatusNotifierWatcher', iface, C.byref(self.vtable), None, None, C.byref(error))
            if not registration:
                self.bus._raise(error)
            owned = self.bus.call('org.freedesktop.DBus', '/org/freedesktop/DBus',
                                  'org.freedesktop.DBus', 'RequestName', "('org.kde.StatusNotifierWatcher', uint32 4)")[0]
            assert owned == 1, owned
            with self.state_lock:
                self.context = context
            self.ready.set()
            self.bus.glib.g_main_loop_run(loop)
        except Exception as error:
            self.errors.append(str(error))
        finally:
            with self.state_lock:
                self.context = None
                self.stopped.set()
            if hasattr(self, 'bus'):
                if registration:
                    self.bus.gio.g_dbus_connection_unregister_object(self.bus.connection, registration)
                    self.bus.call('org.freedesktop.DBus', '/org/freedesktop/DBus',
                                  'org.freedesktop.DBus', 'ReleaseName', "('org.kde.StatusNotifierWatcher',)")
                if node:
                    self.bus.gio.g_dbus_node_info_unref(node)
                if loop:
                    self.bus.glib.g_main_loop_unref(loop)
                if context:
                    self.bus.glib.g_main_context_pop_thread_default(context)
                    self.bus.glib.g_main_context_unref(context)
                self.bus.close()
            self.ready.set()


def main():
    # Refuse accidental use on the real user's bus. The wrapper sets this flag
    # only inside a freshly launched dbus-run-session (see maintenance docs).
    if (os.environ.get('KEYBOARD_POWER_PRIVATE_TEST_BUS') != '1'
            or not os.environ.get('DBUS_SESSION_BUS_ADDRESS', '').startswith(('unix:path=/tmp/', 'unix:abstract=/tmp/'))):
        raise RuntimeError('请按维护文档在 dbus-run-session 内显式运行此隔离测试')
    watcher = Watcher()
    watcher.start()
    assert watcher.ready.wait(5) and watcher.context, watcher.errors
    try:
        for cycle in range(3):
            with TemporaryDirectory() as directory, patch.dict(os.environ, XDG_RUNTIME_DIR=directory, XDG_CONFIG_HOME=directory):
                targets = [Target(binding_id='one', usb_path='/sys/test/one', name='测试设备甲'),
                           Target(binding_id='two', usb_path='/sys/test/two', name='测试设备乙')]
                config = Path(directory) / 'targets.json'
                config.write_text(json.dumps(bindings_document(targets)))
                args = SimpleNamespace(interval=60, vid='05AC', pid='024F', usb_path=None,
                                       targets_config=str(config), tray=False, debug=False, debug_panel=False)
                def inventory(target):
                    return {'devices': [dict(usb_path=target.usb_path, node='/dev/mock', hid_path='/sys/mock/' + target.binding_id)]}
                def read(facts, context):
                    value = 39 if facts['devices'][0]['usb_path'].endswith('one') else 70
                    return BackendResult('ok', '', 100, 'fake', Reading(value, '模拟来源', 100, 100))
                instance = Instance()
                failures = []
                app = None
                with patch('keyboard_power.panel.ApplicationService', side_effect=lambda: ApplicationService(inventory=inventory, reader=read)), \
                        patch('keyboard_power.aula.query', side_effect=AssertionError('real HID forbidden')):
                    try:
                        app = Panel(args, instance)
                        deadline = time.monotonic() + 10
                        def fail(kind, error, traceback):
                            failures.append(repr(error))
                            app.close()
                        app.root.report_callback_exception = fail
                        ipc_results, ipc_done = [], threading.Event()
                        def ipc_client():
                            try:
                                status = command('status')
                                assert status['version'] == 2 and len(status['batteries']) == 2
                                assert status['battery'] == status['batteries']['one']
                                mismatch = command('show', targets=[])
                                assert 'error' in mismatch
                                duplicate = subprocess.run([sys.executable, '-B', str(PROJECT / 'my_devices.py'),
                                                            '--panel', '--targets', str(config)],
                                                           capture_output=True, timeout=5)
                                assert duplicate.returncode == 0, duplicate.stderr.decode()
                                ipc_results.append(True)
                            except Exception as error:
                                ipc_results.append(repr(error))
                            finally:
                                ipc_done.set()
                        def finish():
                            if not ipc_done.is_set() and time.monotonic() < deadline:
                                app.root.after(30, finish)
                                return
                            try:
                                assert ipc_done.is_set() and ipc_results == [True], ipc_results
                                if cycle == 0:
                                    capture_window(dict(window_id=app.root.winfo_id(), window_size=[app.root.winfo_width(), app.root.winfo_height()]),
                                                   '/tmp/keyboard-power-refactor-isolated.png')
                                app.refresh()
                            except Exception as error:
                                failures.append(repr(error))
                            app.close()
                        def check_stale():
                            try:
                                with Bus() as bus:
                                    props = bus.call(app.bus_name, '/StatusNotifierItem', 'org.freedesktop.DBus.Properties',
                                                     'GetAll', "('org.kde.StatusNotifierItem',)")[0]
                                    assert bytes(props['IconPixmap'][0][2]) == icon_pixels(39, 32, stale=True)
                                    assert '已过期' in props['ToolTip'][3]
                                    assert bus.has_owner(TRAY_BUS_NAME)
                                threading.Thread(target=ipc_client, name='isolated-ipc-client', daemon=False).start()
                                app.root.after(30, finish)
                            except Exception as error:
                                failures.append(repr(error))
                                app.close()
                        def check():
                            try:
                                if time.monotonic() > deadline:
                                    raise AssertionError('isolated GUI timeout')
                                if not app.tray_available or app.service.busy() or any(d['percent'] is None for d in app.devices_data.values()):
                                    app.root.after(30, check)
                                    return
                                assert set(app.cards) == {'one', 'two'}
                                assert app.cards['one'].number.cget('text') == '39%'
                                assert app.cards['two'].number.cget('text') == '70%'
                                assert app.cards['one'].style_name != app.cards['two'].style_name
                                with Bus() as bus:
                                    props = bus.call(app.bus_name, '/StatusNotifierItem', 'org.freedesktop.DBus.Properties',
                                                     'GetAll', "('org.kde.StatusNotifierItem',)")[0]
                                    assert '测试设备甲' in props['ToolTip'][3]
                                    assert len(props['IconPixmap'][0][2]) == 32 * 32 * 4
                                    menu = bus.call(app.bus_name, '/MenuBar', 'com.canonical.dbusmenu', 'GetLayout', '(0, -1, @as [])')
                                    assert len(menu[1][2]) == 3
                                app._result({**app.data, 'status': 'stale', 'reason': '模拟超时'}, 'one')
                                app.root.after(50, check_stale)
                            except Exception as error:
                                failures.append(repr(error))
                                app.close()
                        app.root.after(50, check)
                        app.run()
                        assert not failures, failures
                        assert not app.service.is_alive and not app.tray.thread.is_alive()
                        for fd in (app.pipe_r, app.pipe_w):
                            try:
                                os.fstat(fd)
                            except OSError:
                                pass
                            else:
                                raise AssertionError('panel notification fd leaked')
                    finally:
                        if app is not None and (app.service.is_alive or app.tray.thread.is_alive()):
                            app.service.close()
                            app.tray.stop()
                            app.tray.thread.join(5)
                        instance.close()
                assert not instance.path.exists()
                assert not [t for t in threading.enumerate() if t.name.startswith(('battery-', 'status-notifier')) and t is not watcher.thread]
                print(f'isolated cycle {cycle + 1}: two cards, native SNI/menu, v2 IPC, duplicate/mismatch, cancel, thread/fd cleanup PASS', flush=True)
        assert len(watcher.items) == 3, watcher.items
        assert all(service == TRAY_BUS_NAME for _, service in watcher.items)
    finally:
        watcher.stop()
        watcher.thread.join(5)
    assert not watcher.thread.is_alive() and not watcher.errors, watcher.errors
    print('isolated desktop PASS; screenshot /tmp/keyboard-power-refactor-isolated.png', flush=True)


if __name__ == '__main__':
    main()
