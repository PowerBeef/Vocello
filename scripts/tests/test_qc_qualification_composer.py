#!/usr/bin/env python3
"""Composer goldens: recorded detector verdicts give exact take verdicts (audit section 3.3)."""

from __future__ import annotations

import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.qc_qualification import composer  # noqa: E402

RECORD = "a" * 64


def verdict(detector: str, status: str, *, detector_class: str = "B", stage: int = 2,
            level: str | None = "fail", in_scope: bool = True, reasons: list[str] | None = None,
            judges: list[str] | None = None) -> dict:
    calibration = None if level is None else {"recordSHA256": RECORD, "level": level, "inScope": in_scope}
    entry = {"detector": detector, "class": detector_class, "stage": stage, "status": status,
             "judges": judges or ["asr.whisper-large-v3@1"], "calibration": calibration}
    if reasons is not None:
        entry["reasons"] = reasons
    return entry


class PrecedenceTests(unittest.TestCase):
    def test_the_corrected_precedence(self) -> None:
        ladder = [
            ("fail", verdict("content.deletion@2", "fail")),
            ("unavailable", verdict("content.repetition@1", "unavailable", reasons=["timeout"])),
            ("inconclusive", verdict("language.lid@1", "abstain", detector_class="D",
                                     reasons=["families-disagree"])),
            ("warn", verdict("content.substitution@1", "warn", level="warn")),
            ("uncalibrated", verdict("boundary.truncation@1", "pass", detector_class="C", level=None)),
            ("pass", verdict("content.babble@1", "pass")),
        ]
        for index, (expected, _) in enumerate(ladder):
            take = composer.compose([entry for _, entry in ladder[index:]], "language-bench")
            self.assertEqual(take["status"], expected, expected)
        self.assertEqual(composer.PRECEDENCE, ("fail", "unavailable", "abstain", "warn", "uncalibrated", "pass"))

    def test_decided_by_names_every_detector_at_the_deciding_status(self) -> None:
        take = composer.compose([verdict("content.deletion@2", "fail"), verdict("content.repetition@1", "fail"),
                                 verdict("content.babble@1", "warn", level="warn")], "language-bench")
        self.assertEqual(take["decidedBy"], ["content.deletion@2", "content.repetition@1"])


class GatingTests(unittest.TestCase):
    def test_advisory_blocking_statuses_never_change_the_take(self) -> None:
        verdicts = [
            verdict("content.deletion@2", "pass"),
            verdict("identity.onset-break@1", "fail", detector_class="E"),
            verdict("identity.window-drift@1", "unavailable", detector_class="E", reasons=["crash"]),
            verdict("prosody.octave@1", "abstain", detector_class="F", reasons=["out-of-scope"]),
            verdict("quality.audiobox@1", "pass", detector_class="G", level=None),
        ]
        take = composer.compose(verdicts, "language-bench")
        self.assertEqual(take["status"], "pass")
        self.assertEqual(take["gating"], ["content.deletion@2"])
        self.assertEqual(len(take["advisory"]), 4)

    def test_a_qualified_warn_reads_in_any_lane(self) -> None:
        take = composer.compose([verdict("content.deletion@2", "pass"),
                                 verdict("identity.onset-break@1", "warn", detector_class="E", level="warn")],
                                "language-bench")
        self.assertEqual((take["status"], take["decidedBy"]), ("warn", ["identity.onset-break@1"]))

    def test_publication_gates_stage_zero_only(self) -> None:
        stage0 = verdict("fastqc.clicks@8", "fail", detector_class="A", stage=0, level="legacy-unqualified",
                         judges=["fastqc@8"])
        stage2 = verdict("content.deletion@2", "fail")
        self.assertEqual(composer.compose([stage2], "publication")["status"], "unavailable")
        take = composer.compose([stage0, stage2], "publication")
        self.assertEqual((take["status"], take["decidedBy"]), ("fail", ["fastqc.clicks@8"]))
        promotion = composer.compose([stage0, stage2], "release-promotion")
        self.assertEqual(promotion["decidedBy"], ["content.deletion@2", "fastqc.clicks@8"])

    def test_nothing_measured_is_never_a_pass(self) -> None:
        empty = composer.compose([], "clone-lane")
        self.assertEqual((empty["status"], empty["reasons"]), ("unavailable", ["no-gating-verdict"]))
        missing = composer.compose([verdict("content.deletion@2", "pass")], "language-bench",
                                   required=["language.lid@1"])
        self.assertEqual((missing["status"], missing["decidedBy"]), ("unavailable", ["language.lid@1"]))
        self.assertEqual(missing["verdicts"][1]["reasons"], ["missing-verdict"])


class NormalizationTests(unittest.TestCase):
    def test_no_record_is_uncalibrated_and_advisory_uncalibrated_is_listed_only(self) -> None:
        take = composer.compose([verdict("content.deletion@2", "fail", level=None)], "language-bench")
        self.assertEqual(take["status"], "uncalibrated")
        entry = take["verdicts"][0]
        self.assertEqual((entry["reportedStatus"], entry["status"], entry["reasons"]),
                         ("fail", "uncalibrated", ["no-qualified-record"]))
        advisory = composer.compose([verdict("content.deletion@2", "pass"),
                                     verdict("identity.onset-break@1", "warn", detector_class="E", level=None)],
                                    "language-bench")
        self.assertEqual(advisory["status"], "pass")

    def test_out_of_scope_abstains_and_warn_only_records_cap_a_fail(self) -> None:
        out = composer.compose([verdict("content.deletion@2", "pass", in_scope=False)], "language-bench")
        self.assertEqual(out["status"], "inconclusive")
        self.assertEqual(out["verdicts"][0]["reasons"], ["out-of-scope"])
        capped = composer.compose([verdict("content.deletion@2", "fail", level="warn")], "language-bench")
        self.assertEqual(capped["status"], "warn")
        self.assertEqual(capped["verdicts"][0]["reasons"], ["qualified-at-warn-only"])

    def test_legacy_bounds_keep_their_verdict(self) -> None:
        take = composer.compose([verdict("fastqc.dropout@8", "fail", detector_class="A", stage=0,
                                         level="legacy-unqualified", judges=["fastqc@8"])], "publication")
        self.assertEqual(take["status"], "fail")
        self.assertTrue(take["verdicts"][0]["legacy"])

    def test_malformed_verdicts_are_refused(self) -> None:
        good = verdict("content.deletion@2", "pass")
        broken = [
            {**good, "detector": "content.deletion"},
            {**good, "class": "Z"},
            {**good, "stage": 3},
            {**good, "stage": True},
            {**good, "judges": []},
            {**good, "judges": ["whisper"]},
            {**good, "status": "inconclusive"},
            {key: value for key, value in good.items() if key != "calibration"},
            {**good, "calibration": {"recordSHA256": "abc", "level": "fail", "inScope": True}},
            {**good, "calibration": {"recordSHA256": RECORD, "level": "gating", "inScope": True}},
            {**good, "calibration": {"recordSHA256": RECORD, "level": "fail", "inScope": "yes"}},
            {**good, "status": "abstain"},
            {**good, "status": "abstain", "reasons": ["model-tired"]},
            {**good, "status": "unavailable", "reasons": []},
            {**good, "reasons": "timeout"},
        ]
        for entry in broken:
            with self.assertRaises(composer.CompositionError, msg=str(entry)):
                composer.compose([entry], "language-bench")
        with self.assertRaises(composer.CompositionError):
            composer.compose([good, good], "language-bench")
        with self.assertRaises(composer.CompositionError):
            composer.compose([good], "karaoke-lane")


class GoldenTests(unittest.TestCase):
    def test_a_recorded_take_composes_exactly(self) -> None:
        verdicts = [
            verdict("content.deletion@2", "pass", judges=["asr.whisper-large-v3@1", "asr.parakeet-tdt-0.6b-v3@1"]),
            verdict("language.lid@1", "abstain", detector_class="D", level="warn",
                    reasons=["families-disagree"], judges=["lid.voxlingua107-ecapa@1", "asr.whisper-large-v3@1"]),
            verdict("identity.onset-break@1", "uncalibrated", detector_class="E", level=None,
                    judges=["sv.campplus@1"], reasons=["no-qualified-record"]),
        ]
        take = composer.compose(verdicts, "language-bench")
        self.assertEqual(take, {
            "schema": "vocello.audioqc.take-verdict/1",
            "lane": "language-bench",
            "composition": "worst-of-gating/1",
            "status": "inconclusive",
            "decidedBy": ["language.lid@1"],
            "reasons": [],
            "gating": ["content.deletion@2", "language.lid@1"],
            "advisory": ["identity.onset-break@1"],
            "verdicts": [
                {"detector": "content.deletion@2", "class": "B", "stage": 2,
                 "judges": ["asr.parakeet-tdt-0.6b-v3@1", "asr.whisper-large-v3@1"],
                 "calibration": {"recordSHA256": RECORD, "level": "fail", "inScope": True},
                 "reportedStatus": "pass", "status": "pass", "reasons": [], "legacy": False, "gating": True},
                {"detector": "identity.onset-break@1", "class": "E", "stage": 2, "judges": ["sv.campplus@1"],
                 "calibration": None, "reportedStatus": "uncalibrated", "status": "uncalibrated",
                 "reasons": ["no-qualified-record"], "legacy": False, "gating": False},
                {"detector": "language.lid@1", "class": "D", "stage": 2,
                 "judges": ["asr.whisper-large-v3@1", "lid.voxlingua107-ecapa@1"],
                 "calibration": {"recordSHA256": RECORD, "level": "warn", "inScope": True},
                 "reportedStatus": "abstain", "status": "abstain", "reasons": ["families-disagree"],
                 "legacy": False, "gating": True},
            ],
        })

    def test_composition_is_pure_and_never_cached(self) -> None:
        verdicts = [verdict("content.deletion@2", "pass")]
        before = copy.deepcopy(verdicts)
        first = composer.compose(verdicts, "language-bench")
        self.assertEqual(verdicts, before)
        verdicts[0]["status"] = "fail"
        self.assertEqual(composer.compose(verdicts, "language-bench")["status"], "fail")
        self.assertEqual(first["status"], "pass")
        self.assertFalse(hasattr(composer.compose, "cache_info"))


if __name__ == "__main__":
    unittest.main()
