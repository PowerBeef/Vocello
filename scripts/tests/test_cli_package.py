from __future__ import annotations

import copy
import io
import json
import os
from contextlib import redirect_stdout
from pathlib import Path
import plistlib
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import unittest
import wave
from unittest import mock
import xml.etree.ElementTree as ElementTree

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import cli_package as package
import release_evidence

REPOSITORY = Path(__file__).resolve().parents[2]


def plist_dump(info: dict) -> str:
    data = plistlib.dumps(info)
    data += b"\0" * (-len(data) % 4)
    return "\n".join(f"{index:016x}\t{int.from_bytes(data[index:index+4], 'little'):08x}" for index in range(0, len(data), 4))


# What pkgbuild writes for this package (recorded with Xcode 27.1's pkgbuild, InstallCmds-883).
PACKAGE_INFO = """<?xml version="1.0" encoding="utf-8"?>
<pkg-info overwrite-permissions="true" relocatable="false" identifier="com.qwenvoice.cli" postinstall-action="none" version="{version}" format-version="2" generator-version="InstallCmds-883 (26A434)" install-location="{location}" auth="root">
    <payload numberOfFiles="20" installKBytes="1"/>
{bundles}
    <bundle-version/>
    <upgrade-bundle>
{identifiers}
    </upgrade-bundle>
    <update-bundle/>
    <atomic-update-bundle/>
    <strict-identifier>
{identifiers}
    </strict-identifier>
    <relocate{relocate}
    <scripts>
        <preinstall file="./preinstall" timeout="600"/>
{postinstall}
    </scripts>
</pkg-info>
"""

# The Distribution productbuild writes into the product from distribution_xml().
PRODUCT_DISTRIBUTION = """<?xml version="1.0" encoding="utf-8" standalone="yes"?>
<installer-gui-script minSpecVersion="2">
    <title>Vocello CLI</title>
    <readme file="README.txt"/>
    <license file="LICENSE.txt"/>
    <options customize="never" require-scripts="false" hostArchitectures="arm64"/>
    <domains enable_anywhere="false" enable_currentUserHome="false" enable_localSystem="true"/>
    <volume-check>
        <allowed-os-versions>
            <os-version min="26.0"/>
        </allowed-os-versions>
    </volume-check>
    <choices-outline>
        <line choice="com.qwenvoice.cli"/>
    </choices-outline>
    <choice id="com.qwenvoice.cli" visible="false" title="Vocello CLI">
        <pkg-ref id="com.qwenvoice.cli"/>
    </choice>
    <pkg-ref id="com.qwenvoice.cli" version="3.0.0" onConclusion="none" installKBytes="3" updateKBytes="0">#vocello-cli.pkg</pkg-ref>
    <pkg-ref id="com.qwenvoice.cli">
        <bundle-version>
            <bundle id="fixture.GRDB_GRDB.resources" path="GRDB_GRDB.bundle"/>
        </bundle-version>
    </pkg-ref>
</installer-gui-script>
"""

SAMPLE_LOAD_COMMANDS = """vocello:
Load command 10
      cmd LC_UUID
  cmdsize 24
    uuid 1AD9BA78-7CAE-34DD-8444-2D2F930F9271
Load command 11
      cmd LC_BUILD_VERSION
  cmdsize 32
 platform 1
    minos 26.0
      sdk 27.0
   ntools 1
     tool 3
  version 27037.1
Load command 12
      cmd LC_SOURCE_VERSION
  cmdsize 16
  version 0.0
"""


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
            # Like Xcode's SwiftPM resource bundles; pkgbuild accepts only real bundles.
            (directory.parent / "Info.plist").write_bytes(plistlib.dumps(
                {"CFBundleIdentifier": f"fixture.{bundle.removesuffix('.bundle')}.resources",
                 "CFBundlePackageType": "BNDL"}))
        # The package carries the repository's own completion and uninstaller.
        for relative in (package.COMPLETION_SOURCE, package.UNINSTALLER_SOURCE):
            (self.source / relative).parent.mkdir(parents=True, exist_ok=True)
            (self.source / relative).write_bytes((REPOSITORY / relative).read_bytes())
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
            # A v1 envelope here, today's bare array for speakers: the reader takes both.
            return json.dumps({
                "schemaVersion": 1, "ok": True, "command": "modes.list", "requestID": "fixture",
                "result": {"modes": [{"mode": mode} for mode in ("custom", "design", "clone")]},
                "error": None, "warnings": [],
                "meta": {"vocelloVersion": "3.0.0", "build": "24", "contractRevision": 1, "durationMs": 1,
                         "replayed": False},
            })
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
            # The probe's script must be one take the CLI accepts (900 characters at most).
            self.assertLessEqual(len(argv[argv.index("--text") + 1]), 900)
            self.assertIn("--ndjson", argv)
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

    # A fake CLI: a `generation_started` record (unterminated), then on SIGINT the final
    # result record with the cancellation envelope, or a bare exit.
    CANCELLED_RESULT = json.dumps({
        "schemaVersion": 1, "seq": 1, "t": 0.5, "requestID": "fixture", "type": "result",
        "data": {"schemaVersion": 1, "ok": False, "command": "generate", "requestID": "fixture", "result": None,
                 "error": {"code": "cancelled", "category": "cancelled", "exitCode": 130,
                           "message": "cancelled by SIGINT; command cleanup completed", "retryable": False,
                           "retryAfterMs": None, "hint": None, "detail": {"signal": "SIGINT"}},
                 "warnings": [], "meta": {"vocelloVersion": "3.0.0", "build": "24", "contractRevision": 1,
                                          "durationMs": 500, "replayed": False}},
    })

    def fake_cancellable_cli(self, on_interrupt: str) -> list[str]:
        started = '{"schemaVersion":1,"seq":0,"t":0,"requestID":"fixture","type":"generation_started","data":{}}'
        code = (f"import os,signal,time; signal.signal(signal.SIGINT, lambda *_: ({on_interrupt}, os._exit(130))); "
                f"os.write(1, {started.encode()!r}); time.sleep(30)")
        return [sys.executable, "-c", code]

    def test_cancellation_observes_the_generation_started_event(self):
        result = package._run_qualification_cancellation(
            self.fake_cancellable_cli(f"os.write(1, b'\\n' + {self.CANCELLED_RESULT.encode()!r} + b'\\n')"),
            self.root, dict(os.environ), 3)
        self.assertEqual(result, {"generationStartObserved": True, "exitStatus": 130, "cleanupAcknowledged": True})

    def test_an_exit_without_the_cancellation_envelope_is_not_clean(self):
        for on_interrupt in ("None", "os.write(2, b'forced exit')",
                             f"os.write(1, b'\\n' + {self.CANCELLED_RESULT.replace('SIGINT', 'SIGTERM').encode()!r})"):
            with self.subTest(on_interrupt=on_interrupt), self.assertRaisesRegex(ValueError, "terminate cleanly"):
                package._run_qualification_cancellation(
                    self.fake_cancellable_cli(on_interrupt), self.root, dict(os.environ), 3)

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
        self.assertEqual(len(variants), 3)
        for current in (item for item in variants if "--include-cli" in item["argv"]):
            self.assertEqual(current["outputs"], ["build/dist/macos/cli-package-verification.json"])
        self.assertIn("--include-pkg", variants[0]["argv"])
        self.assertIn("macos-artifact-verification-v1", {item["id"] for item in variants})

    def test_stage_adds_completion_and_uninstaller_as_plain_data(self):
        manifest = package.verify(self.output, self.release)
        rows = {row["name"]: row for row in manifest["files"]}
        for name, source in ((package.COMPLETION, package.COMPLETION_SOURCE),
                             (package.UNINSTALLER, package.UNINSTALLER_SOURCE)):
            with self.subTest(name=name):
                self.assertEqual((self.output / name).read_bytes(), (REPOSITORY / source).read_bytes())
                self.assertEqual(stat.S_IMODE((self.output / name).stat().st_mode), 0o644)
                self.assertFalse(rows[name]["executable"])
        self.assertEqual([name for name, row in rows.items() if row["executable"]], ["vocello"])
        readme = (self.output / "README.txt").read_text()
        for route in ("sudo sh /usr/local/lib/vocello/uninstall.sh", "/usr/local/bin/vocello mcp",
                      '"/your/chosen/Vocello CLI/vocello" --version'):
            self.assertIn(route, readme)
        # The uninstaller runs through `sh`; an executable copy would be a second entry point.
        (self.output / package.UNINSTALLER).chmod(0o755)
        with self.assertRaisesRegex(ValueError, "executable"):
            package.seal(self.output, self.release)
        (self.output / package.UNINSTALLER).chmod(0o644)
        (self.output / package.COMPLETION).unlink()
        with self.assertRaisesRegex(ValueError, "missing required files"):
            package.seal(self.output, self.release)

    def test_smoke_runs_the_cli_through_a_launcher_link(self):
        links = self.root / "bin with spaces"
        links.mkdir()
        launcher = links / "vocello"
        launcher.symlink_to(os.path.relpath(self.output / "vocello", links))
        seen = []

        def record(argv, cwd, environment, expected=0):
            seen.append(list(argv))
            return self.fake_command(argv, cwd, environment, expected)

        with mock.patch.object(package, "command", side_effect=record):
            package.smoke(self.output, self.release, launcher=launcher)
        executable = str((self.output / "vocello").resolve())
        inspected = [argv for argv in seen if argv[0] in ("/usr/bin/lipo", "/usr/bin/otool")]
        self.assertEqual(len(inspected), 3)
        self.assertTrue(all(argv[-1] == executable for argv in inspected))
        self.assertEqual({argv[0] for argv in seen if argv not in inspected}, {str(launcher)})

        copy_launcher = links / "copied vocello"
        shutil.copyfile(self.output / "vocello", copy_launcher)
        elsewhere = links / "other"
        elsewhere.symlink_to(self.output / "README.txt")
        for bad in (Path("bin with spaces/vocello"), copy_launcher, elsewhere):
            with self.subTest(launcher=bad.name), mock.patch.object(package, "command", side_effect=record):
                with self.assertRaisesRegex(ValueError, "launcher"):
                    package.smoke(self.output, self.release, launcher=bad)

    def test_qualification_runs_the_cli_through_a_launcher_link(self):
        model_store = self.root / "model store"
        model_store.mkdir()
        reference = self.root / "reference.wav"
        reference.write_bytes(b"RIFF" + b"\0" * 4 + b"WAVE" + b"fixture audio" * 8)
        launcher = self.root / "vocello link"
        launcher.symlink_to(self.output / "vocello")
        launched = []

        def generate(argv, _cwd, _environment, _timeout):
            launched.append(argv[0])
            if argv[1] == "batch":
                return self.batch_result(argv)
            output = Path(argv[argv.index("--out") + 1])
            output.write_bytes(b"RIFF" + b"\0" * 4 + b"WAVE" + b"generated audio" * 8)
            mode = argv[argv.index("--mode") + 1]
            return {"audioPath": str(output), "audioQC": {"verdict": "pass"}, "durationSeconds": 1.0,
                    "finalModelLanguage": argv[argv.index("--language") + 1], "finishReason": "eos",
                    "mode": mode, "modelID": f"pro_{mode}_speed", "variant": "speed"}

        def cancel(argv, _cwd, _environment, _timeout):
            launched.append(argv[0])
            return {"generationStartObserved": True, "exitStatus": 130, "cleanupAcknowledged": True}

        def failure(argv, *_args, **_kwargs):
            launched.append(argv[0])
            return ""

        with mock.patch.object(package, "command", side_effect=failure):
            package.qualify(self.output, self.release, model_store, reference, generation_runner=generate,
                            cancellation_runner=cancel, launcher=launcher)
        self.assertEqual(len(launched), 7)
        self.assertEqual(set(launched), {str(launcher)})


class CLIInstallerPackageTests(unittest.TestCase):
    """`pkg` and `pkg-verify` over the same sealed fixture folder."""

    # Set by the shared setUp.
    root: Path
    output: Path
    release: dict
    setUp = CLIPackageTests.setUp
    tearDown = CLIPackageTests.tearDown
    fake_command = CLIPackageTests.fake_command

    def identifiers(self) -> dict[str, str]:
        return {bundle: f"fixture.{bundle.removesuffix('.bundle')}.resources" for bundle in package.BUNDLES}

    def package_info(self, *, version="3.0.0", location=package.INSTALL_LOCATION, relocate="/>",
                     postinstall='        <postinstall file="./postinstall" timeout="600"/>') -> str:
        identifiers = self.identifiers()
        return PACKAGE_INFO.format(
            version=version, location=location, relocate=relocate, postinstall=postinstall,
            bundles="\n".join(f'    <bundle id="{name}" path="./{bundle}"/>' for bundle, name in identifiers.items()),
            identifiers="\n".join(f'        <bundle id="{name}"/>' for name in identifiers.values()))

    def expand_fixture(self, name: str, *, distribution: bytes | None = None,
                       package_info: str | None = None) -> tuple[Path, Path]:
        """A tree shaped like `pkgutil --expand-full` of the product, built without pkgbuild."""
        expanded = self.root / name
        component = expanded / package.COMPONENT
        component.mkdir(parents=True)
        payload = component / "Payload"
        package._copy_payload(self.output, payload)
        (expanded / "Distribution").write_bytes(distribution or PRODUCT_DISTRIBUTION.encode())
        (expanded / "Resources").mkdir()
        shutil.copyfile(payload / "README.txt", expanded / "Resources/README.txt")
        shutil.copyfile(payload / "LICENSE", expanded / "Resources/LICENSE.txt")
        (component / "Scripts").mkdir()
        for script, source in package.PKG_SCRIPT_SOURCES.items():
            shutil.copyfile(REPOSITORY / source, component / "Scripts" / script)
            (component / "Scripts" / script).chmod(0o755)
        (component / "PackageInfo").write_text(package_info or self.package_info(), encoding="utf-8")
        (component / "Bom").write_bytes(b"BOMStore fixture")
        artifact = expanded.parent / f"{name}-Vocello-macos26-cli.pkg"
        artifact.write_bytes(b"xar! fixture product")
        return expanded, artifact

    @staticmethod
    def bom_rows(payload: Path) -> list[list]:
        rows: list[list] = [[".", 0, 0, 0o40755]]
        for path in sorted(payload.rglob("*")):
            relative = "./" + path.relative_to(payload).as_posix()
            rows.append([relative, 0, 0, 0o40755 if path.is_dir() else 0o100755 if relative == "./vocello" else 0o100644])
        return rows

    def tools(self, payload: Path, *, rows=None, signature="no signature", calls=None):
        """Stand-ins for lsbom, pkgutil --check-signature and stapler."""
        def run(argv, cwd, environment, expected=0, timeout=60):
            if calls is not None:
                calls.append(list(argv))
            if argv[0] == "/usr/bin/lsbom":
                self.assertEqual(argv[1:3], ["-p", "fugm"])
                return "".join(f"{path}\t{uid}\t{gid}\t{mode:o}\n"
                               for path, uid, gid, mode in (rows or self.bom_rows(payload)))
            if argv[:2] == ["/usr/sbin/pkgutil", "--check-signature"]:
                signed = signature != "no signature"
                if expected != (0 if signed else 1):
                    raise ValueError("CLI package subprocess returned an unexpected exit status")
                chain = "   Certificate Chain:\n    1. Developer ID Installer: Fixture (FIXTURE123)\n" if signed else ""
                return f'Package "fixture.pkg":\n   Status: {signature}\n{chain}'
            if argv[:3] == ["/usr/bin/xcrun", "stapler", "validate"]:
                return "The validate action worked!\n"
            raise AssertionError(f"unexpected tool {argv[0]}")
        return run

    def verify_fixture(self, expanded: Path, artifact: Path, *, manifest=None, rows=None,
                       signature="unsigned", notarization="not-performed", status="no signature", calls=None):
        report = expanded.parent / f"{expanded.name}-verification.json"
        tools = self.tools(expanded / package.COMPONENT / "Payload", rows=rows, signature=status, calls=calls)
        with mock.patch.object(package, "binary_minimum_os", return_value="26.0"), \
             mock.patch.object(package, "command", side_effect=tools):
            return package.pkg_verify(
                expanded, artifact, self.release, manifest or package.digest(self.output / package.MANIFEST),
                signature=signature, notarization=notarization, report=report)

    def test_component_plist_keeps_every_bundle_in_place(self):
        rows = plistlib.loads(package.component_plist(self.output))
        self.assertEqual(sorted(row["RootRelativeBundlePath"] for row in rows), sorted(package.BUNDLES))
        for row in rows:
            self.assertEqual({key: value for key, value in row.items() if key != "RootRelativeBundlePath"},
                             {"BundleIsRelocatable": False, "BundleIsVersionChecked": False,
                              "BundleHasStrictIdentifier": True, "BundleOverwriteAction": "upgrade"})
        shutil.rmtree(self.output / package.BUNDLES[0])
        with self.assertRaisesRegex(ValueError, "bundle"):
            package.component_plist(self.output)

    def test_distribution_renders_and_parses_before_and_after_productbuild(self):
        rendered = package.distribution_xml("3.0.0", "26.0")
        self.assertEqual(package.check_distribution(rendered, "3.0.0"), "26.0")
        self.assertEqual(package.check_distribution(PRODUCT_DISTRIBUTION.encode(), "3.0.0"), "26.0")
        script = ElementTree.fromstring(rendered)
        self.assertEqual([node.get("hostArchitectures") for node in script.iter("options")], ["arm64"])
        self.assertEqual([node.attrib for node in script.iter("os-version")], [{"min": "26.0"}])
        self.assertEqual([node.attrib["id"] for node in script.iter("pkg-ref")], [package.PKG_IDENTIFIER] * 2)
        self.assertEqual([node.text for node in script.findall("pkg-ref")], [package.COMPONENT])
        product = PRODUCT_DISTRIBUTION
        faults = {
            "x86_64": (product.replace('hostArchitectures="arm64"', 'hostArchitectures="arm64,x86_64"'), "arm64"),
            "home-domain": (product.replace('enable_currentUserHome="false"', 'enable_currentUserHome="true"'),
                            "startup disk"),
            "any-volume": (product.replace('enable_anywhere="false"', 'enable_anywhere="true"'), "startup disk"),
            "script-element": (product.replace("</installer-gui-script>", "<script>x()</script></installer-gui-script>"),
                               "script-free"),
            "installation-check": (product.replace("<title>", '<installation-check script="x()"/><title>'),
                                   "script-free"),
            # Installer evaluates these attributes as JavaScript.
            "choice-expression": (product.replace('visible="false"', 'visible="false" selected="x()"'),
                                  "script-free"),
            "choice-enabled": (product.replace('visible="false"', 'visible="false" enabled="x()"'), "script-free"),
            "package-active": (product.replace('onConclusion="none"', 'onConclusion="none" active="x()"'),
                               "script-free"),
            "inner-package-active": (product.replace('<pkg-ref id="com.qwenvoice.cli"/>',
                                                     '<pkg-ref id="com.qwenvoice.cli" active="x()"/>'), "script-free"),
            "volume-check-script": (product.replace("<volume-check>", '<volume-check script="x()">'), "script-free"),
            "root-attribute": (product.replace('minSpecVersion="2"', 'minSpecVersion="2" other="x()"'),
                               "script-free"),
            "bundle-attribute": (product.replace('path="GRDB_GRDB.bundle"', 'path="GRDB_GRDB.bundle" active="x()"'),
                                 "script-free"),
            "visible-choice": (product.replace('visible="false"', 'visible="true"'), "hidden, fixed choice"),
            "customizable": (product.replace('customize="never"', 'customize="allow"'), "hidden, fixed choice"),
            "second-package": (product.replace('<pkg-ref id="com.qwenvoice.cli">\n        <bundle-version>',
                                               '<pkg-ref id="com.example.other">\n        <bundle-version>'),
                               "one package"),
            "wrong-version": (product.replace('version="3.0.0"', 'version="2.9.0"'), "release version"),
            "no-minimum": (product.replace('<os-version min="26.0"/>', ""), "minimum macOS"),
            "upper-bound": (product.replace('min="26.0"', 'min="26.0" before="27.0"'), "minimum macOS"),
            "entity": ('<!DOCTYPE x [<!ENTITY a "b">]>' + product.split("?>", 1)[1], "entities"),
        }
        for fault, (text, message) in faults.items():
            with self.subTest(fault=fault), self.assertRaisesRegex(ValueError, message):
                package.check_distribution(text.encode(), "3.0.0")

        # productbuild records a versioned bundle's versions beside its id and path.
        versioned = product.replace('<bundle id=', '<bundle CFBundleShortVersionString="1.2" CFBundleVersion="7" id=')
        self.assertEqual(package.check_distribution(versioned.encode(), "3.0.0"), "26.0")
        # Only plain UTF-8, so the text checked for declarations is the text the parser reads.
        encoded = product.encode()
        for fault, data in {
            "byte-order-mark": b"\xef\xbb\xbf" + encoded,
            "nul": encoded.replace(b"<title>", b"<title>\0"),
            "invalid-utf-8": encoded.replace(b"Vocello CLI</title>", b"Vocello \xe9 CLI</title>"),
            "utf-16": product.encode("utf-16"),
            "utf-16-declared": product.replace('encoding="utf-8"', 'encoding="utf-16"').encode("utf-16-le"),
        }.items():
            with self.subTest(fault=fault), self.assertRaisesRegex(ValueError, "plain UTF-8"):
                package.check_distribution(data, "3.0.0")

    def test_installer_xml_parser_refuses_any_document_type(self):
        self.assertEqual(package.parse_xml('<?xml version="1.0"?><a b="c">d</a>').attrib, {"b": "c"})
        for text in ("<!DOCTYPE a><a/>", '<!DOCTYPE a SYSTEM "file:///etc/passwd"><a/>',
                     '<!DOCTYPE a [<!ENTITY e "x">]><a>&e;</a>', '<!DOCTYPE a [<!ENTITY % p "x">]><a/>'):
            with self.subTest(text=text), self.assertRaisesRegex(ValueError, "declares entities"):
                package.parse_xml(text)
        with self.assertRaisesRegex(ValueError, "malformed"):
            package.parse_xml("<a><b></a>")

    def test_minimum_os_comes_from_the_one_build_version_command(self):
        self.assertEqual(package.parse_minimum_os(SAMPLE_LOAD_COMMANDS), "26.0")
        fat = SAMPLE_LOAD_COMMANDS + SAMPLE_LOAD_COMMANDS.split("Load command 11", 1)[1]
        for text in (fat, SAMPLE_LOAD_COMMANDS.replace(" platform 1", " platform 2"),
                     SAMPLE_LOAD_COMMANDS.replace("LC_BUILD_VERSION", "LC_VERSION_MIN_MACOSX")):
            with self.assertRaisesRegex(ValueError, "minimum version"):
                package.parse_minimum_os(text)

    def test_pkg_builds_the_sealed_folder_with_root_modes_and_scripts(self):
        output = self.root / "dist" / "Vocello-macos26-cli.pkg"
        work = self.root / "pkg work"
        calls = []

        def tools(argv, cwd, environment, expected=0, timeout=60):
            calls.append(list(argv))
            self.assertEqual(environment["PATH"], "/usr/bin:/bin:/usr/sbin:/sbin")
            Path(argv[-1]).write_bytes(b"xar! " + Path(argv[0]).name.encode())
            return ""

        (self.output / "README.txt").chmod(0o600)  # a restrictive umask at stage time
        package.seal(self.output, self.release)
        with mock.patch.object(package, "binary_minimum_os", return_value="26.0"), \
             mock.patch.object(package, "command", side_effect=tools):
            result = package.pkg(self.output, self.release, output, work=work)
        self.assertEqual(output.read_bytes(), b"xar! productbuild")
        self.assertEqual(result["artifact"]["sha256"], package.digest(output))
        pkgbuild, productbuild = calls
        self.assertEqual(pkgbuild[:5], ["/usr/bin/pkgbuild", "--root", str(work.resolve() / "root"),
                                        "--install-location", "/usr/local/lib/vocello"])
        for flag, value in (("--identifier", "com.qwenvoice.cli"), ("--version", "3.0.0"),
                            ("--ownership", "recommended"), ("--scripts", str(work.resolve() / "scripts"))):
            self.assertEqual(pkgbuild[pkgbuild.index(flag) + 1], value)
        self.assertEqual(pkgbuild[-1], str(work.resolve() / package.COMPONENT))
        self.assertEqual(productbuild[productbuild.index("--package-path") + 1], str(work.resolve()))
        self.assertEqual(Path(productbuild[-1]).name, output.name)

        staged = work / "root"
        package.verify(staged, self.release)
        for path in [staged, *staged.rglob("*")]:
            mode = stat.S_IMODE(path.stat().st_mode)
            self.assertEqual(mode, 0o755 if path.is_dir() or path.name == "vocello" else 0o644, path.name)
        self.assertEqual(plistlib.loads((work / "component.plist").read_bytes()),
                         plistlib.loads(package.component_plist(staged)))
        self.assertEqual(sorted(path.name for path in (work / "scripts").iterdir()), ["postinstall", "preinstall"])
        for name, source in package.PKG_SCRIPT_SOURCES.items():
            self.assertEqual((work / "scripts" / name).read_bytes(), (REPOSITORY / source).read_bytes())
            self.assertEqual(stat.S_IMODE((work / "scripts" / name).stat().st_mode), 0o755)
        self.assertEqual(package.check_distribution((work / "Distribution.xml").read_bytes(), "3.0.0"), "26.0")
        self.assertEqual((work / "resources/LICENSE.txt").read_bytes(), (self.output / "LICENSE").read_bytes())
        self.assertFalse(list(output.parent.glob(".cli-pkg-*")))

        with mock.patch.object(package, "binary_minimum_os", return_value="26.0"), \
             mock.patch.object(package, "command", side_effect=tools):
            with self.assertRaisesRegex(ValueError, "overwrite"):
                package.pkg(self.output, self.release, output)
            with self.assertRaisesRegex(ValueError, "work folder"):
                package.pkg(self.output, self.release, self.root / "other.pkg", work=work)
        with mock.patch.object(package, "binary_minimum_os", return_value="27.0"), \
             mock.patch.object(package, "command", side_effect=tools):
            with self.assertRaisesRegex(ValueError, "minimum macOS"):
                package.pkg(self.output, self.release, self.root / "other.pkg")
        self.assertFalse((self.root / "other.pkg").exists())

    def test_pkg_verify_accepts_the_expanded_product_and_reports_it(self):
        expanded, artifact = self.expand_fixture("expanded")
        report = self.verify_fixture(expanded, artifact)
        self.assertEqual(set(report), {"schemaVersion", "status", "release", "manifestSHA256", "fileCount",
                                       "package", "signature", "notarization", "installTest", "checks",
                                       "generationQualification", "artifact"})
        self.assertEqual(report["status"], "passed")
        self.assertEqual(report["release"], self.release)
        self.assertEqual(report["checks"], list(package.PKG_CHECKS))
        self.assertEqual(report["installTest"], "not-performed")
        self.assertEqual(report["generationQualification"], "not-performed")
        self.assertEqual(report["package"]["relocatableBundles"], 0)
        self.assertEqual(report["package"]["hostArchitectures"], ["arm64"])
        self.assertEqual(report["package"]["installLocation"], "/usr/local/lib/vocello")
        self.assertEqual(report["package"]["scriptDigests"],
                         {name: package.digest(REPOSITORY / source)
                          for name, source in package.PKG_SCRIPT_SOURCES.items()})
        self.assertEqual(report["artifact"], {"name": artifact.name, "bytes": artifact.stat().st_size,
                                              "sha256": package.digest(artifact)})
        saved = (expanded.parent / "expanded-verification.json").read_text()
        self.assertEqual(json.loads(saved), report)
        self.assertNotIn(str(self.root), saved)
        with self.assertRaisesRegex(ValueError, "overwrite"):
            self.verify_fixture(expanded, artifact)

    def test_pkg_verify_confirms_the_signature_it_records(self):
        signed = "signed by a developer certificate issued by Apple for distribution"
        expanded, artifact = self.expand_fixture("signed")
        # A stapled product may expand with a plain file beside its own entries.
        (expanded / "ticket").write_bytes(b"fixture ticket")
        calls: list = []
        report = self.verify_fixture(expanded, artifact, signature="developer-id-installer",
                                     notarization="stapled", status=signed, calls=calls)
        self.assertEqual((report["signature"], report["notarization"]), ("developer-id-installer", "stapled"))
        self.assertIn(["/usr/bin/xcrun", "stapler", "validate", str(artifact)], calls)
        self.assertNotIn("FIXTURE123", json.dumps(report))
        cases = {
            "claims-unsigned": dict(status=signed),
            "claims-signed": dict(signature="developer-id-installer"),
            "stapled-unsigned": dict(notarization="stapled"),
            "unknown-claim": dict(signature="ad-hoc"),
            "unstapled-extra-entry": dict(signature="developer-id-installer", status=signed),
        }
        for case, arguments in cases.items():
            expanded, artifact = self.expand_fixture(case)
            if case == "unstapled-extra-entry":
                (expanded / "ticket").write_bytes(b"fixture ticket")
            with self.subTest(case=case), self.assertRaises(ValueError):
                self.verify_fixture(expanded, artifact, **arguments)
            self.assertFalse((expanded.parent / f"{case}-verification.json").exists())
        expanded, artifact = self.expand_fixture("stapled-extra-folder")
        (expanded / "other.pkg").mkdir()
        with self.assertRaisesRegex(ValueError, "layout"):
            self.verify_fixture(expanded, artifact, signature="developer-id-installer",
                                notarization="stapled", status=signed)

    def test_pkg_verify_rejects_package_faults(self):
        relocating = '>\n        <bundle id="fixture.GRDB_GRDB.resources"/>\n    </relocate>'

        def edit(path: str, old: str, new: str):
            def change(expanded: Path):
                target = expanded / path
                target.write_text(target.read_text().replace(old, new))
            return change

        def payload(change):
            def mutate(expanded: Path):
                folder = expanded / package.COMPONENT / "Payload"
                change(folder)
            return mutate

        def bom(mutate):
            def change(rows):
                mutate(rows)
                return rows
            return change

        component = package.COMPONENT
        faults = {
            "relocate": (dict(package_info=self.package_info(relocate=relocating)), None, None, "relocates bundles"),
            "relocatable": (dict(package_info=self.package_info().replace('relocatable="false"', 'relocatable="true"')),
                            None, None, "relocates bundles"),
            "install-location": (dict(package_info=self.package_info(location="/Applications/vocello")),
                                 None, None, "identity mismatch"),
            "package-version": (dict(package_info=self.package_info(version="2.9.0")), None, None, "identity mismatch"),
            "no-postinstall": (dict(package_info=self.package_info(postinstall="")), None, None,
                               "preinstall and postinstall"),
            "package-info-byte-order-mark": (dict(package_info="﻿" + self.package_info()), None, None,
                                             "plain UTF-8"),
            "package-info-entity": (dict(package_info=self.package_info().replace(
                "<pkg-info", '<!DOCTYPE pkg-info [<!ENTITY v "3.0.0">]>\n<pkg-info', 1)), None, None, "entities"),
            "x86_64": (dict(distribution=PRODUCT_DISTRIBUTION.replace('"arm64"', '"arm64,x86_64"').encode()),
                       None, None, "arm64"),
            "home-domain": (dict(distribution=PRODUCT_DISTRIBUTION.replace(
                'enable_currentUserHome="false"', 'enable_currentUserHome="true"').encode()), None, None, "startup disk"),
            "older-minimum": (dict(distribution=PRODUCT_DISTRIBUTION.replace('min="26.0"', 'min="15.0"').encode()),
                              None, None, "minimum macOS differs"),
            "extra-file": ({}, payload(lambda folder: (folder / "extra.txt").write_text("extra")), None, "payload"),
            "script-drift": ({}, edit(f"{component}/Scripts/preinstall", "set -eu", "set -u"), None,
                             "scripts differ"),
            "extra-script": ({}, lambda expanded: (expanded / component / "Scripts/postflight").write_text("x"),
                             None, "layout"),
            "readme-drift": ({}, edit("Resources/README.txt", "Vocello", "Other"), None, "readme or license"),
            "bom-extra": ({}, None, bom(lambda rows: rows.append(["./extra", 0, 0, 0o100644])), "differs from the payload"),
            "bom-missing": ({}, None, bom(lambda rows: rows.pop()), "differs from the payload"),
            "bom-setuid": ({}, None, bom(lambda rows: [row.__setitem__(3, 0o104755) for row in rows
                                                      if row[0] == "./vocello"]), "setuid"),
            "bom-non-root": ({}, None, bom(lambda rows: rows[1].__setitem__(1, 501)), "root:wheel"),
            "bom-writable": ({}, None, bom(lambda rows: rows[1].__setitem__(3, 0o40775)), "modes"),
            "bom-executable-resource": ({}, None, bom(lambda rows: [row.__setitem__(3, 0o100755) for row in rows
                                                                   if row[0] == "./README.txt"]), "modes"),
        }
        for fault, (layout, mutate, change_rows, message) in faults.items():
            expanded, artifact = self.expand_fixture(fault, **layout)
            if mutate:
                mutate(expanded)
            rows = change_rows(self.bom_rows(expanded / component / "Payload")) if change_rows else None
            with self.subTest(fault=fault), self.assertRaisesRegex(ValueError, message):
                self.verify_fixture(expanded, artifact, rows=rows)

        expanded, artifact = self.expand_fixture("manifest")
        with self.assertRaisesRegex(ValueError, "manifest differs"):
            self.verify_fixture(expanded, artifact, manifest="0" * 64)
        # A payload resealed around a different uninstaller still differs from the source.
        expanded, artifact = self.expand_fixture("helper-drift")
        folder = expanded / component / "Payload"
        (folder / package.UNINSTALLER).write_text("#!/bin/sh\nrm -rf /usr/local\n")
        package.seal(folder, self.release)
        with self.assertRaisesRegex(ValueError, "helpers differ"):
            self.verify_fixture(expanded, artifact, manifest=package.digest(folder / package.MANIFEST))

    def test_command_line_routes_pkg_verify_without_a_directory(self):
        arguments = ["cli_package.py", "pkg-verify", "--version", "3.0.0", "--build", "24", "--commit", "a" * 40]
        with mock.patch.object(sys, "argv", arguments), redirect_stdout(io.StringIO()) as printed:
            self.assertEqual(package.main(), 1)
        self.assertIn("pkg-verify: FAIL", printed.getvalue())
        with mock.patch.object(sys, "argv", ["cli_package.py", "pkg", "--version", "3.0.0"]), \
             redirect_stdout(io.StringIO()), mock.patch("sys.stderr", io.StringIO()):
            with self.assertRaises(SystemExit) as exit_status:
                package.main()
        self.assertEqual(exit_status.exception.code, 2)

    @unittest.skipUnless(sys.platform == "darwin" and all(
        Path(tool).exists() for tool in ("/usr/bin/pkgbuild", "/usr/bin/productbuild", "/usr/sbin/pkgutil",
                                         "/usr/bin/lsbom", "/usr/bin/ditto")), "needs the macOS packaging tools")
    def test_real_package_round_trip_installs_upgrades_and_refuses_without_root(self):
        output = self.root / "dist" / "Vocello-macos26-cli.pkg"
        with mock.patch.object(package, "binary_minimum_os", return_value="26.0"):
            package.pkg(self.output, self.release, output)
        expanded = self.root / "expanded product"
        subprocess.run(["/usr/sbin/pkgutil", "--expand-full", str(output), str(expanded)],
                       check=True, capture_output=True)
        info = ElementTree.fromstring((expanded / package.COMPONENT / "PackageInfo").read_bytes())
        self.assertFalse([bundle for node in info.iter("relocate") for bundle in node])
        self.assertEqual({bundle.attrib["id"] for node in info.iter("strict-identifier") for bundle in node},
                         set(self.identifiers().values()))

        real_command = package.command
        cli_runs = []

        def tools(argv, cwd, environment, expected=0, timeout=60):
            # Only the fixture executable is faked; Installer's scripts, ditto and lsbom run for real.
            if argv[0].endswith("/vocello") or argv[0] == "/usr/bin/lipo" or argv[:2] in (
                    ["/usr/bin/otool", "-L"], ["/usr/bin/otool", "-X"]):
                cli_runs.append(list(argv))
                return self.fake_command(argv, cwd, environment, expected)
            return real_command(argv, cwd, environment, expected, timeout)

        report_path = self.root / "cli-pkg-verification.json"
        with mock.patch.object(package, "binary_minimum_os", return_value="26.0"), \
             mock.patch.object(package, "command", side_effect=tools):
            report = package.pkg_verify(
                expanded, output, self.release, package.digest(self.output / package.MANIFEST),
                signature="unsigned", notarization="not-performed", report=report_path, root_free_install=True)
        self.assertEqual(report["checks"], [*package.PKG_CHECKS, *package.PKG_INSTALL_CHECKS])
        self.assertEqual(report["installTest"], "not-performed")
        launched = {argv[0] for argv in cli_runs if argv[0].endswith("/vocello")}
        self.assertEqual(len(launched), 1)
        self.assertTrue(launched.pop().endswith("/root with spaces/usr/local/bin/vocello"))
        inspected = [argv[-1] for argv in cli_runs if not argv[0].endswith("/vocello")]
        self.assertTrue(inspected)
        self.assertTrue(all(path.endswith("/root with spaces/usr/local/lib/vocello/vocello") for path in inspected))
        self.assertNotIn(str(self.root), report_path.read_text())

        # The real report binds in release evidence beside the DMG of the same sealed payload: as
        # rehearsal evidence while unsigned, never as release evidence.
        dmg_report = {"artifact": {"name": "Vocello-macos26-cli.dmg"},
                      "manifestSHA256": package.digest(self.output / package.MANIFEST),
                      "fileCount": len(json.loads((self.output / package.MANIFEST).read_text())["files"])}
        artifacts = [{"kind": "artifact", **report["artifact"]}]
        release_evidence.validate_cli_installer_verification(report, self.release, artifacts, dmg_report,
                                                             rehearsal=True)
        with self.assertRaisesRegex(ValueError, "Developer ID Installer"):
            release_evidence.validate_cli_installer_verification(report, self.release, artifacts, dmg_report)


if __name__ == "__main__":
    unittest.main()
