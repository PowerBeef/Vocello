# Vocello Qwen3 runtime performance architecture

This document explains the causal performance and memory design of the owned Qwen3 runtime. It
does not turn every experiment into a shipped optimization: `RUNTIME_CAPABILITIES.json` is
authoritative for current behaviour and evidence freshness, `SEMANTIC_DELTAS.json` is the active
semantic delta ledger, and `UPSTREAM_BASELINE.json` remains the immutable imported-byte inventory.
Benchmark records stay diagnostic after a runtime-impacting source change until a clean record
matches the current capability sources. MLX mechanics (evaluation, error scopes, quantization, cache
clearing, pins) are [`docs/reference/mlx-guide.md`](../../docs/reference/mlx-guide.md)'s; the model
and its parity with the reference are
[`docs/reference/qwen3-tts-guide.md`](../../docs/reference/qwen3-tts-guide.md)'s.

## Loading and prepared state

Model resolution includes the repository revision in cache identity. Prepared loading validates the
checkpoint once, records the required capability profile, and reuses only the immutable text
tokenizer through a platform-bounded LRU (one entry on iOS, three on macOS). Weight materialization
is batched to bound transient unified-memory peaks. Clone-capable profiles include the learned
encoders, while ordinary synthesis may load the decoder-only tokenizer surface.

The speech tokenizer stays resident across generations on macOS and, gated by device class
(physical memory of 7 GB or more), on iOS (`speechTokenizerResidencySupported`,
`Sources/MLXAudioTTS/Models/Qwen3TTS/Qwen3TTS.swift:485-508`; status in
`config/runtime-refactor-contract.json` `phaseStatus.runtimeComponentReuse`;
`QWENVOICE_TOKENIZER_RESIDENCY` is the registered diagnostic override). **The iOS gate was qualified
on the withdrawn f16 codec** (A-19): the gate was adopted because artifact version 2026.08.01.1's
f16 tokenizer cut the resident decoder to about 218 MB, and it qualified on the iPhone 17 Pro on
2026-08-02 under those artifacts. 2026.09.14.1 restored the fp32 tokenizer
([`model-delivery.md`](../../docs/reference/model-delivery.md)), and no qualification of the fp32
tokenizer's residency on iOS is recorded. Residency never bypasses
engine-operation isolation or reset: a critical trim and a full unload invalidate the resident
cache, and every loaded model still owns its mutable decoder state.

Known gaps: the conditioning-prefix and text-tokenizer caches are keyed by install path, so they
survive a Mac unload, delete or in-session model update (A-10); a trusted prepared load checks only
for unused keys (A-20); and every quantized load leaks its initialization graph (mlx-guide §3.5).

Cold-load evidence must include the model-loading lifecycle boundaries. A warm generation is not
evidence that the loader or the prepared-state trust path is correct.

## Clone conditioning

The speaker encoder does not use the generic Whisper-style mel helper. Clone conditioning uses the
official Qwen frontend contract (`qwen-speaker-mel-v1`): reflect padding, a periodic Hann window,
magnitude STFT, Slaney mel scale and normalization, and natural-log features. Extracted embeddings
are materialized, validated as finite `float32 [1, D]` (the check runs on the CPU stream, so adopting
a stored artifact submits no Metal work), and bound to the decoded encoder and talker dimension
before they enter transcript-backed or x-vector-only generation. They are cast to the talker's
compute dtype only at prefix construction. The transcript-backed reference encode is evaluated
inside prompt creation (F-07), so its lazy graph does not run later in persistence or a take.

The prompt identity includes the model repository, pinned revision, artifact version, installed
integrity-manifest digest, runtime topology and the composite speaker-feature version (the mel
frontend, the reference-encode preprocessing and the MLX build; `CLONE_ARTIFACT_FORMAT.md`).
Changed weights, frontend code, runtime profile or MLX build therefore cannot hit an older in-memory
entry or persisted artifact. This matters most for x-vector-only mode, where no reference codes can
compensate for a malformed speaker embedding. The identity does not yet name the codec encoder's
implementation, which has a known RoPE defect (A-02, G-03; `CLONE_ARTIFACT_FORMAT.md`).

## Sampling and the hot loop

Sampling algorithm v2 resolves one immutable policy at the product boundary. Every request has an
effective seed and owns a fresh `MLXRandom.RandomState`; categorical draws run under that
task-local state and never advance the process-global RNG.

- **Talker.** Under the default Expressive variation the talker uses the official generation
  parameters; Balanced and Consistent lower its temperature and top-p.
- **Code predictor (subtalker).** It samples at the reference's 0.9 / top-k 50 / top-p 1.0 for every
  variation (RF-18 follow-up screen, 2026-10-20), remains independently configurable through
  diagnostics, takes the talker's min-p (0 in production), and never applies the repetition penalty.
- **Precision.** Both stages sample from float32 logits, as Qwen's reference does (SAMPLER-003,
  production since 2026-10-13); the cast is lazy inside the per-frame graph and adds no
  synchronization.
- **Order and EOS.** Temperature is applied before probability filtering. The talker's EOS is
  filtered by top-k/top-p like any token (D2, production since 2026-10-20);
  `QWENVOICE_TALKER_FILTER_EOS=off` restores the older re-insertion after the filters.
- **Hot-loop state.** Repetition state is maintained incrementally (constant-time membership over a
  first-seen token order), and reusable sampler and mask scratch avoids rebuilding equivalent arrays
  each step. The prewarm draws once through the production sampler on a private random state, so its
  kernels are compiled before the first take without changing any output.

Diagnostic environment values are resolved into the request policy before the model is invoked;
they are not static mutable runtime authority. Seeded takes reproduce within one source identity
only: the float32 change, the 2026-10-20 subtalker and EOS changes and MLX 0.32.3's sampler each
changed what a seed produces (mlx-guide §4.5).

Lazy MLX timings around graph construction are not kernel attribution. Performance conclusions
must use the tracked benchmark registry or an Instruments profile with the runtime signposts.

## Production streaming

The producer retains only the pending codes needed for the next decode. A mode- and profile-specific
first chunk establishes initial playback; later chunks may be larger to amortize decoder work. Each
frame's step graph is submitted with `asyncEval`, and the previous chunk's materialization and sends
overlap it (the `.pipelined` step policy; mlx-guide §4.3). The Mimi decoder keeps causal state across
partitions. The actor-owned suspending producer materializes `[Float]` in the caller's isolation
before its awaited sink, and the final chunk always has an explicit barrier before terminal
completion and atomic WAV publication. Compatibility stream methods remain only behind the narrowed
load and prewarm bridge and are not product generation authority.

Cancellation terminates the producer, resets reusable state, and produces exactly one terminal
result. The generation gate permits one owner, transfers FIFO, and handles cancellation after
ownership transfer without releasing another task's permit.

The engine session separates delivery by semantic class. Custom, Design and Clone expose a direct
materialized producer to the engine without an intermediate `AsyncThrowingStream` or an MLX value
crossing isolation. Core audio has one mandatory consumer and a suspending capacity measured in
frames, so a slow output adapter applies bounded backpressure to the token and decode loop instead
of dropping final audio or turning consumer speed into a runtime failure. The channel records its
frame high-water mark, producer suspension duration and cancellation wakeups. Prepared state is
replay-latest, progress is monotonic and coalesced, model terminal is an independent promise, and
diagnostics are bounded, PCM-free and explicitly lossy.

Reservation alone creates no model task. Generation opens only after the output adapter claims the
audio drain, and model EOS moves the same operation lease to product finalization rather than
releasing it. The adapter must drain every frame, finalize and reopen the WAV, run mandatory Fast QC,
publish or clean up atomically, and return the opaque generation and lease token. An identical
repeated acknowledgment is idempotent; a stale or conflicting token cannot release a newer lease.
The old fixed-count mixed facade event channel remains only as a package characterization surface;
QwenVoiceCore product generation does not use it.

## Memory and caches

Pending-token retention, platform-sized prepared caches, a bounded MLX cache policy, reusable PCM
scratch and per-tier cleanup keep resident growth controlled. The per-tier clear points and their
cost are in mlx-guide §5.3–§5.4. Sliding-window and quantized KV experiments, legacy speed profiles
and alternate eval strategies must be read through their ledger state; a knob in source is not proof
that it is active or beneficial. The talker KV cache is the unbounded bf16 `KVCacheSimple`, and the
codec decoder does not apply the reference's 72-frame window, so its KV grows over the take (A-03).

Memory-qualified benchmarks use telemetry schema v8 and evidence manifest v2. One process has one
memory series: the macOS app hosts the engine, so its app and engine samplers are two readers of that
process and their samples are merged by uptime, never summed (memory contract v2; contract-v1
records paired and summed the two layers' samples by uptime).

## Mimi decoder correctness

The speech-tokenizer decoder uses input-side overlap-and-discard, exact block-count fallback,
explicit reset isolation, and timing/no-timing parity. Fixed and randomized partitions must produce
the same waveform within floating-point tolerance: `Qwen3DecoderPartitionTests` bounds the difference
at 1e-5 max absolute and 1e-6 RMS; it is not bit-exact. The generic
`streamingDecode(..., chunkTokens: 100)` helper represents about eight seconds of 12.5 Hz codec
frames; production streaming derives much smaller first and later chunk sizes from the requested
interval and mode profile.

Quality-first (non-streaming) decode, its in-context clone reference cut and codec replay share one
sample window: `[reference, reference + generated) × decode upsample rate`, clamped to the decoded
length. The window comes from explicit frame counts with an integer start; it never counts non-zero
codes, because code 0 is a legal codec token (DECODE-002).

## Evidence states

- **production**: executed in the shipping runtime.
- **diagnostic**: available only for measurement or fault isolation.
- **internal**: package assurance or support behaviour not exposed as a product capability.
- **retired**: historical behaviour that is no longer current.

The historical delta ledger has a broader state vocabulary for upstream comparison. Those labels do
not override the current capability contract.

Current measured results live in `benchmarks/HISTORY.md`. Historical optimization narratives may
explain why a path was rejected, but they are never current performance evidence by themselves.
