# `prosody.pitch-instability@2`

<!-- BEGIN GENERATED audio-qc-docs:definition (scripts/audio_qc_docs.py regen; edit its sources, not this block) -->
Registry entry `prosody.pitch-instability@2` in [config/audio-qc-detectors.json](../../../../config/audio-qc-detectors.json); definition digest `1a3da32c0828136c` (a plan binds it, so any change is a new version, A7).

**Measures.** Level steps per voiced second, reduced from pYIN's frame track inside the speech band (60-800 Hz). The track is cut into level segments at every unvoiced frame and every frame-to-frame change of 1.5 semitones or more (pYIN's ramp across a step), segments shorter than 40 ms are dropped, and two segments at most 160 ms apart meet at a junction whose step is the median of the later segment's first three frames minus the median of the earlier one's last three. Junctions that step 8 semitones or more, either way, are counted over the take's in-band voiced seconds. A pitch that jumps from span to span scores high whether pYIN ramps across a jump or drops voicing over it, while intonation glides inside a segment; 8 semitones lies above the 6-7 semitone steps read speech takes across short voicing gaps. A take with less than 1 s of in-band voiced speech abstains.

| Class | Stage | Direction | Combination | Unit | Thresholds |
|---|---|---|---|---|---|
| F (prosody) | 1 | above | single | events-per-second | per language |

**Strata.** Lexical tone (zh) and pitch accent (ja) move F0 faster within a syllable than intonation does in the other languages, so each language is its own clean distribution.

**Score components.**

| Languages | Components | Requires complete |
|---|---|---|
| chinese, english, french, german, italian, japanese, korean, portuguese, russian, spanish | [`pitch.pyin@1`](../judges/pitch.pyin-v1.md) raw-output `pitchLevelStepsPerVoicedSecond` | - |

**Scope.** chinese, english, french, german, italian, japanese, korean, portuguese, russian, spanish.

**Positives and shams.**

| Injector | Severities | Mechanism | Matched sham |
|---|---|---|---|
| `PRS-ERRATIC` | severe | T1-pcm-construction | yes |

**Populations** (role set `n3-takes-fresh`): fit N3 (calibration, vocello-takes-calibration); confirmNegatives N3 (confirmation, pending-vocello-takes-confirmation-2); positives P1 (confirmation); shams S (confirmation); informational N2.

**Limitations.**

- `n3-expressive-negatives`: The negatives are natural Vocello takes (N3: the product's expressive variation, Built-in and Voice Design voices), so natural expressive speech is a negative, as the maintainer's report of erratic pitch in Voice Clone takes needs; a threshold fitted on FLEURS read speech (N2, informational here) would flag expressive intonation. N3 carries no labels, so the flag rate bounds the false-alarm rate only as f / (1 - pi_max) (audit section 5.1), and a fail bound still needs an expressive N2 corpus (the audit's expressive N1, section 5.7). Each language stratum needs at least 60 scored families in each split of the take plan (the calibration split plans 80 per language).
- `n3-clone-takes`: Version 2 of the take plan (config/audio-qc-calibration-takes.json) adds a clone cell to both N3 splits: Voice Clone takes on human reference clips of the pinned speaker corpora, 80 per language per split, each reference speaker in one split only. The maintainer hears erratic pitch in exactly those takes, and N3 carries no labels, so the fit counts every clone take as clean: an erratic clone take raises the threshold instead of alarming, and the confirmation split's flag rate bounds the false-alarm rate only as f / (1 - pi_max).
- `n3-confirmation-renewed`: The take plan's confirmation split is spent for class F: prosody.pitch-instability@1 confirmed on it on 2026-10-01, with PRS-ERRATIC positives built on its takes. Role set n3-takes-fresh fits on the calibration split again and confirms on a new N3 confirmation split that has never been scored, disjoint by family, speaker and script from both splits of take plan version 2 (a new take plan version with its own scripts and clone reference speakers: regenerating the old split's scripts and seeds would replay spent material). The registry names it pending- until it is generated, so plan refuses the role set until then.
- `pitch-speech-band`: Class F version 2 reads pYIN's voiced frames between 60 and 800 Hz only (detectors.py PITCH_BAND_HZ); a voiced frame outside the band counts as unvoiced. Below the band lie pYIN's readings at its 50 Hz floor on creak and noise, above it debris near its 1 kHz ceiling on fricatives and breath; on the calibration cohorts (the N3 takes and FLEURS reserve-1 N2) both formed displaced runs of 0.3 s and more in clean takes. A voice outside the band is not measured: an octave rise of a voice above 400 Hz leaves it, and a take with too little in-band voicing abstains (no-value).

**Risks.**

- `pyin-tracker-unvalidated`: The audit qualifies class F only after the pitch tracker is validated (section 5.7), and pYIN's oracle ladder is not recorded yet. pYIN's own octave errors (a halved or doubled F0 on creak, breath or low energy) read as jumps, so its error rate on clean N2 sets these detectors' false-alarm floor.
- `pyin-raw-track-export`: The panel bundle keeps pYIN's whole-take L2 statistics only; its frame track (f0Hz, voiced, hopSeconds) stays in the orchestrator's L1 cache. audio_qc_calibration_set.py raw-outputs --judge pitch.pyin@1 exports it per take from the panel's cache root, and scores --raw-outputs binds each track to the take's audio and pYIN's output identity and passes it to score_take as raw; a take whose entry the cache no longer holds is an evidence gap. pYIN is not among the six judges the v1 confirmation panels run, so a class F panel adds it and keeps its cache root until the export.
- `pyin-voicing-gaps`: pYIN's 64 ms frame straddles both pitches of a large step, so it often drops voicing over the step for 50-120 ms instead of ramping across it (catalog-4 PRS-ERRATIC severe: typically 6 to 8 unvoiced frames at a sign change). Version 1's reductions compare voiced frames at most 50 ms apart and missed most of those steps (pilot of 2026-10-01: 9 of 150 severe N3 positives). The version 2 measures bridge gaps up to 160 ms (level steps) or 250 ms (octave chains): a step across a longer gap is not compared, and a pause shorter than the reach joins two words' levels, which the per-language thresholds absorb.

**Lanes it gates** ([config/audio-qc-lane-gates.json](../../../../config/audio-qc-lane-gates.json)): none.
<!-- END GENERATED audio-qc-docs:definition -->

<!-- BEGIN GENERATED audio-qc-docs:qualification (scripts/audio_qc_docs.py regen; edit its sources, not this block) -->
## Qualification

**Status.** Not qualified; no plan.

**Plan.** None committed under [config/audio-qc-preregistrations/](../../../../config/audio-qc-preregistrations).

**Not qualified.** No committed calibration record qualifies it: its measurements compose as `uncalibrated` and it gates no lane.
<!-- END GENERATED audio-qc-docs:qualification -->
