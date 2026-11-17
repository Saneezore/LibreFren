"""Read-only firmware layout evidence, never an image editor or flash authority.

FMAP follows coreboot's documented little-endian serialized format. IFD inspection
is deliberately limited to the five common region registers; it does not infer a
chipset, decode permissions/straps, or certify newer descriptors as fully parsed.
"""
import hashlib
import os
from pathlib import Path
import stat
import struct

from .safety import Refusal

MAX_IMAGE = 128 * 1024**2
FMAP_HEADER = struct.Struct('<8sBBQI32sH')
FMAP_AREA = struct.Struct('<II32sH')
PRESERVE = 8
IDENTITY_AREAS = {'RO_VPD', 'RW_VPD', 'GBB', 'RW_MRC_CACHE', 'RECOVERY_MRC_CACHE', 'MRC_CACHE'}
IFD_NAMES = ('descriptor', 'bios', 'me', 'gbe', 'platform_data')
SOURCES = [
    'https://doc.coreboot.org/lib/flashmap.html',
    'https://github.com/coreboot/coreboot/blob/f13a6c7a61a761559d719f2b2e2a0ae1f43ddeb9/util/ifdtool/ifdtool.c',
    'https://rboot.org/docs/install/ivy_has_common.html',
    'https://rboot.org/docs/install/dell_gbe.html',
    'https://libreboot.org/docs/install/chromebooks-x86.html',
]


def read_image(path):
    """Take one bounded snapshot; do not read devices, pipes or final symlinks."""
    fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    with os.fdopen(fd, 'rb') as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode) or not 4096 <= before.st_size <= MAX_IMAGE:
            raise Refusal('Choose a regular, full-image file between 4 KiB and 128 MiB; partial chip dumps need a reviewed layout first.')
        data = stream.read(MAX_IMAGE + 1)
        after = os.fstat(stream.fileno())
    if (len(data) != before.st_size or len(data) > MAX_IMAGE
            or (before.st_size, before.st_mtime_ns, before.st_ctime_ns)
            != (after.st_size, after.st_mtime_ns, after.st_ctime_ns)):
        raise Refusal('Image changed while reading; take a stable copy before comparing.')
    return data


def _name(raw):
    head, separator, tail = raw.partition(b'\0')
    if not separator or not head or any(tail) or any(c < 33 or c > 126 for c in head):
        raise Refusal('FMAP name is empty, unterminated or contains unsupported bytes.')
    return head.decode('ascii')


def _overlap(a, b):
    return max(a['offset'], b['offset']) < min(a['offset'] + a['size'], b['offset'] + b['size'])


def _contains(a, b):
    return a['offset'] <= b['offset'] and b['offset'] + b['size'] <= a['offset'] + a['size']


def _fill(data, start, size):
    for value in (0, 255):
        if data.count(bytes([value]), start, start + size) == size:
            return value
    return None


def _fmap_at(data, offset):
    if offset + FMAP_HEADER.size > len(data):
        raise Refusal('Truncated FMAP header.')
    _, major, minor, base, size, name, count = FMAP_HEADER.unpack_from(data, offset)
    if (major, minor) not in ((1, 0), (1, 1)):
        raise Refusal('Unsupported FMAP version.')
    if size != len(data) or base + size > 2**64:
        raise Refusal('FMAP size does not match this complete image or its address range overflows.')
    table_end = offset + FMAP_HEADER.size + count * FMAP_AREA.size
    if not 1 <= count <= 1024 or table_end > len(data):
        raise Refusal('FMAP area table is truncated or exceeds the area limit.')
    areas, total_region_bytes = {}, 0
    for i in range(count):
        start, length, raw_name, flags = FMAP_AREA.unpack_from(data, offset + FMAP_HEADER.size + i * FMAP_AREA.size)
        area_name = _name(raw_name)
        if area_name in areas or not length or start + length > size or flags & ~15:
            raise Refusal('FMAP has duplicate names, empty/out-of-bounds regions or unknown flags.')
        total_region_bytes += length
        if total_region_bytes > min(8 * size, 512 * 1024**2):
            raise Refusal('FMAP nesting exceeds the region inspection budget.')
        area = {'offset': start, 'size': length, 'flags': flags}
        for other in areas.values():
            if _overlap(area, other) and not (_contains(area, other) or _contains(other, area)):
                raise Refusal('FMAP regions overlap without a parent/child relationship.')
        areas[area_name] = area
    self_area = areas.get('FMAP')
    if not self_area or not _contains(self_area, {'offset': offset, 'size': table_end - offset}):
        raise Refusal('FMAP does not describe a region containing its own complete table.')
    return {'format': 'FMAP', 'version': f'{major}.{minor}', 'base': base,
            'size': size, 'name': _name(name), 'table_offset': offset, 'areas': areas}


def parse_fmap(data):
    """Reject ambiguous valid maps; a signature embedded in program code is not a map."""
    offset, valid, errors, count = 0, [], [], 0
    while True:
        offset = data.find(b'__FMAP__', offset)
        if offset < 0:
            break
        count += 1
        if count > 64:
            raise Refusal('Too many FMAP signature candidates; layout is ambiguous.')
        try:
            valid.append(_fmap_at(data, offset))
        except Refusal as error:
            errors.append(str(error))
        offset += 8
    if len(valid) > 1:
        raise Refusal('Multiple valid FMAP tables; no automatic choice is safe.')
    if not valid:
        raise Refusal('No supported, unambiguous FMAP: ' + (errors[0] if errors else 'signature not found.'))
    valid[0]['ignored_signature_candidates'] = len(errors)
    for area in valid[0]['areas'].values():
        area['sha256'] = hashlib.sha256(memoryview(data)[area['offset']:area['offset'] + area['size']]).hexdigest()
        area['uniform_fill'] = _fill(data, area['offset'], area['size'])
    return valid[0]


def parse_ifd_common(data):
    """Inspect common IFD geometry only. Additional regions/straps stay unresolved."""
    if len(data) < 4096:
        raise Refusal('Image is too short for an Intel flash descriptor.')
    signature = b'\x5a\xa5\xf0\x0f'
    locations = [off for off in (0, 16) if data[off:off + 4] == signature]
    if len(locations) != 1:
        raise Refusal('Expected exactly one Intel descriptor at offset 0 or 16.')
    position = locations[0]
    map0, map1 = struct.unpack_from('<II', data, position + 4)
    component = (map0 & 255) << 4
    region = ((map0 >> 16) & 255) << 4
    master = (map1 & 255) << 4
    straps = ((map1 >> 16) & 255) << 4
    sections = [component, region, master, straps, 0xefc]
    if len(set(sections)) != len(sections) or any(x < position + 16 or x >= 4096 for x in sections):
        raise Refusal('Invalid or overlapping Intel descriptor section pointers.')
    boundary = min((x for x in sections if x > region), default=4096)
    if region + len(IFD_NAMES) * 4 > boundary:
        raise Refusal('Descriptor region table is too short for the common region registers.')
    areas = {}
    for i, name in enumerate(IFD_NAMES):
        raw, = struct.unpack_from('<I', data, region + i * 4)
        start = (raw & 0x7fff) << 12
        end = (((raw >> 16) & 0x7fff) + 1) << 12
        if start >= end:
            continue  # Disabled region; all common disabled-base encodings work.
        if raw & 0x80008000 or end > len(data):
            raise Refusal('IFD common region has reserved bits or extends beyond the supplied full image.')
        area = {'offset': start, 'size': end - start,
                'uniform_fill': _fill(data, start, end - start),
                'sha256': hashlib.sha256(memoryview(data)[start:end]).hexdigest()}
        if any(_overlap(area, other) for other in areas.values()):
            raise Refusal('IFD common regions overlap.')
        areas[name] = area
    if 'bios' not in areas or areas.get('descriptor', {}).get('offset') != 0 or areas['descriptor']['size'] != 4096:
        raise Refusal('Descriptor must describe its first 4 KiB and a nonempty BIOS region.')
    return {'format': 'IFD-common-regions', 'table_offset': region, 'areas': areas,
            'coverage': 'Only descriptor, BIOS, ME, GbE and platform-data geometry. Chipset generation, extra regions, permissions, density and straps are NOT validated.'}


def _inspect(data):
    result = {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
    for name, parser in (('fmap', parse_fmap), ('ifd', parse_ifd_common)):
        try:
            result[name] = parser(data)
        except Refusal as error:
            result[name + '_unresolved'] = str(error)
    return result


def compare_images(backup_path, candidate_path, context='general', expected_size=None):
    if context not in ('general', 'rboot', 'chromebook'):
        raise Refusal('Unknown layout comparison context.')
    if expected_size is not None and (type(expected_size) is not int or not 4096 <= expected_size <= MAX_IMAGE):
        raise Refusal('Expected target capacity is outside the supported full-image range.')
    original, candidate = _inspect(read_image(backup_path)), _inspect(read_image(candidate_path))
    blockers = ['Physical target identity, backup completeness and candidate provenance are not certified by a layout comparison.',
                'No qualified board/release flashing profile; matching layout never authorizes a write.']
    rows = []
    if original['bytes'] != candidate['bytes']:
        blockers.append('Image sizes differ. Partial dumps and full-chip images cannot be interchanged.')
    if expected_size is not None:
        for role, image in (('backup', original), ('candidate', candidate)):
            if image['bytes'] != expected_size:
                blockers.append(f'{role.capitalize()} size disagrees with the selected target capacity ({expected_size} bytes).')
    for kind in ('fmap', 'ifd'):
        if kind not in original or kind not in candidate:
            if (kind == 'fmap' and context == 'chromebook') or (kind == 'ifd' and context == 'rboot'):
                blockers.append(f'{kind.upper()} could not be compared on both images; obtain a reviewed board-specific procedure.')
            continue
        old, new = original[kind]['areas'], candidate[kind]['areas']
        if kind == 'ifd':
            blockers.append(original[kind]['coverage'])
        elif original[kind]['base'] != candidate[kind]['base']:
            blockers.append('FMAP memory bases differ; region names alone do not establish compatible addressing.')
        names = set(old) | set(new)
        for name in sorted(names):
            a, b = old.get(name), new.get(name)
            preservation = (kind == 'ifd' and name != 'bios') or (kind == 'fmap' and
                (name in IDENTITY_AREAS or any(v and v['flags'] & PRESERVE for v in (a, b))))
            geometry = bool(a and b and (a['offset'], a['size']) == (b['offset'], b['size']))
            content = bool(a and b and a['sha256'] == b['sha256'])
            rows.append({'format': kind, 'region': name, 'backup': a, 'candidate': b,
                         'same_geometry': geometry, 'same_content': content, 'preservation_review': preservation})
            if not geometry:
                blockers.append(f'{kind.upper()} {name}: region is missing, moved or resized; a reviewed migration plan is required.')
            if preservation and not content:
                blockers.append(f'{kind.upper()} {name}: bytes differ or the region is absent. Resolve device-data / vendor-region preservation; do not copy blindly.')
            if preservation and name not in ('descriptor', 'platform_data'):
                for role, area in (('backup', a), ('candidate', b)):
                    if area and area.get('uniform_fill') is not None:
                        blockers.append(f'{kind.upper()} {name}: {role} contains only 0x{area["uniform_fill"]:02x}. Data may be absent, intentionally omitted or unreadable; do not treat it as preserved device/vendor content.')
        if kind == 'ifd' and 'me' in old and 'gbe' in new and _overlap(old['me'], new['gbe']):
            blockers.append('Candidate GbE overlaps the backup ME region. Writing the candidate GbE range would overwrite existing ME bytes.')
        if kind == 'ifd' and 'me' in old and 'bios' in new and _overlap(old['me'], new['bios']):
            blockers.append('Candidate BIOS overlaps the backup ME region. A BIOS-region write using this range would overwrite existing ME bytes.')
        if kind == 'fmap' and context == 'chromebook':
            if 'RO_VPD' not in old or 'RO_VPD' not in new:
                blockers.append('RO_VPD is absent from at least one Chromebook FMAP; identity-data preservation remains unresolved.')
            blockers.append('HWID may be stored in GBB or CBFS. This check does not decode HWID or validate VPD, GBB keys, MRC compatibility, calibration or Google Security Chip state.')
    return {'status': 'layout-evidence-only', 'context': context, 'expected_target_bytes': expected_size, 'backup': original, 'candidate': candidate,
            'regions': rows, 'blockers': list(dict.fromkeys(blockers)), 'sources': SOURCES, 'flash_approved': False}


def format_report(report):
    lines = ['Read-only comparison — no firmware files were changed.',
             f'Backup: {report["backup"]["bytes"]} bytes · SHA-256 {report["backup"]["sha256"]}',
             f'Candidate: {report["candidate"]["bytes"]} bytes · SHA-256 {report["candidate"]["sha256"]}', '', 'Region comparisons:']
    for row in report['regions']:
        def span(area):
            return 'absent' if area is None else f'0x{area["offset"]:x} + {area["size"]} bytes'
        lines.append(f'{row["format"].upper()} {row["region"]}: {span(row["backup"])} → {span(row["candidate"])}; '
                     + ('same bytes' if row['same_content'] else 'different or unavailable bytes'))
    for role in ('backup', 'candidate'):
        for kind in ('fmap', 'ifd'):
            if kind + '_unresolved' in report[role]:
                lines.append(f'{role.capitalize()} {kind.upper()}: {report[role][kind + "_unresolved"]}')
    lines += ['', 'Unresolved requirements:', *report['blockers'], '', 'References:', *report['sources']]
    return '\n\n'.join(lines)
