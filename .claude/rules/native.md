---
paths:
  - "Sources/**"
  - "Packages/**"
  - "Tests/**"
  - "project.yml"
  - "config/runtime-debug-knobs.json"
  - "config/concurrency-safety.json"
  - "config/runtime-refactor-contract.json"
  - "config/model-artifact-receipts.json"
  - "config/macos-entitlement-policy.json"
---
# Native rule — engine, macOS app, iOS app

References, read only what the change needs: `docs/reference/mlx-guide.md`,
`docs/reference/macos-app-guide.md`, `docs/reference/ios-app-guide.md`,
`docs/reference/localization.md`, `docs/reference/delivery-harness.md`, `docs/ARCHITECTURE.md`.
Verification: `scripts/dev.sh test` (macOS unit and owned-runtime tests), `scripts/dev.sh ios`
(generic device-SDK compile). `dev.sh check` compiles the XCUITest bundles for you
(`scripts/build_ui_test_bundles.sh`, build only) whenever the dirty tree touches `Tests/*UITests`,
`Tests/UIAutomationSupport` or `project.yml`; push CI compiles both bundles in the `macos-tests` and
`ios-compile` jobs (`--gate`) but never executes them; a change only under `Tests/Vocello*UITests`
skips the deterministic suites and TSan. Physical-device and macOS XCUITest lanes only when explicitly
requested.

## Engine and runtime (owned package `Packages/VocelloQwen3Core`, `Sources/QwenVoiceCore`)

- **MLX is the only backend.** No Core ML or other runtime. `mlx-swift` and `mlx-swift-lm` move
  together, only with maintainer authorization and a benchmark-gated review; review the
  `swift-transformers` pin in the same change.
- **Owned-package boundary.** Product code imports the `VocelloQwen3Core` facade, never MLXAudio
  implementation modules. MLX arrays stay inside their owning isolation domain; evaluate lazily built
  results before they cross an allowed boundary.
- **Prewarm reentrancy gate.** `acquirePrewarmSlot()` / `releasePrewarmSlot()` stay paired; never pair a
  throwing `try? await acquirePrewarmSlot()` with an unconditional `defer { releasePrewarmSlot() }`.
- **Lossless core audio; non-dropping frontend events.** Final PCM crosses the actor-owned,
  single-consumer suspending channel; frontend preview uses a separate bounded suspending router. No
  eviction policy for audio-bearing events. Cancelling a producer suspended on the channel wakes the
  pending send rather than publishing or stranding it.
- **Cancellation ownership.** `MLXTTSEngine` conforms to `ActiveGenerationCancellable` on every
  platform. `ActiveGenerationCoordinator` owns one active generation, records the typed reason (`user`,
  `memoryPressure`, `superseded`, `shutdown`) and awaits task termination before trim, unload or release.
  Typed cancellation emits `.cancelled`, never `.failed`, and cannot publish a late result; a completed
  output keeps its History ownership without stale player takeover.
- **Per-tier memory.** `NativeMemoryPolicyResolver` sets policy per device class; no hard
  `Memory.memoryLimit` in production and no Quality→Speed OOM fallback. Clear cadence and KV window
  travel in immutable `VocelloQwen3MemoryConfiguration` / `Qwen3RequestMemoryPolicy` values.
- **Sampling is request-local.** Every request gets an effective seed and a fresh
  `MLXRandom.RandomState`; never reintroduce `MLXRandom.seed` or a process-global override.
- **Actor-owned surfaces.** Prepared-model loading, metadata, priming and clone-artifact persistence are
  actor-owned public surfaces; the legacy compatibility SPI is retired. Reserved / generating / aborting
  ownership is explicit: open fails once abort owns the reservation, duplicate aborts join one
  finalization, cache-trim and full-unload relief carry the generation lease. Clone prompt tensors stay
  actor-owned behind epoch-bound handles and are invalidated on reload, critical trim or full unload.
- **Decoder drift.** `Qwen3TTSSpeechTokenizer` uses input-side overlap-and-discard; do not change the
  output side.
- **Convergence authority.** `config/runtime-refactor-contract.json` `phaseStatus` is the only per-phase
  status; do not restate it in prose.
- **Diagnostics fail closed.** Every production-affecting environment key is registered in
  `config/runtime-debug-knobs.json` and needs the internal-diagnostics build plus `QWENVOICE_DEBUG`.
  Every `@unchecked Sendable` and `nonisolated(unsafe)` is justified in
  `config/concurrency-safety.json`; `scripts/runtime_security_contract.py` checks both.
- **Catalog activation fails closed.** The generated schema-v2 catalog is complete for all six
  Speed/Quality artifacts; hosts use exact delivery plans; shared components are reused only after exact
  store verification and installed as hard links, never symlinks. No live repository enumeration,
  inferred digests or partial catalogs. Model eligibility changes update `scripts/check_ios_catalog.sh`.
- **RTF is the standard real-time factor.** `derivedMetrics.realTimeFactor` = request wall seconds
  (prepare entry to the final WAV write, minus model load and prewarm, on the monotonic stage recorder)
  ÷ audio seconds, lower is faster; `audioSecondsPerWallSecond` is the decode-loop speedup and is never
  called RTF. Wall time for any throughput figure comes from `ContinuousClock`, never `Date()`.
- **Telemetry semantics are typed.** Since telemetry schema v8 (records stay v8; the streaming v9
  projection is a digest-bound sidecar), frontend latency stops at playback scheduling; process
  memory belongs to the process that measured it; a macOS UI benchmark is authoritative only when the app
  and engine layers are complete (the merged record names its required layers).

## macOS app (`Sources/QwenVoiceApp.swift`, `Sources/Views`, `ViewModels`, `Services`)

- **The engine runs in-process on the shared store.** `MacEngineBootstrap` builds `MLXTTSEngine` through
  `NativeRuntimeFactory` (bundled contract → macOS-expanded registry, floor-tier prewarm policy) and wraps
  it in the iOS `TTSEngineStore` (compiled by path from `Sources/iOS`, behavior frozen except the shared consent admission and the PA-31 snapshot bridge). No XPC service,
  no service retirement, no wire protocol; a separate engine process must not be reintroduced. Views inject the store as `@EnvironmentObject`; the root shell subscribes to
  `snapshotChanges` with `onReceive` and never reads the store in `body` (W1-D/W2-A).
- **Memory relief is in-process.** The engine's own kernel-pressure responder trims caches and never
  unloads the weights; the store's `MacMemoryBudgetPolicy` gates admission on footprint and Metal working
  set and fully unloads at its critical band; idle unload follows
  `NativeMemoryPolicyResolver`; `MacWarmupAdmissionPolicy` defers proactive warms. Every tier, the
  high-memory Mac included, idle-unloads and answers pressure; warms follow Studio intent, never
  browsing, and a cancelled warm or prime re-arms idle unload (AUD-10). No hard
  `Memory.memoryLimit` on macOS.
- **Liquid Glass is gated.** Every glass surface renders through `GatedGlass` (`Views/Theme/MacGlass.swift`;
  `macGatedGlass` / `macSubtleGlassSurface` wrap the shared `VocelloGlassSurface` body): the
  `generationPerformanceGate` value, Reduce Transparency and the solid fallback live in one place.
- **Accessibility.** Reduce Motion and Reduce Transparency route through `appAnimation` /
  `AppLaunchConfiguration.performAnimated`; no color-only signal; `accessibilityIdentifier`s such as
  `voicesRow_*`, `textInput_*`, `studioChip_*` survive refactors; test-only code lives in the UI test
  target.
- **iOS is the UI reference.** The September 18 approved reset is
  `docs/reference/macos-ios-ui-reset-2026-09.md`. Four sidebar destinations adapt the phone's tabs;
  Studio modes use the shared capsule selector. `VocelloStudioLayout` owns composer/setup/dock
  ordering on both platforms. Preserve the flexible borderless script and shared tinted pills;
  platform wrappers own editors, safe areas, keyboard commands and file actions. Do not reimpose
  superseded Mac pixel prescriptions. First prove Built-in Voice, then convert other screens after
  maintainer review. All three Studio modes use the inline player; the sidebar carries playback on other
  destinations, with a detail-footer fallback when the sidebar is hidden. Never operate unrelated audio from a stale result card. Keep iOS behavior and
  identifiers stable, and update actual Mac test navigation when controls move.
- **Studio generation runs on the shared pipeline.** `StudioGenerationCoordinator` (owned by `MacAppModel`)
  holds the attempt-scoped terminal state, `IOSSingleTakeGenerationExecutor` runs the take through
  `MacStudioSingleTakeGenerationHooks` (timeline, playback handoff, History, telemetry merge) and
  `MacStudioGenerationActions` starts each take from the view's immutable plan and cancels through the
  engine barrier (both on `MacStudioSingleTakeRunner`); no view starts or holds a generation task.
  Line batch loops the same executor through `MacLineBatchRunner`; long-form runs the iOS
  `IOSLongFormCoordinator` with `MacStudioLongFormPlatformHooks`; both are owned by `MacAppModel` and
  the batch sheet (`MacBatchGenerationSheet`) only projects their state.
- **Requests are built by `MacStudioGenerationRequestFactory`** so language, identity, seed, variation
  and prompt are testable before the engine call. Reference language is conditioning metadata only:
  Clone Auto follows the target script, an explicit Studio language wins.
- **Saved-voice review is shared and typed** (`ReferenceTranscriptionReviewState`); Save stays blocked
  while recognition is unresolved; user edits win; persisted metadata comes only from
  `VoiceClipTranscriber.preparedVoiceEnrollmentMetadata(...)`.
- **Entitlements.** App sandbox stays off for MLX; the app is the only entitled Mach-O;
  `config/macos-entitlement-policy.json` changes need a security review.
- **Memory evidence pairs samples by uptime**; independent per-process maxima are not a system peak.

## iOS app (`Sources/iOS`, `Sources/iOSSupport`, `Tests/VocelloiOSLogicTests`)

- **On-device only.** The engine runs in-process on Metal; XCUITest drives the paired iPhone; the
  generic device-SDK compile is the only phone-free lane and `scripts/lib/ios_platform_preflight.py check`
  verifies the toolchain without a Simulator. The duplicate policy-test bundle is compile-only.
- **Typed cancellation barrier and attempt-scoped Studio terminal state.** Every start returns one
  attempt token; stale callbacks, overlapping starts and duplicate cancellations are rejected; a
  cancelled take never lands in History.
- **One short-form executor** (`IOSSingleTakeGenerationExecutor`) owns timeline, engine, cleanup,
  playback, persistence and export; long-form projects run sequential streaming takes through
  `IOSLongFormProjectRunner`, whose platform side effects (variation, waveform seed, diagnostics
  mirror, export, haptics, presentation copy) go through `IOSLongFormPlatformHooks`
  (`IOSStudioLongFormPlatformHooks` on iOS; macOS compiles the file by path with its own adapter).
  No line batch on iOS.
- **Resources are `sources:` entries with `buildPhase: resources`** in `project.yml` (XcodeGen 2.45+
  otherwise drops iOS resources); never a `resources:` key.
- **UI conventions.** `IOSScrollView` for vertical scroll surfaces; mode color pairs with icon, label or
  position; all glass routes through `IOSGatedGlassModifier`; Reduce Motion / Reduce Transparency honored;
  identifiers stable and governed with `config/ios-control-audit.json`; no hidden test UI.
- **Hardware and memory.** `IOSDeviceSupport.isSupportedHardware` (iPhone 15 Pro and later) aligns with
  `scripts/ios_device_eligibility.py`; the `increased-memory-limit` entitlement stays; clone load profile
  follows the entitled limit. Publishable device evidence is memory-qualified (telemetry schema v8 or
  newer, ≥95%
  coverage, no critical pressure, warning, `hardTrim` or `fullUnload`).
- **Localization grows through typed catalog entries.** Dynamic copy belongs in `VocelloPresentationText`
  and `Localizable.xcstrings` with plural rules; formatted copy goes through `VocelloLocalization.format`
  or `IOSAppLanguage.format` so plural rules follow the interface language;
  `scripts/localization_contract.py` rejects new direct literals. Never mutate `AppleLanguages`.
- **Monetization.** Export eligibility uses output provenance, one StoreKit owner
  (`IOSStoreKitClient`), one export boundary (`IOSExportGate`); generation, listening and internal
  History stay free in every mode.
- **Device campaigns are source-bound.** Pause only between completed scenarios; never merge a prior
  failure with a later pass or resume across a source, build, device or plan identity change.

## Build hygiene

- **Warnings are errors** for every owned target (`SWIFT_TREAT_WARNINGS_AS_ERRORS` in `project.yml`); the
  owned MLX package keeps its own settings. Fix the warning, do not silence it with a pragma.
- **Flaky tests are quarantined, not deleted or retried.** List the test in `config/test-quarantine.json`
  and call `try TestQuarantine.skipIfListed(self)`; push CI skips it, nightly still runs it, and the entry
  expires after 30 days.
- `scripts/dev.sh lint` runs the advisory SwiftLint rules in `.swiftlint.yml` on changed files and
  reports a missing or unpinned SwiftLint (`./scripts/install_pinned_tools.sh swiftlint`); formatting
  stays Xcode's.

## Common mistakes

- Editing `project.pbxproj`; adding a generic `#if DEBUG` fork; touching the Simulator.
- Blocking the main thread during model load; observing the whole engine store in the root shell's body.
- Using the saved-reference language as Clone output language; assembling requests in a view.
- Treating `.cancelled` as failure or releasing ownership before the terminal barrier.
- Using raw `ScrollView` on iOS; making color the only indicator; reintroducing a separate engine process.
- Adding, moving or deleting a file under a globbed `Sources/`, `Tests/` or resource path without
  `./scripts/regenerate_project.sh --fast` and the regenerated `project.pbxproj` in the same commit. The
  reminder hook and `dev.sh check` react only to `project.yml`, and CI regenerates before building, so
  CI can pass while local builds fail with "Build input file cannot be found".
- Relying on a class-level `@MainActor` to isolate XCTest `setUp`/`tearDown`; the pinned CI Xcode does
  not, so hop with `await MainActor.run`. CI compile failures are in the run's
  `macos-deterministic-test-artifacts` artifact, not the job log.
- Trusting the local Xcode 27 compile for what CI's pinned Xcode 26.6 accepts: 26.6 flags a
  `withUnsafeContinuation` over `Never` as "will never be executed" (loop on `Task.sleep` instead), and
  its region-isolation checker rejects a throwing `Task { … }` returning a value (return
  `(any Error)?` from a non-throwing task, as the runtime tests do).
- AppKit/SwiftUI traps: an `NSScrollView` representable without `sizeThatFits` (it must answer an
  infinite proposal); two same-named files in one target (they collide on `.stringsdata`, which is why
  the macOS `AppPaths.swift`/`AppDefaults` cannot join `VocelloCoreTests`, which compiles the iOS copy);
  capturing a non-Sendable closure across a `Task { @MainActor }` hop (precompute it first); forgetting
  that a parent's `accessibilityIdentifier` reaches every descendant outside an
  `.accessibilityElement(children: .contain)` container.
- In UI tests: probing an optional element with `VocelloUIWait` (it records `XCTFail` on timeout; use
  `XCTWaiter.wait(for: [XCTNSPredicateExpectation])`); matching visible labels instead of identifiers
  (find Saved Voices rows by `identifier BEGINSWITH "voicesRow_"`); killing a UI lane mid-build.
- Testing pure order or state logic owned by an app-only `@MainActor` iOS type in place: extract it
  into a value type under `Sources/iOSSupport/Services`, list the file under both `VocelloCoreTests`
  and `VocelloiOSLogicTests` in `project.yml`, and add it to the matching `promotionRouting` class in
  `config/quality-promotion-contract.json`. The orchestrators themselves are the exception: the engine
  store, the Studio coordinator, the History `DatabaseService`, the export gate's decision logic and the
  iPhone model inventory are compiled by path into `VocelloCoreTests` only and driven there over fakes;
  extend those suites instead of extracting their state again.
