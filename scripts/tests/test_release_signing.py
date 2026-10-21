"""Release re-signing of the code nested in the app's frameworks, and its packaged-bundle check.

`release_sign_framework` (scripts/lib/release_signing.sh, sourced by scripts/release.sh) runs
over fabricated framework trees whose code files carry a Mach-O header, with a recording
`run_codesign` in place of the release identity, so the tests see what is signed, in which
order, and what is removed. scripts/verify_release_bundle.sh runs from a sandbox
(scripts/tests/shell_stubs.py) whose `codesign` answers from a table of fabricated signatures;
in signed mode it holds every Mach-O under Contents except the app's own executable to the
release team, the hardened runtime and no entitlements. `release_notarize`, the one
notarization path of both DMGs and the CLI installer package, runs over a recording `xcrun`
whose notary verdict each test chooses, and `release_pkg_signer` over recorded
`pkgutil --check-signature` listings.
"""

from __future__ import annotations

import os
import plistlib
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from shell_stubs import ScriptSandbox, quote

ROOT = Path(__file__).resolve().parents[2]
LIBRARY = ROOT / "scripts/lib/release_signing.sh"
# A 64-bit arm64 executable's Mach-O header; `file` reports it as Mach-O.
MACHO = bytes.fromhex("cffaedfe0c000001000000000200000000000000000000000000000000000000")
TEAM = "TEAM123456"


def file_reports_macho() -> bool:
    if not Path("/usr/bin/file").exists():
        return False
    with tempfile.NamedTemporaryFile() as probe:
        probe.write(MACHO)
        probe.flush()
        result = subprocess.run(["/usr/bin/file", "-b", probe.name], capture_output=True, text=True, check=False)
    return "Mach-O" in result.stdout


FILE_READS_MACHO = file_reports_macho()


def macho(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(MACHO)
    path.chmod(0o755)


def text(path: Path, value: str = "fixture") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")


def sparkle_framework(frameworks: Path, *, xpc_services: bool = True) -> Path:
    """Sparkle.framework as the SwiftPM binary target ships it: versioned, with top-level links."""
    framework = frameworks / "Sparkle.framework"
    version = framework / "Versions/B"
    macho(version / "Sparkle")
    macho(version / "Autoupdate")
    macho(version / "Updater.app/Contents/MacOS/Updater")
    text(version / "Updater.app/Contents/Info.plist")
    text(version / "Updater.app/Contents/Resources/Base.lproj/Main.nib")
    text(version / "Resources/Info.plist")
    text(version / "Resources/SUUpdateAlert.nib")
    links = ["Sparkle", "Autoupdate", "Updater.app", "Resources"]
    if xpc_services:
        for service in ("Installer", "Downloader"):
            macho(version / f"XPCServices/{service}.xpc/Contents/MacOS/{service}")
            text(version / f"XPCServices/{service}.xpc/Contents/Info.plist")
        links.append("XPCServices")
    (framework / "Versions/Current").symlink_to("B")
    for name in links:
        (framework / name).symlink_to(f"Versions/Current/{name}")
    return framework


def plain_framework(frameworks: Path, name: str = "QwenVoiceCore") -> Path:
    framework = frameworks / f"{name}.framework"
    macho(framework / f"Versions/A/{name}")
    text(framework / "Versions/A/Resources/Info.plist")
    text(framework / "Versions/A/Resources/contract.json", "{}")
    (framework / "Versions/Current").symlink_to("A")
    (framework / name).symlink_to(f"Versions/Current/{name}")
    return framework


@unittest.skipUnless(FILE_READS_MACHO, "file(1) is missing or does not recognize a Mach-O header")
class ReleaseSignFrameworkTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="vocello release signing ")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.frameworks = self.root / "Vocello.app/Contents/Frameworks"
        self.log = self.root / "codesign.log"

    def sign(self, framework: Path, fail_on: str = "") -> tuple[subprocess.CompletedProcess[str], list[tuple[str, str]]]:
        script = (
            "set -euo pipefail\n"
            f". {quote(LIBRARY)}\n"
            "run_codesign() {\n"
            f"  printf '%s\\t%s\\n' \"$1\" \"${{*:2}}\" >> {quote(self.log)}\n"
            '  [ "$1" != "${FAIL_ON:-}" ]\n'
            "}\n"
            f"release_sign_framework {quote(framework)}\n"
        )
        completed = subprocess.run(
            ["bash", "-c", script], env={**os.environ, "FAIL_ON": fail_on, "TMPDIR": str(self.root)},
            capture_output=True, text=True, timeout=60, check=False,
        )
        calls = []
        if self.log.exists():
            for line in self.log.read_text(encoding="utf-8").splitlines():
                target, arguments = line.split("\t", 1)
                calls.append((os.path.relpath(target, self.frameworks), arguments))
        return completed, calls

    def test_sparkle_is_signed_inside_out_without_its_xpc_services(self) -> None:
        framework = sparkle_framework(self.frameworks)
        completed, calls = self.sign(framework)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        targets = [target for target, _ in calls]
        self.assertEqual(sorted(targets[:-1]), [
            "Sparkle.framework/Versions/B/Autoupdate",
            "Sparkle.framework/Versions/B/Updater.app",
        ])
        self.assertEqual(targets[-1], "Sparkle.framework")
        # Hardened runtime and no entitlements on every nested signature and the framework.
        self.assertEqual({arguments for _, arguments in calls}, {"--options runtime"})
        # The services and the top-level link to them are gone; nothing else is.
        self.assertFalse((framework / "Versions/B/XPCServices").exists())
        self.assertFalse((framework / "XPCServices").is_symlink())
        for kept in ("Versions/B/Autoupdate", "Versions/B/Updater.app/Contents/MacOS/Updater",
                     "Versions/B/Resources/SUUpdateAlert.nib", "Autoupdate", "Updater.app"):
            self.assertTrue((framework / kept).exists(), kept)
        # Leftover files from a temporary listing would ship inside the bundle or the scratch.
        self.assertEqual(sorted(path.name for path in self.root.iterdir()), ["Vocello.app", "codesign.log"])

    def test_already_pruned_sparkle_signs_the_same_code(self) -> None:
        completed, calls = self.sign(sparkle_framework(self.frameworks, xpc_services=False))
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(sorted(target for target, _ in calls), [
            "Sparkle.framework",
            "Sparkle.framework/Versions/B/Autoupdate",
            "Sparkle.framework/Versions/B/Updater.app",
        ])

    def test_code_nested_in_a_nested_bundle_is_signed_before_that_bundle(self) -> None:
        framework = sparkle_framework(self.frameworks)
        macho(framework / "Versions/B/Updater.app/Contents/Frameworks/libhelper.dylib")
        completed, calls = self.sign(framework)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        targets = [target for target, _ in calls]
        helper = targets.index("Sparkle.framework/Versions/B/Updater.app/Contents/Frameworks/libhelper.dylib")
        self.assertLess(helper, targets.index("Sparkle.framework/Versions/B/Updater.app"))
        self.assertEqual(targets[-1], "Sparkle.framework")

    def test_a_framework_without_nested_code_is_signed_as_before(self) -> None:
        framework = plain_framework(self.frameworks)
        completed, calls = self.sign(framework)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(calls, [("QwenVoiceCore.framework", "--options runtime")])
        self.assertTrue((framework / "Versions/A/Resources/contract.json").exists())

    def test_any_other_nested_mach_o_is_signed_rather_than_left_ad_hoc(self) -> None:
        framework = plain_framework(self.frameworks, "Vendor")
        macho(framework / "Versions/A/Resources/libextra.dylib")
        macho(framework / "Versions/A/Helpers/vendor-tool")
        completed, calls = self.sign(framework)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(sorted(target for target, _ in calls[:-1]), [
            "Vendor.framework/Versions/A/Helpers/vendor-tool",
            "Vendor.framework/Versions/A/Resources/libextra.dylib",
        ])
        self.assertEqual(calls[-1][0], "Vendor.framework")

    def test_xpc_services_of_another_framework_are_signed_not_removed(self) -> None:
        framework = plain_framework(self.frameworks, "Vendor")
        macho(framework / "Versions/A/XPCServices/Helper.xpc/Contents/MacOS/Helper")
        completed, calls = self.sign(framework)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn(("Vendor.framework/Versions/A/XPCServices/Helper.xpc", "--options runtime"), calls)

    def test_a_signing_failure_stops_before_the_framework(self) -> None:
        framework = sparkle_framework(self.frameworks)
        completed, calls = self.sign(framework, fail_on=str(framework / "Versions/B/Autoupdate"))
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("could not sign Versions/B/Autoupdate inside Sparkle.framework", completed.stderr)
        self.assertNotIn("Sparkle.framework", [target for target, _ in calls])


@unittest.skipUnless(FILE_READS_MACHO and Path("/usr/libexec/PlistBuddy").exists(),
                     "PlistBuddy or a Mach-O-aware file(1) is not installed")
class VerifyReleaseBundleNestedCodeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.sandbox = ScriptSandbox(self, "scripts/verify_release_bundle.sh", {
            "scripts/lib/shared.sh": None,
            "scripts/lib/release_signing.sh": None,
            "config/apple-platform-capability-matrix.json": None,
        })
        self.sandbox.executable("scripts/check_backend_resource_contract.sh")
        # The allowlist check fails for any path listed in `entitled`.
        self.sandbox.helper("scripts/entitlement_contract.py", (
            'bundle="${@: -1}"\n'
            'if [ -f "$QV_SANDBOX/entitled" ] && grep -qxF "$bundle" "$QV_SANDBOX/entitled"; then exit 1; fi'
        ))
        # `codesign -dv` answers from signatures.tsv (path, team, runtime); anything else is ad hoc.
        self.sandbox.tool("codesign", (
            'target="${@: -1}"\n'
            'case " $* " in\n'
            '  *" --verify "*) exit 0 ;;\n'
            '  *" -dv "*)\n'
            "    row=\"$(awk -F'\\t' -v t=\"$target\" '$1 == t { print; exit }' \"$QV_SANDBOX/signatures.tsv\")\"\n"
            '    team="$(printf "%s" "$row" | cut -f2)"\n'
            '    runtime="$(printf "%s" "$row" | cut -f3)"\n'
            '    echo "Executable=$target" >&2\n'
            '    echo "TeamIdentifier=${team:-not set}" >&2\n'
            # Real codesign keeps writing after the line the verifier wants.
            '    [ -z "${CODESIGN_PAUSE:-}" ] || sleep "$CODESIGN_PAUSE"\n'
            '    echo "Sealed Resources version=2 rules=13 files=4" >&2\n'
            '    [ "$runtime" != 1 ] || echo "Runtime Version=26.0.0" >&2\n'
            "    exit 0 ;;\n"
            "esac\n"
            "exit 64"
        ))
        self.app = self.sandbox.path / "dist/Vocello.app"
        contents = self.app / "Contents"
        (contents / "Resources").mkdir(parents=True)
        macho(contents / "MacOS/Vocello")
        (contents / "Info.plist").write_bytes(plistlib.dumps({
            "CFBundleExecutable": "Vocello", "CFBundleIdentifier": "com.qwenvoice.app",
            "QwenVoiceTeamIdentifier": TEAM,
        }))
        self.frameworks = contents / "Frameworks"
        self.sparkle = sparkle_framework(self.frameworks, xpc_services=False)
        self.core = plain_framework(self.frameworks)
        self.signatures: dict[Path, tuple[str, bool]] = {self.app: (TEAM, True)}
        for path in (self.sparkle, self.core, *self.nested_code()):
            self.signatures[path] = (TEAM, True)

    def nested_code(self) -> list[Path]:
        return [path for path in self.frameworks.rglob("*") if path.is_file() and not path.is_symlink()
                and path.read_bytes()[:4] == MACHO[:4]]

    def verify(self, *, signed: bool = True, **extra: str) -> subprocess.CompletedProcess[str]:
        rows = "".join(f"{path}\t{team}\t{int(runtime)}\n" for path, (team, runtime) in self.signatures.items())
        (self.sandbox.path / "signatures.tsv").write_text(rows, encoding="utf-8")
        environment = {"QWENVOICE_SKIP_LAUNCH_SMOKE": "1", "CI": "false", "QWENVOICE_EXPECT_TEAM_ID": TEAM, **extra}
        if signed:
            environment["QWENVOICE_EXPECT_SIGNED_RELEASE"] = "1"
        return self.sandbox.run_script(str(self.app), env=environment)

    def test_every_nested_mach_o_is_checked_for_team_runtime_and_entitlements(self) -> None:
        completed = self.verify()
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("[2/4] Signed release checks OK", completed.stdout)
        checked = {Path(arguments[-1]) for arguments in self.sandbox.calls_to(
            "scripts/entitlement_contract.py", "verify-bundle", "--role", "macos-framework")}
        self.assertLessEqual(set(self.nested_code()), checked)
        self.assertIn(self.sparkle / "Versions/B/Autoupdate", checked)
        self.assertIn(self.sparkle / "Versions/B/Updater.app/Contents/MacOS/Updater", checked)

    def test_ad_hoc_nested_code_fails(self) -> None:
        del self.signatures[self.sparkle / "Versions/B/Autoupdate"]
        completed = self.verify()
        self.assertEqual(completed.returncode, 1)
        self.assertIn("Nested code Frameworks/Sparkle.framework/Versions/B/Autoupdate signature Team ID mismatch",
                      completed.stderr)
        self.assertIn("got not set", completed.stderr)

    def test_nested_code_without_the_hardened_runtime_fails(self) -> None:
        self.signatures[self.sparkle / "Versions/B/Updater.app/Contents/MacOS/Updater"] = (TEAM, False)
        completed = self.verify()
        self.assertEqual(completed.returncode, 1)
        self.assertIn("Frameworks/Sparkle.framework/Versions/B/Updater.app/Contents/MacOS/Updater is missing the hardened "
                      "runtime", completed.stderr)

    def test_entitled_nested_code_fails(self) -> None:
        (self.sandbox.path / "entitled").write_text(f"{self.sparkle / 'Versions/B/Autoupdate'}\n", encoding="utf-8")
        completed = self.verify()
        self.assertEqual(completed.returncode, 1)
        self.assertIn("Nested code Frameworks/Sparkle.framework/Versions/B/Autoupdate carries unexpected entitlements",
                      completed.stderr)

    def test_codesign_output_after_the_team_line_does_not_break_the_pipe(self) -> None:
        # The team lookup reads codesign's whole output; stopping at the first match left
        # codesign writing into a closed pipe, and pipefail turned its SIGPIPE into exit 141.
        completed = self.verify(CODESIGN_PAUSE="0.2")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("[2/4] Signed release checks OK", completed.stdout)

    def framework_role_checks(self) -> list[Path]:
        return [Path(arguments[-1]) for arguments in self.sandbox.calls_to(
            "scripts/entitlement_contract.py", "verify-bundle", "--role", "macos-framework")]

    def test_mach_o_outside_frameworks_is_held_to_the_same_rules(self) -> None:
        contents = self.app / "Contents"
        helper = contents / "MacOS/vocello-helper"
        plugin = contents / "PlugIns/Importer.bundle/Contents/MacOS/Importer"
        library = contents / "Resources/libextra.dylib"
        for path in (helper, plugin, library):
            macho(path)
            self.signatures[path] = (TEAM, True)
        completed = self.verify()
        self.assertEqual(completed.returncode, 0, completed.stderr)
        checked = self.framework_role_checks()
        self.assertLessEqual({helper, plugin, library}, set(checked))
        # The app's own executable keeps the app role and its allowlisted entitlements.
        self.assertNotIn(contents / "MacOS/Vocello", checked)
        self.assertEqual(len(self.sandbox.calls_to(
            "scripts/entitlement_contract.py", "verify-bundle", "--role", "macos-app")), 1)

    def test_ad_hoc_code_outside_frameworks_fails(self) -> None:
        macho(self.app / "Contents/Resources/tool")
        completed = self.verify()
        self.assertEqual(completed.returncode, 1)
        self.assertIn("Nested code Resources/tool signature Team ID mismatch", completed.stderr)
        self.assertIn("got not set", completed.stderr)

    def test_code_outside_frameworks_without_the_hardened_runtime_or_with_entitlements_fails(self) -> None:
        helper = self.app / "Contents/MacOS/vocello-helper"
        macho(helper)
        self.signatures[helper] = (TEAM, False)
        completed = self.verify()
        self.assertEqual(completed.returncode, 1)
        self.assertIn("Nested code MacOS/vocello-helper is missing the hardened runtime", completed.stderr)
        self.signatures[helper] = (TEAM, True)
        (self.sandbox.path / "entitled").write_text(f"{helper}\n", encoding="utf-8")
        completed = self.verify()
        self.assertEqual(completed.returncode, 1)
        self.assertIn("Nested code MacOS/vocello-helper carries unexpected entitlements", completed.stderr)

    def test_unsigned_mode_does_not_check_signatures(self) -> None:
        macho(self.app / "Contents/Resources/tool")
        completed = self.verify(signed=False)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(self.framework_role_checks(), [])

    def test_sparkle_xpc_services_fail_even_unsigned(self) -> None:
        macho(self.sparkle / "Versions/B/XPCServices/Downloader.xpc/Contents/MacOS/Downloader")
        completed = self.verify(signed=False)
        self.assertEqual(completed.returncode, 1)
        self.assertIn("Sparkle.framework still contains XPCServices", completed.stderr)

    def test_a_dangling_xpc_services_link_fails(self) -> None:
        (self.sparkle / "XPCServices").symlink_to("Versions/Current/XPCServices")
        completed = self.verify(signed=False)
        self.assertEqual(completed.returncode, 1)
        self.assertIn("Sparkle.framework still contains XPCServices", completed.stderr)

    def test_an_app_without_sparkle_verifies_as_before(self) -> None:
        shutil.rmtree(self.sparkle)
        self.signatures = {path: value for path, value in self.signatures.items() if path.exists()}
        completed = self.verify()
        self.assertEqual(completed.returncode, 0, completed.stderr)
        checked = [Path(arguments[-1]) for arguments in self.sandbox.calls_to(
            "scripts/entitlement_contract.py", "verify-bundle", "--role", "macos-framework")]
        self.assertEqual(checked, [self.core, self.core / "Versions/A/QwenVoiceCore"])


ISSUER = "12345678-abcd-4def-8abc-1234567890ab"


class ReleaseNotarizeTests(unittest.TestCase):
    """`release_notarize` over a recording `xcrun`: submit, verdict, issue log, staple, validate."""

    def setUp(self) -> None:
        self.sandbox = ScriptSandbox(self, "scripts/lib/release_signing.sh", {})
        self.artifact = self.sandbox.file("dist/Vocello-macos26-cli.pkg", "package bytes")
        self.key = self.sandbox.file("keys/AuthKey_KEY1234567.p8", "fixture key")
        self.xcrun()

    def xcrun(self, *, status: str = "Accepted", submit: int = 0, staple: int = 0, validate: int = 0) -> None:
        self.sandbox.tool("xcrun", (
            'case "$1 $2" in\n'
            f'  "notarytool submit") printf "  id: sub-0001\\n  status: {status}\\n"; exit {submit} ;;\n'
            '  "notarytool log") echo "{\\"issues\\": [\\"fixture issue\\"]}"; exit 0 ;;\n'
            f'  "stapler staple") exit {staple} ;;\n'
            f'  "stapler validate") exit {validate} ;;\n'
            "esac\n"
            "exit 64"
        ))

    def notarize(self, caller: str = "release_notarize \"$ARTIFACT\"",
                 **extra: str) -> subprocess.CompletedProcess[str]:
        script = (
            "set -euo pipefail\n"
            f". {quote(self.sandbox.record)}\n"
            f". {quote(self.sandbox.script)}\n"
            f"{caller}\n"
        )
        environment = self.sandbox.environment({
            "ARTIFACT": str(self.artifact), "APPLE_API_KEY_PATH": str(self.key),
            "APPLE_API_KEY_ID": "KEY1234567", "APPLE_API_ISSUER_ID": "", **extra,
        })
        return subprocess.run(["bash", "-c", script], cwd=self.sandbox.path, env=environment,
                              capture_output=True, text=True, timeout=60, check=False)

    def xcrun_calls(self) -> list[list[str]]:
        return self.sandbox.calls_to("xcrun")

    def test_an_accepted_artifact_is_stapled_then_validated(self) -> None:
        completed = self.notarize()
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(self.xcrun_calls(), [
            ["notarytool", "submit", str(self.artifact), "--key", str(self.key), "--key-id", "KEY1234567", "--wait"],
            ["stapler", "staple", str(self.artifact)],
            ["stapler", "validate", str(self.artifact)],
        ])
        self.assertIn("Using Individual API key (no issuer).", completed.stdout)

    def test_a_team_key_passes_its_uuid_issuer_without_printing_it(self) -> None:
        completed = self.notarize(APPLE_API_ISSUER_ID=ISSUER)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        submit = self.sandbox.calls_to("xcrun", "notarytool", "submit")[0]
        self.assertEqual(submit[-3:], ["--issuer", ISSUER, "--wait"])
        self.assertNotIn(ISSUER, completed.stdout + completed.stderr)
        self.assertIn("Using Team API key (issuer present).", completed.stdout)

    def test_an_issuer_that_is_not_a_uuid_is_not_passed(self) -> None:
        completed = self.notarize(APPLE_API_ISSUER_ID="not-a-uuid")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertNotIn("--issuer", self.sandbox.calls_to("xcrun", "notarytool", "submit")[0])

    def test_a_rejected_artifact_fetches_apples_log_and_is_not_stapled(self) -> None:
        self.xcrun(status="Invalid")
        completed = self.notarize()
        self.assertEqual(completed.returncode, 1)
        self.assertIn("notarization verdict: Invalid (submission sub-0001)", completed.stderr)
        self.assertIn(["notarytool", "log", "sub-0001", "--key", str(self.key), "--key-id", "KEY1234567"],
                      self.xcrun_calls())
        self.assertIn("fixture issue", completed.stdout)
        self.assertEqual(self.sandbox.calls_to("xcrun", "stapler"), [])

    def test_a_failed_submission_is_not_stapled(self) -> None:
        self.xcrun(submit=1)
        completed = self.notarize()
        self.assertEqual(completed.returncode, 1)
        self.assertIn("notarytool submission failed", completed.stderr)
        self.assertEqual(self.sandbox.calls_to("xcrun", "stapler"), [])

    def test_a_failed_staple_fails_even_when_the_caller_suspends_set_e(self) -> None:
        # release.sh calls `release_notarize … || release_fail …`, which turns `set -e` off
        # inside the function; every step must still be checked.
        self.xcrun(staple=1)
        completed = self.notarize('release_notarize "$ARTIFACT" || { echo "caller saw the failure"; exit 3; }')
        self.assertEqual(completed.returncode, 3, completed.stderr)
        self.assertIn("caller saw the failure", completed.stdout)
        self.assertIn("could not staple", completed.stderr)
        self.assertEqual(self.sandbox.calls_to("xcrun", "stapler", "validate"), [])

    def test_a_ticket_that_does_not_validate_fails(self) -> None:
        self.xcrun(validate=1)
        completed = self.notarize('release_notarize "$ARTIFACT" || exit 3')
        self.assertEqual(completed.returncode, 3)
        self.assertIn("does not validate", completed.stderr)

    def test_a_missing_artifact_is_never_submitted(self) -> None:
        completed = self.notarize(ARTIFACT=str(self.sandbox.path / "dist/missing.pkg"))
        self.assertEqual(completed.returncode, 1)
        self.assertEqual(self.xcrun_calls(), [])


SIGNED_LISTING = """Package "Vocello-macos26-cli.pkg":
   Status: signed by a developer certificate issued by Apple for distribution
   Signed with a trusted timestamp on: 2026-10-21 12:00:00 +0000
   Certificate Chain:
    1. {leaf}
       Expires: 2031-10-21 12:00:00 +0000
       SHA256 Fingerprint:
           00 11 22
       ------------------------------------------------------------------------
    2. Developer ID Certification Authority
       Expires: 2031-09-17 00:00:00 +0000
    3. Apple Root CA
"""


class ReleasePkgSignerTests(unittest.TestCase):
    """`release_pkg_signer` names the leaf certificate only for an Apple-issued distribution signature."""

    def signer(self, listing: str, status: int = 0) -> subprocess.CompletedProcess[str]:
        sandbox = ScriptSandbox(self, "scripts/lib/release_signing.sh", {})
        sandbox.file("listing.txt", listing)
        sandbox.tool("pkgutil", f'cat "$QV_SANDBOX/listing.txt"\nexit {status}')
        script = f"set -euo pipefail\n. {quote(sandbox.record)}\n. {quote(sandbox.script)}\nrelease_pkg_signer fixture.pkg\n"
        return subprocess.run(["bash", "-c", script], cwd=sandbox.path, env=sandbox.environment(),
                              capture_output=True, text=True, timeout=60, check=False)

    def test_a_developer_id_installer_signature_names_its_leaf(self) -> None:
        leaf = f"Developer ID Installer: Fixture ({TEAM})"
        completed = self.signer(SIGNED_LISTING.format(leaf=leaf))
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stdout, leaf + "\n")

    def test_an_unsigned_package_has_no_signer(self) -> None:
        completed = self.signer('Package "fixture.pkg":\n   Status: no signature\n', status=1)
        self.assertEqual(completed.returncode, 1)
        self.assertEqual(completed.stdout, "")

    def test_a_signature_apple_did_not_issue_for_distribution_has_no_signer(self) -> None:
        listing = SIGNED_LISTING.format(leaf="Fixture Local Installer").replace(
            "signed by a developer certificate issued by Apple for distribution",
            "signed by a certificate trusted by macOS")
        completed = self.signer(listing)
        self.assertEqual(completed.returncode, 1)
        self.assertEqual(completed.stdout, "")


if __name__ == "__main__":
    unittest.main()
