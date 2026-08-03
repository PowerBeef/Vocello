---
status: active
owner: backend-mlx
summary: Qwen3-TTS architecture reference — model variants, tokenizer profile, Talker/decoder, speaker roster, generation modes, and parameters.
sourceOfTruth:
  - Sources/Resources/qwenvoice_contract.json
  - Sources/QwenVoiceCore/EmotionPreset.swift
  - Sources/QwenVoiceCore/GenerationSemantics.swift
appliesTo:
  - backend-mlx
---

# Qwen3-TTS Reference Guide

A living reference for the Qwen3-TTS models that power Vocello (formerly QwenVoice). This document covers the model architecture, the three generation modes, the built-in speaker roster, emotion/delivery control, voice cloning, language handling, generation parameters, and the practical behaviors we have observed in the Swift + MLX implementation.

**When to update this file**

- Whenever `Sources/Resources/qwenvoice_contract.json` gains or changes a model variant, speaker, or generation default.
- Whenever `EmotionPreset.swift`, `GenerationSemantics.swift`, `NativeCloneSupport.swift`, or `VoiceDesignBriefCatalog.swift` change the prompt contract, preset copy, clone pipeline, or design briefs.
- Whenever we move the pinned `mlx-community` revisions or quantization tiers.
- Whenever benchmarking reveals new quality/latency/artifact behaviors.

**Source-of-truth hierarchy**

1. `Sources/Resources/qwenvoice_contract.json` — model IDs, repos, revisions, variants, tokenizer profile, generation defaults.
2. `Sources/QwenVoiceCore/*.swift` — runtime prompt construction, speaker/language logic, clone conditioning, preset definitions.
3. `Sources/SharedSupport/Services/VoiceDesignBriefCatalog.swift` — voice-design brief copy and limits.
4. This document and `docs/reference/mlx-guide.md` (for MLX/performance details).
5. Official Qwen3-TTS docs / paper (linked at the end).

---

## 1. What Qwen3-TTS is

Qwen3-TTS is an open-weights text-to-speech family from Alibaba Cloud's Qwen team. It is built around a single neural audio tokenizer (a Mimi-style RVQ codec) and an autoregressive "Talker" language model. The same family supports three distinct usage patterns:

- **Custom Voice** — 9 built-in preset speakers with optional natural-language style instructions.
- **Voice Design** — describe a voice in plain text and synthesize speech in that voice.
- **Voice Cloning** — clone a speaker from a short reference audio clip (≈3 s is enough; 10–20 s is the sweet spot).

All three patterns generate **24 kHz mono PCM**. Vocello ships only the **12 Hz tokenizer** variant; the faster 25 Hz variant mentioned in the technical report is not used.

---

## 2. Model families and variants

Vocello bundles three model families, each from the `mlx-community` Hugging Face organization and pinned to a specific revision in `qwenvoice_contract.json`.

| Family (mode) | Folder suffix | MLX repo suffix | Size | Platforms | Notes |
| --- | --- | --- | --- | --- | --- |
| **Custom Voice** (`custom`) | `…-CustomVoice-8bit` | `…-CustomVoice-8bit` | 1.7B | macOS only | Quality tier; supports instruction control. |
| **Custom Voice** (`custom`) | `…-CustomVoice-4bit` | `…-CustomVoice-4bit` | 1.7B | iOS + macOS | Speed tier; instruction control. |
| **Voice Design** (`design`) | `…-VoiceDesign-8bit` | `…-VoiceDesign-8bit` | 1.7B | macOS only | Quality tier; text-described voices. |
| **Voice Design** (`design`) | `…-VoiceDesign-4bit` | `…-VoiceDesign-4bit` | 1.7B | iOS + macOS | Speed tier; text-described voices. |
| **Voice Cloning** (`clone`) | `…-Base-8bit` | `…-Base-8bit` | 1.7B | macOS only | Quality tier; requires speaker encoder. |
| **Voice Cloning** (`clone`) | `…-Base-4bit` | `…-Base-4bit` | 1.7B | iOS + macOS | Speed tier; requires speaker encoder. |

- **8-bit = Quality**, **4-bit = Speed**. macOS defaults to Quality unless the device is in the `floor8GBMac` memory class, in which case Speed is selected. iOS always uses the Speed variant.
- Qwen3-TTS also publishes **0.6B** checkpoints. Vocello currently pins only the **1.7B** variants.
- `supportsInstructionControl` is `true` for Custom Voice and Voice Design, `false` for the Base clone model.
- `supportsXVectorOnlyClone` is explicitly `true` only for the Base clone model; audio-only
  cloning fails before model preparation if a future checkpoint does not declare it.
- `requiresSpeakerEncoder` is `true` only for the clone model.

---

## 3. Architecture

The pipeline has four parts. All numbers below are for the **1.7B** variant unless noted.

```text
Text  →  Qwen BPE tokenizer  →  Text embedding + projection  →  Talker (28-layer transformer)
                                                                        ↓
                                                           Codebook-0 / semantic token per frame
                                                                        ↓
                                              Code Predictor (5 layers × 15 passes) → codebooks 1-15
                                                                        ↓
                                              16 discrete codes per 80 ms frame
                                                                        ↓
                                              Speech Tokenizer Decoder (Mimi-style RVQ) → 24 kHz PCM
```

### 3.1 Audio representation (tokenizer profile)

The canonical profile is defined once per model capability block in `qwenvoice_contract.json`:

| Parameter | Value |
| --- | --- |
| Sample rate | 24,000 Hz |
| Frame rate | 12.5 Hz (80 ms per frame) |
| Decoder quantizers | 16 |
| Encoder valid quantizers | 16 |
| Encoder configured quantizers | 32 (training config; inference uses 16) |
| Per-quantizer codebook size | 2,048 |
| Semantic codebook size (contract) | 4,096 |
| Effective bitrate | ~2.1 kbps |
| Compression ratio | ~183× vs. 16-bit 24 kHz PCM (~366× vs. float32 PCM). The `decodeUpsampleRate` is 1,920 (24,000 / 12.5). |

Each frame is therefore a vector of 16 integers in `[0, 2047]`. The first codebook carries the most semantic content; later codebooks add prosody, speaker identity, and acoustic residuals.

### 3.2 Talker (main LM)

| Parameter | 1.7B | 0.6B |
| --- | --- | --- |
| Text hidden size | 2,048 | 2,048 |
| Talker hidden size | 2,048 | 1,024 |
| Layers | 28 | 28 |
| Attention heads | 16 | 16 |
| KV heads (GQA) | 8 | 8 |
| Head dimension | 128 | 128 |
| Q dimension (heads × head dim) | 2,048 | 2,048 |
| Intermediate FFN size | 6,144 | 3,072 |
| Position encoding | M-RoPE, θ = 1e6, interleaved | same |
| M-RoPE section | `[24, 20, 20]` | `[24, 20, 20]` |
| Norm | RMSNorm (ε = 1e-6) | same |
| Activation | SwiGLU (SiLU) | same |
| Text projection | SiLU MLP: 2,048 → 2,048 → hidden size | same |

Key implementation details:

- Q and K are **per-head RMSNorm'd** before RoPE.
- RoPE is **interleaved** (adjacent pairs), not NeoX split-half.
- For TTS, all three M-RoPE position dimensions are identical, so it behaves like standard RoPE.
- The Talker predicts tokens from a separate **codec vocabulary** of size 3,072, not the text vocabulary.

Special token IDs (codec vocabulary):

| Token | ID |
| --- | --- |
| `codec_pad` | 2,148 |
| `codec_bos` | 2,149 |
| `codec_eos` | 2,150 |
| `think` | 2,154 |
| `no_think` | 2,155 |

Language IDs are also codec-vocabulary tokens, e.g. English = 2,050, Chinese = 2,055. Vocello's `Qwen3SupportedLanguage` enum maps these at runtime.

### 3.3 Code Predictor (multi-token prediction)

A 5-layer transformer that runs **15 sequential passes** per frame to predict codebooks 1 through 15, conditioned on the Talker's hidden states and previously predicted codebook tokens. Each pass has its own embedding and head:

- `talker.code_predictor.model.codec_embedding.{g}` for g = 0…14
- `talker.code_predictor.lm_head.{g}` for g = 0…14

This means ~103 layer evaluations per 80 ms frame (28 Talker + 75 Code Predictor + decoder), or roughly **1,288 layer evaluations per second of output audio**.

### 3.4 Speech Tokenizer Decoder

A Mimi-based neural codec decoder that converts the 16-code frames back to a 24 kHz waveform. It is causal and streaming-friendly:

- 8 pre-transformer layers
- 7 convolutional decoder blocks with Snake activation
- 2 ConvNeXt upsampling blocks
- Final tanh → float samples in `[-1, 1]`

All speech-tokenizer weights are shipped as **F32**, even when the Talker is quantized to 4/8 bit.

### 3.5 Speaker encoding (voice cloning)

There are **no separate speaker embedding tensors**. In Custom Voice, the 9 speakers are represented as tokens in the codec vocabulary (e.g. `serena` maps to a specific codec ID). In Voice Cloning, a small speaker-encoder network consumes the reference audio and produces a reusable `Qwen3TTSVoiceClonePrompt` that conditions the Base model at inference time.

---

## 4. Built-in speakers

The 9 preset speakers are defined in `Sources/Resources/qwenvoice_contract.json`. Each has a native language and a short description. The model-specific config (`talker_config.spk_id`) is the runtime source of truth for which speakers a checkpoint actually supports.

| ID | Display name | Native language | Description |
| --- | --- | --- | --- |
| `aiden` | Aiden | English | Sunny American male voice with a clear midrange. |
| `ryan` | Ryan | English | Dynamic male voice with strong rhythmic drive — naturally expressive. |
| `vivian` | Vivian | Chinese | Bright, slightly edgy young female voice. |
| `serena` | Serena | Chinese | Warm, gentle young female voice. |
| `uncle_fu` | Uncle Fu | Chinese | Seasoned male voice with a low, mellow timbre. |
| `dylan` | Dylan | Chinese (Beijing dialect) | Youthful Beijing male voice with a clear, natural timbre. |
| `eric` | Eric | Chinese (Sichuan dialect) | Lively Chengdu male voice with a slightly husky brightness. |
| `ono_anna` | Ono Anna | Japanese | Playful Japanese female voice with a light, nimble timbre. |
| `sohee` | Sohee | Korean | Warm Korean female voice with rich emotion. |

- The default speaker is `aiden`.
- Speaker quality is best when the target text is in the speaker's native language, but all speakers can generate any of the 10 supported languages.

---

## 5. Generation modes

> Prompt-writing depth for all three modes — what each text surface does, how the modes differ in
> what conditioning they accept, and which claims are sourced — lives in
> [`qwen3-tts-prompting-guide.md`](qwen3-tts-prompting-guide.md).

### 5.1 Custom Voice

Use a built-in speaker and optionally steer delivery with a natural-language instruction.

```swift
Qwen3PromptAssembly(
    mode: .customVoice,
    text: "Hello, welcome to Vocello.",
    language: "english",
    instruct: "Speak happily and energetically.",
    speakerID: "aiden"
)
```

- Instruction control is **only available on the 1.7B CustomVoice model**. The 0.6B model (not shipped in Vocello) does not support it.
- For English text, `GenerationSemantics` appends a diction-reinforcement clause (`Native English pronunciation with clear English diction and natural stress.`) unless the feature is disabled via the debug-gated `QWENVOICE_ENGLISH_DICTION_REINFORCEMENT=off` diagnostic override. The append is suppressed when the instruction already asks for clarity, and that decision resolves **preset-wide**: if any intensity tier of a preset contains a diction word, every tier of that preset suppresses. Resolving per string instead let a preset's two tiers differ by 76 characters of boilerplate that says nothing about intensity, confounding normal-versus-strong comparisons (fixed 2026-08-02; `scripts/check_delivery_instructions.py` fails the build if it returns). Free-form user instructions still resolve per string.
- Celebrity imitation / voice impersonation instructions are rejected by `validateQwenPromptContract`.

### 5.2 Voice Design

Describe the voice in plain text; the model samples a new voice matching the description.

```swift
Qwen3PromptAssembly(
    mode: .voiceDesign,
    text: "The quick brown fox jumps over the lazy dog.",
    language: "english",
    instruct: "Voice character: A deep, low-pitched male narrator, warm and bass-resonant. Delivery: Calm and soothing.",
    speakerID: nil
)
```

- Voice Design is **1.7B only**.
- The brief (voice description) is limited to **500 characters** in the UI (`VoiceDesignBriefCatalog.descriptionLimit`).
- There is **no fixed speaker ID**. Each call samples a fresh voice, so consistency across sessions requires the **design-then-clone** workflow (see below).
- Effective descriptions are concrete and acoustic: name gender, age, pitch register, pace, timbre, emotion, and use-case. Avoid abstract persona-only prompts.
- Accent/dialect hints are flavor, not guarantees.

### 5.3 Voice Cloning

Clone from a reference audio clip.

```swift
Qwen3PromptAssembly(
    mode: .voiceClone,
    text: "Hello, this is my cloned voice.",
    language: "english",
    instruct: nil,          // Base model ignores instructions
    refText: "Reference transcript.",
    speakerID: nil
)
```

- Requires the **Base** model and the speaker encoder.
- A transcript (`refText`) improves quality but is optional. Vocello also accepts a sidecar `.txt`
  file next to the reference audio. Inline or sidecar text selects typed transcript-backed ICL
  conditioning; absent, empty, or whitespace-only text selects true speaker-embedding-only
  x-vector conditioning rather than falling back to Voice Design.
- The Base model **does not follow delivery/emotion instructions**. To get a styled clone, use **design-then-clone**: generate a styled reference clip with Voice Design, build a clone prompt from it, then generate with the Base model using that prompt.

### 5.4 Design-then-clone workflow

This is the recommended way to create a reusable, styled character voice:

1. Use **Voice Design** to synthesize a short reference clip that matches the desired persona and delivery.
2. Call `createVoiceClonePrompt(refAudio:refText:)` to build a reusable `Qwen3TTSVoiceClonePrompt`.
3. Use the Base model's `generate_voice_clone(voice_clone_prompt=...)` for all subsequent lines.

Vocello caches the resulting clone prompt on disk and in memory to avoid recomputing it for every generation.
The speaker encoder uses Qwen's own 24 kHz magnitude-mel frontend rather than the generic
Whisper-style mel helper: reflect padding, periodic Hann, 1024-point FFT, 256-sample hop, 128
Slaney-scale/Slaney-normalized bands, and natural-log scaling. Embeddings must be finite
`float32 [1, D]` tensors matching the decoded encoder and talker dimensions.

For a focused physical-device semantic check, `scripts/ios_device.sh clone-conditioning` runs the
canonical saved reference twice in one process: first with its explicit transcript and prepared
voice identity, then through an exact purpose-owned audio copy with no sidecar and no prepared voice
identity. The compile-gated runner requires `transcript_backed` and `x_vector_only` runtime flags,
distinct prompt-assembly digests, exact output/telemetry evidence, and cleanup of the temporary
audio-only copy. This local acceptance command does not publish benchmark history and does not
replace the XCUITest UI path for the visible saved-voice workflow.

---

## 6. Delivery / emotion presets

`Sources/QwenVoiceCore/EmotionPreset.swift` defines the single source of truth: **8 presets**, each
shipping one instruction. Neutral is itself a real instructed preset (steady, slightly monotone).

The user-facing **intensity control was retired 2026-08-02**, following the "subtle" tier on
2026-08-01. Both went for the same reason and by the same test — a control whose effect cannot be
verified is not a control. DP-3 measured the `strong` copy at nearly double the recognisability of
`normal` (mean per-preset recall 0.278 against 0.157, chance 0.053) while showing the two tiers are
not separable from each other: for five presets the nearest cell in the whole space is its own other
tier, seven of nine moved *less* at strong than at normal, and dramatic reversed outright. Every
preset therefore ships its strong copy.

`EmotionIntensity` survives internally, addressing both texts, so the delivery matrix harness can
keep running the queued experiments and drafts saved before the change resolve to exactly what they
stored. The table below is that internal pair; the second column is what ships.

| Preset | normal | strong |
| --- | --- | --- |
| `neutral` | Neutral (steady, slightly monotone) | same |
| `happy` | Happy and upbeat, smiling | High pitch, loud, fast, bright, without laughing |
| `sad` | Heavy, restrained, lowered pitch | Fragile, tearful, slow, clear words |
| `angry` | Firm, sharp consonants | Forceful tension, not screaming |
| `fearful` | Anxious, breath caught | Trembling panic, still audible |
| `surprised` | Pitch jumps, quick, astonished | High rising pitch, amazed, no gasping |
| `whisper` | Hushed, breathy, confidential | Urgent, barely voiced, secretive |
| `calm` | Smooth, unhurried, reassuring | Serene, meditative stillness |

> `narrator` and `news` are Voice Design brief archetypes, not delivery presets.

Prompt-writing lessons baked into the preset copy. These were written without citations; each was
sourced or retracted on 2026-08-02, and [`qwen3-tts-prompting-guide.md`](qwen3-tts-prompting-guide.md) §9
carries the full adjudication with references. Summary:

- **Concrete acoustic wording** (pitch, pace, timbre, volume) is followed more reliably than persona-only wording. *Supported* — InstructTTSEval scores our checkpoint at 77–83 on explicit acoustic specification versus 61–64 on role-play framing.
- **Negative constraints work** (`"joyful but without laughing"`). *Unverified* — no upstream source endorses them, and the nearest published ablation found bare paralinguistic tags reduced adherence.
- **Stacked intensifiers do not work** (`"very very very happy"` adds no value). *Partly contradicted* — repetition adding nothing is defensible, but upstream's own examples are `"Very happy."` and `"Say it in a very angry and disappointed tone"`.
- High-arousal instructions (`happy`, `surprised`) can otherwise trigger literal laughter or extra breath sounds; the shipped copy explicitly forbids that. *Symptom is community-reported; the remedy is the unverified part.*
- An intelligibility clause (`"keeping every word audible"`) helps bound extreme emotions. *Unverified as written* — the vendor-documented cousin is a closing recording-quality anchor, which is a different mechanism.

---

## 7. Language handling

### 7.1 Supported languages

`Qwen3SupportedLanguage` enumerates 10 languages plus `auto`:

`chinese`, `english`, `japanese`, `korean`, `german`, `french`, `russian`, `portuguese`, `spanish`, `italian`.

### 7.2 Language hint selection

`GenerationSemantics.qwenLanguageHint(for:resolvedCloneTranscript:)` decides which language token is sent to the model:

- **Custom Voice**: detect from the target text; fall back to `english`.
- **Voice Design**: detect from the target text; fall back to `auto`.
- **Voice Clone**: detect from the resolved transcript if available, otherwise from the target text; fall back to `auto`.

Detection order:

1. Japanese kana → `japanese`
2. Hangul → `korean`
3. Cyrillic → `russian`
4. CJK → `chinese`
5. Latin script → `PromptLanguageDetector` (NLLanguageRecognizer) to disambiguate French/German/Spanish/Portuguese/Italian/English; if confidence is too low, `auto`.

Official guidance: **explicit language tokens outperform `auto`**. Vocello therefore tries to detect and only falls back to `auto` when ambiguous.

**Unit tests:** `Tests/VocelloCoreTests/` covers `Qwen3SupportedLanguage.normalized`, `PromptLanguageDetector`, `LanguageSelectionPresentation`, and the `qwenLanguageHint` matrix. Run on macOS with `scripts/macos_test.sh core-test` (also step 3 of `scripts/macos_test.sh gate`).

**Headless hint bench (Phase 2):** `config/language-bench-matrix.json` + `scripts/ios_device.sh lang-bench` (device) or `scripts/macos_test.sh lang-bench` (CLI). Gated by `scripts/check_language_hints.py` on `notes.languageHint`.

**Output round-trip (Phase 3, iOS device only):** the same fixed-seed matrix retains and
revalidates the exact generated WAV, then runs three sequential locale-locked on-device Speech
passes. `scripts/check_language_output.py` requires exact transcript consensus and independently
recomputes the primary edit metric against the tracked corpus: WER for word-delimited languages or
CER for Chinese and Japanese, with a `0.15` maximum in either case. Requires on-device Speech assets
for non-EN/FR locales (iOS Settings → dictation languages + Wi-Fi download). See
[`language-bench.md`](language-bench.md).

### 7.3 Dialects and accents

- Two built-in speakers carry Chinese dialect hints: `dylan` (Beijing) and `eric` (Sichuan/Chengdu).
- Voice Design prompts can request accents, but the model treats them as suggestions, not guarantees.
- Cross-lingual generation works (e.g. an English-native speaker speaking Chinese), but native-language combinations usually sound most natural.

---

## 8. Voice cloning pipeline

Implemented in `Sources/QwenVoiceCore/NativeCloneSupport.swift`.

1. **Reference normalization**
   - Compute a SHA-256 fingerprint of the source file.
   - Convert to canonical 24 kHz mono WAV if needed.
   - Mirror a sidecar `.txt` transcript if present.
   - Cache the normalized result with LRU eviction.

2. **Transcript resolution**
   - Inline transcript from the UI/CLI.
   - Else sidecar `<audio>.txt`.
   - Else `nil` (the model can still clone from audio alone, but quality drops).

3. **Reference decoding**
   - Load the normalized WAV into an `MLXArray` at the model's sample rate.
   - Cache the decoded array.

4. **Quality warnings**
   `referenceQualityWarnings` checks the normalized reference and returns tokens:

   | Token | Meaning | Severity |
   | --- | --- | --- |
   | `reference_duration_short` | < 10 s | Soft warning |
   | `reference_duration_long` | 30–60 s | Soft warning |
   | `reference_duration_excessive` | > 60 s | **Hard block** — voice cannot be kept |
   | `reference_sample_rate_noncanonical` | Not 24 kHz | Soft warning |
   | `reference_channels_noncanonical` | Not mono | Soft warning |
   | `reference_near_silence` | RMS < 0.0005 | Soft warning |
   | `reference_possible_clipping` | Peak ≥ 0.98 | Soft warning |
   | `reference_quality_unreadable` | Could not read file | Soft warning |

   The recommended reference window is **10–20 seconds of clean speech**.

5. **Clone prompt creation**
   - A resolved transcript calls
     `createVoiceClonePrompt(refAudio:refText:xVectorOnlyMode: false)` and produces ICL reference
     codes plus a speaker embedding.
   - No resolved transcript calls
     `createVoiceClonePrompt(refAudio: referenceAudio, refText: nil, xVectorOnlyMode: true)` and
     produces a speaker-embedding-only prompt.
   - Priming and direct generation consume the same typed prompt. The prompt is cached in memory
     and persisted under `voicesDirectory`, keyed by model ID, reference fingerprint,
     conditioning mode, language, transcript hash when present, pinned model revision, artifact
     version, installed integrity-manifest digest, runtime profile, and speaker-feature algorithm
     version. Changed weights or a frontend/runtime change invalidates both cache tiers.
   - Re-use the same prompt across multiple generations to avoid recomputing speaker features.

---

## 9. Generation parameters

The runtime defaults are a stack of three layers:

1. **Checkpoint defaults** (`generation_config.json`): `max_new_tokens = 8192`.
2. **Wrapper fallback** (`Qwen3GenerationConfiguration.wrapperFallbackMaxNewTokens`): 2048.
3. **App policy** (`qwenvoice_contract.json` / `Qwen3GenerationConfiguration.officialQualityDefault`): 2048.

Vocello's effective defaults:

| Parameter | Value | Source |
| --- | --- | --- |
| `max_new_tokens` | 2048 | App policy |
| `temperature` | 0.9 | App policy |
| `top_k` | 50 | App policy |
| `top_p` | 1.0 | App policy |
| `do_sample` | true | App policy |
| `repetition_penalty` | 1.05 | App policy |

The **Code Predictor** inherits the effective Talker sampling policy by default. Vocello can apply
independent subtalker overrides when they are explicitly configured; it is not unconditionally
greedy. This keeps the default residual-codebook sampling aligned with the public generation
policy while preserving a typed override surface for controlled experiments.

Streaming:

- `appStreamingInterval = 0.32` s (configurable, used to batch decoder output into user-facing chunks).
- PCM preview data is emitted by default on both platforms. A preview-policy environment override is
  production-affecting and therefore inert unless the `QWENVOICE_DEBUG` master gate is enabled.

`config/runtime-debug-knobs.json` is the exhaustive authority for these environment surfaces. Never
add a behavior-changing reader outside `RuntimeDebugGate` or describe a debug-gated override as
shipped product policy.

---

## 10. Performance and memory

For Apple Silicon-specific optimization guidance (Metal, unified memory, KV cache, quantization, `eval`/streaming, MLX cache clearing) see [`mlx-guide.md`](./mlx-guide.md). This section covers Qwen3-TTS-specific numbers.

### 10.1 Compute budget

At 12.5 frames per second of audio:

| Component | Evaluations per frame | Notes |
| --- | --- | --- |
| Talker | 28 layers × 1 pass | Q/K RMSNorm, M-RoPE, GQA 2:1 |
| Code Predictor | 5 layers × 15 passes | One pass per residual codebook |
| Speech decoder | 8 pre-transform + 7 conv + 2 upsample | F32 weights; smaller matrices |
| **Total** | **~103 layer evals/frame** | ~1,288 layer evals/second of audio |

### 10.2 Latency

Official reference numbers (CUDA, torch.compile, CUDA Graph):

| Model | First-packet latency | RTF (real-time factor) |
| --- | --- | --- |
| 0.6B | ~97 ms | — |
| 1.7B | ~101 ms | 0.313 |

Apple Silicon MLX numbers depend heavily on quantization tier, model size, text length, and memory pressure. Use Vocello's built-in telemetry (`QWENVOICE_NATIVE_TELEMETRY_MODE=verbose`) to capture per-generation memory curves.

### 10.3 Variant selection and memory classes

`ModelDescriptor.preferredVariant` selects:

- **iOS**: Speed (4-bit).
- **macOS 8 GB**: Speed (4-bit) to stay within the `floor8GBMac` memory policy.
- **macOS 16 GB+**: Quality (8-bit) by default.

Model download sizes (approximate, from `qwenvoice_contract.json`):

- 4-bit: ~2.3 GB
- 8-bit: ~3.1 GB

---

## 11. Known limitations and behaviors

These are compiled from the official docs, community reports, and Vocello's own QA pass.

- **No instruction control on Base clone model.** If you need a styled clone, use design-then-clone.
- **Voice Design has no fixed speaker.** Each call samples a fresh voice; reuse requires building a clone prompt.
- **Accent/dialect control is suggestive, not deterministic.** It works better for broad language-native speakers than for fine-grained regional accents.
- **Conflicting descriptions fail.** `"high-pitched deep bass voice"` will produce unpredictable results.
- **High-arousal emotions can add sounds.** The preset copy explicitly forbids laughing/gasping in strong tiers.
- **Reference audio sweet spot is 10–20 s.** Shorter clips work (the paper claims 3 s rapid clone) but may be less consistent. Over 60 s is blocked.
- **Music and noise are not the model's strength.** The tokenizer is optimized for clean speech; noisy or musical references degrade.
- **Celebrity/voice impersonation requests are rejected** by the prompt validator.
- **Long outputs can hit the 2048-token app cap.** If generation truncates, the finish reason will be `max_tokens`.
- **Latin-script language detection can be ambiguous.** When in doubt, set the language explicitly in the UI.
- **25 Hz checkpoints exist** but Vocello does not ship them; this guide covers only the 12 Hz tokenizer.

---

## 12. Source-of-truth files

| File | What it owns |
| --- | --- |
| `Sources/Resources/qwenvoice_contract.json` | Model list, variants, repos/revisions, tokenizer profile, generation defaults, speaker roster. |
| `Sources/QwenVoiceCore/EmotionPreset.swift` | 10 emotion/delivery presets × 2 intensity tiers, and their instruction copy. |
| `Sources/QwenVoiceCore/GenerationSemantics.swift` | Prompt assembly, language hint logic, English diction reinforcement, prompt validation. |
| `Sources/QwenVoiceCore/NativeCloneSupport.swift` | Reference normalization, transcript resolution, clone prompt caching, quality warnings. |
| `Sources/QwenVoiceCore/Qwen3TTSRuntimeProfile.swift` | Runtime model-family detection, capability validation, generation-defaults parsing. |
| `Sources/QwenVoiceCore/SemanticTypes.swift` | Languages, modes, tokenizer profile structs, model capabilities. |
| `Sources/SharedSupport/Services/VoiceDesignBriefCatalog.swift` | Voice Design brief copy, description limit, starting-point archetypes. |
| `docs/reference/mlx-guide.md` | Apple Silicon / MLX performance and memory optimization. |

---

## 13. External references

- Qwen3-TTS GitHub: https://github.com/QwenLM/Qwen3-TTS
- Qwen3-TTS documentation site: https://qwenlm-qwen3-tts.mintlify.app/
- Qwen3-TTS tokenizer docs: https://mintlify.com/QwenLM/Qwen3-TTS/concepts/tokenizer
- Technical report: *Qwen3-TTS Technical Report*, arXiv:2601.15621
- mlx-community Qwen3-TTS conversions: https://huggingface.co/mlx-community
- Mimi codec (Kyutai): https://kyutai.org/codec-explainer
- Community architecture / weight reference (unofficial but well-verified): https://github.com/gabriele-mastrapasqua/qwen3-tts/blob/main/MODEL.md
