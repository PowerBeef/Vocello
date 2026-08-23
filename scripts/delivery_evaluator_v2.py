#!/usr/bin/env python3
"""Compact perceptual evaluator v2 for the existing delivery harness.

Ridge-v1 remains the baseline. Elastic-net and PLS are challengers, pairwise
logistic heads are preset-specific, every validation transform is fit inside
its training fold, and no model receives requested labels as input features.
"""

from __future__ import annotations

import hashlib
import json
import math
import copy
from pathlib import Path
from typing import Any, Callable

import numpy as np

from delivery_evaluator import EvaluatorError, canonical_json, digest


SCHEMA_VERSION = 2
MODEL_VERSION = 2
DIMENSIONS = ("valence", "arousal", "dominance")
MODEL_KINDS = ("ridge-v1", "elastic-net-v2", "partial-least-squares-v2")
BLOCK_AXES = ("speakerID", "scriptTranslationGroup", "seed", "outputLanguage")
RIDGE_GRID = (0.01, 0.1, 1.0, 10.0)
ELASTIC_GRID = ((0.01, 0.25), (0.05, 0.5), (0.1, 0.75))
PLS_GRID = (1, 2, 3)
PAIRWISE_RIDGE_GRID = (0.01, 0.1, 1.0)


def validate_v2_contract(payload: dict[str, Any]) -> dict[str, Any]:
    """Validate the research boundary before any v2 workflow is allowed to run."""
    if not isinstance(payload, dict) or payload.get("schemaVersion") != SCHEMA_VERSION:
        raise EvaluatorError("delivery evaluator v2 contract schemaVersion must be 2")
    if payload.get("status") != "active-experimental":
        raise EvaluatorError("delivery evaluator v2 must remain experimental")
    host = payload.get("hostClass")
    if not isinstance(host, dict):
        raise EvaluatorError("delivery evaluator v2 host policy is missing")
    if host.get("executionPolicy") != "strictly-sequential-subprocesses":
        raise EvaluatorError("delivery evaluator v2 requires serial subprocesses")
    if host.get("provisionalMaximumProcessPeakRSSBytes") != 5 * 1024**3:
        raise EvaluatorError("delivery evaluator v2 provisional RSS ceiling drifted")
    if host.get("ceilingIsProvisional") is not True or host.get("qualificationRuns") != 2:
        raise EvaluatorError("delivery evaluator v2 host qualification policy drifted")
    cache = payload.get("cache")
    if not isinstance(cache, dict) or cache.get("reportsMayContainLocalPaths") is not False:
        raise EvaluatorError("delivery evaluator v2 reports must exclude local paths")
    if cache.get("atomicWrites") is not True or cache.get("failClosedOnDigestMismatch") is not True:
        raise EvaluatorError("delivery evaluator v2 cache must remain atomic and fail closed")
    human = payload.get("humanCalibration")
    if not isinstance(human, dict):
        raise EvaluatorError("delivery evaluator v2 human calibration policy is missing")
    if human.get("requestedLabelMayEnterDimensionalBlock") is not False:
        raise EvaluatorError("requested labels cannot enter blind dimensional features")
    if human.get("humanSemanticAuthorityRequired") is not True:
        raise EvaluatorError("human semantic authority cannot be removed")
    if human.get("minimumIntraRaterRepeatAgreement") != 0.75:
        raise EvaluatorError("listener repeat-agreement floor drifted")
    if human.get("minimumAnchorAccuracy") != 0.8:
        raise EvaluatorError("listener anchor-accuracy floor drifted")
    if human.get("minimumValidListenersPerRatedRow") != 3:
        raise EvaluatorError("per-row independent-listener floor drifted")
    evaluator = payload.get("evaluator")
    if not isinstance(evaluator, dict) or evaluator.get("baseline") != "ridge-v1":
        raise EvaluatorError("ridge-v1 must remain the delivery evaluator baseline")
    if evaluator.get("challengerMustImproveUntouchedHoldout") is not True:
        raise EvaluatorError("challengers require untouched holdout improvement")
    if evaluator.get("challengerMayRegressAnyVADDimension") is not False:
        raise EvaluatorError("challengers cannot regress a VAD dimension")
    if evaluator.get("challengerMayRegressAnyPreset") is not False:
        raise EvaluatorError("challengers cannot regress a preset")
    if evaluator.get("challengerMayRegressAnySpeaker") is not False:
        raise EvaluatorError("challengers cannot regress a speaker")
    if evaluator.get("challengerMayRegressAnyScriptGroup") is not False:
        raise EvaluatorError("challengers cannot regress a script group")
    if evaluator.get("distributedSpeakerAndScriptGainRequired") is not True:
        raise EvaluatorError("challenger gains must be speaker/script distributed")
    adapters = payload.get("compactAdapters")
    if not isinstance(adapters, dict) or adapters.get("adopted") != []:
        raise EvaluatorError("no compact model adapter is adopted by this contract")
    promotion = payload.get("promotion")
    if not isinstance(promotion, dict):
        raise EvaluatorError("delivery evaluator v2 promotion policy is missing")
    if promotion.get("automaticLayersMayPromoteSemanticDelivery") is not False:
        raise EvaluatorError("automatic layers cannot gain semantic promotion authority")
    if promotion.get("requestedLabelsForbiddenFromBlindFeatureExtraction") is not True:
        raise EvaluatorError("blind feature extraction cannot consume requested labels")
    if promotion.get("productionEmotionPresetChangesInThisWork") is not False:
        raise EvaluatorError("the evaluator contract cannot change production presets")
    if promotion.get("confirmationSelectorsForbidden") is not True:
        raise EvaluatorError("confirmation selectors must remain forbidden")
    return payload


def _finite(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise EvaluatorError(f"{label} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise EvaluatorError(f"{label} must be finite")
    return result


def _flatten(value: Any, prefix: str, output: dict[str, float]) -> None:
    if isinstance(value, dict):
        for key in sorted(value):
            if key in {"schemaVersion", "promotionAuthority", "memory"}:
                continue
            _flatten(value[key], f"{prefix}.{key}" if prefix else key, output)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _flatten(child, f"{prefix}[{index}]", output)
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        output[prefix] = _finite(value, prefix)


def load_v2_dataset(payload: dict[str, Any], *, require_labels: bool) -> tuple[list[str], list[dict[str, Any]]]:
    if not isinstance(payload, dict) or payload.get("schemaVersion") != SCHEMA_VERSION:
        raise EvaluatorError("v2 dataset schemaVersion must be 2")
    manifest_digest = payload.get("manifestDigest")
    if not isinstance(manifest_digest, str) or len(manifest_digest) != 64:
        raise EvaluatorError("v2 dataset requires a manifest digest")
    provenance = payload.get("labelProvenance")
    if require_labels:
        if not isinstance(provenance, dict) or provenance.get("kind") != "blinded-independent-listener-perceptual-v2":
            raise EvaluatorError("v2 labels require the blinded perceptual provenance")
        if provenance.get("calibrationQualified") is not True or provenance.get("qualificationFailures") != []:
            raise EvaluatorError("v2 labels are not calibration-qualified")
        if provenance.get("targetLabelsVisibleToDimensionalListeners") is not False:
            raise EvaluatorError("requested labels leaked into dimensional calibration")
    rows = payload.get("rows")
    if not isinstance(rows, list) or not rows:
        raise EvaluatorError("v2 dataset rows must be non-empty")
    normalized: list[dict[str, Any]] = []
    feature_sets: list[set[str]] = []
    generations: set[str] = set()
    for index, source in enumerate(rows):
        if not isinstance(source, dict):
            raise EvaluatorError(f"v2 row {index} must be an object")
        generation = source.get("generationID")
        if not isinstance(generation, str) or not generation or generation in generations:
            raise EvaluatorError("v2 generation identities are missing or duplicated")
        generations.add(generation)
        for axis in BLOCK_AXES:
            value = source.get(axis)
            if axis == "seed":
                if isinstance(value, bool) or not isinstance(value, int):
                    raise EvaluatorError(f"{generation}: seed is required")
            elif not isinstance(value, str) or not value:
                raise EvaluatorError(f"{generation}: {axis} is required")
        preset = source.get("preset")
        if not isinstance(preset, str) or not preset:
            raise EvaluatorError(f"{generation}: preset is required for head selection")
        features: dict[str, float] = {}
        if isinstance(source.get("flatFeatureVector"), dict):
            for name, value in source["flatFeatureVector"].items():
                if not isinstance(name, str) or not name:
                    raise EvaluatorError(f"{generation}: flat feature names must be strings")
                features[name] = _finite(value, f"{generation}.{name}")
        else:
            _flatten(source.get("features"), "global", features)
            if source.get("temporalDeltaV1") is not None:
                _flatten(source["temporalDeltaV1"], "temporal", features)
            if source.get("compactDeltaV1") is not None:
                compact = source["compactDeltaV1"]
                if not isinstance(compact, dict) or not isinstance(compact.get("featureVector"), dict):
                    raise EvaluatorError(f"{generation}: compact feature block is invalid")
                _flatten(compact["featureVector"], "compact", features)
        if not features:
            raise EvaluatorError(f"{generation}: no blind acoustic features")
        feature_sets.append(set(features))
        labels = source.get("labels")
        if require_labels:
            if not isinstance(labels, dict) or set(labels) != set(DIMENSIONS):
                raise EvaluatorError(f"{generation}: v2 VAD labels are incomplete")
            labels = {dimension: _finite(labels[dimension], f"{generation}.{dimension}") for dimension in DIMENSIONS}
            if any(not -1 <= value <= 1 for value in labels.values()):
                raise EvaluatorError("v2 VAD labels must lie in [-1, 1]")
            preference = _finite(source.get("targetPreference"), f"{generation}.targetPreference")
            if not 0 <= preference <= 1:
                raise EvaluatorError("targetPreference must lie in [0, 1]")
        else:
            preference = source.get("targetPreference")
        normalized.append({**source, "features": features, "labels": labels, "targetPreference": preference})
    if any(features != feature_sets[0] for features in feature_sets[1:]):
        raise EvaluatorError("v2 feature sets differ across rows")
    if require_labels:
        for axis in BLOCK_AXES:
            if len({row[axis] for row in normalized}) < 2:
                raise EvaluatorError(f"v2 calibration needs at least two {axis} groups")
    return sorted(feature_sets[0]), normalized


def _matrix(rows: list[dict[str, Any]], features: list[str]) -> np.ndarray:
    return np.asarray([[row["features"][name] for name in features] for row in rows], dtype=np.float64)


def _standardize_train(x: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    means = np.median(x, axis=0)
    scales = np.std(x, axis=0)
    selected = np.flatnonzero(scales > 1e-9)
    if selected.size == 0:
        selected = np.asarray([0], dtype=np.int64)
        scales[0] = 1.0
    scales[scales < 1e-9] = 1.0
    return (x[:, selected] - means[selected]) / scales[selected], means, scales, selected


def _fit_ridge(x: np.ndarray, y: np.ndarray, ridge: float) -> tuple[np.ndarray, float]:
    augmented = np.column_stack((np.ones(len(x)), x))
    penalty = np.eye(augmented.shape[1]) * ridge
    penalty[0, 0] = 0.0
    coefficients = np.linalg.solve(augmented.T @ augmented + penalty, augmented.T @ y)
    return coefficients[1:], float(coefficients[0])


def _soft(value: float, penalty: float) -> float:
    return math.copysign(max(0.0, abs(value) - penalty), value)


def _fit_elastic(x: np.ndarray, y: np.ndarray, parameter: tuple[float, float]) -> tuple[np.ndarray, float]:
    alpha, l1_ratio = parameter
    intercept = float(np.mean(y))
    centered_y = y - intercept
    coefficients = np.zeros(x.shape[1], dtype=np.float64)
    for _ in range(500):
        previous = coefficients.copy()
        for column in range(x.shape[1]):
            residual = centered_y - x @ coefficients + x[:, column] * coefficients[column]
            rho = float(np.dot(x[:, column], residual)) / max(1, len(x))
            norm = float(np.dot(x[:, column], x[:, column])) / max(1, len(x))
            coefficients[column] = _soft(rho, alpha * l1_ratio) / max(norm + alpha * (1 - l1_ratio), 1e-12)
        if float(np.max(np.abs(coefficients - previous))) < 1e-9:
            break
    return coefficients, intercept


def _fit_pls(x: np.ndarray, y: np.ndarray, components: int) -> tuple[np.ndarray, float]:
    intercept = float(np.mean(y))
    residual_x = x.copy()
    residual_y = y - intercept
    weights, loadings, responses = [], [], []
    for _ in range(min(components, x.shape[1], max(1, x.shape[0] - 1))):
        weight = residual_x.T @ residual_y
        norm = float(np.linalg.norm(weight))
        if norm < 1e-12:
            break
        weight = weight / norm
        score = residual_x @ weight
        denominator = float(np.dot(score, score))
        if denominator < 1e-12:
            break
        loading = residual_x.T @ score / denominator
        response = float(np.dot(residual_y, score) / denominator)
        residual_x -= np.outer(score, loading)
        residual_y -= response * score
        weights.append(weight); loadings.append(loading); responses.append(response)
    if not weights:
        return np.zeros(x.shape[1]), intercept
    w = np.column_stack(weights)
    p = np.column_stack(loadings)
    coefficients = w @ np.linalg.pinv(p.T @ w) @ np.asarray(responses)
    return coefficients, intercept


def _parameters(kind: str) -> tuple[Any, ...]:
    return {"ridge-v1": RIDGE_GRID, "elastic-net-v2": ELASTIC_GRID, "partial-least-squares-v2": PLS_GRID}[kind]


def _fit(kind: str, x: np.ndarray, y: np.ndarray, parameter: Any) -> tuple[np.ndarray, float]:
    if kind == "ridge-v1":
        return _fit_ridge(x, y, float(parameter))
    if kind == "elastic-net-v2":
        return _fit_elastic(x, y, parameter)
    return _fit_pls(x, y, int(parameter))


def _predict(x: np.ndarray, coefficients: np.ndarray, intercept: float) -> np.ndarray:
    return np.clip(x @ coefficients + intercept, -1.0, 1.0)


def _rmse(y: np.ndarray, predicted: np.ndarray) -> float:
    return float(np.sqrt(np.mean((y - predicted) ** 2)))


def _ccc(y: np.ndarray, predicted: np.ndarray) -> float | None:
    if len(y) < 2:
        return None
    denominator = float(np.var(y) + np.var(predicted) + (np.mean(y) - np.mean(predicted)) ** 2)
    return float(2 * np.mean((y - np.mean(y)) * (predicted - np.mean(predicted))) / denominator) if denominator > 0 else None


def _blocked_partitions(values: set[Any], maximum_folds: int) -> list[set[Any]]:
    ordered = sorted(values, key=lambda value: hashlib.sha256(str(value).encode()).hexdigest())
    fold_count = min(maximum_folds, len(ordered))
    return [set(ordered[index::fold_count]) for index in range(fold_count)] if fold_count else []


def _select_parameter(rows: list[dict[str, Any]], features: list[str], dimension: str, kind: str) -> Any:
    groups = {(row["scriptTranslationGroup"], row["seed"]) for row in rows}
    partitions = _blocked_partitions(groups, 4)
    scores = []
    for parameter in _parameters(kind):
        errors = []
        for held_groups in partitions:
            train = [row for row in rows if (row["scriptTranslationGroup"], row["seed"]) not in held_groups]
            test = [row for row in rows if (row["scriptTranslationGroup"], row["seed"]) in held_groups]
            if len(train) < 3 or not test:
                continue
            train_x, means, scales, selected = _standardize_train(_matrix(train, features))
            test_x = (_matrix(test, features)[:, selected] - means[selected]) / scales[selected]
            coefficients, intercept = _fit(kind, train_x, np.asarray([row["labels"][dimension] for row in train]), parameter)
            errors.append(_rmse(np.asarray([row["labels"][dimension] for row in test]), _predict(test_x, coefficients, intercept)))
        scores.append((float(np.mean(errors)) if errors else float("inf"), str(parameter), parameter))
    return min(scores, key=lambda value: (value[0], value[1]))[2]


def _blocked_validation(rows: list[dict[str, Any]], features: list[str], dimension: str, kind: str) -> dict[str, Any]:
    axes: dict[str, Any] = {}
    speaker_expected: list[float] = []
    speaker_predicted: list[float] = []
    speaker_residuals: list[float] = []
    for axis in BLOCK_AXES:
        folds = []
        expected, predicted = [], []
        for held_groups in _blocked_partitions({row[axis] for row in rows}, 5):
            train = [row for row in rows if row[axis] not in held_groups]
            test = [row for row in rows if row[axis] in held_groups]
            if len(train) < 3 or not test:
                continue
            parameter = _select_parameter(train, features, dimension, kind)
            train_x, means, scales, selected = _standardize_train(_matrix(train, features))
            test_x = (_matrix(test, features)[:, selected] - means[selected]) / scales[selected]
            coefficients, intercept = _fit(kind, train_x, np.asarray([row["labels"][dimension] for row in train]), parameter)
            observed = np.asarray([row["labels"][dimension] for row in test])
            estimates = _predict(test_x, coefficients, intercept)
            expected.extend(observed.tolist()); predicted.extend(estimates.tolist())
            folds.append({
                "heldOutGroupDigest": digest(sorted(held_groups, key=str)),
                "heldOutGroupCount": len(held_groups),
                "n": len(test), "parameter": parameter,
                "selectedFeatureCount": int(len(selected)),
                "rmse": _rmse(observed, estimates),
            })
        expected_array, predicted_array = np.asarray(expected), np.asarray(predicted)
        axes[axis] = {
            "n": len(expected), "rmse": _rmse(expected_array, predicted_array),
            "ccc": _ccc(expected_array, predicted_array), "folds": folds,
        }
        if axis == "speakerID":
            speaker_expected, speaker_predicted = expected, predicted
            speaker_residuals = [abs(a - b) for a, b in zip(expected, predicted)]
    conformal = float(np.quantile(speaker_residuals, 0.90, method="higher")) if speaker_residuals else 2.0
    return {
        "foldLocalReduction": True,
        "axes": axes,
        "primary": axes["speakerID"],
        "splitConformal90HalfWidth": conformal,
        "speakerOOFExpectedDigest": digest(speaker_expected),
        "speakerOOFPredictedDigest": digest(speaker_predicted),
    }


def _fit_final(rows: list[dict[str, Any]], features: list[str], dimension: str, kind: str) -> dict[str, Any]:
    parameter = _select_parameter(rows, features, dimension, kind)
    x, means, scales, selected = _standardize_train(_matrix(rows, features))
    coefficients, intercept = _fit(kind, x, np.asarray([row["labels"][dimension] for row in rows]), parameter)
    validation = _blocked_validation(rows, features, dimension, kind)
    full_coefficients = np.zeros(len(features), dtype=np.float64)
    full_coefficients[selected] = coefficients
    return {
        "parameter": parameter,
        "intercept": intercept,
        "coefficients": {name: float(value) for name, value in zip(features, full_coefficients)},
        "selectedFeatures": [features[int(index)] for index in selected],
        "validation": validation,
    }


def _sigmoid(value: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-np.clip(value, -30, 30)))


def _fit_logistic(x: np.ndarray, y: np.ndarray, ridge: float) -> tuple[np.ndarray, float]:
    coefficients = np.zeros(x.shape[1])
    intercept = 0.0
    for _ in range(1500):
        probabilities = _sigmoid(x @ coefficients + intercept)
        residual = probabilities - y
        gradient = x.T @ residual / len(x) + ridge * coefficients
        intercept_gradient = float(np.mean(residual))
        step = 0.2
        coefficients -= step * gradient
        intercept -= step * intercept_gradient
        if max(float(np.max(np.abs(gradient))), abs(intercept_gradient)) < 1e-7:
            break
    return coefficients, intercept


def _binary_preferences(rows: list[dict[str, Any]]) -> np.ndarray:
    return np.asarray([1.0 if row["targetPreference"] > 0.5 else 0.0 for row in rows])


def _select_logistic_ridge(rows: list[dict[str, Any]], features: list[str]) -> float:
    groups = {(row["scriptTranslationGroup"], row["seed"]) for row in rows}
    scores = []
    for ridge in PAIRWISE_RIDGE_GRID:
        brier_scores = []
        for held_groups in _blocked_partitions(groups, 4):
            train = [
                row for row in rows
                if (row["scriptTranslationGroup"], row["seed"]) not in held_groups
            ]
            test = [
                row for row in rows
                if (row["scriptTranslationGroup"], row["seed"]) in held_groups
            ]
            train_labels = _binary_preferences(train)
            if len(train) < 4 or not test or len(set(train_labels.tolist())) < 2:
                continue
            train_x, means, scales, selected = _standardize_train(_matrix(train, features))
            test_x = (_matrix(test, features)[:, selected] - means[selected]) / scales[selected]
            coefficients, intercept = _fit_logistic(train_x, train_labels, ridge)
            probabilities = _sigmoid(test_x @ coefficients + intercept)
            brier_scores.append(float(np.mean((probabilities - _binary_preferences(test)) ** 2)))
        scores.append((float(np.mean(brier_scores)) if brier_scores else float("inf"), ridge))
    selected_score, selected_ridge = min(scores, key=lambda value: (value[0], value[1]))
    if not math.isfinite(selected_score):
        raise EvaluatorError("pairwise ridge selection has no valid blocked fold")
    return selected_ridge


def _pairwise_blocked_validation(
    rows: list[dict[str, Any]], features: list[str],
) -> dict[str, Any]:
    axes: dict[str, Any] = {}
    for axis in BLOCK_AXES:
        folds = []
        all_labels: list[float] = []
        all_probabilities: list[float] = []
        for held_groups in _blocked_partitions({row[axis] for row in rows}, 5):
            train = [row for row in rows if row[axis] not in held_groups]
            test = [row for row in rows if row[axis] in held_groups]
            train_labels = _binary_preferences(train)
            if len(train) < 4 or not test or len(set(train_labels.tolist())) < 2:
                continue
            ridge = _select_logistic_ridge(train, features)
            train_x, means, scales, selected = _standardize_train(_matrix(train, features))
            test_x = (_matrix(test, features)[:, selected] - means[selected]) / scales[selected]
            coefficients, intercept = _fit_logistic(train_x, train_labels, ridge)
            labels = _binary_preferences(test)
            probabilities = _sigmoid(test_x @ coefficients + intercept)
            all_labels.extend(labels.tolist())
            all_probabilities.extend(probabilities.tolist())
            folds.append({
                "heldOutGroupDigest": digest(sorted(held_groups, key=str)),
                "heldOutGroupCount": len(held_groups),
                "n": len(test),
                "ridge": ridge,
                "selectedFeatureCount": int(len(selected)),
                "brierScore": float(np.mean((probabilities - labels) ** 2)),
            })
        if not folds:
            raise EvaluatorError(f"pairwise {axis} validation has no valid blocked fold")
        labels_array = np.asarray(all_labels)
        probabilities_array = np.asarray(all_probabilities)
        axes[axis] = {
            "n": len(all_labels),
            "brierScore": float(np.mean((probabilities_array - labels_array) ** 2)),
            "accuracy": float(np.mean((probabilities_array >= 0.5) == labels_array)),
            "folds": folds,
        }
    return {"foldLocalReduction": True, "axes": axes}


def _pairwise_heads(rows: list[dict[str, Any]], features: list[str]) -> dict[str, Any]:
    heads: dict[str, Any] = {}
    for preset in sorted({row["preset"] for row in rows}):
        subset = [
            row for row in rows
            if row["preset"] == preset and not math.isclose(row["targetPreference"], 0.5)
        ]
        labels = _binary_preferences(subset)
        complete_blocking = all(len({row[axis] for row in subset}) >= 2 for axis in BLOCK_AXES)
        if len(subset) < 8 or len(set(labels.tolist())) < 2 or not complete_blocking:
            heads[preset] = {"status": "uncalibrated", "reason": "insufficient-balanced-human-preferences"}
            continue
        x, means, scales, selected = _standardize_train(_matrix(subset, features))
        ridge = _select_logistic_ridge(subset, features)
        coefficients, intercept = _fit_logistic(x, labels, ridge)
        full_coefficients = np.zeros(len(features)); full_coefficients[selected] = coefficients
        probabilities = _sigmoid(x @ coefficients + intercept)
        predictions = probabilities >= 0.5
        positive = labels == 1; negative = labels == 0
        balanced = 0.5 * (
            float(np.mean(predictions[positive] == labels[positive]))
            + float(np.mean(predictions[negative] == labels[negative]))
        )
        brier = float(np.mean((probabilities - labels) ** 2))
        heads[preset] = {
            "status": "calibrated", "ridge": ridge, "intercept": intercept,
            "coefficients": {name: float(value) for name, value in zip(features, full_coefficients)},
            "featureMeans": {name: float(value) for name, value in zip(features, means)},
            "featureScales": {name: float(value) for name, value in zip(features, scales)},
            "selectedFeatures": [features[int(index)] for index in selected],
            "balancedAccuracy": balanced, "brierScore": brier,
            "validation": _pairwise_blocked_validation(subset, features),
            "coverageRisk": [
                {
                    "minimumConfidence": threshold,
                    "coverage": float(np.mean(np.abs(probabilities - 0.5) * 2 >= threshold)),
                    "risk": float(np.mean(predictions[np.abs(probabilities - 0.5) * 2 >= threshold] != labels[np.abs(probabilities - 0.5) * 2 >= threshold]))
                    if np.any(np.abs(probabilities - 0.5) * 2 >= threshold) else None,
                }
                for threshold in (0.0, 0.25, 0.5, 0.75)
            ],
        }
    return heads


def _ood_model(x: np.ndarray, features: list[str]) -> dict[str, Any]:
    center = np.median(x, axis=0)
    mad = np.median(np.abs(x - center), axis=0) * 1.4826
    mad[mad < 1e-6] = 1.0
    robust = (x - center) / mad
    covariance = np.cov(robust, rowvar=False)
    if covariance.ndim == 0:
        covariance = np.asarray([[float(covariance)]])
    covariance += np.eye(covariance.shape[0]) * 0.1
    inverse = np.linalg.pinv(covariance)
    distances = np.sqrt(np.maximum(0.0, np.einsum("ij,jk,ik->i", robust, inverse, robust)))
    nearest = []
    for index in range(len(robust)):
        others = np.delete(robust, index, axis=0)
        nearest.append(float(np.min(np.linalg.norm(others - robust[index], axis=1))) if len(others) else 0.0)
    return {
        "center": {name: float(value) for name, value in zip(features, center)},
        "scale": {name: float(value) for name, value in zip(features, mad)},
        "perFeatureAbsolute99": {
            name: max(3.0, float(value))
            for name, value in zip(features, np.quantile(np.abs(robust), 0.99, axis=0))
        },
        "inverseCovariance": inverse.tolist(),
        "mahalanobis95": float(np.quantile(distances, 0.95)),
        "nearestNeighbor95": float(np.quantile(nearest, 0.95)),
        "referenceVectors": robust.tolist(),
        "speakerGroups": [],
        "languageGroups": [],
    }


def calibrate_v2(payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("labelProvenance", {}).get("sourceSplit") != "calibration":
        raise EvaluatorError("v2 model fitting requires the calibration split")
    features, rows = load_v2_dataset(payload, require_labels=True)
    models = {
        kind: {
            dimension: _fit_final(rows, features, dimension, kind)
            for dimension in DIMENSIONS
        }
        for kind in MODEL_KINDS
    }
    baseline_error = float(np.mean([
        models["ridge-v1"][dimension]["validation"]["primary"]["rmse"]
        for dimension in DIMENSIONS
    ]))
    preselection_rows = []
    for kind in MODEL_KINDS[1:]:
        dimension_errors = {
            dimension: models[kind][dimension]["validation"]["primary"]["rmse"]
            for dimension in DIMENSIONS
        }
        regressions = [
            dimension for dimension, error in dimension_errors.items()
            if error > models["ridge-v1"][dimension]["validation"]["primary"]["rmse"] + 1e-12
        ]
        mean_error = float(np.mean(list(dimension_errors.values())))
        preselection_rows.append({
            "modelKind": kind,
            "speakerBlockedMeanRMSE": mean_error,
            "dimensionRMSE": dimension_errors,
            "dimensionRegressions": regressions,
            "eligibleForOneTimeHoldout": mean_error < baseline_error and not regressions,
        })
    eligible = [row for row in preselection_rows if row["eligibleForOneTimeHoldout"]]
    preselected = min(
        eligible, key=lambda row: (row["speakerBlockedMeanRMSE"], row["modelKind"])
    )["modelKind"] if eligible else None
    means = np.median(_matrix(rows, features), axis=0)
    scales = np.std(_matrix(rows, features), axis=0)
    scales[scales < 1e-9] = 1.0
    model = {
        "schemaVersion": SCHEMA_VERSION,
        "modelVersion": MODEL_VERSION,
        "kind": "local-perceptual-delivery-evaluator-v2",
        "promotionAuthority": False,
        "trainerSHA256": hashlib.sha256(Path(__file__).resolve().read_bytes()).hexdigest(),
        "baseline": "ridge-v1",
        "adoptedDimensionalModel": "ridge-v1",
        "challengerAdoptionStatus": (
            "preselected-awaiting-untouched-human-holdout"
            if preselected is not None else "no-calibration-challenger-qualified"
        ),
        "preselectedChallenger": preselected,
        "preselection": {
            "usedConfirmationLabels": False,
            "baselineSpeakerBlockedMeanRMSE": baseline_error,
            "candidates": preselection_rows,
        },
        "featureNames": features,
        "featureMeans": {name: float(value) for name, value in zip(features, means)},
        "featureScales": {name: float(value) for name, value in zip(features, scales)},
        "dimensionalModels": models,
        "pairwiseHeads": _pairwise_heads(rows, features),
        "ood": _ood_model(_matrix(rows, features), features),
        "trainingManifestDigest": payload["manifestDigest"],
        "labelProvenanceDigest": digest(payload["labelProvenance"]),
        "trainingRowsDigest": digest(rows),
        "trainingRowCount": len(rows),
        "speakerGroups": sorted({row["speakerID"] for row in rows}),
        "languageGroups": sorted({row["outputLanguage"] for row in rows}),
    }
    model["ood"]["speakerGroups"] = model["speakerGroups"]
    model["ood"]["languageGroups"] = model["languageGroups"]
    model["modelDigest"] = digest(model)
    return model


def attach_compact_features(
    payload: dict[str, Any], cascade: dict[str, Any],
) -> dict[str, Any]:
    """Join blind compact deltas by generation identity without touching labels."""
    if payload.get("schemaVersion") != SCHEMA_VERSION or not isinstance(payload.get("rows"), list):
        raise EvaluatorError("compact attachment requires a v2 listener dataset")
    if cascade.get("schemaVersion") != 1 or cascade.get("kind") != "local-delivery-cascade":
        raise EvaluatorError("compact attachment requires a local delivery cascade report")
    cascade_rows = cascade.get("rows")
    if not isinstance(cascade_rows, list):
        raise EvaluatorError("compact cascade rows are missing")
    by_generation: dict[str, dict[str, Any]] = {}
    adapter_ids: set[str] = set()
    feature_names: set[str] | None = None
    for row in cascade_rows:
        generation = row.get("generationID") if isinstance(row, dict) else None
        compact = row.get("alwaysLayers", {}).get("compactRepresentation") if isinstance(row, dict) else None
        if not isinstance(generation, str) or not generation or generation in by_generation:
            raise EvaluatorError("compact cascade generation identities are missing or duplicated")
        if not isinstance(compact, dict) or compact.get("kind") != "compact-instructed-minus-neutral-delta":
            raise EvaluatorError(f"{generation}: compact cascade feature is unavailable")
        vector = compact.get("featureVector")
        if not isinstance(vector, dict) or not vector:
            raise EvaluatorError(f"{generation}: compact feature vector is empty")
        normalized: dict[str, float] = {}
        for name, value in vector.items():
            if not isinstance(name, str) or not name:
                raise EvaluatorError(f"{generation}: compact feature name is invalid")
            normalized[name] = _finite(value, f"{generation}.compact.{name}")
        names = set(normalized)
        if feature_names is None:
            feature_names = names
        elif names != feature_names:
            raise EvaluatorError("compact feature sets differ across cascade rows")
        adapter = compact.get("adapterID")
        if not isinstance(adapter, str) or not adapter:
            raise EvaluatorError(f"{generation}: compact adapter identity is missing")
        adapter_ids.add(adapter)
        by_generation[generation] = {**compact, "featureVector": normalized}
    dataset_generations = {
        row.get("generationID") for row in payload["rows"] if isinstance(row, dict)
    }
    if None in dataset_generations or dataset_generations != set(by_generation):
        raise EvaluatorError("listener dataset and compact cascade coverage differ")
    if len(adapter_ids) != 1:
        raise EvaluatorError("compact cascade mixes adapter identities")
    attached = copy.deepcopy(payload)
    prior_manifest = attached.get("manifestDigest")
    if not isinstance(prior_manifest, str) or len(prior_manifest) != 64:
        raise EvaluatorError("listener dataset manifest digest is invalid")
    for row in attached["rows"]:
        if row.get("compactDeltaV1") is not None:
            raise EvaluatorError("listener dataset already contains compact features")
        row["compactDeltaV1"] = by_generation[row["generationID"]]
    attachment = {
        "schemaVersion": 1,
        "kind": "blind-compact-feature-attachment",
        "promotionAuthority": False,
        "adapterID": next(iter(adapter_ids)),
        "sourceManifestDigest": prior_manifest,
        "cascadeInputManifestDigest": cascade.get("inputManifestDigest"),
        "rowCount": len(attached["rows"]),
        "featureNames": sorted(feature_names or set()),
        "rowFeatureDigests": {
            generation: digest(by_generation[generation]) for generation in sorted(by_generation)
        },
    }
    attachment["attachmentDigest"] = digest(attachment)
    attached["compactFeatureAttachment"] = attachment
    attached["manifestDigest"] = digest({
        "sourceManifestDigest": prior_manifest,
        "attachmentDigest": attachment["attachmentDigest"],
    })
    return attached


def score_untouched_holdout(payload: dict[str, Any], model: dict[str, Any]) -> dict[str, Any]:
    """Score every fitted VAD family against a once-opened human confirmation set."""
    model = validate_v2_model(model)
    if payload.get("labelProvenance", {}).get("sourceSplit") != "confirmation":
        raise EvaluatorError("v2 holdout scoring requires the untouched confirmation split")
    features, rows = load_v2_dataset(payload, require_labels=True)
    if features != model.get("featureNames"):
        raise EvaluatorError("v2 holdout feature order differs from calibration")
    preselected = model.get("preselectedChallenger")
    if preselected not in MODEL_KINDS[1:]:
        raise EvaluatorError("no calibration-selected challenger may open the untouched holdout")
    x = _matrix(rows, features)
    means = np.asarray([model["featureMeans"][name] for name in features])
    scales = np.asarray([model["featureScales"][name] for name in features])
    standardized = (x - means) / scales

    def errors_for(kind: str) -> dict[str, Any]:
        per_row: dict[str, list[float]] = {}
        dimension_errors: dict[str, float] = {}
        for dimension in DIMENSIONS:
            entry = model["dimensionalModels"][kind][dimension]
            coefficients = np.asarray([entry["coefficients"][name] for name in features])
            predicted = np.clip(standardized @ coefficients + entry["intercept"], -1, 1)
            expected = np.asarray([row["labels"][dimension] for row in rows])
            dimension_errors[dimension] = _rmse(expected, predicted)
            for index, row in enumerate(rows):
                per_row.setdefault(row["generationID"], []).append(float(predicted[index] - expected[index]))

        def grouped(axis: str) -> dict[str, float]:
            result: dict[str, float] = {}
            for group in sorted({str(row[axis]) for row in rows}):
                residuals = [
                    residual
                    for row in rows if str(row[axis]) == group
                    for residual in per_row[row["generationID"]]
                ]
                result[group] = math.sqrt(sum(value * value for value in residuals) / len(residuals))
            return result

        residuals = [value for values in per_row.values() for value in values]
        return {
            "overallCalibrationError": math.sqrt(sum(value * value for value in residuals) / len(residuals)),
            "dimensions": dimension_errors,
            "presets": grouped("preset"),
            "speakers": grouped("speakerID"),
            "scriptGroups": grouped("scriptTranslationGroup"),
        }

    result = {
        "schemaVersion": SCHEMA_VERSION,
        "kind": "delivery-evaluator-v2-untouched-holdout-scores",
        "designation": "untouched-confirmation",
        "promotionAuthority": False,
        "modelDigest": model["modelDigest"],
        "inputManifestDigest": payload["manifestDigest"],
        "rowCount": len(rows),
        "preselectedChallenger": preselected,
        "models": {
            kind: errors_for(kind) for kind in ("ridge-v1", preselected)
        },
    }
    result["scoreDigest"] = digest(result)
    return result


def validate_v2_model(model: dict[str, Any]) -> dict[str, Any]:
    if model.get("schemaVersion") != SCHEMA_VERSION or model.get("modelVersion") != MODEL_VERSION:
        raise EvaluatorError("v2 model schema is invalid")
    body = dict(model); stored = body.pop("modelDigest", None)
    if stored != digest(body):
        raise EvaluatorError("v2 model digest mismatch")
    if model.get("promotionAuthority") is not False or model.get("baseline") != "ridge-v1":
        raise EvaluatorError("v2 model authority or baseline changed")
    if model.get("trainerSHA256") != hashlib.sha256(Path(__file__).resolve().read_bytes()).hexdigest():
        raise EvaluatorError("v2 model trainer source changed")
    return model


def _contradictions(preset: str, dimensions: dict[str, Any]) -> list[str]:
    values = {name: dimensions[name]["value"] for name in DIMENSIONS}
    reasons = []
    if preset == "happy" and values["valence"] < 0:
        reasons.append("happy-negative-valence")
    if preset in {"angry", "sad", "fearful"} and values["valence"] > 0:
        reasons.append(f"{preset}-positive-valence")
    if preset == "calm" and values["arousal"] > 0.35:
        reasons.append("calm-high-arousal")
    if preset == "fearful" and values["dominance"] > 0.35:
        reasons.append("fearful-high-dominance")
    return reasons


def evaluate_v2(payload: dict[str, Any], model: dict[str, Any]) -> dict[str, Any]:
    model = validate_v2_model(model)
    features, rows = load_v2_dataset(payload, require_labels=False)
    if features != model["featureNames"]:
        raise EvaluatorError("v2 evaluation feature order differs from calibration")
    x = _matrix(rows, features)
    center = np.asarray([model["ood"]["center"][name] for name in features])
    scale = np.asarray([model["ood"]["scale"][name] for name in features])
    robust = (x - center) / scale
    inverse = np.asarray(model["ood"]["inverseCovariance"])
    mahalanobis = np.sqrt(np.maximum(0.0, np.einsum("ij,jk,ik->i", robust, inverse, robust)))
    references = np.asarray(model["ood"]["referenceVectors"], dtype=np.float64)
    training_novelty = [
        float(np.min(np.linalg.norm(references - robust[index], axis=1)))
        if len(references) else float("inf")
        for index in range(len(robust))
    ]
    means = np.asarray([model["featureMeans"][name] for name in features])
    scales = np.asarray([model["featureScales"][name] for name in features])
    standardized = (x - means) / scales
    selected_kind = model["adoptedDimensionalModel"]
    reports = []
    for index, row in enumerate(rows):
        ood_reasons = []
        feature_excursions = [
            name for feature_index, name in enumerate(features)
            if abs(robust[index, feature_index])
            > model["ood"]["perFeatureAbsolute99"][name]
        ]
        if feature_excursions:
            ood_reasons.append("per-feature-robust-z")
        if mahalanobis[index] > model["ood"]["mahalanobis95"]:
            ood_reasons.append("robust-mahalanobis")
        if training_novelty[index] > model["ood"]["nearestNeighbor95"]:
            ood_reasons.append("nearest-neighbor-distance")
        if row["speakerID"] not in model["speakerGroups"]:
            ood_reasons.append("speaker-novelty")
        if row["outputLanguage"] not in model["languageGroups"]:
            ood_reasons.append("language-novelty")
        dimensions = {}
        for dimension in DIMENSIONS:
            entry = model["dimensionalModels"][selected_kind][dimension]
            coefficients = np.asarray([entry["coefficients"][name] for name in features])
            value = float(np.clip(standardized[index] @ coefficients + entry["intercept"], -1, 1))
            width = float(entry["validation"]["splitConformal90HalfWidth"])
            dimensions[dimension] = {
                "value": value,
                "interval90": [max(-1.0, value - width), min(1.0, value + width)],
                "abstained": bool(ood_reasons),
                "abstainReasons": list(ood_reasons),
            }
        contradictions = _contradictions(row["preset"], dimensions)
        head = model["pairwiseHeads"].get(row["preset"], {"status": "uncalibrated"})
        if head.get("status") == "calibrated":
            coefficients = np.asarray([head["coefficients"][name] for name in features])
            head_means = np.asarray([head["featureMeans"][name] for name in features])
            head_scales = np.asarray([head["featureScales"][name] for name in features])
            head_standardized = (x[index] - head_means) / head_scales
            probability = float(_sigmoid(np.asarray([head_standardized @ coefficients + head["intercept"]]))[0])
            pairwise = {"status": "calibrated", "targetAlignedProbability": probability}
        else:
            pairwise = {"status": "abstained", "reason": head.get("reason", "missing-preset-head")}
        abstentions = list(ood_reasons)
        if pairwise["status"] != "calibrated":
            abstentions.append("pairwise-head-unavailable")
        if contradictions:
            abstentions.append("typed-contradiction")
        reports.append({
            "generationID": row["generationID"], "preset": row["preset"],
            "dimensions": dimensions, "pairwise": pairwise,
            "ood": {
                "mahalanobis": float(mahalanobis[index]),
                "nearestNeighborDistance": training_novelty[index],
                "maximumAbsoluteRobustZ": float(np.max(np.abs(robust[index]))),
                "featureExcursions": feature_excursions,
                "reasons": ood_reasons,
            },
            "contradictions": contradictions,
            "abstained": bool(abstentions), "abstainReasons": sorted(set(abstentions)),
        })
    return {
        "schemaVersion": SCHEMA_VERSION,
        "kind": "local-perceptual-delivery-evaluation-v2",
        "promotionAuthority": False,
        "modelDigest": model["modelDigest"],
        "inputManifestDigest": payload["manifestDigest"],
        "rows": reports,
    }


def compare_untouched_holdout(payload: dict[str, Any]) -> dict[str, Any]:
    if (
        payload.get("designation") != "untouched-confirmation"
        or payload.get("kind") != "delivery-evaluator-v2-untouched-holdout-scores"
    ):
        raise EvaluatorError("challenger selection requires the untouched confirmation designation")
    body = dict(payload)
    stored_digest = body.pop("scoreDigest", None)
    if stored_digest != digest(body):
        raise EvaluatorError("untouched holdout score digest mismatch")
    preselected = payload.get("preselectedChallenger")
    if preselected not in MODEL_KINDS[1:]:
        raise EvaluatorError("untouched holdout lacks one preselected challenger")
    models = payload.get("models")
    if not isinstance(models, dict) or set(models) != {"ridge-v1", preselected}:
        raise EvaluatorError("untouched holdout exposed an unselected challenger")
    baseline = models["ridge-v1"]
    challenger = models[preselected]
    if not isinstance(baseline, dict) or not isinstance(challenger, dict):
        raise EvaluatorError("holdout comparison requires baseline and challenger metrics")
    regressions = []
    improvements = []
    for dimension in DIMENSIONS:
        baseline_error = _finite(baseline.get("dimensions", {}).get(dimension), f"baseline.{dimension}")
        challenger_error = _finite(challenger.get("dimensions", {}).get(dimension), f"challenger.{dimension}")
        if challenger_error > baseline_error + 1e-12:
            regressions.append(f"vad-{dimension}")
        elif challenger_error < baseline_error - 1e-12:
            improvements.append(f"vad-{dimension}")
    distributed_improvements: dict[str, int] = {}
    for section, prefix in (("presets", "preset"), ("speakers", "speaker"), ("scriptGroups", "script")):
        baseline_groups = baseline.get(section)
        challenger_groups = challenger.get(section)
        if not isinstance(baseline_groups, dict) or not baseline_groups:
            raise EvaluatorError(f"baseline {section} coverage is missing")
        if not isinstance(challenger_groups, dict) or set(challenger_groups) != set(baseline_groups):
            raise EvaluatorError(f"challenger {section} coverage differs from baseline")
        improved = 0
        for group, baseline_error in baseline_groups.items():
            challenger_error = challenger_groups[group]
            left = _finite(baseline_error, f"baseline.{section}.{group}")
            right = _finite(challenger_error, f"challenger.{section}.{group}")
            if right > left + 1e-12:
                regressions.append(f"{prefix}-{group}")
            elif right < left - 1e-12:
                improved += 1
        distributed_improvements[section] = improved
    baseline_overall = _finite(baseline.get("overallCalibrationError"), "baseline.overall")
    challenger_overall = _finite(challenger.get("overallCalibrationError"), "challenger.overall")
    distributed = all(value > 0 for value in distributed_improvements.values())
    qualifies = (
        challenger_overall < baseline_overall and bool(improvements)
        and distributed and not regressions
    )
    return {
        "schemaVersion": SCHEMA_VERSION,
        "kind": "delivery-evaluator-v2-untouched-holdout-comparison",
        "promotionAuthority": False,
        "preselectedChallenger": preselected,
        "challengerAdvances": qualifies,
        "improvements": improvements,
        "distributedImprovements": distributed_improvements,
        "regressions": regressions,
        "decision": "advance-for-advisory-use" if qualifies else "retain-ridge-v1",
    }
