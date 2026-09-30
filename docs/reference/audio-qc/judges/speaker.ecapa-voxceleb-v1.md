# `speaker.ecapa-voxceleb@1`

<!-- BEGIN GENERATED audio-qc-docs:facts (scripts/audio_qc_docs.py regen; edit its sources, not this block) -->
Registry entry `speaker.ecapa-voxceleb@1` in [config/audio-qc-judges.json](../../../../config/audio-qc-judges.json).

**Measures.** Clone identity cosine (clone fidelity lane, reference-bank selection, long-form carry-over probe); advisory bands, uncalibrated.

| Status | Calibration | Kind | Family | Votes | Ships | Stage | Determinism |
|---|---|---|---|---|---|---|---|
| `advisory` | legacy-unqualified | neural | speaker-ecapa | no | no | 2 (cpu) | unmeasured |

`advisory`: Reported beside verdicts; never gates.

**Planned retirement.**

- `item`: AQ-07
- `status`: deferred
- `reason`: Shadow for one cycle, then retired once the CAM++ and ResNet293 families qualify (audit section 4.3).

## Provenance

- License tier **B** (scraped-web-audio): Permissive weights, but training data includes scraped web audio or corpora whose rights stay with the original owners, with no explicit non-commercial term. Internal, never-shipped evaluation only (decision 2a). Commercial use compatible: yes.
- Weights: Apache-2.0
- Code: Apache-2.0 (SpeechBrain)
- Training data: VoxCeleb 1 and 2: YouTube-derived celebrity speech; copyright stays with the owners; no explicit non-commercial term on the audio
- Tier-B acceptance: decision 2a (2026-09-25), scope `internal-never-shipped-evaluation`.
- Independence: vendor SpeechBrain; architecture ECAPA-TDNN; training data VoxCeleb; label lineage speaker identity labels; correlated with the generator's lab: no.
- Sources: <https://huggingface.co/speechbrain/spkrec-ecapa-voxceleb>, <https://www.robots.ox.ac.uk/~vgg/data/voxceleb/>

## Pins

- `speechbrain/spkrec-ecapa-voxceleb` at revision `0f99f2d0ebe89ac095bcc5903c4dd8f72b367286`.
- Digest status: `content-addressed-snapshot`.
- Verification: Loaded from the local Hugging Face cache only (the complete snapshot of `hf download speechbrain/spkrec-ecapa-voxceleb --revision <revision>`). Before each load the snapshot directory must be the pinned revision and hold exactly these files, each matching its pin; an unpinned, missing or altered file refuses. The similarity report records every verified file's SHA-256.
- Runtime: numpy recorded-at-load, speechbrain recorded-at-load, torch recorded-at-load.
- `filesSource`: The Hugging Face tree metadata of the pinned revision (read 2026-09-25, no download): the LFS SHA-256 of each large file and the git blob ID of every other file.

| File | Bytes | Digest |
|---|---|---|
| `.gitattributes` | 858 | git blob `c79d72cc1197b4b3` |
| `README.md` | 5377 | git blob `6023cecccb30eba7` |
| `classifier.ckpt` | 5534328 | LFS SHA-256 `fd9e3634fe68bd0a` |
| `config.json` | 51 | git blob `2e8b3b4d97ae58d7` |
| `embedding_model.ckpt` | 83316686 | LFS SHA-256 `0575cb64845e6b9a` |
| `example1.wav` | 104390 | git blob `2d5abbd526328179` |
| `example2.flac` | 39589 | git blob `a38e3061f91ba51b` |
| `hyperparams.yaml` | 1919 | git blob `70e4cd0beb74ca08` |
| `label_encoder.txt` | 128619 | git blob `72c6fa7b170cbfd1` |
| `mean_var_norm_emb.ckpt` | 1921 | git blob `1978c5e7f20d5ffd` |

## Execution

- Stage 2; lane cpu; not orchestrated.
- Note: Runs in-process and unsupervised in clone_speaker_similarity.py (the clone lane); it joins the orchestrator as a CPU worker once AQ-06 measures its ceiling.
- Resources: canonical-host peak -; admission ceiling - (provisional); policy: measured canonical-host peak x 1.2 (AQ-06).
- Ceiling basis: Unsupervised in-process CPU scorer today; about 0.4-0.6 GB (audit estimate).
- Output identity: repository, revision, snapshotFileDigests, runtimeVersions, preprocessing, hostProfile. Envelope identity: -.
- Legacy identifiers: sources: scripts/clone_speaker_similarity.py; reportFields: speakerSimilarity, identityCosine.
<!-- END GENERATED audio-qc-docs:facts -->

<!-- BEGIN GENERATED audio-qc-docs:accuracy (scripts/audio_qc_docs.py regen; edit its sources, not this block) -->
## Canary and accuracy

- No canary record.

**UNQUALIFIED.** No registered detector consumes this judge, so no accuracy is claimed for it.
<!-- END GENERATED audio-qc-docs:accuracy -->

## See also

- [Benchmarking procedure](../../benchmarking-procedure.md): the clone fidelity lane and how its identity bands are calibrated.
