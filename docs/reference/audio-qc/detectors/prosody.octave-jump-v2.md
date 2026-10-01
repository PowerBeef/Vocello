# `prosody.octave-jump@2`

<!-- BEGIN GENERATED audio-qc-docs:definition (scripts/audio_qc_docs.py regen; edit its sources, not this block) -->
Registry entry `prosody.octave-jump@2` in [config/audio-qc-detectors.json](../../../../config/audio-qc-detectors.json); definition digest `91228b54efda0f14` (a plan binds it, so any change is a new version, A7).

**Measures.** The longest chain, in voiced seconds, of pYIN frames inside the speech band (60-800 Hz) that sit 9 to 15 semitones above the median of the in-band voiced frames within 1 s of each; an unvoiced gap of up to 250 ms continues a chain, and a voiced frame that does not rise ends it. An octave jump lifts a span of speech about 12 semitones above the register around it, whether pYIN's voicing breaks at its edges or inside it. Rises only: pYIN's subharmonic errors read frames an octave low, and a rise beyond 15 semitones is tracker debris. A take without an in-band voiced frame abstains.

| Class | Stage | Direction | Combination | Unit | Thresholds |
|---|---|---|---|---|---|
| F (prosody) | 1 | above | single | seconds | per language |

**Strata.** Lexical tone (zh) and pitch accent (ja) move F0 faster within a syllable than intonation does in the other languages, so each language is its own clean distribution.

**Score components.**

| Languages | Components | Requires complete |
|---|---|---|
| chinese, english, french, german, italian, japanese, korean, portuguese, russian, spanish | [`pitch.pyin@1`](../judges/pitch.pyin-v1.md) raw-output `longestOctaveRiseSeconds` | - |

**Scope.** chinese, english, french, german, italian, japanese, korean, portuguese, russian, spanish.

**Positives and shams.**

| Injector | Severities | Mechanism | Matched sham |
|---|---|---|---|
| `PRS-OCT` | severe | T1-pcm-construction | yes |

**Populations** (role set `fleurs-reserve-4-n2`): fit N2 (calibration, fleurs-reserve-1); confirmNegatives N2 (confirmation, pending-fleurs-reserve-4; at a fail point fleurs-reserve-3); positives P1 (confirmation); shams S (confirmation); informational N3, N1.

**Limitations.**

- `fleurs-reserve-no-speaker-ids`: FLEURS publishes no speaker ids; its TSVs give only a gender per recording. The reserve cohorts are drawn from the one train split (config/audio-qc-corpora.json fleurs-train), disjoint by FLoRes sentence from each other and from dev and test, so family and script disjointness hold; but they are grouped by sentence, not by speaker, so a train speaker who read sentences of two cohorts speaks in both: the calibration (reserve-1) and confirmation (reserve-2) cohorts likely share speakers, and neither that nor a speaker count can be measured.
- `fleurs-speaker-lower-bound`: Units carry the speaker '<language>:fleurs-unidentified', a lower bound on the speaker count: FLEURS collects each locale separately, so recordings of different languages cannot share a speaker. The policy minimum of 3 speakers is therefore met only by covering at least 3 languages.
- `n2-one-codec`: N2 is one production codec round trip (the pro_clone speed variant at full codebooks) of FLEURS read speech; FAR on it is in the codec's domain, not on natural Vocello takes (N3, informational at warn).
- `n2-read-speech`: FLEURS is read speech, while the audit's class F negatives are expressive N1 (section 5.7): expressive speech moves F0 further and faster, so a threshold fitted on N2 read speech may flag expressive takes; natural Vocello takes (N3, whose expressive variation is the product default) stay informational at warn.
- `fleurs-reserve-4-pending`: FLEURS reserve-2 is spent (the reserve plans of 2026-09-30 confirmed on it, prosody.pitch-break@1 and prosody.octave-jump@1 among them) and reserve-3 is held back for a fail point. Role set fleurs-reserve-4-n2 fits on reserve-1 again and confirms on a fourth reserve cohort, script-disjoint from the first three, which config/audio-qc-corpora.json does not extract yet (its fleurs-train extract declares 3 cohorts). The registry names it pending- until the maintainer extracts and resynthesizes it, so plan refuses the role set until then.
- `pitch-speech-band`: Class F version 2 reads pYIN's voiced frames between 60 and 800 Hz only (detectors.py PITCH_BAND_HZ); a voiced frame outside the band counts as unvoiced. Below the band lie pYIN's readings at its 50 Hz floor on creak and noise, above it debris near its 1 kHz ceiling on fricatives and breath; on the calibration cohorts (the N3 takes and FLEURS reserve-1 N2) both formed displaced runs of 0.3 s and more in clean takes. A voice outside the band is not measured: an octave rise of a voice above 400 Hz leaves it, and a take with too little in-band voicing abstains (no-value).
- `octave-rise-upward-only`: prosody.octave-jump@2 scores rises only. pYIN's subharmonic errors on creak and low energy read clean frames an octave low, and no frame-track measure tells them from a downward jump of the same span, so a downward octave jump (PRS-OCT's down-moderate variant, which is no target) is not scored.
- `octave-unvoiced-spans`: PRS-OCT shifts a fixed span in the middle of the longest aligned word, whatever its voicing. In the pilot of 2026-10-01 (100 severe positives built on catalog 4 from FLEURS reserve-1 N2), 9 spans lay where the source track has fewer than 3 voiced frames, and pYIN lost voicing over about 15 more of the shifted spans. About a quarter of the severe cell therefore carries no rise the frame track can read, which bounds its detection near 0.75 whatever the threshold; the pilot reached 0.61 at alpha 0.05 (lower 95% bound 0.52, below A3's 0.70).

**Risks.**

- `pyin-tracker-unvalidated`: The audit qualifies class F only after the pitch tracker is validated (section 5.7), and pYIN's oracle ladder is not recorded yet. pYIN's own octave errors (a halved or doubled F0 on creak, breath or low energy) read as jumps, so its error rate on clean N2 sets these detectors' false-alarm floor.
- `pyin-raw-track-export`: The panel bundle keeps pYIN's whole-take L2 statistics only; its frame track (f0Hz, voiced, hopSeconds) stays in the orchestrator's L1 cache. audio_qc_calibration_set.py raw-outputs --judge pitch.pyin@1 exports it per take from the panel's cache root, and scores --raw-outputs binds each track to the take's audio and pYIN's output identity and passes it to score_take as raw; a take whose entry the cache no longer holds is an evidence gap. pYIN is not among the six judges the v1 confirmation panels run, so a class F panel adds it and keeps its cache root until the export.
- `pyin-voicing-gaps`: pYIN's 64 ms frame straddles both pitches of a large step, so it often drops voicing over the step for 50-120 ms instead of ramping across it (catalog-4 PRS-ERRATIC severe: typically 6 to 8 unvoiced frames at a sign change). Version 1's reductions compare voiced frames at most 50 ms apart and missed most of those steps (pilot of 2026-10-01: 9 of 150 severe N3 positives). The version 2 measures bridge gaps up to 160 ms (level steps) or 250 ms (octave chains): a step across a longer gap is not compared, and a pause shorter than the reach joins two words' levels, which the per-language thresholds absorb.
- `korean-no-word-positives`: PRS-BRK and PRS-OCT act inside the longest aligned word, and the aligner is out of scope for Korean, so Korean takes carry no positives: the Korean stratum's threshold is fitted and its false alarms bounded on Korean negatives, while its detection rate is the other languages'.

**Lanes it gates** ([config/audio-qc-lane-gates.json](../../../../config/audio-qc-lane-gates.json)): none.
<!-- END GENERATED audio-qc-docs:definition -->

<!-- BEGIN GENERATED audio-qc-docs:qualification (scripts/audio_qc_docs.py regen; edit its sources, not this block) -->
## Qualification

**Status.** Not qualified; no plan.

**Plan.** None committed under [config/audio-qc-preregistrations/](../../../../config/audio-qc-preregistrations).

**Not qualified.** No committed calibration record qualifies it: its measurements compose as `uncalibrated` and it gates no lane.
<!-- END GENERATED audio-qc-docs:qualification -->
