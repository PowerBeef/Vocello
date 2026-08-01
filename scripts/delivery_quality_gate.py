#!/usr/bin/env python3
"""Per-preset delivery-adherence gate for Vocello TTS output.

Verifies that an instructed take actually moved the measurable prosody in the
direction the selected delivery preset asked for, using the paired same-seed
neutral take as the reference. The per-preset expectations live in the
versioned prosody profile (``delivery_expectations``), so the thresholds ride
the same digest chain as every other prosody verdict.

Two evaluation modes:

  paired   — instructed-vs-neutral metric dicts + a ``<preset>.<intensity>``
             delivery id → warn-first verdict {passed, flags, metrics}.
  cohort   — N same-preset takes (typically Neutral) → dispersion bounds and
             per-take expressive outliers ("the delivery should not wander").

Deterministic and dependency-light: the verdict logic consumes already-analyzed
metric dicts, so unit tests need no NumPy; the CLI lazily imports the bounded
analyzer only when given WAV paths.

Usage:
  scripts/delivery_quality_gate.py --instructed d.wav --neutral n.wav \
      --delivery excited.strong [--profile p.json] [--json]
  scripts/delivery_quality_gate.py --cohort a.wav b.wav c.wav d.wav [--json]
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from prosody_profile import (
    builtin_profile,
    delivery_expectation,
    delivery_weight,
    intensity_factor,
    load_profile,
    neutral_consistency,
)

DELIVERY_GATE_ALGORITHM_VERSION = 1

# Flags that mean the verdict could not be computed (mapped to a distinct
# "unavailable" outcome downstream, mirroring the prosody sidecar contract).
ANALYSIS_FAILURE_FLAGS = (
    "analysis_failed",
    "metrics_incomplete",
    "expectation_missing",
    "cohort_too_small",
)

_REQUIRED_METRIC_KEYS = (
    "f0_median_hz",
    "f0_range_hz",
    "f0_range_semitones",
    "f0_std_hz",
    "f0_voiced_frac",
    "rate_syllable_rate_hz",
    "rate_cv",
    "pause_ratio",
    "energy_roughness",
    "durationSec",
)


def _parse_delivery_id(delivery_id):
    """Split ``<preset>[.<intensity>]`` with a normal-intensity default."""
    if not isinstance(delivery_id, str) or not delivery_id:
        raise ValueError("delivery id must be a non-empty string")
    preset, separator, intensity = delivery_id.partition(".")
    return preset, (intensity if separator else "normal")


def delivery_features(instructed, neutral, profile):
    """Signed paired features the expectations bind to. Missing inputs omit."""
    features = {}
    for metrics in (instructed, neutral):
        if any(key not in metrics for key in _REQUIRED_METRIC_KEYS):
            return features
    if instructed["f0_median_hz"] > 0 and neutral["f0_median_hz"] > 0:
        features["pitch_shift_semitones"] = 12.0 * math.log2(
            instructed["f0_median_hz"] / neutral["f0_median_hz"]
        )
    features["pitch_range_delta_semitones"] = (
        instructed["f0_range_semitones"] - neutral["f0_range_semitones"]
    )
    features["pitch_variation_delta_hz"] = instructed["f0_std_hz"] - neutral["f0_std_hz"]
    features["rate_delta_hz"] = (
        instructed["rate_syllable_rate_hz"] - neutral["rate_syllable_rate_hz"]
    )
    features["rate_cv_delta"] = instructed["rate_cv"] - neutral["rate_cv"]
    features["pause_ratio_delta"] = instructed["pause_ratio"] - neutral["pause_ratio"]
    features["roughness_delta"] = instructed["energy_roughness"] - neutral["energy_roughness"]
    features["voiced_fraction_delta"] = (
        instructed["f0_voiced_frac"] - neutral["f0_voiced_frac"]
    )
    features["arousal_score"] = (
        (instructed["f0_median_hz"] - neutral["f0_median_hz"])
        / delivery_weight(profile, "arousal", "f0_median_divisor")
        + (instructed["rate_syllable_rate_hz"] - neutral["rate_syllable_rate_hz"])
        / delivery_weight(profile, "arousal", "syllable_rate_divisor")
        + (instructed["f0_range_hz"] - neutral["f0_range_hz"])
        / delivery_weight(profile, "arousal", "f0_range_divisor")
        - (instructed["durationSec"] - neutral["durationSec"])
        / delivery_weight(profile, "arousal", "duration_divisor")
    )
    if neutral["durationSec"] > 0:
        features["duration_ratio"] = instructed["durationSec"] / neutral["durationSec"]
    return features


def _verdict(delivery_id, preset, intensity, passed, flags, reason, metrics):
    return {
        "deliveryID": delivery_id,
        "preset": preset,
        "intensity": intensity,
        "algorithmVersion": DELIVERY_GATE_ALGORITHM_VERSION,
        "passed": passed,
        "flags": flags,
        "reason": reason,
        "metrics": metrics,
    }


def evaluate_delivery(instructed_metrics, neutral_metrics, delivery_id, profile=None):
    """Paired warn-first adherence verdict for one instructed take."""
    prof = profile if profile is not None else builtin_profile()
    preset, intensity = _parse_delivery_id(delivery_id)

    if "error" in instructed_metrics or "error" in neutral_metrics:
        return _verdict(
            delivery_id, preset, intensity, False, ["analysis_failed"],
            "prosody analysis failed for the pair", {},
        )

    expectation = delivery_expectation(prof, preset)
    if expectation is None:
        return _verdict(
            delivery_id, preset, intensity, False, ["expectation_missing"],
            f"no delivery expectation covers preset {preset!r}", {},
        )

    features = delivery_features(instructed_metrics, neutral_metrics, prof)
    if any(feature not in features for feature in expectation):
        return _verdict(
            delivery_id, preset, intensity, False, ["metrics_incomplete"],
            "expectation features missing from analyzed metrics", {},
        )

    factor = intensity_factor(prof, intensity)
    flags = []
    for feature, spec in sorted(expectation.items()):
        signed = features[feature] * spec["direction"]
        minimum = spec["min_effect_normal"] * factor
        if spec["tier"] == "required":
            if signed <= 0:
                flags.append(f"delivery_direction_miss_{feature}")
            elif signed < minimum:
                flags.append(f"delivery_effect_weak_{feature}")
        elif signed < -minimum:
            flags.append(f"delivery_supporting_miss_{feature}")

    metrics = {key: round(value, 3) for key, value in sorted(features.items())}
    metrics["intensity_factor"] = round(factor, 3)
    return _verdict(
        delivery_id, preset, intensity,
        len(flags) == 0, flags,
        "; ".join(flags) if flags else "delivery adherence gate passed",
        metrics,
    )


def evaluate_neutral_cohort(cohort_metrics, profile=None):
    """Cross-take consistency verdict for repeated same-preset takes."""
    prof = profile if profile is not None else builtin_profile()
    valid = [
        metrics for metrics in cohort_metrics
        if "error" not in metrics and all(key in metrics for key in _REQUIRED_METRIC_KEYS)
    ]
    minimum_size = neutral_consistency(prof, "min_cohort_size")
    if len(valid) < minimum_size:
        return {
            "algorithmVersion": DELIVERY_GATE_ALGORITHM_VERSION,
            "cohortSize": len(valid),
            "passed": False,
            "flags": ["cohort_too_small"],
            "reason": f"cohort has {len(valid)} usable takes; needs {minimum_size}",
            "metrics": {},
            "outliers": [],
        }

    def arousal_proxy(metrics):
        return (
            metrics["f0_median_hz"] / delivery_weight(prof, "arousal", "f0_median_divisor")
            + metrics["rate_syllable_rate_hz"]
            / delivery_weight(prof, "arousal", "syllable_rate_divisor")
            + metrics["f0_range_hz"] / delivery_weight(prof, "arousal", "f0_range_divisor")
        )

    medians = [metrics["f0_median_hz"] for metrics in valid]
    rates = [metrics["rate_syllable_rate_hz"] for metrics in valid]
    proxies = [arousal_proxy(metrics) for metrics in valid]

    pitch_spread = (
        12.0 * math.log2(max(medians) / min(medians)) if min(medians) > 0 else 0.0
    )
    rate_spread = max(rates) - min(rates)
    mean_proxy = sum(proxies) / len(proxies)
    variance = sum((value - mean_proxy) ** 2 for value in proxies) / len(proxies)
    deviation = math.sqrt(variance)
    z_bound = neutral_consistency(prof, "outlier_z_score")
    outliers = []
    max_abs_z = 0.0
    for metrics, proxy in zip(valid, proxies):
        z_score = (proxy - mean_proxy) / deviation if deviation > 1e-9 else 0.0
        max_abs_z = max(max_abs_z, abs(z_score))
        if abs(z_score) > z_bound:
            outliers.append(metrics.get("clip", ""))

    flags = []
    if pitch_spread > neutral_consistency(prof, "max_pitch_spread_semitones"):
        flags.append("pitch_spread_exceeded")
    if rate_spread > neutral_consistency(prof, "max_rate_spread_hz"):
        flags.append("rate_spread_exceeded")
    if outliers:
        flags.append("arousal_outlier")

    return {
        "algorithmVersion": DELIVERY_GATE_ALGORITHM_VERSION,
        "cohortSize": len(valid),
        "passed": len(flags) == 0,
        "flags": flags,
        "reason": "; ".join(flags) if flags else "delivery consistency gate passed",
        "metrics": {
            "pitch_spread_semitones": round(pitch_spread, 3),
            "rate_spread_hz": round(rate_spread, 3),
            "max_abs_z": round(max_abs_z, 3),
        },
        "outliers": outliers,
    }


def _analyze(path):
    """Load the NumPy analyzer only when the CLI is asked to read WAVs."""
    from analyze_prosody import analyze as analyze_wav

    return analyze_wav(path)


def main():
    parser = argparse.ArgumentParser(description="Per-preset delivery adherence gate.")
    parser.add_argument("--instructed", help="instructed-take WAV (paired mode)")
    parser.add_argument("--neutral", help="same-seed neutral WAV (paired mode)")
    parser.add_argument("--delivery", help="delivery id <preset>[.<intensity>] (paired mode)")
    parser.add_argument("--cohort", nargs="*", default=None, help="same-preset WAVs (cohort mode)")
    parser.add_argument("--profile", help="path to a prosody profile JSON (default: built-in)")
    parser.add_argument("--json", action="store_true", help="emit JSON")
    args = parser.parse_args()

    profile = load_profile(args.profile) if args.profile else None
    if args.cohort is not None:
        report = evaluate_neutral_cohort([_analyze(path) for path in args.cohort], profile)
    elif args.instructed and args.neutral and args.delivery:
        report = evaluate_delivery(
            _analyze(args.instructed), _analyze(args.neutral), args.delivery, profile
        )
    else:
        parser.error("provide --instructed/--neutral/--delivery or --cohort")
        return
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
