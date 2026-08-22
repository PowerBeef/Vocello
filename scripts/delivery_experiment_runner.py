#!/usr/bin/env python3
"""Plan, run, resume, and acoustically analyze delivery experiments.

This operator-local harness invokes ``vocello generate`` once per take.  Each
process exits before the next take or analyzer starts, preventing concurrent
TTS/evaluator residency on the canonical 8 GB Mac.  Plans are source-bound,
failures are retained, completed cells are resumable, and no result is
published automatically.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import statistics
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from analyze_prosody import analyze
from delivery_quality_gate import delivery_features, evaluate_delivery
from prosody_profile import builtin_profile
from delivery_experiment import (
    DEFAULT_CONTRACT,
    DEFAULT_CORPUS,
    EXPECTED_ARMS,
    EXPECTED_PRESETS,
    INSTRUCTION_LANGUAGES,
    PRODUCT_CONTRACT,
    ExperimentError,
    _load,
    build_plan,
    canonical_json,
    digest,
    validate_contract,
    validate_corpus,
)


REPO = Path(__file__).resolve().parents[1]
SCHEMA_VERSION = 1
DEFAULT_TIMEOUT_SECONDS = 3_600
ACOUSTIC_FEATURES = (
    "durationSec",
    "f0_median_hz", "f0_std_semitones", "f0_range_semitones",
    "f0_voiced_frac", "f0_turning_points_per_sec",
    "rate_syllable_rate_hz", "rate_local_rate_cv",
    "pauses_pause_speech_ratio", "pauses_mean_pause_seconds",
    "energy_rms_mean_db", "energy_dynamic_range_db", "energy_envelope_roughness",
    "voice_hnr_db_mean", "voice_cpp_db_mean", "voice_frame_jitter_pct",
    "voice_frame_shimmer_db", "spectral_alpha_ratio_db",
    "spectral_centroid_hz", "spectral_hf_energy_ratio",
)


class RunnerError(ValueError):
    """Experiment execution cannot proceed without compromising provenance."""


def classify_cli_failure(stderr: str) -> str:
    """Return an allowlisted failure class without retaining diagnostic prose."""
    normalized = stderr.lower()
    patterns = (
        ("audio-quality-rejected", ("audio quality", "quality gate", "quality check")),
        ("memory-pressure-or-allocation", ("out of memory", "memory pressure", "allocation")),
        ("model-unavailable-or-invalid", ("model unavailable", "model not", "model artifact")),
        ("cancelled", ("cancelled", "canceled")),
        ("missing-output", ("no audio file exists", "missing audio")),
        ("runtime-abort", ("abort", "fatal error", "assertion failed")),
    )
    for category, needles in patterns:
        if any(needle in normalized for needle in needles):
            return category
    return "unclassified-cli-error"


def file_sha256(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(block)
    return hasher.hexdigest()


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


def _json_stdout(result: subprocess.CompletedProcess[str], label: str) -> Any:
    if result.returncode != 0:
        raise RunnerError(
            f"{label} exited {result.returncode} (stderr sha256 "
            f"{hashlib.sha256(result.stderr.encode('utf-8')).hexdigest()})"
        )
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise RunnerError(f"{label} did not emit valid JSON") from error


def discover_production_deliveries(
    binary: Path, data_dir: Path | None = None,
) -> dict[str, dict[str, str]]:
    command = [str(binary), "deliveries", "--shipped-only", "--json", "--quiet"]
    _ = data_dir  # Delivery definitions are compiled into the binary, not read from its data root.
    result = subprocess.run(
        command, cwd=REPO, check=False, capture_output=True, text=True, timeout=60
    )
    payload = _json_stdout(result, "vocello deliveries")
    if not isinstance(payload, list):
        raise RunnerError("vocello deliveries JSON must be an array")
    deliveries: dict[str, dict[str, str]] = {}
    for row in payload:
        preset = row.get("preset") if isinstance(row, dict) else None
        instruction = row.get("instruction") if isinstance(row, dict) else None
        intensity = row.get("intensity") if isinstance(row, dict) else None
        if preset in deliveries or preset not in EXPECTED_PRESETS:
            raise RunnerError("vocello deliveries contains an unknown or duplicate preset")
        if not isinstance(instruction, str) or not instruction.strip():
            raise RunnerError(f"vocello deliveries lacks instruction for {preset!r}")
        if intensity not in {"normal", "strong"}:
            raise RunnerError(f"vocello deliveries lacks shipped intensity for {preset!r}")
        deliveries[preset] = {"instruction": instruction, "intensity": intensity}
    if tuple(deliveries) != EXPECTED_PRESETS:
        raise RunnerError("vocello deliveries order/coverage drifted from the experiment contract")
    return deliveries


def create_execution_plan(
    *, binary: Path, data_dir: Path | None, split: str, arm: str,
    instruction_language: str, variant: str, sampling_combination: str,
    seeds: list[int], contract_path: Path = DEFAULT_CONTRACT,
    corpus_path: Path = DEFAULT_CORPUS,
    screen_label: str | None = None,
    cells: tuple[tuple[str, str], ...] = (),
    presets: tuple[str, ...] = (),
    lengths: tuple[str, ...] = (),
    conditions: tuple[str, ...] = (),
) -> dict[str, Any]:
    if not binary.is_file():
        raise RunnerError(f"CLI binary does not exist: {binary}")
    contract = validate_contract(_load(contract_path))
    product = _load(PRODUCT_CONTRACT)
    corpus = validate_corpus(_load(corpus_path), product)
    deliveries = discover_production_deliveries(binary, data_dir)
    instructions = {
        preset: delivery["instruction"] for preset, delivery in deliveries.items()
    }
    plan = build_plan(
        contract, corpus, product, split=split, arm=arm,
        instruction_language=instruction_language, variant=variant,
        sampling_combination=sampling_combination, seeds=seeds,
        production_instructions=instructions,
    )
    selection_requested = bool(cells or presets or lengths or conditions)
    if split == "confirmation" and selection_requested:
        raise RunnerError(
            "confirmation plans cannot be screened or partially selected; "
            "the untouched holdout must remain complete"
        )
    if screen_label is not None and not screen_label.strip():
        raise RunnerError("screen label must be non-empty when supplied")
    if selection_requested and not screen_label:
        raise RunnerError("screened plans require --screen-label")
    unknown_presets = set(presets) - set(EXPECTED_PRESETS)
    if unknown_presets:
        raise RunnerError(f"unknown preset selector(s): {sorted(unknown_presets)}")
    unknown_lengths = set(lengths) - {"short", "medium", "long"}
    if unknown_lengths:
        raise RunnerError(f"unknown length selector(s): {sorted(unknown_lengths)}")
    unknown_conditions = set(conditions) - {"neutral", "congruent", "conflicting"}
    if unknown_conditions:
        raise RunnerError(
            f"unknown semantic-condition selector(s): {sorted(unknown_conditions)}"
        )
    requested_cells = set(cells)
    rows = [
        row for row in plan["rows"]
        if (not requested_cells or (row["speakerID"], row["outputLanguage"]) in requested_cells)
        and (not presets or row["preset"] in presets)
        and (not lengths or row["script"]["length"] in lengths)
        and (not conditions or row["script"]["semanticCondition"] in conditions)
    ]
    if selection_requested and not rows:
        raise RunnerError("screen selection produced no experiment rows")
    if requested_cells:
        observed_cells = {(row["speakerID"], row["outputLanguage"]) for row in rows}
        missing_cells = requested_cells - observed_cells
        if missing_cells:
            raise RunnerError(f"screen selection has unavailable cells: {sorted(missing_cells)}")
    plan["rows"] = rows
    for row in plan["rows"]:
        row["shippedIntensity"] = deliveries[row["preset"]]["intensity"]
    plan["screeningSelection"] = {
        "label": screen_label,
        "scope": "screened-development" if selection_requested else "complete-split",
        "cells": [
            {"speakerID": speaker, "outputLanguage": language}
            for speaker, language in cells
        ],
        "presets": list(presets),
        "lengths": list(lengths),
        "semanticConditions": list(conditions),
        "promotionAuthority": False,
    }
    plan_body = dict(plan)
    plan_body.pop("planDigest", None)
    plan["planDigest"] = digest(plan_body)
    plan["executionIdentity"] = {
        "runnerSchemaVersion": SCHEMA_VERSION,
        "binarySHA256": file_sha256(binary),
        "runnerSHA256": file_sha256(Path(__file__)),
        "analyzerSHA256": file_sha256(REPO / "scripts/analyze_prosody.py"),
        "deliveryGateSHA256": file_sha256(REPO / "scripts/delivery_quality_gate.py"),
        "prosodyProfileSHA256": file_sha256(REPO / "scripts/prosody_profile.py"),
        "serialProcessPolicy": "one-generator-or-analyzer-process-at-a-time",
        "publicationPolicy": "never-automatic",
    }
    plan["executionPlanDigest"] = digest(plan)
    return plan


def validate_execution_plan(plan: dict[str, Any], binary: Path) -> dict[str, Any]:
    if not isinstance(plan, dict) or plan.get("schemaVersion") != SCHEMA_VERSION:
        raise RunnerError(f"plan schemaVersion must be {SCHEMA_VERSION}")
    body = dict(plan)
    stored = body.pop("executionPlanDigest", None)
    if stored != digest(body):
        raise RunnerError("execution plan digest mismatch")
    identity = plan.get("executionIdentity")
    if not isinstance(identity, dict) or identity.get("binarySHA256") != file_sha256(binary):
        raise RunnerError("CLI binary digest does not match execution plan")
    expected_sources = {
        "runnerSHA256": Path(__file__),
        "analyzerSHA256": REPO / "scripts/analyze_prosody.py",
        "deliveryGateSHA256": REPO / "scripts/delivery_quality_gate.py",
        "prosodyProfileSHA256": REPO / "scripts/prosody_profile.py",
    }
    for field, path in expected_sources.items():
        if identity.get(field) != file_sha256(path):
            raise RunnerError(f"{field} does not match execution plan")
    plan_body = {
        key: value for key, value in plan.items()
        if key not in {"planDigest", "executionIdentity", "executionPlanDigest"}
    }
    if plan.get("planDigest") != digest(plan_body):
        raise RunnerError("experiment plan digest mismatch")
    rows = plan.get("rows")
    if not isinstance(rows, list) or not rows:
        raise RunnerError("execution plan has no rows")
    take_ids = [row.get("takeID") for row in rows if isinstance(row, dict)]
    if len(take_ids) != len(rows) or len(set(take_ids)) != len(rows):
        raise RunnerError("execution plan take IDs are missing or duplicated")
    return plan


def _sampling_environment(row: dict[str, Any]) -> dict[str, str]:
    sampling = row["sampling"]
    talker = sampling["talker"]
    subtalker = sampling["subtalker"]
    return {
        "QWENVOICE_DEBUG": "1",
        "QWENVOICE_TALKER_TEMP": str(talker["temperature"]),
        "QWENVOICE_TALKER_TOPP": str(talker["topP"]),
        "QWENVOICE_TALKER_TOPK": str(talker["topK"]),
        "QWENVOICE_SUBTALKER_TEMP": str(subtalker["temperature"]),
        "QWENVOICE_SUBTALKER_TOPP": str(subtalker["topP"]),
        "QWENVOICE_SUBTALKER_TOPK": str(subtalker["topK"]),
    }


def _invoke_generate(
    *, binary: Path, data_dir: Path | None, row: dict[str, Any],
    instruction: dict[str, Any], output_path: Path, timeout_seconds: int,
) -> dict[str, Any]:
    command = [
        str(binary), "generate", "--mode", "custom",
        "--variant", row["variant"], "--speaker", row["speakerID"],
        "--language", row["outputLanguage"], "--seed", str(row["seed"]),
        "--delivery", instruction["text"], "--text", row["script"]["text"],
        "--out", str(output_path), "--json", "--quiet",
    ]
    if data_dir is not None:
        command.extend(["--data-dir", str(data_dir)])
    env = dict(os.environ)
    env.update(_sampling_environment(row))
    try:
        result = subprocess.run(
            command, cwd=REPO, env=env, check=False, capture_output=True,
            text=True, timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as error:
        def timeout_digest(value: str | bytes | None) -> str:
            raw = value if isinstance(value, bytes) else (value or "").encode("utf-8")
            return hashlib.sha256(raw).hexdigest()

        return {
            "status": "failed-timeout", "timeoutSeconds": timeout_seconds,
            "stdoutSHA256": timeout_digest(error.stdout),
            "stderrSHA256": timeout_digest(error.stderr),
        }
    if result.returncode != 0:
        return {
            "status": "failed", "returnCode": result.returncode,
            "failureCategory": classify_cli_failure(result.stderr),
            "stderrLineCount": len(result.stderr.splitlines()),
            "stdoutSHA256": hashlib.sha256(result.stdout.encode()).hexdigest(),
            "stderrSHA256": hashlib.sha256(result.stderr.encode()).hexdigest(),
        }
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return {"status": "failed-invalid-json", "returnCode": result.returncode}
    if not isinstance(payload, dict):
        return {"status": "failed-invalid-json-shape"}
    if payload.get("deliveryInstructionDigest") != instruction["sha256"]:
        return {
            "status": "failed-instruction-receipt",
            "expectedDigest": instruction["sha256"],
            "observedDigest": payload.get("deliveryInstructionDigest"),
        }
    if not output_path.is_file():
        return {"status": "failed-missing-audio"}
    generation_id = payload.get("generationID")
    if not isinstance(generation_id, str) or not generation_id:
        return {"status": "failed-missing-generation-id"}
    return {
        "status": "complete", "generationID": generation_id,
        "audio": str(Path("audio") / output_path.name),
        "audioSHA256": file_sha256(output_path),
        "durationSeconds": payload.get("durationSeconds"),
        "wallSeconds": payload.get("wallSeconds"),
        "finishReason": payload.get("finishReason"),
        "instructionDigest": instruction["sha256"],
        "scriptDigest": row["script"]["sha256"],
    }


def _reference_key(row: dict[str, Any]) -> str:
    identity = {
        "speakerID": row["speakerID"], "outputLanguage": row["outputLanguage"],
        "scriptDigest": row["script"]["sha256"], "seed": row["seed"],
        "variant": row["variant"], "sampling": row["sampling"],
        "instructionDigest": row["neutralReferenceInstruction"]["sha256"],
    }
    return digest(identity)[:24]


def run_execution_plan(
    *, plan: dict[str, Any], binary: Path, data_dir: Path | None,
    run_dir: Path, limit: int | None = None,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS, retry_failures: bool = False,
) -> dict[str, Any]:
    validate_execution_plan(plan, binary)
    run_dir.mkdir(parents=True, exist_ok=True)
    retained_plan_path = run_dir / "execution-plan.json"
    if retained_plan_path.is_file():
        retained_plan = json.loads(retained_plan_path.read_text(encoding="utf-8"))
        if retained_plan.get("executionPlanDigest") != plan["executionPlanDigest"]:
            raise RunnerError("resume refused: retained execution plan changed")
    else:
        atomic_json(retained_plan_path, plan)
    audio_dir = run_dir / "audio"
    audio_dir.mkdir(exist_ok=True)
    state_path = run_dir / "execution-state.json"
    if state_path.is_file():
        state = json.loads(state_path.read_text(encoding="utf-8"))
        if state.get("executionPlanDigest") != plan["executionPlanDigest"]:
            raise RunnerError("resume refused: execution plan changed")
    else:
        state = {
            "schemaVersion": SCHEMA_VERSION,
            "executionPlanDigest": plan["executionPlanDigest"],
            "binarySHA256": plan["executionIdentity"]["binarySHA256"],
            "references": {}, "takes": {},
        }
        atomic_json(state_path, state)
    processed = 0
    for row in plan["rows"]:
        if limit is not None and processed >= limit:
            break
        take_id = row["takeID"]
        retained = state["takes"].get(take_id)
        if retained and (retained.get("status") == "complete" or not retry_failures):
            continue
        reference_key = _reference_key(row)
        reference = state["references"].get(reference_key)
        if not reference or (reference.get("status") != "complete" and retry_failures):
            reference_path = audio_dir / f"reference-{reference_key}.wav"
            reference = _invoke_generate(
                binary=binary, data_dir=data_dir, row=row,
                instruction=row["neutralReferenceInstruction"],
                output_path=reference_path, timeout_seconds=timeout_seconds,
            )
            state["references"][reference_key] = reference
            atomic_json(state_path, state)
        if reference.get("status") != "complete":
            state["takes"][take_id] = {
                "status": "blocked-reference-failure", "referenceKey": reference_key,
            }
            atomic_json(state_path, state)
            processed += 1
            continue
        instructed_path = audio_dir / f"take-{take_id}.wav"
        take = _invoke_generate(
            binary=binary, data_dir=data_dir, row=row, instruction=row["instruction"],
            output_path=instructed_path, timeout_seconds=timeout_seconds,
        )
        take["referenceKey"] = reference_key
        state["takes"][take_id] = take
        atomic_json(state_path, state)
        processed += 1
    state["counts"] = {
        "planned": len(plan["rows"]),
        "complete": sum(row.get("status") == "complete" for row in state["takes"].values()),
        "failedOrBlocked": sum(row.get("status") != "complete" for row in state["takes"].values()),
    }
    atomic_json(state_path, state)
    return state


def _numeric_delta(instructed: dict[str, Any], reference: dict[str, Any], name: str) -> float:
    left, right = instructed.get(name), reference.get(name)
    if isinstance(left, bool) or isinstance(right, bool) or not isinstance(
        left, (int, float)
    ) or not isinstance(right, (int, float)):
        raise RunnerError(f"prosody feature {name} is unavailable or non-numeric")
    value = float(left) - float(right)
    if not math.isfinite(value):
        raise RunnerError(f"prosody feature {name} is non-finite")
    return value


def analyze_execution(plan: dict[str, Any], run_dir: Path) -> dict[str, Any]:
    state = json.loads((run_dir / "execution-state.json").read_text(encoding="utf-8"))
    if state.get("executionPlanDigest") != plan.get("executionPlanDigest"):
        raise RunnerError("analysis refused: state and plan identities differ")
    rows_by_id = {row["takeID"]: row for row in plan["rows"]}
    profile = builtin_profile()
    rows: list[dict[str, Any]] = []
    for take_id, result in sorted(state["takes"].items()):
        if result.get("status") != "complete":
            continue
        row = rows_by_id.get(take_id)
        reference = state["references"].get(result.get("referenceKey"), {})
        if row is None or reference.get("status") != "complete":
            raise RunnerError(f"{take_id}: missing plan row or complete reference")
        instructed_analysis = analyze(str(run_dir / result["audio"]))
        reference_analysis = analyze(str(run_dir / reference["audio"]))
        if "error" in instructed_analysis or "error" in reference_analysis:
            raise RunnerError(f"{take_id}: deterministic prosody analysis failed")
        rows.append({
            "generationID": result["generationID"],
            "takeID": take_id, "speakerID": row["speakerID"],
            "scriptID": row["script"]["scriptID"], "preset": row["preset"],
            "features": {
                name: _numeric_delta(instructed_analysis, reference_analysis, name)
                for name in ACOUSTIC_FEATURES
            },
            "derivedFeatures": delivery_features(
                instructed_analysis, reference_analysis, profile
            ),
            "deliveryVerdict": evaluate_delivery(
                instructed_analysis, reference_analysis,
                f"{row['preset']}.{row['shippedIntensity']}",
                profile,
            ),
            "analyzerAlgorithmVersion": instructed_analysis["analyzerAlgorithmVersion"],
            "instructionDigest": row["instruction"]["sha256"],
            "scriptDigest": row["script"]["sha256"],
        })
    if not rows:
        raise RunnerError("analysis has no complete instructed/reference pair")
    report = {
        "schemaVersion": SCHEMA_VERSION, "kind": "paired-acoustic-delta",
        "promotionAuthority": False, "manifestDigest": plan["executionPlanDigest"],
        "featureNames": list(ACOUSTIC_FEATURES), "rows": rows,
    }
    atomic_json(run_dir / "acoustic-layer.json", report)
    return report


def _parse_seeds(raw: str) -> list[int]:
    try:
        seeds = [int(item.strip()) for item in raw.split(",") if item.strip()]
    except ValueError as error:
        raise RunnerError("seeds must be comma-separated non-negative integers") from error
    if not seeds or len(seeds) != len(set(seeds)) or any(seed < 0 for seed in seeds):
        raise RunnerError("seeds must be unique non-negative integers")
    return seeds


def _parse_csv(raw: str | None) -> tuple[str, ...]:
    if raw is None:
        return ()
    values = tuple(item.strip() for item in raw.split(",") if item.strip())
    if len(values) != len(set(values)):
        raise RunnerError("screen selectors must not contain duplicates")
    return values


def _parse_cells(raw: str | None) -> tuple[tuple[str, str], ...]:
    cells: list[tuple[str, str]] = []
    for value in _parse_csv(raw):
        speaker, separator, language = value.partition(":")
        if not separator or not speaker or not language:
            raise RunnerError(
                "cells must be comma-separated <speakerID>:<outputLanguage> pairs"
            )
        cells.append((speaker, language))
    if len(cells) != len(set(cells)):
        raise RunnerError("screen cells must not contain duplicates")
    return tuple(cells)


def execution_verdict(result: dict[str, Any]) -> dict[str, Any]:
    counts = result.get("counts")
    if not isinstance(counts, dict):
        raise RunnerError("execution result lacks counts")
    complete = counts.get("complete")
    failed = counts.get("failedOrBlocked")
    if (
        isinstance(complete, bool) or not isinstance(complete, int) or complete < 0
        or isinstance(failed, bool) or not isinstance(failed, int) or failed < 0
    ):
        raise RunnerError("execution result counts are invalid")
    failures = []
    if failed:
        failures.append("failed-or-blocked-rows")
    if complete == 0:
        failures.append("no-complete-row")
    return {
        "status": "PASS" if not failures else "FAIL",
        "complete": complete,
        "failedOrBlocked": failed,
        "failures": failures,
    }


def _comparison_key(row: dict[str, Any]) -> str:
    return digest({
        "speakerID": row["speakerID"],
        "outputLanguage": row["outputLanguage"],
        "preset": row["preset"],
        "scriptDigest": row["script"]["sha256"],
        "seed": row["seed"],
        "variant": row["variant"],
    })


def _paired_exact_p(improved: int, regressed: int) -> float:
    discordant = improved + regressed
    if discordant == 0:
        return 1.0
    tail = sum(
        math.comb(discordant, value)
        for value in range(min(improved, regressed) + 1)
    ) / (2 ** discordant)
    return min(1.0, 2.0 * tail)


def summarize_screen(
    runs: dict[str, Path], *, baseline_label: str | None = None,
) -> dict[str, Any]:
    """Summarize one-factor development screens without claiming promotion."""
    if len(runs) < 2:
        raise RunnerError("screen summary requires at least two labeled runs")
    entries: list[dict[str, Any]] = []
    factor_fields = ("arm", "instructionLanguage", "samplingCombination", "variant")
    selection_identity: dict[str, Any] | None = None
    comparison_keys: set[str] | None = None
    harness_identity: dict[str, str] | None = None
    outcomes_by_label: dict[str, dict[str, bool]] = {}
    metadata_by_key: dict[str, dict[str, str]] = {}
    for label, run_dir in sorted(runs.items()):
        plan_path = run_dir / "execution-plan.json"
        state_path = run_dir / "execution-state.json"
        acoustic_path = run_dir / "acoustic-layer.json"
        if not plan_path.is_file() or not state_path.is_file() or not acoustic_path.is_file():
            raise RunnerError(f"{label}: run lacks plan, state, or acoustic layer")
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        state = json.loads(state_path.read_text(encoding="utf-8"))
        acoustic = json.loads(acoustic_path.read_text(encoding="utf-8"))
        if state.get("executionPlanDigest") != plan.get("executionPlanDigest"):
            raise RunnerError(f"{label}: state and plan identity differ")
        if acoustic.get("manifestDigest") != plan.get("executionPlanDigest"):
            raise RunnerError(f"{label}: acoustic layer and plan identity differ")
        identity = plan.get("executionIdentity", {})
        normalized_harness = {
            field: identity.get(field) for field in (
                "binarySHA256", "runnerSHA256", "analyzerSHA256",
                "deliveryGateSHA256", "prosodyProfileSHA256",
            )
        }
        if any(not isinstance(value, str) or len(value) != 64
               for value in normalized_harness.values()):
            raise RunnerError(f"{label}: source-bound harness identity is incomplete")
        if harness_identity is None:
            harness_identity = normalized_harness
        elif harness_identity != normalized_harness:
            raise RunnerError("screen runs use different binary or harness bytes")
        selection = plan.get("screeningSelection")
        if not isinstance(selection, dict) or selection.get("scope") != "screened-development":
            raise RunnerError(f"{label}: only screened development runs may be summarized")
        normalized_selection = {
            key: value for key, value in selection.items() if key != "label"
        }
        if selection_identity is None:
            selection_identity = normalized_selection
        elif selection_identity != normalized_selection:
            raise RunnerError("screen runs use different row selections")
        keys = {_comparison_key(row) for row in plan["rows"]}
        if comparison_keys is None:
            comparison_keys = keys
        elif comparison_keys != keys:
            raise RunnerError("screen runs do not cover the same comparison cells")
        rows = acoustic.get("rows")
        if not isinstance(rows, list):
            raise RunnerError(f"{label}: acoustic layer rows are invalid")
        passed = sum(
            row.get("deliveryVerdict", {}).get("passed") is True for row in rows
        )
        key_by_take = {
            row["takeID"]: _comparison_key(row) for row in plan["rows"]
        }
        outcomes = {key: False for key in keys}
        for row in rows:
            take_id = row.get("takeID")
            if take_id not in key_by_take:
                raise RunnerError(f"{label}: acoustic row has an unknown take identity")
            outcomes[key_by_take[take_id]] = (
                row.get("deliveryVerdict", {}).get("passed") is True
            )
        outcomes_by_label[label] = outcomes
        for row in plan["rows"]:
            key = _comparison_key(row)
            metadata = {
                "preset": row["preset"], "speakerID": row["speakerID"],
            }
            previous = metadata_by_key.setdefault(key, metadata)
            if previous != metadata:
                raise RunnerError("screen comparison-cell metadata differ")
        per_preset: dict[str, dict[str, int]] = {}
        feature_values: dict[str, list[float]] = {}
        for row in rows:
            preset = row.get("preset")
            bucket = per_preset.setdefault(preset, {"analyzed": 0, "passed": 0})
            bucket["analyzed"] += 1
            bucket["passed"] += row.get("deliveryVerdict", {}).get("passed") is True
            for name, value in row.get("derivedFeatures", {}).items():
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    feature_values.setdefault(name, []).append(float(value))
        entries.append({
            "label": label,
            "runDirectory": str(run_dir),
            "executionPlanDigest": plan["executionPlanDigest"],
            "factors": {field: plan[field] for field in factor_fields},
            "planned": len(plan["rows"]),
            "complete": state.get("counts", {}).get("complete", 0),
            "failedOrBlocked": state.get("counts", {}).get("failedOrBlocked", 0),
            "analyzed": len(rows),
            "acousticPassCount": passed,
            "acousticPassRate": passed / len(plan["rows"]),
            "perPreset": per_preset,
            "medianDerivedFeatures": {
                name: statistics.median(values)
                for name, values in sorted(feature_values.items())
            },
        })
    varying = [
        field for field in factor_fields
        if len({entry["factors"][field] for entry in entries}) > 1
    ]
    if len(varying) != 1:
        raise RunnerError(
            f"screen must vary exactly one factor, observed varying factors: {varying}"
        )
    ranked = sorted(
        entries,
        key=lambda entry: (
            -entry["acousticPassRate"], entry["failedOrBlocked"], entry["label"]
        ),
    )
    paired_comparisons: dict[str, Any] = {}
    if baseline_label is not None:
        if baseline_label not in outcomes_by_label:
            raise RunnerError(f"unknown baseline label {baseline_label}")
        baseline = outcomes_by_label[baseline_label]
        for label, candidate in sorted(outcomes_by_label.items()):
            if label == baseline_label:
                continue
            groups = {"overall": sorted(baseline)}
            groups.update({
                f"preset:{preset}": sorted(
                    key for key in baseline if metadata_by_key[key]["preset"] == preset
                )
                for preset in sorted({value["preset"] for value in metadata_by_key.values()})
            })
            comparisons = {}
            for group, keys in groups.items():
                improved = sum(not baseline[key] and candidate[key] for key in keys)
                regressed = sum(baseline[key] and not candidate[key] for key in keys)
                comparisons[group] = {
                    "cellCount": len(keys),
                    "improved": improved,
                    "regressed": regressed,
                    "bothPassed": sum(baseline[key] and candidate[key] for key in keys),
                    "bothFailed": sum(not baseline[key] and not candidate[key] for key in keys),
                    "discordant": improved + regressed,
                    "twoSidedExactP": _paired_exact_p(improved, regressed),
                }
            paired_comparisons[label] = comparisons
    return {
        "schemaVersion": SCHEMA_VERSION,
        "kind": "delivery-development-screen-summary",
        "promotionAuthority": False,
        "semanticAuthority": False,
        "controlledFactor": varying[0],
        "selection": selection_identity,
        "comparisonCellCount": len(comparison_keys or ()),
        "rankingBasis": "advisory-acoustic-pass-rate-with-failures-in-denominator",
        "harnessIdentity": harness_identity,
        "summarizerSHA256": file_sha256(Path(__file__).resolve()),
        "ranking": [entry["label"] for entry in ranked],
        "runs": entries,
        "pairedAgainst": baseline_label,
        "pairedComparisons": paired_comparisons,
    }


def _parse_labeled_paths(raw: str) -> dict[str, Path]:
    result: dict[str, Path] = {}
    for item in _parse_csv(raw):
        label, separator, path = item.partition("=")
        if not separator or not label or not path:
            raise RunnerError("runs must be comma-separated label=directory entries")
        if label in result:
            raise RunnerError(f"duplicate run label {label}")
        result[label] = Path(path)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    plan_parser = commands.add_parser("plan")
    plan_parser.add_argument("--binary", type=Path, default=REPO / "build/vocello")
    plan_parser.add_argument("--data-dir", type=Path)
    plan_parser.add_argument("--split", choices=("calibration", "development", "confirmation"), required=True)
    plan_parser.add_argument("--arm", choices=EXPECTED_ARMS, required=True)
    plan_parser.add_argument("--instruction-language", choices=INSTRUCTION_LANGUAGES, default="english")
    plan_parser.add_argument("--variant", choices=("speed", "quality"), required=True)
    plan_parser.add_argument("--sampling", required=True)
    plan_parser.add_argument("--seeds", required=True)
    plan_parser.add_argument("--screen-label")
    plan_parser.add_argument(
        "--cells", help="comma-separated speakerID:outputLanguage screen cells"
    )
    plan_parser.add_argument("--presets", help="comma-separated preset screen")
    plan_parser.add_argument("--lengths", help="comma-separated short,medium,long")
    plan_parser.add_argument(
        "--conditions", help="comma-separated neutral,congruent,conflicting"
    )
    plan_parser.add_argument("--out", type=Path, required=True)
    run_parser = commands.add_parser("run")
    run_parser.add_argument("--binary", type=Path, default=REPO / "build/vocello")
    run_parser.add_argument("--data-dir", type=Path)
    run_parser.add_argument("--plan", type=Path, required=True)
    run_parser.add_argument("--run-dir", type=Path, required=True)
    run_parser.add_argument("--limit", type=int)
    run_parser.add_argument("--timeout-seconds", type=int, default=DEFAULT_TIMEOUT_SECONDS)
    run_parser.add_argument("--retry-failures", action="store_true")
    analyze_parser = commands.add_parser("analyze")
    analyze_parser.add_argument("--plan", type=Path, required=True)
    analyze_parser.add_argument("--run-dir", type=Path, required=True)
    summarize_parser = commands.add_parser("summarize")
    summarize_parser.add_argument(
        "--runs", required=True, help="comma-separated label=run-directory entries"
    )
    summarize_parser.add_argument("--out", type=Path, required=True)
    summarize_parser.add_argument(
        "--baseline", help="label used for paired advisory pass/fail comparisons"
    )
    args = parser.parse_args()
    try:
        if args.command == "plan":
            result = create_execution_plan(
                binary=args.binary.resolve(), data_dir=args.data_dir,
                split=args.split, arm=args.arm,
                instruction_language=args.instruction_language,
                variant=args.variant, sampling_combination=args.sampling,
                seeds=_parse_seeds(args.seeds),
                screen_label=args.screen_label,
                cells=_parse_cells(args.cells),
                presets=_parse_csv(args.presets),
                lengths=_parse_csv(args.lengths),
                conditions=_parse_csv(args.conditions),
            )
            atomic_json(args.out, result)
        elif args.command in {"run", "analyze"}:
            plan = json.loads(args.plan.read_text(encoding="utf-8"))
            if args.command == "run":
                result = run_execution_plan(
                    plan=plan, binary=args.binary.resolve(), data_dir=args.data_dir,
                    run_dir=args.run_dir, limit=args.limit,
                    timeout_seconds=args.timeout_seconds,
                    retry_failures=args.retry_failures,
                )
            else:
                result = analyze_execution(plan, args.run_dir)
        else:
            result = summarize_screen(
                _parse_labeled_paths(args.runs), baseline_label=args.baseline,
            )
            atomic_json(args.out, result)
        verdict = (
            execution_verdict(result)
            if args.command == "run"
            else {"status": "PASS", "failures": []}
        )
        print(json.dumps({
            **verdict, "kind": args.command,
            "rows": len(result.get("rows", result.get("takes", result.get("runs", {})))),
        }, indent=2))
        return 0 if verdict["status"] == "PASS" else 2
    except (OSError, json.JSONDecodeError, ExperimentError, RunnerError) as error:
        print(f"Delivery experiment runner: FAIL\n{error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
