---
status: active
owner: backend-mlx
summary: Project-specific Metal reference — how MLX uses Metal for the Qwen3 engine, memory/latency implications, and direct-Metal patterns for potential future custom kernels.
sourceOfTruth:
  - project.yml
---
# Metal Guide for Vocello

> **Living document.** A project-specific reference for Apple's Metal API and Metal performance optimization as it applies to Vocello's Qwen3-TTS engine on Apple Silicon macOS and iOS. Most GPU work today is abstracted by MLX; this doc explains how MLX uses Metal, what that means for memory and latency, and the direct-Metal patterns that would matter if future work adds custom kernels or DSP. When this doc disagrees with the code, the code wins — fix this file.
>
> Last reviewed: 2026-08-01. MLX pin: `mlx-swift` **0.31.6**. Toolchain: Swift 6, Xcode 26, macOS 26+/iOS 26+.

---

## 1. Executive summary

Vocello runs its 1.7 B parameter Qwen3-TTS model entirely on-device. On Apple Silicon, the GPU compute backend is **Metal**. The Swift app does not call Metal directly for model inference; instead it uses **MLX**, which compiles operations into Metal compute kernels, batches them into command buffers, and submits them to the GPU.

This document covers both paths:

- **Metal through MLX** — the active path. Understanding it is essential for debugging memory pressure, interpreting telemetry, and optimizing the autoregressive decode loop.
- **Direct Metal programming** — the future path. Patterns for compute pipelines, buffers, synchronization, and custom kernels, should Vocello ever need audio DSP or a hand-tuned operation that MLX does not provide.

**Source-of-truth hierarchy**

1. `Packages/VocelloQwen3Core/` and `mlx-swift` 0.31.6 source — actual dispatch behavior.
2. `Sources/QwenVoiceCore/NativeMemoryPolicyResolver.swift` — cache/memory-limit policy.
3. `Sources/QwenVoiceCore/IOSMemorySnapshot.swift` — iOS Metal memory telemetry.
4. `Sources/QwenVoiceCore/NativeTelemetrySampler.swift` — runtime sampling of GPU allocation.
5. `docs/reference/mlx-guide.md`, `docs/reference/ios-engine-optimization.md`, `docs/reference/swift-performance-guide.md`.
6. This document.

---

## 2. Metal fundamentals

### 2.1 Core object model

| Object | Role |
| --- | --- |
| `MTLDevice` | A single GPU. Factory for queues, buffers, textures, libraries, pipelines. |
| `MTLCommandQueue` | Serial queue that submits command buffers to one GPU. Long-lived. |
| `MTLCommandBuffer` | Container for encoded GPU commands. Transient; commit → schedule → complete. |
| `MTLComputeCommandEncoder` | Writes compute commands (kernel dispatches, buffer bindings) into a command buffer. |
| `MTLComputePipelineState` | Compiled compute kernel. Expensive to create; cache and reuse. |
| `MTLLibrary` / `MTLFunction` | Compiled Metal shader library and a named function within it. |
| `MTLBuffer` | GPU-accessible memory buffer. On Apple Silicon, CPU-accessible too if `.storageModeShared`. |

A minimal compute dispatch looks like this:

```swift
import Metal

guard let device = MTLCreateSystemDefaultDevice(),
      let queue = device.makeCommandQueue(),
      let library = device.makeDefaultLibrary(),
      let function = library.makeFunction(name: "add_arrays"),
      let pipeline = try? device.makeComputePipelineState(function: function)
else { fatalError("Metal setup failed") }

let commandBuffer = queue.makeCommandBuffer()!
let encoder = commandBuffer.makeComputeCommandEncoder()!
encoder.setComputePipelineState(pipeline)
encoder.setBuffer(bufferA, offset: 0, index: 0)
encoder.setBuffer(bufferB, offset: 0, index: 1)
encoder.setBuffer(bufferResult, offset: 0, index: 2)

let gridSize = MTLSize(width: count, height: 1, depth: 1)
let tgSize = MTLSize(width: min(pipeline.maxTotalThreadsPerThreadgroup, count),
                     height: 1, depth: 1)
encoder.dispatchThreads(gridSize, threadsPerThreadgroup: tgSize)
encoder.endEncoding()
commandBuffer.commit()
commandBuffer.waitUntilCompleted()
```

### 2.2 Execution hierarchy

- **Grid** — total set of threads launched.
- **Threadgroup** — sub-group of threads that share `threadgroup` memory and can synchronize with barriers.
- **SIMD-group** — hardware execution unit, typically 32 threads wide on Apple Silicon.
- **Thread** — one kernel invocation.

In MSL:

```metal
kernel void add_arrays(device const float *inA [[buffer(0)]],
                       device const float *inB [[buffer(1)]],
                       device float *result    [[buffer(2)]],
                       uint index              [[thread_position_in_grid]])
{
    result[index] = inA[index] + inB[index];
}
```

### 2.3 Memory address spaces (MSL)

| Address space | Scope | Typical use |
| --- | --- | --- |
| `device` | Global GPU memory | Read/write arrays, weights, activations. |
| `constant` | Read-only constant cache | Small read-only parameters, lookup tables. |
| `threadgroup` | Shared within one threadgroup | Cooperative tilings, reductions, scratch pads. |
| `thread` | Per-thread registers/scratch | Temporary scalars/vectors. |

### 2.4 Storage modes on Apple Silicon

| Mode | CPU access | GPU access | Use case |
| --- | --- | --- | --- |
| `.storageModeShared` | Yes | Yes | Default on Apple Silicon; zero-copy CPU↔GPU. |
| `.storageModePrivate` | No | Yes | GPU-only intermediates; avoids coherency overhead. |
| `.storageModeMemoryless` | No | Tile memory only | Transient render targets; not backed by DRAM. |
| `.storageModeManaged` | Yes (explicit sync) | Yes | macOS discrete-GPU legacy; avoid on Apple Silicon. |

Vocello's MLX arrays live in shared memory. The telemetry sampler reads `MTLDevice.currentAllocatedSize` and `recommendedMaxWorkingSetSize` from a shared `MTLDevice` to track GPU allocation pressure without extra copies.

---

## 3. Metal as MLX's GPU backend

### 3.1 Lazy evaluation → Metal command buffers

MLX operations build a compute graph. Real GPU work happens only when a value is forced:

- `eval(_:)` / `asyncEval(_:)`
- `.item(...)` or printing
- Converting to `Data`, `asMTLBuffer`, or copying to a CPU buffer

For each GPU stream, MLX maintains a thread-local `CommandEncoder` (internal C++ class) that owns one `MTLCommandBuffer` and one `MTLComputeCommandEncoder`. Primitives are appended until a commit trigger fires (buffer size, operation count, or explicit synchronization). This batching is why many small element-wise ops can fuse into fewer Metal kernels.

```swift
import MLX

let a = MLXArray([1, 2, 3, 4])
let b = a * 2
let c = b + 5          // no GPU work yet

eval(c)                // command buffer built and submitted here
```

### 3.2 `eval()` vs `asyncEval()`

| API | Behavior | When to use |
| --- | --- | --- |
| `eval(_:)` | Blocks caller until GPU finishes. | Simple scripts; final step of a pipeline. |
| `asyncEval(_:)` | Schedules work, returns immediately; syncs later. | Autoregressive loops where the CPU can prepare the next token while the GPU runs the current one. |

Vocello's decode loop uses `asyncEval` so that `code2wav` work can overlap the next talker/code-predictor step. In telemetry this often makes `code2wav` CPU-wall time appear near zero — the work ran while the CPU was busy elsewhere.

### 3.3 Kernel compilation and caching

MLX ships precompiled Metal libraries (`mlx.metallib`) for common primitives. For fused or compiled graphs it JIT-compiles Metal source via `Device::build_library_` and caches:

- Libraries keyed by source/name.
- Pipeline states keyed by kernel hash + function constants.
- Custom kernels cached by name + source in `CustomKernelCache`.

First invocation of a new shape/dtype graph pays a compile cost; subsequent calls reuse the pipeline. This is one reason warmup matters: the first generation after app launch may be slower than the second.

### 3.4 Kernel fusion and `compile()`

`MLX.compile` / `MLXFast.metalKernel` trace a function and fuse operations into fewer kernels. For Vocello this matters for:

- Activations and post-processing inside the talker/code predictor.
- Custom audio DSP if added later.

Recompilation is triggered by changing input shape, dtype, or number of inputs. Use `shapeless: true` when shapes vary but the graph is shape-independent.

```swift
let kernel = MLXFast.metalKernel(
    name: "scale",
    inputNames: ["x"],
    outputNames: ["y"],
    source: """
        uint elem = thread_position_in_grid.x;
        if (elem < y.size()) { y[elem] = x[elem] * 2.0f; }
        """,
    grid: (1024, 1, 1),
    threadGroup: (256, 1, 1),
    outputShapes: [[1024]],
    outputDTypes: [.float32])
```

### 3.5 Unified memory assumptions

On Apple Silicon:

- `MLXArray` buffers are `MTLBuffer` allocations in shared memory.
- No explicit `to(device:)` copy.
- Reading a scalar (`array.item()`) or printing forces a GPU→CPU sync; minimize this inside the token loop.
- Memory pressure affects CPU, GPU, and Neural Engine simultaneously because they share physical DRAM.

Vocello's iOS memory policy (`NativeMemoryPolicyResolver`) treats GPU allocations as part of the app's physical footprint. `Memory.cacheLimit` and `Memory.clearCache()` are the primary levers for controlling retained Metal buffer memory.

---

## 4. Metal Performance Shaders and MLX kernels

### 4.1 When MLX uses MPS

Metal Performance Shaders (MPS) provides optimized kernels for:

- Matrix multiplication (`MPSMatrixMultiplication`)
- Convolutions (`MPSCNNConvolution`)
- Normalization, pooling, common neural-network primitives

MLX uses MPS where it provides a clear win and falls back to custom Metal kernels for operations that need specific fusion, quantization, or layout behavior. For Qwen3-TTS this means matmul and attention-heavy work typically rides MPS or MLX's own tuned matmul kernels, while the Mimi codec's causal convolutions and SnakeBeta activations run as custom Metal kernels compiled by MLX.

### 4.2 Mixed precision

Apple Silicon GPUs run FP16 at roughly double the throughput of FP32. MLX and `mlx-swift` use fp16/bf16 activations by default for inference; quantized weights (4-bit/8-bit) are dequantized on-demand inside the matmul kernel.

Vocello's Speed variant uses 4-bit affine quantization; Quality uses 8-bit. Both keep activations in 16-bit float. This is a bandwidth and compute win with minimal quality loss for TTS.

### 4.3 Threadgroup sizing

For custom kernels, choose threadgroup sizes that are multiples of the SIMD width (typically 32 on Apple Silicon) and do not exceed `maxTotalThreadsPerThreadgroup`. Use `dispatchThreads(_:threadsPerThreadgroup:)` for non-uniform grids.

```swift
let w = pipeline.threadExecutionWidth
let h = pipeline.maxTotalThreadsPerThreadgroup / w
let threadsPerThreadgroup = MTLSize(width: w, height: h, depth: 1)
encoder.dispatchThreads(gridSize, threadsPerThreadgroup: threadsPerThreadgroup)
```

---

## 5. Memory model and bandwidth

### 5.1 Apple Silicon unified memory

CPU, GPU, and Neural Engine share the same DRAM pool. There is no discrete VRAM. For Vocello this means:

- Model weights, KV caches, and MLX buffer cache all compete with the app, the OS, and audio pipelines.
- On iOS, GPU allocations count directly against the Jetsam physical footprint ceiling.
- On macOS, the XPC service isolates the engine's footprint from the app, but both still share system RAM.

### 5.2 Vocello's Metal memory telemetry

`IOSMemorySnapshot.capture(device:)` records:

- `availableHeadroomBytes` from `os_proc_available_memory()`
- `physFootprintBytes` from `task_vm_info`
- `gpuAllocatedBytes` from `MTLDevice.currentAllocatedSize`
- `gpuRecommendedWorkingSetBytes` from `MTLDevice.recommendedMaxWorkingSetSize`
- `hasUnifiedMemory` from `MTLDevice.hasUnifiedMemory`

`NativeTelemetrySampler` caches a single `MTLDevice` instance to avoid repeatedly creating Metal device objects during sampling.

### 5.3 Cache and memory-limit policy

`NativeMemoryPolicyResolver.apply(_:)` sets:

- `Memory.cacheLimit` — how much freed buffer memory MLX retains for reuse.
- `Memory.memoryLimit` — optional harder cap; allocations wait when exceeded.

Per-tier defaults:

| Tier | Cache limit | Memory limit | Clear cache cadence |
| --- | --- | --- | --- |
| `floor8GBMac` | 256 MB | none | every 50 tokens |
| `mid16GBMac` | 512 MB | none | every 50 tokens |
| `highMemoryMac` | 1 GB | none | every 200 tokens |
| `iPhonePro` | 128 MB | env-only | every 50 tokens, per chunk |

On iOS, the small cache limit + per-chunk clear is what keeps the streaming memory peak flat. Do not raise the iPhone cache limit without measuring Jetsam behavior on physical hardware.

### 5.4 Bandwidth vs. compute

For transformer and TTS workloads, **memory bandwidth is usually the bottleneck**, not raw ALU throughput. The GPU spends much of its time fetching weights and KV-cache entries. Optimizations that reduce memory traffic (quantization, smaller KV cache, streaming chunking) generally help more than optimizations that reduce arithmetic.

---

## 6. Direct Metal patterns (future-proofing)

Vocello does not currently use these patterns, but they are the starting point if a custom kernel or audio DSP is needed.

### 6.1 Setting up a compute pipeline

```swift
import Metal

guard let device = MTLCreateSystemDefaultDevice(),
      let queue = device.makeCommandQueue()
else { fatalError("No Metal device") }

let library = try! device.makeDefaultLibrary(bundle: Bundle.main)
let function = library.makeFunction(name: "my_kernel")!
let pipeline = try! device.makeComputePipelineState(function: function)
```

### 6.2 Creating and populating a buffer

```swift
let count = 1024
let byteCount = count * MemoryLayout<Float>.size

let buffer = device.makeBuffer(
    length: byteCount,
    options: .storageModeShared
)!

let ptr = buffer.contents().bindMemory(to: Float.self, capacity: count)
for i in 0..<count { ptr[i] = Float(i) }
// No explicit upload on Apple Silicon — the GPU can read it directly.
```

### 6.3 Dispatching a kernel

```swift
let commandBuffer = queue.makeCommandBuffer()!
let encoder = commandBuffer.makeComputeCommandEncoder()!
encoder.setComputePipelineState(pipeline)
encoder.setBuffer(buffer, offset: 0, index: 0)

let grid = MTLSize(width: count, height: 1, depth: 1)
let tg = MTLSize(width: pipeline.maxTotalThreadsPerThreadgroup, height: 1, depth: 1)
encoder.dispatchThreads(grid, threadsPerThreadgroup: tg)
encoder.endEncoding()
commandBuffer.commit()
```

### 6.4 Synchronization

Avoid `waitUntilCompleted()` on the hot path. Prefer completion handlers:

```swift
commandBuffer.addCompletedHandler { buffer in
    let ms = (buffer.gpuEndTime - buffer.gpuStartTime) * 1000
    print("GPU time: \(ms) ms")
}
commandBuffer.commit()
```

For safe buffer reuse across multiple in-flight buffers, use a `DispatchSemaphore` (triple-buffering pattern).

### 6.5 Interop with MLX arrays

`MLXArray.asMTLBuffer(device:noCopy:)` can expose the underlying `MTLBuffer`. Caveats:

- The array must be evaluated first.
- Lifetime management matters: do not let the `MLXArray` be freed while the buffer is in use.
- Layout must match what the kernel expects (row-contiguous, dtype-aligned).
- Modifying the buffer from a custom kernel while MLX still holds the array can break lazy-evaluation invariants.

If Vocello ever adds a custom Metal kernel, the safest pattern is to copy the relevant slice into a dedicated `MTLBuffer`, process it, and copy back into a new `MLXArray`.

---

## 7. Profiling and debugging

### 7.1 Xcode Metal debugger / frame capture

The Metal debugger captures all Metal commands in a time window and lets you inspect:

- Per-encoder timelines
- GPU counters (occupancy, bandwidth, ALU utilization)
- Shader source and assembly
- Resource dependencies

For MLX/Vocello, captures can be triggered programmatically:

```swift
GPU.startCapture(url: URL(fileURLWithPath: "/tmp/vocello.gputrace"))
// ... run generation ...
eval(output)
GPU.stopCapture(url: URL(fileURLWithPath: "/tmp/vocello.gputrace"))
```

Requires `MTL_CAPTURE_ENABLED=1` at launch (or `MLX_METAL_DEBUG` for shader source preservation).

### 7.2 Metal System Trace (Instruments)

The **Metal System Trace** template records:

- CPU/GPU timelines
- Command buffer scheduling
- Memory allocations
- Performance limiters
- Thermal state

Use it to find CPU/GPU bubbles, excessive sync points, and memory growth.

### 7.3 `os_signpost`

Vocello already uses `OSSignposter` (`AppPerformanceSignposts.swift`, and the
`GenerationOutputAdapter` type in `GenerationOutputAdapter.swift`) to
mark CPU-side phases. These signposts appear in Instruments' **Points of Interest** track and help
correlate app-level events with GPU activity.

```swift
import OSLog

let signposter = OSSignposter(
    subsystem: "com.qwenvoice.app",
    category: "performance"
)
let id = signposter.makeSignpostID()
let state = signposter.beginInterval("TTSInference", id: id)
// ... work ...
signposter.endInterval("TTSInference", id: id, state)
```

### 7.4 Reading GPU time programmatically

For live benchmarking, attach a completion handler to the underlying `MTLCommandBuffer`. MLX does not directly expose per-operation GPU time, but `GPU.startCapture` / `GPU.stopCapture` and Instruments are the authoritative tools.

### 7.5 Key GPU counters

| Counter | What it tells you |
| --- | --- |
| Compute Occupancy | How much of the GPU's thread capacity is in use. |
| Memory Bandwidth | System memory ↔ GPU traffic. High → bandwidth-bound. |
| ALU utilization | How busy the shader ALUs are. Low + high bandwidth = memory-bound. |
| Texture/Buffer limiters | Whether cache or sampler throughput is the bottleneck. |
| Tile memory load/store | Relevant if doing render passes; less so for pure compute. |

Start with **Performance Limiter** counters. They point to the slowest subsystem.

---

## 8. iOS-specific Metal considerations

### 8.1 Jetsam and per-process memory

iOS terminates apps whose physical footprint crosses a per-process limit. Because memory is unified, Metal allocations count against that limit. Vocello's iOS target enables `com.apple.developer.kernel.increased-memory-limit`, which raises the ceiling on supported devices, but the app must still fit within the runtime budget measured by `os_proc_available_memory()`.

Telemetry shows that Vocello's streaming path peaks around **3.0 GB physical footprint** on iPhone, comfortably under the entitled ceiling (~5–6 GB) but not with much margin.

### 8.2 Thermal throttling and sustained performance

iOS devices throttle CPU/GPU frequencies when hot. `ProcessInfo.thermalState` exposes:

- `.nominal`
- `.fair`
- `.serious`
- `.critical`

For long synthesis sessions, design for **sustained** throughput, not burst. If thermal state rises, consider reducing quality, inserting idle gaps, or unloading caches.

### 8.3 Tile-Based Deferred Rendering (TBDR)

Apple GPUs are TBDR. While this matters most for graphics, it affects compute too:

- The GPU splits work into tiles and processes them on-chip.
- `.storageModeMemoryless` attachments live only in tile memory, saving DRAM bandwidth.
- Load/store actions (`MTLLoadAction`, `MTLStoreAction`) control tile-memory traffic.

For Vocello's compute-heavy TTS path, the practical takeaway is to keep intermediate buffers as `.private` when only the GPU reads them and to minimize CPU↔GPU round-trips.

### 8.4 Increased memory entitlement

```xml
<key>com.apple.developer.kernel.increased-memory-limit</key>
<true/>
```

This entitlement is required for Vocello iOS to load the 1.7 B model. It is self-serve (enable on the App ID, regenerate the provisioning profile). It raises the Jetsam ceiling but does not create free memory — `os_proc_available_memory()` remains the authoritative runtime read.

---

## 9. Optimization guidelines

### 9.1 For the MLX path (current)

1. **Batch work, then `eval` or `asyncEval`.** Avoid frequent intermediate evaluations inside the token loop.
2. **Use `asyncEval` to overlap CPU and GPU.** Let the CPU prepare the next graph while the GPU executes the current one.
3. **Minimize `.item()` / printing during generation.** These force GPU→CPU sync.
4. **Tune `Memory.cacheLimit` per tier.** iOS needs a small cache (128 MB) to keep footprint flat; Macs can keep more.
5. **Call `Memory.clearCache()` at boundaries.** Vocello does this per chunk on iOS and after generation on constrained Macs.
6. **Profile with Instruments Metal System Trace.** CPU timers alone are misleading because of lazy evaluation.

### 9.2 For future direct-Metal work

1. **Cache pipeline states, libraries, and command queues.** Creating `MTLComputePipelineState` is expensive.
2. **Choose threadgroup sizes as multiples of SIMD width** (32) and stay under `maxTotalThreadsPerThreadgroup`.
3. **Use `dispatchThreads` for non-uniform grids.** Avoid manual padding where possible.
4. **Prefer `.storageModeShared` for CPU↔GPU data, `.private` for GPU-only temporaries.** Avoid `.managed` on Apple Silicon.
5. **Use `threadgroup` memory for cooperative kernels.** Keep it aligned and sized per threadgroup.
6. **Avoid `waitUntilCompleted` on the hot path.** Use completion handlers and triple buffering.
7. **Prefer FP16 where precision allows.** It runs at higher throughput.
8. **Profile before optimizing.** Bandwidth, occupancy, and limiter counters tell you where the real bottleneck is.

---

## 10. Troubleshooting

### 10.1 Unexpectedly slow generation

**Symptoms:** RTF drops, long time-to-first-audio, high CPU wait time.

**Likely causes:**

1. Too many `eval()` calls splitting the graph.
2. Frequent `.item()` forcing GPU→CPU sync.
3. Cache limit too low, causing repeated buffer allocation.
4. Thermal throttling on iOS.

**Fix:** Use `asyncEval`, batch work, check thermal state, and profile with MST.

### 10.2 iOS Jetsam termination during generation

**Symptoms:** App killed with `jetsam(1) code:per-process-limit(7)`.

**Likely causes:**

1. Peak footprint exceeded the entitled limit.
2. Non-streaming path accumulated all tokens before decoding.
3. Cache limit too high, retaining peak buffers.
4. Clone reference priming added speaker-encoder memory on top of the model.

**Fix:** Verify streaming is enabled, lower `Memory.cacheLimit`, ensure the increased-memory entitlement is active, and gate clone capability on `IOSMemorySnapshot.impliedProcessLimitBytes`.

### 10.3 Memory growth across generations

**Symptoms:** `physFootprint` rises over multiple utterances without returning to baseline.

**Likely causes:**

1. MLX buffer cache not cleared between generations.
2. Metal shader caches or driver allocations accumulating.
3. Retained references to large `MLXArray` outputs.

**Fix:** Call `Memory.clearCache()` at generation boundaries, review retain cycles in the streaming session, and monitor `MTLDevice.currentAllocatedSize` in telemetry.

### 10.4 Frame capture fails or shows no compute work

**Symptoms:** Empty `.gputrace`, no kernels visible.

**Likely causes:**

1. `MTL_CAPTURE_ENABLED=1` not set at launch.
2. Capture started after the work already completed.
3. Using `MLX_METAL_DEBUG=0`, so shader source is stripped.

**Fix:** Set environment variables at process launch, wrap the entire generation in `GPU.startCapture` / `stopCapture`, and build with debug Metal enabled.

### 10.5 Custom kernel produces wrong results

**Symptoms:** Output is garbled, NaN, or shape-mismatched.

**Likely causes:**

1. Buffer layout assumption violated (row vs. column contiguous).
2. Thread indexing off-by-one for non-uniform grids.
3. Missing `threadgroup_barrier` in cooperative kernels.
4. Race condition from writing to a buffer still in use by MLX's lazy graph.

**Fix:** Validate shapes and strides, use `dispatchThreads`, add barriers, and isolate the kernel from MLX's graph with explicit copies.

---

## 11. Appendix

### 11.1 Apple Silicon GPU bandwidth/TFLOPS reference

Approximate peak values for planning. Real sustained throughput is lower due to thermal and bandwidth limits.

| Chip | GPU cores | FP32 TFLOPS (approx.) | Memory bandwidth |
| --- | --- | --- | --- |
| M1 | 7/8 | 2.3–2.6 | 68 GB/s |
| M1 Pro | 14/16 | ~5.2 | 200 GB/s |
| M1 Max | 24/32 | ~10.4 | 400 GB/s |
| M2 | 8/10 | 2.9–3.6 | 100 GB/s |
| M2 Pro | 16/19 | ~6.8 | 200 GB/s |
| M2 Max | 30/38 | ~13.6 | 400 GB/s |
| M3 | 8/10 | ~3.5 | 100 GB/s |
| M3 Pro | 14/18 | ~7.0 | 150 GB/s |
| M3 Max | 30/40 | ~14.1 | 300/400 GB/s |
| M4 | 8/10 | 3.8–4.3 | 120 GB/s |
| M4 Pro | 16/20 | ~8.6 | 273 GB/s |
| M4 Max | 32/40 | ~17.2 | 410/546 GB/s |
| A17 Pro | 6 | ~2.15 | 51 GB/s |
| A18 Pro | 6 | ~2.3 | 60 GB/s |

### 11.2 Glossary

| Term | Meaning |
| --- | --- |
| **Command buffer** | Container of GPU commands submitted to a queue. |
| **Command encoder** | Object that writes commands into a command buffer. |
| **Compute pipeline** | Compiled compute kernel + execution metadata. |
| **Grid** | Total set of threads launched for a kernel. |
| **Threadgroup** | Sub-group of threads sharing fast shared memory. |
| **SIMD-group** | 32-thread hardware execution unit on Apple GPUs. |
| **Threadgroup memory** | Fast on-chip scratch memory shared within a threadgroup. |
| **Unified memory** | CPU/GPU/NE sharing the same physical DRAM. |
| **TBDR** | Tile-Based Deferred Rendering, Apple GPU architecture. |
| **Occupancy** | Percentage of GPU thread capacity in use. |
| **Kernel fusion** | Combining multiple operations into fewer GPU kernels. |
| **Lazy evaluation** | Building a compute graph before executing it. |

### 11.3 Useful environment variables

The MLX/Metal diagnostic variables below come from their respective runtimes. Vocello-owned
production-affecting keys are registered in `config/runtime-debug-knobs.json`, read through
`RuntimeDebugGate`, and remain inert unless `QWENVOICE_DEBUG=1`.

| Variable | Effect |
| --- | --- |
| `MTL_CAPTURE_ENABLED=1` | Enable Metal GPU capture. |
| `MLX_METAL_DEBUG=1` | Preserve Metal shader source in captures. |
| `MLX_DISABLE_COMPILE=1` | Disable MLX automatic kernel fusion. |
| `QVOICE_IOS_MLX_CACHE_LIMIT_MB` | Debug-gated override of the iOS MLX cache limit. |
| `QVOICE_IOS_MLX_MEMORY_LIMIT_MB` | Debug-gated override of the iOS MLX memory limit. |

### 11.4 Cross-references

- [`mlx-guide.md`](mlx-guide.md) — MLX runtime, lazy evaluation, quantization.
- [`swift-performance-guide.md`](swift-performance-guide.md) — Swift 6 concurrency and performance.
- [`ios-engine-optimization.md`](ios-engine-optimization.md) — iOS-specific memory, streaming, Jetsam.
- [`mimi-codec-guide.md`](mimi-codec-guide.md) — Neural audio codec implementation.
- [`telemetry-and-benchmarking.md`](telemetry-and-benchmarking.md) — Telemetry schema and benchmarking.

### 11.5 External references

- Apple Metal documentation: <https://developer.apple.com/documentation/metal>
- Metal Shading Language Specification: <https://developer.apple.com/metal/Metal-Shading-Language-Specification.pdf>
- MLX documentation: <https://ml-explore.github.io/mlx/>
- mlx-swift source: <https://github.com/ml-explore/mlx-swift>
- WWDC25 "Explore large language models on Apple silicon with MLX": <https://developer.apple.com/videos/play/wwdc2025/298/>
- WWDC20 "Optimize Metal apps and games with GPU counters": <https://developer.apple.com/videos/play/wwdc2020/10603/>
