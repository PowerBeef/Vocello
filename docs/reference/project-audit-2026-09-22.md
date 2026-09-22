---
status: active
owner: backend-and-platform
reviewed: 2026-09-22
summary: Whole-project audit at the Claude Code takeover — product, harness and governance map, verified defects (fixed or recorded as project-audit-2026-09 roadmap items) and corrected documentation drift.
sourceOfTruth:
  - config/roadmap.json
  - project.yml
  - .claude/settings.json
  - scripts/development_workflow.py
  - scripts/ci/classify_changes.py
---
# Project audit at the Claude Code takeover — September 22, 2026

## Scope and source identity

The audit read the tree at `7e26f94b` (`main` = `origin/main`) with one paused working-tree edit
(`Tests/VocelloMacUITests/VocelloMacMarketingCaptureUITests.swift`, a marketing-only focus click that
every checkpoint leaves untouched). It covered the native product (`Sources/`, `Packages/`,
`project.yml`, `Tests/`), the harness (`scripts/`, `config/`, `.github/`), governance and history
(the guides, rules, roadmap and the agent-tooling commits) and the website at the level needed to route
work. It ran no build, device, UI, model or benchmark lane; counts below come from source reads and
greps, and test-method counts are approximate. Each defect was confirmed in source before it was
recorded. Follow-ups live in `config/roadmap.json` plan `project-audit-2026-09`; this document is the
plan's authority, not a second ledger.

A second, independent whole-project review of the same day (172 findings at `7e26f94b`) is kept as
[`docs/audits/2026-09-22-project-audit.md`](../audits/2026-09-22-project-audit.md), with a
verification addendum from `0beb6331` that marks what is fixed, overstated or wrong. Its confirmed
findings are grouped into the same plan as PA-09 to PA-26, and PA-05 widens to the whole release
path. This document remains the plan's authority; the report holds the line-level evidence.

The same change returned development to Claude Code as the sole coding agent (see
[the development workflow](development-workflow.md#claude-code-development-workflow)): `CLAUDE.md`,
path-scoped `.claude/rules/`, user-invoked `.claude/skills/`, read-only subagents and
`.claude/settings.json` hooks and permissions replace `AGENTS.md`, `.agents/` and `.codex/`.

## Product map

**Build graph.** Ten targets and seven shared schemes, one `Release` configuration, warnings as
errors, Swift 6 on every owned target, macOS and iOS 26.0. `QwenVoice` (Vocello.app) compiles
`Sources/**` minus the iOS, core and CLI trees plus about twenty iOS files by path
(`TTSEngineStore`, the ownership/release/attempt authorities, `IOSSingleTakeGenerationExecutor`,
`DatabaseService`, `StudioGenerationCoordinator`, `IOSAppLanguage`…). `QwenVoiceCore` and
`QwenVoiceBackendCore` are static frameworks; `VocelloiOS` (module `QVoiceiOS`) is iPhone-only;
`VocelloCLI` builds `vocello`. Test targets: `VocelloCoreTests` (also compiles the iOS logic tests),
compile-only `VocelloiOSLogicTests`, `VocelloMacUITests`, `VocelloiOSUITests` and the black-box
`VocelloiOSCandidateUITests`; `Qwen3RuntimeTests` is a SwiftPM target inside the owned package.
Pins: mlx-swift 0.31.6, mlx-swift-lm 3.31.4 and swift-transformers 1.3.3 (inside the package),
GRDB 7.10.0, swift-huggingface 0.9.0.

**Engine.** `TTSEngine` (`@MainActor` protocol, with `events(for:)` streaming) →
`MLXTTSEngine` (admission, `ActiveGenerationCoordinator`, memory relief, idle unload) →
`NativeEngineRuntime` actor (load, prewarm behind `acquirePrewarmSlot`/`releasePrewarmSlot`, clone
preparation) → `UnsafeSpeechGenerationModel` → the `VocelloQwen3Engine` facade actor
(`reserveGeneration`/`open`, a lossless single-consumer classified session) → `Qwen3TTSModel`
(talker, compiled code predictor, 12.5 Hz / 16-quantizer / 24 kHz speech tokenizer on Mimi
primitives, speaker encoder, AudioSeal marking). One generation is admitted at a time; typed
cancellation (`user`, `memoryPressure`, `superseded`, `shutdown`) emits `.cancelled`; an allocation
failure gets exactly one clear-unload-retry with the same seed. Sampling is request-local
(0.9 / 50 / 1.0 / 1.05 / 2048 by default; `balanced` and `consistent` tighten temperature and top-p).
Memory tiers come from `NativeMemoryPolicyResolver`; macOS adds `MacMemoryBudgetPolicy` admission.
Long-form planning is `LongFormManifestV4`, executed by `IOSLongFormProjectRunner` on both platforms.

**Delivery.** `qwenvoice_contract.json` defines Built-in (`pro_custom`), Design and Clone models, each
with a 4-bit Speed variant (iOS and macOS) and an 8-bit Quality variant (macOS). The generated
schema-v2 production catalog (`activationState: complete`, artifact version `2026.09.14.1`) pins six
artifacts file-by-file with sizes and SHA-256; hosts are limited to Hugging Face.
`HuggingFaceDownloader` (`URLSession` + CryptoKit) stages, verifies and publishes;
`SharedModelComponentStore` hard-links shared components from a content-addressed blob store. Three
drivers call it: the macOS model manager, the iOS background-session coordinator and `vocello models`.

**Apps and CLI.** macOS: `QwenVoiceApp` → `MacEngineBootstrap` → a `NavigationSplitView` with four
sidebar destinations; `MacAppModel` owns three `StudioGenerationCoordinator`s, the line-batch runner and
the shared long-form coordinator; 457 `vocello.mac.*` keys ship in ten languages. iOS:
`IOSAppDependenciesContainer` on the App Group store, a custom `TabDock` with four tabs, onboarding,
one StoreKit owner (`IOSStoreKitClient`) and one export boundary (`IOSExportGate`) for the
non-consumable Design and Clone export unlock; interface language (`IOSUILanguage`) is separate from
speech language. The CLI bootstraps the same runtime on the same macOS storage root.

**Persistence and telemetry.** GRDB `history.sqlite` (migrations v1–v7, the last indexing
`audioPath`) with a fail-closed outbox and launch recovery. Telemetry is off unless `TelemetryGate`
enables it; records are schema v8 and the streaming v9 projection is a digest-bound sidecar.

**Concurrency.** `config/concurrency-safety.json` registers exactly its budget of 33
`@unchecked Sendable` and 7 `nonisolated(unsafe)` declarations, with no headroom; ten sit in
`Qwen3TTS.swift`. Engine, store, coordinators and view models are `@MainActor`; heavy work is actor-owned.

**Tests.** All XCTest (no Swift Testing): about 616 core methods plus about 96 compiled iOS logic
methods, about 125 `Qwen3RuntimeTests`, about 31 Mac UI and 24 iOS UI methods. The test quarantine is
empty.

## Harness map

- **Local loop.** `scripts/dev.sh` routes through `scripts/development_workflow.py`, which classifies
  changed paths with the same `classify()` CI uses. `check` runs lint, the contract gate
  (`check_project_inputs.sh --local`: about 38 validators, `repo_invariants.sh`, the privacy scan, the
  roadmap validator and selected pytest), then the native lanes the paths touch. The only native
  serialization is the `mkdir` lock on the shared SwiftPM store, held per `xcodebuild`.
- **CI.** `ci.yml` runs on pushes to `main`: `changes`, `contracts`, `python`, `macos-tests`, the
  blocking `macos-tsan` subset, `ios-compile`, `website`, `dependency-submission`, and the
  `CI required` aggregate. Each lane diffs against its own last proven run. `nightly.yml` (cold TSan,
  full pytest, cold compiles), `security.yml`, `release.yml` (signed annotated tag, exact-SHA CI,
  signing, notarization, draft) and `promote-release.yml` (the only public path) complete the set.
- **Consent-bound lanes.** `scripts/ui_test.sh`, `scripts/ios_device.sh` and the model, memory and
  benchmark lanes of `scripts/macos_test.sh` run only on explicit request; the rule lives in
  `CLAUDE.md` and is now also an `ask` permission. CI is forbidden from naming UI bundles.
- **Work authority.** `config/roadmap.json` (open) and `config/roadmap-archive.json` (done) render
  `docs/ROADMAP.md`. At the audit the primary plan `release-first-3-0-2026-09` was 40% complete and
  mostly parked on the phone; UIF-08, DP-28/29, F-16, ISU-4/5, AV-07 and ASR-04 were in flight.

## Defects

### Fixed with the takeover

| # | Defect | Fix |
| --- | --- | --- |
| 1 | The hook adapter accepted only Codex `apply_patch` payloads; wired to Claude it would have blocked every edit. | Claude Edit/Write/MultiEdit/NotebookEdit input; unknown or malformed input fails closed. |
| 2 | `.claude/` and `CLAUDE.md` routed to no lane, and the invariant and build-output reference scans skipped them. | `.claude/` config routes to the Python lane and `test_agent_hooks.py`; both scans cover the Claude files. |
| 3 | `commit_lint.sh` matched only the literal `git commit`; `git -c k=v commit`, `git -C dir commit` and `git --no-pager commit` bypassed it (a stale personal allowlist shows the `-c` form was used). | The lint matches `git`, any global options, then `commit`. |
| 4 | The swift lane's green base advanced on a run whose deterministic tests passed while the blocking TSan job failed, so the next push without Swift changes skipped TSan. | The swift base also requires the TSan companion job. |
| 5 | `dev.sh check --dry-run` could never print `lanes: none` (operator precedence). | Fixed and asserted. |
| 6 | The `macos-ui-lane` skill omitted `marketing`; `device-diagnostics` listed 8 of 26 verbs. | Skills list the lanes and defer to `scripts/ios_device.sh help`. |

### Recorded as follow-ups (`project-audit-2026-09`)

- **PA-01 (P1) Prewarm slot can stay held after cancellation.** In
  `NativeEngineRuntime.acquirePrewarmSlot` the trailing `try Task.checkCancellation()` runs after a
  waiter has been resumed by `releasePrewarmSlot`, which already transferred the slot. The callers
  (`try await acquirePrewarmSlot(); defer { releasePrewarmSlot() }`, or a `catch` that returns) never
  release on that throw, so `prewarmInFlight` stays set and later prewarms wait until cancelled. The
  `catch` branch's `if slotAcquired` release is unreachable. This violates the intent of the native
  rule's "prewarm reentrancy gate".
- **PA-02 (P2) The owned package's diagnostics gate is not fail-closed.**
  `VocelloQwen3ImplementationDebugGate` honors `QWENVOICE_DEBUG` alone for `QVOICE_TALKER_KV_QUANT`,
  `QWENVOICE_SAMPLER_COMPILE` and `QWENVOICE_TOKENIZER_RESIDENCY`, which
  `config/runtime-debug-knobs.json` classifies `unavailable-without-internal-capability`; the
  `VOCELLO_INTERNAL_DIAGNOSTICS` compile condition never reaches the package. A distributed build,
  most easily the CLI, accepts them from the environment.
- **PA-03 (P3) iOS diagnostics runners are reachable by environment alone.**
  `IOSStartupReliabilityRunner` and part of `IOSDeviceDiagnosticsRunner.isRequested` sit outside
  `#if QVOICE_DEVICE_DIAGNOSTICS` and depend only on `TelemetryGate`.
- **PA-04 Harness isolation.** `scripts/build_ui_test_bundles.sh` calls `xcodebuild` directly,
  bypassing the `xcb_run` package-store lock, the shared cloned-packages path and the `QVOICE_*` paths,
  and compiles `VocelloMacUI` into the `-Onone` arena while the UI lanes use `macos-optimized`.
  `scripts/lib/ios_coredevice_probe.py` writes fixed-name temporary files that concurrent probes can
  race, and `MAC_TAKE_MANIFEST` uses a fixed temporary path. The virtual-microphone temporary file in
  `ui_test.sh` is deliberate (documented permission-prompt constraint).
- **PA-05 Release workflow toolchain drift.** `release.yml` hard-codes `Xcode_26.6` three times and
  duplicates the pinned-tool install instead of using `.github/actions/native-toolchain`; the
  TestFlight step's `xcrun altool` upload should be checked against the pinned Xcode.
- **PA-06 Routing cost and derived-artifact gaps.** A change only under `Tests/VocelloMacUITests`
  selects the full macOS test and TSan lanes although neither compiles UI bundles; a clean-tree
  `check` runs every lane; `refresh_derived_artifacts.py validate_all` omits the README-charts check
  its registry lists; SwiftLint is unpinned and silently skipped when missing; `nightly.yml` and the
  `macos-tsan` cache owner still describe TSan as scheduled-only.
- **PA-07 Dead code.** `MLXTTSEngine.generateBatch` (no callers), `HuggingFaceDownloader.downloadRepo`
  (no callers, keeps a live repository-enumeration path), `samplerCompileEnabled` (never read), the
  XPC-era handshake latches (`NativeDeviceClassGate.applyHandshakeForcedClass`, one of the seven
  `nonisolated(unsafe)` declarations, and the related `TelemetryGate` plumbing that only `vocello bench`
  uses), about 36 stale XPC mentions, and the `HuggingFace` product that `project.yml` links but no
  owned source imports.
- **PA-08 Duplication and naming.** macOS and iOS `ModelManagerViewModel`s use different observation
  models; three download drivers; two Mac player cards (`MacInlinePlayerCard`, `MacStudioPlayerCard`);
  root views build their `@Observable` models through `State(initialValue:)` in `init`, re-running
  construction on parent re-init; `Qwen3TTS.generateVoiceDesign` is the core loop for every mode;
  `OWNERSHIP.json` omits the `MLXAudioMark` target; the ⌘6 "Models" menu item opens Settings.

## Documentation drift corrected

`docs/ARCHITECTURE.md` now states the 33-declaration unsafe-concurrency budget, migration v7,
`TTSEngineEventStreaming.events(for:)`, the in-process resolution of `QWENVOICE_FORCE_MEMORY_CLASS`
and telemetry mode (no handshake), `URLSession` downloads, the package's `MLXRandom` use, and the
Combine publishers actually used (there is no `GenerationChunkBroker`). The native and release rules
say telemetry records are v8 with a v9 streaming sidecar. The `MacInterfaceText` header names all ten
languages, and three iOS comments cite the current rule file.

## Limitations

No native build, test, UI, device or model run was part of the audit itself; the takeover's own
verification ran the routed deterministic lanes. Test counts are grep-based. The macOS and iOS
duplication findings (PA-08) are maintainability observations, not measured defects. Fresh-session
activation of the Claude Code configuration (discovery of `CLAUDE.md`, rules, skills, hooks and
permissions in a new session) is for the maintainer to confirm; the migrating session confirmed the
edit and policy guards and the deny rules live.
