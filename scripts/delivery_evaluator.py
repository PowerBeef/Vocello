#!/usr/bin/env python3
"""Layered, operator-local evaluator for Qwen3 delivery experiments.

The evaluator is intentionally a post-generation research tool.  It fits a
small regularized dimensional model over deterministic acoustic features,
validates it with speaker/script-grouped folds, emits uncertainty and
abstention, and joins the independent QC/ASR/identity/MOS/SER layers without
turning any advisory model into semantic authority.

Generated audio is never embedded in model or report JSON.  Heavy ML scorers
remain separate subprocesses and must run sequentially after the TTS engine
exits on the canonical 8 GB Mac.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import resource
import sys
import tempfile
from typing import Any

import numpy as np


SCHEMA_VERSION = 1
MODEL_VERSION = 1
DIMENSIONS = ("valence", "arousal", "dominance")
DEFAULT_RIDGE_GRID = (0.01, 0.1, 1.0, 10.0)
DEFAULT_ABSTAIN_RMSE = 0.45
DEFAULT_EXTRAPOLATION_Z = 3.0
REQUIRED_LAYERS = ("acoustic",)
OPTIONAL_LAYERS = ("asr", "identity", "mos", "ser")
CHALLENGER_LAYER = "challenger"


class EvaluatorError(ValueError):
    """The evaluator input or model violates its fail-closed contract."""


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, indent=2, sort_keys=True, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def _finite_number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise EvaluatorError(f"{label} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise EvaluatorError(f"{label} must be finite")
    return result


def validate_label_provenance(payload: dict[str, Any]) -> dict[str, Any]:
    provenance = payload.get("labelProvenance")
    if not isinstance(provenance, dict):
        raise EvaluatorError("labeled dataset requires blinded labelProvenance")
    if provenance.get("kind") != "blinded-independent-listener-median":
        raise EvaluatorError("labels must come from blinded independent listeners")
    if provenance.get("sourceSplit") != "calibration":
        raise EvaluatorError("dimensional training labels must use the calibration split")
    if provenance.get("calibrationQualified") is not True:
        raise EvaluatorError("label provenance is not calibration-qualified")
    if provenance.get("qualificationFailures") != []:
        raise EvaluatorError("qualified label provenance retains failures")
    listener_count = provenance.get("listenerCount")
    if isinstance(listener_count, bool) or not isinstance(listener_count, int) or listener_count < 3:
        raise EvaluatorError("calibration requires at least three independent listeners")
    response_digests = provenance.get("responseDigests")
    if (
        not isinstance(response_digests, list)
        or len(response_digests) < 3
        or len(response_digests) != listener_count
        or len(response_digests) != len(set(response_digests))
        or any(not isinstance(value, str) or len(value) != 64 for value in response_digests)
    ):
        raise EvaluatorError("label provenance has invalid response digests")
    coverage = provenance.get("fluentLanguageCoverage")
    if (
        not isinstance(coverage, dict) or not coverage
        or any(isinstance(value, bool) or not isinstance(value, int) or value < 1
               for value in coverage.values())
    ):
        raise EvaluatorError("label provenance lacks fluent-language coverage")
    agreement = provenance.get("agreement")
    if not isinstance(agreement, dict) or set(agreement) != set(DIMENSIONS):
        raise EvaluatorError("label provenance has incomplete agreement metrics")
    for dimension in DIMENSIONS:
        expected_pairs = listener_count * (listener_count - 1) // 2
        if agreement[dimension].get("pairCount") != expected_pairs:
            raise EvaluatorError("human agreement pair coverage is incomplete")
        value = _finite_number(
            agreement[dimension].get("meanPairwiseCCC"),
            f"labelProvenance.agreement.{dimension}.meanPairwiseCCC",
        )
        if value < 0.60:
            raise EvaluatorError("human agreement is below the calibration floor")
    return provenance


def load_dataset(payload: dict[str, Any], *, require_labels: bool) -> tuple[list[str], list[dict]]:
    if not isinstance(payload, dict) or payload.get("schemaVersion") != SCHEMA_VERSION:
        raise EvaluatorError(f"dataset schemaVersion must be {SCHEMA_VERSION}")
    manifest_digest = payload.get("manifestDigest")
    if not isinstance(manifest_digest, str) or len(manifest_digest) != 64:
        raise EvaluatorError("dataset requires a 64-character manifestDigest")
    feature_names = payload.get("featureNames")
    if (
        not isinstance(feature_names, list)
        or not feature_names
        or len(feature_names) != len(set(feature_names))
        or any(not isinstance(name, str) or not name for name in feature_names)
    ):
        raise EvaluatorError("featureNames must be a non-empty unique string list")
    rows = payload.get("rows")
    if not isinstance(rows, list) or not rows:
        raise EvaluatorError("dataset rows must be a non-empty array")
    if require_labels:
        validate_label_provenance(payload)
    identities: set[str] = set()
    normalized: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise EvaluatorError(f"row {index} must be an object")
        generation_id = row.get("generationID")
        if not isinstance(generation_id, str) or not generation_id:
            raise EvaluatorError(f"row {index} lacks generationID")
        if generation_id in identities:
            raise EvaluatorError(f"duplicate generationID {generation_id}")
        identities.add(generation_id)
        speaker = row.get("speakerID")
        script = row.get("scriptID")
        if not isinstance(speaker, str) or not speaker or not isinstance(script, str) or not script:
            raise EvaluatorError(f"{generation_id}: speakerID and scriptID are required")
        features = row.get("features")
        if not isinstance(features, dict) or set(features) != set(feature_names):
            raise EvaluatorError(f"{generation_id}: feature set does not match featureNames")
        values = {
            name: _finite_number(features[name], f"{generation_id}.features.{name}")
            for name in feature_names
        }
        labels = row.get("labels")
        if require_labels:
            if not isinstance(labels, dict) or set(labels) != set(DIMENSIONS):
                raise EvaluatorError(f"{generation_id}: labels require {DIMENSIONS}")
            labels = {
                name: _finite_number(labels[name], f"{generation_id}.labels.{name}")
                for name in DIMENSIONS
            }
            if any(not -1.0 <= value <= 1.0 for value in labels.values()):
                raise EvaluatorError(f"{generation_id}: dimensional labels must be in [-1, 1]")
        normalized.append({
            **row,
            "features": values,
            "labels": labels,
            "outerGroup": speaker,
            "innerGroup": script,
        })
    if require_labels:
        if len(normalized) < 20:
            raise EvaluatorError("calibration requires at least 20 labeled rows")
        if len({row["outerGroup"] for row in normalized}) < 3:
            raise EvaluatorError("calibration requires at least three speaker groups")
        if len({row["innerGroup"] for row in normalized}) < 3:
            raise EvaluatorError("calibration requires at least three script groups")
    return feature_names, normalized


def _matrix(rows: list[dict], feature_names: list[str]) -> np.ndarray:
    return np.asarray(
        [[row["features"][name] for name in feature_names] for row in rows],
        dtype=np.float64,
    )


def _fit_ridge(x: np.ndarray, y: np.ndarray, ridge: float) -> tuple[np.ndarray, float]:
    if x.ndim != 2 or y.ndim != 1 or x.shape[0] != y.shape[0]:
        raise EvaluatorError("ridge inputs have incompatible shapes")
    augmented = np.column_stack([np.ones(x.shape[0]), x])
    penalty = np.eye(augmented.shape[1], dtype=np.float64) * ridge
    penalty[0, 0] = 0.0
    coefficients = np.linalg.solve(
        augmented.T @ augmented + penalty, augmented.T @ y
    )
    return coefficients[1:], float(coefficients[0])


def _predict(x: np.ndarray, coefficients: np.ndarray, intercept: float) -> np.ndarray:
    return np.clip(x @ coefficients + intercept, -1.0, 1.0)


def _rmse(expected: np.ndarray, observed: np.ndarray) -> float:
    return float(np.sqrt(np.mean((expected - observed) ** 2)))


def _ccc(expected: np.ndarray, observed: np.ndarray) -> float | None:
    if expected.size < 2:
        return None
    expected_mean = float(expected.mean())
    observed_mean = float(observed.mean())
    covariance = float(np.mean((expected - expected_mean) * (observed - observed_mean)))
    denominator = (
        float(np.var(expected)) + float(np.var(observed))
        + (expected_mean - observed_mean) ** 2
    )
    return (2.0 * covariance / denominator) if denominator > 0 else None


def _standardizer(x: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    means = x.mean(axis=0)
    scales = x.std(axis=0)
    scales[scales < 1e-9] = 1.0
    return (x - means) / scales, means, scales


def choose_ridge(
    rows: list[dict], feature_names: list[str], dimension: str,
    grid: tuple[float, ...] = DEFAULT_RIDGE_GRID,
) -> tuple[float, dict[str, float]]:
    """Inner script-group validation, with deterministic smallest-ridge tie break."""
    groups = sorted({row["innerGroup"] for row in rows})
    if len(groups) < 2:
        return grid[0], {str(grid[0]): 0.0}
    scores: dict[str, float] = {}
    for ridge in grid:
        errors: list[float] = []
        for group in groups:
            train = [row for row in rows if row["innerGroup"] != group]
            test = [row for row in rows if row["innerGroup"] == group]
            if not train or not test:
                continue
            train_x, means, scales = _standardizer(_matrix(train, feature_names))
            test_x = (_matrix(test, feature_names) - means) / scales
            train_y = np.asarray([row["labels"][dimension] for row in train])
            test_y = np.asarray([row["labels"][dimension] for row in test])
            coefficients, intercept = _fit_ridge(train_x, train_y, ridge)
            errors.append(_rmse(test_y, _predict(test_x, coefficients, intercept)))
        scores[str(ridge)] = float(np.mean(errors)) if errors else float("inf")
    selected = min(grid, key=lambda value: (scores[str(value)], value))
    return selected, scores


def grouped_validation(
    rows: list[dict], feature_names: list[str], dimension: str,
) -> dict[str, Any]:
    speakers = sorted({row["outerGroup"] for row in rows})
    if len(speakers) < 2:
        raise EvaluatorError("calibration requires at least two speaker groups")
    expected: list[float] = []
    predicted: list[float] = []
    folds: list[dict[str, Any]] = []
    for speaker in speakers:
        train = [row for row in rows if row["outerGroup"] != speaker]
        test = [row for row in rows if row["outerGroup"] == speaker]
        if len({row["innerGroup"] for row in train}) < 2:
            raise EvaluatorError(
                f"outer fold {speaker} has fewer than two training script groups"
            )
        ridge, inner_scores = choose_ridge(train, feature_names, dimension)
        train_x, means, scales = _standardizer(_matrix(train, feature_names))
        test_x = (_matrix(test, feature_names) - means) / scales
        train_y = np.asarray([row["labels"][dimension] for row in train])
        test_y = np.asarray([row["labels"][dimension] for row in test])
        coefficients, intercept = _fit_ridge(train_x, train_y, ridge)
        fold_predictions = _predict(test_x, coefficients, intercept)
        expected.extend(float(value) for value in test_y)
        predicted.extend(float(value) for value in fold_predictions)
        folds.append({
            "heldOutSpeaker": speaker,
            "n": len(test),
            "ridge": ridge,
            "rmse": _rmse(test_y, fold_predictions),
            "innerScriptRMSE": inner_scores,
        })
    expected_array = np.asarray(expected)
    predicted_array = np.asarray(predicted)
    return {
        "grouping": "outer-speaker-inner-script",
        "n": len(expected),
        "rmse": _rmse(expected_array, predicted_array),
        "mae": float(np.mean(np.abs(expected_array - predicted_array))),
        "ccc": _ccc(expected_array, predicted_array),
        "folds": folds,
    }


def calibrate(payload: dict[str, Any]) -> dict[str, Any]:
    feature_names, rows = load_dataset(payload, require_labels=True)
    if len(rows) < 8:
        raise EvaluatorError("calibration requires at least eight labeled rows")
    x = _matrix(rows, feature_names)
    standardized, means, scales = _standardizer(x)
    dimensions: dict[str, Any] = {}
    for dimension in DIMENSIONS:
        validation = grouped_validation(rows, feature_names, dimension)
        ridge, grid_scores = choose_ridge(rows, feature_names, dimension)
        y = np.asarray([row["labels"][dimension] for row in rows])
        coefficients, intercept = _fit_ridge(standardized, y, ridge)
        dimensions[dimension] = {
            "ridge": ridge,
            "ridgeSelectionScriptRMSE": grid_scores,
            "intercept": intercept,
            "coefficients": {
                name: float(value) for name, value in zip(feature_names, coefficients)
            },
            "validation": validation,
            "maximumCalibratedRMSE": DEFAULT_ABSTAIN_RMSE,
        }
    model = {
        "schemaVersion": SCHEMA_VERSION,
        "modelVersion": MODEL_VERSION,
        "kind": "speaker-normalized-dimensional-delivery-ridge",
        "promotionAuthority": False,
        "featureNames": feature_names,
        "featureMeans": {name: float(value) for name, value in zip(feature_names, means)},
        "featureScales": {name: float(value) for name, value in zip(feature_names, scales)},
        "dimensions": dimensions,
        "trainingManifestDigest": payload["manifestDigest"],
        "labelProvenanceDigest": digest(payload["labelProvenance"]),
        "trainingRowsDigest": digest(rows),
        "trainingRowCount": len(rows),
        "outerGroups": sorted({row["outerGroup"] for row in rows}),
        "innerGroups": sorted({row["innerGroup"] for row in rows}),
        "extrapolationZ": DEFAULT_EXTRAPOLATION_Z,
    }
    model["modelDigest"] = digest(model)
    return model


def validate_model(model: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(model, dict) or model.get("schemaVersion") != SCHEMA_VERSION:
        raise EvaluatorError("invalid dimensional model schemaVersion")
    if model.get("modelVersion") != MODEL_VERSION or model.get("promotionAuthority") is not False:
        raise EvaluatorError("dimensional model identity or advisory boundary is invalid")
    stored_digest = model.get("modelDigest")
    if not isinstance(stored_digest, str):
        raise EvaluatorError("dimensional model has no digest")
    body = dict(model)
    body.pop("modelDigest", None)
    if digest(body) != stored_digest:
        raise EvaluatorError("dimensional model digest mismatch")
    features = model.get("featureNames")
    if not isinstance(features, list) or not features:
        raise EvaluatorError("dimensional model has no features")
    if set(model.get("dimensions", {})) != set(DIMENSIONS):
        raise EvaluatorError("dimensional model has incomplete outputs")
    return model


def evaluate(payload: dict[str, Any], model: dict[str, Any]) -> dict[str, Any]:
    model = validate_model(model)
    feature_names, rows = load_dataset(payload, require_labels=False)
    if feature_names != model["featureNames"]:
        raise EvaluatorError("evaluation feature order differs from calibrated model")
    means = np.asarray([model["featureMeans"][name] for name in feature_names])
    scales = np.asarray([model["featureScales"][name] for name in feature_names])
    standardized = (_matrix(rows, feature_names) - means) / scales
    reports: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        maximum_z = float(np.max(np.abs(standardized[index])))
        predictions: dict[str, Any] = {}
        for dimension in DIMENSIONS:
            entry = model["dimensions"][dimension]
            coefficients = np.asarray(
                [entry["coefficients"][name] for name in feature_names]
            )
            value = float(np.clip(
                standardized[index] @ coefficients + entry["intercept"], -1.0, 1.0
            ))
            uncertainty = float(entry["validation"]["rmse"])
            abstain_reasons: list[str] = []
            if uncertainty > entry["maximumCalibratedRMSE"]:
                abstain_reasons.append("calibration-error")
            if maximum_z > model["extrapolationZ"]:
                abstain_reasons.append("feature-extrapolation")
            predictions[dimension] = {
                "value": value,
                "uncertaintyRMSE": uncertainty,
                "abstained": bool(abstain_reasons),
                "abstainReasons": abstain_reasons,
            }
        reports.append({
            "generationID": row["generationID"],
            "speakerID": row["speakerID"],
            "scriptID": row["scriptID"],
            "maximumAbsoluteFeatureZ": maximum_z,
            "dimensions": predictions,
        })
    return {
        "schemaVersion": SCHEMA_VERSION,
        "kind": "dimensional-delivery-evaluation",
        "promotionAuthority": False,
        "modelDigest": model["modelDigest"],
        "inputManifestDigest": payload["manifestDigest"],
        "rows": reports,
    }


def _layer_rows(payload: dict[str, Any], name: str) -> dict[str, dict[str, Any]]:
    if not isinstance(payload, dict) or payload.get("schemaVersion") != SCHEMA_VERSION:
        raise EvaluatorError(f"{name} layer has invalid schemaVersion")
    rows = payload.get("rows")
    if not isinstance(rows, list):
        raise EvaluatorError(f"{name} layer rows must be an array")
    indexed: dict[str, dict[str, Any]] = {}
    for row in rows:
        generation_id = row.get("generationID") if isinstance(row, dict) else None
        if not isinstance(generation_id, str) or not generation_id:
            raise EvaluatorError(f"{name} layer row lacks generationID")
        if generation_id in indexed:
            raise EvaluatorError(f"{name} layer duplicates {generation_id}")
        indexed[generation_id] = row
    return indexed


def validate_challenger_layer(payload: dict[str, Any]) -> dict[str, Any]:
    """Validate an optional external scorer before its rows enter composition."""
    if not isinstance(payload, dict) or payload.get("schemaVersion") != SCHEMA_VERSION:
        raise EvaluatorError("challenger layer has invalid schemaVersion")
    provenance = payload.get("modelProvenance")
    if not isinstance(provenance, dict):
        raise EvaluatorError("challenger layer requires modelProvenance")
    required_strings = (
        "modelID", "sourceRevision", "weightsSHA256", "license",
        "trainingDataDeclaration", "labelMapDigest",
    )
    for field in required_strings:
        value = provenance.get(field)
        if not isinstance(value, str) or not value.strip():
            raise EvaluatorError(f"challenger provenance requires {field}")
    if len(provenance["weightsSHA256"]) != 64 or len(provenance["labelMapDigest"]) != 64:
        raise EvaluatorError("challenger weight and label-map digests must be SHA-256")
    if provenance.get("commercialUseCompatible") is not True:
        raise EvaluatorError("challenger license is not commercially compatible")
    baseline_error = _finite_number(
        provenance.get("baselineHoldoutCalibrationError"),
        "challenger baselineHoldoutCalibrationError",
    )
    challenger_error = _finite_number(
        provenance.get("challengerHoldoutCalibrationError"),
        "challenger challengerHoldoutCalibrationError",
    )
    if challenger_error >= baseline_error:
        raise EvaluatorError("challenger does not improve untouched-holdout calibration")
    peak_rss = provenance.get("peakRSSBytes")
    if isinstance(peak_rss, bool) or not isinstance(peak_rss, int) or peak_rss <= 0:
        raise EvaluatorError("challenger peakRSSBytes must be a positive integer")
    for field in ("eightGigabyteHostCompatible", "offlineAfterAcquisition", "sequentialMemoryReleased"):
        if provenance.get(field) is not True:
            raise EvaluatorError(f"challenger provenance requires {field}=true")
    _layer_rows(payload, CHALLENGER_LAYER)
    return payload


def compose_layers(layers: dict[str, dict[str, Any]], dimensional: dict[str, Any] | None) -> dict:
    missing_required = [name for name in REQUIRED_LAYERS if name not in layers]
    if missing_required:
        raise EvaluatorError(f"missing required evaluator layer(s): {missing_required}")
    if CHALLENGER_LAYER in layers:
        validate_challenger_layer(layers[CHALLENGER_LAYER])
    indexed = {name: _layer_rows(payload, name) for name, payload in layers.items()}
    acoustic_ids = set(indexed["acoustic"])
    for name, rows in indexed.items():
        unknown = set(rows) - acoustic_ids
        if unknown:
            raise EvaluatorError(f"{name} layer contains cross-run identities: {sorted(unknown)[:3]}")
    dimension_rows = _layer_rows(dimensional, "dimensional") if dimensional else {}
    if set(dimension_rows) - acoustic_ids:
        raise EvaluatorError("dimensional layer contains cross-run identities")

    rows = []
    disagreement_count = 0
    for generation_id in sorted(acoustic_ids):
        entry = {
            "generationID": generation_id,
            "layers": {
                name: values.get(generation_id)
                for name, values in indexed.items()
                if generation_id in values
            },
        }
        if generation_id in dimension_rows:
            entry["layers"]["dimensional"] = dimension_rows[generation_id]
        disagreements: list[str] = []
        ser = entry["layers"].get("ser")
        vad = entry["layers"].get("dimensional")
        if ser and vad and not ser.get("abstained"):
            top = ser.get("topEmotion")
            valence = vad.get("dimensions", {}).get("valence", {})
            if not valence.get("abstained"):
                value = valence.get("value")
                if top in {"happy"} and isinstance(value, (int, float)) and value < 0:
                    disagreements.append("ser-happy-vs-negative-valence")
                if top in {"angry", "sad", "fearful", "disgust"} and isinstance(
                    value, (int, float)
                ) and value > 0:
                    disagreements.append("ser-negative-vs-positive-valence")
        entry["disagreements"] = disagreements
        disagreement_count += bool(disagreements)
        rows.append(entry)
    present = sorted(indexed)
    if dimensional:
        present.append("dimensional")
    return {
        "schemaVersion": SCHEMA_VERSION,
        "kind": "layered-delivery-evaluation",
        "promotionAuthority": False,
        "completeLayers": sorted(set(present)),
        "missingAdvisoryLayers": sorted(
            set(OPTIONAL_LAYERS + (CHALLENGER_LAYER,)) - set(indexed)
        ),
        "challengerProvenance": (
            {
                field: layers[CHALLENGER_LAYER]["modelProvenance"][field]
                for field in (
                    "modelID", "sourceRevision", "weightsSHA256", "license",
                    "trainingDataDeclaration", "labelMapDigest", "peakRSSBytes",
                )
            }
            if CHALLENGER_LAYER in layers else None
        ),
        "rowCount": len(rows),
        "disagreementCount": disagreement_count,
        "peakRSSBytes": (
            resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            if sys.platform == "darwin"
            else resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024
        ),
        "rows": rows,
    }


def _read(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise EvaluatorError(f"cannot load {path}: {error}") from error
    if not isinstance(value, dict):
        raise EvaluatorError(f"{path} must contain a JSON object")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    calibrate_command = commands.add_parser("calibrate")
    calibrate_command.add_argument("--input", required=True, type=Path)
    calibrate_command.add_argument("--out", required=True, type=Path)
    evaluate_command = commands.add_parser("evaluate")
    evaluate_command.add_argument("--input", required=True, type=Path)
    evaluate_command.add_argument("--model", required=True, type=Path)
    evaluate_command.add_argument("--out", required=True, type=Path)
    validate_command = commands.add_parser("validate-model")
    validate_command.add_argument("--model", required=True, type=Path)
    calibrate_v2_command = commands.add_parser("calibrate-v2")
    calibrate_v2_command.add_argument("--input", required=True, type=Path)
    calibrate_v2_command.add_argument("--out", required=True, type=Path)
    evaluate_v2_command = commands.add_parser("evaluate-v2")
    evaluate_v2_command.add_argument("--input", required=True, type=Path)
    evaluate_v2_command.add_argument("--model", required=True, type=Path)
    evaluate_v2_command.add_argument("--out", required=True, type=Path)
    compare_v2_command = commands.add_parser("compare-v2-holdout")
    compare_v2_command.add_argument("--input", required=True, type=Path)
    compare_v2_command.add_argument("--out", required=True, type=Path)
    validate_v2_contract_command = commands.add_parser("validate-v2-contract")
    validate_v2_contract_command.add_argument("--contract", required=True, type=Path)
    compose = commands.add_parser("compose")
    compose.add_argument("--acoustic", required=True, type=Path)
    compose.add_argument("--asr", type=Path)
    compose.add_argument("--identity", type=Path)
    compose.add_argument("--mos", type=Path)
    compose.add_argument("--ser", type=Path)
    compose.add_argument("--challenger", type=Path)
    compose.add_argument("--dimensional", type=Path)
    compose.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    try:
        if args.command in {
            "calibrate-v2", "evaluate-v2", "compare-v2-holdout", "validate-v2-contract"
        }:
            from delivery_evaluator_v2 import (
                calibrate_v2, compare_untouched_holdout, evaluate_v2, validate_v2_contract,
            )
            if args.command == "calibrate-v2":
                result = calibrate_v2(_read(args.input))
            elif args.command == "evaluate-v2":
                result = evaluate_v2(_read(args.input), _read(args.model))
            elif args.command == "validate-v2-contract":
                validate_v2_contract(_read(args.contract))
                print(json.dumps({"status": "PASS", "contract": str(args.contract)}))
                return 0
            else:
                result = compare_untouched_holdout(_read(args.input))
            atomic_json(args.out, result)
        elif args.command == "calibrate":
            result = calibrate(_read(args.input))
            atomic_json(args.out, result)
        elif args.command == "evaluate":
            result = evaluate(_read(args.input), _read(args.model))
            atomic_json(args.out, result)
        elif args.command == "validate-model":
            model = validate_model(_read(args.model))
            print(json.dumps({"status": "PASS", "modelDigest": model["modelDigest"]}))
            return 0
        else:
            layers = {"acoustic": _read(args.acoustic)}
            for name in OPTIONAL_LAYERS + (CHALLENGER_LAYER,):
                path = getattr(args, name)
                if path:
                    layers[name] = _read(path)
            result = compose_layers(
                layers, _read(args.dimensional) if args.dimensional else None
            )
            atomic_json(args.out, result)
        print(json.dumps({"status": "PASS", "output": str(args.out)}, indent=2))
        return 0
    except EvaluatorError as error:
        print(f"Delivery evaluator: FAIL\n{error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
