"""QC v2 lane wiring: lane definitions, controls, the language-bench takes and evidence, clone fidelity.

The language lanes (`qc.language`) bind a lang-bench run's takes to the digests its generation
published and turn a QC run's two ASR families into the evidence the publisher re-scores; the
clone lanes (`qc.fidelity`) read a QC run's pitch and speaker results against each take's
reference. Model runs are replaced by results written straight into the cache.
"""

from __future__ import annotations

import copy
import json
import shutil
import sys
import tempfile
import unittest
import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import language_bench_evidence as plan_lib  # noqa: E402
from lib import language_metrics as metrics  # noqa: E402
from qc import detectors, fidelity, lanes, language, runtime, store  # noqa: E402
from qc.features import feature  # noqa: E402
from qc.store import Layout  # noqa: E402

MATRIX = ROOT / "config/language-bench-matrix.json"
CORPUS = ROOT / "config/language-bench-corpus.json"
RUNNERS = {"qc.runners.qwen3_asr", "qc.runners.whisper", "qc.runners.fcpe", "qc.runners.swiftf0",
           "qc.runners.redimnet"}


def write_wav(path: Path, *, value: int, seconds: float = 2.0, rate: int = 24_000) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(int(value).to_bytes(2, "little", signed=True) * int(seconds * rate))
    return path


def temporary_layout(root: Path) -> Layout:
    """config/qc from the repository, the registry's ASR, pitch and speaker models, and stub runner files."""
    layout = Layout(root)
    layout.config.mkdir(parents=True)
    for name in ("detectors.json", "protocol.json"):
        shutil.copyfile(ROOT / "config/qc" / name, layout.config / name)
    registry = store.read_json(ROOT / "config/qc/models.json")
    registry["models"] = [model for model in registry["models"] if model["runner"] in RUNNERS
                          and model.get("role", "primary") == "primary"]
    layout.registry.write_text(json.dumps(registry))
    for model in registry["models"]:
        source = root / "scripts" / (model["runner"].replace(".", "/") + ".py")
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text(f"# stub runner for {model['id']}\n")
    return layout


def model(layout: Layout, model_id: str) -> dict:
    return next(entry for entry in store.read_json(layout.registry)["models"] if entry["id"] == model_id)


def write_run(layout: Layout, run_id: str, manifest: dict, roles: dict[str, str], *, lane: str) -> Path:
    directory = layout.runs / run_id
    directory.mkdir(parents=True)
    store.write_json_atomic(directory / "takes.json", manifest)
    identities = {role: {"id": model_id, "runnerSHA256": runtime.runner_identity(layout, model(layout, model_id)),
                         "available": True} for role, model_id in roles.items()}
    store.write_json_atomic(directory / "features.json", {"lane": lane, "models": identities, "takes": []})
    store.write_json_atomic(directory / "flags.json", {"lane": lane, "takes": [
        {"token": take["token"], "flags": []} for take in manifest["takes"]]})
    return directory


def write_result(layout: Layout, model_id: str, audio_sha: str, outputs: dict, *, variant: str | None = None,
                 duration: float = 2.0) -> None:
    store.write_result(layout.results_dir(model_id), model=model_id,
                       runner_sha=runtime.runner_identity(layout, model(layout, model_id)), audio_sha=audio_sha,
                       variant=variant, duration_seconds=duration, outputs=outputs)


class LaneDefinitionTests(unittest.TestCase):
    def setUp(self):
        self.config = detectors.load_config()

    def test_the_four_lanes_are_defined_with_their_roles(self):
        lanes_config = self.config["lanes"]
        for name in ("language-bench", "ios-language-bench", "qc-takes", "clone-lane", "voice-reliability"):
            self.assertIn(name, lanes_config)
        self.assertEqual(detectors.lane_roles(self.config, "clone-lane"), ["speaker", "pitchA", "pitchB"])
        self.assertIn("asrA", detectors.lane_roles(self.config, "language-bench"))
        self.assertIn("asrB", detectors.lane_roles(self.config, "ios-language-bench"))
        # The LLM judge runs only on labelled and queued takes.
        self.assertNotIn("llm", detectors.lane_roles(self.config, "qc-takes"))
        # A lane the map does not name runs every role.
        self.assertEqual(detectors.lane_roles(self.config, "pool"), list(self.config["models"]))

    def test_a_lane_gates_only_the_detectors_its_roles_can_score(self):
        clone = detectors.gated_detectors(self.config, "clone-lane")
        self.assertTrue({"identity.drift", "prosody.pitch", "prosody.tonal-collapse", "signal.artifacts"} <= clone)
        self.assertFalse({"content.phoneme", "quality.naturalness", "language.wrong"} & clone)
        self.assertFalse(any(name.startswith("judge.llm") for name in clone))
        self.assertIn("judge.llm.stutter", detectors.gated_detectors(self.config, "pool"))

    def test_lane_definitions_are_validated(self):
        for lane in ({"description": "x", "models": ["nope"]}, {"description": "", "models": ["asrA"]},
                     {"description": "x", "models": []}, {"description": "x", "models": ["asrA", "asrA"]}):
            broken = copy.deepcopy(self.config)
            broken["lanes"]["bad"] = lane
            with self.subTest(lane=lane), self.assertRaises(detectors.ConfigError):
                detectors.validate_config(broken)


class ControlAndLaneGatingTests(unittest.TestCase):
    """A control take and a detector its lane cannot score stay report-only, whatever the evaluation says."""

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.layout = temporary_layout(self.root)
        self.config = detectors.load_config(self.layout)
        thresholds = {"schema": "vocello.qc.thresholds/1", "version": 1, "models": {}, "normalization": {},
                      "detectors": {detector["id"]: {"reportOnly": True} for detector in self.config["detectors"]}}
        path = self.layout.config / "thresholds-v1.json"
        store.write_json_atomic(path, thresholds)
        store.write_json_atomic(self.root / "benchmarks/qc/eval-v1.json", {
            "version": 1, "thresholdsSHA256": store.sha256_file(path), "detectors": {
                "pause.anomalous": {"languages": {"french": {"level": "fail"}}},
                "content.phoneme": {"languages": {"french": {"level": "fail"}}}}})

    def tearDown(self):
        self.directory.cleanup()

    def rows(self):
        flagged = {"pause.longest_gap_seconds": feature(0.8, 1.0, 1.8), "phones.repeat_runs": feature(3.0)}
        return [{"token": token, "takeID": token, "language": "french", "features": dict(flagged)}
                for token in ("take", "control")]

    def levels(self, lane):
        flags = lanes.score_run(self.layout, self.config, self.rows(), {}, lane=lane, controls={"control"})
        return {entry["token"]: {flag["detector"]: flag["level"] for flag in entry["flags"]}
                for entry in flags["takes"]}, flags

    def test_a_control_take_never_gates(self):
        levels, flags = self.levels("language-bench")
        self.assertEqual(levels["take"]["pause.anomalous"], "fail")
        self.assertEqual(levels["control"]["pause.anomalous"], "report-only")
        self.assertTrue(next(entry for entry in flags["takes"] if entry["token"] == "control")["control"])

    def test_a_detector_outside_the_lane_reports_only(self):
        levels, _ = self.levels("clone-lane")
        self.assertEqual(levels["take"]["pause.anomalous"], "fail")
        self.assertEqual(levels["take"]["content.phoneme"], "report-only")
        levels, _ = self.levels("language-bench")
        self.assertEqual(levels["take"]["content.phoneme"], "fail")


class LanguageBenchTakesTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.run_id = "mac-lang-bench-20261001-000000-abcd1234"
        self.plan = plan_lib.build_plan(run_id=self.run_id, matrix_path=MATRIX, corpus_path=CORPUS,
                                        subset="quick", cohort_path=None)
        self.plan_path = self.root / "language-run-plan.json"
        self.plan_path.write_text(json.dumps(self.plan))

    def tearDown(self):
        self.directory.cleanup()

    def macos_run(self):
        wav_dir = self.root / "wav"
        rows = []
        for index, planned in enumerate(self.plan["takes"]):
            path = write_wav(wav_dir / f"{planned['cellID']}.wav", value=100 + index)
            rows.append({"generationID": f"{planned['cellID']}-gen", "notes": {
                "benchRunID": self.run_id, "benchCell": planned["cellID"],
                "samplingWAVDigest": store.sha256_file(path)}})
        engine = self.root / "diagnostics/engine/generations.jsonl"
        engine.parent.mkdir(parents=True)
        engine.write_text("".join(json.dumps(row) + "\n" for row in rows))
        return wav_dir

    def test_macos_takes_bind_each_wav_to_the_engine_digest(self):
        wav_dir = self.macos_run()
        manifest = language.build_takes(platform="macos", run_id=self.run_id, plan=self.plan_path, corpus=CORPUS,
                                        diagnostics=self.root / "diagnostics", wav_dir=wav_dir)
        self.assertEqual(manifest["schema"], store.TAKES_SCHEMA)
        self.assertEqual((manifest["kind"], manifest["platform"], manifest["source"]),
                         ("language-bench", "macos", self.run_id))
        takes = {take["languageBench"]["cellID"]: take for take in manifest["takes"]}
        self.assertEqual(len(takes), 7)
        scripts = {entry["id"]: entry["script"] for entry in store.read_json(CORPUS)["languages"]}
        control = takes["custom-fr-text-en-pinned"]
        self.assertTrue(control["control"])
        self.assertEqual((control["language"], control["text"]), ("english", scripts["french"]))
        self.assertEqual(control["languageBench"]["expectedOutcome"], "fail")
        self.assertFalse(takes["custom-fr-pinned"]["control"])
        self.assertEqual(takes["design-fr-pinned"]["voice"][:7], "design-")
        self.assertEqual(takes["custom-fr-pinned"]["takeID"], f"{self.run_id}--custom-fr-pinned")
        self.assertAlmostEqual(takes["custom-fr-pinned"]["languageBench"]["durationSeconds"], 2.0)
        self.assertEqual(len({take["token"] for take in manifest["takes"]}), 7)
        # Bytes that differ from the published digest refuse the run.
        write_wav(wav_dir / "custom-fr-pinned.wav", value=999)
        with self.assertRaisesRegex(language.LanguageBenchError, "differs from the engine"):
            language.build_takes(platform="macos", run_id=self.run_id, plan=self.plan_path, corpus=CORPUS,
                                 diagnostics=self.root / "diagnostics", wav_dir=wav_dir)
        with self.assertRaisesRegex(language.LanguageBenchError, "another run ID"):
            language.build_takes(platform="macos", run_id="other-run", plan=self.plan_path, corpus=CORPUS,
                                 diagnostics=self.root / "diagnostics", wav_dir=wav_dir)

    def test_ios_takes_bind_each_output_to_its_sentinel(self):
        diagnostics = self.root / "evidence"
        for index, planned in enumerate(self.plan["takes"]):
            child = planned["childRunID"]
            output = write_wav(diagnostics / child / "output.wav", value=200 + index)
            (diagnostics / child / "device-diagnostics-done.json").write_text(json.dumps({
                "runID": child, "status": "ok", "generationID": f"{child}-gen",
                "outputEvidence": {"sha256": store.sha256_file(output)}}))
        manifest = language.build_takes(platform="ios", run_id=self.run_id, plan=self.plan_path, corpus=CORPUS,
                                        diagnostics=diagnostics)
        self.assertEqual(len(manifest["takes"]), 7)
        self.assertEqual(manifest["takes"][0]["languageBench"]["generationID"],
                         f"{self.plan['takes'][0]['childRunID']}-gen")
        self.assertEqual(language.LANES["ios"], "ios-language-bench")


class LanguageEvidenceTests(unittest.TestCase):
    FRENCH = "un deux trois quatre cinq six sept huit"

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.layout = temporary_layout(self.root)
        takes = []
        for index, (cell, expected, outcome) in enumerate((("fr", "french", "pass"), ("control", "english", "fail"))):
            path = write_wav(self.root / "wav" / f"{cell}.wav", value=10 + index)
            takes.append({
                "takeID": f"lang-run--{cell}", "token": store.take_token("lang-run", cell), "audio": str(path),
                "audioSHA256": store.sha256_file(path), "language": expected, "text": self.FRENCH,
                "control": outcome == "fail",
                "languageBench": {"cellID": cell, "childRunID": f"lang-run--{cell}", "generationID": f"{cell}-gen",
                                  "expectedOutcome": outcome, "scriptLanguage": "french",
                                  "scriptSHA256": metrics.text_sha256(self.FRENCH), "durationSeconds": 2.0},
            })
        self.manifest = {"schema": store.TAKES_SCHEMA, "kind": "language-bench", "source": "lang-run",
                         "platform": "macos", "generationProcessExited": True, "takes": takes}
        self.run_id = "language-bench-20261001-000000-abcd"
        write_run(self.layout, self.run_id, self.manifest,
                  {"asrA": "asr.qwen3-asr-1.7b", "asrB": "asr.whisper-large-v3"}, lane="language-bench")

    def tearDown(self):
        self.directory.cleanup()

    def recognize(self, *, transcript=None, language_name="French", skip=None):
        for take in self.manifest["takes"]:
            for model_id in ("asr.qwen3-asr-1.7b", "asr.whisper-large-v3"):
                if skip == model_id:
                    continue
                write_result(self.layout, model_id, take["audioSHA256"], {
                    "text": transcript or self.FRENCH, "language": language_name,
                    "languageProbs": {"french": 0.96, "english": 0.04}, "words": None, "truncated": False})

    def test_two_families_meet_each_take_and_the_control_is_a_language_control(self):
        self.recognize()
        evidence = language.build_evidence(self.layout, self.run_id)
        self.assertEqual((evidence["status"], language.exit_code(evidence)), ("pass", 0))
        self.assertEqual(evidence["schema"], "vocello.qc.language-evidence/1")
        self.assertEqual((evidence["runID"], evidence["platform"]), ("lang-run", "macos"))
        self.assertEqual(set(evidence["recognizers"]), {"qwen3-asr", "whisper"})
        self.assertEqual(evidence["recognizers"]["whisper"]["modelID"], "asr.whisper-large-v3")
        control = evidence["cells"]["lang-run--control"]
        self.assertEqual(control["verdict"]["channels"], {"language": "fail", "accuracy": "pass"})
        recognition = evidence["cells"]["lang-run--fr"]["recognitions"][0]
        self.assertEqual((recognition["detectedLanguage"], recognition["languageMatchScore"]), ("french", 0.96))
        self.assertEqual(recognition["processedDurationSeconds"], 2.0)
        self.assertTrue(recognition["fullFileProcessed"])
        # The publisher's re-scoring accepts every cell of it.
        for cell in evidence["cells"].values():
            verdict = metrics.qc_take_verdict(
                cell["recognitions"], audio_sha256=cell["audioSHA256"], script=self.FRENCH,
                language=cell["expectedLanguage"], duration_seconds=2.0,
                expect_failure=cell["expectedOutcome"] == "fail")
            self.assertEqual(verdict["status"], "pass")
        # The summary never prints a transcript.
        self.assertNotIn(self.FRENCH, "\n".join(language.summary_lines(evidence)))

    def test_a_wrong_transcript_fails_and_a_missing_family_is_an_error(self):
        self.recognize(transcript="neuf huit sept six cinq quatre trois deux")
        evidence = language.build_evidence(self.layout, self.run_id)
        self.assertEqual((evidence["status"], language.exit_code(evidence)), ("fail", 1))
        self.assertEqual(evidence["cells"]["lang-run--fr"]["verdict"]["channels"]["accuracy"], "fail")

        shutil.rmtree(self.layout.results)
        self.recognize(skip="asr.whisper-large-v3")
        evidence = language.build_evidence(self.layout, self.run_id)
        self.assertEqual((evidence["status"], language.exit_code(evidence)), ("error", 2))
        self.assertEqual(len(evidence["missing"]), 2)

    def test_a_run_of_another_kind_or_a_changed_recognizer_is_refused(self):
        with self.assertRaises(language.LanguageBenchError):
            language.build_evidence(self.layout, "../escape")
        (self.root / "scripts/qc/runners/whisper.py").write_text("# changed\n")
        with self.assertRaisesRegex(language.LanguageBenchError, "changed since"):
            language.build_evidence(self.layout, self.run_id)


class QCTakeVerdictTests(unittest.TestCase):
    SCRIPT = "un deux trois quatre cinq six sept huit"

    def recognitions(self, **overrides):
        out = []
        for family in metrics.QC_RECOGNITION_FAMILIES:
            out.append({
                "schemaVersion": metrics.QC_RECOGNITION_SCHEMA, "algorithmVersion": metrics.QC_ASR_ALGORITHM,
                "modelFamily": family, "audioSHA256": "a" * 64, "inputTextSHA256": metrics.text_sha256(self.SCRIPT),
                "status": "complete", "outputLanguage": "french", "detectedLanguage": "french",
                "languageMatchScore": 0.9, "fullFileProcessed": True, "processedDurationSeconds": 2.0,
                "transcript": self.SCRIPT,
                "provenance": {"runtimeSHA256": "1" * 64, "modelIdentitySHA256": "2" * 64, "configSHA256": "3" * 64},
                **overrides.get(family, {}),
            })
        return out

    def verdict(self, recognitions, *, expect_failure=False):
        return metrics.qc_take_verdict(recognitions, audio_sha256="a" * 64, script=self.SCRIPT, language="french",
                                       duration_seconds=2.0, expect_failure=expect_failure)

    def test_statuses(self):
        self.assertEqual(self.verdict(self.recognitions())["status"], "pass")
        self.assertEqual(self.verdict(self.recognitions(whisper={"detectedLanguage": "english"}))["status"],
                         "inconclusive")
        both = self.recognitions(**{family: {"detectedLanguage": "english"} for family in ("qwen3-asr", "whisper")})
        self.assertEqual(self.verdict(both)["status"], "fail")
        self.assertEqual(self.verdict(both, expect_failure=True)["status"], "pass")
        unqualified = self.verdict(self.recognitions(whisper={"languageMatchScore": None}))
        self.assertEqual((unqualified["status"], unqualified["issues"]["whisper"]), ("unqualified",
                                                                                   ["language-score-invalid"]))
        self.assertEqual(self.verdict(self.recognitions()[:1])["issues"], {"whisper": ["missing"]})

    def test_the_language_control_constrains_the_language_channel(self):
        self.assertEqual(metrics.expected_channel_outcomes(True, metrics.LANGUAGE_CONTROL_KIND), {"language": "fail"})
        self.assertEqual(metrics.expected_channel_outcomes(True), {"accuracy": "fail"})
        self.assertTrue(metrics.single_family_meets_expectation(
            False, True, expect_failure=True, control_kind=metrics.LANGUAGE_CONTROL_KIND))
        self.assertFalse(metrics.single_family_meets_expectation(
            True, False, expect_failure=True, control_kind=metrics.LANGUAGE_CONTROL_KIND))
        self.assertEqual(metrics.run_channel_verdicts(
            [({"language": "pass", "accuracy": "pass"}, False), ({"language": "fail", "accuracy": "pass"}, True)],
            metrics.LANGUAGE_CONTROL_KIND), {"language": "pass", "accuracy": "pass"})
        with self.assertRaises(ValueError):
            metrics.expected_channel_outcomes(True, "unknown-control")


class CloneFidelityTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.layout = temporary_layout(self.root)

    def tearDown(self):
        self.directory.cleanup()

    def test_pitch_and_identity_are_measured_against_the_reference(self):
        reference = write_wav(self.root / "reference.wav", value=7)
        take_path = write_wav(self.root / "clone.wav", value=8)
        reference_sha = store.sha256_file(reference)
        take = {"takeID": "clone_take_00", "token": "0" * 16, "audio": str(take_path),
                "audioSHA256": store.sha256_file(take_path), "language": "english", "text": "x", "mode": "clone",
                "voice": "clone-v", "reference": str(reference), "referenceSHA256": reference_sha, "control": False}
        manifest = {"schema": store.TAKES_SCHEMA, "source": "clone", "takes": [take]}
        roles = {"pitchA": "pitch.fcpe", "pitchB": "pitch.swiftf0", "speaker": "speaker.redimnet2-plus"}
        run = write_run(self.layout, "clone-lane-20261001-000000-abcd", manifest, roles, lane="clone-lane")
        store.write_json_atomic(run / "flags.json", {"takes": [{"token": take["token"], "flags": [
            {"detector": "prosody.pitch", "class": "pitch", "level": "report-only"}]}]})
        for model_id in ("pitch.fcpe", "pitch.swiftf0"):
            for sha, hz in ((take["audioSHA256"], 220.0), (reference_sha, 196.0)):
                write_result(self.layout, model_id, sha, {"hopSeconds": 0.01, "f0Hz": [hz] * 200,
                                                          "confidence": [0.9] * 200})
        speaker = fidelity.models.find_model(store.read_json(self.layout.registry)["models"],
                                             "speaker.redimnet2-plus")
        write_result(self.layout, "speaker.redimnet2-plus", take["audioSHA256"], {
            "whole": [1.0, 0.0, 0.0], "reference": [0.8, 0.6, 0.0],
            "windows": [{"start": 0.0, "end": 4.0, "embedding": [1.0, 0.0, 0.0]},
                        {"start": 1.0, "end": 5.0, "embedding": [0.6, 0.8, 0.0]}]},
            variant=store.take_variant(speaker, take))
        rows = fidelity.take_fidelity(self.layout, run.name)
        self.assertEqual(len(rows), 1)
        pitch = rows[0]["pitch"]
        self.assertTrue(pitch["available"])
        self.assertAlmostEqual(pitch["registerShiftSemitones"], 12 * np.log2(220 / 196), places=2)
        self.assertEqual(pitch["octaveJumps"], 0)
        identity = rows[0]["identity"]
        self.assertAlmostEqual(identity["similarity"], 0.8)
        self.assertAlmostEqual(identity["worstWindowSimilarity"], 0.8)
        self.assertEqual(identity["worstWindow"], {"start": 0.0, "end": 4.0})
        aggregate = fidelity.aggregate(rows)
        self.assertEqual(aggregate["flagCounts"], {"prosody.pitch": 1})
        self.assertAlmostEqual(aggregate["similarity"]["median"], 0.8)
        models = fidelity.run_models(self.layout, run.name)
        self.assertEqual(models["speaker"]["id"], "speaker.redimnet2-plus")

    def test_a_take_without_results_or_reference_is_unavailable(self):
        self.assertEqual(fidelity.pitch_section(None, None), {"available": False})
        self.assertEqual(fidelity.identity_section(None), {"available": False})
        self.assertEqual(fidelity.identity_section({"whole": [1.0], "reference": None}),
                         {"available": False, "reason": "no-reference"})


if __name__ == "__main__":
    unittest.main()
