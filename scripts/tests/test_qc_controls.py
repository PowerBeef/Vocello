"""Human-speech controls: the manifest, the report, and their exclusion from fit and queue."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from qc import controls, fit, lanes, store  # noqa: E402
from qc.store import Layout  # noqa: E402


def corpus(root: Path, speakers: int, per_speaker: int, language: str = "french") -> dict:
    clips = []
    for speaker in range(speakers):
        for index in range(per_speaker):
            clip_id = f"s{speaker}-c{index}"
            path = root / "wav" / f"{clip_id}.wav"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"RIFF")
            clips.append({"clipID": clip_id, "wavPath": f"wav/{clip_id}.wav", "wavSHA256": f"{speaker:02d}{index:062d}",
                          "speaker": f"spk{speaker}", "language": language, "text": "Une phrase lue.",
                          "durationSeconds": 6.0, "clippedSamples": 0})
    clips.append(dict(clips[0], clipID="too-long", durationSeconds=40.0))
    clips.append(dict(clips[0], clipID="clipped", clippedSamples=12))
    return {"clips": clips}


class ManifestTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.manifest = corpus(self.root, speakers=6, per_speaker=4)

    def tearDown(self):
        self.directory.cleanup()

    def build(self, **kwargs):
        with mock.patch.object(controls, "_manifest", return_value=(self.manifest, self.root)):
            return controls.build_manifest(["mls:french"], **kwargs)

    def test_a_deterministic_spread_over_speakers_marked_control(self):
        first = self.build(per_language=10, per_speaker=2)
        self.assertEqual(first, self.build(per_language=10, per_speaker=2))
        takes = first["takes"]
        self.assertEqual(len(takes), 10)
        speakers = [take["family"] for take in takes]
        self.assertTrue(all(speakers.count(family) <= 2 for family in speakers))
        self.assertEqual(len(set(speakers)), 6)  # every speaker once before any twice
        for take in takes:
            self.assertTrue(take["control"])
            self.assertEqual((take["mode"], take["cell"], take["language"]), ("human", "control", "french"))
            self.assertTrue(take["family"].startswith("human:mls:"))
            self.assertNotIn(take["takeID"], ("human-mls-too-long", "human-mls-clipped"))
        self.assertNotEqual(first, self.build(per_language=10, per_speaker=2, seed=1))

    def test_too_few_clips_is_refused(self):
        with self.assertRaisesRegex(controls.ControlsError, "usable clips"):
            self.build(per_language=13, per_speaker=2)  # 6 speakers x 2
        with self.assertRaisesRegex(controls.ControlsError, "<corpus>:<language>"):
            controls.build_manifest(["mls"])


class ReportAndExclusionTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.layout = Layout(Path(self.directory.name))
        self.layout.config.mkdir(parents=True)
        (self.layout.config / "detectors.json").write_text((ROOT / "config/qc/detectors.json").read_text())

    def tearDown(self):
        self.directory.cleanup()

    def write_run(self, run_id: str, lane: str, takes: list[tuple[str, str, bool, list[str], float]]):
        directory = self.layout.runs / run_id
        directory.mkdir(parents=True)
        store.write_json_atomic(directory / "flags.json", {"lane": lane, "takes": [
            dict({"token": token, "language": language, "flags": [{"detector": d} for d in detectors]},
                 **({"control": True} if control else {}))
            for token, language, control, detectors, _ in takes]})
        store.write_json_atomic(directory / "features.json", {"lane": lane, "models": {}, "takes": [
            {"token": token, "language": language, "features": {"signal.clicks": {"value": clicks}}}
            for token, language, _, _, clicks in takes]})

    def test_flag_rates_and_features_on_controls_against_generated_takes(self):
        self.write_run("controls-1", controls.CONTROLS_LANE, [
            ("c1", "french", True, ["content.phoneme"], 3.0), ("c2", "french", True, [], 1.0),
            ("c3", "english", True, [], 0.0), ("c4", "english", True, [], 0.0)])
        self.write_run("pool-1", "pool", [("g1", "french", False, ["content.phoneme", "pause.anomalous"], 9.0),
                                          ("g2", "french", False, [], 7.0)])
        document = controls.report(self.layout, ["controls-1"], ["pool-1"])
        self.assertEqual(document["takes"], {"controls": 4, "generated": 2})
        phoneme = document["flagRates"]["controls"]["content.phoneme"]
        self.assertEqual((phoneme["french"]["rate"], phoneme["english"]["rate"], phoneme["*"]["rate"]), (0.5, 0.0, 0.25))
        self.assertEqual(document["flagRates"]["generated"]["pause.anomalous"]["french"]["rate"], 0.5)
        self.assertEqual(document["features"]["controls"]["signal.clicks"]["french"]["p50"], 2.0)
        lines = controls.format_report(document)
        self.assertTrue(any(line.startswith("! content.phoneme") and "french" in line for line in lines))
        with self.assertRaisesRegex(controls.ControlsError, "no control take"):
            controls.report(self.layout, ["pool-1"], [])

    def test_fit_and_queue_leave_the_controls_lane_out(self):
        self.write_run("pool-1", "pool", [("g1", "french", False, [], 1.0)])
        self.write_run("controls-1", controls.CONTROLS_LANE, [("c1", "french", True, [], 1.0)])
        rows, _, _ = fit.feature_rows(self.layout)
        self.assertEqual(set(rows), {"g1"})
        rows, _, _ = fit.feature_rows(self.layout, ["controls-1"])  # named on purpose: read
        self.assertEqual(set(rows), {"c1"})
        newest = [path.name for path in lanes.lane_runs(self.layout)]
        self.assertEqual(sorted(newest), ["controls-1", "pool-1"])
        with mock.patch.object(lanes, "lane_runs", return_value=[self.layout.runs / "pool-1",
                                                                 self.layout.runs / "controls-1"]):
            with self.assertRaises(Exception) as caught:  # the queue reads pool-1 (no takes.json here)
                lanes.queue(self.layout, 1)
            self.assertIn("pool-1", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
