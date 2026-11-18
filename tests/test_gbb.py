import hashlib
import json
from pathlib import Path
import struct
import tempfile
import unittest

from librefren.gbb import inspect_region
from librefren.layouts import compare_images, format_report
from librefren.safety import Refusal, flash_gate
from test_layouts import fmap_image


def gbb_region(hwid=b'TEST DEVICE 1234', flags=0):
    data = bytearray(b'\xff' * 4096)
    # Explicit offsets from the vboot 1.2 wire format, independent of parser struct.
    data[:128] = b'\x00' * 128
    data[:4] = b'$GBB'
    struct.pack_into('<HHII', data, 4, 1, 2, 128, flags)
    struct.pack_into('<8I', data, 16, 128, 64, 192, 32, 224, 0, 224, 32)
    data[48:80] = hashlib.sha256(hwid).digest()
    data[128:192] = hwid + b'\x00' * (64 - len(hwid))
    data[192:224] = bytes(range(32))
    data[224:256] = bytes(range(32, 64))
    return data


class GbbTests(unittest.TestCase):
    def test_hwid_digest_and_component_hashes_without_raw_identity(self):
        data = gbb_region()
        result = inspect_region(memoryview(data))
        self.assertTrue(result['hwid']['stored_digest_matches'])
        self.assertEqual(result['hwid']['sha256'], hashlib.sha256(b'TEST DEVICE 1234').hexdigest())
        self.assertEqual(result['components']['root_key']['sha256'], hashlib.sha256(bytes(range(32))).hexdigest())
        self.assertNotIn('TEST DEVICE 1234', json.dumps(result))
        self.assertFalse(result['flash_approved'])

    def test_bad_checksum_and_nonzero_reserved_data_are_refused(self):
        for offset in (48, 80, 128):
            data = gbb_region()
            data[offset] ^= 1
            with self.subTest(offset=offset), self.assertRaises(Refusal):
                inspect_region(data)

    def test_version_and_region_bounds(self):
        for offset, fmt, value in ((6, '<H', 1), (4, '<H', 2), (8, '<I', 64),
                                   (16, '<I', 2**32 - 1), (24, '<I', 64), (28, '<I', 2**32 - 1)):
            data = gbb_region()
            struct.pack_into(fmt, data, offset, value)
            with self.subTest(offset=offset), self.assertRaises(Refusal):
                inspect_region(data)
        with self.assertRaises(Refusal):
            inspect_region(gbb_region()[:127])

    def test_overlapping_components_and_missing_hwid(self):
        for offset, value in ((24, 128), (20, 0), (20, 4097)):
            data = gbb_region()
            struct.pack_into('<I', data, offset, value)
            with self.assertRaises(Refusal):
                inspect_region(data)

    def test_ambiguous_hwid_encoding_is_refused(self):
        for raw in (b'x' * 64, b'\x00' * 64, b'ABC\x00hidden' + b'\x00' * 54,
                    b'ABC\n\x00' + b'\x00' * 59):
            data = gbb_region()
            data[128:192] = raw
            with self.assertRaises(Refusal):
                inspect_region(data)

    def compare(self, old, new):
        backup, candidate = fmap_image(), fmap_image()
        backup[12288:16384], candidate[12288:16384] = old, new
        with tempfile.TemporaryDirectory() as directory:
            a, b = Path(directory) / 'backup', Path(directory) / 'candidate'
            a.write_bytes(backup)
            b.write_bytes(candidate)
            result = compare_images(a, b, 'chromebook')
            self.assertEqual(a.read_bytes(), backup)
            self.assertEqual(b.read_bytes(), candidate)
        self.assertFalse(flash_gate({}, result)['allowed'])
        return result

    def test_changed_identity_keys_and_flags_are_explicit(self):
        old, new = gbb_region(), gbb_region(b'OTHER DEVICE 5678', 1)
        new[192] ^= 1
        result = self.compare(old, new)
        fields = {r['field']: r['status'] for r in result['gbb_fields']}
        self.assertEqual(fields, {'hwid': 'changed', 'root_key': 'changed', 'flags': 'changed', 'recovery_key': 'unchanged'})
        for value in ('TEST DEVICE 1234', 'OTHER DEVICE 5678'):
            self.assertNotIn(value, json.dumps(result) + format_report(result))

    def test_corruption_remains_unresolved_and_identical_never_approves(self):
        bad = gbb_region()
        bad[48] ^= 1
        result = self.compare(gbb_region(), bad)
        self.assertTrue(any('checksum' in reason for reason in result['blockers']))
        result = self.compare(gbb_region(), gbb_region())
        self.assertTrue(all(row['status'] == 'unchanged' for row in result['gbb_fields']))
        self.assertFalse(result['flash_approved'])


if __name__ == '__main__':
    unittest.main()
