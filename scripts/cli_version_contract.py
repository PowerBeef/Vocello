#!/usr/bin/env python3
"""Validate that the vocello CLI version is derived only from project.yml."""

from __future__ import annotations

import argparse
from pathlib import Path
import re
import subprocess
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
VERSION_ALIASES = ("--version", "version", "-v")
REQUIRED_CLI_SETTINGS = {
    "GENERATE_INFOPLIST_FILE": "YES",
    "CREATE_INFOPLIST_SECTION_IN_BINARY": "YES",
    "INFOPLIST_KEY_CFBundleShortVersionString": "$(MARKETING_VERSION)",
    "INFOPLIST_KEY_CFBundleVersion": "$(CURRENT_PROJECT_VERSION)",
}


class ContractError(ValueError):
    """Raised when the CLI version identity is incomplete or inconsistent."""


def _manifest_value(text: str, key: str) -> str:
    pattern = re.compile(
        rf"^[ \t]*{re.escape(key)}:[ \t]*[\"']?([^\"'#\s]+)[\"']?[ \t]*(?:#.*)?$",
        re.MULTILINE,
    )
    values = pattern.findall(text)
    if len(values) != 1:
        raise ContractError(f"project.yml must define {key} exactly once (found {len(values)})")
    return values[0]


def _target_body(text: str, target_name: str) -> str:
    header = re.compile(rf"^  {re.escape(target_name)}:[ \t]*$", re.MULTILINE)
    matches = list(header.finditer(text))
    if len(matches) != 1:
        raise ContractError(
            f"project.yml must define target {target_name} exactly once (found {len(matches)})"
        )
    start = matches[0].end()
    next_header = re.search(r"^  [A-Za-z0-9_.-]+:[ \t]*$", text[start:], re.MULTILINE)
    end = start + next_header.start() if next_header else len(text)
    return text[start:end]


def _target_setting(body: str, key: str) -> str:
    pattern = re.compile(
        rf"^[ \t]+{re.escape(key)}:[ \t]*[\"']?([^\"'#\s]+)[\"']?[ \t]*(?:#.*)?$",
        re.MULTILINE,
    )
    values = pattern.findall(body)
    if len(values) != 1:
        raise ContractError(
            f"VocelloCLI must define {key} exactly once (found {len(values)})"
        )
    return values[0]


def validate_source_contract(root: Path) -> str:
    manifest_path = root / "project.yml"
    support_path = root / "Sources" / "VocelloCLI" / "Support.swift"
    try:
        manifest = manifest_path.read_text(encoding="utf-8")
        support = support_path.read_text(encoding="utf-8")
    except FileNotFoundError as error:
        raise ContractError(f"required CLI version input is missing: {error.filename}") from error

    marketing_version = _manifest_value(manifest, "MARKETING_VERSION")
    if re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", marketing_version) is None:
        raise ContractError(
            f"MARKETING_VERSION must be a three-component version (found {marketing_version!r})"
        )
    build_number = _manifest_value(manifest, "CURRENT_PROJECT_VERSION")
    if re.fullmatch(r"[1-9][0-9]*", build_number) is None:
        raise ContractError(
            f"CURRENT_PROJECT_VERSION must be a positive integer (found {build_number!r})"
        )

    cli_target = _target_body(manifest, "VocelloCLI")
    for key, expected in REQUIRED_CLI_SETTINGS.items():
        actual = _target_setting(cli_target, key)
        if actual != expected:
            raise ContractError(
                f"VocelloCLI {key} must be {expected!r} (found {actual!r})"
            )

    definition = re.search(
        r"^let vocelloCLIVersion: String =\n(?P<body>(?:[ \t]+.*\n)+)",
        support,
        re.MULTILINE,
    )
    if definition is None:
        raise ContractError("Support.swift is missing the vocelloCLIVersion definition")
    body = definition.group("body")
    if 'object(forInfoDictionaryKey: "CFBundleShortVersionString")' not in body:
        raise ContractError("vocelloCLIVersion must read CFBundleShortVersionString")
    fallbacks = re.findall(r'\?\?[ \t]*"([^"]+)"', body)
    if fallbacks != ["unknown"]:
        raise ContractError(
            "vocelloCLIVersion must use only the non-numeric fallback \"unknown\" "
            f"(found {fallbacks})"
        )

    return marketing_version


def validate_binary(binary: Path, marketing_version: str) -> None:
    if not binary.is_file():
        raise ContractError(f"vocello binary is missing: {binary}")
    expected = f"vocello {marketing_version}\n"
    for alias in VERSION_ALIASES:
        try:
            completed = subprocess.run(
                [str(binary), alias],
                text=True,
                capture_output=True,
                check=False,
                timeout=15,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise ContractError(f"failed to execute vocello {alias}: {error}") from error
        if completed.returncode != 0:
            raise ContractError(
                f"vocello {alias} exited {completed.returncode}: {completed.stderr.strip()}"
            )
        if completed.stdout != expected:
            raise ContractError(
                f"vocello {alias} output must be {expected.rstrip()!r} "
                f"(found {completed.stdout.rstrip()!r})"
            )
        if completed.stderr:
            raise ContractError(
                f"vocello {alias} must not write to stderr (found {completed.stderr.strip()!r})"
            )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("validate",))
    parser.add_argument("--root", type=Path, default=REPO_ROOT)
    parser.add_argument("--binary", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = args.root.resolve()
    try:
        marketing_version = validate_source_contract(root)
        if args.binary is not None:
            binary = args.binary if args.binary.is_absolute() else root / args.binary
            validate_binary(binary.resolve(), marketing_version)
    except ContractError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    suffix = " + built binary" if args.binary is not None else ""
    print(f"CLI version contract: PASS (vocello {marketing_version}{suffix})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
