from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock
import uuid


SCRIPTS = Path(__file__).resolve().parents[1]
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import check_ios_clone_conditioning as validator  # noqa: E402


VOICE_ID = "A_warm_elderly_woman"
AUDIO_DIGEST = "03187893a3d82d38264d433f24828982c67ed42cddb71eefccb776b37ab9fe35"
TRANSCRIPT_DIGEST = "98a8e46ed2cd48354f6056dc889f9209641824e610a687eeb9ab91d310477234"
RUN_ID = "ios-clone-conditioning-20260715-120000-1234abcd"


def output_verification() -> dict:
    return {
        "schemaVersion": 3,
        "algorithmVersion": "language-output-verifier-v3",
        "expectedLanguage": "english",
        "pass": True,
        "languagePass": True,
        "accuracyPass": True,
    }


def make_take(index: int, output: Path) -> dict:
    output_bytes = f"output-{index}".encode()
    output.write_bytes(output_bytes)
    transcript_backed = index == 1
    mode = "transcript_backed" if transcript_backed else "x_vector_only"
    return {
        "takeIndex": index,
        "generationID": str(uuid.uuid4()),
        "cell": (
            "clone/speed/conditioning/transcript-backed"
            if transcript_backed else "clone/speed/conditioning/x-vector-only"
        ),
        "mode": "clone",
        "modelID": "qwen3-tts-0.6b-clone-speed",
        "conditioningMode": mode,
        "transcriptMode": "inline" if transcript_backed else "none",
        "promptArtifactScope": "saved_voice" if transcript_backed else "transient_reference",
        "transcriptBacked": transcript_backed,
        "xVectorOnly": not transcript_backed,
        "supportsXVectorOnlyClone": True,
        "optimizedHandlerUsed": True,
        "promptMaterialized": True,
        "conditioningReused": False,
        "preparedCloneCacheHit": False,
        "referenceAudioSHA256": AUDIO_DIGEST,
        "promptAssemblySHA256": hashlib.sha256(f"prompt-{index}".encode()).hexdigest(),
        "wallSeconds": 1.25,
        "outputFileName": output.name,
        "outputEvidence": {
            "artifactRelativePath": f"outputs/{output.name}",
            "sha256": hashlib.sha256(output_bytes).hexdigest(),
            "byteCount": len(output_bytes),
            "durationSeconds": 1.0,
            "sampleRate": 24000.0,
            "channelCount": 1,
            "frameCount": 24000,
        },
        "outputVerification": output_verification(),
    }


def make_payload(outputs: Path) -> dict:
    takes = [
        make_take(1, outputs / "take-01-transcript_backed.wav"),
        make_take(2, outputs / "take-02-x_vector_only.wav"),
    ]
    return {
        "schemaVersion": 1,
        "status": "pass",
        "runID": RUN_ID,
        "startedAt": "2026-07-15T12:00:00Z",
        "finishedAt": "2026-07-15T12:05:00Z",
        "seed": 19_790_615,
        "samplingVariation": "expressive",
        "voiceIDDigest": hashlib.sha256(VOICE_ID.encode()).hexdigest(),
        "referenceAudioSHA256": AUDIO_DIGEST,
        "referenceTranscriptSHA256": TRANSCRIPT_DIGEST,
        "scratchCleanupVerified": True,
        "takes": takes,
    }


class CloneConditioningValidatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.outputs = self.root / "outputs"
        self.outputs.mkdir()
        self.payload = make_payload(self.outputs)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def validate_contract(self, payload: dict | None = None) -> list[dict]:
        return validator.validate_result_contract(
            payload or self.payload,
            run_id=RUN_ID,
            expected_voice_id=VOICE_ID,
            expected_audio_sha256=AUDIO_DIGEST,
            expected_transcript_sha256=TRANSCRIPT_DIGEST,
            outputs=self.outputs,
        )

    def test_exact_two_mode_contract_passes(self) -> None:
        takes = self.validate_contract()
        self.assertEqual([take["conditioningMode"] for take in takes], [
            "transcript_backed", "x_vector_only",
        ])

    def test_audio_only_take_cannot_claim_transcript_backed(self) -> None:
        payload = copy.deepcopy(self.payload)
        payload["takes"][1]["transcriptBacked"] = True
        with self.assertRaisesRegex(validator.CloneConditioningValidationError, "transcriptBacked"):
            self.validate_contract(payload)

    def test_prompt_assemblies_must_be_distinct(self) -> None:
        payload = copy.deepcopy(self.payload)
        payload["takes"][1]["promptAssemblySHA256"] = payload["takes"][0]["promptAssemblySHA256"]
        with self.assertRaisesRegex(validator.CloneConditioningValidationError, "distinct prompt"):
            self.validate_contract(payload)

    def test_missing_output_fails_exact_identity(self) -> None:
        (self.outputs / "take-02-x_vector_only.wav").unlink()
        with self.assertRaisesRegex(validator.CloneConditioningValidationError, "missing exact output"):
            self.validate_contract()

    def test_unknown_result_field_fails_closed(self) -> None:
        payload = copy.deepcopy(self.payload)
        payload["unexpected"] = True
        with self.assertRaisesRegex(validator.CloneConditioningValidationError, "top-level shape"):
            self.validate_contract(payload)

    def test_full_validation_remains_local_and_never_publishes_history(self) -> None:
        result_path = self.root / "clone-conditioning-result.json"
        result_path.write_text(json.dumps(self.payload), encoding="utf-8")
        generation_ids = [take["generationID"] for take in self.payload["takes"]]
        rows = [
            {
                "schemaVersion": 8,
                "layer": "engine",
                "generationID": generation_id,
                "mode": "clone",
                "modelID": "qwen3-tts-0.6b-clone-speed",
                "usedStreaming": True,
                "notes": {
                    "benchRunID": RUN_ID,
                    "benchCell": self.payload["takes"][index - 1]["cell"],
                    "benchTakeIndex": str(index),
                },
            }
            for index, generation_id in enumerate(generation_ids, start=1)
        ]
        app_directory = self.root / "diagnostics" / "app"
        app_directory.mkdir(parents=True)
        app_rows = [
            {
                "schemaVersion": 8,
                "layer": "app",
                "generationID": generation_id,
                "mode": "clone",
                "finishReason": "completed",
                "notes": {
                    "benchRunID": RUN_ID,
                    "benchCell": self.payload["takes"][index - 1]["cell"],
                    "benchTakeIndex": str(index),
                },
                "frontendMetrics": {"submitToCompletedMS": 1250.0},
                "timingsMS": {"submitToCompletedMS": 1250.0},
            }
            for index, generation_id in enumerate(generation_ids, start=1)
        ]
        (app_directory / "generations.jsonl").write_text(
            "".join(json.dumps(row) + "\n" for row in app_rows),
            encoding="utf-8",
        )
        args = argparse.Namespace(
            result=result_path,
            diagnostics=self.root / "diagnostics",
            outputs=self.outputs,
            snapshot=self.root / "benchmark-source.json",
            crash_diagnostics=self.root / "crashes",
            run_id=RUN_ID,
            label="focused-clone-proof",
            expected_voice_id=VOICE_ID,
            expected_audio_sha256=AUDIO_DIGEST,
            expected_transcript_sha256=TRANSCRIPT_DIGEST,
            output=self.root / "validation.json",
        )
        with (
            mock.patch.object(validator, "load_engine_rows", return_value=rows),
            mock.patch.object(validator, "rows_by_generation", return_value=rows),
            mock.patch.object(validator, "successful_row"),
            mock.patch.object(
                validator,
                "qualify_memory_rows",
                return_value=([], {
                    "memoryQualified": True,
                    "status": "qualified",
                    "warnings": [],
                }),
            ),
            mock.patch.object(
                validator,
                "source_from_snapshot",
                return_value={"commit": "a" * 40, "dirty": False, "fingerprintsMatch": True},
            ),
            mock.patch.object(
                validator,
                "crash_delta_from_snapshot",
                return_value={"passed": True, "count": 0},
            ),
        ):
            summary = validator.validate(args)
        self.assertEqual(summary["status"], "passed")
        self.assertFalse(summary["historyPublished"])


if __name__ == "__main__":
    unittest.main()
