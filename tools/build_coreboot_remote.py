#!/usr/bin/env python3
"""Actions entry point: no uploaded configuration, vendor files or local backups."""
import json
import os
from pathlib import Path
import re
import shutil
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from librefren import coreboot
from librefren.prepare import fetch_source
from librefren.remote import repository
from librefren.safety import Refusal
from tools.check_coreboot_build import run_phase


def main():
    target = os.environ['BUILD_TARGET']
    coreboot.board_record(target)
    request_id = os.environ['BUILD_REQUEST_ID']
    expected = os.environ['BUILD_EXPECTED_SHA']
    head = os.environ['GITHUB_SHA']
    if not re.fullmatch('[a-f0-9]{32}', request_id) or not re.fullmatch('[a-f0-9]{40}', expected) or head != expected:
        raise Refusal('Invalid request ID or repository changed after review.')
    repo = repository(os.environ['GITHUB_REPOSITORY'])
    run_id = os.environ['GITHUB_RUN_ID']
    if not run_id.isdecimal():
        raise Refusal('Invalid Actions run identifier.')
    policy = os.environ['BUILD_ALLOW_BLOBS']
    if policy not in ('true', 'false'):
        raise Refusal('Explicit binary-repository policy required.')
    allow_blobs = policy == 'true'
    root = Path('build/remote').resolve()
    root.mkdir(parents=True, exist_ok=False)
    evidence = root / 'evidence'
    evidence.mkdir()
    try:
        source = fetch_source('coreboot', root / 'sources')
        workspace = run_phase('configure', lambda control: coreboot.configure(
            source['source'], target, allow_blobs, 'CONFIGURE ' + target, root / 'workspaces', control))
        shutil.copyfile(workspace.source / '.config', evidence / 'generated.config')
        shutil.copyfile(workspace.path / 'configuration.json', evidence / 'configuration.json')
        results = {}
        for operation in ('toolchain', 'image'):
            results[operation] = run_phase(operation, lambda control: coreboot.build(
                workspace, target, 2, operation, f'BUILD {operation} {target}', control))
        result = results['image']
        # Only publish a candidate after the same local backend completes its checks.
        candidate = root / 'candidate'
        candidate.mkdir()
        shutil.copyfile(result['path'], candidate / 'UNQUALIFIED-coreboot.rom')
        shutil.copyfile(workspace.source / '.config', candidate / 'generated.config')
        receipt = dict(result, schema=1, repository=repo, run_id=run_id, head_sha=head,
                       request_id=request_id, allow_blobs=allow_blobs,
                       status='remote-image-unqualified', flash_approved=False)
        receipt.pop('path', None)
        (candidate / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
    finally:
        for pattern in ('sources/*.log', 'workspaces/*/*.log', 'workspaces/*/*/*.log'):
            for path in root.glob(pattern):
                shutil.copyfile(path, evidence / '--'.join(path.relative_to(root).parts))


if __name__ == '__main__':
    main()
