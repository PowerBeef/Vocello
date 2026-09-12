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

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import check_macos_ui_perf as checker  # noqa: E402


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
        self.thresholds.write_text(json.dumps({
            "schemaVersion": 1,
            "warnOnly": True,
            "confirmatoryScenarios": ["idle-baseline"],
            "hitchCeilingMSPerS": {"idle-baseline": 5.0},
            "maxGapCeilingMS": {"idle-baseline": 40.0},
        }))

    def tearDown(self):
        self._tmp.cleanup()

    def write_run(self, hitch_by_scenario: dict[str, float] | None = None):
        hitch_by_scenario = hitch_by_scenario or {}
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
            }]
            rows += [dict(block, scenario=scenario) for block in make_blocks(
                window_start - 1_000, 16, hitch_ms_per_block=per_block)]
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

    def test_a_missing_refresh_interval_fails_closed(self):
        blocks = make_blocks(0, 4)
        for block in blocks:
            block["refreshIntervalMS"] = 0.0
        with self.assertRaisesRegex(checker.GateError, "refresh interval"):
            checker.summarize_scenario(self.marker(0, 2_000), blocks, exploratory=set())


class ThresholdsContractTests(unittest.TestCase):
    def test_shipped_contract_owns_the_confirmatory_designation(self):
        contract = checker.load_thresholds(checker.DEFAULT_THRESHOLDS_PATH)
        exploratory = checker.exploratory_scenarios(contract)
        self.assertEqual(
            exploratory, {"window-resize", "generation-active", "history-filter", "history-scroll"})
        self.assertEqual(set(contract["hitchCeilingMSPerS"]), set(contract["confirmatoryScenarios"]))

    def test_contract_with_a_ceiling_for_an_undesignated_scenario_is_refused(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "thresholds.json"
            path.write_text(json.dumps({
                "schemaVersion": 1, "warnOnly": True,
                "confirmatoryScenarios": ["idle-baseline"],
                "hitchCeilingMSPerS": {"idle-baseline": 5.0, "window-resize": 5.0},
                "maxGapCeilingMS": {"idle-baseline": 40.0},
            }))
            with self.assertRaisesRegex(checker.GateError, "exactly the confirmatory"):
                checker.load_thresholds(path)


if __name__ == "__main__":
    unittest.main()
