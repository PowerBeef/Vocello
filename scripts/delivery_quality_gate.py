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
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from prosody_profile import (
    arousal_score,
    builtin_profile,
    delivery_expectation,
    delivery_weight,
    intensity_factor,
    load_profile,
    neutral_consistency,
)

# v2 (2026-08-05): expectations may bind optional-analyzer features; a pair
# whose analysis predates those keys skips them into the verdict's
# `unavailableFeatures` list instead of failing `metrics_incomplete`.
# v3 (2026-09-25, audit #39; decided by the audit's recommendation): the
# per-take flags are diagnostics. One noisy instructed/neutral pair per take
# flagged 460 of 902 takes and 96 of 108 records, so a regression was
# invisible; the adherence verdict is now the cell's (`evaluate_delivery_cell`).
DELIVERY_GATE_ALGORITHM_VERSION = 3

# The cell-level adherence verdict (audit #39): every take of one delivery cell
# (mode, model, speaker, length, preset and intensity) judged together.
# A required feature's cell flags when the median signed effect is not
# positive (direction) or sits below its floor (weak); a supporting feature's
# when the median moves clearly the opposite way. `paired_report`
# (delivery_statistics) annotates each feature with its exact Wilcoxon test,
# BCa interval and Wilson direction win-rate; they never decide the verdict.
# Floors are provisional: the per-take floors, measured before the 2026-08-25
# instruction rewrite, until a pre-registered post-rewrite run re-derives them
# (`scripts/delivery_matrix_report.py --emit-expectations`, half the observed
# median effect) under the threshold-change authority. A single run rarely
# holds `CELL_MINIMUM_TAKES` takes of a cell; the cross-seed report judges the
# campaign's cells (`cellAdherence`).
CELL_ADHERENCE_ALGORITHM = "delivery-cell-adherence-v1"
CELL_FLOOR_STATUS = "provisional-per-take-floors"
# Fewer takes than this give a cell verdict of `insufficient`: a median of one
# or two noisy pairs is the per-take judgment again.
CELL_MINIMUM_TAKES = 5

# Neutral-cohort arousal outliers (audit #105).
#
# Binding: the calibrated population z-score (`population-z-v1`) against the
# profile's `outlier_z_score` bound. The candidate sits inside the population
# SD, so |z| <= sqrt(n - 1) (Samuelson's bound) and the 2.5 bound cannot fire
# for a cohort of seven or fewer takes. The bound was calibrated for this
# statistic; moving the verdict onto another score, or setting that score's
# bound, is a threshold change for the maintainer (audio-QC threshold-change
# authority), so it is not made here.
#
# Report only (`leaveOneOutOutlier`, never part of `passed`): each take's
# externally studentized leave-one-out residual
#     T_i = (x_i - mean of the others) / (SD of the others * sqrt(1 + 1/(n - 1))),
# which follows Student's t with n - 2 degrees of freedom when the takes are
# healthy (independent draws from one normal), and the Bonferroni family-wise
# p-value min(1, n * P(|t| >= max |T_i|)). Its null distribution is exact, so
# the maintainer's decision reduces to choosing a cohort-wise alpha. A
# leave-one-out median/MAD score was rejected: with three to seven other takes
# its MAD is biased low, and a seeded null simulation put a take above 2.5 in
# 58-82% of healthy cohorts of four to eight takes.
#
# Its flag threshold (2026-09-25; the maintainer delegated the decision to the
# audit's recommendation): a cohort-wise Bonferroni alpha of 0.05 marks the
# candidate `flagged`, report only. The alpha is the nominal family-wise rate
# the null simulation reproduces, not a bound calibrated on delivery evidence,
# so the flag never enters `passed`, `flags` or a downstream outcome until a
# calibration (a labeled cohort set with known unstable takes, judged under the
# audio-QC threshold-change authority) sets `bindsVerdict`.
COHORT_OUTLIER_ALGORITHM = "population-z-v1"
LEAVE_ONE_OUT_OUTLIER_ALGORITHM = "leave-one-out-studentized-t-v1"
LEAVE_ONE_OUT_REPORT_ALPHA = 0.05
LEAVE_ONE_OUT_ALPHA_STATUS = "report-only-uncalibrated"

# Flags that mean the verdict could not be computed (mapped to a distinct
# "unavailable" outcome downstream, mirroring the prosody sidecar contract).
ANALYSIS_FAILURE_FLAGS = (
    "analysis_failed",
    "metrics_incomplete",
    "expectation_missing",
    "cohort_too_small",
)

# Expectation-bindable features derived from the optional analyzer keys
# (`_OPTIONAL_CADENCE_KEYS`, `_OPTIONAL_VOICE_KEYS`). When one of these is
# absent from an analyzed pair, the expectation entry is skipped as
# unavailable; a missing feature derived from `_REQUIRED_METRIC_KEYS` still
# fails closed as `metrics_incomplete`.
OPTIONAL_EXPECTATION_FEATURES = frozenset({
    "turning_points_delta_per_sec",
    "max_pause_delta_seconds",
    "dynamic_range_delta_db",
    "hnr_delta_db",
    "cpp_delta_db",
    "jitter_delta_pct",
    "shimmer_delta_db",
    "alpha_ratio_delta_db",
    "hammarberg_delta_db",
    "hf_energy_ratio_delta",
    "centroid_delta_hz",
    "spectral_flux_delta",
    "voice_tension_score",
    "voice_breathiness_score",
})

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

# Analyzer-v2 keys that were always computed but never bound to an expectation.
# `dramatic` ("clear held pauses") and `surprised` ("pitch rising steeply on key
# words") are described almost entirely by these, so they are now available as
# paired deltas. Optional so banked rows analyzed before this change still load.
_OPTIONAL_CADENCE_KEYS = (
    "f0_turning_points_per_sec",
    "pauses_max_pause_seconds",
    "energy_dynamic_range_db",
)

# Analyzer-v3 voice-quality and spectral keys. Optional for the same reason:
# every `bench-prosody.json` row banked under v2 predates them, and a missing
# block must degrade to "this feature is unavailable", never to a failed verdict.
_OPTIONAL_VOICE_KEYS = (
    "voice_hnr_db_mean",
    "voice_cpp_db_mean",
    "voice_frame_jitter_pct",
    "voice_frame_shimmer_db",
    "spectral_alpha_ratio_db",
    "spectral_hammarberg_db",
    "spectral_hf_energy_ratio",
    "spectral_centroid_hz",
    "spectral_flux",
)


def _paired_delta(instructed, neutral, key):
    """Signed instructed-minus-neutral delta, or None when either side lacks it."""
    if key not in instructed or key not in neutral:
        return None
    return instructed[key] - neutral[key]


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
    features["arousal_score"] = arousal_score(instructed, neutral, profile)
    if neutral["durationSec"] > 0:
        features["duration_ratio"] = instructed["durationSec"] / neutral["durationSec"]

    # --- cadence deltas the v2 analyzer already measured (see _OPTIONAL_*) ---
    for feature_name, metric_key in (
        ("turning_points_delta_per_sec", "f0_turning_points_per_sec"),
        ("max_pause_delta_seconds", "pauses_max_pause_seconds"),
        ("dynamic_range_delta_db", "energy_dynamic_range_db"),
    ):
        delta = _paired_delta(instructed, neutral, metric_key)
        if delta is not None:
            features[feature_name] = delta

    # --- analyzer-v3 voice-quality / spectral deltas ---
    for feature_name, metric_key in (
        ("hnr_delta_db", "voice_hnr_db_mean"),
        ("cpp_delta_db", "voice_cpp_db_mean"),
        ("jitter_delta_pct", "voice_frame_jitter_pct"),
        ("shimmer_delta_db", "voice_frame_shimmer_db"),
        ("alpha_ratio_delta_db", "spectral_alpha_ratio_db"),
        ("hammarberg_delta_db", "spectral_hammarberg_db"),
        ("hf_energy_ratio_delta", "spectral_hf_energy_ratio"),
        ("centroid_delta_hz", "spectral_centroid_hz"),
        ("spectral_flux_delta", "spectral_flux"),
    ):
        delta = _paired_delta(instructed, neutral, metric_key)
        if delta is not None:
            features[feature_name] = delta

    # Two summary axes over the v3 block, mirroring how `arousal_score`
    # summarizes the v2 block. Named for the constructs they actually index --
    # see the `voice_quality` weights in prosody_profile for why neither is
    # called "valence".
    if all(key in features for key in
           ("alpha_ratio_delta_db", "hammarberg_delta_db", "hf_energy_ratio_delta")):
        features["voice_tension_score"] = (
            -features["alpha_ratio_delta_db"]
            / delivery_weight(profile, "voice_quality", "alpha_ratio_divisor")
            - features["hammarberg_delta_db"]
            / delivery_weight(profile, "voice_quality", "hammarberg_divisor")
            + features["hf_energy_ratio_delta"]
            / delivery_weight(profile, "voice_quality", "hf_energy_ratio_divisor")
        )
    if all(key in features for key in ("hnr_delta_db", "cpp_delta_db")):
        features["voice_breathiness_score"] = (
            -features["hnr_delta_db"]
            / delivery_weight(profile, "voice_quality", "hnr_divisor")
            - features["cpp_delta_db"]
            / delivery_weight(profile, "voice_quality", "cpp_divisor")
        )
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
    missing = [feature for feature in sorted(expectation) if feature not in features]
    if any(feature not in OPTIONAL_EXPECTATION_FEATURES for feature in missing):
        return _verdict(
            delivery_id, preset, intensity, False, ["metrics_incomplete"],
            "expectation features missing from analyzed metrics", {},
        )
    # Expectations may bind optional-analyzer features (cadence, voice
    # quality). A pair analyzed before those keys existed skips them —
    # "this feature is unavailable", never a failed or warned verdict.
    unavailable = missing

    factor = intensity_factor(prof, intensity)
    flags = []
    for feature, spec in sorted(expectation.items()):
        if feature in unavailable:
            continue
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
    verdict = _verdict(
        delivery_id, preset, intensity,
        len(flags) == 0, flags,
        "; ".join(flags) if flags else "delivery adherence gate passed",
        metrics,
    )
    verdict["unavailableFeatures"] = unavailable
    return verdict


def evaluate_delivery_cell(take_features, delivery_id, profile=None, *,
                           minimum_takes=CELL_MINIMUM_TAKES):
    """Cell-level adherence verdict over the paired features of one cell's takes.

    `take_features` holds each take's `evaluate_delivery` metrics (the signed
    paired features). Returns `status` pass, warn, insufficient (fewer than
    `minimum_takes` takes carry the features) or unavailable (no expectation
    covers the preset), the cell `flags`, and per-feature evidence. Warn-only:
    the verdict never fails a take.
    """
    prof = profile if profile is not None else builtin_profile()
    preset, intensity = _parse_delivery_id(delivery_id)
    expectation = delivery_expectation(prof, preset)
    verdict = {
        "algorithm": CELL_ADHERENCE_ALGORITHM,
        "deliveryID": delivery_id,
        "floorStatus": CELL_FLOOR_STATUS,
        "minimumTakes": minimum_takes,
        "takeCount": len(take_features),
    }
    if expectation is None:
        return {**verdict, "status": "unavailable", "flags": ["expectation_missing"], "features": {}}
    from delivery_statistics import paired_report  # NumPy only when a cell is judged

    factor = intensity_factor(prof, intensity)
    flags = []
    features = {}
    judged_any = False
    for feature, spec in sorted(expectation.items()):
        signed = [
            float(metrics[feature]) * spec["direction"]
            for metrics in take_features
            if isinstance(metrics, dict)
            and isinstance(metrics.get(feature), (int, float))
            and not isinstance(metrics.get(feature), bool)
            and math.isfinite(float(metrics[feature]))
        ]
        if not signed:
            continue
        floor = spec["min_effect_normal"] * factor
        median = statistics.median(signed)
        report = paired_report(signed, [0.0] * len(signed), label=feature)
        interval = report["confidenceInterval"]
        judged = len(signed) >= minimum_takes
        judged_any = judged_any or judged
        features[feature] = {
            "tier": spec["tier"],
            "n": len(signed),
            "floor": round(floor, 4),
            "medianSignedEffect": round(median, 4),
            "wilcoxonPValue": report["wilcoxon"]["pValue"],
            "meanInterval": [round(interval["lower"], 4), round(interval["upper"], 4)] if interval else None,
            "directionWinRate": round(report["winRate"]["rate"], 4) if report["winRate"] else None,
            "judged": judged,
        }
        if not judged:
            continue
        if spec["tier"] == "required":
            if median <= 0:
                flags.append(f"cell_direction_miss_{feature}")
            elif median < floor:
                flags.append(f"cell_effect_weak_{feature}")
        elif median < -floor:
            flags.append(f"cell_supporting_miss_{feature}")
    if not judged_any:
        status = "insufficient"
    else:
        status = "warn" if flags else "pass"
    return {**verdict, "status": status, "flags": flags, "features": features}


def delivery_cell_key(row):
    """The cell a delivery take belongs to: every pairing dimension but the seed."""
    return (
        row.get("mode"), row.get("model"), row.get("speakerID"),
        row.get("length"), row.get("delivery"),
    )


def student_t_two_sided_p(statistic, degrees_of_freedom):
    """P(|T| >= |statistic|) for Student's t with a positive integer df.

    The closed form for integer degrees of freedom (Abramowitz and Stegun
    26.7.3 and 26.7.4), so no SciPy is needed.
    """
    if type(degrees_of_freedom) is not int or degrees_of_freedom < 1:
        raise ValueError("degrees of freedom must be a positive integer")
    magnitude = abs(float(statistic))
    if math.isinf(magnitude):
        return 0.0
    theta = math.atan(magnitude / math.sqrt(degrees_of_freedom))
    cos_squared = math.cos(theta) ** 2
    term, series = 1.0, 1.0
    if degrees_of_freedom % 2:
        for k in range(1, (degrees_of_freedom - 1) // 2):
            term *= (2 * k) / (2 * k + 1) * cos_squared
            series += term
        inside = theta + (
            math.sin(theta) * math.cos(theta) * series if degrees_of_freedom > 1 else 0.0
        )
        central = 2.0 / math.pi * inside
    else:
        for k in range(1, degrees_of_freedom // 2):
            term *= (2 * k - 1) / (2 * k) * cos_squared
            series += term
        central = math.sin(theta) * series
    return min(1.0, max(0.0, 1.0 - central))


def leave_one_out_studentized_residual(values, index):
    """``values[index]`` against the mean and SD of the other values (report only).

    Returns None with fewer than two others. When the others agree exactly, a
    departure from them is unbounded (signed infinity) and agreement is 0.
    """
    others = [float(value) for position, value in enumerate(values) if position != index]
    if len(others) < 2:
        return None
    difference = float(values[index]) - statistics.fmean(others)
    scale = statistics.stdev(others) * math.sqrt(1.0 + 1.0 / len(others))
    if scale <= 1e-9:
        return 0.0 if abs(difference) <= 1e-9 else math.copysign(math.inf, difference)
    return difference / scale


def leave_one_out_outlier_report(values, clips):
    """The report-only leave-one-out outlier block (audit #105); never gates.

    `flagged` compares the Bonferroni p-value with the report-only alpha; it
    is a diagnostic until calibration evidence exists (`bindsVerdict` false).
    """
    degrees = len(values) - 2
    report = {
        "reportOnly": True,
        "algorithm": LEAVE_ONE_OUT_OUTLIER_ALGORITHM,
        "degreesOfFreedom": degrees,
        "candidate": None,
        "maxAbsScore": None,
        "bonferroniPValue": None,
        "alpha": LEAVE_ONE_OUT_REPORT_ALPHA,
        "alphaStatus": LEAVE_ONE_OUT_ALPHA_STATUS,
        "bindsVerdict": False,
        "flagged": False,
    }
    if degrees < 1:
        return report
    scores = [leave_one_out_studentized_residual(values, index) for index in range(len(values))]
    worst = max(range(len(values)), key=lambda index: abs(scores[index]))
    magnitude = abs(scores[worst])
    family_wise = min(1.0, len(values) * student_t_two_sided_p(magnitude, degrees))
    report.update({
        "candidate": clips[worst],
        # None when the other takes agree exactly and this one departs from them.
        "maxAbsScore": round(magnitude, 3) if math.isfinite(magnitude) else None,
        "bonferroniPValue": float(f"{family_wise:.4g}"),
        "flagged": family_wise < LEAVE_ONE_OUT_REPORT_ALPHA,
    })
    return report


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
    # Binding: the calibrated population z (see COHORT_OUTLIER_ALGORITHM).
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
        "outlierAlgorithm": COHORT_OUTLIER_ALGORITHM,
        "outliers": outliers,
        "leaveOneOutOutlier": leave_one_out_outlier_report(
            proxies, [metrics.get("clip", "") for metrics in valid],
        ),
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
