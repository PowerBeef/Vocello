from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import plistlib
import signal
import subprocess
import sys
import tempfile
import unittest
import wave
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import cli_package as package
import release_evidence


def plist_dump(info: dict) -> str:
    data = plistlib.dumps(info)
    data += b"\0" * (-len(data) % 4)
    return "\n".join(f"{index:016x}\t{int.from_bytes(data[index:index+4], 'little'):08x}" for index in range(0, len(data), 4))


class CLIPackageTests(unittest.TestCase):
    def batch_result(self, argv):
        self.assertEqual(argv[1], "batch")
        self.assertNotIn("--language", argv)
        self.assertNotIn("--stream", argv)
        self.assertEqual(argv[argv.index("--seed") + 1], "30000005")
        lines = Path(argv[argv.index("--file") + 1]).read_text().splitlines()
        destination = Path(argv[argv.index("--out-dir") + 1])
        items = []
        for index, text in enumerate(lines):
            path = destination / f"fixture_custom_{index:03d}.wav"
            with wave.open(str(path), "wb") as audio:
                audio.setparams((1, 2, 24000, 0, "NONE", "not compressed"))
                audio.writeframes(b"\x10\x00" * 24000)
            items.append({"index": index, "text": text, "audioPath": str(path),
                          "durationSeconds": 1.0, "finishReason": "eos"})
        return {"mode": "custom", "variant": "speed", "modelID": "pro_custom_speed",
                "count": len(items), "wallSeconds": 2.0, "items": items}

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.source = self.root / "source"
        resources = self.source / "Sources/Resources"
        resources.mkdir(parents=True)
        self.products = self.root / "products"
        self.products.mkdir()
        self.output = self.root / "Copy with spaces"
        self.release = package.identity("3.0.0", "24", "a" * 40)
        self.attribution = {"licenses": [{"id": "MIT", "text": "license text"}],
                            "components": [{"id": "fixture", "displayName": "Fixture", "licenseID": "MIT",
                                            "notice": "Required NOTICE", "copyrightNotice": "Copyright fixture"}]}
        (resources / "third_party_attributions.json").write_text(json.dumps(self.attribution))
        (self.source / "LICENSE").write_text("Project license")
        for name in package.CATALOGS:
            content = json.dumps({"speakers": {"Built-in": ["fixture"]}})
            (resources / name).write_text(content)
            (self.products / name).write_text(content)
        (self.products / "vocello").write_bytes(b"fixture executable")
        (self.products / "vocello").chmod(0o755)
        for bundle in package.BUNDLES:
            directory = self.products / bundle / "Contents/Resources"
            directory.mkdir(parents=True)
            (directory / "default.metallib").write_bytes(b"resource")
        package.stage(self.products, self.output, self.source)
        package.seal(self.output, self.release)

    def tearDown(self):
        self.temporary.cleanup()

    def test_complete_payload_notice_and_relative_inventory(self):
        result = package.verify(self.output, self.release)
        self.assertNotIn(str(self.root), json.dumps(result))
        self.assertIn("Required NOTICE", (self.output / "THIRD-PARTY-NOTICES.txt").read_text())
        self.assertIn("license text", (self.output / "THIRD-PARTY-NOTICES.txt").read_text())
        self.assertFalse(any(item["name"].endswith(".safetensors") for item in result["files"]))

    def test_stage_refuses_existing_output(self):
        with self.assertRaises(ValueError):
            package.stage(self.products, self.output, self.source)
        package.verify(self.output, self.release)

    def test_stage_rejects_stale_built_catalog(self):
        (self.products / package.CATALOGS[0]).write_text("{}")
        with self.assertRaises(ValueError):
            package.stage(self.products, self.root / "new", self.source)
        self.assertFalse((self.root / "new").exists())

    def test_packager_explicitly_stages_tool_catalog_resources(self):
        for name in package.CATALOGS:
            (self.products / name).unlink()
        directory = self.root / "new"
        package.stage(self.products, directory, self.source)
        for name in package.CATALOGS:
            self.assertEqual(package.digest(directory / name), package.digest(self.source / "Sources/Resources" / name))

    def test_missing_bundle_and_shader_fail(self):
        shader = self.output / package.BUNDLES[0] / "Contents/Resources/default.metallib"
        shader.unlink()
        with self.assertRaises(ValueError):
            package.verify(self.output, self.release)

    def test_only_adhoc_resource_signature_may_be_empty(self):
        signature = self.output / package.BUNDLES[0] / "Contents/_CodeSignature/CodeSignature"
        signature.parent.mkdir()
        signature.write_bytes(b"")
        package.seal(self.output, self.release)
        package.verify(self.output, self.release)
        (self.output / package.BUNDLES[0] / "Contents/Resources/default.metallib").write_bytes(b"")
        with self.assertRaises(ValueError):
            package.seal(self.output, self.release)

    def test_changed_audio_or_extra_model_file_cannot_enter_package(self):
        (self.output / "model.safetensors").write_bytes(b"not authorized")
        with self.assertRaises(ValueError):
            package.seal(self.output, self.release)

    def test_tamper_and_permission_changes_fail(self):
        binary = self.output / "vocello"
        binary.chmod(0o644)
        with self.assertRaises(ValueError):
            package.verify(self.output, self.release)
        binary.chmod(0o755)
        binary.write_bytes(b"changed")
        with self.assertRaises(ValueError):
            package.verify(self.output, self.release)

    def test_symlink_and_nested_executable_fail(self):
        resource = self.output / package.BUNDLES[0] / "Contents/Resources/extra"
        resource.symlink_to(self.products / "vocello")
        with self.assertRaises(ValueError):
            package.seal(self.output, self.release)
        resource.unlink()
        resource.write_bytes(bytes.fromhex("cffaedfe") + b"executable")
        with self.assertRaises(ValueError):
            package.seal(self.output, self.release)

    def test_corrupted_json_and_identity_drift_fail(self):
        with self.assertRaises(ValueError):
            package.verify(self.output, {**self.release, "commitSHA": "b" * 40})
        (self.output / package.MANIFEST).write_text("{")
        with self.assertRaises(ValueError):
            package.verify(self.output, self.release)

    def test_interrupted_atomic_seal_preserves_previous_bytes(self):
        before = (self.output / package.MANIFEST).read_bytes()
        with mock.patch.object(package.os, "replace", side_effect=OSError("interrupted")):
            with self.assertRaises(OSError):
                package.seal(self.output, self.release)
        self.assertEqual((self.output / package.MANIFEST).read_bytes(), before)
        self.assertFalse(list(self.output.glob(".cli-json-*")))

    def test_notice_override_and_manifest_disagreement(self):
        document = copy.deepcopy(self.attribution)
        document["components"][0]["licenseTextOverride"] = "specific license"
        self.assertIn("specific license", package.notices(document))
        (self.output / "THIRD-PARTY-NOTICES.txt").write_text("missing required text")
        package.seal(self.output, self.release)
        with self.assertRaises(ValueError):
            package.verify(self.output, self.release)

    def test_embedded_plist_decode_and_invalid_dump(self):
        info = {"CFBundleVersion": "24", "CFBundleShortVersionString": "3.0.0"}
        self.assertEqual(package.embedded_info(plist_dump(info)), info)
        with self.assertRaises(ValueError):
            package.embedded_info("not a plist")

    def fake_command(self, argv, cwd, environment, expected=0):
        self.assertNotEqual(cwd, self.output)
        self.assertNotIn("DYLD_LIBRARY_PATH", environment)
        self.assertNotIn("QWENVOICE_DEBUG", environment)
        if argv[0].endswith("lipo"):
            return "arm64\n"
        if argv[0].endswith("otool"):
            if "-L" in argv:
                return "binary:\n\t/usr/lib/libSystem.B.dylib (compatibility version 1.0.0)\n"
            return plist_dump({"CFBundleVersion": "24", "CFBundleShortVersionString": "3.0.0"})
        if argv[1] in {"--version", "version", "-v"}:
            return "vocello 3.0.0\n"
        if argv[1] == "modes":
            return json.dumps([{"mode": mode} for mode in ("custom", "design", "clone")])
        if argv[1] == "speakers":
            self.assertIn("--data-dir", argv)
            return '[{"id":"fixture"}]'
        self.assertEqual(argv[1], "unknown-package-smoke-command")
        self.assertEqual(expected, 2)
        return ""

    def test_smoke_only_runs_discovery_in_isolated_working_directory(self):
        with mock.patch.object(package, "command", side_effect=self.fake_command) as runner:
            report = package.smoke(self.output, self.release)
        self.assertEqual(report["generationQualification"], "not-performed")
        self.assertNotIn(str(self.root), json.dumps(report))
        self.assertFalse(any("generate" in call.args[0] for call in runner.call_args_list))

    def test_smoke_rejects_wrong_build_and_dynamic_dependency(self):
        for failure in ("build", "linkage", "arch"):
            def changed(argv, cwd, environment, expected=0):
                if failure == "build" and "__info_plist" in argv:
                    return plist_dump({"CFBundleVersion": "23", "CFBundleShortVersionString": "3.0.0"})
                if failure == "linkage" and "-L" in argv:
                    return "binary:\n\t@rpath/unbundled.dylib (version)\n"
                if failure == "arch" and "-archs" in argv:
                    return "arm64 x86_64\n"
                return self.fake_command(argv, cwd, environment, expected)
            with self.subTest(failure=failure), mock.patch.object(package, "command", side_effect=changed):
                with self.assertRaises(ValueError):
                    package.smoke(self.output, self.release)

    def test_qualification_runs_all_modes_serially_and_redacts_private_paths(self):
        model_store = self.root / "model store"
        model_store.mkdir()
        reference = self.root / "private reference.wav"
        reference.write_bytes(b"RIFF" + b"\0" * 4 + b"WAVE" + b"fixture audio" * 8)
        calls = []

        def generate(argv, cwd, environment, timeout):
            calls.append((list(argv), cwd, dict(environment), timeout))
            if argv[1] == "batch":
                return self.batch_result(argv)
            mode = argv[argv.index("--mode") + 1]
            language = argv[argv.index("--language") + 1]
            output = Path(argv[argv.index("--out") + 1])
            output.write_bytes(b"RIFF" + b"\0" * 4 + b"WAVE" + b"generated audio" * 8)
            return {
                "audioPath": str(output),
                "audioQC": {"verdict": "pass"},
                "durationSeconds": 1.25,
                "finalModelLanguage": language,
                "finishReason": "eos",
                "mode": mode,
                "modelID": f"pro_{mode}_speed",
                "variant": "speed",
            }

        def cancel(argv, cwd, environment, timeout):
            calls.append((list(argv), cwd, dict(environment), timeout))
            return {"generationStartObserved": True, "exitStatus": 130, "cleanupAcknowledged": True}

        with mock.patch.object(package, "command", return_value="") as failure_runner:
            report = package.qualify(
                self.output, self.release, model_store, reference,
                generation_runner=generate, cancellation_runner=cancel,
            )

        self.assertEqual([row["mode"] for row in report["runs"]], ["custom", "design", "clone"])
        self.assertEqual(report["cancellation"]["exitStatus"], 130)
        self.assertTrue(report["serialExecution"])
        self.assertEqual(failure_runner.call_count, 2)
        self.assertNotIn(str(self.root), json.dumps(report))
        self.assertTrue(all("QWENVOICE_DEBUG" not in call[2] for call in calls))
        self.assertTrue(all(call[3] == 900 for call in calls))
        self.assertNotIn("--transcript", calls[2][0])
        self.assertEqual(report["runs"][0]["requestedSeed"], "30000001")
        self.assertNotIn("seed", report["runs"][0])
        self.assertEqual(report["schemaVersion"], 2)
        self.assertEqual(report["batch"]["count"], 2)
        self.assertEqual(report["batch"]["pcmIntegrity"], "passed")
        self.assertEqual([call[0][1] for call in calls], ["generate", "generate", "generate", "batch", "generate"])

        def failed_batch(argv, cwd, environment, timeout):
            if argv[1] == "batch":
                result = self.batch_result(argv)
                result["count"] = 1
                return result
            return generate(argv, cwd, environment, timeout)

        retained_batch = self.root / "batch-failure.json"
        with mock.patch.object(package, "command", return_value=""):
            with self.assertRaisesRegex(ValueError, "two successful rows"):
                package.qualify(self.output, self.release, model_store, reference,
                                report=retained_batch, generation_runner=failed_batch,
                                cancellation_runner=lambda *_: self.fail("No next process after batch failure"))
        failed = json.loads(retained_batch.read_text())
        self.assertEqual(failed["stage"], "batch")
        self.assertEqual(failed["status"], "failed")
        self.assertEqual(len(failed["runs"]), 3)
        self.assertEqual(len(list((retained_batch.parent / failed["artifactDirectory"] / "qualification outputs/batch").glob("*.wav"))), 2)
        self.assertNotIn(str(self.root), retained_batch.read_text())

        for leftover in ("final", "staging"):
            retained = self.root / f"{leftover}-failure.json"
            leftovers = []
            def dirty_cancel(argv, cwd, environment, timeout):
                output = Path(argv[argv.index("--out") + 1])
                target = output if leftover == "final" else output.parent / ".cancelled.fixture.tmp.wav"
                target.write_bytes(b"must remain forensic evidence")
                leftovers.append(target)
                return {"generationStartObserved": True, "exitStatus": 130, "cleanupAcknowledged": True}
            with mock.patch.object(package, "command", return_value=""):
                with self.assertRaisesRegex(ValueError, "left output/staging"):
                    package.qualify(self.output, self.release, model_store, reference,
                                    report=retained, generation_runner=generate, cancellation_runner=dirty_cancel)
            self.assertEqual(leftovers[0].read_bytes(), b"must remain forensic evidence")
            self.assertEqual(json.loads(retained.read_text())["status"], "failed")

    def test_qualification_retains_failure_and_refuses_report_reuse(self):
        model_store = self.root / "model store"
        model_store.mkdir()
        reference = self.root / "reference.wav"
        reference.write_bytes(b"RIFF" + b"\0" * 4 + b"WAVE" + b"fixture audio" * 8)
        transcript = self.root / "private.txt"
        transcript.write_text("The reviewed reference words.")
        report = self.root / "qualification.json"

        def fail(argv, _cwd, _environment, _timeout):
            self.assertEqual(argv[argv.index("--transcript") + 1], transcript.read_text())
            raise ValueError("private raw error")

        # Reach the Clone cell after two valid synthetic predecessors.
        def generate(argv, cwd, environment, timeout):
            mode = argv[argv.index("--mode") + 1]
            if mode == "clone":
                return fail(argv, cwd, environment, timeout)
            output = Path(argv[argv.index("--out") + 1])
            output.write_bytes(b"RIFF" + b"\0" * 4 + b"WAVE" + b"audio" * 32)
            return {"audioPath": str(output), "audioQC": {"verdict": "pass"},
                    "durationSeconds": 1, "finalModelLanguage": argv[argv.index("--language") + 1],
                    "finishReason": "eos", "mode": mode, "variant": "speed", "modelID": f"pro_{mode}_speed"}

        with self.assertRaises(ValueError):
            package.qualify(self.output, self.release, model_store, reference,
                            clone_transcript=transcript, report=report, generation_runner=generate)
        saved = json.loads(report.read_text())
        self.assertEqual(saved["status"], "failed")
        self.assertEqual(saved["stage"], "clone")
        self.assertEqual(len(saved["runs"]), 2)
        self.assertTrue((report.parent / saved["artifactDirectory"] / "qualification outputs/custom.wav").is_file())
        for private in (str(self.root), "private raw error", transcript.read_text()):
            self.assertNotIn(private, report.read_text())
        with self.assertRaisesRegex(ValueError, "overwrite"):
            package.qualify(self.output, self.release, model_store, reference, report=report,
                            generation_runner=generate)

    def test_batch_qualification_rejects_missing_mismatched_and_invalid_outputs(self):
        faults = ["count", "schema", "missing-row", "order", "text", "duplicate", "missing-file",
                  "symlink", "outside", "nan", "duration", "finish", "pcm", "silent", "truncated", "staging"]
        for fault in faults:
            with self.subTest(fault=fault):
                work = self.root / fault
                work.mkdir()
                def generate(argv, _cwd, _environment, _timeout):
                    result = self.batch_result(argv)
                    item = result["items"][1]
                    path = Path(item["audioPath"])
                    if fault == "count": result["count"] = 1
                    elif fault == "schema": result["schemaVersion"] = 2
                    elif fault == "missing-row": result["items"].pop()
                    elif fault == "order": result["items"].reverse()
                    elif fault == "text": item["text"] = "different input"
                    elif fault == "duplicate": item["audioPath"] = result["items"][0]["audioPath"]
                    elif fault == "missing-file": path.unlink()
                    elif fault == "symlink":
                        path.unlink()
                        path.symlink_to(result["items"][0]["audioPath"])
                    elif fault == "outside":
                        outside = work / "outside.wav"
                        path.rename(outside)
                        item["audioPath"] = str(outside)
                    elif fault == "nan": item["durationSeconds"] = float("nan")
                    elif fault == "duration": item["durationSeconds"] = 2.0
                    elif fault == "finish": item["finishReason"] = "cancelled"
                    elif fault == "pcm": path.write_bytes(b"not a WAV")
                    elif fault == "silent": path.write_bytes(path.read_bytes()[:44] + b"\0" * 48000)
                    elif fault == "truncated": path.write_bytes(path.read_bytes()[:-2])
                    elif fault == "staging": (path.parent / ".leftover.tmp.wav").write_bytes(b"owned staging")
                    return result
                runner = mock.Mock(side_effect=generate)
                with self.assertRaises(ValueError):
                    package.qualify_batch("copied/vocello", work, work, work, {}, runner)
                self.assertEqual(runner.call_count, 1, "Never retry a failed batch")
                self.assertTrue((work / "batch/fixture_custom_000.wav").is_file())

    def test_failed_batch_subprocess_retains_raw_rows_without_exposing_them(self):
        rows = json.dumps({"schemaVersion": 2, "items": [{"audioPath": "private/path"}]})
        process = mock.Mock(returncode=1)
        process.communicate.return_value = (rows, "private error")
        with mock.patch.object(package.subprocess, "Popen", return_value=process):
            with self.assertRaisesRegex(ValueError, "CLI qualification generation failed"):
                package._run_qualification_generation(["vocello", "batch"], self.root, {})
        self.assertEqual((self.root / "batch-result.json").read_text(), rows)

    def test_batch_command_uses_policy_tested_production_builder(self):
        root = Path(__file__).resolve().parents[2]
        command = (root / "Sources/VocelloCLI/BatchCommand.swift").read_text()
        self.assertIn("CLIBatchExecution.makeRequests(", command)
        self.assertNotIn("GenerationRequest(", command)
        self.assertNotIn("request.batchIndex", command)

    def test_cancellation_observes_unterminated_progress_line(self):
        code = "import os,signal,time; signal.signal(signal.SIGINT, lambda *_: (os.write(2,b'Cancelled; command cleanup completed.'),os._exit(130))); os.write(2,b'generating (fixture)'); time.sleep(30)"
        result = package._run_qualification_cancellation(
            [sys.executable, "-c", code], self.root, dict(os.environ), 3)
        self.assertEqual(result, {"generationStartObserved": True, "exitStatus": 130, "cleanupAcknowledged": True})

    def test_forced_signal_exit_is_not_clean_cancellation(self):
        code = "import os,signal,time; signal.signal(signal.SIGINT, lambda *_: os._exit(130)); os.write(2,b'generating (fixture)'); time.sleep(30)"
        with self.assertRaisesRegex(ValueError, "terminate cleanly"):
            package._run_qualification_cancellation(
                [sys.executable, "-c", code], self.root, dict(os.environ), 3)

    def test_partial_progress_timeout_terminates_process(self):
        with self.assertRaisesRegex(ValueError, "did not reach generation"):
            package._run_qualification_cancellation(
                [sys.executable, "-c", "import os,time; os.write(2,b'loading'); time.sleep(30)"],
                self.root, dict(os.environ), 0.2)

    def test_generation_timeout_cleans_up_process_group(self):
        process = mock.Mock(pid=987654)
        process.communicate.side_effect = [subprocess.TimeoutExpired("private", 1), ("", "")]
        with mock.patch.object(package.subprocess, "Popen", return_value=process), \
             mock.patch.object(package.os, "killpg") as kill:
            with self.assertRaises(subprocess.TimeoutExpired):
                package._run_qualification_generation(["fixture"], self.root, {}, 1)
        kill.assert_called_once_with(process.pid, signal.SIGKILL)
        self.assertEqual(process.communicate.call_count, 2)

    def test_qualification_rejects_hard_qc_failure(self):
        model_store = self.root / "model store"
        model_store.mkdir()
        reference = self.root / "reference.wav"
        reference.write_bytes(b"RIFF" + b"\0" * 4 + b"WAVE" + b"fixture audio" * 8)

        def failed_qc(argv, _cwd, _environment, _timeout):
            output = Path(argv[argv.index("--out") + 1])
            output.write_bytes(b"RIFF" + b"\0" * 4 + b"WAVE" + b"generated audio" * 8)
            return {
                "audioPath": str(output), "audioQC": {"verdict": "fail"},
                "durationSeconds": 1.0, "finalModelLanguage": "english",
                "finishReason": "eos", "mode": "custom",
                "modelID": "pro_custom_speed", "variant": "speed",
            }

        with self.assertRaisesRegex(ValueError, "QC verdict"):
            package.qualify(
                self.output, self.release, model_store, reference,
                generation_runner=failed_qc,
                cancellation_runner=lambda *_args: {},
            )

    def test_qualification_rejects_warning_or_wrong_model_identity(self):
        model_store = self.root / "model store"
        model_store.mkdir()
        reference = self.root / "reference.wav"
        reference.write_bytes(b"RIFF" + b"\0" * 4 + b"WAVE" + b"fixture audio" * 8)

        def result_with(*, verdict="pass", model_id="pro_custom_speed"):
            def generate(argv, _cwd, _environment, _timeout):
                output = Path(argv[argv.index("--out") + 1])
                output.write_bytes(b"RIFF" + b"\0" * 4 + b"WAVE" + b"generated audio" * 8)
                return {
                    "audioPath": str(output), "audioQC": {"verdict": verdict},
                    "durationSeconds": 1.0, "finalModelLanguage": "english",
                    "finishReason": "eos", "mode": "custom",
                    "modelID": model_id, "variant": "speed",
                }
            return generate

        with self.assertRaisesRegex(ValueError, "passing QC verdict"):
            package.qualify(
                self.output, self.release, model_store, reference,
                generation_runner=result_with(verdict="warn"),
                cancellation_runner=lambda *_args: {},
            )
        with self.assertRaisesRegex(ValueError, "identity mismatch"):
            package.qualify(
                self.output, self.release, model_store, reference,
                generation_runner=result_with(model_id="unexpected_model"),
                cancellation_runner=lambda *_args: {},
            )

    def test_subprocess_failure_is_redacted_and_timeout_not_waived(self):
        result = subprocess.CompletedProcess([], 1, "private output", "private path")
        with mock.patch.object(package.subprocess, "run", return_value=result):
            with self.assertRaisesRegex(ValueError, "unexpected exit status"):
                package.command(["fixture"], self.root, {})
        with mock.patch.object(package.subprocess, "run", side_effect=subprocess.TimeoutExpired("fixture", 60)):
            with self.assertRaises(subprocess.TimeoutExpired):
                package.command(["fixture"], self.root, {})

    def test_release_report_binds_exact_dmg_and_rejects_quality_claim(self):
        with mock.patch.object(package, "command", side_effect=self.fake_command):
            report = package.smoke(self.output, self.release)
        artifact = {"name": "Vocello-macos26-cli.dmg", "bytes": 123, "sha256": "b" * 64}
        report["artifact"] = artifact
        release_evidence.validate_cli_artifact_verification(report, self.release, [artifact])
        for altered in ({**artifact, "sha256": "c" * 64}, {**artifact, "name": "other-cli.dmg"}):
            with self.assertRaises(ValueError):
                release_evidence.validate_cli_artifact_verification(report, self.release, [altered])
        report["generationQualification"] = "passed"
        with self.assertRaises(ValueError):
            release_evidence.validate_cli_artifact_verification(report, self.release, [artifact])

    def test_workflow_binds_both_dmgs_and_managed_cli_report(self):
        root = Path(__file__).resolve().parents[2]
        workflow = (root / ".github/workflows/release.yml").read_text()
        self.assertGreaterEqual(workflow.count("${{ steps.artifacts.outputs.cli_dmg }}"), 5)
        self.assertGreaterEqual(workflow.count("${{ steps.artifacts.outputs.cli_verification }}"), 4)
        variants = json.loads((root / "config/orchestration-contract.json").read_text())["workflows"]["release-macos-candidate"]["commandTemplates"]["artifact-verification"]
        self.assertEqual(len(variants), 2)
        current = next(item for item in variants if item["argv"][-1] == "--include-cli")
        self.assertEqual(current["outputs"], ["build/dist/macos/cli-package-verification.json"])
        self.assertIn("macos-artifact-verification-v1", {item["id"] for item in variants})


if __name__ == "__main__":
    unittest.main()
