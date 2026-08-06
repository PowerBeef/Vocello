# Vocello (QwenVoice) — Architecture Reference

> **Living document.** This is the code-verified architecture reference for how Vocello fits
> together: modules, runtime architecture, the request/generation
> lifecycle, persistence, model management, and telemetry. When this doc disagrees
> with the code, **the code wins** — fix this doc.
>
> Last reviewed: 2026-07-17.

## TL;DR

**Vocello** (repo *Vocello*, formerly *QwenVoice*; macOS app module `QwenVoice`, iOS app module
`QVoiceiOS`) is a local-first, private text-to-speech app for Apple Silicon. It
synthesizes speech **on-device** with **Qwen3-TTS** models accelerated through
**MLX** — native Swift packages, no Python runtime, no bundled weights, no cloud
generation. Models download on demand from Hugging Face after install.

One engine core (`QwenVoiceCore` / `MLXTTSEngine`) is hosted three ways:

| Host | Process model | Wired by | Used by |
| --- | --- | --- | --- |
| **macOS app** | Engine runs **out-of-process** in an XPC service (`QwenVoiceEngineService`) | `QwenVoiceNative` (XPC client + `TTSEngineStore`) | `Vocello.app` |
| **iOS app** | Engine runs **in-process** (`MLXTTSEngine` via `NativeRuntimeFactory`) | `Sources/iOS/TTSEngineStore.swift` | `VocelloiOS` |
| **CLI** | Engine runs **in-process** | `VocelloCLI` (`CLIRuntime`) | `vocello` binary |

Platforms: macOS 26+, iOS 26+, Apple Silicon (`arm64`), Xcode 26, Swift 6. Minimum
hardware support is an Apple Silicon Mac with 8 GB or iPhone 15 Pro or newer; canonical benchmark
hardware is separately defined as Mac mini M2 8 GB and iPhone 17 Pro.
Stable macOS release: **Vocello 2.1.0**. iOS is on-device-capable on `main` but
not yet distributed.

> Start with the canonical interactive [`project map`](project-map.html). For repo conventions,
> build commands, engine invariants, and release process, read [`CLAUDE.md`](../CLAUDE.md).
> This document provides the deeper architecture narrative.

---

## 1. Module & target dependency graph

The Xcode project is generated from [`project.yml`](../project.yml) (XcodeGen
2.46.0). There are 13 targets split into **cross-platform frameworks**,
**macOS-only frameworks + XPC service**, and **apps/CLI/tests**.

```mermaid
graph TD
    classDef app fill:#eef,stroke:#66f,stroke-width:2px;
    classDef fw fill:#efe,stroke:#3a3;
    classDef macfw fill:#fee,stroke:#c33;
    classDef spm fill:#ffd,stroke:#aa0,stroke-dasharray:3 3;

    QwenVoice["QwenVoice<br/>(macOS app · Vocello.app)"]:::app
    VocelloiOS["VocelloiOS<br/>(iOS app)"]:::app
    VocelloCLI["VocelloCLI<br/>(vocello CLI)"]:::app

    QwenVoiceNative["QwenVoiceNative<br/>(macOS XPC bridge)"]:::macfw
    QwenVoiceEngineService["QwenVoiceEngineService<br/>(macOS XPC service)"]:::macfw
    QwenVoiceEngineSupport["QwenVoiceEngineSupport<br/>(macOS runtime helpers)"]:::macfw
    QwenVoiceCore["QwenVoiceCore<br/>(engine core · iOS+macOS)"]:::fw
    QwenVoiceBackendCore["QwenVoiceBackendCore<br/>(provenance + policy vocabulary · iOS+macOS)"]:::fw

    GRDB["GRDB.swift"]:::spm
    MLXAudio["VocelloQwen3Core<br/>(MLXAudio Core, Codecs, TTS) — owned"]:::spm
    MLXSwift["MLXSwift<br/>(MLX, MLXRandom)"]:::spm
    SwiftHuggingFace["SwiftHuggingFace"]:::spm

    QwenVoice --> QwenVoiceNative
    QwenVoice --> QwenVoiceEngineService
    QwenVoice --> QwenVoiceEngineSupport
    QwenVoice --> QwenVoiceCore
    QwenVoice --> GRDB

    VocelloiOS --> QwenVoiceCore
    VocelloiOS --> GRDB

    VocelloCLI --> QwenVoiceCore
    VocelloCLI --> QwenVoiceEngineSupport

    QwenVoiceNative --> QwenVoiceCore
    QwenVoiceNative --> QwenVoiceEngineSupport
    QwenVoiceEngineService --> QwenVoiceCore
    QwenVoiceEngineService --> QwenVoiceEngineSupport
    QwenVoiceEngineSupport --> QwenVoiceCore
    QwenVoiceCore --> QwenVoiceBackendCore

    QwenVoiceCore --> MLXAudio
    QwenVoiceCore --> MLXSwift
    QwenVoiceCore --> SwiftHuggingFace
```

(SPM products are also linked directly by the macOS frameworks/service/CLI where
needed — e.g. `QwenVoiceCore` pulls `MLXRandom` for deterministic seeding. Only
the architectural edges are shown above; see `project.yml` for the exact link
graph.)

### Targets

| Target | Type | Platform | Module name | Bundle ID | Responsibility |
| --- | --- | --- | --- | --- | --- |
| `QwenVoice` | application | macOS | `QwenVoice` | `com.qwenvoice.app` | macOS SwiftUI app (`Vocello.app`). Links the full XPC stack. |
| `VocelloiOS` | application | iOS | `QVoiceiOS` | `com.patricedery.vocello` | iOS SwiftUI app; engine runs in-process. App Group `group.com.patricedery.vocello.shared`. |
| `VocelloCLI` | tool | macOS | `VocelloCLI` | `com.qwenvoice.cli` | Headless `vocello` binary; engine in-process. |
| `QwenVoiceCore` | framework.static | iOS + macOS | `QwenVoiceCore` | `com.qwenvoice.core` | **Engine core**: `TTSEngine` protocol, `MLXTTSEngine`, generation semantics, runtime, memory policy, telemetry. |
| `QwenVoiceBackendCore` | framework.static | iOS + macOS | `QwenVoiceBackendCore` | `com.qwenvoice.backend-core` | Backend provenance, generation defaults and policy vocabulary, finish reason, and the minimal synthesis abstraction. MLX loading, synthesis, and codecs live in `QwenVoiceCore` and the owned Qwen3 runtime. |
| `QwenVoiceEngineSupport` | framework.static | macOS | `QwenVoiceEngineSupport` | `com.qwenvoice.engine-support` | macOS runtime helpers + the **XPC wire protocol** (`EngineCommand`, envelopes, codec). |
| `QwenVoiceNative` | framework.static | macOS | `QwenVoiceNative` | `com.qwenvoice.native` | macOS app-facing XPC client/coordinator/store bridging XPC to SwiftUI. |
| `QwenVoiceEngineService` | xpc-service | macOS | `QwenVoiceEngineService` | `com.qwenvoice.app.engine-service` | Out-of-process engine host for crash isolation + memory containment. |
| `VocelloCoreTests` | bundle.unit-test | macOS | `VocelloCoreTests` | `com.qwenvoice.core.tests` | Core semantics, typed telemetry compatibility, and atomic/readable output contracts. |
| `VocelloiOSLogicTests` | bundle.unit-test | iOS | `VocelloiOSLogicTests` | `com.patricedery.vocello.logic-tests` | Standalone, app-host-free platform policy contracts for catalog/ledger, memory, cancellation, storage gating, and privacy-safe diagnostics. Ordinary CI compiles this bundle for the physical-device SDK. Xcode 26 does not support executing a tool-hosted app-free bundle on a physical-device destination, so it is compile-only. |
| `VocelloEngineIntegrationTests` | bundle.unit-test | macOS | `VocelloEngineIntegrationTests` | `com.qwenvoice.engine-integration.tests` | Injectable XPC client/transport lifecycle and correlation contracts; never launches frontend UI. |
| `VocelloMacUITests` | bundle.ui-testing | macOS | `VocelloMacUITests` | `com.qwenvoice.app.uitests` | Explicit native-app smoke and benchmark XCUITest lanes. |
| `VocelloiOSUITests` | bundle.ui-testing | iOS | `VocelloiOSUITests` | `com.patricedery.vocello.uitests` | Explicit paired-physical-iPhone smoke/benchmark lanes plus the isolated opt-in model-delivery lifecycle proof; never Simulator. |

### Testing lanes (see [`docs/reference/testing-runbook.md`](reference/testing-runbook.md))

| Layer | macOS | iOS | Development publishing policy |
| --- | --- | --- | --- |
| **Deterministic verification** | Core + XPC integration + `Qwen3RuntimeTests` + app build | Project-input checks + app and standalone logic-test bundle physical-device SDK compile | Required by ordinary CI; sufficient for commit, push, pull request, and merge |
| **Platform runtime gate** | `macos_test.sh gate` | `ios_device.sh gate` | Deterministic/device diagnostics; independent of XCUITest |
| **UI regression** | `ui_test.sh macos smoke\|benchmark` XCUITest | `ui_test.sh ios smoke\|benchmark` XCUITest on a paired physical iPhone | Explicit frontend QA only; never required for publishing or packaging |
| **Model-delivery lifecycle** | Isolated CLI install | `ui_test.sh ios model-download` on a paired physical iPhone | Opt-in diagnostic only; never part of smoke, benchmark, CI, or release |
| **Headless engine** | `vocello bench`, `lang-bench` | `bench`, `lang-bench` device diagnostics | Explicit performance/release QA |
| **UI evidence** | Named XCTest attachments from the native app | Named XCTest attachments from the physical iPhone | Independent explicit-acceptance artifacts |

Release packaging is deterministic and does not consume UI results. Frontend evidence remains
platform-specific and is created only when explicitly requested.

**Six shared schemes**: the four XcodeGen schemes, `QwenVoice` (macOS app + deterministic unit/integration tests), `VocelloiOS`
(iOS app), `VocelloMacUI` (explicit macOS XCUITest), and `VocelloiOSUI` (explicit physical-device
iOS XCUITest), plus the separately rendered `VocelloCLI` and `VocelloiOSLogic` (standalone iOS
policy XCTest) schemes. XcodeGen cannot directly render those tool and app-host-free test
schemes (verified unchanged through 2.46.0), so checked-in templates bind to their generated target IDs. The UI schemes are isolated from ordinary test actions; ordinary CI only
compiles `VocelloiOSLogic` for the generic device SDK and never executes it. A single shippable config,
**`Release`**, is the only config — there is no `Debug` config or generic `DEBUG` symbol.

### Key layering rule

`QwenVoiceBackendCore` ← `QwenVoiceCore` ← {macOS frameworks, apps, CLI}. BackendCore is a narrow,
dependency-light contract/provenance layer; `QwenVoiceCore` and the owned Qwen3 runtime implement model loading,
synthesis, streaming, and codecs. The
**iOS app deliberately does not link** `QwenVoiceNative`, `QwenVoiceEngineService`,
or `QwenVoiceEngineSupport` — those are macOS-only (the XPC stack). iOS reaches
the engine in-process through `QwenVoiceCore` alone. This single dependency
difference is what enforces the XPC-vs-in-process split.

---

## 2. Technology stack & SPM dependencies

SPM dependencies are declared in `project.yml` and **pinned to exact versions**
for backend determinism. `mlx-swift` and `mlx-swift-lm` must move **in lockstep**
(never one alone); don't float pins without a benchmark-gated review. The Qwen3 runtime
is an **owned monorepo core package** under `Packages/VocelloQwen3Core/` (see
[`reference/mlx-audio-swift-patching.md`](reference/mlx-audio-swift-patching.md)).

Resolved versions (`QwenVoice.xcodeproj/.../Package.resolved`):

| Package | Version | Role |
| --- | --- | --- |
| **mlx-swift** | `0.31.6` | MLX runtime bindings (`MLX`, `MLXRandom`). Bumped 2026-08-01 (Tier 3.1, `benchmarks/OPTIMIZATION.md` §Q); vendors mlx core 0.31.1, so the 26.0 OS floors stand. |
| **mlx-swift-lm** | `3.31.4` | LM utilities (through the owned Qwen3 core package). The 3.x major externalized the Hub/Tokenizers implementations, which is why swift-transformers is now a direct dependency. |
| **VocelloQwen3Core** | owned package derived from `mlx-audio-swift` `v0.1.2` | Stable first-party `VocelloQwen3Core` facade for model-bundle, capability, sampling, memory, synthesis, terminal, cancellation, and diagnostic contracts. Compatibility-preserved `MLXAudioCore`, `MLXAudioCodecs`, and `MLXAudioTTS` modules remain implementation surfaces for Qwen3-TTS load, tokenize, and decode. |
| **GRDB.swift** | `7.10.0` | SQLite for local `history.sqlite`. |
| **SwiftHuggingFace** | `0.9.0` | Hugging Face model download / hub client. |
| **swift-transformers** | `1.1.9` | Hub/Tokenizers implementation — a **direct** dependency of `MLXAudioTTS` since the mlx-swift-lm 3.x bump (pinned to the exact version the 2.x graph resolved). |
| swift-jinja | `2.4.2` | Chat/template formatting (transitive via swift-transformers). |
| yyjson | `0.12.0` | JSON parsing (transitive via swift-transformers). |
| swift-nio | `2.100.0` | Networking primitives (transitive, via SwiftHuggingFace/EventSource); minimum security baseline includes the `ByteBuffer` bounds fix. |
| swift-crypto | `4.4.0` | Hashing (transitive). |
| swift-collections | `1.4.1` | Deque/OrderedSet (transitive). |
| swift-atomics | `1.3.0` | Atomics (transitive). |
| swift-numerics | `1.1.1` | Numerics (transitive). |
| swift-system | `1.6.4` | System types (transitive). |
| swift-asn1 | `1.7.0` | ASN.1 parsing (transitive). |
| EventSource | `1.4.1` | Server-sent events (transitive). |
| yyjson | `0.12.0` | Fast JSON parser (transitive). |

Shipped models (`Sources/Resources/qwenvoice_contract.json`): Qwen3-TTS 1.7B in
**Speed (4-bit)** and **Quality (8-bit)** variants across three modes —
`pro_custom`, `pro_design`, `pro_clone` (see [§11 Model management](#11-model-management--contract)).

---

## 3. Runtime architecture: three engine hosts

All three hosts share one engine implementation — `MLXTTSEngine` (an
`@MainActor … ObservableObject` conforming to the `TTSEngine` protocol) — built
by `NativeRuntimeFactory.make(...)`. The hosts differ only in **where the engine
lives** and **how the UI talks to it**.

```mermaid
flowchart LR
    subgraph macOS["macOS app (Vocello.app)"]
        MacUI["SwiftUI views / coordinators"]
        MacStore["TTSEngineStore<br/>(QwenVoiceNative)"]
        MacClient["XPCNativeEngineClient<br/>+ XPCNativeEngineCoordinator"]
    end
    subgraph XPC["XPC service (separate process)"]
        Host["EngineServiceHost"]
        Core1["MLXTTSEngine (QwenVoiceCore)"]
    end
    subgraph iOS["iOS app (in-process)"]
        IOSUI["SwiftUI views / coordinators"]
        IOSStore["TTSEngineStore<br/>(Sources/iOS)"]
        Core2["MLXTTSEngine (QwenVoiceCore)"]
    end
    subgraph CLI["vocello CLI (in-process)"]
        CLIRuntime["CLIRuntime"]
        Core3["MLXTTSEngine (QwenVoiceCore)"]
    end

    MacUI --> MacStore --> MacClient -->|"NSXPCConnection"| Host --> Core1
    Host -.->|"events back over XPC"| MacClient
    IOSUI --> IOSStore --> Core2
    CLIRuntime --> Core3
```

- **macOS** — the engine runs **out-of-process** in `QwenVoiceEngineService`
  (`EngineServiceHost`). This isolates MLX crashes from the app and lets the
  service be **retired under memory pressure** (`shutdownWhenIdle`) to return
  memory that model unload can't (MLX heap fragmentation + Metal shader caches).
  The app talks to it over `NSXPCConnection` through `QwenVoiceNative`.
- **iOS** — the engine runs **in-process** (`MLXTTSEngine` built by
  `NativeRuntimeFactory`). The old ExtensionKit extension was removed because
  non-UI extensions are Jetsam-capped independently of the
  `increased-memory-limit` entitlement. iOS holds the engine behind its own
  `Sources/iOS/TTSEngineStore.swift`.
- **CLI** — `vocello` links `QwenVoiceCore` (+ `QwenVoiceEngineSupport`) and
  drives `MLXTTSEngine` in-process, reusing models the app already installed.

`AppEngineSelection.current()` returns `.native` on every platform; the actual
platform differences are enforced by the runtime factory and the XPC/in-process
wiring, not by engine selection.

---

## 4. Engine core (`QwenVoiceCore`)

### 4.1 The `TTSEngine` abstraction

Defined in `Sources/QwenVoiceCore/TTSEngine.swift`. `TTSEngine` is an
`@MainActor … ObservableObject` protocol; the streaming surface is split into a
companion `TTSEngineEventStreaming` protocol (`var events: AsyncStream<GenerationEvent>`).

`MLXTTSEngine` (`MLXTTSEngine.swift`) is the single concrete implementation. It
exposes generation, batch generation, model load/unload, prewarm, clone-reference
priming, cancellation, and capability queries; it publishes `loadState`,
`clonePreparationState`, `latestEvent`, and snapshot state. Around it sit several
actors that own the heavy, isolated work:

| Type | File | Role |
| --- | --- | --- |
| `NativeEngineRuntime` | `NativeEngineRuntime.swift` | Owns the transitional model-load/prewarm + clone/design conditioning bridge; serializes prewarm through the reentrancy gate. |
| `MLXModelLoadCoordinator` | `MLXModelLoadCoordinator.swift` | Loads/validates/unloads Qwen3-TTS checkpoints; manages the prepared-cache trust markers. |
| `VocelloQwen3Engine` | `Packages/VocelloQwen3Core/Sources/VocelloQwen3Core/Engine.swift` | Shipping Custom/Design/Clone generation mutation authority; holds one operation lease through explicit product finalization. |
| `GenerationOutputAdapter` | `GenerationOutputAdapter.swift` | QwenVoiceCore product authority for lossless frame drain, limiter, atomic WAV, Fast QC, telemetry, product terminal, and finalization acknowledgment. |
| `GenerationPlanShadowMapper` | `GenerationPlanShadowMapper.swift` | Builds privacy-separated product/core/evidence plans and compares them with independently resolved shipping values; shadow work never starts a second generation. |
| `NativeCloneSupport` | `NativeCloneSupport.swift` | Three-level clone cache (normalized audio → decoded `MLXArray` → prompt artifact). |
| `NativeMemoryPolicyResolver` | `NativeMemoryPolicyResolver.swift` | Per-device-tier MLX memory policy (see [§4.5](#45-memory-policy)). |
| `ActiveGenerationCoordinator` | `ActiveGenerationCoordinator.swift` | One active task, typed cancellation reason, and awaited terminal barrier. |
| `GenerationEventDeliveryProbe` | `GenerationEventDeliveryProbe.swift` | Per-generation bounded suspending frontend-event routing plus accepted/terminated/unobserved accounting; audio-bearing preview events are never evicted. |
| `UnsafeSpeechGenerationModel` | `UnsafeSpeechGenerationModel.swift` | `Sendable` single-owner pairing of the runtime actor with immutable post-load facts and request bindings; all mutation routes through `VocelloQwen3Engine`. |

### 4.2 Generation domain model

`GenerationSemantics.swift` + `SemanticTypes.swift`:

- `GenerationMode { custom, design, clone }`
- `GenerationRequest` — `mode`, `modelID`, `text`, `outputPath`, `shouldStream`,
  `streamingInterval`, `languageHint`, `payload`, `generationID`, `seed`,
  `variation`, plus batch (`batchIndex`/`batchTotal`).
  - `GenerationRequest.Payload`:
    - `.custom(speakerID:deliveryStyle:)`
    - `.design(voiceDescription:deliveryStyle:)`
    - `.clone(reference: CloneReference)`
  - `CloneReference { audioPath, conditioningMode, preparedVoiceID }`, where the non-optional
    `CloneConditioningMode` is either `.transcriptBacked(String)` or `.xVectorOnly`. The legacy
    `transcript` wire field remains decode-compatible and is derived from that typed mode.
- `GenerationEvent { .progress(GenerationProgress), .chunk(GenerationChunk),
  .completed(GenerationResult), .cancelled(GenerationCancellationSummary), .failed(String) }`.
  Cancellation is a typed terminal lifecycle outcome, not a failure string.
- `GenerationResult { audioPath, durationSeconds, finishReason, telemetrySummary }`
- `EngineLoadState { idle, starting, loaded(modelID), running(modelID: String?, label: String?, fraction: Double?), failed(message: String) }`
- `ClonePreparationState { idle, preparing(...), primed(...), failed(...) }`

`EmotionPreset.swift` defines the delivery/tone presets (`neutral`, `happy`,
`sad`, `angry`, `fearful`, `surprised`, `calm`, `whisper`).

### 4.3 Factory & paths

`NativeRuntimeFactory.make(...)` (`NativeRuntimeFactory.swift`) wires the whole
core from a contract manifest URL + a `NativeRuntimePaths` root:

```
NativeRuntimeFactory.make
  ├── ContractBackedModelRegistry(manifestURL)        // speakers/models/variants
  ├── LocalModelAssetStore(registry, root, seed)       // installed-model inventory
  ├── NativeAudioPreparationService(preparedAudioDir)  // 24 kHz PCM normalization
  ├── LocalDocumentIO(importedReferenceDir)            // user imports
  └── MLXTTSEngine(...)
        └── NativeEngineRuntime(modelLoadCoordinator, cloneSupport, ...)
              └── MLXModelLoadCoordinator(assetStore, hubCacheDirectory)
```

`NativeRuntimePaths.rooted(at:)` defines the on-disk layout (`models/`,
`cache/prepared_audio`, `cache/imported_references`, `cache/native_mlx`,
`cache/stream_sessions`, …).

### 4.4 Synthesis pipeline

`MLXTTSEngine.generate(_:)` runs this flow (see `GenerationOutputAdapter` in
`Sources/QwenVoiceCore/GenerationOutputAdapter.swift`):

```mermaid
flowchart TD
    Req["GenerationRequest"] --> Ensure["1. Ensure model loaded<br/>MLXModelLoadCoordinator.loadModel<br/>(validate Qwen3-TTS profile + prepared-cache trust)"]
    Ensure --> Cond["2. Prepare conditioning by mode"]
    Cond -->|"custom"| CW["prewarmCustomVoice(speaker, instruction)"]
    Cond -->|"design"| DW["warmDesignConditioning(voiceDescription)"]
    Cond -->|"clone"| CL["NativeCloneSupport.prepareCloneConditioning<br/>(normalize → decode MLXArray → prompt artifact)"]
    CW --> Reserve
    DW --> Reserve
    CL --> Reserve
    Reserve["3. VocelloQwen3Engine.reserveGeneration<br/>one inert lease + classified session"] --> Bind["4. GenerationOutputAdapter claims<br/>the mandatory audio consumer"]
    Bind --> Open["5. open(reservation) → Qwen prompt + MLX inference"]
    Open --> Codec["6. Mimi codec → materialized PCM<br/>(owned MLXAudioCodecs)"]
    Codec --> Channel["7. frame-bounded suspending channel<br/>ordered, single consumer, lossless"]
    Channel --> Lim["8. PCM16StreamLimiter + defect detection<br/>(clip/click/slew/dropout/nanInf)"]
    Lim --> WAV["9. AtomicPCM16WAVWriter + Fast QC"]
    WAV --> Out["10. product terminal + finalization acknowledgment<br/>GenerationResult"]
    Open -.->|"bounded suspending events"| Ev["preview/progress/status<br/>after output drain"]
    Lim --> QC["AudioQCReport → telemetry"]
```

`UnsafeSpeechGenerationModel` holds no model handle: it pairs the runtime actor with its
immutable post-load facts, and every lifecycle operation (load, prewarm, priming, clone
conditioning and artifacts, diagnostics) routes through `VocelloQwen3Engine`'s public surface.
The legacy compatibility SPI is retired (Phase 14b, 2026-07-23); the previously SPI-gated
symbols are internal to the package.

The shipping product-generation path is `VocelloQwen3Engine` plus its classified session and
QwenVoiceCore's `GenerationOutputAdapter`. Sampling and Qwen generation-memory settings remain
immutable request-owned values: sampling algorithm v2 gives every request an effective seed and a
fresh `MLXRandom.RandomState`, while talker/subtalker stages and per-request cache/window policy
travel with the request instead of mutating process-global generation state.

Explicit reserved/generating/aborting ownership prevents an
abort-owned reservation from reopening generation and makes duplicate aborts join one finalization.
Typed cache-trim/full-unload relief transfers the generation lease directly into critical relief;
admission reopens only after the selected release completes and the relief lease revalidates.
Rejected atomic relief claims clear their matching ownership before querying the session barrier;
an ordinary acknowledgment accepted on either side of that rollback therefore cannot strand the
generation lease.
Clone prompts remain actor-owned behind epoch-bound handles. The default retained-handle capacity is
one; larger explicit capacities evict least-recently-used handles. Explicit release makes future
lookups fail closed without invalidating a prompt already captured by a reservation. Noncritical
cache trim preserves handles, while model reload, critical trim, and full unload invalidate them.

`VocelloQwen3Engine` models one actor-owned operation lease; `ClassifiedGenerationSession` provides a single-consumer,
frame-bounded suspending audio channel and independent prepared/progress/model-terminal/diagnostic
semantics; QwenVoiceCore's `GenerationOutputAdapter` preserves the existing limiter, telemetry,
atomic WAV, Fast-QC, and public-result behavior while returning the stale-safe product-finalization
token. Synthetic tests also prove that cancelling a producer task
while it is suspended by channel backpressure removes that pending send and wakes it with
`CancellationError`. The channel backpressures the direct caller-isolated Qwen producer for Custom,
Design, and Clone.
`config/runtime-refactor-contract.json` is the machine-readable status
record, and [`decisions/runtime-streaming-quality-convergence.md`](decisions/runtime-streaming-quality-convergence.md)
defines the promotion boundaries. The source cutover, focused macOS plus physical-iPhone
Custom/Design/Clone proof, clean Phase 0 controls, and the canonical matrices all passed:
`overallPromotion: passed` (2026-07-20). Per-phase status lives solely in the contract's
`phaseStatus` block — cite it rather than restating phase state here (the human summary is the
phase table in [`development-progress.md`](development-progress.md)).

### 4.5 Memory policy

`NativeMemoryPolicyResolver` (`NativeMemoryPolicyResolver.swift`) classifies the
device into `NativeDeviceMemoryClass` and resolves an `NativeMemoryPolicy` per
tier + mode + batch. Classification: iPhone → `.iPhonePro`; Mac ≤10 GB →
`.floor8GBMac`; ≤24 GB → `.mid16GBMac`; else `.highMemoryMac`. Diagnostic override
`QWENVOICE_FORCE_MEMORY_CLASS` is propagated over the `initialize` handshake only when the
`QWENVOICE_DEBUG` master gate is enabled.

| Tier (`NativeDeviceMemoryClass`) | MLX cache | Clone slots | Idle-unload | Token clear cadence | Post-batch trim |
| --- | --- | --- | --- | --- | --- |
| `.floor8GBMac` | 256 MB | 1 | 120 s | 50 | `.hardTrim` |
| `.mid16GBMac` | 512 MB | 8 | 600 s | 50 | — |
| `.highMemoryMac` | 1 GB | 16 | never (`nil`) | 200 | — |
| `.iPhonePro` | 128 MB* | 1 | 30 s | 50 | — |

\* iPhone cache default 128 MB, diagnostically overridable with
`QVOICE_IOS_MLX_CACHE_LIMIT_MB` only behind `QWENVOICE_DEBUG`.
A hard `Memory.memoryLimit` is **only** set on iPhone **and only** when the debug-gated
`QVOICE_IOS_MLX_MEMORY_LIMIT_MB` override is present — so **there is no hard memory limit in
production**, and no Quality→Speed OOM fallback. `apply(_:)` configures only MLX's unavoidable
process-wide allocator limits at the host boundary. The request-varying clear cadence, chunk clear,
and optional sliding-window talker KV policy are resolved into
`VocelloQwen3MemoryConfiguration` and converted to the immutable internal
`Qwen3RequestMemoryPolicy` before generation. `QVOICE_TALKER_KV_WINDOW` remains debug-gated and is
resolved before the model is invoked; there is no mutable process-global request-tuning authority.
Trim levels (`NativeMemoryTrimLevel`): `.softTrim`, `.hardTrim`, `.fullUnload`.
`NativeMemoryPressureResponseExecutor` records every kernel signal before acting. Warning pressure
performs the existing non-interrupting `.softTrim`; critical pressure first requests typed
`.memoryPressure` cancellation, closes admission continuously, and awaits the active generation's
terminal barrier before the same relief operation may clear runtime state and reopen admission.

### 4.6 Streaming

`MLXTTSEngine.events` is an `AsyncStream<GenerationEvent>` view over a per-generation custom
suspending router. Capacity is platform-specific (`MLXTTSEngine.swift`):

- **macOS**: 256 events.
- **iOS**: 96 events for the memory-tight in-process engine.

`GenerationEventDeliveryProbe` records accepted, terminated, and unobserved preview/progress/status/
terminal sends. When capacity is full, the producer suspends until the sole consumer advances;
audio-bearing events are not evicted. Final PCM is independently drained losslessly from the
classified session into the incremental WAV before corresponding preview publication.

`NativeStreamingPreviewDataPolicy` controls whether the output adapter publishes live preview after
the corresponding frames have been written. Preview uses the suspending frontend-event router, not
an `AsyncStream.bufferingNewest` policy. The
`QWENVOICE_STREAMING_PREVIEW_DATA=off` diagnostic override is inert unless `QWENVOICE_DEBUG`
enables the master runtime gate. Output is 24 kHz mono Int16 PCM WAV.

### 4.7 Prewarm

`NativeEngineRuntime` serializes prewarm through a reentrancy gate —
`acquirePrewarmSlot()` / `releasePrewarmSlot()`. **Never** pair a throwing
`try? await acquirePrewarmSlot()` with an unconditional `defer { releasePrewarmSlot() }`
(on a throw the slot isn't held and the defer releases someone else's slot).
Prewarm identity keys are per mode (e.g.
`custom:<speakerID>:<instruction-hash>`); `NativeCustomPrewarmPolicy` is `.eager`
on capable tiers and `.skipDedicatedCustomPrewarm` on `.floor8GBMac`. Depth is
tunable via `CustomVoicePrewarmDepth { .full, .skipDecoderBucket, .skipStreamStep }`.

### 4.8 Voice cloning cache

`NativeCloneSupport` (actor) keeps a three-level cache keyed by audio fingerprint,
conditioning mode, and transcript hash: normalized reference audio → decoded `MLXArray` →
`VoiceClonePromptArtifact`. Transcript-backed mode persists the speaker embedding, reference
codes, and transcript identity; audio-only mode persists a genuine speaker-embedding-only
x-vector prompt. Those modes never share cache or artifact identity. Capacities per tier come
from `NativeMemoryPolicyResolver.cloneCacheCapacity(...)`.

Speaker embeddings use the official Qwen magnitude-mel contract, not the shared Whisper-style mel
helper. The runtime validates finite canonical `float32 [1, D]` storage against the decoded speaker
encoder and talker dimensions, then casts only the prefix slot to the talker's compute dtype. The
prompt identity includes the model repository, pinned revision, artifact version, installed
integrity-manifest digest, runtime-profile signature, and speaker-feature version. Changed weights
or an algorithm change therefore cannot reuse an older in-memory or persisted embedding.

### 4.9 Cancellation

`MLXTTSEngine` admits one model-mutating operation at a time and conforms to
`ActiveGenerationCancellable` on every platform. `ActiveGenerationCoordinator` records one typed
reason (`user`, `memoryPressure`, `superseded`, or `shutdown`), cancels the registered task, and
awaits its terminal barrier before ownership is released or trim/unload begins. The engine emits
`.cancelled(GenerationCancellationSummary)` separately from `.failed`; coordinators must not persist
a late result after cancellation. Every terminal path restores `loadState` and completes exactly
once.

### 4.10 Audio prep & QC

`AudioPreparation.swift` normalizes reference audio to the canonical 24 kHz /
1-channel / 16-bit little-endian PCM format and emits quality warnings.
`PCM16StreamLimiter` applies lookahead limiting and flags defects
(`clip`, `click`, `slew`, `dropout`, `nanInf`); the verdict + flags become an
`AudioQCReport` on the telemetry record.

`GenerationQualityReport`, `QualityGateRegistry`, and `QualityReviewPolicy` now provide a typed,
deterministic foundation for Fast, Standard, and Canonical gate composition. They are not the
shipping quality authority yet: persisted Fast QC plus the existing specialized ASR, prosody,
delivery, and benchmark validators remain authoritative until one end-to-end report/scheduler is
cut over. The Python prosody analyzer is independently shipping algorithm v2, which uses two
bounded passes rather than a duration-sized PCM/frame matrix.

### 4.11 Spoken-text and long-form planning status

Long-form v4 is the shipping macOS path (stages A–E since 2026-07-23; contract keys `longForm`,
`longFormV4`). `SpokenTextPlanning.swift` + `LongFormPlanning.swift` plan the project (typed
transformation risk, UTF-8 ranges, protected spans, CJK-aware boundary precedence, per-segment
stable IDs and deterministic sub-seeds, a delivery-validated 300-unit runtime token ceiling);
`BatchGenerationRunner` executes one ordinary sequential streaming take per segment with mandatory
per-segment engine Fast QC and live preview; `BoundedLongFormAssembler` joins the persisted PCM16
segments in fixed blocks into one atomic WAV with a privacy-safe frame map; `LongFormManifestV4`
records plan + execution + assembly + replacement evidence fail-closed, with schema-v3 documents
readable only as a limited legacy summary. Resume reuses saved takes, single-segment regeneration
appends revision-≥2 replacement lineage, and migration v5 History project columns group the joined
output as one accepted row. Line-separated batch runs on the same sequential streaming path.
iOS long-form remains a later arc. See
[`reference/long-form-generation.md`](reference/long-form-generation.md).

---

## 5. Request lifecycle — macOS

The macOS app never touches `MLXTTSEngine` directly. It goes through the XPC
stack:

```mermaid
sequenceDiagram
    autonumber
    participant V as SwiftUI View
    participant C as Coordinator<br/>(CustomVoice/VoiceDesign/<br/>VoiceCloning)
    participant S as TTSEngineStore<br/>(QwenVoiceNative)
    participant X as XPCNativeEngineClient<br/>+ XPCNativeEngineCoordinator
    participant H as EngineServiceHost<br/>(XPC service)
    participant E as MLXTTSEngine<br/>(QwenVoiceCore)
    participant B as GenerationChunkBroker

    V->>C: generate(draft)
    C->>S: generate(request)
    S->>X: generate(request)
    X->>X: encode EngineRequestEnvelope(.generate)
    X->>H: perform(payload) via NSXPCConnection
    H->>H: reserve admission before timing/task/forwarder side effects
    H->>E: generate(request)
    E-->>H: AsyncStream<GenerationEvent>
    Note over H: drained on Task.detached(.utility)<br/>(off MainActor); lastPublishedEvent hops to MainActor
    H-->>X: handleEvent(payload) — reverse XPC
    X-->>B: publish(event) on MainActor
    B-->>V: Combine publisher (live preview)
    E-->>H: GenerationResult
    H-->>X: EngineReplyEnvelope(.generationResult)
    X-->>S: GenerationResult
    S-->>C: GenerationResult
    C->>C: GenerationPersistence.persist + autoplay
```

**XPC wire protocol** (`Sources/QwenVoiceEngineSupport/EngineServiceIPC.swift`):
a single envelope method —
`QwenVoiceEngineServiceXPCProtocol.perform(_:withReply:)` — carrying an
`EngineCommand`. The reverse event channel is
`QwenVoiceEngineClientEventXPCProtocol.handleEvent(_:)`. Codec:
`EngineServiceCodec` (= `QwenVoiceWireCodec`); envelopes are versioned
(`QwenVoiceWireSchema`) with a legacy fallback path.

`EngineCommand` cases (the full surface): `initialize`, `ping`, `loadModel`,
`unloadModel`, `ensureModelLoadedIfNeeded`, `prewarmModelIfNeeded`,
`prefetchInteractiveReadinessIfNeeded`, `ensureCloneReferencePrimed`,
`cancelClonePreparationIfNeeded`, `generate`,
`cancelActiveGeneration`, `listPreparedVoices`, `enrollPreparedVoice`,
`deletePreparedVoice`, `clearGenerationActivity`, `clearVisibleError`,
`shutdownWhenIdle`.

**Service retirement**: under memory pressure the app calls `shutdownWhenIdle`;
the service refuses while a generation is active, then exits. The client marks
this `expectedRetirement` (no error UI, no auto-reconnect) and lazily relaunches
on next use. Events are drained off `MainActor` so the synchronous XPC encode
can't lag the producer; only `lastPublishedEvent` hops to `MainActor`.

macOS generation flows through three coordinators in `Sources/ViewModels/`:
`CustomVoiceCoordinator`, `VoiceDesignCoordinator`, `VoiceCloningCoordinator`
(all `@MainActor @Observable`). Each builds a `GenerationRequest` from its draft
and runs it through the shared `GenerationLifecycleExecutor`
(`Sources/ViewModels/GenerationLifecycleExecutor.swift`, extracted in the 2026-08
UI review's wave 2): the executor owns the single-take prepare/run/cancel
sequencing against `TTSEngineStore.generate(...)` — a nil prepared take aborts
silently, a throw is the failure path, and `cancelActiveWork` resets task,
generating-flag, and player state in one place. `VoiceCloningCoordinator`
additionally primes the clone reference via `ensureCloneReferencePrimed(...)`.

---

## 6. Request lifecycle — iOS

iOS links only `QwenVoiceCore`, so the engine is in-process and the XPC stack is
absent. The iOS app has its **own** `Sources/iOS/TTSEngineStore.swift` (a
distinct type from the macOS one) that wraps the in-process `MLXTTSEngine`.

```mermaid
sequenceDiagram
    autonumber
    participant V as SwiftUI View (Studio)
    participant C as StudioGenerationCoordinator
    participant S as TTSEngineStore<br/>(Sources/iOS)
    participant E as MLXTTSEngine<br/>(in-process, QwenVoiceCore)
    participant P as GenerationPersistence

    V->>C: start
    C->>S: generate(request)
    S->>E: generate(request) (same process)
    E-->>S: GenerationEvent (96-event suspending router)
    E-->>S: adapter-owned preview after lossless WAV drain
    S-->>V: live preview (in-process, no XPC)
    E-->>S: GenerationResult
    S-->>C: GenerationResult
    C->>P: persist + inline player
```

iOS casts the engine to capability protocols at runtime
(`TTSEngineRuntimeControlling`, `NativeMemoryReporting`, `ActiveGenerationCancellable`) rather than depending on a
concrete type. Key iOS behaviors:

- **No batch on iOS** (removed 2026-07-02, maintainer decision): the affordance was
  dead UI (`onBatch` nil everywhere; native engine unsupported, Jetsam risk).
  `IOSBatchSheet` + `IOSBatchGenerationCoordinator` deleted; macOS batch unaffected.
  If batch returns it must be sequential streaming, validated on device.
- **Typed cancellation barrier**: user and memory-pressure cancellation flow through
  `cancelActiveGeneration(reason:)`; the active task reaches `.cancelled` before ownership release,
  trim, or unload, and no cancelled result is persisted.
- **Thermal gate** (2026-07-02): `TTSEngineStore.startThermalObservation` records
  thermal transitions and blocks PROACTIVE warm work (prewarm/clone priming) at
  serious/critical; generation is never thermally blocked
  (`QVOICE_IOS_THERMAL_GATE=off` is a debug-gated diagnostic override).
- **Interruption recorder** (2026-07-02): `IOSInterruptionRecorder` (CXCallObserver +
  UIApplication lifecycle) runs during headless device diagnostics only; events land in
  `device-diagnostics-done.json` as `interruptions` so doomed runs self-report calls/backgrounding.
- **Memory posture**: `.iPhonePro` policy; `Qwen3TTSMemoryCaches.clearAll()` on
  hard-trim/unload/failure (macOS preserves cache warmth).
- **Clone load profile**: `.fullCapabilities` vs `.iOSProductionDefault`
(`.withoutCloneEncoders`) depending on the entitled memory limit.
- **Hardware gate**: `IOSDeviceSupport.isSupportedHardware` (iPhone 15 Pro+).

---

## 7. CLI (`VocelloCLI`)

`Sources/VocelloCLI/CLIRuntime.swift` (`@MainActor struct CLIRuntime`) bootstraps
the in-process engine the same way the iOS app does — `NativeRuntimeFactory.make`
over a data directory — and reuses models already installed by the app. It is
both a user-facing generator and the deterministic driver for
benchmarks/quality gates (no Python, no bundled weights).

`bootstrap` resolves the contract via `locateManifestURL()`, which searches (in
order): the bundled resource (shipped CLI), repo-relative
`Sources/Resources/qwenvoice_contract.json` (dev + benchmarks), next to the
executable, then walking up from the cwd. Commands (`VocelloMain.swift`):
`generate`, `custom`/`design`/`clone`, `batch`, `voices`, `speakers`, `models`,
`bench`. stdout is machine-readable (a path, or JSON with `--json`); progress
goes to stderr. Full reference: [`reference/cli.md`](reference/cli.md).

---

## 8. App surfaces

### macOS app (`Sources/`, module `QwenVoice`)

- Entry: `QwenVoiceApp.swift` → `ContentView.swift`. Layout is a
  `NavigationSplitView` with a `SidebarItem` enum: `customVoice`, `voiceDesign`,
  `voiceCloning`, `history`, `voices`, `settings`.
- State: predominantly `@Observable`. Coordinators, `ModelManagerViewModel`,
  and (since the 2026-08 UI review's W2-A migration) `TTSEngineStore` are
  `@MainActor @Observable` — the store bridges snapshot/performance-activity
  Combine publishers for the non-observation consumers; `AudioPlayerViewModel`
  remains `ObservableObject`.
- `Sources/Services/` — app-level services: `DatabaseService` (GRDB),
  `BatchGenerationRunner`, `GenerationTelemetryMerger`,
  `MacGenerationWarmupCoordinator`, `MacEngineServiceLifecycleCoordinator`
  (idle XPC service retirement), `AudioService`, `WaveformService`.
- `Sources/ViewModels/` — `ModelManagerViewModel` (model install/variant).
- `Sources/QwenVoiceCore/` — `HuggingFaceDownloader` (SwiftHuggingFace + SHA-256).
- `Sources/Models/` — `TTSModel`, `Generation` (GRDB record), `Voice`,
  `GenerationDrafts` (`CustomVoiceDraft` / `VoiceDesignDraft` /
  `VoiceCloningDraft`), `TTSContract` (contract loader).

### iOS app (`Sources/iOS/`, module `QVoiceiOS`)

- Entry: `QVoiceiOSApp.swift` → `QVoiceiOSRootView.swift`. Four-tab IA
  (`IOSAppTab`): **Studio / Voices / History / Settings**.
- Dependencies container: `IOSAppDependenciesContainer` / `IOSAppBootstrap`
  (`@ObservableObject`) holding `registry`, `engine` (`TTSEngineStore`),
  `modelManager`, `modelInstaller`. Built via `makeBackend(...)`.
- Model downloads: `IOSModelDownloadCoordinator` (shared download engine wrapper).
- Studio: `IOSStudioCanvas.swift` with a mode segmented control
  (custom/design/clone), input area, generate button, and live-preview rail.
  Sheets under `Sources/iOS/Sheets/` (e.g. `IOSVoicePreviewPlayer`).
- Reference import: `IOSVoicesView` presents a native `fileImporter` for WAV, MP3, AIFF, and M4A;
  `RootView.onOpenURL` routes supported documents opened from Files through the same production
  flow. `TTSEngineStore.importReferenceAudio` / `LocalDocumentIO` materializes the security-scoped
  audio and adjacent `.txt` transcript sidecar into app-owned storage. `IOSRecordVoiceSheet` then
  collects the visible name/transcript, enrolls the saved voice, and hands it to Studio Clone.
  `Info.plist` declares `public.audio`, in-place document opening, and Files sharing for this route.
- iOS UI conventions: `IOSScrollView` (not raw `ScrollView`) for vertical
  surfaces, `TabDock`, voice previews from `Resources/voice-previews/`.

---

## 9. Cross-platform sharing

- **`Sources/SharedSupport/`** is compiled into **both** apps — the dual-platform
  UI-layer share point: `AudioPlayerViewModel` (playback surface; its
  AVAudioEngine/player-node live-preview mechanics were extracted into
  `Services/LiveStreamingPlaybackEngine` in the 2026-08 UI review's wave 2 —
  FIFO buffer bookkeeping and graph control live there, session policy stays in
  the view model),
  `ReferenceClipRecorder` + `ClipReviewPlayer` (reference capture),
  `VoiceClipTranscriber` (on-device transcription), `GenerationPersistence`
  (async GRDB writes), `LanguageSelectionPresentation`, `VoiceDesignBriefCatalog`,
  `AppGenerationTimeline` + `MainThreadStallWatchdog` (telemetry), and
  `Database/GenerationMigrations.swift`.
- **`Sources/iOSSupport/`** is the iOS-only counterpart to macOS
  `Services/` + `QwenVoiceEngineSupport/`: runtime helpers + model wrappers
  coordinating through the **App Group** container
  (`group.com.patricedery.vocello.shared`) and a `UserDefaults` suite.
- macOS uses `Sources/Services/` + the XPC stack; iOS uses `Sources/iOS/` +
  `iOSSupport/` + the in-process engine. The divergence point is exactly the
  XPC-vs-in-process choice from [§3](#3-runtime-architecture-three-engine-hosts).

---

## 10. Persistence & storage

**GRDB** (`history.sqlite`) via `Sources/Services/DatabaseService.swift` (macOS)
and `Sources/SharedSupport/Database/GenerationMigrations.swift`. `generations`
table (current schema, after migrations `v1_create_generations` →
`v2_add_sortOrder` → `v3_drop_sortOrder` → `v4_index_generations_createdAt` →
`v5_add_long_form_project` → `v6_add_seed`):

| Column | Type | Notes |
| --- | --- | --- |
| `id` | integer | autoincrement PK |
| `text` | text | not null |
| `mode` | text | not null — `custom` / `design` / `clone` |
| `modelTier` | text | not null — `pro` |
| `voice` | text | speaker id (nullable) |
| `emotion` | text | delivery style (nullable) |
| `speed` | double | reserved/unused (nullable) |
| `audioPath` | text | not null — `file://…/output.wav` |
| `duration` | double | seconds (nullable) |
| `createdAt` | datetime | not null, default `CURRENT_TIMESTAMP` |
| `longFormProjectID` | text | owning long-form plan digest; NULL for ordinary takes (v5) |
| `longFormRole` | text | `segment` / `joined` within a project; NULL otherwise (v5) |
| `seed` | integer | the engine's effective sampling seed, UInt64 stored as its Int64 bit pattern; NULL for pre-v6 rows (v6, DP-15). Powers "Pin seed for new takes" in History: a pinned seed rides every subsequent request of that mode's draft, reproducing the take with identical settings |

Indexes `idx_generations_createdAt` on `createdAt` and
`idx_generations_longFormProjectID` on `longFormProjectID`. `DatabaseService`
uses a GRDB `DatabaseQueue` with async, off-main writes (`saveGenerationAsync`).

**Locations** (release vs debug):

- macOS: `~/Library/Application Support/QwenVoice/` (debug: `QwenVoice-Debug/`).
- iOS: App Group `group.com.patricedery.vocello.shared/Vocello/`.

Layout under the root: `models/` (downloaded HF weights, staged in
`.qwenvoice-downloads/`), `outputs/{CustomVoice,VoiceDesign,VoiceCloning}/`,
`voices/`, `history.sqlite`, and `cache/` (`prepared_audio`,
`imported_references`, `normalized_clone_refs`, `stream_sessions`). Full detail:
[`reference/privacy-storage.md`](reference/privacy-storage.md).

History storage fails closed. Database open, migration, read, write, and delete failures are reduced
to typed privacy-safe classifications; an unavailable store never masquerades as an empty history
and never turns a destructive operation into a successful no-op. History surfaces enter a degraded
state and disable deletion until a read succeeds, preserving the existing database and audio. iOS
exposes a visible Retry action; macOS retries when History reloads or is re-entered and must not be
described as having a dedicated Retry control until one exists.

**`UserDefaults` keys**: `QwenVoice.DebugModeEnabled` (debug toggle, mirrored to
`TelemetryGate`), `vocello.voiceCloningConsent.v1` (visible Settings-owned clone-consent acknowledgment), per-mode variant choices
(`QwenVoice.{CustomVoice,VoiceDesign,VoiceCloning}.VariantID`), and UI state
(`QwenVoice.LastSelectedSidebarItem`, `QwenVoice.LastVoiceCloningSavedVoiceID`).

### Repository-local generated output

`config/build-output-policy.json` is the machine-readable owner and lifetime contract for native
repository output under `build/`. Local development has two persistent Xcode platform caches,
`build/cache/xcode/macos/` and `build/cache/xcode/ios-device/`, plus one serialized shared package
checkout at `build/cache/xcode/source-packages/`. The owned Qwen3 Core runtime uses its separate
policy-owned SwiftPM scratch cache and must not leave `.build` state in the source tree.

Release, XcodeBuildMCP, package-resolution, CI, and compile-safety DerivedData are isolated below
`build/scratch/`; no third persistent platform cache is permitted. Validator-owned telemetry,
profiles, UI results, crash data, and UUID-matched current dSYMs live below `build/artifacts/`.
Signing, archives, exports, and packages live below `build/dist/` and are never removed by routine
or aggressive cache cleanup. The compatibility paths `build/Vocello.app` and `build/vocello` are
symlinks to the canonical macOS cache products, not copied binaries.

Every supported build records an atomic `last-build.json` provenance stamp with its producer,
scheme, configuration, destination, architecture, optimization, signing class, DerivedData, and
package store. Local macOS app, XPC, CLI, and relevant framework products are arm64-only. Preserved
dSYMs are accepted only when their Mach-O UUIDs match the current app/XPC or iOS product. Run
`python3 scripts/build_output_policy.py status|validate`; use
`scripts/clean_build_caches.sh --routine --dry-run` before bounded cleanup. The generated owner and
lifetime table is maintained in [`reference/privacy-storage.md`](reference/privacy-storage.md).
The website has an independent Vite lifecycle: `website/dist/` is website-owned deployment output,
not a native DerivedData, evidence, symbol, or distribution path in the build-output manifest.

The same manifest owns lifecycle rules below artifact roots and minimum free-space floors for heavy
lanes. UI retention keeps the latest passing result per platform/lane, preserves matching benchmark
publication-repair evidence, compacts resolved failures and unrepairable unpublished runs, and
includes the opt-in model-download lane. Failed Instruments traces remain explicit diagnostics:
the status inventory reports them separately and only `--compact-profile-failure RUN_ID` (or a
newer profile of the same platform/kind) may remove their raw trace. Persistent caches can be
reclaimed independently with `--cache macos|ios|packages|runtime`; ordinary successful builds never
run a global cleanup as a side effect.

---

## 11. Model management & contract

The contract — `Sources/Resources/qwenvoice_contract.json` — is the canonical
schema. It defines `defaultSpeaker`, `speakers` (+ `speakerMetadata`), and a
`models[]` array. Each model entry carries: `id`, `name`, `tier`, `mode`,
`folder`, `huggingFaceRepo`, `huggingFaceRevision`, `iosDownloadEligible`,
`estimatedDownloadBytes`, `outputSubfolder`, `requiredRelativePaths[]`, and
`variants[]` (speed/quality with platforms + hardware recommendation).

The generated cross-platform artifact contract is
`Sources/Resources/qwenvoice_production_model_catalog.json`, governed by
`config/model-catalog-schema-v2.json` and exact evidence in
`config/model-artifact-receipts.json`. It is **complete**: all three Speed and all three Quality
artifacts have exact pinned revisions, file sizes, and SHA-256 digests for every required file.
No missing identity may be inferred or fabricated. Schema v2 identifies the identical
`speech_tokenizer` component shared by all six artifacts using separate content and compatibility
identities plus ordered source artifacts. macOS, CLI, and iOS all resolve an `ArtifactDeliveryPlan`:
an already verified component store omits those exact bytes from the network, while a new install
publishes immutable content-addressed blobs and presents ordinary regular files in the model folder
as hard links. Legacy schema-v1 catalog documents remain read-compatible. Deterministic
`python3 scripts/model_catalog_contract.py validate --require-complete` proves catalog integrity,
while resolving a schema-v2 delivery plan now authenticates every catalog file in an existing
installation and automatically migrates or repairs its shared-component presentation. A failed
local authentication contributes no reusable bytes and leaves the downloader to repair from the
network. Live validation across all six macOS artifacts and the three iOS Speed artifacts remains
explicit pending quality work rather than a claim made by static validation or local reconciliation.

The shipped model ids:

| Model ID | Mode | Speed repo (4-bit) | Quality repo (8-bit) |
| --- | --- | --- | --- |
| `pro_custom` | Custom Voice | `mlx-community/Qwen3-TTS-12Hz-1.7B-CustomVoice-4bit` | `…-8bit` |
| `pro_design` | Voice Design | `mlx-community/Qwen3-TTS-12Hz-1.7B-VoiceDesign-4bit` | `…-8bit` |
| `pro_clone` | Voice Cloning | `mlx-community/Qwen3-TTS-12Hz-1.7B-Base-4bit` | `…-8bit` |

`ContractBackedModelRegistry` loads the contract and is expanded per-platform
(`expandedForPlatform(_:deviceClass:includeBaseAliases:)`). Built-in speakers:
`aiden`, `ryan`, `vivian`, `serena`, `uncle_fu`, `dylan`, `eric`, `ono_anna`,
`sohee`.

**iOS** also bundles `qwenvoice_ios_model_catalog.json` (an iOS-eligible subset,
served at `bundle://vocello/ios/catalog/v1/models.json` via
`Info.plist … QVoiceModelCatalogURL`) and `voice-previews/` (24 kHz mono Int16
WAVs named by speaker id, played by `IOSVoicePreviewPlayer`).

**Download** (`Sources/QwenVoiceCore/HuggingFaceDownloader.swift`): consume the catalog's exact
pinned file descriptors, stage, verify exact size plus **CryptoKit SHA-256**, atomically swap the directory, and
persist `.qwenvoice-model-integrity.json`. A verified-artifact receipt avoids a second full-file
hash in the same process; a relaunch rehashes staged data once before reuse. macOS and CLI own
terminal foreground-session teardown. iPhone owns one bundle-aware background session for the app
lifetime, an atomic schema-v2 ledger, exact task adoption, durable delegate staging, and UIKit
completion deferral until postprocessing is durable. Explicit Cancel discards staging; Retry keeps
verified files. Typed transient retries cover connection loss and HTTP 408/429/5xx, while permanent
failures remain terminal. Shared URLSession callbacks use a serial delegate queue; durable file
staging is sequenced before terminal continuation, and cumulative progress is bounded per task while
the exact final byte count is always delivered.
TLS/filesystem/configuration errors fail without retry. Compact local diagnostics are capped at 60
records and 5 MB and contain no raw URLs or absolute paths. Downloads come from Hugging Face over
HTTPS; **no cloud inference**. iOS catalog validation: `scripts/check_ios_catalog.sh`. Headless
install: `vocello models install <id>` (CLI) or the app Settings UI. Full lifecycle and storage
contract: [`reference/model-delivery.md`](reference/model-delivery.md).

**macOS test fixtures:** UI smoke and bench lanes with `QWENVOICE_DEBUG=1` read
`QwenVoice-Debug/models`; the test driver symlinks that path to the canonical
`QwenVoice/models` store. See [`reference/testing-runbook.md`](reference/testing-runbook.md)
"Model readiness"
and [`scripts/lib/test_models.sh`](../scripts/lib/test_models.sh).

---

## 12. Telemetry

Telemetry is **off in production** and on only when `TelemetryGate.isEnabled` —
resolved from `QWENVOICE_DEBUG` (1/true/on/yes) or
`QWENVOICE_NATIVE_TELEMETRY_MODE`, then mirrored to `UserDefaults` and
propagated to the engine over the `initialize` handshake. All diagnostic writers respect
`TelemetryGate.resolvedEnabled` — when the gate is off, no JSONL is appended.

Environment-variable ownership is explicit. `config/runtime-debug-knobs.json` registers every
supported key and classifies production-affecting overrides, bounded observability, and
test-target-only device diagnostics. Production-affecting values are read only through
`RuntimeDebugGate` and remain inert unless `QWENVOICE_DEBUG` is enabled. Likewise,
`config/concurrency-safety.json` is the authoritative inventory and justification for owned
`@unchecked Sendable` and other unsafe concurrency declarations; unregistered exceptions fail
`scripts/runtime_security_contract.py`.

Records are written by the `GenerationTelemetryJSONLSink` actor as JSONL under
`…/QwenVoice[-Debug]/diagnostics/`:

- `app/generations.jsonl`
- `engine/generations.jsonl`
- `engine-service/generations.jsonl` (macOS)
- `generations-merged.jsonl` (merged by `Sources/Services/GenerationTelemetryMerger.swift`)
- `*/native-events.jsonl` (chunk gaps, warm-admission, XPC retirement — gated)
- `<documents>/generation-failures.jsonl` (`GenerationFailureDiagnosticLogger` — gated,
  privacy-reduced schema v2, capped at 200 entries and 256 KiB)

`GenerationTelemetryRecord` schema v8 remains the shipping and publishable versioned Codable
record keyed by `generationID`
with `layer { engine, engineService, app, merged }`. New validation consumes typed
`FrontendGenerationMetrics`, `EngineTransportMetrics`, `BackendGenerationMetrics`, and
`GenerationOutputMetrics`, plus typed model/runtime identity. The generation sampler starts before
model preparation, adds lifecycle boundary samples to its 500 ms cadence, and reports capture time,
lateness, effective interval, drift, resource deltas, and safe run context. Frontend timing calls
playback what it can prove—**scheduled**, not acoustically audible—and reports sampled delayed-heartbeat
counts with coverage plus typed playback queue, continuity, and underrun health. The legacy timing/counter/note dictionaries remain serialization compatibility
output and v1–v7 rows still decode. Engine rows also stamp free-form provenance notes:
script identity (`promptChars`/`promptDigest` — the script text only, never the delivery
instruction), the resolved language hint, sampling seed evidence, the bench `delivery`
cell stamp, and — for any instructed take — the delivery-instruction receipt
(`instructChars`/`instructDigest`) that the delivery harness verifies fail-closed against
the bench manifest's instruction echo
([`docs/reference/delivery-harness.md`](reference/delivery-harness.md) §4). The transport layer records request acceptance, first-chunk,
session/chunk/order/terminal evidence; the backend records typed stages/timings/counters, final barrier,
atomic output, process-owned memory, and audio QC v3's separate pre-limiter-instability and
persisted-WAV written-output verdicts. Schema v8 adds absolute-uptime sample alignment, independent
memory/thread/headroom/Metal capture success and coverage, total-RAM/implied-process-limit context,
start/end/delta/peak memory fields, aligned extrema snapshots, and explicit app/engine lifecycle
boundaries. Publishable benchmark-evidence v2 binds exact verbose sidecars and rejects <95%
coverage, capture failures, critical pressure, memory warnings/exits, `hardTrim`, and `fullUnload`.
macOS UI/XPC aggregates pair app and engine samples by uptime; independent process peaks are never
summed. Older telemetry remains decodable but cannot enter memory-qualified trends.
No telemetry persists raw script, transcript, path, or voice description. The generation-failure
log stores only an allowlisted error code/classification, lifecycle stage, known model identifier,
mode, text length, streaming flag, and timestamp; reflected errors, localized messages, stack
symbols, URLs, and arbitrary metadata are never written.
Aggregate with `scripts/summarize_generation_telemetry.py`; UI-driven tests join matching typed
records by `generationID` before accepting a take.
Logs are budget-capped (`QWENVOICE_DIAGNOSTICS_MAX_MB`, default ~8 MB, pruned
oldest-first); raw `*.jsonl` is gitignored; committed summaries must be ≤256 KB.

`GenerationStreamingTelemetryV9` is the complete target contract for the convergence program. It
models plan/policy digests, separate model and product terminals, codec/materialized/written/preview
frame counts, frame-bounded channel pressure, exact chunk ranges, XPC sequence evidence, and
first-render observation metadata. Complete v9 documents are now written, validated, and published
as sidecars by `GenerationStreamingTelemetryV9Publication`
(`*.streaming-telemetry-v9.json`) where the producer can prove every enumerated observation, and
shipping schema-v8 rows continue to embed the nested `GenerationStreamingTelemetryTransitionV9`
projection — the contract's `phaseStatus` records this as complete-sidecar authority with a v8
envelope (`config/runtime-refactor-contract.json`, `telemetryV9`). Operational guidance and
publication gates continue to require telemetry v8 and benchmark-evidence v2; the v8 envelope
remains the record of authority for the merger, validator, summarizer, and benchmark-history
publisher.

Retained-memory qualification is separate from Instruments profiling. The versioned
`retained-memory-v1` policy runs fixed Custom→Design→Clone Speed/medium sequences and limits
within-mode first-to-last retained-take physical-footprint growth to 5% of physical RAM. Successful lanes
publish `memory-qualification`; `profile --kind memory` records exact-PID CPU Profiler,
Allocations, VM Tracker, and signposts. iOS MetricKit daily aggregates are bounded, local-only field
diagnostics and are never attributed to a benchmark take.

---

## 13. Security, entitlements & platform restrictions

**macOS** (`Sources/QwenVoice.entitlements`):
- App sandbox **disabled** (`com.apple.security.app-sandbox = false`) — MLX needs it.
- `com.apple.security.cs.allow-unsigned-executable-memory` + `disable-library-validation` (MLX JIT).
- `files.user-selected.read-write` (output folders), `device.audio-input` (microphone).
- Release uses hardened runtime + Developer ID signing/notarization; local dev auto-signs with an Apple Development identity so TCC grants survive rebuilds.

**iOS** (`Sources/iOS/VocelloiOS.entitlements`):
- App Group shared container.
- `com.apple.developer.kernel.increased-memory-limit` — raises the Jetsam ceiling for model load.

**Info.plist usage descriptions**: `NSMicrophoneUsageDescription` (reference
clip recording), `NSSpeechRecognitionUsageDescription` (on-device transcript
auto-fill; `requiresOnDeviceRecognition` only, nothing leaves the device; macOS
requires Siri enabled). `ITSAppUsesNonExemptEncryption = false`.

All generation, recording, transcription, and model storage happen locally.
`Sources/PrivacyInfo.xcprivacy` declares no tracking and no collected data types.

Repository supply-chain and publication controls are also security boundaries. External GitHub
Actions are pinned by full SHA through `config/toolchain.json`; CI performs dependency review,
scheduled CodeQL, and deterministic website/native checks. Release candidates produce SPDX and
CycloneDX SBOMs, checksums, provenance/attestation, and a validated
`config/release-evidence-contract.json` evidence set before a draft Release is created. The emitted
schema-v2 `release-evidence.json` binds the clean tracked-and-untracked source identity, required
input digests, and a hashed `release-verification.json` bundle. Every required-step manifest must
come from the managed release subprocess in the same invocation, use the contract-bound command
identity for that step, match the source identity, and complete inside the six-hour freshness
window; a substituted command, prewritten PASS file, or partial manifest is never accepted. The
iOS candidate first binds the deterministic macOS gate and generic iOS device-SDK compile as its
managed `platform-readiness` step. It then binds a privacy-safe schema-v2 archive/IPA verification summary that
proves bundle version/build, bundle identifier, arm64 UUID and signature-normalized code continuity,
root privacy-manifest identity, App Group and increased-memory entitlements, locally trusted and
profile-authorized signing, and team/App ID prefix consistency. Only the exported IPA must carry an App Store profile,
Apple Distribution signature, and no `get-task-allow`; valid two-phase development-signed archives
remain accepted.
Draft assets are downloaded and digest-verified before publication, which remains the final transaction. See
[`SECURITY.md`](../SECURITY.md), `.github/workflows/security.yml`, and
[`reference/macos-release-qa.md`](reference/macos-release-qa.md).

---

## 14. Apple frameworks used

Most-frequent imports across `Sources/**/*.swift`:

| Framework | Usage |
| --- | --- |
| Foundation | Base types, JSON, files, processes. |
| SwiftUI | macOS + iOS UI. |
| AppKit / UIKit | Platform-specific UI. |
| AVFoundation | Audio playback, recording, PCM/WAV. |
| Combine | Reactive event delivery (`GenerationChunkBroker`). |
| Observation | `@Observable` state. |
| Speech | On-device recognition for clone transcripts. |
| NaturalLanguage | Language detection. |
| CryptoKit | SHA-256 download integrity. |
| Metal / MLX | GPU compute via MLX. |
| CoreMedia / Accelerate | Media timing/types, DSP. |
| UniformTypeIdentifiers | File-type handling. |
| OSLog / os | Logging + signposts. |
| XPC (`NSXPCConnection`) | macOS engine-service IPC. |

---

## 15. Key design decisions

- **No Python backend** — everything runs natively in Swift + MLX.
- **No bundled weights** — models download on demand from Hugging Face.
- **Single shippable config** — `Release` only; debug is runtime-gated (`DebugMode`), not compiled.
- **macOS engine out-of-process via XPC** for crash isolation + retireable memory; **iOS engine in-process** (ExtensionKit removed over Jetsam caps).
- **Local-first / privacy-first** — scripts, history, recordings, and generated audio stay on-device unless exported.

---

## 16. Glossary

| Term | Meaning |
| --- | --- |
| `TTSEngine` | `@MainActor ObservableObject` protocol — the engine abstraction (`Sources/QwenVoiceCore/TTSEngine.swift`). |
| `MLXTTSEngine` | The single concrete `TTSEngine`, built on MLX. |
| `TTSEngineStore` | Observable engine facade. macOS one wraps the XPC client (`QwenVoiceNative`); iOS one wraps the in-process engine (`Sources/iOS`). |
| `NativeRuntimeFactory` | Builds the whole core (registry, asset store, audio prep, engine) from a contract + paths root. |
| `NativeEngineRuntime` | Actor owning the transitional model-load/prewarm + conditioning bridge. |
| `VocelloQwen3Engine` | Shipping Custom/Design/Clone generation mutation authority; owns the classified session and operation lease. |
| `GenerationOutputAdapter` | QwenVoiceCore product output/finalization authority (`GenerationOutputAdapter.swift`). |
| `NativeMemoryPolicyResolver` | Per-device-tier MLX cache/clone/idle/cadence policy. |
| `ActiveGenerationCoordinator` | Owns one in-process generation and waits for a typed cancellation terminal barrier before releasing it. |
| `GenerationEventDeliveryProbe` | Owns the bounded suspending frontend-event router and measures accepted, terminated, or unobserved sends. |
| `RuntimeDebugGate` | Makes registered production-affecting environment overrides inert unless `QWENVOICE_DEBUG` is enabled. |
| `EngineServiceHost` | `@MainActor` XPC service host (`QwenVoiceEngineService`) running the engine out-of-process. |
| `XPCNativeEngineClient` | macOS XPC client conforming to `MacTTSEngine`; `XPCNativeEngineCoordinator` manages the connection. |
| `EngineCommand` | The XPC command enum carried inside the single `perform(_:withReply:)` envelope. |
| `GenerationChunkBroker` | Combine bridge delivering streaming events to SwiftUI (macOS). |
| `EngineServiceTransportAccumulator` | Pure bounded XPC probe state: accepted chunks, gaps/duplicates/reordering, cancellation, and single terminal record. |
| `ContractBackedModelRegistry` | Loads `qwenvoice_contract.json` and expands it per platform. |
| `GenerationRequest` / `Payload` | The generation ask + its mode-specific payload (custom/design/clone). |
| `CloneReference` | Reference audio + typed conditioning mode (`transcriptBacked` or genuine audio-only `xVectorOnly`) + optional prepared voice identity. |
| `UnsafeSpeechGenerationModel` | `Sendable` pairing of the runtime actor with immutable post-load facts; no model handle, no SPI. |

---

## 17. Related documents

- [`development-progress.md`](development-progress.md) — active checkpoint: deterministic development status, the completed XCUITest stack, and the agent resume route.
- [`project-map.html`](project-map.html) — canonical interactive project map: product features, build graph, runtime flows, source ownership, dependencies, contracts, and Codex routes.
- [`CLAUDE.md`](../CLAUDE.md) — repo operating manual: build, conventions, engine invariants, dependency pinning, release/QA.
- [`README.md`](../README.md) — product overview + install.
- [`PRODUCT.md`](../PRODUCT.md) — product/brand guidance.
- Per-subsystem deep-dives in `docs/reference/`:
  [`mlx-guide.md`](reference/mlx-guide.md),
  [`qwen3-tts-guide.md`](reference/qwen3-tts-guide.md),
  [`mimi-codec-guide.md`](reference/mimi-codec-guide.md),
  [`metal-guide.md`](reference/metal-guide.md),
  [`swift-performance-guide.md`](reference/swift-performance-guide.md),
  [`ios-engine-optimization.md`](reference/ios-engine-optimization.md),
  [`telemetry-and-benchmarking.md`](reference/telemetry-and-benchmarking.md),
  [`cli.md`](reference/cli.md),
  [`macos-release-qa.md`](reference/macos-release-qa.md),
  [`ios-device-testing.md`](reference/ios-device-testing.md),
  [`testing-runbook.md`](reference/testing-runbook.md),
  [`ios-app-guide.md`](reference/ios-app-guide.md),
  [`privacy-storage.md`](reference/privacy-storage.md),
  [`macos-permissions.md`](reference/macos-permissions.md),
  [`mlx-audio-swift-patching.md`](reference/mlx-audio-swift-patching.md).
