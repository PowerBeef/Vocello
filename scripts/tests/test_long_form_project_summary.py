"""Exercise the UI runner's local long-form summary with synthetic manifest durations.

The shipped `summarize_long_form_project_if_present` of scripts/ui_test.sh runs in bash
(scripts/tests/shell_stubs.py) against a sandbox HOME; no model, native UI or personal
Application Support directory is involved.
"""
from __future__ import annotations

import json
import unittest

from shell_stubs import UIFunctionShell, quote

FUNCTION = "summarize_long_form_project_if_present"


class LongFormProjectSummaryTests(unittest.TestCase):
    def summarize(self, log: str, audio_seconds: int) -> tuple[int, str | None]:
        shell = UIFunctionShell(self)
        outputs = shell.home / "Library/Application Support/QwenVoice-Debug/outputs/CustomVoice"
        outputs.mkdir(parents=True)
        (outputs / "long_form_manifest_fixture.json").write_text(json.dumps({
            "assembly": {"outputFrameCount": audio_seconds * 24_000, "sampleRate": 24_000},
            "execution": {"segments": [{}]},
        }))
        run = shell.path / "run with spaces"
        run.mkdir()
        (run / "xcodebuild.log").write_text(log)
        completed = shell.run((FUNCTION,), f"{FUNCTION} {quote(run)}\n")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        summary = run / "long-form-project-summary.txt"
        return completed.returncode, summary.read_text() if summary.exists() else None

    def test_rtf_uses_wall_seconds_per_audio_second(self) -> None:
        for audio_seconds, expected in [(20, "0.50"), (5, "2.00"), (0, "0.00")]:
            with self.subTest(audio_seconds=audio_seconds):
                _, summary = self.summarize("Test Case started\nLONGFORM_WALL_SECONDS=10\n", audio_seconds)
                self.assertIn(f"project RTF {expected}", summary)

    def test_a_log_without_the_long_form_token_writes_nothing_and_never_fails_the_lane(self) -> None:
        status, summary = self.summarize("Test Case started\n", 20)
        self.assertEqual(status, 0)
        self.assertIsNone(summary)


if __name__ == "__main__":
    unittest.main()
