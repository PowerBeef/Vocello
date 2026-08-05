#!/usr/bin/env python3
"""Bounded cleanup for repository-owned build outputs.

The machine-readable build-output policy owns every normal target.  This
command is deliberately conservative: inventory is the default, cleanup tiers
are explicit, tracked files are never removed, and unresolved evidence is
preserved.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys
import tempfile
from typing import Any, Iterable


LIB_DIRECTORY = Path(__file__).resolve().parent / "lib"
if str(LIB_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(LIB_DIRECTORY))

from build_artifact_retention import (
    UI_COMPACT_FILENAME,
    analyze_ui_artifacts,
)
from profile_trace_retention import (
    RetentionError,
    failed_profile_payload_candidates,
    profile_capture_time,
    valid_failed_profile_for_compaction,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = REPO_ROOT / "config" / "build-output-policy.json"
HISTORY_HELPER = REPO_ROOT / "scripts" / "benchmark_history.py"
DEBUG_MODELS = Path.home() / "Library" / "Application Support" / "QwenVoice-Debug" / "models"
SHIPPED_MODELS = Path.home() / "Library" / "Application Support" / "QwenVoice" / "models"
CACHE_ALIASES = {
    "macos": "xcode-macos-derived-data",
    "ios": "xcode-ios-device-derived-data",
    "packages": "xcode-source-packages",
    "runtime": "swiftpm-mlx-audio-runtime",
}


class CleanupError(RuntimeError):
    pass


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise CleanupError(f"could not read {path}: {error}") from error
    if not isinstance(value, dict):
        raise CleanupError(f"{path} must contain a JSON object")
    return value


def load_policy() -> dict[str, Any]:
    policy = load_json(POLICY_PATH)
    if policy.get("schemaVersion") != 1 or policy.get("buildRoot") != "build":
        raise CleanupError("unsupported build-output policy")
    entries = policy.get("entries")
    if not isinstance(entries, list) or not entries:
        raise CleanupError("build-output policy has no entries")
    seen: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise CleanupError("build-output policy entry must be an object")
        path = entry.get("path")
        if not isinstance(path, str) or not path.startswith("build/"):
            raise CleanupError(f"invalid managed build path: {path!r}")
        resolved = (REPO_ROOT / path).resolve(strict=False)
        try:
            resolved.relative_to((REPO_ROOT / "build").resolve(strict=False))
        except ValueError as error:
            raise CleanupError(f"managed path escapes build/: {path}") from error
        if path in seen:
            raise CleanupError(f"duplicate managed build path: {path}")
        seen.add(path)
    child_retention = policy.get("childRetention")
    ui_retention = child_retention.get("uiResults") if isinstance(child_retention, dict) else None
    profile_retention = child_retention.get("profiles") if isinstance(child_retention, dict) else None
    if not (
        isinstance(child_retention, dict)
        and child_retention.get("schemaVersion") == 1
        and isinstance(ui_retention, dict)
        and ui_retention.get("entry") == "artifacts-ui-tests"
        and ui_retention.get("metadataFilename") == "run.json"
        and ui_retention.get("pinFilename") == "retention-pin.json"
        and {"smoke", "benchmark", "model-download"}.issubset(
            set(ui_retention.get("lanes") or ())
        )
        and isinstance(ui_retention.get("keepPassingPerPlatformLane"), int)
        and ui_retention["keepPassingPerPlatformLane"] >= 1
        and isinstance(ui_retention.get("keepUnresolvedFailuresPerPlatformLane"), int)
        and ui_retention["keepUnresolvedFailuresPerPlatformLane"] >= 1
    ):
        raise CleanupError("build-output policy has no valid child UI retention contract")
    if not (
        isinstance(profile_retention, dict)
        and profile_retention.get("entries") == ["artifacts-macos", "artifacts-ios"]
        and profile_retention.get("markerFilename") == "profile-retention.json"
        and profile_retention.get("pinFilename") == "retention-pin.json"
        and isinstance(profile_retention.get("keepFailedPerPlatformKind"), int)
        and not isinstance(profile_retention.get("keepFailedPerPlatformKind"), bool)
        and profile_retention["keepFailedPerPlatformKind"] >= 1
        and isinstance(profile_retention.get("maximumCompactedDiagnosticBytes"), int)
        and not isinstance(profile_retention.get("maximumCompactedDiagnosticBytes"), bool)
        and isinstance(profile_retention.get("maximumDiagnosticLogBytes"), int)
        and not isinstance(profile_retention.get("maximumDiagnosticLogBytes"), bool)
        and profile_retention["maximumCompactedDiagnosticBytes"]
        >= profile_retention["maximumDiagnosticLogBytes"] >= 1
    ):
        raise CleanupError("build-output policy has no valid profile retention contract")
    heavy_preflight = policy.get("heavyLanePreflight")
    if not (
        isinstance(heavy_preflight, dict)
        and heavy_preflight.get("schemaVersion") == 1
        and isinstance(heavy_preflight.get("lanes"), dict)
        and heavy_preflight["lanes"]
    ):
        raise CleanupError("build-output policy has no valid heavy-lane preflight contract")
    entry_ids = {entry.get("id") for entry in entries}
    if not set(CACHE_ALIASES.values()) <= entry_ids:
        raise CleanupError("build-output policy is missing a selectable cache entry")
    return policy


def allocated_bytes(path: Path) -> int:
    if not path.exists() and not path.is_symlink():
        return 0
    try:
        if path.is_symlink() or path.is_file():
            return path.lstat().st_blocks * 512
    except FileNotFoundError:
        return 0
    total = 0
    for parent, directories, files in os.walk(path, followlinks=False):
        parent_path = Path(parent)
        kept: list[str] = []
        for name in directories:
            child = parent_path / name
            try:
                if child.is_symlink():
                    total += child.lstat().st_blocks * 512
                else:
                    kept.append(name)
            except FileNotFoundError:
                continue
        directories[:] = kept
        for name in files:
            try:
                total += (parent_path / name).lstat().st_blocks * 512
            except FileNotFoundError:
                continue
    return total


def human_bytes(value: int) -> str:
    units = ("B", "KiB", "MiB", "GiB", "TiB")
    amount = float(value)
    index = 0
    while amount >= 1024 and index < len(units) - 1:
        amount /= 1024
        index += 1
    return f"{amount:.0f}{units[index]}" if index == 0 else f"{amount:.2f}{units[index]}"


def canonical_digest(value: Any) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def trace_digest(trace: Path) -> str:
    rows = [
        [path.relative_to(trace).as_posix(), file_digest(path)]
        for path in sorted(trace.rglob("*"))
        if path.is_file() and not path.is_symlink()
    ]
    return canonical_digest(rows)


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2, sort_keys=True, ensure_ascii=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def tracked_paths_below(path: Path) -> list[str]:
    try:
        relative = path.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return []
    result = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "ls-files", "-z", "--", relative],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return [part.decode("utf-8", "replace") for part in result.stdout.split(b"\0") if part]


def assert_repository_target(path: Path, *, allow_build_root: bool = False) -> None:
    root = REPO_ROOT.resolve()
    build = (REPO_ROOT / "build").resolve(strict=False)
    absolute = Path(os.path.abspath(path))
    if REPO_ROOT.is_symlink() or not REPO_ROOT.is_dir():
        raise CleanupError("repository root must be a real directory")
    try:
        absolute.relative_to(build)
    except ValueError as error:
        raise CleanupError(f"cleanup target escapes repository build root: {absolute}") from error
    if absolute == build and not allow_build_root:
        raise CleanupError("build root removal requires the explicit clobber path")
    current = REPO_ROOT
    for component in absolute.relative_to(REPO_ROOT).parts[:-1]:
        current /= component
        if current.is_symlink():
            raise CleanupError(f"cleanup target crosses a symlink: {current}")
    tracked = tracked_paths_below(absolute)
    if tracked:
        raise CleanupError(
            "refusing cleanup target containing tracked files: " + ", ".join(tracked[:5])
        )
    try:
        absolute.parent.resolve(strict=False).relative_to(root)
    except ValueError as error:
        raise CleanupError(f"cleanup target parent escapes repository: {absolute}") from error


class Cleaner:
    def __init__(self, *, dry_run: bool) -> None:
        self.dry_run = dry_run
        self.planned = 0

    def remove(self, path: Path, *, allow_build_root: bool = False, reason: str = "policy") -> None:
        if not path.exists() and not path.is_symlink():
            return
        assert_repository_target(path, allow_build_root=allow_build_root)
        size = allocated_bytes(path)
        self.planned += size
        verb = "would-remove" if self.dry_run else "removed"
        print(f"{verb}: bytes={size} human={human_bytes(size)} path={path} reason={reason}")
        if self.dry_run:
            return
        if path.is_symlink() or path.is_file():
            path.unlink()
        else:
            shutil.rmtree(path)


def policy_entries(policy: dict[str, Any], *, cleanup: str | None = None) -> list[dict[str, Any]]:
    result = [entry for entry in policy["entries"] if isinstance(entry, dict)]
    if cleanup is not None:
        result = [entry for entry in result if entry.get("cleanup") == cleanup]
    return result


def managed_path(entry: dict[str, Any]) -> Path:
    return REPO_ROOT / str(entry["path"])


def flatten_strings(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for child in value.values():
            yield from flatten_strings(child)
    elif isinstance(value, list):
        for child in value:
            yield from flatten_strings(child)


def matching_external_derived_data(policy: dict[str, Any]) -> list[Path]:
    external = policy.get("externalXcodeDerivedData") or {}
    root = Path(os.path.expanduser(str(external.get("path", ""))))
    if not root.is_dir():
        return []
    exact_paths = {
        str((REPO_ROOT / "QwenVoice.xcodeproj").resolve()),
        str(REPO_ROOT.resolve()),
    }
    matches: list[Path] = []
    for candidate in sorted(root.iterdir()):
        info = candidate / "info.plist"
        if candidate.is_symlink() or not candidate.is_dir() or not info.is_file():
            continue
        try:
            with info.open("rb") as stream:
                payload = plistlib.load(stream)
        except (OSError, plistlib.InvalidFileException):
            continue
        values = set(flatten_strings(payload))
        normalized_values = set(values)
        for value in values:
            if value.startswith("/"):
                normalized_values.add(str(Path(value).resolve(strict=False)))
        if normalized_values & exact_paths:
            matches.append(candidate)
    return matches


def inventory(policy: dict[str, Any]) -> None:
    repository_bytes = allocated_bytes(REPO_ROOT)
    print("==> Build-output inventory")
    print(
        f"inventory: id=repository class=source bytes={repository_bytes} "
        f"human={human_bytes(repository_bytes)} path={REPO_ROOT} policy=never-remove"
    )
    for entry in policy_entries(policy):
        path = managed_path(entry)
        size = allocated_bytes(path)
        print(
            "inventory: "
            f"id={entry.get('id')} class={entry.get('class')} bytes={size} "
            f"human={human_bytes(size)} path={path} cleanup={entry.get('cleanup')} "
            f"owner={json.dumps(entry.get('owner'), ensure_ascii=True)}"
        )
    for link in policy.get("publicLinks") or []:
        path = REPO_ROOT / str(link.get("path"))
        target = os.readlink(path) if path.is_symlink() else "not-a-symlink"
        print(f"public-link: path={path} target={target}")
    for candidate in matching_external_derived_data(policy):
        size = allocated_bytes(candidate)
        print(
            f"external-xcode: bytes={size} human={human_bytes(size)} "
            f"path={candidate} action=report-only"
        )
    print(
        f"models: debugBytes={allocated_bytes(DEBUG_MODELS)} shippedBytes={allocated_bytes(SHIPPED_MODELS)} "
        "shippedPolicy=never-remove"
    )


def valid_ui_history(run_id: str, platform: str) -> bool:
    record = REPO_ROOT / "benchmarks" / "runs" / "ui-generation" / f"{run_id}.json"
    try:
        payload = load_json(record)
    except CleanupError:
        return False
    run = payload.get("run") or {}
    if not (
        run.get("id") == run_id
        and run.get("kind") == "ui-generation"
        and run.get("platform") == platform
        and run.get("status") in {"passed", "passedWithWarnings"}
    ):
        return False
    result = subprocess.run(
        [sys.executable, str(HISTORY_HELPER), "validate", str(record)],
        cwd=REPO_ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return result.returncode == 0


def valid_profile_history(
    run: Path, *, platform: str, kind: str, trace: Path | None = None
) -> bool:
    record = REPO_ROOT / "benchmarks" / "runs" / "instrument-profile" / f"{run.name}.json"
    try:
        payload = load_json(record)
    except CleanupError:
        return False
    identity = payload.get("run") or {}
    if not (
        identity.get("id") == run.name
        and identity.get("kind") == "instrument-profile"
        and identity.get("platform") == platform
        and identity.get("status") in {"passed", "passedWithWarnings"}
    ):
        return False
    validation = subprocess.run(
        [sys.executable, str(HISTORY_HELPER), "validate", str(record)],
        cwd=REPO_ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if validation.returncode != 0:
        return False
    if trace is None:
        return True
    trace_evidence = (payload.get("evidence") or {}).get("trace") or {}
    return bool(
        trace_evidence.get("validated") is True
        and trace_evidence.get("digest") == trace_digest(trace)
    )


def valid_profile_marker(
    marker: dict[str, Any], *, run: Path, trace: Path, platform: str, kind: str
) -> bool:
    try:
        capture = profile_capture_time(run.name, platform, kind)
    except RetentionError:
        return False
    return bool(
        marker.get("schemaVersion") == 1
        and marker.get("runID") == run.name
        and marker.get("platform") == platform
        and marker.get("profileKind") == kind
        and marker.get("captureTime") == capture
        and marker.get("originalEphemeralPath") == trace.relative_to(REPO_ROOT).as_posix()
    )


def valid_profile_failure_summary(
    run: Path, trace: Path, *, platform: str, kind: str
) -> bool:
    try:
        summary = load_json(run / "profile-failure-summary.json")
    except CleanupError:
        return False
    return bool(
        summary.get("schemaVersion") == 1
        and summary.get("runID") == run.name
        and summary.get("platform") == platform
        and summary.get("profileKind") == kind
        and summary.get("status") == "failed"
        and summary.get("rawTraceRetained") is True
        and summary.get("originalEphemeralPath") == trace.relative_to(REPO_ROOT).as_posix()
    )


def compact_ui_result(cleaner: Cleaner, path: Path, *, reason: str) -> None:
    metadata = load_json(path / "run.json")
    assert_repository_target(path)
    size = allocated_bytes(path)
    cleaner.planned += size
    verb = "would-compact" if cleaner.dry_run else "compacted"
    print(f"{verb}: bytes={size} human={human_bytes(size)} path={path} reason={reason}")
    if cleaner.dry_run:
        return
    safe_metadata = {
        key: metadata.get(key)
        for key in (
            "schemaVersion", "platform", "lane", "runID", "status", "startedAt",
            "finishedAt", "exitCode", "modes", "lengths", "warm", "label",
        )
        if key in metadata
    }
    summary = {
        "schemaVersion": 1,
        "runID": metadata.get("runID"),
        "platform": metadata.get("platform"),
        "lane": metadata.get("lane"),
        "status": metadata.get("status"),
        "reason": reason,
        "originalAllocatedBytes": size,
        "resultBundleWasPresent": any(path.glob("*.xcresult")),
        "benchmarkEvidenceWasPresent": (path / "benchmark-evidence.json").is_file(),
        "compactedAt": dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    # Publish the compact lifecycle capsule before removing any heavy child. If
    # the process is interrupted, a later run sees the capsule and never loses
    # the run identity merely because compaction was partial.
    atomic_json(path / "run.json", safe_metadata)
    atomic_json(path / UI_COMPACT_FILENAME, summary)
    for child in list(path.iterdir()):
        if child.name in {"run.json", UI_COMPACT_FILENAME}:
            continue
        if child.is_symlink() or child.is_file():
            child.unlink(missing_ok=True)
        elif child.is_dir():
            shutil.rmtree(child)


def prune_ui(
    cleaner: Cleaner,
    ui_root: Path,
    *,
    keep_passing: int,
    keep_failures: int,
    lanes: Iterable[str],
) -> None:
    decisions = analyze_ui_artifacts(
        repo_root=REPO_ROOT,
        ui_root=ui_root,
        keep_passing=keep_passing,
        keep_unresolved_failures=keep_failures,
        lanes=lanes,
        history_validator=valid_ui_history,
    )
    for decision in decisions:
        path = REPO_ROOT / decision.path
        if decision.action == "remove":
            cleaner.remove(path, reason=decision.reason)
        elif decision.action == "compact":
            compact_ui_result(cleaner, path, reason=decision.reason)
        else:
            print(f"ui-result-preserved: path={path} reason={decision.reason}")


def compact_profile_trace(
    cleaner: Cleaner,
    *,
    run: Path,
    trace: Path,
    marker: dict[str, Any],
    reason: str,
) -> None:
    candidates, retained_files = failed_profile_payload_candidates(
        root=REPO_ROOT, artifact_dir=run
    )
    discarded_bytes = sum(allocated_bytes(candidate) for candidate in candidates)
    summary_path = run / "profile-failure-summary.json"
    if cleaner.dry_run:
        for candidate in candidates:
            cleaner.remove(candidate, reason=reason)
        return
    compacted_at = dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")
    if marker.get("retentionPolicy") != "failedCompactionPending":
        marker["rawTraceRetained"] = True
        marker["retentionPolicy"] = "failedCompactionPending"
        marker["compactionStartedAt"] = compacted_at
        atomic_json(run / "profile-retention.json", marker)
        summary = load_json(summary_path)
        summary["rawTraceRetained"] = True
        summary["retentionPolicy"] = "failedCompactionPending"
        summary["compactionStartedAt"] = compacted_at
        atomic_json(summary_path, summary)
    for candidate in candidates:
        cleaner.remove(candidate, reason=reason)
    if summary_path.is_file():
        summary = load_json(summary_path)
        summary["rawTraceRetained"] = False
        summary["retentionPolicy"] = "failedCompacted"
        summary["compactedAt"] = compacted_at
        summary["discardedPayloadBytes"] = discarded_bytes
        summary["retainedDiagnosticFiles"] = retained_files
        atomic_json(summary_path, summary)
    marker["rawTraceRetained"] = False
    marker["retentionPolicy"] = "failedCompacted"
    marker["compactedAt"] = compacted_at
    atomic_json(run / "profile-retention.json", marker)


def compact_named_profile_failure(
    cleaner: Cleaner, root: Path, run_id: str
) -> None:
    if not run_id or "/" in run_id or run_id in {".", ".."}:
        raise CleanupError("--compact-profile-failure requires one safe run ID")
    matches = [
        root / platform / "profiles" / run_id
        for platform in ("macos", "ios")
        if (root / platform / "profiles" / run_id).is_dir()
    ]
    if len(matches) != 1:
        raise CleanupError(f"expected exactly one failed profile run named {run_id}, found {len(matches)}")
    run = matches[0]
    marker = load_json(run / "profile-retention.json")
    summary = load_json(run / "profile-failure-summary.json")
    trace = run / f"{run_id}.trace"
    toc = run / "trace-toc.xml"
    pin_path = run / "retention-pin.json"
    pin = load_json(pin_path) if pin_path.is_file() else None
    if pin and pin.get("schemaVersion") == 1 and pin.get("pinned") is True:
        raise CleanupError(f"failed profile is explicitly pinned: {run_id}")
    latest = (
        marker.get("schemaVersion") == 1
        and marker.get("runID") == run_id
        and marker.get("status") == "failed"
        and marker.get("rawTraceRetained") is True
        and marker.get("retentionPolicy") == "failedLatest"
    )
    already_compacted = (
        marker.get("schemaVersion") == 1
        and marker.get("runID") == run_id
        and marker.get("status") == "failed"
        and marker.get("rawTraceRetained") is False
        and marker.get("retentionPolicy") == "failedCompacted"
    )
    pending = (
        marker.get("schemaVersion") == 1
        and marker.get("runID") == run_id
        and marker.get("status") == "failed"
        and marker.get("rawTraceRetained") is True
        and marker.get("retentionPolicy") == "failedCompactionPending"
    )
    if (latest or pending) and not valid_failed_profile_for_compaction(
        root=REPO_ROOT,
        marker_path=run / "profile-retention.json",
        value=marker,
    ):
        raise CleanupError(f"failed profile retention identity is incomplete: {run_id}")
    if not (latest or pending or already_compacted):
        raise CleanupError(f"failed profile retention marker is not compactable: {run_id}")
    summary_state_valid = (
        summary.get("rawTraceRetained") is (False if already_compacted else True)
    )
    if pending:
        summary_state_valid = summary_state_valid or (
            summary.get("rawTraceRetained") is False
            and summary.get("retentionPolicy") == "failedCompacted"
        )
    if not (
        summary.get("schemaVersion") == 1
        and summary.get("runID") == run_id
        and summary.get("status") == "failed"
        and summary_state_valid
    ):
        raise CleanupError(f"failed profile summary is incomplete: {run_id}")
    if not toc.is_file() or toc.stat().st_size == 0:
        raise CleanupError(f"failed profile has no compact trace table of contents: {run_id}")
    if latest and (not trace.is_dir() or trace.is_symlink()):
        raise CleanupError(f"failed profile raw trace is missing or unsafe: {run_id}")
    if already_compacted and trace.exists():
        raise CleanupError(f"compacted failed profile unexpectedly regained a raw trace: {run_id}")
    compact_profile_trace(
        cleaner,
        run=run,
        trace=trace,
        marker=marker,
        reason="acknowledged-failed-profile",
    )


def compact_profile_failures(
    cleaner: Cleaner, root: Path, *, keep_failures: int
) -> None:
    for platform in ("macos", "ios"):
        profiles = root / platform / "profiles"
        if not profiles.is_dir() or profiles.is_symlink():
            continue
        failed: dict[str, list[tuple[str, Path, Path, dict[str, Any]]]] = {}
        latest_published: dict[str, str] = {}
        for run in sorted(profiles.iterdir()):
            marker_path = run / "profile-retention.json"
            if run.is_symlink() or not run.is_dir() or not marker_path.is_file():
                continue
            try:
                marker = load_json(marker_path)
            except CleanupError:
                continue
            if marker.get("retentionPolicy") == "failedCompactionPending":
                pin_path = run / "retention-pin.json"
                pin = load_json(pin_path) if pin_path.is_file() else None
                if pin and pin.get("schemaVersion") == 1 and pin.get("pinned") is True:
                    print(f"profile-retained: path={run} reason=explicitly-pinned")
                elif valid_failed_profile_for_compaction(
                    root=REPO_ROOT, marker_path=marker_path, value=marker
                ):
                    compact_profile_trace(
                        cleaner,
                        run=run,
                        trace=run / f"{run.name}.trace",
                        marker=marker,
                        reason="resume-interrupted-profile-compaction",
                    )
                else:
                    print(
                        f"profile-retained: path={run} "
                        "reason=invalid-pending-compaction"
                    )
                continue
            kind = marker.get("profileKind")
            trace = run / f"{run.name}.trace"
            if kind not in {"cpu", "memory"}:
                if trace.is_dir() and not trace.is_symlink():
                    print(f"profile-retained: path={trace} reason=invalid-retention-marker")
                continue
            if not valid_profile_marker(
                marker, run=run, trace=trace, platform=platform, kind=kind
            ):
                if trace.is_dir() and not trace.is_symlink():
                    print(f"profile-retained: path={trace} reason=invalid-retention-marker")
                continue
            capture = marker["captureTime"]
            if marker.get("status") == "published":
                if not valid_profile_history(run, platform=platform, kind=kind):
                    if trace.is_dir() and not trace.is_symlink():
                        print(f"profile-retained: path={trace} reason=missing-history-proof")
                    continue
                latest_published[kind] = max(latest_published.get(kind, ""), capture)
            if not trace.is_dir() or trace.is_symlink():
                continue
            pin_path = run / "retention-pin.json"
            pin = load_json(pin_path) if pin_path.is_file() else None
            if pin and pin.get("schemaVersion") == 1 and pin.get("pinned") is True:
                print(f"profile-retained: path={trace} reason=explicitly-pinned")
                continue
            if marker.get("status") == "failed":
                if not (
                    marker.get("retentionPolicy") == "failedLatest"
                    and marker.get("rawTraceRetained") is True
                    and valid_profile_failure_summary(
                        run, trace, platform=platform, kind=kind
                    )
                ):
                    print(f"profile-retained: path={trace} reason=invalid-failure-proof")
                    continue
                failed.setdefault(kind, []).append((capture, run, trace, marker))
                continue
            if marker.get("status") != "published":
                print(f"profile-retained: path={trace} reason=invalid-retention-state")
                continue
            if marker.get("retentionPolicy") == "keptExplicitly":
                print(f"profile-retained: path={trace} policy=keptExplicitly")
                continue
            if not (
                marker.get("retentionPolicy") == "summaryOnly"
                and marker.get("rawTraceRetained") is True
            ):
                print(f"profile-retained: path={trace} reason=invalid-retention-state")
                continue
            if not valid_profile_history(
                run, platform=platform, kind=kind, trace=trace
            ):
                print(f"profile-retained: path={trace} reason=invalid-history-proof")
                continue
            cleaner.remove(trace, reason="published-profile-summary")
            if not cleaner.dry_run:
                marker["rawTraceRetained"] = False
                marker["retentionPolicy"] = "summaryOnly"
                atomic_json(marker_path, marker)
        for kind, candidates in failed.items():
            ordered = sorted(candidates, key=lambda item: (item[0], item[1].name), reverse=True)
            published_capture = latest_published.get(kind)
            retained_unpinned = 0
            for capture, run, trace, marker in ordered:
                pin_path = run / "retention-pin.json"
                pin = load_json(pin_path) if pin_path.is_file() else None
                if pin and pin.get("schemaVersion") == 1 and pin.get("pinned") is True:
                    print(f"profile-retained: path={trace} reason=explicitly-pinned")
                    continue
                resolved = published_capture is not None and published_capture > capture
                if retained_unpinned < keep_failures and not resolved:
                    retained_unpinned += 1
                    print(f"profile-retained: path={trace} reason=latest-unresolved-failure")
                    continue
                compact_profile_trace(
                    cleaner,
                    run=run,
                    trace=trace,
                    marker=marker,
                    reason=("resolved-by-newer-profile-pass" if resolved else "superseded-failed-profile"),
                )


def remove_models(cleaner: Cleaner) -> None:
    if not DEBUG_MODELS.exists() and not DEBUG_MODELS.is_symlink():
        return
    if DEBUG_MODELS == SHIPPED_MODELS:
        raise CleanupError("debug and shipped model paths unexpectedly match")
    size = allocated_bytes(DEBUG_MODELS)
    cleaner.planned += size
    verb = "would-remove" if cleaner.dry_run else "removed"
    print(f"{verb}: bytes={size} human={human_bytes(size)} path={DEBUG_MODELS} reason=models")
    if cleaner.dry_run:
        return
    if DEBUG_MODELS.is_symlink() or DEBUG_MODELS.is_file():
        DEBUG_MODELS.unlink()
    else:
        shutil.rmtree(DEBUG_MODELS)


def remove_selected_caches(
    cleaner: Cleaner, policy: dict[str, Any], aliases: list[str]
) -> None:
    selected_aliases = set(aliases)
    if "all" in selected_aliases:
        if len(selected_aliases) != 1:
            raise CleanupError("--cache all cannot be combined with another cache selector")
        selected_ids = set(CACHE_ALIASES.values())
    else:
        selected_ids = {CACHE_ALIASES[alias] for alias in selected_aliases}
    entries = {entry.get("id"): entry for entry in policy_entries(policy)}
    links = validated_public_links(policy, selected_ids)
    selected_paths = [managed_path(entries[entry_id]) for entry_id in sorted(selected_ids)]
    assert_no_active_build(policy)
    assert_paths_idle(selected_paths)
    for entry_id in sorted(selected_ids):
        entry = entries.get(entry_id)
        if not entry or entry.get("class") != "cache":
            raise CleanupError(f"cache selector does not resolve to a cache entry: {entry_id}")
        cleaner.remove(managed_path(entry), reason=f"selected-cache-{entry_id}")
    for link_path in links:
        cleaner.remove(link_path, reason="selected-cache-public-link")


def validated_public_links(
    policy: dict[str, Any], selected_entry_ids: set[str]
) -> list[Path]:
    """Fail closed before cache cleanup if a public product is not the governed symlink."""

    entries = {entry.get("id"): entry for entry in policy_entries(policy)}
    result: list[Path] = []
    for link in policy.get("publicLinks") or []:
        entry_id = link.get("targetEntry")
        if entry_id not in selected_entry_ids:
            continue
        entry = entries.get(entry_id)
        if not entry:
            raise CleanupError(f"public link references unknown cache entry: {entry_id}")
        link_path = REPO_ROOT / str(link["path"])
        if not link_path.exists() and not link_path.is_symlink():
            continue
        if not link_path.is_symlink():
            raise CleanupError(
                f"refusing to remove non-symlink public product during cache cleanup: {link_path}"
            )
        expected = managed_path(entry) / str(link["targetSuffix"])
        actual = (link_path.parent / os.readlink(link_path)).resolve(strict=False)
        if actual != expected.resolve(strict=False):
            raise CleanupError(
                f"public product does not target the selected cache: {link_path}"
            )
        result.append(link_path)
    return result


def assert_no_active_build(policy: dict[str, Any]) -> None:
    entries = {entry.get("id"): entry for entry in policy_entries(policy)}
    packages = entries.get("xcode-source-packages")
    if not packages:
        raise CleanupError("build-output policy is missing the package-store lock owner")
    lock = managed_path(packages) / ".qwenvoice-package-store.lock"
    if not lock.exists():
        return
    if lock.is_symlink() or not lock.is_dir():
        raise CleanupError(f"shared package-store lock is malformed: {lock}")
    try:
        pid_text = (lock / "pid").read_text(encoding="utf-8").strip()
        pid = int(pid_text)
    except (OSError, ValueError) as error:
        raise CleanupError(f"shared package-store lock has no valid owner PID: {lock}") from error
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return
    except PermissionError:
        pass
    raise CleanupError(
        f"a repository build still owns the shared package store (pid {pid}); retry cleanup later"
    )


def assert_paths_idle(paths: Iterable[Path]) -> None:
    lsof = shutil.which("lsof")
    existing = [path for path in paths if path.exists() and not path.is_symlink()]
    if not existing:
        return
    if lsof is None:
        raise CleanupError("lsof is required to verify that selected build paths are idle")
    for path in existing:
        probe = subprocess.run(
            [lsof, "+D", str(path)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if probe.returncode == 0:
            raise CleanupError(f"build output appears to be in use: {path}")


def remove_external_xcode(cleaner: Cleaner, policy: dict[str, Any]) -> None:
    for candidate in matching_external_derived_data(policy):
        probe = subprocess.run(
            ["lsof", "+D", str(candidate)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        ) if shutil.which("lsof") else None
        if probe is not None and probe.returncode == 0:
            raise CleanupError(f"external Xcode DerivedData appears to be in use: {candidate}")
        size = allocated_bytes(candidate)
        cleaner.planned += size
        verb = "would-remove" if cleaner.dry_run else "removed"
        print(
            f"{verb}: bytes={size} human={human_bytes(size)} path={candidate} "
            "reason=exact-project-external-xcode"
        )
        if not cleaner.dry_run:
            shutil.rmtree(candidate)


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_argument_group("cleanup modes")
    modes.add_argument("--routine", action="store_true")
    modes.add_argument("--aggressive", action="store_true")
    modes.add_argument("--prune-ui-results", action="store_true")
    modes.add_argument("--dist", action="store_true")
    modes.add_argument("--models", action="store_true")
    modes.add_argument(
        "--cache",
        action="append",
        choices=(*CACHE_ALIASES.keys(), "all"),
        help="remove only the selected persistent cache; may be repeated",
    )
    modes.add_argument(
        "--compact-profile-failure",
        metavar="RUN_ID",
        help="discard one acknowledged failed raw trace after validating its compact summary",
    )
    modes.add_argument("--external-xcode", action="store_true")
    modes.add_argument("--clobber", action="store_true")
    parser.add_argument("--ui-keep", type=int, default=1)
    parser.add_argument("--yes", action="store_true")
    parser.add_argument("--dry-run", "-n", action="store_true")
    args = parser.parse_args()
    if args.ui_keep < 1:
        parser.error("--ui-keep must be at least 1")
    selected = sum(
        bool(value)
        for value in (
            args.routine, args.aggressive, args.prune_ui_results, args.dist,
            args.models, bool(args.cache), bool(args.compact_profile_failure),
            args.external_xcode, args.clobber,
        )
    )
    if args.aggressive and args.routine:
        selected -= 1
    if selected > 1:
        parser.error("cleanup modes are mutually exclusive")
    if args.ui_keep != 1 and not args.prune_ui_results:
        parser.error("--ui-keep is valid only with --prune-ui-results")
    if (args.external_xcode or args.clobber) and not args.yes:
        parser.error("--external-xcode and --clobber require --yes")
    if args.yes and not (args.external_xcode or args.clobber):
        parser.error("--yes is valid only with --external-xcode or --clobber")
    return args


def main() -> int:
    args = parse_arguments()
    try:
        policy = load_policy()
        before = allocated_bytes(REPO_ROOT)
        inventory(policy)
        any_mode = any(
            (
                args.routine, args.aggressive, args.prune_ui_results, args.dist,
                args.models, bool(args.cache), bool(args.compact_profile_failure),
                args.external_xcode, args.clobber,
            )
        )
        if not any_mode:
            if args.dry_run:
                print("dryRun=true (inventory only; no cleanup mode selected)")
            return 0
        cleaner = Cleaner(dry_run=args.dry_run)
        by_env = {entry.get("env"): entry for entry in policy_entries(policy)}
        ui_retention = policy["childRetention"]["uiResults"]
        if args.prune_ui_results:
            prune_ui(
                cleaner,
                managed_path(by_env["QVOICE_ARTIFACTS_UI_TESTS"]),
                keep_passing=args.ui_keep,
                keep_failures=ui_retention["keepUnresolvedFailuresPerPlatformLane"],
                lanes=ui_retention["lanes"],
            )
        elif args.routine or args.aggressive:
            cleanup_entries = policy_entries(policy, cleanup="routine")
            if args.aggressive:
                cleanup_entries += policy_entries(policy, cleanup="aggressive")
            assert_no_active_build(policy)
            assert_paths_idle(managed_path(entry) for entry in cleanup_entries)
            aggressive_links = (
                validated_public_links(
                    policy,
                    {
                        entry.get("id")
                        for entry in policy_entries(policy, cleanup="aggressive")
                    },
                )
                if args.aggressive
                else []
            )
            for entry in policy_entries(policy, cleanup="routine"):
                cleaner.remove(managed_path(entry), reason="routine")
            compact_profile_failures(
                cleaner,
                REPO_ROOT / "build" / "artifacts",
                keep_failures=policy["childRetention"]["profiles"][
                    "keepFailedPerPlatformKind"
                ],
            )
            prune_ui(
                cleaner,
                managed_path(by_env["QVOICE_ARTIFACTS_UI_TESTS"]),
                keep_passing=ui_retention["keepPassingPerPlatformLane"],
                keep_failures=ui_retention["keepUnresolvedFailuresPerPlatformLane"],
                lanes=ui_retention["lanes"],
            )
            if args.aggressive:
                for entry in policy_entries(policy, cleanup="aggressive"):
                    cleaner.remove(managed_path(entry), reason="aggressive")
                for link_path in aggressive_links:
                    cleaner.remove(link_path, reason="aggressive-public-link")
        elif args.dist:
            for entry in policy_entries(policy, cleanup="dist"):
                cleaner.remove(managed_path(entry), reason="distribution")
        elif args.models:
            remove_models(cleaner)
        elif args.cache:
            remove_selected_caches(cleaner, policy, args.cache)
        elif args.compact_profile_failure:
            compact_named_profile_failure(
                cleaner,
                REPO_ROOT / "build" / "artifacts",
                args.compact_profile_failure,
            )
        elif args.external_xcode:
            remove_external_xcode(cleaner, policy)
        elif args.clobber:
            cleaner.remove(REPO_ROOT / "build", allow_build_root=True, reason="clobber")
            for migration in policy.get("migrations") or []:
                source = REPO_ROOT / str(migration.get("source", ""))
                if source.parts[-1:] == (".build",) and source.exists():
                    if tracked_paths_below(source):
                        raise CleanupError(f"clobber refuses tracked generated path: {source}")
                    size = allocated_bytes(source)
                    cleaner.planned += size
                    verb = "would-remove" if cleaner.dry_run else "removed"
                    print(f"{verb}: bytes={size} human={human_bytes(size)} path={source} reason=clobber")
                    if not cleaner.dry_run:
                        shutil.rmtree(source)

        after = before if args.dry_run else allocated_bytes(REPO_ROOT)
        reclaimed = max(0, before - after)
        print("==> Cleanup summary")
        print(f"repositoryBytesBefore={before}")
        print(f"plannedReclaimBytes={cleaner.planned}")
        print(f"dryRun={'true' if args.dry_run else 'false'}")
        if not args.dry_run:
            print(f"repositoryReclaimedBytes={reclaimed}")
            print(f"repositoryBytesAfter={after}")
        print(f"shippedModelsPreserved={SHIPPED_MODELS}")
        return 0
    except CleanupError as error:
        print(f"build cleanup error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
