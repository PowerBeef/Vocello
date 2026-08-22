#!/usr/bin/env python3
"""Analyze only the current ``vocello bench --delivery`` run's WAVs.

The immutable ``bench-results.json`` manifest is mandatory: it selects the exact
delivery and neutral outputs from the current run, even when ``outputs/bench``
also contains files from older ``--keep`` runs. The resulting sidecar is written
before the telemetry summary so the current summary and history record include
the same prosody evidence.

Each sidecar row also carries prompt provenance (2026-08-04 delivery-control
audit, hardening item 2): the run seed, the exact instruction string the bench
sent (``instructEcho``), and the engine's own ``promptChars``/``promptDigest``
notes for the take and its paired neutral. The instructed prompt must be
strictly longer than the neutral prompt — the end-to-end proof that the
instruction reached the engine — and the analysis fails closed when that or
any provenance field cannot be established.

Usage:
    scripts/bench_delivery_prosody.py <diagnostics_dir> \
        --results-manifest <run-artifact-dir>/bench-results.json

Output:
    <diagnostics_dir>/bench-prosody.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from delivery_quality_gate import evaluate_delivery
from prosody_profile import builtin_profile, delivery_weight, load_profile
from prosody_quality_gate import evaluate_metrics


def analyze(path: str) -> dict[str, Any]:
    """Load the optional NumPy analyzer only when signal analysis is requested."""
    from analyze_prosody import analyze as analyze_wav

    return analyze_wav(path)


def parse_filename(name: str) -> dict[str, Any] | None:
    """Parse ``<mode>_<modelID>_<len>_<stateToken>_<n>.wav``."""
    if not name.endswith(".wav"):
        return None
    match = re.match(
        r"^(custom|design|clone)_(.+?)_(short|medium|long)_(warm|cold|warm_d-[^_]+)_(\d+)\.wav$",
        name,
    )
    if not match:
        return None
    mode, model, length, state_token, repetition = match.groups()
    delivery = None
    state = state_token
    if state_token.startswith("warm_d-"):
        state = "warm"
        delivery = state_token[len("warm_d-") :]
    return {
        "mode": mode,
        "model": model,
        "length": length,
        "state": state,
        "delivery": delivery,
        "n": int(repetition),
        "name": name,
    }


def collect_run_outputs(
    bench_dir: Path, results_manifest: Path
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Resolve and validate the exact output set named by one run manifest."""
    try:
        manifest = json.loads(results_manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid results manifest {results_manifest}: {error}") from error
    if not isinstance(manifest, dict) or manifest.get("schemaVersion") != 1:
        raise ValueError("results manifest must be a schema-v1 object")
    run_id = manifest.get("runID")
    custom_speaker_id = manifest.get("customSpeakerID")
    if custom_speaker_id is not None and (
        not isinstance(custom_speaker_id, str) or not custom_speaker_id.strip()
    ):
        raise ValueError("results manifest has an invalid customSpeakerID")
    takes = manifest.get("takes")
    reference_failures = manifest.get("referenceFailures", [])
    failures = manifest.get("deliveryFailures", [])
    if not isinstance(run_id, str) or not run_id:
        raise ValueError("results manifest has no runID")
    if not isinstance(takes, list) or not takes:
        raise ValueError("results manifest has no takes")
    if not isinstance(failures, list):
        raise ValueError("results manifest deliveryFailures must be an array")
    if not isinstance(reference_failures, list):
        raise ValueError("results manifest referenceFailures must be an array")

    parsed_outputs: list[dict[str, Any]] = []
    names: set[str] = set()
    generation_ids: set[str] = set()
    attempt_indices: set[int] = set()
    for take in takes:
        index = take.get("takeIndex") if isinstance(take, dict) else None
        if not isinstance(index, int) or isinstance(index, bool) or index < 1:
            raise ValueError("results manifest take indices must be positive integers")
        if index in attempt_indices:
            raise ValueError(f"results manifest repeats attempt index {index}")
        attempt_indices.add(index)
        name = take.get("outputFileName")
        generation_id = take.get("generationID")
        if (
            not isinstance(name, str)
            or not name
            or Path(name).name != name
            or name in names
        ):
            raise ValueError(f"take {index} has an invalid or duplicate output filename")
        if not isinstance(generation_id, str) or not generation_id or generation_id in generation_ids:
            raise ValueError(f"take {index} has an invalid or duplicate generation ID")
        parsed = parse_filename(name)
        if parsed is None:
            raise ValueError(f"take {index} output filename does not match the bench contract: {name}")
        expected = {
            "mode": take.get("mode"),
            "model": take.get("modelID"),
            "length": take.get("length"),
            "state": take.get("warmState"),
            "delivery": take.get("delivery"),
            "n": take.get("repetition"),
        }
        mismatches = [key for key, value in expected.items() if parsed[key] != value]
        if mismatches:
            raise ValueError(
                f"take {index} output filename disagrees with manifest fields: {', '.join(mismatches)}"
            )
        output_path = bench_dir / name
        if not output_path.is_file():
            raise ValueError(f"current run output is missing: {name}")
        parsed["path"] = str(output_path)
        parsed["generationID"] = generation_id
        parsed["deliveryInstruction"] = take.get("deliveryInstruction")
        parsed["speakerID"] = custom_speaker_id if parsed["mode"] == "custom" else None
        parsed_outputs.append(parsed)
        names.add(name)
        generation_ids.add(generation_id)

    allowed_reasons = {
        "fast_qc_dropout",
        "fast_qc_failure",
        "cancelled",
        "generation_token_limit",
        "generation_failed",
    }
    for failure in reference_failures:
        index = failure.get("takeIndex") if isinstance(failure, dict) else None
        if not isinstance(index, int) or isinstance(index, bool) or index < 1:
            raise ValueError("reference failure indices must be positive integers")
        if index in attempt_indices:
            raise ValueError(f"results manifest repeats attempt index {index}")
        attempt_indices.add(index)
        generation_id = failure.get("generationID")
        if (
            not isinstance(generation_id, str)
            or not generation_id
            or generation_id in generation_ids
        ):
            raise ValueError(f"reference failure {index} has an invalid generation ID")
        generation_ids.add(generation_id)
        if failure.get("reasonCode") not in allowed_reasons:
            raise ValueError(f"reference failure {index} has an invalid reason code")
        digest = failure.get("errorDigest")
        if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
            raise ValueError(f"reference failure {index} has an invalid errorDigest")
        name = failure.get("rejectedOutputFileName")
        if (
            not isinstance(name, str)
            or not name
            or Path(name).name != name
            or name in names
        ):
            raise ValueError(f"reference failure {index} has no unique rejected WAV")
        output_path = bench_dir / name
        if not output_path.is_file():
            raise ValueError(f"reference failure {index} rejected WAV is missing: {name}")
        quality_flags = failure.get("qualityFlags")
        if not isinstance(quality_flags, list) or any(
            not isinstance(flag, str) or not flag for flag in quality_flags
        ):
            raise ValueError(f"reference failure {index} has invalid qualityFlags")
        parsed_outputs.append({
            "name": name,
            "path": str(output_path),
            "generationID": generation_id,
            "mode": failure.get("mode"),
            "model": failure.get("modelID"),
            "length": failure.get("length"),
            "state": failure.get("warmState"),
            "n": failure.get("repetition"),
            "delivery": None,
            "deliveryInstruction": None,
            "speakerID": custom_speaker_id if failure.get("mode") == "custom" else None,
            "referenceRejected": True,
            "referenceQualityFlags": quality_flags,
        })
        names.add(name)
    for failure in failures:
        index = failure.get("takeIndex") if isinstance(failure, dict) else None
        if not isinstance(index, int) or isinstance(index, bool) or index < 1:
            raise ValueError("delivery failure indices must be positive integers")
        if index in attempt_indices:
            raise ValueError(f"results manifest repeats attempt index {index}")
        attempt_indices.add(index)
        generation_id = failure.get("generationID")
        if (
            not isinstance(generation_id, str)
            or not generation_id
            or generation_id in generation_ids
        ):
            raise ValueError(f"delivery failure {index} has an invalid generation ID")
        generation_ids.add(generation_id)
        if failure.get("reasonCode") not in allowed_reasons:
            raise ValueError(f"delivery failure {index} has an invalid reason code")
        if not isinstance(failure.get("delivery"), str) or not failure["delivery"]:
            raise ValueError(f"delivery failure {index} has no delivery id")
        for key in ("deliveryInstructionDigest", "errorDigest"):
            digest = failure.get(key)
            if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
                raise ValueError(f"delivery failure {index} has an invalid {key}")

    if sorted(attempt_indices) != list(range(1, len(attempt_indices) + 1)):
        raise ValueError(
            "results manifest attempt indices must be contiguous and one-based across takes and failures"
        )
    return manifest, parsed_outputs


def load_engine_provenance(diagnostics_dir: Path, run_id: str) -> dict[str, dict[str, Any]]:
    """Per-generation prompt provenance from the engine's own telemetry rows.

    The engine stamps every row with the character count and digest of the
    input script (``notes.promptChars`` / ``notes.promptDigest`` — the script
    text, which never includes the delivery instruction), the observed
    sampling seed, and — when the request payload carried a delivery
    instruction — the instruction receipt (``notes.instructChars`` /
    ``notes.instructDigest``). Joining the receipt back to the bench
    manifest's instruction echo is what lets the sidecar prove, from evidence
    alone, that a delivery cell's instruction actually entered the engine
    request. Fail-closed: a missing rows file or a row without
    ``promptChars`` is a provenance gap, not a soft degradation.
    """
    rows_path = diagnostics_dir / "engine" / "generations.jsonl"
    if not rows_path.is_file():
        raise ValueError(f"engine telemetry rows not found: {rows_path}")
    provenance: dict[str, dict[str, Any]] = {}
    with rows_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            notes = row.get("notes") or {}
            if notes.get("benchRunID") != run_id:
                continue
            generation_id = row.get("generationID")
            if not isinstance(generation_id, str) or not generation_id:
                continue
            try:
                chars = int(notes.get("promptChars"))
            except (TypeError, ValueError):
                raise ValueError(
                    f"engine row {generation_id} carries no promptChars note; "
                    "prompt provenance cannot be established"
                ) from None
            entry: dict[str, Any] = {"promptChars": chars}
            digest = notes.get("promptDigest")
            if isinstance(digest, str) and digest:
                entry["promptDigest"] = digest
            instruct_digest = notes.get("instructDigest")
            if isinstance(instruct_digest, str) and instruct_digest:
                entry["instructDigest"] = instruct_digest
            try:
                entry["instructChars"] = int(notes.get("instructChars"))
            except (TypeError, ValueError):
                pass
            seed = notes.get("samplingObservedSeed") or notes.get("samplingSeed")
            if isinstance(seed, str) and seed.isdigit():
                entry["seed"] = int(seed)
            elif isinstance(seed, int) and not isinstance(seed, bool):
                entry["seed"] = seed
            provenance[generation_id] = entry
    return provenance


def find_neutral(parsed: list[dict[str, Any]], target: dict[str, Any]) -> dict[str, Any] | None:
    """Find the closest neutral reference within the selected current run."""
    same_length = [
        item
        for item in parsed
        if item["delivery"] is None
        and item["mode"] == target["mode"]
        and item["model"] == target["model"]
        and item.get("speakerID") == target.get("speakerID")
        and item["length"] == target["length"]
        and item["state"] == target["state"]
    ]
    candidates = same_length or [
        item
        for item in parsed
        if item["delivery"] is None
        and item["mode"] == target["mode"]
        and item["model"] == target["model"]
        and item.get("speakerID") == target.get("speakerID")
        and item["state"] == target["state"]
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda item: (abs(item["n"] - target["n"]), item["n"]))
    return candidates[0]


def prosody_effect(metrics: dict[str, float], profile: dict[str, Any] | None = None) -> float:
    """Replicate the signed effect score from ``delivery_adherence.py``."""
    resolved = profile if profile is not None else builtin_profile()
    return (
        metrics["f0_std_hz"] / delivery_weight(resolved, "prosody_effect", "f0_std_divisor")
        + metrics["rate_cv"] / delivery_weight(resolved, "prosody_effect", "rate_cv_divisor")
        - metrics["pause_ratio"] / delivery_weight(resolved, "prosody_effect", "pause_ratio_divisor")
        + metrics["energy_roughness"]
        / delivery_weight(resolved, "prosody_effect", "energy_roughness_divisor")
    )


def analyze_run(
    diagnostics_dir: Path,
    results_manifest: Path,
    profile: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    bench_dir = diagnostics_dir.parent / "outputs" / "bench"
    if not bench_dir.is_dir():
        raise ValueError(f"bench outputs dir not found: {bench_dir}")
    manifest, parsed = collect_run_outputs(bench_dir, results_manifest)
    run_id = manifest["runID"]
    deliveries = [item for item in parsed if item["delivery"]]
    if not deliveries:
        raise ValueError("current results manifest contains no delivery takes")

    # Structural pairing first, so a missing neutral surfaces before any IO.
    pairs = []
    for delivery in deliveries:
        neutral = find_neutral(parsed, delivery)
        if neutral is None:
            raise ValueError(f"current run has no neutral reference for {delivery['name']}")
        pairs.append((delivery, neutral))

    provenance = load_engine_provenance(diagnostics_dir, run_id)

    resolved_profile = profile if profile is not None else builtin_profile()
    profile_digest = hashlib.sha256(
        json.dumps(
            resolved_profile,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("utf-8")
    ).hexdigest()

    results: list[dict[str, Any]] = []
    for delivery, neutral in pairs:
        instructed_provenance = provenance.get(delivery["generationID"])
        neutral_provenance = provenance.get(neutral["generationID"])
        if instructed_provenance is None or neutral_provenance is None:
            raise ValueError(
                f"no engine telemetry row for {delivery['name']} or its neutral pair; "
                "prompt provenance cannot be established"
            )
        # The end-to-end plumbing proof (v2, DP-18): the engine stamps an
        # instruction receipt (length + digest of the payload's delivery
        # instruction) on every instructed row. The instructed take must carry
        # a receipt, its digest must match the manifest's instruction echo when
        # both exist, and the paired neutral reference must carry none — an
        # instruction on the reference would poison every delta. The previous
        # guard compared promptChars, but that counts only the script text
        # (identical across the pair by design), so it could never pass live.
        instruct_echo = delivery.get("deliveryInstruction")
        if instruct_echo is not None and not str(instruct_echo).strip():
            raise ValueError(
                f"{delivery['name']}: manifest carries an empty deliveryInstruction"
            )
        receipt_chars = instructed_provenance.get("instructChars")
        if not isinstance(receipt_chars, int) or receipt_chars <= 0:
            raise ValueError(
                f"{delivery['name']}: engine row carries no delivery-instruction "
                "receipt (instructChars); the delivery instruction did not reach "
                "the engine"
            )
        receipt_digest = instructed_provenance.get("instructDigest")
        if instruct_echo is not None and receipt_digest is not None:
            echo_digest = hashlib.sha256(str(instruct_echo).encode("utf-8")).hexdigest()
            if echo_digest != receipt_digest:
                raise ValueError(
                    f"{delivery['name']}: engine instruction receipt does not match "
                    "the manifest's deliveryInstruction echo; a different "
                    "instruction reached the engine"
                )
        if neutral_provenance.get("instructChars"):
            raise ValueError(
                f"{delivery['name']}: the paired neutral reference carries a "
                "delivery-instruction receipt; the reference is not neutral"
            )
        instructed_metrics = analyze(delivery["path"])
        neutral_metrics = analyze(neutral["path"])
        if "error" in instructed_metrics or "error" in neutral_metrics:
            raise ValueError(f"prosody analysis failed for current output {delivery['name']}")
        results.append(
            {
                "runID": run_id,
                "runLabel": manifest.get("label"),
                "seed": instructed_provenance.get("seed", manifest.get("seed")),
                "instructEcho": instruct_echo,
                "promptChars": instructed_provenance["promptChars"],
                "neutralPromptChars": neutral_provenance["promptChars"],
                "promptDigest": instructed_provenance.get("promptDigest"),
                "neutralPromptDigest": neutral_provenance.get("promptDigest"),
                "generationID": delivery["generationID"],
                "neutralGenerationID": neutral["generationID"],
                "neutralReferenceAccepted": not neutral.get("referenceRejected", False),
                "neutralReferenceQualityFlags": list(
                    neutral.get("referenceQualityFlags") or []
                ),
                "mode": delivery["mode"],
                "model": delivery["model"],
                "speakerID": delivery.get("speakerID"),
                "length": delivery["length"],
                "delivery": delivery["delivery"],
                "profileDigest": profile_digest,
                "deliveryWav": delivery["name"],
                "neutralWav": neutral["name"],
                "durationSec": instructed_metrics["durationSec"],
                "dF0Std": round(instructed_metrics["f0_std_hz"] - neutral_metrics["f0_std_hz"], 2),
                "dRateCV": round(instructed_metrics["rate_cv"] - neutral_metrics["rate_cv"], 3),
                "dPauseRatio": round(instructed_metrics["pause_ratio"] - neutral_metrics["pause_ratio"], 3),
                "dRoughness": round(
                    instructed_metrics["energy_roughness"] - neutral_metrics["energy_roughness"], 3
                ),
                "prosodyEffect": round(
                    prosody_effect(
                        {
                            key: instructed_metrics[key]
                            for key in ("f0_std_hz", "rate_cv", "pause_ratio", "energy_roughness")
                        },
                        profile,
                    ),
                    2,
                ),
                "deliveryMetrics": instructed_metrics,
                "neutralMetrics": neutral_metrics,
                # Per-take prosody gate verdict from the same analysis pass, so
                # downstream typed quality reports can fold a real verdict
                # instead of re-deriving thresholds.
                "qualityGate": evaluate_metrics(instructed_metrics, resolved_profile),
                # Per-preset adherence verdict against the same-seed neutral
                # pair; carries the profile's delivery_expectations identity
                # through the shared profileDigest.
                "deliveryGate": evaluate_delivery(
                    instructed_metrics,
                    neutral_metrics,
                    delivery["delivery"],
                    resolved_profile,
                ),
            }
        )
    return results


def write_results(diagnostics_dir: Path, results: list[dict[str, Any]]) -> Path:
    diagnostics_dir.mkdir(parents=True, exist_ok=True)
    output_path = diagnostics_dir / "bench-prosody.json"
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".bench-prosody-", suffix=".json", dir=diagnostics_dir
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(results, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, output_path)
    except BaseException:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise
    return output_path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Post-process the current bench run's delivery WAVs with prosody analysis."
    )
    parser.add_argument("diagnostics_dir", type=Path, help="current runtime diagnostics directory")
    parser.add_argument(
        "--results-manifest",
        type=Path,
        required=True,
        help="current run's immutable bench-results.json",
    )
    parser.add_argument(
        "--prosody-profile",
        default="",
        help="path to a prosody profile JSON (default: built-in)",
    )
    args = parser.parse_args()
    try:
        profile = load_profile(args.prosody_profile) if args.prosody_profile else None
        results = analyze_run(args.diagnostics_dir, args.results_manifest, profile)
        output_path = write_results(args.diagnostics_dir, results)
    except (OSError, ValueError) as error:
        raise SystemExit(f"delivery prosody analysis failed: {error}") from error
    print(f"wrote {output_path} ({len(results)} current-run delivery/neutral pairs)")


if __name__ == "__main__":
    main()
