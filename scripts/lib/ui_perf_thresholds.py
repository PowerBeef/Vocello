"""Calibration and derivation of the warn-only ui-perf ceilings (audit #34, #77, #78).

The ceiling contracts (`config/ui-perf-thresholds.json`, `config/ui-perf-thresholds-ios.json`)
name the hardware profile and display refresh interval they were derived on. A run on
another profile or refresh rate gets one `uiperf.uncalibrated:<profile>` code instead
of ceiling verdicts, so a faster host is never scored against a slower host's numbers.

Ceilings come from counted ui-perf records of one profile:

* ``spread-v1`` (maintainer decision 2026-09-25): at least three runs; per confirmatory
  scenario, ``median x max(1.3, 1 + 3 x relative range)``, where the relative range is
  ``(max - min) / median``. Scenarios whose run-to-run spread is under 10% get the
  1.3x floor (the two terms meet at exactly 10%); noisier scenarios get proportionally
  more room, which always clears the worst observed run.
* ``v3``: the 2026-09-15 rule, kept so the committed M2 ceilings stay reproducible:
  ``max(2 x median, 1.25 x max)`` for hitch time and ``max(1.5 x median, 1.25 x max)``
  for the maximum gap.

Hitch ceilings round up to 0.5 ms/s and gap ceilings to 10 ms, with floors of 5 ms/s and
40 ms so a quiet scenario never warns on a single frame.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import statistics
import sys
from typing import Any, Callable, Iterable

SPREAD_RULE = "spread-v1"
V3_RULE = "v3"
RULES = (SPREAD_RULE, V3_RULE)
MINIMUM_RUNS = 3
SPREAD_FLOOR_MULTIPLIER = 1.3
SPREAD_SLOPE = 3.0
HITCH_FLOOR_MS_PER_S = 5.0
GAP_FLOOR_MS = 40.0
HITCH_STEP = 0.5
GAP_STEP = 10.0
REFRESH_TOLERANCE_MS = 0.5
UNCALIBRATED_CODE = "uiperf.uncalibrated"


class DerivationError(ValueError):
    pass


def validate_calibration_fields(thresholds: dict[str, Any]) -> list[str]:
    """Problems with a contract's calibration identity (empty when it is complete)."""
    problems = []
    profile = thresholds.get("calibrationProfile")
    if not isinstance(profile, str) or not profile.strip():
        problems.append("names no calibrationProfile")
    refresh = thresholds.get("calibrationRefreshIntervalMS")
    if isinstance(refresh, bool) or not isinstance(refresh, (int, float)) or not 1000.0 / 140.0 <= refresh <= 1000.0 / 30.0:
        problems.append("needs a calibrationRefreshIntervalMS inside the 30-140 Hz band")
    footprint = thresholds.get("footprintGrowthCeilingMB")
    if footprint is not None and (isinstance(footprint, bool) or not isinstance(footprint, (int, float)) or footprint <= 0):
        problems.append("has a footprintGrowthCeilingMB that is not a positive number")
    return problems


def calibration(
    thresholds: dict[str, Any], canonical_profile_id: str, refresh_intervals_ms: Iterable[float],
) -> dict[str, Any]:
    """Whether the contract's ceilings apply to a run on the canonical profile.

    Records publish only on the canonical profile, so the ceilings apply only when
    the contract was derived there, at the refresh interval every scenario observed.
    """
    profile = thresholds["calibrationProfile"]
    expected_refresh = float(thresholds["calibrationRefreshIntervalMS"])
    reasons = []
    if profile != canonical_profile_id:
        reasons.append(f"ceilings calibrated on {profile}, canonical profile is {canonical_profile_id}")
    observed = sorted({round(float(value), 2) for value in refresh_intervals_ms})
    off = [value for value in observed if abs(value - expected_refresh) > REFRESH_TOLERANCE_MS]
    if off:
        reasons.append(
            f"refresh interval {', '.join(f'{value:g}' for value in off)} ms differs from the "
            f"calibrated {expected_refresh:g} ms"
        )
    return {
        "calibrated": not reasons,
        "calibrationProfile": profile,
        "calibrationRefreshIntervalMS": expected_refresh,
        "reasons": reasons,
        "code": None if not reasons else f"{UNCALIBRATED_CODE}:{profile}",
    }


def footprint_growth_warning(summary: dict[str, Any], thresholds: dict[str, Any]) -> list[str]:
    """Warn-only: memory the scenario's own window grew by (audit #33(a)).

    Growth is the in-window peak over the footprint at the window's start; product
    warms landing inside a navigation window show here long before any hitch does.
    """
    ceiling = thresholds.get("footprintGrowthCeilingMB")
    scenario = summary["scenario"]
    if ceiling is None or scenario not in thresholds["confirmatoryScenarios"]:
        return []
    start, peak = summary.get("footprintStartMB"), summary.get("footprintPeakMB")
    if not isinstance(start, (int, float)) or not isinstance(peak, (int, float)):
        return []
    growth = peak - start
    if growth <= ceiling:
        return []
    return [f"uiperf.footprint:{scenario}({round(growth)}/{round(ceiling)})"]


def _round_up(value: float, step: float) -> float:
    return round(math.ceil(value / step - 1e-9) * step, 2)


def _ceiling(values: list[float], *, rule: str, v3_median_factor: float, floor: float, step: float) -> tuple[float, dict]:
    median = statistics.median(values)
    worst = max(values)
    relative_range = (worst - min(values)) / median if median > 0 else 0.0
    if rule == SPREAD_RULE:
        multiplier = max(SPREAD_FLOOR_MULTIPLIER, 1.0 + SPREAD_SLOPE * relative_range)
        raw = median * multiplier
    else:
        multiplier = v3_median_factor
        raw = max(v3_median_factor * median, 1.25 * worst)
    ceiling = _round_up(max(floor, raw), step)
    return ceiling, {
        "values": [round(value, 3) for value in values],
        "median": round(median, 3),
        "relativeRange": round(relative_range, 4),
        "multiplier": round(multiplier, 4),
        "ceiling": ceiling,
    }


def derive(records: list[dict[str, Any]], base: dict[str, Any], *, rule: str = SPREAD_RULE) -> dict[str, Any]:
    """A ceiling contract derived from counted ui-perf records of one profile.

    `base` supplies what the records cannot: the confirmatory designation, the
    schema fields and the footprint-growth ceiling. The result names its runs,
    its rule, the profile and refresh interval they ran on, and each scenario's
    inputs, so the derivation can be replayed.
    """
    if rule not in RULES:
        raise DerivationError(f"unknown derivation rule {rule!r}")
    if len(records) < MINIMUM_RUNS:
        raise DerivationError(f"ceilings need at least {MINIMUM_RUNS} counted runs, got {len(records)}")
    kinds = {record.get("run", {}).get("kind") for record in records}
    if kinds != {"ui-perf"}:
        raise DerivationError("every derivation input must be a ui-perf record")
    platforms = {record["run"].get("platform") for record in records}
    profiles = {record.get("hardware", {}).get("profileID") for record in records}
    if len(platforms) != 1 or len(profiles) != 1:
        raise DerivationError(
            f"derivation inputs span platforms {sorted(map(str, platforms))} and profiles {sorted(map(str, profiles))}"
        )
    run_ids = [record["run"]["id"] for record in records]
    if len(set(run_ids)) != len(run_ids):
        raise DerivationError("derivation inputs repeat a run")
    confirmatory = list(base["confirmatoryScenarios"])

    def take(record: dict[str, Any], scenario: str) -> dict[str, Any]:
        matches = [item for item in record.get("takes", []) if item.get("cell") == f"ui-perf/{scenario}"]
        if len(matches) != 1:
            raise DerivationError(f"{record['run']['id']} has no single {scenario} take")
        return matches[0]["metrics"]

    refresh = sorted({
        round(float(take(record, scenario)["uiRefreshIntervalMS"]), 2)
        for record in records for scenario in confirmatory
    })
    if refresh[-1] - refresh[0] > REFRESH_TOLERANCE_MS:
        raise DerivationError(f"derivation inputs ran at different refresh intervals: {refresh}")
    hitch, gap, inputs = {}, {}, {}
    for scenario in confirmatory:
        hitch_values = [float(take(record, scenario)["uiHitchTimeMSPerS"]) for record in records]
        gap_values = [float(take(record, scenario)["uiMaxGapMS"]) for record in records]
        hitch[scenario], hitch_inputs = _ceiling(
            hitch_values, rule=rule, v3_median_factor=2.0, floor=HITCH_FLOOR_MS_PER_S, step=HITCH_STEP,
        )
        gap[scenario], gap_inputs = _ceiling(
            gap_values, rule=rule, v3_median_factor=1.5, floor=GAP_FLOOR_MS, step=GAP_STEP,
        )
        inputs[scenario] = {"hitchTimeMSPerS": hitch_inputs, "maxGapMS": gap_inputs}
    profile = profiles.pop()
    contract = {
        "schemaVersion": base.get("schemaVersion", 1),
        "basis": (
            f"Derived with {rule} from {len(records)} counted ui-perf runs on {profile} "
            f"({', '.join(run_ids)}) by check_*_ui_perf.py --derive-thresholds. "
            + (
                "Per confirmatory scenario: median x max(1.3, 1 + 3 x (max - min) / median)"
                if rule == SPREAD_RULE else
                "Per confirmatory scenario: max(2 x median, 1.25 x max) hitch, max(1.5 x median, 1.25 x max) gap"
            )
            + "; hitch rounded up to 0.5 ms/s (floor 5), gap to 10 ms (floor 40). Warn-only."
        ),
        "calibrationProfile": profile,
        "calibrationRefreshIntervalMS": round(statistics.median(refresh), 2),
        "calibrationRuns": run_ids,
        "derivationRule": rule,
        "warnOnly": True,
        "confirmatoryScenarios": confirmatory,
        "hitchCeilingMSPerS": hitch,
        "maxGapCeilingMS": gap,
    }
    if base.get("footprintGrowthCeilingMB") is not None:
        contract["footprintGrowthCeilingMB"] = base["footprintGrowthCeilingMB"]
    contract["derivationInputs"] = inputs
    return contract


def load_record(reference: str, runs_root: Path) -> dict[str, Any]:
    """A committed ui-perf record by path or by run ID."""
    path = Path(reference)
    if not path.is_file():
        path = runs_root / f"{reference}.json"
    if not path.is_file():
        raise DerivationError(f"no ui-perf record {reference!r}")
    return json.loads(path.read_text(encoding="utf-8"))


def derive_main(
    argv: list[str],
    *,
    platform: str,
    default_thresholds: Path,
    load_thresholds: Callable[[Path], dict[str, Any]],
    runs_root: Path,
) -> int:
    """`--derive-thresholds RECORD...` for a platform's ui-perf checker (audit #34, #78)."""
    parser = argparse.ArgumentParser(
        description=f"Derive warn-only {platform} ui-perf ceilings from at least three counted runs of one profile.",
    )
    parser.add_argument("--derive-thresholds", nargs="+", required=True, metavar="RECORD",
                        help="ui-perf record paths or run IDs (benchmarks/runs/ui-perf/<id>.json)")
    parser.add_argument("--rule", choices=RULES, default=SPREAD_RULE)
    parser.add_argument("--thresholds", type=Path, default=default_thresholds,
                        help="the contract whose confirmatory scenarios and footprint ceiling carry over")
    parser.add_argument("--write", type=Path, metavar="PATH",
                        help="write the derived contract here instead of printing it")
    args = parser.parse_args(argv)
    try:
        base = load_thresholds(args.thresholds)
        records = [load_record(reference, runs_root) for reference in args.derive_thresholds]
        if {record.get("run", {}).get("platform") for record in records} != {platform}:
            raise DerivationError(f"derivation inputs must be {platform} ui-perf records")
        contract = derive(records, base, rule=args.rule)
    except (ValueError, OSError, KeyError) as error:
        print(f"ui-perf derivation FAILED: {error}", file=sys.stderr)
        return 1
    text = json.dumps(contract, indent=2) + "\n"
    if args.write:
        args.write.write_text(text, encoding="utf-8")
        print(f"ui-perf ceilings ({args.rule}, {contract['calibrationProfile']}) -> {args.write}")
    else:
        sys.stdout.write(text)
    return 0
