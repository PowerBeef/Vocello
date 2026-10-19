"""Lane ledger (scripts/lane_ledger.py): one classified line per finished run, and its KPIs."""

from __future__ import annotations

import datetime as dt
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("lane_ledger", ROOT / "scripts/lane_ledger.py")
assert SPEC is not None and SPEC.loader is not None
LEDGER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(LEDGER)


def ui_run(root: Path, name: str, *, passed: bool, log: str = "") -> Path:
    run = root / "build/artifacts/ui-tests/ios" / name
    run.mkdir(parents=True)
    status, code = ("passed", 0) if passed else ("failed", 65)
    (run / "run.json").write_text(json.dumps({
        "schemaVersion": 2, "platform": "ios", "lane": "smoke", "runID": name, "status": status, "exitCode": code,
        "startedAt": "2026-10-16T18:00:00Z", "finishedAt": "2026-10-16T18:20:00Z",
    }))
    (run / "required-steps.json").write_text(json.dumps({
        "runID": name, "status": status, "completedAt": "2026-10-16T18:20:00Z",
        "expectedSteps": [{"id": "ui-test", "required": True}],
        "results": {"ui-test": {"status": status, "exitCode": code}},
    }))
    if log:
        (run / "xcodebuild.log").write_text(log)
    return run


class LaneLedgerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_a_failed_ui_run_is_classified_with_its_infrastructure_cause(self) -> None:
        run = ui_run(self.root, "ios-xcui-smoke-20261016-180000-aaaa",
                     passed=False, log="...\nTimed out while enabling automation mode.\n")
        entry = LEDGER.entry_for(run, sha="abc")
        self.assertEqual(entry["lane"], "ios-ui-smoke")
        self.assertNotEqual(entry["verdict"], "PASS")
        self.assertEqual(entry["infrastructure"], "automation-mode")
        self.assertEqual(entry["durationSeconds"], 1200.0)
        self.assertEqual(entry["commit"], "abc")

    def test_a_passing_run_names_no_infrastructure_cause(self) -> None:
        run = ui_run(self.root, "ios-xcui-smoke-20261016-190000-bbbb", passed=True,
                     log="Timed out while enabling automation mode (recovered).\n")
        entry = LEDGER.entry_for(run)
        self.assertEqual(entry["verdict"], "PASS")
        self.assertIsNone(entry["infrastructure"])

    def test_a_deterministic_run_is_named_from_its_directory(self) -> None:
        run = self.root / "build/artifacts/macos/tests/mac-test-20261018-112808"
        run.mkdir(parents=True)
        (run / "verdict.txt").write_text("test_build=0\ncore=0\nruntime=0\ncore_summary=0\nruntime_summary=0\n")
        entry = LEDGER.entry_for(run)
        self.assertEqual(entry["lane"], "macos-deterministic")
        self.assertEqual(entry["verdict"], "PASS")

    def test_a_shipped_configuration_run_is_its_own_lane(self) -> None:
        run = self.root / "build/artifacts/macos/tests/mac-shipped-20261019-020000"
        run.mkdir(parents=True)
        (run / "verdict.txt").write_text("test_build=0\ncore=0\nruntime=0\ncore_summary=0\nruntime_summary=0\n")
        entry = LEDGER.entry_for(run)
        self.assertEqual(entry["lane"], "macos-shipped-config")
        self.assertEqual(entry["verdict"], "PASS")

    def test_append_records_each_run_once(self) -> None:
        run = ui_run(self.root, "ios-xcui-smoke-20261016-180000-cccc", passed=True)
        entry = LEDGER.entry_for(run)
        entry["runDirectory"] = "build/artifacts/ui-tests/ios/x"
        self.assertTrue(LEDGER.append(self.root, entry))
        self.assertFalse(LEDGER.append(self.root, entry))
        self.assertEqual(len(LEDGER.recorded(self.root)), 1)

    def test_backfill_and_kpi(self) -> None:
        ui_run(self.root, "ios-xcui-smoke-20261016-180000-dddd", passed=True)
        ui_run(self.root, "ios-xcui-smoke-20261016-190000-eeee", passed=False,
               log="error: Lost connection to the test manager service\n")
        self.assertEqual(LEDGER.main(["--root", str(self.root), "backfill"]), 0)
        now = dt.datetime(2026, 10, 18, tzinfo=dt.timezone.utc)
        summary = LEDGER.kpi(LEDGER.recorded(self.root), 30, now=now)["lanes"]["ios-ui-smoke"]
        self.assertEqual((summary["runs"], summary["passed"]), (2, 1))
        self.assertEqual(summary["failedMinuteShare"], 0.5)
        self.assertEqual(summary["infrastructure"], {"test-runner-lost": 1})
        self.assertEqual(LEDGER.kpi(LEDGER.recorded(self.root), 1, now=now)["lanes"], {})

    def test_recording_never_fails_the_lane(self) -> None:
        self.assertEqual(LEDGER.main(["--root", str(self.root), "record", str(self.root / "missing")]), 0)
        self.assertEqual(LEDGER.recorded(self.root), [])


if __name__ == "__main__":
    unittest.main()
