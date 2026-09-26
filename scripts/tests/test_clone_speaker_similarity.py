#!/usr/bin/env python3
"""Offline fixtures for the speaker-similarity dev-lane metric.

Everything below the embedding-backend boundary is exercised with injected
embeddings; no torch/speechbrain dependency is required or imported.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import clone_speaker_similarity as sim


class CloneSpeakerSimilarityTests(unittest.TestCase):
    def test_cosine_similarity_bounds_and_errors(self) -> None:
        self.assertAlmostEqual(sim.cosine_similarity([1, 0], [1, 0]), 1.0)
        self.assertAlmostEqual(sim.cosine_similarity([1, 0], [0, 1]), 0.0)
        self.assertAlmostEqual(sim.cosine_similarity([1, 0], [-1, 0]), -1.0)
        with self.assertRaises(ValueError):
            sim.cosine_similarity([1, 0], [1])
        with self.assertRaises(ValueError):
            sim.cosine_similarity([], [])
        with self.assertRaises(ValueError):
            sim.cosine_similarity([0, 0], [1, 0])

    def test_advisory_bands_follow_profile(self) -> None:
        profile = sim.load_similarity_profile(None)
        self.assertEqual(sim.advisory_band(0.75, profile), "strong")
        self.assertEqual(sim.advisory_band(0.60, profile), "strong")
        self.assertEqual(sim.advisory_band(0.50, profile), "acceptable")
        self.assertEqual(sim.advisory_band(0.20, profile), "weak")

    def test_profile_override_and_inverted_bands_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            override = Path(tmp) / "profile.json"
            override.write_text(json.dumps({"strongMinimum": 0.8, "acceptableMinimum": 0.6}))
            profile = sim.load_similarity_profile(str(override))
            self.assertEqual(sim.advisory_band(0.7, profile), "acceptable")

            inverted = Path(tmp) / "inverted.json"
            inverted.write_text(json.dumps({"strongMinimum": 0.4, "acceptableMinimum": 0.6}))
            with self.assertRaises(ValueError):
                sim.load_similarity_profile(str(inverted))

    def test_analyze_takes_uses_basenames_and_aggregates(self) -> None:
        embeddings = {
            "/private/ref.wav": [1.0, 0.0],
            "/private/strong.wav": [0.9, 0.1],
            "/private/weak.wav": [0.1, 0.9],
        }
        result = sim.analyze_takes(
            "/private/ref.wav",
            ["/private/strong.wav", "/private/weak.wav"],
            embeddings.__getitem__,
            sim.load_similarity_profile(None),
        )
        self.assertTrue(result["advisory"])
        self.assertEqual(result["reference"], "ref.wav")
        self.assertEqual([row["take"] for row in result["takes"]], ["strong.wav", "weak.wav"])
        self.assertNotIn("/private", json.dumps(result))
        self.assertEqual(result["takes"][0]["band"], "strong")
        self.assertEqual(result["takes"][1]["band"], "weak")
        self.assertEqual(result["aggregate"]["count"], 2)
        self.assertEqual(result["aggregate"]["weakCount"], 1)
        self.assertLessEqual(result["aggregate"]["minimum"], result["aggregate"]["median"])
        self.assertLessEqual(result["aggregate"]["median"], result["aggregate"]["maximum"])
        self.assertEqual(result["backend"]["source"], sim.ECAPA_SOURCE)
        self.assertEqual(len(sim.ECAPA_REVISION), 40)

    def test_the_report_records_what_the_loader_verified(self) -> None:
        loaded = {
            "snapshotFileDigests": {"embedding_model.ckpt": "a" * 64, "hyperparams.yaml": "b" * 64},
            "runtimeVersions": {"speechbrain": "fixture", "torch": "fixture", "numpy": "fixture"},
            "hostProfile": {"system": "Darwin", "machine": "arm64", "modelIdentifier": "Fixture1,1"},
        }
        embeddings = {"ref.wav": [1.0, 0.0], "take.wav": [0.9, 0.1]}
        embedder = sim.EcapaEmbedder(embeddings.__getitem__, loaded)
        result = sim.analyze_takes("ref.wav", ["take.wav"], embedder, sim.BUILTIN_PROFILE)
        self.assertEqual(result["backend"], {
            "source": sim.ECAPA_SOURCE, "revision": sim.ECAPA_REVISION,
            "preprocessing": sim.ECAPA_PREPROCESSING, **loaded,
        })
        self.assertEqual(sim.backend_identity(embedder), result["backend"])

    def test_analyze_takes_requires_at_least_one_take(self) -> None:
        with self.assertRaises(ValueError):
            sim.analyze_takes("ref.wav", [], lambda _: [1.0], sim.BUILTIN_PROFILE)

    def test_sidecar_write_is_atomic_and_round_trips(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "nested" / "speaker-sim.json"
            payload = {"metric": "speaker-cosine-similarity", "advisory": True}
            sim.write_sidecar(target, payload)
            self.assertEqual(json.loads(target.read_text()), payload)
            leftovers = [p for p in target.parent.iterdir() if p.name.startswith(".speaker-sim-")]
            self.assertEqual(leftovers, [])

    # -- audit #103: calibration code fixes ---------------------------------

    def test_aggregate_median_is_a_true_median(self) -> None:
        embeddings = {"ref": [1.0, 0.0]}
        for name, angle in (("a", 1.3694), ("b", 1.1593), ("c", 0.9273), ("d", 0.6435)):
            embeddings[name] = [math.cos(angle), math.sin(angle)]  # cosines .2 .4 .6 .8
        result = sim.analyze_takes("ref", ["a", "b", "c", "d"], embeddings.__getitem__, sim.BUILTIN_PROFILE)
        # The old upper median read 0.6 for an even count.
        self.assertAlmostEqual(result["aggregate"]["median"], 0.5, places=3)
        self.assertEqual(result["backend"]["preprocessing"],
                         {"sampleRateHz": 16_000, "resampler": "polyphase-kaiser5-v2"})

    def test_separation_reports_auc_and_eer_with_reproducible_intervals(self) -> None:
        clones = [0.814, 0.83, 0.845, 0.85, 0.862, 0.871]
        controls = [0.103, 0.390]
        report = sim.separation(clones, controls)
        self.assertEqual((report["positives"], report["negatives"]), (6, 2))
        self.assertEqual(report["auc"], 1.0)
        self.assertEqual(report["equalErrorRate"], 0.0)
        self.assertEqual(report["aucInterval95"], [1.0, 1.0])
        # Two controls (one cross-gender) cannot calibrate the bands.
        self.assertFalse(report["bandCalibrationReady"])
        self.assertEqual(report, sim.separation(clones, controls))

        overlapping = sim.separation([0.5, 0.6, 0.7], [0.55, 0.65, 0.2] + [0.1] * 5)
        self.assertTrue(overlapping["bandCalibrationReady"])
        self.assertAlmostEqual(overlapping["auc"], (1 + 2 + 3 + 3 * 5) / 24, places=4)
        self.assertGreater(overlapping["equalErrorRate"], 0.0)
        low, high = overlapping["aucInterval95"]
        self.assertLessEqual(low, overlapping["auc"])
        self.assertGreaterEqual(high, overlapping["auc"])
        self.assertIsNone(sim.separation([0.8], []))

    def test_equal_error_rate_at_the_crossing(self) -> None:
        eer, threshold = sim.equal_error_rate([0.4, 0.6, 0.8, 0.9], [0.1, 0.3, 0.5, 0.7])
        self.assertEqual(eer, 0.25)
        self.assertIn(threshold, (0.6, 0.7))

    def test_pinned_resampler_does_not_alias_like_linear_interpolation(self) -> None:
        import numpy as np
        from audio_resampling import RESAMPLER_VERSION

        self.assertEqual(sim.EMBEDDING_RESAMPLER, RESAMPLER_VERSION)
        rate, seconds = 24_000, 0.5
        time = np.arange(int(rate * seconds)) / rate
        in_band = 0.5 * np.sin(2 * np.pi * 1_000 * time)
        above_nyquist = 0.5 * np.sin(2 * np.pi * 11_000 * time)
        resampled = sim.resample_for_embedding(in_band, rate)
        self.assertEqual(resampled.size, 8_000)
        core = slice(400, -400)
        self.assertAlmostEqual(float(np.sqrt(np.mean(resampled[core] ** 2))), 0.5 / math.sqrt(2), delta=0.01)
        filtered = sim.resample_for_embedding(above_nyquist, rate)
        self.assertLess(float(np.sqrt(np.mean(filtered[core] ** 2))), 0.01)
        # The retired np.interp path folds the 11 kHz tone to 5 kHz at full strength.
        positions = np.linspace(0.0, above_nyquist.size - 1, 8_000)
        aliased = np.interp(positions, np.arange(above_nyquist.size), above_nyquist)
        self.assertGreater(float(np.sqrt(np.mean(aliased[core] ** 2))), 0.2)
        self.assertIs(sim.resample_for_embedding(in_band[:1600], 16_000).dtype, np.dtype(np.float32))

    def test_ecapa_snapshot_is_resolved_offline_only(self) -> None:
        calls = []

        def cached(**kwargs):
            calls.append(kwargs)
            return "/cache/ecapa"

        self.assertEqual(sim.pinned_ecapa_snapshot(cached), "/cache/ecapa")
        self.assertEqual(calls, [{"repo_id": sim.ECAPA_SOURCE, "revision": sim.ECAPA_REVISION,
                                  "local_files_only": True}])

        def missing(**_kwargs):
            raise OSError("not cached")

        with self.assertRaises(RuntimeError):
            sim.pinned_ecapa_snapshot(missing)


if __name__ == "__main__":
    unittest.main()
