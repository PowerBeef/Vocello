"""Worker lifecycle and measurement decisions without probing real host processes."""
from __future__ import annotations

import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import active_workers as workers


class ActiveWorkerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.identity = {"pid": 43210, "started": "Sat Oct 10 12:00:00 2026"}

    def event(self, event: str, agent: str = "", session: str = "current") -> dict:
        return {"hook_event_name": event, "session_id": session, "agent_id": agent}

    def apply(self, event: str, agent: str = "", session: str = "current") -> None:
        workers.lifecycle(self.event(event, agent, session), base=self.base, identity=self.identity)

    def inspect(self, pid: int) -> dict:
        return {**self.identity, "pid": pid, "parent": 1, "command": "/Applications/Codex.app/bin/codex"}

    def snapshot(self, session: str = "current", inspect=None) -> dict:
        return workers.snapshot(base=self.base, inspect=inspect or self.inspect, session=workers.key(session))

    def test_start_stop_and_repeated_stop_preserve_session_tracking(self) -> None:
        self.apply("SessionStart")
        self.assertTrue(self.snapshot()["trackingAvailable"])
        self.apply("SubagentStart", "review")
        self.assertEqual(self.snapshot()["activeWorkers"], 1)
        self.apply("SubagentStop", "review")
        self.apply("SubagentStop", "review")
        self.assertEqual(self.snapshot()["activeWorkers"], 0)
        self.assertTrue(self.snapshot()["trackingAvailable"])

    def test_ending_root_session_does_not_claim_its_worker_stopped(self) -> None:
        self.apply("SubagentStart", "editing")
        self.apply("SessionEnd")
        report = self.snapshot()
        self.assertFalse(report["trackingAvailable"])
        self.assertEqual(report["activeWorkers"], 1)
        self.apply("SubagentStop", "editing")
        self.assertEqual(self.snapshot()["activeWorkers"], 0)

    def test_other_session_cannot_establish_current_hook_activation(self) -> None:
        self.apply("SessionStart", session="other")
        self.apply("SubagentStart", "other-worker", session="other")
        report = self.snapshot()
        self.assertFalse(report["trackingAvailable"])
        self.assertEqual(report["activeWorkers"], 1, "activity is host-wide even when activation is scoped")
        self.apply("SessionStart")
        with patch.dict(os.environ, {"QVOICE_WORKER_SESSION": workers.key("current")}):
            self.assertTrue(workers.snapshot(base=self.base, inspect=self.inspect)["trackingAvailable"])
        self.assertFalse(workers.snapshot(base=self.base, inspect=self.inspect, session="")["trackingAvailable"])

    def test_dead_reused_and_wrong_command_ownership_are_stale(self) -> None:
        self.apply("SubagentStart", "review")
        for actual in (None, {**self.inspect(43210), "started": "different start"},
                       {**self.inspect(43210), "command": "/usr/bin/python3"}):
            with self.subTest(actual=actual):
                report = self.snapshot(inspect=lambda pid: actual)
                self.assertEqual(report["activeWorkers"], 0)
                self.assertEqual(report["staleRecords"], 2)
                self.assertEqual(report["unknownRecords"], 0)
                self.assertFalse(report["trackingAvailable"])

    def test_unreadable_ownership_is_unknown_instead_of_idle(self) -> None:
        self.apply("SessionStart")
        with patch.object(workers, "process", side_effect=RuntimeError("unavailable")) as inspect:
            report = workers.snapshot(base=self.base, inspect=inspect, session=workers.key("current"))
        self.assertEqual(report["unknownRecords"], 1)
        self.assertFalse(report["trackingAvailable"])
        (self.base / "bad.json").write_text("not JSON")
        report = self.snapshot()
        self.assertEqual(report["unknownRecords"], 1)
        self.assertFalse(report["trackingAvailable"])

    def test_registration_failure_invalidates_receipt_until_matching_stop(self) -> None:
        self.apply("SessionStart")
        workers.invalidate(self.event("SubagentStart", "failed"), base=self.base)
        report = self.snapshot()
        self.assertEqual(report["unknownRecords"], 1)
        self.assertFalse(report["trackingAvailable"])
        self.apply("SessionStart")
        self.assertFalse(self.snapshot()["trackingAvailable"], "a fresh root receipt cannot hide a live error")
        self.apply("SubagentStop", "different")
        self.assertEqual(self.snapshot()["unknownRecords"], 1)
        self.apply("SubagentStop", "failed")
        self.assertTrue(self.snapshot()["trackingAvailable"])

    def test_invalid_event_identity_does_not_create_worker(self) -> None:
        for payload in ({"hook_event_name": "SessionStart"}, self.event("SubagentStart"),
                        self.event("SubagentStop")):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                workers.lifecycle(payload, base=self.base, identity=self.identity)
        self.assertEqual(self.snapshot()["activeWorkers"], 0)

    def test_successful_session_start_recovers_only_its_own_start_error(self) -> None:
        self.apply("SessionStart")
        workers.invalidate(self.event("SessionStart"), base=self.base)
        self.assertEqual(self.snapshot()["unknownRecords"], 1)
        self.apply("SessionStart")
        self.assertTrue(self.snapshot()["trackingAvailable"])
        workers.invalidate(self.event("SubagentStart", "unresolved"), base=self.base)
        self.apply("SessionStart")
        self.assertFalse(self.snapshot()["trackingAvailable"])
        self.assertEqual(self.snapshot()["unknownRecords"], 1)

    def test_marker_names_hash_session_and_agent_without_storing_agent_text(self) -> None:
        self.apply("SubagentStart", "private-agent")
        files = list(self.base.glob("*.json"))
        self.assertEqual(len(files), 2)
        for file in files:
            self.assertNotIn("private-agent", file.name + file.read_text())
            self.assertNotIn('"session": "current"', file.read_text())

    def test_directory_override_requires_absolute_path(self) -> None:
        with patch.dict(os.environ, {"QVOICE_WORKER_DIRECTORY": str(self.base)}):
            self.assertEqual(workers.directory(), self.base)
        with patch.dict(os.environ, {"QVOICE_WORKER_DIRECTORY": "relative"}), self.assertRaises(ValueError):
            workers.directory()

    def test_process_parser_distinguishes_absence_unavailable_and_valid_owner(self) -> None:
        valid = subprocess.CompletedProcess([], 0, " 1 Sat Oct 10 12:00:00 2026 /opt/bin/codex\n", "")
        with patch.object(workers.subprocess, "run", return_value=valid):
            self.assertEqual(workers.process(43210), {**self.identity, "parent": 1, "command": "/opt/bin/codex"})
        with patch.object(workers.subprocess, "run", return_value=subprocess.CompletedProcess([], 1, "", "")):
            self.assertIsNone(workers.process(43210))
        for result in (subprocess.CompletedProcess([], 1, "", "denied"),
                       subprocess.CompletedProcess([], 0, "malformed", "")):
            with patch.object(workers.subprocess, "run", return_value=result), self.assertRaises(RuntimeError):
                workers.process(43210)

    def test_owner_walks_ancestors_and_rejects_missing_codex_owner(self) -> None:
        with patch.object(workers.os, "getppid", return_value=7), patch.object(workers, "process", side_effect=[
            {"pid": 7, "parent": 8, "started": "shell", "command": "/bin/bash"},
            {**self.identity, "parent": 1, "command": "/opt/bin/codex"},
        ]):
            self.assertEqual(workers.owner(), self.identity)
        with patch.object(workers.os, "getppid", return_value=7), patch.object(workers, "process", return_value=None), \
                self.assertRaises(RuntimeError):
            workers.owner()


class ActiveWorkerCommandTests(unittest.TestCase):
    def invoke(self, report: dict, *args: str, lead_only: str = "") -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with patch.object(workers, "snapshot", return_value=report), \
                patch.object(sys, "argv", ["active_workers.py", *args]), \
                patch.dict(os.environ, {"QVOICE_LEAD_ONLY": lead_only}), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            status = workers.main()
        return status, out.getvalue(), err.getvalue()

    def test_measurement_branch_decisions(self) -> None:
        base = {"trackingAvailable": True, "activeWorkers": 0, "unknownRecords": 0, "staleRecords": 0}
        cases = [
            (base, [], "", 0, ""),
            ({**base, "activeWorkers": 1}, [], "1", 1, "active-workers(1)"),
            ({**base, "activeWorkers": 1}, ["--agents-allowed"], "", 0, "agents:1(allowed)"),
            ({**base, "trackingAvailable": False}, [], "", 2, "tracking unavailable"),
            ({**base, "trackingAvailable": False}, [], "1", 0, "lead-only execution declared"),
            ({**base, "unknownRecords": 1}, ["--agents-allowed"], "1", 2, "unreadable ownership"),
        ]
        for report, options, lead_only, expected, message in cases:
            with self.subTest(report=report, options=options, lead_only=lead_only):
                status, _, error = self.invoke(report, "check", *options, lead_only=lead_only)
                self.assertEqual(status, expected, error)
                self.assertIn(message, error)

    def test_status_preserves_inventory_without_running_a_lane(self) -> None:
        report = {"trackingAvailable": False, "activeWorkers": 2, "unknownRecords": 1, "staleRecords": 3}
        status, output, _ = self.invoke(report, "status")
        self.assertEqual(status, 0)
        self.assertEqual(json.loads(output), report)


if __name__ == "__main__":
    unittest.main()
