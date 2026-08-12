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

IUI-1 still owes its device acceptance: one clean 9/9 PASS on the canonical
iPhone 17 Pro plus the three scripted fail-closed refusals exercised against
real pulled evidence. Offline, the checker's self-tests
(`scripts/tests/test_check_ios_ui_perf.py`) already cover those refusal
branches. The baseline table lands here with IUI-2 (1 discarded warm-up + 5
counted runs, medians + IQR).

## Ranked findings and maintainer pick-list (IUI-3 — pending)

Lands here after the audit. Pre-known candidates entering the ranking are recorded
in the roadmap IUI-3 gate; the maintainer gate sits at this item's exit — no fix
lands until the pick-list and wave scope get an explicit go.

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
