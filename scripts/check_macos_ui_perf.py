#!/usr/bin/env python3
"""macOS UI-perf lane evidence gate and report builder.

Joins the per-scenario wall-clock windows the XCUITest class printed into the
xcodebuild log (``VOCELLO_UIPERF_SCENARIO=<base64>`` lines) against the
in-app frame probe's continuous 500 ms rows
(``diagnostics/ui-perf/frames-<launchEpochMS>-<scenario>.jsonl``), and emits
``ui-perf-report.json`` under the run directory.

Phase-1 posture, deliberate:

* **Local evidence only** (``"evidence": "local-only"``): no benchmark-history
  record is ever written by this lane; registry formalization is a separate
  roadmap item (`prosody-calibration` is the precedent when it happens).
* **No performance thresholds.** The gate is structural: every expected
  scenario present exactly once, probe coverage of each marked window >= the
  floor, monotonic block timestamps, a sane refresh interval. Thresholds are
  set only after repeated baselines establish medians and spread.
* The probe measures main-run-loop display-link cadence — a proxy for
  UI-thread hitching, not compositor-level presents (stated in the report).
"""
from __future__ import annotations

import argparse
import base64
import json
import math
import shutil
import sys
from pathlib import Path

EXPECTED_SCENARIOS = [
    "idle-baseline",
    "sidebar-navigation",
    "history-scroll",
    "history-filter",
    "delivery-menu",
    "settings-scroll",
    "composer-typing",
    "window-resize",
    "generation-active",
]
# The History scenarios are exploratory because a 400-row list under
# XCUITest cannot be measured clean: per-interaction element queries and
# the post-search-clear accessibility maintenance for 400 re-rendered rows
# execute on the app's main thread. A Time Profiler sample over the
# recurring ~3.1 s stall (2026-08-05) attributed it to XCTest query
# servicing, not app frames; with window-anchored coordinate scrolling the
# drain lands deterministically inside history-scroll's window
# (baseline-v2: 456 +/- 3 ms/s), so the number tracks harness+app, never
# the app alone.
EXPLORATORY = {"window-resize", "generation-active", "history-filter", "history-scroll"}
COVERAGE_FLOOR = 0.90
REFRESH_INTERVAL_SANE_MS = (1000.0 / 140.0, 1000.0 / 30.0)
# Gap-histogram bucket upper bounds, in multiples of the refresh interval;
# must match UIPerfFrameProbe's bucketing.
HISTOGRAM_BOUNDS = [1.25, 1.75, 2.75, 4.75, 8.0, 16.0, math.inf]


class GateError(ValueError):
    pass


def parse_markers(log_path: Path) -> dict[str, dict]:
    markers: dict[str, dict] = {}
    for line in log_path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        prefix = "VOCELLO_UIPERF_SCENARIO="
        index = line.find(prefix)
        if index < 0:
            continue
        payload = line[index + len(prefix):].strip()
        try:
            marker = json.loads(base64.b64decode(payload))
        except Exception as error:
            raise GateError(f"unparsable scenario marker line: {error}") from None
        scenario = marker.get("scenario")
        if not scenario:
            raise GateError("scenario marker without a scenario name")
        if scenario in markers:
            raise GateError(f"scenario '{scenario}' emitted more than one marker")
        markers[scenario] = marker
    return markers


def load_probe_rows(path: Path) -> list[dict]:
    rows = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def find_probe_file(ui_perf_dir: Path, scenario: str, run_started_epoch_ms: int) -> Path:
    candidates = []
    for path in sorted(ui_perf_dir.glob(f"frames-*-{scenario}.jsonl")):
        try:
            launch_epoch = int(path.name.split("-")[1])
        except (IndexError, ValueError):
            continue
        if launch_epoch >= run_started_epoch_ms:
            candidates.append(path)
    if not candidates:
        raise GateError(f"scenario '{scenario}': no probe file newer than the run start")
    if len(candidates) > 1:
        raise GateError(
            f"scenario '{scenario}': {len(candidates)} probe files match this run; expected one"
        )
    return candidates[0]


def approximate_p95_gap_ms(histogram: list[int], refresh_ms: float) -> float | None:
    """Histogram-interpolated p95 of frame gaps (upper-bound biased; flagged
    approximate in the report)."""
    total = sum(histogram)
    if total == 0 or refresh_ms <= 0:
        return None
    target = 0.95 * total
    running = 0
    for bucket, count in enumerate(histogram):
        running += count
        if running >= target:
            bound = HISTOGRAM_BOUNDS[bucket]
            if math.isinf(bound):
                bound = 32.0
            return round(bound * refresh_ms, 2)
    return None


def summarize_scenario(marker: dict, rows: list[dict]) -> dict:
    start = int(marker["windowStartEpochMS"])
    end = int(marker["windowEndEpochMS"])
    if end <= start:
        raise GateError(f"scenario '{marker['scenario']}': empty marker window")
    blocks = [r for r in rows if r.get("kind") == "block"]
    previous_end = None
    for block in blocks:
        if previous_end is not None and block["startEpochMS"] < previous_end:
            raise GateError(
                f"scenario '{marker['scenario']}': probe block timestamps not monotonic"
            )
        previous_end = block["endEpochMS"]
    window = [
        b for b in blocks
        if b["endEpochMS"] > start and b["startEpochMS"] < end
    ]
    covered_ms = sum(
        min(int(b["endEpochMS"]), end) - max(int(b["startEpochMS"]), start)
        for b in window
    )
    coverage = covered_ms / (end - start)
    refresh_values = [b["refreshIntervalMS"] for b in window if b.get("refreshIntervalMS")]
    refresh_ms = refresh_values[0] if refresh_values else 0.0
    if refresh_ms and not (
        REFRESH_INTERVAL_SANE_MS[0] <= refresh_ms <= REFRESH_INTERVAL_SANE_MS[1]
    ):
        raise GateError(
            f"scenario '{marker['scenario']}': refresh interval {refresh_ms:.2f} ms "
            "outside the 30-140 Hz sanity band"
        )
    frames = sum(b["framesDelivered"] for b in window)
    expected = sum(b.get("expectedFrames", 0) for b in window)
    excess_ms = sum(b["sumExcessMS"] for b in window)
    max_gap = max((b["maxGapMS"] for b in window), default=0.0)
    histogram = [0] * 7
    for b in window:
        for index, count in enumerate(b.get("gapHistogram", [])):
            histogram[index] += count
    duration_ms = end - start
    cpu_rows = sorted(window, key=lambda b: b["startEpochMS"])
    cpu_user = cpu_rows[-1]["cpuUserMS"] - cpu_rows[0]["cpuUserMS"] if len(cpu_rows) > 1 else 0
    cpu_system = (
        cpu_rows[-1]["cpuSystemMS"] - cpu_rows[0]["cpuSystemMS"] if len(cpu_rows) > 1 else 0
    )
    footprints = [b["footprintMB"] for b in window if b.get("footprintMB")]
    summary_rows = [r for r in rows if r.get("kind") == "summary"]
    stall = summary_rows[0] if summary_rows else {}
    scenario = marker["scenario"]
    return {
        "scenario": scenario,
        "designation": "exploratory" if scenario in EXPLORATORY else "confirmatory",
        "durationMS": duration_ms,
        "probeCoverage": round(coverage, 4),
        "framesDelivered": frames,
        "expectedFrames": expected,
        "hitchTimeMSPerS": round(excess_ms / (duration_ms / 1000.0), 3)
        if duration_ms else None,
        "maxGapMS": round(max_gap, 2),
        "p95GapMSApprox": approximate_p95_gap_ms(histogram, refresh_ms),
        "gapHistogram": histogram,
        "refreshIntervalMS": refresh_ms,
        "cpuUserMS": cpu_user,
        "cpuSystemMS": cpu_system,
        "footprintStartMB": round(footprints[0], 1) if footprints else None,
        "footprintPeakMB": round(max(footprints), 1) if footprints else None,
        "footprintDeltaMB": round(footprints[-1] - footprints[0], 1)
        if len(footprints) > 1 else None,
        "thermalStates": sorted({b.get("thermalState", "unknown") for b in window}),
        # Whole-launch scoped, not window-scoped: the probe's private
        # watchdog runs launch-to-termination.
        "launchStalls50": stall.get("delayedHeartbeatCount50"),
        "launchStalls250": stall.get("delayedHeartbeatCount250"),
        "launchMaxStallMS": stall.get("maximumDelayedHeartbeatMS"),
        "actionCount": marker.get("actionCount"),
    }, coverage


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--xcodebuild-log", required=True)
    parser.add_argument("--diagnostics", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--run-started-epoch-ms", type=int, required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument(
        "--copy-probe-files-to",
        help="directory receiving copies of the matched probe JSONL files",
    )
    args = parser.parse_args()

    ui_perf_dir = Path(args.diagnostics).expanduser() / "ui-perf"
    try:
        markers = parse_markers(Path(args.xcodebuild_log))
        missing = [s for s in EXPECTED_SCENARIOS if s not in markers]
        if missing:
            raise GateError(f"missing scenario markers: {', '.join(missing)}")
        unexpected = [s for s in markers if s not in EXPECTED_SCENARIOS]
        if unexpected:
            raise GateError(f"unexpected scenario markers: {', '.join(unexpected)}")

        scenarios = []
        for name in EXPECTED_SCENARIOS:
            probe_path = find_probe_file(ui_perf_dir, name, args.run_started_epoch_ms)
            rows = load_probe_rows(probe_path)
            env_scenarios = {r.get("scenario") for r in rows}
            if env_scenarios - {name}:
                raise GateError(
                    f"scenario '{name}': probe rows carry mismatched scenario names "
                    f"{sorted(env_scenarios)}"
                )
            summary, coverage = summarize_scenario(markers[name], rows)
            if coverage < COVERAGE_FLOOR:
                raise GateError(
                    f"scenario '{name}': probe coverage {coverage:.0%} below "
                    f"{COVERAGE_FLOOR:.0%} of the marked window"
                )
            summary["probeFile"] = probe_path.name
            scenarios.append(summary)
            if args.copy_probe_files_to:
                destination = Path(args.copy_probe_files_to)
                destination.mkdir(parents=True, exist_ok=True)
                shutil.copy2(probe_path, destination / probe_path.name)
    except GateError as error:
        print(f"ui-perf gate FAILED: {error}", file=sys.stderr)
        return 1

    report = {
        "schemaVersion": 1,
        "evidence": "local-only",
        "runID": args.run_id,
        "measurement": "main-run-loop display-link cadence (UI-thread hitch proxy; "
        "not compositor presents; interaction-issued XCUITest accessibility "
        "queries execute on the app main thread — scenarios minimize them "
        "inside measured windows, and residual query cost marks a scenario "
        "exploratory)",
        "scenarios": scenarios,
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    for row in scenarios:
        print(
            f"  {row['scenario']:20} hitch {row['hitchTimeMSPerS']:>8} ms/s  "
            f"maxGap {row['maxGapMS']:>8} ms  frames {row['framesDelivered']:>6}  "
            f"coverage {row['probeCoverage']:.0%}  [{row['designation']}]"
        )
    print(f"ui-perf gate PASS: {len(scenarios)} scenarios -> {output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
