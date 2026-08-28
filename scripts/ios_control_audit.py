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
    for path in sorted((root / "Sources/iOS").rglob("*.swift")):
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


def generate_plan(contract: dict[str, Any], source_identity: str | None = None) -> dict[str, Any]:
    resolved = catalogs()
    corpus = load_json(ROOT / "config/ios-control-audit-corpus.json")
    scripts = corpus.get("scripts", {})
    if set(scripts) != set(resolved["languages"]):
        missing = sorted(set(resolved["languages"]) - set(scripts))
        extra = sorted(set(scripts) - set(resolved["languages"]))
        raise AuditError(f"control-audit corpus language drift (missing={missing}, extra={extra})")
    rows: list[dict[str, Any]] = []
    search_token_value = int(contract["generationMatrix"]["searchTokenBase"])
    for mode, mode_contract in contract["generationMatrix"]["modes"].items():
        dimensions = _expand_dimensions(mode_contract["dimensions"], resolved)
        mode_rows = all_pairs_rows(dimensions, mode_contract["coldSentinel"])
        for index, values in enumerate(mode_rows):
            language = values["language"]
            length = values["length"]
            script = scripts[language].get(length)
            if not isinstance(script, str) or not script.strip():
                raise AuditError(f"missing {language}/{length} control-audit script")
            search_token = str(search_token_value)
            rendered_script = f"{script} {search_token}."
            row = {
                "takeID": f"{mode}-{index + 1:03d}",
                "mode": mode,
                "warmState": "cold" if index == 0 else "warm",
                **values,
                "script": rendered_script,
                "scriptDigest": hashlib.sha256(rendered_script.encode("utf-8")).hexdigest(),
                "searchToken": search_token,
            }
            row["rowDigest"] = digest(row)
            rows.append(row)
            search_token_value += 1
    maximum = int(contract["generationMatrix"]["maxRows"])
    if len(rows) > maximum:
        raise AuditError(f"all-pairs matrix needs {len(rows)} rows, exceeding maxRows {maximum}")
    payload = {
        "schemaVersion": 1,
        "sourceIdentity": source_identity or tree_fingerprint(),
        "contractDigest": digest(contract),
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
    expected = generate_plan(contract, source_identity)
    if plan != expected:
        raise AuditError("control-audit plan does not match the deterministic source-bound plan")


def encode_plan(contract: dict[str, Any], plan: dict[str, Any]) -> str:
    validate_plan(contract, plan)
    compressed = zlib.compress(canonical_bytes(plan), level=9)
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


def compose(
    contract: dict[str, Any],
    run_metadata: dict[str, Any],
    plan: dict[str, Any],
    observations: list[dict[str, Any]],
) -> dict[str, Any]:
    validate_plan(contract, plan)
    run_id = run_metadata.get("runID")
    source_identity = run_metadata.get("treeFingerprint") or run_metadata.get("sourceIdentity")
    if not run_id or not source_identity:
        raise AuditError("run metadata must contain runID and treeFingerprint/sourceIdentity")
    if plan.get("sourceIdentity") != source_identity:
        raise AuditError("generation plan source identity does not match the device run")

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
            # Accessibility is a cross-cutting proof and therefore retains the
            # whole control inventory, but not generation rows.
            inventory = [row for row in inventory if not row["controlID"].startswith("generation:")]
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
    for row in observations:
        if row.get("runID") not in accepted_run_ids:
            raise AuditError("cross-run observation rejected")
        if row.get("sourceIdentity") != source_identity:
            raise AuditError("cross-source observation rejected")
        status = row.get("classification")
        if status not in TERMINAL:
            raise AuditError(f"invalid observation classification {status!r}")
        if control_id := row.get("controlID"):
            if control_id not in expected_control_ids:
                raise AuditError(f"observation refers to unknown control row {control_id!r}")
            by_control.setdefault(control_id, []).append(row)
    composed_rows: list[dict[str, Any]] = []
    for control in inventory:
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
        "result": result,
        "counts": counts,
        "rows": composed_rows,
    }
    summary["summaryDigest"] = digest(summary)
    return summary


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
    for observation in observations:
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
                "warmState": take["warmState"],
                "streaming": True,
            }
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
            if take.get("delivery"):
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
                "status": "PASS" if not issues else "PRODUCT_FAIL",
                "issues": issues,
            }
        )

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

    return {
        "schemaVersion": 1,
        "result": "passed" if results and all(row["status"] == "PASS" for row in results) else "failed",
        "planDigest": plan["planDigest"],
        "observedTakeCount": len(results),
        "passingTakeCount": sum(row["status"] == "PASS" for row in results),
        "rows": results,
    }


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

    compose_parser = subparsers.add_parser("compose")
    compose_parser.add_argument("--run-metadata", type=pathlib.Path, required=True)
    compose_parser.add_argument("--plan", type=pathlib.Path, required=True)
    compose_parser.add_argument("--observations", type=pathlib.Path, required=True)
    compose_parser.add_argument("--output", type=pathlib.Path, required=True)

    device_parser = subparsers.add_parser("validate-device")
    device_parser.add_argument("--plan", type=pathlib.Path, required=True)
    device_parser.add_argument("--observations", type=pathlib.Path, required=True)
    device_parser.add_argument("--diagnostics", type=pathlib.Path, required=True)
    device_parser.add_argument("--output", type=pathlib.Path, required=True)

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
        if arguments.command == "compose":
            summary = compose(
                contract,
                load_json(arguments.run_metadata),
                load_json(arguments.plan),
                _read_jsonl(arguments.observations),
            )
            atomic_write_json(arguments.output, summary)
            print(arguments.output)
            return 0 if summary["result"] in {"passed", "completed-with-limitations"} else 1
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
    except AuditError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
