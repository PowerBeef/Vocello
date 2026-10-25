#!/usr/bin/env python3
"""Tests for scripts/lib/iphone_mirroring.py over an injected command runner: nothing here reads
this Mac's processes, captures its screen or reaches a phone."""

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

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
DEVICE = "00008150-FIXTURE-UDID"


class FakeRunner:
    def __init__(self, *, running: list[bool] | None = None, windows: str = "4242",
                 locked: bool | None = False, apps: list[dict[str, Any]] | None = None,
                 capture_ok: bool = True) -> None:
        self.running = list(running if running is not None else [True])
        self.windows = windows
        self.locked = locked
        self.apps = apps
        self.capture_ok = capture_ok
        self.calls: list[list[str]] = []

    def __call__(self, argv: list[str], **_: Any) -> subprocess.CompletedProcess[str]:
        self.calls.append(list(argv))
        name = Path(argv[0]).name
        if name == "pgrep":
            state = self.running.pop(0) if len(self.running) > 1 else self.running[0]
            return subprocess.CompletedProcess(argv, 0 if state else 1, "", "")
        if name == "osascript":
            if "-l" in argv:
                return subprocess.CompletedProcess(argv, 0, self.windows + "\n", "")
            return subprocess.CompletedProcess(argv, 0, "", "")
        if name == "screencapture":
            if self.capture_ok:
                Path(argv[-1]).write_bytes(PNG)
            return subprocess.CompletedProcess(argv, 0 if self.capture_ok else 1, "", "")
        if name == "git":
            return subprocess.CompletedProcess(argv, 0, "0123456789abcdef\n", "")
        if name == "xcrun":
            if self.apps is None:
                return subprocess.CompletedProcess(argv, 1, "", "device not reachable")
            Path(argv[argv.index("--json-output") + 1]).write_text(json.dumps({"result": {"apps": self.apps}}))
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


class SessionTests(MirroringCase):
    def test_session_records_the_commit_and_installed_version_and_build(self) -> None:
        apps = [{"bundleIdentifier": mirroring.VOCELLO_BUNDLE_ID, "version": "3.0.0", "bundleVersion": "25"}]
        session = mirroring.start_session(self.root, "rf35 reinstall", FakeRunner(apps=apps),
                                          now="2026-10-25T17:05:20Z")
        self.assertEqual(session.name, "mirroring-20261025T170520Z-rf35-reinstall")
        record = json.loads((session / "session.json").read_text())
        self.assertEqual(record["installedVocello"], {"marketingVersion": "3.0.0", "buildNumber": "25"})
        self.assertEqual(record["sourceCommit"], "0123456789abcdef")
        self.assertEqual((self.root / "current-session").read_text().strip(), session.name)

    def test_session_marks_the_build_unverified_when_coredevice_cannot_read_it(self) -> None:
        session = mirroring.start_session(self.root, "explore", FakeRunner(apps=None))
        self.assertEqual(json.loads((session / "session.json").read_text())["installedVocello"], "unverified")


class CaptureTests(MirroringCase):
    def test_capture_writes_the_window_png_and_one_step_line(self) -> None:
        run = FakeRunner(apps=None)
        session = mirroring.start_session(self.root, "explore", run)
        first = mirroring.capture(self.root, "voice models", "opened Voice Models", "2 of 3 ready", run)
        second = mirroring.capture(self.root, "after install", "tapped Install", None, run)
        self.assertEqual((first["file"], second["file"]), ("001-voice-models.png", "002-after-install.png"))
        self.assertEqual((session / first["file"]).read_bytes(), PNG)
        lines = [json.loads(line) for line in (session / "steps.jsonl").read_text().splitlines()]
        self.assertEqual([line["step"] for line in lines], [1, 2])
        self.assertEqual(lines[0]["observed"], "2 of 3 ready")
        self.assertIn(["screencapture", "-x", "-o", "-l", "4242", str(session / first["file"])], run.calls)

    def test_capture_refuses_without_a_single_mirroring_window(self) -> None:
        for windows in ("", "11,12"):
            with self.subTest(windows=windows):
                run = FakeRunner(windows=windows, apps=None)
                mirroring.start_session(self.root / windows.replace(",", "-") , "explore", run)
                with self.assertRaises(mirroring.Refusal):
                    mirroring.capture(self.root / windows.replace(",", "-"), "x", "look", None, run)

    def test_capture_refuses_without_a_session_and_cleans_a_failed_capture(self) -> None:
        with self.assertRaises(mirroring.Refusal):
            mirroring.capture(self.root, "x", "look", None, FakeRunner())
        run = FakeRunner(capture_ok=False, apps=None)
        session = mirroring.start_session(self.root, "explore", run)
        with self.assertRaises(mirroring.Refusal):
            mirroring.capture(self.root, "x", "look", None, run)
        self.assertFalse(list(session.glob("*.png")))
        self.assertFalse((session / "steps.jsonl").exists())

    def test_records_hold_no_absolute_paths_or_device_identifiers(self) -> None:
        apps = [{"bundleIdentifier": mirroring.VOCELLO_BUNDLE_ID, "version": "3.0.0", "bundleVersion": "25"}]
        run = FakeRunner(apps=apps)
        session = mirroring.start_session(self.root, "explore", run)
        mirroring.capture(self.root, "home", "pressed Home", "Home Screen", run)
        for path in (session / "session.json", session / "steps.jsonl"):
            text = path.read_text()
            self.assertNotIn(DEVICE, text)
            self.assertNotIn(str(self.root), text)


class CommandLineTests(MirroringCase):
    def test_labels_need_a_letter_or_digit(self) -> None:
        with self.assertRaises(mirroring.Refusal):
            mirroring.slug("///")

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
