---
status: active
owner: backend-mlx
summary: Sourced reference for the three model-facing text surfaces (script, delivery instruction, voice description) — every claim labeled OFFICIAL/RESEARCH/MEASURED-HERE/COMMUNITY/UNVERIFIED.
sourceOfTruth:
  - config/delivery-instruction-contract.json
  - Sources/QwenVoiceCore/EmotionPreset.swift
---
# Qwen3-TTS Prompting Guide

A sourced reference for the three text surfaces that reach the model: the **script text**, the
**delivery instruction**, and the **voice description**. It covers what each one does, how the
three generation modes differ, and what upstream actually specifies versus what this repository
invented.

Companion to [`qwen3-tts-guide.md`](qwen3-tts-guide.md), which is the *architecture* reference
(model variants, tokenizer profile, Talker/decoder, speaker roster, parameters). This file is the
*input* reference. Where they overlap, the architecture guide owns the runtime facts and this file
owns the prompt-writing facts.

_First written 2026-08-02, from a primary-source research pass plus a code audit of this checkout._

## How to read this document

The project has repeatedly acted on prompt-writing advice whose origin nobody could name, so every
substantive claim below carries a provenance label:

| Label | Means |
| --- | --- |
| `OFFICIAL` | Stated by the Qwen team: repository source, model card, README, technical report, Alibaba Cloud Model Studio docs, or a maintainer answering an issue. |
| `RESEARCH` | Published peer-reviewed or preprint work, including the benchmark Qwen3-TTS is evaluated against. Applies to the model family or to description-conditioned TTS generally, not necessarily to this checkpoint. |
| `MEASURED-HERE` | Established in this repository, either by reading this checkout's code or by a recorded measurement. The measurement and its date are named. |
| `COMMUNITY` | Third-party report — a GitHub issue, a vendor's own docs for a different product, a blog. Quality varies and is called out. |
| `UNVERIFIED` | Plausible, in circulation, and not supported by anything above. Treated as a hypothesis, never as a rule. |

**This is a reference, not canon.** Nothing here is a normative repository rule yet. Rules get
promoted into [`../../Sources/QwenVoiceCore/EmotionPreset.swift`](../../Sources/QwenVoiceCore/EmotionPreset.swift)
or a domain rule under [`../../.agents/rules/`](../../.agents/rules/) only after they are validated
against our own model, because the alternative — shipping unvalidated guidance — is how the current
preset copy came to be.

---

## 1. The wire format

`OFFICIAL`. The instruction is not a parameter, a tag, or a field. It is a ChatML **user turn**
prepended to the speech prompt. Upstream's reference implementation
(`qwen_tts/inference/qwen3_tts_model.py`) builds it as:

```python
def _build_instruct_text(self, instruct: str) -> str:
    return f"<|im_start|>user\n{instruct}<|im_end|>\n"

def _build_assistant_text(self, text: str) -> str:
    return f"<|im_start|>assistant\n{text}<|im_end|>\n<|im_start|>assistant\n"
```

`MEASURED-HERE`. This checkout matches byte for byte. In
[`Qwen3TTS.swift`](../../Packages/VocelloQwen3Core/Sources/MLXAudioTTS/Models/Qwen3TTS/Qwen3TTS.swift)
(`buildConditioningPrefix`):

```swift
let instructText = "<|im_start|>user\n\(instruct)<|im_end|>\n"
```

The prompt format is **not** a suspect for delivery problems.

### 1.1 What surrounds it

`OFFICIAL`, from upstream's `modeling_qwen3_tts.py`. The full conditioning prefix is:

1. `textProjection(embed("<|im_start|>user\n{instruct}<|im_end|>\n"))` — optional; absent when
   there is no instruction.
2. `textProjection(embed("<|im_start|>assistant\n"))` — the role prefix, always present.
3. A codec lane: TTS padding, BOS, then a **language prefill**, then the speaker embedding.

Text and codec lanes are **summed**, not concatenated — the same position carries both.

### 1.2 There is no chat template and no system turn

`OFFICIAL`. `chat_template` in the checkpoint's `tokenizer_config.json` is `None`. There is no
Jinja template to retrieve and `apply_chat_template` is not part of the TTS path; the ChatML
strings are hardcoded in Python exactly as quoted above. Only two roles appear anywhere in the
upstream codebase: `user` (the instruction) and `assistant` (the text). **There is no
`<|im_start|>system` in Qwen3-TTS.** Anything placed in a system turn is off-distribution.

### 1.3 The language prefill selects a "thinking" branch

`OFFICIAL`. The codec prefill takes one of two shapes depending on whether a language is resolved:

```
language is nil  ->  [codec_nothink, codec_think_bos, codec_think_eos]
language is set  ->  [codec_think,   codec_think_bos, language_id, codec_think_eos]
```

`OFFICIAL`, technical report §3.3: *"we introduce a probabilistically activated thinking pattern
during training to improve instruction following, especially for complex descriptions."* The report
credits this mechanism specifically for instruction following, and again for the voice-design
result.

`MEASURED-HERE`. This checkout implements both branches faithfully
(`resolvedLanguageIdentifier` plus the two `codecPrefill` arms in `Qwen3TTS.swift`). But **which
branch a request takes depends on language detection**, and the fallbacks differ per mode
([`GenerationSemantics.swift`](../../Sources/QwenVoiceCore/GenerationSemantics.swift),
`qwenLanguageHint`):

| Mode | Fallback when detection fails | Branch taken |
| --- | --- | --- |
| Custom | `english` | `think` + language id |
| Design | `auto` | `nothink` |
| Clone | `auto` | `nothink` |

`UNVERIFIED`. Whether the `nothink` branch measurably weakens instruction adherence is not
documented and upstream publishes no ablation. It is a cheap A/B (§10.4) and the paper's own
framing makes it worth running.

---

## 2. Which checkpoint answers which prompt

This is the most load-bearing section in the document. The three modes are not three settings on
one model. **They are three separately weighted checkpoints with different conditioning
interfaces**, and the differences are not symmetric.

`OFFICIAL`, from the upstream README's support matrix:

| Checkpoint | What conditions the voice | Instruction control |
| --- | --- | --- |
| `Qwen3-TTS-12Hz-1.7B-CustomVoice` | one of 9 speaker embeddings | ✅ |
| `Qwen3-TTS-12Hz-1.7B-VoiceDesign` | the instruction itself | ✅ |
| `Qwen3-TTS-12Hz-1.7B-Base` | reference audio | ❌ |
| `Qwen3-TTS-12Hz-0.6B-CustomVoice` | one of 9 speaker embeddings | ❌ |
| `Qwen3-TTS-12Hz-0.6B-Base` | reference audio | ❌ |

### 2.1 The Base (clone) model ignores instructions, silently

`OFFICIAL`, from a Qwen maintainer on upstream issue #25:

> "Since the control capability of the 12Hz base model is relatively unstable, our base model does
> not currently support instruct. In the future, we will release a 25Hz voice editing model, which
> will support both cloning and instruct."

Upstream's `generate_voice_clone()` has **no `instruct` parameter at all**, and upstream drops the
instruction outright on the 0.6B CustomVoice model:

```python
if self.model.tts_model_size in "0b6":  # for 0b6 model, instruct is not supported
    instruct = None
```

`COMMUNITY`, corroborating from at least five independent reporters across upstream discussions
#218, #231, HF discussions #28 and #38, and mlx-audio #453: passing an instruction to Base does
nothing, without warning or error. One reporter: *"We were very close to fabricating emotion
support but dropped it due to inconsistent and unpredictable outcomes, which worsened voice quality
and often changed the speaker's voice."*

`COMMUNITY`, **and this is a live hazard for any MLX-based product**: the upstream MLX port does
not replicate either guard in its generation path. Its only model-type check lives in
`supports_tts_batch()`, a batching-eligibility predicate, not in `generate()`. An MLX caller that
passes a delivery instruction while running Base will prepend an instruct turn the model was never
trained on — roughly 15 to 40 off-distribution tokens at the very front of the prefix.

`MEASURED-HERE`, **and this checkout is not exposed to it.** Vocello's clone path cannot carry an
instruction, structurally: `GenerationSessionIdentity.clone` has no `deliveryStyle` field
(`GenerationSemantics.swift`), and the runtime's `prepareVoiceCloneInputs` takes only text, clone
prompt, and language. There is no code path by which a Vocello clone request reaches the instruct
branch. The one guard that *is* present in the owned runtime is the 0.6B one
(`supportsCustomInstructionControl` in `Qwen3TTS.swift`), which matches upstream.

### 2.2 Voice Design re-invents the voice on every call

`OFFICIAL`, from a Qwen maintainer (quoted in koboldcpp discussion #2192): VoiceDesign *"can create
voices with accurate instructions. However, the voice can vary, as it cannot re-use a voice."*
Base *"supports consistent voice cloning from a reference audio, however you cannot use any
instructions on the voice."* The maintainer's recommended workflow is to design the voice once,
then clone it for consistency.

The consequence is a genuine architectural fork, and it cannot be avoided by prompt wording:

| Approach | Identity | Per-utterance delivery |
| --- | --- | --- |
| VoiceDesign per utterance | drifts every call | works |
| VoiceDesign once → clone prompt → Base | locked | inert |
| CustomVoice (preset speaker + instruction) | locked | works |

`RESEARCH`. This is why the literature separates the two. PromptTTS++ (arXiv:2309.08140) builds a
*speaker prompt* "designed to be approximately independent of" the style prompt. CapTalk
(arXiv:2604.08363) does it architecturally, with KL regularization that "encourages the shared
stable component to be preserved while attenuating segment-specific affective variation."
ControlSpeech (arXiv:2406.01205) names the residual tension that no architecture removes: achieving
whisper while preserving a specific speaker identity "requires careful balancing since whisper
fundamentally alters acoustic properties." Some delivery instructions will always perturb perceived
identity.

`MEASURED-HERE`. Vocello's Custom mode is the third row — preset speaker plus instruction — so it
gets both. Design mode is the first row and its identity drift per call is expected upstream
behavior, not a defect in our prompt assembly.

---

## 3. Script text

The script is not just content. It is the only prosodic-timing control the model exposes.

`OFFICIAL`. Qwen3-TTS does not parse SSML, does not accept pause markers, and does not accept
inline tags. Timing comes from punctuation.

`MEASURED-HERE`, folded in from [`../qwen_tone.md`](../qwen_tone.md) (2026-06-11), whose
punctuation mapping is its most durable content:

| Cue | Effect |
| --- | --- |
| Period | Sentence-end pause, the longest within a paragraph |
| Comma, semicolon, colon | Short pause |
| Blank line between paragraphs | Paragraph-level pause |
| Question mark, exclamation mark | Sentence-end pause with matching prosody |

Not reliable pause cues:

- **Ellipsis (`...`)** — read as text, not as a long pause.
- **Hyphens and dashes** — treated as continuation.
- **Repeated commas or extra spaces** — collapsed; they do not lengthen anything.

For a longer beat, end the sentence and start a new one. For a paragraph break, use a blank line.

`COMMUNITY`. Long single generations tend to speed up and compress pauses toward the end. Splitting
into paragraph-sized generations re-asserts the delivery instruction at each boundary and holds
pacing steadier. This is what
[`../../Sources/QwenVoiceCore/LongFormPlanning.swift`](../../Sources/QwenVoiceCore/LongFormPlanning.swift)
already does for long-form projects.

`COMMUNITY`. Qwen3-TTS inherits Qwen3's text understanding, so unnormalized text with punctuation
intact is the right input; pre-normalizing numbers and abbreviations into words removes information
the model uses.

---

## 4. Delivery instructions

### 4.1 What upstream actually shows

`OFFICIAL`. The instruction examples in upstream's own materials, verbatim:

| Source | Instruction |
| --- | --- |
| README, CustomVoice | `用特别愤怒的语气说` |
| README batch, CustomVoice | `["", "Very happy."]` |
| Model Studio docs | `Say it in a very angry and disappointed tone` |
| Model Studio docs | `Speak slowly and professionally, like giving a formal speech` |
| README, VoiceDesign | `Speak in an incredulous tone, but with a hint of panic beginning to creep into your voice.` |
| README, VoiceDesign | `Male, 17 years old, tenor range, gaining confidence - deeper breath support now, though vowels still tighten when nervous` |
| mlx-audio README | `Very happy and excited.` |

Two things are worth noticing. CustomVoice examples are short — three to nine words — and name the
emotion in plain language, with intensifiers used freely. And the last VoiceDesign example is a
**bare comma-delimited attribute list with no sentence structure at all**, in the official README:
structured attribute lists are in-distribution.

### 4.2 The benchmark says explicit acoustic enumeration wins

`RESEARCH`, and this is the strongest evidence available on instruction *style*. Qwen3-TTS is
evaluated on InstructTTSEval (arXiv:2506.16381), whose three tasks are three granularities of the
same instruction:

- **APS** (Acoustic-Parameter Specification) — explicit instructions covering all twelve features:
  gender, pitch, texture, clarity, fluency, speed, accent, age, volume, emotion, tone, personality.
- **DSD** (Descriptive-Style Directive) — the same content rewritten by an LLM into free-form
  prose, with 20 to 50 percent of the feature mentions randomly dropped.
- **RP** (Role-Play) — a role or scenario only, e.g. *"a nervous interview applicant"*, with no
  vocal traits stated.

`OFFICIAL`, technical report Table 8:

| Model | ZH APS | ZH DSD | ZH RP | EN APS | EN DSD | EN RP |
| --- | --- | --- | --- | --- | --- | --- |
| Qwen3-TTS-12Hz-1.7B-CustomVoice | 83.0 | 77.8 | 61.2 | 77.3 | 77.1 | 63.7 |
| Qwen3-TTS-12Hz-1.7B-VoiceDesign | 85.2 | 81.1 | 65.1 | 82.9 | 82.4 | 68.4 |
| Gemini-flash (upper bound) | 88.2 | 90.9 | 77.3 | 92.3 | 93.8 | 80.1 |
| GPT-4o-mini-tts | 54.9 | 52.3 | 46.0 | 76.4 | 74.3 | 54.8 |

Every model scores **APS > DSD > RP**, and the APS-to-RP gap on our checkpoint is roughly twenty
points. **Explicit acoustic specification is followed measurably better than free prose, and free
prose beats persona or scenario framing by a wide margin.**

This matters because it *supports* the repository's oldest and least-sourced instinct. The claim in
[`qwen3-tts-guide.md`](qwen3-tts-guide.md) §6 that "concrete acoustic wording is followed more
reliably than persona-only wording" turns out to be right, for a reason nobody in this repo had
written down. Section 9 adjudicates the rest of that list, which fares worse.

Note also what the twelve features include that our instructions do not touch: **volume and speed
are first-class APS dimensions**, and so is *tone* as distinct from *emotion*.

### 4.3 Three ceilings worth internalizing

`RESEARCH`. Even the SOTA hosted model tops out near 88 on explicit specification and drops to 77
on role-play. Our checkpoint sits at 77 to 83 on APS. **Partial adherence is the expected regime,
not a defect.** A 2024 survey of controllable speech synthesis (arXiv:2412.06602) says the same of
the CosyVoice lineage that Qwen3-TTS descends from: such systems "often produce speech that
deviates from user intent, requiring multiple synthesis attempts", and "emotion and other vocal
traits are often intertwined and span multiple granularities, making fine-grained control
especially difficult."

`RESEARCH`. MoE-TTS (arXiv:2508.11326) names the second ceiling: description-based TTS degrades on
"novel phrasings, unfamiliar linguistic patterns, or descriptions with acoustic properties not well
represented during training." Training captions were LLM-generated from attribute schemas, so
free-written user prose is out-of-distribution by construction. Rewriting user prose toward the
training distribution is an evidence-backed intervention, not a hack.

`MEASURED-HERE` (DP-10, 2026-08-03; statistics corrected by the 2026-08-04 audit). The third
ceiling is the one that bites hardest, and it is not about adherence at all: **this checkpoint's
text-instruction channel moves essentially one arousal-shaped axis.** Eighteen seeds across the
ten then-shipping presets gave cross-preset separability of UAR 0.311 against a 0.100 chance
floor — a decisively real result (permutation p < 0.001 under a null mirroring the exact shipped
procedure). Scoring only the high-arousal cluster (`happy`, `excited`, `surprised`, `dramatic`)
against each other gave UAR 0.278 against a 0.250 chance floor — **no detectable separability**
(permutation p = 0.28; the originally recorded "1.11x chance" reading over-stated an ordinary
null draw, and at 18 seeds the test cannot exclude real separability below ~1.5x chance).

The important part is what this is *not*. Mean prosodic effect size across all ten presets ran
6.5 to 9.5 and was **uncorrelated with separability**: `fearful` at 0.500 recall passed the
directional delivery gate on only 1 take in 18, while `dramatic` (8.2) and `excited` (8.9)
recorded 0.056 recall — a figure whose exact binomial interval [0.001, 0.27] contains the chance
floor, so "below chance" was never demonstrated. These instructions were not under-driving. Every
preset moved prosody hard, and they all moved it the same way. A previous revision cited "arousal
roughly 91% classifiable from acoustics against roughly 55% for valence" as a published figure;
that pair is untraceable to any source and is retracted. The real literature puts prosody-only
valence at roughly a third of arousal's recoverability (adjusted R^2 0.17 vs 0.58, Sauter 2010;
CCC .248 vs .658 for lexically blind models, Wagner 2023) — a bottleneck, not a wall — and human
listeners decode eight emotions at 72% from prosody alone on a fixed neutral sentence (RAVDESS).

`MEASURED-HERE` (DP-18, 2026-08-04, pre-registered confirmatory; roadmap gate is the authority).
The exploratory DP-10 result replicated on entirely fresh seeds in a two-arm sweep: 8-way
separability UAR **0.477** (4-bit, 16 seeds) and **0.375** (8-bit, 18 seeds) against a 0.125
computed floor, permutation p = 0.001 in each arm at 1000 iterations, per-cell claims under
BH-FDR. The valence ceiling was upgraded from hypothesis to result: the pre-registered
**happy-vs-angry 2-way probe sits at chance in both arms** (UAR 0.531 / 0.583 vs a 0.5 floor,
p = 0.43 / 0.24), and `happy` fails FDR in both arms with `angry` as its top confusion each
time. The 8-bit Quality arm separates no better than 4-bit, retiring quantization as a
suspected adherence bottleneck. Protocol, provenance, and statistics:
[`delivery-harness.md`](delivery-harness.md).

Consequence for prompt-writing: **wording cannot buy a distinction this instruction channel does
not carry.** DP-3 (long versus short form), DP-4 (prosodic null), DP-5 (merge form), and DP-6 all
varied instruction text and none moved this. `excited` was folded into `happy` and `dramatic`
dropped on 2026-08-03 — sustained as a product decision (a control whose output cannot be
distinguished from its neighbour is not a control), with the statistical justification corrected
by the audit and then confirmed by DP-18. What a *listener* reliably identifies is narrower
still: the DP-12 blind session (146 trials) heard only `neutral`, `calm`, `whisper`, and `sad`
above chance — exactly the shipped `EmotionPreset.distinctDeliveryIDs` set — while `angry` and
`fearful` are acoustically separable (both clear FDR in both DP-18 arms) yet were never named
correctly by ear (`angry` 0/11; `fearful` heard as sad). Acoustic separability is not listener
recognizability; the UI's distinct-versus-directional-hint split follows the listener. Corrected
record and follow-up program:
[`delivery-control-audit-2026-08.md`](delivery-control-audit-2026-08.md).

### 4.4 Instruction language: Chinese leads on our checkpoint

`OFFICIAL`. The instruction field accepts **Chinese and English only**, regardless of the output
language, with a documented ceiling of 1,600 tokens on the hosted surface.

`OFFICIAL`, Table 8 above: on CustomVoice-12Hz — the checkpoint Vocello uses for delivery control —
Chinese beats English on APS by 5.7 points and on DSD by 0.7, while English edges RP by 2.5. The
asymmetry is real and it favours Chinese.

`UNVERIFIED`. Whether a Chinese instruction paired with English output text transfers cleanly is
undocumented and I found no experiment either way. Worth an A/B (§10.5); do not ship it on faith.

### 4.5 What does not work

`COMMUNITY`, well-evidenced. Upstream issue #248 systematically tested twelve instructions with
audio attached and found emotion and style instructions (happy, sad, embarrassed, news broadcast,
angry, disgusted, fearful, surprised, whispering) **do** take effect, while **dialect** instructions
(Sichuan, Shanghai, Cantonese) are ignored — output stays Mandarin. The reporter's own conclusion:
*"the current instruction tuning focuses on prosody and emotion, not dialect switching."* This is
also the best public evidence that emotion instructions genuinely work on CustomVoice.

`COMMUNITY`. Accent requests are unreliable in general, and **accent is conspicuously absent from
Alibaba's own voice-design dimension table**. Reports describe English output reverting to standard
American or carrying a Chinese accent. Cloning from accented reference audio is the documented
workaround.

`COMMUNITY`. Duration control ("finish within five seconds") has no effect, which is consistent
with there being no duration conditioning anywhere in the architecture.

`COMMUNITY`, **and actively wrong**: several SEO sites present `[sad]`, `[whispers]`, `[gasp]`,
`[laughing]` as "Qwen3 TTS emotion tags." These belong to the DashScope-hosted
`qwen-audio-3.0-tts-*` family, a different product with an inline-tag interface. Alibaba's own docs
draw the line explicitly. Feeding `[angry]` to Qwen3-TTS synthesizes the literal characters. A
feature request to add inline tags (upstream discussion #238, 24 upvotes) has no maintainer reply.

`OFFICIAL`. CosyVoice conventions do not carry over either. CosyVoice prepends a description
followed by `<|endofprompt|>` and accepts inline `[laughter]` / `<strong>` markers. `<|endofprompt|>`
appears nowhere in the Qwen3-TTS codebase or tokenizer special tokens; Qwen3-TTS replaced that
convention with the ChatML user turn. Any CosyVoice-derived prompt engineering is wrong here.

---

## 5. Voice design descriptions

### 5.1 Qwen's own dimension table

`OFFICIAL`, from the Model Studio Voice Design documentation:

| Dimension | Documented example terms |
| --- | --- |
| Gender | male, female, neutral |
| Age | child (5–12), teenager (13–18), young adult (19–35), middle-aged (36–55), senior (55+) |
| Pitch | high, medium, low, slightly high, slightly low |
| Speed | fast, medium, slow, slightly fast, slightly slow |
| Emotion | cheerful, calm, gentle, serious, lively, composed, soothing |
| Characteristics | resonant, crisp, husky, mellow, sweet, deep, powerful |
| Use case | news broadcast, advertising, audiobook, animation character, voice assistant, documentary narration |

Absent from that table and unreliable in practice: **accent, breathiness, roughness/rasp, recording
quality, reverb**. "Gentle rasp" maps onto "husky" at best.

`OFFICIAL`, Alibaba's five principles, verbatim: *"(1) Be specific, not vague (2) Be
multi-dimensional, not one-dimensional (3) Be objective, not subjective (4) Be original, not
imitative (5) Be concise, not redundant."*

### 5.2 The in-distribution shape

`OFFICIAL`. The eight examples shipped in the Qwen3-TTS Voice Design demo space are the closest
thing to canonical prompts that exists:

> A clear and natural female voice, moderate speed, stable tone, suitable for news broadcasting or
> daily conversation.

> Standard pronunciation with a dramatic, sobbing quality. The voice is slightly raspy and tense,
> conveying deep sorrow and desperate pleading.

> A calm and confident tone. The speed is steady, with very clear articulation. The voice should
> feel firm and certain, with a slight downward inflection at the end.

> A bright, high-pitched young girl's voice. Lively and animated tone that engages the listener,
> with a loud and clear volume reflecting an active personality.

The demo's own UI names five slots: **persona (gender, age) · pace · timbre · emotion · scenario**.
And note the recurring closing clause across nearly every official Qwen example — *"suited for
&lt;use case&gt;"*. That is a training-distribution signature, cheap to append.

### 5.3 The controlled vocabulary from the literature

`RESEARCH`. Parler-TTS's Data-Speech pipeline publishes the only complete public ladder, and it is
directly reusable as a snapping target for user prose:

| Axis | Rungs |
| --- | --- |
| Speaking rate | very slowly · slowly · slightly slowly · moderate speed · slightly fast · fast · very fast |
| Expressivity | very monotone · monotone · slightly expressive and animated · expressive and animated · very expressive and animated |
| Pitch | very low-pitch · low-pitch · slightly low-pitch · moderate pitch · slightly high-pitch · high-pitch · very high-pitch |
| Recording clarity | very noisy · noisy · slightly noisy · balanced in clarity · slightly clean · clean · very clean |
| Proximity | very distant-sounding · distant-sounding · slightly distant-sounding · slightly close-sounding · very close-sounding |

Every rung is built as `very X / X / slightly X / neutral`. Note the ladder contains **no age, no
timbre, no emotion axis** — Parler controls gender, pitch, rate, expressivity, noise, reverb, and
accent only. LibriTTS-P (arXiv:2406.07969) adds the useful distinction between *perception words*
(observable: gender, voice strength) and *impression words* (subjective: "cool", "cute"), with the
same three-level intensity modifier on each.

### 5.4 Vendor guidance worth borrowing

`OFFICIAL` (Inworld, for a different product, but the most prescriptive ordering published
anywhere):

> Distinctive Qualities → Gender → Language/Accent → Age → Tone → Delivery Style → Pacing →
> Additional Qualities → Audio Quality

with three rules that transfer well: use age *ranges* ("mid-20s to early 30s") rather than
"young"/"old"; put texture words ("raspy", "breathy") in the **middle**, softened ("slight",
"subtle", "natural"), so they are not exaggerated; and **close with a recording-quality anchor**
("Perfect broadcast quality audio."), which Inworld calls "especially valuable when describing
textural qualities potentially mistaken for degradation."

`MEASURED-HERE`, **DP-5, 2026-08-03 — the quality anchor was tested on this model and it hurt.**
Appending "Perfect broadcast quality audio." to the Design instruction cost 11 surviving features
against the shipped form (35 against 46) over 8 paired seeds, the worst of three arms. It is sound
advice for the vendor who published it and it does not transfer here. **Do not adopt it**, and treat
the rest of this borrowed guidance as untested rather than recommended — the age-range and
softened-texture rules above have not been measured either.

The underlying claim it was meant to address — that a rasp descriptor with no anchor reads as
recording degradation — remains plausible and unmeasured on this model.

`OFFICIAL` (ElevenLabs): avoid audio-FX terms — "reverb", "echo", "phone", "tape" — they degrade
output. Do not misuse "accent" to mean intonation or emphasis. "Foreign" and "exotic" produce
inconsistent results.

`COMMUNITY`, the conflict rule everyone states and nobody quantifies: contradictory descriptors
("high-pitched deep bass", "fast-paced" with "slow, deliberate") make the model favour one
arbitrarily. VoiceSculptor's pre-submission checklist is worth porting into brief validation: under
the character limit, at least three distinct dimensions, no subjective evaluations ("great",
"favorite"), no celebrity references, no repetitive phrasing, clear usage context, concrete
perceptible language.

`MEASURED-HERE`. Vocello already enforces the celebrity-imitation rule at the contract level
(`validateQwenPromptContract` in `GenerationSemantics.swift` rejects voice-imitation instructions in
both Custom and Design).

---

## 6. Mode interaction

### 6.1 One field carries both

`OFFICIAL`. `generate_voice_design(text, instruct, language)` has exactly **one** conditioning
string. There is no separate voice-identity slot and delivery slot. A product with two fields must
merge them, and **upstream gives no guidance on how.**

`MEASURED-HERE`. Vocello merges them with a labeled template
(`designInstruction` in `GenerationSemantics.swift`):

```swift
return "Voice character: \(description). Delivery: \(emotion)."
```

`MEASURED-HERE`, **DP-5, 2026-08-03 — tested against two alternatives; the repo invention won.**
The labeling has no upstream provenance and upstream's examples are unlabeled attribute lists, so
this was a real open question. Three arms, identical seeds and cells, 8 paired seeds:

| arm | features surviving | cross-preset error | mean recall |
| --- | --- | --- | --- |
| `Voice character: X. Delivery: Y.` (shipped) | **46** | **66.2%** | **0.338** |
| plain concatenation `X. Y.` | 41 | 68.8% | 0.312 |
| plain plus a closing quality anchor | 35 | 68.8% | 0.312 |

**Kept, with the strength of the evidence stated plainly.** The shipped form leads on all three
metrics, but 46 against 41 is a 12% edge — far weaker than DP-3's 57 against 33 — and per cell the
picture is incoherent: `dramatic.strong` gives 7/0/0 favouring labeled while `sad.strong` gives
0/6/5 favouring the others. At 8 seeds that is a small mean difference with loud noise around it.
Treat labeled-over-plain as **directional, not settled**.

The firmer result is the third arm: the borrowed quality anchor is the worst of the three (§5.4).

Design mode is also structurally noisier than Custom, because the one field carries voice identity
*and* delivery, so changing the delivery changes who is speaking. Two things argue the signal
survived that anyway: the ordering is consistent across three independent metrics, and all three
arms show similar cross-preset error, which is what drift affecting every arm equally looks like.
Note also that `plain` and `anchored` are identical to three decimals on both separability metrics,
so those numbers are coarser than they appear — the feature counts carry more information.

`RESEARCH`, the counter-position, stated for honesty: VoxInstruct (arXiv:2408.15676) argues the
opposite, that forcing a content/description split "restricts the ability to control speech at a
fine-grained level", and deliberately unifies them. Since Qwen3-TTS has literally one field,
VoxInstruct's stance is the one our architecture is forced into regardless.

### 6.2 Pace belongs in exactly one place

`OFFICIAL` (Hume, the one major vendor shipping the same two-field design): *"use the `speed`
parameter rather than embedding pace instructions in the description."* Generalized: a
characterological pace belongs to identity, a per-utterance pace belongs to delivery, and it should
never appear in both. Duplication across the two halves of a merged string is a self-conflict of
exactly the kind §5.4 warns about.

`MEASURED-HERE`. Vocello's Design mode can produce exactly this collision today: a brief that says
"deliberate pacing" merged with a Calm preset that says "smooth unhurried pacing" ships both.

### 6.3 Neutral is a real absence

`MEASURED-HERE`. Vocello treats Neutral as "no meaningful instruction" only for typed synonyms —
empty, `neutral`, `normal tone`, `neutral tone` (`isNeutralDeliveryInstruction`). The shipped
Neutral **preset** is not empty; it sends a 140-character instruction asking for an even, level,
slightly monotone read. That was deliberate: an uninstructed request left cross-seed delivery
unconstrained. It does mean "Neutral" is an instructed delivery, not the absence of one, and any
experiment using Neutral as a control must account for that.

---

## 7. Sampling and decode budget

`OFFICIAL`, from the checkpoint's `generation_config.json`:

```json
{ "do_sample": true, "repetition_penalty": 1.05,
  "temperature": 0.9, "top_p": 1.0, "top_k": 50,
  "subtalker_dosample": true, "subtalker_temperature": 0.9,
  "subtalker_top_p": 1.0, "subtalker_top_k": 50,
  "max_new_tokens": 8192 }
```

`OFFICIAL`. The published InstructTTSEval scores in §4.2 were produced at exactly these defaults,
with `max_new_tokens=2048` and bf16. That is the strongest available statement about sampling:
these settings are what the reported instruction-following numbers were measured at.

`MEASURED-HERE`. [`qwenvoice_contract.json`](../../Sources/Resources/qwenvoice_contract.json)
matches on every value, and the owned runtime plumbs the **subtalker sampler independently** rather
than pinning it to the backbone (`Qwen3RequestSamplingPolicy.subtalker`). A port that exposes only
one temperature silently pins the residual-codebook sampler, which can degrade timbre even when
prosody is right; this checkout does not have that bug.

`MEASURED-HERE`. The decode budget is a **fixed constant** (`officialQualityDefault.n`), not derived
from text length. A slow or heavy delivery therefore cannot clip against a text-proportional
budget — a failure mode reported against other MLX TTS ports. Reaching the cap before EOS is
detected and the output discarded rather than silently truncated (`GenerationOutputAdapter`).

`OFFICIAL`, negative findings, stated plainly: there is **no classifier-free guidance, no guidance
scale, and no instruction-weighting parameter** in Qwen3-TTS. And **no upstream source anywhere
links instruction-following quality to sampling settings.** Any claim that lowering temperature
improves instruction adherence here is `UNVERIFIED`.

`UNVERIFIED`. Upstream benchmarks are bf16; Vocello ships 8-bit quants. No upstream evaluation of
instruction adherence under quantization exists. Instruction following is generally the first
capability to degrade under quantization, so this is a real open question (§10.6) rather than a
settled one.

---

## 8. What Vocello sends today

`MEASURED-HERE`, from a code audit of this checkout on 2026-08-02.

### 8.1 The audit

| Property | State |
| --- | --- |
| ChatML instruct turn | matches upstream byte for byte |
| System turn | none (correct) |
| Clone receives an instruction | **no** — structurally impossible, no `deliveryStyle` on the clone identity |
| 0.6B instruction guard | present, matches upstream |
| Subtalker sampler | plumbed independently |
| Decode budget | fixed constant, not text-derived |
| Sampling defaults | match the checkpoint exactly |
| `think`/`nothink` branch | implemented; Design and Clone fall back to `nothink` |
| Design merge template | `Voice character: … Delivery: …`, a repo invention |
| English diction sentence | appended conditionally — see below |
| Instruction receipt (2026-08-04) | every instructed take's telemetry row stamps `instructChars`/`instructDigest` from the request payload; the delivery harness verifies it fail-closed against the bench manifest echo ([`delivery-harness.md`](delivery-harness.md) §4) |

Three of the four hazards that the research pass flagged as likely causes of "delivery sounds off"
in MLX ports do not apply to this checkout. That is worth stating plainly, because it narrows the
search.

### 8.2 The one defect the audit found

`MEASURED-HERE`. Every English instruction is candidate for an appended 76-character boilerplate
sentence:

> `Native English pronunciation with clear English diction and natural stress.`

The append is skipped when the base instruction already contains any of eight diction tokens
(`clear`, `clearly`, `diction`, `articulation`, `pronunciation`, `clarity`, `intelligible`,
`understandable`) — a reasonable rule, added to stop the model receiving redundant clarity
instructions that crowd out the emotion signal.

But which presets tripped that rule was incidental to their wording, and — on the then-shipping
ten-preset × two-tier roster (the roster was cut to 8 on 2026-08-03 and the user-facing intensity
control retired 2026-08-02; see §4.3 and
[`delivery-control-audit-2026-08.md`](delivery-control-audit-2026-08.md)) — **three presets tripped
it on one intensity tier and not the other**:

| Preset | `normal` | `strong` | Boilerplate delta |
| --- | --- | --- | --- |
| happy | suppressed (142 chars) | appended (270 chars) | **+76 on strong only** |
| surprised | suppressed (169 chars) | appended (239 chars) | **+76 on strong only** |
| dramatic *(retired 2026-08-03)* | suppressed (173 chars) | appended (260 chars) | **+76 on strong only** |
| sad | suppressed | suppressed | none |
| the other six | appended | appended | none |

For happy, surprised, and dramatic, the `strong` tier differed from `normal` not only by its
emotional wording but by an extra sentence about English diction that has nothing to do with
intensity. **The intensity-tier measurement recorded in
[`EmotionPreset.swift`](../../Sources/QwenVoiceCore/EmotionPreset.swift) — that `strong` moves cells
sideways rather than further apart — was run across a matrix in which three of ten presets had a
confounded tier comparison.** That does not overturn the finding, and it does not explain the six
unaffected presets, but it does mean the finding is weaker than it reads.

**Fixed 2026-08-02, without touching preset copy.** The append now resolves preset-wide: if any
tier of a preset asks for clarity, the whole preset suppresses it, so the two tiers can never differ
by boilerplate alone. [`check_delivery_instructions.py`](../../scripts/check_delivery_instructions.py)
fails the build if that resolution is removed.

`MEASURED-HERE`, **DP-4, 2026-08-02 — prosodic null. The sentence stays.**

Only six of the then-shipping ten presets received the append at all — `neutral`, `angry`,
`fearful`, `excited` (folded into `happy` when the roster was cut on 2026-08-03), `calm`,
`whisper`. The other four already contained a diction token and suppressed it, which gave the
experiment a built-in control: 8 cells that must be byte-identical across arms and 12 that must
differ. Over 13 paired seeds that held exactly — **104/104 identical, 0/156 identical** — so the
null below is a real null and not a harness that failed to vary anything.

| | features surviving | mean recall | cross-preset error |
| --- | --- | --- | --- |
| append on | 28 | 0.20 | 70.9% |
| append off | 25 | 0.22 | 72.1% |

Differences that small, pointing in opposite directions on the two metrics, are noise at this seed
count. Per cell it is incoherent rather than mixed: `calm` and `fearful` look better with it,
`neutral` and `whisper.strong` disagree with themselves between metrics. The one consistent signal
is that **`angry` is worse with it** on both metrics — `angry.strong` falls from 0.31 recall to
0.00 — which is worth remembering if angry copy is ever revised.

**Intelligibility was tested too, and the test has no power here.** The sentence asks for diction,
not prosody, so a prosodic null proves little on its own. Transcribing bench audio with
`whisper-small` gave **28 of 29 cells at exactly 0.000 WER** (mean 0.0057). Clean 24 kHz synthesis
of an 18-word sentence saturates ASR, so a WER A/B would compare 0.00 against 0.00. A future
attempt needs a harder condition — longer text with proper nouns and numbers, or a deliberately
weaker ASR — before it can discriminate. Do not read the saturated result as "the append does
nothing"; it means this instrument cannot see whether it does.

Kept on that basis: no measured prosodic effect, no usable intelligibility evidence either way, and
removal would be an unmeasured change to six presets. The knob stays registered and inert so the
question can be reopened when there is an instrument that can answer it.

### 8.3 What now gates the instruction copy

Delivery quality needs audio, models, and seeds, so it can never be an ordinary CI gate — but the
text-level ways the copy can be wrong are deterministic, and
[`check_delivery_instructions.py`](../../scripts/check_delivery_instructions.py) runs inside
`check_project_inputs.sh` on every commit and push. It fails outright on **append parity** across a
preset's tiers and on **repeated intensifiers**, both indefensible whatever the right copy turns out
to be. It reports **tier direction inversions** and **copy-versus-expectation conflicts** against
[`delivery-instruction-contract.json`](../../config/delivery-instruction-contract.json): a listed
finding is known-open and passes, a new one fails, and a listed finding that no longer occurs also
fails so the list cannot rot.

It deliberately does **not** assert that the copy must conform to a delivery expectation. Those
expectations were seeded before the project had any voice-quality measurement, so a conformance
gate would fit copy to an unvalidated target — the failure mode this whole document exists to stop.
It reports that the two disagree and that one of them is wrong, without presuming which. Two
findings are acknowledged today, both on `angry`: its tiers invert the pitch axis, and its `normal`
copy contradicts a `required` pitch expectation.

---

## 9. Adjudicating the claims already in this repository

The preset copy was written against five rules stated as canon in
[`EmotionPreset.swift`](../../Sources/QwenVoiceCore/EmotionPreset.swift) and four "prompt-writing
lessons" in [`qwen3-tts-guide.md`](qwen3-tts-guide.md) §6. Neither list cites anything. Here is what
each is actually worth.

| Claim | Verdict |
| --- | --- |
| Concrete acoustic wording beats persona-only wording | **`RESEARCH`, supported.** InstructTTSEval APS 77–83 versus RP 61–64 on our checkpoint. The strongest-supported item on either list. |
| Combine emotion + pace + pitch + timbre | **`OFFICIAL`, supported.** Alibaba's "be multi-dimensional, not one-dimensional". The twelve APS features go further: volume, speed, and tone-distinct-from-emotion are also first-class and our copy is thin on them. |
| Imperative verbs (Speak / Whisper / Narrate) are followed more reliably | **`UNVERIFIED`.** Upstream examples use both imperative (`Speak slowly and professionally`) and descriptive (`Male, 17 years old, tenor range…`) forms with no stated preference. Plausible, unsourced. |
| Negative constraints work (`no laughing`, `never shout`) | **`UNVERIFIED`, and the one nearby datapoint is negative.** No upstream source endorses them. OV-InstructTTS (arXiv:2601.01459) Table 3 found bare paralinguistic tags *reduced* adherence by 0.72 while reasoning-mediated attributes raised it by 2.08. Eight of the ten then-shipped presets spent characters on negation that nothing supports (roster cut to 8 on 2026-08-03; the surviving copy still carries negation clauses). |
| Intelligibility clauses help bound extreme emotions | **`UNVERIFIED` as written, with a documented cousin.** The vendor-supported version is a *recording-quality anchor* at the end ("Perfect broadcast quality audio."), which addresses texture-mistaken-for-degradation. Ours is a *command to the speaker* ("stay fully audible") in the middle. Different mechanism, and ours is what trips the §8.2 boilerplate rule. |
| Avoid stacked intensifiers; `very very very happy` adds no value | **Partly contradicted.** Upstream's own examples are `Very happy.` and `Say it in a very angry and disappointed tone`. The defensible claim is that *repetition* adds nothing; our copy over-generalized it into avoiding intensifiers, and further into avoiding naming the emotion plainly at all — while emotion is an explicit APS feature. |
| High-arousal instructions trigger literal laughter or breath sounds | **`COMMUNITY`, plausible.** Reported for extended generations. The `no laughing` remedy is the unverified part, not the symptom. |

`MEASURED-HERE`. Two further corrections, both **applied 2026-08-02**:
[`qwen3-tts-guide.md`](qwen3-tts-guide.md) and [`../qwen_tone.md`](../qwen_tone.md) each stated the
preset grid with the wrong intensity-tier count, contradicting the guide's own §6 table and the
then-shipped code. The correct figure at the time was **10 presets × 2 intensity tiers**; the
roster has since been cut to 8 presets (2026-08-03) and the user-facing intensity control retired
(2026-08-02), each surviving preset shipping its `strong` copy — see §4.3 and
[`delivery-control-audit-2026-08.md`](delivery-control-audit-2026-08.md).
[`doc_metadata.py`](../../scripts/doc_metadata.py) now derives the current counts from
[`EmotionPreset.swift`](../../Sources/QwenVoiceCore/EmotionPreset.swift) and fails the build on any
document that contradicts them.

`MEASURED-HERE`. [`../qwen_tone.md`](../qwen_tone.md) additionally attributes "negative constraints
work and are officially endorsed" and "the official instruction-writing principle" to upstream
without a link. The first is unverified per the table above. The second is real — it is Alibaba's
"be multi-dimensional" — but the attribution was never traceable. Its prescription that "1–3 dense
sentences is the sweet spot" is reasonable for *voice descriptions* (two independent community
guides converge on it) and unsupported for *delivery instructions*, where the official examples are
three to nine words.

### 9.1 The instruction-length question, stated honestly

Our angry `strong` instruction is 141 characters. Upstream's is `Say it in a very angry and
disappointed tone` — 45. Ours enumerates timbre, attack, pitch, and volume; upstream's names the
emotion twice with an intensifier.

It is tempting to read that contrast as the root cause. It is weaker evidence than it looks:
examples are illustrations, not prescriptions, and the benchmark evidence in §4.2 says explicit
enumeration is the *strongest* regime, not the weakest.

`MEASURED-HERE`, **2026-08-02 — settled, and the contrast is not the cause.** DP-3 ran both forms
over 12 paired seeds × 20 cells, identical seeds and cells, one variable: an official-style short
form (`Very happy.`, `Say it in a very angry tone`) against the shipped long form. Features
surviving Benjamini-Hochberg correction:

| | features surviving | cells won |
| --- | --- | --- |
| shipped long form | **57** | 9 |
| official-style short form | 33 | 2 |

The shipped copy is **better**, not worse, and by a wide margin. Effect sizes move the same way —
`whisper.normal` `cpp_delta_db` is d=−3.50 shipped against d=−1.16 short.

This confirms §4.2 and retires the contrast above as a hypothesis. Our copy is APS-shaped;
`Very happy.` is a bare emotion label, which InstructTTSEval scores in the weakest regime. Upstream's
short examples are illustrations of the *interface*, not a recommended register — reading them as
style guidance was the error, and the benchmark said so before the measurement did.

**What the same run showed instead**, and it matters more: five of the then-shipping presets moved
nothing that survives correction under *either* form — `happy`, `excited`, `neutral`,
`dramatic.normal`, `surprised.normal` (`excited` and `dramatic` have since been retired,
2026-08-03). Cross-preset separability failed in both arms (67.5% error shipped, 77.6%
short), with `happy.normal` at 0.00 recall against a 5% chance floor. Instruction register is not
the lever for those presets; nothing about the wording made them separable.

`MEASURED-HERE`. Three different instruction-length limits exist in this checkout, and they measure
different things rather than disagreeing: 2,048 characters is the Model Studio `voice_prompt`
ceiling mirrored in
[`VoiceDesignBriefCatalog.swift`](../../Sources/SharedSupport/Services/VoiceDesignBriefCatalog.swift),
1,600 tokens is the hosted instruction ceiling, and the 240-character check in
[`IOSDeviceDiagnosticsRunner.swift`](../../Sources/iOS/IOSDeviceDiagnosticsRunner.swift) is a
diagnostics-harness guard on one environment override, not a product limit. The "500-character cap"
named in the `EmotionPreset` canon corresponds to none of them and has no traceable origin.

---

## 10. Open questions, and how to settle them

Ordered by expected value. **None of these is a recommendation to change preset copy.** Acting on
unvalidated prompt guidance is the failure mode this document exists to stop; each item below is a
measurement first.

The harness already exists — the complete operator's reference is
[`delivery-harness.md`](delivery-harness.md). In brief:
[`scripts/delivery_separability.py`](../../scripts/delivery_separability.py) scores cross-preset
separability (computed floors, permutation null, per-cell BH-FDR, `--presets` subset probes,
exploratory/confirmatory designation), [`scripts/bench_delivery_prosody.py`](../../scripts/bench_delivery_prosody.py)
turns a `bench --delivery` run into a receipt-verified paired sidecar,
[`scripts/delivery_matrix_report.py`](../../scripts/delivery_matrix_report.py)
runs a seeded delivery matrix, and [`scripts/delivery_statistics.py`](../../scripts/delivery_statistics.py)
provides paired Wilcoxon tests, Cohen's d_z, BCa intervals, and Benjamini-Hochberg correction. Each
experiment below is a matrix run plus a paired comparison, pre-registered per
[`delivery-harness.md`](delivery-harness.md) §6.

1. ~~**Short versus long instruction.**~~ **SETTLED 2026-08-02 — the shipped long form wins,
   57 surviving features against 33 over 12 paired seeds.** The benchmark's prediction held and the
   official-examples reading was wrong; see §9.1. Reproduce with
   `QWENVOICE_DEBUG=1 QWENVOICE_DELIVERY_INSTRUCTION_SET=short`, registered in
   [`runtime-debug-knobs.json`](../../config/runtime-debug-knobs.json) and inert without the master
   gate. **Do not retry this as a way to fix delivery**: the same run showed `happy`, `excited`,
   `neutral`, `dramatic.normal` and `surprised.normal` moved nothing under *either* form
   (`excited` and `dramatic` have since been retired, 2026-08-03), so the register is not the
   lever for the presets that failed.
2. ~~**The Design merge template.**~~ **SETTLED 2026-08-03 — shipped form kept, quality anchor
   rejected.** 46 / 41 / 35 surviving features across labeled / plain / anchored over 8 paired
   seeds; see §6.1 for the numbers and §5.4 for the anchor. Reproduce with
   `QWENVOICE_DESIGN_MERGE_FORM=plain|anchored`. The labeled-over-plain margin is directional
   rather than settled — worth revisiting at higher seed count if Design work resumes.
3. ~~**The English diction sentence.**~~ **SETTLED 2026-08-02 — prosodic null; kept.** See §8.3.
   The tier-parity half of this item was a bug and was fixed separately (§8.2).
4. **`language="english"` versus `auto` on Design.** Different `think`/`nothink` prefill branch
   (§1.3), and the technical report credits the thinking pattern specifically for instruction
   following.
5. **A Chinese instruction against the English one** on CustomVoice, output text held constant.
   Table 8 says Chinese leads English by 5.7 APS points on our exact checkpoint (§4.4).
`MEASURED-HERE`, **DP-6, 2026-08-03 — an instruction clause can be simply ignored.** Over 23 seeds
the shipped `angry` copy moves pitch **+5.98 semitones** (d=1.40, win rate 0.91), confirming the
`required` +1 expectation. But the retired `angry.normal` copy asks for *"a lower clipped tone"* and
the model **raises** pitch anyway. The contradiction our text-level gate flagged is real in the
prose and absent from the audio, which is worth knowing before rewriting copy to resolve a conflict
that only exists on the page.

The same run carries a methodological caution. DP-3's *aggregate* comparison (57 features against
33) was robust, but its *per-cell* numbers were not: `angry.normal` showed a 12/12 win rate for
pitch at n=12 and fails to survive correction at n=23 on a different seed range, while
`angry.strong` is stable across both (+4.48 then +5.98, win ≈0.91). **Read per-cell rows from a
12-seed matrix as indicative only.** The tier decision in §8.2 leaned on such rows; the aggregate
that decision actually rested on was much stronger than any single cell in it.

6. **Negative constraints and intensifiers**, individually. Eight of the then-shipping ten presets
   carried a negation clause that no source supports, and most of the surviving eight-preset
   roster's copy still does; OV-InstructTTS's ablation points the other way.
7. **8-bit versus bf16 instruction adherence.** Partially answered by DP-18 (2026-08-04): the
   4-bit and 8-bit quantizations were measured head-to-head on fresh seeds and the 8-bit arm
   separates no *better* (UAR 0.375 vs 0.477, overlapping per-cell intervals) — quantization is
   not the adherence bottleneck between our own tiers. The bf16 comparison itself remains
   unmeasured; upstream measures bf16 only, we ship quantized (§7).

`UNVERIFIED`, and worth stating so nobody re-derives it: upstream's answer for emotion control on
*cloned* voices is `Qwen3-TTS-25Hz-1.7B-VoiceEditing`, announced by a maintainer with no committed
date. Until it exists, the supported path is to bake the delivery into a designed reference and
clone that.

---

## Sources

Official:

- [QwenLM/Qwen3-TTS](https://github.com/QwenLM/Qwen3-TTS) — repository, README support matrix, `qwen_tts/inference/qwen3_tts_model.py`, `qwen_tts/core/models/modeling_qwen3_tts.py`
- [Qwen3-TTS Technical Report (arXiv:2601.15621)](https://arxiv.org/abs/2601.15621)
- [Qwen3-TTS-12Hz-1.7B-CustomVoice model card](https://huggingface.co/Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice) · [VoiceDesign model card](https://huggingface.co/Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign) · [Voice Design demo space](https://huggingface.co/spaces/Qwen/Qwen3-TTS-Voice-Design)
- [Model Studio: Voice Design](https://www.alibabacloud.com/help/en/model-studio/qwen-tts-voice-design) · [qwen-tts](https://www.alibabacloud.com/help/en/model-studio/qwen-tts) · [realtime TTS](https://www.alibabacloud.com/help/en/model-studio/qwen-tts-realtime)
- Maintainer statements: upstream issues [#25](https://github.com/QwenLM/Qwen3-TTS/issues/25) and [#14](https://github.com/QwenLM/Qwen3-TTS/issues/14)

Research:

- [InstructTTSEval (arXiv:2506.16381)](https://arxiv.org/abs/2506.16381) — the APS/DSD/RP benchmark Qwen3-TTS is scored on; [dataset, MIT](https://huggingface.co/datasets/CaasiHUANG/InstructTTSEval)
- [Controllable speech synthesis survey (arXiv:2412.06602)](https://arxiv.org/abs/2412.06602)
- [MoE-TTS (arXiv:2508.11326)](https://arxiv.org/pdf/2508.11326) — out-of-distribution description failure
- [OV-InstructTTS (arXiv:2601.01459)](https://arxiv.org/html/2601.01459) — the paralinguistic-tag ablation
- [PromptTTS++ (arXiv:2309.08140)](https://arxiv.org/abs/2309.08140) · [CapTalk (arXiv:2604.08363)](https://arxiv.org/html/2604.08363v1) · [ControlSpeech (arXiv:2406.01205)](https://arxiv.org/pdf/2406.01205) — identity/style separation
- [VoxInstruct (arXiv:2408.15676)](https://arxiv.org/abs/2408.15676) — the counter-position
- [Parler-TTS (arXiv:2402.01912)](https://arxiv.org/abs/2402.01912) · [Data-Speech text bins](https://github.com/huggingface/dataspeech) — the published controlled vocabulary
- [LibriTTS-P (arXiv:2406.07969)](https://arxiv.org/html/2406.07969v1) — perception versus impression words
- [CosyVoice 3 (arXiv:2505.17589)](https://arxiv.org/pdf/2505.17589) — the lineage whose conventions do *not* carry over

Community, quality varies:

- Upstream [issue #248](https://github.com/QwenLM/Qwen3-TTS/issues/248) (best-evidenced: 12 systematic tests with audio) · discussions [#218](https://github.com/QwenLM/Qwen3-TTS/discussions/218), [#231](https://github.com/QwenLM/Qwen3-TTS/discussions/231), [#238](https://github.com/QwenLM/Qwen3-TTS/discussions/238)
- HF discussions [#28](https://huggingface.co/Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice/discussions/28), [#38](https://huggingface.co/Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice/discussions/38)
- Vendor guidance for *other* products, borrowed where it generalizes: [Inworld Voice Design](https://docs.inworld.ai/tts/best-practices/voice-design) · [ElevenLabs Voice Design](https://elevenlabs.io/docs/eleven-creative/voices/voice-design) · [Hume acting instructions](https://dev.hume.ai/docs/text-to-speech-tts/acting-instructions)

## Related documents

- [`qwen3-tts-guide.md`](qwen3-tts-guide.md) — architecture, model variants, speaker roster, parameters
- [`../qwen_tone.md`](../qwen_tone.md) — the earlier app-facing tone guide this document supersedes for provenance questions
- [`benchmarking-procedure.md`](benchmarking-procedure.md) — how to run the matrix the §10 experiments need
- [`../ARCHITECTURE.md`](../ARCHITECTURE.md) §4 — engine core and generation semantics
