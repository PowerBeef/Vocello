# Audio QC v2

QC v2 is the audio QC harness, rebuilt on 2026-10-01. It is calibrated on the maintainer's labels:
- a few strong specialist models score every take: two speech recognition (ASR) families, two phone recognizers and a G2P; for clones only, two pitch trackers and a speaker embedder;
- small detectors turn their outputs into flags with time-localized evidence;
- every detector is first measured on human read speech (the controls), where it should almost never flag;
- thresholds are fitted on the labels and evaluated once per label set out of fold: each labelled take is scored by a model fitted without its script family.

Everything runs locally on the Mac, one model at a time, and no model weights enter Git.

## Why v2

The v1 harness missed defects the maintainer heard at once: clone pitch drift, cut-offs, accented French and the broken syllables of `fr-0101--dylan`. Its synthetic injectors often did not carry the defect they were named for, so detectors qualified on positives that were not positive. Its pitch tracker, pYIN, dropped voicing across pitch steps, the very breaks it was meant to find. No judge measured phonemes, so the ASR families turned stutters and mispronunciations into plausible words. And its ground truth never came from the maintainer's ears; v2 fits every detector on his labels instead.

## What v2 measures, and from which report

QC v2 keeps only what the external reviews recommend:
- **The "Voice Clip QA" report on `fr-0101--dylan`:** the signal measures (loudness, peaks, dropouts, clipping), the pauses and the ending.
- **Its guidance:** a second transcription family with consensus (Qwen3-ASR beside Whisper large-v3), sound-level scoring of the transcripts, and per-language pace and pause norms. It leaves accent and naturalness to a human listener, so no detector measures them.
- **The "Review and Fixes" code review:**
  - two phone recognizers that must agree (ZIPA and wav2vec2-espeak), against expected phones from espeak-ng and PanPhon;
  - quiet-frame pauses, and a pause tested on its own (the excerpt test);
  - the ending as a trimming check, with cut-offs judged from content;
  - human controls, labels first, and out-of-fold evaluation.

No audio-LLM judge: on 2026-10-02 the maintainer found a cloud audio LLM useless for defect detection, Gemma 4 documents its audio for ASR and translation only, and audio LLMs lean on the words more than the voice; v2 measures instead.

Pitch and speaker identity are kept for clones only, by the maintainer's decision of 2026-10-02: FCPE and SwiftF0 measure a clone's register against its reference clip, and ReDimNet2+ its similarity to it.

The 12 label classes cover more than the detectors measure (mispronunciation, tonal collapse, a devoiced syllable, and pitch or voice changes outside clones): what no detector measures is caught by the labels and by listening.

## Commands

All commands go through `python3 scripts/qc.py`.

| Command | What it does |
|---|---|
| `models list [--json] [--verify]` | Lists the registered models with their role, memory, size and whether they are fetched. |
| `models fetch --model ID … \| --all [--role primary\|fallback\|alternate\|any] [--seed-dir DIR …]` | Downloads the pinned files over HTTPS and verifies their size and SHA-256. `--seed-dir` first hard-links (or copies) any local file with the same digest. |
| `models verify [--model ID …]` | Re-hashes the fetched files. Reports missing, mismatched or unextracted ones. |
| `models prune --dry-run\|--yes` | Lists (`--dry-run`) or removes (`--yes`) `models/<id>/` and `results/<id>/` under `build/cache/qc` for every id the registry no longer lists, and the retired llama.cpp runtime, with each path's bytes and the bytes its removal frees. It keeps the registered models, the G2P text cache (`results/g2p`), `work/` and the kept runtimes. It refuses while a run holds `run.lock`, and refuses a symbolic link or a path outside its directory, removing nothing. |
| `runtimes setup --runtime mlx\|onnx\|torch` | Builds a runner venv from `config/qc/runtimes/<name>.txt`. |
| `runtimes verify [--runtime …]` | Checks the venvs against their pins. |
| `label sample --runs <qc-takes runs…> --batch NAME` | Draws a listening batch. Defaults: `--size 96 --languages french,english --blind 0.1`, plus `--enrich-file`. |
| `label serve --batch NAME [--port 8765] [--rater ID]` | Serves the listening page on 127.0.0.1. `--acoustic-only-languages zh,ja,ko,ru` hides the script and the linguistic classes for those languages. `--rater` defaults to the protocol's rater; each rater keeps their own labels. |
| `label export --batch NAME [--rater ID]` | Summarizes one rater's labels: counts per class, severity and language, and intra-rater kappa from the blind repeats. |
| `run --takes <manifest or qc-takes run> --lane NAME [--models roles or ids]` | Scores the takes with the lane's models (see [Lanes](#lanes)), one at a time; `--models` limits which run now, and the rest come from the cache. Then it runs the excerpt test, the features and the detectors, and prints the run id. |
| `language-bench takes --platform macos\|ios --run-id ID --plan PLAN --corpus CORPUS --diagnostics DIR [--wav-dir DIR] --output FILE` | Writes a lang-bench run's planned takes as a takes manifest, each WAV bound to the digest its generation published. |
| `language-bench evidence --run QC_RUN --output FILE` | Writes the two ASR families' recognitions of a QC run for the language publisher, with each take's two-family verdict. Exits 0 when every take met its outcome, 1 when one did not, and 2 when a recognition is missing. |
| `gate --lane NAME [--run ID]` | Exits 0 pass, 3 warn, 1 fail, or 2 error (no run, or a gating detector missing its inputs). |
| `queue --top N [--run ID] [--batch NAME]` | Writes the most suspicious unlabelled takes of a run as a label batch, which `label serve --batch NAME` opens. |
| `fit [--batches …] [--runs …] [--rater ID] [--reuse-reason TEXT]` | Fits the detectors per script-family fold and on every label, and writes `config/qc/thresholds-v<N>.json`. |
| `eval [--thresholds FILE] [--rater ID]` | Scores every labelled sample take out of fold against a committed thresholds file, once per label set, and writes `benchmarks/qc/eval-v<N>.json`. |
| `norms --takes <qc-takes runs…> [--min-count 100] [--dry-run]` | Measures per-language pause, pace and ending percentiles from the pool's audio and cached results, and writes `config/qc/norms-v<N>.json` (see [Per-language norms](#per-language-norms)). |
| `controls build [--sources mls:french libritts-r:english] [--per-language 150]` | Writes a takes manifest of human read speech from the speaker corpora, each take marked `control`; score it with `run --lane controls`. |
| `controls report --runs <controls runs…> [--generated <runs…>]` | Each detector's flag rate on the human controls (with bounds) beside the generated takes', and every feature's p50 and p90. |

## Models and runtimes

`config/qc/models.json` is the registry:

| Model | Role | Runtime | What it gives |
|---|---|---|---|
| `asr.qwen3-asr-1.7b` | `asrA` | mlx | Qwen3-ASR transcript and language. |
| `asr.whisper-large-v3` | `asrB` | mlx | Whisper large-v3 transcript and language. |
| `phones.zipa-large-crctc-500k` | `phones` | onnx | ZIPA phones with posteriors (GOP). |
| `phones.wav2vec2-xlsr-53-espeak-cv-ft` | `phonesB` | torch | wav2vec2 XLS-R espeak phones, the second recognizer. |
| `g2p.espeak-ng` | `g2p` | onnx | The script's expected phones (espeak-ng, PanPhon features). |
| `pitch.fcpe` | `pitchA` | torch | FCPE pitch track (clones only). |
| `pitch.swiftf0` | `pitchB` | onnx | SwiftF0 pitch track (clones only). |
| `speaker.redimnet2-plus` | `speaker` | torch | ReDimNet2+ speaker embeddings (clones only). |

Each model has:
- an id, a kind (`asr`, `phones`, `g2p`, `pitch` or `speaker`) and a role (`primary`, `fallback` or `alternate`; every registered model is primary);
- its runner module (`qc.runners.<name>`) and runtime (`mlx`, `onnx` or `torch`);
- its license, notice and memory budget, and a `version`;
- its pinned sources:
  - a main `source`;
  - optional `dependencies` (`[{name, source}]`), stored under `models/<id>/deps/<name>/`;
  - optional `code`, stored under `models/<id>/code/`.

Source hosts:
- `huggingface`: repo and 40-hex revision;
- `github-raw`: repo, commit and per-file pins;
- `github-archive`: one codeload tarball, extracted with absolute paths, `..` and links refused.

Fetch follows redirects only to that host's own domains. Each file streams to a `.part` file, is checked, then moves into place. The free disk must cover the download plus 2 GB.

A runner runs as a subprocess with its runtime's python, from the repository root:

```sh
<runtime python> -m qc.runners.<name> --job <job.json>
```

`PYTHONPATH=scripts` is set, and Hugging Face offline mode is forced.

The host:
- sends only the takes whose results are not cached yet;
- samples the peak RSS of the runner's process tree every 0.5 s;
- enforces a timeout;
- appends each run's peak memory and timing to `results/<id>/runs.jsonl`.

Only one `qc.py` run holds `build/cache/qc/run.lock` at a time.

The venvs are built from v2's own copy of the pinned standalone CPython (`cpython-3.14.4+20260414`), taken from the v1 cache on first setup. When no pinned copy exists, they use the current `python3`.

Results are content-addressed: `results/<model-id>/<audioSHA256>[.<variantKey>].json`.
- **Variant key:** G2P and speaker results also depend on the take's text, language and reference clip. `qc.store.variant_key` hashes those three into the variant key, and the job hands it to the runner as `variantKey`.
- **Runner identity:** `runnerSHA256` digests the runner file and the `qc` modules it imports (transitively, helpers such as `runners/_kit.py` and `runners/speech_common.py` included), the registry `version` and every pin. Changing any of them re-scores that model's takes, and only that model's: a `qc/phones.py` edit re-runs the phone recognizers and the G2P only. A package name (`from qc import phones`) adds no file, so editing the command line, features, detectors or lanes re-scores nothing.
- **Scoring identity:** `qc.detectors.scoring_identity` digests `config/qc/detectors.json`, the scoring code (`qc/features.py`, `qc/detectors.py`, `qc/phones.py`, `qc/pitch.py`) and the newest norms file. Runs record it in `features.json`; thresholds apply only to features scored by the same code, configuration and norms, and `run` otherwise stays report-only and says why.

## Detectors

`config/qc/detectors.json` maps the runner roles to model ids:

| Role | What it is |
|---|---|
| `asrA`, `asrB` | Two ASR families. |
| `phones`, `phonesB` | Two phone recognizers: ZIPA and wav2vec2 XLS-R espeak. A phone insertion counts only when both hear it. |
| `g2p` | espeak-ng G2P, run as a job in the onnx venv: the script's expected phones, then, in a second pass after every role, the phones of each ASR transcript not yet in its cache. Japanese is read into kana first (see [Sound-level transcript scoring](#sound-level-transcript-scoring)). |
| `pitchA`, `pitchB` | Two pitch trackers (clones only). |
| `speaker` | Speaker embeddings (clones only). |

`config/qc/detectors.json` also lists the detectors: eight for every take and two for clones. Each detector reads one to four features (`qc.features`), oriented so that higher means worse, through an L2 logistic once fitted. Every feature carries its evidence span (`start`, `end`). A detector with `gateLanes` gates only in those lanes: the two clone detectors gate only in `clone-lane`.

| Detector | Class | Features |
|---|---|---|
| `pause.anomalous` | pause | The longest pause: a run of quiet frames (20 dB under the speech median) between the first and last speech frames, bridging holes of 30 ms or less. A whisper or a voiceless consonant is loud, so it is speech, not pause. Also: the loudest 100 ms median of the non-speech stretch around it relative to the speech median; the voiced blips inside it (under 120 ms, isolated and next to quiet); and the excerpt test. |
| `level.loudness` | (advisory) | BS.1770-4 integrated loudness (K-weighted, gated), its distance from −23 LUFS, and the 4× oversampled true peak. LRA is reported too. |
| `content.phoneme` | stutter | From `qc.phones.compare` on the G2P phones against each recognizer's phones (PanPhon-weighted alignment, GOP-SF on ZIPA's posteriors): ZIPA's phone deletion rate and longest low-GOP span, and the insertion rate and repeated-syllable runs of the insertions both recognizers hear (within 60 ms, else at the same expected position). Without `phonesB` the last two abstain. French liaison consonants and final schwas are optional in the expected phones, a substitution within the near-identity scale counts as a match, and a rhyme is not a repeat. |
| `content.asr` | stutter | The smaller of the two ASR families' sound-level phone error rates against the script (`asr.phonetic_error_min`, primary), then their word insertion and deletion rate (characters for Chinese and Japanese). |
| `boundary.cutoff` | cutoff | Phone coverage of the last word, the level of the last 50 ms, and `finishReason`. |
| `language.wrong` | wrong-language | Both ASR families' language-ID mismatch and transcript-script mismatch (the smaller of the two). |
| `prosody.rate` | unnatural | The script's G2P phones per second of articulation (the speech span minus its pauses of 0.1 s or more, so a long pause is not read as slow speech), and its reciprocal, so a fit can weigh both tails. |
| `signal.artifacts` | artifact | Internal digital dropouts, clipping and terminal silence. Click clusters (`signal.clicks`, a 10 ms local robust spike count that skips loud unvoiced frames) are reported, but stay out of the detector until they score near zero on the human controls. |
| `prosody.pitch` (clones) | pitch | On frames where both trackers agree (`qc.pitch`): the sustained shift, octave jumps, the register offset from the clone reference's median (none without a reference), and tracker disagreement. |
| `identity.drift` (clones) | voice-change | The worst 4 s window's and the whole take's distance from the clone reference's embedding (none without a reference), and the spread of the take's windows around its own embedding. |

**The ending** is measured and reported, never a detector: from 10 ms levels (the file's end padded at −60 dB, levels clamped at −100 dB), the drop within 60 ms of the final peak, the tail from 10 dB below the peak down to −60 dBFS and the decay slope; on human recordings that signature (a drop and a short tail) flags 5% of French and 47% of English files, which describes how files are trimmed. `end.file_tail_seconds`, the time from the last speech frame to the file's end, is the trimming check. A cut-off needs content evidence (`boundary.cutoff`).

**Provisional rules.** A detector the labels have not fitted yet scores with its `provisional` rule, when it has one, and flags at report-only. A rule reads the take's language's percentiles from the newest `config/qc/norms-v<N>.json` and falls back to its fixed value when there is no norms file, or the file lacks that language:
- `pause.anomalous`: the pause is over the language's p99 of every within-sentence pause, and at least 0.5 s (0.5 s without norms); and the excerpt test heard no phone in it.
- `prosody.rate`: the phones per second are under the language's p1 or over its p99. Without norms it has no rule.
- `level.loudness`: the loudness is more than 4 LU from −23 LUFS, or the true peak is above −1 dBTP.
- `content.phoneme`: at least 2 repeated-syllable runs, or a phone insertion rate of at least 0.2. With ZIPA alone this flags 9.7% of human French recordings (FLEURS): ZIPA prints silent letters native speakers do not say. The insertion rate and repeat runs therefore count only insertions both phone recognizers hear.

The rules live in `detectors.json`, not in a thresholds file, so a fit never has to carry them. A condition names its `norm` percentile (of its own feature or of `normFeature`) and bounds it with `atLeast` or `atMost`; each flag records the threshold it met and the norm behind it. `fit` replaces the rules once labels exist.

**The excerpt test.** Speech and phone recognizers fill in words and phones over zeroed audio inside a sentence, so silencing a pause and transcribing again proves nothing. Instead:
1. For every take whose longest pause reaches 0.4 s (`excerptMinGapSeconds`), `run` cuts the pause, 40 ms inside its edges, into a WAV of its own: `build/cache/qc/work/excerpts/<audioSHA256>-<startMs>-<endMs>.wav`.
2. Both phone recognizers run on that excerpt alone, with no speech around it to lean on.
3. `pause.excerpt_phones` is the most phones either recognizer hears there at probability 0.5 or more (`excerptPhoneMinProb`), breath-like /h/ and /ɦ/ aside (`excerptIgnorePhones`). Zero says the pause holds no speech sound; the floor is checked on the human controls.

Before any fit, a detector without a rule scores uncalibrated (its largest oriented z-score), which ranks the queue but never flags.

The synthetic test case reproduces fr-0101--dylan as the review measured it: a /t/ closure, a 0.35 s whispered syllable, then a 0.8 s pause with one voiced blip. The pause rule must measure the 0.8 s pause, not the whisper, and a 0.25 s pause must pass (`scripts/tests/test_qc_detectors.py`).

**The first heard positive: `fr-0101--dylan`.** A 5.44 s Built-in Voice take of Dylan reading French, in which the maintainer heard a stutter and missing syllables while every word was recognized. What the signal shows, as corrected on October 2 by an external review run against human French recordings:
- the last syllable of "abattus" ("-tus", 3.07–3.43 s) is whispered, then the voice stops for 0.82 s, with one short voiced sound at 3.92 s just before "obstruaient";
- the take ends 0.02 s after its last sound;
- it sits at −26.4 LUFS.

Two earlier readings were wrong. The "1.16 s non-speech gap" held the whispered syllable, and muting it proved nothing: speech and phone recognizers fill in words and phones over zeroed audio. ZIPA's silent letters ("les" /lɛs/, "des" /dɛs/) are the recognizer's own bias: it prints them after 38% and 36% of those words read by native French speakers, where the wav2vec2 phone recognizer does after 3% and 0%; and "de fait" /dəfɛt/ is correct French. What was heard as a stutter is unexplained. The candidates are the whispered syllable, the voiced sound before "obstruaient", and "ormes abattus" linked as "orme-euz-abattus"; only listening can choose. The new `devoiced` label class names the first.

## Sound-level transcript scoring

A word error rate counts homophones: on fr-0101--dylan, Whisper heard *voie* as *voix* and *abattus* as *abattues*, two wrong words in twelve for the same sounds. Chinese and Japanese have no spaces and many homophones, so their word (character) errors mislead too. QC v2 therefore compares the transcripts at the sound level:
1. The script and each ASR transcript go through the same G2P (espeak-ng, cached by text) into broad phones.
2. `qc.phones.align` aligns them with the PanPhon feature distance.
3. `asr.phonetic_error_a` and `_b` count deletions, insertions and substitutions over the script's phones. A substitution within the phone tools' near-identity scale (PanPhon distance 0.06: /e/ for /ɛ/, a voicing pair) counts as a match, since the ASR's language model makes those choices.
4. `asr.phonetic_error_min` is the smaller of the two; like the word rates, it needs both families.

On the three cached reference takes, fr-0101--dylan scores 0 for Qwen3-ASR and 0.025 for Whisper, against a word error rate of 0.17: espeak-ng reads a liaison /z/ after the feminine *abattues*, one phone in forty. fr-0003's *faim* heard as *fin* scores 0 (word error 0.125), and en-0008--ryan scores 0. A real substitution counts: *le chat dort* heard as *le rat dort* scores 1/7.

Per language:
- **Chinese:** espeak-ng `cmn` reads Hanzi, Simplified or Traditional, with one reading per polyphone. Both sides get the same reading, so a polyphone costs nothing.
- **Japanese:** espeak-ng reads kana only; a kanji comes out as the English words "Chinese letter". The G2P job therefore first reads Japanese into katakana pronunciation (UniDic `pron`, one space between words) with MeCab and the UniDic-lite dictionary through fugashi. fugashi is MIT, MeCab BSD-3-Clause, and UniDic is used under the BSD-3-Clause option of its GPL/LGPL/BSD license; both are pinned in `config/qc/runtimes/onnx.txt`. The reader's versions key the Japanese G2P records. Without the reader (an onnx venv set up before the pins), the job writes no Japanese result and every Japanese phone feature abstains, instead of scoring against "Chinese letter".
- **Korean:** espeak-ng's own rules.

**Future work:** tone and pitch-accent checks for Mandarin and Japanese, per syllable. Broad phones drop tones, so a wrong tone or accent is invisible to the sound-level comparison.

## Per-language norms

A fixed "natural pause" of 0.2-0.3 s is French- and English-centric. Over the pool's 4,751 generated takes (measured from the audio on 2026-10-01), the fixed 0.5 s pause rule flagged 15% of English takes, 25% of French ones and 50% of Chinese ones. `qc.py norms --takes <qc-takes runs…>` measures, per language, from each take's audio and its cached aligner and G2P results:
- `pause.gap_seconds`: every within-sentence pause of at least 100 ms, measured as `pause.anomalous` measures the longest one;
- `pause.longest_gap_seconds`, descriptive;
- `rate.phones_per_second` and `rate.syllables_per_second` (per second of articulation);
- `end.tail_seconds`, `end.decay_db_per_ms`, `end.drop_db_60ms` and `end.file_tail_seconds`.

It writes `config/qc/norms-v<N>.json` with aggregates only: per language and feature, `n`, the mean and p1, p3, p10, p50, p90, p97 and p99, plus counts, the model identities and one digest of the pool's audio digests. It never holds a take id, path or text. Control takes and takes the engine did not finish are left out, and a language gets a feature only from at least `--min-count` values (100).

The figures below were measured on 2026-10-01 with the earlier pause definition (unvoiced frames counted as pause); norms-v1 is computed after the October 2 rescore. The French per-pause p99 of the pool (1.19 s) matched human French read speech (1.17 s).

The pool's own defects shape these choices:
- **Pauses:** the pause rule reads the p99 of every pause, not of each take's longest one. A take has several pauses, so a defect rate above 1% barely moves it, while it pushes the take-level p99 past the defects (1.27 s in French, above fr-0101--dylan's 1.21 s). The per-pause p99 runs from 1.12 s (Portuguese) to 1.56 s (Chinese); 1.19 s in French still flags fr-0101--dylan. It flags 1.3% to 2.8% of each language's takes.
- **Endings:** 2% to 13% of takes end with no decay at all, so the p1 decay time is 0 s in every language. The abrupt-end signature (over 30 dB within 60 ms, under 50 ms of tail) matches 20% to 40% of the pool, and drops over 60 dB 5% to 19%: the ending is reported as a trimming check, and a cut-off is judged from content.
- **Rate:** the p1 and p99 flag about 2% of takes, by construction.

Run `norms` after the pool's G2P role, with the onnx runtime set up from the current pins, so Japanese has its reading. Any later run writes the next version, and the rules read the newest.

## Calibration and levels

**`fit`** joins one rater's labels to the newest features per take from `build/private/qc/runs/*/features.json` (the controls lane aside), and refuses runs of different runner or scoring identities.
- Each detector gets an L2 logistic on per-language z-scores.
- The cut is the one that maximizes the weighted F1.
- The fit is per language when that language has at least 60 clean and 20 positive takes. Otherwise, one pooled model covers it, from 10 positives up (`pooledMinPositive`); below that the detector keeps its provisional rule.
- A class counts as a defect at `fit.positiveMinSeverity` or worse (moderate). A tick below that bar (mild) counts on neither side for that class, nor does an uncertain verdict without a qualifying tick. A clean take is acceptable with no class ticked.
- `fit` and `eval` read one rater's labels (`--rater`, default the protocol's); other JSON files in `batches/` are skipped.
- **Out of fold:** script families fall into `crossValidationFolds` (5) folds by a fixed hash (`label.fold_for_family`). Each fold's detectors are fitted on every label outside it, and the final detectors on every label. The stored 60/40 `split` plays no part.
- Weights are 1 / inclusion probability, so the enrichment does not bias the fit.
- Only takes where the detector's features were measured count.

The thresholds file (`vocello.qc.thresholds/2`) records the model identities, the scoring identity, the rater, each fold's label-set digest and detectors, and the final detectors. Every fit writes a new version.

**`eval`** refuses a thresholds file that is not committed unchanged, a version that has already been scored, features scored with other runners or scoring code, and a label set an earlier evaluation already scored (in `benchmarks/qc/eval-v*.json` or the private `eval-ledger.jsonl`), unless the fit declared `--reuse-reason`.
- It scores every labelled probability-sample take with its own fold's model; queue batches are excluded.
- It writes aggregates only: per detector and language, weighted precision and recall with Clopper-Pearson bounds on the Kish effective size, the clean false-alarm rate, and kappa. It also writes the intra-rater kappa per batch.

Each detector earns a level per language:
- **warn:** the precision lower bound is at least 0.6 and the recall at least 0.6.
- **fail:** the precision lower bound is at least 0.8 and the clean false-alarm upper bound at most 5%. A fail needs about 72 clean labelled takes in that language with no false alarm.
- **report-only:** otherwise.

`run` takes each flag's level from the evaluation of exactly the thresholds file it scored with. Without one, every flag is report-only, so `gate` passes.

## Lanes

The `lanes` map of `config/qc/detectors.json` names each lane's roles. `run` runs them by default; a lane the map does not name, such as `pool`, runs every role. A lane's gate reads only the detectors with a feature it can measure, from the WAV alone or from the roles it runs, and the clone detectors only in `clone-lane` (`gateLanes`); the others stay report-only in that lane. A take marked `control` (a negative control, or a human recording) is scored and flagged, but always at report-only.

**Human controls.** `controls build` samples human read speech from the extracted speaker corpora (MLS for French, LibriTTS-R for English; 150 per language, at most 3 clips per speaker), and `run --lane controls` scores it with the qc-takes roles. The controls lane never feeds `fit`, `queue` or norms. `controls report` gives each detector's flag rate on the controls beside the generated takes': a provisional rule should flag at most 5% of human recordings per language before it is trusted, and a fit should sit above the controls' own floor (human French has a median ZIPA phone error rate of 0.15).

**Controls results (2026-10-02, 300 human takes against batch-1's 96, under `norms-v1`):**

| Rule | Human French | Human English | Batch-1 takes |
|---|---|---|---|
| `content.phoneme` | 0.7% | 0% | 0% |
| `prosody.rate` | 1.3% | 0% | 1% |
| `pause.anomalous` | 27% (not comparable, below) | 0% | 3% |
| `level.loudness` (advisory) | 37% | 100% | 43% |

- `content.phoneme` with two-recognizer agreement flags 0.7% of human French, where ZIPA alone flagged 9.7% (FLEURS, external review).
- The French pause figure is not a like-for-like control: MLS clips are 11-20 s audiobook passages of several sentences (median 35 words, transcripts without punctuation), so their longest pause is often between sentences (median 0.82 s, p90 1.52 s). The English clips are single punctuated sentences (median 17 words, longest pause median 0.17 s), and the rule flags none of them. The French pause rule stays unvalidated until the labels.
- `level.loudness` measures how a recording was mastered against −23 LUFS, not a defect; it is advisory, never gates and never ranks the listening queue.

| Lane | Script | Roles | What it does with QC v2 |
|---|---|---|---|
| `language-bench` | `scripts/macos_test.sh lang-bench` | `asrA`, `asrB`, `g2p`, `phones`, `phonesB` | `language-bench takes`, then `run`, `language-bench evidence` (the verdict line `spoken_content`) and `gate` (`audio_qc_gates`). The evidence feeds `publish_benchmark_history.py language --recognitions`. |
| `ios-language-bench` | `scripts/ios_device.sh lang-bench` | the same | The same, on the Mac over the collected iPhone takes, beside Apple Speech's in-app gate. |
| `qc-takes` | `scripts/macos_test.sh qc-takes` | the same | `run` over the generated take pool, then `queue --top 50`; the summary joins the verdict, and a failure to compute it never fails the generation. |
| `controls` | `qc.py controls build`, then `run --lane controls` | the same | Human read speech: every flag is report-only, and the lane never feeds `fit`, `queue` or norms. |
| `clone-lane` | `scripts/clone_fidelity_lane.py` | `speaker`, `pitchA`, `pitchB` | Every take against the voice's reference clip; the clone takes gate, the controls measure the identity separation. |
| `voice-reliability` | `scripts/voice_identity_language_reliability.py analyze` | `speaker`, `pitchA`, `pitchB` | Clone takes against their reference; reported, never gated. |

**Spoken content.** The language lanes' two families are Qwen3-ASR (`asrA`, family `qwen3-asr`) and Whisper large-v3 (`asrB`, family `whisper`). Both transcribe a take with neither its script nor its language, so a take in the wrong language fails the language channel. The two must meet each take's outcome on both channels (`lib.language_metrics.qc_take_verdict`); the negative control, a pinned hint over a script in another language, is a language control. The publisher re-scores every transcript, and language records carry the `qcQwen3Asr*` and `qcWhisper*` take metrics (language measurement version 6).

**Clone fidelity.** `qc.fidelity` reads the run's results per take: the register shift from the reference (signed semitones) on the frames where FCPE and SwiftF0 agree, through `qc.pitch.summarize`, and the ReDimNet2+ similarity of the whole take and of its least similar window to the reference embedding.

## Labels

`label sample` reads one or more qc-takes runs (`takes-manifest.json`, `wav/`, `references/`; the clone transcripts come from `batches/index.tsv`). Per language, it draws:
- **60% uniform:** a systematic sample over every take, sorted by language, mode, cell and voice. This is implicitly stratified, and each take has inclusion probability n/N.
- **40% enriched:** a simple random sample of the enrichment list. The file maps `"<runTag>:<takeID>"` to `{"run": "<run dir>", "takeID": "...", "reasons": [...]}`; `"certain": true` includes a take with probability 1.

The batch also gets:
- **Inclusion probabilities:** each take's probability is recorded, and the evaluation reweights by it.
- **A family split:** script families split 60/40 by a fixed hash of the script id. Fitting no longer reads it: evaluation is out of fold by the same families (see [Calibration and levels](#calibration-and-levels)).
- **Blind repeats:** about 10% of the takes come back later under a second token, for intra-rater agreement.

The page shows one take at a time:
- It autoplays each take and offers loop, 0.5× and replay.
- It shows the script, plus the reference clip for clones.
- Each defect class has a checkbox, a severity and start/end buttons that read the playhead. A ticked class has no severity until one is chosen.
- An overall verdict is required.
- A take saves only once it has played to the end (at least 95% of it, or the `ended` event); held keys never repeat a save.
- It shows `n / total` and an estimate of the time left.

It never shows a path, mode, voice, score or enrichment reason. Audio streams by opaque token only, and the server answers only 127.0.0.1 and `localhost`.

Keys:

| Key | Action |
|---|---|
| Space | Play or pause. |
| `a` | Mark acceptable, save and go to the next take. Refused while a class is ticked. |
| `o` | Mark objectionable. |
| `u` | Mark uncertain. |
| `1` to `0`, `-`, `=` | Toggle a class. |
| Enter | Save and go to the next take. |
| `l` | Loop. |
| `s` | Play at 0.5×. |
| ← / → | Go to the previous or next take. |

The classes, severities and verdicts come from `config/qc/protocol.json`. The `devoiced` class marks a whispered or devoiced syllable, such as a last syllable spoken in a whisper.

Each save appends one line to `labels/<batch>.jsonl`, with these fields:
- `token`, `batch` and `rater`;
- `classes`: per class, a severity, start and end;
- `verdict`, `acousticOnly`, `playedFraction`, `protocolSHA256` and `labelledAt`.

Re-labelling appends a new line, and the latest line per rater and token wins; another rater's lines never replace them.

## Data layout

| Path | Holds |
|---|---|
| `build/cache/qc/models/<id>/` | Fetched model files, plus `deps/<name>/` and `code/`. |
| `build/cache/qc/runtimes/{mlx,onnx,torch}/` | The runner venvs. |
| `build/cache/qc/runtimes/python/` | The pinned interpreter copy. |
| `build/cache/qc/results/<id>/` | Runner results and `runs.jsonl`; `results/g2p/` is the G2P text cache. |
| `build/private/qc/batches/<name>.json` | Label batches: token to take, split, order and inclusion probability. |
| `build/private/qc/labels/<batch>.jsonl` | The maintainer's labels, append-only. |
| `build/private/qc/jobs/` | Runner jobs and logs. A job that succeeds removes them; a failed one keeps them. |
| `build/cache/qc/work/excerpts/` | Pause excerpts for the excerpt test. |
| `build/private/qc/manifests/` | Takes manifests (the controls, a batch's takes); never read as batches. |
| `build/private/qc/eval-ledger.jsonl` | The label sets each evaluation scored (tokens), so a deleted eval file cannot hide a re-run. |
| `build/private/qc/runs/<run-id>/` | `takes.json`, `features.json` and `flags.json` of each `qc.py run`. |
| `build/private/qc/queues/` | The listening queues `queue` writes. |
| `config/qc/thresholds-v<N>.json`, `benchmarks/qc/eval-v<N>.json` | Fitted thresholds and their one out-of-fold evaluation, both committed. |
| `config/qc/norms-v<N>.json` | Per-language percentiles for the provisional rules, committed; aggregates only. |

`build/cache/qc` (`qc-cache`) is re-creatable from the registry and pins; `qc.py models prune` removes what the registry no longer lists. `build/private/qc` (`qc-private`) is preserved by every cleanup. Both are registered in `config/build-output-policy.json` and git-ignored under `build/`. Labels, transcripts and take paths never enter Git; only aggregates and digests are committed.

The v1 data (its judge models and runtimes, analysis caches, unused corpora and evidence runs) goes through `scripts/clean_build_caches.sh --qc-v1`: `--dry-run` lists every path with its bytes and reason, and removal needs `--yes`. It keeps every model directory QC v2 still hard-links from, and the policy's `qcV1Cleanup` names the rest of what stays ([privacy-storage.md](privacy-storage.md)).
