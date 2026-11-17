# Safety model and qualification requirements

The safe default is refusal with actionable instructions. A release signature, a filename, successful injection, a successful build and a user acknowledgement each establish different facts. None independently establishes that a ROM is safe to flash.

## Required future evidence chain

Hardware identity → physical revision and component inventory → exact project/release profile → authenticated archive/source → required device backups → preparation provenance → structural image validation → allowed variant → allowed write regions → target protection state → recovery readiness → explicit user approval → verified write → board-specific completion sequence.

Every derived artifact needs the input hashes, source/tool versions, settings, target identity, region map and output hash. Changing any dependency invalidates later approval. Crash recovery must reopen a session in an unapproved state and rehash all files. A future write planner must reopen the exact file it inspected and prevent replacement between validation and use.

## Required hardware profile fields

- Stable internal board ID; exact identity evidence; retail aliases with provenance; PCB revisions; CPU/GPU/RAM/EC constraints; project and release range.
- Physical chip model, capacity, voltage, chip count and topology; image-to-chip offsets; IFD platform; FMAP/CBFS layout; expected components and permitted write regions.
- Stock versus existing custom firmware migration paths; vendor BIOS/EC/Thunderbolt prerequisites; boot mode and disk-encryption recovery requirements.
- Internal eligibility conditions and required read/protection evidence; external wiring/disassembly guide; allowed programmer and electrical checks; exact completion/power sequence.
- Required device-specific data, extraction method, region bounds and validation; known failures; source conflicts; timestamp; reviewer and hardware test evidence.
- For Chromebooks: exact HWID/codename, architecture, firmware type, GSC generation, CCD readiness, hardware and software WP states, Ti50 RO verification requirements, source/destination FMAP compatibility, VPD/HWID/GBB/MRC handling and OS compatibility.

Manual confirmations record observations; they cannot create an affirmative result for a missing machine check. Unknown identity, conflicting sources, missing profile, unsigned input, unresolved blob provenance, unreadable regions, incompatible layouts, incorrect chip capacity or failed verification must block a write plan.

## Implemented controls

No firmware write executor exists. `flash_gate()` always refuses, independent of mutable inventory metadata. No expert override is exposed. Network paths use exact target names and approved HTTPS origins; redirects are checked. GPG runs with an isolated keyring, no configuration, a pinned primary fingerprint, and rejects invalid/expired/revoked signatures. Downloaded archives are bounded and checked for traversal, links, devices and duplicate members before use. Extraction creates a new file and never overwrites a backup. Prepared variants remain unapproved.

The dependency and preparation runner is opt-in and invokes pinned upstream code. It is not a hostile-code sandbox. The signature trust bootstrap relies on the configured fingerprint; offline revocations and signed catalog freshness are not yet implemented. A same-user attacker can tamper with this preview's source or files. There is no claim that the companion can stop commands a user runs independently.

## Qualification before unlocking any board

Obtain independent firmware-engineer review, reproducible signed fixtures and tests for wrong-model/suffix/PCB/architecture substitutions. Validate descriptor/FMAP overlap handling, vendor-file presence/content, region preservation, multi-chip layouts, corrupted downloads, signature/key rollover, source mutation, interrupted preparation, cancellation, stale sessions and disk exhaustion. Test successful boot, repeated cold/warm boot, RAM, display, storage, network, thermals, charging and sleep/resume on actual recoverable hardware. Test recovery too.

Do not infer support for all models from a sample that boots. Record test coverage separately for every qualified board/release/configuration. No amount of unit testing can establish electrical correctness for an unexamined physical target.
