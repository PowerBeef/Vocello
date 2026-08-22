---
status: historical
owner: backend-mlx
summary: Point-in-time research and code audit of Qwen3-TTS emotion and tone control, Vocello delivery wiring, evaluation limits, and the governed remediation adopted on 2026-08-22.
contentDigest: sha256:0d4f2841b0d88118c64b6f5ac2c9dece1b2e06681b9274a989509980a7c1a352
---
# Qwen3-TTS emotion and tone delivery research — 2026-08-22

This is a descriptive, pinned report of the external research, local code audit, and measurement
record used to shape DP-27 through DP-32. It does not change a production prompt, authorize a
quality claim, or replace a live contract. Source, the production model catalog, validation
contracts, and `config/roadmap.json` remain authoritative.

## Executive conclusion

Vocello delivers CustomVoice and VoiceDesign instructions to the model correctly. The remaining
problem is probabilistic adherence: a valid instruction can produce different delivery across
speakers, seeds, scripts, languages, and independently sampled talker and subtalker streams.

Official Qwen results establish the ceiling. On InstructTTSEval English, the 12 Hz 1.7B
CustomVoice checkpoint reports 77.3 for Acoustic-Parameter Specification, 77.1 for Descriptive
Style Directive, and 63.7 for Role Play. VoiceDesign reports 82.9, 82.4, and 68.4. These are useful
control scores, not exact obedience. The local 360-take screen reached the same practical
conclusion: an extensive candidate rewrite matched the shipped arm's acoustic adherence and
regressed held-speaker discrimination. No universal prompt rewrite is justified.

The remediation therefore separates prompt factors, sampling, scripts, language, speakers, and
model variants; adds source-bound exact receipts; replaces a single emotion verdict with layered
analysis and abstention; and makes blinded listening the semantic authority for prompt promotion.
The one-take product behavior stays unchanged.

## Official capability and syntax

| Qwen3-TTS checkpoint | Identity input | Instruction channel | Vocello use |
| --- | --- | --- | --- |
| 12Hz-1.7B-CustomVoice | One of nine speaker embeddings | Supported | Built-in Voice / Custom mode |
| 12Hz-1.7B-VoiceDesign | Instruction describes identity and delivery together | Supported | Voice Design |
| 12Hz-1.7B-Base | Reference audio | Unsupported | Voice Cloning |
| 12Hz-0.6B-CustomVoice | Speaker embedding | Unsupported upstream | Not a production artifact |
| 12Hz-0.6B-Base | Reference audio | Unsupported | Not a production artifact |

The supported instruction is plain-language text in a ChatML user turn:

```text
<|im_start|>user
{instruction}<|im_end|>
<|im_start|>assistant
{script}<|im_end|>
<|im_start|>assistant
```

There is no documented SSML parser, inline emotion-tag vocabulary, prompt weighting,
classifier-free-guidance control, negative-prompt field, or system-message override. Syntax such
as `[happy]`, `(whispering)`, XML tags, or CosyVoice's `<|endofprompt|>` must not be invented.
Official examples range from concise phrases such as “Very happy.” to multidimensional VoiceDesign
descriptions. Alibaba's adjacent Voice Design guidance recommends descriptions that are specific,
multidimensional, objective, concise, and nonredundant. Concise and structured prose are therefore
separate experimental arms, not a settled style rule.

The talker and subtalker samplers have separate temperature, top-p and top-k controls. Upstream
does not establish that lower temperature increases instruction adherence, so decoder profiles
must be measured factorially rather than ranked by intuition. Qwen also recommends each built-in
speaker's native language for best quality; cross-language output is supported but requires its
own results.

Primary sources: [official README](https://github.com/QwenLM/Qwen3-TTS/blob/main/README.md),
[official inference source](https://github.com/QwenLM/Qwen3-TTS/blob/main/qwen_tts/inference/qwen3_tts_model.py),
[Qwen3-TTS technical report](https://arxiv.org/html/2601.15621v1), and
[Alibaba Voice Design guidance](https://www.alibabacloud.com/help/en/model-studio/voice-design-user-guide).

## What Vocello sends

### CustomVoice

`EmotionPreset` resolves the shipped preset and intensity into exact text. Generation semantics
places that text in `GenerationRequest.Payload.deliveryInstructionText`; the owned Qwen runtime
builds the same ChatML user turn as upstream. The engine stamps the exact character count and
SHA-256 receipt into telemetry. Bench and experiment runners compare that receipt with their
manifest and fail closed. The CLI now returns the same delivery digest in generated JSON, making a
standalone take source-bound without exposing the instruction contents.

### VoiceDesign

One instruction contains both voice identity and delivery. Vocello uses the measured labeled merge
`Voice character: … Delivery: …`. VoiceDesign can improve instruction following relative to
CustomVoice, but it can also change speaker identity on every call; delivery and identity drift
must be evaluated together.

### Voice Cloning

The Base checkpoint has no instruction channel, and Vocello's clone request type cannot carry one.
Clone emotion control is a reference-audio problem. The supported program remains curated
emotion-specific reference banks scored for delivery, identity, intelligibility, and naturalness.
No prompt remediation is added to the Base engine.

## Local measurement record

The 2026-08-22 DP-26 screen generated 360 instructed CustomVoice attempts: nine speakers, eight
shipped presets, five fixed seeds, Speed-tier models, and exact instruction receipts. The shipped
arm recorded 169/360 product-accepted takes, 182/360 acoustic adherence, and held-speaker UAR
0.342. The candidate-v2 rewrite recorded only two genuine roughly two-second Sad gaps after the
Fast-QC correction, but acoustic adherence remained 182/360 and held-speaker UAR fell to 0.306.
Production copy therefore did not change.

The screen also exposed a false-hard-QC root cause: the earlier cadence-pause rule rejected
ordinary generated pauses. Audio QC v4 now warns on ordinary excess cadence while retaining hard
failure for repeated suspicious gaps and context-sensitive pauses of at least 1.2 or 2.0 seconds.
This implementation correction is independent of the failed prompt hypothesis.

The broader delivery ledger already showed:

- Full-roster presets occupy measurably different acoustic regions, but that does not prove the
  regions match their emotion names.
- Happy versus angry is a valence bottleneck: both can raise pitch, energy, tension, and pace.
- Speed 4-bit and Quality 8-bit did not show a general adherence advantage for Quality.
- A one-listener session recognized only a subset of preset names reliably; it was calibration,
  not sufficient promotion evidence.
- The current easy English ASR corpus nearly saturates at zero WER and cannot reveal small
  articulation regressions.

## Ranked prompting conclusions

| Rank | Conclusion | Evidence level |
| --- | --- | --- |
| 1 | Use the documented plain-language instruction channel only; never tags or SSML | Official source and local byte-level audit |
| 2 | CustomVoice/VoiceDesign can follow instructions; Base cloning cannot | Official support matrix and source |
| 3 | Partial adherence is normal; role/scenario-only prompts score worse than explicit attributes | Official technical-report results |
| 4 | Keep concise emotion and structured acoustic descriptions as separate arms | Official examples plus adjacent official guidance |
| 5 | Measure speaker, script semantics, language, seed, and both samplers explicitly | Local 360-take result and official architecture |
| 6 | Test Speed and Quality separately; do not assume precision tier improves delivery | Local confirmatory measurement |
| 7 | Use a compatible scene only as an isolated factor; test an anti-exaggeration clause separately | Experiment design, not yet a product result |
| 8 | Community “magic prompts,” negative syntax, brackets, weights, and hidden best-of-N | Unverified or unsupported; excluded |

## Evaluation inventory and limits

| Layer | What it can establish | Cost / license / status | Known failure mode |
| --- | --- | --- | --- |
| PCM and `analyze_prosody.py` | Integrity, pitch, range, cadence, pauses, energy, HNR, jitter, CPP, spectral balance | Deterministic, bounded memory, repository-owned | Acoustic proxies do not identify semantic emotion |
| ASR consensus | WER/CER and output-language consistency | Operator-local, locale locked | Existing text is too easy; clean synthesis saturates |
| ECAPA | Relative same-speaker identity drift | Operator-local; advisory thresholds | Vocello voices are not independently calibrated |
| UTMOSv2 | Relative naturalness guardrail | Operator-local, about 3.6 GB observed peak RSS; sequential only | Domain-shifted synthetic-speech predictor, not absolute MOS |
| wav2vec2-XLSR SER | Seven-class posterior, entropy and margin | Roughly 0.3B checkpoint; about 2.4 GB observed peak RSS | No calm or whisper class; uncalibrated across Vocello speakers/languages/synthesis |
| Local dimensional model | Valence, arousal and dominance from normalized deterministic features | Lightweight coefficients only; grouped nested validation | Requires blinded labels and untouched validation before authority |
| audEERING VAD models | Potential dimensional challenger | Research/non-commercial CC-BY-NC-SA license | Not compatible with product evaluation adoption without a separate commercial license |
| emotion2vec+ | Potential multilingual representation | Roughly 1.1 GB weights; license/training provenance unresolved | Excluded until immutable licensing and data provenance are clear |
| Blinded listeners | Perceived meaning, valence, arousal and naturalness | At least three listeners and one fluent listener per locale | Costly; must protect holdout and correct multiplicity |

The current SER top class is not a verdict. The remediation records every probability, posterior
entropy, top-two margin, calibration error, and out-of-distribution state. Calm-to-neutral is a
hypothesis rather than a label equivalence. Whisper abstains from categorical SER and uses
breathiness, HNR, CPP, voicing, and energy.

Automated semantic judging is itself noisy. InstructTTSEval reports 79% average human agreement
and 71% on role-play prompts, supporting a layered screen plus blinded human authority rather than
one evaluator model. See [InstructTTSEval](https://arxiv.org/html/2506.16381v1), the
[audEERING large VAD model card](https://huggingface.co/audeering/wav2vec2-large-robust-12-ft-emotion-msp-dim),
and the [official emotion2vec repository](https://github.com/ddlBoJack/emotion2vec).

## Coverage gaps at capture

| Dimension | Existing evidence | Required confirmation |
| --- | --- | --- |
| Model mode | Strongest on CustomVoice; partial Design and clone-bank evidence | Revalidate Custom, VoiceDesign identity+delivery, and clone banks independently |
| Variant | Speed/Quality English fixed-script comparisons | Both variants on the shortlisted multilingual holdout |
| Speaker | Nine CustomVoice speakers in the 360 screen | Native-language scripts plus held-speaker listener analysis |
| Language | Primarily English output and English instruction | Native English/Mandarin/Japanese/Korean plus fixed cross-language sentinels |
| Script | One easy medium English sentence dominates | Short/medium/long neutral, congruent, and conflicting scripts |
| Seed | Five-screen and earlier 16–23-seed experiments | Paired power calculation, minimum 8 and maximum 20 confirmatory seeds per cell |
| Sampling | Product profiles and isolated historical runs | Five registered talker/subtalker combinations |
| Semantic labels | One-listener calibration and categorical proxy | Three-listener blinded cohort, fluent locale coverage, held-out once |
| Intelligibility | Near-zero-WER easy corpus | Harder names, numbers, syntax, lengths, and native-language CER |
| Naturalness/identity | Advisory relative signals | Locally calibrated guardrails and untouched confirmation |

Translated-equivalent script identity, speaker, and seed must not leak across calibration,
development, and confirmation. The untouched holdout may be opened once per candidate family.

## Remediation implemented at capture

- `DeliveryInstructionSpec` is represented by a versioned internal JSON contract with target VAD,
  acoustic movements, compatible scene, contradictions, language, compiler version, exact text,
  and digest.
- Six attributable prompt arms and five talker/subtalker combinations are machine validated.
- A split-safe multilingual corpus covers three lengths, three semantic conditions, nine native
  speakers, and four cross-language sentinels. Disjoint numeric seed partitions prevent a raw seed
  from crossing calibration, development, and confirmation. Non-English copy remains provisional
  pending fluent review.
- A serial, resumable CLI runner binds binary, catalog variant, production instruction, seed,
  speaker, script, sampling, receipt, and audio digest. It retains failures and never publishes.
- The first live pilot exposed and closed a false-green boundary: a sandbox-aborted model process
  was correctly retained as failed but the runner command initially exited success. Execution now
  fails on any failed/blocked row or on zero completed rows. The same source-bound row then passed
  with native MLX access and produced a receipt-verified instructed/reference pair plus acoustic
  layer.
- CLI generation JSON exposes the exact delivery instruction count and digest used by the request.
- The layered evaluator composes automatic evidence and abstains on missing, uncertain,
  out-of-distribution, or contradictory layers.
- SER records a calibrated posterior shape rather than reducing evidence to top-1.
- Listener scoring now supports independent cohorts, fluent-language coverage, paired bootstrap,
  Holm correction, and speaker/script-balanced checks.
- Promotion fails closed unless blinded improvement, no per-preset regression, audio integrity,
  WER/CER, identity, UTMOS, memory, cancellation, seed identity, and receipts all pass.

The contract validates infrastructure, not model quality. DP-28 through DP-32 retain the real data,
calibration, screening, holdout, listening, and promotion work. If no arm qualifies, current copy
and directional-hint UI remain correct.

## Decision protocol

A global compiler change qualifies only when the paired 95% bootstrap lower bound for macro
listener-identification improvement exceeds zero; instructed-versus-neutral 2AFC exceeds chance
after Holm correction; gains span speakers and scripts; no preset regresses significantly; hard
PCM failures remain zero; WER/CER worsens by at most 0.01; median speaker similarity falls by at
most 0.02; relative UTMOS falls by at most 0.10; and runtime receipts and identity stay valid.

A single preset may qualify independently under the same per-preset holdout rules. No hidden
best-of-N, cloud evaluation, automatic publication, or evaluator shipped inside Vocello is
permitted. Clone acceptance remains a separate reference-bank decision.

## Governed continuation

DP-27 pins this report and the experiment contract. DP-28 owns blinded calibration of the layered
evaluator and cross-references AV-07. DP-29 owns fluent review and native-language evidence and
cross-references AV-08. DP-30 runs prompt, sampling, instruction-language, and script-interaction
screens. DP-31 opens the Speed/Quality untouched holdout and blinded listening. DP-32 may promote
only a qualifying per-preset or global change, then revalidates all three product modes. DP-25
remains the normal-tier threshold-calibration item, and DP-20 remains the future VoiceEditing
watchlist.
