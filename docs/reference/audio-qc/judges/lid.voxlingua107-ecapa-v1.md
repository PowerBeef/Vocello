# `lid.voxlingua107-ecapa@1`

<!-- BEGIN GENERATED audio-qc-docs:facts (scripts/audio_qc_docs.py regen; edit its sources, not this block) -->
Registry entry `lid.voxlingua107-ecapa@1` in [config/audio-qc-judges.json](../../../../config/audio-qc-judges.json).

**Measures.** Audio language-ID vote 1 (audit section 4.2): posteriors over 107 languages, restricted downstream to the ten product languages plus an other mass; warn-only until calibrated per language and voice.

| Status | Calibration | Kind | Family | Votes | Ships | Stage | Determinism |
|---|---|---|---|---|---|---|---|
| `shadow` | legacy-unqualified | neural | lid-voxlingua107 | yes | no | 2 (cpu) | D0 (expected D0) |

`shadow`: Runs beside the current judges; its verdicts are uncalibrated and never block.

**Languages.** identifies: en, de, fr, es, it, pt, ru, zh, ja, ko.

**Audit section.** 4.2.

## Provenance

- License tier **B** (scraped-web-audio): Permissive weights, but training data includes scraped web audio or corpora whose rights stay with the original owners, with no explicit non-commercial term. Internal, never-shipped evaluation only (decision 2a). Commercial use compatible: yes.
- Weights: Apache-2.0
- Code: Apache-2.0 (SpeechBrain)
- Training data: VoxLingua107: 6,628 hours of YouTube-derived speech in 107 languages, labeled from video titles and descriptions; copyright stays with the owners; no explicit non-commercial term
- Tier-B acceptance: decision 2a (2026-09-25), scope `internal-never-shipped-evaluation`.
- Independence: vendor SpeechBrain (VoxLingua107, TalTech); architecture ECAPA-TDNN language classifier (60 mel bins, 256-dimensional embedding); training data VoxLingua107; label lineage video-metadata language labels; volunteer-validated development set; correlated with the generator's lab: no.
- Correlation: Its card reports a 6.7% development error and weaker accented and female speech; Aiden speaking French and the Vivian and Ono Anna fixtures are mandatory negatives (audit section 4.2).
- Sources: <https://huggingface.co/speechbrain/lang-id-voxlingua107-ecapa>, <https://bark.phon.ioc.ee/voxlingua107/>

## Pins

- `speechbrain/lang-id-voxlingua107-ecapa` at revision `0253049ae131d6a4be1c4f0d8b0ff483a0f8c8e9`.
- Digest status: `content-addressed-snapshot`.
- Verification: scripts/acquire_audio_qc_judges.py fetches exactly these files at the pinned revision into the owned model root, refusing any size or digest mismatch; before every load the worker verifies the snapshot directory holds exactly these files, each matching its pin (verify_judge_snapshot), and refuses an excluded runtime package. Nothing is downloaded at load time.
- Runtime: numpy 2.4.6, speechbrain 1.1.1, torch 2.11.0, torchaudio 2.11.0.
- `filesSource`: The Hugging Face tree metadata of the pinned revision (read 2026-09-26, no download): the LFS SHA-256 of each large file and the git blob ID of every other file, with its size. Every file of the revision is pinned and fetched.

| File | Bytes | Digest |
|---|---|---|
| `.gitattributes` | 1223 | git blob `feb65239285b042c` |
| `README.md` | 9538 | git blob `a40a50dc26b99cbc` |
| `classifier.ckpt` | 762555 | LFS SHA-256 `a50d9024ff58d317` |
| `config.json` | 51 | git blob `6fad8e826fd68080` |
| `embedding_model.ckpt` | 84474355 | LFS SHA-256 `ab750d5c06d71347` |
| `hyperparams.yaml` | 1519 | SHA-256 `88fec9791a8416a1` |
| `label_encoder.txt` | 2204 | git blob `addb319892122ba2` |
| `normalizer.ckpt` | 1063 | LFS SHA-256 `c369e01dfa2e0d84` |
| `udhr_th.wav` | 1146684 | LFS SHA-256 `5bdc3a0a686eed58` |

## Execution

- Stage 2; lane cpu; engine speechbrain-lid; device cpu; threads 2 (provisional); batch size 1; orchestrated; worker `scripts/audio_qc_worker.py`.
- Thread control: environment
- Decode options: pretrainedPath="the verified snapshot (overrides the card's Hub path)", labelSet="label_encoder.txt (107 languages; he appears as iw, jv as jw)"
- Acquisition: directory="lang-id-voxlingua107-ecapa", stage=1, runtime="speechbrain-torch"
- Resources: canonical-host peak 1.33 GiB; admission ceiling 1.60 GiB (calibrated), measured in session 20260927-70e86ea6; policy: measured canonical-host peak x 1.2 (AQ-06).
- Ceiling basis: Audit section 3.4 CPU-lane estimate (0.4-0.7 GB resident, section 4.2); provisional until two clean M6 runs measure its peak.
- `ceilingHistory`: [{"canonicalHostPeakBytes": 1418313728, "ceilingBytes": 1701976474, "ceilingSession": "20260927-aaba14fd", "date": "2026-09-27"}]
- Output identity: repository, revision, snapshotFileDigests, runtimeDependenciesDigest, runtimeVersions, workerSourceSHA256, engine, decodeOptions, labelSet, preprocessing, hostProfile, threads. Envelope identity: resourceSupervisorSHA256, probeAlgorithmVersion, supervisorOptions.
<!-- END GENERATED audio-qc-docs:facts -->

<!-- BEGIN GENERATED audio-qc-docs:accuracy (scripts/audio_qc_docs.py regen; edit its sources, not this block) -->
## Canary and accuracy

- Canary record: [benchmarks/audio-qc-qualification/20260927-aaba14fd/judges/lid.voxlingua107-ecapa-v1.json](../../../../benchmarks/audio-qc-qualification/20260927-aaba14fd/judges/lid.voxlingua107-ecapa-v1.json) (2026-09-27), output identity `587770eaaebb9e9d`.
- Canary qualification passed: yes; determinism D0 over 28 rows (28 bit-exact, 0 discrete mismatches); peak 1.32 GiB on mac-mini-m6-16gb (session 20260927-aaba14fd).

Its accuracy is claimed only through the detectors that consume it:

| Detector | Class | Languages | Reads | Qualification |
|---|---|---|---|---|
| [`language.consensus-lid@1`](../detectors/language.consensus-lid-v1.md) | D (language) | chinese, english, french, german, italian, japanese, korean, portuguese, russian, spanish | panel `expectedPosterior` | qualified (warn) |
| [`language.nativeness@1`](../detectors/language.nativeness-v1.md) | D (language) | chinese, english, french, german, italian, japanese, korean, portuguese, russian, spanish | panel `expectedPosterior` | not qualified |
<!-- END GENERATED audio-qc-docs:accuracy -->

## See also

- [Judge panel acquisition](../../audio-qc-engineering.md#judge-panel-acquisition-aq-06-prepared-2026-09-26) and [panel jobs and qualification](../../audio-qc-engineering.md#panel-jobs-and-qualification-aq-06-p8-tooling-2026-09-27): how a panel judge is fetched, run under admission and canaried.
