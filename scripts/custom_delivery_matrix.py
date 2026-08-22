#!/usr/bin/env python3
"""Autonomous Built-in Voice × shipped-delivery diagnostic matrix.

This lane exercises the production ``vocello bench`` path for every speaker in
the checked-in contract and every product-visible delivery preset at its shipped
tier.  It is deliberately exploratory: the fixed English medium script is a
speaker-generalization probe, not a replacement for the independently labelled
multi-script/language holdout required for promotion.

The runner is resumable at the speaker/seed boundary. Every completed unit must
have exactly one outcome for each shipped preset: either a fully analyzed WAV
or an allowlisted generation failure. Matching speaker/seed receipts are
mandatory; missing, duplicate, and malformed outcomes fail the aggregate and
failures remain in the statistical denominator.

Usage:
  scripts/custom_delivery_matrix.py run [--seeds 20261001,20261002]
  scripts/custom_delivery_matrix.py report --output build/artifacts/.../run
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import re
from datetime import datetime, timezone
from typing import Any, Iterable

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from delivery_matrix_report import build_report, load_matrix
from delivery_separability import records_from_sidecar
from delivery_statistics import wilson_interval


REPO = Path(__file__).resolve().parents[1]
SCHEMA_VERSION = 2
DEFAULT_SEEDS = tuple(range(20261001, 20261006))
UNIT_TIMEOUT_SECONDS = 20 * 60
EXPECTED_SPEAKERS = frozenset(
    {"aiden", "ryan", "vivian", "serena", "uncle_fu", "dylan", "eric", "ono_anna", "sohee"}
)
EXPECTED_PRESETS = frozenset(
    {"neutral", "happy", "sad", "angry", "fearful", "surprised", "calm", "whisper"}
)
ANALYSIS_HARNESS_PATHS = (
    "scripts/custom_delivery_matrix.py",
    "scripts/bench_delivery_prosody.py",
    "scripts/analyze_prosody.py",
    "scripts/delivery_quality_gate.py",
    "scripts/delivery_matrix_report.py",
    "scripts/delivery_separability.py",
    "scripts/delivery_statistics.py",
    "scripts/prosody_profile.py",
)
ALLOWED_FAILURE_REASONS = frozenset({
    "fast_qc_dropout",
    "fast_qc_failure",
    "cancelled",
    "generation_token_limit",
    "generation_failed",
})
QUALITY_FLAG_PATTERN = re.compile(
    r"^(?:dropout:(?:[0-9]+ms|excess[0-9]+\([0-9]+/[0-9]+\))|"
    r"nonfinite|empty|near_silent|low_level|silent|clipping|clicks|hot|dc_offset)$"
)
HEX_DIGEST_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class MatrixError(RuntimeError):
    """A fail-closed matrix contract violation."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def profile_digest(profile: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(
            profile,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("utf-8")
    ).hexdigest()


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def parse_json_command(command: list[str], *, env: dict[str, str]) -> Any:
    result = subprocess.run(
        command,
        cwd=REPO,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise MatrixError(
            f"command failed ({result.returncode}): {' '.join(command)}\n{result.stderr.strip()}"
        )
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise MatrixError(f"command did not emit JSON: {' '.join(command)}") from error


def discover_rosters(binary: Path, data_dir: Path, env: dict[str, str]) -> tuple[list[dict], list[dict]]:
    speakers = parse_json_command(
        [str(binary), "speakers", "list", "--json", "--data-dir", str(data_dir)], env=env
    )
    deliveries = parse_json_command(
        [str(binary), "deliveries", "--shipped-only", "--json"], env=env
    )
    if not isinstance(speakers, list) or not isinstance(deliveries, list):
        raise MatrixError("speaker and delivery roster commands must emit JSON arrays")
    speaker_ids = [row.get("id") for row in speakers if isinstance(row, dict)]
    preset_ids = [row.get("preset") for row in deliveries if isinstance(row, dict)]
    if len(speaker_ids) != len(set(speaker_ids)):
        raise MatrixError("speaker roster contains duplicate ids")
    if len(preset_ids) != len(set(preset_ids)):
        raise MatrixError("shipped delivery roster contains duplicate presets")
    if set(speaker_ids) != EXPECTED_SPEAKERS:
        raise MatrixError(
            f"speaker roster mismatch: expected {sorted(EXPECTED_SPEAKERS)}, got {sorted(speaker_ids)}"
        )
    if set(preset_ids) != EXPECTED_PRESETS:
        raise MatrixError(
            f"delivery roster mismatch: expected {sorted(EXPECTED_PRESETS)}, got {sorted(preset_ids)}"
        )
    for row in deliveries:
        if not isinstance(row.get("id"), str) or not row["id"]:
            raise MatrixError("every shipped delivery needs an exact id")
        if not isinstance(row.get("instruction"), str) or not row["instruction"].strip():
            raise MatrixError(f"shipped delivery {row.get('preset')} has no instruction")
    return speakers, deliveries


def source_identity(binary: Path, speakers: list[dict], deliveries: list[dict]) -> dict[str, Any]:
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=REPO, check=True, capture_output=True, text=True
    ).stdout.strip()
    dirty = subprocess.run(
        ["git", "status", "--short"], cwd=REPO, check=True, capture_output=True, text=True
    ).stdout.splitlines()
    encoded_roster = json.dumps(
        {"speakers": speakers, "deliveries": deliveries},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    harness_files = {
        relative: file_sha256(REPO / relative) for relative in ANALYSIS_HARNESS_PATHS
    }
    harness_digest = hashlib.sha256(
        json.dumps(harness_files, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    diff = subprocess.run(
        ["git", "diff", "--no-ext-diff", "--binary", "HEAD"],
        cwd=REPO,
        check=True,
        capture_output=True,
    ).stdout
    try:
        import numpy as np
        numpy_version = np.__version__
    except ImportError:
        numpy_version = None
    return {
        "gitCommit": head,
        "dirty": bool(dirty),
        "dirtyPathCount": len(dirty),
        "binarySHA256": file_sha256(binary),
        "contractSHA256": file_sha256(REPO / "Sources/Resources/qwenvoice_contract.json"),
        "deliveryContractSHA256": file_sha256(REPO / "config/delivery-instruction-contract.json"),
        "rosterSHA256": hashlib.sha256(encoded_roster).hexdigest(),
        "gitDiffSHA256": hashlib.sha256(diff).hexdigest(),
        "analysisHarnessSHA256": harness_digest,
        "analysisHarnessFiles": harness_files,
        "pythonVersion": sys.version.split()[0],
        "numpyVersion": numpy_version,
    }


def unit_key(speaker_id: str, seed: int) -> str:
    return f"{speaker_id}__{seed}"


def validate_sidecar(
    rows: Any,
    *,
    speaker_id: str,
    seed: int,
    deliveries: list[dict],
) -> list[dict]:
    if not isinstance(rows, list):
        raise MatrixError(f"{speaker_id}/{seed}: sidecar must be a JSON array")
    expected = {row["id"] for row in deliveries}
    observed: list[str] = []
    generation_ids: set[str] = set()
    analyzer_versions: set[int] = set()
    for row in rows:
        if not isinstance(row, dict):
            raise MatrixError(f"{speaker_id}/{seed}: non-object analysis row")
        delivery = row.get("delivery")
        if delivery not in expected:
            raise MatrixError(f"{speaker_id}/{seed}: unexpected delivery {delivery!r}")
        observed.append(delivery)
        if row.get("speakerID") != speaker_id:
            raise MatrixError(
                f"{speaker_id}/{seed}: row speaker receipt is {row.get('speakerID')!r}"
            )
        if row.get("seed") != seed:
            raise MatrixError(f"{speaker_id}/{seed}: row seed receipt is {row.get('seed')!r}")
        if not isinstance(row.get("neutralReferenceAccepted"), bool):
            raise MatrixError(f"{speaker_id}/{seed}: row has no neutral reference verdict")
        reference_flags = row.get("neutralReferenceQualityFlags")
        if not isinstance(reference_flags, list) or any(
            not isinstance(flag, str) or QUALITY_FLAG_PATTERN.fullmatch(flag) is None
            for flag in reference_flags
        ):
            raise MatrixError(f"{speaker_id}/{seed}: row has invalid neutral reference flags")
        if row["neutralReferenceAccepted"] and reference_flags:
            raise MatrixError(f"{speaker_id}/{seed}: accepted neutral carries rejection flags")
        if not row["neutralReferenceAccepted"] and not reference_flags:
            raise MatrixError(f"{speaker_id}/{seed}: rejected neutral lacks exact QC flags")
        generation_id = row.get("generationID")
        if not isinstance(generation_id, str) or not generation_id:
            raise MatrixError(f"{speaker_id}/{seed}: row has no generation id")
        if generation_id in generation_ids:
            raise MatrixError(f"{speaker_id}/{seed}: duplicate generation id {generation_id}")
        generation_ids.add(generation_id)
        for metric_name in ("deliveryMetrics", "neutralMetrics"):
            metrics = row.get(metric_name)
            if not isinstance(metrics, dict) or "error" in metrics:
                raise MatrixError(f"{speaker_id}/{seed}: {delivery} has invalid {metric_name}")
            version = metrics.get("analyzerAlgorithmVersion")
            if not isinstance(version, int):
                raise MatrixError(f"{speaker_id}/{seed}: {delivery} has no analyzer version")
            analyzer_versions.add(version)
            for name, value in metrics.items():
                if isinstance(value, float) and not math.isfinite(value):
                    raise MatrixError(f"{speaker_id}/{seed}: {delivery}.{name} is non-finite")
        gate = row.get("deliveryGate")
        if not isinstance(gate, dict) or not isinstance(gate.get("metrics"), dict):
            raise MatrixError(f"{speaker_id}/{seed}: {delivery} has no delivery gate metrics")
        profile_digest = row.get("profileDigest")
        if (
            not isinstance(profile_digest, str)
            or HEX_DIGEST_PATTERN.fullmatch(profile_digest) is None
        ):
            raise MatrixError(f"{speaker_id}/{seed}: {delivery} has no profile digest")
    if len(observed) != len(set(observed)):
        raise MatrixError(f"{speaker_id}/{seed}: duplicate delivery rows: {observed}")
    if len(analyzer_versions) > 1:
        raise MatrixError(f"{speaker_id}/{seed}: mixed analyzer versions {sorted(analyzer_versions)}")
    return rows


def validate_unit_manifest(
    manifest: Any,
    *,
    speaker_id: str,
    seed: int,
    deliveries: list[dict],
) -> tuple[list[dict], list[dict]]:
    """Validate all planned cells as success-or-typed-failure, never retries."""
    if not isinstance(manifest, dict) or manifest.get("schemaVersion") != 1:
        raise MatrixError(f"{speaker_id}/{seed}: invalid bench manifest")
    if manifest.get("customSpeakerID") != speaker_id or manifest.get("seed") != seed:
        raise MatrixError(f"{speaker_id}/{seed}: manifest identity mismatch")
    takes = manifest.get("takes")
    reference_failures = manifest.get("referenceFailures", [])
    failures = manifest.get("deliveryFailures")
    if (
        not isinstance(takes, list)
        or not isinstance(reference_failures, list)
        or not isinstance(failures, list)
    ):
        raise MatrixError(
            f"{speaker_id}/{seed}: manifest lacks takes/referenceFailures/deliveryFailures"
        )
    expected = {row["id"]: row for row in deliveries}
    observed: list[str] = []
    normalized_references: list[dict] = []
    normalized_failures: list[dict] = []
    attempt_indices: set[int] = set()
    generation_ids: set[str] = set()
    neutral_warm = False
    rejected_neutral_warm = False
    for take in takes:
        if not isinstance(take, dict):
            raise MatrixError(f"{speaker_id}/{seed}: malformed take")
        index = take.get("takeIndex")
        generation_id = take.get("generationID")
        if not isinstance(index, int) or isinstance(index, bool) or index < 1:
            raise MatrixError(f"{speaker_id}/{seed}: invalid take index")
        if not isinstance(generation_id, str) or not generation_id:
            raise MatrixError(f"{speaker_id}/{seed}: invalid take generation id")
        if index in attempt_indices or generation_id in generation_ids:
            raise MatrixError(f"{speaker_id}/{seed}: duplicate take identity")
        attempt_indices.add(index)
        generation_ids.add(generation_id)
        delivery = take.get("delivery")
        if delivery is None:
            neutral_warm = neutral_warm or (
                take.get("mode") == "custom"
                and take.get("length") == "medium"
                and take.get("warmState") == "warm"
            )
            continue
        if delivery not in expected:
            raise MatrixError(f"{speaker_id}/{seed}: unexpected successful delivery {delivery!r}")
        if take.get("deliveryInstruction") != expected[delivery]["instruction"]:
            raise MatrixError(f"{speaker_id}/{seed}: {delivery} instruction echo mismatch")
        observed.append(delivery)
    for failure in reference_failures:
        if not isinstance(failure, dict):
            raise MatrixError(f"{speaker_id}/{seed}: malformed reference failure")
        index = failure.get("takeIndex")
        generation_id = failure.get("generationID")
        if not isinstance(index, int) or isinstance(index, bool) or index < 1:
            raise MatrixError(f"{speaker_id}/{seed}: invalid reference failure index")
        if not isinstance(generation_id, str) or not generation_id:
            raise MatrixError(f"{speaker_id}/{seed}: invalid reference failure generation id")
        if index in attempt_indices or generation_id in generation_ids:
            raise MatrixError(f"{speaker_id}/{seed}: duplicate reference failure identity")
        attempt_indices.add(index)
        generation_ids.add(generation_id)
        if failure.get("reasonCode") not in ALLOWED_FAILURE_REASONS:
            raise MatrixError(f"{speaker_id}/{seed}: invalid reference failure reason")
        quality_flags = failure.get("qualityFlags")
        if not isinstance(quality_flags, list) or any(
            not isinstance(flag, str) or QUALITY_FLAG_PATTERN.fullmatch(flag) is None
            for flag in quality_flags
        ):
            raise MatrixError(f"{speaker_id}/{seed}: invalid reference failure flags")
        if failure.get("reasonCode") == "fast_qc_dropout" and not quality_flags:
            raise MatrixError(f"{speaker_id}/{seed}: reference dropout lacks exact QC flag")
        error_digest = failure.get("errorDigest")
        if (
            not isinstance(error_digest, str)
            or HEX_DIGEST_PATTERN.fullmatch(error_digest) is None
        ):
            raise MatrixError(f"{speaker_id}/{seed}: invalid reference failure digest")
        rejected = failure.get("rejectedOutputFileName")
        if rejected is not None and (
            not isinstance(rejected, str) or not rejected or Path(rejected).name != rejected
        ):
            raise MatrixError(f"{speaker_id}/{seed}: invalid rejected reference WAV name")
        if failure.get("reasonCode") in {"fast_qc_dropout", "fast_qc_failure"} and rejected is None:
            raise MatrixError(f"{speaker_id}/{seed}: Fast-QC reference failure lacks rejected WAV")
        rejected_neutral_warm = rejected_neutral_warm or (
            failure.get("mode") == "custom"
            and failure.get("length") == "medium"
            and failure.get("warmState") == "warm"
            and rejected is not None
        )
        normalized_references.append({**failure, "speakerID": speaker_id, "seed": seed})
    if not neutral_warm and not rejected_neutral_warm:
        raise MatrixError(f"{speaker_id}/{seed}: missing analyzable neutral warm reference")
    for failure in failures:
        if not isinstance(failure, dict):
            raise MatrixError(f"{speaker_id}/{seed}: malformed failure")
        index = failure.get("takeIndex")
        generation_id = failure.get("generationID")
        delivery = failure.get("delivery")
        if not isinstance(index, int) or isinstance(index, bool) or index < 1:
            raise MatrixError(f"{speaker_id}/{seed}: invalid failure index")
        if not isinstance(generation_id, str) or not generation_id:
            raise MatrixError(f"{speaker_id}/{seed}: invalid failure generation id")
        if index in attempt_indices or generation_id in generation_ids:
            raise MatrixError(f"{speaker_id}/{seed}: duplicate failure identity")
        attempt_indices.add(index)
        generation_ids.add(generation_id)
        if delivery not in expected:
            raise MatrixError(f"{speaker_id}/{seed}: unexpected failed delivery {delivery!r}")
        if failure.get("reasonCode") not in ALLOWED_FAILURE_REASONS:
            raise MatrixError(f"{speaker_id}/{seed}: {delivery} has invalid failure reason")
        quality_flags = failure.get("qualityFlags")
        if not isinstance(quality_flags, list) or any(
            not isinstance(flag, str) or QUALITY_FLAG_PATTERN.fullmatch(flag) is None
            for flag in quality_flags
        ):
            raise MatrixError(f"{speaker_id}/{seed}: {delivery} has invalid quality flags")
        if failure.get("reasonCode") == "fast_qc_dropout" and not quality_flags:
            raise MatrixError(f"{speaker_id}/{seed}: {delivery} dropout lacks its exact QC flag")
        expected_digest = hashlib.sha256(expected[delivery]["instruction"].encode("utf-8")).hexdigest()
        if failure.get("deliveryInstructionDigest") != expected_digest:
            raise MatrixError(f"{speaker_id}/{seed}: {delivery} instruction digest mismatch")
        error_digest = failure.get("errorDigest")
        if (
            not isinstance(error_digest, str)
            or HEX_DIGEST_PATTERN.fullmatch(error_digest) is None
        ):
            raise MatrixError(f"{speaker_id}/{seed}: {delivery} has invalid error digest")
        rejected = failure.get("rejectedOutputFileName")
        if rejected is not None and (
            not isinstance(rejected, str) or not rejected or Path(rejected).name != rejected
        ):
            raise MatrixError(f"{speaker_id}/{seed}: {delivery} has invalid rejected WAV name")
        if failure.get("reasonCode") in {"fast_qc_dropout", "fast_qc_failure"} and rejected is None:
            raise MatrixError(f"{speaker_id}/{seed}: {delivery} Fast-QC failure lacks rejected WAV")
        observed.append(delivery)
        normalized_failures.append({
            **failure,
            "speakerID": speaker_id,
            "seed": seed,
        })
    if len(observed) != len(set(observed)):
        raise MatrixError(f"{speaker_id}/{seed}: duplicate delivery outcomes {observed}")
    if set(observed) != set(expected):
        raise MatrixError(
            f"{speaker_id}/{seed}: expected outcomes {sorted(expected)}, got {sorted(observed)}"
        )
    if sorted(attempt_indices) != list(range(1, len(attempt_indices) + 1)):
        raise MatrixError(f"{speaker_id}/{seed}: non-contiguous attempt indices")
    return normalized_failures, normalized_references


def validate_unit_evidence(
    rows: Any,
    failures: Any,
    *,
    reference_failures: Any = None,
    speaker_id: str,
    seed: int,
    deliveries: list[dict],
) -> tuple[list[dict], list[dict], list[dict]]:
    validated_rows = validate_sidecar(
        rows, speaker_id=speaker_id, seed=seed, deliveries=deliveries
    )
    if not isinstance(failures, list):
        raise MatrixError(f"{speaker_id}/{seed}: failures must be an array")
    if reference_failures is None:
        reference_failures = []
    if not isinstance(reference_failures, list):
        raise MatrixError(f"{speaker_id}/{seed}: reference failures must be an array")
    for failure in reference_failures:
        if not isinstance(failure, dict):
            raise MatrixError(f"{speaker_id}/{seed}: malformed retained reference failure")
        if failure.get("speakerID") != speaker_id or failure.get("seed") != seed:
            raise MatrixError(f"{speaker_id}/{seed}: retained reference identity mismatch")
        if failure.get("reasonCode") not in ALLOWED_FAILURE_REASONS:
            raise MatrixError(f"{speaker_id}/{seed}: invalid retained reference failure")
        flags = failure.get("qualityFlags")
        if not isinstance(flags, list) or any(
            not isinstance(flag, str) or QUALITY_FLAG_PATTERN.fullmatch(flag) is None
            for flag in flags
        ):
            raise MatrixError(f"{speaker_id}/{seed}: invalid retained reference flags")
        rejected = failure.get("rejectedOutputFileName")
        if failure.get("reasonCode") in {"fast_qc_dropout", "fast_qc_failure"} and not rejected:
            raise MatrixError(f"{speaker_id}/{seed}: retained Fast-QC reference lacks WAV")
    expected = {row["id"] for row in deliveries}
    success_ids = [row["delivery"] for row in validated_rows]
    failed_ids: list[str] = []
    for failure in failures:
        if not isinstance(failure, dict):
            raise MatrixError(f"{speaker_id}/{seed}: malformed retained failure")
        if failure.get("speakerID") != speaker_id or failure.get("seed") != seed:
            raise MatrixError(f"{speaker_id}/{seed}: retained failure identity mismatch")
        delivery = failure.get("delivery")
        if delivery not in expected or failure.get("reasonCode") not in ALLOWED_FAILURE_REASONS:
            raise MatrixError(f"{speaker_id}/{seed}: invalid retained failure")
        flags = failure.get("qualityFlags")
        if not isinstance(flags, list) or any(
            not isinstance(flag, str) or QUALITY_FLAG_PATTERN.fullmatch(flag) is None
            for flag in flags
        ):
            raise MatrixError(f"{speaker_id}/{seed}: invalid retained failure flags")
        rejected_analysis = failure.get("rejectedAnalysis")
        if failure.get("rejectedOutputFileName") is not None:
            if not isinstance(rejected_analysis, dict):
                raise MatrixError(f"{speaker_id}/{seed}: rejected WAV lacks analysis")
            metrics = rejected_analysis.get("deliveryMetrics")
            neutral_metrics = rejected_analysis.get("neutralMetrics")
            gate = rejected_analysis.get("deliveryGate")
            if (
                not isinstance(metrics, dict)
                or "error" in metrics
                or not isinstance(neutral_metrics, dict)
                or "error" in neutral_metrics
                or not isinstance(gate, dict)
                or not isinstance(gate.get("metrics"), dict)
            ):
                raise MatrixError(f"{speaker_id}/{seed}: invalid rejected WAV analysis")
            for analyzed in (metrics, neutral_metrics):
                if not isinstance(analyzed.get("analyzerAlgorithmVersion"), int):
                    raise MatrixError(f"{speaker_id}/{seed}: rejected WAV lacks analyzer identity")
                if any(
                    isinstance(value, float) and not math.isfinite(value)
                    for value in analyzed.values()
                ):
                    raise MatrixError(f"{speaker_id}/{seed}: rejected WAV analysis is non-finite")
            if rejected_analysis.get("deliveryID") != delivery:
                raise MatrixError(f"{speaker_id}/{seed}: rejected WAV delivery identity mismatch")
            neutral_accepted = rejected_analysis.get("neutralReferenceAccepted")
            neutral_flags = rejected_analysis.get("neutralReferenceQualityFlags")
            if not isinstance(neutral_accepted, bool) or not isinstance(neutral_flags, list):
                raise MatrixError(f"{speaker_id}/{seed}: rejected WAV lacks neutral reference verdict")
            if neutral_accepted != (len(neutral_flags) == 0):
                raise MatrixError(f"{speaker_id}/{seed}: rejected WAV neutral verdict is inconsistent")
        failed_ids.append(delivery)
    outcomes = success_ids + failed_ids
    if len(outcomes) != len(set(outcomes)) or set(outcomes) != expected:
        raise MatrixError(
            f"{speaker_id}/{seed}: success/failure outcome coverage mismatch: {outcomes}"
        )
    return validated_rows, failures, reference_failures


def analyze_rejected_failures(
    failures: list[dict],
    *,
    manifest: dict,
    diagnostics: Path,
    archive: Path,
    deliveries: list[dict],
) -> list[dict]:
    """Analyze retained rejected WAVs without upgrading them to successful takes."""
    if not failures:
        return []
    from analyze_prosody import analyze as analyze_wav
    from bench_delivery_prosody import load_engine_provenance
    from delivery_quality_gate import evaluate_delivery
    from prosody_profile import builtin_profile

    neutral = next((
        take for take in manifest["takes"]
        if take.get("delivery") is None
        and take.get("mode") == "custom"
        and take.get("length") == "medium"
        and take.get("warmState") == "warm"
    ), None)
    neutral_accepted = neutral is not None
    if neutral is None:
        neutral = next((
            failure for failure in manifest.get("referenceFailures", [])
            if failure.get("mode") == "custom"
            and failure.get("length") == "medium"
            and failure.get("warmState") == "warm"
            and failure.get("rejectedOutputFileName")
        ), None)
    if neutral is None:
        raise MatrixError("rejected analysis has no neutral warm reference")
    neutral_file_name = (
        neutral["outputFileName"] if neutral_accepted else neutral["rejectedOutputFileName"]
    )
    neutral_path = archive / neutral_file_name
    neutral_metrics = analyze_wav(str(neutral_path))
    if "error" in neutral_metrics:
        raise MatrixError("rejected analysis failed on the neutral warm reference")
    profile = builtin_profile()
    resolved_profile_digest = profile_digest(profile)
    provenance = load_engine_provenance(diagnostics, manifest["runID"])
    neutral_receipt = provenance.get(neutral["generationID"])
    if neutral_receipt is None or neutral_receipt.get("instructChars"):
        raise MatrixError("rejected analysis neutral provenance is missing or instructed")
    expected = {row["id"]: row for row in deliveries}
    enriched: list[dict] = []
    for failure in failures:
        result = dict(failure)
        receipt = provenance.get(failure["generationID"])
        if receipt is None or receipt.get("instructDigest") != failure["deliveryInstructionDigest"]:
            raise MatrixError(
                f"{failure['speakerID']}/{failure['seed']}: {failure['delivery']} "
                "failure lacks an exact engine instruction receipt"
            )
        if receipt.get("seed") not in {None, failure["seed"]}:
            raise MatrixError(
                f"{failure['speakerID']}/{failure['seed']}: failed delivery seed receipt mismatch"
            )
        file_name = failure.get("rejectedOutputFileName")
        if file_name is not None:
            rejected_path = archive / file_name
            if not rejected_path.is_file():
                raise MatrixError(f"rejected WAV was not archived: {file_name}")
            delivery_metrics = analyze_wav(str(rejected_path))
            if "error" in delivery_metrics:
                raise MatrixError(f"prosody analysis failed for rejected WAV: {file_name}")
            result["rejectedAnalysis"] = {
                "archiveFile": file_name,
                "deliveryMetrics": delivery_metrics,
                "neutralMetrics": neutral_metrics,
                "deliveryGate": evaluate_delivery(
                    delivery_metrics,
                    neutral_metrics,
                    failure["delivery"],
                    profile,
                ),
                "deliveryID": expected[failure["delivery"]]["id"],
                "instructionDigest": failure["deliveryInstructionDigest"],
                "neutralReferenceAccepted": neutral_accepted,
                "neutralReferenceQualityFlags": (
                    [] if neutral_accepted else list(neutral.get("qualityFlags") or [])
                ),
                "profileDigest": resolved_profile_digest,
            }
        enriched.append(result)
    return enriched


def validate_complete_matrix(
    evidence_paths: Iterable[Path],
    speakers: list[dict],
    deliveries: list[dict],
    seeds: list[int],
) -> tuple[list[dict], list[dict], list[dict], list[str], list[Path]]:
    expected_units = {unit_key(speaker["id"], seed) for speaker in speakers for seed in seeds}
    rows: list[dict] = []
    failures: list[dict] = []
    reference_failures: list[dict] = []
    units: list[str] = []
    sidecars: list[Path] = []
    for evidence_path in evidence_paths:
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
        if not isinstance(evidence, dict) or evidence.get("schemaVersion") != SCHEMA_VERSION:
            raise MatrixError(f"{evidence_path.parent.name}: invalid unit evidence schema")
        speaker = evidence.get("speakerID")
        seed = evidence.get("seed")
        if not isinstance(speaker, str) or not isinstance(seed, int) or isinstance(seed, bool):
            raise MatrixError(f"{evidence_path.parent.name}: invalid unit evidence identity")
        key = unit_key(speaker, seed)
        if evidence.get("unit") != key or evidence_path.parent.name != key:
            raise MatrixError(f"{key}: unit evidence path or identity mismatch")
        if key in units:
            raise MatrixError(f"duplicate matrix unit {key}")
        sidecar = evidence_path.parent / "bench-prosody.json"
        if not sidecar.is_file():
            raise MatrixError(f"{key}: missing analysis sidecar")
        unit_rows = json.loads(sidecar.read_text(encoding="utf-8"))
        unit_rows, unit_failures, unit_reference_failures = validate_unit_evidence(
            unit_rows,
            evidence.get("deliveryFailures"),
            reference_failures=evidence.get("referenceFailures"),
            speaker_id=speaker,
            seed=seed,
            deliveries=deliveries,
        )
        rows.extend(unit_rows)
        failures.extend(unit_failures)
        reference_failures.extend(unit_reference_failures)
        units.append(key)
        if unit_rows:
            sidecars.append(sidecar)
    if set(units) != expected_units:
        missing = sorted(expected_units - set(units))
        extra = sorted(set(units) - expected_units)
        raise MatrixError(f"matrix coverage mismatch; missing={missing}, extra={extra}")
    expected_outcomes = len(speakers) * len(deliveries) * len(seeds)
    if len(rows) + len(failures) != expected_outcomes:
        raise MatrixError(
            f"matrix has {len(rows) + len(failures)} outcomes; expected {expected_outcomes}"
        )
    return rows, failures, reference_failures, sorted(units), sidecars


def adherence_summary(rows: list[dict], speakers: list[dict], deliveries: list[dict]) -> dict[str, Any]:
    def summarize(cohort: list[dict]) -> dict[str, Any]:
        passed = sum(row.get("deliveryGate", {}).get("passed") is True for row in cohort)
        interval = wilson_interval(passed, len(cohort))
        flags: dict[str, int] = {}
        for row in cohort:
            for flag in row.get("deliveryGate", {}).get("flags") or []:
                flags[str(flag)] = flags.get(str(flag), 0) + 1
        return {
            "passed": passed,
            "total": len(cohort),
            "passRate": interval["rate"],
            "passRateLower95": interval["lower"],
            "passRateUpper95": interval["upper"],
            "flags": dict(sorted(flags.items())),
        }

    return {
        "overall": summarize(rows),
        "bySpeaker": {
            speaker["id"]: summarize([row for row in rows if row["speakerID"] == speaker["id"]])
            for speaker in speakers
        },
        "byDelivery": {
            delivery["id"]: summarize([row for row in rows if row["delivery"] == delivery["id"]])
            for delivery in deliveries
        },
        "bySpeakerAndDelivery": {
            f"{speaker['id']}::{delivery['id']}": summarize([
                row for row in rows
                if row["speakerID"] == speaker["id"] and row["delivery"] == delivery["id"]
            ])
            for speaker in speakers
            for delivery in deliveries
        },
    }


def generation_failure_summary(failures: list[dict]) -> dict[str, Any]:
    reasons: dict[str, int] = {}
    quality_flags: dict[str, int] = {}
    by_delivery: dict[str, int] = {}
    for failure in failures:
        reason = str(failure["reasonCode"])
        delivery = str(failure["delivery"])
        reasons[reason] = reasons.get(reason, 0) + 1
        by_delivery[delivery] = by_delivery.get(delivery, 0) + 1
        for flag in failure.get("qualityFlags") or []:
            quality_flags[str(flag)] = quality_flags.get(str(flag), 0) + 1
    return {
        "total": len(failures),
        "rejectedAudioAnalysisCount": sum(
            isinstance(failure.get("rejectedAnalysis"), dict) for failure in failures
        ),
        "byReason": dict(sorted(reasons.items())),
        "byQualityFlag": dict(sorted(quality_flags.items())),
        "byDelivery": dict(sorted(by_delivery.items())),
    }


def reference_failure_summary(failures: list[dict]) -> dict[str, Any]:
    reasons: dict[str, int] = {}
    quality_flags: dict[str, int] = {}
    by_state: dict[str, int] = {}
    for failure in failures:
        reason = str(failure["reasonCode"])
        state = str(failure.get("warmState") or "unknown")
        reasons[reason] = reasons.get(reason, 0) + 1
        by_state[state] = by_state.get(state, 0) + 1
        for flag in failure.get("qualityFlags") or []:
            quality_flags[str(flag)] = quality_flags.get(str(flag), 0) + 1
    return {
        "total": len(failures),
        "byReason": dict(sorted(reasons.items())),
        "byQualityFlag": dict(sorted(quality_flags.items())),
        "byWarmState": dict(sorted(by_state.items())),
    }


def adherence_outcomes(
    rows: list[dict],
    failures: list[dict],
    *,
    include_rejected_audio: bool,
) -> list[dict]:
    outcomes = list(rows)
    for failure in failures:
        rejected = failure.get("rejectedAnalysis")
        failed_gate = {
            "passed": False,
            "flags": [f"generation_failure:{failure['reasonCode']}"],
            "metrics": {},
        }
        outcomes.append({
            "speakerID": failure["speakerID"],
            "seed": failure["seed"],
            "delivery": failure["delivery"],
            "deliveryGate": (
                rejected["deliveryGate"]
                if include_rejected_audio and isinstance(rejected, dict)
                else failed_gate
            ),
        })
    return outcomes


def exact_paired_binary_p(candidate_only: int, baseline_only: int) -> float | None:
    discordant = candidate_only + baseline_only
    if discordant == 0:
        return None
    tail = min(candidate_only, baseline_only)
    probability = sum(math.comb(discordant, index) for index in range(tail + 1)) / (2 ** discordant)
    return round(min(1.0, 2.0 * probability), 6)


def load_comparison_outcomes(output: Path) -> tuple[dict[str, Any], dict[tuple[str, int, str], dict]]:
    plan = json.loads((output / "matrix-plan.json").read_text(encoding="utf-8"))
    outcomes: dict[tuple[str, int, str], dict] = {}
    for evidence_path in sorted((output / "units").glob("*/evidence.json")):
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
        speaker = evidence["speakerID"]
        seed = evidence["seed"]
        rows = json.loads((evidence_path.parent / "bench-prosody.json").read_text(encoding="utf-8"))
        for row in rows:
            key = (speaker, seed, row["delivery"])
            if key in outcomes:
                raise MatrixError(f"duplicate comparison outcome {key}")
            outcomes[key] = {
                "productPassed": row["deliveryGate"].get("passed") is True,
                "acousticPassed": row["deliveryGate"].get("passed") is True,
                "gateFlags": list(row["deliveryGate"].get("flags") or []),
                "generationFailure": None,
            }
        for failure in evidence.get("deliveryFailures") or []:
            key = (speaker, seed, failure["delivery"])
            if key in outcomes:
                raise MatrixError(f"duplicate comparison failure {key}")
            rejected = failure.get("rejectedAnalysis")
            gate = rejected.get("deliveryGate") if isinstance(rejected, dict) else None
            outcomes[key] = {
                "productPassed": False,
                "acousticPassed": isinstance(gate, dict) and gate.get("passed") is True,
                "gateFlags": (
                    list(gate.get("flags") or [])
                    if isinstance(gate, dict)
                    else [f"generation_failure:{failure['reasonCode']}"]
                ),
                "generationFailure": failure["reasonCode"],
            }
    expected = {
        (speaker["id"], seed, delivery["id"])
        for speaker in plan["speakers"]
        for seed in plan["seeds"]
        for delivery in plan["deliveries"]
    }
    if set(outcomes) != expected:
        raise MatrixError(
            f"comparison outcome coverage mismatch; missing={len(expected - set(outcomes))}, "
            f"extra={len(set(outcomes) - expected)}"
        )
    return plan, outcomes


def compare_arms(baseline_output: Path, candidate_output: Path) -> dict[str, Any]:
    baseline_plan, baseline = load_comparison_outcomes(baseline_output)
    candidate_plan, candidate = load_comparison_outcomes(candidate_output)
    for key in ("seeds", "speakers"):
        if baseline_plan.get(key) != candidate_plan.get(key):
            raise MatrixError(f"comparison plans differ at {key}")
    baseline_roster = [(row["id"], row["preset"]) for row in baseline_plan["deliveries"]]
    candidate_roster = [(row["id"], row["preset"]) for row in candidate_plan["deliveries"]]
    if baseline_roster != candidate_roster:
        raise MatrixError("comparison plans have different delivery cells")
    if set(baseline) != set(candidate):
        raise MatrixError("comparison arms have different outcome identities")

    baseline_report = json.loads(
        (baseline_output / "custom-delivery-matrix-report.json").read_text(encoding="utf-8")
    )
    candidate_report = json.loads(
        (candidate_output / "custom-delivery-matrix-report.json").read_text(encoding="utf-8")
    )

    def summarize(keys: list[tuple[str, int, str]]) -> dict[str, Any]:
        both_pass = candidate_only = baseline_only = both_fail = 0
        baseline_product = candidate_product = 0
        baseline_failures = candidate_failures = 0
        for key in keys:
            first, second = baseline[key], candidate[key]
            baseline_product += first["productPassed"]
            candidate_product += second["productPassed"]
            baseline_failures += first["generationFailure"] is not None
            candidate_failures += second["generationFailure"] is not None
            pair = (first["acousticPassed"], second["acousticPassed"])
            if pair == (True, True):
                both_pass += 1
            elif pair == (False, True):
                candidate_only += 1
            elif pair == (True, False):
                baseline_only += 1
            else:
                both_fail += 1
        baseline_acoustic = both_pass + baseline_only
        candidate_acoustic = both_pass + candidate_only
        return {
            "total": len(keys),
            "baselineProductPassed": baseline_product,
            "candidateProductPassed": candidate_product,
            "productPassDelta": candidate_product - baseline_product,
            "baselineAcousticPassed": baseline_acoustic,
            "candidateAcousticPassed": candidate_acoustic,
            "acousticPassDelta": candidate_acoustic - baseline_acoustic,
            "bothPassed": both_pass,
            "candidateOnlyPassed": candidate_only,
            "baselineOnlyPassed": baseline_only,
            "bothFailed": both_fail,
            "pairedExactP": exact_paired_binary_p(candidate_only, baseline_only),
            "baselineGenerationFailures": baseline_failures,
            "candidateGenerationFailures": candidate_failures,
        }

    all_keys = sorted(baseline)
    by_delivery: dict[str, Any] = {}
    baseline_cells = baseline_report["acousticAnalysis"]["separabilityHeldOutSpeaker"]["cells"]
    candidate_cells = candidate_report["acousticAnalysis"]["separabilityHeldOutSpeaker"]["cells"]
    for delivery_id, preset in baseline_roster:
        row = summarize([key for key in all_keys if key[2] == delivery_id])
        row["baselineHeldSpeakerRecall"] = baseline_cells[preset]["recall"]
        row["candidateHeldSpeakerRecall"] = candidate_cells[preset]["recall"]
        row["heldSpeakerRecallDelta"] = round(
            candidate_cells[preset]["recall"] - baseline_cells[preset]["recall"], 3
        )
        row["decision"] = (
            "fresh-holdout-required"
            if row["acousticPassDelta"] > 0 and row["heldSpeakerRecallDelta"] > 0
            else "candidate-rejected"
        )
        by_delivery[delivery_id] = row

    baseline_held = baseline_report["acousticAnalysis"]["separabilityHeldOutSpeaker"]["metrics"]
    candidate_held = candidate_report["acousticAnalysis"]["separabilityHeldOutSpeaker"]["metrics"]
    overall = summarize(all_keys)
    overall.update({
        "baselineHeldSpeakerUAR": baseline_held["uar"],
        "candidateHeldSpeakerUAR": candidate_held["uar"],
        "heldSpeakerUARDelta": round(candidate_held["uar"] - baseline_held["uar"], 3),
    })
    return {
        "schemaVersion": 1,
        "designation": "exploratory",
        "generatedAt": utc_now(),
        "baselineInstructionSet": baseline_plan.get("instructionSet", "shipped"),
        "candidateInstructionSet": candidate_plan.get("instructionSet", "shipped"),
        "pairedIdentity": {
            "speakerCount": len(baseline_plan["speakers"]),
            "deliveryCount": len(baseline_plan["deliveries"]),
            "seeds": baseline_plan["seeds"],
            "outcomeCount": len(all_keys),
        },
        "overall": overall,
        "byDelivery": by_delivery,
        "decision": {
            "promoteCandidateGlobally": False,
            "reason": (
                "candidate did not improve overall acoustic adherence and reduced "
                "held-speaker separability"
            ),
            "eligibleForFreshHoldout": sorted(
                delivery for delivery, row in by_delivery.items()
                if row["decision"] == "fresh-holdout-required"
            ),
        },
    }


def write_comparison_markdown(path: Path, comparison: dict[str, Any]) -> None:
    overall = comparison["overall"]
    lines = [
        "# Custom Voice Delivery Arm Comparison",
        "",
        f"Generated: {comparison['generatedAt']}",
        "",
        f"Designation: **{comparison['designation']}**.",
        "",
        "| Preset | Acoustic baseline | Acoustic candidate | Delta | Held-speaker recall delta | Decision |",
        "| --- | ---: | ---: | ---: | ---: | --- |",
    ]
    for delivery, row in comparison["byDelivery"].items():
        lines.append(
            f"| {delivery} | {row['baselineAcousticPassed']}/{row['total']} | "
            f"{row['candidateAcousticPassed']}/{row['total']} | "
            f"{row['acousticPassDelta']:+d} | {row['heldSpeakerRecallDelta']:+.3f} | "
            f"{row['decision']} |"
        )
    lines += [
        "",
        (
            f"Overall acoustic adherence: {overall['baselineAcousticPassed']}/"
            f"{overall['total']} → {overall['candidateAcousticPassed']}/{overall['total']} "
            f"({overall['acousticPassDelta']:+d})."
        ),
        (
            f"Held-speaker UAR: {overall['baselineHeldSpeakerUAR']:.3f} → "
            f"{overall['candidateHeldSpeakerUAR']:.3f} "
            f"({overall['heldSpeakerUARDelta']:+.3f})."
        ),
        "",
        f"Decision: {comparison['decision']['reason']}. No prompt is promoted from this exploratory arm.",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def build_aggregate(output: Path, plan: dict[str, Any]) -> dict[str, Any]:
    evidence_paths = sorted((output / "units").glob("*/evidence.json"))
    rows, generation_failures, reference_failures, units, sidecars = validate_complete_matrix(
        evidence_paths, plan["speakers"], plan["deliveries"], plan["seeds"]
    )
    outcome_rows = adherence_outcomes(
        rows, generation_failures, include_rejected_audio=False
    )
    acoustic_outcome_rows = adherence_outcomes(
        rows, generation_failures, include_rejected_audio=True
    )
    records = load_matrix([str(path) for path in sidecars])
    rejected_rows = []
    for failure in generation_failures:
        rejected = failure.get("rejectedAnalysis")
        if not isinstance(rejected, dict):
            continue
        rejected_rows.append({
            "speakerID": failure["speakerID"],
            "seed": failure["seed"],
            "generationID": failure["generationID"],
            "delivery": failure["delivery"],
            "deliveryGate": rejected["deliveryGate"],
        })
    # A valid but product-rejected WAV is still acoustic evidence. Excluding it
    # would make weak/halting deliveries disappear from separability and feature
    # statistics (survivorship bias). Product adherence above continues to count
    # the cell as failed; only the descriptive acoustic cohort includes it.
    records.extend(records_from_sidecar(rejected_rows))
    if not records:
        raise MatrixError("matrix produced no analyzable delivery audio")
    report = build_report(records)
    profile_digests = {row["profileDigest"] for row in rows}
    analyzer_versions = {
        row["deliveryMetrics"]["analyzerAlgorithmVersion"] for row in rows
    }
    rejected_identity_complete = True
    for failure in generation_failures:
        rejected = failure.get("rejectedAnalysis")
        if not isinstance(rejected, dict):
            continue
        rejected_digest = rejected.get("profileDigest")
        if isinstance(rejected_digest, str):
            profile_digests.add(rejected_digest)
        else:
            rejected_identity_complete = False
        metrics = rejected.get("deliveryMetrics")
        if isinstance(metrics, dict) and isinstance(metrics.get("analyzerAlgorithmVersion"), int):
            analyzer_versions.add(metrics["analyzerAlgorithmVersion"])
    profile_digests = sorted(profile_digests)
    analyzer_versions = sorted(analyzer_versions)
    if len(profile_digests) != 1 or len(analyzer_versions) != 1:
        raise MatrixError(
            f"matrix mixed analyzer identity: profiles={profile_digests}, versions={analyzer_versions}"
        )
    seeds = list(plan["seeds"])
    result = {
        "schemaVersion": SCHEMA_VERSION,
        "designation": "exploratory",
        "reason": (
            "Full production speaker/preset screen with fixed English medium text; "
            "not the independent multi-script/language labelled holdout required for promotion."
        ),
        "generatedAt": utc_now(),
        "instructionSet": plan.get("instructionSet", "shipped"),
        "sourceIdentity": plan["sourceIdentity"],
        "coverage": {
            "speakerCount": len(plan["speakers"]),
            "deliveryCount": len(plan["deliveries"]),
            "seedsPerSpeaker": len(seeds),
            "distinctSeedCount": len(set(seeds)),
            "unitCount": len(units),
            "plannedAttemptCount": len(outcome_rows),
            "analyzedTakeCount": len(rows),
            "generationFailureCount": len(generation_failures),
            "referenceFailureCount": len(reference_failures),
            "rejectedNeutralPairCount": sum(
                row.get("neutralReferenceAccepted") is False for row in rows
            ),
            "rejectedAudioAnalysisCount": sum(
                isinstance(failure.get("rejectedAnalysis"), dict)
                for failure in generation_failures
            ),
            "acousticallyAnalyzedAttemptCount": len(records),
            "seeds": seeds,
            "complete": True,
        },
        "methodology": {
            "modelVariant": "speed",
            "mode": "custom",
            "scriptCount": 1,
            "scriptLength": "medium",
            "language": "English",
            "referenceDesign": "same-speaker same-seed uninstructed warm take",
            "productAcceptanceMeaning": "Fast-QC acceptance and delivery adherence",
            "acousticAdherenceMeaning": "delivery gate over every analyzable WAV, including product-rejected WAVs",
            "separabilityMeaning": "request-label acoustic discrimination, not perceived-emotion recognition",
            "thresholdValidation": "profile thresholds are calibrated on prior data, not an independent labelled holdout",
            "promotionEligible": False,
        },
        "analysisIdentity": {
            "profileDigest": profile_digests[0],
            "analyzerAlgorithmVersion": analyzer_versions[0],
            "rejectedAnalysisIdentityComplete": rejected_identity_complete,
        },
        "generationFailures": generation_failures,
        "generationFailureSummary": generation_failure_summary(generation_failures),
        "referenceFailures": reference_failures,
        "referenceFailureSummary": reference_failure_summary(reference_failures),
        "adherence": adherence_summary(outcome_rows, plan["speakers"], plan["deliveries"]),
        "acousticAdherence": adherence_summary(
            acoustic_outcome_rows, plan["speakers"], plan["deliveries"]
        ),
        "qcRejectedButAcousticallyPassingCount": sum(
            isinstance(failure.get("rejectedAnalysis"), dict)
            and failure["rejectedAnalysis"]["deliveryGate"].get("passed") is True
            for failure in generation_failures
        ),
        "acousticAnalysis": report,
    }
    atomic_json(output / "custom-delivery-matrix-report.json", result)
    write_markdown(output / "custom-delivery-matrix-report.md", result)
    return result


def write_markdown(path: Path, report: dict[str, Any]) -> None:
    overall = report["adherence"]["overall"]
    acoustic = report["acousticAdherence"]["overall"]
    held = report["acousticAnalysis"].get("separabilityHeldOutSpeaker") or {}
    lines = [
        "# Custom Voice Delivery Matrix",
        "",
        f"Generated: {report['generatedAt']}",
        "",
        f"Designation: **{report['designation']}** — {report['reason']}",
        "",
        "## Coverage",
        "",
        (
            f"{report['coverage']['speakerCount']} speakers × "
            f"{report['coverage']['deliveryCount']} shipped presets × "
            f"{report['coverage']['seedsPerSpeaker']} fixed seeds per speaker = "
            f"{report['coverage']['plannedAttemptCount']} attempted instructed takes."
        ),
        (
            f"Product-accepted WAVs: {report['coverage']['analyzedTakeCount']}; typed Fast-QC or "
            f"generation failures: {report['coverage']['generationFailureCount']}; "
            f"acoustically analyzed attempts (including preserved rejects): "
            f"{report['coverage']['acousticallyAnalyzedAttemptCount']}."
        ),
        "",
        "## Product acceptance",
        "",
        (
            f"Fast-QC plus delivery adherence: {overall['passed']}/{overall['total']} "
            f"({overall['passRate']:.1%}; 95% Wilson "
            f"{overall['passRateLower95']:.1%}–{overall['passRateUpper95']:.1%})."
        ),
        (
            f"Acoustic adherence over preserved audio: {acoustic['passed']}/{acoustic['total']} "
            f"({acoustic['passRate']:.1%}; 95% Wilson "
            f"{acoustic['passRateLower95']:.1%}–{acoustic['passRateUpper95']:.1%}). "
            f"Fast QC rejected {report['qcRejectedButAcousticallyPassingCount']} clips that "
            "otherwise passed the delivery gate."
        ),
        "",
        "| Speaker | Passed | Rate | 95% interval |",
        "| --- | ---: | ---: | ---: |",
    ]
    for speaker, row in report["adherence"]["bySpeaker"].items():
        lines.append(
            f"| {speaker} | {row['passed']}/{row['total']} | {row['passRate']:.1%} | "
            f"{row['passRateLower95']:.1%}–{row['passRateUpper95']:.1%} |"
        )
    lines += [
        "",
        "## Speaker generalization",
        "",
        (
            f"Held-one-speaker-out preset UAR: {held.get('metrics', {}).get('uar', 'unavailable')}. "
            f"Verdict flags: {', '.join(held.get('flags') or []) or 'none'}."
        ),
        "",
        "The JSON report contains per-preset, per-speaker, per-cell, confidence-interval, "
        "confusion, feature-statistics, and source-identity detail.",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def run_unit(
    *,
    binary: Path,
    data_dir: Path,
    output: Path,
    speaker: str,
    seed: int,
    deliveries: list[dict],
    env: dict[str, str],
) -> Path:
    key = unit_key(speaker, seed)
    unit_dir = output / "units" / key
    sidecar_path = unit_dir / "bench-prosody.json"
    evidence_path = unit_dir / "evidence.json"
    status_path = unit_dir / "status.json"
    if sidecar_path.is_file() and evidence_path.is_file():
        rows = json.loads(sidecar_path.read_text(encoding="utf-8"))
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
        validate_unit_evidence(
            rows,
            evidence.get("deliveryFailures"),
            reference_failures=evidence.get("referenceFailures"),
            speaker_id=speaker,
            seed=seed,
            deliveries=deliveries,
        )
        return sidecar_path
    if status_path.is_file():
        retained = json.loads(status_path.read_text(encoding="utf-8"))
        if str(retained.get("state", "")).startswith("failed"):
            raise MatrixError(
                f"{key}: retained {retained.get('state')} attempt; see {status_path.parent / 'bench.log'}"
            )

    run_id = f"custom-delivery-{speaker}-{seed}"
    command = [
        str(binary), "bench",
        "--modes", "custom",
        "--variants", "speed",
        "--lengths", "medium",
        "--warm", "2",
        "--delivery", ",".join(row["id"] for row in deliveries),
        "--speaker", speaker,
        "--seed", str(seed),
        "--label", run_id,
        "--run-id", run_id,
        "--data-dir", str(data_dir),
        "--telemetry", "lightweight",
        "--no-summary",
        "--continue-delivery-failures",
        "--quiet",
    ]
    atomic_json(status_path, {"state": "running", "startedAt": utc_now(), "command": command[1:]})
    log_path = status_path.parent / "bench.log"
    try:
        result = subprocess.run(
            command,
            cwd=REPO,
            env=env,
            check=False,
            capture_output=True,
            text=True,
            timeout=UNIT_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as error:
        log_path.write_text((error.stdout or "") + (error.stderr or ""), encoding="utf-8")
        atomic_json(status_path, {
            "state": "failed-timeout", "finishedAt": utc_now(),
            "timeoutSeconds": UNIT_TIMEOUT_SECONDS, "log": "bench.log",
        })
        raise MatrixError(f"{key}: bench exceeded {UNIT_TIMEOUT_SECONDS}s; see {log_path}") from error
    log_path.write_text(result.stdout + result.stderr, encoding="utf-8")
    if result.returncode != 0:
        atomic_json(status_path, {
            "state": "failed", "finishedAt": utc_now(), "returnCode": result.returncode,
            "log": "bench.log",
        })
        raise MatrixError(f"{key}: bench failed ({result.returncode}); see {log_path}")

    current_manifest = data_dir / "diagnostics" / "bench-results.json"
    manifest = json.loads(current_manifest.read_text(encoding="utf-8"))
    failures, reference_failures = validate_unit_manifest(
        manifest, speaker_id=speaker, seed=seed, deliveries=deliveries
    )
    unit_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(current_manifest, unit_dir / "bench-results.json")
    successful_deliveries = [
        take for take in manifest["takes"] if take.get("delivery") is not None
    ]
    current_sidecar = data_dir / "diagnostics" / "bench-prosody.json"
    if successful_deliveries:
        analyzer = [
            sys.executable,
            str(REPO / "scripts/bench_delivery_prosody.py"),
            str(data_dir / "diagnostics"),
            "--results-manifest", str(current_manifest),
        ]
        analysis = subprocess.run(
            analyzer, cwd=REPO, env=env, check=False, capture_output=True, text=True
        )
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(analysis.stdout + analysis.stderr)
        if analysis.returncode != 0:
            atomic_json(status_path, {
                "state": "failed-analysis", "finishedAt": utc_now(),
                "returnCode": analysis.returncode, "log": "bench.log",
            })
            raise MatrixError(f"{key}: analyzer failed ({analysis.returncode}); see {log_path}")
        rows = json.loads(current_sidecar.read_text(encoding="utf-8"))
    else:
        rows = []
        atomic_json(current_sidecar, rows)
    archive = data_dir / "outputs" / "bench-archive" / run_id
    failures = analyze_rejected_failures(
        failures,
        manifest=manifest,
        diagnostics=data_dir / "diagnostics",
        archive=archive,
        deliveries=deliveries,
    )
    validate_unit_evidence(
        rows,
        failures,
        reference_failures=reference_failures,
        speaker_id=speaker,
        seed=seed,
        deliveries=deliveries,
    )
    shutil.copy2(current_sidecar, sidecar_path)
    atomic_json(evidence_path, {
        "schemaVersion": SCHEMA_VERSION,
        "unit": key,
        "speakerID": speaker,
        "seed": seed,
        "manifest": "bench-results.json",
        "sidecar": "bench-prosody.json",
        "analyzedDeliveries": sorted(row["delivery"] for row in rows),
        "referenceFailures": reference_failures,
        "deliveryFailures": failures,
    })
    if archive.is_dir():
        shutil.copy2(current_sidecar, archive / "bench-prosody.json")
    atomic_json(status_path, {
        "state": "complete", "finishedAt": utc_now(), "sidecar": "bench-prosody.json",
        "sidecarSHA256": file_sha256(sidecar_path),
        "failureCount": len(failures),
    })
    return sidecar_path


def default_data_dir() -> Path:
    override = os.environ.get("QWENVOICE_APP_SUPPORT_DIR")
    if override:
        return Path(override).expanduser()
    return Path.home() / "Library/Application Support/QwenVoice-Debug"


def parse_seeds(raw: str) -> list[int]:
    try:
        seeds = [int(item.strip()) for item in raw.split(",") if item.strip()]
    except ValueError as error:
        raise MatrixError("--seeds must be comma-separated unsigned integers") from error
    if not seeds or len(seeds) != len(set(seeds)) or any(seed < 0 for seed in seeds):
        raise MatrixError("--seeds must contain unique unsigned integers")
    return seeds


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="action", required=True)
    run_parser = subparsers.add_parser("run", help="generate missing units and report")
    run_parser.add_argument("--binary", type=Path, default=REPO / "build/vocello")
    run_parser.add_argument("--data-dir", type=Path, default=default_data_dir())
    run_parser.add_argument("--output", type=Path)
    run_parser.add_argument("--seeds", default=",".join(map(str, DEFAULT_SEEDS)))
    run_parser.add_argument(
        "--instruction-set",
        choices=("shipped", "short", "candidate-v2"),
        default="shipped",
        help="explicit production or registered debug instruction arm",
    )
    report_parser = subparsers.add_parser("report", help="validate existing sidecars and report")
    report_parser.add_argument("--output", type=Path, required=True)
    compare_parser = subparsers.add_parser(
        "compare", help="paired same-identity comparison of two complete arms"
    )
    compare_parser.add_argument("--baseline", type=Path, required=True)
    compare_parser.add_argument("--candidate", type=Path, required=True)
    compare_parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    try:
        if args.action == "compare":
            comparison = compare_arms(args.baseline.resolve(), args.candidate.resolve())
            destination = args.output.resolve()
            atomic_json(destination, comparison)
            write_comparison_markdown(destination.with_suffix(".md"), comparison)
            print(destination)
            return
        if args.action == "report":
            plan = json.loads((args.output / "matrix-plan.json").read_text(encoding="utf-8"))
            build_aggregate(args.output, plan)
            print(args.output / "custom-delivery-matrix-report.json")
            return

        binary = args.binary.resolve()
        data_dir = args.data_dir.expanduser().resolve()
        if not binary.is_file():
            raise MatrixError(f"CLI binary not found: {binary}; run ./scripts/build.sh cli")
        if not data_dir.is_dir():
            raise MatrixError(f"runtime data directory not found: {data_dir}")
        env = dict(os.environ)
        env["QWENVOICE_DEBUG"] = "1"
        if args.instruction_set == "shipped":
            env.pop("QWENVOICE_DELIVERY_INSTRUCTION_SET", None)
        else:
            env["QWENVOICE_DELIVERY_INSTRUCTION_SET"] = args.instruction_set
        speakers, deliveries = discover_rosters(binary, data_dir, env)
        seeds = parse_seeds(args.seeds)
        output = args.output
        if output is None:
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            output = REPO / "build/artifacts/macos/custom-delivery-matrix" / stamp
        output = output.resolve()
        identity = source_identity(binary, speakers, deliveries)
        plan_path = output / "matrix-plan.json"
        plan = {
            "schemaVersion": SCHEMA_VERSION,
            "createdAt": utc_now(),
            "designation": "exploratory",
            "instructionSet": args.instruction_set,
            "warmNeutralRepetitions": 2,
            "seeds": seeds,
            "speakers": speakers,
            "deliveries": deliveries,
            "sourceIdentity": identity,
        }
        if plan_path.is_file():
            existing = json.loads(plan_path.read_text(encoding="utf-8"))
            for key in (
                "instructionSet", "warmNeutralRepetitions", "seeds", "speakers",
                "deliveries", "sourceIdentity"
            ):
                if existing.get(key) != plan.get(key):
                    raise MatrixError(f"resume refused: matrix plan changed at {key}")
            plan = existing
        else:
            atomic_json(plan_path, plan)

        total = len(speakers) * len(seeds)
        completed = 0
        for speaker in speakers:
            for seed in seeds:
                completed += 1
                print(
                    f"[{completed}/{total}] {speaker['id']} seed {seed}",
                    flush=True,
                )
                run_unit(
                    binary=binary,
                    data_dir=data_dir,
                    output=output,
                    speaker=speaker["id"],
                    seed=seed,
                    deliveries=deliveries,
                    env=env,
                )
        build_aggregate(output, plan)
        print(output / "custom-delivery-matrix-report.json")
    except (OSError, subprocess.SubprocessError, MatrixError, ValueError) as error:
        raise SystemExit(f"custom delivery matrix failed: {error}") from error


if __name__ == "__main__":
    main()
