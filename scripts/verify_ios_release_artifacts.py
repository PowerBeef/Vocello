#!/usr/bin/env python3
"""Fail-closed, non-device verification for the archived and exported iOS app."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import plistlib
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_VERSION = 2
SUMMARY_NAME = "ios-release-artifact-verification.json"
DIGEST_PATTERN = re.compile(r"[0-9a-f]{64}")


class VerificationError(ValueError):
    """A release artifact does not satisfy the repository contract."""


@dataclass(frozen=True)
class ExpectedIOSIdentity:
    bundle_identifier: str
    marketing_version: str
    build_number: str
    application_groups: tuple[str, ...]
    increased_memory_limit: bool
    privacy_manifest_sha256: str
    attribution_manifest_sha256: str


@dataclass(frozen=True)
class BundleSnapshot:
    label: str
    bundle_identifier: str
    marketing_version: str
    build_number: str
    architectures: tuple[str, ...]
    macho_uuids: tuple[str, ...]
    executable_sha256: str
    signature_normalized_executable_sha256: str
    bundle_sha256: str
    signature_verified: bool
    signing_authority_verified: bool
    signing_certificate_trust_verified: bool
    distribution_authority_verified: bool
    team_identifier_verified: bool
    provisioning_profile_verified: bool
    signer_profile_certificate_match: bool
    application_identifier_verified: bool
    application_groups: tuple[str, ...]
    increased_memory_limit: bool
    get_task_allow: bool
    privacy_manifest_sha256: str
    privacy_manifest_verified: bool
    attribution_manifest_sha256: str
    attribution_manifest_verified: bool

    def public_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "bundleIdentifier": self.bundle_identifier,
            "marketingVersion": self.marketing_version,
            "buildNumber": self.build_number,
            "architectures": list(self.architectures),
            "machOUUIDs": list(self.macho_uuids),
            "executableSHA256": self.executable_sha256,
            "signatureNormalizedExecutableSHA256": self.signature_normalized_executable_sha256,
            "bundleSHA256": self.bundle_sha256,
            "signatureVerified": self.signature_verified,
            "signingAuthorityVerified": self.signing_authority_verified,
            "signingCertificateTrustVerified": self.signing_certificate_trust_verified,
            "distributionAuthorityVerified": self.distribution_authority_verified,
            "teamIdentifierVerified": self.team_identifier_verified,
            "provisioningProfileVerified": self.provisioning_profile_verified,
            "signerProfileCertificateMatch": self.signer_profile_certificate_match,
            "applicationIdentifierVerified": self.application_identifier_verified,
            "applicationGroups": list(self.application_groups),
            "increasedMemoryLimit": self.increased_memory_limit,
            "getTaskAllow": self.get_task_allow,
            "privacyManifestSHA256": self.privacy_manifest_sha256,
            "privacyManifestVerified": self.privacy_manifest_verified,
            "attributionManifestSHA256": self.attribution_manifest_sha256,
            "attributionManifestVerified": self.attribution_manifest_verified,
        }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _bundle_digest(path: Path) -> str:
    digest = hashlib.sha256()
    for item in sorted((candidate for candidate in path.rglob("*") if candidate.is_file()), key=lambda p: p.as_posix()):
        relative = item.relative_to(path).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        digest.update(bytes.fromhex(_sha256(item)))
    return digest.hexdigest()


def _canonical_plist_digest(payload: Mapping[str, Any]) -> str:
    encoded = plistlib.dumps(dict(payload), fmt=plistlib.FMT_BINARY, sort_keys=True)
    return hashlib.sha256(encoded).hexdigest()


def _atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(payload, indent=2, sort_keys=True).encode("utf-8") + b"\n"
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=f".{path.name}.", delete=False) as handle:
        temporary = Path(handle.name)
        handle.write(encoded)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def _read_plist(path: Path) -> dict[str, Any]:
    try:
        payload = plistlib.loads(path.read_bytes())
    except (OSError, plistlib.InvalidFileException) as error:
        raise VerificationError(f"invalid property list: {path.name}") from error
    if not isinstance(payload, dict):
        raise VerificationError(f"property list root must be a dictionary: {path.name}")
    return payload


def _validate_privacy_manifest(payload: Mapping[str, Any], label: str) -> str:
    if payload.get("NSPrivacyTracking") is not False:
        raise VerificationError(f"{label} privacy manifest must disable tracking")
    for key in ("NSPrivacyTrackingDomains", "NSPrivacyCollectedDataTypes", "NSPrivacyAccessedAPITypes"):
        if not isinstance(payload.get(key), list):
            raise VerificationError(f"{label} privacy manifest has an invalid {key} value")
    if any(not isinstance(value, str) for value in payload["NSPrivacyTrackingDomains"]):
        raise VerificationError(f"{label} privacy manifest tracking domains are malformed")
    if any(not isinstance(value, dict) for value in payload["NSPrivacyCollectedDataTypes"]):
        raise VerificationError(f"{label} privacy manifest collected-data declarations are malformed")
    for declaration in payload["NSPrivacyAccessedAPITypes"]:
        if not isinstance(declaration, dict):
            raise VerificationError(f"{label} privacy manifest accessed-API declarations are malformed")
        reasons = declaration.get("NSPrivacyAccessedAPITypeReasons")
        if (
            not isinstance(declaration.get("NSPrivacyAccessedAPIType"), str)
            or not isinstance(reasons, list)
            or not reasons
            or any(not isinstance(reason, str) or not reason for reason in reasons)
        ):
            raise VerificationError(f"{label} privacy manifest accessed-API declaration is malformed")
    return _canonical_plist_digest(payload)


def _root_privacy_manifest_digest(app: Path, label: str) -> str:
    try:
        candidates = [
            candidate
            for candidate in app.iterdir()
            if (
                candidate.is_file()
                and not candidate.is_symlink()
                and candidate.name.casefold() == "privacyinfo.xcprivacy"
            )
        ]
    except OSError as error:
        raise VerificationError(f"cannot inspect {label} application resources") from error
    if len(candidates) != 1 or candidates[0].name != "PrivacyInfo.xcprivacy":
        raise VerificationError(f"{label} must contain exactly one root PrivacyInfo.xcprivacy")
    return _validate_privacy_manifest(_read_plist(candidates[0]), label)


def _root_attribution_manifest_digest(app: Path, label: str) -> str:
    try:
        candidates = [
            candidate
            for candidate in app.iterdir()
            if candidate.is_file()
            and not candidate.is_symlink()
            and candidate.name.casefold() == "third_party_attributions.json"
        ]
    except OSError as error:
        raise VerificationError(f"cannot inspect {label} attribution resources") from error
    if len(candidates) != 1 or candidates[0].name != "third_party_attributions.json":
        raise VerificationError(f"{label} must contain exactly one root third_party_attributions.json")
    try:
        payload = json.loads(candidates[0].read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise VerificationError(f"{label} attribution manifest is invalid") from error
    if (
        not isinstance(payload, dict)
        or payload.get("schemaVersion") != 1
        or not isinstance(payload.get("components"), list)
        or not payload["components"]
        or not isinstance(payload.get("modelArtifacts"), list)
        or not payload["modelArtifacts"]
        or not isinstance(payload.get("licenses"), list)
        or not payload["licenses"]
    ):
        raise VerificationError(f"{label} attribution manifest is incomplete")
    return _sha256(candidates[0])


def _target_block(project_text: str, target: str) -> str:
    targets = re.search(r"(?ms)^targets:\n(?P<body>.*?)(?=^[A-Za-z0-9_-]+:\n|\Z)", project_text)
    if not targets:
        raise VerificationError("project targets section is missing")
    match = re.search(
        rf"(?ms)^  {re.escape(target)}:\n(?P<body>.*?)(?=^  [A-Za-z0-9_-]+:\n|\Z)",
        targets.group("body"),
    )
    if not match:
        raise VerificationError(f"project target is missing: {target}")
    return match.group("body")


def _project_base_settings_block(project_text: str) -> str:
    match = re.search(r"(?ms)^settings:\n  base:\n(?P<body>(?:^    \S.*\n)+)", project_text)
    return match.group("body") if match else ""


def _setting(block: str, key: str, *, indent: int = 8) -> str:
    match = re.search(
        rf"(?m)^\s{{{indent}}}{re.escape(key)}:\s*(?:\"([^\"]+)\"|'([^']+)'|([^#\n]+))", block
    )
    if not match:
        raise VerificationError(f"project setting is missing: {key}")
    return next(group.strip() for group in match.groups() if group is not None)


def _inherited_setting(target_block: str, project_settings: str, key: str) -> str:
    """Resolve a build setting the way Xcode does: target scope first, then the
    project-level settings block. Version identity moved to project scope in 2.2.1
    so generated framework Info.plists inherit CFBundleShortVersionString."""
    try:
        return _setting(target_block, key)
    except VerificationError:
        return _setting(project_settings, key, indent=4)


def load_expected_identity(root: Path = ROOT) -> ExpectedIOSIdentity:
    project_text = (root / "project.yml").read_text(encoding="utf-8")
    target = _target_block(project_text, "VocelloiOS")
    project_settings = _project_base_settings_block(project_text)
    matrix = json.loads((root / "config/apple-platform-capability-matrix.json").read_text(encoding="utf-8"))
    app = matrix["iOS"]["app"]
    project_bundle = _setting(target, "PRODUCT_BUNDLE_IDENTIFIER")
    if project_bundle != app["bundleIdentifier"]:
        raise VerificationError("project and capability-matrix iOS bundle identifiers differ")
    groups = tuple(sorted(str(value) for value in app["applicationGroups"]))
    privacy_manifest = _read_plist(root / "Sources/PrivacyInfo.xcprivacy")
    attribution_manifest = root / "Sources/Resources/third_party_attributions.json"
    return ExpectedIOSIdentity(
        bundle_identifier=project_bundle,
        marketing_version=_inherited_setting(target, project_settings, "MARKETING_VERSION"),
        build_number=_inherited_setting(target, project_settings, "CURRENT_PROJECT_VERSION"),
        application_groups=groups,
        increased_memory_limit=bool(
            app["booleanEntitlements"]["com.apple.developer.kernel.increased-memory-limit"]
        ),
        privacy_manifest_sha256=_validate_privacy_manifest(privacy_manifest, "source"),
        attribution_manifest_sha256=_sha256(attribution_manifest),
    )


def _run_bytes(arguments: Sequence[str]) -> tuple[bytes, bytes]:
    completed = subprocess.run(arguments, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if completed.returncode:
        diagnostic = completed.stderr.decode("utf-8", errors="replace").strip().splitlines()
        suffix = f": {diagnostic[-1]}" if diagnostic else ""
        raise VerificationError(f"command failed: {Path(arguments[0]).name}{suffix}")
    return completed.stdout, completed.stderr


def _codesign_entitlements(app: Path) -> dict[str, Any]:
    stdout, _ = _run_bytes(["/usr/bin/codesign", "-d", "--entitlements", ":-", str(app)])
    try:
        payload = plistlib.loads(stdout)
    except plistlib.InvalidFileException as error:
        raise VerificationError("codesign returned invalid entitlements") from error
    if not isinstance(payload, dict):
        raise VerificationError("codesign entitlements root must be a dictionary")
    return payload


def _provisioning_profile(app: Path) -> dict[str, Any]:
    profile = app / "embedded.mobileprovision"
    if not profile.is_file():
        raise VerificationError("embedded provisioning profile is missing")
    stdout, _ = _run_bytes(["/usr/bin/security", "cms", "-D", "-i", str(profile)])
    try:
        payload = plistlib.loads(stdout)
    except plistlib.InvalidFileException as error:
        raise VerificationError("embedded provisioning profile is invalid") from error
    if not isinstance(payload, dict):
        raise VerificationError("provisioning profile root must be a dictionary")
    return payload


def _signature_authorities(app: Path) -> tuple[str, ...]:
    _, stderr = _run_bytes(["/usr/bin/codesign", "-d", "--verbose=4", str(app)])
    lines = stderr.decode("utf-8", errors="replace").splitlines()
    return tuple(line.partition("=")[2] for line in lines if line.startswith("Authority="))


def _trusted_signing_leaf_certificate(app: Path) -> bytes:
    with tempfile.TemporaryDirectory(prefix="vocello-ios-signing-certificate-") as directory:
        prefix = Path(directory) / "certificate"
        _run_bytes([
            "/usr/bin/codesign", "-d", f"--extract-certificates={prefix}", str(app),
        ])
        certificates: list[Path] = []
        index = 0
        while (candidate := Path(f"{prefix}{index}")).is_file():
            if not candidate.stat().st_size:
                raise VerificationError("codesign extracted an empty signing certificate")
            certificates.append(candidate)
            index += 1
        if not certificates:
            raise VerificationError("codesign did not extract a signing leaf certificate")
        verification = ["/usr/bin/security", "verify-cert", "-p", "codeSign", "-L", "-q"]
        for certificate in certificates:
            verification.extend(["-c", str(certificate)])
        _run_bytes(verification)
        return certificates[0].read_bytes()


def _signature_normalized_executable_digest(executable: Path) -> str:
    with tempfile.TemporaryDirectory(prefix="vocello-ios-unsigned-executable-") as directory:
        normalized = Path(directory) / "executable"
        shutil.copyfile(executable, normalized)
        normalized.chmod(0o700)
        _run_bytes(["/usr/bin/codesign", "--remove-signature", str(normalized)])
        return _sha256(normalized)


def _architectures(executable: Path) -> tuple[str, ...]:
    stdout, _ = _run_bytes(["/usr/bin/lipo", "-archs", str(executable)])
    return tuple(sorted(stdout.decode("utf-8").strip().split()))


def _macho_uuids(executable: Path) -> tuple[str, ...]:
    stdout, _ = _run_bytes(["/usr/bin/dwarfdump", "--uuid", str(executable)])
    # Decode once so malformed tool output cannot be silently accepted.
    text = stdout.decode("utf-8", errors="strict")
    parsed = tuple(sorted(match.upper() for match in re.findall(r"UUID: ([0-9A-Fa-f-]{36})", text)))
    if not parsed:
        raise VerificationError("main executable has no Mach-O UUID")
    return parsed


def _string_tuple(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        return ()
    return tuple(sorted(value))


def validate_bundle_contract(
    *,
    label: str,
    info: Mapping[str, Any],
    entitlements: Mapping[str, Any],
    profile: Mapping[str, Any],
    authorities: Sequence[str],
    signing_leaf_certificate: bytes,
    signing_certificate_trust_verified: bool,
    architectures: Sequence[str],
    macho_uuids: Sequence[str],
    expected: ExpectedIOSIdentity,
    expected_team_id: str,
    require_app_store_distribution: bool,
    executable_sha256: str,
    signature_normalized_executable_sha256: str,
    bundle_sha256: str,
    privacy_manifest_sha256: str,
    attribution_manifest_sha256: str,
) -> BundleSnapshot:
    identity = (
        str(info.get("CFBundleIdentifier", "")),
        str(info.get("CFBundleShortVersionString", "")),
        str(info.get("CFBundleVersion", "")),
    )
    expected_identity = (expected.bundle_identifier, expected.marketing_version, expected.build_number)
    if identity != expected_identity:
        raise VerificationError(f"{label} bundle identity does not match project.yml")
    if info.get("CFBundlePackageType") != "APPL":
        raise VerificationError(f"{label} is not an application bundle")
    supported_platforms = info.get("CFBundleSupportedPlatforms", [])
    if not isinstance(supported_platforms, list) or "iPhoneOS" not in supported_platforms:
        raise VerificationError(f"{label} does not declare the iPhoneOS platform")
    normalized_architectures = tuple(sorted(architectures))
    if normalized_architectures != ("arm64",):
        raise VerificationError(f"{label} architecture must be exactly arm64")
    normalized_uuids = tuple(sorted(macho_uuids))
    if not normalized_uuids:
        raise VerificationError(f"{label} main executable has no Mach-O UUID")
    for name, value in (
        ("executable", executable_sha256),
        ("signature-normalized executable", signature_normalized_executable_sha256),
        ("bundle", bundle_sha256),
        ("privacy manifest", privacy_manifest_sha256),
        ("attribution manifest", attribution_manifest_sha256),
    ):
        if DIGEST_PATTERN.fullmatch(value) is None:
            raise VerificationError(f"{label} {name} digest is malformed")
    if privacy_manifest_sha256 != expected.privacy_manifest_sha256:
        raise VerificationError(f"{label} privacy manifest differs from the source contract")
    if attribution_manifest_sha256 != expected.attribution_manifest_sha256:
        raise VerificationError(f"{label} attribution manifest differs from the source contract")
    if signing_certificate_trust_verified is not True:
        raise VerificationError(f"{label} signing certificate did not pass Apple code-signing trust evaluation")

    app_groups = _string_tuple(entitlements.get("com.apple.security.application-groups"))
    if app_groups != expected.application_groups:
        raise VerificationError(f"{label} application-group entitlements do not match the contract")
    increased_memory = entitlements.get("com.apple.developer.kernel.increased-memory-limit") is True
    if increased_memory != expected.increased_memory_limit:
        raise VerificationError(f"{label} increased-memory entitlement does not match the contract")
    get_task_allow = entitlements.get("get-task-allow") is True or entitlements.get("com.apple.security.get-task-allow") is True
    if require_app_store_distribution and get_task_allow:
        raise VerificationError(f"{label} carries get-task-allow")

    team_identifier = entitlements.get("com.apple.developer.team-identifier")
    application_identifier = entitlements.get("application-identifier")
    if team_identifier != expected_team_id:
        raise VerificationError(f"{label} signing-team entitlement does not match the expected team")
    distribution_authority = any(
        authority.startswith(("Apple Distribution:", "iPhone Distribution:"))
        for authority in authorities
    )
    development_authority = any(
        authority.startswith(("Apple Development:", "iPhone Developer:"))
        for authority in authorities
    )
    if not distribution_authority and not development_authority:
        raise VerificationError(f"{label} is not signed by an Apple development or distribution identity")
    if require_app_store_distribution and not distribution_authority:
        raise VerificationError(f"{label} is not signed by an Apple Distribution identity")

    profile_teams = profile.get("TeamIdentifier")
    if not isinstance(profile_teams, list) or profile_teams != [expected_team_id]:
        raise VerificationError(f"{label} provisioning team does not match the expected team")
    profile_entitlements = profile.get("Entitlements")
    if not isinstance(profile_entitlements, dict):
        raise VerificationError(f"{label} provisioning profile has no entitlement dictionary")
    application_prefixes = profile.get("ApplicationIdentifierPrefix")
    if (
        not isinstance(application_prefixes, list)
        or len(application_prefixes) != 1
        or not isinstance(application_prefixes[0], str)
        or re.fullmatch(r"[A-Z0-9]{10}", application_prefixes[0]) is None
    ):
        raise VerificationError(f"{label} provisioning profile has no valid App ID prefix")
    expected_application_identifier = f"{application_prefixes[0]}.{expected.bundle_identifier}"
    if (
        application_identifier != expected_application_identifier
        or profile_entitlements.get("application-identifier") != expected_application_identifier
    ):
        raise VerificationError(f"{label} provisioning application identifier is incorrect")
    if _string_tuple(profile_entitlements.get("com.apple.security.application-groups")) != expected.application_groups:
        raise VerificationError(f"{label} provisioning App Groups do not match the contract")
    if profile_entitlements.get("com.apple.developer.kernel.increased-memory-limit") is not True:
        raise VerificationError(f"{label} provisioning profile lacks the increased-memory capability")
    if require_app_store_distribution and profile_entitlements.get("get-task-allow") is True:
        raise VerificationError(f"{label} provisioning profile enables get-task-allow")
    if require_app_store_distribution and (
        profile.get("ProvisionedDevices") or profile.get("ProvisionsAllDevices") is True
    ):
        raise VerificationError(f"{label} does not use an App Store distribution profile")
    expiration = profile.get("ExpirationDate")
    if not isinstance(expiration, datetime):
        raise VerificationError(f"{label} provisioning profile has no expiration date")
    normalized_expiration = expiration if expiration.tzinfo else expiration.replace(tzinfo=timezone.utc)
    if normalized_expiration <= datetime.now(timezone.utc):
        raise VerificationError(f"{label} provisioning profile is expired")
    profile_certificates = profile.get("DeveloperCertificates")
    if (
        not isinstance(profile_certificates, list)
        or not profile_certificates
        or any(not isinstance(certificate, bytes) for certificate in profile_certificates)
    ):
        raise VerificationError(f"{label} provisioning profile has no valid signing certificates")
    if signing_leaf_certificate not in profile_certificates:
        raise VerificationError(f"{label} signing certificate is not authorized by the provisioning profile")

    return BundleSnapshot(
        label=label,
        bundle_identifier=identity[0],
        marketing_version=identity[1],
        build_number=identity[2],
        architectures=normalized_architectures,
        macho_uuids=normalized_uuids,
        executable_sha256=executable_sha256,
        signature_normalized_executable_sha256=signature_normalized_executable_sha256,
        bundle_sha256=bundle_sha256,
        signature_verified=True,
        signing_authority_verified=True,
        signing_certificate_trust_verified=True,
        distribution_authority_verified=distribution_authority,
        team_identifier_verified=True,
        provisioning_profile_verified=True,
        signer_profile_certificate_match=True,
        application_identifier_verified=True,
        application_groups=app_groups,
        increased_memory_limit=increased_memory,
        get_task_allow=get_task_allow,
        privacy_manifest_sha256=privacy_manifest_sha256,
        privacy_manifest_verified=True,
        attribution_manifest_sha256=attribution_manifest_sha256,
        attribution_manifest_verified=True,
    )


def _snapshot(
    app: Path,
    label: str,
    expected: ExpectedIOSIdentity,
    expected_team_id: str,
    *,
    require_app_store_distribution: bool,
) -> BundleSnapshot:
    _run_bytes(["/usr/bin/codesign", "--verify", "--deep", "--strict", "--verbose=2", str(app)])
    info = _read_plist(app / "Info.plist")
    executable_name = info.get("CFBundleExecutable")
    if not isinstance(executable_name, str) or not executable_name:
        raise VerificationError(f"{label} CFBundleExecutable is missing")
    executable = app / executable_name
    if not executable.is_file():
        raise VerificationError(f"{label} main executable is missing")
    signing_leaf_certificate = _trusted_signing_leaf_certificate(app)
    return validate_bundle_contract(
        label=label,
        info=info,
        entitlements=_codesign_entitlements(app),
        profile=_provisioning_profile(app),
        authorities=_signature_authorities(app),
        signing_leaf_certificate=signing_leaf_certificate,
        signing_certificate_trust_verified=True,
        architectures=_architectures(executable),
        macho_uuids=_macho_uuids(executable),
        expected=expected,
        expected_team_id=expected_team_id,
        require_app_store_distribution=require_app_store_distribution,
        executable_sha256=_sha256(executable),
        signature_normalized_executable_sha256=_signature_normalized_executable_digest(executable),
        bundle_sha256=_bundle_digest(app),
        privacy_manifest_sha256=_root_privacy_manifest_digest(app, label),
        attribution_manifest_sha256=_root_attribution_manifest_digest(app, label),
    )


def _single_path(paths: Sequence[Path], description: str) -> Path:
    if len(paths) != 1:
        raise VerificationError(f"expected exactly one {description}; found {len(paths)}")
    return paths[0]


def compare_archive_and_export(archive: BundleSnapshot, exported: BundleSnapshot) -> None:
    archive_identity = (
        archive.bundle_identifier,
        archive.marketing_version,
        archive.build_number,
        archive.architectures,
        archive.macho_uuids,
        archive.signature_normalized_executable_sha256,
        archive.application_groups,
        archive.increased_memory_limit,
        archive.privacy_manifest_sha256,
        archive.attribution_manifest_sha256,
    )
    export_identity = (
        exported.bundle_identifier,
        exported.marketing_version,
        exported.build_number,
        exported.architectures,
        exported.macho_uuids,
        exported.signature_normalized_executable_sha256,
        exported.application_groups,
        exported.increased_memory_limit,
        exported.privacy_manifest_sha256,
        exported.attribution_manifest_sha256,
    )
    if archive_identity != export_identity:
        raise VerificationError("archive and exported IPA identities differ")


def verify(archive: Path, export_dir: Path, expected_team_id: str, output: Path, root: Path = ROOT) -> dict[str, Any]:
    if not re.fullmatch(r"[A-Z0-9]{10}", expected_team_id):
        raise VerificationError("expected team identifier must be a 10-character Apple Team ID")
    archive_app = _single_path(
        sorted((archive / "Products/Applications").glob("*.app")), "archived application bundle"
    )
    ipa = _single_path(sorted(export_dir.glob("*.ipa")), "exported IPA")
    expected = load_expected_identity(root)
    with tempfile.TemporaryDirectory(prefix="vocello-ios-release-verify-") as temp:
        unpacked = Path(temp) / "ipa"
        unpacked.mkdir()
        _run_bytes(["/usr/bin/ditto", "-x", "-k", str(ipa), str(unpacked)])
        exported_app = _single_path(sorted((unpacked / "Payload").glob("*.app")), "exported application bundle")
        archived = _snapshot(
            archive_app,
            "archive",
            expected,
            expected_team_id,
            require_app_store_distribution=False,
        )
        exported = _snapshot(
            exported_app,
            "export",
            expected,
            expected_team_id,
            require_app_store_distribution=True,
        )
        compare_archive_and_export(archived, exported)
    payload: dict[str, Any] = {
        "schemaVersion": SCHEMA_VERSION,
        "verdict": "passed",
        "artifact": {"ipaName": ipa.name, "ipaSHA256": _sha256(ipa)},
        "expectedIdentity": {
            "bundleIdentifier": expected.bundle_identifier,
            "marketingVersion": expected.marketing_version,
            "buildNumber": expected.build_number,
            "architectures": ["arm64"],
            "applicationGroups": list(expected.application_groups),
            "increasedMemoryLimit": expected.increased_memory_limit,
            "privacyManifestSHA256": expected.privacy_manifest_sha256,
            "attributionManifestSHA256": expected.attribution_manifest_sha256,
        },
        "archive": archived.public_dict(),
        "export": exported.public_dict(),
        "archiveExportIdentityMatch": True,
        "privacy": {"containsTeamIdentifier": False, "containsAbsolutePaths": False},
    }
    _atomic_json(output, payload)
    return payload


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--export-dir", type=Path, required=True)
    parser.add_argument("--expected-team-id-env", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--root", type=Path, default=ROOT)
    return parser


def main() -> int:
    arguments = _parser().parse_args()
    expected_team_id = os.environ.get(arguments.expected_team_id_env, "")
    try:
        payload = verify(
            arguments.archive.resolve(),
            arguments.export_dir.resolve(),
            expected_team_id,
            arguments.output.resolve(),
            arguments.root.resolve(),
        )
    except (OSError, KeyError, json.JSONDecodeError, VerificationError) as error:
        raise SystemExit(f"iOS release artifact verification failed: {error}") from error
    print(f"iOS release artifact verification: PASS ({payload['artifact']['ipaName']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
