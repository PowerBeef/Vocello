---
status: historical
owner: release-qa
summary: 03 — Performance, Memory, Streaming, and Numerical Optimizations. Archived point-in-time audit. Pinned historical record of findings as they stood at capture.
contentDigest: sha256:2260a83e55136c03179ccae60b47da4faa63a72c309c1ebfa7626ddcd26fe0dd
---
# 03 — Performance, Memory, Streaming, and Numerical Optimizations

> **Historical snapshot.** This report is pinned to Vocello commit
> `05bd2b6d24b3f43351f3b388622a72d8f0d6ecce`. It is research evidence, not the current runtime,
> telemetry, or benchmark contract. See the [series notice](README.md) and current documentation.


- **QwenVoice/Vocello:** `05bd2b6d24b3f43351f3b388622a72d8f0d6ecce`
- **Recorded upstream import baseline:** `fcbd04daa1bfebe881932f630af2ba6ce9af3274` (`v0.1.2`)
- **Upstream comparison head:** `d302a5c6080d2bb97bae38c7418f82abb76013b6`
- **Review date:** 2026-07-10


## Executive finding

The fork's strongest performance result is not one isolated micro-optimization. It is the combination of:

- **streaming retention that releases old codec tensors;**
- **reused sampler scratch and incremental repetition state;**
- **fused Code Predictor RoPE and cached per-frame constants;**
- **mode/device-aware prewarm and chunk sizing;**
- **overlapped non-final decoder materialization;**
- **bounded, capability-aware model loading;**
- **the overlap-and-discard decoder algorithm, which permits aggressive chunking without accumulating boundary drift.**

The dominant memory win comes from the streaming architecture, not talker-KV windowing.

## Active source-confirmed optimizations

### 1. Flat streaming retention

The local loop separates `generatedCodes` for full-result mode from `pendingStreamCodes` for streaming. Pending codes are emitted and cleared, whereas the reviewed upstream loop retains all generated code arrays. See [`third_party_patches/mlx-audio-swift/Sources/MLXAudioTTS/Models/Qwen3TTS/Qwen3TTS.swift`](https://github.com/PowerBeef/Vocello/blob/05bd2b6d24b3f43351f3b388622a72d8f0d6ecce/third_party_patches/mlx-audio-swift/Sources/MLXAudioTTS/Models/Qwen3TTS/Qwen3TTS.swift) versus [`Sources/MLXAudioTTS/Models/Qwen3TTS/Qwen3TTS.swift`](https://github.com/Blaizzy/mlx-audio-swift/blob/d302a5c6080d2bb97bae38c7418f82abb76013b6/Sources/MLXAudioTTS/Models/Qwen3TTS/Qwen3TTS.swift).

The committed benchmark record reports:

- old nonstreaming paths around **7–8 GB** physical footprint on the reference 8 GB Mac;
- streaming paths around **2.4–3.8 GB** depending on mode/model;
- streaming Speed RTF around **0.95–1.04** in the referenced baseline.

Those are machine/configuration-specific observations, not universal guarantees. Source structure supports the direction of the result.

### 2. Sampler hot-path allocation reduction

The local sampler reuses:

- negative-infinity rows;
- arange and zero arrays;
- EOS indices;
- suppression pairs;
- incremental repetition-token IDs;
- a separately sized Code Predictor scratch object.

Upstream's reviewed sampler constructs many of those values per call and rebuilds uniqueness through `Array(Set(tokens))`. See [`third_party_patches/mlx-audio-swift/Sources/MLXAudioTTS/Models/Qwen3TTS/Qwen3TTS.swift`](https://github.com/PowerBeef/Vocello/blob/05bd2b6d24b3f43351f3b388622a72d8f0d6ecce/third_party_patches/mlx-audio-swift/Sources/MLXAudioTTS/Models/Qwen3TTS/Qwen3TTS.swift) and [`Sources/MLXAudioTTS/Models/Qwen3TTS/Qwen3TTS.swift`](https://github.com/Blaizzy/mlx-audio-swift/blob/d302a5c6080d2bb97bae38c7418f82abb76013b6/Sources/MLXAudioTTS/Models/Qwen3TTS/Qwen3TTS.swift).

### 3. Fused Code Predictor RoPE

The local Code Predictor passes contiguous cache offsets to `MLXFast.RoPE`. Upstream constructs rotary tables and applies manual rotate-half math. Because the Code Predictor runs for the remaining codebooks on every generated frame, even small graph-launch savings multiply. See [`third_party_patches/mlx-audio-swift/Sources/MLXAudioTTS/Models/Qwen3TTS/Qwen3TTSCodePredictor.swift`](https://github.com/PowerBeef/Vocello/blob/05bd2b6d24b3f43351f3b388622a72d8f0d6ecce/third_party_patches/mlx-audio-swift/Sources/MLXAudioTTS/Models/Qwen3TTS/Qwen3TTSCodePredictor.swift) and [`Sources/MLXAudioTTS/Models/Qwen3TTS/Qwen3TTSCodePredictor.swift`](https://github.com/Blaizzy/mlx-audio-swift/blob/d302a5c6080d2bb97bae38c7418f82abb76013b6/Sources/MLXAudioTTS/Models/Qwen3TTS/Qwen3TTSCodePredictor.swift).

### 4. Per-generation Code Predictor constants

`CodePredictorStepConstants` memoizes the causal mask for repeated pass shapes. The Code Predictor cache is trimmed back to zero each audio frame, so recomputing an identical mask is unnecessary. This is local-only in the reviewed heads.

### 5. Compiled SwiGLU: active but shared

Both local and current upstream implementations compile the elementwise SwiGLU interior with `compile(shapeless:)`. It is part of current performance, but **not a fork-only differentiator**.

### 6. Decoder chunk-size invariance

Local `DecoderBlockUpsample.step` uses one trailing input frame as context, recomputes a composed convolution result, and discards the repeated output prefix. Upstream accumulates an output overflow tail and adds it to the next chunk. The local method avoids repeated floating-point overlap additions and keeps output stable across partition choices. See [`third_party_patches/mlx-audio-swift/Sources/MLXAudioTTS/Models/Qwen3TTS/Qwen3TTSSpeechTokenizer.swift`](https://github.com/PowerBeef/Vocello/blob/05bd2b6d24b3f43351f3b388622a72d8f0d6ecce/third_party_patches/mlx-audio-swift/Sources/MLXAudioTTS/Models/Qwen3TTS/Qwen3TTSSpeechTokenizer.swift) versus [`Sources/MLXAudioTTS/Models/Qwen3TTS/Qwen3TTSSpeechTokenizer.swift`](https://github.com/Blaizzy/mlx-audio-swift/blob/d302a5c6080d2bb97bae38c7418f82abb76013b6/Sources/MLXAudioTTS/Models/Qwen3TTS/Qwen3TTSSpeechTokenizer.swift).

This is primarily a **numerical correctness optimization**. Its performance value is indirect: it allows smaller early chunks and larger later chunks without accepting partition-dependent drift.

### 7. Async non-final chunk materialization and synchronous final barrier

The local generation loop can `asyncEval` non-final decoder chunks to overlap audio materialization with later token work. The trailing chunk is deliberately evaluated synchronously before returning so preview/final-file handoff cannot overtake the last queued audio.

### 8. Mode-aware chunk growth

First chunk size is driven by `streamingInterval`. Later Design/Clone chunks grow by a multiplier, while Custom Voice uses its resolved profile. This preserves low time-to-first-audio while reducing repeated decoder invocation overhead.

### 9. Prepared-component caches

Tokenizer and speech-tokenizer components are cached by canonical prepared-directory identity and capability profile. iOS limits are smaller than macOS limits. Decoder-bucket warm state and conditioning prefixes have separate LRUs.

### 10. Capability-aware loading

The loader can omit the speech encoder and/or speaker encoder, skip duplicate preparation, and skip parameter eval after an externally trusted prepared checkpoint. Temporary dictionaries are released between phases, and parameter materialization is batched.

### 11. Prewarm policy

Custom Voice prewarm can be full, skip decoder buckets, or skip stream-step warming. Core selects lighter policies for short prompts and constrained device tiers.

## Correct sampling order

Local sampling applies temperature before top-p/min-p truncation. This changes the selected probability support whenever temperature differs from one and probability filtering is enabled. It is neutral at the shipped `topP=1` and `minP=0` defaults apart from possible floating-point rounding, but it is required for Balanced/Consistent variations.

## Memory controls that are present but not current wins

### Rotating talker KV

The code supports `RotatingKVCache`, but the repository's current policy leaves it off by default. With `maxNewTokens=2048`, a 2048 generated-token window cannot rotate before the output cap. Repository experiments also found talker KV far smaller than earlier estimates.

### Quantized talker KV

Quantized KV is opt-in. It can alter numerical behavior and should remain behind explicit quality evidence.

## Rejected or reverted experiments

1. **Whole quantized per-frame graph compilation:** benchmark record reports roughly a 5% warm RTF regression; not active.
2. **Eager `talkerSourceWeights` release reordering:** measured no meaningful benefit and was reverted.
3. **Default-on rotating KV/user toggle:** rationale collapsed under the current cap and measured memory profile; only environment plumbing remains.
4. **Deferred stream-step eval as a speed win:** synchronization cost moved to later operations rather than disappearing.
5. **Sampling-side suppression of long pauses:** rejected because measured pauses mostly matched punctuation/prosody; audioQC was recalibrated outside the model instead.

## Required benchmark discipline

Every claimed optimization should carry:

- exact commit and dependency lock;
- model ID/revision/quantization;
- device and OS;
- Release optimization state;
- cold/warm distinction;
- input text and seed;
- streaming/full-result mode;
- RTF, time-to-first-audio, duration, physical footprint, GPU peak, trims;
- audioQC plus listening result;
- token trace or waveform comparison when correctness is expected to be invariant.

The durable benchmark source is [`benchmarks/OPTIMIZATION.md`](https://github.com/PowerBeef/Vocello/blob/05bd2b6d24b3f43351f3b388622a72d8f0d6ecce/benchmarks/OPTIMIZATION.md); historical rows belong in `benchmarks/HISTORY.md`.
