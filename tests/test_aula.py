import unittest
import os
import socket
from contextlib import nullcontext
from unittest.mock import patch

from keyboard_power.aula import DESCRIPTOR, battery_request, parse_reply, query, select_interface


class AulaTests(unittest.TestCase):
    def test_request_matches_public_capture_vector(self):
        self.assertEqual(battery_request().hex(), '2001000000000000000000000000000000000000000000000000000000000021')

    def test_reply_requires_length_header_range_and_checksum(self):
        reply = bytes.fromhex('2001006400000000000000000000000000000000000000000000000000000085')
        self.assertEqual(parse_reply(reply), 100)
        for bad in (reply[:-1], b'\x00' + reply, reply[:-1] + b'\x00',
                    bytes([0x20, 1, 0, 101]) + bytes(27) + bytes([0x86]),
                    bytes([0x21, 0, 0, 100]) + bytes(27) + bytes([0x85])):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                parse_reply(bad)

    def test_identity_requires_exact_descriptor_and_unique_candidate(self):
        device = dict(vid='05AC', pid='024F', product='2.4G Dongle', interface='03',
                      descriptor_hex=DESCRIPTOR.hex(), bcd_device='0121')
        self.assertEqual(select_interface([device]), device)
        for candidates in ([], [device, device], [{**device, 'interface': '04'}],
                           [{**device, 'product': 'Other Keyboard'}],
                           [{**device, 'descriptor_hex': DESCRIPTOR.hex().replace('9520', '9540')} ]):
            with self.subTest(candidates=candidates), self.assertRaises(ValueError):
                select_interface(candidates)

    def test_transport_writes_one_unnumbered_request_and_closes_fd(self):
        client, server = socket.socketpair(type=socket.SOCK_SEQPACKET)
        fd = os.dup(client.fileno())
        device = dict(vid='05AC', pid='024F', product='2.4G Dongle', interface='03',
                      descriptor_hex=DESCRIPTOR.hex(), bcd_device='0121', node='/dev/test')
        # Queue an unrelated packet, then the known-good public reply vector.
        server.send(bytes(32))
        server.send(bytes.fromhex('2001006400000000000000000000000000000000000000000000000000000085'))
        try:
            with patch('keyboard_power.aula.os.open', return_value=fd), patch('keyboard_power.aula.verify_opened_identity'), patch('keyboard_power.transport.transaction', return_value=nullcontext()):
                result = query([device], timeout=0.1)
            self.assertEqual(result['percent'], 100)
            self.assertEqual(result['status'], 'unverified_sample')
            self.assertEqual(server.recv(100), b'\x00' + battery_request())
            with self.assertRaises(OSError):
                os.fstat(fd)
        finally:
            client.close()
            server.close()

    def test_timeout_and_cancellation_close_transport(self):
        device = dict(vid='05AC', pid='024F', product='2.4G Dongle', interface='03',
                      descriptor_hex=DESCRIPTOR.hex(), bcd_device='0121', node='/dev/test')
        for cancel in (False, True):
            client, server = socket.socketpair(type=socket.SOCK_SEQPACKET)
            fd = os.dup(client.fileno())
            read_fd, write_fd = os.pipe()
            try:
                if cancel:
                    os.write(write_fd, b'x')
                with patch('keyboard_power.aula.os.open', return_value=fd), patch('keyboard_power.aula.verify_opened_identity'), patch('keyboard_power.transport.transaction', return_value=nullcontext()):
                    with self.assertRaises(InterruptedError if cancel else TimeoutError):
                        query([device], timeout=0.1, cancel_fd=read_fd)
                with self.assertRaises(OSError):
                    os.fstat(fd)
                server.setblocking(False)
                if cancel:
                    with self.assertRaises(BlockingIOError):
                        server.recv(100)
                else:
                    self.assertEqual(server.recv(100), b'\x00' + battery_request())
            finally:
                client.close()
                server.close()
                os.close(read_fd)
                os.close(write_fd)
