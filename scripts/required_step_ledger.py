#!/usr/bin/env python3
"""Fail-closed required-step ledgers for authoritative repository workflows."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import signal
import subprocess
import tempfile
from typing import Any
from lib import jsonio  # noqa: E402


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONTRACT = ROOT / "config" / "orchestration-contract.json"
STEP_ID = re.compile(r"^[a-z][a-z0-9-]{0,63}$")
WORKFLOW_ID = re.compile(r"^[a-z][a-z0-9-]{0,95}$")
TEMPLATE_ID = re.compile(r"^[a-z][a-z0-9-]{0,95}$")
COMMAND_DIGEST = re.compile(r"^[0-9a-f]{64}$")


class LedgerError(ValueError):
    pass


class ManagedTermination(BaseException):
    """Raised by the narrow signal handler while a managed child is active."""

    def __init__(self, signum: int) -> None:
        self.signum = signum


utc_now = jsonio.utc_now


def load_json(path: Path) -> dict[str, Any]:
    return jsonio.load_json(path, error=LedgerError)


def atomic_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def canonical_bytes(value: Any) -> bytes:
    return jsonio.canonical_bytes(value, newline=True, allow_nan=True)


def payload_digest(payload: dict[str, Any], *, digest_field: str | None = None) -> str:
    unsigned = dict(payload)
    if digest_field is not None:
        unsigned.pop(digest_field, None)
    return hashlib.sha256(canonical_bytes(unsigned)).hexdigest()


file_digest = jsonio.sha256_file


def source_identity_digest(path: Path) -> str:
    payload = load_json(path)
    claimed = payload.get("identityDigest")
    if not isinstance(claimed, str) or not re.fullmatch(r"[0-9a-f]{64}", claimed):
        raise LedgerError("source identity has no valid identityDigest")
    if payload_digest(payload, digest_field="identityDigest") != claimed:
        raise LedgerError("source identity digest does not match its canonical content")
    return claimed


def _normalized_command_token(value: str) -> str:
    """Normalize formatting-only shell whitespace without changing token content."""
    return " ".join(re.sub(r"\\\r?\n", " ", value).split())


def command_template_digest(template: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_bytes(template)).hexdigest()


def workflow_command_contract_digest(workflow: dict[str, Any]) -> str | None:
    templates = workflow.get("commandTemplates")
    if templates is None:
        return None
    return hashlib.sha256(canonical_bytes({"commandTemplates": templates})).hexdigest()


def _validate_command_templates(workflow_id: str, workflow: dict[str, Any]) -> None:
    templates = workflow.get("commandTemplates")
    declared_steps = set(workflow["requiredSteps"] + workflow.get("optionalSteps", []))
    if templates is None:
        if workflow.get("sourceIdentityRequired", False):
            raise LedgerError(f"workflow {workflow_id} requires commandTemplates for every managed step")
        return
    if not isinstance(templates, dict) or set(templates) != declared_steps:
        raise LedgerError(f"workflow {workflow_id} commandTemplates must exactly cover every declared step")
    template_ids: set[str] = set()
    template_digests: set[str] = set()
    for step, variants in templates.items():
        if not isinstance(variants, list) or not variants:
            raise LedgerError(f"workflow {workflow_id} step {step} requires at least one command template")
        for variant in variants:
            if not isinstance(variant, dict) or not {"id", "argv"} <= set(variant) or set(variant) - {
                "id", "argv", "outputs"
            }:
                raise LedgerError(f"workflow {workflow_id} step {step} has a malformed command template")
            template_id = variant.get("id")
            argv = variant.get("argv")
            if not isinstance(template_id, str) or not TEMPLATE_ID.fullmatch(template_id):
                raise LedgerError(f"workflow {workflow_id} step {step} has an invalid command template id")
            if template_id in template_ids:
                raise LedgerError(f"workflow {workflow_id} contains duplicate command template id {template_id}")
            template_ids.add(template_id)
            digest = command_template_digest(variant)
            if digest in template_digests:
                raise LedgerError(f"workflow {workflow_id} contains duplicate command templates")
            template_digests.add(digest)
            if not isinstance(argv, list) or not argv:
                raise LedgerError(f"workflow {workflow_id} template {template_id} has no argv")
            for matcher in argv:
                if isinstance(matcher, str):
                    if not matcher:
                        raise LedgerError(f"workflow {workflow_id} template {template_id} has an empty argv token")
                    continue
                if not isinstance(matcher, dict) or len(matcher) != 1:
                    raise LedgerError(f"workflow {workflow_id} template {template_id} has a malformed argv matcher")
                kind, value = next(iter(matcher.items()))
                if kind not in {"pattern", "normalized"} or not isinstance(value, str) or not value:
                    raise LedgerError(f"workflow {workflow_id} template {template_id} has an invalid argv matcher")
                if kind == "pattern":
                    try:
                        re.compile(value)
                    except re.error as error:
                        raise LedgerError(
                            f"workflow {workflow_id} template {template_id} has an invalid argv pattern: {error}"
                        ) from error
            outputs = variant.get("outputs", [])
            if (
                not isinstance(outputs, list)
                or len(outputs) != len(set(outputs))
                or any(
                    not isinstance(value, str)
                    or not value
                    or value.startswith("/")
                    or ".." in Path(value).parts
                    for value in outputs
                )
            ):
                raise LedgerError(f"workflow {workflow_id} template {template_id} has invalid output paths")


def validate_contract_payload(
    contract: dict[str, Any], *, root: Path | None = ROOT
) -> dict[str, Any]:
    if contract.get("schemaVersion") != 1:
        raise LedgerError("orchestration contract schemaVersion must be 1")
    workflows = contract.get("workflows")
    if not isinstance(workflows, dict) or not workflows:
        raise LedgerError("orchestration contract requires non-empty workflows")
    for workflow_id, workflow in workflows.items():
        if not isinstance(workflow_id, str) or not WORKFLOW_ID.fullmatch(workflow_id):
            raise LedgerError(f"invalid workflow id: {workflow_id!r}")
        if not isinstance(workflow, dict):
            raise LedgerError(f"workflow {workflow_id} must be an object")
        producer = workflow.get("producer")
        if not isinstance(producer, str) or producer.startswith("/") or ".." in Path(producer).parts:
            raise LedgerError(f"workflow {workflow_id} has an unsafe producer path")
        if root is not None and not (root / producer).is_file():
            raise LedgerError(f"workflow {workflow_id} producer is missing: {producer}")
        required = workflow.get("requiredSteps")
        optional = workflow.get("optionalSteps", [])
        if not isinstance(required, list) or not required:
            raise LedgerError(f"workflow {workflow_id} requires at least one required step")
        if not isinstance(optional, list):
            raise LedgerError(f"workflow {workflow_id} optionalSteps must be an array")
        steps = required + optional
        if any(not isinstance(step, str) or not STEP_ID.fullmatch(step) for step in steps):
            raise LedgerError(f"workflow {workflow_id} contains an invalid step id")
        if len(steps) != len(set(steps)):
            raise LedgerError(f"workflow {workflow_id} contains duplicate step ids")
        source_required = workflow.get("sourceIdentityRequired", False)
        if not isinstance(source_required, bool):
            raise LedgerError(f"workflow {workflow_id} sourceIdentityRequired must be boolean")
        _validate_command_templates(workflow_id, workflow)
    fault = contract.get("faultInjection")
    if not isinstance(fault, dict):
        raise LedgerError("orchestration contract requires faultInjection settings")
    for key in ("enableEnvironmentVariable", "stepEnvironmentVariable"):
        value = fault.get(key)
        if not isinstance(value, str) or not re.fullmatch(r"[A-Z][A-Z0-9_]+", value):
            raise LedgerError(f"faultInjection.{key} must be an environment variable name")
    return contract


def validated_contract(path: Path, *, root: Path = ROOT) -> dict[str, Any]:
    return validate_contract_payload(load_json(path), root=root)


def _template_matches(template: dict[str, Any], command: list[str]) -> bool:
    matchers = template["argv"]
    if len(matchers) != len(command):
        return False
    for matcher, value in zip(matchers, command):
        if isinstance(matcher, str):
            if value != matcher:
                return False
            continue
        kind, expected = next(iter(matcher.items()))
        if kind == "pattern" and re.fullmatch(expected, value) is None:
            return False
        if kind == "normalized" and _normalized_command_token(value) != _normalized_command_token(expected):
            return False
    return True


def bind_command(workflow: dict[str, Any], step: str, command: list[str]) -> dict[str, str] | None:
    templates = workflow.get("commandTemplates")
    if templates is None:
        return None
    matches = [template for template in templates[step] if _template_matches(template, command)]
    if not matches:
        raise LedgerError(f"managed command does not match the contract template for step {step}")
    if len(matches) != 1:
        raise LedgerError(f"managed command ambiguously matches multiple templates for step {step}")
    template = matches[0]
    contract_digest = workflow_command_contract_digest(workflow)
    assert contract_digest is not None
    return {
        "commandTemplateID": template["id"],
        "commandTemplateDigest": command_template_digest(template),
        "commandContractDigest": contract_digest,
        "declaredOutputs": list(template.get("outputs", [])),
    }


def _capture_declared_outputs(paths: list[str], cwd: Path | None) -> list[dict[str, Any]]:
    root = (cwd or Path.cwd()).resolve()
    captured: list[dict[str, Any]] = []
    for relative in paths:
        unresolved = root / relative
        if unresolved.is_symlink():
            raise LedgerError(f"declared managed-step output must not be a symlink: {relative}")
        resolved = unresolved.resolve()
        try:
            resolved.relative_to(root)
        except ValueError as error:
            raise LedgerError(f"declared managed-step output escapes its working directory: {relative}") from error
        if not resolved.is_file():
            raise LedgerError(f"declared managed-step output is missing: {relative}")
        captured.append({
            "path": relative,
            "bytes": resolved.stat().st_size,
            "sha256": file_digest(resolved),
        })
    return captured


def workflow_definition(contract: dict[str, Any], workflow_id: str) -> dict[str, Any]:
    workflow = contract["workflows"].get(workflow_id)
    if not isinstance(workflow, dict):
        raise LedgerError(f"unknown workflow: {workflow_id}")
    return workflow


def validate_ledger(payload: dict[str, Any]) -> None:
    if payload.get("schemaVersion") != 1:
        raise LedgerError("ledger schemaVersion must be 1")
    if not isinstance(payload.get("workflow"), str) or not isinstance(payload.get("runID"), str):
        raise LedgerError("ledger identity is incomplete")
    if not isinstance(payload.get("invocationID"), str) or not re.fullmatch(r"[0-9a-f]{32}", payload["invocationID"]):
        raise LedgerError("ledger invocation identity is missing or malformed")
    source_digest = payload.get("sourceIdentityDigest")
    if source_digest is not None and (
        not isinstance(source_digest, str) or not re.fullmatch(r"[0-9a-f]{64}", source_digest)
    ):
        raise LedgerError("ledger source identity digest is malformed")
    command_contract_digest = payload.get("commandContractDigest")
    if command_contract_digest is not None and (
        not isinstance(command_contract_digest, str) or not COMMAND_DIGEST.fullmatch(command_contract_digest)
    ):
        raise LedgerError("ledger command contract digest is malformed")
    expected = payload.get("expectedSteps")
    results = payload.get("results")
    if not isinstance(expected, list) or not isinstance(results, dict):
        raise LedgerError("ledger step state is malformed")
    identifiers = []
    for entry in expected:
        if not isinstance(entry, dict) or not isinstance(entry.get("id"), str):
            raise LedgerError("ledger expected step is malformed")
        if not isinstance(entry.get("required"), bool):
            raise LedgerError("ledger expected step is missing required status")
        identifiers.append(entry["id"])
    if len(identifiers) != len(set(identifiers)):
        raise LedgerError("ledger contains duplicate expected steps")
    if set(results) - set(identifiers):
        raise LedgerError("ledger contains a result for an unknown step")

    for step, result in results.items():
        if not isinstance(result, dict):
            raise LedgerError(f"ledger result for {step} is malformed")
        if result.get("status") not in {"passed", "failed"}:
            raise LedgerError(f"ledger result for {step} has an invalid status")
        if not isinstance(result.get("exitCode"), int):
            raise LedgerError(f"ledger result for {step} has no integer exit code")
        if result.get("executionMode") not in {"managed-subprocess", "reported-exit-code"}:
            raise LedgerError(f"ledger result for {step} has an invalid execution mode")


def initialize(
    path: Path,
    contract_path: Path,
    workflow_id: str,
    run_id: str,
    source_identity: Path | None = None,
) -> None:
    if path.exists():
        raise LedgerError(f"refusing to replace existing step ledger: {path}")
    contract = validated_contract(contract_path)
    workflow = workflow_definition(contract, workflow_id)
    if workflow.get("sourceIdentityRequired", False) and source_identity is None:
        raise LedgerError(f"workflow {workflow_id} requires a source identity manifest")
    identity_digest = source_identity_digest(source_identity) if source_identity is not None else None
    command_contract_digest = workflow_command_contract_digest(workflow)
    expected = [
        *({"id": step, "required": True} for step in workflow["requiredSteps"]),
        *({"id": step, "required": False} for step in workflow.get("optionalSteps", [])),
    ]
    atomic_write(path, {
        "schemaVersion": 1,
        "workflow": workflow_id,
        "runID": run_id,
        "invocationID": secrets.token_hex(16),
        "sourceIdentityDigest": identity_digest,
        "commandContractDigest": command_contract_digest,
        "status": "running",
        "startedAt": utc_now(),
        "completedAt": None,
        "expectedSteps": expected,
        "results": {},
        "missingRequiredSteps": [entry["id"] for entry in expected if entry["required"]],
    })


def record(path: Path, step: str, exit_code: int) -> None:
    payload = load_json(path)
    validate_ledger(payload)
    if payload.get("status") != "running":
        raise LedgerError("cannot record a step after ledger finalization")
    expected = {entry["id"]: entry for entry in payload["expectedSteps"]}
    if step not in expected:
        raise LedgerError(f"step {step!r} is not declared for workflow {payload['workflow']}")
    if step in payload["results"]:
        raise LedgerError(f"step {step!r} already has a terminal result")
    payload["results"][step] = {
        "status": "passed" if exit_code == 0 else "failed",
        "exitCode": exit_code,
        "required": expected[step]["required"],
        "executionMode": "reported-exit-code",
        "completedAt": utc_now(),
    }
    payload["missingRequiredSteps"] = [
        entry["id"] for entry in payload["expectedSteps"]
        if entry["required"] and entry["id"] not in payload["results"]
    ]
    atomic_write(path, payload)


def _stop_process_group(process: subprocess.Popen[Any], first_signal: int = signal.SIGTERM) -> None:
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, first_signal)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait()


def run_managed_step(
    path: Path,
    contract_path: Path,
    step: str,
    command: list[str],
    timeout_seconds: int,
    cwd: Path | None,
) -> int:
    if not command:
        raise LedgerError("managed step requires a command after --")
    if timeout_seconds < 1:
        raise LedgerError("managed step timeout must be at least one second")
    payload = load_json(path)
    validate_ledger(payload)
    if payload.get("status") != "running":
        raise LedgerError("cannot run a step after ledger finalization")
    expected = {entry["id"]: entry for entry in payload["expectedSteps"]}
    if step not in expected:
        raise LedgerError(f"step {step!r} is not declared for workflow {payload['workflow']}")
    if step in payload["results"]:
        raise LedgerError(f"step {step!r} already has a terminal result")

    contract = validated_contract(contract_path)
    workflow = workflow_definition(contract, payload["workflow"])
    expected_command_contract_digest = workflow_command_contract_digest(workflow)
    if payload.get("commandContractDigest") != expected_command_contract_digest:
        raise LedgerError("ledger command contract differs from the current orchestration contract")
    command_binding = bind_command(workflow, step, command)
    declared_outputs = [] if command_binding is None else command_binding.pop("declaredOutputs")

    manifest_relative = Path("steps") / f"{step}.json"
    manifest_path = path.parent / manifest_relative
    if manifest_path.exists():
        raise LedgerError(f"refusing to replace existing step manifest: {manifest_path}")

    started_at = utc_now()
    command_digest = hashlib.sha256(canonical_bytes(command)).hexdigest()
    process: subprocess.Popen[Any] | None = None
    outcome = "failed"
    exit_code = 1
    terminating_signal: int | None = None
    previous_handlers: dict[int, Any] = {}

    def handle_signal(signum: int, _frame: Any) -> None:
        raise ManagedTermination(signum)

    for signum in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        previous_handlers[signum] = signal.getsignal(signum)
        signal.signal(signum, handle_signal)
    try:
        process = subprocess.Popen(command, cwd=cwd, start_new_session=True)
        try:
            exit_code = process.wait(timeout=timeout_seconds)
            outcome = "completed" if exit_code == 0 else "failed"
        except subprocess.TimeoutExpired:
            outcome = "timeout"
            exit_code = 124
            _stop_process_group(process)
        except ManagedTermination as termination:
            outcome = "terminated"
            terminating_signal = termination.signum
            exit_code = 128 + termination.signum
            _stop_process_group(process)
    finally:
        for signum, previous in previous_handlers.items():
            signal.signal(signum, previous)

    captured_outputs: list[dict[str, Any]] = []
    output_error: LedgerError | None = None
    if outcome == "completed" and exit_code == 0:
        try:
            captured_outputs = _capture_declared_outputs(declared_outputs, cwd)
        except LedgerError as error:
            output_error = error
            outcome = "output-validation-failed"
            exit_code = 125

    completed_at = utc_now()
    manifest: dict[str, Any] = {
        "schemaVersion": 1,
        "workflow": payload["workflow"],
        "runID": payload["runID"],
        "invocationID": payload["invocationID"],
        "step": step,
        "sourceIdentityDigest": payload.get("sourceIdentityDigest"),
        "commandDigest": command_digest,
        "timeoutSeconds": timeout_seconds,
        "startedAt": started_at,
        "completedAt": completed_at,
        "outcome": outcome,
        "exitCode": exit_code,
    }
    if command_binding is not None:
        manifest.update(command_binding)
        manifest["outputs"] = captured_outputs
    if terminating_signal is not None:
        manifest["terminatingSignal"] = signal.Signals(terminating_signal).name
    atomic_write(manifest_path, manifest)
    manifest_sha = file_digest(manifest_path)

    # Reload after execution so an external concurrent mutation cannot be silently overwritten.
    payload = load_json(path)
    validate_ledger(payload)
    if payload.get("status") != "running" or step in payload["results"]:
        raise LedgerError("ledger changed while managed step was running")
    payload["results"][step] = {
        "status": "passed" if outcome == "completed" and exit_code == 0 else "failed",
        "exitCode": exit_code,
        "required": expected[step]["required"],
        "executionMode": "managed-subprocess",
        "manifest": manifest_relative.as_posix(),
        "manifestSHA256": manifest_sha,
        "completedAt": completed_at,
    }
    if command_binding is not None:
        payload["results"][step].update(command_binding)
        payload["results"][step]["outputs"] = captured_outputs
    payload["missingRequiredSteps"] = [
        entry["id"] for entry in payload["expectedSteps"]
        if entry["required"] and entry["id"] not in payload["results"]
    ]
    atomic_write(path, payload)
    if output_error is not None:
        print(f"error: {output_error}", file=os.sys.stderr)
    return exit_code


def finalize(path: Path) -> bool:
    payload = load_json(path)
    validate_ledger(payload)
    if payload.get("status") in {"passed", "failed"}:
        return payload["status"] == "passed"
    required = [entry["id"] for entry in payload["expectedSteps"] if entry["required"]]
    missing = [step for step in required if step not in payload["results"]]
    failed = [
        step for step in required
        if payload["results"].get(step, {}).get("status") != "passed"
    ]
    passed = not missing and not failed
    payload["missingRequiredSteps"] = missing
    payload["failedRequiredSteps"] = failed
    payload["status"] = "passed" if passed else "failed"
    payload["completedAt"] = utc_now()
    atomic_write(path, payload)
    return passed


def fault_requested(contract_path: Path, workflow_id: str, step: str) -> bool:
    contract = validated_contract(contract_path)
    workflow = workflow_definition(contract, workflow_id)
    declared = set(workflow["requiredSteps"]) | set(workflow.get("optionalSteps", []))
    if step not in declared:
        raise LedgerError(f"step {step!r} is not declared for workflow {workflow_id}")
    fault = contract["faultInjection"]
    if os.environ.get(fault["enableEnvironmentVariable"]) != "1":
        return False
    requested = os.environ.get(fault["stepEnvironmentVariable"], "")
    return requested in {"*", step, f"{workflow_id}:{step}"}


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    subparsers = result.add_subparsers(dest="command", required=True)
    subparsers.add_parser("validate-contract")
    init = subparsers.add_parser("init")
    init.add_argument("--ledger", type=Path, required=True)
    init.add_argument("--workflow", required=True)
    init.add_argument("--run-id", required=True)
    init.add_argument("--source-identity", type=Path)
    step = subparsers.add_parser("record")
    step.add_argument("--ledger", type=Path, required=True)
    step.add_argument("--step", required=True)
    step.add_argument("--exit-code", type=int, required=True)
    run = subparsers.add_parser("run")
    run.add_argument("--ledger", type=Path, required=True)
    run.add_argument("--step", required=True)
    run.add_argument("--timeout-seconds", type=int, required=True)
    run.add_argument("--cwd", type=Path)
    run.add_argument("argv", nargs=argparse.REMAINDER)
    finish = subparsers.add_parser("finalize")
    finish.add_argument("--ledger", type=Path, required=True)
    fault = subparsers.add_parser("fault-requested")
    fault.add_argument("--workflow", required=True)
    fault.add_argument("--step", required=True)
    return result


def main() -> int:
    args = parser().parse_args()
    try:
        if args.command == "validate-contract":
            contract = validated_contract(args.contract)
            print(f"Orchestration contract: PASS ({len(contract['workflows'])} workflows)")
            return 0
        if args.command == "init":
            initialize(args.ledger, args.contract, args.workflow, args.run_id, args.source_identity)
            return 0
        if args.command == "record":
            record(args.ledger, args.step, args.exit_code)
            return 0
        if args.command == "run":
            command = args.argv[1:] if args.argv[:1] == ["--"] else args.argv
            return run_managed_step(
                args.ledger, args.contract, args.step, command, args.timeout_seconds, args.cwd
            )
        if args.command == "finalize":
            return 0 if finalize(args.ledger) else 1
        if args.command == "fault-requested":
            return 0 if fault_requested(args.contract, args.workflow, args.step) else 1
    except (LedgerError, OSError) as error:
        print(f"error: {error}", file=os.sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
