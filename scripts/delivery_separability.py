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

Algorithm v2 (2026-08-04 delivery-control audit, hardening items 3-5):

* the chance floor (1/cells) is computed and reported, never hand-stated;
* ``--null-iters N`` adds a label-permutation null band (mean, p95, and a
  permutation p-value for the observed UAR) using the exact same folds and
  discriminant — the audit found the original "1.11x chance" cluster reading
  was an ordinary null draw (p = 0.28) that a computed null would have caught;
* per-cell recalls carry Wilson 95% bounds, and "below chance" may only be
  claimed when the *upper* bound sits under the floor (the retired
  excited/dramatic "below chance" recalls had intervals containing it);
* fold grouping prefers the sidecar row's real ``seed`` (present since the
  bench started echoing engine provenance) and loudly reports when unique
  per-take identifiers degenerate the grouping into leave-one-take-out;
* every verdict carries an exploratory/confirmatory designation, defaulting
  to exploratory — decision-bearing claims need a preregistered
  fresh-seed confirmation run.

Usage:
  scripts/delivery_separability.py --sidecar bench-prosody.json [--json]
  scripts/delivery_separability.py --records records.json [--label-mode preset]
  scripts/delivery_separability.py --sidecar bench-prosody.json --null-iters 200
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from prosody_profile import builtin_profile, load_profile, separability_bound

SEPARABILITY_ALGORITHM_VERSION = 2

PERMUTATION_RNG_SEED = 20260804

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
    # The profile's own intensity scaling constant, echoed into the gate
    # metrics. It is 1.0 for normal and 1.15 for strong regardless of what the
    # audio does, so leaving it in lets the classifier read the tier straight
    # off the label and inflates every by-cell score.
    "intensity_factor",
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
    seen_values = {}
    for record in records:
        usable = set()
        for name, value in (record.get("features") or {}).items():
            if name in _EXCLUDED_FEATURES:
                continue
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                continue
            if not math.isfinite(float(value)):
                continue
            usable.add(name)
            seen_values.setdefault(name, set()).add(round(float(value), 12))
        shared = usable if shared is None else (shared & usable)
    # A feature that never varies carries no information and, worse, any
    # constant that happens to track the label would be read as separation.
    constant = {name for name, values in seen_values.items() if len(values) < 2}
    return sorted((shared or set()) - constant)


def _drop_aliased_cells(records, label_mode):
    """Collapse cells that name the same request.

    `neutral` forces its intensity to nil, so `neutral.normal` and
    `neutral.strong` carry identical instruction text and produce byte-identical
    audio at a fixed seed. Scoring both guarantees mutual confusion and drags
    the aggregate down for a reason that has nothing to do with delivery.

    A cell is an alias of another only when they agree exactly on every seed
    they share, over at least two shared seeds -- one coincidental match between
    genuinely different cells is not evidence they are the same request.
    """
    signatures = {}
    for record in records:
        cell = _cell_label(record, label_mode)
        fingerprint = tuple(sorted(
            (name, round(float(value), 9))
            for name, value in record["features"].items()
            # Excluded features must not enter the fingerprint: intensity_factor
            # differs between tiers by construction, so leaving it in would hide
            # exactly the aliasing this detects.
            if name not in _EXCLUDED_FEATURES
            and isinstance(value, (int, float)) and not isinstance(value, bool)
        ))
        signatures.setdefault(cell, {})[str(record.get("seed", ""))] = fingerprint

    aliased = {}
    cells = sorted(signatures)
    for index, cell in enumerate(cells):
        if cell in aliased:
            continue
        for other in cells[index + 1:]:
            if other in aliased:
                continue
            shared = set(signatures[cell]) & set(signatures[other])
            if len(shared) >= 2 and all(
                signatures[cell][seed] == signatures[other][seed] for seed in shared
            ):
                aliased[other] = cell
    if not aliased:
        return records, {}
    kept = [
        record for record in records
        if _cell_label(record, label_mode) not in aliased
    ]
    return kept, aliased


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


def _cross_validated_predictions(matrix, labels, seeds, cells, ridge):
    """Leave-one-seed-out predictions with fold-local standardisation.

    Extracted so the label-permutation null runs the *identical* procedure —
    same folds, same z-scoring, same discriminant — with only the labels
    shuffled.
    """
    import numpy as np

    predictions = [None] * len(labels)
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
    return predictions


def _uar_of(predictions, labels, cells):
    """Unweighted average recall over the cells that received predictions."""
    counts = {cell: [0, 0] for cell in cells}
    for index, prediction in enumerate(predictions):
        if prediction is None:
            continue
        cell = labels[index]
        counts[cell][1] += 1
        if prediction == cell:
            counts[cell][0] += 1
    recalls = [correct / total for correct, total in counts.values() if total]
    return sum(recalls) / len(recalls) if recalls else 0.0


def _wilson_bounds(successes, trials, z=1.959963984540054):
    """Wilson score interval for a binomial proportion; (low, high)."""
    if trials <= 0:
        return None
    proportion = successes / trials
    denominator = 1.0 + z * z / trials
    centre = (proportion + z * z / (2 * trials)) / denominator
    spread = z * math.sqrt(
        proportion * (1.0 - proportion) / trials + z * z / (4 * trials * trials)
    ) / denominator
    return (max(0.0, centre - spread), min(1.0, centre + spread))


def evaluate_separability(
    records, profile=None, label_mode="cell", null_iterations=0, designation="exploratory"
):
    """Cross-validated separability verdict over paired delivery feature vectors.

    ``records`` is a sequence of ``{preset, intensity, seed, features}`` dicts.
    Returns a warn-first verdict mirroring the other delivery gates.
    ``null_iterations`` > 0 additionally runs a label-permutation null with the
    identical folds and discriminant, reporting the null band and a permutation
    p-value for the observed UAR. ``designation`` labels the run exploratory
    (default) or confirmatory; decision-bearing claims require the latter on
    fresh seeds.
    """
    if designation not in ("exploratory", "confirmatory"):
        raise ValueError("designation must be 'exploratory' or 'confirmatory'")
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
            "designation": designation,
            "cells": {},
            "metrics": {},
        }

    records = [record for record in (records or []) if record.get("features")]
    records, aliased_cells = _drop_aliased_cells(records, label_mode)

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

    # Fold-grouping honesty: when every take carries a unique "seed" (the
    # historic fallback used per-take generation IDs), leave-one-seed-out
    # silently degenerates into leave-one-take-out and the docstring's
    # no-leak-across-folds guarantee is void. Report it loudly instead of
    # letting the verdict claim a grouping that never happened.
    degenerate_folds = (
        len(set(seeds)) == len(records) and len(records) >= 2 * len(cells)
    )

    # Leave-one-seed-out: a take never shares a fold with another take from its
    # own seed, so seed-specific sampling luck cannot inflate the score.
    predictions = _cross_validated_predictions(matrix, labels, seeds, cells, ridge)

    scored = [index for index, prediction in enumerate(predictions) if prediction is not None]
    if not scored:
        return failure("cohort_too_small", "no take could be held out and scored")

    confusion = {cell: {other: 0 for other in cells} for cell in cells}
    for index in scored:
        confusion[labels[index]][predictions[index]] += 1

    chance_floor = 1.0 / len(cells)

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
        # Interval-honest chance comparison: a cell is only "below chance"
        # when its whole Wilson interval sits under the computed floor, and
        # only "above chance" when the interval clears it. At n=18 a recall
        # of 1/18 has interval [0.01, 0.26] -- compatible with the floor, not
        # below it, which is the misreading the audit retired.
        bounds = _wilson_bounds(correct, support)
        if bounds is not None:
            low, high = bounds
            per_cell[cell]["recallWilsonLow"] = round(low, 3)
            per_cell[cell]["recallWilsonHigh"] = round(high, 3)
            per_cell[cell]["aboveChance"] = low > chance_floor
            per_cell[cell]["belowChance"] = high < chance_floor
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
    if degenerate_folds:
        flags.append("separability_degenerate_folds")
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

    # A cell-mode miss that lands on the same preset's other tier is a wrong
    # *intensity*, not a wrong emotion -- a listener would still name the
    # emotion correctly. Separating the two keeps the headline number about
    # what the product promises, with the tier question answered by the
    # intensity spread below.
    cross_preset_errors = 0
    tier_errors = 0
    for index in scored:
        if predictions[index] == labels[index]:
            continue
        if labels[index].split(".")[0] == predictions[index].split(".")[0]:
            tier_errors += 1
        else:
            cross_preset_errors += 1
    total_errors = cross_preset_errors + tier_errors

    observed_uar = sum(recalls) / len(recalls) if recalls else 0.0

    # Label-permutation null: the same folds, standardisation, and
    # discriminant, with only the labels shuffled. This is the band the
    # observed UAR must clear before "x times chance" means anything -- the
    # audit's re-analysis showed the 4-cell null has SD ~0.06, so a "1.11x
    # chance" reading was an ordinary draw (permutation p = 0.28).
    permutation = None
    if null_iterations:
        rng = np.random.default_rng(PERMUTATION_RNG_SEED)
        null_uars = []
        for _ in range(int(null_iterations)):
            permuted = list(labels)
            rng.shuffle(permuted)
            null_predictions = _cross_validated_predictions(
                matrix, permuted, seeds, cells, ridge
            )
            null_uars.append(_uar_of(null_predictions, permuted, cells))
        null_uars.sort()
        at_or_above = sum(1 for value in null_uars if value >= observed_uar - 1e-12)
        null_mean = sum(null_uars) / len(null_uars)
        null_sd = math.sqrt(
            sum((value - null_mean) ** 2 for value in null_uars) / len(null_uars)
        )
        permutation = {
            "iterations": len(null_uars),
            "rngSeed": PERMUTATION_RNG_SEED,
            "nullMeanUAR": round(null_mean, 4),
            "nullSdUAR": round(null_sd, 4),
            "nullP95UAR": round(null_uars[int(0.95 * (len(null_uars) - 1))], 4),
            "pValueUAR": round((1 + at_or_above) / (len(null_uars) + 1), 4),
        }

    metrics = {
        "uar": round(observed_uar, 3),
        "macroF1": round(sum(f1_scores) / len(f1_scores), 3) if f1_scores else 0.0,
        "chanceFloor": round(chance_floor, 4),
        "foldGrouping": "leave-one-take-out" if degenerate_folds else "seed-grouped",
        "crossPresetErrorRate": (
            round(cross_preset_errors / len(scored), 3) if scored else 0.0
        ),
        "tierOnlyErrorRate": round(tier_errors / len(scored), 3) if scored else 0.0,
        "errorsThatAreTierOnly": (
            round(tier_errors / total_errors, 3) if total_errors else 0.0
        ),
        "cellCount": len(cells),
        "takeCount": len(scored),
        "seedCount": len(set(seeds)),
        "featureCount": len(feature_names),
        "covarianceDegreesOfFreedom": degrees_of_freedom,
        "features": feature_names,
        "pairDistances": pairs,
    }
    metrics.update(intensity_metrics)
    if permutation:
        metrics["permutation"] = permutation
    if aliased_cells:
        # Reported, never silent: an alias means two catalog cells issue the
        # same request, which is a finding about the preset catalog.
        metrics["aliasedCells"] = {
            alias: canonical for alias, canonical in sorted(aliased_cells.items())
        }
    if thin:
        # Reported, never silently dropped: a thin cell's recall is noise.
        metrics["cellsBelowMinimumSeeds"] = thin

    return {
        "algorithmVersion": SEPARABILITY_ALGORITHM_VERSION,
        "passed": not flags,
        "flags": flags,
        "reason": "; ".join(flags) if flags else "delivery cells remain separable",
        "labelMode": label_mode,
        "designation": designation,
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
        # Prefer the row's real seed (echoed from engine provenance since
        # 2026-08-04). The historic per-take fallbacks degenerate the fold
        # grouping into leave-one-take-out, which evaluate_separability now
        # reports rather than silently claiming seed-grouped CV.
        seed = row.get("seed")
        if seed in (None, ""):
            seed = row.get("generationID") or row.get("deliveryWav") or delivery
        records.append({
            "preset": gate.get("preset") or preset,
            "intensity": gate.get("intensity") or (intensity if separator else "normal"),
            "seed": seed,
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
    parser.add_argument(
        "--null-iters", type=int, default=0, metavar="N",
        help="label-permutation null iterations (0 = off; 200 gives a stable "
             "band and p-value at ~seconds of cost)",
    )
    parser.add_argument(
        "--designation", choices=("exploratory", "confirmatory"), default="exploratory",
        help="evidentiary status of this run; decision-bearing claims need a "
             "preregistered confirmatory run on fresh seeds",
    )
    parser.add_argument("--json", action="store_true", help="emit the verdict as JSON")
    arguments = parser.parse_args()

    profile = load_profile(arguments.profile) if arguments.profile else builtin_profile()
    with open(arguments.sidecar or arguments.records, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    records = records_from_sidecar(payload) if arguments.sidecar else payload
    verdict = evaluate_separability(
        records,
        profile,
        label_mode=arguments.label_mode,
        null_iterations=arguments.null_iters,
        designation=arguments.designation,
    )

    if arguments.json:
        print(json.dumps(verdict, indent=2, sort_keys=True))
        return 0 if verdict["passed"] else 1

    metrics = verdict["metrics"]
    print(f"separability: {'PASS' if verdict['passed'] else 'WARN'} — {verdict['reason']}")
    print(f"  designation: {verdict['designation']}")
    if metrics:
        print(
            f"  UAR {metrics.get('uar', 0.0)}  macro-F1 {metrics.get('macroF1', 0.0)}  "
            f"chance {metrics.get('chanceFloor', 0.0)}  "
            f"{metrics.get('cellCount', 0)} cells, {metrics.get('takeCount', 0)} takes, "
            f"{metrics.get('featureCount', 0)} features"
        )
        if metrics.get("foldGrouping") == "leave-one-take-out":
            print(
                "  WARNING: fold grouping degenerated to leave-one-take-out — "
                "rows carry unique per-take seeds, so the seed-grouped CV "
                "guarantee does not hold for this data"
            )
        permutation = metrics.get("permutation")
        if permutation:
            print(
                f"  permutation null ({permutation['iterations']} iters): "
                f"mean {permutation['nullMeanUAR']}  p95 {permutation['nullP95UAR']}  "
                f"p(UAR ≥ observed) = {permutation['pValueUAR']}"
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
