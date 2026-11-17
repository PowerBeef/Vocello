#!/usr/bin/env python3
"""Tests for scripts/lib/iphone_mirroring.py over an injected command runner: nothing here reads
this Mac's processes or reaches a phone."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib import iphone_mirroring as mirroring  # noqa: E402

DEVICE = "00008150-FIXTURE-UDID"


class FakeRunner:
    def __init__(self, *, running: list[bool] | None = None, locked: bool | None = False) -> None:
        self.running = list(running if running is not None else [True])
        self.locked = locked
        self.calls: list[list[str]] = []

    def __call__(self, argv: list[str], **_: Any) -> subprocess.CompletedProcess[str]:
        self.calls.append(list(argv))
        name = Path(argv[0]).name
        if name == "pgrep":
            state = self.running.pop(0) if len(self.running) > 1 else self.running[0]
            return subprocess.CompletedProcess(argv, 0 if state else 1, "", "")
        if name == "osascript":
            return subprocess.CompletedProcess(argv, 0, "", "")
        if argv[-1] == "probe":
            payload = {"reachable": True, "identifier": DEVICE, "lock": {"deviceLocked": self.locked}}
            return subprocess.CompletedProcess(argv, 0, json.dumps(payload), "")
        raise AssertionError(f"unexpected command: {argv}")


class MirroringCase(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name) / "mirroring"


class StatusTests(MirroringCase):
    def test_status_reports_mirroring_and_lock_state_without_the_device_id(self) -> None:
        value = mirroring.status(FakeRunner(running=[True], locked=True))
        self.assertEqual(value, {"mirroringRunning": True, "phone": {"reachable": True, "deviceLocked": True}})
        self.assertNotIn(DEVICE, json.dumps(value))


class StopTests(MirroringCase):
    def test_stop_quits_by_bundle_id_and_waits_until_the_process_is_gone(self) -> None:
        run = FakeRunner(running=[True, True, False])
        mirroring.stop(run, wait_seconds=5, sleep=lambda _: None)
        quits = [call for call in run.calls if call[0] == "osascript"]
        self.assertEqual(len(quits), 1)
        self.assertIn(mirroring.APP_BUNDLE_ID, quits[0][-1])

    def test_stop_fails_when_mirroring_survives(self) -> None:
        with self.assertRaises(mirroring.Refusal):
            mirroring.stop(FakeRunner(running=[True]), wait_seconds=0, sleep=lambda _: None)

    def test_stop_does_nothing_when_mirroring_is_not_running(self) -> None:
        run = FakeRunner(running=[False])
        mirroring.stop(run, wait_seconds=0, sleep=lambda _: None)
        self.assertFalse([call for call in run.calls if call[0] == "osascript"])


class CommandLineTests(MirroringCase):
    def test_the_retired_record_commands_are_gone(self) -> None:
        """Mirroring is no test route since 2026-11-17: no session or capture records."""
        import contextlib
        import io
        for argv in (["session", "explore"], ["capture", "x", "--step", "look"]):
            with self.subTest(argv=argv), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as raised:
                    mirroring.main(argv, run=FakeRunner())
                self.assertEqual(raised.exception.code, 2)

    def test_status_json_from_the_command_line(self) -> None:
        import contextlib
        import io
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = mirroring.main(["status", "--json"], run=FakeRunner(running=[False], locked=False))
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out.getvalue())["mirroringRunning"], False)


if __name__ == "__main__":
    unittest.main()
