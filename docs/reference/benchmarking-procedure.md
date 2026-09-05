---
status: active
owner: release-qa
reviewed: 2026-08-29
summary: Operator runbook for performance and quality benchmarks — when to bench, the macOS CLI/app-XPC and iOS device paths, expected artifacts, and how to read results.
sourceOfTruth:
  - scripts/macos_test.sh
  - scripts/ios_device.sh
  - scripts/ui_test.sh
---
# Benchmarking procedure — operator runbook

Step-by-step guide for running Vocello performance and quality benchmarks on **macOS**
(CLI and app/XPC) and **iOS** (physical-device UI and headless diagnostics). This document covers **when** to bench,
**how** to drive each platform path, **what** artifacts to expect, and **how** to read results.

For telemetry schema, record fields, and MLX timing semantics, see
[`telemetry-and-benchmarking.md`](telemetry-and-benchmarking.md). For CLI flags, see
[`cli.md`](cli.md) §bench.

If anything here disagrees with the code, the code wins — fix this file.

---

## 1. Purpose and principles

### When to run a benchmark

Run a benchmark when you change anything that can affect **decode throughput**, **memory
peaks**, **first-chunk latency**, or **audio quality**:

- MLX / owned Qwen3-TTS core runtime or Mimi codec
- Memory policy, streaming interval, idle-unload, XPC lifecycle
- Model load path, prewarm, clone conditioning
- Before explicitly promoting engine-adjacent work or cutting a macOS/iOS release

Benchmarks that require models, a device, or XCUITest are not prerequisites for a
commit, push, pull request, ordinary merge, ordinary CI run, or release package. They remain useful
promotion and release-QA evidence when explicitly requested.

### What “good” means

A benchmark pass requires **all** of the following:

| Gate | Criterion |
|------|-----------|
| **audioQC** | Publication accepts `pass` or `warn`; promotion requires `pass` in every required cell. Any `fail` blocks both. |
| **RTF** | `derivedMetrics.audioSecondsPerWallSecond` reviewed against the nearest compatible clean record in generated [`benchmarks/HISTORY.md`](../../benchmarks/HISTORY.md). |
| **Memory** | No rising `physFoot` peak or non-zero `hardTrim` in `trims` on floor-tier runs. |
| **Automated output proof** | Fixed-seed cohort, exact WAV identity, and applicable locale-locked ASR/prosody gates pass. Human listening is optional annotation and is never inferred. |

**RTF > 1** means faster than realtime (more audio seconds produced per wall second).

### Design constraints

1. **Primary backend driver is headless** — `vocello bench` drives the matrix in-process with exact
   cold/warm control. **`scripts/ui_test.sh macos benchmark`** is the supplementary XPC integration net (§4.10).
2. **Telemetry is runtime-gated** — identical code in Release; off unless debug env/toggle/handshake.
3. **No CI execution gate** — model-dependent benchmarks are local and explicitly requested. CI validates the compact registry and reproducible index but does not run models, devices, XCUITest, or Instruments.
4. **Lazy MLX caveat** — decode breakdown columns measure Swift wall-clock around lazy graph
   ops, not per-stage GPU compute. Use Instruments signposts for GPU attribution (§6.3).
5. **PASS-only publication** — a successful repository benchmark publishes one allowlisted JSON
   record and regenerates `HISTORY.md`. Failed or incomplete runs leave tracked history unchanged;
   raw telemetry, audio, screenshots, traces, and result bundles remain untracked.

---

## 2. Platform topology

Three hosts write telemetry; only some layers exist per path:

```text
                    CLI (vocello bench)     macOS app + XPC        iOS app (in-process)
                    ───────────────────     ───────────────        ────────────────────
Engine row          yes                     yes                    yes
Engine-service row  no                      yes (XPC transport)    no
App row             no                      yes (UI timings)       yes (UI timings)
Required join        engine                  app + service + engine app + engine
TTFC column         — (no app process)      yes (submit→chunk)     yes
UI heartbeat        —                       yes                    yes
```

| Path | Driver | Engine topology | Best for |
|------|--------|-----------------|----------|
| **CLI** | `./build/vocello bench` | In-process `MLXTTSEngine` | Deterministic RTF/decode/memory matrix; release QA step 3 |
| **macOS UI** | App + `QwenVoiceEngineService` XPC | Out-of-process engine | Submit-to-first-chunk, playback scheduling, delayed-heartbeat, and XPC transport evidence; UI smoke tests |
| **macOS XPC UI benchmark** | `scripts/ui_test.sh macos benchmark` | Out-of-process engine | Full UI matrix through real app + XPC; merged 3-layer telemetry |
| **macOS profile** | `scripts/macos_test.sh profile --kind cpu|memory` | In-process via CLI inside exact-PID trace | CPU/signpost or allocation/VM validation |
| **iOS device** | `scripts/ios_device.sh bench` | In-process | iPhone tier, Jetsam, on-device RTF (headless diagnostics, single take) |
| **iOS UI benchmark** | `scripts/ui_test.sh ios benchmark` | In-process | Full UI matrix through XCUITest on the paired physical iPhone; telemetry gated per take |
| **macOS UI frame health** | `scripts/ui_test.sh macos perf` | No engine claims (UI-only) | Nine scripted SwiftUI scenarios with the in-app frame probe; warn-only ceilings; canonical-hardware runs publish `ui-perf` registry records ([`macos-ui-refresh-2026-08.md`](macos-ui-refresh-2026-08.md)) |
| **iOS UI frame health** | `scripts/ui_test.sh ios perf` | No engine claims (UI-only) | Nine scripted scenarios on the paired physical iPhone with the pinned-60 Hz in-app probe; `check_ios_ui_perf.py` structural + canonical-hardware gate with warn-only ceilings from [`config/ui-perf-thresholds-ios.json`](../../config/ui-perf-thresholds-ios.json); canonical-iPhone runs publish platform-`ios` `ui-perf` registry records (IUI-6, [`ios-ui-refresh-2026-08.md`](ios-ui-refresh-2026-08.md)) |

**Important:** CLI bench numbers are **not** identical to macOS XPC UI numbers. Compare like with
like (CLI vs CLI, UI vs UI). Use CLI for backend optimization; use UI/XPC for integration regressions.

### Canonical hardware profiles

Native history is anchored to [`benchmarks/hardware-profiles.json`](../../benchmarks/hardware-profiles.json):

| Platform | Profile | Hardware |
|---|---|---|
| macOS | `mac-mini-m2-8gb` | Mac mini `Mac14,3`, Apple M2, 8 GB |
| iOS | `iphone-17-pro` | iPhone 17 Pro `iPhone18,1` |

Records also capture current OS build, thermal/low-power state, sanitized transport, toolchain,
executables, input/model fingerprints, and source state. A dirty success is `exploratory`, not a
canonical trend point. Profiles and forced-memory-class diagnostics are not compared with normal
timing records.

---

## 3. Preflight checklist

Run before any benchmark session:

### Build and CLI

```sh
./scripts/build.sh cli-optimized # produces the hash-bound -O build/vocello used by benchmarks
./scripts/check_project_inputs.sh
```

`scripts/macos_test.sh` uses this optimized route for every CLI-backed benchmark and profile
lane. The publisher reads the adjacent build-provenance sidecar, verifies that its executable
SHA-256 matches the exact `vocello` bytes, and rejects publication unless the producer is
`scripts/build.sh cli-optimized` with optimization identity `-O`. The ordinary `build.sh cli`
route remains useful for development but cannot authorize macOS engine performance evidence.

### Models and clone fixture (macOS)

```sh
scripts/macos_test.sh models ensure
```

This installs (or symlinks into debug context):

- `pro_custom_speed`, `pro_design_speed`, `pro_clone_speed` (~6.0 GB one-time if none installed)
- Clone voice `A_warm_elderly_woman`, enrolled from a 10–20 second, transcript-backed Voice
  Design reference with a distinctive mature feminine alto. `models ensure` replaces the retired
  Custom/Aiden-derived short fixture when it detects that stale transcript.

Set `QVOICE_REQUIRE_TEST_MODELS=1` is automatic on script paths; bare `xcodebuild` may skip tests.

### Environment hygiene

| Check | Action |
|-------|--------|
| Quiet machine | Quit heavy apps; watch thermals (see §6.4). |
| Single Vocello session | Quit any separately installed Vocello first. The XCUITest runner verifies exact executable paths and signals only its own Release products. |
| Debug data dir | `QWENVOICE_DEBUG=1` → `~/Library/Application Support/QwenVoice-Debug/` |
| Floor-tier simulation | `QWENVOICE_FORCE_MEMORY_CLASS=floor_8gb_mac` (propagates to engine via handshake) |
| Suppress proactive warm | `QWENVOICE_SUPPRESS_WARMUP=1` for accurate Custom/Design **cold** rows in UI runs |
| Disable publication marking | `QWENVOICE_MARKING=off` disables both publication marks only in a repository-built internal diagnostics binary with the master gate enabled. It exists for A/B isolation of the marking pass, is unavailable in distributed builds, and must never be set for canonical records. |

**Publication byte-identity discontinuity (CP-2, 2026-08).** Published WAVs carry the
Article 50 marking pass: an imperceptible AudioSeal watermark embedded in the samples plus a
`LIST`/`INFO` provenance chunk appended after the data chunk. Both marks flip together, so
fixed-seed exact-WAV identity comparisons are valid only within one marking era — a pre-marking
reference WAV will never byte-match a marked take of the identical seed, and a digest mismatch
across the flip is expected, not a regression. Compare like with like: same build, same
`QWENVOICE_MARKING` state.

### iOS device

- Paired physical iPhone (never Simulator for real engine)
- Speed models visibly verified in Settings through XCUITest
- `scripts/ios_device.sh preflight` before bench/gate
- Physical-device playbook: [`ios-device-testing.md`](ios-device-testing.md)

---

## 4. Standard workflows

All `--label` values are opaque privacy-safe identifiers matching
`[A-Za-z0-9][A-Za-z0-9._-]{0,95}`. Use a short slug such as `release-QA`; never put a prompt,
voice description, username, path, or free-form note in a label.

### 4.1 Release QA engine net (macOS)

From [`macos-release-qa.md`](macos-release-qa.md) step 3 — run when `Sources/` engine code changed:

```sh
scripts/macos_test.sh models ensure

QWENVOICE_DEBUG=1 ./build/vocello bench \
  --modes custom,design,clone \
  --variants speed \
  --lengths short,medium,long \
  --warm 3 \
  --voice A_warm_elderly_woman \
  --label "release-QA"
```

Gate: all required cells `QC=pass`; RTF within noise of `HISTORY.md`; fixed-seed identity and every
applicable automated language/prosody gate pass. A `warn` may remain in history but is not an
engine-promotion pass.

### 4.2 Quick multi-mode smoke (Speed, short matrix)

```sh
QWENVOICE_DEBUG=1 ./build/vocello bench \
  --modes custom,design,clone \
  --variants speed \
  --lengths short,medium \
  --warm 1 \
  --label "my-change" \
  --force
```

`--force` clears diagnostics before run (default without `--keep`).

### 4.3 Full 6-cell matrix (Speed + Quality)

Default CLI includes both variants; fixture installs **Speed only**:

```sh
# Option A: Speed only (matches models ensure)
QWENVOICE_DEBUG=1 ./build/vocello bench \
  --variants speed --lengths short,medium,long --warm 3 --label "speed-matrix"

# Option B: include Quality — ensure Quality weights installed first (~12–18 GB peak disk)
QWENVOICE_DEBUG=1 ./build/vocello bench \
  --variants speed,quality --lengths short,medium,long --warm 3 --label "full-matrix"
```

**The ordinary Clone matrix is warm-only by design.** The CLI awaits explicit model loading
before its measured Clone takes, without generating an extra warm-up take. `warmState` means
model residency, not that every conditioning/decoder cache is hot. New engine records require
the result label to agree with engine telemetry and any backend/receipt warm-state evidence;
missing or contradictory state blocks publication. The separate retained-memory protocol below
does not preload Clone: its first `retained#0` take remains cold. Historical records are immutable.

### 4.4 Floor-tier forced run

Exercise constrained-tier code paths on any Mac:

```sh
QWENVOICE_DEBUG=1 \
  QWENVOICE_FORCE_MEMORY_CLASS=floor_8gb_mac \
  QWENVOICE_SUPPRESS_WARMUP=1 \
  ./build/vocello bench \
  --modes custom --variants speed --lengths medium --warm 3 \
  --label "floor-tier"
```

Summarizer header shows `tier: floor_8gb_mac ⚠ forced`.

### 4.5 Memory-pressure exercise

While a generation is running on forced floor tier:

```sh
sudo memory_pressure -S -l warn    # or: -S -l critical
```

Then summarize and confirm non-zero `trims` / `memory_pressure` stage marks.

### 4.6 Delivery / prosody cells

> Full delivery-measurement reference — tools, multi-seed sweep protocol,
> instruction-receipt provenance, statistics semantics, and the DP results
> ledger: [`delivery-harness.md`](delivery-harness.md).

```sh
QWENVOICE_DEBUG=1 ./build/vocello bench \
  --modes custom,design \
  --variants speed \
  --lengths medium \
  --warm 1 \
  --delivery happy,calm,whisper \
  --prosody-profile path/to/profile.json \
  --label "delivery-audit"
```

Adds instruct-bearing warm takes. The prosody analyzer reads the current run's immutable
`bench-results.json` allowlist before the final summary, so older WAVs left by `--keep` cannot enter
the delivery comparison; the summarizer then prints that current prosody block. Every delivery take
also receives the per-preset adherence verdict (`deliveryGate` beside `qualityGate` in
`bench-prosody.json`) and the run composes canonical-depth registry verdicts across all seven gates
(`bench-quality-composed.json`).

### 4.6b Fidelity lanes (engine/artifact promotion battery)

Every engine or artifact promotion runs the three fidelity lanes introduced with the
2026-08-01 delivery-fidelity program (findings:
[`delivery-fidelity-report-2026-08-01.md`](delivery-fidelity-report-2026-08-01.md);
tracks: [`delivery-remediation-plan-2026-08.md`](delivery-remediation-plan-2026-08.md)):

```sh
# 1. Preset adherence — paired delivery matrix; canonical composed verdicts.
QWENVOICE_DEBUG=1 ./build/vocello bench --modes custom --variants speed --lengths medium \
  --warm 1 --delivery happy.strong,calm.normal,whisper.normal --seed <fixed> --label "promo-delivery"

# 2. Neutral consistency — N same-preset fixed-seed takes through the cohort gate.
python3 scripts/delivery_quality_gate.py --cohort take1.wav … takeN.wav

# 3. Clone fidelity — identity + prosody + SER layers vs the fixture voice.
.venv/bin/python3 scripts/clone_fidelity_lane.py --voice A_warm_elderly_woman
```

The delivery gate and cohort bounds are calibrated, digest-chained profile values
(`scripts/prosody_profile.py`); adherence/cohort regressions beyond them are promotion
findings, not waivable annotations. The clone lane and SER column stay advisory.

### 4.7 iOS on-device bench

```sh
scripts/ios_device.sh bench custom:speed: \
  --label "ios-device-bench"
```

Optional physical-device memory-profile diagnostic:

```sh
scripts/ios_device.sh bench --memory-profile iphone15pro custom:speed:
```

Pulls diagnostics from the device, runs the summarizer, and exits non-zero unless
`device-diagnostics-done.json` reports success.

### 4.7b iOS UI benchmark (Studio matrix — XCUITest)

This uses the same 29-take matrix semantics as the macOS UI benchmark. The shared lane policy is
in [`testing-runbook.md`](testing-runbook.md).

```sh
scripts/ios_device.sh device-state
# Verify Custom, Design, and Clone Speed visibly in Settings, then run the matrix.
scripts/ui_test.sh ios benchmark

# Targeted diagnostic example (not the full-matrix acceptance result):
scripts/ui_test.sh ios benchmark --modes custom --lengths short --warm 1 --label "focused"
```

For iPhone UI automation, the `long` cell is the historical 150-character text chosen when the
on-device limit was 150; the shipping limit is 900 (memory-qualified 2026-07-24), but the cell
text stays fixed so device benchmark history remains comparable. The extended >220-character
corpus below remains the macOS/CLI definition.

Requires a paired, unlocked physical iPhone and a valid XCUITest destination. Simulator is not
supported. The benchmark accepts `--modes`, `--lengths`, `--warm`, and `--label`; without filters it
runs the canonical 29-take matrix.

Artifacts are the `.xcresult` bundle, exported XCTest screenshots, run-scoped engine/app telemetry,
and the atomic `benchmark-evidence.json`. The validator maps the test-owned ordered matrix directly
to the matching generation IDs; the fixed 150-character case remains explicitly `long`. Test assertions,
the crash delta, and the deterministic telemetry/audio validators form the gate.

The Instruments profile is a separate headless lane, not an attachment to the XCUITest matrix:

```sh
scripts/ios_device.sh profile
scripts/ios_device.sh profile --kind memory
```

It builds and installs the diagnostic app, launches one headless generation suspended, attaches
CPU Profiler plus `os_signpost` to that exact PID, resumes it, waits for the success sentinel, pulls
its run-scoped diagnostics, and publishes an independent `instrument-profile` record. The memory
kind additionally records Allocations and VM Tracker in the same trace. Run it before
or after a UI benchmark when profiling evidence is useful; do not treat its trace, generation, or
history record as part of the UI benchmark's `.xcresult` or evidence manifest.

Retained-memory qualification is a separate one-process nine-take lane:

```sh
scripts/ios_device.sh memory --voice-id <exact-prepared-saved-voice-id> --label retained-check
```

It runs three medium Speed takes each in fixed Custom→Design→Clone order without relaunching the
app. `retained-memory-v1` compares first-to-last retained-take footprint growth within each mode against a 5%
of physical-RAM limit; cross-mode model residency is diagnostic. The terminal sentinel is atomic and
a PASS publishes `memory-qualification`, not `instrument-profile`.

Clone-conditioning semantics have a separate local acceptance command:

```sh
scripts/ios_device.sh clone-conditioning --label focused-clone-proof
```

It proves transcript-backed and genuine x-vector-only conditioning with the exact canonical
reference in one physical-iPhone process. It is intentionally not a timing matrix and never creates
a benchmark-history record; the compact validation and its raw telemetry/WAV evidence remain under
the untracked iOS artifact tree.

### 4.7c iOS benchmark ownership

The XCUITest benchmark lane validates the only supported UI matrix. For engine RTF without UI
friction, use the headless §4.7 `ios_device.sh bench` lane.

| Phase | Tool |
|-------|------|
| Independent trace capture | `scripts/ios_device.sh profile --kind cpu|memory` (separate headless generation/profile lane) |
| Trace analysis | Instruments / `xcrun xctrace`; optional `xcprof` on `PATH` |
| UI failure | `.xcresult` activities, failure diagnostics, and screenshot attachments |
| Crash post-mortem | Xcode Organizer; optional `xcsym` on `PATH` |

Use `$axiom-tools` for workflow selection. Physical-device setup is documented in
[`ios-device-testing.md`](ios-device-testing.md).

The iOS profile command resolves Instruments' UDID independently from CoreDevice's device ID and
stops before launching Vocello if the phone is listed under `Devices Offline`. Reconnect and unlock
the phone until `xcrun xctrace list devices` places it under `Devices`; CoreDevice reachability alone
is not sufficient evidence that Instruments can attach.

### 4.8 macOS Instruments profile (signpost validation)

```sh
QVOICE_MAC_PROFILE_DURATION=120 \
scripts/macos_test.sh profile custom:speed:

scripts/macos_test.sh profile --kind memory custom:speed:

# Only when the raw document must be reopened in Instruments:
scripts/macos_test.sh profile --kind memory --keep-trace custom:speed:
```

The macOS memory profile records one cold long take. This captures model-load plus sustained
allocation/VM peaks. The lane uses Apple's Allocations template for its Allocations and VM Tracker
tracks because that template disables automatic VM snapshots; adding standalone VM Tracker to a
Blank trace enables stop-the-world snapshots that create real holes in the target's 500 ms sampler.
Publication verifies the captured template setting and retains the strict 95% floor. The memory
profile's default 180-second safety cap is only a maximum; exact-target exit ends the recording
early. The separate `scripts/macos_test.sh memory` lane owns repeated retained growth.

Produces `build/artifacts/macos/profiles/<run-id>/<run-id>.trace` containing CPU Profiler samples and
`os_signpost` rows in one capture; the memory kind adds Allocations and VM Tracker. **In-process
only** — not the production XPC
path. The lane is PASS-only: a tracer failure, benchmark failure, invalid trace, or failed publication
returns nonzero without creating history. It retains only the newest raw failure per platform and
profile kind; older failures are compacted to small diagnostic summaries.
Explicitly pinned failures are never compacted. An unpinned compacted failure retains the required
retention marker and summary plus at most 8 MiB of allowlisted auxiliary diagnostics; individual
logs are capped at 1 MiB. Inspect and acknowledge a current failed capture by exact run ID:

```sh
python3 scripts/build_output_policy.py status
scripts/clean_build_caches.sh --compact-profile-failure <run-id> --dry-run
scripts/clean_build_caches.sh --compact-profile-failure <run-id>
```

The profiler launches or attaches to the exact target PID, requires a successful tracer exit, and
validates the trace through `xctrace export --toc`; there is no blind startup sleep. For XPC, attach
to the exact `QwenVoiceEngineService` PID while generating via UI. Traces remain untracked. On
success the registry retains the digest, settings, extracted summary, original ephemeral path, and
retention policy, then the runner removes the raw trace. Pass `--keep-trace` to retain it
explicitly. The same complete retention validation applies to schema-v2 records and quality-bearing
schema-v3 records; neither a schema downgrade nor omission of quality evidence is allowed to repair
a failed publication. Verify a source repair in a new run while preserving the original failure.
The tracer stage requires at least 5 GiB free for CPU profiles and 15 GiB for memory
profiles. The prerequisite macOS CLI build has an 8 GiB floor, so the complete CPU-profile command
effectively requires 8 GiB; memory remains 15 GiB because Allocations can emit tens of megabytes
per second.

The separate retained-memory lane is:

```sh
scripts/macos_test.sh memory --label retained-check
```

It runs Custom and Design as one cold plus three `retained#0...2` takes and Clone as three
`retained#0...2` takes, all Speed/medium in one CLI process. Each retained take keeps its actual
engine warm-state attribution. The same `retained-memory-v1` within-mode 5%-of-RAM policy applies;
an accepted run publishes `memory-qualification` and carries no trace.

### 4.9 UI-driven generation (macOS XPC)

Real generation through the macOS frontend is driven only by XCUITest. Deterministic completion
comes from matching History/WAV state and typed XPC/backend probes:

```sh
scripts/macos_test.sh models ensure
scripts/ui_test.sh macos smoke
```

This validates semantic frontend behavior plus the matching History/WAV/XPC/backend state. It is
not the primary RTF matrix driver.

### 4.10 macOS XPC UI benchmark (supplementary integration net)

**Primary backend regression remains `vocello bench` (§4.1).** The supplementary UI matrix is
driven by XCUITest through the real app + XPC service. Shared fixtures own the take definitions;
deterministic tooling owns timestamps, typed telemetry validation, and aggregation.

Telemetry rows stamp `notes.benchRunID`, `benchTakeIndex`, `benchCell`, and `benchWarmState` when
`QVOICE_MAC_BENCH_RUN_ID` is set. Completion requires matching generation, History, WAV, and typed
probe evidence; there are no hidden UI-test flush markers. The authoritative runner supplies the
matrix arguments, run ID, crash-delta assertion, and evidence-manifest path together. A direct
run-ID-only validator call is useful for diagnosis, but it is not a publishable benchmark contract:

```sh
# Diagnostic only: inspect the default matrix rows already present for one run ID.
python3 scripts/check_macos_xpc_bench.py ~/Library/Application\ Support/QwenVoice-Debug/diagnostics \
  --run-id macos-xcui-benchmark-YYYYMMDD-HHMMSS
```

For the strict contract, use `scripts/ui_test.sh macos benchmark`. Internally it passes the exact
`--modes`, `--lengths`, `--warm`, and `--label` values plus
`--evidence-manifest <run-artifact-dir>/benchmark-evidence.json --crash-delta-passed`. Never add the
crash-delta assertion to a manual command unless the caller actually captured and compared the
pre/post crash snapshots.

**One-time machine setup:** configure Xcode UI-test runner signing, build the native test host, and
install the required models.

See [`macos-testing.md`](macos-testing.md) for the complete lane contract.

**Full matrix:**

```sh
scripts/ui_test.sh macos benchmark

# Targeted diagnostic example (not the full-matrix acceptance result):
scripts/ui_test.sh macos benchmark --modes custom --lengths short --warm 1 --label "focused"
```

The test target consumes the canonical matrix and wraps every UI-driven generation in a named
XCTest activity. The command accepts `--modes`, `--lengths`, `--warm`, and `--label`; without filters
it runs exactly 29 takes. Cold Custom and Design cells are exact-path relaunches; a cell cannot
complete without its matching deterministic History/WAV assertion.

The benchmark `.xcresult`, smoke result, and seeded telemetry-overhead result are independent.
For telemetry/backend changes, run the model-dependent overhead parity lane directly when its
fixture is available; it does not consume or require UI evidence:

```sh
scripts/macos_test.sh telemetry-overhead
```

This counterbalances `off`, `lightweight`, and `verbose` through three deterministic order
rotations. Every rotation performs one warm-up and two measured takes per mode, yielding six
machine-readable measured takes per mode. It requires identical PCM, records thermal/load context,
and gates median RTF/TTFC at 5% (lightweight) and 10% (verbose) versus off. It never repairs or
downloads models; missing fixtures stop the run. Its verdict stays under `build/artifacts/macos/`
and is not
published to schema-v2 history: adding the in-process memory sampler to the `off` lane would change
the observer whose overhead is being measured. This fail-closed exception preserves the experiment
without admitting memory-incomplete records.

The UI runner performs the strict post-run gate and freezes its ordered evidence before summary and
publication. For post-mortem inspection only, the run-ID-only diagnostic command shown above can
re-read the default matrix; filtered runs require their exact matrix arguments and remain
non-authoritative without the runner-owned crash delta and evidence manifest.

| Phase | Tool |
|-------|------|
| Trace capture | `xctrace record --attach <exact-service-pid>` during a benchmark scenario |
| Trace analysis | Instruments/xctrace plus the relevant installed macOS performance skill |
| Logs / warm-admission | `scripts/macos_test.sh logs` and unified-log inspection |
| Crash post-mortem | `scripts/macos_test.sh crashes`, dSYMs, and standard symbolication |

Cold takes: app relaunch + `QWENVOICE_DEBUG=1` + `QWENVOICE_SUPPRESS_WARMUP=1` +
`QWENVOICE_BENCH_FORCE_COLD=1` (master-gated unload before generate). Warm takes stay in-session.

---

## 5. Matrix semantics

### Fixed corpus

Defined in `BenchMatrixSpec` (`Sources/QwenVoiceCore/BenchMatrixSpec.swift`; shared with
`BenchCommand` and XPC UI bench) — do not change without updating baselines:

| Bucket | Chars (approx) | Text role |
|--------|----------------|-----------|
| short | < 70 | One sentence |
| medium | 70–220 | Two sentences |
| long | > 220 | Extended narration |

`lenBucket()` in Swift and Python must agree (bench fails on corpus drift).

### Mode payloads

| Mode | Payload |
|------|---------|
| Built-in Voice | Default speaker + optional delivery |
| Voice Design | Fixed brief: *"A warm, calm middle-aged male narrator with a clear, measured pace."* |
| Voice Cloning | Saved voice `A_warm_elderly_woman` (or `--voice`) |

### Cold vs warm

| Mode | Cold sample | Warm samples |
|------|-------------|--------------|
| Custom | 1× (after `unloadModel`) | `--warm` × each length |
| Design | 1× | `--warm` × each length |
| Clone | **none** (warm-by-design) | `--warm` × each length |

CLI forces cold via awaited explicit unload before the cold take; unload/load failure stops the
matrix instead of inventing a warm/cold label. Ordinary Clone uses explicit model loading before
its first measurement, as described in §4.3. UI cold uses app relaunch +
`QWENVOICE_DEBUG=1` + `QWENVOICE_SUPPRESS_WARMUP=1` + `QWENVOICE_BENCH_FORCE_COLD=1`
(see §4.10).

### Streaming default

`vocello bench` streams by default (`--no-stream` for legacy quality-first accumulation).
Streaming populates `chunkTimeline`; non-streaming leaves it empty.

---

## 6. Reading results

### 6.1 Summarizer invocation

```sh
python3 scripts/summarize_generation_telemetry.py <DIAGNOSTICS_DIR> \
  --run-id <run-id> --evidence-manifest <artifact-dir>/benchmark-evidence.json \
  --label release-QA
```

For an authoritative benchmark, both selectors are mandatory: the run ID rejects unrelated rows,
and the evidence manifest supplies the exact ordered generation IDs/cells. Never summarize an
entire historical diagnostics directory as if it were one run. Ad-hoc diagnostics may still use
the default directory (`~/Library/Application Support/QwenVoice-Debug/diagnostics`) without being
eligible for registry publication.

Useful flags:

| Flag | Purpose |
|------|---------|
| `--show-variance` | IQR / outlier hints per cell |
| `--merged` | Cross-layer first-chunk table from `generations-merged.jsonl` |
| `--save-baseline PATH` | Write the current per-cell summary as a **JSON** baseline |
| `--compare-baseline BASELINE.json` | Fail-closed regression/coverage comparison against a **JSON** baseline from `--save-baseline` (exit 2 on >5% regression, removed/added cells, missing required metrics, or QC worsening; RTF **drop**, tok/s drop, TTFC/physFoot rise). Markdown snapshots cannot be fed to this flag — diff those with `git diff`. |
| `--baseline-migrations PATH` | Use a reviewed schema-v1 old-cell → new-cell migration map. Defaults to `config/benchmark-baseline-migrations.json`; ambiguous mappings and empty reasons fail. |
| `--run-id ID` | Reject rows from other benchmark runs. |
| `--evidence-manifest PATH` | Select the manifest's exact ordered generations and cells. |

### 6.2 Headline table columns

| Column | Source | Notes |
|--------|--------|-------|
| RTF | `derivedMetrics.audioSecondsPerWallSecond` | Primary throughput KPI |
| tok/s | Codec tokens / decode wall | Compare across variants |
| TTFC ms | App row `submitToFirstChunkMS` | `-` for CLI (no app process) |
| peakGPU / physFoot | Sampler peaks | physFoot = Jetsam-relevant on iOS |
| trims | `memory_trim` stage marks | Floor/mid/iPhone tiers |
| UIdelay | App row delayed-heartbeat count/max plus coverage | Sampling signal; `-` for CLI, not an exhaustive stall count |
| QC | `audioQC.verdict` + flags | `fail` = hard stop |

### 6.2a Memory qualification contract

New publishable generation benchmarks require telemetry schema v8 and benchmark-evidence manifest
v2. For every selected generation, the exact `engine/samples-<generationID>.jsonl` sidecar must
begin with one `start`, end with one `stop`, retain monotonic elapsed and absolute-uptime clocks,
and contain the required preparation/model-load/session/first-output/final-WAV/terminal boundaries.
iOS additionally requires finite headroom samples. macOS UI/XPC runs require a matching app sidecar;
their total resident/footprint/compressed/GPU values use samples paired by absolute uptime within one
500 ms cadence. Headless macOS CLI/profile runs remain owning-engine-process evidence. Never add
independent process maxima.

Sidecar and summary counts must agree, capture failures must be zero, and periodic sampler coverage
must be at least 95%. Coverage from 95% to below 100%, guarded pressure, or `softTrim` produces
`passedWithWarnings`. Coverage below 95%, critical pressure, an app memory warning/exit,
`hardTrim`, or `fullUnload` fails publication and leaves tracked history unchanged. Manifest v2
binds `memoryContractVersion`, the selected sidecar count/digest, each take's memory status/digest,
and bounded start/end/delta/peak, headroom/utilization, sampler, pressure, trim, warning, and exit
metrics. Raw samples remain untracked.

### 6.3 Decode breakdown (lazy MLX)

**RTF vs decode ms:** Both now prefer `qwen_token_loop_total` for wall time when present. See
[`telemetry-and-benchmarking.md`](telemetry-and-benchmarking.md) §7 (RTF vs decode ms).

Columns: `talker · sampCB0 · codePred · code2wav · stepEval · other`

- **stepEval** ≈ fused per-frame `eval()` (Talker + CodePredictor + sampling) — best compute proxy in JSONL
- **talker / codePred** ≈ graph **build** time, not GPU kernels
- **code2wav ≈ 0** — decoder is `asyncEval`'d and overlaps the token loop

Validate with Instruments signposts: **Step Eval Flush**, **Code Predictor Loop**, **Talker Forward**, **Audio Decoder**.

### 6.4 Chunk timeline block

When streaming, summarizer prints per-cell medians: chunk count, first-chunk ms, inter-chunk ms,
substage ms. Use for cold-start vs steady-state analysis.

### 6.5 Thermal and environment

Summarizer prints **thermal** (worst state in cell), **gpuWS** (`gpuWorkingSetUsageRatioPeak`),
and **headMin** (`headroomMinMB`) when the sampler collected them. Re-run if thermal throttling
suspected; inspect raw JSONL for full `thermalState` start/end/worst.

---

## 7. Tracking performance over time

### PASS-only registry

Every in-repository benchmark-like lane publishes only after its own success contract passes. The
runner writes an atomic untracked `benchmark-evidence.json`, then calls:

```sh
python3 scripts/benchmark_history.py record --artifact-dir <run-artifact-dir>
python3 scripts/benchmark_history.py validate --all
python3 scripts/benchmark_history.py rebuild-index --check
```

Publication creates `benchmarks/runs/<kind>/<run-id>.json` and regenerates
`benchmarks/HISTORY.md`; it never stages, commits, or pushes. Re-recording byte-identical evidence
is idempotent. A conflicting run ID, duplicate evidence digest, privacy violation, oversized
record, failed QC, failed finish, crash delta, missing layer, wrong take order, or unreadable WAV
fails publication and leaves tracked history unchanged. If publication fails after the expensive
run passed, retain the local artifact directory and rerun the printed `record --artifact-dir`
command after repairing the exporter.

An accepted QC warning produces `passedWithWarnings` and remains visible in run/cell warning
counts and worst-QC fields. A QC failure is never downgraded or published.

Schema-v2 tracked benchmark kinds are `ui-generation`, `engine-generation`, `language`,
`instrument-profile`, `memory-qualification`, `prosody-calibration`, and `ui-perf`
(registered 2026-08 with the macOS frame-health lane). Schema-v1
`telemetry-overhead` records remain readable historical evidence, but new overhead runs are local
observer-effect diagnostics and do not publish. Delivery/prosody cells from
`vocello bench --delivery` remain inside their parent engine-generation record. Smoke, unit tests,
crash inspection, preflight, and standalone analysis tools do not publish benchmark records.

| Kind | Publisher | Minimum publishable success |
|---|---|---|
| `ui-generation` | `ui_test.sh macos|ios benchmark` | XCTest, exact selected matrix/order, complete required telemetry layers, memory qualification, readable atomic WAVs, QC, and crash delta |
| `engine-generation` | `vocello bench`, iOS headless bench, optional gate bench | Exact selected rows, memory qualification, successful finishes, readable/QC-accepted output, and command PASS |
| `language` | macOS/iOS `lang-bench` | Requested hint/output gates; hint-only is explicitly `partial` |
| `instrument-profile` | macOS/iOS profile commands | Memory-qualified target generation PASS, exact PID, tracer success, valid trace TOC, non-empty exported performance rows, and run/generation/take/cell-correlated signposts |
| `memory-qualification` | macOS/iOS `memory` commands | Fixed policy topology, v8 sidecar qualification, output/QC success, and within-mode retained-footprint growth ≤5% of physical RAM |
| `prosody-calibration` | `prosody_calibration.py` | Required corpus coverage with no analysis failure |
| `ui-perf` | `ui_test.sh macos perf` via `check_macos_ui_perf.py` | Structural gate PASS (nine scenarios once each, coverage/refresh sanity), canonical hardware profile, and crash delta; threshold breaches are warn-only (`passedWithWarnings`). The iOS perf lane joins this kind only at IUI-6 (platform-aware relaxation); until then its reports stay local-only |

`HISTORY.md` is a generated index grouped by kind, platform, hardware, and comparable
configuration. It computes a delta against the nearest earlier compatible clean record; a delta is
information, not an automatic failure. [`benchmarks/LEGACY_HISTORY.md`](../../benchmarks/LEGACY_HISTORY.md)
preserves the former manual ledger as incomplete historical evidence.

### Listening annotation

Automated success and optional perceptual review are independent. Add the latter without rewriting
the run:

```sh
python3 scripts/benchmark_history.py annotate --run-id <run-id> \
  --listening pass --note "reviewed representative takes"
```

Use `fail` or `not-performed` when appropriate. Listening never changes the automated verdict and
is not required for promotion; it records subjective observations that deterministic gates do not
claim to measure.

### Baseline comparison (JSON, machine-gated)

```sh
# Seed / reseed a baseline (after an intentional, reviewed perf change):
python3 scripts/summarize_generation_telemetry.py <diag-dir> \
  --run-id <run-id> --evidence-manifest <run-artifact-dir>/benchmark-evidence.json \
  --save-baseline benchmarks/baselines/mac-gate-bench.json

# Compare (exit 2 on regression — usable in scripts/gates):
python3 scripts/summarize_generation_telemetry.py <diag-dir> \
  --run-id <run-id> --evidence-manifest <run-artifact-dir>/benchmark-evidence.json \
  --compare-baseline benchmarks/baselines/mac-gate-bench.json
```

The committed **`benchmarks/baselines/mac-gate-bench.json`** (custom/speed/medium,
cold+warm) is a schema-v2 baseline binding the hardware profile, `-O` optimization,
matrix/corpus, model artifact, and evidence semantics. It is what
`QWENVOICE_GATE_BENCH=1 scripts/macos_test.sh gate` compares against —
the gate uses an isolated runtime directory, rejects rows outside its collision-resistant run ID,
and freezes the exact ordered generation selection in `benchmark-evidence.json` before comparing.
Markdown snapshots (`benchmarks/baseline-*.md`) remain the human-readable full-matrix references;
diff them with `git diff`, not `--compare-baseline`.

### Like-for-like comparison rules

Never compare numbers across topologies — each is a different measurement, not a
regression signal:

| Lane | Build | Topology | Headline custom/speed/medium warm |
|------|-------|----------|-----------------------------------|
| `build.sh cli-optimized` CLI bench | hash-bound `-O` | in-process | Shipping-optimization backend result; compare only with the same optimization identity |
| local release / `-O` CLI | optimized | in-process | RTF ≈ 1.7 |
| macOS `ui_test.sh macos benchmark` | Release app | app + XPC service | RTF ≈ 1.7 |
| iOS `ios_device.sh bench` | `-Onone` device | in-process on iPhone | RTF ≈ 1.6–1.9 |
| iOS `ui_test.sh ios benchmark` | `-O` Release app | in-process, real Studio UI | optimized frontend/device result; do not compare with the `-Onone` headless lane |

Tracked comparison keys include the exact optimization identity, executable UUID/hash, toolchain,
source inputs, model identity, matrix, and hardware profile. Consequently a historical `-Onone`
record cannot become the baseline for a new `-O` record; the first clean optimized record reports
an explicit no-baseline state.

The gate rejects legacy metric-only baseline arrays because they cannot prove whether they came
from `-Onone` or `-O`; a reviewed baseline replacement must be generated from an exact successful
evidence manifest. Compare a history record only against one with the same generated comparison key. That key includes lane,
platform/hardware, matrix (including CLI streaming/seed and overhead rotation settings),
model/runtime, toolchain, and relevant input identities. Dirty,
instrumented, partial, and forced-profile runs are excluded from canonical trends.

---

## 8. Quality gates

### Layer 1 — audioQC (automatic, every run)

Engine runs reference-free PCM analysis: `nonfinite`, `clipping`, `clicks`, `dropout`, `near_silent`.
Punctuation-aware pause budget avoids false positives on natural delivery.

### Layer 2 — Prosody scripts (optional)

`scripts/prosody_quality_gate.py`, `scripts/delivery_adherence.py` on bench WAVs when using `--delivery`.

### Layer 2.5 — Language hint contract (Phase 2)

Headless matrix (`scripts/ios_device.sh lang-bench` or `scripts/macos_test.sh lang-bench`)
stamps `notes.languageHint` (resolved Qwen3 token, not raw UI picker). Gate with
`scripts/check_language_hints.py` against `config/language-bench-matrix.json`.
Offline fixture self-test: `python3 scripts/test_check_language_hints.py`.

### Layer 2.6 — Output language + WER/CER (Phase 3, iOS device diagnostics)

When `QVOICE_IOS_DEVICE_DIAGNOSTICS_VERIFY_OUTPUT=1`, the app transcribes each exact fixed-seed WAV
three times in-process with one locale-locked on-device Speech recognizer and stamps the consensus
evidence on `device-diagnostics-done.json`. `scripts/check_language_output.py` independently
recomputes edit metrics from the corpus: WER is primary for word-delimited languages and CER for
Chinese/Japanese, both with a 0.15 ceiling. Requires Speech Recognition permission on the phone
once. Skip with `QVOICE_LANG_BENCH_SKIP_OUTPUT=1`. See [`language-bench.md`](language-bench.md).

### Layer 3 — Optional listening annotation

When desired, play takes and record a subjective timbre/prosody observation with
`scripts/benchmark_history.py annotate`; never edit `HISTORY.md` directly. This annotation is not
an automated gate and does not authorize overriding a deterministic failure or warning.

---

## 9. Artifact map

### On disk (gitignored)

| Path | Contents |
|------|----------|
| `~/Library/Application Support/QwenVoice-Debug/diagnostics/engine/generations.jsonl` | Richest backend rows |
| `.../engine-service/generations.jsonl` | XPC transport (macOS app path) |
| `.../app/generations.jsonl` | UI timings |
| `.../generations-merged.jsonl` | Joined layers (macOS) |
| `.../engine/samples-<UUID>.jsonl` | Verbose per-sample series |
| `QwenVoice-Debug/outputs/bench/*.wav` | Bench WAV outputs (fixed per-cell filenames — overwritten across seeds) |
| `QwenVoice-Debug/outputs/bench-archive/<runID>/` | Durable per-run evidence for every `--delivery` run: all take WAVs plus `bench-results.json`, `bench-prosody.json`, `bench-quality-composed.json`. Fail-closed for required files, written before the sidecar analysis; unbounded, prune manually. Successful diagnostics run dirs are cleaned after publication, so multi-run scoring reads from this archive ([`delivery-harness.md`](delivery-harness.md) §3) |
| `<run-artifact-dir>/benchmark-evidence.json` | Atomic run-scoped validator selection and verdict used for publication |
| `build/**/*.xcresult`, screenshots | UI evidence retained locally under bounded lane retention |
| `build/**/profiles/` | Compact local profile summaries; raw `*.trace` is success-ephemeral unless `--keep-trace` was explicit |

Auto-pruned: `generations.jsonl` ~8 MB cap; verbose sidecars newest-48 / 64 MB.

### Committed (bounded)

| Path | Rule |
|------|------|
| `benchmarks/runs/<kind>/<run-id>.json` | One canonical allowlisted record per successful run, ≤ 256 KB; only `annotate` may update listening review |
| `benchmarks/HISTORY.md` | Generated registry index; never edit by hand |
| `benchmarks/LEGACY_HISTORY.md` | Preserved incomplete manual history; never promoted to complete registry evidence |
| `benchmarks/hardware-profiles.json`, `schema-v1.json`, `schema-v2.json` | Canonical hardware identities plus compatibility/current record contracts |
| `benchmarks/baseline-*`, `OPTIMIZATION.md` | Existing reference snapshots and historical optimization narrative |

The exporter uses a strict allowlist and rejects serials/UDIDs/ECIDs, host/device/user names,
absolute paths, prompts/transcripts/voice descriptions, raw errors, emails, URLs, and secret-like
labels. **Never commit raw JSONL, WAVs, screenshots, result bundles, or traces** under `benchmarks/`.

### CI / automation

- `.github/workflows/ci.yml` — `ios-compile-check` (compile-only; no attended UI, no bench)
- `.github/workflows/release.yml` — deterministic signing and packaging; UI lanes remain explicit/local
- `scripts/check_project_inputs.sh` — validates all compact records and checks that `HISTORY.md` is reproducible
- Explicit frontend acceptance: `scripts/ui_test.sh macos smoke|benchmark`
- Deterministic macOS platform gate: `scripts/macos_test.sh gate` (does not consume UI results)

Engine regression net remains **manual local** until a self-hosted macOS bench job exists.

---

## 10. Troubleshooting

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| Custom/Design "cold" shows `warm` | Proactive warmup ran | `QWENVOICE_SUPPRESS_WARMUP=1` for UI; CLI unloads explicitly |
| Clone missing from matrix | No enrolled voice | `scripts/macos_test.sh models ensure` |
| `preflightModels` fails Quality | Speed-only fixture | Install Quality weights or use `--variants speed` |
| Summarizer empty | Wrong diagnostics dir / gate off | Confirm `QWENVOICE_DEBUG=1`; check `engine/generations.jsonl` |
| RTF vs decode ms disagree | Different time bases + lazy MLX | Read §6.3; use signpost trace |
| All QC warn:dropout on long | Often natural pauses | Run the fixed-seed exact-WAV cohort; inspect the punctuation-aware budget, ASR consensus, and prosody evidence |
| iOS bench timeout | Model missing / device diagnostics did not complete | `scripts/ios_device.sh console`; install Speed model |
| Clone cold row appears | Corrupt matrix ordering, generation map, or frozen evidence | **Hard failure:** inspect `bench-results.json` or the UI generation map plus `benchmark-evidence.json`, repair the producer/selection mismatch, and rerun. Never relabel or ignore a Clone cold row. |

---

## 11. Related documents

| Doc | Role |
|-----|------|
| [`telemetry-and-benchmarking.md`](telemetry-and-benchmarking.md) | Schema, knobs, telemetry architecture |
| [`cli.md`](cli.md) | Full `vocello bench` flag reference |
| [`macos-release-qa.md`](macos-release-qa.md) | Release gate sequence |
| [`macos-testing.md`](macos-testing.md) | UI test / profile / gate lanes |
| [`ios-device-testing.md`](ios-device-testing.md) | iOS bench, gate, device lanes |
| [`benchmarks/OPTIMIZATION.md`](../../benchmarks/OPTIMIZATION.md) | Optimization program status |
| [`benchmarks/HISTORY.md`](../../benchmarks/HISTORY.md) | Generated benchmark registry index |
