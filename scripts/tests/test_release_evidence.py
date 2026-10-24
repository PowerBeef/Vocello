from __future__ import annotations

import importlib.util
import copy
import dataclasses
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SCRIPTS = Path(__file__).resolve().parents[1]
ROOT = SCRIPTS.parent
LEDGER_TOOL = SCRIPTS / "required_step_ledger.py"
sys.path.insert(0, str(SCRIPTS))
SPEC = importlib.util.spec_from_file_location("release_evidence", SCRIPTS / "release_evidence.py")
assert SPEC and SPEC.loader
release_evidence = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(release_evidence)
import verify_ios_release_artifacts as verifier  # noqa: E402


IDENTITY_DIGESTS = [
    "requiredInputsDigest", "toolchainDigest", "projectInputsDigest", "projectDigest",
    "runtimeCapabilitiesDigest", "compatibilityDigest", "modelCatalogDigest",
    "orchestrationContractDigest", "releaseContractDigest",
]


class ReleaseEvidenceTests(unittest.TestCase):
    VERIFY_TEMPLATES = {
        "fixture-verify-v1": ["/usr/bin/true"],
        "macos-artifact-verification-with-cli-v2": ["/usr/bin/true", "--include-cli"],
        "macos-artifact-verification-with-cli-pkg-v3": ["/usr/bin/true", "--include-cli", "--include-pkg"],
    }

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
                        # The release contract's artifact-verification template identities: the
                        # app only, the CLI DMG folder, and the CLI DMG with its installer package.
                        "verify": [{
                            "id": template_id,
                            "argv": argv,
                            "outputs": ["build/dist/macos/verification-summary.json"],
                        } for template_id, argv in self.VERIFY_TEMPLATES.items()],
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

    def create_managed_ledger(self, ledger: Path | None = None,
                              verify_template: str = "macos-artifact-verification-with-cli-pkg-v3") -> Path:
        """A managed run whose verify step ran `verify_template` (by default, as release.yml does)."""
        ledger = ledger or self.ledger
        self.ledger_tool(
            "init", "--ledger", str(ledger), "--workflow", "release-macos-fixture",
            "--run-id", "fixture", "--source-identity", str(self.source_identity),
        )
        for step, argv in (("build", ["/usr/bin/true"]), ("verify", self.VERIFY_TEMPLATES[verify_template])):
            self.ledger_tool(
                "run", "--ledger", str(ledger), "--step", step,
                "--timeout-seconds", "5", "--cwd", str(self.root), "--", *argv,
            )
        self.ledger_tool("finalize", "--ledger", str(ledger))
        return ledger

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

    # The CLI ships one sealed payload twice: a DMG smoke-checked by `cli_package.py smoke` and an
    # installer package checked by `cli_package.py pkg-verify`; both reports travel as artifacts.
    MANIFEST_SHA256 = "4" * 64

    def cli_release(self) -> dict[str, str]:
        return {"marketingVersion": "2.1.0", "buildNumber": "18", "commitSHA": self.commit}

    def write_cli_fixture(self, *, signature: str = "developer-id-installer",
                          notarization: str = "stapled") -> list[Path]:
        """The CLI DMG, the installer package and both reports, as the release step leaves them."""
        cli_dmg = self.output / "Vocello-macos26-cli.dmg"
        cli_pkg = self.output / "Vocello-macos26-cli.pkg"
        cli_dmg.write_bytes(b"cli dmg fixture")
        cli_pkg.write_bytes(b"xar! cli installer fixture")
        dmg_report = {
            "schemaVersion": 1, "status": "passed", "release": self.cli_release(),
            "manifestSHA256": self.MANIFEST_SHA256, "fileCount": 20,
            "checks": ["content-integrity", "arm64", "system-linkage", "embedded-version", "embedded-build",
                       "json-modes", "bundled-speakers", "usage-exit-status", "checkout-independent-cwd"],
            "generationQualification": "not-performed",
            "artifact": {"name": cli_dmg.name, "bytes": cli_dmg.stat().st_size,
                         "sha256": release_evidence.digest_file(cli_dmg)},
        }
        dmg_report_path = self.output / release_evidence.CLI_VERIFICATION_NAME
        dmg_report_path.write_text(json.dumps(dmg_report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        self.write_pkg_report(self.pkg_report(signature=signature, notarization=notarization))
        return [cli_dmg, dmg_report_path, cli_pkg, self.output / release_evidence.CLI_PKG_VERIFICATION_NAME]

    def pkg_report(self, *, signature: str = "developer-id-installer", notarization: str = "stapled",
                   install_checks: bool = True) -> dict:
        """What `cli_package.py pkg-verify` writes for the fixture package."""
        package = release_evidence.cli_package
        cli_pkg = self.output / "Vocello-macos26-cli.pkg"
        checks = [*package.PKG_CHECKS, *(package.PKG_INSTALL_CHECKS if install_checks else ())]
        return {
            "schemaVersion": 1, "status": "passed", "release": self.cli_release(),
            "manifestSHA256": self.MANIFEST_SHA256, "fileCount": 20,
            "package": {"identifier": "com.qwenvoice.cli", "version": "2.1.0",
                        "installLocation": "/usr/local/lib/vocello", "hostArchitectures": ["arm64"],
                        "minimumOS": "26.0", "relocatableBundles": 0,
                        "scriptDigests": {name: "5" * 64 for name in package.PKG_SCRIPT_SOURCES}},
            "signature": signature, "notarization": notarization, "installTest": "not-performed",
            "checks": checks, "generationQualification": "not-performed",
            "artifact": {"name": cli_pkg.name, "bytes": cli_pkg.stat().st_size,
                         "sha256": release_evidence.digest_file(cli_pkg)},
        }

    def write_pkg_report(self, report: dict) -> None:
        path = self.output / release_evidence.CLI_PKG_VERIFICATION_NAME
        path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def create_with(self, artifacts: list[Path], *, rehearsal: bool = False, ledger: Path | None = None) -> None:
        release_evidence.create(
            self.root, self.output, "v2.1.0", self.commit, "macos", [self.dmg, self.step_summary, *artifacts],
            self.metadata, 1_700_000_000, self.source_identity, ledger or self.ledger, require_tag_ref=False,
            rehearsal=rehearsal,
        )

    def assert_refused(self, artifacts: list[Path], message: str, *, rehearsal: bool = False,
                       ledger: Path | None = None) -> None:
        with self.assertRaisesRegex(ValueError, message):
            self.create_with(artifacts, rehearsal=rehearsal, ledger=ledger)
        for name in (release_evidence.EVIDENCE_NAME, release_evidence.CHECKSUM_NAME,
                     release_evidence.VERIFICATION_BUNDLE_NAME):
            self.assertFalse((self.output / name).exists(), name)

    def installer_case(self) -> tuple[dict, dict, list[dict], dict]:
        """A passing installer report with the evidence rows and DMG report it is checked against."""
        cli = self.write_cli_fixture()
        artifacts = [{"name": path.name, "kind": "artifact", "bytes": path.stat().st_size,
                      "sha256": release_evidence.digest_file(path)} for path in cli]
        dmg_report = json.loads(cli[1].read_text(encoding="utf-8"))
        return self.pkg_report(), {**self.cli_release(), "tag": "v2.1.0"}, artifacts, dmg_report

    def test_cli_installer_package_and_report_bind_into_release_evidence(self) -> None:
        self.create()
        sboms = {name: (self.output / name).read_bytes()
                 for name in ("vocello-macos.spdx.json", "vocello-macos.cdx.json")}
        cli = self.write_cli_fixture()
        self.create_with(cli)
        evidence = release_evidence.validate(self.output, source_root=self.root)
        # The release's one dependency inventory covers the installer as it covers both DMGs.
        self.assertEqual({name: (self.output / name).read_bytes() for name in sboms}, sboms)
        self.assertEqual({item["name"] for item in evidence["sboms"]}, set(sboms))
        named = {item["name"]: item for item in evidence["artifacts"]}
        for path in cli:
            self.assertEqual(named[path.name]["kind"], "artifact")
            self.assertEqual(named[path.name]["sha256"], release_evidence.digest_file(path))
        sums = (self.output / release_evidence.CHECKSUM_NAME).read_text(encoding="utf-8")
        self.assertIn("  Vocello-macos26-cli.pkg\n", sums)
        self.assertIn("  cli-pkg-verification.json\n", sums)
        # Release evidence needs the root-free install checks; a rehearsal may go without them.
        self.write_pkg_report(self.pkg_report(install_checks=False))
        self.assert_refused(cli, "with its root-free install")
        self.create_with(cli, rehearsal=True)
        release_evidence.validate(self.output, rehearsal=True)
        with self.assertRaisesRegex(ValueError, "with its root-free install"):
            release_evidence.validate(self.output)

    def test_cli_evidence_needs_the_verification_that_installs_the_package(self) -> None:
        cli = self.write_cli_fixture()
        # The ledger's verify step ran without --include-pkg (or without the CLI at all).
        for template in ("fixture-verify-v1", "macos-artifact-verification-with-cli-v2"):
            with self.subTest(template=template):
                ledger = self.create_managed_ledger(
                    self.root / f"build/artifacts/{template}/required-steps.json", template)
                self.assert_refused(cli, "macos-artifact-verification-with-cli-pkg-v3", ledger=ledger)
                self.assert_refused(cli, "macos-artifact-verification-with-cli-pkg-v3", ledger=ledger,
                                    rehearsal=True)
                # App-only evidence needs neither.
                release_evidence.create(
                    self.root, self.output, "v2.1.0", self.commit, "macos", [self.dmg, self.step_summary],
                    self.metadata, 1_700_000_000, self.source_identity, ledger, require_tag_ref=False)
                release_evidence.validate(self.output)
        # Evidence that skipped the binding when it was created still fails validation.
        ledger = self.root / "build/artifacts/fixture-verify-v1/required-steps.json"
        with mock.patch.object(release_evidence, "required_command_templates", return_value=frozenset()):
            self.create_with(cli, ledger=ledger)
        with self.assertRaisesRegex(ValueError, "macos-artifact-verification-with-cli-pkg-v3"):
            release_evidence.validate(self.output)
        # A CLI DMG is verified at least by the CLI DMG template.
        self.assertEqual(release_evidence.required_command_templates("macos", ["Vocello-macos26-cli.dmg"]),
                         {"macos-artifact-verification-with-cli-v2", "macos-artifact-verification-with-cli-pkg-v3"})
        self.assertEqual(release_evidence.required_command_templates("ios", ["Vocello-macos26-cli.pkg"]), set())

    def test_cli_dmg_without_its_installer_package_or_report_cannot_publish(self) -> None:
        cli_dmg, dmg_report, cli_pkg, pkg_report = self.write_cli_fixture()
        self.assert_refused([cli_dmg, dmg_report, pkg_report], "requires its installer package")
        self.assert_refused([cli_dmg, dmg_report, cli_pkg], "requires its verification report")
        self.assert_refused([cli_pkg, pkg_report], "requires the CLI DMG")
        self.assert_refused([cli_dmg, cli_pkg, pkg_report], "requires its managed verification report")
        # App-only evidence still carries no CLI at all.
        self.create()
        release_evidence.validate(self.output)

    def test_cli_installer_report_for_another_package_cannot_publish(self) -> None:
        cli = self.write_cli_fixture()
        cli[2].write_bytes(b"xar! a rebuilt installer the report never checked")
        self.assert_refused(cli, "package binding mismatch")
        # Renamed away from the CLI DMG it shares a payload with.
        cli = self.write_cli_fixture()
        report = self.pkg_report()
        other = self.output / "Other-cli.pkg"
        cli[2].rename(other)
        report["artifact"] = {"name": other.name, "bytes": other.stat().st_size,
                              "sha256": release_evidence.digest_file(other)}
        self.write_pkg_report(report)
        self.assert_refused([cli[0], cli[1], other, cli[3]], "package binding mismatch")

    def test_unsigned_cli_installer_is_rehearsal_only(self) -> None:
        cli = self.write_cli_fixture(signature="unsigned", notarization="not-performed")
        self.assert_refused(cli, "Developer ID Installer signed, stapled")
        self.create_with(cli, rehearsal=True)
        release_evidence.validate(self.output, rehearsal=True)
        with self.assertRaisesRegex(ValueError, "Developer ID Installer signed, stapled"):
            release_evidence.validate(self.output)
        with self.assertRaisesRegex(ValueError, "never promoted"):
            release_evidence.validate(self.output, source_root=self.root, rehearsal=True)
        # Signed but not notarized is still not a release candidate.
        self.write_cli_fixture(signature="developer-id-installer", notarization="not-performed")
        self.assert_refused(cli, "Developer ID Installer signed, stapled")
        self.create_with(cli, rehearsal=True)
        # A stapled ticket on an unsigned package is no valid claim, rehearsal or not.
        self.write_cli_fixture(signature="unsigned", notarization="stapled")
        self.assert_refused(cli, "claim is invalid", rehearsal=True)

    def test_command_line_rehearsal_flag_reaches_create_and_validate(self) -> None:
        cli = self.write_cli_fixture(signature="unsigned", notarization="not-performed")
        command = [
            "python3", str(SCRIPTS / "release_evidence.py"), "create",
            "--root", str(self.root), "--tag", "v2.1.0", "--commit", self.commit,
            "--platform", "macos", "--source-date-epoch", "1700000000", "--output-dir", str(self.output),
            "--artifact", str(self.dmg), "--artifact", str(self.step_summary),
            *[argument for path in cli for argument in ("--artifact", str(path))],
            "--metadata", str(self.metadata), "--source-identity", str(self.source_identity),
            "--step-ledger", str(self.ledger), "--allow-missing-tag-ref",
        ]
        refused = subprocess.run(command, text=True, capture_output=True, check=False)
        self.assertNotEqual(refused.returncode, 0)
        self.assertIn("Developer ID Installer", refused.stderr)
        self.assertFalse((self.output / release_evidence.CHECKSUM_NAME).exists())
        created = subprocess.run([*command, "--rehearsal"], text=True, capture_output=True, check=False)
        self.assertEqual(created.returncode, 0, created.stderr)
        validate = ["python3", str(SCRIPTS / "release_evidence.py"), "validate", "--output-dir", str(self.output)]
        self.assertNotEqual(subprocess.run(validate, capture_output=True, check=False).returncode, 0)
        rehearsal = subprocess.run([*validate, "--rehearsal"], text=True, capture_output=True, check=False)
        self.assertEqual(rehearsal.returncode, 0, rehearsal.stderr)

    def test_sha256sums_and_listed_assets_must_name_the_installer(self) -> None:
        cli = self.write_cli_fixture()
        self.create_with(cli)
        sums = self.output / release_evidence.CHECKSUM_NAME
        original = sums.read_text(encoding="utf-8")
        for name in ("Vocello-macos26-cli.pkg", release_evidence.CLI_PKG_VERIFICATION_NAME):
            with self.subTest(name=name):
                sums.write_text("".join(line + "\n" for line in original.splitlines()
                                        if not line.endswith("  " + name)), encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "SHA256SUMS does not exactly match"):
                    release_evidence.validate(self.output)
        sums.write_text(original, encoding="utf-8")
        listing = {"assets": [
            {"name": entry.name, "digest": "sha256:" + release_evidence.digest_file(entry)}
            for entry in sorted(self.output.iterdir()) if entry.name != "Vocello-macos26-cli.pkg"
        ]}
        with self.assertRaisesRegex(ValueError, "differ from the checked files"):
            release_evidence.match_assets(listing, self.output)
        # A missing installer file fails the evidence before any CLI rule.
        cli[2].unlink()
        with self.assertRaisesRegex(ValueError, "release evidence mismatch: Vocello-macos26-cli.pkg"):
            release_evidence.validate(self.output)

    def test_cli_installer_report_is_structurally_release_bound(self) -> None:
        payload, release, artifacts, dmg_report = self.installer_case()
        release_evidence.validate_cli_installer_verification(payload, release, artifacts, dmg_report)

        def drop(key: str):
            return lambda value: value.pop(key)

        team = "Vocello-A1B2C3D4E5-cli.pkg"
        for label, mutation, message in (
            ("unknown field", lambda value: value.update(teamIdentifier="unknown"), "unexpected or missing"),
            ("missing field", drop("installTest"), "unexpected or missing"),
            ("unknown package field", lambda value: value["package"].update(teamID="x"), "malformed package facts"),
            ("unknown artifact field", lambda value: value["artifact"].update(path="x"), "malformed package identity"),
            ("schema", lambda value: value.update(schemaVersion=2), "source/status"),
            ("status", lambda value: value.update(status="failed"), "source/status"),
            ("build", lambda value: value["release"].update(buildNumber="19"), "source/status"),
            ("commit", lambda value: value["release"].update(commitSHA="0" * 40), "source/status"),
            ("package size", lambda value: value["artifact"].update(bytes=1), "binding mismatch"),
            ("package digest", lambda value: value["artifact"].update(sha256="0" * 64), "binding mismatch"),
            ("manifest", lambda value: value.update(manifestSHA256="6" * 64), "CLI DMG's sealed payload"),
            ("file count", lambda value: value.update(fileCount=19), "CLI DMG's sealed payload"),
            ("identifier", lambda value: value["package"].update(identifier="com.qwenvoice.app"), "identity"),
            ("version", lambda value: value["package"].update(version="2.0.0"), "identity"),
            ("location", lambda value: value["package"].update(installLocation="/usr/local/vocello"), "identity"),
            ("architectures", lambda value: value["package"].update(hostArchitectures=["arm64", "x86_64"]),
             "architecture"),
            ("minimum", lambda value: value["package"].update(minimumOS="latest"), "identity"),
            ("relocatable", lambda value: value["package"].update(relocatableBundles=1), "relocation"),
            ("relocatable bool", lambda value: value["package"].update(relocatableBundles=False), "relocation"),
            ("scripts", lambda value: value["package"]["scriptDigests"].update(uninstall="5" * 64), "identity"),
            ("checks reordered", lambda value: value["checks"].reverse(), "checks differ"),
            ("checks partial", lambda value: value["checks"].pop(), "checks differ"),
            ("no root-free install", lambda value: value.update(checks=list(release_evidence.cli_package.PKG_CHECKS)),
             "with its root-free install"),
            ("install test", lambda value: value.update(installTest="passed"), "install test"),
            ("generation", lambda value: value.update(generationQualification="passed"), "generation"),
            ("unknown signature", lambda value: value.update(signature="ad-hoc"), "claim is invalid"),
            ("absolute path", lambda value: value["artifact"].update(name="/Users/example/Vocello-macos26-cli.pkg"),
             "absolute path"),
            ("home path", lambda value: value["package"].update(minimumOS="~/fixture"), "absolute path"),
            ("team id", lambda value: value["artifact"].update(name=team), "Team ID"),
        ):
            with self.subTest(label=label):
                tampered = copy.deepcopy(payload)
                mutation(tampered)
                with self.assertRaisesRegex(ValueError, message):
                    release_evidence.validate_cli_installer_verification(tampered, release, artifacts, dmg_report)

        # A rehearsal may carry the package checks alone, but not a partial or reordered list.
        package_checks = list(release_evidence.cli_package.PKG_CHECKS)
        release_evidence.validate_cli_installer_verification(
            dict(payload, checks=package_checks), release, artifacts, dmg_report, rehearsal=True)
        for checks in (package_checks[:-1], list(reversed(payload["checks"]))):
            with self.assertRaisesRegex(ValueError, "checks differ"):
                release_evidence.validate_cli_installer_verification(
                    dict(payload, checks=checks), release, artifacts, dmg_report, rehearsal=True)

        # The DMG's report is the authority on the payload both forms carry.
        other_payload = dict(dmg_report, manifestSHA256="6" * 64)
        with self.assertRaisesRegex(ValueError, "CLI DMG's sealed payload"):
            release_evidence.validate_cli_installer_verification(payload, release, artifacts, other_payload)
        # Exactly one installer package, published as an artifact.
        package_row = next(row for row in artifacts if row["name"].endswith("-cli.pkg"))
        for rows in ([*artifacts, dict(package_row, name="Second-cli.pkg")],
                     [dict(row, kind="metadata") if row is package_row else row for row in artifacts]):
            with self.assertRaisesRegex(ValueError, "binding mismatch"):
                release_evidence.validate_cli_installer_verification(payload, release, rows, dmg_report)

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

    def test_promotion_binds_the_evidence_to_the_checked_out_source(self) -> None:
        self.create()
        release_evidence.validate(self.output, source_root=self.root)
        # A contract that differs from the checkout's, though consistent with its own digests.
        original = self.release_contract.read_text(encoding="utf-8")
        self.release_contract.write_text(original + "\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "differs from the checked-out source"):
            release_evidence.validate(self.output, source_root=self.root)
        self.release_contract.write_text(original, encoding="utf-8")
        # Evidence for another commit than the one checked out.
        subprocess.run(["git", "-C", str(self.root), "commit", "-q", "--allow-empty", "-m", "later"], check=True)
        with self.assertRaisesRegex(ValueError, "does not name the checked-out commit"):
            release_evidence.validate(self.output, source_root=self.root)

    def test_promotion_publishes_only_assets_the_evidence_names(self) -> None:
        self.create()
        (self.output / "quality-promotion.json").write_text("{}\n", encoding="utf-8")
        release_evidence.validate(self.output, exact_extra=["quality-promotion.json"])
        stray = self.output / "Vocello.zip"
        stray.write_bytes(b"never checked")
        with self.assertRaisesRegex(ValueError, "unexpected=\\['Vocello.zip'\\]"):
            release_evidence.validate(self.output, exact_extra=["quality-promotion.json"])
        stray.unlink()
        (self.output / "quality-promotion.json").unlink()
        with self.assertRaisesRegex(ValueError, "missing=\\['quality-promotion.json'\\]"):
            release_evidence.validate(self.output, exact_extra=["quality-promotion.json"])

    def test_listed_assets_must_be_the_checked_files_digest_for_digest(self) -> None:
        self.create()
        names = sorted(entry.name for entry in self.output.iterdir())
        listing = {"assets": [
            {"name": name, "digest": "sha256:" + release_evidence.digest_file(self.output / name)}
            for name in names
        ]}
        self.assertEqual(release_evidence.match_assets(listing, self.output), names)
        swapped = json.loads(json.dumps(listing))
        swapped["assets"][0]["digest"] = "sha256:" + "0" * 64
        with self.assertRaisesRegex(ValueError, "differs from the checked file"):
            release_evidence.match_assets(swapped, self.output)
        extra = json.loads(json.dumps(listing))
        extra["assets"].append({"name": "late.dmg", "digest": "sha256:" + "1" * 64})
        with self.assertRaisesRegex(ValueError, "differ from the checked files"):
            release_evidence.match_assets(extra, self.output)
        repeated = json.loads(json.dumps(listing))
        repeated["assets"].append(dict(listing["assets"][0]))
        with self.assertRaisesRegex(ValueError, "repeated"):
            release_evidence.match_assets(repeated, self.output)

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
        # Built by the verifier's own summary_payload, so the evidence validator is
        # tested against the shape a release run actually writes.
        release = {"marketingVersion": "2.1.0", "buildNumber": "18"}
        expected = verifier.ExpectedIOSIdentity(
            bundle_identifier="com.patricedery.vocello",
            marketing_version="2.1.0",
            build_number="18",
            application_groups=("group.com.patricedery.vocello.shared",),
            increased_memory_limit=True,
            privacy_manifest_sha256="1" * 64,
            attribution_manifest_sha256="2" * 64,
        )
        archived = verifier.BundleSnapshot(
            label="archive",
            bundle_identifier=expected.bundle_identifier,
            marketing_version=expected.marketing_version,
            build_number=expected.build_number,
            architectures=("arm64",),
            required_device_capabilities=verifier.REQUIRED_DEVICE_CAPABILITIES,
            macho_uuids=("AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE",),
            executable_sha256="b" * 64,
            signature_normalized_executable_sha256="9" * 64,
            bundle_sha256="c" * 64,
            signature_verified=True,
            signing_authority_verified=True,
            signing_certificate_trust_verified=True,
            distribution_authority_verified=False,
            team_identifier_verified=True,
            provisioning_profile_verified=True,
            signer_profile_certificate_match=True,
            application_identifier_verified=True,
            application_groups=expected.application_groups,
            increased_memory_limit=True,
            get_task_allow=True,
            privacy_manifest_sha256=expected.privacy_manifest_sha256,
            privacy_manifest_verified=True,
            attribution_manifest_sha256=expected.attribution_manifest_sha256,
            attribution_manifest_verified=True,
        )
        # App Store export can re-sign the Mach-O, changing its byte digest while
        # preserving the executable UUID and product identity.
        exported = dataclasses.replace(
            archived,
            label="export",
            executable_sha256="f" * 64,
            bundle_sha256="d" * 64,
            distribution_authority_verified=True,
            get_task_allow=False,
        )
        payload = verifier.summary_payload("Vocello.ipa", "a" * 64, expected, archived, exported)
        artifacts = [
            {"name": "export/Vocello.ipa", "kind": "artifact", "sha256": "a" * 64},
            {
                "name": release_evidence.IOS_ARTIFACT_VERIFICATION_NAME,
                "kind": "artifact",
                "sha256": "e" * 64,
            },
        ]
        return payload, release, artifacts

    def test_ios_capability_floor_matches_the_verifier(self) -> None:
        self.assertEqual(release_evidence.IOS_REQUIRED_DEVICE_CAPABILITIES,
                         sorted(verifier.REQUIRED_DEVICE_CAPABILITIES))

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
            ("attribution manifest", lambda value: value["export"].update(attributionManifestSHA256="7" * 64), "failed"),
            ("attribution check", lambda value: value["archive"].update(attributionManifestVerified=False), "failed"),
            ("capabilities", lambda value: value["export"].update(requiredDeviceCapabilities=["arm64"]), "failed"),
            ("both capabilities", lambda value: [value[label].update(requiredDeviceCapabilities=["arm64"])
                                                 for label in ("archive", "export")], "failed"),
            ("hygiene", lambda value: value["releaseHygiene"].update(dSYMUUIDMatch=False), "hygiene"),
            ("unknown field", lambda value: value.update(extra=True), "malformed"),
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
