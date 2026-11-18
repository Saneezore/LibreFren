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

GitHub Actions run [44234928621](https://github.com/Saneezore/LibreFren/actions/runs/44234928621) completed the cross-toolchain and ROM build for the pinned QEMU i440fx default. Its logs show coreboot ramstage and SeaBIOS startup; the final no-boot-device assertion failed after the emulator stopped progressing at the boot menu. The workflow remains failed, and this is not a completed boot test or physical hardware qualification. Configuration tests must not be reported as image-build or hardware support tests. All indexed coreboot selectors are selectable, but unsupported mappings and missing prerequisites stop; the inventory is not a promise that all defaults build successfully.

Implementation references: [upstream tutorial](https://doc.coreboot.org/tutorial/part1.html), [pinned toolchain targets](https://github.com/coreboot/coreboot/blob/f13a6c7a61a761559d719f2b2e2a0ae1f43ddeb9/util/crossgcc/Makefile.mk), [pinned payload defaults](https://github.com/coreboot/coreboot/blob/f13a6c7a61a761559d719f2b2e2a0ae1f43ddeb9/payloads/Kconfig), and [board documentation](https://doc.coreboot.org/mainboard/index.html).

## GitHub Actions builds from the TUI

For a low-powered device, open **Configure and build coreboot → Build on GitHub Actions / resume remote build**. No local source checkout, compiler or host build dependencies are required for this path. Install [GitHub CLI](https://cli.github.com/) and authenticate with `gh auth login --hostname github.com`. Use a LibreFren repository or fork where your account has write access, Actions is enabled, and `coreboot-remote.yml` is present. Fine-grained credentials need Actions read/write and Contents read permissions. Check the repository's Actions usage limits and billing before starting.

Choose the exact target and whether to permit upstream binary repositories. Review the repository and application commit, then explicitly confirm the request. The runner fetches the bundled coreboot revision, generates and checks its default configuration, builds with two jobs, and exports an **unqualified** candidate. The job has a 150-minute limit. Missing board inputs stop it. Hardware settings are locked; this preview does not accept uploaded configurations or vendor files.

Only target/build choices and a random request identifier are sent to GitHub. Backups, device identities and local firmware data stay on the device. Build logs and artifacts follow repository access rules and expire after seven days. Actions executes the reviewed repository code and downloads upstream dependencies: use a trusted repository. A successful run and matching hashes are provenance evidence, not hardware qualification or reproducibility certification.

Requests are saved before dispatch. **Resume / inspect a saved request** works after restarting the app and filters requests by selected target. Refresh shows status and the GitHub run link. Closing the TUI leaves remote work running; explicit cancellation requires confirmation of the run ID. After a network failure, inspect the saved request before starting another build: GitHub might already have accepted the dispatch.

Download checks bind the run to the reviewed commit, workflow, repository and unique request. The archive must match GitHub's SHA-256 digest and contain exactly the receipt, configuration and candidate ROM. The receipt must match the target, source revision and binary-dependency choice; configuration/image hashes, board selectors and ROM capacity are checked again. Files become session candidates only after these checks pass, and flashing stays blocked. No release is published by this workflow.

References: [workflow dispatch API](https://docs.github.com/en/rest/actions/workflows#create-a-workflow-dispatch-event), [artifact API](https://docs.github.com/en/rest/actions/artifacts), [GitHub CLI API command](https://cli.github.com/manual/gh_api).
