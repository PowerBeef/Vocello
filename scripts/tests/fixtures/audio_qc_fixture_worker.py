#!/usr/bin/env python3
"""A test-only worker for `audio_qc_worker.py`'s protocol: no model, deterministic rows.

It runs the real worker host (`audio_qc_worker.main`) with one extra engine,
`fixture`, whose job configuration maps each row's canonical PCM SHA-256 to
the raw result a recognizer would emit. Knobs exercise the runner's crash,
timeout and timing handling:

- `crashOnce`: the SHA-256 of a PCM whose row makes the first launch exit
  abruptly (a marker file records that the crash happened, so the retry
  proceeds).
- `crashAlways`: a PCM SHA-256 whose row crashes every launch.
- `rowError`: a PCM SHA-256 the engine reports it cannot analyze.
- `hangOn`: a PCM SHA-256 whose row never finishes (until the timeout).
- `sleepPerRow`: seconds each row takes.
- `measureWall`: report each row's real wall time, as a recognizer does, so
  two runs of one row differ in timing only.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import audio_qc_worker  # noqa: E402


def fixture_engine(job, emit) -> None:
    config = job["engineConfig"]
    table = config.get("table") or {}
    emit({"kind": "ready", "engine": "fixture", "threads": job["threads"],
          "modelLoadSeconds": 0.0, "warmupSeconds": 0.0})
    marker = Path(config["crashMarker"]) if config.get("crashMarker") else None
    sleep = float(config.get("sleepPerRow") or 0.0)
    for row in job["rows"]:
        started = time.monotonic()
        digest = hashlib.sha256(Path(row["pcmPath"]).read_bytes()).hexdigest()
        if digest == config.get("crashAlways"):
            os._exit(3)
        if digest == config.get("crashOnce") and marker is not None and not marker.exists():
            marker.write_text("crashed\n", encoding="utf-8")
            os._exit(3)
        if digest == config.get("hangOn"):
            time.sleep(3600)
        if digest == config.get("rowError"):
            emit({"kind": "row-error", "id": row["id"], "reason": "analysis-failed"})
            continue
        if sleep:
            time.sleep(sleep)
        result = dict(table[digest])
        result.setdefault("decodedSampleCount", Path(row["pcmPath"]).stat().st_size // 2)
        result.setdefault("sampleRateHz", 16_000)
        result.setdefault("language", row.get("language"))
        if config.get("measureWall"):
            result["wallSeconds"] = time.monotonic() - started
        emit({"kind": "row", "id": row["id"], "result": result})


if __name__ == "__main__":
    raise SystemExit(audio_qc_worker.main(engines={**audio_qc_worker.ENGINES, "fixture": fixture_engine}))
