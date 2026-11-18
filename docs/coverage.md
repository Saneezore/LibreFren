# Coverage ledger

Scope: **all models represented by Libreboot, RBoot and coreboot**, with archived documentation retained for migration research. The implementation currently imports all board targets/selectors found by its parser in the pinned working trees. Historical revisions and downstream forks are not exhaustively enumerated.

| Capability | Coverage today | Remaining requirement |
| --- | --- | --- |
| Board inventory | 327 Libreboot targets, 78 RBoot targets, 930 coreboot selectors | Resolve inherited configs, historical boards, aliases and physical revisions |
| Hardware detection | Advisory DMI fields and exact-name candidates | Reviewed multi-signal identities, chipset/revision/flash geometry and Chromebook HWID acquisition |
| Official documentation | 770 local full-text documents, including predecessor history | Per-board reconciliation, temporal validity, contradictions and independent review |
| Community knowledge | Reviewed blogs and clearly labelled search-excerpt leads | Obtain inaccessible threads, reproduce findings, tie reports to exact board/release |
| Downloads | Exact target only, two pinned current distribution releases, signed archive verification | Historical schemas, key rotation/revocation and source-only build routes |
| Dependencies | Explicitly confirmed upstream host-profile installer | Test on each supported distribution; isolate and qualify build environments |
| Libreboot preparation | Pinned upstream injection runner, logs, MAC choice, archive/variant checks | Real vendor preparation tests and component/region validation per target |
| RBoot preparation | Authenticated inspection-only variant staging, common IFD region comparisons and preservation instructions; generic blob injection refused | Implement and test per-board region-preserving preparation and migration plans |
| coreboot settings/builds | Fresh pinned exact-selector configurations; local and GitHub Actions builds, saved requests, cancellation and provenance-checked downloads; one emulated target compiled remotely | Completed emulation boot validation, reviewed baseline and allowed hardware settings per board, vendor-input integration and hardware qualification |
| Chromebooks | Detailed manual guide, FMAP/IFD comparisons, bounded VPD 2.0 record inspection and GBB 1.2/HWID checksum evidence | Exact-board WP/GSC recipes, required VPD fields/calibration semantics, CBFS HWID, GBB key trust/flags, MRC validation and reviewed data migration |
| Variant selection | Actual archive entries; source hash rechecked against a private snapshot; RBoot signature reverified | Board-specific payload/graphics/keymap compatibility and hardware qualification |
| Flash command generation | Disabled for all physical targets | Independently reviewed profile and complete evidence chain |
| External flashing | General prerequisites and board-source handoff | Qualified chip topology, voltage, offsets, wiring and power sequence per board |
| AppImage | x86_64 local preview plus CI packaging | Cross-distribution tests, ARM host build, publication and release provenance |

The same fail-closed policy applies across the inventory. No particular laptop family is the product's primary support target. An entry's inclusion is research coverage; operational support must be earned separately through model-specific validation.
