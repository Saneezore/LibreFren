"""Remote provenance, dispatch ambiguity and archive quarantine boundaries."""
import hashlib
import json
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import Mock, patch
import zipfile

from librefren import coreboot, remote
from librefren.safety import Refusal

TARGET = 'BOARD_EMULATION_QEMU_X86_I440FX'
CONFIG = f'''CONFIG_VENDOR_EMULATION=y
CONFIG_{TARGET}=y
CONFIG_MAINBOARD_DIR="emulation/qemu-i440fx"
CONFIG_ARCH_X86=y
CONFIG_ROM_SIZE=0x1000
CONFIG_PAYLOAD_SEABIOS=y
'''.encode()
IMAGE = bytes(range(256)) * 16


class RemoteTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.request = dict(schema=1, repository='example/LibreFren', branch='main', head_sha='a' * 40,
                            workflow_id=123, target=TARGET, allow_blobs=False, request_id='b' * 32,
                            coreboot_revision=json.loads((coreboot.DATA / 'revisions.json').read_text())['coreboot'],
                            flash_approved=False, status='dispatched')
        self.run = dict(id=456, head_sha='a' * 40, event='workflow_dispatch', workflow_id=123,
                        display_title='LibreFren coreboot ' + 'b' * 32,
                        repository={'full_name': 'example/LibreFren'}, status='completed', conclusion='success')
        self.receipt = dict(schema=1, repository=self.request['repository'], run_id='456',
                            head_sha='a' * 40, request_id='b' * 32, target=TARGET,
                            revision=self.request['coreboot_revision'], allow_blobs=False,
                            flash_approved=False, status='remote-image-unqualified',
                            sha256=hashlib.sha256(IMAGE).hexdigest(), size=len(IMAGE),
                            config_sha256=hashlib.sha256(CONFIG).hexdigest())
        self.path = self.root / 'request.json'
        remote.save(self.request, self.path)

    def bundle(self, receipt=None, config=CONFIG, image=IMAGE, extra=None):
        path = self.root / 'bundle.zip'
        with zipfile.ZipFile(path, 'w', compression=zipfile.ZIP_DEFLATED) as z:
            z.writestr('receipt.json', json.dumps(receipt or self.receipt))
            z.writestr('generated.config', config)
            z.writestr('UNQUALIFIED-coreboot.rom', image)
            if extra:
                z.writestr(*extra)
        return path

    def test_bundle_is_verified_but_never_flash_approved(self):
        files, result = remote.inspect_bundle(self.bundle(), self.request, 456)
        self.assertEqual(files['UNQUALIFIED-coreboot.rom'], IMAGE)
        self.assertIs(result['flash_approved'], False)
        self.assertFalse((self.root / 'UNQUALIFIED-coreboot.rom').exists())

    def test_mismatched_provenance_is_rejected(self):
        changes = dict(target='BOARD_EMULATION_QEMU_X86_Q35', revision='d' * 40,
                       head_sha='c' * 40, request_id='f' * 32, run_id='789',
                       repository='other/LibreFren', allow_blobs=True, flash_approved=True,
                       status='approved', schema=True)
        for key, value in changes.items():
            with self.subTest(key=key), self.assertRaises(Refusal):
                remote.inspect_bundle(self.bundle(dict(self.receipt, **{key: value})), self.request, 456)

    def test_changed_image_or_config_is_rejected(self):
        for kw in ({'image': b'x' * 4096}, {'config': CONFIG + b'# changed\n'}):
            with self.subTest(kw=kw), self.assertRaises(Refusal):
                remote.inspect_bundle(self.bundle(**kw), self.request, 456)

    def test_even_hash_consistent_wrong_configuration_is_rejected(self):
        for config in (CONFIG.replace(TARGET.encode(), b'BOARD_EMULATION_QEMU_X86_Q35'),
                       CONFIG.replace(b'emulation/qemu-i440fx', b'emulation/qemu-q35'),
                       CONFIG + b'CONFIG_USE_BLOBS=y\n',
                       CONFIG.replace(b'0x1000', b'0x2000'),
                       CONFIG + b'CONFIG_ANY_TOOLCHAIN=y\n'):
            receipt = dict(self.receipt, config_sha256=hashlib.sha256(config).hexdigest())
            with self.subTest(config=config), self.assertRaises(Refusal):
                remote.inspect_bundle(self.bundle(receipt, config=config), self.request, 456)

    def test_extra_paths_and_duplicates_are_rejected(self):
        for name in ('../escape', '/tmp/escape', 'extra.json'):
            with self.subTest(name=name), self.assertRaises(Refusal):
                remote.inspect_bundle(self.bundle(extra=(name, 'bad')), self.request, 456)

    def test_symlink_archive_entry_is_rejected(self):
        path = self.bundle()
        # Rebuild with exactly the same names, but make the ROM a symbolic link.
        with zipfile.ZipFile(path, 'w') as z:
            z.writestr('receipt.json', json.dumps(self.receipt))
            z.writestr('generated.config', CONFIG)
            item = zipfile.ZipInfo('UNQUALIFIED-coreboot.rom')
            item.create_system = 3
            item.external_attr = (stat.S_IFLNK | 0o777) << 16
            z.writestr(item, 'elsewhere')
        with self.assertRaises(Refusal):
            remote.inspect_bundle(path, self.request, 456)

    def test_wrong_or_ambiguous_run_is_rejected(self):
        for field, value in [('head_sha', 'c' * 40), ('event', 'push'), ('workflow_id', 999),
                             ('display_title', 'other'), ('repository', {'full_name': 'other/repo'})]:
            with self.subTest(field=field), self.assertRaises(Refusal):
                remote.checked_run(self.request, dict(self.run, **{field: value}))
        with patch.object(remote.GitHub, 'api', return_value={'workflow_runs': [self.run, self.run]}), self.assertRaises(Refusal):
            remote.refresh(self.request, self.path)

    def test_pending_request_can_be_resumed_after_uncertain_dispatch(self):
        calls = []
        def api(_self, route, method='GET', body=None):
            calls.append((route, method, body))
            if method == 'GET':
                return {'sha': self.request['head_sha']}
            raise Refusal('Network lost after POST')
        with patch.object(remote.GitHub, 'api', api), self.assertRaises(Refusal):
            remote.dispatch(self.request, 'BUILD ON GITHUB ' + TARGET, self.root / 'requests')
        saved = remote.load_request(self.root / 'requests' / (self.request['request_id'] + '.json'))
        self.assertEqual(saved['status'], 'dispatch-pending')
        self.assertEqual(sum(method == 'POST' for _, method, _ in calls), 1)
        self.assertEqual(set(calls[-1][2]['inputs']), {'target', 'allow_blobs', 'request_id', 'expected_sha'})

    def test_changed_repository_or_cancelled_confirmation_prevents_dispatch(self):
        with patch.object(remote.GitHub, 'api', return_value={'sha': 'd' * 40}) as api:
            with self.assertRaises(Refusal):
                remote.dispatch(self.request, 'BUILD ON GITHUB ' + TARGET, self.root / 'requests')
            self.assertEqual(api.call_count, 1)
            api.reset_mock()
            with self.assertRaises(Refusal):
                remote.dispatch(self.request, '', self.root / 'requests')
            api.assert_not_called()

    def test_only_successful_matching_run_can_download(self):
        self.request['run_id'] = 456
        with patch.object(remote.GitHub, 'api', return_value=dict(self.run, conclusion='failure')) as api:
            with self.assertRaises(Refusal):
                remote.download(self.request, self.path, self.root / 'downloads')
            self.assertEqual(api.call_count, 1)
            self.assertFalse((self.root / 'downloads').exists())

    def test_download_checks_artifact_digest_and_imports_only_matching_bundle(self):
        archive = self.bundle().read_bytes()
        artifact = dict(id=789, name='coreboot-candidate-' + self.request['request_id'],
                        expired=False, size_in_bytes=len(archive), digest='sha256:' + hashlib.sha256(archive).hexdigest())
        self.request['run_id'] = 456
        def api(_self, route, method='GET', body=None, destination=None):
            if destination:
                Path(destination).write_bytes(archive)
                return
            return {'artifacts': [artifact]} if route.endswith('/artifacts') else self.run
        with patch.object(remote.GitHub, 'api', api):
            result = remote.download(self.request, self.path, self.root / 'downloads')
            self.assertEqual(Path(result['path']).read_bytes(), IMAGE)
            self.assertIs(result['flash_approved'], False)
            artifact['digest'] = 'sha256:' + '0' * 64
            with self.assertRaisesRegex(Refusal, 'digest'):
                remote.download(self.request, self.path, self.root / 'downloads')

    def test_expired_and_oversized_artifacts_are_not_downloaded(self):
        self.request['run_id'] = 456
        for extra in ({'expired': True}, {'size_in_bytes': remote.MAX_ARCHIVE + 1}, {'digest': None}):
            artifact = dict(id=789, name='coreboot-candidate-' + self.request['request_id'],
                            expired=False, size_in_bytes=99, digest='sha256:' + '0' * 64)
            artifact.update(extra)
            with patch.object(remote.GitHub, 'api', side_effect=[self.run, {'artifacts': [artifact]}]) as api:
                with self.subTest(extra=extra), self.assertRaises(Refusal):
                    remote.download(self.request, self.path, self.root / 'downloads')
                self.assertEqual(api.call_count, 2)

    def test_cancellation_requires_exact_run_confirmation(self):
        self.request['run_id'] = 456
        with patch.object(remote.GitHub, 'api', return_value=dict(self.run, status='in_progress')) as api:
            with self.assertRaises(Refusal):
                remote.cancel(self.request, self.path, 'CANCEL 999')
            self.assertEqual(api.call_count, 1)
            remote.cancel(self.request, self.path, 'CANCEL 456')
            self.assertEqual(api.call_args.args, ('/actions/runs/456/cancel', 'POST'))

    def test_repository_paths_and_obsolete_requests_are_rejected(self):
        for name in ('https://github.com/user/repo', 'user/../evil', '-option/name', 'user/repo?token=x'):
            with self.subTest(name=name), self.assertRaises(Refusal):
                remote.repository(name)
        self.request['coreboot_revision'] = '0' * 40
        remote.save(self.request, self.path)
        with self.assertRaises(Refusal):
            remote.load_request(self.path)

    def test_github_diagnostics_are_not_exposed(self):
        with patch.object(remote.shutil, 'which', return_value='/usr/bin/gh'), \
                patch.object(remote.subprocess, 'Popen') as popen:
            process = popen.return_value
            process.poll.return_value = 1
            process.returncode = 1
            with self.assertRaisesRegex(Refusal, 'authentication'):
                remote.GitHub('user/repo').api('/actions/runs')
            self.assertEqual(popen.call_args.kwargs['stderr'], remote.subprocess.DEVNULL)
            self.assertNotIn('shell', popen.call_args.kwargs)


if __name__ == '__main__':
    unittest.main()
