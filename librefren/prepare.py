"""Opt-in preparation using pinned upstream code; never a flash executor."""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

from .releases import archive_name, verify
from .safety import Refusal, archive_members, digest, inspect_variants

DATA = Path(__file__).parent / 'data'
REPOS = {'libreboot': 'lbmk', 'rboot': 'rbmk'}


def fetch_source(project, directory):
    """Fetch only the recorded source revision. Never executes build scripts."""
    repos = dict(REPOS, coreboot='coreboot')
    if project not in repos:
        raise Refusal('Unknown project')
    repo = repos[project]
    commit = json.loads((DATA / 'revisions.json').read_text())[repo]
    url = 'https://review.coreboot.org/coreboot.git' if project == 'coreboot' else f'https://codeberg.org/{project}/{repo}.git'
    directory = Path(directory).resolve()
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    source = Path(tempfile.mkdtemp(prefix=repo + '-', dir=directory))
    # Distinct logs preserve which network/checkout step failed.
    commands = [
        ['git', 'init', str(source)],
        ['git', '-C', str(source), 'remote', 'add', 'origin', url],
        ['git', '-C', str(source), 'fetch', '--depth=1', 'origin', commit],
        ['git', '-C', str(source), 'checkout', '--detach', commit],
    ]
    for number, command in enumerate(commands):
        # Logs are outside the source to keep the checkout clean.
        run_logged(command, directory, directory / f'{source.name}-{number}.log')
    return {'project': project, 'source': str(source), 'revision': commit,
            'status': 'pinned-source-fetched', 'flash_approved': False}


def checked_source(project, source):
    if project not in REPOS:
        raise Refusal('coreboot configuration/build execution needs a reviewed board baseline; see the manual guide.')
    source = Path(source).resolve(strict=True)
    expected = json.loads((DATA / 'revisions.json').read_text())[REPOS[project]]
    current = subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip()
    dirty = subprocess.check_output(['git', '-C', str(source), 'status', '--porcelain', '--untracked-files=normal'], text=True).strip()
    if current != expected or dirty:
        raise Refusal('Preparation requires the pinned, unmodified upstream checkout. Fetch the exact revision listed in data/revisions.json.')
    if not (source / 'mk').is_file():
        raise Refusal('Build-system entry point missing')
    return source


def run_logged(argv, cwd, log):
    # No shell interpolation, inherited XBMK overrides, LD_PRELOAD or build flags.
    env = {k: os.environ[k] for k in ('HOME', 'USER', 'LOGNAME', 'TERM', 'DISPLAY', 'HTTPS_PROXY', 'HTTP_PROXY', 'NO_PROXY', 'https_proxy', 'http_proxy', 'no_proxy') if k in os.environ}
    env.update(PATH='/usr/local/bin:/usr/bin:/bin', LANG='C.UTF-8')
    with Path(log).open('x') as out:
        out.write(json.dumps({'argv': argv, 'cwd': str(cwd)}) + '\n')
        out.flush()
        result = subprocess.run(argv, cwd=cwd, env=env, stdout=out, stderr=subprocess.STDOUT)
    if result.returncode:
        raise Refusal(f'Preparation failed (exit {result.returncode}). Read {log}. No output is approved for flashing.')


def dependencies(project, source, profile, confirmation, output):
    source = checked_source(project, source)
    if not re.fullmatch(r'[a-z0-9]+', profile) or not (source / 'config/dependencies' / profile).is_file():
        raise Refusal('Choose an exact dependency profile present in this pinned checkout.')
    if confirmation != f'INSTALL {project} {profile}':
        raise Refusal('Dependency installation needs explicit confirmation of project and profile.')
    log = Path(output).resolve()
    run_logged(['sudo', '--', str(source / 'mk'), 'dependencies', profile], source, log)
    return {'status': 'dependency-installer-completed', 'log': str(log)}


def inject(project, target, archive, source, mac, confirmation, directory):
    if project != 'libreboot':
        raise Refusal('RBoot requires region-preserving preparation; generic vendor injection is disabled. Read the target workflow.')
    source = checked_source(project, source)
    archive = Path(archive).resolve(strict=True)
    if archive.name != archive_name(project, target):
        raise Refusal('Archive must identify the exact pinned release and target.')
    if confirmation != f'PREPARE {target}':
        raise Refusal('Preparation requires explicit target confirmation.')
    if mac != 'random':
        if not re.fullmatch(r'[0-9a-fA-F]{2}(?::[0-9a-fA-F]{2}){5}', mac):
            raise Refusal('Choose random or a complete unicast MAC address.')
        if int(mac[:2], 16) & 1 or mac.lower() in ('00:00:00:00:00:00', 'ff:ff:ff:ff:ff:ff'):
            raise Refusal('MAC address must be a nonzero unicast address.')
    if not (source / 'config/module/coreboot' / target / 'config').is_dir():
        raise Refusal('Target is absent from the pinned preparation source.')
    original_hash = verify(archive, archive.parent / 'archive.sig', archive.parent / 'key.asc')
    archive_members(archive)
    directory = Path(directory)
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix='prepared-', dir=directory)).resolve()
    prepared = work / archive.name
    shutil.copyfile(archive, prepared)
    if digest(prepared) != original_hash:
        raise Refusal('Archive changed while copying')
    argv = [str(source / 'mk'), 'inject', str(prepared), 'setmac']
    if mac != 'random':
        argv.append(mac)
    run_logged(argv, source, work / 'preparation.log')
    variants = inspect_variants(prepared, target)
    if any(v['blockers'] for v in variants):
        raise Refusal(f'Prepared output still has blocked variants. Retained logs: {work}')
    receipt = {'project': project, 'target': target, 'original_sha256': original_hash,
               'prepared_sha256': digest(prepared), 'archive': str(prepared),
               'source_revision': json.loads((DATA / 'revisions.json').read_text())['lbmk'],
               'variants': variants, 'mac_choice': mac, 'flash_approved': False,
               'status': 'upstream-preparation-completed-unqualified'}
    (work / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
    return receipt
