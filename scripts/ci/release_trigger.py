#!/usr/bin/env python3
"""Refuse a release run that does not come from the tag's own workflow.

A `workflow_dispatch` run executes the workflow file of the ref it was
dispatched from. Signing secrets must only ever reach the copy of release.yml
recorded in the signed tag, so a dispatched run must be started from
`refs/tags/<tag>` for the same tag it builds (`gh workflow run release.yml
--ref <tag> -f tag=<tag>`). A tag push is its own ref. The optional DMG
basename must match the release-build command template in
config/orchestration-contract.json, which keeps it free of shell syntax
before it reaches any script.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))
from release_source_authority import TAG  # noqa: E402

CONTRACT = SCRIPTS.parent / "config/orchestration-contract.json"
NAMED_BUILD_TEMPLATE = "macos-release-build-named-v1"


class TriggerError(ValueError):
    pass


def output_name_pattern(contract_path: Path = CONTRACT) -> re.Pattern[str]:
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    for template in contract["workflows"]["release-macos-candidate"]["commandTemplates"]["release-build"]:
        if template.get("id") == NAMED_BUILD_TEMPLATE:
            patterns = [part["pattern"] for part in template["argv"] if isinstance(part, dict)]
            if len(patterns) == 1:
                return re.compile(patterns[0])
    raise TriggerError(f"{contract_path.name} has no {NAMED_BUILD_TEMPLATE} output-name pattern")


def validate(event: str, ref: str, tag: str, output_name: str, contract_path: Path = CONTRACT) -> None:
    if event not in ("push", "workflow_dispatch"):
        raise TriggerError(f"release runs only on a tag push or a dispatch, not {event!r}")
    if not TAG.fullmatch(tag):
        raise TriggerError(f"release tag {tag!r} is not a v<major>.<minor>.<patch> tag")
    if ref != f"refs/tags/{tag}":
        raise TriggerError(
            f"release workflow ran from {ref!r}; run it from the tag's own workflow: "
            f"gh workflow run release.yml --ref {tag} -f tag={tag}"
        )
    if output_name and not output_name_pattern(contract_path).fullmatch(output_name):
        raise TriggerError("output_name must match the release-build contract pattern")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Refuse a release run that does not come from the tag's own workflow.")
    parser.add_argument("--event", required=True)
    parser.add_argument("--ref", required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--output-name", default="")
    args = parser.parse_args(argv)
    try:
        validate(args.event, args.ref, args.tag, args.output_name)
    except (TriggerError, KeyError, json.JSONDecodeError) as error:
        print(f"release-trigger: {error}", file=sys.stderr)
        return 1
    print(f"release-trigger: {args.event} from {args.ref} may build {args.tag}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
