#!/usr/bin/env python3
"""Gate shellcheck and ruff on new findings only, against a committed baseline that may only shrink.

    python3 scripts/lint_baseline.py shellcheck            lint every tracked shell script and compare
    python3 scripts/lint_baseline.py ruff                  lint every tracked Python file and compare
    python3 scripts/lint_baseline.py ruff --input out.json compare a saved run instead of running the tool
    python3 scripts/lint_baseline.py ruff --update         also drop baseline entries that no longer occur
    python3 scripts/lint_baseline.py ruff --seed           write the first baseline (refused once one exists)

shellcheck runs as `shellcheck -x -S warning` (the severity `scripts/dev.sh lint` uses) and ruff with
the repository's ruff.toml; both use the versions pinned in config/toolchain.json `artifactPins`
(`scripts/install_pinned_tools.sh shellcheck ruff` installs them). The baselines live in
config/lint-baseline/<tool>.json.

A finding's key is its file, its rule code and a fingerprint of the offending line's text with
whitespace collapsed, never its line number, so edits elsewhere in the file do not move it; identical
keys are counted. A finding whose key, or whose extra occurrence of a key, is absent from the baseline
fails the run. Editing a line that carries a baselined finding changes its fingerprint, so that edit
makes the finding new: fix it then. Baseline entries that no longer occur are reported, and `--update`
removes them; only `--seed`, on a missing baseline, ever adds an entry.

Exit status: 0 no new findings, 1 new findings, 2 the tool, the baseline or an input could not be used.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCHEMA_VERSION = 1
SHELL_SHEBANG = re.compile(rb"#!\s*(?:/usr/bin/env\s+)?(?:\S*/)?(?:ba|da|k)?sh\b")


@dataclass(frozen=True)
class ToolSpec:
    command: tuple[str, ...]
    accepted_exit_codes: frozenset[int]
    version_command: tuple[str, ...]
    per_file: bool  # one process per file, run in parallel (the tool itself is single-threaded)


TOOLS: dict[str, ToolSpec] = {
    # 0: no findings, 1: findings; 2 and above: a file could not be read or the call was invalid.
    "shellcheck": ToolSpec(
        ("shellcheck", "-x", "-S", "warning", "-f", "json1"), frozenset({0, 1}), ("shellcheck", "--version"),
        per_file=True,
    ),
    # --exit-zero: findings exit 0, so any other status is an error. No cache directory in the tree.
    "ruff": ToolSpec(
        ("ruff", "check", "--no-cache", "--force-exclude", "--output-format", "json", "--exit-zero"),
        frozenset({0}), ("ruff", "--version"), per_file=False,
    ),
}


class LintBaselineError(Exception):
    """The tool, the baseline or an input cannot be used; the gate has no verdict."""


@dataclass(frozen=True)
class Finding:
    file: str
    line: int
    column: int
    code: str
    message: str


Key = tuple[str, str, str]


def _relative(root: Path, filename: str) -> str:
    path = Path(filename)
    if path.is_absolute():
        for base in (root, root.resolve()):
            for candidate in (path, path.resolve()):
                try:
                    return candidate.relative_to(base).as_posix()
                except ValueError:
                    continue
    return path.as_posix().removeprefix("./")


def parse_findings(tool: str, output: str, root: Path) -> list[Finding]:
    """Findings from shellcheck's `-f json1` or ruff's `--output-format json`."""
    try:
        payload = json.loads(output) if output.strip() else ({"comments": []} if tool == "shellcheck" else [])
    except json.JSONDecodeError as error:
        raise LintBaselineError(f"{tool} output is not JSON: {error}") from error
    findings: list[Finding] = []
    try:
        if tool == "shellcheck":
            for comment in payload["comments"]:
                findings.append(Finding(
                    _relative(root, comment["file"]), int(comment["line"]), int(comment.get("column") or 0),
                    f"SC{comment['code']}", str(comment.get("message", "")),
                ))
        elif tool == "ruff":
            for item in payload:
                location = item.get("location") or {}
                findings.append(Finding(
                    _relative(root, item["filename"]), int(location.get("row") or 0),
                    int(location.get("column") or 0),
                    # Syntax errors carry no rule code in some ruff versions.
                    str(item.get("code") or "invalid-syntax"), str(item.get("message", "")),
                ))
        else:
            raise LintBaselineError(f"unknown tool: {tool}")
    except (KeyError, TypeError, ValueError) as error:
        raise LintBaselineError(f"{tool} output has an unexpected shape: {error!r}") from error
    return findings


class _LineReader:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.cache: dict[str, list[str]] = {}

    def text(self, file: str, line: int) -> str:
        if file not in self.cache:
            try:
                self.cache[file] = (self.root / file).read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                self.cache[file] = []
        lines = self.cache[file]
        return lines[line - 1] if 1 <= line <= len(lines) else ""


def fingerprint(line_text: str) -> str:
    """A short digest of the line with whitespace collapsed, so re-indenting keeps the key."""
    return hashlib.sha256(" ".join(line_text.split()).encode("utf-8")).hexdigest()[:16]


def keyed(findings: list[Finding], root: Path) -> list[tuple[Key, Finding]]:
    reader = _LineReader(root)
    return [((f.file, f.code, fingerprint(reader.text(f.file, f.line))), f) for f in findings]


def load_baseline(path: Path, tool: str) -> Counter[Key]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise LintBaselineError(
            f"{path} does not exist; `python3 scripts/lint_baseline.py {tool} --seed` writes the first one"
        ) from error
    except (OSError, json.JSONDecodeError) as error:
        raise LintBaselineError(f"{path}: {error}") from error
    if not isinstance(payload, dict) or payload.get("schemaVersion") != SCHEMA_VERSION:
        raise LintBaselineError(f"{path}: unsupported schemaVersion")
    if payload.get("tool") != tool:
        raise LintBaselineError(f"{path}: baseline is for {payload.get('tool')!r}, not {tool!r}")
    baseline: Counter[Key] = Counter()
    entries = payload.get("findings")
    if not isinstance(entries, list):
        raise LintBaselineError(f"{path}: findings must be a list")
    for entry in entries:
        if not isinstance(entry, dict):
            raise LintBaselineError(f"{path}: invalid entry {entry!r}")
        file, code, digest, count = (entry.get(name) for name in ("file", "code", "fingerprint", "count"))
        if not (isinstance(file, str) and isinstance(code, str) and isinstance(digest, str)
                and isinstance(count, int) and not isinstance(count, bool) and count > 0):
            raise LintBaselineError(f"{path}: invalid entry {entry!r}")
        if (file, code, digest) in baseline:
            raise LintBaselineError(f"{path}: duplicate entry {entry!r}")
        baseline[(file, code, digest)] = count
    return baseline


def write_baseline(path: Path, tool: str, counts: Counter[Key]) -> None:
    """One entry per line, sorted, so a shrink reads as a list of removed lines."""
    header = {
        "schemaVersion": SCHEMA_VERSION,
        "tool": tool,
        "description": (
            "Findings that existed when the gate was introduced (DW-02). Only findings absent from "
            "this list fail CI. It may only shrink: `python3 scripts/lint_baseline.py "
            f"{tool} --update` removes fixed entries; nothing adds one."
        ),
    }
    lines = [
        "    " + json.dumps({"file": file, "code": code, "fingerprint": digest, "count": counts[(file, code, digest)]})
        for file, code, digest in sorted(key for key in counts if counts[key] > 0)
    ]
    head = json.dumps(header, indent=2)[:-2]  # reopen the object to append the findings list
    body = ",\n".join(lines)
    text = f"{head},\n  \"findings\": [\n{body}\n  ]\n}}\n" if lines else f"{head},\n  \"findings\": []\n}}\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def tracked_files(root: Path, tool: str) -> list[str]:
    try:
        listing = subprocess.run(
            ["git", "-C", str(root), "ls-files", "-z"], capture_output=True, check=True,
        ).stdout.decode("utf-8")
    except (OSError, subprocess.CalledProcessError) as error:
        raise LintBaselineError(f"could not list tracked files: {error}") from error
    selected = []
    for relative in sorted(path for path in listing.split("\0") if path):
        path = root / relative
        if not path.is_file():  # deleted in the working tree
            continue
        if tool == "ruff":
            if relative.endswith(".py"):
                selected.append(relative)
        elif relative.endswith(".sh"):
            selected.append(relative)
        elif not path.suffix:
            # Extensionless shell scripts (the repository's python3 shim) are shell too.
            try:
                with path.open("rb") as stream:
                    head = stream.read(128)
            except OSError:
                continue
            if SHELL_SHEBANG.match(head):
                selected.append(relative)
    return selected


def _in_ci() -> bool:
    return bool(os.environ.get("CI") or os.environ.get("GITHUB_ACTIONS"))


def check_version(root: Path, tool: str) -> None:
    """The baseline is only meaningful for the pinned version: CI fails on drift, local runs warn."""
    try:
        manifest = json.loads((root / "config/toolchain.json").read_text(encoding="utf-8"))
        pinned = str(manifest["artifactPins"][tool]["version"])
    except (OSError, ValueError, KeyError, TypeError):
        return
    try:
        output = subprocess.run(
            list(TOOLS[tool].version_command), capture_output=True, text=True, timeout=30, check=False,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        output = ""
    match = re.search(r"\d+\.\d+\.\d+", output)
    installed = match.group(0) if match else None
    if installed == pinned:
        return
    message = (f"{tool} {installed or 'of unknown version'} is not the pinned {pinned}; its findings can "
               f"differ from the baseline (scripts/install_pinned_tools.sh {tool} installs the pin)")
    if _in_ci():
        raise LintBaselineError(message)
    print(f"warning: {message}", file=sys.stderr)


def run_tool(root: Path, tool: str, files: list[str]) -> list[str]:
    """The tool's JSON output, one document per invocation."""
    spec = TOOLS[tool]

    def invoke(batch: list[str]) -> str:
        try:
            completed = subprocess.run(
                [*spec.command, *batch], cwd=root, capture_output=True, text=True, check=False,
            )
        except OSError as error:
            raise LintBaselineError(
                f"{tool} is not runnable ({error}); scripts/install_pinned_tools.sh {tool} installs the pin"
            ) from error
        if completed.returncode not in spec.accepted_exit_codes:
            tail = "\n".join(completed.stderr.strip().splitlines()[-10:])
            raise LintBaselineError(f"{tool} exited {completed.returncode} on {len(batch)} file(s):\n{tail}")
        return completed.stdout

    if not files:
        return []
    if not spec.per_file:
        return [invoke(files)]
    with ThreadPoolExecutor(max_workers=os.cpu_count() or 1) as pool:
        return list(pool.map(invoke, [[file] for file in files]))


def _escape(value: str, property_value: bool = False) -> str:
    value = value.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
    return value.replace(":", "%3A").replace(",", "%2C") if property_value else value


@dataclass
class Comparison:
    observed: Counter[Key]
    baseline: Counter[Key]
    new: list[tuple[Finding, int, int]]  # finding, new occurrences of its key, occurrences of its key
    fixed: Counter[Key]

    @property
    def new_count(self) -> int:
        return sum(max(self.observed[key] - self.baseline[key], 0) for key in self.observed)


def compare(findings: list[Finding], baseline: Counter[Key], root: Path) -> Comparison:
    pairs = keyed(findings, root)
    observed = Counter(key for key, _ in pairs)
    new = [
        (finding, observed[key] - baseline[key], observed[key])
        for key, finding in sorted(pairs, key=lambda pair: (pair[1].file, pair[1].line, pair[1].column, pair[1].code))
        if observed[key] > baseline[key]
    ]
    fixed = Counter({key: baseline[key] - observed[key] for key in baseline if baseline[key] > observed[key]})
    return Comparison(observed, baseline, new, fixed)


def report(tool: str, comparison: Comparison, baseline_path: Path) -> None:
    annotate = os.environ.get("GITHUB_ACTIONS") == "true"
    for finding, extra, total in comparison.new:
        note = f" ({extra} of {total} identical findings on this line text are new)" if total > extra else ""
        print(f"{finding.file}:{finding.line}:{finding.column}: {finding.code} {finding.message}{note}")
        if annotate:
            print(f"::error file={_escape(finding.file, True)},line={finding.line},col={finding.column},"
                  f"title={_escape(f'{tool} {finding.code}', True)}::{_escape(finding.message)}")
    if comparison.fixed:
        count = sum(comparison.fixed.values())
        print(f"{tool}: {count} baseline finding(s) no longer occur; "
              f"`python3 scripts/lint_baseline.py {tool} --update` removes them:")
        for (file, code, digest), missing in sorted(comparison.fixed.items()):
            print(f"  {file} {code} {digest}" + (f" x{missing}" if missing > 1 else ""))
        if annotate:
            print(f"::warning title={tool} baseline can shrink::{count} fixed finding(s) are still listed in "
                  f"{_escape(baseline_path.as_posix())}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("tool", choices=sorted(TOOLS))
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--baseline", type=Path, help="default: config/lint-baseline/<tool>.json under --root")
    parser.add_argument("--input", type=Path, help="the tool's saved JSON output, instead of running it")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--update", action="store_true", help="remove baseline entries that no longer occur")
    mode.add_argument("--seed", action="store_true", help="write the baseline from today's findings if none exists")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    baseline_path = args.baseline or root / "config/lint-baseline" / f"{args.tool}.json"
    try:
        if args.seed and baseline_path.exists():
            raise LintBaselineError(
                f"{baseline_path} exists; the baseline may only shrink (`--update` removes fixed entries)"
            )
        if args.input:
            outputs = [args.input.read_text(encoding="utf-8")]
        else:
            check_version(root, args.tool)
            outputs = run_tool(root, args.tool, tracked_files(root, args.tool))
        findings = [finding for output in outputs for finding in parse_findings(args.tool, output, root)]
        if args.seed:
            counts = Counter(key for key, _ in keyed(findings, root))
            write_baseline(baseline_path, args.tool, counts)
            print(f"{args.tool}: seeded {baseline_path} with {sum(counts.values())} finding(s)")
            return 0
        baseline = load_baseline(baseline_path, args.tool)
    except (LintBaselineError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    comparison = compare(findings, baseline, root)
    report(args.tool, comparison, baseline_path)
    if args.update and comparison.fixed:
        shrunk = Counter({key: min(count, comparison.observed[key]) for key, count in baseline.items()})
        write_baseline(baseline_path, args.tool, shrunk)
        print(f"{args.tool}: removed {sum(comparison.fixed.values())} fixed finding(s) from {baseline_path}")
    new_count = comparison.new_count
    total = sum(comparison.observed.values())
    verdict = "FAIL" if new_count else "PASS"
    print(f"{args.tool}: {total} finding(s), {new_count} new, {sum(comparison.fixed.values())} fixed "
          f"against {sum(baseline.values())} in the baseline: {verdict}")
    return 1 if new_count else 0


if __name__ == "__main__":
    raise SystemExit(main())
