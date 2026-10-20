---
status: active
owner: backend-mlx
reviewed: 2026-10-20
summary: Project-specific MLX reference for the Qwen3-TTS engine on mlx-swift 0.32.3 — lazy evaluation and the pipelined per-frame step, MLX error scopes, quantization mechanics and the per-layer recipe, the KV cache, sampler and seed behaviour, cache clearing and memory posture, the version pins and the pin-move procedure (§9).
sourceOfTruth:
  - Packages/VocelloQwen3Core/Package.swift
  - Packages/VocelloQwen3Core/Sources/VocelloQwen3Core/Runtime.swift
  - Packages/VocelloQwen3Core/Sources/MLXAudioTTS/Models/Qwen3TTS/Qwen3TTS.swift
  - Packages/VocelloQwen3Core/Sources/MLXAudioTTS/Models/Qwen3TTS/Qwen3TTSTalker.swift
  - Sources/QwenVoiceCore/NativeMemoryPolicyResolver.swift
  - config/swift-dependency-update-policy.json
---
# MLX Guide for Vocello

> **Living document.** When this guide disagrees with the code, the code wins: fix this file.
> Reviewed 2026-10-20 against the shipping pins (mlx-swift 0.32.3, mlx-swift-lm 3.32.3,
> swift-transformers 1.3.5 and swift-huggingface 1.0.0, moved together by CONV-21 on 2026-10-16) and
> the RF-18 sampling changes of 2026-10-20. Finding IDs (BG-1, DEP-n, A-n, B-n, D-n, F-n) are the
> [engine runtime audit](../audits/2026-10-16-engine-runtime-audit.md)'s; upstream issue citations
> (`QwenLM#n`, `MA#n`, `MAS#n`) come from the
> [Qwen3-TTS model research](../audits/2026-10-17-qwen3-tts-model-research.md).

This guide owns MLX semantics as Vocello uses them: evaluation, error scopes, quantization
mechanics, the KV cache, sampler and seed behaviour, cache clearing and the dependency pins. Other
facts have one owner each:

| Topic | Owner |
|---|---|
| Model family, architecture, generation parameters, failure catalogue, parity ledger | [`qwen3-tts-guide.md`](qwen3-tts-guide.md) |
| Prompt wire format and transcript rules | [`qwen3-tts-prompting-guide.md`](qwen3-tts-prompting-guide.md) |
| The 12 Hz speech tokenizer (codec) | [`mimi-codec-guide.md`](mimi-codec-guide.md) |
| Artifact bytes, digests, quantization map and artifact history | [`model-delivery.md`](model-delivery.md) |
| Engine structure, memory tiers, event router, prewarm, cancellation | [`ARCHITECTURE.md` §4](../ARCHITECTURE.md#4-engine-core-qwenvoicecore) |
| Metal under MLX | [`metal-guide.md`](metal-guide.md) |
| The owned package's maintenance and upstream intake | [`qwen3-core-maintenance.md`](qwen3-core-maintenance.md) |

---

## 1. Why MLX

Vocello synthesizes speech on-device with Qwen3-TTS on Apple's [MLX](https://github.com/ml-explore/mlx),
through [`mlx-swift`](https://github.com/ml-explore/mlx-swift) and
[`mlx-swift-lm`](https://github.com/ml-explore/mlx-swift-lm). The model implementation is the owned
[`VocelloQwen3Core`](../../Packages/VocelloQwen3Core/README.md) package, derived from
[`mlx-audio-swift`](https://github.com/Blaizzy/mlx-audio-swift). MLX fits because of:

- **Unified memory:** CPU and GPU share one physical pool, so weights and caches need no copies.
- **Lazy evaluation:** operations build a graph that runs only when a result is needed.
- **Native quantization:** 4-bit and 8-bit weight-only quantization is a first-class path, which is
  how Vocello ships Speed (4-bit) and Quality (8-bit).
- **A Swift API:** no Python runtime ships in the app or the CLI.

---

## 2. Core MLX concepts

### 2.1 `MLXArray`

`MLXArray` (module `MLX`) is an n-dimensional array with a dtype and a shape that lives in unified
memory.

```swift
import MLX

let a = MLXArray([1, 2, 3, 4])
let b = MLXArray([1.0, 2.0, 3.0, 4.0])
let c = a + b          // still lazy
```

### 2.2 Lazy evaluation

Operations build a graph of primitives; nothing runs until an array is evaluated or read:

- `eval(...)` and `asyncEval(...)`;
- `item(...)`, which reads a scalar;
- `asArray(...)` and other copies to CPU memory.

Timers around graph construction measure Swift CPU time, not GPU time. Vocello's telemetry records
both, and lazy timings are never kernel attribution (§8).

### 2.3 `eval()` and `asyncEval()`

| API | Behaviour | Vocello use |
|---|---|---|
| `eval(_:)` | Blocks until the graph is computed. | Batched weight materialization, readback probes (§2.6), the `.full` step diagnostic. |
| `asyncEval(_:)` | Submits the graph and returns; the next read waits for it. | The production per-frame step and decoder chunks (§4.3). |

### 2.4 Streams and devices

MLX runs operations on a stream; the default is the GPU. Vocello runs model work on that one global
GPU stream (audit F). The only explicit CPU-stream work is the speaker embedding's finite check
(`Qwen3TTS.swift:1040`), so adopting a stored clone artifact submits no Metal work iOS could refuse
in the background (BG-01).

### 2.5 Unified memory

There is no `.to(device:)`: CPU and GPU read the same buffers. GPU allocations, CPU allocations and
OS memory pressure therefore compete for the same RAM, which is why the iPhone policy reads
`os_proc_available_memory()` and the physical footprint rather than a "GPU memory" figure (§5.5).

### 2.6 Errors and error scopes

**MLX's error model.** MLX reports a C++ error through one process-wide callback that carries only a
message. mlx-swift keeps a task-local stack of handlers (`withErrorHandler`) and calls the innermost;
with none installed it calls `fatalError`. `withError { … }` installs its own handler and throws
`MLXError.caught` when the block returns. After an error MLX returns without evaluating: the array
stays unfilled, an `item` read returns a default value, and an `asArray` read copies from a nil
buffer and traps (F-03).

**Command-buffer failures (ml-explore/mlx#3523).** mlx-swift 0.32.3 bundles MLX `1f8e74e3`, which
contains #3523: a Metal command-buffer failure (a GPU submission iOS refuses in the background, or
an out-of-memory buffer) is recorded by the completion handler, poisons the buffer's events and is
raised at the next wait, on the waiting task, inside its scope. On 0.31.6 the completion handler
threw on a Metal thread and aborted the process: BG-1's crash class (DEP-1).

**Vocello's scopes** (`VocelloQwen3MLXErrorScope`,
`Packages/VocelloQwen3Core/Sources/VocelloQwen3Core/Runtime.swift:223`):

- **Coverage.** Model load, prewarm, priming, clone conditioning (`makeCloneHandle`), codec replay,
  audio marking and generation run inside a scope. Since BG-01 (2026-10-16), clone-artifact
  adoption and persistence do too (`Engine.swift:708-757`); before it they ran unscoped, so a refused
  or out-of-memory buffer there reached `fatalError` (F-01, B-14).
- **Typed failures.** The scope keeps the first error and throws `VocelloQwen3RuntimeFailure`:
  `.allocation` reaches the product as memory pressure, `.mlx` as a runtime failure. The message is
  classified once, at this boundary, and never crosses the facade. Cancellation wins over a recorded
  failure.
- **Readback probes (F-03).** Every production `asArray` readback is preceded by `evalForReadback`
  (`Qwen3TTS.swift:54`), a nested `withError`, so a failed evaluation throws before the copy.
- **Unload after a failure.** A recorded evaluation or allocation failure marks the loaded model for
  unload before the next admission (`requiresUnloadAfterRuntimeFailure`), because it may hold
  half-evaluated state. A file error from mlx-swift's own I/O (`MLX.save`, `loadArrays`) during
  artifact adoption or persistence fails the operation without an unload.
- **Lazy work stays inside its scope.** The clone reference encode is evaluated inside
  `createVoiceClonePrompt` (`Qwen3TTS.swift:2257-2260`, F-07) instead of later, in persistence or the
  first take.
- **Not captured.** MLX work on a detached task, on a thread outside the task tree, or on MLX's CPU
  scheduler thread still reaches mlx-swift's process-wide fallback.

Deterministic coverage: `RuntimeFailureCaptureTests`. How the host reacts (the take lifecycle and
the iPhone's foreground permit) is engine structure:
[ARCHITECTURE §4.9](../ARCHITECTURE.md#49-cancellation).

---

## 3. Quantization and model loading

### 3.1 Weight-only affine groupwise quantization

| Variant | Bits | Group size | Platforms |
|---|---|---|---|
| **Speed** | 4 | 64 | macOS and iPhone (the iPhone's only variant) |
| **Quality** | 8 | 64 | macOS only |

Each group of 64 weights is stored as 4-bit or 8-bit integers with a per-group scale and bias
(MLX's `QuantizationMode.affine`). The quantized matmul dequantizes inside the kernel; activations
and compute stay in bf16, the shipped checkpoints' compute dtype. MLX's other quantization modes are
not used.

### 3.2 The per-layer recipe and how the loader applies it

- **Where the recipe lives.** The checkpoint's `config.json` carries a global `quantization` entry
  (group size and bits) and per-layer entries. Vocello's one per-layer entry is
  `model.text_embedding` at 8 bits, group 64, affine, in both tiers, written by
  `scripts/convert_text_embedding_8bit.py` (2026-07-26).
- **What the loader does** (`Qwen3TTS.swift:5768-5781`). `quantize(model: talker)` runs a per-path
  closure that quantizes a module only when the checkpoint holds `<path>.scales`, and uses the
  per-layer entry when one names the path, the global entry otherwise. The artifact therefore decides
  which modules are quantized; the code holds no list.
- **What that yields.** Every talker and code-predictor projection, the 15 code-predictor heads,
  `codec_head`, `small_to_mtp_projection` and `text_projection` are quantized (251 modules in the
  4-bit CustomVoice index); the codec embeddings, norms and biases stay bf16, the Base speaker encoder
  stays float, and the speech tokenizer is a separate fp32 file. The full map, the bytes and the
  artifact history are [`model-delivery.md`](model-delivery.md)'s (artifact provenance).
- **Verification.** A trusted prepared checkpoint loads with `verify: .noUnusedKeys`, an untrusted
  one with `.all` (`Qwen3TTS.swift:5797-5799`); a trusted load therefore checks only for unused keys
  (A-20).
- **Batched materialization.** Weights are evaluated four talker or code-predictor layers at a time
  and eight speech-tokenizer parameter arrays at a time (`Qwen3TTS.swift:470-471`), which bounds the
  transient unified-memory peak.

### 3.3 Precision risks

- Qwen trained and evaluated in bf16 and recommends fp32 where bf16 is unavailable, because the code
  predictor is "extremely sensitive to precision" (QwenLM#43). No quantized checkpoint was ever
  evaluated upstream, and Vocello's 4-bit artifacts quantize all 51 code-predictor linear and head
  tensors. How much that changes output is unmeasured (research open question 7).
- The ports' lessons (research §6): keep embeddings, the speaker encoder and the codec unquantized,
  run RVQ encode in fp32, and avoid fp16 logits. Vocello keeps the codec fp32 (the f16 codec was
  withdrawn on 2026-09-14), samples from float32 logits (§4.5), and casts the float32 speaker
  embedding to the compute dtype only at prefix construction, which avoids the promotion of the
  prefill and KV to float32 (about 2.4× slower) that mlx-audio fixed in `90ee81f`.

### 3.4 Loading weights

1. Resolve the model from `Sources/Resources/qwenvoice_contract.json`.
2. Download through the production catalog's exact delivery plan and activate only after every
   file's digest verifies; swift-huggingface 1.0.0 is only the transport
   ([`model-delivery.md`](model-delivery.md)).
3. Load `model.safetensors` into `MLXArray` dictionaries and sanitize the keys.
4. Quantize the module tree (§3.2), then `update(parameters:verify:)`.
5. Evaluate the weights in batches (§3.2).

### 3.5 The quantized-load leak

Every quantized load leaks its initialization graph: about 110 MB after 43 reloads (mlx-audio-swift
PR #286 and ml-explore/mlx PR #4710, both open when the research checked on 2026-10-16; #4710 has
since closed unmerged). It applies to Vocello's quantized load and is not fixed here. It matters where loads repeat: the iPhone unloads after 30 s idle and reloads for the next
take (ER-06, ER-07), and D-04's 309 MiB left in MLX's cache after an unload may be partly this
(research §10).

### 3.6 API history

- **0.31.x** gave `Quantizable.toQuantized` a `mode: QuantizationMode` parameter, made `quantize`
  a top-level function with `mode:`, and made `quantized()`'s biases optional. Vocello's call sites
  compiled unchanged; the 2026-08-01 move to 0.31.6 / 3.31.4 kept its evidence in
  `benchmarks/OPTIMIZATION.md` §Q.
- **0.32.3** broke no Vocello API, left `KVCacheSimple` unchanged, and changed no stream or device
  semantics that matter (audit F). Its effects are numerical and performance ones (§9.5).

---

## 4. The per-frame loop on MLX

The model itself (the talker, the 15-pass code predictor, the codec) is described in
[`qwen3-tts-guide.md`](qwen3-tts-guide.md). This section covers how the owned runtime runs it on MLX
(`Packages/VocelloQwen3Core/Sources/MLXAudioTTS/Models/Qwen3TTS/`).

### 4.1 Talker attention, RoPE and the KV cache

- **RoPE is plain 1-D split-half.** `TalkerRotaryEmbedding` computes frequencies for three position
  streams and interleaves them with `mrope_section` `[24, 20, 20]`
  (`Qwen3TTSTalker.swift:40-101`), then applies `rotate_half` (`:8-23`). Production passes no
  explicit positions, so the talker stacks three identical streams from the cache offset (`:305-313`),
  as upstream does (`cumsum(mask) - 1`). M-RoPE's separate positions therefore never occur: the
  result is plain 1-D RoPE (A-19).
- **Scalar gather.** The interleave reads `freqs[0]`, `freqs[1]` and `freqs[2]`
  (`Qwen3TTSTalker.swift:57-59`), and RVQ decode reads `codes[idx]`
  (`Qwen3TTSSpeechTokenizer.swift:48`). That scalar-integer gather passes empty index metadata to
  Metal when Metal API validation is on. mlx-audio-swift v0.1.5 (`dbe5eaa`) replaced it with range
  slices; Vocello has not ported that (ER-08, ER-12). No shared Xcode scheme enables API validation,
  and whether the issue reproduces under 0.32.3 is open (research open question 8).
- **Attention.** Per-head RMSNorm on q and k precedes RoPE. Attention goes through
  `MLXLMCommon.attentionWithCacheUpdate`: fused scaled-dot-product attention, or the quantized form
  when the cache is a `QuantizedKVCache`. The SwiGLU is `compile(shapeless: true)`
  (`Qwen3TTSTalker.swift:33-37`).
- **KV cache.** One unbounded `KVCacheSimple` per layer (`Qwen3TTSTalker.swift:333-339`) in the
  compute dtype: **bf16**, not fp16. The alternatives are diagnostic knobs only (§7.5).

### 4.2 The code predictor and its compiled plan

- **RoPE.** `MLXFast.RoPE(traditional: false)`, the split-half layout
  (`Qwen3TTSCodePredictor.swift:62-73`); this fused RoPE replaced a hand-rolled rotate-half chain
  (§7.2).
- **The compiled plan** (`Qwen3TTSCodePredictorCompiled.swift`; `SEMANTIC_DELTAS.json` DECODE-001,
  active). The 15 passes are compiled once per generation, keyed by pass index, and own their K/V
  buffers. `Qwen3CodePredictorCompiledTests` compares the compiled and eager paths within
  `accuracy: 2e-6` on a small fp32 model, not byte for byte (F-15); the file's own comment claims
  more. The adoption A/B measured 12/12 fixed-seed byte-identical takes on its cells, a one-time
  result that the unit test does not guarantee.
- **Weights are baked at trace time** (A-16). The plan lives for one generation today; reusing it
  across takes (PERF-10) must declare the weights as inputs or key the plan by load epoch.
- **Single flight.** Every take traces 15 compiled functions with a nested compiled `silu` (F-09).
  mlx-swift 0.32.x contains #461, the fix for a lock-order deadlock between compiled functions and
  `evalLock`; before it, single-flight generation kept that deadlock unreachable (DEP-2). Keep every
  MLX caller single-flight anyway.

### 4.3 The per-frame step

Each frame builds one graph (talker forward, the 15 code-predictor passes, sampling and the next
step's input embedding) and submits it once. Production uses the `.pipelined` step policy
(`Qwen3StreamStepEvalPolicy`, `Qwen3TTS.swift:432-445`):

1. `asyncEval(inputEmbeds, isEOS)` submits the step (`Qwen3TTS.swift:4049-4052`);
2. the previous chunk's materialization and channel sends run while it computes;
3. the sampled-token `item` read is the step's first blocking read.

`.full` (a synchronous `eval`) remains a diagnostic for exact per-stage attribution. Nothing else
reads the GPU inside the step. The next input sums the codebook embeddings with serial bf16 adds
(`Qwen3TTS.swift:4034-4039`), where the reference uses one reduction (A-17).

### 4.4 The audio decoder

The streaming decoder uses input-side overlap-and-discard (`4fab110`); each decoded chunk is
submitted with `asyncEval` and materialized before its send. The decoder does not apply upstream's
72-frame window, so its fp32 KV grows over the whole take (A-03, PA-16). Codec details:
[`mimi-codec-guide.md`](mimi-codec-guide.md).

### 4.5 Sampling on MLX

- **Request-local randomness.** Sampling algorithm v2 resolves one immutable
  `VocelloQwen3SamplingConfiguration` per request. Each request records its effective seed and owns
  a fresh `MLXRandom.RandomState`; talker and code-predictor draws run under it and never advance
  MLX's process-global RNG.
- **float32 logits.** Both stages sample from float32 logits whatever the model's precision, as
  Qwen's reference does (D3, production since 2026-10-13; `QWENVOICE_SAMPLER_FLOAT32=off` restores
  model-precision sampling). The cast is lazy inside the step graph (`Qwen3TTS.swift:5242-5244`).
- **Order** (`sampleToken`, `Qwen3TTS.swift:5223`): token suppression, the repetition penalty (talker
  only), temperature, top-k, top-p, min-p, then MLX's categorical at temperature 1. Temperature
  comes before the truncation filters (ported from mlx-audio `a730a68`).
- **EOS** is filtered like any token since 2026-10-20 (D2, the RF-18 follow-up screen);
  `QWENVOICE_TALKER_FILTER_EOS=off` restores re-insertion after the filters.
- **Values.** The code predictor samples at the reference's 0.9 / top-k 50 / top-p 1.0 for every
  variation since 2026-10-20 and never applies the repetition penalty; the talker's values per
  variation are [`qwen3-tts-guide.md`](qwen3-tts-guide.md)'s.
- **Seeds (F-02, accepted).** MLX #4177's inverse-CDF categorical applies to `[1, V]` logits, which
  is every Vocello draw, so a seed from mlx-swift 0.31.x does not reproduce its take; the release
  notes say so. `testSeededSamplerGoldenTokens` pins the 0.32.3 draws; re-record it only with a
  reviewed pin move. Takes for one seed also differ across the float32 change and the 2026-10-20
  subtalker and EOS changes, so reproducibility holds within one source identity.
- **Cost (F-04).** The new sampler path adds about 80 kernel launches per frame (16 draws × 5); the
  M6's warm first chunk rose from 146 to 155 ms (§9.5).
- **Prewarm draws through the production sampler** (`productionSamplerWarmDraws`,
  `Qwen3TTS.swift:1910-1938`; F-05): with top-p 1.0 and 0.95, one penalized id and then two, on a
  private random state whose draws are discarded, so the sampler's kernels compile before the first
  take and no output changes.

---

## 5. Memory management

### 5.1 `Memory.cacheLimit` and `Memory.memoryLimit`

- **`Memory.cacheLimit`** caps the buffer pool MLX keeps for reuse. It is Vocello's main memory
  lever, set per tier at the host boundary (`NativeMemoryPolicyResolver.apply`).
- **`Memory.memoryLimit`** is a hard ceiling on MLX's allocations. Vocello does not set it in
  production (§5.2).

### 5.2 Why Vocello avoids a hard `Memory.memoryLimit`

Early experiments set a 6 GB cap on the 8 GB Mac floor and a 5 GB iPhone cap. They caused spurious
out-of-memory downgrades during cold-load peaks, because the cap sat below the real Jetsam ceiling,
and were reverted in `b77c08e`. The engine gates instead on:

- the per-tier `Memory.cacheLimit`;
- explicit cache clears (§5.4);
- `os_proc_available_memory()` on iOS for admission and pressure bands;
- `physFootprint` and `Memory.snapshot()` telemetry.

Only the internal-diagnostics `QVOICE_IOS_MLX_MEMORY_LIMIT_MB` override sets a hard limit.

### 5.3 Per-tier clearing knobs

Tier classification, cache limits and idle-unload windows are
[ARCHITECTURE §4.5](../ARCHITECTURE.md#45-memory-policy)'s. The MLX clearing knobs each tier sets
(`NativeMemoryPolicyResolver.swift`):

| Tier | Clear after generation | Clear on each stream chunk | Token clear cadence |
|---|---|---|---|
| `floor8GBMac` | outside batches | yes | 50 |
| `mid16GBMac` | no | yes | 50 |
| `highMemoryMac` | no | no | 200 |
| `iPhonePro` | always | yes | 50 |

The batch flag is always false today, so the batch policy is unreachable (B-13). The values came
from benchmarking, not a formula; changing them needs fresh RTF and peak-memory evidence on real
hardware. MLX allocator limits are process-wide; the clear cadence, chunk clear and talker KV window
travel per request in the immutable `VocelloQwen3MemoryConfiguration` → `Qwen3RequestMemoryPolicy`,
so one generation cannot change another's.

### 5.4 Cache clearing and what it costs

The runtime clears MLX's buffer cache at three policy points: after a generation (per tier), after
each streamed chunk when `clearCacheOnStreamChunkEmit` is set (`Qwen3TTS.swift:3235-3305`), and
every N generated tokens (`tokenMemoryClearCadence`, `Qwen3TTS.swift:3494`). Outside that policy,
marking clears the cache three times per take (B-09), and the code makes 16 direct
`Memory.clearCache()` calls (B-22, E2-02).

Clearing is not free: freed buffers are re-created on the next allocation.

- mlx-audio's Python Qwen3-TTS cleared at the same two hot-path sites (every 50 tokens and every
  streamed chunk); MA#851 measured about 13% RTF from removing them on an M1 Pro.
- Vocello has not measured its own cost. The iPhone runs 113–126 clears per long take at its
  128 MiB cache (audit D), and D-06 counts the per-chunk clears among the costs the measured 8,192 MB
  budget does not need. A knob to A/B the iPhone's per-chunk clear is an ER-01 measurement gap.
- A full unload left 309 MiB in MLX's cache, because the cache was cleared before the last holder
  released the model; the holder is unidentified (D-04).

### 5.5 iOS memory specifics

The engine runs in-process, so the app and the engine share one Jetsam budget. The
`com.apple.developer.kernel.increased-memory-limit` entitlement raises the per-app limit:

- **iOS 27.0.1, iPhone 17 Pro (12 GB): 8,192 MB**, measured in the October 14 and 16 smoke
  diagnostics (D-06). Peak use there was 2.1–2.6 GB on Speed, 32% of the limit (audit D).
- **iOS 26:** about 6 GB on the same phone (the historical figure in
  [`ios-engine-optimization.md`](ios-engine-optimization.md)).
- **8 GB phones under iOS 27:** unmeasured (research open question 9).

The shipping policy still assumes the older budget: the fixed 4,500 / 5,200 MiB footprint bands
(`IOSMemoryBudgetPolicy.ShippingBandMiB`) trip at about 55% and 63% of the measured limit, and
`NativeMemoryPolicyResolver` has one fixed iPhone tier (D-06). ER-07 derives the bands from measured
limits. The engine never relies on a hard MLX limit; it uses `os_proc_available_memory()` and the
pressure bands.

---

## 6. Streaming vs full-result memory

`vocello generate`, `vocello bench`, the macOS app and the iPhone app stream: codec frames are
decoded and released chunk by chunk. The full-result path (`--no-stream`) accumulates every frame
and decodes once at the end; it is a CLI diagnostic.

Measured on one ~70 s Custom/Speed input (`benchmarks/OPTIMIZATION.md` §F.1, historical):

| Path | gpuAlloc peak | physFootprint |
|---|---|---|
| Full result (`--no-stream`) | ~8.0 GB | ~7.6 GB |
| Streaming | ~3.0 GB | ~3.0 GB |

The streaming peak was nearly flat with length, which is why iPhone generation is viable. Current
per-mode numbers are in `benchmarks/HISTORY.md`. The event router and the lossless PCM channel that
carry the stream are [ARCHITECTURE §4.6](../ARCHITECTURE.md#46-streaming)'s.

---

## 7. Optimization levers and measured outcomes

> **Reading the figures.** This history predates the 2026-09-12 RTF standard. Every speed figure in
> §7.2–§7.5 is the old inverted decode speedup (audio ÷ wall, higher is faster), which current
> records carry as `decodeSpeedupX`; the standard `rtf` is wall ÷ audio, lower is faster (§8.2), and
> the two never share a comparison key.

### 7.1 Where decode time goes

An `xctrace` capture of a long Custom/Speed generation (`benchmarks/OPTIMIZATION.md` §H):

| Signpost window | % of wall | GPU busy inside |
|---|---|---|
| Step Eval Flush (the per-frame submission) | 66–67% | 41–50% |
| Code Predictor Loop (graph build, 15 passes) | 13–15% | ~3–5% |
| Talker Forward (graph build) | 4–5% | ~2–5% |
| Sampling | ~1.6% | — |
| Inter-frame gap / decoder overlap | ~23% | — |

The loop is bound by kernel launches and graph building, not GPU compute: inside the step the GPU
idles about half the time waiting for small batch-1 kernels. Swift graph-build time removed converts
roughly one to one into wall time.

### 7.2 Fused code-predictor RoPE

Replacing the code predictor's hand-rolled rotate-half with `MLXFast.RoPE` removed about 600 kernel
launches per frame. On a native 8 GB M2, Custom/Speed/long:

- warm decode speedup 0.81 → 1.02 (standard `rtf` ≈ 1.23 → 0.98);
- step eval per frame 65.8 → ~50 ms; code-predictor build 16.0 → 11.3 ms.

Numerics moved by 1–2 bf16 ULPs, so the change was validated on QC rather than identity (`f3cd2aa`).

### 7.3 Sampler scratch and allocator caches

Caching dtype-keyed `-inf` rows, zero rows, EOS rows and the code predictor's pass-0 mask removed
about 17K allocations per generation. Wall time moved within noise on the Mac (0.80 → 0.81); the
allocator relief matters more on the iPhone.

### 7.4 `compile()`: quantized parameters as `inputs:` (rejected) and the pass-indexed plan (shipped)

- **Rejected:** compiling the quantized talker MLP with its packed weights as `inputs:`
  (`compile(inputs: [gate, up, down], shapeless: true)`). It ran correctly but cost about 5% warm
  decode speedup (0.80 → 0.76): declaring quantized parameters as inputs marshals their packed state
  on every call, and the cost grows with the compiled region. Re-confirmed on 0.31.6 (§Q: +0.74%
  slower on medium, 6/6 seeds).
- **Shipped:** the pass-indexed code-predictor plan (§4.2), which owns its K/V buffers instead of
  marshalling them. Its same-day A/B measured +8.3% to +10.6% warm decode speedup; the evidence stays
  classed `diagnostic` until a clean canonical matrix upgrades it.

### 7.5 KV cache alternatives

The production talker KV cache is the unbounded bf16 `KVCacheSimple` (§4.1). Two alternatives are
internal-diagnostics knobs only:

- **`RotatingKVCache`** (`QVOICE_TALKER_KV_WINDOW`): inert at the current token cap, because
  `maxNewTokens` is 2048 and the tested window was 2048. Never enable a window with the streaming
  text layout: the prefill holds one text token, so a window would evict text the take has not spoken
  yet (A-05).
- **`QuantizedKVCache`** (`QVOICE_TALKER_KV_QUANT=8|4`): saved about 271 MB of physical footprint on
  clone/long but cost 8.6% decode speedup, because the dequantization kernels add launches.

### 7.6 The 0.6B variant: ruled out

The 0.6B models were considered as an iPhone speed and footprint lever and **ruled out by maintainer
decision (2026-07-02)**: Voice Design exists only at 1.7B, and Vocello ships one model family
(1.7B Speed 4-bit / Quality 8-bit) across all three modes. Do not reopen it without a new maintainer
decision. [`ios-engine-optimization.md`](ios-engine-optimization.md) is historical background.

---

## 8. Profiling and telemetry

### 8.1 `os_signpost` and `xctrace`

The decode loop emits these intervals: Talker Forward, Code Predictor Loop and Code Predictor Step,
Sample First Codebook and Sample Predicted Codebook, Codec Embedding Assembly, Step Eval Flush,
Token Read, EOS Read, Audio Decoder, Audio Chunk Eval and Audio Chunk Flush.

Use the repository profile lane, which launches or attaches by exact PID, requires tracer success and
validates the trace's table of contents:

```sh
scripts/macos_test.sh profile custom:speed:
```

Tracing costs about 25%, so compare fractions, not absolute times.

### 8.2 Reading Vocello telemetry

With telemetry on (`QWENVOICE_DEBUG=1` or `QWENVOICE_NATIVE_TELEMETRY_MODE`), each generation writes
a row to `diagnostics/engine/generations.jsonl` under the app's data root. The MLX-relevant fields:

- `timingsMS.qwen_*`: the Swift-side wall-clock breakdown of the decode loop;
- `mlxMemoryByStage`: MLX active, cache and peak memory at stage boundaries;
- `chunkTimeline`: per-chunk sub-stage timings (streaming only);
- `derivedMetrics.realTimeFactor`: **RTF**, request wall ÷ audio (lower is faster); benchmark
  records publish it as `rtf` and declare `run.rtfDefinition` (`wall/audio`) since 2026-09-12;
- `derivedMetrics.audioSecondsPerWallSecond`: the decode-loop speedup (higher is faster), carried as
  `decodeSpeedupX` and never called RTF;
- `derivedMetrics.tokensPerSecond`;
- the sampler-cadence and process-resource summaries.

```sh
python3 - "<diagnostics dir>" <<'PY'
import json, sys
row = json.loads(open(sys.argv[1] + "/engine/generations.jsonl").read().splitlines()[-1])
print("RTF:", row.get("derivedMetrics", {}).get("realTimeFactor"))
print({k: v for k, v in sorted(row.get("timingsMS", {}).items()) if k.startswith("qwen_")})
PY
```

The full schema and the benchmark recipes are in
[`telemetry-and-benchmarking.md`](telemetry-and-benchmarking.md).

---

## 9. Version pins and safe upgrade procedure

### 9.1 Current pins

| Package | Pin | Declared in |
|---|---|---|
| `mlx-swift` | exact **0.32.3** (never 0.32.2, which crashes at launch below iOS 26.4) | `project.yml`, `Packages/VocelloQwen3Core/Package.swift` |
| `mlx-swift-lm` | exact **3.32.3** | `Packages/VocelloQwen3Core/Package.swift` |
| `swift-transformers` | exact **1.3.5** (the package links only its `Hub` and `Tokenizers` products, F-11) | `Packages/VocelloQwen3Core/Package.swift` |
| `swift-huggingface` | exact **1.0.0** (model download transport) | `project.yml`, `Packages/VocelloQwen3Core/Package.swift` |
| `GRDB.swift` | exact **7.10.0** (app only) | `project.yml` |

Both lock files resolve these versions: `Packages/VocelloQwen3Core/Package.resolved` and
`QwenVoice.xcodeproj/project.xcworkspace/xcshareddata/swiftpm/Package.resolved`.
`config/swift-dependency-update-policy.json` binds the five pins to their declarations and lock
files, and §9.4 watches them.

Couplings:

- The mlx pair moves together.
- swift-huggingface 1.x needs swift-transformers 1.3.5 or newer (1.3.3 capped it below 1.0), so
  those two move together (F-19). Review the swift-transformers pin in every mlx move: tokenizer
  behaviour is engine behaviour.
- The clone-artifact identity names the mlx-swift build
  (`Qwen3TTSVoiceClonePrompt.mlxNumericsVersion`, `Qwen3TTS.swift:798`, F-06), and
  `scripts/qwen3_core_contract.py` fails when it differs from the pin. An mlx-swift move therefore
  rebuilds every saved voice's prompt once.

mlx-swift 0.31 and later ship a `CudaBuild` build-tool plugin that cannot be fingerprint-approved
headlessly; `xcb_run` (`scripts/lib/build_cache.sh`) passes `-skipPackagePluginValidation`
unconditionally, with the reviewed justification in its header.

### 9.2 When to upgrade

Only when:

- a security or correctness fix requires it (CONV-21 moved for #3523's catchable command-buffer
  errors);
- a model change needs an MLX feature 0.32.3 lacks;
- a measured performance win is proven on the Qwen3-TTS backend.

### 9.3 Upgrade procedure

1. Obtain explicit maintainer authorization, confirm the checkout is on `main`, and require the
   pin-owned files to be clean.
2. Move every pin site and lock file in one change, as CONV-21 (`57196483`) did:
   - `project.yml` (mlx-swift, swift-huggingface) and `Packages/VocelloQwen3Core/Package.swift`
     (all four);
   - both `Package.resolved` files;
   - `Packages/VocelloQwen3Core/COMPATIBILITY.json` and `config/swift-dependency-update-policy.json`;
   - `mlxNumericsVersion` for an mlx-swift move (§9.1);
   - the attributions (`scripts/attribution_manifest.py rebuild`) and the entitlement exception
     review in `config/macos-entitlement-policy.json`.
3. Regenerate the project (`./scripts/regenerate_project.sh`; `--verify` also runs the contract
   gate) and the package inventories (`python3 scripts/qwen3_core_contract.py
   rebuild-current-inventory`).
4. Build both foundation targets (`./scripts/build_foundation_targets.sh macos` and `ios`), then
   `scripts/dev.sh check`; `scripts/dev.sh ci` reproduces push CI serially, TSan included.
5. Re-record `testSeededSamplerGoldenTokens` only if the draws changed on purpose, and add a seed
   line to the release notes.
6. Measure on a quiet host with the optimized CLI (`scripts/build.sh cli-optimized`):
   - the gate bench (`scripts/macos_test.sh gate`): seeded, medians of five warm takes against a
     baseline pooled from at least three seeded runs on one clean commit; a loaded or throttled host
     is inconclusive (exit 3). When the toolchain has moved since the committed baseline, run a
     same-host A/B and re-pool, as CONV-21 did (`20496dc4`);
   - Mac memory qualification;
   - a `qc-takes` screen with standard, clone and long-form cells.

   Compare `rtf` (wall ÷ audio, declared through `run.rtfDefinition`) with the nearest compatible
   record in `benchmarks/HISTORY.md`; `decodeSpeedupX` never shares a comparison key with it, and
   `toolchain.optimization` comes from the hash-bound build receipt.
7. Require the applicable automated language and prosody evidence, naming the recognizer family
   (Apple Speech in the iPhone app; QC v2's Qwen3-ASR and Whisper large-v3 on the Mac,
   `qc.py language-bench`; two families for consensus). Listening is optional annotation.
8. Keep the move only if `rtf`, memory and audio QC are unchanged or improved; otherwise record the
   blocker and revert.
9. Queue the iPhone checks (smoke, memory benchmark) for the next announced device window.

### 9.4 Scheduled release and advisory watch

Dependabot cannot cover the root XcodeGen manifest, so
`.github/workflows/swift-dependency-watch.yml` compares all five exact pins weekly, read-only,
against stable GitHub releases and the repository's open Dependabot alerts. It uploads a 14-day
JSON/Markdown proposal and never edits a pin, opens a pull request or treats availability as
compatibility. Validate the policy binding locally:

```sh
python3 scripts/swift_dependency_updates.py validate
```

A proposal is only a review input; authorization and §9.3 still apply.

### 9.5 What the 0.32.3 move changed

- **Errors became catchable** (#3523, §2.6).
- **Seeds draw differently** (#4177, F-02, §4.5).
- **Kernels compile at first use.** The first cold run after the move paid a one-time Metal compile:
  prewarm 6.5 s instead of 0.2 s, and about 1.6 s more before the first take's first chunk; later
  processes reused the system's Metal cache (`20496dc4`). Prewarm now runs the production sampler
  (`bf19e2c6`, §4.5); whether the iPhone's first take is entirely clean, including the talker's
  decode-step kernels, is open for the next device window.
- **The warm first chunk rose** from 146 to 155 ms on the M6 (F-04). Warm RTF (0.265 → 0.266), MLX
  peak memory and audio QC were unchanged (`benchmarks/HISTORY.md`, the 2026-10-17 gate records).
- **Not changed by the move:** the scalar-gather issue (§4.1) and the quantized-load leak (§3.5)
  remain open here.

---

## 10. Anti-patterns and engine invariants

Do not regress these without a maintainer decision:

- **No hard `Memory.memoryLimit` in production.** Use `cacheLimit`, the clears and the pressure bands.
- **No Quality→Speed OOM fallback.** The iPhone is Speed-only by contract; load the chosen variant and
  surface the real error.
- **MLX work runs inside an error scope, and every `asArray` readback follows `evalForReadback`**
  (§2.6).
- **Keep MLX callers single-flight** (§4.2).
- **No talker KV quantization by default** (§7.5), and **no talker KV window with the streaming text
  layout** (A-05).
- **No `compile()` that declares quantized parameters as `inputs:`** (§7.4). The pass-indexed
  code-predictor plan is the shipped exception and must keep matching the eager path within
  tolerance (`Qwen3CodePredictorCompiledTests`).
- **An mlx-swift move changes `mlxNumericsVersion`** in the same change (§9.1).
- **No output-side silence gating.** Suppressing natural pauses masks real defects.
- **Do not revert the input-side decoder-drift fix (`4fab110`).**
- **Do not pipeline the 15-pass code-predictor loop.** It is autoregressive; pipelining would change
  sampling semantics.
- **Do not reintroduce `bufferingNewest` for product events** (ARCHITECTURE §4.6).
- **Streaming-first** on the iPhone, the macOS app and the CLI; `--no-stream` is an explicit CLI
  diagnostic.

---

## 11. Quick reference

### Key MLX and mlx-swift types

| Type | Module | Purpose |
|---|---|---|
| `MLXArray` | `MLX` | n-dimensional array |
| `Module` | `MLXNN` | base class for layers |
| `QuantizedLinear` | `MLXNN` | low-bit weight-only linear layer |
| `Quantizable` | `MLXNN` | `toQuantized(groupSize:bits:mode:)` |
| `QuantizationMode` | `MLX` | Vocello uses `.affine` |
| `MLXFast.scaledDotProductAttention` | `MLX` | fused attention |
| `MLXFast.RoPE` | `MLX` | fused rotary embedding |
| `KVCacheSimple` | `MLXLMCommon` | unbounded KV cache in the compute dtype (bf16) |
| `RotatingKVCache` | `MLXLMCommon` | sliding-window KV cache (diagnostic) |
| `QuantizedKVCache` | `MLXLMCommon` | 4/8-bit KV cache (diagnostic) |
| `Memory.cacheLimit` | `MLX` | buffer-pool cap |
| `Memory.memoryLimit` | `MLX` | hard ceiling (not used in production) |
| `Memory.snapshot()` | `MLX` | active, cache and peak memory |

### Environment variables

`config/runtime-debug-knobs.json` is authoritative. Every production-affecting override below is
read through `RuntimeDebugGate` and needs both a repository-owned internal diagnostics build and
`QWENVOICE_DEBUG=1`; distributed builds omit that capability. Owned-package knobs
(`QVOICE_TALKER_KV_QUANT`, `QWENVOICE_TOKENIZER_RESIDENCY`) are resolved once per model load, only
when the product attests the capability through `VocelloQwen3LoadBehavior`. Telemetry keeps
override key names and a digest, never raw values.

| Variable | Effect |
|---|---|
| `QWENVOICE_DEBUG=1` | Use the `QwenVoice-Debug` data folder and enable telemetry. |
| `QWENVOICE_NATIVE_TELEMETRY_MODE=verbose` | Write raw per-sample memory sidecars. |
| `QWENVOICE_FORCE_MEMORY_CLASS=8gb\|16gb\|high\|iphone` | Force a memory tier (raw values such as `floor_8gb_mac` work too). |
| `QWENVOICE_SIMULATED_PHYSICAL_MEMORY_GB=8` | Emulate a smaller Mac (tier, footprint bands, Metal working set); policy and footprint only. |
| `QWENVOICE_SUPPRESS_WARMUP=1` | Skip proactive warm-up to measure a true cold load. |
| `QWENVOICE_SAMPLER_FLOAT32=off` | Sample from model-precision logits (D3 off). |
| `QWENVOICE_TALKER_FILTER_EOS=off` | Re-insert EOS after the filters (D2 off). |
| `QWENVOICE_TOKENIZER_RESIDENCY` | Override speech-tokenizer residency. |
| `QVOICE_TALKER_KV_WINDOW=<n>` | Sliding-window talker KV cache. |
| `QVOICE_TALKER_KV_QUANT=4\|8` | Quantized talker KV cache. |
| `QVOICE_IOS_MLX_CACHE_LIMIT_MB=<n>` | Override the iPhone MLX cache limit. |
| `QVOICE_IOS_MLX_MEMORY_LIMIT_MB=<n>` | Set a hard iPhone MLX memory limit (never in production). |
| `QWENVOICE_STREAMING_PREVIEW_DATA=off` | Skip inline PCM preview chunks. |

### Common commands

```sh
# Build and run with telemetry
QWENVOICE_DEBUG=1 ./scripts/build.sh run

# Bench a full matrix
QWENVOICE_DEBUG=1 ./build/vocello bench --modes custom,design,clone \
  --variants speed,quality --lengths short,medium,long --warm 3

# Force constrained-tier behaviour on a development Mac
QWENVOICE_DEBUG=1 QWENVOICE_FORCE_MEMORY_CLASS=floor_8gb_mac \
  QWENVOICE_SUPPRESS_WARMUP=1 ./scripts/build.sh run

# Summarize one authoritative benchmark run
python3 scripts/summarize_generation_telemetry.py <diag-dir> \
  --run-id <run-id> --evidence-manifest <run-artifact-dir>/benchmark-evidence.json

# Capture and validate Instruments evidence (the raw trace is deleted after publication
# unless --keep-trace is explicit)
scripts/macos_test.sh profile custom:speed:
```

---

## 12. Sources and further reading

- MLX: [repository](https://github.com/ml-explore/mlx), [compilation](https://ml-explore.github.io/mlx/build/html/usage/compile.html),
  [`nn.quantize`](https://ml-explore.github.io/mlx/build/html/python/_autosummary/mlx.nn.quantize.html),
  ["Writing Fast MLX"](https://gist.github.com/awni/4beb1f7dfefc6f9426f3a7deee74af50)
- [mlx-swift](https://github.com/ml-explore/mlx-swift) and [mlx-swift-lm](https://github.com/ml-explore/mlx-swift-lm)
- MLX issues and pull requests cited here: [#3523](https://github.com/ml-explore/mlx/pull/3523)
  (command-buffer errors), [#4177](https://github.com/ml-explore/mlx/pull/4177) (inverse-CDF
  categorical), [#4710](https://github.com/ml-explore/mlx/pull/4710) (load leak); mlx-swift
  [#461](https://github.com/ml-explore/mlx-swift/pull/461) (compiled-function deadlock)
- [mlx-audio-swift](https://github.com/Blaizzy/mlx-audio-swift) (PR [#286](https://github.com/Blaizzy/mlx-audio-swift/pull/286))
  and [mlx-audio](https://github.com/Blaizzy/mlx-audio) (issue [#851](https://github.com/Blaizzy/mlx-audio/issues/851))
- [Qwen3-TTS on Hugging Face](https://huggingface.co/Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice)
- Vocello: the [engine runtime audit](../audits/2026-10-16-engine-runtime-audit.md), the
  [Qwen3-TTS model research](../audits/2026-10-17-qwen3-tts-model-research.md),
  [`telemetry-and-benchmarking.md`](telemetry-and-benchmarking.md),
  [`benchmarks/OPTIMIZATION.md`](../../benchmarks/OPTIMIZATION.md) and
  [`benchmarks/HISTORY.md`](../../benchmarks/HISTORY.md)
