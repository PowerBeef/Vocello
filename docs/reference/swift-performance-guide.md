---
status: active
owner: backend-and-platform
reviewed: 2026-08-29
summary: Swift 6 language and runtime performance reference for the apps and CLI — ARC, generics, isolation, and allocation patterns as they apply to this codebase.
sourceOfTruth:
  - project.yml
---
# Swift Performance Guide for Vocello

> **Living document.** A project-specific reference for Swift 6 language and runtime performance decisions that affect Vocello's macOS app, iOS app, and `vocello` CLI. It is meant to complement the backend-focused [`mlx-guide.md`](mlx-guide.md) and the model-focused [`qwen3-tts-guide.md`](qwen3-tts-guide.md). When this doc disagrees with the code, the code wins — fix this file.
>
> Last reviewed: 2026-08-29. Swift version: **6.0** (`SWIFT_VERSION: "6"` in `project.yml`).
> The latest manifest change only registers iOS support/attribution UI and resources; build
> configuration, optimization posture, concurrency mode, and runtime performance guidance are unchanged.

---

## 1. Why Swift performance matters here

Vocello is a local-first TTS application that runs a 1.7 B parameter Qwen3-TTS model on Apple Silicon. The actual compute lives in MLX, but the Swift layer orchestrates it: model loading, tokenization, the autoregressive decode loop, audio decoding, streaming chunk dispatch, memory-pressure reactions, and the UI that presents all of it. A slow or allocation-heavy Swift layer can:

- Starve the GPU by delaying the next token graph (`eval()` stalls).
- Inflate physical footprint and trigger Jetsam on iOS.
- Drop UI frames on the main thread during generation.
- Waste battery with unnecessary reference-counting traffic.

This guide is organized around the four low-level performance principles Swift is sensitive to:

1. **Function-call overhead** — static vs. dynamic dispatch, inlining, generics.
2. **Data representation** — inline (structs) vs. out-of-line (classes) storage, protocol types, value layout.
3. **Allocation volume** — heap, stack, async slab, and global memory.
4. **Copying / ownership traffic** — retain/release, exclusivity checks, copy-on-write.

If you change any of those areas in `Sources/`, update this doc with the new rationale and measured impact.

---

## 2. Build settings and toolchain

### 2.1 Single shippable config

`project.yml` defines only a `Release` configuration. There is no separate `Debug` build or `DEBUG` symbol. Two scripts compile the same config differently:

| Script | Optimization | Use case |
| --- | --- | --- |
| `scripts/build.sh build` | `-Onone`, incremental | Fast local dev loop. |
| `scripts/build.sh cli` | `-Onone`, incremental | Headless CLI dev loop. |
| `scripts/release.sh` | Xcode Release defaults (`-O`, whole-module) | Signed/notarized DMG. |

The release build relies on Xcode's default Release optimization level (`-O`) and whole-module compilation. We do **not** override `SWIFT_OPTIMIZATION_LEVEL`, `SWIFT_COMPILATION_MODE`, or `GCC_OPTIMIZATION_LEVEL` in `project.yml`; the scripts pass them as build-settings overrides. This keeps `project.yml` simple and lets the release path stay at Xcode defaults.

### 2.2 Swift 6 language mode

All Swift targets use `SWIFT_VERSION: "6"`. The project uses strict-concurrency-aware patterns (`Sendable`, `actor`, `@MainActor`) but does **not** set the experimental strict-concurrency build flag in `project.yml`. The compiler still enforces the Swift 6 data-race safety rules at the language level.

### 2.3 Compilation-condition switches

- `QW_UI_LIQUID` is set in the `Release` config for the macOS app target to enable Liquid Glass surfaces. It has no performance effect.
- The project has no Debug configuration or generic `DEBUG` symbol. Runtime diagnostic behavior is
  gated by `DebugMode.isEnabled`. Compile-time test isolation belongs in test targets or behind a
  narrowly named compilation condition; do not add hidden app behavior through `#if DEBUG`.

### 2.4 When to rebuild with `-O`

`-Onone` dev builds hide some performance behaviors:

- Stack promotion and inline storage are less aggressive.
- Generic specialization and cross-module inlining are reduced.
- Release-only ARC optimizations are absent.

For any performance work that claims a measured improvement, build with `scripts/release.sh` (or at least pass `-O` to `xcodebuild`) and validate on the target hardware. Do not optimize against `-Onone` timings alone.

---

## 3. Concurrency model and actor isolation

### 3.1 The basic split

Vocello's concurrency design is intentionally coarse-grained:

- **`@MainActor`** — SwiftUI views and view-models (`TTSEngineStore`, `AppModel`, `ContentView`).
- **`actor NativeEngineRuntime`** — the engine's mutable runtime state and MLX call serialization.
- **`actor NativePreparedCloneConditioningCache`** — mutable clone-conditioning cache with LRU eviction.
- **Background `Task` / `Task.detached`** — telemetry sampler, XPC event forwarding, audio decoding consumer.
- **`@unchecked Sendable` + manual locking** — `MainThreadStallWatchdog` uses `NSLock` because it predates `Mutex` and is reviewed for correctness.

This keeps data-race checking tractable and matches the natural boundaries of the app.

### 3.2 `@MainActor` and the UI

`TTSEngineStore` is a `@MainActor` `ObservableObject` that bridges Combine publishers from the XPC engine into SwiftUI state:

```swift
@MainActor
public final class TTSEngineStore: ObservableObject {
    @Published public private(set) var snapshot: TTSEngineSnapshot
    private var snapshotCancellable: AnyCancellable?

    init(engine: any MacTTSEngine) {
        ...
        snapshotCancellable = engine.snapshotPublisher
            .receive(on: DispatchQueue.main)
            .sink { [weak self] snapshot in
                self?.apply(snapshot: snapshot)
            }
    }
}
```

`.receive(on: DispatchQueue.main)` is defensive: even though the publisher should already emit on the main thread, the explicit scheduler prevents a misrouted stream from silently dropping state updates. Do not remove it for performance without a measured UI-telemetry improvement.

### 3.3 Actors as serialization points

`NativeEngineRuntime` is an `actor`. That gives it automatic mutual exclusion, but it is not a free abstraction:

- Every `await` on the actor is a potential suspension point.
- The actor's executor is a single serial queue; long synchronous work inside it blocks all other callers.
- The prewarm slot gate (`acquirePrewarmSlot` / `releasePrewarmSlot`) exists because the actor mutex alone is not enough: the prewarm body itself `await`s inside MLX, releasing actor access while the KV-cache is still mutating. See the invariant in `.agents/rules/backend-mlx.md`.

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
- Use `Task.detached(priority: .utility) { ... }` for long-lived background work that must outlive the initiating scope, such as draining XPC event streams. The XPC host drains `engine.events` on a detached utility task so the synchronous XPC encode cannot lag the producer; only `lastPublishedEvent` hops to `@MainActor`.
- Avoid `Task.sleep` busy-waiting on the hot path. The telemetry sampler uses `try? await Task.sleep(nanoseconds:)` with a device-tiered cadence (500 ms on 8 GB Mac / iPhone).

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

- `NativePreparedGeneration` is a large `Sendable` struct carried from preparation into streaming. It is created once per generation and passed by value; it is not copied repeatedly, so inline struct storage is fine.
- `NativePreparedCloneConditioningCache` is an `actor` class because it holds long-lived mutable caches that must be shared and isolated.
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

`ResolvedCloneConditioning` is large and contains an `MLXArray`. It is `@unchecked Sendable` and passed across actor boundaries, but it is created once per clone generation, so the copy cost is not on the hot token loop.

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

- `any MacTTSEngine` in `TTSEngineStore` — the concrete type is determined at app startup and never changes; the existential cost is paid once per call, not per token.
- `any MLXModelCoordinating` / `any AudioPreparationService` in `NativeEngineRuntime` — injected dependencies, stable for the lifetime of the actor.

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
- Reuse buffers where possible (e.g., the clone-conditioning caches, the streaming chunk buffer pool).
- Use `reserveCapacity(_:)` on arrays that grow in a loop.

### 6.3 Closures and context allocation

Non-escaping closures are stack-allocated; escaping closures are heap-allocated and reference-counted. In `TTSEngineStore.generateBatch`, the progress handler is wrapped in a `@Sendable` closure that captures a `BatchProgressRelay`. Because the relay is `final` and `@unchecked Sendable`, the closure context is heap-allocated, but the per-progress call is lightweight:

```swift
let forwardedHandler = progressRelay.map { relay in
    { @Sendable (fraction: Double?, message: String) in
        relay.send(fraction, message)
    }
}
```

`relay.send` immediately dispatches to `@MainActor`, so the heavy UI update runs on the main thread while the progress callback returns quickly on the engine thread.

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
2. **Use `Span` / `InlineArray` where appropriate (Swift 6.2+).** `Span` gives non-escaping, zero-reference-count access to contiguous memory. `InlineArray` stores a fixed-size collection inline, eliminating COW uniqueness checks and heap allocation. Vocello targets iOS/macOS 26.0 with Xcode 26.0; if the deployment toolchain supports these types, they are the preferred replacement for unsafe buffer pointers in new binary/audio parsing code.
3. **Move large values across boundaries with `consume`.** The `consume` operator explicitly transfers ownership, helping the compiler avoid a retain/release pair.
4. **Avoid retain cycles.** The engine-service and XPC layers hold references to delegates and connections; use `[weak self]` in Combine sinks and XPC reply handlers.

### 7.3 Observed vs. guaranteed object lifetimes

Swift objects are guaranteed alive until their last use, but ARC optimizations may shorten the *observed* lifetime. Do not rely on `deinit` side effects happening at a specific point. If a resource must outlive a scope, use `withExtendedLifetime(_:_:)` explicitly — but prefer redesigning the API so the strong reference is held naturally.

---

## 8. Profiling workflow

### 8.1 When to profile

Profile before and after any non-trivial performance change. The project ships with several profiling hooks:

- `OSSignposter` intervals in `AppPerformanceSignposts` and `NativeEngineRuntime`.
- Telemetry JSONL under `~/Library/Application Support/QwenVoice-Debug/diagnostics/` when `QWENVOICE_DEBUG=1` is set.
- `MainThreadStallWatchdog` samples heartbeat delay per generation as
  `delayedHeartbeatCount50` / `delayedHeartbeatCount250` / `maximumDelayedHeartbeatMS`, with
  scheduled/completed counts and coverage. These are responsiveness samples, not an exhaustive
  enumeration of main-thread stalls.

### 8.2 Instruments templates

For Swift-layer work, start with:

1. **Time Profiler** — find hot Swift functions, `swift_retain`/`swift_release`, `platform_memmove`.
2. **Allocations** — find transient allocations and leaked objects.
3. **Metal GPU** — separate Swift CPU overhead from actual GPU work (see [`mlx-guide.md`](mlx-guide.md)).
4. **Swift Concurrency** — inspect actor contention and task priorities.

### 8.3 Reading a Time Profiler trace

Useful filters:

- `swift_retain`, `swift_release` — reference-counting overhead.
- `swift_beginAccess`, `swift_endAccess` — runtime exclusivity checks; move state out of classes to eliminate them.
- `platform_memmove` — unexpected copies, often from `Data` / `String` slicing.
- `QwenVoice`, `QwenVoiceCore` — project code.

### 8.4 Profiling a unit test

WWDC 2025 demonstrated profiling a test from Xcode's test navigator (secondary-click the run button → Profile). This is the recommended way to isolate a parser or cache helper: write a small test that exercises the hot path, profile it, and compare before/after flame graphs.

---

## 9. Project-specific patterns and invariants

### 9.1 Telemetry is zero-cost when off

`TelemetryGate.resolvedEnabled` is checked once per generation. If telemetry is off, no recorder, sampler, or writer is created. Signposts are near-zero when Instruments is not attached. This means performance work should usually be done with telemetry **on** (to see the numbers) but verified with telemetry **off** (to ensure the probe itself is not the optimization target).

### 9.2 iOS memory policy is Swift-layer driven

`NativeMemoryPolicyResolver` picks a policy per `NativeDeviceMemoryClass`. The Swift code sets MLX `GPU.cacheLimit`, clears caches, and triggers idle-unloads. The iOS `iPhonePro` tier is the most aggressive because the engine runs in-process and shares the app's Jetsam budget. Any Swift change that increases long-lived heap usage directly threatens the iOS streaming guarantee. See [`ios-engine-optimization.md`](ios-engine-optimization.md).

### 9.3 Core audio and frontend events both backpressure safely

- Final PCM uses the classified session's frame-bounded suspending channel. Producer suspension is
  intentional backpressure and must wake correctly on cancellation.
- Frontend preview/status events use a separate suspending router with capacity 256 on macOS and 96
  on iOS.

`GenerationEventDeliveryProbe` measures accepted, terminated, and unobserved sends. The consumer
must drain continuously; a full router suspends rather than evicting an audio-bearing preview event.
Heavy output work belongs in `GenerationOutputAdapter` after the mandatory audio drain.

### 9.4 Prewarm serialization

The prewarm slot gate in `NativeEngineRuntime` is a project-specific invariant. Two callers cannot enter MLX prewarm simultaneously because the upstream KV cache is not thread-safe. The implementation uses `CheckedContinuation` and a FIFO waiter queue. When modifying this code, preserve the rule that a failed `acquirePrewarmSlot()` must not be balanced by a `defer { releasePrewarmSlot() }`.

---

## 10. Promotion/release checklist for performance changes

Ordinary development commits, pushes, pull requests, and merges use deterministic verification and
do not wait for models, a device, or XCUITest evidence. Before promoting or releasing a
Swift performance change, complete the deeper checklist:

- [ ] Build the change optimized (`scripts/release.sh` or `-O` xcodebuild), not just `-Onone`.
- [ ] Run the relevant benchmark (`vocello bench`, `scripts/ios_device.sh bench`, or a targeted Instruments profile).
- [ ] Compare telemetry KPIs: `audioSecondsPerWallSecond`, `tokensPerSecond`, process-owned
      physical-footprint peak, `maximumDelayedHeartbeatMS`, and heartbeat coverage.
- [ ] Check for new `swift_retain` / `swift_release` hot spots in Time Profiler.
- [ ] On iOS, confirm memory stays flat with length and no trims appear.
- [ ] Run `./scripts/check_project_inputs.sh`.
- [ ] When explicit frontend acceptance is requested, run the isolated UI lane:
      `scripts/ui_test.sh macos smoke`. Its absence never blocks promotion or release packaging.
- [ ] For audio-output changes, require clean deterministic QC plus the applicable fixed-seed
      language/prosody gates; optional listening is annotation only.

---

## 11. Further reading

- [`mlx-guide.md`](mlx-guide.md) — MLX runtime, lazy evaluation, streams, quantization.
- [`qwen3-tts-guide.md`](qwen3-tts-guide.md) — model architecture, generation modes, parameters.
- [`ios-engine-optimization.md`](ios-engine-optimization.md) — iPhone memory and streaming specifics.
- [`telemetry-and-benchmarking.md`](telemetry-and-benchmarking.md) — telemetry schema and benchmark procedure.
- [`AGENTS.md`](../../AGENTS.md) — build system, architecture, and critical invariants.
- Apple: [Explore Swift performance (WWDC 2024)](https://developer.apple.com/videos/play/wwdc2024/10217)
- Apple: [Improve memory usage and performance with Swift (WWDC 2025)](https://developer.apple.com/videos/play/wwdc2025/312)
- Apple: [Consume noncopyable types in Swift (WWDC 2024)](https://developer.apple.com/videos/play/wwdc2024/10170)
- Apple: [ARC in Swift: Basics and beyond (WWDC 2021)](https://developer.apple.com/videos/play/wwdc2021/10216)
- Apple: [Explore concurrency in SwiftUI (WWDC 2025)](https://developer.apple.com/videos/play/wwdc2025/266)
