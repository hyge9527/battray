"""StatusNotifierItem and dbusmenu using ctypes + the system GIO/GLib libraries."""

import ctypes as C
import json
import queue
import threading
import time

from .bus import Bus, BusError, GError


SNI = 'org.kde.StatusNotifierItem'
MENU = 'com.canonical.dbusmenu'
TRAY_BUS_NAME = 'org.keyboardpower.Tray'
XML = '''<node>
<interface name="org.kde.StatusNotifierItem">
 <method name="Activate"><arg type="i" direction="in"/><arg type="i" direction="in"/></method>
 <method name="SecondaryActivate"><arg type="i" direction="in"/><arg type="i" direction="in"/></method>
 <method name="ContextMenu"><arg type="i" direction="in"/><arg type="i" direction="in"/></method>
 <property name="Category" type="s" access="read"/><property name="Id" type="s" access="read"/>
 <property name="Title" type="s" access="read"/><property name="Status" type="s" access="read"/>
 <property name="WindowId" type="u" access="read"/><property name="IconName" type="s" access="read"/>
 <property name="IconPixmap" type="a(iiay)" access="read"/>
 <property name="ToolTip" type="(sa(iiay)ss)" access="read"/>
 <property name="ItemIsMenu" type="b" access="read"/><property name="Menu" type="o" access="read"/>
 <signal name="NewIcon"/><signal name="NewToolTip"/><signal name="NewTitle"/>
</interface>
<interface name="com.canonical.dbusmenu">
 <property name="Version" type="u" access="read"/>
 <property name="TextDirection" type="s" access="read"/>
 <property name="Status" type="s" access="read"/>
 <property name="IconThemePath" type="as" access="read"/>
 <method name="GetLayout"><arg type="i" direction="in"/><arg type="i" direction="in"/><arg type="as" direction="in"/><arg type="u" direction="out"/><arg type="(ia{sv}av)" direction="out"/></method>
 <method name="GetGroupProperties"><arg type="ai" direction="in"/><arg type="as" direction="in"/><arg type="a(ia{sv})" direction="out"/></method>
 <method name="GetProperty"><arg type="i" direction="in"/><arg type="s" direction="in"/><arg type="v" direction="out"/></method>
 <method name="Event"><arg type="i" direction="in"/><arg type="s" direction="in"/><arg type="v" direction="in"/><arg type="u" direction="in"/></method>
 <method name="EventGroup"><arg type="a(isvu)" direction="in"/><arg type="ai" direction="out"/></method>
 <method name="AboutToShow"><arg type="i" direction="in"/><arg type="b" direction="out"/></method>
 <method name="AboutToShowGroup"><arg type="ai" direction="in"/><arg type="ai" direction="out"/><arg type="ai" direction="out"/></method>
</interface></node>'''

DIGITS = {
    '0': ['111', '101', '101', '101', '111'], '1': ['010', '110', '010', '010', '111'],
    '2': ['111', '001', '111', '100', '111'], '3': ['111', '001', '111', '001', '111'],
    '4': ['101', '101', '111', '001', '001'], '5': ['111', '100', '111', '001', '111'],
    '6': ['111', '100', '111', '101', '111'], '7': ['111', '001', '010', '010', '010'],
    '8': ['111', '101', '111', '101', '111'], '9': ['111', '101', '111', '001', '111'],
    '?': ['111', '001', '011', '000', '010'],
}


def icon_pixels(percent, size, stale=False):
    text = '?' if percent is None else str(round(percent))
    color = (160, 174, 192) if percent is None or stale else ((66, 215, 133) if percent >= 60 else
             (255, 202, 58) if percent >= 30 else (255, 97, 112))
    width = len(text) * 4 - 1
    scale = min((size - 4) // width, (size - 4) // 5)
    left, top = (size - width * scale) // 2, (size - 5 * scale) // 2
    pixels = bytearray(size * size * 4)
    for index, char in enumerate(text):
        for y, row in enumerate(DIGITS[char]):
            for x, pixel in enumerate(row):
                if pixel == '1':
                    for dy in range(scale):
                        for dx in range(scale):
                            offset = ((top + y * scale + dy) * size + left + (index * 4 + x) * scale + dx) * 4
                            pixels[offset:offset + 4] = bytes((255, *color))  # ARGB network byte order
    return pixels


def string(value):
    return json.dumps(str(value), ensure_ascii=False)


METHOD = C.CFUNCTYPE(None, C.c_void_p, C.c_char_p, C.c_char_p, C.c_char_p,
                     C.c_char_p, C.c_void_p, C.c_void_p, C.c_void_p)
GETPROP = C.CFUNCTYPE(C.c_void_p, C.c_void_p, C.c_char_p, C.c_char_p, C.c_char_p,
                      C.c_char_p, C.POINTER(C.POINTER(GError)), C.c_void_p)
SOURCE = C.CFUNCTYPE(C.c_int, C.c_void_p)
ASYNC = C.CFUNCTYPE(None, C.c_void_p, C.c_void_p, C.c_void_p)
SIGNAL = C.CFUNCTYPE(None, C.c_void_p, C.c_char_p, C.c_char_p, C.c_char_p,
                     C.c_char_p, C.c_void_p, C.c_void_p)


class VTable(C.Structure):
    _fields_ = [('method_call', METHOD), ('get_property', GETPROP),
                ('set_property', C.c_void_p), ('padding', C.c_void_p * 8)]


class Tray:
    def __init__(self, notify, debug=False):
        self.notify, self.debug = notify, debug
        self.data = {'percent': None, 'status': 'unknown'}
        self.commands = queue.Queue()
        self.ready = threading.Event()
        self.stopped = threading.Event()
        self.stop_requested = threading.Event()
        self.state_lock = threading.Lock()
        self.context = None
        self.thread = threading.Thread(target=self._run, name='status-notifier', daemon=False)
        self._method_cb, self._property_cb = METHOD(self._method), GETPROP(self._property)
        self._source_cb, self._async_cb = SOURCE(self._flush), ASYNC(self._registered)
        self._signal_cb = SIGNAL(self._watcher_changed)
        self.vtable = VTable(self._method_cb, self._property_cb, None, (C.c_void_p * 8)())

    def start(self):
        self.thread.start()

    def send(self, command, value=None):
        with self.state_lock:
            if self.context and not self.stopped.is_set():
                self.commands.put((command, value))
                self.bus.glib.g_main_context_invoke_full(self.context, 0, self._source_cb, None, None)

    def stop(self):
        self.stop_requested.set()
        self.send('quit')

    def _bind_native(self):
        b = self.bus
        bind = b._bind
        for name, result, args in [
            ('g_main_context_new', C.c_void_p, []),
            ('g_main_context_push_thread_default', None, [C.c_void_p]),
            ('g_main_context_pop_thread_default', None, [C.c_void_p]),
            ('g_main_context_unref', None, [C.c_void_p]),
            ('g_main_loop_new', C.c_void_p, [C.c_void_p, C.c_int]),
            ('g_main_loop_run', None, [C.c_void_p]),
            ('g_main_loop_quit', None, [C.c_void_p]),
            ('g_main_loop_unref', None, [C.c_void_p]),
            ('g_main_context_invoke_full', None, [C.c_void_p, C.c_int, SOURCE, C.c_void_p, C.c_void_p]),
        ]:
            bind(b.glib, name, result, args)
        bind(b.gio, 'g_dbus_node_info_new_for_xml', C.c_void_p, [C.c_char_p, C.POINTER(C.POINTER(GError))])
        bind(b.gio, 'g_dbus_node_info_lookup_interface', C.c_void_p, [C.c_void_p, C.c_char_p])
        bind(b.gio, 'g_dbus_node_info_unref', None, [C.c_void_p])
        bind(b.gio, 'g_dbus_connection_register_object', C.c_uint,
             [C.c_void_p, C.c_char_p, C.c_void_p, C.POINTER(VTable), C.c_void_p, C.c_void_p, C.POINTER(C.POINTER(GError))])
        bind(b.gio, 'g_dbus_connection_unregister_object', C.c_int, [C.c_void_p, C.c_uint])
        bind(b.gio, 'g_dbus_method_invocation_return_value', None, [C.c_void_p, C.c_void_p])
        bind(b.gio, 'g_dbus_method_invocation_return_dbus_error', None, [C.c_void_p, C.c_char_p, C.c_char_p])
        bind(b.gio, 'g_dbus_connection_get_unique_name', C.c_char_p, [C.c_void_p])
        bind(b.gio, 'g_dbus_connection_emit_signal', C.c_int,
             [C.c_void_p, C.c_char_p, C.c_char_p, C.c_char_p, C.c_char_p, C.c_void_p, C.POINTER(C.POINTER(GError))])
        bind(b.gio, 'g_dbus_connection_call', None,
             [C.c_void_p, C.c_char_p, C.c_char_p, C.c_char_p, C.c_char_p, C.c_void_p,
              C.c_void_p, C.c_int, C.c_int, C.c_void_p, ASYNC, C.c_void_p])
        bind(b.gio, 'g_dbus_connection_call_finish', C.c_void_p,
             [C.c_void_p, C.c_void_p, C.POINTER(C.POINTER(GError))])
        bind(b.gio, 'g_dbus_connection_signal_subscribe', C.c_uint,
             [C.c_void_p, C.c_char_p, C.c_char_p, C.c_char_p, C.c_char_p, C.c_char_p,
              C.c_int, SIGNAL, C.c_void_p, C.c_void_p])
        bind(b.gio, 'g_dbus_connection_signal_unsubscribe', None, [C.c_void_p, C.c_uint])

    def _variant(self, text):
        error = C.POINTER(GError)()
        result = self.bus.glib.g_variant_parse(None, text.encode(), None, None, C.byref(error))
        if not result:
            self.bus._raise(error)
        return result  # floating reference consumed by GIO

    def _run(self):
        registrations, node, subscription, context, loop = [], None, 0, None, None
        name_owned = False
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
            node = self.bus.gio.g_dbus_node_info_new_for_xml(XML.encode(), C.byref(error))
            if not node:
                self.bus._raise(error)
            for path, interface in [('/StatusNotifierItem', SNI), ('/MenuBar', MENU)]:
                iface = self.bus.gio.g_dbus_node_info_lookup_interface(node, interface.encode())
                registration = self.bus.gio.g_dbus_connection_register_object(
                    self.bus.connection, path.encode(), iface, C.byref(self.vtable), None, None, C.byref(error))
                if not registration:
                    self.bus._raise(error)
                registrations.append(registration)
            # A well-known name makes the host's indicator identity independent
            # of the connection's changing :1.N unique name on each restart.
            owned = self.bus.call('org.freedesktop.DBus', '/org/freedesktop/DBus',
                                  'org.freedesktop.DBus', 'RequestName', f"('{TRAY_BUS_NAME}', uint32 4)")[0]
            if owned != 1:
                raise RuntimeError('键盘电量托盘标识已被占用')
            name_owned = True
            subscription = self.bus.gio.g_dbus_connection_signal_subscribe(
                self.bus.connection, b'org.freedesktop.DBus', b'org.freedesktop.DBus', b'NameOwnerChanged',
                b'/org/freedesktop/DBus', b'org.kde.StatusNotifierWatcher', 0, self._signal_cb, None, None)
            with self.state_lock:
                self.context = context
            self.ready.set()
            if not self.stop_requested.is_set():
                self._register()
                self.bus.glib.g_main_loop_run(loop)
        except Exception as error:
            self.notify('tray_error', str(error))
        finally:
            with self.state_lock:
                self.context = None
                self.stopped.set()
            if hasattr(self, 'bus'):
                if subscription:
                    self.bus.gio.g_dbus_connection_signal_unsubscribe(self.bus.connection, subscription)
                for registration in registrations:
                    self.bus.gio.g_dbus_connection_unregister_object(self.bus.connection, registration)
                if name_owned:
                    try:
                        self.bus.call('org.freedesktop.DBus', '/org/freedesktop/DBus',
                                      'org.freedesktop.DBus', 'ReleaseName', f"('{TRAY_BUS_NAME}',)")
                    except (BusError, OSError):
                        pass  # A lost session bus must not skip native cleanup.
                if node:
                    self.bus.gio.g_dbus_node_info_unref(node)
                if loop:
                    self.bus.glib.g_main_loop_unref(loop)
                if context:
                    self.bus.glib.g_main_context_pop_thread_default(context)
                    self.bus.glib.g_main_context_unref(context)
                self.bus.close()
            self.ready.set()

    def _register(self):
        self.bus.gio.g_dbus_connection_call(
            self.bus.connection, b'org.kde.StatusNotifierWatcher', b'/StatusNotifierWatcher',
            b'org.kde.StatusNotifierWatcher', b'RegisterStatusNotifierItem',
            self._variant(f"('{TRAY_BUS_NAME}',)"), None, 1, 1500, None, self._async_cb, None)

    def _registered(self, connection, result, _):
        error = C.POINTER(GError)()
        value = self.bus.gio.g_dbus_connection_call_finish(connection, result, C.byref(error))
        try:
            if not value:
                self.bus._raise(error)
            self.bus.glib.g_variant_unref(value)
            name = self.bus.gio.g_dbus_connection_get_unique_name(connection).decode()
            self.notify('tray_ready', name)
        except Exception as error:
            self.notify('tray_error', str(error))

    def _watcher_changed(self, connection, sender, path, interface, member, parameters, user_data):
        try:
            name, old, new = self.bus._decode(parameters)
            if new:
                self._register()
            else:
                self.notify('tray_error', '托盘宿主已离线，恢复后会重新注册')
        except Exception as error:
            self.notify('tray_error', str(error))

    def _flush(self, _):
        try:
            while True:
                try:
                    command, value = self.commands.get_nowait()
                except queue.Empty:
                    break
                if command == 'quit':
                    self.bus.glib.g_main_loop_quit(self.loop)
                    break
                if command == 'update':
                    old = self.data
                    self.data = dict(value)
                    signals = [b'NewToolTip']
                    if (old.get('percent'), old.get('status') == 'ok') != (value.get('percent'), value.get('status') == 'ok'):
                        signals.append(b'NewIcon')
                    if old.get('device') != value.get('device'):
                        signals.append(b'NewTitle')
                    for signal in signals:
                        error = C.POINTER(GError)()
                        if not self.bus.gio.g_dbus_connection_emit_signal(
                                self.bus.connection, None, b'/StatusNotifierItem', SNI.encode(), signal, None, C.byref(error)):
                            self.bus._raise(error)
        except Exception as error:
            self.notify('tray_error', str(error))
        return 0

    def _property(self, connection, sender, path, interface, prop, error, user_data):
        try:
            name = prop.decode()
            if interface.decode() == MENU:
                return self._variant({'Version': 'uint32 3', 'TextDirection': "'ltr'",
                                      'Status': "'normal'", 'IconThemePath': '@as []'}[name])
            values = {'Category': "'Hardware'", 'Id': "'local.keyboard-power'", 'Title': string((self.data.get('device') or '无线设备') + ' 电量'),
                      'Status': "'Active'", 'WindowId': 'uint32 0', 'IconName': "''", 'ItemIsMenu': 'false',
                      'Menu': "objectpath '/MenuBar'"}
            if name == 'IconPixmap':
                pixmaps = []
                for size in (32, 64):
                    raw = icon_pixels(self.data.get('percent'), size, stale=self.data.get('status') != 'ok')
                    pixmaps.append(f"({size}, {size}, @ay [{','.join(map(str, raw))}])")
                return self._variant('@a(iiay) [' + ','.join(pixmaps) + ']')
            if name == 'ToolTip':
                value = self.data.get('percent')
                value = '?' if value is None else f'{value:g}%'
                if self.data.get('percent') is not None and self.data.get('status') != 'ok':
                    value = '上次 ' + value + '（已过期）'
                stamp = self.data.get('updated_at') or self.data.get('checked_at')
                when = time.strftime('%H:%M:%S', time.localtime(stamp)) if stamp else '尚未读取'
                desc = f"{self.data.get('device') or '无线设备'}：{value}（{when}）"
                if self.data.get('status') != 'ok':
                    desc += ' · ' + self.data.get('reason', '未知')
                return self._variant(f"('', @a(iiay) [], '键盘电量', {string(desc)})")
            return self._variant(values[name])
        except Exception as exc:
            self.notify('tray_error', str(exc))
            return None

    @staticmethod
    def _menu_props(index):
        labels = {1: '打开面板', 2: '立即刷新', 3: '退出'}
        if index == 0:
            return "{'children-display': <'submenu'>}"
        if index not in labels:
            raise ValueError('unknown menu item')
        return "{'label': <" + string(labels[index]) + ">, 'enabled': <true>, 'visible': <true>}"

    def _layout(self, index, depth):
        children = ','.join('<' + self._layout(i, 0) + '>' for i in (1, 2, 3)) if index == 0 and depth != 0 else ''
        return f'({index}, {self._menu_props(index)}, @av [{children}])'

    def _menu_event(self, event):
        index, name = event[:2]
        if name == 'clicked' and index in (1, 2, 3):
            self.notify({1: 'show', 2: 'refresh', 3: 'quit'}[index], None)

    def _method(self, connection, sender, path, interface, method, parameters, invocation, user_data):
        try:
            name, args = method.decode(), self.bus._decode(parameters)
            if interface.decode() == SNI:
                self.notify('refresh' if name == 'Activate' else 'show', None)
                text = '()'
            elif name == 'GetLayout':
                text = f'(uint32 1, {self._layout(args[0], args[1])})'
            elif name == 'GetGroupProperties':
                indices = args[0] or [0, 1, 2, 3]
                text = '(@a(ia{sv}) [' + ','.join(f'({i}, {self._menu_props(i)})' for i in indices) + '],)'
            elif name == 'GetProperty':
                if args[1] == 'label' and args[0] in (1, 2, 3):
                    text = '(<'+ string({1: '打开面板', 2: '立即刷新', 3: '退出'}[args[0]]) + '>,)'
                elif args[1] in ('visible', 'enabled'):
                    text = '(<true>,)'
                elif args[0] == 0 and args[1] == 'children-display':
                    text = "(<'submenu'>,)"
                else:
                    raise ValueError('unknown menu property')
            elif name == 'Event':
                self._menu_event(args)
                text = '()'
            elif name == 'EventGroup':
                for event in args[0]:
                    self._menu_event(event)
                text = '(@ai [],)'
            elif name == 'AboutToShow':
                text = '(false,)'
            elif name == 'AboutToShowGroup':
                text = '(@ai [], @ai [])'
            else:
                raise ValueError('unknown method')
            self.bus.gio.g_dbus_method_invocation_return_value(invocation, self._variant(text))
        except Exception as error:
            self.bus.gio.g_dbus_method_invocation_return_dbus_error(
                invocation, b'local.keyboard_power.InvalidRequest', str(error).encode())
