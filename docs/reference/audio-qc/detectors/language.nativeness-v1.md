# `language.nativeness@1`

<!-- BEGIN GENERATED audio-qc-docs:definition (scripts/audio_qc_docs.py regen; edit its sources, not this block) -->
Registry entry `language.nativeness@1` in [config/audio-qc-detectors.json](../../../../config/audio-qc-detectors.json); definition digest `94d8b3e35238fbd9` (a plan binds it, so any change is a new version, A7).

**Measures.** Whether the take sounds like a native speaker of the expected language: the mean of Whisper large-v3's expected-language probability and VoxLingua107's expected-language posterior, fitted on native read speech (N2 FLEURS), direction below. An accent pulls both classifiers' confidence down while they still identify the language; language.consensus-lid@1 takes the larger of the two, so both must be low (another language), and counts accented speech as a negative (audit section 4.2). Native FLEURS French scores a VoxLingua posterior of 0.999 at the median; the app's French from Serena 0.39.

| Class | Stage | Direction | Combination | Unit | Thresholds |
|---|---|---|---|---|---|
| D (language) | 2 | below | consensus-mean | probability | per language |

**Strata.** Each classifier's confidence on native speech differs by language (spent AQ-07 dev N2, 5th percentile of the mean: 0.487 in de and 0.516 in ru, where VoxLingua is weak, to 0.997 in ko).

**Score components.**

| Languages | Components | Requires complete |
|---|---|---|
| chinese, english, french, german, italian, japanese, korean, portuguese, russian, spanish | [`asr.whisper-large-v3@1`](../judges/asr.whisper-large-v3-v1.md) panel `expectedLanguageProbability`; [`lid.voxlingua107-ecapa@1`](../judges/lid.voxlingua107-ecapa-v1.md) panel `expectedPosterior` | - |

**Scope.** chinese, english, french, german, italian, japanese, korean, portuguese, russian, spanish.

**Positives and shams.**

| Injector | Severities | Mechanism | Matched sham |
|---|---|---|---|
| `NAT-ACCENT` | severe | T4-natural-labelled | no |

**Populations** (role set `accent-natural-n2`): fit N2 (calibration, fleurs-reserve-1); confirmNegatives N2 (confirmation, fleurs-reserve-2; at a fail point fleurs-reserve-3); positives P4 (confirmation, speechocean762-confirmation); shams S (confirmation); informational N3, N1.

**Limitations.**

- `fleurs-reserve-no-speaker-ids`: FLEURS publishes no speaker ids; its TSVs give only a gender per recording. The reserve cohorts are drawn from the one train split (config/audio-qc-corpora.json fleurs-train), disjoint by FLoRes sentence from each other and from dev and test, so family and script disjointness hold; but they are grouped by sentence, not by speaker, so a train speaker who read sentences of two cohorts speaks in both: the calibration (reserve-1) and confirmation (reserve-2) cohorts likely share speakers, and neither that nor a speaker count can be measured.
- `fleurs-speaker-lower-bound`: Units carry the speaker '<language>:fleurs-unidentified', a lower bound on the speaker count: FLEURS collects each locale separately, so recordings of different languages cannot share a speaker. The policy minimum of 3 speakers is therefore met only by covering at least 3 languages.
- `n2-one-codec`: N2 is one production codec round trip (the pro_clone speed variant at full codebooks) of FLEURS read speech; FAR on it is in the codec's domain, not on natural Vocello takes (N3, informational at warn).
- `accent-positives-english-only`: Natural non-native positives exist for English only (speechocean762: Mandarin-L1 speakers reading English), so the detection rate is English's: the other nine languages' thresholds bound their FAR on native N2 speech, but their sensitivity to an accent is unmeasured. A lane should read them as report-only until a labelled non-native corpus of that language exists; the lane gates declare each lane's languages.
- `accent-labels-exception`: The positives' labels are published expert pronunciation scores (T4, speechocean762's sentence-level accuracy). The policy defines P4 as harvested natural failures with T5 labels and lets T4 qualify negatives only; by the maintainer's decision of 2026-09-30 (the policy's labelTierExceptions) speechocean762's accuracy may label this detector's English positives, and no other detector's. The driver refuses natural positives the exception does not name (detector, corpus, field and language). The rules (4 or less severe, 5-6 moderate, of 10) follow the corpus's rubric (heavy accent, many errors), not a fitted cut, so the detection rate is agreement with one expert panel's grading.
- `accent-single-l1`: The positives are the confirmation split of speechocean762 (audio_qc_corpora.py cohort, split by speaker from its extraction, which records each utterance's speaker and scores), resynthesized to N2 like the negatives and scored by a panel of Whisper large-v3 and VoxLingua after the plan. Every speaker is Mandarin L1, so one accent is measured. How many utterances score 4 or less is not known before the extraction, so the builder reports how many the confirmation split holds against the warn floor of 60 before any model runs.
- `mean-consensus-warn-only`: A two-family mean (consensus-mean) qualifies at warn only, by the maintainer's decision of 2026-09-30 (the policy's decisions): Whisper large-v3 silently drops repeated words, so a strict consensus cannot see what one family never transcribes, but a fail level keeps strict two-family consensus (consensus-min or consensus-max). The policy's fail operating points refuse the combination (refusedCombinations), so plan refuses a fail plan of this version and validate refuses any fail plan or record of it; a fail bound needs a new version with a strict consensus.

**Risks.**

- `voxlingua-weak-native-de-ru`: VoxLingua's expected-language posterior is low on much native German and Russian (below 0.5 on about a fifth and two fifths of N2 recordings), so the mean's threshold there sits near 0.5 (spent AQ-07 dev N2 at alpha 0.05: 0.487 in de, 0.516 in ru) and only a strong drop of both classifiers alarms: nativeness in de and ru is close to blind.
- `one-classifier-alarm`: Under the two-family mean one classifier's collapse alarms alone once it falls twice the margin below its native level: VoxLingua's posterior falls further on accented speech than Whisper's language probability (the app's French from Serena: medians 0.39 and 0.97), so the detector mostly reads VoxLingua's view of the accent, which Whisper's near-native confidence only halves.
- `accent-by-voice`: The app's own takes flag by voice as much as by language (spent N3 data at alpha 0.05, French: Serena 19/27, Aiden 13/26, Design 9/27; Spanish 48 of 79): what the detector reports is a voice that sounds foreign in a language, and N3 carries no label saying how many of those a native listener would hear.

**Lanes it gates** ([config/audio-qc-lane-gates.json](../../../../config/audio-qc-lane-gates.json)): none.
<!-- END GENERATED audio-qc-docs:definition -->

<!-- BEGIN GENERATED audio-qc-docs:qualification (scripts/audio_qc_docs.py regen; edit its sources, not this block) -->
## Qualification

**Status.** Not qualified; planned, not confirmed.

**Plan.** [config/audio-qc-preregistrations/language.nativeness@1.json](../../../../config/audio-qc-preregistrations/language.nativeness@1.json): digest `d0d8fe2899a115e0`, rule split-conformal, alpha 0.05, confidence 0.95, operating point warn, population N2; injector catalog -, classes -, - per cell.
Calibration cohort audio-qc-n2-cohort (fleurs-reserve-1, manifest `de5491c5ecb55042`); confirmation cohort audio-qc-n2-cohort (fleurs-reserve-2, manifest `64b667943e2e4bbf`).

**Confirmation.** Not run: no ledger entry.

**Not qualified.** No committed calibration record qualifies it: its measurements compose as `uncalibrated` and it gates no lane.
<!-- END GENERATED audio-qc-docs:qualification -->
