# Layout inspection and region preservation

In **Start / continue guided preparation**, choose **Compare backup and candidate image layouts**. Select the RBoot, Chromebook or general comparison context, then choose the original full-image backup and candidate using the file browser. A staged variant from this session can be selected directly. Reports are recorded locally in the session log; firmware contents and unique device identifiers are not printed.

This operation only reads the input files. It does not copy regions, patch firmware, change protection settings, split multi-chip images, or authorize flashing.

## RBoot workflow

Download the exact target archive, then select a variant for inspection. LibreFren copies the archive into a private temporary snapshot, checks its recorded hash and re-verifies the publisher signature before extracting the selected ROM. The result remains an **inspection copy**.

Some RBoot images intentionally omit Intel ME content. The device's existing vendor regions must remain intact through a board-specific installation procedure. A signed, correctly named, correctly sized archive therefore does not imply a usable whole-chip replacement.

The comparison identifies changed common IFD boundaries and bytes, including candidate GbE or BIOS ranges overlapping the backup ME range. It does not generate a write command. Read [RBoot preservation requirements](https://rboot.org/docs/install/ivy_has_common.html) and [GbE migration guidance](https://rboot.org/docs/install/dell_gbe.html). In particular, do not use a generic MAC injection or descriptor replacement to conceal an 8 KiB/16 KiB GbE mismatch.

## Chromebook workflow

The FMAP reader checks supported versions, table bounds, nonempty regions, unique terminated ASCII names, known flags, the map's own region, and region nesting. Properly nested areas are allowed; crossing overlaps, ambiguous maps, truncated tables and excessive inspection budgets are rejected. Region hashes are calculated from a bounded in-memory snapshot.

The report highlights missing, moved, resized or changed regions. RO_VPD, RW_VPD, GBB, named MRC regions and PRESERVE-marked areas receive explicit preservation review. Hash agreement is evidence of matching bytes, not proof of semantic compatibility or a correct backup.

For supported Google VPD 2.0 stores, the report also compares individual keys and value hashes. Each key is marked unchanged, changed, missing or added. This distinguishes a record change from changes to unrelated padding, while preserving the separate whole-region comparison. Raw values are not displayed or saved in the report; only key names, value lengths and SHA-256 hashes are recorded. Reports still belong with the user's private backup evidence, not public telemetry.

VPD inspection accepts one Google info header at offset 0 or 0x600, bounded declared data and terminated records. It rejects ambiguous headers, duplicate keys, overflow/truncated lengths, unsupported key names, unknown metadata and non-padding bytes after termination. Legacy/headerless formats remain unresolved. Empty stores are explicitly flagged. Parsing records does not establish which fields a particular board requires, whether a value is valid, or whether calibration data is compatible with the candidate firmware.

HWID can move between GBB and CBFS. GBB keys, VPD contents, calibration and MRC compatibility require more than region copying. The companion does not perform these migrations. The current [Libreboot Chromebook guide](https://libreboot.org/docs/install/chromebooks-x86.html) still contains unresolved preservation instructions; such gaps remain blockers. Consult the [MrChromebox custom-firmware guidance](https://docs.mrchromebox.tech/docs/firmware/manual-flashing.html) for supported devices, without treating it as approval for a different distribution's image.

## Deliberate parser limits

- Full files from 4 KiB to 128 MiB only. Devices, pipes and final symlinks are refused. A per-chip dump must not be mistaken for a complete multi-chip address space.
- FMAP 1.0/1.1, at most 1,024 areas and 64 signature candidates. Total region hashing is bounded. Unsupported/ambiguous input remains unresolved.
- IFD inspection covers only descriptor, BIOS, ME, GbE and platform-data geometry at conventional descriptor locations. It uses the common address-field interpretation and does not infer a verified chipset generation. Extra regions, permissions, density, straps, Boot Guard and other platform-specific settings are unvalidated.
- VPD regions are limited to 2 MiB, 2,048 records, 256-byte keys and five-byte length encodings. The companion does not rewrite VPD or infer field semantics.
- Neither input's target identity, independent-read provenance, authenticity, electrical configuration nor actual write-protect state can be established by this comparison. Even identical images cannot unlock flashing.

The format references are [coreboot's FMAP documentation](https://doc.coreboot.org/lib/flashmap.html) and the pinned [ifdtool implementation](https://github.com/coreboot/coreboot/blob/f13a6c7a61a761559d719f2b2e2a0ae1f43ddeb9/util/ifdtool/ifdtool.c).

## Reproduce the independent parser comparison

With the pinned research checkouts present, build the upstream utility into this project's ignored build directory:

```sh
mkdir -p build/verification/ifdtool
make -f research/upstream/coreboot/util/ifdtool/Makefile.mk \
  top=research/upstream/coreboot objutil=build/verification HOSTCC=cc \
  build/verification/ifdtool/ifdtool
python3 tools/check_layouts_against_upstream.py \
  --ifdtool build/verification/ifdtool/ifdtool \
  --output docs/layout-parser-validation.json
```

The decoder agreed with upstream on **55 descriptor geometries** from the pinned Libreboot/RBoot repositories. The tool uses synthetic padding in memory to inspect descriptors as full-size parser fixtures; these are not bootable images and are not saved as ROMs. Results and descriptor hashes are recorded in [the validation report](layout-parser-validation.json). This comparison validates common address decoding only; it is not hardware qualification.

The VPD decoder separately agreed with the pinned upstream C decoder on **32 synthetic fixtures / 224 records**, including binary values and variable-length boundaries. Malformed-input refusals are covered by unit tests. No real device calibration data or ROM migration was tested. See [the VPD comparison report](vpd-decoder-validation.json), [the Google format specification](https://chromium.googlesource.com/chromiumos/platform/vpd/+/2b274e62f481d3121b964e10bd0c5c79398813ae/README.md), and [coreboot's header-location logic](https://github.com/coreboot/coreboot/blob/f13a6c7a61a761559d719f2b2e2a0ae1f43ddeb9/src/drivers/vpd/vpd.c).

```sh
python3 tools/check_vpd_against_upstream.py \
  --source research/upstream/coreboot --output docs/vpd-decoder-validation.json
```

## Release availability

The initial pins (Libreboot 26.11 and RBoot 26.11rev1) returned HTTP 404 during live verification. The pins now match the available revisions and the already-recorded build-system commits: **Libreboot 26.11rev1** and **RBoot 26.11rev2**. The official listings contained **99** and **76** exact target archives with detached-signature links respectively. Remaining indexed configurations are labelled as absent from the saved listing; this does not establish permanent source-only status.

The saved release inventory is advisory and unsigned. Downloads repeat the live exact-name lookup and verify the pinned publisher key. Missing resources do not cause an automatic downgrade, target substitution or signature bypass. Programmer firmware utility archives in those directories are not system-firmware targets.
