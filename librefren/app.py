"""Guided curses application; optional CLI utilities share its safety checks."""
import argparse
from collections import Counter
import curses
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import tarfile
import textwrap
import time
from concurrent.futures import ThreadPoolExecutor

from .guides import CHROMEBOOK, guide_for
from .releases import RELEASES, archive_name, fetch
from .prepare import dependencies, fetch_source, inject, stage_variant
from .layouts import compare_images, format_report
from .session import Session
from . import coreboot, remote
from .safety import Refusal, check_backups, detect, exact_candidates, flash_gate, inspect_variants

DATA = Path(__file__).parent / "data"
ROOT = Path(__file__).resolve().parents[1]


def state_directory():
    base = Path(os.environ.get('XDG_DATA_HOME', ''))
    if not base.is_absolute():
        base = Path.home() / '.local/share'
    return base / 'librefren'


def load(name):
    path = DATA / (name + ".json")
    return json.loads(path.read_text()) if path.exists() else []


def clean(text):
    return ''.join(c if c.isprintable() or c == '\n' else '?' for c in str(text))


def research(query):
    findings = [s for s in load('findings') if query.casefold() in json.dumps(s).casefold()]
    references = [s for s in load('references') if query.strip() and query.casefold() in s['url'].casefold()][:50]
    database = ROOT / "research/knowledge.sqlite"
    if database.exists() and query.strip():
        with sqlite3.connect(f"file:{database}?mode=ro", uri=True) as db:
            # Quote each word to prevent FTS syntax from becoming an expression.
            term = ' AND '.join('"' + w.replace('"', '""') + '"' for w in query.split())
            rows = db.execute("SELECT project,title,url,path FROM documents WHERE documents MATCH ? LIMIT 200", (term,)).fetchall()
        return findings + [dict(zip(('project', 'title', 'url', 'path'), row), status='indexed-unreviewed') for row in rows] + references
    return findings + [s for s in load('sources') if query.casefold() in (s['title'] + ' ' + s['url']).casefold()][:200] + references


class TUI:
    def __init__(self, screen):
        self.screen = screen
        self.boards = load('boards')
        self.release_inventory = load('release-inventory')
        self.hardware = detect()
        self.selected = None
        self.receipt = None
        self.session = None
        self.sources = {}
        self.selected_variant = None
        self.backup_result = None
        self.layout_report = None
        self.coreboot_workspace = None
        self.colour = 0
        try:
            curses.curs_set(0)
        except curses.error:
            pass
        if curses.has_colors():
            curses.start_color()
            # Values are from Libreboot global.css: #280b22, #4e324e, #eedd ee.
            if curses.can_change_color() and curses.COLORS >= 16:
                for n, rgb in ((10, (40, 11, 34)), (11, (78, 50, 78)), (12, (238, 221, 238))):
                    curses.init_color(n, *(round(v * 1000 / 255) for v in rgb))
                curses.init_pair(1, 12, 10)
                curses.init_pair(2, 12, 11)
            else:
                curses.init_pair(1, curses.COLOR_WHITE, curses.COLOR_BLACK)
                curses.init_pair(2, curses.COLOR_WHITE, curses.COLOR_MAGENTA)
            self.colour = curses.color_pair(1)
            self.screen.bkgd(' ', self.colour)

    def line(self, y, text, attr=0):
        h, w = self.screen.getmaxyx()
        if 0 <= y < h - 1 and w > 4:
            try:
                self.screen.addnstr(y, 2, clean(text), w - 4, attr)
            except curses.error:
                pass

    def frame(self, title):
        self.screen.erase()
        self.line(1, 'LIBREFREN', curses.A_BOLD)
        self.line(2, 'Libreboot / RBoot / coreboot     |     Preparation preview · writes locked')
        self.line(4, title, curses.A_BOLD)

    def prompt(self, title):
        value = ''
        try:
            curses.curs_set(1)
        except curses.error:
            pass
        try:
            while True:
                self.frame('Input')
                h, w = self.screen.getmaxyx()
                instructions = textwrap.wrap(title, max(10, w - 6))
                for row, line in enumerate(instructions[:max(1, h - 12)]):
                    self.line(6 + row, line)
                input_row = min(h - 5, 7 + len(instructions))
                self.line(input_row, '> ' + value[-max(1, w - 8):])
                self.line(h - 3, 'Enter to accept · Esc to cancel')
                self.screen.refresh()
                key = self.screen.get_wch()
                if key in ('\n', '\r'):
                    return value
                if key == '\x1b':
                    return None
                if key in (curses.KEY_BACKSPACE, '\b', '\x7f'):
                    value = value[:-1]
                elif isinstance(key, str) and key.isprintable() and len(value) < 512:
                    value += key
        finally:
            try:
                curses.curs_set(0)
            except curses.error:
                pass

    def menu(self, title, labels, searchable=False):
        selected, query = 0, ''
        while True:
            matching = [i for i, label in enumerate(labels) if query.casefold() in label.casefold()]
            selected = max(0, min(selected, len(matching) - 1))
            h, w = self.screen.getmaxyx()
            page = max(1, h - 10)
            start = selected // page * page
            self.frame(title + (f'  / {query}' if query else ''))
            for row, index in enumerate(matching[start:start + page]):
                active = start + row == selected
                self.line(6 + row, ('› ' if active else '  ') + labels[index], curses.A_REVERSE if active else 0)
            self.line(h - 3, f'{len(matching)} entries · ↑↓/jk · Enter · Esc back' + (' · / search' if searchable else ''))
            self.screen.refresh()
            key = self.screen.getch()
            if key in (27, ord('q')):
                return None
            if key in (curses.KEY_DOWN, ord('j')):
                selected = min(selected + 1, len(matching) - 1)
            if key in (curses.KEY_UP, ord('k')):
                selected = max(selected - 1, 0)
            if key == curses.KEY_NPAGE:
                selected = min(selected + page, len(matching) - 1)
            if key == curses.KEY_PPAGE:
                selected = max(selected - page, 0)
            if key in (10, 13) and matching:
                return matching[selected]
            if key == ord('/') and searchable:
                query = self.prompt('Filter entries (empty clears filter)') or ''
                selected = 0

    def view(self, title, body):
        offset = 0
        while True:
            h, w = self.screen.getmaxyx()
            lines = []
            for paragraph in clean(body).splitlines():
                lines.extend(textwrap.wrap(paragraph, max(10, w - 6), replace_whitespace=False) or [''])
            page = max(1, h - 10)
            offset = min(offset, max(0, len(lines) - page))
            self.frame(title)
            for row, line in enumerate(lines[offset:offset + page]):
                self.line(6 + row, line)
            self.line(h - 3, '↑↓ / PgUp PgDn scroll · Esc / q / Enter back')
            self.screen.refresh()
            key = self.screen.getch()
            if key in (27, ord('q'), 10, 13):
                return
            if key in (curses.KEY_DOWN, ord('j')):
                offset += 1
            if key in (curses.KEY_UP, ord('k')):
                offset = max(0, offset - 1)
            if key == curses.KEY_NPAGE:
                offset += page
            if key == curses.KEY_PPAGE:
                offset = max(0, offset - page)

    def guides(self, steps):
        while True:
            index = self.menu('Manual steps — acknowledgements do not certify safety', [s[0] for s in steps])
            if index is None:
                return
            title, body, url = steps[index]
            self.view(title, body + '\n\nReference:\n' + url + '\n\nIf this step cannot be completed or the guide conflicts with your hardware, stop here. No later step is automatically approved.')
            action = self.menu('Record a manual observation (optional)', ['Continue reading', 'Record observation or unresolved question'])
            if action == 1:
                note = self.prompt('Observation (do not enter passwords, keys or serial numbers)')
                if note:
                    if self.session is None:
                        self.session = Session(state_directory() / 'sessions')
                    self.session.record('manual-observation', {'target': self.selected['id'] if self.selected else None,
                                                             'step': title, 'source': url, 'note': note,
                                                             'status': 'user-reported-unverified'})
                    self.view('Observation recorded', 'Saved to ' + str(self.session.path) + '\nThis observation does not unlock flashing or satisfy an unresolved machine check.')

    def show_hardware(self):
        fields = [('sys_vendor', 'Manufacturer'), ('product_name', 'Product'),
                  ('product_version', 'Product version'), ('board_name', 'Board'),
                  ('board_version', 'Board version'), ('bios_vendor', 'Current firmware'),
                  ('bios_version', 'Firmware version'), ('architecture', 'Architecture')]
        body = '\n'.join(f'{label}: {self.hardware.get(key, "unknown")}' for key, label in fields)
        candidates = exact_candidates(self.hardware, self.boards)
        body += '\n\nExact name candidates (identity still needs verification):\n'
        body += '\n'.join(b['project'] + ': ' + b['id'] for b in candidates) or 'None found.'
        body += '\n\nDetection describes this running host. For an external motherboard, identify the target from its own markings and documentation. Names alone never authorize firmware preparation or flashing.'
        self.view('Detected hardware', body)

    def choose_target(self):
        scope = self.menu('Which device are you preparing?', ['This Linux host', 'A separate device or motherboard'])
        if scope is None:
            return
        project_index = self.menu('Choose a firmware project', ['Libreboot', 'RBoot', 'coreboot'])
        if project_index is None:
            return
        project = ('libreboot', 'rboot', 'coreboot')[project_index]
        boards = [b for b in self.boards if b['project'] == project]
        if scope == 0:
            candidates = exact_candidates(self.hardware, boards)
            if candidates:
                selection = self.menu('Exact name candidates — not verified hardware matches',
                                      [b['id'] for b in candidates] + ['Browse the full project inventory'])
                if selection is None:
                    return
                if selection < len(candidates):
                    boards = [candidates[selection]]
        index = self.menu('Select exact target · verify board revision and flash capacity',
                          [b['id'] + ' | ' + self.availability(b) + ' | ' + ', '.join(b.get('names', [])) for b in boards], True)
        if index is None:
            return
        selected = boards[index]
        confirmation = self.menu('Use ' + selected['id'] + ' for research and preparation?',
                                 ['Go back and check the identity', 'Use this target; physical identity is still unverified'])
        if confirmation != 1:
            return
        self.selected = selected
        self.receipt = self.selected_variant = self.backup_result = None
        self.layout_report = None
        self.coreboot_workspace = None

    def availability(self, board):
        if board['project'] == 'coreboot':
            return 'source build required'
        catalog = self.release_inventory or {}
        project = catalog.get('projects', {}).get(board['project'], {})
        entry = project.get('targets', {}).get(board['id'], {})
        if project.get('release') != RELEASES[board['project']][0]:
            return 'release availability unchecked'
        if entry.get('status') == 'listed-with-signature':
            return 'binary listed in ' + project['release']
        return 'no binary in saved release listing'

    def file_picker(self, title, start=None):
        directory = Path(start or Path.home()).expanduser().resolve()
        while True:
            entries = sorted((p for p in directory.iterdir() if not p.is_symlink()),
                             key=lambda p: (not p.is_dir(), p.name.casefold()))
            labels = ['../ (parent directory)', 'Enter a different directory']
            labels += [p.name + ('/' if p.is_dir() else '') for p in entries]
            index = self.menu(title + ' · ' + str(directory), labels, True)
            if index is None:
                return None
            if index == 0:
                directory = directory.parent
            elif index == 1:
                path = self.prompt('Directory to browse')
                if path:
                    candidate = Path(path).expanduser().resolve(strict=True)
                    if not candidate.is_dir():
                        raise Refusal('Choose a directory to browse.')
                    directory = candidate
            else:
                chosen = entries[index - 2]
                if chosen.is_dir():
                    directory = chosen
                elif chosen.is_file():
                    return chosen

    def backup_check(self):
        self.view('Check existing firmware backups',
                  'Obtain at least two independent reads using the exact board documentation first. LibreFren does not read a firmware chip. Select two existing backup files below. Matching bytes do not prove the correct chip was read.\n\nFor multi-chip boards, compare the two reads of each chip separately; do not mix full images and individual chip dumps.')
        size = self.prompt('Expected capacity of this chip in bytes, from verified chip documentation')
        if not size:
            return
        if not size.isdecimal() or not 0 < int(size) <= 128 * 1024**2:
            raise Refusal('Enter a capacity between 1 and 134217728 bytes.')
        first = self.file_picker('Select the first independent read')
        if first is None:
            return
        second = self.file_picker('Select the second independent read', first.parent)
        if second is None:
            return
        self.backup_result = check_backups([first, second], int(size))
        self.view('Backup files contain matching bytes',
                  f'First: {first}\nSecond: {second}\nSHA-256: {self.backup_result["sha256"]}\n\n'
                  + self.backup_result['limitation'] + '\nThis check does not unlock flashing.')

    def background_job(self, title, action):
        # Only tasks without interactive input run here. sudo retains its own
        # terminal prompt through terminal_job; passwords never enter curses.
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(action)
            self.screen.timeout(150)
            tick = 0
            try:
                while not future.done():
                    self.frame(title)
                    self.line(7, 'Working' + '.' * (tick % 4))
                    self.line(9, 'Please wait for the operation to finish. No firmware writes are performed.')
                    self.screen.refresh()
                    self.screen.getch()
                    tick += 1
                return future.result()
            finally:
                self.screen.timeout(-1)

    def compare_layouts(self):
        self.view('Compare backup and candidate layouts',
                  'Select a complete backup image and a candidate image. This inspection reads files only: it does not copy device data or write firmware. For multi-chip devices, individual chip dumps cannot replace a correctly assembled full image.\n\nIFD inspection covers the five common region registers only; additional regions, hardware permissions and chipset straps remain unresolved. FMAP checks do not prove board identity or authenticate a locally selected image.')
        context_index = self.menu('Choose the comparison requirements',
                                  ['RBoot vendor-region preservation', 'Chromebook device-data preservation', 'General layout comparison'])
        if context_index is None:
            return
        backup = self.file_picker('Select the complete original backup image')
        if backup is None:
            return
        candidate, expected_hash = None, None
        if self.selected_variant:
            choice = self.menu('Choose the candidate image', ['Use this session’s inspection copy', 'Browse for another local image'])
            if choice is None:
                return
            if choice == 0:
                candidate = Path(self.selected_variant['path'])
                expected_hash = self.selected_variant['sha256']
        if candidate is None:
            candidate = self.file_picker('Select the candidate image', backup.parent)
        if candidate is None:
            return
        context = ('rboot', 'chromebook', 'general')[context_index]
        size_match = re.search(r'_(\d+)mb$', self.selected['id']) if self.selected else None
        expected_size = int(size_match[1]) * 1024**2 if size_match else None
        report = self.background_job('Compare image layouts without modifying files',
                                     lambda: compare_images(backup, candidate, context, expected_size))
        if expected_hash is not None and report['candidate']['sha256'] != expected_hash:
            self.layout_report = None
            raise Refusal('The staged variant changed after extraction. Stage it again from its authenticated/prepared archive before comparing it as this session’s candidate.')
        # Session metadata is evidence only, and never consumed by flash_gate.
        if self.session is None:
            self.session = Session(state_directory() / 'sessions')
        self.session.record('layout-comparison', {'target': self.selected['id'] if self.selected else None,
                                                 'backup_path': str(backup), 'candidate_path': str(candidate), 'report': report})
        self.layout_report = report
        self.view('Layout evidence — flashing remains blocked', format_report(report)
                  + '\n\nReport recorded in: ' + str(self.session.path))

    def coreboot_job(self, title, action):
        control = coreboot.Control()
        started = time.monotonic()
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(action, control)
            self.screen.timeout(150)
            try:
                while not future.done():
                    self.frame(title)
                    self.line(6, f'Elapsed: {int(time.monotonic() - started)} seconds · no firmware writes')
                    self.line(8, 'Stopping the build…' if control.cancel.is_set() else 'Esc to cancel this operation')
                    if control.log and control.log.exists():
                        self.line(10, 'Log: ' + str(control.log))
                        with control.log.open('rb') as stream:
                            stream.seek(max(0, control.log.stat().st_size - 2048))
                            lines = stream.read(2048).decode('utf-8', errors='replace').splitlines()
                        for row, line in enumerate(lines[-max(1, self.screen.getmaxyx()[0] - 15):]):
                            self.line(12 + row, line)
                    self.screen.refresh()
                    if self.screen.getch() == 27:
                        control.cancel.set()
                return future.result()
            except BaseException:
                control.cancel.set()
                raise
            finally:
                self.screen.timeout(-1)

    def coreboot_dependencies(self):
        profiles = list(coreboot.DEPENDENCIES)
        index = self.menu('coreboot host dependencies · choose your distribution', profiles + ['Other distribution / manual instructions'])
        if index is None:
            return
        if index == len(profiles):
            self.view('coreboot dependency instructions', 'Install the compiler, matching Ada compiler, make, git, bison, flex, curl, OpenSSL and zlib development headers, and pkgconf using your distribution’s packages. Upstream requirements: ' + coreboot.DOCUMENTATION)
            return
        profile = profiles[index]
        self.view('Review system package installation', 'Host profile: ' + profile + '\n\n'
                  + ' '.join(coreboot.DEPENDENCIES[profile]) + '\n\nThis uses sudo and changes system packages. Verify the selected distribution. The package manager will show its own confirmation.\n\n' + coreboot.DOCUMENTATION)
        confirmation = self.prompt('Type INSTALL coreboot ' + profile)
        if confirmation != 'INSTALL coreboot ' + profile:
            return
        import tempfile
        directory = state_directory() / 'dependencies'
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        log = Path(tempfile.mkdtemp(prefix='coreboot-', dir=directory)) / 'installation.json'
        result = self.terminal_job(lambda: coreboot.install_dependencies(profile, confirmation, log))
        self.view('Dependency installer completed', 'Command receipt: ' + result['log'])

    def remote_build(self):
        target = self.selected['id']
        directory = state_directory() / 'remote-requests'
        while True:
            action = self.menu('GitHub Actions · ' + target, [
                'Start a remote build', 'Resume / inspect a saved request',
                'Setup, privacy and usage instructions', 'Back'])
            if action is None or action == 3:
                return
            try:
                if action == 2:
                    self.view('GitHub Actions setup', remote.HELP)
                    continue
                if action == 0:
                    self.view('Build on GitHub Actions', remote.HELP)
                    repo = self.prompt('Repository owner/name (your LibreFren repository or fork)')
                    if not repo:
                        continue
                    choice = self.menu('Permit upstream binary repositories?',
                                       ['No', 'Yes — review upstream licenses and board requirements'])
                    if choice is None:
                        continue
                    request = self.background_job('Check repository and workflow', lambda: remote.plan(repo.strip(), target, choice == 1))
                    self.view('Review remote build request',
                              json.dumps(request, indent=2) + '\n\nThis runs upstream default settings on GitHub and consumes Actions resources. Hardware options remain locked. The artifact is for inspection only. Repository code at the displayed commit is trusted to run the build; inspect your fork before proceeding. Closing LibreFren leaves the remote job running.')
                    confirmation = self.prompt('Type BUILD ON GITHUB ' + target)
                    if confirmation != 'BUILD ON GITHUB ' + target:
                        continue
                    path = self.background_job('Dispatch remote build', lambda: remote.dispatch(request, confirmation, directory))
                else:
                    saved = []
                    for path in sorted(directory.glob('*.json'), key=lambda p: p.stat().st_mtime, reverse=True)[:100]:
                        try:
                            request = remote.load_request(path)
                            if request['target'] == target:
                                saved.append((path, request))
                        except (Refusal, OSError, ValueError, KeyError, TypeError):
                            continue
                    if not saved:
                        self.view('No saved requests for this target', 'Start a remote build first. Requests remain available after restarting LibreFren.')
                        continue
                    selected = self.menu('Choose a saved remote request',
                                         [r['repository'] + ' · ' + r['request_id'][:12] + ' · ' + r['status'] for _, r in saved])
                    if selected is None:
                        continue
                    path, request = saved[selected]
                self.remote_request(request, path)
            except (Refusal, OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
                self.view('Remote build stopped', str(error) + '\n\nCheck saved requests and GitHub Actions before retrying a dispatch. A network failure can occur after GitHub has accepted it.')

    def remote_request(self, request, path):
        while True:
            action = self.menu('Remote build · ' + request['status'], [
                'Refresh run status', 'Review request and GitHub link',
                'Download and inspect completed candidate', 'Cancel remote build',
                'Back (leave remote build running)'])
            if action is None or action == 4:
                return
            if action == 0:
                self.background_job('Refresh GitHub run', lambda: remote.refresh(request, path))
                self.view('Remote build status', json.dumps(request, indent=2))
            elif action == 1:
                self.view('Remote request · flashing remains blocked', json.dumps(request, indent=2)
                          + '\n\nWorkflow and logs: https://github.com/' + request['repository'] + '/actions/workflows/' + remote.WORKFLOW
                          + '\n\nSaved request: ' + str(path))
            elif action == 2:
                if request['target'] != self.selected['id']:
                    raise Refusal('This remote build belongs to another selected target.')
                self.selected_variant = self.layout_report = None
                result = self.background_job('Download and validate remote artifact',
                    lambda: remote.download(request, path, state_directory() / 'coreboot-remote'))
                self.selected_variant = result
                if self.session is None:
                    self.session = Session(state_directory() / 'sessions')
                self.session.record('coreboot-remote-candidate', result)
                self.view('Candidate downloaded · flashing remains blocked', json.dumps(result, indent=2))
            elif action == 3:
                self.background_job('Identify remote run to cancel', lambda: remote.refresh(request, path))
                confirmation = self.prompt('Type CANCEL ' + str(request['run_id']))
                if confirmation != 'CANCEL ' + str(request['run_id']):
                    continue
                self.background_job('Request remote cancellation', lambda: remote.cancel(request, path, confirmation))
                self.view('Cancellation requested', 'Refresh to confirm GitHub has stopped the run. Closing this window alone does not cancel it.')

    def coreboot_build(self):
        if self.selected['project'] != 'coreboot':
            raise Refusal('Select an exact coreboot target to use the source build workflow.')
        target = self.selected['id']
        jobs = 1
        while True:
            workspace = self.coreboot_workspace
            action = self.menu('coreboot · ' + target + ' · unqualified build workspace', [
                'Read build requirements and limitations',
                'Review / install host dependencies',
                'Create fresh configuration for this exact target',
                'Review locked configuration' + (' [available]' if workspace else ''),
                f'Choose build parallelism [{jobs} job(s)]',
                'Build pinned upstream cross-toolchain',
                'Compile an unqualified image', 'Build on GitHub Actions / resume remote build', 'Back'])
            if action is None or action == 8:
                return
            try:
                if action == 7:
                    self.remote_build()
                elif action == 0:
                    self.view('coreboot build requirements', '\n\n'.join(coreboot.LIMITATIONS)
                              + '\n\nFetch the pinned source, install host dependencies, create a fresh configuration, review it, build its cross-toolchain, then compile. Expect substantial disk use and long builds. Esc cancels a running operation. Hardware settings are locked. Changing the binary-dependency choice requires a new workspace.\n\nFor missing vendor files or unsupported defaults, follow the exact board documentation; LibreFren will retain logs and stop.\n\n' + coreboot.DOCUMENTATION)
                elif action == 1:
                    self.coreboot_dependencies()
                elif action == 2:
                    source = self.sources.get('coreboot')
                    if not source:
                        self.view('Fetch pinned source first', 'Return to the guided workflow and choose Fetch pinned upstream source.')
                        continue
                    blobs = self.menu('Allow binary-only upstream dependencies in this configuration?',
                                      ['Do not permit binary-only repositories', 'Permit upstream binary repositories; review their licenses and board requirements'])
                    if blobs is None:
                        continue
                    confirmation = self.prompt('Run pinned upstream Kconfig in a new workspace. Type CONFIGURE ' + target)
                    if confirmation != 'CONFIGURE ' + target:
                        continue
                    self.coreboot_workspace = None
                    self.selected_variant = self.layout_report = None
                    self.coreboot_workspace = self.coreboot_job('Generate exact-target coreboot configuration',
                        lambda control: coreboot.configure(source, target, blobs == 1, confirmation, state_directory() / 'coreboot', control))
                    self.selected_variant = self.layout_report = None
                    self.view('Configuration generated — review before building', json.dumps(self.coreboot_workspace.summary, indent=2)
                              + '\n\nWorkspace: ' + str(self.coreboot_workspace.path) + '\n\nUpstream defaults are not a hardware-qualified installation profile.')
                elif action == 3:
                    if not workspace:
                        raise Refusal('Create a fresh configuration first.')
                    coreboot.verify_workspace(workspace, target)
                    self.view('Locked configuration · ' + workspace.config_sha256,
                              (workspace.source / '.config').read_text() + '\n\n' + '\n\n'.join(coreboot.LIMITATIONS))
                elif action == 4:
                    value = self.prompt('Parallel build jobs, 1–64. More jobs use more RAM; default is 1.')
                    if value is not None:
                        if not value.isdecimal():
                            raise Refusal('Enter an integer from 1 to 64.')
                        coreboot.jobs_value(int(value))
                        jobs = int(value)
                else:
                    if not workspace:
                        raise Refusal('Create and review a fresh configuration first.')
                    operation = 'toolchain' if action == 5 else 'image'
                    confirmation = self.prompt(f'Run upstream {operation} build scripts and their downloads as your user. Output remains unqualified. Type BUILD {operation} {target}')
                    if confirmation != f'BUILD {operation} {target}':
                        continue
                    self.selected_variant = self.layout_report = None
                    result = self.coreboot_job('Build coreboot ' + operation,
                        lambda control: coreboot.build(workspace, target, jobs, operation, confirmation, control))
                    if operation == 'image':
                        self.selected_variant = result
                        self.layout_report = None
                    if self.session is None:
                        self.session = Session(state_directory() / 'sessions')
                    self.session.record('coreboot-' + operation, result)
                    self.view('Build completed — flashing remains blocked', json.dumps(result, indent=2))
            except (Refusal, OSError, ValueError, subprocess.SubprocessError) as error:
                self.view('Build stopped · no flash approval', str(error))

    def download(self):
        if not self.selected or self.selected['project'] == 'coreboot':
            raise Refusal('Select an exact Libreboot or RBoot target first. coreboot requires a board-specific source build.')
        expected = 'DOWNLOAD ' + self.selected['id']
        self.view('Review exact release availability', self.availability(self.selected)
                  + '\n\nAvailability is a saved directory observation, not firmware authentication or hardware approval. The download checks the live listing again. If this target is absent, use its source/manual workflow; no nearby model, capacity or release will be substituted.')
        release = RELEASES[self.selected['project']][0]
        answer = self.prompt('Release ' + release + ': ' + archive_name(self.selected['project'], self.selected['id'])
                             + '. Download this exact archive for preparation only. Type ' + expected)
        if answer != expected:
            return
        self.receipt = self.background_job('Download and authenticate the exact target',
            lambda: fetch(self.selected['project'], self.selected['id'], state_directory() / 'downloads'))
        self.selected_variant = None
        self.layout_report = None
        self.view('Publisher signature verified', 'Target: ' + self.selected['id'] + '\nArchive: '
                  + self.receipt['archive'] + '\n\nThe downloaded archive still needs its preparation checks. Authentication proves publisher provenance, not suitability for your physical device.')

    def terminal_job(self, action):
        curses.def_prog_mode()
        curses.endwin()
        try:
            result = action()
            print('Operation finished. Returning to LibreFren.')
            return result
        finally:
            input('Press Enter to return...')
            curses.reset_prog_mode()
            self.screen.refresh()

    def preparation(self, action=None):
        if not self.selected:
            raise Refusal('Select an exact target first.')
        project, target = self.selected['project'], self.selected['id']
        if action is None:
            action = self.menu('Preparation — outputs remain unqualified for flashing', ['Install build dependencies', 'Prepare authenticated Libreboot archive', 'Select and extract a prepared variant', 'Configure and build coreboot', 'Fetch the pinned upstream source'])
        if action is None:
            return
        if action == 4:
            answer = self.prompt(f'Type FETCH {project} to download its pinned source (no build scripts run)')
            if answer == f'FETCH {project}':
                result = self.background_job('Fetch the pinned upstream source', lambda: fetch_source(project, state_directory() / 'sources'))
                self.sources[project] = result['source']
                self.view('Source ready for this session', 'Checkout: ' + result['source'] + '\nRevision: '
                          + result['revision'] + '\n\nLibreFren will use this checkout for the next preparation steps. No build scripts have run.')
            return
        if action == 3:
            self.coreboot_build()
            return
        if action == 2:
            if not self.receipt or not (self.receipt['status'] == 'upstream-preparation-completed-unqualified'
                                       or (project == 'rboot' and self.receipt['status'] == 'authenticated-download-only')):
                raise Refusal('Libreboot requires preparation first. RBoot requires an authenticated archive; its variants are inspection copies only.')
            variants = self.receipt['variants']
            idx = self.menu('Choose an actual variant for inspection — not flash approval', [v['path'] for v in variants])
            if idx is not None:
                output = self.background_job('Recheck the archive and stage the selected variant',
                    lambda: stage_variant(self.receipt, project, target, variants[idx]['path'], state_directory() / 'inspection'))
                self.selected_variant = output
                self.layout_report = None
                self.view('Inspection copy created — not a flashable-image approval', 'File: ' + output['path']
                          + '\nSHA-256: ' + output['sha256'] + '\n\n' + output['limitation']
                          + '\n\nNext: compare this image with the complete original backup using the layout comparison step.')
            return
        if project == 'coreboot':
            if action == 0:
                self.coreboot_dependencies()
            else:
                self.coreboot_build()
            return
        source = self.sources.get(project)
        if not source:
            self.view('Fetch the project source first', 'Use “Fetch pinned upstream source” in the preparation workflow. LibreFren will remember its path for the rest of this session.')
            return
        if not source:
            return
        if action == 0:
            profiles = Path(source) / 'config/dependencies'
            if not profiles.is_dir():
                raise Refusal('Dependency profiles not found in that source tree.')
            names = sorted(p.name for p in profiles.iterdir() if p.is_file())
            idx = self.menu('Select the exact host distribution profile', names)
            if idx is None:
                return
            profile = names[idx]
            self.view('Review system package changes', (profiles / profile).read_text() + '\n\nThe selected upstream dependency installer will run through sudo and may add system packages. Confirm only if this profile matches your distribution.')
            confirmation = self.prompt(f'Type INSTALL {project} {profile} to install dependencies')
            if confirmation:
                import tempfile
                log = Path(tempfile.mkdtemp(prefix='librefren-deps-')) / 'dependencies.log'
                result = self.terminal_job(lambda: dependencies(project, source, profile, confirmation, log))
                self.view('Dependency installer finished', 'Review the installation log: ' + result['log'])
        else:
            if not self.receipt:
                raise Refusal('Download and authenticate an archive first.')
            mac = self.prompt('MAC choice: random, or the target device’s full unicast MAC address')
            confirmation = self.prompt(f'Type PREPARE {target} to run upstream preparation and vendor downloads')
            if mac and confirmation:
                self.receipt = self.background_job('Prepare the authenticated Libreboot archive', lambda: inject(project, target, self.receipt['archive'], source, mac, confirmation, state_directory() / 'prepared'))
                self.selected_variant = None
                self.layout_report = None
                self.view('Upstream preparation finished', 'Prepared archive: ' + self.receipt['archive']
                          + '\n\nChoose an actual prepared variant next. Hardware validation remains unresolved; successful preparation does not authorize flashing.')

    def workflow(self):
        if not self.selected:
            self.show_hardware()
            self.choose_target()
        while self.selected:
            project, target = self.selected['project'], self.selected['id']
            status = 'No archive downloaded'
            if self.receipt:
                status = ('Prepared archive available' if self.receipt['status'] == 'upstream-preparation-completed-unqualified'
                          else 'Authenticated download available')
            if self.selected_variant:
                status = 'Variant extracted · hardware validation unresolved'
            if project == 'coreboot':
                status = 'Configuration available' if self.coreboot_workspace else 'No configuration created'
                if self.selected_variant:
                    status = 'Unqualified build candidate available'
            labels = ['1. Review target identity / change target',
                      '2. Read board-specific requirements and manual steps',
                      '3. Check existing backup files',
                      '4. Fetch pinned upstream source' + (' [available]' if project in self.sources else ''),
                      '5. Review and install system dependencies',
                      '6. Download and authenticate exact release',
                      ('7. Prepare vendor components' if project == 'libreboot' else
                       '7. Configure and build coreboot' if project == 'coreboot' else '7. Read custom preparation requirements'),
                      '8. Review / build coreboot candidate' if project == 'coreboot' else '8. Select and stage an actual ROM variant for inspection',
                      '9. Compare backup and candidate image layouts',
                      '10. Review flashing blockers and next steps',
                      'Chromebook-specific preparation instructions', 'Back to main menu']
            if project == 'coreboot':
                labels[5:8] = ['6. Configure and build coreboot', '7. Review built candidate and provenance',
                               '8. Read board-specific build requirements']
            action = self.menu(f'{project} · {target} · {status}', labels)
            if action is None or action == 11:
                return
            try:
                if action == 0:
                    self.show_hardware()
                    self.choose_target()
                elif action == 1:
                    self.guides(guide_for(self.selected))
                elif action == 2:
                    self.backup_check()
                elif action == 3:
                    self.preparation(4)
                elif action == 4:
                    self.preparation(0)
                elif action == 5:
                    if project == 'coreboot':
                        self.coreboot_build()
                    else:
                        self.download()
                elif action == 6:
                    if project == 'libreboot':
                        self.preparation(1)
                    elif project == 'coreboot':
                        self.view('coreboot candidate · flashing remains blocked',
                                  json.dumps(self.selected_variant, indent=2) if self.selected_variant else
                                  'No candidate has been built. Use Configure and build coreboot first.')
                    else:
                        self.guides(guide_for(self.selected))
                elif action == 7:
                    if project == 'coreboot':
                        self.guides(guide_for(self.selected))
                    else:
                        self.preparation(2)
                elif action == 8:
                    self.compare_layouts()
                elif action == 9:
                    self.view('Flashing is blocked — unresolved validation',
                              '\n\n'.join(flash_gate(self.selected)['reasons'])
                              + ('\n\nLayout inspection findings:\n' + '\n\n'.join(self.layout_report['blockers']) if self.layout_report else '\n\nNo layout comparison recorded for this session.')
                              + '\n\nNo internal write command or external wiring plan is approved for this target in this version. Consult the target workflow and upstream documentation; stop if identity, chip geometry, voltage, protected regions or recovery are unclear.')
                elif action == 10:
                    self.guides(CHROMEBOOK)
            except (Refusal, OSError, ValueError, subprocess.SubprocessError, tarfile.TarError) as error:
                self.view('Stopped — action needs attention', str(error))

    def run(self):
        labels = ['Start / continue guided preparation', 'View detected hardware',
                  'Chromebook preparation guide', 'Search the knowledge base',
                  'Safety status and coverage', 'Quit']
        while True:
            choice = self.menu('Choose a task', labels)
            if choice is None or choice == 5:
                return
            try:
                if choice == 0:
                    self.workflow()
                elif choice == 1:
                    self.show_hardware()
                elif choice == 2:
                    self.guides(CHROMEBOOK)
                elif choice == 3:
                    query = self.prompt('Search documentation (full text available with local research checkout)')
                    if query is not None:
                        results = research(query)
                        idx = self.menu('Sources — indexed, not individually validated', [s['project'] + ': ' + s['title'] for s in results], True)
                        if idx is not None:
                            record = results[idx]
                            body = '\n\n'.join(f'{key.replace("_", " ").capitalize()}: {value}' for key, value in record.items())
                            if record.get('path'):
                                path = (ROOT / record['path']).resolve()
                                if path.is_relative_to(ROOT / 'research/upstream') and path.is_file():
                                    body += '\n\nUPSTREAM DOCUMENT — REFERENCE ONLY, NOT AN APPROVED WORKFLOW\n\n' + path.read_text(errors='replace')
                            self.view('Source and provenance', body)
                elif choice == 4:
                    counts = Counter(b['project'] for b in self.boards)
                    self.view('Coverage and unresolved requirements', '\n'.join(f'{project}: {count} indexed targets' for project, count in counts.items()) + '\n\nInventory entries are not certified models. No real-hardware flashing profiles have been approved.\n\n' + '\n'.join(flash_gate(self.selected)['reasons']) + '\n\nFirmware writes are not implemented. Hardware configuration editing remains locked. No tool can guarantee against bricking.')
            except (Refusal, OSError, ValueError, subprocess.SubprocessError, tarfile.TarError) as error:
                self.view('Stopped — action needs attention', str(error))


def main():
    parser = argparse.ArgumentParser(description='LibreFren: launch without arguments for the guided terminal interface. Firmware writes remain locked.')
    sub = parser.add_subparsers(dest='command')
    sub.add_parser('detect')
    boards = sub.add_parser('boards')
    boards.add_argument('--project', choices=['libreboot', 'rboot', 'coreboot'])
    boards.add_argument('--search', default='')
    search = sub.add_parser('research')
    search.add_argument('query')
    guide = sub.add_parser('guide')
    guide.add_argument('target', nargs='?', default='chromebook')
    inspect = sub.add_parser('inspect')
    inspect.add_argument('archive', type=Path)
    inspect.add_argument('--target', required=True)
    backups = sub.add_parser('check-backups')
    backups.add_argument('--bytes', type=int, required=True)
    backups.add_argument('paths', nargs='+')
    get = sub.add_parser('download')
    get.add_argument('--project', choices=['libreboot', 'rboot'], required=True)
    get.add_argument('--target', required=True)
    get.add_argument('--directory', type=Path, required=True)
    get.add_argument('--confirm-target', required=True)
    source = sub.add_parser('fetch-source')
    source.add_argument('--project', choices=['libreboot', 'rboot', 'coreboot'], required=True)
    source.add_argument('--directory', type=Path, required=True)
    prep = sub.add_parser('prepare')
    prep.add_argument('--project', choices=['libreboot', 'rboot'], required=True)
    prep.add_argument('--target', required=True)
    prep.add_argument('--source', type=Path, required=True)
    prep.add_argument('--archive', type=Path, required=True)
    prep.add_argument('--mac', required=True)
    prep.add_argument('--confirmation', required=True)
    prep.add_argument('--directory', type=Path, required=True)
    deps = sub.add_parser('dependencies')
    deps.add_argument('--project', choices=['libreboot', 'rboot'], required=True)
    deps.add_argument('--source', type=Path, required=True)
    deps.add_argument('--profile', required=True)
    deps.add_argument('--confirmation', required=True)
    deps.add_argument('--log', type=Path, required=True)
    args = parser.parse_args()
    try:
        if not args.command:
            if not sys.stdin.isatty():
                parser.error('A terminal is required for the TUI; use a subcommand for noninteractive work.')
            curses.wrapper(lambda s: TUI(s).run())
            return
        if args.command == 'detect':
            result = detect()
        elif args.command == 'boards':
            result = [b for b in load('boards') if (not args.project or b['project'] == args.project) and args.search.casefold() in json.dumps(b).casefold()]
        elif args.command == 'research':
            result = research(args.query)
        elif args.command == 'guide':
            board = next((b for b in load('boards') if b['id'] == args.target), None)
            if args.target != 'chromebook' and board is None:
                raise Refusal('Unknown target')
            result = CHROMEBOOK if args.target == 'chromebook' else guide_for(board)
        elif args.command == 'inspect':
            result = inspect_variants(args.archive, args.target)
        elif args.command == 'check-backups':
            if not 0 < args.bytes <= 128 * 1024**2:
                raise Refusal('Expected size is outside the supported backup-check range')
            result = check_backups(args.paths, args.bytes)
        elif args.command == 'download':
            if args.target != args.confirm_target or not any(b['id'] == args.target and b['project'] == args.project for b in load('boards')):
                raise Refusal('Target confirmation or inventory lookup failed')
            result = fetch(args.project, args.target, args.directory)
        elif args.command == 'fetch-source':
            result = fetch_source(args.project, args.directory)
        elif args.command == 'prepare':
            result = inject(args.project, args.target, args.archive, args.source, args.mac, args.confirmation, args.directory)
        elif args.command == 'dependencies':
            result = dependencies(args.project, args.source, args.profile, args.confirmation, args.log)
        print(json.dumps(result, indent=2))
    except (Refusal, OSError, ValueError, subprocess.SubprocessError, tarfile.TarError, curses.error) as error:
        print('Stopped: ' + str(error), file=sys.stderr)
        raise SystemExit(2)


if __name__ == '__main__':
    main()
