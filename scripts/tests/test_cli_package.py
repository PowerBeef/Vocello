from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import plistlib
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import cli_package as package
import release_evidence


def plist_dump(info: dict) -> str:
    data = plistlib.dumps(info)
    data += b"\0" * (-len(data) % 4)
    return "\n".join(f"{index:016x}\t{int.from_bytes(data[index:index+4], 'little'):08x}" for index in range(0, len(data), 4))


class CLIPackageTests(unittest.TestCase):
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
