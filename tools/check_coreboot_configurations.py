#!/usr/bin/env python3
"""Exercise the real pinned Kconfig flow. This does not compile ROMs or touch hardware."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from librefren import coreboot

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--source', required=True, type=Path)
parser.add_argument('--output', required=True, type=Path)
parser.add_argument('--host-tools', type=Path, help='Test-only unpacked bison/flex package root; no system installation')
parser.add_argument('--targets', nargs='+', default=[
    'BOARD_EMULATION_QEMU_X86_I440FX', 'BOARD_EMULATION_QEMU_X86_Q35',
    'BOARD_EMULATION_QEMU_AARCH64', 'BOARD_EMULATION_QEMU_ARMV7',
    'BOARD_EMULATION_QEMU_RISCV_RV64', 'BOARD_EMULATION_QEMU_POWER9',
    'BOARD_LENOVO_X230',
    'BOARD_GOOGLE_ASURADA', 'BOARD_GOOGLE_HAYATO', 'BOARD_ASUS_B85M_E',
    'BOARD_DELL_E6400', 'BOARD_HP_260_G1_DM', 'BOARD_PURISM_LIBREM13_V1',
    'BOARD_PCENGINES_APU2', 'BOARD_PROTECTLI_FW2B', 'BOARD_SYSTEM76_GALP6',
])
args = parser.parse_args()
if args.host_tools:
    original_environment = coreboot.environment
    def local_test_environment():
        env = original_environment()
        env['PATH'] = str(args.host_tools.resolve() / 'usr/bin') + ':' + env['PATH']
        env['BISON_PKGDATADIR'] = str(args.host_tools.resolve() / 'usr/share/bison')
        return env
    coreboot.environment = local_test_environment
results = []
for target in args.targets:
    # Temporary configurations are disposable test outputs, not user workspaces.
    with tempfile.TemporaryDirectory(prefix='librefren-config-check-') as directory:
        try:
            workspace = coreboot.configure(args.source, target, False, 'CONFIGURE ' + target, directory)
            coreboot.verify_workspace(workspace, target)
            result = {'target': target, 'status': 'configuration-verified', 'config_sha256': workspace.config_sha256,
                      'toolchains': workspace.toolchains, 'summary': workspace.summary}
        except Exception as error:
            logs = {str(p.relative_to(directory)): p.read_text(errors='replace')[-8000:]
                    for p in Path(directory).glob('*/*.log')}
            result = {'target': target, 'status': 'stopped', 'error': str(error), 'logs': logs}
        results.append(result)
        print(target + ': ' + result['status'], flush=True)
args.output.write_text(json.dumps({
    'observed_at': datetime.now(timezone.utc).isoformat(),
    'revision': json.loads((coreboot.DATA / 'revisions.json').read_text())['coreboot'],
    'scope': 'Real upstream configuration generation only; no toolchain/ROM build, hardware testing or flash approval.',
    'host_tools': 'workspace-extracted bison/flex packages' if args.host_tools else 'host system tools',
    'results': results,
}, indent=2) + '\n')
sys.exit(any(result['status'] != 'configuration-verified' for result in results))
