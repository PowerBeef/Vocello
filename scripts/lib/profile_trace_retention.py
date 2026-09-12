#!/usr/bin/env python3
"""Bound raw Instruments trace retention without weakening benchmark evidence.

This helper owns only untracked ``build/artifacts/{macos,ios}/profiles`` artifacts.  The profile
runners remain responsible for validating a trace and publishing its compact
benchmark record.  A successful raw trace may be removed only after this helper
can prove that both the compact summary and matching history record exist.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
from typing import Any
try:  # imported as `lib.<module>` from scripts/, or by bare name from scripts/lib
    from lib import jsonio
except ImportError:  # pragma: no cover - bare-name import path
    import jsonio  # type: ignore[no-redef]


GIB = 1024 ** 3
REQUIRED_FREE_BYTES = {"cpu": 5 * GIB, "memory": 15 * GIB}
SCHEMA_VERSION = 1
DEFAULT_MAX_COMPACTED_DIAGNOSTIC_BYTES = 8 * 1024**2
DEFAULT_MAX_DIAGNOSTIC_LOG_BYTES = 1024**2
COMPACTED_CRITICAL_FILES = {
    "profile-retention.json",
    "profile-failure-summary.json",
    "retention-pin.json",
}
COMPACTED_METADATA_FILES = {
    "benchmark-source.json",
    "profile-summary.json",
    "trace-toc.xml",
}
RUN_ID_RE = re.compile(
    r"^(?P<platform>mac|ios)-(?:(?P<kind>cpu|memory)-)?profile-"
    r"(?P<timestamp>[0-9]{8}-[0-9]{6})-(?P<nonce>[0-9a-f]{8})$"
)


class RetentionError(RuntimeError):
    pass


def utc_now() -> str:
    return jsonio.utc_now(whole_seconds=False)


def load_json(path: Path) -> dict[str, Any]:
    return jsonio.load_json(path, error=RetentionError, redact="name")


def digest_file(path: Path) -> str:
    return jsonio.sha256_file(path, error=RetentionError)


canonical_bytes = jsonio.canonical_bytes


def trace_directory_digest(trace: Path) -> str:
    """Reproduce ``publish_benchmark_history.py``'s trace-bundle digest."""

    manifest = [
        [path.relative_to(trace).as_posix(), digest_file(path)]
        for path in sorted(trace.rglob("*"))
        if path.is_file()
    ]
    return hashlib.sha256(canonical_bytes(manifest)).hexdigest()


def trace_record(value: dict[str, Any], location: str) -> dict[str, Any]:
    evidence = value.get("evidence")
    trace = evidence.get("trace") if isinstance(evidence, dict) else None
    if not isinstance(trace, dict):
        raise RetentionError(f"{location} has no validated trace evidence")
    return trace


def retention_projection(trace: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "digest", "originalEphemeralPath", "summaryArtifact",
        "rawTraceRetained", "retentionPolicy", "captureSettingsDigest",
    )
    return {key: trace.get(key) for key in keys}


atomic_json_write = jsonio.atomic_json


def safe_relative(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError as error:
        raise RetentionError(f"artifact must remain under repository root: {path}") from error


def profile_capture_time(run_id: str, platform: str, kind: str) -> str:
    match = RUN_ID_RE.fullmatch(run_id)
    expected_platform = "mac" if platform == "macos" else "ios"
    if (
        match is None
        or match.group("platform") != expected_platform
        or (match.group("kind") or "cpu") != kind
    ):
        raise RetentionError(
            f"profile run ID does not match {platform}/{kind}: {run_id!r}"
        )
    try:
        captured = dt.datetime.strptime(
            match.group("timestamp"), "%Y%m%d-%H%M%S"
        ).replace(tzinfo=dt.timezone.utc)
    except ValueError as error:
        raise RetentionError(f"profile run ID has an invalid capture time: {run_id!r}") from error
    return captured.isoformat().replace("+00:00", "Z")


def real_repository_profiles_root(root: Path, platform: str) -> tuple[Path, Path]:
    root_path = Path(os.path.abspath(root))
    if root_path.is_symlink() or not root_path.is_dir():
        raise RetentionError("repository root must be a real non-symlink directory")
    root_resolved = root_path.resolve()
    current = root_path
    for component in ("build", "artifacts", platform, "profiles"):
        current = current / component
        if current.is_symlink() or not current.is_dir():
            raise RetentionError(
                f"repository profile ancestor must be a real non-symlink directory: {current}"
            )
        resolved = current.resolve()
        try:
            resolved.relative_to(root_resolved)
        except ValueError as error:
            raise RetentionError(
                f"repository profile ancestor resolves outside the repository: {current}"
            ) from error
    return root_resolved, current.resolve()


def directory_bytes(path: Path) -> int:
    if not path.exists():
        return 0
    if path.is_symlink() or not path.is_dir():
        raise RetentionError(f"raw trace must be a real directory: {path}")
    total = 0
    for parent, directories, files in os.walk(path, followlinks=False):
        directories[:] = [
            name for name in directories if not (Path(parent) / name).is_symlink()
        ]
        for name in files:
            child = Path(parent) / name
            if child.is_symlink():
                continue
            try:
                total += child.stat().st_size
            except FileNotFoundError:
                continue
    return total


def payload_bytes(path: Path) -> int:
    """Measure one removable payload without following links outside the run."""

    if not path.exists() and not path.is_symlink():
        return 0
    if path.is_symlink():
        return path.lstat().st_size
    if path.is_file():
        return path.stat().st_size
    if path.is_dir():
        return directory_bytes(path)
    return 0


def validate_profile_paths(
    *, root: Path, artifact_dir: Path, trace: Path, platform: str, kind: str
) -> tuple[Path, Path, Path]:
    if platform not in {"macos", "ios"}:
        raise RetentionError("platform must be macos or ios")
    if kind not in REQUIRED_FREE_BYTES:
        raise RetentionError("profile kind must be cpu or memory")
    root, profiles_root = real_repository_profiles_root(root, platform)
    if artifact_dir.is_symlink():
        raise RetentionError("profile artifact directory must not be a symlink")
    artifact_dir = artifact_dir.resolve()
    try:
        artifact_dir.relative_to(profiles_root)
    except ValueError as error:
        raise RetentionError(
            f"profile artifact directory must be under {profiles_root}"
        ) from error
    if artifact_dir == profiles_root or artifact_dir.parent != profiles_root:
        raise RetentionError("profile artifact directory must be one run below profiles root")
    profile_capture_time(artifact_dir.name, platform, kind)
    expected_trace = artifact_dir / f"{artifact_dir.name}.trace"
    if trace.resolve() != expected_trace.resolve():
        raise RetentionError(f"unexpected raw trace path: expected {expected_trace}")
    if trace.is_symlink():
        raise RetentionError("raw trace path must not be a symlink")
    return root, artifact_dir, profiles_root


def diagnostic_logs(artifact_dir: Path) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for path in sorted(artifact_dir.glob("*.log")):
        if path.is_symlink() or not path.is_file():
            continue
        result.append({"name": path.name, "sizeBytes": path.stat().st_size})
    return result


def profile_retention_settings(root: Path) -> tuple[int, int, int]:
    manifest = root / "config" / "build-output-policy.json"
    if not manifest.exists():
        raise RetentionError(f"profile retention contract is missing: {manifest}")
    try:
        document = json.loads(manifest.read_text(encoding="utf-8"))
        child_retention = document["childRetention"]
        profiles = child_retention["profiles"]
        keep = profiles["keepFailedPerPlatformKind"]
        total = profiles["maximumCompactedDiagnosticBytes"]
        log = profiles["maximumDiagnosticLogBytes"]
        if (
            document.get("schemaVersion") == 1
            and child_retention.get("schemaVersion") == 1
            and profiles.get("entries") == ["artifacts-macos", "artifacts-ios"]
            and profiles.get("markerFilename") == "profile-retention.json"
            and profiles.get("pinFilename") == "retention-pin.json"
            and isinstance(keep, int)
            and not isinstance(keep, bool)
            and isinstance(total, int)
            and not isinstance(total, bool)
            and isinstance(log, int)
            and not isinstance(log, bool)
            and keep >= 1
            and total >= log >= 1
        ):
            return keep, total, log
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise RetentionError(f"invalid profile retention contract: {error}") from error
    raise RetentionError("invalid profile retention contract values")


def valid_failed_profile_for_compaction(
    *, root: Path, marker_path: Path, value: dict[str, Any]
) -> bool:
    artifact_dir = marker_path.parent
    platform = value.get("platform")
    kind = value.get("profileKind")
    if platform not in {"macos", "ios"} or kind not in REQUIRED_FREE_BYTES:
        return False
    trace = artifact_dir / f"{artifact_dir.name}.trace"
    try:
        capture = profile_capture_time(artifact_dir.name, platform, kind)
        original = safe_relative(trace, root)
        summary = load_json(artifact_dir / "profile-failure-summary.json")
    except RetentionError:
        return False
    policy = value.get("retentionPolicy")
    pending = policy == "failedCompactionPending"
    summary_state_valid = (
        summary.get("rawTraceRetained") is True
        and summary.get("retentionPolicy") in {None, "failedLatest", "failedCompactionPending"}
    )
    if pending:
        summary_state_valid = summary_state_valid or (
            summary.get("rawTraceRetained") is False
            and summary.get("retentionPolicy") == "failedCompacted"
        )
    return bool(
        value.get("schemaVersion") == SCHEMA_VERSION
        and value.get("runID") == artifact_dir.name
        and value.get("captureTime") == capture
        and value.get("status") == "failed"
        and policy in {"failedLatest", "failedCompactionPending"}
        and value.get("rawTraceRetained") is True
        and value.get("originalEphemeralPath") == original
        and (pending or (trace.is_dir() and not trace.is_symlink()))
        and summary.get("schemaVersion") == SCHEMA_VERSION
        and summary.get("runID") == artifact_dir.name
        and summary.get("captureTime") == capture
        and summary.get("platform") == platform
        and summary.get("profileKind") == kind
        and summary.get("status") == "failed"
        and summary_state_valid
        and summary.get("originalEphemeralPath") == original
    )


def failed_profile_payload_candidates(
    *, root: Path, artifact_dir: Path
) -> tuple[list[Path], list[str]]:
    """Return payload to discard while retaining one bounded diagnostic capsule."""

    _, maximum_total, maximum_log = profile_retention_settings(root)
    discard: list[Path] = []
    retained: list[str] = []
    retained_bytes = 0
    for child in sorted(artifact_dir.iterdir(), key=lambda item: item.name):
        name = child.name
        if name in COMPACTED_CRITICAL_FILES and child.is_file() and not child.is_symlink():
            retained.append(name)
            retained_bytes += child.stat().st_size
            continue
        allowed_metadata = name in COMPACTED_METADATA_FILES
        allowed_log = name.endswith(".log")
        if (allowed_metadata or allowed_log) and child.is_file() and not child.is_symlink():
            size = child.stat().st_size
            item_limit = maximum_log if allowed_log else maximum_total
            if size <= item_limit and retained_bytes + size <= maximum_total:
                retained.append(name)
                retained_bytes += size
                continue
        discard.append(child)
    return discard, retained


def remove_failed_profile_payload(*, root: Path, artifact_dir: Path) -> tuple[int, list[str]]:
    candidates, retained = failed_profile_payload_candidates(
        root=root, artifact_dir=artifact_dir
    )
    removed = sum(payload_bytes(candidate) for candidate in candidates)
    for candidate in candidates:
        if candidate.is_symlink() or candidate.is_file():
            candidate.unlink(missing_ok=True)
        elif candidate.is_dir():
            shutil.rmtree(candidate)
    return removed, retained


def failure_summary(
    *, root: Path, artifact_dir: Path, trace: Path, platform: str, kind: str,
    phase: str, exit_code: int, retained: bool, trace_bytes: int,
) -> dict[str, Any]:
    return {
        "schemaVersion": SCHEMA_VERSION,
        "runID": artifact_dir.name,
        "captureTime": profile_capture_time(artifact_dir.name, platform, kind),
        "platform": platform,
        "profileKind": kind,
        "status": "failed",
        "failurePhase": phase,
        "exitCode": exit_code,
        "originalEphemeralPath": safe_relative(trace, root),
        "originalTraceBytes": trace_bytes,
        "rawTraceRetained": retained,
        "diagnosticLogs": diagnostic_logs(artifact_dir),
        "capturedAt": utc_now(),
    }


def retention_manifest(
    *, root: Path, artifact_dir: Path, trace: Path, platform: str, kind: str,
    status: str, policy: str, retained: bool, trace_bytes: int,
    summary_artifact: Path | None, phase: str | None = None,
    exit_code: int | None = None,
) -> dict[str, Any]:
    return {
        "schemaVersion": SCHEMA_VERSION,
        "runID": artifact_dir.name,
        "captureTime": profile_capture_time(artifact_dir.name, platform, kind),
        "platform": platform,
        "profileKind": kind,
        "status": status,
        "retentionPolicy": policy,
        "rawTraceRetained": retained,
        "originalEphemeralPath": safe_relative(trace, root),
        "summaryArtifactPath": (
            safe_relative(summary_artifact, root) if summary_artifact is not None else None
        ),
        "originalTraceBytes": trace_bytes,
        "failurePhase": phase,
        "exitCode": exit_code,
        "completedAt": utc_now(),
    }


def cmd_preflight(args: argparse.Namespace) -> int:
    required = REQUIRED_FREE_BYTES[args.kind]
    available = (
        args.available_bytes
        if args.available_bytes is not None
        else shutil.disk_usage(args.root).free
    )
    if available < required:
        print(
            f"insufficient free disk space for {args.kind} profile: "
            f"{available / GIB:.2f} GiB available; {required // GIB} GiB required "
            "before launching the target or Instruments.\n"
            "Reclaim bounded profile/build artifacts with exactly:\n"
            "  scripts/clean_build_caches.sh --routine",
            file=sys.stderr,
        )
        return 2
    print(
        json.dumps(
            {
                "availableBytes": available,
                "profileKind": args.kind,
                "requiredBytes": required,
            },
            sort_keys=True,
        )
    )
    return 0


def cmd_finalize_success(args: argparse.Namespace) -> int:
    root, artifact_dir, _ = validate_profile_paths(
        root=args.root, artifact_dir=args.artifact_dir, trace=args.trace,
        platform=args.platform, kind=args.kind,
    )
    evidence_path = artifact_dir / "benchmark-evidence.json"
    if not evidence_path.is_file():
        raise RetentionError("benchmark evidence is missing; refusing raw trace deletion")
    summary = args.summary_artifact.resolve()
    expected_summary = artifact_dir / "profile-summary.json"
    if summary != expected_summary.resolve():
        raise RetentionError(f"unexpected compact profile summary path: {summary}")
    if not summary.is_file():
        raise RetentionError("compact profile summary is missing; refusing raw trace deletion")
    history = args.history_record.resolve()
    expected_history = (
        root / "benchmarks" / "runs" / "instrument-profile" / f"{artifact_dir.name}.json"
    ).resolve()
    if history != expected_history:
        raise RetentionError(f"unexpected profile history record path: {history}")
    if not history.is_file():
        raise RetentionError("matching history record is missing; refusing raw trace deletion")
    history_value = load_json(history)
    if (history_value.get("run") or {}).get("id") != artifact_dir.name:
        raise RetentionError("history record does not match the profile run ID")
    evidence_value = load_json(evidence_path)
    history_record = evidence_value.get("historyRecord")
    if not isinstance(history_record, dict):
        raise RetentionError("benchmark evidence has no frozen history record")
    if (history_record.get("run") or {}).get("id") != artifact_dir.name:
        raise RetentionError("benchmark evidence does not match the profile run ID")
    tracked_trace = trace_record(history_value, "tracked history record")
    frozen_trace = trace_record(history_record, "benchmark evidence historyRecord")
    expected_original = safe_relative(args.trace, root)
    expected_summary = safe_relative(summary, root)
    expected_retained = args.policy == "keptExplicitly"
    summary_artifact = tracked_trace.get("summaryArtifact")
    expected_summary_digest = digest_file(summary)
    if tracked_trace.get("originalEphemeralPath") != expected_original:
        raise RetentionError("tracked trace path does not match the raw profile trace")
    if tracked_trace.get("retentionPolicy") != args.policy:
        raise RetentionError("tracked trace retention policy does not match finalization")
    if tracked_trace.get("rawTraceRetained") is not expected_retained:
        raise RetentionError("tracked raw-trace state conflicts with finalization policy")
    if not isinstance(summary_artifact, dict):
        raise RetentionError("tracked trace has no compact summary artifact")
    if summary_artifact.get("path") != expected_summary:
        raise RetentionError("tracked compact summary path does not match finalization")
    if summary_artifact.get("digest") != expected_summary_digest:
        raise RetentionError("tracked compact summary digest does not match its file")
    if retention_projection(frozen_trace) != retention_projection(tracked_trace):
        raise RetentionError("benchmark evidence and tracked trace retention metadata differ")
    if not args.trace.is_dir():
        raise RetentionError("published raw trace is missing before retention finalization")
    if trace_directory_digest(args.trace) != tracked_trace.get("digest"):
        raise RetentionError(
            "raw trace digest changed after publication; refusing raw trace deletion"
        )
    summary_value = load_json(summary)
    expected_summary_fields = {
        "runID": artifact_dir.name,
        "traceDigest": tracked_trace.get("digest"),
        "originalEphemeralPath": expected_original,
        "retentionPolicy": args.policy,
        "rawTraceRetained": expected_retained,
    }
    if any(summary_value.get(key) != value for key, value in expected_summary_fields.items()):
        raise RetentionError("compact summary does not match the published trace evidence")
    trace_bytes = directory_bytes(args.trace)
    if args.policy == "summaryOnly":
        if args.trace.exists():
            shutil.rmtree(args.trace)
        retained = False
    else:
        if not args.trace.is_dir():
            raise RetentionError("--keep-trace requested but the raw trace is missing")
        retained = True
    manifest = retention_manifest(
        root=root, artifact_dir=artifact_dir, trace=args.trace,
        platform=args.platform, kind=args.kind, status="published",
        policy=args.policy, retained=retained, trace_bytes=trace_bytes,
        summary_artifact=summary,
    )
    atomic_json_write(artifact_dir / "profile-retention.json", manifest)
    return 0


def compact_failed_trace(root: Path, manifest_path: Path, value: dict[str, Any]) -> None:
    if manifest_path.is_symlink() or manifest_path.parent.is_symlink():
        raise RetentionError(f"failed profile marker must not be reached through a symlink: {manifest_path}")
    if not valid_failed_profile_for_compaction(
        root=root, marker_path=manifest_path, value=value
    ):
        raise RetentionError(f"failed profile metadata is not safe to compact: {manifest_path}")
    trace_relative = value.get("originalEphemeralPath")
    if not isinstance(trace_relative, str) or not trace_relative.startswith("build/"):
        raise RetentionError(f"invalid failed trace path in {manifest_path}")
    trace = root / trace_relative
    artifact_dir = manifest_path.parent
    expected = artifact_dir / f"{artifact_dir.name}.trace"
    if trace.resolve() != expected.resolve():
        raise RetentionError(f"failed trace marker escapes its run directory: {manifest_path}")
    if trace.exists() and (trace.is_symlink() or not trace.is_dir()):
        raise RetentionError(f"refusing to remove non-directory trace: {trace}")
    summary_path = artifact_dir / "profile-failure-summary.json"
    summary = load_json(summary_path)
    if value.get("retentionPolicy") != "failedCompactionPending":
        started_at = utc_now()
        value.update(
            {
                "retentionPolicy": "failedCompactionPending",
                "rawTraceRetained": True,
                "compactionStartedAt": started_at,
            }
        )
        summary.update(
            {
                "rawTraceRetained": True,
                "retentionPolicy": "failedCompactionPending",
                "compactionStartedAt": started_at,
            }
        )
        atomic_json_write(manifest_path, value)
        atomic_json_write(summary_path, summary)
    removed_bytes, retained_files = remove_failed_profile_payload(
        root=root, artifact_dir=artifact_dir
    )
    completed_at = utc_now()
    summary = load_json(summary_path) if summary_path.exists() else {}
    summary.update(
        {
            "rawTraceRetained": False,
            "retentionPolicy": "failedCompacted",
            "compactedAt": completed_at,
            "discardedPayloadBytes": removed_bytes,
            "retainedDiagnosticFiles": retained_files,
        }
    )
    atomic_json_write(summary_path, summary)
    value.update(
        {
            "retentionPolicy": "failedCompacted",
            "rawTraceRetained": False,
            "completedAt": completed_at,
        }
    )
    atomic_json_write(manifest_path, value)


def cmd_mark_failure(args: argparse.Namespace) -> int:
    root, artifact_dir, profiles_root = validate_profile_paths(
        root=args.root, artifact_dir=args.artifact_dir, trace=args.trace,
        platform=args.platform, kind=args.kind,
    )
    trace_bytes = directory_bytes(args.trace)
    retained = args.trace.is_dir()
    summary_path = artifact_dir / "profile-failure-summary.json"
    summary = failure_summary(
        root=root, artifact_dir=artifact_dir, trace=args.trace,
        platform=args.platform, kind=args.kind, phase=args.phase,
        exit_code=args.exit_code, retained=retained, trace_bytes=trace_bytes,
    )
    atomic_json_write(summary_path, summary)
    manifest = retention_manifest(
        root=root, artifact_dir=artifact_dir, trace=args.trace,
        platform=args.platform, kind=args.kind, status="failed",
        policy="failedLatest" if retained else "failedNoTrace",
        retained=retained, trace_bytes=trace_bytes, summary_artifact=summary_path,
        phase=args.phase, exit_code=args.exit_code,
    )
    atomic_json_write(artifact_dir / "profile-retention.json", manifest)

    candidates: list[tuple[str, str, Path, dict[str, Any], bool]] = []
    pending: list[tuple[Path, dict[str, Any]]] = []
    for marker in profiles_root.glob("*/profile-retention.json"):
        if marker.is_symlink() or marker.parent.is_symlink():
            continue
        try:
            value = load_json(marker)
        except RetentionError:
            continue
        if not valid_failed_profile_for_compaction(
            root=root, marker_path=marker, value=value
        ):
            continue
        pin_path = marker.parent / "retention-pin.json"
        pin = load_json(pin_path) if pin_path.is_file() else None
        pinned = bool(
            pin and pin.get("schemaVersion") == 1 and pin.get("pinned") is True
        )
        if value.get("retentionPolicy") == "failedCompactionPending":
            if not pinned:
                pending.append((marker, value))
            continue
        try:
            capture_time = profile_capture_time(marker.parent.name, args.platform, args.kind)
        except RetentionError:
            continue
        candidates.append((capture_time, marker.parent.name, marker, value, pinned))
    for marker, value in pending:
        compact_failed_trace(root, marker, value)
    candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
    keep_failures, _, _ = profile_retention_settings(root)
    retained_unpinned = 0
    for _, _, marker, value, pinned in candidates:
        if pinned:
            continue
        if retained_unpinned < keep_failures:
            retained_unpinned += 1
            continue
        compact_failed_trace(root, marker, value)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    preflight = subparsers.add_parser("preflight")
    preflight.add_argument("--root", type=Path, required=True)
    preflight.add_argument("--kind", choices=sorted(REQUIRED_FREE_BYTES), required=True)
    preflight.add_argument("--available-bytes", type=int)
    preflight.set_defaults(handler=cmd_preflight)

    def add_profile_arguments(command: argparse.ArgumentParser) -> None:
        command.add_argument("--root", type=Path, required=True)
        command.add_argument("--artifact-dir", type=Path, required=True)
        command.add_argument("--trace", type=Path, required=True)
        command.add_argument("--platform", choices=("macos", "ios"), required=True)
        command.add_argument("--kind", choices=sorted(REQUIRED_FREE_BYTES), required=True)

    finalize = subparsers.add_parser("finalize-success")
    add_profile_arguments(finalize)
    finalize.add_argument(
        "--policy", choices=("summaryOnly", "keptExplicitly"), required=True
    )
    finalize.add_argument("--summary-artifact", type=Path, required=True)
    finalize.add_argument("--history-record", type=Path, required=True)
    finalize.set_defaults(handler=cmd_finalize_success)

    failure = subparsers.add_parser("mark-failure")
    add_profile_arguments(failure)
    failure.add_argument("--phase", required=True)
    failure.add_argument("--exit-code", type=int, required=True)
    failure.set_defaults(handler=cmd_mark_failure)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        return int(args.handler(args))
    except RetentionError as error:
        print(f"profile trace retention error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
