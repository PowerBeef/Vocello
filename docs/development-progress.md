---
status: active
owner: backend-and-platform
reviewed: 2026-11-21
summary: Current resume checkpoint; config/roadmap.json owns open work, config/roadmap-archive.json holds finished work, and older narrative lives in git history.
sourceOfTruth:
  - config/roadmap.json
  - config/runtime-refactor-contract.json
---
# Vocello development checkpoint

Start here, then follow `config/roadmap.json`'s `primaryPlan` and the
[release-first execution plan](reference/release-first-execution-2026-09.md).
This is a narrative, not a second work ledger. Product source, contracts and scripts win.
Older checkpoints live in git history (`git log -p -- docs/development-progress.md`): commit
`3eeed981` holds October 26 through November 15, `20533a12` holds October 23 to 25, and
`a0597deb` every checkpoint before them.

## Resume now

### November 21: iOS dev/test/bench overhaul (Waves 1–4) & Pack A release blockers (`RB-01`..`RB-12`) landed locally (resume here)

Six commits landed on local `main` ahead of `origin/main` (`4f273cb4`; **not yet pushed**), bringing
iOS development, profiling, UI-perf testing, and policy modularization to parity with macOS and
resolving all twelve sample-preserving Pack A Release Blockers (`RB-01`..`RB-12`) ahead of the
physical-iPhone 3.1.0 calibration and qualification window (**Wave 5**). Packs B/C remain deferred
post-3.1 behind `RF-57`.

- **iOS Dev/Test/Bench Overhaul — Waves 1–4 (`c43f825f`, `4783d725`, `553d4e4a`, `deca64ee`,
  `DW-03`/`DW-04`/`RF-59`, Waves 2–4 `Reviewed-by: vocello-swift-review`):**
  - **Wave 1 (`c43f825f`):** aligned owned-only `-Onone` dev vs `-O` measured iOS build lanes,
    enabled `SWIFT_TREAT_WARNINGS_AS_ERRORS: YES` on `VocelloiOSUITests` and
    `VocelloiOSCandidateUITests`, and hardened CI parity.
  - **Wave 2 (`4783d725`):** brought iOS profiling, `Metal System Trace` (`os_signpost`), app-layer
    memory sampling, and benchmark history contracts to macOS parity.
  - **Wave 3 (`553d4e4a`):** overhauled `VocelloiOSPerfUITests` to snapshot-free parity, wired
    `ui_test.sh` hitch/stall gates and visual QA, and aligned iOS `ui-perf` lineage contracts.
  - **Wave 4 (`deca64ee`):** extracted static framework `VocelloiOSPolicies` (linked only by
    `VocelloiOS` and iOS/core test bundles, zero link on macOS/CLI), added hermetic RF-59 upgrade
    and attribution XCUITests, burned iOS Python pyright findings to 0, and upgraded `scripts/dev.sh`
    iOS ergonomics.
- **Engine & Hybrid Delivery Pack A — Commit A1 (`1d8397f6`, `RF-35`/`RF-59`,
  `Reviewed-by: vocello-swift-review`):** resolved `RB-01`..`RB-05` — MLX async readback safety,
  deterministic `prewarmSlot` waiting (`prewarm_slot_wait_ms`), `MLXModelLoadCoordinator` load-state
  consistency, `BG-01` background-transition generation guard + `inFlightPreparationDepth`, and
  `IOSMemoryBudgetPolicy.minimumCloneCapableProcessLimitBytes()` (`4,779 MiB`).
- **Engine & Hybrid Delivery Pack A — Commit A2 (`f269200d`, `RF-59`,
  `Reviewed-by: vocello-swift-review`):** resolved `RB-06`..`RB-12` + `runQueueScenario` assertions —
  - `RB-06`: relaunch `.queued` snapshot publication, synchronous coordinator state checks, and
    `IOSModelDownloadLedger.isCurrentArtifactFailed(modelID:artifactVersion:)` so 3.0 → 3.1
    superseded ledger entries never suppress the RF-59 Update prompt.
  - `RB-07`: `SharedStorageBackgroundActivity` (`ProcessInfo.performExpiringActivity`),
    `StorageBackgroundExpirationFlag` propagation across every `IOSBackgroundTime.hold` App Group
    `flock(LOCK_EX)` site, dedicated non-cancellation `backgroundAssertionUnavailable`, and
    expiration checks before post-tombstone reclamation.
  - `RB-08`: pure `IOSBackgroundSessionCompletionCoordinator` in `VocelloiOSPolicies` plus
    exact-once `logicalRequestID`-scoped `HuggingFaceDownloader` background task submission
    flushing (closing Race A wake-before-restore, Race B `beginDownload`→`runDownload`/Model 1→2
    handoffs, dead-task retries, and >6-file rollovers).
  - `RB-09`: immediate unreferenced shared-blob reclamation on `releaseUpdatePins` (off-actor on
    macOS, serialized via `pinReleaseTask` on iOS) + 24 h abandoned-pin fallback sweep.
  - `RB-10`: `.preparing`/`.starting` cancellation targets, `admissionSettlementWaiters` teardown
    sync before deletion, and pre-existing ledger tombstoning before discarding staging.
  - `RB-11`: extracted `IOSAttributionManifest` into `VocelloiOSPolicies` and rendered hybrid
    `additionalBases` and `builtFrom` provenance in `OpenSourceLicensesScreen`.
  - `RB-12`: subtracted verified shared-component bytes from Make Room space estimates, added typed
    `ModelUpdateFailureClassifiable` (`ENOSPC`/`EDQUOT`/Carbon `-34`), gated Make Room consent on
    `afterMakingRoom == .startUpdate`, and added `runQueueScenario` RB-06/RB-10 XCUITest checks.
- **Verification on `f269200d`:** `scripts/dev.sh lint` PASS (35 paths privacy scan, pyright 0 new,
  strict SwiftLint 0 warnings/errors), 39/39 contract validators PASS, 44 Python tests PASS,
  `./scripts/macos_test.sh test` PASS (`VocelloCoreTests` + `Qwen3RuntimeTests`), `scripts/dev.sh
  ios` PASS (`VocelloiOS` + iOS executable scan + `VocelloiOSLogicTests`), `scripts/dev.sh ios --ui`
  PASS (all 3 iOS XCUITest bundles), `scripts/dev.sh build` PASS (`Vocello.app`), and
  `./scripts/build.sh cli --version` PASS (`vocello 3.1.0`).
- **Next:** push these local `main` commits when explicitly requested, watch push CI on `xcode-27`,
  and then execute **Wave 5** in a single announced physical-iPhone window (iPhone Mirroring quit,
  `QVOICE_LEAD_ONLY=1`): 3× iOS `ui-perf` calibrations + threshold calibration, `model-management`
  (queue/relaunch + upgrade Make Room), `profile --kind metal`, and the iOS 3.1.0 candidate
  qualification/TestFlight tag (`v3.1.0-ios.4`).

### November 20, night: Antigravity harness Phases A, B & C complete on local `main`

Phases A, B and C of the Antigravity harness & engineering-velocity upgrade landed on local `main`
(ahead of `origin/main` `670f7e77`; **not yet pushed**), closing five authorized backlog items
(`BKL-63`, `BKL-74`, `BKL-79`, `BKL-87`, `BKL-90`) with zero audio-sample changes and zero
product-binary regressions.

- **Phase A — Harness safety, CI blind spots & workflow kit (`0e207be0`..`f5b1879f`, closes `BKL-63`,
  `BKL-74`, `BKL-87`, `BKL-90`):** fixed Sparkle incremental `CodeSign` race + macOS/iOS build-log
  mirroring (live macOS smoke `macos-xcui-smoke-20261120-202030-03d22d24` and perf
  `macos-xcui-perf-20261120-223253-e83975d8` 12/12 PASS); upgraded irreversible external/destructive
  commands & MCP writes to uncacheable `"force_ask"` with `PostInvocation` drift reminders,
  non-looping `Stop` whitespace guard, in-process `agent_guard` and Antigravity worktree leases;
  gated `ios_control_audit.py validate` in `contract_gate.py`; fixed `nightly.yml` and
  `release-rehearsal.yml` `report` triggers (`always() && !cancelled()`); added `.agents/workflows/`
  (`swift_adversarial_review.py`, `xcuitest_visual_qa.py`, `debt_burndown_pipeline.py`,
  `qc_experiment_synthesizer.py`).
- **Phase B — Lint burndown, Swift 6 hardening, security & perf harness (`f466500e`..`81b0dbf8`,
  `aa97fb2e`, closes `BKL-79`):**
  - Burned **Ruff `44 → 0`** (`f466500e`) and **Pyright `789 → 81`** across 72 Python files via two
    3-worker parallel `share`-worktree waves (`08c70744`, `aa97fb2e`; 0 `# type: ignore`; 3,149
    pytest passed).
  - Hardened `Packages/VocelloQwen3Core` (`cc305197`, `Reviewed-by: vocello-swift-review`):
    `swift-tools-version: 6.2`, `.treatAllWarnings(as: .error)` on 4/5 targets (`MLXAudioTTS`
    documented as waiting on upstream `mlx-swift` `MLXArray: Sendable`), SwiftLint expanded to
    `Packages/VocelloQwen3Core/` (0/0) + `no_if_debug` rule, pure-Swift parameterized Swift Testing
    suite (`Qwen3PropertyInvariantTests`, 9 `@Test` suites); audited all 164 `try?` sites in
    `Sources/` (zero silent data-loss sites).
  - Hardened `HuggingFaceDownloader` (`1251fcc4`, `Reviewed-by: vocello-swift-review`, closes
    `BKL-79`) to fail closed when any planned/installed file lacks a valid 64-hex SHA-256 or
    disagrees between `files` and `installedFiles`, with zero-request/zero-staging tests.
  - Eliminated XCUITest accessibility snapshot walks in `test05DeliveryMenu()` (`81b0dbf8`, `BKL-77`)
    using window-anchored coordinate clicks + keyboard, exposed `actionHitchTimeMSPerS` /
    `queryHitchTimeMSPerS`, bumped `("ui-perf", "macos")` lineage to v3 (`e073bbb8`), ran 3 clean
    canonical calibrations (`8f412666`, `8b059da3`, `b6cfbcce`: `[59.446, 55.426, 53.901]` ms/s,
    median `55.426` vs `84.168`), recalibrated `config/ui-perf-thresholds.json` (`72.5 ms/s`,
    `130 ms`), added `delivery-menu` to `enforce`, and closed **`BKL-77`** (`4974d4e9`).
- **Phase C — Metal profiling, `VocelloSharedPolicies` modularization, Xcode 27.2 CI cutover &
  playbook (`2aea00c9`, `91f5eae6`):** added `macos_test.sh profile --kind metal` (`Metal System
  Trace` + `os_signpost`) across trace retention and benchmark history contracts; extracted pure
  multiplatform static framework `VocelloSharedPolicies` (`91f5eae6`, `Reviewed-by:
  vocello-swift-review`) compiling 7 runtime/Studio/ownership/retry policy files once instead of
  4–5x across 5 targets (macOS, iOS, CLI and all 3 UI test bundles verified green; push CI
  `44853701944` green); cut over `config/toolchain.json` (`Xcode 27.2` / `Swift 6.4.2`) and all 6
  macOS GitHub workflows (`ci.yml`, `nightly.yml`, `promote-release.yml`, `release-rehearsal.yml`,
  `release.yml`, `security.yml`) from `macos-26` to GA `xcode-27` (`DW-04`, matching local
  `Xcode 27.2` build `27B52`); documented the Repeatable Innovation Playbook in
  `docs/reference/development-workflow.md`.
- **Next:** push the `BKL-77` calibration + `DW-04` Xcode 27.2 cutover commits when requested,
  observe the first `xcode-27` push CI run, and resume iOS 3.1.0 candidate work (`RF-12`/`RF-15`/
  `RF-35`–`RF-42`) in the next iPhone window.

### November 20: Antigravity harness takeover

The repository-owned agent harness moved from Claude Code (`.claude/`, `CLAUDE.md`,
`website/CLAUDE.md`) to Antigravity (`AGENTS.md`, `website/AGENTS.md`, `.agents/hooks.json`,
`.agents/plugins/vocello/` and `scripts/hooks/agy_hook_adapter.py`) under `RF-67`, with zero Swift
or product-binary changes. Pushed through `670f7e77` with CI green (`44831811307`). `main` stays on
the iOS 3.1.0 TestFlight candidate track (`v3.1.0-ios.3`, `focusLock` active; `RF-35`, `RF-41`,
`RF-42` remain in flight awaiting an iPhone window).

- **Live verification (2026-11-20):** Antigravity loaded `AGENTS.md`, all six `vocello-*` skills and
  both read-only subagents (`vocello-swift-review`, `vocello-xcresult-triage`). Live `PreToolUse`
  probes denied `git push --force --dry-run origin main`, `edit_file` on `docs/ROADMAP.md`,
  `mobilebuildmcp:list_sims` and `cua-driver_cua-driver:list_apps`, while allowing
  `git status --short --branch` and `mobilebuildmcp:list_schemes`. `RF-67` is closed.

### November 17: Vocello 3.1.0 is public on the Mac

The maintainer uploaded the promotion manifest to the v3.1.0 draft and dispatched **Promote verified
release** from the tag (run 44036811898, approved on the `release` environment). Every step passed,
and at 07:17 UTC the release went public as the latest: 13 assets, and `releases/latest`'s
`appcast.xml` now resolves to v3.1.0, so Sparkle offers it. Two stray drafts that a release-edit
link had created on the phone were deleted first. `main` was pushed through `f99b5c33` with CI and
the release rehearsal green.

The post-promotion refresh is committed on local `main` (`ac173582`): the six promotion records,
and the README chart, performance art and website pooled over the two build-31 records through
`0b6bc26b` (0.29 to 0.41 warm RTF).

The published, notarized 3.1.0 CLI then passed `cli_package.py qualify` on this Mac: Built-in
English, French Voice Design and Clone (a Vocello-generated reference) each with a strict QC pass
and EOS, the two-item batch, cancellation (exit 130, cleanup acknowledged, no output) and the error
exits. Its report stays untracked under `build/artifacts/macos/release`. RF-61 is closed. The 3.1
website is live; its pooled performance numbers deploy with the next push of `main`.

### November 16, night: the follow-up release's Mac backlog, first wave

At the maintainer's request (work for a follow-up release, Mac-only, no lanes on the screen), the
roadmap gained a `needs` tag (mac, keyboard, iphone) on every open item and the first wave of
Mac-only backlog fixes landed on `main` with tests; the routed check, the full macOS deterministic
suite, the CLI, the iPhone compiles and the UI-test bundles pass.

- **Closed:** BKL-18, 20, 21, 22, 24, 25, 26, 32, 37, 46, 47, 48, 58, 64, 66, 70 and 73; DA-14;
  RF-64, superseded by RF-63 (iPhone Settings already has a Help & Support row).
- **Engine-remediation parts done:** B-02 (BKL-73), B-12 (`_exit` in the CLI's forced exit), C-13
  (the QC observer above 102.4 kHz) and BKL-01 (control-token-only scripts have nothing to speak).
- **Fixed, waiting on a run:** BKL-33 and BKL-19 on the next macOS smoke, BKL-28 on the marketing
  lane, BKL-23 on a production Mac language bench, BKL-50 on the next Linux CI run, BKL-60 on the
  phone.
