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
Verification: `scripts/dev.sh test` (macOS unit, XPC and owned-runtime tests), `scripts/dev.sh ios`
(generic device-SDK compile). Physical-device and macOS XCUITest lanes only when explicitly requested.

## Engine and runtime (owned package `Packages/VocelloQwen3Core`, `Sources/QwenVoiceCore`)

- **MLX is the only backend.** No Core ML or other runtime. `mlx-swift` and `mlx-swift-lm` move
  together, only with maintainer authorization and a benchmark-gated review; review the
  `swift-transformers` pin in the same change.
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
- **Telemetry semantics are typed.** Schema-v8 frontend latency stops at playback scheduling; process
  memory belongs to the process that measured it; a macOS UI benchmark is authoritative only when app,
  XPC and engine layers are complete.

## macOS app and XPC (`Sources/App`, `Views`, `ViewModels`, `Services`, `QwenVoiceEngineService`)

- **XPC event forwarding drains off `MainActor`** (`Task.detached(.utility)` in `EngineServiceHost`);
  only `lastPublishedEvent` hops to `MainActor`. Reserve, bind accepted state, then open generation; a
  rejected concurrent request creates no state and does not perturb the accepted one.
- **Service retirement is expected.** `shutdownWhenIdle` retirement is `expectedRetirement`: no error UI,
  no auto-reconnect, lazy relaunch. `isStillTerminatingSession` treats `activeSession == nil` as still
  terminating.
- **Single envelope method.** The wire protocol is one `perform(_:withReply:)` carrying an
  `EngineCommand`.
- **Liquid Glass is gated.** Every glass surface renders through `GatedGlass` (`AppTheme.swift`): the
  `generationPerformanceGate` value, Reduce Transparency and the solid fallback live in one place.
- **Accessibility.** Reduce Motion and Reduce Transparency route through `appAnimation` /
  `AppLaunchConfiguration.performAnimated`; no color-only signal; `accessibilityIdentifier`s such as
  `voicesRow_*`, `textInput_*`, `studioChip_*` survive refactors; test-only code lives in the UI test
  target.
- **Requests are built by `MacStudioGenerationRequestFactory`** so language, identity, seed, variation
  and prompt are testable before the XPC boundary. Reference language is conditioning metadata only:
  Clone Auto follows the target script, an explicit Studio language wins.
- **Saved-voice review is shared and typed** (`ReferenceTranscriptionReviewState`); Save stays blocked
  while recognition is unresolved; user edits win; persisted metadata comes only from
  `VoiceClipTranscriber.preparedVoiceEnrollmentMetadata(...)`.
- **Entitlements are role-scoped.** App sandbox stays off for MLX; the engine XPC uses the narrower
  `QwenVoiceEmbeddedRuntime.entitlements`; `config/macos-entitlement-policy.json` changes need a security
  review.
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
  `IOSLongFormProjectRunner`. No line batch on iOS.
- **Resources are `sources:` entries with `buildPhase: resources`** in `project.yml` (XcodeGen 2.45+
  otherwise drops iOS resources); never a `resources:` key.
- **UI conventions.** `IOSScrollView` for vertical scroll surfaces; mode color pairs with icon, label or
  position; all glass routes through `IOSGatedGlassModifier`; Reduce Motion / Reduce Transparency honored;
  identifiers stable and governed with `config/ios-control-audit.json`; no hidden test UI.
- **Hardware and memory.** `IOSDeviceSupport.isSupportedHardware` (iPhone 15 Pro and later) aligns with
  `scripts/ios_device_eligibility.py`; the `increased-memory-limit` entitlement stays; clone load profile
  follows the entitled limit. Publishable device evidence is memory-qualified (telemetry v8, ≥95%
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

## Common mistakes

- Editing `project.pbxproj`; adding a generic `#if DEBUG` fork; touching the Simulator.
- Draining XPC events on `MainActor`; showing error UI on normal service retirement; blocking the main
  thread during model load.
- Using the saved-reference language as Clone output language; assembling requests in a view.
- Treating `.cancelled` as failure or releasing ownership before the terminal barrier.
- Using raw `ScrollView` on iOS; making color the only indicator; linking the macOS XPC stack into iOS.
