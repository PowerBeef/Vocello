"""scripts/analyze_playback_capture.py: the smoke lane's capture summary without the telemetry checker."""
import datetime as dt
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from lib import playback_capture as pc  # noqa: E402


class AnalyzePlaybackCaptureTests(unittest.TestCase):
    def _fixture(self, root: pathlib.Path, hole_ms: float = 0.0) -> tuple[pathlib.Path, pathlib.Path]:
        rate = 48_000
        t = np.arange(int(rate * 3.0)) / rate
        burst = ((t > 0.2) & (t < 2.7)).astype(float)
        world = 0.4 * np.sin(2 * np.pi * 440 * t) * burst * (1 + 0.3 * np.sin(2 * np.pi * 3 * t))
        outputs = root / "outputs"; (outputs / "CustomVoice").mkdir(parents=True)
        stamp = dt.datetime(2026, 9, 14, 9, 0, 0)
        pc.write_wav_int16(outputs / "CustomVoice" / (stamp.strftime("%Y%m%d_%H-%M-%S-") + "000_smoke.wav"), 24_000, pc.resample(world, rate, 24_000))
        captures = root / "playback-capture"; captures.mkdir()
        played = np.concatenate([np.zeros(int(rate * 0.137)), world * 0.7, np.zeros(rate)])
        if hole_ms:
            start = int(rate * 1.137); played[start:start + int(rate * hole_ms / 1000)] = 0.0
        pc.write_wav_float32(captures / "take-01-custom_smoke_warm-0.wav", rate, played)
        start_ms = stamp.timestamp() * 1000 - 1_000
        (captures / "take-01-custom_smoke_warm-0.json").write_text(json.dumps({
            "takeIndex": 1, "cell": "custom/smoke/warm#0", "status": "captured",
            "submitClickEpochMS": start_ms + 307, "captureStartEpochMS": start_ms, "stopEpochMS": start_ms + 6_000,
        }))
        (captures / "capture-run.json").write_text(json.dumps({"runID": "macos-xcui-smoke-test"}))
        return captures, outputs

    def _run(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, str(ROOT / "scripts/analyze_playback_capture.py"), *args],
                              capture_output=True, text=True, check=False)

    def test_a_clean_smoke_capture_is_summarized(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            captures, outputs = self._fixture(pathlib.Path(temp))
            result = self._run(str(captures), "--outputs-dir", str(outputs), "--gate")
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            summary = json.loads((captures / "summary.json").read_text())
            self.assertEqual(summary["runID"], "macos-xcui-smoke-test")
            self.assertEqual((summary["captured"], summary["expected"]), (1, 1))
            self.assertEqual(summary["takes"][0]["status"], "captured")
            self.assertGreaterEqual(summary["takes"][0]["metrics"]["playbackCaptureCoverage"], 0.99)
            self.assertEqual(summary["gate"]["failedTakes"], [])

    def test_a_dropout_fails_only_when_the_gate_is_requested(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            captures, outputs = self._fixture(pathlib.Path(temp), hole_ms=120)
            advisory = self._run(str(captures), "--outputs-dir", str(outputs))
            self.assertEqual(advisory.returncode, 0, advisory.stdout + advisory.stderr)
            self.assertIn("gate failures: [1]", advisory.stdout)
            gated = self._run(str(captures), "--outputs-dir", str(outputs), "--gate")
            self.assertEqual(gated.returncode, 1)

    def test_a_missing_directory_is_not_an_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            result = self._run(str(pathlib.Path(temp) / "nope"))
            self.assertEqual(result.returncode, 0)
            self.assertIn("no capture directory", result.stdout)


if __name__ == "__main__":
    unittest.main()
