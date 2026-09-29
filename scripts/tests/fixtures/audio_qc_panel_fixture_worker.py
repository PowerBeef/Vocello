#!/usr/bin/env python3
"""A test-only worker for the AQ-06 panel engines: the real worker host, no model.

It runs `audio_qc_worker.main` with every panel engine (and `whisper-mlx`)
replaced by one table engine. The job's engine configuration answers each row:

- `table`: canonical PCM SHA-256 -> the raw result the judge would emit;
- `default`: the result for a PCM the table does not name;
- `embedFromDigest`: a speaker embedding derived from the PCM digest (so a
  take and its reference clip differ), with two 2 s windows;
- `counterFile` and `perturb`: each launch increments the counter, and
  `perturb` (`transcript` or `float`) makes the answer depend on it, as a
  nondeterministic judge would across two runs.

The row's own fields (its language, its reference text) are echoed back so
tests can check what the orchestrator sent.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import audio_qc_worker  # noqa: E402

MINIMUM_LIFE_SECONDS = 0.25


def _launch(config) -> int:
    counter = config.get("counterFile")
    if not counter:
        return 0
    path = Path(counter)
    value = int(path.read_text(encoding="utf-8")) + 1 if path.exists() else 1
    path.write_text(str(value), encoding="utf-8")
    return value


def table_engine(job, emit) -> None:
    config = job["engineConfig"]
    launch = _launch(config)
    emit({"kind": "ready", "engine": job["engine"], "threads": job["threads"],
          "modelLoadSeconds": 0.01, "warmupSeconds": 0.0})
    for row in job["rows"]:
        digest = hashlib.sha256(Path(row["pcmPath"]).read_bytes()).hexdigest()
        result = dict((config.get("table") or {}).get(digest) or config.get("default") or {})
        if config.get("embedFromDigest"):
            vector = [((int(digest[index:index + 2], 16) % 17) - 8) / 8.0 + 0.5 for index in range(0, 16, 2)]
            result.update(embedding=vector, dimension=len(vector),
                          windows=[{"startSeconds": 0.0, "embedding": vector},
                                   {"startSeconds": 0.5, "embedding": list(reversed(vector))}])
        if config.get("perturb") == "transcript" and "transcript" in result:
            result["transcript"] = f"{result['transcript']} {launch}"
        if config.get("perturb") == "float" and "CE" in result:
            result["CE"] = result["CE"] + 1e-7 * launch
        # As `panel_engines.run_backend` adds to every row.
        result.setdefault("decodedSampleCount", Path(row["pcmPath"]).stat().st_size // 2)
        result.setdefault("sampleRateHz", 16_000)
        result["echo"] = {key: row[key] for key in ("language", "referenceText") if key in row}
        emit({"kind": "row", "id": row["id"], "result": result})
    # A real model worker lives far longer than the supervisor's 50 ms sampling
    # period; a fixture answering from a table can exit before the first
    # sample, and an envelope without a sampled peak is a discarded run (CI saw
    # it on a loaded runner). Live a few periods so every launch is measured.
    time.sleep(float(config.get("minimumLifeSeconds", MINIMUM_LIFE_SECONDS)))


PANEL = (*audio_qc_worker.PANEL_ENGINES, "whisper-mlx", "fixture")

if __name__ == "__main__":
    audio_qc_worker.worker_exit(audio_qc_worker.main(engines={**audio_qc_worker.ENGINES,
                                                              **{name: table_engine for name in PANEL}}))
