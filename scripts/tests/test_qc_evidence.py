"""Perceptual evidence integration: provenance, bounded cache reads and abstention."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from qc import evidence, store


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.layout = store.Layout(Path(self.temp.name))
        self.digest = "a" * 64
        self.path = store.result_npz_path(self.layout, "phones-model", self.digest)
        self.path.parent.mkdir(parents=True)
        self.output = {"posteriors": self.path.name}

    def tearDown(self):
        self.temp.cleanup()

    def write(self, **changes):
        values = dict(logprobs=np.log(np.full((8, 3), 1 / 3, dtype=np.float32)),
                      vocab=np.array(["<pad>", "a", "b"]), frameSeconds=np.array(.02))
        values.update(changes)
        np.savez(self.path, **values)

    def load(self, output=None):
        return evidence.load_posteriors(self.layout, "phones-model", self.digest, output or self.output)

    def test_exact_cache_bytes_are_bound_without_claiming_runner_attestation(self):
        self.write()
        values, provenance = self.load()
        self.assertEqual(values["logprobs"].shape, (8, 3))
        self.assertEqual(provenance["sha256"], store.sha256_file(self.path))
        self.assertEqual(provenance["binding"], "observed-cache-bytes-not-runner-attested")

    def test_path_mismatch_symlink_missing_and_oversize_abstain(self):
        self.write()
        for name in ("../" + self.path.name, "b" * 64 + ".npz", str(self.path)):
            with self.subTest(name=name):
                self.assertIsNone(self.load({"posteriors": name})[0])
        with patch.object(evidence, "MAX_ARCHIVE_BYTES", 1):
            self.assertIsNone(self.load()[0])
        saved = self.path.with_suffix(".saved")
        self.path.rename(saved)
        self.path.symlink_to(saved)
        self.assertIsNone(self.load()[0])
        self.path.unlink()
        self.assertIsNone(self.load()[0])

    def test_unsafe_or_malformed_arrays_abstain(self):
        for changes in ({"vocab": np.array([object()], dtype=object)},
                        {"logprobs": np.array([[np.nan, 0, 0]], dtype=np.float32)},
                        {"logprobs": np.zeros(3, dtype=np.float32)},
                        {"vocab": np.array(["a"])}, {"frameSeconds": np.array(0.)},
                        {"frameSeconds": np.array([.02, .02])}):
            with self.subTest(changes=list(changes)):
                self.write(**changes)
                self.assertIsNone(self.load()[0])

    def test_zero_probability_negative_infinity_is_safe_ctc_input(self):
        values = np.full((8, 3), -np.inf, dtype=np.float32)
        values[:, 0] = 0
        self.write(logprobs=values)
        self.assertIsNotNone(self.load()[0])

    def test_expected_windows_reach_acoustics_without_greedy_errors(self):
        window = {"phone": "a", "start": .1, "end": .3}
        pronunciation = {"inputStatus": "complete", "roles": {
            "phones": {"localizedCandidates": [], "posterior": {"expectedWindows": [window]}}}}
        with patch.object(evidence.pronunciation, "analyze", return_value=pronunciation), \
             patch.object(evidence.acoustics, "analyze", return_value={"inputStatus": "complete"}) as acoustic:
            report = evidence.analyze({"language": "french", "audioSHA256": self.digest}, {}, {},
                layout=self.layout, model_ids={}, expected=["a"], words=[], audio=(np.zeros(100), 1000))
        self.assertEqual(acoustic.call_args.kwargs["expected_windows"], [dict(window, source="phones")])
        self.assertEqual(report["decision"], "not-assessed")
        self.assertEqual(report["nativeAccent"]["decision"], "not-assessed")

    def test_candidate_export_preserves_witnesses_and_rejects_unbounded_intervals(self):
        candidates = [{"start": .1, "end": .2}, {"start": -1, "end": .2},
                      {"start": 0, "end": 2}, {"start": None, "end": .1}]
        take = {"token": "one", "audioSHA256": self.digest}
        diagnostic = {"localAcoustics": {"durationSeconds": 1}, "pronunciation": {
            "inputStatus": "complete", "roles": {"phones": {"localizedCandidates": candidates},
                "phonesB": {"localizedCandidates": candidates}}}}
        result = evidence.events_document("run", "b" * 64, {}, [take], [{"perceptualEvidence": diagnostic}])
        events = result["takes"][0]["events"]
        self.assertEqual(len(events), 2)
        self.assertEqual({event["source"] for event in events}, {"phones", "phonesB"})
        self.assertTrue(all(event["status"] == "candidate" for event in events))
        self.assertEqual(result["decision"], "not-assessed")

    def test_no_candidates_is_not_quality_acceptance(self):
        result = evidence.events_document("run", "b" * 64, {},
            [{"token": "one", "audioSHA256": self.digest}], [{}])
        self.assertEqual(result["takes"][0]["inputStatus"], "unavailable")
        self.assertEqual(result["decision"], "not-assessed")
        for name in ("phonation-anomaly", "short-fragment", "boundary-pronunciation"):
            self.assertEqual(result["takes"][0]["dimensions"][name]["inputStatus"], "unavailable")

    def test_new_producers_export_separate_classes_with_provenance(self):
        take = {"token": "one", "audioSHA256": self.digest}
        producers = {name: {"inputStatus": "partial", "candidates": [{"class": name,
            "start": .1, "end": .2, "status": "candidate", "source": "witness",
            "candidateType": "observation", "uncertainties": ["confounded"],
            "expectedTargets": [{"phone": "y", "source": "phones"}]}]}
            for name in ("phonation-anomaly", "short-fragment", "boundary-pronunciation")}
        diagnostic = {"audioDurationSeconds": 1, "localAcoustics": {"candidateProducers": producers},
            "boundaryPronunciation": producers["boundary-pronunciation"]}
        row = evidence.events_document("run", "b" * 64, {}, [take], [{"perceptualEvidence": diagnostic}])["takes"][0]
        self.assertEqual({event["class"] for event in row["events"]}, set(producers))
        self.assertEqual(len({event["id"] for event in row["events"]}), 3)
        self.assertTrue(all(event["uncertainties"] == ["confounded"] for event in row["events"]))
        self.assertEqual(row["inputStatus"], "unavailable")
        self.assertEqual(row["dimensions"]["phonation-anomaly"]["inputStatus"], "partial")
        self.assertNotIn("devoiced", row["dimensions"])

    def test_new_event_intervals_and_collection_are_bounded(self):
        base = {"class": "short-fragment", "status": "candidate", "start": .1, "end": .2}
        observations = [dict(base, start=start, end=end) for start, end in (
            (True, .2), (.1, float("inf")), (float("nan"), .2), (-.1, .2), (.2, .1), (.1, 1.01))]
        observations += [base] * 200
        diagnostic = {"audioDurationSeconds": 1, "localAcoustics": {"candidateProducers": {
            "short-fragment": {"inputStatus": "complete", "candidates": observations}}}}
        row = evidence.events_document("run", "b" * 64, {}, [{"token": "one", "audioSHA256": self.digest}],
            [{"perceptualEvidence": diagnostic}])["takes"][0]
        self.assertEqual(len(row["events"]), 122)
        self.assertTrue(all(event["start"] == .1 and event["end"] == .2 for event in row["events"]))
        self.assertEqual(row["dimensions"]["short-fragment"]["inputStatus"], "partial")
        self.assertEqual(row["dimensions"]["short-fragment"]["export"]["rejected"], 6)
        self.assertEqual(row["dimensions"]["short-fragment"]["export"]["truncated"], 78)

    def test_reviewed_boundary_input_is_forwarded_without_fabrication(self):
        hypotheses = [{"id": "reviewed"}]
        with patch.object(evidence.pronunciation, "analyze", return_value={}), \
             patch.object(evidence.boundary, "analyze", return_value={}) as producer:
            evidence.analyze({"language": "french", "audioSHA256": self.digest,
                "boundaryPronunciationHypotheses": hypotheses}, {}, {}, layout=self.layout,
                model_ids={}, expected=["a"], words=[], audio=None)
        self.assertIs(producer.call_args.kwargs["reviewed_boundaries"], hypotheses)
        self.assertIsNone(producer.call_args.kwargs["duration_seconds"])

    def test_measured_duration_overrides_manifest_hint_without_rounding(self):
        duration = 24001 / 24000
        take = {"token": "one", "audioSHA256": self.digest, "durationSeconds": 999}
        diagnostic = {"audioDurationSeconds": duration, "localAcoustics": {"durationSeconds": round(duration, 6)},
            "pronunciation": {"inputStatus": "complete", "roles": {"phones": {"localizedCandidates": [
                {"start": .1, "end": .2, "type": "repeat"}, {"start": 1.5, "end": 2}]}}}}
        row = evidence.events_document("run", "b" * 64, {}, [take], [{"perceptualEvidence": diagnostic}])["takes"][0]
        self.assertEqual(row["durationSeconds"], duration)
        self.assertTrue(row["manifestDurationMismatch"])
        self.assertEqual(len(row["events"]), 1)
        self.assertEqual(row["events"][0]["candidateType"], "repeat")

    def test_malformed_output_envelopes_abstain(self):
        for value in ([1], "bad", 3, {"error": "failed"}):
            with self.subTest(value=value):
                results = {role: {"outputs": value} for role in ("phones", "phonesB", "pitchA", "pitchB", "speaker")}
                result = evidence.analyze({"language": "english", "audioSHA256": self.digest}, results,
                    {"referenceResults": {None: results}}, layout=self.layout, model_ids={},
                    expected=None, words=[], audio=None)
                self.assertEqual(result["decision"], "not-assessed")
                self.assertFalse(result["cloneIdentity"]["available"])

    def test_invalid_inner_phones_and_speaker_windows_abstain(self):
        for tokens in (None, 42, "bad"):
            with self.subTest(tokens=tokens):
                result = evidence.analyze({"language": "english", "audioSHA256": self.digest},
                    {"phones": {"outputs": {"phones": tokens}}, "speaker": {"outputs": {
                        "whole": [1, 2], "reference": [1, 2], "windows": [42]}}}, {},
                    layout=self.layout, model_ids={}, expected=None, words=[], audio=None)
                self.assertEqual(result["decision"], "not-assessed")
                self.assertEqual(result["cloneIdentity"]["reason"], "invalid-speaker-embeddings")

    def test_recognized_window_collection_is_bounded(self):
        tokens = [{"phone": "a", "start": .1, "end": .2}] * (acoustics_limit := evidence.acoustics.MAX_WINDOWS * 2)
        with patch.object(evidence.acoustics, "analyze", return_value={}) as acoustic:
            evidence.analyze({"language": "english", "audioSHA256": self.digest},
                {"phones": {"outputs": {"phones": tokens}}}, {}, layout=self.layout, model_ids={},
                expected=None, words=[], audio=(np.zeros(100), 1000))
        self.assertLess(len(acoustic.call_args.kwargs["recognized_windows"]), acoustics_limit)
        self.assertEqual(len(acoustic.call_args.kwargs["recognized_windows"]), evidence.acoustics.MAX_WINDOWS + 1)


if __name__ == "__main__":
    unittest.main()
