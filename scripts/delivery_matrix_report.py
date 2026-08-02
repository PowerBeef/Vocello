#!/usr/bin/env python3
"""Cross-seed delivery matrix report: what each preset actually moves.

A single ``vocello bench --delivery`` run measures one seed. Adherence and
separability are cross-seed properties, so they can only be judged over a
sweep: this script merges the ``bench-prosody.json`` sidecars from N seeded
runs and answers the two questions the per-run gates cannot.

  1. For each preset, which features does it reliably move, and by how much?
     Every feature is a paired instructed-minus-neutral delta, so the question
     is whether that delta differs from zero across seeds. Reported with a
     Wilcoxon signed-rank p-value, Cohen's d_z, a BCa confidence interval and a
     win-rate with Wilson bounds -- then Benjamini-Hochberg across the features
     tested per preset, because a sweep this wide otherwise manufactures
     several discoveries every run.

  2. Do the presets stay distinguishable from each other, and does turning
     intensity up push them apart or pile them together? Delegated to
     delivery_separability.

Output feeds two decisions: which features to bind as `delivery_expectations`
(a feature that survives correction with a real effect size is a candidate;
one that does not is noise, whatever its win-rate looked like at n=8), and
which preset instructions need rewriting because their cells collapse.

Usage:
  scripts/delivery_matrix_report.py --matrix-dir sweep/ [--json out.json]
  scripts/delivery_matrix_report.py --sidecar a.json --sidecar b.json
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from delivery_separability import evaluate_separability, records_from_sidecar
from delivery_statistics import (
    benjamini_hochberg,
    bootstrap_ci,
    cohens_dz,
    wilcoxon_signed_rank,
    wilson_interval,
)
from prosody_profile import builtin_profile, load_profile

MATRIX_REPORT_VERSION = 1

# Summary axes and composites are reported, but expectation candidates are
# drawn from the primitive deltas: binding a composite hides which acoustic
# property actually moved, which is how the previous profile ended up unable
# to explain whisper or fearful.
_COMPOSITE_FEATURES = frozenset({
    "arousal_score", "voice_tension_score", "voice_breathiness_score", "duration_ratio",
})


def load_matrix(paths):
    """Merge bench sidecars into separability records, one seed per file."""
    records = []
    for path in paths:
        with open(path, "r", encoding="utf-8") as handle:
            rows = json.load(handle)
        seed = os.path.splitext(os.path.basename(path))[0]
        for record in records_from_sidecar(rows):
            # The sidecar's own seed field is the generation id, which is unique
            # per take; grouping folds by *run* is what keeps a take out of its
            # own training fold.
            record["seed"] = seed
            records.append(record)
    return records


def per_preset_statistics(records, false_discovery_rate=0.10):
    """Paired significance, effect size and win-rate per delivery cell feature."""
    by_cell = {}
    for record in records:
        cell = f"{record['preset']}.{record.get('intensity') or 'normal'}"
        by_cell.setdefault(cell, []).append(record["features"])

    report = {}
    for cell, feature_dicts in sorted(by_cell.items()):
        names = sorted({name for entry in feature_dicts for name in entry})
        rows = []
        for name in names:
            values = [
                float(entry[name]) for entry in feature_dicts
                if isinstance(entry.get(name), (int, float)) and not isinstance(entry.get(name), bool)
            ]
            if len(values) < 3:
                continue
            wins = sum(1 for value in values if value > 0)
            effect = cohens_dz(values)
            interval = bootstrap_ci(values)
            rows.append({
                "feature": name,
                "n": len(values),
                "median": round(sorted(values)[len(values) // 2], 4),
                "mean": round(sum(values) / len(values), 4),
                "cohensDz": round(effect, 3) if effect is not None else None,
                "wilcoxonP": wilcoxon_signed_rank(values)["pValue"],
                "winRate": round(wilson_interval(wins, len(values))["rate"], 3),
                "winRateLower": round(wilson_interval(wins, len(values))["lower"], 3),
                "ciLower": round(interval["lower"], 4) if interval else None,
                "ciUpper": round(interval["upper"], 4) if interval else None,
                "composite": name in _COMPOSITE_FEATURES,
            })
        corrected = benjamini_hochberg([row["wilcoxonP"] for row in rows], false_discovery_rate)
        for row, adjustment in zip(rows, corrected):
            row["adjustedP"] = adjustment["adjusted"]
            row["significant"] = adjustment["significant"]
        # Strongest first: a candidate expectation needs both survival after
        # correction and an effect worth asserting.
        rows.sort(key=lambda row: (not row["significant"], -abs(row["cohensDz"] or 0.0)))
        report[cell] = rows
    return report


def expectation_candidates(statistics, minimum_effect=0.8, minimum_win_rate=0.85):
    """Features a preset moves reliably enough to bind as an expectation.

    Deliberately stricter than "the median moved": the candidate must survive
    false-discovery correction, carry a large paired effect, and hold a
    win-rate whose *lower* Wilson bound clears the bar -- so a lucky sweep
    cannot promote a feature the next sweep drops.
    """
    candidates = {}
    for cell, rows in statistics.items():
        chosen = []
        for row in rows:
            if row["composite"] or not row["significant"]:
                continue
            if abs(row["cohensDz"] or 0.0) < minimum_effect:
                continue
            directional = max(row["winRate"], 1.0 - row["winRate"])
            if directional < minimum_win_rate:
                continue
            chosen.append({
                "feature": row["feature"],
                "direction": 1 if row["median"] > 0 else -1,
                "medianEffect": row["median"],
                "cohensDz": row["cohensDz"],
                "winRate": row["winRate"],
                "adjustedP": row["adjustedP"],
            })
        candidates[cell] = chosen
    return candidates


def build_report(records, profile=None, false_discovery_rate=0.10):
    profile = profile or builtin_profile()
    statistics = per_preset_statistics(records, false_discovery_rate)
    return {
        "reportVersion": MATRIX_REPORT_VERSION,
        "takeCount": len(records),
        "seedCount": len({record["seed"] for record in records}),
        "cellCount": len(statistics),
        "falseDiscoveryRate": false_discovery_rate,
        "separabilityByCell": evaluate_separability(records, profile, label_mode="cell"),
        "separabilityByPreset": evaluate_separability(records, profile, label_mode="preset"),
        "statistics": statistics,
        "expectationCandidates": expectation_candidates(statistics),
    }


def _print_summary(report):
    print(
        f"delivery matrix — {report['takeCount']} takes, {report['seedCount']} seeds, "
        f"{report['cellCount']} cells (BH q={report['falseDiscoveryRate']})"
    )
    for mode in ("separabilityByPreset", "separabilityByCell"):
        verdict = report[mode]
        metrics = verdict.get("metrics") or {}
        print(f"\n{mode}: {'PASS' if verdict['passed'] else 'WARN'} — {verdict['reason']}")
        if "uar" in metrics:
            print(f"  UAR {metrics['uar']}  macro-F1 {metrics['macroF1']}  "
                  f"features {metrics.get('featureCount')}")
        if "strongToNormalRatio" in metrics:
            print(f"  intensity spread — normal {metrics['normalMeanPairDistance']}, "
                  f"strong {metrics['strongMeanPairDistance']} "
                  f"(ratio {metrics['strongToNormalRatio']})")
        for cell in sorted(verdict.get("cells") or {}):
            entry = verdict["cells"][cell]
            print(f"    {cell:22} recall {entry['recall']:.2f}  n={entry['support']:<3}"
                  + (f"  nearest {entry.get('nearestCell')} @ {entry.get('nearestDistance')}"
                     if entry.get("nearestCell") else "")
                  + (f"  → {entry['topConfusion']}×{entry['topConfusionCount']}"
                     if entry.get("topConfusion") else ""))

    print("\nexpectation candidates (survive BH, |d_z| ≥ 0.8, win-rate ≥ 0.85):")
    for cell in sorted(report["expectationCandidates"]):
        chosen = report["expectationCandidates"][cell]
        if not chosen:
            print(f"  {cell:22} (none — this preset moves nothing reliably)")
            continue
        rendered = ", ".join(
            f"{item['feature']}{'+' if item['direction'] > 0 else '-'}"
            f"(d={item['cohensDz']}, med={item['medianEffect']})"
            for item in chosen[:4]
        )
        print(f"  {cell:22} {rendered}")


def main():
    parser = argparse.ArgumentParser(description="Cross-seed delivery matrix report")
    parser.add_argument("--matrix-dir", help="directory of per-seed bench-prosody sidecars")
    parser.add_argument("--sidecar", action="append", default=[], help="explicit sidecar path")
    parser.add_argument("--profile", help="calibrated prosody profile JSON")
    parser.add_argument("--fdr", type=float, default=0.10, help="Benjamini-Hochberg q")
    parser.add_argument("--json", help="write the full report to this path")
    arguments = parser.parse_args()

    paths = list(arguments.sidecar)
    if arguments.matrix_dir:
        paths.extend(sorted(glob.glob(os.path.join(arguments.matrix_dir, "*.json"))))
    if not paths:
        parser.error("give --matrix-dir or at least one --sidecar")

    profile = load_profile(arguments.profile) if arguments.profile else builtin_profile()
    records = load_matrix(paths)
    if not records:
        print("no delivery rows found in the given sidecars", file=sys.stderr)
        return 2

    report = build_report(records, profile, arguments.fdr)
    if arguments.json:
        with open(arguments.json, "w", encoding="utf-8") as handle:
            json.dump(report, handle, indent=2, sort_keys=True)
            handle.write("\n")
    _print_summary(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
