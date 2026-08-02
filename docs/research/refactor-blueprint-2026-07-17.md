---
status: historical
owner: backend-mlx
summary: Vocello Runtime Convergence Refactor Blueprint. Imported point-in-time research snapshot. Pinned: superseded figures carry inline editor's notes; contract JSON remains status authority.
contentDigest: sha256:36ae6415323824d6b601841dc4121183a2faae7045b3dc71fc225bdd1364e443
---
# Vocello Runtime Convergence Refactor Blueprint

> **Imported research snapshot (2026-07-17).** Converted 2026-07-22 from the external HTML
> report bundle into the repository so corrections and review history stay tracked. Every
> measured figure below is a point-in-time capture from on or before 2026-07-17; the
> 2026-07-22 backend refactor review counter-verified this corpus and found its measured
> claims correct at capture with several since superseded. Superseded figures carry inline
> **Editor's note** blocks; see [`docs/research/README.md`](README.md) for the verification
> summary and [`config/runtime-refactor-contract.json`](../../config/runtime-refactor-contract.json)
> for current phase status.


## Contract-First Major Refactor for Qwen3-TTS Performance, Streaming, Memory, Quality and Long-Form

**Repository:** `PowerBeef/Vocello`
 **Branch:** `main`
 **Exact source reviewed:** [`079757abc3524ad5c0308bb1d914a9ff151c0de6`](https://github.com/PowerBeef/Vocello/commit/079757abc3524ad5c0308bb1d914a9ff151c0de6)
 **Report date:** July 17, 2026
 **Primary floor hardware:** Mac mini M2 with 8 GB unified memory
 **Mobile acceptance:** physical iPhone, in-process MLX runtime
 **Input:** four prior Vocello research, quality, performance and project-review documents plus current source inspection   YES major refactor justified — ground-up rewrite rejected   **Executive decision.** The accumulated work has crossed the boundary from a collection of optimizations into a major architectural convergence program. The reason is not that Vocello's top-level architecture is wrong. It is the opposite: macOS XPC isolation, iPhone in-process execution, streaming-first causal decode, incremental WAV output, aggressive memory discipline and exact evidence are the correct foundations. The refactor is required because the next performance, quality and long-form improvements all need the same missing authority: one actor-owned Qwen3 engine, one end-to-end generation operation, immutable request policies, classified event channels and one product session that remains responsible through final output publication. The recommended approach is a phased strangler/convergence refactor with mode-by-mode parity gates—not a new backend written beside the existing one.    4joined reports reviewed 30.2kcombined report words 61%RAM reduction to preserve 0acceptable preview audio drops 1target MLX operation owner 12–18recommended reviewable PRs

>

**Core recommendation:** preserve the current host topology and streaming output path, but converge model lifecycle, generation admission, cancellation, memory relief, sampling, chunk policy and terminal delivery around a single runtime operation lease. Performance and quality features should be built on that converged foundation, not layered onto both the facade session and the product session.

## 1. Scope and input provenance

The four joined reports contain 30,233 words and 411 top-level/subsection headings. They were re-read as one architectural record rather than four independent feature lists.

| Input document | Words | Headings | SHA-256 prefix |
| --- | --- | --- | --- |
| `Vocello_Qwen3TTS_1_7B_4bit_Research_Leverage_Assessment_2026-07-16(1).html` | 5,466 | 70 | `7faee3b6cb906f93…` |
| `Vocello_Audio_Quality_Review_System_Reference_2026-07-16(1).html` | 5,218 | 106 | `95f26d042eb839f2…` |
| `QwenVoice_Performance_Optimization_Deep_Dive_and_Roadmap_2026-07-17(1).html` | 8,447 | 127 | `85a3c8927ed0cfe3…` |
| `QwenVoice_Updated_Exhaustive_Project_Review_2026-07-16(1).html` | 11,102 | 108 | `47a3e4787e1c3488…` |

### 1.1 What each document contributes

**The Qwen3-TTS 1.7B 4-bit leverage assessment** identifies the highest-value unfilled quality layers: deterministic spoken text, duration/token-aware segmentation, request-owned main/residual sampling, VoiceDesign-to-Clone identity locking, selective candidate retry and a custom INT4 program only after non-weight causes are controlled.

**The Audio Quality Review reference** defines the evidence system required to change the backend safely: terminal integrity, codec diagnostics, persisted-WAV signal checks, lexical/language accuracy, prosody, delivery, speaker identity, streaming continuity, long-form consistency and resource behavior. It also establishes the critical 8 GB rule: one MLX model at a time, no parallel candidate generation and no heavyweight reviewer in the first-audio path.

**The performance deep dive** explains why the existing architecture works: streaming changed the physical-memory curve from roughly 7.6 GB to roughly 3.0 GB and made it approximately length-flat; fused Code Predictor work produced substantial RTF gains; live preview already removes seconds of perceived latency; and the remaining high-value opportunities include adaptive preview admission, first/later chunk policy, shared immutable model components, dynamic retention and carefully isolated runtime research.

> **Editor's note (2026-07-22).** The streaming-vs-non-streaming conclusion (≈2.5× smaller, approximately length-flat) stands. The exact ~3.0 GB figure is from the 2026-06-01 experiment; current canonical peaks are 2.56–3.52 GB (iOS) and 2.75–3.90 GB (macOS UI). Do not generalize the older number (see `docs/reference/ios-engine-optimization.md` §3).


**The updated project review** exposes the structural reason the work has become a refactor: the repository has a new stable facade session, but the shipping engine still uses its own generation session; the facade and product have incompatible event-overflow policies; loaded-model mutation is safe only through external serialization; request policy still uses process-global state; and two confirmed source defects remain in XPC admission and memory-pressure observation.

### 1.2 The reports converge on one conclusion

The documents do not describe four separate projects. They describe one missing architecture:

```
immutable generation plan
        │
        ▼
one actor-owned MLX/model operation
        │
        ▼
one low-level model session
        │
        ▼
one mandatory product output adapter
        │
        ├─ final WAV + QC + telemetry
        ├─ lossless preview audio
        ├─ coalesced progress
        └─ exactly one public terminal

```

Spoken-text normalization, dual-stage sampling, chunk policy, adaptive preview, shared components, long-form identity and automated quality review all need that plan and session identity.

### 1.3 Apparent contradictions and their resolution

| Apparent contradiction | Resolution |
| --- | --- |
| “Major refactor” versus “do not undertake another rewrite” | Perform a **convergence refactor**. Preserve topology and proven algorithms; replace duplicated authority incrementally. |
| Core session fails on event overflow, while product stream drops older events | Split event delivery by semantic class. Audio is lossless; progress is coalesced; terminal is independent. |
| Quality review proposes more analysis, while performance requires low RAM | Keep only severe signal/terminal safeguards in the generation path. Run ASR/speaker/long-form review sequentially after TTS unload. |
| Smaller chunks improve feedback, while larger chunks improve throughput | Make first and later chunk sizes independent and separate them from playback admission. |
| Shared decoder reuse improves switching, while aggressive unload protects memory | Reuse only one immutable shared decoder under headroom policy; clear it on pressure/retirement. |
| Long-form quality needs more work, while streaming is a memory pillar | Generate segments sequentially **with streaming enabled internally**, even when audible preview is suppressed. |
| Custom quantization may improve quality, while current 4-bit performance is strong | Defer new weights until frontend, sampler, segmentation and identity variables are controlled. |

## 2. Current source state

### 2.1 Current architecture is fundamentally correct

At `079757abc3524ad5c0308bb1d914a9ff151c0de6`, all hosts share `QwenVoiceCore/MLXTTSEngine`:

```
macOS app
  SwiftUI → QwenVoiceNative/XPC client
          → QwenVoiceEngineService
          → MLXTTSEngine
          → VocelloQwen3Core

iPhone app
  SwiftUI → in-process MLXTTSEngine
          → VocelloQwen3Core

CLI
  vocello → in-process MLXTTSEngine
          → VocelloQwen3Core

```

Keep this split:

- macOS XPC provides crash isolation and process retirement to zero RSS;
- iPhone keeps MLX inside the entitlement-bearing app process;
- CLI remains headless;
- one product engine and one owned Qwen implementation serve every host.

### 2.2 Current evidence is unusually strong

The tracked project-health snapshot records:

- 232 Swift tests in 39 files;
- 524 Python tests in 40 files;
- all 55 required workflow steps covered by forced-failure fixtures;
- all 50 unsafe/unchecked concurrency annotations registered;
- fresh canonical Mac and iPhone evidence for generation terminal, clone conditioning, event delivery, memory policy, model delivery, XPC transport and benchmark validation.

The canonical Mac and iPhone records each execute the exact 29-take matrix with telemetry schema v8, complete correlation, memory qualification and clean crash deltas. That evidence must become the refactor control, not be discarded.

### 2.3 Current performance pillars

The present system already implements the hard parts:

- bounded streaming codec state;
- causal Mimi decoder state;
- asynchronous non-final audio materialization;
- incremental final WAV output;
- reusable PCM conversion buffers;
- per-tier cache limits and clear cadence;
- post-generation trim;
- clone-cache limits;
- proactive-warm admission;
- idle unload;
- macOS process retirement;
- fused Code Predictor RoPE;
- fused attention;
- sampler scratch and cached step constants;
- exact preview sequence/frame metadata;
- seamless preview-to-final-file handoff.

The refactor must preserve these behaviors before adding new ones.

### 2.4 Current generation path

```
GenerationRequest
  → MLXTTSEngine generation/task/model-operation gates
  → NativeEngineRuntime prepares model and conditioning
  → UnsafeSpeechGenerationModel calls mode-specific facade stream
  → Qwen hot loop generates semantic + 15 residual codebooks
  → NativeStreamingSynthesisSession consumes Float chunks
  → limiter + Int16 conversion + incremental WAV + preview event
  → GenerationScopedEventRouter
  → iPhone direct consumer or macOS XPC forwarder
  → AudioPlayerViewModel buffer admission and AVAudioEngine

```

A parallel path also exists:

```
VocelloQwen3LoadedModel.startGenerationSession(...)
  → VocelloQwen3ModelGenerationSession
  → one bounded combined event channel

```

The shipping path does not use that session.

## 3. Why this is now a major refactor

### 3.1 The next improvements are cross-cutting

A simple optimization changes one stage. The proposed work changes contracts that cross:

```
UI / CLI
→ GenerationRequest
→ XPC codec
→ product engine
→ model facade
→ Qwen hot loop
→ streaming output
→ preview playback
→ telemetry/evidence
→ history/long-form manifest

```

Examples:

- request-local dual-stage sampling must cross every layer to the 15-pass predictor;
- adaptive preview depends on chunk policy, exact timing and lossless transport;
- spoken text must change the text given to the model while preserving original history;
- long-form planning must control segmentation, identity, streaming, assembly and review;
- shared components change the catalog, installer, prepared model bundle and loader cache identity;
- one quality report must join evidence now spread across Swift, Python and benchmark records.

### 3.2 Authority is duplicated

| Concern | Current authorities | Result |
| --- | --- | --- |
| Generation admission | `ActiveGenerationCoordinator`, `ServiceActiveGenerationCoordinator`, facade session | XPC can create side effects before service admission. |
| Model operations | `MLXTTSEngine.activeModelOperation`, `NativeEngineRuntime` gates, externally serialized loaded model | Safety depends on multiple adjacent contracts. |
| Session terminal | facade terminal state, product streaming session, product event router, XPC host | More than one layer interprets completion/cancellation. |
| Event buffering | facade non-suspending queue, product `bufferingNewest`, XPC one-way publish | Slow consumers either fail synthesis or lose older audio. |
| Sampling | product static variation lock, implementation static environment overrides, facade request fields | Policy is not one immutable request value. |
| Memory | product policy resolver, facade process-global apply, implementation static tuning | Session isolation is implicit. |
| Clone identity | strong product prompt identity, facade `referenceID` plus separate prompt | Public contract can pair the wrong request identity and prompt. |
| Quality | signal QC, ASR, prosody, delivery and benchmark schemas | Strong components do not yet form one report or scheduler. |

### 3.3 A ground-up rewrite would be the wrong response

A rewrite would put the best current properties at risk:

- length-flat memory;
- exact clone artifacts;
- cancellation and terminal barriers;
- atomic output;
- XPC retirement;
- current model delivery;
- benchmark continuity;
- device evidence.

The proper method is a **strangler migration**: create the target contracts beside the current path, prove parity, cut over one mode at a time and delete old authority as soon as its replacement is accepted.

## 4. Non-negotiable refactor invariants

1. **One MLX mutator.** Exactly one actor owns model load, prewarm, prompt construction, generation, trim and unload.
2. **One active generation.** It has one immutable ID and one first cancellation reason.
3. **One operation lease.** Ownership lasts through model terminal, final WAV publication or cleanup, telemetry terminal and public terminal.
4. **No side effects before admission.** A rejected request creates no task, stream, timing entry, prompt mutation or event forwarder.
5. **Streaming remains production.** Non-streaming is a diagnostic control only.
6. **Memory remains bounded with length.** No full generated-code or full decoded-audio accumulation on the product path.
7. **Audio is lossless.** Progress may be coalesced; preview PCM may not be evicted.
8. **Terminal is independent.** A slow or absent progress subscriber cannot prevent terminal completion.
9. **Final WAV is authoritative.** It is atomically published only after readable finalization.
10. **Request policy is immutable.** Sampling, seed, chunking and memory behavior are captured once.
11. **macOS keeps XPC.** Process isolation and retirement are product features.
12. **iPhone stays in-process.** Do not reintroduce an independently Jetsam-capped extension.
13. **No concurrent large evaluators.** TTS, ASR and speaker analysis execute sequentially on the 8 GB floor.
14. **No parallel candidates.** Candidate two is failure-triggered and sequential.
15. **Original text is preserved.** Spoken normalization is versioned and inspectable.
16. **Quality cannot hide correctness.** Aesthetic metrics never cancel terminal, lexical, language or identity failures.
17. **Every phase has a control.** Structural work must be output-neutral; optimization work must declare a measurable target.
18. **Negative results remain first-class.** Rejected experiments stay documented.
19. **Main remains releasable.** No months-long branch is allowed to become the only source of truth.
20. **Old authority is deleted after cutover.** Feature flags are migration tools, not permanent duplicate architectures.

## 5. Confirmed current-source findings

### 5.1 P0 — XPC request admission occurs after side effects

`EngineServiceHost.perform(.generate)` currently:

1. records request acceptance timing;
2. cancels the current event forwarder;
3. starts a new event forwarder;
4. creates the generation task;
5. only then calls `ServiceActiveGenerationCoordinator.register`.

A second request can be rejected after it has already canceled the accepted request's forwarder. This must be fixed before the session refactor because an aggressive preview policy increases reliance on complete event delivery.

**Target:** `reserve → bind task/forwarder → open start gate`. Rejection must be side-effect-free.

### 5.2 P0 — Memory-pressure state is unsynchronized

`NativeMemoryPressureMonitor.currentLevel` is a plain mutable property written on a dispatch queue and read from the engine's actor/main-actor context. `@unchecked Sendable` does not synchronize the value.

**Target:** a lock/atomic/actor-backed snapshot. Preserve the `DispatchSource` queue but never expose queue-owned mutable state unsafely.

### 5.3 P0/P1 — Pressure cancellation and trim do not visibly share the product operation lease

The pressure executor correctly waits for generation terminal before trim. The engine's model-operation gate is separate, so the source does not make it obvious that a new load/prewarm/generation cannot enter between cancellation completion and trim/unload completion.

**Target:** memory relief is an exclusive operation state held from pressure observation through cancel, terminal, trim/unload and final state publication.

### 5.4 P1 — Two generation sessions exist

The facade declares `VocelloQwen3GenerationSession`, but product generation still uses `NativeStreamingSynthesisSession` over direct mode streams.

Consequences:

- facade tests do not directly prove the shipping lifecycle;
- cancellation and overflow semantics can diverge;
- request policy and diagnostics take different paths;
- future improvements must be implemented twice or remain outside the facade.

**Target:** the product session becomes a thin output/finalization adapter over the core session. It must not own a second model terminal.

### 5.5 P1 — Event delivery applies one policy to incompatible event classes

The facade's one queue fails the session if any nonterminal event overflows. It emits progress after every signal, making observer speed part of synthesis correctness.

The product router uses `bufferingNewest`, which accepts new events by evicting old ones. It measures dropped chunks, but valid preview audio can be lost.

**Target classes:**

```
audio       lossless, ordered, bounded, suspending
progress    latest/coalesced, drop-safe
prepared    replayable latest state
terminal    guaranteed independent promise
diagnostic  bounded, explicitly loss-tolerant

```

### 5.6 P1 — Loaded-model safety is external

`VocelloQwen3LoadedModel` is an `@unchecked Sendable` class exposing direct prewarm, prompt, stream and full-generate operations. Current product discipline prevents overlap, but the stable facade does not make illegal use impossible.

**Target:** `VocelloQwen3Engine` actor is the only public model-mutating API. Loaded-model implementation methods become internal/SPI.

### 5.7 P1 — Sampling policy is process-global and incomplete

The product uses a static lock to install the current variation. The implementation uses `Qwen3SamplingOverrides.shared`, resolved from environment once, for main top-K/min-P and residual temperature/top-K/top-P. The facade request exposes seed and arbitrary top-K but rejects them in the compatibility adapter.

**Target:** one request-owned `Qwen3SamplingPolicy` with fully supported main and residual stages, repetition penalty, max tokens and seed. Debug overrides resolve into the plan and are stamped; they do not remain hidden global mutation.

### 5.8 P1 — Clone identity is stronger inside the product than at the facade

Product clone artifacts bind the normalized reference, conditioning mode, model revision/artifact digest, runtime profile and speaker-feature version. The facade request carries a string `referenceID` while the prompt is passed separately and only prompt presence is validated.

**Target:** an opaque `CloneConditioningHandle` created by the engine. The synthesis request carries that handle; it cannot be paired with another prompt.

### 5.9 P1 — Long-form batch contradicts the streaming memory pillar

`LongFormBatchSegmenter` uses a 900-character ceiling, ASCII `. ! ?` boundaries and word fallback. `BatchGenerationRequest.makeGenerationRequest` sets `shouldStream: false` for Custom, Design and Clone.

This creates two problems:

- segmentation is not language-, duration- or token-aware;
- long-form uses the memory-heavier full-result path even though streaming is the project's primary RAM architecture.

**Target:** versioned `SegmentPlan` plus sequential streaming generation. Audible live preview may be suppressed, but incremental decode/output must remain active.

### 5.10 P1 — Identical model components are stored and cached by model directory

All six model artifacts include the same 682,293,092-byte speech-tokenizer model digest. The prepared component cache is keyed by `preparedKey` and can retain three separate speech-tokenizer objects on macOS.

**Target:** first deduplicate immutable files on disk; then key caches by component digest and qualify one decoder instance across family switches.

### 5.11 P1/P2 — Preview admission is static despite improved generation speed

The frontend already tracks exact queued audio, continuity and underruns. Its smooth-first policy still uses a minimum 3.25 seconds and 35% of estimated duration.

**Target:** after audio transport is lossless, use a conservative lower-bound RTF and observed jitter to calculate safe buffer. Keep current policy as fallback for Clone/unknown cells.

### 5.12 P2 — Quality components are strong but fragmented

Current source already has:

- canonical persisted-WAV QC;
- three-pass on-device Speech consensus;
- WER/CER and language checks;
- low-memory prosody analysis;
- paired same-seed delivery evidence;
- telemetry and benchmark identity.

Missing is one versioned report, gate registry, resource scheduler, codec summary, critical-token alignment, speaker/onset evidence, streaming boundary report and long-form continuity report.

### 5.13 P2 — Large files reflect unresolved ownership

`Qwen3TTS.swift`, `MLXTTSEngine.swift`, `NativeEngineRuntime.swift`, download coordinators and batch orchestration have grown because policy, lifecycle, telemetry and implementation remain adjacent.

**Target:** split only after the new contracts exist. Mechanical moves and behavior changes must be separate commits.

## 6. Target architecture

```
Platform UI / CLI
        │
        ▼
QwenVoiceCore ProductGenerationPlanner
  ├─ SpokenTextPlan
  ├─ LanguagePlan
  ├─ Input / CloneConditioning identity
  ├─ SamplingPolicy
  ├─ StreamChunkPolicy
  ├─ MemoryPolicySnapshot
  ├─ PreviewAdmissionPolicy
  ├─ QualityReviewPlan
  └─ EvidenceIdentity
        │
        ▼
QwenVoiceCore ProductEngineCoordinator
        │  resolves prepared bundle + paths
        ▼
VocelloQwen3Engine actor
  ├─ loaded model
  ├─ RuntimeOperationLease
  ├─ prewarm / clone handle
  ├─ low-level GenerationSession
  ├─ typed model diagnostics
  └─ pressure relief / unload
        │
        ▼
QwenVoiceCore GenerationOutputAdapter
  ├─ mandatory lossless audio drain
  ├─ PCM limiter + reusable scratch
  ├─ incremental final WAV
  ├─ final persisted-WAV QC
  ├─ preview spool/event publication
  └─ public product terminal
        │
        ├─ macOS XPC transport → AudioPlayerViewModel
        ├─ iPhone direct transport → AudioPlayerViewModel
        └─ CLI machine-readable progress/result

```

### 6.1 Ownership boundary

| Layer | Owns | Does not own |
| --- | --- | --- |
| `VocelloQwen3Core` | Qwen/Mimi model, component loading, one MLX operation lease, request-local model policy, clone handle, model audio chunks, model terminal | History, UI, output paths, AVAudioEngine, product QC policy |
| `QwenVoiceCore` | model selection, text/language planning, output files, limiter, incremental WAV, preview publication, product telemetry, public terminal, quality scheduling | SwiftUI presentation, XPC implementation details |
| macOS platform | XPC connection/session, service retirement, app playback | Qwen model semantics |
| iPhone platform | app lifecycle, audio session, playback, memory warning ingress | separate engine implementation |
| CLI | argument/JSON interface, explicit evidence workflows | alternate model path |
| development tooling | ASR/prosody/speaker/canonical review | shipping Python runtime |

### 6.2 One public terminal, two internal barriers

The model naturally reaches EOS before the product has repaired the WAV header, reopened the file, performed mandatory QC and published output. Do not pretend these are the same moment.

Use:

```
internal model terminal
  → output drain complete
  → WAV finalize + readability
  → mandatory QC
  → atomic publication
  → public product terminal
  → release runtime operation lease

```

Cancellation follows:

```
cancel request
  → model terminal cancelled
  → discard partial output/session
  → close preview
  → publish one cancelled product terminal
  → release lease

```

The public API exposes one product terminal. The model terminal is internal telemetry and synchronization.

## 7. Proposed core engine contract

```
public actor VocelloQwen3Engine {
    public enum State: Sendable {
        case idle
        case loading(OperationID)
        case ready(VocelloQwen3ModelIdentity)
        case prewarming(OperationID)
        case generating(GenerationID)
        case relievingMemory(OperationID, MemoryReliefLevel)
        case unloading(OperationID)
        case failed(VocelloQwen3FailureCode)
    }

    public func load(
        _ bundle: VocelloQwen3PreparedModelBundle,
        policy: VocelloQwen3LoadPolicy
    ) async throws

    public func makeCloneConditioning(
        _ input: VocelloQwen3CloneInput
    ) async throws -> CloneConditioningHandle

    public func start(
        _ plan: VocelloQwen3SynthesisPlan
    ) async throws -> VocelloQwen3GenerationSession

    public func prewarm(
        _ plan: VocelloQwen3PrewarmPlan
    ) async throws

    public func relieveMemory(
        _ level: VocelloQwen3MemoryReliefLevel,
        reason: String
    ) async

    public func unload() async
}

```

### 7.1 RuntimeOperationLease

The actor maintains one operation record:

```
struct RuntimeOperationLease: Sendable {
    let id: UUID
    let kind: RuntimeOperationKind
    let generationID: UUID?
    let startedAt: ContinuousClock.Instant
}

```

Rules:

- user generation rejects another generation;
- user load/unload waits for safe non-generation operations;
- proactive warm skips if busy;
- pressure relief may cancel generation, awaits internal terminal, then retains exclusive ownership through trim/unload;
- product finalization acknowledgment is required before the generation lease is released;
- no platform host creates a second independent model-operation gate.

### 7.2 XPC admission becomes a consequence of the engine API

The macOS host should call an atomic start API before creating side effects:

```
let session = try await engine.start(plan)   // admission already reserved
let forwarder = startForwarding(session)
let result = try await session.waitForProductTermination()

```

If `start` throws busy:

- no event stream exists;
- no timing entry exists;
- no task exists;
- the current forwarder remains untouched.

### 7.3 Request-local policy

```
public struct Qwen3SamplerStagePolicy: Codable, Hashable, Sendable {
    public let temperature: Float
    public let topK: Int
    public let topP: Float
    public let minP: Float
}

public struct Qwen3SamplingPolicy: Codable, Hashable, Sendable {
    public let id: String
    public let main: Qwen3SamplerStagePolicy
    public let residual: Qwen3SamplerStagePolicy
    public let repetitionPenalty: Float
    public let maxNewTokens: Int
    public let seed: UInt64?
}

public struct Qwen3StreamChunkPolicy: Codable, Hashable, Sendable {
    public let firstCodecFrames: Int
    public let laterCodecFrames: Int
}

public struct Qwen3SessionMemoryPolicy: Codable, Hashable, Sendable {
    public let cacheLimitBytes: Int
    public let clearCacheOnChunk: Bool
    public let tokenClearCadence: Int
    public let clearCacheAfterGeneration: Bool
}

```

The hot loop receives these values as arguments. Remove:

- `Qwen3TalkerSamplingOverride.requestVariation`;
- `Qwen3SamplingOverrides.shared` as production authority;
- chunk multiplier hidden inside generation-speed profiles;
- session behavior inferred from process-global environment.

Environment knobs may remain registered diagnostic overlays. They must resolve into the immutable plan and be recorded.

### 7.4 CloneConditioningHandle

```
public struct CloneConditioningHandle: Hashable, Codable, Sendable {
    public let id: UUID
    public let identityDigest: String
    public let mode: CloneConditioningMode
    public let modelIdentity: VocelloQwen3ModelIdentity
    public let runtimeProfileSignature: String
    public let speakerFeatureVersion: String
}

```

The actor retains the opaque prompt behind the handle. A request cannot supply a string ID and unrelated prompt.

Persisted schema-3 artifacts remain valuable. The handle resolver validates them and creates an in-memory handle; the artifact format does not need to be discarded.

## 8. One generation session with classified delivery

### 8.1 Proposed session API

```
public protocol VocelloQwen3GenerationSession: Sendable {
    var id: UUID { get }
    var audio: AsyncThrowingStream<VocelloQwen3AudioChunk, Error> { get }
    var progress: AsyncStream<VocelloQwen3ProgressSnapshot> { get }
    var diagnostics: AsyncStream<VocelloQwen3DiagnosticEvent> { get }

    func preparedState() async -> VocelloQwen3PreparedState?
    func cancel(reason: VocelloQwen3CancellationReason) async
    func waitForModelTermination() async -> VocelloQwen3ModelTerminal
}

```

The product wrapper adds:

```
public protocol QwenVoiceGenerationSession: Sendable {
    var events: AsyncStream<GenerationEvent> { get }
    func cancel(reason: GenerationCancellationReason) async
    func waitForResult() async throws -> GenerationResult
}

```

`QwenVoiceGenerationSession` must not invent a second model terminal. It consumes the core model terminal and resolves the public result only after output finalization.

### 8.2 Audio channel

Use a custom bounded async channel:

- producer `send` suspends when capacity is full;
- one mandatory output adapter drains immediately;
- capacity is measured in audio seconds/frames, not arbitrary event count;
- cancellation wakes producer and consumer;
- terminal has a separate promise;
- no progress event shares this capacity.

Backpressure may slightly slow generation if the mandatory output writer cannot keep up. That is preferable to silently deleting preview audio or failing valid synthesis. The adapter should be fast enough that normal runs never hit the bound; telemetry proves it.

### 8.3 Progress

Progress is a snapshot:

```
generated semantic frames
emitted audio frames
elapsed time
current stage
estimated fraction if available

```

Keep only the newest value. A missing observer has no effect on generation.

### 8.4 Diagnostics

Diagnostics are explicitly best-effort and bounded. They may coalesce or count drops. They can never:

- fail generation;
- block first audio;
- hold raw PCM;
- contain prompt/reference content.

### 8.5 Platform transport

First remove audio from `GenerationScopedEventRouter.bufferingNewest`.

For macOS:

1. service drains the product session in order;
2. one serial XPC audio forwarder sends sequence/frame metadata;
3. stress the existing one-way XPC route;
4. add an acknowledgment window or temporary chunk spool only if the transport itself proves capable of unbounded backlog.

Do not introduce disk I/O or XPC round trips speculatively when the current PCM payload is small and measured preview cost is negligible.

For iPhone:

- direct bounded audio channel;
- no extra XPC abstraction.

For CLI:

- drain audio to the output adapter;
- progress JSON may be coalesced;
- no playback consumer.

## 9. ProductGenerationPlan

The product planner should create one immutable value before model mutation.

```
public struct ProductGenerationPlan: Codable, Hashable, Sendable {
    public let generationID: UUID
    public let model: ModelRuntimeIdentity
    public let originalTextDigest: String
    public let spokenText: SpokenTextPlan
    public let language: LanguagePlan
    public let input: GenerationInputPlan
    public let sampling: Qwen3SamplingPolicy
    public let chunks: Qwen3StreamChunkPolicy
    public let memory: NativeMemoryPolicySnapshot
    public let preview: PreviewAdmissionPolicy
    public let quality: QualityReviewPlan
    public let output: GenerationOutputPlan
    public let evidence: GenerationEvidenceIdentity
}

```

### 9.1 Why the plan matters

It becomes the single cache/evidence identity for:

- prewarm;
- prefix cache;
- clone prompt;
- generation;
- long-form segments;
- benchmark cells;
- candidate comparison;
- preview policy;
- quality report.

A policy change cannot silently reuse a cache built under different sampling, text or component identity.

### 9.2 Product versus core subset

The planner maps to a smaller core plan:

```
ProductGenerationPlan
  └─ VocelloQwen3SynthesisPlan
       model identity
       spoken text
       resolved language
       custom/design/clone handle
       sampling
       chunk policy
       memory policy

```

The core does not receive history paths, preview UI state or ASR policy.

## 10. Performance and streaming subsystem

### 10.1 Protect the measured RAM architecture

The structural cutover must preserve:

```
pending codec frames bounded by chunk policy
+ causal decoder state
+ one materialized audio chunk
+ reusable Int16 scratch
+ incremental final WAV
+ bounded preview transport

```

Any refactor that temporarily reconstructs a full utterance or retains all audio chunks is rejected.

### 10.2 Decouple first and later chunk sizes

Current floor policy derives both from `streamingInterval`, with Design/Clone using a 2× later multiplier and Custom baseline staying at 1×.

Move to explicit policy:

| First frames | Approx. audio | Later frames | Approx. audio |
| --- | --- | --- | --- |
| 4 | 0.32 s | 10 | 0.80 s |
| 5 | 0.40 s | 10 | 0.80 s |
| 6 | 0.48 s | 14 | 1.12 s |
| 7 control | 0.56 s | 7/14 control | 0.56/1.12 s |

Structural session cutover keeps the current values. The matrix runs only after parity.

### 10.3 Exact first-render instrumentation

Measure:

```
submit
engine accepted
model ready
first semantic token
first codec chunk ready
first chunk materialized
product adapter received
frontend received
buffer admission passed
AVAudioEngine start begin/end
player-node play call
first render host time/estimate
final completion

```

Use one monotonic clock or validated cross-process correlation. “First chunk” is not “first audible.”

### 10.4 Adaptive preview admission

After the audio path is lossless:

```
Bsafe = jitterMargin + max(0, estimatedAudioDuration × (1 − conservativeRate))

```

Where `conservativeRate` is the lower bound from:

- mode/variant/device/cold-warm canonical history;
- observed first/second chunk production;
- current thermal/pressure state;
- p95 inter-arrival jitter.

Initial policy:

- faster-than-realtime Custom/Design: 2 continuity-valid chunks and roughly 0.8–1.2 s;
- uncertain/near-realtime: formula;
- Clone/unknown: current smooth-first fallback;
- any underrun: increase margin for the session.

Promotion requires zero canonical underruns and audio drops.

### 10.5 AVAudioEngine preparation

The graph is already configured before chunks arrive. Add an isolated experiment for:

```
engine.prepare()
playerNode.prepare(withFrameCount: expectedFirstBufferFrames)

```

Measure first-render improvement and route/interruption behavior. Do not start the audio session early enough to create unnecessary idle power or route changes without evidence.

### 10.6 Dynamic retention

Keep the existing device tiers as safe defaults. Add headroom-aware adjustments later:

- normal + likely reuse: retain cache/shared decoder longer;
- normal + low reuse: shorter retirement;
- warning: stop proactive warm and reduce retention;
- critical: exclusive cancellation/trim/unload;
- background: platform-specific retirement.

Do not optimize for the smallest cache. Optimize the Pareto frontier of TTFC, RTF, pressure, compression and energy.

## 11. Shared component store

### 11.1 Separate disk deduplication from runtime reuse

**Stage A — storage-only**

- catalog declares content-addressed shared files;
- installer stores one verified speech tokenizer and text tokenizer;
- family models reference exact component digests;
- existing installations migrate atomically;
- loader still creates its current object per model if necessary.

This yields the certain storage/network benefit with low runtime risk.

**Stage B — object reuse**

- prepared component cache key becomes component digest, not prepared directory;
- retain one shared speech decoder where architecture and memory evidence permit;
- reset streaming state at session boundaries;
- Base clone can additionally request encoder capability;
- pressure/full unload/retirement clears the pool.

### 11.2 Proposed catalog shape

```
{
  "sharedComponents": [{
    "id": "qwen3-speech-tokenizer-12hz-v1",
    "digest": "836b7b35...",
    "files": ["speech_tokenizer/..."]
  }],
  "models": [{
    "modelID": "pro_custom",
    "variantID": "speed",
    "components": ["qwen3-speech-tokenizer-12hz-v1"],
    "familyFiles": ["model.safetensors", "..."]
  }]
}

```

### 11.3 Migration rules

1. Verify an existing installed copy.
2. Publish it into the shared store atomically.
3. Write the component manifest.
4. Update the installed model receipt.
5. Prove a full model load.
6. Only then remove duplicates.
7. On failure, retain the old model directory unchanged.

No user model redownload is required when valid bytes exist.

## 12. Spoken text and long-form

### 12.1 SpokenTextPlan

```
public struct SpokenTextPlan: Codable, Hashable, Sendable {
    public let originalText: String
    public let spokenText: String
    public let language: Qwen3SupportedLanguage
    public let transformations: [SpokenTextTransformation]
    public let unresolvedRisks: [SpokenTextRisk]
    public let normalizerVersion: String
}

```

The app displays original text and can show a spoken-form review. Generation uses `spokenText`.

First categories:

- Unicode/punctuation/whitespace;
- numbers and decimals;
- dates and times;
- percentages, currency and units;
- acronyms/initialisms;
- URLs/email/version strings;
- custom pronunciation lexicon;
- mixed-script/code-switch risks.

Do not silently resolve true ambiguity in canonical/batch workflows.

### 12.2 LanguagePlan

Replace a single resolved string with:

```
struct LanguagePlan {
    let requested: Qwen3SupportedLanguage
    let resolved: Qwen3SupportedLanguage
    let confidence: Double?
    let source: explicit | script | recognizer | fallback
    let codeSwitchSegments: [...]
}

```

Auto remains a UI choice; the plan records the explicit Qwen token or uncertainty.

### 12.3 SegmentPlan

```
public struct LongFormSegmentPlan: Codable, Hashable, Sendable {
    public let index: Int
    public let sourceRange: Range<Int>
    public let spokenText: String
    public let language: Qwen3SupportedLanguage
    public let boundary: BoundaryKind
    public let estimatedTextTokens: Int
    public let estimatedAudioSeconds: Double
    public let maximumCodecTokens: Int
    public let intendedPauseMilliseconds: Int
}

```

Prefer paragraph, sentence, semicolon/colon, safe clause, whitespace and grapheme fallback. Protect decimal/version/URL/abbreviation patterns and CJK punctuation.

### 12.4 Streaming long-form

Current batch sets `shouldStream: false`. Change the architecture to:

```
for each segment:
  start normal streaming session
  suppress or optionally expose live playback
  incrementally write segment WAV
  run Fast review
  persist segment result
  release chunk state

```

This preserves flat memory even for audiobook-scale work.

### 12.5 Identity continuity

Shared seed helps but does not lock identity.

For Voice Design long form, test:

```
generate short designed reference
→ select/accept it
→ create one Base CloneConditioningHandle
→ synthesize every segment through the handle

```

This is Mac/offline first because it may switch model families and has higher setup cost.

### 12.6 Assembly and segment regeneration

Add `LongFormAudioAssembler`:

- punctuation-aware pauses;
- leading/trailing safe-silence trim;
- loudness matching;
- fade only in verified non-speech;
- joined-output QC and ASR;
- segment map.

Issue-derived UX should allow replay and regeneration of one segment without rerunning the entire project. The manifest stores generation-plan identity and accepted replacement history.

## 13. Unified quality review

### 13.1 Review depths

| Layer | Fast | Standard | Canonical |
| --- | --- | --- | --- |
| terminal/EOS/token cap | required | required | required |
| codec summaries | required | required | required |
| persisted-WAV QC | required | required | required |
| reference-free prosody | required | required | required |
| streaming continuity | when streaming | required | required |
| ASR/language | — | one pass | three-pass consensus |
| critical tokens | — | when risks exist | required |
| speaker/onset | workflow-dependent | clone/selected workflows | required for claims |
| delivery | — | focused paired A/B | required for promotion |
| long-form continuity | basic | required | required |
| candidate retry | — | max 2 on failure | experiment-defined |

### 13.2 Shipping boundary

Always-on generation may include:

- terminal/token-cap;
- output readability;
- finite/format/severe signal checks;
- lightweight codec anomaly counters;
- streaming sequence/frame continuity.

Do not put in first-audio critical path:

- ASR;
- speaker embedding;
- full prosody profile;
- candidate generation;
- long-form batch comparison.

### 13.3 Resource scheduler

```
A generate serially with one TTS model
B run CPU signal/prosody/stream review
C unload TTS
D run ASR serially if required
E load speaker evaluator only if required
F reload TTS once only for failed candidates
G publish report and discard transient arrays

```

### 13.4 GenerationQualityReport

One versioned report should join current evidence without reducing detail. Required identities include source, dirty state, model artifact, component digests, plan digest, algorithm bundle, review mode and audio SHA.

Do not use one blended “quality score.” Candidate ranking is lexicographic after all mandatory gates pass.

## 14. Proposed source layout

```
Packages/VocelloQwen3Core/Sources/VocelloQwen3Core/
  Engine/
    VocelloQwen3Engine.swift
    RuntimeOperationLease.swift
    EngineState.swift
  Generation/
    SynthesisPlan.swift
    SamplingPolicy.swift
    StreamChunkPolicy.swift
    GenerationSession.swift
    GenerationEventChannels.swift
    TerminalState.swift
  Clone/
    CloneConditioningHandle.swift
    ClonePromptArtifact.swift
  Models/
    PreparedModelBundle.swift
    ComponentIdentity.swift
    SharedComponentPool.swift
  Diagnostics/
    DiagnosticEvent.swift

Sources/QwenVoiceCore/
  Generation/
    ProductGenerationPlan.swift
    ProductGenerationPlanner.swift
    QwenVoiceGenerationSession.swift
    GenerationOutputAdapter.swift
    PreviewAudioTransport.swift
    PreviewAdmissionPolicy.swift
  Text/
    SpokenTextPlan.swift
    LanguagePlan.swift
    LongFormSegmentPlan.swift
  Quality/
    GenerationQualityReport.swift
    QualityGateRegistry.swift
    QualityReviewCoordinator.swift
  Models/
    SharedComponentCatalog.swift
    SharedComponentInstaller.swift
    SharedComponentMigration.swift
  LongForm/
    LongFormGenerationCoordinator.swift
    LongFormAudioAssembler.swift

```

### Files that should shrink or retire

| Current file/type | End state |
| --- | --- |
| `UnsafeSpeechGenerationModel` | Removed after actor-owned engine cutover. |
| direct public methods on `VocelloQwen3LoadedModel` | Internal/SPI implementation. |
| `VocelloQwen3ModelGenerationSession` current combined queue | Replaced by classified channels. |
| `NativeStreamingSynthesisSession` | Thin product output adapter, then renamed accordingly. |
| `MLXTTSEngine.activeModelOperation` | Replaced by core operation state; UI projection only. |
| `ServiceActiveGenerationCoordinator` | Replaced by atomic product-session admission or narrowed to connection ownership. |
| `Qwen3TalkerSamplingOverride` | Removed; planner maps variation to immutable policy. |
| `Qwen3SamplingOverrides.shared` | Diagnostic overlay only or removed. |
| `GenerationScopedEventRouter` | Progress/terminal router only; audio leaves `bufferingNewest`. |
| `LongFormBatchSegmenter` | Replaced by versioned planner. |
| duplicated platform persistence | Shared implementation with injected path. |

Do not begin by splitting `Qwen3TTS.swift` mechanically. First move policy and lifecycle authority out; then extract model-loading, prompt, sampler and streaming implementation behind characterization tests.

## 15. Phased implementation program

### R0 — Checkpoint, ADR and characterization

**Behavior change:** none.

- Tag the current accepted main.
- Create and verify an all-refs Git bundle.
- Write `docs/decisions/qwen3-runtime-convergence-refactor.md`.
- Add `config/runtime-refactor-contract.json`.
- Capture current plan identities, session traces, token sequences, chunk sequences, PCM/WAV hashes, RTF, TTFC and memory.
- Add synthetic model fixtures for session/event tests.
- Declare neutral budgets before implementation.

**Exit:** deterministic checks pass; rollback is proven; current canonical evidence is linked.

### R1 — Correctness prerequisites

**Behavior change:** correctness only.

PR 1:

- XPC reservation before timing, task and forwarder.
- gated task starts only after binding.
- repeated concurrent-submission stress.

PR 2:

- synchronized memory-pressure state.
- Thread Sanitizer/stress.
- update concurrency registry.

PR 3:

- one pressure-relief lease across cancel, terminal, trim/unload.
- deterministic suspension after cancellation to prove new admission remains blocked.

**Exit:** H-01/H-02 closed; cancellation/full-unload/recovery remains green.

### R2 — Actor-owned core and policy contracts

**Behavior change:** none; current product path remains control.

- Add `VocelloQwen3Engine`.
- Move loaded model behind actor.
- Add operation state machine.
- Add sampling/chunk/memory plan values.
- Implement request-local seed/top-K/min-P/residual sampling.
- Add opaque clone handle.
- emit typed diagnostics at source.
- compatibility wrappers delegate through actor.

**Exit:** no public overlapping mutation; existing app still uses old session.

### R3 — Classified channels

**Behavior change:** none outside diagnostic test route.

- Build bounded suspending audio channel.
- Build coalesced progress state.
- Build independent terminal promise.
- Build bounded diagnostics.
- update core session.
- run no-consumer, slow-consumer, cancellation and max-length stress.

**Exit:** observer behavior cannot change output or terminal.

### R4 — Product cutover

Do not cut all modes at once.

**R4A Custom**

- product planner maps current request exactly;
- product output adapter drains core session;
- preserve chunk size, sampling and memory;
- fixed-seed parity and M2/iPhone focused evidence.

**R4B Design**

- same procedure;
- preserve design conditioning/prewarm identity.

**R4C Clone**

- introduce clone handle;
- preserve transcript-backed and x-vector artifact behavior;
- schema-3 upgrade and hardware acceptance.

**R4D cleanup**

- remove direct mode stream calls from product;
- remove old core session;
- shrink facade public API;
- remove global product variation lock.

**Exit:** one shipping session across all hosts and modes.

### R5 — Preview and chunk optimization

- move audio out of `bufferingNewest`;
- add exact first-render metric;
- add first/later chunk policy;
- run chunk matrix;
- test AVAudioEngine preparation;
- introduce adaptive admission behind diagnostic plan;
- promote only eligible mode/variant/device cells;
- retain current smooth-first fallback.

**Exit:** zero audio loss/underrun; first-render target achieved.

### R6 — Shared components

**R6A storage**

- catalog vNext;
- shared component installer;
- atomic migration;
- exact byte/storage evidence.

**R6B runtime**

- component-digest cache key;
- one decoder object A/B;
- family-switch memory/load evidence.

**Exit:** storage benefit achieved; runtime reuse only if it wins.

### R7 — Text and long form

**R7A shadow plans**

- generate `SpokenTextPlan`, `LanguagePlan`, `SegmentPlan`;
- do not change output;
- compare current versus planned behavior.

**R7B spoken-text adoption**

- six priority languages, then ten;
- user review and ambiguity behavior.

**R7C streaming long form**

- segment sessions use streaming;
- new manifest;
- replay/regenerate segment.

**R7D identity/assembly**

- VoiceDesign-to-Clone A/B;
- boundary-aware assembler;
- joined review.

### R8 — Quality review

- unify report/gate registry;
- add codec and critical-token layers;
- calibrate semitone/profile prosody;
- add speaker/onset evaluator schedule;
- add long-form continuity;
- add Fast/Standard/Canonical CLI;
- pilot candidate two only after failure.

### R9 — Post-convergence research

Only now:

- decoder-stream trace;
- newer MLX substrate branch;
- custom Code Predictor primitive;
- optional compact model tier;
- multi-token/speculative model research.

These experiments must not reopen lifecycle or evidence ambiguity.

## 16. Recommended pull-request sequence

| PR | Scope | Behavior | Required proof |
| --- | --- | --- | --- |
| 1 | Refactor ADR, contract and baseline fixtures | none | deterministic |
| 2 | XPC reservation-before-side-effects | correctness | XPC stress |
| 3 | synchronized pressure monitor | correctness | TSan/stress |
| 4 | exclusive pressure-relief operation | correctness | cancellation hardware |
| 5 | core engine actor and state machine | shadow | contract tests |
| 6 | immutable sampling/chunk/memory policies | shadow | fixed-seed direct tests |
| 7 | clone conditioning handle | shadow | artifact tests |
| 8 | classified event channels | shadow | slow-consumer stress |
| 9 | Custom product-session cutover | structural | fixed-seed + M2/iPhone |
| 10 | Design cutover | structural | fixed-seed + quality |
| 11 | Clone cutover | structural | both clone modes |
| 12 | remove old lifecycle/global policy | cleanup | full deterministic |
| 13 | lossless preview transport + timing | structural | zero-drop stress |
| 14 | chunk policy + adaptive admission | optimization | canonical preview |
| 15 | shared component disk store | storage | migration/load |
| 16 | component-digest runtime reuse | optimization | switch/memory A/B |
| 17 | spoken/language/segment plans | shadow | corpus fixtures |
| 18 | streaming long-form + identity/assembly | product | long-form corpus |
| 19 | unified quality report/coordinator | QA | mutation suite |
| 20+ | MLX/decoder/kernel research | experimental | isolated canonical |

The exact count may be reduced, but sensitive behavior and mechanical movement should never be combined merely to reduce PR count.

## 17. Performance and quality gates

### 17.1 Structural neutral gate

Proposed initial neutral limits:

| Metric | Gate |
| --- | --- |
| median RTF regression | ≤3% |
| p95 RTF regression | ≤5% |
| peak physical-footprint increase | ≤150 MB |
| first-render regression | ≤100 ms |
| preview audio drops | 0 |
| preview underruns | 0 |
| hard trim/full unload during canonical generation | 0 |
| terminal count | exactly 1 |
| fixed-seed token sequence | identical |
| fixed-seed final PCM/WAV | identical where algorithm/chunk policy unchanged |
| QC/ASR/prosody | no new failure |

These are proposed program thresholds, not claims about current variance. The first baseline phase should confirm that they are realistic.

### 17.2 Preview promotion

- at least 15% p50 submit-to-first-render improvement in the promoted class;
- p95 no worse;
- zero canonical underruns;
- zero audio gaps/duplicates;
- no generation RTF or final output change;
- route/interruption and final handoff pass.

### 17.3 Shared component promotion

- exact digest and component manifest;
- no new network bytes;
- no migration data loss;
- same loaded runtime profile;
- no model-switch peak increase beyond budget;
- shared decoder reuse is optional if load benefit is not material.

### 17.4 Long-form promotion

- original-to-spoken transformation coverage;
- zero text loss/duplication;
- no segment token-cap terminal;
- memory remains length-bounded;
- every segment has one terminal and readable WAV;
- joined signal QC/ASR;
- adjacent speaker/onset/prosody within calibrated profile;
- issue-derived Chinese and VoiceDesign cases included.

### 17.5 Quality-review promotion

- severe synthetic defects fail;
- punctuation-compatible pauses do not hard-fail;
- critical numeral/date/unit errors fail;
- CJK uses CER;
- speaker thresholds use positive/negative distributions;
- analyzer working set is measured;
- no concurrent TTS and speaker evaluator on the 8 GB floor.

## 18. Rollout, branching and release strategy

### 18.1 Preserve a stable checkpoint first

Before R1:

```
git tag -a backup/runtime-convergence-baseline-2026-07-17 079757abc3524ad5c0308bb1d914a9ff151c0de6 \
  -m "Pre-refactor accepted Vocello runtime baseline"
git push origin refs/tags/backup/runtime-convergence-baseline-2026-07-17

git bundle create Vocello-runtime-convergence-baseline.bundle --all
git bundle verify Vocello-runtime-convergence-baseline.bundle
shasum -a 256 Vocello-runtime-convergence-baseline.bundle \
  > Vocello-runtime-convergence-baseline.bundle.sha256

```

A maintenance release of the current clone fixes and correctness prerequisites is preferable to leaving users on an older affected binary while a long refactor proceeds.

### 18.2 Main stays releasable

- each PR independently builds and tests;
- shadow paths are debug/benchmark-only;
- no permanent long-lived integration branch owns unique source;
- feature gates are registered, typed and default off;
- old path remains the control until mode parity passes;
- after acceptance, delete the old path promptly.

### 18.3 Shadow modes

Good shadow uses:

- build a product plan but generate with current request;
- produce new codec/prosody reports without gating;
- install shared-component manifest without deleting duplicates;
- run new core session in synthetic tests, not simultaneously with real model generation.

Bad shadow use:

- run two real 1.7B generations for every user request;
- hold two models;
- duplicate output publication;
- compare live sessions on the 8 GB floor.

### 18.4 Release boundaries

Suggested release boundaries:

1. **maintenance checkpoint:** correctness fixes and current clone/runtime work;
2. **runtime-convergence release:** one session and classified event delivery, no new user behavior;
3. **performance release:** preview/chunk/shared-component improvements;
4. **long-form/quality release:** spoken text, segment planning, identity and review.

This allows rollback and honest release notes.

## 19. Risk register

| Risk | Failure mode | Control |
| --- | --- | --- |
| Big-bang cutover | no known-good comparison | mode-by-mode strangler |
| Session wrapper keeps duplicate terminal | lifecycle remains split | model terminal internal; public terminal after output |
| Audio backpressure slows model | RTF regression | fast mandatory drain, measured bounded queue |
| XPC remains unbounded | service memory growth | stress first; acknowledgment/spool only if needed |
| Actor over-serialization | warm/prep latency | classify user/proactive/CPU-only work |
| Policy cache identity incomplete | stale prewarm/prompt | one plan digest |
| Request-local seed changes output | parity loss | structural phases preserve exact current seed behavior |
| Shared component migration corrupts install | model unavailable | atomic publish, retain old copy until load |
| Shared decoder retains too much RAM | pressure regression | separate storage and object-reuse phases |
| Spoken normalizer changes meaning | lexical correctness failure | inspectable transforms and ambiguity fail-closed |
| Segment planner changes prosody | long-form regression | shadow plan and corpus A/B |
| Identity lock changes delivery | voice stable but wrong style | delivery plus speaker gates |
| Quality system blocks first audio | latency regression | heavyweight review after generation |
| Candidate retry doubles latency | poor UX/energy | failure-triggered, Mac/offline, maximum 2 |
| MLX upgrade confounds refactor | unknown output/perf drift | isolated post-convergence branch |
| Custom kernel becomes maintenance burden | fragile backend | one-layer proof and fallback |
| Giant PR hides defects | review failure | 12–18 focused PRs |
| Evidence overfits one prompt | false confidence | current matrix plus issue-derived corpus |
| iPhone behavior inferred from Mac | mobile regression | physical-device focused gates |
| Old path never removed | permanent complexity | deletion is an explicit phase exit criterion |

## 20. Explicit no-go list

Do not:

- replace the top-level host topology;
- remove XPC from macOS;
- move iPhone MLX to an extension;
- create a second “research backend”;
- make non-streaming the quality mode;
- hold every model or component warm on 8 GB;
- parallelize candidates or segments;
- use `bufferingNewest` for audio;
- let progress backpressure fail synthesis;
- keep sampling/memory state in hidden globals;
- combine lifecycle migration with MLX upgrade or custom quantization;
- change official sampling defaults during structural cutover;
- rewrite the PCM limiter/incremental writer while changing session authority;
- add Python or a local server to the app;
- run a heavyweight neural judge beside TTS;
- use one opaque quality score;
- silently normalize ambiguous text;
- apply blanket crossfades over speech;
- merge the entire program in one pull request;
- claim completion before current M2 and iPhone evidence passes.

## 21. Immediate next actions

### First five actions

1. **Approve the refactor as a convergence program**, not an optimization ticket.
2. **Create the baseline tag, bundle, ADR and characterization suite.**
3. **Fix XPC admission ordering and the memory-pressure race before architectural migration.**
4. **Implement the actor-owned engine and classified channels in shadow mode.**
5. **Cut over Custom Voice first**, because it is the simplest path and has the strongest realtime performance baseline.

### First implementation artifact

The first code-producing design PR should contain only:

- `VocelloQwen3Engine` state/lease contracts;
- request-local policy types;
- classified channel interfaces;
- synthetic tests;
- no product call-site change.

This allows the architecture to be challenged before it carries output.

### First behavior-changing milestone

Custom Voice structural parity:

```
current direct mode stream
versus
new actor/session/output adapter

```

Same:

- prepared bundle;
- prompt;
- seed;
- sampling;
- chunk schedule;
- memory policy;
- output path semantics;
- telemetry identity.

Acceptance requires exact token/chunk/PCM evidence and neutral performance.

## 22. Definition of done

The refactor is complete when:

1. one actor owns every MLX-mutating operation;
2. all three hosts use one product generation session;
3. no platform host creates generation side effects before admission;
4. pressure cancellation and trim/unload hold one exclusive lease;
5. the memory-pressure snapshot is synchronized;
6. sampling, seed, chunk and memory policy are immutable per session;
7. public seed/top-K fields are genuinely supported;
8. clone synthesis uses one opaque identity-bound handle;
9. audio, progress, terminal, prepared state and diagnostics have separate delivery contracts;
10. slow progress/diagnostic consumers cannot affect synthesis;
11. supported preview paths have zero audio drops;
12. final output remains incremental and atomically published;
13. streaming memory remains approximately flat with utterance length;
14. the M2 8 GB canonical matrix remains within declared neutral budgets;
15. physical-iPhone cancellation, clone, memory and preview gates pass;
16. three Speed packages use one verified speech-tokenizer copy on disk;
17. prepared component caches use component identity rather than model-directory identity;
18. long-form segments are duration/token planned and generated through the streaming path;
19. VoiceDesign long-form identity has a proven direct-versus-clone-lock decision;
20. original and spoken text are both preserved with version identity;
21. quality evidence is one report with Fast/Standard/Canonical modes;
22. expensive evaluators execute sequentially after TTS unload;
23. selective retry is never the interactive/iPhone default;
24. old direct mode streams, old combined event channel and global policy shims are removed;
25. documentation, public API baseline, concurrency registry, evidence impact and project health describe the actual final system.

## 23. Final recommendation

Vocello should proceed with the refactor.

The project has already proved the difficult product thesis: Qwen3-TTS 1.7B can run locally with strong memory discipline, realtime-or-better Custom/Design performance on an 8 GB M2, physical-iPhone support, live preview and robust evidence. The purpose of the refactor is not to replace that success. It is to make the success the only architecture.

The correct order is:

```
correctness
→ authority convergence
→ session/event cutover
→ preview/chunk optimization
→ shared components
→ spoken text and long form
→ unified quality review
→ framework/kernel/model research

```

The wrong order is:

```
add adaptive preview
+ add sampler profiles
+ add long-form identity
+ add shared decoder
+ add quality retry
on top of two sessions and three event policies

```

That would increase performance risk and make later debugging harder.

**Proceed, but keep the refactor contract-first, mode-by-mode, output-neutral before optimization, and continuously bound to the M2 8 GB and physical-iPhone evidence.**

## 24. Source index

### Joined reports

- `Vocello_Qwen3TTS_1_7B_4bit_Research_Leverage_Assessment_2026-07-16(1).html`
- `Vocello_Audio_Quality_Review_System_Reference_2026-07-16(1).html`
- `QwenVoice_Performance_Optimization_Deep_Dive_and_Roadmap_2026-07-17(1).html`
- `QwenVoice_Updated_Exhaustive_Project_Review_2026-07-16(1).html`

### Current repository

- [Project health](https://github.com/PowerBeef/Vocello/blob/079757abc3524ad5c0308bb1d914a9ff151c0de6/docs/project-health.md)
- [Development checkpoint](https://github.com/PowerBeef/Vocello/blob/079757abc3524ad5c0308bb1d914a9ff151c0de6/docs/development-progress.md)
- [Architecture](https://github.com/PowerBeef/Vocello/blob/079757abc3524ad5c0308bb1d914a9ff151c0de6/docs/ARCHITECTURE.md)
- [MLXTTSEngine](https://github.com/PowerBeef/Vocello/blob/079757abc3524ad5c0308bb1d914a9ff151c0de6/Sources/QwenVoiceCore/MLXTTSEngine.swift)
- [ActiveGenerationCoordinator](https://github.com/PowerBeef/Vocello/blob/079757abc3524ad5c0308bb1d914a9ff151c0de6/Sources/QwenVoiceCore/ActiveGenerationCoordinator.swift)
- [NativeEngineRuntime](https://github.com/PowerBeef/Vocello/blob/079757abc3524ad5c0308bb1d914a9ff151c0de6/Sources/QwenVoiceCore/NativeEngineRuntime.swift)
- [NativeStreamingSynthesisSession](https://github.com/PowerBeef/Vocello/blob/079757abc3524ad5c0308bb1d914a9ff151c0de6/Sources/QwenVoiceCore/NativeStreamingSynthesisSession.swift)
- [NativeMemoryPressureMonitor](https://github.com/PowerBeef/Vocello/blob/079757abc3524ad5c0308bb1d914a9ff151c0de6/Sources/QwenVoiceCore/NativeMemoryPressureMonitor.swift)
- [GenerationEventDeliveryProbe](https://github.com/PowerBeef/Vocello/blob/079757abc3524ad5c0308bb1d914a9ff151c0de6/Sources/QwenVoiceCore/GenerationEventDeliveryProbe.swift)
- [UnsafeSpeechGenerationModel](https://github.com/PowerBeef/Vocello/blob/079757abc3524ad5c0308bb1d914a9ff151c0de6/Sources/QwenVoiceCore/UnsafeSpeechGenerationModel.swift)
- [NativeCloneSupport](https://github.com/PowerBeef/Vocello/blob/079757abc3524ad5c0308bb1d914a9ff151c0de6/Sources/QwenVoiceCore/NativeCloneSupport.swift)
- [GenerationSemantics](https://github.com/PowerBeef/Vocello/blob/079757abc3524ad5c0308bb1d914a9ff151c0de6/Sources/QwenVoiceCore/GenerationSemantics.swift)
- [SemanticTypes](https://github.com/PowerBeef/Vocello/blob/079757abc3524ad5c0308bb1d914a9ff151c0de6/Sources/QwenVoiceCore/SemanticTypes.swift)
- [PromptLanguageDetector](https://github.com/PowerBeef/Vocello/blob/079757abc3524ad5c0308bb1d914a9ff151c0de6/Sources/QwenVoiceCore/PromptLanguageDetector.swift)
- [NativeMemoryPolicyResolver](https://github.com/PowerBeef/Vocello/blob/079757abc3524ad5c0308bb1d914a9ff151c0de6/Sources/QwenVoiceCore/NativeMemoryPolicyResolver.swift)
- [EngineServiceHost](https://github.com/PowerBeef/Vocello/blob/079757abc3524ad5c0308bb1d914a9ff151c0de6/Sources/QwenVoiceEngineService/EngineServiceHost.swift)
- [AudioPlayerViewModel](https://github.com/PowerBeef/Vocello/blob/079757abc3524ad5c0308bb1d914a9ff151c0de6/Sources/SharedSupport/ViewModels/AudioPlayerViewModel.swift)
- [BatchGenerationRunner](https://github.com/PowerBeef/Vocello/blob/079757abc3524ad5c0308bb1d914a9ff151c0de6/Sources/Services/BatchGenerationRunner.swift)
- [AudioQualityGate](https://github.com/PowerBeef/Vocello/blob/079757abc3524ad5c0308bb1d914a9ff151c0de6/Sources/Services/AudioQualityGate.swift)
- [GenerationOutputVerifier](https://github.com/PowerBeef/Vocello/blob/079757abc3524ad5c0308bb1d914a9ff151c0de6/Sources/SharedSupport/Services/GenerationOutputVerifier.swift)
- [Owned core contracts](https://github.com/PowerBeef/Vocello/blob/079757abc3524ad5c0308bb1d914a9ff151c0de6/Packages/VocelloQwen3Core/Sources/VocelloQwen3Core/Contracts.swift)
- [Owned core runtime](https://github.com/PowerBeef/Vocello/blob/079757abc3524ad5c0308bb1d914a9ff151c0de6/Packages/VocelloQwen3Core/Sources/VocelloQwen3Core/Runtime.swift)
- [Owned loaded model](https://github.com/PowerBeef/Vocello/blob/079757abc3524ad5c0308bb1d914a9ff151c0de6/Packages/VocelloQwen3Core/Sources/VocelloQwen3Core/LoadedModel.swift)
- [Owned generation session](https://github.com/PowerBeef/Vocello/blob/079757abc3524ad5c0308bb1d914a9ff151c0de6/Packages/VocelloQwen3Core/Sources/VocelloQwen3Core/GenerationSession.swift)
- [Qwen3 implementation](https://github.com/PowerBeef/Vocello/blob/079757abc3524ad5c0308bb1d914a9ff151c0de6/Packages/VocelloQwen3Core/Sources/MLXAudioTTS/Models/Qwen3TTS/Qwen3TTS.swift)
- [Code Predictor](https://github.com/PowerBeef/Vocello/blob/079757abc3524ad5c0308bb1d914a9ff151c0de6/Packages/VocelloQwen3Core/Sources/MLXAudioTTS/Models/Qwen3TTS/Qwen3TTSCodePredictor.swift)
- [Production model catalog](https://github.com/PowerBeef/Vocello/blob/079757abc3524ad5c0308bb1d914a9ff151c0de6/Sources/Resources/qwenvoice_production_model_catalog.json)
- [Prosody analyzer](https://github.com/PowerBeef/Vocello/blob/079757abc3524ad5c0308bb1d914a9ff151c0de6/scripts/analyze_prosody.py)
- [Prosody profile](https://github.com/PowerBeef/Vocello/blob/079757abc3524ad5c0308bb1d914a9ff151c0de6/scripts/prosody_profile.py)
- [Prosody gate](https://github.com/PowerBeef/Vocello/blob/079757abc3524ad5c0308bb1d914a9ff151c0de6/scripts/prosody_quality_gate.py)
- [Delivery adherence](https://github.com/PowerBeef/Vocello/blob/079757abc3524ad5c0308bb1d914a9ff151c0de6/scripts/delivery_adherence.py)

## Appendix A — Runtime state machine and failure semantics

### A.1 State transition model

The actor-owned runtime should expose a small state machine and keep all internal implementation details behind it.

| Current state | Request | Accepted transition | Rejected/queued behavior |
| --- | --- | --- | --- |
| `idle` | load | `loading → ready` | — |
| `ready` | same-model generation | `generating` | — |
| `ready` | different-model generation | `unloading/loading → generating` under one lease | — |
| `ready` | proactive prewarm | `prewarming → ready` | skip if pressure or user operation arrives |
| `prewarming` | user generation | cancel/await proactive work, then `generating` | user work wins |
| `generating` | second generation | none | typed busy rejection, zero side effects |
| `generating` | user cancel | internal cancellation; remain `generating` until model terminal and cleanup | first reason wins |
| `generating` | critical pressure | `relievingMemory` owns cancellation, terminal, trim/unload | new user work waits/rejects |
| `ready` | soft trim | `relievingMemory → ready` | proactive work blocked |
| `ready` | full unload | `unloading → idle` | — |
| `failed` | explicit reset/load | fresh validated load | old model state is not reused |

The public `ready` state means the engine can accept user work. It must not mean merely that a model object exists. A model can be loaded while:

- a trim is active;
- output finalization is incomplete;
- clone prompt construction owns MLX;
- a cancellation terminal is still draining;
- a service session is being retired.

Those states are not user-ready.

### A.2 Operation priorities

A deterministic priority order avoids ad hoc races:

```
critical memory relief
user cancellation / shutdown
active user generation
explicit user load/unload
clone conditioning requested by user
interactive prewarm requested by user intent
proactive warm/prefetch
idle unload/retirement

```

A lower-priority operation never steals a lease from a higher-priority one. Proactive work is cancelable and has no user-visible failure. Critical relief can preempt generation, but it must await the terminal barrier before touching model/cache state.

### A.3 Exactly-once completion

Every accepted generation owns:

```
generation ID
operation lease ID
model/session task
mandatory audio-drain task
product finalization task
first cancellation reason
internal model terminal
public product terminal

```

Exactly one code path claims the public terminal. A small terminal gate similar to the existing telemetry terminal gate can guard:

- success after readable final WAV and mandatory QC;
- cancellation after partial cleanup;
- failure after cleanup and privacy-safe diagnostics.

The terminal promise is not stored inside the audio queue. This prevents a full audio/progress queue from evicting or delaying terminal delivery.

### A.4 Error taxonomy

Keep user-facing messages in `QwenVoiceCore`, but use typed lower errors:

```
enum VocelloQwen3EngineError: Error, Sendable {
    case busy(active: RuntimeOperationKind)
    case incompatibleModel
    case invalidPlan(String)
    case unsupportedCapability(String)
    case cloneConditioningMismatch
    case allocationFailure
    case modelRuntimeFailure(String)
    case cancelled(VocelloQwen3CancellationReason)
}

```

Product mapping decides whether an error is:

- retryable allocation failure;
- recoverable model install problem;
- unsupported request;
- cancellation;
- terminal generation failure.

Do not parse arbitrary localized strings to identify typed behavior.

### A.5 Allocation retry

The current one-retry cleanup path is valuable. Under the target architecture:

1. first attempt owns the same generation ID and product operation lease;
2. retryable allocation failure does not publish a public failure;
3. audio/output from the first attempt is discarded;
4. cache/model cleanup occurs under the lease;
5. retry starts with a fresh low-level session;
6. only retry success or terminal retry failure claims the public terminal;
7. telemetry records both attempts without two contradictory public rows.

The retry policy belongs in `QwenVoiceCore`, because it decides output cleanup and user behavior. The core actor supplies typed allocation classification and safe unload.

## Appendix B — Event and output pipeline implementation notes

### B.1 BoundedAsyncChannel requirements

The channel used for model audio must support:

- one producer and one mandatory consumer;
- bounded capacity;
- suspending `send`;
- cancellation from either side;
- deterministic close with success or error;
- no element drop;
- queue-depth and producer-wait telemetry;
- no main-actor requirement;
- tests with injected suspension.

A channel capacity expressed in frames or seconds is easier to reason about than “96 events.” A reasonable first control is enough for two to four current chunks. The exact value is benchmarked.

### B.2 Product output adapter

`GenerationOutputAdapter` should absorb most of the current proven `NativeStreamingSynthesisSession` output logic:

```
start:
  create session directory
  create incremental writer
  reset pooled PCM limiter/scratch
  start telemetry sampler

for each audio chunk:
  validate sequence/model-session identity
  materialize samples
  convert and limit into reusable Int16 storage
  append final WAV
  create preview chunk if policy requests it
  update frame count and QC summaries
  publish product preview metadata
  release transient arrays

on model EOS:
  drain channel
  finish writer
  reopen and validate WAV
  run mandatory persisted-WAV QC
  write engine/product telemetry
  atomically publish result
  claim product success

on cancel/failure:
  discard writer
  remove partial output/session
  close preview
  write one terminal diagnostic
  claim cancelled/failed terminal

```

The adapter is required. An optional UI observer cannot replace it.

### B.3 Preview transport stages

Treat preview as three separately measured queues:

1. core audio → output adapter;
2. output adapter → platform transport;
3. platform transport → AVAudioPlayerNode queue.

Each stage records:

```
produced frames
received frames
queue depth in audio seconds
maximum wait
sequence gaps
duplicates
consumer termination

```

This localizes a preview problem. “No audio” could otherwise be generation, adapter, XPC, frontend validation, admission or AVAudioEngine.

### B.4 XPC transport evolution

Use a two-step strategy.

**Step one:** remove product audio from `bufferingNewest` and prove the existing serial XPC forwarder does not lose or accumulate preview under stress.

**Step two, only if needed:** add one of:

- acknowledgment window by chunk sequence;
- small shared-file spool with metadata over XPC;
- bounded service-side transport actor that pauses the product preview publisher.

The final WAV remains independent, so transport recovery must never corrupt output. A preview transport failure may disable live preview for the session and fall back to final-file playback, but it must be explicit and measured.

### B.5 Final handoff

The existing handoff logic contains hard-won race fixes. Preserve:

- late chunks remain admissible until the live queue drains;
- completed session IDs are recorded only at true drain/immediate handoff;
- stale completion callbacks are tagged by session ID;
- current playback time is preserved;
- a short generation that never reaches prebuffer starts from final file;
- cancellation removes the result and never persists History.

Refactor the owner, not the semantics.

## Appendix C — File-by-file implementation map

### C.1 Owned core package

| Current file | Recommended work |
| --- | --- |
| `VocelloQwen3Core/Contracts.swift` | Add immutable synthesis, stage-sampling, chunk and memory contracts. Remove or implement unsupported public fields. |
| `Runtime.swift` | Move process-global application behind the actor; choose one prepared-trust authority; emit typed diagnostics. |
| `LoadedModel.swift` | Make direct methods internal; expose only through `VocelloQwen3Engine`. |
| `GenerationSession.swift` | Replace the one combined non-suspending channel with classified delivery and independent terminal. |
| `Qwen3TTS.swift` | Accept request-local policies; remove static production overrides; retain the current hot loop and streaming decoder initially. |
| `Qwen3TTSCodePredictor.swift` | No structural change during convergence; keep fused RoPE and compiled SwiGLU. |
| clone prompt/artifact files | Preserve schema 3; add handle resolver and identity checks. |
| package cache code | Later key by component digest; do not mix with session cutover. |

### C.2 QwenVoiceCore

| Current file | Recommended work |
| --- | --- |
| `MLXTTSEngine.swift` | Become a thin `@MainActor` product state/protocol adapter; remove independent model operation authority after cutover. |
| `ActiveGenerationCoordinator.swift` | Its semantics become part of the core operation/session actor or a product terminal wrapper; avoid two authorities. |
| `NativeEngineRuntime.swift` | Separate CPU/product preparation from MLX-mutating operations. Call the core actor for model work. |
| `NativeStreamingSynthesisSession.swift` | Extract/rename to `GenerationOutputAdapter`; consume the core session. |
| `GenerationEventDeliveryProbe.swift` | Retain accounting for progress/terminal; remove audio from drop semantics. |
| `UnsafeSpeechGenerationModel.swift` | Delete after mode cutover. |
| `NativeMemoryPressureMonitor.swift` | Synchronize state and route events into exclusive engine relief. |
| `NativeMemoryPolicyResolver.swift` | Produce immutable policy snapshots; keep safe tier defaults. |
| `NativeCloneSupport.swift` | Continue normalization/persistence; resolve an opaque engine handle rather than pass raw prompt separately. |
| `SemanticTypes.swift` | Replace variation-only surface with a plan reference while preserving UI preference. |
| `GenerationSemantics.swift` | Consume `SpokenTextPlan`/`LanguagePlan`; preserve prompt assembly behavior. |
| `PromptLanguageDetector.swift` | Return confidence/source through `LanguagePlan`. |
| model catalog/downloader | Add shared components in a separate phase. |

### C.3 Platform and app

| Current file | Recommended work |
| --- | --- |
| `EngineServiceHost.swift` | Reservation-first admission; forward one accepted product session; preserve retirement. |
| XPC codec/protocol | Carry plan/policy versions and classified events without raw model types. |
| `XPCNativeEngineClient.swift` | Map one session terminal; preserve exact chunk sequence. |
| macOS/iOS `TTSEngineStore` | Display product session state only; no model ownership. |
| `AudioPlayerViewModel.swift` | Add prepared-engine A/B, exact first-render telemetry and adaptive admission; preserve continuity/handoff fixes. |
| `BatchGenerationRunner.swift` | Replace segmenter/manifest and use streaming internally. |
| generation views | Build/edit original text; display spoken plan/risk when appropriate. |
| History/persistence | Store original text and plan/version digest; avoid raw private evidence in tracked reports. |

### C.4 Development tooling

| Current tool | Recommended work |
| --- | --- |
| `analyze_prosody.py` | Add semitone/phrase features and bounded long-file processing. |
| `prosody_profile.py` | Schema 2 selectors plus median/MAD profiles. |
| `prosody_quality_gate.py` | Profile-calibrated decisions instead of one absolute voice threshold. |
| `delivery_adherence.py` | Style-specific expectations, accuracy and identity deltas. |
| benchmark schemas | Add plan, component, session and quality identities. |
| project health | Track refactor phase, old-path deletion, audio-drop gate and quality-layer freshness. |

## Appendix D — Verification matrix by refactor domain

| Domain | Unit/fixture | Integration | M2 8 GB | Physical iPhone |
| --- | --- | --- | --- | --- |
| Operation lease | state transition/property tests | concurrent load/prewarm/generate/trim | pressure + recovery | memory warning + recovery |
| XPC admission | reservation tests | repeated second-request race | native service | N/A |
| Event channels | slow/no consumer, cancel, overflow | output adapter drain | preview stress | preview stress |
| Product terminal | terminal gate fixtures | file finalize/cancel/fail | canonical focused | smoke/benchmark |
| Sampling policy | serialization and validation | direct-vs-session fixed seed | sampler matrix | focused subset |
| Chunk policy | schedule fixtures | decoder boundary parity | first/later matrix | preview A/B |
| Clone handle | mismatch rejection | artifact load/rebuild | clone focused | both conditioning modes |
| Shared components | catalog/migration fixtures | install/load/switch | disk/load/memory | install/load/delete |
| Spoken text | per-language exact fixtures | ASR comparison | six/ten-language corpus | supported language subset |
| Segment plan | boundaries/token budgets | batch generation/assembly | issue #30/#54 corpus | not required initially |
| Quality report | schema/verdict/mutations | coordinator scheduling | analyzer memory | Standard subset |
| Cleanup/retirement | state fixtures | XPC exit/relaunch | RSS→0 | app memory release |

### D.1 Characterization versus acceptance

**Characterization tests** document current behavior, including awkward behavior, and protect the structural migration.

Examples:

- exact prompt string;
- exact seed and sampler values;
- exact first/later chunk sizes;
- exact event sequence;
- exact PCM hash;
- exact cache-clear count.

**Acceptance tests** state the intended contract after optimization.

Examples:

- zero audio drops;
- lower first-render time;
- shared component storage;
- improved long-form identity.

Do not rewrite characterization baselines to make a new implementation pass. Change them only when an accepted behavior phase intentionally changes the contract.

### D.2 Dirty versus clean evidence

Use dirty exploratory runs during development. Promotion requires:

- clean source;
- exact plan/component/model identity;
- declared comparison cell;
- complete terminal and memory contract;
- no unexplained warning;
- canonical hardware where the domain requires it.

## Appendix E — Refactor operating model

### E.1 Review discipline

For sensitive PRs:

- separate mechanical file movement from behavior;
- include an invariant checklist in the PR body;
- include a before/after sequence diagram;
- include test evidence and declared untested boundaries;
- request an independent or adversarial review for XPC, concurrency, model lifecycle and release work;
- keep each behavioral change small enough to reason about.

The previous large overhaul succeeded strategically but left source-visible interleavings. The next program should optimize reviewability as seriously as runtime performance.

### E.2 Decision records

Create short ADRs for:

1. actor-owned runtime and operation lease;
2. public versus internal terminal boundary;
3. event delivery classes;
4. request-local sampling and chunk policies;
5. shared component store;
6. spoken-text and long-form plan identity;
7. quality-review shipping boundary.

Each ADR should list:

- decision;
- alternatives;
- protected invariants;
- evidence required for reversal;
- compatibility/removal plan.

### E.3 Performance decision ledger

Every optimization receives:

```
experiment ID
source commit
model/component identity
plan/policy identity
control
treatment
hardware
thermal/cold-warm conditions
metrics
quality gates
decision
removal/retest trigger

```

This preserves the project's strongest habit: negative experiments prevent future rework.

### E.4 Resource budgeting

Refactor work should maintain three explicit budgets:

**Generation budget**

- model + active inference;
- streaming decoder;
- output scratch;
- preview queues;
- telemetry.

**Idle-ready budget**

- active model;
- selected shared decoder/cache;
- app UI;
- no orphaned sessions.

**Review budget**

- TTS unloaded before model-dependent evaluator;
- one WAV/frame block at a time;
- no raw arrays retained after report;
- cached compact transcripts/embeddings by digest.

A component is not “free” because it is shared. Shared memory still consumes unified memory and must participate in relief/retirement.

### E.5 Stop conditions

Pause the refactor phase and revert when:

- output parity fails without an intentional behavior change;
- memory becomes length-growing;
- audio drops or terminal duplication appear;
- cancellation cannot prove cleanup;
- performance regression exceeds the declared budget;
- test/evidence identity is incomplete;
- the old and new authorities become entangled rather than one delegating to the other.

A stop is an engineering success when it prevents an ambiguous architecture from landing.   Prepared from four joined Vocello reports and exact-ref source inspection at 079757abc3524ad5c0308bb1d914a9ff151c0de6. Proposed gains and budgets are explicitly identified as targets requiring evidence.
