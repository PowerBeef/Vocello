---
status: active
owner: backend-mlx
reviewed: 2026-10-16
summary: Sourced research on the Qwen3-TTS checkpoints Vocello ships and their upstream family — releases and provenance, the architecture as implemented upstream, official defaults, known failure modes, ports since the fork and Vocello's artifact recipe — with a parity ledger and the reference-documentation gap analysis that drives ER-13's overhaul.
sourceOfTruth:
  - Packages/VocelloQwen3Core/Sources/MLXAudioTTS/Models/Qwen3TTS/Qwen3TTS.swift
  - Packages/VocelloQwen3Core/Sources/MLXAudioTTS/Models/Qwen3TTS/Qwen3TTSTalker.swift
  - Packages/VocelloQwen3Core/Sources/MLXAudioTTS/Models/Qwen3TTS/Qwen3TTSSpeechTokenizer.swift
  - Packages/VocelloQwen3Core/Sources/MLXAudioCodecs/Mimi/Transformer.swift
  - Sources/QwenVoiceCore/UnsafeSpeechGenerationModel.swift
  - Sources/Resources/qwenvoice_production_model_catalog.json
  - config/model-artifact-receipts.json
---
# Qwen3-TTS model research (ER-13)

**Date:** October 16, 2026. **Requested by** the maintainer during the engine audit
([`2026-10-16-engine-runtime-audit.md`](2026-10-16-engine-runtime-audit.md), Part C). **Method:** two
read-only research agents (the upstream family and architecture; the ecosystem, ports and documentation
gaps), then the lead's verification of the load-bearing claims against this repository. The research
built, ran and downloaded nothing; one HTTP range request read the JSON header of one 4-bit
`model.safetensors` (about 110 KB, no weights). **Verified** below means the lead checked the claim
against Vocello's code, receipts or lock files on 2026-10-16; everything else carries its upstream
citation.

**Source keys.** Upstream code is QwenLM/Qwen3-TTS at HEAD `022e286b98` (2026-03-17), the last commit;
line numbers are from that commit
(`https://github.com/QwenLM/Qwen3-TTS/blob/022e286b98fbec7e1e916cb940cdf532cd9f488e/`).

| Key | Source |
|---|---|
| RM | `README.md` |
| WM | `qwen_tts/inference/qwen3_tts_model.py` |
| MQ | `qwen_tts/core/models/modeling_qwen3_tts.py` |
| CQ | `qwen_tts/core/models/configuration_qwen3_tts.py` |
| TV2 / TC2 | `qwen_tts/core/tokenizer_12hz/{modeling,configuration}_qwen3_tts_tokenizer_v2.py` |
| CFG / GEN / TOK | `config.json` / `generation_config.json` / `tokenizer_config.json` at `https://huggingface.co/Qwen/Qwen3-TTS-12Hz-1.7B-{CustomVoice,VoiceDesign,Base}` (GEN is identical, 245 B, in all five TTS repos) |
| STC | `https://huggingface.co/Qwen/Qwen3-TTS-Tokenizer-12Hz/resolve/main/config.json` (= each repo's `speech_tokenizer/config.json`) |
| P | Qwen3-TTS Technical Report, arXiv:2601.15621v1 |
| HFM | transformers **v4.57.3** `models/mimi/modeling_mimi.py` (qwen-tts pins 4.57.3) |
| `QwenLM#N`, `QD#N` | `https://github.com/QwenLM/Qwen3-TTS/issues/N` (PRs on the same path), `/discussions/N` |
| `MA#N`, `MAS#N`, `VO#N` | Blaizzy/mlx-audio, Blaizzy/mlx-audio-swift, vllm-project/vllm-omni issues and PRs |
| MS | Alibaba Cloud Model Studio documentation (`alibabacloud.com/help/en/model-studio/`) |

Vocello paths: `Q` = `Packages/VocelloQwen3Core/Sources/MLXAudioTTS/Models/Qwen3TTS/Qwen3TTS.swift`,
`T` = `…/Qwen3TTSTalker.swift`, `ST` = `…/Qwen3TTSSpeechTokenizer.swift`.

## 1. Headline findings

1. **The open-weight family has not changed since January 2026.** Weights were uploaded on 2026-01-21
   and never revised; the last inference-code change is qwen-tts 0.1.1 (2026-02-06); the last commit
   (2026-03-17) touches fine-tuning only. Nothing open-weight shipped after the September pins. The
   25 Hz models, the 25 Hz tokenizer and 25Hz-VoiceEditing were announced in the paper and never
   published (QwenLM#294, closed not planned; QD#46).
2. **Upstream supports D1 directly.** `generate_custom_voice` and `generate_voice_design` default to
   `non_streaming_mode=True` (WM L642, L738; changed from False in `0c6a7cb`, 2026-01-23);
   `generate_voice_clone` defaults to False (WM L478). vLLM-Omni keeps the same defaults and streams the
   audio independently, which is exactly D1's design; mlx-audio-swift PR #270 (open) proposes the same.
   RF-18's Mac screen nevertheless did not adopt D1 (§8).
3. **D2 was an mlx-audio invention, and mlx-audio removed it.** EOS re-insertion entered with mlx-audio
   `6549fc2` (2026-01-25) and was removed by `d2d02bf` (2026-08-19, MA#882, "early silent EOS
   truncation at sentence tail"), stating that the reference runs plain HF `generate()` with no such
   exemption. Vocello re-inserted EOS until 2026-10-20, when the RF-18 follow-up screen adopted
   filtering (`Qwen3ReferenceParity.production.filtersEOS = true`).
4. **The Mimi encoder RoPE bug (A-02) is confirmed and unfixed in the Swift port.** The 12 Hz encoder is
   HF `MimiModel`, which applies `rotate_half` to q/k weights stored in permuted ("sliced rotary")
   layout (HFM L542-560, L668). mlx-audio fixed its port with `rope_traditional=False` (`6549fc2`);
   mlx-audio-swift `main` and Vocello still use `RoPE(traditional: true)`
   (`Packages/VocelloQwen3Core/Sources/MLXAudioCodecs/Mimi/Transformer.swift:130`, **verified**).
   PowerBeef02's codec file is byte-identical to Qwen's, so the weights are in HF layout (§7).
5. **Four facts in Vocello's reference docs are wrong** and were copied from a community model write-up:
   the talker RoPE is split-half `rotate_half`, not adjacent pairs (MQ L615-619; Vocello `T:8-21`,
   **verified**); the decoder ends in `clamp(-1, 1)`, not tanh (TV2 L884; Vocello `ST:999`,
   **verified**); `semantic_codebook_size: 4096` is used by no official code (the decoder uses
   `codebook_size` 2048, TV2 L834; Vocello only checks the config value,
   `Qwen3TTSConfig.swift:515`, **verified**); and no 25 Hz checkpoint exists.
6. **The encoder's 250-frame window is not upstream behaviour.** Under transformers 4.57.3 the encoder
   runs full causal attention on eager and sdpa (HFM L1101-1108); only FlashAttention-2 honours the
   window, and the official loader has not selected it since PR #15 (2026-01-24). Vocello's encoder is
   full causal (`Mimi/Transformer.swift:166-168`, **verified**), which matches; PA-16's "encoder applies
   its window" step would move Vocello away from upstream. The **decoder** window (72 frames in all 8
   layers) is upstream behaviour that Vocello lacks (A-03).
7. **Production subtalker sampling is not independent.** Upstream keeps `subtalker_*` at 0.9 / top-k 50 /
   top-p 1.0 whatever the talker uses; Vocello's subtalker copies the talker
   (`Sources/QwenVoiceCore/UnsafeSpeechGenerationModel.swift:119-124`, **verified**), so Balanced
   (0.8/0.95) and Consistent (0.7/0.9) diverge. Every failure in RF-18's screen ran under Consistent.
   **Resolved 2026-10-20:** the RF-18 follow-up screen's C1 arm adopted the reference subtalker.
8. **Precision.** Qwen trained and evaluated in bf16 and recommends fp32 where bf16 is unavailable,
   because the code predictor is "extremely sensitive to precision" (QwenLM#43). No quantized
   checkpoint was ever evaluated upstream; Vocello's 4-bit artifacts quantize all 51 code-predictor
   linear and head tensors.
9. **Two considerations for the MLX refresh (CONV-21).** mlx-audio-swift v0.1.5 (`dbe5eaa`,
   2026-10-05) replaced MLX's scalar-gather form, which passes empty index metadata to Metal when API
   validation is on, in RVQ decode and MRoPE; Vocello still uses it (`ST:48`, `T:57-60`). And every
   quantized load leaks its initialization graph (MAS#286, ml-explore/mlx#4710, both open; about 110 MB
   after 43 reloads), which bears on the iPhone's 30 s idle unload and D-04.
10. **Don't use the official Hugging Face demo Space as a parity reference.** It bundles pre-February
    tokenizer code with the old transposed-conv trim (555 samples short) and the old `> 0` length rule.

## 2. The family and its provenance

| Checkpoint | Parameters; file | Role | Release | License |
|---|---|---|---|---|
| Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice | 1,916,676,352; bf16 3,833,402,552 B | 9 preset speakers + instruct | uploaded 2026-01-21 | Apache-2.0 |
| …-1.7B-VoiceDesign | 1,916,676,352; 3,833,402,552 B | voice from a description; no speakers | 2026-01-21 | Apache-2.0 |
| …-1.7B-Base | 1,928,677,440; 3,857,413,744 B (+≈12.0 M for the ECAPA speaker encoder) | ICL or x-vector clone; fine-tuning base | 2026-01-21 | Apache-2.0 |
| …-0.6B-CustomVoice | 905.8 M | 9 speakers, **no instruct** (the wrapper drops it, WM L799-800) | 2026-01-21 | Apache-2.0 |
| …-0.6B-Base | 914,643,008 | clone | 2026-01-21 | Apache-2.0 |
| Qwen/Qwen3-TTS-Tokenizer-12Hz | 170.6 M; fp32 682,293,092 B | codec encode/decode | 2026-01-21 | Apache-2.0 |
| 25 Hz Base/CustomVoice, 25Hz-1.7B-VoiceEditing, Tokenizer-25Hz | — | paper only | **not released** (QwenLM#294; QD#46) | — |

There is no 0.6B VoiceDesign. The HF card for 0.6B-CustomVoice claims instruction control, which RM L78
and WM L799-800 contradict. mlx-community publishes bf16/4/5/6/8-bit conversions of all five models
(created 2026-01-22, last weight upload 2026-01-25, unchanged since).

**Publications.** The technical report (arXiv:2601.15621, only v1, 2026-01-22, CC BY 4.0); the blog
"Qwen3-TTS Family is Now Open Sourced" (2026-01-21); the GitHub repository (created 2026-01-21, 13
commits, Apache-2.0); PyPI `qwen-tts` 0.0.2 → 0.1.1 (2026-01-22 → 2026-02-06). Qwen points to vLLM-Omni
for streaming (RM L432-434). The Mintlify "documentation site" names no publisher and is not linked by
Qwen.

**Closed API models** share the name but not the weights: `qwen3-tts-flash` (2025-09, 17 voices),
voice enrollment and design endpoints, and the `qwen-audio-3.x` successors (MS). Their guidance (10–20 s
references, 60 s maximum, 500-character briefs) applies to the hosted service, not the open weights.

## 3. Architecture as implemented upstream (1.7B unless noted)

**Talker.** Hidden 2048, SwiGLU 6144, 28 layers, 16 heads / 8 KV heads, head dim 128, RMSNorm 1e-6,
θ 1e6, max positions 32,768, codec vocabulary 3072, text vocabulary 151,936, 16 code groups (0.6B:
hidden 1024, SwiGLU 3072; q dim 2048 > hidden). Per-head RMSNorm on q and k before RoPE (MQ L752-780).
RoPE builds `cat(freqs, freqs)` and applies `rotate_half` (MQ L546-559, L615-619); `rope_scaling.interleaved`
only chooses which M-RoPE stream feeds each frequency, and all three position streams are equal
(`cumsum(mask) - 1`, MQ L1794-1798), so this is plain 1-D RoPE. `text_projection` is a SiLU MLP with
bias; `codec_head` is untied. Each step's input is the sum of the previous frame's 16 codebook
embeddings (codebook 0 from the talker's `codec_embedding`, 1–15 from the code predictor's embeddings)
plus the text track (MQ L1682-1692). `position_id_per_seconds: 13` is in the config and used by no code.

**Codec vocabulary (3072 ids).** 0–2047 are codebook-0 codes and the only ids that can be sampled; MQ
L2059-2063 suppresses 2048–3071 except EOS. Control: pad 2148, bos 2149, eos 2150, think 2154, nothink
2155, think_bos 2156, think_eos 2157. Languages: english 2050, german 2053, spanish 2054, chinese 2055,
japanese 2058, french 2061, korean 2064, russian 2069, italian 2070, portuguese 2071; CustomVoice adds
sichuan_dialect 2062 and beijing_dialect 2074. Speakers (CustomVoice): aiden 2861, sohee 2864, ono_anna
2873, eric 2875, dylan 2878, uncle_fu 3010, ryan 3061, vivian 3065, serena 3066; `spk_is_dialect` maps
eric → sichuan and dylan → beijing.

**Text tokenizer and templates.** `Qwen2Tokenizer` BPE from `vocab.json` + `merges.txt`, with no
`tokenizer.json` and no chat template (TOK). Ids: `<|im_start|>` 151644, `<|im_end|>` 151645,
`assistant` 77091, `<tts_pad>` 151671, `<tts_text_bos>` 151672, `<tts_text_eod>` 151673. Templates
(WM L269-276): target `<|im_start|>assistant\n{text}<|im_end|>\n<|im_start|>assistant\n`, reference
`<|im_start|>assistant\n{ref_text}<|im_end|>\n`, instruct `<|im_start|>user\n{instruct}<|im_end|>\n`.
Reference and target are tokenized separately and concatenated, so no space separates them (MQ L2178,
L2190-2191, L2207). WM L118 passes `fix_mistral_regex=True`; under transformers 4.57.3 that swaps in
Mistral's pre-tokenizer regex only when the model loads from a local directory (research reading, not
documented by Qwen).

**Prefill layouts (MQ L2068-2233).** P(x) = text projection of a text embedding, C(x) = codec
embedding.
1. Instruct (CustomVoice/VoiceDesign): P(instruct template), text-only positions.
2. Role header: P(`<|im_start|>`, `assistant`, `\n`), text-only.
3. Codec prefix: `[think, think_bos, lang, think_eos]` with a language, `[nothink, think_bos, think_eos]`
   for Auto; then the speaker vector (CustomVoice row or Base x-vector, which ICL also uses); then
   `[codec_pad, codec_bos]`; the text track under it is `tts_pad × (n−2)` then `tts_bos`. A dialect
   speaker with language Chinese or Auto gets the dialect id (MQ L2118-2122).
4. Then **streaming** (`non_streaming_mode=False`: P(text[0]) + C(bos), the rest of the text trails one
   token per frame, then `tts_pad`), **non-streaming** (all text + `tts_eos` over `codec_pad`, then
   P(`tts_pad`) + C(bos)), or **ICL** (reference + target text over the reference's codec frames, padded
   with `tts_pad`; MQ L1977-2019). The wrapper docstring says the streaming mode only *simulates*
   streaming text input (WM L513-515).

**Decoding.** HF `generate` with `min_new_tokens=2`, EOS 2150 and the suppression above (MQ L2044-2066);
the repetition penalty (1.05) sees only codebook-0 ids; output is cut at the first EOS (MQ L2283-2289).

**Code predictor (MTP).** Hidden 1024, 5 layers, 16 heads / 8 KV, θ 1e6, vocabulary 2048, 15 codec
embeddings at talker width, 15 heads, `small_to_mtp_projection` 2048 → 1024 (identity on 0.6B). Per frame
a fresh 15-step generation with its own `subtalker_*` settings, no EOS and **no repetition penalty**
(MQ L1671-1680, L1276-1299).

**Speaker encoder (Base only).** ECAPA-TDNN without BatchNorm (MQ L95-393), output 2048 (1.7B) or 1024
(0.6B). Input: mono 24 kHz; mel n_fft 1024, hop 256, Hann 1024, 128 Slaney bins, fmax 12 kHz, reflect
padding 384, `center=False`, magnitude `sqrt(re² + im² + 1e-9)`, `log(clamp(·, 1e-5))` (MQ L1943-1952,
L399-464). Vocello's `qwen-speaker-mel-v1` frontend matches this contract
(`Packages/VocelloQwen3Core/CLONE_ARTIFACT_FORMAT.md`).

**12 Hz tokenizer.** Encoder = transformers' `MimiModel` without its decoder: SEANet (strides 4,5,6,8 →
25 Hz), an 8-layer transformer (hidden 512, θ 1e4, layer scale 0.01, `sliding_window` 250 honoured only
by FlashAttention-2), a stride-2 downsample to 12.5 Hz, and split RVQ with 32 quantizers of which Qwen
keeps 16 (TV2 L983-984; the first is WavLM-distilled, P §2.2). Decoder = Qwen's own code: RVQ decode
(2048 × 256 codebooks projected to 512), causal `pre_conv`, an 8-layer transformer whose **every** layer
uses a 72-frame sliding window (TC2 `layer_types`; TV2 L419, L535-551), two ×2 causal transposed-conv +
ConvNeXt upsamplers, a SEANet decoder with SnakeBeta and right-only trimming (rates 8,5,4,3), and a final
`clamp(-1, 1)` (TV2 L824-896). Official batch decode pads with −1, counts length with `> -1`, and
`chunked_decode` runs 300-frame chunks with 25 frames of context (TV2 L886-897, L1011-1017). ICL output
decodes `ref_code + generated` and drops the reference's share of samples (WM L612-633).

**Precision as Qwen runs it.** Talker, code predictor and x-vector in bf16; the codec file is fp32
(STC); the README and evaluation load with `dtype=bf16`, which the loader also forwards to the tokenizer
(research reading). QwenLM#355 (open) reports fp16 logit overflow and proposes float32 logits.

## 4. Official defaults and guidance

| Knob | GEN (all modes) | Wrapper fallback | `model.generate` | Examples, evaluation, Space |
|---|---|---|---|---|
| do_sample / temperature / top_k / top_p | true / 0.9 / 50 / 1.0 | same | same | same |
| repetition_penalty (talker only) | 1.05 | 1.05 | 1.05 | 1.05 |
| subtalker do_sample / temperature / top_k / top_p | true / 0.9 / 50 / 1.0 | same | same | same |
| max_new_tokens | **8192** | 2048 | 4096 | **2048** (RM L465) |

Precedence: an explicit argument, then GEN, then the hard default (WM L319-337). The talker context is
32,768 positions; 8192 frames is 655 s and 2048 frames 163.8 s. The open code caps neither reference
nor text length; the paper claims stable generation beyond 10 minutes (P §1, §4.2.6).

**Languages and speakers.** zh, en, ja, ko, de, fr, ru, pt, es, it, plus Auto (no language token); Qwen
advises setting the language when known (RM L50, L167). Speakers and native languages: Vivian, Serena,
Uncle_Fu (Chinese); Dylan (Beijing dialect); Eric (Sichuan dialect); Ryan, Aiden (English); Ono_Anna
(Japanese); Sohee (Korean). Each sounds best in its native language but can speak all of them (RM L187).
Upstream has no default speaker.

**Cloning.** "3-second rapid clone" (RM L77). ICL requires `ref_text` (WM L436-438); x-vector-only mode
ignores it at lower quality (RM L243). Reuse prompts with `create_voice_clone_prompt` (RM L269); for a
reusable designed voice, design then clone (RM L288-290). Community findings checked against the
official code: a `ref_text` covering only part of the reference makes ICL loop without EOS (MA#921, 3/3
degenerate on PyTorch); a long reference in the streaming ICL layout speeds speech up (QwenLM#239; PR
#362, open, proposes non-streaming as the clone default).

**Instruct and briefs.** Free text wrapped as a user turn, no length limit in code; the blog shows
attribute lists, prose and persona cards. A Qwen collaborator recommends sampling a design several times
and then cloning (QwenLM#4), and suggests "very happy but without laughing" to stop emotive instructs
from adding laughter (QwenLM#16) — an upstream source for negative constraints.

**Latency** (P Table 2; internal vLLM V0 with torch.compile and CUDA Graphs): 12Hz-1.7B first packet
101 ms, RTF 0.313 at concurrency 1 (packet = 4 tokens = 320 ms); 0.6B 97 ms, RTF 0.288; 25Hz-1.7B
150 ms, RTF 0.253. The qwen-tts package targets offline use; streaming is vLLM-Omni's (QwenLM#10).

**Limitations Qwen states** (paraphrased): Base has no instruct support because 12 Hz control is
unstable (QwenLM#25); non-verbal sounds come out only implicitly (#9); emotive instructs can add laughter
(#16); voice design gives a new voice each sample (#4); use fp32 without bf16 (#43); the 25 Hz model is
steadier for long-form (P §4.2.6).

**Evaluation** (RM L465): bf16, `max_new_tokens` 2048, GEN sampling, language "auto" for Seed-TTS and
InstructTTSEval (the nothink branch) and explicit elsewhere. 1.7B-Base: Seed-TTS WER zh 0.77 / en 1.24;
ten-language average WER 1.835, SIM 0.789. InstructTTSEval APS/DSD/RP: CustomVoice zh 83.0/77.8/61.2,
en 77.3/77.1/63.7; VoiceDesign zh 85.2/81.1/65.1, en 82.9/82.4/68.4. Long speech WER (CustomVoice) zh
2.356 / en 2.812. Tokenizer on LibriSpeech test-clean: PESQ-WB 3.21, STOI 0.96, UTMOS 4.16 (P Tables
4-10). Qwen's own numbers disagree in places (the README's Korean 25 Hz row duplicates French; §4.2.6
text versus its table).

## 5. Known failure modes

| Symptom | Items | Relevance to Vocello |
|---|---|---|
| Missing EOS, run-on, noise | QwenLM#118 (~0.5% of Base runs never emit EOS), #305 (5 minutes of noise on a cross-lingual year), #258, #318; VO#6158 reproduces on official CUDA | the 2048 cap ends them as `maxTokens`; RF-18 saw two runaway takes under Consistent |
| Truncation at the tail | #55 (ja/ko last word), #181 (last two words, up to 70% in cases), QD#161 (isolated words); MA#882 (fixed by removing EOS re-insertion) | D2 |
| Pace drift and silences | #239 (rate climbs over long text: text fed at 12.5 tokens/s against ~4–5 spoken), PR #362 (measured +16.7% with a 12.9 s reference in streaming, 0.0% non-streaming), #290 (clones always faster) | A-01, RF-18 |
| Clone identity and echoes | #80 (~20% wrong speaker), #134 (source accent leaks), #341 (echo of the reference tail), #119, #200 (onset noise or stray syllable), #219 (cold-decoder first-token distortion) | G-01, G-07, A-04, D-02 |
| Numbers across languages | #68, #151, #305, #256, #328, QD#330 | the planner does not pre-normalize numbers |
| Accents | #134, #359 (Chinese accent on vivian/serena), QD#230 (Design in es/fr sounds English), #248 (dialect instructions ignored) | Design and dialect control are suggestive only |
| Precision | #333 (NaN under FA2), #355 (fp16 overflow) | D3 adopted float32 sampling |
| Fine-tuning | #179, #278, #337, #371 and others | out of scope (no SFT) |

VO#8569 (merged 2026-10-12) bounds the codec budget at max(192, 12·n) frames for Base and max(400, 40·n)
for CustomVoice/VoiceDesign and retries once with a fresh seed — a reference for ER-11.

## 6. Ports and changes since the fork

Vocello forked mlx-audio-swift `v0.1.2` (`fcbd04da`, 2026-03-12; `Packages/VocelloQwen3Core/ORIGINS.md`)
and last reviewed `d302a5c6` (v0.1.3; `UPSTREAM.md`). Upstream has since cut v0.1.4 and v0.1.5.

| Port and change | Vocello status |
|---|---|
| mlx-audio-swift `dbe5eaa` (v0.1.5): mlx-swift 0.32.3 / lm 3.32.3; scalar gather → range slice in RVQ decode and MRoPE; `streamingStep` evaluates before `sending` | pins now match (CONV-21, 2026-10-16); the range-slice change is **not ported** (`ST:48`, `T:57-60`) |
| mlx-audio-swift PR #270 (open): `nonStreamingMode = true` for CustomVoice/VoiceDesign | = D1 |
| mlx-audio-swift PR #286 (open): stop the per-load initialization-graph leak (ml-explore/mlx#4710) | applies to Vocello's quantized load (Q 5667-5705) |
| mlx-audio `6549fc2`: Mimi `rope_traditional=False`; fp32 RVQ encode; EOS kept after top-k/top-p; ICL repetition-penalty floor 1.5 | RoPE **not fixed** (A-02); EOS re-insertion **inherited** (D2); no 1.5 floor (1.05 is upstream's) |
| mlx-audio `d2d02bf` (MA#882): EOS filtered like any token | D2 open |
| mlx-audio `a730a68`: temperature before top-p/min-p | ported |
| mlx-audio `90ee81f`: a float32 speaker embedding promoted prefill and KV to float32 (~2.4× slower) | Vocello casts at the prefix (`Packages/VocelloQwen3Core/PERFORMANCE.md`) |
| mlx-audio `c4d29e6` (2026-10-07): transposed-conv bias added twice at streaming chunk boundaries | immune: input-side overlap-and-discard (`ST` 541-615) |
| QwenLM `5f8581d` (right-only transposed-conv trim) and `6cafe55` (−1 padding, `> -1` length) | matched (`ST` 786-800); the dead legacy `decode` still uses `> 0` (`ST` 1159; A-22) |
| vLLM-Omni: same prompt-mode defaults; reference leading-silence trim (VO#5041); missing-EOS safeguards (VO#6158, VO#8569) | candidates for ER-03/ER-11 |

Quantization lessons from the ports: keep embeddings, the speaker encoder and the codec unquantized; run
RVQ encode in fp32; avoid fp16 logits; and remember that no quantized model was evaluated upstream.

## 7. Vocello's shipped artifacts (verified)

| Model:variant | Repository @ revision | `model.safetensors` | Total bytes |
|---|---|---|---|
| pro_custom:speed | `PowerBeef02/Qwen3-TTS-12Hz-1.7B-CustomVoice-4bit@29c4b746…` | 1,333,510,029 B | 2,049,696,897 |
| pro_design:speed | `…-VoiceDesign-4bit@62f2646e…` | 1,333,510,029 B | 2,049,696,404 |
| pro_clone:speed | `…-Base-4bit@47ab65f7…` | 1,357,521,577 B | 2,073,713,977 |
| pro_custom:quality | `…-CustomVoice-8bit@50c40b22…` | 2,101,592,453 B (`0b868d14…`, **verified**) | 2,817,779,315 |
| pro_design:quality | `…-VoiceDesign-8bit@bb56faf7…` | 2,101,592,453 B | 2,817,778,822 |
| pro_clone:quality | `…-Base-8bit@f63ea141…` | 2,125,604,061 B | 2,841,796,455 |

Source: `Sources/Resources/qwenvoice_production_model_catalog.json`. The Quality receipts are in
`config/model-artifact-receipts.json`; the Speed digests live in
`Sources/Resources/qwenvoice_ios_model_catalog.json` (`scripts/model_catalog_contract.py`), which
ARCHITECTURE §11 does not say.

- **Shared codec:** `speech_tokenizer/model.safetensors`, fp32, 682,293,092 B, sha256 `836b7b35…` —
  byte-identical to Qwen's (**verified** against the receipts).
- **Marking:** `marking/audioseal_wm16_generator_fp16.safetensors`, 29,360,042 B (Meta AudioSeal, MIT).
- **`generation_config.json`:** identical to upstream (245 B, sha256 `f1b90b45…`).
- **Quantization map** (4-bit CustomVoice index and header): affine, group 64, 251 modules — every
  talker and code-predictor projection, the 15 code-predictor heads, `codec_head`,
  `small_to_mtp_projection` and `text_projection`. `talker.model.text_embedding` is 8-bit in both tiers
  (Vocello's one weight change, `scripts/convert_text_embedding_8bit.py`, 2026-07-26: −292 MB on disk,
  −278 MB MLX peak on an 8 GB Mac, fixed-seed output changed). Kept bf16: the codec embeddings, the 15
  code-predictor codec embeddings, every norm and bias; the Base speaker encoder stays float; the codec
  is fp32. Compute dtype is bf16, so the talker KV cache is bf16 (not fp16 as three docs say).
- **artifactVersion history:** 2026.04.05.2 → 2026.05.25.1 → 2026.07.26.1 (8-bit text embedding) →
  2026.08.01.1 (f16 codec, later withdrawn) → 2026.08.06.1 (AudioSeal) → 2026.09.14.1 (fp32 codec
  restored after a burst in the first 50 ms of streamed clone takes).
- **Gaps:** `scripts/check_ios_catalog.sh` checks digest *format* only and does not compare the
  `baseURL` revision with the contract (`model_catalog_contract.py validate --require-complete` does);
  the PowerBeef02 model cards omit the marking file and the f16 round trip.

## 8. Parity ledger

| ID | Divergence | Upstream | Vocello | Status (2026-10-16) | Owner |
|---|---|---|---|---|---|
| D1 / A-01 | Text layout of streamed Custom/Design takes | non-streaming (full text up front), audio streamed | streaming text: one text token per frame, then `tts_pad` | **not adopted**: RF-18's pre-registered Mac screen (D1-on failed 3 of 23 long segments, D1-off 2 of 27, all under Consistent) | ER-03 |
| D2 | EOS after top-k/top-p | filtered like any token | filtered since 2026-10-20 (`filtersEOS = true`) | **adopted** by the RF-18 follow-up screen's rule; mlx-audio removed the same re-insertion (MA#882) | — |
| D3 | Sampling precision | bf16 logits (fp16 overflow reported, #355) | float32 logits | **adopted** 2026-10-13 | — |
| D5 / A-04 | Decoder history for streamed clones | ICL decodes reference + generated codes, then trims | streamed clones decode from a cold decoder | open (with A-26) | ER-04 |
| D6 | Custom under Auto | nothink, no language token | English fallback plus a diction instruction | open, by design | ER-05 |
| A-02 | Mimi encoder RoPE | `rotate_half` on permuted weights | `traditional: true` | open; ships with G-03's version bump | ER-04 |
| A-03 | Decoder sliding window | 72 frames in all 8 layers; batch decode in 300/25 chunks | full causal; KV grows for the whole take | open | PA-16 |
| — | Encoder window | full causal (window only under FA2) | full causal | **matches**; do not add the 250-frame window | PA-16 wording |
| A-11 | ICL target text | no separator between reference and target | exactly one leading space (`Q` 4589-4593, **verified**; added for French first-word drops) | deliberate; screen before changing | ER-04 |
| A-12 | ICL reference padding | none | +0.5 s of silence (`icl-ref-silence500ms-v2`); its comment wrongly claims parity | open; fix the comment | ER-04 |
| G-14 | ICL layout | streaming by default (PR #362 proposes non-streaming) | non-streaming overlay (mlx-audio lineage) | deliberate | ER-03 |
| — | Subtalker sampling | independent 0.9 / 50 / 1.0 | copies the talker (**verified**) | open; RF-18 hypothesis | ER-05 |
| — | Repetition penalty scope | talker codebook 0 only | same (**verified**) | matches | — |
| — | Dialect speakers under Chinese/Auto | dialect language id | same (`Q` 1524-1535, **verified**) | matches | — |
| — | Talker RoPE; decoder output | `rotate_half`; `clamp(-1,1)` | same (**verified**) | matches | — |
| — | Token cap | GEN 8192; evaluation 2048 | 2048 | deliberate (= evaluation) | — |
| — | Codec precision | bf16 in the README setup | fp32 | deliberate (f16 burst, 2026-09-14) | — |
| — | Weights | bf16 | 4-bit / 8-bit affine group 64, 8-bit text embedding | deliberate; no upstream evaluation | — |

## 9. Reference-documentation gap analysis

Tags: **W** wrong, **S** stale, **M** missing, **D** duplicated, **FM** front matter.

| Doc | Most important gaps |
|---|---|
| `docs/reference/qwen3-tts-guide.md` | **W:** RoPE "adjacent pairs", "final tanh", 2.1 kbps (it is 2.2 kbps: 16 × 11 bit × 12.5 Hz; ~175× against 16-bit PCM), the 4096 semantic codebook, "the faster 25 Hz variant" (slower first packet, unreleased), "25 Hz checkpoints exist", "no upstream source endorses negative constraints" (QwenLM#16), the preset table against the shipped `EmotionPreset.swift`, subtalker "aligned with the public policy" (Expressive only). **S:** transcripts "optional" (partial transcripts collapse ICL, G-01/G-02), prompt caching (B-16), clone warnings (G-09/G-10), the 60 s block (Mac one-off references, G-11), the identity list (missing encoder, MLX and preparation versions), the hosted-service 10–20 s guidance presented as model guidance. **M:** the parity ledger, upstream decoding constraints, the dialect swap, think_bos/think_eos and speaker ids, the speaker encoder, the failure catalogue, licenses. **FM:** body edited after `reviewed`; `sourceOfTruth` lacks the engine files |
| `docs/reference/qwen3-tts-prompting-guide.md` | **W:** the codec-lane order (`tts_pad`/`tts_bos` are text-lane), "lanes are summed" (instruct and role positions are text-only), the subtalker claim, #16 called unofficial. **S:** the 0.6B guard, long-generation speed-up (now mechanism plus measurement), the nothink evaluation basis (RM L465). **M:** ICL layout and transcript rules (G-01, G-12, G-14, G-15, A-11), the reference tail echo (#341), D6 |
| `docs/reference/mimi-codec-guide.md` | **W:** 2.1 kbps; 4096 "used by the talker"; "same audio for 300-token or 12-token decodes" (the reference applies the 72-frame window and 300/25 chunks; Vocello is equal only within tolerance); the SnakeBeta formula; "chunked = memory-bounded synthesis" (dead code in Vocello); the Mimi paper title (it is Moshi, arXiv:2410.00037). **S:** A-02 and G-03 missing. **M:** the official codec digest, the f16 history, upstream decode fixes, #219, #223, the encoder-window caveat |
| `docs/reference/mlx-guide.md` | **W:** MRoPE "separate positions" (A-19), "fp16 KV cache" (bf16), byte-identity of the compiled predictor (tested at 2e-6, F-15), "~6 GB on iPhone 17 Pro" (8,192 MB on iOS 27, D-06). **S:** rewrite §9 and the error-handling text for 0.32.3 (#3523, #4177 sampler, F-04/F-05). **M:** error scopes (BG-1, F-01, F-03), the per-layer quantization recipe, the scalar-gather issue, the load leak, `clear_cache`'s RTF cost (MA#851) |
| `Packages/VocelloQwen3Core/UPSTREAM.md` | **W:** "the macOS app reaches the engine through an XPC service" (in-process since 2026-09-15), "official talker defaults" (Expressive only). **S:** reviewed head. **M:** mlx-audio (Python) and the QwenLM reference as tracked upstreams |
| `docs/ARCHITECTURE.md` (engine) | **W:** §4.7 says only the 8 GB Mac skips the Custom prewarm (the iPhone does too, D-02); §11 places all digests in the receipts. **S:** §4.5/§4.8 clone caches (B-16), the codec decoder's module. **M:** error scopes and the take lifecycle, the reference-parity arms, the streaming text layout |
| `Packages/VocelloQwen3Core/PERFORMANCE.md`, `CLONE_ARTIFACT_FORMAT.md`, `qwen3-core-maintenance.md`, `ios-engine-optimization.md` | "official parameters" claims that hold for Expressive only; iOS tokenizer residency qualified with the withdrawn f16 codec (A-19); "~6 GB" and `decodeSpeedupX`-as-RTF in the historical iOS doc; A-02 and the composite feature version in the artifact spec (F-06 is now recorded there) |

**Target structure (one owner per fact).** The model reference (`qwen3-tts-guide.md`) owns the family,
the shipped checkpoints and recipe, the architecture, generation semantics, languages and speakers, the
failure catalogue and the parity ledger; the prompting guide owns the wire format, instructions, presets
and transcript/ICL input rules; the codec guide becomes the 12 Hz tokenizer guide; `mlx-guide.md` owns
MLX semantics, error scopes, quantization mechanics and pins; `model-delivery.md` owns bytes, digests
and artifact history; ARCHITECTURE §4 owns engine structure, the memory tiers and the clone host
pipeline; `qwen3-core-maintenance.md` absorbs UPSTREAM.md's intake procedure, leaving UPSTREAM.md a
review-point ledger; `ios-engine-optimization.md` stays historical with a banner; dated research docs
stay dated and link to the owners.

## 10. Roadmap implications (no new plans)

- **ER-03:** D1 stays open for a future screen with more strata; PR #362's measured drift and vLLM-Omni's
  defaults are the upstream evidence.
- **ER-04:** A-02 with G-03's version bump (now confirmed by mlx-audio's fix); A-12's padding and its
  comment; A-11 needs a screen before any change.
- **ER-05:** D2 has direct upstream evidence (MA#882); subtalker independence is RF-18's open hypothesis.
- **PA-16:** keep the decoder window; drop the encoder-window step, which would diverge from upstream;
  QwenLM#223's sample loss belongs in its 300/25 parity fixture.
- **ER-06 / ER-07:** the quantized-load leak (MAS#286, mlx#4710) under the iPhone's idle unload; D-04's
  309 MiB may be partly this.
- **ER-08 / ER-12:** port the range-slice gathers (`ST:48`, `T:57-60`); remove the dead `chunkedDecode`
  and legacy `decode`.
- **ER-11:** VO#8569's codec budget and fresh-seed retry; #118's ~0.5% no-EOS rate.
- **ER-13:** the gap analysis in §9 is pass 1's work list; pass 2 follows RF-18 and CONV-21 as shipped.

## 11. Open questions

1. Whether the 25 Hz models and VoiceEditing are still planned; Qwen has said nothing since 2026-01-26.
2. How the API models relate to the open weights.
3. Whether Qwen trained with the Qwen2 or the Mistral pre-tokenizer regex (`fix_mistral_regex`).
4. Whether Qwen intends the encoder's 250-frame window to apply.
5. Whether the paper's streaming numbers used 25 or 72 frames of decoder context.
6. Whether Qwen's evaluation ran the codec in bf16.
7. How much A-02 and 4-bit code-predictor quantization change output (needs a parity or measured run).
8. Whether the scalar-gather issue reproduces under mlx-swift 0.32.3, and the load leak's real size.
9. The iOS 27 memory limit on 8 GB phones (D-06 verified only the 12 GB iPhone 17 Pro).
