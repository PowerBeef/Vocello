#!/usr/bin/env python3
"""Fail-closed promotion decision for a delivery prompt candidate family.

Automatic layers may reject a candidate.  This decision additionally requires
paired, blinded listener evidence and enforces the pre-registered regression,
intelligibility, identity, naturalness, memory, seed, and receipt limits.  It
never generates audio or publishes evidence.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from delivery_statistics import holm_bonferroni, paired_bootstrap_delta


SCHEMA_VERSION = 1
PRESETS = ("neutral", "happy", "sad", "angry", "fearful", "surprised", "calm", "whisper")


class DecisionError(ValueError):
    """Candidate evidence is incomplete or cross-contaminated."""


def _binomial_at_least(successes: int, trials: int, probability: float = 0.5) -> float:
    if not 0 <= successes <= trials or not 0.0 < probability < 1.0:
        raise DecisionError("invalid exact-binomial input")
    return min(1.0, sum(
        math.comb(trials, count) * probability ** count * (1.0 - probability) ** (trials - count)
        for count in range(successes, trials + 1)
    ))


def _balanced_improvement(rows: list[dict[str, Any]], group: str) -> dict[str, Any]:
    grouped: dict[str, list[float]] = {}
    for row in rows:
        grouped.setdefault(row[group], []).append(
            float(row["candidateCorrect"] - row["baselineCorrect"])
        )
    means = {key: sum(values) / len(values) for key, values in grouped.items()}
    positive = {key: value for key, value in means.items() if value > 0}
    total_positive = sum(positive.values())
    largest_share = (
        max(positive.values()) / total_positive if total_positive > 0 else 1.0
    )
    return {
        "group": group, "groupCount": len(grouped), "means": means,
        "improvedCount": len(positive), "largestPositiveContributionShare": largest_share,
        "distributed": len(positive) >= 2 and largest_share <= 0.5 + 1e-12,
    }


def decide(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict) or payload.get("schemaVersion") != SCHEMA_VERSION:
        raise DecisionError(f"schemaVersion must be {SCHEMA_VERSION}")
    rows = payload.get("pairedIdentification")
    if not isinstance(rows, list) or len(rows) < 2:
        raise DecisionError("pairedIdentification requires at least two rows")
    identities: set[str] = set()
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise DecisionError(f"pairedIdentification[{index}] must be an object")
        identity = row.get("pairID")
        if not isinstance(identity, str) or not identity or identity in identities:
            raise DecisionError("pair IDs must be unique non-empty strings")
        identities.add(identity)
        if row.get("preset") not in PRESETS:
            raise DecisionError(f"{identity}: unknown preset")
        for field in ("speakerID", "scriptID"):
            if not isinstance(row.get(field), str) or not row[field]:
                raise DecisionError(f"{identity}: {field} is required")
        if row.get("candidateCorrect") not in (0, 1) or row.get("baselineCorrect") not in (0, 1):
            raise DecisionError(f"{identity}: correctness must be binary")

    bootstrap = paired_bootstrap_delta(
        [row["candidateCorrect"] for row in rows],
        [row["baselineCorrect"] for row in rows],
    )
    assert bootstrap is not None
    speaker_balance = _balanced_improvement(rows, "speakerID")
    script_balance = _balanced_improvement(rows, "scriptID")

    preset_regression_p: list[float | None] = []
    preset_rows: list[dict[str, Any]] = []
    for preset in PRESETS:
        subset = [row for row in rows if row["preset"] == preset]
        candidate_wins = sum(
            row["candidateCorrect"] == 1 and row["baselineCorrect"] == 0 for row in subset
        )
        baseline_wins = sum(
            row["candidateCorrect"] == 0 and row["baselineCorrect"] == 1 for row in subset
        )
        discordant = candidate_wins + baseline_wins
        regression_p = _binomial_at_least(baseline_wins, discordant) if discordant else None
        preset_regression_p.append(regression_p)
        preset_rows.append({
            "preset": preset, "n": len(subset), "candidateWins": candidate_wins,
            "baselineWins": baseline_wins, "discordant": discordant,
        })
    regression_holm = holm_bonferroni(preset_regression_p, alpha=0.05)
    for row, corrected in zip(preset_rows, regression_holm):
        row["regression"] = corrected
        row["statisticallySupportedRegression"] = (
            row["baselineWins"] > row["candidateWins"] and corrected["significant"]
        )

    two_afc = payload.get("instructedVersusNeutral2AFC")
    if not isinstance(two_afc, list):
        raise DecisionError("instructedVersusNeutral2AFC must be an array")
    two_afc_rows = []
    p_values = []
    for preset in PRESETS:
        subset = [row for row in two_afc if row.get("preset") == preset]
        correct = sum(row.get("correct") is True for row in subset)
        if any(row.get("correct") not in (True, False) for row in subset):
            raise DecisionError(f"{preset}: 2AFC correctness must be boolean")
        p_value = _binomial_at_least(correct, len(subset)) if subset else None
        p_values.append(p_value)
        two_afc_rows.append({"preset": preset, "correct": correct, "n": len(subset)})
    two_afc_holm = holm_bonferroni(p_values, alpha=0.05)
    for row, corrected in zip(two_afc_rows, two_afc_holm):
        row["aboveChance"] = corrected

    metrics = payload.get("automaticGuardrails")
    if not isinstance(metrics, dict):
        raise DecisionError("automaticGuardrails is required")
    expected_metrics = {
        "newHardAudioQCFailures": (0, lambda value: value == 0),
        "werCERAbsoluteDelta": (0.01, lambda value: value <= 0.01),
        "medianSpeakerSimilarityDelta": (-0.02, lambda value: value >= -0.02),
        "relativeUTMOSDelta": (-0.10, lambda value: value >= -0.10),
    }
    metric_results = {}
    for name, (limit, predicate) in expected_metrics.items():
        value = metrics.get(name)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise DecisionError(f"{name} must be finite numeric evidence")
        metric_results[name] = {"value": value, "limit": limit, "passed": predicate(value)}

    invariants = payload.get("runtimeInvariants")
    required_invariants = ("memoryQualified", "cancellationValid", "seedIdentityValid", "instructionReceiptsValid")
    if not isinstance(invariants, dict) or any(invariants.get(name) not in (True, False) for name in required_invariants):
        raise DecisionError(f"runtimeInvariants requires booleans {required_invariants}")

    listener_authority = payload.get("listenerAuthority")
    if not isinstance(listener_authority, dict):
        raise DecisionError("listenerAuthority is required")
    authority_passed = (
        listener_authority.get("independentListenerCount", 0) >= 3
        and listener_authority.get("allOutputLanguagesFluentlyCovered") is True
        and listener_authority.get("holdoutOpenedOnce") is True
    )

    failures = []
    if bootstrap["lower"] <= 0:
        failures.append("listener-identification-bootstrap-lower-not-positive")
    if not speaker_balance["distributed"]:
        failures.append("improvement-not-distributed-across-speakers")
    if not script_balance["distributed"]:
        failures.append("improvement-not-distributed-across-scripts")
    if any(row["statisticallySupportedRegression"] for row in preset_rows):
        failures.append("preset-regression-after-holm")
    if not all(row["aboveChance"]["significant"] for row in two_afc_rows):
        failures.append("instructed-versus-neutral-2afc-not-above-chance-after-holm")
    failures.extend(
        f"automatic-guardrail:{name}" for name, row in metric_results.items() if not row["passed"]
    )
    failures.extend(
        f"runtime-invariant:{name}" for name in required_invariants if not invariants[name]
    )
    if not authority_passed:
        failures.append("listener-authority-incomplete")
    return {
        "schemaVersion": SCHEMA_VERSION, "kind": "delivery-candidate-promotion-decision",
        "candidateFamily": payload.get("candidateFamily"),
        "verdict": "qualifies" if not failures else "does-not-qualify",
        "failures": failures, "listenerIdentificationImprovement": bootstrap,
        "speakerBalance": speaker_balance, "scriptBalance": script_balance,
        "presetRegressionTests": preset_rows, "twoAFC": two_afc_rows,
        "automaticGuardrails": metric_results,
        "runtimeInvariants": {name: invariants[name] for name in required_invariants},
        "listenerAuthority": {**listener_authority, "passed": authority_passed},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    try:
        report = decide(json.loads(args.input.read_text(encoding="utf-8")))
        text = json.dumps(report, indent=2, sort_keys=True) + "\n"
        if args.out:
            args.out.write_text(text, encoding="utf-8")
        else:
            print(text, end="")
        return 0 if report["verdict"] == "qualifies" else 2
    except (OSError, json.JSONDecodeError, DecisionError, ValueError) as error:
        print(f"Delivery promotion decision: FAIL\n{error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
