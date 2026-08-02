#!/usr/bin/env python3
"""Every enforced surface must be discoverable from the guidance that routes to it.

CLAUDE.md states its own completeness rule: "Every active invariant must live
here, in a domain rule, in an authoritative reference document, or in a
machine-readable contract named by one of those surfaces." Nothing checked it.

On 2026-08-02 three gates, three contracts, and two generated artifacts were
added and wired into check_project_inputs.sh without being named anywhere in
CLAUDE.md or the domain rules. They fired on every commit while being invisible
to any agent reading the guidance. The same omission hit docs/project-map.html,
which CLAUDE.md calls the canonical component map.

This is an *omission* check, and that is the point. Every other gate in this
repository catches contradiction or drift -- a claim that disagrees with the
tree, or a document that fell behind its sources. None of them can see a surface
that was never mentioned at all, because there is no claim to contradict.

Covered means named in CLAUDE.md or in any .claude/rules/*.md, matching the
completeness rule's own wording. Surfaces that are deliberately internal are
exempted by name in config/surface-coverage-exemptions.json, each with a reason,
so an exemption is a recorded decision rather than an oversight.

Usage:
    python3 scripts/check_surface_coverage.py [--root DIR] [--json]
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
GATE_SCRIPT = "scripts/check_project_inputs.sh"
EXEMPTIONS_PATH = "config/surface-coverage-exemptions.json"
GUIDANCE = ("CLAUDE.md",)
GUIDANCE_GLOBS = (".claude/rules/*.md",)


class CoverageError(RuntimeError):
    """The inputs could not be read."""


def gate_invocations(root: pathlib.Path) -> set[str]:
    """Scripts the deterministic gate actually runs."""
    path = root / GATE_SCRIPT
    if not path.exists():
        raise CoverageError(f"missing {GATE_SCRIPT}")
    text = path.read_text(encoding="utf-8")
    found = set()
    for match in re.finditer(r'"\$SCRIPT_DIR/([A-Za-z0-9_./-]+\.(?:py|sh))"', text):
        found.add(f"scripts/{match.group(1)}")
    if not found:
        raise CoverageError(
            f"parsed zero gate invocations from {GATE_SCRIPT}; refusing to pass vacuously"
        )
    return found


def contracts(root: pathlib.Path) -> set[str]:
    # This check's own exemption list is excluded: a configuration file cannot
    # sensibly be required to justify its own existence, and including it makes
    # the very first exemption impossible to add.
    return {
        p.relative_to(root).as_posix()
        for p in sorted((root / "config").glob("*.json"))
        if p.relative_to(root).as_posix() != EXEMPTIONS_PATH
    }


def _named(surface: str, text: str, globs) -> bool:
    """Is this surface mentioned, as a whole name rather than a substring?

    `documented_gate.py` must not count as documentation for
    `undocumented_gate.py`. Boundaries are checked on the left only, since the
    extension already bounds the right.
    """
    basename = pathlib.Path(surface).name
    for candidate in (surface, basename):
        for match in re.finditer(re.escape(candidate), text):
            before = text[match.start() - 1] if match.start() else " "
            if not (before.isalnum() or before in "_-"):
                return True
    return any(pattern.match(surface) for pattern in globs)


def guidance_text(root: pathlib.Path) -> str:
    parts = []
    for name in GUIDANCE:
        target = root / name
        if not target.exists():
            raise CoverageError(f"missing guidance file: {name}")
        parts.append(target.read_text(encoding="utf-8"))
    for pattern in GUIDANCE_GLOBS:
        for target in sorted(root.glob(pattern)):
            parts.append(target.read_text(encoding="utf-8"))
    return "\n".join(parts)


def load_exemptions(root: pathlib.Path) -> dict[str, str]:
    path = root / EXEMPTIONS_PATH
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    entries = data.get("exemptions", [])
    out = {}
    for entry in entries:
        if not entry.get("surface") or not entry.get("why"):
            raise CoverageError(
                f"{EXEMPTIONS_PATH}: every exemption needs a surface and a why"
            )
        out[entry["surface"]] = entry["why"]
    return out


ASSISTS_BEGIN = "<!-- BEGIN OPTIONAL ASSISTS -->"
ASSISTS_END = "<!-- END OPTIONAL ASSISTS -->"
# Phrases that carry the section's meaning, not its wording. Each one exists
# because losing it would change what the section claims, not merely how it reads.
ASSISTS_REQUIRED = (
    ("no gate can validate", "the admission that the table is unverifiable"),
    # "optional" alone is too weak -- the heading itself contains it, so the
    # phrase survives even when the framing is inverted to "every entry is
    # required". "prerequisite" appears only in the sentence that matters.
    ("prerequisite", "the statement that no entry is a prerequisite"),
)
ASSISTS_MIN_ROWS = 5


def assists_findings(root: pathlib.Path) -> list[str]:
    """Guard the one CLAUDE.md section that no other check can defend.

    Everything else in CLAUDE.md is machine-checked: paths resolve, gates are
    named, facts are derived from code. The optional-assists table is the
    deliberate exception -- it routes work to skills and MCP servers that live in
    user configuration, outside the repository, where no gate can reach.

    That makes it the section most likely to be removed by something acting in
    good faith. A CLAUDE.md-improving agent evaluating against a template, or a
    currency pass tidying unverifiable prose, would both have a reasonable case
    for deleting it. This turns that from an incidental edit into a failing build.

    Rows are free to change as user tooling changes. The section, its
    unverifiability disclaimer, and its optional framing are not.
    """
    findings: list[str] = []
    claude = root / "CLAUDE.md"
    if not claude.exists():
        return [f"missing guidance file: CLAUDE.md"]
    text = claude.read_text(encoding="utf-8")

    if text.count(ASSISTS_BEGIN) != 1 or text.count(ASSISTS_END) != 1:
        return [
            "CLAUDE.md: the optional-assists section markers are missing or duplicated. "
            "This section is unverifiable by design and must not be deleted as untidy; "
            f"restore {ASSISTS_BEGIN} … {ASSISTS_END}"
        ]

    start = text.index(ASSISTS_BEGIN)
    end = text.index(ASSISTS_END)
    if end < start:
        return ["CLAUDE.md: optional-assists END marker precedes BEGIN"]
    block = text[start:end]

    lowered = block.lower()
    for phrase, why in ASSISTS_REQUIRED:
        if phrase not in lowered:
            findings.append(
                f"CLAUDE.md: the optional-assists section lost {why} "
                f"(expected the phrase {phrase!r})"
            )

    rows = [line for line in block.splitlines()
            if line.startswith("| ") and "---" not in line]
    # Header plus content rows; a gutted stub is as bad as a deleted section.
    if len(rows) - 1 < ASSISTS_MIN_ROWS:
        findings.append(
            f"CLAUDE.md: the optional-assists table has {max(len(rows) - 1, 0)} rows, "
            f"fewer than the {ASSISTS_MIN_ROWS} expected; it appears gutted rather than curated"
        )
    return findings


def evaluate(root: pathlib.Path) -> dict:
    text = guidance_text(root)
    exempt = load_exemptions(root)

    surfaces = []
    for surface in sorted(gate_invocations(root)):
        surfaces.append(("gate", surface))
    for surface in sorted(contracts(root)):
        surfaces.append(("contract", surface))

    # Guidance legitimately documents a family with one glob -- CLAUDE.md's key-paths
    # table names `config/language-bench-*.json` for three real files. Treating that
    # as undocumented would push correctly-documented surfaces into exemptions, which
    # is the opposite of what this check is for.
    globs = [
        re.compile(re.escape(pattern).replace(r"\*", "[A-Za-z0-9_.-]*") + r"\Z")
        for pattern in set(re.findall(r"`([A-Za-z0-9_./-]*\*[A-Za-z0-9_./-]*\.json)`", text))
    ]

    missing, covered, exempted, stale_exemptions = [], [], [], []
    for kind, surface in surfaces:
        # Either the full path or the bare filename counts: guidance routinely
        # names a script by filename in prose and by path in a table.
        named = _named(surface, text, globs)
        if named:
            covered.append(surface)
            if surface in exempt:
                stale_exemptions.append(surface)
        elif surface in exempt:
            exempted.append(surface)
        else:
            missing.append({"kind": kind, "surface": surface})

    assists = assists_findings(root)

    return {
        "checked": len(surfaces),
        "covered": len(covered),
        "exempted": exempted,
        "missing": missing,
        "staleExemptions": stale_exemptions,
        "assistsSection": assists,
        "ok": not missing and not stale_exemptions and not assists,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", default=str(REPO_ROOT))
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    try:
        report = evaluate(pathlib.Path(args.root).resolve())
    except CoverageError as error:
        print(f"surface-coverage error: {error}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(report, indent=2))
        return 0 if report["ok"] else 1

    for entry in report["missing"]:
        print(
            f"surface-coverage error: {entry['kind']} {entry['surface']} is enforced but "
            "named in neither CLAUDE.md nor any .claude/rules/*.md",
            file=sys.stderr,
        )
    for surface in report["staleExemptions"]:
        print(
            f"surface-coverage error: {surface} is exempted but is now documented; "
            f"remove its entry from {EXEMPTIONS_PATH}",
            file=sys.stderr,
        )
    for finding in report.get("assistsSection", []):
        print(f"surface-coverage error: {finding}", file=sys.stderr)
    if not report["ok"]:
        print(
            "\nAn enforced surface that no guidance mentions is invisible to anyone "
            "reading the docs. Document it, or exempt it with a reason.",
            file=sys.stderr,
        )
        return 1

    suffix = f", {len(report['exempted'])} exempt" if report["exempted"] else ""
    print(f"Surface coverage: PASS ({report['covered']}/{report['checked']} documented{suffix})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
