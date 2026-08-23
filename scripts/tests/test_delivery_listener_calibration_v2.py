#!/usr/bin/env python3
"""Versioned v2 listening calibration tests; v1 remains covered separately."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest
import wave

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from delivery_calibration_session import CalibrationSessionError, digest  # noqa: E402
from delivery_listener_calibration_v2 import (  # noqa: E402
    build_v2_session,
    listener_trial_plan,
    merge_v2_responses,
)


class DeliveryListenerCalibrationV2Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.run = self.root / "run"
        (self.run / "audio").mkdir(parents=True)
        rows, takes, references, acoustic = [], {}, {}, []
        for index in range(24):
            take_id = f"take-{index}"
            generation = f"generation-{index}"
            reference_key = f"reference-{index}"
            take_audio = self.run / "audio" / f"take-{index}.wav"
            neutral_audio = self.run / "audio" / f"neutral-{index}.wav"
            self._wav(take_audio, index + 2)
            self._wav(neutral_audio, 1)
            take_digest = hashlib.sha256(take_audio.read_bytes()).hexdigest()
            neutral_digest = hashlib.sha256(neutral_audio.read_bytes()).hexdigest()
            rows.append({
                "takeID": take_id,
                "speakerID": ("aiden", "vivian", "sohee")[index % 3],
                "outputLanguage": "English",
                "preset": ("happy", "angry", "sad")[index % 3],
                "seed": 32000000 + index,
                "script": {
                    "scriptID": f"script-{index % 4}",
                    "translationGroup": f"translation-{index % 4}",
                },
            })
            takes[take_id] = {
                "status": "complete", "generationID": generation,
                "referenceKey": reference_key,
                "audio": f"audio/take-{index}.wav", "audioSHA256": take_digest,
            }
            references[reference_key] = {
                "status": "complete", "generationID": f"neutral-generation-{index}",
                "audio": f"audio/neutral-{index}.wav", "audioSHA256": neutral_digest,
            }
            acoustic.append({
                "generationID": generation,
                "features": {"pitch": float(index), "energy": float(index % 5)},
                "temporalDeltaV1": {"derivedContours": {"rise": float(index)}},
            })
        self.plan = {
            "designation": "calibration", "executionPlanDigest": "a" * 64,
            "rows": rows,
        }
        self.plan_path = self.root / "plan.json"
        self.plan_path.write_text(json.dumps(self.plan), encoding="utf-8")
        (self.run / "execution-state.json").write_text(json.dumps({
            "executionPlanDigest": "a" * 64,
            "takes": takes, "references": references,
        }), encoding="utf-8")
        (self.run / "acoustic-layer.json").write_text(json.dumps({
            "schemaVersion": 1, "manifestDigest": "a" * 64,
            "featureNames": ["pitch", "energy"], "rows": acoustic,
        }), encoding="utf-8")
        self.session = self.root / "session"
        self.manifest = build_v2_session(
            plan_path=self.plan_path, run_dir=self.run, out_dir=self.session,
            session_seed=20260822,
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    @staticmethod
    def _wav(path: Path, sample: int) -> None:
        with wave.open(str(path), "wb") as output:
            output.setnchannels(1); output.setsampwidth(2); output.setframerate(16_000)
            output.writeframes(struct.pack("<h", sample) * 640)

    def _response(self, name: str) -> None:
        listener = hashlib.sha256(name.encode()).hexdigest()
        plan = listener_trial_plan(self.manifest, listener)
        rows = []
        for trial in plan:
            row = {
                "presentationID": trial["presentationID"],
                "trialID": trial["trialID"],
                "repeatOfTrialID": trial.get("repeatOfTrialID"),
                "task": trial["task"],
                "uncertain": False,
                "confidence": 4,
                "replayCount": 1,
                "responseLatencyMilliseconds": 500,
            }
            if trial["task"].startswith("dimensional"):
                index = int(trial["trialID"][:4], 16)
                value = (index % 5 - 2) / 2
                row.update({
                    "valence": value, "arousal": value,
                    "dominance": value, "freeIdentification": "happy",
                    "naturalness": 4, "perceivedIntensity": 3,
                })
            else:
                row["choice"] = "A"
            rows.append(row)
        body = {
            "schemaVersion": 2,
            "sessionDigest": self.manifest["sessionDigest"],
            "listenerDigest": listener,
            "fluentLanguages": ["English"],
            "trialOrderDigest": digest(plan),
            "responses": rows,
        }
        body["responseDigest"] = digest(body)
        path = self.session / "responses-v2" / f"{listener[:16]}.json"
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps(body), encoding="utf-8")

    def test_dimensional_block_is_blind_and_pairwise_block_names_target(self) -> None:
        dimensional = json.dumps(self.manifest["dimensionalTrials"])
        self.assertNotIn("preset", dimensional)
        self.assertNotIn("targetDelivery", dimensional)
        self.assertIn("targetDelivery", self.manifest["pairwiseTrials"][0])

    def test_per_listener_order_and_repeat_fraction_are_deterministic(self) -> None:
        one = hashlib.sha256(b"one").hexdigest()
        two = hashlib.sha256(b"two").hexdigest()
        first = listener_trial_plan(self.manifest, one)
        self.assertEqual(first, listener_trial_plan(self.manifest, one))
        self.assertNotEqual(
            [row["presentationID"] for row in first],
            [row["presentationID"] for row in listener_trial_plan(self.manifest, two)],
        )
        repeats = sum(row.get("repeatOfTrialID") is not None for row in first)
        unique = len(self.manifest["dimensionalTrials"]) + len(self.manifest["pairwiseTrials"])
        self.assertGreaterEqual(repeats / unique, 0.10)
        self.assertLessEqual(repeats / unique, 0.15)

    def test_listener_level_data_and_qualification_gaps_are_retained(self) -> None:
        for listener in ("one", "two", "three"):
            self._response(listener)
        merged = merge_v2_responses(session_dir=self.session)
        self.assertEqual(len(merged["listenerRows"]), 3)
        self.assertEqual(len(merged["rows"]), 24)
        failures = merged["labelProvenance"]["qualificationFailures"]
        self.assertIn("fewer-than-six-speakers", failures)
        self.assertIn("fewer-than-eight-presets", failures)
        self.assertIn("anchors-not-configured", failures)
        self.assertFalse(merged["labelProvenance"]["calibrationQualified"])

    def test_order_tampering_fails_closed(self) -> None:
        self._response("one")
        path = next((self.session / "responses-v2").glob("*.json"))
        response = json.loads(path.read_text())
        response["responses"].reverse()
        response["responseDigest"] = digest({
            key: value for key, value in response.items() if key != "responseDigest"
        })
        path.write_text(json.dumps(response), encoding="utf-8")
        with self.assertRaisesRegex(CalibrationSessionError, "deterministic listener order"):
            merge_v2_responses(session_dir=self.session)


if __name__ == "__main__":
    unittest.main()
