#!/usr/bin/env python3
"""Governed autonomous acoustic screening for per-preset delivery prompts.

This extends the existing delivery experiment runner. Feature extraction stays
label blind; requested preset labels enter only after the acoustic and temporal
layers exist. Automatic results can reject or retain a candidate for research,
but never claim perceptual superiority or authorize production publication.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import statistics
import sys
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from delivery_experiment import EXPECTED_PRESETS, digest  # noqa: E402
from delivery_experiment_runner import (  # noqa: E402
    REPO,
    RunnerError,
    _reference_key,
    analyze_execution,
    atomic_json,
    create_execution_plan,
    file_sha256,
    run_execution_plan,
    validate_execution_plan,
)
from delivery_statistics import paired_bootstrap_delta  # noqa: E402


DEFAULT_CONTRACT = REPO / "config/delivery-prompt-remediation-contract.json"
SCHEMA_VERSION = 2
LEGACY_SCHEMA_VERSION = 1
RESULT_VOCABULARY = (
    "automatic_acoustic_improvement",
    "no_measured_improvement",
    "regression",
    "inconclusive",
    "abstained_out_of_distribution",
)
STAGE_ORDER = ("screen", "script-interaction", "powered", "variant-confirmation")
FEATURE_KEYS = {
    "global": {
        "pitch_shift_semitones", "arousal_score", "rate_delta_hz",
        "voice_tension_score", "voice_breathiness_score", "pause_ratio_delta",
    },
    "temporal": {
        "cadenceAccelerationHz", "tensionPersistence", "contourAbruptnessHz",
        "tremorPersistenceHz", "maximumLocalRiseHz", "onsetToPeakPitchHz",
        "normalizedPeakPosition", "peakToEndPitchHz", "phraseFinalPitchSlopeHz",
    },
}


class RemediationError(ValueError):
    """The autonomous remediation evidence is incomplete or inconsistent."""


def _load(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RemediationError(f"cannot load {path}: {error}") from error
    if not isinstance(value, dict):
        raise RemediationError(f"{path} must contain a JSON object")
    return value


def _normalized_text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RemediationError(f"{label} must be a non-empty string")
    normalized = " ".join(value.split())
    if normalized != value:
        raise RemediationError(f"{label} must already be whitespace-normalized")
    return normalized


def _validate_expectations(rows: Any, label: str, layer: str) -> None:
    if not isinstance(rows, list) or not rows:
        raise RemediationError(f"{label} must be a non-empty expectation array")
    observed: set[str] = set()
    for index, row in enumerate(rows):
        if not isinstance(row, dict) or set(row) != {"feature", "direction", "weight"}:
            raise RemediationError(f"{label}[{index}] has an invalid shape")
        feature = row["feature"]
        if feature not in FEATURE_KEYS[layer] or feature in observed:
            raise RemediationError(f"{label} has an unknown or duplicate feature {feature!r}")
        observed.add(feature)
        if row["direction"] not in (-1, 1):
            raise RemediationError(f"{label}.{feature} direction must be -1 or 1")
        weight = row["weight"]
        if isinstance(weight, bool) or not isinstance(weight, (int, float)) or weight <= 0:
            raise RemediationError(f"{label}.{feature} weight must be positive")


def _finite_number(value: Any, label: str, *, minimum: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise RemediationError(f"{label} must be a finite number")
    normalized = float(value)
    if minimum is not None and normalized < minimum:
        raise RemediationError(f"{label} must be at least {minimum}")
    return normalized


def _validate_scoring(contract: dict[str, Any], candidates: list[dict[str, Any]]) -> None:
    scoring = contract.get("scoring")
    if not isinstance(scoring, dict) or set(scoring) != {"algorithm", "calibration", "separation", "legacyRecomposition"}:
        raise RemediationError("scoring block has an invalid shape")
    if scoring.get("algorithm") != "bounded-magnitude-v2":
        raise RemediationError("scoring algorithm must remain bounded-magnitude-v2")
    calibration = scoring.get("calibration")
    required_calibration = {
        "kind", "manifestDigest", "rowCount", "rowsPerPreset", "quantileMethod",
        "minimumAbsoluteQuantile", "fullCreditAbsoluteQuantile",
        "minimumFloorFractionOfFullCredit", "overdriveMultiplierFromObservedMaximum",
        "humanPerceptualAuthority", "bands",
    }
    if not isinstance(calibration, dict) or set(calibration) != required_calibration:
        raise RemediationError("scoring calibration has an invalid shape")
    if calibration.get("kind") != "independent-pre-candidate-acoustic-cohort":
        raise RemediationError("scoring calibration must remain independent of candidate output")
    if not isinstance(calibration.get("manifestDigest"), str) or len(calibration["manifestDigest"]) != 64:
        raise RemediationError("scoring calibration manifest digest is invalid")
    if calibration.get("rowCount") != 64 or calibration.get("rowsPerPreset") != 8:
        raise RemediationError("scoring calibration cohort cardinality drifted")
    if calibration.get("quantileMethod") != "linear-r7":
        raise RemediationError("scoring calibration quantile method drifted")
    if calibration.get("minimumAbsoluteQuantile") != 0.25 or calibration.get("fullCreditAbsoluteQuantile") != 0.5:
        raise RemediationError("scoring calibration quantiles drifted")
    if calibration.get("minimumFloorFractionOfFullCredit") != 0.1:
        raise RemediationError("scoring calibration minimum floor drifted")
    if calibration.get("overdriveMultiplierFromObservedMaximum") != 2.0:
        raise RemediationError("scoring calibration overdrive multiplier drifted")
    if calibration.get("humanPerceptualAuthority") is not False:
        raise RemediationError("acoustic magnitude calibration cannot gain perceptual authority")
    bands = calibration.get("bands")
    if not isinstance(bands, dict):
        raise RemediationError("scoring calibration bands are missing")
    expected_by_preset: dict[str, dict[str, set[str]]] = {}
    for candidate in candidates:
        target = candidate["targetPreset"]
        target_layers = expected_by_preset.setdefault(target, {"global": set(), "temporal": set()})
        target_layers["global"].update(row["feature"] for row in candidate["expectedGlobal"])
        target_layers["temporal"].update(row["feature"] for row in candidate["expectedTemporal"])
    if set(bands) != set(expected_by_preset):
        raise RemediationError("scoring calibration presets do not match candidate targets")
    for preset, layers in expected_by_preset.items():
        preset_bands = bands.get(preset)
        if not isinstance(preset_bands, dict) or set(preset_bands) != {"global", "temporal"}:
            raise RemediationError(f"{preset}: scoring calibration layers are invalid")
        for layer, expected_features in layers.items():
            feature_bands = preset_bands[layer]
            if not isinstance(feature_bands, dict) or set(feature_bands) != expected_features:
                raise RemediationError(f"{preset}.{layer}: scoring calibration features drifted")
            for feature, band in feature_bands.items():
                if not isinstance(band, dict) or set(band) != {"minimum", "fullCredit", "overdrive"}:
                    raise RemediationError(f"{preset}.{layer}.{feature}: magnitude band shape is invalid")
                minimum = _finite_number(band["minimum"], f"{preset}.{layer}.{feature}.minimum", minimum=0.0)
                full_credit = _finite_number(band["fullCredit"], f"{preset}.{layer}.{feature}.fullCredit", minimum=0.0)
                overdrive = _finite_number(band["overdrive"], f"{preset}.{layer}.{feature}.overdrive", minimum=0.0)
                if not 0 < minimum < full_credit < overdrive:
                    raise RemediationError(f"{preset}.{layer}.{feature}: require 0 < minimum < fullCredit < overdrive")
    separation = scoring.get("separation")
    if not isinstance(separation, dict) or set(separation) != {
        "algorithm", "requireStrictPositiveCandidateMedianMargin", "maximumMedianMarginRegression",
        "maximumWrongOrderRateRegression",
    }:
        raise RemediationError("signed preset-separation policy has an invalid shape")
    if separation.get("algorithm") != "signed-target-minus-competitor-v2":
        raise RemediationError("preset separation must preserve target-versus-competitor ordering")
    if separation.get("requireStrictPositiveCandidateMedianMargin") is not True:
        raise RemediationError("preset separation must require a strictly positive target margin")
    _finite_number(separation.get("maximumMedianMarginRegression"), "maximumMedianMarginRegression", minimum=0.0)
    _finite_number(separation.get("maximumWrongOrderRateRegression"), "maximumWrongOrderRateRegression", minimum=0.0)
    legacy = scoring.get("legacyRecomposition")
    if not isinstance(legacy, dict) or set(legacy) != {
        "schemaVersion", "contractDigest", "composerSHA256", "decisionFilename",
    }:
        raise RemediationError("legacy recomposition identity has an invalid shape")
    if legacy.get("schemaVersion") != LEGACY_SCHEMA_VERSION:
        raise RemediationError("legacy recomposition schema version drifted")
    for field in ("contractDigest", "composerSHA256"):
        if not isinstance(legacy.get(field), str) or len(legacy[field]) != 64:
            raise RemediationError(f"legacy recomposition {field} is invalid")
    if legacy.get("decisionFilename") != "automatic-decision-v2-recomposed.json":
        raise RemediationError("legacy recomposition output filename drifted")


def validate_contract(contract: dict[str, Any]) -> dict[str, Any]:
    if contract.get("schemaVersion") != SCHEMA_VERSION:
        raise RemediationError(f"contract schemaVersion must be {SCHEMA_VERSION}")
    if contract.get("status") != "active-experimental":
        raise RemediationError("contract must remain active-experimental")
    if tuple(contract.get("resultVocabulary", ())) != RESULT_VOCABULARY:
        raise RemediationError("result vocabulary drifted")
    if contract.get("baselineArm") != "current":
        raise RemediationError("baseline arm must remain current")
    stable = contract.get("stableControls")
    if stable != ["neutral", "sad", "calm", "whisper"]:
        raise RemediationError("stable controls drifted")
    candidates = contract.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        raise RemediationError("contract needs prompt candidates")
    ids: list[str] = []
    for row in candidates:
        if not isinstance(row, dict):
            raise RemediationError("candidate rows must be objects")
        candidate_id = _normalized_text(row.get("id"), "candidate.id")
        if candidate_id in ids:
            raise RemediationError(f"duplicate candidate id {candidate_id}")
        ids.append(candidate_id)
        target = row.get("targetPreset")
        competitor = row.get("competingPreset")
        if target not in EXPECTED_PRESETS or competitor not in EXPECTED_PRESETS or target == competitor:
            raise RemediationError(f"{candidate_id}: invalid target/competing preset")
        if target in stable:
            raise RemediationError(f"{candidate_id}: stable control cannot be a target")
        instruction = _normalized_text(row.get("instruction"), f"{candidate_id}.instruction")
        expected_digest = hashlib.sha256(instruction.encode("utf-8")).hexdigest()
        if row.get("instructionSHA256") != expected_digest:
            raise RemediationError(f"{candidate_id}: instruction digest mismatch")
        _validate_expectations(row.get("expectedGlobal"), f"{candidate_id}.expectedGlobal", "global")
        _validate_expectations(row.get("expectedTemporal"), f"{candidate_id}.expectedTemporal", "temporal")
    priority = contract.get("candidatePriority")
    if not isinstance(priority, list) or len(priority) != len(set(priority)) or set(priority) != set(ids):
        raise RemediationError("candidate priority must cover every candidate exactly once")
    _validate_scoring(contract, candidates)

    stages = contract.get("stages")
    if not isinstance(stages, dict) or tuple(stages) != STAGE_ORDER:
        raise RemediationError(f"stages must be exactly {STAGE_ORDER}")
    all_seed_sets: list[set[int]] = []
    for name, stage in stages.items():
        if not isinstance(stage, dict):
            raise RemediationError(f"{name}: stage must be an object")
        split = stage.get("split")
        if split not in {"development", "confirmation"}:
            raise RemediationError(f"{name}: invalid split")
        if (name == "variant-confirmation") != (split == "confirmation"):
            raise RemediationError(f"{name}: confirmation split assignment drifted")
        seeds = stage.get("seeds")
        if not isinstance(seeds, list) or not seeds or len(seeds) != len(set(seeds)):
            raise RemediationError(f"{name}: seeds must be non-empty and unique")
        bounds = (32000000, 32999999) if split == "development" else (33000000, 33999999)
        if any(isinstance(seed, bool) or not isinstance(seed, int) or not bounds[0] <= seed <= bounds[1] for seed in seeds):
            raise RemediationError(f"{name}: seed falls outside the {split} partition")
        seed_set = set(seeds)
        if any(seed_set & previous for previous in all_seed_sets):
            raise RemediationError("stage seed partitions overlap")
        all_seed_sets.append(seed_set)
        if name in {"powered", "variant-confirmation"} and not 8 <= len(seeds) <= 20:
            raise RemediationError(f"{name}: confirmatory seed count must be 8...20")
        cells = stage.get("cells")
        if not isinstance(cells, list) or not cells:
            raise RemediationError(f"{name}: cells are missing")
        cell_keys = [(row.get("speakerID"), row.get("outputLanguage")) for row in cells]
        if len(cell_keys) != len(set(cell_keys)) or any(not all(isinstance(value, str) and value for value in key) for key in cell_keys):
            raise RemediationError(f"{name}: cells are invalid or duplicated")
        if stage.get("sampling") != "official-official":
            raise RemediationError(f"{name}: sampling must stay official-official")
        variants = stage.get("variants")
        if not isinstance(variants, list) or not variants or set(variants) - {"speed", "quality"}:
            raise RemediationError(f"{name}: variants are invalid")
        if name == "variant-confirmation" and variants != ["speed", "quality"]:
            raise RemediationError("variant confirmation must keep Speed and Quality separate")
        for threshold in (
            "minimumCompletionRate", "minimumScoreImprovement",
            "minimumAdherenceImprovement",
        ):
            value = stage.get(threshold)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= 1:
                raise RemediationError(f"{name}.{threshold} must be in [0, 1]")
        if not isinstance(stage.get("requirePositiveBootstrapLower"), bool):
            raise RemediationError(f"{name}: bootstrap policy must be boolean")
    acceptance = contract.get("acceptance")
    if not isinstance(acceptance, dict):
        raise RemediationError("acceptance block is missing")
    if acceptance.get("allowAutomaticSemanticPromotion") is not False:
        raise RemediationError("automatic semantic promotion must remain disabled")
    if acceptance.get("allowAutomaticPublication") is not False:
        raise RemediationError("automatic publication must remain disabled")
    return contract


def candidate_by_id(contract: dict[str, Any], candidate_id: str) -> dict[str, Any]:
    validate_contract(contract)
    for row in contract["candidates"]:
        if row["id"] == candidate_id:
            return row
    raise RemediationError(f"unknown candidate {candidate_id!r}")


def _quantile_r7(values: list[float], probability: float) -> float:
    if not values:
        raise RemediationError("cannot calculate a quantile from an empty sample")
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (position - lower) * (ordered[upper] - ordered[lower])


def _derive_band(values: list[float], calibration: dict[str, Any]) -> dict[str, float]:
    absolute = [abs(value) for value in values]
    full_credit = _quantile_r7(absolute, calibration["fullCreditAbsoluteQuantile"])
    minimum = max(
        _quantile_r7(absolute, calibration["minimumAbsoluteQuantile"]),
        full_credit * calibration["minimumFloorFractionOfFullCredit"],
    )
    overdrive = max(absolute) * calibration["overdriveMultiplierFromObservedMaximum"]
    if not 0 < minimum < full_credit < overdrive:
        raise RemediationError("calibration sample cannot produce an ordered positive magnitude band")
    return {
        "minimum": round(minimum, 6),
        "fullCredit": round(full_credit, 6),
        "overdrive": round(overdrive, 6),
    }


def verify_calibration_bands(acoustic: dict[str, Any], contract: dict[str, Any]) -> dict[str, Any]:
    contract = validate_contract(contract)
    calibration = contract["scoring"]["calibration"]
    if acoustic.get("manifestDigest") != calibration["manifestDigest"]:
        raise RemediationError("calibration acoustic manifest digest drifted")
    rows = acoustic.get("rows")
    if not isinstance(rows, list) or len(rows) != calibration["rowCount"]:
        raise RemediationError("calibration acoustic row count drifted")
    expected_by_preset: dict[str, dict[str, set[str]]] = {}
    for candidate in contract["candidates"]:
        layers = expected_by_preset.setdefault(candidate["targetPreset"], {"global": set(), "temporal": set()})
        layers["global"].update(row["feature"] for row in candidate["expectedGlobal"])
        layers["temporal"].update(row["feature"] for row in candidate["expectedTemporal"])
    derived: dict[str, Any] = {}
    for preset, layers in expected_by_preset.items():
        preset_rows = [row for row in rows if row.get("preset") == preset]
        if len(preset_rows) != calibration["rowsPerPreset"]:
            raise RemediationError(f"{preset}: calibration row count drifted")
        derived[preset] = {"global": {}, "temporal": {}}
        for layer, features in layers.items():
            for feature in sorted(features):
                values: list[float] = []
                for row in preset_rows:
                    source = (
                        row.get("derivedFeatures", {}) if layer == "global"
                        else row.get("temporalDeltaV1", {}).get("derivedContours", {})
                    )
                    value = source.get(feature)
                    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
                        raise RemediationError(f"{preset}.{layer}.{feature}: calibration feature is missing or nonfinite")
                    values.append(float(value))
                derived[preset][layer][feature] = _derive_band(values, calibration)
    if derived != calibration["bands"]:
        raise RemediationError("pinned magnitude bands differ from the source-bound calibration cohort")
    return {
        "status": "PASS",
        "manifestDigest": acoustic["manifestDigest"],
        "rowCount": len(rows),
        "bandsDigest": digest(derived),
        "humanPerceptualAuthority": False,
    }


def _row_identity(row: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value for key, value in row.items() if key != "takeID"
    }


def _reseal_plan(plan: dict[str, Any]) -> dict[str, Any]:
    for row in plan["rows"]:
        row["takeID"] = digest(_row_identity(row))[:24]
    plan_body = {
        key: value for key, value in plan.items()
        if key not in {"planDigest", "executionIdentity", "executionPlanDigest"}
    }
    plan["planDigest"] = digest(plan_body)
    plan.pop("executionPlanDigest", None)
    plan["executionPlanDigest"] = digest(plan)
    return plan


def create_candidate_plan(
    *, binary: Path, contract: dict[str, Any], candidate_id: str,
    stage_name: str, variant: str, baseline: bool, data_dir: Path | None = None,
) -> dict[str, Any]:
    contract = validate_contract(contract)
    candidate = candidate_by_id(contract, candidate_id)
    try:
        stage = contract["stages"][stage_name]
    except KeyError as error:
        raise RemediationError(f"unknown stage {stage_name!r}") from error
    if variant not in stage["variants"]:
        raise RemediationError(f"{variant} is not registered for stage {stage_name}")
    plan = create_execution_plan(
        binary=binary, data_dir=data_dir, split=stage["split"], arm="current",
        instruction_language="english", variant=variant,
        sampling_combination=stage["sampling"], seeds=list(stage["seeds"]),
    )
    cells = {(row["speakerID"], row["outputLanguage"]) for row in stage["cells"]}
    presets = {candidate["targetPreset"], candidate["competingPreset"]}
    lengths = set(stage["lengths"])
    conditions = set(stage["semanticConditions"])
    plan["rows"] = [
        row for row in plan["rows"]
        if (row["speakerID"], row["outputLanguage"]) in cells
        and row["preset"] in presets
        and row["script"]["length"] in lengths
        and row["script"]["semanticCondition"] in conditions
    ]
    if not plan["rows"]:
        raise RemediationError("contract selection produced no execution rows")
    if not baseline:
        for row in plan["rows"]:
            if row["preset"] != candidate["targetPreset"]:
                continue
            row["instruction"] = {
                "compilerVersion": 1,
                "preset": candidate["targetPreset"],
                "arm": candidate_id,
                "instructionLanguage": "english",
                "text": candidate["instruction"],
                "wordCount": len(candidate["instruction"].split()),
                "sha256": candidate["instructionSHA256"],
                "dimensions": row["instruction"]["dimensions"],
            }
    plan["arm"] = "current" if baseline else candidate_id
    plan["remediation"] = {
        "schemaVersion": SCHEMA_VERSION,
        "candidateID": candidate_id,
        "stage": stage_name,
        "variant": variant,
        "role": "baseline" if baseline else "candidate",
        "targetPreset": candidate["targetPreset"],
        "competingPreset": candidate["competingPreset"],
        "contractDigest": digest(contract),
        "semanticAuthority": False,
        "publicationAuthority": False,
    }
    plan["screeningSelection"] = {
        "label": f"{candidate_id}:{stage_name}:{variant}",
        "scope": f"contract-{stage_name}",
        "cells": stage["cells"],
        "presets": sorted(presets),
        "lengths": stage["lengths"],
        "semanticConditions": stage["semanticConditions"],
        "promotionAuthority": False,
    }
    plan["executionIdentity"]["remediationComposerSHA256"] = file_sha256(Path(__file__))
    plan["executionIdentity"]["remediationContractDigest"] = digest(contract)
    return _reseal_plan(plan)


def validate_candidate_plan(
    plan: dict[str, Any], binary: Path, contract: dict[str, Any], *,
    candidate_id: str, stage_name: str, variant: str, role: str,
) -> dict[str, Any]:
    validate_execution_plan(plan, binary)
    candidate = candidate_by_id(contract, candidate_id)
    remediation = plan.get("remediation")
    expected = {
        "schemaVersion": SCHEMA_VERSION,
        "candidateID": candidate_id,
        "stage": stage_name,
        "variant": variant,
        "role": role,
        "targetPreset": candidate["targetPreset"],
        "competingPreset": candidate["competingPreset"],
        "contractDigest": digest(contract),
        "semanticAuthority": False,
        "publicationAuthority": False,
    }
    if remediation != expected:
        raise RemediationError("candidate plan remediation identity drifted")
    if plan["executionIdentity"].get("remediationComposerSHA256") != file_sha256(Path(__file__)):
        raise RemediationError("candidate plan composer source drifted")
    for row in plan["rows"]:
        if row["preset"] == candidate["targetPreset"] and role == "candidate":
            if row["instruction"].get("sha256") != candidate["instructionSHA256"]:
                raise RemediationError("candidate plan instruction digest drifted")
        elif row["instruction"].get("arm") != "current":
            raise RemediationError("baseline or competing-preset instruction is not current")
    return plan


def seed_reference_controls(
    *, baseline_run: Path, candidate_plan: dict[str, Any], candidate_run: Path,
    binary: Path, contract: dict[str, Any], candidate_id: str,
    stage_name: str, variant: str,
) -> dict[str, Any]:
    validate_candidate_plan(
        candidate_plan, binary, contract, candidate_id=candidate_id,
        stage_name=stage_name, variant=variant, role="candidate",
    )
    baseline_plan = _load(baseline_run / "execution-plan.json")
    validate_candidate_plan(
        baseline_plan, binary, contract, candidate_id=candidate_id,
        stage_name=stage_name, variant=variant, role="baseline",
    )
    baseline_state = _load(baseline_run / "execution-state.json")
    if baseline_state.get("executionPlanDigest") != baseline_plan["executionPlanDigest"]:
        raise RemediationError("baseline state identity drifted")
    candidate_run.mkdir(parents=True, exist_ok=True)
    audio_dir = candidate_run / "audio"
    audio_dir.mkdir(exist_ok=True)
    references: dict[str, Any] = {}
    for row in candidate_plan["rows"]:
        key = _reference_key(row)
        source = baseline_state.get("references", {}).get(key)
        if not isinstance(source, dict) or source.get("status") != "complete":
            continue
        relative = source.get("audio")
        if not isinstance(relative, str) or Path(relative).is_absolute():
            raise RemediationError("baseline reference path is invalid")
        source_path = baseline_run / relative
        if not source_path.is_file() or file_sha256(source_path) != source.get("audioSHA256"):
            raise RemediationError("baseline reference audio digest mismatch")
        destination = audio_dir / source_path.name
        if destination.exists():
            if file_sha256(destination) != source["audioSHA256"]:
                raise RemediationError("candidate reference destination drifted")
        else:
            os.link(source_path, destination)
        references[key] = {**source, "audio": str(Path("audio") / destination.name)}
    state = {
        "schemaVersion": 1,
        "executionPlanDigest": candidate_plan["executionPlanDigest"],
        "binarySHA256": candidate_plan["executionIdentity"]["binarySHA256"],
        "references": references,
        "takes": {},
    }
    atomic_json(candidate_run / "execution-plan.json", candidate_plan)
    atomic_json(candidate_run / "execution-state.json", state)
    return {"reusedReferenceCount": len(references), "candidateRowCount": len(candidate_plan["rows"])}


def _comparison_key(row: dict[str, Any]) -> str:
    return digest({
        "speakerID": row["speakerID"], "outputLanguage": row["outputLanguage"],
        "preset": row["preset"], "scriptDigest": row["script"]["sha256"],
        "seed": row["seed"], "variant": row["variant"],
    })


def _analysis_index(run_dir: Path, plan: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    state = _load(run_dir / "execution-state.json")
    acoustic = _load(run_dir / "acoustic-layer.json")
    if state.get("executionPlanDigest") != plan["executionPlanDigest"]:
        raise RemediationError("execution state and plan identities differ")
    if acoustic.get("manifestDigest") != plan["executionPlanDigest"]:
        raise RemediationError("acoustic layer and plan identities differ")
    row_by_take = {row["takeID"]: row for row in plan["rows"]}
    indexed: dict[str, dict[str, Any]] = {}
    for result in acoustic.get("rows", []):
        source = row_by_take.get(result.get("takeID"))
        if source is None:
            raise RemediationError("acoustic layer contains an unknown take")
        indexed[_comparison_key(source)] = {"plan": source, "analysis": result}
    return indexed, state


def _bounded_magnitude_credit(signed_movement: float, band: dict[str, Any]) -> tuple[float, str]:
    minimum = float(band["minimum"])
    full_credit = float(band["fullCredit"])
    overdrive = float(band["overdrive"])
    if signed_movement <= 0:
        return 0.0, "wrong-direction-or-zero"
    if signed_movement < minimum:
        return 0.0, "below-calibrated-minimum"
    if signed_movement < full_credit:
        return (signed_movement - minimum) / (full_credit - minimum), "partial-credit"
    if signed_movement <= overdrive:
        return 1.0, "full-credit"
    credit = max(0.0, 1.0 - ((signed_movement - overdrive) / overdrive))
    return credit, "overdrive-penalty"


def _feature_score(
    analysis: dict[str, Any], candidate: dict[str, Any], scoring: dict[str, Any],
) -> tuple[float, list[str], list[dict[str, Any]]]:
    total = 0.0
    earned = 0.0
    missing: list[str] = []
    feature_rows: list[dict[str, Any]] = []
    global_features = analysis.get("derivedFeatures", {})
    temporal_features = analysis.get("temporalDeltaV1", {}).get("derivedContours", {})
    preset_bands = scoring["calibration"]["bands"][candidate["targetPreset"]]
    for layer, source, expectations in (
        ("global", global_features, candidate["expectedGlobal"]),
        ("temporal", temporal_features, candidate["expectedTemporal"]),
    ):
        for expectation in expectations:
            feature = expectation["feature"]
            weight = float(expectation["weight"])
            total += weight
            value = source.get(feature)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
                missing.append(f"{layer}:{feature}")
                feature_rows.append({
                    "layer": layer, "feature": feature, "weight": weight,
                    "available": False, "credit": 0.0, "classification": "missing-or-nonfinite",
                })
                continue
            signed_movement = expectation["direction"] * float(value)
            band = preset_bands[layer][feature]
            credit, classification = _bounded_magnitude_credit(signed_movement, band)
            earned += weight * credit
            feature_rows.append({
                "layer": layer, "feature": feature, "weight": weight,
                "available": True, "rawValue": float(value),
                "signedMovement": signed_movement, "magnitudeBand": band,
                "credit": credit, "classification": classification,
            })
    return earned / total if total else 0.0, missing, feature_rows


def _median(values: list[float]) -> float | None:
    return statistics.median(values) if values else None


def validate_legacy_candidate_plan(
    plan: dict[str, Any], binary: Path, contract: dict[str, Any], *,
    candidate_id: str, stage_name: str, variant: str, role: str,
) -> dict[str, Any]:
    validate_execution_plan(plan, binary)
    contract = validate_contract(contract)
    candidate = candidate_by_id(contract, candidate_id)
    legacy = contract["scoring"]["legacyRecomposition"]
    expected = {
        "schemaVersion": legacy["schemaVersion"],
        "candidateID": candidate_id,
        "stage": stage_name,
        "variant": variant,
        "role": role,
        "targetPreset": candidate["targetPreset"],
        "competingPreset": candidate["competingPreset"],
        "contractDigest": legacy["contractDigest"],
        "semanticAuthority": False,
        "publicationAuthority": False,
    }
    if plan.get("remediation") != expected:
        raise RemediationError("legacy candidate plan remediation identity drifted")
    identity = plan.get("executionIdentity", {})
    if identity.get("remediationComposerSHA256") != legacy["composerSHA256"]:
        raise RemediationError("legacy candidate plan composer identity drifted")
    if identity.get("remediationContractDigest") != legacy["contractDigest"]:
        raise RemediationError("legacy candidate plan contract identity drifted")
    for row in plan["rows"]:
        if row["preset"] == candidate["targetPreset"] and role == "candidate":
            if row["instruction"].get("sha256") != candidate["instructionSHA256"]:
                raise RemediationError("legacy candidate instruction digest drifted")
        elif row["instruction"].get("arm") != "current":
            raise RemediationError("legacy baseline or competing-preset instruction is not current")
    return plan


def decide(
    *, baseline_run: Path, candidate_run: Path, binary: Path,
    contract: dict[str, Any], candidate_id: str, stage_name: str, variant: str,
    legacy_recomposition: bool = False,
) -> dict[str, Any]:
    contract = validate_contract(contract)
    candidate = candidate_by_id(contract, candidate_id)
    stage = contract["stages"][stage_name]
    plan_validator = validate_legacy_candidate_plan if legacy_recomposition else validate_candidate_plan
    baseline_plan = plan_validator(
        _load(baseline_run / "execution-plan.json"), binary, contract,
        candidate_id=candidate_id, stage_name=stage_name, variant=variant, role="baseline",
    )
    candidate_plan = plan_validator(
        _load(candidate_run / "execution-plan.json"), binary, contract,
        candidate_id=candidate_id, stage_name=stage_name, variant=variant, role="candidate",
    )
    baseline_index, baseline_state = _analysis_index(baseline_run, baseline_plan)
    candidate_index, candidate_state = _analysis_index(candidate_run, candidate_plan)
    baseline_keys = {_comparison_key(row) for row in baseline_plan["rows"]}
    candidate_keys = {_comparison_key(row) for row in candidate_plan["rows"]}
    if baseline_keys != candidate_keys:
        raise RemediationError("baseline and candidate comparison cells differ")
    target_keys = sorted(
        _comparison_key(row) for row in baseline_plan["rows"]
        if row["preset"] == candidate["targetPreset"]
    )
    baseline_row_by_key = {_comparison_key(row): row for row in baseline_plan["rows"]}
    candidate_row_by_key = {_comparison_key(row): row for row in candidate_plan["rows"]}
    baseline_scores: list[float] = []
    candidate_scores: list[float] = []
    baseline_adherence: list[float] = []
    candidate_adherence: list[float] = []
    missing_features: set[str] = set()
    missing_analysis_pairs = 0
    pair_rows: list[dict[str, Any]] = []
    for key in target_keys:
        baseline_entry = baseline_index.get(key)
        candidate_entry = candidate_index.get(key)
        if baseline_entry:
            baseline_score, baseline_missing, baseline_feature_rows = _feature_score(
                baseline_entry["analysis"], candidate, contract["scoring"]
            )
        else:
            baseline_score, baseline_missing, baseline_feature_rows = 0.0, [], []
        if candidate_entry:
            candidate_score, candidate_missing, candidate_feature_rows = _feature_score(
                candidate_entry["analysis"], candidate, contract["scoring"]
            )
        else:
            candidate_score, candidate_missing, candidate_feature_rows = 0.0, [], []
        if baseline_entry is None or candidate_entry is None:
            missing_analysis_pairs += 1
        baseline_take = baseline_state.get("takes", {}).get(baseline_row_by_key[key]["takeID"], {})
        candidate_take = candidate_state.get("takes", {}).get(candidate_row_by_key[key]["takeID"], {})
        if baseline_entry is None and baseline_take.get("status") == "complete":
            missing_features.add("baseline:missing-analysis-for-complete-take")
        if candidate_entry is None and candidate_take.get("status") == "complete":
            missing_features.add("candidate:missing-analysis-for-complete-take")
        missing_features.update(baseline_missing)
        missing_features.update(candidate_missing)
        baseline_pass = bool(
            baseline_entry and baseline_entry["analysis"].get("deliveryVerdict", {}).get("passed") is True
        )
        candidate_pass = bool(
            candidate_entry and candidate_entry["analysis"].get("deliveryVerdict", {}).get("passed") is True
        )
        baseline_scores.append(baseline_score)
        candidate_scores.append(candidate_score)
        baseline_adherence.append(float(baseline_pass))
        candidate_adherence.append(float(candidate_pass))
        source = (candidate_entry or baseline_entry or {}).get("plan", {})
        pair_rows.append({
            "comparisonKey": key,
            "speakerID": source.get("speakerID"),
            "outputLanguage": source.get("outputLanguage"),
            "scriptID": source.get("script", {}).get("scriptID"),
            "seed": source.get("seed"),
            "baselineScore": baseline_score,
            "candidateScore": candidate_score,
            "baselineAdherence": baseline_pass,
            "candidateAdherence": candidate_pass,
            "baselineAnalysisAvailable": baseline_entry is not None,
            "candidateAnalysisAvailable": candidate_entry is not None,
            "baselineFeatureRows": baseline_feature_rows,
            "candidateFeatureRows": candidate_feature_rows,
        })
    bootstrap = paired_bootstrap_delta(
        candidate_scores, baseline_scores,
        confidence=contract["acceptance"]["pairedBootstrapConfidence"],
        resamples=contract["acceptance"]["pairedBootstrapResamples"],
        seed=contract["acceptance"]["pairedBootstrapSeed"],
    )
    adherence_bootstrap = paired_bootstrap_delta(
        candidate_adherence, baseline_adherence,
        confidence=contract["acceptance"]["pairedBootstrapConfidence"],
        resamples=contract["acceptance"]["pairedBootstrapResamples"],
        seed=contract["acceptance"]["pairedBootstrapSeed"] + 1,
    )
    score_delta = statistics.mean(candidate_scores) - statistics.mean(baseline_scores)
    adherence_delta = statistics.mean(candidate_adherence) - statistics.mean(baseline_adherence)
    candidate_complete = sum(
        row.get("status") == "complete" for row in candidate_state.get("takes", {}).values()
    )
    completion_rate = candidate_complete / len(candidate_plan["rows"])
    baseline_failures = len(baseline_plan["rows"]) - sum(
        row.get("status") == "complete" for row in baseline_state.get("takes", {}).values()
    )
    candidate_failures = len(candidate_plan["rows"]) - candidate_complete
    new_hard_failures = max(0, candidate_failures - baseline_failures)

    subgroup_regressions: list[dict[str, Any]] = []
    if stage_name in {"powered", "variant-confirmation"}:
        for field in ("speakerID", "outputLanguage", "scriptID"):
            values = sorted({str(row[field]) for row in pair_rows})
            for value in values:
                subset = [row for row in pair_rows if str(row[field]) == value]
                delta = statistics.mean(row["candidateScore"] - row["baselineScore"] for row in subset)
                if delta < 0:
                    subgroup_regressions.append({"field": field, "value": value, "meanScoreDelta": delta})

    # Competing-preset rows are scored against the target expectations. Keep
    # the sign: a positive margin means the target ranks above the competitor.
    def margins(index: dict[str, dict[str, Any]], plan: dict[str, Any]) -> dict[str, float]:
        grouped: dict[str, dict[str, float]] = {}
        for row in plan["rows"]:
            key = _comparison_key(row)
            entry = index.get(key)
            if entry is None:
                continue
            score, missing, _feature_rows = _feature_score(
                entry["analysis"], candidate, contract["scoring"]
            )
            missing_features.update(missing)
            group = digest({
                "speakerID": row["speakerID"], "outputLanguage": row["outputLanguage"],
                "scriptDigest": row["script"]["sha256"], "seed": row["seed"],
                "variant": row["variant"],
            })
            grouped.setdefault(group, {})[row["preset"]] = score
        return {
            group: values[candidate["targetPreset"]] - values[candidate["competingPreset"]]
            for group, values in grouped.items()
            if candidate["targetPreset"] in values and candidate["competingPreset"] in values
        }

    baseline_margin_map = margins(baseline_index, baseline_plan)
    candidate_margin_map = margins(candidate_index, candidate_plan)
    common_margin_keys = sorted(set(baseline_margin_map) & set(candidate_margin_map))
    baseline_margins = [baseline_margin_map[key] for key in common_margin_keys]
    candidate_margins = [candidate_margin_map[key] for key in common_margin_keys]
    baseline_margin_median = _median(baseline_margins)
    candidate_margin_median = _median(candidate_margins)
    margin_delta = (
        candidate_margin_median - baseline_margin_median
        if candidate_margin_median is not None and baseline_margin_median is not None else None
    )
    baseline_wrong_order_count = sum(value < 0 for value in baseline_margins)
    candidate_wrong_order_count = sum(value < 0 for value in candidate_margins)
    baseline_wrong_order_rate = (
        baseline_wrong_order_count / len(baseline_margins) if baseline_margins else None
    )
    candidate_wrong_order_rate = (
        candidate_wrong_order_count / len(candidate_margins) if candidate_margins else None
    )
    wrong_order_rate_delta = (
        candidate_wrong_order_rate - baseline_wrong_order_rate
        if candidate_wrong_order_rate is not None and baseline_wrong_order_rate is not None else None
    )
    separation_policy = contract["scoring"]["separation"]
    margin_regression = (
        margin_delta is not None
        and margin_delta < -float(separation_policy["maximumMedianMarginRegression"])
    )
    wrong_order_regression = (
        wrong_order_rate_delta is not None
        and wrong_order_rate_delta > float(separation_policy["maximumWrongOrderRateRegression"])
    )
    target_order_failure = (
        candidate_margin_median is not None
        and candidate_margin_median <= 0
    )

    failures: list[str] = []
    if missing_features:
        failures.append("missing-or-nonfinite-acoustic-feature")
    if completion_rate < stage["minimumCompletionRate"]:
        failures.append("completion-rate-below-stage-floor")
    if new_hard_failures > contract["acceptance"]["maximumNewHardAudioQCFailures"]:
        failures.append("new-hard-audio-qc-or-generation-failure")
    if score_delta < stage["minimumScoreImprovement"]:
        failures.append("preset-specific-score-improvement-below-floor")
    if adherence_delta < stage["minimumAdherenceImprovement"]:
        failures.append("delivery-adherence-improvement-below-floor")
    if stage["requirePositiveBootstrapLower"]:
        if bootstrap is None or bootstrap["lower"] <= 0:
            failures.append("paired-score-bootstrap-lower-not-positive")
        if adherence_bootstrap is None or adherence_bootstrap["lower"] <= 0:
            failures.append("paired-adherence-bootstrap-lower-not-positive")
    if subgroup_regressions:
        failures.append("speaker-language-or-script-subgroup-regression")
    if margin_delta is None:
        failures.append("competing-preset-separation-unavailable")
    if target_order_failure:
        failures.append("target-preset-does-not-rank-above-competitor")
    if margin_regression:
        failures.append("competing-preset-signed-margin-regression")
    if wrong_order_regression:
        failures.append("competing-preset-wrong-order-rate-regression")

    if missing_features or completion_rate < stage["minimumCompletionRate"]:
        result = "abstained_out_of_distribution"
    elif new_hard_failures or subgroup_regressions or target_order_failure or margin_regression or wrong_order_regression:
        result = "regression"
    elif not failures:
        result = "automatic_acoustic_improvement"
    elif score_delta <= 0 or adherence_delta < 0:
        result = "no_measured_improvement"
    else:
        result = "inconclusive"
    return {
        "schemaVersion": SCHEMA_VERSION,
        "kind": "delivery-prompt-automatic-acoustic-decision",
        "candidateID": candidate_id,
        "targetPreset": candidate["targetPreset"],
        "competingPreset": candidate["competingPreset"],
        "stage": stage_name,
        "variant": variant,
        "result": result,
        "eligibleForNextStage": result == "automatic_acoustic_improvement",
        "semanticAuthority": False,
        "perceptualCalibrationStatus": "not-evaluated-no-qualified-human-labels",
        "productionCopyAuthority": False,
        "publicationAuthority": False,
        "failures": failures,
        "missingFeatures": sorted(missing_features),
        "missingAnalysisPairCount": missing_analysis_pairs,
        "plannedPairCount": len(target_keys),
        "completionRate": completion_rate,
        "newHardFailureCount": new_hard_failures,
        "score": {
            "algorithm": contract["scoring"]["algorithm"],
            "calibrationManifestDigest": contract["scoring"]["calibration"]["manifestDigest"],
            "magnitudeBandsDigest": digest(contract["scoring"]["calibration"]["bands"]),
            "baselineMean": statistics.mean(baseline_scores),
            "candidateMean": statistics.mean(candidate_scores),
            "meanImprovement": score_delta,
            "pairedBootstrap": bootstrap,
        },
        "adherence": {
            "baselineRate": statistics.mean(baseline_adherence),
            "candidateRate": statistics.mean(candidate_adherence),
            "absoluteImprovement": adherence_delta,
            "pairedBootstrap": adherence_bootstrap,
        },
        "competingPresetSeparation": {
            "algorithm": separation_policy["algorithm"],
            "pairedComparisonCount": len(common_margin_keys),
            "baselineMedianSignedMargin": baseline_margin_median,
            "candidateMedianSignedMargin": candidate_margin_median,
            "medianSignedMarginDelta": margin_delta,
            "baselineWrongOrderCount": baseline_wrong_order_count,
            "candidateWrongOrderCount": candidate_wrong_order_count,
            "baselineWrongOrderRate": baseline_wrong_order_rate,
            "candidateWrongOrderRate": candidate_wrong_order_rate,
            "wrongOrderRateDelta": wrong_order_rate_delta,
            "baselineTieCount": sum(value == 0 for value in baseline_margins),
            "candidateTieCount": sum(value == 0 for value in candidate_margins),
            "missingBaselineComparisonCount": len(target_keys) - len(baseline_margin_map),
            "missingCandidateComparisonCount": len(target_keys) - len(candidate_margin_map),
        },
        "subgroupRegressions": subgroup_regressions,
        "pairRows": pair_rows,
        "contractDigest": digest(contract),
        "baselinePlanDigest": baseline_plan["executionPlanDigest"],
        "candidatePlanDigest": candidate_plan["executionPlanDigest"],
        "decisionSourceSHA256": file_sha256(Path(__file__)),
        "recomposition": {
            "legacyInput": legacy_recomposition,
            "inputSchemaVersion": LEGACY_SCHEMA_VERSION if legacy_recomposition else SCHEMA_VERSION,
            "scoringSchemaVersion": SCHEMA_VERSION,
        },
    }


def execute_stage(
    *, root: Path, binary: Path, data_dir: Path | None, contract: dict[str, Any],
    candidate_id: str, stage_name: str, variant: str,
) -> dict[str, Any]:
    baseline_dir = root / candidate_id / stage_name / variant / "baseline"
    candidate_dir = root / candidate_id / stage_name / variant / "candidate"
    baseline_plan = create_candidate_plan(
        binary=binary, contract=contract, candidate_id=candidate_id,
        stage_name=stage_name, variant=variant, baseline=True, data_dir=data_dir,
    )
    candidate_plan = create_candidate_plan(
        binary=binary, contract=contract, candidate_id=candidate_id,
        stage_name=stage_name, variant=variant, baseline=False, data_dir=data_dir,
    )
    run_execution_plan(
        plan=baseline_plan, binary=binary, data_dir=data_dir, run_dir=baseline_dir,
    )
    analyze_execution(baseline_plan, baseline_dir)
    seed_reference_controls(
        baseline_run=baseline_dir, candidate_plan=candidate_plan,
        candidate_run=candidate_dir, binary=binary, contract=contract,
        candidate_id=candidate_id, stage_name=stage_name, variant=variant,
    )
    run_execution_plan(
        plan=candidate_plan, binary=binary, data_dir=data_dir, run_dir=candidate_dir,
    )
    analyze_execution(candidate_plan, candidate_dir)
    result = decide(
        baseline_run=baseline_dir, candidate_run=candidate_dir, binary=binary,
        contract=contract, candidate_id=candidate_id,
        stage_name=stage_name, variant=variant,
    )
    atomic_json(root / candidate_id / stage_name / variant / "automatic-decision.json", result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("validate")
    calibration = commands.add_parser("verify-calibration")
    calibration.add_argument("--acoustic-layer", type=Path, required=True)
    plan = commands.add_parser("plan")
    plan.add_argument("--binary", type=Path, default=REPO / "build/vocello")
    plan.add_argument("--data-dir", type=Path)
    plan.add_argument("--candidate", required=True)
    plan.add_argument("--stage", choices=STAGE_ORDER, required=True)
    plan.add_argument("--variant", choices=("speed", "quality"), required=True)
    plan.add_argument("--baseline", action="store_true")
    plan.add_argument("--out", type=Path, required=True)
    execute = commands.add_parser("execute-stage")
    execute.add_argument("--binary", type=Path, default=REPO / "build/vocello")
    execute.add_argument("--data-dir", type=Path)
    execute.add_argument("--candidate", required=True)
    execute.add_argument("--stage", choices=STAGE_ORDER, required=True)
    execute.add_argument("--variant", choices=("speed", "quality"), required=True)
    execute.add_argument("--root", type=Path, required=True)
    decision = commands.add_parser("decide")
    decision.add_argument("--binary", type=Path, default=REPO / "build/vocello")
    decision.add_argument("--candidate", required=True)
    decision.add_argument("--stage", choices=STAGE_ORDER, required=True)
    decision.add_argument("--variant", choices=("speed", "quality"), required=True)
    decision.add_argument("--baseline-run", type=Path, required=True)
    decision.add_argument("--candidate-run", type=Path, required=True)
    decision.add_argument("--out", type=Path, required=True)
    recompose = commands.add_parser("recompose-legacy")
    recompose.add_argument("--binary", type=Path, default=REPO / "build/vocello")
    recompose.add_argument("--candidate", required=True)
    recompose.add_argument("--stage", choices=STAGE_ORDER, required=True)
    recompose.add_argument("--variant", choices=("speed", "quality"), required=True)
    recompose.add_argument("--baseline-run", type=Path, required=True)
    recompose.add_argument("--candidate-run", type=Path, required=True)
    recompose.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    try:
        contract = validate_contract(_load(args.contract))
        if args.command == "validate":
            result = {
                "status": "PASS", "contractDigest": digest(contract),
                "candidateCount": len(contract["candidates"]),
                "stages": list(contract["stages"]),
            }
        elif args.command == "verify-calibration":
            result = verify_calibration_bands(_load(args.acoustic_layer), contract)
        elif args.command == "plan":
            result = create_candidate_plan(
                binary=args.binary.resolve(), data_dir=args.data_dir,
                contract=contract, candidate_id=args.candidate,
                stage_name=args.stage, variant=args.variant, baseline=args.baseline,
            )
            atomic_json(args.out, result)
        elif args.command == "execute-stage":
            result = execute_stage(
                root=args.root, binary=args.binary.resolve(), data_dir=args.data_dir,
                contract=contract, candidate_id=args.candidate,
                stage_name=args.stage, variant=args.variant,
            )
        elif args.command in {"decide", "recompose-legacy"}:
            result = decide(
                baseline_run=args.baseline_run, candidate_run=args.candidate_run,
                binary=args.binary.resolve(), contract=contract,
                candidate_id=args.candidate, stage_name=args.stage,
                variant=args.variant, legacy_recomposition=args.command == "recompose-legacy",
            )
            atomic_json(args.out, result)
        else:
            raise RemediationError(f"unhandled command {args.command!r}")
        print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False))
        return 0
    except (OSError, json.JSONDecodeError, RunnerError, RemediationError) as error:
        print(f"Delivery prompt remediation: FAIL\n{error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
