---
status: active
owner: backend-mlx
summary: The Mimi-style neural audio codec as owned in the Qwen3 speech tokenizer — architecture, streaming overlap-and-discard semantics, and Vocello deltas from canonical Mimi.
sourceOfTruth:
  - Packages/VocelloQwen3Core/Sources/MLXAudioCodecs
---
# Mimi Codec Guide for Vocello

> **Living document.** A project-specific reference for the Mimi-style neural audio codec used by Vocello's Qwen3-TTS backend. It focuses on the Qwen3-TTS speech tokenizer owned in `Packages/VocelloQwen3Core/`, with Kyutai's canonical Mimi as architectural background. When this doc disagrees with the code, the code wins — fix this file.
>
> Last reviewed: 2026-07-14. Upstream snapshot: `mlx-audio-swift` `v0.1.2` / `fcbd04d`, with Vocello-specific deltas.

---

## 1. Executive summary

Vocello's text-to-speech pipeline ends with a **neural audio codec** that turns discrete tokens into 24 kHz mono PCM. The codec is derived from Kyutai's **Mimi** architecture but is specialized for Qwen3-TTS:

| Property | Canonical Mimi (Kyutai) | Qwen3-TTS tokenizer (Vocello) |
| --- | --- | --- |
| Sample rate | 24 kHz | 24 kHz |
| Frame rate | 12.5 Hz | 12.5 Hz |
| Frame duration | 80 ms | 80 ms |
| Quantizers | 8 | 16 |
| Codebook size | 2,048 | 2,048 (decoder) |
| Semantic codebooks | 1 | 1 |
| Bitrate | ~1.1 kbps | ~2.1 kbps |
| Decoder transformer | No | Yes (8-layer sliding-window) |
| Decoder SEANet | Yes | Yes, with SnakeBeta + ConvNeXt |

The decoder is the quality-critical path. It receives 16 integer codes per frame from the code predictor, looks up quantized vectors, runs a small transformer, upsamples, and emits waveform samples through a SEANet-style upsampling stack. Because Vocello streams audio as soon as tokens are available, the decoder must be **causal** and **chunk-size invariant**: the same audio must be produced whether tokens are decoded in one 300-token batch or in 12-token dribbles.

**Source-of-truth hierarchy**

1. `Packages/VocelloQwen3Core/Sources/MLXAudioTTS/Models/Qwen3TTS/Qwen3TTSSpeechTokenizer.swift`
2. `Packages/VocelloQwen3Core/Sources/MLXAudioTTS/Models/Qwen3TTS/Qwen3TTSConfig.swift`
3. `Packages/VocelloQwen3Core/Sources/MLXAudioCodecs/Mimi/Seanet.swift`
4. `Packages/VocelloQwen3Core/Sources/MLXAudioCodecs/Mimi/Quantization.swift`
5. `Packages/VocelloQwen3Core/Sources/MLXAudioCodecs/Mimi/Transformer.swift`
6. This document and `docs/reference/qwen3-tts-guide.md` (for talker/code-predictor context).

---

## 2. Mimi background

### 2.1 SEANet autoencoder

Mimi is built around **SEANet** (Synthesis-Enabled Audio Network), a convolutional encoder/decoder pair:

- **Encoder** — a stack of strided 1-D convolutions that compresses raw waveform into a compact latent sequence.
- **Decoder** — a mirror stack of transposed convolutions that expands the latent back to audio.

SEANet uses residual blocks with dilated convolutions, skip connections, and ELU activations. In Mimi the design is **causal** so it can be used in streaming mode: every output sample depends only on past and present inputs.

### 2.2 Residual Vector Quantization (RVQ)

The encoder output is a continuous latent vector per frame. RVQ discretizes it into a stack of codebook indices:

1. Find the nearest entry in codebook 0, subtract it from the latent (the *residual*).
2. Find the nearest entry in codebook 1 for the residual, subtract it.
3. Repeat for `N` codebooks.

The final reconstruction is the **sum** of all codebook vectors. More codebooks → finer detail → higher bitrate and quality.

### 2.3 Split RVQ

Canonical Mimi splits the quantizers into two groups:

- **Semantic codebook(s)** — trained with a distillation objective from a self-supervised speech representation (e.g., WavLM). These capture phonetic/linguistic content.
- **Acoustic codebooks** — capture everything else: prosody, speaker identity, environmental cues, and reconstruction residuals.

Splitting lets the model use the semantic tokens for tasks like voice conversion or ASR while the acoustic tokens preserve fidelity.

### 2.4 Why this matters for Vocello

Qwen3-TTS reuses the Mimi *idea* (SEANet + split RVQ) but changes almost every numeric detail: more quantizers, a decoder transformer, different activations, and a different streaming strategy. Do not assume canonical Mimi numbers apply to Vocello's tokenizer.

---

## 3. Qwen3-TTS speech tokenizer architecture

The full pipeline has two sides:

```text
Audio  →  Encoder  →  continuous latent  →  Split RVQ  →  16 codes / frame
                                                         ↑
Text → Talker → Code Predictor ──────────────────────────┘
                                                         ↓
                                            16 codes / frame  →  Decoder  →  24 kHz PCM
```

Vocello normally only runs the **decoder** at inference (the talker and code predictor produce the codes). The encoder is loaded only when voice cloning or audio-to-code features are active.

### 3.1 Encoder path

`Qwen3TTSSpeechTokenizerEncoder` in `Qwen3TTSSpeechTokenizer.swift`:

```text
Audio [B, 1, T]
    ↓
SeanetEncoder          (SEANet downsampling convolutions, ratios [8, 6, 5, 4])
    ↓
ProjectedTransformer   (8-layer transformer with RoPE, sliding-window context)
    ↓
ConvDownsample1d       (stride computed from encoderFrameRate / frameRate)
    ↓
SplitResidualVectorQuantizer  (semantic + acoustic RVQ)
    ↓
Codes [B, Q, T_frame]
```

The encoder is configured for **32 quantizers** during training but Vocello validates that only **16** are emitted at inference (`encoderValidNumQuantizers`). This is a source of frequent confusion: the checkpoint has 32 codebook layers, the contract says 16, and the decoder expects 16.

### 3.2 Decoder path

`Qwen3TTSSpeechTokenizerDecoder` is the heart of the synthesis side:

```text
Codes [B, 16, T_frame]
    ↓
SplitResidualVectorQuantizer.decode  →  [B, codebookDim, T]
    ↓
CausalConv1d (pre_conv)              →  [B, latentDim, T]
    ↓
Transpose 0↔2                        →  [B, T, latentDim]
    ↓
DecoderTransformer (8 layers, sliding-window RoPE)
    ↓
Transpose 0↔2                        →  [B, latentDim, T]
    ↓
UpsampleLayers (ratios [2, 2])
    ↓
DecoderInitialConv + DecoderBlocks (ratios [8, 5, 4, 3])
    ↓
DecoderOutputSnake + DecoderOutputConv
    ↓
Clip to [-1, 1]  →  24 kHz PCM [B, 1, T_sample]
```

The decoder has two distinct upsampling stages:

1. **Transformer-side upsampling** — `UpsampleLayer` blocks that use `ConvTransposed1d` + `ConvNeXtBlock` to expand from the transformer hidden size to the SEANet latent size.
2. **SEANet-style upsampling** — `DecoderBlock` modules that use `DecoderBlockUpsample` (transposed conv) + residual units with `SnakeBeta` activations.

### 3.3 Key numeric profile

| Parameter | Value | Notes |
| --- | --- | --- |
| Sample rate | 24,000 Hz | Input and output. |
| Frame rate | 12.5 Hz | 80 ms per token frame. |
| `decodeUpsampleRate` | 1,920 | 24,000 / 1,920 = 12.5. |
| `encodeDownsampleRate` | 1,920 | Same stride, used for encoder validation. |
| Decoder quantizers | 16 | `numQuantizers`. |
| Semantic quantizers | 1 | `numSemanticQuantizers`; first codebook. |
| Codebook size | 2,048 | Per quantizer. |
| Semantic codebook size | 4,096 | Used by the talker, not the decoder lookup table. |
| Codebook dim | 512 | Decoder; encoder uses 256. |
| Latent dim | 1,024 | Transformer input/output width. |
| Decoder dim | 1,536 | SEANet decoder channel width. |
| Transformer hidden size | 512 | Inside the decoder transformer. |
| Transformer heads | 16 | Head dim 64. |
| Transformer layers | 8 | With layer scale. |
| Sliding window | 72 | Decoder transformer local attention. |
| Upsample ratios (transformer) | [2, 2] | `UpsampleLayer`. |
| Upsample rates (SEANet) | [8, 5, 4, 3] | `DecoderBlock`; product = 480. |
| Total decoder upsample | 1,920 | 2 × 2 × 8 × 5 × 4 × 3 = 1,920. |

---

## 4. Vendored Swift implementation

The implementation lives under `Packages/VocelloQwen3Core/`. Vocello's owned runtime retains only the codec surface needed by Qwen3-TTS and adds product-specific quality and reliability behavior, most notably around streaming state.

### 4.1 File map

| File | Responsibility |
| --- | --- |
| `Sources/MLXAudioTTS/Models/Qwen3TTS/Qwen3TTSSpeechTokenizer.swift` | Top-level tokenizer, encoder, decoder, weight sanitization. |
| `Sources/MLXAudioTTS/Models/Qwen3TTS/Qwen3TTSConfig.swift` | All config structs and validation. |
| `Sources/MLXAudioCodecs/Mimi/Seanet.swift` | Generic SEANet encoder/decoder building blocks. |
| `Sources/MLXAudioCodecs/Mimi/Quantization.swift` | `EuclideanCodebook`, `ResidualVectorQuantizer`, `SplitResidualVectorQuantizer`. |
| `Sources/MLXAudioCodecs/Mimi/Transformer.swift` | `ProjectedTransformer`, causal attention with sliding-window KV cache. |
| `Sources/MLXAudioCodecs/Mimi/Conv.swift` | `Conv1d`, `ConvTranspose1d`, `StreamableConv1d`, `StreamableConvTranspose1d`. |

### 4.2 Quantization (`Quantization.swift`)

`EuclideanCodebook` stores learned codebook entries. The Swift version keeps `embedding_sum` and `cluster_usage` so it can derive the embedding from aggregated statistics (matching the original training setup) and calls `updateInPlace()` after weight loading.

`SplitResidualVectorQuantizer` is the one actually used by both encoder and decoder. It contains:

- `rvq_first` — one quantizer for the semantic codebook.
- `rvq_rest` — the remaining `nq - 1` quantizers for acoustic detail.

In the decoder, `decode(_:)` sums the semantic and acoustic quantized vectors. In the encoder, `encode(_:)` concatenates the indices along the quantizer axis.

### 4.3 Encoder building blocks

The encoder uses the generic SEANet stack from `Seanet.swift`:

- `SeanetEncoder` — causal strided convolutions with residual blocks.
- `SeanetResnetBlock` — dilated residual convolutions.
- `EncoderLayer` — downsampling layer with optional residual repetition.

After SEANet, `ProjectedTransformer` (from `Transformer.swift`) applies an 8-layer causal transformer with **sliding-window attention**: the KV cache is trimmed to `context` past tokens, so memory stays bounded even for long utterances. The `convLayout` flag toggles between `[B, C, T]` and `[B, T, C]` layouts automatically.

`ConvDownsample1d` then reduces the transformer output to the target frame rate before quantization.

### 4.4 Decoder building blocks

#### CausalConv1d

`CausalConv1d` is the workhorse of the decoder. It wraps `MLXNN.Conv1d` and supports both regular and depthwise grouped convolutions.

Key property: `streamBuffer` holds the last `paddingAmount` input samples. On each `step(_:)`, the buffer is prepended to the new input, the convolution runs, and the trailing `paddingAmount` samples are stashed again. This makes the layer **chunk-size invariant** for stride = 1: the output of many small `step()` calls is bit-identical (modulo float precision) to the output of one large `callAsFunction()` call.

#### SnakeBeta activation

`SnakeBeta` implements the learned periodic activation:

```text
x + (1 / (β + ε)) * sin²(α * x)
```

where `α` and `β` are per-channel parameters initialized to zero (so initially `exp(α) = exp(β) = 1`). It appears both in the SEANet residual units and as the final output nonlinearity.

#### ConvNeXtBlock

`ConvNeXtBlock` uses a depthwise causal convolution (`groups = dim`), layer norm, and two pointwise linear layers with GELU. It is used inside `UpsampleLayer` after the transposed convolution.

#### DecoderTransformer

The decoder transformer (`pre_transformer`) is small but critical for temporal consistency. It uses:

- RMSNorm (`DecoderRMSNorm`).
- Multi-head attention with RoPE (`DecoderRotaryEmbedding`).
- GQA (grouped query attention) when `numKeyValueHeads < numAttentionHeads`.
- `KVCacheSimple` for incremental decoding.
- Sliding-window causal mask when `seqLen > 1`.

Because it sits *inside* the decoder, not before it, the transformer sees the already-quantized latent and can smooth discontinuities across frames.

#### DecoderBlockUpsample

`DecoderBlockUpsample` is the most carefully patched piece of the decoder. It wraps `ConvTransposed1d` and historically had an **output-side overlap-and-add** accumulator (`overflow`). The May 2026 Vocello patch replaced that with an **input-side overlap-and-discard** buffer (`inputContext`).

Why: output-side accumulation re-parenthesizes floating-point sums across chunk boundaries. With short streaming chunks (~12 tokens) there are ~25× more boundaries than with the canonical 300-token batch. The accumulated LSB drift amplified through SnakeBeta and downstream blocks to >1 dB peak deviation, which was audibly detectable as a "buzzy" or "popping" boundary artifact.

The new pattern keeps one trailing input sample as left context. The next `step()` composes `[inputContext, newInput]`, runs `callAsFunction(composed)`, and discards the first `inputContext.count * upsampleRate` output samples (which are recomputations of the previous emission). The remaining samples match batch-mode parenthesization regardless of chunk size.

#### Decoder top-level flow

`Qwen3TTSSpeechTokenizerDecoder.callAsFunction(_:)` is the non-streaming batch path.

`streamingStep(_:)` is the incremental path. It:

1. Decodes the new code chunk to a continuous latent.
2. Runs `preConv.step(_:)`.
3. Runs the transformer with `cache: transformerCache`.
4. Runs each `UpsampleLayer.step(_:)`.
5. Runs each decoder block's `step(_:)` path.
6. Clips to `[-1, 1]`.

`chunkedDecode(_:chunkSize:leftContextSize:)` provides a middle ground: it calls the full batch path on overlapping chunks and trims the left context from each output chunk, then concatenates. Default `chunkSize = 300`, `leftContextSize = 25`.

### 4.5 Weight sanitization

`Qwen3TTSSpeechTokenizer.sanitize(weights:)` is a large key-remapping function. It handles:

- Stripping prefixes like `speech_tokenizer.`, `encoder_model.`, `decoder_model.`.
- Mapping PyTorch conv weight layouts to MLX conventions.
- Splitting fused QKV weights into `in_proj` for the encoder transformer.
- Reconstructing `EuclideanCodebook` state from `cluster_usage` and `embedding_sum`.
- Mapping the encoder's nested layer/quantizer naming onto the Swift module tree.

If you load a fresh Qwen3-TTS checkpoint and see "missing key" errors, this is the first file to inspect.

---

## 5. Streaming invariants and quality

Vocello's audio output must be glitch-free when tokens arrive in small groups. The decoder enforces several invariants:

### 5.1 Causal-only dependencies

Every layer is causal: no output sample depends on future input. This includes:

- `CausalConv1d` with left padding only.
- `DecoderBlockUpsample` with input-side context.
- `DecoderTransformer` with causal mask and KV cache.
- `ConvNeXtBlock` with depthwise causal convolution.

### 5.2 State reset contract

`Qwen3TTSSpeechTokenizerDecoder.resetStreamingState()` must be called between utterances. It clears:

- `transformerCache`.
- `preConv.streamBuffer`.
- All `UpsampleLayer` states.
- `DecoderInitialConv`, `DecoderBlock`, and `DecoderOutputConv` states.

Failure to reset leaks context from the previous utterance into the next one, causing clicks, pitch glitches, or rhythmic discontinuities at the start of a new generation.

### 5.3 Chunk-size invariance

The decoder is designed so that `streamingStep` with chunk size `C` produces the same audio as `callAsFunction` over the full sequence, after accounting for latency. The two places that make this possible are:

1. `CausalConv1d.streamBuffer` — input-side context for strided/dilated convolutions.
2. `DecoderBlockUpsample.inputContext` — input-side context for transposed upsampling.

**Do not reintroduce output-side accumulation** in these layers. It was tried and bench-rejected because of float-drift artifacts on short chunks.

### 5.4 Latency vs. throughput trade-off

The decoder has three operating modes:

| Mode | Call site | Chunk size | Use case |
| --- | --- | --- | --- |
| Full batch | `callAsFunction(_:)` | Full utterance | Offline synthesis, quality baseline. |
| Chunked | `chunkedDecode(_:)` | 300 tokens (+25 left context) | Non-streaming but memory-bounded synthesis. |
| Generic streaming helper | `streamingStep(_:)` via `streamingDecode` | Variable (helper default 100) | Low-level API and diagnostics. |
| Vocello production streaming | Qwen3 runtime schedule | Derived from `appStreamingInterval` and mode-specific later-chunk policy | Bounded playback chunks with a final barrier. |

Smaller chunks increase boundary count and can amplify any residual drift bug. Larger chunks increase peak memory and delay the first audio sample. At 12.5 frames per second, 100 codec frames represent approximately **8 seconds**, not 0.8 seconds. The `streamingDecode` default is a generic helper default; Vocello production generation derives its first and later decode batches from `appStreamingInterval` and the owned runtime's mode-specific scheduling policy.

---

## 6. Performance optimization

### 6.1 Memory layout

MLX uses **unified memory** on Apple Silicon. Decoder weights and KV caches live in the same pool as app allocations and OS pressure. On an 8 GB machine:

- Keep the decoder transformer KV cache small: it is bounded by the sliding window (`slidingWindow = 72`), not by utterance length.
- Avoid materializing long intermediate arrays. Use `eval()` only on the audio chunk that is about to be handed to the audio player.
- The decoder weights are not quantized in current Vocello builds; the 1.7 B talker and code predictor are. If memory is tight, the decoder is a smaller but non-zero contributor.

### 6.2 Chunk size

The generic `streamingDecode(_:chunkTokens:)` helper defaults to 100 tokens. Production Vocello
streaming does not treat that value as its schedule. Trade-offs:

- **Smaller chunks** — lower latency, but more `eval()` boundaries and more opportunity for streaming-state overhead.
- **Larger chunks** — better amortized kernel launch cost, but higher peak memory and longer time-to-first-audio.

The sweet spot depends on the target device. For 8 GB Macs and iPhones, 100 is conservative. For 16 GB+ Macs, 150–300 may improve throughput without audible latency.

### 6.3 Causal conv efficiency

`CausalConv1d.step(_:)` is cheaper than `callAsFunction(_:)` for very short inputs because it avoids padding the full sequence. However, each `step()` still builds an MLX graph and must be evaluated. If you are decoding many tokens offline, prefer `chunkedDecode` or `callAsFunction`.

### 6.4 Avoid redundant quantizer decode

`SplitResidualVectorQuantizer.decode(_:)` sums codebook vectors. If you are doing voice cloning or prompt encoding, make sure you are not decoding codes that will only be re-encoded. In the synthesis hot path this is unavoidable; in preprocessing it may not be.

### 6.5 `eval()` placement

`Qwen3TTSSpeechTokenizer.streamingDecode` calls `eval(wavChunk)` after each chunk to force materialization before the chunk is returned. This is intentional: it keeps the audio player from blocking on a large accumulated graph and provides predictable memory growth.

If you move `eval()` around for performance, measure both wall time and peak physical footprint. Faster graph construction is not faster if it increases peak memory enough to trigger Jetsam on iOS.

### 6.6 SEANet vs. transformer bottlenecks

For short chunks, the decoder transformer and attention are the dominant cost because fixed overhead dominates. For long chunks, the SEANet upsampling stack dominates because it is O(audio samples). Profile before optimizing.

---

## 7. Troubleshooting and known issues

### 7.1 Boundary clicks or drift on streaming

**Symptoms:** Audible pops, clicks, or a "wobble" every `chunkTokens` frames in streaming mode.

**Likely causes:**

1. Output-side overlap-and-add in a transposed conv layer. Verify `DecoderBlockUpsample` uses `inputContext` (input-side) not `overflow` (output-side).
2. Missing `resetStreamingState()` between utterances.
3. `CausalConv1d.streamBuffer` not being reset, causing old audio to leak into new audio.

**Fix:** Check the streaming-state reset path and confirm the overlap-and-discard pattern in the diff.

### 7.2 Muffled or robotic output

**Symptoms:** Speech is intelligible but lacks high frequencies or sounds "telephonic."

**Likely causes:**

1. Only the semantic codebook is being used (`nQSemantic` or `validNumQuantizers` too low).
2. Acoustic quantizers are dropped during encode/decode.
3. Decoder is running with fewer than 16 quantizers.

**Fix:** Verify `encoderValidNumQuantizers = 16`, `decoderConfig.numQuantizers = 16`, and the code predictor emits codes for all 16 codebooks.

### 7.3 Length mismatch between codes and audio

**Symptoms:** `audioLengths` does not match the actual waveform length, or concatenated chunks drift out of sync with token timestamps.

**Likely causes:**

1. `decodeUpsampleRate` mismatch. Expected 1,920 for 12.5 fps at 24 kHz.
2. Chunk boundaries not aligned with the total upsample product.
3. `chunkedDecode` left-context trimming is off by one frame.

**Fix:** Run `qwen3TTS12HzValidationFailure(includeEncoder:)` and verify `decodeUpsampleRate` and `encodeDownsampleRate`.

### 7.4 Speaker encoder vs. tokenizer encoder confusion

**Symptoms:** "Encoder not loaded" errors during cloning, or cloning quality is poor.

**Likely causes:** The Qwen3-TTS checkpoint contains *two* encoders: the **speaker encoder** (mel → speaker embedding) and the **speech tokenizer encoder** (audio → codes). `includeEncoder` controls only the speech tokenizer encoder. Speaker encoder weights are handled separately by `Qwen3TTSSpeakerEncoder`.

**Fix:** Check which encoder is being requested. Do not conflate `encoder_model` keys with speaker encoder keys in `sanitize(weights:)`.

### 7.5 Weight loading errors after a checkpoint update

**Symptoms:** `Missing weight for key ...` or shape mismatches.

**Likely causes:**

1. New checkpoint renamed `encoder_transformer` paths.
2. Quantizer naming changed from `semantic_residual_vector_quantizer` / `acoustic_residual_vector_quantizer` to `rvq_first` / `rvq_rest`.
3. Conv weight layout differs from the PyTorch → MLX heuristic.

**Fix:** Inspect `sanitize(weights:)` and add the new key mapping. The function already has branches for multiple naming conventions; add another branch if needed.

---

## 8. Appendix

### 8.1 Decoder config defaults

`Qwen3TTSTokenizerDecoderConfig` defaults (Vocello's contract enforces these):

| Key | Default | Description |
| --- | --- | --- |
| `latentDim` | 1,024 | Transformer I/O width. |
| `codebookDim` | 512 | Width of each codebook vector. |
| `codebookSize` | 2,048 | Entries per quantizer. |
| `decoderDim` | 1,536 | SEANet decoder channel width. |
| `hiddenSize` | 512 | Transformer hidden size. |
| `intermediateSize` | 1,024 | Transformer FFN hidden size. |
| `numHiddenLayers` | 8 | Transformer layers. |
| `numAttentionHeads` | 16 | Attention heads. |
| `numKeyValueHeads` | 16 | GQA heads (16 = no grouping in decoder). |
| `headDim` | 64 | Per-head dimension. |
| `numQuantizers` | 16 | Total decoder quantizers. |
| `numSemanticQuantizers` | 1 | First codebook is semantic. |
| `semanticCodebookSize` | 4,096 | Talker-side semantic vocabulary size. |
| `slidingWindow` | 72 | Local attention context. |
| `upsampleRates` | [8, 5, 4, 3] | SEANet upsampling per block. |
| `upsamplingRatios` | [2, 2] | Transformer-side upsampling. |
| `layerScaleInitialScale` | 0.01 | Initial layer-scale multiplier. |
| `rmsNormEps` | 1e-5 | RMSNorm epsilon. |
| `ropeTheta` | 10,000 | RoPE base. |

### 8.2 Encoder config defaults

`Qwen3TTSTokenizerEncoderConfig` defaults:

| Key | Default | Description |
| --- | --- | --- |
| `frameRate` | 12.5 | Target code frame rate. |
| `audioChannels` | 1 | Mono input. |
| `codebookDim` | 256 | Encoder codebook vector width. |
| `codebookSize` | 2,048 | Entries per quantizer. |
| `numQuantizers` | 32 | Training config; inference uses 16. |
| `numSemanticQuantizers` | 1 | Semantic codebook count. |
| `hiddenSize` | 512 | SEANet channel width. |
| `numFilters` | 64 | SEANet base filters. |
| `numHiddenLayers` | 8 | Encoder transformer layers. |
| `numAttentionHeads` | 8 | Encoder transformer heads. |
| `numKeyValueHeads` | 8 | Encoder GQA heads. |
| `headDim` | 64 | Per-head dimension. |
| `intermediateSize` | 2,048 | Encoder transformer FFN size. |
| `slidingWindow` | 250 | Encoder transformer local context. |
| `upsamplingRatios` | [8, 6, 5, 4] | SEANet encoder downsampling ratios. |
| `useCausalConv` | true | Causal convolutions. |
| `useConvShortcut` | false | No conv shortcuts. |

### 8.3 Glossary

| Term | Meaning |
| --- | --- |
| **RVQ** | Residual Vector Quantization — stacking codebooks to approximate a latent. |
| **Split RVQ** | Separating semantic and acoustic codebooks. |
| **SEANet** | Synthesis-Enabled Audio Network — convolutional encoder/decoder. |
| **SnakeBeta** | Learned sinusoidal activation used in the decoder. |
| **ConvNeXt** | Depthwise-separable residual block used after upsampling. |
| **RoPE** | Rotary Position Embedding. |
| **GQA** | Grouped Query Attention. |
| **KV cache** | Cached key/value tensors for incremental transformer decoding. |
| **Overlap-and-discard** | Streaming pattern where recomputed output head is dropped. |
| **Chunk-size invariance** | Output is independent of how input is partitioned. |

### 8.4 Cross-references

- [`mlx-guide.md`](mlx-guide.md) — MLX runtime, lazy evaluation, quantization, memory.
- [`qwen3-tts-guide.md`](qwen3-tts-guide.md) — Talker, code predictor, generation modes, token IDs.
- [`swift-performance-guide.md`](swift-performance-guide.md) — Swift 6 performance, actors, concurrency.

### 8.5 External references

- Kyutai Mimi paper: *"Mimi: A Streaming Transformer-based Neural Audio Codec"* (arXiv, 2024).
- `mlx-audio-swift` upstream: <https://github.com/Blaizzy/mlx-audio-swift>.
- Qwen3-TTS technical report and checkpoints: <https://huggingface.co/Qwen> and <https://huggingface.co/mlx-community>.
