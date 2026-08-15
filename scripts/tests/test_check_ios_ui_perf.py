#!/usr/bin/env python3
"""Unit tests for scripts/check_ios_ui_perf.py (IUI-1).

Offline fixtures cover the structural gate's fail-closed branches — the
three scripted refusals the roadmap gate names (missing scenario marker,
probe-coverage shortfall, cadence-band violation) plus marker/threshold
semantics — and the canonical-hardware hook, so the device lane only has to
prove the live end of the contract.
"""
import base64
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import check_ios_ui_perf as checker  # noqa: E402


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
                frames_per_block: int = 30, max_gap: float = 16.67) -> list[dict]:
    blocks = []
    for index in range(count):
        block_start = start + index * 500
        blocks.append({
            "kind": "block",
            "scenario": None,
            "startEpochMS": block_start,
            "endEpochMS": block_start + 500,
            "framesDelivered": frames_per_block,
            "expectedFrames": 30,
            "sumExcessMS": hitch_ms_per_block,
            "maxGapMS": max_gap,
            "gapHistogram": [frames_per_block, 0, 0, 0, 0, 0, 0],
            "refreshIntervalMS": 16.667,
            "cpuUserMS": 100 + index,
            "cpuSystemMS": 50 + index,
            "footprintMB": 180.0,
            "thermalState": "nominal",
        })
    return blocks


class IOSUIPerfFixture(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.diagnostics = self.root / "diag"
        (self.diagnostics / "ui-perf").mkdir(parents=True)
        self.run_started = 1_000_000

    def tearDown(self):
        self._tmp.cleanup()

    def write_run(
        self,
        hitch_by_scenario: dict[str, float] | None = None,
        frames_by_scenario: dict[str, int] | None = None,
        block_count_by_scenario: dict[str, int] | None = None,
    ):
        hitch_by_scenario = hitch_by_scenario or {}
        frames_by_scenario = frames_by_scenario or {}
        block_count_by_scenario = block_count_by_scenario or {}
        log_lines = []
        launch = self.run_started + 1_000
        for offset, scenario in enumerate(checker.EXPECTED_SCENARIOS):
            window_start = launch + offset * 20_000 + 3_000
            window_end = window_start + 5_000
            log_lines.append(make_marker(scenario, window_start, window_end))
            per_block = hitch_by_scenario.get(scenario, 0.0) * 0.5  # ms/s -> ms per 500 ms block
            rows = [{
                "kind": "environment",
                "scenario": scenario,
                "capturedEpochMS": launch + offset * 20_000,
                "uptimeSeconds": 3_600.0 + offset,
                "lowPowerModeEnabled": False,
                "loadAverage1Minute": 1.5 + offset * 0.1,
                "freeStorageBytes": 40_000_000_000 + offset,
                "thermalState": "nominal",
            }]
            rows += [dict(block, scenario=scenario) for block in make_blocks(
                window_start - 1_000,
                block_count_by_scenario.get(scenario, 16),
                hitch_ms_per_block=per_block,
                frames_per_block=frames_by_scenario.get(scenario, 30))]
            probe = self.diagnostics / "ui-perf" / f"frames-{launch + offset * 20_000}-{scenario}.jsonl"
            probe.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
        log = self.root / "xcodebuild.log"
        log.write_text("\n".join(log_lines) + "\n")
        return log

    def run_checker(self, log: Path, *, thresholds: Path | None = None,
                    require_canonical: bool = False,
                    emit_evidence: bool = False) -> tuple[int, dict | None]:
        output = self.root / "ui-perf-report.json"
        argv = [
            "check_ios_ui_perf.py",
            "--xcodebuild-log", str(log),
            "--diagnostics", str(self.diagnostics),
            "--run-id", "ios-xcui-perf-fixture-0001",
            "--run-started-epoch-ms", str(self.run_started),
            "--output", str(output),
        ]
        if thresholds is not None:
            argv += ["--thresholds", str(thresholds)]
        if require_canonical:
            argv.append("--require-canonical")
        if emit_evidence:
            argv.append("--emit-evidence")
        old_argv = sys.argv
        sys.argv = argv
        try:
            status = checker.main()
        finally:
            sys.argv = old_argv
        report = json.loads(output.read_text()) if output.is_file() else None
        return status, report

    def test_clean_run_passes_under_the_default_contract(self):
        log = self.write_run()
        status, report = self.run_checker(log)
        self.assertEqual(status, 0)
        self.assertEqual(report["platform"], "ios")
        self.assertEqual(report["status"], "passed")
        self.assertTrue(
            report["thresholds"]["path"].endswith("ui-perf-thresholds-ios.json"))
        self.assertEqual(report["thresholds"]["warnings"], [])
        self.assertEqual(len(report["scenarios"]), len(checker.EXPECTED_SCENARIOS))
        for scenario in report["scenarios"]:
            self.assertEqual(scenario["medianBlockCadenceHz"], 60.0)

    def test_missing_marker_fails_closed(self):
        log = self.write_run()
        lines = log.read_text().splitlines()
        log.write_text("\n".join(lines[1:]) + "\n")
        status, _ = self.run_checker(log)
        self.assertEqual(status, 1)

    def test_duplicate_marker_fails_closed(self):
        log = self.write_run()
        lines = log.read_text().splitlines()
        log.write_text("\n".join(lines + [lines[0]]) + "\n")
        status, _ = self.run_checker(log)
        self.assertEqual(status, 1)

    def test_coverage_shortfall_fails_closed(self):
        # 6 blocks x 500 ms starting 1 s before a 5 s window: only 2 s of the
        # window is covered — far below the 90% floor.
        log = self.write_run(block_count_by_scenario={"ios-voices-scroll": 6})
        status, _ = self.run_checker(log)
        self.assertEqual(status, 1)

    def test_cadence_band_violation_on_the_idle_sentinel_fails_closed(self):
        # 15 frames per 500 ms block = 30 Hz median cadence on the quiet
        # sentinel: the pinned 60 Hz link was not honored (Low Power Mode /
        # thermal cap posture).
        log = self.write_run(frames_by_scenario={"ios-idle-baseline": 15})
        status, _ = self.run_checker(log)
        self.assertEqual(status, 1)

    def test_cadence_band_violation_on_interactive_scenarios_is_warn_only(self):
        # On interactive scenarios block cadence conflates system re-pacing
        # with the main-thread stalls the lane measures, so an out-of-band
        # median must degrade to a warning, never discard the run.
        log = self.write_run(frames_by_scenario={"ios-player-scrub": 15})
        status, report = self.run_checker(log)
        self.assertEqual(status, 0)
        self.assertEqual(report["status"], "passedWithWarnings")
        self.assertEqual(
            report["thresholds"]["warnings"], ["uiperf.cadence:ios-player-scrub(30/55-65)"])

    def test_thresholds_remain_warn_only_when_supplied(self):
        thresholds = self.root / "thresholds.json"
        thresholds.write_text(json.dumps({
            "schemaVersion": 1,
            "warnOnly": True,
            "confirmatoryScenarios": ["ios-idle-baseline"],
            "hitchCeilingMSPerS": {"ios-idle-baseline": 5.0},
            "maxGapCeilingMS": {"ios-idle-baseline": 40.0},
        }))
        log = self.write_run(hitch_by_scenario={"ios-idle-baseline": 50.0})
        status, report = self.run_checker(log, thresholds=thresholds)
        self.assertEqual(status, 0)
        self.assertEqual(report["status"], "passedWithWarnings")
        self.assertEqual(
            report["thresholds"]["warnings"], ["uiperf.hitch:ios-idle-baseline(50/5)"])

    def test_shipped_contract_binds_exactly_the_confirmatory_scenarios(self):
        contract = json.loads(
            (Path(checker.REPO_ROOT) / "config" / "ui-perf-thresholds-ios.json").read_text())
        self.assertEqual(contract["schemaVersion"], 1)
        self.assertTrue(contract["warnOnly"])
        confirmatory = set(checker.EXPECTED_SCENARIOS) - checker.EXPLORATORY
        self.assertEqual(set(contract["confirmatoryScenarios"]), confirmatory)
        self.assertEqual(set(contract["hitchCeilingMSPerS"]), confirmatory)
        self.assertEqual(set(contract["maxGapCeilingMS"]), confirmatory)

    def test_scenario_set_matches_the_registry_contract(self):
        import benchmark_history
        self.assertEqual(
            benchmark_history.UI_PERF_SCENARIOS_BY_PLATFORM["ios"],
            set(checker.EXPECTED_SCENARIOS))

    def test_emit_evidence_writes_a_registry_manifest_including_the_warn_path(self):
        # A hitch breach on a confirmatory scenario must flow warn-only from
        # the checker through the evidence manifest: run and take status
        # passedWithWarnings, gate still PASS — the offline half of the
        # IUI-6 end-to-end warn-path proof.
        log = self.write_run(hitch_by_scenario={"ios-voices-scroll": 500.0})
        original = checker.verify_canonical_iphone
        checker.verify_canonical_iphone = lambda diagnostics, run_id: "iphone-17-pro"
        try:
            status, report = self.run_checker(
                log, require_canonical=True, emit_evidence=True)
        finally:
            checker.verify_canonical_iphone = original
        self.assertEqual(status, 0)
        self.assertEqual(report["status"], "passedWithWarnings")
        self.assertEqual(report["evidence"], "registry")
        self.assertEqual(
            report["thresholds"]["warnings"], ["uiperf.hitch:ios-voices-scroll(500/90)"])
        manifest = json.loads((self.root / "benchmark-evidence.json").read_text())
        self.assertEqual(manifest["benchmarkKind"], "ui-perf")
        self.assertEqual(manifest["platform"], "ios")
        self.assertEqual(manifest["status"], "passedWithWarnings")
        record = manifest["historyRecord"]
        self.assertEqual(record["run"]["matrixScope"], "canonical")
        self.assertEqual(record["run"]["platform"], "ios")
        self.assertEqual(
            record["run"]["warnings"], ["uiperf.hitch:ios-voices-scroll(500/90)"])
        self.assertEqual(record["hardware"], {"profileID": "iphone-17-pro"})
        self.assertEqual(record["models"], [])
        hardware = manifest["hardware"]
        self.assertEqual(hardware["profileID"], "iphone-17-pro")
        self.assertEqual(hardware["thermalState"], "nominal")
        self.assertFalse(hardware["lowPowerMode"])
        self.assertEqual(hardware["uptimeSeconds"], 3_600.0)
        self.assertEqual(hardware["freeStorageBytes"], 40_000_000_000)
        self.assertAlmostEqual(hardware["loadAverage1M"], 2.3)
        self.assertEqual(record["evidence"]["telemetrySchemaVersion"], "not-applicable")
        self.assertEqual(record["evidence"]["qcAlgorithmVersion"], "not-applicable")
        takes = record["takes"]
        self.assertEqual(len(takes), len(checker.EXPECTED_SCENARIOS))
        import benchmark_history
        for take, scenario in zip(takes, checker.EXPECTED_SCENARIOS):
            self.assertEqual(take["cell"], f"ui-perf/{scenario}")
            self.assertEqual(
                take["generationID"], f"ios-xcui-perf-fixture-0001-{scenario}")
            self.assertEqual(take["mode"], "not-applicable")
            self.assertEqual(take["finishReason"], "completed")
            missing = benchmark_history.UI_PERF_REQUIRED_METRICS - set(take["metrics"])
            self.assertEqual(sorted(missing), [])
        breached = next(
            t for t in takes if t["cell"] == "ui-perf/ios-voices-scroll")
        self.assertEqual(breached["status"], "passedWithWarnings")

    def test_emit_evidence_fails_closed_without_an_environment_snapshot(self):
        # A stale installed app (pre-IUI-6 probe) writes no environment row;
        # publishing without device-truth hardware would mint a
        # schema-incomplete record, so the gate must refuse instead.
        log = self.write_run()
        for probe in (self.diagnostics / "ui-perf").glob("frames-*.jsonl"):
            rows = [
                line for line in probe.read_text().splitlines()
                if '"environment"' not in line
            ]
            probe.write_text("\n".join(rows) + "\n")
        original = checker.verify_canonical_iphone
        checker.verify_canonical_iphone = lambda diagnostics, run_id: "iphone-17-pro"
        try:
            status, _ = self.run_checker(
                log, require_canonical=True, emit_evidence=True)
        finally:
            checker.verify_canonical_iphone = original
        self.assertEqual(status, 1)
        self.assertFalse((self.root / "benchmark-evidence.json").exists())

    def test_emit_evidence_skips_gracefully_off_canonical_hardware(self):
        log = self.write_run()

        def failing_verify(diagnostics, run_id):
            raise checker.GateError("canonical iPhone verification failed: fixture")

        original = checker.verify_canonical_iphone
        checker.verify_canonical_iphone = failing_verify
        try:
            status, report = self.run_checker(log, emit_evidence=True)
        finally:
            checker.verify_canonical_iphone = original
        self.assertEqual(status, 0)
        self.assertEqual(report["evidence"], "local-only")
        self.assertFalse((self.root / "benchmark-evidence.json").exists())

    def test_require_canonical_records_the_verified_profile(self):
        log = self.write_run()
        observed = {}

        def fake_verify(diagnostics, run_id):
            observed["diagnostics"] = Path(diagnostics)
            observed["run_id"] = run_id
            return "iphone-17-pro"

        original = checker.verify_canonical_iphone
        checker.verify_canonical_iphone = fake_verify
        try:
            status, report = self.run_checker(log, require_canonical=True)
        finally:
            checker.verify_canonical_iphone = original
        self.assertEqual(status, 0)
        self.assertEqual(report["hardwareProfileID"], "iphone-17-pro")
        self.assertEqual(observed["diagnostics"], self.diagnostics)
        self.assertEqual(observed["run_id"], "ios-xcui-perf-fixture-0001")

    def test_require_canonical_fails_closed_on_verification_error(self):
        log = self.write_run()

        def failing_verify(diagnostics, run_id):
            raise checker.GateError("canonical iPhone verification failed: fixture")

        original = checker.verify_canonical_iphone
        checker.verify_canonical_iphone = failing_verify
        try:
            status, report = self.run_checker(log, require_canonical=True)
        finally:
            checker.verify_canonical_iphone = original
        self.assertEqual(status, 1)
        self.assertIsNone(report)


if __name__ == "__main__":
    unittest.main()
