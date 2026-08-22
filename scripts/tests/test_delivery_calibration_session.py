#!/usr/bin/env python3
"""Deterministic tests for blinded dimensional calibration sessions."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest
import wave

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from delivery_calibration_session import (  # noqa: E402
    CalibrationSessionError,
    build_session,
    digest,
    merge_responses,
)


class DeliveryCalibrationSessionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.run_dir = self.root / "run"
        (self.run_dir / "audio").mkdir(parents=True)
        rows = []
        takes = {}
        acoustic_rows = []
        for index in range(24):
            take_id = f"take-{index}"
            generation_id = f"generation-{index}"
            speaker = ("aiden", "vivian", "sohee")[index % 3]
            script = f"script-{index % 4}"
            language = "English" if index % 2 == 0 else "Chinese"
            audio = self.run_dir / "audio" / f"{take_id}.wav"
            with wave.open(str(audio), "wb") as output:
                output.setnchannels(1); output.setsampwidth(2); output.setframerate(24000)
                output.writeframes(struct.pack("<h", 1) * 240)
            audio_digest = hashlib.sha256(audio.read_bytes()).hexdigest()
            rows.append({
                "takeID": take_id, "speakerID": speaker,
                "outputLanguage": language, "preset": "happy", "seed": 31000000 + index,
                "script": {"scriptID": script},
            })
            takes[take_id] = {
                "status": "complete", "generationID": generation_id,
                "audio": f"audio/{take_id}.wav", "audioSHA256": audio_digest,
            }
            acoustic_rows.append({
                "generationID": generation_id,
                "features": {"pitch": float(index), "rate": float(index % 5)},
            })
        self.plan = {
            "designation": "calibration", "executionPlanDigest": "a" * 64,
            "rows": rows,
        }
        self.plan_path = self.root / "plan.json"
        self.plan_path.write_text(json.dumps(self.plan), encoding="utf-8")
        (self.run_dir / "execution-state.json").write_text(json.dumps({
            "executionPlanDigest": "a" * 64, "takes": takes,
        }), encoding="utf-8")
        (self.run_dir / "acoustic-layer.json").write_text(json.dumps({
            "schemaVersion": 1, "manifestDigest": "a" * 64,
            "featureNames": ["pitch", "rate"], "rows": acoustic_rows,
        }), encoding="utf-8")
        self.session = self.root / "session"
        build_session(
            plan_path=self.plan_path, run_dir=self.run_dir,
            out_dir=self.session, session_seed=77,
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _write_response(self, listener: str, offset: float = 0.0) -> None:
        manifest = json.loads((self.session / "manifest.json").read_text())
        response = {
            "schemaVersion": 1, "sessionDigest": manifest["sessionDigest"],
            "listenerDigest": hashlib.sha256(listener.encode()).hexdigest(),
            "fluentLanguages": ["English", "Chinese"],
            "ratings": [{
                "itemID": item["itemID"],
                "valence": max(-1.0, min(1.0, (index % 5 - 2) / 2 + offset)),
                "arousal": max(-1.0, min(1.0, (index % 7 - 3) / 3 + offset)),
                "dominance": max(-1.0, min(1.0, (index % 3 - 1) + offset)),
            } for index, item in enumerate(manifest["items"])],
        }
        response["responseDigest"] = digest(response)
        path = self.session / "responses" / f"{listener}.json"
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps(response), encoding="utf-8")

    def test_public_manifest_does_not_leak_requested_labels(self) -> None:
        manifest = json.loads((self.session / "manifest.json").read_text())
        text = json.dumps(manifest)
        self.assertNotIn("preset", text)
        self.assertNotIn("speakerID", text)
        self.assertNotIn("scriptID", text)
        self.assertEqual(len(manifest["items"]), 24)

    def test_three_agreeing_fluent_listeners_produce_qualified_dataset(self) -> None:
        for listener, offset in (("one", 0.0), ("two", 0.01), ("three", -0.01)):
            self._write_response(listener, offset)
        result = merge_responses(session_dir=self.session)
        self.assertTrue(result["labelProvenance"]["calibrationQualified"])
        self.assertEqual(len(result["rows"]), 24)
        self.assertEqual(set(result["rows"][0]["labels"]), {
            "valence", "arousal", "dominance",
        })

    def test_missing_listener_or_tampered_response_cannot_qualify(self) -> None:
        self._write_response("one")
        self._write_response("two")
        result = merge_responses(session_dir=self.session)
        self.assertFalse(result["labelProvenance"]["calibrationQualified"])
        self.assertIn(
            "fewer-than-three-independent-listeners",
            result["labelProvenance"]["qualificationFailures"],
        )
        response_path = next((self.session / "responses").glob("*.json"))
        response = json.loads(response_path.read_text())
        response["ratings"][0]["valence"] = -0.75
        response_path.write_text(json.dumps(response), encoding="utf-8")
        with self.assertRaisesRegex(CalibrationSessionError, "response digest"):
            merge_responses(session_dir=self.session)

    def test_partial_generation_run_cannot_become_a_calibration_packet(self) -> None:
        state_path = self.run_dir / "execution-state.json"
        state = json.loads(state_path.read_text())
        state["takes"]["take-0"]["status"] = "failed"
        state_path.write_text(json.dumps(state), encoding="utf-8")
        with self.assertRaisesRegex(CalibrationSessionError, "incomplete or failed"):
            build_session(
                plan_path=self.plan_path, run_dir=self.run_dir,
                out_dir=self.root / "partial-session", session_seed=88,
            )

    def test_private_key_is_digest_bound(self) -> None:
        private_path = self.session / "private-key.json"
        private_key = json.loads(private_path.read_text())
        private_key["items"][0]["preset"] = "angry"
        private_path.write_text(json.dumps(private_key), encoding="utf-8")
        with self.assertRaisesRegex(CalibrationSessionError, "private calibration key changed"):
            merge_responses(session_dir=self.session)

    def test_source_audio_is_digest_bound(self) -> None:
        audio = self.run_dir / "audio" / "take-0.wav"
        audio.write_bytes(audio.read_bytes() + b"changed")
        with self.assertRaisesRegex(CalibrationSessionError, "audio digest mismatch"):
            build_session(
                plan_path=self.plan_path, run_dir=self.run_dir,
                out_dir=self.root / "changed-audio-session", session_seed=99,
            )


if __name__ == "__main__":
    unittest.main()
