#!/usr/bin/env python3
"""macOS UI-perf lane evidence gate and report builder.

Joins the per-scenario wall-clock windows the XCUITest class printed into the
xcodebuild log (``VOCELLO_UIPERF_SCENARIO=<base64>`` lines) against the
in-app frame probe's continuous 500 ms rows
(``diagnostics/ui-perf/frames-<launchEpochMS>-<scenario>.jsonl``), and emits
``ui-perf-report.json`` under the run directory.

Phase-2 posture (UI-7, 2026-08-05):

* **The gate stays structural**: every expected scenario present exactly
  once, probe coverage of each marked window >= the floor, monotonic block
  timestamps, a sane refresh interval.
* **Thresholds are warn-only** (``config/ui-perf-thresholds.json``): a ceiling
  breach marks the scenario and run ``passedWithWarnings`` and never fails the
  gate or blocks publication. Promotion to hard ceilings waits for repeated
  baseline sessions. The contract names the profile and refresh interval it was
  derived on; on any other, the run carries one ``uiperf.uncalibrated:<profile>``
  code instead of ceiling verdicts (audit #77). ``--derive-thresholds RECORD...``
  derives a contract from at least three counted runs (``scripts/lib/
  ui_perf_thresholds.py``: the run-to-run spread with a 1.3x floor, audit #34).
* A confirmatory scenario whose window grows the footprint past
  ``footprintGrowthCeilingMB`` gets a warn-only ``uiperf.footprint`` code (#33).
* **Registry publication** (``--emit-evidence``): on the canonical hardware
  profile the checker writes ``benchmark-evidence.json`` for
  ``benchmark_history.py record`` (kind ``ui-perf``, one take per scenario,
  no model/telemetry/QC claims — the ``prosody-calibration`` precedent).
  Non-canonical hosts keep local-only reports; a dirty or late publication
  classifies ``exploratory`` via the standard source provenance.
* The probe measures main-run-loop display-link cadence — a proxy for
  UI-thread hitching, not compositor-level presents (stated in the report).
* harness-control (exploratory, audit #32) makes sidebar-navigation's readiness
  queries with no click, so its hitch time is the harness's accessibility cost;
  markers may name phases (`query`, `action`, `verify`) whose hitch rates the
  report lists per scenario. sidebar-navigation runs with proactive warms
  suppressed, sidebar-navigation-warms (exploratory) with them on (audit #33).
* The report's `lanePhases` names where lane time went: each scenario's launch,
  settle, setup and window from its `VOCELLO_UIPERF_SETUP=` stamps, and the
  required-step ledger's step durations (audit #82).
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import math
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_THRESHOLDS_PATH = REPO_ROOT / "config" / "ui-perf-thresholds.json"
UI_PERF_RUNS = REPO_ROOT / "benchmarks" / "runs" / "ui-perf"
if str(REPO_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
from lib import ui_perf_thresholds as calibration_rules  # noqa: E402
from lib import ui_perf_lane  # noqa: E402

EXPECTED_SCENARIOS = [
    "idle-baseline",
    "sidebar-navigation",
    "harness-control",
    "history-scroll",
    "history-filter",
    "delivery-menu",
    "settings-scroll",
    "composer-typing",
    "window-resize",
    "sidebar-navigation-warms",
    "generation-active",
]
# The named spans a marker may carry inside its window (audit #32).
PHASE_NAMES = frozenset({"query", "action", "verify"})
# The History scenarios are exploratory because a 400-row list under
# XCUITest cannot be measured clean: per-interaction element queries and
# the post-search-clear accessibility maintenance for 400 re-rendered rows
# execute on the app's main thread. A Time Profiler sample over the
# recurring ~3.1 s stall (2026-08-05) attributed it to XCTest query
# servicing, not app frames; with window-anchored coordinate scrolling the
# drain lands deterministically inside history-scroll's window
# (baseline-v2: 456 +/- 3 ms/s), so the number tracks harness+app, never
# the app alone.
# The confirmatory/exploratory designation lives in the thresholds contract
# (`confirmatoryScenarios`); `exploratory_scenarios()` derives the rest so the
# checker and the config cannot disagree.
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


def exploratory_scenarios(thresholds: dict) -> set[str]:
    return set(EXPECTED_SCENARIOS) - set(thresholds["confirmatoryScenarios"])


def overlap_fraction(block: dict, start: int, end: int) -> float:
    span = int(block["endEpochMS"]) - int(block["startEpochMS"])
    if span <= 0:
        return 0.0
    overlap = min(int(block["endEpochMS"]), end) - max(int(block["startEpochMS"]), start)
    return max(0.0, min(1.0, overlap / span))


def span_hitch(blocks: list[dict], start: int, end: int) -> tuple[float, int]:
    """(in-span excess frame time, covered ms) of one span, apportioned like a window."""
    touching = [b for b in blocks if b["endEpochMS"] > start and b["startEpochMS"] < end]
    covered = sum(min(int(b["endEpochMS"]), end) - max(int(b["startEpochMS"]), start) for b in touching)
    excess = sum(b["sumExcessMS"] * overlap_fraction(b, start, end) for b in touching)
    return excess, covered


def phase_hitch_rates(marker: dict, blocks: list[dict]) -> dict | None:
    """Per phase name, the phases' total duration and hitch rate (audit #32).

    Optional marker field `phases`: [{name, startEpochMS, endEpochMS}, ...],
    ordered, disjoint (a phase may start where the previous ended) and inside
    the window. Report-only: no record metric or ceiling reads it."""
    phases = marker.get("phases")
    if phases is None:
        return None
    scenario = marker["scenario"]
    start, end = int(marker["windowStartEpochMS"]), int(marker["windowEndEpochMS"])
    if not isinstance(phases, list) or not phases:
        raise GateError(f"scenario '{scenario}': phases must be a non-empty list")
    totals: dict[str, dict[str, float]] = {}
    previous_end = start
    for phase in phases:
        try:
            name = phase["name"]
            phase_start, phase_end = int(phase["startEpochMS"]), int(phase["endEpochMS"])
        except (KeyError, TypeError, ValueError):
            raise GateError(f"scenario '{scenario}': malformed phase marker") from None
        if name not in PHASE_NAMES:
            raise GateError(f"scenario '{scenario}': unknown phase {name!r}")
        if not previous_end <= phase_start <= phase_end <= end:
            raise GateError(f"scenario '{scenario}': phases must be ordered, disjoint and inside the window")
        previous_end = phase_end
        excess, covered = span_hitch(blocks, phase_start, phase_end)
        entry = totals.setdefault(name, {"durationMS": 0.0, "excessMS": 0.0, "coveredMS": 0.0})
        entry["durationMS"] += phase_end - phase_start
        entry["excessMS"] += excess
        entry["coveredMS"] += covered
    return {
        name: {
            "durationMS": int(entry["durationMS"]),
            "hitchTimeMSPerS": round(entry["excessMS"] / (entry["coveredMS"] / 1000.0), 3)
            if entry["coveredMS"] > 0 else None,
        }
        for name, entry in sorted(totals.items())
    }


def cycle_hitch_rates(marker: dict, blocks: list[dict]) -> list[float] | None:
    """Per-cycle hitch time for a scenario that marks its repeated cycles (audit #34(b)).

    Optional marker field `cycles`: [{startEpochMS, endEpochMS}, ...], ordered,
    non-overlapping and inside the scenario window. Each cycle is apportioned
    exactly like the window, so the rates are within-run samples of the same
    statistic. Markers without cycles (every record before this) return None.
    """
    cycles = marker.get("cycles")
    if cycles is None:
        return None
    scenario = marker["scenario"]
    start, end = int(marker["windowStartEpochMS"]), int(marker["windowEndEpochMS"])
    if not isinstance(cycles, list) or not cycles:
        raise GateError(f"scenario '{scenario}': cycles must be a non-empty list")
    rates = []
    previous_end = start
    for cycle in cycles:
        try:
            cycle_start, cycle_end = int(cycle["startEpochMS"]), int(cycle["endEpochMS"])
        except (KeyError, TypeError, ValueError):
            raise GateError(f"scenario '{scenario}': malformed cycle marker") from None
        if not previous_end <= cycle_start < cycle_end <= end:
            raise GateError(f"scenario '{scenario}': cycles must be ordered, disjoint and inside the window")
        previous_end = cycle_end
        touching = [b for b in blocks if b["endEpochMS"] > cycle_start and b["startEpochMS"] < cycle_end]
        covered = sum(
            min(int(b["endEpochMS"]), cycle_end) - max(int(b["startEpochMS"]), cycle_start) for b in touching
        )
        excess = sum(b["sumExcessMS"] * overlap_fraction(b, cycle_start, cycle_end) for b in touching)
        rates.append(round(excess / (covered / 1000.0), 3) if covered > 0 else 0.0)
    return rates


def summarize_scenario(marker: dict, rows: list[dict], *, exploratory: set[str]) -> dict:
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
    # A probe block that straddles the window edge contributes only its
    # in-window fraction to every additive quantity, and the denominator is
    # the covered span, so a 500 ms block outside the window can neither
    # inflate nor dilute the scenario. maxGapMS stays unclipped: a gap cannot
    # be apportioned, so it is the worst gap of any block touching the window.
    fractions = {id(b): overlap_fraction(b, start, end) for b in window}
    covered_ms = sum(
        min(int(b["endEpochMS"]), end) - max(int(b["startEpochMS"]), start)
        for b in window
    )
    coverage = covered_ms / (end - start)
    refresh_values = [b["refreshIntervalMS"] for b in window if b.get("refreshIntervalMS")]
    if not refresh_values:
        raise GateError(
            f"scenario '{marker['scenario']}': no probe block reports a refresh interval "
            "(the display link never delivered a positive frame duration)"
        )
    refresh_ms = refresh_values[0]
    if not (REFRESH_INTERVAL_SANE_MS[0] <= refresh_ms <= REFRESH_INTERVAL_SANE_MS[1]):
        raise GateError(
            f"scenario '{marker['scenario']}': refresh interval {refresh_ms:.2f} ms "
            "outside the 30-140 Hz sanity band"
        )
    frames = int(round(sum(b["framesDelivered"] * fractions[id(b)] for b in window)))
    expected = int(round(sum(b.get("expectedFrames", 0) * fractions[id(b)] for b in window)))
    excess_ms = sum(b["sumExcessMS"] * fractions[id(b)] for b in window)
    max_gap = max((b["maxGapMS"] for b in window), default=0.0)
    histogram_raw = [0.0] * 7
    for b in window:
        for index, count in enumerate(b.get("gapHistogram", [])):
            histogram_raw[index] += count * fractions[id(b)]
    histogram = [int(round(value)) for value in histogram_raw]
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
    action_count = marker.get("actionCount")
    cycle_rates = cycle_hitch_rates(marker, blocks)
    phase_rates = phase_hitch_rates(marker, blocks)
    return {
        "scenario": scenario,
        "designation": "exploratory" if scenario in exploratory else "confirmatory",
        "durationMS": duration_ms,
        "probeCoverage": round(coverage, 4),
        "framesDelivered": frames,
        "expectedFrames": expected,
        "hitchTimeMSPerS": round(excess_ms / (covered_ms / 1000.0), 3)
        if covered_ms else None,
        # In-window excess frame time per scripted action (audit #79): unlike
        # ms/s, harness pacing between actions cannot dilute it.
        "hitchMSPerAction": round(excess_ms / action_count, 3)
        if isinstance(action_count, int) and action_count > 0 else None,
        **({"cycleHitchTimeMSPerS": cycle_rates} if cycle_rates is not None else {}),
        # Report-only per-phase hitch (audit #32): how much fell while the
        # harness queried, acted or verified.
        **({"phases": phase_rates} if phase_rates is not None else {}),
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
        # watchdog runs launch-to-termination (and its summary is written only
        # when the probe finishes, which the test driver's terminate skips).
        # Report-only: never published under the generation-scoped names.
        "launchStalls50": stall.get("delayedHeartbeatCount50"),
        "launchStalls250": stall.get("delayedHeartbeatCount250"),
        "launchMaxStallMS": stall.get("maximumDelayedHeartbeatMS"),
        "actionCount": action_count,
    }, coverage


def load_thresholds(path: Path) -> dict:
    thresholds = json.loads(path.read_text(encoding="utf-8"))
    if thresholds.get("schemaVersion") != 1 or thresholds.get("warnOnly") is not True:
        raise GateError(f"unsupported thresholds contract: {path}")
    confirmatory = thresholds.get("confirmatoryScenarios")
    if not isinstance(confirmatory, list) or not set(confirmatory) <= set(EXPECTED_SCENARIOS):
        raise GateError(f"thresholds contract names unknown confirmatory scenarios: {path}")
    for key in ("hitchCeilingMSPerS", "maxGapCeilingMS"):
        if set(thresholds.get(key, {})) != set(confirmatory):
            raise GateError(f"thresholds contract {key} must cover exactly the confirmatory scenarios: {path}")
    if problems := calibration_rules.validate_calibration_fields(thresholds):
        raise GateError(f"thresholds contract {'; '.join(problems)}: {path}")
    return thresholds


THERMAL_RANK = {"nominal": 0, "fair": 1, "serious": 2, "critical": 3}


def run_hardware_context(
    environment_rows: list[dict], scenarios: list[dict], profile_id: str
) -> dict:
    """Host-truth runtime context for the registry record, from the probes'
    one-per-launch environment snapshots (mirrors the iOS lane). Fail-closed:
    a probe without the snapshot predates this checker."""
    if not environment_rows:
        raise GateError(
            "probe files carry no environment snapshot; the built app predates "
            "the environment-aware probe (probe and checker move together)"
        )
    hardware: dict = {"profileID": profile_id}
    loads = [r["loadAverage1Minute"] for r in environment_rows
             if isinstance(r.get("loadAverage1Minute"), (int, float))]
    free = [r["freeStorageBytes"] for r in environment_rows if isinstance(r.get("freeStorageBytes"), int)]
    uptime = [r["uptimeSeconds"] for r in environment_rows
              if isinstance(r.get("uptimeSeconds"), (int, float))]
    low_power = [r["lowPowerModeEnabled"] for r in environment_rows
                 if isinstance(r.get("lowPowerModeEnabled"), bool)]
    if loads: hardware["loadAverage1M"] = max(loads)
    if free: hardware["freeStorageBytes"] = min(free)
    if uptime: hardware["uptimeSeconds"] = min(uptime)
    if low_power: hardware["lowPowerMode"] = any(low_power)
    thermal = [str(r.get("thermalState", "")).lower() for r in environment_rows] + [
        state for summary in scenarios for state in summary.get("thermalStates", [])
    ]
    known = [state for state in thermal if state in THERMAL_RANK]
    if known:
        hardware["thermalState"] = max(known, key=THERMAL_RANK.get)
    return hardware


def evaluate_thresholds(summary: dict, thresholds: dict) -> list[str]:
    """Warn-only ceilings (UI-7): a breach never fails the gate; it marks the
    scenario and run passedWithWarnings so the registry shows the drift."""
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


# The scenario that runs a real take, with the memory samplers alongside.
GENERATION_SCENARIO = "generation-active"


def sampler_interval(rows: list[dict]) -> dict:
    """The telemetry sampler cadence the scenario's launch ran (audit #33), when
    its probe's environment row names one; probes before 2026-09-25 do not."""
    values = {
        row["telemetrySamplerIntervalMS"] for row in rows
        if row.get("kind") == "environment"
        and isinstance(row.get("telemetrySamplerIntervalMS"), (int, float))
        and not isinstance(row.get("telemetrySamplerIntervalMS"), bool)
    }
    if len(values) != 1:
        return {}
    return {"samplerIntervalMS": values.pop()}


def take_metrics(summary: dict) -> dict:
    metrics = {
        "uiHitchTimeMSPerS": summary["hitchTimeMSPerS"],
        "uiMaxGapMS": summary["maxGapMS"],
        "uiFramesDelivered": summary["framesDelivered"],
        "uiExpectedFrames": summary["expectedFrames"],
        "uiProbeCoverage": summary["probeCoverage"],
        "uiRefreshIntervalMS": summary["refreshIntervalMS"],
        "uiWindowDurationMS": summary["durationMS"],
        "uiActionCount": summary["actionCount"],
        "cpuUserSeconds": round(summary["cpuUserMS"] / 1000.0, 3),
        "cpuSystemSeconds": round(summary["cpuSystemMS"] / 1000.0, 3),
    }
    # The probe watchdog's launch-scoped summary is not mapped onto the
    # generation-scoped heartbeat metrics (audit #80).
    optional = {
        "uiHitchMSPerAction": summary.get("hitchMSPerAction"),
        "uiP95GapMSApprox": summary.get("p95GapMSApprox"),
        "physicalFootprintStartMB": summary.get("footprintStartMB"),
        "peakPhysicalFootprintMB": summary.get("footprintPeakMB"),
        "physicalFootprintDeltaMB": summary.get("footprintDeltaMB"),
        # generation-active only: the memory samplers' cadence during its take.
        "samplerTargetIntervalMS": summary.get("samplerIntervalMS"),
    }
    metrics.update({key: value for key, value in optional.items() if value is not None})
    return metrics


def build_evidence_manifest(
    run_id: str,
    label: str,
    scenarios: list[dict],
    scenario_warnings: dict[str, list[str]],
    probe_digest: str,
    profile_id: str,
    hardware: dict | None = None,
    run_warnings: list[str] | None = None,
) -> dict:
    """`run_warnings` carries run-level codes such as `uiperf.uncalibrated:<profile>`."""
    takes = []
    for index, summary in enumerate(scenarios, start=1):
        scenario = summary["scenario"]
        warnings = scenario_warnings.get(scenario, [])
        takes.append({
            "takeIndex": index,
            "generationID": f"{run_id}-{scenario}",
            "cell": f"ui-perf/{scenario}",
            "mode": "not-applicable",
            "modelID": "not-applicable",
            "variant": "not-applicable",
            "warmState": "not-applicable",
            "length": "not-applicable",
            "finishReason": "completed",
            "status": "passedWithWarnings" if warnings else "passed",
            "thermalState": (summary.get("thermalStates") or ["unknown"])[-1],
            "metrics": take_metrics(summary),
            "warnings": warnings,
        })
    run_warnings = sorted(
        {code for codes in scenario_warnings.values() for code in codes} | set(run_warnings or [])
    )
    status = "passedWithWarnings" if run_warnings else "passed"
    return {
        "schemaVersion": 1,
        "benchmarkKind": "ui-perf",
        "platform": "macos",
        "runID": run_id,
        "status": status,
        "label": label or run_id,
        "historyRecord": {
            "run": {
                "id": run_id,
                "kind": "ui-perf",
                "platform": "macos",
                "status": status,
                "label": label or run_id,
                "matrixScope": "canonical",
                "warnings": run_warnings,
            },
            "hardware": {**(hardware or {}), "profileID": profile_id},
            "models": [],
            "evidence": {
                "validatorPassed": True,
                "crashDeltaPassed": True,
                "crashCount": 0,
                "expectedTakeCount": len(EXPECTED_SCENARIOS),
                "actualTakeCount": len(takes),
                "telemetrySchemaVersion": "not-applicable",
                "qcAlgorithmVersion": "not-applicable",
                "rawTelemetryDigest": probe_digest,
            },
            "takes": takes,
        },
    }


def canonical_profile_id(platform: str = "macos") -> str:
    """The registry's canonical profile (a registry lookup, no live probe)."""
    import publish_benchmark_history as publisher

    return str(publisher.canonical_hardware_profile(platform)["id"])


def main() -> int:
    if "--derive-thresholds" in sys.argv[1:]:
        return calibration_rules.derive_main(
            sys.argv[1:], platform="macos", default_thresholds=DEFAULT_THRESHOLDS_PATH,
            load_thresholds=load_thresholds, runs_root=UI_PERF_RUNS,
        )
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
    parser.add_argument(
        "--thresholds", type=Path, default=DEFAULT_THRESHOLDS_PATH,
        help="warn-only ceiling contract (config/ui-perf-thresholds.json)",
    )
    parser.add_argument("--label", default="")
    parser.add_argument(
        "--step-ledger", type=Path, default=None,
        help="the lane's required-steps.json; its step durations join the report's lanePhases (audit #82)",
    )
    parser.add_argument(
        "--emit-evidence", action="store_true",
        help="write benchmark-evidence.json beside the report when the live "
        "host matches the canonical hardware profile (registry publication "
        "input; skipped with a note on non-canonical hardware)",
    )
    args = parser.parse_args()

    ui_perf_dir = Path(args.diagnostics).expanduser() / "ui-perf"
    try:
        thresholds = load_thresholds(args.thresholds)
        markers = parse_markers(Path(args.xcodebuild_log))
        missing = [s for s in EXPECTED_SCENARIOS if s not in markers]
        if missing:
            raise GateError(f"missing scenario markers: {', '.join(missing)}")
        unexpected = [s for s in markers if s not in EXPECTED_SCENARIOS]
        if unexpected:
            raise GateError(f"unexpected scenario markers: {', '.join(unexpected)}")

        exploratory = exploratory_scenarios(thresholds)
        scenarios = []
        environment_rows: list[dict] = []
        probe_hash = hashlib.sha256()
        for name in EXPECTED_SCENARIOS:
            probe_path = find_probe_file(ui_perf_dir, name, args.run_started_epoch_ms)
            rows = load_probe_rows(probe_path)
            environment_rows += [r for r in rows if r.get("kind") == "environment"]
            env_scenarios = {r.get("scenario") for r in rows}
            if env_scenarios - {name}:
                raise GateError(
                    f"scenario '{name}': probe rows carry mismatched scenario names "
                    f"{sorted(env_scenarios)}"
                )
            summary, coverage = summarize_scenario(markers[name], rows, exploratory=exploratory)
            if name == GENERATION_SCENARIO:
                summary.update(sampler_interval(rows))
            if coverage < COVERAGE_FLOOR:
                raise GateError(
                    f"scenario '{name}': probe coverage {coverage:.0%} below "
                    f"{COVERAGE_FLOOR:.0%} of the marked window"
                )
            summary["probeFile"] = probe_path.name
            scenarios.append(summary)
            probe_hash.update(probe_path.read_bytes())
            if args.copy_probe_files_to:
                destination = Path(args.copy_probe_files_to)
                destination.mkdir(parents=True, exist_ok=True)
                shutil.copy2(probe_path, destination / probe_path.name)
        hardware_context = run_hardware_context(environment_rows, scenarios, "pending")
        phases = ui_perf_lane.lane_phases(
            ui_perf_lane.parse_setup_markers(Path(args.xcodebuild_log)),
            ui_perf_lane.load_ledger(args.step_ledger), EXPECTED_SCENARIOS,
        )
    except GateError as error:
        print(f"ui-perf gate FAILED: {error}", file=sys.stderr)
        return 1

    # The ceilings apply only on the profile and refresh interval they were
    # derived on; anywhere else the run says so once instead (audit #77).
    calibration = calibration_rules.calibration(
        thresholds, canonical_profile_id(), [row["refreshIntervalMS"] for row in scenarios],
    )
    scenario_warnings: dict[str, list[str]] = {}
    for summary in scenarios:
        warnings = evaluate_thresholds(summary, thresholds) if calibration["calibrated"] else []
        warnings += calibration_rules.footprint_growth_warning(summary, thresholds)
        summary["thresholdWarnings"] = warnings
        scenario_warnings[summary["scenario"]] = warnings
    extra_run_warnings = [calibration["code"]] if calibration["code"] else []
    run_warnings = sorted(
        {code for codes in scenario_warnings.values() for code in codes} | set(extra_run_warnings)
    )
    report = {
        "schemaVersion": 1,
        "evidence": "registry" if args.emit_evidence else "local-only",
        "hardwareContext": {k: v for k, v in hardware_context.items() if k != "profileID"},
        "runID": args.run_id,
        "status": "passedWithWarnings" if run_warnings else "passed",
        "thresholds": {
            "path": str(args.thresholds), "warnOnly": True, "warnings": run_warnings,
            "calibrated": calibration["calibrated"],
            "calibrationProfile": calibration["calibrationProfile"],
            "calibrationRefreshIntervalMS": calibration["calibrationRefreshIntervalMS"],
            "uncalibratedReasons": calibration["reasons"],
        },
        "measurement": "main-run-loop display-link cadence (UI-thread hitch proxy; "
        "not compositor presents; interaction-issued XCUITest accessibility "
        "queries execute on the app main thread — scenarios minimize them "
        "inside measured windows, and residual query cost marks a scenario "
        "exploratory)",
        "scenarios": scenarios,
        "lanePhases": phases,
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if not calibration["calibrated"]:
        print(f"  ceilings not applied ({calibration['code']}): {'; '.join(calibration['reasons'])}")
    for row in scenarios:
        flag = " !" + ",".join(row["thresholdWarnings"]) if row["thresholdWarnings"] else ""
        print(
            f"  {row['scenario']:20} hitch {row['hitchTimeMSPerS']:>8} ms/s  "
            f"maxGap {row['maxGapMS']:>8} ms  frames {row['framesDelivered']:>6}  "
            f"coverage {row['probeCoverage']:.0%}  [{row['designation']}]{flag}"
        )

    if args.emit_evidence:
        import publish_benchmark_history as publisher
        try:
            profile_id = publisher.verify_canonical_hardware("macos")["profileID"]
        except publisher.PublicationError as error:
            print(f"ui-perf evidence skipped (non-canonical hardware): {error}")
        else:
            manifest = build_evidence_manifest(
                run_id=args.run_id,
                label=args.label,
                scenarios=scenarios,
                scenario_warnings=scenario_warnings,
                probe_digest=probe_hash.hexdigest(),
                profile_id=profile_id,
                hardware={k: v for k, v in hardware_context.items() if k != "profileID"},
                run_warnings=extra_run_warnings,
            )
            evidence_path = output.parent / "benchmark-evidence.json"
            evidence_path.write_text(
                json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
            print(f"ui-perf evidence -> {evidence_path}")

    print(f"ui-perf gate PASS: {len(scenarios)} scenarios -> {output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
