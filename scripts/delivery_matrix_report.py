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

  3. Does each cell adhere (audit #39)? The cell-level verdict
     (`delivery_quality_gate.evaluate_delivery_cell`) judges all of a cell's
     takes together against the profile floors, with `paired_report`
     annotations, and is reported beside the per-take flag rate it replaces as
     the warning channel (`cellAdherence`). The floors it reads are provisional
     until a pre-registered post-rewrite sweep re-derives them
     (`--emit-expectations`: half the observed median effect).

  4. Do the features depend on who speaks and how long the script is (audit
     #40)? `strata` reports every cell's features per speaker and script
     length, beside their semitone and ratio counterparts, with a confound
     index (range of the stratum medians over the pooled interquartile range)
     for each; the floors are refitted and the profile versioned only after a
     sweep with at least two speakers and two lengths per cell measures it.

Output feeds two decisions: which features to bind as `delivery_expectations`
(a feature that survives correction with a real effect size is a candidate;
one that does not is noise, whatever its win-rate looked like at n=8), and
which preset instructions need rewriting because their cells collapse.

Committed history records replay offline (`--records benchmarks/runs
--label-prefix dp22-normal`): their takes publish the paired features the
expectations bind (the last four since 2026-09-25), so a campaign is re-judged
without its untracked sidecars.

Usage:
  scripts/delivery_matrix_report.py --matrix-dir sweep/ [--json out.json]
  scripts/delivery_matrix_report.py --sidecar a.json --sidecar b.json
  scripts/delivery_matrix_report.py --records benchmarks/runs --label-prefix dp22-normal
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from delivery_quality_gate import CELL_ADHERENCE_ALGORITHM, evaluate_delivery_cell
from delivery_separability import evaluate_separability, records_from_sidecar
from delivery_statistics import (
    benjamini_hochberg,
    bootstrap_ci,
    cohens_dz,
    wilcoxon_signed_rank,
    wilson_interval,
)
from prosody_profile import builtin_profile, load_profile

MATRIX_REPORT_VERSION = 2

# Summary axes and composites are reported, but expectation candidates are
# drawn from the primitive deltas: binding a composite hides which acoustic
# property actually moved, which is how the previous profile ended up unable
# to explain whisper or fearful.
_COMPOSITE_FEATURES = frozenset({
    "arousal_score", "voice_tension_score", "voice_breathiness_score", "duration_ratio",
})

# Not a measurement: the profile's own intensity scaling constant, echoed into
# the gate metrics. It is 1.15 for every strong take regardless of the audio, so
# it reports a perfect effect size for a value nothing measured.
_NON_MEASUREMENT_FEATURES = frozenset({"intensity_factor"})


# Tracked take metric -> the paired feature the delivery gate names it.
HISTORY_FEATURE_METRICS = {
    "deliveryPitchShiftSemitones": "pitch_shift_semitones",
    "deliveryArousalScore": "arousal_score",
    "deliveryDF0StdHz": "pitch_variation_delta_hz",
    "deliveryDPauseRatio": "pause_ratio_delta",
    "deliveryDRateCV": "rate_cv_delta",
    "deliveryDRoughness": "roughness_delta",
    "deliveryVoiceTensionScore": "voice_tension_score",
    "deliveryVoiceBreathinessScore": "voice_breathiness_score",
    "deliveryVoicedFractionDelta": "voiced_fraction_delta",
    "deliveryTurningPointsDeltaPerSecond": "turning_points_delta_per_sec",
}


def records_from_history(paths, label_prefixes=()):
    """Delivery takes of committed history records, as matrix records.

    Every run of a campaign is one seed: the take's own seed when published,
    else its run. Per-take flags come from the legacy `delivery_gate:` warnings
    or, since gate v3, the `deliveryTakeFlagCount` diagnostic.
    """
    records = []
    for path in paths:
        with open(path, "r", encoding="utf-8") as handle:
            value = json.load(handle)
        record = value.get("historyRecord", value) if isinstance(value, dict) else {}
        run = record.get("run") or {}
        label = str(run.get("label") or "")
        if label_prefixes and not any(label.startswith(prefix) for prefix in label_prefixes):
            continue
        for take in record.get("takes") or []:
            cell = str(take.get("cell") or "")
            if "#delivery-" not in cell:
                continue
            delivery = cell.split("#delivery-", 1)[1]
            preset, separator, intensity = delivery.partition(".")
            metrics = take.get("metrics") or {}
            features = {
                feature: float(metrics[key])
                for key, feature in HISTORY_FEATURE_METRICS.items()
                if isinstance(metrics.get(key), (int, float)) and not isinstance(metrics.get(key), bool)
            }
            if not features:
                continue
            legacy_flags = [
                warning.split(":", 1)[1] for warning in take.get("warnings") or []
                if warning.startswith("delivery_gate:")
            ]
            flag_count = metrics.get("deliveryTakeFlagCount")
            records.append({
                "preset": preset,
                "intensity": intensity if separator else "normal",
                "seed": take.get("seed") if take.get("seed") is not None else run.get("id"),
                "speakerID": None,
                "length": take.get("length"),
                "scaleFreeFeatures": (
                    {"pitch_shift_semitones": features["pitch_shift_semitones"]}
                    if "pitch_shift_semitones" in features else {}
                ),
                "model": take.get("modelID") or take.get("variant"),
                "features": features,
                "deliveryFlags": legacy_flags,
                "deliveryFlagCount": int(flag_count) if isinstance(flag_count, (int, float)) else len(legacy_flags),
                "source": os.path.basename(path),
            })
    return records


def cell_adherence(records, profile):
    """The cell-level adherence verdict per cell, beside the per-take flag rate (audit #39)."""
    by_cell = {}
    for record in records:
        delivery = f"{record['preset']}.{record.get('intensity') or 'normal'}"
        key = (
            str(record.get("model") or ""), str(record.get("speakerID") or ""),
            str(record.get("length") or ""), delivery,
        )
        by_cell.setdefault(key, []).append(record)
    cells = {}
    for (model, speaker, length, delivery), members in sorted(by_cell.items()):
        verdict = evaluate_delivery_cell([member["features"] for member in members], delivery, profile)
        flagged = sum(
            1 for member in members
            if (member.get("deliveryFlagCount") if member.get("deliveryFlagCount") is not None
                else len(member.get("deliveryFlags") or [])) > 0
        )
        name = ":".join(part for part in (model, speaker, length, delivery) if part)
        cells[name] = {
            "status": verdict["status"],
            "flags": verdict["flags"],
            "takeCount": len(members),
            "takesWithPerTakeFlags": flagged,
            "features": verdict["features"],
        }
    judged = [cell for cell in cells.values() if cell["status"] in {"pass", "warn"}]
    takes = sum(cell["takeCount"] for cell in cells.values())
    return {
        "algorithm": CELL_ADHERENCE_ALGORITHM,
        "cellCount": len(cells),
        "judgedCells": len(judged),
        "warnedCells": sum(cell["status"] == "warn" for cell in judged),
        "insufficientCells": sum(cell["status"] == "insufficient" for cell in cells.values()),
        "takeCount": takes,
        "takesWithPerTakeFlags": sum(cell["takesWithPerTakeFlags"] for cell in cells.values()),
        "cells": cells,
    }


# Raw Hz or seconds features and the scale-free counterpart that should replace
# them if the stratified report shows the speaker or length confound (audit #40).
SCALE_FREE_COUNTERPARTS = {
    "pitch_variation_delta_hz": "pitch_variation_delta_semitones",
    "arousal_score": "pitch_shift_semitones",
    "rate_delta_hz": "rate_ratio",
}
# What a stratum comparison needs before its confound index means anything.
MINIMUM_STRATUM_TAKES = 5
STRATA_DATA_NEEDED = (
    "every judged cell run for at least two Built-in Voice speakers of different pitch registers "
    "and at least two script lengths, with at least five seeds per speaker, length and cell, "
    "analyzed from the bench-prosody sidecars (committed records carry no speaker name)"
)


def _quartile_range(values):
    ordered = sorted(values)
    if len(ordered) < 4:
        return None
    return ordered[(3 * len(ordered)) // 4] - ordered[len(ordered) // 4]


def stratified_features(records):
    """Per cell, each feature's median per (speaker, length) stratum and its confound index (audit #40)."""
    by_cell = {}
    for record in records:
        cell = f"{record['preset']}.{record.get('intensity') or 'normal'}"
        by_cell.setdefault(cell, []).append(record)
    cells = {}
    for cell, members in sorted(by_cell.items()):
        strata = {}
        for member in members:
            key = f"{member.get('speakerID') or 'unknown-speaker'}|{member.get('length') or 'unknown-length'}"
            strata.setdefault(key, []).append(member)
        features = {}
        names = sorted({
            name for member in members
            for name in [*member["features"], *(member.get("scaleFreeFeatures") or {})]
        } - _NON_MEASUREMENT_FEATURES)
        for name in names:
            def values_of(group):
                return [
                    float(source[name]) for source in (
                        member["scaleFreeFeatures"] if name in (member.get("scaleFreeFeatures") or {})
                        else member["features"] for member in group
                    )
                    if isinstance(source.get(name), (int, float)) and not isinstance(source.get(name), bool)
                ]
            pooled = values_of(members)
            if not pooled:
                continue
            medians = {}
            for key, group in sorted(strata.items()):
                values = values_of(group)
                if len(values) >= MINIMUM_STRATUM_TAKES:
                    medians[key] = round(sorted(values)[len(values) // 2], 4)
            spread = _quartile_range(pooled)
            index = (
                round((max(medians.values()) - min(medians.values())) / spread, 3)
                if len(medians) >= 2 and spread else None
            )
            features[name] = {
                "n": len(pooled), "strataJudged": len(medians), "strataMedians": medians,
                "pooledIQR": round(spread, 4) if spread is not None else None, "confoundIndex": index,
            }
        comparisons = {}
        for raw, scale_free in SCALE_FREE_COUNTERPARTS.items():
            if raw in features and scale_free in features:
                comparisons[raw] = {
                    "scaleFree": scale_free,
                    "rawConfoundIndex": features[raw]["confoundIndex"],
                    "scaleFreeConfoundIndex": features[scale_free]["confoundIndex"],
                }
        cells[cell] = {
            "strata": sorted(strata), "features": features, "scaleFreeComparisons": comparisons,
        }
    judged = any(
        feature["strataJudged"] >= 2 for cell in cells.values() for feature in cell["features"].values()
    )
    return {
        "minimumStratumTakes": MINIMUM_STRATUM_TAKES,
        "confoundMeasurable": judged,
        "dataNeeded": None if judged else STRATA_DATA_NEEDED,
        "cells": cells,
    }


def load_matrix(paths):
    """Merge bench sidecars while preserving real seed/speaker identities.

    Historical sidecars without a seed fall back to the filename. Current
    speaker-matrix rows must keep the engine-observed seed: replacing it with
    one filename per speaker would put another speaker's take with the same
    random seed in a training fold and overstate generalization.
    """
    records = []
    for path in paths:
        with open(path, "r", encoding="utf-8") as handle:
            rows = json.load(handle)
        fallback_seed = os.path.splitext(os.path.basename(path))[0]
        for record in records_from_sidecar(rows, fallback_seed=fallback_seed):
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
        names = sorted(
            {name for entry in feature_dicts for name in entry} - _NON_MEASUREMENT_FEATURES
        )
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


def intensity_ladder(statistics, minimum_effect=0.2):
    """Does `strong` actually amplify what `normal` does, per preset?

    The profile scales every expectation magnitude by ``intensity_scale``, so a
    strong take is held to a higher bar than its normal counterpart. That is
    only fair if the tier genuinely produces a larger effect. Where the ladder
    saturates, strong fails a bar it was never going to clear, and the fix
    belongs in the instruction rather than the threshold.

    For each preset, compares the median effect of every feature the normal
    tier moves against the same feature at strong, in normal's own direction.
    """
    ladder = {}
    for cell, rows in statistics.items():
        preset, _, intensity = cell.partition(".")
        if intensity != "normal":
            continue
        strong_rows = {row["feature"]: row for row in statistics.get(f"{preset}.strong", [])}
        amplified = []
        saturated = []
        reversed_features = []
        ratios = []
        for row in rows:
            if row["composite"] or abs(row["median"]) < minimum_effect:
                continue
            counterpart = strong_rows.get(row["feature"])
            if counterpart is None:
                continue
            # Project both onto normal's direction so "bigger" always means
            # "further along the axis the preset intends".
            sign = 1.0 if row["median"] > 0 else -1.0
            normal_effect = sign * row["median"]
            strong_effect = sign * counterpart["median"]
            if normal_effect <= 0:
                continue
            ratios.append(strong_effect / normal_effect)
            if strong_effect < 0:
                reversed_features.append(row["feature"])
            elif strong_effect >= normal_effect:
                amplified.append(row["feature"])
            else:
                saturated.append(row["feature"])
        if not ratios:
            continue
        ladder[preset] = {
            "featuresCompared": len(ratios),
            "medianStrongToNormalRatio": round(sorted(ratios)[len(ratios) // 2], 3),
            "amplified": sorted(amplified),
            "saturated": sorted(saturated),
            "reversed": sorted(reversed_features),
            "amplifiedFraction": round(len(amplified) / len(ratios), 3),
        }
    return ladder


def emit_expectations(candidates, required_per_preset=2, effect_fraction=0.5):
    """Derive a ``delivery_expectations.presets`` block from measured candidates.

    **A derived expectation is a regression guard, not a correctness standard.**
    It encodes what a preset currently does, so a later change that stops doing
    it is caught. It says nothing about whether the preset *should* do that --
    the project has never had a golden standard for delivery, and the previous
    hand-seeded expectations were written before any voice-quality measurement
    existed (finding F2 caught two of them being factually backwards). Judge
    whether a preset is any good with the instruction-independent criteria --
    separability between cells and intensity monotonicity within a preset --
    not by whether it satisfies expectations derived from its own behaviour.

    Follows the method the profile already documents -- required features carry
    a real measured effect, magnitudes sit near half the observed median -- but
    derives it from data rather than hand-tuning, so a recalibration is
    reproducible from the sweep it came from.

    A feature is promoted to ``required`` only when the preset's ``strong`` cell
    agrees in direction with its ``normal`` cell. Magnitudes come from the
    ``normal`` cell because the profile scales them by intensity, so binding a
    strong-tier magnitude would double-count the tier.
    """
    presets = {}
    for cell, chosen in candidates.items():
        preset, _, intensity = cell.partition(".")
        if intensity != "normal":
            continue
        strong_direction = {
            item["feature"]: item["direction"]
            for item in candidates.get(f"{preset}.strong", [])
        }
        features = {}
        for rank, item in enumerate(chosen):
            agrees = strong_direction.get(item["feature"]) == item["direction"]
            required = agrees and rank < required_per_preset
            features[item["feature"]] = {
                "direction": item["direction"],
                "min_effect_normal": (
                    round(abs(item["medianEffect"]) * effect_fraction, 4) if required else 0.0
                ),
                "tier": "required" if required else "supporting",
            }
        if features:
            presets[preset] = features
    return presets


def build_report(records, profile=None, false_discovery_rate=0.10):
    profile = profile or builtin_profile()
    statistics = per_preset_statistics(records, false_discovery_rate)
    candidates = expectation_candidates(statistics)
    speakers = sorted({
        str(record["speakerID"])
        for record in records
        if isinstance(record.get("speakerID"), str) and record["speakerID"]
    })
    per_speaker = {}
    for speaker in speakers:
        cohort = [record for record in records if record.get("speakerID") == speaker]
        per_speaker[speaker] = {
            "takeCount": len(cohort),
            "seedCount": len({record["seed"] for record in cohort}),
            "separabilityByPreset": evaluate_separability(
                cohort, profile, label_mode="preset"
            ),
        }

    held_out_speaker_records = [
        {**record, "seed": record.get("speakerID")}
        for record in records
        if record.get("speakerID")
    ]
    speaker_generalization = (
        evaluate_separability(
            held_out_speaker_records, profile, label_mode="preset"
        )
        if len(speakers) >= 2 else None
    )
    if speaker_generalization is not None:
        speaker_generalization.setdefault("metrics", {})["foldGrouping"] = "speaker-grouped"
        speaker_generalization["metrics"]["speakerCount"] = len(speakers)

    # Treat each speaker, rather than every take, as one independent unit for
    # feature-discovery statistics. This prevents five seeds from one voice
    # being counted as five independent speakers (pseudo-replication).
    speaker_balanced = []
    if speakers:
        by_speaker_cell = {}
        for record in records:
            speaker = record.get("speakerID")
            if not speaker:
                continue
            cell = (speaker, record["preset"], record.get("intensity") or "normal")
            by_speaker_cell.setdefault(cell, []).append(record["features"])
        for (speaker, preset, intensity), feature_rows in sorted(by_speaker_cell.items()):
            shared = set.intersection(*(set(row) for row in feature_rows)) if feature_rows else set()
            medians = {}
            for name in shared:
                values = sorted(
                    float(row[name]) for row in feature_rows
                    if isinstance(row.get(name), (int, float)) and not isinstance(row.get(name), bool)
                )
                if values:
                    medians[name] = values[len(values) // 2]
            speaker_balanced.append({
                "preset": preset,
                "intensity": intensity,
                "seed": speaker,
                "speakerID": speaker,
                "features": medians,
            })

    return {
        "reportVersion": MATRIX_REPORT_VERSION,
        "takeCount": len(records),
        "seedCount": len({record["seed"] for record in records}),
        "speakerCount": len(speakers),
        "speakers": speakers,
        "cellCount": len(statistics),
        "falseDiscoveryRate": false_discovery_rate,
        "separabilityByCell": evaluate_separability(records, profile, label_mode="cell"),
        "separabilityByPreset": evaluate_separability(records, profile, label_mode="preset"),
        "separabilityHeldOutSpeaker": speaker_generalization,
        "perSpeaker": per_speaker,
        "statistics": statistics,
        "speakerBalancedStatistics": (
            per_preset_statistics(speaker_balanced, false_discovery_rate)
            if speaker_balanced else {}
        ),
        "intensityLadder": intensity_ladder(statistics),
        "expectationCandidates": candidates,
        "derivedExpectations": emit_expectations(candidates),
        "cellAdherence": cell_adherence(records, profile),
        "strata": stratified_features(records),
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

    ladder = report.get("intensityLadder") or {}
    if ladder:
        print("\nintensity ladder (does strong amplify what normal does?):")
        for preset in sorted(ladder, key=lambda name: ladder[name]["amplifiedFraction"]):
            entry = ladder[preset]
            print(
                f"  {preset:12} {entry['amplifiedFraction']:.2f} amplified "
                f"({len(entry['amplified'])}/{entry['featuresCompared']}), "
                f"median ratio {entry['medianStrongToNormalRatio']}"
                + (f", reversed: {', '.join(entry['reversed'])}" if entry["reversed"] else "")
            )

    adherence = report.get("cellAdherence") or {}
    if adherence:
        print(
            f"\ncell adherence ({adherence['algorithm']}): {adherence['warnedCells']} of "
            f"{adherence['judgedCells']} judged cells warn, {adherence['insufficientCells']} insufficient; "
            f"per-take flags on {adherence['takesWithPerTakeFlags']} of {adherence['takeCount']} takes"
        )
        for name, cell in sorted(adherence["cells"].items()):
            if cell["status"] == "warn":
                print(f"  {name:32} {', '.join(cell['flags'])}")

    strata = report.get("strata") or {}
    if strata:
        if strata["confoundMeasurable"]:
            print("\nspeaker/length confound (range of stratum medians / pooled IQR):")
            for cell, entry in sorted(strata["cells"].items()):
                for raw, comparison in sorted(entry["scaleFreeComparisons"].items()):
                    print(f"  {cell:22} {raw} {comparison['rawConfoundIndex']} -> "
                          f"{comparison['scaleFree']} {comparison['scaleFreeConfoundIndex']}")
        else:
            print(f"\nspeaker/length confound: not measurable here; needs {strata['dataNeeded']}")

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
    parser.add_argument(
        "--records", action="append", default=[],
        help="committed history record(s) or a directory of them (replays their delivery takes)",
    )
    parser.add_argument(
        "--label-prefix", action="append", default=[],
        help="with --records: keep only runs whose label starts with this prefix",
    )
    parser.add_argument("--profile", help="calibrated prosody profile JSON")
    parser.add_argument("--fdr", type=float, default=0.10, help="Benjamini-Hochberg q")
    parser.add_argument("--json", help="write the full report to this path")
    parser.add_argument(
        "--emit-expectations",
        help="write the derived delivery_expectations.presets block to this path",
    )
    arguments = parser.parse_args()

    paths = list(arguments.sidecar)
    if arguments.matrix_dir:
        paths.extend(sorted(glob.glob(os.path.join(arguments.matrix_dir, "*.json"))))
    history_paths = []
    for item in arguments.records:
        if os.path.isdir(item):
            history_paths.extend(sorted(glob.glob(os.path.join(item, "**", "*.json"), recursive=True)))
        else:
            history_paths.append(item)
    if not paths and not history_paths:
        parser.error("give --matrix-dir, at least one --sidecar, or --records")

    profile = load_profile(arguments.profile) if arguments.profile else builtin_profile()
    records = load_matrix(paths) + records_from_history(history_paths, tuple(arguments.label_prefix))
    if not records:
        print("no delivery rows found in the given sidecars", file=sys.stderr)
        return 2

    report = build_report(records, profile, arguments.fdr)
    if arguments.json:
        with open(arguments.json, "w", encoding="utf-8") as handle:
            json.dump(report, handle, indent=2, sort_keys=True)
            handle.write("\n")
    if arguments.emit_expectations:
        with open(arguments.emit_expectations, "w", encoding="utf-8") as handle:
            json.dump(report["derivedExpectations"], handle, indent=2, sort_keys=True)
            handle.write("\n")
    _print_summary(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
