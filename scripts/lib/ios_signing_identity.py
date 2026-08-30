#!/usr/bin/env python3
"""Privacy-safe validation of the local Apple Development signing identity.

The physical-device runner needs a *valid code-signing identity*, not merely a
team identifier or a certificate without its private key.  This helper keeps
certificate names and fingerprints out of its output while distinguishing the
operator actions that can make a device build possible.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import re
import subprocess
import sys
from typing import Sequence


IDENTITY_PATTERN = re.compile(
    r'^\s*\d+\)\s+([0-9A-Fa-f]{40})\s+"Apple Development:',
    re.MULTILINE,
)
PEM_PATTERN = re.compile(
    rb"-----BEGIN CERTIFICATE-----.*?-----END CERTIFICATE-----",
    re.DOTALL,
)


@dataclass(frozen=True)
class CertificateRecord:
    fingerprint: str
    team: str | None
    expired: bool


@dataclass(frozen=True)
class SigningDiagnosis:
    ready: bool
    reason: str
    valid_identity_count: int
    certificate_count: int
    matching_team_certificate_count: int

    def as_json(self) -> dict[str, object]:
        return {
            "ready": self.ready,
            "reason": self.reason,
            "validIdentityCount": self.valid_identity_count,
            "certificateCount": self.certificate_count,
            "matchingTeamCertificateCount": self.matching_team_certificate_count,
        }


def parse_identity_hashes(output: str) -> set[str]:
    return {match.upper() for match in IDENTITY_PATTERN.findall(output)}


def _openssl(pem: bytes, *arguments: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["/usr/bin/openssl", "x509", *arguments],
        input=pem,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def parse_certificates(pem_output: bytes) -> list[CertificateRecord]:
    records: list[CertificateRecord] = []
    for pem in PEM_PATTERN.findall(pem_output):
        fingerprint_result = _openssl(pem, "-noout", "-fingerprint", "-sha1")
        subject_result = _openssl(pem, "-noout", "-subject")
        if fingerprint_result.returncode != 0 or subject_result.returncode != 0:
            continue
        fingerprint_text = fingerprint_result.stdout.decode("utf-8", errors="replace")
        fingerprint = fingerprint_text.partition("=")[2].replace(":", "").strip().upper()
        if not re.fullmatch(r"[0-9A-F]{40}", fingerprint):
            continue
        subject = subject_result.stdout.decode("utf-8", errors="replace")
        team_match = re.search(r"\bOU\s*=\s*([^,/\n]+)", subject)
        team = team_match.group(1).strip() if team_match else None
        expiry_result = _openssl(pem, "-checkend", "0", "-noout")
        records.append(
            CertificateRecord(
                fingerprint=fingerprint,
                team=team,
                expired=expiry_result.returncode != 0,
            )
        )
    return records


def diagnose(
    identity_hashes: set[str],
    certificates: Sequence[CertificateRecord],
    expected_team: str | None,
) -> SigningDiagnosis:
    matching = [
        certificate
        for certificate in certificates
        if expected_team is None or certificate.team == expected_team
    ]
    valid = [
        certificate
        for certificate in matching
        if not certificate.expired and certificate.fingerprint in identity_hashes
    ]
    if valid:
        reason = "ready"
        ready = True
    elif matching and any(not certificate.expired for certificate in matching):
        reason = "missing_private_key"
        ready = False
    elif matching:
        reason = "expired_certificate"
        ready = False
    elif certificates and expected_team is not None:
        reason = "team_mismatch"
        ready = False
    elif identity_hashes:
        reason = "unresolved_identity"
        ready = False
    else:
        reason = "missing_certificate"
        ready = False
    return SigningDiagnosis(
        ready=ready,
        reason=reason,
        valid_identity_count=len(valid),
        certificate_count=len(certificates),
        matching_team_certificate_count=len(matching),
    )


def inspect_keychain(expected_team: str | None) -> SigningDiagnosis:
    identities = subprocess.run(
        ["/usr/bin/security", "find-identity", "-v", "-p", "codesigning"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    certificates = subprocess.run(
        [
            "/usr/bin/security",
            "find-certificate",
            "-a",
            "-c",
            "Apple Development",
            "-p",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if identities.returncode != 0 or certificates.returncode not in (0, 44):
        return SigningDiagnosis(False, "keychain_unavailable", 0, 0, 0)
    return diagnose(
        parse_identity_hashes(identities.stdout),
        parse_certificates(certificates.stdout),
        expected_team,
    )


def human_message(diagnosis: SigningDiagnosis) -> str:
    return {
        "ready": "valid Apple Development identity and private key available",
        "expired_certificate": (
            "Apple Development certificate expired; create a replacement in "
            "Xcode Settings > Accounts > Manage Certificates"
        ),
        "missing_private_key": (
            "Apple Development certificate has no usable private key; create or import "
            "a matching development identity"
        ),
        "team_mismatch": "Apple Development certificate does not belong to the selected team",
        "unresolved_identity": "Apple Development identity could not be matched to its certificate",
        "missing_certificate": (
            "no Apple Development certificate/private key is installed; create one in "
            "Xcode Settings > Accounts > Manage Certificates"
        ),
        "keychain_unavailable": "the login Keychain signing inventory could not be inspected",
    }[diagnosis.reason]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("check",))
    parser.add_argument("--team")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    diagnosis = inspect_keychain(args.team)
    if args.json:
        print(json.dumps(diagnosis.as_json(), sort_keys=True))
    else:
        print(human_message(diagnosis))
    return 0 if diagnosis.ready else 1


if __name__ == "__main__":
    sys.exit(main())
