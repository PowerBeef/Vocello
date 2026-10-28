---
status: active
owner: release-qa
reviewed: 2026-10-28
summary: The single telemetry and benchmarking reference — which benchmark lane to run, preflight and the macOS CLI/app and iOS device procedures, the Phase 2-3 language bench, per-generation typed telemetry schemas and fields, PASS-only publication, lineage and baselines, and the artifact map.
sourceOfTruth:
  - Sources/QwenVoiceCore/NativeTelemetrySampler.swift
  - scripts/macos_test.sh
  - scripts/ios_device.sh
  - scripts/ui_test.sh
  - scripts/benchmark_history.py
  - scripts/check_language_hints.py
  - scripts/check_language_output.py
  - scripts/lib/language_metrics.py
  - scripts/audio_qc_script_pool.py
  - config/memory-qualification-policy.json
  - config/macos-ui-stall-gate.json
  - config/language-bench-matrix.json
  - benchmarks/baselines/mac-gate-bench.json
---
# Telemetry and benchmarking

How Vocello measures itself: when to bench and which lane to run, how to drive each platform path,
the language bench, the per-generation telemetry that spans the **frontend (app UI)** and the
**backend core (MLX / Qwen3-TTS)** — one process on macOS and iOS since 2026-09-15 — and how
evidence is published and where it lives. Telemetry stays cheap enough to run on restricted
hardware (8 GB Macs, iPhone) without distorting the numbers you optimize against. For CLI flags see
[`cli.md`](cli.md) §bench.

If anything here disagrees with the code, the code wins — fix this file.

**Contents**

1. [Which lane to run](#1-which-lane-to-run)
2. [Preflight and switches](#2-preflight-and-switches)
3. [Matrix semantics](#3-matrix-semantics)
4. [Standard workflows](#4-standard-workflows)
5. [Language bench](#5-language-bench)
6. [Telemetry schemas and fields](#6-telemetry-schemas-and-fields)
7. [Reading results](#7-reading-results)
8. [Publication, lineage and baselines](#8-publication-lineage-and-baselines)
9. [Artifact map](#9-artifact-map)
10. [Troubleshooting](#10-troubleshooting)
11. [Related documents](#11-related-documents)

---

## 1. Which lane to run

### When to run a benchmark

Run a benchmark when you change anything that can affect **decode throughput**, **memory
peaks**, **first-chunk latency**, or **audio quality**:

- MLX / owned Qwen3-TTS core runtime or Mimi codec
- Memory policy, streaming interval, idle-unload, in-process relief
- Model load path, prewarm, clone conditioning
- Before explicitly promoting engine-adjacent work or cutting a macOS/iOS release

Benchmarks that require models, a device, or XCUITest are not prerequisites for a
commit, push, pull request, ordinary merge, ordinary CI run, or release package. They remain useful
promotion and release-QA evidence at the checkpoints a task or release names (full matrices are
task- or release-specific).

### What “good” means

A benchmark pass requires **all** of the following:

| Gate | Criterion |
|------|-----------|
| **audioQC** | Publication accepts `pass` or `warn`; promotion requires `pass` in every required cell. Any `fail` blocks both. |
| **RTF** | `derivedMetrics.realTimeFactor` (request wall ÷ audio, lower is faster; [§6.8](#68-derived-kpis-derivedmetrics)) reviewed against the nearest compatible clean record in generated [`benchmarks/HISTORY.md`](../../benchmarks/HISTORY.md). |
| **Memory** | No rising `physFoot` peak or non-zero `hardTrim` in `trims` on floor-tier runs. |
| **Automated output proof** | Fixed-seed cohort, exact WAV identity, and applicable locale-locked ASR/prosody gates pass. Human listening is optional annotation and is never inferred. |

The decode-loop speedup that older documents and records called "RTF" is now `decodeSpeedupX` /
the summarizer's `xRT` column.

### Principles

1. **The primary backend driver is headless.** `vocello bench` drives the matrix in-process with
   exact cold/warm control; `scripts/ui_test.sh macos benchmark` is the supplementary UI
   integration net ([§4.10](#410-macos-ui-benchmark-supplementary-integration-net)). XCUITest is
   the only automated UI evidence; deterministic history/WAV/backend probes validate its smoke
   and benchmark results. iOS UI tests and real-engine generation run **on-device only**, on a
   paired physical iPhone (see [`testing-runbook.md`](testing-runbook.md) and
   [`ios-device-testing.md`](ios-device-testing.md)).
2. **Runtime-gated, never compiled out.** There is one shippable config; dev and release run
   identical code (see root `CLAUDE.md`). Telemetry is switched on at runtime by `TelemetryGate`
   ([§2](#telemetry-gate)), not by `#if DEBUG`. When the gate is off, every probe is a no-op and
   nothing is written.
3. **Correlated by `generationID`.** The app mints a `UUID` per generation and threads it down;
   the engine reuses it. Every layer keys its rows on that one ID so they join.
4. **Cheap on the hot path.** No per-chunk file I/O, no per-chunk allocations or MainActor hops
   added by telemetry. Per-generation work happens at boundaries; the memory sampler runs on a
   background task at a device-tiered cadence.
5. **Measure, don't perturb.** The fine-grained backend timings read clocks around work that
   already happens (including the GPU syncs that generation requires); telemetry does not add
   synchronization ([§6.12](#612-overhead-and-observer-effect)). Decode-breakdown columns are
   Swift wall-clock around lazy MLX graph ops, not per-stage GPU compute; use Instruments
   signposts for GPU attribution ([§7.3](#73-decode-breakdown-lazy-mlx)).
6. **Select one run, never a directory history.** Benchmark validators emit an atomic
   `benchmark-evidence.json` with the exact ordered generation IDs and cells. Summaries and the
   tracked registry consume that manifest plus its run ID; unrelated historical rows are ignored.
7. **Process ownership stays explicit.** Memory and resource deltas remain on the process that
   measured them. macOS and iOS UI evidence require app + engine (records before 2026-09-15 also
   carried an engine-service layer). A partial merge is marked incomplete and cannot publish
   history.
8. **No CI execution gate.** Routine CI validates evidence contracts and indices without models,
   devices, native UI or Instruments; GitHub CI executes Foundation-level iOS policy assertions on
   the macOS host and stays compile-only for iOS binaries. Targeted local benchmark/model/device/UI
   validation is authorized at coherent committed checkpoints; full matrices remain
   task/release-specific. Join workers and respect host serialization/load/memory checks. Reuse
   installed assets; new large downloads, dependency changes and publication need a specific
   request. See [`tooling-and-evidence.md`](tooling-and-evidence.md).
9. **PASS-only publication.** A successful repository benchmark publishes one allowlisted JSON
   record and regenerates `HISTORY.md`; successful records, historical baselines and generated
   indexes are tracked, bounded by the `benchmarks/` cap. Failed or incomplete runs leave tracked
   history unchanged; raw telemetry, audio, screenshots, traces, and result bundles remain
   untracked ([§8](#8-publication-lineage-and-baselines)).

### Platform topology

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
| **macOS UI frame health** | `scripts/ui_test.sh macos perf` | No engine claims (UI-only) | Eleven scripted SwiftUI scenarios with the in-app frame probe; warn-only ceilings; canonical-hardware runs publish `ui-perf` registry records; lane contract in [`macos-testing.md`](macos-testing.md) (history: [the 2026-08 macOS UI audit](../audits/2026-08-04-macos-ui-refresh.md)) |
| **iOS UI frame health** | `scripts/ui_test.sh ios perf` | No engine claims (UI-only) | Nine scripted scenarios on the paired physical iPhone with the pinned-60 Hz in-app probe; `check_ios_ui_perf.py` structural + canonical-hardware gate with warn-only ceilings from [`config/ui-perf-thresholds-ios.json`](../../config/ui-perf-thresholds-ios.json); canonical-iPhone runs publish platform-`ios` `ui-perf` registry records; lane contract in [`ios-device-testing.md`](ios-device-testing.md) (history: IUI-6, [the 2026-08 iOS UI audit](../audits/2026-08-29-ios-ui-refresh.md)) |
| **Language bench** | `scripts/macos_test.sh lang-bench` / `scripts/ios_device.sh lang-bench` | In-process | Language hint contract and spoken-output verification ([§5](#5-language-bench)) |

**Important:** CLI bench numbers are **not** identical to macOS UI numbers. Compare like with
like (CLI vs CLI, UI vs UI). Use CLI for backend optimization; use the UI lane for integration
regressions.

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
the benchmark machine, not the floor ([§4.4](#44-floor-tier-forced-run)). A macOS benchmark run
refuses to start unless
`python3 scripts/publish_benchmark_history.py verify-hardware --platform macos` confirms the live
host is the canonical profile.

Records also capture current OS build, thermal/low-power state, sanitized transport, toolchain,
executables, input/model fingerprints, and source state. A dirty success is `exploratory`, not a
canonical trend point. Profiles and forced-memory-class diagnostics are not compared with normal
timing records. Engine and macOS UI benchmark records published since 2026-09-25 also carry
`run.runtimePolicy` (`deviceClass`, `deviceClassForced`, and `simulatedPhysicalMemoryMB` on an
emulated smaller Mac), taken from the rows' own stamps, so a record proves which memory tier it
measured; the validator refuses a native tier on the wrong platform and a forced tier on a
comparable record.

---

## 2. Preflight and switches

Run before any benchmark session.

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

Do not derive a Clone fixture from a Built-in Voice output: the canonical fixture is generated
through Voice Design and its provenance is verified by the repository model-preparation helper.
The `scripts/macos_test.sh` model lanes verify the fixture themselves before running
(`scripts/macos_test.sh preflight --strict-models` fails when anything is missing; `models check`
prints read-only status); bare `xcodebuild` performs no such check.

### Environment hygiene

| Check | Action |
|-------|--------|
| Quiet machine | Timing lanes refuse to start on a busy host (`require_quiet_host` exits 1 before any model loads; [`tooling-and-evidence.md`](tooling-and-evidence.md), Host preflight, owns its thresholds, worker rules and the exploratory override; it guards the `macos_test.sh gate` bench (`QWENVOICE_GATE_BENCH=1`; the deterministic gate alone does not check) and `macos_test.sh profile|memory|lang-bench|qc-takes|telemetry-overhead`, `ios_device.sh bench|lang-bench|memory|gate` and the `ui_test.sh` benchmark and perf lanes). Engine and UI benchmark takes (macOS and iPhone) also keep their own one-minute load (`metrics.loadAverage1M`): publication marks an engine or UI benchmark record exploratory when any take exceeded 1× the core count of its canonical profile, and the gate bench is inconclusive (exit 3) when its busiest warm take exceeded 2×. Quit heavy apps and watch thermals ([§7.5](#75-thermal-and-environment)). |
| Free disk | Heavy lanes check the floors in `config/build-output-policy.json` before building or launching (`require_build_free_space`, `scripts/lib/storage_preflight.py`): 15 GiB for `ui_test.sh … benchmark`, macOS/iOS `memory`, `lang-bench`, macOS `qc-takes` and iOS `bench`/`gate`; 12 GiB for `telemetry-overhead` and `ui_test.sh … perf`; 8 GiB for `macos_test.sh gate`. A shortfall stops the lane before any work starts. |
| Single Vocello session | Quit any separately installed Vocello first. The XCUITest runner verifies exact executable paths and signals only its own Release products. |
| Debug data dir | `QWENVOICE_DEBUG=1` → `~/Library/Application Support/QwenVoice-Debug/` (written `QwenVoice-Debug/` below), so real data is never polluted. |

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

### Telemetry gate

Telemetry persistence is governed by **`TelemetryGate`** (`Sources/QwenVoiceCore/TelemetryGate.swift`),
resolved once per process:

| Source | Effect |
|---|---|
| `QWENVOICE_DEBUG=1` (env) | On in any process that inherits it (e.g. `./scripts/build.sh run`), unless `QWENVOICE_NATIVE_TELEMETRY_MODE=off` says otherwise. |
| In-process latch | `vocello bench` latches its `--telemetry` mode through `TelemetryGate.applyHandshakeMode(_:)`; a latched `off` keeps telemetry off for the rest of the process. There is no persisted Settings tap-toggle. |
| `QWENVOICE_NATIVE_TELEMETRY_MODE=off` (alias: `disabled`) | Off, and it wins over `QWENVOICE_DEBUG=1`: the debug switch still unlocks registered runtime overrides (`RuntimeDebugGate`, which keeps needing the internal-diagnostics build), but it cannot turn back on telemetry a run disabled. |
| `QWENVOICE_NATIVE_TELEMETRY_MODE=lightweight\|verbose` (aliases: `light`, `full`, `deep`) | Forces sampling/persistence on regardless of the gate. |

The engine runs **in process on macOS and iOS** (the macOS XPC service was retired on 2026-09-15 and the
iOS ExtensionKit extension earlier; see [`ARCHITECTURE.md`](../ARCHITECTURE.md)), so it reads the
host process's own environment; no handshake relays a mode. Telemetry opt-in is distinct from
production-affecting overrides, which additionally require the registered internal-diagnostics
build capability and debug gate. Do not claim that all telemetry code is compiled out of
distributed binaries.

### Sampling modes

`NativeTelemetryMode`, in `SemanticTypes.swift`:

| Mode | `QWENVOICE_NATIVE_TELEMETRY_MODE` | Memory sampler | Raw per-sample series |
|---|---|---|---|
| `off` | `off` / `disabled` | — | — |
| `lightweight` (default when gate on) | `lightweight` / `light` | device-tiered cadence | no |
| `verbose` | `verbose` / `full` / `deep` | device-tiered cadence | **yes** (sidecar) |

`NativeTelemetryWorkPlan` makes the off contract explicit: no recorder, sampler, sink,
per-chunk QC, or expensive derived diagnostics are constructed. The engine builds its stage
recorder only when the gate is on and the mode is not off, and writes engine rows, raw sample
sidecars, streaming v9 sidecars and the published-WAV digest only through the plan's `writesSink`.
`vocello bench --telemetry off` sets the off mode and latches it, so the off arm stays off although
its runtime overrides set `QWENVOICE_DEBUG=1`; the telemetry-overhead lane
([§4.12](#412-telemetry-overhead-parity-lane)) verifies it.

Typical backend-optimization invocation:

```sh
QWENVOICE_DEBUG=1 QWENVOICE_NATIVE_TELEMETRY_MODE=verbose ./scripts/build.sh run
```

### Runtime knobs

`config/runtime-debug-knobs.json` owns this inventory, read in-process by the engine's host.
Production-affecting knobs are read through `RuntimeDebugGate` and require both
`VOCELLO_INTERNAL_DIAGNOSTICS` and `QWENVOICE_DEBUG=1`; distributed builds omit the capability.
Bounded observability and test-target-only keys are separately classified. Generation telemetry
binds active override key names and a digest of their values without retaining raw launch input.
Never add an undocumented environment reader.

| Env | Effect |
|---|---|
| `QWENVOICE_SUPPRESS_WARMUP=1` | Skips proactive prewarm/clone-priming so the first generation records its own **cold** load (`MacGenerationWarmupCoordinator`); use it for accurate Custom/Design cold rows in UI runs. App-process only. |
| `QWENVOICE_FORCE_MEMORY_CLASS=floor_8gb_mac` | Forces the device-memory tier (`NativeDeviceClassGate`), read in-process by whichever host runs the engine (the app or `vocello bench --force-class`), so constrained-tier code paths run for diagnostic comparison ([§7.6](#76-memory-and-pressure-interpretation)). Accepts the `NativeDeviceMemoryClass` raw values (`floor_8gb_mac`, `mid_16gb_mac`, `high_memory_mac`, `iphone_pro`) or the aliases `8gb`/`16gb`/`high`/`iphone`. Exploratory only. |
| `QWENVOICE_SIMULATED_PHYSICAL_MEMORY_GB=8` | **Floor emulation on a larger Mac** (`NativeHostMemoryEmulation`, audit #11): the whole 8 GB machine (tier, footprint bands, Metal working set), not just the tier's policy. Exploratory only; see [§4.4](#44-floor-tier-forced-run). |
| `QWENVOICE_BENCH_SEED_POLICY=cell-hash-v1` | **UI benchmark seed policy** (`BenchSeedPolicy`, audit #29): every generation samples with the seed of the benchmark cell it measures (the first eight bytes of SHA-256 of `vocello-ui-bench-seed-v1`, NUL, the cell ID such as `custom/short/warm#1`), replacing a draft's pinned seed; the cell comes from `QWENVOICE_BENCH_SEED_CELLS` (a comma-separated launch schedule consumed one per generation, the iPhone lane) or else the benchmark's current-take file (macOS). Rows stamp `notes.samplingSeedPolicy`; the lane checkers and the history validator recompute each take's seed (`scripts/lib/bench_seed.py`) and the record names `run.seedPolicy`. `scripts/ui_test.sh <platform> benchmark` sets it by default (`--seed-policy generated` keeps random seeds). |
| `QWENVOICE_MAC_WARM_GATE=off\|records\|enforce` | macOS warm-admission gate (`MacWarmupAdmissionPolicy`): defers **proactive** warms while the app-process kernel pressure level is soft/hardTrim on every Mac tier (the high-memory Mac since AUD-10). Default `enforce` (validated 2026-06-09); `records` logs verdicts without blocking; user generations are never gated. Events land in the app layer's `native-events.jsonl`. |
| `QWENVOICE_MARKING=off` | Disables both publication marks only in a repository-built internal diagnostics binary with the master gate enabled. It exists for A/B isolation of the marking pass, is unavailable in distributed builds, and must never be set for canonical records. |
| `QVOICE_TALKER_KV_QUANT=8\|4` | **Dev-only** opt-in talker KV-cache quantization (QuantizedKVCache, group 64). Measured (P4, §H): clone/long −271 MB physFoot but **−8.6% decode speedup** (`decodeSpeedupX`; pre-2026-09-12 "RTF") — not shipped on any tier; insurance knob only. Never combined with `QVOICE_TALKER_KV_WINDOW`. |
| `QVOICE_IOS_MLX_CACHE_LIMIT_MB=<n>` | **Dev-only** override of the MLX `Memory.cacheLimit` for the iPhone tier. Useful for sweeps; production uses the tier default. |
| `QVOICE_IOS_MLX_MEMORY_LIMIT_MB=<n>` | **Dev-only / do not ship** override of MLX `Memory.memoryLimit`. Production avoids a hard `memoryLimit`; see `mlx-guide.md` §5.2. |
| `QVOICE_IOS_MEMORY_PROFILE=iphone15pro` | **Physical-device memory-profile diagnostic**: clamps the effective per-process limit inside `IOSMemorySnapshot.capture()` so bands/admission/clone-gate use the smaller-device budget (`iphone15pro` → 5,000 MB). Rows stamp `notes.memoryProfile` and `notes.simulatedProcessLimitMB`. GPU compute and thermals remain those of the connected device; this is not proof for a different device. Driven by `ios_device.sh bench --memory-profile` ([§4.7](#47-ios-on-device-bench)). |

---

## 3. Matrix semantics

### Fixed corpus

Defined in `BenchMatrixSpec` (`Sources/QwenVoiceCore/BenchMatrixSpec.swift`; shared with
`BenchCommand` and the UI bench) — do not change without updating baselines:

| Bucket | Chars (approx) | Text role |
|--------|----------------|-----------|
| short | < 70 | One sentence |
| medium | 70–220 | Two sentences |
| long | > 220 | Extended narration |

`lenBucket()` in Swift and Python must agree (bench fails on corpus drift). The iPhone UI
benchmark keeps a fixed 150-character `long` text ([§4.7b](#47b-ios-ui-benchmark-studio-matrix--xcuitest)).

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

The CLI forces cold via awaited explicit unload before the cold take; unload/load failure stops the
matrix instead of inventing a warm/cold label. Ordinary Clone uses explicit model loading and
reference priming before its first measurement ([§4.3](#43-full-6-cell-matrix-speed--quality)).
UI cold takes use an app relaunch + `QWENVOICE_DEBUG=1` + `QWENVOICE_SUPPRESS_WARMUP=1` +
`QWENVOICE_BENCH_FORCE_COLD=1` (master-gated unload before generate); warm takes stay in-session.

Each engine row identifies its cell through `mode`, variant-specific `modelID`, and `warmState`.
For Built-in Voice and Voice Design, each accepted cold row must show `"warmState":"cold"` and carry
`upstreamModelLoad` in `stageMarks`; warm rows show `"warm"`. Clone is normally warm because
reference conditioning primes the model, so a missing Clone cold row is expected unless this
procedure explicitly changes that contract; a Clone cold row that does appear is a hard failure
([§10](#10-troubleshooting)).

### Streaming default

`vocello bench` streams by default (`--no-stream` for legacy quality-first accumulation).
Streaming populates `chunkTimeline`; non-streaming leaves it empty.

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
missing or contradictory state blocks publication. The retained-memory protocol
([§4.11](#411-retained-memory-qualification)) does not preload Clone: its first `retained#0` take
remains cold. Historical records are immutable.

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
option b); the M2 history stays the floor's only timing and pressure evidence. There is no second
canonical host: the floor is emulated on the M6 with `QWENVOICE_SIMULATED_PHYSICAL_MEMORY_GB=8`
(`NativeHostMemoryEmulation`, registered in `config/runtime-debug-knobs.json`; it needs the
internal-diagnostics build and `QWENVOICE_DEBUG=1`, which every repository lane sets). Only a
smaller Mac can be emulated. The host then reads as an 8 GB Mac wherever policy reads the machine:
`NativeMemoryPolicyResolver.deviceClass()` resolves `floor_8gb_mac` with its policy, the store's
footprint bands (`MacMemoryBudgetPolicy`) are the floor's (guarded at 55%, critical at 72% of
8 GiB), and the snapshot reports 8,192 MB of RAM and a Metal working set of two thirds of it
(5,461 MB), so every row's `gpuRecommendedWorkingSetMB` reads about 5,461, `totalDeviceRAMMB`
8,192, and `gpuWorkingSetUsageRatioPeak` judges the floor's budget. A forced class alone keeps the
M6's bands and working set; use the emulation for floor evidence.

```sh
# Engine footprint and policy on the emulated floor (vocello bench rows)
QWENVOICE_DEBUG=1 QWENVOICE_SIMULATED_PHYSICAL_MEMORY_GB=8 ./build/vocello bench \
  --modes custom,design,clone --variants speed --lengths medium --warm 3 --label "floor-emulated"

# The retained-memory protocol on the emulated floor
QWENVOICE_SIMULATED_PHYSICAL_MEMORY_GB=8 scripts/macos_test.sh memory --label floor-emulated

# The app's bands on the emulated floor (the runner hands the knob to the app)
QWENVOICE_SIMULATED_PHYSICAL_MEMORY_GB=8 scripts/ui_test.sh macos benchmark --label floor-emulated
```

Each follows the same targeted checkpoint and quiet-host policy as its unemulated form. The rows
stamp `notes.deviceClassForced=true`, `notes.simulatedPhysicalMemoryMB` and
`notes.simulatedMetalWorkingSetMB`; the publisher classifies every such record `exploratory`
(never canonical, never comparable, never a baseline or a chart point) and the record's
`run.runtimePolicy`, on engine and macOS UI benchmark records alike, names
`simulatedPhysicalMemoryMB` beside the forced floor tier. Lineage contract 2 (2026-09-25, audit #11
option b) reads that block: an emulated or forced record gets a comparison key of its own, so
`benchmarks/HISTORY.md` groups the emulated-floor runs in their own M6 section instead of among the
host's records. Records stamped with contract 1 (the first M6 gate records) and legacy records keep
their stored keys; a published key is never edited in place. An emulated or forced record is still
excluded from every comparison: it gets no baseline or deltas and is never another record's baseline,
and HISTORY names its classification `exploratory (emulated 8192 MB)` (a forced class alone reads
`exploratory (forced <tier>)`) with the comparison `excluded`. The band paths reuse the store's
existing knobs: `QVOICE_IOS_MEMORY_GUARD_FORCE_BAND=guarded` or
`QVOICE_IOS_MEMORY_GUARD_FORCE_CRITICAL_ONCE=1` (the Mac hosts the same store), which the UI
benchmark lane also hands to the app. A forced band trims or unloads, which fails memory
qualification by design, so such a run is a band-path diagnostic that keeps its artifacts and
publishes nothing.

What the evidence can claim is **policy and footprint**: the floor tier's policy values (256 MB MLX
cache, the per-generation clear, the 0.6 s streaming interval, the skipped dedicated custom
prewarm, the 2-minute idle unload, one clone cache slot), the footprint each take reaches against
the floor's bands, and Metal allocations against the floor's working set. The kernel still has
16 GB: it cannot claim kernel memory pressure, compression, swap or the real Metal budget of an
8 GB Mac, and M6 timings say nothing about the floor's speed. A pressure balloon that would
reproduce pressure needs its own quiet-host exemption and is not part of this path.

### 4.5 Memory-pressure exercise

While a generation is running on forced floor tier:

```sh
sudo memory_pressure -S -l warn    # or: -S -l critical
```

Then summarize and confirm non-zero `trims` / `memory_pressure` stage marks.

### 4.6 Delivery / prosody cells

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
the delivery comparison; the summarizer then prints that current prosody block (`prosEff` /
`dF0Std` / `dRateCV` / `dPauseR` / `dRough`). A benchmark without `--delivery` does not run that
paired gate. Every delivery take also receives the per-preset adherence verdict (`deliveryGate`
beside `qualityGate` in `bench-prosody.json`; a diagnostic since gate v3) and its cell's verdict
(`deliveryCellGate`, the adherence verdict; see **Cell verdict** below), and the run composes
canonical-depth registry verdicts across all seven gates (`bench-quality-composed.json`; a cell too
small to judge, and a clean verdict of the uncalibrated prosody gate, compose as `uncalibrated`,
never as a pass; a gate that abstains composes as `abstained`, which the summary counts and the run
refuses as inconclusive, though no gate abstains yet).

**Cells and sweeps.**

- Cells are `<preset>.<intensity>`. `vocello deliveries --shipped-only --json` is the
  machine-readable authority for the eight product-visible cells and their exact instructions; do
  not reconstruct the shipped-tier policy in a shell script. Each cell generates one instructed
  warm take.
- The plain warm take is the neutral reference for every paired delta, so `--warm 0` is rejected
  with `--delivery`.
- Clone is excluded: the clone checkpoints have no instruction channel, so delivery cells run for
  Built-in Voice and Voice Design only.
- A multi-seed sweep loops one invocation per seed; a fixed seed reproduces its takes exactly. Use
  zsh brace expansion for seed ranges (`for seed in {20260810..20260827}; do … --seed $seed …;
  done`): macOS `seq` renders 8-digit integers in scientific notation, which the CLI rejects.
- Arms (for example two quantizations) are told apart by `--label` and by each take's `modelID` in
  `bench-results.json`; filter on both when collecting.
- An ordinary run stays fail-fast when mandatory Fast QC rejects a take. The diagnostic-only
  `--continue-delivery-failures` (it requires `--delivery` and `--no-summary`) records one typed
  success or failure for every attempted cell and preserves rejected WAVs, so a failed take stays
  in the denominator; such a run is never eligible for history publication.
- `--no-cold` (it requires `--delivery`) skips the Built-in Voice and Voice Design cold take, which
  no delivery analysis pairs (about 11.5% of sweep time). It loads the model explicitly, runs the
  cold length's prewarm itself and fails if that prewarm did not run. The 8 GB tier defers the
  Built-in Voice prewarm into the first generation, so there `--no-cold` refuses a Built-in Voice
  sweep. The run has no `cold#0` cell and records `coldTakes: false`; it is a delivery sweep, not a
  timing benchmark.

**Instruction provenance (fail closed).** A delivery measurement is only as good as its proof that
the instruction entered the engine:

1. The request payload carries the instruction (`GenerationRequest.Payload.deliveryInstructionText`;
   nil for clone).
2. The engine stamps a receipt on the take's telemetry row: `notes.instructChars` and
   `notes.instructDigest`, the SHA-256 of the instruction text
   (`Sources/QwenVoiceCore/GenerationOutputAdapter.swift`).
3. `scripts/bench_delivery_prosody.py` fails closed per instructed cell unless the receipt exists,
   its digest matches the manifest's `deliveryInstruction` echo, and the paired neutral reference
   carries no receipt (an instruction on the reference would poison every delta).

`notes.promptChars` counts only the script text, which never includes the instruction, so it proves
nothing about delivery. Exercise every new fail-closed check live in the change that lands it: a
check proven only on synthetic fixtures can be fixture-true and live-false.

**Cell verdict.** Since delivery gate v3 the per-take adherence flags are diagnostics: the record
publishes their count, `deliveryTakeFlagCount`, never a warning. The adherence verdict judges every
take of one cell (mode, model, speaker, length, preset and intensity) together. A required feature
flags `cell_direction_miss_<feature>` when the cell's median signed effect is not positive and
`cell_effect_weak_<feature>` when it sits below the floor; a supporting feature flags
`cell_supporting_miss_<feature>` only when the median moves past the floor the opposite way. A cell
with fewer than five takes is `insufficient`, so a single-seed run's cells compose as
`uncalibrated`, never `pass`, and the history publisher warns `delivery_cell:<flag>` only for a cell
that was judged. The floors were measured before the 2026-08-25 instruction rewrite, so they are
provisional: the verdict warns and never fails.

**Analyzer boundary.** `scripts/analyze_prosody.py` is deterministic, bounded-memory PCM analysis.
Analyzer algorithm v3 (adds the `voice_*` and `spectral_*` proxies) reads the persisted PCM16 in
exactly two fixed-block passes, retains no whole-file PCM or frame matrix, adds semitone-relative
pitch and caller-declared boundary continuity summaries, and reports bounded
managed-buffer/working-set evidence. Its fixed-bin quantiles may differ slightly from the legacy
full-array algorithm, so the algorithm version is carried by newly calibrated profiles and results.
Its synthetic contracts cover silence and noise rejection, pause placement, voiced-harmonic and
spectral behavior, repeatability, and an 80–390 Hz harmonic F0 sweep with at most 1% error. That
establishes implementation correctness, not perceptual ground truth. Thresholds and
delivery-effect weights come from a JSON prosody profile (`scripts/prosody_profile.py`); the
built-in profile, used when `--prosody-profile` supplies none, was calibrated on earlier generated
takes, not on an independently labelled holdout. A delivery effect shows that presets reach different acoustic
regions, not that they sound like the named delivery. The delivery bench keeps its own analyzers
(QC-07 declined 2026-10-02: QC v2 measures pitch and identity for clones only).

**Evidence.** Every delivery run keeps a durable copy under
`QwenVoice-Debug/outputs/bench-archive/<runID>/`: all take WAVs plus
`bench-results.json` (the immutable manifest), `bench-prosody.json` (the paired-delta sidecar) and
`bench-quality-composed.json`. Archiving is fail-closed for required files and happens before the
sidecar analysis, so an analysis-failed run keeps its audio; the archive is unbounded, so prune it
manually. A successful run's `diagnostics/benchmark-runs/` directory is removed after publication,
so multi-seed scoring reads from the bench archive. Compact PASS records go to `benchmarks/runs/`
inside their parent `engine-generation` record.

### 4.6b Fidelity lanes (engine/artifact promotion battery)

Every engine or artifact promotion runs the three fidelity lanes introduced with the
2026-08-01 delivery-fidelity programme:

```sh
# 1. Preset adherence — paired delivery matrix; canonical composed verdicts.
QWENVOICE_DEBUG=1 ./build/vocello bench --modes custom --variants speed --lengths medium \
  --warm 1 --delivery happy.strong,calm.normal,whisper.normal --seed <fixed> --label "promo-delivery"

# 2. Neutral consistency — N same-preset fixed-seed takes through the cohort gate.
python3 scripts/delivery_quality_gate.py --cohort take1.wav … takeN.wav

# 3. Clone fidelity — QC v2 identity (ReDimNet2+) and pitch (FCPE, SwiftF0) vs the fixture voice.
python3 scripts/clone_fidelity_lane.py --voice A_warm_elderly_woman
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
to eight takes. Since 2026-09-25 (the maintainer delegated the decision to the audit's
recommendation) a cohort-wise Bonferroni alpha of 0.05 marks the candidate `flagged`, with
`alphaStatus: report-only-uncalibrated` and `bindsVerdict: false`: 0.05 is the nominal family-wise
rate the null simulation reproduces, not a bound calibrated on delivery evidence, so the flag never
enters `passed`, `flags` or any outcome. Making it binding needs calibration evidence under the
audio-QC threshold-change authority: a labeled set of cohorts with known unstable takes, judged on
an untouched confirmation cohort.

The clone lane stays advisory; it reports AUC and equal error rate with seeded 95%
intervals whenever it has controls (`bandCalibrationReady` needs at least eight). Since
2026-09-25 (audit #103 part 1, decided by the audit's recommendation) its default plan generates
eight built-in-speaker controls matched to the reference voice's gender (read from the voice name,
else `--reference-gender`), and reports the separation per kind (`controlSeparation`,
`crossCloneSeparation`) and over every negative (`separation`). Cross-clone negatives, clone takes
of other saved voices, need those voices named: every clone take passes `--confirm-consent`, so each
`--cross-clone-voice NAME` (repeatable; one take per named voice unless `--cross-clones N`) is the
operator's attestation that they own or may clone that voice. The lane never discovers saved voices
and generates no cross-clone take by default (lane version 3). Since lane version 5 (2026-10-01) the
lane scores every take with QC v2 after the last generation exits (lane `clone-lane`): ReDimNet2+
similarity of the whole take and its least similar 4 s window to the reference, and the register
shift on frames where FCPE and SwiftF0 agree. Only clone takes gate; controls and cross-clone takes
never do. Flags stay report-only until an evaluated thresholds file gives a level; a warn is
reported, a fail or an uncomputed gate fails the lane. The report is
`<run>/clone-fidelity-report.json` (`qcGate`, `fidelity`), with `<run>/qc-takes.json` beside it.

### 4.7 iOS on-device bench

```sh
scripts/ios_device.sh bench custom:speed: \
  --label "ios-device-bench"
```

Optional physical-device memory-profile diagnostic (`QVOICE_IOS_MEMORY_PROFILE`,
[§2](#runtime-knobs)):

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
corpus ([§3](#fixed-corpus)) remains the macOS/CLI definition.

Requires a paired, unlocked physical iPhone and a valid XCUITest destination. Simulator is not
supported. The benchmark accepts `--modes`, `--lengths`, `--warm`, `--label`, `--seed-policy` and
`--matrix-version` (as on macOS, §4.10); without filters it runs the canonical 29-take matrix.

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
history record as part of the UI benchmark's `.xcresult` or evidence manifest. The iPhone
retained-memory lane is in [§4.11](#411-retained-memory-qualification).

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

The CPU and memory kinds sample with Time Profiler since 2026-09-26 (macOS `instrument-profile`
measurement version 4): CPU Profiler programs the hardware counters (kpc), which needs root on
macOS 27 even with Developer Tools access, while Time Profiler's timer sampling records
unprivileged. Its trace exports `time-profile` rows (sample time and sampled-time weight, published
as `cpuSampleCount`, `cpuSampleSpanMS` and `cpuSampleWeightMS`) and a raw `time-sample` table the
publisher does not read; the schema names are lowercase and case-sensitive. Before it builds, the
lane refuses a template or instrument that `xcrun xctrace list templates` or `list instruments`
does not list. Earlier Mac records and the iPhone lane keep CPU Profiler's `cpu-profile` cycles;
the validator refuses a Mac CPU Profiler capture from version 4 on and a Time Profiler one before
it, so the two never share a comparison key and are never compared.

A trace with CPU Profiler cycles also
publishes `cpuPlausibility` (`scripts/lib/trace_cpu.py`, audit #97): per take, the cycles inside its
generation window against its own rusage CPU seconds, in gigacycles per CPU-second, judged against a
provisional 0.8-5 GHz band, and the count of target CPU rows whose time or weight could not be
resolved. A Time Profiler trace has no cycles and publishes no such block. An implausible take
carries `trace.cpu-cycles-implausible`; it never fails publication and
never keeps the trace by itself. Every profile take also carries `trace.instrumented:<kind>`, naming
the capture its metrics were measured under.

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
Blank trace enables stop-the-world snapshots that create real holes in the target's memory sampler
(250 ms on the M6). Publication verifies the captured template setting and applies the same
unobserved-gap gate as every memory-qualified take ([§6.10](#610-memory-qualification-contract)).
The memory profile's default 180-second safety cap is only a maximum; exact-target exit ends the
recording early. The retained-memory lane ([§4.11](#411-retained-memory-qualification)) owns
repeated retained growth.

Produces `build/artifacts/macos/profiles/<run-id>/<run-id>.trace` containing Time Profiler samples and
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

**One-time machine setup:** configure Xcode UI-test runner signing, build the native test host, and
install the required models. See [`macos-testing.md`](macos-testing.md) for the complete lane
contract.

**Full matrix:**

```sh
scripts/ui_test.sh macos benchmark

# Targeted diagnostic example (not the full-matrix acceptance result):
scripts/ui_test.sh macos benchmark --modes custom --lengths short --warm 1 --label "focused"
```

The test target consumes the canonical matrix and wraps every UI-driven generation in a named
XCTest activity. The command accepts `--modes`, `--lengths`, `--warm`, `--label`, `--seed-policy` and
`--matrix-version`; without filters it runs exactly 29 takes. Cold Custom and Design cells are
exact-path relaunches ([§3](#cold-vs-warm)); a cell cannot complete without its matching
deterministic History/WAV assertion.

Telemetry rows stamp `notes.benchRunID`, `benchTakeIndex`, `benchCell`, and `benchWarmState` when
`QVOICE_MAC_BENCH_RUN_ID` is set. Completion requires matching generation, History, WAV, and typed
probe evidence; there are no hidden UI-test flush markers. The authoritative runner supplies the
matrix arguments, run ID, crash-delta assertion, and evidence-manifest path together. A direct
run-ID-only validator call is useful for post-mortem diagnosis, but it is not a publishable
benchmark contract (filtered runs require their exact matrix arguments):

```sh
# Diagnostic only: inspect the default matrix rows already present for one run ID.
python3 scripts/check_macos_ui_bench.py ~/Library/Application\ Support/QwenVoice-Debug/diagnostics \
  --run-id macos-xcui-benchmark-YYYYMMDD-HHMMSS
```

For the strict contract, use `scripts/ui_test.sh macos benchmark`. Internally it passes the exact
`--modes`, `--lengths`, `--warm`, `--label`, `--seed-policy`, `--allocation` and `--matrix-version`
values plus `--evidence-manifest <run-artifact-dir>/benchmark-evidence.json --crash-delta-passed
--build-provenance <run-artifact-dir>/last-build.json --outputs-dir <QwenVoice-Debug>/outputs`, and
`--playback-capture-dir <run-artifact-dir>/playback-capture` when capture is armed. The build receipt names the app executable
and its digest, and the gate copies its optimization level into `toolchain.optimization` only after
re-hashing that executable. Never add the crash-delta assertion to a manual command unless the
caller actually captured and compared the pre/post crash snapshots. The runner performs the strict
post-run gate and freezes its ordered evidence before summary and publication.

**Stall gate.** The lane also passes `--stall-contract config/macos-ui-stall-gate.json --variant
speed`. The stall contract names the gate's statistic (each take's
`maximumDelayedHeartbeatMS`, [§6.11](#611-frontend-responsiveness-and-playback-health)), its limit
and the profile it is calibrated for. The contract's status decides what the limit does (maintainer
decision 2026-09-25): a **provisional** limit reports only and never fails a run (the checker
records `stallGate.enforced: false` and `stallGate.wouldFail` in the evidence manifest, and a run
over the limit publishes with the run warning `stall.provisional.wouldfail(<takes above>/<gated
takes>)`); a **calibrated** contract, which must name its calibrating run IDs in
`calibrationRuns`, fails a run with a take above the limit. The committed contract is calibrated on
the canonical M6; its limit, calibrating run and derivation are in the contract's `maximumAllowed`,
`calibrationRuns` and `basis`. Apple's 250 ms hang threshold stays a report. The checker prints the
distribution to `benchmark-gate.txt` either way: the summary (median, p90, maximum, takes above the
limit, would fail, censored heartbeats) and every gated take's `cell=value`. Recalibrate when the
matrix, the watchdog definition or the host changes. A contract naming another profile than the
registry's canonical one fails the gate.

**Variant and retries.** Every take must have run the declared variant (Speed), whatever the tier
recommends (the 16 GB tier recommends Quality). Before the first take the benchmark makes Speed the
active variant of each measured mode through the visible toolbar switch
(`<mode>_speedVariantButton`) and restores the original visible choice when the session ends; it
never toggles "Prefer lower-memory models", which clears every stored choice. The checker still
refuses any take that ran another variant. The engine runs in the app, which has exited before
validation, so the lane validates once and retries only the checker's distinct "rows not yet
present" exit (75), for about ten seconds. Timing lanes also let the load of their own build settle
(up to 90 s, down to the core count) and re-apply the quiet-host rule after build-for-testing,
before the first take.

**Take harness.** One repetition of each cell is captured (audit #31): the last warm repetition of
each mode and length, never a take that starts an app session (the first take, a cold take, the
first Clone take). Those takes play out before the next begins, with a half-second tail; every
other take pauses its playback through the visible player control at completion and settles the
same half second. Which takes play out is fixed by the matrix, never by the recording grant, so the
idle gap before a take never depends on whether the tap is live (audit #74). A relaunched app has
no Core Audio process object until its first playback, so a tap armed on a session's first take
would attach mid-take; the plan never captures one, and every captured take's tap is live before
its submit (audit #74 part 4). Making the app open its output device at launch instead would move
the device-open cost out of the first take's measured playback-scheduling latency and change the
shipped audio lifecycle, so the app is left as it is. The runner pastes each take's script with one
genuine paste (Cmd-A, Cmd-V, restoring the pasteboard's text) instead of typing it a key at a time,
and an unsandboxed runner (the lane re-signed it) writes the current-take file itself instead of
relaying it through the log and polling; a sandboxed one keeps the relay. The app row keeps the
take identity it was submitted under, and the checker refuses a run whose app and engine rows name
different takes. The runner prints each take's harness phases (monotonic offsets from the take's
start: manifest published, session ready, script entered, submit, completion seen, playback ended,
settled, end, and whether the take was captured) and the lane keeps them as `take-phases.jsonl`
beside the run, so per-take harness overhead is measured rather than inferred (audit #31); they
time the harness around the measured windows, never inside them.

**Seeds and aggregates.** The evidence manifest names each take's effective seed and its source
from the engine's receipt, so a run-on can be reproduced. The lane runs under the seed policy
`cell-hash-v1` by default ([§2](#runtime-knobs); audit #29, `--seed-policy generated` opts out):
the runner hands the registered `QWENVOICE_BENCH_SEED_POLICY` knob to the app, every take samples
with the seed of its cell, the checker refuses a take that sampled with any other seed (an app
built without internal diagnostics ignores the knob and fails here), and the record names
`run.seedPolicy` and each take's `seed`; lineage contract 2 keys a seeded matrix apart from random
seeds. The iPhone lane does the same through a per-process cell schedule. The manifest flags the
first warm take after a cold take (`followsColdTake`, audit #30): in the 16 canonical M2 records it
is the slowest take of its cell in 14 (custom/short) and 11 (design/short) runs. The tracked record
keeps that take, flagged (`followsColdTake: true`), but its cells use aggregate 2
(`evidence.cellAggregateVersion`): the flagged take stays out of its cell's statistics, and an IQR
is published only from at least four takes (null below). The README medians leave flagged takes out
too. Records without the declaration keep aggregate 1 and their stored cells; lineage contract 2
keys the aggregate version.

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

**Played-audio capture (PC-01).** The runner taps the app's own output for the one captured take
per cell (the plan above) through a Core Audio process tap (`mutedWhenTapped`), so the speakers
stay silent while a take is captured; the tap's destruction restores audible output. The runner
(`com.qwenvoice.app.uitests.xctrunner`, re-signed unsandboxed by the lane) needs one **System Audio
Recording** grant: on macOS 26 a process tap never prompts, so it is added by hand in System
Settings after the first lane run; on macOS 27 the first captured take prompts and blocks the
runner until it is answered, so `QVOICE_MAC_BENCH_PLAYBACK_CAPTURE=auto` (the default) arms capture
only when the TCC database shows a grant (see [`macos-app-guide.md` §7](macos-app-guide.md#7-macos-permissions-tcc)).
Artifacts land under `<run-artifact-dir>/playback-capture/` (`capture-run.json`,
`take-NN-<cell>.wav` and `.json`, `summary.json`); the WAVs stay untracked and only their digests
enter the record. `scripts/lib/playback_capture.py` compares each capture with the published take
WAV, and the take then carries:

- `playbackCaptureStatus` (`captured`, `silent`, `unavailable`, `referenceUnresolved`, `aborted`)
  and `playbackCaptureDigest`; takes outside the plan carry no capture fields;
- when captured, `playbackCaptureFirstAudibleMS` (submit → first frame above −50 dBFS; the submit
  reference is the app row's own wall-clock stamp `timingsMS.submittedAtEpochMS` when present, else
  the runner's click stamp, which precedes the app's submit by the UI driver's dispatch latency; the
  capture's first sample is the first buffer the tap delivered, which arrives only once the app's
  output device runs; the capture `summary.json` records `clickToSubmitMS` per take);
- `playbackCaptureAlignmentMS` (where the published WAV starts inside the capture, a lead-in, not a
  fault), `playbackCaptureResidualDBFS` (after gain match), `playbackCaptureDropoutCount` /
  `playbackCaptureMaxGapMS` (20 ms frames where the file speaks above −40 dBFS and the capture
  collapses by more than 25 dB), `playbackCaptureCoverage` and `playbackCaptureStepBurstPeakCount`.

Anomalies are warn-only codes on the take (`playback.capture.misaligned` when the audible first
frame and the app's own `playbackScheduledMS` disagree by more than 250 ms either way — the app's
timeline stops at scheduling, the tap hears the result; the first captured takes put the audible
onset about 1.8 s after scheduling on final-file playback — `.dropouts`, `.low_coverage` below
0.95, `.high_residual` above −20 dBFS, `.silent`). Since 2026-09-14 (PC-02) a **captured** take also
fails the lane when it breaks the gate set from the first three canonical captured runs (87 takes):
coverage below 0.98, residual above −25 dBFS, any dropout, or an audible onset more than 500 ms
from `playbackScheduledMS`. Without a grant the lane passes: an unarmed run carries no capture
evidence, and unavailable, silent and unresolved captures stay warnings so an ungranted host still
passes. The macOS smoke lane captures its completed-generation take too;
`scripts/analyze_playback_capture.py` writes its `summary.json` (advisory there).

The benchmark `.xcresult`, smoke result, and seeded telemetry-overhead result
([§4.12](#412-telemetry-overhead-parity-lane)) are independent.

| Phase | Tool |
|-------|------|
| Trace capture | `xctrace record --attach <exact-app-pid>` during a benchmark scenario |
| Trace analysis | Instruments/xctrace plus the relevant installed macOS performance skill |
| Logs / warm-admission | `scripts/macos_test.sh logs` and unified-log inspection |
| Crash post-mortem | `scripts/macos_test.sh crashes`, dSYMs, and standard symbolication |

### 4.11 Retained-memory qualification

```sh
scripts/macos_test.sh memory --label retained-check
scripts/ios_device.sh memory --voice-id <exact-prepared-saved-voice-id> --label retained-check
```

Both run policy `retained-memory-v1`: fixed Custom→Design→Clone Speed/medium sequences with three
retained takes per mode in one process. On macOS, Custom and Design run one cold plus three
`retained#0...2` takes and Clone three `retained#0...2` takes, all in one CLI process; each retained
take keeps its actual engine warm-state attribution. The iPhone lane runs the nine retained takes
without relaunching the app, and its terminal sentinel is atomic. Within each mode, the highest
end-of-take physical footprint among the later retained takes may exceed the first retained take's
by at most 5% of the canonical profile's RAM. Intentional cross-mode model residency is diagnostic unless
a future runner proves an explicit full unload. These PASS-only runs publish the
`memory-qualification` kind and carry no trace; `profile --kind memory`
([§4.8](#48-macos-instruments-profile-signpost-validation)) remains the distinct Allocations + VM
Tracker Instruments lane.

Since 2026-09-25 the same run also reports policy `retained-memory-v2`
(`config/memory-qualification-policy.json` `retainedMemoryV2`; `evidence.retainedMemoryV2` on the
record). v1's 5% bound lets a leak of up to about 410 MB per take pass on the canonical 16 GB M6
(819 MB over two takes; 307 MB per take on the 12 GB iPhone), and on a tier without the
post-generation cache clear its end value includes the MLX cache. Each take now publishes
`mlxEndActiveMB`/`mlxEndCacheMB` from the MLX snapshot after that clear (else after the stream) and,
when sampled, `graphicsFootprintEndMB`; v2's metric is each mode's growth of `mlxEndActiveMB` from
the first retained take to the highest later one. It gates per mode only against a bound calibrated
from a consented memory run on the platform's canonical host (`derive_memory_calibration.py`,
[§6.10](#610-memory-qualification-contract)); `retainedMemoryV2.calibration` in the policy records
each platform's status, bounds and run ID. An uncalibrated platform's record reports the growth with
no bound and no verdict, and v1 alone decides publication.

### 4.12 Telemetry-overhead parity lane

For telemetry/backend changes, run the model-dependent overhead parity lane directly when its
fixture is available; it does not consume or require UI evidence:

```sh
scripts/macos_test.sh telemetry-overhead
```

This is a real generation lane with its own read-only model integrity check. It never invokes
`models ensure`, downloads weights, bootstraps a clone fixture, or depends on an XCUITest result;
missing fixtures stop the run. It applies one fixed `vocello bench --seed` and counterbalances
`off`, `lightweight`, and `verbose` through three deterministic mode-order rotations. Each rotation
runs one warm-up and two measured Custom/Speed/medium takes per mode, yielding six machine-readable
measured takes per mode. PCM SHA-256 must match across the three modes, and the lane fails if an
off arm leaves any file under `diagnostics/engine`; every arm's timings come from the CLI observer
(`bench-results.json`), and raw evidence and load/thermal context stay under
`build/artifacts/macos/`.

RTF and TTFC regression limits versus off are 5% for lightweight and 10% for verbose. Since
2026-09-25 (audit #63 part 3, decided by the audit's recommendation) each arm's paired 95% interval
of the percent difference decides when it exists (each take paired with the off take of its
rotation): wholly above the limit fails, straddling it is inconclusive, and wholly at or below it
passes only when the median regression is within the limit too (an interval under the limit beside
a median over it is inconclusive, never a pass); without an interval the median comparison decides.
A measured take above twice the core count, at a serious or critical thermal state or in low power
mode also makes the run inconclusive. An inconclusive verdict is recorded (`status: inconclusive`,
`inconclusiveReasons`) and exits 3, never a pass or a fail.

The verdict is deliberately local-only and never published to tracked history: the `off` lane
cannot supply mandatory v8 memory evidence, and adding the in-process memory sampler to it would
change the observer whose overhead is being measured. This fail-closed exception preserves the
experiment without admitting memory-incomplete records. Existing schema-v1 overhead records remain
readable and memory-contract-incomplete.

---

## 5. Language bench

Headless matrix for the Qwen3 language path:

1. **Phase 2 — hint contract:** UI hint → resolved `notes.languageHint` (the resolved Qwen3
   token, not the raw UI picker) in engine telemetry.
2. **Phase 3 — output verification:** recognized speech scored for language and WER/CER against
   the script, with exact fixed-seed WAV proof. The iPhone lane uses three-pass locale-locked
   on-device Speech consensus plus QC v2's two ASR families; the macOS lane uses the two QC v2
   families alone.

### 5.1 Matrix and corpus

| File | Role |
| --- | --- |
| `config/language-bench-corpus.json` | Versioned scripts plus Custom speaker and Design delivery fixtures per language |
| `config/language-bench-matrix.json` | Cells: mode, `uiHint`, `scriptLang`, `expectedHint` |
| `config/language-bench-diagnostic-cohort.json` | Fixed cells and five predeclared seeds for autonomous failure diagnosis |
| `config/audio-qc-script-pool.json` | The AQ-02 CC0 ten-language script pool for the QC take generator ([§5.2](#52-qualification-script-pool-aq-02)); not a bench cell input |
| `config/audio-qc-script-pool-sources.json` | The pinned Common Voice commit and the size and SHA-256 of every file the pool is selected from |

Cells tagged `"quick": true` form the **quick** subset (English + French + negative control, 7 cells).
**full** runs all 23 cells: six languages × Custom pinned/Auto + Design explicit-language, the
negative control, and a Custom pinned cell each for Russian, Portuguese, Italian and Korean. Those
four joined in corpus version 3 (2026-10-22) so the full matrix covers every language the
promotion contract's language lanes require; they have no Auto or Design cell.

The corpus is deliberately longer than the original smoke snippets: each alphabetic script
contains at least 15 normalized words and each Chinese, Japanese and Korean script contains at
least 24 normalized characters. The plan refuses a script that fails the corpus
lint ([§5.3](#53-accuracy-contract)). Design always receives the known target language explicitly.
Custom uses a native-language speaker where the Qwen speaker contract provides one (Chinese
`vivian`, Japanese `ono_anna`, Korean `sohee`); the remaining languages use the contract's stable
`aiden` fixture.

The paired Custom pinned/Auto cells intentionally generate the same prompt with the same speaker
and sampling policy; the shared resolved prompt digest proves that Auto resolves equivalently to the
pinned hint. Since seed identity v2 (2026-09-25) the Auto cell draws its own seed, so its audio is an
independent sample rather than a byte copy of the pinned take. Likewise, the three sequential Speech
recognitions prove that the on-device recognizer reproduced one transcript for one WAV. They do not
provide three statistically independent accuracy observations. The 22 positive output cells (plus
the expected-fail negative control) remain strict per-cell multilingual smoke acceptance, not a
population estimate of language quality.

Before the first take, each lane atomically writes the immutable `language-run-plan.json`
(`scripts/language_bench_evidence.py plan`) with one-based take indexes, child run IDs, cells,
prompt-equivalence groups, seeds, and sampling variation. Normal
quick/full matrices use seed identity v2 (`seedPolicy: sha256-v2-mode-script-language-auto-63bit`;
audit #86 part 2, the maintainer delegated the decision to the audit's recommendation on
2026-09-25): a pinned cell keeps its v1 seed per mode/script language, and an Auto cell draws its own
seed, so Auto is an independent sample. The pinned and Auto Custom cells of one script still share
the resolved prompt assembly, and every gate (`check_language_hints.py`, `check_language_output.py`,
the publisher) requires the members of a prompt-equivalence group to share that digest whatever
their seeds: the prompt, not the audio, proves Auto resolution. Every take publishes
`output.fileDigest` (macOS from the engine's WAV digest since 2026-09-25, iOS from the sentinel), and
group members that share a seed (a diagnostic cohort's pinned and Auto takes at one explicit seed)
must publish one digest (audit #86 part 1; the committed iOS records' eight groups replay
identical). The iOS rerun that shows the Auto takes' own verdicts is the part-3 device run. The plan
also freezes the corpus-owned Custom speaker and one shared Design delivery instruction; the shared
Design fixture keeps language as the controlled variable and preserves one typed fixture identity
for the model across the matrix.

### 5.2 Qualification script pool (AQ-02)

Detector calibration needs many scripts per language, not one, so a separate script pool sits
beside the bench corpus; the corpus above stays the bench cohort.
`config/audio-qc-script-pool.json` holds 120 scripts in each of the ten product languages, split
60 `calibration` and 60 `confirmation` (disjoint by script). It is the script source for natural
Vocello calibration takes, which `scripts/audio_qc_calibration_takes.py` generates for QC v2
([qc.md](qc.md)).

- **Source and license.** Common Voice Sentence Collector files
  (`server/data/<locale>/sentence-collector.txt`, human-reviewed submissions) at one pinned commit of
  `common-voice/common-voice`, whose `server/data/LICENSE` is CC0 1.0 Universal. The sources file
  pins the commit, the license and every file's size and SHA-256. Only these texts are committed.
- **Selection** (rules `audio-qc-script-pool-rules-v2`, recorded in the pool's `selection` block):
  every text passes the corpus lint ([§5.3](#53-accuracy-contract)); it is well formed, has no URL
  or email, is not all capitals, and reads as one sentence (a capital or inverted mark first, `.`,
  `!`, `?` or `。` last, no ellipsis); it names no one where letter case marks names (below); every
  letter is in the language's script (Simplified Chinese only under the committed Hant-Hans fold
  table, Japanese with kana, Korean in Hangul, no Latin in CJK and no CJK in alphabetic text); its
  length in the scoring unit (`normalized_tokens` words, or characters for Chinese and Japanese and
  syllables for Korean) lies in a window sized for takes of about 3-8 s; it is unique after
  normalization within and across languages and overlaps no legacy corpus script. Candidates are
  ordered by a seeded SHA-256 of the normalized text, the first 120 are kept (ids `en-0001`
  onward), and a second seeded hash assigns the splits. Each language records its candidate count
  after every filter, and `poolDigest` covers the entries.
- **No proper names (v2).** Recognizers spell names their own way, so a name turns a correct take
  into a content error (the first cohort's French "ajouta Robin Poussepain"). In English, French,
  Spanish, Italian, Portuguese and Russian a text is refused when a word that opens no sentence is
  capitalized (English "I" excepted), when a word holds a capital after its first letter
  ("Jean-Pierre"), or when its opening word is one the language's source file capitalizes inside
  sentences and never writes in lower case. Case cannot mark names in German (every noun is
  capitalized) or in Chinese, Japanese and Korean, so their names are not detected; the pool records
  this limitation. `validate` checks the per-text part; the lexicon part needs the source file and is
  checked by `validate --rebuild`.
- **Versions and cohorts.** Ids are ranks within a version, so a cohort binds to its pool version by
  `poolDigest` and to texts by `textSHA256`. Of the first calibration cohort's 800 takes (pool v1,
  `mac-qc-takes-20260927-182513-872126ac`), 683 read texts that pool v2 keeps, 672 of them in the
  calibration split. Splits are ranks among the selected texts, so 11 texts moved split: calibration
  data taken from the v1 cohort uses only texts in v2's calibration split, which keeps calibration
  and confirmation disjoint by script.
- **Commands.** `python3 scripts/audio_qc_script_pool.py fetch` downloads the pinned files into
  `build/cache/audio-qc-corpora/` (verified, re-fetchable); `build` rewrites the pool from them;
  `validate` checks the committed pool without network and runs in the contract gate, and
  `validate --rebuild` also requires a byte-identical rebuild from the fetched files. A rule
  change bumps the rules version and rebuilds the pool.
- **No audio.** Common Voice audio comes from the Mozilla Data Collective under its own terms and is
  never committed.
- **Deferred.** A per-language hard-case pool (the seed-tts test-hard design) and a digits and
  abbreviations diagnostic pool.

### 5.3 Accuracy contract

The versioned accuracy contract uses **WER ≤ 0.15** for languages with word boundaries and
**CER ≤ 0.15** for Chinese and Japanese (and Korean since accuracy metric v3); both scores and both
word/character edit-count decompositions remain evidence. The Python gate and history publisher
independently recompute the metrics from the tracked corpus and the untracked consensus transcript
before accepting the Swift verdict. Recognizer or metric changes go into
`scripts/lib/language_metrics.py`.

**WER v2 (`segmentation-aware-edit-rate-v2`, 2026-09-25).** Audit #43; the maintainer delegated the
decision to the audit's recommendation. The word gate no longer charges a recognizer's
word-boundary choice as errors: the alignment may pair a block of one to four reference words with
a block of one to four hypothesis words at no cost when both spell the same characters and one side
holds two or more words (a merge such as "vor Mittag" heard as "Vormittag", a split, or a moved
boundary). Every other edit keeps its v1 cost, and a merge of five or more words is charged as
before. Takes publish `segmentationAwareWordErrorRate` and `wordBoundaryOnlyEdits` (the plain edits
the v2 alignment credited) per family (`independent…` for the retired whisper-small witness;
`qcQwen3Asr…`/`qcWhisper…` since language measurement version 6) beside the unchanged v1
`wordErrorRate`, and `primaryAccuracyScore` is the v2 rate for word languages; the character rate is
the same under both versions. Swift (`VoiceClipTranscriber.segmentationAwareWordMetrics`) and
`scripts/lib/language_metrics.py` share the operation set and parity fixtures; the minimum is unique,
so they agree exactly. Records published before carry `normalized-edit-rate-v1` and keep validating
under it; the v2 distance never exceeds the v1 distance, so no passing take changes verdict. The
app's `languageASR` quality gate
reports the rate its outcome reads since gate composition 5 (the v2 word rate as `word_error_rate`,
or the character rate as `character_error_rate`; through version 4 it reported the v1 word rate).

**Normalization v2 (`normalization-v2-edit-rate-v3`, 2026-09-25).** AQ-02 phase P2a, from the
audio QC audit the maintainer accepted: the same WER v2 and character rates, scored under text
normalization v2 (`normalized_tokens` in `scripts/lib/language_metrics.py`, mirrored step for step
by `VoiceClipTranscriber.normalizedWordTokens`). It applies NFKC (NFC for Korean) and case folding,
strips recognizer tags (`<|…|>`), keeps v1's diacritic fold for the Latin and Cyrillic languages and
adds ß, æ, œ, ø and ł, and in English, French and Italian joins a word across an inner apostrophe
(l'homme, dell'autunno, don't) without scoring the apostrophe, so a recognizer that splits the
elision makes a boundary edit WER v2 credits. Bracket contents and fillers stay words (Whisper's
normalizers delete both); fillers beyond the script's are also counted per family
(`excessFillerCount`; `qcQwen3AsrExcessFillerCount`/`qcWhisperExcessFillerCount` since version 6)
and never gate. Korean gates its space-free syllable rate, never NFKD jamo (audit AQ-F21). The
character rate is space- and punctuation-free in every version. The language tables cover the
product's ten languages, so Italian, Portuguese, Russian and Korean cells no longer fail closed; the
corpus still scripts six. Korean jamo CER and a diacritic-preserving WER (French, German, Spanish,
Italian, Portuguese) are Python diagnostics that never gate. The steps beyond P2a (a Chinese
script-variant fold, cn2an for Chinese, num2words digit diagnostics, a fugashi kana-reading CER for
Japanese, Whisper's English spelling map) are phase P2b: named slots in
`NORMALIZATION_EXTENSION_SLOTS`, fixtures marked `P2b`, and a new normalization and metric version
when each lands. The corpus lint refuses digits, brackets, symbols and spoken punctuation, and
abbreviations in a gated script (`script_lint_issues`): the plan builder applies it and the Python
suite lints the tracked corpus. The in-app `languageASR` gate was composition 6 and the language
kinds' measurement version 4 under v3. v1 and v2 records keep validating and rescoring under their
own normalization; filler counts are refused on them.

**Chinese fold (`normalization-v3-edit-rate-v4`, 2026-09-26).** AQ-02 phase P2b, first step; audit
AQ-F22: the same rates under text normalization v3, which is v2 plus a Traditional-to-Simplified
fold of Chinese on both sides, after case folding. whisper-small wrote a correct Mandarin take of
the corpus script in Traditional characters on the first real-audio orchestrator run (CER 12/27, a
false fail); folded, only its one real homophone remains (1/27). The fold is the committed
single-character table `config/language-normalization/hant-hans-v1.txt` (3,079 entries, with its
SHA-256, provenance and license in `hant-hans-v1.json`), derived once from ICU's `Hant-Hans`
transform on macOS 27.0 (26A428) by `scripts/generate_hant_hans_table.swift` and closed so no
target is itself a source. Neither runtime calls ICU, whose data moves with the OS:
`language_metrics.fold_traditional_chinese` reads the table and refuses one that fails its
integrity check (`fold_table_issues`), and the in-app verifier embeds its exact bytes in the
generated `HantHansFoldTable.swift` (`scripts/generate_hant_hans_fold_swift.py`; `scripts/dev.sh
regen` refreshes it and the contract gate checks it). The table replaces the audit's OpenCC `t2s`:
no package pin, and the same bytes in both runtimes. It is Unicode-3.0 data and is attributed in
the app's open-source licenses. Only Chinese folds: Japanese writes its own kanji (葉 "leaf" and 叶
"to grant" are different words the table would merge) and Korean hanja stay as written. Folding
both sides only merges characters, so an edit count can only stay or drop. Swift and Python score
every case of `scripts/tests/fixtures/language_normalization.json` identically
(`WordErrorRateTests` and `test_language_metrics.py`), including a generated sweep of every table
entry; the Chinese cases the fold changes also pin their normalization v2 count, which records
declaring `normalization-v2-edit-rate-v3` keep rescoring under. The in-app `languageASR` gate is
composition 7 and the language kinds' measurement version became 5 (6 since the QC v2 families,
2026-10-01).

**Deletion runs (warn-only).** Each family's alignment also yields `longestDeletionRun`, the longest
run of consecutive reference units the recognizer deleted on the primary metric's units (a match,
substitution or insertion ends a run; the Swift verifier and `scripts/lib/language_metrics.py`
share the tie-broken path and parity fixtures). A skipped phrase of two to four words stays under
the 15 % gate on the corpus's 17-32-unit scripts, so a run of two or more on a take that must pass
publishes the take with `language.deletion_run:<family>` and never changes a verdict or the
accuracy contract. Published as `longestDeletionRun` (Apple Speech, recomputed and checked against
the app's value) and `qcQwen3AsrLongestDeletionRun`/`qcWhisperLongestDeletionRun`
(`independentLongestDeletionRun` on whisper-small records through version 5).

**Outer-edge timing.** The host checker also enforces the app's existing outer-edge timing rule
whenever the verification declares `sourceAudioDurationSeconds` or the record includes WAV
`outputEvidence`: all three recognitions must start within `min(2.5, max(1.0, duration × 0.15))`
seconds of the beginning and end within that allowance of the end, without exceeding the duration
by more than 0.25 seconds. Supplied durations must be positive, finite and mutually consistent.
Missing timings, invalid durations or incomplete edges cannot authorize a claimed PASS. The VLR
composer classifies this as a harness/evidence gap, preserving already typed incomplete-coverage
results. Legacy reports lacking both duration fields retain historical validation; they are not
fresh full-WAV proof. Edge coverage does **not** establish interior completeness or waive WER/CER.
Independent recognizers disagreeing on the same WAV remain diagnostic evidence; never choose the
better score, substitute their transcripts, or relabel a retained failure automatically.

### 5.4 Language checks, consensus and the negative control

Each family's language check observes something different, and records say so (audit #42):
`evidence.languageVerification.languageCheckKinds` declares `transcript-language-consistency` for
Apple Speech (text language detection over a transcript produced with the recognizer locked to the
expected locale, close to unfalsifiable for an anglicized take) and `audio-language-identification`
for Qwen3-ASR and Whisper large-v3 (both decode with no language lock; Whisper detects from the
first 30 s). Each language take publishes each family's detected language in `detectedLanguages`.

Consensus is per channel (audit #42; the maintainer delegated the decision to the audit's
recommendation on 2026-09-25). A verdict has a `language` channel and an `accuracy` channel, and
`scripts/lib/language_metrics.py` `channel_consensus` votes each one separately through the family
rule, so two families that fail a take for different reasons no longer read as agreement and a
channel the families split on is `inconclusive`. A take that must pass needs both channels to pass
by consensus. A two-family record publishes each scored take's `channelConsensus` (`pass`, `fail`
or `inconclusive` per channel) and the run's `languageVerification.channelVerdicts` (a channel is
`pass` when every take that constrains it reached its expected status) with
`channelConsensusAlgorithm: per-channel-family-consensus-v1`; QC v2 records vote the two QC families
under `qc-v2-family-consensus-v1`. The history validator recomputes both from the per-family
verdicts the takes publish. The cohort verdict (`qc.py language-bench evidence`) applies the same
rule and prints each take's status and per-family detected language and error rate. A second
acoustic language detector would be research, not part of this rule.

**Negative control.** `custom-fr-text-en-pinned` carries `expectedOutcome: "fail"`: the pinned
English hint is sent over a French script, synthesis still speaks French today, and the cell passes
only when the output verification ran and failed as the control declares. A verification that
passes means the model started honoring the pinned hint; a skipped verification is not a confirmed
control. Before 2026-09-12 this cell was hint-only and never measured its output. In a published
record the control's take carries `expectedOutcome: "fail"` (a schema-v3 take key) and
`scripts/benchmark_history.py` inverts its accuracy gate: the take is evidence only if its
verification failed, and the stamped takes must match `negativeControlsConfirmed`. What the control
must fail depends on the families:

- **Accuracy control** (`negativeControlKind: accuracy-control`; records through language
  measurement version 5, whose independent witness was an English-locked whisper-small): since
  2026-09-25 it must fail the accuracy channel by consensus, and its language channel is reported
  only (before, a failed language check alone also confirmed it). whisper-small passed the language
  check, so the control failed on accuracy alone.
- **Language control** (`negativeControlKind: language-control`; QC v2 records): Qwen3-ASR and
  Whisper large-v3 decode with no language lock and both hear the French, so the take must be heard
  as a language other than the pinned English by both families.

### 5.5 iOS on-device lane

Requires Built-in Voice and Voice Design **Speed** installed on the paired iPhone, and Speech
Recognition permission: grant **Settings → Privacy → Speech Recognition → Vocello** once before the
first output-gated run.

Phase 3 transcribes each exact fixed-seed output WAV three times in the app process with one
**on-device Speech** recognizer locked to the deterministic locale of each cell
(`QVOICE_IOS_DEVICE_DIAGNOSTICS_VERIFY_OUTPUT=1`) and stamps the consensus evidence on
`device-diagnostics-done.json`. All three final transcripts must agree before WER/CER is scored.
Authorization denied, recognizer unavailable, missing on-device support, timeout, engine error,
inconsistent transcripts, or failed WER/CER are distinct machine failures; none is replaced with a
fabricated score or a listening judgment. After the run the Mac scores the collected `output.wav`
files with QC v2's two ASR families (Qwen3-ASR and Whisper large-v3, lane `ios-language-bench`,
[qc.md](qc.md)), which must both meet each take's outcome per channel beside Apple Speech's in-app
gate; the record lists `languageVerification.families: ["apple-speech", "qwen3-asr", "whisper"]`,
and only the two QC families vote.

**Speech asset prerequisites.** EN/FR work out of the box; **DE, ES, ZH, JA** need system dictation
languages and downloaded voice assets on the phone. One-time setup (on the iPhone — Settings app,
not Vocello):

1. **Keyboards:** Settings → General → Keyboard → Keyboards → Add keyboard — e.g.
   Allemand, Espagnol, Japonais (Romaji), Chinois simplifié (Pinyin QWERTY).
2. **Dictation languages:** Settings → search *dictée* → **Langues de Dictée** — enable
   Allemand, Espagnol, Japonais, Mandarin (and any variants listed for your locale).
3. **Explicit asset bootstrap:** With the unlocked phone on Wi‑Fi, run
   `scripts/ios_device.sh speech-assets`. Vocello resolves the device-supported equivalents for
   `de_DE`, `es_419`, `ja_JP`, and `zh_CN`, creates DictationTranscriber modules, checks
   AssetInventory before and after one combined `downloadAndInstall()` request, and requires every
   resolved locale to report installed. The command also prints a separate
   `vocello_legacy_gate` verdict from fresh SFSpeechRecognizer instances and the same deterministic
   locale-selection policy used by the output verifier.
4. **Interpret both results:** `asset_inventory=PASS` proves the modern assets installed.
   `vocello_legacy_gate=PASS` is additionally required by the current Phase 3 verifier. If the
   modern gate passes but the legacy gate remains blocked, do not claim language readiness or run
   the full matrix as promotion evidence; preserve the local diagnostic result and investigate the
   OS-level legacy recognizer state.
5. **Re-run** once both are ready:
   `scripts/ios_device.sh lang-bench --subset full --label "lang-full-output-v3"`.

Settings remains useful for confirming enabled Dictation languages, but the explicit command owns
asset installation and machine verification. This is an operational prerequisite, not a subjective
audio review. Vocello UI expectations remain documented in
[the iOS app guide's UI state map](ios-app-guide.md#7-compact-ui-state-map). Language-benchmark
labels follow the label rule in [§4](#4-standard-workflows).

```sh
scripts/ios_device.sh lang-bench --subset quick --label "lang-smoke"
scripts/ios_device.sh lang-bench --subset full --label "lang-full"
scripts/ios_device.sh lang-bench --diagnostic-cohort
```

Skip output verification (hint gate only):

```sh
QVOICE_LANG_BENCH_SKIP_OUTPUT=1 scripts/ios_device.sh lang-bench --subset quick
```

Per cell the driver sets:

- `QVOICE_IOS_DEVICE_RUN_ID` — shared run id (`ios-lang-bench-…`)
- `QVOICE_MAC_BENCH_CELL` — matrix cell id
- `QVOICE_IOS_DEVICE_DIAGNOSTICS_LANGUAGE` — language hint (`english`, `french`, …; omitted for Auto)
- `QVOICE_IOS_DEVICE_DIAGNOSTICS_SPEC` — `mode:speed:<script>`
- `QVOICE_IOS_DEVICE_DIAGNOSTICS_VERIFY_OUTPUT=1` — Speech round-trip (default unless skipped)
- `QVOICE_IOS_DEVICE_DIAGNOSTICS_SEED` — immutable UInt64 from the pre-generation plan
- `QVOICE_IOS_DEVICE_DIAGNOSTICS_VARIATION=expressive` — explicit sampling policy

The diagnostic cohort is seed-major and evaluates exactly three cells across five fixed
seeds (15 takes). It performs no retry and never publishes benchmark history. QC v2's two families
score the cohort too (takes are keyed by child run ID, so a cell repeated across seeds is five
takes), and `qc.py language-bench evidence` prints each take's two-family verdict: the cohort passes
only when both families meet every take's expected outcome per channel, beside the in-app Apple
Speech gate. A take the families split on is `inconclusive`, and one with a missing or disqualified
recognition (truncated, empty, wrong digest) is `unqualified`; either fails the lane, so a broken
decode never confirms a negative control. Passing the diagnostic cohort prints its verdict locally
and intentionally creates no record.

Gates:

- `scripts/check_language_hints.py` — exact plan-selected `engine/generations.jsonl` against
  `config/language-bench-matrix.json`, including run/cell/generation/seed/variation and resolved
  prompt-assembly correlation
- `scripts/check_language_output.py` — exact plan-selected `device-diagnostics-done.json` →
  `outputVerification`, exact WAV SHA/metadata, structured three-pass recognition evidence, and the
  independent edit-metric recomputation ([§5.3](#53-accuracy-contract))

The device sentinel is schema v2 and is written last as a completion barrier. The collector copies
only the plan-selected engine/app rows, their verbose sidecars, the exact `output.wav`, and bounded
manifests into the untracked run artifact. It verifies the WAV digest, byte/frame/channel/sample-rate
metadata, generation identity, and unique ordering; it never summarizes the phone's historical
diagnostics tree. Raw transcripts and audio remain untracked.

After both requested gates pass, the runner automatically publishes one privacy-safe `language`
record under `benchmarks/runs/language/` and regenerates `benchmarks/HISTORY.md`. A run made with
`QVOICE_LANG_BENCH_SKIP_OUTPUT=1` is recorded as `partial` and excluded from normal timing trends.
Failed cells, missing typed telemetry/model identity, or a publication error leave the tracked
registry unchanged; the untracked artifact directory retains the idempotent repair command.

### 5.6 macOS in-process CLI lane

Requires test models (`scripts/macos_test.sh models ensure`).

```sh
scripts/macos_test.sh lang-bench --subset quick
```

The lane writes the same immutable `language-run-plan.json` the iPhone lane follows
([§5.1](#51-matrix-and-corpus)) and generates its takes in order (audit #88, the
maintainer delegated the decision to the audit's recommendation on 2026-09-25): each Custom take
speaks with its script language's corpus speaker (`vocello generate --speaker`, for example `vivian`
for Chinese and `ono_anna` for Japanese) and each Design take with the corpus's one Voice Design
brief (`--voice-brief`), at the plan's seed-identity-v2 seed (`--seed`, `--variation expressive`,
`--language` for a pinned hint). Until then the lane spoke every language with the default speaker
and a lane-owned brief, so macOS and iPhone takes were not comparable. The engine row names its
Custom speaker (`notes.customSpeakerID`) and its Design brief's digest (the typed fixture digest),
and the publisher (`--plan`) refuses a macOS verification whose rows do not match the plan's seed,
variation and fixture, or that has no plan. Each Custom and Design row also carries
`notes.resolvedPromptAssemblyDigest`, the request-resolved prompt digest the iPhone sentinel records
(one definition, `GenerationSemantics.promptAssemblyDigest`): the Auto take draws its own seed, so
the publisher proves Auto resolution on the Mac by requiring every member of a prompt-equivalence
group to carry that digest and share it; the plan's fixtures and seed policy enter the analysis
profile. The hint gate reads `QwenVoice-Debug/diagnostics/` with `QWENVOICE_DEBUG=1`.

Apple Speech is **not** available to the CLI (TCC). After every CLI process has exited, QC v2
verifies spoken content ([qc.md](qc.md)): `qc.py language-bench takes` binds each planned WAV to the
digest the engine published, `qc.py run --lane language-bench` scores it with Qwen3-ASR 1.7B and
Whisper large-v3 (MLX, one model process at a time, cached by audio digest), and
`qc.py language-bench evidence` writes their recognitions with each take's two-family verdict. Both
decode the whole take with neither its script nor its language. The publisher (`--output-gate
independent --recognitions`) re-qualifies and re-scores every transcript with the same 15 % gate
and refuses a cell the two families do not both meet on both channels. The record is `focused`
with `languageVerification.families: ["qwen3-asr", "whisper"]`, a two-family consensus. The
lineage's measurement version was 3 (WER v2, per-channel vote, Auto seed, corpus fixtures, macOS
prompt digest), 4 (normalization v2), 5 (Chinese fold) and is 6 (QC v2 families); records through 5
cite the retired whisper-small witness and keep validating. Fetch the models and build the runtimes
first (`qc.py models fetch --all`, `qc.py runtimes setup --runtime mlx|onnx|torch`); nothing
downloads automatically. `language_metrics.py` also accepts `sensevoice` as a family identifier;
publication cites only `apple-speech`, `qwen3-asr` and `whisper`.

Then `qc.py gate --lane language-bench` gates the run's QC v2 detectors (`audio-qc-gates.txt`; the
verdict's `audio_qc_gates` line). Until an evaluated thresholds file gives a detector a level, every
flag is report-only and the gate passes. A warn or a gate that could not be computed (ERROR) is
reported and never fails the lane; a fail does. The negative control is marked `control` and never
gates. The gate result is not part of the published record.

### 5.7 Offline gate tests

```sh
"$(python3 scripts/select_python.py)" -m pytest scripts/tests/test_check_ios_speech_assets.py scripts/tests/test_check_language_hints.py scripts/tests/test_check_language_output.py
# or, after editing a gate: scripts/dev.sh py
```

Phase 1 unit tests run in `scripts/macos_test.sh core-test`; language semantics are in
`docs/reference/qwen3-tts-guide.md` §7.

---

## 6. Telemetry schemas and fields

### 6.1 Architecture

```
 App process (Vocello)                    Engine (same process on macOS and iOS)
 ┌───────────────────────────┐  in-proc  ┌──────────────────────────────────────────┐
 │ Coordinators              │  ───────► │ NativeEngineRuntime.prepareGeneration      │
 │   mint generationID       │ generate  │   creates per‑generation recorder          │
 │ AudioPlayerViewModel      │           │ MLXModelLoadCoordinator (load/tokenize)    │
 │   submit→firstChunk→       │ ◄──────   │ GenerationOutputAdapter                    │
 │   playbackScheduled→done  │  chunks   │   decode loop + shared sampler/session      │
 │ AppGenerationTimeline      │           │   reads MLX timings, per‑chunk substages   │
 │ GenerationTelemetryMerger  │           │ Qwen3TTS (owned) emits timings/counters │
 └───────────────────────────┘           └──────────────────────────────────────────┘
        │  writes app row                          │  writes the engine row
        └──────────────► diagnostics/*/generations.jsonl ◄───────┘
                                  │ merge by generationID
                                  ▼
                         generations-merged.jsonl
```

Core types (all in `Sources/QwenVoiceCore/` unless noted):

| Type | Role |
|---|---|
| `TelemetryGate` | Master on/off, per process; in-process mode latch (`vocello bench`). |
| `NativeTelemetryRecorder` | Per-generation stage timeline (`mark(stage:)`). The generation telemetry session begins before model preparation and shares one clock across load, prewarm, synthesis, finalize, trim, cancellation, and failure. |
| `NativeTelemetrySampler` | Background memory/timing sampler → `TelemetrySummary` + raw `[TelemetrySample]`. |
| `GenerationTelemetryRecord` | One durable row per layer (`engine` / `app`; `engine-service` only in records before 2026-09-15). |
| `GenerationTelemetryJSONLSink` | Append-only writer (gated); also the verbose raw-sample sidecar. |
| `GenerationTelemetryMerger` (`Sources/Services/`, macOS) | Joins per-layer rows → `generations-merged.jsonl`. |
| `AppGenerationTimeline` (`Sources/SharedSupport/Telemetry/`) | Frontend submit→firstChunk→playbackScheduled→completed plus bounded playback-health counters. |

### 6.2 Output files

Under `~/Library/Application Support/QwenVoice[-Debug]/diagnostics/` (the `-Debug` folder when
`QWENVOICE_DEBUG=1`, so real data is never polluted):

| File | Layer | Contents |
|---|---|---|
| `engine/generations.jsonl` | backend | The decode breakdown, KPIs, per-stage MLX memory, per-chunk timeline, stage marks, memory summary. **The richest source for backend work.** |
| `app/generations.jsonl` | frontend | Submit→first chunk→playback scheduled→completed, delayed-heartbeat coverage, and playback health. It does not claim acoustic audibility or inherit engine memory. |
| `generations-merged.jsonl` | merged | Layers joined per `generationID`, with explicit `requiredLayers`, `missingLayers`, and `complete`. |
| `engine/samples-*.jsonl` | backend (verbose only) | Raw per-sample memory/timing series, one file per `generationID`. |
| `*/native-events.jsonl` | engine/app | Chunk-sequence gaps + encode drops; the **app** file also carries `mac_warm_admission_observed` / `mac_warm_blocked` (warm-admission gate) events. **Written only when telemetry is enabled** (`TelemetryGate.resolvedEnabled` / app-process intended mode). |
| `<documents>/generation-failures.jsonl` | debug | Append-only failure log when telemetry is on (see `GenerationFailureDiagnosticLogger`). |

One JSON object per line; the reading order is in [§7.1](#71-summarizer-invocation). These logs are
size-capped and auto-pruned, so no manual clearing is needed ([§9](#9-artifact-map)).

### 6.3 The per-generation record schema

`GenerationTelemetryRecord` (schema v8). Optional fields are omitted from JSON when nil and
v1–v7 rows remain decodable. New history publication that claims qualified memory requires v8;
older rows stay readable but are marked memory-contract-incomplete and excluded from memory trends.

> **Convergence status:** The shipping JSONL envelope remains schema v8 and still embeds a nested
> `GenerationStreamingTelemetryTransitionV9` projection. When the transition is publication-ready
> and every chunk carries its MLX instants, the engine also publishes a complete
> `*.streaming-telemetry-v9.json` sidecar and stamps `streamingTelemetryV9SidecarDigest` /
> `streamingTelemetryV9PublicationReady` notes. No producer observes MLX events: a chunk's
> `generatedAtNS`, `mlxEvaluationEnqueuedAtNS` and the two MLX durations are counted back from the
> engine's per-chunk step durations, and `materializedAtNS` is the output adapter's receipt of the
> chunk. Since output-adapter identity version 3 each such chunk says so with
> `mlxInstantProvenance: derived-from-step-durations`; older sidecars carry the same derived values
> without the label (audit #49/#62). Since version 4 every streamed chunk in the nested transition
> also carries `transportPublishedAtNS`, its hand-off to the product sink, with or without preview
> PCM (audit #48). History may bind those sidecar digests; the
> top-level JSONL schema is not flipped to 9. Sampling promotion packaging stamps
> `samplingPromotionPackaged=true` after `SamplingTakeEvidence.validatedForPromotion()`.

| Field | Type | Notes |
|---|---|---|
| `schemaVersion` | Int | 8 (v2 derived/memory/chunk; v3 model/warm state; v4 audioQC; v5 high-resolution clocks; v6 typed payloads; v7 sampler accuracy/resource deltas and playback-scheduled naming; v8 independently qualified memory captures, absolute uptime, aligned snapshots, and coverage). |
| `clockSource` | String? | `mach_absolute_time` when nanosecond timestamps are present. |
| `generationID` | String | Correlation key (UUID). |
| `layer` | String | `engine` / `app` / `merged` (`engine-service` and the iOS `engine-extension` layers are retired and appear only in older records). |
| `mode` | String? | `custom` / `design` / `clone`. |
| `modelID` | String? | Resolved model variant id (e.g. `pro_custom_quality`). |
| `warmState` | String? | `cold` / `warm` — the benchmark cell. |
| `usedStreaming` | Bool? | Streaming vs quality-first. |
| `finishReason` | String? | Typed terminal reason: `eos` / `maxTokens` / `cancelled` / `failed` / `completed` / `superseded` / `unknown`. Compatibility input also accepts `max_tokens` and `canceled`; v7 typed payloads encode the canonical values. |
| `stageMarks` | `[{tMS, tNS?, sequence?, stage, metadata}]` | Lifecycle timeline with optional nanosecond timestamps and monotonic sequence numbers ([§6.5](#65-stage-timeline-stagemarks)). |
| `frontendMetrics` | `FrontendGenerationMetrics?` | Typed submit/first-chunk/playback-scheduled/completed, delayed-heartbeat coverage, and bounded playback queue/continuity/underrun metrics. Legacy `*Audible*` keys decode as compatibility aliases only. |
| `transportMetrics` | `EngineTransportMetrics?` | Retired engine-service rows only (macOS records before 2026-09-15): typed request-to-first-chunk timing, terminal/cancellation/lifecycle, opaque session identity, first/last sequence, and forwarded/gap/duplicate/reordered counters. |
| `backendMetrics` | `BackendGenerationMetrics?` | Typed lifecycle stages, warm/streaming state, finish reason, timing/counter enums, and final-chunk barrier. |
| `outputMetrics` | `GenerationOutputMetrics?` | Duration, readable-WAV verdict, atomic-publication verdict, and audio QC. |
| `timingsMS` / `counters` | compatibility maps | Generated compatibility output for existing summarizers and old rows; new validators consume typed payloads. |
| `derivedMetrics` | `[String: Double]?` | Headline KPIs ([§6.8](#68-derived-kpis-derivedmetrics)). Includes `kvCacheEstimatedPeakMB` (2026-07-01, audit P1-2) — the peak of the per-chunk KV-cache footprint estimates, surfaced at row level so regression tooling doesn't walk the chunk timeline. |
| `mlxMemoryByStage` | `[String: {activeMB, cacheMB, peakMB, stagePeakMB?}]?` | MLX GPU memory at each stage ([§6.9](#69-memory-probes)); `stagePeakMB` only under `QWENVOICE_MLX_STAGE_PEAKS=1`. |
| `chunkTimeline` | `[GenerationChunkTelemetry]?` | Per-chunk decode substages, with `arrivalNS` (v5) and optional `mimiDecoderBreakdownMS` (v5) ([§6.7](#67-per-chunk-timeline-chunktimeline-streaming-only)). |
| `audioQC` | `AudioQCReport?` | Versioned reference-free overall, model-instability, and written-output verdicts plus flags, defect offsets, and optional per-chunk QC. Algorithm v8 (`makeAudioQCReport`; v7 adds warn-only `onset_step_burst`, v8 `speaking_rate_slow`) judges the atomically published WAV frames and, since 2026-09-12, also asserts the file's sample rate, channel count and frame count against the request ([§7.7](#77-output-quality-layers)). |
| `audioQC.signal` | `AudioQCSignalObservations?` | Since 2026-09-26 (AQ-04, additive on QC v8): the Stage 0 observational measures of the persisted WAV (BS.1770 loudness, loudness range and 4x true peak, noise floor, WADA-SNR, effective bandwidth, spectral-flux events, 12.5 Hz codec-frame modulation, seam z-score, repetition stripe) under their own `algorithmVersion`. No flag or verdict reads them; eleven reach the tracked take as `audioQC.metrics`. |
| `engineIntrospection` | `GenerationEngineIntrospection?` | Since 2026-09-26 (AQ-04, engine rows, success and post-terminal failure): the talker's own signals, from the facade's `VocelloQwen3GenerationIntrospection`: codebook-0 token cycles, per-step entropy (mean, p95, longest run at or above 4 nats), the EOS-probability trajectory and the streaming seam frames. Observational; telemetry only. |
| `summary` | `TelemetrySummary?` | Owning-process resident/physical-footprint/compressed/headroom/Metal start, end, delta, peak/min and aligned extrema snapshots; total RAM and implied process limit; independent memory/thread/headroom/Metal coverage; sampler cadence/boundaries; and process CPU/page-fault/context-switch/block-I/O deltas. `timeToPeakMS` tracks the physical-footprint peak. |
| `streamingTelemetryV9` | `GenerationStreamingTelemetryTransitionV9?` | Nested partial v9 transition projection carried by new schema-v8 rows. Invalid generation IDs may omit it; otherwise missing producer domains are explicit `unavailable` entries and never inferred as zero. It is not a publishable schema-v9 envelope. |
| `notes` | `[String: String]` | Bounded compatibility metadata such as `deviceClass`, `promptChars`, privacy-safe `promptDigest` (script text only — never the delivery instruction), the bench `delivery` cell stamp, the delivery-instruction receipt `instructChars`/`instructDigest` on instructed takes (verified fail-closed by the delivery bench; [§4.6](#46-delivery--prosody-cells)), and memory pressure. Raw script, transcript, voice description, file path, and failure message are forbidden; prompts/failures/instructions use SHA-256 identity rather than content. |
| `recordedAt` / `processName` / `processIdentifier` | | Provenance. |

`MergedGenerationTelemetry` is schema v2. A macOS or iOS UI record requires the app and engine
rows of the same run/generation (`engineService` only decodes pre-2026-09-15 records). The
`complete` flag and `missingLayers` list prevent a timed-out partial merge from appearing
authoritative.

### 6.4 os_signpost interval mirrors (`timingsMS`)

Beside the MLX decode counters, the runtime and output adapter time each lifecycle
span twice: an `os_signpost` interval (subsystem `com.qwenvoice.engine`, carrying the
run, generation, take and cell correlation fields) and a `timingsMS` key read where that
interval closes, so a JSONL row and a trace time the same span (audit #48):

| Key | Interval |
|---|---|
| `native_prepare_generation_ms` | `Native Prepare Generation` |
| `native_model_load_ms` | `Native Model Load` |
| `native_clone_conditioning_ms` | `Native Clone Conditioning` |
| `native_explicit_prewarm_ms` | `Native Explicit Prewarm` |
| `native_generation_stream_ms` | `Native Generation Stream` |
| `native_final_wav_finish_ms` | `Native Final WAV Finish` |

Each key appears only when its span ran. The pairs are written by hand at each site,
because every interval carries correlation arguments; the unused generic helper
(`withMirroredSignpost`, which could not carry them) was removed on 2026-09-25.

Some intervals are trace-only, with no `timingsMS` key, so no telemetry row or published
value changes with them. Inside `Native Final WAV Finish`, the manual writer's
`Native Final WAV Manual Header Build` / `File Write` / `Publish` and the publication marking pass
`Native Final WAV Marking` carry the take correlation. Outside a take, subsystem
`com.qwenvoice.engine` also emits `Long-Form Assembly`, `Long-Form Segment Join` and
`Long-Form Provenance Marking` (category `long-form`); `Model Artifact Download`,
`Model File Download` and `Model File Verification` (the SHA-256 pass; category `model-download`);
and the point events `Native Memory Pressure`, `Native Memory Trim` and `Native Model Unload`
(category `runtime`; the unload event marks unloads through `NativeEngineRuntime.unloadModel`,
not `stop()`, an iOS model switch inside a load or a failed load or prewarm). None of these names is in `scripts/lib/trace_intervals.py`'s decode-loop set,
and only `Native Prepare Generation` and `Native Generation Stream` bound a take's window, so the
per-take interval statistics ignore them; a profile's total signpost row counts include them. The
macOS CLI bench also publishes `ttfcObserverLagMS`, the part of `ttfcMS` its own
first-chunk observer adds after the engine handed chunk 0 to the product sink: the
observer's uptime at its first chunk minus chunk 0's nested-v9 `transportPublishedAtNS`,
the one clock read the output adapter takes as each streamed chunk's event returns from
the sink. The bench turns preview PCM off, so it joins on that stamp and never on
`previewPublishedAtNS`, which only preview-bearing chunks carry. Rows written before
output-adapter identity version 4 have no hand-off stamp and publish no lag.

### 6.5 Stage timeline (`stageMarks`)

Coarse milestones for one generation, in ms from generation start (the recorder and the
memory sampler **share one high-resolution `NativeTelemetryClock`**, so marks and samples
align on both ms and ns timelines). The session exists before model preparation and finishes
exactly once on success, cancellation, or failure. Each mark carries `tMS`, optional `tNS`
(nanoseconds since start), and a monotonic `sequence` number. Readers order by nanoseconds and use
sequence only to break ties. `metadata` values are
typed (`string`/`int`/`double`/`bool`) in v5, while remaining JSON-serializable.
Stages (`NativeRuntimeStage`): `preparedCacheValidation`, `preparedCacheRebuild`,
`tokenizerPreparation`, `upstreamModelLoad`, `prewarm`, `clonePreparation`, `streamStartup`,
`firstChunk`, `streamGenerationEnded`, `streamCompleted` / `streamFailed`, `unload`.
`streamGenerationEnded` closes the model/decode span before final WAV publication, while
`streamCompleted` is the successful terminal lifecycle mark. Load/prewarm marks appear only on a **cold**
run (warm runs skip that work — that's correct, not missing data). Two additional
string-keyed marks record memory events on every tier: `memory_pressure` and
`memory_trim` ([§6.9](#69-memory-probes)).

### 6.6 Decode breakdown (`timingsMS`)

The engine re-reads the model's diagnostics **after** the decode loop (the MLX hot-loop
totals are only finalized post-loop), so `timingsMS` carries the per-substage wall-clock
breakdown of where decode time actually went, accumulated across the whole generation.
The MLX layer owns these keys; the set is mode-dependent — **inspect a real row for the
authoritative list.** Representative keys (prefix `qwen_…`):

| Key (representative) | Meaning |
|---|---|
| `qwen_talker_forward_total` | LLM talker forward pass, summed over tokens. |
| `qwen_code_predictor_total` | Multi-codebook code-predictor loop. |
| `qwen_stream_decoder_total` | Streaming audio decoder (codec → waveform). |
| `qwen_stream_step_eval_total` | `eval(...)` flush after each forward step (GPU dispatch; under the default `.pipelined` policy only the `asyncEval` enqueue). |
| `qwen_stream_step_token_read_total` | The step's first blocking read, the sampled token: under `.pipelined` the host's wait for the step's GPU work (signpost `Token Read`). |
| `qwen_stream_step_eval_wait_total` | The observed step wait: equals the token read under `.pipelined`; 0 under synchronous policies, whose wait stays inside the eval call, and under `.deferred`, whose token read itself dispatches and waits for the work the token depends on. The v9 sidecar's derived `mlxMaterializationDurationNS` counts back this wait; rows and sidecars with that meaning carry output-adapter identity version 2 or later (3 labels the derived instants). |
| `qwen_stream_step_eos_read_total` | EOS-flag readback (a GPU sync). |
| `qwen_audio_chunk_eval_total` | Audio-chunk evals: the assembly `asyncEval`, the pipelined flush (signpost `Audio Chunk Flush`) and the tail chunk. |
| `qwen_token_loop_total` | Whole per-token loop wall time. |
| `qwen_tail_decode_total` | The work after the loop: the final pipelined flush, `.info`, and the tail chunk's decode, eval and sends (or quality-first's full decode). Rows since 2026-09-25 (audit #60); no loop key covers it. |
| `qwen_token_loop_unattributed` | In-loop time no named substage covers (slack to chase), read when the loop exits so the tail work after it cannot hide it. It still contains the sink hand-offs below. |
| `qwen_token_loop_sink_handoff_total` / `_count` | The awaited materialized-sink hand-offs inside the token loop (`.token`, `.codecFrame`, `.chunkTimings`, `.audio`, the pipelined flush's sends and the codec-trace sink); the final flush, `.info` and tail chunk after the loop are not counted (audit #61, 2026-09-25). A part of `qwen_token_loop_unattributed`, never subtracted from it. |
| `qwen_generated_code_count` | Tokens generated (counter). |
| `qwen_stream_decoder_calls` | Streaming chunk decode count. |
| prep / prewarm keys | `*_prefix_tokenize_ms`, `*_prefix_embed_build_ms`, `decoder_bucket_warm`, `*_prewarm_eval_ms`, … |

Use the breakdown to see which substage dominates (talker vs code-predictor vs decoder)
and how much loop time is `unattributed` (candidate for new sub-probes). The engine sums
each span unrounded and rounds a total once at export (audit #61), and every span has a
same-named `os_signpost` interval (subsystem `com.qwenvoice.engine.qwen3`) opened and
closed around the same code, so a profile's per-take interval sums line up with these keys. How
the summarizer groups them, and why they are not per-stage GPU compute, is in
[§7.3](#73-decode-breakdown-lazy-mlx).

### 6.7 Per-chunk timeline (`chunkTimeline`, streaming only)

One entry per emitted audio chunk — the decode substage deltas that produced it, plus its
wall-clock arrival. Mirrors the owned runtime's `ChunkSubstageTimings`:
`talkerForwardMS`, `codePredictorMS`, `audioDecoderMS`, `streamStepEvalMS`,
`streamStepEOSReadMS`, `audioChunkEvalMS`, plus `chunkIndex`, `arrivalMS`, and in v5
`arrivalNS` (nanosecond resolution from `NativeTelemetryClock`). In v5 verbose mode,
`mimiDecoderBreakdownMS` further splits the chunk decode into `quantizer`, `transformer`,
`upsample`, `seanet`, and `output` (coarse stage clocks around the Mimi decoder). This
exposes **cold-start vs steady-state** behavior and localizes stalls to a substage and a
chunk. Captured cheaply (a small struct appended per chunk, only when telemetry is on) and
written once at generation end.

### 6.8 Derived KPIs (`derivedMetrics`)

Computed once at generation end from data already gathered — the headline numbers for
backend throughput:

| Key | Definition | Read as |
|---|---|---|
| `audioSeconds` | Generated audio duration (frames ÷ sample rate). | Output length. |
| `requestWallSeconds` | Whole request on the per-generation monotonic recorder: prepare entry → `streamCompleted` (after the final WAV write), minus the one-time `startup.model_load_*` and `startup.prewarm_*` intervals. | Synthesis wall time; the wall side of RTF on cold and warm takes alike. |
| (published) `excludedStartupMS`, `modelLoadWindowMS`, `prewarmWindowMS` | The `startup.model_load_*` and `startup.prewarm_*` windows on the take's own recorder, and their sum: exactly what `requestWallSeconds` leaves out (`scripts/lib/rtf.py`, records since 2026-09-25). `prewarmMS` still times the explicit prewarm. | How much startup work the RTF excludes; work moved into these windows lowers RTF without being faster. |
| `realTimeFactor` | `requestWallSeconds ÷ audioSeconds`. | **Standard real-time factor (RTF): lower is faster, <1 = faster than real time.** Primary throughput KPI since 2026-09-12; published as `rtf`. Every record since then declares `run.rtfDefinition: "wall/audio"`; a record without that field predates the cutover, stores the decode speedup under `rtf`, and never shares a comparison key with a new one. |
| `decodeWallSeconds` | Decode wall time (`qwen_token_loop_total` when present, else model `.info.generateTime`, else `streamStartup→streamGenerationEnded` span). Excludes WAV finalize I/O. | Compute cost — **same time base as the summarizer `decode ms` column.** |
| `audioSecondsPerWallSecond` | `audioSeconds ÷ decodeWallSeconds`. | **Decode-loop speedup** (higher is faster), published as `decodeSpeedupX`. Records before 2026-09-12 stored it under `rtf`; it is not an RTF. |
| `tokensPerSecond` | Codec tokens ÷ decode wall seconds (from `.info` when present). | Decode throughput; compare across model variants / patches. |
| `generatedTokenCount` | Codec tokens produced. | Work done; normalize other metrics by this. |

A record's published `ttfcMS` is not one measurement: the macOS CLI bench stamps it from its own
submission to the first chunk its stream observer receives, while the iOS device runner reads the
engine recorder's `firstChunk` mark from prepare entry. Records since 2026-09-25 that carry a
`ttfcMS` declare which as `run.ttfcDefinition` (`cli-submit-to-first-chunk` or
`engine-prepare-to-first-chunk`), and the two never share a comparison key; older records carry no
declaration and keep their keys. (The summarizer's TTFC column is a third view: the app row's
submit→first chunk, `-` for CLI rows; [§7.2](#72-headline-table-columns).)

Frontend latency is the app row's `submitToFirstChunkMS` and
`submitToPlaybackScheduledMS`. The latter means the player was commanded with a bounded queued
buffer; it is **not** proof that acoustic output was audible — the macOS UI benchmark's played-audio
capture measures that ([§4.10](#410-macos-ui-benchmark-supplementary-integration-net)). The engine
row's `firstChunk` mark is backend-only; the transport row's `requestToFirstChunkMS` exists only in
macOS records before 2026-09-15.

#### RTF vs `decode ms` (read together, don't diff naively)

The summarizer prints **RTF** (`derivedMetrics.realTimeFactor`, request wall ÷ audio), **xRT**
(`audioSecondsPerWallSecond`, the decode-loop speedup) and **decode ms** from
`timingsMS.qwen_token_loop_total`. xRT and decode ms share the token-loop wall clock when
`qwen_token_loop_total` is present; RTF spans the whole request, so it is always the slower-looking
of the two figures.

Caveats that still apply (besides lazy MLX, [§7.3](#73-decode-breakdown-lazy-mlx)):

- **`.info.generateTime`** — a ContinuousClock span from KV-cache setup to the end of the token
  loop, emitted before the trailing decoder flush; retained only as a fallback and as the span behind
  `tokensPerSecond`. `qwen_token_loop_total` sums in-loop iterations only, so the two spans never
  isolate a decoder drain (the former `qwen_stream_decoder_drain_ms` key could not be positive and
  was removed on 2026-09-25).
- **Token-loop rounding (BT-06, 2026-09-25)** — `qwen_token_loop_total` and the other hot-loop
  totals are now summed unrounded and rounded once at export. Rows written before BT-06 summed
  per-step rounded milliseconds: an error of up to 0.5 ms per step, near zero when step durations
  jitter but systematic when they cluster. `decodeWallSeconds` and `decodeSpeedupX` (and the
  `tokensPerSecond` fallback when a row has no `.info`) can therefore shift at that change by up to
  0.5 ms x steps without an engine speedup; the gate's `tokps` reads `.info`'s own span and does
  not move. Rows since then carry `streamingV9OutputAdapterVersion` 2 or later.
- **Stage marks** — `streamGenerationEnded` closes before WAV finalize; do not compare
  `streamStartup→streamCompleted` to decode ms (finalize I/O inflates the old span).

Use **RTF** (lower is better; a higher value is the regression direction) for release throughput
gates; use **decode breakdown + chunk timeline** for where time goes; use **Instruments
signposts** ([§4.8](#48-macos-instruments-profile-signpost-validation)) for GPU attribution.

### 6.9 Memory probes

- **`mlxMemoryByStage`** — MLX GPU `active`/`cache`/`peak` MB captured at stage boundaries
  (`before_stream`, `first_chunk`, `after_stream`, `after_final_write`,
  `after_generation_trim`, `before_marking`/`after_marking` when marking runs, plus
  prepare/clone/prewarm stages). `peak` is cumulative since the request began, so a stage raised
  the request's high-water mark exactly when its peak exceeds the previous stage's. With
  `QWENVOICE_MLX_STAGE_PEAKS=1` (a production-affecting diagnostic behind `QWENVOICE_DEBUG`, named in the
  row's runtime-debug provenance; audit #3 part 2) each stage snapshot
  also carries `stagePeakMB`, that stage's own exact peak: the snapshot reads MLX's peak counter and
  resets it, bounded below by the memory active at the reset, while `peak` stays the running
  request maximum. It is off by default because a mid-request reset races the generation's
  allocations and the gate compares the per-request peak exactly. Both marking
  snapshots follow the cache release that precedes the marking pass, so the take's
  `mlxCachePeakMB` keeps excluding the end-of-generation cache. Shows GPU memory growth
  across the pipeline — key for restricted-hardware tuning. Captured at boundaries only
  (a GPU snapshot is too costly per chunk).
- **`summary`** (`TelemetrySummary`) — owning-process memory **curve** summary from the background
  sampler: resident, physical footprint, compressed, headroom, and GPU allocated start/end/delta
  plus peak/min; recommended Metal working set and usage ratio; total device RAM and the implied
  process limit; `timeToPeakMS`; and aligned `memoryAtStart`, `memoryAtEnd`,
  `memoryAtPeakPhysFootprint`, and `memoryAtMinimumHeadroom` snapshots. Memory, thread, headroom,
  Metal, and process-resource capture success/coverage are independent, so one failed API cannot
  masquerade as a zero value. Generation-scoped CPU, page-fault, context-switch, and block-I/O
  deltas remain process-owned. Since 2026-09-25 the summary also carries the kernel's
  physical-footprint ledger high-water mark at the first and last sample
  (`kernelPhysFootprintPeakStartMB`, `kernelPhysFootprintPeakMB`) and the graphics-tagged footprint
  at the last (`graphicsFootprintEndMB`). The ledger peak is exact but a process-lifetime maximum:
  it is the window's own peak only when the end value is above the start value, and never a system
  peak.
- **Boundary samples** — capture immediately around model load, first chunk, final WAV, and trim.
  They sit at stage edges, not at the allocation spike, so sampled peaks still miss allocations
  shorter than the sampler tick ([§6.12](#612-overhead-and-observer-effect)): more than half of the
  committed takes sampled a Metal peak below the exact `mlxPeakMB` (the MLX allocator's own
  per-request high-water mark), typically by hundreds of MB. Treat sampled peaks as lower bounds
  and `mlxPeakMB` as the exact MLX figure. `benchmark_history.py validate`
  and `record` warn (without failing) when a take's `peakGPUAllocatedMB` is below its `mlxPeakMB`,
  and `benchmark_history.py peak-miss-report [--json]` reports the count for every committed record
  without rewriting any.
- **Verbose raw series** — `verbose` mode writes every sample (`tMS`, `scheduledElapsedNS`,
  `capturedElapsedNS`, absolute `capturedUptimeNS`, `latenessNS`, `kind`, `boundary`,
  `processRole`, resident/physical-footprint/compressed/headroom/Metal values, total RAM, implied
  process limit, the kernel ledgers read in the same `task_vm_info` call
  (`kernelPhysFootprintPeakMB`, `graphicsFootprintMB`; absent when the kernel did not fill them),
  and separate `memoryCaptureSucceeded`, `threadCaptureSucceeded`,
  `headroomCaptureSucceeded`, and `metalCaptureSucceeded` flags) to the exact
  `<layer>/samples-<generationID>.jsonl` sidecar. Raw rows remain untracked.
  Off by default (higher volume).
- **Kernel memory-pressure marks** (in `stageMarks`) — on every tier, where
  `NativeMemoryPressureMonitor` runs:
  - `memory_pressure` — the **raw kernel signal** (`metadata.level` = `softTrim`/`hardTrim`),
    stamped by `NativeEngineRuntime.recordMemoryPressureObserved` the instant the
    `DispatchSource` event arrives. Always recorded — it takes no prewarm slot.
  - `memory_trim` — the **trim action** taken in response (`metadata.level` + `reason`, e.g.
    `macos_memory_pressure_hardTrim`). Written by
    `NativeEngineRuntime.trimMemory`; skipped if the prewarm slot is contended, hence the
    separate always-on `memory_pressure` mark above.

  A run with a `hardTrim` mid-generation is shedding model state under pressure — an early
  OOM signal. Every tier starts the monitor (the high-memory Mac since AUD-10), so absent
  marks mean the kernel reported no pressure, not missing data. `headroom*` summary fields populate on
  iOS only (`os_proc_available_memory`); on macOS they're nil and `phys_footprint` is the
  OOM-relevant figure to watch.

On iOS, MetricKit's delayed daily aggregate is a complementary field signal. The app persists only
a bounded privacy-reduced memory/exit summary; raw payload JSON, call stacks, identifiers, and paths
are not retained for this purpose. After an explicit device pull,
`scripts/ios_device.sh memory-field-report [pulled-diagnostics]` reads local files only. It does not
contact the phone, does not publish benchmark history, and reports `notYetDelivered` nonfatally when
MetricKit has not delivered a payload. Each lane pull copies the same rolling document, so the report
counts one record per (kind, interval start, interval end), keeps the newest document's copy and
reports the rest as `duplicateRecordCount`. Daily values are not run-correlated and cannot qualify or
retroactively fail an individual take.
The Mac app keeps the same document under its app-support `diagnostics/` folder (DW-03,
`MacMetricKitReporter`), with the same limits; no lane or report reads it yet.

### 6.10 Memory qualification contract

New publishable generation benchmarks require telemetry schema v8 and benchmark-evidence manifest
v2. Manifest v2 binds `memoryContractVersion: 2` (since 2026-09-25), `memoryQualified: true`, the
exact selected sidecar count/digest, each take's `memoryStatus` plus sidecar digest, and bounded
start/end/delta/peak, headroom/utilization, sampler, pressure, trim, warning, and exit metrics. Raw
samples remain untracked.

**Sidecars.** For every selected generation, the exact `engine/samples-*.jsonl` sidecar for that
`generationID` must start with one `start` and stop with one `stop`, keep monotonic elapsed and
absolute-uptime clocks, match all summary counts and report zero memory-capture failures. Engine
evidence includes the preparation/model-load/session/first-output/final-WAV/terminal boundaries;
app evidence includes `app_submit` and `app_terminal`. iOS additionally requires finite headroom
samples.

**One process, one series.** The macOS app hosts the engine, so its app-layer and engine-layer
samplers are two readers of that one process. A macOS UI take's series is the union of both
layers' samples in absolute-uptime order (a duplicate uptime counted once), spanning the app's
submit-to-terminal window; its values are never summed, and both rows must name the same process
ID. The app sidecar contributes its samples, its coverage and its submit/terminal order.
Contract-v1 macOS UI records (2026-09-15 to 2026-09-25) summed uptime-paired app and engine samples
of that one process and so report about twice its memory; they are not rewritten. Headless
CLI/profile evidence reports only its owning engine process.

**Timer health.** Contract v2 judges each take's one memory series. No gap between two consecutive
samples (`samplerMaximumUnobservedGapMS`) may exceed the bound in
`config/memory-qualification-policy.json` `unobservedGapBound`: max(twice the sampler's target
interval, 500 ms), so a single stall at the 100 ms cadence of Macs above 16 GB does not fail a
take, or max(twice the interval, 1,000 ms) on the floor tiers (`floorTiers`: an iPhone, or a Mac
whose engine row stamps `floor_8gb_mac`). A longer gap fails publication, and each take records the
bound it met as `samplerUnobservedGapLimitMS`. The policy records each bound's calibration status
and run: the general bound is calibrated on the canonical M6, while the floor tiers' 1,000 ms floor
stays provisional until an unforced iPhone or 8 GB Mac record calibrates it; an M6 record never
moves it. Periodic coverage (`samplerCoverage`,
`samplerMissedDeadlineCount`) is still published but no longer gates, because it counts deadlines
honoured rather than whether the peak was seen.

**Calibration.** After a memory lane,
`python3 scripts/derive_memory_calibration.py benchmarks/runs/memory-qualification/<run-id>.json`
prints what the run measured and the bounds it proposes: from a Mac above the floor tiers, the gap
multiple (never below 2, the floor unchanged) that covers every take's longest gap with a 1.25
margin; from an iPhone or 8 GB Mac record, the floor tiers' floor (the largest such bound rounded up
to 50 ms, never below 500 ms); and each mode's retained-memory-v2 bound
([§4.11](#411-retained-memory-qualification); the mode's MLX growth plus three times its end-of-take
spread, rounded up to 8 MB, at least 16 MB). `--write` records them in the policy as calibrated with
the run ID; a forced or emulated tier, or a record without its runtime policy, calibrates no gap
bound. The maintainer commits the policy with the record.

**Peak fidelity.** `gpuPeakCaptureMissMB` is how far the sampled Metal peak fell below the exact
`mlxPeakMB` (0 when it caught it). When the sampler read the kernel ledgers (samplers since
2026-09-25, from the same `task_vm_info` call), `kernelPhysFootprintPeakMB` is the process-lifetime
footprint high-water mark at the take's end: `kernelPhysFootprintPeakExact` is 1 when it rose inside
the take, so it is the take's exact peak and `footprintPeakCaptureMissMB` is the sampled peak's
shortfall, and 0 when it is only an upper bound set earlier in the process; `graphicsFootprintEndMB`
is the graphics-tagged footprint at the take's end. A ledger peak below a sampled footprint is a
broken read and fails publication; a miss is reported, never failed.

**Pressure.** Critical pressure, `application_memory_warning`, a memory exit, `hardTrim`, or
`fullUnload` fails publication and leaves tracked history unchanged. Guarded pressure or `softTrim`
is `passedWithWarnings`, except the routine per-tier cache clear (source `post-generation`, reason
`post_generation_cache_clear`): since 2026-09-25 it is counted as `policyCacheClearCount` with no
pressure level and no warning. iOS additionally fails at a peak process-budget utilization ≥0.92
(the take's footprint over its own process limit, exact through the kernel ledger when it rose
inside the take; audit #68) or minimum headroom <384 MiB, and warns at utilization ≥0.80 or
headroom <768 MiB. The fractions and headroom bands are declared once in
`config/ios-memory-budget-policy.json`, beside the app's admission bands (a Swift test pins
`IOSMemoryBudgetPolicy` and its `EvidenceBudgetUtilization` to it); the absolute footprint bands and
the Metal working-set ratio no longer judge evidence. The iOS record retains start/end/min headroom
and peak process-budget utilization.

**Contract v1.** Records before 2026-09-25 are contract v1: they required at least 95% periodic
coverage (95–<100% was warning evidence), and they keep that meaning. The contract version joins the
comparison key from v2 on, so a v2 series never shares a lineage with a v1 aggregate.

### 6.11 Frontend responsiveness and playback health

The app watchdog uses generation-scoped session tokens so a late callback from a finished run
cannot contaminate the next. It reports scheduled/completed heartbeat counts, coverage, delayed
heartbeat counts at the configured thresholds, and the maximum observed delay. These are sampling
statistics, not an exhaustive count of every main-thread stall. Since 2026-09-25 a heartbeat still
queued behind the main thread when the session ends counts as a censored observation: its age at
`end()` is a lower bound on its delay and enters the thresholds and the maximum
(`frontendMetrics.censoredHeartbeatCount`, `heartbeatDelayDefinition: completedAndCensoredPending`;
rows without the field counted completed heartbeats only, which read low at the generation boundary).
The UI benchmark records carry the same count as the take metric `censoredHeartbeatCount`, so a
tracked `uiMaximumDelayedHeartbeatMS` names its definition: a take without the key predates it.
The macOS UI benchmark judges this statistic under its stall contract
([§4.10](#410-macos-ui-benchmark-supplementary-integration-net)).

App telemetry also records bounded playback health: chunks received, continuity failures,
underruns, queued chunks/audio at playback scheduling, and minimum queue duration. This makes UI
benchmarks sensitive to streaming health while keeping raw audio and user content out of telemetry.

### 6.12 Overhead and observer effect

Designed so the numbers you optimize against are trustworthy.

- **Gated to zero when off.** No recorder, no sampler, no writes; per-chunk capture is
  guarded by `telemetryRecorder != nil`.
- **Device-tiered sampler cadence** (`NativeTelemetryMode.sampleIntervalMS(for:)`, the same in
  lightweight and verbose): high-memory Mac 100 ms; 16 GB Mac, 8 GB Mac and iPhone 250 ms (the
  floor tiers sampled every 500 ms until 2026-09-25, when periodic ticks stopped enumerating
  threads, their heaviest call; audit #3). Each sample records its own `captureDurationNS`, and a
  take's `samplerBoundaryCaptureTotalMS` sums the boundary captures the generation path awaits
  inline (audit #65) — the background sampler never competes with generation on constrained
  devices.
- **Cadence is measured, not assumed.** Periodic samples retain scheduled and captured elapsed
  nanoseconds plus lateness. The summary reports effective/maximum interval, maximum drift,
  boundary count, and capture failures; the old duplicate elapsed timestamp remains decode-only
  compatibility data.
- **Per-sample cost reduced.** The Metal device is resolved **once per generation** and
  reused (`IOSMemorySnapshot.capture` would otherwise allocate a fresh `MTLCreateSystemDefaultDevice()`
  every tick). A sample is a few `task_info`/mach calls + one cached-device GPU read.
- **No hot-path additions.** Writes happen at generation boundaries; the per-chunk timeline
  is an in-memory append, persisted once at the end. The bounded macOS chunk stream is drained
  continuously and never blocked by file I/O; `GenerationScopedEventRouter` accounts every send as
  accepted, terminated or unobserved.
- **The backend timing reads do not add GPU syncs.** The `eval`/EOS-read syncs that
  `qwen_stream_step_*` measure are required by generation itself — telemetry times existing
  work. Signposts are near-zero when Instruments isn't attached.

Rule of thumb: compare like with like. Lightweight and verbose run the same sampler; `verbose`
adds the raw-sample sidecar write, so for the tightest latency numbers use `lightweight` and read
`derivedMetrics` + `timingsMS`. The telemetry-overhead lane
([§4.12](#412-telemetry-overhead-parity-lane)) measures the cost of each mode against off.

### 6.13 Extending the telemetry

- **New backend substage timing:** add a `ContinuousClock` accumulator in the Qwen3TTS
  decode loop (`Packages/VocelloQwen3Core/Sources/MLXAudioTTS/Models/Qwen3TTS/Qwen3TTS.swift`) and store it into
  the model's preparation-timings dict — see [`qwen3-core-maintenance.md`](qwen3-core-maintenance.md)
  for the patch + validation gates. It will surface automatically in the engine row's
  `timingsMS` (the session re-reads the model post-loop). Avoid adding `eval()`/`.item()`
  syncs purely to measure — they distort the very thing you're measuring.
- **New stage mark:** add a `NativeRuntimeStage` case and `recorder.mark(stage:)` at the site
  (or a string-keyed `recorder.mark(stage: "…")` for one-off events like `memory_pressure` /
  `memory_trim` — no enum/schema change, the mark flows through `stageMarks` automatically).
  In v5 prefer typed metadata (`recorder.mark(stage:, metadata:)`) over string formatting for
  numeric metadata.
- **New derived KPI:** extend `computeDerivedMetrics` in `GenerationOutputAdapter`
  (`Sources/QwenVoiceCore/GenerationOutputAdapter.swift`).
- **New signpost interval:** open the interval and read the clock around the same code, and
  close it where the timing is captured (as `native_prepare_generation_ms` and the Qwen3 loop
  spans do), so the trace and the `timingsMS` key time the same span (audit #48). Inside the token loop use the allocation-free
  `os_signpost` entry point: `OSSignposter.beginInterval` allocates per call. A trace-only
  interval (no `timingsMS` key, so no telemetry change) is listed in [§6.4](#64-os_signpost-interval-mirrors-timingsms), takes a name outside
  `scripts/lib/trace_intervals.py`'s decode-loop set, and takes its own signpost ID when instances
  can overlap.
- **New field on the record:** add an optional field to `GenerationTelemetryRecord` (so old
  rows still decode) and bump `currentSchemaVersion`.
- **Naming:** use the `NativeTelemetry…` / `GenerationTelemetry…` families for new telemetry
  types.

---

## 7. Reading results

### 7.1 Summarizer invocation

```sh
python3 scripts/summarize_generation_telemetry.py <DIAGNOSTICS_DIR> \
  --run-id <run-id> --evidence-manifest <artifact-dir>/benchmark-evidence.json \
  --label release-QA
```

For an authoritative benchmark, both selectors are mandatory: the run ID rejects unrelated rows,
and the evidence manifest supplies the exact ordered generation IDs/cells, so historical rows cannot
leak into the current summary. Never summarize an entire historical diagnostics directory as if it
were one run. Ad-hoc diagnostics may still use the default directory
(`QwenVoice-Debug/diagnostics`) without being eligible for registry publication. The summarizer
merges the app and engine layers by `generationID`; CLI rows have only the engine boundary. Read
`finishReason` and `audioQC` before interpreting performance, keep cold and warm populations
separate, and compare `derivedMetrics.realTimeFactor` (and the decode speedup
`audioSecondsPerWallSecond`) with the dominant `timingsMS` substage. A cold Custom or Design row
should include `upstreamModelLoad` in `stageMarks`; an immediately repeated row should be warm.

The summarizer is streaming (it walks JSONL once with `iter_jsonl`, maintains a lightweight app
index, and aggregates with `CellAccumulator`), so it handles large verbose logs without loading
them into memory. It is read-only.

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

### 7.2 Headline table columns

The main block is a `mode × model × cold/warm` table (median over warm). A header line shows the
**tier** each row ran under (from `notes.deviceClass`) and flags a forced or emulated tier.

| Column | Source | Notes |
|--------|--------|-------|
| RTF | `derivedMetrics.realTimeFactor` (request wall ÷ audio) | Primary throughput KPI, lower is faster |
| xRT | `derivedMetrics.audioSecondsPerWallSecond` (audio ÷ decode s) | Decode-loop speedup, higher is faster |
| tok/s | Codec tokens / decode wall | Compare across variants |
| TTFC ms | App row `submitToFirstChunkMS` | `-` for CLI (no app process) |
| decode ms | `timingsMS.qwen_token_loop_total` | Same time base as xRT ([§6.8](#68-derived-kpis-derivedmetrics)) |
| peakGPU / RSS / physFoot | Sampler peaks | `physFoot` (phys_footprint peak) is the Jetsam-relevant OOM figure |
| headMin | Minimum available headroom | iOS only; `-` on macOS |
| trims | `memory_trim` stage marks | Median count per cell, annotated with the worst level (`soft`/`hard`/`full`); derived from `stageMarks`, no new record field |
| UIdelay | App row delayed-heartbeat count/max plus coverage | Sampling signal; `-` for CLI, not an exhaustive stall count |
| QC | `audioQC.verdict` + flags | `fail` = hard stop ([§7.7](#77-output-quality-layers)) |

A second block — **GPU MB by stage** (`load → stream → peak → trim`, from `mlxMemoryByStage`) —
shows *where* GPU memory grows across the pipeline and how much the post-generation trim reclaims.
A third block is the decode breakdown ([§7.3](#73-decode-breakdown-lazy-mlx)), and delivery runs
add the prosody block ([§4.6](#46-delivery--prosody-cells)).

### 7.3 Decode breakdown (lazy MLX)

Columns: `talker · sampCB0 · codePred · code2wav · stepEval · other`, from the `timingsMS` sub-keys
([§6.6](#66-decode-breakdown-timingsms)); named + other ≈ decode ms.

These are Swift-side wall-clock timers around **lazy** MLX graph ops, not per-stage GPU compute;
they sum to less than `qwen_token_loop_total` when work is pipelined across iterations:

- **stepEval** ≈ the fused per-frame `eval()` (Talker + CodePredictor + sampling) — the best compute
  proxy in JSONL
- **talker / codePred** ≈ graph **build** time, not GPU kernels
- **code2wav ≈ 0** — the decoder is `asyncEval`'d (Phase 2c) and overlaps the token loop
  (pipelined, not free)

To attribute compute per stage, capture the os_signpost intervals under Instruments `xctrace`
([§4.8](#48-macos-instruments-profile-signpost-validation)): **Step Eval Flush**, **Code Predictor
Loop**, **Talker Forward**, **Audio Decoder**.

### 7.4 Chunk timeline block

When streaming, the summarizer prints per-cell medians: chunk count, first-chunk ms, inter-chunk ms,
substage ms. Use for cold-start vs steady-state analysis ([§6.7](#67-per-chunk-timeline-chunktimeline-streaming-only)).

### 7.5 Thermal and environment

The summarizer prints **thermal** (worst state in cell), **gpuWS** (`gpuWorkingSetUsageRatioPeak`),
and **headMin** (`headroomMinMB`) when the sampler collected them. Re-run if thermal throttling is
suspected; inspect raw JSONL for full `thermalState` start/end/worst.

### 7.6 Memory and pressure interpretation

RAM usage (physFoot/RSS/peak-GPU + the per-stage GPU block) is captured on **every** run. The
**memory-pressure** signals (`trims`/`pressure`) fire on every tier, but `deviceClass()` is derived
from real RAM and a high-memory dev Mac rarely reaches kernel pressure — so there they usually
read `0`.

A forced class (`QWENVOICE_FORCE_MEMORY_CLASS`, [§2](#runtime-knobs)) makes the engine run the
floor-tier code paths: caches are tight, single-gen clears fire, and idle-unload is short and
shortens further under pressure. Every engine row stamps `notes.deviceClass`, so the summarizer
header shows `tier: floor_8gb_mac ⚠ forced or emulated` — never mistake a forced or emulated run
for native-tier data, and see [§4.4](#44-floor-tier-forced-run) for what floor emulation can and
cannot claim. Pressure-triggered trims appear as `memory_pressure` and `memory_trim` stage marks.
Interpret them together with `physFoot`, the GPU-by-stage block, and the recorded device class; a
forced class is diagnostic evidence, not proof for that physical device.

> **Caveat:** on the forced floor tier, a Quality load that cannot fit will surface as an error rather
> than silently falling back to Speed. The row's `modelID` reveals the actual variant served — check it
> before attributing a Quality cell. The forced tier changes real behavior **only while the env is set**;
> unset it for normal use.

**Watch for OOM regressions** when optimizing the backend: a rising `physFoot` peak, GPU-stage peak,
or any `hardTrim` in `trims` means a run is shedding model state under pressure — the early OOM signal.

### 7.7 Output-quality layers

Perf is only half the story — a backend change must not introduce **audio** regressions (glitches,
dropouts, garbled words, "sounds worse"). Interpretation order is `audioQC` first, then
fixed-seed/ASR evidence and any requested delivery/per-clip prosody output. Any `QC=fail` is a hard
stop for engine promotion, and an unresolved warning is publishable evidence but not
promotion-quality. The in-engine `audioQC` is the default signal; committed bounded quality
summaries and baselines remain permitted.

1. **Reference-free defect detector — automatic, every run.** The engine runs a per-sample QC pass on
   the final PCM (extends `PCM16StreamLimiter`) and writes an `audioQC` verdict into the engine row:
   `pass` / `warn` / `fail` plus flags — `nonfinite` (NaN/Inf model output), `clipping`, `clicks`
   (chunk-boundary discontinuities — the decoder-drift class), `dropout` (interior silence),
   `near_silent` (dead output), `onset_step_burst` (v7: at least three quarter-scale steps clustered
   inside the first 50 ms, warn-only — the fp16 codec's first streamed chunk signature; the ordinary
   plosive-onset cluster 150 to 250 ms in is recorded as `stepBurstPeakCount` / `stepBurstPeakStartMS`
   and not judged), and `speaking_rate_slow` (v8). Surfaced as the summarizer's **`QC`** column.
   Thresholds are conservative + tunable (`makeAudioQCReport`).
   **Dropout is punctuation-aware.** Long interior pauses (≥350 ms) count against the text's
   punctuation pause budget; an excess (flag `dropout:excessN`, followed by the long-pause count over the budget in parentheses; ≥2 fail, 1 warn) or a
   single egregious gap (≥1200 ms fail, ≥900 ms warn) flags. The regimes and their calibration
   history live in `makeAudioQCReport`; a threshold changes only on labelled evidence (QC v2 owns
   the maintainer's labels and confirmations and their evaluation, [`qc.md`](qc.md)), and a warning is
   never cleared by a subjective waiver.
   In v5 `audioQC` also reports **defect sample offsets** for debugging: `firstNonFiniteSample`,
   `firstClipSample`, and `longestSilenceStartMS`. In verbose mode the streaming path captures
   `chunkQC: [AudioQCChunkReport]` so defects can be tied to an individual output chunk. The report
   carries separate `instabilityVerdict` (pre-limiter evidence) and `writtenOutputVerdict` (the
   persisted WAV's exact frames) values in addition to the worst overall verdict; the algorithm
   version is stored with tracked evidence.
2. **Prosody analysis — conditional or explicit, no external model.** `vocello bench --delivery`
   runs the paired `scripts/bench_delivery_prosody.py` analysis on its manifest-selected
   neutral/instructed pairs ([§4.6](#46-delivery--prosody-cells)).
   `scripts/prosody_quality_gate.py` analyzes individual takes for monotone, rushed, flat, and
   pause-issue signatures only when invoked explicitly. All are deterministic, reference-free, and
   operate on bench WAVs.
3. **Language hint and output verification.** The language bench ([§5](#5-language-bench)) checks
   the resolved language hint and scores spoken output against the script.
4. **Optional listening annotation.** Automated checks deliberately claim structural integrity,
   intelligibility, language accuracy, reference consistency, and bounded prosody — not subjective
   beauty or naturalness. A person may annotate those impressions
   ([§8](#listening-annotation)), but the annotation never changes the machine verdict.

---

## 8. Publication, lineage and baselines

### PASS-only registry

Every in-repository benchmark-like lane publishes only after its own success contract passes. The
runner writes an atomic untracked `benchmark-evidence.json`, then calls:

```sh
python3 scripts/benchmark_history.py record --artifact-dir <run-artifact-dir>
python3 scripts/benchmark_history.py validate --all
python3 scripts/benchmark_history.py rebuild-index --check
```

Publication creates one allowlisted `<kind>/<run-id>.json` record under `benchmarks/runs/` (one
directory per kind, ≤256 KB per record) and regenerates `benchmarks/HISTORY.md`; direct Markdown
append is unsupported, and publication never stages, commits, or pushes. Re-recording
byte-identical evidence is idempotent. A conflicting run ID, duplicate evidence digest, privacy
violation, oversized record, failed QC, failed finish, crash delta, missing layer, wrong take
order, or unreadable WAV fails publication and leaves tracked history unchanged. If publication
fails after the expensive run passed, retain the local artifact directory and rerun the printed
`record --artifact-dir` command after repairing the exporter.

An accepted QC warning produces `passedWithWarnings` and remains visible in run/cell warning
counts and worst-QC fields. A QC failure is never downgraded or published.

Tracked benchmark kinds (schema v3 when every take carries the quality-registry identity, schema v2
otherwise, `ui-perf` records are v2; schema-v1 history is read-only) are:

| Kind | Publisher | Minimum publishable success |
|---|---|---|
| `ui-generation` | `ui_test.sh macos|ios benchmark` | XCTest, exact selected matrix/order, complete required telemetry layers, memory qualification, readable atomic WAVs, QC, and crash delta |
| `engine-generation` | `vocello bench`, iOS headless bench, optional gate bench | Exact selected rows, memory qualification, successful finishes, readable/QC-accepted output, and command PASS |
| `language` | macOS/iOS `lang-bench` | Requested hint/output gates; hint-only is explicitly `partial` |
| `instrument-profile` | macOS/iOS profile commands | Memory-qualified target generation PASS, exact PID, tracer success, valid trace TOC, non-empty exported performance rows, and run/generation/take/cell-correlated signposts |
| `memory-qualification` | macOS/iOS `memory` commands | Fixed policy topology, v8 sidecar qualification, output/QC success, and within-mode retained-footprint growth ≤5% of the canonical profile's RAM |
| `prosody-calibration` | `publish_benchmark_history.py prosody` (producer `prosody_calibration.py` deleted 2026-10-01, `c44d0205`) | Required corpus coverage with no analysis failure |
| `ui-perf` | `ui_test.sh macos|ios perf` via `check_macos_ui_perf.py` / `check_ios_ui_perf.py` (registered 2026-08 with the macOS frame-health lane) | Structural gate PASS (every expected scenario once each: eleven on macOS, nine on iOS; coverage/refresh sanity), canonical hardware profile, and crash delta; threshold breaches are warn-only (`passedWithWarnings`); iOS records carry the platform-aware ceilings from `config/ui-perf-thresholds-ios.json` |

Schema-v1 `telemetry-overhead` records remain readable historical evidence, but new overhead runs
are local observer-effect diagnostics and do not publish ([§4.12](#412-telemetry-overhead-parity-lane)).
Delivery/prosody cells from `vocello bench --delivery` remain inside their parent engine-generation
record. Smoke, unit tests, crash inspection, preflight, and standalone analysis tools do not publish
benchmark records. Existing Markdown/JSON baselines remain reference artifacts; they are not
silently upgraded into complete records.

### Record contents and privacy

A strict allowlist rejects identifiers and content that could expose serials, UDIDs/ECIDs,
host/device/user names, absolute paths, prompts/transcripts/voice descriptions, raw errors, email
addresses, URLs, or secrets. Run labels are opaque machine identifiers (letters, numbers, `.`, `_`,
`-`) and warning fields contain only bounded machine codes; listening notes remain the separately
scanned human-review field.

Every record binds source SHA/dirty paths and fingerprints, hardware/OS/thermal context, toolchain
and executable identity, project/input/harness hashes, model/runtime/fixture identities, evidence
digests, ordered takes, per-cell distribution statistics, and optional independent listening
review. A successful profile record captures the
original trace digest/path, capture settings, extracted summary, and retention policy
([§4.8](#48-macos-instruments-profile-signpost-validation)). Memory-qualified (v2+) records are
never mixed into memory trends with v1.

Tracked validation re-derives cell aggregates and enforces each kind's immutable success shape,
including structured PID/CPU/signpost profile evidence, schema-v2 sidecar memory qualification and retention
policy evidence, and complete prosody-calibration aggregates. Registry validation is deterministic
CI work, but model/device/UI execution is not an ordinary CI or packaging gate.

### Trends in HISTORY.md

`HISTORY.md` is a generated index grouped by kind, platform, hardware, and comparable
configuration. `rebuild-index` reconciles comparison deltas from the nearest earlier compatible
clean record, so merge order cannot leave stale trends; the `--check` form rejects any
unreconciled record. The trend takes the median per-cell delta over cells with at least three
takes and reads "within noise" below max(5%, 3 × the median absolute deviation of the cell
deltas), or "not trended" when only smaller cells carry a delta; UI records trend on the app's
submit→first-chunk span. A delta is information: it does not automatically fail a benchmark whose
own correctness gates passed. [`benchmarks/LEGACY_HISTORY.md`](../../benchmarks/LEGACY_HISTORY.md)
preserves the former manual ledger as incomplete historical evidence.

For trustworthy deltas: use the same canonical hardware, keep it quiet, watch thermals, keep cold
and warm separate, and compare medians/IQR from equivalent matrices.

### Listening annotation

Automated success and optional perceptual review are independent. Add the latter without rewriting
the run:

```sh
python3 scripts/benchmark_history.py annotate --run-id <run-id> \
  --listening pass --note "reviewed representative takes"
```

Use `fail` or `not-performed` when appropriate; never edit `HISTORY.md` directly. Listening never
changes the automated verdict, is not required for promotion, and does not authorize overriding a
deterministic failure or warning; it records subjective observations that deterministic gates do
not claim to measure.

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

Compare a history record only against one with the same generated comparison key; the key selects
the nearest earlier compatible clean run. It includes the lane, platform/hardware profile, matrix
(including CLI streaming/seed and overhead rotation settings), model/runtime identity, the exact
optimization identity, toolchain, OS, and relevant input identities (executable hashes are
provenance, never identity). Legacy records also key on whole-tree project and harness hashes and
keep their stored keys byte for byte. Records stamped with a lineage contract
(`inputs.lineageContractVersion`, `scripts/lib/lineage_identity.py`) key instead on what their kind
measures: the project.yml build settings its lane builds, the take topology (the layer set) and the
kind's reviewed measurement version; contract 2 (the current one) adds a forced or emulated memory tier
(`run.runtimePolicy`; a native tier adds nothing to the key), the run's seed policy
(`run.seedPolicy`) and the cell aggregate version (`evidence.cellAggregateVersion`), while
contract-1 records keep their keys. A contract-2 record at the defaults (a native tier, no seed
policy, aggregate 1) keeps the contract-1 key, so the M6 engine gate lineage continues across the
contract bump; a contract-1 record cannot carry a seed policy or aggregate 2. Harness and engine
edits therefore keep a lineage (HISTORY marks "harness changed"), while a scheme, compiler-setting,
topology, model or definition change starts a new one; a change that alters what a kind measures
bumps its measurement version. `python3 scripts/benchmark_history.py lineage-replay [--kind K
--platform P]` replays the current contract over committed records from their own source commits,
read-only. Consequently a historical `-Onone` record cannot become the baseline for a new `-O`
record; the first clean optimized record reports an explicit no-baseline state. Dirty runs are
exploratory; dirty, instrumented, partial, and forced-profile runs are excluded from canonical
comparisons and normal timing trends.

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
the baseline's ("engine output changed"). The gate rejects legacy metric-only baseline arrays
because they cannot prove whether they came from `-Onone` or `-O`; a reviewed baseline replacement
must be generated from an exact successful evidence manifest.

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

The committed baseline's own identity and `seededRuns` record the commit, host, OS and toolchain it
was pooled from (last re-pooled on 2026-10-16 for the mlx-swift 0.32.3 repin, CONV-21). A new OS or
Xcode build number changes the identity and needs a re-seed; earlier baselines stay in git history
only.

**Between-run noise before the gate MAD changes (audit #106, 2026-09-25).** Three MADs of one
run's five warm takes measure within-run noise; drift between runs of identical source is what a
false regression is made of. Following the audit's recommendation (the maintainer delegated the
decision), `scripts/estimate_between_run_noise.py` estimates it from committed records (`--records
benchmarks/runs/engine-generation --label mac-gate-bench`) or a governed baseline's `seededRuns`
(`--baseline benchmarks/baselines/mac-gate-bench.json`, which agree exactly): for every group of
clean runs sharing the gate identity and one commit it reports each metric's run medians, their
relative range and MAD beside the median within-run 3-MAD threshold, and replays the gate
leave-one-run-out with the summarizer's own `pooled_cells` and `compare_summaries`, so a flagged
metric is a false regression on identical source. It never edits a threshold; a gate-MAD change
needs at least four identical-source runs on the canonical host (each left-out run then faces a
pool of three, the gate's minimum).

---

## 9. Artifact map

### On disk (gitignored)

| Path | Contents |
|------|----------|
| `QwenVoice-Debug/diagnostics/` | Per-layer telemetry JSONL, merged rows and verbose sample sidecars ([§6.2](#62-output-files)); `engine/generations.jsonl` holds the richest backend rows |
| `QwenVoice-Debug/outputs/bench/*.wav` | Bench WAV outputs (fixed per-cell filenames — overwritten across seeds) |
| `QwenVoice-Debug/outputs/bench-archive/<runID>/` | Durable per-run evidence for every `--delivery` run: all take WAVs plus `bench-results.json`, `bench-prosody.json`, `bench-quality-composed.json`. Fail-closed for required files, written before the sidecar analysis; unbounded, prune manually. Successful diagnostics run dirs are cleaned after publication, so multi-run scoring reads from this archive ([§4.6](#46-delivery--prosody-cells)) |
| `<run-artifact-dir>/benchmark-evidence.json` | Atomic run-scoped validator selection and verdict used for publication |
| `<run-artifact-dir>/playback-capture/` | Played-audio capture WAVs and sidecars ([§4.10](#410-macos-ui-benchmark-supplementary-integration-net)) |
| `build/**/*.xcresult`, screenshots | UI evidence retained locally under bounded lane retention |
| `build/**/profiles/` | Compact local profile summaries; a CPU profile's raw `*.trace` is success-ephemeral unless `--keep-trace` was explicit, a memory profile's is kept by default (prune manually) |

**Bounded by design.** Telemetry logs are append-only but size-capped and auto-pruned
(oldest-first) by `GenerationTelemetryJSONLSink`, so they can't blow out disk: each
`generations.jsonl` (incl. the merged file) is front-trimmed past ~8 MB
(`QWENVOICE_DIAGNOSTICS_MAX_MB` scales it), and verbose `samples-*.jsonl` sidecars keep only the
newest files. Ad-hoc diagnostics keep the newest 48 / ≤64 MiB. `vocello bench --telemetry verbose`
sizes the sidecar budget to its own plan before any model loads (one sidecar per planned
generation, delivery takes and TTFC probe included, at the same per-sidecar byte allowance) and
refuses a plan above 256 generations, so a full default matrix (58 takes) keeps every sidecar
publication needs (`GenerationTelemetrySidecarBudget`). No manual clearing is needed for logs.

### Committed (bounded)

| Path | Rule |
|------|------|
| `benchmarks/runs/` | One canonical allowlisted `<kind>/<run-id>.json` record per successful run, ≤ 256 KB; only `annotate` may update listening review |
| `benchmarks/HISTORY.md` | Generated registry index (`scripts/benchmark_history.py rebuild-index`, run by publication; `rebuild-index --check` runs in the contract gate); the generated-file guard hook refuses hand edits |
| `benchmarks/LEGACY_HISTORY.md` | Preserved incomplete manual history; never promoted to complete registry evidence |
| `benchmarks/hardware-profiles.json`, `schema-v3.json`, `schema-v2.json` (both published today), `schema-v1.json` (read-only) | Canonical hardware identities plus the record contracts |
| `benchmarks/baselines/mac-gate-bench.json` | The governed gate baseline ([§8](#baseline-comparison-json-machine-gated)) |
| `benchmarks/qc/eval-v*.json` | QC v2 threshold evaluations ([`qc.md`](qc.md)) |
| `benchmarks/OPTIMIZATION.md` | Historical optimization narrative |

**Never commit raw JSONL, WAVs, screenshots, result bundles, or traces** under `benchmarks/`; the
exporter's allowlist ([§8](#record-contents-and-privacy)) keeps identifiers and content out of
records.

### CI / automation

- `.github/workflows/ci.yml` — `ios-compile` job (generic device-SDK compile of `VocelloiOS` and the policy-test bundle; no UI, no bench, no device)
- `.github/workflows/release.yml` — deterministic signing and packaging; UI lanes remain explicit/local
- `scripts/check_project_inputs.sh` — validates all compact records and checks that `HISTORY.md` is reproducible
- Explicit frontend acceptance: `scripts/ui_test.sh macos smoke|benchmark`
- Deterministic macOS platform gate: `scripts/macos_test.sh gate` (does not consume UI results)

The engine regression net is a targeted local checkpoint lane; ordinary CI never runs a model, a
device or XCUITest.

---

## 10. Troubleshooting

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| Custom/Design "cold" shows `warm` | Proactive warmup ran | `QWENVOICE_SUPPRESS_WARMUP=1` for UI; CLI unloads explicitly |
| Clone missing from matrix | No enrolled voice | `scripts/macos_test.sh models ensure` |
| `preflightModels` fails Quality | Speed-only fixture | Install Quality weights or use `--variants speed` |
| Summarizer empty | Wrong diagnostics dir / gate off | Confirm `QWENVOICE_DEBUG=1`; check `engine/generations.jsonl` |
| RTF vs decode ms disagree | Different time bases + lazy MLX | RTF spans the whole request, decode ms the token loop; read [§6.8](#rtf-vs-decode-ms-read-together-dont-diff-naively) and [§7.3](#73-decode-breakdown-lazy-mlx); use a signpost trace |
| All QC warn:dropout on long | Often natural pauses | Run the fixed-seed exact-WAV cohort; inspect the punctuation-aware budget, ASR consensus, and prosody evidence |
| iOS bench timeout | Model missing / device diagnostics did not complete | `scripts/ios_device.sh console`; install Speed model |
| Clone cold row appears | Corrupt matrix ordering, generation map, or frozen evidence | **Hard failure:** inspect `bench-results.json` or the UI generation map plus `benchmark-evidence.json`, repair the producer/selection mismatch, and rerun. Never relabel or ignore a Clone cold row. |

---

## 11. Related documents

| Doc | Role |
|-----|------|
| [`cli.md`](cli.md) | Full `vocello bench` flag reference |
| [`macos-release-qa.md`](macos-release-qa.md) | Release gate sequence |
| [`macos-testing.md`](macos-testing.md) | UI test / profile / gate lanes |
| [`ios-device-testing.md`](ios-device-testing.md) | iOS bench, gate, device lanes |
| [`testing-runbook.md`](testing-runbook.md) | Shared lane policy |
| [`qc.md`](qc.md) | QC v2 harness, ASR families and audio-QC thresholds |
| [`qwen3-core-maintenance.md`](qwen3-core-maintenance.md) | Owned core runtime procedure and validation gates |
| [`privacy-storage.md`](privacy-storage.md) | Where diagnostics live; deletion paths |
| [`native-engineering.md`](native-engineering.md) | Telemetry summary + engine invariants (bounded measured event delivery, typed cancellation, prewarm reentrancy, per-tier memory) |
| [`qwen3-tts-guide.md` §7](qwen3-tts-guide.md#7-language-handling) | Language semantics |
| [`benchmarks/OPTIMIZATION.md`](../../benchmarks/OPTIMIZATION.md) | Historical optimization decision ledger (through 2026-08) |
| [`benchmarks/HISTORY.md`](../../benchmarks/HISTORY.md) | Generated benchmark registry index |
