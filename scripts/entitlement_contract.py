#!/usr/bin/env python3
"""Fail-closed source and signed-bundle entitlement allowlist for Vocello."""

from __future__ import annotations

import argparse
import json
import plistlib
import re
import subprocess
import sys
from datetime import date
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
POLICY_PATH = Path("config/macos-entitlement-policy.json")
LOCK_PATH = Path("QwenVoice.xcodeproj/project.xcworkspace/xcshareddata/swiftpm/Package.resolved")
SAFE_ID = re.compile(r"^[a-z0-9-]+$")


class EntitlementError(ValueError):
    pass


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise EntitlementError(f"{path}: {error}") from error
    if not isinstance(value, dict):
        raise EntitlementError(f"{path}: expected an object")
    return value


def _safe_relative(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value or value.startswith("/") or ".." in Path(value).parts:
        raise EntitlementError(f"{field} must be a safe repository-relative path")
    return value


def _plist(path: Path) -> dict[str, Any]:
    try:
        value = plistlib.loads(path.read_bytes())
    except (OSError, plistlib.InvalidFileException) as error:
        raise EntitlementError(f"{path}: invalid entitlement plist: {error}") from error
    if not isinstance(value, dict):
        raise EntitlementError(f"{path}: entitlement plist must be a dictionary")
    return value


def _target_blocks(project: str) -> dict[str, str]:
    marker = re.search(r"(?m)^targets:\s*$", project)
    if not marker:
        raise EntitlementError("project.yml is missing targets")
    text = project[marker.end():]
    matches = list(re.finditer(r"(?m)^  ([A-Za-z0-9_.-]+):\s*$", text))
    return {
        match.group(1): text[match.start():(matches[index + 1].start() if index + 1 < len(matches) else len(text))]
        for index, match in enumerate(matches)
    }


def _declared_entitlements(project: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for target, block in _target_blocks(project).items():
        if not re.search(r"(?m)^\s+platform:\s*macOS\s*$", block):
            continue
        matches = re.findall(r"(?m)^\s+CODE_SIGN_ENTITLEMENTS:\s*([^#\n]+?)\s*$", block)
        if len(matches) > 1:
            raise EntitlementError(f"project.yml target {target} declares multiple entitlement files")
        if matches:
            result[target] = matches[0].strip().strip("'\"")
    return result


def _resolved_versions(root: Path) -> dict[str, str]:
    lock = _read_json(root / LOCK_PATH)
    pins = lock.get("pins")
    if lock.get("version") not in (2, 3) or not isinstance(pins, list):
        raise EntitlementError(f"{LOCK_PATH}: unsupported Package.resolved schema")
    result: dict[str, str] = {}
    for pin in pins:
        if not isinstance(pin, dict) or not isinstance(pin.get("identity"), str):
            raise EntitlementError(f"{LOCK_PATH}: invalid pin")
        state = pin.get("state")
        if not isinstance(state, dict) or not isinstance(state.get("version"), str):
            raise EntitlementError(f"{LOCK_PATH}: {pin['identity']} lacks an exact version")
        result[pin["identity"]] = state["version"]
    return result


def _strip_swift_comments(source: str) -> str:
    source = re.sub(r"/\*.*?\*/", " ", source, flags=re.DOTALL)
    return re.sub(r"//[^\n]*", "", source)


def _dynamic_loading_sites(root: Path, policy: dict[str, Any]) -> list[str]:
    patterns = {
        "dlopen": re.compile(r"\bdlopen\s*\("),
        "NSCreateObjectFileImageFromFile": re.compile(r"\bNSCreateObjectFileImageFromFile\s*\("),
        "CFBundleLoadExecutable": re.compile(r"\bCFBundleLoadExecutable\s*\("),
        "NSBundle.load": re.compile(r"\bNSBundle(?:\.[A-Za-z_][A-Za-z0-9_]*)*\.load\s*\("),
    }
    configured = policy.get("forbiddenDynamicLoadingAPIs")
    if not isinstance(configured, list) or set(configured) != set(patterns):
        raise EntitlementError("forbiddenDynamicLoadingAPIs must contain the complete loading API set")
    roots = policy.get("scannedSourceRoots")
    if not isinstance(roots, list) or not roots:
        raise EntitlementError("scannedSourceRoots must be non-empty")
    sites: list[str] = []
    for raw_root in roots:
        relative = _safe_relative(raw_root, "scannedSourceRoots")
        source_root = root / relative
        if not source_root.is_dir():
            raise EntitlementError(f"scanned source root is missing: {relative}")
        for path in sorted(source_root.rglob("*.swift")):
            source = _strip_swift_comments(path.read_text(encoding="utf-8"))
            for name, pattern in patterns.items():
                for match in pattern.finditer(source):
                    line = source.count("\n", 0, match.start()) + 1
                    sites.append(f"{path.relative_to(root).as_posix()}:{line}:{name}")
    return sites


def validate(root: Path = ROOT, policy_relative: Path = POLICY_PATH) -> list[str]:
    errors: list[str] = []
    try:
        policy = _read_json(root / policy_relative)
        if policy.get("schemaVersion") != 1:
            errors.append("macOS entitlement policy has an unsupported schemaVersion")
        targets = policy.get("targets")
        if not isinstance(targets, list) or len(targets) != 3:
            raise EntitlementError("macOS entitlement policy must define app, XPC, and framework roles")
        by_id: dict[str, dict[str, Any]] = {}
        for row in targets:
            if not isinstance(row, dict) or not isinstance(row.get("id"), str) or not SAFE_ID.fullmatch(row["id"]):
                raise EntitlementError("macOS entitlement policy target has an invalid id")
            if row["id"] in by_id or not isinstance(row.get("allowed"), dict):
                raise EntitlementError("macOS entitlement policy target is duplicate or lacks an allowlist")
            by_id[row["id"]] = row
        if set(by_id) != {"macos-app", "macos-engine-xpc", "macos-framework"}:
            errors.append("macOS entitlement policy target roles are incomplete")

        project = (root / "project.yml").read_text(encoding="utf-8")
        declared = _declared_entitlements(project)
        expected_declared: dict[str, str] = {}
        for role in ("macos-app", "macos-engine-xpc"):
            row = by_id.get(role)
            if not row:
                continue
            target = row.get("projectTarget")
            source = _safe_relative(row.get("source"), f"targets.{role}.source")
            if not isinstance(target, str) or not target:
                errors.append(f"{role} must name a project target")
                continue
            expected_declared[target] = source
            actual = _plist(root / source)
            if actual != row["allowed"]:
                errors.append(f"{source} differs from the exact {role} entitlement allowlist")
        framework = by_id.get("macos-framework", {})
        if framework.get("projectTarget") is not None or framework.get("source") is not None or framework.get("allowed") != {}:
            errors.append("macos-framework must have an empty entitlement allowlist and no source plist")
        if declared != expected_declared:
            errors.append(
                "project.yml macOS entitlement routing differs from policy: "
                f"expected {expected_declared}, observed {declared}"
            )

        release = (root / "scripts/release.sh").read_text(encoding="utf-8")
        xpc_loop_match = re.search(
            r"while IFS= read -r -d '' xpc_path; do(.*?)done < <\(find \"\$APP_PATH/Contents/XPCServices\"",
            release,
            re.DOTALL,
        )
        xpc_source = by_id.get("macos-engine-xpc", {}).get("source")
        app_source = by_id.get("macos-app", {}).get("source")
        if not xpc_loop_match or f'--entitlements "$PROJECT_DIR/{xpc_source}"' not in xpc_loop_match.group(1):
            errors.append("release XPC signing does not use the XPC entitlement allowlist")
        if f'--entitlements "$PROJECT_DIR/{app_source}"' not in release:
            errors.append("release app signing does not use the app entitlement allowlist")

        verifier = (root / "scripts/verify_release_bundle.sh").read_text(encoding="utf-8")
        for role in ("macos-app", "macos-engine-xpc", "macos-framework"):
            if f"verify-bundle --role {role}" not in verifier:
                errors.append(f"packaged release verifier does not enforce {role} entitlements")

        review = policy.get("mlxExceptionReview")
        if not isinstance(review, dict):
            raise EntitlementError("mlxExceptionReview is missing")
        try:
            date.fromisoformat(review.get("reviewedAt", ""))
        except ValueError:
            errors.append("mlxExceptionReview.reviewedAt must be an ISO date")
        reviewed_pins = review.get("reviewedPins")
        resolved = _resolved_versions(root)
        expected_pins = {identity: resolved.get(identity) for identity in ("mlx-swift", "mlx-swift-lm")}
        if reviewed_pins != expected_pins:
            errors.append("MLX entitlement exception review is stale for the resolved MLX pins")
        exceptions = review.get("exceptionEntitlements")
        expected_exceptions = {
            "com.apple.security.cs.allow-unsigned-executable-memory",
            "com.apple.security.cs.disable-library-validation",
        }
        if not isinstance(exceptions, list) or set(exceptions) != expected_exceptions:
            errors.append("MLX entitlement exception review must cover both hardened-runtime exceptions")
        for field in ("conclusion", "removalCondition"):
            if not isinstance(review.get(field), str) or len(review[field].strip()) < 24:
                errors.append(f"mlxExceptionReview.{field} must record a substantive decision")

        for site in _dynamic_loading_sites(root, policy):
            errors.append(f"owned source may not load arbitrary executable code: {site}")
    except (OSError, EntitlementError) as error:
        errors.append(str(error))
    return errors


def _signed_entitlements(bundle: Path) -> dict[str, Any]:
    try:
        output = subprocess.check_output(
            ["codesign", "--display", "--entitlements", ":-", str(bundle)],
            stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.CalledProcessError) as error:
        raise EntitlementError(f"could not read signed entitlements for {bundle.name}: {error}") from error
    if not output.strip():
        return {}
    try:
        value = plistlib.loads(output)
    except plistlib.InvalidFileException as error:
        raise EntitlementError(f"signed entitlements for {bundle.name} are not a plist") from error
    if not isinstance(value, dict):
        raise EntitlementError(f"signed entitlements for {bundle.name} are not a dictionary")
    return value


def verify_bundle(root: Path, role: str, bundle: Path) -> None:
    policy = _read_json(root / POLICY_PATH)
    rows = policy.get("targets")
    row = next((item for item in rows if isinstance(item, dict) and item.get("id") == role), None) if isinstance(rows, list) else None
    if not row or not isinstance(row.get("allowed"), dict):
        raise EntitlementError(f"unknown entitlement role: {role}")
    actual = _signed_entitlements(bundle)
    if actual != row["allowed"]:
        added = sorted(set(actual) - set(row["allowed"]))
        missing = sorted(set(row["allowed"]) - set(actual))
        changed = sorted(key for key in set(actual) & set(row["allowed"]) if actual[key] != row["allowed"][key])
        raise EntitlementError(
            f"{bundle.name} signed entitlements differ for {role}; added={added}, missing={missing}, changed={changed}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("validate")
    bundle_parser = subparsers.add_parser("verify-bundle")
    bundle_parser.add_argument("--role", required=True)
    bundle_parser.add_argument("--bundle", type=Path, required=True)
    args = parser.parse_args()
    root = args.root.resolve()
    if args.command == "validate":
        errors = validate(root)
        if errors:
            for error in errors:
                print(f"error: {error}")
            return 1
        print("macOS entitlement contract: PASS")
        return 0
    try:
        verify_bundle(root, args.role, args.bundle.resolve())
    except EntitlementError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    print(f"signed entitlement contract: PASS ({args.role})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
