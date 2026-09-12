---
status: active
owner: macos
reviewed: 2026-09-12
summary: macOS test lanes — deterministic development verification, the platform gate, model fixtures, explicit XCUITest smoke/benchmark/perf acceptance with the ui-perf baseline protocol (copy reports out between runs; discard-and-replace on concurrent use), and crash/profile evidence.
sourceOfTruth:
  - scripts/macos_test.sh
  - scripts/ui_test.sh
  - scripts/lib/xctest_summary.py
  - scripts/lib/host_preflight.sh
  - Tests/VocelloCoreTests/MacStudioGenerationRequestFactoryTests.swift
  - Tests/VocelloCoreTests/VoiceClipEnrollmentEvidenceTests.swift
---
# macOS testing

Vocello separates routine deterministic development verification from explicit native-app UI
acceptance. XCUITest is the sole autonomous macOS app UI driver.

Clone/enrollment parity is part of ordinary deterministic verification. The core suite exercises
the shared transcription-review/evidence policy and the pure macOS Design/Clone request factory,
including manual-edit precedence, stale-result rejection, explicit audio-only enrollment,
reference-language metadata, target-text Auto routing, explicit-language precedence, and exact
reference/prompt/seed/variation identity. These tests guard the pre-XPC boundary; native visual and
interaction acceptance remains the explicitly requested XCUITest lane below.

## Ordinary development

```sh
scripts/dev.sh check        # lint, contracts, selected tests, native lanes the dirty tree touches
scripts/macos_test.sh test  # the three deterministic macOS bundles when you want them all
scripts/dev.sh ci           # exactly what push CI runs, serially
```

These are advisory; the commit lint is the only local block and CI on `main` is the gate
(development is main-only, so there is no pull-request or merge step). None of them needs UI
execution, installed generation models, or release evidence.

`scripts/macos_test.sh test` writes each bundle's raw log plus a structured summary next to it
(`core.test-results.json`, `transport.test-results.json`, `runtime.test-results.json`, produced by
`scripts/lib/xctest_summary.py`, the same writer the XCUITest lanes use) and `verdict.txt` under
`build/artifacts/macos/tests/<run>/`. The bundles run through the direct `xcrun xctest` runner on
purpose: Xcode 26.6 can compile and then wait indefinitely before spawning `xctest` for these
hostless bundles through `xcodebuild`, so no `.xcresult` is produced for this lane.

`scripts/macos_test.sh test --coverage` is opt-in and non-blocking: it builds the bundles with
`-enableCodeCoverage YES` (which flips the shared macOS cache and forces a rebuild, so it is never
part of `scripts/dev.sh check` or push CI), runs them with `LLVM_PROFILE_FILE` under the run directory, and
exports `coverage.json` (llvm-cov, summary only), `coverage-summary.txt` (line coverage per source
root) and `coverage-runtime.json` (SwiftPM export for `Qwen3RuntimeTests`). The verdict gains a
`coverage=` line; no threshold exists yet. A future floor belongs in a dedicated `config/` policy
file validated from `scripts/check_project_inputs.sh`, not in this lane.

## Platform gate (`scripts/macos_test.sh gate`)

```sh
scripts/macos_test.sh gate                         # project inputs → foundation build → core-test → deterministic tests → crash delta
QWENVOICE_GATE_BENCH=1 scripts/macos_test.sh gate  # adds a bounded vocello bench step; a PASS publishes its benchmark history
scripts/macos_test.sh release-readiness            # project inputs → exact-path app build → deterministic tests → crash delta
scripts/macos_test.sh preflight [--strict-models]  # Xcode, app, dSYM, XPC and model-fixture status; --strict-models fails on a missing fixture
scripts/macos_test.sh crashes [--test]             # collect and symbolicate .ips for the app and the XPC service
scripts/macos_test.sh telemetry-overhead           # model-dependent on/off telemetry parity diagnostic
```

The gate is release tooling, not the daily loop: `.github/workflows/release.yml` runs it in the
`archive-ios` job as the `platform-readiness` step (`scripts/macos_test.sh gate &&
./scripts/build_foundation_targets.sh ios`). Its five ledgered required steps are `project-inputs`
(`check_project_inputs.sh`, step 0), `foundation-build` (`build_foundation_targets.sh macos`), `core-tests`
(`VocelloCoreTests`), `deterministic-tests` (the same three bundles as `test`) and the gate-fatal
`crash-delta` over `.ips` files newer than the run's marker. Every step lands in a
required-step ledger with the verdict under `build/artifacts/macos/gates/`, and
`QWENVOICE_GATE_BENCH=1` appends a fifth bounded `vocello bench` step whose PASS publishes one
benchmark record. `release-readiness` is the packaging prerequisite `scripts/release.sh` invokes
before signing; it needs no model fixture and no UI evidence.

`gate`, `telemetry-overhead`, `lang-bench` and `memory` refuse to start on a busy host:
`require_quiet_host` in `scripts/lib/host_preflight.sh` rejects a one-minute load above twice the
core count or a kernel memory-pressure level above normal before any model loads, and
`QVOICE_ALLOW_BUSY_HOST=1` records the numbers and continues only for an explicitly exploratory run.
`memory` and `lang-bench` are consent-bound (`ask` in `.claude/settings.json`) and are never run
unasked; the storage floors every lane checks first are listed under Instruments profiles below.

## Scheduled ThreadSanitizer characterization

```sh
scripts/macos_test.sh tsan
```

This explicit lane instruments the deterministic `VocelloCoreTests` and injectable
`VocelloEngineIntegrationTests` bundles. It does not execute the MLX/Metal runtime tests, whose
lazy graph and single-owner behavior remain covered by their owned deterministic suite. Xcode may
still compile linked MLX targets while building the test host. The driver launches Xcode's resolved
`xctest` binary directly with each bundle's own embedded TSan runtime preloaded; repository-owned
Mach-O files remain arm64-only, while only the named Xcode sanitizer dylib may retain its universal
toolchain slices.

The nightly workflow (`nightly.yml`, job `tsan`, 04:00 UTC and on dispatch) is non-blocking only
during the bounded characterization period in `config/tsan-policy.json`. It preserves every failed run, performs no automatic retry, and requires
three consecutive clean runs plus explicit maintainer review before it may become blocking. The
first corrected physical-host run on 2026-08-26 passed all 460 core and 18 XPC tests with no TSan
warning or race summary.

## Explicit XCUITest lanes

Run only when frontend acceptance is explicitly requested:

```sh
scripts/ui_test.sh macos smoke
scripts/ui_test.sh macos localization
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
dirty-source or late publications classify `exploratory` as usual. Since
IUI-6 the `ui-perf` kind is platform-aware: the iOS twin lane
(`scripts/ui_test.sh ios perf`) publishes through the same plumbing against
its own contract (`config/ui-perf-thresholds-ios.json`; see
[`ios-device-testing.md`](ios-device-testing.md)). The probe
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
| Smoke | Seven ordered focused journeys, each in a fresh app session; generated diagnostic-store audio and History are retained, not automatically erased: (1) navigation + visible model/clone readiness, (2) one real Custom generation with the completed take asserted exactly once in History, (3) mid-generation cancellation — clean reset, no error badge, no History row, (4) the virtual-microphone recording flow through capture and review (registered `QWENVOICE_FAKE_MIC_WAV` knob, `/tmp` fixture; cancels before the permission-sensitive accept), (5) library surfaces, (6) a long-form project (default ~1,900-character script; report the actual planner segment count rather than assuming a fixed count; `--long-form-segments N` scales the same journey up to 12 planned segments for local memory-scaling evidence — the summary then adds a per-segment engine physical-footprint table and retains the compact per-generation diagnostics beside the run artifacts; joined WAV, one History project row with a working segment map; the lane prints the project wall clock and writes `long-form-project-summary.txt`), (7) a two-line batch (two streamed takes → two History rows) |
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

Do not infer an OS memory-pressure event from `memory.pressure.soft_trim` alone. Inspect the
typed event's kind, source and reason: routine `post-generation` cache cleanup also emits a
`trim-action` with reason `post_generation_cache_clear`. Keep the existing qualification warning
and report its origin separately; zero pressure signals is not proof of leak freedom. Use the
policy-owned retained-memory lane below for bounded within-mode growth, rather than comparing
unrelated peaks or interpreting initial model/cache residency as a leak.

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
