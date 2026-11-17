# Repository and documentation analysis

Research date: 2026-11-17. Exact commits are in `librefren/data/revisions.json`. The repositories are complete shallow working trees, without fetched build dependencies. No upstream files were edited or contributed back.

## Libreboot

The inspected tree dispatches tasks through `mk` and sources `include/env`, `include/fw` and `include/mk`. Older tutorials referring to `script/` are not a reliable API for this revision. Board configurations live under `config/module/coreboot`; dependency trees coexist with board targets. The inventory importer requires a board config directory instead of interpreting every dependency tree as hardware.

`include/env/init.sh` implements the dependency entry point and rejects non-dependency builds as root. Dependency profiles are executable shell configuration, not passive package lists. The companion treats upstream preparation as code execution: it requires a pinned unmodified checkout, previews the profile, requests an explicit user action and captures logs. This is not an OS sandbox for the upstream build.

`include/fw/inject.sh` accepts archives, resolves their target and builds the appropriate utilities. It includes target-translation logic for older naming schemes. The companion does not use that translation to select a different download: downloading remains exact-release/exact-target.

`include/fw/vendor.sh` handles board-specific vendor inputs and hash checking. Paths can include ME, MRC/refcode, FSP, EC or Thunderbolt components. Vendor processing is not simply copying a universal blob into a universal offset. Missing payload inputs and scrubbed image markers cannot be repaired by removing the warning name or padding byte. The companion preserves the original signed archive and labels all resulting files unqualified until board-specific checks exist.

`config/module/coreboot/lenovo_thinkpad_t480s_16mb/target.cfg` selects a distinct vendor profile and `sklkbl` descriptor platform. Its saved config selects `BOARD_LENOVO_T480S`. This demonstrates why model suffixes and platform-specific descriptor parsing must be preserved. It is an example, not the application's coverage boundary.

`include/fw/rom.sh` orchestrates payload/image production. Not all configured boards are shipped as binary releases. Current Chromebook documentation expressly describes source-only targets and a transition in payload/ME policy. The download layer refuses an absent exact artifact instead of substituting a nearby target.

## RBoot

RBoot has its own `rbmk` repository, releases, key URL and documentation. Historical Canoeboot trees are retained only as evidence for migration research. Current RBoot targets are imported from rbmk, not copied from the predecessor's list.

`include/fw/inject.sh` still exists, but an identical command name does not imply Libreboot-style proprietary-file insertion. `docs/install/ivy_has_common.md` describes preserving factory vendor regions on relevant Intel systems. `dell_gbe.md` warns about incompatible GbE region lengths during migration. Preparing an image that looks structurally valid does not authorize overwriting omitted vendor regions. Generic RBoot injection is therefore blocked in this preview.

Some target configs are inherited or assembled from fragments. The importer records literal structural facts and hashes; it does not execute shell to resolve them or pretend the fragments are fully evaluated Kconfig. Hardware approval requires resolving the selected build tree and final configuration.

## coreboot

The current checkout includes 930 selectors parsed from `src/mainboard/**/Kconfig.name`. A single directory can contain several distinct selectable boards: the Skylake/Kabylake ThinkPad directory, for example, has separate selectors for T480 and T480s. Conversely, a retail brand name can map to multiple board/codename variants. Selectors are not a complete DMI identity database.

`Documentation/` is imported into the local full-text index, including board guides, platform details, payload guidance and tooling documentation. Coreboot source alone does not supply a universal distribution-style flashable release. The unresolved pipeline needs board-specific baseline configs, blob provenance, payload constraints, toolchain pins and final image validation.

Kconfig's dependency solver establishes configuration relationships; it is not a proof that every selectable combination is electrically or functionally safe. Editing mainboard, flash geometry, memory initialization, EC, power, GPIO, security/Boot Guard, IFD/FM AP or vendor-component settings must not become a generic novice interface. Even ostensibly cosmetic changes can overflow flash regions or disrupt the available display/boot path. No settings are presented as universally safe.

## Chromebook source/documentation reconciliation

The reviewed Libreboot x86 guide contains current notes alongside historical examples and unresolved preservation instructions. It discusses EDK2, source-only images, the Google flashrom fork, RO_VPD and changing ME behaviour. These contradictions are recorded as unresolved release-specific questions, not averaged into a recipe.

Current MrChromebox documentation distinguishes native Linux/ChromeOS access from Crostini/VM environments, requires board/HWID identification, describes automatic data preservation in its custom-firmware path, and distinguishes CR50 from Ti50. Ti50 RO verification can block boot even when only software-WP state was changed. Its procedure is a manual handoff only after matching the actual target and chosen distribution; the companion does not execute the external flashing script.

ARM Chromebooks use a separate project/architecture path. MrChromebox x86 support must not be extended to ARM by inference. Data-preservation layout compatibility and GSC/CCD recovery readiness remain explicit prerequisites.

## Evidence tiers

1. **Official source/documentation reviewed:** scoped findings with a source and review date; still not hardware certification.
2. **Indexed official material:** complete local text available for research; not individually assessed for correctness or currency.
3. **Community material reviewed:** useful experiences and failure cases; not normative flashing authority.
4. **Search excerpts:** snippets only when the full forum page was inaccessible; clearly labelled.
5. **Discovered references:** URLs extracted from project docs for follow-up; not fetched or reviewed merely because they appear in the database.

The automated warning/TODO review queue is a triage aid. It cannot resolve contradictory sources, approve hardware support, or certify a final ROM.
