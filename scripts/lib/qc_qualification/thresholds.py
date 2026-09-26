"""Pre-registered threshold derivation from clean clips only (audit section 5.5).

1. The plan (rule, grid, alpha, strata and split) is a `PreRegistration`. It is
   committed as a file in a `PreRegistrationStore` before any confirmation
   score exists, and every derivation and confirmation reads it back from
   there (A5); a plan held only in memory is refused. The repository store,
   `config/audio-qc-preregistrations/`, also requires the file to be committed
   in Git and unmodified at HEAD.
2. The split is by connected component of family, speaker and script, so the
   calibration and confirmation cohorts share no family, no speaker and no
   script.
3. Every rate and quantile counts source families, not clips (audit 5.4).
4. A single threshold is the split-conformal quantile of clean calibration
   scores, one per family: the ceil((n + 1)(1 - alpha))-th order statistic,
   which bounds the marginal false-alarm rate by alpha. Positives never enter
   the derivation: detection is measured, never optimized.
5. A multi-parameter rule walks a pre-ordered grid with fixed-sequence
   Learn-then-Test and keeps the last setting whose exact binomial test
   rejects "FAR > alpha".
6. Confirmation runs once per plan digest: its outcome, qualified or refused,
   is written to a `ConfirmationLedger` file created exclusively, so a second
   confirmation is refused in any process. It checks every requirement of the
   policy's operating point: pooled and per-language FAR on N2 (the
   per-language bound at the Bonferroni confidence over the languages the
   claim covers), the pooled N3 flag rate, clean abstention, detection per
   severity cell on enough mechanisms, the minimum units, and a matched sham
   for every positive mechanism whose FAR interval overlaps the N2 one (A4).
"""

from __future__ import annotations

import hashlib
import json
import math
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Hashable, Iterable, Mapping, Sequence

from .pcm import canonical_json
from .stats import DEFAULT_CONFIDENCE, Rate, binomial_cdf, bonferroni_confidence, family_rate

RULES = ("split-conformal", "learn-then-test")
DIRECTIONS = ("above", "below")
REPO = Path(__file__).resolve().parents[3]
PREREGISTRATION_DIRECTORY = REPO / "config" / "audio-qc-preregistrations"
PLAN_SCHEMA = "vocello.audioqc.preregistration/1"
CONFIRMATION_SCHEMA = "vocello.audioqc.confirmation/1"
SEVERITY_FLOORS = {"severe": "tprSevereMin", "moderate": "tprModerateMin"}


class PreRegistrationError(ValueError):
    """The plan is incomplete, not committed, or a derivation departs from it."""


@dataclass(frozen=True)
class PreRegistration:
    """The plan for one detector's threshold (A5)."""
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
            raise PreRegistrationError("the split needs a committed salt")
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
            "schema": PLAN_SCHEMA,
            "detector": self.detector, "rule": self.rule, "alpha": self.alpha,
            "direction": self.direction, "confidence": self.confidence, "population": self.population,
            "split": {"method": "component-hash", "disjointBy": ["family", "speaker", "script"],
                      "salt": self.split_salt, "calibrationFraction": self.calibration_fraction},
            "strata": [{"name": name, "reason": reason} for name, reason in self.strata],
            "grid": list(self.grid),
        }

    def digest(self) -> str:
        return hashlib.sha256(canonical_json(self.as_dict())).hexdigest()


# --------------------------------------------------------------------------- #
# Commitment (A5)
# --------------------------------------------------------------------------- #

def _git(root: Path, *arguments: str) -> int:
    return subprocess.run(["git", "-C", str(root), *arguments], stdout=subprocess.DEVNULL,
                          stderr=subprocess.DEVNULL, check=False).returncode


class PreRegistrationStore:
    """Committed plans, one canonical JSON file per plan digest.

    `commit` writes the file; `require` reads it back and checks it is the
    plan, byte for byte in canonical form. With `git_root`, `require` also
    demands that the file exists at HEAD and the working tree matches it, so
    the plan was committed before this run scored anything.
    """

    def __init__(self, directory: Path, *, git_root: Path | None = None) -> None:
        self.directory = Path(directory)
        self.git_root = None if git_root is None else Path(git_root)

    @classmethod
    def repository(cls) -> "PreRegistrationStore":
        return cls(PREREGISTRATION_DIRECTORY, git_root=REPO)

    def path(self, digest: str) -> Path:
        return self.directory / f"plan-{digest}.json"

    def commit(self, plan: PreRegistration) -> Path:
        path = self.path(plan.digest())
        text = json.dumps(plan.as_dict(), indent=2, sort_keys=True) + "\n"
        if path.exists():
            if path.read_text(encoding="utf-8") != text:
                raise PreRegistrationError(f"{path.name} exists with other content")
            return path
        self.directory.mkdir(parents=True, exist_ok=True)
        with path.open("x", encoding="utf-8") as handle:
            handle.write(text)
        return path

    def require(self, plan: PreRegistration) -> dict:
        digest = plan.digest()
        path = self.path(digest)
        if not path.is_file():
            raise PreRegistrationError(f"plan {digest[:12]} was not committed before derivation (A5)")
        try:
            stored = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            raise PreRegistrationError(f"{path.name} is unreadable: {error}") from error
        if stored != plan.as_dict() or hashlib.sha256(canonical_json(stored)).hexdigest() != digest:
            raise PreRegistrationError(f"{path.name} does not hold this plan (A5)")
        if self.git_root is not None:
            relative = path.resolve().relative_to(self.git_root.resolve()).as_posix()
            if _git(self.git_root, "cat-file", "-e", f"HEAD:{relative}") != 0:
                raise PreRegistrationError(f"{relative} is not committed in Git (A5)")
            if _git(self.git_root, "diff", "--quiet", "HEAD", "--", relative) != 0:
                raise PreRegistrationError(f"{relative} differs from its committed version (A5)")
        return stored


# --------------------------------------------------------------------------- #
# Split
# --------------------------------------------------------------------------- #

def split_families(units: Iterable[tuple[str, str, str]], plan: PreRegistration) -> dict[str, str]:
    """Assign each family to `calibration` or `confirmation`, disjoint by family, speaker and script.

    `units` are (family, speaker, script) triples. Families that share a
    speaker or a script, directly or through a chain, form one component and
    land on one side; the side comes from a salted hash of the component's
    smallest family id, so it is reproducible and never looks at a score.
    """
    parent: dict[tuple[str, str], tuple[str, str]] = {}

    def find(node: tuple[str, str]) -> tuple[str, str]:
        while parent[node] != node:
            parent[node] = parent[parent[node]]
            node = parent[node]
        return node

    for family, speaker, script in units:
        nodes = [("family", str(family)), ("speaker", str(speaker)), ("script", str(script))]
        for node in nodes:
            parent.setdefault(node, node)
        root = find(nodes[0])
        for node in nodes[1:]:
            other = find(node)
            if other != root:
                parent[other] = root
    components: dict[tuple[str, str], list[str]] = {}
    for node in parent:
        if node[0] == "family":
            components.setdefault(find(node), []).append(node[1])
    assignment: dict[str, str] = {}
    for members in components.values():
        key = hashlib.sha256(f"{plan.split_salt}|{min(members)}".encode("utf-8")).digest()
        position = int.from_bytes(key[:8], "big") / 2.0 ** 64
        side = "calibration" if position < plan.calibration_fraction else "confirmation"
        for family in members:
            assignment[family] = side
    sides = set(assignment.values())
    if assignment and sides != {"calibration", "confirmation"}:
        raise PreRegistrationError(f"the split left a cohort empty ({len(components)} disjoint components); "
                                   "choose another salt before committing the plan")
    return assignment


# --------------------------------------------------------------------------- #
# Derivation
# --------------------------------------------------------------------------- #

def conformal_rank(count: int, alpha: float) -> int | None:
    """1-based order statistic of the split-conformal threshold, or None when n is too small."""
    rank = math.ceil((count + 1) * (1.0 - alpha))
    return rank if rank <= count else None


def conformal_threshold(negative_scores: Sequence[float], alpha: float, direction: str = "above") -> dict:
    """The split-conformal threshold from clean scores only, one score per independent unit.

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


def family_scores(scores: Iterable[tuple[Hashable, float]], direction: str) -> list[float]:
    """One score per family: its most alarming clip (the largest for `above`, the smallest for `below`)."""
    if direction not in DIRECTIONS:
        raise ValueError(f"direction must be one of {DIRECTIONS}")
    worst: dict[Hashable, float] = {}
    pick = max if direction == "above" else min
    for family, score in scores:
        value = float(score)
        worst[family] = pick(worst[family], value) if family in worst else value
    return list(worst.values())


def derive_threshold(plan: PreRegistration, store: PreRegistrationStore,
                     calibration_negatives: Sequence[tuple[Hashable, float]]) -> dict:
    """Derive a split-conformal threshold under a committed plan, from (family, score) negatives."""
    store.require(plan)
    if plan.rule != "split-conformal":
        raise PreRegistrationError("this plan uses Learn-then-Test")
    scores = family_scores(calibration_negatives, plan.direction)
    result = conformal_threshold(scores, plan.alpha, plan.direction)
    return {"plan": plan.digest(), "detector": plan.detector, "unit": "source-family",
            "calibrationClips": len(calibration_negatives), **result}


def binomial_far_p_value(alarms: int, units: int, alpha: float) -> float:
    """Exact p-value for H0: FAR >= alpha, given `alarms` of `units` clean units."""
    return binomial_cdf(alarms, units, alpha)


def learn_then_test(plan: PreRegistration, store: PreRegistrationStore,
                    alarms_at: Callable[[float], Sequence[tuple[Hashable, bool]]]
                    | Mapping[float, Sequence[tuple[Hashable, bool]]]) -> dict:
    """Fixed-sequence Learn-then-Test over the plan's pre-ordered grid.

    `alarms_at(setting)` gives the (family, alarm) pairs of the clean
    calibration negatives at one grid setting; a family alarms if any of its
    clips does. The walk starts at the plan's first (most conservative) setting
    and stops at the first that fails to reject FAR >= alpha at level
    1 - confidence; the last rejected setting is kept.
    """
    store.require(plan)
    if plan.rule != "learn-then-test":
        raise PreRegistrationError("this plan uses the split-conformal rule")
    lookup = alarms_at if callable(alarms_at) else alarms_at.__getitem__
    level = 1.0 - plan.confidence
    steps = []
    selected = None
    for setting in plan.grid:
        rate = family_rate(lookup(setting))
        if not rate.units:
            raise PreRegistrationError("no calibration negatives")
        p_value = binomial_far_p_value(rate.events, rate.units, plan.alpha)
        rejected = p_value <= level
        steps.append({"setting": setting, "alarms": rate.events, "units": rate.units,
                      "pValue": round(p_value, 12), "rejected": rejected})
        if not rejected:
            break
        selected = setting
    return {"plan": plan.digest(), "detector": plan.detector, "rule": "learn-then-test", "unit": "source-family",
            "selected": selected, "status": "derived" if selected is not None else "no-valid-setting",
            "steps": steps}


# --------------------------------------------------------------------------- #
# Confirmation (A2-A5, A8)
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class ScoredUnit:
    """One scored clip of the confirmation cohort. `alarm` is None when the detector abstained."""
    family: str
    language: str
    speaker: str
    script: str
    alarm: bool | None


def _alarm_rate(units: Sequence[ScoredUnit], confidence: float) -> Rate:
    """False alarms (or flags) per family, over judged clips only."""
    return family_rate(((unit.family, unit.alarm) for unit in units if unit.alarm is not None), confidence)


def _miss_rate(units: Sequence[ScoredUnit], confidence: float) -> Rate:
    """Misses per family: a family is missed if any clip did not alarm, an abstention included."""
    return family_rate(((unit.family, unit.alarm is not True) for unit in units), confidence)


def _entry(rate: Rate, *, limit: float, side: str, minimum: int | None = None) -> dict:
    bound = rate.upper if side == "upper" else rate.lower
    meets = bool(rate.units) and (bound <= limit if side == "upper" else bound >= limit)
    enough = minimum is None or rate.units >= minimum
    return {**rate.as_dict(), "limit": limit, "minimumUnits": minimum, "meets": bool(meets and enough)}


def _overlap(first: Rate, second: Rate) -> bool:
    return bool(first.units and second.units and first.lower <= second.upper and second.lower <= first.upper)


def _severity(cell: str) -> str:
    return cell.rsplit("/", 1)[-1]


def evaluate_confirmation(plan: PreRegistration, threshold: float, *, operating_point: Mapping,
                          confidence: float, n2_negatives: Sequence[ScoredUnit],
                          n3_negatives: Sequence[ScoredUnit] = (),
                          positives: Mapping[str, Mapping[str, Sequence[ScoredUnit]]],
                          shams: Mapping[str, Sequence[ScoredUnit]]) -> dict:
    """Score the untouched confirmation cohort against one policy operating point.

    `operating_point` is `operatingPoints.warn`, `.fail` or `.evidenceLaneFail`
    of the qualification policy. `positives` maps each construction mechanism
    to its cells, keyed by severity or "subtype/severity"; `shams` maps each
    positive mechanism to its matched sham scores. Every rate counts families.
    """
    fail_like = "farPopulation" in operating_point
    units = operating_point["minimumUnits"]
    reasons: list[str] = []

    far = _alarm_rate(n2_negatives, confidence)
    pooled_floor = units["n2Negatives"] if fail_like else units["good"]
    pooled = _entry(far, limit=operating_point["farPooledMax"], side="upper", minimum=pooled_floor)
    if not pooled["meets"]:
        reasons.append("far-pooled-not-met")

    languages = sorted({unit.language for unit in n2_negatives})
    language_floor = units["languages"]
    per_language_confidence = bonferroni_confidence(confidence, max(len(languages), 1))
    per_language_minimum = units.get("n2NegativesPerLanguage") if fail_like else None
    per_language = {language: _entry(_alarm_rate([unit for unit in n2_negatives if unit.language == language],
                                                 per_language_confidence),
                                     limit=operating_point["farPerLanguageMax"], side="upper",
                                     minimum=per_language_minimum)
                    for language in languages}
    if len(languages) < language_floor:
        reasons.append("too-few-languages")
    if not all(entry["meets"] for entry in per_language.values()):
        reasons.append("far-per-language-not-met")
    if not fail_like:
        speakers = {unit.speaker for unit in n2_negatives}
        scripts = {unit.script for unit in n2_negatives}
        if len(speakers) < units["speakers"] or len(scripts) < units["scripts"]:
            reasons.append("too-few-speakers-or-scripts")

    abstention = _entry(family_rate(((unit.family, unit.alarm is None) for unit in n2_negatives), confidence),
                        limit=operating_point["cleanAbstentionMax"], side="upper")
    if not abstention["meets"]:
        reasons.append("clean-abstention-not-met")

    n3 = None
    if fail_like:
        n3 = _entry(_alarm_rate(n3_negatives, confidence), limit=operating_point["n3FlagRateMax"], side="upper")
        n3["perLanguage"] = {language: len({unit.family for unit in n3_negatives if unit.language == language})
                             for language in languages}
        n3_floor = units["n3NegativesPerLanguage"]
        if not n3["meets"]:
            reasons.append("n3-flag-rate-not-met")
        if any(count < n3_floor for count in n3["perLanguage"].values()) or not languages:
            reasons.append("n3-coverage-not-met")

    mechanisms = {}
    cell_floor = units["positivesPerCell"] if fail_like else units["bad"]
    for mechanism, cells in sorted(positives.items()):
        judged = {}
        for cell, scored in sorted(cells.items()):
            key = SEVERITY_FLOORS.get(_severity(cell))
            if key is None or (not fail_like and key != "tprSevereMin"):
                continue
            misses = _miss_rate(scored, confidence)
            judged[cell] = _entry(Rate(misses.units - misses.events, misses.units, confidence),
                                  limit=operating_point[key], side="lower", minimum=cell_floor)
        wanted = {"severe", "moderate"} if fail_like else {"severe"}
        covered = {_severity(cell) for cell in judged}
        mechanisms[mechanism] = {"cells": judged, "meets": bool(judged) and wanted <= covered
                                 and all(entry["meets"] for entry in judged.values())}
    meeting = [name for name, entry in mechanisms.items() if entry["meets"]]
    required_mechanisms = operating_point.get("mechanismsMin", 1)
    if len(meeting) < required_mechanisms:
        reasons.append("cross-mechanism-detection-not-met")

    sham_results = {}
    for mechanism in sorted(positives):
        scored = shams.get(mechanism)
        if not scored:
            sham_results[mechanism] = {"present": False, "overlaps": False}
            reasons.append(f"sham-missing:{mechanism}")
            continue
        rate = _alarm_rate(scored, confidence)
        overlaps = _overlap(rate, far)
        sham_results[mechanism] = {**rate.as_dict(), "present": True, "overlaps": overlaps}
        if not overlaps:
            reasons.append(f"sham-departs:{mechanism}")

    return {
        "schema": CONFIRMATION_SCHEMA,
        "plan": plan.digest(), "detector": plan.detector, "threshold": threshold, "unit": "source-family",
        "operatingPoint": "fail-like" if fail_like else "warn",
        "farPooled": pooled,
        "farPerLanguage": {"confidence": round(per_language_confidence, 12), "languages": per_language},
        "cleanAbstention": abstention,
        "n3": n3,
        "mechanisms": mechanisms, "mechanismsMeeting": meeting, "mechanismsMin": required_mechanisms,
        "shams": sham_results,
        "status": "qualified" if not reasons else "refused",
        "reasons": reasons,
    }


class ConfirmationLedger:
    """Confirmation outcomes, one file per plan digest, created exclusively.

    Confirmation runs once (A5): a second attempt on a digest is refused in any
    process or ledger instance, whatever the first outcome was, and a refused
    outcome is recorded like a qualified one.
    """

    def __init__(self, directory: Path) -> None:
        self.directory = Path(directory)

    @classmethod
    def repository(cls) -> "ConfirmationLedger":
        return cls(PREREGISTRATION_DIRECTORY)

    def path(self, digest: str) -> Path:
        return self.directory / f"confirmation-{digest}.json"

    def outcome(self, digest: str) -> dict | None:
        path = self.path(digest)
        return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None

    def confirm(self, plan: PreRegistration, store: PreRegistrationStore, threshold: float, *,
                operating_point: Mapping, confidence: float, n2_negatives: Sequence[ScoredUnit],
                n3_negatives: Sequence[ScoredUnit] = (),
                positives: Mapping[str, Mapping[str, Sequence[ScoredUnit]]],
                shams: Mapping[str, Sequence[ScoredUnit]]) -> dict:
        """Check the committed plan, refuse a second confirmation, score once and record it."""
        store.require(plan)
        path = self.path(plan.digest())
        if path.exists():
            raise PreRegistrationError("this plan was already confirmed; confirmation runs once (A5)")
        outcome = evaluate_confirmation(plan, threshold, operating_point=operating_point, confidence=confidence,
                                        n2_negatives=n2_negatives, n3_negatives=n3_negatives,
                                        positives=positives, shams=shams)
        self.directory.mkdir(parents=True, exist_ok=True)
        try:
            with path.open("x", encoding="utf-8") as handle:
                handle.write(json.dumps(outcome, indent=2, sort_keys=True, allow_nan=False) + "\n")
        except FileExistsError as error:
            raise PreRegistrationError("this plan was already confirmed; confirmation runs once (A5)") from error
        return outcome
