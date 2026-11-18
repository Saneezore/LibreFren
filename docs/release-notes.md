LibreFren is an interactive Linux terminal application for researching and preparing Libreboot, RBoot and coreboot firmware.

Download the AppImage and checksum, make the AppImage executable, and launch it **without arguments** to open the purple TUI. Python is bundled; no Python commands or separate Python installation are required. Choose **Start / continue guided preparation**. If FUSE is unavailable, launch with `APPIMAGE_EXTRACT_AND_RUN=1`.

This preview includes:

- Advisory hardware detection, exact-target selection and release-availability labels.
- Corrected release pins for Libreboot 26.11rev1 and RBoot 26.11rev2. Missing releases, targets and signatures stop the download; no alternative target is substituted.
- Pinned source downloads, confirmed dependency installation and Libreboot vendor preparation controls.
- Current upstream ROM filename formats, prepared-archive hash rechecks, and signature-reverified RBoot inspection copies.
- Read-only backup/candidate layout comparisons for common Intel descriptor regions and FMAP, with device-data preservation findings and local reports.
- Google VPD 2.0 record comparisons that distinguish changed/missing device records from region padding changes, without displaying raw record values or copying them into images.
- GBB 1.2 structure and HWID checksum checks, with identity/key/flag comparisons. These checks provide evidence only; they do not authenticate a device or enable identity migration.
- Chromebook preparation and RBoot region-preservation instructions.
- A coreboot build screen with fresh pinned workspaces, exact board/configuration checks, confirmed host dependencies, cross-toolchain and image build controls, live logs and cancellation. Hardware settings remain locked and image outputs are marked unqualified.
- Optional GitHub Actions builds from the TUI: explicit repository/target review, saved requests, status, cancellation and provenance-checked downloads. Requires an authenticated GitHub CLI and repository write access; local backups are never uploaded.

**Preparation preview: firmware flashing is not enabled.** Indexed targets are research inventory, not validated hardware support. Region-preserving image assembly, Chromebook identity-data migration and reviewed coreboot hardware settings remain incomplete. Matching filenames, signatures or layouts never certify a device-safe ROM.

Validation records are under `docs/`, including automated tests, real upstream coreboot configuration checks, a comparison against ifdtool across 55 source descriptors and signed release archive inspections. An Actions run built the QEMU i440fx cross-toolchain and ROM and reached SeaBIOS; its final boot assertion failed. No physical hardware boot has been qualified. No physical firmware writes, actual Libreboot vendor injection or system dependency installation on the user's host were performed during development. Hardware qualification and broad Linux distribution testing remain pending.
