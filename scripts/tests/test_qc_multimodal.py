"""Unit tests for the offline report-only multimodal audio QC complement (RF-72)."""

from __future__ import annotations

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

from qc import detectors, multimodal, multimodal_audio, store  # noqa: E402
from qc.store import Layout  # noqa: E402


def _make_tone(seconds: float, freq: float = 220.0, rate: int = 24000, amp: float = 0.25) -> np.ndarray:
    t = np.arange(int(round(seconds * rate)), dtype=np.float64) / float(rate)
    return amp * np.sin(2.0 * np.pi * freq * t)


def _write_wav(path: Path, samples: np.ndarray, *, rate: int = 24000, channels: int = 1) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    pcm = np.clip(np.rint(samples * 32767.0), -32768, 32767).astype("<i2")
    if channels == 2:
        pcm = np.repeat(pcm[:, None], 2, axis=1).reshape(-1)
    with wave.open(str(path), "wb") as writer:
        writer.setnchannels(channels)
        writer.setsampwidth(2)
        writer.setframerate(rate)
        writer.writeframes(pcm.tobytes())
    return path


class ScoringIdentityIsolationTests(unittest.TestCase):
    def test_multimodal_modules_are_outside_qc_scoring_sources(self) -> None:
        self.assertNotIn("qc/multimodal.py", detectors.SCORING_SOURCES)
        self.assertNotIn("qc/multimodal_audio.py", detectors.SCORING_SOURCES)
        identity = detectors.scoring_identity(Layout(ROOT))
        self.assertNotIn("config/qc/multimodal-rubric-v1.json", identity["files"])
        self.assertNotIn("scripts/qc/multimodal.py", identity["files"])
        self.assertNotIn("scripts/qc/multimodal_audio.py", identity["files"])

    def test_rubric_contract_is_valid_and_never_gating(self) -> None:
        rubric, digest = multimodal.load_rubric(Layout(ROOT))
        self.assertEqual(rubric["schema"], multimodal.RUBRIC_SCHEMA)
        self.assertTrue(rubric["neverGates"])
        self.assertEqual(rubric["status"], "report-only-advisory")
        self.assertEqual(len(digest), 64)
        protocol = store.read_json(ROOT / "config/qc/protocol.json")
        protocol_classes = [item["id"] for item in protocol["classes"]]
        self.assertEqual(rubric["defectClasses"], protocol_classes)


class MultimodalAudioTests(unittest.TestCase):
    def test_normalize_stereo_24k_to_mono_16k_and_stitch_timeline(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            wav_a = _write_wav(root / "a.wav", _make_tone(1.2, 220.0, rate=24000), rate=24000, channels=2)
            wav_b = _write_wav(root / "b.wav", _make_tone(0.8, 330.0, rate=16000), rate=16000, channels=1)
            sa = multimodal_audio.load_normalized_16k(wav_a)
            sb = multimodal_audio.load_normalized_16k(wav_b)
            self.assertAlmostEqual(sa.size / 16000.0, 1.2, delta=0.01)
            self.assertAlmostEqual(sb.size / 16000.0, 0.8, delta=0.01)

            marker = multimodal_audio.make_marker_tone(rate=16000)
            stitched, timeline = multimodal_audio.stitch_segments([sa, sb], rate=16000, marker=marker)
            out = root / "stitched.wav"
            meta = multimodal_audio.write_wav_pcm16(out, stitched, rate=16000)
            self.assertEqual(meta["sampleRate"], 16000)
            self.assertEqual(meta["channels"], 1)
            self.assertEqual(len(timeline), 2)
            self.assertEqual(timeline[0]["startSeconds"], 0.0)
            self.assertAlmostEqual(timeline[0]["endSeconds"], 1.2, delta=0.01)
            self.assertAlmostEqual(timeline[1]["startSeconds"], 1.2 + marker.size / 16000.0, delta=0.01)

    def test_crop_and_longform_slices_and_transforms(self) -> None:
        rate = 16000
        long_audio = _make_tone(22.0, 200.0, rate=rate)
        crop, start_s, end_s = multimodal_audio.crop_window(long_audio, rate, center_s=0.4, window_s=2.5)
        self.assertEqual(start_s, 0.0)
        self.assertAlmostEqual(end_s, 2.5, delta=0.01)
        self.assertAlmostEqual(crop.size / rate, 2.5, delta=0.01)

        slices = multimodal_audio.build_longform_slices(long_audio, rate=rate)
        self.assertEqual(len(slices), 3)
        for seg in slices:
            self.assertAlmostEqual(seg.size / rate, 6.0, delta=0.01)

        shifted = multimodal_audio.apply_harmless_transform(crop, rate, "lead_silence_200ms")
        self.assertAlmostEqual((shifted.size - crop.size) / rate, 0.2, delta=0.01)
        warped = multimodal_audio.apply_clear_perturbation(crop, rate, "speed_1_4x", seed=1)
        self.assertLess(warped.size, crop.size)


class PrivacyAndBlindingTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.layout = Layout(self.root)
        (self.layout.config).mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / "config/qc/multimodal-rubric-v1.json", self.layout.config / "multimodal-rubric-v1.json")
        shutil.copyfile(ROOT / "config/qc/protocol.json", self.layout.config / "protocol.json")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_privacy_guard_refuses_external_personal_and_unopted_confirm_audio(self) -> None:
        with tempfile.TemporaryDirectory() as external:
            ext_wav = _write_wav(Path(external) / "user_recording.wav", _make_tone(1.0))
            with self.assertRaises(multimodal.PrivacyBoundaryError):
                multimodal.validate_audio_source(self.layout, ext_wav)

        allowed_wav = _write_wav(self.root / "build/artifacts/sample.wav", _make_tone(1.0))
        self.assertEqual(multimodal.validate_audio_source(self.layout, allowed_wav), allowed_wav.resolve())

        with self.assertRaises(multimodal.PrivacyBoundaryError):
            multimodal.validate_audio_source(self.layout, allowed_wav, take={"privacy": "personal"})

        confirm_wav = _write_wav(self.layout.private / "confirm/confirm-1/1.wav", _make_tone(1.0))
        with self.assertRaises(multimodal.PrivacyBoundaryError):
            multimodal.validate_audio_source(self.layout, confirm_wav, allow_synthetic_confirm_batches=False)
        self.assertEqual(
            multimodal.validate_audio_source(
                self.layout, confirm_wav, take={"mode": "custom"}, allow_synthetic_confirm_batches=True
            ),
            confirm_wav.resolve(),
        )
        with self.assertRaises(multimodal.PrivacyBoundaryError):
            multimodal.validate_audio_source(
                self.layout, confirm_wav, take={"mode": "clone"}, allow_synthetic_confirm_batches=True
            )

    def test_prepare_qc_run_blinds_filenames_and_extracts_local_zooms_and_clone_pair(self) -> None:
        run_id = "test-run-1"
        run_dir = self.layout.runs / run_id
        audio = _write_wav(self.root / "build/artifacts/serena_secret_voice.wav", _make_tone(4.0, 240.0))
        ref = _write_wav(self.root / "build/cache/audio-qc-corpora/mls/ref_speaker_1591.wav", _make_tone(2.5, 180.0))
        store.write_json_atomic(run_dir / "takes.json", {
            "schema": store.TAKES_SCHEMA,
            "takes": [{
                "token": "tok-real-1",
                "takeID": "fr-0101--serena",
                "audio": str(audio),
                "audioSHA256": store.audio_sha256(audio),
                "reference": str(ref),
                "referenceSHA256": store.audio_sha256(ref),
                "language": "french",
                "mode": "clone",
                "text": "Bonjour le monde.",
            }],
        })
        store.write_json_atomic(run_dir / "events.json", {
            "schema": "vocello.qc.events/1",
            "takes": [{
                "token": "tok-real-1",
                "events": [{"class": "phonation-anomaly", "start": 1.8, "end": 2.2}],
            }],
        })
        summary = multimodal.prepare_qc_run(self.layout, run_id, session="s1", seed=42)
        self.assertEqual(summary["takes"], 1)
        self.assertEqual(summary["clonePairs"], 1)
        self.assertEqual(summary["localZooms"], 1)

        packet_text = (self.layout.private / "multimodal/s1/review-packet.json").read_text(encoding="utf-8")
        self.assertNotIn("serena", packet_text)
        self.assertNotIn("1591", packet_text)
        self.assertNotIn("tok-real-1", packet_text)
        packet = json.loads(packet_text)
        # Blind Pass 1 task must never carry the script.
        self.assertNotIn("intendedText", packet["blindTasks"][0])
        self.assertEqual(packet["auditTasks"][0]["intendedText"], "Bonjour le monde.")
        self.assertTrue(packet["auditTasks"][0]["hasReference"])

    def test_prepare_screen_ab_and_dual_order_reconciliation(self) -> None:
        screen = self.root / "build/artifacts/screen-1"
        wav_a = _write_wav(screen / "arms/attn/wav/t1.wav", _make_tone(2.0, 220.0))
        wav_b = _write_wav(screen / "arms/attn-io/wav/t1.wav", _make_tone(2.0, 330.0))
        wav_a2 = _write_wav(screen / "arms/attn/wav/t2.wav", _make_tone(2.0, 250.0))
        wav_b2 = _write_wav(screen / "arms/attn-io/wav/t2.wav", _make_tone(2.0, 390.0))
        store.write_json_atomic(screen / "plan.json", {
            "screen": "hybrid-test",
            "kind": "custom",
            "takes": [
                {"takeID": "t1", "language": "french", "text": "Un test."},
                {"takeID": "t2", "language": "english", "text": "Two tests."},
            ],
        })
        store.write_json_atomic(screen / "arms/attn/takes.json", {
            "takes": [
                {"takeID": "t1", "outcome": "generated", "wav": "wav/t1.wav", "pcmSHA256": store.audio_sha256(wav_a)},
                {"takeID": "t2", "outcome": "generated", "wav": "wav/t2.wav", "pcmSHA256": store.audio_sha256(wav_a2)},
            ],
        })
        store.write_json_atomic(screen / "arms/attn-io/takes.json", {
            "takes": [
                {"takeID": "t1", "outcome": "generated", "wav": "wav/t1.wav", "pcmSHA256": store.audio_sha256(wav_b)},
                {"takeID": "t2", "outcome": "generated", "wav": "wav/t2.wav", "pcmSHA256": store.audio_sha256(wav_b2)},
            ],
        })
        prep = multimodal.prepare_screen_ab(self.layout, screen, "attn", "attn-io", session="ab1", seed=7)
        self.assertEqual(prep["pairs"], 2)
        self.assertEqual(prep["pairwiseTasks"], 4)

        packet_text = (self.layout.private / "multimodal/ab1/review-packet.json").read_text(encoding="utf-8")
        self.assertNotIn("attn-io", packet_text)
        key = store.read_json(self.layout.private / "multimodal/ab1/private-key.json")

        # Pair 1: consistent win for attn-io; Pair 2: order-inconsistent (always picks clip_1 -> position bias).
        pair_ids = sorted(key["pairs"])
        verdicts_rows = []
        for otoken, ometa in key["orders"].items():
            if ometa["pairToken"] == pair_ids[0]:
                winner = "clip_1" if ometa["clip1Arm"] == "attn-io" else "clip_2"
            else:
                winner = "clip_1"  # pure first-position bias
            verdicts_rows.append({
                "taskId": f"pair-{otoken}", "orderToken": otoken, "winner": winner,
                "margin": "clear", "primaryDimension": "pronunciation", "confidence": "high",
            })
        vpath = self.layout.private / "multimodal/ab1/input-verdicts.json"
        store.write_json_atomic(vpath, {"schema": multimodal.VERDICTS_SCHEMA, "session": "ab1", "pairwise": verdicts_rows})
        report = multimodal.aggregate_session(self.layout, "ab1", vpath)
        summary = report["pairwiseSummary"]
        self.assertEqual(summary["strictWins"], 1)
        self.assertEqual(summary["orderInconsistent"], 1)
        self.assertEqual(summary["armWins"], {"attn-io": 1})
        self.assertAlmostEqual(summary["orderFlipRate"], 0.5)
        self.assertAlmostEqual(summary["positionBias"]["firstShareOfDirectional"], 0.75)

    def test_qualification_eval_contains_no_private_text_or_paths(self) -> None:
        # Build synthetic Q1 and Q2 sessions and verify aggregate-only output.
        q1_dir = multimodal.session_dir(self.layout, "q1-test")
        store.write_json_atomic(q1_dir / "private-key.json", {
            "session": "q1-test", "kind": "q1-controls",
            "truth": {
                "c1": {"o1": {"expected": "tie"}},
                "c2Pairs": {"p1": {"subtype": "clear_perturbation", "expectedWinner": "clean"}},
                "c2Orders": {
                    "o2": {"pairToken": "p1", "orientation": "ab", "clip1Arm": "clean", "clip2Arm": "perturbed:hard_clip"},
                    "o3": {"pairToken": "p1", "orientation": "ba", "clip1Arm": "perturbed:hard_clip", "clip2Arm": "clean"},
                },
                "c3": {"t1": {"corruption": "substituted_words"}},
                "c4": {"c1": {"sameSpeaker": True}, "c2": {"sameSpeaker": False}},
                "c5": {
                    "d1": {"subtype": "brief_mismatch", "shouldMatch": False},
                    "d2": {"subtype": "brief_match", "shouldMatch": True},
                    "d3": {"subtype": "harmless:gain_plus_3db", "shouldMatch": True},
                },
            },
        })
        store.write_json_atomic(q1_dir / "verdicts.json", {
            "schema": multimodal.VERDICTS_SCHEMA, "session": "q1-test",
            "pairwise": [
                {"orderToken": "o1", "winner": "tie", "margin": "none"},
                {"orderToken": "o2", "winner": "clip_1", "margin": "major"},
                {"orderToken": "o3", "winner": "clip_2", "margin": "major"},
            ],
            "diction": [{"opaqueToken": "t1", "contentMatch": "major_mismatch", "overallUsability": "unusable"}],
            "clone": [
                {"opaqueToken": "c1", "sameSpeaker": "yes", "overallUsability": "usable"},
                {"opaqueToken": "c2", "sameSpeaker": "no", "overallUsability": "unusable"},
            ],
            "delivery": [
                {"opaqueToken": "d1", "briefCompliance": "contradicts", "overallUsability": "unusable"},
                {"opaqueToken": "d2", "briefCompliance": "matches", "overallUsability": "usable"},
                {"opaqueToken": "d3", "briefCompliance": "matches", "overallUsability": "usable"},
            ],
        })
        q2_dir = multimodal.session_dir(self.layout, "q2-test")
        store.write_json_atomic(q2_dir / "private-key.json", {
            "session": "q2-test", "kind": "q2-calibration",
            "items": {
                "h1": {"role": "human_control", "language": "french", "humanVerdict": "acceptable"},
                "k1": {"role": "confirm", "language": "french", "humanVerdict": "objectionable"},
                "k2": {"role": "confirm", "language": "english", "humanVerdict": "acceptable"},
                "anchor": {"role": "dev_anchor", "language": "french", "humanVerdict": "objectionable"},
            },
        })
        store.write_json_atomic(q2_dir / "verdicts.json", {
            "schema": multimodal.VERDICTS_SCHEMA, "session": "q2-test",
            "diction": [
                {"opaqueToken": "h1", "overallUsability": "usable"},
                {"opaqueToken": "k1", "overallUsability": "unusable"},
                {"opaqueToken": "k2", "overallUsability": "usable"},
                {"opaqueToken": "anchor", "overallUsability": "usable"},  # excluded from held-out stats!
            ],
        })
        out = self.root / "eval.json"
        doc = multimodal.build_qualification_eval(self.layout, q1_session="q1-test", q2_session="q2-test", output_path=out)
        self.assertEqual(doc["axisStatus"], {
            "diction": "active_advisory",
            "delivery": "active_advisory",
            "clone": "active_advisory",
            "pairwise": "active_advisory",
        })
        # Verify dev_anchor was excluded (confirmDecisiveTotal == 2, not 3).
        self.assertEqual(doc["q2"]["confirmDecisiveTotal"], 2)
        self.assertEqual(doc["q2"]["confirmStrictUnusablePrecision"]["rate"], 1.0)
        self.assertEqual(doc["q2"]["cleanHumanFalseAlarm"]["rate"], 0.0)


if __name__ == "__main__":
    unittest.main()
