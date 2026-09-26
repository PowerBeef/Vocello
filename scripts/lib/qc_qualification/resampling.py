"""Resampling by source family (audit section 5.4, "Independence and multiplicity").

The unit of independence is the source family, not the clip: crops, injections
and resyntheses of one utterance are one family, and one script x voice x seed
is one Vocello family, deduplicated by PCM digest. Intervals over pooled clips
use a cluster bootstrap that draws whole families with replacement (B = 2,000,
fixed seed), so correlated clips of one family never count as independent
evidence.
"""

from __future__ import annotations

from collections import OrderedDict
from typing import Hashable, Iterable, Sequence

import numpy as np

from .pcm import SeededStream

DEFAULT_RESAMPLES = 2_000
DEFAULT_SEED = 20_260_925


def merge_families_by_digest(items: Iterable[tuple[str, Hashable]]) -> dict[Hashable, Hashable]:
    """Map each declared family to its independence unit.

    `items` are (PCM digest, declared family) pairs. Families that share any
    digest are one unit (a deduplicated copy is not new evidence); the unit is
    named by its earliest-seen family.
    """
    parent: dict[Hashable, Hashable] = {}
    order: dict[Hashable, int] = {}
    first_family: dict[str, Hashable] = {}

    def find(family: Hashable) -> Hashable:
        while parent[family] != family:
            parent[family] = parent[parent[family]]
            family = parent[family]
        return family

    for digest, family in items:
        if family not in parent:
            parent[family] = family
            order[family] = len(order)
        if digest not in first_family:
            first_family[digest] = family
            continue
        left, right = find(first_family[digest]), find(family)
        if left != right:
            keep, merge = (left, right) if order[left] < order[right] else (right, left)
            parent[merge] = keep
    return {family: find(family) for family in order}


def family_counts(units: Iterable[tuple[Hashable, bool]]) -> "OrderedDict[Hashable, tuple[int, int]]":
    """(events, units) per family, in first-seen order."""
    counts: "OrderedDict[Hashable, list[int]]" = OrderedDict()
    for family, event in units:
        entry = counts.setdefault(family, [0, 0])
        entry[0] += int(bool(event))
        entry[1] += 1
    return OrderedDict((family, (events, total)) for family, (events, total) in counts.items())


def _order_statistic(values: np.ndarray, fraction: float, *, upper: bool) -> float:
    ordered = np.sort(values)
    count = ordered.size
    if upper:
        index = min(count - 1, max(0, int(np.ceil(fraction * count)) - 1))
    else:
        index = min(count - 1, max(0, int(np.floor(fraction * count))))
    return float(ordered[index])


def cluster_bootstrap_rate(units: Sequence[tuple[Hashable, bool]], *, resamples: int = DEFAULT_RESAMPLES,
                           seed: int = DEFAULT_SEED, confidence: float = 0.95,
                           label: str = "rate") -> dict:
    """Pooled event rate with a family-cluster bootstrap interval.

    Returns the pooled rate, a two-sided percentile interval and the one-sided
    upper percentile at `confidence`. Families are drawn with replacement, so a
    family's clips always travel together.
    """
    counts = family_counts(units)
    if not counts:
        return {"families": 0, "units": 0, "events": 0, "rate": None, "lower": None, "upper": None,
                "oneSidedUpper": None, "resamples": resamples, "seed": seed, "method": "cluster-bootstrap"}
    events = np.array([value[0] for value in counts.values()], dtype=np.float64)
    totals = np.array([value[1] for value in counts.values()], dtype=np.float64)
    families = len(counts)
    draws = SeededStream(seed, "cluster-bootstrap", label).integers(families, resamples * families)
    draws = draws.reshape(resamples, families)
    rates = events[draws].sum(axis=1) / totals[draws].sum(axis=1)
    tail = 1.0 - confidence
    return {
        "families": families,
        "units": int(totals.sum()),
        "events": int(events.sum()),
        "rate": round(float(events.sum() / totals.sum()), 6),
        "lower": round(_order_statistic(rates, tail / 2.0, upper=False), 6),
        "upper": round(_order_statistic(rates, 1.0 - tail / 2.0, upper=True), 6),
        "oneSidedUpper": round(_order_statistic(rates, confidence, upper=True), 6),
        "resamples": resamples,
        "seed": seed,
        "method": "cluster-bootstrap",
    }


def family_level_events(units: Sequence[tuple[Hashable, bool]]) -> tuple[int, int]:
    """(families with any event, families): the conservative one-unit-per-family count."""
    counts = family_counts(units)
    return sum(1 for events, _ in counts.values() if events), len(counts)
