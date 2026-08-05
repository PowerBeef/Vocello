#!/usr/bin/env python3
"""Unit tests for scripts/build_emotion_reference_bank.py.

Everything below the backend boundary runs with injected scorers and a fake
generation runner — no torch, no speechbrain, no CLI. The selection contract
under test: emotion criterion first (SER agreement; whisper by voiced-fraction
drop), then nearest-to-anchor identity, never peak expressiveness; and the
generation plan must never use the silent no-stream path (CM-7).
"""
from __future__ import annotations

import json
import os
import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from build_emotion_reference_bank import (
    WHISPER_VOICED_DELTA_MAX,
    enrollment_plan,
    plan_generation,
    run_generation,
    sanitized_persona,
    score_candidates,
    select_winners,
    voice_name,
    write_manifest,
)


def plan(work_dir: pathlib.Path, emotions=("happy", "whisper"), candidates=2):
    instructions = {emotion: f"Speak {emotion}." for emotion in emotions}
    return plan_generation(
        work_dir, "A narrator.", "The transcript.", list(emotions),
        instructions, candidates, 42_000,
    )


class GenerationPlanTests(unittest.TestCase):
    def test_plan_streams_and_uses_distinct_seeds(self) -> None:
        entries = plan(pathlib.Path("/tmp/bank"))
        for entry in entries:
            self.assertNotIn("--no-stream", entry["arguments"])  # CM-7
            self.assertIn("--seed", entry["arguments"])
        seeds = [entry["seed"] for entry in entries]
        self.assertEqual(len(seeds), len(set(seeds)))
        anchors = [entry for entry in entries if entry["kind"] == "anchor"]
        self.assertEqual(len(anchors), 3)
        for anchor in anchors:
            self.assertNotIn("--delivery", anchor["arguments"])
        candidates = [entry for entry in entries if entry["kind"] == "candidate"]
        for candidate in candidates:
            self.assertIn("--delivery", candidate["arguments"])

    def test_anchor_retries_then_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            work = pathlib.Path(temporary)
            entries = plan(work)

            calls: list[str] = []

            def runner_never_writes(arguments: list[str]) -> bool:
                calls.append(arguments[arguments.index("--out") + 1])
                return True  # exit 0 but no file — the CM-7 shape

            with self.assertRaisesRegex(RuntimeError, "anchor generation failed"):
                run_generation(entries, runner_never_writes)
            self.assertEqual(len(calls), 3)

    def test_candidate_failures_are_tolerated_and_reported(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            work = pathlib.Path(temporary)
            entries = plan(work)

            def runner(arguments: list[str]) -> bool:
                out = pathlib.Path(arguments[arguments.index("--out") + 1])
                if "whisper" in out.name and out.name.endswith("0.wav"):
                    return False  # one QC casualty
                out.write_bytes(b"RIFFfake")
                return True

            anchor, generated, failed = run_generation(entries, runner)
            self.assertTrue(anchor.endswith("anchor_s42000.wav"))
            self.assertEqual(len(failed), 1)
            self.assertEqual(failed[0]["emotion"], "whisper")
            self.assertEqual(len(generated), 3)


class SelectionTests(unittest.TestCase):
    @staticmethod
    def scored_rows():
        def row(emotion, seed, top, prob, identity, voiced_delta):
            agreement = None if emotion == "whisper" else top == emotion
            return {
                "emotion": emotion,
                "seed": seed,
                "path": f"/work/{emotion}_s{seed}.wav",
                "ser": {"topEmotion": top, "topProbability": prob, "agreement": agreement},
                "identityCosine": identity,
                "identityBand": "acceptable",
                "voicedFrac": 0.6,
                "voicedFracDelta": voiced_delta,
                "f0StdDelta": 1.0,
            }

        return [
            # happy: two agreeing candidates; the *more anchor-like* one wins
            # even though the other has the higher SER probability.
            row("happy", 1, "happy", 0.95, 0.55, 0.01),
            row("happy", 2, "happy", 0.70, 0.72, 0.02),
            row("happy", 3, "surprised", 0.90, 0.90, 0.00),  # ineligible
            # sad: nothing agrees.
            row("sad", 4, "neutral", 0.80, 0.80, 0.00),
            # whisper: judged by voiced-fraction drop, not SER.
            row("whisper", 5, "sad", 0.40, 0.60, -0.20),
            row("whisper", 6, "sad", 0.45, 0.75, -0.01),  # not whispered enough
        ]

    def test_selection_filters_then_prefers_anchor_identity(self) -> None:
        selection = select_winners(self.scored_rows(), ["happy", "sad", "whisper"])
        self.assertEqual(selection["happy"]["winner"]["seed"], 2)
        self.assertEqual(selection["happy"]["eligibleCount"], 2)
        self.assertIsNone(selection["sad"]["winner"])
        self.assertEqual(selection["sad"]["reason"], "no_eligible_candidate")
        self.assertEqual(selection["whisper"]["winner"]["seed"], 5)
        self.assertIn(str(WHISPER_VOICED_DELTA_MAX), selection["whisper"]["criterion"])

    def test_score_candidates_pairs_against_the_anchor(self) -> None:
        embeddings = {
            "/work/anchor.wav": [1.0, 0.0],
            "/work/happy_s1.wav": [1.0, 0.0],
            "/work/happy_s2.wav": [0.0, 1.0],
        }
        metrics = {
            # The analyzer's real flat key is f0_voiced_frac; one row uses the
            # bare fallback so the compatibility path stays covered.
            "/work/anchor.wav": {"f0_voiced_frac": 0.70, "f0_std_hz": 20.0},
            "/work/happy_s1.wav": {"f0_voiced_frac": 0.65, "f0_std_hz": 26.0},
            "/work/happy_s2.wav": {"voiced_frac": 0.72, "f0_std_hz": 31.0},
        }
        candidates = [
            {"emotion": "happy", "seed": 1, "path": "/work/happy_s1.wav"},
            {"emotion": "happy", "seed": 2, "path": "/work/happy_s2.wav"},
        ]
        scored = score_candidates(
            "/work/anchor.wav",
            candidates,
            classify=lambda path: {"happy": 0.9, "sad": 0.1},
            embed=lambda path: embeddings[path],
            analyze=lambda path: metrics[path],
        )
        self.assertEqual(scored[0]["identityCosine"], 1.0)
        self.assertEqual(scored[1]["identityCosine"], 0.0)
        self.assertEqual(scored[0]["voicedFracDelta"], -0.05)
        self.assertEqual(scored[0]["f0StdDelta"], 6.0)
        self.assertTrue(all(row["ser"]["agreement"] for row in scored))


class NamingAndManifestTests(unittest.TestCase):
    def test_voice_names_and_persona_sanitisation(self) -> None:
        self.assertEqual(voice_name("Warm  Narrator", None), "Warm  Narrator")
        self.assertEqual(voice_name("Warm Narrator", "angry"), "Warm Narrator (Angry)")
        self.assertEqual(sanitized_persona("  Warm   Narrator  "), "Warm Narrator")
        with self.assertRaises(ValueError):
            sanitized_persona("bad/name")
        with self.assertRaises(ValueError):
            sanitized_persona("   ")

    def test_enrollment_plan_covers_anchor_and_winners_only(self) -> None:
        selection = {
            "happy": {"winner": {"path": "/work/happy_s2.wav", "seed": 2}},
            "sad": {"winner": None, "reason": "no_eligible_candidate"},
        }
        plan = enrollment_plan("Warm Narrator", "/work/anchor.wav", "T.", selection)
        names = [entry["name"] for entry in plan]
        self.assertEqual(names, ["Warm Narrator", "Warm Narrator (Happy)"])
        self.assertTrue(all(entry["transcript"] == "T." for entry in plan))

    def test_manifest_writes_atomically(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = pathlib.Path(temporary) / "bank-manifest.json"
            write_manifest(path, {"bankVersion": 1})
            self.assertEqual(json.loads(path.read_text()), {"bankVersion": 1})
            self.assertEqual(
                [p.name for p in pathlib.Path(temporary).glob(".emotion-bank-*")], []
            )


if __name__ == "__main__":
    unittest.main()
