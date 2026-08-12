---
status: active
owner: ios
summary: The 2026-08 iOS UI review — the planned frame-health lane, measured baseline, ranked audit findings, maintainer pick-list, and fix waves. Roadmap authority for the ios-ui-2026-08 plan.
sourceOfTruth:
  - scripts/ui_test.sh
  - scripts/check_ios_ui_perf.py
  - Sources/iOSSupport/Services/IOSUIPerfFrameProbe.swift
  - Tests/VocelloiOSUITests/VocelloiOSPerfUITests.swift
  - Tests/VocelloiOSUITests/VocelloiOSUITestCase.swift
---
# iOS UI review & refresh — 2026-08

> The durable record of the iOS UI stability/reactiveness arc: the frame-health
> instrument, the measured baseline, the four-lens audit merged into one ranked
> findings list (performance and design together — design items are a maintainer
> pick-list, never pre-committed work), and the measured fix waves. Mirrors the
> completed macOS arc's structure
> ([`macos-ui-refresh-2026-08.md`](macos-ui-refresh-2026-08.md)). Work items:
> plan `ios-ui-2026-08` in [`docs/ROADMAP.md`](../ROADMAP.md), which is the
> status authority; this document interprets and records evidence.

## Why instrument-first is mandatory here

The 2026-06 iOS frontend perf audit shipped four fix waves with no measurement in
front of them — its own Wave 1 commit records the gap ("Frame-time win is real but
not captured by decode telemetry"). The macOS arc proved the ordering that works:
instrument (UI-1), baseline (UI-2), audit-with-numbers (UI-3), then measured waves.
This arc repeats that ordering on the canonical iPhone 17 Pro.

## Measurement basis (IUI-1 authored; device validation and IUI-2 pending)

`scripts/ui_test.sh ios perf` joins nine XCUITest scenarios
(`Tests/VocelloiOSUITests/VocelloiOSPerfUITests.swift`; one fresh app launch and
one marked device-clock window each) to an in-app 500 ms `CADisplayLink` probe
(`Sources/iOSSupport/Services/IOSUIPerfFrameProbe.swift`) pinned to
`preferredFrameRateRange(60, 60, 60)`. The app is 60 Hz-capped; expected frames
come from the link's own observed per-tick target (`targetTimestamp − timestamp`,
never a hard-coded 16.67 ms and never `duration`, which reports the panel's
native period on ProMotion hardware), and `scripts/check_ios_ui_perf.py`
fail-closes when the median block cadence leaves the 55–65 Hz band **on the
quiet `ios-idle-baseline` sentinel** — the one window where cadence isolates
whether the pin was honored (Low Power Mode off and nominal thermals are run
preconditions). On interactive scenarios an out-of-band cadence degrades to a
warn-only `uiperf.cadence:*` code instead: block cadence there conflates
system re-pacing with the main-thread stalls the lane exists to measure
(CADisplayLink coalesces missed callbacks; macOS history-scroll's 456 ms/s
baseline is ~33 Hz effective cadence). The checker also fail-closes on a
missing/duplicate scenario, probe coverage under 90% of a marked window,
non-monotonic blocks, and non-canonical hardware (run-scoped device manifest
+ live `devicectl` inventory). Probe output lives in the
devicectl-pullable `Library/Caches/Vocello/diagnostics/ui-perf/` tree; the
seeded-History knob (`Sources/iOSSupport/Services/IOSUIPerfHistorySeeder.swift`)
mirrors the macOS seeder through the production iOS `Generation` model.
Honesty limits, stated up front: a main-run-loop display link measures
main-thread cadence health, not render-server-only hitches — the same claim
limits as the macOS probe. MetricKit `MXAnimationMetric` /
`MXAppResponsivenessMetric` aggregates now accrue through
`IOSMetricKitMemoryReporter` as advisory field evidence only (24 h delivery,
never run-correlated, never gating).

Scenario set: confirmatory `ios-idle-baseline`, `ios-tab-navigation`,
`ios-history-scroll`, `ios-voices-scroll`, `ios-settings-scroll`,
`ios-composer-typing`, `ios-sheet-present-dismiss`; exploratory
`ios-player-scrub` (element-anchored drags through the custom scrubber re-query
per event), `ios-generation-active` (model-dependent duration).

**IUI-1 device acceptance (2026-08-12, canonical iPhone 17 Pro):** run
`ios-xcui-perf-20260812-145449-41b82c87` passed 9/9 scenarios with the checker
gate green — the idle sentinel measured 60.0 Hz median cadence at 0.006 ms/s
hitch (the pin is honored and the probe is near-silent at rest), every
scenario ≥98% probe coverage, all thermal states nominal. The three scripted
fail-closed refusals were then demonstrated against doctored copies of that
run's real pulled evidence: a stripped marker (`missing scenario markers`),
a truncated probe file (`probe coverage 0% below 90%`), and halved idle
frame counts (`median block cadence 30.0 Hz outside the 55-65 Hz band on the
idle sentinel`). The checker's offline self-tests
(`scripts/tests/test_check_ios_ui_perf.py`) cover the same branches. Two
acceptance attempts preceded the pass: the device-side UI Automation toggle
had dropped (re-enabled by the maintainer), and the seeded-history sentinel
typed into the search field before the software keyboard finished presenting
— keystrokes drop silently there; fixed by waiting for the keyboard, a
digits-only token (live autocorrection is active on the production search
field — an IUI-3 audit candidate), and filter-recovery clear verification
(an empty `TextField` reports its placeholder as `value`).

## Baseline (IUI-2, 2026-08-12 — canonical iPhone 17 Pro)

One sitting: the IUI-1 acceptance run served as the discarded warm-up, then
five counted lane runs back-to-back
(`ios-xcui-perf-20260812-150617-6f2622f1`, `…-151529-762c86ba`,
`…-152444-f555f9ec`, `…-153408-8e55fe32`, `…-154331-9cb3d9f7`), each a full
9/9 PASS with every scenario's thermal states nominal, Low Power Mode off,
and zero warnings. Per-scenario medians (IQR) across the five counted runs:

| Scenario | Designation | Hitch ms/s median (IQR) | Max gap ms median (IQR) | p95 gap ms median | Cadence Hz median | Coverage min |
| --- | --- | --- | --- | --- | --- | --- |
| `ios-idle-baseline` | confirmatory | 0.0 (0.0) | 17 (0) | 21 | 60.0 | 99% |
| `ios-tab-navigation` | confirmatory | 76.5 (1.5) | 112 (1) | 29 | 58.0 | 99% |
| `ios-history-scroll` | confirmatory | 79.5 (8.1) | 83 (9) | 29 | 59.9 | 98% |
| `ios-voices-scroll` | confirmatory | 44.9 (4.8) | 59 (9) | 21 | 60.0 | 97% |
| `ios-settings-scroll` | confirmatory | 58.0 (6.8) | 60 (2) | 21 | 60.0 | 97% |
| `ios-composer-typing` | confirmatory | 27.3 (9.0) | 67 (0) | 21 | 60.0 | 96% |
| `ios-sheet-present-dismiss` | confirmatory | 99.9 (0.4) | 178 (1) | 29 | 58.0 | 99% |
| `ios-player-scrub` | exploratory | 106.5 (3.7) | 82 (9) | 46 | 59.9 | 98% |
| `ios-generation-active` | exploratory | 51.1 (7.5) | 132 (15) | 21 | 60.0 | 96% |

Reading, ahead of the IUI-3 audit: the idle floor is essentially silent
(0.006 ms/s worst run) — every other number is real UI work. The heaviest
confirmatory scenarios are sheet present/dismiss (~100 ms/s with an extremely
stable 178 ms worst gap — a repeatable presentation stall) and history scroll
(~80 ms/s over 400 seeded rows); tab navigation's 76.5 ms/s with ±1.5 IQR is
a highly repeatable re-render cost consistent with the unported macOS
root-shell observation finding. Generation-active shows the engine/UI
contention signature (132 ms worst gaps at only ~51 ms/s average hitch).

Provenance note: result retention (`--prune-ui-results --ui-keep 1`) removed
runs 1–4's host artifact directories as later runs passed — the counted
verdicts, run IDs, and thermal states were captured live by the runner chain,
and the four missing `ui-perf-report.json`s were regenerated afterwards by
re-running `scripts/check_ios_ui_perf.py` (deterministic) over the device's
retained probe JSONL (re-pulled; all 63 files present under the 64-file
retention cap) joined to the captured lane logs' marker lines, bucketed per
run by lane-start epoch. Canonical-hardware verification ran live inside each
counted lane's `perf-validation` step. Protocol correction recorded in
[`ios-device-testing.md`](ios-device-testing.md): copy
`ui-perf-report.json` out of the run directory after every counted run, as
the macOS baseline protocol already instructed.

## Ranked findings and maintainer pick-list (IUI-3, 2026-08-12)

Four lenses (observation architecture, render cost, accessibility, design polish)
ran over `Sources/iOS` + `Sources/iOSSupport` with a per-lens adversarial accuracy
check; 36 raw findings deduplicated to 30 (five cross-lens twins — P1, P3, P4, and
X1 were each found independently by two lenses, which is corroboration, and one
finding was downgraded by its check: the model-installer republish is already
throttled to ~4 Hz upstream, leaving only a granularity cost). Every row below was
verified against the current tree at the cited line. **The maintainer gate sits
here: no fix lands until the pick-list and wave scope get an explicit go.**

Tier A: measured performance. Tier B: input/accessibility defects. Tier C: the
design pick-list. Wave 1 = safe/low-risk fixes with before/after measurement
(IUI-4); wave 2 = refinements/re-engineering (IUI-5); pick = maintainer's call.

| # | Finding | Where | Cat | Sev | Risk | Baseline signal | Wave |
| --- | --- | --- | --- | --- | --- | --- | --- |
| P1 | Player sheet runs synchronous `AVAudioSession` activation + `AVAudioPlayer` decode + word-timing plan on MainActor inside the present transition (and sync deactivation inside dismiss) | `Sheets/IOSPlayerSheet.swift:570` | perf | high | low-risk | sheet-present-dismiss 99.9 ms/s, the metronomic 178 ms gap | 1 |
| P2 | `TTSEngineStore` whole-object observation storms ~7 live views per generation progress event (11 subscription sites; the unported macOS 158 ms/s root-shell finding — no flip-scoped gate model, no `@Observable`) | `TTSEngineStore.swift:35`, `App/RootView.swift:20` | perf | high | refinement | generation-active 51.1 ms/s, 132 ms gaps | 2 |
| P3 | 20–60 Hz `CADisplayLink` invalidates the whole player sheet per tick and rebuilds the karaoke `AttributedString` from scratch (visible output changes at ~2–4 Hz) | `Sheets/IOSPlayerSheet.swift:555,529` | perf | high | refinement | player-scrub 106.5 ms/s | 2 |
| P4 | Tab switch structurally remounts each screen (switch-branch identity), discarding search/filter/scroll `@State` — a UX defect as much as a perf one | `App/RootView.swift:146` | perf | med | re-engineering | tab-navigation 76.5 ms/s, IQR ±1.5 | 2 |
| P5 | History rows build their `Menu` content eagerly and stat the audio file (`FileManager.fileExists`) on the main thread per row during scroll | `History/HistoryScreen.swift:632` | perf | med | low-risk | history-scroll 79.5 ms/s / 83 ms gaps | 1 |
| P6 | `VoiceBankCatalog` rebuilt per saved-voice row and twice per Studio clone-composer body (O(n²) as voices grow; unported macOS finding-7 twin) | `IOSVoicesView.swift:47` | perf | med | refinement | voices-scroll 44.9 ms/s, scales badly | 2 |
| P7 | Shared `IOSScrollView` per-frame tax: per-scroll-event state write + `Task` spawn in the custom indicator, plus a whole-surface gradient mask | `IOSScrollRefinements.swift:82` | perf | med | refinement | floor under all three scroll scenarios | 2 |
| P8 | Dead prefetch coordinator: policy hard-disabled, yet 10 `onChange` handlers + 2 whole-store subscriptions stay wired | `IOSGenerateFlowViews.swift:151` | perf | med | safe-removal | composer-typing keystroke diffing share | 1 |
| P9 | `TabDock` dead `@EnvironmentObject` re-renders the dock on every store publish | `App/TabDock.swift:14` | perf | low | safe-removal | constant share of generation-active | 1 |
| P10 | Lifecycle toast pairs its scoped `onReceive` with a redundant whole-store subscription | `IOSEngineLifecycleToast.swift:6` | perf | low | low-risk | constant share of generation-active | 1 |
| P11 | Installer `states` dict re-diffs all of Settings ~4×/s during downloads (downgraded: upstream throttle already caps cadence) | `IOSModelInstallerViewModel.swift:28` | perf | low | refinement | unmeasured (baseline had no active download) | 2 |
| X1 | Search fields keep live autocorrection, rewriting user queries (History + Voices; reproduced on-device during IUI-1) | `IOSDesignSystemPrimitives.swift:1245` | a11y | high | safe-removal | unmeasured — input correctness | 1 |
| X2 | Voice-name field autocorrects proper nouns (sibling of X1) | `IOSGenerationInputControls.swift:367` | a11y | med | safe-removal | unmeasured — input correctness | 1 |
| X3 | Reduce Motion / Reduce Transparency environment never reaches sheets, covers, or bottom chrome (hard-rule adjacent) | `App/RootView.swift:55` | a11y | high | low-risk | unmeasured; fixing also trims sheet per-tick work | 2 |
| X4 | Dynamic Type ignored by ~90% of iOS text (132 fixed `.system(size:)` vs 15 `iosScaledFont`) | app-wide (e.g. `Sheets/IOSPlayerSheet.swift:522`) | a11y | high | refinement | design-only; re-baseline scrolls after adoption | pick |
| X5 | History row mode becomes color-only (and unspoken) when a voice name is present — the no-color-only hard rule | `History/HistoryScreen.swift:602` | a11y | med | low-risk | design-only | 1 |
| X6 | Studio inline-player waveform scrub is drag-only — no VoiceOver path (the sheet scrubber has one; the card does not) | `Studio/IOSStudioInlinePlayerCard.swift:407` | a11y | med | low-risk | design-only | 2 |
| X7 | Selected state invisible to VoiceOver on segmented chips and intensity buttons | `Sheets/IOSBottomSheets.swift:544` | a11y | med | low-risk | design-only | 1 |
| X8 | Sub-44 pt touch targets: player close (40), voice preview (40), search clear (~18) | `Sheets/IOSPlayerSheet.swift:119` + siblings | a11y | low | low-risk | design-only | 1 |
| D1 | Player sheet offers "Save" and "Download" as two labels for the identical action | `Sheets/IOSPlayerSheet.swift:317` | design | med | refinement | design-only | pick |
| D2 | Onboarding closes on "You're ready" while no model is installed and nothing can generate | `Overlays/IOSOnboardingFlow.swift:234` | design | med | refinement | design-only | pick |
| D3 | Engine-error toast routes to "Settings → Model Downloads", which does not exist | `IOSEngineLifecycleToast.swift:139` | design | med | low-risk | design-only | pick |
| D4 | History load-error copy says "Pull to retry" but there is no pull-to-refresh | `History/HistoryScreen.swift:213` | design | low | low-risk | design-only | pick |
| D5 | Settings glyphs contradict their rows (lock for transparency, sparkles for motion) | `Settings/SettingsScreen.swift:143` | design | low | low-risk | design-only | pick |
| D6 | Playback haptic fires on play and autoplay, never on pause | `Sheets/IOSPlayerSheet.swift:604` | design | low | low-risk | design-only | pick |
| D7 | Onboarding benefit-row titles render in secondary ink, flattening hierarchy | `Overlays/IOSOnboardingFlow.swift:326` | design | low | low-risk | design-only | pick |
| D8 | Bottom-panel pickers draw a grabber but cannot be drag-dismissed | `IOSDesignSystemPrimitives.swift:795` | design | med | low-risk | design-only | pick |
| D9 | Marquee text (sheet titles, player header, onboarding headlines) is fixed-size | `IOSDesignSystemPrimitives.swift:812` | a11y | med | refinement | joins the X4 program | pick |
| D10 | Two full theme systems coexist and have drifted; four independently hand-rolled glass gates with no iOS `GatedGlass` twin | `Theme/Theme.swift:16`, `Theme/ThemeModifiers.swift:9` | design | med | re-engineering | design-only; regression-risk reduction | pick |
| N1 | `iosGenerationPerformanceGate` 60 Hz tier is unmeasurable on the canonical ProMotion iPhone | `App/RootView.swift:62` | — | — | annotation-only | frozen posture stands (see below) | — |

Harness notes from the device window (not app findings): the shared
`VocelloUITextEntry.replace` has no keyboard-presence wait and reads an empty
field's placeholder as its value (both bitten during IUI-1 acceptance; the perf
suite works around them locally) — worth folding into the shared support during
wave 1's harness housekeeping.

**Wave scoping proposal.** Wave 1 (IUI-4): P1 + P5 + P8 + P9 + P10 (measured on
sheet-present-dismiss, history-scroll, composer-typing, generation-active) plus
the one-line input-trait and VoiceOver fixes X1, X2, X5, X7, X8 — all
safe-removal/low-risk, before/after five-run measurement on affected scenarios.
Wave 2 (IUI-5): the observation re-engineering P2 + P3 + P4 (root-shell gate
model + `@Observable` migration, sheet-controller scoping, stable tab identity),
P6 + P7 + P11, X3 + X6, plus whatever the design pick-list approves (D-items,
X4/D9 Dynamic Type program, D10 theme unification).

## Fix waves (IUI-4/IUI-5 — pending)

Before/after tables land here per wave.

## 60 Hz-tier posture

`iosGenerationPerformanceGate` engages only on fixed-refresh (60 Hz) devices, and
the canonical iPhone 17 Pro cannot exercise that tier. The tier stays behaviorally
frozen through the fix waves; if a physical 60 Hz device becomes available, the
lane may run on it as recorded **non-canonical** evidence only (it cannot gate and
cannot publish as canonical). Simulator timing is not evidence.

## Landed in this arc

- (pre-arc housekeeping, 2026-08-12) `ui-ios-delivery-cohort` workflow registration in
  `config/orchestration-contract.json` — the existing delivery-cohort lane died at
  required-step ledger init without it (`unknown workflow`); found during this arc's
  exploration.
- (IUI-1 authoring, 2026-08-12) The full `ios perf` harness: probe, seeder,
  nine-scenario XCUITest class, `scripts/check_ios_ui_perf.py` with offline
  self-tests, the `ui-ios-perf` workflow entry, the `iosPlayer_close` stable
  identifier, and the MetricKit animation/responsiveness advisory aggregates
  (`MetricKitUIResponsivenessAggregates` + `scripts/ios_memory_field_report.py`
  allowlist). Device acceptance (9/9 PASS + three live refusals) waits for the
  next phone window.
