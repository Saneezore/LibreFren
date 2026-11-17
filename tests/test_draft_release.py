import os
from pathlib import Path
import subprocess
import tempfile
import unittest


class DraftReleaseTests(unittest.TestCase):
    def run_script(self, state):
        script = Path(__file__).resolve().parents[1] / 'packaging/publish_draft.sh'
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'dist').mkdir()
            (root / 'bin').mkdir()
            for name in ('LibreFren-test.AppImage', 'LibreFren-test.AppImage.sha256'):
                (root / 'dist' / name).write_text('fixture')
            gh = root / 'bin/gh'
            gh.write_text('''#!/bin/sh
printf '%s\\n' "$*" >> "$CALL_LOG"
if [ "$2" = view ]; then
    if [ "$DRAFT_STATE" = absent ]; then exit 1; fi
    printf '%s\\n' "$DRAFT_STATE"
fi
''')
            gh.chmod(0o755)
            env = dict(os.environ, PATH=str(root / 'bin') + ':' + os.environ['PATH'],
                       RELEASE_TAG='v0.1.0', GH_REPO='fixture/repository', DRAFT_STATE=state,
                       CALL_LOG=str(root / 'calls'))
            result = subprocess.run(['sh', str(script)], cwd=root, env=env, capture_output=True, text=True)
            return result, (root / 'calls').read_text().splitlines()

    def test_published_release_assets_cannot_be_overwritten(self):
        result, calls = self.run_script('false')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(len(calls), 1)
        self.assertIn('Refusing', result.stderr)

    def test_existing_draft_updates_only_assets_and_notes(self):
        result, calls = self.run_script('true')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('release upload', calls[1])
        self.assertIn('--clobber', calls[1])
        self.assertIn('release edit', calls[2])
        self.assertNotIn('--draft=false', ' '.join(calls))

    def test_new_release_is_always_created_as_draft_prerelease(self):
        result, calls = self.run_script('absent')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('release create', calls[1])
        self.assertIn('--draft --prerelease', calls[1])


if __name__ == '__main__':
    unittest.main()
