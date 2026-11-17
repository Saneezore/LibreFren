import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from librefren.prepare import checked_source, dependencies, inject
from librefren.releases import verify
from librefren.safety import Refusal
from librefren.session import Session


class ProvenanceTests(unittest.TestCase):
    def test_manual_observation_cannot_approve(self):
        with tempfile.TemporaryDirectory() as directory:
            session = Session(directory)
            session.record('manual-observation', {'note': 'backups copied'})
            session.record('manual-observation', {'note': 'voltage unresolved'})
            records = Session.inspect(session.path / 'events.jsonl')
            self.assertEqual(len(records), 2)
            self.assertTrue(all(not r['flash_approved'] for r in records))
            path = session.path / 'events.jsonl'
            path.write_text(path.read_text().replace('voltage unresolved', 'voltage verified'))
            with self.assertRaises(ValueError):
                Session.inspect(path)

    def test_rboot_cannot_invoke_libreboot_vendor_injection(self):
        with self.assertRaises(Refusal):
            inject('rboot', 'anything', '', '', 'random', 'PREPARE anything', '')

    def test_coreboot_cannot_use_unreviewed_build_executor(self):
        with self.assertRaises(Refusal):
            checked_source('coreboot', '/')

    def test_dependency_command_requires_matching_confirmation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'config/dependencies').mkdir(parents=True)
            (root / 'config/dependencies/debian').write_text('pkglist="example"')
            with patch('librefren.prepare.checked_source', return_value=root), patch('librefren.prepare.run_logged') as runner:
                with self.assertRaises(Refusal):
                    dependencies('libreboot', root, 'debian', 'yes', root / 'log')
                runner.assert_not_called()

    @unittest.skipUnless(shutil.which('gpg'), 'GPG not installed')
    def test_real_detached_signature_and_corrupted_artifact(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            home = root / 'gpg'
            home.mkdir(mode=0o700)
            command = ['gpg', '--no-options', '--homedir', str(home), '--batch', '--pinentry-mode', 'loopback', '--passphrase', '']
            generated = subprocess.run(command + ['--quick-generate-key', 'Fixture <fixture@example.invalid>', 'ed25519', 'sign', '0'], capture_output=True)
            self.assertEqual(generated.returncode, 0, generated.stderr.decode())
            listing = subprocess.check_output(command + ['--with-colons', '--list-keys'], stderr=subprocess.DEVNULL, text=True)
            fingerprint = next(line.split(':')[9] for line in listing.splitlines() if line.startswith('fpr:'))
            payload = root / 'payload'
            payload.write_bytes(b'not firmware; signature test fixture')
            subprocess.run(command + ['--detach-sign', str(payload)], check=True, capture_output=True)
            key = root / 'key.asc'
            key.write_bytes(subprocess.check_output(command + ['--armor', '--export', fingerprint]))
            with patch('librefren.releases.FINGERPRINT', fingerprint):
                self.assertEqual(len(verify(payload, root / 'payload.sig', key)), 64)
                payload.write_bytes(b'corrupted fixture')
                with self.assertRaises(Refusal):
                    verify(payload, root / 'payload.sig', key)


if __name__ == '__main__':
    unittest.main()
