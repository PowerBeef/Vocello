"""QC coverage policy: absence of a qualified decision cannot silently pass."""
import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
from qc import assessment, detectors, features, fidelity, forensics, lanes, store


class CoverageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.layout = store.Layout(Path(self.temp.name))
        self.config = detectors.load_config()
        store.write_json_atomic(self.layout.config / "detectors.json", self.config)

    def tearDown(self):
        self.temp.cleanup()

    def baseline(self):
        return {item["name"]: features.feature(-23 if item["name"] == "level.lufs" else
                    -3 if item["name"] == "level.true_peak_dbtp" else
                    -80 if item["name"] == "pause.nonspeech_level_db" else 0)
                for detector in self.config["detectors"] for item in detector["features"]
                if item["name"].split(".")[0] in ("signal", "pause", "engine", "level")}

    def score(self, values):
        return lanes.score_run(self.layout, self.config,
                    [{"token": "one", "language": "french", "features": values},
                     {"token": "two", "language": "french", "features": self.baseline()}], {}, lane="clone-lane")

    def gate(self, flags, **options):
        flags.update(run="clone-test", lane="clone-lane")
        store.write_json_atomic(self.layout.runs / "clone-test/flags.json", flags)
        with contextlib.redirect_stdout(io.StringIO()) as output:
            code = lanes.gate(self.layout, "clone-lane", "clone-test", **options)
        return code, output.getvalue()

    def test_missing_clone_inputs_are_not_assessed_not_pass(self):
        flags = self.score(self.baseline())
        self.assertFalse(flags["errors"])
        self.assertEqual(flags["assessment"]["execution"], "complete")
        clone = flags["takes"][0]["assessment"]["prosody.pitch"]
        self.assertEqual(clone["decision"], "not-assessed")
        self.assertIn("pitch.register_offset_st", clone["missingFeatures"])
        code, output = self.gate(flags)
        self.assertEqual(code, 4)
        self.assertIn("NOT_ASSESSED", output)
        self.assertEqual(self.gate(flags, legacy_exit=True)[0], 0)

    def test_octave_reference_mismatch_without_qualified_cut_is_uncertain(self):
        values = self.baseline()
        values.update({item["name"]: features.feature(12 if "register" in item["name"] else 0)
                       for detector in self.config["detectors"] if detector["id"] == "prosody.pitch"
                       for item in detector["features"]})
        values.update({"pitch.agreeing_seconds": features.feature(2),
                       "pitch.reference_agreeing_seconds": features.feature(2)})
        flags = self.score(values)
        self.assertEqual(flags["takes"][0]["assessment"]["prosody.pitch"]["decision"], "uncertain")
        self.assertEqual(flags["takes"][0]["flags"], [])
        self.assertEqual(self.gate(flags)[0], 4)

    def test_short_agreement_is_coverage_failure_even_if_threshold_qualified(self):
        detector = next(d for d in self.config["detectors"] if d["id"] == "prosody.pitch")
        values = {item["name"]: features.feature(0) for item in detector["features"]}
        values.update({"pitch.agreeing_seconds": features.feature(.1),
                       "pitch.reference_agreeing_seconds": features.feature(.1)})
        result = assessment.dimension(detector, values, {}, qualified=True, relevant=True, control=False)
        self.assertEqual(result["decision"], "not-assessed")
        self.assertIn("insufficient-agreeing-voiced-duration", result["reasons"])

    def test_partial_nonfinite_features_do_not_count_as_coverage(self):
        detector = next(d for d in self.config["detectors"] if d["id"] == "identity.drift")
        values = {"speaker.whole_distance": {"value": float("nan")},
                  "speaker.window_range": {"value": 0}}
        result = assessment.dimension(detector, values, {}, qualified=True, relevant=True, control=False)
        self.assertEqual(result["inputStatus"], "partial")
        self.assertEqual(result["decision"], "not-assessed")

    def test_runner_failure_is_execution_error_even_with_report_only_features(self):
        flags = self.score(self.baseline())
        flags["models"] = {"pitchA": {"failed": 1, "exitCode": 0}}
        flags["assessment"] = assessment.summarize(flags["takes"], flags["errors"], flags["models"])
        code, text = self.gate(flags)
        self.assertEqual(code, 2)
        self.assertIn(": ERROR;", text)
        self.assertEqual(self.gate(flags, legacy_exit=True)[0], 0)

    def test_stale_scoring_and_legacy_reports_cannot_be_accepted(self):
        flags = self.score(self.baseline())
        flags["scoringSHA256"] = "stale"
        code, text = self.gate(flags, json_output=True)
        self.assertEqual(code, 4)
        self.assertIn("stale-scoring-identity", text)
        flags.pop("assessment")
        flags["schema"] = "vocello.qc.flags/1"
        self.assertEqual(self.gate(flags)[0], 4)
        self.assertEqual(self.gate(flags, legacy_exit=True)[0], 0)

    def test_explicit_complete_assessed_decisions_keep_pass_warn_fail_exits(self):
        for decision, level, expected in (("pass", None, 0), ("warn", "warn", 3), ("fail", "fail", 1)):
            flags = self.score(self.baseline())
            flags["takes"] = [{"assessment": {"synthetic": {"required": True, "decision": decision}},
                               "flags": [] if level is None else [{"level": level}]}]
            flags["assessment"] = assessment.summarize(flags["takes"], [])
            self.assertEqual(self.gate(flags)[0], expected)

    def test_control_take_does_not_create_required_quality_dimensions(self):
        flags = lanes.score_run(self.layout, self.config,
                    [{"token": "one", "language": "french", "features": self.baseline()}], {},
                    lane="clone-lane", controls={"one"})
        self.assertEqual(flags["assessment"]["requiredDimensions"], 0)
        self.assertEqual(self.gate(flags)[0], 4)  # a control-only run cannot accept a clone

    def test_previously_qualified_decision_abstains_after_runner_change(self):
        flags = self.score(self.baseline())
        flags["takes"] = [{"assessment": {"identity.drift": {"required": True, "decision": "pass"}}, "flags": []}]
        flags["assessment"] = assessment.summarize(flags["takes"], [])
        flags["modelIdentities"] = {"speaker": {"id": self.config["models"]["speaker"], "runnerSHA256": "old"}}
        with patch.object(lanes.models, "load_registry", return_value=[{"id": self.config["models"]["speaker"]}]), \
             patch.object(lanes.runtime, "runner_identity", return_value="old"):
            self.assertEqual(self.gate(flags)[0], 0)
        with patch.object(lanes.models, "load_registry", return_value=[{"id": self.config["models"]["speaker"]}]), \
             patch.object(lanes.runtime, "runner_identity", return_value="new"):
            code, text = self.gate(flags, json_output=True)
            self.assertEqual(code, 4)
            self.assertIn("stale-or-missing-runner-identity", text)
            flags["takes"][0]["flags"] = [{"level": "fail"}]
            self.assertEqual(self.gate(flags)[0], 4)
            flags["takes"][0]["token"] = "one"
            store.write_json_atomic(self.layout.runs / "clone-test/flags.json", flags)
            store.write_json_atomic(self.layout.runs / "clone-test/features.json", {
                "scoringSHA256": flags["scoringSHA256"], "takes": [{"token": "one"}]})
            report = lanes.report(self.layout, "clone-test")
            self.assertEqual(report["takes"][0]["assessment"]["identity.drift"]["qualification"], "stale")
            self.assertEqual(report["takes"][0]["recordedAssessment"]["identity.drift"]["decision"], "pass")


class EvidenceTests(unittest.TestCase):
    def track(self, value, n=100):
        return {"outputs": {"hopSeconds": .01, "f0Hz": [value] * n}}

    def test_signed_shift_reference_duration_and_range_are_descriptive(self):
        reference = {"r": {"pitchA": self.track(100), "pitchB": self.track(100)}}
        context = features.build_context(reference, {})
        values = features.pitch_features({"referenceSHA256": "r"},
                       {"pitchA": self.track(200), "pitchB": self.track(200)}, context, {})
        self.assertEqual(values["pitch.register_offset_signed_st"]["value"], 12)
        self.assertEqual(values["pitch.agreeing_seconds"]["value"], 1)
        self.assertEqual(values["pitch.reference_agreeing_seconds"]["value"], 1)
        self.assertEqual(values["pitch.range_p10_p90_st"]["value"], 0)
        values = features.pitch_features({"referenceSHA256": "r"},
                       {"pitchA": self.track(50), "pitchB": self.track(50)}, context, {})
        self.assertEqual(values["pitch.register_offset_signed_st"]["value"], -12)

    def test_silent_or_disagreeing_trackers_do_not_hide_missing_coverage(self):
        for a, b in ((None, None), (100, 200)):
            values = features.pitch_features({}, {"pitchA": self.track(a), "pitchB": self.track(b)}, {}, {})
            self.assertEqual(values["pitch.agreeing_seconds"]["value"], 0)
            self.assertIsNone(values["pitch.register_offset_signed_st"]["value"])

    def test_french_rhotic_and_inserted_vowel_survive_narrow_evidence(self):
        heard = {"phones": [{"phone": p, "start": i * .05, "end": (i+1) * .05}
                              for i, p in enumerate(("ɹ", "ãː", "ə", "p"))]}
        evidence = forensics.french(["ʁ", "ãː", "p"], {"phones": heard, "phonesB": heard})
        self.assertEqual(evidence["inputStatus"], "complete")
        self.assertEqual(evidence["nativeAccentDecision"], "not-assessed")
        events = evidence["agreedEvents"]
        self.assertTrue(any(e["expected"] == "ʁ" and e["recognized"] == "ɹ" for e in events))
        self.assertTrue(any(e["operation"] == "ins" and e["recognized"] == "ə" for e in events))
        self.assertEqual(evidence["expectedTokens"][1], "ãː")
        self.assertEqual(forensics.french(["ʁ"], {"phones": heard})["inputStatus"], "partial")
        self.assertEqual(forensics.french(None, {})["inputStatus"], "unavailable")

    def test_no_temporal_consensus_for_distinct_local_events(self):
        evidence = forensics.french(["ʁ"], {
            "phones": {"phones": [{"phone": "ɹ", "start": 0, "end": .05}]},
            "phonesB": {"phones": [{"phone": "ɹ", "start": 1, "end": 1.05}]}})
        self.assertEqual(evidence["agreedEvents"], [])

    def test_local_vowel_acoustics_retain_quiet_unvoiced_evidence(self):
        profile = {"time": np.array([0, .01, .02]), "level": np.array([-30, -44, -44]),
                   "periodicity": np.array([.9, .1, .1]), "centroid": np.array([800, 5000, 5000])}
        value = forensics.local_acoustics({"phones": {"phones": [
            {"phone": "y", "start": .01, "end": .03}, {"phone": "t", "start": 0, "end": .01}]}}, profile, -30)
        windows = value["roles"]["phones"]["windows"]
        self.assertEqual(len(windows), 1)
        self.assertEqual(windows[0]["levelRelativeSpeechDb"], -14)
        self.assertEqual(windows[0]["medianPeriodicity"], .1)
        self.assertEqual(value["decision"], "not-assessed")

    def test_malformed_pitch_results_abstain_without_aborting_analysis(self):
        malformed = {"outputs": {"hopSeconds": 0, "f0Hz": [100]}}
        value = features.pitch_features({}, {"pitchA": malformed, "pitchB": malformed}, {}, {})
        self.assertTrue(all(v["value"] is None for v in value.values()))
        self.assertEqual(features.build_context({"x": {"pitchA": malformed, "pitchB": malformed}}, {}),
                         {"referencePitch": {}, "referencePitchSummary": {}})
        self.assertFalse(fidelity.pitch_section((malformed["outputs"], malformed["outputs"]), None)["available"])

    def test_invalid_speaker_vector_is_unavailable(self):
        self.assertIsNone(features._cosine_distance([float("nan")], [1]))
        self.assertIsNone(features._cosine_distance([0], [1]))


if __name__ == "__main__":
    unittest.main()
