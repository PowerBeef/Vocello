#!/usr/bin/env python3
"""Unit tests for scripts/delivery_identification_check.py."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from delivery_identification_check import evaluate_discrimination, evaluate_identification


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


def trials(spec):
    """spec: list of (group, tier, sideA, sideB, correctSide) -> 2AFC manifest."""
    manifest = []
    for index, (group, tier, side_a, side_b, correct) in enumerate(spec, start=1):
        manifest.append({
            "id": f"trial_{index:02d}", "group": group, "tier": tier, "seed": 1,
            "sideA": side_a, "sideB": side_b,
            "asked": side_a if correct == "A" else side_b,
            "correctSide": correct,
        })
    return manifest


def angry_block(tier, count, correct_count, group="angry", other="excited"):
    """`count` trials in one tier, `correct_count` of which the listener gets right."""
    spec = [(group, tier, "angry", other, "A") for _ in range(count)]
    manifest = trials(spec)
    answers = {}
    for index, entry in enumerate(manifest):
        answers[entry["id"]] = "A" if index < correct_count else "B"
    return manifest, answers


class DiscriminationTests(unittest.TestCase):
    def _combine(self, *blocks):
        manifest, answers, offset = [], {}, 0
        for block_manifest, block_answers in blocks:
            for entry in block_manifest:
                offset += 1
                new_id = f"t{offset:03d}"
                answers[new_id] = block_answers[entry["id"]]
                manifest.append(dict(entry, id=new_id))
        return manifest, answers

    def test_perfect_discrimination_reports_no_collapse(self):
        manifest, answers = self._combine(
            angry_block("normal", 8, 8), angry_block("strong", 8, 8),
            angry_block("normal", 4, 4, group="anchor", other="whisper"),
        )
        report = evaluate_discrimination(manifest, answers)
        self.assertEqual(report["verdict"], "no_measured_strong_tier_collapse")
        self.assertEqual(report["overallAccuracy"]["rate"], 1.0)

    def test_an_angry_specific_drop_at_strong_is_named(self):
        # Angry pairs fall apart at strong while control pairs hold: the exact
        # shape of the standing complaint.
        manifest, answers = self._combine(
            angry_block("normal", 12, 12), angry_block("strong", 12, 4),
            angry_block("normal", 8, 8, group="control", other="sad"),
            angry_block("strong", 8, 8, group="control", other="sad"),
            angry_block("strong", 4, 4, group="anchor", other="whisper"),
        )
        report = evaluate_discrimination(manifest, answers)
        self.assertEqual(report["verdict"], "strong_tier_collapses_toward_angry")
        difference = report["groups"]["angry"]["strongMinusNormal"]
        self.assertLess(difference["difference"], 0)
        self.assertTrue(difference["excludesZero"])

    def test_a_global_strong_tier_drop_is_distinguished_from_an_angry_one(self):
        # Controls fall apart too, so the tier is worse at everything rather
        # than collapsing toward anger specifically -- a different diagnosis.
        manifest, answers = self._combine(
            angry_block("normal", 12, 12), angry_block("strong", 12, 4),
            angry_block("normal", 12, 12, group="control", other="sad"),
            angry_block("strong", 12, 4, group="control", other="sad"),
            angry_block("strong", 4, 4, group="anchor", other="whisper"),
        )
        report = evaluate_discrimination(manifest, answers)
        self.assertEqual(report["verdict"], "strong_tier_worse_across_the_board")

    def test_failed_anchors_discard_the_session(self):
        # Anchors are meant to be trivial; at chance the listener was not
        # engaged and a striking angry result must not be believed.
        manifest, answers = self._combine(
            angry_block("normal", 12, 12), angry_block("strong", 12, 4),
            angry_block("strong", 8, 4, group="anchor", other="whisper"),
        )
        report = evaluate_discrimination(manifest, answers)
        self.assertEqual(report["verdict"], "session_unusable")
        self.assertFalse(report["sessionEngaged"])

    def test_pairings_are_broken_out_so_one_bad_preset_cannot_hide(self):
        manifest, answers = self._combine(
            angry_block("strong", 6, 6, other="excited"),
            angry_block("strong", 6, 1, other="dramatic"),
        )
        report = evaluate_discrimination(manifest, answers)
        self.assertEqual(report["pairings"]["angry vs excited"]["strong"]["rate"], 1.0)
        self.assertLess(report["pairings"]["angry vs dramatic"]["strong"]["rate"], 0.3)


if __name__ == "__main__":
    unittest.main()
