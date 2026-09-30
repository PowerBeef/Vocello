# Audio QC corpora

<!-- BEGIN GENERATED audio-qc-docs:corpora-summary (scripts/audio_qc_docs.py regen; edit its sources, not this block) -->
Rendered from [config/audio-qc-corpora.json](../../../config/audio-qc-corpora.json) (`AQ-07`): Fixture corpora: one Hub mirror and one Zenodo archive.

**Decisions.**

- Fixture decision: the lean set only.

**Groups.** A shared source is counted in its own group only.

| Group | Class | Title | Sources | Files | Download | Extracted (estimate) |
|---|---|---|---|---|---|---|
| `fleurs-train` | N1 | FLEURS train reserve | - | 0 | 0.00 GB | 0.00 GB |
| `speaker` | E | Speaker-labelled speech | hub-mirror | 1 | 1.50 GB | 3.00 GB |
| `emotion` | H | Acted emotion | emo-archive, hub-mirror (shared) | 1 | 0.01 GB | 0.02 GB |
| `accent` | D | Accented English | - | 0 | 0.00 GB | 0.00 GB |

- `fleurs-train`: Fixture reserve cohorts.
- `speaker`: Fixture speaker-labelled speech.
- `emotion`: Fixture acted emotion.
- `accent`: Fixture accented speech.

**Totals.** 2 files, 1.51 GB to download; about 3.02 GB of mono PCM16 WAV once extracted (estimates; each extraction checks its own need first).
Set `lean`: `fleurs-train`, `speaker`, `emotion`, `accent`. Every group.

**Hosts.** https only, on `huggingface.co`, `*.hf.co`, `*.huggingface.co`, `media.githubusercontent.com`, `zenodo.org`.

**Parquet runtime.** `corpora-parquet`: [config/audio-qc-runtimes/corpora-parquet.txt](../../../config/audio-qc-runtimes/corpora-parquet.txt), 6 packages, about 0.05 GB of wheels, import probe `pyarrow.parquet`, `soundfile`. Fixture runtime.
<!-- END GENERATED audio-qc-docs:corpora-summary -->

<!-- BEGIN GENERATED audio-qc-docs:corpora-sources (scripts/audio_qc_docs.py regen; edit its sources, not this block) -->
| Source | Group | Host | Languages | Labels | License | Files | Download |
|---|---|---|---|---|---|---|---|
| `hub-mirror` | `speaker` (+ emotion) | huggingface.co | english | speaker | CC-BY-4.0 | 1 | 1.50 GB |
| `emo-archive` | `emotion` | zenodo.org | german | emotion, speaker | CC-BY-4.0 | 1 | 0.01 GB |

### Fixture Hub mirror (`hub-mirror`)

- Pinned: `owner/corpus` at `0123456789ab` on `huggingface.co`; 1 file (1 by LFS SHA-256), 1.50 GB.
- License: CC-BY-4.0 ([text](https://creativecommons.org/licenses/by/4.0/); official source <https://example.org/corpus>).
- License note: Fixture note.
- Attribution: Fixture Hub mirror, attributed to its fixture authors under CC BY 4.0.
- Labels: speaker (speaker_id column); absent: accent, emotion, gender, pronunciationScores, text.
- Extraction: `parquet`; written at 16000 Hz; about 3.00 GB (fixture estimate).
- Caveat: An unofficial mirror.
- Caveat: No gender.

### Fixture emotion archive (`emo-archive`)

- Pinned: Zenodo record 1, version 1.0 on `zenodo.org`; 1 file (1 by Zenodo MD5), 0.01 GB.
- License: CC-BY-4.0 ([text](https://creativecommons.org/licenses/by/4.0/); official source <https://zenodo.org/records/1>).
- Attribution: Fixture emotion archive, attributed to its fixture authors under CC BY 4.0.
- Labels: emotion (file name), speaker (file name); absent: accent, gender, pronunciationScores, text.
- Extraction: `zip`; written at 24000 Hz; about 0.02 GB (fixture estimate).
- Caveat: Pinned by Zenodo's MD5 and size.
<!-- END GENERATED audio-qc-docs:corpora-sources -->
