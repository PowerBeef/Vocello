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

import delivery_compact_model_adapter as adapter  # noqa: E402
import delivery_resource_supervisor  # noqa: E402
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
        dependencies = {"mlx": "fixture", "mlx-whisper": "fixture", "numpy": "fixture"}
        # The registry's pinned repository and revision: the load gate refuses any other.
        pins = json.loads((Path(__file__).resolve().parents[2] / "config/audio-qc-judges.json")
                          .read_text(encoding="utf-8"))["judges"][independent_asr.JUDGE_ID]["pins"]
        self.config = adapter.bind_output_identity({
            "schemaVersion": 1,
            "adapterID": "whisper-small-mlx",
            "modelID": pins["repository"],
            "sourceRevision": pins["revision"],
            "weightsPath": str(self.weights),
            "weightsSHA256": file_sha256(self.weights),
            "binaryPath": sys.executable,
            "binarySHA256": file_sha256(Path(sys.executable)),
            "adapterSourceSHA256": file_sha256(independent_asr.WORKER_SOURCE),
            "adapterLayerSHA256": file_sha256(Path(adapter.__file__)),
            "license": "Apache-2.0-fixture",
            "commercialUseCompatible": True,
            "trainingDataDeclaration": "fixture",
            "sourceURI": "https://example.invalid/whisper",
            "trainingDataSourceURI": "https://example.invalid/whisper-data",
            "labelMap": label_map,
            "labelMapDigest": digest(label_map),
            "runtimeDependencies": dependencies,
            "runtimeDependenciesDigest": digest(dependencies),
            "preprocessingConfig": preprocessing,
            "offlineAfterAcquisition": True,
            "outputFormat": "whisper-json",
            "decodeOptions": {"temperature": 0.0, "conditionOnPreviousText": False, "fp16": True},
            "commandTemplate": ["{binary}", str(independent_asr.WORKER_SOURCE), "--weights", "{weights}",
                                "--audio", "{audio}"],
        })
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
        # The recognizer child is its own file (audit #89).
        self.assertEqual(Path(command[1]).name, "independent_asr_worker.py")
        self.assertEqual(command[2], "--job")
        job = json.loads(Path(command[3]).read_text())
        self.assertEqual(job["weights"], str(self.weights))
        self.assertEqual(kwargs["maximum_rss_bytes"], independent_asr.MAXIMUM_RSS_BYTES)
        # MLX: the footprint ceiling is measured and evaluated, never printed unevaluated.
        self.assertIs(kwargs["measure_physical_footprint"], True)
        self.assertEqual(kwargs["environment"]["HF_HUB_OFFLINE"], "1")
        rows = []
        for row in job["rows"]:
            self.assertTrue(Path(row["pcmPath"]).is_file())
            self.assertEqual(row["language"], "en")
            rows.append({
                "id": row["id"], "transcript": SCRIPT, "language": "en", "detectedLanguage": "en",
                "detectedLanguageProbability": 0.98, "expectedLanguageProbability": 0.98,
                "segments": [{"start": 0.0, "end": 1.0, "noSpeechProb": 0.01, "avgLogprob": -0.2},
                             {"start": 1.0, "end": 1.9, "noSpeechProb": 0.03, "avgLogprob": -0.4}],
                "decodedSampleCount": Path(row["pcmPath"]).stat().st_size // 2,
                "sampleRateHz": 16_000,
                "wallSeconds": 0.4,
            })
        payload = {"schemaVersion": 1, "kind": "independent-asr-worker-output",
                   "modelLoadSeconds": 0.3, "warmupSeconds": 0.1, "rows": rows}
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

    def test_the_producer_loads_only_its_registry_judge(self) -> None:
        # The producer names its judge; a config for another judge's model never launches.
        with mock.patch.object(independent_asr, "JUDGE_ID", "compact.sensevoice-small-q8@1"):
            with self.assertRaisesRegex(independent_asr.IndependentASRError, "another model or revision"):
                independent_asr.transcribe_manifest(
                    manifest=self.manifest, config=self.config, cache=self.cache,
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
        # Measured by the recognizer, not copied from the WAV header (audit #89).
        self.assertEqual(recognition["decodedSampleCount"], 32_000)
        self.assertEqual(recognition["processedDurationSeconds"], 2.0)
        self.assertEqual(recognition["maximumNoSpeechProbability"], 0.03)
        self.assertAlmostEqual(recognition["meanAverageLogProbability"], -0.3)
        self.assertEqual(recognition["recognitionDurationSeconds"], 0.4)
        self.assertEqual(evidence["producer"]["modelLoadSeconds"], 0.3)
        self.assertEqual(evidence["producer"]["warmupSeconds"], 0.1)
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

    def test_supervisor_only_change_replays_cached_recognitions_offline(self) -> None:
        """Audit AQ-F47: the supervisor is envelope provenance; it never keys the cache."""
        config = self.config
        first = independent_asr.transcribe_manifest(
            manifest=self.manifest, config=config, cache=self.cache,
            lock_root=self.root, supervisor=self.supervisor,
        )
        self.assertEqual(first["producer"]["modelLaunches"], 1)
        # The launch records the supervisor that measured it (envelope provenance).
        self.assertEqual(first["producer"]["envelopeIdentity"], adapter.envelope_identity())
        changed = self.root / "delivery_resource_supervisor.py"
        changed.write_bytes(Path(delivery_resource_supervisor.__file__).read_bytes()
                            + b"\n# a supervisor-only fix\n")

        def must_not_launch(*_args, **_kwargs):
            raise AssertionError("a supervisor-only change launched the recognizer")

        with mock.patch.object(adapter, "SUPERVISOR_SOURCE", changed):
            replayed = independent_asr.transcribe_manifest(
                manifest=self.manifest, config=config, cache=self.cache,
                lock_root=self.root, supervisor=must_not_launch,
            )
        self.assertEqual(replayed["producer"]["modelLaunches"], 0)
        self.assertEqual(replayed["producer"]["cacheHits"], 1)
        self.assertIsNone(replayed["producer"]["envelopeIdentity"])
        self.assertEqual(replayed["cells"], first["cells"])
        # A decode-option change is an output-identity change: a new recognition.
        relocked = adapter.bind_output_identity({**config, "decodeOptions": {**config["decodeOptions"], "fp16": False}})
        self.assertNotEqual(relocked["outputIdentityDigest"], config["outputIdentityDigest"])
        again = independent_asr.transcribe_manifest(
            manifest=self.manifest, config=relocked, cache=self.cache,
            lock_root=self.root, supervisor=self.supervisor,
        )
        self.assertEqual(again["producer"]["modelLaunches"], 1)

    def test_cache_holds_the_worker_result_and_a_hit_is_derived_by_current_code(self) -> None:
        """The derivation lives in the producer, outside the cache identity, so a
        hit must re-derive rather than serve a stored derivation (review of #89)."""
        independent_asr.transcribe_manifest(
            manifest=self.manifest, config=self.config, cache=self.cache,
            lock_root=self.root, supervisor=self.supervisor,
        )
        entries = list((self.root / "cache" / "layers").rglob("*.json"))
        self.assertEqual(len(entries), 1)
        payload = json.loads(entries[0].read_text())["payload"]
        self.assertEqual(payload["decodedSampleCount"], 32_000)
        self.assertIn("segments", payload)
        for derived in ("id", "provenance", "processedDurationSeconds", "fullFileProcessed"):
            self.assertNotIn(derived, payload)

        derive = independent_asr._recognition

        def edited(*args, **kwargs):
            return {**derive(*args, **kwargs), "derivation": "edited"}

        def must_not_launch(*_args, **_kwargs):
            raise AssertionError("cache hit launched the recognizer")

        with mock.patch.object(independent_asr, "_recognition", side_effect=edited):
            again = independent_asr.transcribe_manifest(
                manifest=self.manifest, config=self.config, cache=self.cache,
                lock_root=self.root, supervisor=must_not_launch,
            )
        self.assertEqual(again["producer"]["cacheHits"], 1)
        self.assertEqual(again["cells"]["en"]["recognitions"][0]["derivation"], "edited")

    def test_byte_identical_audio_is_decoded_once_for_every_row(self) -> None:
        """Pinned and Auto cells of one prompt group regenerate identical audio
        (audit #86); two timed decodes of one identity cannot share a cache entry."""
        twin = self.root / "twin.wav"
        twin.write_bytes(self.wav.read_bytes())
        manifest = copy.deepcopy(self.manifest)
        manifest["rows"].append({**manifest["rows"][0], "id": "en-auto", "generationID": "gen-auto",
                                 "audioPath": str(twin)})
        job_rows: list[list[str]] = []
        timings = iter([0.4, 0.7])

        def timed(command, **kwargs):
            job_rows.append([row["id"] for row in json.loads(Path(command[3]).read_text())["rows"]])
            result = self.supervisor(command, **kwargs)
            payload = json.loads(result.stdout)
            for row in payload["rows"]:
                row["wallSeconds"] = next(timings)
            return SupervisedResult(result.report, json.dumps(payload).encode(), b"")

        evidence = independent_asr.transcribe_manifest(
            manifest=manifest, config=self.config, cache=self.cache,
            lock_root=self.root, supervisor=timed,
        )
        self.assertEqual(job_rows, [["en"]])
        pinned, auto = (evidence["cells"][key]["recognitions"][0] for key in ("en", "en-auto"))
        self.assertEqual(evidence["cells"]["en-auto"]["generationID"], "gen-auto")
        self.assertEqual(pinned, auto)
        self.assertEqual(pinned["recognitionDurationSeconds"], 0.4)
        again = independent_asr.transcribe_manifest(
            manifest=manifest, config=self.config, cache=self.cache,
            lock_root=self.root, supervisor=timed,
        )
        self.assertEqual((again["producer"]["cacheHits"], again["producer"]["modelLaunches"]), (2, 0))

    def test_an_unqualified_recognition_never_confirms_a_negative_control(self) -> None:
        """The publisher refuses a truncated decode; the cohort verdict must not
        count it as the expected failure (review of #44)."""
        def truncated(command, **kwargs):
            result = self.supervisor(command, **kwargs)
            payload = json.loads(result.stdout)
            for row in payload["rows"]:
                row["decodedSampleCount"] = 16_000
                row["transcript"] = "The quiet"
            return SupervisedResult(result.report, json.dumps(payload).encode(), b"")

        manifest = copy.deepcopy(self.manifest)
        manifest["rows"][0]["expectedOutcome"] = "fail"
        evidence = independent_asr.transcribe_manifest(
            manifest=manifest, config=self.config, cache=self.cache,
            lock_root=self.root, supervisor=truncated,
        )
        verdict = independent_asr.witness_verdict(manifest, evidence)
        self.assertEqual(verdict["status"], "unqualified")
        self.assertEqual(verdict["rows"][0]["status"], "unqualified")
        self.assertFalse(verdict["rows"][0]["expectationMet"])
        self.assertIn("processed-duration-mismatch", verdict["rows"][0]["whisperIssues"])
        # Nor with the in-app family agreeing on the failure.
        manifest["rows"][0]["appleSpeechPass"] = False
        manifest["rows"][0]["appleSpeechChannels"] = {"language": True, "accuracy": False}
        self.assertEqual(independent_asr.witness_verdict(manifest, evidence)["status"], "unqualified")

    def test_truncated_decode_is_a_processed_duration_mismatch(self) -> None:
        """The mismatch check can fire now that the duration is measured (audit #89)."""
        def truncated(command, **kwargs):
            result = self.supervisor(command, **kwargs)
            payload = json.loads(result.stdout)
            for row in payload["rows"]:
                row["decodedSampleCount"] = 16_000  # one of the two seconds
            return SupervisedResult(result.report, json.dumps(payload).encode(), b"")

        evidence = independent_asr.transcribe_manifest(
            manifest=self.manifest, config=self.config, cache=self.cache,
            lock_root=self.root, supervisor=truncated,
        )
        recognition = evidence["cells"]["en"]["recognitions"][0]
        self.assertEqual(recognition["processedDurationSeconds"], 1.0)
        self.assertIn("processed-duration-mismatch", recognition_issues(
            recognition, audio_sha256=file_sha256(self.wav), script=SCRIPT,
            script_sha256=text_sha256(SCRIPT), language="english", duration_seconds=2.0,
        ))

    def test_worker_loads_and_warms_once_before_any_row_is_timed(self) -> None:
        import independent_asr_worker as worker

        events: list = []

        class FakeRecognizer:
            def __init__(self, model_dir, decode, *, warmup_language=None) -> None:
                events.append(("load", model_dir.name, decode, warmup_language))
                self.model_load_seconds, self.warmup_seconds = 1.5, 0.2

            def recognize(self, audio, language):
                events.append(("row", len(audio), language))
                return {"decodedSampleCount": len(audio), "wallSeconds": 0.1}

        first, second = self.root / "a.pcm", self.root / "b.pcm"
        first.write_bytes(b"\x00\x00" * 480)
        second.write_bytes(b"\x00\x00" * 960)
        job = {"weights": str(self.weights), "decodeOptions": {"fp16": True}, "rows": [
            {"id": "a", "pcmPath": str(first), "language": "en"},
            {"id": "b", "pcmPath": str(second), "language": "fr"},
        ]}
        with mock.patch.object(worker, "Recognizer", FakeRecognizer):
            output = worker.run_job(job)
        # The warm-up decodes in the first row's locked language.
        self.assertEqual(events, [("load", self.root.name, {"fp16": True}, "en"),
                                  ("row", 480, "en"), ("row", 960, "fr")])
        self.assertEqual((output["modelLoadSeconds"], output["warmupSeconds"]), (1.5, 0.2))
        self.assertEqual([row["decodedSampleCount"] for row in output["rows"]], [480, 960])

    def test_cache_identity_follows_the_worker_not_the_producer(self) -> None:
        with mock.patch.object(independent_asr, "WORKER_SOURCE", self.root / "worker-a.py"):
            (self.root / "worker-a.py").write_text("a")
            first = independent_asr._provenance(self.config, language_code="en")
            with mock.patch.object(independent_asr, "__file__", str(self.root / "producer-edited.py")):
                self.assertEqual(independent_asr._provenance(self.config, language_code="en"), first)
            (self.root / "worker-a.py").write_text("b")
            self.assertNotEqual(
                independent_asr._provenance(self.config, language_code="en")["runtimeSHA256"],
                first["runtimeSHA256"],
            )

    def test_edge_coverage_and_empty_transcripts_are_reported_not_hidden(self) -> None:
        def short_read(command, **kwargs):
            job = json.loads(Path(command[3]).read_text())
            rows = [{
                "id": row["id"], "transcript": "", "language": "en", "detectedLanguage": "fr",
                "detectedLanguageProbability": 0.6, "expectedLanguageProbability": 0.3,
                "segments": [{"start": 0.0, "end": 0.4, "noSpeechProb": 0.9, "avgLogprob": -1.0}],
                "decodedSampleCount": 32_000, "sampleRateHz": 16_000,
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

    def test_fifteen_row_cohort_gets_whisper_and_a_family_consensus(self) -> None:
        """Audit #44: the 3-cell x 5-seed diagnostic cohort repeats cell IDs, so rows
        keyed by cell were rejected as duplicates and whisper never ran for it."""
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from test_language_bench_evidence import COHORT, CORPUS, MATRIX, build_source
        from language_bench_evidence import build_plan

        plan = build_plan(run_id="cohort-fixture", matrix_path=MATRIX, corpus_path=CORPUS,
                          subset="full", cohort_path=COHORT)
        plan_path = self.root / "plan.json"
        plan_path.write_text(json.dumps(plan))
        diagnostics = self.root / "cohort"
        build_source(diagnostics, plan)
        for take in plan["takes"]:
            sentinel = diagnostics / take["childRunID"] / "device-diagnostics-done.json"
            record = json.loads(sentinel.read_text())
            record["outputVerification"] = {"pass": True, "languagePass": True, "accuracyPass": True}
            sentinel.write_text(json.dumps(record))

        with self.assertRaises(independent_asr.IndependentASRError):
            independent_asr._manifest(
                [{"id": take["cellID"]} for take in plan["takes"]], run_id="cohort-fixture",
                platform="ios", generation_process_exited=True,
            )
        manifest = independent_asr.build_ios_manifest(
            diagnostics=diagnostics, run_id="cohort-fixture", plan=plan_path, corpus=CORPUS,
            generation_process_exited=True,
        )
        rows = manifest["rows"]
        self.assertEqual(len(rows), 15)
        self.assertEqual(len({row["id"] for row in rows}), 15)
        self.assertEqual(len({row["cellID"] for row in rows}), 3)
        self.assertTrue(all(row["appleSpeechPass"] is True for row in rows))
        self.assertTrue(all(
            row["appleSpeechChannels"] == {"language": True, "accuracy": True} for row in rows
        ))

        by_id = {row["id"]: row for row in rows}
        codes = {"english": "en", "french": "fr"}

        def cohort_worker(command, **kwargs):
            job = json.loads(Path(command[3]).read_text())
            answers = []
            for item in job["rows"]:
                row = by_id[item["id"]]
                answers.append({
                    "id": item["id"], "transcript": row["referenceText"],
                    "language": item["language"], "detectedLanguage": codes[row["expectedLanguage"]],
                    "detectedLanguageProbability": 0.97, "expectedLanguageProbability": 0.97,
                    "segments": [{"start": 0.0, "end": 1.2, "noSpeechProb": 0.01, "avgLogprob": -0.2}],
                    "decodedSampleCount": Path(item["pcmPath"]).stat().st_size // 2,
                    "sampleRateHz": 16_000, "wallSeconds": 0.2,
                })
            payload = {"schemaVersion": 1, "kind": "independent-asr-worker-output", "rows": answers}
            return SupervisedResult(envelope(), json.dumps(payload).encode(), b"")

        evidence = independent_asr.transcribe_manifest(
            manifest=manifest, config=self.config, cache=self.cache,
            lock_root=self.root, supervisor=cohort_worker,
        )
        self.assertEqual(len(evidence["cells"]), 15)
        verdict = independent_asr.witness_verdict(manifest, evidence)
        self.assertEqual(verdict["status"], "pass")
        self.assertEqual(verdict["families"], ["apple-speech", "whisper"])
        self.assertEqual(verdict["rowCount"], 15)

        self.assertEqual(verdict["rows"][4]["channels"], {"language": "pass", "accuracy": "pass"})

        # One family disagreeing on one channel of one take leaves the cohort
        # inconclusive, and the row names the channel (audit #42).
        split = copy.deepcopy(manifest)
        split["rows"][4]["appleSpeechChannels"]["language"] = False
        split_verdict = independent_asr.witness_verdict(split, evidence)
        self.assertEqual(split_verdict["status"], "inconclusive")
        self.assertEqual(split_verdict["rows"][4]["channels"], {"language": "inconclusive", "accuracy": "pass"})
        # Without the in-app verdicts the cohort rests on one witness, labelled so.
        alone = copy.deepcopy(manifest)
        for row in alone["rows"]:
            row.pop("appleSpeechPass")
            row.pop("appleSpeechChannels")
        self.assertEqual(independent_asr.witness_verdict(alone, evidence)["status"], "one-witness")

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
