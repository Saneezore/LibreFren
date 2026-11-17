#!/usr/bin/env python3
"""Index complete upstream checkouts without executing their configuration files.

The full-text database stays local; redistributable metadata contains links,
hashes and structural facts, not copied wiki articles. Indexed != reviewed.
"""
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import subprocess

ROOT = Path(__file__).resolve().parents[1]
UP = ROOT / "research/upstream"
DATA = ROOT / "librefren/data"


def revision(path):
    return subprocess.check_output(["git", "-C", str(path), "rev-parse", "HEAD"], text=True).strip()


def assignments(text):
    return dict(re.findall(r'^([A-Za-z_][A-Za-z_0-9]*)="([^"\n]*)"$', text, re.M))


def main():
    boards, sources, revisions, references, review_queue = [], [], {}, {}, []
    db = sqlite3.connect(ROOT / "research/knowledge.sqlite")
    db.execute("DROP TABLE IF EXISTS documents")
    db.execute("CREATE VIRTUAL TABLE documents USING fts5(project, path, url, title, body)")
    for repo in ("lbmk", "rbmk", "coreboot", "lbwww", "rbwww", "cbmk", "cbwww"):
        path = UP / repo
        revisions[repo] = revision(path)
    for project, repo in (("libreboot", "lbmk"), ("rboot", "rbmk")):
        root = UP / repo
        for target in sorted((root / "config/module/coreboot").iterdir()):
            configs = target / "config"
            if not configs.is_dir():
                continue  # dependency trees are not board build targets
            tc = target / "target.cfg"
            values = assignments(tc.read_text()) if tc.exists() else {}
            variants, selectors, names, sizes = [], set(), set(), set()
            for config in sorted(configs.iterdir()):
                if not config.is_file():
                    continue
                text = config.read_text()
                selectors.update(re.findall(r'^CONFIG_(BOARD_\w+)=y$', text, re.M))
                names.update(re.findall(r'^CONFIG_MAINBOARD_PART_NUMBER="([^"]+)"$', text, re.M))
                sizes.update(re.findall(r'^CONFIG_ROM_SIZE=(\S+)$', text, re.M))
                variants.append({"name": config.name, "sha256": hashlib.sha256(config.read_bytes()).hexdigest()})
            boards.append({"project": project, "id": target.name, "names": sorted(names),
                           "selectors": sorted(selectors), "variants": variants,
                           "rom_size_config": sorted(sizes), "vendor_profile": values.get("vcfg"),
                           "ifd_platform": values.get("IFD_platform"), "tree": values.get("tree"),
                           "source": f"https://codeberg.org/{project}/{repo}/src/commit/{revisions[repo]}/config/module/coreboot/{target.name}",
                           "status": "indexed-unreviewed", "flash_approved": False})
    root = UP / "coreboot"
    for config in sorted((root / "src/mainboard").rglob("Kconfig.name")):
        text = config.read_text()
        info_path = config.parent / 'board_info.txt'
        info = {}
        if info_path.is_file():
            for line in info_path.read_text().splitlines():
                if ':' in line:
                    key, value = line.split(':', 1)
                    info[key.strip()] = value.strip()
        for match in re.finditer(r'^config (BOARD_\w+)\s*\n\s*bool(?:\s+"([^"]+)")?', text, re.M):
            selector, label = match.groups()
            boards.append({"project": "coreboot", "id": selector, "names": [label or selector],
                           "selectors": [selector], "directory": str(config.parent.relative_to(root)),
                           "upstream_board_info": info,
                           "source": f"https://github.com/coreboot/coreboot/blob/{revisions['coreboot']}/{config.relative_to(root)}",
                           "status": "indexed-unreviewed", "flash_approved": False})
    bodies = {}
    for project, repo, directory, base in (
        ("libreboot", "lbwww", "site", "https://libreboot.org/"),
        ("rboot", "rbwww", "site", "https://rboot.org/"),
        ("canoeboot-history", "cbwww", "site", "https://canoeboot.org/"),
        ("coreboot", "coreboot", "Documentation", "https://doc.coreboot.org/"),
    ):
        root = UP / repo / directory
        for path in sorted(root.rglob("*.md")):
            text = path.read_text(errors="replace")
            relative = path.relative_to(root).as_posix()
            title = next((s[7:].strip() for s in text.splitlines() if s.startswith("title: ")), None) or next((s.lstrip('#% ').strip() for s in text.splitlines() if s.startswith(("#", "%"))), path.stem)
            url = base + relative[:-3] + ".html"
            record = {"project": project, "path": str(path.relative_to(ROOT)), "url": url,
                      "title": title, "revision": revisions[repo],
                      "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                      "status": "indexed-unreviewed", "kind": "official-documentation"}
            sources.append(record)
            bodies[url] = text
            for line_number, line in enumerate(text.splitlines(), 1):
                tags = [tag for tag in ('brick', 'warning', 'voltage', 'write protection', 'backup', 'vpd', 'hwid', 'TODO') if tag.casefold() in line.casefold()]
                if tags:
                    review_queue.append({'url': url, 'line': line_number, 'tags': tags, 'revision': revisions[repo], 'status': 'needs-human-review'})
                for link in re.findall(r'https?://[^\s<>"\)\]]+', line):
                    references.setdefault(link, {'url': link, 'title': link, 'project': project, 'discovered_in': [], 'status': 'discovered-not-reviewed'})['discovered_in'].append(url)
            db.execute("INSERT INTO documents VALUES (?,?,?,?,?)", (project, record["path"], url, title, text))
    for board in boards:
        board['documentation'] = [url for url, body in bodies.items() if board['id'] in body and re.search(r'(?<![\w])' + re.escape(board['id']) + r'(?![\w])', body)]
        if board['project'] == 'coreboot':
            relative = board['directory'].removeprefix('src/')
            candidates = [relative + '.html', relative + '/index.html']
            for candidate in candidates:
                url = 'https://doc.coreboot.org/' + candidate
                if url in bodies and url not in board['documentation']:
                    board['documentation'].append(url)
        board['documentation_status'] = 'explicit-identifier-references' if board['documentation'] else 'board-specific-guide-mapping-required'
    db.commit()
    db.close()
    DATA.mkdir(exist_ok=True)
    for reference in references.values():
        reference['discovered_in'] = sorted(set(reference['discovered_in']))
    for filename, value in (("boards.json", boards), ("sources.json", sources), ("revisions.json", revisions), ("references.json", list(references.values())), ("review-queue.json", review_queue)):
        (DATA / filename).write_text(json.dumps(value, indent=2) + "\n")
    counts = {p: sum(b['project'] == p for b in boards) for p in ('libreboot', 'rboot', 'coreboot')}
    print(json.dumps({"boards": counts, "documents": len(sources), "references": len(references), "review_queue": len(review_queue), "revisions": revisions}, indent=2))


if __name__ == "__main__":
    main()
