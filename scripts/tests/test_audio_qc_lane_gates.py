#!/usr/bin/env python3
"""AQ-09 lane gating contract: a detector gates a lane only behind a qualified record that covers it.

Runs on the fixture repository of the docs generator (`fixtures/audio_qc_docs/repo`),
whose language bench is gated at warn by `content.consensus-error@1` with a committed,
qualified warn record over english, french and german.
"""

from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import audio_qc_lane_gates as gates  # noqa: E402

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "audio_qc_docs" / "repo"
CONTENT, CLICKS = "content.consensus-error@1", "signal.clicks@1"
RECORDS = Path("benchmarks/audio-qc-calibration") / CONTENT


class LaneGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / "repo"
        shutil.copytree(FIXTURE, self.root)
        self.record = next((self.root / RECORDS).glob("record-*.json")).relative_to(self.root).as_posix()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def reset(self) -> None:
        """A fresh copy of the fixture, for a test that checks several independent edits."""
        self.tearDown()
        self.setUp()

    def edit(self, relative: str, change) -> None:
        path = self.root / relative
        value = json.loads(path.read_text(encoding="utf-8"))
        change(value)
        path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def lane(self, name: str = "language-bench"):
        def change(update):
            self.edit(gates.GATES, lambda config: update(config["lanes"][name]))
        return change

    def errors(self) -> list[str]:
        return gates.lane_gate_errors(self.root)

    def assert_refused(self, fragment: str) -> None:
        errors = self.errors()
        self.assertTrue(any(fragment in error for error in errors), errors)

    def test_a_gate_behind_a_qualified_covering_record_passes(self) -> None:
        self.assertEqual(self.errors(), [])
        out, err = StringIO(), StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = gates.main(["--repo-root", str(self.root), "validate"])
        self.assertEqual(code, 0, err.getvalue())
        self.assertIn("2 lanes, 1 gates", out.getvalue())

    def test_a_gate_without_any_record_is_refused(self) -> None:
        shutil.rmtree(self.root / RECORDS)
        self.assert_refused(f"{CONTENT} gates language-bench at warn without a committed calibration record")
        out, err = StringIO(), StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = gates.main(["--repo-root", str(self.root), "validate"])
        self.assertEqual(code, 1)
        self.assertIn("without a committed calibration record", err.getvalue())

    def test_a_refused_record_does_not_back_a_gate(self) -> None:
        self.edit(self.record, lambda record: record.update(verdict="refused", level=None,
                                                             reasons=["far-pooled-not-met"]))
        self.assert_refused("refused (far-pooled-not-met)")

    def test_a_warn_record_does_not_back_a_fail_gate(self) -> None:
        self.lane()(lambda lane: lane["gates"][0].update(level="fail"))
        self.assert_refused("qualified at warn, not fail")

    def fail_record(self, point: str = "fail") -> None:
        """Turn the fixture's warn record into a qualified record at a fail point, with its N3 bound."""
        def change(record: dict) -> None:
            record.update(operatingPoint=point, level="fail")
            record["cohorts"]["n3"] = {"kind": "audio-qc-calibration-takes", "manifestDigest": "7" * 64,
                                       "scoresSHA256": "8" * 64}
            record["rates"]["n3"] = {"events": 0, "units": 180, "rate": 0.0, "lower": 0.0, "upper": 0.0165,
                                     "confidence": 0.95, "method": "clopper-pearson-one-sided", "limit": 0.05,
                                     "minimumUnits": None, "meets": True}
        self.edit(self.record, change)

    def test_a_fail_record_backs_a_fail_gate_and_the_evidence_lane_bar_no_product_lane(self) -> None:
        self.fail_record()
        self.lane()(lambda lane: lane["gates"][0].update(level="fail"))
        self.assertEqual(self.errors(), [])
        # A fail record also covers a warn gate.
        self.lane()(lambda lane: lane["gates"][0].update(level="warn"))
        self.assertEqual(self.errors(), [])
        self.reset()
        self.fail_record("evidenceLaneFail")
        self.lane()(lambda lane: lane["gates"][0].update(level="fail"))
        self.assertEqual(self.errors(), [])
        self.lane()(lambda lane: lane.update(kind="product"))
        self.assert_refused("operating point evidenceLaneFail does not apply to the lane's kind (product)")
        self.reset()
        # A fail record without its N3 bound is no valid record.
        self.fail_record()
        self.edit(self.record, lambda record: record["rates"].pop("n3"))
        self.lane()(lambda lane: lane["gates"][0].update(level="fail"))
        self.assert_refused("not a valid record (a fail record carries its N3 bound")

    def test_a_record_of_an_earlier_definition_does_not_back_a_gate(self) -> None:
        def reword(registry: dict) -> None:
            next(entry for entry in registry["detectors"] if entry["id"] == CONTENT)["measures"] += " Reworded."
        self.edit("config/audio-qc-detectors.json", reword)
        self.assert_refused("confirmed an earlier definition of the detector (A7)")

    def test_a_lane_language_outside_the_record_scope_is_refused(self) -> None:
        def widen(lane: dict) -> None:
            del lane["matrix"]
            lane["scope"]["languages"].append("spanish")
        self.lane()(widen)
        self.assert_refused("its scope lacks spanish")

    def test_a_language_without_a_measured_far_is_refused(self) -> None:
        self.edit(self.record, lambda record: record["rates"]["farPerLanguage"]["languages"].pop("german"))
        self.assert_refused("it measured no FAR in german")

    def test_record_modes_must_cover_the_lane_modes(self) -> None:
        self.edit(self.record, lambda record: record["scope"].update(modes=["custom"]))
        self.assert_refused("its modes custom do not cover custom, design")

    def test_the_far_population_must_be_the_lane_s(self) -> None:
        self.edit(self.record, lambda record: record["cohorts"]["confirmation"].update(kind="audio-qc-n1-cohort"))
        self.assert_refused("its FAR was confirmed on N1, not N2")

    def test_an_operating_point_that_does_not_apply_to_the_lane_kind_is_refused(self) -> None:
        self.edit("config/audio-qc-qualification-policy.json",
                  lambda policy: policy["operatingPoints"]["warn"].update(appliesTo=["product"]))
        self.assert_refused("operating point warn does not apply to the lane's kind (evidence-lane)")

    def test_an_invalid_or_misfiled_record_does_not_back_a_gate(self) -> None:
        self.edit(self.record, lambda record: record.pop("phiAudit"))
        self.assert_refused("not a valid record")
        self.reset()
        path = self.root / self.record
        path.rename(path.with_name("record-0000000000000000.json"))
        self.assert_refused("not filed as")

    def test_one_covering_record_among_others_is_enough(self) -> None:
        (self.root / RECORDS / "record-ffffffffffffffff.json").write_text("{}\n", encoding="utf-8")
        self.assertEqual(self.errors(), [])

    def test_a_detector_outside_the_lane_gating_classes_is_refused(self) -> None:
        self.lane()(lambda lane: lane["gates"].append({"detector": CLICKS, "level": "warn"}))
        self.assert_refused(f"{CLICKS} (class A, stage 0) is outside the classes")

    def test_gate_entries_are_well_formed(self) -> None:
        for gate, fragment in (({"detector": "signal.unknown@1", "level": "warn"}, "is not in"),
                               ({"detector": CONTENT, "level": "gating"}, "level is one of"),
                               ({"detector": CONTENT}, "names exactly a detector and a level"),
                               ({"detector": CONTENT, "level": "warn"}, "is listed twice")):
            with self.subTest(gate=gate):
                self.reset()
                self.lane()(lambda lane: lane["gates"].append(gate))
                self.assert_refused(fragment)

    def test_a_lane_must_be_a_policy_lane_with_a_declared_scope(self) -> None:
        self.edit(gates.GATES, lambda config: config["lanes"].update(
            {"night-bench": {"kind": "evidence-lane", "gates": [],
                             "scope": {"languages": ["english"], "modes": ["custom"], "farPopulation": "N2"}}}))
        self.assert_refused("lanes.night-bench is not a lane of the policy's laneGatingSets")
        self.reset()
        self.lane("clone-lane")(lambda lane: lane["scope"].update(modes=["whisper"]))
        self.assert_refused("lanes.clone-lane.scope.modes lists distinct modes")
        self.reset()
        self.lane("clone-lane")(lambda lane: lane.update(kind="nightly"))
        self.assert_refused("lanes.clone-lane.kind is one of")

    def test_a_lane_that_names_a_matrix_declares_its_languages_and_modes(self) -> None:
        self.lane()(lambda lane: lane["scope"]["languages"].remove("german"))
        self.assert_refused("declares the languages ['english', 'french', 'german'] and modes ['custom', 'design']")


if __name__ == "__main__":
    unittest.main()
