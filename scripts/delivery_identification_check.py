#!/usr/bin/env python3
"""Score a blind delivery-identification session: what does a listener hear?

Every other measurement in this stack is *pairwise* -- is cell A distinguishable
from cell B. The standing product complaint ("at strong intensity it sounds like
angry") is a claim about which delivery a listener *attributes* to a clip, and
ten presets can be perfectly distinguishable from each other while a listener
still calls most of them angry. Difference is not identity, so no pairwise
instrument can confirm or refute it. This asks directly.

What it produces:

  * a human confusion matrix over our own synthesized speech -- the golden
    standard the project has never had, and the only ground truth that can
    validate or retire an acoustic gate;
  * per-preset recall, and for each preset the label listeners actually reach
    for, which may not be the requested one;
  * the attractor test: is one label pulled disproportionately at `strong`
    relative to `normal`, reported as a difference in proportions with a
    confidence interval rather than an impression;
  * self-consistency from exact repeats, which bounds how well any classifier
    could ever agree with this listener.

Listening is ground truth here, not a gate. Nothing consumes this verdict
automatically; it exists so acoustic measures can be checked against perception
instead of against each other.

Usage:
  scripts/delivery_identification_check.py --key key.json --answers answers.json
"""

from __future__ import annotations

import argparse
import collections
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

IDENTIFICATION_CHECK_VERSION = 1

UNSURE = "Unsure"


def _wilson(successes, trials, confidence=0.95):
    if trials <= 0:
        return None
    z = 1.959963984540054 if confidence == 0.95 else 1.959963984540054
    proportion = successes / trials
    denominator = 1.0 + z * z / trials
    centre = (proportion + z * z / (2 * trials)) / denominator
    spread = z * math.sqrt(
        proportion * (1.0 - proportion) / trials + z * z / (4 * trials * trials)
    ) / denominator
    return {
        "rate": round(proportion, 3),
        "lower": round(max(0.0, centre - spread), 3),
        "upper": round(min(1.0, centre + spread), 3),
        "n": trials,
    }


def _difference_interval(first_successes, first_n, second_successes, second_n, confidence=0.95):
    """Newcombe interval for a difference of two independent proportions.

    Built from the two Wilson intervals rather than a normal approximation,
    which behaves badly when either rate sits near zero -- and an attractor
    test is exactly the case where one side may be at or near zero.
    """
    first = _wilson(first_successes, first_n, confidence)
    second = _wilson(second_successes, second_n, confidence)
    if first is None or second is None:
        return None
    difference = first["rate"] - second["rate"]
    lower = difference - math.sqrt(
        (first["rate"] - first["lower"]) ** 2 + (second["upper"] - second["rate"]) ** 2
    )
    upper = difference + math.sqrt(
        (first["upper"] - first["rate"]) ** 2 + (second["rate"] - second["lower"]) ** 2
    )
    return {
        "difference": round(difference, 3),
        "lower": round(lower, 3),
        "upper": round(upper, 3),
        "excludesZero": lower > 0 or upper < 0,
    }


def evaluate_identification(key, answers):
    """Confusion matrix, per-preset recall, and the strong-tier attractor test."""
    by_id = {entry["id"]: entry for entry in key}
    trials = [
        (by_id[item_id], label)
        for item_id, label in sorted(answers.items())
        if item_id in by_id and by_id[item_id].get("kind") != "repeat"
    ]
    missing = sorted(set(by_id) - set(answers))
    unknown = sorted(set(answers) - set(by_id))

    # Exact repeats: the same recording labelled twice. Agreement here caps how
    # well any automated judge could ever match this listener.
    repeat_pairs = []
    for entry in key:
        if entry.get("kind") == "repeat" and entry.get("repeatOf"):
            first, second = answers.get(entry["repeatOf"]), answers.get(entry["id"])
            if first and second:
                repeat_pairs.append((first, second))
    self_agreement = None
    if repeat_pairs:
        agreed = sum(1 for first, second in repeat_pairs if first == second)
        self_agreement = {
            "n": len(repeat_pairs),
            "agreement": round(agreed / len(repeat_pairs), 3),
            "disagreements": [
                {"first": first, "second": second}
                for first, second in repeat_pairs if first != second
            ],
        }

    confusion = collections.defaultdict(collections.Counter)
    for entry, label in trials:
        confusion[entry["cell"]][label] += 1

    def preset_of(cell):
        return cell.split(".")[0]

    def expected_label(cell):
        return preset_of(cell).capitalize()

    per_cell = {}
    for cell, counts in sorted(confusion.items()):
        total = sum(counts.values())
        correct = counts.get(expected_label(cell), 0)
        unsure = counts.get(UNSURE, 0)
        ranked = [(label, n) for label, n in counts.most_common() if label != expected_label(cell)]
        per_cell[cell] = {
            "n": total,
            "recall": round(correct / total, 3) if total else 0.0,
            "unsureRate": round(unsure / total, 3) if total else 0.0,
            "topOtherLabel": ranked[0][0] if ranked else None,
            "topOtherCount": ranked[0][1] if ranked else 0,
            "labels": dict(counts),
        }

    per_preset = {}
    for preset in sorted({preset_of(cell) for cell in confusion}):
        counts = collections.Counter()
        for cell, cell_counts in confusion.items():
            if preset_of(cell) == preset:
                counts.update(cell_counts)
        total = sum(counts.values())
        correct = counts.get(preset.capitalize(), 0)
        per_preset[preset] = {
            "n": total,
            "recall": round(correct / total, 3) if total else 0.0,
            "accuracy": _wilson(correct, total),
            "mostCommonLabel": counts.most_common(1)[0][0] if counts else None,
            "labels": dict(counts),
        }

    labelled = [label for _, label in trials]
    decided = [label for label in labelled if label != UNSURE]
    correct_total = sum(
        1 for entry, label in trials if label == expected_label(entry["cell"])
    )

    # Attractor test: does any single label get pulled disproportionately at
    # `strong` relative to `normal`? Reported for every label so the answer is
    # not restricted to the one the complaint happened to name.
    strong = [(entry, label) for entry, label in trials if entry["cell"].endswith(".strong")]
    normal = [(entry, label) for entry, label in trials if entry["cell"].endswith(".normal")]
    attractors = {}
    for label in sorted(set(labelled)):
        strong_hits = sum(1 for _, chosen in strong if chosen == label)
        normal_hits = sum(1 for _, chosen in normal if chosen == label)
        interval = _difference_interval(strong_hits, len(strong), normal_hits, len(normal))
        if interval:
            attractors[label] = {
                "strong": _wilson(strong_hits, len(strong)),
                "normal": _wilson(normal_hits, len(normal)),
                "strongMinusNormal": interval,
            }
    significant = sorted(
        (label for label, entry in attractors.items()
         if entry["strongMinusNormal"]["excludesZero"]
         and entry["strongMinusNormal"]["difference"] > 0),
        key=lambda label: -attractors[label]["strongMinusNormal"]["difference"],
    )

    return {
        "checkVersion": IDENTIFICATION_CHECK_VERSION,
        "trials": len(trials),
        "overallAccuracy": _wilson(correct_total, len(trials)) if trials else None,
        "unsureRate": (
            round((len(labelled) - len(decided)) / len(labelled), 3) if labelled else 0.0
        ),
        "perPreset": per_preset,
        "perCell": per_cell,
        "attractors": attractors,
        "strongTierAttractors": significant,
        "selfAgreement": self_agreement,
        "missingAnswers": missing,
        "unknownItemIDs": unknown,
    }


def main():
    parser = argparse.ArgumentParser(description="Score a blind delivery-identification session")
    parser.add_argument("--key", required=True)
    parser.add_argument("--answers", required=True)
    parser.add_argument("--json", action="store_true")
    arguments = parser.parse_args()

    with open(arguments.key, "r", encoding="utf-8") as handle:
        key = json.load(handle)
    with open(arguments.answers, "r", encoding="utf-8") as handle:
        answers = json.load(handle)

    report = evaluate_identification(key, answers)
    if arguments.json:
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0

    accuracy = report["overallAccuracy"]
    print(f"delivery identification — {report['trials']} trials")
    if accuracy:
        print(f"  overall accuracy {accuracy['rate']}  95% CI [{accuracy['lower']}, {accuracy['upper']}]"
              f"   (chance ≈ {round(1 / max(len(report['perPreset']), 1), 3)})")
    print(f"  'not sure' used on {report['unsureRate']} of trials")
    agreement = report.get("selfAgreement")
    if agreement:
        print(f"  listener self-agreement on {agreement['n']} exact repeats: {agreement['agreement']}")

    print("\n  per preset (what listeners actually called it):")
    for preset in sorted(report["perPreset"], key=lambda p: report["perPreset"][p]["recall"]):
        entry = report["perPreset"][preset]
        note = "" if entry["mostCommonLabel"] == preset.capitalize() \
            else f"   most often heard as {entry['mostCommonLabel']}"
        print(f"    {preset:11} recall {entry['recall']:.2f}  (n={entry['n']}){note}")

    if report["strongTierAttractors"]:
        print("\n  labels pulled more at strong than at normal (interval excludes zero):")
        for label in report["strongTierAttractors"]:
            entry = report["attractors"][label]
            difference = entry["strongMinusNormal"]
            print(f"    {label:11} strong {entry['strong']['rate']} vs normal {entry['normal']['rate']}"
                  f"   difference {difference['difference']} [{difference['lower']}, {difference['upper']}]")
    else:
        print("\n  no label is pulled significantly more at strong than at normal")
    if report["missingAnswers"]:
        print(f"\n  missing answers: {len(report['missingAnswers'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
