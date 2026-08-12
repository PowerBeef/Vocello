---
status: active
owner: macos
summary: macOS test lanes — deterministic development verification, the platform gate, model fixtures, explicit XCUITest smoke/benchmark/perf acceptance with the ui-perf baseline protocol (copy reports out between runs; discard-and-replace on concurrent use), and crash/profile evidence.
sourceOfTruth:
  - scripts/macos_test.sh
  - scripts/ui_test.sh
---
# macOS testing

Vocello separates routine deterministic development verification from explicit native-app UI
acceptance. XCUITest is the sole autonomous macOS app UI driver.

## Ordinary development

```sh
./scripts/check_project_inputs.sh
scripts/macos_test.sh test
./scripts/build.sh build
```

These checks are sufficient to commit, push, open a pull request, merge ordinary development, and
run ordinary CI. They do not require UI execution, installed generation models, or release
evidence.

## Explicit XCUITest lanes

Run only when frontend acceptance is explicitly requested:

```sh
scripts/ui_test.sh macos smoke
scripts/ui_test.sh macos benchmark
# Filtered benchmark example:
scripts/ui_test.sh macos benchmark --modes custom --lengths short --warm 1 --label "focused"
# Scaled long-form memory evidence (local only, 2–12 segments; default 2):
scripts/ui_test.sh macos smoke --long-form-segments 10
# SwiftUI performance / animation-smoothness scenarios (local evidence only):
scripts/ui_test.sh macos perf
```

## UI-performance lane (`macos perf`)

Nine XCUITest-driven scenarios measure SwiftUI frame health, resource usage, and
animation smoothness: idle-baseline, sidebar-navigation, history-scroll (400 seeded
rows; exploratory), history-filter (exploratory), delivery-menu, settings-scroll,
composer-typing, window-resize (exploratory), and generation-active (exploratory;
gate ON, engine busy). Scroll scenarios drive a WINDOW-anchored coordinate, never
`scrollViews.firstMatch`: element-addressed events re-resolve their query per
event and that accessibility walk executes on the app's main thread, polluting
the measurement (Time Profiler evidence 2026-08-05). The History scenarios stay
exploratory because the 400-row tree's accessibility maintenance cannot be
excluded from their windows at all. Each scenario launches the app once with the in-app frame probe enabled
(`QWENVOICE_UIPERF_FRAME_PROBE`, registered knob) and marks its wall-clock window;
the probe streams 500 ms display-link blocks (frames delivered vs expected, excess
frame time, max gap, gap histogram, CPU, footprint, thermal) to
`diagnostics/ui-perf/`, and `scripts/check_macos_ui_perf.py` joins windows to rows
and writes `ui-perf-report.json` under the run directory. History seeding uses
`QWENVOICE_UIPERF_SEED_HISTORY` (registered knob; idempotent, debug-store only).

Registry posture (UI-7): the structural gate is unchanged (every scenario
present once, probe coverage ≥90% of each window, monotonic blocks, sane
refresh interval). On a PASS the checker evaluates the **warn-only** ceilings
in [`config/ui-perf-thresholds.json`](../../config/ui-perf-thresholds.json)
(derived from the baseline-v2 medians; a breach marks the run
`passedWithWarnings`, never fails it) and — on the canonical hardware profile
only — emits `benchmark-evidence.json`, which the lane publishes as a
PASS-only `ui-perf` registry record (one take per scenario, no
model/telemetry/QC claims). Non-canonical hosts keep local-only reports, and
dirty-source or late publications classify `exploratory` as usual. The probe
measures main-run-loop display-link cadence, a UI-thread hitch proxy;
compositor ground truth remains an Instruments Hitches/Core Animation trace.

Baseline protocol: one discarded warm-up run, then five counted runs (fixed
scenario order, AC power, cursor parked, `caffeinate` held by the lane); report
per-scenario median and IQR; discard any counted run whose thermal state left
nominal, that failed, or that ran during concurrent machine use, and replace it
with a fresh counted run. **Copy `ui-perf-report.json` out of the run directory
after every counted run**: retention keeps only the newest passing perf run per
lane, so a multi-run session that skips the copy loses its earlier reports (the
probe JSONL under the debug diagnostics store remains the recoverable raw
source). Thresholds are set only after repeated baselines establish spread.

| Lane | Scope |
| --- | --- |
| Smoke | Seven ordered focused journeys, each in a fresh app session with no persisted state left behind: (1) navigation + visible model/clone readiness, (2) one real Custom generation with the completed take asserted exactly once in History, (3) mid-generation cancellation — clean reset, no error badge, no History row, (4) the virtual-microphone recording flow through capture and review (registered `QWENVOICE_FAKE_MIC_WAV` knob, `/tmp` fixture; cancels before the permission-sensitive accept), (5) library surfaces, (6) a long-form project (default ~1,900-character script → two sequential streaming segments; `--long-form-segments N` scales the same journey up to 12 planned segments for local memory-scaling evidence — the summary then adds a per-segment engine physical-footprint table and retains the compact per-generation diagnostics beside the run artifacts; joined WAV, one History project row with a working segment map; the lane prints the project wall clock and writes `long-form-project-summary.txt`), (7) a two-line batch (two streamed takes → two History rows) |
| Benchmark | Ordered, configurable Custom/Design/Clone matrix with cold/warm classification and per-take deterministic proof; the default is exactly 29 takes |

The runner targets the configured native Vocello test host. Before launch it resolves every matching
Vocello and engine-service PID to its executable, fails fast if any process belongs to another app
path, and signals only the exact app/service products under the runner's Release build directory.
It uses stable accessibility identifiers and condition waits, preserves saved voices, visibly
enables the persistent Clone consent preference for acceptance, restores temporary Auto-play
changes, and records failures as XCTest activities and attachments. It never retries through a
display name or alternate app path.

Every wait/action failure automatically attaches a full-desktop screenshot (which captures foreign
system dialogs the app screenshot cannot see) plus a bounded accessibility-tree dump; each launch
fails fast with the same evidence when the app window is obscured, and an interruption-monitor
sentinel names any unrelated modal that blocks an interaction (it never answers TCC dialogs —
those stay human-answered). The macOS lanes run an advisory `ui-preflight` step that warns when
the app's microphone or speech-recognition TCC grant is undecided, execute in two phases
(a skippable `build-for-testing` keyed to a source fingerprint, then `test-without-building`, so
repeat runs on an unchanged tree skip the rebuild entirely), and write a per-test verdict sidecar
(`test-results.json`) next to `run.json`.

Benchmark accepts `--modes`, `--lengths`, `--warm`, and `--label`. Filters are explicit diagnostic
runs; invoking the command without filters is the canonical 29-take matrix on the tracked Mac mini
`Mac14,3` / Apple M2 / 8 GB profile. Dirty-source successes are exploratory even on that hardware.

## Model-dependent tests

Before generation, XCUITest must visibly confirm that Custom, Design, and Clone Speed are ready,
Generate is enabled, and the benchmark clone voice is present. Use
`scripts/macos_test.sh models ensure` only to repair/bootstrap fixtures, then begin a fresh test
run. Do not download models implicitly inside a normal UI lane.

## Deterministic evidence retained

The benchmark validator joins UI completion with:

- History/database correlation and a readable WAV;
- audio QC and complete typed frontend/XPC/backend telemetry by `generationID`;
- crash delta and XPC process lifecycle evidence;
- benchmark order, take count, cold/warm class, and timing.

The validator atomically writes an untracked `benchmark-evidence.json` containing only the run's
ordered generation IDs/cells and verdicts. The summarizer consumes that manifest plus the run ID,
never the diagnostics directory's historical population. A PASS publishes one privacy-safe record
under `benchmarks/runs/ui-generation/` and regenerates `benchmarks/HISTORY.md`. Raw telemetry, WAVs,
screenshots, and `.xcresult` remain untracked; publication never stages, commits, or pushes.

New publishable generation runs use telemetry schema v8 and evidence manifest v2. Their exact
`samples-<generationID>.jsonl` files must begin/end with one start/stop sample, contain the required
load/stream/finalization boundaries, match summary counts, have zero capture failures, and retain at
least 95% periodic coverage. macOS UI/XPC totals are calculated only from app and engine samples
paired by absolute uptime within one 500 ms cadence; independent process maxima are never added.
Critical pressure, app memory warning/exit, `hardTrim`, or `fullUnload` fails publication, and so
does a marking peak-equality breach (CP-2: within every take, no post-marking footprint sample may
exceed the pre-marking peak beyond tolerance — `config/marking-peak-equality.json`). Guarded
pressure, `softTrim`, or 95–<100% coverage publishes only as an explicit warning.

Smoke is intentionally smaller: it asserts visible completion and History plus the runner's
single-process/crash-delta checks; it does not claim the benchmark's per-take telemetry matrix.

## Instruments profiles

```sh
# CPU/signpost profile (default)
scripts/macos_test.sh profile custom:speed:

# CPU + Allocations + VM Tracker + signposts
scripts/macos_test.sh profile --kind memory custom:speed:

# Explicit diagnostic exception: retain the raw Instruments document.
scripts/macos_test.sh profile --kind memory --keep-trace custom:speed:
```

The memory profile captures one cold long take so Allocations/VM Tracker include model-load and
sustained-generation peaks. It uses Apple's Allocations template, which contains both memory tracks
with automatic VM snapshots disabled; standalone VM Tracker auto-snapshots suspend the target and
would legitimately lower its 500 ms sampler coverage. Publication verifies that setting from the
captured trace and still enforces the unmodified 95% coverage floor. The default 180-second safety
cap accommodates a cold long take, while target exit ends recording early. `scripts/macos_test.sh
memory` owns the repeated retained-growth qualification.

Both commands build the exact CLI, suspend one owned process, attach Instruments to that exact PID,
resume it only after xctrace reports recording, and validate the exported trace table of contents.
The memory lane enables verbose per-sample telemetry and remains PASS-only. Headless CLI profiles
report the owning engine process; XPC UI benchmarks use the uptime-aligned app+engine aggregate.
The tracer stage requires at least 5 GiB free for CPU profiles and 15 GiB for memory profiles before
it launches the target. The prerequisite CLI build uses the shared 8 GiB development-build floor,
so a complete CPU-profile command effectively requires 8 GiB; memory remains 15 GiB. After
successful trace validation and history publication, the raw trace is
deleted by default; the record retains its digest, capture settings, extracted summary, original
ephemeral path, and retention status. `--keep-trace` is the explicit diagnostic exception. A
failure retains only the newest raw failure for that platform/profile kind. Sidecars and retained
diagnostics remain under `build/` and untracked.

Other heavy macOS lanes also use the manifest-owned build-storage preflight before creating output:
8 GiB for deterministic/runtime builds, 12 GiB for telemetry-overhead and UI smoke, and 15 GiB for
language, memory, and UI benchmark work. These are working-space floors, not cache quotas. Inspect
`python3 scripts/build_output_policy.py status` before applying its suggested bounded cleanup.

Retained-memory qualification is a distinct non-Instruments lane:

```sh
scripts/macos_test.sh memory --label retained-check
```

It runs the policy-owned Custom→Design→Clone Speed/medium sequence with three canonically named
`retained#0...2` takes per mode (plus the CLI's genuine Custom/Design cold takes) in one process.
Those retained takes still report their actual engine warm state. Policy
`retained-memory-v1` compares the first and last completed retained-take footprint within each mode;
the maximum positive growth must stay at or below 5% of physical RAM. Intended cross-mode model
residency is diagnostic and is not mislabeled as a leak. A PASS creates a
`memory-qualification` record; a generation, memory, QC, or retention failure leaves only local
artifacts.

## Generated-output ownership

macOS development and UI lanes reuse only `build/cache/xcode/macos/`; shared package checkouts live
under `build/cache/xcode/source-packages/`. Result bundles, diagnostics, profiles, and current dSYMs
are untracked artifacts under `build/artifacts/`, while release packaging is isolated under
`build/scratch/derived-data/release-macos/` and `build/dist/macos/`. `build/Vocello.app` and
`build/vocello` are public symlinks to current canonical products, not copied applications. See the
authoritative owner/lifetime table in [`privacy-storage.md`](privacy-storage.md).

## Release boundary

macOS signing, notarization, and packaging use deterministic release-readiness checks. Smoke and
benchmark XCUITest results are independent frontend QA artifacts and never a packaging prerequisite.

See also [`testing-runbook.md`](testing-runbook.md),
[`benchmarking-procedure.md`](benchmarking-procedure.md), and
[`macos-release-qa.md`](macos-release-qa.md).
