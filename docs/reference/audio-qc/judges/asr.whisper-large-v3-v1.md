# `asr.whisper-large-v3@1`

<!-- BEGIN GENERATED audio-qc-docs:facts (scripts/audio_qc_docs.py regen; edit its sources, not this block) -->
Registry entry `asr.whisper-large-v3@1` in [config/audio-qc-judges.json](../../../../config/audio-qc-judges.json).

**Measures.** Content voter for en, de, fr, es, it, pt, ru, ja and ko and secondary voter for zh (audit section 4.1): a language-locked full-file transcript, plus audio language identification from the same process (language-ID vote 2, section 4.2), after the generator exits. Succeeds asr.whisper-small@1 only after the dual run records every flip (audit section 7.1).

| Status | Calibration | Kind | Family | Votes | Ships | Stage | Determinism |
|---|---|---|---|---|---|---|---|
| `shadow` | legacy-unqualified | neural | whisper | yes | no | 2 (gpu) | D0 (expected D1) |

`shadow`: Runs beside the current judges; its verdicts are uncalibrated and never block.

**Languages.** voter: en, de, fr, es, it, pt, ru, ja, ko; secondary: zh.

**Audit section.** 4.1, 4.2.

## Provenance

- License tier **B** (scraped-web-audio): Permissive weights, but training data includes scraped web audio or corpora whose rights stay with the original owners, with no explicit non-commercial term. Internal, never-shipped evaluation only (decision 2a). Commercial use compatible: yes.
- Weights: MIT (OpenAI Whisper release and the mlx-community conversion card)
- Code: MIT (mlx-whisper)
- Training data: Whisper large-v3: about 1 million hours of weakly labeled and 4 million hours of Whisper large-v2 pseudo-labeled web audio (OpenAI model card); rights stay with the original owners; no explicit non-commercial term
- Tier-B acceptance: decision 2a (2026-09-25), scope `internal-never-shipped-evaluation`.
- Independence: vendor OpenAI (weights); mlx-community (conversion); architecture encoder-decoder transformer, 1.55B parameters, 128 mel bins, fp16; training data Whisper web audio; label lineage weakly supervised web transcripts and Whisper large-v2 pseudo-labels; correlated with the generator's lab: no.
- Correlation: The same family as asr.whisper-small@1, so the two never count as two families. Parakeet's training labels include Whisper pseudo-labels (Granary), so the pair's error correlation is audited before any consensus gates (AQ-F35).
- Sources: <https://huggingface.co/mlx-community/whisper-large-v3-mlx>, <https://huggingface.co/openai/whisper-large-v3>, <https://github.com/openai/whisper>

## Pins

- `mlx-community/whisper-large-v3-mlx` at revision `49e6aa286ad60c14352c404340ded53710378a11`.
- Digest status: `content-addressed-snapshot`.
- Verification: scripts/acquire_audio_qc_judges.py fetches exactly these files at the pinned revision into the owned model root, refusing any size or digest mismatch; before every load the worker verifies the snapshot directory holds exactly these files, each matching its pin (verify_judge_snapshot), and refuses an excluded runtime package. Nothing is downloaded at load time.
- Runtime: mlx 0.32.0, mlx-whisper 0.4.3, numpy 2.4.6, torch 2.11.0.
- `filesSource`: The Hugging Face tree metadata of the pinned revision (read 2026-09-26, no download): the LFS SHA-256 of each large file and the git blob ID of every other file, with its size. Every file of the revision is pinned and fetched.

| File | Bytes | Digest |
|---|---|---|
| `.gitattributes` | 1519 | git blob `a6344aac8c09253b` |
| `README.md` | 283 | git blob `aa6058f979bed0dc` |
| `config.json` | 269 | git blob `2c626df3c540bdc0` |
| `weights.npz` | 3083520416 | LFS SHA-256 `05ff791ce3630fae` |

## Execution

- Stage 2; lane gpu; engine whisper-mlx; device mlx-gpu; threads 2 (provisional); batch size 1; orchestrated; worker `scripts/audio_qc_worker.py`.
- Thread control: environment
- Decode options: temperature=0.0, conditionOnPreviousText=false, fp16=true, wordTimestamps=false, initialPrompt=null, noSpeechThreshold=null, languageLock="expected-language", languageDetection="first-30-seconds-mel-argmax"
- Acquisition: directory="whisper-large-v3-mlx", stage=1, runtime="whisper-mlx"
- Resources: canonical-host peak 5.70 GiB; admission ceiling 6.84 GiB (calibrated), measured in session 20260927-aaba14fd; policy: measured canonical-host peak x 1.2 (AQ-06).
- Ceiling basis: Audit section 3.4 GPU-lane estimate (about 4-4.5 GB resident, section 4.1); provisional until two clean M6 runs measure its peak.
- Output identity: repository, revision, snapshotFileDigests, runtimeDependenciesDigest, runtimeVersions, workerSourceSHA256, engine, decodeOptions, lockedLanguage, preprocessing, hostProfile, threads. Envelope identity: resourceSupervisorSHA256, probeAlgorithmVersion, supervisorOptions.
<!-- END GENERATED audio-qc-docs:facts -->

<!-- BEGIN GENERATED audio-qc-docs:accuracy (scripts/audio_qc_docs.py regen; edit its sources, not this block) -->
## Canary and accuracy

- Canary record: [benchmarks/audio-qc-qualification/20260927-aaba14fd/judges/asr.whisper-large-v3-v1.json](../../../../benchmarks/audio-qc-qualification/20260927-aaba14fd/judges/asr.whisper-large-v3-v1.json) (2026-09-27), output identity `815045ab8a6a740b`.
- Canary qualification passed: yes; determinism D0 over 28 rows (28 bit-exact, 0 discrete mismatches); peak 5.70 GiB on mac-mini-m6-16gb (session 20260927-aaba14fd).

Its accuracy is claimed only through the detectors that consume it:

| Detector | Class | Languages | Reads | Qualification |
|---|---|---|---|---|
| [`content.consensus-error@1`](../detectors/content.consensus-error-v1.md) | B (content) | english, french, german, italian, portuguese, russian, spanish, chinese, japanese, korean | panel `errorRate` | not qualified |
| [`boundary.truncation@1`](../detectors/boundary.truncation-v1.md) | C (boundary) | english, french, german, italian, portuguese, russian, spanish, chinese, japanese, korean | transcript-tail `trailingUnmatchedFraction` | not qualified |
| [`boundary.run-on@1`](../detectors/boundary.run-on-v1.md) | C (boundary) | english, french, german, italian, portuguese, russian, spanish, chinese, japanese | panel `lastSegmentEndSeconds`, must complete | not qualified |
| [`language.consensus-lid@1`](../detectors/language.consensus-lid-v1.md) | D (language) | chinese, english, french, german, italian, japanese, korean, portuguese, russian, spanish | panel `expectedLanguageProbability` | not qualified |

**UNQUALIFIED.** No committed calibration record qualifies a detector that consumes this judge, so every verdict built on it composes as `uncalibrated`.
<!-- END GENERATED audio-qc-docs:accuracy -->

## See also

- [Judge panel acquisition](../../audio-qc-engineering.md#judge-panel-acquisition-aq-06-prepared-2026-09-26) and [panel jobs and qualification](../../audio-qc-engineering.md#panel-jobs-and-qualification-aq-06-p8-tooling-2026-09-27): how a panel judge is fetched, run under admission and canaried.
