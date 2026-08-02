#!/usr/bin/env python3
"""Unit tests for scripts/delivery_identification_check.py."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from delivery_identification_check import evaluate_identification


def key(entries):
    """entries: (id, cell) -> trial rows."""
    return [{"id": item_id, "cell": cell, "seed": 1, "kind": "trial"}
            for item_id, cell in entries]


def cells(spec, seeds=3):
    """spec: {cell: count} -> a manifest with sequential ids."""
    manifest, index = [], 0
    for cell, count in spec.items():
        for _ in range(count):
            index += 1
            manifest.append({"id": f"clip_{index:02d}", "cell": cell,
                             "seed": seeds, "kind": "trial"})
    return manifest


class IdentificationTests(unittest.TestCase):
    def test_a_correctly_identified_preset_scores_full_recall(self):
        manifest = cells({"happy.normal": 3, "sad.normal": 3})
        answers = {"clip_01": "Happy", "clip_02": "Happy", "clip_03": "Happy",
                   "clip_04": "Sad", "clip_05": "Sad", "clip_06": "Sad"}
        report = evaluate_identification(manifest, answers)
        self.assertEqual(report["perPreset"]["happy"]["recall"], 1.0)
        self.assertEqual(report["perPreset"]["sad"]["recall"], 1.0)
        self.assertEqual(report["overallAccuracy"]["rate"], 1.0)

    def test_a_preset_heard_as_something_else_names_the_substitute(self):
        manifest = cells({"dramatic.normal": 3})
        answers = {"clip_01": "Happy", "clip_02": "Happy", "clip_03": "Dramatic"}
        report = evaluate_identification(manifest, answers)
        self.assertAlmostEqual(report["perPreset"]["dramatic"]["recall"], 0.333, places=2)
        self.assertEqual(report["perPreset"]["dramatic"]["mostCommonLabel"], "Happy")
        self.assertEqual(report["perCell"]["dramatic.normal"]["topOtherLabel"], "Happy")

    def test_the_attractor_test_finds_a_label_pulled_at_strong(self):
        # Every strong clip heard as Angry, no normal clip heard that way: the
        # exact shape of the standing complaint, and it must be detected.
        manifest = cells({
            "happy.strong": 4, "excited.strong": 4,
            "happy.normal": 4, "excited.normal": 4,
        })
        answers = {}
        for index in range(1, 9):
            answers[f"clip_{index:02d}"] = "Angry"
        for index in range(9, 13):
            answers[f"clip_{index:02d}"] = "Happy"
        for index in range(13, 17):
            answers[f"clip_{index:02d}"] = "Excited"
        report = evaluate_identification(manifest, answers)
        self.assertIn("Angry", report["strongTierAttractors"])
        difference = report["attractors"]["Angry"]["strongMinusNormal"]
        self.assertTrue(difference["excludesZero"])
        self.assertGreater(difference["difference"], 0.5)

    def test_no_attractor_is_reported_when_tiers_behave_alike(self):
        manifest = cells({"happy.strong": 4, "happy.normal": 4})
        answers = {f"clip_{index:02d}": "Happy" for index in range(1, 9)}
        report = evaluate_identification(manifest, answers)
        self.assertEqual(report["strongTierAttractors"], [])

    def test_exact_repeats_measure_listener_self_agreement(self):
        manifest = cells({"happy.normal": 2})
        manifest += [
            {"id": "clip_03", "cell": "happy.normal", "seed": 3,
             "kind": "repeat", "repeatOf": "clip_01"},
            {"id": "clip_04", "cell": "happy.normal", "seed": 3,
             "kind": "repeat", "repeatOf": "clip_02"},
        ]
        answers = {"clip_01": "Happy", "clip_02": "Happy",
                   "clip_03": "Happy", "clip_04": "Excited"}
        report = evaluate_identification(manifest, answers)
        self.assertEqual(report["selfAgreement"]["n"], 2)
        self.assertEqual(report["selfAgreement"]["agreement"], 0.5)
        # Repeats are second looks at an already-counted clip and must not
        # inflate the trial count.
        self.assertEqual(report["trials"], 2)

    def test_unsure_is_tracked_separately_and_never_counted_correct(self):
        manifest = cells({"happy.normal": 4})
        answers = {"clip_01": "Happy", "clip_02": "Unsure",
                   "clip_03": "Unsure", "clip_04": "Happy"}
        report = evaluate_identification(manifest, answers)
        self.assertEqual(report["unsureRate"], 0.5)
        self.assertEqual(report["perPreset"]["happy"]["recall"], 0.5)
        self.assertEqual(report["perCell"]["happy.normal"]["unsureRate"], 0.5)

    def test_missing_and_unknown_ids_are_reported(self):
        manifest = cells({"happy.normal": 2})
        report = evaluate_identification(manifest, {"clip_01": "Happy", "ghost": "Sad"})
        self.assertEqual(report["missingAnswers"], ["clip_02"])
        self.assertEqual(report["unknownItemIDs"], ["ghost"])


if __name__ == "__main__":
    unittest.main()
