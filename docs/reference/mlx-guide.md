# MLX Guide for Vocello

> **Living document.** A project-specific reference for the MLX runtime, the Qwen3-TTS backend, and the optimization decisions that shape Vocello's macOS/iOS engine. When this doc disagrees with the code, the code wins — fix this file.
>
> Last reviewed: 2026-08-01. Shipping pins: `mlx-swift` **0.31.6**, `mlx-swift-lm` **3.31.4**, `swift-transformers` **1.1.9** (direct since the lm 3.x Hub/Tokenizers externalization).

---

## 1. Why MLX?

Vocello synthesizes speech entirely on-device using **Qwen3-TTS** models. The runtime is Apple's **[MLX](https://github.com/ml-explore/mlx)** framework, accessed through the Swift packages [`mlx-swift`](https://github.com/ml-explore/mlx-swift) and [`mlx-swift-lm`](https://github.com/ml-explore/mlx-swift-lm). The lower-level audio/TTS model implementation is the owned [`VocelloQwen3Core`](../../Packages/VocelloQwen3Core/README.md) package, derived from [`mlx-audio-swift`](https://github.com/Blaizzy/mlx-audio-swift).

MLX was chosen because it is designed for Apple Silicon:

- **Unified memory** — CPU, GPU, and Neural Engine share the same physical memory pool. Model weights and KV caches are accessible to the GPU without PCIe copies.
- **Lazy evaluation** — operations build a computation graph that is only executed when results are needed, enabling fusion and reducing allocator churn.
- **Native quantization** — 4-bit and 8-bit weight-only quantization is a first-class path, which is how Vocello ships Speed (4-bit) and Quality (8-bit) variants.
- **Swift-native API** — `mlx-swift` exposes arrays, modules, and device/memory controls directly to the app and CLI, with no Python runtime in the shipping binary.

---

## 2. Core MLX concepts

### 2.1 `MLXArray`

The fundamental type is `MLXArray` (imported from `MLX`). It is a multi-dimensional tensor. Arrays have a dtype, a shape, and live in unified memory. They can be created from scalars, buffers, or NumPy-like constructors:

```swift
import MLX

let a = MLXArray([1, 2, 3, 4])
let b = MLXArray([1.0, 2.0, 3.0, 4.0])
let c = a + b          // still lazy
```

### 2.2 Lazy evaluation

MLX operations do not run immediately. They build a graph of primitives. The graph is materialized only when an array is **evaluated** or its value is read. This is the single most important behavior for performance work:

```swift
let c = a + b          // no GPU work yet
mx.eval(c)             // c is now materialized
```

Common evaluation triggers:

- `eval(...)` / `asyncEval(...)` — explicit evaluation.
- `.item(...)` — reading a scalar forces evaluation.
- Printing, converting to `Data`, or copying to CPU buffers.
- Sampling operations that need a token value from the GPU.

Because evaluation is lazy, many small operations can be fused into fewer GPU kernels. But it also means wall-clock timers around graph construction (the Swift CPU time spent building `MLXArray` expressions) are distinct from the GPU time spent executing them. Vocello's telemetry captures both.

### 2.3 `eval()` vs `asyncEval()`

| API | Behavior | When to use |
|---|---|---|
| `eval(_:)` | Blocks the calling thread until the graph is complete. | Simple synchronous scripts; be careful on the main/UI thread. |
| `asyncEval(_:)` | Enqueues work and returns immediately; the caller can continue building the next graph while the GPU executes the previous one. | Autoregressive decode loops where the next token's graph can be prepared in parallel with the current token's execution. |

Vocello's decode loop uses `asyncEval` for the audio decoder so that `code2wav` work overlaps the next token's talker/code-predictor graph. This is why the telemetry `code2wav` timing is often near zero on the CPU timeline — it ran in the background while the CPU was busy with the token loop.

### 2.4 Streams and devices

MLX operations run on a **stream**. The default stream is the GPU (`DeviceType.gpu`). You can also use `DeviceType.cpu` for parts of a model that are cheaper on the CPU, or to overlap CPU preprocessing with GPU compute:

```swift
let onGPU = matmul(a, b, stream: .gpu)
let onCPU = exp(c, stream: .cpu)
```

In practice Vocello keeps the hot path on the GPU stream; CPU streams are used for audio preprocessing and metadata plumbing.

### 2.5 Unified memory

On Apple Silicon, `MLXArray` buffers live in memory that both CPU and GPU can access. There is no explicit `.to(device:)` call. The benefit is zero-copy data movement; the risk is that GPU allocations, CPU allocations, and OS memory pressure all compete for the same physical RAM. This is why Vocello's iOS memory policy is built around `os_proc_available_memory()` and `physFootprint`, not a traditional "GPU memory" reading.

---

## 3. Quantization and model loading

### 3.1 Weight-only affine groupwise quantization

Vocello ships two weight variants:

| Variant | Bits | Group size | Use case |
|---|---|---|---|
| **Speed** | 4 | 64 | macOS + iOS; smaller, faster, default on iPhone. |
| **Quality** | 8 | 64 | macOS only; larger, slightly higher fidelity. |

The quantization scheme is **affine weight-only quantization**. Each group of 64 weights is stored as 4-bit (or 8-bit) integers plus a per-group scale and bias. At runtime, the GPU dequantizes the weight group on demand inside the matrix-multiplication kernel. The activations stay in fp16/bf16.

This matches MLX's `QuantizationMode.affine` (still the default in `mlx-swift` 0.31.6). Newer MLX versions also support `nvfp4` and `mxfp8`, but those are not used by Vocello's Qwen3-TTS checkpoints.

### 3.2 Swift API for quantization

In Python MLX:

```python
import mlx.nn as nn
nn.quantize(model, group_size=64, bits=4, mode="affine")
```

In `mlx-swift` 0.31.6, a `Module` conforming to `Quantizable` exposes:

```swift
func toQuantized(groupSize: Int, bits: Int, mode: QuantizationMode) -> Module
```

`QuantizedLinear` stores:

```swift
let weight: MLXArray      // packed low-bit weights
let scales: MLXArray      // per-group scale
let biases: MLXArray?     // per-group bias (optional in newer APIs)
let groupSize: Int
let bits: Int
let mode: QuantizationMode
```

### 3.3 The 0.31.x API change (why Vocello stays pinned)

`mlx-swift` 0.31.x introduced breaking changes to the quantization surface:

- `Quantizable.toQuantized(groupSize:bits:)` gained a `mode: QuantizationMode` parameter.
- `quantize(model:groupSize:bits:)` moved to a top-level function with a `mode:` argument.
- The `biases` result from `quantized()` became optional.

Vocello Qwen3 Core was written against the 0.30.x API. The 2026-08-01 sanctioned bump to **0.31.6 / 3.31.4** followed the required process — throwaway branch, lockstep across `project.yml` and `Packages/VocelloQwen3Core/Package.swift`, fixed-seed `vocello bench` A/B against a same-day 0.30.6 control, clean audioQC — and measured warm RTF inside the noise band with byte-equal clone durations (`benchmarks/OPTIMIZATION.md` §Q). Any future upgrade repeats that process; the quantization call sites compiled unchanged across the 0.31 API revision.

### 3.4 Loading weights

Models are downloaded from the Hugging Face `mlx-community` repos listed in `Sources/Resources/qwenvoice_contract.json`. Weights are stored as `.safetensors` and loaded into the owned Qwen3-TTS model. The load path:

1. Resolve the model ID from the contract.
2. Download / verify the package via `SwiftHuggingFace`.
3. Load `*.safetensors` into `MLXArray` dictionaries.
4. Call the model initializer, which maps weights into `Linear`, `Embedding`, `LayerNorm`, `RMSNorm`, etc.
5. If the variant is Speed/Quality, the checkpoint is already quantized; the model constructs `QuantizedLinear` layers from the packed weights, scales, and biases.

---

## 4. Qwen3-TTS decode loop anatomy

Understanding the per-frame loop is essential for optimization work. The owned Qwen3-TTS model in `Packages/VocelloQwen3Core/Sources/MLXAudioTTS/Models/Qwen3TTS/` has three main stages.

### 4.1 Talker (language model)

The talker is a small LLM that predicts the next audio-codebook token conditioned on:

- text tokens,
- speaker embedding (built-in speaker or cloned reference),
- delivery/prompt embedding,
- previously generated audio tokens.

Key implementation details:

- **Interleaved MRoPE** `[24, 20, 20]` — multi-dimensional rotary position embeddings that separate time, codebook, and text positions.
- **`MLXFast.scaledDotProductAttention`** — fused attention on supported shapes.
- **fp16 KV cache** by default (`KVCacheSimple`).
- The talker runs one forward pass per generated audio frame.

### 4.2 Code Predictor

For each frame, the talker emits a first codebook token. A 15-pass code predictor then fills the remaining codebooks. This is a tight, autoregressive loop over codebook dimension:

```
frame 0: talker -> cb0
         code predictor -> cb1 .. cb15
frame 1: talker -> cb0
         code predictor -> cb1 .. cb15
...
```

Historically the code predictor used a hand-rolled RoPE (rotate-half). Vocello replaced it with **`MLXFast.RoPE`**, which reduced the number of kernel launches per frame and improved RTF by ~26% on the native 8 GB Mac (the largest single backend win to date).

### 4.3 Audio decoder (Mimi codec)

The Mimi neural codec converts generated audio-codebook frames into a 24 kHz PCM waveform. In the **full-result path**, all frames are accumulated and decoded once at the end. In the **streaming path**, a chunk of frames is emitted and decoded periodically, releasing memory as it goes.

The decoder uses input-side overlap-and-discard (`inputContext`) to avoid chunk-boundary discontinuities. Do not revert to output-side accumulation.

### 4.4 Sampling

Sampling algorithm v2 resolves one immutable `VocelloQwen3SamplingConfiguration` per request.
Every request has a recorded effective seed and owns a fresh `MLXRandom.RandomState`; all talker and
Code Predictor categorical draws run under that state and do not advance MLX's process-global RNG.
Talker and subtalker stages have independent temperature, top-k, top-p, and min-p values. The
subtalker never inherits repetition penalty. The order matters: Vocello applies temperature scaling
before top-p/min-p truncation. Talker defaults are:

- temperature `0.9`
- topK `50`
- topP `1.0` (nucleus off)
- repetitionPenalty `1.05`
- minP `0.0`

Debug-gated environment values may be used for A/B experiments
(`QWENVOICE_TALKER_TEMP`, `QWENVOICE_TALKER_TOPP`, etc.), but they are resolved into the request
before model invocation and are never mutable runtime authority. Sampling v2 can differ from
historical v1 byte output; promotion requires reproducibility within v2 plus the normal fixed-seed
QC and applicable ASR/prosody evidence.

### 4.5 The single per-frame `eval()`

The most important performance invariant in the loop is that **one fused `eval()` is issued per generated frame**. The talker forward, code predictor loop, and sampling are built into one graph, then `eval()` flushes it to the GPU. There is no per-step `.item()` read inside the loop; the EOS flag is read after the `eval()` returns. This minimizes CPU↔GPU synchronization.

---

## 5. Memory management

### 5.1 `Memory.cacheLimit` and `Memory.memoryLimit`

`mlx-swift` exposes two knobs for controlling the Metal backend's memory behavior:

```swift
import MLX

Memory.cacheLimit = 256 * 1024 * 1024   // 256 MB
Memory.memoryLimit = 6 * 1024 * 1024 * 1024 // 6 GB (use with caution)
```

- **`Memory.cacheLimit`** — the amount of GPU memory MLX is allowed to keep in its internal buffer pool for reuse. A larger cache speeds up repeated allocations; a smaller cache reduces steady-state footprint. This is Vocello's primary memory-control lever.
- **`Memory.memoryLimit`** — a hard ceiling on total GPU memory use. If a graph would exceed the limit, MLX can either block or fail. On Apple Silicon this interacts poorly with the real OS memory-pressure/Jetsam system because it over-promises available headroom.

### 5.2 Why Vocello avoids a hard `Memory.memoryLimit`

The project explicitly **does not set a hard `Memory.memoryLimit` in production**. Early experiments set a 6 GB floor-8GB cap and a 5 GB iPhonePro cap, but they caused spurious OOM downgrades during cold-load peaks because the limit was lower than the actual Jetsam ceiling. The policy was reverted in commit `b77c08e`.

Instead, the engine gates behavior on:

- `Memory.cacheLimit` (per-tier, small on iPhone).
- Explicit cache clears at generation and chunk boundaries.
- `os_proc_available_memory()` on iOS for admission/pressure decisions.
- `physFootprint` / `Memory.snapshot()` telemetry for post-hoc analysis.

### 5.3 Per-tier memory policy

`NativeMemoryPolicyResolver` (`Sources/QwenVoiceCore/NativeMemoryPolicyResolver.swift`) picks a policy based on device class:

| Device class | Cache limit | Clear after generation | Clear on chunk | Token clear cadence | Idle unload |
|---|---|---|---|---|---|
| `floor8GBMac` | 256 MB | single-shot only | yes | 50 tokens | 120 s |
| `mid16GBMac` | 512 MB | no | yes | 50 tokens | 600 s |
| `highMemoryMac` | 1 GB | no | no | 200 tokens | never |
| `iPhonePro` | 128 MB | always | yes | 50 tokens | 30 s |

These numbers are the result of on-device and constrained-tier benchmarking. They are not derived from a formula; changing them requires re-measuring RTF and peak memory on real hardware.

MLX allocator limits remain process-wide API state and are applied at the host boundary. The
request-varying Qwen behavior is different: `NativeMemoryPolicyResolver` creates an immutable
`VocelloQwen3MemoryConfiguration`, which the facade converts into a `Qwen3RequestMemoryPolicy`
carried by Custom, Design, and Clone calls. A generation cannot change another request's cache-clear
cadence or talker KV window.

### 5.4 Cache clearing cadence

The engine clears MLX's internal caches at three points:

1. **Per-generation** on constrained tiers (`floor8GBMac` single-shot, `iPhonePro` always).
2. **Per-streaming-chunk** when `clearMLXCacheOnStreamChunkEmit` is true. This is the main reason the iOS streaming peak stays flat.
3. **Per-N tokens** via the request's `tokenMemoryClearCadence`. The token loop calls
   `clearCache()` every N generated tokens to release transient allocator buffers.

Over-clearing can hurt RTF by forcing the allocator to re-create buffers; under-clearing can push peak memory up. The 50-token cadence was chosen empirically.

### 5.5 iOS memory specifics

On iOS the engine runs **in-process** inside the app. The app and the engine share one Jetsam budget. The entitlement `com.apple.developer.kernel.increased-memory-limit` raises the per-app ceiling (measured at ~6 GB on iPhone 17 Pro, ~5–5.5 GB on 8 GB devices). The engine never relies on a hard MLX limit; it uses `os_proc_available_memory()` and the pressure bands in `IOSMemoryBudgetPolicy`.

---

## 6. Streaming vs full-result memory

`vocello bench` and `vocello generate` now use a **streaming-first** pipeline by default on macOS: chunks of codec tokens are emitted, decoded, and released as generation proceeds. The legacy **non-streaming, full-result** path (accumulates all tokens, decodes once at the end) is still available with `--no-stream`; it uses more peak memory.

The iOS app path is also **streaming-first**.

Measured on the same ~70 s custom/Speed input (`benchmarks/OPTIMIZATION.md` §F.1):

| Path | gpuAlloc peak | physFootprint |
|---|---|---|
| Non-streaming (`--no-stream`) | ~8.0 GB | ~7.6 GB |
| Streaming (CLI default / iOS path) | ~3.0 GB | ~3.0 GB |

The streaming peak is **flat with length** — short, medium, and long inputs all peak around 3 GB. This is why iPhone generation is viable despite the lower device RAM.

### 6.1 Core audio and frontend events use different suspending contracts

`MLXTTSEngine.events` is an `AsyncStream` view over a custom per-generation suspending router:

- **macOS**: capacity 256.
- **iOS**: capacity 96 to stay bounded under the shared-process budget.

`GenerationEventDeliveryProbe` records accepted, terminated, and unobserved sends. A full router
suspends the producer until the sole consumer advances; preview/status events are never evicted.

Final PCM uses `ClassifiedGenerationSession`'s separate single-consumer, frame-bounded suspending
audio channel for Custom, Design, and Clone. Cancelling a producer task while it is suspended on
backpressure removes the pending send and wakes the producer with `CancellationError`.
`GenerationOutputAdapter` writes every drained frame before frontend publication and completes the
product-finalization acknowledgment. Do not reintroduce `bufferingNewest` or another eviction
policy for audio-bearing product events.

---

## 7. Optimization levers and measured outcomes

### 7.1 Decode breakdown (where time goes)

An `xctrace` capture of a long custom/Speed generation (Vocello P0, `benchmarks/OPTIMIZATION.md` §H) showed:

| Signpost window | % of wall | GPU busy inside |
|---|---|---|
| Step Eval Flush (single fused `eval()` per frame) | 66–67% | 41–50% |
| Code Predictor Loop (graph build, 15 passes) | 13–15% | ~3–5% |
| Talker Forward (graph build) | 4–5% | ~2–5% |
| Sampling | ~1.6% | — |
| Inter-frame gap / decoder overlap | ~23% | — |

**Interpretation:** the workload is **kernel-launch / graph-build bound**, not GPU-bound. Even inside the fused `eval()`, the GPU idles roughly half the time waiting for small batch-1 kernels to be launched. Every millisecond of Swift graph-build time removed converts roughly 1:1 to wall time.

### 7.2 Fused Code-Predictor RoPE (+26% RTF)

Replacing the hand-rolled rotate-half RoPE in the code predictor with `MLXFast.RoPE` eliminated ~600 kernel launches per frame. On a native 8 GB M2:

- custom/speed/long warm RTF: **0.81 → 1.02**
- stepEval/frame: 65.8 ms → ~50 ms
- codePred build: 16.0 ms → 11.3 ms

Numerics shifted by 1–2 bf16 ULPs (a precision improvement, not identical tokens), so the change was validated with `audioQC` pass + listening pass. This was the largest backend win in the Qwen3-specialization program (`f3cd2aa`).

### 7.3 Sampler scratch / allocator caches (~+1% wall)

Cacheing dtype-keyed `-inf` rows, zero rows, EOS rows, and the code-predictor pass-0 mask removed ~17K allocations per generation. The wall-time gain is within noise on Mac (RTF 0.80 → 0.81), but the allocator-pressure reduction matters on iPhone.

### 7.4 `compile()` on the quantized per-frame graph (tested and rejected)

Compiling the quantized talker MLP with `compile(inputs: [gate, up, down], shapeless: true)` built and ran correctly, but it **regressed warm RTF by ~5%** (0.80 → 0.76). The reason: declaring quantized parameters as `inputs:` forces `compile` to marshal their packed state (weights, scales, biases) on every call, costing more than the Swift build overhead it removes. This cost scales with the compiled region, so compiling a larger region would regress more.

**Lesson:** on MLX 0.30.6, `compile()` is not a free win for small, quantized, autoregressive graphs. Re-confirmed on 0.31.6 by the P1b re-test and its paired 6-seed soak (§Q: +0.74% slower on medium, 6/6 seeds).

### 7.5 KV cache options

Vocello's default talker KV cache is unbounded `KVCacheSimple` in fp16. Two alternatives were evaluated:

- **`RotatingKVCache` (sliding window)** — implemented and validated, but **inert at the current token cap**. `maxNewTokens` is 2048 and the window was 2048, so the cache never rotates. It is kept as an env-only override (`QVOICE_TALKER_KV_WINDOW`) for future token-ceiling increases.
- **`QuantizedKVCache` (8-bit / 4-bit)** — saves ~271 MB physical footprint on clone/long, but costs **−8.6% RTF** because dequant kernels add overhead on a launch-bound decode. It is kept as a dev-only knob (`QVOICE_TALKER_KV_QUANT=8|4`), default off.

Neither is shipped on any tier because the iOS streaming peak is already ~3 GB and 0 trims.

### 7.6 The 0.6B variant — ruled out

The smaller **0.6B Qwen3-TTS** variant was considered as the next iPhone RTF/footprint
lever but **ruled out by maintainer decision (2026-07-02)**: Voice Design is only
available on the 1.7B model, and Vocello ships one model family (1.7B Speed 4-bit /
Quality 8-bit) across all three modes. It is off the roadmap — do not re-open without
a new maintainer decision. iPhone speed work targets the 1.7B variants only
(benchmark-gated mlx-swift bumps, kernel-level work — see
[`ios-engine-optimization.md`](ios-engine-optimization.md) §9).

---

## 8. Profiling and telemetry

### 8.1 `os_signpost` and `xctrace`

The owned Qwen3-TTS decode loop emits `os_signpost` intervals:

- "Talker Forward"
- "Code Predictor Loop" / "Code Predictor Step"
- "Step Eval Flush"
- "Audio Decoder"
- "Sample First Codebook" / "Sample Predicted Codebooks"

Prefer the repository profile lane, which launches or attaches by exact PID, requires tracer
success, and validates the trace table of contents:

```sh
scripts/macos_test.sh profile custom:speed:
```

Trace overhead is ~25%, so compare fractions, not absolute RTF.

### 8.2 Reading Vocello telemetry

When telemetry is on (`QWENVOICE_DEBUG=1` or the debug toggle), each generation writes rows to `diagnostics/engine/generations.jsonl`. The key fields for MLX work are:

- `timingsMS.qwen_*` — Swift-side wall-clock breakdown of the decode loop.
- `mlxMemoryByStage` — `active` / `cache` / `peak` GPU memory at stage boundaries.
- `chunkTimeline` — per-chunk substage timings (streaming only).
- `derivedMetrics.audioSecondsPerWallSecond` — **RTF** (>1 = faster than realtime).
- `derivedMetrics.tokensPerSecond` — token throughput.
- `summary.targetIntervalNS` / `effectiveIntervalNS` / `maximumDriftNS` / `maximumLatenessNS` — sampler cadence, observed interval, and anchored scheduling phase error/lateness.
- `summary.missedPeriodicDeadlineCount` — cadence deadlines skipped instead of issuing misleading burst catch-up samples.
- `summary.boundarySampleCount` / `processResourceUsage` — lifecycle snapshots and owning-process CPU/fault/switch/I/O deltas.

Example one-liner to read the latest engine row:

```sh
python3 - <<'PY'
import json, os
d = os.path.expanduser("~/Library/Application Support/QwenVoice-Debug/diagnostics")
row = json.loads(open(d+"/engine/generations.jsonl").read().splitlines()[-1])
print("RTF:", row.get("derivedMetrics", {}).get("audioSecondsPerWallSecond"))
print("timingsMS:", {k: v for k, v in sorted(row.get("timingsMS", {}).items()) if k.startswith("qwen_")})
PY
```

See [`telemetry-and-benchmarking.md`](telemetry-and-benchmarking.md) for the full schema and benchmark recipes.

---

## 9. Version pins and safe upgrade procedure

### 9.1 Current pins

- `mlx-swift`: exact **0.31.6** in `project.yml` and `Packages/VocelloQwen3Core/Package.swift`
- `mlx-swift-lm`: exact **3.31.4** in `Packages/VocelloQwen3Core/Package.swift`
- `swift-transformers`: exact **1.1.9** in `Packages/VocelloQwen3Core/Package.swift` — the app-supplied
  Hub/Tokenizers implementation required since mlx-swift-lm 3.x

Move the mlx pair in lockstep; review the swift-transformers pin in the same change. Do not float one without the others. mlx-swift ≥0.31 ships a `CudaBuild` build-tool plugin that cannot be fingerprint-approved headlessly; `xcb_run` (scripts/lib/build_cache.sh) passes `-skipPackagePluginValidation` unconditionally with the reviewed justification recorded in its header.

### 9.2 When to upgrade

Only upgrade when:

- A security or correctness fix requires it.
- A new model variant requires an MLX feature not present in 0.31.6.
- A measured performance win is proven on the Qwen3-TTS backend.

### 9.3 Upgrade procedure

1. Create a throwaway branch from `main`.
2. Update both pin sites simultaneously:
   - `project.yml` → `mlx-swift` pin
   - `Packages/VocelloQwen3Core/Package.swift` → `mlx-swift-lm` and `mlx-swift` pins
3. Run `./scripts/regenerate_project.sh`.
4. Build both foundation targets:
   ```sh
   ./scripts/build_foundation_targets.sh macos
   ./scripts/build_foundation_targets.sh ios
   ```
5. Run a fixed-seed `vocello bench`; compare its generated registry entry with the nearest
   compatible clean run in `benchmarks/HISTORY.md`, and require the applicable automated
   language/prosody evidence. Optional listening may be annotated independently.
6. Keep the bump only if RTF, memory, and audioQC are unchanged or improved.
7. If anything regresses, document the blocker and revert.

### 9.4 Known 0.31.x gotchas

- `Quantizable.toQuantized` gains `mode: QuantizationMode`.
- `quantize(model:groupSize:bits:)` becomes a top-level function with `mode:`.
- `quantized()` may return optional `biases`.
- These touch the 4-bit/8-bit model-load path, so a clean build is not enough — you must re-run the full bench matrix.

---

## 10. Anti-patterns and engine invariants

Do not regress these without a maintainer decision:

- **No hard `Memory.memoryLimit` in production.** Use `cacheLimit`, explicit clears, and pressure bands.
- **No Quality→Speed OOM fallback.** iPhone is Speed-only by contract; load the chosen variant and surface the real error.
- **No TTS KV quantization by default.** It saves memory but costs RTF.
- **No `compile()` on the quantized per-frame graph.** It was measured and regressed.
- **No output-side silence gating.** Suppressing natural pauses masks real defects.
- **Do not revert the input-side decoder-drift fix (`4fab110`).**
- **Do not pipeline the 15-pass Code Predictor loop.** It is autoregressive; pipelining would change sampling semantics.
- **Do not reintroduce `bufferingNewest` for product events.** Keep the 256-event macOS and 96-event
  iOS suspending router plus delivery accounting; audio-bearing preview sends backpressure.
- **Streaming-first on iOS, the macOS app, and the macOS CLI** (`vocello generate` /
  `vocello bench`). The three macOS app coordinators set `shouldStream: true`; `--no-stream` is an
  explicit CLI diagnostic, not the app quality path.

---

## 11. Quick reference

### Key MLX / mlx-swift types

| Type | Module | Purpose |
|---|---|---|
| `MLXArray` | `MLX` | Tensor / n-dimensional array. |
| `Module` | `MLXNN` | Base class for neural network layers. |
| `QuantizedLinear` | `MLXNN` | Low-bit weight-only linear layer. |
| `Quantizable` | `MLXNN` | Protocol for `toQuantized(groupSize:bits:mode:)`. |
| `QuantizationMode` | `MLXNN` | `.affine`, `.nvfp4`, `.mxfp8`. Vocello uses `.affine`. |
| `MLXFast.scaledDotProductAttention` | `MLX` | Fused SDPA. |
| `MLXFast.RoPE` | `MLX` | Fused rotary position embedding. |
| `KVCacheSimple` | `MLXLMCommon` | Unbounded fp16 KV cache. |
| `RotatingKVCache` | `MLXLMCommon` | Sliding-window KV cache. |
| `QuantizedKVCache` | `MLXLMCommon` | 4/8-bit KV cache. |
| `Memory.cacheLimit` | `MLX` | MLX buffer-pool cap. |
| `Memory.memoryLimit` | `MLX` | Hard GPU memory ceiling (avoid in production). |
| `Memory.snapshot()` | `MLX` | Read active/cache/peak memory. |

### Environment variables

`config/runtime-debug-knobs.json` is authoritative. Every production-affecting override below is
read through `RuntimeDebugGate` and is inert unless `QWENVOICE_DEBUG=1`; bounded observability keys
such as telemetry selection are classified separately and do not change synthesis policy.

| Variable | Effect |
|---|---|
| `QWENVOICE_DEBUG=1` | Use `QwenVoice-Debug` data folder and enable telemetry. |
| `QWENVOICE_NATIVE_TELEMETRY_MODE=verbose` | Write raw per-sample memory sidecars. |
| `QWENVOICE_FORCE_MEMORY_CLASS=8gb\|16gb\|high\|iphone` | Force a constrained memory tier. |
| `QWENVOICE_SUPPRESS_WARMUP=1` | Skip proactive warmup to measure true cold load. |
| `QVOICE_TALKER_KV_WINDOW=<n>` | Enable sliding-window talker KV cache (dev). |
| `QVOICE_TALKER_KV_QUANT=4\|8` | Enable quantized talker KV cache (dev). |
| `QVOICE_IOS_MLX_CACHE_LIMIT_MB=<n>` | Override iOS MLX cache limit. |
| `QVOICE_IOS_MLX_MEMORY_LIMIT_MB=<n>` | Override iOS MLX memory limit (dev only). |
| `QWENVOICE_STREAMING_PREVIEW_DATA=off` | Skip inline PCM preview chunks on iOS. |

### Common commands

```sh
# Build and run with telemetry
QWENVOICE_DEBUG=1 ./scripts/build.sh run

# Bench a full matrix
QWENVOICE_DEBUG=1 ./build/vocello bench --modes custom,design,clone \
  --variants speed,quality --lengths short,medium,long --warm 3

# Force constrained-tier behavior on a dev Mac
QWENVOICE_DEBUG=1 QWENVOICE_FORCE_MEMORY_CLASS=floor_8gb_mac \
  QWENVOICE_SUPPRESS_WARMUP=1 ./scripts/build.sh run

# Summarize one authoritative benchmark run
python3 scripts/summarize_generation_telemetry.py <diag-dir> \
  --run-id <run-id> --evidence-manifest <run-artifact-dir>/benchmark-evidence.json

# Capture and validate Instruments evidence. The compact PASS summary is durable;
# the multi-gigabyte raw trace is deleted after publication unless --keep-trace is explicit.
scripts/macos_test.sh profile custom:speed:
```

---

## 12. Sources and further reading

- [MLX GitHub repository](https://github.com/ml-explore/mlx)
- [MLX Swift package](https://github.com/ml-explore/mlx-swift)
- [MLX Swift LM package](https://github.com/ml-explore/mlx-swift-lm)
- [MLX Compilation docs](https://ml-explore.github.io/mlx/build/html/usage/compile.html)
- [MLX `nn.quantize` docs](https://ml-explore.github.io/mlx/build/html/python/_autosummary/mlx.nn.quantize.html)
- ["Writing Fast MLX" gist (Awni Hannun)](https://gist.github.com/awni/4beb1f7dfefc6f9426f3a7deee74af50)
- [mlx-audio-swift upstream](https://github.com/Blaizzy/mlx-audio-swift)
- [Qwen3-TTS Hugging Face](https://huggingface.co/Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice)
- Vocello docs:
  - [`mlx-audio-swift-patching.md`](mlx-audio-swift-patching.md)
  - [`ios-engine-optimization.md`](ios-engine-optimization.md)
  - [`telemetry-and-benchmarking.md`](telemetry-and-benchmarking.md)
  - [`benchmarks/OPTIMIZATION.md`](../../benchmarks/OPTIMIZATION.md)
  - [`benchmarks/HISTORY.md`](../../benchmarks/HISTORY.md)
