#!/usr/bin/env python3
"""Oracle ladders for pYIN, HNR and the quality composite (AQ-08; audit sections 4.4, 4.6 and 5.8).

No judge runs here: the pYIN and quality ladders are scored from hand-built
bundles and L1 cache entries, and the HNR ladder runs the pure-DSP Stage 1
analyzers in-process.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
from pathlib import Path
import sys
import tempfile
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import audio_qc_oracle_ladders as cli  # noqa: E402
import audio_qc_orchestrator as orchestrator  # noqa: E402
from audio_qc_judges import load_registry  # noqa: E402
from delivery_analysis_cache import CanonicalAudio, DeliveryAnalysisCache  # noqa: E402
from lib.qc_pipeline.evidence import PRIVATE_SCHEMA, TAKE_EVIDENCE_SCHEMA, write_private_bundle  # noqa: E402
from lib.qc_pipeline.layered_cache import l1_identity  # noqa: E402
from lib.qc_pipeline.panel_jobs import panel_identity  # noqa: E402
from lib.qc_pipeline.verdicts import compose_take, stage0_detector  # noqa: E402
from lib.qc_qualification import ladders as L  # noqa: E402
from lib.qc_qualification.recordings import write_pcm16_wav  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
# Golden digests over every clip's identity, PCM16 digest and truth (ladder version 1).
GOLDENS = {
    "pyin": ("9eb6974bd08878356827d27661f01068d85e8144bfeafc94dd2fbcff45a6769b", 48),
    "hnr": ("a2397848bf6c1c9f64e606b7e4f3f5e0aa6ab2bd3fad98c69b475ad0e5f63f0b", 39),
    "quality": ("29041f69767b949fb1e2916bd3c771fdd63a612c618fe215068d9baba1372e66", 92),
}


def _sha(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def fake_record(take_id: str, audio_sha: str, canonical_sha: str, measurements: list[dict],
                duration: float = 1.5) -> dict:
    composed = compose_take("language-bench", [stage0_detector(None)])
    return {
        "schema": TAKE_EVIDENCE_SCHEMA,
        "take": {"takeID": take_id, "audioSHA256": audio_sha, "canonicalPCMSHA256": canonical_sha,
                 "canonicalSampleRateHz": 16000, "durationSeconds": duration, "textSHA256": None,
                 "language": "english", "role": "oracle-ladder", "expectedOutcome": "pass"},
        "registries": {"judges": "d" * 64, "detectors": None, "policy": "e" * 64},
        "stage0": None,
        "measurements": measurements,
        "verdicts": composed["verdicts"],
        "takeVerdict": {key: composed[key] for key in ("lane", "status", "composition", "decidedBy", "reasons")},
        "legacyVerdicts": {},
    }


def fake_measurement(judge: str, identity: str, metrics: dict) -> dict:
    return {"judge": judge, "outputIdentity": identity, "status": "complete", "metrics": metrics,
            "metricsSHA256": _sha(json.dumps(metrics, sort_keys=True)), "transcriptSHA256": None,
            "wallSeconds": None, "reasons": [], "cache": {"l1": "miss", "l2": "miss"}}


def write_bundle(root: Path, records: list[dict]) -> Path:
    bundle = root / "bundle"
    privates = [{"schema": PRIVATE_SCHEMA, "takeID": record["take"]["takeID"],
                 "manifestTakeID": record["take"]["takeID"], "audioPath": "unused", "referenceText": None,
                 "transcripts": {}} for record in records]
    write_private_bundle(bundle, header={"runID": "oracle-ladder-test", "lane": "language-bench"},
                         takes=zip(records, privates), repository=REPO)
    return bundle


class GoldenTests(unittest.TestCase):
    def test_every_ladder_is_deterministic_and_pinned_by_digest(self) -> None:
        for ladder, (golden, count) in GOLDENS.items():
            with self.subTest(ladder=ladder):
                clips = L.ladder_clips(ladder)
                self.assertEqual(len(clips), count)
                self.assertEqual(len({clip.clip_id for clip in clips}), count)
                self.assertEqual(L.clips_digest(clips), golden)
                self.assertEqual(L.clips_digest(L.ladder_clips(ladder)), golden)

    def test_clip_ids_are_privacy_safe_tokens(self) -> None:
        from lib.qc_pipeline.evidence import is_token

        for ladder in L.LADDERS:
            for clip in L.ladder_clips(ladder):
                self.assertTrue(is_token(clip.clip_id), clip.clip_id)


class TruthConstructionTests(unittest.TestCase):
    def test_pitch_truth_sits_on_the_trackers_frame_grid(self) -> None:
        clips = {clip.clip_id: clip for clip in L.pyin_clips()}
        steady = clips["pyin-steady-0160hz"]
        truth = steady.truth
        self.assertEqual(truth["frames"], 1 + steady.samples.size // L.PYIN_HOP)
        self.assertTrue(all(truth["voiced"]))
        self.assertEqual({value for value in truth["f0Hz"]}, {160.0})
        # The edges are never scored: the analysis window would reach past the clip.
        guard_frames = math.ceil(L.GUARD_SAMPLES / L.PYIN_HOP)
        self.assertFalse(any(truth["scored"][:guard_frames]))
        self.assertTrue(truth["scored"][guard_frames])

    def test_frames_near_voicing_changes_and_jumps_are_not_scored(self) -> None:
        clips = {clip.clip_id: clip for clip in L.pyin_clips()}
        for clip_id in ("pyin-vuv-fricative-0150hz", "pyin-octave-up-0150hz"):
            truth = clips[clip_id].truth
            voiced = truth["voiced"]
            f0 = truth["f0Hz"]
            changes = [index for index in range(1, truth["frames"])
                       if voiced[index] != voiced[index - 1] or f0[index] != f0[index - 1]]
            self.assertTrue(changes, clip_id)
            for index in range(truth["frames"]):
                if truth["scored"][index]:
                    distance = min(abs(index - change) * L.PYIN_HOP for change in changes)
                    self.assertGreaterEqual(distance + L.PYIN_HOP, L.GUARD_SAMPLES, (clip_id, index))
        vuv = clips["pyin-vuv-fricative-0150hz"].truth
        scored = [voiced for voiced, keep in zip(vuv["voiced"], vuv["scored"]) if keep]
        self.assertGreater(scored.count(True), 50)
        self.assertGreater(scored.count(False), 50)
        octave = clips["pyin-octave-up-0150hz"].truth
        self.assertEqual({value for value in octave["f0Hz"]}, {150.0, 300.0})

    def test_hnr_rungs_carry_the_exact_constructed_ratio(self) -> None:
        clips = {clip.clip_id: clip for clip in L.hnr_clips()}
        periodic = L._hnr_periodic("glottal", 150.0)
        for snr in L.HNR_STEPS_DB:
            clip = clips[f"hnr-glottal-0150hz-snr{snr:02.0f}db"]
            noise = clip.samples - periodic
            measured = 10.0 * math.log10(float(np.sum(periodic ** 2)) / float(np.sum(noise ** 2)))
            self.assertAlmostEqual(measured, snr, places=9)
            self.assertEqual(clip.truth["hnrDB"], snr)
        self.assertTrue(np.array_equal(clips["hnr-glottal-0150hz-noiseless"].samples, periodic))
        self.assertEqual(sum(1 for clip in clips.values() if clip.condition == "noiseless-sine"), 3)

    def test_every_quality_family_moves_monotonically_away_from_the_clean_source(self) -> None:
        clips = {clip.clip_id: clip for clip in L.quality_clips()}
        for stratum, index in L.QUALITY_SOURCES:
            source = f"proc-{stratum}-{index:04d}"
            clean = clips[f"q-{source}-clean"].samples
            for family in L.QUALITY_FAMILIES:
                distances = [float(np.sum((clips[f"q-{source}-{family}-{rank}"].samples - clean) ** 2))
                             for rank in range(1, 6)]
                self.assertEqual(distances, sorted(distances), (source, family))
                self.assertGreater(distances[0], 0.0)
            for family in L.QUALITY_SHAMS:
                sham = clips[f"q-{source}-{family}-sham"].samples
                mild = clips[f"q-{source}-{family}-1"].samples
                self.assertLess(float(np.sum((sham - clean) ** 2)), float(np.sum((mild - clean) ** 2)))

    def test_degradations_hit_their_parameters(self) -> None:
        fixture = L.procedural_quality_sources()[0]
        clean = np.asarray(fixture.samples)
        noisy = L.degrade(fixture, "noise", 10.0)
        noise = noisy - clean
        self.assertAlmostEqual(20.0 * math.log10(L.speech_rms(fixture) / L._rms(noise)), 10.0, places=9)
        clipped = L.degrade(fixture, "clip", 0.03)
        level = float(np.max(np.abs(clipped)))
        self.assertAlmostEqual(float(np.mean(np.abs(clean) > level)), 0.03, delta=0.001)
        banded = L.degrade(fixture, "band", 2_500.0)
        spectrum = np.abs(np.fft.rfft(banded)) ** 2
        frequencies = np.fft.rfftfreq(banded.size, 1.0 / fixture.sample_rate)
        self.assertLess(float(np.sum(spectrum[frequencies > 3_500.0])) / float(np.sum(spectrum)), 1e-6)
        errors = [L._rms(L.mu_law(clean, bits) - clean) for bits in (8, 6, 4)]
        self.assertEqual(errors, sorted(errors))


class PitchScoringTests(unittest.TestCase):
    def truth(self) -> dict:
        voiced = [False] * 5 + [True] * 10 + [False] * 5
        return {"frames": 20, "f0Hz": [200.0 if flag else 0.0 for flag in voiced], "voiced": voiced,
                "scored": [True] * 20}

    def test_a_perfect_estimate_scores_zero_error(self) -> None:
        truth = self.truth()
        counts = L.score_pitch(truth, {"f0Hz": [value or None for value in truth["f0Hz"]], "voiced": truth["voiced"]})
        metrics = counts.metrics()
        self.assertEqual((metrics["gpe"], metrics["vde"], metrics["fpeRmsCents"]), (0.0, 0.0, 0.0))
        self.assertEqual((metrics["voicedRecall"], metrics["voicingFalseAlarmRate"]), (1.0, 0.0))

    def test_gross_octave_fine_and_voicing_errors_are_counted(self) -> None:
        truth = self.truth()
        cents10 = 200.0 * 2.0 ** (10.0 / 1200.0)
        f0 = [None] * 5 + [400.0, 400.0] + [cents10] * 8 + [None] * 4 + [150.0]
        voiced = [False] * 5 + [True] * 10 + [False] * 4 + [True]
        metrics = L.score_pitch(truth, {"f0Hz": f0, "voiced": voiced}).metrics()
        self.assertEqual(metrics["jointlyVoicedFrames"], 10)
        self.assertEqual(metrics["gpe"], 0.2)
        self.assertEqual(metrics["octaveErrorRate"], 0.2)
        self.assertAlmostEqual(metrics["fpeRmsCents"], 10.0, places=3)
        self.assertEqual(metrics["vde"], 0.05)
        self.assertEqual(metrics["voicingFalseAlarmRate"], 0.1)

    def test_unscored_frames_and_a_wrong_frame_count(self) -> None:
        truth = self.truth()
        truth["scored"] = [False] * 10 + [True] * 10
        wrong = [None] * 20
        metrics = L.score_pitch(truth, {"f0Hz": wrong, "voiced": [False] * 20}).metrics()
        self.assertEqual(metrics["scoredFrames"], 10)
        self.assertEqual(metrics["vde"], 0.5)
        self.assertIsNone(metrics["gpe"])
        with self.assertRaises(L.LadderError):
            L.score_pitch(truth, {"f0Hz": wrong[:-1], "voiced": [False] * 19})

    def test_group_limits_decide_the_verdict(self) -> None:
        truth = self.truth()
        truths = {"a": truth, "b": truth}
        perfect = {"f0Hz": [value or None for value in truth["f0Hz"]], "voiced": truth["voiced"]}
        result = L.evaluate_pitch(truths, {"a": "core-clean", "b": "noise-stress"}, {"a": perfect, "b": None})
        self.assertEqual(result["verdict"], "incomplete")
        result = L.evaluate_pitch(truths, {"a": "core-clean", "b": "noise-stress"}, {"a": perfect, "b": perfect})
        # Every pYIN limit is provisional, and groups with no clip cannot be evaluated.
        self.assertEqual(result["verdict"], "incomplete")
        groups = {group: group for group in L.PYIN_LIMITS}
        many = {group: truth for group in L.PYIN_LIMITS}
        result = L.evaluate_pitch(many, groups, {group: perfect for group in L.PYIN_LIMITS})
        self.assertEqual(result["verdict"], "pass-provisional")
        octave = copy.deepcopy(perfect)
        octave["f0Hz"][6] = 400.0
        result = L.evaluate_pitch(many, groups, {**{group: perfect for group in L.PYIN_LIMITS}, "core-clean": octave})
        self.assertEqual(result["verdict"], "fail")
        failed = [item["id"] for item in result["criteria"] if item["status"] == "fail"]
        self.assertEqual(failed, ["core-clean.gpe"])


class HnrScoringTests(unittest.TestCase):
    def setUp(self) -> None:
        self.truths = {clip.clip_id: clip.truth for clip in L.hnr_clips()}

    def perfect(self) -> dict:
        return {clip_id: 60.0 if truth["noiseless"] else float(truth["hnrDB"]) for clip_id, truth in self.truths.items()}

    def test_a_truthful_tracker_passes_provisionally_and_fully_with_an_oracle(self) -> None:
        readings = self.perfect()
        result = L.evaluate_hnr_tracker(self.truths, readings, None)
        self.assertEqual(result["verdict"], "pass-provisional")
        oracle = {clip_id: value + 0.5 for clip_id, value in readings.items() if not self.truths[clip_id]["noiseless"]}
        result = L.evaluate_hnr_tracker(self.truths, readings, oracle)
        self.assertEqual(result["verdict"], "pass")
        oracle = {clip_id: value + 1.5 for clip_id, value in oracle.items()}
        self.assertEqual(L.evaluate_hnr_tracker(self.truths, readings, oracle)["verdict"], "fail")

    def test_the_sine_floor_monotonicity_and_tolerance_each_fail(self) -> None:
        readings = self.perfect()
        readings["hnr-sine-0150hz-noiseless"] = 36.9
        result = L.evaluate_hnr_tracker(self.truths, readings, None)
        self.assertEqual([item["id"] for item in result["criteria"] if item["status"] == "fail"],
                         ["noiseless-sine-floor"])
        readings = self.perfect()
        readings["hnr-glottal-0220hz-snr40db"] = 61.0
        result = L.evaluate_hnr_tracker(self.truths, readings, None)
        self.assertEqual([item["id"] for item in result["criteria"] if item["status"] == "fail"],
                         ["monotone-in-truth"])
        readings = self.perfect()
        readings["hnr-glottal-0100hz-snr25db"] = 26.2
        readings["hnr-glottal-0100hz-snr40db"] = 31.0  # above the 30 dB ceiling only monotonicity binds
        result = L.evaluate_hnr_tracker(self.truths, readings, None)
        self.assertEqual([item["id"] for item in result["criteria"] if item["status"] == "fail"],
                         ["analytic-truth-1db"])
        readings = self.perfect()
        readings["hnr-glottal-0100hz-snr10db"] = None
        self.assertEqual(L.evaluate_hnr_tracker(self.truths, readings, None)["verdict"], "incomplete")


class QualityScoringTests(unittest.TestCase):
    def setUp(self) -> None:
        self.truths = {clip.clip_id: clip.truth for clip in L.quality_clips()}
        self.durations = {clip.clip_id: clip.duration_seconds for clip in L.quality_clips()}

    def columns(self) -> dict:
        pq, ovrl = {}, {}
        for clip_id, truth in self.truths.items():
            offset = sum(ord(character) for character in truth["source"]) % 7 / 10.0
            rank = truth["severityRank"]
            pq[clip_id] = 7.0 + offset - 0.4 * rank + (0.01 if truth["sham"] else 0.0)
            ovrl[clip_id] = 3.4 - 0.25 * rank - 0.05 * offset
        return {"PQ": pq, "OVRL": ovrl}

    def test_spearman_and_duration_standardization(self) -> None:
        self.assertAlmostEqual(L.spearman([0, 1, 2, 3], [4.0, 3.0, 3.0, 1.0]), -0.9486832980505138)
        self.assertIsNone(L.spearman([0, 1, 2], [1.0, 1.0, 1.0]))
        durations = {"a": 1.0, "b": 2.0, "c": 3.0, "d": 4.0}
        values = {key: 10.0 * durations[key] + (1.0 if key in "ac" else -1.0) for key in durations}
        z = L.standardize(values, durations)
        self.assertAlmostEqual(sum(z.values()), 0.0)
        # Once duration is regressed out only the alternating part remains.
        self.assertGreater(z["a"], 0.0)
        self.assertLess(z["b"], 0.0)
        self.assertGreater(z["c"], 0.0)

    def test_a_monotone_composite_passes_and_a_reversal_fails(self) -> None:
        columns = self.columns()
        result = L.evaluate_quality(self.truths, columns, self.durations)
        self.assertEqual(result["verdict"], "pass-provisional", result["criteria"])
        self.assertEqual(len(result["ladders"]), 16)
        self.assertTrue(all(value["passing"] == 4 for value in result["families"].values()))
        broken = copy.deepcopy(columns)
        broken["PQ"]["q-proc-modal-0001-band-4"] += 3.0
        broken["OVRL"]["q-proc-modal-0001-band-4"] += 1.0
        result = L.evaluate_quality(self.truths, broken, self.durations)
        self.assertEqual(result["verdict"], "fail")
        self.assertEqual(result["families"]["band"]["passing"], 3)
        sham = copy.deepcopy(columns)
        sham["PQ"]["q-proc-breathy-0003-noise-sham"] -= 2.0
        result = L.evaluate_quality(self.truths, sham, self.durations)
        self.assertEqual([item["id"] for item in result["criteria"] if item["status"] == "fail"], ["sham-tolerance"])

    def test_ties_within_tolerance_pass_and_missing_clips_are_incomplete(self) -> None:
        columns = self.columns()
        for column in columns.values():
            column["q-proc-modal-0000-clip-1"] = column["q-proc-modal-0000-clean"]
        self.assertEqual(L.evaluate_quality(self.truths, columns, self.durations)["verdict"], "pass-provisional")
        del columns["OVRL"]["q-proc-modal-0000-quant-2"]
        result = L.evaluate_quality(self.truths, columns, self.durations)
        self.assertEqual(result["verdict"], "incomplete")
        self.assertEqual(result["missingClips"], ["q-proc-modal-0000-quant-2"])

    def test_the_wer_term_enters_only_ladders_with_an_error_rate_on_every_rung(self) -> None:
        columns = self.columns()
        source = "proc-modal-0000"
        # PQ and OVRL blind to this source's degradations: its ladders are flat, so they fail...
        for column in columns.values():
            for clip_id, truth in self.truths.items():
                if truth["source"] == source:
                    column[clip_id] = column[f"q-{source}-clean"]
        result = L.evaluate_quality(self.truths, columns, self.durations)
        self.assertEqual(result["verdict"], "fail")
        self.assertEqual(result["werSources"], [])
        # ...until a recognizer's error rate, rising with severity, enters them as -z(WER).
        wer = {clip_id: 0.05 * truth["severityRank"] for clip_id, truth in self.truths.items()
               if truth["source"] == source}
        result = L.evaluate_quality(self.truths, columns, self.durations, wer=wer)
        self.assertEqual(result["werSources"], [source])
        self.assertEqual(result["verdict"], "pass-provisional", result["criteria"])
        noise = next(entry for entry in result["ladders"] if entry["source"] == source and entry["family"] == "noise")
        self.assertTrue(noise["werTerm"])
        self.assertEqual(noise["componentSpearman"]["errorRate"], 1.0)
        # A source missing one rung's error rate keeps the composite without the term.
        del wer[f"q-{source}-band-3"]
        self.assertEqual(L.evaluate_quality(self.truths, columns, self.durations, wer=wer)["werSources"], [])


class CommandTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.registry = load_registry()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_build_writes_truth_wavs_and_a_manifest_the_orchestrator_accepts(self) -> None:
        summary = cli.build("pyin", self.root, registry=self.registry)
        self.assertEqual((summary["clips"], summary["clipsSHA256"]), (48, GOLDENS["pyin"][0]))
        truth = cli.read_truth(self.root / "pyin", "pyin")
        manifest = orchestrator.validate_manifest(json.loads((self.root / "pyin/manifest.json").read_text()))
        self.assertEqual(len(manifest["takes"]), 48)
        for take, entry in zip(manifest["takes"], truth["clips"]):
            self.assertEqual(take["id"], entry["clipID"])
            self.assertIsNone(take["referenceText"])
            self.assertEqual(cli.sha256_file(Path(take["audioPath"])), take["audioSHA256"])
        # Rebuilding the same ladder reuses it; another build in its place is refused.
        self.assertTrue(cli.build("pyin", self.root, registry=self.registry)["reused"])
        (self.root / "pyin" / cli.TRUTH_FILE).write_text(json.dumps({**truth, "clipsSHA256": "0" * 64}))
        with self.assertRaises(cli.LadderCommandError):
            cli.build("pyin", self.root, registry=self.registry)

    def test_build_refuses_tracked_paths_and_a_foreign_pitch_grid(self) -> None:
        with self.assertRaises(cli.LadderCommandError):
            cli.build("hnr", REPO / "docs")
        registry = copy.deepcopy(self.registry)
        registry["judges"][L.PYIN_JUDGE]["configuration"]["hopLength"] = 256
        with self.assertRaises(cli.LadderCommandError):
            cli.build("pyin", self.root, registry=registry)

    def test_pyin_is_scored_from_the_bundle_and_the_runs_l1_entries(self) -> None:
        cli.build("pyin", self.root, registry=self.registry)
        truth = cli.read_truth(self.root / "pyin", "pyin")
        identity = panel_identity(L.PYIN_JUDGE, self.registry, {"threads": 1, "test": "oracle-ladder"})
        cache_root = self.root / "cache"
        cache = DeliveryAnalysisCache(cache_root)
        records = []
        for entry in truth["clips"]:
            canonical_sha = _sha("canonical:" + entry["clipID"])
            canonical = CanonicalAudio(entry["wavSHA256"], canonical_sha, 0, 0.0, Path("."), "")
            clip_truth = entry["truth"]
            # A tracker 5 cents sharp everywhere, with the truth's voicing.
            f0 = [value * 2.0 ** (5.0 / 1200.0) if voiced else None
                  for value, voiced in zip(clip_truth["f0Hz"], clip_truth["voiced"])]
            cache.store(l1_identity(canonical, identity, {}),
                        {"hopSeconds": 0.01, "f0Hz": f0, "voiced": clip_truth["voiced"],
                         "voicedProbability": [0.9] * clip_truth["frames"], "sampleRateHz": 16000,
                         "decodedSampleCount": entry["frames"]})
            records.append(fake_record(entry["clipID"], entry["wavSHA256"], canonical_sha,
                                       [fake_measurement(L.PYIN_JUDGE, identity.output_identity,
                                                         {"voicedFraction": 1.0})]))
        bundle = write_bundle(self.root, records)
        evaluation = cli.evaluate_pyin(self.root / "pyin", bundle, cache_root, registry=self.registry)
        result = evaluation["trackers"][L.PYIN_JUDGE]
        self.assertEqual(evaluation["verdict"], "pass-provisional")
        self.assertEqual(result["missingClips"], [])
        self.assertAlmostEqual(result["groups"]["core-clean"]["fpeRmsCents"], 5.0, places=2)
        self.assertEqual(evaluation["judges"], {L.PYIN_JUDGE: [identity.output_identity]})
        self.assertEqual(cli.privacy_errors(evaluation), [])
        # Without its L1 entries the ladder is incomplete, never a pass.
        evaluation = cli.evaluate_pyin(self.root / "pyin", bundle, self.root / "empty-cache", registry=self.registry)
        self.assertEqual(evaluation["verdict"], "incomplete")
        self.assertEqual(evaluation["unavailable"]["l1"], 48)
        # A tampered entry fails its digest and is counted, not scored.
        entry = sorted((cache_root / "layers").rglob("*.json"))[0]
        stored = json.loads(entry.read_text())
        stored["payload"]["hopSeconds"] = 0.02
        entry.write_text(json.dumps(stored))
        evaluation = cli.evaluate_pyin(self.root / "pyin", bundle, cache_root, registry=self.registry)
        self.assertEqual((evaluation["verdict"], evaluation["unavailable"]["l1Invalid"]), ("incomplete", 1))

    def test_quality_is_scored_from_the_bundles_audiobox_and_dnsmos_columns(self) -> None:
        cli.build("quality", self.root)
        truth = cli.read_truth(self.root / "quality", "quality")
        records = []
        for entry in truth["clips"]:
            rank = entry["truth"]["severityRank"]
            measurements = [
                fake_measurement(L.AUDIOBOX_JUDGE, "a" * 64, {"PQ": 7.5 - 0.5 * rank, "CE": 6.0, "CU": 6.0,
                                                               "PC": 2.0}),
                fake_measurement(L.DNSMOS_JUDGE, "b" * 64, {"OVRL": 3.3 - 0.3 * rank, "SIG": 3.5, "BAK": 4.0}),
            ]
            records.append(fake_record(entry["clipID"], entry["wavSHA256"], _sha("c" + entry["clipID"]),
                                       measurements, duration=entry["durationSeconds"]))
        bundle = write_bundle(self.root, records)
        evaluation = cli.evaluate_quality(self.root / "quality", bundle)
        self.assertEqual(evaluation["verdict"], "pass-provisional")
        self.assertEqual(sorted(evaluation["judges"]), [L.AUDIOBOX_JUDGE, L.DNSMOS_JUDGE])
        path = cli.write_evaluation(self.root / "quality", evaluation)
        self.assertTrue(path.is_file())

    def test_recordings_replace_the_procedural_sources_and_their_text_stays_private(self) -> None:
        rng = np.random.default_rng(3)
        takes = []
        for index in range(2):
            wav = self.root / "sources" / f"take-{index}.wav"
            samples = 0.1 * np.sin(2 * np.pi * 180.0 * np.arange(48_000) / 24_000) + 0.01 * rng.normal(size=48_000)
            digest = write_pcm16_wav(wav, samples)
            text = f"a private sentence number {index}"
            takes.append(orchestrator._take(take_id=f"take-{index}", generation_id=f"take-{index}", audio=str(wav),
                                            audio_sha256=digest, language="french", reference_text=text,
                                            script_sha256=orchestrator.text_sha256(text)))
        source = self.root / "sources.json"
        source.write_text(json.dumps({"schema": orchestrator.MANIFEST_SCHEMA, "runID": "sources",
                                      "lane": "language-bench", "generationProcessExited": True, "takes": takes,
                                      "pairs": []}))
        summary = cli.build("quality", self.root, quality_sources=source)
        self.assertEqual(summary["clips"], 2 * 23)
        truth_text = (self.root / "quality" / cli.TRUTH_FILE).read_text()
        self.assertNotIn("private sentence", truth_text)
        manifest = json.loads((self.root / "quality" / cli.MANIFEST_FILE).read_text())
        self.assertTrue(all(take["referenceText"].startswith("a private sentence") for take in manifest["takes"]))
        self.assertEqual({take["language"] for take in manifest["takes"]}, {"french"})

    def test_hnr_runs_in_process_and_reproduces_the_proxy_defect(self) -> None:
        cli.build("hnr", self.root)
        truth = cli.read_truth(self.root / "hnr", "hnr")
        readings = cli.hnr_readings(self.root / "hnr", truth)
        evaluation = cli.evaluate_hnr(self.root / "hnr", readings=readings)
        legacy = evaluation["trackers"]["prosody@3"]
        candidate = evaluation["trackers"][L.HNR_GATED_TRACKER]
        # AQ-F16: the Hann-biased proxy reads 0.51, 6.99 and 13.29 dB on noiseless 80/150/300 Hz sines.
        self.assertEqual([round(value, 1) for value in legacy["noiselessSines"].values()], [0.5, 7.0, 13.3])
        self.assertEqual(legacy["verdict"], "fail")
        self.assertEqual(candidate["verdict"], "pass-provisional")
        self.assertEqual(evaluation["verdict"], "pass-provisional")
        self.assertLess(candidate["maximumAbsErrorDB"], 1.0)
        # An oracle file (an isolated Parselmouth run) turns the audit criterion on.
        values = {entry["clipID"]: readings[L.HNR_GATED_TRACKER][entry["clipID"]] + 0.3 for entry in truth["clips"]
                  if not entry["truth"]["noiseless"]}
        oracle = self.root / "oracle.json"
        oracle.write_text(json.dumps({"schema": L.HNR_ORACLE_SCHEMA, "tool": "parselmouth-0.4.7", "values": values}))
        with_oracle = cli.evaluate_hnr(self.root / "hnr", oracle_path=oracle, readings=readings)
        self.assertEqual(with_oracle["trackers"][L.HNR_GATED_TRACKER]["verdict"], "pass")
        self.assertEqual(with_oracle["trackers"]["prosody@3"]["verdict"], "fail")
        oracle.write_text(json.dumps({"schema": L.HNR_ORACLE_SCHEMA, "tool": "parselmouth", "values": {"x": 1.0}}))
        with self.assertRaises(cli.LadderCommandError):
            cli.evaluate_hnr(self.root / "hnr", oracle_path=oracle, readings=readings)
        self.assertEqual(with_oracle["oracle"], {"tool": "parselmouth-0.4.7", "clips": 32})
        self.assertEqual(cli.privacy_errors(with_oracle), [])

    def test_report_is_privacy_safe_and_names_the_aq08_ladder_gate(self) -> None:
        def evaluation(ladder: str, verdict: str) -> dict:
            return {"schema": L.EVALUATION_SCHEMA, "ladder": ladder, "ladderVersion": 1, "clipsSHA256": "0" * 64,
                    "trackers": {}, "verdict": verdict}

        record = cli.report([evaluation("pyin", "pass-provisional"), evaluation("hnr", "pass"),
                             evaluation("quality", "pass-provisional")])
        self.assertTrue(record["aq08LaddersPass"])
        self.assertEqual(cli.privacy_errors(record), [])
        self.assertFalse(cli.report([evaluation("pyin", "pass"), evaluation("hnr", "fail")])["aq08LaddersPass"])
        with self.assertRaises(cli.LadderCommandError):
            cli.report([evaluation("hnr", "pass"), evaluation("hnr", "pass")])
        unsafe = evaluation("quality", "pass")
        unsafe["trackers"] = {"note": "a sentence with spaces"}
        with self.assertRaises(cli.LadderCommandError):
            cli.report([unsafe])

    def test_the_cli_exit_status_follows_the_verdict(self) -> None:
        self.assertEqual(cli.main(["build", "--ladder", "hnr", "--root", str(self.root)]), 0)
        self.assertEqual(cli.main(["evaluate", "--ladder", "hnr", "--root", str(self.root)]), 0)
        output = self.root / "report.json"
        self.assertEqual(cli.main(["report", "--evaluation", str(self.root / "hnr" / cli.EVALUATION_FILE),
                                   "--output", str(output)]), 0)
        self.assertFalse(json.loads(output.read_text())["aq08LaddersPass"])
        self.assertEqual(cli.main(["report", "--evaluation", str(self.root / "hnr" / cli.EVALUATION_FILE),
                                   "--output", str(output)]), 1)
        self.assertEqual(cli.main(["evaluate", "--ladder", "pyin", "--root", str(self.root)]), 1)


if __name__ == "__main__":
    unittest.main()
