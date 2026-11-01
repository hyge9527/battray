"""Small synchronous, read-only GIO D-Bus client, with explicit native ownership.

Shared by diagnostics and the tray's native bindings. Client calls do not
auto-start services; tray service registration is implemented in tray.py.
"""

import ctypes as C
from ctypes.util import find_library
import re


class BusError(RuntimeError):
    pass


class GError(C.Structure):
    _fields_ = [('domain', C.c_uint32), ('code', C.c_int), ('message', C.c_char_p)]


class Bus:
    def __init__(self, system=False, connect=True):
        self.connection = None
        try:
            self.gio = C.CDLL(find_library('gio-2.0') or 'libgio-2.0.so.0')
            self.glib = C.CDLL(find_library('glib-2.0') or 'libglib-2.0.so.0')
            self.obj = C.CDLL(find_library('gobject-2.0') or 'libgobject-2.0.so.0')
        except OSError as error:
            raise BusError(str(error)) from error
        self._bind(self.gio, 'g_bus_get_sync', C.c_void_p, [C.c_int, C.c_void_p, C.POINTER(C.POINTER(GError))])
        self._bind(self.gio, 'g_dbus_connection_call_sync', C.c_void_p,
                   [C.c_void_p, C.c_char_p, C.c_char_p, C.c_char_p, C.c_char_p,
                    C.c_void_p, C.c_void_p, C.c_int, C.c_int, C.c_void_p, C.POINTER(C.POINTER(GError))])
        self._bind(self.glib, 'g_variant_get_type_string', C.c_char_p, [C.c_void_p])
        self._bind(self.glib, 'g_variant_get_string', C.c_char_p, [C.c_void_p, C.POINTER(C.c_size_t)])
        self._bind(self.glib, 'g_variant_n_children', C.c_size_t, [C.c_void_p])
        self._bind(self.glib, 'g_variant_get_child_value', C.c_void_p, [C.c_void_p, C.c_size_t])
        self._bind(self.glib, 'g_variant_parse', C.c_void_p,
                   [C.c_void_p, C.c_char_p, C.c_void_p, C.c_void_p, C.POINTER(C.POINTER(GError))])
        self._bind(self.glib, 'g_variant_ref_sink', C.c_void_p, [C.c_void_p])
        self._bind(self.glib, 'g_variant_unref', None, [C.c_void_p])
        self._bind(self.glib, 'g_error_free', None, [C.POINTER(GError)])
        self._bind(self.obj, 'g_object_unref', None, [C.c_void_p])
        for suffix, typ in [('boolean', C.c_int), ('byte', C.c_ubyte), ('int16', C.c_int16),
                            ('uint16', C.c_uint16), ('int32', C.c_int32), ('uint32', C.c_uint32),
                            ('int64', C.c_int64), ('uint64', C.c_uint64), ('double', C.c_double)]:
            self._bind(self.glib, 'g_variant_get_' + suffix, typ, [C.c_void_p])
        if connect:
            error = C.POINTER(GError)()
            self.connection = self.gio.g_bus_get_sync(1 if system else 2, None, C.byref(error))
            if not self.connection:
                self._raise(error)

    @staticmethod
    def _bind(lib, name, result, args):
        function = getattr(lib, name)
        function.restype, function.argtypes = result, args

    def _raise(self, error):
        message = error.contents.message.decode('utf-8', 'replace') if error else 'D-Bus operation failed'
        if error:
            self.glib.g_error_free(error)
        raise BusError(message)

    def _decode(self, variant):
        kind = self.glib.g_variant_get_type_string(variant).decode('ascii')
        if kind in ('s', 'o', 'g'):
            return self.glib.g_variant_get_string(variant, None).decode('utf-8', 'replace')
        numeric = {'b': 'boolean', 'y': 'byte', 'n': 'int16', 'q': 'uint16',
                   'i': 'int32', 'u': 'uint32', 'x': 'int64', 't': 'uint64', 'd': 'double'}
        if kind in numeric:
            value = getattr(self.glib, 'g_variant_get_' + numeric[kind])(variant)
            return bool(value) if kind == 'b' else value
        children = []
        for index in range(self.glib.g_variant_n_children(variant)):
            child = self.glib.g_variant_get_child_value(variant, index)
            try:
                children.append(self._decode(child))
            finally:
                self.glib.g_variant_unref(child)
        if kind == 'v':
            return children[0]
        if kind.startswith('a{'):
            return dict(children)
        return children

    def call(self, name, path, interface, method, arguments=None):
        parameters = None
        error = C.POINTER(GError)()
        if arguments is not None:
            parameters = self.glib.g_variant_parse(None, arguments.encode(), None, None, C.byref(error))
            if not parameters:
                self._raise(error)
            self.glib.g_variant_ref_sink(parameters)
        try:
            result = self.gio.g_dbus_connection_call_sync(
                self.connection, name.encode(), path.encode(), interface.encode(), method.encode(),
                parameters, None, 1, 1500, None, C.byref(error))  # NO_AUTO_START
            if not result:
                self._raise(error)
            try:
                return self._decode(result)
            finally:
                self.glib.g_variant_unref(result)
        finally:
            if parameters:
                self.glib.g_variant_unref(parameters)

    def has_owner(self, name):
        # This helper only accepts bus names, never arbitrary GVariant text.
        if not re.fullmatch(r'(?:[A-Za-z_-][A-Za-z0-9_-]*|:[0-9]+)(?:\.[A-Za-z0-9_-]+)+', name):
            raise ValueError('invalid bus name')
        return self.call('org.freedesktop.DBus', '/org/freedesktop/DBus',
                         'org.freedesktop.DBus', 'NameHasOwner', f"('{name}',)")[0]

    def close(self):
        if self.connection:
            self.obj.g_object_unref(self.connection)
            self.connection = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


def upower_devices():
    with Bus(system=True) as bus:
        if not bus.has_owner('org.freedesktop.UPower'):
            return {'status': 'not_running', 'devices': []}
        paths = bus.call('org.freedesktop.UPower', '/org/freedesktop/UPower',
                         'org.freedesktop.UPower', 'EnumerateDevices')[0]
        devices = []
        for path in paths:
            properties = bus.call('org.freedesktop.UPower', path, 'org.freedesktop.DBus.Properties',
                                  'GetAll', "('org.freedesktop.UPower.Device',)")[0]
            # No addresses, serials or unrelated usage history are retained.
            keep = ('NativePath', 'Model', 'Type', 'IsPresent', 'Percentage',
                    'BatteryLevel', 'State', 'UpdateTime', 'PowerSupply')
            devices.append({'path': path, **{key: properties[key] for key in keep if key in properties}})
        return {'status': 'ok', 'devices': devices}
