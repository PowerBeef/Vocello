from __future__ import annotations

import importlib.util
import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1]
ROOT = SCRIPTS.parent
LEDGER_TOOL = SCRIPTS / "required_step_ledger.py"
sys.path.insert(0, str(SCRIPTS))
SPEC = importlib.util.spec_from_file_location("release_evidence", SCRIPTS / "release_evidence.py")
assert SPEC and SPEC.loader
release_evidence = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(release_evidence)


IDENTITY_DIGESTS = [
    "requiredInputsDigest", "toolchainDigest", "projectInputsDigest", "projectDigest",
    "runtimeCapabilitiesDigest", "compatibilityDigest", "modelCatalogDigest",
    "evidenceImpactDigest", "orchestrationContractDigest", "releaseContractDigest",
]


class ReleaseEvidenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "QwenVoice.xcodeproj/project.xcworkspace/xcshareddata/swiftpm").mkdir(parents=True)
        (self.root / "website").mkdir()
        (self.root / "config").mkdir()
        (self.root / "project.yml").write_text(
            'settings:\n  MARKETING_VERSION: "2.1.0"\n  CURRENT_PROJECT_VERSION: "18"\n', encoding="utf-8"
        )
        (self.root / release_evidence.release_sbom.SWIFT_LOCK).write_text(json.dumps({
            "pins": [{"identity": "mlx-swift", "location": "https://example.invalid/mlx-swift.git", "state": {
                "revision": "a" * 40, "version": "1.0.0"
            }}]
        }), encoding="utf-8")
        (self.root / "website/package-lock.json").write_text(json.dumps({
            "packages": {"": {"name": "site"}, "node_modules/react": {
                "version": "18.3.1", "resolved": "https://registry.npmjs.org/react/-/react-18.3.1.tgz",
                "integrity": "sha512-YWJj", "license": "MIT"
            }}
        }), encoding="utf-8")
        self.release_contract = self.root / "config/release-evidence-contract.json"
        source_inputs = {field: ["project.yml"] for field in IDENTITY_DIGESTS}
        source_inputs["orchestrationContractDigest"] = ["config/orchestration-contract.json"]
        source_inputs["releaseContractDigest"] = ["config/release-evidence-contract.json"]
        self.release_contract.write_text(json.dumps({
            "schemaVersion": 1,
            "publicationPolicy": "draft-build-verify-attest-await-source-bound-promotion",
            "sourceIdentity": ["gitCommit", "treeDirty", *IDENTITY_DIGESTS],
            "sourceIdentityInputs": source_inputs,
            "verificationFreshnessSeconds": 3600,
            "platformVerification": {
                "macos": {"workflow": "release-macos-fixture", "requiredSteps": ["build", "verify"]},
                "ios": {"workflow": "release-ios-fixture", "requiredSteps": ["archive"]},
            },
            "artifacts": ["fixture"],
        }, indent=2, sort_keys=True), encoding="utf-8")
        self.orchestration_contract = self.root / "config/orchestration-contract.json"
        self.orchestration_contract.write_text(json.dumps({
            "schemaVersion": 1,
            "faultInjection": {
                "enableEnvironmentVariable": "FIXTURE_FAULTS",
                "stepEnvironmentVariable": "FIXTURE_STEP",
            },
            "workflows": {
                "release-macos-fixture": {
                    "producer": "project.yml", "sourceIdentityRequired": True,
                    "requiredSteps": ["build", "verify"],
                    "commandTemplates": {
                        "build": [{"id": "fixture-build-v1", "argv": ["/usr/bin/true"]}],
                        "verify": [{
                            "id": "fixture-verify-v1",
                            "argv": ["/usr/bin/true"],
                            "outputs": ["build/dist/macos/verification-summary.json"],
                        }],
                    },
                },
                "release-ios-fixture": {
                    "producer": "project.yml", "sourceIdentityRequired": True,
                    "requiredSteps": ["archive"],
                    "commandTemplates": {
                        "archive": [{"id": "fixture-archive-v1", "argv": ["/usr/bin/true"]}],
                    },
                },
            },
        }, indent=2), encoding="utf-8")
        (self.root / ".gitignore").write_text("build/\n", encoding="utf-8")
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        subprocess.run(["git", "-C", str(self.root), "config", "user.email", "fixture@example.invalid"], check=True)
        subprocess.run(["git", "-C", str(self.root), "config", "user.name", "Fixture"], check=True)
        subprocess.run(["git", "-C", str(self.root), "add", "."], check=True)
        subprocess.run(["git", "-C", str(self.root), "commit", "-qm", "fixture"], check=True)
        self.commit = subprocess.check_output(["git", "-C", str(self.root), "rev-parse", "HEAD"], text=True).strip()

        self.output = self.root / "build/dist/macos"
        self.output.mkdir(parents=True)
        self.dmg = self.output / "Vocello-macos26.dmg"
        self.metadata = self.output / "release-metadata.txt"
        self.step_summary = self.output / "verification-summary.json"
        self.dmg.write_bytes(b"dmg fixture")
        self.metadata.write_text("dmg_name=Vocello-macos26.dmg\n", encoding="utf-8")
        self.step_summary.write_text('{"verdict":"passed"}\n', encoding="utf-8")
        self.source_identity = self.root / "build/artifacts/release/source-identity.json"
        self.ledger = self.root / "build/artifacts/release/required-steps.json"
        release_evidence.capture_source_identity(self.root, self.commit, self.source_identity)
        self.create_managed_ledger()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def ledger_tool(self, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        completed = subprocess.run(
            ["python3", str(LEDGER_TOOL), "--contract", str(self.orchestration_contract), *args],
            text=True, capture_output=True, check=False,
        )
        if check and completed.returncode:
            self.fail(completed.stdout + completed.stderr)
        return completed

    def create_managed_ledger(self) -> None:
        self.ledger_tool(
            "init", "--ledger", str(self.ledger), "--workflow", "release-macos-fixture",
            "--run-id", "fixture", "--source-identity", str(self.source_identity),
        )
        for step in ("build", "verify"):
            self.ledger_tool(
                "run", "--ledger", str(self.ledger), "--step", step,
                "--timeout-seconds", "5", "--cwd", str(self.root), "--", "/usr/bin/true",
            )
        self.ledger_tool("finalize", "--ledger", str(self.ledger))

    def create(self) -> None:
        release_evidence.create(
            self.root, self.output, "v2.1.0", self.commit, "macos", [self.dmg, self.step_summary], self.metadata,
            1_700_000_000, self.source_identity, self.ledger, require_tag_ref=False,
        )

    def create_cli(self, ledger: Path | None = None) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                "python3", str(SCRIPTS / "release_evidence.py"), "create",
                "--root", str(self.root), "--tag", "v2.1.0", "--commit", self.commit,
                "--platform", "macos", "--source-date-epoch", "1700000000",
                "--output-dir", str(self.output), "--artifact", str(self.dmg),
                "--artifact", str(self.step_summary),
                "--metadata", str(self.metadata), "--source-identity", str(self.source_identity),
                "--step-ledger", str(ledger or self.ledger), "--allow-missing-tag-ref",
            ],
            text=True, capture_output=True, check=False,
        )

    def test_create_is_deterministic_relative_and_ledger_derived(self) -> None:
        self.create()
        first = (self.output / release_evidence.EVIDENCE_NAME).read_bytes()
        self.create()
        self.assertEqual(first, (self.output / release_evidence.EVIDENCE_NAME).read_bytes())
        evidence = release_evidence.validate(self.output)
        encoded = json.dumps(evidence)
        self.assertNotIn(str(self.root), encoded)
        self.assertEqual(evidence["release"]["tag"], "v2.1.0")
        self.assertEqual([item["id"] for item in evidence["verification"]], ["build", "verify"])
        self.assertEqual({item["status"] for item in evidence["verification"]}, {"passed"})
        self.assertTrue((self.output / release_evidence.VERIFICATION_BUNDLE_NAME).is_file())

    def test_source_identity_rejects_untracked_source_before_release_work(self) -> None:
        untracked = self.root / "unexpected-source.swift"
        untracked.write_text("// must fail closed\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "clean tracked and untracked"):
            release_evidence.capture_source_identity(
                self.root,
                self.commit,
                self.root / "build/artifacts/release/dirty-source.json",
            )

    def test_unmanaged_required_check_claim_is_rejected(self) -> None:
        payload = json.loads(self.release_contract.read_text(encoding="utf-8"))
        payload["requiredDeterministicChecks"] = ["unbound-check"]
        self.release_contract.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "unbound requiredDeterministicChecks"):
            release_evidence.load_contract(self.root)

    def test_platform_steps_must_match_managed_orchestration(self) -> None:
        payload = json.loads(self.release_contract.read_text(encoding="utf-8"))
        payload["platformVerification"]["macos"]["requiredSteps"] = ["build"]
        self.release_contract.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "differ from managed orchestration"):
            release_evidence.load_contract(self.root)

    def test_tampered_artifact_fails_validation(self) -> None:
        self.create()
        self.dmg.write_bytes(b"tampered")
        with self.assertRaisesRegex(ValueError, "mismatch"):
            release_evidence.validate(self.output)

    def test_tag_must_match_project_version(self) -> None:
        with self.assertRaisesRegex(ValueError, "does not match"):
            release_evidence.create(
                self.root, self.output, "v9.9.9", self.commit, "macos", [self.dmg], self.metadata,
                1_700_000_000, self.source_identity, self.ledger, require_tag_ref=False,
            )

    def test_asset_outside_output_is_rejected(self) -> None:
        # Keep the fixture under the ignored build tree so this test reaches the
        # asset-containment check rather than intentionally tripping the clean
        # full-tree source-identity gate first.
        outside = self.root / "build/secret.dmg"
        outside.parent.mkdir(parents=True, exist_ok=True)
        outside.write_bytes(b"secret")
        with self.assertRaisesRegex(ValueError, "escapes"):
            release_evidence.create(
                self.root, self.output, "v2.1.0", self.commit, "macos", [outside], self.metadata,
                1_700_000_000, self.source_identity, self.ledger, require_tag_ref=False,
            )

    def test_reported_exit_codes_cannot_fabricate_release_pass(self) -> None:
        fabricated = self.root / "build/artifacts/fabricated/required-steps.json"
        self.ledger_tool(
            "init", "--ledger", str(fabricated), "--workflow", "release-macos-fixture",
            "--run-id", "fabricated", "--source-identity", str(self.source_identity),
        )
        for step in ("build", "verify"):
            self.ledger_tool("record", "--ledger", str(fabricated), "--step", step, "--exit-code", "0")
        self.ledger_tool("finalize", "--ledger", str(fabricated))
        with self.assertRaisesRegex(ValueError, "managed subprocess"):
            release_evidence.create(
                self.root, self.output, "v2.1.0", self.commit, "macos", [self.dmg], self.metadata,
                1_700_000_000, self.source_identity, fabricated, require_tag_ref=False,
            )
        self.assertFalse((self.output / release_evidence.EVIDENCE_NAME).exists())

    def test_tampered_command_binding_cannot_publish(self) -> None:
        manifest_path = self.ledger.parent / "steps/build.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["commandTemplateID"] = "fabricated-template-v1"
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        payload = json.loads(self.ledger.read_text(encoding="utf-8"))
        payload["results"]["build"]["commandTemplateID"] = "fabricated-template-v1"
        payload["results"]["build"]["manifestSHA256"] = release_evidence.digest_file(manifest_path)
        self.ledger.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "template identity is unknown"):
            self.create()
        self.assertFalse((self.output / release_evidence.EVIDENCE_NAME).exists())

    def test_managed_output_replacement_cannot_publish(self) -> None:
        self.step_summary.write_text('{"verdict":"replaced"}\n', encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "changed after managed execution"):
            self.create()
        self.assertFalse((self.output / release_evidence.EVIDENCE_NAME).exists())

    @staticmethod
    def ios_verification_fixture() -> tuple[dict[str, object], dict[str, object], list[dict[str, object]]]:
        release = {"marketingVersion": "2.1.0", "buildNumber": "18"}
        expected = {
            "bundleIdentifier": "com.patricedery.vocello",
            "marketingVersion": "2.1.0",
            "buildNumber": "18",
            "architectures": ["arm64"],
            "applicationGroups": ["group.com.patricedery.vocello.shared"],
            "increasedMemoryLimit": True,
            "privacyManifestSHA256": "1" * 64,
        }
        snapshot = {
            "label": "archive",
            "bundleIdentifier": expected["bundleIdentifier"],
            "marketingVersion": expected["marketingVersion"],
            "buildNumber": expected["buildNumber"],
            "architectures": ["arm64"],
            "machOUUIDs": ["AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE"],
            "executableSHA256": "b" * 64,
            "signatureNormalizedExecutableSHA256": "9" * 64,
            "bundleSHA256": "c" * 64,
            "signatureVerified": True,
            "signingAuthorityVerified": True,
            "signingCertificateTrustVerified": True,
            "distributionAuthorityVerified": False,
            "teamIdentifierVerified": True,
            "provisioningProfileVerified": True,
            "signerProfileCertificateMatch": True,
            "applicationIdentifierVerified": True,
            "applicationGroups": expected["applicationGroups"],
            "increasedMemoryLimit": True,
            "getTaskAllow": True,
            "privacyManifestSHA256": expected["privacyManifestSHA256"],
            "privacyManifestVerified": True,
        }
        # App Store export can re-sign the Mach-O, changing its byte digest while
        # preserving the executable UUID and product identity.
        exported = dict(
            snapshot,
            label="export",
            executableSHA256="f" * 64,
            bundleSHA256="d" * 64,
            distributionAuthorityVerified=True,
            getTaskAllow=False,
        )
        payload = {
            "schemaVersion": 2,
            "verdict": "passed",
            "artifact": {"ipaName": "Vocello.ipa", "ipaSHA256": "a" * 64},
            "expectedIdentity": expected,
            "archive": snapshot,
            "export": exported,
            "archiveExportIdentityMatch": True,
            "privacy": {"containsTeamIdentifier": False, "containsAbsolutePaths": False},
        }
        artifacts = [
            {"name": "export/Vocello.ipa", "kind": "artifact", "sha256": "a" * 64},
            {
                "name": release_evidence.IOS_ARTIFACT_VERIFICATION_NAME,
                "kind": "artifact",
                "sha256": "e" * 64,
            },
        ]
        return payload, release, artifacts

    def test_ios_verification_summary_is_structurally_release_bound(self) -> None:
        payload, release, artifacts = self.ios_verification_fixture()
        release_evidence.validate_ios_release_artifact_verification(payload, release, artifacts)

        for label, mutation, message in (
            ("ipa digest", lambda value: value["artifact"].update(ipaSHA256="f" * 64), "different IPA"),
            ("version", lambda value: value["expectedIdentity"].update(marketingVersion="9.0.0"), "differs"),
            ("signature", lambda value: value["export"].update(signatureVerified=False), "failed"),
            ("certificate trust", lambda value: value["export"].update(signingCertificateTrustVerified=False), "failed"),
            ("uuid", lambda value: value["export"].update(machOUUIDs=["11111111-2222-3333-4444-555555555555"]), "do not match"),
            ("normalized executable", lambda value: value["export"].update(signatureNormalizedExecutableSHA256="8" * 64), "do not match"),
            ("certificate binding", lambda value: value["export"].update(signerProfileCertificateMatch=False), "failed"),
            ("privacy manifest", lambda value: value["export"].update(privacyManifestSHA256="7" * 64), "failed"),
            ("privacy", lambda value: value.update(privacy={"containsTeamIdentifier": True, "containsAbsolutePaths": False}), "privacy"),
        ):
            with self.subTest(label=label):
                tampered = copy.deepcopy(payload)
                mutation(tampered)
                with self.assertRaisesRegex(ValueError, message):
                    release_evidence.validate_ios_release_artifact_verification(tampered, release, artifacts)

    def test_partial_step_manifest_prevents_publication(self) -> None:
        (self.output / release_evidence.EVIDENCE_NAME).write_text("stale", encoding="utf-8")
        (self.output / release_evidence.CHECKSUM_NAME).write_text("stale", encoding="utf-8")
        (self.output / release_evidence.VERIFICATION_BUNDLE_NAME).write_text("stale", encoding="utf-8")
        manifest = self.ledger.parent / "steps/build.json"
        manifest.write_text('{"schemaVersion":', encoding="utf-8")
        completed = self.create_cli()
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("missing, partial, or stale", completed.stderr)
        self.assertFalse((self.output / release_evidence.EVIDENCE_NAME).exists())
        self.assertFalse((self.output / release_evidence.CHECKSUM_NAME).exists())
        self.assertFalse((self.output / release_evidence.VERIFICATION_BUNDLE_NAME).exists())

    def test_duplicate_step_manifest_digest_prevents_publication(self) -> None:
        build_manifest = self.ledger.parent / "steps/build.json"
        verify_manifest = self.ledger.parent / "steps/verify.json"
        verify_manifest.write_bytes(build_manifest.read_bytes())
        payload = json.loads(self.ledger.read_text(encoding="utf-8"))
        payload["results"]["verify"]["manifestSHA256"] = release_evidence.digest_file(verify_manifest)
        self.ledger.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "duplicate required-step manifest digest"):
            self.create()
        self.assertFalse((self.output / release_evidence.EVIDENCE_NAME).exists())

    def test_stale_ledger_prevents_publication(self) -> None:
        payload = json.loads(self.ledger.read_text(encoding="utf-8"))
        payload["startedAt"] = "2020-01-01T00:00:00Z"
        payload["completedAt"] = "2020-01-01T00:01:00Z"
        for index, step in enumerate(("build", "verify")):
            started = f"2020-01-01T00:00:0{index}Z"
            completed = f"2020-01-01T00:00:1{index}Z"
            path = self.ledger.parent / f"steps/{step}.json"
            manifest = json.loads(path.read_text(encoding="utf-8"))
            manifest["startedAt"] = started
            manifest["completedAt"] = completed
            path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            payload["results"][step]["completedAt"] = completed
            payload["results"][step]["manifestSHA256"] = release_evidence.digest_file(path)
        self.ledger.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        completed = self.create_cli()
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("stale", completed.stderr)
        self.assertFalse((self.output / release_evidence.EVIDENCE_NAME).exists())

    def test_missing_step_cannot_publish(self) -> None:
        partial = self.root / "build/artifacts/partial/required-steps.json"
        self.ledger_tool(
            "init", "--ledger", str(partial), "--workflow", "release-macos-fixture",
            "--run-id", "partial", "--source-identity", str(self.source_identity),
        )
        self.ledger_tool(
            "run", "--ledger", str(partial), "--step", "build",
            "--timeout-seconds", "5", "--", "/usr/bin/true",
        )
        with self.assertRaisesRegex(ValueError, "did not pass"):
            release_evidence.create(
                self.root, self.output, "v2.1.0", self.commit, "macos", [self.dmg], self.metadata,
                1_700_000_000, self.source_identity, partial, require_tag_ref=False,
            )
        self.assertFalse((self.output / release_evidence.EVIDENCE_NAME).exists())

    def test_source_change_after_capture_prevents_publication(self) -> None:
        (self.root / "project.yml").write_text(
            'settings:\n  MARKETING_VERSION: "2.1.0"\n  CURRENT_PROJECT_VERSION: "19"\n', encoding="utf-8"
        )
        with self.assertRaisesRegex(ValueError, "source tree changed"):
            self.create()
        self.assertFalse((self.output / release_evidence.EVIDENCE_NAME).exists())


if __name__ == "__main__":
    unittest.main()
