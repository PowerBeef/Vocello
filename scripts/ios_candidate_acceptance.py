#!/usr/bin/env python3
"""Fail-closed preinstalled-candidate helpers for scripts/ui_test.sh, not a UI driver."""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
from pathlib import Path
import plistlib
import subprocess

import release_evidence
import ios_startup_reliability
from lib import jsonio  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
BUNDLE_ID = "com.patricedery.vocello"
TARGET = "VocelloiOSCandidateUITests"
RUNNER_ID = BUNDLE_ID + ".candidateuitests.xctrunner"
TEST = TARGET + "/VocelloiOSCandidateAcceptanceUITests/testPreinstalledCandidateNavigation"


def snapshot_crashes(device: str, destination: Path) -> None:
    """Use system reports, never distribution-app private container access."""
    destination.mkdir(parents=True, exist_ok=False)
    raw = destination / "raw"
    raw.mkdir()
    with (destination / "collection.log").open("wb") as log:
        subprocess.run(["xcrun", "devicectl", "device", "copy", "from", "--device", device,
                        "--domain-type", "systemCrashLogs", "--source", ".",
                        "--destination", str(raw), "--timeout", "60", "--quiet"],
                       stdout=log, stderr=log, check=True, timeout=75)
    hashes = sorted({digest(path) for path in raw.rglob("*") if path.is_file()})
    release_evidence.atomic_write(destination / "hashes.json", json.dumps(hashes).encode())


def crash_delta(before: Path, after: Path, output: Path) -> dict:
    old = set(json.loads((before / "hashes.json").read_text()))
    current = {digest(path): path for path in (after / "raw").rglob("*") if path.is_file()}
    if set(current) != set(json.loads((after / "hashes.json").read_text())):
        raise ValueError("crash snapshot drift")
    delta = output.parent / "new-system-reports"
    delta.mkdir(exist_ok=False)
    for sha in current.keys() - old:
        release_evidence.atomic_write(delta / f"{sha}.ips", current[sha].read_bytes())
    summary = ios_startup_reliability.sanitize_system_crashes(
        delta, output.parent / "candidate-crash-summary.json", {"Vocello", BUNDLE_ID, RUNNER_ID, TARGET + "-Runner"})
    return {"schemaVersion": 1, "newReportCount": len(current.keys() - old),
            "newReportSHA256": sorted(current.keys() - old), "sanitized": summary,
            # Unclassified system reports are not silently counted as a clean run.
            "status": "passed" if not current.keys() - old else "requires-review"}


digest = jsonio.sha256_file


def read_json(path: Path) -> dict:
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise ValueError("expected an object")
    return value


def candidate_identity(directory: Path, root: Path = ROOT) -> dict:
    # Reuse the complete command-bound artifact validator. A hand-authored PASS
    # or a build number alone is never permission to qualify a candidate.
    evidence = release_evidence.validate(directory)
    release = evidence["release"]
    if release["platform"] != "ios":
        raise ValueError("candidate evidence is not iOS")
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    dirty = subprocess.check_output(["git", "status", "--porcelain"], cwd=root, text=True).strip()
    if commit != release["commitSHA"] or dirty:
        raise ValueError("candidate tests require the exact clean source commit")
    verified = read_json(directory / release_evidence.IOS_ARTIFACT_VERIFICATION_NAME)
    expected = verified["expectedIdentity"]
    if expected["bundleIdentifier"] != BUNDLE_ID:
        raise ValueError("unexpected candidate bundle identifier")
    return {
        "schemaVersion": 1, "evidenceClass": "preinstalled-candidate-black-box",
        "sourceCommit": commit, "tag": release["tag"], "bundleIdentifier": BUNDLE_ID,
        "marketingVersion": expected["marketingVersion"], "buildNumber": expected["buildNumber"],
        "releaseEvidenceSHA256": digest(directory / release_evidence.EVIDENCE_NAME),
        "artifactVerificationSHA256": digest(directory / release_evidence.IOS_ARTIFACT_VERIFICATION_NAME),
        "ipaSHA256": verified["artifact"]["ipaSHA256"],
        "bindingMethod": "unique-version-build-and-non-development-origin",
        "installedBinaryDigestObserved": False,
    }


def installed_identity(apps: dict, expected: dict) -> dict:
    rows = apps.get("result", {}).get("apps")
    if not isinstance(rows, list):
        raise ValueError("CoreDevice application inventory is missing")
    matches = [row for row in rows if isinstance(row, dict) and row.get("bundleIdentifier") == BUNDLE_ID]
    if len(matches) != 1:
        raise ValueError("candidate application is missing or ambiguous")
    app = matches[0]
    if app.get("isBuiltByDeveloper") is not False:
        raise ValueError("development installation or unknown application origin is prohibited")
    if (app.get("version") != expected["marketingVersion"]
            or app.get("bundleVersion") != expected["buildNumber"]):
        raise ValueError("installed candidate version/build differs from approved evidence")
    return {"bundleIdentifier": BUNDLE_ID, "marketingVersion": app["version"],
            "buildNumber": app["bundleVersion"], "isBuiltByDeveloper": False}


def validate_results(summary: dict, attachments: Path, identity: dict) -> dict:
    tests = summary.get("tests")
    if (not isinstance(tests, list) or len(tests) != 1 or not isinstance(tests[0], dict)
            or tests[0].get("test") != TEST.rsplit("/", 1)[1]
            or tests[0].get("verdict") != "passed"):
        raise ValueError("candidate navigation must execute and pass exactly once")
    matched = []
    for path in attachments.rglob("*"):
        if not path.is_file() or path.stat().st_size > 65536:
            continue
        try:
            if json.loads(path.read_bytes()) == identity:
                matched.append(digest(path))
        except (ValueError, UnicodeError):
            continue
    if not matched:
        raise ValueError("candidate runner identity attachment was not collected")
    return {"schemaVersion": 1, "evidenceClass": "preinstalled-candidate-black-box",
            "scope": "navigation-route-proof-only", "status": "passed",
            "testCount": 1, "identityAttachmentSHA256": sorted(set(matched))}


def runner_configuration(payload: dict, runner_info: dict, identity: dict) -> dict:
    """Xcode's documented UseDestinationArtifacts prohibits installation during test."""
    if set(payload) != {TARGET, "__xctestrun_metadata__"}:
        raise ValueError("candidate xctestrun must contain only the standalone candidate runner")
    version = payload["__xctestrun_metadata__"].get("FormatVersion")
    if type(version) is not int or version != 1:
        raise ValueError("unsupported xctestrun version requires an explicit migration")
    if runner_info.get("CFBundleIdentifier") != RUNNER_ID:
        raise ValueError("refusing to install any bundle other than the candidate test runner")
    target = dict(payload[TARGET])
    if target.get("IsUITestBundle") is not True:
        raise ValueError("candidate runner must be a UI test bundle")
    # Any target app build dependency indicates the wrong scheme was used.
    if target.get("UITargetAppPath") or target.get("UITargetAppBundleIdentifier"):
        raise ValueError("candidate runner must be built without a target application")
    for path in target.get("DependentProductPaths", []):
        if f"{TARGET}-Runner.app" not in path:
            raise ValueError("candidate build contains a non-runner product dependency")
    for field in ("TestHostPath", "TestBundlePath", "UITargetAppPath", "DependentProductPaths"):
        target.pop(field, None)
    target.update({
        "UseDestinationArtifacts": True,
        "TestHostBundleIdentifier": RUNNER_ID,
        "TestBundleDestinationRelativePath": f"__TESTHOST__/PlugIns/{TARGET}.xctest",
        "UITargetAppBundleIdentifier": BUNDLE_ID,
        "OnlyTestIdentifiers": [TEST.split("/", 1)[1]],
        "CommandLineArguments": [], "UITargetAppCommandLineArguments": [],
        "UITargetAppEnvironmentVariables": {},
        "EnvironmentVariables": {"VOCELLO_CANDIDATE_IDENTITY": base64.b64encode(
            json.dumps(identity, sort_keys=True).encode()).decode()},
        "TestingEnvironmentVariables": {
            "DYLD_FRAMEWORK_PATH": "__TESTHOST__/Frameworks",
            "DYLD_LIBRARY_PATH": "__TESTHOST__/Frameworks",
        },
    })
    # Repetition/retry settings must not survive a modified build scheme.
    for field in ("TestIterations", "RetryTestsOnFailure", "RunTestsUntilFailure", "MaximumTestRepetitions"):
        target.pop(field, None)
    return {TARGET: target, "__xctestrun_metadata__": payload["__xctestrun_metadata__"]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    identity = sub.add_parser("identity")
    identity.add_argument("--evidence", required=True, type=Path)
    identity.add_argument("--output", required=True, type=Path)
    installed = sub.add_parser("installed")
    installed.add_argument("--apps", required=True, type=Path)
    installed.add_argument("--identity", required=True, type=Path)
    installed.add_argument("--output", required=True, type=Path)
    prepare = sub.add_parser("prepare-runner")
    prepare.add_argument("--xctestrun", required=True, type=Path)
    prepare.add_argument("--runner", required=True, type=Path)
    prepare.add_argument("--identity", required=True, type=Path)
    prepare.add_argument("--output", required=True, type=Path)
    snapshot = sub.add_parser("snapshot-crashes")
    snapshot.add_argument("--device", required=True)
    snapshot.add_argument("--output", required=True, type=Path)
    delta = sub.add_parser("crash-delta")
    delta.add_argument("--before", required=True, type=Path)
    delta.add_argument("--after", required=True, type=Path)
    delta.add_argument("--output", required=True, type=Path)
    results = sub.add_parser("validate-results")
    results.add_argument("--summary", required=True, type=Path)
    results.add_argument("--attachments", required=True, type=Path)
    results.add_argument("--identity", required=True, type=Path)
    results.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        if args.output.exists():
            raise ValueError("refusing to overwrite retained candidate evidence")
        if args.command == "snapshot-crashes":
            snapshot_crashes(args.device, args.output)
            return 0
        if args.command == "validate-results":
            value = validate_results(read_json(args.summary), args.attachments, read_json(args.identity))
        elif args.command == "crash-delta":
            value = crash_delta(args.before, args.after, args.output)
        elif args.command == "identity":
            value = candidate_identity(args.evidence.resolve())
        elif args.command == "installed":
            value = installed_identity(read_json(args.apps), read_json(args.identity))
        else:
            value = runner_configuration(plistlib.loads(args.xctestrun.read_bytes()),
                                         plistlib.loads((args.runner / "Info.plist").read_bytes()),
                                         read_json(args.identity))
            release_evidence.atomic_write(args.output, plistlib.dumps(value))
            print("Candidate runner: destination artifacts only; target installation disabled")
            return 0
        release_evidence.atomic_write(args.output, (json.dumps(value, indent=2, sort_keys=True) + "\n").encode())
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        # Account/device payloads and filesystem paths are never echoed.
        print(f"Candidate acceptance refused ({type(error).__name__}); inspect untracked inputs.")
        return 1
    if value.get("status") == "requires-review":
        print("New system crash reports require review; not a clean candidate run.")
        return 1
    print("Candidate check: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
