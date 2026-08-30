#!/usr/bin/env python3
"""Validate and compose privacy-safe iOS startup reliability diagnostics."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import struct
import tempfile
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_VERSION = 1
RESULT_SCHEMA_VERSIONS = {1, 2}
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
        "speakerID", "deliveryID", "instructionDigest", "instructionLanguage",
        "modelFacingInstructionLanguage",
        "predecessorIdentityDigest",
        "storedLanguageSelection", "detectedTargetLanguage", "referenceTranscriptLanguage",
        "finalModelLanguage", "languageTokenMode", "conditioningMode",
        "normalizedTargetTextDigest", "normalizedTargetTextCharacters",
        "referenceTranscriptDigest", "referenceTranscriptCharacters",
        "referenceAudioDigest", "modelArtifactVersion",
        "modelIntegrityManifestDigest", "speechTokenizerDigest",
    }
    if not isinstance(value, dict) or not required.issubset(value) or set(value) - allowed:
        raise ContractError(f"{field} does not match request-receipt schema v1")
    if value["schemaVersion"] not in {1, 2}:
        raise ContractError(f"{field} uses an unsupported schema")
    if value["schemaVersion"] == 2:
        v2_required = {
            "storedLanguageSelection", "finalModelLanguage", "languageTokenMode", "conditioningMode",
            "normalizedTargetTextDigest", "normalizedTargetTextCharacters",
            "referenceTranscriptCharacters",
        }
        if not v2_required.issubset(value):
            raise ContractError(f"{field} omits request-receipt schema v2 fields")
        if value.get("instructionDigest") is not None and "modelFacingInstructionLanguage" not in value:
            raise ContractError(f"{field} omits model-facing instruction language")
    validate_uuid(value["generationID"], f"{field}.generationID")
    for key in ("generationIdentityDigest", "requestIdentityDigest", "sessionIdentityDigest", "prewarmIdentityDigest"):
        if not isinstance(value[key], str) or not SHA256.fullmatch(value[key]):
            raise ContractError(f"{field}.{key} is not SHA-256")
    for key in (
        "instructionDigest", "predecessorIdentityDigest", "normalizedTargetTextDigest",
        "referenceTranscriptDigest", "referenceAudioDigest", "modelIntegrityManifestDigest",
        "speechTokenizerDigest",
    ):
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
    for key in ("storedLanguageSelection", "detectedTargetLanguage", "referenceTranscriptLanguage", "finalModelLanguage"):
        child = value.get(key)
        if child is not None and child not in LANGUAGES:
            raise ContractError(f"{field}.{key} is invalid")
    if value.get("finalModelLanguage") not in {None, value["language"]}:
        raise ContractError(f"{field}.finalModelLanguage disagrees with language")
    if value.get("languageTokenMode") not in {None, "think", "nothink"}:
        raise ContractError(f"{field}.languageTokenMode is invalid")
    if value.get("conditioningMode") not in {
        None, "custom_voice", "voice_design", "clone_transcript_backed", "clone_audio_only",
    }:
        raise ContractError(f"{field}.conditioningMode is invalid")
    if value.get("instructionLanguage") not in {None, "english", "mandarin", "verbatim"}:
        raise ContractError(f"{field}.instructionLanguage is invalid")
    if value.get("modelFacingInstructionLanguage") not in LANGUAGES | {None}:
        raise ContractError(f"{field}.modelFacingInstructionLanguage is invalid")
    if value["seedSource"] not in {"requested", "generated"} or value["warmState"] not in {"cold", "warm"}:
        raise ContractError(f"{field} has invalid seed or warm-state vocabulary")
    if not isinstance(value["streaming"], bool):
        raise ContractError(f"{field}.streaming must be boolean")
    for key, maximum in (("instructionCharacters", 10000), ("seed", 2**64 - 1), ("retryAttempt", 1), ("operationGeneration", 2**64 - 1)):
        child = value[key]
        if not isinstance(child, int) or isinstance(child, bool) or not 0 <= child <= maximum:
            raise ContractError(f"{field}.{key} is out of bounds")
    for key in ("normalizedTargetTextCharacters", "referenceTranscriptCharacters"):
        child = value.get(key)
        if child is not None and (not isinstance(child, int) or isinstance(child, bool) or not 0 <= child <= 100000):
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


def validate_preparation_evidence(value: Any, field: str) -> None:
    required = {
        "stage", "sequence", "capturedAtUptimeSeconds", "hasActiveGeneration",
        "memoryActionInFlight", "modelOperationInFlight",
        "generationReservationInFlight", "engineLifecycle", "violations",
    }
    allowed = required | {
        "mlxActiveMB", "mlxCacheMB", "mlxPeakMB", "metalAllocatedMB",
        "physicalFootprintMB", "availableHeadroomMB", "loadedModelID",
    }
    if not isinstance(value, dict) or not required.issubset(value) or set(value) - allowed:
        raise ContractError(f"{field} does not match preparation-evidence schema v2")
    if not isinstance(value["stage"], str) or not SAFE_ID.fullmatch(value["stage"]):
        raise ContractError(f"{field}.stage is invalid")
    if not isinstance(value["sequence"], int) or value["sequence"] < 0:
        raise ContractError(f"{field}.sequence is invalid")
    if not isinstance(value["capturedAtUptimeSeconds"], (int, float)) or value["capturedAtUptimeSeconds"] < 0:
        raise ContractError(f"{field}.capturedAtUptimeSeconds is invalid")
    for key in (
        "mlxActiveMB", "mlxCacheMB", "mlxPeakMB", "metalAllocatedMB",
        "physicalFootprintMB", "availableHeadroomMB",
    ):
        child = value.get(key)
        if child is not None and (not isinstance(child, (int, float)) or child < 0):
            raise ContractError(f"{field}.{key} is invalid")
    for key in (
        "hasActiveGeneration", "memoryActionInFlight", "modelOperationInFlight",
        "generationReservationInFlight",
    ):
        if not isinstance(value[key], bool):
            raise ContractError(f"{field}.{key} must be boolean")
    for key in ("loadedModelID",):
        child = value.get(key)
        if child is not None and (not isinstance(child, str) or not SAFE_ID.fullmatch(child)):
            raise ContractError(f"{field}.{key} is invalid")
    if not isinstance(value["engineLifecycle"], str) or not SAFE_ID.fullmatch(value["engineLifecycle"]):
        raise ContractError(f"{field}.engineLifecycle is invalid")
    violations = value["violations"]
    if not isinstance(violations, list) or violations != sorted(set(violations)) or any(
        not isinstance(item, str) or not SAFE_ID.fullmatch(item) for item in violations
    ):
        raise ContractError(f"{field}.violations is not a sorted allowlisted set")


def validate_audio_qc(value: Any, field: str) -> None:
    required = {
        "algorithmVersion", "instabilityVerdict", "writtenOutputVerdict", "verdict",
        "flags", "peak", "clippedSamples", "hotSamples", "nonFiniteSamples",
        "clickEvents", "longestSilenceMS", "durationSeconds",
    }
    allowed = required | {
        "rmsDBFS", "dcOffset", "firstNonFiniteSample", "firstClipSample",
        "longestSilenceStartMS", "chunkQC",
    }
    if not isinstance(value, dict) or not required.issubset(value) or set(value) - allowed:
        raise ContractError(f"{field} does not match complete AudioQCReport")
    if value["verdict"] not in {"pass", "warn", "fail"} or value["instabilityVerdict"] not in {"pass", "warn", "fail"} or value["writtenOutputVerdict"] not in {"pass", "warn", "fail"}:
        raise ContractError(f"{field} has invalid verdict vocabulary")
    if not isinstance(value["longestSilenceMS"], int) or value["longestSilenceMS"] < 0:
        raise ContractError(f"{field}.longestSilenceMS is invalid")
    silence_start = value.get("longestSilenceStartMS")
    if silence_start is not None and (not isinstance(silence_start, int) or silence_start < 0):
        raise ContractError(f"{field}.longestSilenceStartMS is invalid")
    if not isinstance(value["durationSeconds"], (int, float)) or value["durationSeconds"] <= 0:
        raise ContractError(f"{field}.durationSeconds is invalid")
    if not isinstance(value["flags"], list) or any(not isinstance(flag, str) for flag in value["flags"]):
        raise ContractError(f"{field}.flags is invalid")
    if not isinstance(value["algorithmVersion"], int) or value["algorithmVersion"] < 1:
        raise ContractError(f"{field}.algorithmVersion is invalid")
    for key in ("clippedSamples", "hotSamples", "nonFiniteSamples", "clickEvents"):
        if not isinstance(value[key], int) or value[key] < 0:
            raise ContractError(f"{field}.{key} is invalid")
    if not isinstance(value["peak"], (int, float)) or value["peak"] < 0:
        raise ContractError(f"{field}.peak is invalid")
    chunk_qc = value.get("chunkQC")
    if chunk_qc is not None:
        if not isinstance(chunk_qc, list):
            raise ContractError(f"{field}.chunkQC is invalid")
        chunk_required = {
            "chunkIndex", "frameOffset", "frameCount", "verdict", "flags", "peak",
            "clippedSamples", "hotSamples", "nonFiniteSamples", "clickEvents",
            "longestSilenceMS", "durationSeconds",
        }
        chunk_allowed = chunk_required | {
            "rmsDBFS", "firstNonFiniteSample", "firstClipSample", "longestSilenceStartMS",
        }
        expected_frame_offset = 0
        for index, chunk in enumerate(chunk_qc):
            if not isinstance(chunk, dict) or not chunk_required.issubset(chunk) or set(chunk) - chunk_allowed:
                raise ContractError(f"{field}.chunkQC[{index}] is incomplete")
            if chunk["chunkIndex"] != index or chunk["verdict"] not in {"pass", "warn", "fail"}:
                raise ContractError(f"{field}.chunkQC[{index}] identity is invalid")
            for key in ("frameOffset", "frameCount", "clippedSamples", "hotSamples", "nonFiniteSamples", "clickEvents", "longestSilenceMS"):
                if not isinstance(chunk[key], int) or chunk[key] < 0 or (key == "frameCount" and chunk[key] == 0):
                    raise ContractError(f"{field}.chunkQC[{index}].{key} is invalid")
            if chunk["frameOffset"] != expected_frame_offset:
                raise ContractError(f"{field}.chunkQC[{index}] frame coverage is not contiguous")
            expected_frame_offset += chunk["frameCount"]
            if not isinstance(chunk["flags"], list) or any(
                not isinstance(flag, str) for flag in chunk["flags"]
            ):
                raise ContractError(f"{field}.chunkQC[{index}].flags is invalid")
            if not isinstance(chunk["peak"], (int, float)) or chunk["peak"] < 0:
                raise ContractError(f"{field}.chunkQC[{index}].peak is invalid")
            if not isinstance(chunk["durationSeconds"], (int, float)) or chunk["durationSeconds"] <= 0:
                raise ContractError(f"{field}.chunkQC[{index}].durationSeconds is invalid")
            for key in ("firstNonFiniteSample", "firstClipSample", "longestSilenceStartMS"):
                optional_index = chunk.get(key)
                if optional_index is not None and (
                    not isinstance(optional_index, int) or optional_index < 0
                ):
                    raise ContractError(f"{field}.chunkQC[{index}].{key} is invalid")


def validate_codec_ranges(value: Any, field: str, frame_count: int | None = None) -> list[dict[str, int]]:
    if not isinstance(value, list) or not value:
        raise ContractError(f"{field} is empty")
    expected = 0
    for index, row in enumerate(value):
        if not isinstance(row, dict) or set(row) != {"start", "endExclusive"}:
            raise ContractError(f"{field}[{index}] does not match the range schema")
        if row["start"] != expected or not isinstance(row["endExclusive"], int) or row["endExclusive"] <= row["start"]:
            raise ContractError(f"{field}[{index}] is not contiguous")
        expected = row["endExclusive"]
    if frame_count is not None and expected != frame_count:
        raise ContractError(f"{field} does not cover every codec frame")
    return value


def validate_diagnostic_artifacts(
    value: Any,
    field: str,
    *,
    artifact_dir: Path,
    generation_id: str,
) -> None:
    if not isinstance(value, list) or len(value) > 4:
        raise ContractError(f"{field} exceeds the bounded diagnostic artifact set")
    seen: set[str] = set()
    for index, row in enumerate(value):
        required = {"schemaVersion", "kind", "sha256", "byteCount"}
        allowed = required | {"durationSeconds", "codecFrameCount", "codeGroupRange", "codecChunkRanges", "complete"}
        if not isinstance(row, dict) or not required.issubset(row) or set(row) - allowed:
            raise ContractError(f"{field}[{index}] does not match diagnostic-artifact schema")
        kind = row["kind"]
        kinds = {"codec_trace", "rejected_audio", "incremental_replay_audio", "full_replay_audio"}
        if row["schemaVersion"] != 1 or kind not in kinds or kind in seen:
            raise ContractError(f"{field}[{index}] has invalid identity")
        seen.add(kind)
        if not isinstance(row["sha256"], str) or not SHA256.fullmatch(row["sha256"]):
            raise ContractError(f"{field}[{index}].sha256 is invalid")
        if not isinstance(row["byteCount"], int) or row["byteCount"] <= 0:
            raise ContractError(f"{field}[{index}].byteCount is invalid")
        filenames = {
            "codec_trace": "codec-trace-v1.bin",
            "rejected_audio": "rejected.wav",
            "incremental_replay_audio": "incremental-replay.wav",
            "full_replay_audio": "full-replay.wav",
        }
        filename = filenames[kind]
        candidates = list(artifact_dir.rglob(f"evidence/{generation_id}/{filename}"))
        if len(candidates) != 1:
            raise ContractError(f"{field}[{index}] has no unique correlated binary artifact")
        data = candidates[0].read_bytes()
        if len(data) != row["byteCount"] or digest_bytes(data) != row["sha256"]:
            raise ContractError(f"{field}[{index}] artifact bytes do not match retained identity")
        if kind == "codec_trace":
            if not data.startswith(b"VQCT") or len(data) < 16:
                raise ContractError(f"{field}[{index}] codec trace is corrupt")
            if not isinstance(row.get("codecFrameCount"), int) or row["codecFrameCount"] < 0:
                raise ContractError(f"{field}[{index}] codec frame count is invalid")
            code_range = row.get("codeGroupRange")
            if not isinstance(code_range, dict) or set(code_range) != {"minimum", "maximum"}:
                raise ContractError(f"{field}[{index}] code-group range is invalid")
            if not isinstance(row.get("complete"), bool):
                raise ContractError(f"{field}[{index}] completeness is invalid")
            version, frame_count, dropped_count = struct.unpack_from("<III", data, 4)
            if version != 1 or frame_count != row["codecFrameCount"]:
                raise ContractError(f"{field}[{index}] codec trace header drifted")
            offset = 16
            group_counts: list[int] = []
            for _ in range(frame_count):
                if offset + 2 > len(data):
                    raise ContractError(f"{field}[{index}] codec trace is truncated")
                group_count = struct.unpack_from("<H", data, offset)[0]
                offset += 2
                if not 1 <= group_count <= 64 or offset + group_count * 4 > len(data):
                    raise ContractError(f"{field}[{index}] codec frame is out of bounds")
                group_counts.append(group_count)
                offset += group_count * 4
            if offset != len(data):
                raise ContractError(f"{field}[{index}] codec trace has trailing bytes")
            if not group_counts:
                raise ContractError(f"{field}[{index}] codec trace is empty")
            if code_range != {"minimum": min(group_counts), "maximum": max(group_counts)}:
                raise ContractError(f"{field}[{index}] code-group range drifted")
            if row["complete"] != (dropped_count == 0):
                raise ContractError(f"{field}[{index}] completeness drifted")
            validate_codec_ranges(
                row.get("codecChunkRanges"),
                f"{field}[{index}].codecChunkRanges",
                frame_count=frame_count,
            )
        else:
            if not isinstance(row.get("durationSeconds"), (int, float)) or row["durationSeconds"] <= 0:
                raise ContractError(f"{field}[{index}] audio duration is invalid")


def validate_codec_replay(value: Any, field: str, artifacts: list[dict[str, Any]]) -> None:
    required = {"status", "traceSHA256", "ranges"}
    allowed = required | {
        "failureCode", "incrementalArtifact", "incrementalAudioQC",
        "fullArtifact", "fullAudioQC",
    }
    if not isinstance(value, dict) or not required.issubset(value) or set(value) - allowed:
        raise ContractError(f"{field} does not match codec-replay schema")
    if value["status"] not in {"complete", "failed"} or not SHA256.fullmatch(str(value["traceSHA256"])):
        raise ContractError(f"{field} identity is invalid")
    ranges = validate_codec_ranges(value["ranges"], f"{field}.ranges")
    codec = next((item for item in artifacts if item.get("kind") == "codec_trace"), None)
    if codec is None or codec.get("sha256") != value["traceSHA256"] or codec.get("codecChunkRanges") != ranges:
        raise ContractError(f"{field} is not bound to the retained codec trace")
    if value["status"] == "failed":
        if not isinstance(value.get("failureCode"), str) or not SAFE_ID.fullmatch(value["failureCode"]):
            raise ContractError(f"{field} lacks a typed failure")
        if any(value.get(key) is not None for key in ("incrementalArtifact", "incrementalAudioQC", "fullArtifact", "fullAudioQC")):
            raise ContractError(f"{field} failed replay carries completed evidence")
        return
    expected_kinds = {
        "incrementalArtifact": "incremental_replay_audio",
        "fullArtifact": "full_replay_audio",
    }
    for artifact_key, kind in expected_kinds.items():
        artifact = value.get(artifact_key)
        if not isinstance(artifact, dict) or artifact.get("kind") != kind or artifact not in artifacts:
            raise ContractError(f"{field}.{artifact_key} is missing from the retained set")
    for key in ("incrementalAudioQC", "fullAudioQC"):
        validate_audio_qc(value.get(key), f"{field}.{key}")


def validate_result(plan_path: Path, artifact_dir: Path, run_id: str) -> dict[str, Any]:
    plan = load_plan(plan_path)
    result_path = next(iter(artifact_dir.rglob("startup-reliability-result.json")), None)
    if result_path is None:
        failure = next(iter(artifact_dir.rglob("startup-reliability-failure.json")), None)
        raise ContractError("terminal result is missing" + ("; typed failure marker exists" if failure else ""))
    result = json.loads(result_path.read_text(encoding="utf-8"))
    result_version = result.get("schemaVersion") if isinstance(result, dict) else None
    if result_version not in RESULT_SCHEMA_VERSIONS or result.get("runID") != run_id:
        raise ContractError("terminal result identity is invalid")
    required_result = {"schemaVersion", "status", "runID", "scriptSHA256", "scriptCharacters", "plannedTakeCount", "representedTakeCount", "startedAt", "finishedAt", "startingDeviceState", "finishingDeviceState", "takes"}
    if set(result) != required_result or result.get("status") not in {"pass", "diagnosed_failure"}:
        raise ContractError(f"terminal result does not match result schema v{result_version}")
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
        if result_version == 2:
            required_take |= {
                "prePreparationStoreWarmState", "preRequestStoreWarmState",
                "preparationEvidence", "audioQC", "diagnosticArtifacts",
            }
            allowed_take |= required_take | {"codecReplay"}
        if not isinstance(observed, dict) or not required_take.issubset(observed) or set(observed) - allowed_take:
            raise ContractError(f"take does not match result schema v{result_version}")
        validate_uuid(observed["generationID"], "take.generationID")
        if observed["status"] not in {"pass", "failed"} or observed["preparation"] not in PREPARATIONS or observed["classification"] not in CLASSIFICATIONS:
            raise ContractError("take has invalid terminal vocabulary")
        if observed["preparation"] != planned["preparation"]:
            raise ContractError("take preparation drifted")
        if observed.get("output") is not None:
            validate_output(observed["output"], "take.output")
        if result_version == 2:
            for key in ("prePreparationStoreWarmState", "preRequestStoreWarmState"):
                if observed.get(key) not in {"cold", "warm"}:
                    raise ContractError(f"take.{key} is invalid")
            preparation_evidence = observed.get("preparationEvidence")
            if not isinstance(preparation_evidence, list) or not preparation_evidence:
                raise ContractError("take lacks preparation evidence")
            for evidence_index, evidence in enumerate(preparation_evidence):
                validate_preparation_evidence(
                    evidence,
                    f"take.preparationEvidence[{evidence_index}]",
                )
            audio_qc = observed.get("audioQC")
            if audio_qc is not None:
                validate_audio_qc(audio_qc, "take.audioQC")
            validate_diagnostic_artifacts(
                observed.get("diagnosticArtifacts"),
                "take.diagnosticArtifacts",
                artifact_dir=artifact_dir,
                generation_id=observed["generationID"],
            )
            artifacts = observed.get("diagnosticArtifacts", [])
            codec_replay = observed.get("codecReplay")
            if codec_replay is not None:
                validate_codec_replay(codec_replay, "take.codecReplay", artifacts)
            if observed.get("failureCode") == "audio_qc_failed":
                if not isinstance(audio_qc, dict) or audio_qc.get("verdict") != "fail":
                    raise ContractError("audio-QC rejection lacks its complete failing report")
                if not any(
                    artifact.get("kind") == "rejected_audio"
                    for artifact in observed.get("diagnosticArtifacts", [])
                    if isinstance(artifact, dict)
                ):
                    raise ContractError("audio-QC rejection lacks generation-scoped rejected audio")
                if codec_replay is None:
                    raise ContractError("audio-QC rejection lacks codec replay accounting")
        if observed.get("takeIndex") != planned["takeIndex"] or observed.get("takeID") != planned["takeID"]:
            raise ContractError("take identity/order drifted")
        receipt = observed.get("requestReceipt")
        if not isinstance(receipt, dict):
            allowed_receiptless = {"request_receipt_unavailable"}
            if result_version == 2:
                allowed_receiptless.add("preparation_not_quiescent")
            if observed.get("status") == "pass" or observed.get("failureCode") not in allowed_receiptless:
                raise ContractError("take request receipt is missing without a typed diagnostic failure")
            previous_session = None
            continue
        validate_receipt(receipt, "take.requestReceipt")
        if result_version == 2:
            artifacts = observed.get("diagnosticArtifacts", [])
            has_codec_trace = any(
                artifact.get("kind") == "codec_trace"
                for artifact in artifacts
                if isinstance(artifact, dict)
            )
            reached_codec_boundary = any(
                row.get("boundary") == "first_audio_code_group"
                for row in observed.get("startupTimeline", [])
                if isinstance(row, dict)
            )
            if reached_codec_boundary and not has_codec_trace:
                raise ContractError("materialized-code take lacks its codec trace")
            if observed.get("status") == "pass" and not isinstance(observed.get("audioQC"), dict):
                raise ContractError("passing take lacks its complete AudioQCReport")
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
        "schemaVersion": result_version,
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


def compose_process_exit(
    plan_path: Path,
    artifact_dir: Path,
    run_id: str,
    output: Path,
) -> dict[str, Any]:
    if not SAFE_ID.fullmatch(run_id):
        raise ContractError("run ID is not allowlisted")
    plan = load_plan(plan_path)
    if next(iter(artifact_dir.rglob("startup-reliability-result.json")), None) is not None:
        raise ContractError("process-exit composition refuses an app-completed terminal result")
    represented: dict[int, dict[str, Any]] = {}
    for path in artifact_dir.rglob("startup-reliability-take-*.json"):
        row = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(row, dict) or not isinstance(row.get("takeIndex"), int):
            raise ContractError("partial take result is malformed")
        index = row["takeIndex"]
        if index in represented:
            raise ContractError("partial take result identity is duplicated")
        if row.get("takeID") != plan["takes"][index - 1]["takeID"]:
            raise ContractError("partial take result drifted from the plan")
        recursively_reject_private_fields(row)
        represented[index] = row
    rows: list[dict[str, Any]] = []
    first_missing = next(
        (take["takeIndex"] for take in plan["takes"] if take["takeIndex"] not in represented),
        None,
    )
    if first_missing is None:
        raise ContractError("all takes are represented but the terminal sentinel is missing")
    for take in plan["takes"]:
        index = take["takeIndex"]
        if index in represented:
            observed = represented[index]
            rows.append({
                "takeIndex": index,
                "takeID": take["takeID"],
                "status": "represented",
                "classification": observed.get("classification", "unmaterialized_unknown"),
                "generationID": observed.get("generationID"),
            })
        elif index == first_missing:
            rows.append({
                "takeIndex": index,
                "takeID": take["takeID"],
                "status": "process_terminated",
                "classification": "crash",
            })
        else:
            rows.append({
                "takeIndex": index,
                "takeID": take["takeID"],
                "status": "not_started_after_process_exit",
                "classification": "unmaterialized_unknown",
            })
    result = {
        "schemaVersion": 1,
        "status": "process_terminated",
        "runID": run_id,
        "scriptSHA256": plan["scriptSHA256"],
        "plannedTakeCount": len(plan["takes"]),
        "representedTakeCount": len(represented),
        "rows": rows,
    }
    recursively_reject_private_fields(result)
    atomic_json(output, result)
    return result


def _load_ips_objects(path: Path) -> list[Any]:
    text = path.read_text(encoding="utf-8", errors="replace")
    objects: list[Any] = []
    try:
        objects.append(json.loads(text))
        return objects
    except json.JSONDecodeError:
        pass
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            objects.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return objects


def _walk_scalars(value: Any, *, prefix: str = "") -> list[tuple[str, Any]]:
    result: list[tuple[str, Any]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            result.extend(_walk_scalars(child, prefix=f"{prefix}.{key}" if prefix else str(key)))
    elif isinstance(value, list):
        for child in value[:64]:
            result.extend(_walk_scalars(child, prefix=prefix))
    elif isinstance(value, (str, int, float, bool)) or value is None:
        result.append((prefix.lower(), value))
    return result


def sanitize_system_crashes(
    input_dir: Path,
    output: Path,
    process_allowlist: set[str],
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for path in sorted(input_dir.rglob("*")):
        if not path.is_file():
            continue
        scalars = [item for obj in _load_ips_objects(path) for item in _walk_scalars(obj)]
        process_candidates = [
            str(value) for key, value in scalars
            if isinstance(value, str) and any(token in key for token in ("procname", "process", "bundleid", "app_name"))
        ]
        process = next(
            (candidate for candidate in process_candidates if candidate in process_allowlist),
            None,
        )
        if process is None:
            continue
        combined = " ".join(
            str(value).lower() for key, value in scalars
            if isinstance(value, str) and any(token in key for token in ("termination", "reason", "exception", "jetsam"))
        )
        if any(token in combined for token in ("jetsam", "per-process-limit", "highwater", "memory-pressure")):
            classification = "jetsam"
            reason = "memory_pressure_termination"
        elif "watchdog" in combined:
            classification = "watchdog"
            reason = "watchdog_termination"
        elif combined:
            classification = "crash"
            reason = "process_crash"
        else:
            classification = "unknown"
            reason = "unclassified_termination"
        timestamp = next(
            (str(value) for key, value in scalars if isinstance(value, str) and any(token in key for token in ("timestamp", "capturetime"))),
            None,
        )
        footprint_mb = None
        for key, value in scalars:
            if isinstance(value, (int, float)) and not isinstance(value, bool) and any(
                token in key for token in ("phys_footprint", "physfootprint", "footprintbytes")
            ):
                footprint_mb = round(float(value) / 1_048_576, 3)
                break
        row: dict[str, Any] = {
            "process": process,
            "classification": classification,
            "reason": reason,
            "reportSHA256": digest_bytes(path.read_bytes()),
        }
        if timestamp is not None:
            row["timestamp"] = timestamp[:64]
        if footprint_mb is not None:
            row["footprintMB"] = footprint_mb
        rows.append(row)
    result = {"schemaVersion": 1, "reports": rows}
    atomic_json(output, result)
    return result


def classify_xcui_bootstrap(
    log_path: Path,
    summary_path: Path,
    run_id: str,
    output: Path,
) -> dict[str, Any]:
    if not SAFE_ID.fullmatch(run_id):
        raise ContractError("run ID is not allowlisted")
    log = log_path.read_text(encoding="utf-8", errors="replace")
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    if not isinstance(summary, dict):
        raise ContractError("xcresult summary is not an object")
    count_values = [summary.get(key) for key in ("totalTestCount", "testsCount", "testCount") if key in summary]
    if len(count_values) != 1 or not isinstance(count_values[0], int) or isinstance(count_values[0], bool):
        raise ContractError("XCUITest bootstrap classification requires a proved test count")
    reported_test_count = count_values[0]
    failures = summary.get("testFailures", [])
    if not isinstance(failures, list) or not all(isinstance(row, dict) for row in failures):
        raise ContractError("xcresult test failures are malformed")

    # `xcresulttool get test-results summary` reports the UI-test runner's own
    # bootstrap error as one failed test even though no XCTestCase entered its
    # body. Prove that special shape narrowly instead of treating the aggregate
    # `totalTestCount` as a launched-test count. A real test failure carries a
    # `testIdentifierURL` and a class/method identifier; the runner-level error
    # has neither and names only the generated `*-Runner` process.
    runner_failures = [
        row for row in failures
        if isinstance(row.get("testName"), str)
        and "-Runner (" in row["testName"]
        and row["testName"].endswith("encountered an error")
        and row.get("testIdentifierURL") in (None, "")
        and isinstance(row.get("failureText"), str)
        and any(
            marker in row["failureText"]
            for marker in (
                "Timed out while enabling automation mode",
                "Failed to enable automation mode",
            )
        )
    ]
    proved_zero_launched = reported_test_count == 0
    if reported_test_count == 1 and len(failures) == 1 and len(runner_failures) == 1:
        proved_zero_launched = all(
            summary.get(key, 0) == expected
            for key, expected in (("passedTests", 0), ("skippedTests", 0), ("failedTests", 1))
        )
    if not proved_zero_launched:
        raise ContractError("XCUITest bootstrap classification requires a proved zero launched tests")
    bootstrap_markers = (
        "Timed out while enabling automation mode",
        "Failed to enable automation mode",
    )
    if not any(marker in log for marker in bootstrap_markers):
        raise ContractError("failure did not occur in the automation-session bootstrap phase")
    forbidden_markers = (
        "Test Case '-[",
        "VOCELLO-STARTUP-PARITY-UI-MANIFEST",
        "generation failed",
        "audio_qc",
        "Assertion Failure",
        "crashed",
    )
    if any(marker.lower() in log.lower() for marker in forbidden_markers):
        raise ContractError("launched-test or product evidence forbids bootstrap classification")
    result = {
        "schemaVersion": 1,
        "status": "infrastructure_bootstrap_failure",
        "runID": run_id,
        "testCaseCount": 0,
        "xcresultReportedTestCount": reported_test_count,
        "runnerFailureCount": len(runner_failures),
        "xcodebuildLogSHA256": digest_bytes(log_path.read_bytes()),
        "xcresultSummarySHA256": digest_bytes(summary_path.read_bytes()),
    }
    atomic_json(output, result)
    return result


def classify_xcui_external_interruption(
    log_path: Path,
    summary_path: Path,
    run_id: str,
    output: Path,
) -> dict[str, Any]:
    """Classify a launched UI test blocked by a proved SpringBoard notification.

    This is deliberately separate from bootstrap classification: the XCTestCase
    did launch, and its failed result remains failed. The classification only
    records that the first divergent layer was an external system banner rather
    than a Vocello product terminal.
    """
    if not SAFE_ID.fullmatch(run_id):
        raise ContractError("run ID is not allowlisted")
    log = log_path.read_text(encoding="utf-8", errors="replace")
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    if not isinstance(summary, dict):
        raise ContractError("xcresult summary is not an object")
    count = summary.get("totalTestCount")
    if not isinstance(count, int) or isinstance(count, bool) or count < 1:
        raise ContractError("external interruption requires a launched test")
    failures = summary.get("testFailures", [])
    if len(failures) != 1 or not isinstance(failures[0], dict):
        raise ContractError("external interruption requires exactly one test failure")
    failure = failures[0]
    if not isinstance(failure.get("testIdentifierURL"), str) or not failure["testIdentifierURL"]:
        raise ContractError("external interruption requires an identified launched test")
    failure_text = failure.get("failureText")
    if not isinstance(failure_text, str) or not all(
        marker in failure_text for marker in ("Timed out after", "waiting for")
    ):
        raise ContractError("test failure is not a post-interruption wait timeout")

    interruption_markers = (
        "Failed to construct element query matching interruption.",
        "Interrupting element BannerNotification",
        "NotificationShortLookView",
        "foreground application Application 'com.apple.springboard'",
    )
    if not all(marker in log for marker in interruption_markers):
        raise ContractError("log does not prove an external SpringBoard notification interruption")
    forbidden_markers = (
        "generation failed",
        "audio_qc",
        "fatal error",
        "application crashed",
    )
    if any(marker in log.lower() for marker in forbidden_markers):
        raise ContractError("product or crash evidence forbids external interruption classification")
    result = {
        "schemaVersion": 1,
        "status": "infrastructure_external_interruption",
        "runID": run_id,
        "testCaseCount": count,
        "notificationKind": "springboard_banner",
        "xcodebuildLogSHA256": digest_bytes(log_path.read_bytes()),
        "xcresultSummarySHA256": digest_bytes(summary_path.read_bytes()),
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
    exit_parser = sub.add_parser("compose-process-exit")
    exit_parser.add_argument("--plan", required=True, type=Path)
    exit_parser.add_argument("--artifact-dir", required=True, type=Path)
    exit_parser.add_argument("--run-id", required=True)
    exit_parser.add_argument("--output", required=True, type=Path)
    crash_parser = sub.add_parser("sanitize-system-crashes")
    crash_parser.add_argument("--input-dir", required=True, type=Path)
    crash_parser.add_argument("--output", required=True, type=Path)
    crash_parser.add_argument("--process", action="append", required=True)
    bootstrap_parser = sub.add_parser("classify-xcui-bootstrap")
    bootstrap_parser.add_argument("--xcodebuild-log", required=True, type=Path)
    bootstrap_parser.add_argument("--xcresult-summary", required=True, type=Path)
    bootstrap_parser.add_argument("--run-id", required=True)
    bootstrap_parser.add_argument("--output", required=True, type=Path)
    interruption_parser = sub.add_parser("classify-xcui-external-interruption")
    interruption_parser.add_argument("--xcodebuild-log", required=True, type=Path)
    interruption_parser.add_argument("--xcresult-summary", required=True, type=Path)
    interruption_parser.add_argument("--run-id", required=True)
    interruption_parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "prepare":
            prepare(args.plan, args.script_file, args.run_id, args.sanitized_output, args.launch_output)
        elif args.command == "validate-result":
            validate_result(args.plan, args.artifact_dir, args.run_id)
        elif args.command == "validate-ui-parity":
            validate_ui_parity(args.xcodebuild_log, args.diagnostics, args.run_id, args.output)
        elif args.command == "compose-process-exit":
            compose_process_exit(args.plan, args.artifact_dir, args.run_id, args.output)
        elif args.command == "sanitize-system-crashes":
            sanitize_system_crashes(args.input_dir, args.output, set(args.process))
        elif args.command == "classify-xcui-bootstrap":
            classify_xcui_bootstrap(
                args.xcodebuild_log,
                args.xcresult_summary,
                args.run_id,
                args.output,
            )
        else:
            classify_xcui_external_interruption(
                args.xcodebuild_log,
                args.xcresult_summary,
                args.run_id,
                args.output,
            )
    except (ContractError, json.JSONDecodeError, OSError) as error:
        print(f"startup reliability contract failed: {error}", file=os.sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
