#!/usr/bin/env python3
"""Unit tests for scripts/mos_advisory.py (CM-6).

Offline: exercises the pure report assembly without torch or utmosv2, so the
suite runs in the deterministic self-test lane. The advisory contract under
test: every sidecar row is represented, unscored WAVs are recorded rather
than dropped, the report is explicitly not a gate, and aggregates are
per delivery-cell medians.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mos_advisory import ADVISORY_SCHEMA_VERSION, build_report


def row(gid, delivery, seed=1, model="pro_custom_speed",
        delivery_wav="d.wav", neutral_wav="n.wav"):
    return {
        "generationID": gid, "delivery": delivery, "seed": seed, "model": model,
        "deliveryWav": f"/runs/x/{delivery_wav}", "neutralWav": f"/runs/x/{neutral_wav}",
    }


class MOSAdvisoryReportTests(unittest.TestCase):
    def test_report_is_advisory_never_a_gate(self):
        report = build_report([], {})
        self.assertEqual(report["advisory"], "mos-proxy")
        self.assertEqual(report["schemaVersion"], ADVISORY_SCHEMA_VERSION)
        self.assertFalse(report["gate"])

    def test_takes_carry_mos_and_paired_neutral_delta(self):
        rows = [row("g1", "happy.strong", delivery_wav="a.wav", neutral_wav="n.wav")]
        report = build_report(rows, {"a.wav": 3.4, "n.wav": 3.1})
        take = report["takes"][0]
        self.assertEqual(take["mos"], 3.4)
        self.assertEqual(take["neutralMOS"], 3.1)
        self.assertAlmostEqual(take["deltaMOS"], 0.3)
        self.assertEqual(report["scoredCount"], 1)
        self.assertEqual(report["missing"], [])

    def test_unscored_wavs_are_recorded_not_dropped(self):
        rows = [
            row("g1", "sad.strong", delivery_wav="a.wav", neutral_wav="n.wav"),
            row("g2", "sad.strong", delivery_wav="b.wav", neutral_wav="n.wav"),
        ]
        report = build_report(rows, {"a.wav": 3.0, "n.wav": 3.2})
        self.assertEqual(len(report["takes"]), 2)
        self.assertIsNone(report["takes"][1]["mos"])
        self.assertEqual(report["missing"], ["b.wav"])
        self.assertEqual(report["scoredCount"], 1)

    def test_aggregates_are_per_delivery_and_model_medians(self):
        rows = [
            row("g1", "calm.strong", seed=1, delivery_wav="a.wav", neutral_wav="n1.wav"),
            row("g2", "calm.strong", seed=2, delivery_wav="b.wav", neutral_wav="n2.wav"),
            row("g3", "calm.strong", seed=3, model="pro_custom_quality",
                delivery_wav="c.wav", neutral_wav="n3.wav"),
        ]
        scores = {"a.wav": 3.0, "b.wav": 3.6, "c.wav": 2.8,
                  "n1.wav": 3.0, "n2.wav": 3.0, "n3.wav": 3.0}
        report = build_report(rows, scores)
        speed = report["aggregates"]["calm.strong|pro_custom_speed"]
        self.assertEqual(speed["n"], 2)
        self.assertAlmostEqual(speed["medianMOS"], 3.3)
        self.assertAlmostEqual(speed["medianDeltaMOS"], 0.3)
        quality = report["aggregates"]["calm.strong|pro_custom_quality"]
        self.assertEqual(quality["n"], 1)
        self.assertEqual(report["overallMedianMOS"], 3.0)


if __name__ == "__main__":
    unittest.main()
