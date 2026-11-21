#!/usr/bin/env python3
"""Read-only Xcode iOS platform-component readiness preflight.

The generic physical-device destination does not execute a Simulator, but
current Xcode releases still require a compatible installed iOS runtime
component before that destination becomes eligible. This helper inspects the
public Xcode inventories only; it never downloads, installs, boots, creates, or
deletes a runtime.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence


SDK_COMMAND = ("xcodebuild", "-showsdks", "-json")
RUNTIME_COMMAND = ("xcrun", "simctl", "list", "runtimes", "-j")
REPAIR_COMMAND = "xcodebuild -downloadPlatform iOS -architectureVariant arm64"


class PreflightError(RuntimeError):
    """A privacy-safe, classified platform-readiness failure."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class IOSSDK:
    canonical_name: str
    display_name: str
    version: str
    build: str | None


@dataclass(frozen=True)
class RuntimeComponent:
    identifier: str
    version: str | None
    build: str | None
    available: bool


@dataclass(frozen=True)
class PreflightResult:
    sdk: IOSSDK
    runtime: RuntimeComponent

    def payload(self) -> dict[str, Any]:
        return {
            "schemaVersion": 1,
            "status": "ready",
            "sdk": {
                "canonicalName": self.sdk.canonical_name,
                "displayName": self.sdk.display_name,
                "version": self.sdk.version,
                "build": self.sdk.build,
            },
            "runtime": {
                "identifier": self.runtime.identifier,
                "version": self.runtime.version,
                "build": self.runtime.build,
            },
            "destination": "generic/platform=iOS",
            "simulatorExecutionAuthorized": False,
        }


def _read_json(path: Path, label: str) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except OSError as error:
        raise PreflightError("inspectionFailed", f"could not read {label} fixture") from error
    except json.JSONDecodeError as error:
        raise PreflightError("inspectionFailed", f"{label} inventory is not valid JSON") from error


def _run_json(command: Sequence[str], label: str) -> Any:
    try:
        completed = subprocess.run(
            list(command),
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError as error:
        raise PreflightError("inspectionFailed", f"could not run {label} inspection") from error
    if completed.returncode != 0:
        code = "runtimeRegistryUnavailable" if label == "Xcode runtime" else "inspectionFailed"
        message = (
            "Xcode runtime inventory could not be queried; the runtime service is unavailable"
            if label == "Xcode runtime"
            else f"{label} inventory could not be queried"
        )
        raise PreflightError(
            code,
            message,
        )
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise PreflightError("inspectionFailed", f"{label} inventory is not valid JSON") from error


def _version_pair(value: str | None) -> tuple[int, int] | None:
    if not value:
        return None
    match = re.match(r"^\s*(\d+)\.(\d+)", value)
    if match is None:
        return None
    return int(match.group(1)), int(match.group(2))


def _ios_sdk(payload: Any) -> IOSSDK:
    if not isinstance(payload, list):
        raise PreflightError("inspectionFailed", "Xcode SDK inventory has an unexpected shape")
    candidates = [
        item
        for item in payload
        if isinstance(item, dict)
        and item.get("platform") == "iphoneos"
        and item.get("isBaseSdk") is True
    ]
    if not candidates:
        raise PreflightError(
            "missingIOSSDK",
            "the selected Xcode installation does not expose a base iPhoneOS SDK",
        )

    def sort_key(item: dict[str, Any]) -> tuple[int, int, str]:
        version = _version_pair(str(item.get("platformVersion") or item.get("sdkVersion") or ""))
        major, minor = version or (-1, -1)
        return (major, minor, str(item.get("canonicalName") or ""))

    item = max(candidates, key=sort_key)
    version = str(item.get("platformVersion") or item.get("sdkVersion") or "").strip()
    canonical_name = str(item.get("canonicalName") or "iphoneos").strip()
    display_name = str(item.get("displayName") or f"iOS {version}").strip()
    build_value = str(item.get("productBuildVersion") or "").strip() or None
    if _version_pair(version) is None:
        raise PreflightError("inspectionFailed", "the base iPhoneOS SDK has no usable version")
    return IOSSDK(canonical_name, display_name, version, build_value)


def _runtime_entries(payload: Any) -> Iterable[dict[str, Any]]:
    if not isinstance(payload, dict) or not isinstance(payload.get("runtimes"), list):
        raise PreflightError("inspectionFailed", "Xcode runtime inventory has an unexpected shape")
    for item in payload["runtimes"]:
        if isinstance(item, dict):
            yield item


def _runtime_component(item: dict[str, Any]) -> RuntimeComponent | None:
    identifier = str(item.get("identifier") or item.get("runtimeIdentifier") or "").strip()
    name = str(item.get("name") or item.get("displayName") or "").strip()
    platform = str(item.get("platform") or item.get("platformIdentifier") or "").strip()
    ios_identity = (
        identifier.startswith("com.apple.CoreSimulator.SimRuntime.iOS-")
        or platform in {"iOS", "com.apple.platform.iphonesimulator"}
        or name.startswith("iOS ")
    )
    if not ios_identity:
        return None
    version = str(item.get("version") or item.get("platformVersion") or "").strip() or None
    build = str(
        item.get("buildversion")
        or item.get("buildVersion")
        or item.get("productBuildVersion")
        or ""
    ).strip() or None
    return RuntimeComponent(
        identifier=identifier or name or "iOS runtime",
        version=version,
        build=build,
        available=item.get("isAvailable") is True,
    )


def _runtime_matches_sdk(sdk: IOSSDK, runtime: RuntimeComponent) -> bool:
    """Return whether Xcode can pair the runtime component with the SDK.

    Runtime version is the authoritative compatibility field when present.
    Xcode's downloader can install a compatible patch build whose product
    build differs from the SDK build. Build identity is therefore only a
    fail-closed fallback for older inventory shapes that omit a usable runtime
    version.
    """
    runtime_pair = _version_pair(runtime.version)
    if runtime_pair is not None:
        return runtime_pair == _version_pair(sdk.version)
    return bool(sdk.build and runtime.build and sdk.build == runtime.build)


def evaluate(sdk_payload: Any, runtime_payload: Any) -> PreflightResult:
    sdk = _ios_sdk(sdk_payload)
    runtimes = [
        runtime
        for item in _runtime_entries(runtime_payload)
        if (runtime := _runtime_component(item)) is not None
    ]
    for runtime in runtimes:
        if not runtime.available:
            continue
        # Xcode's platform downloader can legitimately install a compatible
        # runtime patch build whose product build differs from the SDK build.
        # Xcode 26.6, for example, ships iphoneos26.5 build 23F81a while its
        # own `-downloadPlatform iOS` command installs iOS 26.5 build 23F77;
        # `xcodebuild -showdestinations` accepts both the generic iOS
        # destination and a paired physical phone with that combination.
        if _runtime_matches_sdk(sdk, runtime):
            return PreflightResult(sdk, runtime)

    unavailable_match = any(
        not runtime.available
        and _runtime_matches_sdk(sdk, runtime)
        for runtime in runtimes
    )
    detail = "a matching runtime is installed but unavailable" if unavailable_match else "no matching available runtime is installed"
    raise PreflightError(
        "missingPlatformComponent",
        f"Xcode lists {sdk.canonical_name}, but {detail}",
    )


def _failure_payload(error: PreflightError) -> dict[str, Any]:
    return {
        "schemaVersion": 1,
        "status": "blocked-toolchain-component",
        "code": error.code,
        "message": str(error),
        "destination": "generic/platform=iOS",
        "simulatorExecutionAuthorized": False,
    }


def _print_failure(error: PreflightError, as_json: bool) -> None:
    if as_json:
        print(json.dumps(_failure_payload(error), indent=2, sort_keys=True))
        return
    print(f"error: {error}", file=sys.stderr)
    if error.code == "missingPlatformComponent":
        print(
            "error: generic/platform=iOS and physical iOS destinations are ineligible until "
            "matching Xcode iOS Platform Support is restored",
            file=sys.stderr,
        )
    if error.code in {"missingPlatformComponent", "missingIOSSDK"}:
        print("repair: install or enable the matching iOS component in Xcode > Settings > Components", file=sys.stderr)
        print(f"repair (explicit alternative): {REPAIR_COMMAND}", file=sys.stderr)
    elif error.code == "runtimeRegistryUnavailable":
        print(
            "repair: restore Xcode runtime-service health, then rerun this check; if no matching "
            "runtime is listed, use Xcode > Settings > Components",
            file=sys.stderr,
        )
    print(
        "note: this read-only preflight installs nothing and does not authorize Simulator "
        "builds, launches, or tests",
        file=sys.stderr,
    )


def command_check(args: argparse.Namespace) -> int:
    try:
        sdk_payload = _read_json(args.sdk_json, "Xcode SDK") if args.sdk_json else _run_json(SDK_COMMAND, "Xcode SDK")
        runtime_payload = (
            _read_json(args.runtime_json, "Xcode runtime")
            if args.runtime_json
            else _run_json(RUNTIME_COMMAND, "Xcode runtime")
        )
        result = evaluate(sdk_payload, runtime_payload)
    except PreflightError as error:
        _print_failure(error, args.json)
        return 1

    if args.json:
        print(json.dumps(result.payload(), indent=2, sort_keys=True))
    else:
        print(
            f"==> Xcode iOS platform ready: {result.sdk.canonical_name} / "
            f"{result.runtime.identifier}"
        )
    return 0


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    subparsers = result.add_subparsers(dest="command", required=True)
    check = subparsers.add_parser("check", help="verify matching installed iOS Platform Support")
    check.add_argument("--sdk-json", type=Path, help=argparse.SUPPRESS)
    check.add_argument("--runtime-json", type=Path, help=argparse.SUPPRESS)
    check.add_argument("--json", action="store_true", help="emit a machine-readable verdict")
    check.set_defaults(handler=command_check)
    return result


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    return int(args.handler(args))


if __name__ == "__main__":
    raise SystemExit(main())
