---
status: active
owner: backend-mlx
reviewed: 2026-09-29
summary: The pinned corpora of the next audio QC qualification round (AQ-07) - groups, sources, pins, licenses, attributions, labels and caveats - rendered from config/audio-qc-corpora.json.
sourceOfTruth:
  - config/audio-qc-corpora.json
  - config/audio-qc-corpora/
  - config/audio-qc-runtimes/corpora-parquet.txt
  - scripts/audio_qc_corpora.py
  - scripts/audio_qc_corpora_worker.py
---
# Audio QC corpora

The corpora the next qualification round reads, beside the FLEURS dev and test N1 cohorts of
`config/audio-qc-n1-sources.json`. The registry is the authority and this page renders it; the
commands, the receipts and the extraction rules are in
[audio-qc-engineering.md](../audio-qc-engineering.md#corpora-for-the-next-qualification-round). No
corpus audio, transcript or manifest is ever committed.

<!-- BEGIN GENERATED audio-qc-docs:corpora-summary (scripts/audio_qc_docs.py regen; edit its sources, not this block) -->
Rendered from [config/audio-qc-corpora.json](../../../config/audio-qc-corpora.json) (`AQ-07`): The pinned corpora of the next audio QC qualification round (audit sections 5.3 and 5.7): FLEURS train reserve cohorts for N1 and N2, speaker-labelled speech for class E, acted emotion for class H and accented English for class D. Only pins, licenses and attributions are committed; scripts/audio_qc_corpora.py fetches, verifies and extracts into the untracked build/cache/audio-qc-corpora.

**Decisions.**

- 2026-09-29, maintainer: the lean set (about 29 GB to download).
- Multilingual LibriSpeech is used for anonymous same/different-speaker trials only, never speaker identification.
- A Zenodo source is pinned by the publisher's MD5 and exact size; its SHA-256 is recorded in the fetch receipt on the first verified fetch and binds every later run.
- An unofficial Hugging Face mirror is accepted pinned by revision and LFS SHA-256; its license is cited from the corpus's official source.
- Scope gaps: class E has no acceptable source for Japanese or Russian; class H has none for French, Chinese or Korean, and Spanish is weak and not pinned.

**Groups.** A shared source is counted in its own group only.

| Group | Class | Title | Sources | Files | Download | Extracted (estimate) |
|---|---|---|---|---|---|---|
| `fleurs-train` | N1 | FLEURS train reserve | fleurs-train | 20 | 15.58 GB | 5.38 GB |
| `speaker` | E | Speaker-labelled speech | aishell3-subset, crema-d, emozionalmente, libritts-r, mls, zeroth-korean | 8999 | 9.66 GB | 26.53 GB |
| `emotion` | H | Acted emotion | emodb, emouerj, jvnv, resd, thorsten-emotional, crema-d (shared), emozionalmente (shared) | 10 | 3.09 GB | 1.71 GB |
| `accent` | D | Accented English | speechocean762 | 2 | 0.64 GB | 0.64 GB |

- `fleurs-train`: New, never-scored N1 reserve cohorts from FLEURS train, for N1 and its N2 resynthesis; dev and test stay in config/audio-qc-n1-sources.json.
- `speaker`: Class E identity: same- and different-speaker trials and splice shams.
- `emotion`: Class H delivery: actor-labelled emotion; CREMA-D and Emozionalmente come from the speaker group.
- `accent`: Class D language: non-native English with expert pronunciation scores, as accented negatives.

**Totals.** 9031 files, 28.96 GB to download; about 34.25 GB of mono PCM16 WAV once extracted (estimates; each extraction checks its own need first).
Set `lean`: `fleurs-train`, `speaker`, `emotion`, `accent`. Every group: about 29 GB to download.

**Hosts.** https only, on `huggingface.co`, `*.hf.co`, `*.huggingface.co`, `media.githubusercontent.com`, `zenodo.org`.

**Parquet runtime.** `corpora-parquet`: [config/audio-qc-runtimes/corpora-parquet.txt](../../../config/audio-qc-runtimes/corpora-parquet.txt), 6 packages, about 0.05 GB of wheels, import probe `pyarrow.parquet`, `soundfile`, `numpy`. Not a judge runtime: built by scripts/audio_qc_corpora.py runtime with the judge acquisition's interpreter and venv builder, under the same model root.
<!-- END GENERATED audio-qc-docs:corpora-summary -->

<!-- BEGIN GENERATED audio-qc-docs:corpora-sources (scripts/audio_qc_docs.py regen; edit its sources, not this block) -->
| Source | Group | Host | Languages | Labels | License | Files | Download |
|---|---|---|---|---|---|---|---|
| `fleurs-train` | `fleurs-train` | huggingface.co | english, french, german, spanish, italian, portuguese, russian, chinese, japanese, korean | gender, text | CC-BY-4.0 | 20 | 15.58 GB |
| `aishell3-subset` | `speaker` | huggingface.co | chinese | accent, gender, speaker, text | Apache-2.0 | 1522 | 0.46 GB |
| `crema-d` | `speaker` (+ emotion) | media.githubusercontent.com | english | emotion, speaker | ODbL-1.0 AND DbCL-1.0 | 7442 | 0.61 GB |
| `emozionalmente` | `speaker` (+ emotion) | zenodo.org | italian | emotion, gender, speaker, text | CC-BY-4.0 | 1 | 0.56 GB |
| `libritts-r` | `speaker` | huggingface.co | english | speaker, text | CC-BY-4.0 | 7 | 3.01 GB |
| `mls` | `speaker` | huggingface.co | german, french, spanish, italian, portuguese | speaker, text | CC-BY-4.0 | 20 | 2.14 GB |
| `zeroth-korean` | `speaker` | huggingface.co | korean | speaker, text | CC-BY-4.0 | 7 | 2.88 GB |
| `emodb` | `emotion` | zenodo.org | german | emotion, gender, speaker | CC-BY-4.0 | 1 | 0.04 GB |
| `emouerj` | `emotion` | zenodo.org | portuguese | emotion, gender, speaker | CC-BY-4.0 | 1 | 0.11 GB |
| `jvnv` | `emotion` | huggingface.co | japanese | emotion, gender, speaker | CC-BY-SA-4.0 | 5 | 2.06 GB |
| `resd` | `emotion` | huggingface.co | russian | emotion | MIT | 2 | 0.49 GB |
| `thorsten-emotional` | `emotion` | zenodo.org | german | emotion, gender, speaker, text | CC0-1.0 | 1 | 0.40 GB |
| `speechocean762` | `accent` | huggingface.co | english | accent, gender, pronunciationScores, speaker, text | CC-BY-4.0 | 2 | 0.64 GB |

### FLEURS train (N1 reserve cohorts) (`fleurs-train`)

- Pinned: `google/fleurs` at `70bb2e84b976` on `huggingface.co`; 20 files (10 by git blob SHA-1, 10 by LFS SHA-256), 15.58 GB.
- License: CC-BY-4.0 ([text](https://creativecommons.org/licenses/by/4.0/); official source <https://huggingface.co/datasets/google/fleurs>).
- Attribution: FLEURS (Few-shot Learning Evaluation of Universal Representations of Speech; Conneau et al., 2022, arXiv:2205.12446), released by Google as the Hugging Face dataset google/fleurs under the Creative Commons Attribution 4.0 International license (CC BY 4.0). Vocello's audio QC tooling downloads the pinned files into an untracked local cache for detector qualification; no FLEURS audio or transcript is redistributed or committed.
- Labels: gender (TSV gender column), text (TSV raw transcription); absent: accent, emotion, pronunciationScores, speaker.
- Extraction: `fleurs-reserve`; written at 16000 Hz; about 5.38 GB (3 cohorts x 400 recordings x 10 languages at about 14 s of 16 kHz PCM16 each; extract computes the exact need from the TSV sample counts before it writes); 3 cohorts of 400 recordings per language, seed `aq07-fleurs-train-reserve-v1`.
- Caveat: FLEURS publishes no speaker ids (the N1 limitation fleurs-no-speaker-ids): speaker disjointness between the reserve cohorts and dev or test cannot be verified.
- Caveat: The reserve cohorts are new and never scored; they stay held back until a qualification round needs a fresh cohort.
- Caveat: Recordings are 32-bit float WAVs converted to PCM16 by the N1 extractor (audio_qc_n1_corpus decode_wav).

### AISHELL-3 (test subset) (`aishell3-subset`)

- Pinned: `shenyunhang/AISHELL-3` at `e1af0fa23933` on `huggingface.co`; 1522 files (2 by git blob SHA-1, 1520 by LFS SHA-256), 0.46 GB.
- Pin file: [config/audio-qc-corpora/aishell3-test-subset.tsv](../../../config/audio-qc-corpora/aishell3-test-subset.tsv) (SHA-256 `34a1cfff30086848`).
- License: Apache-2.0 ([text](https://www.apache.org/licenses/LICENSE-2.0); official source <https://www.openslr.org/93/>).
- Attribution: AISHELL-3 (Shi et al., 2021, Interspeech), provided by Beijing Shell Shell Technology Co., Ltd., OpenSLR 93, under the Apache License 2.0; read here from the Hugging Face mirror shenyunhang/AISHELL-3. No audio or transcript is redistributed or committed.
- Labels: accent (spk-info.txt regional accent), gender (spk-info.txt), speaker (speaker directory), text (test/content.txt); absent: emotion, pronunciationScores.
- Extraction: `wav-files`; written at 24000 Hz; about 0.25 GB (the pinned WAV bytes (44.1 kHz PCM16) scaled to 24 kHz).
- Subset: Speakers of the pinned revision's test/wav with at least minimumFiles WAVs (76 of 214), each contributing the perSpeaker WAVs of lowest SHA-256(seed NUL path); resolved from the Hub tree listing by `audio_qc_corpora.py resolve-subset` into the pin file. Seed `aq07-aishell3-test-subset-v1`.
- Caveat: An unofficial Hugging Face mirror, pinned by revision and each WAV's LFS SHA-256 (maintainer decision).
- Caveat: A subset of the test split by the seeded rule in subset: 76 speakers with at least 100 utterances, 20 utterances each (about 0.44 GB).
- Caveat: 44.1 kHz audio, resampled to 24 kHz; the transcripts interleave characters and pinyin, and text keeps the characters.

### CREMA-D (`crema-d`)

- Pinned: `CheyneyComputerScience/CREMA-D` at `1658cd342dff` on `media.githubusercontent.com`; 7442 files (7442 by LFS SHA-256), 0.61 GB.
- Pin file: [config/audio-qc-corpora/crema-d.tsv](../../../config/audio-qc-corpora/crema-d.tsv) (SHA-256 `76292ac0f82c1b0c`).
- License: ODbL-1.0 AND DbCL-1.0 ([text](https://opendatacommons.org/licenses/odbl/1-0/); official source <https://github.com/CheyneyComputerScience/CREMA-D/blob/1658cd342dff90010aa843eaeebd53610a08b1dc/LICENSE.txt>).
- License note: The database is under the Open Database License 1.0 and its contents under the Database Contents License 1.0 (https://opendatacommons.org/licenses/dbcl/1-0/); a derived database shared publicly stays under the ODbL.
- Attribution: CREMA-D, the Crowd-sourced Emotional Multimodal Actors Dataset (Cao et al., 2014, IEEE Transactions on Affective Computing 5(4)), by Cheyney University of Pennsylvania and the CREMA-D contributors, under the Open Database License 1.0 with contents under the Database Contents License 1.0. Vocello's audio QC tooling downloads the pinned WAVs into an untracked local cache; no CREMA-D audio or label is redistributed or committed.
- Labels: emotion (acted emotion and intensity (file name)), speaker (actor id (file name)); absent: accent, gender, pronunciationScores, text.
- Extraction: `wav-files`; written at 16000 Hz; about 0.61 GB (the pinned WAV bytes (16 kHz mono PCM16, kept as they are)).
- Caveat: 91 actors reading 12 fixed sentences in six acted emotions; the intensity level XX is unspecified.
- Caveat: Gender and other demographics are in VideoDemographics.csv, a plain git file that media.githubusercontent.com does not serve (it serves LFS content only); it is not fetched, so the clips carry no gender.
- Caveat: The sentence text is not extracted: each clip carries its sentence code (textID) only.

### Emozionalmente (`emozionalmente`)

- Pinned: Zenodo record 12616095, version 1.1 on `zenodo.org`; 1 file (1 by Zenodo MD5), 0.56 GB.
- License: CC-BY-4.0 ([text](https://creativecommons.org/licenses/by/4.0/); official source <https://zenodo.org/records/12616095>).
- Attribution: Emozionalmente: a crowdsourced corpus of simulated emotional speech in Italian (F. Catania, J. W. Wilke and F. Garzotto, IEEE Transactions on Audio, Speech and Language Processing 33, 2025, doi:10.1109/TASLPRO.2025.3540662), Zenodo record 12616095 version 1.1, under the Creative Commons Attribution 4.0 International license (CC BY 4.0). No audio or label is redistributed or committed.
- Labels: emotion (metadata/samples.csv emotion_expressed), gender (metadata/users.csv), speaker (metadata/samples.csv actor), text (metadata/samples.csv sentence); absent: accent, pronunciationScores.
- Extraction: `zip`; written at 16000 Hz; about 0.84 GB (6,902 clips of 3.81 s on average (the Zenodo record) of 16 kHz PCM16).
- Caveat: 431 amateur actors recorded on non-professional equipment; each clip's emotion is the actor's intended emotion, not a perceived one.
- Caveat: Pinned by Zenodo's MD5 and size; the SHA-256 is recorded on the first verified fetch.
- Caveat: The archive carries macOS __MACOSX entries, which are ignored.

### LibriTTS-R (dev.clean and test.clean) (`libritts-r`)

- Pinned: `mythicinfinity/libritts_r` at `0d1718db3512` on `huggingface.co`; 7 files (7 by LFS SHA-256), 3.01 GB.
- License: CC-BY-4.0 ([text](https://creativecommons.org/licenses/by/4.0/); official source <https://www.openslr.org/141/>).
- Attribution: LibriTTS-R (Koizumi et al., 2023, arXiv:2305.18802), the sound-quality-restored LibriTTS corpus (Zen et al., 2019) derived from LibriSpeech and LibriVox, OpenSLR 141, under the Creative Commons Attribution 4.0 International license (CC BY 4.0); read here from the Hugging Face dataset mythicinfinity/libritts_r. No audio or transcript is redistributed or committed.
- Labels: speaker (speaker_id column), text (text_original column); absent: accent, emotion, gender, pronunciationScores.
- Extraction: `parquet`; written at 24000 Hz; about 3.02 GB (62,877 s (datasets-server duration statistics of dev.clean and test.clean) of 24 kHz PCM16).
- Caveat: The audio is restored by a speech restoration model (Miipher), not a raw recording: unsuitable as a class A or G signal-quality negative.
- Caveat: This mirror carries no speaker gender (LibriTTS's SPEAKERS.txt is not in it).
- Caveat: dev.clean holds 40 speakers and test.clean 39; audio is 24 kHz.

### Multilingual LibriSpeech (de, fr, es, it, pt: dev, test, 9_hours, 1_hours) (`mls`)

- Pinned: `facebook/multilingual_librispeech` at `2e83e61823b4` on `huggingface.co`; 20 files (20 by LFS SHA-256), 2.14 GB.
- License: CC-BY-4.0 ([text](https://creativecommons.org/licenses/by/4.0/); official source <https://www.openslr.org/94/>).
- Attribution: Multilingual LibriSpeech (Pratap et al., 2020, arXiv:2012.03411), derived from LibriVox audiobooks, OpenSLR 94, under the Creative Commons Attribution 4.0 International license (CC BY 4.0); read here from the Hugging Face dataset facebook/multilingual_librispeech. No audio or transcript is redistributed or committed.
- Labels: speaker (speaker_id column), text (transcript column); absent: accent, emotion, gender, pronunciationScores.
- Extraction: `parquet`; written at 16000 Hz; about 15.73 GB (491,408 s (datasets-server duration statistics of the 20 splits) of 16 kHz PCM16).
- Caveat: Maintainer decision: anonymous same/different-speaker trials only, never speaker identification.
- Caveat: Portuguese mixes pt-PT and pt-BR speakers without a label; it has 46 speakers, 38 with at least 20 utterances.
- Caveat: The audio is cut from LibriVox 64 kbps MP3 audiobooks (the original_path column) and stored compressed in this mirror (about 35 kbps), so it carries lossy coding artifacts: not a class A or G negative.
- Caveat: 1_hours is a limited-supervision set overlapping 9_hours speakers; identical clips are written once and listed as duplicates.
- Caveat: This mirror carries no speaker gender.

### Zeroth-Korean (test and train) (`zeroth-korean`)

- Pinned: `kresnik/zeroth_korean` at `1fe937899f82` on `huggingface.co`; 7 files (7 by LFS SHA-256), 2.88 GB.
- License: CC-BY-4.0 ([text](https://creativecommons.org/licenses/by/4.0/); official source <https://www.openslr.org/40/>).
- Attribution: Zeroth-Korean, the Korean speech corpus of the Zeroth project (Lucas Jo, Wonkyum Lee and Atlas Guide), OpenSLR 40, under the Creative Commons Attribution 4.0 International license (CC BY 4.0); read here from the Hugging Face mirror kresnik/zeroth_korean. No audio or transcript is redistributed or committed.
- Labels: speaker (speaker_id column), text (text column); absent: accent, emotion, gender, pronunciationScores.
- Extraction: `parquet`; written at 16000 Hz; about 6.09 GB (190,334 s (datasets-server duration statistics) of 16 kHz PCM16).
- Caveat: An unofficial Hugging Face mirror, pinned by revision and LFS SHA-256 (maintainer decision).
- Caveat: test holds 10 speakers and train 105; this mirror carries no speaker gender.

### Berlin EmoDB (`emodb`)

- Pinned: Zenodo record 7447302, version 1.3.0 on `zenodo.org`; 1 file (1 by Zenodo MD5), 0.04 GB.
- License: CC-BY-4.0 ([text](https://creativecommons.org/licenses/by/4.0/); official source <https://zenodo.org/records/7447302>).
- Attribution: Berlin Database of Emotional Speech (EmoDB; Burkhardt, Paeschke, Kienast, Sendlmeier and Weiss, 2005, Interspeech), Zenodo record 7447302 version 1.3.0 (audformat), under the Creative Commons Attribution 4.0 International license (CC BY 4.0). No audio or label is redistributed or committed.
- Labels: emotion (emotion code (file name)), gender (db.speaker.csv), speaker (actor id (file name)); absent: accent, pronunciationScores, text.
- Extraction: `zip`; written at 16000 Hz; about 0.05 GB (the archive's 16 kHz PCM16 WAVs (about 40 MB) with a 25% margin).
- Caveat: 10 actors, 7 emotions, 535 utterances kept by a perception test (recognized by more than 80% of listeners and judged natural by more than 60%): prototypical acted emotion, not natural speech.
- Caveat: No transcript is extracted: each clip carries its sentence code (textID) only. Pinned by Zenodo's MD5 and size; the SHA-256 is recorded on the first verified fetch.

### emoUERJ (`emouerj`)

- Pinned: Zenodo record 5427549, version 1.0.0 on `zenodo.org`; 1 file (1 by Zenodo MD5), 0.11 GB.
- License: CC-BY-4.0 ([text](https://creativecommons.org/licenses/by/4.0/); official source <https://zenodo.org/records/5427549>).
- Attribution: emoUERJ: an emotional speech database in Portuguese (Bastos Germano, Pompeu Tcheou, da Rocha Henriques and Pinto Gomes Junior, State University of Rio de Janeiro), Zenodo record 5427549 version 1.0.0, under the Creative Commons Attribution 4.0 International license (CC BY 4.0). No audio or label is redistributed or committed.
- Labels: emotion (emotion code (file name)), gender (file name), speaker (actor id (file name)); absent: accent, pronunciationScores, text.
- Extraction: `zip`; written at 24000 Hz; about 0.20 GB (the archive's WAV bytes (the Zenodo preview listing), an upper bound once resampled to 24 kHz from a higher rate).
- Caveat: Brazilian Portuguese; 8 actors (4 women, 4 men), 377 clips in 4 emotions including neutral.
- Caveat: Actors chose freely among 10 sentences, so no clip carries its text. Pinned by Zenodo's MD5 and size; the SHA-256 is recorded on the first verified fetch.

### JVNV (`jvnv`)

- Pinned: `asahi417/jvnv-emotional-speech-corpus` at `3b6c3794754e` on `huggingface.co`; 5 files (5 by LFS SHA-256), 2.06 GB.
- License: CC-BY-SA-4.0 ([text](https://creativecommons.org/licenses/by-sa/4.0/); official source <https://sites.google.com/site/shinnosuketakamichi/research-topics/jvnv_corpus>).
- License note: The license is the official JVNV page's; the mirror's card states none.
- Attribution: JVNV, a Japanese emotional speech corpus with verbal content and nonverbal vocalizations (Xin, Jiang, Takamichi, Saito, Aizawa and Saruwatari, 2024, IEEE Access), under the Creative Commons Attribution-ShareAlike 4.0 International license (CC BY-SA 4.0); read here from the Hugging Face mirror asahi417/jvnv-emotional-speech-corpus. No audio is redistributed or committed.
- Labels: emotion (style column), gender (speaker id prefix (F or M)), speaker (speaker_id column); absent: accent, pronunciationScores, text.
- Extraction: `parquet`; written at 24000 Hz; about 0.68 GB (14,198 s (datasets-server duration statistics) of 24 kHz PCM16).
- Caveat: An unofficial Hugging Face mirror, pinned by revision and LFS SHA-256 (maintainer decision); share-alike license.
- Caveat: 4 speakers (F1, F2, M1, M2) in 6 emotions with no neutral style: no neutral baseline. Gender is derived from the speaker id's F or M.
- Caveat: Utterances embed nonverbal vocalizations by design; this mirror carries no transcript.
- Caveat: 48 kHz 24-bit audio, resampled to 24 kHz.

### RESD (Russian Emotional Speech Dialogs) (`resd`)

- Pinned: `Aniemore/resd` at `8db7068a7717` on `huggingface.co`; 2 files (2 by LFS SHA-256), 0.49 GB.
- License: MIT ([text](https://opensource.org/license/mit); official source <https://huggingface.co/datasets/Aniemore/resd>).
- License note: MIT is stated only on the Hugging Face dataset card; no other primary source states it.
- Attribution: RESD, the Russian Emotional Speech Dialogs dataset of the Aniemore project (Lubenets, Davidchuk, Amentes and others), the Hugging Face dataset Aniemore/resd, under the MIT license its card states. No audio is redistributed or committed.
- Labels: emotion (emotion column); absent: accent, gender, pronunciationScores, speaker, text.
- Extraction: `parquet`; written at 16000 Hz; about 0.27 GB (8,430 s (datasets-server duration statistics) of 16 kHz PCM16).
- Caveat: The license is stated only on the dataset card (recorded as a caveat).
- Caveat: No speaker id column: the clips carry no speaker, so RESD serves class H only, never class E.
- Caveat: Mixed 16 and 44.1 kHz audio, resampled to 16 kHz; enthusiasm has no canonical emotion.

### Thorsten-Voice 2021.06 emotional (v2) (`thorsten-emotional`)

- Pinned: Zenodo record 5525023, version 2.0 on `zenodo.org`; 1 file (1 by Zenodo MD5), 0.40 GB.
- License: CC0-1.0 ([text](https://creativecommons.org/publicdomain/zero/1.0/); official source <https://www.openslr.org/110/>).
- License note: OpenSLR 110 and the Zenodo record's description say CC0; the Zenodo record's license field says CC-BY-4.0. Both are recorded, and the attribution is given either way.
- Attribution: Thorsten-Voice Dataset 2021.06 emotional (Thorsten Müller, voice; Dominik Kreutz, audio optimization), Zenodo record 5525023 version 2.0 and OpenSLR 110, released under CC0 1.0. No audio or transcript is redistributed or committed.
- Labels: emotion (style directory), gender (one speaker (constant)), speaker (one speaker (constant)), text (thorsten-emotional-metadata.csv); absent: accent, pronunciationScores.
- Extraction: `tar.gz`; written at 24000 Hz; about 0.50 GB (about 175 minutes (the Zenodo record's per-style lengths) of 24 kHz PCM16).
- Caveat: Denoised, normalized to -24 dB and trimmed of leading and trailing silence (the end of a sentence may be cut off early): unsuitable as a class C boundary or silence negative.
- Caveat: One speaker, 300 sentences in 8 styles; drunk, sleepy and whisper have no canonical emotion.
- Caveat: 22.05 kHz audio, resampled to 24 kHz. Pinned by Zenodo's MD5 and size; the SHA-256 is recorded on the first verified fetch.

### speechocean762 (`speechocean762`)

- Pinned: `mispeech/speechocean762` at `06385584fad2` on `huggingface.co`; 2 files (2 by LFS SHA-256), 0.64 GB.
- License: CC-BY-4.0 ([text](https://creativecommons.org/licenses/by/4.0/); official source <https://www.openslr.org/101/>).
- License note: The Hugging Face card says apache-2.0; OpenSLR 101 says CC BY 4.0. Both allow commercial use.
- Attribution: speechocean762, an open-source non-native English speech corpus for pronunciation assessment (Zhang et al., 2021, Interspeech), by SpeechOcean and Xiaomi, OpenSLR 101, under the Creative Commons Attribution 4.0 International license (CC BY 4.0); read here from the Hugging Face dataset mispeech/speechocean762. No audio or transcript is redistributed or committed.
- Labels: accent (Mandarin L1 (constant)), gender (gender column), pronunciationScores (sentence-level expert scores), speaker (speaker column), text (text column); absent: emotion.
- Extraction: `parquet`; written at 16000 Hz; about 0.64 GB (20,043 s (datasets-server duration statistics) of 16 kHz PCM16).
- Caveat: Every speaker is a Mandarin L1 speaker of English (250 speakers, children and adults): the accent is a constant, not a per-clip label.
- Caveat: Scores are sentence-level expert scores (accuracy, completeness, fluency, prosodic, total).
<!-- END GENERATED audio-qc-docs:corpora-sources -->
