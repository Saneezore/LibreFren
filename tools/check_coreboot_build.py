#!/usr/bin/env python3
"""Build and boot one emulated target through LibreFren; never test physical firmware."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from librefren import coreboot
from librefren.prepare import fetch_source
from librefren.safety import Refusal

TARGET = 'BOARD_EMULATION_QEMU_X86_I440FX'


def run_phase(name, action):
    control = coreboot.Control()
    started = time.monotonic()
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(action, control)
        try:
            while not future.done():
                print(f'{name}: {int(time.monotonic() - started)}s; log={control.log}', flush=True)
                if control.log and control.log.exists():
                    with control.log.open('rb') as stream:
                        stream.seek(max(0, control.log.stat().st_size - 512))
                        print(stream.read(512).decode('utf-8', errors='replace'), flush=True)
                time.sleep(10)
            return future.result()
        except BaseException:
            control.cancel.set()
            raise


def qemu_boot(image, expected_hash, evidence):
    data = image.read_bytes()
    if hashlib.sha256(data).hexdigest() != expected_hash:
        raise Refusal('QEMU candidate hash changed after build.')
    debug, serial, errors = (evidence / name for name in ('qemu-debug.log', 'qemu-serial.log', 'qemu-stderr.log'))
    argv = ['qemu-system-x86_64', '-machine', 'pc', '-accel', 'tcg', '-m', '128',
            '-bios', str(image), '-display', 'none', '-monitor', 'none', '-nic', 'none',
            '-serial', 'file:' + str(serial), '-debugcon', 'file:' + str(debug),
            '-global', 'isa-debugcon.iobase=0x402', '-no-reboot']
    result = {'argv': argv, 'duration_limit_seconds': 45,
              'version': subprocess.check_output(['qemu-system-x86_64', '--version'], text=True).splitlines()[0]}
    with errors.open('xb') as stderr:
        process = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=stderr, stderr=stderr)
        try:
            process.wait(timeout=45)
        except subprocess.TimeoutExpired:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
    text = '\n'.join(p.read_text(errors='replace') for p in (debug, serial) if p.exists())
    result.update(returncode=process.returncode,
                  coreboot_ramstage=bool(re.search(r'coreboot-[^\n]*ramstage starting', text)),
                  seabios_started='SeaBIOS (version ' in text,
                  no_boot_device='No bootable device.' in text)
    result['passed'] = all(result[key] for key in ('coreboot_ramstage', 'seabios_started', 'no_boot_device'))
    (evidence / 'qemu.json').write_text(json.dumps(result, indent=2) + '\n')
    if not result['passed']:
        raise Refusal('QEMU did not show all required boot markers; inspect its debug/serial logs.')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path, required=True)
    parser.add_argument('--jobs', type=int, default=2)
    args = parser.parse_args()
    coreboot.jobs_value(args.jobs)
    directory = args.directory.resolve()
    directory.mkdir(parents=True, exist_ok=False)
    evidence = directory / 'evidence'
    evidence.mkdir()
    report = {'observed_at': datetime.now(timezone.utc).isoformat(), 'target': TARGET,
              'scope': 'One QEMU i440fx emulation configuration; no physical hardware support or flash approval.',
              'flash_approved': False, 'phases': {}, 'status': 'running'}
    try:
        source = fetch_source('coreboot', directory / 'sources')
        report['source'] = source
        workspace = run_phase('configure', lambda control: coreboot.configure(
            source['source'], TARGET, False, 'CONFIGURE ' + TARGET, directory / 'workspaces', control))
        shutil.copyfile(workspace.path / 'configuration.json', evidence / 'configuration.json')
        shutil.copyfile(workspace.source / '.config', evidence / 'generated.config')
        for operation in ('toolchain', 'image'):
            report['phases'][operation] = run_phase(operation, lambda control: coreboot.build(
                workspace, TARGET, args.jobs, operation, f'BUILD {operation} {TARGET}', control))
            (evidence / 'validation.json').write_text(json.dumps(report, indent=2) + '\n')
        image = report['phases']['image']
        report['phases']['qemu'] = qemu_boot(Path(image['path']), image['sha256'], evidence)
        report['status'] = 'emulated-build-and-payload-boot-verified'
    except Exception as error:
        report.update(status='failed', error=str(error))
        raise
    finally:
        # Only LibreFren operation logs are exported, never ROMs or upstream trees.
        for pattern in ('sources/*.log', 'workspaces/*/*.log', 'workspaces/*/*/*.log'):
            for path in directory.glob(pattern):
                destination = evidence / ('--'.join(path.relative_to(directory).parts))
                shutil.copyfile(path, destination)
        (evidence / 'validation.json').write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    main()
