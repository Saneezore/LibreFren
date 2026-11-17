# coreboot build workspaces

In the guided TUI, select an exact coreboot selector, fetch the pinned source, and open **Configure and build coreboot**. The app can install host dependencies after showing the selected distribution's package command and obtaining explicit confirmation. Package-manager output and its confirmation stay on the terminal; LibreFren does not collect passwords.

Create a new configuration and choose whether upstream binary-only repositories are permitted. This choice may leave required inputs unavailable; it does not certify a blob-free build as bootable. Review the generated defaults, select build parallelism (1–64 jobs, default 1), build the cross-toolchain, then compile. Live logs show progress. Esc cancels the operation and terminates its process group. Each command has a two-hour limit, with a five-minute limit for configuration and a 64 MiB log limit.

Every configuration receives a new private checkout of the bundled coreboot revision. The app does not reuse a different board's `.config`, ignored build outputs or git object alternates. It verifies the exact board selector, vendor and `MAINBOARD_DIR`, records the configuration hash and derives the cross-toolchain from the target architecture. Hardware settings and payload selection are locked. Upstream defaults can contain no payload; the receipt explicitly identifies these outputs as unable to boot an operating system.

Before and after a build, source/submodule changes, a changed configuration, another board selector, a changed binary-dependency policy or the system-toolchain override stop progression. Interrupted or failed workspaces retain their logs and cannot be reused. The user must create a fresh configuration. Builds run pinned upstream scripts as the current user, with inherited Make, Kconfig, compiler and git overrides removed. They are **not sandboxed**. Upstream scripts may download toolchain, submodule and payload dependencies; pinning the main source does not certify every external input or a reproducible build.

Successful compilation exports a separate `UNQUALIFIED-coreboot.rom` only after checking its capacity against `CONFIG_ROM_SIZE`. Its receipt records the source/configuration/image hashes, submodule status and limitations. The candidate can be compared with a complete original backup in the layout inspector. It does not unlock internal write commands or external flashing plans.

## Manual handoffs

For a missing vendor input, unsupported configuration mapping, inadequate host toolchain, or failed compile, read the retained log and the exact board documentation. Do not select another board, remove checks, or substitute another device's vendor files. Board-specific FSP/ME/microcode, descriptor permissions, VPD/HWID, EC requirements, payload integration and recovery remain outside the generic build runner. A compiling upstream default is not an installation profile.

RBoot region-preserving assembly and Chromebook identity migration remain separate, unfinished workflows. This build feature does not bypass those requirements or modify existing firmware backups.

## Evidence and limits

The unit tests exercise real local git workspaces with a fixture Makefile, target/configuration changes, command injection rejection, cancellation/timeouts, failed-workspace refusal and output quarantine. [The upstream configuration check](coreboot-configuration-validation.json) separately runs the actual pinned Kconfig implementation across the listed selectors. Locally, bison/flex were downloaded and unpacked into a test directory without installing system packages; the test harness explicitly supplies that private tool directory. CI uses the runner's host packages.

No complete cross-toolchain build, real coreboot ROM compilation or physical boot test has been validated for this feature yet. Configuration tests must not be reported as image-build or hardware support tests. All indexed coreboot selectors are selectable, but unsupported mappings and missing prerequisites stop; the inventory is not a promise that all defaults build successfully.

Implementation references: [upstream tutorial](https://doc.coreboot.org/tutorial/part1.html), [pinned toolchain targets](https://github.com/coreboot/coreboot/blob/f13a6c7a61a761559d719f2b2e2a0ae1f43ddeb9/util/crossgcc/Makefile.mk), [pinned payload defaults](https://github.com/coreboot/coreboot/blob/f13a6c7a61a761559d719f2b2e2a0ae1f43ddeb9/payloads/Kconfig), and [board documentation](https://doc.coreboot.org/mainboard/index.html).
