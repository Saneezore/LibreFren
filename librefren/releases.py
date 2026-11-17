"""Official, exact-target downloads with isolated OpenPGP verification."""
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import subprocess
import tempfile
from urllib.parse import urlparse
from urllib.request import build_opener, HTTPRedirectHandler, Request

from .safety import Refusal, digest, inspect_variants

FINGERPRINT = "8BB1F7D28CF7696DBF4F71925C654067D383B1FF"
HOSTS = {"mirror.math.princeton.edu", "rsync.rboot.org", "rboot.org", "libreboot.org"}
RELEASES = {
    "libreboot": ("26.11", "https://mirror.math.princeton.edu/pub/libreboot/stable/26.11/"),
    "rboot": ("26.11rev1", "https://rsync.rboot.org/26.11rev1/"),
}


def check_url(url):
    value = urlparse(url)
    if value.scheme != "https" or value.hostname not in HOSTS or value.username or value.password or value.port not in (None, 443):
        raise Refusal("Download is not on an approved HTTPS origin")


class Redirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        check_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def download(url, path, limit=256 * 1024**2):
    check_url(url)
    total = 0
    with build_opener(Redirects()).open(Request(url, headers={"User-Agent": "LibreFren/0.1"}), timeout=30) as response, Path(path).open("xb") as out:
        check_url(response.url)
        while chunk := response.read(1024**2):
            total += len(chunk)
            if total > limit:
                raise Refusal("Download exceeds size limit")
            out.write(chunk)


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = set()

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            href = dict(attrs).get("href", "")
            if re.fullmatch(r"[A-Za-z0-9_.-]+", href):
                self.links.add(href)


def archive_name(project, target):
    if project not in RELEASES or not re.fullmatch(r"[a-z0-9_]+", target):
        raise Refusal("Unknown project or invalid target")
    return f"{project}-{RELEASES[project][0]}_{target}.tar.xz"


def verify(archive, signature, key):
    with tempfile.TemporaryDirectory(prefix="fc-gpg-") as home:
        base = ["gpg", "--no-options", "--homedir", home, "--batch", "--no-auto-key-retrieve"]
        imported = subprocess.run(base + ["--import", str(key)], capture_output=True, text=True)
        if imported.returncode:
            raise Refusal("Cannot import the release verification key")
        result = subprocess.run(base + ["--status-fd", "1", "--verify", str(signature), str(archive)], capture_output=True, text=True)
        statuses = [s.split() for s in result.stdout.splitlines() if s.startswith("[GNUPG:] VALIDSIG ")]
        invalid = any(f"[GNUPG:] {s} " in result.stdout for s in ("EXPKEYSIG", "EXPSIG", "REVKEYSIG", "BADSIG", "ERRSIG"))
        # VALIDSIG's last field is the primary key fingerprint for subkey signatures.
        valid = any(s[2] == FINGERPRINT or s[-1] == FINGERPRINT for s in statuses)
        if result.returncode or invalid or not valid:
            raise Refusal("Release signature is invalid, expired, revoked, or signed by an unexpected key")
    return digest(archive)


def fetch(project, target, directory):
    name = archive_name(project, target)
    base = RELEASES[project][1]
    directory = Path(directory)
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix=f"{project}-", dir=directory))
    download(base + "roms/", work / "index.html", 4 * 1024**2)
    parser = Links()
    parser.feed((work / "index.html").read_text())
    if name not in parser.links:
        raise Refusal("This exact target is absent from the pinned release. No substitute was downloaded.")
    archive = work / name
    download(base + "roms/" + name, archive)
    download(base + "roms/" + name + ".sig", work / "archive.sig", 65536)
    download("https://rboot.org/rbkey.asc" if project == "rboot" else "https://libreboot.org/lbkey.asc", work / "key.asc", 1024**2)
    sha = verify(archive, work / "archive.sig", work / "key.asc")
    variants = inspect_variants(archive, target)
    record = {"project": project, "release": RELEASES[project][0], "target": target,
              "archive": str(archive), "sha256": sha, "signer": FINGERPRINT,
              "variants": variants, "flash_approved": False,
              "status": "authenticated-download-only"}
    (work / "receipt.json").write_text(json.dumps(record, indent=2) + "\n")
    return record
