#!/usr/bin/env python3
"""What the migrate-mode strictness settings would flag, for the nightly summary. Report-only.

The 2026-10-18 workflow audit (E-04, P2-6) lists strictness settings the installed Xcode offers in a
migrate mode, which only warns: strict memory safety (SE-0458) and the upcoming features
NonisolatedNonsendingByDefault (SE-0461) and InferIsolatedConformances (SE-0470). The nightly
`migration-warnings` job compiles the macOS app and VocelloCoreTests once with them
(`QVOICE_FOUNDATION_MIGRATION_SETTINGS=... scripts/build_foundation_targets.sh macos`) and this
script reports what they flag. It files no issue and fails nothing; no count is a verdict.

    migration_warnings_report.py plan [--developer-dir DIR] [--output plan.json] [--github-output]
        Chooses each setting's value for the selected Xcode: MIGRATE where its specification offers
        it; YES for strict memory safety where only YES is offered (its diagnostics are warnings
        either way); skipped when the build-setting probe (probe_build_settings.py) reports the
        setting absent, or when an upcoming feature has no migrate mode (YES would change the
        language rules and can fail the build). `--github-output` writes `settings=<NAME=VALUE ...>`.
    migration_warnings_report.py report LOG [--plan plan.json] [--root DIR] [--top N] [--output report.md]
        Counts the build log's warnings per diagnostic group ([#StrictMemorySafety], [-Wflag], ...)
        and per file, each distinct site once (xcodebuild repeats a diagnostic per compile job and per
        target that compiles the file), and writes a Markdown report to $GITHUB_STEP_SUMMARY, stdout
        and `--output`. A missing log is reported, not an error.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import pathlib
import re
import subprocess
import sys
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass

# The settings the job enables, each with the diagnostic group its warnings carry. The group is the
# compiler's, not the feature's name: InferIsolatedConformances warns under [#IsolatedConformances].
MIGRATION_SETTINGS = {
    "SWIFT_STRICT_MEMORY_SAFETY": "StrictMemorySafety",
    "SWIFT_UPCOMING_FEATURE_NONISOLATED_NONSENDING_BY_DEFAULT": "NonisolatedNonsendingByDefault",
    "SWIFT_UPCOMING_FEATURE_INFER_ISOLATED_CONFORMANCES": "IsolatedConformances",
}
# Settings whose plain YES only adds warnings, so YES stands in where no migrate mode exists.
WARNING_ONLY = frozenset({"SWIFT_STRICT_MEMORY_SAFETY"})
PLAN_SCHEMA = 1
DEFAULT_TOP = 30

DIAGNOSTIC = re.compile(
    r"^(?P<file>.+?):(?P<line>\d+):(?P<column>\d+): (?P<kind>warning|error): (?P<message>.*)$")
GROUP = re.compile(r"\s\[(?P<group>#[A-Za-z0-9_]+|-W[^\]\s]+)\]\s*$")
ANSI = re.compile(r"\x1b\[[0-9;]*m")
NO_GROUP = "(no group)"


def _load_probe():
    path = pathlib.Path(__file__).resolve().with_name("probe_build_settings.py")
    spec = importlib.util.spec_from_file_location("probe_build_settings", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


PROBE = _load_probe()


# --- plan -----------------------------------------------------------------------------------------

def setting_values(text: str, name: str) -> tuple[str, ...] | None:
    """The values the build-setting specifications offer for `name`; None when none defines it.

    An enumeration offers its `Values`; a Boolean offers YES and NO. A setting's definition ends at
    the `}` that closes its dictionary inside the specification's list (`},` or `})`), never at a
    nested dictionary such as `CommandLineArgs = { ... };`.
    """
    found = False
    values: list[str] = []
    for match in re.finditer(rf'\bName\s*=\s*"?{re.escape(name)}"?\s*;', text):
        found = True
        body = text[match.end():]
        end = re.search(r"\}\s*[,)]", body)
        body = body[:end.start()] if end else body
        listed = re.search(r"\bValues\s*=\s*\(([^)]*)\)", body)
        kind = re.search(r'\bType\s*=\s*"?(\w+)', body)
        if listed:
            values += [value.strip().strip('"') for value in listed.group(1).split(",") if value.strip()]
        elif kind and kind.group(1).lower() == "boolean":
            values += ["YES", "NO"]
    return tuple(dict.fromkeys(values)) if found else None


@dataclass(frozen=True)
class Choice:
    setting: str
    group: str
    value: str | None  # None: skipped
    reason: str


def plan(text: str, defined: dict[str, bool]) -> list[Choice]:
    """One choice per migration setting, from the specifications and the probe's verdicts."""
    choices = []
    for setting, group in MIGRATION_SETTINGS.items():
        values = setting_values(text, setting)
        if not defined.get(setting):
            choices.append(Choice(setting, group, None,
                                  "skipped: the build-setting probe reports it absent from this Xcode"))
        elif values is None:
            choices.append(Choice(setting, group, None,
                                  "skipped: this Xcode names it but its specification does not define it"))
        elif "MIGRATE" in values:
            choices.append(Choice(setting, group, "MIGRATE", "migrate mode"))
        elif setting in WARNING_ONLY and "YES" in values:
            choices.append(Choice(setting, group, "YES",
                                  "this Xcode offers no migrate mode; its YES only warns, so it flags the same sites"))
        else:
            choices.append(Choice(setting, group, None,
                                  "skipped: this Xcode offers no migrate mode, and YES would change the "
                                  "language rules (errors, not warnings)"))
    return choices


def settings_argument(choices: list[Choice]) -> str:
    """The QVOICE_FOUNDATION_MIGRATION_SETTINGS value: the chosen NAME=VALUE pairs."""
    return " ".join(f"{choice.setting}={choice.value}" for choice in choices if choice.value)


def _xcode_version() -> str:
    try:
        lines = subprocess.run(["xcodebuild", "-version"], capture_output=True, text=True,
                               check=False).stdout.splitlines()
    except OSError:
        lines = []
    return lines[0] if lines else "the selected Xcode"


def _developer_dir(argument: pathlib.Path | None) -> pathlib.Path:
    if argument:
        return argument
    return pathlib.Path(subprocess.run(["xcode-select", "-p"], capture_output=True, text=True,
                                       check=True).stdout.strip())


def command_plan(args: argparse.Namespace) -> int:
    text = PROBE.spec_texts(_developer_dir(args.developer_dir))
    choices = plan(text, PROBE.probe(text, tuple(MIGRATION_SETTINGS)))
    payload = {"schemaVersion": PLAN_SCHEMA, "xcode": _xcode_version(),
               "settings": [asdict(choice) for choice in choices]}
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    argument = settings_argument(choices)
    if args.github_output:
        target = os.environ.get("GITHUB_OUTPUT")
        if target:
            with open(target, "a", encoding="utf-8") as handle:
                handle.write(f"settings={argument}\n")
    for choice in choices:
        print(f"{choice.setting}: {choice.value or 'skipped'} ({choice.reason})")
    print(f"settings={argument}")
    return 0


# --- report ---------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Site:
    file: str  # repository-relative, `checkouts/<package>/...` or `(outside the repository)/...`
    line: int
    column: int
    kind: str
    group: str
    message: str


def display_path(path: str, root: str) -> str:
    """A privacy-safe, repository-relative name for a diagnostic's file."""
    prefix = root.rstrip("/") + "/"
    relative = path[len(prefix):] if root and path.startswith(prefix) else path
    if "/checkouts/" in f"/{relative}":
        return "checkouts/" + f"/{relative}".split("/checkouts/", 1)[1]
    if relative.startswith("/"):
        return "(outside the repository)/" + "/".join(relative.split("/")[-2:])
    return relative


def area(file: str) -> str:
    """Where a site lives: a source area of the repository, the package checkouts or elsewhere."""
    if file.startswith("checkouts/"):
        return "third-party packages"
    if file.startswith("(outside"):
        return "outside the repository"
    parts = file.split("/")
    return "/".join(parts[:2]) if parts[0] in ("Sources", "Tests", "Packages") and len(parts) > 2 else parts[0]


def parse_log(text: str, root: str) -> tuple[list[Site], int]:
    """Distinct warning and error sites with a file location, and how many log lines carried one."""
    sites: dict[Site, None] = {}
    lines = 0
    for raw in text.splitlines():
        match = DIAGNOSTIC.match(ANSI.sub("", raw).rstrip())
        if not match:
            continue
        lines += 1
        message = match["message"]
        tag = GROUP.search(message)
        group = tag["group"].removeprefix("#") if tag else NO_GROUP
        if tag:
            message = message[:tag.start()]
        site = Site(display_path(match["file"], root), int(match["line"]), int(match["column"]),
                    match["kind"], group, message.strip())
        sites.setdefault(site, None)
    return list(sites), lines


def build_outcome(text: str) -> str:
    if "** BUILD FAILED **" in text or "** TEST BUILD FAILED **" in text:
        return "failed"
    if "** BUILD SUCCEEDED **" in text or "** TEST BUILD SUCCEEDED **" in text:
        return "succeeded"
    return "unknown"


def _cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


def render(log_text: str | None, log_name: str, plan_payload: dict | None, root: str,
           top: int = DEFAULT_TOP) -> str:
    out = ["### Migrate-mode strictness warnings (report-only)", ""]
    # Each setting's group comes from this script, not the plan, so a plan written before a group
    # was corrected still counts the right diagnostics.
    choices = [Choice(**{**entry, "group": MIGRATION_SETTINGS.get(entry["setting"], entry["group"])})
               for entry in (plan_payload or {}).get("settings", [])]
    xcode = (plan_payload or {}).get("xcode", "the selected Xcode")
    if not choices:
        choices = [Choice(setting, group, None, "no plan was recorded")
                   for setting, group in MIGRATION_SETTINGS.items()]
    applied = [choice for choice in choices if choice.value]
    if log_text is None:
        reason = ("every setting was skipped, so nothing was compiled" if not applied
                  else "the compile did not run, or stopped before xcodebuild wrote it")
        out += [f"No build log at `{log_name}`: {reason}.", ""]
    sites, lines = parse_log(log_text or "", root)
    by_group: dict[str, list[Site]] = defaultdict(list)
    for site in sites:
        by_group[site.group].append(site)

    if log_text is not None:
        outcome = build_outcome(log_text)
        note = {"succeeded": "the build succeeded",
                "failed": "**the build failed**, so the counts cover only what compiled before it stopped",
                "unknown": "the log records no build result"}[outcome]
        out += [f"{xcode} compiled the macOS app and VocelloCoreTests from a clean tree with warnings "
                f"not treated as errors; {note}. {len(sites)} distinct diagnostic site(s) from {lines} "
                "log line(s).", ""]

    out += ["| Setting | Value | Diagnostic group | Sites | Files |", "|---|---|---|---|---|"]
    for choice in choices:
        group_sites = by_group.get(choice.group, [])
        counted = log_text is not None and choice.value
        out.append(f"| `{choice.setting}` | {f'`{choice.value}`' if choice.value else 'skipped'} | "
                   f"`#{choice.group}` | {len(group_sites) if counted else '–'} | "
                   f"{len({site.file for site in group_sites}) if counted else '–'} |")
    notes = [choice for choice in choices if choice.value != "MIGRATE"]
    if notes:
        out.append("")
        out += [f"- `{choice.setting}`: {choice.reason}." for choice in notes]
    out.append("")
    if log_text is None:
        return "\n".join(out)

    migration_groups = [choice.group for choice in applied]
    migration_sites = [site for site in sites if site.group in migration_groups]
    if migration_sites:
        header = " | ".join(migration_groups)
        out += ["#### Migration sites by area", "", f"| Area | {header} |",
                "|---|" + "---|" * len(migration_groups)]
        areas: dict[str, Counter[str]] = defaultdict(Counter)
        for site in migration_sites:
            areas[area(site.file)][site.group] += 1
        for name, counts in sorted(areas.items(), key=lambda item: (-sum(item[1].values()), item[0])):
            out.append(f"| {_cell(name)} | " + " | ".join(str(counts[group]) for group in migration_groups) + " |")
        out.append("")
        files: dict[str, Counter[str]] = defaultdict(Counter)
        for site in migration_sites:
            files[site.file][site.group] += 1
        ranked = sorted(files.items(), key=lambda item: (-sum(item[1].values()), item[0]))
        shown = ranked[:top]
        out += [f"#### Files with the most migration sites ({len(shown)} of {len(ranked)})", "",
                f"| File | Sites | {header} |", "|---|---|" + "---|" * len(migration_groups)]
        for file, counts in shown:
            out.append(f"| `{_cell(file)}` | {sum(counts.values())} | "
                       + " | ".join(str(counts[group]) for group in migration_groups) + " |")
        out.append("")

    others = sorted(((group, group_sites) for group, group_sites in by_group.items()
                     if group not in migration_groups), key=lambda item: (-len(item[1]), item[0]))
    if others:
        out += ["#### Other diagnostic groups in the same build", "",
                "Most of these also appear without the migrate settings (package and toolchain warnings).", "",
                "| Group | Sites | Files |", "|---|---|---|"]
        for group, group_sites in others:
            label = group if group == NO_GROUP or group.startswith("-W") else f"#{group}"
            out.append(f"| `{_cell(label)}` | {len(group_sites)} | {len({site.file for site in group_sites})} |")
        out.append("")

    errors = [site for site in sites if site.kind == "error"]
    if errors:
        out += [f"#### Errors ({len(errors)})", ""]
        out += [f"- `{_cell(site.file)}:{site.line}` {_cell(site.message)}" for site in errors[:10]]
        if len(errors) > 10:
            out.append(f"- … and {len(errors) - 10} more in the retained log")
        out.append("")
    return "\n".join(out)


def command_report(args: argparse.Namespace) -> int:
    try:
        log_text: str | None = args.log.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        log_text = None
    plan_payload = None
    if args.plan:
        try:
            plan_payload = json.loads(args.plan.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            print(f"warning: the plan at {args.plan} is unreadable ({error}); reporting without it",
                  file=sys.stderr)
    text = render(log_text, args.log.name, plan_payload, str(args.root), args.top) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    target = os.environ.get("GITHUB_STEP_SUMMARY")
    if target:
        with open(target, "a", encoding="utf-8") as handle:
            handle.write(text)
    sys.stdout.write(text)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    plan_parser = commands.add_parser("plan", help="choose each setting's value for the selected Xcode")
    plan_parser.add_argument("--developer-dir", type=pathlib.Path, help="defaults to `xcode-select -p`")
    plan_parser.add_argument("--output", type=pathlib.Path, help="write the plan as JSON")
    plan_parser.add_argument("--github-output", action="store_true", help="append settings=... to $GITHUB_OUTPUT")
    report_parser = commands.add_parser("report", help="count a build log's warnings per group and file")
    report_parser.add_argument("log", type=pathlib.Path)
    report_parser.add_argument("--plan", type=pathlib.Path, help="the plan JSON `plan --output` wrote")
    report_parser.add_argument("--root", type=pathlib.Path, default=pathlib.Path.cwd(),
                               help="the repository root the log's paths are made relative to")
    report_parser.add_argument("--top", type=int, default=DEFAULT_TOP, help="files listed (default 30)")
    report_parser.add_argument("--output", type=pathlib.Path, help="also write the Markdown here")
    args = parser.parse_args(argv)
    return command_plan(args) if args.command == "plan" else command_report(args)


if __name__ == "__main__":
    sys.exit(main())
