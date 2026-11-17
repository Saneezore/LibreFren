import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError

from librefren.releases import RELEASES, archive_name, download, fetch
from librefren.safety import Refusal


class ReleaseInventoryTests(unittest.TestCase):
    def test_saved_catalog_covers_every_distribution_target_at_current_pin(self):
        root = Path(__file__).resolve().parents[1] / 'librefren/data'
        boards = json.loads((root / 'boards.json').read_text())
        catalog = json.loads((root / 'release-inventory.json').read_text())
        for project, (version, base) in RELEASES.items():
            saved = catalog['projects'][project]
            self.assertEqual(saved['release'], version)
            self.assertEqual(saved['listing_url'], base + 'roms/')
            self.assertEqual(set(saved['targets']), {b['id'] for b in boards if b['project'] == project})
            for target, item in saved['targets'].items():
                self.assertEqual(item['archive'], archive_name(project, target))

    def test_unavailable_release_does_not_fall_back(self):
        opener = Mock()
        opener.open.side_effect = HTTPError('https://rboot.org/absent', 404, 'Not Found', {}, None)
        with patch('librefren.releases.build_opener', return_value=opener), tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(Refusal, 'No different release or target'):
                download('https://rboot.org/absent', Path(directory) / 'index')
            opener.open.assert_called_once()
            self.assertFalse((Path(directory) / 'index').exists())

    def test_neighbor_target_does_not_trigger_archive_download(self):
        name = archive_name('rboot', 'fixture_other')
        self.assert_stops_after_listing(f'<a href="{name}">archive</a><a href="{name}.sig">sig</a>')

    def test_missing_signature_stops_before_archive_download(self):
        name = archive_name('rboot', 'fixture')
        self.assert_stops_after_listing(f'<a href="{name}">archive</a>')

    def assert_stops_after_listing(self, html):
        def listing_only(url, output, limit):
            self.assertTrue(url.endswith('/roms/'))
            Path(output).write_text(html)
        with tempfile.TemporaryDirectory() as directory, patch('librefren.releases.download', side_effect=listing_only) as downloader:
            with self.assertRaises(Refusal):
                fetch('rboot', 'fixture', directory)
            downloader.assert_called_once()


if __name__ == '__main__':
    unittest.main()
