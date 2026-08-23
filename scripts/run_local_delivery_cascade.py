#!/usr/bin/env python3
"""Run the existing delivery harness as a local, serial perceptual cascade.

Always-on deterministic layers are cached by audio bytes and source identity.
Compact neural features are optional until a candidate is fully pinned. Rows
are explicitly accepted for more screening, rejected, abstained, or routed to
manual listening; no automatic result has semantic promotion authority.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any

import numpy as np

from analyze_prosody import analyze
from delivery_analysis_cache import (
    DeliveryAnalysisCache,
    LayerIdentity,
    NO_MODEL_DIGEST,
    digest,
    file_sha256,
)
from delivery_compact_model_adapter import run_compact_adapter
from delivery_evaluator import atomic_json
from delivery_evaluator_v2 import evaluate_v2
from delivery_temporal_features import analyze_temporal, paired_temporal_delta


SCHEMA_VERSION = 1
REPO = Path(__file__).resolve().parents[1]
GLOBAL_ANALYZER = REPO / "scripts/analyze_prosody.py"
TEMPORAL_ANALYZER = REPO / "scripts/delivery_temporal_features.py"
CASCADE_SOURCE = Path(__file__).resolve()
DEFAULT_CACHE_ROOT = Path(os.environ.get(
    "QVOICE_DELIVERY_ANALYSIS_CACHE", REPO / "build/cache/delivery-analysis"
))


class CascadeError(ValueError):
    """The cascade input is incomplete, cross-run, or unsafe."""


def _read(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise CascadeError(f"cannot load {path.name}: {error}") from error
    if not isinstance(value, dict):
        raise CascadeError(f"{path.name} must contain an object")
    return value


def _identity(canonical, *, layer: str, version: str, source: Path) -> LayerIdentity:
    return LayerIdentity(
        original_wav_sha256=canonical.original_wav_sha256,
        canonical_derivative_sha256=canonical.canonical_derivative_sha256,
        layer_id=layer, layer_version=version,
        binary_sha256=file_sha256(source), model_id="none",
        model_revision="not-applicable", weights_sha256=NO_MODEL_DIGEST,
        preprocessing_config_digest=digest({
            "sampleRate": "source-native", "requestedLabelVisible": False,
        }),
    )


def _pcm_integrity_layer(canonical) -> dict[str, Any]:
    sample_count = 0
    peak = 0
    clipped = 0
    sum_squares = 0.0
    with canonical.derivative_path.open("rb") as handle:
        for raw in iter(lambda: handle.read(1024 * 1024), b""):
            if len(raw) % 2:
                return {"status": "rejected", "errorCode": "truncated-pcm-s16le"}
            samples = np.frombuffer(raw, dtype="<i2").astype(np.float64)
            sample_count += int(samples.size)
            if samples.size:
                peak = max(peak, int(np.max(np.abs(samples))))
                clipped += int(np.count_nonzero(np.abs(samples) >= 32767))
                sum_squares += float(np.dot(samples, samples))
    if sample_count != canonical.sample_count or sample_count == 0:
        return {"status": "rejected", "errorCode": "pcm-sample-count-mismatch"}
    if peak == 0:
        return {"status": "rejected", "errorCode": "all-zero-pcm"}
    return {
        "status": "complete",
        "sampleCount": sample_count,
        "durationSeconds": canonical.duration_seconds,
        "peakAbsolutePCM16": peak,
        "rmsPCM16": math.sqrt(sum_squares / sample_count),
        "clippedSampleFraction": clipped / sample_count,
    }


def _global_layer(path: Path) -> dict[str, Any]:
    report = analyze(str(path))
    if "error" in report:
        return {"status": "rejected", "errorCode": str(report["error"]).split(":", 1)[0]}
    report = dict(report)
    report.pop("clip", None)
    return {"status": "complete", "features": report}


def _temporal_layer(path: Path) -> dict[str, Any]:
    try:
        return {"status": "complete", "features": analyze_temporal(str(path))}
    except ValueError as error:
        return {"status": "rejected", "errorCode": type(error).__name__}


def _numeric_delta(left: Any, right: Any) -> Any:
    if isinstance(left, dict) and isinstance(right, dict):
        return {key: _numeric_delta(left[key], right[key]) for key in left.keys() & right.keys()}
    if isinstance(left, bool) or isinstance(right, bool):
        return None
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        value = float(left) - float(right)
        return value if math.isfinite(value) else None
    return None


def _flatten_numeric(value: Any, prefix: str, output: dict[str, float]) -> None:
    if isinstance(value, dict):
        for key in sorted(value):
            if key in {"schemaVersion", "promotionAuthority", "memory"}:
                continue
            _flatten_numeric(value[key], f"{prefix}.{key}" if prefix else key, output)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _flatten_numeric(child, f"{prefix}[{index}]", output)
    elif isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value)):
        output[prefix] = float(value)


def build_cascade_manifest(*, plan_path: Path, run_dir: Path) -> dict[str, Any]:
    plan = _read(plan_path)
    retained_plan = _read(run_dir / "execution-plan.json")
    state = _read(run_dir / "execution-state.json")
    acoustic = _read(run_dir / "acoustic-layer.json")
    execution_digest = plan.get("executionPlanDigest")
    if (
        not isinstance(execution_digest, str) or len(execution_digest) != 64
        or retained_plan.get("executionPlanDigest") != execution_digest
        or state.get("executionPlanDigest") != execution_digest
        or acoustic.get("manifestDigest") != execution_digest
    ):
        raise CascadeError("cascade plan, retained plan, state, and acoustic identities differ")
    plan_rows = {row.get("takeID"): row for row in plan.get("rows", []) if isinstance(row, dict)}
    takes = state.get("takes")
    if not plan_rows or not isinstance(takes, dict) or set(takes) != set(plan_rows):
        raise CascadeError("cascade requires exact planned-row coverage")
    if any(not isinstance(row, dict) or row.get("status") != "complete" for row in takes.values()):
        raise CascadeError("cascade requires every planned generation to complete")
    acoustic_rows = {
        row.get("takeID"): row for row in acoustic.get("rows", []) if isinstance(row, dict)
    }
    if set(acoustic_rows) != set(plan_rows):
        raise CascadeError("cascade requires exact acoustic-row coverage")
    rows = []
    for take_id, row in sorted(plan_rows.items()):
        take = takes[take_id]
        reference = state.get("references", {}).get(take.get("referenceKey"), {})
        if reference.get("status") != "complete":
            raise CascadeError(f"{take_id}: paired neutral reference is incomplete")
        instructed = run_dir / str(take.get("audio", ""))
        neutral = run_dir / str(reference.get("audio", ""))
        if (
            not instructed.is_file() or file_sha256(instructed) != take.get("audioSHA256")
            or not neutral.is_file() or file_sha256(neutral) != reference.get("audioSHA256")
        ):
            raise CascadeError(f"{take_id}: source-bound audio is missing or changed")
        rows.append({
            "generationID": take["generationID"],
            "speakerID": row["speakerID"],
            "scriptID": row["script"]["scriptID"],
            "scriptTranslationGroup": row["script"].get(
                "translationGroup", row["script"]["scriptID"]
            ),
            "seed": row["seed"],
            "outputLanguage": row["outputLanguage"],
            "preset": row["preset"],
            "instructedWAV": str(instructed),
            "neutralWAV": str(neutral),
            "instructedSHA256": take["audioSHA256"],
            "neutralSHA256": reference["audioSHA256"],
        })
    identity = plan.get("executionIdentity")
    required_identity = (
        "binarySHA256", "runnerSHA256", "analyzerSHA256", "temporalAnalyzerSHA256"
    )
    if not isinstance(identity, dict) or any(
        not isinstance(identity.get(field), str) or len(identity[field]) != 64
        for field in required_identity
    ):
        raise CascadeError("cascade generator or analyzer identity is incomplete")
    body = {
        "schemaVersion": SCHEMA_VERSION,
        "kind": "source-bound-delivery-cascade-input",
        "generationProcessExited": True,
        "executionPlanDigest": execution_digest,
        "sourceDigests": {
            "retainedPlanSHA256": file_sha256(run_dir / "execution-plan.json"),
            "executionStateSHA256": file_sha256(run_dir / "execution-state.json"),
            "acousticLayerSHA256": file_sha256(run_dir / "acoustic-layer.json"),
            **{field: identity[field] for field in required_identity},
        },
        "rows": rows,
    }
    return {**body, "manifestDigest": digest(body)}


def _validate_manifest(payload: dict[str, Any]) -> list[dict[str, Any]]:
    if payload.get("schemaVersion") != SCHEMA_VERSION:
        raise CascadeError("cascade manifest schemaVersion must be 1")
    if payload.get("kind") != "source-bound-delivery-cascade-input":
        raise CascadeError("cascade input is not source-bound")
    body = dict(payload)
    stored_digest = body.pop("manifestDigest", None)
    if stored_digest != digest(body):
        raise CascadeError("cascade manifest digest mismatch")
    execution_digest = payload.get("executionPlanDigest")
    if not isinstance(execution_digest, str) or len(execution_digest) != 64:
        raise CascadeError("cascade execution plan identity is invalid")
    source_digests = payload.get("sourceDigests")
    if not isinstance(source_digests, dict) or any(
        not isinstance(value, str) or len(value) != 64 for value in source_digests.values()
    ):
        raise CascadeError("cascade source digests are incomplete")
    if payload.get("generationProcessExited") is not True:
        raise CascadeError("TTS/MLX process must exit before the evaluator cascade starts")
    rows = payload.get("rows")
    if not isinstance(rows, list) or not rows:
        raise CascadeError("cascade manifest rows must be non-empty")
    identities = set()
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("generationID"), str):
            raise CascadeError("cascade row lacks a generation identity")
        if row["generationID"] in identities:
            raise CascadeError("cascade generation identities are duplicated")
        identities.add(row["generationID"])
        for field in (
            "speakerID", "scriptID", "scriptTranslationGroup", "outputLanguage", "preset",
            "instructedWAV", "neutralWAV", "instructedSHA256", "neutralSHA256",
        ):
            if not isinstance(row.get(field), str) or not row[field]:
                raise CascadeError(f"{row['generationID']}: {field} is required")
        if isinstance(row.get("seed"), bool) or not isinstance(row.get("seed"), int):
            raise CascadeError(f"{row['generationID']}: seed is required")
        for field in ("instructedWAV", "neutralWAV"):
            path = Path(row[field])
            expected = row["instructedSHA256" if field == "instructedWAV" else "neutralSHA256"]
            if not path.is_file() or file_sha256(path) != expected:
                raise CascadeError(f"{row['generationID']}: input audio is missing or changed")
    return rows


def run_cascade(
    *, manifest: dict[str, Any], cache: DeliveryAnalysisCache, lock_root: Path,
    compact_config: dict[str, Any] | None = None,
    evaluator_model: dict[str, Any] | None = None,
    compact_supervisor_options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    rows = _validate_manifest(manifest)
    output_rows = []
    cache_hits = 0
    cache_misses = 0
    for row in rows:
        per_audio: dict[str, dict[str, Any]] = {}
        for role, field in (("instructed", "instructedWAV"), ("neutral", "neutralWAV")):
            path = Path(row[field])
            canonical = cache.canonicalize(path)
            qc_identity = _identity(
                canonical, layer="pcm-integrity-qc", version="1", source=CASCADE_SOURCE
            )
            qc_report, hit = cache.get_or_compute(
                qc_identity, lambda canonical=canonical: _pcm_integrity_layer(canonical)
            )
            cache_hits += hit; cache_misses += not hit
            global_identity = _identity(canonical, layer="global-acoustics", version="3", source=GLOBAL_ANALYZER)
            global_report, hit = cache.get_or_compute(global_identity, lambda path=path: _global_layer(path))
            cache_hits += hit; cache_misses += not hit
            temporal_identity = _identity(canonical, layer="temporal-contour", version="1", source=TEMPORAL_ANALYZER)
            temporal_report, hit = cache.get_or_compute(temporal_identity, lambda path=path: _temporal_layer(path))
            cache_hits += hit; cache_misses += not hit
            compact_report = None
            compact_hit = None
            if compact_config is not None:
                compact_report, compact_hit = run_compact_adapter(
                    wav_path=path, config=compact_config, cache=cache,
                    lock_root=lock_root,
                    supervisor_options=compact_supervisor_options,
                )
                cache_hits += bool(compact_hit); cache_misses += not bool(compact_hit)
            per_audio[role] = {
                "canonical": canonical.report(),
                "qc": qc_report,
                "global": global_report,
                "temporal": temporal_report,
                "compact": compact_report,
                "compactCacheHit": compact_hit,
            }
        reasons: list[str] = []
        route = "accepted-for-continued-screening"
        if any(
            per_audio[role][layer].get("status") != "complete"
            for role in ("instructed", "neutral") for layer in ("qc", "global", "temporal")
        ):
            route = "rejected"
            reasons.append("deterministic-audio-qc-or-global-analysis-failed")
        global_delta = _numeric_delta(
            per_audio["instructed"]["global"].get("features", {}),
            per_audio["neutral"]["global"].get("features", {}),
        )
        temporal_delta = (
            paired_temporal_delta(
                per_audio["instructed"]["temporal"]["features"],
                per_audio["neutral"]["temporal"]["features"],
            )
            if all(per_audio[role]["temporal"].get("status") == "complete" for role in ("instructed", "neutral"))
            else {"schemaVersion": 1, "kind": "temporal-delta-unavailable"}
        )
        evaluation = None
        if route != "rejected" and evaluator_model is not None:
            flat_features: dict[str, float] = {}
            _flatten_numeric(global_delta, "global", flat_features)
            _flatten_numeric(temporal_delta, "temporal", flat_features)
            expected_features = evaluator_model.get("featureNames", [])
            missing_features = sorted(set(expected_features) - set(flat_features))
            if missing_features:
                raise CascadeError(
                    f"{row['generationID']}: evaluator features unavailable: {missing_features[:3]}"
                )
            flat_features = {name: flat_features[name] for name in expected_features}
            evaluation_payload = {
                "schemaVersion": 2,
                "manifestDigest": hashlib.sha256(
                    (manifest.get("runIdentity", "") + row["generationID"]).encode()
                ).hexdigest(),
                "rows": [{
                    "generationID": row["generationID"],
                    "speakerID": row["speakerID"], "scriptID": row["scriptID"],
                    "scriptTranslationGroup": row["scriptTranslationGroup"],
                    "seed": row["seed"], "outputLanguage": row["outputLanguage"],
                    "preset": row["preset"], "flatFeatureVector": flat_features,
                }],
            }
            evaluation = evaluate_v2(evaluation_payload, evaluator_model)["rows"][0]
        if route != "rejected" and compact_config is None:
            route = "abstained"
            reasons.append("compact-representation-not-qualified-or-configured")
        if route != "rejected" and evaluator_model is None:
            route = "abstained"
            reasons.append("tiny-local-heads-not-calibrated")
        if evaluation is not None and evaluation.get("abstained"):
            route = "routed-to-manual-listening"
            reasons.extend(evaluation.get("abstainReasons", []))
        if evaluation is not None and not evaluation.get("abstained"):
            probability = evaluation.get("pairwise", {}).get("targetAlignedProbability")
            if isinstance(probability, (int, float)) and 0.4 <= probability <= 0.6:
                route = "routed-to-manual-listening"
                reasons.append("pairwise-target-adherence-ambiguous")
        if not reasons:
            reasons.append("all-always-on-layers-complete-and-noncontradictory")
        ambiguous = route in {"abstained", "routed-to-manual-listening"}
        finalist = (
            evaluation is not None and not evaluation.get("abstained")
            and float(evaluation.get("pairwise", {}).get("targetAlignedProbability", 0.0)) >= 0.7
        )
        output_rows.append({
            "generationID": row["generationID"],
            "route": route, "reasons": sorted(set(reasons)),
            "promotionAuthority": False,
            "alwaysLayers": {
                "audioQC": {
                    role: per_audio[role]["qc"] for role in ("instructed", "neutral")
                },
                "globalAcoustics": global_delta,
                "temporalAcoustics": temporal_delta,
                "compactRepresentation": "complete" if compact_config is not None else "unavailable",
                "tinyLocalHeads": evaluation,
            },
            "ambiguousLayers": {
                "required": ambiguous,
                "requested": ["coarse-ser-asr", "extra-identity", "legacy-ser-during-bakeoff"] if ambiguous else [],
            },
            "finalistLayers": {
                "required": finalist,
                "requested": ["utmos", "complete-multilingual-asr-cer", "human-holdout"] if finalist else [],
            },
        })
    return {
        "schemaVersion": SCHEMA_VERSION,
        "kind": "local-delivery-cascade",
        "promotionAuthority": False,
        "inputManifestDigest": manifest["manifestDigest"],
        "cache": {"hits": cache_hits, "misses": cache_misses},
        "rowCount": len(output_rows),
        "rows": output_rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--cache-root", type=Path, default=DEFAULT_CACHE_ROOT)
    parser.add_argument("--lock-root", type=Path, default=DEFAULT_CACHE_ROOT)
    parser.add_argument("--compact-adapter-config", type=Path)
    parser.add_argument("--evaluator-model", type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    try:
        result = run_cascade(
            manifest=build_cascade_manifest(plan_path=args.plan, run_dir=args.run_dir),
            cache=DeliveryAnalysisCache(args.cache_root), lock_root=args.lock_root,
            compact_config=_read(args.compact_adapter_config) if args.compact_adapter_config else None,
            evaluator_model=_read(args.evaluator_model) if args.evaluator_model else None,
        )
        atomic_json(args.out, result)
        print(json.dumps({"status": "PASS", "rows": result["rowCount"], "output": str(args.out)}, indent=2))
        return 0
    except (CascadeError, ValueError, OSError) as error:
        print(f"Local delivery cascade: FAIL\n{error}", file=__import__("sys").stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
