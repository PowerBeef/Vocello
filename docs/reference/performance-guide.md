---
status: active
owner: backend-and-platform
reviewed: 2026-10-28
summary: Swift 6 and Metal performance reference for the apps and CLI — build settings, isolation, value types, dispatch, allocation and ARC; profiling and GPU capture; how MLX drives Metal (command buffers, kernel caching, compile(), no MPS, unified memory, Metal memory telemetry); direct-Metal patterns for future custom kernels; iOS Metal limits, troubleshooting and the performance-change checklist.
sourceOfTruth:
  - project.yml
  - Sources/QwenVoiceCore/NativeMemoryPolicyResolver.swift
  - Sources/QwenVoiceCore/IOSMemorySnapshot.swift
---
# Swift and Metal performance guide

> **Living document.** When this guide disagrees with the code, the code wins: fix this file.
> Language mode Swift 6 (`SWIFT_VERSION: "6"`, `project.yml:33`); CI's compiler is Swift 6.3.3 with
> Xcode 26.6 (`config/toolchain.json`). The MLX pins are
> [`mlx-guide.md` §9.1](mlx-guide.md#91-current-pins)'s.

This guide owns Swift-layer and Metal performance practice. Other facts have one owner each:

| Topic | Owner |
|---|---|
| MLX semantics: evaluation, error scopes, quantization, KV cache, sampling, cache clearing, pins | [`mlx-guide.md`](mlx-guide.md) |
| Engine structure, memory tiers, event router, prewarm, cancellation | [`ARCHITECTURE.md` §4](../ARCHITECTURE.md#4-engine-core-qwenvoicecore) |
| Model architecture and generation parameters | [`qwen3-tts-guide.md`](qwen3-tts-guide.md) |
| Telemetry schema and benchmark procedure | [`telemetry-and-benchmarking.md`](telemetry-and-benchmarking.md) |
| The iOS increased-memory entitlement | [`ios-increased-memory-entitlement-request.md`](ios-increased-memory-entitlement-request.md) |

## Contents

- Swift: [1. Why it matters](#1-why-swift-performance-matters-here) ·
  [2. Build settings](#2-build-settings-and-toolchain) ·
  [3. Concurrency](#3-concurrency-model-and-actor-isolation) ·
  [4. Value types](#4-memory-and-value-types) · [5. Dispatch](#5-function-calls-and-dispatch) ·
  [6. Allocation](#6-allocation-patterns) · [7. ARC](#7-reference-counting-and-arc)
- Practice: [8. Profiling](#8-profiling-workflow) ·
  [9. Project invariants](#9-project-specific-patterns-and-invariants) ·
  [10. Checklist](#10-promotionrelease-checklist-for-performance-changes)
- Metal: [11. Fundamentals](#11-metal-fundamentals) ·
  [12. MLX's GPU backend](#12-metal-as-mlxs-gpu-backend) ·
  [13. Direct Metal](#13-direct-metal-patterns-future-proofing) ·
  [14. iOS](#14-ios-specific-metal-considerations) ·
  [15. Optimization guidelines](#15-optimization-guidelines) ·
  [16. Troubleshooting](#16-troubleshooting) · [17. Appendix](#17-appendix)

---

## 1. Why Swift performance matters here

Vocello runs a 1.7 B parameter Qwen3-TTS model on Apple Silicon. MLX does the compute and drives
the GPU through Metal; the app never calls Metal for inference. The Swift layer orchestrates it:
model loading, tokenization, the autoregressive decode loop, audio decoding, streaming chunk
dispatch, memory-pressure reactions, and the UI that presents all of it. A slow or
allocation-heavy Swift layer can:

- Starve the GPU by delaying the next token graph (`eval()` stalls).
- Inflate physical footprint and trigger Jetsam on iOS.
- Drop UI frames on the main thread during generation.
- Waste battery with unnecessary reference-counting traffic.

The Swift half (§2–§7) follows the four low-level principles Swift is sensitive to:

1. **Function-call overhead** — static vs. dynamic dispatch, inlining, generics.
2. **Data representation** — inline (structs) vs. out-of-line (classes) storage, protocol types, value layout.
3. **Allocation volume** — heap, stack, async slab, and global memory.
4. **Copying / ownership traffic** — retain/release, exclusivity checks, copy-on-write.

The Metal half (§11–§16) covers Metal as MLX uses it (the active path) and direct-Metal patterns
should Vocello ever need a custom kernel or GPU audio DSP (the future path). If you change any of
these areas in `Sources/`, update this guide with the new rationale and measured impact.

---

## 2. Build settings and toolchain

### 2.1 Single shippable config

`project.yml` defines only a `Release` configuration. There is no separate `Debug` build or `DEBUG` symbol. The scripts compile the same config differently:

| Script | Optimization | Use case |
| --- | --- | --- |
| `scripts/build.sh build` | owned code `-Onone`, incremental; packages at their Release defaults | Fast local dev loop. |
| `scripts/build.sh cli` | owned code `-Onone`, incremental; packages at their Release defaults | Headless CLI dev loop. |
| `scripts/build.sh cli-optimized` | `-O` | Optimized `vocello` for benchmark and shipping-performance evidence; `toolchain.optimization` in a record comes from its hash-bound build receipt, never a literal. |
| `scripts/release.sh` | Xcode Release defaults (`-O`, whole-module) | Signed/notarized DMG. |
| `scripts/build.sh release` | runs `scripts/release.sh` | The same DMG build through the shared regeneration and SwiftPM caches. |

`project.yml` sets `SWIFT_OPTIMIZATION_LEVEL`, `SWIFT_COMPILATION_MODE`, `GCC_OPTIMIZATION_LEVEL` and `ENABLE_TESTABILITY` at project level to `QVOICE_OWNED_*` variables whose defaults are the Release values (`-O`, whole-module, `s`, no testability; `project.yml:54-61`), so the release path compiles exactly as Xcode's Release defaults did. Project-level settings reach only this project's targets, never the Swift packages. The development and test builds of the shared `-Onone` arena (`build.sh build` and `cli`, `macos_test.sh test` and `tsan`, the macOS XCUITest `--gate` compile) pass `QVOICE_OWNED_DEV_SETTINGS` (`scripts/lib/build_cache.sh:642-647`), which makes owned code `-Onone`, incremental and testable while MLX and the other packages keep their optimized builds. Builds that pass `SWIFT_OPTIMIZATION_LEVEL` on the command line (the optimized CLI, the release scripts, the device lanes and the foundation compiles) still set it for every target, packages included.

### 2.2 Swift 6 language mode

All Swift targets use `SWIFT_VERSION: "6"`. App, engine and CLI targets rely on the Swift 6 language mode alone for data-race safety (`Sendable`, `actor`, `@MainActor`); only the three XCUITest bundles (`VocelloMacUITests`, `VocelloiOSUITests`, `VocelloiOSCandidateUITests`) set `SWIFT_STRICT_CONCURRENCY: complete` explicitly in `project.yml`.

### 2.3 Compilation-condition switches

- `QW_UI_LIQUID` is set in the `Release` config for the macOS app target (`project.yml:280`) to enable Liquid Glass surfaces. It has no performance effect.
- The project has no Debug configuration or generic `DEBUG` symbol. Runtime diagnostic behavior is
  gated by `DebugMode.isEnabled`. Compile-time test isolation belongs in test targets or behind a
  narrowly named compilation condition; do not add hidden app behavior through `#if DEBUG`.

### 2.4 When to rebuild with `-O`

`-Onone` dev builds hide some performance behaviors:

- Stack promotion and inline storage are less aggressive.
- Generic specialization and cross-module inlining are reduced.
- Release-only ARC optimizations are absent.

For any performance work that claims a measured improvement, build optimized (`scripts/build.sh cli-optimized` for the CLI, `scripts/release.sh` for the apps) and validate on the target hardware. Do not optimize against `-Onone` timings alone.

---

## 3. Concurrency model and actor isolation

### 3.1 The basic split

Vocello's concurrency design is intentionally coarse-grained:

- **`@MainActor`** — SwiftUI views and the models behind them (`TTSEngineStore`, `MacAppModel` on macOS, `AppModel` on iOS, `ContentView`).
- **Engine actors** — `NativeEngineRuntime` (`NativeEngineRuntime.swift:399`), the owned package's `VocelloQwen3Engine`, and `NativePreparedCloneConditioningCache` (`NativeCloneSupport.swift:82`, the clone cache with LRU eviction). What each owns is [ARCHITECTURE §4.1](../ARCHITECTURE.md#41-the-ttsengine-abstraction)'s.
- **Background `Task` / `Task.detached`** — telemetry sampler, chunk forwarding, audio decoding consumer.
- **`Mutex` (Synchronization)** — small synchronous state shared across threads (`MainThreadStallWatchdog`, the `TelemetryGate` latch, `GenerationFailureDiagnosticLogger`) lives in a `Mutex`, so those types stay checked `Sendable`. `ModelDownloadDiagnosticsStore` also keeps its state in a `Mutex` but stays `@unchecked Sendable` for its injected `FileManager`; it and every other remaining `@unchecked Sendable` are registered in `config/concurrency-safety.json`.

This keeps data-race checking tractable and matches the natural boundaries of the app.

### 3.2 `@MainActor` and the UI

`TTSEngineStore` (`Sources/iOS/TTSEngineStore.swift:34-35`, compiled into both apps) is a `@MainActor` class over a `nonisolated ObservableObject` conformance. macOS hosts `MLXTTSEngine` in-process through the same type-erased `AnyTTSEngineBackend` the iPhone uses (`MacEngineBootstrap`). The store's `@Published` state (`loadState`, `clonePreparationState`, `latestEvent`, …) is fed from the backend's `stateDidChange` signal, which hops onto the main actor and re-reads one backend snapshot (`TTSEngineStore.swift:133-138`):

```swift
@MainActor
final class TTSEngineStore: nonisolated ObservableObject, TTSEngine {
    @Published private(set) var loadState: EngineLoadState = .idle
    private let backend: AnyTTSEngineBackend

    init(backend: AnyTTSEngineBackend, ...) {
        ...
        changeObserver = backend.stateDidChange
            .sink { [weak self] in
                Task { @MainActor [weak self] in
                    self?.syncFromBackend()
                }
            }
    }
}
```

Because the store is one coarse `ObservableObject`, a view that reads it in `body` re-renders on every published change. Streaming chunks therefore never become `@Published` state (they are forwarded to the player separately), and the Mac root shell does not observe the store at all: it subscribes to the explicit `snapshotChanges` bridge (`Sources/Services/TTSEngineStore+Mac.swift:19`, over the store's `snapshotUpdates` subject) with `onReceive` (`ContentView.swift:212`), which fires only on applied snapshot changes (W1-D/W2-A). Keep new imperative consumers on such explicit bridges rather than reading the store in a view body.

### 3.3 Actors as serialization points

`NativeEngineRuntime` is an `actor`. That gives it automatic mutual exclusion, but it is not a free abstraction:

- Every `await` on the actor is a potential suspension point.
- The actor's executor is a single serial queue; long synchronous work inside it blocks all other callers.
- The actor alone does not serialize prewarm: the prewarm body `await`s inside MLX, releasing actor access while the KV cache, which is not thread-safe, is still mutating. The prewarm slot gate exists for that ([§9.4](#94-prewarm-serialization)).

Rule: keep actor-isolated methods short. Move heavy MLX work off the actor when possible, or design explicit gates when MLX calls suspend but must remain mutually exclusive.

### 3.4 Sendable and unchecked conformances

Most value types in the engine conform to `Sendable` automatically or explicitly. The exhaustive
authority for owned `@unchecked Sendable` and other unsafe concurrency declarations is
`config/concurrency-safety.json`; examples in prose are intentionally non-exhaustive. Each registry
entry names the protected state, synchronization/immutability argument, owner, and review evidence.

Do not add an unchecked or unsafe declaration without a narrow code-level safety argument and a
matching registry entry. Prefer `actor`, `Mutex` (Swift 6), immutable adapters, or value types.
`python3 scripts/runtime_security_contract.py` rejects unregistered declarations and stale entries.

### 3.5 `Task` and `Task.detached`

- Use `Task { ... }` from `@MainActor` contexts when the work must hop off the main thread and you want structured concurrency.
- Use `Task.detached(priority: .utility) { ... }` for long-lived background work that must outlive the initiating scope, such as the telemetry merge after a generation completes.
- Avoid `Task.sleep` busy-waiting on the hot path. The telemetry sampler uses `try? await Task.sleep(nanoseconds:)` with a device-tiered cadence: 100 ms on the high-memory Mac, 250 ms on the 16 GB and 8 GB Macs and the iPhone (`SemanticTypes.swift:1045-1057`); periodic ticks skip `task_threads`.

---

## 4. Memory and value types

### 4.1 Structs vs. classes: the inline/out-of-line trade-off

Swift stores structs inline in their container and classes out-of-line (as a pointer to a heap object). This has direct performance consequences:

| Pattern | Storage | Copy cost | Best for |
| --- | --- | --- | --- |
| Small struct (`Int`, `CGSize`, small tuples) | Inline | Cheap bitwise copy | POD-like values, coordinates, IDs. |
| Large struct with reference fields | Inline | Multiple retains + full inline copy | Short-lived intermediates that are not copied often. |
| Class | Out-of-line | One retain | Shared mutable state, identity semantics, large objects copied frequently. |
| Copy-on-write struct (e.g. `Array`, `String`, `Data`) | Inline pointer + heap buffer | One retain until mutation | Collections and buffers. |

Vocello examples:

- `NativePreparedGeneration` (`NativeEngineRuntime.swift:352`) is a large `Sendable` struct carried from preparation into streaming. It is created once per generation and passed by value; it is not copied repeatedly, so inline struct storage is fine.
- `NativePreparedCloneConditioningCache` is an `actor` (a reference type) because it holds long-lived mutable caches that must be shared and isolated.
- `TTSEngineSnapshot` and related UI state are value types; mutations produce a new snapshot and publish it.

### 4.2 Copy-on-write (COW)

`Array`, `Dictionary`, `String`, and `Data` are COW. Copying is cheap, but mutation triggers a uniqueness check and may allocate a new buffer. In tight loops this matters:

- The telemetry sampler copies small dictionaries of counters; this is fine.
- Audio chunk buffers are passed as `Data` references; avoid repeated `append` / `dropFirst` reallocations inside the decode loop.
- The QOI-parser example from WWDC 2025 is a canonical warning: repeatedly calling `Data(bytesNoCopy:)` / `dropFirst()` can turn a constant-time slice into an O(n²) copy. If you manipulate binary buffers in the audio pipeline, use slice operations that do not copy unless profiling says it is safe.

### 4.3 Avoiding large struct copies

If a struct becomes large and is copied across many isolation boundaries, consider:

1. Making it a class (reference semantics).
2. Wrapping the class in a struct with COW.
3. Moving it behind an `actor` so all access is serialized and copies happen only at actor boundaries.

`ResolvedCloneConditioning` (`NativeCloneSupport.swift:24`) is large and `@unchecked Sendable`, and is passed across actor boundaries. It carries the reference audio as `[Float]` and an epoch-bound `VocelloQwen3CloneHandle` rather than an `MLXArray` (the prompt stays actor-owned, [ARCHITECTURE §4.4](../ARCHITECTURE.md#44-synthesis-pipeline)); it is created once per clone generation, so the copy cost is not on the hot token loop.

---

## 5. Function calls and dispatch

### 5.1 Static vs. dynamic dispatch

Swift dispatch rules (from WWDC 2024):

- **Protocol requirement** (declared in the protocol body) → dynamic dispatch.
- **Protocol extension method** (declared only in an extension) → static dispatch.
- **Final class methods** → static dispatch.
- **Non-final class methods** → dynamic dispatch.
- **Generic functions with concrete caller types** → can be specialized and inlined.

For the hot path (token loop, audio decoder, telemetry sampler), prefer static dispatch:

- Mark classes `final` unless subclassing is required.
- Prefer generic constraints over existential (`any P`) when all elements are the same concrete type.
- Use protocol extensions for helper methods that do not need runtime polymorphism.

### 5.2 Existential types (`any P`)

Existentials carry a 3-pointer inline buffer; larger values are heap-allocated. They also prevent specialization and inlining. Vocello uses existentials deliberately in a few places:

- `TTSEngineStore` holds the type-erased `AnyTTSEngineBackend`, fixed at app startup and never changed; the existential cost is paid once per call, not per token.
- `any MLXModelCoordinating` / `any AudioPreparationService` in `NativeEngineRuntime` (`NativeEngineRuntime.swift:414-415`) — injected dependencies, stable for the lifetime of the actor.

Do not introduce `any P` parameters inside the token loop or per-chunk audio path without profiling. If the loop calls a method on an existential, the dynamic dispatch + heap-boxing overhead can add up.

### 5.3 Generics and specialization

Generic functions are monomorphized (specialized) when the caller's concrete type is visible to the compiler. This removes abstraction cost. To help the optimizer:

- Keep generic hot-path code in the same module as its callers, or use `@inlinable` / `@usableFromInline` across modules.
- Avoid type-erasing a homogeneous collection into `[any P]` if all elements are the same type; use `[ConcreteType]` or a generic `Array<T>`.
- For MLX-specific wrappers in `QwenVoiceCore` or the owned Qwen3 runtime, small generic helpers that operate on `MLXArray` are usually specialized because the concrete type is always `MLXArray`. `QwenVoiceBackendCore` itself is the narrow provenance and policy layer.

---

## 6. Allocation patterns

### 6.1 Stack vs. heap vs. async slab

Swift allocates memory in three main places:

1. **Global memory** — fixed-size globals and static vars, initialized at load time.
2. **Stack / call frame** — synchronous local variables whose lifetime is scoped.
3. **Heap** — class instances, closures, escaping contexts, dynamically-sized locals, async continuations.

For synchronous functions, local values that fit in the call frame are essentially free (the stack pointer is adjusted once). For async functions, locals whose lifetime crosses an `await` are stored in the task's async slab allocator; this is faster than `malloc` but still more expensive than a synchronous call frame.

### 6.2 Minimizing heap allocations on the hot path

- Prefer value types for per-token intermediates.
- Avoid capturing local `var`s in escaping closures unless necessary; captured `var`s force heap allocation.
- Reuse buffers where possible: the clone-conditioning caches, and the sampler's cached scratch rows, which removed about 17K allocations per generation ([mlx-guide §7.3](mlx-guide.md#73-sampler-scratch-and-allocator-caches)).
- Use `reserveCapacity(_:)` on arrays that grow in a loop.

### 6.3 Closures and context allocation

Non-escaping closures are stack-allocated; escaping closures are heap-allocated and reference-counted. The long-form runner shows the pattern the codebase prefers: `IOSLongFormProjectRunner.run` (a `@MainActor` class in `Sources/iOS/Studio/IOSLongFormProject.swift`, compiled by both apps) takes its progress sinks as `@escaping @MainActor (IOSLongFormProgressSnapshot) -> Void` / `([IOSLongFormSegmentState]) -> Void` closures (`onProgress:` / `onSegmentsUpdated:`, `:826`), so every UI update is already isolated to the main actor and nothing needs an `@unchecked Sendable` relay object. Off-main work that must not block the actor (audio QC, duration probes) hops through `Task.detached(priority: .utility)` and returns a value (`IOSLongFormProject.swift:813-820`):

```swift
private func evaluateQC(path: String, expectedPauseCount: Int) async -> AudioQualityGate.Report {
    await Task.detached(priority: .utility) { @concurrent in
        AudioQualityGate.evaluate(
            url: URL(fileURLWithPath: path),
            expectedPauseCount: expectedPauseCount
        )
    }.value
}
```

Each escaping closure context is one heap allocation per run, not per token, so the cost is not on the hot path; keep it that way by passing snapshots (value types) through the closures rather than capturing mutable `var`s.

---

## 7. Reference counting and ARC

### 7.1 ARC is not free

Every strong reference copy is a retain; every last-use is a release. They are atomic and very fast, but in tight loops they show up as `swift_retain` / `swift_release` in Instruments. Common sources:

- Passing `Array`/`String`/`Data` across function boundaries.
- Copying structs that contain reference-typed fields.
- Protocol existentials that box heap-allocated values.
- Escaping closures that capture reference-typed locals.

### 7.2 How to reduce retain/release traffic

1. **Borrow instead of copy.** Read-only access to a value should borrow it. Swift usually does this automatically for local variables; for class properties it may need a defensive copy.
2. **Use `Span` / `InlineArray` where appropriate (Swift 6.2+).** `Span` gives non-escaping, zero-reference-count access to contiguous memory. `InlineArray` stores a fixed-size collection inline, eliminating COW uniqueness checks and heap allocation. Vocello targets iOS/macOS 26.0 and builds with the pinned toolchain (§2), which supports these types; they are the preferred replacement for unsafe buffer pointers in new binary/audio parsing code.
3. **Move large values across boundaries with `consume`.** The `consume` operator explicitly transfers ownership, helping the compiler avoid a retain/release pair.
4. **Avoid retain cycles.** The store and the player hold long-lived Combine sinks and notification observers; use `[weak self]` in every sink and observer closure.

### 7.3 Observed vs. guaranteed object lifetimes

Swift objects are guaranteed alive until their last use, but ARC optimizations may shorten the *observed* lifetime. Do not rely on `deinit` side effects happening at a specific point. If a resource must outlive a scope, use `withExtendedLifetime(_:_:)` explicitly — but prefer redesigning the API so the strong reference is held naturally.

---

## 8. Profiling workflow

### 8.1 When to profile

Profile before and after any non-trivial performance change. The project ships with several profiling hooks:

- `OSSignposter` intervals, in Instruments' Points of Interest and signpost tracks, correlate
  app-level phases with GPU activity: `AppPerformanceSignposts` (category `performance`; subsystem
  `com.qwenvoice.app` on macOS, `com.patricedery.vocello` on iOS), `NativeEngineRuntime`
  (`com.qwenvoice.engine` / `runtime`,
  `NativeEngineRuntime.swift:400`) and `GenerationOutputAdapter` (`com.qwenvoice.engine` /
  `generation`, `GenerationOutputAdapter.swift:90`). The decode-loop intervals are
  [mlx-guide §8.1](mlx-guide.md#81-os_signpost-and-xctrace)'s.
- Telemetry JSONL when `QWENVOICE_DEBUG=1` is set: one row per generation in
  `diagnostics/engine/generations.jsonl` under the `QwenVoice-Debug` data root
  ([mlx-guide §8.2](mlx-guide.md#82-reading-vocello-telemetry); schema in
  [`telemetry-and-benchmarking.md`](telemetry-and-benchmarking.md)).
- `MainThreadStallWatchdog` samples heartbeat delay per generation as
  `delayedHeartbeatCount50` / `delayedHeartbeatCount250` / `maximumDelayedHeartbeatMS`, with
  scheduled/completed counts and coverage. These are responsiveness samples, not an exhaustive
  enumeration of main-thread stalls.

### 8.2 Instruments templates

Start with:

1. **Time Profiler** — find hot Swift functions, `swift_retain`/`swift_release`, `platform_memmove`.
2. **Allocations** — find transient allocations and leaked objects.
3. **Metal System Trace** — CPU/GPU timelines, command-buffer scheduling, memory allocations,
   performance limiters and thermal state. Use it to find CPU/GPU bubbles, excessive sync points
   and memory growth, and to separate Swift CPU overhead from GPU work: CPU timers alone mislead
   under lazy evaluation.
4. **Swift Concurrency** — inspect actor contention and task priorities.

For engine traces, use the repository lane (`scripts/macos_test.sh profile custom:speed:`), which
launches or attaches by exact PID and validates the trace; tracing costs about 25%, so compare
fractions, not absolute times ([mlx-guide §8.1](mlx-guide.md#81-os_signpost-and-xctrace)).

### 8.3 Reading a Time Profiler trace

Useful filters:

- `swift_retain`, `swift_release` — reference-counting overhead.
- `swift_beginAccess`, `swift_endAccess` — runtime exclusivity checks; move state out of classes to eliminate them.
- `platform_memmove` — unexpected copies, often from `Data` / `String` slicing.
- `QwenVoice`, `QwenVoiceCore` — project code.

### 8.4 Profiling a unit test

WWDC 2025 demonstrated profiling a test from Xcode's test navigator (secondary-click the run button → Profile). This is the recommended way to isolate a parser or cache helper: write a small test that exercises the hot path, profile it, and compare before/after flame graphs.

### 8.5 Xcode Metal debugger / frame capture

The Metal debugger captures every Metal command in a window and shows per-encoder timelines, GPU
counters (occupancy, bandwidth, ALU utilization), shader source and assembly, and resource
dependencies. mlx-swift starts and stops a capture programmatically:

```swift
let trace = URL(fileURLWithPath: "/tmp/vocello.gputrace")   // must not exist yet
GPU.startCapture(url: trace)
// ... run generation ...
eval(output)
GPU.stopCapture(url: trace)
```

Its own documentation (`Source/MLX/GPU+Metal.swift:195-215` in the pinned checkout) lists three
requirements: MLX built with the `MLX_METAL_DEBUG` define (`.define("MLX_METAL_DEBUG")` in the
`Cmlx` target's `cxxSettings`), `MTL_CAPTURE_ENABLED=1` at launch, and a trace file that does not
exist yet. The pinned mlx-swift `Package.swift` does not set the define, so a capture needs a
locally modified mlx-swift build.

MLX does not expose per-operation GPU time. Frame capture and Instruments are the authoritative
tools; a completion handler (§13.4) times only command buffers you own.

### 8.6 Key GPU counters

| Counter | What it tells you |
| --- | --- |
| Compute Occupancy | How much of the GPU's thread capacity is in use. |
| Memory Bandwidth | System memory ↔ GPU traffic. High → bandwidth-bound. |
| ALU utilization | How busy the shader ALUs are. Low + high bandwidth = memory-bound. |
| Texture/Buffer limiters | Whether cache or sampler throughput is the bottleneck. |
| Tile memory load/store | Relevant if doing render passes; less so for pure compute. |

Start with **Performance Limiter** counters. They point to the slowest subsystem.

---

## 9. Project-specific patterns and invariants

### 9.1 Telemetry is zero-cost when off

`TelemetryGate.resolvedEnabled` (`TelemetryGate.swift:43`) is checked once per generation. If telemetry is off, no recorder, sampler, or writer is created. Signposts are near-zero when Instruments is not attached. This means performance work should usually be done with telemetry **on** (to see the numbers) but verified with telemetry **off** (to ensure the probe itself is not the optimization target).

### 9.2 iOS memory policy is Swift-layer driven

`NativeMemoryPolicyResolver` picks a policy per `NativeDeviceMemoryClass` and sets MLX's
process-wide `Memory.cacheLimit` in `apply(_:)`. The tiers, idle-unload windows and the debug-only
hard limit are [ARCHITECTURE §4.5](../ARCHITECTURE.md#45-memory-policy)'s; the clearing knobs and
their cost are [mlx-guide §5.3–§5.4](mlx-guide.md#53-per-tier-clearing-knobs)'s. The `iPhonePro`
tier is the tightest because the engine runs in-process and shares the app's Jetsam budget, so any
Swift change that increases long-lived heap usage directly threatens the iOS streaming guarantee.
The 2026 iPhone program that produced these tiers is recorded historically in
[`ios-engine-optimization.md`](ios-engine-optimization.md).

### 9.3 Core audio and frontend events both backpressure safely

Final PCM and frontend events travel on separate suspending channels
([ARCHITECTURE §4.4](../ARCHITECTURE.md#44-synthesis-pipeline) and
[§4.6](../ARCHITECTURE.md#46-streaming)). Producer suspension is intentional backpressure and must
wake correctly on cancellation. The consumer must drain continuously; a full router suspends rather
than evicting an audio-bearing preview event. Heavy output work belongs in `GenerationOutputAdapter`
after the mandatory audio drain.

### 9.4 Prewarm serialization

Two callers cannot enter MLX prewarm at once (§3.3). `PrewarmSlotGate` enforces it; its pairing
and cancellation rules are [ARCHITECTURE §4.7](../ARCHITECTURE.md#47-prewarm)'s, and
`PrewarmSlotGateTests` pins them.

---

## 10. Promotion/release checklist for performance changes

Ordinary commits and pushes on `main` use `scripts/dev.sh check` (advisory; the commit lint hook is
the only local block) and CI on `main` as the gate; nothing waits for a model, a device, or XCUITest
evidence. Before promoting or releasing a Swift performance change, complete the deeper checklist:

- [ ] Build the change optimized (`scripts/build.sh cli-optimized` for the CLI, `scripts/release.sh` for the apps), not just `-Onone`.
- [ ] Run the relevant benchmark (`vocello bench`, `scripts/ios_device.sh bench`, or a targeted Instruments profile) on a quiet host: timing lanes refuse a loaded host (`require_quiet_host`), and the gate bench compares medians of five warm takes and reports a loaded or throttled host as inconclusive (exit 3), never as pass or fail.
- [ ] Publish only validated records (schema v3 for generation lanes): `rtf` is wall ÷ audio (lower is faster) and is declared through `run.rtfDefinition`; `decodeSpeedupX` is the old inverted figure and never shares a comparison key with `rtf`; `toolchain.optimization` comes from the hash-bound build receipt via `scripts/lib/build_provenance.py`.
- [ ] Compare telemetry KPIs: `realTimeFactor` (lower is faster), `tokensPerSecond`, process-owned
      physical-footprint peak, `maximumDelayedHeartbeatMS`, and heartbeat coverage.
- [ ] Check for new `swift_retain` / `swift_release` hot spots in Time Profiler.
- [ ] On iOS, confirm memory stays flat with length and no trims appear.
- [ ] Run `scripts/dev.sh check` (or `scripts/dev.sh ci` for the full push-CI list, serially).
- [ ] When explicit frontend acceptance is requested, run the isolated UI lane:
      `scripts/ui_test.sh macos smoke`. Its absence never blocks promotion or release packaging.
- [ ] For audio-output changes, require clean deterministic QC plus the applicable fixed-seed
      language/prosody gates. Language verdicts name their recognizer family: Apple Speech in the
      iPhone app; QC v2's Qwen3-ASR and Whisper large-v3 on the Mac after the generator has exited,
      `qc.py language-bench`; one family is one witness and two must agree for consensus. Listening
      is optional annotation with no lane and never clears a machine failure.

---

## 11. Metal fundamentals

### 11.1 Core object model

| Object | Role |
| --- | --- |
| `MTLDevice` | A single GPU. Factory for queues, buffers, textures, libraries, pipelines. |
| `MTLCommandQueue` | Serial queue that submits command buffers to one GPU. Long-lived. |
| `MTLCommandBuffer` | Container for encoded GPU commands. Transient; commit → schedule → complete. |
| `MTLComputeCommandEncoder` | Writes compute commands (kernel dispatches, buffer bindings) into a command buffer. |
| `MTLComputePipelineState` | Compiled compute kernel. Expensive to create; cache and reuse. |
| `MTLLibrary` / `MTLFunction` | Compiled Metal shader library and a named function within it. |
| `MTLBuffer` | GPU-accessible memory buffer. On Apple Silicon, CPU-accessible too if `.storageModeShared`. |

§13 walks through a complete compute dispatch.

### 11.2 Execution hierarchy

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

### 11.3 Memory address spaces (MSL)

| Address space | Scope | Typical use |
| --- | --- | --- |
| `device` | Global GPU memory | Read/write arrays, weights, activations. |
| `constant` | Read-only constant cache | Small read-only parameters, lookup tables. |
| `threadgroup` | Shared within one threadgroup | Cooperative tilings, reductions, scratch pads. |
| `thread` | Per-thread registers/scratch | Temporary scalars/vectors. |

### 11.4 Storage modes on Apple Silicon

| Mode | CPU access | GPU access | Use case |
| --- | --- | --- | --- |
| `.storageModeShared` | Yes | Yes | Default on Apple Silicon; zero-copy CPU↔GPU. |
| `.storageModePrivate` | No | Yes | GPU-only intermediates; avoids coherency overhead. |
| `.storageModeMemoryless` | No | Tile memory only | Transient render targets; not backed by DRAM. |
| `.storageModeManaged` | Yes (explicit sync) | Yes | macOS discrete-GPU legacy; avoid on Apple Silicon. |

MLX allocates every array buffer shared, with untracked hazards
(`ResourceStorageModeShared | ResourceHazardTrackingModeUntracked`,
`backend/metal/allocator.cpp:16`).

---

## 12. Metal as MLX's GPU backend

What forces evaluation, `eval()` versus `asyncEval()`, and how the per-frame step pipelines are
[mlx-guide §2.2–§2.3](mlx-guide.md#23-eval-and-asynceval) and
[§4.3](mlx-guide.md#43-the-per-frame-step)'s. This section covers what happens below them. Unless
noted, `file:line` citations here are in the pinned mlx-swift 0.32.3 checkout (revision `19601207`),
under `Source/Cmlx/mlx/mlx/`.

### 12.1 Lazy evaluation → Metal command buffers

Each GPU stream has a `CommandEncoder` (`backend/metal/device.h:24`), held in a thread-local map
(`backend/metal/device.cpp:933-936`), that owns the stream's command queue, current command buffer
and compute encoder. Evaluated primitives append dispatches to the open buffer until
`needs_commit()` (`device.cpp:511-514`) sees more operations or megabytes than the per-buffer
limits, or until a synchronization point. `Device` sets those limits by GPU class: 20 operations /
40 MB on phone GPUs, 40 / 40 on base and Pro chips, 50 / 50 on Max and Ultra (`device.cpp:603-624`);
`MLX_MAX_OPS_PER_BUFFER` and `MLX_MAX_MB_PER_BUFFER` override them (`device.cpp:625-626`,
`utils.h:182-191`). Batching
amortizes submission cost; it does not merge kernels, which is `compile()`'s job (§12.3).

### 12.2 Kernel compilation and caching

mlx-swift builds MLX's Metal sources into a `default.metallib` in the `mlx-swift_Cmlx` bundle
(`Package.swift:229-230`) and builds MLX's JIT variant (`nojit_kernels.cpp` is excluded,
`Package.swift:293`), so some kernels are compiled from source at first use. `Device` caches
libraries by name (`library_map_`, `device.h:239`) and pipeline states per library
(`library_kernels_`, `device.h:244`); a custom kernel's library name hashes its source and compile
options (`backend/metal/custom_kernel.cpp:51`). The first use of a new kernel, shape or dtype pays a
compile, and later processes reuse the system's Metal cache: after the 0.32.3 move the first cold
prewarm took 6.5 s instead of 0.2 s ([mlx-guide §9.5](mlx-guide.md#95-what-the-0323-move-changed)).
That is one reason prewarm matters.

### 12.3 Kernel fusion and `compile()`

`compile()` traces a function and fuses its operations into fewer kernels. A change of input shape,
dtype or input count retraces it unless the function is compiled `shapeless: true`.
`MLX_DISABLE_COMPILE` turns compilation off process-wide (`compile.cpp:218-226`). Vocello compiles
the talker and code-predictor SwiGLU (`Qwen3TTSTalker.swift:33-37`,
`Qwen3TTSCodePredictor.swift:8-12` in the owned package) and the pass-indexed code-predictor plan
([mlx-guide §4.2](mlx-guide.md#42-the-code-predictor-and-its-compiled-plan)); declaring quantized
weights as compile `inputs:` was measured and rejected
([mlx-guide §7.4](mlx-guide.md#74-compile-quantized-parameters-as-inputs-rejected-and-the-pass-indexed-plan-shipped)).

`MLXFast.metalKernel` JIT-compiles a custom kernel from a source string; Vocello uses none. It
returns an `MLXFastKernel`, and the launch geometry goes on the call
(`Source/MLX/MLXFastKernel.swift:176`, `callAsFunction` above it):

```swift
let kernel = MLXFast.metalKernel(
    name: "scale",
    inputNames: ["x"],
    outputNames: ["y"],
    source: """
        uint elem = thread_position_in_grid.x;
        y[elem] = x[elem] * 2.0f;
        """)
let y = kernel(
    [x],
    grid: (1024, 1, 1),
    threadGroup: (256, 1, 1),
    outputShapes: [[1024]],
    outputDTypes: [.float32])[0]
```

### 12.4 MLX does not use Metal Performance Shaders

No Metal Performance Shaders symbol appears anywhere in the pinned mlx-swift checkout. Matmul,
quantized matmul, attention, convolution and element-wise work all run MLX's own Metal kernels
(`backend/metal/matmul.cpp`, `quantized.cpp`, `scaled_dot_product_attention.cpp`, `conv.cpp`). The
codec's SnakeBeta activation is plain element-wise MLX operations
(`Qwen3TTSSpeechTokenizer.swift:244-261` in the owned package), not a custom kernel. Quantization
mechanics and the bf16 compute dtype are
[mlx-guide §3.1](mlx-guide.md#31-weight-only-affine-groupwise-quantization)'s.

### 12.5 Unified memory assumptions

Unified-memory semantics are [mlx-guide §2.5](mlx-guide.md#25-unified-memory)'s. For Metal work
they mean:

- There is no discrete VRAM: model weights, KV caches and MLX's buffer cache compete with the app,
  the OS and the audio pipeline.
- On iOS, GPU allocations count directly against the Jetsam footprint limit (§14.1). On macOS the
  engine shares the app process (since 2026-09-15), so its footprint and the UI's are one budget
  against system RAM.
- Reading a scalar (`item()`) or printing forces a GPU→CPU sync; minimize this inside the token loop.
- `Memory.cacheLimit` and `Memory.clearCache()` are the levers for retained Metal buffer memory
  ([mlx-guide §5](mlx-guide.md#5-memory-management)).

### 12.6 Bandwidth vs. compute

Large batched transformer work is usually memory-bandwidth bound, which is why weight quantization
pays. Vocello's measured batch-1 decode loop is different: it is bound by kernel launches and
graph building, and the GPU idles about half of each step
([mlx-guide §7.1](mlx-guide.md#71-where-decode-time-goes)). Changes that remove launches (the fused
code-predictor RoPE, [mlx-guide §7.2](mlx-guide.md#72-fused-code-predictor-rope)) have paid more there than
changes that remove arithmetic.

### 12.7 Vocello's Metal memory telemetry

`IOSMemorySnapshot.capture(role:device:)` (`Sources/QwenVoiceCore/IOSMemorySnapshot.swift:192`)
records, among other fields:

- `availableHeadroomBytes` from `os_proc_available_memory()`
- `physFootprintBytes`, plus `graphicsFootprintBytes` (the IOAccelerator/Metal ledger), from `task_vm_info`
- `gpuAllocatedBytes` from `MTLDevice.currentAllocatedSize`
- `gpuRecommendedWorkingSetBytes` from `MTLDevice.recommendedMaxWorkingSetSize` (emulated under
  `QWENVOICE_SIMULATED_PHYSICAL_MEMORY_GB`)
- `hasUnifiedMemory` from `MTLDevice.hasUnifiedMemory`

`capture` falls back to one static `MTLDevice` (`IOSMemorySnapshot.swift:190`), and
`NativeTelemetrySampler` resolves its device once per generation
(`NativeTelemetrySampler.swift:799`), so sampling never creates Metal device objects per tick.

---

## 13. Direct Metal patterns (future-proofing)

Vocello does not use these patterns today; they are the starting point if a custom kernel or audio
DSP is needed.

### 13.1 Setting up a compute pipeline

```swift
import Metal

guard let device = MTLCreateSystemDefaultDevice(),
      let queue = device.makeCommandQueue()
else { fatalError("No Metal device") }

let library = try! device.makeDefaultLibrary(bundle: Bundle.main)
let function = library.makeFunction(name: "my_kernel")!
let pipeline = try! device.makeComputePipelineState(function: function)
```

### 13.2 Creating and populating a buffer

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

### 13.3 Dispatching a kernel

Choose threadgroup sizes that are multiples of the SIMD width and do not exceed
`maxTotalThreadsPerThreadgroup`; `dispatchThreads(_:threadsPerThreadgroup:)` handles non-uniform
grids without manual padding.

```swift
let commandBuffer = queue.makeCommandBuffer()!
let encoder = commandBuffer.makeComputeCommandEncoder()!
encoder.setComputePipelineState(pipeline)
encoder.setBuffer(buffer, offset: 0, index: 0)

let w = pipeline.threadExecutionWidth
let h = pipeline.maxTotalThreadsPerThreadgroup / w
let grid = MTLSize(width: count, height: 1, depth: 1)
encoder.dispatchThreads(grid, threadsPerThreadgroup: MTLSize(width: w, height: h, depth: 1))
encoder.endEncoding()
commandBuffer.commit()
```

### 13.4 Synchronization

Avoid `waitUntilCompleted()` on the hot path. Prefer completion handlers:

```swift
commandBuffer.addCompletedHandler { buffer in
    let ms = (buffer.gpuEndTime - buffer.gpuStartTime) * 1000
    print("GPU time: \(ms) ms")
}
commandBuffer.commit()
```

For safe buffer reuse across multiple in-flight buffers, use a `DispatchSemaphore` (triple-buffering pattern).

### 13.5 Interop with MLX arrays

`MLXArray.asMTLBuffer(device:noCopy:)` (`Source/MLX/MLXArray+Metal.swift:21` in mlx-swift) can
expose the underlying `MTLBuffer`. Caveats:

- The array must be evaluated first.
- Lifetime management matters: do not let the `MLXArray` be freed while the buffer is in use.
- Layout must match what the kernel expects (row-contiguous, dtype-aligned).
- Modifying the buffer from a custom kernel while MLX still holds the array can break lazy-evaluation invariants.

If Vocello ever adds a custom Metal kernel, the safest pattern is to copy the relevant slice into a dedicated `MTLBuffer`, process it, and copy back into a new `MLXArray`.

### 13.6 For future direct-Metal work

1. **Cache pipeline states, libraries, and command queues.** Creating `MTLComputePipelineState` is expensive.
2. **Size threadgroups as multiples of the SIMD width** (32) under `maxTotalThreadsPerThreadgroup`, and use `dispatchThreads` for non-uniform grids.
3. **Prefer `.storageModeShared` for CPU↔GPU data, `.private` for GPU-only temporaries.** Avoid `.managed` on Apple Silicon.
4. **Use `threadgroup` memory for cooperative kernels.** Keep it aligned and sized per threadgroup.
5. **Avoid `waitUntilCompleted` on the hot path.** Use completion handlers and triple buffering.
6. **Mind the tile architecture.** Apple GPUs are tile-based deferred renderers (TBDR): work is
   split into on-chip tiles, `.storageModeMemoryless` attachments live only in tile memory, and
   load/store actions (`MTLLoadAction`, `MTLStoreAction`) control tile traffic. For compute, the
   practical takeaway is `.private` for GPU-only intermediates and few CPU↔GPU round-trips.
7. **Profile before optimizing.** Bandwidth, occupancy, and limiter counters (§8.6) tell you where the real bottleneck is.

---

## 14. iOS-specific Metal considerations

### 14.1 Jetsam and per-process memory

iOS terminates an app whose physical footprint crosses its per-process limit, and Metal allocations
count against that limit. The increased-memory entitlement raises it
([enablement](ios-increased-memory-entitlement-request.md)) but creates no free memory;
`os_proc_available_memory()` stays the runtime read. The measured limits and peaks per OS are
[mlx-guide §5.5](mlx-guide.md#55-ios-memory-specifics)'s. At launch,
`IOSAppBootstrap.cloneCapableLoadProfile()` enables the clone encoders only when
`impliedProcessLimitBytes` (footprint plus available memory) is at least 4.5 GB
(`Sources/iOS/IOSAppBootstrap.swift:144-157`).

### 14.2 Thermal throttling and sustained performance

iOS devices throttle CPU/GPU frequencies when hot. `ProcessInfo.thermalState` exposes `.nominal`,
`.fair`, `.serious` and `.critical`. For long synthesis sessions, design for **sustained**
throughput, not burst. If thermal state rises, consider reducing quality, inserting idle gaps, or
unloading caches.

---

## 15. Optimization guidelines

### 15.1 For the MLX path (current)

1. **Batch work, then `eval` or `asyncEval`.** Avoid intermediate evaluations inside the token loop;
   the production step submits once per frame ([mlx-guide §4.3](mlx-guide.md#43-the-per-frame-step)).
2. **Minimize `.item()` / printing during generation.** These force a GPU→CPU sync.
3. **Change cache limits and clears only with evidence.** The per-tier values came from
   benchmarking ([mlx-guide §5.3](mlx-guide.md#53-per-tier-clearing-knobs)); do not raise the
   iPhone cache limit without measuring Jetsam behaviour on physical hardware.
4. **Profile with Metal System Trace** (§8.2), not CPU timers alone.

---

## 16. Troubleshooting

### 16.1 Unexpectedly slow generation

**Symptoms:** RTF rises (`rtf` = wall ÷ audio, lower is faster), long time-to-first-audio, high CPU wait time.

**Likely causes:** too many `eval()` calls splitting the graph; frequent `.item()` forcing GPU→CPU
sync; a cache limit too low, causing repeated buffer allocation; thermal throttling on iOS; a first
use paying kernel compilation (§12.2).

**Fix:** use `asyncEval`, batch work, check thermal state, and profile with Metal System Trace.

### 16.2 iOS Jetsam termination during generation

**Symptoms:** App killed with `jetsam(1) code:per-process-limit(7)`.

**Likely causes:** peak footprint above the entitled limit; a cache limit too high, retaining peak
buffers; clone reference priming adding speaker-encoder memory on top of the model.

**Fix:** lower `Memory.cacheLimit` (the internal-diagnostics override is
`QVOICE_IOS_MLX_CACHE_LIMIT_MB`), confirm the increased-memory entitlement is active in the signed
build, and check the launch-time clone gate (§14.1). The iPhone app always streams; the full-result
path is a CLI diagnostic ([mlx-guide §6](mlx-guide.md#6-streaming-vs-full-result-memory)).

### 16.3 Memory growth across generations

**Symptoms:** `physFootprint` rises over multiple utterances without returning to baseline.

**Likely causes:** MLX buffer cache not cleared between generations; Metal shader caches or driver
allocations accumulating; retained references to large `MLXArray` outputs; the known quantized-load
leak when models reload ([mlx-guide §3.5](mlx-guide.md#35-the-quantized-load-leak)).

**Fix:** check the generation-boundary clears, review retain cycles in the streaming session, and
watch `gpuAllocatedBytes` (`MTLDevice.currentAllocatedSize`) in telemetry.

### 16.4 Frame capture fails or shows no compute work

**Symptoms:** Empty `.gputrace`, no kernels visible.

**Likely causes:** MLX built without `MLX_METAL_DEBUG`; `MTL_CAPTURE_ENABLED=1` not set at launch;
the trace file already existed; capture started after the work had completed.

**Fix:** meet the §8.5 requirements and wrap the whole generation in `GPU.startCapture` /
`GPU.stopCapture`.

### 16.5 Custom kernel produces wrong results

**Symptoms:** Output is garbled, NaN, or shape-mismatched.

**Likely causes:** buffer layout assumption violated (row vs. column contiguous); thread indexing
off by one for non-uniform grids; a missing `threadgroup_barrier` in cooperative kernels; a race
from writing to a buffer still in use by MLX's lazy graph.

**Fix:** validate shapes and strides, use `dispatchThreads`, add barriers, and isolate the kernel
from MLX's graph with explicit copies (§13.5).

---

## 17. Appendix

### 17.1 Apple Silicon GPU bandwidth/TFLOPS reference

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

### 17.2 Useful environment variables

These belong to Metal and MLX and are read at runtime by those libraries. Vocello's own diagnostic
knobs, including the iPhone cache and memory-limit overrides, are registered in
`config/runtime-debug-knobs.json` and listed in
[mlx-guide §11](mlx-guide.md#environment-variables); they need an internal diagnostics build and
`QWENVOICE_DEBUG=1`.

| Variable | Effect |
| --- | --- |
| `MTL_CAPTURE_ENABLED=1` | Enable Metal GPU capture (§8.5). |
| `MLX_DISABLE_COMPILE` | Disable MLX `compile()` fusion process-wide (§12.3). |
| `MLX_MAX_OPS_PER_BUFFER` / `MLX_MAX_MB_PER_BUFFER` | Override MLX's per-command-buffer commit limits (§12.1). |

`MLX_METAL_DEBUG` is a compile-time define, not an environment variable (§8.5).

### 17.3 Further reading

- [`mlx-guide.md`](mlx-guide.md) — MLX runtime, lazy evaluation, streams, quantization.
- [`qwen3-tts-guide.md`](qwen3-tts-guide.md) — model architecture, generation modes, parameters.
- [`mimi-codec-guide.md`](mimi-codec-guide.md) — the neural audio codec implementation.
- [`ios-engine-optimization.md`](ios-engine-optimization.md) — historical iPhone memory/streaming program notes (current policy lives in `NativeMemoryPolicyResolver` and `docs/reference/native-engineering.md`).
- [`telemetry-and-benchmarking.md`](telemetry-and-benchmarking.md) — telemetry schema and benchmark procedure.
- [`CLAUDE.md`](../../CLAUDE.md) — build system, architecture, and critical invariants.
- Apple: [Explore Swift performance (WWDC 2024)](https://developer.apple.com/videos/play/wwdc2024/10217)
- Apple: [Improve memory usage and performance with Swift (WWDC 2025)](https://developer.apple.com/videos/play/wwdc2025/312)
- Apple: [Consume noncopyable types in Swift (WWDC 2024)](https://developer.apple.com/videos/play/wwdc2024/10170)
- Apple: [ARC in Swift: Basics and beyond (WWDC 2021)](https://developer.apple.com/videos/play/wwdc2021/10216)
- Apple: [Explore concurrency in SwiftUI (WWDC 2025)](https://developer.apple.com/videos/play/wwdc2025/266)
- Apple: [Explore large language models on Apple silicon with MLX (WWDC 2025)](https://developer.apple.com/videos/play/wwdc2025/298/)
- Apple: [Optimize Metal apps and games with GPU counters (WWDC 2020)](https://developer.apple.com/videos/play/wwdc2020/10603/)
- Apple: [Metal documentation](https://developer.apple.com/documentation/metal) and the [Metal Shading Language Specification](https://developer.apple.com/metal/Metal-Shading-Language-Specification.pdf)
- MLX: [documentation](https://ml-explore.github.io/mlx/) and [mlx-swift source](https://github.com/ml-explore/mlx-swift)
