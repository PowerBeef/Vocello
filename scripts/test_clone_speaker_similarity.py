#!/usr/bin/env python3
"""Offline fixtures for the speaker-similarity dev-lane metric.

Everything below the embedding-backend boundary is exercised with injected
embeddings; no torch/speechbrain dependency is required or imported.
"""

from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

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


if __name__ == "__main__":
    unittest.main()
