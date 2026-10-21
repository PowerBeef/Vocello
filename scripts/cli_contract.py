#!/usr/bin/env python3
"""Validate the vocello CLI machine contract (`config/cli-contract/v1/`) and record its additive changes.

    python3 scripts/cli_contract.py validate                record nothing; check everything (the contract gate)
    python3 scripts/cli_contract.py record --change "..."   record an additive change in baseline.json

`validate` checks that:

- every `*.schema.json` keeps to the Vocello schema profile (`scripts/lib/cli_contract_schema.py`),
  declares the 2020-12 dialect and names itself `urn:vocello:cli:v1:<name>`;
- the tables agree: exit codes are unique and 0 alone is `ok`; every error code's exit code is a row
  of its category, `retryable` is true exactly for the transient category, and every failing
  category has a code; event types are unique and include `started` and `result`;
- the schemas agree with the tables (the error schema's code, category and exit enums, the event
  schema's type enum and its result/other branches) and with each other (the envelope's `$defs`
  copy of the error schema, the event schema's copies of the envelope and its definitions);
- the contract only grew since `baseline.json`: no exit code, error code, event type, schema
  property, command, alias or option (in `commands.json`, the Swift command model rendered and kept
  equal to it by CLICommandModelGoldenTests) was removed or renamed, no option changed between a
  flag and a value, no exit class, error class or `retryable` changed, no required
  property became optional; anything new must be recorded there (`record`), which bumps
  `contractRevision`;
- every example validates: each `examples/*.json` as an envelope whose error agrees with the tables,
  each `examples/*.jsonl` as an NDJSON stream (one request, `seq` from 0, `t` never decreasing,
  `started` first and exactly one `result` last, whose envelope names the same request);
- when `docs/reference/cli.md` holds an exit-code table (a Markdown table whose header starts with
  "Exit" and has a "Category" column), its exit/category rows equal `exit-codes.json`'s.

`record` refuses a breaking change and any other issue, then writes the next revision of
`baseline.json` with the change's one-line description.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import datetime
import json
from pathlib import Path
import re
import sys
from typing import Any, Iterable, Iterator, Mapping, Sequence

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from lib import cli_contract_schema as profile  # noqa: E402
from lib import jsonio  # noqa: E402

REPO = SCRIPT_DIR.parent
CONTRACT_DIR = Path("config/cli-contract/v1")
DOCS = Path("docs/reference/cli.md")
CONTRACT_URN = "urn:vocello:cli:v1"
SCHEMA_SUFFIX = ".schema.json"
REQUIRED_SCHEMAS = ("envelope", "error", "event")
CODE = re.compile(r"[a-z][a-z0-9_]*\Z")
DATE = re.compile(r"\d{4}-\d{2}-\d{2}\Z")
OK, TRANSIENT, CANCELLED = "ok", "transient", "cancelled"
STARTED, RESULT = "started", "result"
SIGNAL_EXITS = {"SIGINT": 130, "SIGTERM": 143}
ROOT_ONLY = ("$schema", "$id", "title", "$defs")
EXIT_FIELDS = frozenset({"exit", "category", "meaning"})
ERROR_FIELDS = frozenset({"code", "category", "exitCode", "retryable", "summary"})
EVENT_FIELDS = frozenset({"type", "summary"})


class ContractError(ValueError):
    """A contract file is missing or unreadable."""


@dataclass(frozen=True)
class Contract:
    root: Path
    exit_rows: list[Any]
    error_rows: list[Any]
    event_rows: list[Any]
    documents: dict[str, dict[str, Any]]  # exit-codes, error-codes, event-types: the whole files
    schemas: dict[str, dict[str, Any]]  # by name: envelope, error, event and any other *.schema.json
    baseline: dict[str, Any] | None
    examples: list[Path]
    commands: dict[str, Any] | None = None  # commands.json: the command model

    @property
    def directory(self) -> Path:
        return self.root / CONTRACT_DIR


def _load(path: Path) -> dict[str, Any]:
    return jsonio.load_json(path, error=ContractError, reject_duplicate_keys=True)


def load_contract(root: Path) -> Contract:
    directory = root / CONTRACT_DIR
    if not directory.is_dir():
        raise ContractError(f"{CONTRACT_DIR} is missing")
    documents = {name: _load(directory / f"{name}.json") for name in ("exit-codes", "error-codes", "event-types")}
    schemas = {path.name[:-len(SCHEMA_SUFFIX)]: _load(path) for path in sorted(directory.glob(f"*{SCHEMA_SUFFIX}"))}
    for name in REQUIRED_SCHEMAS:
        if name not in schemas:
            raise ContractError(f"{CONTRACT_DIR / (name + SCHEMA_SUFFIX)} is missing")
    baseline_path = directory / "baseline.json"
    examples = directory / "examples"
    return Contract(
        root=root,
        exit_rows=_list(documents["exit-codes"].get("exitCodes")),
        error_rows=_list(documents["error-codes"].get("errorCodes")),
        event_rows=_list(documents["event-types"].get("eventTypes")),
        documents=documents,
        schemas=schemas,
        baseline=_load(baseline_path) if baseline_path.is_file() else None,
        examples=sorted(examples.iterdir()) if examples.is_dir() else [],
        commands=_load(directory / "commands.json") if (directory / "commands.json").is_file() else None,
    )


def command_surface(contract: Contract) -> dict[str, Any] | None:
    """What `commands.json` promises: each command path with its aliases and options (name → takes a
    value), the global options and the mode shortcuts."""
    if contract.commands is None:
        return None
    def options(rows: Any) -> dict[str, bool]:
        return {row["name"]: bool(row.get("takesValue")) for row in _list(rows) if isinstance(row, dict)}
    return {
        "commands": {row["path"]: {"aliases": sorted(_list(row.get("aliases"))), "options": options(row.get("options"))}
                     for row in _list(contract.commands.get("commands")) if isinstance(row, dict) and "path" in row},
        "globalOptions": options(contract.commands.get("globalOptions")),
        "modeShortcuts": sorted(_list(contract.commands.get("modeShortcuts"))),
    }


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _equal(left: Any, right: Any) -> bool:
    return profile.json_equal(left, right)


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


# --------------------------------------------------------------------------- #
# The tables
# --------------------------------------------------------------------------- #

def _row_shape(rows: Sequence[Any], fields: frozenset[str]) -> Iterator[tuple[int, dict[str, Any]]]:
    """The rows that are objects with exactly `fields`; the rest are reported by `table_issues`."""
    for index, row in enumerate(rows):
        if isinstance(row, dict) and set(row) == fields:
            yield index, row


def _shape_issues(rows: Sequence[Any], fields: frozenset[str], label: str) -> list[str]:
    issues = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            issues.append(f"{label}[{index}]: must be an object")
        elif set(row) != fields:
            issues.append(f"{label}[{index}]: fields must be exactly {sorted(fields)} (found {sorted(row)})")
    return issues


def exit_categories(contract: Contract) -> dict[int, str]:
    return {row["exit"]: row["category"] for _, row in _row_shape(contract.exit_rows, EXIT_FIELDS)}


def table_issues(contract: Contract) -> list[str]:
    issues: list[str] = []
    for name, document in contract.documents.items():
        if document.get("schemaVersion") != 1 or document.get("contract") != CONTRACT_URN:
            issues.append(f"{name}.json: schemaVersion must be 1 and contract {CONTRACT_URN}")

    # Exit codes.
    fields = EXIT_FIELDS
    issues += _shape_issues(contract.exit_rows, fields, "exit-codes.json exitCodes")
    if not contract.exit_rows:
        issues.append("exit-codes.json: exitCodes must be a non-empty list")
    previous = -1
    for index, row in _row_shape(contract.exit_rows, fields):
        at = f"exit-codes.json exitCodes[{index}]"
        code, category = row["exit"], row["category"]
        if not (_is_int(code) and 0 <= code <= 255):
            issues.append(f"{at}: exit must be an integer from 0 to 255")
            continue
        if code <= previous:
            issues.append(f"{at}: exit {code} repeats or is out of ascending order")
        previous = max(previous, code)
        if not (isinstance(category, str) and CODE.match(category)):
            issues.append(f"{at}: category must be snake_case")
        elif (code == 0) != (category == OK):
            issues.append(f"{at}: exit 0, and only exit 0, has category {OK}")
        if not (isinstance(row["meaning"], str) and row["meaning"].strip()):
            issues.append(f"{at}: meaning must be a non-empty string")
    categories = exit_categories(contract)
    if 0 not in categories:
        issues.append("exit-codes.json: exit 0 (ok) is missing")

    # Error codes.
    fields = ERROR_FIELDS
    issues += _shape_issues(contract.error_rows, fields, "error-codes.json errorCodes")
    if not contract.error_rows:
        issues.append("error-codes.json: errorCodes must be a non-empty list")
    seen: set[str] = set()
    used: set[str] = set()
    for index, row in _row_shape(contract.error_rows, fields):
        code, category, exit_code = row["code"], row["category"], row["exitCode"]
        at = f"error-codes.json {code if isinstance(code, str) else f'errorCodes[{index}]'}"
        if not (isinstance(code, str) and CODE.match(code)):
            issues.append(f"{at}: code must be snake_case")
        elif code in seen:
            issues.append(f"{at}: repeats an earlier code")
        else:
            seen.add(code)
        if category == OK or category not in categories.values():
            issues.append(f"{at}: category {category!r} is not a failing category of exit-codes.json")
        elif categories.get(exit_code) != category:
            issues.append(f"{at}: exitCode {exit_code!r} is not an exit of category {category} in exit-codes.json")
        else:
            used.add(category)
        if not isinstance(row["retryable"], bool) or row["retryable"] != (category == TRANSIENT):
            issues.append(f"{at}: retryable must be true exactly for the {TRANSIENT} category")
        if not (isinstance(row["summary"], str) and row["summary"].strip()):
            issues.append(f"{at}: summary must be a non-empty string")
    for category in sorted(set(categories.values()) - {OK} - used):
        issues.append(f"exit-codes.json: category {category} has no error code in error-codes.json")

    # Event types.
    fields = EVENT_FIELDS
    issues += _shape_issues(contract.event_rows, fields, "event-types.json eventTypes")
    types: list[str] = []
    for index, row in _row_shape(contract.event_rows, fields):
        kind = row["type"]
        at = f"event-types.json eventTypes[{index}]"
        if not (isinstance(kind, str) and CODE.match(kind)):
            issues.append(f"{at}: type must be snake_case")
        elif kind in types:
            issues.append(f"{at}: type {kind} repeats")
        else:
            types.append(kind)
        if not (isinstance(row["summary"], str) and row["summary"].strip()):
            issues.append(f"{at}: summary must be a non-empty string")
    for required in (STARTED, RESULT):
        if required not in types:
            issues.append(f"event-types.json: the {required} type is missing")
    return issues


def error_codes(contract: Contract) -> dict[str, dict[str, Any]]:
    fields = ERROR_FIELDS
    return {row["code"]: row for _, row in _row_shape(contract.error_rows, fields)
            if isinstance(row["code"], str)}


def event_types(contract: Contract) -> list[str]:
    return [row["type"] for _, row in _row_shape(contract.event_rows, EVENT_FIELDS)
            if isinstance(row["type"], str)]


# --------------------------------------------------------------------------- #
# The schemas
# --------------------------------------------------------------------------- #

def schema_body(schema: Mapping[str, Any]) -> dict[str, Any]:
    """A schema without its document-level keywords: what another document embeds in its $defs."""
    return {key: value for key, value in schema.items() if key not in ROOT_ONLY}


def _enum(schema: Mapping[str, Any], *path: str) -> Any:
    node: Any = schema
    for key in path:
        node = node.get(key) if isinstance(node, dict) else None
    return node.get("enum") if isinstance(node, dict) else None


def schema_issues(contract: Contract) -> list[str]:
    issues: list[str] = []
    for name, schema in contract.schemas.items():
        label = f"{name}{SCHEMA_SUFFIX}"
        issues += [f"{label} {problem}" for problem in profile.profile_issues(schema)]
        if schema.get("$schema") != profile.DIALECT:
            issues.append(f"{label}: $schema must be {profile.DIALECT}")
        if schema.get("$id") != f"{CONTRACT_URN}:{name}":
            issues.append(f"{label}: $id must be {CONTRACT_URN}:{name}")
        if not isinstance(schema.get("title"), str):
            issues.append(f"{label}: title must be a string")
    if issues:
        return issues

    codes = error_codes(contract)
    categories = exit_categories(contract)
    error, envelope, event = (contract.schemas[name] for name in ("error", "envelope", "event"))
    expected = {
        "code": sorted(codes),
        "category": sorted(set(categories.values()) - {OK}),
        "exitCode": sorted(code for code in categories if code != 0),
    }
    for field, values in expected.items():
        if not _equal(_enum(error, "properties", field), values):
            issues.append(f"error{SCHEMA_SUFFIX}: properties.{field}.enum must be {values} (the tables, sorted)")

    types = event_types(contract)
    declared = _enum(event, "properties", "type")
    if not (isinstance(declared, list) and sorted(map(str, declared)) == sorted(types)):
        issues.append(f"event{SCHEMA_SUFFIX}: properties.type.enum must list event-types.json's types")
    branches = [branch.get("properties", {}).get("type", {}) for branch in event.get("oneOf", [])
                if isinstance(branch, dict)]
    if not any(_equal(branch.get("const"), RESULT) for branch in branches):
        issues.append(f"event{SCHEMA_SUFFIX}: oneOf needs a branch for type const {RESULT!r}")
    others = sorted(kind for kind in types if kind != RESULT)
    if not any(isinstance(branch.get("enum"), list) and sorted(map(str, branch["enum"])) == others
               for branch in branches):
        issues.append(f"event{SCHEMA_SUFFIX}: oneOf needs a branch whose type enum lists every type but {RESULT}")

    envelope_defs = envelope.get("$defs", {})
    event_defs = event.get("$defs", {})
    if not _equal(envelope_defs.get("error"), schema_body(error)):
        issues.append(f"envelope{SCHEMA_SUFFIX}: $defs.error must equal error{SCHEMA_SUFFIX} without "
                      f"{', '.join(ROOT_ONLY)}")
    if not _equal(event_defs.get("envelope"), schema_body(envelope)):
        issues.append(f"event{SCHEMA_SUFFIX}: $defs.envelope must equal envelope{SCHEMA_SUFFIX} without "
                      f"{', '.join(ROOT_ONLY)}")
    if set(event_defs) != {"envelope", *envelope_defs}:
        issues.append(f"event{SCHEMA_SUFFIX}: $defs must be envelope plus envelope{SCHEMA_SUFFIX}'s $defs")
    for name, definition in envelope_defs.items():
        if name in event_defs and not _equal(event_defs[name], definition):
            issues.append(f"event{SCHEMA_SUFFIX}: $defs.{name} must equal envelope{SCHEMA_SUFFIX}'s $defs.{name}")
    return issues


def property_paths(schema: Mapping[str, Any]) -> tuple[list[str], list[str]]:
    """Every property path a schema declares (`error.code`, `warnings[].message`) and the required ones."""
    definitions = schema.get("$defs", {})
    every: set[str] = set()
    required: set[str] = set()

    def walk(node: Any, path: str, expanding: tuple[str, ...]) -> None:
        if not isinstance(node, dict):
            return
        ref = node.get("$ref")
        if isinstance(ref, str) and ref.startswith(profile.REF_PREFIX):
            name = ref[len(profile.REF_PREFIX):]
            if name not in expanding:
                walk(definitions.get(name), path, (*expanding, name))
        names = node.get("required", [])
        for key, child in (node.get("properties") or {}).items():
            child_path = f"{path}.{key}" if path else key
            every.add(child_path)
            if key in names:
                required.add(child_path)
            walk(child, child_path, expanding)
        if "items" in node:
            walk(node["items"], f"{path}[]", expanding)
        for branch in node.get("oneOf", []):
            walk(branch, path, expanding)

    walk(schema_body(schema), "", ())
    return sorted(every), sorted(required)


# --------------------------------------------------------------------------- #
# The baseline: additive-only within v1
# --------------------------------------------------------------------------- #

def baseline_snapshot(contract: Contract) -> dict[str, Any]:
    """The parts of baseline.json the current contract determines."""
    codes = error_codes(contract)
    properties = {}
    for name, schema in contract.schemas.items():
        every, required = property_paths(schema)
        properties[name] = {"properties": every, "required": required}
    return {
        "exitCodes": [{"exit": code, "category": category}
                      for code, category in sorted(exit_categories(contract).items())],
        "errorCodes": sorted(codes),
        "errorClasses": {code: {"category": row["category"], "exitCode": row["exitCode"],
                                "retryable": row["retryable"]} for code, row in sorted(codes.items())},
        "eventTypes": sorted(event_types(contract)),
        "schemaProperties": properties,
        **({"commandSurface": surface} if (surface := command_surface(contract)) is not None else {}),
    }


def _baseline_shape_issues(baseline: Mapping[str, Any]) -> list[str]:
    issues = []
    if baseline.get("schemaVersion") != 1 or baseline.get("contract") != CONTRACT_URN:
        issues.append(f"baseline.json: schemaVersion must be 1 and contract {CONTRACT_URN}")
    revision = baseline.get("contractRevision")
    revisions = baseline.get("revisions")
    if not (isinstance(revision, int) and not isinstance(revision, bool) and revision >= 1):
        issues.append("baseline.json: contractRevision must be a positive integer")
    elif not (isinstance(revisions, list) and len(revisions) == revision):
        issues.append("baseline.json: revisions must hold one entry per contract revision")
    else:
        previous = ""
        for number, entry in enumerate(revisions, start=1):
            if not (isinstance(entry, dict) and set(entry) == {"revision", "date", "change"}
                    and entry["revision"] == number and isinstance(entry["date"], str)
                    and DATE.match(entry["date"]) and entry["date"] >= previous
                    and isinstance(entry["change"], str) and entry["change"].strip()):
                issues.append(f"baseline.json: revisions[{number - 1}] must be {{revision: {number}, date: "
                              "YYYY-MM-DD not before the previous one, change: a description}")
                continue
            previous = entry["date"]
    for key in ("exitCodes", "errorCodes", "errorClasses", "eventTypes", "schemaProperties"):
        if key not in baseline:
            issues.append(f"baseline.json: {key} is missing")
    if isinstance(baseline.get("errorCodes"), list) and isinstance(baseline.get("errorClasses"), dict):
        if baseline["errorCodes"] != sorted(baseline["errorClasses"]):
            issues.append("baseline.json: errorCodes must be the sorted keys of errorClasses")
    if isinstance(baseline.get("eventTypes"), list) and baseline["eventTypes"] != sorted(set(baseline["eventTypes"])):
        issues.append("baseline.json: eventTypes must be sorted and distinct")
    return issues


def compare_with_baseline(contract: Contract, baseline: Mapping[str, Any]) -> tuple[list[str], list[str]]:
    """(breaking changes, additions baseline.json does not record yet)."""
    current = baseline_snapshot(contract)
    breaking: list[str] = []
    unrecorded: list[str] = []
    record_hint = "record it with `python3 scripts/cli_contract.py record --change ...` (bumps contractRevision)"

    frozen_exits = {row.get("exit"): row.get("category") for row in _list(baseline.get("exitCodes"))
                    if isinstance(row, dict)}
    exits = {row["exit"]: row["category"] for row in current["exitCodes"]}
    for code, category in frozen_exits.items():
        if code not in exits:
            breaking.append(f"exit {code} ({category}) was removed; v1 never removes an exit code")
        elif exits[code] != category:
            breaking.append(f"exit {code} moved from {category} to {exits[code]}; v1 never changes an exit class")
    unrecorded += [f"exit {code} ({exits[code]}) is not in baseline.json; {record_hint}"
                   for code in sorted(set(exits) - set(frozen_exits))]

    frozen_classes = _dict(baseline.get("errorClasses"))
    classes = current["errorClasses"]
    for code, frozen in sorted(frozen_classes.items()):
        if code not in classes:
            breaking.append(f"error code {code} was removed or renamed; v1 never removes an error code "
                            "(a breaking change goes to v2)")
        elif not _equal(classes[code], frozen):
            breaking.append(f"error code {code} was reclassified from {json.dumps(frozen, sort_keys=True)} to "
                            f"{json.dumps(classes[code], sort_keys=True)}; v1 never changes a code's exit class "
                            "or retryable")
    unrecorded += [f"error code {code} is not in baseline.json; {record_hint}"
                   for code in sorted(set(classes) - set(frozen_classes))]

    frozen_types = set(_list(baseline.get("eventTypes")))
    types = set(current["eventTypes"])
    breaking += [f"event type {kind} was removed or renamed; v1 never removes an event type"
                 for kind in sorted(frozen_types - types)]
    unrecorded += [f"event type {kind} is not in baseline.json; {record_hint}" for kind in sorted(types - frozen_types)]

    frozen_schemas = _dict(baseline.get("schemaProperties"))
    schemas = current["schemaProperties"]
    for name, frozen in sorted(frozen_schemas.items()):
        if name not in schemas:
            breaking.append(f"{name}{SCHEMA_SUFFIX} was removed; v1 never removes a schema")
            continue
        frozen = _dict(frozen)
        every, required = set(schemas[name]["properties"]), set(schemas[name]["required"])
        frozen_every, frozen_required = set(_list(frozen.get("properties"))), set(_list(frozen.get("required")))
        breaking += [f"{name}{SCHEMA_SUFFIX}: property {path} was removed or renamed; v1 never removes a property"
                     for path in sorted(frozen_every - every)]
        breaking += [f"{name}{SCHEMA_SUFFIX}: property {path} is no longer required; v1 never makes a property "
                     "optional" for path in sorted((frozen_required & every) - required)]
        unrecorded += [f"{name}{SCHEMA_SUFFIX}: property {path} is not in baseline.json; {record_hint}"
                       for path in sorted(every - frozen_every)]
        unrecorded += [f"{name}{SCHEMA_SUFFIX}: property {path} became required and baseline.json does not "
                       f"record it; {record_hint}" for path in sorted((required - frozen_required) & frozen_every)]
    unrecorded += [f"{name}{SCHEMA_SUFFIX} is not in baseline.json; {record_hint}"
                   for name in sorted(set(schemas) - set(frozen_schemas))]

    surface = current.get("commandSurface")
    frozen_surface = baseline.get("commandSurface")
    if surface is not None and frozen_surface is None:
        unrecorded.append(f"commands.json is not in baseline.json; {record_hint}")
    elif frozen_surface is not None and surface is None:
        breaking.append("commands.json was removed; v1 never removes the command model")
    elif surface is not None and isinstance(frozen_surface, dict):
        def options_diff(label: str, frozen: Mapping[str, Any], now: Mapping[str, Any]) -> None:
            for name, takes_value in sorted(frozen.items()):
                if name not in now:
                    breaking.append(f"{label}: option --{name} was removed or renamed; v1 never removes an option")
                elif now[name] != takes_value:
                    breaking.append(f"{label}: option --{name} changed between a flag and a value")
            unrecorded.extend(f"{label}: option --{name} is not in baseline.json; {record_hint}"
                              for name in sorted(set(now) - set(frozen)))
        options_diff("global", _dict(frozen_surface.get("globalOptions")), surface["globalOptions"])
        frozen_commands = _dict(frozen_surface.get("commands"))
        for path, frozen in sorted(frozen_commands.items()):
            if path not in surface["commands"]:
                breaking.append(f"command {path} was removed or renamed; v1 never removes a command")
                continue
            now = surface["commands"][path]
            breaking += [f"command {path}: alias {alias} was removed; v1 never removes an alias"
                         for alias in sorted(set(_list(_dict(frozen).get("aliases"))) - set(now["aliases"]))]
            unrecorded += [f"command {path}: alias {alias} is not in baseline.json; {record_hint}"
                           for alias in sorted(set(now["aliases"]) - set(_list(_dict(frozen).get("aliases"))))]
            options_diff(f"command {path}", _dict(_dict(frozen).get("options")), now["options"])
        unrecorded += [f"command {path} is not in baseline.json; {record_hint}"
                       for path in sorted(set(surface["commands"]) - set(frozen_commands))]
        breaking += [f"mode shortcut {name} was removed; v1 never removes a command"
                     for name in sorted(set(_list(frozen_surface.get("modeShortcuts"))) - set(surface["modeShortcuts"]))]
    return breaking, unrecorded


def baseline_issues(contract: Contract) -> list[str]:
    if contract.baseline is None:
        return ["baseline.json is missing; write the first one with `python3 scripts/cli_contract.py record "
                "--change ...`"]
    issues = _baseline_shape_issues(contract.baseline)
    if issues:
        return issues
    breaking, unrecorded = compare_with_baseline(contract, contract.baseline)
    return breaking + unrecorded


# --------------------------------------------------------------------------- #
# The examples
# --------------------------------------------------------------------------- #

def envelope_issues(envelope: Any, contract: Contract, label: str) -> list[str]:
    """Schema and table issues of one envelope."""
    issues = [f"{label} {issue}" for issue in profile.validate(envelope, contract.schemas["envelope"])]
    if issues:
        return issues
    revision = contract.baseline.get("contractRevision") if contract.baseline else None
    if _is_int(revision) and envelope["meta"]["contractRevision"] > revision:
        issues.append(f"{label} $.meta.contractRevision: {envelope['meta']['contractRevision']} is newer than "
                      f"baseline.json's {revision}")
    error = envelope["error"]
    if error is None:
        return issues
    row = error_codes(contract).get(error["code"])
    exits = exit_categories(contract)
    if row is None:
        return issues + [f"{label} $.error.code: {error['code']} is not in error-codes.json"]
    if error["category"] != row["category"]:
        issues.append(f"{label} $.error.category: {error['code']} is {row['category']}, not {error['category']}")
    if error["retryable"] != row["retryable"]:
        issues.append(f"{label} $.error.retryable: {error['code']} has retryable {str(row['retryable']).lower()}")
    if exits.get(error["exitCode"]) != row["category"]:
        issues.append(f"{label} $.error.exitCode: {error['exitCode']} is not an exit of category {row['category']}")
    elif row["category"] != CANCELLED and error["exitCode"] != row["exitCode"]:
        issues.append(f"{label} $.error.exitCode: {error['code']} exits {row['exitCode']}")
    signal = (error["detail"] or {}).get("signal")
    if signal is not None and SIGNAL_EXITS.get(signal) != error["exitCode"]:
        issues.append(f"{label} $.error.detail.signal: {signal!r} does not exit {error['exitCode']} "
                      f"(SIGINT exits 130, SIGTERM 143)")
    if error["retryAfterMs"] is not None and not error["retryable"]:
        issues.append(f"{label} $.error.retryAfterMs: only a retryable error suggests a wait")
    return issues


def stream_issues(text: str, contract: Contract, label: str) -> list[str]:
    """Schema, ordering and envelope issues of one NDJSON stream."""
    issues: list[str] = []
    records: list[dict[str, Any]] = []
    for number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            issues.append(f"{label}:{number}: blank line inside the stream")
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as error:
            issues.append(f"{label}:{number}: not JSON ({error.msg})")
            continue
        found = profile.validate(record, contract.schemas["event"])
        issues += [f"{label}:{number} {issue}" for issue in found]
        if not found:
            records.append(record)
    if issues:
        return issues
    if not records:
        return [f"{label}: the stream is empty"]
    request = records[0]["requestID"]
    for index, record in enumerate(records):
        at = f"{label}:{index + 1}"
        if record["seq"] != index:
            issues.append(f"{at} $.seq: expected {index}, found {record['seq']}")
        if index and record["t"] < records[index - 1]["t"]:
            issues.append(f"{at} $.t: {record['t']} is before the previous record's {records[index - 1]['t']}")
        if record["requestID"] != request:
            issues.append(f"{at} $.requestID: a stream carries one request ({request})")
        if record["type"] == RESULT and index != len(records) - 1:
            issues.append(f"{at} $.type: the result record must be the stream's last")
    if records[0]["type"] != STARTED:
        issues.append(f"{label}:1 $.type: a stream starts with a {STARTED} record")
    final = records[-1]
    if final["type"] != RESULT:
        issues.append(f"{label}: the stream must end with a {RESULT} record")
    else:
        issues += envelope_issues(final["data"], contract, f"{label}:{len(records)} result")
        if final["data"].get("requestID") != request:
            issues.append(f"{label}:{len(records)} $.data.requestID: the envelope names another request")
    return issues


def example_issues(contract: Contract) -> list[str]:
    issues: list[str] = []
    outcomes: set[bool] = set()
    streams = 0
    for path in contract.examples:
        label = f"examples/{path.name}"
        if path.suffix == ".jsonl":
            streams += 1
            issues += stream_issues(path.read_text(encoding="utf-8"), contract, label)
        elif path.suffix == ".json":
            try:
                envelope = _load(path)
            except ContractError as error:
                issues.append(f"{label}: {error}")
                continue
            issues += envelope_issues(envelope, contract, label)
            if isinstance(envelope.get("ok"), bool):
                outcomes.add(envelope["ok"])
        else:
            issues.append(f"{label}: an example is an envelope (.json) or an NDJSON stream (.jsonl)")
    if outcomes != {True, False} or not streams:
        issues.append("examples/: keep at least one success envelope, one failure envelope and one .jsonl stream")
    return issues


# --------------------------------------------------------------------------- #
# The reference docs
# --------------------------------------------------------------------------- #

def _table_blocks(text: str) -> Iterator[list[str]]:
    block: list[str] = []
    for line in [*text.splitlines(), ""]:
        if line.lstrip().startswith("|"):
            block.append(line.strip())
        elif block:
            yield block
            block = []


def _cells(line: str) -> list[str]:
    return [cell.strip().strip("`*").strip() for cell in line.strip().strip("|").split("|")]


def docs_exit_table(text: str) -> tuple[list[tuple[str, str]] | None, list[str]]:
    """The (exit, category) rows of the document's exit-code table, None when it has none, and its issues."""
    tables = []
    for block in _table_blocks(text):
        header = [cell.lower() for cell in _cells(block[0])]
        if header and header[0].startswith("exit") and "category" in header:
            tables.append((header.index("category"), block[2:]))
    if not tables:
        return None, []
    if len(tables) > 1:
        return None, [f"{DOCS}: holds {len(tables)} exit-code tables; keep one"]
    column, lines = tables[0]
    rows = []
    for line in lines:
        cells = _cells(line)
        rows.append((cells[0], cells[column] if column < len(cells) else ""))
    return rows, []


def docs_issues(contract: Contract) -> tuple[list[str], bool]:
    """Issues of the docs' exit-code table, and whether the docs hold one."""
    path = contract.root / DOCS
    if not path.is_file():
        return [], False
    rows, issues = docs_exit_table(path.read_text(encoding="utf-8"))
    if rows is None:
        return issues, bool(issues)
    expected = [(str(code), category) for code, category in sorted(exit_categories(contract).items())]
    if rows != expected:
        documented = ", ".join(f"{code} {category}" for code, category in rows)
        canonical = ", ".join(f"{code} {category}" for code, category in expected)
        issues.append(f"{DOCS}: the exit-code table lists [{documented}]; exit-codes.json lists [{canonical}]")
    return issues, True


# --------------------------------------------------------------------------- #
# Commands
# --------------------------------------------------------------------------- #

def contract_issues(contract: Contract, *, with_baseline: bool = True) -> list[str]:
    issues = table_issues(contract)
    issues += schema_issues(contract)
    if not issues:
        if with_baseline:
            issues += baseline_issues(contract)
        issues += example_issues(contract)
    issues += docs_issues(contract)[0]
    return issues


def validate(root: Path) -> tuple[list[str], str]:
    try:
        contract = load_contract(root)
    except ContractError as error:
        return [str(error)], ""
    issues = contract_issues(contract)
    revision = contract.baseline.get("contractRevision") if contract.baseline else None
    docs = "checked" if docs_issues(contract)[1] else f"no exit-code table in {DOCS}"
    summary = (f"v1 revision {revision}: {len(contract.exit_rows)} exit codes, {len(contract.error_rows)} error "
               f"codes, {len(contract.event_rows)} event types, {len(contract.schemas)} schemas, "
               f"{len(contract.examples)} examples; docs {docs}")
    return issues, summary


def record(root: Path, change: str, date: str) -> tuple[list[str], str]:
    """Write the next baseline revision; refuse a breaking change or any other issue."""
    if not change.strip():
        return ["--change must describe the change"], ""
    if not DATE.match(date):
        return [f"--date must be YYYY-MM-DD (found {date})"], ""
    try:
        contract = load_contract(root)
    except ContractError as error:
        return [str(error)], ""
    issues = contract_issues(contract, with_baseline=False)
    baseline = contract.baseline
    revisions: list[Any] = []
    if baseline is not None:
        issues += _baseline_shape_issues(baseline)
        if not issues:
            breaking, unrecorded = compare_with_baseline(contract, baseline)
            if breaking:
                return breaking, ""
            if not unrecorded:
                return [], "baseline.json already records the contract; nothing to record"
        revisions = list(baseline.get("revisions") or [])
        if revisions and date < revisions[-1].get("date", ""):
            issues.append(f"--date {date} is before revision {len(revisions)}'s {revisions[-1]['date']}")
    if issues:
        return issues, ""
    revision = len(revisions) + 1
    updated = {
        "schemaVersion": 1,
        "contract": CONTRACT_URN,
        "contractRevision": revision,
        "revisions": [*revisions, {"revision": revision, "date": date, "change": change.strip()}],
        **baseline_snapshot(contract),
    }
    jsonio.atomic_json(contract.directory / "baseline.json", updated, ascii=False, allow_nan=False)
    return [], f"recorded contract revision {revision} in {CONTRACT_DIR / 'baseline.json'}"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--root", type=Path, default=REPO, help=argparse.SUPPRESS)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("validate", help="check the contract (the contract gate runs this)")
    recording = commands.add_parser("record", help="record an additive change in baseline.json")
    recording.add_argument("--change", required=True, help="one line describing what the revision adds")
    recording.add_argument("--date", default=datetime.date.today().isoformat(), help="YYYY-MM-DD (default today)")
    return parser


def _report(issues: Iterable[str]) -> None:
    for issue in issues:
        print(f"error: {issue}", file=sys.stderr)


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = args.root.resolve()
    if args.command == "record":
        issues, message = record(root, args.change, args.date)
    else:
        issues, message = validate(root)
    if issues:
        _report(issues)
        print(f"CLI contract: FAIL ({len(issues)} issue(s))", file=sys.stderr)
        return 1
    print(f"CLI contract: PASS ({message})" if args.command == "validate" else message)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
