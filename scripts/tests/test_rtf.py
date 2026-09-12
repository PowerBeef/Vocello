"""Standard real-time factor semantics shared by the benchmark harness (scripts/lib/rtf.py)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))
from lib import rtf  # noqa: E402


def mark(stage: str, t_ms: int) -> dict:
    return {"stage": stage, "tMS": t_ms}


class RequestWallTests(unittest.TestCase):
    def test_request_span_excludes_model_load_and_prewarm(self) -> None:
        marks = [
            mark("startup.request_validated", 0),
            mark("startup.model_load_started", 20),
            mark("startup.model_loaded", 1_520),
            mark("startup.prewarm_started", 1_530),
            mark("startup.prewarm_completed", 2_030),
            mark("streamStartup", 2_100),
            mark("streamGenerationEnded", 7_900),
            mark("streamCompleted", 8_030),
        ]
        self.assertAlmostEqual(rtf.request_wall_seconds_from_marks(marks), 6.03)

    def test_generation_ended_is_the_fallback_terminal_mark(self) -> None:
        marks = [mark("startup.request_validated", 0), mark("streamGenerationEnded", 4_000)]
        self.assertEqual(rtf.request_wall_seconds_from_marks(marks), 4.0)
        self.assertIsNone(rtf.request_wall_seconds_from_marks([]))
        self.assertIsNone(rtf.request_wall_seconds_from_marks([mark("streamCompleted", 0)]))

    def test_engine_rtf_prefers_the_typed_derived_metric(self) -> None:
        row = {"derivedMetrics": {"audioSeconds": 10.0, "requestWallSeconds": 6.0, "realTimeFactor": 0.6,
                                  "audioSecondsPerWallSecond": 2.0}}
        self.assertEqual(rtf.engine_rtf(row), 0.6)
        self.assertEqual(rtf.decode_speedup(row), 2.0)
        self.assertEqual(rtf.request_wall_seconds(row), 6.0)

    def test_engine_rtf_recomputes_from_stage_marks_for_older_rows(self) -> None:
        row = {
            "derivedMetrics": {"audioSeconds": 5.0, "audioSecondsPerWallSecond": 2.0},
            "backendMetrics": {"stages": [mark("startup.request_validated", 0), mark("streamCompleted", 3_000)]},
        }
        self.assertAlmostEqual(rtf.engine_rtf(row), 0.6)
        self.assertIsNone(rtf.engine_rtf({"derivedMetrics": {"audioSeconds": 5.0}}))

    def test_app_end_to_end_rtf_uses_the_submit_to_completed_span(self) -> None:
        self.assertAlmostEqual(rtf.app_end_to_end_rtf({"frontendMetrics": {"submitToCompletedMS": 7_000}}, 10.0), 0.7)
        self.assertAlmostEqual(rtf.app_end_to_end_rtf({"timingsMS": {"submitToCompletedMS": 7_000}}, 10.0), 0.7)
        self.assertIsNone(rtf.app_end_to_end_rtf({}, 10.0))
        self.assertIsNone(rtf.app_end_to_end_rtf({"timingsMS": {"submitToCompletedMS": 7_000}}, 0.0))


class RecordSemanticsTests(unittest.TestCase):
    def test_legacy_records_derive_a_standard_rtf_without_being_rewritten(self) -> None:
        legacy_ui = {
            "run": {"kind": "ui-generation"},
            "takes": [
                {"metrics": {"rtf": 1.8, "audioSeconds": 10.0, "submitToCompletedMS": 6_000}},
                {"metrics": {"rtf": 1.9, "audioSeconds": 10.0, "submitToCompletedMS": 8_000}},
            ],
        }
        self.assertFalse(rtf.is_standard(legacy_ui))
        self.assertEqual(rtf.record_rtf_median(legacy_ui), (0.7, True))
        legacy_cli = {"run": {"kind": "engine-generation"}, "takes": [{"metrics": {"rtf": 2.0, "audioSeconds": 4.0}}]}
        self.assertEqual(rtf.record_rtf_median(legacy_cli), (0.5, True))
        legacy_other = {"run": {"kind": "language"}, "takes": [{"metrics": {"rtf": 2.0}}]}
        self.assertEqual(rtf.record_rtf_median(legacy_other), (None, True))

    def test_standard_records_report_their_measured_rtf(self) -> None:
        record = {"run": {"kind": "ui-generation", "rtfDefinition": "wall/audio"},
                  "takes": [{"metrics": {"rtf": 0.61}}, {"metrics": {"rtf": 0.59}}]}
        self.assertTrue(rtf.is_standard(record))
        self.assertEqual(rtf.record_rtf_median(record), (0.6, False))
        self.assertEqual(rtf.format_rtf(0.6), "0.60")
        self.assertEqual(rtf.format_rtf(0.6, derived=True), "~0.60")
        self.assertEqual(rtf.format_rtf(None), "—")

    def test_regression_direction_follows_the_definition(self) -> None:
        self.assertAlmostEqual(rtf.regression_percent(0.60, 0.66), 10.0)
        self.assertAlmostEqual(rtf.regression_percent(0.60, 0.54), -10.0)
        self.assertAlmostEqual(rtf.regression_percent(2.0, 1.8, rtf.LEGACY_RTF_DEFINITION), 10.0)
        self.assertEqual(rtf.regression_percent(0.0, 1.0), 0.0)


if __name__ == "__main__":
    unittest.main()
