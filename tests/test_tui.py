"""Exercise the default interactive entry point and safety-relevant UI transitions."""
from pathlib import Path
import os
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

from librefren.app import TUI, main
from librefren.safety import Refusal


def interface():
    app = TUI.__new__(TUI)
    app.selected = {'project': 'libreboot', 'id': 'board_16mb'}
    app.receipt = {'archive': '/old/archive', 'status': 'authenticated-download-only'}
    app.selected_variant = {'path': '/old/image.rom'}
    app.backup_result = {'status': 'consistent'}
    app.sources = {}
    app.hardware = {}
    app.boards = [app.selected, {'project': 'libreboot', 'id': 'other_16mb', 'names': []}]
    app.view = Mock()
    return app


class TuiTests(unittest.TestCase):
    def test_no_arguments_launches_interactive_interface(self):
        with patch('sys.argv', ['librefren']), patch('sys.stdin.isatty', return_value=True), \
                patch('librefren.app.curses.wrapper', side_effect=lambda callback: callback('screen')), \
                patch('librefren.app.TUI') as ui:
            main()
            ui.assert_called_once_with('screen')
            ui.return_value.run.assert_called_once_with()

    def test_target_change_discards_previous_artifacts_and_backup_status(self):
        app = interface()
        app.menu = Mock(side_effect=[1, 0, 1, 1])
        app.choose_target()
        self.assertEqual(app.selected['id'], 'other_16mb')
        self.assertIsNone(app.receipt)
        self.assertIsNone(app.selected_variant)
        self.assertIsNone(app.backup_result)

    def test_cancelled_target_change_preserves_current_session(self):
        app = interface()
        app.menu = Mock(side_effect=[1, 0, 1, 0])
        app.choose_target()
        self.assertEqual(app.selected['id'], 'board_16mb')
        self.assertEqual(app.receipt['archive'], '/old/archive')

    def test_cancelled_download_does_not_start_network_work(self):
        app = interface()
        app.prompt = Mock(return_value=None)
        app.background_job = Mock()
        app.download()
        app.background_job.assert_not_called()

    def test_downloaded_archive_cannot_be_selected_as_prepared(self):
        app = interface()
        with patch('librefren.app.extract_variant') as extract:
            with self.assertRaises(Refusal):
                app.preparation(2)
            extract.assert_not_called()

    def test_missing_source_cannot_start_dependency_installation(self):
        app = interface()
        app.terminal_job = Mock()
        app.preparation(0)
        app.terminal_job.assert_not_called()

    def test_coreboot_dependency_step_shows_manual_guidance(self):
        app = interface()
        app.selected = {'project': 'coreboot', 'id': 'vendor/board'}
        app.terminal_job = Mock()
        app.preparation(0)
        app.terminal_job.assert_not_called()
        self.assertIn('configuration', app.view.call_args.args[0])

    def test_apprun_forwards_explicit_arguments_without_terminal(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'usr/bin').mkdir(parents=True)
            shutil.copyfile(Path(__file__).resolve().parents[1] / 'packaging/AppRun', root / 'AppRun')
            entry = root / 'usr/bin/librefren'
            entry.write_text('#!/bin/sh\nprintf "%s\\n" "$@"\n')
            entry.chmod(0o755)
            result = subprocess.run(['sh', str(root / 'AppRun'), 'boards', 'one argument'],
                                    capture_output=True, text=True, check=True)
            self.assertEqual(result.stdout.splitlines(), ['boards', 'one argument'])

    def test_desktop_launch_opens_terminal_with_tui_no_arguments(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tools = root / 'tools'
            tools.mkdir()
            for name in ('readlink', 'dirname'):
                (tools / name).symlink_to(shutil.which(name))
            terminal = tools / 'x-terminal-emulator'
            terminal.write_text('#!/bin/sh\nprintf "%s\\n" "$@"\n')
            terminal.chmod(0o755)
            shutil.copyfile(Path(__file__).resolve().parents[1] / 'packaging/AppRun', root / 'AppRun')
            result = subprocess.run(['/bin/sh', str(root / 'AppRun')], capture_output=True,
                                    text=True, check=True, env=dict(os.environ, PATH=str(tools)))
            self.assertEqual(result.stdout.splitlines(), ['-e', str(root / 'usr/bin/librefren')])


if __name__ == '__main__':
    unittest.main()
