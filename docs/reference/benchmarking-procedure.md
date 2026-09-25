---
status: active
owner: release-qa
reviewed: 2026-09-12
summary: Operator runbook for performance and quality benchmarks — when to bench, the macOS CLI/app and iOS device paths, expected artifacts, and how to read results.
sourceOfTruth:
  - scripts/macos_test.sh
  - scripts/ios_device.sh
  - scripts/ui_test.sh
---
# Benchmarking procedure — operator runbook

Step-by-step guide for running Vocello performance and quality benchmarks on **macOS**
(CLI and app) and **iOS** (physical-device UI and headless diagnostics). This document covers **when** to bench,
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
- Memory policy, streaming interval, idle-unload, in-process relief
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
| **RTF** | `derivedMetrics.realTimeFactor` (request wall ÷ audio, lower is faster) reviewed against the nearest compatible clean record in generated [`benchmarks/HISTORY.md`](../../benchmarks/HISTORY.md); records before 2026-09-12 stored the inverted decode speedup under `rtf` and never share a comparison key with new ones. New records declare `run.rtfDefinition: "wall/audio"`; a record without that field stores the legacy decode speedup under `rtf`. |
| **Memory** | No rising `physFoot` peak or non-zero `hardTrim` in `trims` on floor-tier runs. |
| **Automated output proof** | Fixed-seed cohort, exact WAV identity, and applicable locale-locked ASR/prosody gates pass. Human listening is optional annotation and is never inferred. |

**RTF < 1** means faster than real time (the standard definition: synthesis seconds per audio second). The
decode-loop speedup that older documents and records called "RTF" is now `decodeSpeedupX` / the
summarizer's `xRT` column.

### Design constraints

1. **Primary backend driver is headless** — `vocello bench` drives the matrix in-process with exact
   cold/warm control. **`scripts/ui_test.sh macos benchmark`** is the supplementary UI integration net (§4.10).
2. **Telemetry is runtime-gated** — identical code in Release; off unless `QWENVOICE_DEBUG=1`,
   `QWENVOICE_NATIVE_TELEMETRY_MODE`, or the in-process latch enables it, and always off under an
   explicit `QWENVOICE_NATIVE_TELEMETRY_MODE=off` (`vocello bench --telemetry off`).
3. **No CI execution gate** — model-dependent benchmarks are local and explicitly requested. CI validates the compact registry and reproducible index but does not run models, devices, XCUITest, or Instruments.
   The consent-bound lanes, never run unasked, are `scripts/macos_test.sh memory|lang-bench`, every
   `scripts/ui_test.sh` lane and every `scripts/ios_device.sh` verb; `scripts/macos_test.sh gate` and
   `telemetry-overhead` are ordinary local lanes; `telemetry-overhead` needs the model fixture, `gate`
   only when `QWENVOICE_GATE_BENCH=1` adds its bounded bench.
4. **Lazy MLX caveat** — decode breakdown columns measure Swift wall-clock around lazy graph
   ops, not per-stage GPU compute. Use Instruments signposts for GPU attribution (§6.3).
5. **PASS-only publication** — a successful repository benchmark publishes one allowlisted JSON
   record and regenerates `HISTORY.md`. Failed or incomplete runs leave tracked history unchanged;
   raw telemetry, audio, screenshots, traces, and result bundles remain untracked.

---

## 2. Platform topology

Three hosts write telemetry; only some layers exist per path:

```text
                    CLI (vocello bench)     macOS app (in-process) iOS app (in-process)
                    ───────────────────     ─────────────────────  ────────────────────
Engine row          yes                     yes                    yes
App row             no                      yes (UI timings)       yes (UI timings)
Required join        engine                  app + engine           app + engine
TTFC column         — (no app process)      yes (submit→chunk)     yes
UI heartbeat        —                       yes                    yes
```

| Path | Driver | Engine topology | Best for |
|------|--------|-----------------|----------|
| **CLI** | `./build/vocello bench` | In-process `MLXTTSEngine` | Deterministic RTF/decode/memory matrix; release QA step 3 |
| **macOS UI** | App (in-process engine) | In-process engine | Submit-to-first-chunk, playback scheduling and delayed-heartbeat evidence; UI smoke tests |
| **macOS UI benchmark** | `scripts/ui_test.sh macos benchmark` | In-process engine | Full UI matrix through the real app; merged app + engine telemetry |
| **macOS profile** | `scripts/macos_test.sh profile --kind cpu|memory|witness` | In-process via CLI inside exact-PID trace | CPU/signpost, allocation/VM validation, or the signpost-only timing witness |
| **iOS device** | `scripts/ios_device.sh bench` | In-process | iPhone tier, Jetsam, on-device RTF (headless diagnostics, single take) |
| **iOS UI benchmark** | `scripts/ui_test.sh ios benchmark` | In-process | Full UI matrix through XCUITest on the paired physical iPhone; telemetry gated per take |
| **macOS UI frame health** | `scripts/ui_test.sh macos perf` | No engine claims (UI-only) | Nine scripted SwiftUI scenarios with the in-app frame probe; warn-only ceilings; canonical-hardware runs publish `ui-perf` registry records; lane contract in [`macos-testing.md`](macos-testing.md) (history: [`macos-ui-refresh-2026-08.md`](macos-ui-refresh-2026-08.md)) |
| **iOS UI frame health** | `scripts/ui_test.sh ios perf` | No engine claims (UI-only) | Nine scripted scenarios on the paired physical iPhone with the pinned-60 Hz in-app probe; `check_ios_ui_perf.py` structural + canonical-hardware gate with warn-only ceilings from [`config/ui-perf-thresholds-ios.json`](../../config/ui-perf-thresholds-ios.json); canonical-iPhone runs publish platform-`ios` `ui-perf` registry records; lane contract in [`ios-device-testing.md`](ios-device-testing.md) (history: IUI-6, [`ios-ui-refresh-2026-08.md`](ios-ui-refresh-2026-08.md)) |

**Important:** CLI bench numbers are **not** identical to macOS UI numbers. Compare like with
like (CLI vs CLI, UI vs UI). Use CLI for backend optimization; use the UI lane for integration regressions.

### Canonical hardware profiles

Native history is anchored to [`benchmarks/hardware-profiles.json`](../../benchmarks/hardware-profiles.json):

| Platform | Profile | Hardware | Status |
|---|---|---|---|
| macOS | `mac-mini-m6-16gb` | Mac mini `Mac18,5`, Apple M6, 16 GB, 12 cores (2 Super, 4 Performance, 6 Efficiency) | Canonical since 2026-09-22 |
| macOS | `mac-mini-m2-8gb` | Mac mini `Mac14,3`, Apple M2, 8 GB | Retired canonical, history only |
| iOS | `iphone-17-pro` | iPhone 17 Pro `iPhone18,1` | Canonical |

The M6 records start a new published series. The M2 records stay valid history under their own
profile: they are never rewritten, and a profile is part of every comparison key, so M2 and M6
records are never compared. The 8 GB Mac remains the product support floor; the canonical host is
the benchmark machine, not the floor. A macOS benchmark run refuses to start unless
`python3 scripts/publish_benchmark_history.py verify-hardware --platform macos` confirms the live
host is the canonical profile.

Records also capture current OS build, thermal/low-power state, sanitized transport, toolchain,
executables, input/model fingerprints, and source state. A dirty success is `exploratory`, not a
canonical trend point. Profiles and forced-memory-class diagnostics are not compared with normal
timing records. Engine and macOS UI benchmark records published since 2026-09-25 also carry
`run.runtimePolicy` (`deviceClass`, `deviceClassForced`, and `simulatedPhysicalMemoryMB` on an
emulated smaller Mac), taken from the rows' own stamps, so a record proves which memory tier it
measured; the validator refuses a native tier on the wrong platform and a forced tier on a comparable
record. Lineage contract 2 keys a forced or emulated tier (its `deviceClass` and
`simulatedPhysicalMemoryMB`) apart from the host's own records; a native tier adds nothing to the key.

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

The `scripts/macos_test.sh` model lanes verify the fixture themselves before running
(`scripts/macos_test.sh preflight --strict-models` fails when anything is missing; `models check`
prints read-only status); bare `xcodebuild` performs no such check.

### Environment hygiene

| Check | Action |
|-------|--------|
| Quiet machine | Timing lanes refuse to start on a busy host (`require_quiet_host` in `scripts/lib/host_preflight.sh`: a 1-minute load average above 2× the core count, kernel memory pressure above normal, another holder of the host-wide native lock or a locked agent worktree exits 1 before any model loads; it guards the `macos_test.sh gate` bench (`QWENVOICE_GATE_BENCH=1`; the deterministic gate alone does not check) and `macos_test.sh memory|lang-bench|telemetry-overhead`, `ios_device.sh bench|lang-bench|memory|gate` and the `ui_test.sh` benchmark and perf lanes). `QVOICE_ALLOW_BUSY_HOST=1` records the numbers and continues, and the run's own load sample then classifies it. Engine and UI benchmark takes (macOS and iPhone) also keep their own one-minute load (`metrics.loadAverage1M`): publication marks an engine or UI benchmark record exploratory when any take exceeded 1× the core count of its canonical profile, and the gate bench is inconclusive (exit 3) when its busiest warm take exceeded 2×. Quit heavy apps and watch thermals (see §6.4). |
| Free disk | Heavy lanes check the floors in `config/build-output-policy.json` before building or launching (`require_build_free_space`, `scripts/lib/storage_preflight.py`): 15 GiB for `ui_test.sh … benchmark`, macOS/iOS `memory`, `lang-bench` and iOS `bench`/`gate`; 12 GiB for `telemetry-overhead` and `ui_test.sh … perf`; 8 GiB for `macos_test.sh gate`. A shortfall stops the lane before any work starts. |
| Single Vocello session | Quit any separately installed Vocello first. The XCUITest runner verifies exact executable paths and signals only its own Release products. |
| Debug data dir | `QWENVOICE_DEBUG=1` → `~/Library/Application Support/QwenVoice-Debug/` |
| Floor-tier simulation | `QWENVOICE_FORCE_MEMORY_CLASS=floor_8gb_mac` forces the tier's policy (read in-process by whichever host runs the engine); `QWENVOICE_SIMULATED_PHYSICAL_MEMORY_GB=8` emulates the whole 8 GB machine on the M6 (tier, footprint bands, Metal working set). Both are exploratory only; see §4.4 |
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
and then primes the reference as Studio does (`ensureCloneReferencePrimed`, the same clone
prewarm a take would otherwise pay inside `warm#0`) before its measured Clone takes, without
generating an extra warm-up take, so every warm take measures the same warm path. `warmState`
means model residency, not that every conditioning/decoder cache is hot. New engine records require
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

Summarizer header shows `tier: floor_8gb_mac ⚠ forced or emulated`. `--save-baseline` and
`--compare-baseline` refuse forced rows (exit 1): a forced tier changes policy values, not the
hardware, so it never seeds or meets a regression baseline. The governed baseline identity also
binds the native `deviceClass` from the evidence's `run.runtimePolicy`; a baseline saved before
that key compares without it and the summarizer says so.

**The 8 GB floor evidence path (after the M6 became canonical).** The Mac mini M6 16 GB is the
benchmark host and the 8 GB Mac stays the support floor (maintainer decision 2026-09-25, audit #11
option b). There is no second canonical host: the floor is emulated on the M6 with
`QWENVOICE_SIMULATED_PHYSICAL_MEMORY_GB=8` (registered in `config/runtime-debug-knobs.json`; it needs
the internal-diagnostics build and `QWENVOICE_DEBUG=1`, which every repository lane sets). The host
then reads as an 8 GB Mac wherever policy reads the machine: the tier resolves to `floor_8gb_mac` with
its policy, the store's footprint bands are the floor's (guarded at 55%, critical at 72% of 8 GiB) and
the snapshot reports 8,192 MB of RAM and a 5,461 MB Metal working set, so every row's
`gpuRecommendedWorkingSetMB` reads about 5,461 and `totalDeviceRAMMB` 8,192. A forced class alone
keeps the M6's bands and working set; use the emulation for floor evidence.

```sh
# Engine footprint and policy on the emulated floor (vocello bench rows)
QWENVOICE_DEBUG=1 QWENVOICE_SIMULATED_PHYSICAL_MEMORY_GB=8 ./build/vocello bench \
  --modes custom,design,clone --variants speed --lengths medium --warm 3 --label "floor-emulated"

# The retained-memory protocol on the emulated floor
QWENVOICE_SIMULATED_PHYSICAL_MEMORY_GB=8 scripts/macos_test.sh memory --label floor-emulated

# The app's bands on the emulated floor (the runner hands the knob to the app)
QWENVOICE_SIMULATED_PHYSICAL_MEMORY_GB=8 scripts/ui_test.sh macos benchmark --label floor-emulated
```

Each is a consent-bound lane like its unemulated form. The rows stamp `deviceClassForced=true`,
`simulatedPhysicalMemoryMB` and `simulatedMetalWorkingSetMB`; the publisher classifies every such
record `exploratory` (never canonical, never comparable, never a baseline or a chart point) and the
record's `run.runtimePolicy`, on engine and macOS UI benchmark records alike, names
`simulatedPhysicalMemoryMB` beside the forced floor tier. Lineage contract 2 (2026-09-25, audit #11
option b) reads that block: an emulated or forced record gets a comparison key of its own, so
`benchmarks/HISTORY.md` groups the emulated-floor runs in their own M6 section instead of among the
host's records. Records stamped with contract 1 (the first M6 gate records) and legacy records keep
their stored keys; a published key is never edited in place. An emulated or forced record is still
excluded from every comparison: it gets no baseline or deltas and is never another record's baseline,
and HISTORY names its classification `exploratory (emulated 8192 MB)` (a forced class alone reads
`exploratory (forced <tier>)`) with the comparison `excluded`. The
band paths reuse the store's existing knobs: `QVOICE_IOS_MEMORY_GUARD_FORCE_BAND=guarded` or
`QVOICE_IOS_MEMORY_GUARD_FORCE_CRITICAL_ONCE=1`, which the UI benchmark lane also hands to the app. A
forced band trims or unloads, which fails memory qualification by design, so such a run is a
band-path diagnostic that keeps its artifacts and publishes nothing.

What the evidence can claim is **policy and footprint**: the floor tier's policy values, the footprint
each take reaches against the floor's bands, and Metal allocations against the floor's working set.
It cannot claim kernel memory pressure, compression, swap or the real Metal budget of an 8 GB Mac, and
M6 timings say nothing about the floor's speed; the M2 history stays the only 8 GB timing and pressure
evidence. A pressure balloon that would reproduce pressure needs its own quiet-host exemption and is not
part of this path.

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
2026-08-01 delivery-fidelity programme:

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
findings, not waivable annotations. The cohort's binding arousal-outlier check stays the
calibrated population z-score (`outlierAlgorithm: population-z-v1`, bound 2.5). It includes the
candidate, so it cannot exceed √(n−1) and cannot fire for seven or fewer takes (audit #105).
Beside it, `leaveOneOutOutlier` reports, and never gates, the largest externally studentized
leave-one-out residual (`leave-one-out-studentized-t-v1`: the take against the mean and SD of the
others), which follows Student's t with n−2 degrees of freedom for a healthy cohort, with its
candidate take and Bonferroni family-wise p-value. A seeded null simulation keeps it near 5% at
p < 0.05, where a leave-one-out median/MAD score crossed 2.5 in 58-82% of healthy cohorts of four
to eight takes. Choosing its cohort-wise alpha, and so making it binding, is a maintainer decision
under the audio-QC threshold-change authority. The clone lane
and SER column stay advisory; the clone lane reports AUC and equal error rate with seeded 95%
intervals whenever it has controls (`bandCalibrationReady` needs at least eight), embeds 16 kHz
audio through the pinned polyphase resampler and loads the ECAPA snapshot from the local cache
only.

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

The optional `axiom:axiom-tools` plugin skill can help choose an Instruments workflow; the procedure in
[`ios-device-testing.md`](ios-device-testing.md) is authoritative, including physical-device setup.

The iOS profile command resolves Instruments' UDID independently from CoreDevice's device ID and
stops before launching Vocello if the phone is listed under `Devices Offline`. Reconnect and unlock
the phone until `xcrun xctrace list devices` places it under `Devices`; CoreDevice reachability alone
is not sufficient evidence that Instruments can attach.

### 4.8 macOS Instruments profile (signpost validation)

```sh
QVOICE_MAC_PROFILE_DURATION=120 \
scripts/macos_test.sh profile custom:speed:

scripts/macos_test.sh profile --kind memory custom:speed:

# The low-perturbation timing witness: os_signpost only, on the gate bench's seed.
scripts/macos_test.sh profile --kind witness

# Only when a CPU profile's raw document must be reopened in Instruments:
scripts/macos_test.sh profile --keep-trace custom:speed:
```

The CPU profile records one cold and three warm medium takes; every kind refuses a busy host
(`require_quiet_host`) and a dirty tree (`--allow-dirty` records an exploratory profile of
uncommitted source). Publication streams each exported table once and publishes, beside the row
counts, a versioned signpost block: interval, begin, end and point counts, the orphan intervals
outside every take, the trace's recorded duration and, per take, statistics of the engine's
decode-loop intervals (count, total, median, p95, max per interval name, `Token Read` included)
assigned by containment in the take's window, from the end of its correlated prepare interval to
the end of its correlated `Native Generation Stream` interval. Each decode
step emits 36 loop intervals, and the take's own end reason (`endReason`) says how many steps it
ran: `tokens + 1` for an EOS take, whose last step samples EOS, and `tokens` for a take that hit
the token cap (a QC warning, still published). A macOS take short of 36 per step fails
publication; an iPhone take is published with `complete: false`.
Each take also reports how many interval sums drifted from the engine's own JSONL totals
(`scripts/lib/trace_intervals.py`); that witness only reports.

The witness profile (`--kind witness`, audit #50) records the CPU profile's takes with
`os_signpost` alone: no CPU sampler, which cost profiled takes 29-80% of their warm tokens/s. It
runs on the gate bench's seed, so its takes are token-exact with the gate's and its warm tokens/s
can be set against the gate bench's (expected within about 1%). Its trace summary carries the same
signpost block and no CPU fields; its matrix hash names its profile kind, so it never shares a
lineage with a CPU or memory profile. Like the CPU profile it deletes its raw trace after
publication unless `--keep-trace`, and it is an instrumented record, never canonical.

The macOS memory profile records one cold long take. This captures model-load plus sustained
allocation/VM peaks. The lane uses Apple's Allocations template for its Allocations and VM Tracker
tracks because that template disables automatic VM snapshots; adding standalone VM Tracker to a
Blank trace enables stop-the-world snapshots that create real holes in the target's 500 ms sampler.
Publication verifies the captured template setting and applies the same unobserved-gap gate as
every memory-qualified take (no gap above the policy bound: twice the cadence, at least 500 ms). The
memory profile's default 180-second safety cap is only a maximum; exact-target exit ends the recording
early. The separate `scripts/macos_test.sh memory` lane owns repeated retained growth.

Produces `build/artifacts/macos/profiles/<run-id>/<run-id>.trace` containing CPU Profiler samples and
`os_signpost` rows in one capture; the memory kind adds Allocations and VM Tracker. **In-process
only** — the CLI process rather than
the app. The lane is PASS-only: a tracer failure, benchmark failure, invalid trace, or failed publication
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
validates the trace through `xctrace export --toc`; there is no blind startup sleep. For the app path,
attach to the exact `Vocello` PID while generating via UI. Traces remain untracked. On
success the registry retains the digest, settings, extracted summary, original ephemeral path, and
retention policy, then the runner removes a CPU profile's raw trace; pass `--keep-trace` to retain
it explicitly. A memory profile keeps its raw trace by default (`keptByDefault`): xctrace cannot
export its allocation and VM tables, so the trace is its only memory evidence. The same complete
retention validation applies to schema-v2 records and quality-bearing
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

### 4.9 UI-driven generation (macOS app)

Real generation through the macOS frontend is driven only by XCUITest. Deterministic completion
comes from matching History/WAV state and typed backend probes:

```sh
scripts/macos_test.sh models ensure
scripts/ui_test.sh macos smoke
```

This validates semantic frontend behavior plus the matching History/WAV/backend state. It is
not the primary RTF matrix driver.

### 4.10 macOS UI benchmark (supplementary integration net)

**Primary backend regression remains `vocello bench` (§4.1).** The supplementary UI matrix is
driven by XCUITest through the real app (in-process engine). Shared fixtures own the take definitions;
deterministic tooling owns timestamps, typed telemetry validation, and aggregation.

Telemetry rows stamp `notes.benchRunID`, `benchTakeIndex`, `benchCell`, and `benchWarmState` when
`QVOICE_MAC_BENCH_RUN_ID` is set. Completion requires matching generation, History, WAV, and typed
probe evidence; there are no hidden UI-test flush markers. The authoritative runner supplies the
matrix arguments, run ID, crash-delta assertion, and evidence-manifest path together. A direct
run-ID-only validator call is useful for diagnosis, but it is not a publishable benchmark contract:

```sh
# Diagnostic only: inspect the default matrix rows already present for one run ID.
python3 scripts/check_macos_ui_bench.py ~/Library/Application\ Support/QwenVoice-Debug/diagnostics \
  --run-id macos-xcui-benchmark-YYYYMMDD-HHMMSS
```

For the strict contract, use `scripts/ui_test.sh macos benchmark`. Internally it passes the exact
`--modes`, `--lengths`, `--warm`, and `--label` values plus
`--evidence-manifest <run-artifact-dir>/benchmark-evidence.json --crash-delta-passed
--build-provenance <run-artifact-dir>/last-build.json --playback-capture-dir
<run-artifact-dir>/playback-capture --outputs-dir <QwenVoice-Debug>/outputs`. The build receipt names the app executable
and its digest, and the gate copies its optimization level into `toolchain.optimization` only after
re-hashing that executable. Never add the crash-delta assertion to a manual command unless the
caller actually captured and compared the pre/post crash snapshots.

The lane also passes `--stall-contract config/macos-ui-stall-gate.json --variant speed`. The stall
contract names the gate's statistic, its limit and the profile it is calibrated for; today it is the
provisional "no heartbeat delayed more than 250 ms" on `mac-mini-m6-16gb`, uncalibrated until one
exploratory M6 run records the per-take distribution and the contract is re-declared `calibrated`
with that run. The contract's status decides what the limit does (maintainer decision 2026-09-25): a
**provisional** limit reports only and never fails a run; the checker still records the full
distribution and whether the run would have failed (`stallGate.enforced: false` and
`stallGate.wouldFail` in the evidence manifest; a run over the limit publishes with the run warning
`stall.provisional.wouldfail(<takes above>/<gated takes>)`). Only a **calibrated** contract, which must
name its calibrating run IDs in `calibrationRuns`, fails a run with a take above the limit. The checker
prints the distribution to `benchmark-gate.txt` either way: the summary (median, p90, maximum, takes
above the limit, would fail, censored heartbeats) and every gated take's `cell=value`. Expect the
calibration run to exceed the provisional limit: replayed on the 464 canonical M2 takes, 250 ms is
exceeded by 189 (40.7%) and in all 16 runs, and the four 2026-09-14 runs have 16 to 23 of 29 takes
above it (per-run medians 295-353 ms). Under the report-only contract all 16 would have published,
each with its would-fail warning. A contract naming another profile than the registry's canonical one
fails the gate.

Every take must have run the declared variant (Speed), whatever the tier recommends (the 16 GB tier
recommends Quality). Before the first take the benchmark makes Speed the active variant of each
measured mode through the visible toolbar switch (`<mode>_speedVariantButton`) and restores the
original visible choice when the session ends; it never toggles "Prefer lower-memory models", which
clears every stored choice. The checker still refuses any take that ran another variant. The engine runs in the app,
which has exited before validation, so the lane validates once and retries only the checker's
distinct "rows not yet present" exit (75), for about ten seconds. Timing lanes also let the load of
their own build settle (up to 90 s, down to the core count) and re-apply the quiet-host rule after
build-for-testing, before the first take.

One repetition of each cell is captured (audit #31): the last warm repetition of each mode and
length, never a take that starts an app session (the first take, a cold take, the first Clone take).
Those takes play out before the next begins, with a half-second tail; every other take pauses its
playback through the visible player control at completion and settles the same half second. Which
takes play out is fixed by the matrix, never by the recording grant, so the idle gap before a take
never depends on whether the tap is live (audit #74). A relaunched app has no Core Audio process
object until its first playback, so a tap armed on a session's first take would attach mid-take;
the plan never captures one, and every captured take's tap is live before its submit (audit #74 part
4). Making the app open its output device at launch instead would move the device-open cost out of
the first take's measured playback-scheduling latency and change the shipped audio lifecycle, so
the app is left as it is. The runner pastes each take's script with one genuine paste (Cmd-A,
Cmd-V, restoring the pasteboard's text) instead of typing it a key at a time, and an unsandboxed
runner (the lane re-signed it) writes the current-take file itself instead of relaying it through
the log and polling; a sandboxed one keeps the relay. The app row keeps the take identity it was
submitted under, and the checker refuses a run whose app and engine rows name different takes. The
runner prints each take's harness phases (monotonic offsets from the take's start: manifest
published, session ready, script entered, submit, completion seen, playback ended, settled, end,
and whether the take was captured) and the lane keeps them as `take-phases.jsonl` beside the run,
so per-take harness overhead is measured rather than inferred (audit #31); they time the harness
around the measured windows, never inside them. The evidence manifest also names each take's effective seed
and its source from the engine's receipt, so a run-on can be reproduced. The lane runs under the seed
policy `cell-hash-v1` by default (audit #29, `--seed-policy generated` opts out): the runner hands the
registered `QWENVOICE_BENCH_SEED_POLICY` knob to the app, every take samples with the seed of its cell
(`scripts/lib/bench_seed.py`), the checker refuses a take that sampled with any other seed (an app
built without internal diagnostics ignores the knob and fails here), and the record names
`run.seedPolicy` and each take's `seed`; lineage contract 2 keys a seeded matrix apart from random
seeds. The iPhone lane does the same through a per-process cell schedule. The manifest flags the first warm take after a cold
take (`followsColdTake`, audit #30): in the 16 canonical M2 records it is the slowest take of its cell
in 14 (custom/short) and 11 (design/short) runs. The tracked record keeps that take, flagged
(`followsColdTake: true`), but its cells use aggregate 2 (`evidence.cellAggregateVersion`): the flagged
take stays out of its cell's statistics, and an IQR is published only from at least four takes (null
below). The README medians leave flagged takes out too. Records without the declaration keep aggregate
1 and their stored cells; lineage contract 2 keys the aggregate version.

**Declared matrices (audit #30).** `config/ui-bench-matrix.json` names the matrix versions. The
canonical one, `uniform-v1`, is the 29-take matrix; `--matrix-version NAME` runs another (for example
the audit's provisional `proposal-5-3-2`, 32 takes), whose warm repetitions per mode and length reach
the XCUITest matrix as `QVOICE_<PLATFORM>_BENCH_ALLOCATION` and the checker as `--allocation`, and whose
records are focused, never canonical. `python3 scripts/ui_bench_allocation.py derive RECORD...
[--phases take-phases.jsonl ...] [--write NAME]` computes an allocation from a run's measured per-cell
spread: the pooled within-run spread of each warm cell's log RTF (the take after a cold take left out)
and each take's cost (its harness phases when given), spending the canonical matrix's own time budget
one take at a time on the cell whose median has the largest standard error, two to eight takes per
cell. Adopting a derived version as `canonicalVersion` is a separate, reviewed change; until then the
29-take assertion stays the default.

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
XCTest activity. The command accepts `--modes`, `--lengths`, `--warm`, `--label`, `--seed-policy` and
`--matrix-version`; without filters it runs exactly 29 takes. Cold Custom and Design cells are exact-path relaunches; a cell cannot
complete without its matching deterministic History/WAV assertion.

**Played-audio capture.** The runner taps the app's own output for one take per cell (the plan
above) through a Core Audio process tap (`mutedWhenTapped`), so the speakers stay silent while a
take is captured; the tap's
destruction restores audible output. The runner (`com.qwenvoice.app.uitests.xctrunner`, re-signed
unsandboxed by the lane) needs one manual **System Audio Recording** grant, added in System Settings
after the first lane run because a process tap never prompts (see
[`macos-permissions.md`](macos-permissions.md)); until granted, the lane passes and every planned
take's `playbackCaptureStatus` is `unavailable` or `silent` (takes outside the plan carry no capture
fields). A captured take that fails the played-audio gate
(coverage < 0.98, residual > −25 dBFS, a dropout, or an audible onset more than 500 ms from the
scheduling stamp; thresholds from the three canonical runs of 2026-09-14) fails the lane. Artifacts land under
`<run-artifact-dir>/playback-capture/` (`capture-run.json`, `take-NN-<cell>.wav` and `.json`,
`summary.json`); the WAVs stay untracked and only their digests enter the record. The metrics and
warn codes are listed in [`telemetry-and-benchmarking.md`](telemetry-and-benchmarking.md).

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
published to tracked history: adding the in-process memory sampler to the `off` lane would change
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
`BenchCommand` and the UI bench) — do not change without updating baselines:

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
matrix instead of inventing a warm/cold label. Ordinary Clone uses explicit model loading and
reference priming before its first measurement, as described in §4.3. UI cold uses app relaunch +
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
| `--save-baseline PATH` | Write the current per-cell summary as an ungoverned **JSON** baseline (ad-hoc local comparison; the gate seeds with `--seed-baseline`) |
| `--seed-baseline PATH` | Governed seed: add this run to the pooled baseline at `PATH` only when its evidence carries the full identity, its source is a clean commit, the judged takes ran on a quiet host (exit 3 otherwise) and every judged cell has at least `--seed-minimum-takes` (3) takes. A file with the same identity whose seeded runs share this commit gains the run; any other file is replaced by a one-run baseline. Prints the thresholds the pooled baseline implies. |
| `--compare-baseline BASELINE.json` | Fail-closed regression/coverage comparison against a **JSON** baseline. Exit 2 on regression (RTF **rise**, tok/s drop, TTFC, `engineFirstChunkMS`, `physFootMB` or `mlxPeakMB` rise beyond its threshold), removed/added cells, a missing sample count or required metric, or QC worsening; exit 3 (inconclusive) when the busiest judged take ran above 2× the core count, the host was in low power mode or the thermal state was serious/critical. The host verdict comes before the identity check, so a loaded run is inconclusive even against a stale baseline. Each metric's threshold is the largest of its floor (`rtf`, `tokps`, `ttfcMS`: `--regress-threshold`, 5%; `engineFirstChunkMS` 15%; `physFootMB` 30%; `mlxPeakMB` 2%), three median absolute deviations of the baseline's own takes (n ≥ 3), and the range of the per-run medians of a baseline pooled from at least three seeded runs. Every judged metric is printed with its threshold and basis. A baseline cell without the `engineFirstChunkMS` or `mlxPeakMB` key predates them and is not judged on them. A baseline saved before 2026-09-12 stores the decode speedup under `rtf` and is compared with the current `decodeSpeedupX`. Markdown snapshots cannot be fed to this flag — diff those with `git diff`. |
| `--verdict-json PATH` | Keep the comparison or seed verdict, the baseline's SHA-256, the host-load reasons, the token-count determinism report and every threshold used |
| `--preflight-baseline PATH --expected-identity FILE [--seeding]` | Without telemetry, predict whether a run with the identity in `FILE` (from `publish_benchmark_history.py expected-identity`) can compare against, or seed into, the baseline at `PATH`; exit 1 when the comparison would be BASELINE INVALID or a seed run would be refused |
| `--compare-states STATE[,STATE]` | Restrict the baseline verdict to cells in those warm states (the gate passes `warm`: its five-take medians decide, the single cold take stays informational). Without it every cell is judged. |
| `--baseline-migrations PATH` | Use a reviewed schema-v1 old-cell → new-cell migration map. Defaults to `config/benchmark-baseline-migrations.json`; ambiguous mappings and empty reasons fail. |
| `--run-id ID` | Reject rows from other benchmark runs. |
| `--evidence-manifest PATH` | Select the manifest's exact ordered generations and cells. |

### 6.2 Headline table columns

| Column | Source | Notes |
|--------|--------|-------|
| RTF | `derivedMetrics.realTimeFactor` (request wall ÷ audio) | Primary throughput KPI, lower is faster |
| xRT | `derivedMetrics.audioSecondsPerWallSecond` (audio ÷ decode s) | Decode-loop speedup, higher is faster |
| tok/s | Codec tokens / decode wall | Compare across variants |
| TTFC ms | App row `submitToFirstChunkMS` | `-` for CLI (no app process) |
| peakGPU / physFoot | Sampler peaks | physFoot = Jetsam-relevant on iOS |
| trims | `memory_trim` stage marks | Floor/mid/iPhone tiers |
| UIdelay | App row delayed-heartbeat count/max plus coverage | Sampling signal; `-` for CLI, not an exhaustive stall count |
| QC | `audioQC.verdict` + flags | `fail` = hard stop |

### 6.2a Memory qualification contract

New publishable generation benchmarks require telemetry schema v8 and benchmark-evidence manifest
v2. For every selected generation, the exact `engine/samples-*.jsonl` sidecar for that `generationID` must
begin with one `start`, end with one `stop`, retain monotonic elapsed and absolute-uptime clocks,
and contain the required preparation/model-load/session/first-output/final-WAV/terminal boundaries.
iOS additionally requires finite headroom samples. macOS UI runs require a matching app sidecar
from the same process ID: the app hosts the engine, so both layers' samples form one series of that
process in absolute-uptime order (memory contract v2) and are never summed. Headless macOS
CLI/profile runs remain owning-engine-process evidence.

Sidecar and summary counts must agree, capture failures must be zero, and no gap between two
consecutive samples of the series may exceed the unobserved-gap bound declared in
`config/memory-qualification-policy.json` (`unobservedGapBound`: twice the sampler cadence, at least
500 ms, so a single stall at the 100 ms cadence of Macs above 16 GB does not fail a take). The bound
is provisional: the first consented memory lane on the canonical M6 calibrates it, and each take
records the bound it met as `samplerUnobservedGapLimitMS`. Each take also publishes
how far its sampled peaks fell below the exact high-water marks (`gpuPeakCaptureMissMB` against
`mlxPeakMB`, and the kernel footprint ledger when sampled). Guarded pressure or `softTrim` produces
`passedWithWarnings`; the routine post-generation cache clear is counted as `policyCacheClearCount`
instead (records since 2026-09-25). A longer gap, a kernel ledger below a sample, critical pressure,
an app memory warning/exit, `hardTrim`, or `fullUnload` fails publication and leaves tracked history
unchanged. Contract-v1 records (before 2026-09-25) required at least 95% periodic coverage instead
and summed uptime-paired macOS app and engine samples. Manifest v2
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

Publication creates one `<kind>/<run-id>.json` record under `benchmarks/runs/` and regenerates
`benchmarks/HISTORY.md`; it never stages, commits, or pushes. Re-recording byte-identical evidence
is idempotent. A conflicting run ID, duplicate evidence digest, privacy violation, oversized
record, failed QC, failed finish, crash delta, missing layer, wrong take order, or unreadable WAV
fails publication and leaves tracked history unchanged. If publication fails after the expensive
run passed, retain the local artifact directory and rerun the printed `record --artifact-dir`
command after repairing the exporter.

An accepted QC warning produces `passedWithWarnings` and remains visible in run/cell warning
counts and worst-QC fields. A QC failure is never downgraded or published.

Tracked benchmark kinds (schema v3 when every take carries the quality-registry identity, schema v2
otherwise; v1 is read-only) are `ui-generation`,
`engine-generation`, `language`, `instrument-profile`, `memory-qualification`,
`prosody-calibration`, and `ui-perf` (registered 2026-08 with the macOS frame-health lane). Schema-v1
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
| `ui-perf` | `ui_test.sh macos|ios perf` via `check_macos_ui_perf.py` / `check_ios_ui_perf.py` | Structural gate PASS (nine scenarios once each, coverage/refresh sanity), canonical hardware profile, and crash delta; threshold breaches are warn-only (`passedWithWarnings`); iOS records carry the platform-aware ceilings from `config/ui-perf-thresholds-ios.json` |

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
# Seed a baseline (after an intentional, reviewed perf change, on a clean commit):
# run the gate at least three times; each run joins the staged, pooled baseline.
QWENVOICE_GATE_BENCH_SEED=1 scripts/macos_test.sh gate
# then promote the staged file (the gate prints this exact command) and commit it:
cp build/artifacts/macos/gates/staged-baseline/mac-gate-bench.json benchmarks/baselines/mac-gate-bench.json

# Seed from one finished run's own evidence instead of rerunning it:
python3 scripts/summarize_generation_telemetry.py <run-diag> \
  --run-id <run-id> --evidence-manifest <run-artifact-dir>/benchmark-evidence.json \
  --engine-only --compare-states warm \
  --seed-baseline build/artifacts/macos/gates/staged-baseline/mac-gate-bench.json

# Compare (exit 2 on regression, 3 inconclusive — usable in scripts/gates):
python3 scripts/summarize_generation_telemetry.py <run-diag> \
  --run-id <run-id> --evidence-manifest <run-artifact-dir>/benchmark-evidence.json \
  --engine-only --compare-states warm --require-baseline-identity \
  --compare-baseline benchmarks/baselines/mac-gate-bench.json
```

The committed **`benchmarks/baselines/mac-gate-bench.json`** (custom/speed/medium,
cold+warm) is a schema-v2 baseline binding the hardware profile, `-O` optimization, matrix
(including the gate's fixed sampling seed) and corpus, model artifact, evidence semantics, the
RTF definition and the OS and toolchain that measured it: `osVersion`, `osBuild`,
`xcodeVersion`, `xcodeBuild` and `swiftVersion`. Those five come from the run's own evidence (the
pre-run snapshot records them and the publisher folds them into the manifest), never from the tools
installed when the baseline is saved or compared, so a new OS or Xcode build number forces a
re-seed. It is what `QWENVOICE_GATE_BENCH=1 scripts/macos_test.sh gate` compares against — the
gate runs five warm takes with `--seed 19790615` and compares their medians (`--compare-states
warm`; the cold take is informational; the take count is part of the matrix hash, so changing it
forces a re-seed), uses an isolated runtime directory, rejects rows outside
its collision-resistant run ID, freezes the exact ordered generation selection in
`benchmark-evidence.json` before comparing, prints every threshold it used (and keeps them with
the baseline digest in `bench-verdict.json`), and reports a loaded, low-power or throttled host as
inconclusive (exit 3) rather than pass or fail. Seeded takes are token-exact, so the comparison
also reports, without a verdict, when the warm takes disagree on `generatedTokens` or differ from
the baseline's ("engine output changed").

Governed seeding (`QWENVOICE_GATE_BENCH_SEED=1`, or `--seed-baseline` on a finished run) writes
only the untracked staged file, never the committed baseline, and refuses a busy host, a dirty
tree or a warm cell with fewer takes than the gate runs (`--seed-minimum-takes 5`; the
summarizer's own default is three). A staged baseline pools the runs that share its
identity and source commit: each cell keeps the median of the per-run medians and the between-run
range, and once it pools three runs that range becomes a threshold basis, so no seed run
regresses against the baseline it built. Seed at least three runs from one clean commit, then
promote. With `--require-baseline-identity` (the gate passes it) an identity mismatch exits 1 and
the gate reports BASELINE INVALID with the exact seed command for that run's paths; the gate's
preflight predicts the same mismatch from the live host and the gate matrix before any build.

The committed baseline is the first canonical Mac mini M6 baseline (AV-17 step 1, 2026-09-25): three
seeded gate runs from commit 848e140a on `mac-mini-m6-16gb` (`mid_16gb_mac`, macOS 27.0 26A428,
Xcode 27.0 27A266a), whose between-run ranges were at most 0.7% for RTF, first chunk and tokens per
second and 1.9% for footprint, so every threshold sits at its floor. A new OS or Xcode build number
changes the identity and needs a re-seed; the retired M2 baseline stays in git history only.
Markdown snapshots (`benchmarks/baseline-*.md`) remain the human-readable full-matrix references;
diff them with `git diff`, not `--compare-baseline`.

### Like-for-like comparison rules

Never compare numbers across topologies — each is a different measurement, not a
regression signal:

| Lane | Build | Topology | Headline custom/speed/medium warm |
|------|-------|----------|-----------------------------------|
| `build.sh cli-optimized` CLI bench | hash-bound `-O` | in-process | Shipping-optimization backend result; compare only with the same optimization identity |
| local release / `-O` CLI | optimized | in-process | legacy `decodeSpeedupX` ≈ 1.7 (records before 2026-09-12) |
| macOS `ui_test.sh macos benchmark` | Release app | app (in-process engine; app + XPC service before 2026-09-15) | legacy `decodeSpeedupX` ≈ 1.7 (records before 2026-09-12) |
| iOS `ios_device.sh bench` | `-Onone` device | in-process on iPhone | legacy `decodeSpeedupX` ≈ 1.6–1.9 (records before 2026-09-12) |
| iOS `ui_test.sh ios benchmark` | `-O` Release app | in-process, real Studio UI | optimized frontend/device result; do not compare with the `-Onone` headless lane |

The speedup figures above are the inverted pre-cutover measure (audio ÷ decode seconds, higher is
faster); headline standard `rtf` values live in generated `HISTORY.md` and are never compared with them.

Tracked comparison keys include the exact optimization identity, toolchain, OS, model identity,
matrix, and hardware profile (executable hashes are provenance, never identity). Legacy records
also key on whole-tree project and harness hashes. Records stamped with a lineage contract
(`inputs.lineageContractVersion`, `scripts/lib/lineage_identity.py`) key instead on what their kind
measures: the project.yml build settings its lane builds, the take topology (the layer set) and the
kind's reviewed measurement version; contract 2 (the current one) adds a forced or emulated memory tier
(`run.runtimePolicy`) and the run's seed policy (`run.seedPolicy`), while contract-1 records keep their
keys. Harness and engine edits therefore keep a lineage (HISTORY
marks "harness changed"), while a scheme, compiler-setting, topology, model or definition change
starts a new one; a change that alters what a kind measures bumps its measurement version.
`python3 scripts/benchmark_history.py lineage-replay [--kind K --platform P]` replays the current
contract over committed records from their own source commits, read-only. Consequently a
historical `-Onone` record cannot become the baseline for a new `-O` record; the first clean
optimized record reports an explicit no-baseline state.

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

`scripts/prosody_quality_gate.py` on individual takes; `vocello bench --delivery` runs the paired
`scripts/bench_delivery_prosody.py` analysis itself.

### Layer 2.5 — Language hint contract (Phase 2)

Headless matrix (`scripts/ios_device.sh lang-bench` or `scripts/macos_test.sh lang-bench`)
stamps `notes.languageHint` (resolved Qwen3 token, not raw UI picker). Gate with
`scripts/check_language_hints.py` against `config/language-bench-matrix.json`.
Offline fixture self-test: `python3 -m pytest scripts/tests/test_check_language_hints.py` (or
`scripts/dev.sh py` after editing the gate).

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
| `…/app/generations.jsonl` | UI timings |
| `…/generations-merged.jsonl` | Joined layers (macOS) |
| `…/engine/samples-<UUID>.jsonl` | Verbose per-sample series |
| `QwenVoice-Debug/outputs/bench/*.wav` | Bench WAV outputs (fixed per-cell filenames — overwritten across seeds) |
| `…/outputs/bench-archive/<runID>/` | Durable per-run evidence for every `--delivery` run: all take WAVs plus `bench-results.json`, `bench-prosody.json`, `bench-quality-composed.json`. Fail-closed for required files, written before the sidecar analysis; unbounded, prune manually. Successful diagnostics run dirs are cleaned after publication, so multi-run scoring reads from this archive ([`delivery-harness.md`](delivery-harness.md) §3) |
| `<run-artifact-dir>/benchmark-evidence.json` | Atomic run-scoped validator selection and verdict used for publication |
| `build/**/*.xcresult`, screenshots | UI evidence retained locally under bounded lane retention |
| `build/**/profiles/` | Compact local profile summaries; a CPU profile's raw `*.trace` is success-ephemeral unless `--keep-trace` was explicit, a memory profile's is kept by default (prune manually) |

Auto-pruned: `generations.jsonl` ~8 MB cap; verbose sidecars newest-48 / 64 MB for ad-hoc
diagnostics. `vocello bench --telemetry verbose` sizes the sidecar budget to its own plan before any
model loads (at least one sidecar per planned take and TTFC probe, the same per-sidecar byte
allowance) and refuses a plan above 256 generations, so a full default matrix (58 takes) keeps every
sidecar publication needs (`GenerationTelemetrySidecarBudget`).

### Committed (bounded)

| Path | Rule |
|------|------|
| `benchmarks/runs/` | One canonical allowlisted `<kind>/<run-id>.json` record per successful run, ≤ 256 KB; only `annotate` may update listening review |
| `benchmarks/HISTORY.md` | Generated registry index (`scripts/benchmark_history.py rebuild-index`, run by publication; `rebuild-index --check` runs in the contract gate); the generated-file guard hook refuses hand edits |
| `benchmarks/LEGACY_HISTORY.md` | Preserved incomplete manual history; never promoted to complete registry evidence |
| `benchmarks/hardware-profiles.json`, `schema-v3.json`, `schema-v2.json` (both published today), `schema-v1.json` (read-only) | Canonical hardware identities plus the record contracts |
| `benchmarks/baseline-*`, `OPTIMIZATION.md` | Existing reference snapshots and historical optimization narrative |

The exporter uses a strict allowlist and rejects serials/UDIDs/ECIDs, host/device/user names,
absolute paths, prompts/transcripts/voice descriptions, raw errors, emails, URLs, and secret-like
labels. **Never commit raw JSONL, WAVs, screenshots, result bundles, or traces** under `benchmarks/`.

### CI / automation

- `.github/workflows/ci.yml` — `ios-compile` job (generic device-SDK compile of `VocelloiOS` and the policy-test bundle; no UI, no bench, no device)
- `.github/workflows/release.yml` — deterministic signing and packaging; UI lanes remain explicit/local
- `scripts/check_project_inputs.sh` — validates all compact records and checks that `HISTORY.md` is reproducible
- Explicit frontend acceptance: `scripts/ui_test.sh macos smoke|benchmark`
- Deterministic macOS platform gate: `scripts/macos_test.sh gate` (does not consume UI results)

The engine regression net is a consent-bound local lane by design; ordinary CI never runs a model, a
device or XCUITest.

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
