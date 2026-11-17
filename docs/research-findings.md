# Research findings

Reviewed 17 November 2026. Indexed sources are not individually reviewed. Community reports are leads, not firmware authorization.

## Exact identity is necessary but insufficient

Board suffix, PCB revision, GPU/CPU variant, physical capacity and current firmware all affect applicability. Do not turn a name match into flash approval.

Evidence: official-reviewed. [Source](https://libreboot.org/docs/install/t480.html).

## Authenticate before processing

Verify detached signatures against a pinned primary fingerprint. An adjacent unsigned checksum alone does not authenticate a release. Keep the authenticated original separate from prepared output.

Evidence: official-reviewed. [Source](https://libreboot.org/download.html).

## Vendor file insertion is a real build operation

lbmk downloads and processes required inputs, checks prepared image hashes and can modify the GbE MAC. Check completion and inspect the resulting variants. Renaming or trimming scrubbed ROMs is not preparation.

Evidence: official-reviewed. [Source](https://libreboot.org/docs/install/ivy_has_common.html).

## Region preservation differs from Libreboot injection

Supported Sandy/Ivy Bridge and Haswell systems preserve existing vendor regions. Migration needs the actual source and destination region layouts, not a generic whole-chip command.

Evidence: official-reviewed. [Source](https://rboot.org/docs/install/ivy_has_common.html).

## Dell GbE boundary hazard

RBoot documents a 16 KiB GbE layout versus 8 KiB in some other distributions. Replacing GbE or IFD without migration-specific validation can overwrite ME bytes.

Evidence: official-reviewed. [Source](https://rboot.org/docs/install/dell_gbe.html).

## FMAP is nested region metadata, not target identity

Validate the serialized table, bounds, unique region names and nesting. PRESERVE flags identify areas requiring attention, but neither matching names nor matching lengths proves that copying their data between firmware versions is valid.

Evidence: official-reviewed. [Source](https://doc.coreboot.org/lib/flashmap.html).

## IFD decoding depends on chipset generation

Upstream ifdtool uses generation-specific masks, region counts and platform interpretation. LibreFren compares only the five common region geometries and explicitly leaves additional regions, permissions, density and straps unresolved.

Evidence: official-reviewed. [Source](https://github.com/coreboot/coreboot/blob/f13a6c7a61a761559d719f2b2e2a0ae1f43ddeb9/util/ifdtool/ifdtool.c).

## Broad write examples need reconciliation with preservation rules

The board documentation includes external chip-splitting and write examples alongside a requirement not to overwrite omitted ME content. Do not convert the broad example into an executable whole-chip plan without resolving the exact layout and preserved regions.

Evidence: design-inference. [Source](https://rboot.org/docs/install/dell9020.html).

## Dell 9020 completion sequence

The guide warns that vendor shutdown can write EFI variables after installation. The exact post-write power procedure and a live environment belong in the board workflow.

Evidence: official-reviewed. [Source](https://libreboot.org/docs/install/dell9020.html).

## HP 8200 staged migration

The internal migration guide uses an intermediate image, altered layout and power cycles. A generic capacity-matched full-ROM command cannot reproduce this workflow safely.

Evidence: official-reviewed. [Source](https://libreboot.org/docs/install/hp8200sff.html).

## Independent reads and recovery copies

Compare repeated reads before erasure. Store original dumps off-device. Matching bytes alone do not prove completeness, independence, correct chip selection or electrical safety.

Evidence: official-reviewed. [Source](https://libreboot.org/docs/install/simplified-hw-flashing.html).

## Voltage is a property of the actual chip

Use chip markings and its datasheet; check programmer supply and logic levels. Do not infer voltage from the laptop name, a jumper label, or a successful anecdotal flash.

Evidence: official-reviewed. [Source](https://libreboot.org/docs/install/spi.html).

## Release-specific payload choices

26.11 shifts most boards toward EDK2. Derive choices from the selected archive instead of promising GRUB keymaps, SeaBIOS or text-mode variants universally. Check the OS boot path.

Evidence: official-reviewed. [Source](https://libreboot.org/download.html).

## Kconfig validity is not hardware safety

A selectable option or successful build cannot certify that a board will initialize. Pin the baseline, toolchain, dependencies and every hardware-critical setting; require board testing before exposing editable options.

Evidence: design-inference. [Source](https://doc.coreboot.org/tutorial/part1.html).

## Codename rather than retail branding

Identify the target HWID/codename and distinguish x86 from ARM. A vendor support table and upstream source selector are evidence, not proof of support in a different distribution.

Evidence: official-reviewed. [Source](https://docs.mrchromebox.tech/docs/supported-devices.html).

## Hardware WP and software WP are separate

The GSC or physical WP mechanism controls whether protected ranges can change. Record both states and use the device-specific procedure.

Evidence: official-reviewed. [Source](https://docs.mrchromebox.tech/docs/firmware/wp/).

## Ti50 RO verification prerequisite

The current guide requires resolving AllowUnverifiedRo before Full ROM or software-WP changes. Battery disconnection does not replace the Ti50 procedure.

Evidence: official-reviewed. [Source](https://docs.mrchromebox.tech/docs/firmware/wp/).

## Custom image data preservation

Keep original device data and validate region compatibility before transferring it. Prefer the documented custom-firmware path on a bootable supported device; do not blindly use generic manual writes.

Evidence: official-reviewed. [Source](https://docs.mrchromebox.tech/docs/firmware/manual-flashing.html).

## Documentation contradictions need resolution

The reviewed Chromebook page includes source-only target notes, changing ME policy, and unresolved data-preservation text. Treat these as blockers for a generic release recipe; resolve per pinned release.

Evidence: official-reviewed. [Source](https://libreboot.org/docs/install/chromebooks-x86.html).

## Host backup may omit protected content

The Haswell guide distinguishes a live device dump from firmware-update inputs containing ME. It is historical and board-specific; do not apply its build recipe to other generations.

Evidence: official-reviewed. [Source](https://www.chromium.org/chromium-os/developer-library/reference/development/developer-information-for-chrome-os-devices/upstream-coreboot-on-intel-haswell-chromebook/).

## Failed write is not a normal reboot point

Retain logs and follow the relevant recovery procedure before rebooting after an internal flash failure.

Evidence: official-reviewed. [Source](https://flashprog.org/wiki/Flashprog).

## T480s update walkthrough

A personal report of an existing Libreboot installation update. Its force flags are not imported into this companion. Useful for understanding backup and preparation friction.

Evidence: community-reviewed. [Source](https://blog.jeronimodiaz.com/updating-libreboot-in-thinkpad-t480s/).

## Practical installation walkthrough

W500-oriented experience describes clips, repeated reads and image selection. Historical model recommendations and disputed programmer-voltage claims are not safety evidence.

Evidence: community-reviewed. [Source](https://valdemarbila.com/blog/libreboot-eng.html).

## T480s inconsistent-read report

Search-index excerpt reports unstable reads and an unusable stock backup. Full thread retrieval was denied. Corroborates the need to investigate read consistency; not a verified root cause.

Evidence: search-excerpt-only. [Source](https://www.reddit.com/r/libreboot/comments/1jfeqtk).

## X200 erase failure

Report concerns erase failure despite apparent successful reads. Read success must not be treated as proof of write capability.

Evidence: search-excerpt-only. [Source](https://www.reddit.com/r/libreboot/comments/icvr6t).

## X220 missing vendor-file report

Search excerpt describes a blank screen after omitting required files. The official insertion guide supplies the normative preparation requirement.

Evidence: search-excerpt-only. [Source](https://www.reddit.com/r/libreboot/comments/1kjkmah).

## T400 failed boot and lost backup

Report highlights the importance of retaining a separate recovery copy throughout the operation. Exact root cause remains unverified.

Evidence: search-excerpt-only. [Source](https://www.reddit.com/r/libreboot/comments/1m60n75).

## T480 memory instability report

Report describes boot and resume instability. A completed write is not acceptance testing; RAM topology and sleep/resume need test coverage.

Evidence: search-excerpt-only. [Source](https://www.reddit.com/r/libreboot/comments/1m5knh3).

## Chromebook failure after settings change

Forum report describes failure after changing advanced settings. This is a test lead, not proof of which setting caused the failure.

Evidence: search-excerpt-only. [Source](https://forum.chrultrabook.com/t/chromebook-mostly-bricked-due-to-a-setting-i-changed-in-coreboot/7800).

## Full-ROM flashing trouble

Forum excerpt includes VPD extraction during a Chromebook installation. Investigate exact release and board before drawing conclusions.

Evidence: search-excerpt-only. [Source](https://forum.chrultrabook.com/t/im-having-trouble-flashing-the-full-rom-firmware/9010).

## Dell 9020 no-POST report

Anecdotal report of intermittent POST and advice to gather firmware logs. Add POST consistency to board qualification tests.

Evidence: search-excerpt-only. [Source](https://www.reddit.com/r/libreboot/comments/1b43uwc).

## HP 820 G2 success report

A success report is a useful candidate for a test fixture but does not establish all variants, releases or components work.

Evidence: search-excerpt-only. [Source](https://www.reddit.com/r/coreboot/comments/14o306s).

## KGPE-D16 historical issues

A user reports booting coreboot 4.10 with issues. Bind historical hardware reports to their exact source revision and configuration.

Evidence: search-excerpt-only. [Source](https://www.reddit.com/r/coreboot/comments/yb3g2j).

## Morphius Full ROM and VPD discussion

Discussion covers a failed Full ROM installation and VPD handling. External flashing alone cannot repair an incompatible image.

Evidence: search-excerpt-only. [Source](https://www.reddit.com/r/coreboot/comments/1dpagh0).
