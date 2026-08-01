#!/usr/bin/env python3
"""Versioned prosody profile: calibrated thresholds + delivery-effect weights.

A profile is a plain JSON file with a schema version so future calibrations can
be migrated. It is consumed by:

  - scripts/prosody_quality_gate.py      (pass/fail thresholds)
  - scripts/delivery_quality_gate.py     (per-preset delivery expectations)
  - scripts/delivery_adherence.py        (arousal / prosody-effect weights)
  - scripts/bench_delivery_prosody.py    (prosody-effect weights + delivery gate)

Usage:
  from prosody_profile import builtin_profile, load_profile
  profile = load_profile("profiles/warm_narrator.json")
"""
import json
import os

SCHEMA_VERSION = 2

# Built-in defaults mirror the original hard-coded thresholds/weights. They are
# intentionally conservative: they flag obvious prosody issues, not subtle
# artistic choices.
#
# Schema v2 adds two blocks:
#   delivery_expectations — per-preset expected signed effects of an instructed
#     take relative to its same-seed neutral pair. Each preset maps feature →
#     {direction, min_effect_normal, tier}; magnitudes are scaled by intensity.
#     Directions come from the preset instruction semantics
#     (Sources/QwenVoiceCore/EmotionPreset.swift); the initial magnitudes are
#     deliberately conservative seeds pending the paired calibration run.
#   neutral_consistency — cohort dispersion bounds for repeated same-preset
#     fixed-seed takes (the "neutral should not wander" check).
BUILTIN_PROFILE = {
    "schema_version": SCHEMA_VERSION,
    "name": "builtin",
    "description": "Conservative default prosody thresholds and delivery weights.",
    "thresholds": {
        "monotone_f0_std_hz": 8.0,
        "monotone_turning_points_per_sec": 4.0,
        "rushed_syllable_rate_hz": 6.5,
        "rushed_max_pause_ratio": 0.03,
        "flat_envelope_roughness": 0.08,
        "flat_rate_cv": 0.08,
        "pause_max_seconds": 1.2,
        "pause_ratio_max": 0.35,
    },
    "delivery_weights": {
        "arousal": {
            "f0_median_divisor": 10.0,
            "syllable_rate_divisor": 0.5,
            "f0_range_divisor": 20.0,
            "duration_divisor": 0.5,
        },
        "prosody_effect": {
            "f0_std_divisor": 10.0,
            "rate_cv_divisor": 0.1,
            "pause_ratio_divisor": 0.05,
            "energy_roughness_divisor": 0.05,
        },
    },
    # Calibrated 2026-08-01 from the banked 7-seed × 18-cell paired matrix
    # (records labeled delivery-cal-s1..s8; seed 20260802 excluded by its
    # reproducible sad.strong Fast-QC failure). Required features have a
    # measured ≥0.85 direction win-rate; supporting features 0.71–0.84;
    # magnitudes sit near half the observed median effect. Dramatic and
    # surprised measurably barely move prosody, so they carry direction-only
    # supporting expectations — the honest reading of the data.
    "delivery_expectations": {
        "intensity_scale": {"subtle": 0.0, "normal": 1.0, "strong": 1.15},
        "presets": {
            "happy": {
                "pitch_variation_delta_hz": {"direction": 1, "min_effect_normal": 2.5, "tier": "required"},
                "arousal_score": {"direction": 1, "min_effect_normal": 0.5, "tier": "required"},
                "pitch_shift_semitones": {"direction": 1, "min_effect_normal": 0.0, "tier": "supporting"},
            },
            "excited": {
                "pitch_variation_delta_hz": {"direction": 1, "min_effect_normal": 3.0, "tier": "required"},
                "arousal_score": {"direction": 1, "min_effect_normal": 0.5, "tier": "supporting"},
                "pitch_shift_semitones": {"direction": 1, "min_effect_normal": 0.0, "tier": "supporting"},
            },
            "surprised": {
                "pitch_variation_delta_hz": {"direction": 1, "min_effect_normal": 0.0, "tier": "supporting"},
                "pitch_shift_semitones": {"direction": 1, "min_effect_normal": 0.0, "tier": "supporting"},
            },
            "sad": {
                "arousal_score": {"direction": -1, "min_effect_normal": 0.5, "tier": "required"},
                "pitch_variation_delta_hz": {"direction": -1, "min_effect_normal": 0.0, "tier": "supporting"},
                "pause_ratio_delta": {"direction": 1, "min_effect_normal": 0.0, "tier": "supporting"},
            },
            "calm": {
                "pitch_shift_semitones": {"direction": -1, "min_effect_normal": 0.6, "tier": "required"},
                "arousal_score": {"direction": -1, "min_effect_normal": 0.5, "tier": "supporting"},
            },
            "angry": {
                "pitch_shift_semitones": {"direction": 1, "min_effect_normal": 1.0, "tier": "required"},
                "pitch_variation_delta_hz": {"direction": 1, "min_effect_normal": 3.0, "tier": "required"},
                "arousal_score": {"direction": 1, "min_effect_normal": 0.5, "tier": "supporting"},
            },
            "fearful": {
                "pitch_shift_semitones": {"direction": 1, "min_effect_normal": 0.8, "tier": "required"},
                "arousal_score": {"direction": -1, "min_effect_normal": 0.5, "tier": "required"},
                "pause_ratio_delta": {"direction": 1, "min_effect_normal": 0.01, "tier": "required"},
                "pitch_variation_delta_hz": {"direction": -1, "min_effect_normal": 0.0, "tier": "supporting"},
            },
            "whisper": {
                "pitch_variation_delta_hz": {"direction": -1, "min_effect_normal": 4.0, "tier": "required"},
                "arousal_score": {"direction": -1, "min_effect_normal": 0.5, "tier": "required"},
                "voiced_fraction_delta": {"direction": -1, "min_effect_normal": 0.0, "tier": "supporting"},
            },
            "dramatic": {
                "roughness_delta": {"direction": 1, "min_effect_normal": 0.0, "tier": "supporting"},
                "pitch_shift_semitones": {"direction": 1, "min_effect_normal": 0.0, "tier": "supporting"},
            },
        },
    },
    # Calibrated 2026-08-01 from the three 8-seed Aiden neutral cohorts
    # (expressive 2.70 st / 1.97 Hz spread, consistent 3.99 / 2.2, steadied
    # 2.13 / 2.5): bounds sit just above the measured baseline so the gate
    # flags regressions beyond today's cross-seed wander, which is itself
    # recorded as a product finding, not silently normalized.
    "neutral_consistency": {
        "min_cohort_size": 4,
        "max_pitch_spread_semitones": 4.5,
        "max_rate_spread_hz": 2.75,
        "outlier_z_score": 2.5,
    },
    # Warn-first reference-vs-output bounds for clone takes. Uncalibrated
    # seeds pending the negative-control lane; a cloned voice should sit near
    # the reference's pitch register, expressiveness band, and pacing.
    "clone_fidelity": {
        "max_abs_pitch_shift_semitones": 2.0,
        "max_abs_range_delta_semitones": 4.0,
        "max_rate_ratio_deviation": 0.30,
        "max_abs_voiced_fraction_delta": 0.20,
    },
}


_EXPECTATION_TIERS = ("required", "supporting")


_ADDON_BLOCKS = ("delivery_expectations", "neutral_consistency", "clone_fidelity")


def migrate_profile(profile):
    """Migrate an older or partially populated profile dict to the current
    schema.

    A v1 profile predates the schema-v2 add-on blocks; a v2 profile saved
    before a later add-on block existed simply lacks it. Migration fills any
    missing add-on block from the builtin defaults so a calibrated threshold
    file keeps working while new consumers see complete data.
    """
    if not isinstance(profile, dict):
        return profile
    if profile.get("schema_version") in (1, SCHEMA_VERSION):
        profile = dict(profile)
        profile["schema_version"] = SCHEMA_VERSION
        for key in _ADDON_BLOCKS:
            profile.setdefault(key, json.loads(json.dumps(BUILTIN_PROFILE[key])))
    return profile


def _validate_delivery_expectations(block):
    if not isinstance(block, dict):
        raise ValueError("delivery_expectations must be an object")
    scale = block.get("intensity_scale")
    if not isinstance(scale, dict) or set(scale.keys()) != {"subtle", "normal", "strong"}:
        raise ValueError("delivery_expectations.intensity_scale must map subtle/normal/strong")
    for tier_name, factor in scale.items():
        if not isinstance(factor, (int, float)) or factor < 0:
            raise ValueError(f"intensity_scale.{tier_name} must be a non-negative number")
    presets = block.get("presets")
    if not isinstance(presets, dict) or not presets:
        raise ValueError("delivery_expectations.presets must be a non-empty object")
    for preset_id, features in presets.items():
        if not isinstance(features, dict) or not features:
            raise ValueError(f"delivery_expectations.presets.{preset_id} must be a non-empty object")
        for feature, spec in features.items():
            if not isinstance(spec, dict):
                raise ValueError(f"expectation {preset_id}.{feature} must be an object")
            if spec.get("direction") not in (1, -1):
                raise ValueError(f"expectation {preset_id}.{feature}.direction must be 1 or -1")
            minimum = spec.get("min_effect_normal")
            if not isinstance(minimum, (int, float)) or minimum < 0:
                raise ValueError(
                    f"expectation {preset_id}.{feature}.min_effect_normal must be non-negative"
                )
            if spec.get("tier") not in _EXPECTATION_TIERS:
                raise ValueError(
                    f"expectation {preset_id}.{feature}.tier must be one of {_EXPECTATION_TIERS}"
                )


def _validate_clone_fidelity(block):
    if not isinstance(block, dict):
        raise ValueError("clone_fidelity must be an object")
    required = set(BUILTIN_PROFILE["clone_fidelity"].keys())
    present = set(block.keys())
    if present != required:
        raise ValueError(
            f"clone_fidelity keys mismatch: missing {required - present}, extra {present - required}"
        )
    for key, value in block.items():
        if not isinstance(value, (int, float)) or value <= 0:
            raise ValueError(f"clone_fidelity.{key} must be a positive number")


def _validate_neutral_consistency(block):
    if not isinstance(block, dict):
        raise ValueError("neutral_consistency must be an object")
    required = set(BUILTIN_PROFILE["neutral_consistency"].keys())
    present = set(block.keys())
    if present != required:
        raise ValueError(
            f"neutral_consistency keys mismatch: missing {required - present}, extra {present - required}"
        )
    for key, value in block.items():
        if not isinstance(value, (int, float)) or value <= 0:
            raise ValueError(f"neutral_consistency.{key} must be a positive number")


def validate_profile(profile):
    """Return profile if valid, else raise ValueError with a clear message."""
    if not isinstance(profile, dict):
        raise ValueError("profile must be a JSON object")
    version = profile.get("schema_version")
    if version != SCHEMA_VERSION:
        raise ValueError(f"unsupported profile schema version {version!r}; expected {SCHEMA_VERSION}")
    missing = [k for k in BUILTIN_PROFILE.keys() if k not in profile]
    if missing:
        raise ValueError(f"profile missing top-level keys: {missing}")
    builtin_thr = set(BUILTIN_PROFILE["thresholds"].keys())
    prof_thr = set(profile["thresholds"].keys())
    if prof_thr != builtin_thr:
        raise ValueError(
            f"profile thresholds keys mismatch: missing {builtin_thr - prof_thr}, extra {prof_thr - builtin_thr}"
        )
    for key, value in profile["thresholds"].items():
        if not isinstance(value, (int, float)):
            raise ValueError(f"threshold {key} must be numeric")
    # Validate delivery weights shape lightly; default on missing inner keys is
    # handled by callers via .get(..., default).
    if not isinstance(profile.get("delivery_weights"), dict):
        raise ValueError("delivery_weights must be an object")
    _validate_delivery_expectations(profile["delivery_expectations"])
    _validate_neutral_consistency(profile["neutral_consistency"])
    _validate_clone_fidelity(profile["clone_fidelity"])
    analyzer_version = profile.get("analyzer_algorithm_version")
    if analyzer_version is not None and (
        not isinstance(analyzer_version, int) or analyzer_version < 1
    ):
        raise ValueError("analyzer_algorithm_version must be a positive integer")
    return profile


def load_profile(path):
    """Load, migrate, and validate a profile from JSON file."""
    if not os.path.exists(path):
        raise FileNotFoundError(f"prosody profile not found: {path}")
    with open(path, "r", encoding="utf-8") as f:
        profile = json.load(f)
    return validate_profile(migrate_profile(profile))


def builtin_profile():
    """Return a fresh copy of the built-in profile."""
    return json.loads(json.dumps(BUILTIN_PROFILE))


def save_profile(profile, path):
    """Write a validated profile to JSON."""
    validate_profile(profile)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(profile, f, indent=2)


def threshold(profile, key, default=None):
    """Read a threshold, falling back to builtin if the key is missing."""
    return profile["thresholds"].get(key, default if default is not None else BUILTIN_PROFILE["thresholds"][key])


def delivery_weight(profile, section, key, default=None):
    """Read a delivery weight divisor, with built-in fallback."""
    builtin_section = BUILTIN_PROFILE["delivery_weights"][section]
    return profile["delivery_weights"].get(section, {}).get(
        key, default if default is not None else builtin_section[key]
    )


def delivery_expectation(profile, preset_id):
    """Expectation feature map for one preset id, or None when uncovered."""
    return profile.get("delivery_expectations", {}).get("presets", {}).get(preset_id)


def intensity_factor(profile, intensity):
    """Magnitude scale for an intensity tier, with built-in fallback."""
    builtin_scale = BUILTIN_PROFILE["delivery_expectations"]["intensity_scale"]
    scale = profile.get("delivery_expectations", {}).get("intensity_scale", builtin_scale)
    return scale.get(intensity, builtin_scale.get(intensity, 1.0))


def neutral_consistency(profile, key):
    """Read a neutral-consistency bound, with built-in fallback."""
    return profile.get("neutral_consistency", {}).get(
        key, BUILTIN_PROFILE["neutral_consistency"][key]
    )


def clone_fidelity_bound(profile, key):
    """Read a clone-fidelity bound, with built-in fallback."""
    return profile.get("clone_fidelity", {}).get(
        key, BUILTIN_PROFILE["clone_fidelity"][key]
    )
