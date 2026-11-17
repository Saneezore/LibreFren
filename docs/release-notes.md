LibreFren is an interactive Linux terminal application for researching and preparing Libreboot, RBoot and coreboot firmware.

Download the AppImage and checksum, make the AppImage executable, and launch it **without arguments** to open the purple TUI. Python is bundled; no Python commands or separate Python installation are required. Choose **Start / continue guided preparation**. If FUSE is unavailable, launch with `APPIMAGE_EXTRACT_AND_RUN=1`.

This preview includes:

- Advisory hardware detection, exact-target selection and release-availability labels.
- Corrected release pins for Libreboot 26.11rev1 and RBoot 26.11rev2. Missing releases, targets and signatures stop the download; no alternative target is substituted.
- Pinned source downloads, confirmed dependency installation and Libreboot vendor preparation controls.
- Current upstream ROM filename formats, prepared-archive hash rechecks, and signature-reverified RBoot inspection copies.
- Read-only backup/candidate layout comparisons for common Intel descriptor regions and FMAP, with device-data preservation findings and local reports.
- Chromebook preparation and RBoot region-preservation instructions.

**Preparation preview: firmware flashing is not enabled.** Indexed targets are research inventory, not validated hardware support. Region-preserving image assembly, Chromebook identity-data migration and coreboot configuration/build execution remain incomplete. Matching filenames, signatures or layouts never certify a device-safe ROM.

Validation records are under `docs/`, including automated tests, a comparison against coreboot's ifdtool across 55 source descriptors and an actual signed RBoot archive inspection. No physical firmware writes, actual Libreboot vendor injection or system dependency installation were performed during development. Hardware qualification and broad Linux distribution testing remain pending.
