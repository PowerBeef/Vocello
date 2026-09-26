#!/usr/bin/env python3
"""Unit tests for scripts/build_emotion_reference_bank.py.

Everything below the backend boundary runs with injected scorers and a fake
generation runner — no torch, no speechbrain, no CLI. The selection contract
under test: emotion criterion first (paired delivery adherence against the
neutral anchor; whisper by voiced-fraction drop), then nearest-to-anchor
identity, never peak expressiveness; and the generation plan must never use
the silent no-stream path (CM-7).
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

# Analyzer-shaped metrics: a neutral anchor, a livelier take and a flatter one.
ANCHOR_METRICS = {
    "f0_median_hz": 120.0, "f0_range_hz": 60.0, "f0_range_semitones": 8.0, "f0_std_hz": 20.0,
    "f0_voiced_frac": 0.70, "rate_syllable_rate_hz": 4.0, "rate_cv": 0.3, "pause_ratio": 0.2,
    "energy_roughness": 0.1, "durationSec": 20.0,
}
LIVELY_METRICS = dict(
    ANCHOR_METRICS, f0_median_hz=140.0, f0_range_hz=90.0, f0_range_semitones=11.0, f0_std_hz=30.0,
    rate_syllable_rate_hz=4.6, energy_roughness=0.15, f0_voiced_frac=0.65,
)
FLAT_METRICS = dict(
    ANCHOR_METRICS, f0_median_hz=110.0, f0_range_hz=40.0, f0_range_semitones=5.0, f0_std_hz=12.0,
    rate_syllable_rate_hz=3.6, energy_roughness=0.08,
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
        def row(emotion, seed, adherent, arousal, identity, voiced_delta):
            return {
                "emotion": emotion,
                "seed": seed,
                "path": f"/work/{emotion}_s{seed}.wav",
                "deliveryAdherence": {"passed": adherent, "flags": [], "arousalScore": arousal},
                "identityCosine": identity,
                "identityBand": "acceptable",
                "voicedFrac": 0.6,
                "voicedFracDelta": voiced_delta,
                "f0StdDelta": 1.0,
            }

        return [
            # happy: two adherent candidates; the *more anchor-like* one wins
            # even though the other moved arousal further.
            row("happy", 1, True, 6.0, 0.55, 0.01),
            row("happy", 2, True, 2.0, 0.72, 0.02),
            row("happy", 3, False, -1.0, 0.90, 0.00),  # ineligible
            # sad: nothing adheres.
            row("sad", 4, False, 1.0, 0.80, 0.00),
            # whisper: judged by voiced-fraction drop, not the adherence verdict.
            row("whisper", 5, False, -1.0, 0.60, -0.20),
            row("whisper", 6, True, -1.0, 0.75, -0.01),  # not whispered enough
        ]

    def test_selection_filters_then_prefers_anchor_identity(self) -> None:
        selection = select_winners(self.scored_rows(), ["happy", "sad", "whisper"])
        self.assertEqual(selection["happy"]["winner"]["seed"], 2)
        self.assertEqual(selection["happy"]["eligibleCount"], 2)
        self.assertIsNone(selection["sad"]["winner"])
        self.assertEqual(selection["sad"]["reason"], "no_eligible_candidate")
        self.assertEqual(selection["whisper"]["winner"]["seed"], 5)
        self.assertIn(str(WHISPER_VOICED_DELTA_MAX), selection["whisper"]["criterion"])
        self.assertEqual(selection["happy"]["criterion"],
                         "paired delivery adherence against the neutral anchor")

    def test_score_candidates_pairs_against_the_anchor(self) -> None:
        embeddings = {
            "/work/anchor.wav": [1.0, 0.0],
            "/work/happy_s1.wav": [1.0, 0.0],
            "/work/happy_s2.wav": [0.0, 1.0],
            "/work/happy_s3.wav": [0.6, 0.8],
        }
        fallback = {key: value for key, value in LIVELY_METRICS.items() if key != "f0_voiced_frac"}
        metrics = {
            # The analyzer's real flat key is f0_voiced_frac; one row uses the
            # bare fallback so the compatibility path stays covered.
            "/work/anchor.wav": ANCHOR_METRICS,
            "/work/happy_s1.wav": LIVELY_METRICS,
            "/work/happy_s2.wav": {**fallback, "voiced_frac": 0.72},
            "/work/happy_s3.wav": FLAT_METRICS,
        }
        candidates = [
            {"emotion": "happy", "seed": 1, "path": "/work/happy_s1.wav"},
            {"emotion": "happy", "seed": 2, "path": "/work/happy_s2.wav"},
            {"emotion": "happy", "seed": 3, "path": "/work/happy_s3.wav"},
        ]
        scored = score_candidates(
            "/work/anchor.wav",
            candidates,
            embed=lambda path: embeddings[path],
            analyze=lambda path: metrics[path],
        )
        self.assertEqual(scored[0]["identityCosine"], 1.0)
        self.assertEqual(scored[1]["identityCosine"], 0.0)
        self.assertEqual(scored[0]["voicedFracDelta"], -0.05)
        self.assertEqual(scored[0]["f0StdDelta"], 10.0)
        # The paired, same-voice arousal and prosody deltas decide eligibility:
        # the livelier take adheres to happy, the flatter one does not.
        self.assertEqual(scored[1]["voicedFracDelta"], 0.02)
        self.assertTrue(scored[0]["deliveryAdherence"]["passed"])
        self.assertGreater(scored[0]["deliveryAdherence"]["arousalScore"], 0)
        # Incomplete analyzer metrics fail closed rather than pass.
        self.assertEqual(scored[1]["deliveryAdherence"]["flags"], ["metrics_incomplete"])
        self.assertFalse(scored[2]["deliveryAdherence"]["passed"])
        self.assertIn("delivery_supporting_miss_arousal_score", scored[2]["deliveryAdherence"]["flags"])
        selection = select_winners(scored, ["happy"])
        self.assertEqual(selection["happy"]["winner"]["seed"], 1)
        self.assertNotIn("ser", json.dumps(scored))


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
