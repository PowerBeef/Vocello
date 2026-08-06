# Telemetry & benchmarking

How Vocello measures itself. This is the single reference for the per‑generation
telemetry that spans the **frontend (app UI)**, the **middle communication layer
(macOS XPC service / iOS in‑process engine)**, and the **backend core (MLX / Qwen3‑TTS)** — what
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
> history/WAV/XPC/backend probes validate its smoke and benchmark results. iOS UI tests
> and real-engine generation remain **on-device only** on a paired physical iPhone. GitHub CI is
> compile-only for iOS.
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
   measured them. macOS UI evidence requires app + engine-service + engine; iOS UI evidence
   requires app + engine. A partial merge is marked incomplete and cannot publish history.

---

## 2. Turning it on

Telemetry persistence is governed by **`TelemetryGate`** (`Sources/QwenVoiceCore/TelemetryGate.swift`),
resolved once per process:

| Source | Effect |
|---|---|
| `QWENVOICE_DEBUG=1` (env) | On in any process that inherits it (e.g. `./scripts/build.sh run`). |
| 7‑tap the version label in Settings (persisted `UserDefaults` flag) | On in the app process; relayed to the engine process over the `initialize` IPC handshake (`telemetryEnabled`). |
| `QWENVOICE_NATIVE_TELEMETRY_MODE=lightweight\|verbose` (aliases: `light`, `full`, `deep`) | Forces sampling/persistence on regardless of the gate. |

The engine runs **out of process on macOS** (XPC service) and **in process on iOS**
(the ExtensionKit extension was removed; see `CLAUDE.md` / commit `aed617c`). The
different bundle id means the app's `UserDefaults` flag still can't reach the macOS
engine via environment — it is carried on the handshake, where the host calls
`TelemetryGate.applyHandshakeMode(_:)`.

### Sampling modes (`NativeTelemetryMode`, in `SemanticTypes.swift`)

| Mode | `QWENVOICE_NATIVE_TELEMETRY_MODE` | Memory sampler | Raw per‑sample series |
|---|---|---|---|
| `off` | `off` / `disabled` | — | — |
| `lightweight` (default when gate on) | `lightweight` / `light` | device‑tiered cadence | no |
| `verbose` | `verbose` / `full` / `deep` | device‑tiered cadence | **yes** (sidecar) |

`NativeTelemetryWorkPlan` makes the off contract explicit: no sampler, sink,
per-chunk QC, or expensive derived diagnostics are constructed. The deterministic
overhead lane verifies that optimization and waveform parity:

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
experiment, so new schema-v2 history publication fails closed. Existing schema-v1 overhead
records remain readable and memory-contract-incomplete.

Typical backend‑optimization invocation:

```sh
QWENVOICE_DEBUG=1 QWENVOICE_NATIVE_TELEMETRY_MODE=verbose ./scripts/build.sh run
```

### Related benchmark knobs (also propagated over the handshake)

`config/runtime-debug-knobs.json` owns this inventory. Production-affecting knobs are read through
`RuntimeDebugGate` and remain inert unless `QWENVOICE_DEBUG=1`; bounded observability and
test-target-only keys are separately classified. Never add an undocumented environment reader.

| Env | Effect |
|---|---|
| `QWENVOICE_SUPPRESS_WARMUP=1` | Skips proactive prewarm/clone‑priming so the first generation records its own **cold** load (`MacGenerationWarmupCoordinator`). App‑process only. |
| `QWENVOICE_FORCE_MEMORY_CLASS=floor_8gb_mac` | Forces the device-memory tier (`NativeDeviceClassGate`), propagated to the engine over `initialize`. Runs constrained-tier code paths for diagnostic comparison. See §11 "Memory and pressure interpretation". Accepts the `NativeDeviceMemoryClass` raw values + aliases `8gb`/`16gb`. |
| `QWENVOICE_MAC_WARM_GATE=off\|records\|enforce` | macOS warm‑admission gate (`MacWarmupAdmissionPolicy`): defers **proactive** warms while the app‑process kernel pressure level is soft/hardTrim on floor/mid tiers. Default `enforce` (validated 2026‑06‑09); `records` logs verdicts without blocking; user generations are never gated. Events land in `diagnostics/app/native-events.jsonl`. |
| `QWENVOICE_ENGINE_RETIRE_DWELL_SECONDS=<n>` | Dev override for the XPC service retirement idle dwell (default 300 s) so retirement‑to‑reclaim can be exercised without the full wait. App‑process only. |
| `QVOICE_TALKER_KV_QUANT=8\|4` | **Dev-only** opt‑in talker KV‑cache quantization (QuantizedKVCache, group 64). Measured (P4, §H): clone/long −271 MB physFoot but **−8.6% RTF** — not shipped on any tier; insurance knob only. Never combined with `QVOICE_TALKER_KV_WINDOW`. |
| `QVOICE_IOS_MLX_CACHE_LIMIT_MB=<n>` | **Dev-only** override of the MLX `Memory.cacheLimit` for the iPhone tier. Useful for sweeps; production uses the tier default. |
| `QVOICE_IOS_MLX_MEMORY_LIMIT_MB=<n>` | **Dev-only / do not ship** override of MLX `Memory.memoryLimit`. Production avoids a hard `memoryLimit`; see `mlx-guide.md` §5.2. |
| `QVOICE_IOS_MEMORY_PROFILE=iphone15pro` | **Physical-device memory-profile diagnostic**: clamps the effective per-process limit inside `IOSMemorySnapshot.capture()` so bands/admission/clone-gate use the smaller-device budget (`iphone15pro` → 5,000 MB). Rows stamp `notes.memoryProfile` and `notes.simulatedProcessLimitMB`. GPU compute and thermals remain those of the connected device; this is not proof for a different device. See the canonical benchmark procedure for `--memory-profile`. |

---

## 3. Architecture

```
 App process (Vocello)                    Engine process (macOS XPC service / iOS in‑process engine)
 ┌───────────────────────────┐  IPC      ┌──────────────────────────────────────────┐
 │ Coordinators              │  ───────► │ NativeEngineRuntime.prepareGeneration      │
 │   mint generationID       │ generate  │   creates per‑generation recorder          │
 │ AudioPlayerViewModel      │           │ MLXModelLoadCoordinator (load/tokenize)    │
 │   submit→firstChunk→       │ ◄──────   │ GenerationOutputAdapter                    │
 │   playbackScheduled→done  │  chunks   │   decode loop + shared sampler/session      │
 │ AppGenerationTimeline      │           │   reads MLX timings, per‑chunk substages   │
 │ GenerationTelemetryMerger  │           │ Qwen3TTS (owned) emits timings/counters │
 └───────────────────────────┘           └──────────────────────────────────────────┘
        │  writes app row                          │  writes engine + engine-service rows
        └──────────────► diagnostics/*/generations.jsonl ◄───────┘
                                  │ merge by generationID
                                  ▼
                         generations-merged.jsonl
```

Core types (all in `Sources/QwenVoiceCore/` unless noted):

| Type | Role |
|---|---|
| `TelemetryGate` | Master on/off, per process; handshake latch. |
| `NativeTelemetryRecorder` | Per‑generation stage timeline (`mark(stage:)`). The generation telemetry session begins before model preparation and shares one clock across load, prewarm, synthesis, finalize, trim, cancellation, and failure. |
| `NativeTelemetrySampler` | Background memory/timing sampler → `TelemetrySummary` + raw `[TelemetrySample]`. |
| `GenerationTelemetryRecord` | One durable row per layer (`engine` / `engine-service` / `app`). |
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
| `engine-service/generations.jsonl` | middle | XPC transport: request acceptance→first chunk, chunks forwarded, gaps, and forwarding span. |
| `app/generations.jsonl` | frontend | Submit→first chunk→playback scheduled→completed, delayed-heartbeat coverage, and playback health. It does not claim acoustic audibility or inherit engine memory. |
| `generations-merged.jsonl` | merged | Layers joined per `generationID`, with explicit `requiredLayers`, `missingLayers`, and `complete`. |
| `engine/samples-<generationID>.jsonl` | backend (verbose only) | Raw per‑sample memory/timing series. |
| `*/native-events.jsonl` | engine/middle/app | Chunk‑sequence gaps + encode drops; the **app** file also carries `mac_warm_admission_observed` / `mac_warm_blocked` (warm‑admission gate) and `engine_service_retired` (XPC retirement) events. **Written only when telemetry is enabled** (`TelemetryGate.resolvedEnabled` / app-process intended mode). |
| `<documents>/generation-failures.jsonl` | debug | Append-only failure log when telemetry is on (see `GenerationFailureDiagnosticLogger`). |

One JSON object per line. The field-reading order is in [§10](#10-reading-telemetry).

**Bounded by design.** These are append‑only but **size‑capped + auto‑pruned** (oldest‑first) by
`GenerationTelemetryJSONLSink`, so logs can't blow out disk: each `generations.jsonl` (incl. the merged
file) is front‑trimmed past ~8 MB (`QWENVOICE_DIAGNOSTICS_MAX_MB` scales it), and verbose
`samples-*.jsonl` sidecars are retained newest‑48 / ≤64 MB. No manual clearing needed for logs.

---

## 5. The per‑generation record schema

`GenerationTelemetryRecord` (schema v8). Optional fields are omitted from JSON when nil and
v1–v7 rows remain decodable. New history publication that claims qualified memory requires v8;
older rows stay readable but are marked memory-contract-incomplete and excluded from memory trends.

> **Convergence status:** The shipping JSONL envelope remains schema v8 and still embeds a nested
> `GenerationStreamingTelemetryTransitionV9` projection. When the transition is publication-ready
> and every chunk carries exact MLX instants, the engine also publishes a complete
> `*.streaming-telemetry-v9.json` sidecar and stamps `streamingTelemetryV9SidecarDigest` /
> `streamingTelemetryV9PublicationReady` notes. History may bind those sidecar digests; the
> top-level JSONL schema is not flipped to 9. Sampling promotion packaging stamps
> `samplingPromotionPackaged=true` after `SamplingTakeEvidence.validatedForPromotion()`.

| Field | Type | Notes |
|---|---|---|
| `schemaVersion` | Int | 8 (v2 derived/memory/chunk; v3 model/warm state; v4 audioQC; v5 high-resolution clocks; v6 typed payloads; v7 sampler accuracy/resource deltas and playback-scheduled naming; v8 independently qualified memory captures, absolute uptime, aligned snapshots, and coverage). |
| `clockSource` | String? | `mach_absolute_time` when nanosecond timestamps are present. |
| `generationID` | String | Correlation key (UUID). |
| `layer` | String | `engine` / `engine-service` / `app` / `merged`. (The retired iOS `engine-extension` layer no longer emits — iOS runs in-process.) |
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
| `audioQC` | `AudioQCReport?` | Versioned reference‑free overall, model-instability, and written-output verdicts plus flags, defect offsets, and optional per‑chunk QC. Algorithm v3 preserves chunk-spanning silence state and derives written-output evidence from the atomically published WAV frames. |
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

In addition to the MLX decode counters, v5 records the client/server boundary
intervals captured by `NativeTelemetrySignpostInterval` so a JSONL row can be read
back into Instruments‑style spans without the trace file:

| Key | Meaning |
|---|---|
| `clientWaitMS` | Time from user submit to the engine accepting the request. |
| `requestMS` | Engine total request wall time. |
| `serverGenerationMS` | Core model generation (token loop + decode). |
| `outputStreamingMS` | From first output byte to stream complete. |
| `totalMS` | End‑to‑end request span. |

These are optional and only emitted when the corresponding signpost interval was logged.

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
string‑keyed marks record memory events on pressure‑bound tiers: `memory_pressure` and
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
| `qwen_stream_step_eval_total` | `eval(...)` flush after each forward step (GPU dispatch). |
| `qwen_stream_step_eos_read_total` | EOS‑flag readback (a GPU sync). |
| `qwen_token_loop_total` | Whole per‑token loop wall time. |
| `qwen_token_loop_unattributed` | Loop time not attributed to a named substage (slack to chase). |
| `qwen_generated_code_count` | Tokens generated (counter). |
| `qwen_stream_decoder_calls` | Streaming chunk decode count. |
| prep / prewarm keys | `*_prefix_tokenize_ms`, `*_prefix_embed_build_ms`, `decoder_bucket_warm`, `*_prewarm_eval_ms`, … |

Use the breakdown to see which substage dominates (talker vs code‑predictor vs decoder)
and how much loop time is `unattributed` (candidate for new sub‑probes).

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
| `decodeWallSeconds` | Decode wall time (`qwen_token_loop_total` when present, else model `.info.generateTime`, else `streamStartup→streamGenerationEnded` span). Excludes WAV finalize I/O. | Compute cost — **same time base as the summarizer `decode ms` column.** |
| `audioSecondsPerWallSecond` | `audioSeconds ÷ decodeWallSeconds`. | **Real‑time factor: >1 = faster than realtime.** Primary throughput KPI. |
| `tokensPerSecond` | Codec tokens ÷ decode wall seconds (from `.info` when present). | Decode throughput; compare across model variants / patches. |
| `generatedTokenCount` | Codec tokens produced. | Work done; normalize other metrics by this. |

Frontend latency is the app row's `submitToFirstChunkMS` and
`submitToPlaybackScheduledMS`. The latter means the player was commanded with a bounded queued
buffer; it is **not** proof that acoustic output was audible. Proving audibility would require an
independent loopback measurement. The engine row's `firstChunk` mark is backend-only, while the
macOS transport row's `requestToFirstChunkMS` begins at request acceptance.

### RTF vs `decode ms` (read together, don't diff naively)

The summarizer prints **RTF** from `derivedMetrics.audioSecondsPerWallSecond` and **decode
ms** from `timingsMS.qwen_token_loop_total`. As of the P0‑1 alignment, both prefer the same
token‑loop wall clock when `qwen_token_loop_total` is present.

Caveats that still apply:

- **Lazy MLX** — substage columns (`talkerForward`, `codePredictor`, `streamStepEval`, Mimi
  decoder) measure Swift wall time around lazy graph ops; they sum to less than
  `qwen_token_loop_total` when work is pipelined across iterations.
- **`.info.generateTime`** — emitted mid‑stream before the trailing decoder flush; retained
  only as a fallback. When it differs from the token loop, `qwen_stream_decoder_drain_ms`
  captures the gap.
- **Stage marks** — `streamGenerationEnded` closes before WAV finalize; do not compare
  `streamStartup→streamCompleted` to decode ms (finalize I/O inflates the old span).

Use **RTF** for release throughput gates; use **decode breakdown + chunk timeline** for
where time goes; use **Instruments signposts** (see [`benchmarking-procedure.md`](benchmarking-procedure.md)
§4.8) for GPU attribution.

---

## 8. Memory probes

- **`mlxMemoryByStage`** — MLX GPU `active`/`cache`/`peak` MB captured at stage boundaries
  (`before_stream`, `first_chunk`, `after_stream`, `after_final_write`,
  `after_generation_trim`, plus prepare/clone/prewarm stages). Shows GPU memory growth
  across the pipeline — key for restricted‑hardware tuning. Captured at boundaries only
  (a GPU snapshot is too costly per chunk).
- **`summary`** (`TelemetrySummary`) — owning-process memory **curve** summary from the background
  sampler: resident, physical footprint, compressed, headroom, and GPU allocated start/end/delta
  plus peak/min; recommended Metal working set and usage ratio; total device RAM and the implied
  process limit; `timeToPeakMS`; and aligned `memoryAtStart`, `memoryAtEnd`,
  `memoryAtPeakPhysFootprint`, and `memoryAtMinimumHeadroom` snapshots. Memory, thread, headroom,
  Metal, and process-resource capture success/coverage are independent, so one failed API cannot
  masquerade as a zero value. Generation-scoped CPU, page-fault, context-switch, and block-I/O
  deltas remain process-owned.
- **Boundary samples** — capture immediately around model load, first chunk, final WAV, and trim,
  so short cold-load or finalize peaks are not dependent on the 500 ms constrained-device tick.
- **Verbose raw series** — `verbose` mode writes every sample (`tMS`, `scheduledElapsedNS`,
  `capturedElapsedNS`, absolute `capturedUptimeNS`, `latenessNS`, `kind`, `boundary`,
  `processRole`, resident/physical-footprint/compressed/headroom/Metal values, total RAM, implied
  process limit, and separate `memoryCaptureSucceeded`, `threadCaptureSucceeded`,
  `headroomCaptureSucceeded`, and `metalCaptureSucceeded` flags) to the exact
  `<layer>/samples-<generationID>.jsonl` sidecar. Raw rows remain untracked.
  Off by default (higher volume).
- **Kernel memory‑pressure marks** (in `stageMarks`) — on the pressure‑bound tiers
  (`floor8GBMac` / `mid16GBMac` / `iPhonePro`, where `NativeMemoryPressureMonitor` runs):
  - `memory_pressure` — the **raw kernel signal** (`metadata.level` = `softTrim`/`hardTrim`),
    stamped by `NativeEngineRuntime.recordMemoryPressureObserved` the instant the
    `DispatchSource` event arrives. Always recorded — it takes no prewarm slot.
  - `memory_trim` — the **trim action** taken in response (`metadata.level` + `reason`, e.g.
    `macos_memory_pressure_hardTrim`, `post_batch_low_ram`). Written by
    `NativeEngineRuntime.trimMemory`; skipped if the prewarm slot is contended, hence the
    separate always‑on `memory_pressure` mark above.

  A run with a `hardTrim` mid‑generation is shedding model state under pressure — an early
  OOM signal. On a non‑pressure‑bound tier (high‑memory Mac) the monitor never starts, so
  these marks are absent (correct, not missing data). `headroom*` summary fields populate on
  iOS only (`os_proc_available_memory`); on macOS they're nil and `phys_footprint` is the
  OOM‑relevant figure to watch.

### Publication-grade memory qualification

Benchmark-evidence manifest v2 binds `memoryContractVersion: 1`, `memoryQualified: true`, the exact
selected sidecar count/digest, and each take's `memoryStatus` plus sidecar digest. A sidecar must
start/stop exactly once, have monotonic elapsed/uptime clocks, match all summary counts, report zero
memory-capture failures, and retain at least 95% periodic coverage. Engine evidence includes
preparation/model-load/session/final-WAV and first-output/terminal boundaries; app evidence includes
`app_submit` and `app_terminal`. A 95–<100% coverage result is warning evidence.

Critical pressure, `application_memory_warning`, a memory exit, `hardTrim`, or `fullUnload` fails
publication. Guarded pressure or `softTrim` is `passedWithWarnings`. iOS additionally fails at
physical footprint ≥5.2 GB, minimum headroom <384 MB, or Metal working-set ratio ≥0.8; footprint
≥4.5 GB or headroom <768 MB is a warning. The iOS record retains start/end/min headroom and peak
process-budget utilization. macOS UI/XPC totals pair app and engine samples by absolute uptime within
one 500 ms cadence; they never add independent process maxima. Headless CLI/profile evidence reports
only its owning engine process.

The separate `memory` commands run policy `retained-memory-v1`: fixed Custom→Design→Clone
Speed/medium sequences with three retained takes per mode. Within each mode, first-to-last retained
physical-footprint growth must remain ≤5% of physical RAM. Intentional cross-mode model residency is
diagnostic unless a future runner proves an explicit full unload. These PASS-only runs publish the
`memory-qualification` kind; `profile --kind memory` remains the distinct Allocations + VM Tracker
Instruments lane.

On iOS, MetricKit's delayed daily aggregate is a complementary field signal. The app persists only
a bounded privacy-reduced memory/exit summary; raw payload JSON, call stacks, identifiers, and paths
are not retained for this purpose. After an explicit device pull,
`scripts/ios_device.sh memory-field-report [pulled-diagnostics]` reads local files only. It does not
contact the phone, does not publish benchmark history, and reports `notYetDelivered` nonfatally when
MetricKit has not delivered a payload. Daily values are not run-correlated and cannot qualify or
retroactively fail an individual take.

### Frontend responsiveness and playback health

The app watchdog uses generation-scoped session tokens so a late callback from a finished run
cannot contaminate the next. It reports scheduled/completed heartbeat counts, coverage, delayed
heartbeat counts at the configured thresholds, and the maximum observed delay. These are sampling
statistics, not an exhaustive count of every main-thread stall.

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
from leaking into the current summary. The summarizer can merge the macOS app, XPC, and engine
layers by `generationID`; CLI rows have only the engine boundary. Read `finishReason` and
`audioQC` before interpreting performance, keep cold and warm populations separate, and compare
`derivedMetrics.audioSecondsPerWallSecond` with the dominant `timingsMS` substage. A cold Custom or
Design row should include `upstreamModelLoad` in `stageMarks`; an immediately repeated row should be
warm. See [`benchmarking-procedure.md`](benchmarking-procedure.md) for supported invocations.

---

## 11. Benchmark result interpretation

This document is the telemetry schema and interpretation reference. The sole operational source for
benchmark preflight, model and clone-fixture preparation, exact matrices, commands, UI lanes,
artifact handling, and troubleshooting is
[`benchmarking-procedure.md`](benchmarking-procedure.md). In particular, do not derive a Clone
fixture from a Custom Voice output: the canonical fixture is generated through Voice Design and its
provenance is verified by the repository model-preparation helper.

Each engine row identifies its cell through `mode`, variant-specific `modelID`, and `warmState`.
Custom and Design can produce genuine cold rows; Clone is normally warm because reference
conditioning primes the model. Interpret a missing Clone cold row as expected unless the canonical
procedure explicitly changes that contract.

The summarizer is streaming (it walks JSONL once with `iter_jsonl`, maintains a lightweight
app index, and aggregates with `CellAccumulator`) so it handles large verbose logs without
loading them into memory. Prints a `mode × model × cold/warm` table (median over warm): RTF, tokens/s, TTFC, decode‑loop ms,
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
`benchmarks/runs/<kind>/` (≤256 KB), with a generated `HISTORY.md` index. Existing Markdown/JSON
baselines remain reference artifacts; they are not silently upgraded into complete records.
Schema-v1 history remains readable; new memory-qualified records use schema v2 and cannot be mixed
into memory trends with v1. Raw telemetry, audio, screenshots, result bundles, and traces remain untracked. A successful
profile record captures the original trace digest/path, capture settings, extracted summary, and
retention policy; the raw trace is discarded after publication unless `--keep-trace` was explicit. Registry
validation is deterministic CI work, but model/device/UI execution is not an ordinary CI or
packaging gate.

### Memory and pressure interpretation

RAM usage (physFoot/RSS/peak‑GPU + the per‑stage GPU block) is captured on **every** run. But the
**memory‑pressure** signals (`trims`/`pressure`) only fire on a pressure‑bound tier
(`floor8GBMac`/`mid16GBMac`/`iPhonePro`), and `deviceClass()` is derived from real RAM — so on a
high‑memory dev Mac they read `0`.

`QWENVOICE_FORCE_MEMORY_CLASS` (accepts `floor_8gb_mac`/`mid_16gb_mac`/`high_memory_mac`/`iphone_pro`,
or aliases `8gb`/`16gb`/`high`/`iphone`) is read in the app process and **propagated to the engine over the
`initialize` IPC handshake** (env doesn't cross to the engine process — same path as `telemetryMode`).
When selected by the canonical diagnostic procedure, it makes the engine run the floor-tier code
paths: the pressure monitor **starts**, caches are tight,
single‑gen clears + post‑batch hard trims fire, and idle‑unload is aggressive. Every engine row stamps
`notes.deviceClass`, so the summarizer header shows `tier: floor_8gb_mac ⚠ forced` — never mistake a
forced run for native‑tier data.

Pressure-triggered trims appear as `memory_pressure` and `memory_trim` stage marks. Interpret them
together with `physFoot`, the GPU-by-stage block, and the recorded device class; a forced class is
diagnostic evidence, not proof for that physical device.

> **Caveat:** on the forced floor tier, a Quality load that cannot fit will surface as an error rather
> than silently falling back to Speed. The row's `modelID` reveals the actual variant served — check it
> before attributing a Quality cell. The forced tier changes real behavior **only while the env is set**;
> unset it for normal use.

**Watch for OOM regressions** when optimizing the backend: a rising `physFoot` peak, GPU‑stage peak,
or any `hardTrim` in `trims` means a run is shedding model state under pressure — the early OOM signal.

**Verify attribution:** for Custom Voice and Voice Design, each accepted cold row must show
`warmState":"cold"` and carry `upstreamModelLoad`; warm rows show `"warm"`. Clone rows are normally
warm by design.

### Tracking performance over time

Each successful publishable runner creates one canonical, privacy-safe schema-v2 record under one
of seven kinds: UI generation, engine generation, language, instrument profile, retained-memory
qualification, prosody calibration, or UI frame health (`ui-perf`, from the macOS perf lane). `scripts/benchmark_history.py` validates these records and regenerates
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
enforces equivalence and selects the nearest earlier compatible clean run. A performance delta does
not automatically fail a benchmark whose own correctness gates passed.

### Guarding output quality

Perf is only half the story — a backend change must not introduce **audio** regressions (glitches,
dropouts, garbled words, "sounds worse"). Three layers, increasing in what they catch and what they cost:

1. **Reference-free defect detector — automatic, every run.** The engine runs a per-sample QC pass on
   the final PCM (extends `PCM16StreamLimiter`) and writes an `audioQC` verdict into the engine row:
   `pass` / `warn` / `fail` plus flags — `nonfinite` (NaN/Inf model output), `clipping`, `clicks`
   (chunk-boundary discontinuities — the decoder-drift class), `dropout` (interior silence),
   `near_silent` (dead output). Surfaced as the summarizer's **`QC`** column. **Any `fail` blocks
   promoting a backend change.** Thresholds are conservative + tunable (`makeAudioQCReport`).
   **Dropout is punctuation-aware** (calibrated 2026-05-31): the model emits a prosodic pause at each
   sentence/clause boundary, so on long, slow content interior silences legitimately reach ~800 ms — a
   fixed ≥400 ms fail line cried wolf on natural delivery (every long-content silence mapped to a
   punctuation mark). Instead the detector counts *long pauses* (≥350 ms) against the text's **pause
   budget** (interior punctuation boundaries, including CJK full-width marks, from `request.text`)
   and flags only an **excess** beyond it
   (`dropout:excessN(long/budget)` — ≥2 = fail, 1 = warn) or a single **egregious** gap no natural pause
   reaches (≥1200 ms = fail `dropout:Nms`; ≥900 ms = warn). A genuine mid-phrase gap that merely *replaces*
   a punctuation pause (same count, ~same length) is positionally indistinguishable from a comma pause by
   amplitude alone. Promotion therefore requires the remaining automated cohort, ASR, and prosody
   evidence to be clean; a warning is not cleared by a subjective waiver.
   In v5 `audioQC` also reports **defect sample offsets** for debugging: `firstNonFiniteSample`,
   `firstClipSample`, and `longestSilenceStartMS`. In verbose mode the streaming path captures
   `chunkQC: [AudioQCChunkReport]` so defects can be tied to an individual output chunk. QC
   algorithm v2 introduced persistence of the absolute start of an open silence run across chunk
   appends, so a chunk-spanning dropout keeps its correct start and duration. Algorithm v3 retains
   pre-limiter instability evidence but reopens the atomically published WAV and computes level,
   DC-offset, and dropout evidence from its exact persisted frames. It reports separate
   `instabilityVerdict` and `writtenOutputVerdict` values in addition to the worst overall verdict;
   the algorithm version is stored with tracked evidence.
2. **Prosody analysis — conditional or explicit, no external model.** `vocello bench --delivery`
   automatically analyzes only its manifest-selected neutral/instructed pairs before final
   aggregation; the summarizer then surfaces `prosEff` / `dF0Std` / `dRateCV` / `dPauseR` /
   `dRough` in the delivery table. A benchmark without `--delivery` does not run that paired gate.
   `scripts/prosody_quality_gate.py` analyzes individual takes for monotone, rushed, flat, and
   pause-issue signatures only when invoked explicitly, and `scripts/delivery_adherence.py` is an
   explicit corpus workflow. Analyzer algorithm v2 reads the persisted PCM16 in exactly two
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
  the model's preparation‑timings dict — see [`mlx-audio-swift-patching.md`](mlx-audio-swift-patching.md)
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
- **New signpost interval:** wrap the span with `NativeTelemetrySignpostInterval.begin/end`
  and merge the resulting key into `timingsMS`.
- **New field on the record:** add an optional field to `GenerationTelemetryRecord` (so old
  rows still decode) and bump `currentSchemaVersion`.
- **Naming:** do **not** introduce symbols containing `Probe`/`Benchmark` or the other tokens
  in `scripts/check_project_inputs.sh` — that guard fails the build. Use the `NativeTelemetry…`
  / `GenerationTelemetry…` families.

---

## 13. See also

- [`mlx-audio-swift-patching.md`](mlx-audio-swift-patching.md) — owned core runtime procedure and validation gates.
- [`privacy-storage.md`](privacy-storage.md) — where diagnostics live; deletion paths.
- [`.claude/rules/backend-mlx.md`](../../.claude/rules/backend-mlx.md) — telemetry summary + engine invariants (bounded measured event delivery, typed cancellation, prewarm reentrancy, per-tier memory).
