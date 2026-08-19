#!/usr/bin/env python3
"""Create and validate source-bound quality evidence for public promotion."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from typing import Any

import benchmark_history
import evidence_impact


ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = Path("config/quality-promotion-contract.json")
SCHEMA_VERSION = 1
DIGEST_RE = re.compile(r"[0-9a-f]{64}")
COMMIT_RE = re.compile(r"[0-9a-f]{40}")
TAG_RE = re.compile(r"v\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?")


class PromotionError(ValueError):
    pass


def canonical_bytes(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode()


def digest_value(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise PromotionError(f"cannot read {path}: {error}") from error
    if not isinstance(value, dict):
        raise PromotionError(f"{path} must contain a JSON object")
    return value


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(json.dumps(value, indent=2, sort_keys=True).encode() + b"\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def load_contract(root: Path = ROOT) -> dict[str, Any]:
    return read_json(root / CONTRACT_PATH)


def validate_contract(contract: dict[str, Any], impact: dict[str, Any] | None = None) -> None:
    if contract.get("schemaVersion") != SCHEMA_VERSION:
        raise PromotionError(f"quality promotion schemaVersion must be {SCHEMA_VERSION}")
    if contract.get("publicPromotionPolicy") != "source-bound-quality-evidence":
        raise PromotionError("public promotion policy must remain source-bound-quality-evidence")
    age = contract.get("maxEvidenceAgeSeconds")
    if not isinstance(age, int) or age <= 0:
        raise PromotionError("maxEvidenceAgeSeconds must be positive")
    warnings = contract.get("allowedWarnings")
    if not isinstance(warnings, list) or len(warnings) != len(set(warnings)) or any(
        not isinstance(item, str) or not item for item in warnings
    ):
        raise PromotionError("allowedWarnings must be a unique string array")
    definitions = contract.get("evidence")
    if not isinstance(definitions, dict) or not definitions:
        raise PromotionError("quality promotion evidence definitions are missing")
    for identity, definition in definitions.items():
        if not isinstance(identity, str) or not re.fullmatch(r"[a-z][a-z0-9-]+", identity):
            raise PromotionError(f"invalid quality evidence id: {identity!r}")
        if not isinstance(definition, dict) or definition.get("platform") not in {"macos", "ios"}:
            raise PromotionError(f"{identity} has no supported platform")
        evidence_type = definition.get("type")
        if evidence_type == "benchmark-record":
            if definition.get("kind") not in benchmark_history.V2_KINDS:
                raise PromotionError(f"{identity} has an unsupported benchmark kind")
            if definition.get("matrixScope") not in benchmark_history.MATRIX_SCOPES:
                raise PromotionError(f"{identity} has an unsupported matrix scope")
            classifications = definition.get("classifications")
            if not isinstance(classifications, list) or not classifications or set(classifications) - benchmark_history.CLASSIFICATIONS:
                raise PromotionError(f"{identity} has invalid classifications")
        elif evidence_type == "managed-command":
            command = definition.get("command")
            if not isinstance(command, list) or not command or any(not isinstance(item, str) or not item for item in command):
                raise PromotionError(f"{identity} has an invalid managed command")
        else:
            raise PromotionError(f"{identity} has unsupported type {evidence_type!r}")
    minimum = contract.get("platformMinimumEvidence")
    if not isinstance(minimum, dict) or set(minimum) != {"macos", "ios"}:
        raise PromotionError("platformMinimumEvidence must define macos and ios")
    for platform, identities in minimum.items():
        if not isinstance(identities, list) or not identities:
            raise PromotionError(f"{platform} promotion minimum is empty")
        for identity in identities:
            if identity not in definitions or definitions[identity].get("platform") != platform:
                raise PromotionError(f"{platform} promotion minimum references invalid evidence {identity}")
    privacy = contract.get("privacy")
    if not isinstance(privacy, dict) or privacy.get("deviceIdentity") != "canonical-hardware-profile-only":
        raise PromotionError("quality promotion privacy policy is invalid")
    forbidden = privacy.get("forbiddenKeys")
    if not isinstance(forbidden, list) or not forbidden:
        raise PromotionError("quality promotion privacy forbiddenKeys are missing")
    if impact is not None:
        references: set[str] = set()
        for item in [*impact.get("pathClasses", []), impact.get("fallbackClass", {})]:
            if isinstance(item, dict):
                references.update(item.get("promotionRequiredEvidence") or [])
        unknown = sorted(references - definitions.keys())
        if unknown:
            raise PromotionError("evidence-impact promotion references are undefined: " + ", ".join(unknown))


def git(root: Path, *arguments: str) -> str:
    completed = subprocess.run(["git", *arguments], cwd=root, text=True, capture_output=True, check=False)
    if completed.returncode != 0:
        raise PromotionError(completed.stderr.strip() or f"git {' '.join(arguments)} failed")
    return completed.stdout.strip()


def resolve_commit(root: Path, value: str) -> str:
    commit = git(root, "rev-parse", f"{value}^{{commit}}")
    if COMMIT_RE.fullmatch(commit) is None:
        raise PromotionError(f"cannot resolve commit {value!r}")
    return commit


def parse_time(value: Any, label: str) -> datetime:
    if not isinstance(value, str):
        raise PromotionError(f"{label} is missing")
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise PromotionError(f"{label} is invalid") from error


def privacy_scan(value: Any, contract: dict[str, Any], path: str = "manifest") -> None:
    forbidden = {str(item).casefold() for item in contract["privacy"]["forbiddenKeys"]}
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key).casefold() in forbidden:
                raise PromotionError(f"quality promotion manifest contains forbidden key at {path}.{key}")
            privacy_scan(child, contract, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            privacy_scan(child, contract, f"{path}[{index}]")
    elif isinstance(value, str) and (
        re.search(r"(?:^|\s)/Users/[^/\s]+/", value)
        or re.search(r"(?:^|\s)/home/[^/\s]+/", value)
        or "file:///" in value
    ):
        raise PromotionError(f"quality promotion manifest contains an absolute user path at {path}")


def release_identity(path: Path, platform: str, tag: str, root: Path) -> tuple[dict[str, Any], str]:
    if TAG_RE.fullmatch(tag) is None:
        raise PromotionError("promotion tag is invalid")
    evidence = read_json(path)
    release = evidence.get("release")
    source = evidence.get("sourceIdentity")
    if evidence.get("schemaVersion") != 2 or not isinstance(release, dict) or not isinstance(source, dict):
        raise PromotionError("release evidence is malformed")
    if release.get("tag") != tag or release.get("platform") != platform:
        raise PromotionError("release evidence belongs to another tag or platform")
    commit = release.get("commitSHA")
    if not isinstance(commit, str) or COMMIT_RE.fullmatch(commit) is None:
        raise PromotionError("release evidence commit is invalid")
    if resolve_commit(root, tag) != commit:
        raise PromotionError("release evidence is not bound to the tag commit")
    if source.get("gitCommit") != commit or source.get("treeDirty") is not False:
        raise PromotionError("release source identity is dirty or cross-source")
    identity_digest = source.get("identityDigest")
    if not isinstance(identity_digest, str) or DIGEST_RE.fullmatch(identity_digest) is None:
        raise PromotionError("release source identity digest is invalid")
    return evidence, commit


def changed_paths(root: Path, base: str, commit: str) -> tuple[str, list[str]]:
    base_commit = resolve_commit(root, base)
    ancestor = subprocess.run(
        ["git", "merge-base", "--is-ancestor", base_commit, commit], cwd=root, check=False,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    if ancestor.returncode != 0 or base_commit == commit:
        raise PromotionError("promotion base must be a distinct ancestor of the candidate")
    paths = git(root, "diff", "--name-only", f"{base_commit}..{commit}").splitlines()
    return base_commit, sorted(set(filter(None, paths)))


def required_evidence(
    contract: dict[str, Any], impact_result: dict[str, Any], platform: str
) -> list[str]:
    definitions = contract["evidence"]
    identities = set(contract["platformMinimumEvidence"][platform])
    identities.update(impact_result.get("promotionRequiredEvidence") or [])
    return sorted(identity for identity in identities if definitions.get(identity, {}).get("platform") == platform)


def validate_record(
    identity: str, record: dict[str, Any], definition: dict[str, Any], release: dict[str, Any],
    commit: str, accepted_warnings: set[str], contract: dict[str, Any], now: datetime,
) -> dict[str, Any]:
    try:
        benchmark_history.validate_record(record)
    except benchmark_history.HistoryError as error:
        raise PromotionError(f"{identity} benchmark record is invalid: {error}") from error
    run = record["run"]
    source = record["source"]
    toolchain = record["toolchain"]
    if (
        run.get("platform") != definition["platform"]
        or run.get("kind") != definition["kind"]
        or run.get("matrixScope") != definition["matrixScope"]
        or run.get("classification") not in definition["classifications"]
    ):
        raise PromotionError(f"{identity} benchmark record has the wrong lane identity")
    if source.get("commit") != commit or source.get("dirty") is not False or source.get("fingerprintsMatch") is not True:
        raise PromotionError(f"{identity} benchmark record is dirty or cross-source")
    if source.get("changedPaths") != []:
        raise PromotionError(f"{identity} benchmark record carries changed source paths")
    if (
        toolchain.get("appVersion") != release.get("marketingVersion")
        or toolchain.get("appBuild") != release.get("buildNumber")
        or not toolchain.get("executableHashes")
        or not toolchain.get("executableUUIDs")
    ):
        raise PromotionError(f"{identity} benchmark record differs from the release build identity")
    warnings = set(run.get("warnings") or [])
    if warnings - set(contract["allowedWarnings"]):
        raise PromotionError(f"{identity} uses warnings not allowed by the promotion contract")
    if warnings - accepted_warnings:
        raise PromotionError(f"{identity} has warnings that were not explicitly accepted")
    finished = parse_time(run.get("finishedAt"), f"{identity}.run.finishedAt")
    age = (now - finished).total_seconds()
    if age < -300 or age > contract["maxEvidenceAgeSeconds"]:
        raise PromotionError(f"{identity} benchmark record is outside the promotion freshness window")
    return {
        "type": "benchmark-record",
        "record": record,
        "recordDigest": record["digest"],
        "runID": run["id"],
        "hardwareProfileID": record["hardware"]["profileID"],
    }


def validate_receipt(
    identity: str, receipt: dict[str, Any], definition: dict[str, Any], commit: str,
    contract_digest: str, max_age_seconds: int, now: datetime,
) -> dict[str, Any]:
    expected_keys = {
        "schemaVersion", "evidenceID", "platform", "sourceCommit", "sourceDirty",
        "command", "commandDigest", "startedAt", "finishedAt", "exitCode", "outputDigest",
        "contractDigest", "digest",
    }
    if set(receipt) != expected_keys or receipt.get("schemaVersion") != 1:
        raise PromotionError(f"{identity} managed-command receipt is malformed")
    unsigned = dict(receipt)
    claimed = unsigned.pop("digest")
    if claimed != digest_value(unsigned):
        raise PromotionError(f"{identity} managed-command receipt digest is invalid")
    if (
        receipt.get("evidenceID") != identity
        or receipt.get("platform") != definition["platform"]
        or receipt.get("sourceCommit") != commit
        or receipt.get("sourceDirty") is not False
        or receipt.get("command") != definition["command"]
        or receipt.get("commandDigest") != digest_value(definition["command"])
        or receipt.get("contractDigest") != contract_digest
        or receipt.get("exitCode") != 0
        or DIGEST_RE.fullmatch(str(receipt.get("outputDigest", ""))) is None
    ):
        raise PromotionError(f"{identity} managed-command receipt is cross-source or did not pass")
    started = parse_time(receipt.get("startedAt"), f"{identity}.startedAt")
    finished = parse_time(receipt.get("finishedAt"), f"{identity}.finishedAt")
    if finished < started:
        raise PromotionError(f"{identity} managed-command receipt has reversed timestamps")
    age = (now - finished).total_seconds()
    if age < -300 or age > max_age_seconds:
        raise PromotionError(f"{identity} managed-command receipt is outside the promotion freshness window")
    return {"type": "managed-command", "receipt": receipt, "receiptDigest": receipt["digest"]}


def assignments(values: list[str], label: str) -> dict[str, Path]:
    result: dict[str, Path] = {}
    for value in values:
        identity, separator, path = value.partition("=")
        if not separator or not identity or not path or identity in result:
            raise PromotionError(f"{label} must use unique evidence-id=path assignments")
        result[identity] = Path(path).resolve()
    return result


def create(args: argparse.Namespace) -> dict[str, Any]:
    root = args.root.resolve()
    contract = load_contract(root)
    impact_contract = evidence_impact.load_contract(root)
    validate_contract(contract, impact_contract)
    release_evidence, commit = release_identity(args.release_evidence.resolve(), args.platform, args.tag, root)
    base_commit, paths = changed_paths(root, args.base, commit)
    impact_result = evidence_impact.classify(impact_contract, paths)
    required = required_evidence(contract, impact_result, args.platform)
    record_paths = assignments(args.record, "--record")
    receipt_paths = assignments(args.receipt, "--receipt")
    supplied = set(record_paths) | set(receipt_paths)
    missing = sorted(set(required) - supplied)
    extra = sorted(supplied - set(required))
    if missing or extra:
        raise PromotionError(f"promotion evidence set differs from required set: missing={missing} extra={extra}")
    accepted = set(args.accept_warning)
    if accepted - set(contract["allowedWarnings"]):
        raise PromotionError("accepted warnings exceed the promotion allowlist")
    now = datetime.now(timezone.utc).replace(microsecond=0)
    contract_digest = digest_value(contract)
    lanes: dict[str, Any] = {}
    for identity in required:
        definition = contract["evidence"][identity]
        if definition["type"] == "benchmark-record":
            path = record_paths.get(identity)
            if path is None:
                raise PromotionError(f"{identity} requires --record")
            lanes[identity] = validate_record(
                identity, read_json(path), definition, release_evidence["release"], commit,
                accepted, contract, now,
            )
        else:
            path = receipt_paths.get(identity)
            if path is None:
                raise PromotionError(f"{identity} requires --receipt")
            lanes[identity] = validate_receipt(
                identity, read_json(path), definition, commit, contract_digest,
                contract["maxEvidenceAgeSeconds"], now,
            )
    manifest: dict[str, Any] = {
        "schemaVersion": SCHEMA_VERSION,
        "platform": args.platform,
        "tag": args.tag,
        "sourceCommit": commit,
        "baseCommit": base_commit,
        "createdAt": now.isoformat().replace("+00:00", "Z"),
        "release": {
            "marketingVersion": release_evidence["release"]["marketingVersion"],
            "buildNumber": release_evidence["release"]["buildNumber"],
            "sourceIdentityDigest": release_evidence["sourceIdentity"]["identityDigest"],
            "releaseEvidenceSHA256": file_digest(args.release_evidence.resolve()),
        },
        "contractDigest": contract_digest,
        "impact": {
            "contractDigest": impact_result["contractDigest"],
            "changedPaths": paths,
            "changedPathsDigest": digest_value(paths),
            "classes": impact_result["classes"],
            "promotionRequiredEvidence": impact_result["promotionRequiredEvidence"],
        },
        "requiredEvidence": required,
        "acceptedWarnings": sorted(accepted),
        "lanes": lanes,
        "privacy": {"containsPrivateDeviceIdentity": False, "containsAbsolutePaths": False},
    }
    manifest["digest"] = digest_value(manifest)
    privacy_scan(manifest, contract)
    return manifest


def validate_manifest(args: argparse.Namespace) -> dict[str, Any]:
    root = args.root.resolve()
    contract = load_contract(root)
    impact_contract = evidence_impact.load_contract(root)
    validate_contract(contract, impact_contract)
    manifest = read_json(args.manifest.resolve())
    expected_top_level = {
        "schemaVersion", "platform", "tag", "sourceCommit", "baseCommit", "createdAt",
        "release", "contractDigest", "impact", "requiredEvidence", "acceptedWarnings",
        "lanes", "privacy", "digest",
    }
    if set(manifest) != expected_top_level:
        raise PromotionError("quality promotion manifest top-level fields are malformed")
    privacy_scan(manifest, contract)
    claimed_digest = manifest.get("digest")
    unsigned = dict(manifest)
    unsigned.pop("digest", None)
    if claimed_digest != digest_value(unsigned):
        raise PromotionError("quality promotion manifest digest is invalid")
    release_evidence, commit = release_identity(args.release_evidence.resolve(), args.platform, args.tag, root)
    if (
        manifest.get("schemaVersion") != SCHEMA_VERSION
        or manifest.get("platform") != args.platform
        or manifest.get("tag") != args.tag
        or manifest.get("sourceCommit") != commit
        or manifest.get("contractDigest") != digest_value(contract)
        or manifest.get("privacy") != {"containsPrivateDeviceIdentity": False, "containsAbsolutePaths": False}
    ):
        raise PromotionError("quality promotion manifest identity is malformed or cross-source")
    release = manifest.get("release")
    if not isinstance(release, dict) or release != {
        "marketingVersion": release_evidence["release"]["marketingVersion"],
        "buildNumber": release_evidence["release"]["buildNumber"],
        "sourceIdentityDigest": release_evidence["sourceIdentity"]["identityDigest"],
        "releaseEvidenceSHA256": file_digest(args.release_evidence.resolve()),
    }:
        raise PromotionError("quality promotion manifest differs from release evidence")
    base_commit, paths = changed_paths(root, str(manifest.get("baseCommit", "")), commit)
    impact_result = evidence_impact.classify(impact_contract, paths)
    impact = manifest.get("impact")
    expected_impact = {
        "contractDigest": impact_result["contractDigest"],
        "changedPaths": paths,
        "changedPathsDigest": digest_value(paths),
        "classes": impact_result["classes"],
        "promotionRequiredEvidence": impact_result["promotionRequiredEvidence"],
    }
    required = required_evidence(contract, impact_result, args.platform)
    if base_commit != manifest.get("baseCommit") or impact != expected_impact or manifest.get("requiredEvidence") != required:
        raise PromotionError("quality promotion impact classification is stale or incomplete")
    accepted = manifest.get("acceptedWarnings")
    if not isinstance(accepted, list) or accepted != sorted(set(accepted)):
        raise PromotionError("quality promotion accepted warnings are malformed")
    lanes = manifest.get("lanes")
    if not isinstance(lanes, dict) or sorted(lanes) != required:
        raise PromotionError("quality promotion lane set is incomplete")
    now = datetime.now(timezone.utc).replace(microsecond=0)
    for identity in required:
        lane = lanes[identity]
        definition = contract["evidence"][identity]
        if not isinstance(lane, dict):
            raise PromotionError(f"{identity} lane is malformed")
        if definition["type"] == "benchmark-record":
            expected = validate_record(
                identity, lane.get("record"), definition, release_evidence["release"], commit,
                set(accepted), contract, now,
            )
        else:
            expected = validate_receipt(
                identity, lane.get("receipt"), definition, commit, digest_value(contract),
                contract["maxEvidenceAgeSeconds"], now,
            )
        if lane != expected:
            raise PromotionError(f"{identity} lane wrapper differs from its evidence")
    return manifest


def capture(args: argparse.Namespace) -> dict[str, Any]:
    root = args.root.resolve()
    contract = load_contract(root)
    impact_contract = evidence_impact.load_contract(root)
    validate_contract(contract, impact_contract)
    definition = contract["evidence"].get(args.evidence_id)
    if not isinstance(definition, dict) or definition.get("type") != "managed-command":
        raise PromotionError("capture requires a managed-command evidence id")
    if args.platform != definition["platform"] or args.command != definition["command"]:
        raise PromotionError("capture command differs from the contract-bound command")
    commit = resolve_commit(root, args.tag)
    if resolve_commit(root, "HEAD") != commit or git(root, "status", "--porcelain", "--untracked-files=all"):
        raise PromotionError("managed quality capture requires a clean tag checkout")
    started = datetime.now(timezone.utc).replace(microsecond=0)
    scratch = root / "build/scratch/transient/quality-promotion"
    scratch.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=scratch, prefix="capture-", delete=False) as output:
        output_path = Path(output.name)
        completed = subprocess.run(args.command, cwd=root, stdout=output, stderr=subprocess.STDOUT, check=False)
    try:
        output_digest = file_digest(output_path)
        sys.stdout.buffer.write(output_path.read_bytes())
    finally:
        output_path.unlink(missing_ok=True)
    finished = datetime.now(timezone.utc).replace(microsecond=0)
    if completed.returncode != 0:
        raise PromotionError(f"managed quality command failed with exit code {completed.returncode}")
    if git(root, "status", "--porcelain", "--untracked-files=all"):
        raise PromotionError("managed quality command changed the source tree")
    receipt: dict[str, Any] = {
        "schemaVersion": 1,
        "evidenceID": args.evidence_id,
        "platform": args.platform,
        "sourceCommit": commit,
        "sourceDirty": False,
        "command": args.command,
        "commandDigest": digest_value(args.command),
        "startedAt": started.isoformat().replace("+00:00", "Z"),
        "finishedAt": finished.isoformat().replace("+00:00", "Z"),
        "exitCode": 0,
        "outputDigest": output_digest,
        "contractDigest": digest_value(contract),
    }
    receipt["digest"] = digest_value(receipt)
    return receipt


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--root", type=Path, default=ROOT, help=argparse.SUPPRESS)
    commands = result.add_subparsers(dest="operation", required=True)
    commands.add_parser("validate-contract")
    capture_parser = commands.add_parser("capture")
    capture_parser.add_argument("--evidence-id", required=True)
    capture_parser.add_argument("--platform", choices=("macos", "ios"), required=True)
    capture_parser.add_argument("--tag", required=True)
    capture_parser.add_argument("--output", type=Path, required=True)
    capture_parser.add_argument("command", nargs=argparse.REMAINDER)
    create_parser = commands.add_parser("create")
    create_parser.add_argument("--platform", choices=("macos", "ios"), required=True)
    create_parser.add_argument("--tag", required=True)
    create_parser.add_argument("--base", required=True)
    create_parser.add_argument("--release-evidence", type=Path, required=True)
    create_parser.add_argument("--record", action="append", default=[])
    create_parser.add_argument("--receipt", action="append", default=[])
    create_parser.add_argument("--accept-warning", action="append", default=[])
    create_parser.add_argument("--output", type=Path, required=True)
    validate_parser = commands.add_parser("validate")
    validate_parser.add_argument("--platform", choices=("macos", "ios"), required=True)
    validate_parser.add_argument("--tag", required=True)
    validate_parser.add_argument("--release-evidence", type=Path, required=True)
    validate_parser.add_argument("--manifest", type=Path, required=True)
    return result


def main() -> int:
    args = parser().parse_args()
    try:
        if args.operation == "validate-contract":
            contract = load_contract(args.root.resolve())
            validate_contract(contract, evidence_impact.load_contract(args.root.resolve()))
            print(f"Quality promotion contract: PASS ({digest_value(contract)})")
            return 0
        if args.operation == "capture":
            if args.command and args.command[0] == "--":
                args.command = args.command[1:]
            value = capture(args)
            atomic_json(args.output.resolve(), value)
        elif args.operation == "create":
            value = create(args)
            atomic_json(args.output.resolve(), value)
        else:
            value = validate_manifest(args)
        print(f"Quality promotion: PASS ({value['digest']})")
        return 0
    except (PromotionError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
