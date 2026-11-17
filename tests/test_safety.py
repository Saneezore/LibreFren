import io
import json
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import patch

from librefren.releases import archive_name, check_url, verify
from librefren.safety import Refusal, archive_members, check_backups, exact_candidates, extract_variant, flash_gate, inspect_variants


class SafetyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.target = 'lenovo_thinkpad_t480s_16mb'

    def tearDown(self):
        self.tmp.cleanup()

    def tar(self, names, links=False):
        path = self.root / 'archive.tar.xz'
        with tarfile.open(path, 'w:xz') as out:
            for name, data in names:
                info = tarfile.TarInfo(name)
                info.size = len(data)
                if links:
                    info.type = tarfile.SYMTYPE
                    info.linkname = '/etc/passwd'
                out.addfile(info, io.BytesIO(data))
        return path

    def test_t480_is_not_t480s(self):
        boards = [{'names': ['ThinkPad T480'], 'id': 't480'}, {'names': ['ThinkPad T480s'], 'id': 't480s'}]
        self.assertEqual([b['id'] for b in exact_candidates({'product_version': 'ThinkPad T480s'}, boards)], ['t480s'])

    def test_unknown_and_substrings_not_matched(self):
        self.assertEqual(exact_candidates({'product_version': 'T480s'}, [{'names': ['T480'], 'id': 'x'}]), [])
        self.assertEqual(exact_candidates({'product_version': 'unknown'}, [{'names': ['unknown']}]), [])

    def test_all_metadata_cannot_unlock_flashing(self):
        self.assertFalse(flash_gate({'flash_approved': True}, {'everything': True})['allowed'])

    def test_target_name_exact(self):
        self.assertEqual(archive_name('libreboot', self.target), 'libreboot-26.11rev1_lenovo_thinkpad_t480s_16mb.tar.xz')
        with self.assertRaises(Refusal):
            archive_name('libreboot', '../t480')

    def test_every_distribution_target_has_a_distinct_download_name(self):
        boards = json.loads((Path(__file__).parents[1] / 'librefren/data/boards.json').read_text())
        for project in ('libreboot', 'rboot'):
            targets = [b['id'] for b in boards if b['project'] == project]
            names = [archive_name(project, target) for target in targets]
            self.assertEqual(len(names), len(set(names)))
            for target, name in zip(targets, names):
                self.assertEqual(name.split('_', 1)[1].removesuffix('.tar.xz'), target)

    def test_exact_identity_rule_across_complete_inventory(self):
        boards = json.loads((Path(__file__).parents[1] / 'librefren/data/boards.json').read_text())
        for name in {name for board in boards for name in board.get('names', []) if name}:
            matches = exact_candidates({'product_name': name}, boards)
            self.assertTrue(matches)
            self.assertTrue(all(name.casefold() in [n.casefold() for n in b['names']] for b in matches))
            # Invented suffixes must never match the original model name.
            self.assertFalse(exact_candidates({'product_name': name + '-UNKNOWN-REVISION'}, boards))

    def test_https_origin_only(self):
        for url in ('http://libreboot.org/a', 'https://libreboot.org.evil.example/a', 'https://user@libreboot.org/a', 'https://libreboot.org:8080/a'):
            with self.subTest(url=url), self.assertRaises(Refusal):
                check_url(url)

    def test_traversal_absolute_links_controls(self):
        for name in ('../escape', '/tmp/escape', 'bin/../../escape', 'bin/a\x1bb', 'bin\\escape'):
            with self.subTest(name=name):
                path = self.tar([(name, b'x')])
                with self.assertRaises(Refusal):
                    archive_members(path)
        with self.assertRaises(Refusal):
            archive_members(self.tar([('link', b'')], links=True))

    def test_duplicate_archive_entries(self):
        with self.assertRaises(Refusal):
            archive_members(self.tar([('a', b'x'), ('a', b'y')]))

    def test_resource_limit(self):
        with self.assertRaises(Refusal):
            archive_members(self.tar([('a', b'123')]), max_bytes=2)

    def test_wrong_target_directory(self):
        with self.assertRaises(Refusal):
            inspect_variants(self.tar([('bin/lenovo_thinkpad_t480_16mb/edk2_other.rom', b'123')]), self.target)

    def test_same_size_wrong_target_filename(self):
        path = self.tar([(f'bin/{self.target}/edk2_lenovo_thinkpad_t480_16mb_libgfxinit_corebootfb.rom', bytes(16 * 1024**2))])
        self.assertTrue(inspect_variants(path, self.target)[0]['blockers'])

    def test_current_upstream_compound_payload_names_remain_target_exact(self):
        target = 'vendor_board'
        for payload in ('uefi_edk2', 'bios_seabios', 'uefi_uboot'):
            for image_target, valid in ((target, True), ('vendor_other_board', False)):
                with self.subTest(payload=payload, image_target=image_target):
                    path = self.tar([(f'bin/{target}/{payload}_{image_target}_libgfxinit_corebootfb.rom', b'fixture')])
                    item = inspect_variants(path, target)[0]
                    self.assertEqual(item['payload'], payload)
                    self.assertEqual(not item['blockers'], valid)

    def test_scrubbed_and_wrong_size_blocked(self):
        path = self.tar([(f'bin/{self.target}/DO_NOT_FLASH_edk2_{self.target}_x.rom', b'123')])
        self.assertGreaterEqual(len(inspect_variants(path, self.target)[0]['blockers']), 2)

    def test_extract_does_not_approve_or_overwrite(self):
        target = 'test'
        name = 'bin/test/edk2_test_libgfxinit_corebootfb.rom'
        path = self.tar([(name, b'firmware fixture only')])
        result = extract_variant(path, target, name, self.root / 'selected')
        self.assertFalse(result['flash_approved'])
        with self.assertRaises(FileExistsError):
            extract_variant(path, target, name, self.root / 'selected')

    def test_backup_rejects_uniform_size_difference_and_same_file(self):
        a, b = self.root / 'a', self.root / 'b'
        a.write_bytes(b'1234'); b.write_bytes(b'1234')
        self.assertEqual(check_backups([a, b], 4)['status'], 'consistent')
        for paths, size in (([a], 4), ([a, a], 4), ([a, b], 5)):
            with self.assertRaises(Refusal):
                check_backups(paths, size)
        b.write_bytes(b'1235')
        with self.assertRaises(Refusal):
            check_backups([a, b], 4)
        a.write_bytes(b'0000'); b.write_bytes(b'0000')
        with self.assertRaises(Refusal):
            check_backups([a, b], 4)

    def test_signature_failure_and_unexpected_signer(self):
        fake = subprocess.CompletedProcess([], 0, '[GNUPG:] VALIDSIG ' + 'F' * 40 + '\n', '')
        with patch('librefren.releases.subprocess.run', return_value=fake), self.assertRaises(Refusal):
            verify(self.root / 'rom', self.root / 'sig', self.root / 'key')

    def test_review_status_is_explicit_for_all_boards(self):
        boards = json.loads((Path(__file__).parents[1] / 'librefren/data/boards.json').read_text())
        self.assertEqual({b['project'] for b in boards}, {'libreboot', 'rboot', 'coreboot'})
        self.assertTrue(all(not b['flash_approved'] for b in boards))
        self.assertEqual(len({(b['project'], b['id']) for b in boards}), len(boards))


if __name__ == '__main__':
    unittest.main()
