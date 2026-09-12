from __future__ import annotations

import importlib.util
import base64
import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "supply_chain_contract.py"
SPEC = importlib.util.spec_from_file_location("supply_chain_contract", SCRIPT)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


class SupplyChainContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        for relative in (".github/workflows", "config", "website"):
            (self.root / relative).mkdir(parents=True, exist_ok=True)
        self.sha = "a" * 40
        self.write_toolchain({
            "actions/checkout": {"version": "v4", "sha": self.sha},
            "actions/upload-artifact": {"version": "v4", "sha": self.sha},
        })
        (self.root / ".github/workflows/ci.yml").write_text(
            "jobs:\n  test:\n    steps:\n"
            f"      - name: Checkout\n        uses: actions/checkout@{self.sha} # v4\n"
            f"      - name: Upload\n        uses: actions/upload-artifact@{self.sha} # v4\n",
            encoding="utf-8",
        )
        (self.root / ".github/dependabot.yml").write_text(
            "\n".join(f'  - package-ecosystem: "{eco}"' for eco in ("github-actions", "npm", "swift"))
            + '\n    directory: "/Packages/VocelloQwen3Core"\n',
            encoding="utf-8",
        )
        (self.root / "website/package.json").write_text(json.dumps({
            "scripts": {"lint": "x", "test": "x", "build": "x", "check": "x"},
        }), encoding="utf-8")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def write_toolchain(self, actions: dict, native: dict | None = None) -> None:
        (self.root / "config/toolchain.json").write_text(json.dumps({
            "schemaVersion": 1,
            "native": native or {}, "release": {}, "website": {},
            "actions": actions,
        }), encoding="utf-8")

    def test_valid_fixture_passes(self) -> None:
        self.assertEqual(module.validate(self.root), [])

    def test_mutable_action_ref_fails(self) -> None:
        path = self.root / ".github/workflows/ci.yml"
        path.write_text(path.read_text().replace(f"actions/checkout@{self.sha}", "actions/checkout@v4"))
        self.assertTrue(any("not pinned to a full SHA" in e for e in module.validate(self.root)))

    def test_sha_must_match_toolchain_manifest(self) -> None:
        self.write_toolchain({
            "actions/checkout": {"version": "v4", "sha": "b" * 40},
            "actions/upload-artifact": {"version": "v4", "sha": self.sha},
        })
        self.assertTrue(any("SHA differs" in e for e in module.validate(self.root)))

    def test_unlisted_and_unused_actions_fail(self) -> None:
        self.write_toolchain({
            "actions/checkout": {"version": "v4", "sha": self.sha},
            "actions/setup-node": {"version": "v4", "sha": self.sha},
        })
        errors = module.validate(self.root)
        self.assertTrue(any("absent from config/toolchain.json: actions/upload-artifact" in e for e in errors))
        self.assertTrue(any("configured action is unused: actions/setup-node" in e for e in errors))

    def test_dependabot_must_cover_every_ecosystem(self) -> None:
        (self.root / ".github/dependabot.yml").write_text('  - package-ecosystem: "npm"\n')
        errors = module.validate(self.root)
        self.assertTrue(any("does not cover github-actions" in e for e in errors))
        self.assertTrue(any("does not cover swift" in e for e in errors))

    def test_website_scripts_must_stay_deterministic(self) -> None:
        (self.root / "website/package.json").write_text(json.dumps({"scripts": {"lint": "x"}}))
        self.assertTrue(any("missing the deterministic check script" in e for e in module.validate(self.root)))

    def test_toolchain_numpy_matches_the_whisper_adapter_runtime_pin(self) -> None:
        # The language producer is qualified under one numpy; CI installs the toolchain pin.
        root = Path(__file__).resolve().parents[2]
        toolchain = json.loads((root / "config/toolchain.json").read_text(encoding="utf-8"))
        candidates = json.loads((root / "config/delivery-evaluator-v2-candidates.json").read_text(encoding="utf-8"))
        whisper = candidates["candidates"]["whisper-small-mlx"]["runtimeDependencies"]["numpy"]
        self.assertEqual(toolchain["native"]["numpy"]["version"], whisper)

    def test_installed_tool_versions_are_checked_exactly(self) -> None:
        self.write_toolchain(
            {"actions/checkout": {"version": "v4", "sha": self.sha},
             "actions/upload-artifact": {"version": "v4", "sha": self.sha}},
            native={"xcodegen": {"version": "2.46.0", "versionCommand": ["xcodegen", "--version"]}},
        )
        original = module._tool_output
        try:
            module._tool_output = lambda command: "Version: 2.46.0\n"
            self.assertEqual(module.validate(self.root, "native"), [])
            module._tool_output = lambda command: "Version: 2.46.10\n"
            self.assertTrue(any("expected 2.46.0" in e for e in module.validate(self.root, "native")))
        finally:
            module._tool_output = original


class ReleaseCredentialHygieneTests(unittest.TestCase):
    """Execute real workflow blocks with dummy bytes; never call Apple/ASC tools.

    Only home paths and the platform-specific plist executable are substituted.
    Permission checks run before chmod/import and after copies, not just at the end.
    """

    ROOT = SCRIPT.parent.parent
    SETUP_MAC = "Setup signing keychain"
    SETUP_KEY = "Write App Store Connect API key file"
    SETUP_IOS = "Import signing assets"
    STUBS = r'''
assert_private() {
  "$CREDENTIAL_TEST_PYTHON" -c 'import os,pathlib,stat; root=pathlib.Path(os.environ["CREDENTIAL_TEST_ROOT"]); files=[p for p in root.rglob("*") if p.is_file() and p.suffix in (".p8",".p12",".mobileprovision",".keychain-db")]; assert all(stat.S_IMODE(p.stat().st_mode)==0o600 for p in files), "credential permissions"'
}
security() {
  assert_private || return 99
  case "$1" in
    create-keychain) : > "${@: -1}" ;;
    delete-keychain)
      [ "$FAIL_STAGE" != cleanup ] || return 57
      command rm -f "${@: -1}"; return ;;
    import)
      if [ "$FAIL_STAGE" = terminate ]; then kill -TERM "$$"; fi ;;
    find-identity) printf '%s\n' '1) FIXTURE "Developer ID Application: Fixture"' ;;
    cms) printf '%s\n' '<plist><dict/></plist>' ;;
    list-keychain|list-keychains|set-keychain-settings|unlock-keychain|set-key-partition-list) : ;;
    *) return 98 ;;
  esac
  [ "$FAIL_STAGE" != "$1" ] || return 41
}
base64() {
  assert_private || return 99
  if [ "$FAIL_STAGE" = decode ]; then printf 'partial'; return 41; fi
  "$CREDENTIAL_TEST_PYTHON" -c 'import base64,sys; sys.stdout.buffer.write(base64.b64decode(sys.stdin.buffer.read(),validate=False))'
}
chmod() {
  assert_private || return 99
  [ "$FAIL_STAGE" != chmod ] || return 41
  command chmod "$@"
}
cp() {
  assert_private || return 99
  command cp "$@" || return
  assert_private || return 99
  case "$1:$FAIL_STAGE" in
    *.mobileprovision:profile-copy|*.p8:key-copy) return 41 ;;
  esac
}
fixture_plistbuddy() { printf '%s\n' 'AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE'; }
openssl() { printf '%s\n' 'fixture-random-password'; }
uuidgen() { printf '%s\n' 'fixture-random-password'; }
asc() { return 0; }
'''

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="vocello-credential-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.runner = self.root / "runner with spaces"
        self.runner.mkdir()
        self.user_root = self.root / "isolated user"
        self.user_root.mkdir()
        self.env_file = self.root / "github-env"
        self.env_file.touch()
        encoded = base64.b64encode(b"fixture-only-not-a-real-credential").decode()
        self.env = {
            "PATH": os.environ["PATH"], "RUNNER_TEMP": str(self.runner),
            "GITHUB_ENV": str(self.env_file), "CREDENTIAL_TEST_ROOT": str(self.root),
            "CREDENTIAL_TEST_HOME": str(self.user_root), "CREDENTIAL_TEST_PYTHON": sys.executable,
            "CERT_BASE64": encoded, "CERT_PASSWORD": "fixture-password",
            "IOS_DIST_CERT_P12": encoded, "IOS_DIST_CERT_PASSWORD": "fixture-password",
            "IOS_PROVISION_PROFILE": encoded, "ASC_API_KEY_P8": encoded,
            "APPLE_API_KEY_ID": "FIXTURE123", "ASC_API_KEY_ID": "FIXTURE123",
            "NOTARY_KEY_P8": "-----BEGIN PRIVATE KEY-----\nfixture-only-invalid-key\n",
            "FAIL_STAGE": "",
        }

    def block(self, name):
        workflow = (self.ROOT / ".github/workflows/release.yml").read_text()
        step = workflow.split("      - name: " + name + "\n", 1)[1]
        step = step.split("\n      - name:", 1)[0]
        run = step.split("        run: |\n", 1)[1]
        lines = []
        for line in run.splitlines():
            if line.strip() and not line.startswith("          "):
                break
            lines.append(line)
        return textwrap.dedent("\n".join(lines))

    def run_block(self, name, failure="", mutation=None):
        body = self.block(name)
        if mutation:
            body = mutation(body)
        # Do not repurpose HOME or touch real home/Keychain state.
        body = body.replace("$HOME", "${CREDENTIAL_TEST_HOME}").replace("~/", '"${CREDENTIAL_TEST_HOME}"/')
        body = body.replace("/usr/libexec/PlistBuddy", "fixture_plistbuddy")
        self.assertNotIn("${{", body)
        self.assertNotIn("$HOME", body)
        env = self.env | {"FAIL_STAGE": failure}
        result = subprocess.run(["bash", "-euo", "pipefail", "-c", self.STUBS + "\n" + body],
                                cwd=self.root, env=env, capture_output=True, text=True, timeout=15)
        for secret in ("fixture-password", "fixture-random-password", "fixture-only-not-a-real-credential",
                       self.env["CERT_BASE64"]):
            self.assertNotIn(secret, result.stdout + result.stderr)
        # Mimic GitHub's next-step environment; partial setup registrations survive.
        for line in self.env_file.read_text().splitlines():
            key, value = line.split("=", 1)
            self.env[key] = value
        return result

    def credentials(self):
        return [p for p in self.root.rglob("*") if p.is_file()
                and p.suffix in (".p8", ".p12", ".mobileprovision", ".keychain-db")]

    def test_gitignore_blocks_credentials_but_keeps_documented_examples(self):
        (self.root / ".gitignore").write_text((self.ROOT / ".gitignore").read_text())
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        blocked = ["key.p8", "nested/key.p12", "key.pfx", "secret.key", "private.pem",
                   "signing.keychain-db", "signing.keychain", "app.mobileprovision", "app.provisionprofile",
                   ".env", ".env.local", "nested/.env.production", ".asc/config.json",
                   ".appstoreconnect/private_keys/key.p8", "id_rsa", "nested/id_ed25519"]
        allowed = [".env.example", "nested/.env.sample", "Tests/Fixtures/VocelloExports.storekit",
                   "Sources/iOS/Commerce/IOSStoreKitClient.swift", "config/public-product-facts.json"]
        r = subprocess.run(["git", "-c", "core.excludesFile=/dev/null", "check-ignore", "--stdin"],
                           cwd=self.root, input="\n".join(blocked + allowed), capture_output=True, text=True)
        self.assertEqual(set(r.stdout.splitlines()), set(blocked))

    def test_permissions_and_success_cleanup_on_both_platforms(self):
        for name in (self.SETUP_MAC, self.SETUP_KEY):
            r = self.run_block(name)
            self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(len(self.credentials()), 2)  # keychain + notary key, no decoded P12
        self.assertEqual(self.run_block("Cleanup signing material").returncode, 0)
        self.assertFalse(self.credentials())
        r = self.run_block(self.SETUP_IOS)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(len(self.credentials()), 4)  # keychain + profile + two key copies
        self.assertEqual(self.run_block("Cleanup iOS signing material").returncode, 0)
        self.assertFalse(self.credentials())
        self.assertEqual(self.run_block("Cleanup iOS signing material").returncode, 0)

    def test_early_failures_and_termination_remove_partial_material(self):
        cases = [(self.SETUP_MAC, x) for x in ("decode", "create-keychain", "import", "set-key-partition-list", "terminate")]
        cases += [(self.SETUP_KEY, "chmod")]
        cases += [(self.SETUP_IOS, x) for x in ("create-keychain", "decode", "import", "profile-copy", "chmod", "key-copy", "terminate")]
        for name, failure in cases:
            with self.subTest(step=name, failure=failure):
                r = self.run_block(name, failure)
                self.assertEqual(r.returncode, 143 if failure == "terminate" else 41, r.stderr)
                self.assertFalse(self.credentials(), str(self.credentials()))

    def test_existing_files_are_not_overwritten_or_deleted(self):
        cases = [(self.SETUP_MAC, self.runner / "cert.p12"),
                 (self.SETUP_KEY, self.runner / "AuthKey_FIXTURE123.p8"),
                 (self.SETUP_IOS, self.user_root / ".appstoreconnect/private_keys/AuthKey_FIXTURE123.p8"),
                 (self.SETUP_IOS, self.user_root / "Library/MobileDevice/Provisioning Profiles/AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE.mobileprovision")]
        for name, path in cases:
            with self.subTest(step=name, path=path.name):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"existing-owner")
                path.chmod(0o600)
                r = self.run_block(name)
                self.assertNotEqual(r.returncode, 0)
                self.assertEqual(path.read_bytes(), b"existing-owner")
                self.assertEqual(self.credentials(), [path])
                path.unlink()

    def test_cleanup_failure_does_not_skip_remaining_credentials(self):
        self.assertEqual(self.run_block(self.SETUP_IOS).returncode, 0)
        self.assertEqual(self.run_block("Cleanup iOS signing material", "cleanup").returncode, 1)
        self.assertEqual([p.suffix for p in self.credentials()], [".keychain-db"])
        self.assertEqual(self.run_block("Cleanup iOS signing material").returncode, 0)
        self.assertFalse(self.credentials())

    def test_invalid_key_content_and_missing_environment_file_fail_cleanly(self):
        self.env["NOTARY_KEY_P8"] = "invalid-fixture-key"
        self.assertEqual(self.run_block(self.SETUP_KEY).returncode, 1)
        self.assertFalse(self.credentials())
        self.env["GITHUB_ENV"] = str(self.root / "missing-parent" / "env")
        for name in (self.SETUP_MAC, self.SETUP_KEY, self.SETUP_IOS):
            with self.subTest(step=name):
                self.assertNotEqual(self.run_block(name).returncode, 0)
                self.assertFalse(self.credentials())

    def test_cleanup_steps_are_safe_without_prior_setup(self):
        for name in ("Cleanup signing material", "Cleanup iOS signing material"):
            self.assertEqual(self.run_block(name).returncode, 0)
            self.assertFalse(self.credentials())

    def test_missing_restrictions_and_traps_are_detected(self):
        r = self.run_block(self.SETUP_KEY, mutation=lambda s: s.replace("umask 077", "umask 022"))
        self.assertEqual(r.returncode, 99)  # permission check before chmod
        self.assertFalse(self.credentials())
        r = self.run_block(self.SETUP_KEY, "chmod", mutation=lambda s: s.replace("trap cleanup_setup EXIT", "trap - EXIT"))
        self.assertEqual(r.returncode, 41)
        self.assertEqual(len(self.credentials()), 1)  # deliberate-negative fixture
        self.assertEqual(self.run_block("Cleanup signing material").returncode, 0)
        self.assertFalse(self.credentials())


if __name__ == "__main__":
    unittest.main()
