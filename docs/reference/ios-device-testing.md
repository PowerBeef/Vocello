---
status: active
owner: ios
summary: iOS physical-device testing — deterministic compile lanes, explicit on-device acceptance (smoke/benchmark/perf with the frame-health protocol), headless diagnostics, and burn-in safety.
sourceOfTruth:
  - scripts/ios_device.sh
  - scripts/ui_test.sh
  - scripts/check_ios_ui_perf.py
  - scripts/check_ios_model_management.py
---
# iOS physical-device testing

Vocello's iOS runtime and UI acceptance run on a paired physical iPhone. Simulator build, launch,
and UI automation are unsupported. XCUITest is the sole autonomous iOS app UI driver.

## Ordinary development

```sh
./scripts/check_project_inputs.sh
./scripts/build_foundation_targets.sh ios
```

The generic physical-device SDK compile builds both the app and the standalone
`VocelloiOSLogicTests` policy bundle without executing XCTest. It requires no connected phone and is
sufficient for routine commits, pushes, pull requests, ordinary merges, and ordinary CI. Missing
models, a phone, or UI results must not block preserving and sharing development work.

### Host toolchain prerequisite

`generic/platform=iOS` does not launch or execute a Simulator. Current Xcode 26 toolchains still
require the selected Xcode installation to expose usable iOS Platform Support and a compatible iOS
runtime component before that physical-device SDK destination becomes eligible. An `iphoneos`
entry in `xcodebuild -showsdks` is not sufficient proof. Repository build routes run this read-only
check before package resolution or compilation:

```sh
python3 scripts/lib/ios_platform_preflight.py check
```

If it reports `blocked-toolchain-component`, install or enable the matching iOS component in
Xcode → Settings → Components. Apple also exposes the attended command
`xcodebuild -downloadPlatform iOS -architectureVariant arm64`. This can be a multi-gigabyte
operation, so repository scripts never invoke it automatically. Installing the component is a host
toolchain repair; it does not authorize Simulator builds, launches, tests, or UI automation. See
[Apple's additional Xcode components guide](https://developer.apple.com/documentation/xcode/downloading-and-installing-additional-xcode-components).

That app-host-free bundle covers catalog and delivery-ledger validation, memory policy,
cancellation semantics, app-support path gating, and privacy-safe diagnostics at compile time. Xcode
26 reports tool-hosted testing as unavailable for physical-device destinations, so the repository
does not expose a device execution command for this target. Physical runtime assurance remains in
the existing headless diagnostics and genuine XCUITest lanes; no Simulator substitute is used.

## Device preparation

```sh
scripts/ios_device.sh preflight
scripts/ios_device.sh device-state
```

`preflight` and `device-state` verify the paired CoreDevice identity and reachability; preflight
also checks the selected Xcode's iOS Platform Support, signing, and the existing app-build and dSYM
readiness. `device-state` treats
reachability as its only blocker. The XCUITest runner independently rejects a phone that
CoreDevice reports as locked before invoking `xcodebuild`. Install or repair iOS models through the
visible Settings → Voice models section; neither device scripts nor normal UI tests install them.
The sole exception is the separately selected `scripts/ui_test.sh ios model-download` lifecycle
diagnostic, which uses an isolated app-support root and is never part of smoke or benchmark.

## Explicit XCUITest lanes

```sh
scripts/ui_test.sh ios smoke
scripts/ui_test.sh ios benchmark
# Filtered benchmark example:
scripts/ui_test.sh ios benchmark --modes custom --lengths short --warm 1 --label "focused"

# UI-performance frame-health lane (ios-ui-2026-08):
scripts/ui_test.sh ios perf [--label RUN_ID]

# Explicit isolated background-transfer diagnostics, not a normal UI lane:
scripts/ui_test.sh ios model-download --scenario diagnose
scripts/ui_test.sh ios model-download --scenario queue
scripts/ui_test.sh ios model-download --scenario acceptance
scripts/ui_test.sh ios model-download --scenario soak --iterations 3
scripts/ui_test.sh ios model-download --scenario recover
```

The iPhone matrix keeps the shared short/medium/long ordering; its long script is the historical
150-character text from the era of the 150-character limit, kept fixed for benchmark-history
comparability (the shipping single-take limit is 900, memory-qualified 2026-07-24). macOS retains
the extended >220-character long corpus; the iPhone lane never bypasses the user-facing limit.

| Lane | Scope |
| --- | --- |
| Smoke | Two journeys. Standard: exact app launch, Studio mode and tab navigation, visible model and clone-reference readiness, one visible user cancellation, one run-scoped critical-memory cancellation with cancel-before-unload diagnostics, post-pressure engine reuse, no cancelled History rows, and one real completed Custom History row. Long-form: a >2,000-character script routes to a project, streams every segment with live narration, surfaces the joined output in the inline player, and History shows search-flattened rows plus the grouped project with its expandable per-segment map |
| Benchmark | Ordered, configurable Studio matrix with pulled telemetry, readable audio, audio QC, thermal and timing evidence; the default is exactly 29 takes |
| Model delivery | Fixed test-owned root normalized through visible state-appropriate controls. `diagnose` covers Custom cancel/restart/process adoption/Ready/remove; `queue` proves independent active/queued cancellation; `acceptance` adds Design/Clone shared-component reuse and all-model removal; `soak` repeats the lifecycle; `recover` inspects and visibly clears retained failure state without starting a transfer. Every transfer records exact logical bytes, milestone row/bar screenshots, phase activity, action exclusivity, five-minute advancement bounds, correlated delivery events, and exact canonical-state preservation |
| Perf | Nine frame-health scenarios (`Tests/VocelloiOSUITests/VocelloiOSPerfUITests.swift`), each a fresh app launch with the in-app `CADisplayLink` probe pinned to the app's 60 Hz cap and one marked wall-clock window; `scripts/check_ios_ui_perf.py` joins windows to the pulled 500 ms probe rows |

Every lane uses the paired physical-device destination. Tests use stable accessibility identifiers,
condition-based waits, XCTest activities, screenshots, and failure attachments. Coordinate tables,
OCR taps, alternate UI drivers, and fixed sleeps are not supported — the perf scenario file is the
one recorded exemption (`scripts/check_test_workflows.sh`): its paced sleeps ARE the measured
workload, and its sweep gestures anchor on the application root so deep per-event accessibility
re-queries stay out of the measured windows.

The model-delivery runner always exports the `.xcresult`, attachments, diagnostics journal,
delivery summaries, ledger copy, sanitized storage inventories, crash delta, and host diagnosis even
when XCTest fails. Determinate bar observations include raw and total bytes, expected and
accessibility fractions, visible copy, status, phase, action set, frames, and screenshot names.
`scripts/check_ios_model_management.py` identifies the first inconsistent layer and emits a timeline,
machine-readable diagnosis/summary, visual measurements, and a milestone contact sheet. A failed
isolated root remains available to the next `diagnose` or `recover` run; ordinary app data and
canonical model state are never used as the test root.

The smoke runner pulls its exact diagnostics and fails unless the one-shot event sequence is
`debug_force_critical_once` → `critical_memory_action` → typed `memory_pressure` cancellation →
`fullUnload`, followed by a successful generation from the same relaunched app process.

Benchmark accepts `--modes`, `--lengths`, `--warm`, and `--label`. Filters are explicit diagnostic
runs; invoking the command without filters is the canonical 29-take matrix on the tracked iPhone 17
Pro `iPhone18,1` profile. Dirty-source successes are exploratory even on that hardware.

### UI-performance lane (`ios perf`)

The probe writes `frames-<launchEpochMS>-<scenario>.jsonl` to the devicectl-pullable
`Library/Caches/Vocello/diagnostics/ui-perf/` tree; markers travel through the on-device test
runner's stdout into `xcodebuild.log`, so marker and probe share the device clock. The
`perf-validation` step pulls diagnostics and runs `scripts/check_ios_ui_perf.py`, which
fail-closes on a missing/duplicate scenario, probe coverage below 90% of a marked window,
non-monotonic blocks, and non-canonical hardware (run-scoped device manifest + live `devicectl`
inventory must resolve to the canonical iPhone profile). The 55–65 Hz median-block-cadence band
fail-closes on `ios-idle-baseline` only — the quiet sentinel where cadence isolates whether the
pinned 60 Hz link was honored (Low Power Mode, thermal caps, idle throttling); both Low Power
Mode off and nominal thermals are run preconditions. On interactive scenarios an out-of-band
cadence is recorded as a `uiperf.cadence:*` warning (`passedWithWarnings`), never a failure:
block cadence there conflates system re-pacing with the main-thread stalls the lane exists to
measure (the macOS history-scroll baseline of 456 ms/s hitch — ~33 Hz effective — is the
canonical example). Artifacts: `ui-perf-report.json` and `ui-perf-gate.txt` under the run
directory, probe JSONL under `diagnostics/ui-perf/`. **Copy
`ui-perf-report.json` out of the run directory after every counted baseline
run** — result retention keeps only the latest passing result per lane, so a
multi-run session otherwise loses its earlier reports (they remain
deterministically regenerable from the device's probe files and the captured
lane log, but copying is the protocol). Warn-only ceilings live in
`config/ui-perf-thresholds-ios.json` (IUI-6, derived from the three counted
sessions; a breach marks the scenario and run `passedWithWarnings`, never
failed), and on the canonical iPhone profile a PASS emits registry evidence
and publishes a platform-`ios` `ui-perf` record — the macOS UI-7 twin
([`ios-ui-refresh-2026-08.md`](ios-ui-refresh-2026-08.md)).

## Headless device diagnostics

`bench`, `lang-bench`, `speech-assets`, `profile`, `memory`, and the deliberate crash diagnostic launch
`IOSDeviceDiagnosticsRunner` through purpose-specific `QVOICE_IOS_*` environment contracts.
Generation lanes write `device-diagnostics-done.json`; `speech-assets` writes its distinct
`speech-assets-done.json` completion barrier. The runner never drives or inspects the app UI. Clone
diagnostics require the exact prepared voice ID, and `--memory-profile` can apply a
smaller-device memory budget while retaining the connected phone's real GPU and thermals. These
operations are diagnostics, not a second frontend acceptance stack.

`speech-assets` is an explicit, non-generation bootstrap for the language-output prerequisite. It
resolves `de_DE`, `es_419`, `ja_JP`, and `zh_CN` through
`DictationTranscriber.supportedLocale(equivalentTo:)`, creates one module per resolved locale,
checks each status, performs one combined AssetInventory download/install request, and then requires
every module to report installed. Its local sentinel also records a fresh
`SFSpeechRecognizer.supportsOnDeviceRecognition` read and Vocello's deterministic legacy locale
selection. Modern installation and legacy readiness are separate verdicts; the command publishes no
benchmark history and performs no generation.

`lang-bench` declares an immutable one-based run plan before generation and passes an explicit
UInt64 seed plus sampling variation to every take. Its schema-v2 sentinel is published last and
binds the resolved language, prompt-assembly digest, exact output-WAV digest/metadata, generation
telemetry identity, and structured three-pass on-device Speech evidence. The collector retains only
those plan-selected rows and files. Corpus v2 requires at least 15 normalized words for alphabetic
scripts and 24 normalized characters for Chinese/Japanese, freezes the Custom speaker and shared
Design instruction in the plan, and sends the known language explicitly for Design. Custom pinned/Auto
pairs share the exact fixture and prove language-hint equivalence rather than independent audio
quality; three transcription passes prove recognizer reproducibility rather than statistical
independence. `--diagnostic-cohort` runs the fixed 15-take English-Design and
French pinned/Auto regression cohort without retries or history publication. Language acceptance is
fully autonomous; listening is optional annotation only. Its primary accuracy metric is WER for
word-delimited languages and CER for Chinese/Japanese, both at the versioned 0.15 threshold; the
Python validator and publisher recompute the edit evidence from the corpus rather than trusting the
app's aggregate score.

## Model readiness

Before generation, XCUITest visibly requires Custom, Design, and Clone Speed to report ready,
Generate to be enabled, and the required clone voice to exist. iOS has no command-line model
ensure/install path: repair missing models in the visible Settings → Voice models section, then restart the
UI lane. Device scripts retain headless engine diagnostics, but normal acceptance never substitutes
a headless inventory for the visible Settings state.

When a device wipe removes the benchmark clone voice,
`scripts/ios_device.sh enroll-clone-fixture --wav A_warm_elderly_woman.wav --transcript A_warm_elderly_woman.txt`
re-enrolls it through the headless diagnostics runner. (The visible Files-import flow returned
2026-08-15 and has its own opt-in `scripts/ui_test.sh ios enroll-clone-fixture` UI lane; the
headless command remains the no-UI, hash-pinned wipe-recovery route.)
The command stages the exact WAV plus the mandatory `.txt` transcript sidecar (from the macOS
fixture store `~/Library/Application Support/QwenVoice-Debug/voices/`) into the app's Documents,
launches with `QVOICE_IOS_DEVICE_ENROLL_VOICE_NAME`, and validates the enrollment sentinel
(staged digests, voice ID, quality warnings). The runner deletes the staged inputs after a clean
enrollment. The command is opt-in and never runs in smoke, benchmark, CI, or release.

F-01 saved-voice lifecycle acceptance is separately opt-in:

```sh
scripts/ui_test.sh ios saved-voice-lifecycle
```

Before running it, stage `F01 Saved Voice Lifecycle.wav` and an optional matching `.txt` sidecar
in the app's Documents directory. The XCUITest uses only visible production controls to import the
throwaway reference, resolve a possible soft warning, preview it, hand it to Clone, confirm the
exact named deletion, verify the row disappears, and verify the matching Studio draft is cleared.
It does not run in smoke, benchmark, CI, or release.

**Bench spec syntax:** the `ios_device.sh bench` positional argument is the full
`mode:variant:text` spec; a bare argument is treated as *text* (wrapped as
`custom:speed:<arg>`), so `bench custom` generates the literal word "custom" — a
six-character prompt that mandatory Fast QC rejects at generation startup. Always pass
the full spec; a startup failure with healthy memory and a tiny `promptCharacters` in
the sentinel is this mistake.

## Deterministic evidence retained

The benchmark result is joined with exact device/app identity, current-run engine and app telemetry,
History/database correlation, readable WAV validation, audio QC, crash deltas, thermal state,
matrix ordering, and take counts. The app mints the generation UUID across Custom, Design, and Clone
and writes its frontend row durably before only the matching run rows/verbose sidecars are mirrored.
The fixed 150-character case remains explicitly `long`; no prompt-length inference is used.
Smoke asserts visible active-cancellation recovery, absence of a cancelled History row, subsequent
completion and History persistence, plus the runner's device/crash checks. It does not claim the
benchmark's per-take telemetry matrix or synthesize an operating-system pressure event. Headless `bench`, `lang-bench`, `profile`,
`crashes`, logs, and console operations remain supported physical-device diagnostics.

Profile commands launch or attach to the exact target PID, record CPU Profiler and `os_signpost`
rows in one trace, require a successful tracer exit, and verify the trace using exported
table-of-contents data plus non-empty performance-row and correlated-signpost exports. Traces remain local; a successful profile
publishes only its digest, capture settings, CPU/data-row summary, and sanitized artifact reference as
an `instrument-profile` record. CoreDevice and Instruments use different runtime identifiers for the
same phone; the profile lane resolves the Instruments UDID from CoreDevice JSON and fails before
installing or launching the app unless `xcrun xctrace list devices` reports that phone in its online
`Devices` section. Tracer startup is bounded by xctrace's own `Starting recording` output rather than
the unreliable physical-device Darwin-notification callback. Any target suspended by a later failure
is terminated automatically.

For allocation and VM evidence, use the Instruments memory profile:

```sh
scripts/ios_device.sh profile --kind memory custom:speed:

# Retain the raw trace only when it must be reopened in Instruments.
scripts/ios_device.sh profile --kind memory --keep-trace custom:speed:
```

This keeps CPU Profiler and correlated `os_signpost` data while adding Allocations and VM Tracker in
the same exact-PID trace, and forces verbose run-scoped samples. New publishable device runs require
telemetry schema v8 and evidence manifest v2: exact start/periodic/boundary/stop sidecars, summary
agreement, zero capture failures, and at least 95% sampler coverage. Critical pressure, an app memory
warning/exit, `hardTrim`, or `fullUnload` fails publication; guarded pressure, `softTrim`, or 95–<100%
coverage is explicit warning evidence. The record retains footprint/resident start, end, delta, and
peak; compressed/GPU peaks; minimum headroom and peak process-budget utilization; sampler coverage;
and pressure/trim/warning/exit counters. iPhone admission is also strict: physical footprint ≥5.2
GB, minimum headroom <384 MB, or Metal working-set ratio ≥0.8 fails; footprint ≥4.5 GB or
headroom <768 MB warns. The lane requires 15 GiB free before device launch. After validation and
history publication, the raw trace is discarded by default while its digest/settings/extracted
summary and retention status remain in compact evidence; `--keep-trace` opts into local retention.
Raw traces and sample rows remain untracked.

Device builds require 10 GiB of host free space before compilation. Language, generation benchmark,
memory, clone-conditioning, and gate lanes require 15 GiB; UI smoke, benchmark, and isolated model
download require 12, 15, and 18 GiB respectively. These host-side checks run before adding another
cache/result tree and do not contact, pair, or alter the phone. The exact-PID profile lane retains
its separate tracer-stage 5/15 GiB CPU/memory check. Because every profile rebuilds the exact app,
the full CPU-profile command is also subject to the 10 GiB device-build floor; memory remains
15 GiB.

Retained-memory qualification is separate from Instruments:

```sh
scripts/ios_device.sh memory --voice-id <exact-prepared-saved-voice-id> --label retained-check
```

One persistent app/engine process executes three medium Speed takes for Custom, then Design, then
Clone (nine total). The terminal sentinel is written only after all output/QC/telemetry proofs pass.
Policy `retained-memory-v1` compares first-to-last retained-take footprint growth within each mode and allows
at most 5% of physical RAM; cross-mode residency is diagnostic because different models are
intentionally loaded. A PASS creates `memory-qualification`, while any generation, memory,
retention, output, or crash failure leaves tracked history unchanged.

### Clone-conditioning semantic acceptance

```sh
scripts/ios_device.sh clone-conditioning --label focused-clone-proof
```

This compile-gated physical-device lane runs exactly two Clone Speed generations in one app/engine
process. It verifies the canonical saved Voice Design reference and transcript digests, then uses an
exact purpose-owned copy without a `.txt` sidecar or prepared voice ID for the x-vector-only take.
Both takes must pass typed conditioning flags, distinct prompt identities, strict output/ASR,
telemetry-v8 memory coverage, app/engine correlation, crash delta, and interruption checks. The
runner removes the audio-only scratch copy before PASS. It writes only local untracked validation
evidence and never creates or repairs benchmark history; XCUITest remains the visible UI proof.

MetricKit supplies a complementary delayed field view, not per-take benchmark attribution. After a
normal explicit pull, summarize only the already-local privacy-reduced aggregate with:

```sh
scripts/ios_device.sh memory-field-report build/artifacts/diagnostics/ios
```

The command never resolves, wakes, pulls from, or otherwise contacts an iPhone. MetricKit delivery
may take a day or longer; no payload reports `notYetDelivered` with success status and cannot qualify
or retroactively fail a benchmark run.

The validator atomically writes an untracked `benchmark-evidence.json` with the exact ordered
generation IDs/cells and verdicts. A PASS publishes one privacy-safe record under
`benchmarks/runs/ui-generation/` and regenerates `benchmarks/HISTORY.md`. Raw pulled JSONL, WAVs,
screenshots, traces, and `.xcresult` stay untracked; publication never stages, commits, or pushes.

Physical-iPhone acceptance of telemetry v8/evidence v2 is complete for the clean canonical
[29-take UI matrix](../../benchmarks/runs/ui-generation/ios-xcui-benchmark-20260716-184106-48e3a3a6.json),
[retained-memory qualification](../../benchmarks/runs/memory-qualification/ios-memory-qualification-20260714-112536-32554d95.json),
and the exact-PID [memory profile](../../benchmarks/runs/instrument-profile/ios-memory-profile-20260714-112759-9a573224.json).
Each record proves only its exact source, toolchain, model, and hardware identities; repository
contract tests and Simulator results never substitute for fresh physical-device evidence after a
relevant change.

## Generated-output ownership

Physical-device development and UI lanes reuse only `build/cache/xcode/ios-device/`; Xcode package
checkouts are shared under `build/cache/xcode/source-packages/`. Pulled diagnostics, UI results,
profiles, gates, and current UUID-matched symbols live under `build/artifacts/`, never inside the
incremental cache. Archive/export products live only under `build/dist/ios/`. Local release
DerivedData is isolated under `build/scratch/derived-data/release-ios/`; CI uses its
own `build/scratch/derived-data/ci/ios-archive/` leaf. See the authoritative owner/lifetime table in
[`privacy-storage.md`](privacy-storage.md).

## Release boundary

An iOS archive/TestFlight candidate uses deterministic signing, entitlement, catalog, archive, and
artifact checks. Physical-device smoke and benchmark results are independent frontend QA artifacts
and never an archive, upload, or Git-publishing prerequisite.

See also [`testing-runbook.md`](testing-runbook.md) and
[`benchmarking-procedure.md`](benchmarking-procedure.md).
