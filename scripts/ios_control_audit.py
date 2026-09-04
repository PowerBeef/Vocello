#!/usr/bin/env python3
"""Source-bound physical-iPhone control audit planning and composition.

This module never drives application UI.  It binds the production Swift
surface to the checked-in XCUITest owner, generates a deterministic all-pairs
generation plan, and composes untracked device observations without turning a
missing or blocked row into a pass.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import itertools
import json
import pathlib
import re
import subprocess
import sys
import zlib
from dataclasses import dataclass
from typing import Any, Iterable


ROOT = pathlib.Path(__file__).resolve().parent.parent
CONTRACT_PATH = ROOT / "config/ios-control-audit.json"
SCHEMA_PATH = ROOT / "config/ios-control-audit-schema-v1.json"
UI_TEST_PATH = ROOT / "Tests/VocelloiOSUITests/VocelloiOSControlAuditUITests.swift"
LEGACY_CONTRACT_PATH = ROOT / "config/ios-control-audit-contract-20260904.json"
LEGACY_CONTRACT_DIGEST = "cbaa65d7e33e708bb7bf23b7f3715d34eab4a501c840e98bb9151707d97811e5"
LEGACY_PLAN_V1_CONTRACT_DIGESTS = {
    # August 29 physical-device campaign. Schema v1 used sequential History
    # tokens and labelled every post-sentinel row `warm`; its retained plans
    # remain self-verifying evidence after schema v2 tightened both policies.
    "720c69792b8d8e28d3f09f06d025f3df6f59c9e2650227dab202ee93b7877d5d",
}
LEGACY_PLAN_V1_PLAN_DIGESTS = {
    # Exact plan retained by ICA-09 run
    # ios-xcui-control-audit-20260829-152245-bbe90762.
    "d49456e622ad6491965f988648da1407ec1e966d7404ccac125c1e05a4f3ddce",
}

INTERACTIVE_RE = re.compile(
    r"\b(?:Button|Toggle|Picker|NavigationLink|Link|TextEditor|TextField|Slider)\s*\("
    r"|\.(?:onTapGesture|fileImporter|confirmationDialog|alert)\b"
)
SWIFT_CASE_RE = re.compile(r"^\s*case\s+([a-z][A-Za-z0-9_]*)\b", re.MULTILINE)

TERMINAL = {
    "PASS",
    "PRODUCT_FAIL",
    "HARNESS_FAIL",
    "INFRASTRUCTURE_FAIL",
    "BLOCKED_PREREQUISITE",
    "BLOCKED_PRESERVATION_POLICY",
    "NOT_APPLICABLE",
    "SKIPPED_AFTER_FAILURE",
}

# The accessibility XCUITest emits two aggregate observations after exercising
# the four explicit content-size walks and the separate unfiltered XCTest audit.
# Keep those rows explicit so a partial attachment cannot turn an unobserved
# production inventory into PASS, while a focused accessibility run is not
# incorrectly required to repeat the inventory/stateful/external journeys.
ACCESSIBILITY_AGGREGATE_CONTROLS = {"root-tabs", "settings-preferences"}


class AuditError(RuntimeError):
    pass


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def load_json(path: pathlib.Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise AuditError(f"cannot read {path.relative_to(ROOT)}: {error}") from error


def load_contract(path: pathlib.Path = CONTRACT_PATH) -> dict[str, Any]:
    contract = load_json(path)
    if contract.get("schemaVersion") != 1:
        raise AuditError("iOS control audit contract must use schemaVersion 1")
    if set(contract.get("terminalClassifications", [])) != TERMINAL:
        raise AuditError("terminal classifications drifted from the fail-closed vocabulary")
    return contract


def _swift_cases(path: pathlib.Path, enum_name: str) -> list[str]:
    text = path.read_text(encoding="utf-8")
    marker = re.search(rf"\benum\s+{re.escape(enum_name)}\b", text)
    if not marker:
        raise AuditError(f"cannot find enum {enum_name} in {path.relative_to(ROOT)}")
    opening = text.find("{", marker.end())
    depth = 0
    end = None
    for offset, character in enumerate(text[opening:], start=opening):
        if character == "{":
            depth += 1
        elif character == "}":
            depth -= 1
            if depth == 0:
                end = offset
                break
    if end is None:
        raise AuditError(f"unterminated enum {enum_name}")
    return SWIFT_CASE_RE.findall(text[opening + 1 : end])


def catalogs() -> dict[str, list[str]]:
    speaker_contract = load_json(ROOT / "Sources/Resources/qwenvoice_contract.json")
    speakers = speaker_contract.get("speakers", {}).get("Built-in", [])
    if not speakers or not all(isinstance(value, str) for value in speakers):
        raise AuditError("qwenvoice_contract.json has no Built-in speaker catalog")

    emotion_text = (ROOT / "Sources/QwenVoiceCore/EmotionPreset.swift").read_text(encoding="utf-8")
    deliveries = re.findall(r'EmotionPreset\(\s*\n\s*id:\s*"([a-z_]+)"', emotion_text)
    languages = [
        value
        for value in _swift_cases(
            ROOT / "Sources/QwenVoiceCore/SemanticTypes.swift", "Qwen3SupportedLanguage"
        )
        if value != "auto"
    ]
    variations = _swift_cases(
        ROOT / "Sources/QwenVoiceCore/SemanticTypes.swift", "Qwen3SamplingVariation"
    )
    model_catalog = load_json(
        ROOT / "Sources/Resources/qwenvoice_production_model_catalog.json"
    )
    models = sorted(
        {
            artifact["modelID"]
            for artifact in model_catalog.get("artifacts", [])
            if "iOS" in artifact.get("platforms", [])
        }
    )
    result = {
        "speakers": list(speakers),
        "deliveries": deliveries,
        "languages": languages,
        "variations": variations,
        "models": models,
    }
    for name, values in result.items():
        if not values or len(values) != len(set(values)):
            raise AuditError(f"catalog {name} is empty or contains duplicates")
    return result


def interactive_sources(root: pathlib.Path = ROOT) -> dict[str, list[int]]:
    result: dict[str, list[int]] = {}
    paths = list((root / "Sources/iOS").rglob("*.swift"))
    shared_warning = root / "Sources/SharedSupport/Views/GenerationHistoryEnqueueWarning.swift"
    if shared_warning.exists():
        paths.append(shared_warning)
    for path in sorted(paths):
        lines = path.read_text(encoding="utf-8").splitlines()
        hits = [index for index, line in enumerate(lines, start=1) if INTERACTIVE_RE.search(line)]
        if hits:
            result[path.relative_to(root).as_posix()] = hits
    return result


def expand_inventory(contract: dict[str, Any], resolved: dict[str, list[str]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for family in contract["controlFamilies"]:
        values: Iterable[str | None] = [None]
        if family.get("expandFrom"):
            values = resolved[family["expandFrom"]]
        for value in values:
            row = dict(family)
            row.pop("expandFrom", None)
            row_id = family["id"] if value is None else f"{family['id']}:{value}"
            if row_id in seen:
                raise AuditError(f"duplicate expanded control row {row_id}")
            seen.add(row_id)
            row["controlID"] = row_id
            row["identifier"] = family["identifierPattern"].replace("{value}", value or "*")
            if value is not None:
                row["catalogValue"] = value
            rows.append(row)
    return rows


def validate_contract(contract: dict[str, Any], root: pathlib.Path = ROOT) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    resolved = catalogs()

    try:
        schema = load_json(SCHEMA_PATH)
        if schema.get("properties", {}).get("schemaVersion", {}).get("const") != 1:
            errors.append("schema does not pin schemaVersion 1")
    except AuditError as error:
        errors.append(str(error))

    source_hits = interactive_sources(root)
    coverage_rows = {row.get("path"): row for row in contract.get("sourceCoverage", [])}
    covered = set(coverage_rows)
    missing = sorted(set(source_hits) - covered)
    stale = sorted(covered - set(source_hits))
    errors.extend(f"interactive production source lacks audit policy: {path}" for path in missing)
    errors.extend(f"audit source policy no longer resolves to an interactive source: {path}" for path in stale)
    for path, lines in source_hits.items():
        expected_count = coverage_rows.get(path, {}).get("interactiveOccurrenceCount")
        if expected_count != len(lines):
            errors.append(
                f"interactive occurrence count drifted for {path}: "
                f"contract={expected_count!r}, source={len(lines)}"
            )

    source_text = "\n".join(
        path.read_text(encoding="utf-8") for path in sorted((root / "Sources/iOS").rglob("*.swift"))
    )
    shared_warning = root / "Sources/SharedSupport/Views/GenerationHistoryEnqueueWarning.swift"
    if shared_warning.exists():
        source_text += "\n" + shared_warning.read_text(encoding="utf-8")
    family_ids: set[str] = set()
    for family in contract.get("controlFamilies", []):
        family_id = family.get("id")
        if not family_id or family_id in family_ids:
            errors.append(f"missing or duplicate control family id: {family_id!r}")
            continue
        family_ids.add(family_id)
        if family.get("sourceToken") not in source_text:
            errors.append(f"control family {family_id} sourceToken does not resolve")
        if family.get("minimumTargetPoints", 0) < 44 and family.get("role") not in {
            "screen, search, and buttons",
            "row and buttons",
            "search, menu, and buttons",
            "status",
        }:
            errors.append(f"control family {family_id} permits a target below 44 points")
        if family.get("availability") == "required" and not family.get("scenario"):
            errors.append(f"required control family {family_id} has no dynamic owner")

    inventory = expand_inventory(contract, resolved)
    if UI_TEST_PATH.exists():
        test_text = UI_TEST_PATH.read_text(encoding="utf-8")
        for scenario in ("inventory", "stateful", "external", "accessibility", "generation"):
            if f'case "{scenario}"' not in test_text and f'run{scenario.title()}Audit' not in test_text:
                errors.append(f"XCUITest owner does not implement scenario {scenario}")
        for family_id in sorted(family_ids):
            if f'"{family_id}"' not in test_text:
                errors.append(f"XCUITest owner does not bind control family {family_id}")
    else:
        errors.append(f"missing {UI_TEST_PATH.relative_to(ROOT)}")

    for catalog_name, definition in contract.get("catalogs", {}).items():
        source = root / definition.get("source", "")
        if not source.exists():
            errors.append(f"catalog {catalog_name} source does not exist")
        if catalog_name not in resolved:
            errors.append(f"catalog {catalog_name} has no resolver")

    return {
        "schemaVersion": 1,
        "result": "passed" if not errors else "failed",
        "errors": errors,
        "warnings": warnings,
        "interactiveSourceCount": len(source_hits),
        "interactiveOccurrenceCount": sum(map(len, source_hits.values())),
        "controlFamilyCount": len(family_ids),
        "expandedControlCount": len(inventory),
        "catalogs": resolved,
        "inventoryDigest": digest(inventory),
    }


def _expand_dimensions(dimensions: dict[str, list[str]], resolved: dict[str, list[str]]) -> dict[str, list[str]]:
    expanded: dict[str, list[str]] = {}
    for name, values in dimensions.items():
        if len(values) == 1 and values[0].startswith("@"):
            catalog_name = values[0][1:]
            if catalog_name not in resolved:
                raise AuditError(f"unknown matrix catalog {catalog_name}")
            expanded[name] = resolved[catalog_name]
        else:
            expanded[name] = values
    return expanded


def _pair_requirements(dimensions: dict[str, list[str]]) -> set[tuple[str, str, str, str]]:
    requirements: set[tuple[str, str, str, str]] = set()
    names = list(dimensions)
    for left_index, left in enumerate(names):
        for right in names[left_index + 1 :]:
            requirements.update(
                (left, left_value, right, right_value)
                for left_value in dimensions[left]
                for right_value in dimensions[right]
            )
    return requirements


def _row_pairs(row: dict[str, str], names: list[str]) -> set[tuple[str, str, str, str]]:
    return {
        (left, row[left], right, row[right])
        for left_index, left in enumerate(names)
        for right in names[left_index + 1 :]
    }


def all_pairs_rows(dimensions: dict[str, list[str]], sentinel: dict[str, str]) -> list[dict[str, str]]:
    names = list(dimensions)
    for name in names:
        if sentinel.get(name) not in dimensions[name]:
            raise AuditError(f"cold sentinel {name}={sentinel.get(name)!r} is outside its dimension")
    candidates = [dict(zip(names, values)) for values in itertools.product(*(dimensions[name] for name in names))]
    uncovered = _pair_requirements(dimensions)
    rows: list[dict[str, str]] = [dict(sentinel)]
    uncovered.difference_update(_row_pairs(rows[0], names))
    used = {tuple(rows[0][name] for name in names)}
    while uncovered:
        best: dict[str, str] | None = None
        best_score = -1
        best_key: tuple[str, ...] | None = None
        for candidate in candidates:
            key = tuple(candidate[name] for name in names)
            if key in used:
                continue
            score = len(_row_pairs(candidate, names) & uncovered)
            if score > best_score or (score == best_score and (best_key is None or key < best_key)):
                best, best_score, best_key = candidate, score, key
        if best is None or best_score <= 0:
            raise AuditError("all-pairs generator stalled with uncovered requirements")
        rows.append(best)
        used.add(tuple(best[name] for name in names))
        uncovered.difference_update(_row_pairs(best, names))
    return rows


def tree_fingerprint(root: pathlib.Path = ROOT) -> str:
    process = subprocess.run(
        [sys.executable, str(root / "scripts/tree_fingerprint.py"), "--root", str(root)],
        text=True,
        capture_output=True,
        check=False,
    )
    if process.returncode:
        raise AuditError(f"tree fingerprint failed: {process.stderr.strip()}")
    value = process.stdout.strip()
    if not re.fullmatch(r"[0-9a-f]{64}", value):
        raise AuditError("tree fingerprint did not emit a SHA-256")
    return value


def _source_bound_search_token(
    *,
    source_identity: str,
    contract_digest: str,
    take_id: str,
    namespace_salt: int,
    used: set[str],
) -> str:
    """Return one deterministic eight-digit token unique within this plan.

    History search is only a narrowing aid; the UI test still proves the full
    immutable script before touching a row. Binding the aid to the source and
    contract prevents an older audit plan from reusing the same numeric token
    namespace on a phone that retains its History.
    """

    for attempt in range(1_024):
        identity = (
            f"{source_identity}:{contract_digest}:{namespace_salt}:"
            f"{take_id}:{attempt}"
        )
        value = 10_000_000 + (
            int.from_bytes(hashlib.sha256(identity.encode("utf-8")).digest()[:8], "big")
            % 90_000_000
        )
        token = str(value)
        if token not in used:
            used.add(token)
            return token
    raise AuditError("could not allocate a unique source-bound History search token")


def generate_plan(
    contract: dict[str, Any],
    source_identity: str | None = None,
    *,
    schema_version: int = 3,
) -> dict[str, Any]:
    if schema_version not in {1, 2, 3}:
        raise AuditError("unsupported control-audit plan schema")
    resolved_source_identity = source_identity or tree_fingerprint()
    if not re.fullmatch(r"[0-9a-f]{64}", resolved_source_identity):
        raise AuditError("control-audit source identity must be a SHA-256")
    resolved = catalogs()
    corpus = load_json(ROOT / "config/ios-control-audit-corpus.json")
    scripts = corpus.get("scripts", {})
    if set(scripts) != set(resolved["languages"]):
        missing = sorted(set(resolved["languages"]) - set(scripts))
        extra = sorted(set(scripts) - set(resolved["languages"]))
        raise AuditError(f"control-audit corpus language drift (missing={missing}, extra={extra})")
    rows: list[dict[str, Any]] = []
    contract_digest = digest(contract)
    search_token_salt = int(contract["generationMatrix"]["searchTokenBase"])
    used_search_tokens: set[str] = set()
    for mode, mode_contract in contract["generationMatrix"]["modes"].items():
        dimensions = _expand_dimensions(mode_contract["dimensions"], resolved)
        mode_rows = all_pairs_rows(dimensions, mode_contract["coldSentinel"])
        for index, values in enumerate(mode_rows):
            language = values["language"]
            length = values["length"]
            script = scripts[language].get(length)
            if not isinstance(script, str) or not script.strip():
                raise AuditError(f"missing {language}/{length} control-audit script")
            take_id = f"{mode}-{index + 1:03d}"
            if schema_version == 1:
                search_token = str(search_token_salt + len(rows))
            elif schema_version == 2:
                search_token = _source_bound_search_token(
                    source_identity=resolved_source_identity,
                    contract_digest=contract_digest,
                    take_id=take_id,
                    namespace_salt=search_token_salt,
                    used=used_search_tokens,
                )
            # v1/v2 remain exact historical regression protocols. v3 never
            # injects bookkeeping into the utterance: ownership comes from a
            # before/after History census plus the completed generation UUID.
            rendered_script = script if schema_version == 3 else f"{script} {search_token}."
            row = {
                "takeID": take_id,
                "mode": mode,
                # Only the first row is an enforced cold sentinel. Ordinary UI work between
                # subsequent rows can legitimately cross iOS's 30-second idle-unload boundary,
                # so their request receipts are observed rather than inferred from matrix order.
                "warmState": "cold" if index == 0 else "observed",
                **values,
                "script": rendered_script,
                "scriptDigest": hashlib.sha256(rendered_script.encode("utf-8")).hexdigest(),
            }
            if schema_version < 3:
                row["searchToken"] = search_token
            row["rowDigest"] = digest(row)
            rows.append(row)
    maximum = int(contract["generationMatrix"]["maxRows"])
    if len(rows) > maximum:
        raise AuditError(f"all-pairs matrix needs {len(rows)} rows, exceeding maxRows {maximum}")
    payload = {
        "schemaVersion": schema_version,
        "sourceIdentity": resolved_source_identity,
        "contractDigest": contract_digest,
        "catalogDigest": digest(resolved),
        "takeCount": len(rows),
        "takes": rows,
    }
    payload["planDigest"] = digest(payload)
    return payload


def validate_plan(contract: dict[str, Any], plan: dict[str, Any]) -> None:
    """Reject drift, truncation, reordering, or row substitution in a retained plan."""

    source_identity = plan.get("sourceIdentity")
    if not isinstance(source_identity, str) or not re.fullmatch(r"[0-9a-f]{64}", source_identity):
        raise AuditError("control-audit plan has no valid source identity")
    schema_version = plan.get("schemaVersion")
    if schema_version not in {1, 2, 3}:
        raise AuditError("unsupported control-audit plan schema")
    expected = generate_plan(
        contract,
        source_identity,
        schema_version=schema_version,
    )
    if plan == expected:
        return
    if schema_version in {2, 3} and plan.get("contractDigest") == LEGACY_CONTRACT_DIGEST:
        # Retained evidence predating the visible enqueue warning must keep its
        # exact script/seed identity, especially v2's contract-salted numeric
        # suffix. This is a pinned compatibility decoder, not a resume waiver.
        legacy = load_json(LEGACY_CONTRACT_PATH)
        if digest(legacy) != LEGACY_CONTRACT_DIGEST:
            raise AuditError("historical control-audit contract digest mismatch")
        if plan == generate_plan(legacy, source_identity, schema_version=schema_version):
            return
    if (
        schema_version == 1
        and plan.get("contractDigest") in LEGACY_PLAN_V1_CONTRACT_DIGESTS
        and plan.get("planDigest") in LEGACY_PLAN_V1_PLAN_DIGESTS
    ):
        _validate_legacy_plan_v1(contract, plan)
        return
    raise AuditError("control-audit plan does not match the deterministic source-bound plan")


def _validate_legacy_plan_v1(contract: dict[str, Any], plan: dict[str, Any]) -> None:
    """Validate retained v1 bytes without rewriting historical evidence.

    The old contract digest is allowlisted, but public SHA-256 fields are not
    signatures: accepting an arbitrary self-rehashed row would weaken the
    source-bound plan contract. Reconstruct the complete historical plan from
    its frozen source identity and the one known v1 semantic difference
    (post-sentinel rows declared `warm` instead of `observed`), then require
    byte-for-byte decoded equality. This is a compatibility decoder, not
    permission to produce new schema-v1 plans.
    """
    expected = generate_plan(
        contract,
        plan["sourceIdentity"],
        schema_version=1,
    )
    expected["contractDigest"] = plan["contractDigest"]
    seen_modes: set[str] = set()
    for row in expected["takes"]:
        if row["mode"] in seen_modes:
            row["warmState"] = "warm"
        else:
            seen_modes.add(row["mode"])
        row["rowDigest"] = digest(
            {key: value for key, value in row.items() if key != "rowDigest"}
        )
    expected["planDigest"] = digest(
        {key: value for key, value in expected.items() if key != "planDigest"}
    )
    if plan != expected:
        raise AuditError("legacy control-audit plan does not match its deterministic v1 bytes")


def encode_plan(contract: dict[str, Any], plan: dict[str, Any]) -> str:
    validate_plan(contract, plan)
    # Foundation's NSData.CompressionAlgorithm.zlib decoder consumes a raw
    # DEFLATE stream rather than the RFC 1950 wrapper emitted by
    # zlib.compress(). Keep the transport explicit so the host-produced plan
    # decodes identically in the physical-device XCTest runner.
    compressor = zlib.compressobj(level=9, method=zlib.DEFLATED, wbits=-zlib.MAX_WBITS)
    compressed = compressor.compress(canonical_bytes(plan)) + compressor.flush()
    return base64.b64encode(compressed).decode("ascii")


def _read_jsonl(path: pathlib.Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not raw.strip():
            continue
        try:
            row = json.loads(raw)
        except json.JSONDecodeError as error:
            raise AuditError(f"invalid observation JSONL line {line_number}: {error}") from error
        if not isinstance(row, dict):
            raise AuditError(f"observation line {line_number} is not an object")
        rows.append(row)
    return rows


def collect_observations(
    manifest_path: pathlib.Path,
    attachment_root: pathlib.Path,
    output_path: pathlib.Path,
) -> list[dict[str, Any]]:
    """Collect XCTest's versioned attachment names into validated JSONL.

    `xcresulttool export attachments` may preserve the requested attachment
    name or append an occurrence index and UUID. Match that documented export
    shape rather than requiring one literal filename, while rejecting path
    traversal, missing bytes, malformed JSONL, and a silent zero-row result.
    """

    manifest = load_json(manifest_path)
    if not isinstance(manifest, list):
        raise AuditError("xcresult attachment manifest must be an array")
    attachment_name = re.compile(
        r"^control-observations(?:_[0-9]+_[0-9A-Fa-f-]+)?\.jsonl$"
    )
    rows: list[dict[str, Any]] = []
    matches = 0
    for test in manifest:
        if not isinstance(test, dict):
            raise AuditError("xcresult attachment manifest contains a non-object test")
        attachments = test.get("attachments", [])
        if not isinstance(attachments, list):
            raise AuditError("xcresult attachment list is not an array")
        for attachment in attachments:
            if not isinstance(attachment, dict):
                raise AuditError("xcresult attachment entry is not an object")
            suggested = attachment.get("suggestedHumanReadableName")
            if not isinstance(suggested, str) or not attachment_name.fullmatch(suggested):
                continue
            exported = attachment.get("exportedFileName")
            if not isinstance(exported, str) or pathlib.Path(exported).name != exported:
                raise AuditError("control observation attachment has an unsafe exported filename")
            source = attachment_root / exported
            if not source.is_file():
                raise AuditError(f"control observation attachment is missing: {exported}")
            matches += 1
            rows.extend(_read_jsonl(source))
    if matches == 0:
        raise AuditError("xcresult contains no control-observations attachment")
    if not rows:
        raise AuditError("control-observations attachment contains no rows")
    if len({row.get("runID") for row in rows}) != 1:
        raise AuditError("cross-run attachment collection rejected")
    rows = ordered_observations(rows)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_name(f".{output_path.name}.next")
    temporary.write_text(
        "".join(
            json.dumps(row, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"
            for row in rows
        ),
        encoding="utf-8",
    )
    temporary.replace(output_path)
    return rows


def ordered_observations(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """v1 is immutable legacy; v2 is an immediate, gap-checked stage stream."""
    if not rows or all(row.get("schemaVersion") == 1 for row in rows):
        return rows
    if any(row.get("schemaVersion") != 2 for row in rows):
        raise AuditError("mixed observation schemas rejected")
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        if not isinstance(row.get("runID"), str) or not row["runID"]:
            raise AuditError("observation stream lacks run identity")
        sequence = row.get("sequence")
        if type(sequence) is not int or sequence < 1:
            raise AuditError("observation stream lacks a positive sequence")
        phase = row.get("phase")
        if phase not in {"request-prepared", "player-visible", "terminal", "restored"}:
            raise AuditError("unknown observation phase")
        if phase != "terminal" and row.get("classification") != "IN_PROGRESS":
            raise AuditError("nonterminal observation cannot claim a verdict")
        grouped.setdefault(row["runID"], []).append(row)
    ordered = []
    for run_rows in grouped.values():
        run_rows.sort(key=lambda row: row["sequence"])
        if [row["sequence"] for row in run_rows] != list(range(1, len(run_rows) + 1)):
            raise AuditError("duplicate or gapped observation sequence")
        if len({row.get("sourceIdentity") for row in run_rows}) != 1:
            raise AuditError("cross-source observation stream")
        if any(row["phase"] == "restored" for row in run_rows[:-1]):
            raise AuditError("observation appended after restoration boundary")
        ordered.extend(run_rows)
    return ordered


def is_terminal_observation(row: dict[str, Any]) -> bool:
    version = row.get("schemaVersion", 1)
    if version not in {1, 2}:
        raise AuditError("unsupported observation schema")
    return version == 1 or row.get("phase") == "terminal"


def generation_shard(metadata: dict[str, Any], plan: dict[str, Any]) -> tuple[int, int] | None:
    if metadata.get("controlObservationSchemaVersion") != 2:
        return None
    if metadata.get("controlAuditScenario") not in {"generation", "all"}:
        return None
    start, limit = metadata.get("controlTakeStart"), metadata.get("controlTakeLimit")
    count = len(plan["takes"])
    if type(start) is not int or type(limit) is not int or not 0 <= start < count or not 1 <= limit <= count:
        raise AuditError("invalid generation shard bounds")
    return start, min(start + limit, count)


def compose(
    contract: dict[str, Any],
    run_metadata: dict[str, Any],
    plan: dict[str, Any],
    observations: list[dict[str, Any]],
    bootstrap_classification: dict[str, Any] | None = None,
    external_interruption_classification: dict[str, Any] | None = None,
) -> dict[str, Any]:
    validate_plan(contract, plan)
    run_id = run_metadata.get("runID")
    source_identity = run_metadata.get("treeFingerprint") or run_metadata.get("sourceIdentity")
    if not run_id or not source_identity:
        raise AuditError("run metadata must contain runID and treeFingerprint/sourceIdentity")
    if plan.get("sourceIdentity") != source_identity:
        raise AuditError("generation plan source identity does not match the device run")
    if bootstrap_classification is not None and external_interruption_classification is not None:
        raise AuditError("XCUITest run cannot have two infrastructure classifications")
    if bootstrap_classification is not None:
        if bootstrap_classification.get("status") != "infrastructure_bootstrap_failure":
            raise AuditError("unsupported XCUITest bootstrap classification")
        if bootstrap_classification.get("runID") != run_id:
            raise AuditError("cross-run XCUITest bootstrap classification rejected")
        if bootstrap_classification.get("testCaseCount") != 0:
            raise AuditError("bootstrap classification must prove zero launched tests")
        if observations:
            raise AuditError("bootstrap classification cannot coexist with control observations")
    if external_interruption_classification is not None:
        if external_interruption_classification.get("status") != "infrastructure_external_interruption":
            raise AuditError("unsupported XCUITest external interruption classification")
        if external_interruption_classification.get("runID") != run_id:
            raise AuditError("cross-run XCUITest external interruption classification rejected")
        test_count = external_interruption_classification.get("testCaseCount")
        if not isinstance(test_count, int) or isinstance(test_count, bool) or test_count < 1:
            raise AuditError("external interruption classification must prove a launched test")
        if any(
            row.get("classification") in {"PRODUCT_FAIL", "HARNESS_FAIL", "INFRASTRUCTURE_FAIL"}
            for row in observations
        ):
            raise AuditError("product or harness evidence forbids external interruption classification")

    inventory = expand_inventory(contract, catalogs())
    scenario = run_metadata.get("controlAuditScenario", "all")
    if scenario in {"generation", "all"}:
        inventory.extend(
            {
                "controlID": f"generation:{take['takeID']}",
                "scenario": "generation",
                "availability": "required",
            }
            for take in plan["takes"]
        )
    if scenario != "all":
        if scenario == "accessibility":
            inventory = [
                {**row, "scenario": "accessibility"}
                for row in inventory
                if row["controlID"] in ACCESSIBILITY_AGGREGATE_CONTROLS
            ]
            if {row["controlID"] for row in inventory} != ACCESSIBILITY_AGGREGATE_CONTROLS:
                raise AuditError("accessibility aggregate controls drifted from the inventory")
        else:
            inventory = [row for row in inventory if row["scenario"] == scenario]
    expected_control_ids = {row["controlID"] for row in inventory}

    accepted_run_ids = {run_id}
    resume_run_ids = run_metadata.get("resumeRunIDs", [])
    if not isinstance(resume_run_ids, list) or any(
        not isinstance(value, str) or not value for value in resume_run_ids
    ):
        raise AuditError("resumeRunIDs must be an array of nonempty run IDs")
    accepted_run_ids.update(resume_run_ids)

    by_control: dict[str, list[dict[str, Any]]] = {}
    stages = []
    shard = generation_shard(run_metadata, plan)
    future_ids = {f"generation:{take['takeID']}" for take in plan["takes"][shard[1]:]} if shard else set()
    scheduled_ids = {f"generation:{take['takeID']}" for take in plan["takes"][shard[0]:shard[1]]} if shard else set()
    for row in ordered_observations(observations):
        if row.get("runID") not in accepted_run_ids:
            raise AuditError("cross-run observation rejected")
        if row.get("sourceIdentity") != source_identity:
            raise AuditError("cross-source observation rejected")
        if shard and row.get("controlID", "").startswith("generation:"):
            if row["controlID"] in future_ids or (row["runID"] == run_id and row["controlID"] not in scheduled_ids):
                raise AuditError("observation outside the declared generation shard")
        if not is_terminal_observation(row):
            if row.get("controlID") not in expected_control_ids | {"audit-restoration"}:
                raise AuditError("stage refers to an unknown control")
            stages.append(row)
            continue
        status = row.get("classification")
        if status not in TERMINAL:
            raise AuditError(f"invalid observation classification {status!r}")
        if control_id := row.get("controlID"):
            if control_id not in expected_control_ids:
                raise AuditError(f"observation refers to unknown control row {control_id!r}")
            by_control.setdefault(control_id, []).append(row)
    composed_rows: list[dict[str, Any]] = []
    for control in inventory:
        if control["controlID"] in future_ids:
            continue
        matches = by_control.get(control["controlID"], [])
        if control["controlID"].startswith("generation:") and len(matches) > 1:
            raise AuditError(
                f"generation row {control['controlID']!r} was observed more than once; "
                "resume must not retry or overwrite a prior terminal row"
            )
        if matches:
            classification = matches[-1]["classification"]
            evidence = [match.get("evidence") for match in matches if match.get("evidence")]
        else:
            classification = "SKIPPED_AFTER_FAILURE"
            evidence = []
        composed_rows.append(
            {
                "controlID": control["controlID"],
                "scenario": control["scenario"],
                "availability": control["availability"],
                "classification": classification,
                "evidence": evidence,
            }
        )

    counts = {status: 0 for status in sorted(TERMINAL)}
    for row in composed_rows:
        counts[row["classification"]] += 1
    unresolved_required = [
        row
        for row in composed_rows
        if row["availability"] == "required"
        and row["classification"]
        in {"PRODUCT_FAIL", "HARNESS_FAIL", "INFRASTRUCTURE_FAIL", "SKIPPED_AFTER_FAILURE"}
    ]
    limitations = [
        row
        for row in composed_rows
        if row["classification"]
        in {"BLOCKED_PREREQUISITE", "BLOCKED_PRESERVATION_POLICY", "NOT_APPLICABLE"}
    ]
    if unresolved_required:
        result = "failed"
    elif limitations:
        result = "completed-with-limitations"
    else:
        result = "passed"
    summary = {
        "schemaVersion": 1,
        "runID": run_id,
        "sourceIdentity": source_identity,
        "planDigest": plan.get("planDigest"),
        "scenario": scenario,
        "runClassification": (
            "INFRASTRUCTURE_FAIL"
            if bootstrap_classification is not None or external_interruption_classification is not None
            else None
        ),
        "result": result,
        "counts": counts,
        "rows": composed_rows,
    }
    if run_metadata.get("controlObservationSchemaVersion") == 2:
        current_stages = [row for row in stages if row["runID"] == run_id]
        restored = bool(current_stages and current_stages[-1]["phase"] == "restored")
        if shard is not None:
            start, end = shard
            current_ids = {f"generation:{row['takeID']}" for row in plan["takes"][start:end]}
            current_ids.update(row["controlID"] for row in inventory if not row["controlID"].startswith("generation:"))
            # Keep prior/current missing/failed rows visible. Only this explicit
            # bounded shard can succeed; it cannot certify the other 196 takes.
            shard_rows = [row for row in composed_rows if row["controlID"] in current_ids]
            shard_passed = restored and all(row["classification"] == "PASS" for row in shard_rows)
            for control_id in current_ids:
                if not any(row.get("runID") == run_id for row in by_control.get(control_id, [])):
                    shard_passed = False
            summary["shard"] = {"takeStart": start, "takeEndExclusive": end, "result": "passed" if shard_passed else "failed"}
            summary["remainingTakeCount"] = len(plan["takes"]) - end
            summary["unscheduledTakeIDs"] = [take["takeID"] for take in plan["takes"][end:]]
            if future_ids and summary["result"] == "passed":
                summary["result"] = "incomplete"
        summary["restorationObserved"] = restored
        summary["stageObservationCount"] = len(stages)
        if not restored:
            summary["result"] = "failed"
    if bootstrap_classification is not None:
        summary["infrastructureFailure"] = {
            "status": bootstrap_classification["status"],
            "testCaseCount": 0,
            "xcodebuildLogSHA256": bootstrap_classification.get("xcodebuildLogSHA256"),
            "xcresultSummarySHA256": bootstrap_classification.get("xcresultSummarySHA256"),
        }
    if external_interruption_classification is not None:
        summary["infrastructureFailure"] = {
            "status": external_interruption_classification["status"],
            "testCaseCount": external_interruption_classification["testCaseCount"],
            "notificationKind": external_interruption_classification.get("notificationKind"),
            "xcodebuildLogSHA256": external_interruption_classification.get("xcodebuildLogSHA256"),
            "xcresultSummarySHA256": external_interruption_classification.get("xcresultSummarySHA256"),
        }
    summary["summaryDigest"] = digest(summary)
    return summary


def validate_history_ownership(take: dict[str, Any], observation: dict[str, Any]) -> dict[str, Any]:
    """Validate observation-only ownership; matching speech is never authority."""
    binding = observation.get("historyOwnership")
    if not isinstance(binding, dict) or type(binding.get("schemaVersion")) is not int or binding["schemaVersion"] != 1:
        raise AuditError("missing versioned History ownership")
    if set(binding) != {"schemaVersion", "rowID", "beforeRowIDs", "afterRowIDs", "finalRowIDs", "transcriptMatched", "retainedAsSeedCarrier", "pinOwnedByAudit"}:
        raise AuditError("History ownership contains missing or unapproved fields")
    if observation.get("scriptDigest") != take["scriptDigest"]:
        raise AuditError("History ownership script digest mismatch")
    row_id = binding.get("rowID")
    if not isinstance(row_id, str) or not re.fullmatch(r"generation-[1-9][0-9]*", row_id):
        raise AuditError("History ownership requires a persisted row ID")
    sets = {}
    for name in ("beforeRowIDs", "afterRowIDs", "finalRowIDs"):
        values = binding.get(name)
        if not isinstance(values, list) or len(values) > 4096 or any(
            not isinstance(value, str) or not re.fullmatch(r"generation-[1-9][0-9]*", value)
            for value in values
        ) or len(set(values)) != len(values):
            raise AuditError(f"invalid History ownership {name}")
        sets[name] = set(values)
    before, after, final = (sets[name] for name in ("beforeRowIDs", "afterRowIDs", "finalRowIDs"))
    if not before.issubset(after) or after - before != {row_id}:
        raise AuditError("History ownership requires exactly one new row and preserves the baseline")
    if binding.get("transcriptMatched") is not True:
        raise AuditError("History ownership requires exact full-player transcript proof")
    retained = binding.get("retainedAsSeedCarrier")
    if type(retained) is not bool or type(binding.get("pinOwnedByAudit")) is not bool or final != (after if retained else before):
        raise AuditError("History ownership cleanup or carrier preservation mismatch")
    return binding


def validate_device_evidence(
    contract: dict[str, Any],
    plan: dict[str, Any],
    observations: list[dict[str, Any]],
    diagnostics_root: pathlib.Path,
) -> dict[str, Any]:
    """Correlate every visible completed take with its exact engine terminal row."""

    validate_plan(contract, plan)
    planned = {take["takeID"]: take for take in plan["takes"]}
    generation_observations: dict[str, dict[str, Any]] = {}
    seen_generations: set[str] = set()
    seen_history: set[str] = set()
    for observation in observations:
        if not is_terminal_observation(observation):
            continue
        take_id = observation.get("takeID")
        generation_id = observation.get("generationID")
        if not take_id and not generation_id:
            continue
        if observation.get("classification") != "PASS":
            # Blocked or explicitly failed rows are terminal composition
            # evidence, but have no successful engine request to correlate.
            continue
        if take_id not in planned:
            raise AuditError(f"device observation has unknown takeID {take_id!r}")
        if take_id in generation_observations:
            raise AuditError(f"device observations duplicate takeID {take_id}")
        if not isinstance(generation_id, str) or not re.fullmatch(
            r"[0-9A-Fa-f]{8}(?:-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12}", generation_id
        ):
            raise AuditError(f"take {take_id} has no valid generation identity")
        if generation_id.lower() in seen_generations:
            raise AuditError("device observations reuse a generation identity")
        seen_generations.add(generation_id.lower())
        if plan["schemaVersion"] >= 3:
            binding = validate_history_ownership(planned[take_id], observation)
            if binding["rowID"] in seen_history:
                raise AuditError("device observations reuse a History row identity")
            seen_history.add(binding["rowID"])
        generation_observations[take_id] = observation

    engine_rows: dict[str, list[dict[str, Any]]] = {}
    if diagnostics_root.is_dir():
        for path in diagnostics_root.rglob("generations.jsonl"):
            for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
                if not raw.strip():
                    continue
                try:
                    row = json.loads(raw)
                except json.JSONDecodeError as error:
                    raise AuditError(f"invalid engine telemetry {path.name}:{line_number}: {error}") from error
                if row.get("layer") != "engine" or not isinstance(row.get("requestReceipt"), dict):
                    continue
                generation_id = str(row.get("generationID", "")).lower()
                engine_rows.setdefault(generation_id, []).append(row)

    results: list[dict[str, Any]] = []
    model_by_mode = {"custom": "pro_custom", "design": "pro_design", "clone": "pro_clone"}
    for take_id, observation in sorted(generation_observations.items()):
        take = planned[take_id]
        generation_id = observation["generationID"].lower()
        candidates = engine_rows.get(generation_id, [])
        issues: list[str] = []
        if observation.get("schemaVersion") == 2:
            selections = observation.get("observedSelections") or {}
            for key in ("mode", "speaker", "delivery", "language", "variation"):
                if take.get(key) is not None and selections.get(key) != take[key]:
                    issues.append(f"visible_{key}_mismatch")
            if take["mode"] == "clone" and not selections.get("referenceRowID"):
                issues.append("missing_visible_reference")
            player = observation.get("playerEvidence") or {}
            if player.get("playingLabel") != "Pause" or player.get("pausedLabel") != "Play":
                issues.append("missing_playback_transition")
            if player.get("scrubPlaybackLabel") != "Play" or not all(
                isinstance(player.get(key), str) and re.fullmatch(r"[0-9]+:[0-5][0-9]", player[key])
                for key in ("scrubBefore", "scrubAfter")
            ) or player.get("scrubBefore") == player.get("scrubAfter"):
                issues.append("missing_paused_scrub_transition")
        if not candidates:
            issues.append("missing_engine_terminal")
            terminal: dict[str, Any] = {}
            receipt: dict[str, Any] = {}
        else:
            terminal = max(candidates, key=lambda row: row["requestReceipt"].get("retryAttempt", -1))
            receipt = terminal["requestReceipt"]
            expected_receipt = {
                "modelID": model_by_mode[take["mode"]],
                "language": take["language"],
                "variation": take["variation"],
                "streaming": True,
            }
            if take["warmState"] == "cold":
                expected_receipt["warmState"] = "cold"
            if take.get("speaker"):
                expected_receipt["speakerID"] = take["speaker"]
            observed_seed = observation.get("seed")
            if not isinstance(observed_seed, int) or observed_seed < 0:
                issues.append("missing_frozen_seed")
            else:
                expected_receipt["seed"] = observed_seed
            for key, expected in expected_receipt.items():
                if receipt.get(key) != expected:
                    issues.append(f"receipt_{key}_mismatch")
            if take.get("delivery") == "neutral":
                if receipt.get("deliveryID") not in {None, ""}:
                    issues.append("receipt_delivery_mismatch")
            elif take.get("delivery"):
                delivery_id = receipt.get("deliveryID")
                if not isinstance(delivery_id, str) or delivery_id.split(".", 1)[0] != take["delivery"]:
                    issues.append("receipt_delivery_mismatch")
            if terminal.get("mode") != take["mode"]:
                issues.append("engine_mode_mismatch")
            if terminal.get("finishReason") != "eos":
                issues.append("engine_finish_not_eos")
            stages = {
                mark.get("stage") for mark in terminal.get("stageMarks", []) if isinstance(mark, dict)
            }
            if "startup.first_decoded_audio_frame" not in stages:
                issues.append("missing_decoded_audio_boundary")
            if "startup.first_published_stream_chunk" not in stages:
                issues.append("missing_published_audio_boundary")
            notes = terminal.get("notes") if isinstance(terminal.get("notes"), dict) else {}
            if notes.get("promptDigest") != take["scriptDigest"]:
                issues.append("script_digest_mismatch")
            if notes.get("quality_registry_outcome") not in {"pass", "warning"}:
                issues.append("mandatory_quality_gate_failed")
            if (terminal.get("audioQC") or {}).get("verdict") == "fail":
                issues.append("audio_qc_failed")
        results.append(
            {
                "takeID": take_id,
                "generationID": observation["generationID"].lower(),
                "observedWarmState": receipt.get("warmState") if receipt else None,
                "status": "PASS" if not issues else "PRODUCT_FAIL",
                "issues": issues,
            }
        )
        if plan["schemaVersion"] >= 3:
            results[-1]["historyOwnershipDigest"] = digest(observation["historyOwnership"])

    seeds_by_mode: dict[str, set[int]] = {}
    for observation in generation_observations.values():
        seed = observation.get("seed")
        mode = observation.get("mode")
        if isinstance(seed, int) and isinstance(mode, str):
            seeds_by_mode.setdefault(mode, set()).add(seed)
    for mode, seeds in seeds_by_mode.items():
        if len(seeds) != 1:
            for row in results:
                if planned[row["takeID"]]["mode"] == mode:
                    row["status"] = "PRODUCT_FAIL"
                    if "mode_seed_not_frozen" not in row["issues"]:
                        row["issues"].append("mode_seed_not_frozen")

    for mode in sorted({planned[take_id]["mode"] for take_id in generation_observations}):
        ordinary_rows = [
            row for row in results
            if planned[row["takeID"]]["mode"] == mode
            and planned[row["takeID"]]["warmState"] == "observed"
        ]
        if ordinary_rows and not any(row["observedWarmState"] == "warm" for row in ordinary_rows):
            for row in ordinary_rows:
                row["status"] = "PRODUCT_FAIL"
                if "missing_observed_warm_coverage" not in row["issues"]:
                    row["issues"].append("missing_observed_warm_coverage")

    return {
        "schemaVersion": 1,
        "result": "passed" if results and all(row["status"] == "PASS" for row in results) else "failed",
        "planDigest": plan["planDigest"],
        "observedTakeCount": len(results),
        "passingTakeCount": sum(row["status"] == "PASS" for row in results),
        "rows": results,
    }


def prepare_resume(
    run_path: pathlib.Path,
    prior_plan_path: pathlib.Path,
    source_identity: str,
    current_plan_path: pathlib.Path,
    scenario: str,
    observations_path: pathlib.Path,
    correlation_path: pathlib.Path,
    state_path: pathlib.Path,
    prior_output_path: pathlib.Path,
) -> dict[str, Any]:
    """Validate a retained run and select the first safe continuation row.

    A failed take that emitted a terminal observation is already represented and
    must not cause the following, unattempted take to be skipped.  Conversely, a
    failed run with no terminal observation for its in-flight take must advance
    past that take so a resume never becomes an implicit retry.  Version-1
    resume artifacts are accepted so campaigns started by the original runner
    can continue without rewriting retained evidence.
    """

    if not run_path.is_file() or not prior_plan_path.is_file():
        raise AuditError("prior run is missing run.json or control-audit-plan.json")
    if not observations_path.is_file():
        raise AuditError("prior run is missing composed control observations")
    run = load_json(run_path)
    prior = load_json(prior_plan_path)
    current = load_json(current_plan_path)
    if run.get("runID") != run_path.parent.name:
        raise AuditError("prior run directory and runID disagree")
    if run.get("treeFingerprint") != source_identity:
        raise AuditError("prior run source fingerprint differs")
    if prior.get("sourceIdentity") != source_identity:
        raise AuditError("prior plan source fingerprint differs")
    if prior.get("planDigest") != current.get("planDigest"):
        raise AuditError("prior and current immutable plans differ")
    if run.get("controlAuditScenario") != scenario:
        raise AuditError("prior and current control-audit scenarios differ")

    stream = ordered_observations(_read_jsonl(observations_path))
    rows = [row for row in stream if is_terminal_observation(row)]
    if run.get("controlObservationSchemaVersion") == 2:
        current_stages = [row for row in stream if row.get("runID") == run["runID"] and not is_terminal_observation(row)]
        if not current_stages or current_stages[-1].get("phase") != "restored":
            raise AuditError("resume requires collected restoration evidence")
        terminal_takes = {row.get("takeID") for row in rows}
        if any(row.get("takeID") and row["takeID"] not in terminal_takes for row in current_stages):
            raise AuditError("in-flight stage has no terminal observation; manual forensic reconciliation required")
    if current.get("schemaVersion", 1) >= 3:
        validate_plan(load_contract(), current)
        validate_plan(load_contract(), prior)
        if not any(row.get("takeID") for row in rows):
            raise AuditError("zero-observation generation run cannot resume")
    generation_ids = [f"generation:{take['takeID']}" for take in current["takes"]]
    generation_id_set = set(generation_ids)
    represented_rows: dict[str, dict[str, Any]] = {}
    for row in rows:
        control_id = row.get("controlID")
        if control_id not in generation_id_set:
            continue
        if control_id in represented_rows:
            raise AuditError(f"prior generation row {control_id!r} was observed more than once")
        represented_rows[control_id] = row

    skipped_ids: set[str] = set()
    prior_state_path = run_path.parent / "control-resume-state.json"
    if prior_state_path.is_file():
        prior_state = load_json(prior_state_path)
        state_version = prior_state.get("schemaVersion")
        if state_version == 1:
            skipped = prior_state.get("skippedAfterFailure")
            if skipped:
                skipped_ids.add(skipped)
        elif state_version == 2:
            values = prior_state.get("skippedAfterFailures", [])
            if not isinstance(values, list) or any(not isinstance(value, str) for value in values):
                raise AuditError("resume skippedAfterFailures must be an array of strings")
            skipped_ids.update(values)
        else:
            raise AuditError("unsupported control resume-state schema")
    if not skipped_ids.issubset(generation_id_set):
        raise AuditError("resume state refers to an unknown skipped generation row")
    if skipped_ids & set(represented_rows):
        raise AuditError("a generation row cannot be both observed and skipped")

    terminal_ids = set(represented_rows) | skipped_ids
    contiguous = 0
    while contiguous < len(generation_ids) and generation_ids[contiguous] in terminal_ids:
        contiguous += 1
    if any(control_id in terminal_ids for control_id in generation_ids[contiguous + 1 :]):
        raise AuditError("prior generation evidence contains a non-contiguous gap")

    successful_generation = [
        row for row in rows
        if row.get("controlID", "").startswith("generation:")
        and row.get("classification") == "PASS"
    ]
    carriers: list[dict[str, Any]] = []
    if successful_generation:
        if not correlation_path.is_file():
            raise AuditError("prior successful generation rows have no device-correlation report")
        correlation = load_json(correlation_path)
        if correlation.get("result") != "passed":
            raise AuditError("prior successful generation evidence did not pass correlation")
        if current.get("schemaVersion", 1) >= 3:
            allowed_runs = set(run.get("resumeRunIDs", [])) | {run["runID"]}
            planned = {take["takeID"]: take for take in current["takes"]}
            if correlation.get("planDigest") != current["planDigest"]:
                raise AuditError("resume correlation plan identity mismatch")
            correlations = {run["runID"]: correlation}
            modes: set[str] = set()
            history_ids: set[str] = set()
            generation_ids_seen: set[str] = set()
            for observation in successful_generation:
                take = planned.get(observation.get("takeID"))
                if take is None or observation.get("runID") not in allowed_runs or observation.get("sourceIdentity") != source_identity:
                    raise AuditError("resume History ownership crosses run/source identity")
                origin = observation["runID"]
                if origin not in correlations:
                    if not isinstance(origin, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", origin):
                        raise AuditError("unsafe resume run identity")
                    origin_root = run_path.parent.parent / origin
                    origin_metadata = load_json(origin_root / "run.json")
                    origin_plan = load_json(origin_root / "control-audit-plan.json")
                    if origin_metadata.get("runID") != origin or origin_metadata.get("treeFingerprint") != source_identity or origin_plan != current:
                        raise AuditError("original resume evidence crosses source/plan identity")
                    correlations[origin] = load_json(origin_root / "control-audit-generation-correlation.json")
                origin_proof = correlations[origin]
                if origin_proof.get("result") != "passed" or origin_proof.get("planDigest") != current["planDigest"]:
                    raise AuditError("original resume correlation did not pass for this plan")
                correlated = {row["takeID"]: row for row in origin_proof.get("rows", [])}
                binding = validate_history_ownership(take, observation)
                proof = correlated.get(take["takeID"], {})
                generation_id = str(observation.get("generationID", "")).lower()
                if not re.fullmatch(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", generation_id) or proof.get("status") != "PASS" or proof.get("generationID") != generation_id or proof.get("historyOwnershipDigest") != digest(binding):
                    raise AuditError("resume History ownership has no exact correlated generation")
                if binding["rowID"] in history_ids or generation_id in generation_ids_seen:
                    raise AuditError("resume reuses History or generation identity")
                history_ids.add(binding["rowID"])
                generation_ids_seen.add(generation_id)
                seed = observation.get("seed")
                if type(seed) is not int or not 0 <= seed <= 2**64 - 1:
                    raise AuditError("resume carrier seed must be an exact UInt64")
                if binding["retainedAsSeedCarrier"]:
                    if take["mode"] in modes:
                        raise AuditError("resume has multiple retained carriers for a mode")
                    modes.add(take["mode"])
                    carriers.append({
                        "takeID": take["takeID"], "mode": take["mode"],
                        "rowID": binding["rowID"], "seed": seed,
                        "generationID": generation_id, "scriptDigest": take["scriptDigest"],
                        "pinOwnedByAudit": binding["pinOwnedByAudit"],
                    })

    newly_skipped = None
    start = contiguous
    if run.get("status") not in {"passed", "diagnosedFailure"} and start < len(generation_ids):
        current_run_id = run["runID"]
        represented_failure = any(
            row.get("runID") == current_run_id
            and row.get("controlID") == generation_ids[start - 1]
            and row.get("classification")
            in {"PRODUCT_FAIL", "HARNESS_FAIL", "INFRASTRUCTURE_FAIL"}
            for row in rows
        ) if start > 0 else False
        shard = generation_shard(run, current)
        at_shard_boundary = shard is not None and start == shard[1]
        if not represented_failure and not at_shard_boundary:
            if run.get("controlObservationSchemaVersion") == 2:
                raise AuditError("failed shard has no safe terminal boundary")
            newly_skipped = generation_ids[start]
            skipped_ids.add(newly_skipped)
            start += 1
    if start >= len(generation_ids):
        raise AuditError("prior run leaves no generation take to resume")

    chain = list(run.get("resumeRunIDs", []))
    chain.append(run["runID"])
    if len(chain) != len(set(chain)):
        raise AuditError("resume chain contains a duplicate run ID")
    prior_output_path.parent.mkdir(parents=True, exist_ok=True)
    prior_output_path.write_text(observations_path.read_text(encoding="utf-8"), encoding="utf-8")
    ordered_skips = [control_id for control_id in generation_ids if control_id in skipped_ids]
    state = {
        "schemaVersion": 2,
        "resumeRunIDs": chain,
        "takeStart": start,
        "representedTakeCount": len(represented_rows),
        "terminalTakeCount": contiguous + (1 if newly_skipped else 0),
        "skippedAfterFailure": newly_skipped,
        "skippedAfterFailures": ordered_skips,
    }
    if current.get("schemaVersion", 1) >= 3:
        state["seedCarriers"] = carriers
    atomic_write_json(state_path, state)
    return state


def atomic_write_json(path: pathlib.Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.next")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate_parser = subparsers.add_parser("validate")
    validate_parser.add_argument("--output", type=pathlib.Path)

    plan_parser = subparsers.add_parser("generate-plan")
    plan_parser.add_argument("--output", type=pathlib.Path, required=True)
    plan_parser.add_argument("--source-identity")

    encode_parser = subparsers.add_parser("encode-plan")
    encode_parser.add_argument("--plan", type=pathlib.Path, required=True)
    encode_parser.add_argument("--output", type=pathlib.Path, required=True)

    collect_parser = subparsers.add_parser("collect-observations")
    collect_parser.add_argument("--manifest", type=pathlib.Path, required=True)
    collect_parser.add_argument("--attachments", type=pathlib.Path, required=True)
    collect_parser.add_argument("--output", type=pathlib.Path, required=True)

    compose_parser = subparsers.add_parser("compose")
    compose_parser.add_argument("--run-metadata", type=pathlib.Path, required=True)
    compose_parser.add_argument("--plan", type=pathlib.Path, required=True)
    compose_parser.add_argument("--observations", type=pathlib.Path, required=True)
    compose_parser.add_argument("--bootstrap-classification", type=pathlib.Path)
    compose_parser.add_argument("--external-interruption-classification", type=pathlib.Path)
    compose_parser.add_argument("--output", type=pathlib.Path, required=True)

    device_parser = subparsers.add_parser("validate-device")
    device_parser.add_argument("--plan", type=pathlib.Path, required=True)
    device_parser.add_argument("--observations", type=pathlib.Path, required=True)
    device_parser.add_argument("--diagnostics", type=pathlib.Path, required=True)
    device_parser.add_argument("--output", type=pathlib.Path, required=True)

    resume_parser = subparsers.add_parser("prepare-resume")
    resume_parser.add_argument("--run-metadata", type=pathlib.Path, required=True)
    resume_parser.add_argument("--prior-plan", type=pathlib.Path, required=True)
    resume_parser.add_argument("--source-identity", required=True)
    resume_parser.add_argument("--current-plan", type=pathlib.Path, required=True)
    resume_parser.add_argument("--scenario", required=True)
    resume_parser.add_argument("--observations", type=pathlib.Path, required=True)
    resume_parser.add_argument("--correlation", type=pathlib.Path, required=True)
    resume_parser.add_argument("--state-output", type=pathlib.Path, required=True)
    resume_parser.add_argument("--observations-output", type=pathlib.Path, required=True)

    arguments = parser.parse_args()
    try:
        contract = load_contract()
        if arguments.command == "validate":
            report = validate_contract(contract)
            if arguments.output:
                atomic_write_json(arguments.output, report)
            print(json.dumps(report, indent=2, sort_keys=True))
            return 0 if report["result"] == "passed" else 1
        if arguments.command == "generate-plan":
            plan = generate_plan(contract, arguments.source_identity)
            atomic_write_json(arguments.output, plan)
            print(arguments.output)
            return 0
        if arguments.command == "encode-plan":
            encoded = encode_plan(contract, load_json(arguments.plan))
            arguments.output.parent.mkdir(parents=True, exist_ok=True)
            arguments.output.write_text(encoded + "\n", encoding="ascii")
            print(arguments.output)
            return 0
        if arguments.command == "collect-observations":
            rows = collect_observations(
                arguments.manifest,
                arguments.attachments,
                arguments.output,
            )
            print(f"collected {len(rows)} control observations")
            return 0
        if arguments.command == "compose":
            summary = compose(
                contract,
                load_json(arguments.run_metadata),
                load_json(arguments.plan),
                _read_jsonl(arguments.observations),
                (
                    load_json(arguments.bootstrap_classification)
                    if arguments.bootstrap_classification
                    else None
                ),
                (
                    load_json(arguments.external_interruption_classification)
                    if arguments.external_interruption_classification
                    else None
                ),
            )
            atomic_write_json(arguments.output, summary)
            print(arguments.output)
            return 0 if summary.get("shard", {}).get("result", summary["result"]) in {"passed", "completed-with-limitations"} else 1
        if arguments.command == "validate-device":
            report = validate_device_evidence(
                contract,
                load_json(arguments.plan),
                _read_jsonl(arguments.observations),
                arguments.diagnostics,
            )
            atomic_write_json(arguments.output, report)
            print(arguments.output)
            return 0 if report["result"] == "passed" else 1
        if arguments.command == "prepare-resume":
            state = prepare_resume(
                arguments.run_metadata,
                arguments.prior_plan,
                arguments.source_identity,
                arguments.current_plan,
                arguments.scenario,
                arguments.observations,
                arguments.correlation,
                arguments.state_output,
                arguments.observations_output,
            )
            print(
                f"resume identity accepted from {state['resumeRunIDs'][-1]}; "
                f"starting take index {state['takeStart']}"
            )
            return 0
    except AuditError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
