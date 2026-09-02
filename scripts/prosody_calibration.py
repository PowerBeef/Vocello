#!/usr/bin/env python3
"""Calibrate a prosody profile from a labeled good/bad corpus.

Reads a JSONL label file where each line is:

  {"path": "clips/good_01.wav", "label": "good"}
  {"path": "clips/bad_01.wav", "label": "bad"}

Runs scripts/analyze_prosody.py on every clip, then sets each threshold so that
approximately `--target-fpr` of the good clips would be flagged by that specific
metric (independent of the boolean combinations used by the gate). This gives a
principled, corpus-specific starting point. Validate the resulting profile against
a held-out labeled corpus before using it for autonomous pass/fail decisions.

Usage:
  scripts/prosody_calibration.py --labels labels.jsonl --out profile.json
"""
import argparse
import datetime as dt
import hashlib
import json
import math
import os
from pathlib import Path
import secrets
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build_output_policy import load_policy
from prosody_profile import builtin_profile, save_profile, SCHEMA_VERSION


def analyze(path):
    """Load the optional NumPy analyzer only for an actual calibration run."""
    from analyze_prosody import analyze as analyze_wav

    return analyze_wav(path)


def analyzer_algorithm_version():
    """Resolve the optional analyzer only for an actual calibration run."""
    from analyze_prosody import ANALYZER_ALGORITHM_VERSION

    return ANALYZER_ALGORITHM_VERSION


# Map threshold key -> (metric key, direction) where direction "low" means the
# flag fires when metric < threshold, "high" means metric > threshold.
THRESHOLD_MAP = {
    "monotone_f0_std_hz": ("f0_std_hz", "low"),
    "monotone_turning_points_per_sec": ("f0_turning_points_per_sec", "low"),
    "rushed_syllable_rate_hz": ("rate_syllable_rate_hz", "high"),
    "rushed_max_pause_ratio": ("pauses_pause_speech_ratio", "low"),
    "flat_envelope_roughness": ("energy_envelope_roughness", "low"),
    "flat_rate_cv": ("rate_local_rate_cv", "low"),
    "pause_max_seconds": ("pauses_max_pause_seconds", "high"),
    "pause_ratio_max": ("pauses_pause_speech_ratio", "high"),
}


def load_labels(path):
    """Load labels, resolving relative clip paths beside the JSONL file."""
    entries = []
    labels_dir = os.path.dirname(os.path.abspath(path))
    with open(path, "r", encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError as e:
                raise ValueError(f"labels:{i}: invalid JSON: {e}")
            label = str(entry.get("label", "")).lower()
            if label not in {"good", "bad"}:
                raise ValueError(f"labels:{i}: label must be 'good' or 'bad', got {entry.get('label')!r}")
            clip_path = entry.get("path")
            if not isinstance(clip_path, str) or not clip_path:
                raise ValueError(f"labels:{i}: path must be a non-empty string")
            if not os.path.isabs(clip_path):
                clip_path = os.path.join(labels_dir, clip_path)
            entry["path"] = os.path.normpath(clip_path)
            entry["label"] = label
            entries.append(entry)
    return entries


def analyze_corpus(entries):
    """Return (good_metrics, bad_metrics) as dict-of-lists plus a summary."""
    good = {m: [] for m, _ in THRESHOLD_MAP.values()}
    bad = {m: [] for m, _ in THRESHOLD_MAP.values()}
    errors = []
    for entry in entries:
        path = entry["path"]
        pros = analyze(path)
        if "error" in pros:
            errors.append((path, pros["error"]))
            continue
        bucket = good if entry["label"] == "good" else bad
        for metric, _ in THRESHOLD_MAP.values():
            bucket[metric].append(pros.get(metric, 0.0))
    return good, bad, errors


def corpus_digest(entries):
    """Hash the labeled corpus semantics and every referenced WAV byte.

    Path strings are deliberately excluded: the same corpus should identify
    the same way after a checkout moves, while a label or split-metadata change,
    ordering change, missing clip, or one-byte audio change must alter the digest.
    """
    digest = hashlib.sha256(b"vocello-prosody-corpus-v1\0")
    for index, entry in enumerate(entries):
        clip = Path(entry["path"])
        if not clip.is_file():
            raise ValueError(f"corpus clip does not exist: {clip}")
        digest.update(str(index).encode("ascii"))
        digest.update(b"\0")
        semantics = {key: value for key, value in entry.items() if key != "path"}
        digest.update(
            json.dumps(
                semantics,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        )
        digest.update(b"\0")
        digest.update(hashlib.sha256(clip.read_bytes()).digest())
    return digest.hexdigest()


def percentile_value(values, q):
    """Return the q-th percentile of a list of floats, or nan if empty."""
    if not values:
        return math.nan
    import numpy as np

    return float(np.percentile(np.array(values, dtype=float), q))


def calibrate_thresholds(good, bad, target_fpr):
    """Pick thresholds from good-clip distributions targeting target_fpr."""
    thresholds = {}
    for key, (metric, direction) in THRESHOLD_MAP.items():
        good_vals = good.get(metric, [])
        bad_vals = bad.get(metric, [])
        if not good_vals:
            # No good examples to calibrate from — keep builtin default.
            thresholds[key] = builtin_profile()["thresholds"][key]
            continue
        if direction == "low":
            # Flag values below threshold. Choose a low percentile of good clips
            # so only the most extreme low values trip.
            q = max(0.0, min(100.0, target_fpr * 100.0))
            value = percentile_value(good_vals, q)
        else:
            q = max(0.0, min(100.0, (1.0 - target_fpr) * 100.0))
            value = percentile_value(good_vals, q)
        if math.isnan(value):
            thresholds[key] = builtin_profile()["thresholds"][key]
            continue
        # Clamp to the observed bad-clip range when it is stricter, so obviously
        # defective clips remain flagged if the good distribution is very tight.
        if bad_vals:
            if direction == "low":
                value = min(value, percentile_value(bad_vals, 25.0))
            else:
                value = max(value, percentile_value(bad_vals, 75.0))
        # Round to a sensible precision for readability.
        if key in {"monotone_f0_std_hz", "monotone_turning_points_per_sec", "rushed_syllable_rate_hz"}:
            thresholds[key] = round(value, 2)
        else:
            thresholds[key] = round(value, 3)
    return thresholds


def evaluate_profile(profile, good, bad):
    """Compute flag rates on the labeled corpus using the gate logic."""
    thr = profile["thresholds"]

    def flags(metrics):
        f = []
        if metrics["f0_std_hz"] < thr["monotone_f0_std_hz"] and metrics["f0_turning_points_per_sec"] < thr["monotone_turning_points_per_sec"]:
            f.append("monotone")
        if metrics["rate_syllable_rate_hz"] > thr["rushed_syllable_rate_hz"] and metrics["pauses_pause_speech_ratio"] < thr["rushed_max_pause_ratio"]:
            f.append("rushed")
        if metrics["energy_envelope_roughness"] < thr["flat_envelope_roughness"] and metrics["rate_local_rate_cv"] < thr["flat_rate_cv"]:
            f.append("flat")
        if metrics["pauses_max_pause_seconds"] > thr["pause_max_seconds"]:
            f.append("long_pause")
        if metrics["pauses_pause_speech_ratio"] > thr["pause_ratio_max"]:
            f.append("high_pause_ratio")
        return f

    def flagged(bucket):
        return [m for m in bucket if flags(m)]

    good_flagged = flagged(good)
    bad_flagged = flagged(bad)
    n_good = len(good)
    n_bad = len(bad)
    return {
        "good_flag_rate": len(good_flagged) / n_good if n_good else 0.0,
        "bad_flag_rate": len(bad_flagged) / n_bad if n_bad else 0.0,
        "false_positive_rate": len(good_flagged) / n_good if n_good else 0.0,
        "true_positive_rate": len(bad_flagged) / n_bad if n_bad else 0.0,
    }


def main():
    ap = argparse.ArgumentParser(description="Calibrate a prosody profile from labeled WAVs.")
    ap.add_argument("--labels", required=True, help="JSONL of {path, label} entries (label: good|bad)")
    ap.add_argument("--out", required=True, help="output profile JSON path")
    ap.add_argument("--target-fpr", type=float, default=0.05,
                    help="target per-metric false-positive rate on good clips (default 0.05)")
    ap.add_argument("--name", default="calibrated", help="profile name")
    ap.add_argument("--description", default="", help="profile description")
    args = ap.parse_args()
    started_at = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    run_id = (
        "prosody-calibration-"
        + dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d-%H%M%S-")
        + secrets.token_hex(4)
    )
    root = Path(__file__).resolve().parents[1]
    test_history_disabled = os.environ.get("QVOICE_BENCHMARK_HISTORY_TEST_DISABLE") == "1"
    output_policy = load_policy(root)
    artifact_dir = (
        root
        / output_policy.entries_by_id["artifacts-macos"]["path"]
        / "prosody-calibration"
        / run_id
    )
    snapshot = artifact_dir / "benchmark-source.json"
    if not test_history_disabled:
        artifact_dir.mkdir(parents=True, exist_ok=False)
        snapshot_command = [
            sys.executable, str(root / "scripts" / "publish_benchmark_history.py"),
            "snapshot", "--output", str(snapshot), "--crash-scope", "none",
        ]
        captured = subprocess.run(snapshot_command, cwd=root, text=True, capture_output=True)
        if captured.returncode:
            sys.exit(
                "could not capture pre-run source provenance: "
                + (captured.stderr.strip() or captured.stdout.strip())
            )

    if not (0 < args.target_fpr < 1):
        sys.exit("--target-fpr must be between 0 and 1")

    entries = load_labels(args.labels)
    if len(entries) < 4:
        sys.exit(f"need at least 4 labeled clips, got {len(entries)}")

    good, bad, errors = analyze_corpus(entries)
    if errors:
        print(f"analysis failed for {len(errors)} clip(s):", file=sys.stderr)
        for path, err in errors[:5]:
            print(f"  {path}: {err}", file=sys.stderr)
        sys.exit("calibration requires every labeled clip to analyze successfully")

    n_good = sum(1 for e in entries if e["label"] == "good")
    n_bad = sum(1 for e in entries if e["label"] == "bad")
    if n_good < 2 or n_bad < 2:
        sys.exit(f"need at least 2 good and 2 bad clips (good={n_good}, bad={n_bad})")

    labels_digest = corpus_digest(entries)
    thresholds = calibrate_thresholds(good, bad, args.target_fpr)
    profile = builtin_profile()
    profile["name"] = args.name
    profile["description"] = args.description or f"Calibrated from {n_good} good / {n_bad} bad clips at target_fpr={args.target_fpr}"
    profile["thresholds"] = thresholds
    # Profile schema v1 remains readable.  This optional field binds newly
    # calibrated values to the bounded analyzer methodology whose fixed-bin
    # percentiles can drift slightly from the legacy full-array implementation.
    current_analyzer_version = analyzer_algorithm_version()
    profile["analyzer_algorithm_version"] = current_analyzer_version
    profile["calibration_corpus_digest"] = labels_digest

    # Convert good/bad metric dicts to lists of dicts for evaluation.
    good_records = [dict(zip(good.keys(), vals)) for vals in zip(*good.values())]
    bad_records = [dict(zip(bad.keys(), vals)) for vals in zip(*bad.values())]
    stats = evaluate_profile(profile, good_records, bad_records)

    save_profile(profile, args.out)
    result = {
        "schemaVersion": 1,
        "analyzerAlgorithmVersion": current_analyzer_version,
        "runID": run_id,
        # Profile names remain human-facing metadata. The tracked benchmark label
        # is the opaque run ID and never copies this free-form description.
        "label": run_id,
        "startedAt": started_at,
        "finishedAt": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "status": "pass",
        "analysisFailureCount": 0,
        "goodClipCount": n_good,
        "badClipCount": n_bad,
        "targetFalsePositiveRate": args.target_fpr,
        "corpusDigest": labels_digest,
        "profileDigest": hashlib.sha256(Path(args.out).read_bytes()).hexdigest(),
        "flagRates": stats,
    }
    if not test_history_disabled:
        result_path = artifact_dir / "calibration-results.json"
        result_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        publish_command = [
            sys.executable, str(root / "scripts" / "publish_benchmark_history.py"),
            "prosody", "--artifact-dir", str(artifact_dir), "--snapshot", str(snapshot),
            "--results", str(result_path), "--profile", str(Path(args.out).resolve()),
        ]
        published = subprocess.run(publish_command, cwd=root, text=True, capture_output=True)
        if published.returncode:
            detail = published.stderr.strip() or published.stdout.strip()
            sys.exit(f"history publication failed: {detail}")
    print(f"wrote {args.out}")
    print(f"  clips: {n_good} good, {n_bad} bad; analysis errors: {len(errors)}")
    print(f"  calibrated thresholds: {json.dumps(thresholds, indent=2)}")
    print(f"  flag rates — good={stats['good_flag_rate']:.2%}, bad={stats['bad_flag_rate']:.2%}, "
          f"fpr={stats['false_positive_rate']:.2%}, tpr={stats['true_positive_rate']:.2%}")
    print("\nNOTE: validate thresholds on a held-out labeled corpus before promotion; target-fpr is "
          "per-metric, and boolean combinations may flag fewer good clips than the printed "
          "false-positive rate.")


if __name__ == "__main__":
    main()
