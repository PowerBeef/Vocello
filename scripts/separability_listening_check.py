#!/usr/bin/env python3
"""Score a blind listening session against the separability metric.

This validates **the instrument, not the takes**. The separability gate decides
which delivery presets are too alike to ship, so it needs to have earned that
authority: if a listener cannot hear the difference between the pairs it calls
distinct, or hears an obvious difference between the pairs it calls
interchangeable, the metric is what needs fixing before any preset does.

That distinction matters because the project has never had a golden standard
for delivery. The previous expectations were seeded from guesses at acoustic
correlates and calibrated against an analyzer that measured only arousal, so
"the gate failed" has never been evidence a preset is wrong. Anchoring the
metric to perception once, on pairs chosen by the metric's own distance scale,
is what makes its later verdicts mean something.

Listening is used here to *calibrate an instrument*, never to grade a take.
The repo's standing rule is unchanged: a human verdict cannot clear a machine
failure, and no gate consumes this output.

Inputs:
  key      the pair manifest emitted with the blind set: bucket, cells, distance
  ratings  {pair_id: 1..4}, 1 = "the same", 4 = "a different emotion"

Reports:
  * Spearman rank correlation between metric distance and perceived difference
  * mean rating per distance bucket, and whether they order correctly
  * an identity-control check -- rating the same recording twice as different
    means the session was guessing and everything else should be discounted
  * the pairs where metric and ear disagree most, which are the specific cases
    to investigate

Usage:
  scripts/separability_listening_check.py --key key.json --ratings answers.json
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

LISTENING_CHECK_VERSION = 1

# A listener who calls the identical recording "noticeably different" is not
# attending to the task; at or above this the session is not usable.
IDENTITY_CONTROL_MAX_RATING = 2
# Below this, the metric's ordering does not track perception well enough to
# arbitrate preset decisions on its own.
MINIMUM_TRUSTWORTHY_CORRELATION = 0.5


def _ranks(values):
    """Ranks starting at 1, ties sharing their average rank."""
    order = sorted(range(len(values)), key=lambda index: values[index])
    ranks = [0.0] * len(values)
    position = 0
    while position < len(order):
        end = position
        while end + 1 < len(order) and values[order[end + 1]] == values[order[position]]:
            end += 1
        average = 0.5 * (position + end) + 1.0
        for index in range(position, end + 1):
            ranks[order[index]] = average
        position = end + 1
    return ranks


def spearman(first, second):
    """Rank correlation, tie-aware, with no SciPy dependency."""
    if len(first) != len(second):
        raise ValueError("paired inputs must be the same length")
    if len(first) < 3:
        return None
    a_ranks, b_ranks = _ranks(first), _ranks(second)
    a_mean = sum(a_ranks) / len(a_ranks)
    b_mean = sum(b_ranks) / len(b_ranks)
    covariance = sum((a - a_mean) * (b - b_mean) for a, b in zip(a_ranks, b_ranks))
    a_spread = math.sqrt(sum((a - a_mean) ** 2 for a in a_ranks))
    b_spread = math.sqrt(sum((b - b_mean) ** 2 for b in b_ranks))
    if a_spread <= 0 or b_spread <= 0:
        return None
    return covariance / (a_spread * b_spread)


def evaluate_listening(key, ratings):
    """Compare a listening session against the metric that chose its pairs."""
    by_id = {entry["id"]: entry for entry in key}
    missing = sorted(set(by_id) - set(ratings))
    unknown = sorted(set(ratings) - set(by_id))

    scored = [
        (by_id[pair_id], float(rating))
        for pair_id, rating in sorted(ratings.items())
        if pair_id in by_id
    ]
    controls = [(entry, rating) for entry, rating in scored if entry["bucket"] == "identity"]
    judged = [(entry, rating) for entry, rating in scored if entry["bucket"] != "identity"]

    failed_controls = [
        entry["id"] for entry, rating in controls if rating > IDENTITY_CONTROL_MAX_RATING
    ]

    buckets = {}
    for name in ("close", "mid", "far"):
        values = [rating for entry, rating in judged if entry["bucket"] == name]
        if values:
            buckets[name] = {
                "n": len(values),
                "meanRating": round(sum(values) / len(values), 2),
            }
    ordered = (
        len(buckets) == 3
        and buckets["close"]["meanRating"]
        <= buckets["mid"]["meanRating"]
        <= buckets["far"]["meanRating"]
    )

    correlation = spearman(
        [entry["distance"] for entry, _ in judged],
        [rating for _, rating in judged],
    )

    # Where metric and ear disagree most: rank both, and report the pairs whose
    # ranks are furthest apart. These are the concrete cases to go listen to.
    disagreements = []
    if len(judged) >= 3:
        distance_ranks = _ranks([entry["distance"] for entry, _ in judged])
        rating_ranks = _ranks([rating for _, rating in judged])
        for (entry, rating), metric_rank, heard_rank in zip(judged, distance_ranks, rating_ranks):
            disagreements.append({
                "pair": entry["id"],
                "cells": [entry["a"], entry["b"]],
                "distance": entry["distance"],
                "rating": rating,
                "rankGap": round(abs(metric_rank - heard_rank), 1),
            })
        disagreements.sort(key=lambda item: -item["rankGap"])

    trustworthy = (
        not failed_controls
        and correlation is not None
        and correlation >= MINIMUM_TRUSTWORTHY_CORRELATION
        and ordered
    )
    if failed_controls:
        verdict = "session_unusable"
    elif trustworthy:
        verdict = "metric_tracks_perception"
    else:
        verdict = "metric_does_not_track_perception"

    return {
        "checkVersion": LISTENING_CHECK_VERSION,
        "verdict": verdict,
        "trustworthy": trustworthy,
        "spearman": round(correlation, 3) if correlation is not None else None,
        "bucketMeans": buckets,
        "bucketsOrderedCorrectly": ordered,
        "identityControls": {
            "n": len(controls),
            "failed": failed_controls,
            "maximumAcceptableRating": IDENTITY_CONTROL_MAX_RATING,
        },
        "ratedPairs": len(judged),
        "missingRatings": missing,
        "unknownPairIDs": unknown,
        "largestDisagreements": disagreements[:5],
    }


def main():
    parser = argparse.ArgumentParser(description="Score a blind separability listening session")
    parser.add_argument("--key", required=True, help="pair manifest from the blind set")
    parser.add_argument("--ratings", required=True, help="JSON {pair_id: 1..4}")
    parser.add_argument("--json", action="store_true", help="emit the report as JSON")
    arguments = parser.parse_args()

    with open(arguments.key, "r", encoding="utf-8") as handle:
        key = json.load(handle)
    with open(arguments.ratings, "r", encoding="utf-8") as handle:
        ratings = json.load(handle)

    report = evaluate_listening(key, ratings)
    if arguments.json:
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0 if report["trustworthy"] else 1

    print(f"listening check: {report['verdict']}")
    print(f"  Spearman(metric distance, perceived difference) = {report['spearman']}")
    for name in ("close", "mid", "far"):
        entry = report["bucketMeans"].get(name)
        if entry:
            print(f"  {name:6} mean rating {entry['meanRating']}  (n={entry['n']})")
    print(f"  buckets ordered correctly: {report['bucketsOrderedCorrectly']}")
    controls = report["identityControls"]
    print(f"  identity controls: {controls['n']}, failed: {controls['failed'] or 'none'}")
    if report["missingRatings"]:
        print(f"  missing ratings: {', '.join(report['missingRatings'])}")
    if report["largestDisagreements"]:
        print("  biggest metric/ear disagreements:")
        for item in report["largestDisagreements"]:
            print(f"    {item['pair']}  {' vs '.join(item['cells'])}  "
                  f"distance {item['distance']}, heard {int(item['rating'])}  "
                  f"(rank gap {item['rankGap']})")
    return 0 if report["trustworthy"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
