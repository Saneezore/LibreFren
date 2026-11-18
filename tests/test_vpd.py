import hashlib
import json
from pathlib import Path
import struct
import tempfile
import unittest

from librefren.layouts import compare_images, format_report
from librefren.safety import Refusal, flash_gate
from librefren.vpd import INFO_MAGIC, decode_records, inspect_region
from test_layouts import fmap_image


def encode_length(value):
    parts = [value & 127]
    while value > 127:
        value >>= 7
        parts.insert(0, (value & 127) | 128)
    return bytes(parts)


def record(key, value):
    return b'\x01' + encode_length(len(key)) + key + encode_length(len(value)) + value


def region(payload, offset=0, size=4096):
    data = bytearray(b'\xff' * size)
    header = INFO_MAGIC + struct.pack('<I', len(payload))
    data[offset:offset + len(header + payload)] = header + payload
    return data


class VpdTests(unittest.TestCase):
    def test_both_documented_header_positions_and_binary_values(self):
        value = bytes(range(256)) * 3
        payload = record(b'calibration', value) + record(b'empty', b'') + b'\x00'
        for offset in (0, 0x600):
            parsed = inspect_region(memoryview(region(payload, offset)))
            self.assertEqual(parsed['header_offset'], offset)
            self.assertEqual(parsed['records']['calibration'], {'bytes': len(value), 'sha256': hashlib.sha256(value).hexdigest()})
            self.assertFalse(parsed['flash_approved'])

    def test_long_length_and_implicit_termination(self):
        value = b'x' * 65793
        parsed = decode_records(record(b'any', value) + b'\xff')
        self.assertEqual(parsed['records']['any']['bytes'], len(value))
        self.assertEqual(parsed['terminator'], 255)

    def test_bounds_overflow_duplicates_and_unsupported_keys(self):
        malformed = [b'', b'\x01', b'\x01\x81', b'\x01\x80\x01a\x00\x00',
                     b'\x01' + b'\xff' * 6, b'\x01\x7fa\x00', b'\xfe\x00\x00\x00',
                     record(b'a', b'1') * 2 + b'\x00', record(b'bad\nname', b'1') + b'\x00',
                     record(b'', b'1') + b'\x00', record(b'a', b'1'),
                     record(b'a', b'1') + b'\x00hidden', b'\x02\x00']
        for data in malformed:
            with self.subTest(data=data[:30]), self.assertRaises(Refusal):
                decode_records(data)

    def test_declared_size_missing_header_and_ambiguity(self):
        good = region(record(b'a', b'b') + b'\x00')
        huge = bytearray(good)
        struct.pack_into('<I', huge, 12, 2**32 - 1)
        ambiguous = bytearray(good)
        ambiguous[0x600:0x610] = INFO_MAGIC + struct.pack('<I', 1)
        for data in (b'\xff' * 4096, good[:15], huge, ambiguous):
            with self.assertRaises(Refusal):
                inspect_region(data)

    def test_record_limit_and_empty_store(self):
        payload = b''.join(record(f'key{i}'.encode(), b'x') for i in range(2049)) + b'\x00'
        with self.assertRaises(Refusal):
            decode_records(payload)
        self.assertTrue(inspect_region(region(b'\x00'))['empty'])

    def compare(self, old, new):
        backup, candidate = fmap_image(), fmap_image()
        backup[4096:8192], candidate[4096:8192] = old, new
        with tempfile.TemporaryDirectory() as temporary:
            a, b = Path(temporary) / 'backup', Path(temporary) / 'candidate'
            a.write_bytes(backup)
            b.write_bytes(candidate)
            result = compare_images(a, b, 'chromebook')
            self.assertEqual(a.read_bytes(), backup)
            self.assertEqual(b.read_bytes(), candidate)
        self.assertFalse(flash_gate({}, result)['allowed'])
        return result

    def test_missing_changed_added_records_without_leaking_values(self):
        old = record(b'serial_number', b'PRIVATE-SERIAL-EXAMPLE') + record(b'ethernet_mac', b'PRIVATE-MAC') + b'\x00'
        new = record(b'serial_number', b'DIFFERENT-SERIAL') + record(b'calibration', b'PRIVATE-CALIBRATION') + b'\x00'
        result = self.compare(region(old), region(new))
        states = {r['key']: r['status'] for r in result['vpd_records']}
        self.assertEqual(states, {'serial_number': 'changed', 'ethernet_mac': 'missing', 'calibration': 'added'})
        serialized = json.dumps(result) + format_report(result)
        for secret in ('PRIVATE-SERIAL-EXAMPLE', 'PRIVATE-MAC', 'DIFFERENT-SERIAL', 'PRIVATE-CALIBRATION'):
            self.assertNotIn(secret, serialized)
        self.assertIn('serial_number: changed', format_report(result))

    def test_padding_change_does_not_claim_record_change_or_flash_approval(self):
        old = region(record(b'serial_number', b'SAME') + b'\x00')
        new = bytearray(old)
        new[-1] = 0
        result = self.compare(old, new)
        self.assertEqual(result['vpd_records'][0]['status'], 'unchanged')
        self.assertFalse(next(r for r in result['regions'] if r['region'] == 'RO_VPD')['same_content'])
        self.assertFalse(result['flash_approved'])


if __name__ == '__main__':
    unittest.main()
