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
| `run`, `gate`, `queue`, `fit`, `eval` | Lane scoring, gating, the listening queue and calibration. These are phase 2: until it lands, they exit 2. |

The `gate` exit codes are 0 pass, 3 warn, 1 fail and 2 error.

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
- **Runner identity:** `runnerSHA256` digests the runner source, the registry `version` and every pin. Changing any of them re-scores every take.

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
| `1` to `0` | Toggle a class. |
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
| `build/private/qc/runs/`, `queues/` | Lane flags and listening queues (phase 2). |

`build/cache/qc` (`qc-cache`) is re-creatable from the registry and pins. `build/private/qc` (`qc-private`) is preserved by every cleanup. Both are registered in `config/build-output-policy.json` and git-ignored under `build/`. Labels, transcripts and take paths never enter Git; only aggregates and digests are committed.
