"""Read-only GBB 1.2 layout and HWID checksum evidence, never key authentication."""
import hashlib
import struct

from .safety import Refusal

HEADER = struct.Struct('<4sHH10I32s48s')
FIELDS = ('hwid', 'root_key', 'bitmap_fv', 'recovery_key')
SOURCE = 'https://github.com/coreboot/vboot/blob/f691f7675d46c8f4726146803543a095b68477c5/firmware/2lib/include/2struct.h'
DIGEST_SOURCE = 'https://github.com/coreboot/vboot/blob/f691f7675d46c8f4726146803543a095b68477c5/futility/misc.c'


def inspect_region(data):
    if not HEADER.size <= len(data) <= 2 * 1024**2:
        raise Refusal('GBB region is truncated or exceeds the 2 MiB inspection limit.')
    signature, major, minor, header_size, flags, *tail = HEADER.unpack_from(data)
    if signature != b'$GBB' or (major, minor) != (1, 2) or header_size != HEADER.size:
        raise Refusal('Only a GBB 1.2 header at the start of its FMAP region is supported; other layouts need manual review.')
    offsets, stored_digest, reserved = tail[:8], tail[8], tail[9]
    if any(reserved):
        raise Refusal('GBB reserved header bytes are nonzero; interpretation is unresolved.')
    components = {}
    for index, name in enumerate(FIELDS):
        start, size = offsets[2 * index:2 * index + 2]
        if start > len(data) or start + size > len(data) or (size and start < header_size):
            raise Refusal('GBB component extends outside its region or overlaps its header.')
        if not size:
            components[name] = None
            continue
        for previous in components.values():
            if previous and max(start, previous['offset']) < min(start + size, previous['offset'] + previous['bytes']):
                raise Refusal('GBB components overlap.')
        components[name] = {'offset': start, 'bytes': size,
                            'sha256': hashlib.sha256(data[start:start + size]).hexdigest()}
    area = components['hwid']
    if not area or area['bytes'] > 4096:
        raise Refusal('GBB HWID is absent or exceeds its inspection limit.')
    raw = bytes(data[area['offset']:area['offset'] + area['bytes']])
    value, separator, padding = raw.partition(b'\x00')
    if not separator or not value or any(c < 32 or c > 126 for c in value) or any(padding):
        raise Refusal('GBB HWID is empty, unterminated, non-ASCII or has nonzero trailing data.')
    calculated = hashlib.sha256(value).digest()
    if calculated != stored_digest:
        raise Refusal('GBB HWID checksum does not match its stored digest.')
    return {'status': 'identity-evidence-only', 'format': 'GBB-1.2', 'flags': flags,
            'hwid': {'bytes': len(value), 'sha256': calculated.hex(), 'stored_digest_matches': True},
            'components': components, 'flash_approved': False,
            'limitation': 'The checksum is not an authenticity check. Key blobs and flags are not qualified for this device; CBFS HWID, VPD calibration, GSC and migration compatibility remain unresolved.'}
