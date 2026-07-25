#!/usr/bin/env python3
"""Create and validate fail-closed, privacy-safe release evidence."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import release_sbom
import required_step_ledger


SCHEMA_VERSION = 2
SOURCE_IDENTITY_SCHEMA_VERSION = 1
EVIDENCE_NAME = "release-evidence.json"
CHECKSUM_NAME = "SHA256SUMS"
CONTRACT_RELATIVE = Path("config/release-evidence-contract.json")
ORCHESTRATION_RELATIVE = Path("config/orchestration-contract.json")
VERIFICATION_DIR = Path("release-verification")
VERIFICATION_BUNDLE_NAME = "release-verification.json"
IOS_ARTIFACT_VERIFICATION_NAME = "ios-release-artifact-verification.json"
DIGEST = re.compile(r"[0-9a-f]{64}")


def digest_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True) + "\n").encode("utf-8")


def compact_canonical_bytes(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n").encode("utf-8")


def canonical_digest(value: Any) -> str:
    return hashlib.sha256(compact_canonical_bytes(value)).hexdigest()


def atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"cannot read JSON from {path}: {error}") from error
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def project_version(root: Path) -> tuple[str, str]:
    text = (root / "project.yml").read_text(encoding="utf-8")
    versions = set(re.findall(r'MARKETING_VERSION:\s*["\']?([^"\'\s]+)', text))
    builds = set(re.findall(r'CURRENT_PROJECT_VERSION:\s*["\']?([^"\'\s]+)', text))
    if len(versions) != 1 or len(builds) != 1:
        raise ValueError("project.yml must declare one consistent marketing version and build number")
    return versions.pop(), builds.pop()


def verify_source(root: Path, tag: str, commit: str, require_tag_ref: bool = True) -> tuple[str, str]:
    version, build = project_version(root)
    expected_tag = f"v{version}"
    if tag != expected_tag and not tag.startswith(expected_tag + "-"):
        raise ValueError(f"release tag {tag!r} does not match MARKETING_VERSION {version!r}")
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("release commit must be a lowercase 40-character Git SHA")
    head = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
    if head != commit:
        raise ValueError(f"release commit {commit} does not match checkout HEAD {head}")
    if require_tag_ref:
        tagged = subprocess.check_output(
            ["git", "-C", str(root), "rev-parse", f"refs/tags/{tag}^{{commit}}"], text=True
        ).strip()
        if tagged != commit:
            raise ValueError(f"tag {tag} resolves to {tagged}, not checkout {commit}")
    return version, build


def _safe_repo_path(value: Any) -> str:
    if not isinstance(value, str) or not value or value.startswith("/") or ".." in Path(value).parts:
        raise ValueError(f"unsafe repository input path: {value!r}")
    return Path(value).as_posix()


def _safe_name(value: Any) -> str:
    if not isinstance(value, str) or not value or value.startswith("/") or ".." in Path(value).parts:
        raise ValueError(f"unsafe release evidence path: {value!r}")
    return value


def load_contract(root: Path) -> dict[str, Any]:
    contract = load_json(root / CONTRACT_RELATIVE)
    if contract.get("schemaVersion") != 1:
        raise ValueError("release-evidence-contract schemaVersion must be 1")
    if "requiredDeterministicChecks" in contract:
        raise ValueError(
            "release-evidence-contract cannot claim unbound requiredDeterministicChecks; "
            "required execution is platform-scoped through managed requiredSteps"
        )
    identity_fields = contract.get("sourceIdentity")
    inputs = contract.get("sourceIdentityInputs")
    if not isinstance(identity_fields, list) or len(identity_fields) != len(set(identity_fields)):
        raise ValueError("release evidence sourceIdentity must be a unique array")
    if not isinstance(inputs, dict) or not inputs:
        raise ValueError("release evidence sourceIdentityInputs must be a non-empty object")
    expected_fields = set(identity_fields) - {"gitCommit", "treeDirty"}
    if set(inputs) != expected_fields:
        raise ValueError("sourceIdentityInputs must exactly define every digest identity field")
    for field, paths in inputs.items():
        if not field.endswith("Digest") or not isinstance(paths, list) or not paths:
            raise ValueError(f"invalid source identity input group: {field}")
        normalized = [_safe_repo_path(value) for value in paths]
        if len(normalized) != len(set(normalized)):
            raise ValueError(f"source identity input group contains duplicates: {field}")
        for relative in normalized:
            if not (root / relative).is_file():
                raise ValueError(f"source identity input is missing: {relative}")
    freshness = contract.get("verificationFreshnessSeconds")
    if not isinstance(freshness, int) or freshness < 60:
        raise ValueError("verificationFreshnessSeconds must be at least 60")
    platforms = contract.get("platformVerification")
    if not isinstance(platforms, dict) or set(platforms) != {"macos", "ios"}:
        raise ValueError("platformVerification must define exactly macos and ios")
    for platform, definition in platforms.items():
        if not isinstance(definition, dict) or not isinstance(definition.get("workflow"), str):
            raise ValueError(f"invalid platform verification definition: {platform}")
        steps = definition.get("requiredSteps")
        if not isinstance(steps, list) or not steps or len(steps) != len(set(steps)):
            raise ValueError(f"invalid required release steps: {platform}")
    orchestration_path = root / "config/orchestration-contract.json"
    if orchestration_path.is_file():
        workflows = load_json(orchestration_path).get("workflows", {})
        for platform, definition in platforms.items():
            managed = workflows.get(definition["workflow"])
            if (
                not isinstance(managed, dict)
                or managed.get("sourceIdentityRequired") is not True
                or managed.get("requiredSteps") != definition["requiredSteps"]
            ):
                raise ValueError(
                    f"{platform} release evidence requiredSteps differ from managed orchestration"
                )
    return contract


def _input_entries(root: Path, paths: list[str]) -> list[dict[str, Any]]:
    return [
        {"path": relative, "bytes": (root / relative).stat().st_size, "sha256": digest_file(root / relative)}
        for relative in sorted(paths)
    ]


def _input_group_digest(entries: list[dict[str, Any]]) -> str:
    return canonical_digest(entries)


def _source_tree_status(root: Path) -> str:
    completed = subprocess.run(
        ["git", "-C", str(root), "status", "--porcelain=v1", "--untracked-files=all"],
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise ValueError("cannot determine complete Git source-tree state")
    return completed.stdout.strip()


def _dirty_tree_detail(status: str, limit: int = 20) -> str:
    lines = status.splitlines()
    shown = "; ".join(lines[:limit])
    if len(lines) > limit:
        shown += f"; … {len(lines) - limit} more"
    return shown


def _identity_digest(payload: dict[str, Any]) -> str:
    unsigned = dict(payload)
    unsigned.pop("identityDigest", None)
    return canonical_digest(unsigned)


def capture_source_identity(root: Path, commit: str, output: Path) -> dict[str, Any]:
    contract = load_contract(root)
    head = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
    if commit != head or not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("source identity commit must exactly match checkout HEAD")
    status = _source_tree_status(root)
    if status:
        raise ValueError(
            "release source identity requires a clean tracked and untracked source tree: "
            + _dirty_tree_detail(status)
        )
    inputs: dict[str, list[dict[str, Any]]] = {}
    digests: dict[str, str] = {}
    for field, raw_paths in sorted(contract["sourceIdentityInputs"].items()):
        paths = [_safe_repo_path(value) for value in raw_paths]
        entries = _input_entries(root, paths)
        inputs[field] = entries
        digests[field] = _input_group_digest(entries)
    payload: dict[str, Any] = {
        "schemaVersion": SOURCE_IDENTITY_SCHEMA_VERSION,
        "capturedAtUTC": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "gitCommit": commit,
        "treeDirty": False,
        **digests,
        "inputs": inputs,
    }
    payload["identityDigest"] = _identity_digest(payload)
    atomic_write(output, canonical_bytes(payload))
    return payload


def validate_source_identity(
    payload: dict[str, Any],
    contract: dict[str, Any],
    *,
    root: Path | None = None,
    expected_commit: str | None = None,
) -> None:
    if payload.get("schemaVersion") != SOURCE_IDENTITY_SCHEMA_VERSION:
        raise ValueError("unsupported source identity schema")
    identity_digest = payload.get("identityDigest")
    if not isinstance(identity_digest, str) or not DIGEST.fullmatch(identity_digest):
        raise ValueError("source identity has no valid identity digest")
    if _identity_digest(payload) != identity_digest:
        raise ValueError("source identity digest does not match its canonical content")
    if expected_commit is not None and payload.get("gitCommit") != expected_commit:
        raise ValueError("source identity commit does not match release commit")
    if payload.get("treeDirty") is not False:
        raise ValueError("release source identity must describe a clean tracked tree")
    identity_fields = contract["sourceIdentity"]
    for field in identity_fields:
        value = payload.get(field)
        if field == "gitCommit":
            if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{40}", value):
                raise ValueError("source identity Git commit is malformed")
        elif field == "treeDirty":
            if not isinstance(value, bool):
                raise ValueError("source identity treeDirty must be boolean")
        elif not isinstance(value, str) or not DIGEST.fullmatch(value):
            raise ValueError(f"source identity digest is malformed: {field}")
    inputs = payload.get("inputs")
    if not isinstance(inputs, dict) or set(inputs) != set(contract["sourceIdentityInputs"]):
        raise ValueError("source identity input inventory does not match the contract")
    for field, contract_paths in contract["sourceIdentityInputs"].items():
        entries = inputs.get(field)
        if not isinstance(entries, list):
            raise ValueError(f"source identity input group is malformed: {field}")
        expected_paths = sorted(_safe_repo_path(value) for value in contract_paths)
        actual_paths = [entry.get("path") for entry in entries if isinstance(entry, dict)]
        if actual_paths != expected_paths or len(actual_paths) != len(entries):
            raise ValueError(f"source identity input paths do not match the contract: {field}")
        if _input_group_digest(entries) != payload[field]:
            raise ValueError(f"source identity input digest does not match: {field}")
        for entry in entries:
            if (
                not isinstance(entry.get("bytes"), int)
                or entry["bytes"] < 0
                or not isinstance(entry.get("sha256"), str)
                or not DIGEST.fullmatch(entry["sha256"])
            ):
                raise ValueError(f"source identity input entry is malformed: {field}")
    if root is not None:
        status = _source_tree_status(root)
        if status:
            raise ValueError(
                "source tree changed after source identity capture: "
                + _dirty_tree_detail(status)
            )
        head = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
        if head != payload["gitCommit"]:
            raise ValueError("checkout commit changed after source identity capture")
        for field, paths in contract["sourceIdentityInputs"].items():
            current = _input_entries(root, [_safe_repo_path(value) for value in paths])
            if current != inputs[field]:
                raise ValueError(f"source input changed after identity capture: {field}")


def _parse_time(value: Any, label: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"{label} timestamp is missing")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"{label} timestamp is malformed") from error
    if parsed.tzinfo is None:
        raise ValueError(f"{label} timestamp must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def _release_output_relative(path: str, platform: str) -> Path:
    declared = Path(path)
    prefix = Path("build") / "dist" / platform
    try:
        relative = declared.relative_to(prefix)
    except ValueError as error:
        raise ValueError(f"managed release output is outside the canonical {platform} distribution root: {path}") from error
    if not relative.parts or ".." in relative.parts:
        raise ValueError(f"managed release output path is unsafe: {path}")
    return relative


def _validate_bound_outputs(
    manifest: dict[str, Any],
    result: dict[str, Any],
    template: dict[str, Any],
    platform: str,
    output_dir: Path,
    step: str,
) -> None:
    declared = template.get("outputs", [])
    outputs = manifest.get("outputs")
    if not isinstance(outputs, list) or len(outputs) != len(declared):
        raise ValueError(f"required step output evidence is incomplete: {step}")
    if result.get("outputs") != outputs:
        raise ValueError(f"required-step result output evidence differs from its manifest: {step}")
    for expected_path, entry in zip(declared, outputs):
        if not isinstance(entry, dict) or set(entry) != {"path", "bytes", "sha256"}:
            raise ValueError(f"required step output entry is malformed: {step}")
        if entry.get("path") != expected_path:
            raise ValueError(f"required step output path differs from its command template: {step}")
        if not isinstance(entry.get("bytes"), int) or entry["bytes"] < 0:
            raise ValueError(f"required step output size is malformed: {step}")
        if not isinstance(entry.get("sha256"), str) or not DIGEST.fullmatch(entry["sha256"]):
            raise ValueError(f"required step output digest is malformed: {step}")
        relative = _release_output_relative(expected_path, platform)
        candidate = output_dir / relative
        if (
            candidate.is_symlink()
            or not candidate.is_file()
            or candidate.stat().st_size != entry["bytes"]
            or digest_file(candidate) != entry["sha256"]
        ):
            raise ValueError(f"required step output changed after managed execution: {step}:{expected_path}")


def _bound_output_entries(
    manifests: dict[str, dict[str, Any]], platform: str
) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for manifest in manifests.values():
        for entry in manifest.get("outputs", []):
            name = _release_output_relative(entry["path"], platform).as_posix()
            if name in result:
                raise ValueError(f"duplicate managed release output: {name}")
            result[name] = entry
    return result


def validate_step_ledger(
    ledger_path: Path,
    source_identity: dict[str, Any],
    contract: dict[str, Any],
    platform: str,
    orchestration_contract: dict[str, Any],
    output_dir: Path,
    *,
    enforce_freshness: bool,
    manifest_payloads: dict[str, dict[str, Any]] | None = None,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    ledger = load_json(ledger_path)
    definition = contract["platformVerification"][platform]
    required_steps = definition["requiredSteps"]
    managed_workflow = required_step_ledger.workflow_definition(
        orchestration_contract, definition["workflow"]
    )
    expected_command_contract_digest = required_step_ledger.workflow_command_contract_digest(
        managed_workflow
    )
    if expected_command_contract_digest is None:
        raise ValueError("release workflow has no command binding contract")
    if ledger.get("commandContractDigest") != expected_command_contract_digest:
        raise ValueError("required-step ledger command contract differs from release orchestration")
    if ledger.get("schemaVersion") != 1:
        raise ValueError("unsupported required-step ledger schema")
    if ledger.get("workflow") != definition["workflow"]:
        raise ValueError("required-step ledger belongs to the wrong workflow")
    if ledger.get("sourceIdentityDigest") != source_identity["identityDigest"]:
        raise ValueError("required-step ledger is bound to a different source identity")
    if ledger.get("status") != "passed":
        raise ValueError("required-step ledger did not pass")
    expected = ledger.get("expectedSteps")
    results = ledger.get("results")
    if not isinstance(expected, list) or not isinstance(results, dict):
        raise ValueError("required-step ledger is malformed")
    expected_ids = [entry.get("id") for entry in expected if isinstance(entry, dict)]
    if expected_ids != required_steps or any(entry.get("required") is not True for entry in expected):
        raise ValueError("required-step ledger does not exactly match the platform release contract")
    if set(results) != set(required_steps):
        raise ValueError("required-step ledger is partial or contains unknown results")
    if ledger.get("missingRequiredSteps") not in ([], None) or ledger.get("failedRequiredSteps") not in ([], None):
        raise ValueError("required-step ledger reports missing or failed steps")

    started = _parse_time(ledger.get("startedAt"), "ledger startedAt")
    completed = _parse_time(ledger.get("completedAt"), "ledger completedAt")
    if completed < started:
        raise ValueError("required-step ledger completes before it starts")
    if enforce_freshness:
        now = datetime.now(timezone.utc)
        if completed > now.replace(microsecond=0) and (completed - now).total_seconds() > 300:
            raise ValueError("required-step ledger completion is in the future")
        if (now - completed).total_seconds() > contract["verificationFreshnessSeconds"]:
            raise ValueError("required-step ledger is stale")

    manifests: dict[str, dict[str, Any]] = {}
    manifest_digests: set[str] = set()
    invocation_id = ledger.get("invocationID")
    if not isinstance(invocation_id, str) or not re.fullmatch(r"[0-9a-f]{32}", invocation_id):
        raise ValueError("required-step ledger invocation identity is malformed")
    for step in required_steps:
        result = results[step]
        if not isinstance(result, dict):
            raise ValueError(f"required-step result is malformed: {step}")
        if (
            result.get("status") != "passed"
            or result.get("exitCode") != 0
            or result.get("executionMode") != "managed-subprocess"
        ):
            raise ValueError(f"required step was not passed by a managed subprocess: {step}")
        expected_name = f"steps/{step}.json"
        if result.get("manifest") != expected_name:
            raise ValueError(f"required step manifest path is not canonical: {step}")
        claimed_digest = result.get("manifestSHA256")
        if not isinstance(claimed_digest, str) or not DIGEST.fullmatch(claimed_digest):
            raise ValueError(f"required step manifest digest is malformed: {step}")
        if claimed_digest in manifest_digests:
            raise ValueError("duplicate required-step manifest digest")
        manifest_digests.add(claimed_digest)
        if manifest_payloads is None:
            manifest_path = ledger_path.parent / expected_name
            if not manifest_path.is_file() or digest_file(manifest_path) != claimed_digest:
                raise ValueError(f"required step manifest is missing, partial, or stale: {step}")
            manifest = load_json(manifest_path)
        else:
            manifest = manifest_payloads.get(step, {})
            if not isinstance(manifest, dict) or hashlib.sha256(canonical_bytes(manifest)).hexdigest() != claimed_digest:
                raise ValueError(f"bundled required step manifest is missing, partial, or stale: {step}")
        if set(manifest) - {
            "schemaVersion", "workflow", "runID", "invocationID", "step",
            "sourceIdentityDigest", "commandDigest", "timeoutSeconds", "startedAt",
            "completedAt", "outcome", "exitCode", "terminatingSignal",
            "commandTemplateID", "commandTemplateDigest", "commandContractDigest",
            "outputs",
        }:
            raise ValueError(f"required step manifest has unknown fields: {step}")
        for field, value in (
            ("schemaVersion", 1),
            ("workflow", ledger["workflow"]),
            ("runID", ledger["runID"]),
            ("invocationID", invocation_id),
            ("step", step),
            ("sourceIdentityDigest", source_identity["identityDigest"]),
            ("outcome", "completed"),
            ("exitCode", 0),
        ):
            if manifest.get(field) != value:
                raise ValueError(f"required step manifest identity or outcome mismatch: {step}:{field}")
        if not isinstance(manifest.get("commandDigest"), str) or not DIGEST.fullmatch(manifest["commandDigest"]):
            raise ValueError(f"required step command digest is malformed: {step}")
        template_id = manifest.get("commandTemplateID")
        templates = managed_workflow["commandTemplates"][step]
        matching_templates = [template for template in templates if template["id"] == template_id]
        if len(matching_templates) != 1:
            raise ValueError(f"required step command template identity is unknown: {step}")
        expected_template_digest = required_step_ledger.command_template_digest(matching_templates[0])
        if (
            manifest.get("commandTemplateDigest") != expected_template_digest
            or manifest.get("commandContractDigest") != expected_command_contract_digest
        ):
            raise ValueError(f"required step command binding differs from release orchestration: {step}")
        if any(
            result.get(field) != manifest.get(field)
            for field in ("commandTemplateID", "commandTemplateDigest", "commandContractDigest")
        ):
            raise ValueError(f"required-step result command binding differs from its manifest: {step}")
        _validate_bound_outputs(
            manifest, result, matching_templates[0], platform, output_dir, step
        )
        if not isinstance(manifest.get("timeoutSeconds"), int) or manifest["timeoutSeconds"] < 1:
            raise ValueError(f"required step timeout is malformed: {step}")
        manifest_started = _parse_time(manifest.get("startedAt"), f"{step} startedAt")
        manifest_completed = _parse_time(manifest.get("completedAt"), f"{step} completedAt")
        if manifest_started < started or manifest_completed < manifest_started or manifest_completed > completed:
            raise ValueError(f"required step timestamps escape the ledger interval: {step}")
        if result.get("completedAt") != manifest.get("completedAt"):
            raise ValueError(f"required-step result timestamp does not match its manifest: {step}")
        manifests[step] = manifest
    return ledger, manifests


def _relative_file(output_dir: Path, value: Path) -> tuple[str, Path]:
    resolved = value.resolve()
    try:
        relative = resolved.relative_to(output_dir.resolve()).as_posix()
    except ValueError as error:
        raise ValueError(f"release asset escapes output directory: {value}") from error
    if not resolved.is_file() or relative.startswith("../") or relative.startswith("/"):
        raise ValueError(f"release asset is missing or unsafe: {value}")
    return relative, resolved


def _entry(output_dir: Path, path: Path, kind: str) -> dict[str, Any]:
    relative, resolved = _relative_file(output_dir, path)
    return {"name": relative, "kind": kind, "bytes": resolved.stat().st_size, "sha256": digest_file(resolved)}


def _copy_json(payload: dict[str, Any], destination: Path) -> None:
    atomic_write(destination, canonical_bytes(payload))


def create(
    root: Path,
    output_dir: Path,
    tag: str,
    commit: str,
    platform: str,
    artifacts: list[Path],
    metadata: Path | None,
    source_date_epoch: int,
    source_identity_path: Path | None = None,
    step_ledger_path: Path | None = None,
    require_tag_ref: bool = True,
) -> tuple[Path, Path]:
    if source_identity_path is None or step_ledger_path is None:
        raise ValueError("release evidence requires source identity and managed required-step ledger manifests")
    output_dir.mkdir(parents=True, exist_ok=True)
    evidence_path = output_dir / EVIDENCE_NAME
    checksum_path = output_dir / CHECKSUM_NAME
    verification_bundle_path = output_dir / VERIFICATION_BUNDLE_NAME
    # A failed recreation must never leave a previous publication manifest or verification bundle behind.
    evidence_path.unlink(missing_ok=True)
    checksum_path.unlink(missing_ok=True)
    verification_bundle_path.unlink(missing_ok=True)
    version, build = verify_source(root, tag, commit, require_tag_ref=require_tag_ref)
    contract = load_contract(root)
    orchestration_text = (root / ORCHESTRATION_RELATIVE).read_text(encoding="utf-8")
    orchestration_contract = required_step_ledger.validate_contract_payload(
        json.loads(orchestration_text), root=root
    )
    source_identity = load_json(source_identity_path)
    validate_source_identity(source_identity, contract, root=root, expected_commit=commit)
    ledger, manifests = validate_step_ledger(
        step_ledger_path, source_identity, contract, platform, orchestration_contract, output_dir,
        enforce_freshness=True
    )

    verification_bundle = {
        "schemaVersion": 1,
        "contractText": (root / CONTRACT_RELATIVE).read_text(encoding="utf-8"),
        "orchestrationContractText": orchestration_text,
        "sourceIdentity": source_identity,
        "requiredStepLedger": ledger,
        "stepManifests": manifests,
    }
    _copy_json(verification_bundle, verification_bundle_path)

    prefix = f"vocello-{platform}"
    spdx_path, cdx_path = release_sbom.generate(root, output_dir, commit, source_date_epoch, prefix)
    artifact_entries = [_entry(output_dir, path, "artifact") for path in artifacts]
    if metadata is not None:
        artifact_entries.append(_entry(output_dir, metadata, "metadata"))
    sbom_entries = [_entry(output_dir, spdx_path, "spdx-2.3"), _entry(output_dir, cdx_path, "cyclonedx-1.5")]
    verification_entries = [_entry(output_dir, verification_bundle_path, "release-verification-bundle")]
    bound_outputs = _bound_output_entries(manifests, platform)
    artifact_outputs = {item["name"]: item for item in artifact_entries}
    missing_bound_outputs = set(bound_outputs) - set(artifact_outputs)
    if missing_bound_outputs:
        raise ValueError(
            "managed release outputs must be included as release artifacts: "
            + ", ".join(sorted(missing_bound_outputs))
        )
    for name, managed in bound_outputs.items():
        artifact = artifact_outputs[name]
        if managed["bytes"] != artifact["bytes"] or managed["sha256"] != artifact["sha256"]:
            raise ValueError(f"managed release output changed before evidence creation: {name}")
    source_materials = []
    for relative in (release_sbom.SWIFT_LOCK, release_sbom.NPM_LOCK, Path("project.yml")):
        path = root / relative
        source_materials.append({"name": relative.as_posix(), "sha256": digest_file(path)})

    evidence = {
        "schemaVersion": SCHEMA_VERSION,
        "release": {
            "tag": tag,
            "commitSHA": commit,
            "marketingVersion": version,
            "buildNumber": build,
            "platform": platform,
            "createdAtUTC": datetime.fromtimestamp(source_date_epoch, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        },
        "sourceIdentity": source_identity,
        "sourceMaterials": sorted(source_materials, key=lambda item: item["name"]),
        "artifacts": sorted(artifact_entries, key=lambda item: item["name"]),
        "sboms": sorted(sbom_entries, key=lambda item: item["name"]),
        "verificationEvidence": sorted(verification_entries, key=lambda item: item["name"]),
        "verification": [
            {
                "id": step,
                "status": ledger["results"][step]["status"],
                "commandDigest": manifests[step]["commandDigest"],
                "commandTemplateID": manifests[step]["commandTemplateID"],
                "commandTemplateDigest": manifests[step]["commandTemplateDigest"],
                "completedAt": manifests[step]["completedAt"],
                "manifestSHA256": ledger["results"][step]["manifestSHA256"],
            }
            for step in contract["platformVerification"][platform]["requiredSteps"]
        ],
    }
    atomic_write(evidence_path, canonical_bytes(evidence))
    checksum_paths = [
        output_dir / item["name"]
        for item in artifact_entries + sbom_entries + verification_entries
    ] + [evidence_path]
    checksum_lines = [f"{digest_file(path)}  {path.relative_to(output_dir).as_posix()}" for path in checksum_paths]
    atomic_write(checksum_path, ("\n".join(sorted(checksum_lines)) + "\n").encode("utf-8"))
    validate(output_dir)
    return evidence_path, checksum_path


def _validate_entry_files(output_dir: Path, entries: list[dict[str, Any]]) -> dict[str, str]:
    expected: dict[str, str] = {}
    for item in entries:
        if not isinstance(item, dict):
            raise ValueError("release evidence file entry is malformed")
        name = _safe_name(item.get("name"))
        if name in expected:
            raise ValueError(f"duplicate release evidence file entry: {name}")
        path = output_dir / name
        if not path.is_file() or path.stat().st_size != item.get("bytes") or digest_file(path) != item.get("sha256"):
            raise ValueError(f"release evidence mismatch: {name}")
        expected[name] = item["sha256"]
    return expected


def validate_ios_release_artifact_verification(
    payload: dict[str, Any], release: dict[str, Any], artifacts: list[dict[str, Any]]
) -> None:
    top_level = {
        "schemaVersion", "verdict", "artifact", "expectedIdentity", "archive", "export",
        "archiveExportIdentityMatch", "privacy",
    }
    if set(payload) != top_level or payload.get("schemaVersion") != 2 or payload.get("verdict") != "passed":
        raise ValueError("iOS release artifact verification summary is malformed or did not pass")
    summary_entries = [item for item in artifacts if item.get("name") == IOS_ARTIFACT_VERIFICATION_NAME]
    ipa_entries = [item for item in artifacts if str(item.get("name", "")).endswith(".ipa")]
    if len(summary_entries) != 1 or summary_entries[0].get("kind") != "artifact" or len(ipa_entries) != 1:
        raise ValueError("iOS release evidence must contain exactly one verification summary and one IPA")

    artifact = payload.get("artifact")
    if not isinstance(artifact, dict) or set(artifact) != {"ipaName", "ipaSHA256"}:
        raise ValueError("iOS verification summary artifact identity is malformed")
    ipa_entry = ipa_entries[0]
    if (
        artifact.get("ipaName") != Path(str(ipa_entry.get("name"))).name
        or artifact.get("ipaSHA256") != ipa_entry.get("sha256")
    ):
        raise ValueError("iOS verification summary is bound to a different IPA")

    identity = payload.get("expectedIdentity")
    identity_fields = {
        "bundleIdentifier", "marketingVersion", "buildNumber", "architectures",
        "applicationGroups", "increasedMemoryLimit", "privacyManifestSHA256",
    }
    if not isinstance(identity, dict) or set(identity) != identity_fields:
        raise ValueError("iOS verification expected identity is malformed")
    bundle_identifier = identity.get("bundleIdentifier")
    application_groups = identity.get("applicationGroups")
    if (
        not isinstance(bundle_identifier, str)
        or re.fullmatch(r"[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+", bundle_identifier) is None
        or identity.get("marketingVersion") != release.get("marketingVersion")
        or identity.get("buildNumber") != release.get("buildNumber")
        or identity.get("architectures") != ["arm64"]
        or not isinstance(application_groups, list)
        or not application_groups
        or len(application_groups) != len(set(application_groups))
        or any(not isinstance(value, str) or not value.startswith("group.") for value in application_groups)
        or identity.get("increasedMemoryLimit") is not True
        or not isinstance(identity.get("privacyManifestSHA256"), str)
        or DIGEST.fullmatch(identity["privacyManifestSHA256"]) is None
    ):
        raise ValueError("iOS verification expected identity differs from release evidence")

    snapshot_fields = {
        "label", "bundleIdentifier", "marketingVersion", "buildNumber", "architectures",
        "machOUUIDs", "executableSHA256", "signatureNormalizedExecutableSHA256", "bundleSHA256",
        "signatureVerified", "signingAuthorityVerified", "signingCertificateTrustVerified",
        "distributionAuthorityVerified",
        "teamIdentifierVerified", "provisioningProfileVerified", "signerProfileCertificateMatch",
        "applicationIdentifierVerified", "applicationGroups", "increasedMemoryLimit", "getTaskAllow",
        "privacyManifestSHA256", "privacyManifestVerified",
    }
    snapshots: dict[str, dict[str, Any]] = {}
    for label in ("archive", "export"):
        snapshot = payload.get(label)
        if not isinstance(snapshot, dict) or set(snapshot) != snapshot_fields or snapshot.get("label") != label:
            raise ValueError(f"iOS verification {label} snapshot is malformed")
        if (
            snapshot.get("bundleIdentifier") != bundle_identifier
            or snapshot.get("marketingVersion") != release.get("marketingVersion")
            or snapshot.get("buildNumber") != release.get("buildNumber")
            or snapshot.get("architectures") != ["arm64"]
            or snapshot.get("applicationGroups") != application_groups
            or snapshot.get("increasedMemoryLimit") is not True
            or not isinstance(snapshot.get("getTaskAllow"), bool)
            or any(snapshot.get(field) is not True for field in (
                "signatureVerified", "signingAuthorityVerified", "signingCertificateTrustVerified",
                "teamIdentifierVerified",
                "provisioningProfileVerified", "signerProfileCertificateMatch",
                "applicationIdentifierVerified", "privacyManifestVerified",
            ))
            or not isinstance(snapshot.get("distributionAuthorityVerified"), bool)
            or (label == "export" and snapshot.get("distributionAuthorityVerified") is not True)
            or (label == "export" and snapshot.get("getTaskAllow") is not False)
            or not isinstance(snapshot.get("machOUUIDs"), list)
            or not snapshot["machOUUIDs"]
            or any(re.fullmatch(r"[0-9A-Fa-f]{8}(?:-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12}", value) is None
                   for value in snapshot["machOUUIDs"] if isinstance(value, str))
            or any(not isinstance(value, str) for value in snapshot["machOUUIDs"])
            or not isinstance(snapshot.get("executableSHA256"), str)
            or DIGEST.fullmatch(snapshot["executableSHA256"]) is None
            or not isinstance(snapshot.get("signatureNormalizedExecutableSHA256"), str)
            or DIGEST.fullmatch(snapshot["signatureNormalizedExecutableSHA256"]) is None
            or not isinstance(snapshot.get("bundleSHA256"), str)
            or DIGEST.fullmatch(snapshot["bundleSHA256"]) is None
            or snapshot.get("privacyManifestSHA256") != identity.get("privacyManifestSHA256")
        ):
            raise ValueError(f"iOS verification {label} snapshot failed its release contract")
        snapshots[label] = snapshot
    if (
        payload.get("archiveExportIdentityMatch") is not True
        or snapshots["archive"]["machOUUIDs"] != snapshots["export"]["machOUUIDs"]
        or snapshots["archive"]["signatureNormalizedExecutableSHA256"]
        != snapshots["export"]["signatureNormalizedExecutableSHA256"]
        or snapshots["archive"]["privacyManifestSHA256"] != snapshots["export"]["privacyManifestSHA256"]
    ):
        raise ValueError("iOS archive and exported IPA identities do not match")
    if payload.get("privacy") != {"containsTeamIdentifier": False, "containsAbsolutePaths": False}:
        raise ValueError("iOS verification summary privacy declaration is invalid")


def validate(output_dir: Path) -> dict[str, Any]:
    output_dir = output_dir.resolve()
    evidence_path = output_dir / EVIDENCE_NAME
    checksum_path = output_dir / CHECKSUM_NAME
    evidence = load_json(evidence_path)
    if evidence.get("schemaVersion") != SCHEMA_VERSION:
        raise ValueError("unsupported release evidence schema")
    release = evidence.get("release", {})
    if not re.fullmatch(r"v\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?", str(release.get("tag", ""))):
        raise ValueError("invalid release tag in evidence")
    if not re.fullmatch(r"[0-9a-f]{40}", str(release.get("commitSHA", ""))):
        raise ValueError("invalid commit SHA in evidence")
    platform = release.get("platform")
    if platform not in {"macos", "ios"}:
        raise ValueError("invalid platform in release evidence")

    verification_entries = evidence.get("verificationEvidence")
    entries = evidence.get("artifacts", []) + evidence.get("sboms", [])
    if not isinstance(entries, list) or not entries or not isinstance(verification_entries, list):
        raise ValueError("release evidence contains no artifacts or verification evidence")
    expected = _validate_entry_files(output_dir, entries + verification_entries)
    if platform == "ios":
        summary = load_json(output_dir / IOS_ARTIFACT_VERIFICATION_NAME)
        validate_ios_release_artifact_verification(summary, release, evidence.get("artifacts", []))

    bundle_path = output_dir / VERIFICATION_BUNDLE_NAME
    bundle = load_json(bundle_path)
    if (
        bundle.get("schemaVersion") != 1
        or not isinstance(bundle.get("contractText"), str)
        or not isinstance(bundle.get("orchestrationContractText"), str)
    ):
        raise ValueError("release verification bundle is malformed")
    try:
        contract = json.loads(bundle["contractText"])
        orchestration_contract = json.loads(bundle["orchestrationContractText"])
    except json.JSONDecodeError as error:
        raise ValueError("bundled release evidence contract is malformed") from error
    # Validate the copied contract structurally without requiring a repository checkout.
    if contract.get("schemaVersion") != 1 or platform not in contract.get("platformVerification", {}):
        raise ValueError("copied release evidence contract is malformed")
    try:
        orchestration_contract = required_step_ledger.validate_contract_payload(
            orchestration_contract, root=None
        )
    except required_step_ledger.LedgerError as error:
        raise ValueError(f"copied orchestration contract is malformed: {error}") from error
    source_identity = bundle.get("sourceIdentity")
    ledger = bundle.get("requiredStepLedger")
    manifests = bundle.get("stepManifests")
    if not isinstance(source_identity, dict) or not isinstance(ledger, dict) or not isinstance(manifests, dict):
        raise ValueError("release verification bundle payloads are malformed")
    validate_source_identity(source_identity, contract, expected_commit=release["commitSHA"])
    if evidence.get("sourceIdentity") != source_identity:
        raise ValueError("embedded source identity differs from its hashed manifest")
    contract_entries = source_identity["inputs"].get("releaseContractDigest", [])
    contract_text_digest = hashlib.sha256(bundle["contractText"].encode("utf-8")).hexdigest()
    if len(contract_entries) != 1 or contract_entries[0].get("sha256") != contract_text_digest:
        raise ValueError("copied release evidence contract differs from source identity")
    orchestration_entries = source_identity["inputs"].get("orchestrationContractDigest", [])
    orchestration_text_digest = hashlib.sha256(bundle["orchestrationContractText"].encode("utf-8")).hexdigest()
    if len(orchestration_entries) != 1 or orchestration_entries[0].get("sha256") != orchestration_text_digest:
        raise ValueError("copied orchestration contract differs from source identity")
    # The ledger path is used only to resolve external manifests; bundled validation supplies them directly.
    with tempfile.TemporaryDirectory() as directory:
        synthetic_ledger = Path(directory) / "required-steps.json"
        atomic_write(synthetic_ledger, canonical_bytes(ledger))
        _, validated_manifests = validate_step_ledger(
            synthetic_ledger, source_identity, contract, platform, orchestration_contract, output_dir,
            enforce_freshness=False, manifest_payloads=manifests,
        )
    missing_bound_outputs = set(_bound_output_entries(validated_manifests, platform)) - {
        _safe_name(item.get("name")) for item in evidence.get("artifacts", [])
    }
    if missing_bound_outputs:
        raise ValueError("managed release outputs are absent from release artifacts")
    expected_verification = [
        {
            "id": step,
            "status": ledger["results"][step]["status"],
            "commandDigest": validated_manifests[step]["commandDigest"],
            "commandTemplateID": validated_manifests[step]["commandTemplateID"],
            "commandTemplateDigest": validated_manifests[step]["commandTemplateDigest"],
            "completedAt": validated_manifests[step]["completedAt"],
            "manifestSHA256": ledger["results"][step]["manifestSHA256"],
        }
        for step in contract["platformVerification"][platform]["requiredSteps"]
    ]
    if evidence.get("verification") != expected_verification:
        raise ValueError("release verification summary does not match managed step manifests")

    expected[EVIDENCE_NAME] = digest_file(evidence_path)
    actual: dict[str, str] = {}
    for line in checksum_path.read_text(encoding="utf-8").splitlines():
        match = re.fullmatch(r"([0-9a-f]{64})  (.+)", line)
        if not match:
            raise ValueError(f"malformed checksum line: {line!r}")
        name = _safe_name(match.group(2))
        if name in actual:
            raise ValueError(f"duplicate checksum entry: {name}")
        actual[name] = match.group(1)
    if actual != expected:
        raise ValueError("SHA256SUMS does not exactly match release evidence")
    return evidence


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    verify = sub.add_parser("verify-source")
    verify.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent)
    verify.add_argument("--tag", required=True)
    verify.add_argument("--commit", required=True)
    identity = sub.add_parser("capture-source-identity")
    identity.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent)
    identity.add_argument("--commit", required=True)
    identity.add_argument("--output", type=Path, required=True)
    create_parser = sub.add_parser("create")
    create_parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent)
    create_parser.add_argument("--output-dir", type=Path, required=True)
    create_parser.add_argument("--tag", required=True)
    create_parser.add_argument("--commit", required=True)
    create_parser.add_argument("--platform", choices=("macos", "ios"), required=True)
    create_parser.add_argument("--artifact", action="append", type=Path, required=True)
    create_parser.add_argument("--metadata", type=Path)
    create_parser.add_argument("--source-identity", type=Path, required=True)
    create_parser.add_argument("--step-ledger", type=Path, required=True)
    create_parser.add_argument("--source-date-epoch", type=int, required=True)
    create_parser.add_argument("--allow-missing-tag-ref", action="store_true", help=argparse.SUPPRESS)
    validate_parser = sub.add_parser("validate")
    validate_parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    if args.command == "verify-source":
        version, build = verify_source(args.root.resolve(), args.tag, args.commit)
        print(json.dumps({"tag": args.tag, "commit": args.commit, "version": version, "build": build}, sort_keys=True))
    elif args.command == "capture-source-identity":
        payload = capture_source_identity(args.root.resolve(), args.commit, args.output.resolve())
        print(json.dumps({"identity": str(args.output), "digest": payload["identityDigest"]}, sort_keys=True))
    elif args.command == "create":
        evidence, checksums = create(
            args.root.resolve(), args.output_dir.resolve(), args.tag, args.commit, args.platform,
            args.artifact, args.metadata, args.source_date_epoch,
            args.source_identity.resolve(), args.step_ledger.resolve(),
            require_tag_ref=not args.allow_missing_tag_ref,
        )
        print(json.dumps({"evidence": str(evidence), "checksums": str(checksums)}, sort_keys=True))
    else:
        evidence = validate(args.output_dir)
        print(json.dumps({"status": "passed", "tag": evidence["release"]["tag"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
