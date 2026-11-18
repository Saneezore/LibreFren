#!/usr/bin/env python3
"""Diagnose only the fixed QEMU target, reusing a verified Actions artifact."""
import json
import os
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from librefren import coreboot, remote
from librefren.safety import Refusal
from tools.check_coreboot_build import TARGET, qemu_boot


def main():
    run_id = os.environ['BUILD_RUN_ID']
    request_id = os.environ['BUILD_REQUEST_ID']
    if not run_id.isdecimal() or not re.fullmatch('[a-f0-9]{32}', request_id):
        raise Refusal('Invalid build run or request identifier.')
    root = Path('build/remote-emulation').resolve()
    root.mkdir(parents=True, exist_ok=False)
    repo = remote.repository(os.environ['GITHUB_REPOSITORY'])
    client = remote.GitHub(repo)
    run = client.api('/actions/runs/' + run_id)
    workflow = client.api('/actions/workflows/' + remote.WORKFLOW)
    request = dict(schema=1, repository=repo, branch=run['head_branch'], head_sha=run['head_sha'],
                   workflow_id=workflow['id'], target=TARGET, allow_blobs=False, request_id=request_id,
                   coreboot_revision=json.loads((coreboot.DATA / 'revisions.json').read_text())['coreboot'],
                   flash_approved=False, status='inspection-requested', run_id=int(run_id))
    remote.checked_run(request, run)
    request_path = root / 'request.json'
    remote.save(request, request_path)
    result = remote.download(request, request_path, root / 'download')
    evidence = root / 'evidence'
    evidence.mkdir()
    (evidence / 'candidate.json').write_text(json.dumps(result, indent=2) + '\n')
    cases = {}
    for name, machine, menu in [('baseline', 'pc', True), ('acpi-off', 'pc,acpi=off', True),
                                ('menu-off', 'pc', False)]:
        directory = evidence / name
        directory.mkdir()
        print('Checking ' + name, flush=True)
        try:
            cases[name] = qemu_boot(Path(result['path']), result['sha256'], directory, machine, menu)
        except Refusal as error:
            cases[name] = json.loads((directory / 'qemu.json').read_text())
            cases[name]['error'] = str(error)
    summary = {'source_run': request['run_url'], 'target': TARGET, 'image_sha256': result['sha256'],
               'cases': cases, 'flash_approved': False,
               'passed': cases['baseline']['passed'],
               'scope': 'One emulated target. Diagnostic alternatives cannot substitute for a failed baseline.'}
    (evidence / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    if not summary['passed']:
        raise Refusal('Baseline emulation still failed. Inspect all case logs; alternate settings do not qualify the default.')


if __name__ == '__main__':
    main()
