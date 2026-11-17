"""Pure safety checks. A matching name or checksum is never flash approval."""
import hashlib
import platform
from pathlib import Path, PurePosixPath
import re
import tarfile


class Refusal(ValueError):
    pass


def digest(path):
    with open(path, "rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def detect(root=Path("/sys/class/dmi/id")):
    fields = ("sys_vendor", "product_name", "product_version", "board_vendor", "board_name", "board_version", "bios_vendor", "bios_version")
    result = {}
    for name in fields:
        try:
            result[name] = (root / name).read_text().strip()
        except (OSError, UnicodeError):
            result[name] = "unknown"
    result["scope"] = "This is the running host, not an externally connected motherboard. DMI is advisory."
    result['architecture'] = platform.machine()
    result['pci_devices'] = []
    for device in sorted(Path('/sys/bus/pci/devices').glob('*')):
        entry = {}
        for name in ('vendor', 'device', 'class', 'subsystem_vendor', 'subsystem_device'):
            try:
                entry[name] = (device / name).read_text().strip()
            except OSError:
                entry[name] = 'unknown'
        result['pci_devices'].append(entry)
    for field in ('model', 'compatible'):
        try:
            result['device_tree_' + field] = Path('/sys/firmware/devicetree/base', field).read_bytes().decode(errors='replace').strip('\x00').replace('\x00', ', ')
        except OSError:
            pass
    result['physical_flash_geometry'] = 'unknown; requires board-specific evidence'
    return result


def exact_candidates(hardware, boards):
    # Deliberately preserve punctuation and suffixes. No prefix/substring match.
    identities = {hardware.get(k, "").strip().casefold() for k in ("product_name", "product_version", "board_name")}
    identities -= {"", "unknown", "default string", "to be filled by o.e.m."}
    return [b for b in boards if identities.intersection(n.casefold() for n in b.get("names", []))]


def archive_members(path, max_bytes=2 * 1024**3):
    """Preflight entire tar before any extraction. No links, devices or traversal."""
    total, seen, result = 0, set(), []
    with tarfile.open(path, "r:*") as archive:
        for member in archive:
            p = PurePosixPath(member.name)
            if (p.is_absolute() or ".." in p.parts or "\\" in member.name
                    or any(ord(c) < 32 or ord(c) == 127 for c in member.name)
                    or not (member.isfile() or member.isdir())):
                raise Refusal(f"Unsafe archive member: {member.name!r}")
            if str(p) in seen:
                raise Refusal("Duplicate archive member")
            seen.add(str(p))
            total += member.size
            if total > max_bytes or len(seen) > 10000:
                raise Refusal("Archive exceeds resource limits")
            result.append(member)
    return result


def inspect_variants(path, target):
    members = archive_members(path)
    result = []
    for member in members:
        if not member.isfile() or not member.name.endswith(".rom"):
            continue
        p = PurePosixPath(member.name)
        if p.parent != PurePosixPath("bin") / target:
            raise Refusal("ROM is outside the exact selected target directory")
        name = p.name
        # Current lbmk/rbmk cprom names use explicit firmware-type + payload.
        # Match these before the legacy single-word prefixes; never strip an
        # arbitrary prefix or loosen the exact target directory/name check.
        prefix = re.match(r"^(uefi_edk2|bios_seabios|uefi_uboot|edk2|seabios|seagrub|grub|uboot|u-boot|seauboot|bios|uefi)_", name)
        blocked = []
        if "DO_NOT_FLASH" in name.upper() or "DONOTFLASH" in name.upper():
            blocked.append("Vendor-file injection is incomplete")
        if not prefix or not name[len(prefix.group(0)):].startswith(target + "_"):
            blocked.append("Filename does not identify the exact target")
        size_match = re.search(r"_(\d+)mb$", target)
        if size_match and member.size != int(size_match[1]) * 1024**2:
            blocked.append("Image size disagrees with selected target capacity")
        result.append({"path": member.name, "size": member.size,
                       "payload": prefix.group(1) if prefix else "unknown",
                       "blockers": blocked, "flash_approved": False})
    if not result:
        raise Refusal("No ROM variants in the expected directory")
    return result


def extract_variant(archive_path, target, name, destination):
    choices = inspect_variants(archive_path, target)
    choice = next((v for v in choices if v['path'] == name), None)
    if not choice or choice['blockers']:
        raise Refusal("Variant missing or still requires preparation")
    destination = Path(destination)
    destination.mkdir(mode=0o700, parents=True, exist_ok=True)
    output = destination / PurePosixPath(name).name
    # Never overwrite backups or follow existing symlinks.
    with tarfile.open(archive_path) as archive, output.open("xb") as stream:
        source = archive.extractfile(name)
        if source is None:
            raise Refusal("Variant could not be read")
        while chunk := source.read(1024**2):
            stream.write(chunk)
    return {"path": str(output), "sha256": digest(output), "flash_approved": False}


def check_backups(paths, expected_size):
    if len(paths) < 2:
        raise Refusal("At least two independent reads are required")
    identities, hashes = set(), set()
    for value in paths:
        path = Path(value)
        if path.is_symlink() or not path.is_file():
            raise Refusal("Backups must be regular files")
        st = path.stat()
        identities.add((st.st_dev, st.st_ino))
        if st.st_size != expected_size:
            raise Refusal("Backup size does not match the expected chip capacity")
        data = path.read_bytes()
        if len(set(data)) <= 1:
            raise Refusal("Uniform backup is not credible firmware")
        hashes.add(hashlib.sha256(data).hexdigest())
    if len(identities) != len(paths) or len(hashes) != 1:
        raise Refusal("Backups are the same file or contain different bytes")
    return {"sha256": hashes.pop(), "status": "consistent",
            "limitation": "Matching files do not prove independent reads or correct chip identity."}


def flash_gate(board, evidence=None):
    # No reviewed hardware profiles have been commissioned yet. Inventory metadata
    # is deliberately not a means to bypass this gate, even if edited by the user.
    return {"allowed": False, "reasons": [
        "No independently reviewed flashing profile for this board/release.",
        "Physical board revision, chip layout and voltage remain unverified.",
        "Backup provenance, image structure and vendor-file completion need board-specific validation.",
        "Current firmware protections and recovery readiness require verification.",
    ]}
