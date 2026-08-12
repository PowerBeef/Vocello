#!/usr/bin/env python3
"""iOS UI-perf lane evidence gate and report builder (IUI-1).

Joins the per-scenario wall-clock windows the physical-iPhone XCUITest class
printed into the xcodebuild log (``VOCELLO_UIPERF_SCENARIO=<base64>`` lines;
timestamps come from the on-device test runner, so markers and probe rows
share the device clock) against the in-app frame probe's continuous 500 ms
rows pulled from the device
(``<diagnostics>/ui-perf/frames-<launchEpochMS>-<scenario>.jsonl``), and
emits ``ui-perf-report.json`` under the run directory.

IUI-1 posture (mirrors the macOS UI-7 checker, with iOS deltas):

* **The gate stays structural**: every expected scenario present exactly
  once, probe coverage of each marked window >= the floor, monotonic block
  timestamps, a sane refresh interval.
* **Cadence band is fail-closed on the quiet sentinel only**: the probe pins
  its ``CADisplayLink`` to the app's 60 Hz cap, and on ``ios-idle-baseline``
  — no interaction, no engine load — a median block cadence outside 55-65 Hz
  can only mean the system ignored the pin (Low Power Mode, thermal caps,
  idle throttling), so the gate refuses the run instead of publishing a lie.
  Low Power Mode off and nominal thermals are run preconditions. On
  interactive scenarios block cadence conflates system re-pacing with the
  main-thread stalls this lane exists to measure (CADisplayLink coalesces
  missed callbacks; the macOS history-scroll baseline of 456 ms/s hitch is
  ~33 Hz effective cadence), so an out-of-band cadence there is recorded as
  a ``uiperf.cadence:*`` warning and marks the run ``passedWithWarnings``,
  never failed.
* **Canonical hardware is proven, not assumed** (``--require-canonical``):
  the run-scoped device manifest (written because the test launches the app
  with ``QVOICE_IOS_DEVICE_RUN_ID``) plus a live ``devicectl`` inventory must
  resolve to the canonical iPhone profile via
  ``publish_benchmark_history.verify_canonical_hardware("ios", ...)``.
* **No thresholds contract yet**: warn-only ceilings are an IUI-6 decision
  after repeated counted baselines; ``--thresholds`` is optional and absent
  by default.
* **No registry publication yet**: platform-aware ``ui-perf`` records are
  IUI-6; this checker never writes ``benchmark-evidence.json``.
* The probe measures main-run-loop display-link cadence — a proxy for
  UI-thread hitching, not render-server presents (stated in the report).
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import math
import shutil
import statistics
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

EXPECTED_SCENARIOS = [
    "ios-idle-baseline",
    "ios-tab-navigation",
    "ios-history-scroll",
    "ios-voices-scroll",
    "ios-settings-scroll",
    "ios-composer-typing",
    "ios-sheet-present-dismiss",
    "ios-player-scrub",
    "ios-generation-active",
]
# Player scrub drags an element-anchored coordinate through a custom
# DragGesture surface (per-event accessibility re-query executes on the
# app's main thread — the macOS history-scroll lesson), and generation
# duration is model-dependent; both are exploratory by design.
EXPLORATORY = {"ios-player-scrub", "ios-generation-active"}
COVERAGE_FLOOR = 0.90
REFRESH_INTERVAL_SANE_MS = (1000.0 / 140.0, 1000.0 / 30.0)
# Observed-cadence band around the probe's pinned 60 Hz link. Fail-closed on
# the idle sentinel, warn-only elsewhere (see the module docstring).
CADENCE_BAND_HZ = (55.0, 65.0)
CADENCE_GATED_SCENARIO = "ios-idle-baseline"
# Gap-histogram bucket upper bounds, in multiples of the refresh interval;
# must match IOSUIPerfFrameProbe's bucketing.
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
        # launch_epoch is device-clock, run start is host-clock; the minutes
        # of build/install between them dwarf ordinary NTP skew.
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


def median_block_cadence_hz(window: list[dict]) -> float | None:
    cadences = []
    for block in window:
        duration_ms = int(block["endEpochMS"]) - int(block["startEpochMS"])
        if duration_ms <= 0:
            continue
        cadences.append(block["framesDelivered"] * 1000.0 / duration_ms)
    if not cadences:
        return None
    return round(statistics.median(cadences), 2)


def summarize_scenario(marker: dict, rows: list[dict]) -> tuple[dict, float]:
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
    cadence = median_block_cadence_hz(window)
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
        "medianBlockCadenceHz": cadence,
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


def evaluate_cadence(summary: dict) -> list[str]:
    """Idle-anchored honesty gate. On the quiet sentinel an out-of-band
    median cadence can only mean the pinned link was not honored — refuse
    the run. On interactive scenarios cadence conflates system re-pacing
    with the main-thread stalls the lane measures, so it degrades to a
    warn-only code instead of discarding a complete device run."""
    scenario = summary["scenario"]
    cadence = summary["medianBlockCadenceHz"]
    if cadence is None or CADENCE_BAND_HZ[0] <= cadence <= CADENCE_BAND_HZ[1]:
        return []
    if scenario == CADENCE_GATED_SCENARIO:
        raise GateError(
            f"scenario '{scenario}': median block cadence {cadence:.1f} Hz "
            f"outside the {CADENCE_BAND_HZ[0]:.0f}-{CADENCE_BAND_HZ[1]:.0f} Hz band "
            "on the idle sentinel (the pinned 60 Hz display link was not "
            "honored — check Low Power Mode and thermals)"
        )
    return [
        f"uiperf.cadence:{scenario}"
        f"({round(cadence)}/{CADENCE_BAND_HZ[0]:.0f}-{CADENCE_BAND_HZ[1]:.0f})"
    ]


def load_thresholds(path: Path) -> dict:
    thresholds = json.loads(path.read_text(encoding="utf-8"))
    if thresholds.get("schemaVersion") != 1 or thresholds.get("warnOnly") is not True:
        raise GateError(f"unsupported thresholds contract: {path}")
    return thresholds


def evaluate_thresholds(summary: dict, thresholds: dict | None) -> list[str]:
    """Warn-only ceilings: a breach never fails the gate; it marks the
    scenario and run passedWithWarnings. No iOS ceiling contract exists yet
    (IUI-6 derives one from repeated counted baselines), so this is inert
    until --thresholds is supplied."""
    if thresholds is None:
        return []
    scenario = summary["scenario"]
    warnings = []
    hitch_ceiling = thresholds["hitchCeilingMSPerS"].get(scenario)
    if hitch_ceiling is not None and summary["hitchTimeMSPerS"] > hitch_ceiling:
        warnings.append(
            f"uiperf.hitch:{scenario}"
            f"({round(summary['hitchTimeMSPerS'])}/{round(hitch_ceiling)})"
        )
    gap_ceiling = thresholds["maxGapCeilingMS"].get(scenario)
    if gap_ceiling is not None and summary["maxGapMS"] > gap_ceiling:
        warnings.append(
            f"uiperf.maxgap:{scenario}"
            f"({round(summary['maxGapMS'])}/{round(gap_ceiling)})"
        )
    return warnings


def verify_canonical_iphone(diagnostics: Path, run_id: str) -> str:
    """Prove the pulled run manifest + the live paired device resolve to the
    canonical iPhone profile. Returns the profile ID; raises GateError."""
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    import publish_benchmark_history as publisher
    try:
        evidence = publisher.ios_run_hardware_evidence(diagnostics, run_id)
        return publisher.verify_canonical_hardware("ios", ios_evidence=evidence)["profileID"]
    except publisher.PublicationError as error:
        raise GateError(f"canonical iPhone verification failed: {error}") from None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--xcodebuild-log", required=True)
    parser.add_argument("--diagnostics", required=True,
                        help="pulled device diagnostics root (contains ui-perf/ "
                        "and <runID>/manifest.json)")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--run-started-epoch-ms", type=int, required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument(
        "--copy-probe-files-to",
        help="directory receiving copies of the matched probe JSONL files",
    )
    parser.add_argument(
        "--thresholds", type=Path, default=None,
        help="optional warn-only ceiling contract (none exists for iOS yet; "
        "IUI-6 derives one from repeated counted baselines)",
    )
    parser.add_argument("--label", default="")
    parser.add_argument(
        "--require-canonical", action="store_true",
        help="fail closed unless the pulled run manifest and the live paired "
        "device resolve to the canonical iPhone hardware profile",
    )
    args = parser.parse_args()

    diagnostics = Path(args.diagnostics).expanduser()
    ui_perf_dir = diagnostics / "ui-perf"
    profile_id = None
    try:
        thresholds = load_thresholds(args.thresholds) if args.thresholds else None
        if args.require_canonical:
            profile_id = verify_canonical_iphone(diagnostics, args.run_id)
        markers = parse_markers(Path(args.xcodebuild_log))
        missing = [s for s in EXPECTED_SCENARIOS if s not in markers]
        if missing:
            raise GateError(f"missing scenario markers: {', '.join(missing)}")
        unexpected = [s for s in markers if s not in EXPECTED_SCENARIOS]
        if unexpected:
            raise GateError(f"unexpected scenario markers: {', '.join(unexpected)}")

        scenarios = []
        scenario_warnings: dict[str, list[str]] = {}
        probe_hash = hashlib.sha256()
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
            warnings = evaluate_cadence(summary) + evaluate_thresholds(summary, thresholds)
            summary["thresholdWarnings"] = warnings
            scenario_warnings[name] = warnings
            scenarios.append(summary)
            probe_hash.update(probe_path.read_bytes())
            if args.copy_probe_files_to:
                destination = Path(args.copy_probe_files_to)
                destination.mkdir(parents=True, exist_ok=True)
                shutil.copy2(probe_path, destination / probe_path.name)
    except GateError as error:
        print(f"ios ui-perf gate FAILED: {error}", file=sys.stderr)
        return 1

    run_warnings = sorted({code for codes in scenario_warnings.values() for code in codes})
    report = {
        "schemaVersion": 1,
        "platform": "ios",
        "evidence": "local-only",
        "runID": args.run_id,
        "label": args.label or args.run_id,
        "status": "passedWithWarnings" if run_warnings else "passed",
        "hardwareProfileID": profile_id,
        "probeDigest": probe_hash.hexdigest(),
        "thresholds": {
            "path": str(args.thresholds) if args.thresholds else None,
            "warnOnly": True,
            "warnings": run_warnings,
        },
        "measurement": "main-run-loop CADisplayLink cadence pinned to the app's "
        "60 Hz cap (UI-thread hitch proxy; not render-server presents; "
        "interaction-issued XCUITest accessibility queries execute on the app "
        "main thread — scenarios minimize them inside measured windows, and "
        "residual query cost marks a scenario exploratory)",
        "scenarios": scenarios,
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    for row in scenarios:
        flag = " !" + ",".join(row["thresholdWarnings"]) if row["thresholdWarnings"] else ""
        print(
            f"  {row['scenario']:26} hitch {row['hitchTimeMSPerS']:>8} ms/s  "
            f"maxGap {row['maxGapMS']:>8} ms  cadence {row['medianBlockCadenceHz']:>6} Hz  "
            f"coverage {row['probeCoverage']:.0%}  [{row['designation']}]{flag}"
        )

    print(f"ios ui-perf gate PASS: {len(scenarios)} scenarios -> {output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
