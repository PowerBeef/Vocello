# `introspection.eos-overrun@1`

<!-- BEGIN GENERATED audio-qc-docs:definition (scripts/audio_qc_docs.py regen; edit its sources, not this block) -->
Registry entry `introspection.eos-overrun@1` in [config/audio-qc-detectors.json](../../../../config/audio-qc-detectors.json); definition digest `e96bbcc2656c5b2e` (a plan binds it, so any change is a new version, A7).

**Measures.** Generation steps at which the talker gave EOS a probability of at least 0.5 and generation went on (eosLikelyStepsWithoutStop): the take ran on past points where the talker would likely have stopped.

| Class | Stage | Direction | Combination | Unit | Thresholds |
|---|---|---|---|---|---|
| I (introspection) | 0 | above | single | steps | per language |

**Strata.** The talker's per-step distribution follows each language's text tokens and prosody (its entropy, where it stops, and the cycles its pauses and repeated syllables form), so each language is its own clean distribution.

**Score components.**

| Languages | Components | Requires complete |
|---|---|---|
| chinese, english, french, german, italian, japanese, korean, portuguese, russian, spanish | [`fastqc@8`](../judges/fastqc-v8.md) introspection `eosLikelyStepsWithoutStop` | - |

**Scope.** chinese, english, french, german, italian, japanese, korean, portuguese, russian, spanish.

**Positives and shams.**

| Injector | Severities | Mechanism | Matched sham |
|---|---|---|---|
| `GEN-NOEOS` | severe | T3-controlled-generation | yes |

**Populations** (role set `n3-controlled-generation`): fit N3 (calibration, vocello-takes-calibration); confirmNegatives N3 (confirmation, vocello-takes-confirmation); positives P3 (confirmation); shams S (confirmation).

**Limitations.**

- `n3-no-labels`: A measure that exists only on generated takes (the talker's introspection, long-form seams) has no N2 to confirm on: a codec round trip samples no token and joins no segment, so its fit and confirmation negatives are N3 alone (audit section 5.7), the two splits of config/audio-qc-calibration-takes.json disjoint by family, speaker and script. N3 carries no defect labels, so a flag rate f bounds the false-alarm rate only as f / (1 - pi_max), where pi_max is the largest defect prevalence admitted (section 5.1). Each language stratum needs at least 60 scored families in each split (the calibration split plans 80 per language).

**Risks.**

- `introspection-rows-kept`: The engine's introspection summary reaches a take through its diagnostics row, which the engine front-trims at its log cap. The qc-takes lane marks the rows present before it starts, raises the cap (QWENVOICE_DIAGNOSTICS_MAX_MB=64), copies each vocello batch's new rows (generation id, WAV digest, Fast QC flag names, failure code and introspection numbers) into its diagnostics/ directory, and audio_qc_calibration_takes.py manifest --diagnostics binds each take to the row whose samplingWAVDigest is its WAV digest; verdict.txt reports the bound count. A take still without its row abstains (no-value); the 2026-09-27 cohort, generated before the lane kept its rows, bound 251 of its 791 takes.
- `generation-knob-published-only`: GEN-NOEOS@1 (T3, audit section 5.2; construction catalog 1) regenerates a confirmation take (its text, voice, batch seed and delivery) under the registered internal-diagnostics knob QWENVOICE_TALKER_EOS_SUPPRESSION_FRAMES (config/runtime-debug-knobs.json, group controlled-generation), which holds back the talker's first sampled EOS for 6, 18 or 50 codec frames; N = 0 is its sham. Each take's engine row records its hold, and the builder refuses a take whose row does not. The engine's mandatory Fast QC still refuses some held takes (a long slow or silent tail), and a refused take has no published WAV: P3 positives are published takes only, as N3 negatives are, so the detection rate is conditional on the product publishing the take, and the set counts the refusals per variant. Only Custom and Voice Design takes are regenerated (a clone take would need its reference transcript), and a positive whose talker never sampled EOS before the token cap is no entry.

**Lanes it gates** ([config/audio-qc-lane-gates.json](../../../../config/audio-qc-lane-gates.json)): none.
<!-- END GENERATED audio-qc-docs:definition -->

<!-- BEGIN GENERATED audio-qc-docs:qualification (scripts/audio_qc_docs.py regen; edit its sources, not this block) -->
## Qualification

**Status.** Qualified (warn); confirmed (qualified).

**Plan.** [config/audio-qc-preregistrations/introspection.eos-overrun@1.json](../../../../config/audio-qc-preregistrations/introspection.eos-overrun@1.json): digest `855b29791923038f`, rule split-conformal, alpha 0.05, confidence 0.95, operating point warn, population N3; injector catalog 1, classes I, 150 per cell.
Calibration cohort audio-qc-calibration-takes (vocello-takes-calibration, manifest `9482435d54f16582`); confirmation cohort audio-qc-calibration-takes (vocello-takes-confirmation, manifest `20211aeea93a0abd`).

**Confirmation.** Ledger entry qualified.

### Record [record-855b29791923038f.json](../../../../benchmarks/audio-qc-calibration/introspection.eos-overrun@1/record-855b29791923038f.json): qualified at warn

Operating point warn; rule split-conformal, alpha 0.05, thresholds per language; plan `855b29791923038f`. Rates count source families with one-sided Clopper-Pearson bounds.

| Stratum | Threshold | FAR on confirmation N3 | Limit | Meets |
|---|---|---|---|---|
| chinese | 0 | 13/239 (0.054), upper 0.104 | 0.2 | yes |
| english | 0 | 5/240 (0.021), upper 0.058 | 0.2 | yes |
| french | 0 | 15/239 (0.063), upper 0.115 | 0.2 | yes |
| german | 0 | 13/238 (0.055), upper 0.104 | 0.2 | yes |
| italian | 0 | 13/238 (0.055), upper 0.104 | 0.2 | yes |
| japanese | 1 | 2/239 (0.008), upper 0.038 | 0.2 | yes |
| korean | 0 | 6/232 (0.026), upper 0.066 | 0.2 | yes |
| portuguese | 1 | 0/238 (0.000), upper 0.022 | 0.2 | yes |
| russian | 1 | 1/240 (0.004), upper 0.031 | 0.2 | yes |
| spanish | 0 | 15/238 (0.063), upper 0.115 | 0.2 | yes |
| pooled | - | 83/2381 (0.035), upper 0.042 | 0.1 | yes |

Per-language bounds at confidence 0.995 (Bonferroni over the languages), pooled at 0.95. Clean abstention: 0/2381 (0.000), upper 0.001 (limit 0.1, meets yes).

| Mechanism | Cell | Detected | Limit | Meets |
|---|---|---|---|---|
| T3-controlled-generation | GEN-NOEOS/severe | 65/69 (0.942), lower 0.872 | 0.7 | yes |

Mechanisms meeting: T3-controlled-generation (minimum 1).

| Sham cell | Alarms | Overlaps N2 FAR | Informative |
|---|---|---|---|
| GEN-NOEOS | 4/150 (0.027), upper 0.060 | yes | no |

Counts: calibration 2370 clips, 2370 families, 0 abstained; confirmation N3 2381 clips, 2381 families, 0 abstained; P3 69 clips, 69 families, 0 abstained; S 150 clips, 150 families, 0 abstained. Speakers: 175 (identified, unit `vocello-voice`).

Judge output identities: `fastqc@8` `072d385c65e95361`. Record limitations: `n3-no-labels`; risks: `introspection-rows-kept`, `generation-knob-published-only`.
<!-- END GENERATED audio-qc-docs:qualification -->
