#!/usr/bin/env python3
"""Validate Vocello's public support contact across source-owned surfaces."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[1]
PLACEHOLDERS = ("example.com", "your-email", "todo", "tbd", "placeholder")


def _load_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"cannot read {path.name}: {error}") from error
    if not isinstance(value, dict):
        raise ValueError(f"{path.name} must contain a JSON object")
    return value


def _required_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    text = value.strip()
    if any(marker in text.lower() for marker in PLACEHOLDERS):
        raise ValueError(f"{field} contains a placeholder")
    return text


def _https_url(value: object, field: str) -> str:
    text = _required_text(value, field)
    parsed = urlparse(text)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
        raise ValueError(f"{field} must be a public HTTPS URL without credentials")
    return text


def validate(root: Path) -> list[str]:
    errors: list[str] = []
    config_path = root / "config/support-contact.json"
    try:
        config = _load_json(config_path)
        if config.get("schemaVersion") != 1:
            raise ValueError("schemaVersion must be 1")
        product = _required_text(config.get("product"), "product")
        email = _required_text(config.get("supportEmail"), "supportEmail")
        if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
            raise ValueError("supportEmail is not a valid email address")
        owner = _required_text(config.get("responseOwner"), "responseOwner")
        support_url = _https_url(config.get("supportURL"), "supportURL")
        privacy_url = _https_url(config.get("privacyURL"), "privacyURL")
        discussion_url = _https_url(config.get("publicDiscussionURL"), "publicDiscussionURL")
        security_url = _https_url(config.get("securityReportURL"), "securityReportURL")
    except ValueError as error:
        return [str(error)]

    required_files = {
        "support page": root / "website/public/support/index.html",
        "privacy page": root / "website/public/privacy/index.html",
        "website footer": root / "website/src/sections/Footer.jsx",
        "iOS Settings": root / "Sources/iOS/Settings/SettingsScreen.swift",
    }
    texts: dict[str, str] = {}
    for label, path in required_files.items():
        try:
            texts[label] = path.read_text(encoding="utf-8")
        except OSError as error:
            errors.append(f"missing {label}: {error}")
    if errors:
        return errors

    support = texts["support page"]
    for needle, label in (
        (product, "product name"),
        (f"mailto:{email}", "support mailto"),
        (owner, "response owner"),
        (privacy_url, "privacy URL"),
        (discussion_url, "discussion URL"),
        (security_url, "security-report URL"),
    ):
        if needle not in support:
            errors.append(f"support page is missing configured {label}")
    if re.search(r"(?:respond|reply|response)\s+(?:in|within)\s+\d", support, re.IGNORECASE):
        errors.append("support page promises an ungoverned response SLA")

    privacy = texts["privacy page"]
    if f"mailto:{email}" not in privacy or support_url not in privacy:
        errors.append("privacy page must expose the configured email and support URL")

    footer = texts["website footer"]
    if '/support/' not in footer:
        errors.append("website footer must link to /support/")

    settings = texts["iOS Settings"]
    if support_url not in settings:
        errors.append("iOS Settings support row must use the configured support URL")
    if '"iosSettings_supportRow"' not in settings:
        errors.append("iOS Settings is missing iosSettings_supportRow")

    return sorted(set(errors))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("validate",))
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    errors = validate(args.root.resolve())
    if errors:
        for error in errors:
            print(f"error: {error}", file=sys.stderr)
        return 1
    print("Support contact contract: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
