#!/usr/bin/env python3
"""Clip-quality screen: deterministic onset detector, warn floor, separation statistics, no paths."""

from __future__ import annotations

import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest
import wave

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from delivery_analysis_cache import DeliveryAnalysisCache  # noqa: E402
import clip_quality_screen as screen_module  # noqa: E402
from clip_quality_screen import ScreenError, rank_auc, screen, spearman, step_burst  # noqa: E402


def _write(path: Path, samples: np.ndarray, rate: int = 24_000) -> None:
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1); output.setsampwidth(2); output.setframerate(rate)
        output.writeframes(struct.pack(f"<{len(samples)}h", *[int(v) for v in samples]))


def _tone(seconds: float = 1.0, rate: int = 24_000) -> np.ndarray:
    t = np.arange(int(rate * seconds)) / rate
    return np.rint(6000 * np.sin(2 * np.pi * 180 * t))


class ClipQualityScreenTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.clean = self.root / "clean.wav"
        _write(self.clean, _tone())
        # A plosive-onset cluster: twelve alternating quarter-scale steps inside 20 ms at 200 ms.
        cluster = _tone()
        start = int(24_000 * 0.2)
        for index in range(12):
            cluster[start + index] = 12000 if index % 2 == 0 else -12000
        self.cluster = self.root / "cluster.wav"
        _write(self.cluster, cluster)
        self.config = {"adapterID": "nisqa-v2", "modelID": "nisqa-fixture", "weightsSHA256": "a" * 64,
                       "warnFloor": {"mos": 3.81}}
        self.cache = DeliveryAnalysisCache(self.root / "cache")
        self.mos = {"clean.wav": 4.8, "cluster.wav": 4.7}

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _judge(self, *, wav_path: Path, config, cache, lock_root):
        with wave.open(str(wav_path)) as reader:
            frames = reader.getnframes()
        mos = self.mos[wav_path.name] - (0.9 if frames < 24_000 else 0.0)
        return ({"adapterID": "nisqa-v2", "outputs": {"mos": mos, "noisiness": 4.5, "discontinuity": 4.6,
                                                      "coloration": 4.4, "loudness": 4.5}}, False)

    def test_detector_finds_the_injected_cluster_and_nothing_in_the_clean_tone(self) -> None:
        self.assertEqual(step_burst(self.clean)[0], 0)
        count, start = step_burst(self.cluster)
        self.assertGreaterEqual(count, 8)
        self.assertAlmostEqual(start, 200.0, delta=2.0)

    def test_report_carries_floor_detector_separation_and_no_paths(self) -> None:
        report = screen(
            wav_paths=[self.clean, self.cluster], config=self.config, cache=self.cache,
            lock_root=self.root / "lock", onset_window_ms=300, adapter=self._judge,
        )
        rows = {row["take"]: row for row in report["rows"]}
        self.assertTrue(rows["cluster.wav"]["onsetCluster"])
        self.assertFalse(rows["clean.wav"]["onsetCluster"])
        self.assertFalse(rows["clean.wav"]["belowWarnFloor"])
        self.assertEqual(rows["clean.wav"]["onsetMOS"], 3.9)
        self.assertEqual(rows["clean.wav"]["onsetDeltaMOS"], 0.9)
        self.assertEqual(report["onsetClusterTakes"], 1)
        self.assertEqual(report["judge"]["warnFloorMOS"], 3.81)
        self.assertEqual([entry["score"] for entry in report["separation"]], ["mos", "onsetMOS", "onsetDeltaMOS"])
        mos_entry = report["separation"][0]
        self.assertEqual((mos_entry["clusterTakes"], mos_entry["cleanTakes"]), (1, 1))
        self.assertEqual(mos_entry["aucClusterScoresLower"], 1.0)
        self.assertIsNone(mos_entry["spearmanWithStepBurstCount"])
        serialized = json.dumps(report)
        self.assertNotIn(str(self.root), serialized)
        self.assertIn(rows["clean.wav"]["sha256"], serialized)

    def test_below_floor_takes_are_counted_and_bad_judges_fail_closed(self) -> None:
        self.mos["clean.wav"] = 3.2
        report = screen(wav_paths=[self.clean], config=self.config, cache=self.cache,
                        lock_root=self.root / "lock", adapter=self._judge)
        self.assertEqual(report["belowWarnFloor"], 1)
        self.assertTrue(report["rows"][0]["belowWarnFloor"])

        def broken(*, wav_path, config, cache, lock_root):
            return ({"adapterID": "nisqa-v2", "outputs": {"mos": float("nan")}}, False)

        with self.assertRaisesRegex(ScreenError, "no finite mos"):
            screen(wav_paths=[self.clean], config=self.config, cache=self.cache,
                   lock_root=self.root / "lock", adapter=broken)
        with self.assertRaisesRegex(ScreenError, "missing"):
            screen(wav_paths=[self.root / "absent.wav"], config=self.config, cache=self.cache,
                   lock_root=self.root / "lock", adapter=self._judge)

    def test_statistics_are_rank_based(self) -> None:
        self.assertEqual(rank_auc([1.0, 2.0], [3.0, 4.0]), 1.0)
        self.assertEqual(rank_auc([3.0], [3.0]), 0.5)
        self.assertIsNone(rank_auc([], [1.0]))
        self.assertEqual(spearman([1.0, 2.0, 3.0, 4.0], [10, 20, 30, 40]), 1.0)
        self.assertEqual(spearman([4.0, 3.0, 2.0, 1.0], [10, 20, 30, 40]), -1.0)
        self.assertIsNone(spearman([1.0, 1.0, 1.0], [1, 2, 3]))

    def test_config_must_be_a_prepared_judge_with_a_floor(self) -> None:
        path = self.root / "config.json"
        path.write_text(json.dumps({"adapterID": "distilhubert"}))
        with self.assertRaisesRegex(ScreenError, "nisqa-v2"):
            screen_module._read_config(path)
        path.write_text(json.dumps({"adapterID": "nisqa-v2"}))
        with self.assertRaisesRegex(ScreenError, "warn floor"):
            screen_module._read_config(path)


if __name__ == "__main__":
    unittest.main()
