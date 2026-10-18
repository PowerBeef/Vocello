#!/usr/bin/env python3
"""What the pinned Periphery reports unused in owned code, for the nightly summary. Report-only.

The nightly `dead-code` job (workflow audit P3-4, DW-04) compiles the macOS app, the CLI and the iOS
app into one scratch root with the index store kept and runs Periphery over all three schemes
(`scripts/dead_code_report.sh`). This script reads Periphery's JSON results and writes Markdown: the
total, the counts by hint and by declaration kind, by area (the first two path components, such as
Sources/QwenVoiceCore) and the files with the most findings. Only owned code counts (Sources/ and
Packages/VocelloQwen3Core/); every path it prints is repository-relative, and a result outside owned
code is counted as excluded, never named. It fails on no finding and exits non-zero only when the
results are missing or unreadable. No finding is a verdict.

    periphery_report.py RESULTS [--root DIR] [--top N] [--output report.md]
        Writes the Markdown to $GITHUB_STEP_SUMMARY, stdout and `--output`. `--root` is the
        repository root an absolute result path is made relative to (default: the working
        directory).
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass

OWNED_PREFIXES = ("Sources/", "Packages/VocelloQwen3Core/")
DEFAULT_TOP = 30
TITLE = "### Dead code: Periphery over the macOS app, CLI and iOS app (report-only)"
# What each Periphery hint means; a hint not listed here is shown without a meaning.
HINTS = {
    "unused": "never referenced",
    "assignOnlyProperty": "assigned but never read",
    "redundantPublicAccessibility": "public, but used only inside its own module",
    "redundantProtocol": "a protocol no declaration is used as",
    "redundantConformance": "a conformance nothing relies on",
    "superfluousIgnoreCommand": "a `periphery:ignore` comment that retains nothing",
}
# Periphery reports an unused import as a declaration of kind `module`.
KIND_NOTES = {"module": "an unused import"}
NO_HINT = "(none)"


class ResultsError(Exception):
    """The results file is missing or is not Periphery's JSON."""


@dataclass(frozen=True)
class Finding:
    file: str  # repository-relative, always under an owned prefix
    line: int
    kind: str
    hints: tuple[str, ...]


def relative_file(location: str, root: str) -> str | None:
    """The repository-relative file of a `path:line:column` location; None outside the repository."""
    path = location.rsplit(":", 2)[0] if location.count(":") >= 2 else location
    prefix = root.rstrip("/") + "/"
    if root and path.startswith(prefix):
        path = path[len(prefix):]
    elif path.startswith("/"):
        return None
    while path.startswith("./"):
        path = path[2:]
    return path or None


def is_owned(file: str) -> bool:
    return file.startswith(OWNED_PREFIXES) and "/../" not in f"/{file}"


def _line(location: str) -> int:
    parts = location.rsplit(":", 2)
    return int(parts[1]) if len(parts) == 3 and parts[1].isdigit() else 0


def parse(results: list[object], root: str) -> tuple[list[Finding], int]:
    """The findings in owned code, and how many results were outside it (or had no location)."""
    findings: list[Finding] = []
    excluded = 0
    for result in results:
        location = result.get("location") if isinstance(result, dict) else None
        if not isinstance(result, dict) or not isinstance(location, str):
            excluded += 1
            continue
        file = relative_file(location, root)
        if file is None or not is_owned(file):
            excluded += 1
            continue
        hints = result.get("hints")
        kind = result.get("kind")
        findings.append(Finding(
            file=file,
            line=_line(location),
            kind=kind if isinstance(kind, str) and kind else "(unknown)",
            hints=tuple(str(hint) for hint in hints) if isinstance(hints, list) and hints else (NO_HINT,),
        ))
    return findings, excluded


def area(file: str) -> str:
    """The first two path components (Sources/QwenVoiceCore); a file directly under Sources/ is Sources."""
    parts = file.split("/")
    return "/".join(parts[:2]) if len(parts) > 2 else parts[0]


def _cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


def _ranked(counts: Counter[str]) -> list[tuple[str, int]]:
    return sorted(counts.items(), key=lambda item: (-item[1], item[0]))


def render(findings: list[Finding], excluded: int, top: int = DEFAULT_TOP) -> str:
    out = [TITLE, ""]
    files = {finding.file for finding in findings}
    scope = "owned code (`Sources/`, `Packages/VocelloQwen3Core/`)"
    outside = (f"; {excluded} result(s) outside owned code are not counted" if excluded else "")
    if not findings:
        out += [f"No finding in {scope}{outside}.", ""]
        return "\n".join(out)
    out += [f"{len(findings)} finding(s) in {scope} across {len(files)} file(s){outside}. No finding is a "
            "verdict: Periphery cannot see a use through reflection, a string lookup or a target outside these "
            "schemes, so check each one before deleting it.", ""]

    hint_counts: Counter[str] = Counter(hint for finding in findings for hint in finding.hints)
    hints = [hint for hint, _ in _ranked(hint_counts)]
    out += ["#### By hint", "", "| Hint | Meaning | Findings |", "|---|---|---|"]
    out += [f"| `{_cell(hint)}` | {HINTS.get(hint, '')} | {count} |" for hint, count in _ranked(hint_counts)]
    out.append("")

    kind_counts: Counter[str] = Counter(finding.kind for finding in findings)
    out += ["#### By declaration kind", "", "| Kind | Findings |", "|---|---|"]
    for kind, count in _ranked(kind_counts):
        note = f" ({KIND_NOTES[kind]})" if kind in KIND_NOTES else ""
        out.append(f"| `{_cell(kind)}`{note} | {count} |")
    out.append("")

    header = " | ".join(f"`{_cell(hint)}`" for hint in hints)
    divider = "|---|---|" + "---|" * len(hints)

    def table(groups: dict[str, list[Finding]], limit: int | None, label: str) -> list[str]:
        ranked = sorted(groups.items(), key=lambda item: (-len(item[1]), item[0]))
        shown = ranked if limit is None else ranked[:limit]
        rows = [f"| {label} | Findings | {header} |", divider]
        for name, members in shown:
            counts = Counter(hint for member in members for hint in member.hints)
            cell = f"`{_cell(name)}`" if label == "File" else _cell(name)
            rows.append(f"| {cell} | {len(members)} | " + " | ".join(str(counts[hint]) for hint in hints) + " |")
        return rows

    by_area: dict[str, list[Finding]] = defaultdict(list)
    by_file: dict[str, list[Finding]] = defaultdict(list)
    for finding in findings:
        by_area[area(finding.file)].append(finding)
        by_file[finding.file].append(finding)
    out += ["#### By area", ""] + table(by_area, None, "Area") + [""]
    shown = min(top, len(by_file))
    out += [f"#### Files with the most findings ({shown} of {len(by_file)})", ""]
    out += table(by_file, top, "File") + [""]
    return "\n".join(out)


def load(path: pathlib.Path) -> list[object]:
    """Periphery's results; a ResultsError names only the file's name, never its directory."""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError as error:
        raise ResultsError(f"no Periphery results at `{path.name}`") from error
    except (OSError, UnicodeDecodeError) as error:
        reason = error.strerror if isinstance(error, OSError) and error.strerror else type(error).__name__
        raise ResultsError(f"the Periphery results at `{path.name}` are unreadable ({reason})") from error
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as error:
        raise ResultsError(f"the Periphery results at `{path.name}` are not JSON ({error.msg}, line "
                           f"{error.lineno})") from error
    if not isinstance(payload, list):
        raise ResultsError(f"the Periphery results at `{path.name}` are not a JSON array")
    return payload


def _emit(text: str, output: pathlib.Path | None) -> None:
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text, encoding="utf-8")
    target = os.environ.get("GITHUB_STEP_SUMMARY")
    if target:
        with open(target, "a", encoding="utf-8") as handle:
            handle.write(text)
    sys.stdout.write(text)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("results", type=pathlib.Path, help="Periphery's `--format json` results")
    parser.add_argument("--root", default=os.getcwd(),
                        help="the repository root an absolute result path is made relative to")
    parser.add_argument("--top", type=int, default=DEFAULT_TOP, help="files listed (default 30)")
    parser.add_argument("--output", type=pathlib.Path, help="also write the Markdown here")
    args = parser.parse_args(argv)
    try:
        results = load(args.results)
    except ResultsError as error:
        print(f"error: {error}", file=sys.stderr)
        _emit(f"{TITLE}\n\nNo report: {error}. The scan did not run or failed before it finished; "
              "see the job log.\n", args.output)
        return 1
    findings, excluded = parse(results, str(args.root))
    _emit(render(findings, excluded, args.top) + "\n", args.output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
