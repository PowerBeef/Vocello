#!/usr/bin/env python3
"""Fail-closed release-notes quality gate.

The GitHub Release body is sourced verbatim from ``docs/releases/<tag>.md`` by
the release workflow (never ``--generate-notes``), and the same file's
TestFlight section is the paste source for the build's ASC Test Details. This
gate makes a thin or unfinished notes file fail the release before any build
work starts:

  * the file must exist for the exact tag and carry real substance (minimum
    size, a What's-new/Headline section, Requirements, Install, and a
    TestFlight What-to-Test section);
  * placeholder tokens (PENDING/TBD/TODO/FIXME) fail closed — they mark a
    file that was staged mid-flight and never finished;
  * markdown links must be absolute (https/mailto/intra-page anchors), because
    the file renders both in-repo and on the release page, where relative
    links break.

Usage: check_release_notes.py TAG [--file PATH]
"""

from __future__ import annotations

import argparse
import pathlib
import re
import sys

MIN_BYTES = 1500
TAG_PATTERN = re.compile(r"^v\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$")

REQUIRED_SECTIONS = (
    ("what's-new/headline substance", re.compile(r"(?mi)^##\s+(what|headline)")),
    ("requirements", re.compile(r"(?mi)^##\s+requirements")),
    ("install", re.compile(r"(?mi)^##\s+install")),
    ("testflight what-to-test", re.compile(r"(?mi)^##\s+testflight")),
)

PLACEHOLDER_PATTERN = re.compile(r"\b(PENDING(?:-[A-Z0-9-]+)?|TBD|TODO|FIXME)\b")

# A markdown link target that is not absolute https/http, an intra-page
# anchor, or a mailto link breaks on the GitHub Release page.
RELATIVE_LINK_PATTERN = re.compile(r"\]\((?!https?://|#|mailto:)([^)\s]+)\)")


def validate_notes(text: str) -> list[str]:
    """Return a list of human-readable failures; empty means PASS."""
    failures: list[str] = []
    if len(text.encode("utf-8")) < MIN_BYTES:
        failures.append(
            f"notes body is under {MIN_BYTES} bytes — a release the size of a "
            "Vocello release deserves real notes"
        )
    for label, pattern in REQUIRED_SECTIONS:
        if not pattern.search(text):
            failures.append(f"missing required section: {label} (## heading)")
    placeholders = sorted({m.group(1) for m in PLACEHOLDER_PATTERN.finditer(text)})
    if placeholders:
        failures.append(
            "placeholder tokens present (finish the file before tagging): "
            + ", ".join(placeholders)
        )
    relative_links = sorted({m.group(1) for m in RELATIVE_LINK_PATTERN.finditer(text)})
    if relative_links:
        failures.append(
            "relative markdown links break on the release page — use absolute "
            "URLs: " + ", ".join(relative_links)
        )
    return failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tag", help="release tag, e.g. v2.3.0")
    parser.add_argument(
        "--file",
        type=pathlib.Path,
        default=None,
        help="override the notes path (default: docs/releases/<tag>.md)",
    )
    args = parser.parse_args(argv)

    if not TAG_PATTERN.match(args.tag):
        print(f"check_release_notes: invalid tag {args.tag!r}", file=sys.stderr)
        return 1

    notes_path = args.file or pathlib.Path("docs/releases") / f"{args.tag}.md"
    if not notes_path.is_file():
        print(
            f"check_release_notes: FAIL — {notes_path} does not exist; every "
            "release ships curated notes (see docs/reference/macos-release-qa.md)",
            file=sys.stderr,
        )
        return 1

    failures = validate_notes(notes_path.read_text(encoding="utf-8"))
    if failures:
        print(f"check_release_notes: FAIL — {notes_path}", file=sys.stderr)
        for failure in failures:
            print(f"  - {failure}", file=sys.stderr)
        return 1

    print(f"check_release_notes: PASS — {notes_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
