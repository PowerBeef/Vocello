---
status: active
owner: ios
reviewed: 2026-09-02
summary: Domain rule for the VocelloiOS target — boundaries, physical-device-only testing, typed cancellation, Dynamic Type/Reduce Motion invariants, stable identifiers, and the frame-health perf lane.
sourceOfTruth:
  - scripts/ios_device.sh
  - scripts/ui_test.sh
  - scripts/ios_control_audit.py
  - scripts/build_foundation_targets.sh
  - scripts/localization_contract.py
  - config/localization-unlocalized-baseline.json
  - Sources/SharedSupport/Services/ReferenceTranscriptionReviewState.swift
  - Sources/SharedSupport/Services/VoiceClipTranscriber.swift
paths:
  - "Sources/iOS/**"
  - "Sources/iOSSupport/**"
  - "Tests/VocelloiOS*/**"
  - "scripts/ios_*"
  - "config/ios-*.json"
  - "Sources/Resources/Localizable.xcstrings"
---
# iOS domain rule

> Domain rule for the `VocelloiOS` target, `Sources/iOS/`, `Sources/iOSSupport/`, and the
> iOS-side pieces of `Sources/SharedSupport`.

## Boundaries

**Owns:**
- `Sources/iOS/` (SwiftUI, sheets, studio canvas, coordinators, app bootstrap)
- `Sources/iOSSupport/`
- `Sources/SharedSupport/` when the change is iOS-specific (e.g. `IOSScrollView`, iOS player VM behavior)
- iOS entitlements, Info.plist, App Store submission materials

**Does NOT own:**
- macOS app / XPC service (`.claude/rules/macos.md`)
- Engine core / MLX internals (`.claude/rules/backend-mlx.md`)
- Build scripts / CI / release (`.claude/rules/release-qa.md`)

**Consults:**
- `docs/ARCHITECTURE.md` §6 (iOS request lifecycle)
- `docs/reference/{ios-app-guide,ios-device-testing,ios-engine-optimization,ios-appstore-submission,ios-increased-memory-entitlement-request}.md`
- Root `CLAUDE.md` (Hard invariants) + [`docs/project-map.html`](../../docs/project-map.html)

## Required pre-read

Before changing iOS UI or behavior, read:
1. `docs/reference/ios-app-guide.md` — app map + how to drive it in tests.
2. `docs/reference/ios-device-testing.md` — deterministic compile and explicit on-device acceptance
   workflows plus burn-in safety.
3. `docs/ARCHITECTURE.md` §6 — iOS request lifecycle, typed cancellation barrier, memory posture
   (batch was removed from iOS 2026-07-02).
4. `docs/reference/ios-engine-optimization.md` if the change affects generation performance or memory.

## Tools and skills

- **Shell scripts** are the only way to build/test/run real-engine iOS work on device:
  - `scripts/ios_device.sh preflight`
  - `scripts/ios_device.sh build|install|launch`
  - `scripts/ios_device.sh bench|lang-bench`
  - `scripts/ios_device.sh speech-assets` (explicit DE/ES/JA/ZH DictationTranscriber install plus legacy Speech recheck)
  - `scripts/ios_device.sh profile [--kind cpu|memory] [--keep-trace] [spec]`
  - `scripts/ios_device.sh memory --voice-id ID [--label ID]` (one-process retained-memory sequence)
  - `scripts/ios_device.sh clone-conditioning [--label ID]` (compile-gated, local-only transcript-backed versus x-vector proof; no history publication)
  - `scripts/ios_device.sh delivery-reliability --plan PLAN.json --script-file SCRIPT.txt` (compile-gated ordered Built-in Voice startup diagnosis; exact script remains untracked)
  - `scripts/ios_device.sh enroll-clone-fixture --wav W.wav --transcript W.txt` (headless benchmark-fixture voice enrollment for wipe recovery; the visible Files-import flow returned 2026-08-15 and has its own opt-in `ui_test.sh ios enroll-clone-fixture` lane)
  - `scripts/ios_device.sh memory-field-report [pulled-diagnostics]` (local-only; never contacts the phone)
  - `scripts/ios_device.sh crashes`
  - `scripts/ios_device.sh gate`
- When an XcodeBuildMCP server is installed and callable, use the one shared route: call
  `session_show_defaults`, select `ios-device`, and set the paired device ID at runtime. Never
  select Simulator support or configure a second XcodeBuildMCP server when the optional route is
  absent. Repository scripts remain authoritative for build, launch, telemetry, profiling, and
  crash proof.
- Generated output must use `config/build-output-policy.json`. Do not add an iOS DerivedData,
  package, evidence, symbol, or archive root outside the manifest; route policy changes through
  `.claude/rules/release-qa.md`.
- Built-in Voice startup plans, retained results, and the tracked control sentence are governed by
  `config/ios-startup-reliability-plan-schema-v1.json`,
  `config/ios-startup-reliability-result-schema-v1.json`,
  `config/ios-startup-reliability-result-schema-v2.json`, and
  `config/ios-startup-reliability-sentinel.json`. Exact reported script bytes remain untracked and
  may enter the app only through the diagnostic command's ephemeral launch input. Schema v2 adds
  gated, generation-scoped rejected audio and codec replay, unload-quiescence samples, and strict
  process-exit/crash evidence while the host continues to validate schema-v1 results.
- Use authoritative Apple documentation (docs MCP when callable) for current framework APIs. Use a
  GitHub integration when callable, otherwise `gh`, for repository context; scripts remain the test
  interface.
- **XCUITest owns iOS UI.** It runs only on the paired physical iPhone. Run smoke and
  benchmark lanes only for explicitly requested frontend acceptance.
  Missing device, UI, or model evidence never blocks a commit, push, pull request, ordinary merge,
  or ordinary CI. Never add a Simulator route, alternate UI driver, or coordinate table. The
  computer-use MCP is dev-environment-assistive only and never drives the app UI.
- iOS owns on-device capture, frontend/engine correlation, transport, memory-warning, MetricKit,
  and platform-pressure evidence. Typed field semantics remain backend-owned and schema/publication
  changes require release/QA review.

## Execution procedure

Additional enforced evidence contracts: `config/ios-control-audit-contract-20260904.json`
is historical v2/v3 plan compatibility, never current-source acceptance;
`config/model-management-diagnostics-schema-v1.json` owns model lifecycle correlation;
`config/voice-identity-language-reliability.json` owns private Clone/French diagnostics;
`config/language-bench-corpus.json`, `config/language-bench-matrix.json`, and
`config/language-bench-diagnostic-cohort.json` freeze language fixtures and cells.

The [development workflow](../../docs/reference/development-workflow.md) owns no-phone checks.
[iOS device testing](../../docs/reference/ios-device-testing.md) owns preflight, candidate
navigation, smoke, control audit, model download, startup/saved-voice, benchmark and performance
procedures. The perf protocol is enforced by `scripts/check_ios_ui_perf.py` and
`config/ui-perf-thresholds-ios.json`; warnings remain warnings, never clean promotion evidence.
Do not reproduce that guide's commands or dated run progress here.

For a multi-run campaign, pass `--retain-result` before each member starts. Follow the single
pause/resume procedure in `docs/reference/ios-device-testing.md`: during a frozen campaign,
retain run IDs, findings, blocked/skipped rows and the validated next command in untracked
checkpoints only. Update the roadmap/narrative at a deliberate source checkpoint, acknowledging
the changed evidence identity. Verify pins with a cleanup dry-run; retire them only after closure.
The runner verdict, not the raw XCTest count, owns lane qualification: post-test diagnostics,
crash-delta collection, artifact validation, and cleanup required by that lane must all finish. If
collection is cancelled after XCTest passes, retain the partial proof but keep the lane failed and
rerun it under a new ID. A generation run that emits no terminal observation has no row-level resume
boundary. History seed carriers must be resolved through exact run/plan-owned content; a numeric
search-token collision with an unrelated History row is a harness-integrity failure, never evidence
about product generation and never permission to delete or mutate that row.

## Invariants (do not regress)

- **All iOS runtime work is on-device only.** The MLX engine runs in-process on Metal. XCUITest
  drives the paired physical iPhone; scripts handle the device and telemetry. The generic
  physical-device SDK compile (app plus standalone policy-test bundle) is the sole no-phone iOS
  development lane. It still requires the selected Xcode's matching iOS Platform Support/runtime
  component; `scripts/lib/ios_platform_preflight.py check` verifies that external toolchain state
  without running a Simulator. The same Foundation-level policy assertions execute
  in ordinary macOS `VocelloCoreTests`; Xcode 26 cannot execute the duplicate app-host-free,
  tool-hosted XCTest bundle on a physical-device destination, so that iOS target is compile-only.
  Runtime proof still uses the existing headless diagnostics and XCUITest lanes.
- **Typed cancellation barrier.** The in-process `MLXTTSEngine` conforms to
  `ActiveGenerationCancellable`. iOS forwards user and memory-pressure reasons, awaits the active
  task's terminal barrier before trim/unload or ownership release, and treats `.cancelled` as a
  distinct terminal event. A cancelled take must never land in History.
- **Attempt-scoped Studio terminal state.** Every Studio start returns one attempt token. Live,
  success, failure, deferred cleanup, and cancellation-barrier callbacks must match the current
  token; stale callbacks, overlapping starts, and duplicate cancellation requests are rejected.
  Never restore unscoped terminal setters or swallow a cancellation-barrier failure.
- **One short-form generation executor.** Built-in, Design, and Clone views retain typed request
  assembly and mode-specific preparation, but common timeline, engine, cancellation cleanup,
  playback, persistence, and export sequencing belongs to `IOSSingleTakeGenerationExecutor`.
  Do not fork that lifecycle back into individual mode views.
- **Enrollment review is one cross-platform policy.** `ReferenceTranscriptionReviewState` owns
  awaiting-audio, automatic, manual, unavailable, and explicit audio-only states for both apps.
  Save is disabled while recognition is unresolved; operation generations reject delayed results,
  and user edits win. Build persisted metadata only through
  `VoiceClipTranscriber.preparedVoiceEnrollmentMetadata(...)`. Reference language describes the
  conditioning clip and must never select Clone output: Auto follows target text and an explicit
  Studio language always wins.
- **Use `IOSScrollView`.** iOS vertical scroll surfaces use `IOSScrollView`, not raw `ScrollView`.
- **Mode color pairs with icon/label/position.** No color-only signal.
- **Honor Reduce Motion / Reduce Transparency.** Animations route through `appAnimation` /
  `AppLaunchConfiguration.performAnimated`; Liquid Glass falls back to solid fills when reduced
  transparency is enabled. The same solid-fill branch backs `iosGenerationPerformanceGate`:
  on fixed-refresh (non-ProMotion) devices every glass surface drops glass while a
  generation is active; the gate stays inert on ProMotion hardware. All iOS glass routes
  through the shared `IOSGatedGlassModifier` (`Sources/iOS/Theme/ThemeModifiers.swift`,
  the macOS `GatedGlass` twin) — never hand-roll the
  reduce-transparency/performance-gate condition at a surface.
- **`increased-memory-limit` entitlement.** Required for model load headroom. Do not remove.
- **Memory-qualified benchmark evidence.** New publishable device generations require telemetry v8
  sample sidecars, lifecycle-boundary coverage, zero capture failures, at least 95% periodic
  coverage, and no critical pressure, app memory warning/exit, `hardTrim`, or `fullUnload`.
  Delayed MetricKit memory/exit aggregates are field diagnostics only: they are not run-correlated
  and their absence is `notYetDelivered`, never a benchmark failure.
- **Supported hardware gate.** `IOSDeviceSupport.isSupportedHardware` enforces iPhone 15 Pro+.
- **No line batch on iOS** (removed 2026-07-02, maintainer decision — dead UI, native engine unsupported, Jetsam risk; macOS batch unaffected). Long-form projects (2026-07-24) are the required sequential-streaming design validated on device: one ordinary streaming take per planned segment through `IOSLongFormProjectRunner`, never a concurrent batch. Do not reintroduce line-separated batch UI or any non-sequential execution.
- **Clone load profile.** Respect `.fullCapabilities` vs `.iOSProductionDefault`
  (`.withoutCloneEncoders`) depending on the entitled memory limit.
- **`accessibilityIdentifier`s are stable.** Values like `voicesRow_*`, `textInput_*`,
  `studioChip_*` must survive refactors. Interactive iOS source files and dynamic control families
  are also governed by `config/ios-control-audit.json`, its strict
  `config/ios-control-audit-schema-v1.json`, and the language-matched
  `config/ios-control-audit-corpus.json`; update source coverage, corpus identity, and the
  XCUITest owner in the same change instead of exempting a new control silently.
- **Localization grows through typed catalog entries.** Dynamic errors/status belong in
  `VocelloPresentationText` and `Sources/Resources/Localizable.xcstrings`, with complete format
  strings, translator context, and plural rules. `scripts/localization_contract.py` rejects new
  direct presentation literals against `config/localization-unlocalized-baseline.json`; do not
  refresh that baseline without reviewing the new copy. Before broad translations, run the macOS
  pseudo-localization smoke and the physical-iPhone `Pseudo-AX-XXXL` Settings walk documented in
  [`docs/reference/localization.md`](../../docs/reference/localization.md).
- **No hidden test UI.** XCUITest observes genuine visible controls. Put test-only code in the UI
  test target; do not add preview routes, invisible state markers, onboarding bypasses, seeded UI
  text, or generic `#if DEBUG` app behavior.
- **Device-campaign checkpoints are source-bound.** Pause only between completed scenarios. Never
  merge a prior failure with a later pass, resume after a source/build/device/plan identity change,
  or represent pruned raw evidence as retained. Record missing evidence as a recapture requirement.
  Passed XCTest cases do not qualify a lane whose required runner-owned evidence collection or
  validation was interrupted. A zero-observation generation shard is preserved as failed evidence
  but cannot supply a resume cursor; after any corrective source change, start again with a new run
  ID and frozen identity.

## Common mistakes

- Running **runtime iOS work** on the Simulator. Real iOS tests and generation/download must run on
  a paired device; the generic physical-device SDK compile lane is the deterministic development
  check and does not require a connected phone.
- Treating `xcodebuild -showsdks` as proof that `generic/platform=iOS` is usable. On current Xcode
  26 toolchains, removing every compatible iOS runtime component can make the generic destination
  ineligible while `iphoneos` still appears. Restore the matching component explicitly; never
  weaken the destination or add a Simulator lane.
- Letting the runtime hardware gate drift from App Store installation eligibility;
  `scripts/ios_device_eligibility.py` owns their fail-closed alignment.
- Bypassing `cancelActiveGeneration(reason:)`, treating `.cancelled` as failure, or releasing
  generation ownership before the active task reaches its terminal barrier.
- Using raw `ScrollView` instead of `IOSScrollView`.
- Making color the only indicator for mode or state.
- Forgetting that the iOS app deliberately does **not** link the macOS XPC stack.
