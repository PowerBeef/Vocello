#!/usr/bin/env python3
"""Stage 0 generation evidence in measurements.json (AQ-07 classes I and J).

`audio_qc_calibration_set.py score` copies a take's engine introspection
summary and long-form block into its clip, passes the long-form seams to the
Stage 0 seam z-score, and measures each clip's boundary jump on its own PCM.
Takes are procedural renders written at run time; no WAV is committed.
"""

from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import copy
import hashlib
from io import StringIO
import json
from pathlib import Path
import sys
import tempfile
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import audio_qc_calibration_set as m2  # noqa: E402
from lib.qc_qualification import fixtures, injectors, recordings  # noqa: E402
from lib.qc_qualification.pcm import json_digest, pcm_digest  # noqa: E402

SUMMARY = {"algorithmVersion": 1, "codecFrameCount": 60, "longestRepeatedTokenRunFrames": 2,
           "tokenCyclePeriod": 8, "tokenCycleSpanFrames": 32, "tokenCycleRepeats": 4, "tokenCycleStartFrame": 4,
           "observedStepCount": 61, "entropyMeanNats": 0.8, "entropyP95Nats": 1.9, "longestHighEntropyRunSteps": 0,
           "eosProbabilityFinal": 0.6, "eosProbabilityMax": 0.6, "eosProbabilityMaxStep": 60,
           "eosFirstLikelyStep": None, "eosLikelyStepsWithoutStop": 0, "seamCodecFrames": []}


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def quiet(function, *args, **kwargs):
    with redirect_stderr(StringIO()), redirect_stdout(StringIO()):
        return function(*args, **kwargs)


class GenerationEvidenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        first = fixtures.render(fixtures.make_script(601, word_count=6), fixtures.VOICES["low"])
        second = fixtures.render(fixtures.make_script(602, word_count=6), fixtures.VOICES["low"])
        # A two-segment project: the second segment's content starts after a 300 ms pause.
        pause = np.zeros(7_200)
        self.joined = np.concatenate([first, pause, second])
        self.seam = first.size + pause.size
        stored = np.rint(self.joined * recordings.PCM16_FULL_SCALE).astype(np.int64)
        self.jump = int(abs(stored[self.seam] - stored[self.seam - 1]))
        self.block = {"schemaVersion": 1, "algorithmVersion": 4, "sampleRate": 24_000, "segmentCount": 2,
                      "outputFrameCount": int(self.joined.size), "maximumSegmentBoundaryJump": self.jump,
                      "seamFrames": [int(self.seam)]}
        self.single = first

    def tearDown(self) -> None:
        self.directory.cleanup()

    def take(self, take_id: str, samples: np.ndarray, **extra) -> dict:
        wav = recordings.write_pcm16_wav(self.root / "wav" / f"{take_id}.wav", samples)
        return {"takeID": take_id, "family": take_id, "scriptID": take_id.split("--")[0], "language": "english",
                "mode": "custom", "variant": "speed", "voice": {"kind": "builtin", "id": "aiden"}, "seed": 7,
                "text": "one two three four five six", "wavPath": f"wav/{take_id}.wav", "wavSHA256": wav,
                "durationSeconds": round(samples.size / 24_000, 3), "finishReason": "eos", "status": "generated",
                "engineIntrospection": None, "longForm": None, **extra}

    def manifest(self, takes: list[dict]) -> Path:
        path = self.root / "takes.json"
        path.write_text(json.dumps({"schemaVersion": 1, "kind": "audio-qc-calibration-takes", "runID": "run",
                                    "planDigest": "0" * 64, "poolDigest": "1" * 64, "split": "calibration",
                                    "takes": takes}), encoding="utf-8")
        return path

    def entry(self, source: dict, clip_id: str, samples: np.ndarray, *, population: str, mechanism: str,
              **extra) -> dict:
        wav = recordings.write_pcm16_wav(self.root / "set" / "wav" / f"{clip_id}.wav", samples)
        entry = {key: value for key, value in source.items() if key != "text"}
        entry.update(takeID=clip_id, sourceTakeID=source["takeID"], wavPath=f"wav/{clip_id}.wav", wavSHA256=wav,
                     injection={"injector": "X@1", "injectorID": "SIG-CLICK", "variant": "take-severe",
                                "severity": "severe", "classes": ["A"], "population": population,
                                "mechanism": mechanism, "outputPCMSHA256": pcm_digest(samples)}, **extra)
        return entry

    def injection_set(self, takes_path: Path, entries: list[dict]) -> Path:
        path = self.root / "set" / "injection-set.json"
        path.write_text(json.dumps({"schemaVersion": 1, "kind": m2.SET_KIND,
                                    "sourceManifest": {"sha256": m2.file_sha256(takes_path)},
                                    "entries": entries, "entriesSHA256": json_digest(entries)}), encoding="utf-8")
        return path

    def clips(self, takes_path: Path, set_path: Path | None = None) -> dict[str, dict]:
        quiet(m2.run_score, takes_path, set_path, self.root / "score", jobs=1)
        data = json.loads((self.root / "score" / "measurements.json").read_text(encoding="utf-8"))
        return {clip["clipID"]: clip for clip in data["clips"]}

    def test_clips_carry_the_introspection_summary_and_the_long_form_block(self) -> None:
        looped = self.take("s1--aiden", self.single, engineIntrospection=SUMMARY)
        joined = self.take("s2--aiden", self.joined, longForm=self.block)
        plain = self.take("s3--aiden", self.single[: self.single.size // 2])
        takes_path = self.manifest([looped, joined, plain])
        # A T1 click that keeps the length keeps the seams, and its jump is measured on its PCM; a T1 cut that
        # moves them has no block; a T3 knob take carries its own generation's summary.
        clicked = self.joined.copy()
        clicked[self.seam] = 0.9
        knob_summary = {**SUMMARY, "eosLikelyStepsWithoutStop": 7}
        entries = [
            self.entry(joined, "s2--click", clicked, population="P1", mechanism=injectors.MECHANISM),
            self.entry(joined, "s2--cut", self.joined[: -2_400], population="P1", mechanism=injectors.MECHANISM),
            self.entry(looped, "s1--knob", self.single, population="P3", mechanism="T3-controlled-generation",
                       engineIntrospection=knob_summary),
            self.entry(looped, "s1--pcm", self.single, population="S", mechanism=injectors.MECHANISM),
        ]
        clips = self.clips(takes_path, self.injection_set(takes_path, entries))
        self.assertEqual(clips["s1--aiden"]["introspection"], SUMMARY)
        self.assertNotIn("longForm", clips["s1--aiden"])
        self.assertEqual(clips["s2--aiden"]["longForm"], self.block)
        self.assertIsNotNone(clips["s2--aiden"]["observations"]["seamDiscontinuityMaxZ"])
        self.assertEqual(clips["s2--aiden"]["observations"]["seamCount"], 1)
        for clip_id in ("s3--aiden", "s1--aiden"):
            self.assertNotIn("introspection" if clip_id == "s3--aiden" else "longForm", clips[clip_id])
            self.assertIsNone(clips[clip_id]["observations"]["seamDiscontinuityMaxZ"])
        click = clips["s2--click"]
        self.assertEqual(click["longForm"]["maximumSegmentBoundaryJump"],
                         int(abs(round(0.9 * recordings.PCM16_FULL_SCALE)
                                 - round(self.joined[self.seam - 1] * recordings.PCM16_FULL_SCALE))))
        self.assertEqual(click["longForm"]["seamFrames"], self.block["seamFrames"])
        self.assertNotIn("introspection", click)
        self.assertNotIn("longForm", clips["s2--cut"])
        self.assertEqual(clips["s2--cut"]["observations"]["seamCount"], 0)
        self.assertEqual(clips["s1--knob"]["introspection"], knob_summary)
        self.assertNotIn("introspection", clips["s1--pcm"], "a T1 construction carries no generation summary")

    def test_a_recorded_block_must_describe_its_wav(self) -> None:
        wrong = self.take("s2--aiden", self.joined, longForm={**self.block,
                                                             "maximumSegmentBoundaryJump": self.jump + 1})
        with self.assertRaisesRegex(m2.CalibrationError, "the assembler recorded"):
            self.clips(self.manifest([wrong]))
        short = self.take("s2--aiden", self.joined, longForm={**self.block,
                                                             "outputFrameCount": self.joined.size + 1})
        with self.assertRaisesRegex(m2.CalibrationError, "does not describe its WAV"):
            self.clips(self.manifest([short]))
        broken = copy.deepcopy(SUMMARY)
        broken["codecFrameCount"] = None
        with self.assertRaisesRegex(m2.CalibrationError, "codecFrameCount"):
            self.clips(self.manifest([self.take("s1--aiden", self.single, engineIntrospection=broken)]))

    def test_the_boundary_jump_mirrors_the_assembler(self) -> None:
        self.assertEqual(m2.boundary_jump(self.joined, [self.seam]), self.jump)
        self.assertEqual(m2.boundary_jump(self.joined, []), 0)
        # 0.5 and -0.5 at 1/32767 store as 16384 and -16384: the step between them is the largest.
        steps = np.array([0.0, 0.5, -0.5, 0.25])
        self.assertEqual(m2.boundary_jump(steps, [1, 2, 3]), 32_768)


PYIN, CAMPPLUS = "pitch.pyin@1", "speaker.campplus-voxceleb@1"


def pitch_track(hertz: float) -> dict:
    """pYIN's raw output as its worker returns it (with the voicing probability the export drops)."""
    f0 = [None] * 5 + [hertz] * 40 + [None] * 5
    return {"hopSeconds": 0.01, "f0Hz": f0, "voiced": [value is not None for value in f0],
            "voicedProbability": [0.9 if value is not None else 0.1 for value in f0]}


class RawOutputExportTests(unittest.TestCase):
    """`raw-outputs` rebuilds each take's L1 key from its evidence and exports the fields the reducers read."""

    def setUp(self) -> None:
        from delivery_analysis_cache import CanonicalAudio, DeliveryAnalysisCache
        from lib.jsonio import sha256_json
        from lib.qc_pipeline.evidence import BUNDLE_SCHEMA
        from lib.qc_pipeline.layered_cache import l1_identity
        from lib.qc_pipeline.panel_jobs import identity_components, judge_scope, panel_identity, panel_request, profile

        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        repository = Path(__file__).resolve().parents[2]
        registry = json.loads((repository / "config/audio-qc-judges.json").read_text(encoding="utf-8"))
        takes = []
        for index, language in enumerate(("english", "french", "korean")):
            take_id = f"s{index}--aiden"
            takes.append({"takeID": take_id, "family": take_id, "scriptID": f"s{index}", "language": language,
                          "text": "one two three", "status": "generated", "wavPath": f"wav/{take_id}.wav",
                          "wavSHA256": sha(take_id)})
        self.manifest = self.root / "takes.json"
        self.manifest.write_text(json.dumps({"schemaVersion": 1, "kind": m2.TAKES_KIND, "runID": "run",
                                             "split": "calibration", "takes": takes}), encoding="utf-8")
        judge = registry["judges"][PYIN]
        components = identity_components(PYIN, registry, engine=judge["execution"]["engine"],
                                         threads=judge["execution"]["threads"], host={"machine": "fixture"})
        self.identity = panel_identity(PYIN, registry, components)
        spec, scope = profile(PYIN), judge_scope(judge)
        self.cache_root = self.root / "cache"
        cache = DeliveryAnalysisCache(self.cache_root)
        self.bundle = self.root / "bundle"
        entries = []
        for number, take in enumerate(takes, 1):
            canonical_digest = sha(f"canonical:{take['takeID']}")
            canonical = CanonicalAudio(take["wavSHA256"], canonical_digest, 1, 1.0, Path("unused"),
                                       "polyphase-kaiser5-v2")
            request = panel_request(spec, scope, {"language": take["language"]})
            if take["takeID"] != "s2--aiden":
                cache.store(l1_identity(canonical, self.identity, request), pitch_track(200.0 + number))
            evidence = {"schema": "vocello.audioqc.take-evidence/1",
                        "measurements": [{"judge": PYIN, "status": "complete", "reasons": [], "metrics": {},
                                          "outputIdentity": self.identity.output_identity}],
                        "take": {"takeID": take["takeID"], "audioSHA256": take["wavSHA256"],
                                 "canonicalPCMSHA256": canonical_digest, "language": take["language"]}}
            path = self.bundle / "evidence" / f"{number:04d}.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(evidence), encoding="utf-8")
            entries.append({"takeID": take["takeID"], "evidence": f"evidence/{number:04d}.json",
                            "evidenceSHA256": recordings.file_sha256(path)})
        body = {"schema": BUNDLE_SCHEMA, "runID": "panel", "manifestSHA256": "2" * 64, "takes": entries}
        (self.bundle / "bundle.json").write_text(json.dumps({**body, "bundleDigest": sha256_json(
            body, ascii=False, allow_nan=False)}), encoding="utf-8")

    def tearDown(self) -> None:
        self.directory.cleanup()

    def test_the_export_keeps_the_reduced_fields_and_binds_the_manifest_and_bundle(self) -> None:
        import audio_qc_detector_calibration as calibration

        output = self.root / "raw.json"
        export = quiet(m2.export_raw_outputs, self.manifest, self.bundle, output, judge_id=PYIN,
                       cache_root=self.cache_root)
        self.assertEqual(export["counts"]["byStatus"], {"complete": 2, "not-in-cache": 1})
        record = export["takes"]["s0--aiden"]
        self.assertEqual(sorted(record["output"]), ["f0Hz", "hopSeconds", "voiced"])
        self.assertEqual(record["output"]["f0Hz"][5], 201.0)
        self.assertEqual((record["outputIdentity"], export["judge"]["outputIdentities"]),
                         (self.identity.output_identity, [self.identity.output_identity]))
        self.assertEqual(export["takesManifest"]["sha256"], m2.file_sha256(self.manifest))
        loaded = calibration.load_raw_outputs(output)
        self.assertEqual((loaded["judge"], loaded["sourceSHA256"]), (PYIN, m2.file_sha256(self.manifest)))
        self.assertNotIn("one two three", output.read_text(encoding="utf-8"))
        # An edited export is refused by the driver, and a judge whose raw output no detector reduces by the export.
        data = json.loads(output.read_text(encoding="utf-8"))
        data["takes"]["s0--aiden"]["output"]["f0Hz"][5] = 400.0
        output.write_text(json.dumps(data), encoding="utf-8")
        with self.assertRaisesRegex(calibration.CalibrationError, "takesSHA256"):
            calibration.load_raw_outputs(output)
        with self.assertRaisesRegex(m2.CalibrationError, "raw output a detector reduces"):
            m2.export_raw_outputs(self.manifest, self.bundle, output, judge_id="asr.whisper-large-v3@1",
                                  cache_root=self.cache_root)


if __name__ == "__main__":
    unittest.main()
