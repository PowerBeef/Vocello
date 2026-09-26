"""One persistent, supervised worker per judge per run (audit AQ-F42, section 3.4).

`run_persistent_worker` writes the job, admits the worker (when the caller runs
under an orchestrator's `RunAdmission`), launches `scripts/audio_qc_worker.py`
(or any command speaking its JSONL protocol) under the resource supervisor with
the judge's ceiling, and reads the rows it emitted:

- A clean, qualified run accepts every emitted row.
- A worker that ended abnormally mid-job (a crash, a timeout or a ceiling
  breach) keeps the rows it had emitted; the remainder is retried once in a
  fresh worker, and the retry is recorded as its own launch. A row the retry
  does not complete either is `unavailable` (`crash`, `timeout` or
  `envelope-breach`).
- A run whose envelope failed a host condition (pressure, swap, post-exit
  recovery or a probe) accepts nothing: its rows are `unavailable`
  (`envelope-breach`) and nothing is retried, since a retry would not change
  the host.
- A row the engine reports it could not analyze is `unavailable`
  (`analysis-failed`, or the reason the engine gave) and is not retried.

Accepted rows are what the caller may cache (L1); unavailable rows never are.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from audio_qc_worker import JOB_KIND, PROTOCOL, thread_environment
from delivery_resource_supervisor import WHOLE_HOST_RECOVERY_RULE, run_supervised

# Failures that mean the worker did not finish its job normally. Rows it
# emitted before are kept when these are the only failures.
ABNORMAL_END_FAILURES = frozenset({
    "timeout", "nonzero-exit", "resource-limit-termination",
    "provisional-rss-ceiling-exceeded", "provisional-physical-footprint-ceiling-exceeded",
})
# A worker that died before its first sample has no measured peak; that gap is
# part of the crash, not a separate host condition.
SHORT_LIFE_MEASUREMENT_GAPS = frozenset({"peak-rss-unavailable", "physical-footprint-unavailable"})
ROW_ERROR_REASONS = frozenset({"analysis-failed", "timeout", "envelope-breach"})
DEFAULT_TIMEOUT_SECONDS = 900.0


class WorkerProtocolError(ValueError):
    """The worker's output does not follow the JSONL protocol."""


@dataclass(frozen=True)
class WorkerSpec:
    judge_id: str
    engine: str
    command: tuple[str, ...]
    threads: int
    lane: str
    ceiling_bytes: int
    engine_config: Mapping[str, Any] = field(default_factory=dict)
    measure_physical_footprint: bool = False
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    environment: Mapping[str, str] | None = None


@dataclass
class WorkerOutcome:
    judge_id: str
    results: dict[str, dict[str, Any]] = field(default_factory=dict)
    unavailable: dict[str, str] = field(default_factory=dict)
    launches: list[dict[str, Any]] = field(default_factory=list)
    # The launch (1 or 2) whose worker emitted each accepted row.
    row_launch: dict[str, int] = field(default_factory=dict)
    ready: dict[str, Any] | None = None

    def report(self) -> dict[str, Any]:
        return {
            "judge": self.judge_id,
            "launches": self.launches,
            "rowsAccepted": len(self.results),
            "rowsUnavailable": dict(sorted(self.unavailable.items())),
            "modelLoadSeconds": (self.ready or {}).get("modelLoadSeconds"),
            "warmupSeconds": (self.ready or {}).get("warmupSeconds"),
        }


@dataclass
class ParsedStream:
    ready: dict[str, Any] | None
    rows: dict[str, dict[str, Any]]
    row_errors: dict[str, str]
    child_peaks: dict[str, int]
    done: bool


def parse_worker_stream(stdout: bytes, expected: Sequence[str]) -> ParsedStream:
    """Parse the complete lines of a worker's stdout; a torn last line is ignored."""
    wanted = set(expected)
    parsed = ParsedStream(None, {}, {}, {}, False)
    lines = stdout.split(b"\n")
    for raw in lines[:-1]:  # the element after the last newline is incomplete
        if not raw.strip():
            continue
        try:
            item = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise WorkerProtocolError("a worker line is not one JSON object") from error
        if not isinstance(item, dict):
            raise WorkerProtocolError("a worker line is not one JSON object")
        kind = item.get("kind")
        if kind == "ready":
            parsed.ready = {key: item.get(key) for key in ("engine", "threads", "modelLoadSeconds", "warmupSeconds")}
            continue
        if kind == "done":
            parsed.done = True
            continue
        identity = item.get("id")
        if kind not in ("row", "row-error") or identity not in wanted:
            raise WorkerProtocolError("a worker emitted an unknown line or row")
        if identity in parsed.rows or identity in parsed.row_errors:
            raise WorkerProtocolError("a worker emitted one row twice")
        peak = item.get("childMaxRSSBytes")
        if type(peak) is int and peak > 0:
            parsed.child_peaks[identity] = peak
        if kind == "row":
            if not isinstance(item.get("result"), dict):
                raise WorkerProtocolError("a worker row carries no result object")
            parsed.rows[identity] = item["result"]
        else:
            reason = item.get("reason")
            parsed.row_errors[identity] = reason if reason in ROW_ERROR_REASONS else "analysis-failed"
    return parsed


CEILING_FAILURES = frozenset({
    "resource-limit-termination", "provisional-rss-ceiling-exceeded",
    "provisional-physical-footprint-ceiling-exceeded",
})


def host_condition_failed(failures: set[str]) -> bool:
    """True when the envelope failed something other than the worker ending abnormally."""
    tolerated = set(ABNORMAL_END_FAILURES)
    if failures & {"timeout", "nonzero-exit", "resource-limit-termination"}:
        tolerated |= SHORT_LIFE_MEASUREMENT_GAPS
    return bool(failures - tolerated)


def _unavailable_reason(failures: set[str]) -> str:
    """Why rows a retried worker still did not complete are unavailable."""
    if "timeout" in failures:
        return "timeout"
    if failures & CEILING_FAILURES:
        return "envelope-breach"
    return "crash"


def run_persistent_worker(
    spec: WorkerSpec, rows: Sequence[Mapping[str, Any]], *, workdir: Path, lock_root: Path,
    run_admission: Any | None = None, judge_admission: Any | None = None,
    supervisor: Callable[..., Any] = run_supervised,
    recovery_rule: str = WHOLE_HOST_RECOVERY_RULE,
    supervisor_options: Mapping[str, Any] | None = None,
) -> WorkerOutcome:
    """Run one judge's rows through one worker (plus at most one recorded retry)."""
    if run_admission is not None and judge_admission is None:
        raise ValueError("an admitted worker needs its judge admission")
    if judge_admission is not None and judge_admission.ceiling_bytes != spec.ceiling_bytes:
        raise ValueError("a worker's ceiling must be its admitted ceiling")
    identities = [str(row["id"]) for row in rows]
    if len(set(identities)) != len(identities):
        raise ValueError("worker rows need unique identities")
    outcome = WorkerOutcome(spec.judge_id)
    pending = [dict(row) for row in rows]
    workdir.mkdir(parents=True, exist_ok=True)
    for attempt in (0, 1):
        if not pending:
            break
        job_path = workdir / f"{spec.judge_id.replace('@', '-')}-launch-{attempt + 1}.json"
        job_path.write_text(json.dumps({
            "schemaVersion": 1, "kind": JOB_KIND, "protocol": PROTOCOL,
            "judge": spec.judge_id, "engine": spec.engine, "threads": spec.threads,
            "engineConfig": dict(spec.engine_config), "rows": pending,
        }, ensure_ascii=False), encoding="utf-8")
        environment = {**os.environ, **dict(spec.environment or {}), **thread_environment(spec.threads)}
        ticket = run_admission.admit(judge_admission) if run_admission is not None else None
        try:
            result = supervisor(
                [*spec.command, "--job", str(job_path)], lock_root=lock_root,
                timeout_seconds=spec.timeout_seconds,
                maximum_rss_bytes=spec.ceiling_bytes, maximum_physical_footprint_bytes=spec.ceiling_bytes,
                measure_physical_footprint=spec.measure_physical_footprint,
                environment=environment, admission=ticket, recovery_rule=recovery_rule,
                **dict(supervisor_options or {}),
            )
        finally:
            if ticket is not None:
                ticket.release()
        envelope = result.report
        failures = set(envelope.get("qualificationFailures") or [])
        expected = [str(row["id"]) for row in pending]
        protocol_error = None
        try:
            parsed = parse_worker_stream(result.stdout, expected)
        except WorkerProtocolError as error:
            protocol_error = str(error)
            parsed = ParsedStream(None, {}, {}, {}, False)
        if outcome.ready is None and parsed.ready is not None:
            outcome.ready = parsed.ready
        completed = parsed.done and envelope.get("returnCode") == 0
        host_condition = host_condition_failed(failures)
        accepted = 0
        if not host_condition and protocol_error is None:
            for identity, value in parsed.rows.items():
                peak = parsed.child_peaks.get(identity)
                if peak is not None and peak > spec.ceiling_bytes:
                    outcome.unavailable[identity] = "envelope-breach"
                    continue
                outcome.results[identity] = value
                outcome.row_launch[identity] = attempt + 1
                accepted += 1
            for identity, reason in parsed.row_errors.items():
                outcome.unavailable[identity] = reason
        outcome.launches.append({
            "launch": attempt + 1,
            "retry": attempt > 0,
            "rows": len(pending),
            "rowsEmitted": len(parsed.rows),
            "rowsAccepted": accepted,
            "rowErrors": len(parsed.row_errors),
            "completed": completed,
            "protocolError": protocol_error is not None,
            "descendantPeakRSSBytes": max(parsed.child_peaks.values(), default=None),
            "resourceEnvelope": envelope,
        })
        remaining = [row for row in pending
                     if str(row["id"]) not in outcome.results and str(row["id"]) not in outcome.unavailable]
        if host_condition:
            for row in remaining:
                outcome.unavailable[str(row["id"])] = "envelope-breach"
            break
        if not remaining:
            break
        if attempt == 1:
            reason = "crash" if protocol_error else _unavailable_reason(failures)
            for row in remaining:
                outcome.unavailable[str(row["id"])] = reason
            break
        pending = remaining
    return outcome
