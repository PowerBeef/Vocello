# `signal.terminal-silence@2`

<!-- BEGIN GENERATED audio-qc-docs:definition (scripts/audio_qc_docs.py regen; edit its sources, not this block) -->
Registry entry `signal.terminal-silence@2` in [config/audio-qc-detectors.json](../../../../config/audio-qc-detectors.json); definition digest `9d6c49f524fa2ccf` (a plan binds it, so any change is a new version, A7).

**Measures.** The run of exact digital silence (PCM16 zeros) after the take's last nonzero sample, in milliseconds (pcmMeasures trailingDigitalSilenceMS), against one threshold pooled over the languages. FLEURS's natural trailing room tone is never exactly zero, so the score does not follow the recording conditions that set v1's per-language thresholds (3 ms in pt against 2.8 s in ko).

| Class | Stage | Direction | Combination | Unit | Thresholds |
|---|---|---|---|---|---|
| A (signal) | 0 | above | single | milliseconds | pooled |

**Score components.**

| Languages | Components | Requires complete |
|---|---|---|
| chinese, english, french, german, italian, japanese, korean, portuguese, russian, spanish | [`fastqc@8`](../judges/fastqc-v8.md) pcm `trailingDigitalSilenceMS` | - |

**Scope.** chinese, english, french, german, italian, japanese, korean, portuguese, russian, spanish.

**Positives and shams.**

| Injector | Severities | Mechanism | Matched sham |
|---|---|---|---|
| `SIG-SIL` | moderate, severe | T1-pcm-construction | yes |

**Populations** (role set `fleurs-reserve-n2`): fit N2 (calibration, fleurs-reserve-1); confirmNegatives N2 (confirmation, fleurs-reserve-2; at a fail point fleurs-reserve-3); positives P1 (confirmation); shams S (confirmation); informational N3, N1.

**Limitations.**

- `fleurs-reserve-no-speaker-ids`: FLEURS publishes no speaker ids; its TSVs give only a gender per recording. The reserve cohorts are drawn from the one train split (config/audio-qc-corpora.json fleurs-train), disjoint by FLoRes sentence from each other and from dev and test, so family and script disjointness hold; but they are grouped by sentence, not by speaker, so a train speaker who read sentences of two cohorts speaks in both: the calibration (reserve-1) and confirmation (reserve-2) cohorts likely share speakers, and neither that nor a speaker count can be measured.
- `fleurs-speaker-lower-bound`: Units carry the speaker '<language>:fleurs-unidentified', a lower bound on the speaker count: FLEURS collects each locale separately, so recordings of different languages cannot share a speaker. The policy minimum of 3 speakers is therefore met only by covering at least 3 languages.
- `n2-one-codec`: N2 is one production codec round trip (the pro_clone speed variant at full codebooks) of FLEURS read speech; FAR on it is in the codec's domain, not on natural Vocello takes (N3, informational at warn).
- `digital-silence-only`: The score counts exact digital silence (PCM16 zeros) only: a quiet but nonzero gap or tail (room tone, codec silence tokens, an attenuated span) is not scored, so a generated pause or tail that merely runs long is outside this detector. The legacy Fast QC v8 silence flags keep reporting those (A10), and SIG-DROP's attenuated variant is no target.
- `pcm-measures-python-only`: The pcmMeasures block is measured by the calibration scorer (scripts/lib/qc_qualification/pcm_measures.py, audio_qc_calibration_set.py score) over the persisted PCM16, not inside the engine: until a Swift mirror joins the Stage 0 observations the app's own takes carry no such field, so the detector serves the evidence lanes that run the scorer. An N1 recording is measured after its resampling, which smooths flat tops and zero runs.

**Risks.**

- `fleurs-digital-silence`: FLEURS N2 holds exact-zero spans that generated takes never show (spent AQ-07 cohorts: clean dev N2 interior runs up to 0.88 s, 99th percentile 0.40 s, from zh, es and ru recordings, and trailing runs up to 17 ms in zh and en; the 791 N3 takes of 2026-09-27: at most 1 ms), so the pooled thresholds sit near 0.4 s inside the take and 12 ms at its end, and a shorter digital dropout (SIG-DROP mild, 150 ms) is missed.
- `pooled-fleurs-locale-concentration`: One threshold pooled over the languages puts FLEURS's false alarms in the locales whose recording chain sits furthest out, while the confirmation still bounds every language's FAR (0.20 at warn, upper bound at the Bonferroni confidence). On the spent AQ-07 cohorts (design data, fitted on FLEURS dev N2 and counted on test N2), a pooled plan at alpha 0.05 put the worst language's bound at 0.354 (German DC), 0.283 (Spanish digital dropout) and 0.265 (English digital tail), and at alpha 0.01 at 0.066, 0.075 and 0.071: plan these detectors at alpha 0.01.

**Lanes it gates** ([config/audio-qc-lane-gates.json](../../../../config/audio-qc-lane-gates.json)): none.
<!-- END GENERATED audio-qc-docs:definition -->

<!-- BEGIN GENERATED audio-qc-docs:qualification (scripts/audio_qc_docs.py regen; edit its sources, not this block) -->
## Qualification

**Status.** Not qualified; no plan.

**Plan.** None committed under [config/audio-qc-preregistrations/](../../../../config/audio-qc-preregistrations).

**Not qualified.** No committed calibration record qualifies it: its measurements compose as `uncalibrated` and it gates no lane.
<!-- END GENERATED audio-qc-docs:qualification -->
