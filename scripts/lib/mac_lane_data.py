#!/usr/bin/env python3
"""The data steps of scripts/macos_test.sh, as tested functions behind one command line.

The lane used to carry these as inline `python3 -` heredocs and `python3 -c` one-liners,
where nothing tested them. Each subcommand prints exactly what the inline code printed,
so the shell around it reads the same lines:

    coverage-summary COVERAGE_JSON OUT ROOT   per-directory line coverage of repository
                                              sources; prints `coverage=P% lines (C/N)`
    language-models MATRIX SUBSET             the model IDs a language-bench subset needs
    language-takes PLAN CORPUS                one unit-separated line per planned take
    field FILE KEY [--join SEP]               one top-level JSON value
    takes-counts MANIFEST                     the qc-takes manifest's six summary counts
    audio-qc ROWS                             exit 1 when any telemetry row's audioQC failed

Only the standard library: the lane runs it with whichever `python3` is on PATH.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

UNIT_SEPARATOR = "\x1f"


def _load(path: str | Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def coverage_lines(data: Mapping[str, Any], root: str) -> tuple[list[str], float, int, int]:
    """Group llvm-cov's per-file line counts under the repository root.

    Sources/ and Packages/ group by their first two path components, everything else
    by its first. Files outside the root, and the build tree (SwiftPM checkouts and
    DerivedData), are not repository sources."""
    prefix = root.rstrip("/") + "/"
    groups: dict[str, list[int]] = {}
    total_covered = total_count = 0
    for item in data.get("data", []):
        for entry in item.get("files", []):
            name = entry["filename"]
            if not name.startswith(prefix):
                continue
            relative = name[len(prefix):]
            if relative.startswith("build/"):
                continue
            parts = relative.split("/")
            top = "/".join(parts[:2]) if relative.startswith(("Sources/", "Packages/")) else parts[0]
            lines = entry["summary"]["lines"]
            group = groups.setdefault(top, [0, 0])
            group[0] += lines["covered"]
            group[1] += lines["count"]
            total_covered += lines["covered"]
            total_count += lines["count"]
    out: list[str] = []
    for top, (covered, count) in sorted(groups.items()):
        percent = (100.0 * covered / count) if count else 0.0
        out.append(f"{percent:6.1f}%  {covered:7d}/{count:<7d}  {top}")
    percent = (100.0 * total_covered / total_count) if total_count else 0.0
    out.append(f"{percent:6.1f}%  {total_covered:7d}/{total_count:<7d}  TOTAL (lines, repository sources)")
    return out, percent, total_covered, total_count


def language_models(matrix: Mapping[str, Any], subset: str) -> list[str]:
    """The sorted model IDs (`pro_<mode>_<variant>`) of a language-bench subset."""
    cells = matrix["cells"] if subset == "full" else [cell for cell in matrix["cells"] if cell.get("quick")]
    return sorted({f"pro_{cell['mode']}_{cell.get('variant', 'speed')}" for cell in cells})


def language_take_lines(plan: Mapping[str, Any], corpus: Mapping[str, Any]) -> list[str]:
    """Each planned take as cellID, mode, variant, uiHint, seed, Custom speaker, Voice
    Design brief and script, unit-separated on one line.

    The speaker is empty for Design and the brief empty for Custom. A field holding the
    separator or a newline would split the line, so it refuses."""
    scripts = {entry["id"]: entry["script"] for entry in corpus["languages"]}
    lines: list[str] = []
    for take in plan["takes"]:
        fields = [
            take["cellID"], take["mode"], take.get("variant", "speed"), take.get("uiHint", "auto"),
            str(take["seed"]), take.get("customSpeakerID") or "", take.get("designInstruction") or "",
            scripts[take["scriptLang"]],
        ]
        if any(UNIT_SEPARATOR in field or "\n" in field for field in fields):
            raise ValueError(f"{take['cellID']}: a planned field contains a separator")
        lines.append(UNIT_SEPARATOR.join(fields))
    return lines


def field_text(document: Mapping[str, Any], key: str, join: str | None = None) -> str:
    value = document[key]
    if join is not None:
        return join.join(str(item) for item in value)
    return str(value)


def takes_counts(manifest: Mapping[str, Any]) -> list[str]:
    """generated, rejected, failed, missing, bound/total introspection, and the takes
    that failed for reaching the generation limit (`generation.incomplete`)."""
    counts = manifest["counts"]
    introspection = manifest.get("introspection", {})
    limit = sum(
        1 for take in manifest["takes"]
        if take.get("status") == "failed"
        and (take.get("failure") or {}).get("errorCode") == "generation.incomplete"
    )
    bound = "{}/{}".format(
        introspection.get("bound", "?"), introspection.get("bound", 0) + introspection.get("unbound", 0),
    )
    return [str(counts["generated"]), str(counts["rejected"]), str(counts["failed"]),
            str(counts["missing"]), bound, str(limit)]


def audio_qc_failures(rows: Iterable[str]) -> list[str]:
    """The generation IDs whose audioQC verdict is `fail`, from telemetry JSON lines."""
    failures: list[str] = []
    for line in rows:
        line = line.strip()
        if not line:
            continue
        row = json.loads(line)
        if (row.get("audioQC") or {}).get("verdict") == "fail":
            failures.append(row.get("generationID", "?"))
    return failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    coverage = commands.add_parser("coverage-summary")
    coverage.add_argument("coverage_json")
    coverage.add_argument("out")
    coverage.add_argument("root")
    models = commands.add_parser("language-models")
    models.add_argument("matrix")
    models.add_argument("subset")
    takes = commands.add_parser("language-takes")
    takes.add_argument("plan")
    takes.add_argument("corpus")
    field = commands.add_parser("field")
    field.add_argument("file")
    field.add_argument("key")
    field.add_argument("--join")
    counts = commands.add_parser("takes-counts")
    counts.add_argument("manifest")
    qc = commands.add_parser("audio-qc")
    qc.add_argument("rows")
    arguments = parser.parse_args(argv)

    if arguments.command == "coverage-summary":
        lines, percent, covered, count = coverage_lines(_load(arguments.coverage_json), arguments.root)
        Path(arguments.out).write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"coverage={percent:.1f}% lines ({covered}/{count})")
    elif arguments.command == "language-models":
        for model_id in language_models(_load(arguments.matrix), arguments.subset):
            print(model_id)
    elif arguments.command == "language-takes":
        try:
            lines = language_take_lines(_load(arguments.plan), _load(arguments.corpus))
        except ValueError as error:
            print(error, file=sys.stderr)
            return 1
        for line in lines:
            print(line)
    elif arguments.command == "field":
        print(field_text(_load(arguments.file), arguments.key, arguments.join))
    elif arguments.command == "takes-counts":
        print(" ".join(takes_counts(_load(arguments.manifest))))
    else:
        with open(arguments.rows, encoding="utf-8") as rows:
            failures = audio_qc_failures(rows)
        if failures:
            print(f"gate bench: audioQC fail on {len(failures)} row(s): {', '.join(failures)}", file=sys.stderr)
            return 1
        print("gate bench: audioQC pass on all rows")
    return 0


if __name__ == "__main__":
    sys.exit(main())
