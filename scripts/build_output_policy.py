#!/usr/bin/env python3
"""Validate, inventory, and conservatively migrate Vocello build outputs.

The checked-in manifest is the build-output contract.  This helper intentionally
does not build, clean, or resolve packages.  Migration is opt-in and refuses to
merge divergent trees or move tracked files.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import plistlib
import re
import shlex
import shutil
import stat
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Sequence


LIB_DIRECTORY = Path(__file__).resolve().parent / "lib"
if str(LIB_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(LIB_DIRECTORY))

from build_artifact_retention import analyze_ui_artifacts, summarize_decisions
from profile_trace_retention import (
    RetentionError,
    failed_profile_payload_candidates,
    profile_capture_time,
    valid_failed_profile_for_compaction,
)


SCRIPT_PATH = Path(__file__).resolve()
DEFAULT_REPO_ROOT = SCRIPT_PATH.parent.parent
DEFAULT_MANIFEST_RELATIVE = Path("config/build-output-policy.json")
HISTORY_HELPER_RELATIVE = Path("scripts/benchmark_history.py")
POLICY_DOCUMENTATION_RELATIVE = Path("docs/reference/privacy-storage.md")
POLICY_TABLE_BEGIN = "<!-- BEGIN GENERATED BUILD OUTPUT POLICY TABLE -->"
POLICY_TABLE_END = "<!-- END GENERATED BUILD OUTPUT POLICY TABLE -->"

ENTRY_CLASSES = {"cache", "scratch", "artifact", "distribution"}
CLEANUP_POLICIES = {
    "routine",
    "aggressive",
    "prune-ui-results",
    "governed",
    "preserve",
    "dist",
    "clobber-only",
}
DIRECT_RECLAIM_POLICIES = {
    "routine",
    "aggressive",
    "prune-ui-results",
    "dist",
    "clobber-only",
}
IDENTIFIER_RE = re.compile(r"^[a-z][a-z0-9-]*$")
ENV_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")
MACHO_UUID_RE = re.compile(r"^UUID:\s+([0-9A-Fa-f-]{36})\s+", re.MULTILINE)
METADATA_ALLOWLIST = (
    "producer",
    "status",
    "platform",
    "scheme",
    "configuration",
    "startedAt",
    "finishedAt",
    "gitRevision",
)
HEAVY_LANE_IDS = {
    "development-build",
    "foundation-compile",
    "device-build",
    "runtime-tests",
    "language-benchmark",
    "telemetry-overhead",
    "memory-qualification",
    "ui-smoke",
    "ui-benchmark",
    "ui-delivery-cohort",
    "ui-model-download",
    "ui-enroll-clone-fixture",
    "release",
}


class PolicyError(ValueError):
    """The checked-in policy or repository state violates the contract."""


@dataclass(frozen=True)
class LoadedPolicy:
    repo_root: Path
    manifest_path: Path
    document: dict[str, Any]
    entries: tuple[dict[str, Any], ...]
    entries_by_id: dict[str, dict[str, Any]]

    @property
    def build_root(self) -> Path:
        return self.repo_root / self.document["buildRoot"]


def _relative_posix(value: Any, label: str) -> PurePosixPath:
    if not isinstance(value, str) or not value:
        raise PolicyError(f"{label} must be a non-empty relative POSIX path")
    if "\\" in value:
        raise PolicyError(f"{label} must use POSIX separators: {value!r}")
    path = PurePosixPath(value)
    if path.is_absolute() or value.startswith("~"):
        raise PolicyError(f"{label} must be repository-relative: {value!r}")
    if any(component in {"", ".", ".."} for component in value.split("/")):
        raise PolicyError(f"{label} must be normalized and cannot escape: {value!r}")
    if path.as_posix() != value:
        raise PolicyError(f"{label} must be normalized: {value!r}")
    return path


def _is_same_or_descendant(path: PurePosixPath, parent: PurePosixPath) -> bool:
    return path == parent or path.parts[: len(parent.parts)] == parent.parts


def _assert_non_overlapping(paths: Sequence[tuple[str, PurePosixPath]]) -> None:
    for index, (left_id, left_path) in enumerate(paths):
        for right_id, right_path in paths[index + 1 :]:
            if _is_same_or_descendant(left_path, right_path) or _is_same_or_descendant(
                right_path, left_path
            ):
                raise PolicyError(
                    "managed output roots cannot overlap: "
                    f"{left_id}={left_path} and {right_id}={right_path}"
                )


def _validate_string_list(value: Any, label: str) -> list[str]:
    if not isinstance(value, list) or not all(
        isinstance(item, str) and item for item in value
    ):
        raise PolicyError(f"{label} must be a list of non-empty strings")
    if len(set(value)) != len(value):
        raise PolicyError(f"{label} cannot contain duplicates")
    return value


def _validate_policy_document(document: Any) -> tuple[tuple[dict[str, Any], ...], dict[str, dict[str, Any]]]:
    if not isinstance(document, dict):
        raise PolicyError("policy root must be a JSON object")
    if document.get("schemaVersion") != 1:
        raise PolicyError("unsupported build-output policy schemaVersion")

    build_root = _relative_posix(document.get("buildRoot"), "buildRoot")
    if build_root != PurePosixPath("build"):
        raise PolicyError("buildRoot must remain the repository-local build directory")
    build_root_env = document.get("buildRootEnv")
    if not isinstance(build_root_env, str) or not ENV_RE.fullmatch(build_root_env):
        raise PolicyError("buildRootEnv must be an uppercase shell variable name")
    metadata_filename = document.get("producerMetadataFilename")
    if metadata_filename != "last-build.json":
        raise PolicyError("producerMetadataFilename must be last-build.json")

    raw_entries = document.get("entries")
    if not isinstance(raw_entries, list) or not raw_entries:
        raise PolicyError("entries must be a non-empty array")

    ids: set[str] = set()
    envs: set[str] = {build_root_env}
    paths: list[tuple[str, PurePosixPath]] = []
    entries: list[dict[str, Any]] = []
    for index, raw_entry in enumerate(raw_entries):
        label = f"entries[{index}]"
        if not isinstance(raw_entry, dict):
            raise PolicyError(f"{label} must be an object")
        required = {"id", "path", "class", "owner", "cleanup", "retention", "env"}
        missing = sorted(required.difference(raw_entry))
        if missing:
            raise PolicyError(f"{label} is missing required fields: {', '.join(missing)}")

        entry_id = raw_entry["id"]
        if not isinstance(entry_id, str) or not IDENTIFIER_RE.fullmatch(entry_id):
            raise PolicyError(f"{label}.id is invalid: {entry_id!r}")
        if entry_id in ids:
            raise PolicyError(f"duplicate entry id: {entry_id}")
        ids.add(entry_id)

        entry_path = _relative_posix(raw_entry["path"], f"{label}.path")
        if not _is_same_or_descendant(entry_path, build_root) or entry_path == build_root:
            raise PolicyError(f"{label}.path must be a child of build/: {entry_path}")
        paths.append((entry_id, entry_path))

        entry_class = raw_entry["class"]
        if entry_class not in ENTRY_CLASSES:
            raise PolicyError(f"{label}.class is invalid: {entry_class!r}")
        cleanup = raw_entry["cleanup"]
        if cleanup not in CLEANUP_POLICIES:
            raise PolicyError(f"{label}.cleanup is invalid: {cleanup!r}")
        for field in ("owner", "retention"):
            if not isinstance(raw_entry[field], str) or not raw_entry[field].strip():
                raise PolicyError(f"{label}.{field} must be a non-empty string")

        env = raw_entry["env"]
        if not isinstance(env, str) or not ENV_RE.fullmatch(env):
            raise PolicyError(f"{label}.env is invalid: {env!r}")
        if env in envs:
            raise PolicyError(f"duplicate shell environment name: {env}")
        envs.add(env)
        entries.append(dict(raw_entry))

    _assert_non_overlapping(paths)
    entries_by_id = {entry["id"]: entry for entry in entries}

    raw_links = document.get("publicLinks", [])
    if not isinstance(raw_links, list):
        raise PolicyError("publicLinks must be an array")
    link_paths: set[PurePosixPath] = set()
    for index, link in enumerate(raw_links):
        label = f"publicLinks[{index}]"
        if not isinstance(link, dict):
            raise PolicyError(f"{label} must be an object")
        link_path = _relative_posix(link.get("path"), f"{label}.path")
        if not _is_same_or_descendant(link_path, build_root) or link_path == build_root:
            raise PolicyError(f"{label}.path must be a child of build/")
        if link_path in link_paths:
            raise PolicyError(f"duplicate public link path: {link_path}")
        link_paths.add(link_path)
        if any(_is_same_or_descendant(link_path, path) for _, path in paths):
            raise PolicyError(f"{label}.path cannot be inside a managed output root")
        target_id = link.get("targetEntry")
        if target_id not in entries_by_id:
            raise PolicyError(f"{label}.targetEntry is unknown: {target_id!r}")
        suffix = _relative_posix(link.get("targetSuffix"), f"{label}.targetSuffix")
        if suffix.parts[0] == "build":
            raise PolicyError(f"{label}.targetSuffix must be relative to its target entry")

    external = document.get("externalXcodeDerivedData")
    if not isinstance(external, dict):
        raise PolicyError("externalXcodeDerivedData must be an object")
    external_path = external.get("path")
    if not isinstance(external_path, str) or not external_path.startswith("~/"):
        raise PolicyError("externalXcodeDerivedData.path must be a HOME-relative path")
    if ".." in PurePosixPath(external_path[2:]).parts:
        raise PolicyError("externalXcodeDerivedData.path cannot escape HOME")
    if external.get("policy") != "report-only":
        raise PolicyError("external Xcode DerivedData must remain report-only")
    _validate_string_list(external.get("projectNames"), "externalXcodeDerivedData.projectNames")

    migrations = document.get("migrations", [])
    if not isinstance(migrations, list):
        raise PolicyError("migrations must be an array")
    migration_ids: set[str] = set()
    for index, migration in enumerate(migrations):
        label = f"migrations[{index}]"
        if not isinstance(migration, dict):
            raise PolicyError(f"{label} must be an object")
        migration_id = migration.get("id")
        if not isinstance(migration_id, str) or not IDENTIFIER_RE.fullmatch(migration_id):
            raise PolicyError(f"{label}.id is invalid: {migration_id!r}")
        if migration_id in migration_ids:
            raise PolicyError(f"duplicate migration id: {migration_id}")
        migration_ids.add(migration_id)
        source = _relative_posix(migration.get("source"), f"{label}.source")
        destination = _relative_posix(
            migration.get("destination"), f"{label}.destination"
        )
        mode = migration.get("mode", "move")
        if mode not in {"move", "merge"}:
            raise PolicyError(f"{label}.mode must be move or merge")
        equivalence = migration.get("equivalence", "byte-identical")
        if equivalence not in {"byte-identical", "swiftpm-checkouts"}:
            raise PolicyError(
                f"{label}.equivalence must be byte-identical or swiftpm-checkouts"
            )
        source_allowed = _is_same_or_descendant(source, build_root) or (
            len(source.parts) >= 3
            and source.parts[0] in {"third_party_patches", "Packages"}
            and source.parts[-1] == ".build"
        )
        if not source_allowed:
            raise PolicyError(
                f"{label}.source must be a legacy build root or owned-package .build: {source}"
            )
        if not any(
            _is_same_or_descendant(destination, entry_path) for _, entry_path in paths
        ):
            raise PolicyError(
                f"{label}.destination must be inside a managed output root: {destination}"
            )
        if source == destination or _is_same_or_descendant(destination, source):
            raise PolicyError(f"{label} cannot move a root into itself")

    reference_policy = document.get("referencePolicy")
    if not isinstance(reference_policy, dict):
        raise PolicyError("referencePolicy must be an object")
    for key in ("scanRoots", "excludePrefixes", "retiredPrefixes", "retiredFragments"):
        values = _validate_string_list(reference_policy.get(key), f"referencePolicy.{key}")
        if key == "retiredPrefixes":
            for value in values:
                _relative_posix(value.rstrip("/"), f"referencePolicy.{key}")
        elif key != "retiredFragments":
            for value in values:
                _relative_posix(value, f"referencePolicy.{key}")

    child_retention = document.get("childRetention")
    if not isinstance(child_retention, dict) or child_retention.get("schemaVersion") != 1:
        raise PolicyError("childRetention must be a schema-v1 object")
    ui_retention = child_retention.get("uiResults")
    if not isinstance(ui_retention, dict):
        raise PolicyError("childRetention.uiResults must be an object")
    if ui_retention.get("entry") != "artifacts-ui-tests":
        raise PolicyError("childRetention.uiResults.entry must be artifacts-ui-tests")
    if ui_retention["entry"] not in entries_by_id:
        raise PolicyError("childRetention.uiResults.entry is not a managed entry")
    if ui_retention.get("metadataFilename") != "run.json":
        raise PolicyError("childRetention.uiResults.metadataFilename must be run.json")
    if ui_retention.get("pinFilename") != "retention-pin.json":
        raise PolicyError("childRetention.uiResults.pinFilename must be retention-pin.json")
    lanes = _validate_string_list(ui_retention.get("lanes"), "childRetention.uiResults.lanes")
    if set(lanes) != {"smoke", "benchmark", "model-download"}:
        raise PolicyError("childRetention.uiResults.lanes must cover smoke, benchmark, and model-download")
    for key in (
        "keepPassingPerPlatformLane",
        "keepUnresolvedFailuresPerPlatformLane",
    ):
        value = ui_retention.get(key)
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            raise PolicyError(f"childRetention.uiResults.{key} must be a positive integer")

    profile_retention = child_retention.get("profiles")
    if not isinstance(profile_retention, dict):
        raise PolicyError("childRetention.profiles must be an object")
    profile_entries = _validate_string_list(
        profile_retention.get("entries"), "childRetention.profiles.entries"
    )
    if profile_entries != ["artifacts-macos", "artifacts-ios"]:
        raise PolicyError("childRetention.profiles.entries must be macOS then iOS artifacts")
    if any(entry_id not in entries_by_id for entry_id in profile_entries):
        raise PolicyError("childRetention.profiles references an unknown entry")
    if profile_retention.get("markerFilename") != "profile-retention.json":
        raise PolicyError("childRetention.profiles.markerFilename must be profile-retention.json")
    if profile_retention.get("pinFilename") != "retention-pin.json":
        raise PolicyError("childRetention.profiles.pinFilename must be retention-pin.json")
    for key in (
        "keepFailedPerPlatformKind",
        "maximumCompactedDiagnosticBytes",
        "maximumDiagnosticLogBytes",
    ):
        value = profile_retention.get(key)
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            raise PolicyError(f"childRetention.profiles.{key} must be a positive integer")
    if (
        profile_retention["maximumDiagnosticLogBytes"]
        > profile_retention["maximumCompactedDiagnosticBytes"]
    ):
        raise PolicyError(
            "childRetention.profiles maximumDiagnosticLogBytes cannot exceed the compacted budget"
        )

    heavy_preflight = document.get("heavyLanePreflight")
    if not isinstance(heavy_preflight, dict) or heavy_preflight.get("schemaVersion") != 1:
        raise PolicyError("heavyLanePreflight must be a schema-v1 object")
    heavy_lanes = heavy_preflight.get("lanes")
    if not isinstance(heavy_lanes, dict) or set(heavy_lanes) != HEAVY_LANE_IDS:
        raise PolicyError("heavyLanePreflight.lanes must contain the governed lane set")
    for lane, contract in heavy_lanes.items():
        if not isinstance(contract, dict):
            raise PolicyError(f"heavyLanePreflight.lanes.{lane} must be an object")
        required_bytes = contract.get("requiredFreeBytes")
        if (
            not isinstance(required_bytes, int)
            or isinstance(required_bytes, bool)
            or required_bytes < 1024**3
        ):
            raise PolicyError(
                f"heavyLanePreflight.lanes.{lane}.requiredFreeBytes must be at least one GiB"
            )
        cleanup_hint = contract.get("cleanupHint")
        if (
            not isinstance(cleanup_hint, str)
            or not cleanup_hint.startswith("scripts/clean_build_caches.sh --")
            or any(token in cleanup_hint for token in (";", "|", "&&", "`", "$"))
        ):
            raise PolicyError(
                f"heavyLanePreflight.lanes.{lane}.cleanupHint must be one bounded cleanup command"
            )

    return tuple(entries), entries_by_id


def load_policy(repo_root: Path, manifest_path: Path | None = None) -> LoadedPolicy:
    repo_root = repo_root.expanduser().absolute()
    if not repo_root.is_dir() or repo_root.is_symlink():
        raise PolicyError(f"repository root must be a real directory: {repo_root}")
    selected_manifest = manifest_path or (repo_root / DEFAULT_MANIFEST_RELATIVE)
    if not selected_manifest.is_absolute():
        selected_manifest = repo_root / selected_manifest
    selected_manifest = selected_manifest.absolute()
    try:
        selected_manifest.relative_to(repo_root)
    except ValueError as error:
        raise PolicyError("policy manifest must be inside the repository") from error
    try:
        raw = selected_manifest.read_text(encoding="utf-8")
    except OSError as error:
        raise PolicyError(f"cannot read policy manifest {selected_manifest}: {error}") from error
    try:
        document = json.loads(raw)
    except json.JSONDecodeError as error:
        raise PolicyError(f"invalid policy JSON: {error}") from error
    entries, entries_by_id = _validate_policy_document(document)
    return LoadedPolicy(repo_root, selected_manifest, document, entries, entries_by_id)


def _ensure_existing_path_is_contained(repo_root: Path, path: Path, label: str) -> None:
    try:
        path.relative_to(repo_root)
    except ValueError as error:
        raise PolicyError(f"{label} escapes the repository: {path}") from error
    current = repo_root
    relative = path.relative_to(repo_root)
    for component in relative.parts:
        current = current / component
        if current.is_symlink():
            raise PolicyError(f"{label} contains a symlink path component: {current}")
        if not current.exists():
            break
    if path.exists():
        try:
            path.resolve(strict=True).relative_to(repo_root.resolve(strict=True))
        except (OSError, ValueError) as error:
            raise PolicyError(f"{label} resolves outside the repository: {path}") from error


def _allocated_bytes(path: Path) -> tuple[int, str | None]:
    """Return allocated bytes without following symlinks or double-counting hard links."""

    seen: set[tuple[int, int]] = set()
    total = 0
    errors: list[str] = []

    def visit(candidate: Path) -> None:
        nonlocal total
        try:
            info = candidate.lstat()
        except FileNotFoundError:
            return
        except OSError as error:
            errors.append(f"{candidate}: {error}")
            return
        identity = (info.st_dev, info.st_ino)
        if identity in seen:
            return
        seen.add(identity)
        total += info.st_blocks * 512
        if stat.S_ISDIR(info.st_mode) and not stat.S_ISLNK(info.st_mode):
            try:
                with os.scandir(candidate) as children:
                    for child in children:
                        visit(Path(child.path))
            except OSError as error:
                errors.append(f"{candidate}: {error}")

    visit(path)
    return total, "; ".join(errors[:5]) or None


def _read_last_producer(root: Path, filename: str) -> dict[str, Any] | None:
    metadata = root / filename
    if not metadata.is_file() or metadata.is_symlink():
        return None
    try:
        document = json.loads(metadata.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"valid": False}
    if not isinstance(document, dict):
        return {"valid": False}
    result = {key: document[key] for key in METADATA_ALLOWLIST if key in document}
    result["valid"] = True
    return result


def _path_kind(path: Path) -> str:
    if path.is_symlink():
        return "symlink"
    if path.is_dir():
        return "directory"
    if path.is_file():
        return "file"
    return "missing"


def _plist_path_value(value: Any) -> Path | None:
    if not isinstance(value, str) or not value:
        return None
    if value.startswith("file://"):
        value = value[7:]
    return Path(value).expanduser().absolute()


def _external_xcode_matches(policy: LoadedPolicy) -> dict[str, Any]:
    config = policy.document["externalXcodeDerivedData"]
    configured = os.path.expanduser(config["path"])
    root = Path(os.environ.get("QVOICE_EXTERNAL_XCODE_DERIVED_DATA", configured)).absolute()
    project_path = (policy.repo_root / "QwenVoice.xcodeproj").absolute()
    names = set(config["projectNames"])
    matches: list[dict[str, Any]] = []
    if root.is_dir() and not root.is_symlink():
        try:
            children = sorted(root.iterdir(), key=lambda item: item.name)
        except OSError:
            children = []
        for child in children:
            if not child.is_dir() or child.is_symlink():
                continue
            info_path = child / "info.plist"
            try:
                info = plistlib.loads(info_path.read_bytes())
            except (OSError, plistlib.InvalidFileException):
                continue
            if not isinstance(info, dict):
                continue
            reason: str | None = None
            path_values: list[Path] = []
            for key in ("WorkspacePath", "ProjectPath"):
                candidate = _plist_path_value(info.get(key))
                if candidate is not None:
                    path_values.append(candidate)
                if candidate == project_path:
                    reason = key
                    break
            if reason is None and not path_values:
                candidate_names = {
                    value
                    for key in ("WorkspaceName", "ProjectName")
                    if isinstance((value := info.get(key)), str)
                }
                if candidate_names.intersection(names):
                    reason = "project-name"
            if reason is None:
                continue
            allocated, error = _allocated_bytes(child)
            item: dict[str, Any] = {
                "path": str(child),
                "allocatedBytes": allocated,
                "matchReason": reason,
            }
            if error:
                item["inventoryError"] = error
            matches.append(item)
    return {
        "root": str(root),
        "policy": "report-only",
        "matchingEntries": matches,
        "allocatedBytes": sum(item["allocatedBytes"] for item in matches),
    }


def _load_json_object(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _valid_ui_history_record(policy: LoadedPolicy, run_id: str, platform: str) -> bool:
    record = (
        policy.repo_root
        / "benchmarks"
        / "runs"
        / "ui-generation"
        / f"{run_id}.json"
    )
    payload = _load_json_object(record)
    run = payload.get("run") if payload else None
    if not (
        isinstance(run, dict)
        and run.get("id") == run_id
        and run.get("kind") == "ui-generation"
        and run.get("platform") == platform
        and run.get("status") in {"passed", "passedWithWarnings"}
    ):
        return False
    helper = policy.repo_root / HISTORY_HELPER_RELATIVE
    if not helper.is_file():
        return False
    result = subprocess.run(
        [sys.executable, str(helper), "validate", str(record)],
        cwd=policy.repo_root,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return result.returncode == 0


def _profile_trace_digest(trace: Path) -> str:
    rows = [
        [path.relative_to(trace).as_posix(), _file_digest(path)]
        for path in sorted(trace.rglob("*"))
        if path.is_file() and not path.is_symlink()
    ]
    encoded = json.dumps(
        rows, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _valid_profile_history_record(
    policy: LoadedPolicy,
    run_dir: Path,
    *,
    platform: str,
    trace: Path | None = None,
) -> bool:
    record = (
        policy.repo_root
        / "benchmarks"
        / "runs"
        / "instrument-profile"
        / f"{run_dir.name}.json"
    )
    payload = _load_json_object(record)
    run = payload.get("run") if payload else None
    if not (
        isinstance(run, dict)
        and run.get("id") == run_dir.name
        and run.get("kind") == "instrument-profile"
        and run.get("platform") == platform
        and run.get("status") in {"passed", "passedWithWarnings"}
    ):
        return False
    helper = policy.repo_root / HISTORY_HELPER_RELATIVE
    result = subprocess.run(
        [sys.executable, str(helper), "validate", str(record)],
        cwd=policy.repo_root,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if result.returncode != 0 or trace is None:
        return result.returncode == 0
    trace_evidence = (payload.get("evidence") or {}).get("trace") or {}
    return bool(
        trace_evidence.get("validated") is True
        and trace_evidence.get("digest") == _profile_trace_digest(trace)
    )


def _valid_profile_marker(
    policy: LoadedPolicy,
    marker: dict[str, Any],
    *,
    run_dir: Path,
    trace: Path,
    platform: str,
    kind: str,
) -> bool:
    try:
        capture = profile_capture_time(run_dir.name, platform, kind)
    except RetentionError:
        return False
    return bool(
        marker.get("schemaVersion") == 1
        and marker.get("runID") == run_dir.name
        and marker.get("platform") == platform
        and marker.get("profileKind") == kind
        and marker.get("captureTime") == capture
        and marker.get("originalEphemeralPath")
        == trace.relative_to(policy.repo_root).as_posix()
    )


def _valid_profile_failure_summary(
    policy: LoadedPolicy,
    run_dir: Path,
    trace: Path,
    *,
    platform: str,
    kind: str,
) -> bool:
    summary = _load_json_object(run_dir / "profile-failure-summary.json")
    if not summary:
        return False
    try:
        capture = profile_capture_time(run_dir.name, platform, kind)
    except RetentionError:
        return False
    return bool(
        summary.get("schemaVersion") == 1
        and summary.get("runID") == run_dir.name
        and summary.get("captureTime") == capture
        and summary.get("platform") == platform
        and summary.get("profileKind") == kind
        and summary.get("status") == "failed"
        and summary.get("rawTraceRetained") is True
        and summary.get("originalEphemeralPath")
        == trace.relative_to(policy.repo_root).as_posix()
    )


def _profile_retention_status(policy: LoadedPolicy) -> dict[str, Any]:
    contract = policy.document["childRetention"]["profiles"]
    candidates: list[dict[str, Any]] = []
    latest_published: dict[tuple[str, str], str] = {}
    runs: list[dict[str, Any]] = []
    automatic_reclaimable = 0
    explicit_reclaimable = 0
    blocked = 0
    unclassified = 0
    for entry_id in contract["entries"]:
        entry = policy.entries_by_id[entry_id]
        platform = "macos" if entry_id == "artifacts-macos" else "ios"
        profiles = policy.repo_root / entry["path"] / "profiles"
        if not profiles.is_dir() or profiles.is_symlink():
            continue
        for run_dir in sorted(profiles.iterdir(), key=lambda item: item.name):
            if not run_dir.is_dir() or run_dir.is_symlink():
                continue
            trace = run_dir / f"{run_dir.name}.trace"
            marker = _load_json_object(run_dir / contract["markerFilename"])
            pin = _load_json_object(run_dir / contract["pinFilename"])
            kind = marker.get("profileKind") if marker else None
            marker_valid = bool(
                marker
                and kind in {"cpu", "memory"}
                and _valid_profile_marker(
                    policy,
                    marker,
                    run_dir=run_dir,
                    trace=trace,
                    platform=platform,
                    kind=kind,
                )
            )
            if (
                marker_valid
                and marker.get("status") == "published"
                and _valid_profile_history_record(
                    policy, run_dir, platform=platform
                )
            ):
                key = (platform, kind)
                latest_published[key] = max(
                    latest_published.get(key, ""), marker["captureTime"]
                )
            if (
                marker_valid
                and marker.get("retentionPolicy") == "failedCompactionPending"
                and valid_failed_profile_for_compaction(
                    root=policy.repo_root,
                    marker_path=run_dir / contract["markerFilename"],
                    value=marker,
                )
            ):
                discard, _ = failed_profile_payload_candidates(
                    root=policy.repo_root, artifact_dir=run_dir
                )
                remaining = 0
                errors: list[str] = []
                for path in discard:
                    allocated, error = _allocated_bytes(path)
                    remaining += allocated
                    if error:
                        errors.append(error)
                candidates.append(
                    {
                        "runDir": run_dir,
                        "trace": trace,
                        "path": run_dir,
                        "marker": marker,
                        "markerValid": True,
                        "pending": True,
                        "pin": pin,
                        "platform": platform,
                        "kind": kind,
                        "allocatedBytes": remaining,
                        "inventoryError": "; ".join(errors[:5]) or None,
                    }
                )
                continue
            if not trace.is_dir() or trace.is_symlink():
                continue
            trace_bytes, inventory_error = _allocated_bytes(trace)
            candidates.append(
                {
                    "runDir": run_dir,
                    "trace": trace,
                    "path": trace,
                    "marker": marker,
                    "markerValid": marker_valid,
                    "pin": pin,
                    "platform": platform,
                    "kind": kind,
                    "allocatedBytes": trace_bytes,
                    "inventoryError": inventory_error,
                }
            )

    valid_failures: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for candidate in candidates:
        marker = candidate["marker"]
        if not candidate["markerValid"]:
            candidate.update(action="retain", reason="profile-retention-metadata-missing")
            continue
        if (
            candidate["pin"]
            and candidate["pin"].get("schemaVersion") == 1
            and candidate["pin"].get("pinned") is True
        ):
            candidate.update(action="retain", reason="explicitly-pinned")
            continue
        if candidate.get("pending"):
            candidate.update(
                action="compact-automatic",
                reason="resume-interrupted-profile-compaction",
            )
            continue
        if marker.get("status") == "published":
            if marker.get("retentionPolicy") == "keptExplicitly":
                candidate.update(action="retain", reason="kept-explicitly")
            elif (
                marker.get("retentionPolicy") == "summaryOnly"
                and marker.get("rawTraceRetained") is True
                and _valid_profile_history_record(
                    policy,
                    candidate["runDir"],
                    platform=candidate["platform"],
                    trace=candidate["trace"],
                )
            ):
                candidate.update(action="remove-automatic", reason="published-profile-summary")
            else:
                candidate.update(action="retain", reason="publication-proof-invalid")
            continue
        if (
            marker.get("status") == "failed"
            and marker.get("retentionPolicy") == "failedLatest"
            and marker.get("rawTraceRetained") is True
            and _valid_profile_failure_summary(
                policy,
                candidate["runDir"],
                candidate["trace"],
                platform=candidate["platform"],
                kind=candidate["kind"],
            )
        ):
            valid_failures.setdefault(
                (candidate["platform"], candidate["kind"]), []
            ).append(candidate)
        else:
            candidate.update(action="retain", reason="failed-profile-proof-invalid")

    keep_failures = contract["keepFailedPerPlatformKind"]
    for key, failures in valid_failures.items():
        failures.sort(
            key=lambda item: (item["marker"]["captureTime"], item["runDir"].name),
            reverse=True,
        )
        retained = 0
        for candidate in failures:
            capture = candidate["marker"]["captureTime"]
            resolved = latest_published.get(key, "") > capture
            if resolved or retained >= keep_failures:
                candidate.update(
                    action="compact-automatic",
                    reason=("resolved-by-newer-profile-pass" if resolved else "superseded-failed-profile"),
                )
                continue
            retained += 1
            toc = candidate["runDir"] / "trace-toc.xml"
            if toc.is_file() and toc.stat().st_size > 0:
                candidate.update(
                    action="compact-explicitly", reason="acknowledge-failed-profile"
                )
            else:
                candidate.update(action="retain", reason="failed-profile-summary-incomplete")

    for candidate in candidates:
        action = candidate.get("action", "retain")
        allocated = candidate["allocatedBytes"]
        automatic = allocated if action in {"remove-automatic", "compact-automatic"} else 0
        explicit = allocated if action == "compact-explicitly" else 0
        if automatic:
            automatic_reclaimable += automatic
        elif explicit:
            explicit_reclaimable += explicit
        else:
            blocked += allocated
        if candidate.get("reason") == "profile-retention-metadata-missing":
            unclassified += allocated
        item: dict[str, Any] = {
            "path": candidate["path"].relative_to(policy.repo_root).as_posix(),
            "runID": candidate["runDir"].name,
            "platform": candidate["platform"],
            "allocatedBytes": allocated,
            "action": action,
            "reason": candidate.get("reason"),
            "automaticReclaimableBytes": automatic,
            "explicitReclaimableBytes": explicit,
        }
        if candidate["inventoryError"]:
            item["inventoryError"] = candidate["inventoryError"]
        runs.append(item)
    return {
        "automaticReclaimableBytes": automatic_reclaimable,
        "explicitReclaimableBytes": explicit_reclaimable,
        "blockedBytes": blocked,
        "unclassifiedBytes": unclassified,
        "runs": runs,
    }


def build_status(policy: LoadedPolicy) -> dict[str, Any]:
    roots: list[dict[str, Any]] = []
    totals: dict[str, int] = {cleanup: 0 for cleanup in sorted(CLEANUP_POLICIES)}
    allocated_total = 0
    metadata_filename = policy.document["producerMetadataFilename"]
    ui_contract = policy.document["childRetention"]["uiResults"]
    ui_analysis: dict[str, Any] | None = None
    for entry in policy.entries:
        path = policy.repo_root / entry["path"]
        _ensure_existing_path_is_contained(policy.repo_root, path, entry["id"])
        allocated, error = _allocated_bytes(path)
        allocated_total += allocated
        reclaimable = allocated if entry["cleanup"] in DIRECT_RECLAIM_POLICIES else 0
        blocked = max(0, allocated - reclaimable)
        if entry["id"] == ui_contract["entry"]:
            decisions = analyze_ui_artifacts(
                repo_root=policy.repo_root,
                ui_root=path,
                keep_passing=ui_contract["keepPassingPerPlatformLane"],
                keep_unresolved_failures=ui_contract[
                    "keepUnresolvedFailuresPerPlatformLane"
                ],
                lanes=ui_contract["lanes"],
                history_validator=lambda run_id, platform: _valid_ui_history_record(
                    policy, run_id, platform
                ),
            )
            ui_analysis = summarize_decisions(decisions)
            reclaimable = ui_analysis["reclaimableBytes"]
            blocked = max(0, allocated - reclaimable)
        totals[entry["cleanup"]] += reclaimable
        item: dict[str, Any] = {
            "id": entry["id"],
            "path": entry["path"],
            "class": entry["class"],
            "owner": entry["owner"],
            "cleanup": entry["cleanup"],
            "retention": entry["retention"],
            "exists": path.exists(),
            "kind": _path_kind(path),
            "allocatedBytes": allocated,
            "reclaimableBytes": reclaimable,
            "eligibleReclaimBytes": reclaimable,
            "blockedReclaimBytes": blocked,
            "lastProducer": _read_last_producer(path, metadata_filename),
        }
        if entry["id"] == ui_contract["entry"] and ui_analysis is not None:
            item["retentionAnalysis"] = ui_analysis
        if error:
            item["inventoryError"] = error
        roots.append(item)

    unowned_roots = _unowned_build_roots(policy)
    unowned_allocated = sum(item["allocatedBytes"] for item in unowned_roots)
    disk = shutil.disk_usage(policy.repo_root)
    profile_analysis = _profile_retention_status(policy)
    for platform, entry_id in (("macos", "artifacts-macos"), ("ios", "artifacts-ios")):
        automatic = sum(
            item["automaticReclaimableBytes"]
            for item in profile_analysis["runs"]
            if item["platform"] == platform
        )
        if not automatic:
            continue
        root = next(item for item in roots if item["id"] == entry_id)
        root["reclaimableBytes"] += automatic
        root["eligibleReclaimBytes"] += automatic
        root["blockedReclaimBytes"] = max(0, root["blockedReclaimBytes"] - automatic)
        totals[root["cleanup"]] += automatic
    return {
        "schemaVersion": 1,
        "manifest": str(policy.manifest_path),
        "repositoryRoot": str(policy.repo_root),
        "buildRoot": policy.document["buildRoot"],
        "allocatedBytes": allocated_total + unowned_allocated,
        "managedAllocatedBytes": allocated_total,
        "unownedAllocatedBytes": unowned_allocated,
        "reclaimableBytesByPolicy": totals,
        "filesystem": {
            "totalBytes": disk.total,
            "usedBytes": disk.used,
            "freeBytes": disk.free,
        },
        "retentionSummary": {
            "uiResults": ui_analysis or summarize_decisions([]),
            "profiles": profile_analysis,
            "automaticReclaimableBytes": profile_analysis[
                "automaticReclaimableBytes"
            ],
            "explicitReclaimableBytes": profile_analysis["explicitReclaimableBytes"],
        },
        "roots": roots,
        "unownedRoots": unowned_roots,
        "externalXcodeDerivedData": _external_xcode_matches(policy),
    }


def _unowned_build_roots(policy: LoadedPolicy) -> list[dict[str, Any]]:
    """Report generated top-level roots that are outside the manifest contract."""

    build = policy.build_root
    if not build.is_dir() or build.is_symlink():
        return []
    allowed = {
        PurePosixPath(entry["path"]).parts[1]
        for entry in policy.entries
    }
    allowed.update(
        PurePosixPath(link["path"]).parts[1]
        for link in policy.document.get("publicLinks", [])
    )
    # Finder may recreate this metadata file whenever the ignored build folder
    # is viewed. It is neither a producer root nor build evidence.
    allowed.add(".DS_Store")
    result: list[dict[str, Any]] = []
    for child in sorted(build.iterdir(), key=lambda item: item.name):
        if child.name in allowed:
            continue
        _ensure_existing_path_is_contained(policy.repo_root, child, "unowned build root")
        allocated, error = _allocated_bytes(child)
        item: dict[str, Any] = {
            "path": child.relative_to(policy.repo_root).as_posix(),
            "kind": _path_kind(child),
            "allocatedBytes": allocated,
        }
        if error:
            item["inventoryError"] = error
        result.append(item)
    return result


def _markdown_cell(value: Any) -> str:
    """Render one manifest string as a stable single-line Markdown table cell."""

    return " ".join(str(value).split()).replace("|", "\\|")


def render_policy_markdown_table(policy: LoadedPolicy) -> str:
    """Render the checked-in owner/lifetime table directly from the manifest."""

    lines = [
        POLICY_TABLE_BEGIN,
        "| Path | Owner | Class | Cleanup | Retention |",
        "| --- | --- | --- | --- | --- |",
    ]
    for entry in policy.entries:
        path = _markdown_cell(entry["path"] + "/")
        owner = _markdown_cell(entry["owner"])
        entry_class = _markdown_cell(entry["class"])
        cleanup = _markdown_cell(entry["cleanup"])
        retention = _markdown_cell(entry["retention"])
        lines.append(
            f"| `{path}` | {owner} | `{entry_class}` | `{cleanup}` | {retention} |"
        )
    lines.append(POLICY_TABLE_END)
    return "\n".join(lines)


def _git_tracked_files(policy: LoadedPolicy) -> list[str]:
    if not (policy.repo_root / ".git").exists():
        return []
    result = subprocess.run(
        ["git", "-C", str(policy.repo_root), "ls-files", "-z"],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result.returncode != 0:
        raise PolicyError("cannot enumerate tracked files for build-output validation")
    return [
        value.decode("utf-8", "surrogateescape")
        for value in result.stdout.split(b"\0")
        if value
    ]


def _selected_for_reference_scan(path: str, reference_policy: dict[str, Any]) -> bool:
    pure = PurePosixPath(path)
    selected = any(
        _is_same_or_descendant(pure, PurePosixPath(root))
        for root in reference_policy["scanRoots"]
    )
    excluded = any(
        _is_same_or_descendant(pure, PurePosixPath(prefix))
        for prefix in reference_policy["excludePrefixes"]
    )
    return selected and not excluded


def _tracked_reference_violations(policy: LoadedPolicy) -> list[str]:
    reference_policy = policy.document["referencePolicy"]
    retired = list(reference_policy["retiredPrefixes"]) + list(
        reference_policy["retiredFragments"]
    )
    absolute_build = str(policy.repo_root / policy.document["buildRoot"])
    violations: list[str] = []
    for relative in _git_tracked_files(policy):
        if not _selected_for_reference_scan(relative, reference_policy):
            continue
        path = policy.repo_root / relative
        try:
            raw = path.read_bytes()
        except OSError:
            continue
        if b"\0" in raw:
            continue
        text = raw.decode("utf-8", "replace")
        for line_number, line in enumerate(text.splitlines(), start=1):
            for marker in retired:
                if marker in line:
                    violations.append(
                        f"{relative}:{line_number}: retired build-output reference {marker!r}"
                    )
            if absolute_build in line:
                violations.append(
                    f"{relative}:{line_number}: absolute repository build path is not portable"
                )
    return sorted(set(violations))


def _documentation_table_violations(policy: LoadedPolicy) -> list[str]:
    """Require the tracked policy table to equal the deterministic manifest render."""

    relative = POLICY_DOCUMENTATION_RELATIVE.as_posix()
    if relative not in set(_git_tracked_files(policy)):
        return []
    path = policy.repo_root / POLICY_DOCUMENTATION_RELATIVE
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        return [f"{relative}: cannot read generated build-output policy table: {error}"]

    if text.count(POLICY_TABLE_BEGIN) != 1 or text.count(POLICY_TABLE_END) != 1:
        return [
            f"{relative}: generated build-output policy table markers are missing or duplicated"
        ]
    start = text.index(POLICY_TABLE_BEGIN)
    end = text.index(POLICY_TABLE_END, start) + len(POLICY_TABLE_END)
    actual = text[start:end]
    expected = render_policy_markdown_table(policy)
    if actual != expected:
        return [
            f"{relative}: generated build-output policy table is stale; "
            "replace it with `python3 scripts/build_output_policy.py status --markdown` output"
        ]
    return []


def _public_link_violations(policy: LoadedPolicy) -> list[str]:
    violations: list[str] = []
    for link in policy.document.get("publicLinks", []):
        link_path = policy.repo_root / link["path"]
        target_entry = policy.entries_by_id[link["targetEntry"]]
        expected = policy.repo_root / target_entry["path"] / link["targetSuffix"]
        if not link_path.exists() and not link_path.is_symlink():
            continue
        if not link_path.is_symlink():
            violations.append(f"{link['path']}: public compatibility path must be a symlink")
            continue
        actual = (link_path.parent / os.readlink(link_path)).resolve(strict=False)
        if actual != expected.resolve(strict=False):
            violations.append(
                f"{link['path']}: symlink target does not match {expected.relative_to(policy.repo_root)}"
            )
    return violations


def _macho_uuids(path: Path) -> tuple[set[str], str | None]:
    try:
        result = subprocess.run(
            ["xcrun", "dwarfdump", "--uuid", str(path)],
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except OSError as error:
        return set(), str(error)
    uuids = {value.upper() for value in MACHO_UUID_RE.findall(result.stdout)}
    if result.returncode != 0 or not uuids:
        detail = result.stderr.strip() or "no Mach-O UUID reported"
        return set(), detail
    return uuids, None


def _repair_preserved_dsym(
    label: str,
    binary_uuids: set[str],
    source_dsym: Path,
    target_dsym: Path,
    repo_root: Path,
) -> str | None:
    """Re-preserve the products-directory dSYM when it proves identity.

    Every build writes a fresh dSYM beside its product, so a stale preserved
    copy is repairable from local ground truth: adopt the sibling dSYM only
    after its Mach-O UUIDs cover the current binary, staging the copy and
    re-validating before it replaces the preserved tree. Returns None on a
    successful repair, otherwise the reason the local source cannot be
    trusted (which keeps the check fail-closed).
    """

    if not source_dsym.is_dir():
        return f"no rebuilt dSYM beside the product at {source_dsym.relative_to(repo_root)}"
    source_uuids, source_error = _macho_uuids(source_dsym)
    if source_error:
        return f"cannot inspect the rebuilt dSYM beside the product: {source_error}"
    missing = sorted(binary_uuids.difference(source_uuids))
    if missing:
        return (
            "the rebuilt dSYM beside the product does not cover current UUID(s): "
            + ", ".join(missing)
        )
    staging = target_dsym.with_name("repair-staging-" + target_dsym.name)
    if staging.exists():
        shutil.rmtree(staging)
    target_dsym.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source_dsym, staging)
    staged_uuids, staged_error = _macho_uuids(staging)
    if staged_error or binary_uuids.difference(staged_uuids):
        shutil.rmtree(staging, ignore_errors=True)
        return "the re-preserved dSYM copy failed UUID validation"
    if target_dsym.exists():
        shutil.rmtree(target_dsym)
    staging.rename(target_dsym)
    print(
        f"note: {label}: preserved dSYM re-synced from "
        f"{source_dsym.relative_to(repo_root)}",
        file=sys.stderr,
    )
    return None


def _symbol_identity_violations(policy: LoadedPolicy) -> list[str]:
    """Validate retained symbols whenever their canonical product exists.

    A stale preserved dSYM self-heals from the dSYM sitting beside the
    current product (see _repair_preserved_dsym); the check fails only when
    no local dSYM can prove identity for the current binary.
    """

    macos_cache = policy.repo_root / policy.entries_by_id["xcode-macos-derived-data"]["path"]
    ios_cache = policy.repo_root / policy.entries_by_id["xcode-ios-device-derived-data"]["path"]
    macos_symbols = policy.repo_root / policy.entries_by_id["symbols-macos"]["path"]
    ios_symbols = policy.repo_root / policy.entries_by_id["symbols-ios"]["path"]
    macos_products = macos_cache / "Build/Products/Release"
    ios_products = ios_cache / "Build/Products/Release-iphoneos"
    checks = (
        (
            "macOS Vocello",
            macos_products / "Vocello.app/Contents/MacOS/Vocello",
            macos_symbols / "Vocello.app.dSYM",
            macos_products / "Vocello.app.dSYM",
        ),
        (
            "macOS QwenVoiceEngineService",
            macos_products
            / "Vocello.app/Contents/XPCServices/"
            "QwenVoiceEngineService.xpc/Contents/MacOS/QwenVoiceEngineService",
            macos_symbols / "QwenVoiceEngineService.xpc.dSYM",
            macos_products / "QwenVoiceEngineService.xpc.dSYM",
        ),
        (
            "iOS Vocello",
            ios_products / "Vocello.app/Vocello",
            ios_symbols / "Vocello.app.dSYM",
            ios_products / "Vocello.app.dSYM",
        ),
    )
    violations: list[str] = []
    for label, binary, dsym, sibling in checks:
        if not binary.is_file():
            continue
        binary_uuids, binary_error = _macho_uuids(binary)
        if binary_error:
            violations.append(f"{label}: cannot inspect current binary UUID: {binary_error}")
            continue
        if not dsym.is_dir():
            repair_failure = _repair_preserved_dsym(
                label, binary_uuids, sibling, dsym, policy.repo_root
            )
            if repair_failure:
                violations.append(
                    f"{label}: current product exists but preserved dSYM is missing at "
                    f"{dsym.relative_to(policy.repo_root)}; {repair_failure}"
                )
            continue
        dsym_uuids, dsym_error = _macho_uuids(dsym)
        if dsym_error:
            violations.append(f"{label}: cannot inspect preserved dSYM UUID: {dsym_error}")
            continue
        missing = sorted(binary_uuids.difference(dsym_uuids))
        if missing:
            repair_failure = _repair_preserved_dsym(
                label, binary_uuids, sibling, dsym, policy.repo_root
            )
            if repair_failure:
                violations.append(
                    f"{label}: preserved dSYM does not match current product UUID(s): "
                    + ", ".join(missing)
                    + f"; {repair_failure}"
                )
    return violations


def validate_repository(policy: LoadedPolicy) -> list[str]:
    violations: list[str] = []
    for entry in policy.entries:
        path = policy.repo_root / entry["path"]
        try:
            _ensure_existing_path_is_contained(policy.repo_root, path, entry["id"])
        except PolicyError as error:
            violations.append(str(error))
    violations.extend(_public_link_violations(policy))
    violations.extend(
        f"{item['path']}: unowned generated root; migrate it into the build-output policy"
        for item in _unowned_build_roots(policy)
    )
    violations.extend(_tracked_reference_violations(policy))
    violations.extend(_documentation_table_violations(policy))
    violations.extend(_symbol_identity_violations(policy))
    return sorted(set(violations))


def shell_environment(policy: LoadedPolicy) -> list[tuple[str, str]]:
    values = [
        (policy.document["buildRootEnv"], str(policy.build_root)),
    ]
    values.extend(
        (entry["env"], str(policy.repo_root / entry["path"]))
        for entry in policy.entries
    )
    return values


def _tracked_under(policy: LoadedPolicy, relative: str) -> list[str]:
    if not (policy.repo_root / ".git").exists():
        return []
    result = subprocess.run(
        ["git", "-C", str(policy.repo_root), "ls-files", "-z", "--", relative],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result.returncode != 0:
        raise PolicyError(f"cannot inspect tracked content under {relative}")
    return [
        value.decode("utf-8", "replace")
        for value in result.stdout.split(b"\0")
        if value
    ]


def _file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _tree_signature(path: Path) -> tuple[Any, ...]:
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode):
        return ("symlink", os.readlink(path))
    if stat.S_ISREG(info.st_mode):
        return ("file", stat.S_IMODE(info.st_mode), info.st_size, _file_digest(path))
    if stat.S_ISDIR(info.st_mode):
        children = tuple(
            (child.name, _tree_signature(child))
            for child in sorted(path.iterdir(), key=lambda item: item.name)
        )
        return ("directory", children)
    return ("special", stat.S_IFMT(info.st_mode), info.st_size)


def _trees_identical(left: Path, right: Path) -> bool:
    try:
        return _tree_signature(left) == _tree_signature(right)
    except OSError:
        return False


def _git_output(checkout: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(checkout), *arguments],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise PolicyError(
            f"cannot verify SwiftPM checkout {checkout.name}: "
            f"{' '.join(arguments)} failed"
        )
    return result.stdout.strip()


def _swiftpm_store_signature(path: Path) -> tuple[Any, ...]:
    """Compare resolver identity and clean checkout revisions, not Git internals.

    Xcode embeds absolute repository/alternates paths and mutable Git indexes in
    each SourcePackages copy. Those bytes necessarily differ by DerivedData
    location even when both stores resolve the exact same immutable sources.
    """

    workspace = path / "workspace-state.json"
    checkouts = path / "checkouts"
    if not workspace.is_file() or not checkouts.is_dir():
        raise PolicyError(f"incomplete SwiftPM SourcePackages store: {path}")
    try:
        workspace_value = json.loads(workspace.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise PolicyError(f"invalid SwiftPM workspace-state.json in {path}") from error
    workspace_digest = hashlib.sha256(
        json.dumps(
            workspace_value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()
    revisions: list[tuple[str, str, str]] = []
    for checkout in sorted(checkouts.iterdir(), key=lambda item: item.name):
        if checkout.name == ".DS_Store":
            continue
        if checkout.is_symlink() or not checkout.is_dir():
            raise PolicyError(f"unexpected SwiftPM checkout entry: {checkout}")
        revision = _git_output(checkout, "rev-parse", "HEAD")
        dirty = _git_output(checkout, "status", "--porcelain", "--untracked-files=no")
        if dirty:
            raise PolicyError(f"SwiftPM checkout has tracked modifications: {checkout}")
        submodules = _git_output(checkout, "submodule", "status", "--recursive")
        if any(line[:1] in {"-", "+", "U"} for line in submodules.splitlines() if line):
            raise PolicyError(f"SwiftPM checkout has unresolved submodule state: {checkout}")
        revisions.append((checkout.name, revision, submodules))
    return (workspace_digest, tuple(revisions))


def _migration_sources_equivalent(
    left: Path, right: Path, equivalence: str
) -> bool:
    if _trees_identical(left, right):
        return True
    if equivalence != "swiftpm-checkouts":
        return False
    try:
        return _swiftpm_store_signature(left) == _swiftpm_store_signature(right)
    except PolicyError:
        return False


def _is_excluded_migration_source(path: Path, exclusions: Sequence[Path]) -> bool:
    return any(path == exclusion or exclusion in path.parents for exclusion in exclusions)


def _merge_conflict(
    source: Path, destination: Path, exclusions: Sequence[Path]
) -> str | None:
    """Return the first unsafe merge collision without mutating either tree."""

    if _is_excluded_migration_source(source, exclusions):
        return None
    if not destination.exists() and not destination.is_symlink():
        return None
    if source.is_symlink() or destination.is_symlink():
        return None if _trees_identical(source, destination) else str(destination)
    if source.is_dir() and destination.is_dir():
        for child in sorted(source.iterdir(), key=lambda item: item.name):
            conflict = _merge_conflict(child, destination / child.name, exclusions)
            if conflict:
                return conflict
        return None
    return None if _trees_identical(source, destination) else str(destination)


def _migration_item(
    migration: dict[str, Any], action: str, reason: str, *, blocking: bool = False
) -> dict[str, Any]:
    item = {
        "id": migration["id"],
        "source": migration["source"],
        "destination": migration["destination"],
        "action": action,
        "reason": reason,
        "blocking": blocking,
    }
    if "equivalence" in migration:
        item["equivalence"] = migration["equivalence"]
    return item


def plan_migration(policy: LoadedPolicy) -> list[dict[str, Any]]:
    planned: list[dict[str, Any]] = []
    future_destinations: dict[Path, Path] = {}
    for migration in policy.document.get("migrations", []):
        source = policy.repo_root / migration["source"]
        destination = policy.repo_root / migration["destination"]
        try:
            _ensure_existing_path_is_contained(policy.repo_root, source, migration["id"])
            _ensure_existing_path_is_contained(
                policy.repo_root, destination.parent, migration["id"]
            )
        except PolicyError as error:
            planned.append(_migration_item(migration, "blocked", str(error), blocking=True))
            continue
        tracked = _tracked_under(policy, migration["source"])
        if tracked:
            planned.append(
                _migration_item(
                    migration,
                    "blocked",
                    "source contains tracked content: " + ", ".join(tracked[:5]),
                    blocking=True,
                )
            )
            continue
        if not source.exists() and not source.is_symlink():
            action = "already-migrated" if destination.exists() else "not-present"
            reason = "legacy source is absent and destination exists" if destination.exists() else "legacy source is absent"
            planned.append(_migration_item(migration, action, reason))
            continue
        if source.is_symlink():
            planned.append(
                _migration_item(
                    migration,
                    "blocked",
                    "legacy source is a symlink",
                    blocking=True,
                )
            )
            continue
        if migration.get("mode", "move") == "merge":
            if not source.is_dir():
                planned.append(
                    _migration_item(
                        migration,
                        "blocked",
                        "merge migration source is not a directory",
                        blocking=True,
                    )
                )
                continue
            prior_sources = [
                policy.repo_root / prior["source"]
                for prior in planned
                if not prior["blocking"]
                and prior["action"] in {"move", "remove-identical-duplicate"}
                and _is_same_or_descendant(
                    PurePosixPath(prior["source"]), PurePosixPath(migration["source"])
                )
            ]
            conflict = _merge_conflict(source, destination, prior_sources)
            if conflict:
                planned.append(
                    _migration_item(
                        migration,
                        "blocked",
                        f"merge would overwrite non-identical destination content: {conflict}",
                        blocking=True,
                    )
                )
            else:
                planned.append(
                    _migration_item(
                        migration,
                        "merge",
                        "remaining untracked content can be merged without overwriting differences",
                    )
                )
            continue
        comparison = destination if destination.exists() else future_destinations.get(destination)
        if comparison is not None:
            if _migration_sources_equivalent(
                source, comparison, migration.get("equivalence", "byte-identical")
            ):
                planned.append(
                    _migration_item(
                        migration,
                        "remove-identical-duplicate",
                        "destination (or an earlier source for it) is equivalent under the declared policy",
                    )
                )
            else:
                planned.append(
                    _migration_item(
                        migration,
                        "blocked",
                        "destination exists or is planned from different content",
                        blocking=True,
                    )
                )
            continue
        future_destinations[destination] = source
        planned.append(
            _migration_item(
                migration,
                "move",
                "untracked legacy source can be atomically renamed",
            )
        )
    planned.extend(_plan_public_links(policy, planned))
    return planned


def _future_source_for_destination(
    policy: LoadedPolicy, expected: Path, migration_plan: Sequence[dict[str, Any]]
) -> Path | None:
    for item in migration_plan:
        if item["blocking"] or item["action"] not in {"move", "merge"}:
            continue
        destination = policy.repo_root / item["destination"]
        try:
            relative = expected.relative_to(destination)
        except ValueError:
            continue
        return policy.repo_root / item["source"] / relative
    return None


def _plan_public_links(
    policy: LoadedPolicy, migration_plan: Sequence[dict[str, Any]]
) -> list[dict[str, Any]]:
    planned: list[dict[str, Any]] = []
    for link in policy.document.get("publicLinks", []):
        link_path = policy.repo_root / link["path"]
        target_entry = policy.entries_by_id[link["targetEntry"]]
        expected = policy.repo_root / target_entry["path"] / link["targetSuffix"]
        comparison = expected if expected.exists() else _future_source_for_destination(
            policy, expected, migration_plan
        )
        item = {
            "id": "public-link-" + link_path.name.lower().replace(".", "-"),
            "source": link["path"],
            "destination": str(expected.relative_to(policy.repo_root)),
            "blocking": False,
        }
        if link_path.is_symlink():
            actual = (link_path.parent / os.readlink(link_path)).resolve(strict=False)
            if actual == expected.resolve(strict=False):
                item.update(action="already-migrated", reason="public symlink already targets the canonical product")
            elif comparison is not None and actual == comparison.resolve(strict=False):
                item.update(action="replace-symlink", reason="public symlink targets the legacy product scheduled for migration")
            else:
                item.update(action="blocked", reason="public symlink has an unknown target", blocking=True)
            planned.append(item)
            continue
        if not link_path.exists():
            if comparison is None or not comparison.exists():
                item.update(action="not-present", reason="neither public path nor canonical product exists")
            else:
                item.update(action="create-symlink", reason="canonical product exists or is scheduled for migration")
            planned.append(item)
            continue
        if comparison is None or not comparison.exists():
            item.update(action="blocked", reason="cannot verify copied public product because canonical product is absent", blocking=True)
        elif _trees_identical(link_path, comparison):
            item.update(action="replace-with-symlink", reason="copied public product is byte-identical to the canonical product")
        else:
            item.update(action="blocked", reason="copied public product differs from the canonical product", blocking=True)
        planned.append(item)
    return planned


def _remove_untracked_duplicate(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink()


def _rewrite_swiftpm_store_location(path: Path, old_root: Path, new_root: Path) -> None:
    """Repair Xcode's location-specific Git metadata after an atomic store move."""

    old = str(old_root.absolute()).encode("utf-8")
    new = str(new_root.absolute()).encode("utf-8")
    for candidate in sorted(path.rglob("*")):
        if candidate.is_symlink() or not candidate.is_file() or ".git" not in candidate.parts:
            continue
        relative_git = candidate.parts[candidate.parts.index(".git") :]
        allowed = (
            candidate.name in {"config", "alternates", ".git"}
            or "logs" in relative_git
        )
        if not allowed:
            continue
        try:
            payload = candidate.read_bytes()
        except OSError as error:
            raise PolicyError(f"cannot inspect moved SwiftPM metadata: {candidate}") from error
        if old not in payload:
            continue
        replacement = payload.replace(old, new)
        temporary = candidate.with_name(f".{candidate.name}.policy-rewrite-{os.getpid()}")
        if temporary.exists() or temporary.is_symlink():
            raise PolicyError(f"temporary SwiftPM metadata path already exists: {temporary}")
        temporary.write_bytes(replacement)
        os.chmod(temporary, stat.S_IMODE(candidate.stat().st_mode))
        os.replace(temporary, candidate)
    _swiftpm_store_signature(path)


def _merge_tree_safely(source: Path, destination: Path) -> None:
    if not destination.exists() and not destination.is_symlink():
        destination.parent.mkdir(parents=True, exist_ok=True)
        os.replace(source, destination)
        return
    if not source.is_dir() or source.is_symlink() or not destination.is_dir() or destination.is_symlink():
        if _trees_identical(source, destination):
            _remove_untracked_duplicate(source)
            return
        raise PolicyError(f"refusing non-identical migration merge at {destination}")
    for child in sorted(source.iterdir(), key=lambda item: item.name):
        _merge_tree_safely(child, destination / child.name)
    source.rmdir()


def _install_relative_symlink(link_path: Path, target: Path, replace_copy: bool) -> None:
    link_path.parent.mkdir(parents=True, exist_ok=True)
    relative_target = os.path.relpath(target, start=link_path.parent)
    temporary_link = link_path.parent / f".{link_path.name}.policy-link-{os.getpid()}"
    backup = link_path.parent / f".{link_path.name}.policy-backup-{os.getpid()}"
    if temporary_link.exists() or temporary_link.is_symlink() or backup.exists():
        raise PolicyError(f"temporary migration path already exists beside {link_path}")
    os.symlink(relative_target, temporary_link)
    if not replace_copy:
        os.replace(temporary_link, link_path)
        return
    os.replace(link_path, backup)
    try:
        os.replace(temporary_link, link_path)
    except BaseException:
        os.replace(backup, link_path)
        if temporary_link.exists() or temporary_link.is_symlink():
            temporary_link.unlink()
        raise
    _remove_untracked_duplicate(backup)


def apply_migration(policy: LoadedPolicy, plan: list[dict[str, Any]]) -> list[dict[str, Any]]:
    blockers = [item for item in plan if item["blocking"]]
    if blockers:
        raise PolicyError("migration has blocking conflicts; no changes were made")
    results: list[dict[str, Any]] = []
    for item in plan:
        source = policy.repo_root / item["source"]
        destination = policy.repo_root / item["destination"]
        action = item["action"]
        if action == "move":
            destination.parent.mkdir(parents=True, exist_ok=True)
            os.replace(source, destination)
            if (
                item.get("equivalence") == "swiftpm-checkouts"
                and (destination / "workspace-state.json").is_file()
                and (destination / "checkouts").is_dir()
            ):
                _rewrite_swiftpm_store_location(destination, source, destination)
            result = dict(item)
            result["applied"] = True
            results.append(result)
        elif action == "merge":
            _merge_tree_safely(source, destination)
            result = dict(item)
            result["applied"] = True
            results.append(result)
        elif action == "remove-identical-duplicate":
            if not _migration_sources_equivalent(
                source,
                destination,
                str(item.get("equivalence", "byte-identical")),
            ):
                raise PolicyError(
                    f"migration duplicate changed after planning: {source}"
                )
            _remove_untracked_duplicate(source)
            result = dict(item)
            result["applied"] = True
            results.append(result)
        elif action in {"create-symlink", "replace-with-symlink", "replace-symlink"}:
            if action == "replace-symlink":
                temporary = source.parent / f".{source.name}.policy-link-{os.getpid()}"
                if temporary.exists() or temporary.is_symlink():
                    raise PolicyError(f"temporary migration path already exists beside {source}")
                os.symlink(os.path.relpath(destination, start=source.parent), temporary)
                os.replace(temporary, source)
            else:
                _install_relative_symlink(
                    source,
                    destination,
                    replace_copy=action == "replace-with-symlink",
                )
            result = dict(item)
            result["applied"] = True
            results.append(result)
        else:
            result = dict(item)
            result["applied"] = False
            results.append(result)
    return results


def _human_bytes(value: int) -> str:
    units = ("B", "KiB", "MiB", "GiB", "TiB")
    amount = float(value)
    unit = units[0]
    for unit in units:
        if amount < 1024 or unit == units[-1]:
            break
        amount /= 1024
    return f"{amount:.0f}{unit}" if unit == "B" else f"{amount:.2f}{unit}"


def _print_status_human(status: dict[str, Any]) -> None:
    print(f"Build output policy: {status['manifest']}")
    print(
        f"Allocated bytes: total={status['allocatedBytes']} ({_human_bytes(status['allocatedBytes'])}) "
        f"managed={status['managedAllocatedBytes']} ({_human_bytes(status['managedAllocatedBytes'])}) "
        f"unowned={status['unownedAllocatedBytes']} ({_human_bytes(status['unownedAllocatedBytes'])})"
    )
    filesystem = status["filesystem"]
    print(
        f"Filesystem: free={filesystem['freeBytes']} ({_human_bytes(filesystem['freeBytes'])}) "
        f"used={filesystem['usedBytes']} ({_human_bytes(filesystem['usedBytes'])}) "
        f"total={filesystem['totalBytes']} ({_human_bytes(filesystem['totalBytes'])})"
    )
    for root in status["roots"]:
        producer = root["lastProducer"] or "none"
        print(
            f"{root['id']}: class={root['class']} cleanup={root['cleanup']} "
            f"bytes={root['allocatedBytes']} ({_human_bytes(root['allocatedBytes'])}) "
            f"eligible={root['eligibleReclaimBytes']} ({_human_bytes(root['eligibleReclaimBytes'])}) "
            f"blocked={root['blockedReclaimBytes']} ({_human_bytes(root['blockedReclaimBytes'])}) "
            f"path={root['path']} owner={root['owner']} lastProducer={producer}"
        )
    for root in status["unownedRoots"]:
        print(
            f"unowned: class=unowned cleanup=none bytes={root['allocatedBytes']} "
            f"({_human_bytes(root['allocatedBytes'])}) path={root['path']} owner=none"
        )
    external = status["externalXcodeDerivedData"]
    print(
        "external-xcode-derived-data: "
        f"policy={external['policy']} matches={len(external['matchingEntries'])} "
        f"bytes={external['allocatedBytes']} ({_human_bytes(external['allocatedBytes'])}) "
        f"path={external['root']}"
    )
    profiles = status["retentionSummary"]["profiles"]
    print(
        "profile-retention: "
        f"automaticReclaimable={profiles['automaticReclaimableBytes']} "
        f"({_human_bytes(profiles['automaticReclaimableBytes'])}) "
        f"explicitReclaimable={profiles['explicitReclaimableBytes']} "
        f"({_human_bytes(profiles['explicitReclaimableBytes'])}) "
        f"blocked={profiles['blockedBytes']} ({_human_bytes(profiles['blockedBytes'])}) "
        f"unclassified={profiles['unclassifiedBytes']} ({_human_bytes(profiles['unclassifiedBytes'])})"
    )


def _print_migration(plan: list[dict[str, Any]], mode: str) -> None:
    print(f"migration-mode: {mode}")
    for item in plan:
        print(
            f"migration: id={item['id']} action={item['action']} blocking={str(item['blocking']).lower()} "
            f"source={item['source']} destination={item['destination']} reason={item['reason']}"
        )


def _add_common_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=DEFAULT_REPO_ROOT,
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        help=argparse.SUPPRESS,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    status = subparsers.add_parser("status", help="inventory managed and external build output")
    _add_common_arguments(status)
    status_format = status.add_mutually_exclusive_group()
    status_format.add_argument("--json", action="store_true", dest="as_json")
    status_format.add_argument(
        "--markdown",
        action="store_true",
        help="render the manifest-owned documentation table",
    )

    validate = subparsers.add_parser("validate", help="validate policy and tracked references")
    _add_common_arguments(validate)
    validate.add_argument("--json", action="store_true", dest="as_json")

    shell_env = subparsers.add_parser("shell-env", help="emit shell-safe canonical path exports")
    _add_common_arguments(shell_env)

    migrate = subparsers.add_parser("migrate", help="plan or apply conservative legacy migration")
    _add_common_arguments(migrate)
    mode = migrate.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    migrate.add_argument("--json", action="store_true", dest="as_json")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        policy = load_policy(args.repo_root, args.manifest)
        if args.command == "status":
            if args.markdown:
                print(render_policy_markdown_table(policy))
                return 0
            status = build_status(policy)
            if args.as_json:
                print(json.dumps(status, sort_keys=True, indent=2))
            else:
                _print_status_human(status)
            return 0
        if args.command == "validate":
            violations = validate_repository(policy)
            if args.as_json:
                print(
                    json.dumps(
                        {"valid": not violations, "violations": violations},
                        sort_keys=True,
                        indent=2,
                    )
                )
            elif violations:
                for violation in violations:
                    print(f"error: {violation}", file=sys.stderr)
            else:
                print("Build output policy: PASS")
            return 1 if violations else 0
        if args.command == "shell-env":
            for name, value in shell_environment(policy):
                print(f"export {name}={shlex.quote(value)}")
            return 0
        if args.command == "migrate":
            migration_plan = plan_migration(policy)
            if args.apply:
                migration_plan = apply_migration(policy, migration_plan)
                mode_name = "apply"
            else:
                mode_name = "dry-run"
            if args.as_json:
                print(
                    json.dumps(
                        {"mode": mode_name, "operations": migration_plan},
                        sort_keys=True,
                        indent=2,
                    )
                )
            else:
                _print_migration(migration_plan, mode_name)
            return 1 if any(item["blocking"] for item in migration_plan) else 0
    except PolicyError as error:
        print(f"build-output-policy error: {error}", file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
