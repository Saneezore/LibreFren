#!/usr/bin/env python3
"""Record exact target availability from saved official listings; not authentication."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from librefren.releases import Links, RELEASES, archive_name


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--libreboot', type=Path, required=True)
    parser.add_argument('--rboot', type=Path, required=True)
    args = parser.parse_args()
    boards = json.loads((ROOT / 'librefren/data/boards.json').read_text())
    report = {'observed_at': datetime.now(timezone.utc).isoformat(),
              'evidence': 'Unsigned official-directory snapshot. Every download still requires a live exact-name lookup and pinned-key signature verification.',
              'projects': {}}
    for project in RELEASES:
        data = getattr(args, project).read_bytes()
        listing = Links()
        listing.feed(data.decode('utf-8'))
        targets = [b['id'] for b in boards if b['project'] == project]
        entries = {}
        for target in targets:
            name = archive_name(project, target)
            entries[target] = {'archive': name,
                               'status': 'listed-with-signature' if name in listing.links and name + '.sig' in listing.links else 'not-listed-with-signature'}
        matched = sum(e['status'] == 'listed-with-signature' for e in entries.values())
        report['projects'][project] = {'release': RELEASES[project][0], 'listing_url': RELEASES[project][1] + 'roms/',
                                       'listing_sha256': hashlib.sha256(data).hexdigest(), 'targets': entries,
                                       'listed_targets': matched, 'unlisted_targets': len(entries) - matched,
                                       'other_archives': sorted(n for n in listing.links if n.endswith('.tar.xz')
                                                                and n not in {e['archive'] for e in entries.values()})}
        print(f'{project}: {matched} exact target archives with signature links; {len(entries) - matched} inventory targets not listed.')
    (ROOT / 'librefren/data/release-inventory.json').write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    main()
