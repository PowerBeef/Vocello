#!/usr/bin/env python3
"""Analyze only the current ``vocello bench --delivery`` run's WAVs.

The immutable ``bench-results.json`` manifest is mandatory: it selects the exact
delivery and neutral outputs from the current run, even when ``outputs/bench``
also contains files from older ``--keep`` runs. The resulting sidecar is written
before the telemetry summary so the current summary and history record include
the same prosody evidence.

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


def collect_run_outputs(bench_dir: Path, results_manifest: Path) -> tuple[str, list[dict[str, Any]]]:
    """Resolve and validate the exact output set named by one run manifest."""
    try:
        manifest = json.loads(results_manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid results manifest {results_manifest}: {error}") from error
    if not isinstance(manifest, dict) or manifest.get("schemaVersion") != 1:
        raise ValueError("results manifest must be a schema-v1 object")
    run_id = manifest.get("runID")
    takes = manifest.get("takes")
    if not isinstance(run_id, str) or not run_id:
        raise ValueError("results manifest has no runID")
    if not isinstance(takes, list) or not takes:
        raise ValueError("results manifest has no takes")

    parsed_outputs: list[dict[str, Any]] = []
    names: set[str] = set()
    generation_ids: set[str] = set()
    for index, take in enumerate(takes, start=1):
        if not isinstance(take, dict) or take.get("takeIndex") != index:
            raise ValueError("results manifest take indices must be contiguous and one-based")
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
        parsed_outputs.append(parsed)
        names.add(name)
        generation_ids.add(generation_id)
    return run_id, parsed_outputs


def find_neutral(parsed: list[dict[str, Any]], target: dict[str, Any]) -> dict[str, Any] | None:
    """Find the closest neutral reference within the selected current run."""
    same_length = [
        item
        for item in parsed
        if item["delivery"] is None
        and item["mode"] == target["mode"]
        and item["model"] == target["model"]
        and item["length"] == target["length"]
        and item["state"] == target["state"]
    ]
    candidates = same_length or [
        item
        for item in parsed
        if item["delivery"] is None
        and item["mode"] == target["mode"]
        and item["model"] == target["model"]
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
    run_id, parsed = collect_run_outputs(bench_dir, results_manifest)
    deliveries = [item for item in parsed if item["delivery"]]
    if not deliveries:
        raise ValueError("current results manifest contains no delivery takes")

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
    for delivery in deliveries:
        neutral = find_neutral(parsed, delivery)
        if neutral is None:
            raise ValueError(f"current run has no neutral reference for {delivery['name']}")
        instructed_metrics = analyze(delivery["path"])
        neutral_metrics = analyze(neutral["path"])
        if "error" in instructed_metrics or "error" in neutral_metrics:
            raise ValueError(f"prosody analysis failed for current output {delivery['name']}")
        results.append(
            {
                "runID": run_id,
                "generationID": delivery["generationID"],
                "neutralGenerationID": neutral["generationID"],
                "mode": delivery["mode"],
                "model": delivery["model"],
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
