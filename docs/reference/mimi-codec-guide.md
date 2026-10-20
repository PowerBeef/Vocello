---
status: active
owner: backend-mlx
reviewed: 2026-10-20
summary: The Qwen3-TTS 12 Hz speech tokenizer guide (formerly the Mimi codec guide; the filename is kept) — the Mimi-derived encoder, split RVQ and Qwen decoder as owned in Vocello, streaming and partition semantics, where Vocello's decode and clone-reference encode diverge from the reference (A-02, A-03, A-04, G-03), and the shipped fp32 codec.
sourceOfTruth:
  - Packages/VocelloQwen3Core/Sources/MLXAudioTTS/Models/Qwen3TTS/Qwen3TTSSpeechTokenizer.swift
  - Packages/VocelloQwen3Core/Sources/MLXAudioTTS/Models/Qwen3TTS/Qwen3TTSConfig.swift
  - Packages/VocelloQwen3Core/Sources/MLXAudioTTS/Models/Qwen3TTS/Qwen3TTS.swift
  - Packages/VocelloQwen3Core/Sources/MLXAudioCodecs/Mimi/Transformer.swift
  - Packages/VocelloQwen3Core/Sources/MLXAudioCodecs/Mimi/Quantization.swift
  - Packages/VocelloQwen3Core/Sources/MLXAudioCodecs/Mimi/Seanet.swift
  - docs/audits/2026-10-17-qwen3-tts-model-research.md
  - docs/audits/2026-10-16-engine-runtime-audit.md
---
# Qwen3-TTS 12 Hz Speech Tokenizer Guide

> This file used to be the "Mimi codec guide" and keeps its filename. It describes the Qwen3-TTS
> 12 Hz speech tokenizer as owned in `Packages/VocelloQwen3Core/`. When it disagrees with the code,
> the code wins: fix this file.

**Conventions.** Vocello paths are relative to `Packages/VocelloQwen3Core/Sources/`: `ST` is
`MLXAudioTTS/Models/Qwen3TTS/Qwen3TTSSpeechTokenizer.swift`, `Q` is
`MLXAudioTTS/Models/Qwen3TTS/Qwen3TTS.swift`. Upstream line numbers (`TV2`, `TC2`, `WM`, `HFM`) are
QwenLM/Qwen3-TTS at `022e286b98` and transformers 4.57.3, keyed as in the
[ER-13 research report](../audits/2026-10-17-qwen3-tts-model-research.md). Finding IDs (A-02, G-03…)
are from the [engine audit](../audits/2026-10-16-engine-runtime-audit.md).

**What this file owns:** the tokenizer's structure, its Swift implementation, decode and streaming
semantics, the clone-reference encoder, and how they differ from the reference. **Owned elsewhere:**
the model family, the talker and code predictor, generation semantics, the failure catalogue and the
parity ledger in [`qwen3-tts-guide.md`](qwen3-tts-guide.md) (the sourced ledger is
[research §8](../audits/2026-10-17-qwen3-tts-model-research.md#8-parity-ledger)); MLX semantics,
quantization and dependency pins in [`mlx-guide.md`](mlx-guide.md); codec bytes, digests and
artifact history in [`model-delivery.md`](model-delivery.md#artifact-provenance); reference
preparation and transcript rules for clones in the
[prompting guide §2.3](qwen3-tts-prompting-guide.md).

---

## 1. Summary

| Property | Value |
| --- | --- |
| Sample rate | 24 kHz in and out |
| Frame rate | 12.5 Hz: 80 ms, 1,920 samples per frame |
| Codes per frame | 16: one semantic codebook, then 15 acoustic ones |
| Codebook size | 2,048 entries (11 bits) |
| Bitrate | about 2.2 kbps (16 × 11 bits × 12.5 Hz), about 175× below 16-bit 24 kHz PCM |
| Encoder | transformers' `MimiModel` without its decoder (research §3) |
| Decoder | Qwen's own: RVQ decode, causal pre-conv, an 8-layer transformer, two ConvNeXt upsamplers, a SEANet-style decoder with SnakeBeta, and a final `clamp(-1, 1)` (TV2 L824-896) |

The lineage is Kyutai's Mimi, introduced in the Moshi paper (arXiv:2410.00037). Only the encoder is
Mimi's own code; the decoder and its numbers are Qwen's, so canonical Mimi figures do not carry over.

In Vocello the talker and code predictor produce the 16 codes per frame and the decoder turns them
into PCM. The encoder runs only to turn a clone reference into codes for in-context learning (ICL).

**Where Vocello differs from the reference** (statuses in the parity ledger):

| ID | What | Status |
| --- | --- | --- |
| A-02 | The encoder's rotary embedding uses the wrong convention (§2.2) | open; ships with G-03's version bump (ER-04) |
| A-03 | The decoder never applies its 72-frame window; its KV cache grows for the whole take (§5) | open (PA-16) |
| D5 / A-04 | Streamed clones decode from a cold decoder; the reference decodes reference plus generated codes (§5) | open, with A-26 (ER-04) |
| — | Encoder attention is full causal, as upstream's is (§2.3) | matches; do not add the 250-frame window |
| — | The codec runs in fp32; Qwen's README setup loads bf16 (§7) | deliberate |

---

## 2. Encoder: clone references

### 2.1 Path

`Qwen3TTSSpeechTokenizerEncoder` (`ST:846-939`):

```text
Audio [B, 1, T] at 24 kHz
    ↓ SeanetEncoder          config ratios [8, 6, 5, 4], applied reversed (strides 4, 5, 6, 8) → 25 Hz
    ↓ ProjectedTransformer   8 layers, hidden 512, RoPE θ 1e4, layer scale 0.01
    ↓ ConvDownsample1d       stride 2 → 12.5 Hz
    ↓ SplitResidualVectorQuantizer   32 configured quantizers
Codes [B, 16, T_frame]       the first 16 are kept (encoder_valid_num_quantizers)
```

The SEANet encoder iterates its ratios reversed (`MLXAudioCodecs/Mimi/Seanet.swift:223`), and the
downsample stride is `25 Hz / 12.5 Hz` (`ST:860-862`). The checkpoint configures 32 quantizers;
Qwen keeps 16 (TV2 L983-984), and Vocello's validation insists on 32 configured and 16 kept
(`Qwen3TTSConfig.swift:496-529`). The first codebook is distilled from WavLM (technical report §2.2,
via research §3).

The encoder loads by default only for Base (clone) checkpoints (`includeEncoder`,
`Q:5632`). The speaker encoder (mel → x-vector) is a separate module, `Qwen3TTSSpeakerEncoder`; see
§9.4.

### 2.2 The rotary-embedding bug (A-02)

The checkpoint stores HF-format q/k weights, permuted for transformers' split-half `rotate_half`
(HFM L542-560, L668). Vocello's encoder transformer applies
`RoPE(traditional: true)`, the adjacent-pair convention
(`MLXAudioCodecs/Mimi/Transformer.swift:129`), and `sanitize(weights:)` only concatenates the
separate q, k and v projections into one `in_proj` (`ST:1372-1385`, `ST:1503-1507`). mlx-audio fixed
the same port with `rope_traditional=False` (`6549fc2`, "silence in VC"); mlx-audio-swift `main` and
Vocello have not (research §1, finding 4). The PowerBeef02 codec file is byte-identical to Qwen's
(§7), so the weights are in HF layout.

Consequence: every transcript-backed clone encodes reference codes that differ from the official
tokenizer's, and persisted clone artifacts hold those codes. How much this changes output is
unmeasured (research open question 7).

**G-03.** Nothing versions the encoder implementation. The clone identity's speaker-feature version
is `qwen-speaker-mel-v1+icl-ref-silence500ms-v2+mlx-swift-0.32.3` (`Q:790-798`): the mel frontend,
the ICL reference preprocessing and the MLX build (F-06, since CONV-21). After a RoPE fix alone, every
saved voice would keep adopting its persisted wrong codes. The fix therefore adds an encoder version
to that identifier, pinned by a golden-codes test, so transcript-backed artifacts rebuild once
(ER-04; [`CLONE_ARTIFACT_FORMAT.md`](../../Packages/VocelloQwen3Core/CLONE_ARTIFACT_FORMAT.md)).

### 2.3 Attention window: leave it full causal

The encoder config declares `sliding_window: 250`. Under transformers 4.57.3 that window is honoured
only by FlashAttention-2; eager and sdpa run full causal attention (HFM L1101-1108), and the official
loader has not selected FlashAttention-2 since QwenLM PR #15 (2026-01-24) (research §1, finding 6).
Vocello's one-pass encode trims the cache to empty before each call (`ST:928`), so the transformer's
`context` trim (`Transformer.swift:158-164`) never bites and every position attends causally to the
whole reference. That matches upstream. Adding the 250-frame window, as an earlier PA-16 step
proposed, would move Vocello away from the reference.

### 2.4 Other encoder facts

- **Eager encode (F-07, fixed).** `createVoiceClonePrompt` now evaluates the reference codes inside
  the caller's MLX scope (`Q:2257`), so the lazy encode no longer escapes into `MLX.save` or the
  first take.
- **Memory (A-08, A-28, open).** The encoder KV cache is kept between calls and a longer input
  concatenates onto the stale buffer (MEM-1). The SEANet encoder runs on the whole reference: about
  126 MB per activation for a 20 s reference and 740 MB for a 120 s Mac reference.
- **Reference padding.** Before encoding, Vocello appends 0.5 s of silence to the reference
  (`Q:607-650`); the x-vector uses the unpadded audio. Upstream pads nothing (A-12). The input rule
  and its status belong to the [prompting guide §2.3](qwen3-tts-prompting-guide.md).

---

## 3. Decoder

### 3.1 Path

`Qwen3TTSSpeechTokenizerDecoder` (`ST:942-1114`):

```text
Codes [B, 16, T_frame]
    ↓ SplitResidualVectorQuantizer.decode   codebooks 2,048 × 256, projected to 512 → [B, 512, T]
    ↓ CausalConv1d pre_conv (kernel 3)       → [B, 1024, T]
    ↓ DecoderTransformer (8 layers)          input 1024 → hidden 512 → output 1024
    ↓ UpsampleLayer × 2                      transposed conv ×2 + ConvNeXt, each
    ↓ DecoderInitialConv (kernel 7)          → 1,536 channels
    ↓ DecoderBlock × 4                       rates 8, 5, 4, 3; channels halve each block → 96
    ↓ DecoderOutputSnake + DecoderOutputConv (kernel 7)
    ↓ clip(-1, 1)                            → 24 kHz PCM [B, 1, T × 1920]
```

Total upsampling is 2 × 2 × 8 × 5 × 4 × 3 = 1,920 samples per frame. The output is clipped, not
passed through tanh (`ST:999`, `ST:1082`), as upstream (TV2 L884).

### 3.2 Building blocks

**RVQ decode.** The decoder's own `SplitResidualVectorQuantizer` (`ST:92-120`) splits the 16 codes
into `rvq_first` (1 semantic) and `rvq_rest` (15 acoustic). Each group looks up 256-wide entries
(`codebook_dim / 2`), sums them and projects to 512 through its `output_proj`; the two groups are
then summed. Codebook entries are rebuilt from training statistics:
`embedding = embedding_sum / max(cluster_usage, 1e-5)`
(`EuclideanCodebook`, `MLXAudioCodecs/Mimi/Quantization.swift:7-55`).

**CausalConv1d** (`ST:133-238`). Left padding only. `streamBuffer` keeps the last
`paddingAmount = (kernel − 1) × dilation + 1 − stride` input samples, so `step(_:)` prepends them to
new input and produces the same outputs as one batch call (stride 1). Depthwise convolutions are
built from kernel-size slices (A-29 lists this as a small performance lever).

**SnakeBeta** (`ST:244-261`; the output stage `DecoderOutputSnake`, `ST:730-746`, is the same):

```text
y = x + 1 / (exp(β) + 1e-9) · sin²(exp(α) · x)
```

α and β are per-channel parameters stored in log scale; the zeros they are initialized with are
placeholders the checkpoint overwrites.

**ConvNeXtBlock** (`ST:265-306`). A depthwise causal convolution (kernel 7, `groups = dim`),
LayerNorm (ε 1e-6), a 4× pointwise MLP with GELU, and a learned per-channel scale on the residual.
It follows the transposed convolution in each `UpsampleLayer`.

**DecoderTransformer** (`ST:457-510`). RMSNorm, attention with split-half RoPE
(`decoderRotateHalf`, `ST:355`), layer scale, and a `KVCacheSimple` per layer for incremental decode.
With more than one new frame it builds a full causal mask over `offset + n` positions and keeps the
last `n` rows (`ST:490-497`). The config's 72-frame `sliding_window` is decoded but never applied
(A-03, §5).

**DecoderBlock** (`ST:618-690`). SnakeBeta, then `DecoderBlockUpsample` (a transposed conv with
kernel `2 × rate` and stride `rate`, trimmed on the right only), then three residual units at
dilations 1, 3 and 9, each SnakeBeta → causal conv (kernel 7) → SnakeBeta → conv (kernel 1).

**DecoderBlockUpsample** (`ST:541-616`). Vocello's May 2026 patch replaced the output-side
overlap-and-add accumulator with input-side overlap-and-discard (`inputContext`). Output-side
accumulation re-parenthesized floating-point sums at every chunk boundary; with short streaming
chunks that drift amplified through SnakeBeta to more than 1 dB of peak deviation, an audible
boundary artifact (bench-rejected May 2026). Now each `step(_:)` keeps one trailing input sample,
decodes `[inputContext, newInput]` in one call and drops the first `upsampleRate` output samples,
which recompute the previous emission.

**Right-only trimming.** Both transposed convolutions trim `kernel − stride` samples on the right
only: none for the ×2 upsamplers (`CausalTransposeConv1d`, `ST:786-802`), `rate` for the decoder
blocks. That is the convention QwenLM settled on in `5f8581d` (§5.4).

---

## 4. Numeric profile

`Qwen3TTSTokenizerDecoderConfig` defaults (`Qwen3TTSConfig.swift:274-352`); the checkpoint's
`speech_tokenizer/config.json` supplies the values at load.

| Key | Default | Notes |
| --- | --- | --- |
| `latent_dim` | 1,024 | pre-conv output and transformer input/output width |
| `codebook_dim` | 512 | RVQ output width; entries are 256 wide (`codebook_dim / 2`) |
| `codebook_size` | 2,048 | entries per quantizer |
| `decoder_dim` | 1,536 | first SEANet-style block width |
| `hidden_size` | 512 | transformer width |
| `intermediate_size` | 1,024 | transformer MLP |
| `num_hidden_layers` | 8 | |
| `num_attention_heads` / `num_key_value_heads` | 16 / 16 | head dim 64 |
| `num_quantizers` | 16 | validated (`Qwen3TTSConfig.swift:509`) |
| `num_semantic_quantizers` | 1 | |
| `semantic_codebook_size` | 4,096 | a config value only: no official code reads it, the decoder uses `codebook_size` 2,048 (TV2 L834), and the talker's codebook 0 has 2,048 codes. Vocello only checks it (`Qwen3TTSConfig.swift:515`) |
| `sliding_window` | 72 | upstream applies it in every layer; Vocello does not (A-03) |
| `max_position_embeddings` | 8,000 | |
| `upsample_rates` | [8, 5, 4, 3] | `DecoderBlock`s; product 480 |
| `upsampling_ratios` | [2, 2] | `UpsampleLayer`s |
| `layer_scale_initial_scale` | 0.01 | |
| `rms_norm_eps` | 1e-5 | |
| `rope_theta` | 10,000 | |

`Qwen3TTSTokenizerEncoderConfig` defaults (`Qwen3TTSConfig.swift:358-460`):

| Key | Default | Notes |
| --- | --- | --- |
| `frame_rate` | 12.5 | validated |
| `sampling_rate` | 24,000 | |
| `codebook_dim` / `codebook_size` | 256 / 2,048 | |
| `num_quantizers` | 32 | 16 kept (`encoder_valid_num_quantizers`) |
| `hidden_size` | 512 | |
| `num_filters` | 64 | SEANet base filters |
| `num_hidden_layers` | 8 | |
| `num_attention_heads` / `num_key_value_heads` | 8 / 8 | head dim 64 |
| `intermediate_size` | 2,048 | |
| `sliding_window` | 250 | inert, as upstream (§2.3) |
| `upsampling_ratios` | [8, 6, 5, 4] | applied reversed |
| `rope_theta` | 10,000 | |

The wrapper config's `decode_upsample_rate` and `encode_downsample_rate` are both 1,920, and
`qwen3TTS12HzValidationFailure(includeEncoder:)` rejects any other stride, sample rate or quantizer
count (`Qwen3TTSConfig.swift:496-529`).

---

## 5. Decode semantics: the reference and Vocello

### 5.1 The reference

- **Window.** Every one of the 8 decoder layers uses a 72-frame sliding window (TC2 `layer_types`;
  TV2 L419, L535-551).
- **Batch decode** pads with −1 and counts valid length with `> -1`; `chunked_decode` decodes
  300-frame chunks with 25 frames of left context (TV2 L886-897, L1011-1017).
- **ICL output** decodes `ref_code + generated` and drops the reference's share of the samples
  (WM L612-633).
- **Precision.** The codec file is fp32; the README and evaluation load with `dtype=bf16`, which the
  loader also forwards to the tokenizer (research §3, a research reading).

### 5.2 What Vocello runs

Production decodes only through `streamingStep(_:)`, never through the batch call:

| Path | How it decodes | Source |
| --- | --- | --- |
| Streamed takes | `streamingStep` per playback chunk, on the runtime's chunk schedule | `Q:4185-4195`, `Q:4385-4392` |
| Quality-first takes | `streamingDecode` over 25-frame ranges (`qualityFirstDecoderChunkFrames`), then the sample window `[reference, reference + generated) × 1920` | `Q:3075-3125` |
| Codec replay (diagnostics) | `streamingStep` over the recorded ranges | `Q:3270-3300` |

The quality-first window counts frames explicitly; it never infers length from non-zero codes, since
code 0 is a legal codec token (`Q:3077-3094`).

**Clone history (D5, A-04).** Quality-first clones decode the reference codes and the generated codes
together and cut the reference's samples, as upstream does. Streamed clones start from a cold
decoder with no reference history. The cold path is open in ER-04 with A-26: re-decoding the whole
reference on every quality-first take costs about 65% more decoder work for a 20 s reference on a
30 s take, so the fix caches the primed decoder state per clone prompt.

**No window (A-03).** The decoder attends causally over the whole take. Its fp32 KV grows by about
64 KiB per frame: about 48 MiB at 60 s and 128 MiB at the 2,048-frame cap. Restoring the 72-frame
window and a bounded cache, with a parity fixture against the official 300/25 decode, is PA-16.
The decoder window must land before the decoder performance levers (audit ordering traps).

### 5.3 Partition invariance, within tolerance

Within Vocello, decoding the same codes in one call or in any partition gives the same waveform
within floating-point tolerance. `Qwen3DecoderPartitionTests` checks fixed partitions of 1, 2, 3, 4,
12, 25, 100 and 300 frames and 12 random ones against a single 300-frame decode, at a maximum absolute
difference of 1e-5 and an RMS difference of 1e-6, on a small test configuration
(`Packages/VocelloQwen3Core/Tests/Qwen3RuntimeTests/Qwen3DecoderPartitionTests.swift:8-59`).

That is a property of Vocello's unwindowed decoder. It does not make Vocello equal to the reference:
upstream's windowed layers and 300/25 chunking give different audio, and the PA-16 fixture is what
will measure the difference.

### 5.4 Upstream fixes and community reports

- **QwenLM `5f8581d`** (right-only transposed-conv trim) and **`6cafe55`** (−1 padding and the
  `> -1` length rule): Vocello matches both (`ST:786-802`; research §6).
- **The official Hugging Face demo Space** bundles pre-February tokenizer code with the old trim
  (555 samples short) and the old `> 0` length rule. Do not use it as a parity reference (research
  §1, finding 10).
- **QwenLM#219** (community): a cold decoder distorts the first token of a take. It bears on
  Vocello's cold streamed-clone decode (A-04).
- **QwenLM#223** (community): `chunked_decode` loses samples between chunks. It belongs in PA-16's
  parity fixture against the official 300/25 decode (research §10).
- **mlx-audio `c4d29e6`** (2026-10-07) added the transposed-conv bias twice at streaming chunk
  boundaries. Vocello is immune: its input-side overlap-and-discard (`ST:541-616`) decodes each
  emission in one call (research §6).

### 5.5 Chunk sizes (A-15, fixed)

A streaming chunk size travels from the contract to the talker loop as seconds
(`frames / 12.5`) and back. `Qwen3StreamChunkSchedule.codecFrames(forStreamingInterval:)` now rounds
(`Q:1395-1407`, commit `54842e39`, 2026-10-18); the earlier truncation lost a frame for 37 of the
chunk sizes 1–512. The product's own tier mapper still truncates by design
(`StreamChunkPolicy.currentShippingDefault`): 0.6 s is 7 frames there. The generic
`streamingDecode(_:chunkTokens:)` helper defaults to 100 frames, which is 8 s of audio; production
never uses that default.

### 5.6 Dead code (A-22)

`Qwen3TTSSpeechTokenizer.decode(_:)` (`ST:1153-1161`) has no caller. It still counts length with the
old `> 0` rule (`ST:1159`), the DECODE-002 pattern. `chunkedDecode(_:chunkSize:leftContextSize:)`
(`ST:1099-1113`, 300/25) is reachable only from it; it trims `contextSize × 1920` samples from each
chunk, the pattern QwenLM#223 reports. Neither is a memory-bounded production path. ER-12 removes
both.

---

## 6. Streaming invariants

Vocello's output must be glitch-free when codes arrive a few frames at a time.

### 6.1 Causal only

No output sample depends on later input: `CausalConv1d` pads on the left, `DecoderBlockUpsample`
keeps input-side context, the transformer uses a causal mask and its KV cache, and `ConvNeXtBlock`
uses a causal depthwise convolution.

### 6.2 Reset between utterances

`resetStreamingState()` (`ST:1002-1022`) clears the transformer cache, `preConv`'s buffer, both
`UpsampleLayer`s, `DecoderInitialConv`, every `DecoderBlock` and `DecoderOutputConv`. Skipping it
leaks the previous utterance into the next one's opening. `streamingDecode` resets before and after
its loop; codec replay resets on entry and exit.

### 6.3 Overlap-and-discard, never overlap-and-add

Two buffers make partitions agree (§5.3): `CausalConv1d.streamBuffer` and
`DecoderBlockUpsample.inputContext`. **Do not reintroduce output-side accumulation** in either; it
was bench-rejected for float drift on short chunks.

---

## 7. The shipped codec artifact

All six PowerBeef02 artifacts share `speech_tokenizer/model.safetensors`: fp32, 682,293,092 bytes,
SHA-256 `836b7b357f5ea43e889936a3709af68dfe3751881acefe4ecf0dbd30ba571258`
(`config/model-artifact-receipts.json`). It is byte-identical to Qwen's own
`Qwen/Qwen3-TTS-Tokenizer-12Hz` file (research §7, verified against the receipts). The decoder and
encoder weights are not quantized.

**The f16 round trip.** Artifact version 2026.08.01.1 halved the codec to f16. 2026.09.14.1 restored
fp32 because the f16 codec opened streamed clone takes with a burst in their first 50 ms. Byte
counts, digests and the full history are in
[`model-delivery.md`](model-delivery.md#artifact-provenance). Running the codec in fp32 is a
deliberate divergence from the README's bf16 setup; whether Qwen's evaluation ran the codec in bf16
is open (research question 6).

**Clone-artifact identity.** Persisted clone prompts hold encoder output, so anything that changes
the encode must change the speaker-feature version (§2.2): the reference preprocessing
(`icl-ref-silence500ms-v2`, `Q:621`), the MLX build (`mlx-swift-0.32.3`, `Q:798`), and, once A-02 is
fixed, the encoder itself (G-03). Audio preparation has no version either (G-13), so its fixes never
reach cached references; G-13 lands first in ER-04.

---

## 8. Performance and memory

Measured figures are from the engine audit (iPhone 17 Pro on iOS 27 with Speed 4-bit; Mac M6
16 GB).

- **Share of the loop.** Decode is 15–16% of the iPhone token loop and about 4% on the M6. On the
  iPhone its per-frame cost grows 8–21% over a take (D-10/D-11), which the unbounded KV and mask
  explain in part (A-03, A-27).
- **Mask (A-27).** Each multi-frame chunk builds an `(offset + n)²` additive mask, 16.8 MB at the
  cap, and keeps `n` rows.
- **First take after launch (D-02).** The Custom path never warms the codec decoder on the iPhone
  or the 8 GB Mac, so the iPhone's first take after every launch pays 0.21–0.23 s more. The audit's refuter confirmed Custom and
  refuted Design, whose `warmPreparedInputs` precompiles the decoder. The decoder warm-up shapes
  (1–4 frames) also miss production chunk sizes such as 7 and 14 (A-30).
- **`eval()` placement.** `streamingDecode` evaluates each chunk before returning it (`ST:1176`), and
  the live paths evaluate before readback, so the graph never accumulates across chunks. If you move
  an `eval`, measure wall time and peak footprint together; on iOS a faster graph that raises peak
  memory can trigger Jetsam.
- **Weights.** The codec is fp32 and unquantized in both tiers. Whole-model memory and the tier
  policy are in [`mlx-guide.md`](mlx-guide.md).

**MLX notes (CONV-21).** The package pins mlx-swift 0.32.3 since CONV-21. mlx-audio-swift v0.1.5
(`dbe5eaa`) replaced MLX's scalar-gather form, which passes empty index metadata to Metal when API
validation is on, in RVQ decode; Vocello still uses it (`ST:48`). Porting the range slice is ER-08 or
ER-12 work; whether the issue reproduces under 0.32.3 is open (research question 8). The pins and the
upgrade procedure are in [`mlx-guide.md`](mlx-guide.md); the upstream review point is in
[`UPSTREAM.md`](../../Packages/VocelloQwen3Core/UPSTREAM.md).

---

## 9. Troubleshooting

### 9.1 Clicks or wobble at chunk boundaries

1. Output-side overlap-and-add in a transposed conv: `DecoderBlockUpsample` must use `inputContext`.
2. A missing `resetStreamingState()` between utterances.
3. A `CausalConv1d.streamBuffer` that survived a reset.

Check the reset path, then confirm the overlap-and-discard pattern in the diff.

### 9.2 Muffled or telephonic output

Fewer than 16 codebooks reached the decoder: check `encoder_valid_num_quantizers = 16`, the decoder's
`num_quantizers = 16`, and that the code predictor emits all 15 residual codebooks.

### 9.3 Codes and audio disagree in length

Every frame decodes to exactly 1,920 samples. Check `decode_upsample_rate` and
`encode_downsample_rate` with `qwen3TTS12HzValidationFailure(includeEncoder:)`, and that any length
is counted in frames, never by testing codes against 0.

### 9.4 Speaker encoder or tokenizer encoder

A Base checkpoint carries two encoders: the speaker encoder (mel → x-vector,
`Qwen3TTSSpeakerEncoder`) and the speech-tokenizer encoder (audio → codes). `includeEncoder` controls
only the second. Do not mix `encoder_model` keys with speaker-encoder keys in `sanitize(weights:)`.

### 9.5 Missing keys or shape mismatches after a checkpoint change

`Qwen3TTSSpeechTokenizer.sanitize(weights:)` (`ST:1185` onward) strips prefixes, maps PyTorch
convolution layouts to MLX, concatenates the encoder's q/k/v into `in_proj`, rebuilds codebooks from
`cluster_usage` and `embedding_sum`, and maps nested encoder names onto the Swift module tree. Add a
branch there for a new naming convention.

---

## 10. Appendix

### 10.1 Glossary

| Term | Meaning |
| --- | --- |
| RVQ | Residual vector quantization: each codebook quantizes what the previous ones left over; decode sums the entries |
| Split RVQ | One semantic codebook (`rvq_first`) and the acoustic rest (`rvq_rest`), quantized and decoded as two groups |
| SnakeBeta | The learned periodic activation in §3.2 |
| ConvNeXt block | Depthwise causal conv, LayerNorm and a pointwise MLP with a scaled residual |
| ICL | In-context learning: a clone conditioned on the reference's codes and transcript |
| Overlap-and-discard | Streaming by recomputing a little left context and dropping the recomputed head |
| Partition invariance | The same waveform, within tolerance, however the codes are chunked |

### 10.2 Related documents

- [`qwen3-tts-guide.md`](qwen3-tts-guide.md): model family, talker, code predictor, generation
  modes and the parity ledger.
- [`qwen3-tts-prompting-guide.md`](qwen3-tts-prompting-guide.md): wire format, and the clone
  reference and transcript rules.
- [`mlx-guide.md`](mlx-guide.md): MLX runtime, lazy evaluation, quantization, memory and pins.
- [`model-delivery.md`](model-delivery.md): codec bytes, digests and artifact history.
- [`CLONE_ARTIFACT_FORMAT.md`](../../Packages/VocelloQwen3Core/CLONE_ARTIFACT_FORMAT.md): the
  persisted clone-prompt identity.

### 10.3 External references

- Kyutai's Mimi: the Moshi paper, arXiv:2410.00037.
- Qwen3-TTS Technical Report, arXiv:2601.15621.
- QwenLM/Qwen3-TTS, `qwen_tts/core/tokenizer_12hz/`, at `022e286b98`:
  <https://github.com/QwenLM/Qwen3-TTS>.
- mlx-audio-swift: <https://github.com/Blaizzy/mlx-audio-swift>.
- Vocello's sourced research and parity ledger:
  [`2026-10-17-qwen3-tts-model-research.md`](../audits/2026-10-17-qwen3-tts-model-research.md).
