#!/usr/bin/env python3
"""Stage 2 jobs for the AQ-06 panel judges (audit P8): building, admission, caching, metrics and verdicts.

No model runs: a fixture worker speaks the real worker protocol for every panel
engine under the real supervisor and admission, answering from tables keyed by
canonical PCM. It proves that the orchestrator:

- builds each panel judge from its worker launch with the registry's threads,
  ceiling and engine, keyed by an output identity that changes with them;
- asks each judge what its profile says (the ISO code or the language name, the
  script for the aligner, the reference clip for a speaker judge) and leaves
  out-of-scope takes alone;
- caches each judge's rows under its own output identity (a second run
  launches nothing);
- reduces each family's raw output to its metrics, keeps transcripts private,
  and lists every panel verdict as report-only, so the take verdict is exactly
  what it is without the panel.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
from pathlib import Path
import struct
import sys
import tempfile
import unittest
import wave

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import audio_qc_orchestrator as orchestrator_module  # noqa: E402
from audio_qc_judges import load_registry  # noqa: E402
from audio_qc_orchestrator import (  # noqa: E402
    MANIFEST_SCHEMA,
    Orchestrator,
    OrchestratorError,
    Stage2Judge,
    _take,
    panel_stage2_judge,
    select_panel_judges,
)
from delivery_analysis_cache import DeliveryAnalysisCache, digest, file_sha256  # noqa: E402
from delivery_resource_supervisor import HostSnapshot, run_supervised  # noqa: E402
from lib.language_metrics import text_sha256  # noqa: E402
from lib.qc_pipeline import panel_metrics  # noqa: E402
from lib.qc_pipeline.admission import judge_admission  # noqa: E402
from lib.qc_pipeline.evidence import validate_take_evidence  # noqa: E402
from lib.qc_pipeline.layered_cache import JudgeIdentity, output_identity_digest  # noqa: E402
from lib.qc_pipeline.panel_jobs import REFERENCE_SUFFIX, panel_judge_ids  # noqa: E402
from lib.qc_pipeline.verdicts import channel_detectors, compose_take  # noqa: E402
from lib.qc_qualification.composer import CompositionError, compose  # noqa: E402

FIXTURE_WORKER = Path(__file__).resolve().parent / "fixtures/audio_qc_panel_fixture_worker.py"
MIB = 1024**2
HOST = {"system": "Darwin", "machine": "arm64", "modelIdentifier": "Mac16,11"}
CANONICAL_HOST = "mac-mini-m6-16gb"
WHISPER_SMALL = "asr.whisper-small@1"
WHISPER_LARGE = "asr.whisper-large-v3@1"
PARAKEET = "asr.parakeet-tdt-0.6b-v3@1"
PARAFORMER = "asr.paraformer-zh@1"
SENSEVOICE = "asr.sensevoice-small-f16@1"
QWEN_ASR = "asr.qwen3-asr-1.7b@1"
ALIGNER = "align.qwen3-forcedaligner-0.6b@1"
LID = "lid.voxlingua107-ecapa@1"
CAMPPLUS = "speaker.campplus-voxceleb@1"
RESNET = "speaker.resnet293-voxceleb@1"
PYIN = "pitch.pyin@1"
AUDIOBOX = "quality.audiobox-aesthetics@1"
DNSMOS = "quality.dnsmos-p835@1"
SCRIPTS = {
    "english": "The quiet garden opens early every morning.",
    "chinese": "安静的花园每天早上很早开门。",
    "korean": "조용한 정원은 매일 아침 일찍 문을 엽니다.",
}


def quiet_supervisor(command, **kwargs):
    result = run_supervised(command, snapshotter=lambda: HostSnapshot(50.0, 0, False),
                            rss_sampler=lambda _pid: 32 * MIB, physical_footprint_sampler=lambda _pid: 48 * MIB,
                            **kwargs)
    # The fixture host stands in for the canonical M6.
    result.report["hostProfileID"] = CANONICAL_HOST
    return result


def refusing_supervisor(command, **kwargs):
    raise AssertionError("a cached run launched a worker")


def write_tone(path: Path, frequency: float, *, seconds: float = 2.0, amplitude: int = 7000) -> None:
    count = int(24_000 * seconds)
    samples = [int(math.sin(2 * math.pi * frequency * index / 24_000) * amplitude) for index in range(count)]
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(24_000)
        output.writeframes(struct.pack(f"<{count}h", *samples))


class PanelFixture(unittest.TestCase):
    """A registry, a cache root, audio and fixture panel judges; no test of its own."""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.cache_root = self.root / "cache"
        self.registry = load_registry()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def audio(self, name: str, frequency: float, **kwargs) -> Path:
        path = self.root / f"{name}.wav"
        write_tone(path, frequency, **kwargs)
        return path

    def pcm(self, audio: Path) -> str:
        return DeliveryAnalysisCache(self.cache_root).canonicalize(audio).canonical_derivative_sha256

    def launch(self, judge_id: str, registry: dict | None = None, **config) -> dict:
        registry = registry or self.registry
        execution = registry["judges"][judge_id]["execution"]
        return {"judge": judge_id, "engine": execution["engine"], "lane": execution["lane"],
                "threads": execution["threads"], "command": [sys.executable, str(FIXTURE_WORKER)],
                "engineConfig": {"judge": judge_id, **config}}

    def panel_judge(self, judge_id: str, registry: dict | None = None, **config) -> Stage2Judge:
        registry = registry or self.registry
        return panel_stage2_judge(judge_id, self.launch(judge_id, registry, **config), registry, host=HOST)

    def whisper_small(self, table: dict) -> Stage2Judge:
        return Stage2Judge(
            judge_id=WHISPER_SMALL, engine="fixture", command=(sys.executable, str(FIXTURE_WORKER)),
            engine_config={"table": table},
            identity=JudgeIdentity(WHISPER_SMALL, output_identity_digest(WHISPER_SMALL, {"fixture": "small", "threads": 2}),
                                   "fixture/whisper-small", "a" * 40, hashlib.sha256(b"fixture weights").hexdigest()),
            threads=2, family="whisper",
            language_codes={"english": "en", "chinese": "zh", "korean": "ko"},
            model_identity_sha256=digest({"fixture": "whisper-small"}),
        )

    def take(self, take_id: str, audio: Path, language: str, *, script: bool = True,
             reference: Path | None = None, role: str | None = None) -> dict:
        text = SCRIPTS[language] if script else None
        return _take(take_id=take_id, generation_id=take_id, audio=str(audio), audio_sha256=file_sha256(audio),
                     language=language, reference_text=text, script_sha256=text_sha256(text) if text else None,
                     role=role, cell_id=take_id,
                     reference_audio=str(reference) if reference else None,
                     reference_audio_sha256=file_sha256(reference) if reference else None)

    def manifest(self, takes: list[dict], run_id: str = "panel-fixture") -> dict:
        return {"schema": MANIFEST_SCHEMA, "runID": run_id, "lane": "language-bench", "platform": "macos",
                "generationProcessExited": True, "source": {"kind": "fixture", "sha256": "0" * 64},
                "takes": takes, "pairs": []}

    def orchestrator(self, judges: list[Stage2Judge], *, cache_root: Path | None = None,
                     supervisor=quiet_supervisor, offline: bool = False) -> Orchestrator:
        return Orchestrator(registry=self.registry, cache=DeliveryAnalysisCache(cache_root or self.cache_root),
                            lock_root=self.root / "locks", stage2=judges, supervisor=supervisor, offline=offline)

    def whisper_answer(self, transcript: str, code: str, audio: Path) -> dict:
        duration = DeliveryAnalysisCache(self.cache_root).canonicalize(audio).duration_seconds
        return {"transcript": transcript, "language": code, "detectedLanguage": code,
                "detectedLanguageProbability": 0.93, "expectedLanguageProbability": 0.91,
                "segments": [{"start": 0.0, "end": duration, "noSpeechProb": 0.01, "avgLogprob": -0.2}]}

    def panel_scene(self) -> tuple[dict, list[Stage2Judge], dict]:
        """English (with a reference clip), Chinese and Korean takes, and every panel judge's answers."""
        english, chinese, korean = self.audio("en", 180), self.audio("zh", 220), self.audio("ko", 260)
        reference = self.audio("en-reference", 190)
        takes = [self.take("custom-en", english, "english", reference=reference),
                 self.take("custom-zh", chinese, "chinese"), self.take("custom-ko", korean, "korean")]
        pcm = {name: self.pcm(path) for name, path in (("en", english), ("zh", chinese), ("ko", korean))}
        whisper = {pcm["en"]: self.whisper_answer(SCRIPTS["english"], "en", english),
                   pcm["zh"]: self.whisper_answer(SCRIPTS["chinese"], "zh", chinese),
                   pcm["ko"]: self.whisper_answer(SCRIPTS["korean"], "ko", korean)}
        lid = {pcm["en"]: {"logPosteriors": {"en": -0.05, "fr": -3.5, "zh": -6.0, "nl": -4.0}, "top1": "en"},
               pcm["zh"]: {"logPosteriors": {"zh": -0.1, "en": -3.0, "ja": -4.0}, "top1": "zh"},
               pcm["ko"]: {"logPosteriors": {"ja": -0.2, "ko": -1.9}, "top1": "ja"}}
        judges = [
            self.whisper_small(whisper),
            self.panel_judge(WHISPER_LARGE, table=whisper),
            self.panel_judge(PARAKEET, default={"transcript": "The quiet garden opens late every morning."}),
            self.panel_judge(PARAFORMER, default={"transcript": SCRIPTS["chinese"]}),
            self.panel_judge(SENSEVOICE, default={"stdout": "<|ko|><|NEUTRAL|><|Speech|><|woitn|>" + SCRIPTS["korean"]}),
            self.panel_judge(QWEN_ASR, default={"transcript": SCRIPTS["english"]}),
            self.panel_judge(ALIGNER, default={"units": ["a", "b", "c"], "intervals": [
                {"unit": "a", "start": 0.1, "end": 0.4}, {"unit": "b", "start": 0.5, "end": 0.9}]}),
            self.panel_judge(LID, table=lid),
            self.panel_judge(CAMPPLUS, embedFromDigest=True),
            self.panel_judge(RESNET, embedFromDigest=True),
            self.panel_judge(PYIN, default={"hopSeconds": 0.01, "f0Hz": [None, 200.0, 210.0, 190.0],
                                            "voiced": [False, True, True, True],
                                            "voicedProbability": [0.1, 0.9, 0.9, 0.8]}),
            self.panel_judge(AUDIOBOX, default={"CE": 5.1, "CU": 5.5, "PC": 2.0, "PQ": 6.0}),
            self.panel_judge(DNSMOS, default={"SIG": 3.3, "BAK": 3.9, "OVRL": 3.0, "P808_MOS": 3.5,
                                              "windowsScored": 1}),
        ]
        return self.manifest(takes), judges, {"whisper": whisper}


class PanelJobTests(PanelFixture):
    def test_every_panel_judge_is_built_from_its_launch_with_the_registrys_threads_and_ceiling(self) -> None:
        panel = panel_judge_ids(self.registry)
        self.assertEqual(len(panel), 12)
        self.assertEqual(select_panel_judges(self.registry, [], panel=True), panel)
        identities = set()
        for judge_id in panel:
            with self.subTest(judge=judge_id):
                judge = self.panel_judge(judge_id)
                admission = judge_admission(self.registry, judge_id)
                spec = judge.spec(admission.ceiling_bytes, admission.lane)
                self.assertEqual((judge.threads, spec.threads, spec.ceiling_bytes, spec.lane),
                                 (admission.threads, admission.threads, admission.ceiling_bytes,
                                  self.registry["judges"][judge_id]["execution"]["lane"]))
                self.assertTrue(judge.measure_physical_footprint)
                # Candidates, same-lab judges and ResNet293 only report.
                self.assertTrue(judge.report_only)
                self.assertEqual(judge.identity_components["threads"], admission.threads)
                identities.add(judge.identity.output_identity)
        self.assertEqual(len(identities), len(panel), "each judge caches under its own output identity")
        # The thread count is output identity: another count is another L1 key.
        registry = copy.deepcopy(self.registry)
        registry["judges"][PARAKEET]["execution"]["threads"] = 3
        self.assertNotEqual(self.panel_judge(PARAKEET, registry).identity.output_identity,
                            self.panel_judge(PARAKEET).identity.output_identity)
        # So is the host, until cross-host determinism is measured.
        other_host = panel_stage2_judge(PARAKEET, self.launch(PARAKEET), self.registry,
                                        host={**HOST, "modelIdentifier": "Mac14,3"})
        self.assertNotEqual(other_host.identity.output_identity, self.panel_judge(PARAKEET).identity.output_identity)
        # A launch that disagrees with the registry is refused.
        with self.assertRaisesRegex(OrchestratorError, "engine and threads"):
            panel_stage2_judge(PARAKEET, {**self.launch(PARAKEET), "threads": 7}, self.registry, host=HOST)
        with self.assertRaisesRegex(OrchestratorError, "--judge-config"):
            select_panel_judges(self.registry, [WHISPER_SMALL], panel=False)

    def test_each_judge_is_asked_what_its_profile_says(self) -> None:
        english, chinese = self.audio("en", 180), self.audio("zh", 220)
        en = self.take("en", english, "english")
        zh = self.take("zh", chinese, "chinese")
        bare = self.take("bare", english, "english", script=False)
        judges = {judge_id: self.panel_judge(judge_id) for judge_id in panel_judge_ids(self.registry)}
        self.assertEqual(judges[WHISPER_LARGE].request(en), {"lockedLanguage": "en"})
        self.assertEqual(judges[QWEN_ASR].request(zh), {"lockedLanguage": "Chinese"})
        self.assertIsNone(judges[PARAFORMER].request(en))
        self.assertEqual(judges[PARAFORMER].request(zh), {"lockedLanguage": "zh"})
        self.assertIsNone(judges[SENSEVOICE].request(en))
        self.assertIsNone(judges[PARAKEET].request(zh))
        self.assertEqual(judges[ALIGNER].request(en), {"lockedLanguage": "English", "scriptSHA256": en["scriptSHA256"]})
        self.assertIsNone(judges[ALIGNER].request(bare), "the aligner needs a script")
        for judge_id in (LID, CAMPPLUS, RESNET, PYIN, AUDIOBOX, DNSMOS):
            self.assertEqual(judges[judge_id].request(zh), {}, judge_id)
        canonical = DeliveryAnalysisCache(self.cache_root).canonicalize(english)
        row = judges[ALIGNER].job_row("key", canonical, judges[ALIGNER].request(en), en)
        self.assertEqual((row["language"], row["referenceText"]), ("English", SCRIPTS["english"]))
        self.assertEqual(set(judges[LID].job_row("key", canonical, {}, en)), {"id", "pcmPath"})


class PanelRunTests(PanelFixture):
    def test_the_orchestrator_runs_every_panel_judge_and_reduces_each_familys_metrics(self) -> None:
        manifest, judges, _answers = self.panel_scene()
        result = self.orchestrator(judges).run(manifest)
        workers = {worker["judge"]: worker for worker in result["header"]["workers"]}
        for judge in judges[1:]:
            with self.subTest(judge=judge.judge_id):
                admission = judge_admission(self.registry, judge.judge_id)
                launches = workers[judge.judge_id]["launches"]
                self.assertEqual(len(launches), 1, "one persistent worker per judge per run")
                envelope = launches[0]["resourceEnvelope"]
                self.assertEqual((envelope["admission"]["judge"], envelope["admission"]["ceilingBytes"],
                                  envelope["admission"]["lane"]),
                                 (judge.judge_id, admission.ceiling_bytes, admission.lane))
                self.assertEqual(workers[judge.judge_id]["threads"], admission.threads)
        # Only in-scope takes run: Paraformer sees Chinese, SenseVoice Korean, Parakeet English.
        self.assertEqual({judge: workers[judge]["launches"][0]["rows"] for judge in (PARAFORMER, SENSEVOICE, PARAKEET)},
                         {PARAFORMER: 1, SENSEVOICE: 1, PARAKEET: 1})
        # The speaker judges embed the English take's reference clip as its own row.
        self.assertEqual(workers[CAMPPLUS]["launches"][0]["rows"], 4)
        self.assertIn("custom-en" + REFERENCE_SUFFIX, result["raw"][CAMPPLUS])
        records = {record["take"]["takeID"]: record for record in result["records"]}
        for record in records.values():
            self.assertEqual(validate_take_evidence(record), [])
            dumped = json.dumps(record, ensure_ascii=False)
            for script in SCRIPTS.values():
                self.assertNotIn(script, dumped, "transcripts and scripts stay private")
        en = {item["judge"]: item for item in records["custom-en"]["measurements"]}
        zh = {item["judge"]: item for item in records["custom-zh"]["measurements"]}
        ko = {item["judge"]: item for item in records["custom-ko"]["measurements"]}
        self.assertEqual((en[WHISPER_LARGE]["metrics"]["errorRate"], en[WHISPER_LARGE]["metrics"]["detectedLanguage"]),
                         (0.0, "english"))
        self.assertGreater(en[PARAKEET]["metrics"]["errorRate"], 0.0)
        self.assertEqual(en[PARAKEET]["metrics"]["accuracyMetricVersion"], "normalization-v3-edit-rate-v4")
        self.assertEqual(zh[PARAFORMER]["metrics"]["metric"], "CER")
        self.assertEqual((ko[SENSEVOICE]["metrics"]["detectedLanguage"], ko[SENSEVOICE]["metrics"]["errorRate"]),
                         ("korean", 0.0))
        self.assertEqual(en[PARAFORMER]["status"], "out-of-scope")
        self.assertEqual(en[LID]["metrics"]["topLanguage"], "english")
        self.assertGreater(en[LID]["metrics"]["expectedPosterior"], 0.9)
        self.assertEqual(ko[LID]["metrics"]["topLanguage"], "japanese")
        self.assertIsNotNone(en[CAMPPLUS]["metrics"]["cosine"])
        self.assertEqual(zh[CAMPPLUS]["metrics"], {}, "no reference clip, no speaker metric")
        self.assertEqual((en[PYIN]["metrics"]["voicedFrames"], en[PYIN]["metrics"]["f0MedianHz"]), (3, 200.0))
        self.assertEqual(en[AUDIOBOX]["metrics"], {"CE": 5.1, "CU": 5.5, "PC": 2.0, "PQ": 6.0})
        self.assertEqual((en[DNSMOS]["metrics"]["SIG"], en[DNSMOS]["metrics"]["BAK"], en[DNSMOS]["metrics"]["OVRL"]),
                         (3.3, 3.9, 3.0))
        self.assertEqual((en[ALIGNER]["metrics"]["unitsExpected"], en[ALIGNER]["metrics"]["unitsAligned"]), (3, 2))
        for measurement in en.values():
            if measurement["judge"] in (PARAFORMER, SENSEVOICE):
                continue
            self.assertEqual(measurement["cache"]["l1"], "miss")
        private = {entry["manifestTakeID"]: entry for entry in result["privates"]}
        self.assertEqual(private["custom-en"]["transcripts"][WHISPER_LARGE], SCRIPTS["english"])
        # Every panel verdict only reports: the take verdict is whisper-small's alone.
        panel_verdicts = [verdict for verdict in records["custom-en"]["verdicts"]
                          if verdict["detector"].startswith("panel.")]
        self.assertTrue(panel_verdicts)
        self.assertTrue(all(verdict.get("reportOnly") and not verdict["gating"] for verdict in panel_verdicts))
        self.assertTrue(all(verdict["status"] in ("uncalibrated", "unavailable") for verdict in panel_verdicts))
        detectors = {verdict["detector"]: verdict for verdict in panel_verdicts}
        self.assertEqual(detectors["panel.asr.parakeet-tdt-0.6b-v3.accuracy@1"]["reportedStatus"], "pass")
        self.assertEqual(detectors["panel.lid.voxlingua107-ecapa.language@1"]["reportedStatus"], "pass")
        self.assertIn("panel.speaker.resnet293-voxceleb.identity@1", detectors)
        alone = self.orchestrator(judges[:1], cache_root=self.root / "alone").run(manifest)
        for record in alone["records"]:
            self.assertEqual(records[record["take"]["takeID"]]["takeVerdict"], record["takeVerdict"])
            self.assertEqual(records[record["take"]["takeID"]]["legacyVerdicts"], record["legacyVerdicts"])

    def test_each_judges_rows_are_cached_under_its_output_identity(self) -> None:
        manifest, judges, _answers = self.panel_scene()
        first = self.orchestrator(judges).run(manifest)
        replay = self.orchestrator(judges, supervisor=refusing_supervisor, offline=True).run(manifest)
        self.assertEqual(replay["header"]["cache"]["L1"]["misses"], 0)
        self.assertEqual(replay["header"]["workers"], [])
        for before, after in zip(first["records"], replay["records"]):
            self.assertEqual({item["judge"]: item["metrics"] for item in before["measurements"]},
                             {item["judge"]: item["metrics"] for item in after["measurements"]})
            self.assertEqual(before["verdicts"], after["verdicts"])
        # A judge whose output identity changes (its thread count) must run again; the others stay cached.
        registry = copy.deepcopy(self.registry)
        registry["judges"][AUDIOBOX]["execution"]["threads"] = 3
        changed = panel_stage2_judge(AUDIOBOX, self.launch(AUDIOBOX, registry, default={"CE": 1.0}), registry,
                                     host=HOST)
        with self.assertRaisesRegex(OrchestratorError, "quality.audiobox-aesthetics@1"):
            self.orchestrator([*judges[:-2], changed, judges[-1]], supervisor=refusing_supervisor,
                              offline=True).run(manifest)

    def test_a_panel_judge_that_fails_is_unavailable_and_still_only_reports(self) -> None:
        manifest, judges, _answers = self.panel_scene()
        # The DNSMOS worker's command does not exist: it never becomes ready, twice.
        broken = Stage2Judge(**{**judges[-1].__dict__, "command": (sys.executable, str(self.root / "missing.py"))})
        result = self.orchestrator([judges[0], broken]).run(manifest)
        for record in result["records"]:
            measured = {item["judge"]: item for item in record["measurements"]}
            self.assertEqual(measured[DNSMOS]["status"], "unavailable")
            verdict = [item for item in record["verdicts"] if item["detector"] == "panel.quality.dnsmos-p835.quality@1"]
            self.assertEqual((verdict[0]["status"], verdict[0]["gating"]), ("unavailable", False))
            self.assertNotEqual(record["takeVerdict"]["status"], "unavailable")


class PanelMetricTests(unittest.TestCase):
    def test_language_id_is_restricted_to_the_product_languages_plus_other(self) -> None:
        metrics = panel_metrics.lid_reduce({"logPosteriors": {"en": math.log(0.6), "nl": math.log(0.3),
                                                              "fr": math.log(0.1)}, "top1": "en"}, language="french")
        self.assertAlmostEqual(metrics["otherMass"], 0.3, places=5)
        self.assertEqual(metrics["topLanguage"], "english")
        self.assertAlmostEqual(metrics["margin"], 0.1 - 0.6, places=5)

    def test_speaker_pitch_alignment_and_sensevoice_reductions(self) -> None:
        self.assertEqual(panel_metrics.speaker_reduce({"embedding": [1.0, 0.0]}, None), {})
        same = panel_metrics.speaker_reduce({"embedding": [1.0, 0.0], "windows": [{"embedding": [0.0, 1.0]}]},
                                            {"embedding": [2.0, 0.0]})
        self.assertEqual((same["cosine"], same["windowCosineMinimum"]), (1.0, 0.0))
        silent = panel_metrics.pitch_reduce({"f0Hz": [None, None], "voiced": [False, False]})
        self.assertEqual((silent["voicedFrames"], silent["f0MedianHz"]), (0, None))
        octave = panel_metrics.pitch_reduce({"f0Hz": [100.0, 200.0], "voiced": [True, True]})
        self.assertAlmostEqual(octave["f0RangeSemitones"], 12.0 * math.log2(195.0 / 105.0), places=3)
        aligned = panel_metrics.alignment_reduce({"units": ["a", "b"], "intervals": [
            {"start": 0.5, "end": 1.0}, {"start": 0.2, "end": 0.1}]}, duration_seconds=2.0)
        self.assertEqual((aligned["unitsAligned"], aligned["unitCoverage"], aligned["tailGapSeconds"]), (1, 0.5, 1.0))
        unparsed, text = panel_metrics.asr_reduce(SENSEVOICE, {"stdout": "no tags"}, script=None, language="korean")
        self.assertEqual((unparsed["outputParsed"], unparsed["transcriptEmpty"], text), (False, True, None))
        # The pinned llama.cpp binary prints two tags; the FunASR form prints four.
        for stdout in ("<|ko|><|EMO_UNKNOWN|>안녕하세요\n", "<|ko|><|NEUTRAL|><|Speech|><|withitn|>안녕하세요"):
            parsed, _ = panel_metrics.asr_reduce(SENSEVOICE, {"stdout": stdout}, script="안녕하세요",
                                                 language="korean")
            self.assertEqual((parsed["outputParsed"], parsed["transcriptEmpty"], parsed["errorRate"],
                              parsed["detectedLanguage"]), (True, False, 0.0, "korean"), stdout)

    def test_report_only_verdicts_never_decide_a_take(self) -> None:
        gating = {"detector": "content.accuracy@1", "class": "B", "stage": 2, "judges": [WHISPER_SMALL],
                  "status": "pass", "reasons": [], "calibration": None}
        panel = panel_metrics.panel_verdicts(PARAKEET, "asr", stage=2, reporting_only=True, measurement="complete",
                                             metrics={"errorRate": 0.9}, language="english", has_script=True)
        broken = panel_metrics.panel_verdicts(DNSMOS, "dnsmos", stage=2, reporting_only=True,
                                              measurement="unavailable", metrics={}, language="english",
                                              has_script=False, unavailable_reason="admission-timeout")
        self.assertEqual(broken[0]["reasons"], ["timeout"])
        alone = compose([gating], "language-bench")
        with_panel = compose([gating, *panel, *broken], "language-bench")
        self.assertEqual((alone["status"], with_panel["status"]), ("uncalibrated", "uncalibrated"))
        self.assertEqual(sorted(with_panel["advisory"]), sorted(item["detector"] for item in panel + broken))
        with self.assertRaises(CompositionError):
            compose([{**gating, "reportOnly": True}], "language-bench", required=["content.accuracy@1"])
        # An orchestrator code the composer does not know (an admission timeout) maps onto its reasons.
        verdicts = channel_detectors({}, unqualified=[], unavailable={WHISPER_SMALL: "admission-timeout"})
        self.assertEqual({verdict["status"] for verdict in verdicts}, {"unavailable"})
        self.assertEqual(verdicts[0]["reasons"], ["timeout"])
        self.assertEqual(compose_take("language-bench", verdicts)["status"], "unavailable")


if __name__ == "__main__":
    unittest.main()
