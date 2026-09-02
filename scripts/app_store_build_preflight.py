#!/usr/bin/env python3
"""Reject an App Store bundle/version/build collision before iOS archiving."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Sequence


ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
import asc_readonly  # noqa: E402


class PreflightError(ValueError):
    pass


def _project_block(text: str, target: str) -> str:
    targets = re.search(r"(?ms)^targets:\n(?P<body>.*)\Z", text)
    if not targets:
        raise PreflightError("missing project targets section")
    match = re.search(
        rf"(?ms)^  {re.escape(target)}:\n(?P<body>.*?)(?=^  [A-Za-z0-9_-]+:\n|\Z)",
        targets.group("body"),
    )
    if not match:
        raise PreflightError(f"missing project target: {target}")
    return match.group("body")


def _setting(text: str, key: str) -> str:
    matches = re.findall(
        rf"(?m)^\s+{re.escape(key)}:\s*(?:\"([^\"]+)\"|'([^']+)'|([^#\n]+))",
        text,
    )
    if not matches:
        raise PreflightError(f"missing project setting: {key}")
    values = [next(value.strip() for value in match if value) for match in matches]
    if len(set(values)) != 1:
        raise PreflightError(f"ambiguous project setting: {key}")
    return values[0]


def project_identity(root: Path = ROOT) -> dict[str, str]:
    text = (root / "project.yml").read_text(encoding="utf-8")
    target = _project_block(text, "VocelloiOS")
    return {
        "bundleIdentifier": _setting(target, "PRODUCT_BUNDLE_IDENTIFIER"),
        "marketingVersion": _setting(text, "MARKETING_VERSION"),
        "buildNumber": _setting(text, "CURRENT_PROJECT_VERSION"),
    }


def _data(payload: Any, label: str) -> list[dict[str, Any]]:
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        raise PreflightError(f"{label} response is not a paginated App Store Connect document")
    if any(not isinstance(row, dict) for row in payload["data"]):
        raise PreflightError(f"{label} response contains malformed rows")
    return payload["data"]


def _default_runner(arguments: Sequence[str], profile: str) -> dict[str, Any]:
    try:
        return asc_readonly.run_json(arguments, profile, 120)
    except asc_readonly.ASCReadError as error:
        raise PreflightError(str(error)) from error


def check(
    *,
    root: Path = ROOT,
    profile: str = "primary",
    runner: Callable[[Sequence[str], str], dict[str, Any]] = _default_runner,
) -> dict[str, Any]:
    identity = project_identity(root)
    apps = _data(
        runner(
            [
                "apps", "list",
                "--bundle-id", identity["bundleIdentifier"],
                "--paginate",
                "--output", "json",
            ],
            profile,
        ),
        "apps",
    )
    exact = [
        app for app in apps
        if isinstance(app.get("attributes"), dict)
        and app["attributes"].get("bundleId") == identity["bundleIdentifier"]
        and isinstance(app.get("id"), str)
        and app["id"]
    ]
    if len(exact) != 1:
        raise PreflightError("bundle identifier must resolve to exactly one App Store Connect app")

    builds = _data(
        runner(
            [
                "builds", "list",
                "--app", exact[0]["id"],
                "--platform", "IOS",
                "--version", identity["marketingVersion"],
                "--build-number", identity["buildNumber"],
                "--processing-state", "all",
                "--paginate",
                "--output", "json",
            ],
            profile,
        ),
        "builds",
    )
    if builds:
        raise PreflightError(
            "App Store Connect already contains this bundle/version/build identity; "
            "update CURRENT_PROJECT_VERSION in project.yml and regenerate the project"
        )

    bundle_digest = hashlib.sha256(identity["bundleIdentifier"].encode("utf-8")).hexdigest()
    return {
        "schemaVersion": 1,
        "status": "PASS",
        "checkedAtUTC": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "platform": "IOS",
        "appIdentityDigest": bundle_digest,
        "marketingVersion": identity["marketingVersion"],
        "buildNumber": identity["buildNumber"],
        "matchedBuildCount": 0,
        "paginationComplete": True,
        "mutationPerformed": False,
    }


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(payload, indent=2, sort_keys=True).encode("utf-8") + b"\n"
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=f".{path.name}.", delete=False) as handle:
        temporary = Path(handle.name)
        handle.write(encoded)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("identity", "check"))
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--profile", default="primary")
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()
    try:
        if arguments.command == "identity":
            payload: dict[str, Any] = project_identity(arguments.root.resolve())
        else:
            if arguments.output is None:
                raise PreflightError("check requires --output")
            payload = check(root=arguments.root.resolve(), profile=arguments.profile)
            _atomic_json(arguments.output.resolve(), payload)
    except (OSError, PreflightError) as error:
        print(f"App Store build preflight: FAIL\n{error}")
        return 1
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
