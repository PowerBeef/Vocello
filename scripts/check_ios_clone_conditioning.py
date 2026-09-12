#!/usr/bin/env python3
"""Validate the local two-take physical-iPhone clone-conditioning proof.

This command writes one compact untracked validation summary. It never creates a
benchmark-evidence manifest and never publishes benchmark history.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import tempfile
from typing import Any
import uuid

from benchmark_memory import MemoryEvidenceError, qualify_memory_rows
from publish_benchmark_history import (
    PublicationError,
    correlated_ios_app_rows,
    crash_delta_from_snapshot,
    load_engine_rows,
    rows_by_generation,
    source_from_snapshot,
    successful_row,
)
from lib import jsonio  # noqa: E402


DIGEST = re.compile(r"^[0-9a-f]{64}$")
SAFE_LABEL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,95}$")
VALIDATOR_VERSION = "ios-clone-conditioning-v1"
EXPECTED_SEED = 19_790_615
EXPECTED_VARIATION = "consistent"
EXPECTED_TAKES = (
    {
        "takeIndex": 1,
        "cell": "clone/speed/conditioning/transcript-backed",
        "mode": "clone",
        "conditioningMode": "transcript_backed",
        "transcriptMode": "inline",
        "promptArtifactScope": "saved_voice",
        "transcriptBacked": True,
        "xVectorOnly": False,
        "outputFileName": "take-01-transcript_backed.wav",
    },
    {
        "takeIndex": 2,
        "cell": "clone/speed/conditioning/x-vector-only",
        "mode": "clone",
        "conditioningMode": "x_vector_only",
        "transcriptMode": "none",
        "promptArtifactScope": "transient_reference",
        "transcriptBacked": False,
        "xVectorOnly": True,
        "outputFileName": "take-02-x_vector_only.wav",
    },
)
TOP_LEVEL_FIELDS = {
    "schemaVersion", "status", "runID", "startedAt", "finishedAt", "seed",
    "samplingVariation", "voiceIDDigest", "referenceAudioSHA256",
    "referenceTranscriptSHA256", "scratchCleanupVerified", "takes",
}
TAKE_FIELDS = {
    "takeIndex", "generationID", "cell", "mode", "modelID", "conditioningMode",
    "transcriptMode", "promptArtifactScope", "transcriptBacked", "xVectorOnly",
    "supportsXVectorOnlyClone", "optimizedHandlerUsed", "promptMaterialized",
    "conditioningReused", "preparedCloneCacheHit", "referenceAudioSHA256",
    "promptAssemblySHA256", "wallSeconds", "outputFileName", "outputEvidence",
    "outputVerification",
}
OUTPUT_FIELDS = {
    "artifactRelativePath", "sha256", "byteCount", "durationSeconds", "sampleRate",
    "channelCount", "frameCount",
}


class CloneConditioningValidationError(ValueError):
    pass


def load_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise CloneConditioningValidationError(f"cannot read {path.name}: {error}") from error
    if not isinstance(value, dict):
        raise CloneConditioningValidationError(f"{path.name} must contain one JSON object")
    return value


sha256_file = jsonio.sha256_file


def require_digest(value: Any, field: str) -> str:
    if not isinstance(value, str) or DIGEST.fullmatch(value) is None:
        raise CloneConditioningValidationError(f"{field} must be a lowercase SHA-256 digest")
    return value


def require_positive_number(value: Any, field: str) -> float:
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not math.isfinite(float(value))
        or float(value) <= 0
    ):
        raise CloneConditioningValidationError(f"{field} must be finite and positive")
    return float(value)


def validate_output_evidence(take: dict[str, Any], outputs: Path) -> str:
    evidence = take.get("outputEvidence")
    if not isinstance(evidence, dict) or set(evidence) != OUTPUT_FIELDS:
        raise CloneConditioningValidationError("outputEvidence has an unsupported shape")
    output_name = take.get("outputFileName")
    if not isinstance(output_name, str) or Path(output_name).name != output_name:
        raise CloneConditioningValidationError("outputFileName must be one safe basename")
    if evidence.get("artifactRelativePath") != f"outputs/{output_name}":
        raise CloneConditioningValidationError("outputEvidence artifact scope changed")
    digest = require_digest(evidence.get("sha256"), "outputEvidence.sha256")
    byte_count = evidence.get("byteCount")
    if not isinstance(byte_count, int) or isinstance(byte_count, bool) or byte_count <= 0:
        raise CloneConditioningValidationError("outputEvidence.byteCount must be positive")
    for field in ("durationSeconds", "sampleRate", "channelCount", "frameCount"):
        require_positive_number(evidence.get(field), f"outputEvidence.{field}")

    output = outputs / output_name
    if not output.is_file() or output.is_symlink():
        raise CloneConditioningValidationError(f"missing exact output {output_name}")
    if output.stat().st_size != byte_count or sha256_file(output) != digest:
        raise CloneConditioningValidationError(f"output identity mismatch for {output_name}")
    return digest


def validate_output_verification(take: dict[str, Any]) -> None:
    verification = take.get("outputVerification")
    if not isinstance(verification, dict):
        raise CloneConditioningValidationError("outputVerification is missing")
    if (
        verification.get("schemaVersion") != 3
        or verification.get("algorithmVersion") != "language-output-verifier-v3"
        or verification.get("expectedLanguage") != "english"
        or verification.get("pass") is not True
        or verification.get("languagePass") is not True
        or verification.get("accuracyPass") is not True
    ):
        raise CloneConditioningValidationError("clone output did not pass strict English verification")


def validate_result_contract(
    payload: dict[str, Any],
    *,
    run_id: str,
    expected_voice_id: str,
    expected_audio_sha256: str,
    expected_transcript_sha256: str,
    outputs: Path,
) -> list[dict[str, Any]]:
    if set(payload) != TOP_LEVEL_FIELDS:
        raise CloneConditioningValidationError("result has an unsupported top-level shape")
    if payload.get("schemaVersion") != 1 or payload.get("status") != "pass":
        raise CloneConditioningValidationError("result is not a schema-v1 PASS record")
    if payload.get("runID") != run_id:
        raise CloneConditioningValidationError("result run identity changed")
    if payload.get("seed") != EXPECTED_SEED or payload.get("samplingVariation") != EXPECTED_VARIATION:
        raise CloneConditioningValidationError("fixed sampling policy changed")
    expected_audio_sha256 = require_digest(expected_audio_sha256, "expected audio SHA-256")
    expected_transcript_sha256 = require_digest(
        expected_transcript_sha256, "expected transcript SHA-256"
    )
    if (
        payload.get("voiceIDDigest") != hashlib.sha256(expected_voice_id.encode("utf-8")).hexdigest()
        or payload.get("referenceAudioSHA256") != expected_audio_sha256
        or payload.get("referenceTranscriptSHA256") != expected_transcript_sha256
        or payload.get("scratchCleanupVerified") is not True
    ):
        raise CloneConditioningValidationError("fixture identity or scratch-cleanup proof changed")

    takes = payload.get("takes")
    if not isinstance(takes, list) or len(takes) != 2:
        raise CloneConditioningValidationError("exactly two ordered clone takes are required")
    generation_ids: set[str] = set()
    prompt_digests: set[str] = set()
    model_ids: set[str] = set()
    for take, expected in zip(takes, EXPECTED_TAKES):
        if not isinstance(take, dict) or set(take) != TAKE_FIELDS:
            raise CloneConditioningValidationError("clone take has an unsupported shape")
        for field, expected_value in expected.items():
            if take.get(field) != expected_value:
                raise CloneConditioningValidationError(
                    f"take {expected['takeIndex']} changed {field}"
                )
        try:
            generation_id = str(uuid.UUID(str(take.get("generationID"))))
        except ValueError as error:
            raise CloneConditioningValidationError("take generationID is invalid") from error
        generation_ids.add(generation_id.lower())
        prompt_digests.add(require_digest(take.get("promptAssemblySHA256"), "promptAssemblySHA256"))
        if (
            take.get("supportsXVectorOnlyClone") is not True
            or take.get("optimizedHandlerUsed") is not True
            or take.get("promptMaterialized") is not True
            or take.get("referenceAudioSHA256") != expected_audio_sha256
        ):
            raise CloneConditioningValidationError("runtime clone capability proof is incomplete")
        if not isinstance(take.get("conditioningReused"), bool) or not isinstance(
            take.get("preparedCloneCacheHit"), bool
        ):
            raise CloneConditioningValidationError("clone cache diagnostics must be boolean")
        model_id = take.get("modelID")
        if not isinstance(model_id, str) or not model_id:
            raise CloneConditioningValidationError("clone model identity is missing")
        model_ids.add(model_id)
        require_positive_number(take.get("wallSeconds"), "wallSeconds")
        validate_output_verification(take)
        validate_output_evidence(take, outputs)
    if len(generation_ids) != 2 or len(prompt_digests) != 2 or len(model_ids) != 1:
        raise CloneConditioningValidationError(
            "takes must use unique generations, distinct prompt identities, and one model"
        )
    return takes


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    jsonio.atomic_json(path, payload, allow_nan=False)


def validate(args: argparse.Namespace) -> dict[str, Any]:
    payload = load_object(args.result)
    takes = validate_result_contract(
        payload,
        run_id=args.run_id,
        expected_voice_id=args.expected_voice_id,
        expected_audio_sha256=args.expected_audio_sha256,
        expected_transcript_sha256=args.expected_transcript_sha256,
        outputs=args.outputs,
    )
    generation_ids = [str(take["generationID"]) for take in takes]
    engine_rows = rows_by_generation(load_engine_rows(args.diagnostics), generation_ids)
    for index, (row, take) in enumerate(zip(engine_rows, takes), start=1):
        successful_row(row)
        notes = row.get("notes") if isinstance(row.get("notes"), dict) else {}
        if (
            int(row.get("schemaVersion", 0)) < 8
            or row.get("layer") != "engine"
            or row.get("mode") != "clone"
            or row.get("modelID") != take.get("modelID")
            or row.get("usedStreaming") is not True
            or notes.get("benchRunID") != args.run_id
            or notes.get("benchCell") != take.get("cell")
            or str(notes.get("benchTakeIndex", "")) != str(index)
        ):
            raise CloneConditioningValidationError(
                f"take {index} engine telemetry identity is invalid"
            )
    app_rows = correlated_ios_app_rows(
        diagnostics=args.diagnostics,
        engine_rows=engine_rows,
        takes=takes,
        run_id=args.run_id,
    )
    _, memory = qualify_memory_rows(
        rows=engine_rows,
        diagnostics=args.diagnostics,
        platform="ios",
        app_rows=app_rows,
        require_app_layer=False,
    )
    source = source_from_snapshot(args.snapshot)
    if source.get("fingerprintsMatch") is not True:
        raise CloneConditioningValidationError("source changed during clone-conditioning acceptance")
    crash = crash_delta_from_snapshot(
        args.snapshot,
        expected_scope="ios",
        diagnostics=args.crash_diagnostics,
    )
    warnings = memory.get("warnings") if isinstance(memory.get("warnings"), list) else []
    return {
        "schemaVersion": 1,
        "validatorVersion": VALIDATOR_VERSION,
        "status": "passedWithWarnings" if warnings else "passed",
        "runID": args.run_id,
        "label": args.label,
        "takeCount": 2,
        "conditioningModes": [take["conditioningMode"] for take in takes],
        "generationIDs": generation_ids,
        "promptAssemblyDigests": [take["promptAssemblySHA256"] for take in takes],
        "referenceAudioSHA256": args.expected_audio_sha256,
        "referenceTranscriptSHA256": args.expected_transcript_sha256,
        "outputDigests": [take["outputEvidence"]["sha256"] for take in takes],
        "telemetrySchemaVersion": min(int(row["schemaVersion"]) for row in engine_rows),
        "appLayerCount": len(app_rows),
        "memoryQualified": memory.get("memoryQualified") is True,
        "memoryStatus": memory.get("status"),
        "memoryWarnings": warnings,
        "source": {
            "commit": source.get("commit"),
            "dirty": source.get("dirty"),
            "fingerprintsMatch": source.get("fingerprintsMatch"),
        },
        "crashDelta": crash,
        "historyPublished": False,
    }


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser()
    result.add_argument("--result", type=Path, required=True)
    result.add_argument("--diagnostics", type=Path, required=True)
    result.add_argument("--outputs", type=Path, required=True)
    result.add_argument("--snapshot", type=Path, required=True)
    result.add_argument("--crash-diagnostics", type=Path, required=True)
    result.add_argument("--run-id", required=True)
    result.add_argument("--label", required=True)
    result.add_argument("--expected-voice-id", required=True)
    result.add_argument("--expected-audio-sha256", required=True)
    result.add_argument("--expected-transcript-sha256", required=True)
    result.add_argument("--output", type=Path, required=True)
    return result


def main() -> int:
    args = parser().parse_args()
    if SAFE_LABEL.fullmatch(args.run_id) is None or SAFE_LABEL.fullmatch(args.label) is None:
        print("clone-conditioning validation FAIL: unsafe run ID or label")
        return 2
    try:
        summary = validate(args)
        atomic_json(args.output, summary)
    except (
        CloneConditioningValidationError,
        PublicationError,
        MemoryEvidenceError,
        OSError,
        RuntimeError,
    ) as error:
        print(f"clone-conditioning validation FAIL: {error}")
        return 1
    print(
        "clone-conditioning validation PASS: "
        f"{summary['takeCount']} takes, modes={','.join(summary['conditioningModes'])}, "
        f"historyPublished={summary['historyPublished']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
