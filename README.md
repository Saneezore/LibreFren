# LibreFren

A small purple Linux TUI for researching and preparing **Libreboot, RBoot and coreboot** firmware. The primary interface is an interactive, full-screen application.

Launch the AppImage without arguments:

```sh
chmod +x LibreFren-0.1.0-x86_64.AppImage
./LibreFren-0.1.0-x86_64.AppImage
```

The AppImage bundles Python; users do not need to install Python or type Python commands. Desktop launches open an available terminal. Choose **Start / continue guided preparation** to identify the target, read requirements, check backups, fetch source, review dependencies, authenticate the exact release, prepare vendor components and select an actual ROM variant. Missing hardware validation remains a visible blocker.

For developers running from the source checkout:

```sh
python3 -m librefren
```

**This is a research and preparation preview, not a qualified universal firmware installer.** It indexes all selectable board targets found by the current repository importer. It does not claim that every historical board, downstream fork, hardware revision or variant has been audited. No real-hardware flashing profile has been approved. Firmware write commands and unrestricted coreboot configuration changes remain disabled. No software can promise that flashing will never brick a device.

## Implemented

- Dependency-free Python/curses interface; Libreboot website colours `#280b22` and `#4e324e`, keyboard navigation, search and scrollable instructions.
- Advisory Linux DMI, architecture, PCI and device-tree detection without reading serial numbers or requesting root. Exact name candidates preserve suffixes; external targets are distinguished from the running host.
- Inventory of 327 Libreboot targets, 78 RBoot targets and 930 coreboot board selectors at recorded revisions. These are build targets/selectors, not unique tested retail models.
- Local full-text database of 770 upstream documents, 37 curated findings, 2,917 discovered reference URLs and 1,271 warning/TODO review locations. Indexed, reviewed and merely discovered evidence have different labels.
- Exact-target downloads for pinned Libreboot 26.11rev1 and RBoot 26.11rev2 releases, HTTPS origin restrictions, isolated GPG verification against the publisher fingerprint, bounded archive inspection, and receipts. Missing releases, targets or detached signatures stop the download; there is no automatic substitution.
- Explicitly confirmed dependency installation from an unmodified, pinned lbmk/rbmk checkout. The upstream distribution profile is shown before sudo is invoked.
- Pinned upstream source fetching without running build scripts; optional session logs for user-reported manual observations, which never unlock flashing.
- Explicitly confirmed Libreboot vendor preparation through pinned upstream lbmk, with a MAC choice, untouched original archive, captured logs, prepared hashes and inspection of actual ROM variants. Successful preparation **does not** grant flash approval.
- Guided preparation keeps the selected target, source checkout, authenticated archive and prepared variant together. Download and preparation progress stays in the TUI; system package installation uses sudo's terminal prompt.
- Selection/extraction of a prepared variant without overwriting existing files; repeated-backup consistency checks with a TUI file browser.
- RBoot variant staging for inspection, with the original archive hash and publisher signature rechecked on a private snapshot. Prepared Libreboot variants also have their recorded archive hash rechecked before extraction.
- Read-only backup/candidate layout comparisons inside the guided TUI: bounded FMAP parsing, region boundaries and hashes, missing or changed device-data regions, and common IFD region overlap checks. Reports remain local and never authorize a write. See [layout inspection](docs/layout-inspection.md) for scope and validation.
- Detailed manual instructions for Chromebook preparation, CR50/Ti50, target identity, protected regions, recovery and custom-firmware handoffs. Other boards receive general steps and exact-identifier documentation references when available.
- AppImage packaging and a GitHub Actions workflow which creates **draft prereleases** on version tags.

## Deliberately unresolved

End-to-end installation for all boards is **not implemented or validated**. RBoot region-preserving image preparation, automated Chromebook VPD/HWID preservation, validated internal flashing command generation, per-chip external plans, reviewed coreboot hardware settings, historical release selection, dependency isolation and signed catalog updates remain work to do. Layout comparison is evidence, not an image repair or flash approval. Unknown requirements stop progression. The UI's preparation controls are an implementation preview; no real vendor injection or system dependency installation on the user's host was exercised during development.

The [coreboot build workflow](docs/coreboot-builds.md) now creates fresh exact-selector configurations, offers confirmed host dependency installation and cross-toolchain/image build controls, and checks inputs before and after each operation. Hardware settings remain locked. Builds show logs and support cancellation. Exported candidates remain unqualified. Real upstream configuration checks cover the selectors in the validation report; complete toolchain/ROM builds and hardware operation have not yet been validated.

Coreboot source availability is not a promise of end-user installation support. Many boards need unique blobs, straps, manufacturing configuration, downstream patches or hardware recovery. A board appearing in the source inventory never authorizes a write. A manual acknowledgement is not machine-verifiable evidence.

## Optional command-line utilities

These commands are for scripting and diagnostics. Normal interactive use does not require them.

```sh
python3 -m librefren detect
python3 -m librefren boards --project libreboot
python3 -m librefren research 'RO_VPD'
python3 -m librefren guide chromebook
python3 -m librefren guide EXACT_TARGET
python3 -m librefren inspect /path/to/archive.tar.xz --target EXACT_TARGET
python3 -m librefren check-backups --bytes 16777216 read1.bin read2.bin
```

Download only after selecting the exact target for research/preparation:

```sh
python3 -m librefren download --project libreboot --target EXACT_TARGET \
  --confirm-target EXACT_TARGET --directory ./downloads
```

GPG must be installed on the host for signature verification. The app will refuse verification if it is unavailable. Source builds require the upstream dependency set; the AppImage contains the companion, not compilers or firmware. In the TUI, choose **Dependencies, preparation and variant selection** for opt-in preparation actions. RBoot preparation remains a manual, region-aware handoff.

## Research

See [findings](docs/research-findings.md), [source analysis](docs/source-analysis.md), [safety design](docs/safety-design.md) and [coverage](docs/coverage.md).

Complete shallow working trees are under `research/upstream/`: `lbmk`, `rbmk`, `coreboot`, `lbwww`, `rbwww`, and historical `cbmk`/`cbwww`. Git histories are shallow; recursively fetched firmware dependencies/submodules are not included. These read-only research trees are excluded from this project's distributable. The user's existing `../lbmk` directory is untouched.

Regenerate the metadata and local FTS database after checking out the recorded revisions:

```sh
python3 tools/index_sources.py
python3 tools/curate_research.py
```

The AppImage bundles source metadata, links, findings and manual guides. The full text of upstream documentation is searchable locally when the research checkouts/database are present; it is not silently republished inside the release.

## Tests and packaging

```sh
python3 -m unittest discover -s tests -v
```

`packaging/build_appimage.py` consumes PyInstaller and explicitly supplied AppImage tools with SHA-256 pins. See `.github/workflows/release.yml` for the complete build invocation. CI builds on Ubuntu 22.04 for a more portable glibc baseline. The locally built preview uses this development host's libc and is not yet cross-distribution qualified. x86_64 is the only packaged architecture currently; ARM target research is supported, but an ARM-native AppImage remains unbuilt.

The project repository is [Saneezore/LibreFren](https://github.com/Saneezore/LibreFren). Version tags build draft preview releases; publishing the repository does not publish those drafts. Before publishing an AppImage release, qualify the artifact on the supported Linux distributions and complete independent firmware-domain review. Upstream project names and colour references do not imply endorsement. The existing repository GPL-2.0 license is retained.
