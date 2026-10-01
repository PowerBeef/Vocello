# `prosody.octave-jump@1`

<!-- BEGIN GENERATED audio-qc-docs:definition (scripts/audio_qc_docs.py regen; edit its sources, not this block) -->
Registry entry `prosody.octave-jump@1` in [config/audio-qc-detectors.json](../../../../config/audio-qc-detectors.json); definition digest `e4949fdeb868fda4` (a plan binds it, so any change is a new version, A7).

**Measures.** The longest run, in seconds, of consecutive pYIN voiced frames at least 9 semitones from the median F0 of the take's voiced frames, reduced from pYIN's frame track: an octave jump holds the displaced register for its span, where intonation passes through it. A take without a voiced frame abstains.

| Class | Stage | Direction | Combination | Unit | Thresholds |
|---|---|---|---|---|---|
| F (prosody) | 1 | above | single | seconds | per language |

**Strata.** Lexical tone (zh) and pitch accent (ja) move F0 faster within a syllable than intonation does in the other languages, so each language is its own clean distribution.

**Score components.**

| Languages | Components | Requires complete |
|---|---|---|
| chinese, english, french, german, italian, japanese, korean, portuguese, russian, spanish | [`pitch.pyin@1`](../judges/pitch.pyin-v1.md) raw-output `longestOctaveDisplacementSeconds` | - |

**Scope.** chinese, english, french, german, italian, japanese, korean, portuguese, russian, spanish.

**Positives and shams.**

| Injector | Severities | Mechanism | Matched sham |
|---|---|---|---|
| `PRS-OCT` | severe | T1-pcm-construction | yes |

**Populations** (role set `fleurs-reserve-n2`): fit N2 (calibration, fleurs-reserve-1); confirmNegatives N2 (confirmation, fleurs-reserve-2; at a fail point fleurs-reserve-3); positives P1 (confirmation); shams S (confirmation); informational N3, N1.

**Limitations.**

- `fleurs-reserve-no-speaker-ids`: FLEURS publishes no speaker ids; its TSVs give only a gender per recording. The reserve cohorts are drawn from the one train split (config/audio-qc-corpora.json fleurs-train), disjoint by FLoRes sentence from each other and from dev and test, so family and script disjointness hold; but they are grouped by sentence, not by speaker, so a train speaker who read sentences of two cohorts speaks in both: the calibration (reserve-1) and confirmation (reserve-2) cohorts likely share speakers, and neither that nor a speaker count can be measured.
- `fleurs-speaker-lower-bound`: Units carry the speaker '<language>:fleurs-unidentified', a lower bound on the speaker count: FLEURS collects each locale separately, so recordings of different languages cannot share a speaker. The policy minimum of 3 speakers is therefore met only by covering at least 3 languages.
- `n2-one-codec`: N2 is one production codec round trip (the pro_clone speed variant at full codebooks) of FLEURS read speech; FAR on it is in the codec's domain, not on natural Vocello takes (N3, informational at warn).
- `n2-read-speech`: FLEURS is read speech, while the audit's class F negatives are expressive N1 (section 5.7): expressive speech moves F0 further and faster, so a threshold fitted on N2 read speech may flag expressive takes; natural Vocello takes (N3, whose expressive variation is the product default) stay informational at warn.

**Risks.**

- `pyin-tracker-unvalidated`: The audit qualifies class F only after the pitch tracker is validated (section 5.7), and pYIN's oracle ladder is not recorded yet. pYIN's own octave errors (a halved or doubled F0 on creak, breath or low energy) read as jumps, so its error rate on clean N2 sets these detectors' false-alarm floor.
- `pyin-raw-track-export`: The panel bundle keeps pYIN's whole-take L2 statistics only; its frame track (f0Hz, voiced, hopSeconds) stays in the orchestrator's L1 cache. audio_qc_calibration_set.py raw-outputs --judge pitch.pyin@1 exports it per take from the panel's cache root, and scores --raw-outputs binds each track to the take's audio and pYIN's output identity and passes it to score_take as raw; a take whose entry the cache no longer holds is an evidence gap. pYIN is not among the six judges the v1 confirmation panels run, so a class F panel adds it and keeps its cache root until the export.
- `korean-no-word-positives`: PRS-BRK and PRS-OCT act inside the longest aligned word, and the aligner is out of scope for Korean, so Korean takes carry no positives: the Korean stratum's threshold is fitted and its false alarms bounded on Korean negatives, while its detection rate is the other languages'.

**Lanes it gates** ([config/audio-qc-lane-gates.json](../../../../config/audio-qc-lane-gates.json)): none.
<!-- END GENERATED audio-qc-docs:definition -->

<!-- BEGIN GENERATED audio-qc-docs:qualification (scripts/audio_qc_docs.py regen; edit its sources, not this block) -->
## Qualification

**Status.** Refused; confirmed (refused).

**Plan.** [config/audio-qc-preregistrations/prosody.octave-jump@1.json](../../../../config/audio-qc-preregistrations/prosody.octave-jump@1.json): digest `4f2478f5404eacc0`, rule split-conformal, alpha 0.05, confidence 0.95, operating point warn, population N2; injector catalog 3, classes A,B,C,F, 150 per cell.
Calibration cohort audio-qc-n2-cohort (fleurs-reserve-1, manifest `de5491c5ecb55042`); confirmation cohort audio-qc-n2-cohort (fleurs-reserve-2, manifest `64b667943e2e4bbf`).

**Confirmation.** Ledger entry refused (cross-mechanism-detection-not-met).

**Not qualified.** No committed calibration record qualifies it: its measurements compose as `uncalibrated` and it gates no lane.

### Record [record-4f2478f5404eacc0.json](../../../../benchmarks/audio-qc-calibration/prosody.octave-jump@1/record-4f2478f5404eacc0.json): refused (cross-mechanism-detection-not-met)

Operating point warn; rule split-conformal, alpha 0.05, thresholds per language; plan `4f2478f5404eacc0`. Rates count source families with one-sided Clopper-Pearson bounds.

| Stratum | Threshold | FAR on confirmation N2 | Limit | Meets |
|---|---|---|---|---|
| chinese | 0.63 | 8/257 (0.031), upper 0.071 | 0.2 | yes |
| english | 0.53 | 14/213 (0.066), upper 0.122 | 0.2 | yes |
| french | 1.16 | 15/237 (0.063), upper 0.116 | 0.2 | yes |
| german | 0.7 | 10/245 (0.041), upper 0.085 | 0.2 | yes |
| italian | 0.42 | 8/218 (0.037), upper 0.083 | 0.2 | yes |
| japanese | 0.52 | 12/238 (0.050), upper 0.099 | 0.2 | yes |
| korean | 1.53 | 16/254 (0.063), upper 0.113 | 0.2 | yes |
| portuguese | 0.53 | 16/231 (0.069), upper 0.124 | 0.2 | yes |
| russian | 0.51 | 12/227 (0.053), upper 0.104 | 0.2 | yes |
| spanish | 0.52 | 13/202 (0.064), upper 0.122 | 0.2 | yes |
| pooled | - | 124/2322 (0.053), upper 0.062 | 0.1 | yes |

Per-language bounds at confidence 0.995 (Bonferroni over the languages), pooled at 0.95. Clean abstention: 26/2348 (0.011), upper 0.015 (limit 0.1, meets yes).

| Mechanism | Cell | Detected | Limit | Meets |
|---|---|---|---|---|
| T1-pcm-construction | PRS-OCT/severe | 11/150 (0.073), lower 0.042 | 0.7 | no |

Mechanisms meeting: - (minimum 1).

| Sham cell | Alarms | Overlaps N2 FAR | Informative |
|---|---|---|---|
| PRS-OCT | 11/150 (0.073), upper 0.118 | yes | no |

Counts: calibration 2262 clips, 2262 families, 39 abstained; confirmation N2 2348 clips, 2348 families, 26 abstained; P1 150 clips, 150 families, 0 abstained; S 150 clips, 150 families, 0 abstained. Speakers: 10 (lower-bound, unit `language:fleurs-unidentified`).

Judge output identities: `pitch.pyin@1` `a12f12f5cf71a807`. Record limitations: `fleurs-reserve-no-speaker-ids`, `fleurs-speaker-lower-bound`, `n2-one-codec`, `n2-read-speech`; risks: `pyin-tracker-unvalidated`, `pyin-raw-track-export`, `korean-no-word-positives`.
<!-- END GENERATED audio-qc-docs:qualification -->
