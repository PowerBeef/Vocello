#!/usr/bin/env python3
"""Validate an untouched, independently grouped prosody-threshold holdout."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import prosody_calibration
from prosody_profile import load_profile


ROOT = Path(__file__).resolve().parent.parent
METADATA_FIELDS = (
    "speakerGroup", "scriptGroup", "translationGroup", "lengthClass", "language", "defectSeverity"
)


class HoldoutError(ValueError):
    pass


def _load_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise HoldoutError(f"cannot read {path.name}: {error}") from error
    if not isinstance(value, dict):
        raise HoldoutError(f"{path.name} must contain an object")
    return value


def validate_policy(root: Path = ROOT) -> dict[str, Any]:
    policy = _load_object(root / "config/prosody-holdout-policy.json")
    if policy.get("schemaVersion") != 1 or policy.get("confidenceLevel") != 0.95:
        raise HoldoutError("prosody holdout policy must be schema v1 at 95% confidence")
    for key in (
        "minimumCalibrationClips", "minimumHoldoutGoodClips", "minimumHoldoutBadClips",
        "minimumHoldoutSpeakerGroups", "minimumHoldoutScriptGroups", "minimumHoldoutLanguages",
    ):
        if not isinstance(policy.get(key), int) or policy[key] < 2:
            raise HoldoutError(f"{key} must be an integer of at least two")
    if not 0 < policy.get("maximumFalsePositiveRateUpperBound", 0) < 1:
        raise HoldoutError("maximum false-positive bound is invalid")
    if not 0 < policy.get("minimumTruePositiveRateLowerBound", 0) < 1:
        raise HoldoutError("minimum true-positive bound is invalid")
    for key in ("requiredLengthClasses", "requiredDefectSeverities", "groupIsolation"):
        value = policy.get(key)
        if not isinstance(value, list) or not value or any(not isinstance(item, str) for item in value):
            raise HoldoutError(f"{key} must be a non-empty string array")
    if set(policy["groupIsolation"]) != {"speakerGroup", "scriptGroup", "translationGroup"}:
        raise HoldoutError("holdout isolation must cover speaker, script, and translation groups")
    return policy


def _safe_token(value: Any, field: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", value):
        raise HoldoutError(f"{field} must be a privacy-safe stable token")
    return value


def _clip_digest(entry: dict[str, Any]) -> str:
    try:
        return hashlib.sha256(Path(entry["path"]).read_bytes()).hexdigest()
    except OSError as error:
        raise HoldoutError("a manifest clip cannot be read") from error


def validate_manifests(
    calibration: list[dict[str, Any]],
    holdout: list[dict[str, Any]],
    policy: dict[str, Any],
) -> dict[str, Any]:
    if len(calibration) < policy["minimumCalibrationClips"]:
        raise HoldoutError("calibration manifest is below the frozen minimum")
    good = sum(row.get("label") == "good" for row in holdout)
    bad = sum(row.get("label") == "bad" for row in holdout)
    if good < policy["minimumHoldoutGoodClips"] or bad < policy["minimumHoldoutBadClips"]:
        raise HoldoutError("holdout lacks the frozen good/bad sample floors")
    for split_name, entries in (("calibration", calibration), ("holdout", holdout)):
        for row in entries:
            for field in METADATA_FIELDS:
                _safe_token(row.get(field), f"{split_name}.{field}")
    calibration_audio = {_clip_digest(row) for row in calibration}
    holdout_audio = {_clip_digest(row) for row in holdout}
    if calibration_audio & holdout_audio:
        raise HoldoutError("calibration and holdout reuse audio bytes")
    for field in policy["groupIsolation"]:
        if {row[field] for row in calibration} & {row[field] for row in holdout}:
            raise HoldoutError(f"calibration and holdout leak {field}")
    speaker_count = len({row["speakerGroup"] for row in holdout})
    script_count = len({row["scriptGroup"] for row in holdout})
    languages = sorted({row["language"] for row in holdout})
    if speaker_count < policy["minimumHoldoutSpeakerGroups"]:
        raise HoldoutError("holdout speaker coverage is incomplete")
    if script_count < policy["minimumHoldoutScriptGroups"]:
        raise HoldoutError("holdout script coverage is incomplete")
    if len(languages) < policy["minimumHoldoutLanguages"]:
        raise HoldoutError("holdout language coverage is incomplete")
    if not set(policy["requiredLengthClasses"]) <= {row["lengthClass"] for row in holdout}:
        raise HoldoutError("holdout length coverage is incomplete")
    if not set(policy["requiredDefectSeverities"]) <= {row["defectSeverity"] for row in holdout}:
        raise HoldoutError("holdout defect-severity coverage is incomplete")
    return {
        "calibrationClipCount": len(calibration),
        "holdoutGoodClipCount": good,
        "holdoutBadClipCount": bad,
        "holdoutSpeakerGroupCount": speaker_count,
        "holdoutScriptGroupCount": script_count,
        "holdoutLanguages": languages,
    }


def _wilson(successes: int, total: int) -> dict[str, float]:
    if total <= 0:
        raise HoldoutError("confidence interval requires observations")
    z = 1.959963984540054
    proportion = successes / total
    denominator = 1 + z * z / total
    centre = (proportion + z * z / (2 * total)) / denominator
    radius = z * math.sqrt(proportion * (1 - proportion) / total + z * z / (4 * total * total)) / denominator
    return {"estimate": proportion, "lower": max(0.0, centre - radius), "upper": min(1.0, centre + radius)}


def _metrics(
    entries: list[dict[str, Any]],
    analyzer: Callable[[str], dict[str, Any]],
) -> tuple[list[dict[str, float]], list[dict[str, float]]]:
    good: list[dict[str, float]] = []
    bad: list[dict[str, float]] = []
    for row in entries:
        result = analyzer(row["path"])
        if "error" in result:
            raise HoldoutError("holdout analysis failed")
        record = {
            metric: float(result.get(metric, 0.0))
            for metric, _direction in prosody_calibration.THRESHOLD_MAP.values()
        }
        (good if row["label"] == "good" else bad).append(record)
    return good, bad


def validate_profile_binding(
    profile: dict[str, Any],
    calibration: list[dict[str, Any]],
) -> str:
    calibration_digest = prosody_calibration.corpus_digest(calibration)
    if profile.get("calibration_corpus_digest") != calibration_digest:
        raise HoldoutError("profile is not bound to the calibration manifest")
    if profile.get("analyzer_algorithm_version") != prosody_calibration.analyzer_algorithm_version():
        raise HoldoutError("profile analyzer version does not match the current analyzer")
    return calibration_digest


def evaluate(
    calibration_path: Path,
    holdout_path: Path,
    profile_path: Path,
    *,
    root: Path = ROOT,
    analyzer: Callable[[str], dict[str, Any]] = prosody_calibration.analyze,
) -> dict[str, Any]:
    policy = validate_policy(root)
    calibration = prosody_calibration.load_labels(calibration_path)
    holdout = prosody_calibration.load_labels(holdout_path)
    coverage = validate_manifests(calibration, holdout, policy)
    profile = load_profile(profile_path)
    calibration_digest = validate_profile_binding(profile, calibration)
    good, bad = _metrics(holdout, analyzer)
    rates = prosody_calibration.evaluate_profile(profile, good, bad)
    false_positive_count = round(rates["false_positive_rate"] * len(good))
    true_positive_count = round(rates["true_positive_rate"] * len(bad))
    fpr = _wilson(false_positive_count, len(good))
    tpr = _wilson(true_positive_count, len(bad))
    failures: list[str] = []
    if fpr["upper"] > policy["maximumFalsePositiveRateUpperBound"]:
        failures.append("false-positive-upper-bound")
    if tpr["lower"] < policy["minimumTruePositiveRateLowerBound"]:
        failures.append("true-positive-lower-bound")
    return {
        "schemaVersion": 1,
        "status": "PASS" if not failures else "FAIL",
        "checkedAtUTC": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "analyzerAlgorithmVersion": profile["analyzer_algorithm_version"],
        "calibrationCorpusDigest": calibration_digest,
        "holdoutCorpusDigest": prosody_calibration.corpus_digest(holdout),
        "profileDigest": hashlib.sha256(profile_path.read_bytes()).hexdigest(),
        "coverage": coverage,
        "falsePositiveRate95CI": fpr,
        "truePositiveRate95CI": tpr,
        "qualificationFailures": failures,
        "promotionAuthority": not failures,
    }


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(payload, indent=2, sort_keys=True).encode() + b"\n"
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=f".{path.name}.", delete=False) as handle:
        temporary = Path(handle.name)
        handle.write(encoded)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("validate-contract", "evaluate"))
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--calibration-labels", type=Path)
    parser.add_argument("--holdout-labels", type=Path)
    parser.add_argument("--profile", type=Path)
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()
    try:
        if arguments.command == "validate-contract":
            policy = validate_policy(arguments.root.resolve())
            print(f"Prosody holdout contract: PASS ({policy['minimumHoldoutGoodClips']} good + {policy['minimumHoldoutBadClips']} bad)")
            return 0
        if not all((arguments.calibration_labels, arguments.holdout_labels, arguments.profile, arguments.output)):
            raise HoldoutError("evaluate requires calibration, holdout, profile, and output paths")
        result = evaluate(
            arguments.calibration_labels.resolve(),
            arguments.holdout_labels.resolve(),
            arguments.profile.resolve(),
            root=arguments.root.resolve(),
        )
        _atomic_json(arguments.output.resolve(), result)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0 if result["status"] == "PASS" else 1
    except (OSError, ValueError) as error:
        print(f"Prosody holdout validation: FAIL\n{error}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
