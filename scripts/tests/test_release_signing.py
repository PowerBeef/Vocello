"""Release re-signing of the code nested in the app's frameworks, and its packaged-bundle check.

`release_sign_framework` (scripts/lib/release_signing.sh, sourced by scripts/release.sh) runs
over fabricated framework trees whose code files carry a Mach-O header, with a recording
`run_codesign` in place of the release identity, so the tests see what is signed, in which
order, and what is removed. scripts/verify_release_bundle.sh runs from a sandbox
(scripts/tests/shell_stubs.py) whose `codesign` answers from a table of fabricated signatures;
in signed mode it holds every Mach-O under Contents except the app's own executable to the
release team, the hardened runtime and no entitlements.
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

    def verify(self, *, signed: bool = True) -> subprocess.CompletedProcess[str]:
        rows = "".join(f"{path}\t{team}\t{int(runtime)}\n" for path, (team, runtime) in self.signatures.items())
        (self.sandbox.path / "signatures.tsv").write_text(rows, encoding="utf-8")
        environment = {"QWENVOICE_SKIP_LAUNCH_SMOKE": "1", "CI": "false", "QWENVOICE_EXPECT_TEAM_ID": TEAM}
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


if __name__ == "__main__":
    unittest.main()
