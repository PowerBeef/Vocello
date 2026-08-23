#!/usr/bin/env python3
"""Build, run, and merge blinded dimensional delivery-calibration sessions.

The public session exposes randomized audio and output language only. Requested
preset, speaker, script, seed, prompt arm, and acoustic features remain in a
private key that the interactive listener path never prints. Three independent
listeners and fluent coverage for every output language are required before a
merged dataset can qualify for evaluator calibration.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import random
import shutil
import statistics
import subprocess
import tempfile
from typing import Any


SCHEMA_VERSION = 1
DIMENSIONS = ("valence", "arousal", "dominance")
MINIMUM_LISTENERS = 3
MINIMUM_SPEAKERS = 3
MINIMUM_SCRIPTS = 3
MINIMUM_ROWS = 20
MINIMUM_MEAN_PAIRWISE_CCC = 0.60


class CalibrationSessionError(ValueError):
    """A calibration session is incomplete, unblinded, or cross-run."""


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


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


def _read(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise CalibrationSessionError(f"cannot load {path}: {error}") from error
    if not isinstance(value, dict):
        raise CalibrationSessionError(f"{path} must contain a JSON object")
    return value


def _validated_session(session_dir: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    manifest = _read(session_dir / "manifest.json")
    private_key = _read(session_dir / "private-key.json")
    if manifest.get("schemaVersion") != SCHEMA_VERSION:
        raise CalibrationSessionError("session manifest schemaVersion is invalid")
    stored = manifest.get("sessionDigest")
    body = dict(manifest)
    body.pop("sessionDigest", None)
    if stored != digest(body):
        raise CalibrationSessionError("session manifest digest mismatch")
    if private_key.get("sessionDigest") != stored:
        raise CalibrationSessionError("private key is not bound to the session")
    private_digest = private_key.get("privateKeyDigest")
    private_body = dict(private_key)
    private_body.pop("sessionDigest", None)
    private_body.pop("privateKeyDigest", None)
    if (
        not isinstance(private_digest, str)
        or private_digest != digest(private_body)
        or manifest.get("privateKeyDigest") != private_digest
    ):
        raise CalibrationSessionError("private calibration key changed")
    if private_key.get("executionPlanDigest") != manifest.get("executionPlanDigest"):
        raise CalibrationSessionError("private key and session execution identities differ")
    public_ids = [row.get("itemID") for row in manifest.get("items", [])]
    private_ids = [row.get("itemID") for row in private_key.get("items", [])]
    if len(public_ids) != len(set(public_ids)) or set(public_ids) != set(private_ids):
        raise CalibrationSessionError("public and private session identities differ")
    return manifest, private_key


def build_session(
    *, plan_path: Path, run_dir: Path, out_dir: Path, session_seed: int,
) -> dict[str, Any]:
    plan = _read(plan_path)
    state = _read(run_dir / "execution-state.json")
    acoustic = _read(run_dir / "acoustic-layer.json")
    if plan.get("designation") != "calibration":
        raise CalibrationSessionError("calibration labels require the calibration split")
    execution_digest = plan.get("executionPlanDigest")
    if state.get("executionPlanDigest") != execution_digest:
        raise CalibrationSessionError("state and plan identities differ")
    if acoustic.get("manifestDigest") != execution_digest:
        raise CalibrationSessionError("acoustic layer and plan identities differ")
    acoustic_by_generation = {
        row["generationID"]: row for row in acoustic.get("rows", [])
        if isinstance(row, dict) and isinstance(row.get("generationID"), str)
    }
    rows_by_take = {row["takeID"]: row for row in plan.get("rows", [])}
    if not rows_by_take or len(rows_by_take) != len(plan.get("rows", [])):
        raise CalibrationSessionError("calibration plan has missing or duplicate take identities")
    state_takes = state.get("takes")
    if not isinstance(state_takes, dict) or set(state_takes) != set(rows_by_take):
        raise CalibrationSessionError("calibration run does not cover the exact planned rows")
    incomplete = sorted(
        take_id for take_id, result in state_takes.items()
        if not isinstance(result, dict) or result.get("status") != "complete"
    )
    if incomplete:
        raise CalibrationSessionError(
            f"calibration run retains {len(incomplete)} incomplete or failed rows"
        )
    candidates: list[dict[str, Any]] = []
    used_generations: set[str] = set()
    for take_id, result in sorted(state_takes.items()):
        plan_row = rows_by_take.get(take_id)
        generation_id = result.get("generationID")
        acoustic_row = acoustic_by_generation.get(generation_id)
        source_audio = run_dir / result.get("audio", "")
        if plan_row is None or acoustic_row is None or not source_audio.is_file():
            raise CalibrationSessionError(f"{take_id}: incomplete calibration evidence")
        if generation_id in used_generations:
            raise CalibrationSessionError("calibration run reuses a generation identity")
        used_generations.add(generation_id)
        if file_sha256(source_audio) != result.get("audioSHA256"):
            raise CalibrationSessionError(f"{take_id}: calibration audio digest mismatch")
        item_id = digest({
            "sessionSeed": session_seed,
            "generationID": generation_id,
            "audioSHA256": result.get("audioSHA256"),
        })[:24]
        candidates.append({
            "itemID": item_id,
            "generationID": generation_id,
            "sourceAudio": source_audio,
            "audioSHA256": result.get("audioSHA256"),
            "speakerID": plan_row["speakerID"],
            "scriptID": plan_row["script"]["scriptID"],
            "outputLanguage": plan_row["outputLanguage"],
            "preset": plan_row["preset"],
            "seed": plan_row["seed"],
            "features": acoustic_row["features"],
        })
    if not candidates:
        raise CalibrationSessionError("calibration session has no complete analyzed rows")
    random.Random(session_seed).shuffle(candidates)
    clips_dir = out_dir / "clips"
    clips_dir.mkdir(parents=True, exist_ok=True)
    public_items = []
    private_items = []
    for order, row in enumerate(candidates):
        relative = Path("clips") / f"{row['itemID']}.wav"
        destination = out_dir / relative
        if destination.exists():
            if file_sha256(destination) != row["audioSHA256"]:
                raise CalibrationSessionError(f"retained clip {row['itemID']} changed")
        else:
            try:
                os.link(row["sourceAudio"], destination)
            except OSError:
                shutil.copy2(row["sourceAudio"], destination)
        public_items.append({
            "itemID": row["itemID"], "order": order,
            "clip": str(relative), "audioSHA256": row["audioSHA256"],
            "outputLanguage": row["outputLanguage"],
        })
        private_items.append({
            key: value for key, value in row.items() if key != "sourceAudio"
        })
    private_body = {
        "schemaVersion": SCHEMA_VERSION,
        "executionPlanDigest": execution_digest,
        "featureNames": acoustic["featureNames"],
        "items": private_items,
    }
    private_digest = digest(private_body)
    manifest = {
        "schemaVersion": SCHEMA_VERSION,
        "kind": "blinded-delivery-dimensional-calibration",
        "promotionAuthority": False,
        "executionPlanDigest": execution_digest,
        "privateKeyDigest": private_digest,
        "sessionSeed": session_seed,
        "ratingScale": {
            "minimum": -1.0, "maximum": 1.0,
            "dimensions": list(DIMENSIONS),
            "anchors": {
                "valence": {"-1": "very negative", "0": "neutral", "1": "very positive"},
                "arousal": {"-1": "very subdued", "0": "moderate", "1": "very activated"},
                "dominance": {"-1": "very yielding", "0": "balanced", "1": "very commanding"},
            },
        },
        "items": public_items,
    }
    manifest["sessionDigest"] = digest(manifest)
    private_key = {
        **private_body,
        "sessionDigest": manifest["sessionDigest"],
        "privateKeyDigest": private_digest,
    }
    atomic_json(out_dir / "manifest.json", manifest)
    atomic_json(out_dir / "private-key.json", private_key)
    return manifest


def _rating(prompt: str) -> float:
    while True:
        raw = input(prompt).strip()
        try:
            value = float(raw)
        except ValueError:
            print("Enter a number from -1 to 1.")
            continue
        if math.isfinite(value) and -1.0 <= value <= 1.0:
            return value
        print("Enter a finite number from -1 to 1.")


def run_session(
    *, session_dir: Path, listener_id: str, fluent_languages: tuple[str, ...],
    player: str = "/usr/bin/afplay",
) -> dict[str, Any]:
    manifest, _ = _validated_session(session_dir)
    if not listener_id.strip() or not fluent_languages:
        raise CalibrationSessionError("listener ID and fluent languages are required")
    listener_digest = hashlib.sha256(listener_id.strip().encode("utf-8")).hexdigest()
    ratings = []
    print("Rate only what you hear. Requested presets and speaker identity are hidden.")
    for index, item in enumerate(manifest["items"], start=1):
        clip = session_dir / item["clip"]
        if not clip.is_file() or file_sha256(clip) != item["audioSHA256"]:
            raise CalibrationSessionError(f"session clip {item['itemID']} is missing or changed")
        print(f"\nClip {index}/{len(manifest['items'])} — {item['outputLanguage']}")
        result = subprocess.run([player, str(clip)], check=False)
        if result.returncode != 0:
            raise CalibrationSessionError(f"audio player exited {result.returncode}")
        ratings.append({
            "itemID": item["itemID"],
            "valence": _rating("Valence [-1 negative, 0 neutral, 1 positive]: "),
            "arousal": _rating("Arousal [-1 subdued, 0 moderate, 1 activated]: "),
            "dominance": _rating("Dominance [-1 yielding, 0 balanced, 1 commanding]: "),
        })
    response = {
        "schemaVersion": SCHEMA_VERSION,
        "sessionDigest": manifest["sessionDigest"],
        "listenerDigest": listener_digest,
        "fluentLanguages": sorted(set(fluent_languages)),
        "ratings": ratings,
    }
    response["responseDigest"] = digest(response)
    atomic_json(session_dir / "responses" / f"{listener_digest[:16]}.json", response)
    return response


def _ccc(left: list[float], right: list[float]) -> float | None:
    if len(left) != len(right) or len(left) < 2:
        return None
    left_mean = statistics.fmean(left)
    right_mean = statistics.fmean(right)
    covariance = statistics.fmean(
        (x - left_mean) * (y - right_mean) for x, y in zip(left, right)
    )
    left_variance = statistics.fmean((x - left_mean) ** 2 for x in left)
    right_variance = statistics.fmean((y - right_mean) ** 2 for y in right)
    denominator = left_variance + right_variance + (left_mean - right_mean) ** 2
    return (2.0 * covariance / denominator) if denominator > 0 else None


def merge_responses(*, session_dir: Path) -> dict[str, Any]:
    manifest, private_key = _validated_session(session_dir)
    response_paths = sorted((session_dir / "responses").glob("*.json"))
    responses = [_read(path) for path in response_paths]
    public_ids = [row["itemID"] for row in manifest["items"]]
    listener_ids: set[str] = set()
    normalized = []
    for response in responses:
        stored = response.get("responseDigest")
        body = dict(response)
        body.pop("responseDigest", None)
        if stored != digest(body) or response.get("sessionDigest") != manifest["sessionDigest"]:
            raise CalibrationSessionError("response digest or session identity is invalid")
        listener = response.get("listenerDigest")
        if not isinstance(listener, str) or listener in listener_ids:
            raise CalibrationSessionError("listener identities are missing or duplicated")
        listener_ids.add(listener)
        ratings = response.get("ratings")
        if not isinstance(ratings, list) or [row.get("itemID") for row in ratings] != public_ids:
            raise CalibrationSessionError("response rows do not cover the blinded session order")
        for row in ratings:
            for dimension in DIMENSIONS:
                value = row.get(dimension)
                if (
                    isinstance(value, bool) or not isinstance(value, (int, float))
                    or not math.isfinite(float(value)) or not -1.0 <= float(value) <= 1.0
                ):
                    raise CalibrationSessionError("response contains an invalid dimensional rating")
        normalized.append(response)
    ratings_by_listener = {
        response["listenerDigest"]: {
            row["itemID"]: row for row in response["ratings"]
        }
        for response in normalized
    }
    pairwise: dict[str, list[float]] = {dimension: [] for dimension in DIMENSIONS}
    listeners = sorted(ratings_by_listener)
    for left_index, left in enumerate(listeners):
        for right in listeners[left_index + 1:]:
            for dimension in DIMENSIONS:
                score = _ccc(
                    [ratings_by_listener[left][item][dimension] for item in public_ids],
                    [ratings_by_listener[right][item][dimension] for item in public_ids],
                )
                if score is not None:
                    pairwise[dimension].append(score)
    agreement = {
        dimension: {
            "pairCount": len(scores),
            "meanPairwiseCCC": statistics.fmean(scores) if scores else None,
            "minimumPairwiseCCC": min(scores) if scores else None,
        }
        for dimension, scores in pairwise.items()
    }
    languages = sorted({row["outputLanguage"] for row in manifest["items"]})
    fluent_coverage = {
        language: sum(language in response.get("fluentLanguages", []) for response in normalized)
        for language in languages
    }
    private_by_id = {row["itemID"]: row for row in private_key["items"]}
    dataset_rows = []
    for item_id in public_ids:
        source = private_by_id[item_id]
        dataset_rows.append({
            "generationID": source["generationID"],
            "speakerID": source["speakerID"],
            "scriptID": source["scriptID"],
            "features": source["features"],
            "labels": {
                dimension: statistics.median(
                    ratings_by_listener[listener][item_id][dimension]
                    for listener in listeners
                )
                for dimension in DIMENSIONS
            },
        })
    failures = []
    if len(listeners) < MINIMUM_LISTENERS:
        failures.append("fewer-than-three-independent-listeners")
    if any(count < 1 for count in fluent_coverage.values()):
        failures.append("missing-fluent-language-coverage")
    if len(dataset_rows) < MINIMUM_ROWS:
        failures.append("insufficient-labeled-rows")
    if len({row["speakerID"] for row in dataset_rows}) < MINIMUM_SPEAKERS:
        failures.append("insufficient-speaker-groups")
    if len({row["scriptID"] for row in dataset_rows}) < MINIMUM_SCRIPTS:
        failures.append("insufficient-script-groups")
    if any(
        value["meanPairwiseCCC"] is None
        or value["meanPairwiseCCC"] < MINIMUM_MEAN_PAIRWISE_CCC
        for value in agreement.values()
    ):
        failures.append("human-agreement-below-calibration-floor")
    expected_pairs = len(listeners) * (len(listeners) - 1) // 2
    if any(value["pairCount"] != expected_pairs for value in agreement.values()):
        failures.append("human-agreement-pairs-incomplete")
    response_digests = sorted(response["responseDigest"] for response in normalized)
    manifest_digest = digest({
        "sessionDigest": manifest["sessionDigest"],
        "responseDigests": response_digests,
        "featureNames": private_key["featureNames"],
    })
    return {
        "schemaVersion": SCHEMA_VERSION,
        "manifestDigest": manifest_digest,
        "featureNames": private_key["featureNames"],
        "rows": dataset_rows,
        "labelProvenance": {
            "kind": "blinded-independent-listener-median",
            "sourceSplit": "calibration",
            "targetLabelsVisibleToListeners": False,
            "sessionDigest": manifest["sessionDigest"],
            "listenerCount": len(listeners),
            "responseDigests": response_digests,
            "fluentLanguageCoverage": fluent_coverage,
            "agreement": agreement,
            "qualificationFailures": failures,
            "calibrationQualified": not failures,
        },
    }


def _parse_languages(raw: str) -> tuple[str, ...]:
    values = tuple(item.strip() for item in raw.split(",") if item.strip())
    if not values:
        raise CalibrationSessionError("at least one fluent language is required")
    return values


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("build")
    build.add_argument("--plan", required=True, type=Path)
    build.add_argument("--run-dir", required=True, type=Path)
    build.add_argument("--out", required=True, type=Path)
    build.add_argument("--session-seed", required=True, type=int)
    run = commands.add_parser("run")
    run.add_argument("--session", required=True, type=Path)
    run.add_argument("--listener-id", required=True)
    run.add_argument("--fluent-languages", required=True)
    run.add_argument("--player", default="/usr/bin/afplay")
    merge = commands.add_parser("merge")
    merge.add_argument("--session", required=True, type=Path)
    merge.add_argument("--out", required=True, type=Path)
    build_v2 = commands.add_parser("build-v2")
    build_v2.add_argument("--plan", required=True, type=Path)
    build_v2.add_argument("--run-dir", required=True, type=Path)
    build_v2.add_argument("--baseline-run-dir", type=Path)
    build_v2.add_argument("--anchors", type=Path)
    build_v2.add_argument("--out", required=True, type=Path)
    build_v2.add_argument("--session-seed", required=True, type=int)
    run_v2 = commands.add_parser("run-v2")
    run_v2.add_argument("--session", required=True, type=Path)
    run_v2.add_argument("--listener-id", required=True)
    run_v2.add_argument("--fluent-languages", required=True)
    run_v2.add_argument("--player", default="/usr/bin/afplay")
    merge_v2 = commands.add_parser("merge-v2")
    merge_v2.add_argument("--session", required=True, type=Path)
    merge_v2.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    try:
        if args.command in {"build-v2", "run-v2", "merge-v2"}:
            from delivery_listener_calibration_v2 import (
                build_v2_session, merge_v2_responses, run_v2_session,
            )
            if args.command == "build-v2":
                result = build_v2_session(
                    plan_path=args.plan, run_dir=args.run_dir,
                    baseline_run_dir=args.baseline_run_dir,
                    anchor_manifest_path=args.anchors,
                    out_dir=args.out, session_seed=args.session_seed,
                )
            elif args.command == "run-v2":
                result = run_v2_session(
                    session_dir=args.session, listener_id=args.listener_id,
                    fluent_languages=_parse_languages(args.fluent_languages),
                    player=args.player,
                )
            else:
                result = merge_v2_responses(session_dir=args.session)
                atomic_json(args.out, result)
        elif args.command == "build":
            result = build_session(
                plan_path=args.plan, run_dir=args.run_dir, out_dir=args.out,
                session_seed=args.session_seed,
            )
        elif args.command == "run":
            result = run_session(
                session_dir=args.session, listener_id=args.listener_id,
                fluent_languages=_parse_languages(args.fluent_languages),
                player=args.player,
            )
        else:
            result = merge_responses(session_dir=args.session)
            atomic_json(args.out, result)
        qualified = result.get("labelProvenance", {}).get("calibrationQualified")
        print(json.dumps({
            "status": "PASS" if qualified is not False else "INCOMPLETE",
            "rows": len(result.get("rows", result.get("items", result.get("ratings", [])))),
            "qualified": qualified,
        }, indent=2))
        return 0 if qualified is not False else 2
    except CalibrationSessionError as error:
        print(f"Delivery calibration session: FAIL\n{error}", file=__import__("sys").stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
