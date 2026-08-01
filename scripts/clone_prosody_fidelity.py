#!/usr/bin/env python3
"""Reference-vs-output prosody fidelity for clone takes (warn-first, advisory).

Complements ``clone_speaker_similarity.py``: ECAPA cosine similarity answers
"is this the same speaker identity"; this script answers "does the output
carry the reference's delivery" using speaker-fair prosody distances from the
bounded analyzer — pitch register in semitones, expressiveness band, pacing
ratio, and voicing character. Bounds live in the versioned prosody profile's
``clone_fidelity`` block (uncalibrated seeds until the negative-control lane
banks distributions), and the verdict logic consumes already-analyzed metric
dicts so unit tests need no NumPy.

Usage:
  scripts/clone_prosody_fidelity.py --reference REF.wav take1.wav [take2.wav …]
      [--profile p.json] [--out sidecar.json] [--json]
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from prosody_profile import builtin_profile, clone_fidelity_bound, load_profile

CLONE_FIDELITY_ALGORITHM_VERSION = 1

ANALYSIS_FAILURE_FLAGS = ("analysis_failed", "metrics_incomplete")

_REQUIRED_METRIC_KEYS = (
    "f0_median_hz",
    "f0_range_semitones",
    "f0_voiced_frac",
    "rate_syllable_rate_hz",
    "pause_ratio",
    "energy_roughness",
)


def clone_features(reference, take):
    """Speaker-fair reference→take distances. Missing inputs omit features."""
    features = {}
    for metrics in (reference, take):
        if any(key not in metrics for key in _REQUIRED_METRIC_KEYS):
            return features
    if reference["f0_median_hz"] > 0 and take["f0_median_hz"] > 0:
        features["pitch_shift_semitones"] = 12.0 * math.log2(
            take["f0_median_hz"] / reference["f0_median_hz"]
        )
    features["range_delta_semitones"] = (
        take["f0_range_semitones"] - reference["f0_range_semitones"]
    )
    if reference["rate_syllable_rate_hz"] > 0:
        features["rate_ratio"] = (
            take["rate_syllable_rate_hz"] / reference["rate_syllable_rate_hz"]
        )
    features["voiced_fraction_delta"] = (
        take["f0_voiced_frac"] - reference["f0_voiced_frac"]
    )
    features["pause_ratio_delta"] = take["pause_ratio"] - reference["pause_ratio"]
    features["roughness_delta"] = (
        take["energy_roughness"] - reference["energy_roughness"]
    )
    return features


def evaluate_clone_fidelity(reference_metrics, take_metrics, profile=None):
    """Warn-first fidelity verdict for one clone take against its reference."""
    prof = profile if profile is not None else builtin_profile()
    clip = take_metrics.get("clip", "") if isinstance(take_metrics, dict) else ""
    if "error" in reference_metrics or "error" in take_metrics:
        return {
            "clip": clip,
            "algorithmVersion": CLONE_FIDELITY_ALGORITHM_VERSION,
            "passed": False,
            "flags": ["analysis_failed"],
            "reason": "prosody analysis failed for the reference/take pair",
            "metrics": {},
        }
    features = clone_features(reference_metrics, take_metrics)
    required = ("pitch_shift_semitones", "range_delta_semitones", "rate_ratio",
                "voiced_fraction_delta")
    if any(feature not in features for feature in required):
        return {
            "clip": clip,
            "algorithmVersion": CLONE_FIDELITY_ALGORITHM_VERSION,
            "passed": False,
            "flags": ["metrics_incomplete"],
            "reason": "fidelity features missing from analyzed metrics",
            "metrics": {},
        }

    flags = []
    if abs(features["pitch_shift_semitones"]) > clone_fidelity_bound(
        prof, "max_abs_pitch_shift_semitones"
    ):
        flags.append("clone_pitch_register_mismatch")
    if abs(features["range_delta_semitones"]) > clone_fidelity_bound(
        prof, "max_abs_range_delta_semitones"
    ):
        flags.append("clone_expressiveness_mismatch")
    if abs(features["rate_ratio"] - 1.0) > clone_fidelity_bound(
        prof, "max_rate_ratio_deviation"
    ):
        flags.append("clone_pacing_mismatch")
    if abs(features["voiced_fraction_delta"]) > clone_fidelity_bound(
        prof, "max_abs_voiced_fraction_delta"
    ):
        flags.append("clone_voicing_mismatch")

    return {
        "clip": clip,
        "algorithmVersion": CLONE_FIDELITY_ALGORITHM_VERSION,
        "passed": len(flags) == 0,
        "flags": flags,
        "reason": "; ".join(flags) if flags else "clone fidelity gate passed",
        "metrics": {key: round(value, 3) for key, value in sorted(features.items())},
    }


def evaluate_takes(reference_metrics, take_metrics_list, profile=None):
    """Per-take verdicts plus a compact aggregate."""
    verdicts = [
        evaluate_clone_fidelity(reference_metrics, take, profile)
        for take in take_metrics_list
    ]
    flag_counts: dict[str, int] = {}
    for verdict in verdicts:
        for flag in verdict["flags"]:
            flag_counts[flag] = flag_counts.get(flag, 0) + 1
    clean = sum(1 for verdict in verdicts if verdict["passed"])
    return {
        "algorithmVersion": CLONE_FIDELITY_ALGORITHM_VERSION,
        "takes": verdicts,
        "aggregate": {
            "count": len(verdicts),
            "clean": clean,
            "flagCounts": dict(sorted(flag_counts.items())),
        },
    }


def _analyze(path):
    """Load the bounded NumPy analyzer only when the CLI reads WAVs."""
    from analyze_prosody import analyze as analyze_wav

    return analyze_wav(path)


def main():
    parser = argparse.ArgumentParser(description="Clone reference-vs-output prosody fidelity.")
    parser.add_argument("takes", nargs="+", help="generated clone take WAV(s)")
    parser.add_argument("--reference", required=True, help="clone reference WAV")
    parser.add_argument("--profile", help="path to a prosody profile JSON (default: built-in)")
    parser.add_argument("--out", help="write the full report JSON here")
    parser.add_argument("--json", action="store_true", help="emit full JSON to stdout")
    args = parser.parse_args()

    profile = load_profile(args.profile) if args.profile else None
    reference_metrics = _analyze(args.reference)
    report = evaluate_takes(
        reference_metrics, [_analyze(path) for path in args.takes], profile
    )
    report["referenceClip"] = os.path.basename(args.reference)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as handle:
            json.dump(report, handle, indent=2, sort_keys=True)
            handle.write("\n")
    print(json.dumps(report if args.json else report["aggregate"], indent=2))


if __name__ == "__main__":
    main()
