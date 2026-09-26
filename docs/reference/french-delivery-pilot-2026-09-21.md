---
status: active
owner: backend-and-platform
reviewed: 2026-09-21
summary: Exploratory paired comparison of shipped English delivery instructions and French translations for French Built-in speech; no production promotion.
sourceOfTruth:
  - config/delivery-french-pilot.json
  - scripts/delivery_experiment_runner.py
  - scripts/independent_asr.py
  - config/audio-qc-judges.json
---
# French delivery instruction pilot — September 21, 2026

## Decision

This pilot does not justify replacing the English model-facing presets with French instructions.
The results are mixed: French wording scored higher on generic NISQA quality and reduced native
cadence warnings for Sad, but English wording
passed more existing acoustic delivery checks for Angry, Sad and Whisper. French did not produce a
consistent transcription improvement across the two voices. Keep the localized user-facing copy and
current internal instructions; DP-31/DP-32 remain open.

These are measurements of four particular instruction pairs on two voices, not proof that English
is universally superior. Acoustic checks are not calibrated French emotion judgments.

## Frozen method and execution

- 192 instructed takes: Aiden/Vivian × Happy/Sad/Angry/Whisper × three neutral French passages ×
  four paired development seeds × English/French instructions.
- 24 shared **canonical English Neutral controls**, one per voice/passage/seed. Neutral is itself
  an instruction, not an instruction-free baseline.
- Quality, `balanced-official` sampling, explicit French output, default CLI streaming, and the
  shipped intensity of each preset. English wording was checked against the compiled shipped
  instructions; French wording translates those complete directions, not their UI descriptions.
- Matched pairs were interleaved in a frozen randomized order. Every generation used a separate CLI
  process. No replacement seeds, retries, or best-of-N selection occurred.
- All 216 requests completed with EOS. All receipts agreed on French output and one Quality
  model/tokenizer identity. Model artifact version: `2026.09.14.1`; the CLI build receipt verified
  `-O` against the executed binary digest.
- Model integrity manifest: `50ca1f9d3c8e523b977a88d49e42a18dae6a4135b3291d47bef410ff7a257a48`.
- Plan digest: `5e339df4ca5d5ddcc63f6fdac3749491581ce693300d99755c20fc82d3ecd120`.

Native QC, paired acoustic analysis, full-file French-locked Whisper ASR, and advisory NISQA were
separate stages. The generator exited before analysis, and heavy analyzers ran serially. No new
models were downloaded. The study generated approximately 43 minutes of audio.

## Measured results

Each treatment cell below contains 24 clips. A native-QC warning is retained and is not a hard
failure. A delivery-check pass is an acoustic proxy, not proof of the named emotion.

| Delivery | Native QC clean passes, EN / FR | Acoustic delivery passes, EN / FR | Mean WER, EN / FR |
|---|---:|---:|---:|
| Happy | 23 / 19 | 5 / 6 | 7.22% / 7.99% |
| Sad | 11 / 19 | 12 / 5 | 7.58% / 8.90% |
| Angry | 24 / 23 | 13 / 8 | 7.69% / 8.61% |
| Whisper | 16 / 15 | 14 / 7 | 7.35% / 7.24% |
| **Total / mean** | **74 / 76 of 96** | **44 / 26 of 96** | **7.46% / 8.19%** |

Across treatments and controls, native QC recorded **173 passes, 43 warnings, and zero hard
failures**. Treatment warnings included 38 cadence flags and four dropout flags; a clip can carry
more than one flag. French Sad clips were 1.86 seconds shorter on average (12.29 versus 14.14 s).
Fewer cadence warnings therefore cannot, by themselves, be interpreted as better sadness delivery.

### Script fidelity and voice differences

Whisper processed all 216 files. All 192 treatment recognitions passed receipt and audio-edge
coverage checks. This is one recognizer family, not independent-family consensus or human-corrected
transcription. WER/CER use the existing shared tokenizer and edit-distance policy unchanged.
Of 216 transcripts, 186 contain digit-form numbers although the scripts spell those numbers out;
for example, `20` versus `vingt`. Recognized homophones such as `vers` versus `verres` also contribute
orthographic errors without demonstrating different pronunciation. The absolute WER figures are
therefore not literal audible speech-error rates. No transcript rewriting or post-hoc metric
normalization was used to improve a score.

| Voice | Mean WER, EN / FR | Acoustic delivery passes, EN / FR | Whisper threshold/language passes, EN / FR |
|---|---:|---:|---:|
| Aiden | 9.31% / 11.17% | 29 / 17 of 48 | 43 / 39 of 48 |
| Vivian | 5.60% / 5.20% | 15 / 9 of 48 | 47 / 48 of 48 |

The existing ASR threshold is WER ≤15%, with detected French also required for that recognizer's
pass. One English-instructed Aiden Whisper take was labelled English with probability 0.495 versus
0.472 for French, despite a predominantly French forced-decode transcript. It remains a failed
language-detector vote, **not proof that the clip switched to English**. The other 215 clips were
detected as French. Accent, French nativeness, and Quebec pronunciation were not established.

### Advisory clip quality versus delivery strength

NISQA v2 was retired on 2026-09-25, after this pilot: its released weights are CC BY-NC-SA 4.0
(audio QC audit AQ-F01, decision 1a; `config/audio-qc-judges.json`). The figures below are the
historical record of this run and support no current decision.

NISQA v2 scored all 216 clips using the then-pinned weights and warning floor of **3.81**.
Across the 192 treatments, mean predicted MOS was **3.875 for English instructions versus 4.197
for French**. The warning floor caught **42/96 English** and **16/96 French** treatment clips,
plus one Neutral control. These are model predictions, not listener MOS ratings or hard failures.

| Delivery | Mean NISQA, EN / FR | FR minus EN | Exploratory 95% interval |
|---|---:|---:|---:|
| Happy | 4.154 / 4.235 | +0.081 | −0.270 to +0.493 |
| Sad | 4.031 / 4.356 | +0.325 | +0.119 to +0.447 |
| Angry | 3.758 / 4.085 | +0.327 | +0.162 to +0.594 |
| Whisper | 3.556 / 4.111 | +0.555 | +0.131 to +0.948 |

French's higher generic quality scores coexist with weaker target-style proxies:

- Sad duration relative to the shared Neutral control: **1.283× EN versus 1.113× FR**.
- Angry pitch lift relative to Neutral: **+3.86 semitones EN versus +2.18 FR**.
- Whisper voiced-fraction change: **−0.073 EN versus −0.029 FR**; CPP change was **−3.97 dB EN
  versus −1.78 dB FR**, consistent with less breathy/devoiced French outputs in this cohort.

One plausible interpretation is a quality/style-strength tradeoff: less extreme delivery can
score better on a generic speech-quality model. This is an inference, not a causal explanation
proved by NISQA or a French semantic judge. Both voices show the same direction in mean NISQA:
Aiden **4.011 → 4.352**, Vivian **3.738 → 4.041** (EN → FR). No layer overrides another layer's
warning, and no thresholds were changed after viewing results.

### Paired uncertainty

For each delivery, average four seed-pair differences within each voice/passage, then average the
two fixed voices within each passage. Bootstrap those **three passage means** with the existing
paired-statistics function, 10,000 resamples, seed `20260921`. This avoids counting all 24 seed pairs
as independent linguistic examples. These descriptive intervals have very limited coverage with
only three passages; they are not population or confirmatory inference.

| Delivery | FR minus EN WER (percentage points) | Exploratory 95% interval |
|---|---:|---:|
| Happy | +0.77 | −0.83 to +2.31 |
| Sad | +1.33 | −1.85 to +3.33 |
| Angry | +0.93 | −1.39 to +2.92 |
| Whisper | −0.11 | −2.08 to +0.93 |

All WER intervals include zero. No multiplicity-corrected superiority claim or production promotion
is made. The largest consistent acoustic difference is reduced passage duration for French Sad;
that change does not tell us which performance a French listener would perceive as more convincing.

## Limits and reproducibility

This is a short-form development pilot on Quality with two fixed, non-French-native built-in
voices, three passages, one translation per instruction, and four seeds. Wording and language
cannot be completely separated by one translation. There was no Speed, Voice Design, Clone,
long-form, iPhone, accent, calibrated speaker-identity, or independent semantic-judge qualification.
NISQA and existing delivery thresholds remain advisory for this cohort. A production change would
still need fresh passages/paraphrases, more voices, the other tier, and the established confirmation
and promotion gates.

The bounded specification is checked in; the immutable plan, receipts, WAVs, acoustic layer,
recognitions and detailed paired analysis stay untracked under run ID
`french-instruction-pilot-20260921`. The local report includes representative pairs selected by the
fixed Aiden/library/seed-32000001 key, not by score. No benchmark-history PASS record was published.
Implementation: `ebe65e18`; its repository contracts, product tests, research tests and CI gate
passed. The unrelated paused Mac marketing-test edit was preserved.
