"""Exercise the UI runner's local summary with synthetic manifest durations."""
from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
UI_RUNNER = ROOT / "scripts" / "ui_test.sh"


class LongFormProjectSummaryTests(unittest.TestCase):
    def test_rtf_uses_wall_seconds_per_audio_second(self) -> None:
        # Execute the embedded producer itself; no model, native UI or personal
        # Application Support directory is involved.
        function = UI_RUNNER.read_text().split(
            "summarize_long_form_project_if_present() {", 1
        )[1]
        program = function.split("<<'PY'\n", 1)[1].split("\nPY\n", 1)[0]
        for audio_seconds, expected in [(20, "0.50"), (5, "2.00"), (0, "0.00")]:
            with self.subTest(audio_seconds=audio_seconds), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                outputs = root / "outputs"
                outputs.mkdir()
                (outputs / "long_form_manifest_fixture.json").write_text(json.dumps({
                    "assembly": {"outputFrameCount": audio_seconds * 24_000, "sampleRate": 24_000},
                    "execution": {"segments": [{}]},
                }))
                run = root / "run with spaces"
                run.mkdir()
                summary = run / "long-form-project-summary.txt"
                def fixture_path(path: str) -> str:
                    return str(outputs if path.endswith("outputs/CustomVoice") else root / "diagnostics")

                with (
                    mock.patch.object(sys, "argv", ["summary", "10", str(summary), str(run)]),
                    mock.patch("os.path.expanduser", side_effect=fixture_path),
                    contextlib.redirect_stdout(io.StringIO()),
                ):
                    exec(compile(program, str(UI_RUNNER), "exec"), {})
                self.assertIn(f"project RTF {expected}", summary.read_text())


if __name__ == "__main__":
    unittest.main()
