"""scripts/release.sh builds, signs, notarizes and verifies the CLI installer package.

The whole release script runs from a sandbox (scripts/tests/shell_stubs.py) with `--skip-build`:
the build-cache library is a recorded stand-in whose `xcb_run` answers the build settings, the
readiness, bundle and DMG scripts are recorded stand-ins, `scripts/cli_package.py` stages, seals
and smokes a fixture folder and writes the package and its report, and `codesign`,
`productsign`, `pkgutil`, `xcrun`, `otool`, `xcodebuild` and `git` are recorded shims. The real
scripts/lib/release_signing.sh supplies the one notarization path. Nothing is built, signed,
submitted or installed; the tests read the recorded order, arguments and outputs.
"""

from __future__ import annotations

import hashlib
import subprocess
import unittest
from pathlib import Path

from shell_stubs import SANDBOX_BUILD_PATHS, ScriptSandbox, option

TEAM = "TEAM123456"
APP_IDENTITY = f"Developer ID Application: Fixture ({TEAM})"
INSTALLER_IDENTITY = f"Developer ID Installer: Fixture ({TEAM})"
COMMIT = "c0ffee" + "0" * 34
MANIFEST = b'{"fixture": "sealed manifest"}\n'
OUTPUT = "Vocello-macos26"

BUILD_CACHE = (
    "".join(f"qv_stub {name}\n" for name in (
        "require_build_free_space", "ensure_project_regenerated", "ensure_spm_resolved",
        "write_build_provenance", "assert_macos_bundle_arm64_only", "preserve_macos_dsyms",
        "prune_stale_builds",
    ))
    + 'copy_tree_clone_first() { qv_record copy_tree_clone_first "$@"; cp -R "$1" "$2"; }\n'
    + "xcb_run() {\n"
    '  qv_record xcb_run "$@"\n'
    '  case " $* " in *" -showBuildSettings "*)\n'
    '    printf "    %s = %s\\n" BUILT_PRODUCTS_DIR "$QV_SANDBOX/products" WRAPPER_NAME Vocello.app \\\n'
    "      EXECUTABLE_NAME Vocello MARKETING_VERSION 3.0.0 CURRENT_PROJECT_VERSION 24 ;;\n"
    "  esac\n"
    "}\n"
)

# scripts/cli_package.py: stage and seal a fixture folder, write the package and its report the way
# the real commands refuse to overwrite them, and fail a command named in CLI_PACKAGE_FAIL.
CLI_PACKAGE = r'''
command="$1"; shift
value() {
  local name="$1"; shift
  while [ $# -gt 1 ]; do
    if [ "$1" = "$name" ]; then printf '%s\n' "$2"; return 0; fi
    shift
  done
  return 1
}
[ "${CLI_PACKAGE_FAIL:-}" != "$command" ] || exit 1
case "$command" in
  stage) directory="$(value --directory "$@")"; mkdir -p "$directory/GRDB_GRDB.bundle"; printf cli > "$directory/vocello" ;;
  seal) printf '{"fixture": "sealed manifest"}\n' > "$(value --directory "$@")/package-manifest.json" ;;
  smoke) ;;
  pkg) output="$(value --output "$@")"; [ ! -e "$output" ] || exit 1; printf 'unsigned package' > "$output" ;;
  pkg-verify)
    report="$(value --report "$@")"; [ ! -e "$report" ] || exit 1
    [ -d "$(value --expanded "$@")" ] || exit 1
    printf '{"status": "passed"}\n' > "$report" ;;
  *) exit 64 ;;
esac
'''

# productsign copies its input; pkgutil names PKG_SIGNER (the installer identity by default) and
# expands into a new folder; xcrun answers notarytool (Invalid for the artifact named in
# NOTARY_REJECT) and stapler; otool, xcodebuild and git answer the metadata step.
TOOLS = {
    "codesign": "exit 0",
    "productsign": 'cp "${@: -2:1}" "${@: -1}"',
    "pkgutil": (
        'case "$1" in\n'
        '  --check-signature)\n'
        '    printf "Package \\"%s\\":\\n   Status: signed by a developer certificate issued by Apple for distribution\\n'
        '   Certificate Chain:\\n    1. %s\\n       Expires: 2031\\n    2. Developer ID Certification Authority\\n" '
        f'"$(basename "$2")" "${{PKG_SIGNER:-{INSTALLER_IDENTITY}}}" ;;\n'
        '  --expand-full) [ ! -e "$3" ] || exit 1; mkdir -p "$3/vocello-cli.pkg/Payload" ;;\n'
        "  *) exit 64 ;;\n"
        "esac"
    ),
    "xcrun": (
        'case "$1 $2" in\n'
        '  "notarytool submit")\n'
        '    status=Accepted; [ "$(basename "$3")" != "${NOTARY_REJECT:-}" ] || status=Invalid\n'
        '    printf "  id: sub-%s\\n  status: %s\\n" "$(basename "$3")" "$status" ;;\n'
        '  "notarytool log"|"stapler staple"|"stapler validate") ;;\n'
        "  *) exit 64 ;;\n"
        "esac"
    ),
    "otool": 'printf "Load command 9\\n      cmd LC_BUILD_VERSION\\n  cmdsize 32\\n platform 1\\n    minos 26.0\\n      sdk 27.1\\n"',
    "xcodebuild": '[ "$1" = -version ] || exit 64\nprintf "Xcode 27.1\\nBuild version 27A1\\n"',
    "git": f'[ "${{*: -2}}" = "rev-parse HEAD" ] || exit 64\necho {COMMIT}',
}


class ReleaseCLIPackageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.sandbox = ScriptSandbox(self, "scripts/release.sh", {
            "scripts/lib/build_paths.sh": SANDBOX_BUILD_PATHS,
            "scripts/lib/build_cache.sh": BUILD_CACHE,
            "scripts/lib/release_signing.sh": None,
        })
        for script in ("scripts/macos_test.sh", "scripts/check_backend_resource_contract.sh",
                       "scripts/verify_release_bundle.sh"):
            self.sandbox.executable(script)
        self.sandbox.executable("scripts/create_dmg.sh", 'printf dmg > "$QVOICE_DIST_MACOS/$2.dmg"')
        self.sandbox.helper("scripts/cli_package.py", CLI_PACKAGE)
        for name, behaviour in TOOLS.items():
            self.sandbox.tool(name, behaviour)
        self.sandbox.file("products/Vocello.app/Contents/MacOS/Vocello", "app")
        self.sandbox.file("products/Vocello.app/Contents/Resources/contract.json", "{}")
        self.key = self.sandbox.file("keys/AuthKey_KEY1234567.p8", "fixture key")
        self.dist = self.sandbox.build / "qvoice_dist_macos"
        self.package = self.dist / f"{OUTPUT}-cli.pkg"
        self.unsigned = self.dist / f"{OUTPUT}-cli.unsigned.pkg"
        self.report = self.dist / "cli-pkg-verification.json"

    def release(self, **overrides: str) -> subprocess.CompletedProcess[str]:
        environment = {
            "QWENVOICE_SIGNING_MODE": "developer-id", "QWENVOICE_SIGNING_IDENTITY": APP_IDENTITY,
            "APPLE_DEV_ID_INSTALLER": INSTALLER_IDENTITY, "APPLE_TEAM_ID": TEAM,
            "QWENVOICE_NOTARIZE": "1", "APPLE_API_KEY_PATH": str(self.key),
            "APPLE_API_KEY_ID": "KEY1234567", "APPLE_API_ISSUER_ID": "",
            **overrides,
        }
        return self.sandbox.run_script("--skip-build", env=environment, timeout=120)

    def ad_hoc(self, **overrides: str) -> subprocess.CompletedProcess[str]:
        return self.release(QWENVOICE_SIGNING_MODE="ad-hoc", QWENVOICE_NOTARIZE="0",
                            QWENVOICE_SIGNING_IDENTITY="", APPLE_DEV_ID_INSTALLER="", **overrides)

    def cli(self, command: str) -> list[str]:
        calls = self.sandbox.calls_to("scripts/cli_package.py", command)
        self.assertEqual(len(calls), 1, self.sandbox.calls())
        return calls[0]

    def metadata(self) -> list[tuple[str, str]]:
        text = (self.dist / "release-metadata.txt").read_text(encoding="utf-8")
        return [tuple(line.split("=", 1)) for line in text.splitlines()]  # type: ignore[misc]

    def test_a_developer_id_release_signs_notarizes_and_verifies_the_package_from_the_sealed_folder(self) -> None:
        completed = self.release()
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        index = self.sandbox.index
        # The package comes from the folder once it is signed, sealed and smoked, before either DMG.
        order = [
            index("scripts/cli_package.py", "seal"), index("scripts/cli_package.py", "smoke"),
            index("scripts/cli_package.py", "pkg"), index("productsign"),
            index("xcrun", "notarytool", "submit", str(self.package)),
            index("pkgutil", "--expand-full"), index("scripts/cli_package.py", "pkg-verify"),
            index("scripts/create_dmg.sh"),
        ]
        self.assertEqual(order, sorted(order))
        sealed = option(self.cli("seal"), "--directory")
        build = self.cli("pkg")
        self.assertEqual(option(build, "--directory"), sealed)
        self.assertEqual(option(build, "--output"), str(self.unsigned))
        self.assertEqual([option(build, flag) for flag in ("--version", "--build", "--commit")], ["3.0.0", "24", COMMIT])
        self.assertEqual(self.sandbox.calls_to("productsign"), [
            ["--sign", INSTALLER_IDENTITY, "--timestamp", str(self.unsigned), str(self.package)],
        ])
        verify = self.cli("pkg-verify")
        expanded = self.sandbox.calls_to("pkgutil", "--expand-full")
        self.assertEqual(expanded, [[ "--expand-full", str(self.package), option(verify, "--expanded")]])
        self.assertEqual(option(verify, "--artifact"), str(self.package))
        self.assertEqual(option(verify, "--manifest-sha256"), hashlib.sha256(MANIFEST).hexdigest())
        self.assertEqual((option(verify, "--signature"), option(verify, "--notarization")),
                         ("developer-id-installer", "stapled"))
        self.assertEqual(option(verify, "--report"), str(self.report))
        self.assertIn("--root-free-install", verify)
        self.assertEqual([option(verify, flag) for flag in ("--version", "--build", "--commit")], ["3.0.0", "24", COMMIT])
        self.assertTrue(self.package.is_file())
        self.assertFalse(self.unsigned.exists())
        self.assertTrue(self.report.is_file())
        # The expanded tree lived in the staging root, which is gone.
        self.assertFalse(Path(option(verify, "--expanded")).exists())

    def test_one_notarization_path_submits_staples_and_validates_all_three_artifacts(self) -> None:
        completed = self.release()
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        artifacts = [str(self.package), str(self.dist / f"{OUTPUT}.dmg"), str(self.dist / f"{OUTPUT}-cli.dmg")]
        self.assertEqual([call[2] for call in self.sandbox.calls_to("xcrun", "notarytool", "submit")], artifacts)
        self.assertEqual([call[2] for call in self.sandbox.calls_to("xcrun", "stapler", "staple")], artifacts)
        self.assertEqual([call[2] for call in self.sandbox.calls_to("xcrun", "stapler", "validate")], artifacts)
        for submit in self.sandbox.calls_to("xcrun", "notarytool", "submit"):
            self.assertEqual(submit[3:], ["--key", str(self.key), "--key-id", "KEY1234567", "--wait"])

    def test_productsign_reads_the_release_keychain_when_one_is_given(self) -> None:
        keychain = self.sandbox.file("keychains/vocello-signing.keychain-db")
        completed = self.release(QWENVOICE_CODESIGN_KEYCHAIN=str(keychain))
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertEqual(self.sandbox.calls_to("productsign"), [[
            "--sign", INSTALLER_IDENTITY, "--timestamp", "--keychain", str(keychain),
            str(self.unsigned), str(self.package),
        ]])

    def test_the_ad_hoc_rehearsal_keeps_the_package_unsigned_under_its_release_name(self) -> None:
        # An earlier run's package and report never stand in: the stand-in, like the real
        # commands, refuses to overwrite them, so success means release.sh removed them first.
        self.dist.mkdir(parents=True)
        for stale in (self.unsigned, self.package, self.report):
            stale.write_text("from an earlier run", encoding="utf-8")
        completed = self.ad_hoc()
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertEqual(self.sandbox.calls_to("productsign"), [])
        self.assertEqual(self.sandbox.calls_to("xcrun"), [])
        verify = self.cli("pkg-verify")
        self.assertEqual((option(verify, "--signature"), option(verify, "--notarization")),
                         ("unsigned", "not-performed"))
        self.assertEqual(self.package.read_text(encoding="utf-8"), "unsigned package")
        self.assertFalse(self.unsigned.exists())
        self.assertEqual(self.report.read_text(encoding="utf-8"), '{"status": "passed"}\n')

    def test_developer_id_without_notarization_claims_no_ticket(self) -> None:
        completed = self.release(QWENVOICE_NOTARIZE="0")
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertEqual(len(self.sandbox.calls_to("productsign")), 1)
        self.assertEqual(self.sandbox.calls_to("xcrun"), [])
        verify = self.cli("pkg-verify")
        self.assertEqual((option(verify, "--signature"), option(verify, "--notarization")),
                         ("developer-id-installer", "not-performed"))

    def test_the_outputs_block_names_the_package_and_its_report_beside_the_cli_dmg(self) -> None:
        completed = self.release()
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        rows = self.metadata()
        keys = [key for key, _ in rows]
        values = dict(rows)
        self.assertEqual(len(keys), len(set(keys)))
        position = keys.index("cli_dmg_name")
        self.assertEqual(keys[position:position + 4],
                         ["cli_dmg_name", "cli_pkg_name", "cli_pkg_verification", "cli_manifest_sha256"])
        self.assertEqual(values["cli_dmg_name"], f"{OUTPUT}-cli.dmg")
        self.assertEqual(values["cli_pkg_name"], f"{OUTPUT}-cli.pkg")
        self.assertEqual(values["cli_pkg_verification"], "cli-pkg-verification.json")
        self.assertEqual(values["cli_manifest_sha256"], hashlib.sha256(MANIFEST).hexdigest())
        # The metadata names exactly the package and report the run left beside it.
        self.assertTrue((self.dist / values["cli_pkg_name"]).is_file())
        self.assertTrue((self.dist / values["cli_pkg_verification"]).is_file())

    def test_a_named_output_names_its_package_after_it(self) -> None:
        completed = self.sandbox.run_script("--skip-build", "--output-name", "Vocello candidate", env={
            "QWENVOICE_SIGNING_MODE": "ad-hoc", "QWENVOICE_NOTARIZE": "0"}, timeout=120)
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertEqual(option(self.cli("pkg-verify"), "--artifact"), str(self.dist / "Vocello candidate-cli.pkg"))
        self.assertEqual(dict(self.metadata())["cli_pkg_name"], "Vocello candidate-cli.pkg")

    def test_an_installer_identity_outside_the_release_team_is_refused_before_any_work(self) -> None:
        cases = {
            "another team": "Developer ID Installer: Fixture (OTHER12345)",
            "an application identity": APP_IDENTITY,
            "a partial name": "Developer ID Installer: Fixture",
            "none": "",
        }
        for label, identity in cases.items():
            with self.subTest(label):
                self.sandbox.log.write_text("", encoding="utf-8")
                completed = self.release(APPLE_DEV_ID_INSTALLER=identity)
                self.assertEqual(completed.returncode, 1, completed.stdout)
                self.assertIn("installer", completed.stderr)
                self.assertEqual(self.sandbox.calls_to("scripts/macos_test.sh"), [])
                self.assertEqual(self.sandbox.calls_to("scripts/cli_package.py"), [])

    def test_the_flag_names_the_installer_identity_too(self) -> None:
        completed = self.sandbox.run_script("--skip-build", "--installer-identity", INSTALLER_IDENTITY, env={
            "QWENVOICE_SIGNING_MODE": "developer-id", "QWENVOICE_SIGNING_IDENTITY": APP_IDENTITY,
            "APPLE_DEV_ID_INSTALLER": "", "APPLE_TEAM_ID": TEAM, "QWENVOICE_NOTARIZE": "0"}, timeout=120)
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertEqual(self.sandbox.calls_to("productsign")[0][:2], ["--sign", INSTALLER_IDENTITY])

    def test_a_package_signed_by_another_identity_is_never_verified_or_shipped(self) -> None:
        completed = self.release(PKG_SIGNER="Developer ID Installer: Someone Else (OTHER12345)")
        self.assertEqual(completed.returncode, 1)
        self.assertIn("is not signed by the release installer identity", completed.stderr)
        self.assertEqual(self.sandbox.calls_to("xcrun"), [])
        self.assertEqual(self.sandbox.calls_to("scripts/cli_package.py", "pkg-verify"), [])
        self.assertEqual(self.sandbox.calls_to("scripts/create_dmg.sh"), [])

    def test_a_rejected_package_fetches_apples_log_and_stops_before_the_dmgs(self) -> None:
        completed = self.release(NOTARY_REJECT=self.package.name)
        self.assertEqual(completed.returncode, 1)
        self.assertIn(f"Notarization of {self.package.name} failed", completed.stderr)
        self.assertEqual([call[2] for call in self.sandbox.calls_to("xcrun", "notarytool", "log")],
                         [f"sub-{self.package.name}"])
        self.assertEqual(self.sandbox.calls_to("xcrun", "stapler"), [])
        self.assertEqual(self.sandbox.calls_to("scripts/cli_package.py", "pkg-verify"), [])
        self.assertEqual(self.sandbox.calls_to("scripts/create_dmg.sh"), [])

    def test_a_rejected_dmg_still_fails_the_release(self) -> None:
        completed = self.release(NOTARY_REJECT=f"{OUTPUT}-cli.dmg")
        self.assertEqual(completed.returncode, 1)
        self.assertIn(f"Notarization of {OUTPUT}-cli.dmg failed", completed.stderr)
        self.assertFalse((self.dist / "release-metadata.txt").exists())

    def test_a_failed_package_build_or_verification_fails_the_release(self) -> None:
        for command in ("pkg", "pkg-verify"):
            with self.subTest(command):
                self.sandbox.log.write_text("", encoding="utf-8")
                for stale in (self.package, self.unsigned, self.report):
                    stale.unlink(missing_ok=True)
                completed = self.ad_hoc(CLI_PACKAGE_FAIL=command)
                self.assertEqual(completed.returncode, 1)
                self.assertIn("Error:", completed.stderr)
                self.assertEqual(self.sandbox.calls_to("scripts/create_dmg.sh"), [])
                self.assertFalse((self.dist / "release-metadata.txt").exists())


if __name__ == "__main__":
    unittest.main()
