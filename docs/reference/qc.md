# Audio QC v2

QC v2 is the audio QC harness, rebuilt on 2026-10-01. It is calibrated on the maintainer's labels:
- a few strong specialist models score every take: ASR, word alignment, phones, pitch, speaker identity, MOS, aesthetics and one audio LLM;
- small detectors turn their outputs into flags with time-localized evidence;
- thresholds are fitted on a train split of the labels and evaluated once on a held-out split.

Everything runs locally on the Mac, one model at a time, and no model weights enter Git.

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
| `label serve --batch NAME [--port 8765]` | Serves the listening page on 127.0.0.1. `--acoustic-only-languages zh,ja,ko,ru` hides the script and the linguistic classes for those languages. |
| `label export --batch NAME` | Summarizes the labels: counts per class, severity and language, and intra-rater kappa from the blind repeats. |
| `run --takes <manifest or qc-takes run> --lane NAME [--models roles or ids]` | Scores the takes with the detector models, one at a time; `--models` limits which run now, and the rest come from the cache. Then it runs the mute test, the features and the detectors. |
| `gate --lane NAME [--run ID]` | Exits 0 pass, 3 warn, 1 fail, or 2 error (no run, or a gating detector missing its inputs). |
| `queue --top N [--run ID] [--batch NAME]` | Writes the most suspicious unlabelled takes of a run as a label batch, which `label serve --batch NAME` opens. |
| `fit [--batches …] [--runs …]` | Fits the detectors on the train-split labels and writes `config/qc/thresholds-v<N>.json`. |
| `eval [--thresholds FILE]` | Scores the held-out split once against a committed thresholds file and writes `benchmarks/qc/eval-v<N>.json`. |

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
- **Runner identity:** `runnerSHA256` digests the runner file, the shared runner helpers (`runners/_*.py`, which hold the LLM prompts and class definitions), `qc/phones.py` and `qc/pitch.py`, the registry `version` and every pin. Changing any of them re-scores every take.

## Detectors

`config/qc/detectors.json` maps the runner roles to model ids:

| Role | What it is |
|---|---|
| `asrA`, `asrB` | Two ASR families. |
| `align` | The forced aligner. |
| `phones` | The phone recognizer. |
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
| `content.phoneme` | stutter | Phone deletions and repeated-syllable insertions (`qc.phones` G2P and alignment), the longest low-GOP run, and the smaller of the two ASR families' insertion and deletion rates against the script. |
| `boundary.cutoff` | cutoff | Phone coverage of the last word, the aligner's last-word duration ratio, the level of the last 50 ms, and `finishReason`. |
| `language.wrong` | wrong-language | Both ASR families' language-ID mismatch and transcript-script mismatch (the smaller of the two). |
| `language.accent` | mispronunciation | Mean GOP, substitution rate, L1 substitutions (for example French /y/→/u/, /ʁ/→/ɹ/, denasalization), and the LLM's vote. |
| `prosody.pitch` | pitch | On frames where both trackers agree (`qc.pitch`): the sustained shift, octave jumps, the register offset from the voice's or clone reference's median, and tracker disagreement. |
| `prosody.tonal-collapse` | tonal-collapse | The longest steady-F0 run, its spectral flatness and its harmonic-to-noise ratio. |
| `identity.drift` | voice-change | The worst 3 s window's distance from the clone reference, the Built-in voice centroid or the take's own embedding; the whole take's distance; and the window range. |
| `signal.artifacts` | artifact | Click clusters, internal digital dropouts, clipping and terminal silence. |
| `quality.naturalness` | unnatural | UTMOSv2 on the whole take and its worst 3 s window, and Audiobox PQ and CE relative to the cell median. |
| `judge.llm.<class>` | each class | The audio LLM's `pYes`. It stays report-only unless its train kappa is at least 0.6. |

**Provisional rules.** A detector the labels have not fitted yet scores with its `provisional` rule, when it has one, and flags at report-only:
- `pause.anomalous`: the gap is over 0.5 s, and the mute test did not find words in it.
- `boundary.abrupt-end`: the drop is over 30 dB within 60 ms, with a tail under 50 ms.
- `level.loudness`: the loudness is more than 4 LU from −23 LUFS, or the true peak is above −1 dBTP.

The rules live in `detectors.json`, not in a thresholds file, so a fit never has to carry them.

**The mute test.**
1. For every take whose gap reaches 0.4 s, `run` silences the gap into `build/cache/qc/work/muted/<audioSHA256>-<startMs>-<endMs>.wav`.
2. It re-transcribes that file with `asrA`.
3. It sets `pause.mute_confirmed` to 1 when the transcript is unchanged (normalized edit distance ≤ 0.1), and to 0 when it changed.

Before any fit, a detector without a rule scores uncalibrated (its largest oriented z-score), which ranks the queue but never flags.

The synthetic test case reproduces fr-0101--dylan: a 1.1 s hiss, blip and silence gap, and a 40 ms cut ending. The provisional rules must flag it, and a 0.25 s pause with a 200 ms decay must pass (`scripts/tests/test_qc_detectors.py`).

## Calibration and levels

**`fit`** joins the labels to the newest features per take from `build/private/qc/runs/*/features.json`.
- Each detector gets an L2 logistic on per-language z-scores, or one threshold for an LLM judge.
- The cut is the one that maximizes the weighted F1.
- The fit is per language when that language has at least 60 clean and 20 positive train takes. Otherwise, one pooled model covers it.
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
- Each defect class has a checkbox, a severity and start/end buttons that read the playhead.
- An overall verdict is required.
- It shows `n / total` and an estimate of the time left.

It never shows a path, mode, voice, score or enrichment reason. Audio streams by opaque token only, and the server answers only 127.0.0.1 and `localhost`.

Keys:

| Key | Action |
|---|---|
| Space | Play or pause. |
| `a` | Mark acceptable, save and go to the next take. |
| `o` | Mark objectionable. |
| `u` | Mark uncertain. |
| `1` to `0`, `-` | Toggle a class. |
| Enter | Save and go to the next take. |
| `l` | Loop. |
| `s` | Play at 0.5×. |
| ← / → | Go to the previous or next take. |

The classes, severities and verdicts come from `config/qc/protocol.json`.

Each save appends one line to `labels/<batch>.jsonl`, with these fields:
- `token`, `batch` and `rater`;
- `classes`: per class, a severity, start and end;
- `verdict`, `acousticOnly` and `labelledAt`.

Re-labelling appends a new line, and the latest line per token wins.

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

`build/cache/qc` (`qc-cache`) is re-creatable from the registry and pins. `build/private/qc` (`qc-private`) is preserved by every cleanup. Both are registered in `config/build-output-policy.json` and git-ignored under `build/`. Labels, transcripts and take paths never enter Git; only aggregates and digests are committed.
