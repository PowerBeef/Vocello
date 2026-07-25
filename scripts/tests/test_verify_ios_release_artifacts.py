from __future__ import annotations

import importlib.util
import hashlib
import sys
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock


SCRIPTS = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "verify_ios_release_artifacts", SCRIPTS / "verify_ios_release_artifacts.py"
)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)


class IOSReleaseArtifactVerificationTests(unittest.TestCase):
    TEAM = "ABCDE12345"
    PREFIX = "ABCDE12345"
    BUNDLE = "com.patricedery.vocello"
    GROUP = "group.com.patricedery.vocello.shared"
    LEAF_CERTIFICATE = b"fixture-signing-leaf"
    PRIVACY_DIGEST = "1" * 64

    def setUp(self) -> None:
        self.expected = module.ExpectedIOSIdentity(
            bundle_identifier=self.BUNDLE,
            marketing_version="2.1.0",
            build_number="18",
            application_groups=(self.GROUP,),
            increased_memory_limit=True,
            privacy_manifest_sha256=self.PRIVACY_DIGEST,
        )
        self.info = {
            "CFBundleIdentifier": self.BUNDLE,
            "CFBundleShortVersionString": "2.1.0",
            "CFBundleVersion": "18",
            "CFBundlePackageType": "APPL",
            "CFBundleSupportedPlatforms": ["iPhoneOS"],
        }
        self.entitlements = {
            "application-identifier": f"{self.PREFIX}.{self.BUNDLE}",
            "com.apple.developer.team-identifier": self.TEAM,
            "com.apple.security.application-groups": [self.GROUP],
            "com.apple.developer.kernel.increased-memory-limit": True,
        }
        self.profile = {
            "TeamIdentifier": [self.TEAM],
            "ApplicationIdentifierPrefix": [self.PREFIX],
            "DeveloperCertificates": [self.LEAF_CERTIFICATE],
            "ExpirationDate": datetime.now(timezone.utc) + timedelta(days=365),
            "Entitlements": {
                "application-identifier": f"{self.PREFIX}.{self.BUNDLE}",
                "com.apple.security.application-groups": [self.GROUP],
                "com.apple.developer.kernel.increased-memory-limit": True,
            },
        }

    def snapshot(self, **overrides: object) -> module.BundleSnapshot:
        arguments = {
            "label": "archive",
            "info": self.info,
            "entitlements": self.entitlements,
            "profile": self.profile,
            "authorities": ["Apple Development: Fixture"],
            "signing_leaf_certificate": self.LEAF_CERTIFICATE,
            "signing_certificate_trust_verified": True,
            "architectures": ["arm64"],
            "macho_uuids": ["AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE"],
            "expected": self.expected,
            "expected_team_id": self.TEAM,
            "require_app_store_distribution": False,
            "executable_sha256": "a" * 64,
            "signature_normalized_executable_sha256": "c" * 64,
            "bundle_sha256": "b" * 64,
            "privacy_manifest_sha256": self.PRIVACY_DIGEST,
        }
        arguments.update(overrides)
        return module.validate_bundle_contract(**arguments)

    def test_expected_identity_resolves_from_the_live_project(self) -> None:
        # Regression: version identity moved to project-scope settings in 2.2.1 and
        # the release-lane verifier (which regex-parses project.yml rather than
        # xcodebuild output) only looked at the target block, failing the v2.2.1
        # ipa-verification step on CI. Bind the verifier to the real tree so a
        # settings-layout change breaks here, before a tag freezes it.
        identity = module.load_expected_identity()
        self.assertEqual(identity.bundle_identifier, "com.patricedery.vocello")
        self.assertRegex(identity.marketing_version, r"^\d+\.\d+\.\d+$")
        self.assertRegex(identity.build_number, r"^\d+$")

    def test_valid_distribution_bundle_passes_without_exposing_team(self) -> None:
        snapshot = self.snapshot(
            label="export",
            authorities=["Apple Distribution: Fixture"],
            require_app_store_distribution=True,
        )
        self.assertTrue(snapshot.signature_verified)
        self.assertTrue(snapshot.signing_certificate_trust_verified)
        self.assertTrue(snapshot.distribution_authority_verified)
        self.assertTrue(snapshot.provisioning_profile_verified)
        self.assertTrue(snapshot.signer_profile_certificate_match)
        self.assertNotIn(self.TEAM, str(snapshot.public_dict()))

    def test_bundle_version_and_build_must_match_project(self) -> None:
        info = dict(self.info, CFBundleShortVersionString="2.2.0")
        with self.assertRaisesRegex(module.VerificationError, "identity"):
            self.snapshot(info=info)

    def test_only_arm64_is_accepted(self) -> None:
        with self.assertRaisesRegex(module.VerificationError, "exactly arm64"):
            self.snapshot(architectures=["arm64", "x86_64"])

    def test_debug_entitlement_is_rejected(self) -> None:
        entitlements = dict(self.entitlements, **{"get-task-allow": True})
        with self.assertRaisesRegex(module.VerificationError, "get-task-allow"):
            self.snapshot(
                label="export",
                entitlements=entitlements,
                authorities=["Apple Distribution: Fixture"],
                require_app_store_distribution=True,
            )

    def test_development_signed_archive_is_valid_and_may_allow_debugging(self) -> None:
        entitlements = dict(self.entitlements, **{"get-task-allow": True})
        profile = dict(self.profile, ProvisionedDevices=["fixture-device"])
        profile["Entitlements"] = dict(self.profile["Entitlements"], **{"get-task-allow": True})
        snapshot = self.snapshot(entitlements=entitlements, profile=profile)
        self.assertTrue(snapshot.signing_authority_verified)
        self.assertFalse(snapshot.distribution_authority_verified)
        self.assertTrue(snapshot.get_task_allow)

    def test_wrong_or_ad_hoc_profile_is_rejected(self) -> None:
        wrong_team = dict(self.profile, TeamIdentifier=["ZZZZZ99999"])
        with self.assertRaisesRegex(module.VerificationError, "provisioning team"):
            self.snapshot(profile=wrong_team)
        ad_hoc = dict(self.profile, ProvisionedDevices=["fixture-device"])
        with self.assertRaisesRegex(module.VerificationError, "App Store distribution"):
            self.snapshot(
                label="export",
                profile=ad_hoc,
                authorities=["Apple Distribution: Fixture"],
                require_app_store_distribution=True,
            )

    def test_profile_must_authorize_app_group_and_memory_capability(self) -> None:
        profile = dict(self.profile)
        profile["Entitlements"] = dict(self.profile["Entitlements"], **{
            "com.apple.security.application-groups": [],
        })
        with self.assertRaisesRegex(module.VerificationError, "App Groups"):
            self.snapshot(profile=profile)

    def test_distribution_authority_is_required(self) -> None:
        with self.assertRaisesRegex(module.VerificationError, "Apple Distribution"):
            self.snapshot(label="export", require_app_store_distribution=True)
        with self.assertRaisesRegex(module.VerificationError, "Apple development or distribution"):
            self.snapshot(authorities=["Fixture Signing: Invalid"])

    def test_signing_leaf_must_be_authorized_by_profile(self) -> None:
        with self.assertRaisesRegex(module.VerificationError, "not authorized"):
            self.snapshot(signing_leaf_certificate=b"unlisted-certificate")
        with self.assertRaisesRegex(module.VerificationError, "trust evaluation"):
            self.snapshot(signing_certificate_trust_verified=False)

    def test_app_identifier_prefix_may_differ_from_team_identifier(self) -> None:
        prefix = "ZYXWV98765"
        entitlements = dict(self.entitlements, **{
            "application-identifier": f"{prefix}.{self.BUNDLE}",
        })
        profile = dict(self.profile, ApplicationIdentifierPrefix=[prefix])
        profile["Entitlements"] = dict(self.profile["Entitlements"], **{
            "application-identifier": f"{prefix}.{self.BUNDLE}",
        })
        snapshot = self.snapshot(entitlements=entitlements, profile=profile)
        self.assertTrue(snapshot.application_identifier_verified)

        mismatched = dict(profile)
        mismatched["Entitlements"] = dict(profile["Entitlements"], **{
            "application-identifier": f"{self.TEAM}.{self.BUNDLE}",
        })
        with self.assertRaisesRegex(module.VerificationError, "application identifier"):
            self.snapshot(entitlements=entitlements, profile=mismatched)

    def test_archive_and_export_uuid_identity_must_match(self) -> None:
        archived = self.snapshot()
        exported = replace(
            archived,
            label="export",
            macho_uuids=("11111111-2222-3333-4444-555555555555",),
        )
        with self.assertRaisesRegex(module.VerificationError, "identities differ"):
            module.compare_archive_and_export(archived, exported)

    def test_archive_and_export_may_have_different_signed_bytes_but_not_different_code(self) -> None:
        archived = self.snapshot()
        exported = replace(
            archived,
            label="export",
            executable_sha256="d" * 64,
            distribution_authority_verified=True,
        )
        module.compare_archive_and_export(archived, exported)

        changed_code = replace(exported, signature_normalized_executable_sha256="e" * 64)
        with self.assertRaisesRegex(module.VerificationError, "identities differ"):
            module.compare_archive_and_export(archived, changed_code)

    def test_privacy_manifest_must_match_source_contract(self) -> None:
        with self.assertRaisesRegex(module.VerificationError, "privacy manifest differs"):
            self.snapshot(privacy_manifest_sha256="f" * 64)

    def test_root_privacy_manifest_is_required_and_semantically_hashed(self) -> None:
        payload = {
            "NSPrivacyTracking": False,
            "NSPrivacyTrackingDomains": [],
            "NSPrivacyCollectedDataTypes": [],
            "NSPrivacyAccessedAPITypes": [{
                "NSPrivacyAccessedAPIType": "NSPrivacyAccessedAPICategoryUserDefaults",
                "NSPrivacyAccessedAPITypeReasons": ["CA92.1"],
            }],
        }
        with tempfile.TemporaryDirectory() as directory:
            app = Path(directory) / "Fixture.app"
            app.mkdir()
            with self.assertRaisesRegex(module.VerificationError, "exactly one root"):
                module._root_privacy_manifest_digest(app, "archive")
            (app / "PrivacyInfo.xcprivacy").write_bytes(module.plistlib.dumps(payload))
            self.assertEqual(
                module._root_privacy_manifest_digest(app, "archive"),
                module._canonical_plist_digest(payload),
            )
            (app / "PrivacyInfo.xcprivacy").write_bytes(module.plistlib.dumps({"NSPrivacyTracking": True}))
            with self.assertRaisesRegex(module.VerificationError, "disable tracking"):
                module._root_privacy_manifest_digest(app, "archive")

    def test_signature_normalized_digest_removes_signature_from_a_copy(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            executable = Path(directory) / "Vocello"
            executable.write_bytes(b"CODE|SIGNATURE-A")

            def remove_signature(arguments: list[str]) -> tuple[bytes, bytes]:
                self.assertIn("--remove-signature", arguments)
                copied = Path(arguments[-1])
                copied.write_bytes(copied.read_bytes().split(b"|SIGNATURE", 1)[0])
                return b"", b""

            with mock.patch.object(module, "_run_bytes", side_effect=remove_signature):
                digest = module._signature_normalized_executable_digest(executable)
            self.assertEqual(digest, hashlib.sha256(b"CODE").hexdigest())
            self.assertEqual(executable.read_bytes(), b"CODE|SIGNATURE-A")

    def test_signing_leaf_is_returned_only_after_local_code_signing_trust_passes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            app = Path(directory) / "Fixture.app"
            app.mkdir()
            observed_verification: list[str] = []

            def trusted_run(arguments: list[str]) -> tuple[bytes, bytes]:
                extraction = next(
                    (value for value in arguments if value.startswith("--extract-certificates=")), None
                )
                if extraction is not None:
                    prefix = Path(extraction.partition("=")[2])
                    Path(f"{prefix}0").write_bytes(self.LEAF_CERTIFICATE)
                    Path(f"{prefix}1").write_bytes(b"fixture-intermediate")
                elif "verify-cert" in arguments:
                    observed_verification.extend(arguments)
                return b"", b""

            with mock.patch.object(module, "_run_bytes", side_effect=trusted_run):
                leaf = module._trusted_signing_leaf_certificate(app)
            self.assertEqual(leaf, self.LEAF_CERTIFICATE)
            self.assertIn("codeSign", observed_verification)
            self.assertIn("-L", observed_verification)
            self.assertEqual(observed_verification.count("-c"), 2)

            def untrusted_run(arguments: list[str]) -> tuple[bytes, bytes]:
                extraction = next(
                    (value for value in arguments if value.startswith("--extract-certificates=")), None
                )
                if extraction is not None:
                    prefix = Path(extraction.partition("=")[2])
                    Path(f"{prefix}0").write_bytes(self.LEAF_CERTIFICATE)
                    return b"", b""
                raise module.VerificationError("certificate trust failed")

            with mock.patch.object(module, "_run_bytes", side_effect=untrusted_run):
                with self.assertRaisesRegex(module.VerificationError, "trust failed"):
                    module._trusted_signing_leaf_certificate(app)

    def test_repository_expected_identity_matches_capability_contract(self) -> None:
        expected = module.load_expected_identity(SCRIPTS.parent)
        self.assertEqual(expected.bundle_identifier, self.BUNDLE)
        self.assertEqual(expected.application_groups, (self.GROUP,))
        self.assertRegex(expected.privacy_manifest_sha256, r"^[0-9a-f]{64}$")


if __name__ == "__main__":
    unittest.main()
