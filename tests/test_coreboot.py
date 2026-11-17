"""Exercise exact-board configuration, stale inputs, cancellation and build quarantine."""
import dataclasses
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from librefren import coreboot as cb
from librefren.safety import Refusal

TARGET = 'BOARD_TEST_ONE'
CONFIG = '''CONFIG_VENDOR_TEST=y
CONFIG_BOARD_TEST_ONE=y
CONFIG_MAINBOARD_DIR="test/one"
CONFIG_ARCH_X86=y
CONFIG_ROM_SIZE=0x1000
CONFIG_PAYLOAD_NONE=y
# CONFIG_USE_BLOBS is not set
'''


class CorebootTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.data = self.root / 'data'
        self.data.mkdir()
        self.data.joinpath('boards.json').write_text(json.dumps([
            {'project': 'coreboot', 'id': TARGET, 'directory': 'src/mainboard/test/one'},
            {'project': 'coreboot', 'id': 'BOARD_TEST_TWO', 'directory': 'src/mainboard/test/two'},
        ]))
        self.patch = patch.object(cb, 'DATA', self.data)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.source = self.root / 'original'
        self.source.mkdir()
        self.source.joinpath('.gitignore').write_text('.config\nbuild/\n')
        self.source.joinpath('fixture.config').write_text(CONFIG)
        vendor = self.source / 'src/mainboard/test'
        vendor.mkdir(parents=True)
        vendor.joinpath('Kconfig.name').write_text('config VENDOR_TEST\n\tbool "Test"\n')
        self.source.joinpath('Makefile').write_text('olddefconfig:\n\tcp fixture.config .config\n')
        self.git('init', '-q')
        self.git('add', '.')
        self.git('-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-qm', 'fixture')
        self.revision = self.git('rev-parse', 'HEAD')
        self.data.joinpath('revisions.json').write_text(json.dumps({'coreboot': self.revision}))

    def git(self, *args):
        return subprocess.check_output(['git', '-C', str(self.source), *args], env=cb.environment(), text=True, stderr=subprocess.PIPE).strip()

    def configure(self):
        # Fixture Makefile needs no parser generators; real integration tests use them.
        with patch.object(cb.shutil, 'which', return_value='/usr/bin/true'):
            return cb.configure(self.source, TARGET, False, 'CONFIGURE ' + TARGET, self.root / 'work')

    def audit(self, text):
        path = self.root / 'test.config'
        path.write_text(text)
        return cb.audit_config(path, TARGET, 'VENDOR_TEST', 'test/one', False)

    def test_exact_board_default_is_accepted_without_flash_approval(self):
        digest, arches, summary = self.audit(CONFIG)
        self.assertEqual(arches, ('i386',))
        self.assertEqual(summary['PAYLOAD_NONE'], 'y')
        self.assertEqual(len(digest), 64)

    def test_wrong_board_vendor_directory_and_multiple_boards_are_rejected(self):
        for text in (CONFIG.replace(TARGET, 'BOARD_TEST_TWO'),
                     CONFIG + 'CONFIG_BOARD_TEST_TWO=y\n',
                     CONFIG.replace('VENDOR_TEST', 'VENDOR_OTHER'),
                     CONFIG.replace('test/one', 'test/two')):
            with self.subTest(text=text), self.assertRaises(Refusal):
                self.audit(text)

    def test_config_cannot_inject_make_commands_or_duplicate_values(self):
        for addition in ('include /tmp/evil\n', 'CONFIG_EVIL=$(shell touch /tmp/evil)\n',
                         'CONFIG_EVIL="$(shell true)"\n', 'CONFIG_EVIL="`true`"\n',
                         'CONFIG_BOARD_TEST_ONE=y\n'):
            with self.subTest(addition=addition), self.assertRaises(Refusal):
                self.audit(CONFIG + addition)

    def test_only_upstream_board_directory_references_are_permitted(self):
        self.audit(CONFIG + 'CONFIG_CMOS_LAYOUT_FILE="src/mainboard/$(MAINBOARDDIR)/cmos.layout"\nCONFIG_NEGATIVE=-1\n')
        for expression in ('${MAINBOARDDIR}', '$(HOME)', '$(shell $(MAINBOARDDIR))'):
            with self.assertRaises(Refusal):
                self.audit(CONFIG + 'CONFIG_PATH="' + expression + '"\n')

    def test_blob_policy_and_system_toolchain_cannot_change(self):
        for addition in ('CONFIG_USE_BLOBS=y\n', 'CONFIG_ANY_TOOLCHAIN=y\n'):
            with self.assertRaises(Refusal):
                self.audit(CONFIG + addition)

    def test_symlink_configuration_is_refused(self):
        path = self.root / 'link'
        path.symlink_to(self.source / 'fixture.config')
        with self.assertRaises(Refusal):
            cb.parse_config(path)

    def test_new_workspace_never_inherits_old_configuration_or_outputs(self):
        self.source.joinpath('.config').write_text('CONFIG_BOARD_TEST_TWO=y\n')
        self.source.joinpath('build').mkdir()
        self.source.joinpath('build/old.rom').write_bytes(b'old')
        first, second = self.configure(), self.configure()
        self.assertNotEqual(first.path, second.path)
        self.assertEqual(first.source.joinpath('.config').read_text(), CONFIG)
        self.assertFalse(first.source.joinpath('build/old.rom').exists())
        cb.verify_workspace(first, TARGET)
        receipt = json.loads(first.path.joinpath('configuration.json').read_text())
        self.assertFalse(receipt['flash_approved'])
        self.assertEqual(self.source.joinpath('.config').read_text(), 'CONFIG_BOARD_TEST_TWO=y\n')

    def test_changed_config_or_target_blocks_execution_before_make(self):
        workspace = self.configure()
        with patch.object(cb, 'command') as command:
            with self.assertRaises(Refusal):
                cb.build(workspace, 'BOARD_TEST_TWO', 1, 'image', 'BUILD image BOARD_TEST_TWO')
            workspace.source.joinpath('.config').write_text(CONFIG + 'CONFIG_EXTRA=y\n')
            with self.assertRaises(Refusal):
                cb.build(workspace, TARGET, 1, 'image', 'BUILD image ' + TARGET)
            command.assert_not_called()

    def test_dirty_source_and_wrong_revision_are_refused(self):
        workspace = self.configure()
        with self.assertRaises(Refusal):
            cb.verify_workspace(dataclasses.replace(workspace, revision='0' * 40), TARGET)
        workspace.source.joinpath('Makefile').write_text('all:\n\ttrue\n')
        with self.assertRaises(Refusal):
            cb.verify_workspace(workspace, TARGET)

    def test_partial_failed_build_cannot_be_reused(self):
        workspace = self.configure()
        with patch.object(cb, 'command', side_effect=Refusal('failed')), self.assertRaises(Refusal):
            cb.build(workspace, TARGET, 1, 'image', 'BUILD image ' + TARGET)
        with self.assertRaisesRegex(Refusal, 'previous operation'):
            cb.verify_workspace(workspace, TARGET)

    def test_output_is_quarantined_and_bound_to_config_and_size(self):
        workspace = self.configure()
        def produce(*args):
            directory = workspace.source / 'build'
            directory.mkdir(exist_ok=True)
            directory.joinpath('coreboot.rom').write_bytes(bytes(range(256)) * 16)
        with patch.object(cb, 'command', side_effect=produce):
            result = cb.build(workspace, TARGET, 1, 'image', 'BUILD image ' + TARGET)
        self.assertFalse(result['flash_approved'])
        self.assertEqual(result['config_sha256'], workspace.config_sha256)
        self.assertEqual(Path(result['path']).name, 'UNQUALIFIED-coreboot.rom')
        # A nominally successful build with an unexpected capacity must not export.
        def wrong_size(*args):
            workspace.source.joinpath('build/coreboot.rom').write_bytes(bytes(range(256)) * 32)
        with patch.object(cb, 'command', side_effect=wrong_size), self.assertRaisesRegex(Refusal, 'size differs'):
            cb.build(workspace, TARGET, 1, 'image', 'BUILD image ' + TARGET)

    def test_make_cannot_mutate_configuration_then_export_candidate(self):
        workspace = self.configure()
        def alter(*args):
            workspace.source.joinpath('.config').write_text(CONFIG + 'CONFIG_EXTRA=y\n')
        with patch.object(cb, 'command', side_effect=alter), self.assertRaisesRegex(Refusal, 'changed after review'):
            cb.build(workspace, TARGET, 1, 'image', 'BUILD image ' + TARGET)
        self.assertFalse(list(workspace.path.rglob('UNQUALIFIED-coreboot.rom')))

    def test_invalid_parallelism_confirmation_and_environment(self):
        for value in (0, 65, True, '1; exit'):
            with self.assertRaises(Refusal):
                cb.jobs_value(value)
        with patch.dict(os.environ, {'MAKEFLAGS': '-f /tmp/evil', 'GIT_CONFIG_GLOBAL': '/tmp/evil', 'LD_PRELOAD': '/tmp/evil'}):
            env = cb.environment()
            self.assertNotIn('MAKEFLAGS', env)
            self.assertNotIn('LD_PRELOAD', env)
            self.assertEqual(env['GIT_CONFIG_GLOBAL'], os.devnull)
        with patch.object(cb, 'command') as command, self.assertRaises(Refusal):
            cb.configure(self.source, TARGET, False, '', self.root / 'work')
        command.assert_not_called()

    def test_timeout_and_prestart_cancellation(self):
        control = cb.Control()
        control.cancel.set()
        with self.assertRaisesRegex(Refusal, 'cancelled'):
            cb.command(['false'], self.root, self.root / 'cancel.log', control)
        started = time.monotonic()
        with self.assertRaisesRegex(Refusal, 'time limit'):
            cb.command([sys.executable, '-c', 'import time; time.sleep(60)'], self.root, self.root / 'timeout.log', timeout=0.1)
        self.assertLess(time.monotonic() - started, 5)

    def test_dependency_confirmation_cannot_start_sudo(self):
        with patch.object(cb.subprocess, 'run') as run, self.assertRaises(Refusal):
            cb.install_dependencies('Arch Linux', 'INSTALL coreboot Fedora', self.root / 'deps.log')
        run.assert_not_called()


if __name__ == '__main__':
    unittest.main()
