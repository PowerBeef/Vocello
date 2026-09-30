#!/usr/bin/env python3
"""The lane gating contract of the audio QC detectors (AQ-09, audit sections 3.3 and 5.9).

`config/audio-qc-lane-gates.json` names, per evidence lane, the registered
detectors that gate it and at which level (`warn` or `fail`). A detector gates
only inside the scope of a qualified record (A1), so `validate` refuses a listed
detector unless one committed calibration record under
`benchmarks/audio-qc-calibration/<id>/`:

- is a valid qc-calibration record (`audio_qc_detector_calibration.record_errors`)
  of that detector, filed as `record-<plan digest 16>.json`;
- qualified it at the gate's level or a stricter one (a fail record covers a
  warn gate, never the reverse);
- was confirmed under the detector's current registry definition (A7: a changed
  entry needs a new version, a new plan and a new record);
- was confirmed at an operating point that applies to the lane's kind
  (`operatingPoints.<point>.appliesTo` in the qualification policy, so the
  evidence-lane fail bar never backs a product lane);
- covers the lane's scope: each lane language is in the record's scope with a
  measured per-language FAR; the lane's modes are among the modes the record,
  or its detector's entry, declares, and a record that declares none was
  confirmed on mode-independent audio (N2 is a codec round trip of human
  speech); and the record's confirmation population is the lane's FAR
  population.

A lane lists only detectors of the classes or stages that its `laneGatingSets`
entry in the qualification policy names, and a lane that names a matrix declares
exactly the languages and modes of the matrix's cells. The records' own
integrity (plan, ledger, rewrites) is `audio_qc_detector_calibration.py
validate`, which the contract gate runs first.

    python3 scripts/audio_qc_lane_gates.py validate
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import audio_qc_detector_calibration as calibration  # noqa: E402
from lib import language_metrics  # noqa: E402
from lib.qc_qualification import detectors as registry_lib  # noqa: E402

GATES = "config/audio-qc-lane-gates.json"
KIND = "audio-qc-lane-gates"
SCHEMA_VERSION = 1
# In order of strictness: a record qualified at a later level covers a gate at an earlier one.
LEVELS = ("warn", "fail")
# The `appliesTo` vocabulary of the policy's operating points.
LANE_KINDS = ("product", "evidence-lane")
MODES = ("custom", "design", "clone")
LANE_KEYS = frozenset({"kind", "scope", "gates"})
OPTIONAL_LANE_KEYS = frozenset({"matrix", "note"})
SCOPE_KEYS = frozenset({"languages", "modes", "farPopulation"})


class GateError(ValueError):
    """A lane-gates file or an input it names that cannot be read."""


def load_json(path: Path, what: str) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise GateError(f"{what} {Path(path).name} is unreadable: {error}") from error


def detector_records(root: Path, detector: str) -> list[tuple[str, Any]]:
    """The committed records of one detector as (repository-relative path, parsed JSON or None)."""
    directory = Path(root) / calibration.RECORDS / detector
    if not directory.is_dir():
        return []
    records = []
    for path in sorted(directory.glob("record-*.json")):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            record = None
        records.append((path.relative_to(root).as_posix(), record))
    return records


def record_population(record: Mapping[str, Any]) -> str | None:
    """The population the record's FAR was confirmed on, from its confirmation cohort's kind."""
    cohort = (record.get("cohorts") or {}).get("confirmation") or {}
    return calibration.COHORT_KINDS.get(cohort.get("kind"))


def record_modes(record: Mapping[str, Any], entry: Mapping[str, Any]) -> list[str] | None:
    """The modes a record is scoped to (its own, else its detector's), or None when mode-independent."""
    for scope in (record.get("scope") or {}, entry.get("scope") or {}):
        if scope.get("modes") is not None:
            return list(scope["modes"])
    return None


def coverage_problems(record: Any, path: str, *, entry: Mapping[str, Any], level: str,
                      lane: Mapping[str, Any], policy: Mapping[str, Any]) -> list[str]:
    """Why one record does not back a gate at `level` on `lane`; empty when it does."""
    if record is None:
        return ["unreadable"]
    invalid = calibration.record_errors(record)
    if invalid:
        return [f"not a valid record ({invalid[0]})"]
    if record["detector"] != entry["id"] or Path(path).name != f"record-{record['planSHA256'][:16]}.json":
        return [f"not filed as {entry['id']}/record-<plan digest 16>.json"]
    if record["verdict"] != "qualified":
        return [f"refused ({', '.join(record['reasons'])})"]
    problems = []
    if record["level"] not in LEVELS or LEVELS.index(record["level"]) < LEVELS.index(level):
        problems.append(f"qualified at {record['level']}, not {level}")
    if record["detectorDefinitionSHA256"] != registry_lib.definition_digest(entry):
        problems.append("confirmed an earlier definition of the detector (A7)")
    point = (policy.get("operatingPoints") or {}).get(record["operatingPoint"])
    if not isinstance(point, Mapping):
        problems.append(f"operating point {record['operatingPoint']} is not in the policy")
    elif point.get("appliesTo") is not None and lane["kind"] not in point["appliesTo"]:
        problems.append(f"operating point {record['operatingPoint']} does not apply to the lane's kind "
                        f"({lane['kind']})")
    scope = lane["scope"]
    covered = set(record["scope"].get("languages") or ())
    measured = set(((record["rates"].get("farPerLanguage") or {}).get("languages") or {}))
    outside = [language for language in scope["languages"] if language not in covered]
    if outside:
        problems.append(f"its scope lacks {', '.join(outside)}")
    unmeasured = [language for language in scope["languages"] if language in covered and language not in measured]
    if unmeasured:
        problems.append(f"it measured no FAR in {', '.join(unmeasured)}")
    modes = record_modes(record, entry)
    if modes is not None and not set(scope["modes"]) <= set(modes):
        problems.append(f"its modes {', '.join(modes)} do not cover {', '.join(scope['modes'])}")
    population = record_population(record)
    if population != scope["farPopulation"]:
        problems.append(f"its FAR was confirmed on {population}, not {scope['farPopulation']}")
    return problems


def _names(value: Any, allowed: Sequence[str]) -> bool:
    return (isinstance(value, list) and bool(value) and len(set(value)) == len(value)
            and all(isinstance(item, str) and item in allowed for item in value))


def scope_errors(root: Path, lane: Mapping[str, Any], where: str) -> list[str]:
    scope = lane.get("scope")
    if not isinstance(scope, Mapping) or set(scope) != SCOPE_KEYS:
        return [f"{where}.scope declares exactly {sorted(SCOPE_KEYS)}"]
    errors = []
    if not _names(scope["languages"], language_metrics.PRODUCT_LANGUAGES):
        errors.append(f"{where}.scope.languages lists distinct product languages")
    if not _names(scope["modes"], MODES):
        errors.append(f"{where}.scope.modes lists distinct modes of {MODES}")
    if scope["farPopulation"] not in registry_lib.POPULATIONS:
        errors.append(f"{where}.scope.farPopulation is one of {registry_lib.POPULATIONS}")
    matrix = lane.get("matrix")
    if matrix is None or errors:
        return errors
    path = Path(root) / str(matrix)
    if not isinstance(matrix, str) or Path(matrix).is_absolute() or ".." in Path(matrix).parts or not path.is_file():
        return [f"{where}.matrix names a committed matrix file"]
    document = load_json(path, "the lane matrix")
    cells = document.get("cells") if isinstance(document, Mapping) else None
    if not isinstance(cells, list) or not cells:
        return [f"{where}.matrix {matrix} lists no cells"]
    languages = sorted({cell.get("scriptLang") for cell in cells if isinstance(cell, Mapping)})
    modes = sorted({cell.get("mode") for cell in cells if isinstance(cell, Mapping)})
    if sorted(scope["languages"]) != languages or sorted(scope["modes"]) != modes:
        errors.append(f"{where}.scope declares the languages {languages} and modes {modes} of {matrix}")
    return errors


def lane_gate_errors(root: Path = REPO) -> list[str]:
    """Every problem in the lane-gates file; empty when each gate is backed by a covering record."""
    root = Path(root)
    config = load_json(root / GATES, "the lane gates")
    registry = load_json(root / calibration.REGISTRY, "the detector registry")
    policy = load_json(root / calibration.POLICY, "the qualification policy")
    if not isinstance(config, Mapping) or config.get("kind") != KIND or config.get("schemaVersion") != SCHEMA_VERSION:
        return [f"the file declares kind {KIND} and schemaVersion {SCHEMA_VERSION}"]
    lanes = config.get("lanes")
    if not isinstance(lanes, Mapping) or not lanes:
        return ["lanes names at least one lane"]
    gating_sets = policy.get("laneGatingSets") or {}
    entries = {entry["id"]: entry for entry in registry.get("detectors") or ()
               if isinstance(entry, Mapping) and isinstance(entry.get("id"), str)}
    errors: list[str] = []
    for name, lane in lanes.items():
        where = f"lanes.{name}"
        gating = gating_sets.get(name)
        if not isinstance(gating, Mapping):
            errors.append(f"{where} is not a lane of the policy's laneGatingSets {sorted(gating_sets)}")
            continue
        if not isinstance(lane, Mapping) or not LANE_KEYS <= set(lane) <= LANE_KEYS | OPTIONAL_LANE_KEYS:
            errors.append(f"{where} declares {sorted(LANE_KEYS)} and optionally {sorted(OPTIONAL_LANE_KEYS)}")
            continue
        if lane["kind"] not in LANE_KINDS:
            errors.append(f"{where}.kind is one of {LANE_KINDS}")
            continue
        problems = scope_errors(root, lane, where)
        errors.extend(problems)
        gates = lane["gates"]
        if not isinstance(gates, list):
            errors.append(f"{where}.gates must be a list")
            continue
        if problems:
            continue
        seen: set[str] = set()
        for index, gate in enumerate(gates):
            spot = f"{where}.gates[{index}]"
            if not isinstance(gate, Mapping) or set(gate) != {"detector", "level"}:
                errors.append(f"{spot} names exactly a detector and a level")
                continue
            detector, level = gate["detector"], gate["level"]
            if level not in LEVELS:
                errors.append(f"{spot}.level is one of {LEVELS}")
                continue
            entry = entries.get(detector)
            if entry is None:
                errors.append(f"{spot}: {detector} is not in {calibration.REGISTRY}")
                continue
            if detector in seen:
                errors.append(f"{spot}: {detector} is listed twice")
                continue
            seen.add(detector)
            if entry.get("class") not in (gating.get("classes") or ()) \
                    and entry.get("stage") not in (gating.get("stages") or ()):
                errors.append(f"{spot}: {detector} (class {entry.get('class')}, stage {entry.get('stage')}) is "
                              f"outside the classes {gating.get('classes')} and stages {gating.get('stages')} "
                              f"that {name} gates on")
                continue
            records = detector_records(root, detector)
            if not records:
                errors.append(f"{spot}: {detector} gates {name} at {level} without a committed calibration record")
                continue
            reasons = {path: coverage_problems(record, path, entry=entry, level=level, lane=lane, policy=policy)
                       for path, record in records}
            if all(reasons.values()):
                detail = "; ".join(f"{Path(path).name}: {', '.join(found)}" for path, found in reasons.items())
                errors.append(f"{spot}: {detector} gates {name} at {level} without a qualified record whose scope "
                              f"covers the lane ({detail})")
    return errors


def command_validate(args: argparse.Namespace) -> int:
    root = Path(args.repo_root)
    try:
        errors = lane_gate_errors(root)
    except GateError as error:
        errors = [str(error)]
    for error in errors:
        print(f"audio-qc lane gates: {GATES}: {error}", file=sys.stderr)
    if errors:
        return 1
    lanes = load_json(root / GATES, "the lane gates")["lanes"]
    count = sum(len(lane["gates"]) for lane in lanes.values())
    print(f"audio-qc lane gates: {len(lanes)} lanes, {count} gates, each backed by a qualified record covering "
          "its lane")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--repo-root", type=Path, default=REPO, help=argparse.SUPPRESS)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("validate", help="refuse a gate without a qualified scope-covering record")
    args = parser.parse_args(argv)
    return command_validate(args)


if __name__ == "__main__":
    raise SystemExit(main())
