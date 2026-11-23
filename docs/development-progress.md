---
status: active
owner: backend-and-platform
reviewed: 2026-11-23
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

### November 23: `RF-72` closed; Pack B (`RF-68` Mac + `RF-69`) verified bit-identical, memory-qualified & committed (local `main`, unpushed); entering Pack C (`RF-70`)

Local `main` is ahead of `origin/main` (`67ebb3f7`; awaiting explicit push authorization) with the
first two phases of the approved 3.2 execution plan completed and verified:

- **`RF-72` (closed `done`, `611388ac..26bbfeec`):** Landed the offline, report-only Gemini 4 Neon
  multimodal audio QC complement (`scripts/qc/multimodal.py`, `scripts/qc.py multimodal`,
  `config/qc/multimodal-rubric-v1.json`, `vocello-audio-qc` skill, Antigravity `run_workflow`
  emitter) strictly outside QC v2 `SCORING_SOURCES` and Fast QC, blocking personal audio by default.
  Recorded `benchmarks/qc/multimodal-eval-v1.json` calibration: `diction`, `delivery`, and
  `pairwise` are `active_advisory` (Q2 strict `unusable` precision `8/9 = 88.9%` vs `31%` QC v2
  baseline, broad recall `11/11 = 100%`, clean human FA `1/30 = 3.3%`, C1 tie `12/12`, C2 win
  `8/8`, swap flip `1/16 = 6.25%`); static `clone` speaker verification remains fail-closed at
  `abstain_uncalibrated` (`75.0%` C4 balanced accuracy).
- **Pack B (`RF-69` closed `done`; `RF-68` Mac work complete, `needs: iphone` only, `695717be..9d572dfb`, all substantive Swift commits `Reviewed-by: vocello-swift-review`):**
  - **`RF-68` (engine/package, `574d58d8..9d572dfb`):** single `evalForReadback` error check,
    fail-closed quantization parse + `[.noUnusedKeys, .shapeMismatch]` + fused-projection summary,
    `A-08` per-encode Mimi encoder KV cache, `A-27` rectangular `[seqLen, totalLen]` decoder causal
    mask, hoisted/prewarmed `CodePredictorCompiledPlan` with lazy per-pass KV buffers and
    deduplicated cache clears, telemetry-gated `captureIntrospection` (keeping chunk timings on),
    package hygiene, narrow `A3` fixed-shape 3 KiB GPU `seenMask` with prewarm warmup (`3852e8c7`;
    `H2` AudioSeal weight caching and full speculative `A3` deferred per D2), and
    `compile(inputs: [weightInputs])` (`87d6a4b0`) fixing a `180.2 MiB/switch` cross-thread MLX
    `CompileCache` weight leak caught by the Mac memory qualification.
  - **`RF-69` (runtime, lease, QC & delivery, `052f7fb9..efe6400f`):** closed all 6 Mac/CLI
    `EngineHostLease` / `MacEngineHostCoordinator` races with direct `VocelloCoreTests` coverage,
    wired `unloadEpoch`, `.starting` on cold load, `stop()`/`B-05` `forMemoryRelief` unloads,
    skipped redundant post-watermark Fast QC in `IOSLongFormProjectRunner`, classified Carbon `-34`,
    wired explicit Korean long-form warnings across CLI/Mac/iOS, hardened outbox writes with
    `fsync`+`rename(2)`, landed spine `C-04` and `C-05` (`PCM16LeadingSilenceGate.silenceFloor`
    decoupled, Fast QC kept at `v10` per D1), added `.hybrid` telemetry quantization tier across
    Swift/`schema-v2`/`schema-v3`/`benchmark_history`, updated `backend-risk-spine.json` (20
    implemented: `G-06`, `G-07`, `B-05`, `C-04`, `E-03`), and hardened `HuggingFaceDownloader`,
    `SharedModelComponentStore`, and iOS versioned staging (`E-03`/`ER-10`).
  - **Verification:** `scripts/macos_test.sh test` PASS (`mac-test-20261123-130512`),
    `scripts/dev.sh ios` PASS, `scripts/build.sh cli` PASS, contracts & lints (`swiftlint`, `ruff`,
    `pyright`) 0 new findings, `scripts/pcm_identity.py compare` **14/14 bit-identical PCM takes**
    vs `pre-pack-b` (`post-pack-b-final-20261123-181128`: host CPU `-3.56%`, `custom/short`
    `-2.74%` RTF / `-9.0 ms` first chunk, `custom/medium` `-2.33%` RTF / `-9.0 ms` first chunk),
    and quiet-Mac retained-memory qualification PASS (`mac-memory-qualification-20261123-180900-4b639d73`:
    `0.0 MB` cross-model retention, Clone cold MLX peak `-16.0 MB` to `3749.3 MB` / `physFoot`
    `-373.7 MB` to `3452.3 MB`, Clone retained MLX peak `-10.5 MB` to `3084.5 MB`, warm RTF
    `0.28` / `0.28` / `0.30`).
- **Next:**
  1. Execute **Phase 3 — Pack C (`RF-70`)**: pre-register fresh-seed `RF-57` screens in
     `config/quality-screens.json`, add `.attnIO` / `.attnIOEdge` recipes and fix
     `scripts/build_hybrid_model.py` `.bias` parity, then run Exp 1 (Korean `D1`), Exp 2 (Bundle A
     `attn-io`, `+24.12 MB`), and Exp 3 (Bundle B `attn-io-edge`, `+99.62 MB`) paired with
     calibrated `RF-72` advisory pairwise audits; close `RF-54` and `RF-57` per D5.
  2. Prepare **Phase 4 (`RF-71` Mac/CLI 3.2.0)** and **Phase 5 (iOS 3.2.0 `v3.2.0-ios.1`, grouped
     iPhone window covering `RF-68`/`RF-15`/`RF-17`, AWS Device Farm `RF-65` Option A, and `RF-16`)**
     — coordinating with the maintainer at all push, tag, HF upload, UI window, and ASC boundaries.

### November 21, late night: `c0750fe7` pushed & native CI green; CI lint/test fix landed; roadmap retargeted to 3.2.0 (`RF-68`..`RF-71`)

Local `main` (`4f273cb4..c0750fe7`) was pushed to `origin/main` at the maintainer's request, both
triggered workflows completed, the small lint/test regressions were fixed locally (`65436f01`), and
the roadmap was updated per the maintainer's 2026-11-21 decision.

- **Push CI & Release Rehearsal on `c0750fe7`:**
  - **All native Xcode jobs PASSED on GA `xcode-27`:** `macOS deterministic tests` (12m09s, incl.
    Main Thread Checker, CLI identity, macOS XCUITest compile), `iOS compile check (device SDK)`
    (11m39s, incl. `VocelloiOS`, policy tests, and all 3 iOS XCUITest bundles), `macOS ThreadSanitizer
    subset` (10m04s), and `Rehearse iOS archive prerequisites` (2m55s).
  - **Fixed locally in `65436f01` (`DW-04`):** cleared 5 unused imports flagged by pinned `ruff 0.17.1`
    (`check_ios_ui_benchmark.py`, `check_ios_ui_perf.py`, `check_macos_ui_perf.py`) and updated
    `test_ios_ui_preflight.py` (signing-identity stub + `ROOT_DIR`/`lane`/`no_publish`) and
    `test_required_step_ledger.py` (`ui-build` in `ui-ios-control-audit` `optionalSteps`), which were
    the sole failures in `Repository contracts`, `Python tests (linux)` (3/2,749), and `Rehearse macOS
    package` (3/3,161). Verified locally with `ruff` (0 findings PASS) and routed `scripts/dev.sh check`
    (108/108 passed).
- **2026-11-21 Roadmap Decision (`config/roadmap.json`, `docs/ROADMAP.md`, `AGENTS.md`, `release-first-execution-2026-09.md`):**
  - **No more 3.1 TestFlight builds** and no iOS 3.1 release (Mac & CLI 3.1.0 shipped Nov 17 under
    `RF-61`; internal 3.1.0 builds 31–33 are historical/superseded).
  - **3.2.0 is the new target for the iOS App Store submission** (`v3.2.0-ios.N` candidates).
  - **Pack B & Pack C pulled ahead of 3.2:**
    - `RF-68`: Engine Pack B (part 1) — sample-preserving MLX/Metal safety, memory (`A-08`, `A-27`) &
      hot-loop performance.
    - `RF-69`: Engine Pack B (part 2) — sample-preserving runtime, Mac/CLI `EngineHostLease`, Fast QC
      & delivery hardening.
    - `RF-70` (blocked by `RF-68`): Engine Pack C — `RF-57`-screened quality upgrades (zero-weight
      Korean `D1`, Bundle A `+24.12 MB`, Bundle B `+99.62 MB`).
    - `RF-71` (blocked by `RF-68`, `RF-69`, `RF-70`): Ship Vocello and the `vocello` CLI 3.2 on the Mac.
  - `RF-12`, `RF-15`, `RF-16`, `RF-17`, `RF-62`, `RF-63` retargeted to `3.2.0` (`RF-12`, `RF-16`,
    `RF-17` blocked by `RF-68`, `RF-69`, `RF-70`); `RF-35`, `RF-41`, `RF-42` moved back to `planned`
    behind `RF-12` (0 staleness warnings; all 3 focus-lock `in-flight` slots free for `RF-68`..`RF-70`).
- **Docs, instructions & `AGENTS.md` reconciled (2026-11-21):** synced `AGENTS.md`, `ARCHITECTURE.md`,
  `native-engineering.md`, `tooling-and-evidence.md`, `development-workflow.md`, `ios-device-testing.md`,
  `telemetry-and-benchmarking.md`, `hybrid-model.md`, `ios-appstore-submission.md`,
  `app-store-listing.md`, and `.agents/plugins/vocello/skills/*` with the 15-target / 8-scheme project
  (`VocelloiOSPolicies`, warnings-as-errors on `VocelloiOSUITests` & `VocelloiOSCandidateUITests`),
  Wave 5 calibrated iOS `ui-perf` enforcement (12 scenarios, 7 enforced), wired-USB `xctrace` Metal/CPU/witness
  profiling, `RB-11` hybrid attribution rendering, and the 3.2.0 iOS submission target.
- **Next (next session):**
  1. Confirm push CI & Release rehearsal green on the pushed 2026-11-21 tip.
  2. Begin **Pack B** (`RF-68` & `RF-69`, sample-preserving, Mac-driven) in parallel or sequence,
     then run **Pack C** (`RF-70`, `RF-57`-screened Korean `D1`, Bundle A, Bundle B) before bumping to
     `3.2.0` for Mac/CLI (`RF-71`) and cutting `v3.2.0-ios.1` (`RF-12`).

### November 21, night: Wave 5 physical-iPhone 3.1.0 calibration & qualification complete (`c0750fe7`, pushed)

Physical-iPhone **Wave 5** completed on the paired iPhone 17 Pro (iOS 27.2.1, Xcode 27.2, wired USB
+ clean checkpoints) and was pushed to `origin/main` at `c0750fe7`.

- **Wave 5 On-Device Evidence & Calibrations:**
  - **`ios benchmark` (3.1 hybrid, 29/29 PASS, 0 refusals):**
    `ios-xcui-benchmark-20261121-180730-f1e8631c` (`5cc8ed43`; 10 Custom + 10 Design + 9 Clone
    with `A_warm_elderly_woman`; 4 named screenshots verified clean).
  - **`ios_device.sh memory` (3.1 hybrid, 9/9 PASS, 0 MB retained growth) + calibration:**
    `ios-memory-qualification-20261121-182637-c2b75046` (`5cc8ed43`) calibrated
    `config/memory-qualification-policy.json` (`retainedMemoryV2.calibration.ios`
    `growthLimitMB = 16.0`, `floorTiers` `floorMS = 500.0`). Warm `physFoot`: Custom `1969 MB`,
    Design `1949 MB`, Clone `2503 MB` (cold peak `3584 MB`, `2560 MB` headroom remaining —
    confirms Pack A `RB-05` `4.5 GiB` Clone gate).
  - **Wired-USB `xctrace` profiling baselines + `axiom_xcprof_analyze` validation:**
    - `metal` (`ios-metal-profile-20261122-004303-62fc2244`, `1a10801d`): `23.3 tok/s` warm,
      `1952 MB physFoot`, 142,990 captured Metal/signpost/Time Profiler rows (fixed
      `benchmarks/schema-v3.json` `profileKind` enum + `scripts/benchmark_history.py` embedded
      `time-profile` acceptance + unit test).
    - `cpu --keep-trace` (`ios-cpu-profile-20261122-010506-af2fc0e1`, `9fcfb630`): `24.4 tok/s`
      warm (`1.95×RT`), `1987 MB physFoot`, validated end-to-end with `axiom_xcprof_analyze` +
      preserved iOS dSYM (`17,997` symbolicated CPU samples; noted non-shipped
      `IOSPullableDiagnosticsMirror.syncGenerationTelemetry` at ~75% of diagnostics-runner CPU).
    - `witness` (`ios-witness-profile-20261122-010852-a0085eed`, `43371913`): `25.7 tok/s` warm
      (`2.06×RT`), `377 ms` first chunk, `1975 MB physFoot`.
    - `memory` (`ios-memory-profile-20261122-010716-e232a884` & `011044-6468584f`): captured
      Allocations + VM Tracker `.trace` cleanly over USB; publication tripped the newly tightened
      uninstrumented `500 ms` `floorTiers` unobserved-gap bound (`669.4 ms` / `789.9 ms` under
      malloc-stack instrumentation during cold load; traces retained, policy kept strict).
  - **3× counted snapshot-free `ios perf` + `AV-14` closed (`bc350530`):**
    `ios-xcui-perf-20261121-200255-00f49267`, `ios-xcui-perf-20261122-012923-b890c982`, and
    `ios-xcui-perf-20261122-014227-2dc60e89` all passed 12/12 with 100% probe coverage; derived
    `spread-v1` ceilings and enabled confirmatory enforcement in `config/ui-perf-thresholds-ios.json`,
    closing `AV-14` (`18/18` `test_check_ios_ui_perf.py` PASS).
  - **Pack A model delivery & RF-59 upgrade proofs live on device:**
    - `ios model-download --scenario queue` (`ios-xcui-model-download-20261121-201559-ff88637e`):
      **PASS (108.8s)** — `RB-06`, `RB-08`, `RB-10`, `RB-12` (prepare cancel + `Queued` relaunch
      restoration; screenshots reviewed clean).
    - `ios model-download --scenario upgrade` (`ios-xcui-model-download-20261122-012545-cdcd6211`):
      **PASS (91.5s)** — normal Update prompt + `Later` relaunch persistence + low-space Make Room
      prompt + active transfer (`10.9 MB/s`) + clean cancel (fixed `rootTab_studio` relaunch wait
      at `8eb44950`; screenshots reviewed clean).
  - **Full `ios smoke` (`ios-xcui-smoke-20261122-030658-6da29045`): 4/4 PASS (15 min):**
    `testPhysicalDeviceSmokeJourney` (518.8s, including critical memory-pressure recovery and
    visually verified `RB-11` hybrid `Additional base` / `Built from` attribution in
    `010-ios-settings-model-attribution-pro_custom-speed.png`), `testRecordThenPlayReviewsTheClip`
    (34.0s), `testStudioModesKeepTheirDockLayout` (46.3s), `testZLongFormProjectJourney` (290.7s,
    2:17 project complete).
  - **Headless `lang-bench --subset full` (`ios-lang-bench-20261122-011722-250a84c4`):**
    **23/23 `spoken_content=PASS`**, `hint_gate=PASS`, `diagnostics_fail=0` across all 10
    languages on both `qwen3-asr` and `whisper` (nearly all `0.000` WER/CER); on-device Apple
    Speech `output_gate` passed all 12 installed locales (`en-CA`, `fr-CA`, `de-DE`, `zh-CN`) and
    flagged only the 6 locales without iOS dictation packs installed (`es`, `ja`, `ru`, `pt`, `it`,
    `ko`).
  - **`ios localization` (`ios-xcui-localization-20261122-021927-fcb2d313`) + harness fixes:**
    Passed all 10 languages, Default, French-Default, AX-L (incl. Voice Models), and AX-XXXL
    Audio/About; fixed the final AX-XXXL `VocelloUISettingsReveal` short-drag stall and cached
    per-step staticText frames (`31a71e40`, `12a76ed3`, `2ecf5ceb`, `9b68d928`). An optional full
    `ios localization` re-run can confirm AX-XXXL Voice Models green in the next window.
- **Outcome:** Pushed at `c0750fe7` (see entry above); superseded for TestFlight by the 2026-11-21
  decision targeting `3.2.0`.

### November 21: iOS dev/test/bench overhaul (Waves 1–4) & Pack A release blockers (`RB-01`..`RB-12`) landed locally

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
