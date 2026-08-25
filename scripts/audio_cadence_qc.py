#!/usr/bin/env python3
"""Validate and audit human-calibrated Fast-QC cadence evidence.

The shipping amplitude-only gate remains source-owned. This tool never derives
or edits a production threshold. It verifies that an untracked, privacy-safe
calibration cohort is complete and independent, then reports whether a proposed
threshold review may begin without opening an untouched holdout selectively.

Usage:
    python3 scripts/audio_cadence_qc.py validate-contract
    python3 scripts/audio_cadence_qc.py evaluate --dataset /untracked/cohort.json
"""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import sys
from typing import Any


REPO_ROOT = Path(__file__).resolve().parent.parent
CONTRACT_PATH = Path("config/audio-cadence-qc-contract.json")
SPEAKER_CONTRACT_PATH = Path("Sources/Resources/qwenvoice_contract.json")
DELIVERY_CONTRACT_PATH = Path("config/delivery-experiment-contract.json")
SCHEMA_VERSION = 1
CLASSIFICATIONS = {"withinFastGate", "unusual", "severe"}
REASONS = {
    "excess_cadence_pauses",
    "single_suspicious_pause",
    "repeated_suspicious_pauses",
    "egregious_interior_silence",
}


class CadenceContractError(ValueError):
    """Cadence evidence is incomplete, unsafe, or internally inconsistent."""


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise CadenceContractError(f"cannot read valid JSON: {path.name}: {error}") from error


def _require_exact_keys(value: dict[str, Any], expected: set[str], context: str) -> None:
    extras = sorted(set(value) - expected)
    missing = sorted(expected - set(value))
    if missing or extras:
        details = []
        if missing:
            details.append(f"missing {missing}")
        if extras:
            details.append(f"unexpected {extras}")
        raise CadenceContractError(f"{context}: {'; '.join(details)}")


def _nonempty_string(value: Any, context: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CadenceContractError(f"{context} must be a non-empty string")
    return value


def _digest(value: Any, context: str) -> str:
    digest = _nonempty_string(value, context).lower()
    if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
        raise CadenceContractError(f"{context} must be a lowercase SHA-256 digest")
    return digest


def load_contract(root: Path = REPO_ROOT) -> dict[str, Any]:
    contract = _read_json(root / CONTRACT_PATH)
    if not isinstance(contract, dict) or contract.get("schemaVersion") != SCHEMA_VERSION:
        raise CadenceContractError(f"contract schemaVersion must be {SCHEMA_VERSION}")
    if contract.get("status") != "calibration-required":
        raise CadenceContractError("contract status must remain calibration-required")
    if contract.get("fastQCAlgorithmVersion") != 5:
        raise CadenceContractError("contract must bind Fast-QC algorithm version 5")

    policy = contract.get("policy")
    if not isinstance(policy, dict):
        raise CadenceContractError("policy must be an object")
    required_policy = {
        "withinFastGate": "publish",
        "unusual": "publish-with-visible-review-notice",
        "severe": "reject-before-publication",
        "retry": "explicit-user-controlled-visible-settings",
        "automaticRetry": False,
        "seedMutation": False,
        "bestOfN": False,
        "semanticDeliveryAuthority": False,
    }
    if policy != required_policy:
        raise CadenceContractError("policy weakens publication, retry, seed, or authority invariants")
    if contract.get("labels") != ["acceptable", "unusual", "severe"]:
        raise CadenceContractError("labels must preserve acceptable/unusual/severe ordering")
    if contract.get("splits") != ["calibration", "development", "confirmation"]:
        raise CadenceContractError("splits must preserve calibration/development/confirmation")
    if contract.get("scriptLengths") != ["short", "medium", "long"]:
        raise CadenceContractError("scriptLengths must preserve short/medium/long")

    minimum = contract.get("minimumCoverage")
    if not isinstance(minimum, dict):
        raise CadenceContractError("minimumCoverage must be an object")
    numeric_floors = {
        "speakerCount": 6,
        "distinctSeeds": 8,
        "distinctScriptGroups": 6,
        "listenersPerRow": 3,
    }
    for field, floor in numeric_floors.items():
        if not isinstance(minimum.get(field), int) or minimum[field] < floor:
            raise CadenceContractError(f"minimumCoverage.{field} must be at least {floor}")
    if minimum.get("allPresets") is not True:
        raise CadenceContractError("minimumCoverage must require all presets")
    if set(minimum.get("outputLanguages", [])) != {"en", "zh", "ja", "ko"}:
        raise CadenceContractError("minimumCoverage must require en/zh/ja/ko")
    if minimum.get("scriptLengths") != ["short", "medium", "long"]:
        raise CadenceContractError("minimumCoverage must require all script lengths")
    agreement = minimum.get("minimumLabelAgreement")
    if not isinstance(agreement, (int, float)) or not 0.5 < agreement <= 1.0:
        raise CadenceContractError("minimumLabelAgreement must be in (0.5, 1]")

    guardrails = contract.get("confirmationGuardrails")
    expected_guardrails = {
        "maximumAcceptableSevereFalseRejectRate": 0.0,
        "minimumSevereRecall": 0.9,
        "maximumAcceptableReviewNoticeRate": 0.25,
    }
    if guardrails != expected_guardrails:
        raise CadenceContractError("confirmation guardrails must remain fail closed")
    identity = contract.get("identity")
    if not isinstance(identity, dict):
        raise CadenceContractError("identity must be an object")
    if identity.get("requiredDigests") != ["audioDigest", "requestReceiptDigest"]:
        raise CadenceContractError("identity digests must bind audio and request receipt")
    if identity.get("blockedSplitKey") != [
        "speakerID", "scriptGroupID", "seed", "outputLanguage"
    ]:
        raise CadenceContractError("blockedSplitKey drifted")
    forbidden = set(identity.get("forbiddenFields", []))
    if not {"audioPath", "path", "scriptText", "prompt", "transcript", "rawError"} <= forbidden:
        raise CadenceContractError("identity must prohibit paths, text, prompts, and raw errors")
    authority = contract.get("thresholdChangeAuthority")
    if not isinstance(authority, dict) or not all(authority.values()):
        raise CadenceContractError("threshold-change authority must remain fully fail closed")
    return contract


def _known_identities(root: Path) -> tuple[set[str], set[str]]:
    speaker_contract = _read_json(root / SPEAKER_CONTRACT_PATH)
    delivery_contract = _read_json(root / DELIVERY_CONTRACT_PATH)
    try:
        speakers = set(speaker_contract["speakers"]["Built-in"])
        presets = set(delivery_contract["presets"])
    except (KeyError, TypeError) as error:
        raise CadenceContractError("authoritative speaker or preset contract is malformed") from error
    if not speakers or not presets:
        raise CadenceContractError("authoritative speaker and preset sets must be non-empty")
    return speakers, presets


def _validate_cadence(cadence: Any, context: str) -> dict[str, Any]:
    if not isinstance(cadence, dict):
        raise CadenceContractError(f"{context}.cadence must be an object")
    expected = {
        "classification", "reasons", "durationMS", "expectedPauseCount",
        "observedCadencePauseCount", "excessCadencePauseCount", "suspiciousPauseCount",
        "recordedInteriorPausesMS", "totalInteriorSilenceMS", "totalCadenceSilenceMS",
        "medianCadencePauseMS", "p90CadencePauseMS", "cadenceSilenceRatio",
    }
    _require_exact_keys(cadence, expected, f"{context}.cadence")
    if cadence["classification"] not in CLASSIFICATIONS:
        raise CadenceContractError(f"{context}: unknown cadence classification")
    reasons = cadence["reasons"]
    if not isinstance(reasons, list) or len(reasons) != len(set(reasons)) or not set(reasons) <= REASONS:
        raise CadenceContractError(f"{context}: invalid cadence reasons")
    integer_fields = (
        "durationMS", "expectedPauseCount", "observedCadencePauseCount",
        "excessCadencePauseCount", "suspiciousPauseCount", "totalInteriorSilenceMS",
        "totalCadenceSilenceMS",
    )
    for field in integer_fields:
        if not isinstance(cadence[field], int) or cadence[field] < 0:
            raise CadenceContractError(f"{context}.cadence.{field} must be a nonnegative integer")
    pauses = cadence["recordedInteriorPausesMS"]
    if not isinstance(pauses, list) or len(pauses) > 256 or any(
        not isinstance(value, int) or value < 0 for value in pauses
    ):
        raise CadenceContractError(f"{context}: recorded pause evidence is invalid or unbounded")
    if sum(pauses) != cadence["totalInteriorSilenceMS"]:
        raise CadenceContractError(f"{context}: totalInteriorSilenceMS disagrees with pauses")
    if cadence["totalCadenceSilenceMS"] > cadence["totalInteriorSilenceMS"]:
        raise CadenceContractError(f"{context}: cadence silence exceeds all interior silence")
    expected_excess = max(
        0, cadence["observedCadencePauseCount"] - cadence["expectedPauseCount"]
    )
    if cadence["excessCadencePauseCount"] != expected_excess:
        raise CadenceContractError(f"{context}: excess cadence pause count is inconsistent")
    ratio = cadence["cadenceSilenceRatio"]
    if not isinstance(ratio, (int, float)) or not math.isfinite(ratio) or not 0.0 <= ratio <= 1.0:
        raise CadenceContractError(f"{context}: cadenceSilenceRatio must be finite in [0, 1]")
    expected_ratio = (
        cadence["totalCadenceSilenceMS"] / cadence["durationMS"]
        if cadence["durationMS"] else 0.0
    )
    if abs(float(ratio) - expected_ratio) > 1e-6:
        raise CadenceContractError(f"{context}: cadenceSilenceRatio disagrees with durations")
    for field in ("medianCadencePauseMS", "p90CadencePauseMS"):
        value = cadence[field]
        if value is not None and (not isinstance(value, int) or value < 0):
            raise CadenceContractError(f"{context}.cadence.{field} must be null or nonnegative")
    return cadence


def evaluate(payload: dict[str, Any], root: Path = REPO_ROOT) -> dict[str, Any]:
    contract = load_contract(root)
    if not isinstance(payload, dict) or payload.get("schemaVersion") != SCHEMA_VERSION:
        raise CadenceContractError(f"dataset schemaVersion must be {SCHEMA_VERSION}")
    _require_exact_keys(payload, {"schemaVersion", "runID", "rows"}, "dataset")
    run_id = _nonempty_string(payload["runID"], "runID")
    rows = payload["rows"]
    if not isinstance(rows, list) or not rows:
        raise CadenceContractError("rows must be a non-empty array")
    speakers, presets = _known_identities(root)
    labels = set(contract["labels"])
    splits = set(contract["splits"])
    lengths = set(contract["scriptLengths"])
    forbidden = set(contract["identity"]["forbiddenFields"])
    allowed_row_keys = {
        "rowID", "runID", "generationID", "audioDigest", "requestReceiptDigest",
        "speakerID", "presetID", "outputLanguage", "scriptLength", "scriptGroupID",
        "seed", "split", "humanLabel", "listenerCount", "labelAgreement", "cadence",
    }
    seen_rows: set[str] = set()
    seen_generations: set[str] = set()
    seen_audio: set[str] = set()
    blocked_splits: dict[str, str] = {}
    validated: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        context = f"rows[{index}]"
        if not isinstance(row, dict):
            raise CadenceContractError(f"{context} must be an object")
        if forbidden & set(row):
            raise CadenceContractError(f"{context} contains privacy-forbidden fields")
        _require_exact_keys(row, allowed_row_keys, context)
        if row["runID"] != run_id:
            raise CadenceContractError(f"{context}: cross-run identity")
        row_id = _nonempty_string(row["rowID"], f"{context}.rowID")
        generation_id = _nonempty_string(row["generationID"], f"{context}.generationID")
        audio_digest = _digest(row["audioDigest"], f"{context}.audioDigest")
        _digest(row["requestReceiptDigest"], f"{context}.requestReceiptDigest")
        if row_id in seen_rows or generation_id in seen_generations or audio_digest in seen_audio:
            raise CadenceContractError(f"{context}: duplicate row, generation, or audio identity")
        seen_rows.add(row_id)
        seen_generations.add(generation_id)
        seen_audio.add(audio_digest)
        if row["speakerID"] not in speakers:
            raise CadenceContractError(f"{context}: unknown speakerID")
        if row["presetID"] not in presets:
            raise CadenceContractError(f"{context}: unknown presetID")
        if row["scriptLength"] not in lengths or row["split"] not in splits:
            raise CadenceContractError(f"{context}: unknown script length or split")
        _nonempty_string(row["outputLanguage"], f"{context}.outputLanguage")
        _nonempty_string(row["scriptGroupID"], f"{context}.scriptGroupID")
        if not isinstance(row["seed"], int) or row["seed"] < 0:
            raise CadenceContractError(f"{context}.seed must be a nonnegative integer")
        if row["humanLabel"] not in labels:
            raise CadenceContractError(f"{context}: unknown humanLabel")
        if not isinstance(row["listenerCount"], int) or row["listenerCount"] < contract["minimumCoverage"]["listenersPerRow"]:
            raise CadenceContractError(f"{context}: insufficient independent listeners")
        agreement = row["labelAgreement"]
        if not isinstance(agreement, (int, float)) or not math.isfinite(agreement):
            raise CadenceContractError(f"{context}: labelAgreement must be finite")
        if not contract["minimumCoverage"]["minimumLabelAgreement"] <= agreement <= 1.0:
            raise CadenceContractError(f"{context}: insufficient label agreement")
        cadence = _validate_cadence(row["cadence"], context)
        blocked = "|".join(str(row[field]) for field in contract["identity"]["blockedSplitKey"])
        prior_split = blocked_splits.setdefault(blocked, row["split"])
        if prior_split != row["split"]:
            raise CadenceContractError(f"{context}: blocked identity leaks across splits")
        validated.append({**row, "cadence": cadence})

    coverage: dict[str, Any] = {}
    minimum = contract["minimumCoverage"]
    for split in contract["splits"]:
        split_rows = [row for row in validated if row["split"] == split]
        coverage[split] = {
            "rowCount": len(split_rows),
            "presets": sorted({row["presetID"] for row in split_rows}),
            "speakers": sorted({row["speakerID"] for row in split_rows}),
            "outputLanguages": sorted({row["outputLanguage"] for row in split_rows}),
            "scriptLengths": sorted({row["scriptLength"] for row in split_rows}),
            "scriptGroupCount": len({row["scriptGroupID"] for row in split_rows}),
            "distinctSeedCount": len({row["seed"] for row in split_rows}),
            "humanLabels": sorted({row["humanLabel"] for row in split_rows}),
        }

    def coverage_failures(split: str) -> list[str]:
        value = coverage[split]
        failures: list[str] = []
        if set(value["presets"]) != presets:
            failures.append(f"{split}:missing-preset-coverage")
        if len(value["speakers"]) < minimum["speakerCount"]:
            failures.append(f"{split}:insufficient-speakers")
        if not set(minimum["outputLanguages"]) <= set(value["outputLanguages"]):
            failures.append(f"{split}:insufficient-languages")
        if set(value["scriptLengths"]) != set(minimum["scriptLengths"]):
            failures.append(f"{split}:insufficient-script-lengths")
        if value["scriptGroupCount"] < minimum["distinctScriptGroups"]:
            failures.append(f"{split}:insufficient-script-groups")
        if value["distinctSeedCount"] < minimum["distinctSeeds"]:
            failures.append(f"{split}:insufficient-seeds")
        if set(value["humanLabels"]) != labels:
            failures.append(f"{split}:missing-human-label-class")
        return failures

    failures = [failure for split in contract["splits"] for failure in coverage_failures(split)]
    confirmation = [row for row in validated if row["split"] == "confirmation"]
    confusion: Counter[str] = Counter(
        f"{row['humanLabel']}->{row['cadence']['classification']}" for row in confirmation
    )
    acceptable = [row for row in confirmation if row["humanLabel"] == "acceptable"]
    severe = [row for row in confirmation if row["humanLabel"] == "severe"]
    false_reject_rate = (
        sum(row["cadence"]["classification"] == "severe" for row in acceptable) / len(acceptable)
        if acceptable else 1.0
    )
    review_notice_rate = (
        sum(row["cadence"]["classification"] == "unusual" for row in acceptable) / len(acceptable)
        if acceptable else 1.0
    )
    severe_recall = (
        sum(row["cadence"]["classification"] == "severe" for row in severe) / len(severe)
        if severe else 0.0
    )
    guardrails = contract["confirmationGuardrails"]
    if false_reject_rate > guardrails["maximumAcceptableSevereFalseRejectRate"]:
        failures.append("confirmation:acceptable-severe-false-reject-rate")
    if review_notice_rate > guardrails["maximumAcceptableReviewNoticeRate"]:
        failures.append("confirmation:acceptable-review-notice-rate")
    if severe_recall < guardrails["minimumSevereRecall"]:
        failures.append("confirmation:severe-recall")

    dataset_digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return {
        "schemaVersion": SCHEMA_VERSION,
        "runID": run_id,
        "datasetDigest": dataset_digest,
        "rowCount": len(validated),
        "coverage": coverage,
        "confirmation": {
            "confusion": dict(sorted(confusion.items())),
            "acceptableSevereFalseRejectRate": false_reject_rate,
            "acceptableReviewNoticeRate": review_notice_rate,
            "severeRecall": severe_recall,
        },
        "failures": sorted(set(failures)),
        "readyForThresholdReview": not failures,
        "authority": "human-calibrated-cadence-screening-only",
        "semanticDeliveryAuthority": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=REPO_ROOT)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("validate-contract")
    evaluate_parser = subparsers.add_parser("evaluate")
    evaluate_parser.add_argument("--dataset", type=Path, required=True)
    evaluate_parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        load_contract(args.root)
        if args.command == "validate-contract":
            print("audio cadence QC contract: PASS")
            return 0
        payload = _read_json(args.dataset)
        report = evaluate(payload, args.root)
        rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            temporary = args.output.with_suffix(args.output.suffix + ".tmp")
            temporary.write_text(rendered, encoding="utf-8")
            temporary.replace(args.output)
        else:
            print(rendered, end="")
        return 0 if report["readyForThresholdReview"] else 2
    except CadenceContractError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
