---
status: historical
owner: release-qa
summary: 04 — Correctness, Concurrency, Integrity, and Maintainability Findings. Archived point-in-time audit. Pinned historical record of findings as they stood at capture.
contentDigest: sha256:c98607a9f97492a99d5d79e40651cec4cf0b387911db55af6c5f000dc9f24318
---
# 04 — Correctness, Concurrency, Integrity, and Maintainability Findings

> **Historical snapshot.** This report is pinned to Vocello commit
> `05bd2b6d24b3f43351f3b388622a72d8f0d6ecce`. It is research evidence, not the current runtime,
> telemetry, or benchmark contract. See the [series notice](README.md) and current documentation.


- **QwenVoice/Vocello:** `05bd2b6d24b3f43351f3b388622a72d8f0d6ecce`
- **Recorded upstream import baseline:** `fcbd04daa1bfebe881932f630af2ba6ce9af3274` (`v0.1.2`)
- **Upstream comparison head:** `d302a5c6080d2bb97bae38c7418f82abb76013b6`
- **Review date:** 2026-07-10


## Severity policy

- **High:** can indefinitely stall the backend, corrupt a durable product invariant, or make successful operation unreliable under ordinary cancellation/error conditions.
- **Medium-High:** can expose invalid learned components or persistent conditioning, but generally requires a corrupt/incomplete local artifact or an untested edge path.
- **Medium:** significant maintenance, observability, or boundary weakness.
- **Low:** localized hygiene or documentation concern.

## High

### H1 — Generation-gate ownership can leak after cancellation transfer

**Status:** confirmed source-level defect.

The actor resumes a queued waiter while retaining the logical held state. The resumed task marks transfer, then performs a final cancellation check. A cancellation after resume but before completion of `acquire()` can throw after ownership transferred. Because the outer `withGenerationGate` body has not started, its release handling cannot run.

**Impact:** later prewarm/generation calls can wait indefinitely.

**Evidence:** [`third_party_patches/mlx-audio-swift/Sources/MLXAudioTTS/Models/Qwen3TTS/Qwen3TTS.swift`](https://github.com/PowerBeef/Vocello/blob/05bd2b6d24b3f43351f3b388622a72d8f0d6ecce/third_party_patches/mlx-audio-swift/Sources/MLXAudioTTS/Models/Qwen3TTS/Qwen3TTS.swift) — `Qwen3TTSGenerationGate.acquire`, `release`, and `withGenerationGate`.

**Repair:** make ownership an explicit permit/lease or perform the post-transfer cancellation check inside a scope that releases on every throw. Test with a deterministic hook immediately after continuation resume.

### H2 — Fork-specific behavior lacks a dedicated deterministic test target

**Status:** confirmed assurance gap.

The vendor package has no test target, while the fork adds concurrency, persistent tensors, custom sampler behavior, caches, prewarm, alternate completion semantics, and numerical streaming changes.

**Impact:** high-risk paths depend on platform/system tests and benchmark runs rather than fast deterministic regression tests.

**Evidence:** [`third_party_patches/mlx-audio-swift/Package.swift`](https://github.com/PowerBeef/Vocello/blob/05bd2b6d24b3f43351f3b388622a72d8f0d6ecce/third_party_patches/mlx-audio-swift/Package.swift) versus [`Tests/MLXAudioTTSTests.swift`](https://github.com/Blaizzy/mlx-audio-swift/blob/d302a5c6080d2bb97bae38c7418f82abb76013b6/Tests/MLXAudioTTSTests.swift).

## Medium-High

### MH1 — Learned component can be returned without learned weights

When requested speaker-encoder weights are empty, a constructed encoder can remain non-nil. When speech-tokenizer weights are empty, the update block is skipped and the initialized tokenizer can still be returned after a “loaded” log.

**Impact:** incomplete/corrupt prepared directories can expose randomly initialized components instead of failing at load.

**Repair:** require a nonempty, verified parameter set for every requested learned component; otherwise throw a typed artifact error or return nil when the capability is optional.

**Evidence:** [`third_party_patches/mlx-audio-swift/Sources/MLXAudioTTS/Models/Qwen3TTS/Qwen3TTS.swift`](https://github.com/PowerBeef/Vocello/blob/05bd2b6d24b3f43351f3b388622a72d8f0d6ecce/third_party_patches/mlx-audio-swift/Sources/MLXAudioTTS/Models/Qwen3TTS/Qwen3TTS.swift) — `loadTalkerComponents` and `loadSpeechTokenizer`.

### MH2 — Clone prompt tensors lack structural and cryptographic validation

Production publication is atomic, but load validates only manifest schema/metadata and reads named arrays. It does not bind each tensor file to a SHA-256, byte length, key set, dtype, dimensions, or clone-mode requirement.

**Impact:** local corruption or accidental replacement can produce delayed failure or incorrect conditioning.

**Repair:** add per-file and per-tensor descriptors to the manifest; reject extras, missing required tensors, wrong shapes/dtypes, or digest mismatch.

**Evidence:** [`third_party_patches/mlx-audio-swift/Sources/MLXAudioTTS/Models/Qwen3TTS/Qwen3TTS.swift`](https://github.com/PowerBeef/Vocello/blob/05bd2b6d24b3f43351f3b388622a72d8f0d6ecce/third_party_patches/mlx-audio-swift/Sources/MLXAudioTTS/Models/Qwen3TTS/Qwen3TTS.swift) and atomic wrapper [`Sources/QwenVoiceCore/NativeCloneSupport.swift`](https://github.com/PowerBeef/Vocello/blob/05bd2b6d24b3f43351f3b388622a72d8f0d6ecce/Sources/QwenVoiceCore/NativeCloneSupport.swift).

## Medium

### M1 — Fork-specific API leaks above BackendCore

QwenVoiceCore, CLI, native framework, app, and service link MLXAudio products directly. The strongest recommendation is not an absolute ban on neutral MLX data types; it is to isolate fork-specific generation protocols, loaders, diagnostics, and policy in BackendCore.

### M2 — Qwen3TTS.swift is a mixed-responsibility hotspot

It combines caches, clone serialization, generation gate, diagnostics, prewarm, prompt assembly, sampling, streaming/full-result loops, model loading, and weight sanitation.

Split by responsibility while preserving the single model type and fixed-seed behavior.

### M3 — Diagnostics are stringly typed

Timing and flag dictionaries are merged by key across vendor/Core layers. A typo or rename can silently break summarizers.

**Repair:** typed metric enum/structs, explicit schema version, one serialization adapter, compatibility tests.

### M4 — Cache identity is mostly string-composed

Prepared keys are canonical paths; conditioning and clone keys concatenate normalized strings. These are effective but difficult to audit for collisions and invalidation completeness.

**Repair:** typed key structs containing model digest, runtime profile, capability flags, language, speaker, and instruction/transcript digests.

### M5 — `@unchecked Sendable` scope is broad

The model's single-owner/gate contract can justify unchecked sendability, but that invariant should be executable:

- debug ownership assertions;
- no concurrent generation tests;
- cache-eviction races;
- cancellation at every boundary.

### M6 — Product environment policy is read inside vendor code

Sampling, cache, and diagnostic knobs are easier to reason about when resolved by BackendCore into immutable typed request policy.

### M7 — Prepared trust signature should bind dependency ABI

The trust marker should include exact MLX, MLX-LM, fork schema/API, architecture, and quantization ABI so a dependency upgrade cannot reuse an artifact under an old trust assumption.

### M8 — Upstream intake is documentary rather than automated

`UPSTREAM.md` records the import baseline but does not automatically watch relevant retained paths or record every disposition.

## Low

### L1 — Low-level clone serializer is unsafe as a general public persistence API

The product wrapper is safe. The vendor method should be internal/staging-only or clearly documented.

### L2 — Vendored README can describe removed upstream products

Replace it with a specialization README.

### L3 — Directory name implies a patch set

`third_party_patches` understates local ownership and encourages the wrong synchronization model.

### L4 — Generic StreamingWAVWriter lags upstream

Low production impact because QwenVoiceCore does not rely on it for the canonical final-file path.

## Explicit non-findings

1. **Production clone publication is not nontransactional.** It stages and atomically publishes directories.
2. **The model architecture is not missing the 2048→1024 projection, 2048-dimensional speaker conditioning, interleaved MRoPE, or Q/K normalization.**
3. **Rotating KV is not currently responsible for the measured streaming memory improvement.**
4. **Compiled SwiGLU is not unique to the fork.**
5. **The overlap-and-discard decoder change is intentional and should not be “simplified” back to upstream overflow accumulation without parity evidence.**
