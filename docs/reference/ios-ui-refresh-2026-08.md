---
status: active
owner: ios
summary: The 2026-08 iOS UI review — the planned frame-health lane, measured baseline, ranked audit findings, maintainer pick-list, and fix waves. Roadmap authority for the ios-ui-2026-08 plan.
sourceOfTruth:
  - scripts/ui_test.sh
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

## Measurement basis (IUI-1/IUI-2 — pending)

Planned: `scripts/ui_test.sh ios perf` joins nine XCUITest scenarios to an in-app
500 ms `CADisplayLink` probe pinned to `preferredFrameRateRange(60, 60, 60)` (the
app is 60 Hz-capped; expected frames are computed from the observed per-tick
cadence, and the checker fail-closes when the median block cadence leaves the
55–65 Hz band — Low Power Mode off and nominal thermals are run preconditions).
Honesty limits, stated up front: a main-run-loop display link measures main-thread
cadence health, not render-server-only hitches — the same claim limits as the
macOS probe. MetricKit `MXAnimationMetric` / `MXAppResponsivenessMetric`
aggregates accrue as advisory field evidence only (24 h delivery, never
run-correlated, never gating).

Scenario set: confirmatory `ios-idle-baseline`, `ios-tab-navigation`,
`ios-history-scroll`, `ios-voices-scroll`, `ios-settings-scroll`,
`ios-composer-typing`, `ios-sheet-present-dismiss`; exploratory
`ios-player-scrub`, `ios-generation-active`.

Baseline table lands here with IUI-2 (1 discarded warm-up + 5 counted runs,
medians + IQR).

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

- (pre-arc housekeeping, pending) `ui-ios-delivery-cohort` workflow registration in
  `config/orchestration-contract.json` — the existing delivery-cohort lane was
  unrunnable without it; found during this arc's exploration.
