#!/usr/bin/env python3
"""The audio QC orchestrator end to end, and the L0-L2 cache replay of today's verdicts (AQ-05).

No model runs: a fixture worker speaks the real worker protocol under the real
supervisor and admission, answering from a table keyed by canonical PCM.

The replay proves three things:

- The orchestrator's Stage 3, reading each recognition's score from its cached
  L2 metrics, reproduces exactly what the current code computes from the same
  recognitions: the language lane's `witness_verdict` and the delivery
  cascade's automated review and route (`run_cascade`).
- A second run from the cache launches nothing (every L1 and L2 entry hits)
  and reproduces every record's verdicts and metrics exactly; a metric
  definition change recomputes L2 from L1, still launching nothing.
- The committed language records' verdicts follow from their committed
  metrics through the same Stage 3 functions.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import inspect
import json
import math
import os
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest import mock
import wave

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import audio_qc_orchestrator as orchestrator_module  # noqa: E402
from audio_qc_judges import load_registry  # noqa: E402
from audio_qc_orchestrator import (  # noqa: E402
    Orchestrator,
    OrchestratorError,
    Stage2Judge,
    compare_with_bundle,
    manifest_from_cascade_input,
    manifest_from_independent_asr,
    replay_committed_records,
)
from delivery_analysis_cache import DeliveryAnalysisCache, digest, file_sha256  # noqa: E402
import delivery_resource_supervisor  # noqa: E402
from delivery_resource_supervisor import (  # noqa: E402
    HostSnapshot,
    ResourceSupervisorError,
    host_exclusion,
    run_supervised,
)
import independent_asr  # noqa: E402
from lib.language_metrics import score_recognition, text_sha256  # noqa: E402
from lib.qc_pipeline.admission import AdmissionPolicy, AdmissionTimeout, HostAdmission, HostBusy  # noqa: E402
from lib.qc_pipeline.evidence import (  # noqa: E402
    validate_private_bundle,
    validate_take_evidence,
    write_private_bundle,
)
from lib.qc_pipeline.layered_cache import JudgeIdentity, output_identity_digest  # noqa: E402
from run_local_delivery_cascade import run_cascade  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
FIXTURE_WORKER = Path(__file__).resolve().parent / "fixtures/audio_qc_fixture_worker.py"
WHISPER = "asr.whisper-small@1"
SENSEVOICE = "compact.sensevoice-small-q8@1"
MIB = 1024**2
LANGUAGE_CODES = {"english": "en", "french": "fr", "german": "de", "korean": "ko", "chinese": "zh"}
SCRIPTS = {
    "english": "The quiet garden opens early every morning.",
    "french": "Le jardin tranquille ouvre tôt chaque matin.",
    "korean": "조용한 정원은 매일 아침 일찍 문을 엽니다.",
    "italian": "Il giardino tranquillo apre presto ogni mattina.",
}


def quiet_supervisor(command, **kwargs):
    return run_supervised(command, snapshotter=lambda: HostSnapshot(50.0, 0, False),
                          rss_sampler=lambda _pid: 32 * MIB, **kwargs)


def refusing_supervisor(command, **kwargs):
    raise AssertionError("a cached replay launched a worker")


def _tone(path: Path, frequency: float, *, seconds: float = 2.0, amplitude: int = 7000) -> None:
    count = int(24_000 * seconds)
    samples = [int(math.sin(2 * math.pi * frequency * index / 24_000) * amplitude) for index in range(count)]
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(24_000)
        output.writeframes(struct.pack(f"<{count}h", *samples))


class OrchestratorFixture(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.cache_root = self.root / "cache"
        self.registry = load_registry()
        self.table: dict[str, dict] = {}

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _audio(self, name: str, frequency: float, **kwargs) -> Path:
        path = self.root / f"{name}.wav"
        _tone(path, frequency, **kwargs)
        return path

    def _answer(self, audio: Path, *, transcript: str, detected: str, coverage: float = 1.0) -> None:
        """What the fixture recognizer says for this audio's canonical PCM."""
        canonical = DeliveryAnalysisCache(self.cache_root).canonicalize(audio)
        duration = canonical.duration_seconds
        self.table[canonical.canonical_derivative_sha256] = {
            "transcript": transcript, "detectedLanguage": detected,
            "detectedLanguageProbability": 0.93, "expectedLanguageProbability": 0.91,
            "segments": [{"start": 0.0, "end": duration * coverage, "noSpeechProb": 0.01, "avgLogprob": -0.2}],
            "wallSeconds": 0.05,
        }

    def _judge(self, **overrides) -> Stage2Judge:
        values = dict(
            judge_id=WHISPER, engine="fixture", command=(sys.executable, str(FIXTURE_WORKER)),
            engine_config={"table": self.table},
            identity=JudgeIdentity(WHISPER, output_identity_digest(WHISPER, {"fixture": "whisper-table-v1", "threads": 2}),
                                   "fixture/whisper-small", "a" * 40, hashlib.sha256(b"fixture weights").hexdigest()),
            threads=2, family="whisper", language_codes=LANGUAGE_CODES,
            model_identity_sha256=digest({"fixture": "whisper"}),
        )
        values.update(overrides)
        return Stage2Judge(**values)

    def _orchestrator(self, *, supervisor=quiet_supervisor, offline: bool = False, judge: Stage2Judge | None = None):
        return Orchestrator(
            registry=self.registry, cache=DeliveryAnalysisCache(self.cache_root), lock_root=self.root / "locks",
            stage2=[judge or self._judge()], supervisor=supervisor, offline=offline,
            supervisor_options={}, host_admission=None,
        )


class LanguageLaneTests(OrchestratorFixture):
    def _manifest(self) -> dict:
        rows = []

        def row(row_id, audio, language, script_language, *, transcript, detected, expected="pass",
                apple=None, coverage=1.0):
            self._answer(audio, transcript=transcript, detected=detected, coverage=coverage)
            text = SCRIPTS[script_language]
            entry = independent_asr._row(
                row_id=row_id, generation_id=f"generation-{row_id}", audio=audio,
                audio_sha256=file_sha256(audio), expected_language=language, reference_text=text,
                expected_outcome=expected, cell_id=row_id, apple_speech_channels=apple,
            )
            rows.append(entry)

        row("custom-en-pinned", self._audio("en", 180), "english", "english",
            transcript=SCRIPTS["english"], detected="en")
        row("custom-fr-pinned", self._audio("fr", 200), "french", "french",
            transcript="Le jardin tranquille ouvre tot chaque matin", detected="fr")
        row("custom-fr-text-en-pinned", self._audio("control", 220), "english", "french",
            transcript="Le jardin tranquille ouvre", detected="fr", expected="fail")
        row("design-en-apple", self._audio("apple", 240), "english", "english",
            transcript=SCRIPTS["english"], detected="en", apple={"language": True, "accuracy": True})
        row("design-en-disagree", self._audio("disagree", 260), "english", "english",
            transcript=SCRIPTS["english"], detected="en", apple={"language": True, "accuracy": False})
        row("custom-en-wrong", self._audio("wrong", 280), "english", "english",
            transcript="Nothing like the script at all here", detected="en")
        row("custom-en-partial", self._audio("partial", 300), "english", "english",
            transcript=SCRIPTS["english"], detected="en", coverage=0.4)
        row("custom-ko-pinned", self._audio("ko", 320), "korean", "korean",
            transcript="조용한 정원은 매일 아침 일찍 문을 엽니다", detected="ko")
        # A language the fixture recognizer cannot lock: out of scope.
        italian = self._audio("it", 340)
        rows.append(independent_asr._row(
            row_id="custom-it-pinned", generation_id="generation-it", audio=italian,
            audio_sha256=file_sha256(italian), expected_language="italian", reference_text=SCRIPTS["italian"],
        ))
        source = {"schemaVersion": 1, "kind": "independent-asr-manifest", "runID": "lang-fixture-run",
                  "platform": "macos", "generationProcessExited": True, "rows": rows}
        self.source = source
        return manifest_from_independent_asr(source, source_sha256=digest(source))

    def test_the_language_lane_runs_one_worker_and_replays_todays_verdicts(self) -> None:
        manifest = self._manifest()
        result = self._orchestrator().run(manifest)
        header = result["header"]
        workers = header["workers"]
        self.assertEqual(len(workers), 1)
        self.assertEqual(len(workers[0]["launches"]), 1, "one persistent worker for the whole run")
        self.assertEqual(workers[0]["launches"][0]["rows"], 8)
        envelope = workers[0]["launches"][0]["resourceEnvelope"]
        self.assertEqual(envelope["exclusion"], "budgeted-admission")
        self.assertEqual(envelope["admission"]["ceilingBytes"], 2684354560)
        self.assertEqual(envelope["maximumAllowedRSSBytes"], 2684354560)
        self.assertEqual(header["cache"]["L1"], {"hits": 0, "misses": 9 - 1, "adopted": 0})
        for record in result["records"]:
            self.assertEqual(validate_take_evidence(record), [], record["take"]["takeID"])

        # 1. Exactly what `witness_verdict` computes from the same recognitions.
        recognitions = result["recognitions"]
        rows = [row for row in self.source["rows"] if recognitions[row["id"]]]
        legacy = independent_asr.witness_verdict(
            {**self.source, "rows": rows}, {"cells": {row["id"]: {"recognitions": recognitions[row["id"]]}
                                                      for row in rows}},
        )
        by_take = {record["take"]["takeID"]: record for record in result["records"]}
        for row in legacy["rows"]:
            replayed = by_take[row["id"]]["legacyVerdicts"]["languageWitness"]
            expected = {key: row[key] for key in replayed}
            self.assertEqual(replayed, expected, row["id"])
        statuses = {row["id"]: row["status"] for row in legacy["rows"]}
        self.assertEqual(statuses, {
            "custom-en-pinned": "one-witness", "custom-fr-pinned": "one-witness",
            "custom-fr-text-en-pinned": "one-witness", "design-en-apple": "pass",
            "design-en-disagree": "inconclusive", "custom-en-wrong": "one-witness",
            "custom-en-partial": "unqualified", "custom-ko-pinned": "one-witness",
        })
        self.assertEqual(header["run"]["languageWitness"]["status"], "unavailable")
        self.assertEqual(header["run"]["languageWitness"]["unavailableTakes"], 1)
        self.assertEqual(by_take["custom-it-pinned"]["legacyVerdicts"]["languageWitness"]["status"], "unavailable")

        # The composer: no qualified record yet, so verdicts are uncalibrated,
        # abstentions and scope stay explicit, and nothing claims a pass.
        take_verdicts = {take_id: record["takeVerdict"]["status"] for take_id, record in by_take.items()}
        self.assertEqual(take_verdicts["custom-en-pinned"], "uncalibrated")
        self.assertEqual(take_verdicts["design-en-disagree"], "inconclusive")
        self.assertEqual(take_verdicts["custom-en-partial"], "inconclusive")
        self.assertEqual(take_verdicts["custom-it-pinned"], "inconclusive")
        self.assertNotIn("pass", take_verdicts.values())

        # 2. The private bundle validates, keeps transcripts out of the records
        # and names its failing takes.
        bundle = self.root / "bundle"
        written = write_private_bundle(bundle, header=header, takes=zip(result["records"], result["privates"]),
                                       repository=REPO)
        self.assertEqual(validate_private_bundle(bundle, repository=REPO), [])
        # The partial take is unqualified; the wrong transcript missed its expectation.
        failing = {entry["takeID"] for entry in written["takes"] if entry["failing"]}
        self.assertEqual(failing, {"custom-en-partial", "custom-en-wrong"})
        self.assertEqual(written["failingTakes"], 2)
        for entry in written["takes"]:
            evidence_text = (bundle / entry["evidence"]).read_text(encoding="utf-8")
            self.assertNotIn(SCRIPTS["english"], evidence_text)
            self.assertNotIn(str(self.root), evidence_text)
        private = json.loads((bundle / written["takes"][0]["private"]).read_text(encoding="utf-8"))
        self.assertEqual(private["transcripts"][WHISPER], SCRIPTS["english"])

        # 3. A replay from the cache launches nothing and is identical.
        replay = self._orchestrator(supervisor=refusing_supervisor, offline=True).run(manifest)
        self.assertEqual(replay["header"]["cache"]["L1"]["misses"], 0)
        self.assertEqual(replay["header"]["cache"]["L2"]["misses"], 0)
        self.assertEqual(replay["header"]["workers"], [])
        self.assertEqual(replay["header"]["scorer"]["l2Metrics"], header["scorer"]["l2Metrics"])
        comparison = compare_with_bundle(replay, bundle)
        self.assertTrue(comparison["identical"], comparison["differences"])

        # 4. A metric-definition change recomputes L2 from L1 without a model.
        redefined = self._orchestrator(supervisor=refusing_supervisor, offline=True,
                                       judge=self._judge(metric_definition="normalization-v2-edit-rate-v3-test"))
        changed = redefined.run(manifest)
        self.assertEqual(changed["header"]["cache"]["L1"]["misses"], 0)
        self.assertEqual(changed["header"]["cache"]["L2"]["hits"], 0)
        self.assertGreater(changed["header"]["cache"]["L2"]["misses"], 0)
        self.assertTrue(compare_with_bundle(changed, bundle)["identical"])

        # A replay that would need a model refuses rather than launching one.
        fresh = self._judge(identity=JudgeIdentity(
            WHISPER, output_identity_digest(WHISPER, {"fixture": "whisper-table-v2", "threads": 2}),
            "fixture/whisper-small", "a" * 40, hashlib.sha256(b"fixture weights").hexdigest()))
        with self.assertRaisesRegex(OrchestratorError, "a model would have to run"):
            self._orchestrator(supervisor=refusing_supervisor, offline=True, judge=fresh).run(manifest)

    def test_a_manifest_must_follow_generator_exit_and_bind_its_audio(self) -> None:
        manifest = self._manifest()
        exited = copy.deepcopy(manifest)
        exited["generationProcessExited"] = False
        with self.assertRaisesRegex(OrchestratorError, "generator must have exited"):
            self._orchestrator().run(exited)
        changed = copy.deepcopy(manifest)
        changed["takes"][0]["audioSHA256"] = "0" * 64
        with self.assertRaisesRegex(OrchestratorError, "bytes changed"):
            self._orchestrator().run(changed)
        unbound = copy.deepcopy(manifest)
        unbound["takes"][0]["scriptSHA256"] = text_sha256("another script")
        with self.assertRaisesRegex(OrchestratorError, "script digest"):
            self._orchestrator().run(unbound)

    def test_a_crashing_worker_leaves_its_rows_unavailable_never_passed(self) -> None:
        manifest = self._manifest()
        crashing = next(iter(self.table))
        judge = self._judge(engine_config={"table": self.table, "crashAlways": crashing})
        result = self._orchestrator(judge=judge).run(manifest)
        launches = result["header"]["workers"][0]["launches"]
        # The job, the crashing row alone, then the rest: one bad take costs no other.
        self.assertEqual([launch["kind"] for launch in launches], ["job", "isolated", "remainder"])
        unavailable = [record for record in result["records"]
                       if any(item["status"] == "unavailable" for item in record["measurements"])]
        self.assertEqual([record["take"]["takeID"] for record in unavailable], ["custom-en-pinned"])
        for record in unavailable:
            self.assertEqual(record["takeVerdict"]["status"], "unavailable")
            self.assertEqual(record["legacyVerdicts"]["languageWitness"]["status"], "unavailable")
            self.assertEqual(validate_take_evidence(record), [])


class DeliveryLaneTests(OrchestratorFixture):
    def _qc(self, duration: float, verdict: str = "pass") -> dict:
        return {"algorithmVersion": 6, "verdict": verdict, "instabilityVerdict": "pass",
                "writtenOutputVerdict": "pass", "durationSeconds": duration, "flags": [],
                **{key: 0 for key in ("nonFiniteSamples", "clippedSamples", "hotSamples", "clickEvents",
                                      "longestSilenceMS", "trailingSilenceMS")}}

    def _external(self, audio: Path, *, transcript: str, family: str = "sensevoice") -> dict:
        duration = DeliveryAnalysisCache(self.cache_root).canonicalize(audio).duration_seconds
        return {"modelFamily": family, "audioSHA256": file_sha256(audio),
                "inputTextSHA256": text_sha256(SCRIPTS["english"]), "status": "complete",
                "outputLanguage": "english", "detectedLanguage": "english", "fullFileProcessed": True,
                "processedDurationSeconds": duration, "transcript": transcript,
                "provenance": {key: digest(f"{family}-{key}") for key in
                               ("runtimeSHA256", "modelIdentitySHA256", "configSHA256")}}

    def _cascade_input(self) -> dict:
        neutral = self._audio("neutral", 150)
        self._answer(neutral, transcript=SCRIPTS["english"], detected="en")
        silent = self.root / "silent.wav"
        with wave.open(str(silent), "wb") as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(24_000)
            output.writeframes(b"\0\0" * 48_000)
        self._answer(silent, transcript=SCRIPTS["english"], detected="en")
        plans = [
            ("pair-clean", self._audio("clean", 190), SCRIPTS["english"], SCRIPTS["english"], "pass"),
            ("pair-native-fail", self._audio("native", 210), SCRIPTS["english"], SCRIPTS["english"], "fail"),
            ("pair-content-fail", self._audio("content", 230), "Something else entirely was said.",
             "Something else entirely was said.", "pass"),
            ("pair-disagree", self._audio("disagree", 250), SCRIPTS["english"],
             "Something else entirely was said.", "pass"),
            ("pair-silent", silent, SCRIPTS["english"], SCRIPTS["english"], "pass"),
        ]
        rows = []
        for generation, audio, whisper_text, external_text, native in plans:
            if audio != silent:
                self._answer(audio, transcript=whisper_text, detected="en")
            duration = DeliveryAnalysisCache(self.cache_root).canonicalize(audio).duration_seconds
            neutral_duration = DeliveryAnalysisCache(self.cache_root).canonicalize(neutral).duration_seconds
            rows.append({
                "generationID": generation, "speakerID": "aiden", "scriptID": "script-1",
                "scriptTranslationGroup": "translation-1", "seed": len(rows) + 1, "outputLanguage": "English",
                "preset": "happy", "instructedWAV": str(audio), "instructedSHA256": file_sha256(audio),
                "neutralWAV": str(neutral), "neutralSHA256": file_sha256(neutral),
                "referenceText": SCRIPTS["english"], "scriptSHA256": text_sha256(SCRIPTS["english"]),
                "reviewEvidence": {
                    "instructed": {"audioSHA256": file_sha256(audio), "audioQC": self._qc(duration, native),
                                   "recognitions": [self._external(audio, transcript=external_text)]},
                    "neutral": {"audioSHA256": file_sha256(neutral), "audioQC": self._qc(neutral_duration),
                                "recognitions": [self._external(neutral, transcript=SCRIPTS["english"])]},
                },
            })
        body = {
            "schemaVersion": 1, "kind": "source-bound-delivery-cascade-input", "generationProcessExited": True,
            "executionPlanDigest": "1" * 64,
            "sourceDigests": {key: "2" * 64 for key in (
                "retainedPlanSHA256", "executionStateSHA256", "acousticLayerSHA256", "binarySHA256",
                "runnerSHA256", "analyzerSHA256", "temporalAnalyzerSHA256")},
            "rows": rows,
        }
        return {**body, "manifestDigest": digest(body)}

    def test_the_delivery_lane_replays_the_cascade_routes_and_reviews_exactly(self) -> None:
        source = self._cascade_input()
        manifest = manifest_from_cascade_input(source, source_sha256=digest(source))
        result = self._orchestrator().run(manifest)
        workers = result["header"]["workers"]
        self.assertEqual([len(worker["launches"]) for worker in workers], [1])
        # The neutral clip is shared by every pair: one row, not five.
        self.assertEqual(workers[0]["launches"][0]["rows"], 6)
        for record in result["records"]:
            self.assertEqual(validate_take_evidence(record), [], record["take"]["takeID"])

        # The current cascade over the same recognitions (supplied as review evidence).
        legacy_input = copy.deepcopy(source)
        for row in legacy_input["rows"]:
            for role in ("instructed", "neutral"):
                row["reviewEvidence"][role]["recognitions"] += result["recognitions"][f"{row['generationID']}:{role}"]
        legacy_input.pop("manifestDigest")
        legacy_input["manifestDigest"] = digest(legacy_input)
        cascade = run_cascade(manifest=legacy_input, cache=DeliveryAnalysisCache(self.root / "cascade-cache"),
                              lock_root=self.root / "cascade-locks")
        routes = {row["generationID"]: (row["route"], row["reasons"]) for row in cascade["rows"]}
        replayed = {pair["pairID"]: (pair["route"], pair["reasons"]) for pair in result["header"]["run"]["pairs"]}
        self.assertEqual(replayed, routes)
        self.assertGreaterEqual(len({route for route, _reasons in routes.values()}), 2)
        by_take = {record["take"]["takeID"]: record for record in result["records"]}
        for row in cascade["rows"]:
            for role in ("instructed", "neutral"):
                review = row["automatedReview"][role]
                replayed_review = by_take[f"{row['generationID']}:{role}"]["legacyVerdicts"]["automatedReview"]
                self.assertEqual(replayed_review, {key: review[key] for key in replayed_review},
                                 f"{row['generationID']}:{role}")
        self.assertEqual(routes["pair-native-fail"][0], "rejected")
        self.assertEqual(routes["pair-content-fail"][0], "rejected")
        self.assertEqual(routes["pair-silent"][0], "rejected")

        # From the cache: nothing launches, nothing changes.
        bundle = self.root / "build" / "bundle"
        write_private_bundle(bundle, header=result["header"], takes=zip(result["records"], result["privates"]),
                             repository=self.root)
        replay = self._orchestrator(supervisor=refusing_supervisor, offline=True).run(manifest)
        self.assertEqual(replay["header"]["cache"]["L1"]["misses"], 0)
        comparison = compare_with_bundle(replay, bundle)
        self.assertTrue(comparison["identical"], comparison["differences"])
        self.assertEqual(replay["header"]["run"], result["header"]["run"])


class SmallRunFixture(OrchestratorFixture):
    def _small_manifest(self, count: int = 3, *, take_ids: list[str] | None = None) -> dict:
        rows = []
        for index in range(count):
            audio = self._audio(f"small-{index}", 180 + 20 * index)
            self._answer(audio, transcript=SCRIPTS["english"], detected="en")
            rows.append(independent_asr._row(
                row_id=f"small-{index}", generation_id=f"generation-{index}", audio=audio,
                audio_sha256=file_sha256(audio), expected_language="english", reference_text=SCRIPTS["english"],
                cell_id=f"small-{index}",
            ))
        source = {"schemaVersion": 1, "kind": "independent-asr-manifest", "runID": "small-run",
                  "platform": "macos", "generationProcessExited": True, "rows": rows}
        manifest = manifest_from_independent_asr(source, source_sha256=digest(source))
        for take, take_id in zip(manifest["takes"], take_ids or []):
            take["id"] = take_id
        return manifest


class ConcurrentRunTests(SmallRunFixture):
    def test_a_run_adopts_what_another_run_stored_after_it_planned(self) -> None:
        """Two orchestrators planned the same misses; the later one adopts, never fails its takes."""
        manifest = self._small_manifest()
        judge = self._judge(engine_config={"table": self.table, "measureWall": True})
        locks = self.root / "locks"
        policy = AdmissionPolicy.from_registry(self.registry)
        other = self._orchestrator(judge=judge)
        other.host = HostAdmission(locks, policy)
        ran_other: list[dict] = []

        class InterleavedHost(HostAdmission):
            def _admit(self, lane, judge_id, ceiling_bytes, host_fd, **kwargs):
                if lane == "gpu" and not ran_other:
                    # Another run finishes between this run's plan and its admission.
                    ran_other.append(other.run(manifest))
                return super()._admit(lane, judge_id, ceiling_bytes, host_fd, **kwargs)

        later = self._orchestrator(judge=judge)
        later.host = InterleavedHost(locks, policy)
        result = later.run(manifest)
        self.assertEqual(len(ran_other), 1)
        worker = result["header"]["workers"][0]
        self.assertEqual((worker["launches"], worker["rowsAdopted"]), ([], 3))
        self.assertEqual(result["header"]["cache"]["L1"]["adopted"], 3)
        for record, first in zip(result["records"], ran_other[0]["records"]):
            statuses = {item["judge"]: item["status"] for item in record["measurements"]}
            self.assertEqual(statuses[WHISPER], "complete", record["take"]["takeID"])
            self.assertEqual(record["verdicts"], first["verdicts"])
        # Timing never entered the cached entry; the launch that measured it keeps it.
        first_measurement = next(item for item in ran_other[0]["records"][0]["measurements"] if item["judge"] == WHISPER)
        self.assertIsInstance(first_measurement["wallSeconds"], float)
        self.assertNotIn("recognition.recognitionDurationSeconds", first_measurement["metrics"])

    def test_a_different_entry_stored_first_is_adopted(self) -> None:
        from lib.qc_pipeline.layered_cache import LayeredCache, l1_identity

        cache = DeliveryAnalysisCache(self.cache_root)
        audio = self._audio("adopted", 440)
        canonical = cache.canonicalize(audio)
        identity = l1_identity(canonical, self._judge().identity, {"lockedLanguage": "en"})
        first, second = LayeredCache(cache), LayeredCache(cache)
        stored, adopted = first.store_l1(identity, {"transcript": "first run"})
        self.assertEqual((stored, adopted), ({"transcript": "first run"}, False))
        # A nondeterministic judge's second run: its own value never replaces or fails the first.
        stored, adopted = second.store_l1(identity, {"transcript": "second run"})
        self.assertEqual((stored, adopted), ({"transcript": "first run"}, True))
        self.assertEqual(second.report()["L1"]["adopted"], 1)

    def test_a_judge_never_admitted_keeps_the_other_judges_results(self) -> None:
        manifest = self._small_manifest(2)
        whisper = self._judge(engine_config={"table": self.table, "sleepPerRow": 0.3})
        second = self._judge(
            judge_id=SENSEVOICE, family=None, language_codes={}, engine_config={"table": self.table},
            identity=JudgeIdentity(SENSEVOICE, output_identity_digest(SENSEVOICE, {"fixture": "tags", "threads": 2}),
                                   "fixture/sensevoice", "b" * 40, hashlib.sha256(b"sensevoice weights").hexdigest()),
        )

        class NeverFits(HostAdmission):
            """SenseVoice's admission times out while whisper's worker still runs."""

            def _admit(self, lane, judge_id, ceiling_bytes, host_fd, **kwargs):
                if judge_id == SENSEVOICE:
                    raise AdmissionTimeout(f"{judge_id} was not admitted in time: budget-exhausted")
                return super()._admit(lane, judge_id, ceiling_bytes, host_fd, **kwargs)

        orchestrator = Orchestrator(
            registry=self.registry, cache=DeliveryAnalysisCache(self.cache_root), lock_root=self.root / "locks",
            stage2=[whisper, second], supervisor=quiet_supervisor,
            host_admission=NeverFits(self.root / "locks", AdmissionPolicy.from_registry(self.registry)),
        )
        result = orchestrator.run(manifest)
        for record in result["records"]:
            measured = {item["judge"]: item for item in record["measurements"]}
            self.assertEqual(measured[WHISPER]["status"], "complete")
            self.assertEqual((measured[SENSEVOICE]["status"], measured[SENSEVOICE]["reasons"]),
                             ("unavailable", ["admission-timeout"]))
            self.assertEqual(validate_take_evidence(record), [])
        workers = {worker["judge"]: worker for worker in result["header"]["workers"]}
        self.assertEqual(workers[SENSEVOICE]["launches"], [])
        # Whisper's rows were stored as its worker finished: a replay of it alone launches nothing.
        replay = Orchestrator(registry=self.registry, cache=DeliveryAnalysisCache(self.cache_root),
                              lock_root=self.root / "locks", stage2=[whisper], supervisor=refusing_supervisor,
                              offline=True).run(manifest)
        self.assertEqual(replay["header"]["cache"]["L1"]["misses"], 0)


class CacheIdentityTests(SmallRunFixture):
    def test_the_l2_key_covers_every_source_that_shapes_it(self) -> None:
        from lib.qc_pipeline import verdicts

        shaping = {Path(inspect.getsourcefile(function)).resolve() for function in (
            verdicts.asr_metrics, score_recognition, independent_asr._recognition)}
        self.assertEqual({path.resolve() for path in verdicts.ASR_METRIC_SOURCES}, shaping)
        copies = []
        for source in verdicts.ASR_METRIC_SOURCES:
            copy_path = self.root / "sources" / source.name
            copy_path.parent.mkdir(exist_ok=True)
            copy_path.write_bytes(source.read_bytes())
            copies.append(copy_path)
        judge = self._judge(metric_sources=tuple(copies))
        manifest = self._small_manifest(2)
        first = self._orchestrator(judge=judge).run(manifest)
        self.assertEqual(first["header"]["cache"]["L2"]["misses"], 2)
        again = self._orchestrator(judge=judge, supervisor=refusing_supervisor, offline=True).run(manifest)
        self.assertEqual((again["header"]["cache"]["L2"]["hits"], again["header"]["cache"]["L2"]["misses"]), (2, 0))
        for copy_path in copies:
            with self.subTest(source=copy_path.name):
                copy_path.write_bytes(copy_path.read_bytes() + b"\n# an edit that could move a metric\n")
                edited = self._orchestrator(judge=judge, supervisor=refusing_supervisor, offline=True).run(manifest)
                self.assertEqual(edited["header"]["cache"]["L2"]["hits"], 0)
                self.assertEqual(edited["header"]["cache"]["L2"]["misses"], 2)

    def test_a_take_id_that_is_not_a_token_keeps_its_bundle_valid(self) -> None:
        manifest = self._small_manifest(2, take_ids=["take one, English", "take/two/nested"])
        result = self._orchestrator().run(manifest)
        bundle = self.root / "bundle"
        write_private_bundle(bundle, header=result["header"], takes=zip(result["records"], result["privates"]),
                             repository=REPO)
        self.assertEqual(validate_private_bundle(bundle, repository=REPO), [])
        for record, private in zip(result["records"], result["privates"]):
            self.assertEqual(private["takeID"], record["take"]["takeID"])
            self.assertEqual(private["takeID"], digest(private["manifestTakeID"]))

    def test_each_launch_scales_its_timeout_with_the_per_row_budget(self) -> None:
        manifest = self._small_manifest(3)
        timeouts = []

        def recording(command, **kwargs):
            timeouts.append(kwargs["timeout_seconds"])
            return quiet_supervisor(command, **kwargs)

        judge = self._judge(row_timeout_seconds=7.0, startup_seconds=11.0)
        self._orchestrator(judge=judge, supervisor=recording).run(manifest)
        self.assertEqual(timeouts, [11.0 + 3 * 7.0])

        class Captured(Exception):
            pass

        seen = {}

        def capture(judge_id, config, registry, **kwargs):
            seen.update(kwargs)
            raise Captured

        config = self.root / "config.json"
        config.write_text("{}", encoding="utf-8")
        with mock.patch.object(orchestrator_module, "stage2_judge_from_adapter_config", capture), \
                self.assertRaises(Captured):
            orchestrator_module.main(["run", "--manifest", str(config), "--judge-config", f"{WHISPER}={config}",
                                      "--resampler", "linear-rational-v1", "--timeout-seconds", "7"])
        self.assertEqual(seen, {"row_timeout_seconds": 7.0})


class HostWideLockTests(SmallRunFixture):
    def test_every_cache_root_contends_on_the_one_host_lock(self) -> None:
        host_root = self.root / "host-analysis-lock"
        with mock.patch.dict(os.environ, {"QVOICE_DELIVERY_ANALYSIS_LOCK_ROOT": str(host_root),
                                          "QVOICE_DELIVERY_ANALYSIS_CACHE": str(self.root / "env-cache")}):
            manifest = self._small_manifest(1)
            first = Orchestrator(registry=self.registry, cache=DeliveryAnalysisCache(self.root / "cache-a"),
                                 stage2=[self._judge()], supervisor=quiet_supervisor)
            second = orchestrator_module._orchestrator(argparse.Namespace(
                judge_config=None, resampler=None, cache_root=self.root / "cache-b", timeout_seconds=900.0,
            ), offline=False)
            self.assertEqual(first.host.lock_root, host_root)
            self.assertEqual(second.host.lock_root, host_root)
            # One ledger: a run under one cache root spends the budget the other sees.
            with first.host.run():
                self.assertEqual([ticket["lane"] for ticket in second.host.status()["tickets"]], ["orchestrator"])
            # A generator (the exclusive host lock) keeps out an orchestrator on any cache root.
            with host_exclusion(delivery_resource_supervisor.host_analysis_lock_root()):
                for orchestrator in (first, second):
                    with self.assertRaises(HostBusy):
                        orchestrator.run(manifest)
                with self.assertRaises(ResourceSupervisorError):
                    run_supervised([sys.executable, "-c", "print(1)"], snapshotter=lambda: HostSnapshot(50.0, 0, False))
            # And an orchestrator run keeps out a generator or standalone analyzer.
            with second.host.run():
                with self.assertRaises(ResourceSupervisorError):
                    with host_exclusion():
                        pass


class CommittedRecordReplayTests(unittest.TestCase):
    def test_committed_language_verdicts_follow_from_their_committed_metrics(self) -> None:
        report = replay_committed_records(REPO / "benchmarks/runs/language", REPO / "config/language-bench-matrix.json")
        self.assertTrue(report["identical"], json.dumps(
            {name: row["mismatches"] for name, row in report["byRecord"].items() if row["mismatches"]}))
        self.assertGreaterEqual(report["recordsWithMetrics"], 5)
        self.assertEqual(report["accuracyReplayed"], report["takesWithMetrics"])
        self.assertGreaterEqual(report["languageReplayed"], 31)
        for name, row in report["byRecord"].items():
            recorded = row["recordedCounts"]
            if "outputCellsPassed" in recorded:
                self.assertEqual(recorded["outputCellsPassed"], row["expectationsMet"], name)

    def test_a_tampered_committed_verdict_is_caught(self) -> None:
        path = sorted((REPO / "benchmarks/runs/language").glob("mac-lang-bench-20260926-*.json"))[0]
        record = json.loads(path.read_text(encoding="utf-8"))
        cells = {cell["id"]: cell for cell in json.loads(
            (REPO / "config/language-bench-matrix.json").read_text(encoding="utf-8"))["cells"]}
        from lib.qc_pipeline.verdicts import replay_committed_language_record
        self.assertTrue(replay_committed_language_record(record, cells)["identical"])
        tampered = copy.deepcopy(record)
        tampered["takes"][0]["metrics"]["independentPrimaryAccuracyScore"] = 0.4
        self.assertFalse(replay_committed_language_record(tampered, cells)["identical"])
        wrong_language = copy.deepcopy(record)
        wrong_language["takes"][0]["detectedLanguages"]["whisper"] = "french"
        self.assertFalse(replay_committed_language_record(wrong_language, cells)["identical"])


class CommandLineTests(unittest.TestCase):
    def test_replay_records_command_reports_identical(self) -> None:
        with mock.patch("sys.stdout") as stdout:
            self.assertEqual(orchestrator_module.main(["replay-records"]), 0)
        printed = "".join(call.args[0] for call in stdout.write.call_args_list)
        self.assertTrue(json.loads(printed)["identical"])


if __name__ == "__main__":
    unittest.main()
