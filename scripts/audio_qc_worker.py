#!/usr/bin/env python3
"""The persistent audio QC worker: one process per judge per run (audit AQ-F42, section 3.4).

The orchestrator (`scripts/audio_qc_orchestrator.py`) and the compact-adapter
batch path launch this file once per judge per run, supervised and admitted,
after the generator has exited. It loads its model once, warms it, streams the
job's rows and exits at the end of the job. It is never a daemon spanning runs.

Protocol (`audio-qc-worker-jsonl/1`): the job is a JSON file
(`--job`, kind `audio-qc-worker-job`); stdout carries one JSON object per line:

- `{"kind": "ready", ...}` once, after the model loaded and warmed;
- `{"kind": "row", "id": ..., "result": {...}}` per completed row;
- `{"kind": "row-error", "id": ..., "reason": ...}` for a row the engine
  could not analyze (the row is unavailable; the worker carries on);
- `{"kind": "done", "rows": n}` last.

A crash leaves the rows already emitted intact; the runner
(`lib.qc_pipeline.workers`) keeps them and retries the remainder once in a
fresh worker. Nothing here prints paths or transcripts anywhere but stdout.

Thread counts are declared per judge in the registry and fixed by the
launcher's environment before this interpreter starts (`OMP_NUM_THREADS` and
friends); the job repeats the count and the worker refuses a mismatch, so the
count recorded in the judge's output identity is the one that ran.

Engines:

- `whisper-mlx`: the pinned whisper-small MLX recognizer of
  `independent_asr_worker.py` (loaded once; each row decodes the canonical
  16 kHz PCM locked to its language and detects the language from the first
  30 s, exactly as that worker does).
- `native-command`: a pinned native binary that analyzes one file per
  invocation (the SenseVoice Q8 llama.cpp runtime). The command template is the
  adapter configuration's, with `{audio}` bound per row to a canonical WAV. The
  binary loads its model on every invocation: only the supervision and the
  admission are per run for this engine. Each invocation stays in this
  worker's process group, which the supervisor samples live: the judge's
  ceiling binds the worker and the binary together while the binary runs, and
  a breach terminates the whole group. Each invocation is also reaped with
  `wait4` and its peak resident memory reported per row (`childMaxRSSBytes`),
  a second, per-row check. Its timeout is the job's per-row budget
  (`rowTimeoutSeconds`).

Rows are analyzed in job order, so the runner can name the row in flight when
a worker ends abnormally. A row's `wallSeconds` is timing, which the runner
keeps beside the result, never in what it caches.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from typing import Any, Callable
import wave

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

PROTOCOL = "audio-qc-worker-jsonl/1"
JOB_KIND = "audio-qc-worker-job"
THREAD_ENVIRONMENT = (
    "OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "VECLIB_MAXIMUM_THREADS",
    "NUMEXPR_NUM_THREADS",
)
THREADS_VARIABLE = "VOCELLO_AUDIO_QC_THREADS"
CANONICAL_SAMPLE_RATE = 16_000
NATIVE_ROW_TIMEOUT_SECONDS = 600.0
REAP_POLL_SECONDS = 0.01


class WorkerJobError(ValueError):
    """The job is malformed or does not match this process."""


Emit = Callable[[dict[str, Any]], None]


def thread_environment(threads: int) -> dict[str, str]:
    """The environment that fixes a worker's numerical thread count before it starts."""
    if type(threads) is not int or threads <= 0:
        raise WorkerJobError("a worker's thread count must be a positive integer")
    return {**{name: str(threads) for name in THREAD_ENVIRONMENT}, THREADS_VARIABLE: str(threads)}


def validate_job(job: Any, environment: dict[str, str] | None = None) -> dict[str, Any]:
    environment = os.environ if environment is None else environment
    if not isinstance(job, dict) or job.get("kind") != JOB_KIND or job.get("protocol") != PROTOCOL:
        raise WorkerJobError(f"the job is not a {JOB_KIND} ({PROTOCOL})")
    rows = job.get("rows")
    if not isinstance(rows, list) or not rows:
        raise WorkerJobError("the job has no rows")
    identities = [row.get("id") if isinstance(row, dict) else None for row in rows]
    if any(not isinstance(identity, str) or not identity for identity in identities) or len(set(identities)) != len(identities):
        raise WorkerJobError("job rows need unique string identities")
    threads = job.get("threads")
    expected = thread_environment(threads) if type(threads) is int and threads > 0 else None
    if expected is None or any(environment.get(name) != value for name, value in expected.items()):
        raise WorkerJobError("the worker's thread environment differs from the job's declared thread count")
    if not isinstance(job.get("engineConfig"), dict):
        raise WorkerJobError("the job has no engine configuration")
    return job


def _emitter(stream: Any) -> Emit:
    def emit(payload: dict[str, Any]) -> None:
        stream.write(json.dumps(payload, ensure_ascii=False, sort_keys=True, allow_nan=False))
        stream.write("\n")
        stream.flush()
    return emit


# --------------------------------------------------------------------------- #
# Engines
# --------------------------------------------------------------------------- #

def whisper_mlx(job: dict[str, Any], emit: Emit) -> None:
    from independent_asr_worker import Recognizer, read_pcm16

    config = job["engineConfig"]
    rows = job["rows"]
    weights = config.get("weights")
    if not isinstance(weights, str) or not weights:
        raise WorkerJobError("the whisper engine needs its pinned weights")
    recognizer = Recognizer(
        Path(weights).parent, config.get("decodeOptions") or {},
        warmup_language=rows[0].get("language"),
    )
    emit({
        "kind": "ready", "engine": "whisper-mlx", "threads": job["threads"],
        "modelLoadSeconds": recognizer.model_load_seconds, "warmupSeconds": recognizer.warmup_seconds,
    })
    for row in rows:
        try:
            audio = read_pcm16(Path(str(row["pcmPath"])))
            result = recognizer.recognize(audio, row.get("language"))
        except (OSError, ValueError, KeyError):
            emit({"kind": "row-error", "id": row["id"], "reason": "analysis-failed"})
            continue
        emit({"kind": "row", "id": row["id"], "result": result})


def _canonical_wav(pcm: Path, destination: Path) -> None:
    with wave.open(str(destination), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(CANONICAL_SAMPLE_RATE)
        with pcm.open("rb") as source:
            for block in iter(lambda: source.read(1024 * 1024), b""):
                output.writeframesraw(block)


def _max_rss_bytes(usage: Any) -> int | None:
    value = getattr(usage, "ru_maxrss", None)
    if type(value) is not int or value <= 0:
        return None
    return value if sys.platform == "darwin" else value * 1024


def run_reaped(argv: list[str], *, timeout_seconds: float) -> tuple[int | None, bytes, int | None]:
    """Run one invocation and reap it with `wait4`: (return code, stdout, peak RSS bytes)."""
    with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
        process = subprocess.Popen(argv, stdout=stdout, stderr=stderr)
        deadline = time.monotonic() + timeout_seconds
        timed_out = False
        while True:
            pid, status, usage = os.wait4(process.pid, os.WNOHANG)
            if pid:
                break
            if time.monotonic() >= deadline:
                timed_out = True
                process.kill()
                _pid, status, usage = os.wait4(process.pid, 0)
                break
            time.sleep(REAP_POLL_SECONDS)
        # Reaped here, so Popen never waits on it again.
        process.returncode = os.waitstatus_to_exitcode(status)
        stdout.seek(0)
        return (None if timed_out else process.returncode), stdout.read(), _max_rss_bytes(usage)


def native_command(job: dict[str, Any], emit: Emit) -> None:
    config = job["engineConfig"]
    command = config.get("command")
    if (not isinstance(command, list) or not command or any(not isinstance(item, str) for item in command)
            or sum(item.count("{audio}") for item in command) != 1):
        raise WorkerJobError("the native engine needs a command template that binds {audio} once")
    ceiling = config.get("ceilingBytes")
    timeout = float(config.get("rowTimeoutSeconds") or NATIVE_ROW_TIMEOUT_SECONDS)
    emit({"kind": "ready", "engine": "native-command", "threads": job["threads"],
          "modelLoadSeconds": None, "warmupSeconds": None})
    with tempfile.TemporaryDirectory(prefix="vocello-audio-qc-native-") as temporary:
        model_input = Path(temporary) / "canonical.wav"
        for row in job["rows"]:
            try:
                _canonical_wav(Path(str(row["pcmPath"])), model_input)
            except (OSError, KeyError, wave.Error):
                emit({"kind": "row-error", "id": row["id"], "reason": "analysis-failed"})
                continue
            started = time.monotonic()
            code, stdout, peak = run_reaped(
                [item.replace("{audio}", str(model_input)) for item in command], timeout_seconds=timeout,
            )
            wall = time.monotonic() - started
            if type(ceiling) is int and peak is not None and peak > ceiling:
                emit({"kind": "row-error", "id": row["id"], "reason": "envelope-breach",
                      "childMaxRSSBytes": peak})
                continue
            if code != 0:
                emit({"kind": "row-error", "id": row["id"],
                      "reason": "timeout" if code is None else "analysis-failed", "childMaxRSSBytes": peak})
                continue
            try:
                text = stdout.decode("utf-8")
            except UnicodeDecodeError:
                emit({"kind": "row-error", "id": row["id"], "reason": "analysis-failed", "childMaxRSSBytes": peak})
                continue
            emit({"kind": "row", "id": row["id"], "childMaxRSSBytes": peak,
                  "result": {"stdout": text, "wallSeconds": wall}})


ENGINES: dict[str, Callable[[dict[str, Any], Emit], None]] = {
    "whisper-mlx": whisper_mlx,
    "native-command": native_command,
}


def run(job: dict[str, Any], *, emit: Emit, engines: dict[str, Callable[[dict[str, Any], Emit], None]] = ENGINES,
        environment: dict[str, str] | None = None) -> None:
    job = validate_job(job, environment)
    engine = engines.get(job.get("engine"))
    if engine is None:
        raise WorkerJobError(f"unknown worker engine {job.get('engine')!r}")
    engine(job, emit)
    emit({"kind": "done", "rows": len(job["rows"])})


def main(argv: list[str] | None = None, *,
         engines: dict[str, Callable[[dict[str, Any], Emit], None]] = ENGINES) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--job", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        job = json.loads(args.job.read_text(encoding="utf-8"))
        run(job, emit=_emitter(sys.stdout), engines=engines)
    except (WorkerJobError, OSError, ValueError, KeyError) as error:
        print(f"audio-qc-worker: FAIL\n{type(error).__name__}: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
