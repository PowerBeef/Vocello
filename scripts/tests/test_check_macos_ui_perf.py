#!/usr/bin/env python3
"""Unit tests for scripts/check_macos_ui_perf.py (UI-7).

Offline fixtures cover the structural gate's fail-closed branches, the
warn-only threshold evaluation, and the registry evidence manifest's exact
take identities — the contract validate_ui_perf_semantics enforces at
publication time.
"""
import base64
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import check_macos_ui_perf as checker  # noqa: E402
from lib import ui_perf_thresholds as rules  # noqa: E402
from lib import ui_perf_lane as lane  # noqa: E402


def make_marker(scenario: str, start: int, end: int, actions: int = 4) -> str:
    payload = base64.b64encode(json.dumps({
        "schemaVersion": 1,
        "scenario": scenario,
        "windowStartEpochMS": start,
        "windowEndEpochMS": end,
        "actionCount": actions,
    }).encode()).decode()
    return f"VOCELLO_UIPERF_SCENARIO={payload}"


def make_blocks(start: int, count: int, hitch_ms_per_block: float = 0.0,
                max_gap: float = 16.67) -> list[dict]:
    blocks = []
    for index in range(count):
        block_start = start + index * 500
        blocks.append({
            "kind": "block",
            "scenario": None,
            "startEpochMS": block_start,
            "endEpochMS": block_start + 500,
            "framesDelivered": 30,
            "expectedFrames": 30,
            "sumExcessMS": hitch_ms_per_block,
            "maxGapMS": max_gap,
            "gapHistogram": [30, 0, 0, 0, 0, 0, 0],
            "refreshIntervalMS": 16.667,
            "cpuUserMS": 100 + index,
            "cpuSystemMS": 50 + index,
            "footprintMB": 60.0,
            "thermalState": "nominal",
        })
    return blocks


class UIPerfFixture(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.diagnostics = self.root / "diag"
        (self.diagnostics / "ui-perf").mkdir(parents=True)
        self.run_started = 1_000_000
        self.thresholds = self.root / "thresholds.json"
        self.contract = {
            "schemaVersion": 1,
            "warnOnly": True,
            "calibrationProfile": "mac-mini-m6-16gb",
            "calibrationRefreshIntervalMS": 16.67,
            "confirmatoryScenarios": ["idle-baseline"],
            "hitchCeilingMSPerS": {"idle-baseline": 5.0},
            "maxGapCeilingMS": {"idle-baseline": 40.0},
        }
        self.thresholds.write_text(json.dumps(self.contract))

    def tearDown(self):
        self._tmp.cleanup()

    def write_run(self, hitch_by_scenario: dict[str, float] | None = None, *,
                  refresh_ms: float = 16.667, footprint_growth: dict[str, float] | None = None,
                  probe_summary: dict | None = None, sampler_interval_ms: int | None = None,
                  samples: bool = False):
        hitch_by_scenario = hitch_by_scenario or {}
        footprint_growth = footprint_growth or {}
        log_lines = []
        launch = self.run_started + 1_000
        for offset, scenario in enumerate(checker.EXPECTED_SCENARIOS):
            window_start = launch + offset * 20_000 + 3_000
            window_end = window_start + 5_000
            log_lines.append(make_marker(scenario, window_start, window_end))
            per_block = hitch_by_scenario.get(scenario, 0.0) * 0.5  # ms/s -> ms per 500 ms block
            rows = [{"kind": "meta", "scenario": scenario}, {
                "kind": "environment",
                "scenario": scenario,
                "capturedEpochMS": launch + offset * 20_000,
                "uptimeSeconds": 7_200.0 + offset,
                "lowPowerModeEnabled": False,
                "loadAverage1Minute": 2.0 + offset * 0.1,
                "freeStorageBytes": 90_000_000_000 + offset,
                "thermalState": "nominal",
                **({"telemetrySamplerIntervalMS": sampler_interval_ms} if sampler_interval_ms else {}),
            }]
            blocks = make_blocks(window_start - 1_000, 16, hitch_ms_per_block=per_block)
            for index, block in enumerate(blocks):
                block["refreshIntervalMS"] = refresh_ms
                block["footprintMB"] = 60.0 + footprint_growth.get(scenario, 0.0) * index / (len(blocks) - 1)
                if samples:
                    # Every frame gap and the block's heartbeats (audit #80, #81).
                    block["gaps"] = [[round((frame + 1) * 16.667, 2), 16.67] for frame in range(30)]
                    block["heartbeatCount"] = 5
                    block["delayedHeartbeats"] = (
                        [[block["startEpochMS"] + 250, 120]] if index == 4 else []
                    )
            rows += [dict(block, scenario=scenario) for block in blocks]
            if probe_summary is not None:
                rows.append({"kind": "summary", "scenario": scenario, **probe_summary})
            probe = self.diagnostics / "ui-perf" / f"frames-{launch + offset * 20_000}-{scenario}.jsonl"
            probe.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
        log = self.root / "xcodebuild.log"
        log.write_text("\n".join(log_lines) + "\n")
        return log

    def run_checker(self, log: Path, *, emit: bool = False) -> tuple[int, dict | None]:
        output = self.root / "ui-perf-report.json"
        argv = [
            "check_macos_ui_perf.py",
            "--xcodebuild-log", str(log),
            "--diagnostics", str(self.diagnostics),
            "--run-id", "macos-xcui-perf-fixture-0001",
            "--run-started-epoch-ms", str(self.run_started),
            "--output", str(output),
            "--thresholds", str(self.thresholds),
        ]
        if emit:
            argv.append("--emit-evidence")
        old_argv = sys.argv
        sys.argv = argv
        try:
            status = checker.main()
        finally:
            sys.argv = old_argv
        report = json.loads(output.read_text()) if output.is_file() else None
        return status, report

    def test_clean_run_passes_without_warnings(self):
        log = self.write_run()
        status, report = self.run_checker(log)
        self.assertEqual(status, 0)
        self.assertEqual(report["status"], "passed")
        self.assertEqual(report["thresholds"]["warnings"], [])
        self.assertEqual(len(report["scenarios"]), len(checker.EXPECTED_SCENARIOS))

    def test_generation_active_names_its_sampler_cadence(self):
        """audit #33: the memory samplers run beside the generation-active window."""
        status, report = self.run_checker(self.write_run(sampler_interval_ms=250))
        self.assertEqual(status, 0)
        by_scenario = {row["scenario"]: row for row in report["scenarios"]}
        self.assertEqual(by_scenario["generation-active"]["samplerIntervalMS"], 250)
        self.assertEqual(
            checker.take_metrics(by_scenario["generation-active"])["samplerTargetIntervalMS"], 250,
        )
        self.assertNotIn("samplerIntervalMS", by_scenario["idle-baseline"])
        # Probes that predate the field publish no cadence.
        status, report = self.run_checker(self.write_run())
        self.assertEqual(status, 0)
        self.assertNotIn(
            "samplerTargetIntervalMS",
            checker.take_metrics({row["scenario"]: row for row in report["scenarios"]}["generation-active"]),
        )

    def test_missing_marker_fails_closed(self):
        log = self.write_run()
        lines = log.read_text().splitlines()
        log.write_text("\n".join(lines[1:]) + "\n")
        status, _ = self.run_checker(log)
        self.assertEqual(status, 1)

    def test_threshold_breach_is_warn_only(self):
        log = self.write_run(hitch_by_scenario={"idle-baseline": 50.0})
        status, report = self.run_checker(log)
        self.assertEqual(status, 0)
        self.assertEqual(report["status"], "passedWithWarnings")
        self.assertEqual(report["thresholds"]["warnings"], ["uiperf.hitch:idle-baseline(50/5)"])

    def test_m2_ceilings_on_the_canonical_m6_are_uncalibrated(self):
        """audit #77: M6 runs carry one uncalibrated code, never M2 verdicts."""
        self.thresholds.write_text(json.dumps({**self.contract, "calibrationProfile": "mac-mini-m2-8gb"}))
        log = self.write_run(hitch_by_scenario={"idle-baseline": 50.0})
        status, report = self.run_checker(log)
        self.assertEqual(status, 0)
        self.assertFalse(report["thresholds"]["calibrated"])
        self.assertEqual(report["thresholds"]["warnings"], ["uiperf.uncalibrated:mac-mini-m2-8gb"])
        self.assertEqual(report["status"], "passedWithWarnings")
        self.assertTrue(all(not row["thresholdWarnings"] for row in report["scenarios"]))

    def test_another_refresh_interval_is_uncalibrated(self):
        log = self.write_run(hitch_by_scenario={"idle-baseline": 50.0}, refresh_ms=8.333)
        status, report = self.run_checker(log)
        self.assertEqual(status, 0)
        self.assertFalse(report["thresholds"]["calibrated"])
        self.assertEqual(report["thresholds"]["warnings"], ["uiperf.uncalibrated:mac-mini-m6-16gb"])

    def test_the_shipped_contract_names_its_calibration(self):
        contract = checker.load_thresholds(checker.DEFAULT_THRESHOLDS_PATH)
        self.assertEqual(
            (contract["calibrationProfile"], contract["calibrationRefreshIntervalMS"]),
            ("mac-mini-m2-8gb", 16.67),
        )
        for field in ("calibrationProfile", "calibrationRefreshIntervalMS"):
            broken = {key: value for key, value in self.contract.items() if key != field}
            self.thresholds.write_text(json.dumps(broken))
            with self.subTest(field=field), self.assertRaises(checker.GateError):
                checker.load_thresholds(self.thresholds)

    def test_footprint_growth_in_a_confirmatory_window_warns(self):
        """audit #33(a): product warms inside a navigation window show as growth."""
        self.thresholds.write_text(json.dumps({**self.contract, "footprintGrowthCeilingMB": 250.0}))
        log = self.write_run(footprint_growth={"idle-baseline": 900.0, "window-resize": 900.0})
        status, report = self.run_checker(log)
        self.assertEqual(status, 0)
        idle = next(row for row in report["scenarios"] if row["scenario"] == "idle-baseline")
        self.assertEqual(len(idle["thresholdWarnings"]), 1)
        self.assertTrue(idle["thresholdWarnings"][0].startswith("uiperf.footprint:idle-baseline("))
        # Exploratory scenarios carry no footprint ceiling either.
        resize = next(row for row in report["scenarios"] if row["scenario"] == "window-resize")
        self.assertEqual(resize["thresholdWarnings"], [])

    def test_probe_watchdog_summary_is_not_published_as_generation_metrics(self):
        """audit #80: the launch-scoped summary never takes generation-scoped names."""
        log = self.write_run(probe_summary={
            "delayedHeartbeatCount50": 3, "delayedHeartbeatCount250": 1, "maximumDelayedHeartbeatMS": 400,
        })
        live_publisher = sys.modules.get("publish_benchmark_history")
        if live_publisher is None:
            import publish_benchmark_history as live_publisher
        with mock.patch.object(
            live_publisher, "verify_canonical_hardware", return_value={"profileID": "mac-mini-m6-16gb"}
        ):
            status, report = self.run_checker(log, emit=True)
        self.assertEqual(status, 0)
        self.assertEqual(report["scenarios"][0]["launchMaxStallMS"], 400)
        manifest = json.loads((self.root / "benchmark-evidence.json").read_text())
        for take in manifest["historyRecord"]["takes"]:
            self.assertNotIn("uiMaximumDelayedHeartbeatMS", take["metrics"])
            self.assertNotIn("delayedHeartbeatCount", take["metrics"])

    def test_exploratory_scenarios_carry_no_ceilings(self):
        log = self.write_run(hitch_by_scenario={"history-scroll": 900.0})
        status, report = self.run_checker(log)
        self.assertEqual(status, 0)
        self.assertEqual(report["status"], "passed")

    def test_evidence_manifest_take_identity_matches_registry_contract(self):
        summaries = [
            {
                "scenario": scenario,
                "hitchTimeMSPerS": 1.0,
                "maxGapMS": 16.7,
                "framesDelivered": 300,
                "expectedFrames": 300,
                "probeCoverage": 1.0,
                "refreshIntervalMS": 16.667,
                "durationMS": 5000,
                "actionCount": 4,
                "cpuUserMS": 100,
                "cpuSystemMS": 50,
                "thermalStates": ["nominal"],
                "p95GapMSApprox": 20.83,
            }
            for scenario in checker.EXPECTED_SCENARIOS
        ]
        manifest = checker.build_evidence_manifest(
            run_id="macos-xcui-perf-fixture-0001",
            label="fixture",
            scenarios=summaries,
            scenario_warnings={"idle-baseline": ["uiperf.hitch:idle-baseline(50/5)"]},
            probe_digest="0" * 64,
            profile_id="mac-mini-m2-8gb",
        )
        self.assertEqual(manifest["benchmarkKind"], "ui-perf")
        self.assertEqual(manifest["status"], "passedWithWarnings")
        record = manifest["historyRecord"]
        self.assertEqual(record["run"]["matrixScope"], "canonical")
        self.assertEqual(record["models"], [])
        self.assertEqual(record["evidence"]["telemetrySchemaVersion"], "not-applicable")
        self.assertEqual(record["evidence"]["qcAlgorithmVersion"], "not-applicable")
        takes = record["takes"]
        self.assertEqual(len(takes), len(checker.EXPECTED_SCENARIOS))
        for take, scenario in zip(takes, checker.EXPECTED_SCENARIOS):
            self.assertEqual(take["cell"], f"ui-perf/{scenario}")
            self.assertEqual(take["generationID"], f"macos-xcui-perf-fixture-0001-{scenario}")
            self.assertEqual(take["mode"], "not-applicable")
            self.assertEqual(take["finishReason"], "completed")
            self.assertIn("uiHitchTimeMSPerS", take["metrics"])
            self.assertIn("cpuUserSeconds", take["metrics"])
        idle = takes[0]
        self.assertEqual(idle["status"], "passedWithWarnings")
        self.assertEqual(takes[1]["status"], "passed")



class WindowArithmeticTests(unittest.TestCase):
    def marker(self, start: int, end: int) -> dict:
        return {"scenario": "idle-baseline", "windowStartEpochMS": start, "windowEndEpochMS": end,
                "actionCount": 1}

    def test_edge_blocks_contribute_only_their_in_window_fraction(self):
        # Blocks at 0-500, 500-1000, 1000-1500; window 250-1250 straddles both edges.
        blocks = make_blocks(0, 3, hitch_ms_per_block=100.0)
        summary, coverage = checker.summarize_scenario(
            self.marker(250, 1_250), blocks, exploratory=set())
        self.assertEqual(coverage, 1.0)
        self.assertEqual(summary["framesDelivered"], 60)      # 15 + 30 + 15
        self.assertEqual(summary["gapHistogram"][0], 60)
        self.assertAlmostEqual(summary["hitchTimeMSPerS"], 200.0)  # 200 ms over 1.0 s covered
        self.assertEqual(summary["maxGapMS"], 16.67)           # unclipped worst gap

    def test_hitch_rate_uses_the_covered_span_not_the_marker_length(self):
        # Only the first 1.0 s of a 2.0 s window has probe blocks.
        blocks = make_blocks(0, 2, hitch_ms_per_block=50.0)
        summary, coverage = checker.summarize_scenario(
            self.marker(0, 2_000), blocks, exploratory=set())
        self.assertEqual(coverage, 0.5)
        self.assertAlmostEqual(summary["hitchTimeMSPerS"], 100.0)

    def test_hitch_per_action_is_the_in_window_excess_over_the_actions(self):
        """audit #79: harness pacing between actions cannot dilute it."""
        blocks = make_blocks(0, 4, hitch_ms_per_block=100.0)
        marker = dict(self.marker(0, 2_000), actionCount=4)
        summary, _ = checker.summarize_scenario(marker, blocks, exploratory=set())
        self.assertAlmostEqual(summary["hitchMSPerAction"], 100.0)   # 400 ms over 4 actions
        self.assertAlmostEqual(checker.take_metrics({**summary, "cpuUserMS": 0, "cpuSystemMS": 0})["uiHitchMSPerAction"], 100.0)
        idle = dict(self.marker(0, 2_000), actionCount=0)
        summary, _ = checker.summarize_scenario(idle, blocks, exploratory=set())
        self.assertIsNone(summary["hitchMSPerAction"])

    def test_cycle_markers_yield_per_cycle_hitch_rates(self):
        """audit #34(b): within-run samples, apportioned like the window."""
        blocks = make_blocks(0, 4)
        blocks[1]["sumExcessMS"] = 250.0      # 500-1000 ms
        marker = dict(self.marker(0, 2_000), cycles=[
            {"startEpochMS": 0, "endEpochMS": 1_000}, {"startEpochMS": 1_000, "endEpochMS": 2_000},
        ])
        summary, _ = checker.summarize_scenario(marker, blocks, exploratory=set())
        self.assertEqual(summary["cycleHitchTimeMSPerS"], [250.0, 0.0])
        self.assertAlmostEqual(summary["hitchTimeMSPerS"], 125.0)
        legacy, _ = checker.summarize_scenario(self.marker(0, 2_000), blocks, exploratory=set())
        self.assertNotIn("cycleHitchTimeMSPerS", legacy)
        for cycles in (
            [],
            [{"startEpochMS": 500, "endEpochMS": 2_500}],
            [{"startEpochMS": 1_000, "endEpochMS": 1_500}, {"startEpochMS": 0, "endEpochMS": 900}],
            [{"startEpochMS": 0}],
        ):
            with self.subTest(cycles=cycles), self.assertRaises(checker.GateError):
                checker.summarize_scenario(dict(self.marker(0, 2_000), cycles=cycles), blocks, exploratory=set())

    def test_phase_markers_split_the_window_by_what_the_harness_did(self):
        """audit #32: query, action and verify spans, each apportioned like the window."""
        blocks = make_blocks(0, 4)
        blocks[0]["sumExcessMS"] = 100.0      # 0-500 ms: the query span
        blocks[2]["sumExcessMS"] = 300.0      # 1000-1500 ms: the action span
        marker = dict(self.marker(0, 2_000), phases=[
            {"name": "query", "startEpochMS": 0, "endEpochMS": 500},
            {"name": "action", "startEpochMS": 1_000, "endEpochMS": 1_500},
            {"name": "verify", "startEpochMS": 1_500, "endEpochMS": 2_000},
        ])
        summary, _ = checker.summarize_scenario(marker, blocks, exploratory=set())
        self.assertEqual(summary["phases"], {
            "action": {"durationMS": 500, "hitchTimeMSPerS": 600.0},
            "query": {"durationMS": 500, "hitchTimeMSPerS": 200.0},
            "verify": {"durationMS": 500, "hitchTimeMSPerS": 0.0},
        })
        legacy, _ = checker.summarize_scenario(self.marker(0, 2_000), blocks, exploratory=set())
        self.assertNotIn("phases", legacy)
        for phases in (
            [],
            [{"name": "idle", "startEpochMS": 0, "endEpochMS": 500}],
            [{"name": "query", "startEpochMS": 500, "endEpochMS": 2_500}],
            [{"name": "query", "startEpochMS": 600, "endEpochMS": 900},
             {"name": "action", "startEpochMS": 0, "endEpochMS": 500}],
        ):
            with self.subTest(phases=phases), self.assertRaises(checker.GateError):
                checker.summarize_scenario(dict(self.marker(0, 2_000), phases=phases), blocks, exploratory=set())

    def test_lane_phases_name_where_the_lane_time_went(self):
        """audit #82: setup stamps per scenario and the step ledger's durations."""
        stamps = {
            "idle-baseline": {"launchStart": 0, "launchReady": 4_000, "settled": 7_000,
                              "windowStart": 8_000, "windowEnd": 23_000},
            "sidebar-navigation": {"launchStart": 30_000, "launchReady": 33_000, "settled": 36_000,
                                   "windowStart": 36_000, "windowEnd": 46_000},
            "history-scroll": {"launchStart": 50_000},
        }
        ledger = {
            "startedAt": "2026-09-25T10:00:00Z",
            "results": {
                "xcuitest": {"status": "passed", "completedAt": "2026-09-25T10:05:00Z"},
                "build": {"status": "passed", "completedAt": "2026-09-25T10:01:30Z"},
            },
        }
        phases = lane.lane_phases(stamps, ledger, checker.EXPECTED_SCENARIOS)
        self.assertEqual([item["scenario"] for item in phases["scenarios"]], ["idle-baseline", "sidebar-navigation"])
        self.assertEqual(phases["scenarios"][0], {
            "scenario": "idle-baseline", "launchMS": 4_000, "settleMS": 3_000, "setupMS": 1_000,
            "windowMS": 15_000, "totalMS": 23_000,
        })
        self.assertEqual(phases["windowShare"], round(25_000 / 39_000, 4))
        self.assertEqual(phases["steps"], [
            {"step": "build", "status": "passed", "secondsSincePrevious": 90.0},
            {"step": "xcuitest", "status": "passed", "secondsSincePrevious": 210.0},
        ])
        self.assertEqual(lane.lane_phases({}, None, checker.EXPECTED_SCENARIOS), {"scenarios": [], "windowShare": None})

    def test_samples_clip_the_maximum_gap_and_scope_heartbeats_to_the_window(self):
        """audit #80, #81: a gap straddling the window edge counts only its
        in-window part, p95 comes from samples, heartbeats by completion time."""
        blocks = make_blocks(0, 4)
        for block in blocks:
            block["gaps"] = [[16.67 * (frame + 1), 16.67] for frame in range(29)]
            block["heartbeatCount"] = 5
            block["delayedHeartbeats"] = []
        # A 400 ms stall ending 100 ms into the window [1_000, 2_000): 300 ms
        # of it fell before the window opened.
        blocks[2]["gaps"].append([100.0, 400.0])
        blocks[2]["maxGapMS"] = 400.0
        blocks[3]["delayedHeartbeats"] = [[1_700, 300], [2_600, 900]]
        summary, _ = checker.summarize_scenario(self.marker(1_000, 2_000), blocks, exploratory=set())
        self.assertEqual(summary["maxGapMS"], 100.0)
        self.assertTrue(summary["maxGapClipped"])
        self.assertEqual(summary["p95GapMS"], 16.67)
        self.assertEqual(summary["gapSampleCount"], 59)
        self.assertIsNone(summary["p95GapMSApprox"])
        self.assertEqual(summary["windowHeartbeats"], {
            "heartbeatCount": 10, "delayedHeartbeatCount50": 1,
            "delayedHeartbeatCount250": 1, "maximumDelayedHeartbeatMS": 300,
        })
        metrics = checker.take_metrics(summary)
        self.assertEqual(metrics["uiMaxGapMS"], 100.0)
        self.assertEqual(metrics["uiP95GapMS"], 16.67)
        self.assertNotIn("uiP95GapMSApprox", metrics)
        self.assertEqual(metrics["uiWindowMaximumDelayedHeartbeatMS"], 300)
        # A probe without samples keeps the block maxima and the approximation.
        legacy, _ = checker.summarize_scenario(self.marker(1_000, 2_000), make_blocks(0, 4), exploratory=set())
        self.assertNotIn("maxGapClipped", legacy)
        self.assertIsNotNone(legacy["p95GapMSApprox"])
        self.assertFalse({key for key in checker.take_metrics(legacy) if key.startswith("uiWindowHeartbeat") or key.startswith("uiWindowDelayed") or key.startswith("uiWindowMaximum")})

    def test_a_missing_refresh_interval_fails_closed(self):
        blocks = make_blocks(0, 4)
        for block in blocks:
            block["refreshIntervalMS"] = 0.0
        with self.assertRaisesRegex(checker.GateError, "refresh interval"):
            checker.summarize_scenario(self.marker(0, 2_000), blocks, exploratory=set())


# The three counted M2 sessions behind the committed baseline-v3 ceilings
# (runs 0bb33592, 636488c2, 64610737), embedded so the test never reads live records.
V3_BASIS = {
    "idle-baseline": ([1.338, 0.0, 0.0], [36.37, 16.67, 16.67]),
    "sidebar-navigation": ([106.222, 117.668, 112.21], [227.75, 248.29, 230.2]),
    "delivery-menu": ([117.043, 115.545, 116.451], [106.05, 99.66, 103.54]),
    "settings-scroll": ([0.0, 0.0, 0.0], [16.67, 16.67, 16.67]),
    "composer-typing": ([19.115, 18.367, 18.233], [78.45, 79.92, 73.0]),
}


def perf_record(run_id: str, values: dict[str, tuple[float, float]], *, profile: str = "mac-mini-m2-8gb",
                refresh: float = 16.667) -> dict:
    return {
        "run": {"id": run_id, "kind": "ui-perf", "platform": "macos", "classification": "canonical"},
        "hardware": {"profileID": profile},
        "comparison": {"key": "0" * 64},
        "takes": [
            {"cell": f"ui-perf/{scenario}", "metrics": {
                "uiHitchTimeMSPerS": hitch, "uiMaxGapMS": gap, "uiRefreshIntervalMS": refresh,
            }}
            for scenario, (hitch, gap) in values.items()
        ],
    }


def v3_records() -> list[dict]:
    return [
        perf_record(f"macos-xcui-perf-fixture-{index}", {
            scenario: (hitch[index], gap[index]) for scenario, (hitch, gap) in V3_BASIS.items()
        })
        for index in range(3)
    ]


class DerivationTests(unittest.TestCase):
    """audit #34, #78: ceilings derived from counted runs, reproducibly."""

    def setUp(self):
        self.base = checker.load_thresholds(checker.DEFAULT_THRESHOLDS_PATH)

    def test_the_v3_rule_reproduces_the_committed_ceilings(self):
        derived = rules.derive(v3_records(), self.base, rule=rules.V3_RULE)
        self.assertEqual(derived["hitchCeilingMSPerS"], self.base["hitchCeilingMSPerS"])
        self.assertEqual(derived["maxGapCeilingMS"], self.base["maxGapCeilingMS"])
        self.assertEqual(derived["calibrationProfile"], "mac-mini-m2-8gb")

    def test_the_spread_rule_floors_low_spread_scenarios_at_1_3x(self):
        derived = rules.derive(v3_records(), self.base, rule=rules.SPREAD_RULE)
        # delivery-menu: median 116.451, spread 1.3% -> 1.3x -> 151.39 -> 151.5
        self.assertEqual(derived["hitchCeilingMSPerS"]["delivery-menu"], 151.5)
        # sidebar-navigation: spread 10.2% -> 1 + 3 x 0.102 -> 146.66 -> 147.0
        self.assertEqual(derived["hitchCeilingMSPerS"]["sidebar-navigation"], 147.0)
        self.assertEqual(derived["hitchCeilingMSPerS"]["idle-baseline"], 5.0)
        self.assertEqual(derived["maxGapCeilingMS"]["settings-scroll"], 40.0)
        for scenario, (hitch, gap) in V3_BASIS.items():
            self.assertGreaterEqual(derived["hitchCeilingMSPerS"][scenario], max(hitch))
            self.assertGreaterEqual(derived["maxGapCeilingMS"][scenario], max(gap))

    def test_a_noisy_scenario_gets_room_in_proportion_to_its_spread(self):
        records = v3_records()
        for record, value in zip(records, (20.0, 30.0, 40.0)):
            next(t for t in record["takes"] if t["cell"] == "ui-perf/composer-typing")["metrics"]["uiHitchTimeMSPerS"] = value
        derived = rules.derive(records, self.base, rule=rules.SPREAD_RULE)
        # median 30, relative range 66.7% -> x3.0 -> 90
        self.assertEqual(derived["hitchCeilingMSPerS"]["composer-typing"], 90.0)

    def test_a_zero_median_scenario_still_clears_its_worst_run(self):
        records = v3_records()
        for record, value in zip(records, (0.0, 0.0, 20.0)):
            next(t for t in record["takes"] if t["cell"] == "ui-perf/settings-scroll")["metrics"]["uiHitchTimeMSPerS"] = value
        derived = rules.derive(records, self.base, rule=rules.SPREAD_RULE)
        # median 0, range 20 -> 0 + 3 x 20 = 60, above the calibration run's own 20
        self.assertEqual(derived["hitchCeilingMSPerS"]["settings-scroll"], 60.0)

    def test_derivation_counts_only_canonical_runs_of_one_lineage(self):
        exploratory = v3_records()
        exploratory[1]["run"]["classification"] = "exploratory"
        with self.assertRaises(rules.DerivationError):
            rules.derive(exploratory, self.base)
        mixed = v3_records()
        mixed[2]["comparison"]["key"] = "1" * 64
        with self.assertRaises(rules.DerivationError):
            rules.derive(mixed, self.base)
        keyless = v3_records()
        for record in keyless:
            del record["comparison"]
        with self.assertRaises(rules.DerivationError):
            rules.derive(keyless, self.base)

    def test_derivation_refuses_too_few_runs_or_mixed_profiles(self):
        with self.assertRaises(rules.DerivationError):
            rules.derive(v3_records()[:2], self.base)
        mixed = v3_records()
        mixed[2]["hardware"]["profileID"] = "mac-mini-m6-16gb"
        with self.assertRaises(rules.DerivationError):
            rules.derive(mixed, self.base)
        refresh = v3_records()
        for take in refresh[1]["takes"]:
            take["metrics"]["uiRefreshIntervalMS"] = 8.333
        with self.assertRaises(rules.DerivationError):
            rules.derive(refresh, self.base)

    def test_the_cli_writes_a_contract_the_checker_accepts(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = []
            for record in v3_records():
                record["hardware"]["profileID"] = "mac-mini-m6-16gb"
                path = root / f"{record['run']['id']}.json"
                path.write_text(json.dumps(record))
                paths.append(str(path))
            output = root / "derived.json"
            with mock.patch.object(sys, "argv", ["check_macos_ui_perf.py", "--derive-thresholds", *paths,
                                                 "--write", str(output)]):
                self.assertEqual(checker.main(), 0)
            derived = checker.load_thresholds(output)
        self.assertEqual(derived["calibrationProfile"], "mac-mini-m6-16gb")
        self.assertEqual(derived["derivationRule"], "spread-v1")
        self.assertEqual(len(derived["calibrationRuns"]), 3)
        self.assertEqual(derived["confirmatoryScenarios"], self.base["confirmatoryScenarios"])


class ThresholdsContractTests(unittest.TestCase):
    def test_shipped_contract_owns_the_confirmatory_designation(self):
        contract = checker.load_thresholds(checker.DEFAULT_THRESHOLDS_PATH)
        exploratory = checker.exploratory_scenarios(contract)
        self.assertEqual(exploratory, {
            "window-resize", "generation-active", "history-filter", "history-scroll",
            # audit #32 and #33: the harness control and the warm-on navigation.
            "harness-control", "sidebar-navigation-warms",
        })
        self.assertEqual(set(contract["hitchCeilingMSPerS"]), set(contract["confirmatoryScenarios"]))

    def test_contract_with_a_ceiling_for_an_undesignated_scenario_is_refused(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "thresholds.json"
            path.write_text(json.dumps({
                "schemaVersion": 1, "warnOnly": True,
                "calibrationProfile": "mac-mini-m6-16gb", "calibrationRefreshIntervalMS": 16.67,
                "confirmatoryScenarios": ["idle-baseline"],
                "hitchCeilingMSPerS": {"idle-baseline": 5.0, "window-resize": 5.0},
                "maxGapCeilingMS": {"idle-baseline": 40.0},
            }))
            with self.assertRaisesRegex(checker.GateError, "exactly the confirmatory"):
                checker.load_thresholds(path)


if __name__ == "__main__":
    unittest.main()
