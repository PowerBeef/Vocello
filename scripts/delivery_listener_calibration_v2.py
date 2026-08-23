#!/usr/bin/env python3
"""Versioned perceptual calibration extension for delivery_calibration_session.

This module is deliberately invoked by the existing calibration entry point.
It keeps dimensional trials label-blind, creates target-vs-neutral and optional
candidate-vs-baseline pairs, gives each listener an independent deterministic
order, injects exact repeats, and retains listener-level responses locally.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import random
import shutil
import statistics
import subprocess
import time
from typing import Any

from delivery_calibration_session import (
    CalibrationSessionError,
    atomic_json,
    digest,
    file_sha256,
)


SCHEMA_VERSION = 2
DIMENSIONS = ("valence", "arousal", "dominance")
PRESETS = ("neutral", "happy", "sad", "angry", "fearful", "surprised", "calm", "whisper")
REPEAT_FRACTION = 0.125
MIN_LISTENERS = 3
MIN_SPEAKERS = 6
MIN_SCRIPTS = 3
MIN_PRESETS = 8
MIN_PAIRWISE_CCC = 0.60


def _read(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise CalibrationSessionError(f"cannot load {path}: {error}") from error
    if not isinstance(value, dict):
        raise CalibrationSessionError(f"{path.name} must contain an object")
    return value


def _copy_bound(source: Path, destination: Path, expected_digest: str) -> None:
    if not source.is_file() or file_sha256(source) != expected_digest:
        raise CalibrationSessionError("v2 source audio is missing or changed")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        if file_sha256(destination) != expected_digest:
            raise CalibrationSessionError("retained v2 session audio changed")
        return
    try:
        os.link(source, destination)
    except OSError:
        shutil.copy2(source, destination)


def _collect_run(plan: dict[str, Any], run_dir: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    state = _read(run_dir / "execution-state.json")
    acoustic = _read(run_dir / "acoustic-layer.json")
    execution_digest = plan.get("executionPlanDigest")
    if state.get("executionPlanDigest") != execution_digest or acoustic.get("manifestDigest") != execution_digest:
        raise CalibrationSessionError("v2 plan, state, and acoustic identities differ")
    plan_rows = {row.get("takeID"): row for row in plan.get("rows", []) if isinstance(row, dict)}
    takes = state.get("takes")
    if not plan_rows or not isinstance(takes, dict) or set(takes) != set(plan_rows):
        raise CalibrationSessionError("v2 session requires exact planned-row coverage")
    if any(not isinstance(row, dict) or row.get("status") != "complete" for row in takes.values()):
        raise CalibrationSessionError("v2 session retains failed or incomplete rows")
    acoustic_rows = {
        row.get("generationID"): row for row in acoustic.get("rows", []) if isinstance(row, dict)
    }
    results: list[dict[str, Any]] = []
    for take_id, take in sorted(takes.items()):
        row = plan_rows[take_id]
        reference = state.get("references", {}).get(take.get("referenceKey"), {})
        analyzed = acoustic_rows.get(take.get("generationID"))
        instructed = run_dir / str(take.get("audio", ""))
        neutral = run_dir / str(reference.get("audio", ""))
        if reference.get("status") != "complete" or analyzed is None:
            raise CalibrationSessionError("v2 session lacks a complete paired reference or analysis")
        if file_sha256(instructed) != take.get("audioSHA256") or file_sha256(neutral) != reference.get("audioSHA256"):
            raise CalibrationSessionError("v2 session audio digest mismatch")
        results.append({
            "takeID": take_id,
            "generationID": take["generationID"],
            "speakerID": row["speakerID"],
            "scriptID": row["script"]["scriptID"],
            "scriptTranslationGroup": row["script"].get("translationGroup", row["script"]["scriptID"]),
            "seed": row["seed"],
            "outputLanguage": row["outputLanguage"],
            "preset": row["preset"],
            "features": analyzed["features"],
            "temporalDeltaV1": analyzed.get("temporalDeltaV1"),
            "instructedPath": instructed,
            "instructedSHA256": take["audioSHA256"],
            "neutralPath": neutral,
            "neutralSHA256": reference["audioSHA256"],
        })
    return results, acoustic


def build_v2_session(
    *, plan_path: Path, run_dir: Path, out_dir: Path, session_seed: int,
    baseline_run_dir: Path | None = None,
    anchor_manifest_path: Path | None = None,
) -> dict[str, Any]:
    plan = _read(plan_path)
    if plan.get("designation") != "calibration":
        raise CalibrationSessionError("v2 perceptual labels require the calibration split")
    rows, acoustic = _collect_run(plan, run_dir)
    baseline_rows: dict[str, dict[str, Any]] = {}
    if baseline_run_dir is not None:
        baseline, _ = _collect_run(plan, baseline_run_dir)
        baseline_rows = {row["takeID"]: row for row in baseline}
    clips = out_dir / "clips"
    public_dimensional: list[dict[str, Any]] = []
    public_pairs: list[dict[str, Any]] = []
    private_rows: list[dict[str, Any]] = []
    for row in rows:
        opaque = digest({
            "sessionSeed": session_seed,
            "generationID": row["generationID"],
            "instructedSHA256": row["instructedSHA256"],
        })[:24]
        instructed_clip = digest({"opaque": opaque, "slot": "x"})[:24]
        neutral_clip = digest({"opaque": opaque, "slot": "y"})[:24]
        instructed_relative = Path("clips") / f"{instructed_clip}.wav"
        neutral_relative = Path("clips") / f"{neutral_clip}.wav"
        _copy_bound(row["instructedPath"], out_dir / instructed_relative, row["instructedSHA256"])
        _copy_bound(row["neutralPath"], out_dir / neutral_relative, row["neutralSHA256"])
        dimensional_id = digest({"opaque": opaque, "task": "dimensional"})[:24]
        pair_id = digest({"opaque": opaque, "task": "target-neutral"})[:24]
        # Requested preset is intentionally absent from this public block.
        public_dimensional.append({
            "trialID": dimensional_id,
            "clipID": instructed_clip,
            "clip": str(instructed_relative),
            "audioSHA256": row["instructedSHA256"],
            "outputLanguage": row["outputLanguage"],
            "task": "dimensional-naturalness-intensity-free-identification",
        })
        public_pairs.append({
            "trialID": pair_id,
            "task": "target-versus-neutral-2afc",
            "targetDelivery": row["preset"],
            "outputLanguage": row["outputLanguage"],
            "clipIDs": [instructed_clip, neutral_clip],
        })
        private = {
            key: value for key, value in row.items()
            if key not in {"instructedPath", "neutralPath"}
        }
        private.update({
            "dimensionalTrialID": dimensional_id,
            "targetNeutralTrialID": pair_id,
            "instructedClipID": instructed_clip,
            "neutralClipID": neutral_clip,
        })
        if row["takeID"] in baseline_rows:
            baseline = baseline_rows[row["takeID"]]
            baseline_clip = digest({"opaque": opaque, "slot": "baseline"})[:24]
            baseline_relative = Path("clips") / f"{baseline_clip}.wav"
            _copy_bound(baseline["instructedPath"], out_dir / baseline_relative, baseline["instructedSHA256"])
            candidate_pair_id = digest({"opaque": opaque, "task": "candidate-baseline"})[:24]
            public_pairs.append({
                "trialID": candidate_pair_id,
                "task": "candidate-versus-baseline-2afc",
                "targetDelivery": row["preset"],
                "outputLanguage": row["outputLanguage"],
                "clipIDs": [instructed_clip, baseline_clip],
            })
            private["candidateBaselineTrialID"] = candidate_pair_id
            private["baselineClipID"] = baseline_clip
            private["baselineSHA256"] = baseline["instructedSHA256"]
        private_rows.append(private)
    private_body = {
        "schemaVersion": SCHEMA_VERSION,
        "executionPlanDigest": plan["executionPlanDigest"],
        "featureNames": acoustic["featureNames"],
        "items": private_rows,
    }
    public_anchors: list[dict[str, Any]] = []
    private_anchors: list[dict[str, Any]] = []
    if anchor_manifest_path is not None:
        anchor_manifest = _read(anchor_manifest_path)
        if anchor_manifest.get("schemaVersion") != 1 or not isinstance(anchor_manifest.get("anchors"), list):
            raise CalibrationSessionError("v2 anchor manifest schema is invalid")
        for index, anchor in enumerate(anchor_manifest["anchors"]):
            if not isinstance(anchor, dict):
                raise CalibrationSessionError("v2 anchor rows must be objects")
            expected_source = Path(str(anchor.get("expectedPath", "")))
            comparison_source = Path(str(anchor.get("comparisonPath", "")))
            expected_digest = str(anchor.get("expectedSHA256", ""))
            comparison_digest = str(anchor.get("comparisonSHA256", ""))
            anchor_id = digest({
                "sessionSeed": session_seed, "anchorIndex": index,
                "expectedSHA256": expected_digest, "comparisonSHA256": comparison_digest,
            })[:24]
            expected_clip = digest({"anchor": anchor_id, "slot": "x"})[:24]
            comparison_clip = digest({"anchor": anchor_id, "slot": "y"})[:24]
            _copy_bound(expected_source, clips / f"{expected_clip}.wav", expected_digest)
            _copy_bound(comparison_source, clips / f"{comparison_clip}.wav", comparison_digest)
            public_anchors.append({
                "trialID": anchor_id,
                "task": "anchor-2afc",
                "anchorPrompt": str(anchor.get("prompt", "Select the clearer delivery match")),
                "outputLanguage": str(anchor.get("outputLanguage", "Unknown")),
                "clipIDs": [expected_clip, comparison_clip],
            })
            private_anchors.append({
                "trialID": anchor_id,
                "expectedClipID": expected_clip,
                "expectedSHA256": expected_digest,
                "comparisonClipID": comparison_clip,
                "comparisonSHA256": comparison_digest,
            })
    private_body["anchors"] = private_anchors
    private_digest = digest(private_body)
    manifest = {
        "schemaVersion": SCHEMA_VERSION,
        "kind": "blinded-delivery-perceptual-calibration-v2",
        "promotionAuthority": False,
        "executionPlanDigest": plan["executionPlanDigest"],
        "privateKeyDigest": private_digest,
        "sessionSeed": session_seed,
        "repeatFraction": REPEAT_FRACTION,
        "anchors": public_anchors,
        "dimensionalTrials": public_dimensional,
        "pairwiseTrials": public_pairs,
        "responseFields": [
            "uncertain", "confidence", "replayCount", "responseLatencyMilliseconds",
            "freeIdentification", "valence", "arousal", "dominance",
            "naturalness", "perceivedIntensity", "choice",
        ],
        "requestedLabelVisibleInDimensionalBlock": False,
    }
    manifest["sessionDigest"] = digest(manifest)
    private = {
        **private_body,
        "sessionDigest": manifest["sessionDigest"],
        "privateKeyDigest": private_digest,
    }
    atomic_json(out_dir / "manifest.json", manifest)
    atomic_json(out_dir / "private-key.json", private)
    return manifest


def validate_v2_session(session_dir: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    manifest = _read(session_dir / "manifest.json")
    private = _read(session_dir / "private-key.json")
    if manifest.get("schemaVersion") != SCHEMA_VERSION or private.get("schemaVersion") != SCHEMA_VERSION:
        raise CalibrationSessionError("v2 session schema is invalid")
    body = dict(manifest)
    stored = body.pop("sessionDigest", None)
    if stored != digest(body) or private.get("sessionDigest") != stored:
        raise CalibrationSessionError("v2 session digest mismatch")
    private_body = dict(private)
    private_digest = private_body.pop("privateKeyDigest", None)
    private_body.pop("sessionDigest", None)
    if private_digest != digest(private_body) or manifest.get("privateKeyDigest") != private_digest:
        raise CalibrationSessionError("v2 private key changed")
    dimensional_text = json.dumps(manifest.get("dimensionalTrials", []), sort_keys=True)
    for forbidden in ("targetDelivery", "preset", "speakerID", "scriptID", "seed"):
        if forbidden in dimensional_text:
            raise CalibrationSessionError("requested metadata leaked into v2 dimensional trials")
    return manifest, private


def listener_trial_plan(manifest: dict[str, Any], listener_digest: str) -> list[dict[str, Any]]:
    if not isinstance(listener_digest, str) or len(listener_digest) != 64:
        raise CalibrationSessionError("v2 listener digest must be SHA-256")
    trials = [dict(row) for row in manifest.get("dimensionalTrials", []) + manifest.get("pairwiseTrials", []) + manifest.get("anchors", [])]
    if not trials:
        raise CalibrationSessionError("v2 session has no trials")
    rng = random.Random(int(digest({
        "sessionDigest": manifest["sessionDigest"], "listenerDigest": listener_digest,
    })[:16], 16))
    for trial in trials:
        if "clipIDs" in trial and rng.random() < 0.5:
            trial["clipIDs"] = list(reversed(trial["clipIDs"]))
        trial["presentationID"] = digest({
            "listener": listener_digest, "trial": trial["trialID"], "repeat": 0,
        })[:24]
    repeat_count = max(1, int(round(len(trials) * REPEAT_FRACTION)))
    repeat_sources = rng.sample(trials, min(repeat_count, len(trials)))
    for repeat_index, source in enumerate(repeat_sources, start=1):
        repeated = dict(source)
        repeated["repeatOfTrialID"] = source["trialID"]
        repeated["presentationID"] = digest({
            "listener": listener_digest, "trial": source["trialID"], "repeat": repeat_index,
        })[:24]
        trials.append(repeated)
    rng.shuffle(trials)
    return trials


def _bounded_float(prompt: str, minimum: float, maximum: float, *, allow_uncertain: bool = False) -> float | None:
    while True:
        raw = input(prompt).strip().lower()
        if allow_uncertain and raw in {"u", "uncertain"}:
            return None
        try:
            value = float(raw)
        except ValueError:
            print(f"Enter {minimum}..{maximum}" + (" or u" if allow_uncertain else "") + ".")
            continue
        if math.isfinite(value) and minimum <= value <= maximum:
            return value


def run_v2_session(
    *, session_dir: Path, listener_id: str, fluent_languages: tuple[str, ...],
    player: str = "/usr/bin/afplay",
) -> dict[str, Any]:
    manifest, _ = validate_v2_session(session_dir)
    if not listener_id.strip() or not fluent_languages:
        raise CalibrationSessionError("v2 listener ID and fluent languages are required")
    listener_digest = hashlib.sha256(listener_id.strip().encode()).hexdigest()
    plan = listener_trial_plan(manifest, listener_digest)
    clip_by_id = {
        row["clipID"]: row for row in manifest.get("dimensionalTrials", [])
    }
    # Pair clips not used by dimensional tasks are still present below clips/;
    # bind IDs to their exact private digest before playback.
    _manifest, private = validate_v2_session(session_dir)
    private_clips: dict[str, str] = {}
    for row in private["items"]:
        private_clips[row["instructedClipID"]] = row["instructedSHA256"]
        private_clips[row["neutralClipID"]] = row["neutralSHA256"]
        if row.get("baselineClipID"):
            private_clips[row["baselineClipID"]] = row["baselineSHA256"]
    for anchor in private.get("anchors", []):
        private_clips[anchor["expectedClipID"]] = anchor["expectedSHA256"]
        private_clips[anchor["comparisonClipID"]] = anchor["comparisonSHA256"]
    responses = []
    for index, trial in enumerate(plan, start=1):
        started = time.monotonic()
        replay_count = 0
        clip_ids = [trial["clipID"]] if "clipID" in trial else trial.get("clipIDs", [])
        for slot, clip_id in enumerate(clip_ids, start=1):
            public = clip_by_id.get(clip_id)
            clip = session_dir / (public["clip"] if public else f"clips/{clip_id}.wav")
            expected = public["audioSHA256"] if public else private_clips.get(clip_id)
            if not clip.is_file() or not expected or file_sha256(clip) != expected:
                raise CalibrationSessionError("v2 playback clip is missing or changed")
            print(f"\nTrial {index}/{len(plan)} clip {slot}/{len(clip_ids)}")
            result = subprocess.run([player, str(clip)], check=False)
            if result.returncode != 0:
                raise CalibrationSessionError("v2 audio player failed")
            replay_count += 1
        response: dict[str, Any] = {
            "presentationID": trial["presentationID"],
            "trialID": trial["trialID"],
            "repeatOfTrialID": trial.get("repeatOfTrialID"),
            "task": trial["task"],
            "replayCount": replay_count,
        }
        if trial["task"].startswith("dimensional"):
            values = {
                dimension: _bounded_float(f"{dimension} [-1..1 or u]: ", -1, 1, allow_uncertain=True)
                for dimension in DIMENSIONS
            }
            response.update(values)
            response["uncertain"] = any(value is None for value in values.values())
            response["freeIdentification"] = input("Delivery ID [8 presets or uncertain]: ").strip().lower()
            response["naturalness"] = _bounded_float("Naturalness [1..5]: ", 1, 5)
            response["perceivedIntensity"] = _bounded_float("Intensity [1..5]: ", 1, 5)
        else:
            choice = input("More aligned [A/B/u]: ").strip().upper()
            response["choice"] = choice if choice in {"A", "B"} else "uncertain"
            response["uncertain"] = response["choice"] == "uncertain"
        response["confidence"] = _bounded_float("Confidence [1..5]: ", 1, 5)
        response["responseLatencyMilliseconds"] = int((time.monotonic() - started) * 1000)
        responses.append(response)
    body = {
        "schemaVersion": SCHEMA_VERSION,
        "sessionDigest": manifest["sessionDigest"],
        "listenerDigest": listener_digest,
        "fluentLanguages": sorted(set(fluent_languages)),
        "trialOrderDigest": digest(plan),
        "responses": responses,
    }
    body["responseDigest"] = digest(body)
    atomic_json(session_dir / "responses-v2" / f"{listener_digest[:16]}.json", body)
    return body


def _ccc(left: list[float], right: list[float]) -> float | None:
    if len(left) != len(right) or len(left) < 2:
        return None
    left_mean, right_mean = statistics.fmean(left), statistics.fmean(right)
    covariance = statistics.fmean((a - left_mean) * (b - right_mean) for a, b in zip(left, right))
    denominator = statistics.pvariance(left) + statistics.pvariance(right) + (left_mean - right_mean) ** 2
    return 2 * covariance / denominator if denominator > 0 else None


def _response_signature(row: dict[str, Any]) -> tuple[Any, ...]:
    if row["task"].startswith("dimensional"):
        return tuple(row.get(name) for name in (*DIMENSIONS, "freeIdentification"))
    return (row.get("choice"),)


def _validate_response_row(row: dict[str, Any], trial: dict[str, Any]) -> None:
    if not isinstance(row, dict) or row.get("task") != trial.get("task"):
        raise CalibrationSessionError("v2 response task identity changed")
    for field in ("replayCount", "responseLatencyMilliseconds"):
        value = row.get(field)
        if isinstance(value, bool) or not isinstance(value, int) or value < (1 if field == "replayCount" else 0):
            raise CalibrationSessionError(f"v2 response has invalid {field}")
    confidence = row.get("confidence")
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not 1 <= float(confidence) <= 5:
        raise CalibrationSessionError("v2 response confidence must lie in [1, 5]")
    if not isinstance(row.get("uncertain"), bool):
        raise CalibrationSessionError("v2 response uncertain flag is required")
    if trial["task"].startswith("dimensional"):
        for dimension in DIMENSIONS:
            value = row.get(dimension)
            if value is None and row["uncertain"]:
                continue
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)) or not -1 <= float(value) <= 1:
                raise CalibrationSessionError("v2 dimensional response is invalid")
        identification = row.get("freeIdentification")
        if identification not in set(PRESETS) | {"uncertain"}:
            raise CalibrationSessionError("v2 free-identification response is invalid")
        for field in ("naturalness", "perceivedIntensity"):
            value = row.get(field)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not 1 <= float(value) <= 5:
                raise CalibrationSessionError(f"v2 {field} must lie in [1, 5]")
    elif row.get("choice") not in {"A", "B", "uncertain"}:
        raise CalibrationSessionError("v2 pairwise choice must be A, B, or uncertain")


def merge_v2_responses(*, session_dir: Path) -> dict[str, Any]:
    manifest, private = validate_v2_session(session_dir)
    responses = [_read(path) for path in sorted((session_dir / "responses-v2").glob("*.json"))]
    listeners: dict[str, dict[str, Any]] = {}
    for response in responses:
        body = dict(response)
        stored = body.pop("responseDigest", None)
        if stored != digest(body) or response.get("sessionDigest") != manifest["sessionDigest"]:
            raise CalibrationSessionError("v2 response digest or session identity is invalid")
        listener = response.get("listenerDigest")
        if not isinstance(listener, str) or listener in listeners:
            raise CalibrationSessionError("v2 listener identities are missing or duplicated")
        plan = listener_trial_plan(manifest, listener)
        rows = response.get("responses")
        if not isinstance(rows, list) or [row.get("presentationID") for row in rows] != [row["presentationID"] for row in plan]:
            raise CalibrationSessionError("v2 response does not cover its deterministic listener order")
        for row, trial in zip(rows, plan):
            _validate_response_row(row, trial)
        if response.get("trialOrderDigest") != digest(plan):
            raise CalibrationSessionError("v2 listener order digest mismatch")
        listeners[listener] = response

    by_listener_trial: dict[str, dict[str, list[dict[str, Any]]]] = {}
    presented_by_listener: dict[str, dict[str, dict[str, Any]]] = {}
    repeat_scores: dict[str, float | None] = {}
    for listener, response in listeners.items():
        listener_plan = listener_trial_plan(manifest, listener)
        presented_by_listener[listener] = {}
        for trial in listener_plan:
            if trial.get("repeatOfTrialID") is None:
                presented_by_listener[listener][trial["trialID"]] = trial
        grouped: dict[str, list[dict[str, Any]]] = {}
        for row in response["responses"]:
            grouped.setdefault(row["trialID"], []).append(row)
        by_listener_trial[listener] = grouped
        repeated = [rows for rows in grouped.values() if len(rows) > 1]
        repeat_scores[listener] = (
            statistics.fmean(_response_signature(rows[0]) == _response_signature(rows[1]) for rows in repeated)
            if repeated else None
        )

    dimensional_ids = [row["trialID"] for row in manifest["dimensionalTrials"]]
    agreement: dict[str, dict[str, Any]] = {}
    listener_ids = sorted(listeners)
    for dimension in DIMENSIONS:
        scores = []
        for left_index, left in enumerate(listener_ids):
            for right in listener_ids[left_index + 1:]:
                left_values, right_values = [], []
                for trial_id in dimensional_ids:
                    a = by_listener_trial[left][trial_id][0].get(dimension)
                    b = by_listener_trial[right][trial_id][0].get(dimension)
                    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
                        left_values.append(float(a)); right_values.append(float(b))
                score = _ccc(left_values, right_values)
                if score is not None:
                    scores.append(score)
        agreement[dimension] = {
            "pairCount": len(scores),
            "meanPairwiseCCC": statistics.fmean(scores) if scores else None,
        }

    unique_rows = [row for response in listeners.values() for row in response["responses"] if row.get("repeatOfTrialID") is None]
    uncertain_rate = (
        sum(row.get("uncertain") is True for row in unique_rows) / len(unique_rows)
        if unique_rows else None
    )
    pair_rows = [row for row in unique_rows if "2afc" in row.get("task", "")]
    decided_pairs = [row for row in pair_rows if row.get("choice") in {"A", "B"}]
    order_bias = {
        "aChoiceRate": sum(row["choice"] == "A" for row in decided_pairs) / len(decided_pairs) if decided_pairs else None,
        "decidedCount": len(decided_pairs),
    }
    languages = sorted({row["outputLanguage"] for row in manifest["dimensionalTrials"]})
    fluent_coverage = {
        language: sum(language in response.get("fluentLanguages", []) for response in listeners.values())
        for language in languages
    }
    free_identification_agreement = None
    if len(listener_ids) >= 2 and dimensional_ids:
        agreements = []
        for trial_id in dimensional_ids:
            values = [by_listener_trial[listener][trial_id][0].get("freeIdentification") for listener in listener_ids]
            for left_index, left in enumerate(values):
                for right in values[left_index + 1:]:
                    agreements.append(left == right)
        free_identification_agreement = statistics.fmean(agreements) if agreements else None

    private_by_dimensional = {row["dimensionalTrialID"]: row for row in private["items"]}
    private_by_pair = {row["targetNeutralTrialID"]: row for row in private["items"]}
    dataset_rows = []
    for trial_id in dimensional_ids:
        source = private_by_dimensional[trial_id]
        dimension_values = {
            dimension: [
                by_listener_trial[listener][trial_id][0].get(dimension)
                for listener in listener_ids
            ]
            for dimension in DIMENSIONS
        }
        pair_id = source["targetNeutralTrialID"]
        preferences = []
        for listener in listener_ids:
            response = by_listener_trial[listener][pair_id][0]
            choice = response.get("choice")
            if choice in {"A", "B"}:
                presented = presented_by_listener[listener][pair_id]
                chosen_clip = presented["clipIDs"][0 if choice == "A" else 1]
                preferences.append(1.0 if chosen_clip == source["instructedClipID"] else 0.0)
        candidate_preferences = []
        candidate_pair_id = source.get("candidateBaselineTrialID")
        if candidate_pair_id:
            for listener in listener_ids:
                response = by_listener_trial[listener][candidate_pair_id][0]
                if response.get("choice") in {"A", "B"}:
                    presented = presented_by_listener[listener][candidate_pair_id]
                    chosen_clip = presented["clipIDs"][0 if response["choice"] == "A" else 1]
                    candidate_preferences.append(1.0 if chosen_clip == source["instructedClipID"] else 0.0)
        dimensional_responses = [by_listener_trial[listener][trial_id][0] for listener in listener_ids]
        dataset_rows.append({
            "generationID": source["generationID"],
            "speakerID": source["speakerID"],
            "scriptID": source["scriptID"],
            "scriptTranslationGroup": source["scriptTranslationGroup"],
            "seed": source["seed"],
            "outputLanguage": source["outputLanguage"],
            "preset": source["preset"],
            "features": source["features"],
            "temporalDeltaV1": source.get("temporalDeltaV1"),
            "labels": {
                dimension: statistics.median(float(value) for value in values if isinstance(value, (int, float)))
                if any(isinstance(value, (int, float)) for value in values) else None
                for dimension, values in dimension_values.items()
            },
            "targetPreference": statistics.fmean(preferences) if preferences else None,
            "candidatePreference": statistics.fmean(candidate_preferences) if candidate_preferences else None,
            "naturalness": statistics.median(float(row["naturalness"]) for row in dimensional_responses),
            "perceivedIntensity": statistics.median(float(row["perceivedIntensity"]) for row in dimensional_responses),
        })
    failures = []
    if len(listener_ids) < MIN_LISTENERS:
        failures.append("fewer-than-three-independent-listeners")
    if len({row["speakerID"] for row in dataset_rows}) < MIN_SPEAKERS:
        failures.append("fewer-than-six-speakers")
    if len({row["scriptID"] for row in dataset_rows}) < MIN_SCRIPTS:
        failures.append("fewer-than-three-scripts")
    if len({row["preset"] for row in dataset_rows}) < MIN_PRESETS:
        failures.append("fewer-than-eight-presets")
    if not manifest.get("anchors"):
        failures.append("anchors-not-configured")
    if any(count < 1 for count in fluent_coverage.values()):
        failures.append("missing-fluent-language-coverage")
    if any(value["meanPairwiseCCC"] is None or value["meanPairwiseCCC"] < MIN_PAIRWISE_CCC for value in agreement.values()):
        failures.append("human-agreement-below-calibration-floor")
    anchor_scores = []
    private_anchor_by_id = {row["trialID"]: row for row in private.get("anchors", [])}
    for listener in listener_ids:
        for trial_id, anchor in private_anchor_by_id.items():
            response = by_listener_trial[listener][trial_id][0]
            if response.get("choice") not in {"A", "B"}:
                continue
            presented = presented_by_listener[listener][trial_id]
            chosen = presented["clipIDs"][0 if response["choice"] == "A" else 1]
            anchor_scores.append(chosen == anchor["expectedClipID"])
    anchor_accuracy = statistics.fmean(anchor_scores) if anchor_scores else None
    report = {
        "schemaVersion": SCHEMA_VERSION,
        "kind": "blinded-delivery-perceptual-labels-v2",
        "manifestDigest": digest({
            "sessionDigest": manifest["sessionDigest"],
            "responses": sorted(response["responseDigest"] for response in listeners.values()),
        }),
        "featureNames": private["featureNames"],
        "rows": dataset_rows,
        "listenerRows": [listeners[listener] for listener in listener_ids],
        "labelProvenance": {
            "kind": "blinded-independent-listener-perceptual-v2",
            "sourceSplit": "calibration",
            "targetLabelsVisibleToDimensionalListeners": False,
            "listenerCount": len(listener_ids),
            "responseDigests": sorted(response["responseDigest"] for response in listeners.values()),
            "intraRaterRepeatAgreement": repeat_scores,
            "agreement": agreement,
            "freeIdentificationAgreement": free_identification_agreement,
            "anchorAccuracy": anchor_accuracy,
            "orderBias": order_bias,
            "uncertainRate": uncertain_rate,
            "fluentLanguageCoverage": fluent_coverage,
            "qualificationFailures": failures,
            "calibrationQualified": not failures,
        },
    }
    return report
