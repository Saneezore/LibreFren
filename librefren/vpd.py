"""Bounded Google VPD 2.0 evidence. Never migrate records or expose their values."""
import hashlib
import re
import struct

from .safety import Refusal

INFO_MAGIC = b'\xfe\x09\x01gVpdInfo\x04'
MAX_REGION = 2 * 1024**2
MAX_RECORDS = 2048
SOURCE = 'https://chromium.googlesource.com/chromiumos/platform/vpd/+/2b274e62f481d3121b964e10bd0c5c79398813ae/README.md'
COREBOOT_SOURCE = 'https://github.com/coreboot/coreboot/blob/f13a6c7a61a761559d719f2b2e2a0ae1f43ddeb9/src/drivers/vpd/vpd.c'


def _entry(data, offset):
    length = 0
    for count in range(5):
        if offset >= len(data):
            raise Refusal('Truncated VPD length.')
        byte = data[offset]
        offset += 1
        if count == 0 and byte == 0x80:
            raise Refusal('Noncanonical VPD length encoding.')
        length = (length << 7) | (byte & 127)
        if not byte & 128:
            break
    else:
        raise Refusal('VPD length encoding exceeds its inspection limit.')
    if length > MAX_REGION or offset + length > len(data):
        raise Refusal('VPD entry length exceeds its declared data boundary.')
    return data[offset:offset + length], offset + length


def decode_records(data):
    if not 1 <= len(data) <= MAX_REGION:
        raise Refusal('VPD payload is empty or exceeds its inspection limit.')
    records, offset = {}, 0
    while offset < len(data):
        kind = data[offset]
        offset += 1
        if kind in (0, 255):
            if any(byte not in (0, 255) for byte in data[offset:]):
                raise Refusal('Non-padding bytes follow the VPD terminator inside the declared payload.')
            return {'records': records, 'terminator': kind, 'consumed_bytes': offset,
                    'empty': not records}
        if kind != 1:
            raise Refusal('Unknown or nested VPD metadata record; manual format review is required.')
        if len(records) >= MAX_RECORDS:
            raise Refusal('VPD record count exceeds its inspection limit.')
        key, offset = _entry(data, offset)
        value, offset = _entry(data, offset)
        if not 1 <= len(key) <= 256 or not re.fullmatch(rb'[A-Za-z0-9_]+', key):
            raise Refusal('VPD key has an unsupported name or length.')
        name = bytes(key).decode('ascii')
        if name in records:
            raise Refusal('Duplicate VPD keys make preservation ambiguous.')
        records[name] = {'bytes': len(value), 'sha256': hashlib.sha256(value).hexdigest()}
    raise Refusal('VPD payload has no explicit or implicit terminator.')


def inspect_region(data):
    if not 16 <= len(data) <= MAX_REGION:
        raise Refusal('VPD region is too small or exceeds its inspection limit.')
    offsets = [offset for offset in (0, 0x600) if data[offset:offset + 12] == INFO_MAGIC]
    if len(offsets) != 1:
        raise Refusal('VPD must have one unambiguous Google info header at offset 0 or 0x600. Legacy/headerless formats need manual review.')
    offset = offsets[0]
    if offset + 16 > len(data):
        raise Refusal('Truncated Google VPD info header.')
    size, = struct.unpack_from('<I', data, offset + 12)
    if not size or offset + 16 + size > len(data):
        raise Refusal('Declared Google VPD size exceeds its FMAP region or is empty.')
    result = decode_records(data[offset + 16:offset + 16 + size])
    result.update(format='Google-VPD-2.0', header_offset=offset, declared_bytes=size,
                  status='record-evidence-only', flash_approved=False,
                  limitation='Record equality does not validate field meanings, calibration compatibility, required board fields, GBB/HWID or a migration procedure.')
    return result


def compare_records(backup, candidate):
    old, new = backup['records'], candidate['records']
    return [{'key': key, 'status': 'added' if key not in old else 'missing' if key not in new
             else 'unchanged' if old[key] == new[key] else 'changed',
             'backup': old.get(key), 'candidate': new.get(key)}
            for key in sorted(set(old) | set(new))]
