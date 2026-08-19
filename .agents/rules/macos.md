---
status: active
owner: macos
summary: Domain rule for the macOS app and XPC stack — boundaries, XPC lifecycle invariants, gated Liquid Glass, accessibility rules, and the macOS test lanes.
sourceOfTruth:
  - scripts/macos_test.sh
  - scripts/ui_test.sh
  - scripts/build.sh
---
# macOS domain rule

> Domain rule for the macOS app target `QwenVoice`, the XPC stack
> (`QwenVoiceNative`, `QwenVoiceEngineService`, `QwenVoiceEngineSupport`), and the
> macOS SwiftUI/AppKit layers.

## Boundaries

**Owns:**
- `Sources/QwenVoiceNative/`
- `Sources/QwenVoiceEngineService/`
- `Sources/QwenVoiceEngineSupport/`
- `Sources/Services/` (macOS app-level services)
- `Sources/ViewModels/`, `Sources/Views/`, `Sources/Models/` (macOS SwiftUI)
- `Sources/QwenVoiceApp.swift`, `Sources/ContentView.swift`
- macOS entitlements and `Sources/Info.plist`

**Does NOT own:**
- Engine core / MLX internals (`.agents/rules/backend-mlx.md`)
- iOS app (`.agents/rules/ios.md`)
- Build scripts / CI / release (`.agents/rules/release-qa.md`)

**Consults:**
- `docs/ARCHITECTURE.md` §3 (runtime architecture), §5 (macOS request lifecycle), §8 (macOS app surfaces)
- `docs/reference/{macos-app-guide,macos-testing,macos-release-qa,macos-permissions,privacy-storage}.md`
- Root `AGENTS.md` (Hard rules) + [`docs/project-map.html`](../../docs/project-map.html)

## Required pre-read

Before changing macOS app or XPC code, read:
1. `docs/reference/macos-app-guide.md` — app map + test driving.
2. `docs/reference/macos-testing.md` — macOS lanes and the XPC dimension.
3. `docs/ARCHITECTURE.md` §5 — macOS request lifecycle and XPC wire protocol.
4. `docs/reference/privacy-storage.md` if the change touches on-disk data locations.

## Tools and skills

- **Shell tool / scripts** (the source of truth for the local loop):
  - `./scripts/build.sh build|run|cli`
  - `scripts/macos_test.sh test|gate|crashes|debug|logs`
  - `scripts/macos_test.sh profile [--kind cpu|memory] [--keep-trace] [spec]`
  - `scripts/macos_test.sh memory [--label ID]` (fixed retained-memory qualification)
  - `scripts/macos_test.sh models check|ensure|install`
  - `scripts/ui_test.sh macos smoke|benchmark|perf` — the perf lane's warn-only frame-health
    ceilings live in [`config/ui-perf-thresholds.json`](../../config/ui-perf-thresholds.json)
    (baseline-v2-derived; breaches mark `passedWithWarnings`, never fail the lane), and on the
    canonical hardware profile a PASS publishes a `ui-perf` registry record
  - `./scripts/regenerate_project.sh` after `project.yml` changes
- When an XcodeBuildMCP server is installed and callable, use the one shared route for optional
  macOS project discovery, build, run, and debug: call `session_show_defaults`, select the `macos`
  profile, and return to repository scripts for final verification. Unavailability is not permission
  to configure a second XcodeBuildMCP server.
- Optional SwiftUI/AppKit or performance skills may assist after their instructions are read;
  shell scripts remain the source of truth for gates. Triage UI-lane failures and flake patterns
  with `axiom-testing`, symbolicate crashes with `xcsym` through `axiom-tools`, and drive fast
  inner-loop builds/test runs
  through the shared XcodeBuildMCP route (`macos` profile, `test_macos` on the `VocelloMacUI`
  scheme, LLDB tools for hangs) — its UI-automation tools stay banned for Vocello, and
  `scripts/ui_test.sh` remains the sole acceptance lane. Computer use stays assistive:
  exploratory QA and failure diagnosis per
  [`docs/reference/interactive-ui-qa.md`](../../docs/reference/interactive-ui-qa.md).
- Generated output must use `config/build-output-policy.json`. Do not add a macOS DerivedData,
  package, evidence, symbol, or distribution root outside the manifest; route policy changes
  through `.agents/rules/release-qa.md`.
- Use authoritative Apple documentation (docs MCP when callable) where current framework behavior
  matters, and a GitHub integration or `gh` for repository/CI context.
- XCUITest is the sole autonomous macOS app UI driver. Run the smoke and benchmark lanes
  only for explicitly requested frontend acceptance. Missing UI evidence never blocks committing,
  pushing, opening a pull request, merging, ordinary CI, or release packaging. The computer-use MCP
  is dev-environment-assistive only (Xcode GUI, Instruments, system dialogs) and never drives
  Vocello's UI.
- macOS owns app/XPC capture, uptime alignment, transport, and platform-pressure evidence. Typed
  field semantics remain backend-owned and schema/publication changes require release/QA review.

## Build / test commands

```sh
# Fast local loop
./scripts/build.sh build
./scripts/build.sh run

# Deterministic macOS tests do not require a model-readiness bootstrap.
scripts/macos_test.sh test

# Explicit macOS fixture repair/bootstrap only after visible Settings readiness fails.
# This symlinks QwenVoice-Debug/models → the canonical store; restart the UI lane afterward.
scripts/macos_test.sh models ensure

# Explicit frontend acceptance only:
scripts/ui_test.sh macos smoke
scripts/ui_test.sh macos benchmark
scripts/macos_test.sh gate            # deterministic macOS platform gate

# XPC lifecycle / crash isolation is included in the deterministic test and gate lanes.
```

## Invariants (do not regress)

- **XPC event forwarding drains `engine.events` off `MainActor`.** In `EngineServiceHost`,
  drain on `Task.detached(.utility)`; only `lastPublishedEvent` hops to `MainActor`.
- **Service retirement is expected.** When `shutdownWhenIdle` retires the service, the client
  marks it `expectedRetirement` — no error UI, no auto-reconnect. It lazily relaunches on next use.
- **Terminating sessions remain terminating.** `EngineServiceHost.isStillTerminatingSession`
  must treat `activeSession == nil` as still terminating so teardown cleanup cannot be skipped
  after the active session clears.
- **Single envelope method.** The XPC wire protocol is one `perform(_:withReply:)` carrying an
  `EngineCommand`. Do not add ad-hoc XPC methods.
- **Reserve before generation side effects.** `EngineServiceHost` must reserve, bind accepted
  state, and only then open generation. A rejected concurrent request must not create timing,
  forwarding, task, or stream state or perturb the accepted request.
- **Liquid Glass is gated.** `QW_UI_LIQUID` compilation condition controls Liquid Glass surfaces,
  and the `generationPerformanceGate` environment value (injected in `ContentView` from the
  flip-scoped `GenerationPerformanceGateModel`, which republishes only changes to
  `hasActiveGeneration || hasSustainedPerformanceActivity` so engine ticks cannot re-diff the
  root shell) renders glass surfaces with the shipped solid-fill fallback while a generation is
  active — Liquid Glass compositor work measurably competed with the engine (benchmarks/OPTIMIZATION.md
  §K). Every glass surface renders through the shared `GatedGlass` container in `AppTheme.swift`
  (gate + Reduce Transparency + solid fallback in one place); do not hand-roll the condition,
  remove the gate from a glass style, or add a glass surface that bypasses the container.
- **Reduce Motion / Reduce Transparency.** All animation routes through `appAnimation` /
  `AppLaunchConfiguration.performAnimated`; reduced-transparency fallback uses solid fills.
- **No color-only signal.** Mode colors pair with icon, label, or position cue.
- **`accessibilityIdentifier`s are stable.** Values like `voicesRow_*`, `textInput_*`,
  `studioChip_*` must survive refactors.
- **No hidden test UI.** XCUITest observes genuine visible controls. Put test-only code in the UI
  test target; do not add invisible state markers, seeded app state, or generic `#if DEBUG` app
  behavior. Registered debug knobs (e.g. the virtual microphone) substitute inputs, never UI.
- **Mac cancellation UI coverage exists.** The smoke suite's cancellation journey clicks the
  visible mid-generation Cancel and asserts a clean reset: Generate re-enabled, no backend
  error/crash badge, and zero History rows for the cancelled take. Do not regress the engine
  semantics it protects (user cancel is `.cancelled`, never an error, never persisted).
- **App sandbox disabled.** `Sources/QwenVoice.entitlements` keeps sandbox off for MLX; do not
  re-enable it.
- **Do not sum unrelated memory peaks.** New memory-qualified macOS benchmark evidence pairs app
  and engine samples by absolute uptime within one 500 ms cadence. Independent per-process maxima
  are useful layer diagnostics but are not a valid total system peak.

## Common mistakes

- Editing `QwenVoice.xcodeproj/project.pbxproj` directly. Always edit `project.yml` and run
  `./scripts/regenerate_project.sh`.
- Performing XPC event draining on `MainActor`.
- Showing error UI when the XPC service retires normally.
- Blocking the main thread during model load or generation.
- Adding a generic `#if DEBUG` behavior fork instead of runtime `DebugMode.isEnabled` or a narrowly
  named test-target condition.
