#!/usr/bin/env python3
"""Validate the physical-iPhone smoke memory-pressure proof.

The XCUITest runner pulls the app-container diagnostics mirror after the smoke
scenario. This validator selects only the collision-resistant run requested by
the caller, accepts semantically identical duplicate mirrors, and rejects
partial/divergent evidence. It emits a compact privacy-safe summary; raw paths
and telemetry remain local and untracked.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import sys
from typing import Any, Iterable


SAFE_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,95}$")
REQUIRED_EVENTS = (
    "debug_force_critical_once",
    "critical_memory_action",
    "critical_generation_cancel",
    "critical_full_unload",
)
SUCCESS_FINISH_REASONS = {"eos", "maxtokens", "completed", "complete", "success", "ok"}
CANCELLED_FINISH_REASONS = {"cancelled", "canceled"}
MAX_JSONL_BYTES = 64 * 1024 * 1024


class IOSSmokeAcceptanceError(ValueError):
    """Evidence is missing, ambiguous, malformed, or does not prove the scenario."""


def _safe_timestamp(value: Any, field: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise IOSSmokeAcceptanceError(f"{field} is missing")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise IOSSmokeAcceptanceError(f"{field} is not an ISO-8601 timestamp") from error
    if parsed.tzinfo is None:
        raise IOSSmokeAcceptanceError(f"{field} must include a timezone")
    return parsed.astimezone(timezone.utc)


def _load_jsonl(path: Path, label: str) -> list[dict[str, Any]]:
    if path.is_symlink() or not path.is_file():
        raise IOSSmokeAcceptanceError(f"{label} evidence must be one regular file")
    try:
        if path.stat().st_size > MAX_JSONL_BYTES:
            raise IOSSmokeAcceptanceError(f"{label} evidence exceeds the bounded size limit")
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise IOSSmokeAcceptanceError(f"{label} evidence could not be read") from error

    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as error:
            raise IOSSmokeAcceptanceError(
                f"{label} evidence contains invalid JSON at line {line_number}"
            ) from error
        if not isinstance(row, dict):
            raise IOSSmokeAcceptanceError(
                f"{label} evidence line {line_number} is not an object"
            )
        rows.append(row)
    if not rows:
        raise IOSSmokeAcceptanceError(f"{label} evidence is empty")
    return rows


def _canonical_digest(rows: Iterable[dict[str, Any]]) -> str:
    encoded = json.dumps(
        list(rows),
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _select_memory_rows(root: Path, run_id: str) -> tuple[list[dict[str, Any]], int]:
    candidates = sorted(
        path
        for path in root.rglob("memory-contexts.jsonl")
        if path.parent.name == run_id
    )
    if not candidates:
        raise IOSSmokeAcceptanceError("run-scoped memory-contexts evidence is missing")

    mirrors: dict[str, list[dict[str, Any]]] = {}
    for path in candidates:
        rows = _load_jsonl(path, "memory-contexts")
        if any(row.get("runID") != run_id for row in rows):
            raise IOSSmokeAcceptanceError("memory-contexts evidence mixes run identities")
        mirrors.setdefault(_canonical_digest(rows), rows)
    if len(mirrors) != 1:
        raise IOSSmokeAcceptanceError("run-scoped memory-contexts mirrors diverge")
    return next(iter(mirrors.values())), len(candidates)


def _validate_memory_sequence(rows: list[dict[str, Any]]) -> tuple[datetime, datetime]:
    events = [row.get("event") for row in rows]
    if any(
        isinstance(event, str)
        and (event == "cancel_failed" or event.endswith("_cancel_failed"))
        for event in events
    ):
        raise IOSSmokeAcceptanceError("memory-pressure cancellation reported cancel_failed")

    required_rows: list[dict[str, Any]] = []
    required_indices: list[int] = []
    for event in REQUIRED_EVENTS:
        matches = [index for index, value in enumerate(events) if value == event]
        if len(matches) != 1:
            raise IOSSmokeAcceptanceError(f"expected exactly one {event} event")
        required_indices.append(matches[0])
        required_rows.append(rows[matches[0]])
    if required_indices != sorted(required_indices):
        raise IOSSmokeAcceptanceError("memory-pressure events are out of order")

    uptimes: list[float] = []
    timestamps: list[datetime] = []
    for event, row in zip(REQUIRED_EVENTS, required_rows):
        uptime = row.get("processUptimeSeconds")
        if (
            not isinstance(uptime, (int, float))
            or isinstance(uptime, bool)
            or not math.isfinite(float(uptime))
            or float(uptime) < 0
        ):
            raise IOSSmokeAcceptanceError(f"{event} has invalid process uptime")
        uptimes.append(float(uptime))
        timestamps.append(_safe_timestamp(row.get("recordedAt"), f"{event}.recordedAt"))
    if any(later < earlier for earlier, later in zip(uptimes, uptimes[1:])):
        raise IOSSmokeAcceptanceError("memory-pressure event uptime regressed")
    if any(later < earlier for earlier, later in zip(timestamps, timestamps[1:])):
        raise IOSSmokeAcceptanceError("memory-pressure event timestamps regressed")

    if required_rows[2].get("reason") != "memory_pressure":
        raise IOSSmokeAcceptanceError("critical cancellation reason is not memory_pressure")
    if required_rows[3].get("trimLevel") != "fullUnload":
        raise IOSSmokeAcceptanceError("critical pressure did not record a fullUnload trim")
    return timestamps[0], timestamps[3]


def _normal_finish_reason(value: Any) -> str:
    return str(value or "").replace("_", "").lower()


def _select_app_rows(root: Path, run_id: str) -> tuple[list[dict[str, Any]], int]:
    mirrors: dict[str, list[dict[str, Any]]] = {}
    candidate_count = 0
    for path in sorted(root.rglob("generations.jsonl")):
        if path.parent.name != "app":
            continue
        rows = _load_jsonl(path, "app generations")
        selected = [
            row
            for row in rows
            if isinstance(row.get("notes"), dict)
            and row["notes"].get("benchRunID") == run_id
        ]
        if not selected:
            continue
        candidate_count += 1
        mirrors.setdefault(_canonical_digest(selected), selected)
    if not mirrors:
        raise IOSSmokeAcceptanceError("run-scoped app telemetry is missing")
    if len(mirrors) != 1:
        raise IOSSmokeAcceptanceError("run-scoped app telemetry mirrors diverge")
    return next(iter(mirrors.values())), candidate_count


def _validate_post_pressure_reuse(
    rows: list[dict[str, Any]],
    *,
    run_id: str,
    critical_signal_at: datetime,
    full_unload_at: datetime,
) -> tuple[str, datetime, int]:
    successful_after: list[tuple[datetime, dict[str, Any]]] = []
    cancelled_rows: list[tuple[int, datetime]] = []
    for row_index, row in enumerate(rows):
        if not isinstance(row.get("schemaVersion"), int) or row["schemaVersion"] < 8:
            raise IOSSmokeAcceptanceError("app telemetry must use schema v8 or newer")
        if row.get("layer") != "app":
            raise IOSSmokeAcceptanceError("selected app telemetry has the wrong layer")
        notes = row.get("notes")
        if not isinstance(notes, dict) or notes.get("benchRunID") != run_id:
            raise IOSSmokeAcceptanceError("selected app telemetry has the wrong run identity")
        recorded_at = _safe_timestamp(row.get("recordedAt"), "app.recordedAt")
        finish_reason = _normal_finish_reason(row.get("finishReason"))
        if finish_reason in CANCELLED_FINISH_REASONS:
            cancelled_rows.append((row_index, recorded_at))
        if (
            recorded_at > full_unload_at
            and finish_reason in SUCCESS_FINISH_REASONS
        ):
            successful_after.append((recorded_at, row))

    if len(cancelled_rows) != 2:
        raise IOSSmokeAcceptanceError(
            "expected exactly two app cancellations for the user and memory-pressure paths"
        )
    (_, user_cancelled_at), (_, memory_cancelled_at) = cancelled_rows
    if user_cancelled_at > critical_signal_at:
        raise IOSSmokeAcceptanceError(
            "visible user cancellation did not precede the critical signal"
        )
    if not critical_signal_at <= memory_cancelled_at <= full_unload_at:
        raise IOSSmokeAcceptanceError(
            "memory-pressure app cancellation is outside the critical handling interval"
        )
    if not successful_after:
        raise IOSSmokeAcceptanceError(
            "no successful app generation completed after the critical full unload"
        )
    successful_after.sort(key=lambda item: item[0])
    recorded_at, row = successful_after[0]
    generation_id = row.get("generationID")
    if not isinstance(generation_id, str) or not generation_id:
        raise IOSSmokeAcceptanceError("post-pressure app generation ID is missing")
    return generation_id, recorded_at, len(cancelled_rows)


def validate(root: Path, run_id: str) -> dict[str, Any]:
    if SAFE_RUN_ID.fullmatch(run_id) is None:
        raise IOSSmokeAcceptanceError("run ID is not a privacy-safe diagnostic identifier")
    if root.is_symlink() or not root.is_dir():
        raise IOSSmokeAcceptanceError("diagnostics root is not one regular directory")

    memory_rows, memory_mirror_count = _select_memory_rows(root, run_id)
    critical_signal_at, full_unload_at = _validate_memory_sequence(memory_rows)
    app_rows, app_mirror_count = _select_app_rows(root, run_id)
    generation_id, completed_at, cancelled_generation_count = _validate_post_pressure_reuse(
        app_rows,
        run_id=run_id,
        critical_signal_at=critical_signal_at,
        full_unload_at=full_unload_at,
    )
    return {
        "schemaVersion": 1,
        "status": "pass",
        "runID": run_id,
        "orderedEvents": list(REQUIRED_EVENTS),
        "cancellationReason": "memory_pressure",
        "trimLevel": "fullUnload",
        "memoryMirrorCount": memory_mirror_count,
        "appMirrorCount": app_mirror_count,
        "cancelledGenerationCount": cancelled_generation_count,
        "postPressureGenerationID": generation_id,
        "postPressureCompletedAt": completed_at.isoformat().replace("+00:00", "Z"),
    }


def validate_history_observation(root: Path, run_id: str, row_id: str) -> dict[str, Any]:
    """Collect one private XCUI value; do not turn observation into audio acceptance."""
    if not SAFE_RUN_ID.fullmatch(run_id) or not re.fullmatch(r"generation-[0-9]+", row_id):
        raise IOSSmokeAcceptanceError("invalid observation identity")
    try:
        manifest_path = root / "manifest.json"
        if root.is_symlink() or manifest_path.is_symlink() or manifest_path.stat().st_size > 8 * 1024 * 1024:
            raise IOSSmokeAcceptanceError("invalid attachment manifest file")
        manifest = json.loads(manifest_path.read_text())
        if not isinstance(manifest, list) or any(
            not isinstance(test, dict) or not isinstance(test.get("attachments", []), list)
            or any(not isinstance(item, dict) for item in test.get("attachments", []))
            for test in manifest
        ):
            raise IOSSmokeAcceptanceError("invalid attachment manifest")
        pattern = re.compile(r"history-transcript-observation(?:_[0-9]+_[0-9A-Fa-f-]+)?(?:\.json)?")
        matches = [
            attachment for test in manifest for attachment in test.get("attachments", [])
            if pattern.fullmatch(str(attachment.get("suggestedHumanReadableName", "")))
        ]
        if len(matches) != 1:
            raise IOSSmokeAcceptanceError("expected exactly one History observation attachment")
        name = matches[0]["exportedFileName"]
        if Path(name).name != name:
            raise IOSSmokeAcceptanceError("invalid attachment name")
        path = root / name
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 256 * 1024:
            raise IOSSmokeAcceptanceError("invalid observation attachment")
        data = path.read_bytes()
        row = json.loads(data)
        if not isinstance(row, dict) or type(row.get("schemaVersion")) is not int or row.get("schemaVersion") != 1 or row.get("runID") != run_id or row.get("rowID") != row_id:
            raise IOSSmokeAcceptanceError("History observation identity mismatch")
        transcript = row.get("observedTranscript")
        if not isinstance(transcript, str) or not transcript:
            raise IOSSmokeAcceptanceError("missing History transcript value")
        transcript_bytes = transcript.encode("utf-8")
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise IOSSmokeAcceptanceError("History observation could not be validated") from error
    return {
        "schemaVersion": 1, "status": "observed", "runID": run_id, "rowID": row_id,
        "evidenceClass": "read-only-history-observation",
        "transcriptSHA256": hashlib.sha256(transcript_bytes).hexdigest(),
        "transcriptCharacterCount": len(transcript),
        "attachmentSHA256": hashlib.sha256(data).hexdigest(),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="validate run-scoped physical-iPhone smoke memory-pressure evidence"
    )
    parser.add_argument("diagnostics_root", type=Path)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--history-row-id")
    args = parser.parse_args(argv)
    try:
        result = (
            validate_history_observation(args.diagnostics_root, args.run_id, args.history_row_id)
            if args.history_row_id else validate(args.diagnostics_root, args.run_id)
        )
    except IOSSmokeAcceptanceError as error:
        print(f"iOS smoke acceptance FAIL: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
