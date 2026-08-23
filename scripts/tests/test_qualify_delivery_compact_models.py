#!/usr/bin/env python3
"""Privacy-safe compact-model qualification report tests."""

from __future__ import annotations

import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch
import wave

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from delivery_analysis_cache import file_sha256  # noqa: E402
from qualify_delivery_compact_models import (  # noqa: E402
    QualificationError,
    canonical_hardware_attestation,
    qualify,
)


class QualifyDeliveryCompactModelsTests(unittest.TestCase):
    HARDWARE = {
        "profileID": "fixture-host", "modelIdentifier": "Fixture1,1",
        "memoryBytes": 8 * 1024**3,
    }

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.config = self.root / "config.json"
        self.config.write_text(json.dumps({
            "adapterID": "sensevoice-small-q8", "modelID": "fixture",
            "sourceRevision": "revision", "weightsSHA256": "1" * 64,
            "binarySHA256": "2" * 64, "adapterSourceSHA256": "3" * 64,
            "runtimeDependenciesDigest": "4" * 64, "labelMapDigest": "5" * 64,
            "preprocessingConfigDigest": "6" * 64,
            "adapterLayerSHA256": "7" * 64,
            "resourceSupervisorSHA256": "8" * 64,
        }), encoding="utf-8")
        self.audio = [self._wav(f"{index}.wav", index + 1) for index in range(2)]

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _wav(self, name: str, sample: int) -> Path:
        path = self.root / name
        with wave.open(str(path), "wb") as output:
            output.setnchannels(1); output.setsampwidth(2); output.setframerate(16_000)
            output.writeframes(struct.pack("<3200h", *([sample] * 3200)))
        return path

    @staticmethod
    def _payload() -> dict:
        return {
            "adapterID": "sensevoice-small-q8",
            "outputs": {
                "transcript": "private fixture transcript", "languageTag": "en",
                "emotionTag": "NEUTRAL", "eventTag": "Speech",
                "textNormalizationTag": "withitn",
            },
            "resourceEnvelope": {
                "qualified": True, "peakRSSBytes": 100, "qualificationFailures": [],
            },
        }

    def test_report_hashes_transcript_and_never_exposes_paths_or_text(self) -> None:
        with patch("qualify_delivery_compact_models.run_compact_adapter") as adapter:
            adapter.side_effect = [(self._payload(), False), (self._payload(), False)]
            report = qualify(
                config_path=self.config, audio_paths=self.audio,
                output_root=self.root / "output", hardware_attestation=self.HARDWARE,
            )
        serialized = json.dumps(report)
        self.assertTrue(report["qualifiedForHoldoutBakeoff"])
        self.assertNotIn("private fixture transcript", serialized)
        self.assertNotIn(str(self.root), serialized)
        self.assertEqual(report["serialRunCount"], 2)

    def test_cache_hit_and_duplicate_audio_fail_closed(self) -> None:
        with self.assertRaisesRegex(QualificationError, "byte-distinct"):
            qualify(
                config_path=self.config, audio_paths=[self.audio[0], self.audio[0]],
                output_root=self.root / "output", hardware_attestation=self.HARDWARE,
            )
        with patch("qualify_delivery_compact_models.run_compact_adapter") as adapter:
            adapter.return_value = (self._payload(), True)
            with self.assertRaisesRegex(QualificationError, "cache"):
                qualify(
                    config_path=self.config, audio_paths=self.audio,
                    output_root=self.root / "output", hardware_attestation=self.HARDWARE,
                )

    def test_unqualified_envelope_is_retained_and_stops_before_next_layer(self) -> None:
        payload = self._payload()
        payload["resourceEnvelope"] = {
            "qualified": False, "peakRSSBytes": 100,
            "qualificationFailures": ["post-exit-memory-recovery-unqualified"],
        }
        with patch("qualify_delivery_compact_models.run_compact_adapter") as adapter:
            adapter.return_value = (payload, False)
            report = qualify(
                config_path=self.config, audio_paths=self.audio,
                output_root=self.root / "output", hardware_attestation=self.HARDWARE,
            )
        self.assertFalse(report["qualifiedForHoldoutBakeoff"])
        self.assertEqual(len(report["runs"]), 1)
        self.assertIn("post-exit-memory-recovery-unqualified", report["qualificationFailures"][0])
        adapter.assert_called_once()

    def test_hardware_attestation_is_required_and_reported(self) -> None:
        with patch(
            "qualify_delivery_compact_models.canonical_hardware_attestation",
            return_value=self.HARDWARE,
        ), patch("qualify_delivery_compact_models.run_compact_adapter") as adapter:
            adapter.side_effect = [(self._payload(), False), (self._payload(), False)]
            report = qualify(
                config_path=self.config, audio_paths=self.audio,
                output_root=self.root / "output",
            )
        self.assertEqual(report["hardware"], self.HARDWARE)
        with self.assertRaisesRegex(QualificationError, "hardware attestation"):
            qualify(
                config_path=self.config, audio_paths=self.audio,
                output_root=self.root / "other",
                hardware_attestation={"profileID": "fixture-host"},
            )

    def test_live_hardware_attestation_matches_tracked_canonical_profile(self) -> None:
        registry = {"profiles": [{
            "id": "mac-mini-m2-8gb", "platform": "macos", "canonical": True,
            "modelIdentifier": "Mac14,3", "memoryBytes": 8 * 1024**3,
        }]}
        with patch("qualify_delivery_compact_models._read", return_value=registry), patch(
            "qualify_delivery_compact_models._required_command_output",
            side_effect=("Mac14,3", str(8 * 1024**3)),
        ):
            attestation = canonical_hardware_attestation()
        self.assertEqual(attestation["profileID"], "mac-mini-m2-8gb")
        with patch("qualify_delivery_compact_models._read", return_value=registry), patch(
            "qualify_delivery_compact_models._required_command_output",
            side_effect=("Mac99,1", str(8 * 1024**3)),
        ), self.assertRaisesRegex(QualificationError, "does not match"):
            canonical_hardware_attestation()


if __name__ == "__main__":
    unittest.main()
