"""Correlated-failure audit between two judges (AQ-F35, audit sections 5.7 and 11).

Consensus treats two families as independent evidence. Shared training data
(Parakeet's Whisper pseudo-labels, VoxCeleb for every speaker model) can make
them fail together, so a consensus rule does not gate until this audit is
recorded. Each unit is one labeled item that both judges saw; "failed" means the
judge got that item wrong (a miss on a positive or a false alarm on a
negative), never that it raised an alarm.

The audit reports the 2 x 2 table, the phi coefficient (with a family-cluster
bootstrap), each judge's failure rate, the conditional failure rates and the
joint rate independence would predict, all descriptive and per unit; and the
joint failure rate with its exact bound, a claim, so it counts source families
(a family is a joint failure if both judges failed on one of its units). It
decides nothing: the policy names what a recorded audit must show before two
judges vote jointly.
"""

from __future__ import annotations

import math
from typing import Hashable, Sequence

import numpy as np

from .pcm import SeededStream
from .resampling import DEFAULT_RESAMPLES, DEFAULT_SEED
from .stats import DEFAULT_CONFIDENCE, family_rate


def _ratio(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 6) if denominator else None


def phi_coefficient(both: int, only_a: int, only_b: int, neither: int) -> float | None:
    """Phi of a 2 x 2 failure table; None when a margin is empty (undefined)."""
    a_fail, a_ok = both + only_a, only_b + neither
    b_fail, b_ok = both + only_b, only_a + neither
    denominator = a_fail * a_ok * b_fail * b_ok
    if denominator == 0:
        return None
    return (both * neither - only_a * only_b) / math.sqrt(denominator)


def failure_correlation(a_failed: Sequence[bool], b_failed: Sequence[bool], *,
                        families: Sequence[Hashable],
                        judges: tuple[str, str] = ("a", "b"),
                        confidence: float = DEFAULT_CONFIDENCE,
                        resamples: int = DEFAULT_RESAMPLES, seed: int = DEFAULT_SEED) -> dict:
    """Audit two judges' failures over the same units, one source family per unit.

    Phi gets a family-cluster bootstrap interval, since clips of one family
    fail together for reasons that have nothing to do with the judges, and the
    joint failure bound counts families.
    """
    if len(a_failed) != len(b_failed):
        raise ValueError("both judges must be scored on the same units")
    if len(families) != len(a_failed):
        raise ValueError("one family per unit")
    both = only_a = only_b = neither = 0
    for a, b in zip(a_failed, b_failed):
        if a and b:
            both += 1
        elif a:
            only_a += 1
        elif b:
            only_b += 1
        else:
            neither += 1
    total = both + only_a + only_b + neither
    a_fail, b_fail = both + only_a, both + only_b
    phi = phi_coefficient(both, only_a, only_b, neither)
    expected_joint = (a_fail / total) * (b_fail / total) if total else None
    joint = family_rate(((family, bool(a) and bool(b)) for family, a, b in zip(families, a_failed, b_failed)),
                        confidence)
    report = {
        "judges": list(judges),
        "units": total,
        "families": joint.units,
        "table": {"bothFailed": both, "onlyFirstFailed": only_a, "onlySecondFailed": only_b,
                  "neitherFailed": neither},
        "phi": None if phi is None else round(phi, 6),
        "failureRate": {judges[0]: _ratio(a_fail, total), judges[1]: _ratio(b_fail, total)},
        "conditionalFailureRate": {
            f"{judges[1]}|{judges[0]}Failed": _ratio(both, a_fail),
            f"{judges[1]}|{judges[0]}Passed": _ratio(only_b, only_b + neither),
            f"{judges[0]}|{judges[1]}Failed": _ratio(both, b_fail),
            f"{judges[0]}|{judges[1]}Passed": _ratio(only_a, only_a + neither),
        },
        "jointFailure": {**joint.as_dict(), "unit": "source-family"},
        "jointFailurePerUnit": {
            "rate": _ratio(both, total),
            "ifIndependent": None if expected_joint is None else round(expected_joint, 6),
            "lift": None if not expected_joint else round((both / total) / expected_joint, 6),
        },
    }
    if total:
        report["phiClusterBootstrap"] = _phi_bootstrap(a_failed, b_failed, families, confidence,
                                                       resamples, seed)
    return report


def _phi_bootstrap(a_failed: Sequence[bool], b_failed: Sequence[bool], families: Sequence[Hashable],
                   confidence: float, resamples: int, seed: int) -> dict:
    cells = {}
    for family, a, b in zip(families, a_failed, b_failed):
        entry = cells.setdefault(family, [0, 0, 0, 0])
        entry[0 if a and b else 1 if a else 2 if b else 3] += 1
    table = np.array(list(cells.values()), dtype=np.float64)
    count = table.shape[0]
    draws = SeededStream(seed, "phi-bootstrap").integers(count, resamples * count).reshape(resamples, count)
    sums = table[draws].sum(axis=1)
    both, only_a, only_b, neither = sums[:, 0], sums[:, 1], sums[:, 2], sums[:, 3]
    denominator = (both + only_a) * (only_b + neither) * (both + only_b) * (only_a + neither)
    defined = denominator > 0
    phis = (both * neither - only_a * only_b)[defined] / np.sqrt(denominator[defined])
    if phis.size == 0:
        return {"families": count, "defined": 0, "lower": None, "upper": None, "resamples": resamples,
                "seed": seed}
    ordered = np.sort(phis)
    tail = (1.0 - confidence) / 2.0
    lower = ordered[min(ordered.size - 1, int(math.floor(tail * ordered.size)))]
    upper = ordered[max(0, min(ordered.size - 1, int(math.ceil((1.0 - tail) * ordered.size)) - 1))]
    return {"families": count, "defined": int(phis.size), "lower": round(float(lower), 6),
            "upper": round(float(upper), 6), "resamples": resamples, "seed": seed}
