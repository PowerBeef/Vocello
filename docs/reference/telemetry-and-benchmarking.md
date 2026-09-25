---
status: active
owner: release-qa
reviewed: 2026-09-12
summary: The single telemetry and benchmarking reference — per-generation typed telemetry across frontend/transport/backend, schema versions, knobs, artifacts, and how evidence stays cheap.
sourceOfTruth:
  - Sources/QwenVoiceCore/NativeTelemetrySampler.swift
  - scripts/benchmark_history.py
  - config/memory-qualification-policy.json
---
# Telemetry & benchmarking

How Vocello measures itself. This is the single reference for the per‑generation
telemetry that spans the **frontend (app UI)** and the **backend core (MLX / Qwen3‑TTS)**, both
in one process on macOS and iOS since 2026-09-15 — what
is measured, where it lands, how to read it, and how it stays cheap enough to run on
restricted hardware (8 GB Macs, iPhone) without distorting the numbers you optimize
against.

If anything here disagrees with the code, the code wins — fix this file.

> Scope note: this covers the runtime telemetry that is the **default** benchmarking path —
> drive a generation, then read the JSONL this system writes + aggregate with
> `summarize_generation_telemetry.py`. Benchmarking + output‑quality checks are **first‑class**:
> successful benchmark records, historical baselines, and generated indexes are permitted
> (bounded by the `benchmarks/` cap). Raw telemetry, audio, screenshots, traces, and result
> bundles remain untracked. XCUITest is the sole autonomous app UI driver; deterministic
> history/WAV/backend probes validate its smoke and benchmark results. iOS UI tests
> and real-engine generation remain **on-device only** on a paired physical iPhone. GitHub CI
> executes Foundation-level iOS policy assertions on the macOS host and remains compile-only for
> iOS binaries.
> See [`testing-runbook.md`](testing-runbook.md) and [`ios-device-testing.md`](ios-device-testing.md).

---

## 1. Principles

1. **Runtime‑gated, never compiled out.** There is one shippable config; dev and
   release run identical code (see root `CLAUDE.md`). Telemetry is switched on at
   runtime by `TelemetryGate`, not by `#if DEBUG`. When the gate is off, every probe
   is a no‑op and nothing is written.
2. **Correlated by `generationID`.** The app mints a `UUID` per generation and threads
   it down; the engine reuses it. Every layer keys its rows on that one ID so they join.
3. **Cheap on the hot path.** No per‑chunk file I/O, no per‑chunk allocations or
   MainActor hops added by telemetry. Per‑generation work happens at boundaries; the
   memory sampler runs on a background task at a device‑tiered cadence.
4. **Measure, don't perturb.** The fine‑grained backend timings read clocks around work
   that already happens (including the GPU syncs that generation requires); telemetry
   does not add synchronization. See [§9 Observer effect](#9-overhead--observer-effect).
5. **Select one run, never a directory history.** Benchmark validators emit an atomic
   `benchmark-evidence.json` with the exact ordered generation IDs and cells. Summaries and the
   tracked registry consume that manifest plus its run ID; unrelated historical rows are ignored.
6. **Process ownership stays explicit.** Memory and resource deltas remain on the process that
   measured them. macOS and iOS UI evidence require app + engine (records before 2026-09-15 also
   carried an engine-service layer). A partial merge is marked incomplete and cannot publish history.

---

## 2. Turning it on

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
host process's own environment; no handshake relays a mode. Telemetry opt-in is distinct from production-affecting overrides, which additionally
require the registered internal-diagnostics build capability and debug gate. Do not claim that
all telemetry code is compiled out of distributed binaries.

### Sampling modes (`NativeTelemetryMode`, in `SemanticTypes.swift`)

| Mode | `QWENVOICE_NATIVE_TELEMETRY_MODE` | Memory sampler | Raw per‑sample series |
|---|---|---|---|
| `off` | `off` / `disabled` | — | — |
| `lightweight` (default when gate on) | `lightweight` / `light` | device‑tiered cadence | no |
| `verbose` | `verbose` / `full` / `deep` | device‑tiered cadence | **yes** (sidecar) |

`NativeTelemetryWorkPlan` makes the off contract explicit: no recorder, sampler, sink,
per-chunk QC, or expensive derived diagnostics are constructed. The engine builds its stage
recorder only when the gate is on and the mode is not off, and writes engine rows, raw sample
sidecars, streaming v9 sidecars and the published-WAV digest only through the plan's `writesSink`.
`vocello bench --telemetry off` sets the off mode and latches it, so the off arm stays off although
its runtime overrides set `QWENVOICE_DEBUG=1`. The deterministic overhead lane verifies that
optimization and waveform parity, and fails if an off arm leaves any file under
`diagnostics/engine`; every arm's timings come from the CLI observer (`bench-results.json`):

```sh
scripts/macos_test.sh telemetry-overhead
```

This is a real generation lane with its own read-only model integrity check. It never invokes
`models ensure`, downloads weights, bootstraps a clone fixture, or depends on an XCUITest result.

It applies one fixed `vocello bench --seed` through three deterministic mode-order rotations.
Each rotation runs one warm-up and two measured Custom/Speed/medium takes per mode, yielding six
machine-readable takes per mode. PCM SHA-256 must match across off, lightweight, and verbose.
Median RTF and TTFC regression limits are 5% for lightweight and 10% for verbose. Raw evidence and
load/thermal context stay under `build/artifacts/macos/`. The verdict is deliberately local-only: the
`off` lane cannot supply mandatory v8 memory evidence without changing the observer-effect
experiment, so new tracked history publication fails closed. Existing schema-v1 overhead
records remain readable and memory-contract-incomplete.

Typical backend‑optimization invocation:

```sh
QWENVOICE_DEBUG=1 QWENVOICE_NATIVE_TELEMETRY_MODE=verbose ./scripts/build.sh run
```

### Related benchmark knobs (also propagated over the handshake)

`config/runtime-debug-knobs.json` owns this inventory. Production-affecting knobs are read through
`RuntimeDebugGate` and require both `VOCELLO_INTERNAL_DIAGNOSTICS` and `QWENVOICE_DEBUG=1`;
distributed builds omit the capability. Bounded observability and test-target-only keys are
separately classified. Generation telemetry binds active override key names and a digest of their
values without retaining raw launch input. Never add an undocumented environment reader.

| Env | Effect |
|---|---|
| `QWENVOICE_SUPPRESS_WARMUP=1` | Skips proactive prewarm/clone‑priming so the first generation records its own **cold** load (`MacGenerationWarmupCoordinator`). App‑process only. |
| `QWENVOICE_FORCE_MEMORY_CLASS=floor_8gb_mac` | Forces the device-memory tier (`NativeDeviceClassGate`), read in-process by the engine's host. Runs constrained-tier code paths for diagnostic comparison. See §11 "Memory and pressure interpretation". Accepts the `NativeDeviceMemoryClass` raw values + aliases `8gb`/`16gb`. |
| `QWENVOICE_SIMULATED_PHYSICAL_MEMORY_GB=8` | **Floor emulation on a larger Mac** (`NativeHostMemoryEmulation`, audit #11): the host reads as a Mac with that much RAM wherever policy reads the machine: `NativeMemoryPolicyResolver.deviceClass()` (so 8 resolves the floor tier and its policy), the store's footprint bands (`MacMemoryBudgetPolicy`: guarded at 55%, critical at 72% of the emulated RAM) and the snapshot's `totalDeviceRAMMB` and Metal working set (two thirds of the emulated RAM: 5,461 MB for 8 GB), so the GPU working-set ratio is judged against the floor's budget. Only a smaller Mac can be emulated. Rows stamp `notes.deviceClassForced=true`, `notes.simulatedPhysicalMemoryMB` and `notes.simulatedMetalWorkingSetMB`; records are exploratory. Policy and footprint only: see §11. |
| `QWENVOICE_BENCH_SEED_POLICY=cell-hash-v1` | **UI benchmark seed policy** (`BenchSeedPolicy`, audit #29): every generation samples with the seed of the benchmark cell it measures (the first eight bytes of SHA-256 of `vocello-ui-bench-seed-v1`, NUL, the cell ID such as `custom/short/warm#1`), replacing a draft's pinned seed; the cell comes from `QWENVOICE_BENCH_SEED_CELLS` (a comma-separated launch schedule consumed one per generation, the iPhone lane) or else the benchmark's current-take file (macOS). Rows stamp `notes.samplingSeedPolicy`; the lane checkers and the history validator recompute each take's seed (`scripts/lib/bench_seed.py`) and the record names `run.seedPolicy`. `scripts/ui_test.sh <platform> benchmark` sets it by default (`--seed-policy generated` keeps random seeds). |
| `QWENVOICE_MAC_WARM_GATE=off\|records\|enforce` | macOS warm‑admission gate (`MacWarmupAdmissionPolicy`): defers **proactive** warms while the app‑process kernel pressure level is soft/hardTrim on every Mac tier (the high‑memory Mac since AUD‑10). Default `enforce` (validated 2026‑06‑09); `records` logs verdicts without blocking; user generations are never gated. Events land in the app layer's `native-events.jsonl`. |
| `QVOICE_TALKER_KV_QUANT=8\|4` | **Dev-only** opt‑in talker KV‑cache quantization (QuantizedKVCache, group 64). Measured (P4, §H): clone/long −271 MB physFoot but **−8.6% RTF** — not shipped on any tier; insurance knob only. Never combined with `QVOICE_TALKER_KV_WINDOW`. |
| `QVOICE_IOS_MLX_CACHE_LIMIT_MB=<n>` | **Dev-only** override of the MLX `Memory.cacheLimit` for the iPhone tier. Useful for sweeps; production uses the tier default. |
| `QVOICE_IOS_MLX_MEMORY_LIMIT_MB=<n>` | **Dev-only / do not ship** override of MLX `Memory.memoryLimit`. Production avoids a hard `memoryLimit`; see `mlx-guide.md` §5.2. |
| `QVOICE_IOS_MEMORY_PROFILE=iphone15pro` | **Physical-device memory-profile diagnostic**: clamps the effective per-process limit inside `IOSMemorySnapshot.capture()` so bands/admission/clone-gate use the smaller-device budget (`iphone15pro` → 5,000 MB). Rows stamp `notes.memoryProfile` and `notes.simulatedProcessLimitMB`. GPU compute and thermals remain those of the connected device; this is not proof for a different device. See the canonical benchmark procedure for `--memory-profile`. |

---

## 3. Architecture

```
 App process (Vocello)                    Engine (same process on macOS and iOS)
 ┌───────────────────────────┐  IPC      ┌──────────────────────────────────────────┐
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
| `NativeTelemetryRecorder` | Per‑generation stage timeline (`mark(stage:)`). The generation telemetry session begins before model preparation and shares one clock across load, prewarm, synthesis, finalize, trim, cancellation, and failure. |
| `NativeTelemetrySampler` | Background memory/timing sampler → `TelemetrySummary` + raw `[TelemetrySample]`. |
| `GenerationTelemetryRecord` | One durable row per layer (`engine` / `app`; `engine-service` only in records before 2026-09-15). |
| `GenerationTelemetryJSONLSink` | Append‑only writer (gated); also the verbose raw‑sample sidecar. |
| `GenerationTelemetryMerger` (`Sources/Services/`, macOS) | Joins per‑layer rows → `generations-merged.jsonl`. |
| `AppGenerationTimeline` (`Sources/SharedSupport/Telemetry/`) | Frontend submit→firstChunk→playbackScheduled→completed plus bounded playback-health counters. |

---

## 4. Output files

Under `~/Library/Application Support/QwenVoice[-Debug]/diagnostics/` (the `-Debug`
folder when DebugMode is on, so real data is never polluted):

| File | Layer | Contents |
|---|---|---|
| `engine/generations.jsonl` | backend | The decode breakdown, KPIs, per‑stage MLX memory, per‑chunk timeline, stage marks, memory summary. **The richest source for backend work.** |
| `app/generations.jsonl` | frontend | Submit→first chunk→playback scheduled→completed, delayed-heartbeat coverage, and playback health. It does not claim acoustic audibility or inherit engine memory. |
| `generations-merged.jsonl` | merged | Layers joined per `generationID`, with explicit `requiredLayers`, `missingLayers`, and `complete`. |
| `engine/samples-*.jsonl` | backend (verbose only) | Raw per‑sample memory/timing series, one file per `generationID`. |
| `*/native-events.jsonl` | engine/middle/app | Chunk‑sequence gaps + encode drops; the **app** file also carries `mac_warm_admission_observed` / `mac_warm_blocked` (warm‑admission gate) and `engine_service_retired` (XPC retirement) events. **Written only when telemetry is enabled** (`TelemetryGate.resolvedEnabled` / app-process intended mode). |
| `<documents>/generation-failures.jsonl` | debug | Append-only failure log when telemetry is on (see `GenerationFailureDiagnosticLogger`). |

One JSON object per line. The field-reading order is in [§10](#10-reading-telemetry).

**Bounded by design.** These are append‑only but **size‑capped + auto‑pruned** (oldest‑first) by
`GenerationTelemetryJSONLSink`, so logs can't blow out disk: each `generations.jsonl` (incl. the merged
file) is front‑trimmed past ~8 MB (`QWENVOICE_DIAGNOSTICS_MAX_MB` scales it), and verbose
`samples-*.jsonl` sidecars keep only the newest files. Ad‑hoc diagnostics keep the newest 48 / ≤64 MiB;
`vocello bench --telemetry verbose` sizes the budget to its own plan instead (one sidecar per planned
generation, the same per‑sidecar byte allowance) and refuses a plan above 256 generations
(`GenerationTelemetrySidecarBudget`; see [`benchmarking-procedure.md`](benchmarking-procedure.md#9-artifact-map)).
No manual clearing needed for logs.

---

## 5. The per‑generation record schema

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
> without the label (audit #49/#62). History may bind those sidecar digests; the
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
| `usedStreaming` | Bool? | Streaming vs quality‑first. |
| `finishReason` | String? | Typed terminal reason: `eos` / `maxTokens` / `cancelled` / `failed` / `completed` / `superseded` / `unknown`. Compatibility input also accepts `max_tokens` and `canceled`; v7 typed payloads encode the canonical values. |
| `stageMarks` | `[{tMS, tNS?, sequence?, stage, metadata}]` | Lifecycle timeline with optional nanosecond timestamps and monotonic sequence numbers (see §6). |
| `frontendMetrics` | `FrontendGenerationMetrics?` | Typed submit/first-chunk/playback-scheduled/completed, delayed-heartbeat coverage, and bounded playback queue/continuity/underrun metrics. Legacy `*Audible*` keys decode as compatibility aliases only. |
| `transportMetrics` | `EngineTransportMetrics?` | Typed request-to-first-chunk timing, terminal/cancellation/lifecycle, opaque session identity, first/last sequence, and forwarded/gap/duplicate/reordered counters. |
| `backendMetrics` | `BackendGenerationMetrics?` | Typed lifecycle stages, warm/streaming state, finish reason, timing/counter enums, and final-chunk barrier. |
| `outputMetrics` | `GenerationOutputMetrics?` | Duration, readable-WAV verdict, atomic-publication verdict, and audio QC. |
| `timingsMS` / `counters` | compatibility maps | Generated compatibility output for existing summarizers and old rows; new validators consume typed payloads. |
| `derivedMetrics` | `[String: Double]?` | Headline KPIs (see §7). Includes `kvCacheEstimatedPeakMB` (2026‑07‑01, audit P1‑2) — the peak of the per‑chunk KV‑cache footprint estimates, surfaced at row level so regression tooling doesn't walk the chunk timeline. |
| `mlxMemoryByStage` | `[String: {activeMB, cacheMB, peakMB}]?` | MLX GPU memory at each stage (see §8). |
| `chunkTimeline` | `[GenerationChunkTelemetry]?` | Per‑chunk decode substages, with `arrivalNS` (v5) and optional `mimiDecoderBreakdownMS` (v5) (see §6.3). |
| `audioQC` | `AudioQCReport?` | Versioned reference‑free overall, model-instability, and written-output verdicts plus flags, defect offsets, and optional per‑chunk QC. Algorithm v6 (`makeAudioQCReport`) judges the atomically published WAV frames and, since 2026-09-12, also asserts the file's sample rate, channel count and frame count against the request. |
| `summary` | `TelemetrySummary?` | Owning-process resident/physical-footprint/compressed/headroom/Metal start, end, delta, peak/min and aligned extrema snapshots; total RAM and implied process limit; independent memory/thread/headroom/Metal coverage; sampler cadence/boundaries; and process CPU/page-fault/context-switch/block-I/O deltas. `timeToPeakMS` tracks the physical-footprint peak. |
| `streamingTelemetryV9` | `GenerationStreamingTelemetryTransitionV9?` | Nested partial v9 transition projection carried by new schema-v8 rows. Invalid generation IDs may omit it; otherwise missing producer domains are explicit `unavailable` entries and never inferred as zero. It is not a publishable schema-v9 envelope. |
| `notes` | `[String: String]` | Bounded compatibility metadata such as `deviceClass`, `promptChars`, privacy-safe `promptDigest` (script text only — never the delivery instruction), the bench `delivery` cell stamp, the delivery-instruction receipt `instructChars`/`instructDigest` on instructed takes (verified fail-closed by the delivery harness; [`delivery-harness.md`](delivery-harness.md) §4), and memory pressure. Raw script, transcript, voice description, file path, and failure message are forbidden; prompts/failures/instructions use SHA-256 identity rather than content. |
| `recordedAt` / `processName` / `processIdentifier` | | Provenance. |

`MergedGenerationTelemetry` is schema v2. A macOS UI record requires `.app`,
`.engineService`, and `.engine`; an iOS UI validator requires app and engine rows from the same
run/generation. The `complete` flag and `missingLayers` list prevent a timed-out partial merge from
appearing authoritative.

---

## 6. Backend (MLX) timing — the optimization data

### 6.0 os_signpost interval mirrors (`timingsMS`)

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
(`withMirroredSignpost`, which could not carry them) was removed on 2026-09-25. The
macOS CLI bench also publishes `ttfcObserverLagMS`, the part of `ttfcMS` its own
first-chunk observer adds after the engine handed chunk 0 to the product sink.

### 6.1 Stage timeline (`stageMarks`)

Coarse milestones for one generation, in ms from generation start (the recorder and the
memory sampler **share one high‑resolution `NativeTelemetryClock`**, so marks and samples
align on both ms and ns timelines). The session exists before model preparation and finishes
exactly once on success, cancellation, or failure. Each mark carries `tMS`, optional `tNS`
(nanoseconds since start), and a monotonic `sequence` number. Readers order by nanoseconds and use
sequence only to break ties. `metadata` values are
typed (`string`/`int`/`double`/`bool`) in v5, while remaining JSON‑serializable.
Stages (`NativeRuntimeStage`): `preparedCacheValidation`, `preparedCacheRebuild`,
`tokenizerPreparation`, `upstreamModelLoad`, `prewarm`, `clonePreparation`, `streamStartup`,
`firstChunk`, `streamGenerationEnded`, `streamCompleted` / `streamFailed`, `unload`.
`streamGenerationEnded` closes the model/decode span before final WAV publication, while
`streamCompleted` is the successful terminal lifecycle mark. Load/prewarm marks appear only on a **cold**
run (warm runs skip that work — that's correct, not missing data). Two additional
string‑keyed marks record memory events on every tier: `memory_pressure` and
`memory_trim` (see §8).

### 6.2 Decode breakdown (`timingsMS`)

The engine re‑reads the model's diagnostics **after** the decode loop (the MLX hot‑loop
totals are only finalized post‑loop), so `timingsMS` carries the per‑substage wall‑clock
breakdown of where decode time actually went, accumulated across the whole generation.
The MLX layer owns these keys; the set is mode‑dependent — **inspect a real row for the
authoritative list.** Representative keys (prefix `qwen_…`):

| Key (representative) | Meaning |
|---|---|
| `qwen_talker_forward_total` | LLM talker forward pass, summed over tokens. |
| `qwen_code_predictor_total` | Multi‑codebook code‑predictor loop. |
| `qwen_stream_decoder_total` | Streaming audio decoder (codec → waveform). |
| `qwen_stream_step_eval_total` | `eval(...)` flush after each forward step (GPU dispatch; under the default `.pipelined` policy only the `asyncEval` enqueue). |
| `qwen_stream_step_token_read_total` | The step's first blocking read, the sampled token: under `.pipelined` the host's wait for the step's GPU work (signpost `Token Read`). |
| `qwen_stream_step_eval_wait_total` | The observed step wait: equals the token read under `.pipelined`; 0 under synchronous policies, whose wait stays inside the eval call, and under `.deferred`, whose token read itself dispatches and waits for the work the token depends on. The v9 sidecar's derived `mlxMaterializationDurationNS` counts back this wait; rows and sidecars with that meaning carry output-adapter identity version 2 or later (3 labels the derived instants). |
| `qwen_stream_step_eos_read_total` | EOS‑flag readback (a GPU sync). |
| `qwen_audio_chunk_eval_total` | Audio‑chunk evals: the assembly `asyncEval`, the pipelined flush (signpost `Audio Chunk Flush`) and the tail chunk. |
| `qwen_token_loop_total` | Whole per‑token loop wall time. |
| `qwen_tail_decode_total` | The work after the loop: the final pipelined flush, `.info`, and the tail chunk's decode, eval and sends (or quality-first's full decode). Rows since 2026-09-25 (audit #60); no loop key covers it. |
| `qwen_token_loop_unattributed` | In‑loop time no named substage covers (slack to chase), read when the loop exits so the tail work after it cannot hide it. It still contains the sink hand-offs below. |
| `qwen_token_loop_sink_handoff_total` / `_count` | The awaited materialized-sink hand-offs inside the token loop (`.token`, `.codecFrame`, `.chunkTimings`, `.audio`, the pipelined flush's sends and the codec-trace sink); the final flush, `.info` and tail chunk after the loop are not counted (audit #61, 2026-09-25). A part of `qwen_token_loop_unattributed`, never subtracted from it. |
| `qwen_generated_code_count` | Tokens generated (counter). |
| `qwen_stream_decoder_calls` | Streaming chunk decode count. |
| prep / prewarm keys | `*_prefix_tokenize_ms`, `*_prefix_embed_build_ms`, `decoder_bucket_warm`, `*_prewarm_eval_ms`, … |

Use the breakdown to see which substage dominates (talker vs code‑predictor vs decoder)
and how much loop time is `unattributed` (candidate for new sub‑probes). The engine sums
each span unrounded and rounds a total once at export (audit #61), and every span has a
same‑named `os_signpost` interval (subsystem `com.qwenvoice.engine.qwen3`) opened and
closed around the same code, so a profile's per‑take interval sums line up with these keys.

### 6.3 Per‑chunk timeline (`chunkTimeline`, streaming only)

One entry per emitted audio chunk — the decode substage deltas that produced it, plus its
wall‑clock arrival. Mirrors the owned runtime's `ChunkSubstageTimings`:
`talkerForwardMS`, `codePredictorMS`, `audioDecoderMS`, `streamStepEvalMS`,
`streamStepEOSReadMS`, `audioChunkEvalMS`, plus `chunkIndex`, `arrivalMS`, and in v5
`arrivalNS` (nanosecond resolution from `NativeTelemetryClock`). In v5 verbose mode,
`mimiDecoderBreakdownMS` further splits the chunk decode into `quantizer`, `transformer`,
`upsample`, `seanet`, and `output` (coarse stage clocks around the Mimi decoder). This
exposes **cold‑start vs steady‑state** behavior and localizes stalls to a substage and a
chunk. Captured cheaply (a small struct appended per chunk, only when telemetry is on) and
written once at generation end.

---

## 7. Derived KPIs (`derivedMetrics`)

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
declaration and keep their keys.

Frontend latency is the app row's `submitToFirstChunkMS` and
`submitToPlaybackScheduledMS`. The latter means the player was commanded with a bounded queued
buffer; it is **not** proof that acoustic output was audible. The engine row's `firstChunk` mark is
backend-only, while the macOS transport row's `requestToFirstChunkMS` begins at request acceptance.

**Played-audio capture (PC-01, macOS benchmark lane).** The XCUITest runner taps the app's own audio
output during one take per cell (since 2026-09-25, audit #31: the last warm repetition of each mode
and length that does not start an app session; other takes carry no capture fields) (a Core Audio
process tap with the physical output muted), writes
`take-NN-<cell>.wav` plus a sidecar under `<run>/playback-capture/`, and
`scripts/lib/playback_capture.py` compares the capture with the published take WAV. The take then
carries `playbackCaptureStatus` (`captured`, `silent`, `unavailable`, `referenceUnresolved`,
`aborted`), `playbackCaptureDigest` and, when captured, `playbackCaptureFirstAudibleMS` (submit →
first frame above −50 dBFS; the submit reference is the app row's own wall-clock stamp
`timingsMS.submittedAtEpochMS` when present, else the runner's click stamp, which precedes the
app's submit by the UI driver's dispatch latency; the capture's first sample is the first buffer
the tap delivered, which arrives only once the app's output device runs; the capture
`summary.json` records `clickToSubmitMS` per take),
`playbackCaptureAlignmentMS` (where the published WAV starts inside the capture, a lead-in, not a
fault),
`playbackCaptureResidualDBFS` (after gain match), `playbackCaptureDropoutCount` /
`playbackCaptureMaxGapMS` (20 ms frames where the file speaks above −40 dBFS and the capture
collapses by more than 25 dB), `playbackCaptureCoverage` and `playbackCaptureStepBurstPeakCount`.
Anomalies are warn-only codes on the take (`playback.capture.misaligned` when the audible first
frame and the app's own `playbackScheduledMS` disagree by more than 250 ms either way — the app's
timeline stops at scheduling, the tap hears the result; the first captured takes put the audible
onset about 1.8 s after scheduling on final-file playback —
`.dropouts`, `.low_coverage` below 0.95, `.high_residual` above −20 dBFS, `.silent`). Since
2026-09-14 (PC-02) a **captured** take also fails the lane when it breaks the gate set from the first
three canonical captured runs (87 takes): coverage below 0.98, residual above −25 dBFS, any
dropout, or an audible onset more than 500 ms from `playbackScheduledMS`; unavailable, silent and
unresolved captures stay warnings so an ungranted host still passes. The macOS smoke lane captures
its completed-generation take too; `scripts/analyze_playback_capture.py` writes its `summary.json`
(advisory there).

### RTF vs `decode ms` (read together, don't diff naively)

The summarizer prints **RTF** (`derivedMetrics.realTimeFactor`, request wall ÷ audio), **xRT**
(`audioSecondsPerWallSecond`, the decode-loop speedup) and **decode ms** from
`timingsMS.qwen_token_loop_total`. xRT and decode ms share the token-loop wall clock when
`qwen_token_loop_total` is present; RTF spans the whole request, so it is always the slower-looking
of the two figures.

Caveats that still apply:

- **Lazy MLX** — substage columns (`talkerForward`, `codePredictor`, `streamStepEval`, Mimi
  decoder) measure Swift wall time around lazy graph ops; they sum to less than
  `qwen_token_loop_total` when work is pipelined across iterations.
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
gates; use **decode breakdown + chunk timeline** for
where time goes; use **Instruments signposts** (see [`benchmarking-procedure.md`](benchmarking-procedure.md)
§4.8) for GPU attribution.

---

## 8. Memory probes

- **`mlxMemoryByStage`** — MLX GPU `active`/`cache`/`peak` MB captured at stage boundaries
  (`before_stream`, `first_chunk`, `after_stream`, `after_final_write`,
  `after_generation_trim`, `before_marking`/`after_marking` when marking runs, plus
  prepare/clone/prewarm stages). `peak` is cumulative since the request began, so a stage raised
  the request's high-water mark exactly when its peak exceeds the previous stage's. Both marking
  snapshots follow the cache release that precedes the marking pass, so the take's
  `mlxCachePeakMB` keeps excluding the end-of-generation cache. Shows GPU memory growth
  across the pipeline — key for restricted‑hardware tuning. Captured at boundaries only
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
  shorter than the 500 ms constrained-device tick: in committed records 2,035 of 3,634 takes sampled
  a Metal peak below the exact `mlxPeakMB` (the MLX allocator's own per-request high-water mark),
  by a median of about 120-460 MB per record kind. Treat sampled peaks as lower bounds and
  `mlxPeakMB` as the exact MLX figure. `benchmark_history.py validate` and `record` warn (without
  failing) when a take's `peakGPUAllocatedMB` is below its `mlxPeakMB`, and `benchmark_history.py
  peak-miss-report [--json]` reports the count for every committed record without rewriting any.
- **Verbose raw series** — `verbose` mode writes every sample (`tMS`, `scheduledElapsedNS`,
  `capturedElapsedNS`, absolute `capturedUptimeNS`, `latenessNS`, `kind`, `boundary`,
  `processRole`, resident/physical-footprint/compressed/headroom/Metal values, total RAM, implied
  process limit, the kernel ledgers read in the same `task_vm_info` call
  (`kernelPhysFootprintPeakMB`, `graphicsFootprintMB`; absent when the kernel did not fill them),
  and separate `memoryCaptureSucceeded`, `threadCaptureSucceeded`,
  `headroomCaptureSucceeded`, and `metalCaptureSucceeded` flags) to the exact
  `<layer>/samples-<generationID>.jsonl` sidecar. Raw rows remain untracked.
  Off by default (higher volume).
- **Kernel memory‑pressure marks** (in `stageMarks`) — on every tier, where
  `NativeMemoryPressureMonitor` runs:
  - `memory_pressure` — the **raw kernel signal** (`metadata.level` = `softTrim`/`hardTrim`),
    stamped by `NativeEngineRuntime.recordMemoryPressureObserved` the instant the
    `DispatchSource` event arrives. Always recorded — it takes no prewarm slot.
  - `memory_trim` — the **trim action** taken in response (`metadata.level` + `reason`, e.g.
    `macos_memory_pressure_hardTrim`). Written by
    `NativeEngineRuntime.trimMemory`; skipped if the prewarm slot is contended, hence the
    separate always‑on `memory_pressure` mark above.

  A run with a `hardTrim` mid‑generation is shedding model state under pressure — an early
  OOM signal. Every tier starts the monitor (the high‑memory Mac since AUD‑10), so absent
  marks mean the kernel reported no pressure, not missing data. `headroom*` summary fields populate on
  iOS only (`os_proc_available_memory`); on macOS they're nil and `phys_footprint` is the
  OOM‑relevant figure to watch.

### Publication-grade memory qualification

Benchmark-evidence manifest v2 binds `memoryContractVersion: 2` (since 2026-09-25), `memoryQualified:
true`, the exact selected sidecar count/digest, and each take's `memoryStatus` plus sidecar digest. A
sidecar must start/stop exactly once, have monotonic elapsed/uptime clocks, match all summary counts
and report zero memory-capture failures. Engine evidence includes
preparation/model-load/session/final-WAV and first-output/terminal boundaries; app evidence includes
`app_submit` and `app_terminal`.

Contract v2 judges each take's one memory series. Timer health: no gap between two consecutive
samples (`samplerMaximumUnobservedGapMS`) may exceed the bound in
`config/memory-qualification-policy.json` `unobservedGapBound`, max(twice the sampler's target
interval, 500 ms); a longer gap fails publication, and each take records the bound it met as
`samplerUnobservedGapLimitMS`. The bound is provisional until the first consented memory lane on the
canonical M6 (250 ms cadence) calibrates it. Periodic coverage (`samplerCoverage`,
`samplerMissedDeadlineCount`) is still published but no longer gates, because it counts deadlines
honoured rather than whether the peak was seen. Peak fidelity: `gpuPeakCaptureMissMB` is how far the sampled Metal peak fell below the exact
`mlxPeakMB` (0 when it caught it). When the sampler read the kernel ledgers (samplers since
2026-09-25, from the same `task_vm_info` call), `kernelPhysFootprintPeakMB` is the process-lifetime
footprint high-water mark at the take's end: `kernelPhysFootprintPeakExact` is 1 when it rose inside
the take, so it is the take's exact peak and `footprintPeakCaptureMissMB` is the sampled peak's
shortfall, and 0 when it is only an upper bound set earlier in the process; `graphicsFootprintEndMB`
is the graphics-tagged footprint at the take's end. A ledger peak below a sampled footprint is a
broken read and fails publication; a miss is reported, never failed. Records before 2026-09-25 are
contract v1: they required at least 95% periodic coverage (95–<100% was warning evidence), and they
keep that meaning. The contract version joins the comparison key from v2 on, so a v2 series never
shares a lineage with a v1 aggregate.

Critical pressure, `application_memory_warning`, a memory exit, `hardTrim`, or `fullUnload` fails
publication. Guarded pressure or `softTrim` is `passedWithWarnings`, except the routine per-tier
cache clear (source `post-generation`, reason `post_generation_cache_clear`): since 2026-09-25 it is
counted as `policyCacheClearCount` with no pressure level and no warning. iOS additionally fails at
physical footprint ≥5,200 MiB, minimum headroom <384 MiB, or Metal working-set ratio ≥0.8; footprint
≥4,500 MiB or headroom <768 MiB is a warning. These are the app's shipping budget bands, declared
once in `config/ios-memory-budget-policy.json` (a Swift test pins `IOSMemoryBudgetPolicy` to it). The iOS record retains start/end/min headroom and peak
process-budget utilization. One process has one memory series: the macOS app hosts the engine, so
its app-layer and engine-layer samplers are two readers of that one process. A macOS UI take's
series is the union of both layers' samples in absolute-uptime order (a duplicate uptime counted
once), spanning the app's submit-to-terminal window; its values are never summed, and both rows must
name the same process ID. The app sidecar contributes its samples, its coverage and its
submit/terminal order. Contract-v1 macOS UI records (2026-09-15 to 2026-09-25) summed uptime-paired
app and engine samples of that one process and so report about twice its memory; they are not
rewritten. Headless CLI/profile evidence reports only its owning engine process.

The separate `memory` commands run policy `retained-memory-v1`: fixed Custom→Design→Clone
Speed/medium sequences with three retained takes per mode. Within each mode, first-to-last retained
physical-footprint growth must remain ≤5% of physical RAM. Intentional cross-mode model residency is
diagnostic unless a future runner proves an explicit full unload. These PASS-only runs publish the
`memory-qualification` kind; `profile --kind memory` remains the distinct Allocations + VM Tracker
Instruments lane.

Since 2026-09-25 the same run also reports policy `retained-memory-v2`
(`config/memory-qualification-policy.json` `retainedMemoryV2`; `evidence.retainedMemoryV2` on the
record). v1's bound is 5% of the canonical host's RAM, first retained take to the highest later one,
so a leak of up to about 410 MB per take passes on the canonical 16 GB M6 (819 MB over two takes;
307 MB per take on the 12 GB iPhone), and on a tier without the post-generation cache clear its end
value includes the MLX cache. Each take now publishes `mlxEndActiveMB`/`mlxEndCacheMB` from the MLX
snapshot after that clear (else after the stream) and, when sampled, `graphicsFootprintEndMB`; v2's
metric is each mode's growth of `mlxEndActiveMB` from the first retained take to the highest later
one. It gates per mode only against a bound calibrated from a consented memory run on the platform's
canonical host. Until a maintainer records that bound and its run ID, both platforms are
`uncalibrated`: the record reports the growth with no bound and no verdict, and v1 alone decides
publication.

On iOS, MetricKit's delayed daily aggregate is a complementary field signal. The app persists only
a bounded privacy-reduced memory/exit summary; raw payload JSON, call stacks, identifiers, and paths
are not retained for this purpose. After an explicit device pull,
`scripts/ios_device.sh memory-field-report [pulled-diagnostics]` reads local files only. It does not
contact the phone, does not publish benchmark history, and reports `notYetDelivered` nonfatally when
MetricKit has not delivered a payload. Each lane pull copies the same rolling document, so the report
counts one record per (kind, interval start, interval end), keeps the newest document's copy and
reports the rest as `duplicateRecordCount`. Daily values are not run-correlated and cannot qualify or
retroactively fail an individual take.

### Frontend responsiveness and playback health

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
The macOS UI benchmark judges this statistic under `config/macos-ui-stall-gate.json`: while the
contract is `provisional` it only reports (the run publishes, with the run warning
`stall.provisional.wouldfail(<above>/<gated>)` when a take exceeds the limit); once it is
`calibrated` with its calibrating run IDs, a take above the limit fails the run.

App telemetry also records bounded playback health: chunks received, continuity failures,
underruns, queued chunks/audio at playback scheduling, and minimum queue duration. This makes UI
benchmarks sensitive to streaming health while keeping raw audio and user content out of telemetry.

---

## 9. Overhead & observer effect

Designed so the numbers you optimize against are trustworthy.

- **Gated to zero when off.** No recorder, no sampler, no writes; per‑chunk capture is
  guarded by `telemetryRecorder != nil`.
- **Device‑tiered sampler cadence** (`NativeTelemetryMode.sampleIntervalMS(for:)`): high‑memory
  Mac 100 ms, 16 GB Mac 250 ms, **8 GB Mac / iPhone 500 ms** — the background sampler never
  competes with generation on constrained devices.
- **Cadence is measured, not assumed.** Periodic samples retain scheduled and captured elapsed
  nanoseconds plus lateness. The summary reports effective/maximum interval, maximum drift,
  boundary count, and capture failures; the old duplicate elapsed timestamp remains decode-only
  compatibility data.
- **Per‑sample cost reduced.** The Metal device is resolved **once per generation** and
  reused (`IOSMemorySnapshot.capture` would otherwise allocate a fresh `MTLCreateSystemDefaultDevice()`
  every tick). A sample is a few `task_info`/mach calls + one cached‑device GPU read.
- **No hot‑path additions.** Writes happen at generation boundaries; the per‑chunk timeline
  is an in‑memory append, persisted once at the end; the engine‑service transport row is
  flushed off the publish loop. The bounded macOS chunk stream is drained continuously and never
  blocked by file I/O; `GenerationEventDeliveryProbe` reports any dropped yield.
- **The backend timing reads do not add GPU syncs.** The `eval`/EOS‑read syncs that
  `qwen_stream_step_*` measure are required by generation itself — telemetry times existing
  work. Signposts are near‑zero when Instruments isn't attached.

Rule of thumb: compare like with like. A `verbose` run on an 8 GB Mac adds a 500 ms
sampler + a sidecar write; for the tightest latency numbers use `lightweight` and read
`derivedMetrics` + `timingsMS`.

---

## 10. Reading telemetry

The canonical benchmark procedure owns launch configuration, matrix execution, and diagnostics-path
selection. For authoritative output, call `summarize_generation_telemetry.py` with both
`--run-id` and `--evidence-manifest`; the manifest's ordered generation IDs prevent historical rows
from leaking into the current summary. The summarizer merges the app and engine layers by
`generationID`; CLI rows have only the engine boundary. Read `finishReason` and
`audioQC` before interpreting performance, keep cold and warm populations separate, and compare
`derivedMetrics.realTimeFactor` (and the decode speedup `audioSecondsPerWallSecond`) with the dominant `timingsMS` substage. A cold Custom or
Design row should include `upstreamModelLoad` in `stageMarks`; an immediately repeated row should be
warm. See [`benchmarking-procedure.md`](benchmarking-procedure.md) for supported invocations.

---

## 11. Benchmark result interpretation

This document is the telemetry schema and interpretation reference. The sole operational source for
benchmark preflight, model and clone-fixture preparation, exact matrices, commands, UI lanes,
artifact handling, and troubleshooting is
[`benchmarking-procedure.md`](benchmarking-procedure.md). In particular, do not derive a Clone
fixture from a Built-in Voice output: the canonical fixture is generated through Voice Design and its
provenance is verified by the repository model-preparation helper.

Each engine row identifies its cell through `mode`, variant-specific `modelID`, and `warmState`.
Custom and Design can produce genuine cold rows; Clone is normally warm because reference
conditioning primes the model. Interpret a missing Clone cold row as expected unless the canonical
procedure explicitly changes that contract.

The summarizer is streaming (it walks JSONL once with `iter_jsonl`, maintains a lightweight
app index, and aggregates with `CellAccumulator`) so it handles large verbose logs without
loading them into memory. Prints a `mode × model × cold/warm` table (median over warm): RTF (wall ÷ audio), xRT (decode speedup), tokens/s, TTFC, decode‑loop ms,
peak GPU / RSS MB, **`physFoot`** (phys_footprint peak — the Jetsam‑relevant OOM figure),
**`headMin`** (min available headroom; iOS‑only, `-` on macOS), and **`trims`** (median
`memory_trim` count for the cell, annotated with the worst level — `soft`/`hard`/`full`; derived
from `stageMarks`, no new record field). A header line shows the **tier** each row ran under (from
`notes.deviceClass`) and flags a forced tier. A second block — **GPU MB by stage** (`load → stream
→ peak → trim`, from `mlxMemoryByStage`) — shows *where* GPU memory grows across the pipeline and how
much the post‑generation trim reclaims. A third block — **Decode breakdown** (`talker · sampCB0 ·
codePred · code2wav · stepEval · other`, from the `timingsMS` sub‑keys; named + other ≈ decode ms) —
splits the decode loop. ⚠ These are Swift‑side wall‑clock timers around **lazy** MLX ops, not per‑stage
GPU compute: `talker`/`codePred` measure graph‑*build* time, the single per‑frame `eval()` makes
`stepEval` the *fused* compute of Talker+CodePredictor+sampling, and `code2wav`≈0 because the decoder is
`asyncEval`'d (Phase 2c) and overlaps the token loop (pipelined, not free). To attribute compute per
stage, capture the os_signpost intervals under Instruments `xctrace`. Read‑only; joins `engine/` +
`app/` rows by `generationID`.
New benchmark history is one allowlisted JSON record per successful run under
`benchmarks/runs/` (one directory per kind, ≤256 KB per record), with a generated `HISTORY.md` index. Existing Markdown/JSON
baselines remain reference artifacts; they are not silently upgraded into complete records.
Schema-v1 history remains readable; new records publish as schema v3 when every take carries the
quality-registry identity and as schema v2 otherwise (`ui-perf` records are v2), and memory-qualified (v2+)
records are never mixed into memory trends with v1. Raw telemetry, audio, screenshots, result bundles, and traces remain untracked. A successful
profile record captures the original trace digest/path, capture settings, extracted summary, and
retention policy; a CPU profile's raw trace is discarded after publication unless `--keep-trace` was
explicit, and a memory profile keeps its trace by default (`keptByDefault`). Registry
validation is deterministic CI work, but model/device/UI execution is not an ordinary CI or
packaging gate.

### Memory and pressure interpretation

RAM usage (physFoot/RSS/peak‑GPU + the per‑stage GPU block) is captured on **every** run. The
**memory‑pressure** signals (`trims`/`pressure`) fire on every tier, but `deviceClass()` is derived
from real RAM and a high‑memory dev Mac rarely reaches kernel pressure — so there they usually
read `0`.

`QWENVOICE_FORCE_MEMORY_CLASS` (accepts `floor_8gb_mac`/`mid_16gb_mac`/`high_memory_mac`/`iphone_pro`,
or aliases `8gb`/`16gb`/`high`/`iphone`) is read in-process by whichever host runs the engine (the
app or `vocello bench --force-class`).
When selected by the canonical diagnostic procedure, it makes the engine run the floor-tier code
paths: caches are tight, single‑gen clears fire, and idle‑unload is short and shortens further
under pressure. Every engine row stamps
`notes.deviceClass`, so the summarizer header shows `tier: floor_8gb_mac ⚠ forced` — never mistake a
forced run for native‑tier data.

Pressure-triggered trims appear as `memory_pressure` and `memory_trim` stage marks. Interpret them
together with `physFoot`, the GPU-by-stage block, and the recorded device class; a forced class is
diagnostic evidence, not proof for that physical device.

**The 8 GB floor after the M6 became canonical (audit #11, option b).** The canonical host is the
Mac mini M6 16 GB; the 8 GB Mac stays the support floor, and the M2 history stays its only timing and
pressure evidence. On the M6 the floor is emulated: `QWENVOICE_SIMULATED_PHYSICAL_MEMORY_GB=8` makes the
host read as an 8 GB Mac wherever policy reads the machine, so the tier resolves to `floor_8gb_mac` (a
forced class alone would keep the M6's bands and working set), the store's footprint bands are the
floor's (guarded at 55%, critical at 72% of 8 GiB) and the snapshot reports 8,192 MB of RAM and a
5,461 MB Metal working set, so `gpuWorkingSetUsageRatioPeak` judges the floor's budget. The band paths
reuse `QVOICE_IOS_MEMORY_GUARD_FORCE_BAND=guarded` and `QVOICE_IOS_MEMORY_GUARD_FORCE_CRITICAL_ONCE=1`
(the Mac hosts the same store). Emulated rows stamp `deviceClassForced=true` and
`simulatedPhysicalMemoryMB`, and their records are exploratory, never canonical, never a baseline and
never comparable with real-hardware records: the engine or macOS UI benchmark record's
`run.runtimePolicy` carries `simulatedPhysicalMemoryMB` beside the forced floor tier. Lineage contract 2
keys them apart from the M6's own records (contract-1 and legacy records keep their stored keys), and
HISTORY names the emulation in their classification. The procedure is in the benchmarking procedure, §4.4.

The claims are limited to **policy and footprint**: the floor tier's policy values (256 MB MLX cache,
the per-generation clear, the 0.6 s streaming interval, the skipped dedicated custom prewarm, the
2-minute idle unload, one clone cache slot), the footprint each take reaches against the floor's bands,
and the Metal allocations against its working set. The kernel still has 16 GB: no kernel memory
pressure, compression, swap or real Metal budget of an 8 GB Mac is reproduced, and timings on the M6
say nothing about the floor's speed. A pressure balloon that would reproduce pressure needs its own
quiet-host exemption and is not part of this path.

> **Caveat:** on the forced floor tier, a Quality load that cannot fit will surface as an error rather
> than silently falling back to Speed. The row's `modelID` reveals the actual variant served — check it
> before attributing a Quality cell. The forced tier changes real behavior **only while the env is set**;
> unset it for normal use.

**Watch for OOM regressions** when optimizing the backend: a rising `physFoot` peak, GPU‑stage peak,
or any `hardTrim` in `trims` means a run is shedding model state under pressure — the early OOM signal.

**Verify attribution:** for Built-in Voice and Voice Design, each accepted cold row must show
`warmState":"cold"` and carry `upstreamModelLoad`; warm rows show `"warm"`. Clone rows are normally
warm by design.

### Tracking performance over time

Each successful publishable runner creates one canonical, privacy-safe record (schema v3 when every take
carries the quality-registry identity, schema v2 otherwise) under one of seven kinds: UI generation, engine generation, language, instrument profile, retained-memory
qualification, prosody calibration, or UI frame health (`ui-perf`, from the macOS and iOS perf lanes). `scripts/benchmark_history.py` validates these records and regenerates
`benchmarks/HISTORY.md`; direct Markdown append is unsupported. A strict allowlist rejects
identifiers and content that could expose serials, UDIDs/ECIDs, host/device/user names, absolute
paths, prompts/transcripts/voice descriptions, raw errors, email addresses, URLs, or secrets. Run
labels are opaque machine identifiers (letters, numbers, `.`, `_`, `-`) and warning fields contain
only bounded machine codes; listening notes remain the separately scanned human-review field.

Every record binds source SHA/dirty paths and fingerprints, hardware/OS/thermal context, toolchain
and executable identity, project/input/harness hashes, model/runtime/fixture identities, evidence
digests, ordered takes, per-cell distribution statistics, and optional independent listening
review. Dirty runs are exploratory and excluded from canonical comparisons. Instrumented and
partial runs are also isolated from normal timing trends.

Tracked validation re-derives cell aggregates and enforces each kind's immutable success shape,
including structured PID/CPU/signpost profile evidence, schema-v2 sidecar memory qualification and retention
policy evidence, and complete prosody-calibration aggregates. `rebuild-index` also reconciles comparison
deltas from the nearest earlier compatible clean record, so merge order cannot leave stale trends;
the `--check` form rejects any unreconciled record.

For trustworthy deltas: use the same canonical hardware, keep it quiet, watch thermals, keep cold
and warm separate, and compare medians/IQR from equivalent matrices. The generated comparison key
enforces equivalence and selects the nearest earlier compatible clean run; new records key on what
their kind measures (`scripts/lib/lineage_identity.py`, see benchmarking-procedure.md), legacy
records keep their stored keys byte for byte. The HISTORY trend takes the median per-cell delta over
cells with at least three takes and reads "within noise" below max(5%, 3 × the median absolute
deviation of the cell deltas), or "not trended" when only smaller cells carry a delta; UI records
trend on the app's submit→first-chunk span. A performance
delta does not automatically fail a benchmark whose own correctness gates passed.

### Guarding output quality

Perf is only half the story — a backend change must not introduce **audio** regressions (glitches,
dropouts, garbled words, "sounds worse"). Three layers, increasing in what they catch and what they cost:

1. **Reference-free defect detector — automatic, every run.** The engine runs a per-sample QC pass on
   the final PCM (extends `PCM16StreamLimiter`) and writes an `audioQC` verdict into the engine row:
   `pass` / `warn` / `fail` plus flags — `nonfinite` (NaN/Inf model output), `clipping`, `clicks`
   (chunk-boundary discontinuities — the decoder-drift class), `dropout` (interior silence),
   `near_silent` (dead output), `onset_step_burst` (v7: at least three quarter-scale steps clustered
   inside the first 50 ms, warn-only — the fp16 codec's first streamed chunk signature; the ordinary
   plosive-onset cluster 150 to 250 ms in is recorded as `stepBurstPeakCount` / `stepBurstPeakStartMS`
   and not judged). Surfaced as the summarizer's **`QC`** column. **Any `fail` blocks
   promoting a backend change.** Thresholds are conservative + tunable (`makeAudioQCReport`).
   **Dropout is punctuation-aware.** Long interior pauses (≥350 ms) count against the text's
   punctuation pause budget; an excess (flag `dropout:excessN`, followed by the long-pause count over the budget in parentheses; ≥2 fail, 1 warn) or a
   single egregious gap (≥1200 ms fail, ≥900 ms warn) flags. The regimes, their calibration history
   and the threshold-change authority live in `makeAudioQCReport` and
   [`audio-qc-engineering.md`](audio-qc-engineering.md#threshold-change-authority); a warning is
   never cleared by a subjective waiver.
   In v5 `audioQC` also reports **defect sample offsets** for debugging: `firstNonFiniteSample`,
   `firstClipSample`, and `longestSilenceStartMS`. In verbose mode the streaming path captures
   `chunkQC: [AudioQCChunkReport]` so defects can be tied to an individual output chunk. The report
   carries separate `instabilityVerdict` (pre-limiter evidence) and `writtenOutputVerdict` (the
   persisted WAV's exact frames) values in addition to the worst overall verdict; the algorithm
   version is stored with tracked evidence.
2. **Prosody analysis — conditional or explicit, no external model.** `vocello bench --delivery`
   automatically analyzes only its manifest-selected neutral/instructed pairs before final
   aggregation; the summarizer then surfaces `prosEff` / `dF0Std` / `dRateCV` / `dPauseR` /
   `dRough` in the delivery table. A benchmark without `--delivery` does not run that paired gate.
   `scripts/prosody_quality_gate.py` analyzes individual takes for monotone, rushed, flat, and
   pause-issue signatures only when invoked explicitly. Analyzer algorithm v2 reads the persisted PCM16 in exactly two
   fixed-block passes, retains no whole-file PCM or frame matrix, adds semitone-relative pitch and
   caller-declared boundary continuity summaries, and reports bounded managed-buffer/working-set
   evidence. Its fixed-bin quantiles may differ slightly from the legacy full-array algorithm, so
   the algorithm version is carried by newly calibrated profiles and results. All are deterministic,
   reference-free, and operate on bench WAVs.
   A JSON **prosody profile** (`scripts/prosody_profile.py`) supplies thresholds and delivery-effect
   weights. The canonical procedure owns calibration and benchmark invocation; the built-in profile
   is used when none is supplied.
3. **Optional listening annotation.** Automated checks deliberately claim structural integrity,
   intelligibility, language accuracy, reference consistency, and bounded prosody—not subjective
   beauty or naturalness. A person may annotate those impressions with
   `scripts/benchmark_history.py annotate`, but the annotation never changes the machine verdict.

Interpretation order is `audioQC` first, then fixed-seed/ASR evidence and any requested
delivery/per-clip prosody output. Any `QC=fail` is a hard stop for engine promotion, and an unresolved
warning is publishable evidence but not promotion-quality. The in-engine `audioQC` is the default signal;
committed bounded quality summaries and baselines remain permitted.

---

## 12. Extending the telemetry

- **New backend substage timing:** add a `ContinuousClock` accumulator in the Qwen3TTS
  decode loop (`Packages/VocelloQwen3Core/Sources/MLXAudioTTS/Models/Qwen3TTS/Qwen3TTS.swift`) and store it into
  the model's preparation‑timings dict — see [`qwen3-core-maintenance.md`](qwen3-core-maintenance.md)
  for the patch + validation gates. It will surface automatically in the engine row's
  `timingsMS` (the session re‑reads the model post‑loop). Avoid adding `eval()`/`.item()`
  syncs purely to measure — they distort the very thing you're measuring.
- **New stage mark:** add a `NativeRuntimeStage` case and `recorder.mark(stage:)` at the site
  (or a string‑keyed `recorder.mark(stage: "…")` for one‑off events like `memory_pressure` /
  `memory_trim` — no enum/schema change, the mark flows through `stageMarks` automatically).
  In v5 prefer typed metadata (`recorder.mark(stage:, metadata:)`) over string formatting for
  numeric metadata.
- **New derived KPI:** extend `computeDerivedMetrics` in `GenerationOutputAdapter`
  (`Sources/QwenVoiceCore/GenerationOutputAdapter.swift`).
- **New signpost interval:** open the interval and read the clock around the same code, and
  close it where the timing is captured (as `native_prepare_generation_ms` and the Qwen3 loop
  spans do), so the trace and the `timingsMS` key time the same span (audit #48). Inside the token loop use the allocation-free
  `os_signpost` entry point: `OSSignposter.beginInterval` allocates per call.
- **New field on the record:** add an optional field to `GenerationTelemetryRecord` (so old
  rows still decode) and bump `currentSchemaVersion`.
- **Naming:** use the `NativeTelemetry…` / `GenerationTelemetry…` families for new telemetry
  types.

---

## 13. See also

- [`qwen3-core-maintenance.md`](qwen3-core-maintenance.md) — owned core runtime procedure and validation gates.
- [`privacy-storage.md`](privacy-storage.md) — where diagnostics live; deletion paths.
- [`.claude/rules/native.md`](../../.claude/rules/native.md) — telemetry summary + engine invariants (bounded measured event delivery, typed cancellation, prewarm reentrancy, per-tier memory).
