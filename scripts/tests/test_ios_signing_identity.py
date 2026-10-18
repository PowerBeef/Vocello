from __future__ import annotations

import importlib.util
from pathlib import Path
import subprocess
import sys
import unittest

from shell_stubs import LaneShell


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "scripts" / "lib" / "ios_signing_identity.py"
SPEC = importlib.util.spec_from_file_location("ios_signing_identity", MODULE_PATH)
assert SPEC and SPEC.loader
signing = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = signing
SPEC.loader.exec_module(signing)


class IOSSigningIdentityTests(unittest.TestCase):
    def certificate(
        self,
        fingerprint: str = "A" * 40,
        team: str = "TEAM123456",
        expired: bool = False,
    ) -> signing.CertificateRecord:
        return signing.CertificateRecord(fingerprint, team, expired)

    def test_identity_parser_selects_only_apple_development(self) -> None:
        output = '''
  1) AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA "Developer ID Application: Example"
  2) BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB "Apple Development: Example"
     2 valid identities found
'''
        self.assertEqual(signing.parse_identity_hashes(output), {"B" * 40})

    def test_matching_valid_identity_is_ready(self) -> None:
        result = signing.diagnose({"A" * 40}, [self.certificate()], "TEAM123456")
        self.assertTrue(result.ready)
        self.assertEqual(result.reason, "ready")

    def test_expired_certificate_is_not_a_signing_identity(self) -> None:
        result = signing.diagnose(set(), [self.certificate(expired=True)], "TEAM123456")
        self.assertFalse(result.ready)
        self.assertEqual(result.reason, "expired_certificate")

    def test_certificate_without_private_key_fails_closed(self) -> None:
        result = signing.diagnose(set(), [self.certificate()], "TEAM123456")
        self.assertFalse(result.ready)
        self.assertEqual(result.reason, "missing_private_key")

    def test_team_mismatch_is_distinct(self) -> None:
        result = signing.diagnose({"A" * 40}, [self.certificate(team="OTHERTEAM1")], "TEAM123456")
        self.assertFalse(result.ready)
        self.assertEqual(result.reason, "team_mismatch")

    def test_missing_certificate_is_distinct(self) -> None:
        result = signing.diagnose(set(), [], "TEAM123456")
        self.assertFalse(result.ready)
        self.assertEqual(result.reason, "missing_certificate")

    def test_json_output_is_privacy_safe(self) -> None:
        result = signing.diagnose(set(), [self.certificate(expired=True)], "TEAM123456")
        encoded = result.as_json()
        self.assertNotIn("fingerprint", encoded)
        self.assertNotIn("team", encoded)
        self.assertEqual(encoded["certificateCount"], 1)


IDENTITY = "scripts/lib/ios_signing_identity.py"
VALID = 'echo "Apple Development identity valid"'
EXPIRED = 'echo "the Apple Development certificate expired"; exit 1'
DEVICE_LIST = r'''
[[ "$1 $2 $3" == "devicectl list devices" ]] || exit 97
while (( $# )); do case "$1" in --json-output) output="$2"; shift 2 ;; *) shift ;; esac; done
printf '{"result": {"devices": [{"identifier": "fixture-device", "connectionProperties": {"pairingState": "paired"}}]}}\n' >"$output"
'''


class DeviceLaneSigningTests(unittest.TestCase):
    """The shipped scripts/ios_device.sh build and preflight over stand-ins
    (scripts/tests/shell_stubs.py): the identity check is a stand-in, Xcode a shim."""

    def build(self, identity: str) -> tuple[subprocess.CompletedProcess[str], LaneShell]:
        shell = LaneShell(self, "ios_device.sh")
        shell.helper(IDENTITY, identity)
        body = (
            "qv_stub require_ios_xcode_platform\nqv_stub require_build_free_space\n"
            "qv_stub ensure_project_regenerated\nqv_stub ensure_spm_resolved\n"
            "derive_team() { printf 'TEAMFIXTURE\\n'; }\n"
            "resolve_device() { printf 'fixture-device\\n'; }\n"
            'xcb_run() { qv_record xcb_run "$@"; return 65; }\n'
            "cmd_build\n"
        )
        return shell.run(body), shell

    def test_device_build_checks_the_identity_before_regeneration_or_package_resolution(self) -> None:
        completed, shell = self.build(EXPIRED)
        self.assertEqual(completed.returncode, 1)
        self.assertIn("device signing unavailable — the Apple Development certificate expired", completed.stderr)
        # The refused identity is the last thing the build did.
        self.assertEqual(shell.calls()[-1], [IDENTITY, "check", "--team", "TEAMFIXTURE"])
        for later in ("ensure_project_regenerated", "ensure_spm_resolved", "xcb_run"):
            self.assertNotIn(later, shell.names())

        completed, shell = self.build(VALID)
        self.assertEqual(completed.returncode, 1, "the stand-in Xcode build fails")
        self.assertIn("device build failed", completed.stderr)
        order = [shell.index(IDENTITY), shell.index("ensure_project_regenerated"),
                 shell.index("ensure_spm_resolved"), shell.index("xcb_run")]
        self.assertEqual(order, sorted(order))

    def test_preflight_reports_the_signing_identity_it_checked(self) -> None:
        for identity, status, line in ((VALID, 0, "signing: OK team TEAMFIXTURE (Apple Development identity valid)"),
                                       (EXPIRED, 1, "signing: ✗ the Apple Development certificate expired")):
            with self.subTest(status=status):
                shell = LaneShell(self, "ios_device.sh")
                shell.helper(IDENTITY, identity)
                shell.tool("xcrun", DEVICE_LIST)
                body = (
                    "derive_team() { printf 'TEAMFIXTURE\\n'; }\n"
                    "resolve_device() { printf 'fixture-device\\n'; }\n"
                    "qv_stub guard_device_state\n"
                    'mkdir -p "$APP_PATH"\n'
                    "cmd_preflight\n"
                )
                completed = shell.run(body)
                self.assertEqual(completed.returncode, status, completed.stderr)
                self.assertIn(line, completed.stderr)
                self.assertEqual(shell.calls_to(IDENTITY), [["check", "--team", "TEAMFIXTURE"]])


if __name__ == "__main__":
    unittest.main()
