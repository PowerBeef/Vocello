# Audio QC v2

QC v2 is the audio QC harness, rebuilt on 2026-10-01. It is calibrated on the maintainer's labels:
- a few strong specialist models score every take: ASR, word alignment, phones, pitch, speaker identity, MOS, aesthetics and one audio LLM;
- small detectors turn their outputs into flags with time-localized evidence;
- thresholds are fitted on a train split of the labels and evaluated once on a held-out split.

Everything runs locally on the Mac, one model at a time, and no model weights enter Git.

## Why v2

The v1 harness missed defects the maintainer heard at once: clone pitch drift, cut-offs, accented French and the broken syllables of `fr-0101--dylan`. Its synthetic injectors often did not carry the defect they were named for, so detectors qualified on positives that were not positive. Its pitch tracker, pYIN, dropped voicing across pitch steps, the very breaks it was meant to find. No judge measured phonemes, so the ASR families turned stutters and mispronunciations into plausible words. And its ground truth never came from the maintainer's ears; v2 fits every detector on his labels instead.

## Commands

All commands go through `python3 scripts/qc.py`.

| Command | What it does |
|---|---|
| `models list [--json] [--verify]` | Lists the registered models with their role, memory, size and whether they are fetched. |
| `models fetch --model ID … \| --all [--role primary\|fallback\|alternate\|any] [--seed-dir DIR …]` | Downloads the pinned files over HTTPS and verifies their size and SHA-256. `--seed-dir` first hard-links (or copies) any local file with the same digest. |
| `models verify [--model ID …]` | Re-hashes the fetched files. Reports missing, mismatched or unextracted ones. |
| `runtimes setup --runtime mlx\|onnx\|torch\|llamacpp` | Builds a runner venv from `config/qc/runtimes/<name>.txt`, or unpacks the pinned llama.cpp release. |
| `runtimes verify [--runtime …]` | Checks the venvs against their pins. |
| `label sample --runs <qc-takes runs…> --batch NAME` | Draws a listening batch. Defaults: `--size 96 --languages french,english --blind 0.1`, plus `--enrich-file`. |
| `label serve --batch NAME [--port 8765] [--rater ID]` | Serves the listening page on 127.0.0.1. `--acoustic-only-languages zh,ja,ko,ru` hides the script and the linguistic classes for those languages. `--rater` defaults to the protocol's rater; each rater keeps their own labels. |
| `label export --batch NAME [--rater ID]` | Summarizes one rater's labels: counts per class, severity and language, and intra-rater kappa from the blind repeats. |
| `run --takes <manifest or qc-takes run> --lane NAME [--models roles or ids]` | Scores the takes with the lane's models (see [Lanes](#lanes)), one at a time; `--models` limits which run now, and the rest come from the cache. Then it runs the mute test, the features and the detectors, and prints the run id. |
| `language-bench takes --platform macos\|ios --run-id ID --plan PLAN --corpus CORPUS --diagnostics DIR [--wav-dir DIR] --output FILE` | Writes a lang-bench run's planned takes as a takes manifest, each WAV bound to the digest its generation published. |
| `language-bench evidence --run QC_RUN --output FILE` | Writes the two ASR families' recognitions of a QC run for the language publisher, with each take's two-family verdict. Exits 0 when every take met its outcome, 1 when one did not, and 2 when a recognition is missing. |
| `gate --lane NAME [--run ID]` | Exits 0 pass, 3 warn, 1 fail, or 2 error (no run, or a gating detector missing its inputs). |
| `queue --top N [--run ID] [--batch NAME]` | Writes the most suspicious unlabelled takes of a run as a label batch, which `label serve --batch NAME` opens. |
| `fit [--batches …] [--runs …]` | Fits the detectors on the train-split labels and writes `config/qc/thresholds-v<N>.json`. |
| `eval [--thresholds FILE]` | Scores the held-out split once against a committed thresholds file and writes `benchmarks/qc/eval-v<N>.json`. |
| `norms --takes <qc-takes runs…> [--min-count 100] [--dry-run]` | Measures per-language pause, pace and ending percentiles from the pool's audio and cached results, and writes `config/qc/norms-v<N>.json` (see [Per-language norms](#per-language-norms)). |

## Models and runtimes

`config/qc/models.json` is the registry. Each model has:
- an id, a kind (`asr`, `align`, `phones`, `g2p`, `pitch`, `speaker`, `mos`, `aesthetics`, `llm` or `runtime`) and a role (`primary`, `fallback` or `alternate`);
- its runner module (`qc.runners.<name>`) and runtime (`mlx`, `onnx`, `torch` or `llamacpp`);
- its license, notice and memory budget, and a `version`;
- its pinned sources:
  - a main `source`;
  - optional `dependencies` (`[{name, source}]`), stored under `models/<id>/deps/<name>/`;
  - optional `code`, stored under `models/<id>/code/`.

Source hosts:
- `huggingface`: repo and 40-hex revision;
- `github-release`: a URL per file;
- `github-raw`: repo, commit and per-file pins;
- `github-archive`: one codeload tarball, extracted with absolute paths, `..` and links refused.

Fetch follows redirects only to that host's own domains. Each file streams to a `.part` file, is checked, then moves into place. The free disk must cover the download plus 2 GB.

A runner runs as a subprocess with its runtime's python, from the repository root:

```sh
<runtime python> -m qc.runners.<name> --job <job.json>
```

`PYTHONPATH=scripts` is set, and Hugging Face offline mode is forced. The llama.cpp runners use the onnx venv.

The host:
- sends only the takes whose results are not cached yet;
- samples the peak RSS of the runner's process tree every 0.5 s;
- enforces a timeout;
- appends each run's peak memory and timing to `results/<id>/runs.jsonl`.

Only one `qc.py` run holds `build/cache/qc/run.lock` at a time.

The venvs are built from v2's own copy of the pinned standalone CPython (`cpython-3.14.4+20260414`), taken from the v1 cache on first setup. When no pinned copy exists, they use the current `python3`.

Results are content-addressed: `results/<model-id>/<audioSHA256>[.<variantKey>].json`.
- **Variant key:** alignment, LLM and speaker results also depend on the take's text, language and reference clip. `qc.store.variant_key` hashes those three into the variant key, and the job hands it to the runner as `variantKey`.
- **Runner identity:** `runnerSHA256` digests the runner file and the `qc` modules it imports (transitively), the shared runner helpers (`runners/_*.py`, which hold the LLM prompts and class definitions), `qc/phones.py` and `qc/pitch.py`, the registry `version` and every pin. Changing any of them re-scores every take. A package name (`from qc import phones`) adds no file, so editing the command line, features, detectors or lanes re-scores nothing.

## Detectors

`config/qc/detectors.json` maps the runner roles to model ids:

| Role | What it is |
|---|---|
| `asrA`, `asrB` | Two ASR families. |
| `align` | The forced aligner. |
| `phones` | The phone recognizer. |
| `g2p` | espeak-ng G2P, run as a job in the onnx venv: the script's expected phones, then, in a second pass after every role, the phones of each ASR transcript not yet in its cache. Japanese is read into kana first (see [Sound-level transcript scoring](#sound-level-transcript-scoring)). |
| `pitchA`, `pitchB` | Two pitch trackers. |
| `speaker` | Speaker embeddings. |
| `mos` | The MOS predictor. |
| `aesthetics` | Audiobox Aesthetics. |
| `llm` | The audio-LLM judge. |

`config/qc/detectors.json` also lists the detectors. Each detector reads one to four features (`qc.features`), oriented so that higher means worse. Every feature carries its evidence span (`start`, `end`).

| Detector | Class | Features |
|---|---|---|
| `pause.anomalous` | pause | The longest stretch without voiced speech between the first and last speech frames, or between two aligned words. Up to 120 ms of loud unvoiced frames is trimmed at each edge, since word-edge consonants are speech. Also: the loudest 100 ms median of its non-speech frames relative to the speech median (sustained hiss or breath, not a transient); the voiced blips inside it (under 120 ms, isolated and next to quiet); and the mute test. |
| `boundary.abrupt-end` | cutoff | From 10 ms levels: the drop within 60 ms of the final peak; the tail from 10 dB below the peak down to −60 dBFS; the decay slope; and `finishReason`. |
| `level.loudness` | (advisory) | BS.1770-4 integrated loudness (K-weighted, gated), its distance from −23 LUFS, and the 4× oversampled true peak. LRA is reported too. |
| `content.phoneme` | stutter | From `qc.phones.compare` on the G2P phones against the recognized phones (PanPhon-weighted alignment, GOP-SF on the posteriors): the phone deletion rate, repeated-syllable runs, the longest low-GOP span and the phone insertion rate. |
| `content.asr` | stutter | The smaller of the two ASR families' sound-level phone error rates against the script (`asr.phonetic_error_min`, primary), then their word insertion and deletion rate (characters for Chinese and Japanese). |
| `boundary.cutoff` | cutoff | Phone coverage of the last word, the aligner's last-word duration ratio, the level of the last 50 ms, and `finishReason`. |
| `language.wrong` | wrong-language | Both ASR families' language-ID mismatch and transcript-script mismatch (the smaller of the two). |
| `language.accent` | mispronunciation | Mean GOP, substitution rate and L1 substitutions (for example French /y/→/u/, /ʁ/→/ɹ/, denasalization). It reads no LLM vote: the lanes do not run the judge, so a vote seen in training would be missing in every lane. |
| `prosody.pitch` | pitch | On frames where both trackers agree (`qc.pitch`): the sustained shift, octave jumps, the register offset from the voice's or clone reference's median, and tracker disagreement. |
| `prosody.rate` | unnatural | The script's G2P phones per second over the speech span (first to last speech frame), and its reciprocal, so a fit can weigh both tails. |
| `prosody.tonal-collapse` | tonal-collapse | The longest steady-F0 run, its spectral flatness and its harmonic-to-noise ratio. |
| `identity.drift` | voice-change | The worst 3 s window's distance from the clone reference, the Built-in voice centroid or the take's own embedding; the whole take's distance; and the window range. |
| `signal.artifacts` | artifact | Click clusters, internal digital dropouts, clipping and terminal silence. |
| `quality.naturalness` | unnatural | UTMOSv2 on the whole take and its worst 3 s window, and Audiobox PQ and CE relative to the cell median. |
| `judge.llm.<class>` | each class | The audio LLM's `pYes`. It stays report-only unless its train kappa is at least 0.6. Gemma 4 documents its audio for speech recognition and translation only, and audio LLMs lean on the words more than the voice, so the prosody, accent and naturalness votes are expected to miss the gate. Its transcript can fill in words it expects, so no content feature reads it. |

**Provisional rules.** A detector the labels have not fitted yet scores with its `provisional` rule, when it has one, and flags at report-only. A rule reads the take's language's percentiles from the newest `config/qc/norms-v<N>.json` and falls back to its fixed value when there is no norms file, or the file lacks that language:
- `pause.anomalous`: the gap is over the language's p99 of every within-sentence pause, and at least 0.5 s (0.5 s without norms); and the mute test did not find words in it.
- `boundary.abrupt-end`: the drop is over 30 dB within 60 ms, with a tail under the language's p1 decay time, and at least 50 ms (50 ms without norms).
- `prosody.rate`: the phones per second are under the language's p1 or over its p99. Without norms it has no rule.
- `level.loudness`: the loudness is more than 4 LU from −23 LUFS, or the true peak is above −1 dBTP.
- `content.phoneme`: at least 2 repeated-syllable runs, or a phone insertion rate of at least 0.2. Against espeak-ng, ZIPA measured fr-0101--dylan at 4 runs and 0.275, and a clean en-0008--ryan at 0 and 0.

The rules live in `detectors.json`, not in a thresholds file, so a fit never has to carry them. A condition names its `norm` percentile (of its own feature or of `normFeature`) and bounds it with `atLeast` or `atMost`; each flag records the threshold it met and the norm behind it. `fit` replaces the rules once labels exist.

**The mute test.**
1. For every take whose gap reaches 0.4 s, `run` silences the gap into `build/cache/qc/work/muted/<audioSHA256>-<startMs>-<endMs>.wav`.
2. It re-transcribes that file with `asrA`.
3. It sets `pause.mute_confirmed` to 1 when the transcript is unchanged (normalized edit distance ≤ 0.1), and to 0 when it changed.

Before any fit, a detector without a rule scores uncalibrated (its largest oriented z-score), which ranks the queue but never flags.

The synthetic test case reproduces fr-0101--dylan: a 1.1 s hiss, blip and silence gap, and a 40 ms cut ending. The provisional rules must flag it, and a 0.25 s pause with a 200 ms decay must pass (`scripts/tests/test_qc_detectors.py`).

**The first heard positive: `fr-0101--dylan`.** A 5.44 s Built-in Voice take of Dylan reading French. The maintainer's own signal analysis, with two Whisper models, found two defects while every word was recognized:
- a 1.16 s non-speech gap mid-sentence (hiss, breath noise, a voiced blip and silence), proven word-free by muting it and transcribing again;
- an abrupt ending: about 36 dB of drop in 40 ms, with a 20 ms tail.

QC v2's phone check found what the ASR families hid: the voice pronounces silent letters. "fait" is read as /fɛt/, "les" as /lɛs/, "vieux" as /vjœks/ and "ormes" as /ɔʁmɛs/. The take's phone error rate is 0.48, with 11 insertions, against 0.10 on a clean take. The heard stutter is therefore spelling pronunciation, a cross-lingual defect of a Built-in voice reading French; QC-06 tracks the product side. `pause.anomalous`, `boundary.abrupt-end` and `content.phoneme` cover the three defects.

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
- `pause.longest_gap_seconds` and `pause.word_gap_seconds` (the silences between aligned words), both descriptive;
- `rate.phones_per_second` and `rate.syllables_per_second` (vowel runs of the script's G2P phones);
- `end.tail_seconds`, `end.decay_db_per_ms` and `end.drop_db_60ms`.

It writes `config/qc/norms-v<N>.json` with aggregates only: per language and feature, `n`, the mean and p1, p3, p10, p50, p90, p97 and p99, plus counts, the model identities and one digest of the pool's audio digests. It never holds a take id, path or text. Takes the engine did not finish are left out, and a language gets a feature only from at least `--min-count` values (100).

The pool's own defects shape these choices:
- **Pauses:** the pause rule reads the p99 of every pause, not of each take's longest one. A take has several pauses, so a defect rate above 1% barely moves it, while it pushes the take-level p99 past the defects (1.27 s in French, above fr-0101--dylan's 1.21 s). The per-pause p99 runs from 1.12 s (Portuguese) to 1.56 s (Chinese); 1.19 s in French still flags fr-0101--dylan. It flags 1.3% to 2.8% of each language's takes.
- **Endings:** 2% to 13% of takes end with no decay at all, so the p1 decay time is 0 s in every language, and 50 ms stays the floor. The abrupt-end signature (over 30 dB within 60 ms, under 50 ms of tail) matches 20% to 40% of the pool, and drops over 60 dB 5% to 19%: that rule needs labels.
- **Rate:** the p1 and p99 flag about 2% of takes, by construction.

Run `norms` after the pool's G2P role (and its aligner, for the descriptive word gaps), with the onnx runtime set up from the current pins, so Japanese has its reading. Any later run writes the next version, and the rules read the newest.

## Calibration and levels

**`fit`** joins the labels to the newest features per take from `build/private/qc/runs/*/features.json`.
- Each detector gets an L2 logistic on per-language z-scores, or one threshold for an LLM judge.
- The cut is the one that maximizes the weighted F1.
- The fit is per language when that language has at least 60 clean and 20 positive train takes. Otherwise, one pooled model covers it.
- A class counts as a defect at `fit.positiveMinSeverity` or worse (moderate). A tick below that bar (mild) counts on neither side for that class, nor does an uncertain verdict without a qualifying tick. A clean take is acceptable with no class ticked.
- `fit` and `eval` read the protocol's rater's labels; other JSON files in `batches/` (a takes manifest) are skipped.
- Weights are 1 / inclusion probability, so the enrichment does not bias the fit.
- Only takes where the detector's features were measured count.

The thresholds file records the model identities, the detectors digest and the label-set digest. Every fit writes a new version.

**`eval`** refuses a thresholds file that is not committed unchanged, and refuses a version that has already been scored.
- It scores the held-out probability-sample labels; queue batches are excluded.
- It writes aggregates only: per detector and language, weighted precision and recall with Clopper-Pearson bounds on the Kish effective size, the clean false-alarm rate, and kappa. It also writes the intra-rater kappa per batch.

Each detector earns a level per language:
- **warn:** the precision lower bound is at least 0.6 and the recall at least 0.6.
- **fail:** the precision lower bound is at least 0.8 and the clean false-alarm upper bound at most 5%. A fail needs about 72 clean held-out takes with no false alarm.
- **report-only:** otherwise.

`run` takes each flag's level from the evaluation of exactly the thresholds file it scored with. Without one, every flag is report-only, so `gate` passes.

## Lanes

The `lanes` map of `config/qc/detectors.json` names each lane's roles. `run` runs them by default; a lane the map does not name, such as `pool`, runs every role. A lane's gate reads only the detectors with a feature it can measure, from the WAV alone or from the roles it runs; the others stay report-only in that lane. A take marked `control` (a negative control) is scored and flagged, but always at report-only.

| Lane | Script | Roles | What it does with QC v2 |
|---|---|---|---|
| `language-bench` | `scripts/macos_test.sh lang-bench` | every role but `llm` | `language-bench takes`, then `run`, `language-bench evidence` (the verdict line `spoken_content`) and `gate` (`audio_qc_gates`). The evidence feeds `publish_benchmark_history.py language --recognitions`. |
| `ios-language-bench` | `scripts/ios_device.sh lang-bench` | every role but `llm` | The same, on the Mac over the collected iPhone takes, beside Apple Speech's in-app gate. |
| `qc-takes` | `scripts/macos_test.sh qc-takes` | every role but `llm` | `run` over the generated take pool, then `queue --top 50`; the summary joins the verdict, and a failure to compute it never fails the generation. |
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
- **A family split:** script families split 60/40 into train and held-out by a fixed hash of the script id, so a script keeps its side in every batch.
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
| `build/cache/qc/runtimes/llamacpp/` | The unpacked llama.cpp release. |
| `build/cache/qc/results/<id>/` | Runner results and `runs.jsonl`. |
| `build/private/qc/batches/<name>.json` | Label batches: token to take, split, order and inclusion probability. |
| `build/private/qc/labels/<batch>.jsonl` | The maintainer's labels, append-only. |
| `build/private/qc/jobs/` | Runner jobs and logs. A job that succeeds removes them; a failed one keeps them. |
| `build/cache/qc/work/muted/` | Muted variants for the mute test. |
| `build/private/qc/runs/<run-id>/` | `takes.json`, `features.json` and `flags.json` of each `qc.py run`. |
| `build/private/qc/queues/` | The listening queues `queue` writes. |
| `config/qc/thresholds-v<N>.json`, `benchmarks/qc/eval-v<N>.json` | Fitted thresholds and their one held-out evaluation, both committed. |
| `config/qc/norms-v<N>.json` | Per-language percentiles for the provisional rules, committed; aggregates only. |

`build/cache/qc` (`qc-cache`) is re-creatable from the registry and pins. `build/private/qc` (`qc-private`) is preserved by every cleanup. Both are registered in `config/build-output-policy.json` and git-ignored under `build/`. Labels, transcripts and take paths never enter Git; only aggregates and digests are committed.

The v1 data (its judge models and runtimes, analysis caches, unused corpora and evidence runs) goes through `scripts/clean_build_caches.sh --qc-v1`: `--dry-run` lists every path with its bytes and reason, and removal needs `--yes`. It keeps every model directory QC v2 still hard-links from, and the policy's `qcV1Cleanup` names the rest of what stays ([privacy-storage.md](privacy-storage.md)).
