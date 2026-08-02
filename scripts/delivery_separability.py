#!/usr/bin/env python3
"""Cross-preset separability for Vocello delivery takes.

Every other delivery check asks "did this preset move prosody in its own
intended direction?".  None of them asks "does this preset still sound like
*itself* rather than like its neighbour?", and that gap is exactly where the
standing complaint lives: at ``strong`` intensity the hot presets all maximise
the same arousal-bearing features, each one passes its own direction check, and
the suite reports success while a listener hears one generic intense voice.

This module measures the missing property.  Each take contributes the signed
paired feature vector the delivery gate already computes (instructed versus its
same-seed neutral), the takes are labelled by the delivery cell that requested
them, and a classifier is fitted and cross-validated across seeds.  The label is
the *request*, not a human rating, so the measurement stays autonomous; and the
model is fitted on our own output, so it is in-domain by construction -- which
matters, because off-the-shelf speech-emotion models do not transfer to
synthesized speech (emotion2vec drops from 99.6% on human TESS to 15.3% on
synthesized audio, ACL 2026 arXiv 2603.16483).

If the classifier cannot tell two cells apart, the acoustic difference a
listener would need is genuinely absent.  That is the finding, not a defect of
the measurement.

Method (closed-form, deterministic, NumPy only -- no new pinned dependency):

* features are z-scored using the training fold's own statistics;
* a linear discriminant (per-cell centroids sharing one ridge-regularized
  pooled covariance) assigns each held-out take to its nearest centroid in
  Mahalanobis distance;
* folds are grouped by seed, so a seed never appears in both train and test --
  a take and its own paired neutral cannot leak across the split;
* reported per cell: recall, nearest confusable neighbour, and the pairwise
  centroid separation used to decide confusability.

Aggregate scores use UAR (unweighted average recall) and macro-F1 rather than
accuracy, because delivery cells are unbalanced whenever a take fails QC.

Usage:
  scripts/delivery_separability.py --sidecar bench-prosody.json [--json]
  scripts/delivery_separability.py --records records.json [--label-mode preset]
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from prosody_profile import builtin_profile, load_profile, separability_bound

SEPARABILITY_ALGORITHM_VERSION = 1

# Verdict could not be computed rather than "the presets are indistinguishable".
ANALYSIS_FAILURE_FLAGS = (
    "cohort_too_small",
    "insufficient_cells",
    "insufficient_features",
    "insufficient_seeds",
    "separability_underpowered",
)

_EXCLUDED_FEATURES = frozenset({
    # Ratios of absolute duration are seed-dependent scale, not delivery colour.
    "duration_ratio",
})


def _cell_label(record, label_mode):
    preset = record.get("preset")
    intensity = record.get("intensity") or "normal"
    if not preset:
        raise ValueError("every record needs a preset")
    return preset if label_mode == "preset" else f"{preset}.{intensity}"


def _shared_feature_names(records):
    """Features present and finite in every record, in stable sorted order.

    A feature missing from any take is dropped rather than imputed: analyzer-v2
    rows carry no voice-quality block, and silently substituting zeros would
    manufacture separation that the audio does not contain.
    """
    shared = None
    for record in records:
        usable = {
            name for name, value in (record.get("features") or {}).items()
            if name not in _EXCLUDED_FEATURES
            and isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(float(value))
        }
        shared = usable if shared is None else (shared & usable)
    return sorted(shared or ())


def _matrix(records, feature_names):
    import numpy as np

    return np.array(
        [[float(record["features"][name]) for name in feature_names] for record in records],
        dtype=np.float64,
    )


def _fit_discriminant(train, labels_of_train, cells, ridge):
    """Per-cell centroids plus one ridge-regularized pooled covariance."""
    import numpy as np

    dimensions = train.shape[1]
    centroids = {}
    scatter = np.zeros((dimensions, dimensions), dtype=np.float64)
    degrees_of_freedom = 0
    for cell in cells:
        rows = train[[index for index, label in enumerate(labels_of_train) if label == cell]]
        if not len(rows):
            continue
        centroids[cell] = rows.mean(axis=0)
        if len(rows) > 1:
            centered = rows - centroids[cell]
            scatter += centered.T @ centered
            degrees_of_freedom += len(rows) - 1
    pooled = scatter / max(degrees_of_freedom, 1)
    # Ridge keeps the inverse well-conditioned when a fold has fewer takes than
    # features, which is the normal case early in a calibration sweep.
    pooled += ridge * np.eye(dimensions)
    return centroids, np.linalg.pinv(pooled)


def _mahalanobis(delta, precision):
    import numpy as np

    return float(math.sqrt(max(float(delta @ precision @ delta), 0.0)))


def _predict(rows, centroids, precision, cells):
    import numpy as np

    ordered = [cell for cell in cells if cell in centroids]
    if not ordered:
        return []
    distances = np.stack(
        [
            np.einsum("ij,jk,ik->i", rows - centroids[cell], precision, rows - centroids[cell])
            for cell in ordered
        ],
        axis=1,
    )
    return [ordered[index] for index in distances.argmin(axis=1)]


def evaluate_separability(records, profile=None, label_mode="cell"):
    """Cross-validated separability verdict over paired delivery feature vectors.

    ``records`` is a sequence of ``{preset, intensity, seed, features}`` dicts.
    Returns a warn-first verdict mirroring the other delivery gates.
    """
    profile = profile or builtin_profile()
    minimum_seeds = int(separability_bound(profile, "minimum_seeds_per_cell"))
    minimum_recall = float(separability_bound(profile, "minimum_cell_recall"))
    minimum_margin = float(separability_bound(profile, "minimum_pair_margin"))
    collapse_ratio = float(separability_bound(profile, "intensity_collapse_ratio"))
    ridge = float(separability_bound(profile, "covariance_ridge"))

    def failure(flag, reason):
        return {
            "algorithmVersion": SEPARABILITY_ALGORITHM_VERSION,
            "passed": False,
            "flags": [flag],
            "reason": reason,
            "labelMode": label_mode,
            "cells": {},
            "metrics": {},
        }

    records = [record for record in (records or []) if record.get("features")]
    if len(records) < 2:
        return failure("cohort_too_small", "separability needs at least two takes")

    labels = [_cell_label(record, label_mode) for record in records]
    seeds = [str(record.get("seed", "")) for record in records]
    cells = sorted(set(labels))
    if len(cells) < 2:
        return failure("insufficient_cells", "separability needs at least two delivery cells")
    if len(set(seeds)) < 2:
        return failure("insufficient_seeds", "separability needs takes from at least two seeds")

    thin = sorted({cell for cell in cells if labels.count(cell) < minimum_seeds})
    feature_names = _shared_feature_names(records)
    if len(feature_names) < 2:
        return failure(
            "insufficient_features",
            "fewer than two features are present in every take; "
            "mixing analyzer-v2 and v3 rows drops the voice-quality block",
        )

    # The pooled covariance is estimated from (takes - cells) degrees of
    # freedom.  With fewer of those than features the fit is rank-deficient:
    # the ridge still returns *a* number, but neither the recalls nor the
    # centroid distances mean anything.  Refuse rather than let an
    # under-determined UAR be read as "the presets are indistinguishable" --
    # that is the exact misreading this gate exists to prevent.
    degrees_of_freedom = len(records) - len(cells)
    if degrees_of_freedom < len(feature_names):
        verdict = failure(
            "separability_underpowered",
            f"pooled covariance has {degrees_of_freedom} degrees of freedom for "
            f"{len(feature_names)} features; needs at least "
            f"{len(feature_names) + len(cells)} takes across {len(cells)} cells",
        )
        verdict["metrics"] = {
            "cellCount": len(cells),
            "takeCount": len(records),
            "seedCount": len(set(seeds)),
            "featureCount": len(feature_names),
            "covarianceDegreesOfFreedom": degrees_of_freedom,
            "minimumTakesForFit": len(feature_names) + len(cells),
        }
        if thin:
            verdict["metrics"]["cellsBelowMinimumSeeds"] = thin
        return verdict

    import numpy as np

    matrix = _matrix(records, feature_names)

    # Leave-one-seed-out: a take never shares a fold with another take from its
    # own seed, so seed-specific sampling luck cannot inflate the score.
    predictions: list[str | None] = [None] * len(records)
    for held_out in sorted(set(seeds)):
        test_index = [index for index, seed in enumerate(seeds) if seed == held_out]
        train_index = [index for index, seed in enumerate(seeds) if seed != held_out]
        if not train_index:
            continue
        train = matrix[train_index]
        mean = train.mean(axis=0)
        deviation = np.maximum(train.std(axis=0), 1e-9)
        centroids, precision = _fit_discriminant(
            (train - mean) / deviation,
            [labels[index] for index in train_index],
            cells,
            ridge,
        )
        assigned = _predict((matrix[test_index] - mean) / deviation, centroids, precision, cells)
        for position, index in enumerate(test_index):
            if position < len(assigned):
                predictions[index] = assigned[position]

    scored = [index for index, prediction in enumerate(predictions) if prediction is not None]
    if not scored:
        return failure("cohort_too_small", "no take could be held out and scored")

    confusion = {cell: {other: 0 for other in cells} for cell in cells}
    for index in scored:
        confusion[labels[index]][predictions[index]] += 1

    per_cell = {}
    recalls = []
    f1_scores = []
    for cell in cells:
        support = sum(confusion[cell].values())
        correct = confusion[cell][cell]
        recall = correct / support if support else 0.0
        predicted_as = sum(confusion[other][cell] for other in cells)
        precision_value = correct / predicted_as if predicted_as else 0.0
        f1 = (
            2.0 * precision_value * recall / (precision_value + recall)
            if (precision_value + recall) > 0 else 0.0
        )
        confusions = sorted(
            ((other, count) for other, count in confusion[cell].items() if other != cell and count),
            key=lambda item: (-item[1], item[0]),
        )
        per_cell[cell] = {
            "support": support,
            "recall": round(recall, 3),
            "f1": round(f1, 3),
            "topConfusion": confusions[0][0] if confusions else None,
            "topConfusionCount": confusions[0][1] if confusions else 0,
        }
        if support:
            recalls.append(recall)
            f1_scores.append(f1)

    # Centroid geometry over the whole set, for pair margins and the intensity
    # collapse check.  Standardized once here; the CV above is what guards
    # against optimism, this part is descriptive.
    mean = matrix.mean(axis=0)
    deviation = np.maximum(matrix.std(axis=0), 1e-9)
    standardized = (matrix - mean) / deviation
    centroids, precision = _fit_discriminant(standardized, labels, cells, ridge)
    pairs = {}
    for first_index, first in enumerate(cells):
        for second in cells[first_index + 1:]:
            if first in centroids and second in centroids:
                pairs[f"{first}|{second}"] = round(
                    _mahalanobis(centroids[first] - centroids[second], precision), 3
                )

    for cell in cells:
        neighbours = [
            (key.split("|")[1] if key.split("|")[0] == cell else key.split("|")[0], value)
            for key, value in pairs.items() if cell in key.split("|")
        ]
        if neighbours:
            nearest, distance = min(neighbours, key=lambda item: (item[1], item[0]))
            per_cell[cell]["nearestCell"] = nearest
            per_cell[cell]["nearestDistance"] = distance

    flags = []
    for cell in sorted(per_cell):
        entry = per_cell[cell]
        if entry["support"] and entry["recall"] < minimum_recall:
            flags.append(f"separability_low_recall_{cell}")
        if entry.get("nearestDistance") is not None and entry["nearestDistance"] < minimum_margin:
            flags.append(f"separability_confusion_{cell}_vs_{entry['nearestCell']}")

    # Intensity collapse: does turning intensity up push cells together instead
    # of apart?  Measured only when the label mode keeps intensity distinct.
    intensity_metrics = {}
    if label_mode != "preset":
        def mean_pair_distance(suffix):
            values = [
                value for key, value in pairs.items()
                if all(part.endswith(f".{suffix}") for part in key.split("|"))
            ]
            return sum(values) / len(values) if values else None

        normal_spread = mean_pair_distance("normal")
        strong_spread = mean_pair_distance("strong")
        if normal_spread and strong_spread is not None:
            intensity_metrics = {
                "normalMeanPairDistance": round(normal_spread, 3),
                "strongMeanPairDistance": round(strong_spread, 3),
                "strongToNormalRatio": round(strong_spread / normal_spread, 3),
            }
            if strong_spread < normal_spread * collapse_ratio:
                flags.append("separability_intensity_collapse")

    metrics = {
        "uar": round(sum(recalls) / len(recalls), 3) if recalls else 0.0,
        "macroF1": round(sum(f1_scores) / len(f1_scores), 3) if f1_scores else 0.0,
        "cellCount": len(cells),
        "takeCount": len(scored),
        "seedCount": len(set(seeds)),
        "featureCount": len(feature_names),
        "covarianceDegreesOfFreedom": degrees_of_freedom,
        "features": feature_names,
        "pairDistances": pairs,
    }
    metrics.update(intensity_metrics)
    if thin:
        # Reported, never silently dropped: a thin cell's recall is noise.
        metrics["cellsBelowMinimumSeeds"] = thin

    return {
        "algorithmVersion": SEPARABILITY_ALGORITHM_VERSION,
        "passed": not flags,
        "flags": flags,
        "reason": "; ".join(flags) if flags else "delivery cells remain separable",
        "labelMode": label_mode,
        "cells": per_cell,
        "confusion": confusion,
        "metrics": metrics,
    }


def records_from_sidecar(rows):
    """Build separability records from ``bench-prosody.json`` rows."""
    records = []
    for row in rows or []:
        gate = row.get("deliveryGate") or {}
        delivery = row.get("delivery") or gate.get("deliveryID")
        if not delivery:
            continue
        preset, separator, intensity = str(delivery).partition(".")
        features = gate.get("metrics") or {}
        if not features:
            continue
        records.append({
            "preset": gate.get("preset") or preset,
            "intensity": gate.get("intensity") or (intensity if separator else "normal"),
            "seed": row.get("generationID") or row.get("deliveryWav") or delivery,
            "features": features,
        })
    return records


def main():
    parser = argparse.ArgumentParser(description="Cross-preset delivery separability")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--sidecar", help="bench-prosody.json produced by the delivery bench")
    source.add_argument("--records", help="JSON array of {preset,intensity,seed,features}")
    parser.add_argument("--profile", help="calibrated prosody profile JSON")
    parser.add_argument(
        "--label-mode", choices=("cell", "preset"), default="cell",
        help="'cell' keeps intensity distinct (default); 'preset' pools intensities",
    )
    parser.add_argument("--json", action="store_true", help="emit the verdict as JSON")
    arguments = parser.parse_args()

    profile = load_profile(arguments.profile) if arguments.profile else builtin_profile()
    with open(arguments.sidecar or arguments.records, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    records = records_from_sidecar(payload) if arguments.sidecar else payload
    verdict = evaluate_separability(records, profile, label_mode=arguments.label_mode)

    if arguments.json:
        print(json.dumps(verdict, indent=2, sort_keys=True))
        return 0 if verdict["passed"] else 1

    metrics = verdict["metrics"]
    print(f"separability: {'PASS' if verdict['passed'] else 'WARN'} — {verdict['reason']}")
    if metrics:
        print(
            f"  UAR {metrics.get('uar', 0.0)}  macro-F1 {metrics.get('macroF1', 0.0)}  "
            f"{metrics.get('cellCount', 0)} cells, {metrics.get('takeCount', 0)} takes, "
            f"{metrics.get('featureCount', 0)} features"
        )
        if "strongToNormalRatio" in metrics:
            print(
                f"  intensity spread — normal {metrics['normalMeanPairDistance']}, "
                f"strong {metrics['strongMeanPairDistance']} "
                f"(ratio {metrics['strongToNormalRatio']})"
            )
    for cell in sorted(verdict["cells"]):
        entry = verdict["cells"][cell]
        nearest = entry.get("nearestCell")
        print(
            f"  {cell:24} recall {entry['recall']:.2f}  n={entry['support']:<3}"
            + (f"  nearest {nearest} @ {entry.get('nearestDistance')}" if nearest else "")
            + (f"  confused with {entry['topConfusion']}×{entry['topConfusionCount']}"
               if entry.get("topConfusion") else "")
        )
    return 0 if verdict["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
