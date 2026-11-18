#!/usr/bin/env python3
"""Compare synthetic VPD records with the pinned upstream C decoder."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import random
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from librefren.vpd import decode_records

HARNESS = r'''
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include "vpd_decode.h"
static int capture(const u8 *key, u32 n, const u8 *value, u32 m, void *arg) {
    (void)arg;
    printf("%.*s %u ", (int)n, key, m);
    for (u32 i = 0; i < m; i++) printf("%02x", value[i]);
    putchar('\n');
    return VPD_DECODE_OK;
}
int main(int argc, char **argv) {
    if (argc != 2) return 2;
    FILE *input = fopen(argv[1], "rb");
    if (!input) return 3;
    unsigned char *data = malloc(2097153);
    if (!data) return 4;
    size_t size = fread(data, 1, 2097153, input);
    fclose(input);
    if (size > 2097152) return 5;
    u32 used = 0;
    while (used < size && data[used] != 0 && data[used] != 255)
        if (vpd_decode_string(size, data, &used, capture, NULL) != VPD_DECODE_OK) return 6;
    int result = used < size ? 0 : 7;
    free(data);
    return result;
}
'''


def encode_size(size):
    values = [size & 127]
    while size > 127:
        size >>= 7
        values.insert(0, (size & 127) | 128)
    return bytes(values)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    source = args.source.resolve()
    revision = subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip()
    expected = json.loads((Path(__file__).resolve().parents[1] / 'librefren/data/revisions.json').read_text())['coreboot']
    if revision != expected or subprocess.check_output(['git', '-C', str(source), 'status', '--porcelain'], text=True).strip():
        raise RuntimeError('Expected the clean pinned coreboot source')
    results = []
    randomizer = random.Random(0x565044)
    with tempfile.TemporaryDirectory(prefix='librefren-vpd-check-') as temporary:
        directory = Path(temporary)
        harness = directory / 'harness.c'
        harness.write_text(HARNESS)
        decoder = source / 'src/drivers/vpd/vpd_decode.c'
        executable = directory / 'decode'
        subprocess.run(['cc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-Wno-error=sign-compare', '-include', 'stdint.h',
                        '-Du32=uint32_t', '-Du8=uint8_t', '-I', str(decoder.parent),
                        str(decoder), str(harness), '-o', str(executable)], check=True)
        for number in range(32):
            payload = bytearray()
            for index, length in enumerate((0, 1, 127, 128, 16383, 16384, 65793)):
                key = f'fixture_{number}_{index}'.encode()
                value = randomizer.randbytes(length)
                payload += b'\x01' + encode_size(len(key)) + key + encode_size(length) + value
            payload += b'\x00' if number % 2 else b'\xff'
            input_file = directory / 'payload.bin'
            input_file.write_bytes(payload)
            lines = subprocess.check_output([str(executable), str(input_file)], text=True).splitlines()
            reference = {}
            for line in lines:
                key, size, value = line.split(' ', 2)
                reference[key] = {'bytes': int(size), 'sha256': hashlib.sha256(bytes.fromhex(value)).hexdigest()}
            actual = decode_records(memoryview(payload))['records']
            if reference != actual:
                raise RuntimeError('VPD decoder disagrees with upstream on synthetic fixture ' + str(number))
            results.append({'fixture': number, 'records': len(actual), 'payload_bytes': len(payload),
                            'payload_sha256': hashlib.sha256(payload).hexdigest()})
    args.output.write_text(json.dumps({'observed_at': datetime.now(timezone.utc).isoformat(),
        'source_revision': revision, 'source_file': 'src/drivers/vpd/vpd_decode.c',
        'fixtures_compared': len(results), 'records_compared': sum(r['records'] for r in results),
        'scope': 'Synthetic valid record decoding only. Strict malformed-input checks are separate unit tests. No real device-data migration or hardware validation.',
        'flash_approved': False, 'results': results}, indent=2) + '\n')
    print(f'{len(results)} synthetic fixtures agree with the pinned upstream C decoder')


if __name__ == '__main__':
    main()
