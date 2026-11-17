#!/usr/bin/env python3
"""Compare common-region decoding with pinned upstream ifdtool, without firmware writes.

Build ifdtool outside the upstream checkout using the command in docs/layout-inspection.md.
The padded buffers below are parser fixtures, NOT bootable/prepared firmware images.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from librefren.layouts import IFD_NAMES, MAX_IMAGE, parse_ifd_common


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--ifdtool', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    records = []
    for project in ('lbmk', 'rbmk'):
        source = ROOT / 'research/upstream' / project
        base = source / 'config/data/coreboot/ifd'
        for path in sorted(base.glob('*/*')):
            if not path.is_file() or path.stat().st_size != 4096:
                continue
            data = path.read_bytes()
            if not any(data[pos:pos + 4] == b'\x5a\xa5\xf0\x0f' for pos in (0, 16)):
                continue
            result = subprocess.run([str(args.ifdtool.resolve()), '-d', str(path)], check=True, capture_output=True, text=True)
            expected = {}
            for match in re.finditer(r'Flash Region (\d+) \([^)]+\): ([0-9a-f]{8}) - ([0-9a-f]{8}) ([^\n]*)', result.stdout):
                number, start, end, annotation = match.groups()
                index, start, end = int(number), int(start, 16), int(end, 16)
                if index < len(IFD_NAMES) and 'unused' not in annotation:
                    expected[IFD_NAMES[index]] = {'offset': start, 'size': end + 1 - start}
            if not expected or 'bios' not in expected:
                raise SystemExit('No BIOS geometry from ifdtool: ' + str(path))
            size = max(a['offset'] + a['size'] for a in expected.values())
            if not 4096 <= size <= MAX_IMAGE:
                raise SystemExit('Out-of-budget descriptor: ' + str(path))
            parsed = parse_ifd_common(data + b'\xff' * (size - len(data)))
            actual = {name: {key: area[key] for key in ('offset', 'size')} for name, area in parsed['areas'].items()}
            if actual != expected:
                raise SystemExit(f'Geometry mismatch: {path}\nupstream={expected}\nLibreFren={actual}')
            records.append({'project': project, 'path': str(path.relative_to(source)),
                            'descriptor_sha256': hashlib.sha256(data).hexdigest(), 'common_regions': actual})
    if not records:
        raise SystemExit('No descriptors checked; pinned upstream checkouts are required.')
    revisions = json.loads((ROOT / 'librefren/data/revisions.json').read_text())
    report = {'status': 'common-region-geometry-matches-upstream', 'descriptors_checked': len(records),
              'coreboot_revision': revisions['coreboot'], 'lbmk_revision': revisions['lbmk'], 'rbmk_revision': revisions['rbmk'],
              'limitation': 'Parser comparison using source descriptors and synthetic padding only; no hardware, firmware payload, straps or write-safety qualification.',
              'results': records}
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    print(f'{len(records)} descriptor geometries agree with upstream ifdtool; no firmware files were written.')


if __name__ == '__main__':
    main()
