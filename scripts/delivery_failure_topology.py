#!/usr/bin/env python3
"""Classify retained generation evidence without generating or reading audio.

The topology report is deliberately conservative: a missing WAV is never a
startup diagnosis by itself. Only typed journal/telemetry boundaries can prove
that a request failed before audio materialized; retained QC rejections prove
the opposite boundary.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

SCHEMA_VERSION = 1
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
SAFE_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")

PRE_AUDIO_STAGES = {
    "request_validated",
    "memory_admitted",
    "model_load_started",
    "model_loaded",
    "prewarm_started",
    "prewarm_completed",
    "generation_reserved",
    "audio_consumer_claimed",
    "session_directory_created",
    "engine_opened",
    "first_model_token",
    "first_audio_code_group",
}
AUDIO_STAGES = {"first_decoded_audio_frame", "first_published_stream_chunk", "firstChunk"}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def safe_id(value: Any) -> str | None:
    text = str(value or "")
    return text if SAFE_ID_RE.fullmatch(text) else None


def safe_digest(value: Any) -> str | None:
    text = str(value or "").lower()
    return text if SHA256_RE.fullmatch(text) else None


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError(f"JSONL row {number} is not an object")
        rows.append(value)
    return rows


def stage_name(raw: Any) -> str | None:
    value = str(raw or "")
    if value.startswith("startup."):
        value = value.removeprefix("startup.")
    return value if value in PRE_AUDIO_STAGES | AUDIO_STAGES else None


def terminal_classification(reason: Any, classification: Any = None) -> tuple[str, list[str]] | None:
    """Map only explicit terminal vocabulary; never infer from a missing WAV."""
    reason_value = str(reason or "").lower()
    classification_value = str(classification or "").lower()
    if classification_value == "cancelled" or "cancel" in reason_value:
        return "cancelled", ["typed_terminal_reason"]
    if classification_value == "memory" or "memory" in reason_value or "allocation" in reason_value:
        return "memory_failure", ["typed_terminal_reason"]
    if "timeout" in reason_value or "timed_out" in reason_value:
        return "timeout", ["typed_terminal_reason"]
    if "crash" in reason_value or "signal" in reason_value or "exception" in reason_value:
        return "crash", ["typed_terminal_reason"]
    return None


@dataclass
class Attempt:
    source_kind: str
    source_digest: str
    source_index: int
    generation_id: str | None
    request_digest: str | None
    cell: str | None
    take_index: int | None
    predecessor: str | None
    warm_state: str | None
    retry_attempt: int | None
    classification: str
    confidence: str
    last_boundary: str | None
    reason_code: str | None
    evidence: list[str]

    def identity(self) -> tuple[Any, ...]:
        if self.generation_id is None and self.request_digest is None:
            # Historical schemas may have no request correlation at all. Keep
            # those rows independently represented instead of collapsing every
            # anonymous failure into one synthetic retry history.
            return (self.source_kind, self.source_digest, self.source_index)
        return (
            self.generation_id or self.request_digest,
            self.cell,
            self.take_index,
            self.retry_attempt,
        )

    def as_json(self, scope: str) -> dict[str, Any]:
        return {
            "sourceKind": self.source_kind,
            "sourceSHA256": self.source_digest,
            "sourceIndex": self.source_index,
            "attemptScope": scope,
            "generationID": self.generation_id,
            "requestIdentityDigest": self.request_digest,
            "cell": self.cell,
            "takeIndex": self.take_index,
            "predecessorCell": self.predecessor,
            "warmState": self.warm_state,
            "retryAttempt": self.retry_attempt,
            "classification": self.classification,
            "confidence": self.confidence,
            "lastBoundary": self.last_boundary,
            "reasonCode": self.reason_code,
            "evidence": self.evidence,
        }


def matrix_attempts(path: Path) -> list[Attempt]:
    data = load_json(path)
    if not isinstance(data, dict):
        raise ValueError("matrix report must be an object")
    digest = sha256_file(path)
    failures = list(data.get("referenceFailures") or []) + list(data.get("generationFailures") or [])
    attempts: list[Attempt] = []
    previous: str | None = None
    for index, row in enumerate(failures):
        if not isinstance(row, dict):
            raise ValueError("matrix failure row must be an object")
        reason = safe_id(row.get("reasonCode")) or "unknown"
        has_audio = bool(row.get("rejectedOutputFileName") or row.get("rejectedAnalysis"))
        if has_audio:
            classification, confidence = "post_generation_qc", "source_proven"
            evidence = ["retained_qc_rejection", "materialized_audio_identity"]
            last = "first_published_stream_chunk"
        else:
            classification, confidence = "unmaterialized_unknown", "source_proven"
            evidence = ["failure_row_without_typed_startup_boundary"]
            last = None
        cell = safe_id(row.get("cell"))
        attempts.append(Attempt(
            "delivery_matrix", digest, index,
            safe_id(row.get("generationID")), None, cell,
            row.get("takeIndex") if isinstance(row.get("takeIndex"), int) else None,
            previous, safe_id(row.get("warmState")), None,
            classification, confidence, last, reason, evidence,
        ))
        previous = cell
    return attempts


def experiment_attempts(path: Path) -> list[Attempt]:
    data = load_json(path)
    takes = data.get("takes") if isinstance(data, dict) else None
    if not isinstance(takes, dict):
        raise ValueError("experiment state must contain a takes object")
    digest = sha256_file(path)
    attempts: list[Attempt] = []
    previous: str | None = None
    for index, (key, row) in enumerate(sorted(takes.items())):
        if not isinstance(row, dict):
            raise ValueError("experiment take must be an object")
        status = row.get("status")
        cell = safe_id(key)
        if status == "complete" and safe_digest(row.get("audioSHA256")):
            classification, reason, evidence, last = (
                "success", "complete", ["output_digest", "terminal_complete"],
                "first_published_stream_chunk",
            )
        elif status == "failed":
            classification, reason, evidence, last = (
                "unmaterialized_unknown", "process_failed",
                ["nonzero_process_exit_without_typed_boundary"], None,
            )
        else:
            classification, reason, evidence, last = (
                "unmaterialized_unknown", safe_id(status) or "unknown",
                ["unrepresented_or_nonterminal_state"], None,
            )
        attempts.append(Attempt(
            "delivery_experiment", digest, index,
            safe_id(row.get("generationID")), None, cell, index + 1,
            previous, None, None, classification, "source_proven", last, reason, evidence,
        ))
        previous = cell
    return attempts


def telemetry_attempts(path: Path, expected_run_id: str | None) -> list[Attempt]:
    digest = sha256_file(path)
    attempts: list[Attempt] = []
    previous: str | None = None
    for index, row in enumerate(load_jsonl(path)):
        notes = row.get("notes") if isinstance(row.get("notes"), dict) else {}
        if expected_run_id and notes.get("benchRunID") not in {None, expected_run_id}:
            raise ValueError("telemetry contains a different run identity")
        marks = row.get("stageMarks") if isinstance(row.get("stageMarks"), list) else []
        stages = [stage_name(mark.get("stage")) for mark in marks if isinstance(mark, dict)]
        stages = [value for value in stages if value]
        output = row.get("outputMetrics") if isinstance(row.get("outputMetrics"), dict) else {}
        frames = output.get("frameCount") or (row.get("counters") or {}).get("audioFramesWritten")
        finish = safe_id(row.get("finishReason")) or "unknown"
        terminal = terminal_classification(finish)
        if any(value in AUDIO_STAGES for value in stages) or (isinstance(frames, int) and frames > 0):
            classification = "success" if finish in {"eos", "completed"} else "post_generation_qc"
            evidence = ["typed_audio_boundary"]
        elif terminal:
            classification, evidence = terminal
        elif stages and all(value in PRE_AUDIO_STAGES for value in stages):
            classification, evidence = "pre_audio_startup", ["typed_startup_boundary_without_audio"]
        else:
            classification, evidence = "unmaterialized_unknown", ["no_decision_complete_boundary"]
        receipt = row.get("requestReceipt") if isinstance(row.get("requestReceipt"), dict) else {}
        cell = safe_id(notes.get("benchCell"))
        attempts.append(Attempt(
            "generation_telemetry", digest, index,
            safe_id(row.get("generationID")), safe_digest(receipt.get("requestIdentityDigest")),
            cell, int(notes["benchTakeIndex"]) if str(notes.get("benchTakeIndex", "")).isdigit() else None,
            previous, safe_id((row.get("warmState") or notes.get("benchWarmState"))),
            receipt.get("retryAttempt") if isinstance(receipt.get("retryAttempt"), int) else None,
            classification, "live_reproduced", stages[-1] if stages else None, finish, evidence,
        ))
        previous = cell
    return attempts


def journal_attempts(path: Path) -> list[Attempt]:
    digest = sha256_file(path)
    attempts: list[Attempt] = []
    previous: str | None = None
    for index, row in enumerate(load_jsonl(path)):
        stage = stage_name(row.get("stage"))
        classification_value = row.get("classification")
        error_code = safe_id(row.get("errorCode")) or "unknown"
        terminal = terminal_classification(error_code, classification_value)
        if terminal:
            classification, _ = terminal
        elif stage in PRE_AUDIO_STAGES or row.get("stage") in {"stream_startup", "model_load", "prewarm"}:
            classification = "pre_audio_startup"
        else:
            classification = "unmaterialized_unknown"
        attempts.append(Attempt(
            "failure_journal", digest, index,
            safe_id(row.get("generationID")), safe_digest(row.get("requestIdentityDigest")),
            None, None, previous, None,
            row.get("retryAttempt") if isinstance(row.get("retryAttempt"), int) else None,
            classification, "source_proven", stage, error_code,
            ["allowlisted_failure_journal"],
        ))
    return attempts


def build_report(attempts: list[Attempt]) -> dict[str, Any]:
    last_by_identity: dict[tuple[Any, ...], int] = {}
    for index, attempt in enumerate(attempts):
        last_by_identity[attempt.identity()] = index
    rows = [attempt.as_json(
        "current" if last_by_identity[attempt.identity()] == index else "historical"
    ) for index, attempt in enumerate(attempts)]
    counts: dict[str, int] = {}
    for row in rows:
        counts[row["classification"]] = counts.get(row["classification"], 0) + 1
    return {
        "schemaVersion": SCHEMA_VERSION,
        "status": "complete",
        "attemptCount": len(rows),
        "counts": dict(sorted(counts.items())),
        "attempts": rows,
        "policy": {
            "missingAudioAloneIsStartupFailure": False,
            "requiresTypedBoundaryForPreAudioClassification": True,
        },
    }


def write_report(report: dict[str, Any], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "failure-topology.json"
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    lines = [
        "# Delivery failure topology",
        "",
        f"Attempts: **{report['attemptCount']}**",
        "",
        "| Classification | Count |",
        "| --- | ---: |",
    ]
    lines.extend(f"| {key} | {value} |" for key, value in report["counts"].items())
    lines += [
        "",
        "A missing audio file is classified as unknown unless typed runtime evidence proves the pre-audio boundary.",
        "The JSON report contains only allowlisted identities and digests; source paths, scripts, audio, and raw errors are omitted.",
    ]
    (output_dir / "failure-topology.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--matrix", action="append", default=[], type=Path)
    parser.add_argument("--experiment", action="append", default=[], type=Path)
    parser.add_argument("--telemetry", action="append", default=[], type=Path)
    parser.add_argument("--failure-journal", action="append", default=[], type=Path)
    parser.add_argument("--run-id")
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args(argv)
    if args.run_id and not SAFE_ID_RE.fullmatch(args.run_id):
        parser.error("--run-id must be an opaque allowlisted identifier")
    inputs = args.matrix + args.experiment + args.telemetry + args.failure_journal
    if not inputs:
        parser.error("at least one evidence input is required")
    for path in inputs:
        if not path.is_file():
            parser.error("an evidence input does not exist")

    attempts: list[Attempt] = []
    for path in args.matrix:
        attempts.extend(matrix_attempts(path))
    for path in args.experiment:
        attempts.extend(experiment_attempts(path))
    for path in args.telemetry:
        attempts.extend(telemetry_attempts(path, args.run_id))
    for path in args.failure_journal:
        attempts.extend(journal_attempts(path))
    write_report(build_report(attempts), args.output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
