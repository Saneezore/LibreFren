"""GitHub Actions builds: explicit requests, bound provenance, quarantined downloads."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import tempfile
import time
import uuid
import zipfile

from . import coreboot
from .safety import Refusal

WORKFLOW = 'coreboot-remote.yml'
MAX_ARCHIVE = 128 * 1024**2
MAX_IMAGE = 64 * 1024**2
HELP = ('Install GitHub CLI (gh) using https://cli.github.com/ and sign in with '
        '`gh auth login --hostname github.com`. Use a repository you can run Actions in, '
        'such as your own LibreFren fork, with Actions enabled and the remote build workflow present. '
        'Fine-grained credentials need Actions read/write and Contents read access. '
        'Review GitHub Actions usage limits and billing for that repository. '
        'Only the target, binary-dependency choice and request identifier are sent. '
        'Backups, hardware identifiers and vendor files are never uploaded. '
        'Build artifacts and logs follow the repository’s visibility and access rules. '
        'Missing device-specific inputs stop the build; do not upload them to bypass it.')


def repository(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9_.-]{1,100}', value) or value.split('/')[1] in ('.', '..'):
        raise Refusal('Enter a GitHub repository as owner/name, without a URL.')
    return value


def digest(value):
    if not isinstance(value, str) or not re.fullmatch('[0-9a-f]{64}', value):
        raise Refusal('Missing or invalid SHA-256 evidence.')
    return value


def gh_environment():
    env = dict(os.environ)
    # The frozen AppImage loader must not leak its libraries into system gh.
    if 'LD_LIBRARY_PATH_ORIG' in env:
        env['LD_LIBRARY_PATH'] = env['LD_LIBRARY_PATH_ORIG']
    else:
        env.pop('LD_LIBRARY_PATH', None)
    for key in ('GH_DEBUG', 'GH_HOST', 'GH_PAGER', 'GH_BROWSER'):
        env.pop(key, None)
    env.update(GH_PROMPT_DISABLED='1', GH_PAGER='cat', NO_COLOR='1')
    return env


class GitHub:
    def __init__(self, repo):
        self.repo = repository(repo)

    def api(self, route, method='GET', body=None, destination=None):
        gh = shutil.which('gh')
        if not gh:
            raise Refusal('GitHub CLI is not installed. ' + HELP)
        if (route and not route.startswith('/')) or '..' in route:
            raise Refusal('Invalid GitHub API route.')
        argv = [gh, 'api', '--hostname', 'github.com', '--method', method,
                '-H', 'Accept: application/vnd.github+json', '/repos/' + self.repo + route]
        raw = json.dumps(body).encode() if body is not None else b''
        if body is not None:
            argv += ['--input', '-']
        # Never display stderr: gh diagnostics may contain account or credential details.
        with tempfile.TemporaryFile() as incoming, tempfile.TemporaryFile() as output:
            incoming.write(raw)
            incoming.seek(0)
            process = subprocess.Popen(argv, stdin=incoming, stdout=output, stderr=subprocess.DEVNULL,
                                       env=gh_environment())
            limit = MAX_ARCHIVE if destination else 4 * 1024**2
            started = time.monotonic()
            try:
                while process.poll() is None:
                    if time.monotonic() - started > 120 or os.fstat(output.fileno()).st_size > limit:
                        raise Refusal('GitHub request exceeded its time or size limit. Check Actions before retrying a dispatch; it may already have started.')
                    time.sleep(0.1)
                if process.returncode:
                    raise Refusal('GitHub request failed. Check gh authentication, repository permissions and the workflow in GitHub. A failed response does not prove a dispatch was rejected.')
                if os.fstat(output.fileno()).st_size > limit:
                    raise Refusal('GitHub response is too large.')
                output.seek(0)
                if destination:
                    with Path(destination).open('xb') as stream:
                        shutil.copyfileobj(output, stream, 1024 * 1024)
                    return
                data = output.read(limit + 1)
                return json.loads(data) if data else None
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait()


def plan(repo, target, allow_blobs):
    coreboot.board_record(target)
    if type(allow_blobs) is not bool:
        raise Refusal('Choose whether upstream binary repositories are permitted.')
    client = GitHub(repo)
    info = client.api('')
    if info.get('archived') or not info.get('permissions', {}).get('push'):
        raise Refusal('This repository is archived or you lack write access. Use your own LibreFren fork with Actions enabled.')
    branch = info.get('default_branch', '')
    # A fixed branch route avoids arbitrary URL and ref interpretation.
    if not re.fullmatch(r'[A-Za-z0-9_.-]+', branch):
        raise Refusal('This preview needs a default branch name without slashes.')
    head = client.api('/commits/' + branch)['sha']
    if not re.fullmatch('[0-9a-f]{40}', head):
        raise Refusal('Invalid application commit returned by GitHub.')
    workflow = client.api('/actions/workflows/' + WORKFLOW)
    if workflow.get('state') != 'active' or workflow.get('path') != '.github/workflows/' + WORKFLOW:
        raise Refusal('Enable the LibreFren remote build workflow in this repository first.')
    return {'schema': 1, 'repository': client.repo, 'branch': branch, 'head_sha': head,
            'workflow_id': workflow['id'], 'target': target, 'allow_blobs': allow_blobs,
            'request_id': uuid.uuid4().hex, 'coreboot_revision': json.loads((coreboot.DATA / 'revisions.json').read_text())['coreboot'],
            'flash_approved': False, 'status': 'review-required'}


def save(request, path):
    # Same-directory atomic replace preserves a request across interruption.
    path = Path(path)
    temporary = path.with_suffix('.tmp')
    with temporary.open('w') as stream:
        json.dump(request, stream, indent=2)
        stream.write('\n')
    temporary.replace(path)


def load_request(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 65536:
        raise Refusal('Saved request must be a bounded regular file.')
    request = json.loads(path.read_text())
    repository(request['repository'])
    coreboot.board_record(request['target'])
    if (request.get('schema') != 1 or type(request.get('allow_blobs')) is not bool
            or not re.fullmatch('[a-f0-9]{32}', request['request_id'])
            or not re.fullmatch('[a-f0-9]{40}', request['head_sha'])
            or not re.fullmatch(r'[A-Za-z0-9_.-]+', request['branch'])
            or type(request.get('workflow_id')) is not int
            or request.get('coreboot_revision') != json.loads((coreboot.DATA / 'revisions.json').read_text())['coreboot']
            or request.get('flash_approved') is not False):
        raise Refusal('Saved request is incompatible with this application’s source pin or schema.')
    return request


def dispatch(request, confirmation, directory):
    if confirmation != 'BUILD ON GITHUB ' + request['target']:
        raise Refusal('Remote builds require explicit confirmation of the target and repository.')
    client = GitHub(request['repository'])
    if client.api('/commits/' + request['branch'])['sha'] != request['head_sha']:
        raise Refusal('Repository changed since review. Review a fresh request before dispatching.')
    directory = Path(directory)
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = directory / (request['request_id'] + '.json')
    with path.open('x') as stream:
        json.dump(dict(request, status='dispatch-pending'), stream, indent=2)
    # Persist before POST. Never automatically retry an ambiguous dispatch.
    client.api('/actions/workflows/' + WORKFLOW + '/dispatches', 'POST', {
        'ref': request['branch'], 'inputs': {
            'target': request['target'], 'allow_blobs': request['allow_blobs'],
            'request_id': request['request_id'], 'expected_sha': request['head_sha']}})
    request['status'] = 'dispatched'
    save(request, path)
    return path


def checked_run(request, run):
    if (run.get('head_sha') != request['head_sha'] or run.get('event') != 'workflow_dispatch'
            or run.get('workflow_id') != request['workflow_id']
            or run.get('display_title') != 'LibreFren coreboot ' + request['request_id']
            or run.get('repository', {}).get('full_name', '').lower() != request['repository'].lower()):
        raise Refusal('The run does not match this repository, reviewed commit, workflow and request. No artifact accepted.')
    if type(run.get('id')) is not int or run['id'] <= 0:
        raise Refusal('Invalid run identifier.')
    return run


def refresh(request, path):
    client = GitHub(request['repository'])
    if request.get('run_id'):
        run = checked_run(request, client.api('/actions/runs/' + str(request['run_id'])))
    else:
        runs = client.api('/actions/workflows/' + WORKFLOW + '/runs?event=workflow_dispatch&per_page=100')['workflow_runs']
        matches = [r for r in runs if r.get('display_title') == 'LibreFren coreboot ' + request['request_id']]
        if len(matches) != 1:
            raise Refusal('No unique run found in the latest 100 dispatches. Wait and refresh, or inspect GitHub Actions using request ID ' + request['request_id'] + '. Do not dispatch again automatically.')
        run = checked_run(request, matches[0])
    request.update(run_id=run['id'], status=run['status'], conclusion=run.get('conclusion'),
                   run_url=f"https://github.com/{request['repository']}/actions/runs/{run['id']}")
    save(request, path)
    return run


def cancel(request, path, confirmation):
    run = refresh(request, path)
    if confirmation != 'CANCEL ' + str(run['id']):
        raise Refusal('Confirm the exact remote run before cancellation.')
    if run['status'] == 'completed':
        raise Refusal('The remote run has already completed.')
    GitHub(request['repository']).api('/actions/runs/' + str(run['id']) + '/cancel', 'POST')
    request['status'] = 'cancellation-requested'
    save(request, path)


def inspect_bundle(archive, request, run_id):
    """Only our three regular files; nothing is extracted until every check passes."""
    expected = {'receipt.json': 1024**2, 'generated.config': 2 * 1024**2, 'UNQUALIFIED-coreboot.rom': MAX_IMAGE}
    try:
        with zipfile.ZipFile(archive) as bundle:
            entries = bundle.infolist()
            if len(entries) != 3 or {i.filename for i in entries} != set(expected):
                raise Refusal('Unexpected or duplicate files in the remote build artifact.')
            for item in entries:
                mode = item.external_attr >> 16
                if item.flag_bits & 1 or stat.S_IFMT(mode) not in (0, stat.S_IFREG) or not 0 < item.file_size <= expected[item.filename]:
                    raise Refusal('Artifact contains an encrypted, special, empty or oversized file.')
            files = {i.filename: bundle.read(i) for i in entries}
    except (zipfile.BadZipFile, RuntimeError) as error:
        raise Refusal('Invalid remote build archive.') from error
    receipt = json.loads(files['receipt.json'])
    checks = {'schema': 1, 'repository': request['repository'], 'run_id': str(run_id),
              'head_sha': request['head_sha'], 'request_id': request['request_id'],
              'target': request['target'], 'allow_blobs': request['allow_blobs'],
              'revision': request['coreboot_revision'], 'flash_approved': False,
              'status': 'remote-image-unqualified'}
    for key, value in checks.items():
        if type(receipt.get(key)) is not type(value) or receipt[key] != value:
            raise Refusal('Remote receipt mismatch: ' + key)
    image = files['UNQUALIFIED-coreboot.rom']
    if hashlib.sha256(image).hexdigest() != digest(receipt.get('sha256')) or len(image) != receipt.get('size'):
        raise Refusal('Remote image size or hash differs from its receipt.')
    if hashlib.sha256(files['generated.config']).hexdigest() != digest(receipt.get('config_sha256')):
        raise Refusal('Remote configuration hash differs from its receipt.')
    # Audit the actual downloaded configuration using the same board/policy checks.
    board = coreboot.board_record(request['target'])
    with tempfile.TemporaryDirectory() as directory:
        config = Path(directory) / 'config'
        config.write_bytes(files['generated.config'])
        values, _ = coreboot.parse_config(config)
        vendors = [key for key, value in values.items() if key.startswith('VENDOR_') and value == 'y']
        if len(vendors) != 1:
            raise Refusal('Remote configuration has no unique vendor.')
        coreboot.audit_config(config, request['target'], vendors[0], board['directory'].removeprefix('src/mainboard/'), request['allow_blobs'])
        if len(image) != int(values.get('ROM_SIZE', '0'), 0):
            raise Refusal('Remote ROM capacity differs from the downloaded configuration.')
    return files, receipt


def download(request, path, directory):
    run = refresh(request, path)
    if run.get('status') != 'completed' or run.get('conclusion') != 'success':
        raise Refusal('Only a completed, successful matching run can supply a candidate.')
    client = GitHub(request['repository'])
    artifacts = client.api('/actions/runs/' + str(run['id']) + '/artifacts')['artifacts']
    matches = [a for a in artifacts if a['name'] == 'coreboot-candidate-' + request['request_id']]
    if len(matches) != 1:
        raise Refusal('No unique candidate artifact is available.')
    artifact = matches[0]
    if (artifact.get('expired') is not False or type(artifact.get('size_in_bytes')) is not int
            or not 0 < artifact['size_in_bytes'] <= MAX_ARCHIVE
            or type(artifact.get('id')) is not int or artifact['id'] <= 0):
        raise Refusal('Artifact expired or exceeds the download limit.')
    remote_digest = artifact.get('digest', '')
    if not isinstance(remote_digest, str) or not remote_digest.startswith('sha256:'):
        raise Refusal('GitHub did not provide a SHA-256 artifact digest.')
    expected_hash = digest(remote_digest[7:])
    directory = Path(directory)
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix='remote-', dir=directory))
    archive = work / 'artifact.zip'
    client.api('/actions/artifacts/' + str(artifact['id']) + '/zip', destination=archive)
    if archive.stat().st_size != artifact['size_in_bytes'] or hashlib.sha256(archive.read_bytes()).hexdigest() != expected_hash:
        raise Refusal('Downloaded artifact differs from the GitHub size or digest. Retained for inspection only.')
    files, receipt = inspect_bundle(archive, request, run['id'])
    for name, data in files.items():
        with (work / name).open('xb') as stream:
            stream.write(data)
    return dict(receipt, path=str(work / 'UNQUALIFIED-coreboot.rom'), artifact_sha256=expected_hash,
                run_url=request['run_url'], flash_approved=False)
