#!/usr/bin/env python3
"""Validate iOS App Store installation eligibility against the runtime hardware floor."""

from __future__ import annotations

import argparse
import plistlib
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
INFO_PLIST = Path("Sources/iOS/Info.plist")
POLICY_SOURCE = Path("Sources/iOSSupport/Services/IOSDeviceEligibilityPolicy.swift")
BOOTSTRAP_SOURCE = Path("Sources/iOS/IOSAppBootstrap.swift")
PROJECT = Path("project.yml")
RELEASE_VERIFIER = Path("scripts/verify_ios_release_artifacts.py")
EXPECTED_CAPABILITIES = ("arm64", "iphone-performance-gaming-tier")


class EligibilityError(ValueError):
    pass


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        raise EligibilityError(f"cannot read {path.name}") from error


def validate(root: Path = ROOT) -> dict[str, object]:
    try:
        info = plistlib.loads((root / INFO_PLIST).read_bytes())
    except (OSError, plistlib.InvalidFileException) as error:
        raise EligibilityError("cannot read the iOS Info.plist") from error
    capabilities = info.get("UIRequiredDeviceCapabilities")
    if not isinstance(capabilities, list) or not all(isinstance(item, str) for item in capabilities):
        raise EligibilityError("UIRequiredDeviceCapabilities must be a string array")
    if tuple(sorted(capabilities)) != tuple(sorted(EXPECTED_CAPABILITIES)):
        raise EligibilityError(
            "Info.plist must require exactly arm64 and iphone-performance-gaming-tier"
        )

    policy = _read(root / POLICY_SOURCE)
    for literal in EXPECTED_CAPABILITIES:
        if f'"{literal}"' not in policy:
            raise EligibilityError(f"Swift eligibility policy omits {literal}")
    required_identifiers = ('identifier == "iPhone16,1"', 'identifier == "iPhone16,2"')
    if any(fragment not in policy for fragment in required_identifiers):
        raise EligibilityError("Swift eligibility policy does not admit both iPhone 15 Pro identifiers")
    if '(majorVersion ?? 0) >= 17' not in policy:
        raise EligibilityError("Swift eligibility policy does not admit later iPhone generations")
    if 'minimumHardwareDescription = "iPhone 15 Pro or newer"' not in policy:
        raise EligibilityError("Swift hardware description differs from the governed floor")

    bootstrap = _read(root / BOOTSTRAP_SOURCE)
    if "IOSDeviceEligibilityPolicy.isSupportedMachineIdentifier(machineIdentifier())" not in bootstrap:
        raise EligibilityError("runtime hardware guard does not delegate to the governed policy")
    if "IOSDeviceEligibilityPolicy.minimumHardwareDescription" not in bootstrap:
        raise EligibilityError("unsupported-device copy does not use the governed description")

    project = _read(root / PROJECT)
    source_path = POLICY_SOURCE.as_posix()
    if project.count(source_path) != 2:
        raise EligibilityError(
            "eligibility policy must compile in both host and generic-iOS logic-test targets"
        )

    verifier = _read(root / RELEASE_VERIFIER)
    if "REQUIRED_DEVICE_CAPABILITIES" not in verifier or "UIRequiredDeviceCapabilities" not in verifier:
        raise EligibilityError("release verifier does not enforce archived device capabilities")

    return {
        "schemaVersion": 1,
        "status": "PASS",
        "minimumHardware": "iPhone 15 Pro or newer",
        "requiredCapabilities": list(EXPECTED_CAPABILITIES),
        "runtimeGuard": True,
        "archiveVerification": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("validate",))
    parser.add_argument("--root", type=Path, default=ROOT)
    arguments = parser.parse_args()
    try:
        result = validate(arguments.root.resolve())
    except (OSError, EligibilityError) as error:
        print(f"iOS device eligibility: FAIL\n{error}")
        return 1
    print(
        "iOS device eligibility: PASS "
        f"({', '.join(result['requiredCapabilities'])}; {result['minimumHardware']})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
