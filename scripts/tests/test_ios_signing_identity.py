from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import unittest


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

    def test_device_build_checks_identity_before_package_resolution(self) -> None:
        source = (ROOT / "scripts" / "ios_device.sh").read_text(encoding="utf-8")
        build = source[source.index("cmd_build() {") : source.index("cmd_install() {")]
        self.assertLess(
            build.index('require_development_identity "$team"'),
            build.index("ensure_spm_resolved"),
        )
        preflight = source[source.index("cmd_preflight() {") : source.index("_gate_generation_check() {")]
        self.assertIn('development_identity_status "$team"', preflight)


if __name__ == "__main__":
    unittest.main()
