"""Loader and validator of `config/audio-qc-qualification-policy.json`.

The validator checks meaning, not wording: the five authority rules keep their
values, A1-A10 are present in order, fail is stricter than warn at every
operating point (A8), every declared minimum can meet its own bound with
perfect results (a floor that cannot is refused, as the prosody holdout policy
refuses one), the sample-size table equals the exact Clopper-Pearson
recomputation, and the verdict vocabulary and lane gating sets are the ones
the composer implements. A per-language bound is a simultaneous claim over the
operating point's languages, so its floor is checked at the Bonferroni
confidence the operating point states; the N3 flag-rate bound is pooled.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from . import composer
from .stats import bonferroni_confidence, cp_lower, cp_upper, minimum_units

REPO = Path(__file__).resolve().parents[3]
POLICY_PATH = REPO / "config" / "audio-qc-qualification-policy.json"
AUTHORITY_RULES = {
    "requiresUntouchedConfirmation": True,
    "requiresIndependentReferenceEvidence": True,
    "requiresIndependentHumanLabels": False,
    "automaticMetricsMayScreenOnly": True,
    "sourceChangeRequiresExplicitReview": True,
    "currentBoundaryRemainsUntilQualified": True,
}
ADDITIONS = tuple(f"A{number}" for number in range(1, 11))
LABEL_TIERS = tuple(f"T{number}" for number in range(1, 7))
POPULATIONS = ("N1", "N2", "N3", "S", "P1", "P2", "P3", "P4")


class PolicyError(ValueError):
    """The policy file is unreadable."""


def load_policy(path: Path = POLICY_PATH) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise PolicyError(f"{path.name} is unreadable: {error}") from error
    if not isinstance(value, dict):
        raise PolicyError(f"{path.name} must hold a JSON object")
    return value


def policy_digest(path: Path = POLICY_PATH) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _rate(errors: list[str], where: str, value: Any) -> bool:
    if not _number(value) or not 0.0 < value < 1.0:
        errors.append(f"{where} must be a rate in (0, 1)")
        return False
    return True


def _count(errors: list[str], where: str, value: Any) -> bool:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        errors.append(f"{where} must be a positive integer")
        return False
    return True


def _feasible_far(errors: list[str], where: str, units: int, bound: float, confidence: float) -> None:
    ceiling = cp_upper(0, units, confidence)
    if ceiling > bound:
        errors.append(f"{where}: {units} units with zero errors bound FAR at {ceiling:.4f} "
                      f"(confidence {confidence:g}), above {bound}; the floor needs "
                      f"{minimum_units(bound, 0, confidence)}")


def per_language_confidence(confidence: float, languages: int) -> float:
    """The Bonferroni confidence of a simultaneous per-language claim over `languages`."""
    return bonferroni_confidence(confidence, languages)


def _stated_confidence(errors: list[str], name: str, point: dict, confidence: float, languages: int) -> float:
    """The exact per-language confidence, after checking the one the policy states (6 decimals)."""
    exact = per_language_confidence(confidence, languages)
    stated = point.get("perLanguageConfidence")
    if not _number(stated) or abs(stated - exact) > 5e-7:
        errors.append(f"operatingPoints.{name}.perLanguageConfidence must state the Bonferroni confidence over "
                      f"its {languages} languages, {round(exact, 6)}")
    return exact


def _feasible_tpr(errors: list[str], where: str, units: int, bound: float, confidence: float) -> None:
    floor = cp_lower(units, units, confidence)
    if floor < bound:
        errors.append(f"{where}: {units} positives with zero misses bound TPR at {floor:.4f}, below {bound}")


def _check_fail_like(errors: list[str], name: str, point: dict, confidence: float) -> None:
    for key in ("farPooledMax", "farPerLanguageMax", "n3FlagRateMax", "tprSevereMin", "tprModerateMin",
                "cleanAbstentionMax"):
        _rate(errors, f"operatingPoints.{name}.{key}", point.get(key))
    if point.get("farPopulation") != "N2":
        errors.append(f"operatingPoints.{name}.farPopulation must be N2 (A2)")
    if not isinstance(point.get("mechanismsMin"), int) or point.get("mechanismsMin", 0) < 2:
        errors.append(f"operatingPoints.{name}.mechanismsMin must be at least 2 (A3)")
    units = point.get("minimumUnits")
    if not isinstance(units, dict):
        errors.append(f"operatingPoints.{name}.minimumUnits must be an object")
        return
    keys = ("n2Negatives", "n2NegativesPerLanguage", "languages", "n3NegativesPerLanguage", "positivesPerCell")
    if not all(_count(errors, f"operatingPoints.{name}.minimumUnits.{key}", units.get(key)) for key in keys):
        return
    if not all(_number(point.get(key)) for key in ("farPooledMax", "farPerLanguageMax", "n3FlagRateMax",
                                                     "tprSevereMin", "tprModerateMin")):
        return
    if units["n2Negatives"] < units["n2NegativesPerLanguage"] * units["languages"]:
        errors.append(f"operatingPoints.{name}: pooled N2 negatives are fewer than the per-language floors")
    if point.get("n3FlagRateScope") != "pooled":
        errors.append(f"operatingPoints.{name}.n3FlagRateScope must be pooled (600 N3 at ten languages, decision 5)")
    per_language = _stated_confidence(errors, name, point, confidence, units["languages"])
    _feasible_far(errors, f"operatingPoints.{name} pooled N2", units["n2Negatives"], point["farPooledMax"],
                  confidence)
    _feasible_far(errors, f"operatingPoints.{name} per-language N2", units["n2NegativesPerLanguage"],
                  point["farPerLanguageMax"], per_language)
    _feasible_far(errors, f"operatingPoints.{name} pooled N3", units["n3NegativesPerLanguage"] * units["languages"],
                  point["n3FlagRateMax"], confidence)
    _feasible_tpr(errors, f"operatingPoints.{name} severe positives", units["positivesPerCell"],
                  point["tprSevereMin"], confidence)
    if point["tprModerateMin"] > point["tprSevereMin"]:
        errors.append(f"operatingPoints.{name}: moderate detection cannot be stricter than severe")


def validate_policy(policy: dict[str, Any]) -> list[str]:
    """Every problem found, in file order; an empty list is a valid policy."""
    errors: list[str] = []
    if policy.get("schemaVersion") != 1 or policy.get("policy") != "audio-qc-qualification":
        errors.append("schemaVersion must be 1 and policy 'audio-qc-qualification'")
    if policy.get("status") not in ("draft", "adopted"):
        errors.append("status must be draft or adopted")

    rules = policy.get("authorityRules")
    if not isinstance(rules, dict):
        errors.append("authorityRules must be an object")
    else:
        for key, expected in AUTHORITY_RULES.items():
            if rules.get(key) is not expected:
                errors.append(f"authorityRules.{key} must stay {str(expected).lower()} (carried over verbatim)")
        text = rules.get("text")
        if not isinstance(text, list) or len(text) != 5 or any(not isinstance(line, str) or not line
                                                                for line in text):
            errors.append("authorityRules.text must keep the five rules")

    additions = policy.get("additions")
    ids = [entry.get("id") for entry in additions] if isinstance(additions, list) else []
    if tuple(ids) != ADDITIONS:
        errors.append("additions must be A1 through A10, in order")
    elif any(not entry.get("title") or not entry.get("rule") for entry in additions):
        errors.append("every addition needs a title and a rule")

    tiers = policy.get("labelTiers")
    if not isinstance(tiers, list) or tuple(entry.get("id") for entry in tiers) != LABEL_TIERS:
        errors.append("labelTiers must be T1 through T6, in order")
    populations = policy.get("populations")
    if not isinstance(populations, list) or tuple(entry.get("id") for entry in populations) != POPULATIONS:
        errors.append(f"populations must be {', '.join(POPULATIONS)}")

    statistics = policy.get("statistics") if isinstance(policy.get("statistics"), dict) else {}
    confidence = statistics.get("confidence")
    if statistics.get("method") != "clopper-pearson-one-sided":
        errors.append("statistics.method must be clopper-pearson-one-sided")
    if not _rate(errors, "statistics.confidence", confidence):
        confidence = 0.95
    if statistics.get("unitOfIndependence") != "source-family":
        errors.append("statistics.unitOfIndependence must be source-family")
    bootstrap = statistics.get("clusterBootstrap") if isinstance(statistics.get("clusterBootstrap"), dict) else {}
    _count(errors, "statistics.clusterBootstrap.resamples", bootstrap.get("resamples"))
    if isinstance(bootstrap.get("seed"), bool) or not isinstance(bootstrap.get("seed"), int):
        errors.append("statistics.clusterBootstrap.seed must be a fixed integer")
    multiplicity = statistics.get("multiplicity") if isinstance(statistics.get("multiplicity"), dict) else {}
    languages = multiplicity.get("simultaneousLanguages")
    if multiplicity.get("method") != "bonferroni":
        errors.append("statistics.multiplicity.method must be bonferroni")
    elif _count(errors, "statistics.multiplicity.simultaneousLanguages", languages):
        expected = minimum_units(0.05, 0, 1.0 - (1.0 - confidence) / languages)
        if multiplicity.get("zeroErrorUnitsPerLanguageAtFivePercent") != expected:
            errors.append(f"statistics.multiplicity: a simultaneous {languages}-language claim at 5% needs "
                          f"{expected} units per language")
    table = statistics.get("sampleSizeTable")
    if not isinstance(table, list) or not table:
        errors.append("statistics.sampleSizeTable must list the section 5.4 table")
    else:
        for row in table:
            target = row.get("target") if isinstance(row, dict) else None
            if not _rate(errors, "statistics.sampleSizeTable.target", target):
                continue
            for errors_key, units in (row.get("clopperPearson") or {}).items():
                expected = minimum_units(target, int(errors_key), confidence)
                if units != expected:
                    errors.append(f"sampleSizeTable: target {target} with {errors_key} errors needs "
                                  f"{expected} units, not {units}")
            if row.get("wilsonTwoSidedZeroErrors") != minimum_units(target, 0, method="wilson"):
                errors.append(f"sampleSizeTable: the Wilson zero-error floor for {target} is "
                              f"{minimum_units(target, 0, method='wilson')}")

    points = policy.get("operatingPoints") if isinstance(policy.get("operatingPoints"), dict) else {}
    warn, fail, lane = points.get("warn"), points.get("fail"), points.get("evidenceLaneFail")
    if not all(isinstance(point, dict) for point in (warn, fail, lane)):
        errors.append("operatingPoints must define warn, fail and evidenceLaneFail")
        return errors
    for key in ("farPooledMax", "farPerLanguageMax", "tprSevereMin", "cleanAbstentionMax"):
        _rate(errors, f"operatingPoints.warn.{key}", warn.get(key))
    warn_units = warn.get("minimumUnits") if isinstance(warn.get("minimumUnits"), dict) else {}
    if all(_count(errors, f"operatingPoints.warn.minimumUnits.{key}", warn_units.get(key))
           for key in ("calibration", "good", "bad", "speakers", "scripts", "languages")) \
            and all(_number(warn.get(key)) for key in ("farPooledMax", "farPerLanguageMax", "tprSevereMin")):
        _feasible_far(errors, "operatingPoints.warn pooled", warn_units["good"], warn["farPooledMax"], confidence)
        warn_language = _stated_confidence(errors, "warn", warn, confidence, warn_units["languages"])
        _feasible_far(errors, "operatingPoints.warn per-language", warn_units["good"] // warn_units["languages"],
                      warn["farPerLanguageMax"], warn_language)
        _feasible_tpr(errors, "operatingPoints.warn severe positives", warn_units["bad"], warn["tprSevereMin"],
                      confidence)
    _check_fail_like(errors, "fail", fail, confidence)
    _check_fail_like(errors, "evidenceLaneFail", lane, confidence)
    for name, point in (("fail", fail), ("evidenceLaneFail", lane)):
        covered = (point.get("minimumUnits") or {}).get("languages") if isinstance(point.get("minimumUnits"), dict) \
            else None
        if isinstance(languages, int) and covered != languages:
            errors.append(f"operatingPoints.{name} covers {covered} languages, not the "
                          f"{languages} of statistics.multiplicity")
    if lane.get("productAffecting") is not False or lane.get("appliesTo") != ["evidence-lane"]:
        errors.append("operatingPoints.evidenceLaneFail applies to evidence lanes only, never to a product verdict")
    comparable = all(_number(point.get(key)) for point in (warn, fail, lane)
                     for key in ("farPooledMax", "farPerLanguageMax", "tprSevereMin", "cleanAbstentionMax"))
    if comparable:
        # A8: fail is stricter than warn; the evidence-lane fail sits between them.
        if not (fail["farPooledMax"] <= lane["farPooledMax"] < warn["farPooledMax"]
                and fail["farPerLanguageMax"] <= lane["farPerLanguageMax"] < warn["farPerLanguageMax"]):
            errors.append("A8: fail FAR bounds must be stricter than the evidence-lane bounds, and those than warn")
        if not fail["tprSevereMin"] > warn["tprSevereMin"] or not lane["tprSevereMin"] > warn["tprSevereMin"]:
            errors.append("A8: fail detection floors must exceed the warn floor")
        if fail["cleanAbstentionMax"] > warn["cleanAbstentionMax"]:
            errors.append("A8: fail may abstain on clean speech no more often than warn")
    shadow = points.get("shadow")
    if shadow != {"blocks": False, "countsAsPass": False}:
        errors.append("operatingPoints.shadow never blocks and never counts as pass")
    if not isinstance(points.get("physicalEventsT1Only"), list) or not points.get("physicalEventsT1Only"):
        errors.append("operatingPoints.physicalEventsT1Only must list the physically defined events")

    derivation = policy.get("thresholdDerivation") if isinstance(policy.get("thresholdDerivation"), dict) else {}
    for key, expected in (("fitOn", "clean-negatives-only"), ("singleThresholdRule", "split-conformal"),
                          ("multiParameterRule", "learn-then-test-fixed-sequence"), ("tprOptimized", False),
                          ("requiresPreRegistrationDigest", True), ("confirmOnce", True),
                          ("stratificationRequiresDeclaredReason", True)):
        if derivation.get(key) != expected or type(derivation.get(key)) is not type(expected):
            errors.append(f"thresholdDerivation.{key} must be {json.dumps(expected)}")

    verdicts = policy.get("verdicts") if isinstance(policy.get("verdicts"), dict) else {}
    if tuple(verdicts.get("detectorStatuses") or ()) != composer.DETECTOR_STATUSES:
        errors.append("verdicts.detectorStatuses must match the composer")
    if tuple(verdicts.get("takeStatuses") or ()) != composer.TAKE_STATUSES:
        errors.append("verdicts.takeStatuses must match the composer")
    if tuple(verdicts.get("precedence") or ()) != composer.PRECEDENCE:
        errors.append("verdicts.precedence must be fail, unavailable, abstain, warn, uncalibrated, pass")
    if verdicts.get("composition") != composer.COMPOSITION:
        errors.append(f"verdicts.composition must be {composer.COMPOSITION}")
    swift = verdicts.get("swiftOutcomes")
    if not isinstance(swift, dict) or set(swift) != set(composer.DETECTOR_STATUSES):
        errors.append("verdicts.swiftOutcomes must map every detector status")
    if policy.get("laneGatingSets") != composer.LANE_GATING:
        errors.append("laneGatingSets must match the composer's lanes")
    transitions = policy.get("statusTransitions") if isinstance(policy.get("statusTransitions"), dict) else {}
    if transitions.get("judgeStatuses") != ["candidate", "shadow", "warn", "gating", "retired", "quarantined"]:
        errors.append("statusTransitions.judgeStatuses must list the six judge statuses")
    if transitions.get("consensusRequiresPhiAudit") is not True:
        errors.append("statusTransitions.consensusRequiresPhiAudit must be true")
    return errors
