"""scripts/verify_packaged_cli.sh --include-pkg and its pass-through in verify_packaged_dmg.sh.

The scripts run from sandboxes (scripts/tests/shell_stubs.py) whose `sudo`, `installer`,
`pkgutil`, `hdiutil`, `codesign`, `xcrun` and `spctl` are recorded stand-ins and whose
`scripts/cli_package.py` and `scripts/entitlement_contract.py` are recorded helpers. Whole-script
runs cover the refusal outside a GitHub-hosted runner and every check before anything is installed. The install,
upgrade and uninstall sequence runs the shipped functions after sourcing the script, with the
paths the package owns moved under a sandbox volume (as LaneShell moves build paths): the
`installer` stand-in plays Installer with its preinstall and postinstall there, `sudo` runs the
command it is given, and the payload's `uninstall.sh` is a stand-in for that volume. Nothing is
installed, mounted or run as root.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

from shell_stubs import ScriptSandbox, quote

# Past the refusals, the scripts read ownership, modes and sizes with macOS's `stat -f` and copy
# with `ditto`; Linux's stat reads the file system instead, so those runs belong to macOS.
MACOS_ONLY = unittest.skipUnless(sys.platform == "darwin", "the scripts use macOS's stat and ditto")

TEAM = "TEAM123456"
COMMIT = "c0ffee" + "0" * 34
MANIFEST = b'{"fixture": "sealed manifest"}\n'
DIGEST = hashlib.sha256(MANIFEST).hexdigest()
PACKAGE = "Vocello-macos26-cli.pkg"

# Installer with the package's preinstall (skipped with INSTALLER_SKIPS_PREINSTALL=1) and
# postinstall (absolute links with INSTALLER_ABSOLUTE_LINKS=1), on the -target volume.
INSTALLER = r'''
target=""
while [ $# -gt 0 ]; do
  if [ "$1" = -target ]; then target="${2%/}"; fi
  shift
done
lib="$target/usr/local/lib/vocello"
[ "${INSTALLER_SKIPS_PREINSTALL:-}" = 1 ] || rm -rf "$lib"
mkdir -p "$lib" "$target/usr/local/bin" "$target/usr/local/share/zsh/site-functions"
cp -R "$QV_SANDBOX/payload/." "$lib/"
if [ "${INSTALLER_ABSOLUTE_LINKS:-}" = 1 ]; then
  ln -sfn "$lib/vocello" "$target/usr/local/bin/vocello"
else
  ln -sfn ../lib/vocello/vocello "$target/usr/local/bin/vocello"
fi
ln -sfn ../../../lib/vocello/_vocello "$target/usr/local/share/zsh/site-functions/_vocello"
printf '%s\n' "${INSTALLER_VERSION:-3.0.0}" > "$QV_SANDBOX/receipt"
'''

PKGUTIL = r'''
case "$1" in
  --pkg-info)
    [ "$2" = com.qwenvoice.cli ] && [ -f "$QV_SANDBOX/receipt" ] || exit 1
    printf 'package-id: com.qwenvoice.cli\nversion: %s\nvolume: /\nlocation: usr/local/lib/vocello\n' "$(cat "$QV_SANDBOX/receipt")" ;;
  --expand-full)
    [ ! -e "$3" ] || exit 1
    mkdir -p "$3/vocello-cli.pkg/Payload"
    cp -R "$QV_SANDBOX/payload/." "$3/vocello-cli.pkg/Payload/" ;;
  --check-signature)
    printf '   Status: signed by a developer certificate issued by Apple for distribution\n    1. %s\n' \
      "${PKG_SIGNER:-Developer ID Installer: Fixture (TEAM123456)}" ;;
  *) exit 64 ;;
esac
'''

# The shipped uninstall.sh removes the two links, the folder and the receipt; this stand-in does
# that on the sandbox volume, or less (UNINSTALL_KEEPS) or more (UNINSTALL_TOUCHES_STORE).
UNINSTALL = r'''
root="$QV_SANDBOX/volume"
[ "${UNINSTALL_KEEPS:-}" = link ] || rm -f "$root/usr/local/bin/vocello"
rm -f "$root/usr/local/share/zsh/site-functions/_vocello"
[ "${UNINSTALL_KEEPS:-}" = folder ] || rm -rf "$root/usr/local/lib/vocello"
[ "${UNINSTALL_KEEPS:-}" = receipt ] || rm -f "$QV_SANDBOX/receipt"
[ "${UNINSTALL_TOUCHES_STORE:-}" != 1 ] || printf new > "$HOME/Library/Application Support/QwenVoice/new-file"
'''


def write_payload(sandbox: ScriptSandbox) -> None:
    payload = sandbox.path / "payload"
    (payload / "GRDB_GRDB.bundle").mkdir(parents=True)
    (payload / "vocello").write_text("cli", encoding="utf-8")
    (payload / "vocello").chmod(0o755)
    (payload / "_vocello").write_text("#compdef vocello\n", encoding="utf-8")
    (payload / "package-manifest.json").write_bytes(MANIFEST)
    (payload / "uninstall.sh").write_text(UNINSTALL, encoding="utf-8")


def cli_sandbox(test: unittest.TestCase) -> ScriptSandbox:
    sandbox = ScriptSandbox(test, "scripts/verify_packaged_cli.sh", {"scripts/lib/release_signing.sh": None})
    write_payload(sandbox)
    sandbox.helper("scripts/cli_package.py", (
        '[ "$1" = smoke ] || exit 64\n'
        '[ "${SMOKE_FAILS:-}" != 1 ] || exit 1\n'
        # The DMG smoke writes its report, as the real command does.
        'shift\nwhile [ $# -gt 1 ]; do [ "$1" != --report ] || printf "{}\\n" > "$2"; shift; done'
    ))
    sandbox.helper("scripts/entitlement_contract.py", '[ "${ENTITLED:-}" != "${@: -1}" ] || exit 1')
    sandbox.tool("installer", INSTALLER)
    sandbox.tool("pkgutil", PKGUTIL)
    sandbox.tool("sudo", '[ "$1" != -n ] || exit "${SUDO_N_STATUS:-0}"\nexec "$@"')
    # Only root can give a folder to root; the sandbox records the request instead.
    sandbox.tool("chown", "exit 0")
    store = sandbox.home / "Library/Application Support/QwenVoice"
    store.mkdir(parents=True)
    (store / "history.sqlite").write_text("history", encoding="utf-8")
    return sandbox


# A GitHub-hosted Actions runner, the only host the install test runs on. Every run names all
# three variables, so a test run on such a runner inherits none of them.
HOSTED_RUNNER = {"CI": "true", "GITHUB_ACTIONS": "true", "RUNNER_ENVIRONMENT": "github-hosted"}
NO_RUNNER = {name: "" for name in HOSTED_RUNNER}


def store_state(sandbox: ScriptSandbox) -> dict[str, str]:
    store = sandbox.home / "Library/Application Support/QwenVoice"
    return {path.relative_to(store).as_posix(): path.read_text(encoding="utf-8")
            for path in store.rglob("*") if path.is_file()}


class InstallTestRefusalTests(unittest.TestCase):
    """The whole script: --include-pkg never reaches sudo outside a GitHub-hosted runner."""

    def setUp(self) -> None:
        self.sandbox = cli_sandbox(self)
        self.metadata = self.sandbox.file("dist/release-metadata.txt", "cli_dmg_name=Vocello-macos26-cli.dmg\n")
        self.package = self.sandbox.file(f"dist/{PACKAGE}", "package")

    def run_cli(self, *arguments: str, **env: str) -> subprocess.CompletedProcess[str]:
        return self.sandbox.run_script(*arguments, env={**NO_RUNNER, **env})

    def test_outside_a_github_hosted_runner_the_install_test_is_refused_without_sudo(self) -> None:
        hosts = {
            "local": {},
            "other CI": {"CI": "true"},
            "self-hosted runner": {**HOSTED_RUNNER, "RUNNER_ENVIRONMENT": "self-hosted"},
            "no Actions": {**HOSTED_RUNNER, "GITHUB_ACTIONS": "false"},
            "not CI": {**HOSTED_RUNNER, "CI": ""},
        }
        for host, env in hosts.items():
            with self.subTest(host=host):
                self.sandbox.log.write_text("", encoding="utf-8")
                completed = self.run_cli(str(self.metadata), "--include-pkg", str(self.package), **env)
                self.assertEqual(completed.returncode, 2)
                self.assertIn("runs only on a GitHub-hosted runner (CI=true, GITHUB_ACTIONS=true, "
                              "RUNNER_ENVIRONMENT=github-hosted) with passwordless sudo", completed.stderr)
                self.assertEqual(self.sandbox.calls_to("sudo"), [])
                self.assertEqual(self.sandbox.calls(), [])

    def test_a_hosted_runner_without_passwordless_sudo_is_refused(self) -> None:
        completed = self.run_cli(str(self.metadata), "--include-pkg", str(self.package),
                                 **HOSTED_RUNNER, SUDO_N_STATUS="1")
        self.assertEqual(completed.returncode, 2)
        self.assertEqual(self.sandbox.calls(), [["sudo", "-n", "true"]])

    def test_malformed_arguments_are_a_usage_error(self) -> None:
        for arguments in ((str(self.metadata), "--include-pkg"),
                          (str(self.metadata), "--other", str(self.package)),
                          (str(self.metadata), "--include-pkg", "")):
            with self.subTest(arguments=arguments):
                completed = self.run_cli(*arguments, **HOSTED_RUNNER)
                self.assertEqual(completed.returncode, 1)
                self.assertIn("Usage:", completed.stderr)
                self.assertEqual(self.sandbox.calls_to("sudo"), [])


@MACOS_ONLY
class PackageChecksBeforeInstallingTests(unittest.TestCase):
    """The whole script on a hosted runner: the DMG folder, then every package check before installing."""

    def setUp(self) -> None:
        self.sandbox = cli_sandbox(self)
        dist = self.sandbox.path / "dist"
        dist.mkdir()
        self.dist = dist
        (dist / "Vocello-macos26-cli.dmg").write_text("dmg", encoding="utf-8")
        self.package = dist / PACKAGE
        self.package.write_text("package", encoding="utf-8")
        self.metadata = dist / "release-metadata.txt"
        self.metadata.write_text("\n".join([
            f"commit_sha={COMMIT}", "marketing_version=3.0.0", "build_number=24",
            "dmg_name=Vocello-macos26.dmg", "cli_dmg_name=Vocello-macos26-cli.dmg",
            f"cli_pkg_name={PACKAGE}", "cli_pkg_verification=cli-pkg-verification.json",
            f"cli_manifest_sha256={DIGEST}",
        ]) + "\n", encoding="utf-8")
        self.write_report()
        # Attaching the CLI DMG mounts the sealed folder at the requested mount point.
        self.sandbox.tool("hdiutil", (
            'if [ "$1" = attach ]; then\n'
            '  mkdir -p "$3/Vocello CLI"; cp -R "$QV_SANDBOX/payload/." "$3/Vocello CLI/"\n'
            "fi"
        ))
        self.sandbox.tool("codesign", (
            'case " $* " in *" -dvv "*) printf "Authority=Developer ID Application: Fixture\\n'
            f'TeamIdentifier={TEAM}\\nflags=0x10000(runtime)\\n" >&2 ;; esac'
        ))
        self.sandbox.tool("xcrun", '[ "$1 $2" = "stapler validate" ] || exit 64\n[ "${STAPLE_FAILS:-}" != "${@: -1}" ] || exit 1')
        self.sandbox.tool("spctl", "exit 0")
        # The install test is PackageInstallTests' subject. Here the stand-in receipt makes its
        # first check refuse, so a run that reaches it touches no real path and installs nothing.
        (self.sandbox.path / "receipt").write_text("3.0.0\n", encoding="utf-8")

    def write_report(self, **changes: object) -> None:
        payload = {
            "schemaVersion": 1, "status": "passed",
            "release": {"marketingVersion": "3.0.0", "buildNumber": "24", "commitSHA": COMMIT},
            "manifestSHA256": DIGEST, "installTest": "not-performed",
            "artifact": {"name": PACKAGE, "bytes": self.package.stat().st_size,
                         "sha256": hashlib.sha256(self.package.read_bytes()).hexdigest()},
            **changes,
        }
        (self.dist / "cli-pkg-verification.json").write_text(json.dumps(payload), encoding="utf-8")

    def verify(self, *, signed: bool = False, **env: str) -> subprocess.CompletedProcess[str]:
        environment = {**HOSTED_RUNNER, **env}
        if signed:
            environment.update({"QWENVOICE_EXPECT_SIGNED_RELEASE": "1", "QWENVOICE_EXPECT_NOTARIZED_DMG": "1",
                                "QWENVOICE_EXPECT_TEAM_ID": TEAM})
        return self.sandbox.run_script(str(self.metadata), "--include-pkg", str(self.package), env=environment)

    def assert_not_installed(self, completed: subprocess.CompletedProcess[str], message: str) -> None:
        self.assertEqual(completed.returncode, 1, completed.stdout + completed.stderr)
        self.assertIn(message, completed.stderr)
        self.assertEqual(self.sandbox.calls_to("sudo", "installer"), [])

    def test_both_copies_of_vocello_are_held_to_the_macos_cli_entitlement_role(self) -> None:
        completed = self.verify()
        self.assertIn("already has a com.qwenvoice.cli receipt", completed.stderr)
        bundles = [Path(call[-1]) for call in self.sandbox.calls_to(
            "scripts/entitlement_contract.py", "verify-bundle", "--role", "macos-cli")]
        self.assertEqual([path.name for path in bundles], ["vocello", "vocello"])
        self.assertEqual(bundles[0].parent.name, "Copied CLI with spaces")
        self.assertEqual(bundles[1].parent.as_posix().split("/")[-2:], ["vocello-cli.pkg", "Payload"])

    def test_an_entitled_payload_stops_before_installing(self) -> None:
        # The DMG copy passes; the package's expanded payload carries entitlements.
        expanded_vocello = "vocello-cli.pkg/Payload/vocello"
        self.sandbox.helper("scripts/entitlement_contract.py",
                            f'case "${{@: -1}}" in *{expanded_vocello}) exit 1 ;; esac')
        self.assert_not_installed(self.verify(), "entitlements outside the macos-cli role")

    def test_the_package_must_be_the_one_the_metadata_names(self) -> None:
        other = self.dist / "Other-cli.pkg"
        other.write_text("package", encoding="utf-8")
        completed = self.sandbox.run_script(str(self.metadata), "--include-pkg", str(other), env=HOSTED_RUNNER)
        self.assert_not_installed(completed, "is not the one the release metadata names")

    def test_the_package_must_be_the_one_release_sh_verified(self) -> None:
        cases = {
            "other bytes": {"artifact": {"name": PACKAGE, "bytes": 7, "sha256": "0" * 64}},
            "other folder": {"manifestSHA256": "1" * 64},
            "other build": {"release": {"marketingVersion": "3.0.0", "buildNumber": "23", "commitSHA": COMMIT}},
            "not passed": {"status": "failed"},
        }
        for label, change in cases.items():
            with self.subTest(label):
                self.sandbox.log.write_text("", encoding="utf-8")
                self.write_report(**change)
                self.assert_not_installed(self.verify(), "report does not bind this package and release")

    def test_a_signed_release_needs_the_release_teams_installer_signature(self) -> None:
        self.assert_not_installed(
            self.verify(signed=True, PKG_SIGNER="Developer ID Installer: Someone Else (OTHER12345)"),
            "not signed by the release team's Developer ID Installer identity")

    def test_a_notarized_release_needs_a_stapled_ticket_on_the_package(self) -> None:
        self.assert_not_installed(self.verify(signed=True, STAPLE_FAILS=str(self.package)),
                                  "no valid stapled ticket")

    def test_a_signed_release_checks_signature_ticket_and_gatekeeper_then_installs(self) -> None:
        completed = self.verify(signed=True)
        self.assertEqual(self.sandbox.calls_to("pkgutil", "--check-signature"), [["--check-signature", str(self.package)]])
        self.assertIn(["stapler", "validate", str(self.package)], self.sandbox.calls_to("xcrun"))
        self.assertEqual(self.sandbox.calls_to("spctl"), [
            ["-a", "-vvv", "--type", "open", "--context", "context:primary-signature",
             str(self.dist / "Vocello-macos26-cli.dmg")],
            ["-a", "-vvv", "-t", "install", str(self.package)],
        ])
        # Every check passed, so the install test began (and refused the stand-in receipt).
        self.assertEqual(completed.returncode, 1)
        self.assertIn("already has a com.qwenvoice.cli receipt", completed.stderr)
        # Only the passwordless-sudo probe ran as root.
        self.assertEqual(self.sandbox.calls_to("sudo"), [["-n", "true"]])


@MACOS_ONLY
class PackageInstallTests(unittest.TestCase):
    """`pkg_install_test`, sourced, on a sandbox volume."""

    def setUp(self) -> None:
        self.sandbox = cli_sandbox(self)
        self.volume = self.sandbox.path / "volume"
        self.volume.mkdir()
        self.package = self.sandbox.file(f"dist/{PACKAGE}", "package")
        self.lib = self.volume / "usr/local/lib/vocello"
        self.link = self.volume / "usr/local/bin/vocello"
        self.completion = self.volume / "usr/local/share/zsh/site-functions/_vocello"

    def install_test(self, **env: str) -> subprocess.CompletedProcess[str]:
        script = (
            "set -euo pipefail\n"
            f". {quote(self.sandbox.record)}\n"
            f". {quote(self.sandbox.script)}\n"
            f"PKG_TARGET={quote(self.volume)}\n"
            f"PKG_LIB={quote(self.lib)}\n"
            f"PKG_BIN_LINK={quote(self.link)}\n"
            f"PKG_COMPLETION_LINK={quote(self.completion)}\n"
            f"pkg_install_test {quote(self.package)} 3.0.0 24 {COMMIT} {DIGEST}\n"
        )
        return subprocess.run(["bash", "-c", script], cwd=self.sandbox.root,
                              env=self.sandbox.environment({**HOSTED_RUNNER, **env}),
                              capture_output=True, text=True, timeout=60, check=False)

    def sequence(self) -> list[list[str]]:
        """sudo commands and smokes, in order."""
        return [call for call in self.sandbox.calls()
                if call[0] == "sudo" or call[:2] == ["scripts/cli_package.py", "smoke"]]

    def test_install_upgrade_and_uninstall_leave_the_volume_clean_and_the_data_store_alone(self) -> None:
        before = store_state(self.sandbox)
        completed = self.install_test()
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        install = ["sudo", "installer", "-pkg", str(self.package), "-target", str(self.volume)]
        smoke = ["scripts/cli_package.py", "smoke", "--directory", str(self.lib), "--launcher", str(self.link),
                 "--version", "3.0.0", "--build", "24", "--commit", COMMIT]
        self.assertEqual(self.sequence(), [
            install, smoke,
            ["sudo", "touch", str(self.lib / "stale-file-from-an-older-version.txt")],
            install, smoke,
            ["sudo", "sh", str(self.lib / "uninstall.sh")],
        ])
        for path in (self.lib, self.link, self.completion):
            self.assertFalse(path.exists() or path.is_symlink(), path)
        self.assertFalse((self.sandbox.path / "receipt").exists())
        self.assertEqual(store_state(self.sandbox), before)

    def test_link_folders_the_runner_owns_are_given_to_root_before_installing(self) -> None:
        # A hosted runner's /usr/local/bin belongs to its user; postinstall links only into a
        # folder root alone can change, as on a stock Mac.
        local = self.volume / "usr/local"
        (local / "bin").mkdir(parents=True)
        (local / "bin").chmod(0o775)
        completed = self.install_test()
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        sequence = self.sequence()
        self.assertEqual(sequence[:4], [
            ["sudo", "chown", "root:wheel", str(local)],
            ["sudo", "chmod", "go-w", str(local)],
            ["sudo", "chown", "root:wheel", str(local / "bin")],
            ["sudo", "chmod", "go-w", str(local / "bin")],
        ])
        self.assertEqual(sequence[4][:2], ["sudo", "installer"])
        self.assertFalse(any(call[1] in ("chown", "chmod") and "share" in call[-1] for call in sequence))

    def test_an_upgrade_that_keeps_a_stale_file_fails_before_uninstalling(self) -> None:
        completed = self.install_test(INSTALLER_SKIPS_PREINSTALL="1")
        self.assertEqual(completed.returncode, 1)
        self.assertIn("upgrading kept a file the new payload does not have", completed.stderr)
        self.assertEqual(self.sandbox.calls_to("sudo", "sh"), [])

    def test_links_must_be_relative_into_the_installed_folder(self) -> None:
        completed = self.install_test(INSTALLER_ABSOLUTE_LINKS="1")
        self.assertEqual(completed.returncode, 1)
        self.assertIn("is not the relative link into", completed.stderr)
        self.assertEqual(self.sandbox.calls_to("scripts/cli_package.py", "smoke"), [])

    def test_the_receipt_must_record_this_version(self) -> None:
        completed = self.install_test(INSTALLER_VERSION="2.4.0")
        self.assertEqual(completed.returncode, 1)
        self.assertIn("does not record version 3.0.0", completed.stderr)

    def test_a_failed_smoke_through_the_link_fails(self) -> None:
        completed = self.install_test(SMOKE_FAILS="1")
        self.assertEqual(completed.returncode, 1)
        self.assertIn("failed its smoke run through", completed.stderr)
        self.assertEqual(len(self.sandbox.calls_to("sudo", "installer")), 1)

    def test_the_installed_manifest_must_be_the_sealed_folders(self) -> None:
        (self.sandbox.path / "payload/package-manifest.json").write_text("{}\n", encoding="utf-8")
        completed = self.install_test()
        self.assertEqual(completed.returncode, 1)
        self.assertIn("installed manifest differs", completed.stderr)

    def test_uninstall_must_remove_the_receipt_folder_and_links(self) -> None:
        for kept, message in (("link", f"left {self.link}"), ("folder", f"left {self.lib}"),
                              ("receipt", "left the com.qwenvoice.cli receipt")):
            with self.subTest(kept):
                self.sandbox.log.write_text("", encoding="utf-8")
                for path in (self.link, self.completion):
                    path.unlink(missing_ok=True)
                (self.sandbox.path / "receipt").unlink(missing_ok=True)
                completed = self.install_test(UNINSTALL_KEEPS=kept)
                self.assertEqual(completed.returncode, 1)
                self.assertIn(message, completed.stderr)
                if self.lib.exists():
                    for path in sorted(self.lib.rglob("*"), reverse=True):
                        path.unlink() if not path.is_dir() else path.rmdir()
                    self.lib.rmdir()

    def test_removing_the_cli_must_not_touch_the_data_store(self) -> None:
        completed = self.install_test(UNINSTALL_TOUCHES_STORE="1")
        self.assertEqual(completed.returncode, 1)
        self.assertIn("changed the data store", completed.stderr)

    def test_a_host_with_the_cli_installed_is_refused_before_installing(self) -> None:
        (self.sandbox.path / "receipt").write_text("3.0.0\n", encoding="utf-8")
        completed = self.install_test()
        self.assertEqual(completed.returncode, 1)
        self.assertIn("already has a com.qwenvoice.cli receipt", completed.stderr)
        self.assertEqual(self.sandbox.calls_to("sudo"), [])
        (self.sandbox.path / "receipt").unlink()
        self.link.parent.mkdir(parents=True)
        self.link.symlink_to("../lib/vocello/vocello")
        completed = self.install_test()
        self.assertEqual(completed.returncode, 1)
        self.assertIn("already exists; the install test needs a clean runner", completed.stderr)
        self.assertEqual(self.sandbox.calls_to("sudo"), [])


@MACOS_ONLY
class VerifyPackagedDMGPassThroughTests(unittest.TestCase):
    """verify_packaged_dmg.sh hands --include-pkg to the CLI verifier, only after --include-cli."""

    def setUp(self) -> None:
        self.sandbox = ScriptSandbox(self, "scripts/verify_packaged_dmg.sh", {})
        self.sandbox.executable("scripts/verify_release_bundle.sh")
        self.sandbox.executable("scripts/verify_packaged_cli.sh", 'exit "${CLI_VERIFIER_STATUS:-0}"')
        self.sandbox.tool("hdiutil", (
            'if [ "$1" = attach ]; then\n'
            '  mount="$3"; mkdir -p "$mount/Vocello.app/Contents"\n'
            '  printf "<plist><dict><key>system-entities</key><array><dict><key>dev-entry</key>'
            '<string>/dev/disk99</string><key>mount-point</key><string>%s</string></dict></array>'
            '</dict></plist>" "$mount"\n'
            "fi"
        ))
        self.dmg = self.sandbox.file("dist/Vocello-macos26.dmg", "dmg")
        self.metadata = self.sandbox.file("dist/release-metadata.txt", "dmg_name=Vocello-macos26.dmg\n")
        self.package = self.sandbox.file(f"dist/{PACKAGE}", "package")

    def verify(self, *arguments: str, **env: str) -> subprocess.CompletedProcess[str]:
        return self.sandbox.run_script(str(self.dmg), str(self.metadata), *arguments, env=env)

    def test_include_pkg_reaches_the_cli_verifier_with_an_absolute_path(self) -> None:
        relative = os.path.relpath(self.package, self.sandbox.root)
        completed = self.verify("--include-cli", "--include-pkg", relative)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(self.sandbox.calls_to("scripts/verify_packaged_cli.sh"),
                         [[str(self.metadata), "--include-pkg", str(self.package)]])

    def test_include_cli_alone_verifies_the_dmg_folder_only(self) -> None:
        completed = self.verify("--include-cli")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(self.sandbox.calls_to("scripts/verify_packaged_cli.sh"), [[str(self.metadata)]])

    def test_the_cli_verifiers_refusal_keeps_its_exit_status(self) -> None:
        completed = self.verify("--include-cli", "--include-pkg", str(self.package), CLI_VERIFIER_STATUS="2")
        self.assertEqual(completed.returncode, 2)

    def test_include_pkg_needs_include_cli_and_an_existing_package(self) -> None:
        for arguments in (("--include-pkg", str(self.package)),
                          ("--include-cli", "--include-pkg"),
                          ("--include-cli", "--other", str(self.package)),
                          ("--include-cli", "--include-pkg", str(self.sandbox.path / "dist/missing.pkg"))):
            with self.subTest(arguments=arguments):
                completed = self.verify(*arguments)
                self.assertEqual(completed.returncode, 1)
                self.assertEqual(self.sandbox.calls_to("hdiutil"), [])


if __name__ == "__main__":
    unittest.main()
