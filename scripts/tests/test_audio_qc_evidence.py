#!/usr/bin/env python3
"""The take-evidence schema and the private bundle (AQ-05, audit section 3.6)."""

from __future__ import annotations

import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.qc_pipeline.evidence import (  # noqa: E402
    PRIVATE_SCHEMA,
    TAKE_EVIDENCE_SCHEMA,
    EvidenceError,
    failing,
    validate_private_bundle,
    validate_take_evidence,
    write_private_bundle,
)
from lib.qc_pipeline.verdicts import channel_detectors, compose_take, stage0_detector  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
SHA = "a" * 64


def record(take_id: str = "custom-en-pinned", **overrides) -> dict:
    composed = compose_take("language-bench", [
        stage0_detector({"algorithmVersion": 8, "verdict": "pass", "instabilityVerdict": "pass",
                         "writtenOutputVerdict": "pass"}),
        *channel_detectors({"whisper": [{"language": True, "accuracy": True}]}, unqualified=[], unavailable={}),
    ])
    value = {
        "schema": TAKE_EVIDENCE_SCHEMA,
        "take": {"takeID": take_id, "audioSHA256": SHA, "canonicalPCMSHA256": "b" * 64,
                 "canonicalSampleRateHz": 16000, "durationSeconds": 2.0, "textSHA256": "c" * 64,
                 "language": "english", "role": None, "expectedOutcome": "pass"},
        "registries": {"judges": "d" * 64, "detectors": None, "policy": "e" * 64},
        "stage0": {"audioQC": {"algorithmVersion": 8, "verdict": "pass", "flags": []}},
        "measurements": [{"judge": "asr.whisper-small@1", "outputIdentity": "f" * 64, "status": "complete",
                          "metrics": {"errorRate": 0.0, "detectedLanguage": "english", "metric": "WER"},
                          "metricsSHA256": SHA, "transcriptSHA256": SHA, "wallSeconds": 0.2, "reasons": [],
                          "cache": {"l1": "miss", "l2": "miss"}}],
        "verdicts": composed["verdicts"],
        "takeVerdict": {key: composed[key] for key in ("lane", "status", "composition", "decidedBy", "reasons")},
        "legacyVerdicts": {"languageWitness": {"status": "one-witness", "expectationMet": True, "families": ["whisper"],
                                               "reasons": []}},
    }
    value.update(overrides)
    return value


class TakeEvidenceTests(unittest.TestCase):
    def test_a_record_of_digests_and_metrics_validates(self) -> None:
        value = record()
        self.assertEqual(validate_take_evidence(value), [])
        self.assertEqual(value["takeVerdict"]["status"], "uncalibrated")
        # Fast QC v8 cites its legacy-unqualified Stage 0 record (A10).
        fastqc = {item["detector"]: item for item in value["verdicts"]}["signal.fastqc@8"]
        self.assertEqual(fastqc["calibration"]["level"], "legacy-unqualified")

    def test_text_paths_and_unknown_shapes_are_refused(self) -> None:
        cases = {
            "a transcript key": lambda v: v["measurements"][0]["metrics"].update(transcript="words"),
            "a nested reference text": lambda v: v["legacyVerdicts"]["languageWitness"].update(referenceText="x"),
            "a sentence value": lambda v: v["measurements"][0]["metrics"].update(detectedLanguage="the quiet garden"),
            "an absolute path": lambda v: v["legacyVerdicts"]["languageWitness"].update(source="/Users/example/a.wav"),
            "a relative path": lambda v: v["legacyVerdicts"]["languageWitness"].update(source="Users/example/a.wav"),
            "a nested metric": lambda v: v["measurements"][0]["metrics"].update(word={"substitutions": 1}),
            "a non-finite number": lambda v: v["measurements"][0]["metrics"].update(errorRate=float("nan")),
            "an extra field": lambda v: v.update(audio="base64"),
            "an unknown judge id": lambda v: v["measurements"][0].update(judge="whisper"),
            "a missing cache state": lambda v: v["measurements"][0].pop("cache"),
            "an unknown take status": lambda v: v["takeVerdict"].update(status="ok"),
            "a malformed digest": lambda v: v["take"].update(audioSHA256="abc"),
        }
        for label, mutate in cases.items():
            value = record()
            mutate(value)
            with self.subTest(case=label):
                self.assertTrue(validate_take_evidence(value), label)

    def test_failing_takes_are_named(self) -> None:
        self.assertFalse(failing(record()))
        missed = record(legacyVerdicts={"languageWitness": {"status": "one-witness", "expectationMet": False}})
        self.assertTrue(failing(missed))
        self.assertTrue(failing(record(legacyVerdicts={"pairRoute": {"status": "rejected"}})))
        self.assertFalse(failing(record(legacyVerdicts={"languageWitness": {"status": "inconclusive"}})))


class PrivateBundleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _private(self, take_id: str) -> dict:
        return {"schema": PRIVATE_SCHEMA, "takeID": take_id, "audioPath": str(self.root / f"{take_id}.wav"),
                "referenceText": "The quiet garden opens early.", "transcripts": {"asr.whisper-small@1": "the quiet"}}

    def _write(self, bundle: Path) -> dict:
        takes = [(record("take-one"), self._private("take-one")),
                 (record("take-two", legacyVerdicts={"languageWitness": {"status": "fail"}}), self._private("take-two"))]
        return write_private_bundle(bundle, header={"runID": "run-1", "lane": "language-bench"}, takes=takes,
                                    repository=self.root)

    def test_a_bundle_validates_and_names_its_failing_takes(self) -> None:
        bundle = self.root / "build" / "audio-qc" / "run-1"
        written = self._write(bundle)
        self.assertEqual(written["failingTakes"], 1)
        self.assertEqual(validate_private_bundle(bundle, repository=self.root), [])
        # Private data stays in private/; the records never carry it.
        private_text = (bundle / "private/0001.json").read_text(encoding="utf-8")
        self.assertIn("quiet garden", private_text)
        self.assertNotIn("quiet garden", (bundle / "evidence/0001.json").read_text(encoding="utf-8"))

    def test_tampering_misplacement_and_overwrites_are_refused(self) -> None:
        bundle = self.root / "build" / "run-1"
        self._write(bundle)
        evidence = bundle / "evidence/0001.json"
        payload = json.loads(evidence.read_text(encoding="utf-8"))
        payload["takeVerdict"]["status"] = "pass"
        evidence.write_text(json.dumps(payload), encoding="utf-8")
        self.assertTrue(any("changed" in error for error in validate_private_bundle(bundle, repository=self.root)))
        with self.assertRaisesRegex(EvidenceError, "written once"):
            self._write(bundle)
        # Inside the repository, only the build root holds a bundle.
        with self.assertRaisesRegex(EvidenceError, "tracked paths"):
            self._write(self.root / "benchmarks" / "run-1")
        self.assertTrue(validate_private_bundle(self.root / "docs", repository=self.root))
        with self.assertRaisesRegex(EvidenceError, "unsafe"):
            write_private_bundle(self.root / "build" / "unsafe", header={"note": "a sentence with spaces"},
                                 takes=[(record(), self._private("custom-en-pinned"))], repository=self.root)
        unsafe = copy.deepcopy(record())
        unsafe["measurements"][0]["metrics"]["transcript"] = "words"
        with self.assertRaisesRegex(EvidenceError, "may not appear"):
            write_private_bundle(self.root / "build" / "bad", header={}, takes=[(unsafe, self._private("x"))],
                                 repository=self.root)


if __name__ == "__main__":
    unittest.main()
