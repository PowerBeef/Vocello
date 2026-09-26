"""Exact binomial bounds and operating-point rates (audit section 5.4).

New claims use the exact one-sided Clopper-Pearson (CP) bound at 95%: the upper
bound on an error rate (false alarms among negatives, misses among positives)
and the lower bound on a detection rate. The legacy two-sided Wilson bound is
kept for reading legacy records (0 of 60 gives 0.0602).

The CP upper bound with k errors of n solves P(X <= k; n, p) = alpha, the lower
bound solves P(X >= k; n, p) = alpha. k = 0 and k = n have closed forms; the
rest is bisection over the exact binomial tail, summed in log space.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable, Iterable, Sequence

DEFAULT_CONFIDENCE = 0.95
# Two-sided 95% normal quantile, as `prosody_holdout_validation.py` uses it.
WILSON_Z = 1.959963984540054
_BISECTION_STEPS = 200


def _check(k: int, n: int, confidence: float) -> None:
    if isinstance(k, bool) or isinstance(n, bool) or not isinstance(k, int) or not isinstance(n, int):
        raise TypeError("counts must be integers")
    if n <= 0 or not 0 <= k <= n:
        raise ValueError(f"need 0 <= k <= n and n > 0, got k={k} n={n}")
    if not 0.0 < confidence < 1.0:
        raise ValueError("confidence must lie in (0, 1)")


def binomial_cdf(k: int, n: int, p: float) -> float:
    """P(X <= k) for X ~ Binomial(n, p)."""
    if k < 0:
        return 0.0
    if k >= n or p <= 0.0:
        return 1.0
    if p >= 1.0:
        return 0.0
    log_p, log_q = math.log(p), math.log1p(-p)
    base = math.lgamma(n + 1)
    return min(1.0, math.fsum(
        math.exp(base - math.lgamma(i + 1) - math.lgamma(n - i + 1) + i * log_p + (n - i) * log_q)
        for i in range(k + 1)
    ))


def _bisect(predicate_high: Callable[[float], bool]) -> float:
    """Smallest p in [0, 1] (to double precision) for which predicate_high(p) holds."""
    low, high = 0.0, 1.0
    for _ in range(_BISECTION_STEPS):
        middle = (low + high) / 2.0
        if middle in (low, high):
            break
        if predicate_high(middle):
            high = middle
        else:
            low = middle
    return high


def cp_upper(k: int, n: int, confidence: float = DEFAULT_CONFIDENCE) -> float:
    """One-sided exact upper bound on a rate with k events in n trials."""
    _check(k, n, confidence)
    alpha = 1.0 - confidence
    if k == n:
        return 1.0
    if k == 0:
        return 1.0 - alpha ** (1.0 / n)
    return _bisect(lambda p: binomial_cdf(k, n, p) <= alpha)


def cp_lower(k: int, n: int, confidence: float = DEFAULT_CONFIDENCE) -> float:
    """One-sided exact lower bound on a rate with k events in n trials."""
    _check(k, n, confidence)
    alpha = 1.0 - confidence
    if k == 0:
        return 0.0
    if k == n:
        return alpha ** (1.0 / n)
    # P(X >= k; p) = 1 - cdf(k - 1; p) rises with p: the bound is where it reaches alpha.
    return _bisect(lambda p: 1.0 - binomial_cdf(k - 1, n, p) >= alpha)


def wilson_upper(k: int, n: int, z: float = WILSON_Z) -> float:
    """Legacy two-sided Wilson upper bound (0 of 60 gives 0.0602)."""
    _check(k, n, 0.95)
    rate = k / n
    z2 = z * z
    centre = rate + z2 / (2 * n)
    spread = z * math.sqrt(rate * (1 - rate) / n + z2 / (4 * n * n))
    return min(1.0, (centre + spread) / (1 + z2 / n))


def minimum_units(target: float, errors: int = 0, confidence: float = DEFAULT_CONFIDENCE,
                  method: str = "clopper-pearson") -> int:
    """Fewest independent units for which `errors` observed errors keep the bound <= target.

    The same table sizes miss rates, since a detection rate >= 1 - target needs
    the miss rate's upper bound <= target.
    """
    if not 0.0 < target < 1.0:
        raise ValueError("target must lie in (0, 1)")
    if isinstance(errors, bool) or not isinstance(errors, int) or errors < 0:
        raise ValueError("errors must be a non-negative integer")
    if method == "clopper-pearson":
        bound = lambda n: cp_upper(errors, n, confidence)  # noqa: E731
    elif method == "wilson":
        if confidence != DEFAULT_CONFIDENCE:
            raise ValueError("the legacy Wilson bound is defined at 95% only")
        bound = lambda n: wilson_upper(errors, n)  # noqa: E731
    else:
        raise ValueError(f"unknown method {method!r}")
    low = errors + 1
    if bound(low) <= target:
        return low
    high = low
    while bound(high) > target:
        low, high = high, high * 2
    # bound(low) > target >= bound(high); the bound falls as n grows.
    while high - low > 1:
        middle = (low + high) // 2
        if bound(middle) <= target:
            high = middle
        else:
            low = middle
    return high


def bonferroni_confidence(confidence: float, comparisons: int) -> float:
    """Per-comparison confidence for a simultaneous claim over `comparisons` strata."""
    if isinstance(comparisons, bool) or not isinstance(comparisons, int) or comparisons < 1:
        raise ValueError("comparisons must be a positive integer")
    return 1.0 - (1.0 - confidence) / comparisons


def sample_size_table(targets: Sequence[float] = (0.20, 0.10, 0.05, 0.02, 0.01),
                      errors: Sequence[int] = (0, 1, 2, 5),
                      confidence: float = DEFAULT_CONFIDENCE) -> list[dict]:
    """The audit's section 5.4 table, recomputed."""
    return [{
        "target": target,
        "clopperPearson": {str(k): minimum_units(target, k, confidence) for k in errors},
        "wilsonTwoSidedZeroErrors": minimum_units(target, 0, method="wilson"),
    } for target in targets]


@dataclass(frozen=True)
class Rate:
    """k events in n independent units, with one-sided CP bounds."""
    events: int
    units: int
    confidence: float = DEFAULT_CONFIDENCE

    def __post_init__(self) -> None:
        if self.units:
            _check(self.events, self.units, self.confidence)
        elif self.events:
            raise ValueError("events without units")

    @property
    def rate(self) -> float | None:
        return self.events / self.units if self.units else None

    @property
    def upper(self) -> float | None:
        return cp_upper(self.events, self.units, self.confidence) if self.units else None

    @property
    def lower(self) -> float | None:
        return cp_lower(self.events, self.units, self.confidence) if self.units else None

    def as_dict(self) -> dict:
        return {"events": self.events, "units": self.units, "rate": _round(self.rate),
                "upper": _round(self.upper), "lower": _round(self.lower),
                "confidence": self.confidence, "method": "clopper-pearson-one-sided"}


def _round(value: float | None) -> float | None:
    return None if value is None else round(value, 6)


def rate_of(flags: Iterable[bool], confidence: float = DEFAULT_CONFIDENCE) -> Rate:
    values = [bool(flag) for flag in flags]
    return Rate(sum(values), len(values), confidence)


def alarms(scores: Iterable[float | None], threshold: float, direction: str) -> list[bool | None]:
    """Per-unit alarm at a threshold: `above` alarms when score > threshold, `below` when <.

    A None score is an abstention and stays None.
    """
    if direction not in ("above", "below"):
        raise ValueError("direction must be 'above' or 'below'")
    result: list[bool | None] = []
    for score in scores:
        if score is None:
            result.append(None)
        elif not math.isfinite(score):
            raise ValueError("scores must be finite or None")
        else:
            result.append(score > threshold if direction == "above" else score < threshold)
    return result


def operating_point(negative_scores: Sequence[float | None], positive_scores: Sequence[float | None],
                    threshold: float, direction: str = "above",
                    confidence: float = DEFAULT_CONFIDENCE) -> dict:
    """FAR on negatives and FRR/TPR on positives at one declared threshold.

    Abstentions (None scores) are counted apart and excluded from both rates;
    the clean abstention rate is reported, since the policy bounds it too.
    """
    negative = alarms(negative_scores, threshold, direction)
    positive = alarms(positive_scores, threshold, direction)
    judged_negative = [flag for flag in negative if flag is not None]
    judged_positive = [flag for flag in positive if flag is not None]
    far = rate_of(judged_negative, confidence)
    frr = Rate(sum(1 for flag in judged_positive if not flag), len(judged_positive), confidence)
    tpr = Rate(sum(1 for flag in judged_positive if flag), len(judged_positive), confidence)
    return {
        "threshold": threshold,
        "direction": direction,
        "far": far.as_dict(),
        "frr": frr.as_dict(),
        "tpr": tpr.as_dict(),
        "cleanAbstention": Rate(len(negative) - len(judged_negative), len(negative), confidence).as_dict()
        if negative else Rate(0, 0).as_dict(),
    }


def meets(rate: Rate, *, maximum: float | None = None, minimum: float | None = None) -> bool:
    """Whether the CP bound clears an operating point: upper <= maximum, lower >= minimum."""
    if rate.units == 0:
        return False
    if maximum is not None and rate.upper > maximum:
        return False
    if minimum is not None and rate.lower < minimum:
        return False
    return True
