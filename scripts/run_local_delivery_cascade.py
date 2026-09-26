#!/usr/bin/env python3
"""Run the existing delivery harness as a local perceptual cascade.

Always-on deterministic layers are cached by audio bytes and source identity.
Compact neural features are optional until a candidate is fully pinned; when
requested, one persistent worker per run analyzes every clip that survived the
deterministic layers (audit AQ-F42), never one process per clip. Rows are
explicitly accepted for more screening, rejected, or inconclusive. Listening is
optional. Measured screening is not listener-proven semantic improvement.

The fitted tiny local heads (ridge, elastic-net and PLS) and the DistilHuBERT
representation left this QC path on 2026-09-26 (AQ-05; audit sections 4.9 and
7.1): neither has a QC measurand and the heads were never calibrated. The
route is composed by `compose_route` from the deterministic layers, the
automated review and the prosody gate alone; the audio QC orchestrator
(`audio_qc_orchestrator.py`) replays it from cached metrics.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from pathlib import Path
from typing import Any, Callable

import numpy as np

from analyze_prosody import analyze
from delivery_analysis_cache import (
    DeliveryAnalysisCache,
    LayerIdentity,
    NO_MODEL_DIGEST,
    digest,
    file_sha256,
    select_resampler,
    canonicalization_identity,
    SUPPORTED_RESAMPLERS,
)
from delivery_compact_model_adapter import run_compact_adapter_batch
from delivery_evaluator import atomic_json
from delivery_temporal_features import analyze_temporal, paired_temporal_delta
from lib.language_metrics import (
    ACCURACY_METRIC_VERSION,
    consensus as family_consensus,
    recognition_issues,
    score_recognition,
)
from prosody_quality_gate import evaluate_metrics
import delivery_acoustic_reference as acoustic_reference


SCHEMA_VERSION = 1
# The evidence contract shared with `independent_asr.py`. How a recognition is
# scored is recorded beside it as `accuracyMetricVersion` (WER v2 since
# 2026-09-25), since it moves pass/fail without changing the evidence format.
REVIEW_POLICY = "automated-evidence-1"
REPO = Path(__file__).resolve().parents[1]
GLOBAL_ANALYZER = REPO / "scripts/analyze_prosody.py"
TEMPORAL_ANALYZER = REPO / "scripts/delivery_temporal_features.py"
CASCADE_SOURCE = Path(__file__).resolve()
# Layers a row may request beyond the always-on ones. They match the evaluator
# contract's cascade lists; no retired judge (audio QC registry) appears here.
AMBIGUOUS_LAYERS = ("coarse-ser-asr", "extra-identity")
FINALIST_LAYERS = ("complete-multilingual-asr-cer", "automated-untouched-holdout")
DEFAULT_CACHE_ROOT = Path(os.environ.get(
    "QVOICE_DELIVERY_ANALYSIS_CACHE", REPO / "build/cache/delivery-analysis"
))


class CascadeError(ValueError):
    """The cascade input is incomplete, cross-run, or unsafe."""


def review_automated_audio(
    row: dict[str, Any], role: str, duration: float,
    *, scorer: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Compose byte-bound native QC and independent full-file recognitions.

    This consumes retained evidence; it never launches a model or treats an
    absent scorer as PASS. Transcripts are private inputs, never report fields.
    Repetitions of one ASR family are one witness, not independent votes.
    `scorer` replaces `score_recognition` with the same signature and result;
    the audio QC orchestrator passes one that reads cached L2 metrics.
    """
    score = scorer or score_recognition
    all_evidence = row.get("reviewEvidence") or {}
    evidence = all_evidence.get(role, {}) if isinstance(all_evidence, dict) else {}
    if not isinstance(evidence, dict):
        evidence = {}
    expected = row[f"{role}SHA256"]
    reasons: list[str] = []
    qc = evidence.get("audioQC")
    safety = "inconclusive"
    if evidence.get("audioSHA256") != expected:
        reasons.append("missing-or-mismatched-native-qc-audio-binding")
    elif not isinstance(qc, dict) or qc.get("algorithmVersion") != 6:
        reasons.append("current-native-fast-qc-unavailable")
    else:
        verdicts = [qc.get(key) for key in ("verdict", "instabilityVerdict", "writtenOutputVerdict")]
        reported_duration = qc.get("durationSeconds")
        valid = (all(value in ("pass", "warn", "fail") for value in verdicts)
                 and type(reported_duration) in (int, float) and math.isfinite(reported_duration)
                 and abs(reported_duration - duration) <= max(0.001, duration * 0.001)
                 and all(type(qc.get(key)) is int and qc[key] >= 0 for key in
                         ("nonFiniteSamples", "clippedSamples", "hotSamples", "clickEvents",
                          "longestSilenceMS", "trailingSilenceMS"))
                 and isinstance(qc.get("flags"), list)
                 and (qc.get('cadence') is None or isinstance(qc['cadence'], dict)))
        if not valid:
            reasons.append("invalid-native-qc-receipt")
        elif "fail" in verdicts:
            safety = "fail"
            reasons.append("native-fast-qc-failed")
        elif "warn" in verdicts or qc["flags"]:
            reasons.append("native-fast-qc-warning-unresolved")
        elif qc["nonFiniteSamples"] or (qc.get("cadence") or {}).get("classification") == "severe":
            reasons.append("native-fast-qc-receipt-contradiction")
        else:
            safety = "pass"
    recognitions = evidence.get("recognitions", [])
    metrics = []
    families: dict[str, list[bool]] = {}
    language = row["outputLanguage"].lower()
    script = row.get("referenceText")
    if not isinstance(recognitions, list):
        recognitions = []
        reasons.append("invalid-recognition-evidence")
    for recognition in recognitions:
        if not isinstance(recognition, dict):
            reasons.append("invalid-recognition-evidence")
            continue
        if recognition_issues(
            recognition, audio_sha256=expected, script=script,
            script_sha256=row.get("scriptSHA256"), language=language, duration_seconds=duration,
        ):
            reasons.append("unqualified-recognition-evidence")
            continue
        verdict = score(recognition, script=script, language=language)
        families.setdefault(verdict["modelFamily"], []).append(verdict["passed"])
        metrics.append({"modelFamily": verdict["modelFamily"], "metric": verdict["metric"],
                        "accuracyMetricVersion": verdict["accuracyMetricVersion"],
                        "errorRate": verdict["errorRate"], "passed": verdict["passed"],
                        "provenance": recognition["provenance"]})
    agreement = family_consensus(families)
    language_status = agreement["status"]
    reasons.extend(agreement["reasons"])
    if any(reason in reasons for reason in ("unqualified-recognition-evidence", "invalid-recognition-evidence")):
        language_status = "inconclusive"
    status = ("fail" if "fail" in (safety, language_status) else
              "pass" if (safety, language_status) == ("pass", "pass") else "inconclusive")
    return {"policyID": REVIEW_POLICY, "accuracyMetricVersion": ACCURACY_METRIC_VERSION,
            "status": status, "safety": safety,
            "spokenContent": language_status, "recognitions": metrics,
            "independentASRFamilies": len(families), "reasons": sorted(set(reasons)),
            "humanListeningRequired": False, "perceptualQuality": "not-established",
            "audioSHA256": expected}


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
            "sampleRate": canonical.report()["sampleRateHz"] if layer == "pcm-integrity-qc" else "source-native",
            "requestedLabelVisible": False,
            "canonicalizationIdentity": canonicalization_identity(canonical.resampler_version),
            "cacheSourceSHA256": file_sha256(REPO / "scripts/delivery_analysis_cache.py"),
            "sharedAnalyzerSHA256": file_sha256(GLOBAL_ANALYZER),
            "pythonVersion": sys.version, "numpyVersion": np.__version__,
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
        "scope": "canonical-pcm-integrity-only",
        "sampleCount": sample_count,
        "durationSeconds": canonical.duration_seconds,
        "peakAbsolutePCM16": peak,
        "rmsPCM16": math.sqrt(sum_squares / sample_count),
        "clippedSampleFraction": clipped / sample_count,
    }


def _global_layer(path: Path) -> dict[str, Any]:
    report = analyze(str(path))
    if "error" in report:
        return {"status": "rejected", "errorCode": "prosody-analysis-unavailable"}
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


def _compact_delta(
    config: dict[str, Any], instructed: dict[str, Any], neutral: dict[str, Any],
) -> dict[str, Any]:
    adapter_id = config.get("adapterID")
    instructed_output = instructed.get("outputs", {})
    neutral_output = neutral.get("outputs", {})
    features: dict[str, float] = {}
    if adapter_id == "sensevoice-small-q8":
        label_map = config.get("labelMap", {})
        for output_field, labels_key in (
            ("languageTag", "languages"), ("emotionTag", "emotions"),
            ("eventTag", "events"), ("textNormalizationTag", "textNormalization"),
        ):
            labels = label_map.get(labels_key)
            if not isinstance(labels, list):
                raise CascadeError("SenseVoice label map is incomplete")
            for label in labels:
                features[f"{labels_key}.{label}"] = float(
                    (1 if instructed_output.get(output_field) == label else 0)
                    - (1 if neutral_output.get(output_field) == label else 0)
                )
    else:
        raise CascadeError("compact adapter is not recognized by the cascade")
    return {
        "schemaVersion": 1,
        "kind": "compact-instructed-minus-neutral-delta",
        "adapterID": adapter_id,
        "modelID": config.get("modelID"),
        "sourceRevision": config.get("sourceRevision"),
        "weightsSHA256": config.get("weightsSHA256"),
        "preprocessingConfigDigest": config.get("preprocessingConfigDigest"),
        "adapterLayerSHA256": config.get("adapterLayerSHA256"),
        "outputIdentityDigest": config.get("outputIdentityDigest"),
        "featureVector": features,
    }


ROLES = ("instructed", "neutral")
DETERMINISTIC_LAYERS = ("qc", "global", "temporal")


def compose_route(
    per_audio: dict[str, dict[str, Any]], automated: dict[str, dict[str, Any]],
    prosody: dict[str, dict[str, Any]],
) -> tuple[str, list[str]]:
    """One pair's route from its deterministic layers, automated review and prosody gate.

    A failed deterministic layer or a failed review rejects; an incomplete
    review or a prosody warning abstains; otherwise the pair continues to
    screening. Pure: the orchestrator replays it from cached metrics.
    """
    reasons: list[str] = []
    route = "accepted-for-continued-screening"
    if any(per_audio[role][layer].get("status") != "complete" for role in ROLES for layer in DETERMINISTIC_LAYERS):
        route = "rejected"
        reasons.append("deterministic-audio-qc-or-global-analysis-failed")
    if any(value["status"] == "fail" for value in automated.values()):
        route = "rejected"
        reasons.append("byte-bound-native-qc-or-independent-content-failed")
    if route != "rejected" and (any(value["status"] != "pass" for value in automated.values())
                                or any(not value["passed"] for value in prosody.values())):
        route = "abstained"
        reasons.append("automated-quality-evidence-incomplete-or-prosody-warning")
    if not reasons:
        reasons.append("all-always-on-layers-complete-and-noncontradictory")
    return route, sorted(set(reasons))


def build_cascade_manifest(*, plan_path: Path, run_dir: Path, review_evidence: dict[str, Any] | None = None) -> dict[str, Any]:
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
    if any(acoustic_rows[key].get('generationID') != take.get('generationID') for key, take in takes.items()):
        raise CascadeError('cascade acoustic generation identities differ')
    if review_evidence is not None and (
        review_evidence.get("policyID") != REVIEW_POLICY
        or review_evidence.get("executionPlanDigest") != execution_digest
        or not isinstance(review_evidence.get("rows"), dict)
        or set(review_evidence["rows"]) != {take["generationID"] for take in takes.values()}
    ):
        raise CascadeError("automated review evidence must cover the exact run and generations")
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
            "referenceText": row["script"].get("text"),
            "scriptSHA256": row["script"].get("sha256"),
            "reviewEvidence": {
                role: {
                    "audioSHA256": result["audioSHA256"], "audioQC": result.get("audioQC"),
                    "recognitions": (review_evidence or {}).get("rows", {}).get(
                        take["generationID"], {}).get(role, []),
                } for role, result in (("instructed", take), ("neutral", reference))
            },
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
            "reviewEvidenceSHA256": digest(review_evidence),
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
    if (not isinstance(source_digests, dict) or not {
        'retainedPlanSHA256', 'executionStateSHA256', 'acousticLayerSHA256',
        'binarySHA256', 'runnerSHA256', 'analyzerSHA256', 'temporalAnalyzerSHA256',
    } <= set(source_digests) or any(
        not isinstance(value, str) or len(value) != 64 for value in source_digests.values()
    )):
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
    *, manifest: dict[str, Any], cache: DeliveryAnalysisCache, lock_root: Path | None = None,
    compact_config: dict[str, Any] | None = None,
    compact_supervisor_options: dict[str, Any] | None = None,
    reference_audio_dir: Path | None = None,
    compact_runner: Callable[..., Any] = run_compact_adapter_batch,
) -> dict[str, Any]:
    select_resampler(cache.resampler_version, compact_config)
    rows = _validate_manifest(manifest)
    cache_hits = 0
    cache_misses = 0
    reference_base = None
    reference_status = {"status": "unavailable", "promotionAuthority": False}
    try:
        reference_base = acoustic_reference.load_base()
        problem = acoustic_reference.availability(reference_base, cache.resampler_version)
        reference_status.update(baseID=reference_base['id'], manifestSHA256=reference_base['_manifestSHA256'])
        if reference_audio_dir is not None:
            audit = acoustic_reference.verify_originals(reference_base, reference_audio_dir)
            reference_status['originalAudioAudit'] = audit
            if not audit['allMatched']:
                problem = 'reference-original-audio-missing-or-mismatched'
        reference_status.update(status='available' if problem is None else 'unavailable', reason=problem)
    except (ValueError, OSError, KeyError, TypeError):
        # An optional reference cannot manufacture a PASS or block native QC.
        reference_status['reason'] = 'reference-base-missing-invalid-or-drifted'
    # Pass 1: every deterministic layer, review and route, before any neural process.
    screened = []
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
            global_report = {"status": "skipped", "errorCode": "pcm-integrity-rejected"}
            temporal_report = {"status": "skipped", "errorCode": "earlier-deterministic-layer-rejected"}
            if qc_report.get("status") == "complete":
                global_identity = _identity(canonical, layer="global-acoustics", version="3", source=GLOBAL_ANALYZER)
                global_report, hit = cache.get_or_compute(global_identity, lambda path=path: _global_layer(path))
                cache_hits += hit; cache_misses += not hit
            if global_report.get("status") == "complete":
                temporal_identity = _identity(canonical, layer="temporal-contour", version="1", source=TEMPORAL_ANALYZER)
                temporal_report, hit = cache.get_or_compute(temporal_identity, lambda path=path: _temporal_layer(path))
                cache_hits += hit; cache_misses += not hit
            per_audio[role] = {
                "canonical": canonical.report(),
                "qc": qc_report,
                "global": global_report,
                "temporal": temporal_report,
                "compact": None,
                "compactCacheHit": None,
                "referenceFeatures": None,
            }
            if reference_status['status'] == 'available' and global_report.get('status') == 'complete':
                try:
                    features, hit = acoustic_reference.extract_canonical(canonical, cache, reference_base)
                    per_audio[role]['referenceFeatures'] = features
                    cache_hits += hit; cache_misses += not hit
                except (ValueError, OSError, KeyError):
                    pass  # Explicit unavailable comparison below; never change quality routing.
        automated = {role: review_automated_audio(row, role, per_audio[role]["canonical"]["durationSeconds"])
                     for role in ROLES}
        # Advisory features are not trained perceptual truth. Report them without
        # duplicating extraction or weakening native QC to match a proxy.
        prosody = {role: evaluate_metrics(per_audio[role]["global"].get("features", {}))
                   for role in ROLES}
        for report in prosody.values():
            report.pop("clip", None)
        route, reasons = compose_route(per_audio, automated, prosody)
        screened.append((row, per_audio, automated, prosody, route, reasons))
    # Pass 2: one persistent compact worker for the run. Both sides of a pair
    # qualify before any neural process: a rejected neutral control invalidates
    # the pair just as a rejected take does, and no rejected pair is analyzed.
    compact_payloads: dict[str, tuple[dict[str, Any], bool]] = {}
    if compact_config is not None:
        wavs = []
        for row, _per_audio, _automated, _prosody, route, _reasons in screened:
            if route != "rejected":
                wavs.extend(Path(row[field]) for field in ("instructedWAV", "neutralWAV"))
        unique = list(dict.fromkeys(wavs))
        if unique:
            results = compact_runner(
                wav_paths=unique, config=compact_config, cache=cache, lock_root=lock_root,
                supervisor_options=compact_supervisor_options,
            )
            compact_payloads = {str(path): value for path, value in results.items()}
    output_rows = []
    for row, per_audio, automated, prosody, route, reasons in screened:
        compact_delta = None
        if route != "rejected" and compact_config is not None:
            for role, field in (("instructed", "instructedWAV"), ("neutral", "neutralWAV")):
                compact_report, compact_hit = compact_payloads[str(Path(row[field]))]
                per_audio[role]["compact"] = compact_report
                per_audio[role]["compactCacheHit"] = compact_hit
                cache_hits += bool(compact_hit); cache_misses += not bool(compact_hit)
            compact_delta = _compact_delta(
                compact_config, per_audio["instructed"]["compact"], per_audio["neutral"]["compact"],
            )
        global_delta = _numeric_delta(
            per_audio["instructed"]["global"].get("features", {}),
            per_audio["neutral"]["global"].get("features", {}),
        )
        temporal_delta = (
            paired_temporal_delta(
                per_audio["instructed"]["temporal"]["features"],
                per_audio["neutral"]["temporal"]["features"],
            )
            if all(per_audio[role]["temporal"].get("status") == "complete" for role in ROLES)
            else {"schemaVersion": 1, "kind": "temporal-delta-unavailable"}
        )
        ambiguous = route == "abstained"
        reference_comparison = {**reference_status, 'status': 'unavailable'}
        if reference_status['status'] == 'available':
            if all(per_audio[role]['referenceFeatures'] is not None for role in ROLES):
                reference_comparison = acoustic_reference.compare(
                    reference_base, preset=row['preset'], language=row['outputLanguage'],
                    instructed=per_audio['instructed']['referenceFeatures'],
                    neutral=per_audio['neutral']['referenceFeatures'])
                reference_comparison['inputAudio'] = {role: per_audio[role]['canonical'] for role in ROLES}
                reference_comparison['featureRuntime'] = {'pythonVersion': sys.version,
                                                          'numpyVersion': np.__version__}
            else:
                reference_comparison['reason'] = 'canonical-reference-features-unavailable'
        output_rows.append({
            "generationID": row["generationID"],
            "route": route, "reasons": reasons,
            "promotionAuthority": False,
            "automatedReview": automated,
            "advisoryProsody": prosody,
            # No semantic-delivery measurand remains in this path: the fitted
            # heads that estimated it were uncalibrated and left QC (AQ-05).
            "semanticDelivery": "unmeasured",
            "humanListeningRequired": False,
            "acousticReference": reference_comparison,
            "alwaysLayers": {
                "audioQC": {role: per_audio[role]["qc"] for role in ROLES},
                "globalAcoustics": global_delta,
                "temporalAcoustics": temporal_delta,
                "compactRepresentation": compact_delta if compact_delta is not None else "unavailable",
            },
            "ambiguousLayers": {
                "required": ambiguous,
                "requested": list(AMBIGUOUS_LAYERS) if ambiguous else [],
            },
            # Finalists were the heads' confident target-aligned pairs; with no
            # qualified delivery detector (class H, AQ-08) no pair is one.
            "finalistLayers": {"required": False, "requested": []},
        })
    report = {
        "schemaVersion": SCHEMA_VERSION,
        "kind": "local-delivery-cascade",
        "reviewPolicyID": REVIEW_POLICY,
        "accuracyMetricVersion": ACCURACY_METRIC_VERSION,
        "humanListeningRequired": False,
        "promotionAuthority": False,
        "inputManifestDigest": manifest["manifestDigest"],
        "composerSHA256": file_sha256(CASCADE_SOURCE),
        "reviewDependencies": {name: file_sha256(REPO / 'scripts' / name) for name in
                               ('check_language_output.py', 'lib/language_metrics.py',
                                'prosody_quality_gate.py', 'prosody_profile.py')},
        "canonicalizationIdentity": canonicalization_identity(cache.resampler_version),
        "acousticReferenceBase": reference_status,
        "acousticReferenceComparatorSHA256": file_sha256(Path(acoustic_reference.__file__)),
        "cache": {"hits": cache_hits, "misses": cache_misses},
        "rowCount": len(output_rows),
        "reviewCounts": {route: sum(row['route'] == route for row in output_rows) for route in
                         ('accepted-for-continued-screening', 'rejected', 'abstained')},
        "rows": output_rows,
    }
    report["reportDigest"] = digest(report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--cache-root", type=Path, default=DEFAULT_CACHE_ROOT)
    parser.add_argument("--compact-adapter-config", type=Path)
    parser.add_argument("--review-evidence", type=Path, help="untracked, run-bound full-file ASR receipts; never listener responses")
    parser.add_argument("--resampler", choices=SUPPORTED_RESAMPLERS)
    parser.add_argument("--reference-audio-dir", type=Path,
                        help="optional original-reference hash audit; no download or model launch")
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    try:
        compact = _read(args.compact_adapter_config) if args.compact_adapter_config else None
        resampler = select_resampler(args.resampler, compact)
        result = run_cascade(
            manifest=build_cascade_manifest(plan_path=args.plan, run_dir=args.run_dir,
                                           review_evidence=_read(args.review_evidence) if args.review_evidence else None),
            # The host-wide analysis lock, never one beside the cache root.
            cache=DeliveryAnalysisCache(args.cache_root, resampler_version=resampler),
            compact_config=compact,
            reference_audio_dir=args.reference_audio_dir,
        )
        atomic_json(args.out, result)
        print(json.dumps({"status": "COMPLETED", "rows": result["rowCount"],
                          "reviewCounts": result.get('reviewCounts'),
                          "promotionAuthority": False, "output": str(args.out)}, indent=2))
        return 0
    except (CascadeError, ValueError, OSError) as error:
        print(f"Local delivery cascade: FAIL\n{error}", file=__import__("sys").stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
