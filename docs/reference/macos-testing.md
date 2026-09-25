---
status: active
owner: macos
reviewed: 2026-09-20
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
reference/prompt/seed/variation identity. These tests guard the request boundary; native visual and
interaction acceptance remains the explicitly requested XCUITest lane below.

## Ordinary development

```sh
scripts/dev.sh check        # lint, contracts, selected tests, native lanes the dirty tree touches
scripts/macos_test.sh test  # the deterministic macOS core and runtime tests
scripts/dev.sh ci           # exactly what push CI runs, serially
```

These are advisory; the commit lint is the only local block and CI on `main` is the gate (`main` is
the only published branch; agent worktree branches are integrated into it by the lead, with no pull
request). None of them needs UI
execution, installed generation models, or release evidence.

`scripts/macos_test.sh test` writes each bundle's raw log plus a structured summary next to it
(`core.test-results.json`, `runtime.test-results.json`, produced by
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
scripts/macos_test.sh gate                         # project inputs → foundation build → deterministic tests → crash delta
QWENVOICE_GATE_BENCH=1 scripts/macos_test.sh gate  # adds a bench preflight and a bounded, seeded vocello bench; a PASS publishes its benchmark history
QWENVOICE_GATE_BENCH_SEED=1 scripts/macos_test.sh gate  # the same bench, added to the staged baseline instead of compared
scripts/macos_test.sh release-readiness            # project inputs → exact-path app build → deterministic tests → crash delta
scripts/macos_test.sh preflight [--strict-models]  # Xcode, app, dSYM and model-fixture status; --strict-models fails on a missing fixture
scripts/macos_test.sh crashes [--test]             # collect and symbolicate .ips for the app
scripts/macos_test.sh telemetry-overhead           # model-dependent on/off telemetry parity diagnostic
```

The gate is release tooling, not the daily loop: `.github/workflows/release.yml` runs it in the
`archive-ios` job as the `platform-readiness` step (`scripts/macos_test.sh gate &&
./scripts/build_foundation_targets.sh ios`). Its four ledgered required steps are `project-inputs`
(`check_project_inputs.sh`, step 0; locally the gate sets `QVOICE_GATES=quick`, so the Python
suite CI already ran is skipped while `scripts/` and `config/` are clean, and CI ignores it),
`foundation-build` (`build_foundation_targets.sh macos`), `deterministic-tests` (the same bundles as
`test`: `VocelloCoreTests`, which the gate no longer runs a second time, and the Qwen3 runtime
tests) and the gate-fatal `crash-delta` over `.ips` files newer than the run's marker. Every step
lands in a required-step ledger with the verdict under `build/artifacts/macos/gates/`.

`QWENVOICE_GATE_BENCH=1` adds two steps. A `benchmark-preflight` before step 0 takes seconds: a
quiet host, the canonical hardware profile, the installed benchmark model and a prediction of the
baseline identity from the live host and the gate matrix; any failure stops the gate before a
build, with a finalized ledger and a verdict that quotes the preflight's reason (a busy host, the
hardware, a missing model, or a predicted BASELINE INVALID with its seed command). After the crash delta, unless an earlier step failed
(the bench step is then left unrecorded and the ledger marks it missing), a bounded `vocello bench`
of five seeded warm takes re-checks the host right before the model loads, compares the warm
medians with the committed baseline and, on a PASS, publishes one benchmark record. A loaded,
low-power or throttled host makes the bench INCONCLUSIVE: the ledger records the step as failed with
exit code 3, nothing is published, and the gate prints `GATE: INCONCLUSIVE` and exits 3, never PASS
or FAIL. The optimized CLI build logs to `cli-build.log`, the measurement to `bench.log`, and every
threshold used, with the baseline digest, to `bench-verdict.json`. `QWENVOICE_GATE_BENCH_SEED=1`
runs the same bench but adds the run to the staged baseline instead of comparing
([benchmarking-procedure.md](benchmarking-procedure.md), baseline comparison).
`release-readiness` is the packaging prerequisite `scripts/release.sh` invokes before signing; it
needs no model fixture and no UI evidence.

The gate bench, `telemetry-overhead`, `lang-bench` and `memory` refuse to start on a busy host (the
deterministic gate without a bench does not check, so it can run beside an agent or a native build):
`require_quiet_host` in `scripts/lib/host_preflight.sh` rejects a one-minute load above twice the
core count, a kernel memory-pressure level above normal, another holder of the host-wide native lock
or a locked agent worktree before any model loads, and
`QVOICE_ALLOW_BUSY_HOST=1` records the numbers and continues only for an explicitly exploratory run.
`memory` and `lang-bench` are consent-bound (`ask` rules in `.claude/settings.json`; explicit
request required) and are never run unasked; the storage floors every lane checks first are listed under Instruments profiles below.

## Blocking ThreadSanitizer subset

```sh
scripts/macos_test.sh tsan
```

This lane instruments the deterministic `VocelloCoreTests` bundle, the whole subset
`config/tsan-policy.json` names. It does not execute the MLX/Metal runtime tests, whose
lazy graph and single-owner behavior remain covered by their owned deterministic suite. Xcode may
still compile linked MLX targets while building the test host. The driver launches Xcode's resolved
`xctest` binary directly with the bundle's own embedded TSan runtime preloaded; repository-owned
Mach-O files remain arm64-only, while only the named Xcode sanitizer dylib may retain its universal
toolchain slices.

Since 2026-09-14 this lane is blocking: `ci.yml` runs it as the `macos-tsan` job whenever the Swift
lane routes (its own `build/cache/xcode/macos-tsan` cache, 5 to 11 minutes on a second macOS runner)
inside `CI required`, and the nightly workflow (`nightly.yml`, job `tsan`, 04:00 UTC and on
dispatch) keeps a cold run of the same lane. `config/tsan-policy.json` records the characterization
that earned the promotion (three consecutive scheduled nightly passes, runs 34683488068,
34749309445 and 34829408217, zero race reports, only the two registered skips) and the dated
maintainer decision; `scripts/runtime_security_contract.py` refuses a blocking status without the
recorded passes, zero open confirmed races and that decision. Both workflows preserve every failed
run and perform no automatic retry. The first corrected physical-host run on 2026-08-26 passed all
460 core and 18 transport tests with no TSan warning or race summary (the transport bundle left
with the XPC service on 2026-09-15; the lane is core-only since).

## Explicit XCUITest lanes

Run only when frontend acceptance is explicitly requested. `test01_NavigationAndReadiness` (the whole
`localization` lane, and the first journey of every `smoke` lane) launches the app with Foundation's
`-NSDoubleLocalizedStrings YES -NSShowNonLocalizedStrings YES`, so doubled text (menus included) and
UPPERCASE labels in its attachment `mac-smoke-readiness-pseudolocalized` are the diagnostic, not a
defect: doubling is the long-string stress and uppercase marks a key absent from the String Catalog.
Under that stress the journey asserts single-line Saved Voices rows, chips and Settings badges and
in-window controls (`assertSavedVoicesLayoutIntact`, `assertSettingsPackageRowsLayoutIntact`), the
check that caught the 2026-09-13 row collapse. Every macOS journey also launches with
`-AppleLanguages (en) -AppleLocale en_US` (`VocelloMacUITestCase.englishLaunchArguments`), so the
few English values the journeys read ("Ready", "N characters") do not depend on the host's system
language now that the catalog carries French. All of these arguments are process-scoped and never
persist.
Lanes:

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
# Product image refresh (asset workflow, never acceptance or benchmark evidence):
scripts/ui_test.sh macos marketing [--scenario all|models]
```

The `marketing` lane refreshes the README and website images through genuine controls at a
1040×680 window (`VocelloMacMarketingCaptureUITests.test00_WebsiteRefresh`; `--scenario models`
runs `test06_ModelDownloadsRefresh` alone): it generates two demo takes and saves one designed
voice, attaches the captures for export and publishes nothing. Its run record carries
`evidenceClass: marketing-assets`; it is never acceptance, promotion or benchmark evidence.

The benchmark lane also records what the app actually plays: the test runner taps the app's own
audio output for every take (Core Audio process tap, physical output muted while tapped, one
manual System Audio Recording grant for the lane-re-signed `com.qwenvoice.app.uitests.xctrunner`), writes the captures under the run's
`playback-capture/` directory and the checker compares each one with the published take WAV
(`playbackCapture*` metrics, warn codes, and since 2026-09-14 a gate on captured takes; the smoke lane captures its completed-generation take as well; see
[`benchmarking-procedure.md`](benchmarking-procedure.md) §4.10). A missing or denied capture never
fails the lane; the take reads `playbackCaptureStatus: unavailable`.

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
(calibrated on the retired Mac mini M2 8 GB and provisional on the canonical Mac mini M6 until
roadmap item AV-17 re-derives them; a breach marks the run
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
Vocello PID to its executable, fails fast if the process belongs to another app path, and signals
only the exact app product under the runner's Release build directory.
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
`Mac18,5` / Apple M6 / 16 GB profile (canonical since 2026-09-22; the retired Mac mini M2 8 GB
records stay history). The lane refuses to build on any other Mac ("non-canonical host; benchmark
records are not publishable"). Dirty-source successes are exploratory even on that hardware.

## Model-dependent tests

Before generation, XCUITest must visibly confirm that Custom, Design, and Clone Speed are ready,
Generate is enabled, and the benchmark clone voice is present. Use
`scripts/macos_test.sh models ensure` only to repair/bootstrap fixtures, then begin a fresh test
run. Do not download models implicitly inside a normal UI lane.

## Deterministic evidence retained

The benchmark validator joins UI completion with:

- History/database correlation and a readable WAV;
- audio QC and complete typed frontend/backend telemetry by `generationID` (app + engine rows);
- crash delta evidence;
- benchmark order, take count, cold/warm class, and timing.

The validator atomically writes an untracked `benchmark-evidence.json` containing only the run's
ordered generation IDs/cells and verdicts. The summarizer consumes that manifest plus the run ID,
never the diagnostics directory's historical population. A PASS publishes one privacy-safe record
under `benchmarks/runs/ui-generation/` and regenerates `benchmarks/HISTORY.md`. Raw telemetry, WAVs,
screenshots, and `.xcresult` remain untracked; publication never stages, commits, or pushes.

New publishable generation runs use telemetry schema v8 and evidence manifest v2. Their exact
`samples-<generationID>.jsonl` files must begin/end with one start/stop sample, contain the required
load/stream/finalization boundaries, match summary counts, have zero capture failures, and leave no
gap between samples above twice the sampler cadence. The app and engine samples of the one hosting
process form one series in absolute-uptime order; they are never summed.
Critical pressure, app memory warning/exit, `hardTrim`, or `fullUnload` fails publication, and so
does a marking peak-equality breach (CP-2: within every take, no post-marking footprint sample may
exceed the pre-marking peak beyond tolerance, and the exact MLX peak, cumulative since the request
began, may not rise across the marking pass by more than one page —
`config/marking-peak-equality.json`). Guarded
pressure or `softTrim` publishes only as an explicit warning.

The routine per-tier cache clear (a `trim-action` with source `post-generation` and reason
`post_generation_cache_clear`, emitted after every take where `clearCacheAfterGeneration` is set)
is not memory pressure: records since 2026-09-25 count it as `policyCacheClearCount` (it stays in
`memoryTrimCount`/`maximumTrimLevel`) and it raises neither the pressure level nor
`memory.pressure.soft_trim`. Every other soft trim still warns. Older records fold the routine
clear into that warning, so there `memory.pressure.soft_trim` alone is not an OS pressure event;
zero pressure signals is not proof of leak freedom either. Use the
policy-owned retained-memory lane below for bounded within-mode growth, rather than comparing
unrelated peaks or interpreting initial model/cache residency as a leak.

Smoke is intentionally smaller: it asserts visible completion and History plus the runner's
single-process/crash-delta checks; it does not claim the benchmark's per-take telemetry matrix.

## Instruments profiles

```sh
# CPU/signpost profile (default)
scripts/macos_test.sh profile custom:speed:

# CPU + Allocations + VM Tracker + signposts (keeps its raw trace by default)
scripts/macos_test.sh profile --kind memory custom:speed:

# Explicit diagnostic exception: retain a CPU profile's raw Instruments document.
scripts/macos_test.sh profile --keep-trace custom:speed:
```

The memory profile captures one cold long take so Allocations/VM Tracker include model-load and
sustained-generation peaks. It uses Apple's Allocations template, which contains both memory tracks
with automatic VM snapshots disabled; standalone VM Tracker auto-snapshots suspend the target and
would legitimately blind its 500 ms sampler. Publication verifies that setting from the captured
trace and still enforces the unobserved-gap gate unmodified. The default 180-second safety
cap accommodates a cold long take, while target exit ends recording early. `scripts/macos_test.sh
memory` owns the repeated retained-growth qualification.

Both commands build the exact CLI, suspend one owned process, attach Instruments to that exact PID,
resume it only after xctrace reports recording, and validate the exported trace table of contents.
The memory lane enables verbose per-sample telemetry and remains PASS-only. Headless CLI profiles
report the owning engine process; UI benchmarks merge the app and engine samples of their one
process into one series.
The tracer stage requires at least 5 GiB free for CPU profiles and 15 GiB for memory profiles before
it launches the target. The prerequisite CLI build uses the shared 8 GiB development-build floor,
so a complete CPU-profile command effectively requires 8 GiB; memory remains 15 GiB. After
successful trace validation and history publication, a CPU profile's raw trace is
deleted by default; the record retains its digest, capture settings, extracted summary, original
ephemeral path, and retention status. `--keep-trace` is the explicit diagnostic exception. A memory
profile keeps its raw trace by default (`keptByDefault`, several GB; prune it by hand), because
xctrace cannot export its allocation and VM tables and the trace is its only memory evidence. A
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
the maximum positive growth must stay at or below 5% of physical RAM. `retained-memory-v2` (MLX
active growth at the end of each take) is reported beside it and stays uncalibrated, gating nothing,
until a consented run sets its bounds (`telemetry-and-benchmarking.md`). Intended cross-mode model
residency is diagnostic and is not mislabeled as a leak. A PASS creates a
`memory-qualification` record; a generation, memory, QC, or retention failure leaves only local
artifacts.

## Generated-output ownership

macOS -Onone development builds and deterministic tests reuse `build/cache/xcode/macos/`; the optimized
CLI and every macOS UI lane (compiled at -O) reuse `build/cache/xcode/macos-optimized/`, so an optimized
build never recompiles the -Onone arena; shared package checkouts live
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
