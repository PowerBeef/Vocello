import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import wave


REPO = Path(__file__).resolve().parents[2]
MODULE_PATH = REPO / "scripts/voice_identity_language_reliability.py"
SPEC = importlib.util.spec_from_file_location("voice_identity_language_reliability", MODULE_PATH)
VLR = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(VLR)


class VoiceIdentityLanguageReliabilityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.contract = VLR.load_json(REPO / "config/voice-identity-language-reliability.json")
        self.runtime = self.root / "runtime"
        tokenizer = self.runtime / "models/current/speech_tokenizer/model.safetensors"
        tokenizer.parent.mkdir(parents=True)
        tokenizer.write_bytes(b"test-tokenizer")
        identity = {
            "required": True,
            "sha256": hashlib.sha256(b"test-tokenizer").hexdigest(),
            "sizeBytes": len(b"test-tokenizer"),
            "artifactVersion": "test-current",
        }
        self.contract = copy.deepcopy(self.contract)
        self.contract["tokenizerArms"]["current-fp16"] = identity
        self.contract["tokenizerArms"]["archived-fp32"] = {
            **identity,
            "required": False,
            "artifactVersion": "test-archived",
        }
        self.references = []
        for index, (alias, role, language) in enumerate((
            ("user-reference-a", "user", "french"),
            ("user-reference-b", "user", "english"),
            ("control-french", "control", "french"),
            ("control-english", "control", "english"),
        )):
            audio = self.root / f"audio-{index}.wav"
            self._write_wav(audio, value=100 + index)
            reviewed = self.root / f"reviewed-{index}.txt"
            corrected = self.root / f"corrected-{index}.txt"
            reviewed.write_text(
                "Bonjour, ceci est une référence française claire."
                if language == "french" else
                "Hello, this is a clear English reference.",
                encoding="utf-8",
            )
            corrected.write_text(reviewed.read_text(encoding="utf-8") + " Corrected.", encoding="utf-8")
            self.references.append({
                "alias": alias, "role": role, "audioPath": str(audio),
                "reviewedTranscriptPath": str(reviewed),
                "correctedTranscriptPath": str(corrected),
                "referenceLanguage": language,
            })
        self.spec = self.root / "private-input.json"
        self._write_spec()
        self.bundle_root = self.root / "bundle"
        self.bundle = VLR.prepare_bundle(
            input_spec_path=self.spec, output=self.bundle_root, contract=self.contract
        )

    def tearDown(self):
        self.temp.cleanup()

    @staticmethod
    def _write_wav(path: Path, *, value: int) -> None:
        with wave.open(str(path), "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(16_000)
            sample = int(value).to_bytes(2, "little", signed=True)
            handle.writeframes(sample * 1_600)

    def _write_spec(self, profiles=None) -> None:
        payload = {
            "schemaVersion": 1,
            "runID": "vlr-test-run",
            "references": self.references,
            "runtimeProfiles": profiles or {
                "current-fp16": {"dataDir": str(self.runtime)},
                "archived-fp32": {"dataDir": str(self.runtime)},
            },
        }
        self.spec.write_text(json.dumps(payload), encoding="utf-8")

    def test_bundle_is_content_addressed_and_public_manifest_is_redacted(self):
        public = (self.bundle_root / "bundle-manifest.json").read_text(encoding="utf-8")
        self.assertNotIn(str(self.root), public)
        self.assertNotIn("Bonjour", public)
        self.assertNotIn("Hello", public)
        self.assertEqual({row["alias"] for row in self.bundle["references"]}, {
            "user-reference-a", "user-reference-b", "control-french", "control-english",
        })
        for row in self.bundle["references"]:
            self.assertRegex(row["audioSHA256"], r"^[0-9a-f]{64}$")
            self.assertTrue(row["transcripts"]["reviewed"]["characters"] > 0)

    def test_plan_has_complete_frozen_matrix_and_exact_source_binding(self):
        plan = VLR.build_plan(
            contract=self.contract, bundle=self.bundle, source_identity="a" * 64
        )
        self.assertEqual(plan["takeCount"], 734)
        VLR.validate_plan(
            plan, self.contract, self.bundle,
            expected_source_identity="a" * 64,
        )
        self.assertEqual({row["seed"] for row in plan["takes"]}, set(self.contract["fixedSeeds"]))
        modes = {row["mode"] for row in plan["takes"]}
        self.assertEqual(modes, {"clone", "design"})
        design_arms = {row.get("deliveryArm") for row in plan["takes"] if row["mode"] == "design"}
        self.assertEqual(design_arms, {
            "current-neutral", "diagnostic-no-delivery", "calm-strong-control",
        })
        clone_arms = {row["transcriptArm"] for row in plan["takes"] if row["mode"] == "clone"}
        self.assertEqual(clone_arms, {"reviewed", "corrected", "audio-only"})

    def test_missing_transcript_and_archived_runtime_are_explicitly_blocked(self):
        self.references[0].pop("correctedTranscriptPath")
        self._write_spec(profiles={"current-fp16": {"dataDir": str(self.runtime)}})
        bundle_root = self.root / "partial-bundle"
        bundle = VLR.prepare_bundle(
            input_spec_path=self.spec, output=bundle_root, contract=self.contract
        )
        plan = VLR.build_plan(
            contract=self.contract, bundle=bundle, source_identity="b" * 64
        )
        blocked = [row for row in plan["takes"] if row.get("blockedPrerequisite")]
        self.assertTrue(any(row["blockedPrerequisite"] == "corrected-transcript-missing" for row in blocked))
        self.assertTrue(any(row["blockedPrerequisite"] == "archived-fp32-runtime-unavailable" for row in blocked))
        self.assertEqual(plan["takeCount"], 734)

    def test_plan_digest_and_cross_run_observation_fail_closed(self):
        plan = VLR.build_plan(
            contract=self.contract, bundle=self.bundle,
            source_identity=VLR.tree_fingerprint(),
        )
        tampered = copy.deepcopy(plan)
        tampered["takes"][0]["seed"] += 1
        with self.assertRaisesRegex(VLR.ReliabilityError, "plan digest"):
            VLR.validate_plan(tampered, self.contract, self.bundle)

        run_dir = self.root / "run"
        run_dir.mkdir()
        VLR.atomic_json(run_dir / "execution-plan.json", plan)
        VLR.append_jsonl(run_dir / "observations.jsonl", {
            "takeID": plan["takes"][0]["takeID"],
            "planDigest": "d" * 64,
            "status": "HARD_FAILURE",
        })
        fake_binary = self.root / "vocello"
        fake_binary.write_text("not executed", encoding="utf-8")
        with self.assertRaisesRegex(VLR.ReliabilityError, "cross-run"):
            VLR.execute_plan(
                plan=plan, contract=self.contract, bundle_root=self.bundle_root,
                binary=fake_binary, run_dir=run_dir, max_takes=0,
            )

    def test_analysis_manifest_excludes_failures_and_binds_audio(self):
        plan = VLR.build_plan(
            contract=self.contract, bundle=self.bundle, source_identity="e" * 64
        )
        clone_rows = [row for row in plan["takes"] if row["mode"] == "clone"]
        passing = clone_rows[0]
        failing = clone_rows[1]
        run_dir = self.root / "analysis-run"
        audio_root = run_dir / "private/audio"
        audio_root.mkdir(parents=True)
        output = audio_root / "take.wav"
        self._write_wav(output, value=250)
        VLR.append_jsonl(run_dir / "observations.jsonl", {
            "takeID": passing["takeID"], "planDigest": plan["planDigest"],
            "status": "PASS", "generationID": "generation-1",
            "audioFileName": output.name, "audioSHA256": VLR.file_digest(output),
        })
        VLR.append_jsonl(run_dir / "observations.jsonl", {
            "takeID": failing["takeID"], "planDigest": plan["planDigest"],
            "status": "HARD_FAILURE",
        })
        manifest = VLR.build_analysis_manifest(
            plan=plan, bundle_root=self.bundle_root, run_dir=run_dir
        )
        self.assertEqual(len(manifest["rows"]), 1)
        self.assertEqual(manifest["rows"][0]["generationID"], "generation-1")
        self.assertFalse(manifest.get("promotionAuthority", False))

    def test_device_plan_is_exact_and_private_map_is_source_bound(self):
        plan = VLR.build_device_plan(
            contract=self.contract,
            run_id="vlr-device-test",
            source_identity="f" * 64,
        )
        VLR.validate_device_plan(
            plan, self.contract, expected_source_identity="f" * 64
        )
        with self.assertRaisesRegex(VLR.ReliabilityError, "source identity"):
            VLR.validate_device_plan(plan, self.contract)
        self.assertEqual(plan["takeCount"], 26)
        self.assertEqual(
            sum(row["mode"] == "clone" for row in plan["takes"]), 8
        )
        self.assertEqual(
            sum(row["mode"] == "design" for row in plan["takes"]), 18
        )
        private_map = self.root / "device-map.json"
        private_map.write_text(json.dumps({
            "schemaVersion": 1,
            "planDigest": plan["planDigest"],
            "references": [
                {"alias": "user-reference-a", "voiceID": "private-a"},
                {"alias": "user-reference-b", "voiceID": "private-b"},
            ],
        }), encoding="utf-8")
        resolved = VLR.load_private_device_map(
            private_map, plan, self.contract
        )
        self.assertEqual(set(resolved), {"user-reference-a", "user-reference-b"})

        changed = json.loads(private_map.read_text(encoding="utf-8"))
        changed["planDigest"] = "0" * 64
        private_map.write_text(json.dumps(changed), encoding="utf-8")
        with self.assertRaisesRegex(VLR.ReliabilityError, "another plan"):
            VLR.load_private_device_map(private_map, plan, self.contract)

    def test_device_composer_fails_closed_and_redacts_voice_ids(self):
        plan = VLR.build_device_plan(
            contract=self.contract,
            run_id="vlr-device-compose",
            source_identity=VLR.tree_fingerprint(),
        )
        diagnostics = self.root / "diagnostics"
        for row in plan["takes"]:
            sentinel = {
                "status": "ok",
                "mode": row["mode"],
                "seed": row["seed"],
                "samplingVariation": row["variation"],
                "resolvedLanguageHint": row["expectedFinalLanguage"],
                "requestReceipt": {
                    "schemaVersion": 2,
                    "storedLanguageSelection": row["expectedStoredLanguage"],
                    "detectedTargetLanguage": row["targetLanguage"],
                    "finalModelLanguage": row["expectedFinalLanguage"],
                    "conditioningMode": row["expectedConditioningMode"],
                    "targetTextDigest": row["scriptDigest"],
                    "speechTokenizerDigest": row["expectedTokenizerDigest"],
                    "instructionDigest": row.get("expectedInstructionDigest"),
                    "modelFacingInstructionLanguage": row.get("expectedInstructionLanguage"),
                    "referenceAudioDigest": "a" * 64 if row["referenceAlias"] == "user-reference-a" else "b" * 64,
                    "referenceTranscriptLanguage": "french",
                },
                "outputVerification": {
                    "pass": True,
                    "wordErrorRate": 0.0,
                    "characterErrorRate": 0.0,
                },
            }
            path = diagnostics / row["childRunID"] / "device-diagnostics-done.json"
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps(sentinel), encoding="utf-8")
        transcription = self.root / "transcription.json"
        transcription.write_text(json.dumps({
            "schemaVersion": 1,
            "references": [
                {
                    "alias": alias,
                    "found": True,
                    "referenceAudioDigest": digest * 64,
                    "hasStoredTranscript": True,
                    "storedTranscriptDigest": "c" * 64,
                    "automaticTranscription": {
                        "outcome": "success",
                        "authorizationStatus": "authorized",
                        "attempts": [],
                    },
                }
                for alias, digest in (
                    ("user-reference-a", "a"),
                    ("user-reference-b", "b"),
                )
            ],
        }), encoding="utf-8")
        output = self.root / "device-summary.json"
        report = VLR.compose_device_results(
            plan=plan,
            contract=self.contract,
            diagnostics_root=diagnostics,
            transcription=transcription,
            output=output,
        )
        self.assertEqual(report["status"], "PASS")
        serialized = output.read_text(encoding="utf-8")
        self.assertNotIn("private-a", serialized)
        self.assertNotIn("private-b", serialized)

        first = plan["takes"][0]
        first_path = diagnostics / first["childRunID"] / "device-diagnostics-done.json"
        tampered = json.loads(first_path.read_text(encoding="utf-8"))
        tampered["requestReceipt"]["finalModelLanguage"] = "chinese"
        first_path.write_text(json.dumps(tampered), encoding="utf-8")
        tampered_report = VLR.compose_device_results(
            plan=plan,
            contract=self.contract,
            diagnostics_root=diagnostics,
            transcription=transcription,
            output=self.root / "tampered-summary.json",
        )
        self.assertEqual(tampered_report["status"], "FAIL")
        self.assertIn(
            "receipt-finalModelLanguage-mismatch",
            tampered_report["takes"][0]["failures"],
        )


if __name__ == "__main__":
    unittest.main()
