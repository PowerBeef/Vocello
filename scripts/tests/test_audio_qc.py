#!/usr/bin/env python3
"""The one audio-QC take mapping the publisher and both UI gates share."""

from __future__ import annotations

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib import audio_qc  # noqa: E402


def row(**overrides) -> dict:
    base = {
        "finishReason": "eos",
        "outputMetrics": {"readableWAV": True, "atomicallyPublished": True, "durationSeconds": 2.5},
        "audioQC": {
            "algorithmVersion": 6, "verdict": "pass", "instabilityVerdict": "pass",
            "writtenOutputVerdict": "pass", "flags": [], "clickEvents": 0, "clippedSamples": 1,
            "nonFiniteSamples": 0, "longestSilenceMS": 40, "dcOffset": -0.0001,
        },
        "notes": {"quality_registry_outcome": "pass",
                  "quality_registry_required_gates": "terminal,token_cap,persisted_wav"},
    }
    base.update(overrides)
    return base


class AudioQCTests(unittest.TestCase):
    def test_metric_rename_drops_non_finite_and_boolean_values(self) -> None:
        metrics = audio_qc.qc_metrics({
            "clickEvents": 2, "clippedSamples": True, "nonFiniteSamples": float("nan"),
            "longestSilenceMS": 12, "dcOffset": 0.5, "peak": 0.9,
        })
        self.assertEqual(metrics, {"discontinuityCount": 2.0, "longestSilenceMS": 12.0, "dcOffset": 0.5})

    def test_record_takes_the_worst_verdict_and_names_warning_sources(self) -> None:
        warned = row()
        warned["audioQC"].update({"writtenOutputVerdict": "warn", "flags": ["dropout:900ms"]})
        record = audio_qc.qc_record(warned)
        self.assertEqual(record["verdict"], "warn")
        self.assertEqual(record["warningCodes"], ["dropout:900ms", "written-output-warn"])
        self.assertEqual(record["metrics"]["clipCount"], 1.0)
        passed = audio_qc.qc_record(row())
        self.assertEqual(passed["warningCodes"], [])
        failed = row()
        failed["audioQC"]["instabilityVerdict"] = "fail"
        self.assertEqual(audio_qc.qc_record(failed)["verdict"], "fail")

    def test_failure_predicates_cover_finish_output_and_verdict(self) -> None:
        self.assertIsNone(audio_qc.output_failure(row()))
        self.assertIsNone(audio_qc.audio_qc_failure(row()))
        cancelled = row(finishReason="cancelled")
        self.assertIn("finishReason", audio_qc.output_failure(cancelled))
        unreadable = row(outputMetrics={"readableWAV": False, "atomicallyPublished": True, "durationSeconds": 1.0})
        self.assertIn("readableWAV", audio_qc.output_failure(unreadable))
        failed = row()
        failed["audioQC"].update({"verdict": "fail", "flags": ["clipping"]})
        self.assertEqual(audio_qc.audio_qc_failure(failed), "failed: ['clipping']")
        self.assertEqual(audio_qc.output_failure(failed), "audioQC failed: ['clipping']")
        missing = row(audioQC={})
        self.assertIn("missing or invalid", audio_qc.audio_qc_failure(missing))
        nested = row(audioQC=None)
        nested["outputMetrics"]["audioQC"] = {"verdict": "warn"}
        self.assertIsNone(audio_qc.audio_qc_failure(nested))
        self.assertTrue(audio_qc.finish_succeeded("MAX_TOKENS"))
        self.assertFalse(audio_qc.finish_succeeded("failed"))

    def test_quality_identity_and_schema_version_refuse_a_mixed_run(self) -> None:
        identity = audio_qc.quality_identity_fields(row())
        self.assertEqual(identity["qualityRegistryOutcome"], "pass")
        self.assertEqual(identity["qualityRegistryRequiredGates"], ["persisted_wav", "terminal", "token_cap"])
        self.assertEqual(audio_qc.quality_identity_fields(row(notes={})), {})
        self.assertEqual(audio_qc.history_record_schema_version([identity, identity]), 3)
        self.assertEqual(audio_qc.history_record_schema_version([{}, {}]), 2)
        with self.assertRaisesRegex(audio_qc.AudioQCError, "partial schema-v3"):
            audio_qc.history_record_schema_version([identity, {}])
        self.assertEqual(audio_qc.qc_algorithm_version([row(), row(audioQC={"algorithmVersion": 4})]), 6)


if __name__ == "__main__":
    unittest.main()
