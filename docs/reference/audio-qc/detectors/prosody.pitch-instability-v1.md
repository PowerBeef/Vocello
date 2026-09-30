# `prosody.pitch-instability@1`

<!-- BEGIN GENERATED audio-qc-docs:definition (scripts/audio_qc_docs.py regen; edit its sources, not this block) -->
Registry entry `prosody.pitch-instability@1` in [config/audio-qc-detectors.json](../../../../config/audio-qc-detectors.json); definition digest `48761aa606877abc` (a plan binds it, so any change is a new version, A7).

**Measures.** Pitch jumps per voiced second, reduced from pYIN's frame track: F0 changes between consecutive voiced frames at most 50 ms apart faster than 150 semitones per second (about twice the fastest change a speaker makes), a cluster within 50 ms counted once, over the take's voiced seconds. A pitch that jumps from syllable to syllable scores high, while expressive intonation, however wide, glides below the rate; semitone rates do not depend on the voice's register. A take with less than 1 s of voiced speech abstains.

| Class | Stage | Direction | Combination | Unit | Thresholds |
|---|---|---|---|---|---|
| F (prosody) | 1 | above | single | events-per-second | per language |

**Strata.** Lexical tone (zh) and pitch accent (ja) move F0 faster within a syllable than intonation does in the other languages, so each language is its own clean distribution.

**Score components.**

| Languages | Components | Requires complete |
|---|---|---|
| chinese, english, french, german, italian, japanese, korean, portuguese, russian, spanish | [`pitch.pyin@1`](../judges/pitch.pyin-v1.md) raw-output `pitchJumpsPerVoicedSecond` | - |

**Scope.** chinese, english, french, german, italian, japanese, korean, portuguese, russian, spanish.

**Positives and shams.**

| Injector | Severities | Mechanism | Matched sham |
|---|---|---|---|
| `PRS-ERRATIC` | severe | T1-pcm-construction | yes |

**Populations** (role set `n3-takes`): fit N3 (calibration, vocello-takes-calibration); confirmNegatives N3 (confirmation, vocello-takes-confirmation); positives P1 (confirmation); shams S (confirmation); informational N2.

**Limitations.**

- `n3-expressive-negatives`: The negatives are natural Vocello takes (N3: the product's expressive variation, Built-in and Voice Design voices), so natural expressive speech is a negative, as the maintainer's report of erratic pitch in Voice Clone takes needs; a threshold fitted on FLEURS read speech (N2, informational here) would flag expressive intonation. N3 carries no labels, so the flag rate bounds the false-alarm rate only as f / (1 - pi_max) (audit section 5.1), and a fail bound still needs an expressive N2 corpus (the audit's expressive N1, section 5.7). Each language stratum needs at least 60 scored families in each split of the take plan (the calibration split plans 80 per language).
- `n3-no-clone-takes`: The maintainer hears erratic pitch in Voice Clone takes, but the N3 take plan (config/audio-qc-calibration-takes.json) covers Built-in and Voice Design voices only, so no clone take is a negative or informational yet; a clone split needs reference clips that may be cloned (the class E speaker corpus would serve) and the same families per stratum.

**Risks.**

- `pyin-tracker-unvalidated`: The audit qualifies class F only after the pitch tracker is validated (section 5.7), and pYIN's oracle ladder is not recorded yet. pYIN's own octave errors (a halved or doubled F0 on creak, breath or low energy) read as jumps, so its error rate on clean N2 sets these detectors' false-alarm floor.
- `pyin-raw-track-export`: The panel bundle keeps pYIN's whole-take L2 statistics only; its frame track (f0Hz, voiced, hopSeconds) stays in the orchestrator's L1 cache. The scores need it exported per take, as audio_qc_calibration_set.py alignments exports the aligner's intervals, and passed to score_take as raw; no command does that yet, and pYIN is not among the six judges the v1 confirmation panels run.
- `no-erratic-pitch-injector`: Injector catalog version 2 has no erratic-pitch construction: PRS-BRK and PRS-OCT change one span each, which a take-level rate barely registers. PRS-ERRATIC would cut the take into seeded 150-300 ms spans and shift each by a seeded sign and magnitude (2, 4 and 7 semitones for mild, moderate and severe) through the PRS-BRK shifter, with 0 semitones through the same path as its sham; it needs no word interval, so it runs on N3 recordings. Until it exists the detector has no positives.

**Lanes it gates** ([config/audio-qc-lane-gates.json](../../../../config/audio-qc-lane-gates.json)): none.
<!-- END GENERATED audio-qc-docs:definition -->

<!-- BEGIN GENERATED audio-qc-docs:qualification (scripts/audio_qc_docs.py regen; edit its sources, not this block) -->
## Qualification

**Status.** Not qualified; no plan.

**Plan.** None committed under [config/audio-qc-preregistrations/](../../../../config/audio-qc-preregistrations).

**Not qualified.** No committed calibration record qualifies it: its measurements compose as `uncalibrated` and it gates no lane.
<!-- END GENERATED audio-qc-docs:qualification -->
