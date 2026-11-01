import ctypes as C
import unittest

from keyboard_power.bus import Bus, BusError, GError


class NativeVariantTests(unittest.TestCase):
    def test_native_arrays_dictionaries_variants_and_ownership(self):
        try:
            bus = Bus(connect=False)
        except BusError as error:
            self.skipTest(str(error))
        examples = [
            ("(['org.test.One', 'org.test.Two'],)", [['org.test.One', 'org.test.Two']]),
            ("(true, byte 255, int16 -3, uint16 65000, int32 -5, uint32 42, int64 -9, uint64 99, 4.5)",
             [True, 255, -3, 65000, -5, 42, -9, 99, 4.5]),
            ("({'Percentage': <double 62.5>, 'IsPresent': <true>, 'UpdateTime': <uint64 100>},)",
             [{'Percentage': 62.5, 'IsPresent': True, 'UpdateTime': 100}]),
            ("(@ao [],)", [[]]),
            ("(objectpath '/org/freedesktop/UPower',)", ['/org/freedesktop/UPower']),
        ]
        with bus:
            for text, expected in examples:
                with self.subTest(text=text):
                    error = C.POINTER(GError)()
                    variant = bus.glib.g_variant_parse(None, text.encode(), None, None, C.byref(error))
                    if not variant:
                        bus._raise(error)
                    bus.glib.g_variant_ref_sink(variant)
                    try:
                        self.assertEqual(bus._decode(variant), expected)
                    finally:
                        bus.glib.g_variant_unref(variant)
