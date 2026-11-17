"""Pinned, fresh coreboot build workspaces. Build success never approves flashing."""
from dataclasses import dataclass, field
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import stat
import subprocess
import tempfile
import threading
import time

from .layouts import read_image
from .prepare import DATA
from .safety import Refusal

DOCUMENTATION = 'https://doc.coreboot.org/tutorial/part1.html'
DEPENDENCIES = {
    'Debian / Ubuntu / Devuan': ['apt-get', 'install', 'bison', 'build-essential', 'curl', 'flex', 'git', 'gnat', 'libncurses-dev', 'libssl-dev', 'zlib1g-dev', 'pkgconf', 'python-is-python3'],
    'Fedora': ['dnf', 'install', 'git', 'make', 'gcc-gnat', 'flex', 'bison', 'xz', 'bzip2', 'gcc', 'gcc-c++', 'ncurses-devel', 'wget', 'zlib-devel', 'patch', 'openssl-devel', 'pkgconf-pkg-config'],
    'Arch Linux': ['pacman', '-S', '--needed', 'base-devel', 'curl', 'git', 'gcc-ada', 'ncurses', 'zlib', 'openssl', 'pkgconf'],
}
ARCHES = {'X86': 'i386', 'ARM': 'arm', 'ARM64': 'aarch64', 'RISCV': 'riscv', 'PPC64': 'ppc64'}
# Literal variable references present in the pinned upstream src/**/Kconfig* defaults.
CONFIG_REFERENCES = {
    'CONFIG_AMD_SOC_PACKAGE', 'CONFIG_BASEBOARD_DIR', 'CONFIG_CARRIER_DIR',
    'CONFIG_COREBOOT_ROMSIZE_KB', 'CONFIG_MAINBOARD_DIR', 'CONFIG_MAINBOARD_PART_NUMBER',
    'CONFIG_MAINBOARD_VENDOR', 'CONFIG_VARIANT_DIR', 'KERNELVERSION', 'MAINBOARDDIR',
    'MAINBOARD_DIR', 'VARIANT_DIR', 'VBOOT_SOURCE', 'obj', 'src', 'top',
}
LIMITATIONS = [
    'The exact source selector is checked; physical board identity and revision are not established.',
    'Upstream defaults are not a reviewed installation profile. Missing vendor inputs need the exact board documentation.',
    'Payload bootability, device-data preservation, flash layout, EC prerequisites and recovery remain unqualified.',
    'Upstream build scripts run as your user and can download dependencies. This is not a build sandbox or a reproducible-build certification.',
    'No firmware write or flash command is authorized by a successful build.',
]


@dataclass
class Control:
    cancel: threading.Event = field(default_factory=threading.Event)
    log: Path | None = None


@dataclass(frozen=True)
class Workspace:
    path: Path
    target: str
    revision: str
    vendor: str
    board_directory: str
    config_sha256: str
    allow_blobs: bool
    toolchains: tuple
    summary: dict

    @property
    def source(self):
        return self.path / 'source'


def environment():
    # Ignore ambient MAKEFLAGS, KCONFIG, compiler overrides and git URL rewrites.
    env = {k: os.environ[k] for k in ('HOME', 'USER', 'LOGNAME', 'HTTPS_PROXY', 'HTTP_PROXY', 'NO_PROXY', 'https_proxy', 'http_proxy', 'no_proxy') if k in os.environ}
    env.update(PATH='/usr/local/bin:/usr/bin:/bin', LANG='C.UTF-8',
               GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull,
               GIT_TERMINAL_PROMPT='0', GIT_CONFIG_COUNT='2',
               GIT_CONFIG_KEY_0='core.hooksPath', GIT_CONFIG_VALUE_0=os.devnull,
               GIT_CONFIG_KEY_1='protocol.file.allow', GIT_CONFIG_VALUE_1='never')
    return env


def command(argv, cwd, log, control=None, timeout=7200):
    """Bounded logs, no stdin/shell, and cancellation of the whole process group."""
    control = control or Control()
    if control.cancel.is_set():
        raise Refusal('Build operation cancelled. No output is approved for flashing.')
    control.log = Path(log)
    with control.log.open('x') as output:
        output.write(json.dumps({'argv': argv, 'cwd': str(cwd)}) + '\n')
        output.flush()
        process = subprocess.Popen(argv, cwd=cwd, env=environment(), stdin=subprocess.DEVNULL,
                                   stdout=output, stderr=subprocess.STDOUT, start_new_session=True)
        started = time.monotonic()
        reason = None
        try:
            while process.poll() is None:
                if control.cancel.is_set():
                    reason = 'Cancelled by user'
                elif time.monotonic() - started > timeout:
                    reason = 'Operation exceeded its time limit'
                elif os.fstat(output.fileno()).st_size > 64 * 1024**2:
                    reason = 'Operation exceeded its log size limit'
                if reason:
                    raise Refusal(f'{reason}. Retained workspace and log: {log}. Start a fresh configuration before retrying.')
                time.sleep(0.1)
        finally:
            if process.poll() is None:
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    pass
                # Children may survive their parent exiting; stop those too.
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait()
        if process.returncode:
            raise Refusal(f'coreboot operation failed (exit {process.returncode}). Read {log}. Check the board guide for missing vendor inputs; do not substitute another board or disable checks.')


def git(source, *args):
    return subprocess.check_output(['git', '-C', str(source), *args], env=environment(), text=True, stderr=subprocess.PIPE).strip()


def checked_tree(source, revision):
    if git(source, 'rev-parse', 'HEAD') != revision:
        raise Refusal('coreboot source revision changed; create a fresh pinned workspace.')
    if git(source, 'status', '--porcelain', '--untracked-files=normal', '--ignore-submodules=none'):
        raise Refusal('coreboot source or submodules have changed; create a fresh pinned workspace.')


def board_record(target):
    records = json.loads((DATA / 'boards.json').read_text())
    found = [b for b in records if b['project'] == 'coreboot' and b['id'] == target]
    if len(found) != 1 or not re.fullmatch(r'BOARD_[A-Z0-9_]+', target):
        raise Refusal('Choose one exact coreboot selector from the bundled inventory.')
    board = found[0]
    if not re.fullmatch(r'src/mainboard/[a-zA-Z0-9_-]+/[a-zA-Z0-9_-]+', board['directory']):
        raise Refusal('This source directory needs a reviewed configuration mapping.')
    return board


def parse_config(path):
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    except OSError as error:
        raise Refusal('Cannot open configuration as a regular file without following symlinks.') from error
    with os.fdopen(fd, 'rb') as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode) or not 0 < before.st_size <= 2 * 1024**2:
            raise Refusal('Configuration must be a bounded regular file, not a symlink or device.')
        raw = stream.read(2 * 1024**2 + 1)
        after = os.fstat(stream.fileno())
    if len(raw) != before.st_size or (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (after.st_size, after.st_mtime_ns, after.st_ctime_ns):
        raise Refusal('Configuration changed while reading.')
    values = {}
    for number, line in enumerate(raw.decode('utf-8').splitlines(), 1):
        if not line or line.startswith('#'):
            continue
        # Permit the upstream literal references, never Make functions or arbitrary variables.
        validation = line
        for reference in CONFIG_REFERENCES:
            validation = validation.replace('$(' + reference + ')', 'UPSTREAM_VARIABLE')
        match = re.fullmatch(r'CONFIG_([A-Za-z0-9_]+)=(y|n|m|0x[0-9a-fA-F]+|-?[0-9]+|"(?:[^"\\$`\x00-\x1f]|\\["\\])*")', validation)
        if not match or match[1] in values:
            raise Refusal(f'Configuration line {number} contains a duplicate or unsupported statement. Arbitrary Make/Kconfig edits are not accepted.')
        values[match[1]] = line.split('=', 1)[1]
    return values, hashlib.sha256(raw).hexdigest()


def audit_config(path, target, vendor, directory, allow_blobs):
    values, config_hash = parse_config(path)
    selectors = {b['id'] for b in json.loads((DATA / 'boards.json').read_text()) if b['project'] == 'coreboot'}
    enabled = {key for key in selectors if values.get(key) == 'y'}
    vendors = {key for key, value in values.items() if key.startswith('VENDOR_') and value == 'y'}
    if enabled != {target} or vendors != {vendor} or values.get('MAINBOARD_DIR') != json.dumps(directory):
        raise Refusal('Kconfig selected a different or ambiguous board/vendor/directory. No configuration or image is accepted.')
    if values.get('ANY_TOOLCHAIN') == 'y':
        raise Refusal('The unpinned system-toolchain override is not permitted.')
    if (values.get('USE_BLOBS') == 'y') != allow_blobs:
        raise Refusal('The generated binary-dependency policy differs from the explicit choice.')
    arches = tuple(sorted({tool for arch, tool in ARCHES.items() if values.get('ARCH_' + arch) == 'y'}))
    if not arches:
        raise Refusal('No supported cross-toolchain mapping exists for this configuration. Follow the board-specific build documentation.')
    summary = {key: value for key, value in values.items()
               if key in {'MAINBOARD_DIR', 'MAINBOARD_PART_NUMBER', 'ROM_SIZE', 'CBFS_SIZE', 'USE_BLOBS'}
               or (key.startswith(('ARCH_', 'PAYLOAD_')) and value == 'y')}
    return config_hash, arches, summary


def jobs_value(jobs):
    if type(jobs) is not int or not 1 <= jobs <= 64:
        raise Refusal('Build parallelism must be an integer from 1 to 64.')
    return str(jobs)


def configure(source, target, allow_blobs, confirmation, directory, control=None):
    board = board_record(target)
    if type(allow_blobs) is not bool or confirmation != 'CONFIGURE ' + target:
        raise Refusal('Configuration requires an explicit target and binary-dependency choice.')
    missing = [name for name in ('git', 'make', 'cc', 'bison', 'flex') if not shutil.which(name, path=environment()['PATH'])]
    if missing:
        raise Refusal('Missing configuration dependencies: ' + ', '.join(missing) + '. Use the coreboot dependency installer or follow ' + DOCUMENTATION)
    revision = json.loads((DATA / 'revisions.json').read_text())['coreboot']
    source = Path(source).resolve(strict=True)
    checked_tree(source, revision)
    directory = Path(directory).resolve()
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix='coreboot-', dir=directory))
    tree = work / 'source'
    # A real local clone, not hard links/alternates; ignored old outputs cannot leak in.
    command(['git', '-c', 'protocol.file.allow=always', 'clone', '--no-local', '--no-checkout', '--template=', str(source), str(tree)], directory, work / 'clone.log', control)
    command(['git', 'checkout', '--detach', revision], tree, work / 'checkout.log', control)
    command(['git', 'remote', 'set-url', 'origin', 'https://review.coreboot.org/coreboot.git'], tree, work / 'origin.log', control)
    checked_tree(tree, revision)
    vendor_file = tree / Path(board['directory']).parent / 'Kconfig.name'
    symbols = re.findall(r'^config (VENDOR_[A-Z0-9_]+)\s*$', vendor_file.read_text(), re.M)
    if len(symbols) != 1:
        raise Refusal('This vendor needs a reviewed Kconfig selector mapping.')
    vendor = symbols[0]
    directory_name = board['directory'].removeprefix('src/mainboard/')
    seed = f'CONFIG_{vendor}=y\nCONFIG_{target}=y\n'
    seed += 'CONFIG_USE_BLOBS=y\n' if allow_blobs else '# CONFIG_USE_BLOBS is not set\n'
    (tree / '.config').write_text(seed)
    (work / 'seed.config').write_text(seed)
    command(['make', 'olddefconfig', 'UPDATED_SUBMODULES=1'], tree, work / 'configure.log', control, timeout=300)
    config_hash, arches, summary = audit_config(tree / '.config', target, vendor, directory_name, allow_blobs)
    workspace = Workspace(work, target, revision, vendor, directory_name, config_hash, allow_blobs, arches, summary)
    (work / 'configuration.json').write_text(json.dumps({
        'target': target, 'revision': revision, 'config_sha256': config_hash,
        'allow_blobs': allow_blobs, 'toolchains': arches, 'summary': summary,
        'status': 'unqualified-upstream-defaults', 'flash_approved': False, 'limitations': LIMITATIONS,
    }, indent=2) + '\n')
    return workspace


def verify_workspace(workspace, target):
    if workspace.target != target:
        raise Refusal('Build workspace belongs to a different target.')
    if workspace.revision != json.loads((DATA / 'revisions.json').read_text())['coreboot']:
        raise Refusal('Build workspace does not use the bundled coreboot revision pin.')
    checked_tree(workspace.source, workspace.revision)
    config_hash, arches, summary = audit_config(workspace.source / '.config', target, workspace.vendor,
                                               workspace.board_directory, workspace.allow_blobs)
    if config_hash != workspace.config_sha256 or arches != workspace.toolchains or summary != workspace.summary:
        raise Refusal('Configuration changed after review. Create a fresh configuration; build execution is blocked.')
    if (workspace.path / 'operation-incomplete').exists():
        raise Refusal('A previous operation failed or was cancelled. Keep its logs and create a fresh workspace before retrying.')


def build(workspace, target, jobs, operation, confirmation, control=None):
    parallelism = jobs_value(jobs)
    if operation not in ('toolchain', 'image') or confirmation != f'BUILD {operation} {target}':
        raise Refusal('Build requires explicit operation and target confirmation.')
    verify_workspace(workspace, target)
    incomplete = workspace.path / 'operation-incomplete'
    incomplete.touch(exist_ok=False)
    logs = Path(tempfile.mkdtemp(prefix=operation + '-', dir=workspace.path))
    if operation == 'toolchain':
        for arch in workspace.toolchains:
            command(['make', 'crossgcc-' + arch, 'CPUS=' + parallelism, 'UPDATED_SUBMODULES=1'], workspace.source, logs / (arch + '.log'), control)
    else:
        command(['make', '-j' + parallelism], workspace.source, logs / 'build.log', control)
    # Check inputs again before releasing any candidate, including make's automatic config updates.
    incomplete.unlink()
    try:
        verify_workspace(workspace, target)
        limitations = list(LIMITATIONS)
        if workspace.summary.get('PAYLOAD_NONE') == 'y':
            limitations.insert(0, 'This configuration has no payload. Its output cannot boot an operating system; a board-specific payload integration is still required.')
        result = {'project': 'coreboot', 'target': target, 'revision': workspace.revision,
                  'config_sha256': workspace.config_sha256, 'allow_blobs': workspace.allow_blobs,
                  'toolchains': workspace.toolchains, 'log_directory': str(logs),
                  'status': operation + '-completed-unqualified', 'flash_approved': False,
                  'configuration': workspace.summary, 'limitations': limitations}
        if operation == 'image':
            data = read_image(workspace.source / 'build/coreboot.rom')
            expected = workspace.summary.get('ROM_SIZE')
            if not expected or len(data) != int(expected, 0):
                raise Refusal('Built image size differs from the reviewed configuration; output is quarantined.')
            output = logs / 'UNQUALIFIED-coreboot.rom'
            with output.open('xb') as stream:
                stream.write(data)
            result.update(path=str(output), sha256=hashlib.sha256(data).hexdigest(), size=len(data),
                          submodules=git(workspace.source, 'submodule', 'status', '--recursive'))
        (logs / 'receipt.json').write_text(json.dumps(result, indent=2) + '\n')
        return result
    except BaseException:
        incomplete.touch(exist_ok=True)
        raise


def install_dependencies(profile, confirmation, log):
    if profile not in DEPENDENCIES or confirmation != 'INSTALL coreboot ' + profile:
        raise Refusal('Dependency installation requires explicit confirmation of the host distribution.')
    # Package managers retain their own final interactive confirmation; no automatic yes.
    argv = ['sudo', '--', *DEPENDENCIES[profile]]
    with Path(log).open('x') as receipt:
        receipt.write(json.dumps({'argv': argv, 'status': 'started'}) + '\n')
        receipt.flush()
        # Keep package-manager output and prompts on the handed-off terminal.
        result = subprocess.run(argv, env=environment())
        receipt.write(json.dumps({'returncode': result.returncode}) + '\n')
    if result.returncode:
        raise Refusal('Dependency installation did not complete. Review the terminal output and command receipt: ' + str(log))
    return {'status': 'dependency-installer-completed', 'log': str(log)}
