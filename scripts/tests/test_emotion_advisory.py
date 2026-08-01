#!/usr/bin/env python3
"""Unit tests for scripts/emotion_advisory.py.

The agreement logic and sidecar plumbing are exercised with an injectable
classifier, so the suite needs neither torch nor the pinned model.
"""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from emotion_advisory import (
    ABSTAIN_PRESETS,
    EMOTION_LABELS,
    PRESET_ALLOWED_EMOTIONS,
    analyze_sidecar,
    evaluate_agreement,
)


def probabilities(top, value=0.8):
    spread = (1.0 - value) / (len(EMOTION_LABELS) - 1)
    return {label: (value if label == top else spread) for label in EMOTION_LABELS}


class EmotionAdvisoryTests(unittest.TestCase):
    def test_every_expressive_preset_is_mapped_or_abstains(self):
        presets = {"happy", "sad", "angry", "fearful", "surprised", "excited",
                   "calm", "whisper", "dramatic", "neutral"}
        covered = set(PRESET_ALLOWED_EMOTIONS) | ABSTAIN_PRESETS
        self.assertEqual(presets - covered, set())

    def test_matching_emotion_agrees(self):
        report = evaluate_agreement(probabilities("happy"), "happy.strong")
        self.assertTrue(report["agreement"])
        self.assertEqual(report["topEmotion"], "happy")

    def test_excited_accepts_happy_or_surprised(self):
        self.assertTrue(evaluate_agreement(probabilities("surprised"), "excited.normal")["agreement"])
        self.assertTrue(evaluate_agreement(probabilities("happy"), "excited.normal")["agreement"])
        self.assertFalse(evaluate_agreement(probabilities("sad"), "excited.normal")["agreement"])

    def test_whisper_abstains(self):
        report = evaluate_agreement(probabilities("neutral"), "whisper.normal")
        self.assertIsNone(report["agreement"])
        self.assertEqual(report["note"], "preset_abstains")

    def test_unknown_preset_reports_unmapped(self):
        report = evaluate_agreement(probabilities("happy"), "bogus.normal")
        self.assertIsNone(report["agreement"])
        self.assertEqual(report["note"], "preset_unmapped")

    def test_empty_probabilities_report_unavailable(self):
        report = evaluate_agreement({}, "happy.normal")
        self.assertIsNone(report["agreement"])
        self.assertEqual(report["note"], "classification_unavailable")

    def test_sidecar_mode_aggregates_agreement_rate(self):
        with tempfile.TemporaryDirectory() as tmp:
            outputs = os.path.join(tmp, "bench")
            os.makedirs(outputs)
            rows = []
            for index, (delivery, top) in enumerate(
                [("happy.strong", "happy"), ("sad.normal", "happy"), ("whisper.normal", "neutral")]
            ):
                name = f"custom_m_medium_warm_d-{delivery}_{index}.wav"
                open(os.path.join(outputs, name), "wb").close()
                rows.append({
                    "deliveryWav": name,
                    "delivery": delivery,
                    "generationID": f"gen-{index}",
                })
            sidecar = os.path.join(tmp, "bench-prosody.json")
            with open(sidecar, "w", encoding="utf-8") as handle:
                json.dump(rows, handle)

            tops = {"happy.strong": "happy", "sad.normal": "happy", "whisper.normal": "neutral"}

            def classify(path):
                for delivery, top in tops.items():
                    if f"d-{delivery}_" in os.path.basename(path):
                        return probabilities(top)
                raise AssertionError(f"unexpected clip {path}")

            report = analyze_sidecar(sidecar, outputs, classify)
        self.assertEqual(report["aggregate"]["count"], 3)
        self.assertEqual(report["aggregate"]["judged"], 2)  # whisper abstains
        self.assertEqual(report["aggregate"]["agreed"], 1)  # sad got happy
        self.assertEqual(report["aggregate"]["agreementRate"], 0.5)
        self.assertIn("peakRSSBytes", report)

    def test_sidecar_mode_fails_closed_on_missing_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            outputs = os.path.join(tmp, "bench")
            os.makedirs(outputs)
            sidecar = os.path.join(tmp, "bench-prosody.json")
            with open(sidecar, "w", encoding="utf-8") as handle:
                json.dump([{"deliveryWav": "missing.wav", "delivery": "happy.normal"}], handle)
            with self.assertRaises(ValueError):
                analyze_sidecar(sidecar, outputs, lambda path: probabilities("happy"))


if __name__ == "__main__":
    unittest.main()
