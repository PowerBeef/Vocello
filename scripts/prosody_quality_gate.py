#!/usr/bin/env python3
"""Reference-free prosody quality gate for Vocello TTS output.

Flags perceptual tone/tempo/cadence issues that signal-level QC cannot catch:
  - monotone      : low F0 variation + few turning points
  - rushed        : fast syllable rate with little pausing
  - slurred/flat  : low energy dynamics + low rate variability
  - pause_issue   : very long interior pause or extreme pause-to-speech ratio

Deterministic, numpy-only, low-RAM. Designed to run on every vocello bench take.

Usage:
  scripts/prosody_quality_gate.py <wav> [<wav> ...] [--json] [--profile path.json]
  python3 -c "from prosody_quality_gate import evaluate; print(evaluate('clip.wav'))"
"""
import sys, json, argparse, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from analyze_prosody import ANALYZER_ALGORITHM_VERSION, analyze
from prosody_profile import builtin_profile, load_profile, threshold


def evaluate(path, profile=None):
    """Return a gate report for a single WAV using the supplied profile."""
    prof = profile if profile is not None else builtin_profile()
    pros = analyze(path)

    if "error" in pros:
        return {
            "clip": pros.get("clip", path.split("/")[-1]),
            "analyzerAlgorithmVersion": pros.get(
                "analyzerAlgorithmVersion", ANALYZER_ALGORITHM_VERSION
            ),
            "passed": False,
            "flags": ["analysis_failed"],
            "reason": pros["error"],
            "metrics": {},
        }

    return evaluate_metrics(pros, prof)


def evaluate_metrics(pros, prof=None):
    """Gate report from already-analyzed metrics (no re-analysis).

    Lets a caller that has run ``analyze`` once (e.g. the bench delivery
    sidecar) attach the per-take gate verdict without paying for a second
    signal pass. Metrics missing any gate input are reported as a distinct
    non-passing ``metrics_incomplete`` outcome rather than guessed around.
    """
    if prof is None:
        prof = builtin_profile()
    required = (
        "f0_std_hz", "f0_turning_points_per_sec", "rate_syllable_rate_hz",
        "pauses_pause_speech_ratio", "energy_envelope_roughness",
        "rate_local_rate_cv", "pauses_max_pause_seconds",
    )
    if any(key not in pros for key in required):
        return {
            "clip": pros.get("clip", ""),
            "analyzerAlgorithmVersion": pros.get(
                "analyzerAlgorithmVersion", ANALYZER_ALGORITHM_VERSION
            ),
            "passed": False,
            "flags": ["metrics_incomplete"],
            "reason": "gate inputs missing from analyzed metrics",
            "metrics": {},
        }

    flags = []

    # Monotone: very little pitch movement
    if (pros["f0_std_hz"] < threshold(prof, "monotone_f0_std_hz") and
            pros["f0_turning_points_per_sec"] < threshold(prof, "monotone_turning_points_per_sec")):
        flags.append("monotone")

    # Rushed: fast with almost no pausing
    if (pros["rate_syllable_rate_hz"] > threshold(prof, "rushed_syllable_rate_hz") and
            pros["pauses_pause_speech_ratio"] < threshold(prof, "rushed_max_pause_ratio")):
        flags.append("rushed")

    # Flat/slurred: little energy variation and little rate variation
    if (pros["energy_envelope_roughness"] < threshold(prof, "flat_envelope_roughness") and
            pros["rate_local_rate_cv"] < threshold(prof, "flat_rate_cv")):
        flags.append("flat")

    # Pause issue: unnaturally long silence or too much silence
    if pros["pauses_max_pause_seconds"] > threshold(prof, "pause_max_seconds"):
        flags.append("long_pause")
    if pros["pauses_pause_speech_ratio"] > threshold(prof, "pause_ratio_max"):
        flags.append("high_pause_ratio")

    summary_metrics = {
        "f0_std_hz": pros["f0_std_hz"],
        "turning_points_per_sec": pros["f0_turning_points_per_sec"],
        "syllable_rate_hz": pros["rate_syllable_rate_hz"],
        "rate_cv": pros["rate_local_rate_cv"],
        "pause_ratio": pros["pauses_pause_speech_ratio"],
        "max_pause_sec": pros["pauses_max_pause_seconds"],
        "envelope_roughness": pros["energy_envelope_roughness"],
    }
    for summary_key, source_key in (
        ("pitch_std_semitones", "f0_std_semitones"),
        ("pitch_range_semitones", "f0_range_semitones"),
        ("boundary_discontinuity", "boundaries_max_sample_jump"),
        ("analyzer_peak_working_set_bytes", "analysisEstimatedPeakWorkingSetBytes"),
    ):
        if source_key in pros:
            summary_metrics[summary_key] = pros[source_key]

    return {
        "clip": pros.get("clip", ""),
        "analyzerAlgorithmVersion": pros.get(
            "analyzerAlgorithmVersion", ANALYZER_ALGORITHM_VERSION
        ),
        "passed": len(flags) == 0,
        "flags": flags,
        "reason": "; ".join(flags) if flags else "prosody gate passed",
        "metrics": summary_metrics,
    }


def main():
    ap = argparse.ArgumentParser(description="Reference-free prosody quality gate.")
    ap.add_argument("clips", nargs="*", help="WAV file(s) to evaluate")
    ap.add_argument("--json", action="store_true", help="emit JSON")
    ap.add_argument("--profile", help="path to a prosody profile JSON (default: built-in)")
    args = ap.parse_args()

    profile = None
    if args.profile:
        profile = load_profile(args.profile)

    if not args.clips:
        ap.print_help()
        return

    out = [evaluate(p, profile) for p in args.clips]
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
