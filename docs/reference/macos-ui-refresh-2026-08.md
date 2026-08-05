---
status: active
owner: macos
summary: The 2026-08 macOS UI review — measured frame-health baseline, ranked audit findings, the staged refresh proposal (wave 1 refinements, wave 2 re-engineering), and what already landed. Roadmap authority for the macos-ui-2026-08 plan.
sourceOfTruth:
  - scripts/check_macos_ui_perf.py
  - Tests/VocelloMacUITests/VocelloMacPerfUITests.swift
---
# macOS UI review & refresh — 2026-08

> The durable record of the 2026-08-04/05 macOS UI review arc: what was measured, what
> the audits found, the maintainer-approved safe fixes that landed, and the staged
> refresh proposal awaiting maintainer review. The remote-review rendering of this
> document is a private claude.ai Artifact (published 2026-08-05, viewable in the
> maintainer's Claude iOS app); this file is the repository authority. Work items:
> plan `macos-ui-2026-08` in [`docs/ROADMAP.md`](../ROADMAP.md).

## Measurement basis

The SwiftUI frame-health lane (`scripts/ui_test.sh macos perf`, landed `9d283a9`; lane
reference: [`macos-testing.md`](macos-testing.md) "UI-performance lane") drove nine
scripted scenarios against the real app. Baseline session 2026-08-05: one discarded
warm-up plus five counted runs on the canonical Mac mini M2 8 GB, 60 Hz panel, AC
power, cursor parked, thermals nominal in every counted run. *Hitch* = summed excess
frame time per second of measured window (main-run-loop display-link cadence — a
UI-thread hitch proxy, not compositor presents).

| scenario | hitch ms/s (median) | IQR | max gap ms | CPU user s | peak MB |
| --- | --- | --- | --- | --- | --- |
| history-filter | 312.4 | 3.4 | 2010 | 7.6 | 221 |
| history-scroll | 270.7 | 112.9 | 2946 | 1.4 | 258 |
| generation-active | 158.1 | 31.6 | 177 | 1.3 | 91 |
| sidebar-navigation | 131.3 | 3.9 | 285 | 11.7 | 125 |
| delivery-menu | 119.1 | 1.4 | 98 | 4.4 | 110 |
| composer-typing | 51.4 | 11.4 | 70 | 9.4 | 90 |
| settings-scroll | 43.3 | 5.8 | 51 | 0.7 | 68 |
| window-resize (exploratory) | 26.1 | 19.3 | 58 | 2.4 | 90 |
| idle-baseline | 0.0 | 0.0 | 17 | 0.1 | 60 |

Idle at exactly 0.0 across all runs means there is no ambient rendering bug — every
cost above is interaction-triggered. Reports are local evidence (`ui-perf-report.json`
beside each run; retention keeps the newest passing run per lane, so multi-run baseline
sessions must copy each report out before the next run — the probe JSONL under the
debug diagnostics store is the durable raw source).

## Ranked findings (four audits + measurement)

1. **History pipeline** — worst measured surface (312/271 ms/s, 2.9 s single stalls,
   82 MB churn per filter cycle). `displayEntries` is rebuilt (dictionary build +
   per-project segment sorts) on every body evaluation and re-triggered by an unused
   `@EnvironmentObject ttsEngineStore`; delete paths are logic-in-view with no test
   seam.
2. **Root-shell invalidation** — `ContentView` reads engine properties in `body` for
   the gate environment, so every engine transition re-diffs the whole
   `NavigationSplitView` during the most contended windows (generation-active:
   158 ms/s with glass already off).
3. **Screen-switch cost** — ~650 ms CPU per sidebar switch (11.7 s / 18 switches):
   coarse `TTSEngineStore` observation by every screen plus full screen remounts.
4. **Focus loss on resize** — `GenerationSetupRow`'s `ViewThatFits` remounts its text
   fields on breakpoint flip; Clone transcript / Design brief lose first-responder
   mid-typing. The nested fit containers also produce a hybrid layout at exactly the
   720×560 default window.
5. **Accessibility, five high-severity** — `.tertiary` state text at ~2.0–2.4:1
   contrast (~12 sites, AA 1.4.3 fail); `.focusEffectDisabled()` on 12 controls with
   no substitute indicator (AA 2.4.7); the 8 direct glass sites that skipped Reduce
   Transparency (**fixed**, `99d746d`); zero `@ScaledMetric` anywhere plus hard
   62×24 / 17 pt / 14 pt / 7–10 pt fixed sizes (AA 1.4.4); waveform seek is
   gesture-only (Level A 2.1.1 — VoiceOver/keyboard users cannot scrub).
6. **Delivery menu** — 119 ms/s and 4.4 s CPU per 10 open/close cycles (menu popup +
   advisory re-render; `EmotionPickerView` `ViewThatFits`).
7. **ViewThatFits misuse family** — `VoicesView` double-builds both row layouts per
   visible row per pass; `CloneSourceRow` builds `VoiceBankCatalog` twice per render.
8. **Dead code** — the studio-shell scaffolding ledger (**removed**, `99d746d`;
   −615 lines).

Cross-cutting root causes: invalidation **scope** (not event rate — the coalescer
already bounds frequency); `ViewThatFits` used as a layout decision engine with
unstable child identity; tokens that never scale (iOS's newer theme layer is the
porting source for text ramp, motion family, and `ScaledMetric` adoption).

## Refresh proposal (awaiting maintainer review of the artifact)

Direction is bound by `PRODUCT.md`: Warm · Premium · Native, stability-led polish, no
studio-shell relayouts, dark-only, glass economics respected (§K gate). Thesis: **the
same room, better lit** — no layout changes; text, focus, motion, and invalidation
scope carry the refresh.

**Wave 1 — refinements, each independently landable, gated on maintainer go:**

| ID | Proposal | Effort | Also fixes |
| --- | --- | --- | --- |
| W1-A | Warm text ramp ported from iOS (three ink tokens replacing cold `.tertiary`/`.secondary` on state-bearing text) | S–M | AA 1.4.3 contrast |
| W1-B | Named motion family ported from iOS (220–420 ms curves through `appAnimation`) | S | — |
| W1-C | Mode-tinted focus rings replacing all 12 `.focusEffectDisabled()` suppressions | M | AA 2.4.7 |
| W1-D | Scoped observation: dedicated gate observable + History `displayEntries` cache + drop unused env object | M | findings 1–2 (312/271/158 ms/s) |
| W1-E | `@ScaledMetric` on fixed sizes; free the two Settings fixed-width labels | M | AA 1.4.4 |
| W1-F | Stable field identity outside `ViewThatFits`; single width signal; `VoicesView`/`CloneSourceRow` compute-once | M | finding 4, 7 |
| W1-G | Shared `glassBackground` helper consolidating gate + Reduce Transparency so the invariant cannot regress | S | — |

Perf-relevant waves re-run the perf lane before/after and attach both numbers.

**Wave 2 — re-engineering (separate roadmap items):** `TTSEngineStore` `@Observable`
migration with scoped projections; History/Voices coordinator extraction (test seam on
delete paths); shared generation-lifecycle executor (triplicated generate/cancel);
`AudioPlayerViewModel` split (streaming playback engine extraction).

## Wave 1 results (landed 2026-08-05, maintainer go)

All seven W1 items shipped (`4e0c7cf`, `bc7c108`, `357d482`, `20e14b2`). Verified by the full gate, both
platform compiles, core tests, a 7/7 smoke lane on the wave-1 tree, and an
after-measurement session under the baseline protocol (warm-up + 5 counted runs;
two additional runs were discarded per protocol after a concurrent-use memory
pressure transient failed their generation takes mid-stream — engine telemetry
showed identical 82-char failures with no crash, and a post-quiescence CLI take
plus both replacement runs generated cleanly).

| scenario | before ms/s | after ms/s | Δ | note |
| --- | --- | --- | --- | --- |
| settings-scroll | 43.3 | 35.0 | **−19%** | |
| composer-typing | 51.4 | 43.3 | **−16%** | |
| sidebar-navigation | 131.3 | 126.5 | −4% | |
| delivery-menu | 119.1 | 120.4 | +1% | unchanged |
| history-filter | 312.4 | 326.2 | +4% | unchanged — see finding below |
| history-scroll | 270.7 | 287.6 | +6% (IQR 205) | unchanged — see finding below |
| generation-active | 158.1 | 172.2 | +9% (IQR 33) | within spread |
| window-resize | 26.1 | 29.4 | +13% (IQR 19) | within spread |
| idle-baseline | 0.0 | 0.0 | — | still pristine |

**Honest read, twice corrected:** the W1-D observation scoping delivered real
but modest wins on the light scenarios and did NOT move the History numbers.
The after-session first localized the ~3.1 s history-scroll stall to row
materialization — and then a Time Profiler sample (2026-08-05, wave-2 phase A)
overturned that too: the stall was **the measurement harness observing
itself**. Element-addressed XCUITest scrolls re-resolve their query per event,
and that accessibility snapshot walk over the 400-row tree executes on the
app's main thread — the sampled window showed the app idle apart from
XCTElementQuery machinery. Users never trigger it. The scenarios were fixed to
scroll through window-anchored coordinates (shallow query), history-filter was
reclassified exploratory (typing cannot avoid per-interaction queries), and the
first corrected run measured history-scroll's TRUE cost at ~210 ms/s hitch with
a worst gap of ~200 ms — no multi-second stalls exist outside the harness.
History numbers from the original baseline are not comparable to the corrected
scenario and are superseded by the baseline-v2 session. Row thinning remains a
legitimate wave-2 item at the ~200 ms-batch scale (UI-6), an order of magnitude
smaller than first believed.

## Wave 2 results (landed 2026-08-05, maintainer go)

All wave-2 items shipped in five commits (`de063d9` harness-honesty
correction, `40ba8ab` store `@Observable` migration, the deletion-engine,
lifecycle-executor, and player-split commits): the measurement correction
above; `TTSEngineStore` migrated to `@Observable` with explicit Combine
bridges for its two imperative consumers; History's irreversible delete
paths extracted into the core-tested `HistoryDeletionEngine` (eight
deterministic tests); the triplicated generate/cancel unified in
`GenerationLifecycleExecutor` with the May-2026 no-flicker discipline
preserved; and the shared player's audio-graph mechanics extracted into
`LiveStreamingPlaybackEngine` (both platforms compile; session semantics
stay in the view model). Verified: full deterministic suite, both
compiles, a 7/7 smoke lane, and the baseline-v2 session below (5 counted
runs on the corrected scenarios, thermals nominal, zero failed runs).

**Baseline-v2** (corrected scenarios: scrolls are window-anchored, History
scenarios exploratory):

| scenario | v2 median ms/s | IQR | trend from first baseline |
| --- | --- | --- | --- |
| idle-baseline | 0.0 | 0.0 | unchanged, pristine |
| settings-scroll | **0.0** | 0.0 | 43.3 → 0 — verified genuine (≈700 ms CPU, ≈57 fps in-window): the old number was query pollution; the screen scrolls perfectly |
| window-resize | 28.7 | 10.4 | ≈ unchanged (exploratory) |
| composer-typing | 41.9 | 4.0 | 51.4 → 41.9 (**−18%**) |
| sidebar-navigation | 118.6 | 1.1 | 131.3 → 118.6 (**−10%**, store migration measurable) |
| delivery-menu | 120.4 | 2.9 | ≈ unchanged |
| generation-active | 175.4 | 38.8 | ≈ unchanged within spread (exploratory) |
| history-filter | 321.3 | 6.2 | exploratory — includes harness AX cost |
| history-scroll | 456.4 | 5.7 | exploratory — the ~3.1 s AX drain now lands deterministically in-window; the app-real component measured standalone is ≈210 ms/s with ≈200 ms worst gaps |

The confirmatory picture after both waves: every interaction surface a
user touches outside History sits at or under ~120 ms/s with the two
scroll surfaces at 0.0, and History's true app cost is ~200 ms batch
materialization under fast scrolling — row thinning remains open at that
scale (tracked under UI-7's threshold formalization; any further History
work should lean on Instruments, not the lane's polluted History numbers).

## UI-7 (landed 2026-08-05): the perf lane is a registered benchmark kind

`ui-perf` joined the PASS-only registry on the `prosody-calibration`
precedent: schema v2/v3 enums, a bounded `ui*` metric allowlist, a kind
semantics validator (one take per scenario, no model/telemetry/QC claims,
coverage and refresh sanity), harness-hash binding of the probe/seeder/
scenarios/checker/threshold contract, and **warn-only ceilings** in
[`config/ui-perf-thresholds.json`](../../config/ui-perf-thresholds.json)
derived from the baseline-v2 medians (a breach marks the run
`passedWithWarnings`; hard ceilings wait for repeated baseline sessions).
The lane emits evidence only on the canonical hardware profile and
publishes through `benchmark_history.py record`; five offline self-tests
cover the gate, thresholds, and take identities, and the first live record
published from the real baseline-v2 v5 run (classified exploratory by the
standard provenance because publication came after later commits; canonical
records mint automatically from in-run publications). With UI-7 done the
`macos-ui-2026-08` plan is **complete**.

## Landed in this arc

- `9d283a9` — the perf harness (nine scenarios, structural gate, fail-closed proofs,
  registered `QWENVOICE_UIPERF_*` knobs, hardened UI-lane build fingerprint,
  retention-contract consumers widened to superset lane semantics).
- `99d746d` — safe fixes: dead-UI-code removal (−615 lines, reference-free-verified)
  and Reduce Transparency honored at all 8 direct glass sites; verified by the full
  gate, both platform compiles, core tests, and a green 7/7 smoke lane.
