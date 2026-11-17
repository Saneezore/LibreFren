import hashlib
from pathlib import Path
import struct
import tempfile
import unittest

from librefren.layouts import FMAP_AREA, FMAP_HEADER, compare_images, format_report, parse_fmap, parse_ifd_common, read_image
from librefren.safety import Refusal, flash_gate


def fmap_image(areas=None, size=65536, offset=256, base=0, minor=1):
    areas = areas or [('FMAP', 256, 2048, 0), ('RO_SECTION', 0, 32768, 0),
                      ('RO_VPD', 4096, 4096, 8), ('GBB', 12288, 4096, 0),
                      ('COREBOOT', 32768, 32768, 0)]
    data = bytearray(b'\xaa' * size)
    header = FMAP_HEADER.pack(b'__FMAP__', 1, minor, base, size, b'FLASH', len(areas))
    body = b''.join(FMAP_AREA.pack(start, length, name.encode(), flags) for name, start, length, flags in areas)
    data[offset:offset + len(header + body)] = header + body
    return data


def ifd_image(gbe_size=8192, me_fill=0x55, signature_offset=16):
    size = 4 * 1024**2
    data = bytearray(b'\xaa' * size)
    struct.pack_into('<III', data, signature_offset, 0x0ff0a55a, (3 << 24) | (4 << 16) | 3, (16 << 16) | 8)
    regions = [(0, 4096), (1024**2, size), (4096 + gbe_size, 1024**2), (4096, 4096 + gbe_size), None]
    for i, region in enumerate(regions):
        raw = 0x7fff if region is None else ((region[1] - 1) // 4096 << 16) | (region[0] // 4096)
        struct.pack_into('<I', data, 64 + 4 * i, raw)
    data[4096 + gbe_size:1024**2] = bytes([me_fill]) * (1024**2 - 4096 - gbe_size)
    return data


class LayoutTests(unittest.TestCase):
    def test_fmap_nested_regions_and_preserve_flag(self):
        result = parse_fmap(fmap_image())
        self.assertEqual(result['areas']['RO_VPD']['offset'], 4096)
        self.assertEqual(result['areas']['RO_VPD']['flags'], 8)
        self.assertEqual(len(result['areas']['RO_VPD']['sha256']), 64)

    def test_code_signature_is_not_mistaken_for_second_table(self):
        data = fmap_image()
        data[-64:-56] = b'__FMAP__'
        self.assertEqual(parse_fmap(data)['ignored_signature_candidates'], 1)

    def test_multiple_valid_maps_are_refused(self):
        data = fmap_image()
        table = data[256:256 + FMAP_HEADER.size + 5 * FMAP_AREA.size]
        data[1024:1024 + len(table)] = table
        with self.assertRaisesRegex(Refusal, 'Multiple valid'):
            parse_fmap(data)

    def test_fmap_malformed_geometry_and_metadata(self):
        variants = [
            [('FMAP', 256, 2048, 0), ('A', 5000, 8000, 0), ('B', 10000, 8000, 0)],
            [('FMAP', 256, 2048, 0), ('A', 5000, 8000, 0), ('A', 20000, 8000, 0)],
            [('FMAP', 256, 2048, 0), ('A', 60000, 8000, 0)],
            [('FMAP', 256, 2048, 0), ('A', 5000, 0, 0)],
            [('FMAP', 256, 2048, 0), ('A', 5000, 4096, 16)],
            [('FMAP', 4096, 2048, 0)],
            [('FMAP', 256, 2048, 0), ('A' * 32, 5000, 4096, 0)],
        ]
        for areas in variants:
            with self.subTest(areas=areas), self.assertRaises(Refusal):
                parse_fmap(fmap_image(areas))
        for data in (fmap_image(minor=2), fmap_image()[:-1], fmap_image(base=2**64 - 1)):
            with self.assertRaises(Refusal):
                parse_fmap(data)

    def test_fmap_repeated_nested_ranges_exceed_budget(self):
        areas = [('FMAP', 256, 2048, 0)] + [(f'FULL{i}', 0, 65536, 0) for i in range(9)]
        with self.assertRaises(Refusal):
            parse_fmap(fmap_image(areas))

    def test_ifd_common_ranges_and_disabled_region(self):
        for offset in (0, 16):
            with self.subTest(offset=offset):
                result = parse_ifd_common(ifd_image(signature_offset=offset))
                self.assertEqual(result['areas']['gbe']['size'], 8192)
                self.assertNotIn('platform_data', result['areas'])
                self.assertIn('NOT validated', result['coverage'])

    def test_ifd_refuses_out_of_bounds_overlap_and_bad_pointer(self):
        for register, raw in ((1, 0xffff0100), (2, 0x00ff0000), (0, 0x00010000)):
            data = ifd_image()
            struct.pack_into('<I', data, 64 + 4 * register, raw)
            with self.subTest(register=register), self.assertRaises(Refusal):
                parse_ifd_common(data)
        data = ifd_image()
        struct.pack_into('<I', data, 20, 0)
        with self.assertRaises(Refusal):
            parse_ifd_common(data)

    def compare(self, backup, candidate, context):
        with tempfile.TemporaryDirectory() as directory:
            a, b = Path(directory) / 'backup', Path(directory) / 'candidate'
            a.write_bytes(backup)
            b.write_bytes(candidate)
            report = compare_images(a, b, context)
            self.assertEqual(a.read_bytes(), backup)
            self.assertEqual(b.read_bytes(), candidate)
            self.assertFalse(report['flash_approved'])
            self.assertFalse(flash_gate({}, report)['allowed'])
            self.assertIn('Read-only comparison', format_report(report))
            return report

    def test_gbe_growth_overwrites_old_me_boundary(self):
        report = self.compare(ifd_image(), ifd_image(gbe_size=16384), 'rboot')
        self.assertTrue(any('GbE overlaps' in item for item in report['blockers']))
        gbe = next(r for r in report['regions'] if r['region'] == 'gbe')
        self.assertFalse(gbe['same_geometry'])

    def test_omitted_me_is_not_treated_as_ready_full_rom(self):
        report = self.compare(ifd_image(), ifd_image(me_fill=255), 'rboot')
        self.assertTrue(any('IFD me: bytes differ' in item for item in report['blockers']))
        self.assertTrue(any('candidate contains only 0xff' in item for item in report['blockers']))

    def test_growing_bios_into_old_me_is_reported(self):
        candidate = ifd_image()
        # Move the BIOS start down one page and end the candidate ME before it.
        struct.pack_into('<I', candidate, 68, 0x03ff00ff)
        struct.pack_into('<I', candidate, 72, 0x00fe0003)
        report = self.compare(ifd_image(), candidate, 'rboot')
        self.assertTrue(any('BIOS overlaps the backup ME' in item for item in report['blockers']))

    def test_changed_vpd_and_gbb_need_manual_preservation(self):
        backup = fmap_image()
        candidate = bytearray(backup)
        candidate[4096:8192] = b'\xff' * 4096
        candidate[12288] ^= 1
        report = self.compare(backup, candidate, 'chromebook')
        for name in ('RO_VPD', 'GBB'):
            self.assertTrue(any(f'FMAP {name}: bytes differ' in b for b in report['blockers']))

    def test_missing_vpd_is_explicit_and_identical_images_never_approve(self):
        candidate = fmap_image([('FMAP', 256, 2048, 0), ('COREBOOT', 32768, 32768, 0)])
        report = self.compare(fmap_image(), candidate, 'chromebook')
        self.assertTrue(any('RO_VPD is absent' in b for b in report['blockers']))
        same = self.compare(fmap_image(), fmap_image(), 'chromebook')
        self.assertTrue(same['blockers'])
        self.assertEqual(same['backup']['sha256'], same['candidate']['sha256'])

    def test_file_inputs_are_bounded_regular_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            file = root / 'valid'
            file.write_bytes(fmap_image())
            link = root / 'link'
            link.symlink_to(file)
            with self.assertRaises(OSError):
                read_image(link)
            tiny = root / 'tiny'
            tiny.write_bytes(b'tiny')
            with self.assertRaises(Refusal):
                read_image(tiny)
            self.assertEqual(hashlib.sha256(read_image(file)).hexdigest(), hashlib.sha256(file.read_bytes()).hexdigest())

    def test_matching_images_cannot_hide_wrong_target_capacity(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'image'
            path.write_bytes(fmap_image())
            result = compare_images(path, path, 'general', expected_size=131072)
            self.assertEqual(sum('selected target capacity' in b for b in result['blockers']), 2)
            self.assertFalse(result['flash_approved'])


if __name__ == '__main__':
    unittest.main()
