# Vocello Qwen3 runtime performance architecture

This document explains the causal performance and memory design of the owned Qwen3 runtime. It
does not turn every experiment into a shipped optimization: `RUNTIME_CAPABILITIES.json` is
authoritative for current behavior and evidence freshness. `PATCHES.json` is the active semantic
delta ledger, while `UPSTREAM_BASELINE.json` remains the immutable imported-byte inventory.
Benchmark records remain diagnostic after a runtime-impacting source change until a clean record
matches the current capability sources.

## Loading and prepared state

Model resolution includes repository revision in cache identity. Prepared loading validates the
checkpoint once, records the required capability profile, and reuses only the immutable text
tokenizer through a platform-bounded LRU. The speech tokenizer is resident across generations on
macOS and, device-class gated (physical memory of 7 GB or more), on iOS
(`speechTokenizerResidencySupported`; status in `config/runtime-refactor-contract.json`
`phaseStatus.runtimeComponentReuse`; `QWENVOICE_TOKENIZER_RESIDENCY` is the registered diagnostic
override). Residency never bypasses engine-operation isolation or reset: critical trim and full
unload invalidate the resident cache, and every loaded model still owns its mutable decoder state.
Clone-capable profiles include learned encoders while ordinary
synthesis may load the decoder-only tokenizer surface. Weight materialization is batched to bound
transient unified-memory peaks.

Cold-load evidence must include the model-loading lifecycle boundaries. A warm generation is not
evidence that the loader or prepared-state trust path is correct.

## Clone conditioning

The speaker encoder does not consume the generic Whisper-style mel helper. Clone conditioning uses
the official Qwen frontend contract: reflect padding, a periodic Hann window, magnitude STFT,
Slaney mel scale and normalization, and natural-log features. Extracted embeddings are materialized,
validated as finite `float32 [1, D]`, and bound to the decoded encoder/talker dimension before they
enter either transcript-backed or x-vector-only generation. They are cast to the talker compute
dtype only at prefix construction.

The prompt identity includes the model repository, pinned revision, artifact version, installed
integrity-manifest digest, runtime topology, and speaker-feature algorithm version. Changed weights,
frontend code, or runtime profile therefore cannot hit an older in-memory entry or persisted clone
artifact. This is especially important for x-vector-only mode because no reference acoustic codes
can compensate for a malformed speaker embedding.

## Sampling and the hot loop

Sampling algorithm v2 resolves one immutable policy at the product boundary. Every request has an
effective seed and owns a fresh `MLXRandom.RandomState`; categorical draws run under that
task-local state and never advance the process-global RNG. The talker uses the official effective
generation parameters. The subtalker/Code Predictor inherits temperature, top-k, top-p, and min-p
by default, but remains independently configurable and never inherits repetition penalty.
Diagnostic environment values are resolved into the request policy before the model is invoked;
they are not static mutable runtime authority. Temperature is applied before probability filtering,
EOS remains eligible, repetition state is maintained incrementally, and reusable sampler/mask
scratch avoids rebuilding equivalent arrays in each token step. Sampling v2 requires fresh
fixed-seed quality evidence before its output is promoted as equivalent to historical v1 records.

Lazy MLX timings around graph construction are not kernel attribution. Performance conclusions
must use the tracked benchmark registry or an Instruments profile with the runtime signposts.

## Production streaming

The producer retains only pending codes needed for the next decode. A mode/profile-specific first
chunk establishes initial playback; later chunks may be larger to amortize decoder work. The Mimi
decoder maintains causal state across partitions. The shipping actor-owned suspending producer
materializes `[Float]` in the caller's isolation before its awaited sink, and the final chunk always
has an explicit barrier before terminal completion and atomic WAV publication. Compatibility stream
methods remain only behind the narrowed load/prewarm bridge and are not product generation authority.

Cancellation terminates the producer, resets reusable state, and produces exactly one terminal
result. The generation gate permits one owner, transfers FIFO, and handles cancellation after
ownership transfer without releasing another task’s permit.

The shipping engine session separates delivery by semantic class. Custom, Design, and Clone expose a
direct materialized producer to that engine without an intermediate `AsyncThrowingStream` or MLX
value crossing isolation. Core audio has one mandatory consumer and a suspending capacity measured
in frames, so a slow output adapter applies bounded backpressure to the actual token/decode loop
instead of dropping final audio or converting consumer speed into a runtime failure.
The channel records its frame high-water mark, producer suspension duration, and cancellation
wakeups. Prepared state is replay-latest, progress is monotonic and coalesced, model terminal is an
independent promise, and diagnostics are bounded, PCM-free, and explicitly lossy.

Reservation alone creates no model task. Generation opens only after the output adapter claims the
audio drain, and model EOS transitions the same operation lease to product finalization rather than
releasing it. The adapter must drain every frame, finalize and reopen the WAV, run mandatory Fast
QC, publish or clean up atomically, and return the opaque generation/lease token. An identical
repeated acknowledgment is idempotent; a stale or conflicting token cannot release a newer lease.
The old fixed-count mixed facade event channel remains only as a package characterization surface;
QwenVoiceCore product generation does not use it.

## Memory and caches

Pending token retention, platform-sized prepared caches, bounded MLX cache policy, reusable PCM
scratch, and per-tier cleanup keep resident growth controlled. Sliding/quantized KV experiments,
legacy speed profiles, and alternate eval strategies must be read through their ledger state; a
knob in source is not proof that it is active or beneficial.

Memory-qualified benchmarks use telemetry schema v8 and evidence manifest v2. Process memory
stays attributed to the process that measured it; macOS app/XPC totals use uptime-aligned samples.

## Mimi decoder correctness

The speech-tokenizer decoder uses input-side overlap-and-discard, exact block-count fallback,
explicit reset isolation, and timing/no-timing parity. Fixed and randomized partition tests must
produce the same waveform. The generic `streamingDecode(..., chunkTokens: 100)` helper represents
about eight seconds of 12.5 Hz codec frames; production Qwen streaming derives much smaller
first/later chunk sizes from the requested interval and mode profile.

## Evidence states

- **production**: executed in the shipping runtime.
- **diagnostic**: available only for measurement or fault isolation.
- **internal**: package assurance or support behavior not exposed as a product capability.
- **retired**: historical behavior that is no longer current.

The historical delta ledger has a broader state vocabulary for upstream comparison. Those labels do
not override the current capability contract.

Current measured results live in `benchmarks/HISTORY.md`. Historical optimization narratives may
explain why a path was rejected, but they are never current performance evidence by themselves.
