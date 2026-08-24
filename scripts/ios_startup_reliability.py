#!/usr/bin/env python3
"""Validate and compose privacy-safe iOS startup reliability diagnostics."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import tempfile
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_VERSION = 1
SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,95}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
DELIVERY = re.compile(r"^(neutral|happy|sad|angry|fearful|surprised|calm|whisper)\.(normal|strong)$")
SPEAKERS = {"aiden", "ryan", "vivian", "serena", "uncle_fu", "dylan", "eric", "ono_anna", "sohee"}
LANGUAGES = {"auto", "english", "chinese", "japanese", "korean", "french", "german", "spanish", "portuguese", "russian", "italian"}
VARIATIONS = {"expressive", "balanced", "consistent"}
PREPARATIONS = {"production", "full_runtime_unload", "prepared_cache_clear", "prewarm_disabled"}
CLASSIFICATIONS = {"success", "pre_audio_startup", "post_generation_qc", "timeout", "cancelled", "memory_failure", "crash", "unmaterialized_unknown"}
BOUNDARIES = {"request_validated", "memory_admitted", "model_load_started", "model_loaded", "prewarm_started", "prewarm_completed", "generation_reserved", "audio_consumer_claimed", "session_directory_created", "engine_opened", "first_model_token", "first_audio_code_group", "first_decoded_audio_frame", "first_published_stream_chunk"}
BOUNDARY_ORDER = (
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
    "first_decoded_audio_frame",
    "first_published_stream_chunk",
)
REQUIRED_PASS_BOUNDARIES = frozenset(BOUNDARY_ORDER[:-1])
FORBIDDEN_KEYS = {"script", "text", "path", "url", "error", "message", "deviceID", "deviceName"}
UI_MANIFEST = re.compile(
    r"VOCELLO-STARTUP-PARITY-UI-MANIFEST "
    r"runID=(?P<run>[A-Za-z0-9._-]+) generationID=(?P<generation>[0-9A-Fa-f-]{36}) "
    r"speakerID=(?P<speaker>[a-z_]+) deliveryID=(?P<delivery>[a-z]+\.(?:normal|strong)) "
    r"language=(?P<language>[a-z]+) variation=(?P<variation>[a-z]+) "
    r"streaming=(?P<streaming>true|false) seedSource=(?P<seed_source>[a-z]+)"
)


class ContractError(ValueError):
    pass


def digest_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass


def load_plan(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or set(value) != {"schemaVersion", "scriptSHA256", "scriptCharacters", "takes"}:
        raise ContractError("plan fields do not match schema v1")
    if value["schemaVersion"] != SCHEMA_VERSION:
        raise ContractError("unsupported plan schema version")
    if not SHA256.fullmatch(str(value["scriptSHA256"])):
        raise ContractError("scriptSHA256 must be lowercase SHA-256")
    if not isinstance(value["scriptCharacters"], int) or not 1 <= value["scriptCharacters"] <= 2000:
        raise ContractError("scriptCharacters must be 1...2000")
    takes = value["takes"]
    if not isinstance(takes, list) or not 1 <= len(takes) <= 128:
        raise ContractError("takes must contain 1...128 rows")
    seen_ids: set[str] = set()
    seen_indexes: set[int] = set()
    prior_id: str | None = None
    required = {"takeIndex", "takeID", "speakerID", "deliveryID", "language", "seed", "variation", "streaming", "preparation"}
    for position, take in enumerate(takes, 1):
        if not isinstance(take, dict) or not required.issubset(take):
            raise ContractError(f"take {position} is missing required fields")
        if set(take) - (required | {"predecessorTakeID"}):
            raise ContractError(f"take {position} has unknown fields")
        index = take["takeIndex"]
        take_id = take["takeID"]
        if index != position or index in seen_indexes:
            raise ContractError("takeIndex must be unique, contiguous, and ordered from one")
        if not isinstance(take_id, str) or not SAFE_ID.fullmatch(take_id) or take_id in seen_ids:
            raise ContractError("takeID must be unique and allowlisted")
        if take["speakerID"] not in SPEAKERS:
            raise ContractError(f"take {position} has an unknown speaker")
        if not isinstance(take["deliveryID"], str) or not DELIVERY.fullmatch(take["deliveryID"]):
            raise ContractError(f"take {position} has an invalid delivery cell")
        if take["language"] not in LANGUAGES or take["variation"] not in VARIATIONS:
            raise ContractError(f"take {position} has an invalid language or variation")
        if not isinstance(take["seed"], int) or take["seed"] < 0 or take["seed"] > 2**64 - 1:
            raise ContractError(f"take {position} has an invalid seed")
        if not isinstance(take["streaming"], bool) or take["preparation"] not in PREPARATIONS:
            raise ContractError(f"take {position} has an invalid execution policy")
        predecessor = take.get("predecessorTakeID")
        if predecessor != prior_id:
            raise ContractError(f"take {position} predecessor does not name the immediately previous take")
        seen_ids.add(take_id)
        seen_indexes.add(index)
        prior_id = take_id
    return value


def validate_script(plan: dict[str, Any], path: Path) -> str:
    data = path.read_bytes()
    try:
        script = data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ContractError("script file must be UTF-8") from error
    if digest_bytes(data) != plan["scriptSHA256"]:
        raise ContractError("script digest does not match the plan")
    if len(script) != plan["scriptCharacters"]:
        raise ContractError("script character count does not match the plan")
    if not script.strip() or "\x00" in script:
        raise ContractError("script is empty or contains NUL")
    return script


def prepare(plan_path: Path, script_path: Path, run_id: str, sanitized: Path, launch: Path) -> None:
    if not SAFE_ID.fullmatch(run_id):
        raise ContractError("run ID is not allowlisted")
    plan = load_plan(plan_path)
    script = validate_script(plan, script_path)
    sanitized_plan = dict(plan)
    sanitized_plan["runID"] = run_id
    sanitized_plan["planSHA256"] = digest_bytes(plan_path.read_bytes())
    atomic_json(sanitized, sanitized_plan)
    atomic_json(launch, {"schemaVersion": 1, "runID": run_id, "plan": plan, "script": script})


def recursively_reject_private_fields(value: Any, *, path: str = "$") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if key in FORBIDDEN_KEYS or key.lower().endswith("path") or key.lower().endswith("url"):
                raise ContractError(f"retained result contains forbidden field at {path}.{key}")
            recursively_reject_private_fields(child, path=f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            recursively_reject_private_fields(child, path=f"{path}[{index}]")


def parse_timestamp(value: Any, field: str) -> datetime:
    if not isinstance(value, str):
        raise ContractError(f"{field} must be an ISO-8601 timestamp")
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ContractError(f"{field} must be an ISO-8601 timestamp") from error


def validate_uuid(value: Any, field: str) -> None:
    try:
        uuid.UUID(str(value))
    except (ValueError, AttributeError) as error:
        raise ContractError(f"{field} must be a UUID") from error


def validate_device_state(value: Any, field: str) -> None:
    required = {"lowPowerModeEnabled", "thermalState", "modelInstalled"}
    allowed = required | {"loadedModelID"}
    if not isinstance(value, dict) or not required.issubset(value) or set(value) - allowed:
        raise ContractError(f"{field} does not match the device-state schema")
    if not isinstance(value["lowPowerModeEnabled"], bool) or not isinstance(value["modelInstalled"], bool):
        raise ContractError(f"{field} has invalid booleans")
    if value["thermalState"] not in {"nominal", "fair", "serious", "critical", "unknown"}:
        raise ContractError(f"{field} has invalid thermal state")
    loaded = value.get("loadedModelID")
    if loaded is not None and (not isinstance(loaded, str) or not SAFE_ID.fullmatch(loaded)):
        raise ContractError(f"{field} has an invalid loaded model identity")


def validate_receipt(value: Any, field: str) -> None:
    required = {
        "schemaVersion", "generationID", "generationIdentityDigest", "requestIdentityDigest",
        "sessionIdentityDigest", "prewarmIdentityDigest", "modelID", "instructionCharacters",
        "language", "seed", "seedSource", "variation", "streaming", "warmState",
        "retryAttempt", "operationGeneration",
    }
    allowed = required | {
        "speakerID", "deliveryID", "instructionDigest", "predecessorIdentityDigest",
    }
    if not isinstance(value, dict) or not required.issubset(value) or set(value) - allowed:
        raise ContractError(f"{field} does not match request-receipt schema v1")
    if value["schemaVersion"] != 1:
        raise ContractError(f"{field} uses an unsupported schema")
    validate_uuid(value["generationID"], f"{field}.generationID")
    for key in ("generationIdentityDigest", "requestIdentityDigest", "sessionIdentityDigest", "prewarmIdentityDigest"):
        if not isinstance(value[key], str) or not SHA256.fullmatch(value[key]):
            raise ContractError(f"{field}.{key} is not SHA-256")
    for key in ("instructionDigest", "predecessorIdentityDigest"):
        child = value.get(key)
        if child is not None and (not isinstance(child, str) or not SHA256.fullmatch(child)):
            raise ContractError(f"{field}.{key} is not nullable SHA-256")
    if not isinstance(value["modelID"], str) or not SAFE_ID.fullmatch(value["modelID"]):
        raise ContractError(f"{field}.modelID is invalid")
    speaker = value.get("speakerID")
    if speaker is not None and speaker not in SPEAKERS:
        raise ContractError(f"{field}.speakerID is invalid")
    delivery = value.get("deliveryID")
    if delivery is not None and (not isinstance(delivery, str) or not DELIVERY.fullmatch(delivery)):
        raise ContractError(f"{field}.deliveryID is invalid")
    if value["language"] not in LANGUAGES or value["variation"] not in VARIATIONS:
        raise ContractError(f"{field} has invalid language or variation")
    if value["seedSource"] not in {"requested", "generated"} or value["warmState"] not in {"cold", "warm"}:
        raise ContractError(f"{field} has invalid seed or warm-state vocabulary")
    if not isinstance(value["streaming"], bool):
        raise ContractError(f"{field}.streaming must be boolean")
    for key, maximum in (("instructionCharacters", 10000), ("seed", 2**64 - 1), ("retryAttempt", 1), ("operationGeneration", 2**64 - 1)):
        child = value[key]
        if not isinstance(child, int) or isinstance(child, bool) or not 0 <= child <= maximum:
            raise ContractError(f"{field}.{key} is out of bounds")


def validate_timeline(value: Any, field: str) -> None:
    if not isinstance(value, list):
        raise ContractError(f"{field} must be a boundary array")
    seen: set[str] = set()
    prior = -1
    for index, row in enumerate(value):
        if not isinstance(row, dict) or set(row) != {"boundary", "tMS"}:
            raise ContractError(f"{field}[{index}] does not match the boundary schema")
        boundary, time_ms = row["boundary"], row["tMS"]
        if boundary not in BOUNDARIES or boundary in seen:
            raise ContractError(f"{field} contains an invalid or repeated one-shot boundary")
        if not isinstance(time_ms, int) or isinstance(time_ms, bool) or time_ms < prior:
            raise ContractError(f"{field} is not monotonic")
        seen.add(boundary)
        prior = time_ms
    observed_times = {row["boundary"]: row["tMS"] for row in value}
    ordered_times = [observed_times[boundary] for boundary in BOUNDARY_ORDER if boundary in observed_times]
    if ordered_times != sorted(ordered_times):
        raise ContractError(f"{field} violates causal startup-boundary order")
    token_time = observed_times.get("first_model_token")
    code_time = observed_times.get("first_audio_code_group")
    if (token_time is None) != (code_time is None) or (
        token_time is not None and token_time != code_time
    ):
        raise ContractError(f"{field} must co-observe first model token and audio-code group")


def validate_output(value: Any, field: str) -> None:
    if not isinstance(value, dict) or set(value) != {"sha256", "byteCount", "durationSeconds"}:
        raise ContractError(f"{field} does not match output schema")
    if not isinstance(value["sha256"], str) or not SHA256.fullmatch(value["sha256"]):
        raise ContractError(f"{field}.sha256 is invalid")
    if not isinstance(value["byteCount"], int) or value["byteCount"] <= 0:
        raise ContractError(f"{field}.byteCount is invalid")
    if not isinstance(value["durationSeconds"], (int, float)) or value["durationSeconds"] <= 0:
        raise ContractError(f"{field}.durationSeconds is invalid")


def validate_result(plan_path: Path, artifact_dir: Path, run_id: str) -> dict[str, Any]:
    plan = load_plan(plan_path)
    result_path = next(iter(artifact_dir.rglob("startup-reliability-result.json")), None)
    if result_path is None:
        failure = next(iter(artifact_dir.rglob("startup-reliability-failure.json")), None)
        raise ContractError("terminal result is missing" + ("; typed failure marker exists" if failure else ""))
    result = json.loads(result_path.read_text(encoding="utf-8"))
    if not isinstance(result, dict) or result.get("schemaVersion") != 1 or result.get("runID") != run_id:
        raise ContractError("terminal result identity is invalid")
    required_result = {"schemaVersion", "status", "runID", "scriptSHA256", "scriptCharacters", "plannedTakeCount", "representedTakeCount", "startedAt", "finishedAt", "startingDeviceState", "finishingDeviceState", "takes"}
    if set(result) != required_result or result.get("status") not in {"pass", "diagnosed_failure"}:
        raise ContractError("terminal result does not match result schema v1")
    started_at = parse_timestamp(result["startedAt"], "startedAt")
    finished_at = parse_timestamp(result["finishedAt"], "finishedAt")
    if finished_at < started_at:
        raise ContractError("finishedAt predates startedAt")
    validate_device_state(result["startingDeviceState"], "startingDeviceState")
    validate_device_state(result["finishingDeviceState"], "finishingDeviceState")
    recursively_reject_private_fields(result)
    takes = result.get("takes")
    if not isinstance(takes, list) or len(takes) != len(plan["takes"]):
        raise ContractError("terminal result does not represent every planned take")
    if result.get("plannedTakeCount") != len(plan["takes"]) or result.get("representedTakeCount") != len(takes):
        raise ContractError("terminal result counts are inconsistent")
    if result.get("scriptSHA256") != plan["scriptSHA256"] or result.get("scriptCharacters") != plan["scriptCharacters"]:
        raise ContractError("terminal result script identity drifted")
    previous_session: str | None = None
    for planned, observed in zip(plan["takes"], takes):
        required_take = {"takeIndex", "takeID", "generationID", "status", "preparation", "attempts", "startupTimeline", "classification"}
        allowed_take = required_take | {"requestReceipt", "failureCode", "output"}
        if not isinstance(observed, dict) or not required_take.issubset(observed) or set(observed) - allowed_take:
            raise ContractError("take does not match result schema v1")
        validate_uuid(observed["generationID"], "take.generationID")
        if observed["status"] not in {"pass", "failed"} or observed["preparation"] not in PREPARATIONS or observed["classification"] not in CLASSIFICATIONS:
            raise ContractError("take has invalid terminal vocabulary")
        if observed["preparation"] != planned["preparation"]:
            raise ContractError("take preparation drifted")
        if observed.get("output") is not None:
            validate_output(observed["output"], "take.output")
        if observed.get("takeIndex") != planned["takeIndex"] or observed.get("takeID") != planned["takeID"]:
            raise ContractError("take identity/order drifted")
        receipt = observed.get("requestReceipt")
        if not isinstance(receipt, dict):
            if observed.get("status") == "pass" or observed.get("failureCode") != "request_receipt_unavailable":
                raise ContractError("take request receipt is missing without a typed diagnostic failure")
            previous_session = None
            continue
        validate_receipt(receipt, "take.requestReceipt")
        required_matches = {
            "speakerID": planned["speakerID"], "deliveryID": planned["deliveryID"],
            "language": planned["language"], "seed": planned["seed"],
            "variation": planned["variation"], "streaming": planned["streaming"],
        }
        if any(receipt.get(key) != value for key, value in required_matches.items()):
            raise ContractError("take request receipt does not match the plan")
        attempts = observed.get("attempts")
        if not isinstance(attempts, list) or not attempts:
            raise ContractError("receipt-bearing take has no represented attempt history")
        attempt_receipts: list[dict[str, Any]] = []
        for expected_retry, attempt in enumerate(attempts):
            if not isinstance(attempt, dict) or attempt.get("retryAttempt") != expected_retry:
                raise ContractError("retry attempts must be unique, contiguous, and ordered from zero")
            if set(attempt) != {"retryAttempt", "finishReason", "requestReceipt", "startupTimeline"}:
                raise ContractError("retry attempt does not match schema v1")
            if not isinstance(attempt.get("finishReason"), str) or not SAFE_ID.fullmatch(attempt["finishReason"]):
                raise ContractError("retry attempt finish reason is invalid")
            attempt_receipt = attempt.get("requestReceipt")
            if not isinstance(attempt_receipt, dict) or attempt_receipt.get("retryAttempt") != expected_retry:
                raise ContractError("retry attempt receipt accounting is inconsistent")
            validate_receipt(attempt_receipt, "take.attempt.requestReceipt")
            validate_timeline(attempt.get("startupTimeline"), "take.attempt.startupTimeline")
            attempt_receipts.append(attempt_receipt)
        if len(attempt_receipts) > 2:
            raise ContractError("startup reliability permits at most one allocation retry")
        if attempt_receipts[-1] != receipt:
            raise ContractError("terminal request receipt is not the final represented attempt")
        stable_retry_fields = {
            "schemaVersion", "generationID", "generationIdentityDigest", "requestIdentityDigest",
            "sessionIdentityDigest", "prewarmIdentityDigest", "modelID", "speakerID", "deliveryID",
            "instructionDigest", "instructionCharacters", "language", "seed", "seedSource", "variation",
            "streaming", "predecessorIdentityDigest", "operationGeneration",
        }
        baseline_attempt = attempt_receipts[0]
        for attempt_receipt in attempt_receipts[1:]:
            if any(attempt_receipt.get(field) != baseline_attempt.get(field) for field in stable_retry_fields):
                raise ContractError("allocation retry changed request, seed, or operation identity")
        if planned.get("predecessorTakeID") is None:
            if receipt.get("predecessorIdentityDigest") is not None:
                raise ContractError("first take unexpectedly carries a predecessor")
        elif receipt.get("predecessorIdentityDigest") != previous_session:
            raise ContractError("take predecessor identity is not the prior session")
        stages = observed.get("startupTimeline")
        validate_timeline(stages, "take.startupTimeline")
        if stages != attempts[-1].get("startupTimeline"):
            raise ContractError("terminal startup timeline is not the final represented attempt")
        if observed.get("status") == "pass" and not any(
            stage.get("boundary") == "first_decoded_audio_frame" for stage in stages if isinstance(stage, dict)
        ):
            raise ContractError("passing take lacks the decoded-audio boundary")
        if observed.get("status") == "pass":
            observed_boundaries = {
                stage["boundary"] for stage in stages if isinstance(stage, dict)
            }
            missing = REQUIRED_PASS_BOUNDARIES - observed_boundaries
            if missing:
                raise ContractError(
                    "passing take lacks required startup boundaries: " + ",".join(sorted(missing))
                )
            published = "first_published_stream_chunk" in observed_boundaries
            if published != bool(receipt["streaming"]):
                raise ContractError("passing take has inconsistent stream-publication boundary")
        previous_session = receipt.get("sessionIdentityDigest")
        if not isinstance(previous_session, str) or not SHA256.fullmatch(previous_session):
            raise ContractError("take session identity is invalid")
    failed_count = sum(take.get("status") != "pass" for take in takes)
    if (result["status"] == "pass") != (failed_count == 0):
        raise ContractError("terminal status does not match represented take outcomes")
    device_terminal_inputs = {
        "startup-reliability-take.json",
        "generation-failures.jsonl",
        "generations.jsonl",
    }
    other_files = [
        path for path in result_path.parent.rglob("*")
        if path.is_file()
        and path != result_path
        and (
            path.name in device_terminal_inputs
            or path.name.startswith("startup-reliability-take-")
        )
    ]
    if other_files and any(path.stat().st_mtime_ns > result_path.stat().st_mtime_ns for path in other_files):
        raise ContractError("terminal sentinel was not written last")
    summary = {
        "schemaVersion": 1,
        "runID": run_id,
        "result": result.get("status"),
        "plannedTakeCount": len(plan["takes"]),
        "representedTakeCount": len(takes),
        "failedTakeCount": failed_count,
        "scriptSHA256": plan["scriptSHA256"],
    }
    atomic_json(artifact_dir / "startup-reliability-summary.json", summary)
    return summary


def validate_ui_parity(log_path: Path, diagnostics: Path, run_id: str, output: Path) -> dict[str, Any]:
    log = log_path.read_text(encoding="utf-8", errors="replace")
    matches = list(UI_MANIFEST.finditer(log))
    if len(matches) != 1:
        raise ContractError("UI parity log must contain exactly one bounded manifest")
    visible = matches[0].groupdict()
    if visible["run"] != run_id:
        raise ContractError("UI parity manifest run identity drifted")
    try:
        visible_generation = uuid.UUID(visible["generation"])
    except ValueError as error:
        raise ContractError("UI parity manifest generation identity is invalid") from error
    rows: list[dict[str, Any]] = []
    for path in diagnostics.rglob("generations.jsonl"):
        if path.parent.name != "engine":
            continue
        for line in path.read_text(encoding="utf-8", errors="strict").splitlines():
            value = json.loads(line)
            try:
                row_generation = uuid.UUID(str(value.get("generationID")))
            except ValueError:
                continue
            if row_generation == visible_generation and value.get("layer") == "engine":
                rows.append(value)
    receipts = [row.get("requestReceipt") for row in rows if isinstance(row.get("requestReceipt"), dict)]
    if not receipts:
        raise ContractError("UI generation has no correlated engine request receipt")
    receipt = max(receipts, key=lambda value: value.get("retryAttempt", -1))
    try:
        receipt_generation = uuid.UUID(str(receipt.get("generationID")))
    except ValueError as error:
        raise ContractError("engine receipt generation identity is invalid") from error
    if receipt_generation != visible_generation:
        raise ContractError("visible UI request and engine receipt diverged")
    expected = {
        "speakerID": visible["speaker"],
        "deliveryID": visible["delivery"],
        "language": visible["language"],
        "variation": visible["variation"],
        "streaming": visible["streaming"] == "true",
        "seedSource": visible["seed_source"],
    }
    if any(receipt.get(key) != value for key, value in expected.items()):
        raise ContractError("visible UI request and engine receipt diverged")
    if not SHA256.fullmatch(str(receipt.get("instructionDigest"))) or receipt.get("instructionCharacters", 0) <= 0:
        raise ContractError("engine receipt lacks the exact canonical instruction identity")
    seed = receipt.get("seed")
    if not isinstance(seed, int) or seed < 0:
        raise ContractError("engine receipt seed is invalid")
    terminal = max(rows, key=lambda row: (row.get("requestReceipt") or {}).get("retryAttempt", -1))
    stages = {
        mark.get("stage") for mark in terminal.get("stageMarks", []) if isinstance(mark, dict)
    }
    if "startup.first_decoded_audio_frame" not in stages:
        raise ContractError("UI generation lacks the decoded-audio startup boundary")
    result = {
        "schemaVersion": 1,
        "status": "pass",
        "runID": run_id,
        "generationID": str(visible_generation),
        "speakerID": visible["speaker"],
        "deliveryID": visible["delivery"],
        "instructionDigest": receipt["instructionDigest"],
        "language": visible["language"],
        "seed": seed,
        "seedSource": visible["seed_source"],
        "variation": visible["variation"],
        "streaming": visible["streaming"] == "true",
        "retryAttempt": receipt.get("retryAttempt"),
    }
    atomic_json(output, result)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    prepare_parser = sub.add_parser("prepare")
    prepare_parser.add_argument("--plan", required=True, type=Path)
    prepare_parser.add_argument("--script-file", required=True, type=Path)
    prepare_parser.add_argument("--run-id", required=True)
    prepare_parser.add_argument("--sanitized-output", required=True, type=Path)
    prepare_parser.add_argument("--launch-output", required=True, type=Path)
    validate_parser = sub.add_parser("validate-result")
    validate_parser.add_argument("--plan", required=True, type=Path)
    validate_parser.add_argument("--artifact-dir", required=True, type=Path)
    validate_parser.add_argument("--run-id", required=True)
    ui_parser = sub.add_parser("validate-ui-parity")
    ui_parser.add_argument("--xcodebuild-log", required=True, type=Path)
    ui_parser.add_argument("--diagnostics", required=True, type=Path)
    ui_parser.add_argument("--run-id", required=True)
    ui_parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "prepare":
            prepare(args.plan, args.script_file, args.run_id, args.sanitized_output, args.launch_output)
        elif args.command == "validate-result":
            validate_result(args.plan, args.artifact_dir, args.run_id)
        else:
            validate_ui_parity(args.xcodebuild_log, args.diagnostics, args.run_id, args.output)
    except (ContractError, json.JSONDecodeError, OSError) as error:
        print(f"startup reliability contract failed: {error}", file=os.sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
