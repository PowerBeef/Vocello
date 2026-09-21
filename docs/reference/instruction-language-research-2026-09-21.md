---
status: active
owner: backend-mlx
reviewed: 2026-09-21
summary: Evidence review of instruction versus speech language in local Qwen3-TTS, with French recommendations and an unexecuted controlled evaluation proposal.
sourceOfTruth:
  - Sources/QwenVoiceCore/GenerationSemantics.swift
  - Packages/VocelloQwen3Core/Sources/MLXAudioTTS/Models/Qwen3TTS/Qwen3TTS.swift
  - config/delivery-instruction-contract.json
---
# Should voice descriptions and delivery instructions match the spoken language?

Research date: **September 21, 2026**. Local source baseline: `cf373d7d`.
Scope: Vocello's local Qwen3-TTS 12Hz 1.7B CustomVoice, VoiceDesign and Base paths,
with particular attention to French. This is source research, not a new audio experiment.

## 1. Decision and confidence

**Do not require the instruction language to match the script. Keep English as the current
engineering baseline, allow user-written French instructions, and do not claim that English,
French or Chinese is universally best.**

English is a conservative operational choice: it preserves Vocello's existing canonical prompts
and sits within the instruction languages explicitly documented by the related hosted services.
That is weaker than evidence that English produces the best French speech. No controlled public
experiment answering that specific comparison was located in this review.

| Question | Finding | Confidence and boundary |
| --- | --- | --- |
| Must instruction and speech languages match? | No such requirement exists in the inspected local or upstream generation paths. | High for source behavior; not a guarantee of equal audio quality. |
| Does French output require French descriptions? | No demonstrated requirement. | High against a software requirement; best perceptual outcome remains unresolved. |
| Are French instructions forbidden locally? | No instruction-language rejection or automatic translation was found. | High for inspected paths; comprehension and adherence need measurement. |
| Are English/Chinese the only TTS instruction-training languages? | The examined training report does not establish that exclusive claim. | Unknown training distribution. |
| Is Chinese better than English for the same French script? | Public benchmark scores do not answer this. | Unresolved. |
| Should Vocello translate every instruction into the output language? | No evidence currently justifies that behavior change. | Engineering recommendation, not a measured ranking. |
| Does an English instruction force an English accent? | It does not set the output-language field. Statistical influence remains possible. | Separate code facts from acoustic hypotheses. |
| Does Clone have the same question? | Its shipped path has no delivery instruction; reference audio/transcript conditioning is a different problem. | High for current Vocello behavior. |

## 2. Eight different meanings of “language”

| Surface | Its role | What should agree |
| --- | --- | --- |
| Interface language | Labels, menus and help | User preference; independent of generation. |
| Script language | The words to be spoken | Intended output. A language selector is not a translation request. |
| Output-language hint | Conditioning supplied to the model | The intended spoken language; explicitly French for a controlled French experiment. |
| Voice-description language | Expresses desired identity and vocal characteristics | No proven equality requirement with the script. |
| Delivery-instruction language | Expresses pace, emotion and performance | No proven equality requirement with the script. |
| Built-in speaker's native language | A property of the trained speaker identity | A potential accent/quality factor, not an instruction validator. |
| Clone reference language | Language spoken in the conditioning recording | Its transcript must describe that actual recording, not translate it into the target language. |
| Requested accent/dialect | Desired pronunciation and regional identity | Must be evaluated separately from language and intelligibility. |

Writing a direction in French, requesting French output, and requesting a Quebec French accent
are three different interventions. A French-language description that says nothing about accent
does not specify Quebec pronunciation. Conversely, an English description can explicitly request
Quebec French. Whether the requested regional qualities emerge is an acoustic question.

## 3. What the open implementation proves

Upstream was inspected at commit
[`022e286b98fbec7e1e916cb940cdf532cd9f488e`](https://github.com/QwenLM/Qwen3-TTS/tree/022e286b98fbec7e1e916cb940cdf532cd9f488e)
(March 17, 2026). Its
[Python wrapper, lines 580–767](https://github.com/QwenLM/Qwen3-TTS/blob/022e286b98fbec7e1e916cb940cdf532cd9f488e/qwen_tts/inference/qwen3_tts_model.py#L580)
accepts speech text, instruction and language separately for VoiceDesign/CustomVoice. It validates
supported output languages and input shapes, then tokenizes instructions separately. There is no
requirement that the instruction be detected as the output language. The 0.6B CustomVoice branch
discards instructions; that limitation must not be confused with Vocello's 1.7B Speed tier.

The [underlying model, lines 1909–1978](https://github.com/QwenLM/Qwen3-TTS/blob/022e286b98fbec7e1e916cb940cdf532cd9f488e/qwen_tts/core/models/modeling_qwen3_tts.py#L1909)
prepends instruction embeddings while constructing language/speaker conditioning separately.
Explicit language and `auto` produce different codec prefills. Chinese/auto can also select
speaker-specific dialect conditioning. Therefore an experiment that changes instruction language
*and* switches explicit French to auto is not an instruction-only comparison.

These are separate inputs to a learned model, not acoustically isolated controls. Source separation
rules out a hard equality requirement; it does **not** rule out statistical interactions between
instruction wording, accent, identity and the spoken text.

Tokenization is another limitation on intuition. A multilingual tokenizer can encode French
instructions without proving that the speech model learned every requested French direction.
Likewise, multilingual knowledge in a language-model backbone does not establish the coverage of
the later speech-conditioning training. “The API accepted it” is the lowest evidence threshold.

## 4. Training evidence and the benchmark trap

The [Qwen3-TTS technical report](https://arxiv.org/html/2601.15621v1) describes multilingual training
and instruction conditioning, but does not disclose a full instruction-language × speech-language
training distribution. Table 8 reports the following scores:

| 12Hz 1.7B model | Evaluation split | APS | DSD | RP |
| --- | --- | ---: | ---: | ---: |
| CustomVoice | Chinese | 83.0 | 77.8 | 61.2 |
| CustomVoice | English | 77.3 | 77.1 | 63.7 |
| VoiceDesign | Chinese | 85.2 | 81.1 | 65.1 |
| VoiceDesign | English | 82.9 | 82.4 | 68.4 |

These are benchmark-split results, not the effect of translating an instruction while holding
the speech fixed. Even their numerical direction is mixed. French intelligibility results elsewhere
in that report are not French-instruction adherence measurements. Its published models are also
not a qualification of Vocello's quantized MLX execution. [Technical report, Tables 8–9](https://arxiv.org/html/2601.15621v1).

The [original InstructTTSEval paper](https://arxiv.org/html/2506.16381) defines APS as
Acoustic-Parameter Specification, DSD as Descriptive-Style Directive and RP as Role-Play.
These task names differ from the expansions in Qwen's Table 8 caption. The benchmark contains
1,000 English and 1,000 Chinese cases per task, with generated instructions informed by expressive
speech. Its Gemini judge's reported human agreement varies by task/language; role-play agreement
is lower than acoustic-parameter agreement. Automated scores are not infallible perceptual truth.

The [released dataset](https://huggingface.co/datasets/CaasiHUANG/InstructTTSEval) independently
confirms English/Chinese splits and separate text, APS, DSD, RP and reference-audio fields. The
visible samples couple language-specific scripts and instructions; this is not a released
French-script translation ablation. No French split is listed.

**Causal consequence:** a difference between those splits can reflect scripts, speakers, requested
attributes, accents, instruction complexity or judge behavior. Subtracting their scores cannot
isolate instruction language. In particular, the 5.7-point CustomVoice APS difference is not a
predicted gain from translating a French user's direction into Chinese.

Nor does a prompt-language effect measured in CustomVoice automatically transfer to VoiceDesign:
the latter must construct the vocal identity as well as perform the delivery. The research question
needs separate answers for those two jobs.

## 5. Hosted guidance is useful, but its scope matters

Alibaba's [hosted voice-design guide](https://www.alibabacloud.com/help/en/model-studio/voice-design-user-guide)
documents English/Chinese descriptions while allowing multilingual generated speech.
Its [non-real-time speech guide](https://www.alibabacloud.com/help/en/model-studio/non-realtime-tts-user-guide)
documents English/Chinese instruction text specifically for the Qwen3-TTS-Instruct-Flash service.
These demonstrate that matching instruction and output languages is not a universal Qwen product
requirement. They do not impose a French-input rejection rule on the open local checkpoints.

There is an additional comparison hazard: the
[hosted realtime API](https://www.alibabacloud.com/help/en/model-studio/qwen-tts-realtime-client-events)
offers `optimize_instructions`, which rewrites the direction when enabled. A hosted demo may
therefore evaluate a different internal instruction as well as a different model/runtime.
Vocello's inspected path does not make that hosted call.

Do not silently transfer hosted character/token limits, instruction optimization, voice rosters
or promises of support into local product rules. Shared family names are insufficient provenance.

## 6. Community evidence: useful questions, weak answers

| Primary firsthand source | What it contributes | What it does not establish |
| --- | --- | --- |
| [Upstream issue 248](https://github.com/QwenLM/Qwen3-TTS/issues/248) | A reporter tested several emotion/style and Chinese-dialect requests; dialect switching did not behave like emotion control. | A translated-instruction comparison. The explanatory comment is from the reporter, not a maintainer. Closure/locking is not validation. |
| [Upstream discussion 230](https://github.com/QwenLM/Qwen3-TTS/discussions/230) | Reports of Spanish and French outputs retaining an English-sounding accent. | Which instruction language caused the accent, or a measured population failure rate. |
| [Upstream issue 134](https://github.com/QwenLM/Qwen3-TTS/issues/134) | English-reference cloning reportedly retained an American accent in Italian output. | A voice-description effect: reference conditioning is the relevant changed factor. |
| [Lalo's own usage guide](https://github.com/willianpaixao/lalo#tips-for-effective-instructions) | Recommends matching instructions to a speaker's native language. | A controlled result supporting that recommendation was not supplied in the inspected guidance. |
| [Upstream issue 14](https://github.com/QwenLM/Qwen3-TTS/issues/14) | A collaborator discussed future voice-editing support for cloning plus instructions. | Evidence that Vocello's existing Base cloning path supports delivery instructions now. |

The attached audio in community reports was not independently regenerated or scored in this
research. Reports help identify accent and conditioning failure modes; they cannot settle the
language-choice policy. Repeated online advice is not multiple independent experiments when all
copies trace back to the same guide or anecdote.

## 7. What Vocello actually sends

The following findings are from current local source, independent of marketing claims:

| Implementation | Observed behavior | Implication |
| --- | --- | --- |
| [`GenerationSemantics.designInstruction`](../../Sources/QwenVoiceCore/GenerationSemantics.swift), around line 529 | Combines description and delivery using English “Voice character” and “Delivery” labels when both are present. | French description plus English delivery is possible; there are not two separately encoded instruction-language controls. |
| `qwen3PromptAssembly`, around lines 615–694 in the same file | Supplies `text`, `language` and `instruct` separately; Clone has `instruct: nil`. | Do not derive the spoken language from the description or reference transcript. |
| `resolvedDeliveryInstruction`, around line 697 | Canonical English presets, except the governed Mandarin `angry.normal` variant for both Chinese-native speaker and Chinese output; freeform/legacy text remains verbatim. | No general instruction-localization system currently exists. |
| `englishDictionReinforcedInstruction`, around line 788 | English diction handling is conditioned on English output. | An English instruction accompanying French output is not by itself a reason to append English diction. |
| `qwenLanguageHint`, around line 826 | An explicit non-auto hint wins; otherwise the script is detected, with mode-specific fallback. | UI auto and engine auto are not interchangeable experimental labels; record the resolved value. |
| [Owned MLX Qwen3TTS implementation](../../Packages/VocelloQwen3Core/Sources/MLXAudioTTS/Models/Qwen3TTS/Qwen3TTS.swift), lines 1431–1605 | Trims/tokenizes instruction text; constructs separate language/speaker codec conditioning. | No EN/FR equality gate or translation is present at this boundary either. |

The production catalog uses 1.7B variants with Speed/Quality quantization choices. A result from
0.6B, a 25Hz model, a fine-tuned community checkpoint, or a hosted Flash service does not qualify
those exact assets. The frozen model/artifact digest and runtime matter more than a display name.

The existing [bilingual safety matrix record](delivery-harness.md#29-angry-bilingual-hard-safety-checkpoint-2026-08-26)
documents 36/36 Speed takes without hard generation/audio-QC failure. That is historical recorded
evidence, not a rerun in this review. It establishes a narrow routing/safety checkpoint, not improved
anger perception or the best language for French instructions. DP-31 and DP-32 remain open in the
existing roadmap; this research does not close either.

## 8. Recommendations by generation mode

### Built-in Voice / CustomVoice

Keep existing canonical English delivery copy. Preserve the narrow Mandarin exception rather than
expanding it on the basis of Table 8. Treat French freeform delivery as permissible but not yet
qualified for consistent adherence. User-facing French labels do not require French model-facing
preset text.

The [official CustomVoice roster](https://huggingface.co/Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice)
lists native-language identities in Chinese, English, Japanese and Korean, with no French-native
preset. Its native-language quality recommendation concerns the speaker's generated speech.
It does not establish that instructions must match the speaker's language.

For French quality problems, first distinguish wrong words, wrong output language, unwanted accent,
and weak emotion. They require different measurements. Translating a direction should not be
presented as an established cure for all four.

### Voice Design

Use English as the initial description/delivery baseline for reproducibility. Permit French
descriptions and evaluate them instead of rejecting them or silently translating them. Keep the
desired spoken language explicit; describe the desired accent separately when it matters.

Identity and performance share one conditioning string in Vocello. Compare four combinations
before attributing an effect to “matching”: English description/English delivery, English/French,
French/English, French/French. Hold the semantic brief constant. The two mixed combinations are
essential: otherwise a gain from translated delivery can be mistaken for better voice design.

A translated description may produce a different plausible voice. Even a fixed seed is not a
promise of identical vocal identity after changing conditioning. Evaluate adherence to the same
identity brief across seeds, and report identity stability separately from delivery quality.

### Voice Clone / Base

There is no delivery-language setting to optimize in the shipped clone path. Reference audio,
accurate reference transcription, target script and output-language hint are the relevant inputs.
Do not translate a reference transcript away from the words actually spoken in the reference.

For a desired Quebec French voice, a suitable, authorized Quebec French reference is a practical
starting hypothesis because it directly supplies the desired pronunciation. This review did not
measure its advantage or guarantee accent transfer. Cross-language cloning is supported, but
reference identity and accent can be entangled; changing the reference is not an instruction test.

## 9. Product consequences for French and Quebec French

Recommended policy today:

1. Keep interface localization independent from model-facing canonical preset copy.
2. Use the spoken-language selector for the intended script; do not change it to English merely
   because a description is written in English.
3. Allow descriptions/directions in the user's preferred language, while accurately describing
   English as the current preset baseline rather than a proven universal optimum.
4. Avoid a blocking “languages must match” validator and avoid automatic translation for now.
5. Distinguish an accent request from a language request. Generic French is not a measured guarantee
   of Quebec phonology, rhythm or vocabulary.
6. If later adding translation, preserve the original, make the transformation visible, and qualify
   the translator and downstream audio together. Translation changes meaning, register and degree
   of emotion as well as token language; it is a product feature requiring its own justification.

These recommendations preserve current runtime behavior. This research introduces no translator,
new inference service, UI restriction, sampling adjustment or preset rewrite.

## 10. The experiment that would resolve the uncertainty

**Proposed only. No generation, benchmark, device run or paid evaluator call was performed.** Reuse
the existing delivery corpus, experiment runner, receipts and promotion decision tooling described
in [the delivery harness](delivery-harness.md). Do not build another evaluation framework.

### 10.1 Start with a narrow, answerable question

Primary question: for a fixed French passage and intended delivery, does translating an English
direction into French improve adherence without harming intelligibility or identity?

Secondary questions: does Mandarin perform differently; does the answer depend on speaker,
description language, quantization, script register or the particular emotion? Do not turn a
French pilot into a claim covering all ten output languages.

Use semantically equivalent EN/FR/ZH instructions reviewed for meaning and intensity. Include
more than one paraphrase in confirmation, since one translation can be better writing without
its language being generally better. Keep prompts reasonably comparable in content; forcing equal
character counts would distort translations. Record token counts as a possible explanatory factor.

### 10.2 A bounded pilot, followed by independent confirmation

An illustrative CustomVoice screen is two speakers with different native-language backgrounds,
three French passages, two delivery styles, three instruction languages and four fixed seeds:
**144 instructed takes**. Add **24 no-instruction controls** (two speakers × three passages × four
seeds). Total: **168 takes on one frozen tier**. No-instruction means genuinely absent instruction;
Vocello's Neutral preset is itself instructed and is not that control.

This is a screening budget, not a statistical power calculation. Two speakers cannot support a
roster-wide recommendation, and four seeds do not turn three scripts into twelve independent
linguistic examples. Expand only a promising, non-regressing result onto held-out passages,
paraphrases, additional speakers and the other tier.

A separate VoiceDesign screen can use the EN/FR description × EN/FR delivery combinations,
three identity briefs, three passages and four seeds: **144 takes**. It tests the interaction that
the CustomVoice screen cannot. Add Mandarin after that question is tractable, rather than
multiplying every factor before learning anything.

Long-form and line-by-line confirmation should follow a successful short-form result. Freeze
segmentation and carry the same instruction policy through all chunks; otherwise chunk boundaries
and reset behavior become new confounders. Do not assume a sentence-level benefit persists over
an entire long recording.

### 10.3 Freeze and record the actual intervention

- Same script, resolved output language, model/artifact digest, build identity and device/runtime.
- Same speaker or semantic identity brief, delivery meaning, sampling parameters and seed pairs.
- Record the final merged instruction digest, language treatment, resolved hint, prefix/streaming
  settings and Speed/Quality tier; do not rely only on the UI text.
- Randomize execution order within matched blocks to reduce time/thermal/order effects.
- Keep every take and every failure. No hidden retries, cherry-picked seeds or best-of-N selection.
- Use synthetic governed corpus material; keep raw audio and potentially sensitive text untracked.

Changing a prompt changes tokenization and the generation distribution. A paired seed improves
reproducibility, not semantic equivalence of the sampled acoustic trajectory. Record variance and
failure rate rather than relying on one unusually good pair.

### 10.4 Measure separate outcomes

| Outcome | Suitable evidence | Common false conclusion |
| --- | --- | --- |
| Script fidelity | Locale-locked full-audio ASR, WER/CER, omissions, insertions, repetitions and wrong-language flags | Low WER proves a native accent or correct emotion. |
| Delivery adherence | Existing acoustic expectations plus independently judged adherence to the same semantic specification | Louder or higher-pitched automatically means more accurate emotion. |
| Voice identity | Similarity/stability relative to the intended speaker or design brief | One identity similarity score proves accent or performance quality. |
| Accent | Explicit regional criteria assessed separately; document recognizer/judge limitations | French-language detection proves Quebec French. |
| Audio integrity | Existing PCM, clipping, silence, duration and truncation checks | A successful request means usable audio. |
| Runtime | Duration, latency and peak memory if that comparison is explicitly included | Better language adherence implies the best performance tier. |

Use the existing independent-judge and order-reversal requirements for promotion. Give judges a
single canonical semantic specification rather than changing the judge's prompt language with
the generation treatment. Otherwise one can measure the evaluator's preference for English or
French wording instead of the generated audio. A judge must demonstrably handle French speech;
a multilingual label alone is insufficient qualification.

Report paired effects, uncertainty and subgroup failures. Group analysis by speaker/script/brief;
account for multiple comparisons. Predeclare practically meaningful improvement and non-regression
bounds using the existing promotion contract. Optional native-speaker assessment can add accent
context but cannot waive the repository's machine-evidence failures.

The useful outcomes include “equivalent within measured uncertainty” or “French helps this style
on these speakers but harms another.” Do not force a universal winning language out of mixed data.

## 11. Documentation corrections and remaining uncertainty

This review corrects three active documentation overclaims: an exclusive local EN/ZH restriction,
an asserted exclusive instruction-training language set, and a causal Chinese advantage inferred
from different benchmark splits. Historical experiments and their attribution remain intact.

Still unknown:

- The instruction-language distribution and language-pair coverage in speech training.
- Whether French instructions outperform equivalent English instructions on the shipped assets.
- Whether any advantage is stable across accents, speakers, emotion, wording and quantization.
- Whether matching the speaker's native language matters independently of output language.
- Whether mixed-language description/delivery improves, harms or simply changes designed identity.
- Whether a short-form result generalizes to the existing long-form and batch execution paths.

DP-31/DP-32 remain the existing promotion work, not completed evidence. Any future French-language
experiment belongs within that work and its consent/evidence boundaries, not a second task ledger.

## 12. Search coverage and reproducibility limits

Reviewed source classes: official open repository/wrapper/model code and examples; official model
cards and technical report; original InstructTTSEval paper, repository and public dataset viewer;
Alibaba hosted design/instruction documentation; relevant upstream issues/discussions and an
application author's contrary guidance; Vocello source, contracts and retained experiment prose.

Searches covered instruction language, French descriptions, EN/ZH instructions, multilingual
instruction control, accent transfer, speaker-native-language advice and translated-instruction
comparisons. Public issue comments were checked for author association where a claim might be
mistaken for a maintainer statement. No issue was opened and no external message was sent.

This is an extensive public-source review, not a claim that every unpublished result or unindexed
discussion was found. Dynamic hosted documentation may change. The upstream code revision is
pinned above; local line references describe the stated baseline. No model weights, evaluation
audio corpora or private training data were downloaded, and no new perceptual result is claimed.
