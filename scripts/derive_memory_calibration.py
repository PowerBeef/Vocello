#!/usr/bin/env python3
"""Derive the provisional memory bounds from a consented memory-lane record.

Two bounds in config/memory-qualification-policy.json wait for a measured run
(BT-01, audit #25/#26/#66):

- `unobservedGapBound`: no gap between two consecutive samples of a take's one
  memory series may exceed max(targetIntervalMultiple x the sampler cadence,
  floorMS). Provisional at twice the cadence with a 500 ms floor; the floor
  tiers (`floorTiers`: the 8 GB Mac and the iPhone) keep a provisional 1,000 ms
  floor of their own.
- `retainedMemoryV2.calibration.<platform>.growthLimitMBByMode`: the within-mode
  MLX active growth a retained take may add. Null (uncalibrated) until a run
  measures the noise of identical seeded retained takes.

This tool reads one published memory-qualification record (memory contract v2,
so every take carries `samplerMaximumUnobservedGapMS`, `samplerTargetIntervalMS`
and `mlxEndActiveMB`) and prints what it measured and the bounds it proposes:

- Gap: each take's required bound is its longest gap times `--margin`. The
  record's tier comes from its `run.runtimePolicy`. Above the floor tiers (the
  canonical M6), the floor stays the policy's (it keeps a scheduler stall on a
  fast-cadence host from failing a take) and the multiple is the smallest
  quarter step, never below 2, that covers every take whose required bound
  exceeds that floor. On a floor tier (an iPhone or an 8 GB Mac record) the
  tier's floor is the largest required bound rounded up to 50 ms, never below
  the general floor. A forced or emulated tier, or a Mac record without its
  runtime policy, proposes no gap bound: its host is not the tier it names.
- Retained v2, per mode: growth is the policy's own statistic (the highest
  later retained take's end-of-take MLX active memory minus the first's); the
  noise is the spread of those end values. The proposed bound is the growth
  plus three times the noise (at least 1 MB of it), rounded up to 8 MB, never
  below 16 MB.

It only reports unless `--write` is given; then it records the proposals and
the run ID in the policy as calibrated: the general gap bound only from a Mac
above the floor tiers, the floor-tier floor only from an unforced iPhone or
8 GB Mac record. A maintainer runs it after the consented lane and commits the
policy with the record.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "config" / "memory-qualification-policy.json"
DEFAULT_MARGIN = 1.25
MINIMUM_GAP_MULTIPLE = 2.0
GAP_MULTIPLE_STEP = 0.25
FLOOR_TIER_FLOOR_STEP_MS = 50.0
# The gap tier a record calibrates: the general bound or the floor tiers' floor.
GENERAL_GAP_TIER = "general"
FLOOR_GAP_TIER = "floorTiers"
RETAINED_NOISE_MULTIPLE = 3.0
RETAINED_MINIMUM_NOISE_MB = 1.0
RETAINED_ROUNDING_MB = 8.0
RETAINED_MINIMUM_BOUND_MB = 16.0


class CalibrationError(ValueError):
    pass


def _number(value: Any, location: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise CalibrationError(f"{location} must be a finite number")
    return float(value)


def _round_up(value: float, step: float) -> float:
    return math.ceil(value / step - 1e-9) * step


def record_takes(record: dict[str, Any]) -> tuple[str, str, list[dict[str, Any]]]:
    """(platform, run ID, takes) of a contract-v2 memory-qualification record."""
    run = record.get("run") if isinstance(record.get("run"), dict) else {}
    if run.get("kind") != "memory-qualification":
        raise CalibrationError("the record is not a memory-qualification record")
    evidence = record.get("evidence") if isinstance(record.get("evidence"), dict) else {}
    if evidence.get("memoryContractVersion") != 2:
        raise CalibrationError(
            "the record predates memory contract v2: its takes carry no unobserved gap "
            "or end-of-take MLX values"
        )
    platform = run.get("platform")
    run_id = run.get("id")
    takes = record.get("takes")
    if platform not in {"macos", "ios"} or not isinstance(run_id, str) or not isinstance(takes, list) or not takes:
        raise CalibrationError("the record lacks its platform, run ID or takes")
    return platform, run_id, takes


def gap_tier(record: dict[str, Any], platform: str, floor_classes: set[str]) -> tuple[str | None, str]:
    """(tier, why) of the gap bound a record may calibrate; no tier when it may calibrate none.

    The gaps measure the host's scheduler, so only an unforced tier on its own
    hardware calibrates: the floor tiers from an iPhone or an 8 GB Mac, the
    general bound from a Mac above them (the canonical M6)."""
    runtime_policy = (record.get("run") or {}).get("runtimePolicy")
    if not isinstance(runtime_policy, dict):
        return None, "the record names no run.runtimePolicy, so its tier is unknown"
    device_class = runtime_policy.get("deviceClass")
    if runtime_policy.get("deviceClassForced") is not False:
        return None, f"a forced or emulated {device_class} tier is not the hardware it names"
    if platform == "ios" or device_class in floor_classes:
        return FLOOR_GAP_TIER, f"an unforced {device_class} record calibrates the floor tiers"
    return GENERAL_GAP_TIER, f"an unforced {device_class} record calibrates the general bound"


def derive_gap_bound(
    takes: list[dict[str, Any]], *, floor_ms: float, margin: float = DEFAULT_MARGIN,
    tier: str | None = GENERAL_GAP_TIER,
) -> dict[str, Any]:
    ratios: list[float] = []
    gaps: list[float] = []
    covering = MINIMUM_GAP_MULTIPLE
    tier_floor = floor_ms
    for take in takes:
        metrics = take.get("metrics") if isinstance(take.get("metrics"), dict) else {}
        location = f"take {take.get('takeIndex')}"
        gap = _number(metrics.get("samplerMaximumUnobservedGapMS"), f"{location} samplerMaximumUnobservedGapMS")
        cadence = _number(metrics.get("samplerTargetIntervalMS"), f"{location} samplerTargetIntervalMS")
        if cadence <= 0 or gap < 0:
            raise CalibrationError(f"{location} has a non-positive cadence or a negative gap")
        gaps.append(gap)
        ratios.append(gap / cadence)
        required = gap * margin
        if required > floor_ms:
            covering = max(covering, _round_up(required / cadence, GAP_MULTIPLE_STEP))
        tier_floor = max(tier_floor, _round_up(required, FLOOR_TIER_FLOOR_STEP_MS))
    ordered = sorted(ratios)
    proposed: dict[str, float] | None = None
    if tier == GENERAL_GAP_TIER:
        proposed = {"targetIntervalMultiple": covering, "floorMS": floor_ms}
    elif tier == FLOOR_GAP_TIER:
        proposed = {"floorMS": tier_floor}
    return {
        "takeCount": len(takes),
        "maximumGapMS": max(gaps),
        "medianGapToCadence": ordered[(len(ordered) - 1) // 2],
        "maximumGapToCadence": ordered[-1],
        "margin": margin,
        "tier": tier,
        "proposed": proposed,
    }


def derive_retained_bounds(
    takes: list[dict[str, Any]], *, modes: list[str], repetitions: int,
) -> dict[str, Any]:
    by_mode: dict[str, Any] = {}
    for mode in modes:
        ends = [
            _number((take.get("metrics") or {}).get("mlxEndActiveMB"), f"{mode} mlxEndActiveMB")
            for take in takes
            if take.get("mode") == mode and "/retained#" in str(take.get("cell"))
        ]
        if len(ends) != repetitions:
            raise CalibrationError(
                f"mode {mode} has {len(ends)} retained takes with end-of-take MLX values, "
                f"not the policy's {repetitions}"
            )
        growth = max(0.0, max(ends[1:]) - ends[0])
        spread = max(ends) - min(ends)
        noise = max(spread, RETAINED_MINIMUM_NOISE_MB)
        bound = max(
            RETAINED_MINIMUM_BOUND_MB,
            _round_up(growth + RETAINED_NOISE_MULTIPLE * noise, RETAINED_ROUNDING_MB),
        )
        by_mode[mode] = {
            "endActiveMB": ends,
            "growthMB": growth,
            "spreadMB": spread,
            "proposedGrowthLimitMB": bound,
        }
    return by_mode


def derive(record: dict[str, Any], policy: dict[str, Any], *, margin: float = DEFAULT_MARGIN) -> dict[str, Any]:
    platform, run_id, takes = record_takes(record)
    gap_policy = policy.get("unobservedGapBound")
    retained = policy.get("retainedMemoryV2")
    if not isinstance(gap_policy, dict) or not isinstance(retained, dict):
        raise CalibrationError("the policy lacks its unobservedGapBound or retainedMemoryV2 block")
    floor_ms = _number(gap_policy.get("floorMS"), "unobservedGapBound.floorMS")
    floor_tiers = gap_policy.get(FLOOR_GAP_TIER)
    floor_classes = floor_tiers.get("deviceClasses") if isinstance(floor_tiers, dict) else None
    if not isinstance(floor_classes, list) or not all(isinstance(value, str) for value in floor_classes):
        raise CalibrationError("the policy lacks its unobservedGapBound.floorTiers device classes")
    modes = policy.get("modes")
    repetitions = policy.get("repetitionsPerMode")
    if not isinstance(modes, list) or not isinstance(repetitions, int) or repetitions < 2:
        raise CalibrationError("the policy lacks its modes or repetitions")
    classification = (record.get("run") or {}).get("classification")
    tier, why = gap_tier(record, platform, set(floor_classes))
    gap = derive_gap_bound(takes, floor_ms=floor_ms, margin=margin, tier=tier)
    gap["tierReason"] = why
    return {
        "schemaVersion": 1,
        "runID": run_id,
        "platform": platform,
        "classification": classification,
        "unobservedGap": gap,
        "retainedMemoryV2": derive_retained_bounds(takes, modes=modes, repetitions=repetitions),
    }


def apply_to_policy(policy: dict[str, Any], report: dict[str, Any]) -> dict[str, Any]:
    """The policy with the report's proposals recorded as calibrated."""
    if report["classification"] in {"exploratory", "partial"}:
        raise CalibrationError(
            f"a {report['classification']} record cannot calibrate the policy"
        )
    updated = json.loads(json.dumps(policy))
    gap = report["unobservedGap"]
    if gap["tier"] in {GENERAL_GAP_TIER, FLOOR_GAP_TIER}:
        block = updated["unobservedGapBound"]
        if gap["tier"] == FLOOR_GAP_TIER:
            block = block[FLOOR_GAP_TIER]
        block.update(gap["proposed"])
        block["status"] = "calibrated"
        block["calibrationRunID"] = report["runID"]
    entry = updated["retainedMemoryV2"]["calibration"][report["platform"]]
    entry["status"] = "calibrated"
    entry["calibrationRunID"] = report["runID"]
    entry["growthLimitMBByMode"] = {
        mode: values["proposedGrowthLimitMB"]
        for mode, values in report["retainedMemoryV2"].items()
    }
    return updated


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("record", type=Path, help="published memory-qualification record (JSON)")
    parser.add_argument("--policy", type=Path, default=POLICY_PATH)
    parser.add_argument("--margin", type=float, default=DEFAULT_MARGIN,
                        help="headroom over each take's longest gap (default 1.25)")
    parser.add_argument("--write", action="store_true",
                        help="record the proposals in the policy as calibrated")
    args = parser.parse_args(argv)
    if not math.isfinite(args.margin) or args.margin < 1:
        parser.error("--margin must be at least 1")
    try:
        record = json.loads(args.record.read_text(encoding="utf-8"))
        policy = json.loads(args.policy.read_text(encoding="utf-8"))
        report = derive(record, policy, margin=args.margin)
        if args.write:
            args.policy.write_text(
                json.dumps(apply_to_policy(policy, report), indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
    except (OSError, json.JSONDecodeError, CalibrationError, KeyError) as error:
        print(f"memory calibration: {error}", file=sys.stderr)
        return 1
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
