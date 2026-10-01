# `identity.window-drift@1`

<!-- BEGIN GENERATED audio-qc-docs:definition (scripts/audio_qc_docs.py regen; edit its sources, not this block) -->
Registry entry `identity.window-drift@1` in [config/audio-qc-detectors.json](../../../../config/audio-qc-detectors.json); definition digest `87f6d847163f6356` (a plan binds it, so any change is a new version, A7).

**Measures.** Window drift: CAM++'s whole-take cosine to the reference clip minus its lowest 2 s window cosine (0.5 s hop) to the same reference, so a span of another voice inside the take alarms against the take's own similarity while a whole-take mismatch (the clone-similarity detector's) does not.

| Class | Stage | Direction | Combination | Unit | Thresholds |
|---|---|---|---|---|---|
| E (identity) | 2 | above | difference | cosine | per language |

**Strata.** Speaker-verification scores shift with language: both speaker families train on VoxCeleb, which is mostly English, and the audit draws impostors from the same language first (section 4.3).

**Score components.**

| Languages | Components | Requires complete |
|---|---|---|
| chinese, english, french, german, italian, korean, portuguese, spanish | [`speaker.campplus-voxceleb@1`](../judges/speaker.campplus-voxceleb-v1.md) panel `cosine`; [`speaker.campplus-voxceleb@1`](../judges/speaker.campplus-voxceleb-v1.md) panel `windowCosineMinimum` | - |

**Scope.** chinese, english, french, german, italian, korean, portuguese, spanish.
Excludes japanese: The speaker group of config/audio-qc-corpora.json has no corpus in this language with speaker labels and transcripts (Japanese: JVNV, of the emotion group, has four actors and no transcript; Russian: RESD labels no speaker), so there is no speaker cohort to fit or confirm on (audit section 5.5 step 5). A corpus that meets the warn floors brings the language back as a new version.
Excludes russian: The speaker group of config/audio-qc-corpora.json has no corpus in this language with speaker labels and transcripts (Japanese: JVNV, of the emotion group, has four actors and no transcript; Russian: RESD labels no speaker), so there is no speaker cohort to fit or confirm on (audit section 5.5 step 5). A corpus that meets the warn floors brings the language back as a new version.

**Positives and shams.**

| Injector | Severities | Mechanism | Matched sham |
|---|---|---|---|
| `IDN-SWAP` | severe | T1-pcm-construction | yes |

**Populations** (role set `speaker-labeled-n2`): fit N2 (calibration, speaker-corpora-v1-calibration); confirmNegatives N2 (confirmation, speaker-corpora-v1-confirmation); positives P1 (confirmation); shams S (confirmation); informational N3, N1.

**Limitations.**

- `speaker-corpora-v1`: FLEURS publishes no speaker ids, so class E fits and confirms on the speaker cohort (role set speaker-labeled-n2: speaker-corpora-v1-calibration, then speaker-corpora-v1-confirmation), which audio_qc_corpora.py cohort --source speaker builds from the speaker group of config/audio-qc-corpora.json under the maintainer's decision of 2026-09-30 (anonymous same- and different-speaker trials, outputs never published; never speaker identification). Each language reads one corpus: LibriTTS-R dev.clean and test.clean (English), Multilingual LibriSpeech (German, French, Spanish, Italian, Portuguese), the AISHELL-3 test subset (Chinese) and Zeroth-Korean (Korean), all read speech, resynthesized to N2. A take has a transcript and 4-30 s of audio, at most 10 per speaker; the splits are disjoint by speaker (a seeded split within each corpus) and by script, and on the extraction of 2026-09-30 every language holds 167 to 580 families from 22 to 58 speakers per split, above the warn floors (60 scored families and 3 speakers per language). CREMA-D (no transcript, 1-5 s acted clips) and Emozionalmente (Italian reads Multilingual LibriSpeech, so a donor never differs from its source by recording channel) serve no cohort. The negatives are read speech: FAR on conversational or expressive speech is not measured.
- `speaker-reference-clip`: The speaker judges score a take only against a reference clip: another utterance of the same speaker for a corpus take, the clone's reference in the clone lane (panel_jobs: needs_reference). The orchestrator embeds it only when the manifest names it (a calibration take's or entry's reference: its WAV path and digest); without one CAM++ reports no similarity and the take abstains (no-value), and the calibration refuses evidence measured against another clip than the declared one.
- `speaker-reference-n2`: Each cohort take is scored against another take of its speaker in the same split, with another script (the cohort's seeded reference choice), and the N2 manifest names that take's resynthesis, so both sides carry the codec, as an impostor is scored against its N2 source take. The clone lane scores a generated take against the user's raw recording, so its similarity also carries the clone's own shortfall and the codec on one side only: these thresholds bound FAR on pairs of human codec speech, and clone takes stay informational (n3-clone-takes).
- `speaker-gender-unlabelled`: IDN-IMPOSTOR and the recorded IDN-SWAP and IDN-ONSET splices draw donors of the source's language and gender, and LibriTTS-R and Zeroth-Korean publish no speaker gender (no pinnable source on the allowed hosts; a gender is never guessed), so English and Korean takes neither receive nor give such a positive (Korean also has no word intervals for a splice: aligner-excludes-korean). Their FAR is bounded like every language's, but those cells are drawn from German, French, Spanish, Italian, Portuguese and Chinese; IDN-SHIFT, which needs no donor, is drawn in every language. English and Korean sensitivity is therefore measured through IDN-SHIFT only (clone-similarity) and not at all for the drift detectors: a lane should read it as report-only there.

**Risks.**

- `resnet293-not-voting`: The audit fails an identity only when both speaker families fall below their thresholds and abstains when they disagree (section 4.3), but ResNet293 votes only after its correlated-failure audit against CAM++ (the same VoxCeleb training data) passes. These detectors read CAM++ alone; the two-family rule (consensus-max of the two families' scores) is a new version once ResNet293 votes.
- `short-window-embeddings`: Speaker embeddings degrade on short windows (audit section 4.3): a 2 s window scores lower against the reference than the whole take even on clean speech. The drift and onset scores subtract the window's cosine from the take's own whole-take cosine, so each take is its own baseline; a take shorter than one window has none and abstains (no-value).

**Lanes it gates** ([config/audio-qc-lane-gates.json](../../../../config/audio-qc-lane-gates.json)): none.
<!-- END GENERATED audio-qc-docs:definition -->

<!-- BEGIN GENERATED audio-qc-docs:qualification (scripts/audio_qc_docs.py regen; edit its sources, not this block) -->
## Qualification

**Status.** Not qualified; planned, not confirmed.

**Plan.** [config/audio-qc-preregistrations/identity.window-drift@1.json](../../../../config/audio-qc-preregistrations/identity.window-drift@1.json): digest `dd56165e2339406c`, rule split-conformal, alpha 0.05, confidence 0.95, operating point warn, population N2; injector catalog 3, classes E, 150 per cell.
Calibration cohort audio-qc-n2-cohort (speaker-corpora-v1-calibration, manifest `efc0efc2306671e6`); confirmation cohort audio-qc-n2-cohort (speaker-corpora-v1-confirmation, manifest `02ccee35215e5844`).

**Confirmation.** Not run: no ledger entry.

**Not qualified.** No committed calibration record qualifies it: its measurements compose as `uncalibrated` and it gates no lane.
<!-- END GENERATED audio-qc-docs:qualification -->
