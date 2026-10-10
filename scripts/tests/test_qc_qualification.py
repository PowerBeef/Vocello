"""Private event qualification is leakage-safe, byte-bound and always report-only."""
from __future__ import annotations

import copy
import json
import struct
import sys
import tempfile
import unittest
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from qc import qualification as q, store  # noqa: E402


def event(identity="label", start=0.2, end=0.4, class_id="devoiced"):
    return {"id": identity, "class": class_id, "start": start, "end": end}


class QualificationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.layout = store.Layout(Path(self.temporary.name))
        self.run_id = "qc-retained-1"
        self.directory = self.layout.runs / self.run_id
        self.directory.mkdir(parents=True)
        self.scoring = "a" * 64
        self.models = {"phones": {"id": "phones.fixture", "runnerSHA256": "b" * 64}}
        self.takes, self.evidence, panel_rows = [], [], []
        for index, split in enumerate(("train", "calibration", "heldout")):
            token = f"{index:016x}"
            audio = self.layout.private / f"audio-{index}.wav"
            with wave.open(str(audio), "wb") as handle:
                handle.setnchannels(1)
                handle.setsampwidth(2)
                handle.setframerate(100)
                handle.writeframes(struct.pack("<100h", *([index + 1] * 100)))
            digest = store.sha256_file(audio)
            self.takes.append({"token": token, "audio": str(audio), "audioSHA256": digest,
                               "reference": None, "referenceSHA256": None})
            self.evidence.append({"token": token, "audioSHA256": digest, "durationSeconds": 1.0,
                                  "inputStatus": "complete", "dimensions": {},
                                  "events": [dict(event("candidate"), source="fixture", status="candidate")]})
            panel_rows.append({"token": token, "audioSHA256": digest, "split": split,
                               "groups": {group: None if group == "reference" else f"{group}-{index}"
                                          for group in q.GROUPS},
                               "origin": "human-observed", "labelCoverage": {"devoiced": "complete"},
                               "events": [event()]})
        self.panel = {"schema": q.PANEL_SCHEMA, "id": "protected-panel", "purpose": "challenge",
                      "scoringSHA256": self.scoring, "models": self.models, "classes": ["devoiced"],
                      "annotationProtocolSHA256": "c" * 64,
                      "policy": {"minimumIntersectionOverUnion": 0.5}, "takes": panel_rows}
        self.panel["policySHA256"] = store.sha256_text(store.canonical_json(self.panel["policy"]))
        self.panel_path = self.layout.private / "panel.json"
        self.write()

    def write(self):
        store.write_json_atomic(self.panel_path, self.panel)
        store.write_json_atomic(self.directory / "takes.json", {"schema": store.TAKES_SCHEMA, "takes": self.takes})
        store.write_json_atomic(self.directory / "features.json", {
            "schema": "vocello.qc.features/1", "run": self.run_id,
            "scoringSHA256": self.scoring, "models": self.models,
            "takes": [{"token": take["token"]} for take in self.takes]})
        store.write_json_atomic(self.directory / "events.json", {
            "schema": q.EVENTS_SCHEMA, "run": self.run_id, "scoringSHA256": self.scoring,
            "models": self.models, "takes": self.evidence})

    def evaluate(self, name="test-eval"):
        self.write()
        return q.evaluate(self.layout, self.panel_path, run_ids=[self.run_id], name=name)

    def refused(self, expression):
        with self.assertRaisesRegex((q.QualificationError, OSError), expression):
            self.evaluate()
        self.assertFalse((self.layout.private / "qualification/test-eval/report.json").exists())

    def test_matching_is_report_only_and_uses_only_heldout(self):
        self.evidence[0]["events"] = []
        path, report = self.evaluate()
        self.assertTrue(path.is_relative_to(self.layout.private.resolve()))
        self.assertEqual(store.read_json(path), report)
        self.assertEqual(report["qualification"], "not-qualified")
        self.assertTrue(report["reportOnly"])
        self.assertFalse(report["acceptancePolicyChanged"])
        self.assertEqual(report["evaluator"]["contract"], q.MATCHING_CONTRACT)
        self.assertEqual(report["evaluator"]["sha256"], store.sha256_file(q.__file__))
        measured = report["classes"]["devoiced"]
        self.assertEqual((measured["truePositives"], measured["falsePositives"], measured["falseNegatives"]), (1, 0, 0))
        self.assertEqual(measured["recall"], 1.0)
        self.assertEqual(report["splits"], {"train": 1, "calibration": 1, "heldout": 1})
        self.assertEqual(set(report["runFiles"][self.run_id]), {"takes.json", "features.json", "events.json"})
        self.assertFalse(self.layout.config.exists())
        self.assertFalse((self.layout.root / "benchmarks").exists())

    def test_multiple_same_class_events_and_duplicate_candidates_match_once(self):
        self.panel["takes"][2]["events"] = [event("a", 0.1, 0.2), event("b", 0.6, 0.8)]
        self.evidence[2]["events"] = [dict(event(identity, start, end), status="candidate")
                                      for identity, start, end in (("x", 0.1, 0.2), ("y", 0.1, 0.2), ("z", 0.6, 0.8))]
        _, report = self.evaluate()
        metrics = report["classes"]["devoiced"]
        self.assertEqual((metrics["truePositives"], metrics["falsePositives"], metrics["falseNegatives"]), (2, 1, 0))
        self.assertAlmostEqual(metrics["precision"], 2 / 3, places=5)

    def test_maximum_matching_does_not_greedily_lose_a_valid_pair(self):
        truth = [event("a", 0, 0.6), event("b", 0.4, 1)]
        candidates = [event("x", 0.2, 0.8), event("y", 0, 0.5)]
        self.assertEqual(q._matches(truth, candidates, 0.4), [(0, 1), (1, 0)])

    def test_nonoverlap_is_miss_and_false_alarm(self):
        self.evidence[2]["events"][0].update(start=0.6, end=0.8)
        _, report = self.evaluate()
        metrics = report["classes"]["devoiced"]
        self.assertEqual((metrics["truePositives"], metrics["falsePositives"], metrics["falseNegatives"]), (0, 1, 1))
        self.assertEqual(metrics["clipMissRate"], 1.0)

    def test_unavailable_input_is_coverage_loss_not_a_clean_pass(self):
        self.evidence[2]["inputStatus"] = "unavailable"
        _, report = self.evaluate()
        metrics = report["classes"]["devoiced"]
        self.assertEqual(metrics["inputCoverage"]["rate"], 0)
        self.assertEqual(metrics["falseNegatives"], 1)
        self.assertEqual(metrics["recall"], 0)
        self.assertIsNone(metrics["conditionalRecall"])
        self.assertEqual(metrics["takes"][0]["status"], "abstained")

    def test_dimension_unsupported_overrides_complete_aggregate_input(self):
        self.evidence[2]["dimensions"] = {"devoiced": {"inputStatus": "unsupported"}}
        _, report = self.evaluate()
        self.assertEqual(report["classes"]["devoiced"]["inputCoverage"]["rate"], 0)

    def test_explicit_not_assessed_dimension_is_not_assumed_supported(self):
        self.evidence[2]["dimensions"] = {"devoiced": {"decision": "not-assessed"}}
        _, report = self.evaluate()
        self.assertEqual(report["classes"]["devoiced"]["inputCoverage"]["rate"], 0)

    def test_unreviewed_empty_labels_do_not_become_negative_examples(self):
        row = self.panel["takes"][2]
        row.update(events=[], labelCoverage={"devoiced": "unreviewed"})
        _, report = self.evaluate()
        metrics = report["classes"]["devoiced"]
        self.assertEqual(metrics["cleanClips"], 0)
        self.assertEqual(metrics["falsePositives"], 0)
        self.assertIsNone(metrics["precision"])
        self.assertIsNone(metrics["recall"])

    def test_clean_clip_false_positive_and_rate_are_separate(self):
        self.panel["takes"][2]["events"] = []
        _, report = self.evaluate()
        metrics = report["classes"]["devoiced"]
        self.assertEqual(metrics["cleanClips"], 1)
        self.assertEqual(metrics["falsePositiveClips"], 1)
        self.assertEqual(metrics["cleanClipFalsePositiveRate"], 1)
        self.assertEqual(metrics["falseAlarmsPerMinute"], 60)
        self.assertIsNone(metrics["recall"])

    def test_positive_only_annotation_does_not_support_precision(self):
        self.panel["takes"][2]["labelCoverage"]["devoiced"] = "positive-only"
        _, report = self.evaluate()
        self.assertEqual(report["classes"]["devoiced"]["recall"], 1)
        self.assertIsNone(report["classes"]["devoiced"]["precision"])

    def test_synthetic_control_can_never_qualify_real_failure_acceptance(self):
        self.panel["takes"][2]["origin"] = "synthetic-control"
        _, report = self.evaluate()
        self.assertEqual(report["qualification"], "not-qualified")
        self.assertIn("synthetic-controls-do-not-establish-real-failure-recall", report["limitations"])

    def test_each_group_kind_is_disjoint_across_splits(self):
        original = copy.deepcopy(self.panel)
        for kind in q.GROUPS:
            with self.subTest(kind=kind):
                self.panel = copy.deepcopy(original)
                self.panel["takes"][0]["groups"][kind] = "shared"
                self.panel["takes"][2]["groups"][kind] = "shared"
                self.refused(f"{kind} group leaks")

    def test_identical_audio_is_disjoint_even_when_declared_groups_lie(self):
        self.takes[2].update(audio=self.takes[0]["audio"], audioSHA256=self.takes[0]["audioSHA256"])
        self.panel["takes"][2]["audioSHA256"] = self.takes[0]["audioSHA256"]
        self.evidence[2]["audioSHA256"] = self.takes[0]["audioSHA256"]
        self.refused("identical audio leaks")

    def test_missing_group_identity_and_reference_group_are_refused(self):
        del self.panel["takes"][2]["groups"]["source"]
        self.refused("group identities are required")
        self.panel["takes"][2]["groups"]["source"] = "source-2"
        self.takes[2]["referenceSHA256"] = "f" * 64
        self.refused("reference group is missing")

    def test_reference_audio_identity_cannot_be_hidden_by_different_declared_groups(self):
        for index in (0, 2):
            self.takes[index].update(reference=self.takes[1]["audio"],
                                     referenceSHA256=self.takes[1]["audioSHA256"])
            self.panel["takes"][index]["groups"]["reference"] = f"reference-{index}"
        self.refused("identical reference audio leaks")
        self.takes[2]["referenceSHA256"] = "f" * 64
        self.refused("reference bytes differ")

    def test_malformed_or_out_of_duration_spans_are_refused(self):
        for start, end in ((-1, 0.2), (0.3, 0.2), (0.2, 0.2), (0.2, 1.1), (float("nan"), 0.2), (True, 0.2)):
            with self.subTest(start=start, end=end):
                self.panel["takes"][2]["events"] = [event(start=start, end=end)]
                self.refused("span|finite")
        self.panel["takes"][2]["events"] = [event()]
        self.evidence[2]["events"][0]["end"] = float("inf")
        self.refused("finite")

    def test_unknown_label_class_duplicate_event_or_non_candidate_is_refused(self):
        self.panel["takes"][2]["events"] = [event(class_id="unknown")]
        self.refused("outside the panel classes")
        self.panel["takes"][2]["events"] = [event(), event()]
        self.refused("duplicate event id")
        self.panel["takes"][2]["events"] = [event()]
        self.evidence[2]["events"][0]["status"] = "qualified-failure"
        self.refused("descriptive candidates")

    def test_audio_bytes_identity_and_duration_are_verified(self):
        self.evidence[2]["audioSHA256"] = "f" * 64
        self.refused("audio identity differs")
        self.evidence[2]["audioSHA256"] = self.takes[2]["audioSHA256"]
        self.evidence[2]["durationSeconds"] = 2
        self.refused("duration differs")
        self.evidence[2]["durationSeconds"] = 1
        Path(self.takes[2]["audio"]).write_bytes(b"changed bytes")
        self.refused("audio bytes differ")

    def test_scoring_model_and_policy_identity_drift_are_refused(self):
        for key in ("scoringSHA256", "policySHA256"):
            with self.subTest(key=key):
                original = self.panel[key]
                self.panel[key] = "f" * 64
                self.refused("identity|digest mismatch")
                self.panel[key] = original
        self.panel["models"] = {"phones": {"id": "changed", "runnerSHA256": "f" * 64}}
        self.refused("model identities differ")

    def test_missing_explicit_label_coverage_no_heldout_and_duplicate_takes_refuse(self):
        row = self.panel["takes"][2]
        row["labelCoverage"] = {}
        self.refused("annotation coverage")
        row["labelCoverage"] = {"devoiced": "complete"}
        row["split"] = "train"
        self.refused("no protected heldout")
        row["split"] = "heldout"
        self.panel["takes"].append(copy.deepcopy(row))
        self.refused("duplicate or unavailable")

    def test_output_identity_is_immutable_and_paths_stay_private(self):
        path, _ = self.evaluate()
        original = path.read_bytes()
        with self.assertRaisesRegex(q.QualificationError, "already exists"):
            self.evaluate()
        self.assertEqual(path.read_bytes(), original)
        self.assertRaises(q.QualificationError, q.evaluate, self.layout, self.panel_path,
                          run_ids=["../escaped"], name="other")
        external = self.layout.root / "panel.json"
        external.write_text(json.dumps(self.panel))
        self.assertRaises(q.QualificationError, q.evaluate, self.layout, external,
                          run_ids=[self.run_id], name="other")

    def test_run_inventory_or_identity_mismatch_refuses(self):
        self.write()
        path = self.directory / "events.json"
        document = store.read_json(path)
        for mutate in (lambda value: value.update(run="other"),
                       lambda value: value.update(scoringSHA256="f" * 64),
                       lambda value: value["takes"].pop()):
            changed = copy.deepcopy(document)
            mutate(changed)
            store.write_json_atomic(path, changed)
            with self.assertRaises(q.QualificationError):
                q.evaluate(self.layout, self.panel_path, run_ids=[self.run_id])

    def test_malformed_retained_documents_refuse_without_writing_a_report(self):
        self.write()
        for filename in ("takes.json", "features.json", "events.json"):
            path = self.directory / filename
            original = path.read_bytes()
            for malformed in ([], {"schema": store.TAKES_SCHEMA, "takes": [None]}):
                store.write_json_atomic(path, malformed)
                with self.assertRaises(q.QualificationError):
                    q.evaluate(self.layout, self.panel_path, run_ids=[self.run_id])
            path.write_bytes(original)


if __name__ == "__main__":
    unittest.main()
