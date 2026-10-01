"""Paired-comparison statistics: significance, effect size and intervals.

Moved here from the retired ``delivery_statistics.py`` (QC v2, 2026-10-01) with
the routines its two remaining consumers use, unchanged:

  wilcoxon_signed_rank  paired significance without a normality assumption --
                        prosody deltas are ordinal and heavy-tailed
  cohens_dz             paired effect size, reported alongside every p-value
                        so a significant triviality cannot pass as a finding
  bootstrap_ci          bias-corrected and accelerated (BCa) interval, which
                        needs no distributional assumption
  wilson_interval       win-rate with an interval that behaves at the extremes
                        where the normal approximation fails
  required_pairs        the n a given effect size needs
  paired_report         all of the above for one paired feature

Consumers: ``scripts/delivery_quality_gate.py`` (the delivery bench's per-cell
adherence verdict) and ``scripts/telemetry_overhead.py`` (the telemetry-on
versus telemetry-off parity interval).

NumPy plus the standard library only, so it runs under system ``python3``.
Every routine is deterministic; the bootstrap takes an explicit seed.
"""

from __future__ import annotations

import math

import numpy as np

STATISTICS_ALGORITHM_VERSION = 1

# Exact Wilcoxon enumeration is cheap and assumption-free, but only valid
# without tied absolute differences; beyond this n the normal approximation is
# accurate anyway.
_EXACT_WILCOXON_MAX_N = 20


def _standard_normal_cdf(value):
    return 0.5 * (1.0 + math.erf(value / math.sqrt(2.0)))


def _standard_normal_quantile(probability):
    """Inverse standard-normal CDF (Acklam's rational approximation)."""
    if not 0.0 < probability < 1.0:
        raise ValueError("probability must fall strictly inside (0, 1)")
    a = (-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
         1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00)
    b = (-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
         6.680131188771972e+01, -1.328068155288572e+01)
    c = (-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
         -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00)
    d = (7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00,
         3.754408661907416e+00)
    low, high = 0.02425, 1.0 - 0.02425
    if probability < low:
        q = math.sqrt(-2.0 * math.log(probability))
        return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / \
               ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0)
    if probability > high:
        q = math.sqrt(-2.0 * math.log(1.0 - probability))
        return -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / \
               ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0)
    q = probability - 0.5
    r = q * q
    return (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q / \
           (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1.0)


def _average_ranks(values):
    """Ranks of ``values`` starting at 1, ties sharing their average rank."""
    order = np.argsort(values, kind="stable")
    ranks = np.empty(len(values), dtype=np.float64)
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


def _exact_wilcoxon_p(statistic, count):
    """Two-sided exact p for the signed-rank statistic, no ties assumed."""
    # Number of rank subsets summing to each total, by dynamic programming.
    total = count * (count + 1) // 2
    ways = np.zeros(total + 1, dtype=np.float64)
    ways[0] = 1.0
    for rank in range(1, count + 1):
        ways[rank:] += ways[:-rank] if rank else ways
    distribution = ways / (2.0 ** count)
    lower = float(distribution[: int(statistic) + 1].sum())
    return min(1.0, 2.0 * lower)


def wilcoxon_signed_rank(differences):
    """Two-sided Wilcoxon signed-rank test over paired differences.

    Zero differences are discarded (Wilcoxon's original treatment). Returns
    ``{statistic, pValue, n, method}``; ``pValue`` is None when every pair ties.
    """
    values = np.asarray([float(value) for value in differences], dtype=np.float64)
    nonzero = values[values != 0.0]
    count = int(nonzero.size)
    if count == 0:
        return {"statistic": 0.0, "pValue": None, "n": 0, "method": "undefined"}

    magnitudes = np.abs(nonzero)
    ranks = _average_ranks(magnitudes)
    positive = float(ranks[nonzero > 0].sum())
    negative = float(ranks[nonzero < 0].sum())
    statistic = min(positive, negative)

    has_ties = len(np.unique(magnitudes)) != count
    if not has_ties and count <= _EXACT_WILCOXON_MAX_N:
        return {
            "statistic": statistic,
            "pValue": round(_exact_wilcoxon_p(statistic, count), 6),
            "n": count,
            "method": "exact",
        }

    mean = count * (count + 1) / 4.0
    _, tie_counts = np.unique(magnitudes, return_counts=True)
    tie_correction = float(((tie_counts ** 3) - tie_counts).sum())
    variance = (count * (count + 1) * (2 * count + 1) - 0.5 * tie_correction) / 24.0
    if variance <= 0:
        return {"statistic": statistic, "pValue": None, "n": count, "method": "undefined"}
    # Continuity correction toward the mean.
    z = (statistic - mean + 0.5) / math.sqrt(variance)
    return {
        "statistic": statistic,
        "pValue": round(min(1.0, 2.0 * _standard_normal_cdf(z)), 6),
        "n": count,
        "method": "normal-approximation",
    }


def cohens_dz(differences):
    """Paired effect size: mean difference over its own standard deviation."""
    values = np.asarray([float(value) for value in differences], dtype=np.float64)
    if values.size < 2:
        return None
    deviation = float(values.std(ddof=1))
    if deviation <= 0.0:
        return None
    return float(values.mean() / deviation)


def bootstrap_ci(values, confidence=0.95, resamples=10_000, seed=20260802):
    """Bias-corrected and accelerated bootstrap interval for the mean.

    BCa rather than a percentile interval because paired prosody deltas are
    skewed often enough that the naive interval sits off-centre. The seed is
    explicit so a published interval is reproducible.
    """
    sample = np.asarray([float(value) for value in values], dtype=np.float64)
    count = sample.size
    if count < 2:
        return None
    observed = float(sample.mean())

    generator = np.random.default_rng(seed)
    indices = generator.integers(0, count, size=(resamples, count))
    replicates = sample[indices].mean(axis=1)

    below = float((replicates < observed).mean())
    if below <= 0.0 or below >= 1.0:
        # Degenerate resample distribution: fall back to percentiles.
        alpha = (1.0 - confidence) / 2.0
        return {
            "mean": observed,
            "lower": float(np.quantile(replicates, alpha)),
            "upper": float(np.quantile(replicates, 1.0 - alpha)),
            "method": "percentile",
            "resamples": resamples,
        }
    bias = _standard_normal_quantile(below)

    # Jackknife acceleration.
    total = sample.sum()
    jackknife = (total - sample) / (count - 1)
    centered = jackknife.mean() - jackknife
    denominator = 6.0 * (float((centered ** 2).sum()) ** 1.5)
    acceleration = float((centered ** 3).sum()) / denominator if denominator > 0 else 0.0

    alpha = (1.0 - confidence) / 2.0
    bounds = []
    for tail in (alpha, 1.0 - alpha):
        z = _standard_normal_quantile(tail)
        adjusted = bias + (bias + z) / max(1.0 - acceleration * (bias + z), 1e-12)
        bounds.append(float(np.quantile(replicates, min(max(_standard_normal_cdf(adjusted), 0.0), 1.0))))
    return {
        "mean": observed,
        "lower": bounds[0],
        "upper": bounds[1],
        "method": "BCa",
        "resamples": resamples,
    }


def wilson_interval(successes, trials, confidence=0.95):
    """Wilson score interval for a win-rate.

    The normal approximation collapses near 0 and 1, which is exactly where
    delivery win-rates live (the acceptance bar is 0.85).
    """
    if trials <= 0:
        return None
    z = _standard_normal_quantile(1.0 - (1.0 - confidence) / 2.0)
    proportion = successes / trials
    denominator = 1.0 + z * z / trials
    centre = (proportion + z * z / (2 * trials)) / denominator
    spread = z * math.sqrt(
        proportion * (1.0 - proportion) / trials + z * z / (4 * trials * trials)
    ) / denominator
    return {
        "rate": proportion,
        "lower": max(0.0, centre - spread),
        "upper": min(1.0, centre + spread),
        "n": trials,
    }


def required_pairs(effect_size, power=0.80, alpha=0.05):
    """Paired-sample size for a target effect, so a sweep is sized up front.

    Normal approximation with a small correction for estimating the standard
    deviation. Reported as guidance for planning, not as a hard gate.
    """
    if effect_size is None or effect_size <= 0:
        return None
    z_alpha = _standard_normal_quantile(1.0 - alpha / 2.0)
    z_power = _standard_normal_quantile(power)
    return int(math.ceil(((z_alpha + z_power) / effect_size) ** 2)) + 2


def paired_report(instructed, neutral, label=None, seed=20260802):
    """Full paired summary for one feature: significance, size, interval, win-rate."""
    first = np.asarray([float(value) for value in instructed], dtype=np.float64)
    second = np.asarray([float(value) for value in neutral], dtype=np.float64)
    if first.size != second.size:
        raise ValueError("paired inputs must be the same length")
    differences = first - second
    wins = int((differences > 0).sum())
    effect = cohens_dz(differences)
    return {
        "label": label,
        "algorithmVersion": STATISTICS_ALGORITHM_VERSION,
        "n": int(differences.size),
        "meanDifference": float(differences.mean()) if differences.size else None,
        "cohensDz": round(effect, 4) if effect is not None else None,
        "wilcoxon": wilcoxon_signed_rank(differences),
        "confidenceInterval": bootstrap_ci(differences, seed=seed),
        "winRate": wilson_interval(wins, int(differences.size)),
        "requiredPairsForObservedEffect": required_pairs(abs(effect)) if effect else None,
    }
