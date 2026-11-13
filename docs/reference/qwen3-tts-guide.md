---
status: active
owner: backend-mlx
reviewed: 2026-11-11
summary: Model reference for the Qwen3-TTS checkpoints Vocello ships — the upstream family, the shipped artifacts and conversion recipe, the architecture, generation semantics as shipped after RF-18 and CONV-21, languages and speakers, the failure catalogue and the parity ledger.
sourceOfTruth:
  - Packages/VocelloQwen3Core/Sources/MLXAudioTTS/Models/Qwen3TTS/Qwen3TTS.swift
  - Packages/VocelloQwen3Core/Sources/MLXAudioTTS/Models/Qwen3TTS/Qwen3TTSTalker.swift
  - Packages/VocelloQwen3Core/Sources/MLXAudioTTS/Models/Qwen3TTS/Qwen3TTSCodePredictor.swift
  - Packages/VocelloQwen3Core/Sources/MLXAudioTTS/Models/Qwen3TTS/Qwen3TTSConfig.swift
  - Packages/VocelloQwen3Core/Sources/MLXAudioTTS/Models/Qwen3TTS/Qwen3TTSSpeakerMelFrontend.swift
  - Packages/VocelloQwen3Core/Sources/MLXAudioTTS/Models/Qwen3TTS/Qwen3TTSSpeechTokenizer.swift
  - Packages/VocelloQwen3Core/Sources/MLXAudioCodecs/Mimi/Transformer.swift
  - Packages/VocelloQwen3Core/Sources/MLXAudioTTS/Generation.swift
  - Packages/VocelloQwen3Core/Sources/VocelloQwen3Core/Contracts.swift
  - Sources/QwenVoiceBackendCore/QwenVoiceBackendCore.swift
  - Sources/QwenVoiceCore/UnsafeSpeechGenerationModel.swift
  - Sources/QwenVoiceCore/GenerationSemantics.swift
  - Sources/QwenVoiceCore/SemanticTypes.swift
  - Sources/QwenVoiceCore/NativeCloneSupport.swift
  - Sources/Resources/qwenvoice_contract.json
  - docs/audits/2026-10-17-qwen3-tts-model-research.md
  - docs/audits/2026-10-16-engine-runtime-audit.md
  - docs/audits/2026-11-11-qwen3-tts-quality-report-review.md
---

# Qwen3-TTS Reference Guide

The model reference for the Qwen3-TTS checkpoints that power Vocello. It owns the model family, the
shipped checkpoints and their conversion recipe, the architecture, generation semantics, languages
and speakers, the failure catalogue and the parity ledger. Other facts have one owner each:

| Fact | Owner |
| --- | --- |
| Wire format, instructions, presets, briefs, transcript and ICL input rules | [`qwen3-tts-prompting-guide.md`](qwen3-tts-prompting-guide.md) |
| The 12 Hz speech tokenizer (encoder, RVQ, decoder internals) | [`mimi-codec-guide.md`](mimi-codec-guide.md) |
| MLX semantics, error scopes, quantization mechanics, dependency pins | [`mlx-guide.md`](mlx-guide.md) |
| Artifact bytes, digests, revisions and `artifactVersion` history | [`model-delivery.md`](model-delivery.md) |
| Engine structure, memory tiers, streaming, prewarm and the clone host pipeline | [`ARCHITECTURE.md` §4](../ARCHITECTURE.md#4-engine-core-qwenvoicecore) |

Every model fact below comes from Vocello's code, from the sourced research report
[`2026-10-17-qwen3-tts-model-research.md`](../audits/2026-10-17-qwen3-tts-model-research.md) (upstream
citations such as `MQ L615` or `QwenLM#239` use its source keys), or from the
[engine runtime audit](../audits/2026-10-16-engine-runtime-audit.md) (finding IDs such as A-02 or
G-01). The corrections to upstream readings and the measurements dated 2026-11-11 come from the
[counter-verification review](../audits/2026-11-11-qwen3-tts-quality-report-review.md) of that day. Code citations are
`path:line` at the commit that last reviewed this file.

**Update this file** when `qwenvoice_contract.json` changes a model, variant, speaker or default;
when the engine's sampling, decoding or conditioning changes (`UnsafeSpeechGenerationModel.swift`,
`Generation.swift`, `Contracts.swift`, `Qwen3TTS.swift`); when a parity item's status changes; or
when upstream publishes a new checkpoint.

---

## 1. What Qwen3-TTS is

Qwen3-TTS is an open-weight text-to-speech family from Alibaba Cloud's Qwen team, released on
2026-01-21 under Apache-2.0. An autoregressive **talker** language model predicts one codec frame at a
time, a small **code predictor** fills in the rest of each frame, and the **12 Hz speech tokenizer**
decodes the frames to 24 kHz mono audio. The family serves three uses, each a separately weighted
checkpoint:

- **CustomVoice**: 9 preset speakers, steered by a natural-language instruction. Vocello labels this
  mode **Built-in Voice** (mode id `custom`).
- **VoiceDesign**: a voice described in text, sampled anew on each call (`design`).
- **Base**: a voice cloned from reference audio (`clone`).

The open-weight family has not changed since January 2026: the weights were never revised, the last
inference-code change is `qwen-tts` 0.1.1 (2026-02-06), and the last repository commit (2026-03-17)
touches fine-tuning only. The 25 Hz models, the 25 Hz tokenizer and 25Hz-VoiceEditing appear in the
technical report and were never published (QwenLM#294, closed as not planned; QD#46). The hosted
`qwen3-tts-flash` and `qwen-audio-3.x` API models share the name but not the weights, and their
guidance (10–20 s references, a 60 s maximum, 500-character briefs) describes the hosted service,
not the open checkpoints.

---

## 2. The family and the shipped checkpoints

### 2.1 Upstream family

| Checkpoint | Parameters | Role | Instruction | Vocello |
| --- | --- | --- | --- | --- |
| `Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice` | 1,916,676,352 | 9 preset speakers | yes | ships |
| `Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign` | 1,916,676,352 | voice from a description; no speakers | the description is the instruction | ships |
| `Qwen/Qwen3-TTS-12Hz-1.7B-Base` | 1,928,677,440 | ICL or x-vector clone; fine-tuning base; carries the speaker encoder | no (QwenLM#25) | ships |
| `Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice` | 905.8 M | 9 preset speakers | no: the wrapper drops it (WM L799-800), although the model card claims it | not shipped |
| `Qwen/Qwen3-TTS-12Hz-0.6B-Base` | 914,643,008 | clone | no | not shipped |
| `Qwen/Qwen3-TTS-Tokenizer-12Hz` | 170.6 M, fp32 | codec encode and decode | — | ships as each artifact's `speech_tokenizer/` |
| 25 Hz Base and CustomVoice, 25Hz-1.7B-VoiceEditing, Tokenizer-25Hz | — | paper only | — | never released |

There is no 0.6B VoiceDesign. mlx-community publishes bf16, 4-, 5-, 6- and 8-bit conversions of all
five models, unchanged since 2026-01-25; Vocello ships its own conversions instead (§2.2, §2.3).

### 2.2 What Vocello ships

Three model ids, each in two variants, all MLX conversions of the 1.7B checkpoints published as
`PowerBeef02/Qwen3-TTS-12Hz-1.7B-{CustomVoice,VoiceDesign,Base}-{4bit,8bit}` at the revisions
`qwenvoice_contract.json` pins (`artifactVersion` `2026.09.14.1`).

| Mode (id) | Model id | Upstream checkpoint | Speed, 4-bit | Quality, 8-bit |
| --- | --- | --- | --- | --- |
| Built-in Voice (`custom`) | `pro_custom` | 1.7B-CustomVoice | iOS and macOS | macOS |
| Voice Design (`design`) | `pro_design` | 1.7B-VoiceDesign | iOS and macOS | macOS |
| Voice Cloning (`clone`) | `pro_clone` | 1.7B-Base | iOS and macOS | macOS |

- **Variant selection** (`ModelDescriptor.preferredVariant`, `SemanticTypes.swift:494-512`): the
  iPhone always takes Speed; a Mac takes Quality unless it is in the `floor8GBMac` memory class.
- **Capabilities** (contract `qwen3Capabilities`): `supportsInstructionControl` is true for Custom
  and Design; `supportsVoiceClone`, `supportsXVectorOnlyClone` and `requiresSpeakerEncoder` are true
  only for Clone. An audio-only clone fails before model preparation on a model that does not
  declare x-vector support (`NativeEngineRuntime.swift:1960-1972`).
- Revisions, files, byte counts and digests: [`model-delivery.md`](model-delivery.md#artifact-provenance).

### 2.3 Conversion recipe

- **Quantization:** affine, group size 64, 4-bit (Speed) or 8-bit (Quality), over 251 modules in the
  4-bit CustomVoice index: every talker and code-predictor projection, the 15 code-predictor heads,
  `codec_head`, `small_to_mtp_projection` and `text_projection`.
- **Text embedding:** `talker.model.text_embedding` is 8-bit in both tiers. This is Vocello's one change
  to the weights (`scripts/convert_text_embedding_8bit.py`, 2026-07-26): 292 MB less on disk, 278 MB
  less MLX peak on an 8 GB Mac, and a change to fixed-seed output.
- **Kept unquantized:** the talker's codec embeddings, the 15 code-predictor codec embeddings, every
  norm and bias (bf16); the Base speaker encoder (float); the speech tokenizer (fp32, byte-identical to
  Qwen's release).
- **Compute dtype** is bf16, so the talker KV cache is bf16.
- **`generation_config.json`** is upstream's, unchanged.
- **Marking:** every artifact also carries Meta's AudioSeal generator
  (`marking/audioseal_wm16_generator_fp16.safetensors`).
- **Precision caveat:** Qwen trained and evaluated in bf16 and recommends fp32 where bf16 is
  unavailable. A collaborator says the code predictor is "extremely sensitive to precision"
  (QwenLM#43); the context is half-precision assertion failures on CUDA, not a quality comparison
  of quantized weights (corrected 2026-11-11). No quantized checkpoint was ever evaluated upstream.
  Vocello quantizes all 51 code-predictor linear and head modules in both tiers, which the local
  model files confirm (2026-11-11).
- **Precision pre-screen (2026-11-11,
  [review §4.2](../audits/2026-11-11-qwen3-tts-quality-report-review.md#42-4-bit-against-8-bit) and
  [§4.3](../audits/2026-11-11-qwen3-tts-quality-report-review.md#43-where-the-loss-sits-mixed-precision)).**
  Quantization costs clone fidelity, measurably and by a small amount:
  - The 8-bit Base model's clones match the reference speaker better than the 4-bit model's by
    0.025 in ReDimNet2+ similarity (95% interval +0.016 to +0.034, 48 pairs).
  - An 8-bit code predictor under the 4-bit talker gives +0.010 (+0.002 to +0.019) for 56 MB
    (189.0 MB to 245.1 MB).
  - The 8-bit talker alone gives +0.007 for 712 MB.
  - Speed was not measured. The runs used the Python port, in English, and nobody listened, so
    this is a pre-screen, not a qualification.

### 2.4 Licenses

The five Qwen3-TTS checkpoints, the 12 Hz tokenizer and the QwenLM/Qwen3-TTS repository are
Apache-2.0; the technical report (arXiv:2601.15621) is CC BY 4.0; the AudioSeal generator each
artifact bundles is MIT.

---

## 3. Architecture

Numbers are for the 1.7B checkpoints unless noted; upstream line citations are in the research report
[§3](../audits/2026-10-17-qwen3-tts-model-research.md#3-architecture-as-implemented-upstream-17b-unless-noted).

```text
Script ─► Qwen2 BPE ─► text embedding + text_projection ─┐
Speaker row or x-vector (+ ICL reference codes) ─► codec ─┴─► Talker (28 layers)
                                                                │  one codebook-0 token per frame
                                                                ▼
                                   Code predictor (5 layers × 15 passes) ─► codebooks 1–15
                                                                │  16 codes per 80 ms frame
                                                                ▼
                                   12 Hz tokenizer decoder ─► 24 kHz mono PCM in [-1, 1]
```

### 3.1 Talker

| Parameter | 1.7B | 0.6B |
| --- | --- | --- |
| Hidden size | 2,048 | 1,024 |
| SwiGLU intermediate size | 6,144 | 3,072 |
| Layers | 28 | — |
| Attention heads / KV heads / head dim | 16 / 8 / 128 (q dim 2,048) | q dim 2,048, larger than the hidden size |
| Norm | RMSNorm, ε 1e-6 | — |
| RoPE θ; max positions | 1e6; 32,768 | — |
| Codec vocabulary; text vocabulary | 3,072; 151,936 | — |
| Code groups per frame | 16 | — |

A dash means the research report lists no difference from 1.7B.

- **Q/K norm.** Per-head RMSNorm on q and k before RoPE.
- **RoPE is split-half** (`rotate_half` over `cat(freqs, freqs)`), upstream (MQ L546-559, L615-619)
  and in Vocello (`Qwen3TTSTalker.swift:8-21`). The config's `rope_scaling.interleaved` only chooses
  which M-RoPE stream feeds each frequency, and all three position streams are equal, so this is plain
  1-D RoPE.
- **Text path.** `text_projection` is a SiLU MLP with bias; `codec_head` is untied.
- **Step input.** Each step's input is the sum of the previous frame's 16 codebook embeddings
  (codebook 0 from the talker's `codec_embedding`, 1–15 from the code predictor's) plus the text track
  (`Qwen3TTS.swift:2835-2859`).
- `position_id_per_seconds: 13` is in the config and read by no code.

### 3.2 Codec vocabulary and control ids

Ids 0–2047 are codebook-0 codes and the only ids the talker may sample; the rest are control,
language and speaker ids. The defaults below match the checkpoint config and the loader
(`Qwen3TTSConfig.swift:247-253`).

| Id | Token | Id | Token |
| --- | --- | --- | --- |
| 2148 | `codec_pad` | 2154 | `think` |
| 2149 | `codec_bos` | 2155 | `nothink` |
| 2150 | `codec_eos` | 2156 | `think_bos` |
| | | 2157 | `think_eos` |

**Languages:** english 2050, german 2053, spanish 2054, chinese 2055, japanese 2058, french 2061,
korean 2064, russian 2069, italian 2070, portuguese 2071; CustomVoice adds `sichuan_dialect` 2062 and
`beijing_dialect` 2074. **Speakers** are in §4. The engine looks both up in the checkpoint's
`codec_language_id` and `spk_id` tables, not in a hard-coded list (`Qwen3TTS.swift:318-343`).

### 3.3 Text tokenizer

`Qwen2Tokenizer` byte-level BPE from `vocab.json` and `merges.txt`, with no `tokenizer.json` and no chat
template. Special ids: `<|im_start|>` 151644, `<|im_end|>` 151645, `assistant` 77091, `<tts_pad>`
151671, `<tts_text_bos>` 151672, `<tts_text_eod>` 151673. The ChatML strings, the prefill order and the
`think`/`nothink` branch are wire format:
[prompting guide §1](qwen3-tts-prompting-guide.md#1-the-wire-format).

### 3.4 Code predictor (multi-token prediction)

Hidden 1,024, 5 layers, 16 heads / 8 KV heads, θ 1e6, vocabulary 2,048, with 15 codec embeddings at
talker width, 15 heads and `small_to_mtp_projection` (2,048 → 1,024; identity on 0.6B). Each frame
runs 15 sequential passes, one per residual codebook (`Qwen3TTS.swift:2763-2833`), with its own
sampling settings, no EOS and no repetition penalty (MQ L1671-1680, L1276-1299). The weights sit
under `talker.code_predictor.model.codec_embedding.{0…14}` and `talker.code_predictor.lm_head.{0…14}`
(`Qwen3TTSCodePredictor.swift:212`, `:273`).

### 3.5 Speaker encoder (Base only)

An ECAPA-TDNN without BatchNorm (MQ L95-393) whose output is 2,048 wide on 1.7B (1,024 on 0.6B). It
reads mono 24 kHz audio through a magnitude-mel frontend: 1,024-point FFT, hop 256, periodic Hann
window, reflect padding 384, 128 Slaney mel bins up to 12 kHz, `sqrt(re² + im² + 1e-9)` and
`log(max(·, 1e-5))`. Vocello's frontend, `qwen-speaker-mel-v1`, implements that contract
(`Qwen3TTSSpeakerMelFrontend.swift:11-22`); the clone artifact format is in
[`CLONE_ARTIFACT_FORMAT.md`](../../Packages/VocelloQwen3Core/CLONE_ARTIFACT_FORMAT.md). CustomVoice
speakers are not encoder outputs: each is a row of the talker's codec embedding, addressed by its
`spk_id`.

### 3.6 The 12 Hz speech tokenizer

The profile below is declared per model in `qwenvoice_contract.json` and checked at load
(`Qwen3TTSConfig.swift:496-529`). Internals are in the
[codec guide](mimi-codec-guide.md#1-summary).

| Parameter | Value |
| --- | --- |
| Sample rate; frame rate | 24,000 Hz; 12.5 Hz (80 ms per frame, `decode_upsample_rate` 1,920) |
| Quantizers | 16 decode; 16 valid of the encoder's 32 configured |
| Codebook size | 2,048 per quantizer |
| `semantic_codebook_size` | 4,096 in the config only: no official code reads it, and Vocello only checks the value |
| Bitrate | ~2.2 kbps (16 × 11 bits × 12.5 Hz), ~175× smaller than 16-bit 24 kHz PCM |

Three model-level facts matter for parity (§12):

- **Encoder.** Transformers' `MimiModel` without its decoder. Its q/k weights are stored for
  `rotate_half`, but Vocello's port applies `RoPE(traditional: true)`
  (`Packages/VocelloQwen3Core/Sources/MLXAudioCodecs/Mimi/Transformer.swift:130`; A-02, open, with
  no detectable effect on clone output in the 2026-11-11 pre-screen, §12). Its
  attention is full causal (`Transformer.swift:168`), which matches upstream: the configured 250-frame
  window applies only under FlashAttention-2, which the official loader does not select.
- **Decoder.** Qwen's own code. Upstream gives each of its 8 transformer layers a 72-frame sliding
  window; Vocello's decoder attends causally over the whole take (`Qwen3TTSSpeechTokenizer.swift:490-498`;
  A-03, open).
- **Output** ends in `clamp(-1, 1)`, not tanh (`Qwen3TTSSpeechTokenizer.swift:999`).

---

## 4. Built-in speakers

The roster, native languages and descriptions come from `qwenvoice_contract.json`; the codec ids and
dialect map come from the CustomVoice checkpoint config (`spk_id`, `spk_is_dialect`), which is what the
engine reads at runtime.

| Id | Display name | Native language | Codec id | Description (contract) |
| --- | --- | --- | --- | --- |
| `aiden` | Aiden | English | 2861 | Sunny American male voice with a clear midrange |
| `ryan` | Ryan | English | 3061 | Dynamic male voice with strong rhythmic drive |
| `vivian` | Vivian | Chinese | 3065 | Bright, slightly edgy young female voice |
| `serena` | Serena | Chinese | 3066 | Warm, gentle young female voice |
| `uncle_fu` | Uncle Fu | Chinese | 3010 | Seasoned male voice with a low, mellow timbre |
| `dylan` | Dylan | Chinese (Beijing dialect) | 2878 | Youthful male voice with a clear, natural timbre |
| `eric` | Eric | Chinese (Sichuan dialect) | 2875 | Lively Chengdu male voice with a slightly husky brightness |
| `ono_anna` | Ono Anna | Japanese | 2873 | Playful female voice with a light, nimble timbre |
| `sohee` | Sohee | Korean | 2864 | Warm female voice with rich emotion |

- **Default speaker:** `aiden` is Vocello's default (`defaultSpeaker`); upstream has none.
- **Cross-lingual use:** each speaker sounds best in its native language but can speak all ten
  (RM L187).
- **Dialect swap.** `spk_is_dialect` maps `eric` to `sichuan_dialect` and `dylan` to
  `beijing_dialect`. With language Chinese or Auto, those two speakers take the dialect language id
  instead (`Qwen3TTS.swift:324-329`), as upstream does (MQ L2118-2122). Production Custom never sends
  Auto (§7.2, D6), so in practice the swap fires when the language resolves to Chinese.

---

## 5. Generation modes

What each mode accepts and what the host sends (`GenerationSemantics.qwen3PromptAssembly`,
`GenerationSemantics.swift:617-696`). How to write the script, instruction and brief is the
[prompting guide](qwen3-tts-prompting-guide.md)'s subject.

| Mode | Voice identity from | Instruction | Reference transcript | Language when undetected |
| --- | --- | --- | --- | --- |
| Custom | the speaker's codec row | the delivery preset or free text, if the model supports it | — | `english` (D6) |
| Design | the instruction | the brief and the delivery, as one instruction | — | `auto` |
| Clone | the reference: x-vector, plus reference codes for ICL | none; the request type has no field for it | inline or saved-voice transcript | `auto` |

Custom and Design instructions are refused if they ask for celebrity imitation or voice impersonation
(`validateQwenPromptContract`, `GenerationSemantics.swift:891`).

### 5.1 Built-in Voice (CustomVoice)

A preset speaker plus an optional delivery instruction. Instruction control exists on the 1.7B
CustomVoice checkpoint; upstream drops it on 0.6B, and the runtime keeps the same guard
(`supportsCustomInstructionControl`). For English output the host appends a diction sentence to the
instruction unless the instruction already asks for clarity; the rule, its exceptions and its
measurements are in the [prompting guide §8.2](qwen3-tts-prompting-guide.md#82-the-one-defect-the-audit-found).

### 5.2 Voice Design

The brief (at most 500 characters, `VoiceDesignBriefCatalog.descriptionLimit`) and the delivery form
one instruction, and the model samples a new voice that fits it on every call (QwenLM#4): Design has
no fixed speaker id. Design exists only at 1.7B. The English diction sentence applies here too
(`GenerationSemantics.swift:666`). For a voice that stays the same across takes, design it once and
clone the result (§5.4).

### 5.3 Voice Cloning (Base)

Two conditioning modes, chosen by whether a transcript resolves:

- **ICL (transcript-backed):** the speaker embedding plus the reference's codec codes and its
  transcript. Upstream requires `ref_text` for ICL (WM L436-438), and it should cover the **whole**
  reference: a transcript of only part of it is reported to make ICL loop without EOS. The report
  is MA#921, from one user with one clip and one text: on official PyTorch, three degenerate takes
  of three with a transcript covering about 6 s of a 10 s clip, and five normal takes of five with
  the full transcript.
- **x-vector only (audio-only):** the speaker embedding alone. Upstream ignores any transcript here
  and calls the quality lower (RM L243). An empty or whitespace transcript selects this mode; it never
  falls back to Voice Design.

A one-off reference uses only an inline transcript; a saved voice also reads its `.txt` sidecar
(`NativeCloneSupport.swift:783-801`). The Base model does not support instructions (QwenLM#25), and
Vocello's clone request has no field to carry one. Model-side conditioning details and Vocello's
open clone gaps are in §8.

### 5.4 Design, then clone

Qwen's recommended route to a reusable designed voice (RM L288-290; QwenLM#4): sample a design until
one fits, then use that take as a clone reference with its exact script as the transcript, and
generate every later line from the clone prompt.

---

## 6. Delivery presets

`Sources/QwenVoiceCore/EmotionPreset.swift` defines eight presets — Neutral, Happy, Sad, Angry,
Fearful, Surprised, Calm and Whisper — each shipping one instruction; Neutral is itself an instructed
preset. The user-facing intensity control was retired on 2026-08-02. The prompting guide owns the
preset copy, its measured recognizability and instruction language; it also adjudicates, in
[§9](qwen3-tts-prompting-guide.md#9-adjudicating-the-claims-already-in-this-repository), the
prompt-writing lessons this guide used to list. Two upstream facts frame them: emotive instructions
can add laughter, and Qwen's own suggested remedy is a negative constraint such as "very happy but
without laughing" (QwenLM#16); non-verbal sounds come out only implicitly (QwenLM#9).

---

## 7. Language handling

### 7.1 Supported languages

`Qwen3SupportedLanguage` (`SemanticTypes.swift:32-43`) lists Chinese, English, Japanese, Korean,
German, French, Russian, Portuguese, Spanish and Italian, plus `auto`. Each named language becomes its
codec language id (§3.2) and selects the `think` branch; `auto` sends no language id and selects
`nothink`. Qwen advises setting the language when it is known (RM L50, L167); its own evaluation
ran Seed-TTS and InstructTTSEval with language `auto` and the other benchmarks with an explicit
language (RM L465).

### 7.2 How a take's language is chosen

`GenerationSemantics.qwenLanguageHint` (`GenerationSemantics.swift:864-889`):

1. An explicit language on the request wins in every mode.
2. Otherwise the language is detected from the target script
   (`detectedQwenLanguage`, `GenerationSemantics.swift:1172-1196`). A script decides only when it
   carries most of the text: a mostly East Asian text resolves to Chinese, Japanese or Korean by the
   proportion of kana, Hangul and Han; a mostly Cyrillic text to Russian; anything else goes to
   `NLLanguageRecognizer` (`PromptLanguageDetector`), which separates the Latin-script languages and
   returns nothing when unsure.
3. Undetected: Custom falls back to `english` (D6), Design and Clone to `auto`.

For Clone, the reference transcript's language is conditioning metadata and never redirects the
target. D6's A/B knob, `QWENVOICE_CUSTOM_AUTO_LANGUAGE=on`, sends Auto for undetected Custom takes;
like every knob it needs the internal-diagnostics build and `QWENVOICE_DEBUG`
(`config/runtime-debug-knobs.json`).

Delivery-instruction language, including the one Mandarin preset cell, belongs to the
[prompting guide §4.4](qwen3-tts-prompting-guide.md#44-instruction-language-separate-inputs-unresolved-comparative-quality).
The language unit tests, the hint bench and the output round trip are in
[`telemetry-and-benchmarking.md` §5](telemetry-and-benchmarking.md#5-language-bench).

### 7.3 Dialects and accents

- Dylan and Eric take their dialect ids under Chinese (§4). Upstream reports dialect instructions as
  ignored (QwenLM#248).
- Accent requests in Voice Design are suggestions, not guarantees: Design in Spanish or French can
  sound English (QD#230), and Vivian and Serena carry a Chinese accent in other languages (QwenLM#359).
- Latin-script detection can be ambiguous on short texts; set the language explicitly when it
  matters.

---

## 8. Clone conditioning

What the model receives for a clone, and where Vocello departs from upstream. The host pipeline
(normalization, caches, persistence, review) is
[`ARCHITECTURE.md` §4.8](../ARCHITECTURE.md#48-voice-cloning-cache); transcript and ICL input rules
for users and the enrollment flow belong to the [prompting guide §2.3](qwen3-tts-prompting-guide.md#23-clone-input-the-transcript-and-the-reference).

### 8.1 The clone prompt

- **Both modes** extract the speaker embedding with the speaker encoder (§3.5) from the unpadded
  reference (an ICL prompt's trimmed and faded first, below; an audio-only prompt's as given), a finite `float32 [1, D]` vector cast to the talker's dtype only at the prefix slot.
- **ICL** also encodes the reference with the tokenizer's encoder, unpadded, as upstream does (since
  2026-11-11), after trimming its silent edges and fading it (G-07, since 2026-11-12; version
  `icl-ref-edges-trimmed-v4`). Vocello used to append 0.5 s of silence first (A-12,
  its own step); the clone screen's rule `reference-padding-none` adopted none: speaker similarity
  +0.019 (interval +0.001 to +0.039), trailing silence -22 ms (-35 to -8), the better family's error
  rate +0.012 (+0.002 to +0.026, the size of the screen's own noise floor), gross failures 2 and 4.
- **ICL target text** gets exactly one leading space unless its first letter is Han or kana
  (`Qwen3ICLTargetText.boundaryMarked`); upstream joins the reference and target tokens with no separator.
  Vocello added the space for French first-word drops (A-11, deliberate); since 2026-11-12 a Han or kana
  target joins as upstream's does, adopted by the `clone-cjk` screen's rule
  `icl-target-space-unspaced-scripts` (RF-52: no guard moved beyond the screen's floor, and 2 takes lost
  against 6). `QWENVOICE_ICL_TARGET_SPACE=every-target` puts the space before every target again in a
  diagnostics build.
- **ICL layout.** Vocello always lays the reference and target text over the reference's codec frames
  in the non-streaming overlay (mlx-audio lineage, G-14). Upstream's `generate_voice_clone` defaults
  to the streaming layout (WM L478), and a long reference in that layout speeds speech up
  (QwenLM#239). Pull request 362 proposes non-streaming as the default; as of 2026-11-11 it is
  open, from an outside contributor and unreviewed.
- **Decoder history.** Upstream's ICL decodes the reference codes plus the generated ones and drops
  the reference's share of the samples (WM L612-633). Vocello's streamed clones start from a cold
  decoder until 2026-11-12 (A-04). They now prime the decoder with the reference's codes, adopted by
  the clone screen on two seed sets (speaker similarity +0.060 and +0.056, error rate unchanged;
  `QWENVOICE_CLONE_DECODER_HISTORY=cold` restores the cold decoder). Since A-26 the first streamed
  take of a reference keeps the primed state and later streamed takes restore it, bit for bit the
  same; a quality-first clone still decodes the reference on every take. No upstream report shows
  audible harm from a cold decoder: the one that was cited, QwenLM#219, was withdrawn by its author
  (§11.1).

### 8.2 Reference length and warnings

Qwen advertises a "3-second rapid clone" (RM L77). Vocello's duration thresholds come from the hosted
service's guidance, not from a documented limit of the open model. One check,
`CloneReferenceQuality` (`Sources/QwenVoiceCore/CloneReferenceQuality.swift`), serves enrollment, the
saved-voice list, a one-off reference in the Mac Studio and the engine, and reads the clip as the user
gave it (RF-51, fixed 2026-11-11; the audit's G-08 to G-11):

| Finding | Token | Effect |
|---|---|---|
| Under 10 s | `reference_duration_short` | Advice |
| 30 to 60 s | `reference_duration_long` | Advice |
| Over 60 s | `reference_duration_excessive` | Blocks |
| Cannot be read | `reference_quality_unreadable` | Blocks |
| Silent (level under -66 dBFS) | `reference_near_silence` | Blocks |
| Source sampled below 16 kHz | `reference_source_rate_low` | Advice |
| Clipped | `reference_possible_clipping` | Advice |

- **Blocks** means three things. The review surfaces offer no "Keep voice". The saved-voice store
  refuses to commit such a candidate, so a one-shot enrollment cannot keep it either. And the engine
  refuses a one-off reference (`CloneReferenceQuality.Rejection`) before it loads a model, so the Mac
  Studio, line batches, long-form and the CLI's `--reference` share one policy and a refused clip
  costs no load. The apps show the reason (too long, or silent) from the catalog; the CLI reports
  `audio.input_too_long` or `audio.reference_silent`. A voice already saved keeps working.
- **Every surface measures the clip as the user gave it**, so they cannot disagree about it. The
  engine keeps its result per file state (path, size and modification time), so a take after the
  first, a long-form segment or a batch line reads no audio for the check again.
- **The source rate is read from the original file's header.** Preparation resamples to 24 kHz mono,
  so the earlier check of the prepared file never fired and 8 kHz telephone audio enrolled silently.
- **Clipping is counted as flat tops**: the signal held at the clip's own peak for 125 microseconds
  (three samples at 24 kHz), at least 0.5 times a second. On 476 licensed speech clips, at their own
  rates and resampled to 48 kHz, no clean clip is flagged (the highest has 0.43 a second), 89% of the
  same clips overdriven by 3 dB are, and 99% by 6 dB. A loud clean clip is not flagged, and a clip
  overdriven and then turned down still is. A lossy re-encode smooths the flat tops, so clipping baked
  into an AAC or MP3 file is not detected.
- **Enrollment runs the whole check; the saved-voice list reads only the header** (duration and
  source rate), so listing stays one cheap read per voice.
- **The iPhone recorder's Stop keeps a clip under 10 s on the recorder**, as the Mac's does.
- **Not checked:** whether the clip holds speech at all (a recording of room noise passes), and the
  bandwidth of a narrow-band clip that was upsampled before it reached Vocello. Silence and clipping
  are judged on the clip's first 30 seconds.

### 8.3 Identity and caching

A persisted clone prompt is valid only for the identity it was built under (the full key list is in
[ARCHITECTURE §4.8](../ARCHITECTURE.md#48-voice-cloning-cache)). Its speaker-feature version composes
the mel frontend version, the ICL reference-encode version and the MLX build
(`qwen-speaker-mel-v1+icl-ref-edges-trimmed-v4+mlx-swift-0.32.3`; `Qwen3TTSVoiceClonePrompt.swift:285-293`; F-06), so
an artifact built on an earlier MLX is rejected at load and rebuilt once from its reference.

- **The host's audio preparation is versioned** (G-13, fixed 2026-11-11, RF-51):
  `NativeAudioPreparationService.cloneReferencePreparationVersion` is folded into the reference's
  fingerprint, which keys the prepared file's name, the decoded-audio and prompt caches and the
  persisted prompt. Version 1 is the content digest earlier builds used, so nothing was invalidated;
  a change to preparation raises it, and each prompt is then rebuilt once.
- **Preparation was not reproducible until 2026-11-11** (found by running the clone screen against
  itself; RF-52). A reference that is not already 24 kHz mono 16-bit WAV was decoded and resampled
  by `AVAssetReader`, and that reader gives different samples from run to run: a 16 kHz WAV came out
  two ways, one sample apart in length, in three of five clips over twelve runs; an AAC file decoded
  three ways; a FLAC file came out 1,332 frames longer than it is. So one file enrolled twice can
  make two slightly different voices. Version 2 (`Resampling.singleCall`) decodes with
  `AVAudioFile` and resamples the whole clip with one `AVAudioConverter` call: the same samples
  every time, at the clip's exact length. The clone screen's recorded rule adopted it
  (`config/quality-screens.json`, `reference-preparation-v2`): two runs of it gave 190 identical
  takes of 190 where the old path gave 167 of 191, with no measurable cost in speaker similarity
  (-0.009, interval -0.025 to +0.006) or content errors (+0.003), and 22 ms more trailing silence
  on average (interval +6 to +40 ms, inside the rule's margin). Version 3 below keeps this
  resampling. `QWENVOICE_REFERENCE_PREPARATION=asset-reader` restores the old path in a
  diagnostics build.
- **Two channels are averaged** (version 3, the default since 2026-11-11), as upstream Qwen3-TTS
  (`librosa.load(mono=True)`, then `np.mean`) and the Python port (`ffmpeg -ac 1`) do. Versions 1
  and 2 mixed them as the sum over the square root of two, so a voice recorded on both channels came
  out 3 dB hotter than its source and clipped where it peaked above -3 dBFS. The `clone-stereo`
  screen (the clone screen's references saved as two-channel WAVs) adopted it under its rule
  `reference-mixdown-average`: speaker similarity +0.005 (interval -0.010 to +0.021), error rate
  +0.005 (-0.009 to +0.020), trailing silence +6 ms, gross failures 5 and 4. Not worse, and not
  shown better. A mono reference prepares to the same samples under versions 2 and 3, but its
  fingerprint changes, so every saved voice's prompt rebuilds once.
- **The codec encoder's implementation is still unversioned**, so the A-02 fix must add a version or
  saved voices keep their old reference codes (G-03, RF-52).

The in-memory clone prompt cache rarely helps today: every Clone take re-adopts the prompt from disk
before that cache is consulted (B-16, ER-06).

The device check for both conditioning modes, `scripts/ios_device.sh clone-conditioning`, is
described in [`telemetry-and-benchmarking.md`](telemetry-and-benchmarking.md) (§4.7b).

---

## 9. Generation parameters

### 9.1 Defaults

| Knob | Upstream `generation_config.json` | Vocello |
| --- | --- | --- |
| `do_sample` / `temperature` / `top_k` / `top_p` | true / 0.9 / 50 / 1.0 | same, for every take |
| `repetition_penalty` (talker codebook 0 only) | 1.05 | 1.05 |
| `subtalker_*` sampling | true / 0.9 / 50 / 1.0 | same, for every take |
| `max_new_tokens` | 8,192 | 2,048 |

Upstream's precedence is an explicit argument, then `generation_config.json`, then the wrapper's own
fallback (2,048; `model.generate` alone uses 4,096). Qwen's README examples and evaluation use 2,048
(RM L465), which is Vocello's fixed cap: 2,048 frames are 163.8 s of audio. Vocello's defaults are
`Qwen3GenerationConfiguration.officialQualityDefault`
(`Sources/QwenVoiceBackendCore/QwenVoiceBackendCore.swift:12-42`) and the contract's
`generationDefaults`.

### 9.2 One sampling for every take

Every take samples as the reference does (`Qwen3TalkerSamplingOverride.samplingConfiguration`,
`UnsafeSpeechGenerationModel.swift:101-146`):

| Stage | Temperature / top-p / top-k | Repetition penalty |
| --- | --- | --- |
| Talker | 0.9 / 1.0 / 50 | 1.05 |
| Subtalker (code predictor) | 0.9 / 1.0 / 50 | none |

Until 2026-11-12 a **take variation** setting could lower the talker: Balanced 0.8 / 0.95 and
Consistent 0.7 / 0.9 (and, until 2026-10-20, the subtalker with it). RF-58 retired it, with
Expressive, the reference, as the only sampling: the lower settings refused far more long-form
projects (18 of 32 under Consistent against 4 of 32 under Expressive; 8 of 32 even after a
Consistent segment sampled as Balanced, rule `long-form-consistent-talker`), RF-18's runaway
endings ran only under Consistent, and no measurement showed a benefit of either. Old settings,
plans and `--variation` arguments still decode, and the CLI warns that it samples as Expressive.
The internal-diagnostics knobs (`QWENVOICE_TALKER_*`, `QWENVOICE_SUBTALKER_*`) can still override
either stage for a screen.

### 9.3 Decoding

The talker's sampler (`Qwen3TTSSampling.swift:173-372`, called at `Qwen3TTS.swift:2679-2692`) runs in this order:

1. **Float32 logits.** Logits are cast to float32 before sampling, as the reference does (D3,
   production since 2026-10-13; `QWENVOICE_SAMPLER_FLOAT32=off` samples in the model's precision).
2. **Suppression.** Ids 2048–3071 are set to −∞ except EOS (`Qwen3TTS.swift:2342-2343`), and EOS stays
   suppressed until two frames exist (`productionMinimumGeneratedCodeTokensBeforeEOS`,
   `Qwen3TTS.swift:213`), matching upstream's `min_new_tokens=2`.
3. **Repetition penalty.** 1.05 over the talker's previously generated codebook-0 ids.
4. **Temperature**, then **top-k**, then **top-p** (temperature first, ported from mlx-audio
   `a730a68`). Min-p is 0 in production.
5. **EOS.** EOS is filtered like any other token (D2, production since 2026-10-20). With
   `QWENVOICE_TALKER_FILTER_EOS=off`, the older mlx-audio behavior returns: the EOS logit is re-inserted
   after the filters, and the engine labels the departure `reinserts_eos`.
6. A categorical draw from the request's own random state. The take ends at the first EOS or at the
   2,048-frame cap; a capped take ends as `maxTokens`, and its quality report records the cap.

The code predictor runs the same sampler with the subtalker stage, float32 logits, no suppression,
no EOS and no penalty; in production that stage is plain temperature and top-k, and since RF-46 it
runs inside the frame's one compiled function on keys the loop resolves from the request's random
state, drawing the same codes (`CompiledPassSampling`). The eager form serves the other stages and observed takes (`Qwen3TTS.swift:2792-2831`). Both production constants live in one value,
`.production = (fullTextConditioning: true, filtersEOS: true, float32Sampling: true)`, defined
twice and kept equal: `Qwen3ReferenceParity` in `Generation.swift` and `VocelloQwen3ReferenceParity`
in `Contracts.swift`. A long-form segment's request turns D1 off.

### 9.4 Text layout

How the target text reaches the talker is generation semantics. The token-level layouts are in the
[prompting guide §1](qwen3-tts-prompting-guide.md#1-the-wire-format).

- **Single takes** (Studio's Built-in Voice and Voice Design, streamed or not) lay the whole text up
  front, as upstream defaults `generate_custom_voice` and `generate_voice_design`
  (`non_streaming_mode=True`, WM L642, L738), and stream only the audio. **D1 was adopted for them
  on 2026-10-20** (RF-21, §11.2, §12).
- **Long-form segments and x-vector clones** use the streaming text layout: after the prefix, the
  text trails one token per codec frame, then `tts_pad` once it runs out (`Qwen3TTS.swift:2837-2843`).
  Text enters at 12.5 tokens/s against about 4–5 spoken, so an ~860-character segment's text is
  used up after about 16 s and the talker sees only `tts_pad` for the remaining ~40 s (A-01). RF-18's
  screen kept this layout for long-form segments.
- **ICL clones** use the non-streaming overlay (§8.1).

### 9.5 Seeds and reproducibility

Every request carries an effective seed (requested or random) and runs on its own MLX random state;
the sampling algorithm version is 2 (`Generation.swift:79-91`). Seeded takes are deterministic on one
build: a rerun of a fixed seed reproduced its PCM byte for byte in the RF-18 screens. A seed does not
reproduce takes across these changes (this list is the one the other guides link to):

- D3 float32 sampling (`c62390d6`, 2026-10-13, RF-14);
- the CONV-21 refresh to mlx-swift 0.32.3 (`57196483`, 2026-10-16), whose inverse-CDF categorical
  draws differently for Vocello's `[1, V]` logits (ml-explore/mlx#4177; F-02, accepted with a
  release-note line);
- RF-18's subtalker and EOS changes (`7a125aaf`, 2026-10-20), which change Balanced and Consistent
  takes most;
- RF-21's whole-script text layout for single streamed takes (`9cd075bd`, 2026-10-20, §9.4), which
  changes every streamed Built-in Voice and Voice Design take; long-form segments keep the
  trailing-text layout;
- RF-53's Consistent long-form talker (2026-11-12, rule `long-form-consistent-talker`), which
  sampled a long-form segment under Consistent at 0.8 / 0.95 and changed only those segments;
- RF-58's single sampling (2026-11-12), which retires Balanced and Consistent: a seed that ran
  under either now gives the Expressive take, and Expressive takes do not change.

The refresh also moved mlx-swift-lm to 3.32.3, swift-transformers to 1.3.5 and swift-huggingface to
1.0.0. The pins are in [`mlx-guide.md` §9.1](mlx-guide.md#91-current-pins) and the refresh's notes in
[§9.5](mlx-guide.md#95-what-the-0323-move-changed).
Since CONV-21, prewarm also draws once through the production sampler, with and without top-p, on a
private seed-0 state that no take reads, and discards the draws (`Qwen3TTS.swift:674-710`). The
sampler's kernels therefore compile during prewarm instead of in the first take, and no output
changes.

### 9.6 Streaming

`GenerationSemantics.appStreamingInterval` is 0.32 s, 4 codec frames, the same size as the
technical report's 4-token packet. Chunk policy, live preview and the preview knob are
[ARCHITECTURE §4.6](../ARCHITECTURE.md#46-streaming); every knob is registered in
`config/runtime-debug-knobs.json`.

### 9.7 Long-form

The long-form planner fills each segment up to a 300-unit budget (`LongFormPlanning.swift:131`; about
867 characters, about 60 s; C-02), and each segment is one streamed take, so long segments meet A-01's
text exhaustion. The RF-18 screens kept that budget: a 200-unit budget (C2) failed 15 of 56 projects
under Consistent against 9 for the control, so C-02 was not adopted. Consistent is retired (RF-58);
the long-form refusals left under Expressive, mostly in Chinese, Japanese and Korean, are RF-55's
subject (§11.2). Shipping behavior is in
[`long-form-generation.md`](long-form-generation.md).

---

## 10. Performance

### 10.1 Compute per frame

| Component | Work per 80 ms frame |
| --- | --- |
| Talker | 28 layers, one pass |
| Code predictor | 5 layers × 15 passes = 75 layer passes |
| **Transformer total** | **103 layer passes per frame, about 1,288 per second of audio**, before the decoder |
| Decoder | RVQ decode, 8 transformer layers, two ×2 upsamplers and the SEANet decoder over each chunk (fp32 weights) |

### 10.2 Latency

Qwen's numbers (technical report Table 2; internal vLLM with torch.compile and CUDA Graphs; a packet
is 4 tokens, 320 ms of audio):

| Model | First packet | RTF |
| --- | --- | --- |
| 12Hz-0.6B | 97 ms | 0.288 |
| 12Hz-1.7B | 101 ms | 0.313 |
| 25Hz-1.7B (never released) | 150 ms | 0.253 |

Measured on Vocello before the CONV-21 refresh (engine audit, section D): the iPhone 17 Pro's Speed
token loop ran at 24.7 tokens/s (RTF 0.55–0.59), and the M6 Mac at 50–52 tokens/s (RTF 0.27). The
refresh left RTF, memory and audio QC unchanged on the M6 and raised its warm first chunk from 146 to
155 ms ([mlx-guide §9.5](mlx-guide.md#95-what-the-0323-move-changed)). Memory policy per device is
[ARCHITECTURE §4.5](../ARCHITECTURE.md#45-memory-policy).

---

## 11. Failure catalogue

### 11.1 Upstream failure modes and their status in Vocello

From the research report [§5](../audits/2026-10-17-qwen3-tts-model-research.md#5-known-failure-modes),
updated for RF-18. The upstream readings in the clone, loop and number rows were corrected on
2026-11-11 against the [counter-verification review, §5](../audits/2026-11-11-qwen3-tts-quality-report-review.md#5-citations-that-do-not-hold).

| Symptom | Upstream reports | In Vocello |
| --- | --- | --- |
| Missing EOS, run-on, noise | QwenLM#118 (~0.5% of Base runs never emit EOS), #305 (5 minutes of noise on a cross-lingual year; a single report, run on vLLM-Omni), #258, #318; reproduced on official CUDA (VO#6158) | The 2,048-frame cap ends them as `maxTokens`. RF-18's runaway endings (the cap, or 10 s or more of terminal silence) ran only under Consistent: 3 in the control, 0 after the subtalker fix. VO#8569's budget and fresh-seed retry are ER-11 candidates |
| Truncated last words | #55 (Japanese and Korean), #181 (last two words), QD#161; MA#882 (fixed by removing EOS re-insertion) | D2 adopted 2026-10-20; it changed no Expressive take (§11.2) |
| Pace drift and long silences in long takes | #239 (rate climbs: text fed at 12.5 tokens/s against ~4–5 spoken), PR #362 (open and unreviewed, from an outside contributor: +16.7% with a 12.9 s reference in streaming, 0.0% non-streaming), #290 | A-01's streaming text layout (§9.4) is the leading mechanism; long-form segments keep it (RF-18) and single takes have the full text since RF-21; Consistent known limitation (§11.2) |
| ICL loops without EOS | MA#921, reported by one user on one clip and one text: on official PyTorch, 3 degenerate takes of 3 with a transcript covering about 6 s of a 10 s clip, and 5 normal takes of 5 with the full transcript | Fixed 2026-11-11 (G-01, RF-51): recognized text that does not reach both ends of the clip's audible span needs the user's edit, review or audio-only choice before it saves or conditions a take |
| Clone identity, accent leaks and echoes | #80 (about 20% wrong speaker, from one user in an all-English setup on vLLM-Omni; the cross-language remark in that issue is separate and unquantified). #134 (the source accent is kept across languages; user reports, no maintainer confirmation). #341 (clones whose output begins with the last words of the reference transcript, on the official PyTorch code at full precision; the author verified the trim arithmetic and supposed the model runs past the reference boundary; no maintainer answered; one commenter fixed one voice of six by cutting the reference's last phrase). #119, #200 (onset noise or stray syllable). #219 is withdrawn: it concerned a non-streamed Built-in Voice take, and its author found the WAV clean and the fault in an MP3 encoder's delay | Recorded references can end abruptly; since 2026-11-12 a transcript-backed reference's silent edges are trimmed and it is faded in and out before conditioning reads it (G-07, adopted by the clone screen's rule `reference-edges-trimmed`: no guard harmed, trailing silence 15 ms shorter, RF-52). #341 never mentions abrupt endings, so the link between them and echoes is Vocello's own unmeasured inference. Streamed clones decode after the reference's codes since A-04 was adopted (2026-11-12). Cross-language references are not flagged (G-16–21) |
| Numbers across languages | #68, #151, #305, #256, #328, QD#330. All five QwenLM issues were closed by the inactivity bot with no maintainer reply; #256 and #328 are misreadings, not wrong-language readings; #305 is a single report run on vLLM-Omni; none concerns abbreviations | The planner does not pre-normalize numbers |
| Accents and dialects | #134, #359, QD#230, #248 | Design accents and dialect control are suggestive only (§7.3) |
| Precision | #333 (NaN under FlashAttention-2), #355 (fp16 logit overflow) | D3: float32 sampling since 2026-10-13 |
| Fine-tuning | #179, #278, #337, #371 and others | Out of scope: Vocello ships no fine-tuning |

### 11.2 Vocello's known limitations

- **Consistent long-form takes stalled; the variation is retired (RF-58).** About one-minute
  segments under Consistent could pause for seconds or never reach end of speech, and Fast QC
  refused the segment. Every take samples as Expressive since 2026-11-12. The record that led there,
  RF-18's follow-up screen (pre-registered, Mac CLI on mlx-swift 0.32.3, 56 long-form projects per
  arm; engine audit [A2](../audits/2026-10-16-engine-runtime-audit.md#a2-rf-18-long-form-pacing-due-oct-22)):

  | Arm | Variation | Change | Failed projects of 56 | Runaway endings |
  | --- | --- | --- | --- | --- |
  | C0 | Consistent | none (control) | 9 | 3 |
  | C1 | Consistent | reference subtalker | 2 | 0 |
  | C2 | Consistent | planner budget 200 | 15 | 5 |
  | C4 | Consistent | EOS filtered (D2) | 7 | 2 |
  | E0 | Expressive | none (control) | 0 | 0 |
  | E2 | Expressive | planner budget 200 | 0 | 0 |
  | E4 | Expressive | EOS filtered (D2) | 0 | 0 |
  | C1 + C4 | Consistent | both shipped changes | 2 | 0 |

  C1 and D2 shipped together; C2 did not. E0 and E4 were byte-identical on all 56 projects, so the
  effect is C1's. The first RF-18 screen had already rejected D1: pooled, D1-on failed 3 of 23 long
  segments and D1-off 2 of 27, all under Consistent. The November long-form screen (projects of
  twenty sentences, Fast QC v10) still refused 18 of 32 Consistent projects, mostly for silent gaps
  past 2 s and slow delivery; sampling the talker as Balanced does (0.8 / 0.95) refused 8, with the
  error rate flat, and shipped for long-form segments on 2026-11-12 (rule
  `long-form-consistent-talker`, RF-53) until RF-58 retired the variation the same day. Under
  Expressive, East Asian long-form projects are still refused most (RF-55).
- **Single takes see their whole text (D1, adopted 2026-10-20, RF-21).** With the streaming text
  layout, a short take that opened with a sigh or a long pause could feed its whole script before
  speech started; the talker then saw only `tts_pad` and whispered or mumbled (a French take ran to
  35 s and Fast QC rejected it). RF-20's pre-registered screen (Mac CLI, Expressive, 251 takes per
  arm) favored full text: 5 gross failures against 10, sentence medians within 16%. Its first
  rule also required the Mac language bench to pass, and D1 garbled one Japanese bench take, so
  RF-20 declined it. The maintainer then had both ASR families score every saved screen take under a
  second pre-registered rule: wrong-content takes fell from 31 to 16 of 248 (19 against 34 failures
  with the rejections), with no language worse by two, and the maintainer adopted D1 for single
  takes. Two costs remain: Voice Design ends with a longer trailing pause (3 rejections for 1.2–1.5 s
  of terminal silence in 50 takes, none with streaming text), and the same seed no longer reproduces
  a take made before RF-21.
- **Clone references.** The gaps in §8.2 and §8.3. "Use audio only" on a saved voice with a
  transcript no longer conditions on that transcript (G-02, fixed 2026-11-11, RF-51).
- **No human listening for 3.0.** Machine screens catch gross failures only; subtle defects ship as a
  documented limitation ([v3.0.0 release notes](../releases/v3.0.0.md)).

### 11.3 Model limits Qwen states

- Base has no instruction support, because 12 Hz control is unstable (QwenLM#25).
- Voice Design gives a new voice on every sample (QwenLM#4).
- Emotive instructions can add laughter (QwenLM#16); non-verbal sounds come out only implicitly
  (QwenLM#9).
- Use fp32 where bf16 is unavailable (QwenLM#43).
- The unreleased 25 Hz model is the steadier one for long-form (technical report §4.2.6).

---

## 12. Parity ledger

Every verified place Vocello's runtime departs from Qwen's reference implementation (`qwen_tts` at
`022e286b98`, transformers 4.57.3), as of 2026-10-20, with the A-02 and precision measurements of
2026-11-11. The research report
[§8](../audits/2026-10-17-qwen3-tts-model-research.md#8-parity-ledger) carries the upstream citations.

| ID | Divergence | Upstream | Vocello | Status | Owner |
| --- | --- | --- | --- | --- | --- |
| D1 / A-01 | Text layout of streamed Custom and Design takes | whole text up front; audio streamed | the same for single takes; long-form segments trail one text token per frame, then `tts_pad` | **adopted for single takes** 2026-10-20 (RF-21, §11.2); long-form kept streaming by RF-18; `QWENVOICE_FULL_TEXT_CONDITIONING=off` restores trailing text, `=on` extends full text to long-form | ER-03 |
| D2 | EOS after top-k/top-p | filtered like any token | filtered | **adopted** 2026-10-20; `QWENVOICE_TALKER_FILTER_EOS=off` restores re-insertion | — |
| D3 | Sampling precision | float32 logits | float32 logits | **adopted** 2026-10-13 | — |
| — | Subtalker sampling | 0.9 / top-k 50 / top-p 1.0 for every request | same, for every take | **adopted** 2026-10-20 (RF-18's C1 arm) | — |
| D5 / A-04 | Decoder history for streamed clones | decodes reference plus generated codes, then trims | primed with the reference since 2026-11-12 | matches; adopted by `clone-decoder-history-primed-confirm`; the primed state is reused since A-26 | RF-52 |
| D6 | Custom with no detected language | `nothink`, no language id | English plus the English diction sentence | open, by design; `QWENVOICE_CUSTOM_AUTO_LANGUAGE=on` is the A/B arm | ER-05 |
| A-02 | Mimi encoder RoPE | `rotate_half` on permuted q/k weights | `traditional: true` | open; ships with G-03's version bump; measured 2026-11-11 with no detectable effect on clone output (below) | ER-04 |
| A-03 | Decoder attention | 72-frame window in all 8 layers; batch decode in 300-frame chunks with 25 of context | full causal; KV grows for the whole take | open | PA-16 |
| — | Encoder attention | full causal (the window applies only under FlashAttention-2) | full causal | matches; do not add the 250-frame window | PA-16 wording |
| A-11 | ICL target text | no separator after the reference text | none before a Han or kana target since 2026-11-12; one leading space otherwise (French first-word drops) | matches for Han and kana; adopted by the `clone-cjk` screen's rule `icl-target-space-unspaced-scripts`; `every-target` restores the space | RF-52 |
| A-12 | ICL reference padding | none | none since 2026-11-11 (`icl-ref-unpadded-v3`; 0.5 s of silence before) | matches; adopted by the clone screen's rule `reference-padding-none` | RF-52 |
| G-07 | Clone reference edges | taken as given | a transcript-backed reference trimmed at its silent edges (100 ms kept around its sound) and faded over 10 ms since 2026-11-12 (`icl-ref-edges-trimmed-v4`); audio-only taken as given | **adopted** by the clone screen's rule `reference-edges-trimmed`; `QWENVOICE_REFERENCE_EDGES=as-given` restores it as given | RF-52 |
| G-14 | ICL layout | streaming by default (PR #362, open and unreviewed, proposes non-streaming) | non-streaming overlay | deliberate | ER-03 |
| — | Repetition penalty scope | talker codebook 0 only | same | matches | — |
| — | Minimum frames before EOS; special-id suppression | 2; 2048–3071 except EOS | same | matches | — |
| — | Dialect speakers under Chinese or Auto | dialect language id | same | matches | — |
| — | Talker RoPE; decoder output | `rotate_half`; `clamp(-1, 1)` | same | matches | — |
| — | Token cap | 8,192 in the config; 2,048 in evaluation | 2,048 | deliberate (= evaluation) | — |
| — | Codec precision | bf16 in the README setup; the file is fp32 | fp32 | deliberate (an f16 codec opened streamed clone takes with a burst; withdrawn 2026-09-14) | — |
| — | Weights | bf16 | 4-bit or 8-bit affine, group 64, 8-bit text embedding | deliberate; never evaluated upstream; in the 2026-11-11 pre-screen 8-bit clones match the reference speaker better than 4-bit ones by 0.025 (§2.3) | — |

**A-02, measured on 2026-11-11** ([review §4.1](../audits/2026-11-11-qwen3-tts-quality-report-review.md#41-the-encoders-rotary-convention-a-02)).
The finding stays open, and its effect is no longer unmeasured:

- **The divergence is real.** The Hugging Face conversion script permutes the rows of the q and k
  projections for split-half rotary (verified upstream on 2026-11-11), Qwen runs that code, and
  Vocello's encoder applies the adjacent-pair form.
- **The stored codes differ.** The Swift encoder's stored codes match the reference encoder's on
  31% of codes. They match an emulation of the adjacent-pair rotary on 96.8%, and on 100% of the
  first codebook.
- **Both code sets decode equally close to the input:** speaker similarity 0.983 for the
  reference codes against 0.981.
- **Clone output does not change detectably.** A pre-screen in the Python port (English, clean
  references, 96 paired clones) found +0.004 speaker similarity for the fix (95% interval -0.003
  to +0.011) and an identical word error rate.
- **Upstream ports.** mlx-audio's commit `6549fc2` added the encoder with the correct setting from
  the start; it did not fix a measured defect. mlx-audio-swift `main` still has the wrong
  convention.

The pre-screen does not cover other languages, cross-language or noisy references, long targets or
the Swift runtime. The fix is for parity, with G-03's version bump, and no audible change is
expected from it.

The audit's A-06 and A-07 are D2 and D6. One constraint follows from D1 (A-05): a talker KV window
would evict the unspoken script under the streaming text layout, so a window is allowed only with a
full-text layout.

Everything else the audit compared matched: the chat template, the talker, the code predictor, the
sampler order, the streaming decoder's conv state, the codec math, the speaker encoder and the
quantized load. Ports and fixes in mlx-audio, mlx-audio-swift and vLLM-Omni since Vocello's fork are
in the research report [§6](../audits/2026-10-17-qwen3-tts-model-research.md#6-ports-and-changes-since-the-fork).

---

## 13. Source-of-truth files

| File | What it owns |
| --- | --- |
| `Sources/Resources/qwenvoice_contract.json` | Models, variants, repositories and revisions, capabilities, tokenizer profile, generation defaults, speaker roster |
| `Sources/QwenVoiceBackendCore/QwenVoiceBackendCore.swift` | `Qwen3GenerationConfiguration` defaults and the upstream provenance |
| `Sources/QwenVoiceCore/UnsafeSpeechGenerationModel.swift` | Request sampling: the reference's stages, the diagnostics knobs and reference-parity arms |
| `Packages/VocelloQwen3Core/Sources/MLXAudioTTS/Generation.swift`, `…/VocelloQwen3Core/Contracts.swift` | `Qwen3ReferenceParity.production` and the sampling policy types |
| `Packages/VocelloQwen3Core/Sources/MLXAudioTTS/Models/Qwen3TTS/Qwen3TTS.swift` | Prefill, the generate loop, the sampler, clone prompts, prewarm |
| `Packages/VocelloQwen3Core/Sources/MLXAudioTTS/Models/Qwen3TTS/Qwen3TTSTalker.swift`, `Qwen3TTSCodePredictor.swift`, `Qwen3TTSConfig.swift` | Talker, code predictor and config defaults |
| `Packages/VocelloQwen3Core/Sources/MLXAudioTTS/Models/Qwen3TTS/Qwen3TTSSpeechTokenizer.swift`, `…/MLXAudioCodecs/Mimi/Transformer.swift` | The 12 Hz tokenizer's decoder and encoder |
| `Sources/QwenVoiceCore/GenerationSemantics.swift` | Prompt assembly, language selection, the diction sentence, prompt validation |
| `Sources/QwenVoiceCore/NativeCloneSupport.swift` | Clone references: transcript resolution, warnings, prompt caching |
| `Sources/QwenVoiceCore/EmotionPreset.swift` | The eight delivery presets |
| `config/runtime-debug-knobs.json` | Every diagnostics knob named here |

---

## 14. External references

- Qwen3-TTS repository: https://github.com/QwenLM/Qwen3-TTS (reviewed at `022e286b98`, 2026-03-17)
- *Qwen3-TTS Technical Report*, arXiv:2601.15621
- Vocello's research and its sources: [`2026-10-17-qwen3-tts-model-research.md`](../audits/2026-10-17-qwen3-tts-model-research.md)
- Vocello's pinned MLX conversions: https://huggingface.co/PowerBeef02
- Mimi codec (Kyutai): https://kyutai.org/codec-explainer; paper: Moshi, arXiv:2410.00037
- **Not authoritative:** the official Hugging Face demo Space (it bundles pre-February tokenizer code
  with the old transposed-conv trim and length rule), the Mintlify "documentation site" (no publisher,
  not linked by Qwen), and the community MODEL.md write-up, whose RoPE, tanh, 4,096-codebook and
  25 Hz claims are wrong
