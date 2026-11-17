import io
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch

from librefren.prepare import stage_variant
from librefren.releases import archive_name
from librefren.safety import Refusal, digest


class StagingTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.name = 'bin/fixture/edk2_fixture_txtmode.rom'
        self.archive = self.root / archive_name('rboot', 'fixture')
        with tarfile.open(self.archive, 'w:xz') as out:
            info = tarfile.TarInfo(self.name)
            body = b'Synthetic test data only.'
            info.size = len(body)
            out.addfile(info, io.BytesIO(body))
        self.receipt = {'project': 'rboot', 'target': 'fixture', 'archive': str(self.archive),
                        'sha256': digest(self.archive), 'status': 'authenticated-download-only'}

    def test_rboot_snapshot_is_reverified_and_copy_never_approved(self):
        def check_snapshot(snapshot, signature, key):
            self.assertNotEqual(snapshot, self.archive)
            self.assertEqual(digest(snapshot), self.receipt['sha256'])
            self.assertEqual(signature, self.root / 'archive.sig')
            self.assertEqual(key, self.root / 'key.asc')
        with patch('librefren.prepare.verify', side_effect=check_snapshot) as verify:
            result = stage_variant(self.receipt, 'rboot', 'fixture', self.name, self.root / 'stage')
        verify.assert_called_once()
        self.assertEqual(result['status'], 'inspection-copy-only')
        self.assertFalse(result['flash_approved'])
        self.assertEqual(Path(result['path']).read_bytes(), b'Synthetic test data only.')
        self.assertEqual(digest(self.archive), self.receipt['sha256'])
        self.assertFalse(list((self.root / 'stage').rglob('.snapshot-*')))

    def test_changed_archive_is_refused_before_extraction(self):
        self.archive.write_bytes(b'replaced archive')
        with patch('librefren.prepare.extract_variant') as extract, self.assertRaises(Refusal):
            stage_variant(self.receipt, 'rboot', 'fixture', self.name, self.root / 'stage')
        extract.assert_not_called()

    def test_wrong_target_and_project_are_refused(self):
        for project, target in (('libreboot', 'fixture'), ('rboot', 'fixture_other')):
            with self.subTest(project=project, target=target), self.assertRaises(Refusal):
                stage_variant(self.receipt, project, target, self.name, self.root / 'stage')

    def test_signature_failure_cannot_create_rom(self):
        with patch('librefren.prepare.verify', side_effect=Refusal('Bad signature')), self.assertRaises(Refusal):
            stage_variant(self.receipt, 'rboot', 'fixture', self.name, self.root / 'stage')
        self.assertFalse(list((self.root / 'stage').rglob('*.rom')))

    def test_prepared_libreboot_hash_is_rechecked(self):
        path = self.root / archive_name('libreboot', 'fixture')
        path.write_bytes(self.archive.read_bytes())
        receipt = {'project': 'libreboot', 'target': 'fixture', 'archive': str(path),
                   'prepared_sha256': digest(path), 'status': 'upstream-preparation-completed-unqualified'}
        result = stage_variant(receipt, 'libreboot', 'fixture', self.name, self.root / 'stage')
        self.assertFalse(result['flash_approved'])
        path.write_bytes(b'changed prepared archive')
        with self.assertRaises(Refusal):
            stage_variant(receipt, 'libreboot', 'fixture', self.name, self.root / 'stage')


if __name__ == '__main__':
    unittest.main()
