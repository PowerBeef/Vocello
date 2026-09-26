"""Pre-registered threshold derivation from clean clips only (audit section 5.5).

1. The plan (rule, grid, alpha, strata, split) is a `PreRegistration` whose
   digest is committed before any confirmation score exists (A5).
2. The split is by family, so calibration and confirmation share no family.
3. A single threshold is the split-conformal quantile of clean calibration
   scores: the ceil((n + 1)(1 - alpha))-th order statistic, which bounds the
   marginal false-alarm rate by alpha. Positives never enter the derivation:
   detection is measured, never optimized.
4. A multi-parameter rule walks a pre-ordered grid with fixed-sequence
   Learn-then-Test and keeps the last setting whose exact binomial test
   rejects "FAR > alpha".
5. Confirmation runs once per plan digest; a second attempt is refused, and a
   failed confirmation is recorded, not retried.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, field
from typing import Callable, Hashable, Mapping, Sequence

from .pcm import canonical_json
from .stats import DEFAULT_CONFIDENCE, Rate, binomial_cdf

RULES = ("split-conformal", "learn-then-test")
DIRECTIONS = ("above", "below")


class PreRegistrationError(ValueError):
    """The plan is incomplete, or a derivation departs from its committed plan."""


@dataclass(frozen=True)
class PreRegistration:
    """The committed plan for one detector's threshold (A5)."""
    detector: str
    rule: str
    alpha: float
    direction: str
    split_salt: str
    calibration_fraction: float = 0.5
    strata: tuple[tuple[str, str], ...] = ()
    grid: tuple[float, ...] = ()
    confidence: float = DEFAULT_CONFIDENCE
    population: str = "N2"

    def __post_init__(self) -> None:
        if not self.detector or "@" not in self.detector:
            raise PreRegistrationError("detector must name an id and version, like 'fastqc.clicks@8'")
        if self.rule not in RULES:
            raise PreRegistrationError(f"rule must be one of {RULES}")
        if not 0.0 < self.alpha < 1.0:
            raise PreRegistrationError("alpha must lie in (0, 1)")
        if self.direction not in DIRECTIONS:
            raise PreRegistrationError(f"direction must be one of {DIRECTIONS}")
        if not self.split_salt:
            raise PreRegistrationError("the family split needs a committed salt")
        if not 0.0 < self.calibration_fraction < 1.0:
            raise PreRegistrationError("calibration_fraction must lie in (0, 1)")
        for name, reason in self.strata:
            if not name or not reason:
                raise PreRegistrationError("every stratum is declared in advance with its reason")
        if self.rule == "learn-then-test" and not self.grid:
            raise PreRegistrationError("Learn-then-Test needs a pre-ordered grid")
        if self.rule == "split-conformal" and self.grid:
            raise PreRegistrationError("a split-conformal plan has no grid")

    def as_dict(self) -> dict:
        return {
            "schema": "vocello.audioqc.preregistration/1",
            "detector": self.detector, "rule": self.rule, "alpha": self.alpha,
            "direction": self.direction, "confidence": self.confidence, "population": self.population,
            "split": {"method": "family-hash", "salt": self.split_salt,
                      "calibrationFraction": self.calibration_fraction},
            "strata": [{"name": name, "reason": reason} for name, reason in self.strata],
            "grid": list(self.grid),
        }

    def digest(self) -> str:
        return hashlib.sha256(canonical_json(self.as_dict())).hexdigest()


def split_families(families: Sequence[Hashable], plan: PreRegistration) -> dict[Hashable, str]:
    """Assign each family to `calibration` or `confirmation` by a salted hash.

    The assignment depends only on the family id and the committed salt, so it
    is reproducible and never looks at a score.
    """
    assignment: dict[Hashable, str] = {}
    for family in families:
        if family in assignment:
            continue
        key = hashlib.sha256(f"{plan.split_salt}|{family}".encode("utf-8")).digest()
        position = int.from_bytes(key[:8], "big") / 2.0 ** 64
        assignment[family] = "calibration" if position < plan.calibration_fraction else "confirmation"
    return assignment


def _require_commitment(plan: PreRegistration, committed_digest: str) -> None:
    if committed_digest != plan.digest():
        raise PreRegistrationError("the plan's digest was not committed before derivation (A5)")


def conformal_rank(count: int, alpha: float) -> int | None:
    """1-based order statistic of the split-conformal threshold, or None when n is too small."""
    rank = math.ceil((count + 1) * (1.0 - alpha))
    return rank if rank <= count else None


def conformal_threshold(negative_scores: Sequence[float], alpha: float, direction: str = "above") -> dict:
    """The split-conformal threshold from clean scores only.

    `above` alarms when a score exceeds the threshold; `below` when it falls
    under it. With fewer than ceil(1/alpha) - 1 negatives no threshold can carry
    the guarantee, and none is returned.
    """
    if direction not in DIRECTIONS:
        raise ValueError(f"direction must be one of {DIRECTIONS}")
    scores = [float(score) for score in negative_scores]
    if any(not math.isfinite(score) for score in scores):
        raise ValueError("calibration scores must be finite")
    count = len(scores)
    rank = conformal_rank(count, alpha)
    if rank is None:
        return {"threshold": None, "rank": None, "calibrationUnits": count, "alpha": alpha,
                "direction": direction, "status": "insufficient-negatives",
                "minimumNegatives": math.ceil(1.0 / alpha) - 1}
    ordered = sorted(scores) if direction == "above" else sorted(scores, reverse=True)
    return {"threshold": ordered[rank - 1], "rank": rank, "calibrationUnits": count, "alpha": alpha,
            "direction": direction, "status": "derived",
            "minimumNegatives": math.ceil(1.0 / alpha) - 1}


def derive_threshold(plan: PreRegistration, committed_digest: str,
                     calibration_negatives: Sequence[float]) -> dict:
    """Derive a split-conformal threshold under a committed plan."""
    _require_commitment(plan, committed_digest)
    if plan.rule != "split-conformal":
        raise PreRegistrationError("this plan uses Learn-then-Test")
    result = conformal_threshold(calibration_negatives, plan.alpha, plan.direction)
    return {"plan": plan.digest(), "detector": plan.detector, **result}


def binomial_far_p_value(alarms: int, units: int, alpha: float) -> float:
    """Exact p-value for H0: FAR >= alpha, given `alarms` of `units` clean units."""
    return binomial_cdf(alarms, units, alpha)


def learn_then_test(plan: PreRegistration, committed_digest: str,
                    alarms_at: Callable[[float], Sequence[bool]] | Mapping[float, Sequence[bool]]) -> dict:
    """Fixed-sequence Learn-then-Test over the plan's pre-ordered grid.

    `alarms_at(setting)` gives the per-unit alarms of the clean calibration
    negatives at one grid setting. The walk starts at the plan's first
    (most conservative) setting and stops at the first that fails to reject
    FAR >= alpha at level 1 - confidence; the last rejected setting is kept.
    """
    _require_commitment(plan, committed_digest)
    if plan.rule != "learn-then-test":
        raise PreRegistrationError("this plan uses the split-conformal rule")
    lookup = alarms_at if callable(alarms_at) else alarms_at.__getitem__
    level = 1.0 - plan.confidence
    steps = []
    selected = None
    for setting in plan.grid:
        flags = [bool(flag) for flag in lookup(setting)]
        if not flags:
            raise PreRegistrationError("no calibration negatives")
        count = sum(flags)
        p_value = binomial_far_p_value(count, len(flags), plan.alpha)
        rejected = p_value <= level
        steps.append({"setting": setting, "alarms": count, "units": len(flags),
                      "pValue": round(p_value, 12), "rejected": rejected})
        if not rejected:
            break
        selected = setting
    return {"plan": plan.digest(), "detector": plan.detector, "rule": "learn-then-test",
            "selected": selected, "status": "derived" if selected is not None else "no-valid-setting",
            "steps": steps}


@dataclass
class ConfirmationLedger:
    """Plan digests already confirmed: confirmation runs once, with no top-ups (A5)."""
    confirmed: dict[str, dict] = field(default_factory=dict)

    def confirm(self, plan: PreRegistration, committed_digest: str, threshold: float,
                confirmation_negative_alarms: Sequence[bool],
                positive_detections_by_mechanism: Mapping[str, Sequence[bool]],
                *, maximum_far: float, minimum_tpr: float, minimum_mechanisms: int = 2) -> dict:
        """Score the untouched confirmation cohort once and record the outcome.

        FAR is the CP upper bound on the confirmation negatives; detection must
        clear `minimum_tpr` (CP lower bound) on at least `minimum_mechanisms`
        construction mechanisms (A3). The thresholds of this rule are fitted on
        negatives only, so no mechanism was used for fitting.
        """
        _require_commitment(plan, committed_digest)
        digest = plan.digest()
        if digest in self.confirmed:
            raise PreRegistrationError("this plan was already confirmed; confirmation runs once (A5)")
        far = Rate(sum(bool(flag) for flag in confirmation_negative_alarms),
                   len(confirmation_negative_alarms), plan.confidence)
        mechanisms = {}
        for mechanism, detections in sorted(positive_detections_by_mechanism.items()):
            flags = [bool(flag) for flag in detections]
            rate = Rate(sum(flags), len(flags), plan.confidence)
            mechanisms[mechanism] = {**rate.as_dict(), "meets": bool(rate.units and rate.lower >= minimum_tpr)}
        passing = [name for name, result in mechanisms.items() if result["meets"]]
        far_meets = bool(far.units and far.upper <= maximum_far)
        qualified = far_meets and len(passing) >= minimum_mechanisms
        reasons = []
        if not far_meets:
            reasons.append("far-bound-not-met")
        if len(passing) < minimum_mechanisms:
            reasons.append("cross-mechanism-detection-not-met")
        outcome = {"plan": digest, "detector": plan.detector, "threshold": threshold,
                   "far": far.as_dict(), "maximumFAR": maximum_far, "minimumTPR": minimum_tpr,
                   "mechanisms": mechanisms, "mechanismsMeeting": passing,
                   "status": "qualified" if qualified else "refused", "reasons": reasons}
        self.confirmed[digest] = outcome
        return outcome
