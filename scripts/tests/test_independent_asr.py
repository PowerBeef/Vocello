#!/usr/bin/env python3
"""Producer tests with the recognizer subprocess mocked; no model ever loads here."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest import mock
import wave

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import independent_asr  # noqa: E402
from delivery_analysis_cache import (  # noqa: E402
    DeliveryAnalysisCache, RESAMPLER_VERSION, canonicalization_identity, digest, file_sha256,
)
from delivery_resource_supervisor import SupervisedResult  # noqa: E402
from lib.language_metrics import INDEPENDENT_ASR_ALGORITHM, recognition_issues, text_sha256  # noqa: E402


SCRIPT = "The quiet garden is open today."


def write_wave(path: Path, *, seconds: float = 2.0, rate: int = 24_000) -> None:
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(rate)
        output.writeframes(struct.pack("<h", 800) * int(seconds * rate))


def envelope(**overrides) -> dict:
    report = {
        "qualified": True, "qualificationFailures": [], "peakRSSBytes": 900 * 1024**2,
        "wallSeconds": 3.2, "postExitMemoryRecovered": True, "returnCode": 0,
    }
    report.update(overrides)
    return report


class IndependentASRTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.wav = self.root / "cell.wav"
        write_wave(self.wav)
        self.weights = self.root / "weights.npz"
        self.weights.write_bytes(b"fixture weights")
        (self.root / "config.json").write_text("{}")
        preprocessing = {
            "sampleRateHz": 16000, "channels": 1, "format": "pcm-s16le",
            "canonicalizationIdentity": canonicalization_identity(RESAMPLER_VERSION),
        }
        label_map = {"type": "locked-language-transcript",
                     "languages": {"english": "en", "french": "fr", "japanese": "ja"}}
        self.config = {
            "schemaVersion": 1,
            "adapterID": "whisper-small-mlx",
            "modelID": "mlx-community/whisper-small-mlx",
            "sourceRevision": "revision-fixture",
            "weightsPath": str(self.weights),
            "weightsSHA256": file_sha256(self.weights),
            "binaryPath": sys.executable,
            "binarySHA256": file_sha256(Path(sys.executable)),
            "license": "Apache-2.0-fixture",
            "commercialUseCompatible": True,
            "trainingDataDeclaration": "fixture",
            "labelMap": label_map,
            "labelMapDigest": digest(label_map),
            "preprocessingConfig": preprocessing,
            "preprocessingConfigDigest": digest(preprocessing),
            "offlineAfterAcquisition": True,
            "outputFormat": "whisper-json",
            "decodeOptions": {"temperature": 0.0, "conditionOnPreviousText": False, "fp16": True},
            "commandTemplate": [sys.executable, "independent_asr.py", "worker", "--weights", "{weights}",
                                "--audio", "{audio}", "{binary}"],
        }
        self.cache = DeliveryAnalysisCache(self.root / "cache")
        self.manifest = {
            "schemaVersion": 1, "kind": "independent-asr-manifest", "runID": "run-1",
            "platform": "macos", "generationProcessExited": True,
            "rows": [{
                "id": "en", "generationID": "gen-en", "audioPath": str(self.wav),
                "audioSHA256": file_sha256(self.wav), "durationSeconds": 2.0,
                "expectedLanguage": "english", "referenceText": SCRIPT,
                "scriptSHA256": text_sha256(SCRIPT), "expectedOutcome": "pass",
            }],
        }
        self.launches: list[list[str]] = []

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def supervisor(self, command, **kwargs):
        """Stand in for the whisper worker: read the job, answer every row."""
        self.launches.append(list(command))
        self.assertEqual(command[2], "worker")
        job = json.loads(Path(command[4]).read_text())
        self.assertEqual(job["weights"], str(self.weights))
        self.assertEqual(kwargs["maximum_rss_bytes"], independent_asr.MAXIMUM_RSS_BYTES)
        self.assertEqual(kwargs["environment"]["HF_HUB_OFFLINE"], "1")
        rows = []
        for row in job["rows"]:
            self.assertTrue(Path(row["pcmPath"]).is_file())
            self.assertEqual(row["language"], "en")
            rows.append({
                "id": row["id"], "transcript": SCRIPT, "language": "en", "detectedLanguage": "en",
                "detectedLanguageProbability": 0.98, "expectedLanguageProbability": 0.98,
                "segments": [{"start": 0.0, "end": 1.9, "noSpeechProb": 0.01, "avgLogprob": -0.2}],
                "wallSeconds": 0.4,
            })
        payload = {"schemaVersion": 1, "kind": "independent-asr-worker-output", "rows": rows}
        return SupervisedResult(envelope(), json.dumps(payload).encode(), b"")

    def test_manifest_must_declare_generator_exit(self) -> None:
        manifest = copy.deepcopy(self.manifest)
        manifest["generationProcessExited"] = False
        with self.assertRaisesRegex(independent_asr.IndependentASRError, "generator process must have exited"):
            independent_asr.transcribe_manifest(
                manifest=manifest, config=self.config, cache=self.cache,
                lock_root=self.root, supervisor=self.supervisor,
            )
        self.assertEqual(self.launches, [])

    def test_one_launch_emits_bound_recognitions_and_the_rerun_is_a_cache_hit(self) -> None:
        evidence = independent_asr.transcribe_manifest(
            manifest=self.manifest, config=self.config, cache=self.cache,
            lock_root=self.root, supervisor=self.supervisor,
        )
        self.assertEqual(len(self.launches), 1)
        self.assertEqual(evidence["kind"], "independent-asr-language-evidence")
        self.assertEqual(evidence["families"], ["whisper"])
        self.assertEqual(evidence["producer"]["modelLaunches"], 1)
        self.assertEqual(evidence["producer"]["algorithmVersion"], INDEPENDENT_ASR_ALGORITHM)
        cell = evidence["cells"]["en"]
        self.assertEqual(cell["generationID"], "gen-en")
        recognition = cell["recognitions"][0]
        self.assertEqual(recognition_issues(
            recognition, audio_sha256=file_sha256(self.wav), script=SCRIPT,
            script_sha256=text_sha256(SCRIPT), language="english", duration_seconds=2.0,
        ), [])
        self.assertEqual(recognition["detectedLanguage"], "english")
        self.assertTrue(recognition["fullFileProcessed"])
        self.assertEqual(recognition["languageMatchScore"], 0.98)
        self.assertNotIn(str(self.root), json.dumps(evidence))

        def must_not_launch(*_args, **_kwargs):
            raise AssertionError("cache hit launched the recognizer")

        again = independent_asr.transcribe_manifest(
            manifest=self.manifest, config=self.config, cache=self.cache,
            lock_root=self.root, supervisor=must_not_launch,
        )
        self.assertEqual(again["producer"]["modelLaunches"], 0)
        self.assertEqual(again["producer"]["cacheHits"], 1)
        self.assertEqual(again["cells"], evidence["cells"])

    def test_edge_coverage_and_empty_transcripts_are_reported_not_hidden(self) -> None:
        def short_read(command, **kwargs):
            job = json.loads(Path(command[4]).read_text())
            rows = [{
                "id": row["id"], "transcript": "", "language": "en", "detectedLanguage": "fr",
                "detectedLanguageProbability": 0.6, "expectedLanguageProbability": 0.3,
                "segments": [{"start": 0.0, "end": 0.4, "noSpeechProb": 0.9, "avgLogprob": -1.0}],
                "wallSeconds": 0.1,
            } for row in job["rows"]]
            payload = {"schemaVersion": 1, "kind": "independent-asr-worker-output", "rows": rows}
            return SupervisedResult(envelope(), json.dumps(payload).encode(), b"")

        evidence = independent_asr.transcribe_manifest(
            manifest=self.manifest, config=self.config, cache=self.cache,
            lock_root=self.root, supervisor=short_read,
        )
        recognition = evidence["cells"]["en"]["recognitions"][0]
        self.assertFalse(recognition["fullFileProcessed"])
        self.assertEqual(recognition["status"], "empty")
        self.assertEqual(recognition["detectedLanguage"], "french")
        issues = recognition_issues(
            recognition, audio_sha256=file_sha256(self.wav), script=SCRIPT,
            script_sha256=text_sha256(SCRIPT), language="english", duration_seconds=2.0,
        )
        self.assertIn("partial-file", issues)
        self.assertIn("incomplete", issues)

    def test_unqualified_envelope_or_changed_audio_refuses(self) -> None:
        def over_ceiling(command, **kwargs):
            return SupervisedResult(
                envelope(qualified=False, qualificationFailures=["provisional-rss-ceiling-exceeded"]),
                b"{}", b"Traceback: boom",
            )
        with self.assertRaisesRegex(independent_asr.IndependentASRError, "rss-ceiling-exceeded"):
            independent_asr.transcribe_manifest(
                manifest=self.manifest, config=self.config, cache=self.cache,
                lock_root=self.root, supervisor=over_ceiling,
            )
        changed = copy.deepcopy(self.manifest)
        changed["rows"][0]["audioSHA256"] = "0" * 64
        with self.assertRaisesRegex(independent_asr.IndependentASRError, "bytes changed"):
            independent_asr.transcribe_manifest(
                manifest=changed, config=self.config, cache=self.cache,
                lock_root=self.root, supervisor=self.supervisor,
            )
        wrong_adapter = copy.deepcopy(self.config)
        wrong_adapter["adapterID"] = "distilhubert"
        with self.assertRaises(independent_asr.IndependentASRError):
            independent_asr.transcribe_manifest(
                manifest=self.manifest, config=wrong_adapter, cache=self.cache,
                lock_root=self.root, supervisor=self.supervisor,
            )

    def test_macos_manifest_binds_each_cell_to_the_engine_published_digest(self) -> None:
        diagnostics = self.root / "diag"
        (diagnostics / "engine").mkdir(parents=True)
        wav_dir = self.root / "wav"
        wav_dir.mkdir()
        write_wave(wav_dir / "en.wav")
        published = file_sha256(wav_dir / "en.wav")
        row = {"generationID": "gen-en", "notes": {"benchRunID": "run-1", "benchCell": "en",
                                                   "samplingWAVDigest": published}}
        (diagnostics / "engine" / "generations.jsonl").write_text(json.dumps(row) + "\n")
        matrix = self.root / "matrix.json"
        matrix.write_text(json.dumps({"cells": [
            {"id": "en", "quick": True, "expectedHint": "english", "scriptLang": "english"},
            {"id": "hint-only", "quick": True, "expectedHint": "english", "scriptLang": "english",
             "skipOutputVerification": True},
        ]}))
        corpus = self.root / "corpus.json"
        corpus.write_text(json.dumps({"languages": [{"id": "english", "script": SCRIPT}]}))
        manifest = independent_asr.build_macos_manifest(
            diagnostics=diagnostics, run_id="run-1", matrix=matrix, corpus=corpus,
            subset="quick", wav_dir=wav_dir, generation_process_exited=True,
        )
        self.assertEqual([row["id"] for row in manifest["rows"]], ["en"])
        self.assertEqual(manifest["rows"][0]["audioSHA256"], published)
        self.assertEqual(manifest["rows"][0]["scriptSHA256"], text_sha256(SCRIPT))
        independent_asr.validate_manifest(manifest)

        write_wave(wav_dir / "en.wav", seconds=1.0)  # bytes no longer match telemetry
        with self.assertRaisesRegex(independent_asr.IndependentASRError, "differ from the engine"):
            independent_asr.build_macos_manifest(
                diagnostics=diagnostics, run_id="run-1", matrix=matrix, corpus=corpus,
                subset="quick", wav_dir=wav_dir, generation_process_exited=True,
            )

    def test_cascade_manifest_carries_roles_and_review_evidence_shape(self) -> None:
        neutral = self.root / "neutral.wav"
        write_wave(neutral, seconds=1.5)
        cascade_input = self.root / "cascade.json"
        cascade_input.write_text(json.dumps({
            "kind": "source-bound-delivery-cascade-input", "generationProcessExited": True,
            "executionPlanDigest": "d" * 64, "runID": "cascade-run",
            "rows": [{
                "generationID": "g1", "outputLanguage": "english", "referenceText": SCRIPT,
                "instructedWAV": str(self.wav), "instructedSHA256": file_sha256(self.wav),
                "neutralWAV": str(neutral), "neutralSHA256": file_sha256(neutral),
            }],
        }))
        manifest = independent_asr.build_cascade_manifest(cascade_input=cascade_input)
        self.assertEqual([row["role"] for row in manifest["rows"]], ["instructed", "neutral"])
        evidence = independent_asr.transcribe_manifest(
            manifest=manifest, config=self.config, cache=self.cache,
            lock_root=self.root, supervisor=self.supervisor,
        )
        self.assertEqual(evidence["policyID"], "automated-evidence-1")
        self.assertEqual(evidence["executionPlanDigest"], "d" * 64)
        self.assertEqual(set(evidence["rows"]["g1"]), {"instructed", "neutral"})
        self.assertEqual(len(self.launches), 1)


if __name__ == "__main__":
    unittest.main()
