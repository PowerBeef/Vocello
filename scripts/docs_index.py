#!/usr/bin/env python3
"""The index of the documentation: one line per document, generated.

`docs/INDEX.md` lists `docs/ARCHITECTURE.md` and every Markdown document under
`docs/reference`, `docs/audits`, `docs/decisions` and `docs/releases`, grouped by
folder and sorted by path. Each line carries the document's front-matter
`summary`, or its first heading when it has no front matter or no summary.

The index is derived, never edited: a new, renamed or deleted document, or a
changed summary, makes the committed file stale, and `render --check` says so.
The contract gate runs that check (`scripts/lib/contract_gate.py`, whose inputs
name the folders below), `scripts/dev.sh regen` rewrites a stale index
(`scripts/refresh_derived_artifacts.py`), and the generated-file guard refuses a
hand edit.

Usage:
    python3 scripts/docs_index.py render [--check] [--root <repository>]
    python3 scripts/docs_index.py --check          # the same as: render --check

Exit status: 0 written or fresh, 1 stale (with --check), 2 a document that
cannot be read or described.
"""
from __future__ import annotations

import argparse
import pathlib
import re
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent

DOCS = pathlib.PurePosixPath("docs")
RENDER_PATH = "docs/INDEX.md"
# Single documents first, then each folder, walked recursively.
SINGLE_DOCUMENTS = ("docs/ARCHITECTURE.md",)
FOLDERS = ("docs/reference", "docs/audits", "docs/decisions", "docs/releases")

HEADING = re.compile(r"^#{1,6}\s+(.+?)\s*#*\s*$")
KEY = re.compile(r"^([A-Za-z][A-Za-z0-9_-]*):(?:\s+(.*))?$")


class DocsIndexError(Exception):
    """A document the index cannot describe."""


def front_matter(text: str) -> tuple[dict[str, str], str]:
    """The top-level scalar keys of a document's front matter, and the text after it.

    Only what the index needs: `key: value` lines, with indented continuation
    lines joined to their key. Lists and nested maps keep an empty value.
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text
    try:
        end = next(i for i, line in enumerate(lines[1:], start=1) if line.strip() == "---")
    except StopIteration:
        return {}, text
    fields: dict[str, str] = {}
    current: str | None = None
    for line in lines[1:end]:
        match = KEY.match(line)
        if match:
            current = match.group(1)
            fields[current] = (match.group(2) or "").strip()
        elif current is not None and line.startswith((" ", "\t")) and not line.lstrip().startswith("- "):
            fields[current] = f"{fields[current]} {line.strip()}".strip()
        else:
            current = None
    return fields, "\n".join(lines[end + 1:])


def unquoted(value: str) -> str:
    """A scalar without its YAML quotes or block indicator, on one line."""
    value = value.strip()
    if value[:1] in (">", "|"):
        value = value.lstrip(">|+-").strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        quote = value[0]
        value = value[1:-1]
        value = value.replace("''", "'") if quote == "'" else value.replace('\\"', '"')
    return " ".join(value.split())


def first_heading(body: str) -> str | None:
    """The text of the first Markdown heading outside a fenced code block."""
    fenced = False
    for line in body.splitlines():
        if line.lstrip().startswith(("```", "~~~")):
            fenced = not fenced
            continue
        if fenced:
            continue
        match = HEADING.match(line)
        if match:
            return " ".join(match.group(1).split())
    return None


def describe(path: pathlib.Path) -> str:
    """A document's one-line description: its summary, else its first heading."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        raise DocsIndexError(f"{path}: cannot be read ({error})") from error
    fields, body = front_matter(text)
    summary = unquoted(fields.get("summary", ""))
    if summary:
        return summary
    heading = first_heading(body)
    if heading:
        return heading
    raise DocsIndexError(f"{path}: has no front-matter summary and no heading")


def documents(root: pathlib.Path) -> list[tuple[str, list[str]]]:
    """Each group's title and its documents' repository-relative paths, sorted."""
    groups: list[tuple[str, list[str]]] = []
    single = [name for name in SINGLE_DOCUMENTS if (root / name).is_file()]
    if single:
        groups.append(("docs", single))
    for folder in FOLDERS:
        base = root / folder
        if not base.is_dir():
            continue
        by_folder: dict[str, list[str]] = {}
        for path in base.rglob("*.md"):
            if not path.is_file():
                continue
            relative = path.relative_to(root).as_posix()
            by_folder.setdefault(str(pathlib.PurePosixPath(relative).parent), []).append(relative)
        groups.extend((name, sorted(by_folder[name])) for name in sorted(by_folder))
    return groups


def render(root: pathlib.Path) -> str:
    groups = documents(root)
    total = sum(len(paths) for _, paths in groups)
    lines = [
        "# Documentation index",
        "",
        "> Generated by `python3 scripts/docs_index.py render`. Do not edit manually.",
        "> Each line is a document's front-matter `summary`, or its first heading when it has none.",
        "",
        f"{total} documents.",
    ]
    for title, paths in groups:
        lines += ["", f"## {title}", ""]
        for relative in paths:
            link = pathlib.PurePosixPath(relative).relative_to(DOCS).as_posix()
            name = pathlib.PurePosixPath(relative).name
            lines.append(f"- [{name}]({link}): {describe(root / relative)}")
    return "\n".join(lines) + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0], epilog=__doc__[__doc__.index("Usage:"):],
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", nargs="?", default="render", choices=["render"], help=f"write {RENDER_PATH}")
    parser.add_argument("--check", action="store_true", help="verify, do not write")
    parser.add_argument("--root", default=str(REPO_ROOT), help="repository root (default: this checkout)")
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    root = pathlib.Path(args.root).resolve()
    try:
        text = render(root)
    except DocsIndexError as error:
        print(f"docs index error: {error}", file=sys.stderr)
        return 2
    target = root / RENDER_PATH
    if args.check:
        if not target.exists() or target.read_text(encoding="utf-8") != text:
            print(f"error: {RENDER_PATH} is stale; run: python3 scripts/docs_index.py render", file=sys.stderr)
            return 1
        print("Docs index: fresh")
        return 0
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    print(f"Wrote {RENDER_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
