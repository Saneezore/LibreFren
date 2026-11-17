"""Small curses frontend with the same refusal rules as the CLI."""
import argparse
from collections import Counter
import curses
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tarfile
import textwrap

from .guides import CHROMEBOOK, guide_for
from .releases import fetch
from .prepare import dependencies, fetch_source, inject
from .session import Session
from .safety import Refusal, check_backups, detect, exact_candidates, extract_variant, flash_gate, inspect_variants

DATA = Path(__file__).parent / "data"
ROOT = Path(__file__).resolve().parents[1]


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
        self.hardware = detect()
        self.selected = None
        self.receipt = None
        self.session = None
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
                        self.session = Session(Path.home() / '.local/share/librefren/sessions')
                    self.session.record('manual-observation', {'target': self.selected['id'] if self.selected else None,
                                                             'step': title, 'source': url, 'note': note,
                                                             'status': 'user-reported-unverified'})
                    self.view('Observation recorded', 'Saved to ' + str(self.session.path) + '\nThis observation does not unlock flashing or satisfy an unresolved machine check.')

    def download(self):
        if not self.selected or self.selected['project'] == 'coreboot':
            raise Refusal('Select an exact Libreboot or RBoot target first. coreboot requires a board-specific source build.')
        expected = 'DOWNLOAD ' + self.selected['id']
        answer = self.prompt('Download only this exact target; not flash approval. Type ' + expected)
        if answer != expected:
            return
        curses.def_prog_mode()
        curses.endwin()
        try:
            print('Downloading one exact target and verifying its publisher signature. No firmware writes.')
            self.receipt = fetch(self.selected['project'], self.selected['id'], Path.home() / '.local/share/librefren/downloads')
            print(json.dumps(self.receipt, indent=2))
        finally:
            input('Press Enter to return to the companion...')
            curses.reset_prog_mode()
            self.screen.refresh()

    def terminal_job(self, action):
        curses.def_prog_mode()
        curses.endwin()
        try:
            result = action()
            print(json.dumps(result, indent=2))
            return result
        finally:
            input('Press Enter to return...')
            curses.reset_prog_mode()
            self.screen.refresh()

    def preparation(self):
        if not self.selected:
            raise Refusal('Select an exact target first.')
        project, target = self.selected['project'], self.selected['id']
        action = self.menu('Preparation — outputs remain unqualified for flashing', ['Install build dependencies', 'Prepare authenticated Libreboot archive', 'Select and extract a prepared variant', 'coreboot settings and build guidance', 'Fetch the pinned upstream source'])
        if action is None:
            return
        if action == 4:
            answer = self.prompt(f'Type FETCH {project} to download its pinned source (no build scripts run)')
            if answer == f'FETCH {project}':
                result = self.terminal_job(lambda: fetch_source(project, Path.home() / '.local/share/librefren/sources'))
                self.view('Source downloaded — use this path for preparation', json.dumps(result, indent=2))
            return
        if action == 3:
            self.view('coreboot configuration — hardware settings locked',
                      'Use the exact board selector below as research evidence. A compiling configuration is not proof of safe hardware initialization. This preview does not expose editable Kconfig or a build executor without a reviewed baseline.\n\n' + json.dumps(self.selected, indent=2) + '\n\nManual next steps: review the board documentation, obtain required vendor files from documented sources, pin source/toolchain/submodules, and qualify the unchanged baseline on recoverable hardware.\n\nhttps://doc.coreboot.org/tutorial/part1.html')
            return
        if action == 2:
            if not self.receipt or self.receipt['status'] != 'upstream-preparation-completed-unqualified':
                raise Refusal('Complete preparation first. Downloaded scrubbed images cannot be extracted through this menu.')
            variants = self.receipt['variants']
            idx = self.menu('Choose an actual prepared variant — not flash approval', [v['path'] for v in variants])
            if idx is not None:
                output = extract_variant(self.receipt['archive'], target, variants[idx]['path'], Path(self.receipt['archive']).parent / 'selected')
                self.view('Variant extracted; hardware validation remains blocked', json.dumps(output, indent=2))
            return
        source = self.prompt('Path to the pinned upstream source checkout')
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
                log = Path(tempfile.mkdtemp(prefix='fc-deps-')) / 'dependencies.log'
                self.terminal_job(lambda: dependencies(project, source, profile, confirmation, log))
        else:
            if not self.receipt:
                raise Refusal('Download and authenticate an archive first.')
            mac = self.prompt('MAC choice: random, or the target device’s full unicast MAC address')
            confirmation = self.prompt(f'Type PREPARE {target} to run upstream preparation and vendor downloads')
            if mac and confirmation:
                self.receipt = self.terminal_job(lambda: inject(project, target, self.receipt['archive'], source, mac, confirmation, Path.home() / '.local/share/librefren/prepared'))

    def run(self):
        labels = ['Detect this Linux host', 'Browse all project targets', 'Selected target: workflow and manual instructions',
                  'Chromebook preparation guide', 'Search the knowledge base', 'Download and authenticate exact target',
                  'Inspect downloaded variants', 'Safety status and coverage', 'Dependencies, preparation and variant selection', 'Quit']
        while True:
            choice = self.menu('Choose a task', labels)
            if choice is None or choice == 9:
                return
            try:
                if choice == 0:
                    candidates = exact_candidates(self.hardware, self.boards)
                    self.view('Hardware evidence — advisory only', json.dumps(self.hardware, indent=2) + '\n\nExact name candidates (not verified matches):\n' + '\n'.join(b['project'] + ': ' + b['id'] for b in candidates))
                elif choice == 1:
                    idx = self.menu('All indexed targets — not tested hardware support', [b['project'] + ' | ' + b['id'] + ' | ' + ', '.join(b.get('names', [])) for b in self.boards], True)
                    if idx is not None:
                        self.selected, self.receipt = self.boards[idx], None
                        self.view('Target selected for research', json.dumps(self.selected, indent=2))
                elif choice == 2:
                    if not self.selected:
                        raise Refusal('Choose a target from the inventory first.')
                    self.guides(guide_for(self.selected))
                elif choice == 3:
                    self.guides(CHROMEBOOK)
                elif choice == 4:
                    query = self.prompt('Search documentation (full text available with local research checkout)')
                    if query is not None:
                        results = research(query)
                        idx = self.menu('Sources — indexed, not individually validated', [s['project'] + ': ' + s['title'] for s in results], True)
                        if idx is not None:
                            record = results[idx]
                            body = json.dumps(record, indent=2)
                            if record.get('path'):
                                path = (ROOT / record['path']).resolve()
                                if path.is_relative_to(ROOT / 'research/upstream') and path.is_file():
                                    body += '\n\nUPSTREAM DOCUMENT — REFERENCE ONLY, NOT AN APPROVED WORKFLOW\n\n' + path.read_text(errors='replace')
                            self.view('Source and provenance', body)
                elif choice == 5:
                    self.download()
                elif choice == 6:
                    if not self.receipt:
                        raise Refusal('Download an authenticated target first, or use the CLI inspect command for a local archive.')
                    self.view('Actual archive variants', json.dumps(self.receipt['variants'], indent=2))
                elif choice == 7:
                    counts = Counter(b['project'] for b in self.boards)
                    self.view('Coverage and unresolved requirements', json.dumps(counts, indent=2) + '\n\nInventory entries are not certified models. No real-hardware flashing profiles have been approved.\n\n' + '\n'.join(flash_gate(self.selected)['reasons']) + '\n\nFirmware writes are not implemented. Hardware configuration editing remains locked. No tool can guarantee against bricking.')
                elif choice == 8:
                    self.preparation()
            except (Refusal, OSError, ValueError, subprocess.SubprocessError, tarfile.TarError) as error:
                self.view('Stopped — action needs attention', str(error))


def main():
    parser = argparse.ArgumentParser(description='Firmware preparation and research companion; firmware writes are locked.')
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
