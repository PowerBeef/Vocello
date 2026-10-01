#!/usr/bin/env python3
"""Hermetic contracts for the classified build cleanup policy."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
from pathlib import Path
import plistlib
import re
import shutil
import subprocess
import tempfile
import time
from typing import Any
import unittest


REPO_ROOT = Path(__file__).resolve().parents[2]
SHELL = REPO_ROOT / "scripts" / "clean_build_caches.sh"
HELPER = REPO_ROOT / "scripts" / "build_cleanup.py"
POLICY = REPO_ROOT / "config" / "build-output-policy.json"
RETENTION = REPO_ROOT / "scripts" / "lib" / "build_artifact_retention.py"
PROFILE_RETENTION = REPO_ROOT / "scripts" / "lib" / "profile_trace_retention.py"
JSONIO = REPO_ROOT / "scripts" / "lib" / "jsonio.py"


class CleanBuildCachesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        base = Path(self.temporary.name)
        self.root = base / "checkout"
        (self.root / "scripts").mkdir(parents=True)
        (self.root / "scripts" / "lib").mkdir()
        (self.root / "config").mkdir()
        shutil.copy2(SHELL, self.root / "scripts" / SHELL.name)
        shutil.copy2(HELPER, self.root / "scripts" / HELPER.name)
        shutil.copy2(POLICY, self.root / "config" / POLICY.name)
        shutil.copy2(RETENTION, self.root / "scripts" / "lib" / RETENTION.name)
        shutil.copy2(JSONIO, self.root / "scripts" / "lib" / JSONIO.name)
        shutil.copy2(
            PROFILE_RETENTION,
            self.root / "scripts" / "lib" / PROFILE_RETENTION.name,
        )
        (self.root / "scripts" / "benchmark_history.py").write_text(
            """#!/usr/bin/env python3
import json
from pathlib import Path
import sys
if len(sys.argv) != 3 or sys.argv[1] != "validate":
    raise SystemExit(2)
payload = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
raise SystemExit(0 if payload.get("_fixtureValid") is True else 1)
""",
            encoding="utf-8",
        )
        self.home = base / "home"
        self.home.mkdir()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def run_clean(
        self, *arguments: str, expected: int = 0
    ) -> subprocess.CompletedProcess[str]:
        environment = os.environ.copy()
        environment["HOME"] = str(self.home)
        # The host locks resolve under the fixture HOME, never the real one.
        environment.pop("QVOICE_NATIVE_LOCK", None)
        environment.pop("QVOICE_DELIVERY_ANALYSIS_LOCK_ROOT", None)
        result = subprocess.run(
            [str(self.root / "scripts" / SHELL.name), *arguments],
            cwd=self.root,
            env=environment,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(
            result.returncode,
            expected,
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}",
        )
        return result

    @staticmethod
    def write(path: Path, value: str | bytes = "sentinel") -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(value, bytes):
            path.write_bytes(value)
        else:
            path.write_text(value, encoding="utf-8")
        return path

    def track(self, *paths: Path) -> None:
        if not (self.root / ".git").exists():
            subprocess.run(["git", "init", "-q"], cwd=self.root, check=True)
        subprocess.run(
            ["git", "add", "-f", "--", *(str(path.relative_to(self.root)) for path in paths)],
            cwd=self.root,
            check=True,
        )

    def ui_run(self, platform: str, lane: str, suffix: str, status: str) -> Path:
        run_id = f"{platform}-xcui-{lane}-{suffix}"
        run = self.root / "build" / "artifacts" / "ui-tests" / platform / run_id
        self.write(
            run / "run.json",
            json.dumps(
                {
                    "schemaVersion": 2,
                    "platform": platform,
                    "lane": lane,
                    "runID": run_id,
                    "status": status,
                }
            ),
        )
        self.write(run / "result.xcresult" / "payload", b"result")
        return run

    def valid_ui_history(self, run: Path) -> None:
        metadata = json.loads((run / "run.json").read_text())
        record = (
            self.root
            / "benchmarks"
            / "runs"
            / "ui-generation"
            / f"{metadata['runID']}.json"
        )
        self.write(
            record,
            json.dumps(
                {
                    "_fixtureValid": True,
                    "run": {
                        "id": metadata["runID"],
                        "kind": "ui-generation",
                        "platform": metadata["platform"],
                        "status": "passed",
                    },
                }
            ),
        )

    def repairable_ui_evidence(self, run: Path) -> None:
        metadata = json.loads((run / "run.json").read_text())
        self.write(
            run / "benchmark-evidence.json",
            json.dumps(
                {
                    "historyRecord": {
                        "run": {
                            "id": metadata["runID"],
                            "kind": "ui-generation",
                            "platform": metadata["platform"],
                            "status": "passed",
                        }
                    }
                }
            ),
        )

    def profile_run(
        self, run_id: str, *, platform: str = "macos", kind: str = "memory"
    ) -> tuple[Path, Path]:
        run = self.root / "build" / "artifacts" / platform / "profiles" / run_id
        trace = run / f"{run_id}.trace"
        self.write(trace / "instrument_data" / "events.bin", b"trace-data")
        return run, trace

    def profile_marker(
        self,
        run: Path,
        trace: Path,
        *,
        platform: str,
        kind: str,
        status: str,
        policy: str,
        capture_time: str,
    ) -> None:
        self.write(
            run / "profile-retention.json",
            json.dumps(
                {
                    "schemaVersion": 1,
                    "runID": run.name,
                    "platform": platform,
                    "profileKind": kind,
                    "status": status,
                    "retentionPolicy": policy,
                    "rawTraceRetained": True,
                    "captureTime": capture_time,
                    "originalEphemeralPath": trace.relative_to(self.root).as_posix(),
                }
            ),
        )
        self.write(
            run / "profile-failure-summary.json",
            json.dumps(
                {
                    "schemaVersion": 1,
                    "runID": run.name,
                    "platform": platform,
                    "profileKind": kind,
                    "status": status,
                    "captureTime": capture_time,
                    "rawTraceRetained": True,
                    "originalEphemeralPath": trace.relative_to(self.root).as_posix(),
                }
            ),
        )

    @staticmethod
    def trace_digest(trace: Path) -> str:
        rows = [
            [path.relative_to(trace).as_posix(), hashlib.sha256(path.read_bytes()).hexdigest()]
            for path in sorted(trace.rglob("*"))
            if path.is_file()
        ]
        return hashlib.sha256(
            json.dumps(
                rows,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
                allow_nan=False,
            ).encode("utf-8")
        ).hexdigest()

    def published_profile(self, run: Path, trace: Path, *, platform: str) -> None:
        digest = self.trace_digest(trace)
        record = (
            self.root
            / "benchmarks"
            / "runs"
            / "instrument-profile"
            / f"{run.name}.json"
        )
        self.write(
            record,
            json.dumps(
                {
                    "_fixtureValid": True,
                    "run": {
                        "id": run.name,
                        "kind": "instrument-profile",
                        "status": "passed",
                        "platform": platform,
                    },
                    "evidence": {"trace": {"validated": True, "digest": digest}},
                }
            ),
        )

    def test_no_arguments_is_read_only_inventory(self) -> None:
        scratch = self.write(
            self.root / "build" / "scratch" / "derived-data" / "foundation" / "blob"
        )
        result = self.run_clean()
        self.assertTrue(scratch.exists())
        self.assertIn("Build-output inventory", result.stdout)
        self.assertNotIn("removed:", result.stdout)

    def test_routine_is_bounded_and_prunes_only_superseded_ui_evidence(self) -> None:
        scratch = self.write(
            self.root / "build" / "scratch" / "derived-data" / "foundation" / "blob"
        )
        foundation = self.write(self.root / "build" / "artifacts" / "foundation" / "result")
        preserved = [
            self.write(self.root / "build" / "cache" / "xcode" / "macos" / "cache"),
            self.write(self.root / "build" / "dist" / "macos" / "Vocello.dmg"),
            self.write(self.root / "build" / "artifacts" / "symbols" / "macos" / "symbol"),
            self.write(self.root / "build" / "artifacts" / "diagnostics" / "failure.log"),
        ]
        old_pass = self.ui_run("macos", "smoke", "20260713-000001-a", "passed")
        newest_pass = self.ui_run("macos", "smoke", "20260713-000002-b", "passed")
        old_fail = self.ui_run("macos", "smoke", "20260713-000003-c", "failed")
        newest_fail = self.ui_run("macos", "smoke", "20260713-000004-d", "failed")

        self.run_clean("--routine")

        self.assertFalse(scratch.exists())
        self.assertFalse(foundation.exists())
        self.assertFalse(old_pass.exists())
        self.assertTrue(newest_pass.exists())
        self.assertTrue(old_fail.exists())
        self.assertFalse((old_fail / "result.xcresult").exists())
        self.assertTrue((old_fail / "retention-summary.json").is_file())
        self.assertTrue(newest_fail.exists())
        for path in preserved:
            self.assertTrue(path.exists(), path)

    def test_prune_ui_results_is_mutually_exclusive_and_cannot_touch_other_classes(self) -> None:
        old = self.ui_run("ios", "smoke", "20260713-000001-a", "passed")
        newest = self.ui_run("ios", "smoke", "20260713-000002-b", "passed")
        scratch = self.write(self.root / "build" / "scratch" / "derived-data" / "ci" / "blob")
        diagnostics = self.write(self.root / "build" / "artifacts" / "diagnostics" / "report")
        dist = self.write(self.root / "build" / "dist" / "ios" / "Vocello.ipa")
        symbols = self.write(self.root / "build" / "artifacts" / "symbols" / "ios" / "symbol")

        self.run_clean("--prune-ui-results")

        self.assertFalse(old.exists())
        self.assertTrue(newest.exists())
        for path in (scratch, diagnostics, dist, symbols):
            self.assertTrue(path.exists())
        result = self.run_clean("--prune-ui-results", "--routine", expected=2)
        self.assertIn("mutually exclusive", result.stderr)

    def test_explicit_ui_pin_precedes_legacy_metadata_classification(self) -> None:
        run = (
            self.root
            / "build"
            / "artifacts"
            / "ui-tests"
            / "ios"
            / "ios-xcui-control-audit-20260713-000001-a"
        )
        self.write(run / "run.json", "{malformed")
        self.write(run / "result.xcresult" / "payload", b"result")
        self.write(
            run / "retention-pin.json",
            json.dumps(
                {
                    "schemaVersion": 1,
                    "pinned": True,
                    "reason": "campaign-checkpoint",
                }
            ),
        )

        result = self.run_clean("--prune-ui-results", "--dry-run")

        self.assertTrue(run.exists())
        self.assertIn(run.name, result.stdout)
        self.assertIn("reason=explicitly-pinned", result.stdout)

    def test_prune_preserves_benchmark_publication_repair_evidence(self) -> None:
        repair = self.ui_run("macos", "benchmark", "20260713-000001-a", "passed")
        newest = self.ui_run("macos", "benchmark", "20260713-000002-b", "passed")
        self.repairable_ui_evidence(repair)
        result = self.run_clean("--prune-ui-results")
        self.assertTrue(repair.exists())
        self.assertTrue(newest.exists())
        self.assertIn("benchmark-publication-repair-evidence", result.stdout)
        self.valid_ui_history(repair)
        self.run_clean("--prune-ui-results")
        self.assertFalse(repair.exists())

    def test_unrepairable_benchmark_is_compacted_instead_of_retained_forever(self) -> None:
        stale = self.ui_run("macos", "benchmark", "20260713-000001-a", "passed")
        newest = self.ui_run("macos", "benchmark", "20260713-000002-b", "passed")
        result = self.run_clean("--prune-ui-results")
        self.assertTrue(stale.exists())
        self.assertFalse((stale / "result.xcresult").exists())
        self.assertTrue((stale / "retention-summary.json").is_file())
        self.assertTrue(newest.exists())
        self.assertIn("unrepairable-unpublished-benchmark", result.stdout)

        self.write(stale / "late-payload" / "result.bin", b"partial-compaction")
        retry = self.run_clean("--prune-ui-results")
        self.assertFalse((stale / "late-payload").exists())
        self.assertIn("incomplete-compaction", retry.stdout)

    def test_model_download_and_newer_pass_resolve_older_failures(self) -> None:
        old_fail = self.ui_run("ios", "model-download", "20260713-000001-a", "failed")
        old_pass = self.ui_run("ios", "model-download", "20260713-000002-b", "passed")
        newest_pass = self.ui_run("ios", "model-download", "20260713-000003-c", "passed")
        self.run_clean("--prune-ui-results")
        self.assertTrue(old_fail.exists())
        self.assertTrue((old_fail / "retention-summary.json").is_file())
        self.assertFalse(old_pass.exists())
        self.assertTrue(newest_pass.exists())

    def test_selective_cache_cleanup_preserves_other_platforms(self) -> None:
        mac = self.write(self.root / "build" / "cache" / "xcode" / "macos" / "cache")
        ios = self.write(self.root / "build" / "cache" / "xcode" / "ios-device" / "cache")
        packages = self.write(self.root / "build" / "cache" / "xcode" / "source-packages" / "cache")
        runtime = self.write(self.root / "build" / "cache" / "swiftpm" / "mlx-audio-runtime" / "cache")
        public_app = self.root / "build" / "Vocello.app"
        public_app.parent.mkdir(parents=True, exist_ok=True)
        public_app.symlink_to("cache/xcode/macos/Build/Products/Release/Vocello.app")

        self.run_clean("--cache", "macos")

        self.assertFalse(mac.exists())
        self.assertFalse(public_app.is_symlink())
        for path in (ios, packages, runtime):
            self.assertTrue(path.exists())

    def test_a_public_link_into_the_alternate_arena_survives_and_falls_with_it(self) -> None:
        mac = self.write(self.root / "build" / "cache" / "xcode" / "macos" / "cache")
        optimized = self.write(self.root / "build" / "cache" / "xcode" / "macos-optimized" / "cache")
        cli = self.root / "build" / "vocello"
        cli.parent.mkdir(parents=True, exist_ok=True)
        cli.symlink_to("cache/xcode/macos-optimized/Build/Products/Release/vocello")

        self.run_clean("--cache", "macos")
        self.assertFalse(mac.exists())
        self.assertTrue(cli.is_symlink(), "the CLI link points into the optimized arena, which stays")
        self.assertTrue(optimized.exists())

        self.run_clean("--cache", "macos-optimized")
        self.assertFalse(optimized.exists())
        self.assertFalse(cli.is_symlink())

    def test_selective_cache_cleanup_refuses_a_copied_public_product(self) -> None:
        cache = self.write(
            self.root / "build" / "cache" / "xcode" / "macos" / "cache"
        )
        copied = self.write(self.root / "build" / "Vocello.app" / "binary")

        result = self.run_clean("--cache", "macos", expected=1)

        self.assertIn("non-symlink public product", result.stderr)
        self.assertTrue(cache.exists())
        self.assertTrue(copied.exists())

    def test_cache_cleanup_refuses_a_live_shared_package_store_lock(self) -> None:
        cache = self.write(
            self.root / "build" / "cache" / "xcode" / "ios-device" / "cache"
        )
        lock = (
            self.root
            / "build"
            / "cache"
            / "xcode"
            / "source-packages"
            / ".qwenvoice-package-store.lock"
        )
        self.write(lock / "pid", str(os.getpid()))

        result = self.run_clean("--cache", "ios", expected=1)

        self.assertIn("still owns the shared package store", result.stderr)
        self.assertTrue(cache.exists())

    def write_host_lock(self, checkout: Path) -> Path:
        lock = self.home / "Library" / "Caches" / "Vocello" / "native-build.lock"
        self.write(lock / "pid", str(os.getpid()))
        self.write(lock / "checkout", str(checkout))
        return lock

    def test_cache_cleanup_refuses_a_live_host_lock_owned_by_this_checkout(self) -> None:
        cache = self.write(
            self.root / "build" / "cache" / "xcode" / "ios-device" / "cache"
        )
        self.write_host_lock(self.root)

        result = self.run_clean("--cache", "ios", expected=1)

        self.assertIn("still owns the native lock", result.stderr)
        self.assertTrue(cache.exists())

    def test_cache_cleanup_ignores_a_host_lock_owned_by_another_checkout(self) -> None:
        cache = self.write(
            self.root / "build" / "cache" / "xcode" / "ios-device" / "cache"
        )
        self.write_host_lock(self.root.parent / "other-worktree")

        self.run_clean("--cache", "ios")

        self.assertFalse(cache.exists())

    def test_aggressive_removes_persistent_caches_and_links_but_preserves_dist_and_symbols(self) -> None:
        caches = [
            self.write(self.root / "build" / "cache" / "xcode" / "macos" / "cache"),
            self.write(self.root / "build" / "cache" / "xcode" / "ios-device" / "cache"),
            self.write(self.root / "build" / "cache" / "xcode" / "source-packages" / "checkout"),
            self.write(self.root / "build" / "cache" / "swiftpm" / "mlx-audio-runtime" / "cache"),
        ]
        public_app = self.root / "build" / "Vocello.app"
        public_app.parent.mkdir(parents=True, exist_ok=True)
        public_app.symlink_to("cache/xcode/macos/Build/Products/Release/Vocello.app")
        dist = self.write(self.root / "build" / "dist" / "macos" / "Vocello.dmg")
        symbol = self.write(self.root / "build" / "artifacts" / "symbols" / "macos" / "symbol")

        self.run_clean("--aggressive")

        for path in caches:
            self.assertFalse(path.exists())
        self.assertFalse(public_app.is_symlink())
        self.assertTrue(dist.exists())
        self.assertTrue(symbol.exists())

    def test_distribution_cleanup_is_explicit(self) -> None:
        mac = self.write(self.root / "build" / "dist" / "macos" / "Vocello.dmg")
        ios = self.write(self.root / "build" / "dist" / "ios" / "Vocello.ipa")
        cache = self.write(self.root / "build" / "cache" / "xcode" / "macos" / "cache")
        self.run_clean("--dist")
        self.assertFalse(mac.exists())
        self.assertFalse(ios.exists())
        self.assertTrue(cache.exists())

    def test_profile_cleanup_requires_proof_and_keeps_only_latest_failure(self) -> None:
        published_run, published_trace = self.profile_run(
            "mac-memory-profile-20260713-000000-00000001"
        )
        self.profile_marker(
            published_run,
            published_trace,
            platform="macos",
            kind="memory",
            status="published",
            policy="summaryOnly",
            capture_time="2026-07-13T00:00:00Z",
        )
        self.published_profile(published_run, published_trace, platform="macos")
        old_run, old_trace = self.profile_run(
            "mac-memory-profile-20260713-000001-00000002"
        )
        self.profile_marker(
            old_run,
            old_trace,
            platform="macos",
            kind="memory",
            status="failed",
            policy="failedLatest",
            capture_time="2026-07-13T00:00:01Z",
        )
        new_run, new_trace = self.profile_run(
            "mac-memory-profile-20260713-000002-00000003"
        )
        self.profile_marker(
            new_run,
            new_trace,
            platform="macos",
            kind="memory",
            status="failed",
            policy="failedLatest",
            capture_time="2026-07-13T00:00:02Z",
        )

        self.run_clean("--routine")

        self.assertFalse(published_trace.exists())
        self.assertFalse(old_trace.exists())
        self.assertTrue(new_trace.exists())
        old_marker = json.loads((old_run / "profile-retention.json").read_text())
        self.assertEqual(old_marker["retentionPolicy"], "failedCompacted")

    def test_memory_profile_trace_kept_by_default_is_retained_as_valid(self) -> None:
        memory_run, memory_trace = self.profile_run(
            "mac-memory-profile-20260713-000000-00000001"
        )
        self.profile_marker(
            memory_run,
            memory_trace,
            platform="macos",
            kind="memory",
            status="published",
            policy="keptByDefault",
            capture_time="2026-07-13T00:00:00Z",
        )
        self.published_profile(memory_run, memory_trace, platform="macos")
        # Only a memory profile keeps its trace by default; a CPU marker that
        # claims it is kept as invalid state, never removed.
        cpu_run, cpu_trace = self.profile_run(
            "mac-cpu-profile-20260713-000001-00000002", kind="cpu"
        )
        self.profile_marker(
            cpu_run,
            cpu_trace,
            platform="macos",
            kind="cpu",
            status="published",
            policy="keptByDefault",
            capture_time="2026-07-13T00:00:01Z",
        )
        self.published_profile(cpu_run, cpu_trace, platform="macos")

        result = self.run_clean("--routine")

        self.assertTrue(memory_trace.exists())
        self.assertIn(f"/{memory_trace.name} policy=keptByDefault", result.stdout)
        self.assertNotIn(f"/{memory_trace.name} reason=", result.stdout)
        self.assertTrue(cpu_trace.exists())
        self.assertIn(f"/{cpu_trace.name} reason=invalid-retention-state", result.stdout)

    def test_profile_digest_mismatch_is_preserved(self) -> None:
        run, trace = self.profile_run("mac-cpu-profile-20260713-000000-00000001", kind="cpu")
        self.profile_marker(
            run,
            trace,
            platform="macos",
            kind="cpu",
            status="published",
            policy="summaryOnly",
            capture_time="2026-07-13T00:00:00Z",
        )
        self.published_profile(run, trace, platform="macos")
        self.write(trace / "instrument_data" / "events.bin", b"mutated")
        result = self.run_clean("--routine")
        self.assertTrue(trace.exists())
        self.assertIn("invalid-history-proof", result.stdout)

    def test_explicit_failed_profile_compaction_requires_summary_and_toc(self) -> None:
        run_id = "mac-memory-profile-20260713-000000-00000001"
        run, trace = self.profile_run(run_id)
        self.profile_marker(
            run,
            trace,
            platform="macos",
            kind="memory",
            status="failed",
            policy="failedLatest",
            capture_time="2026-07-13T00:00:00Z",
        )
        missing = self.run_clean("--compact-profile-failure", run_id, expected=1)
        self.assertIn("trace table of contents", missing.stderr)
        self.assertTrue(trace.exists())
        self.write(run / "trace-toc.xml", "<trace-toc/>\n")
        self.write(run / "device-diagnostics" / "payload.bin", b"device-diagnostics")
        self.write(run / "small.log", "useful failure context\n")
        self.write(run / "oversized.log", b"x" * (1024 * 1024 + 1))

        self.run_clean("--compact-profile-failure", run_id)

        self.assertFalse(trace.exists())
        self.assertFalse((run / "device-diagnostics").exists())
        self.assertFalse((run / "oversized.log").exists())
        self.assertTrue((run / "small.log").is_file())
        marker = json.loads((run / "profile-retention.json").read_text())
        self.assertEqual(marker["retentionPolicy"], "failedCompacted")
        self.assertFalse(marker["rawTraceRetained"])
        summary = json.loads((run / "profile-failure-summary.json").read_text())
        self.assertIn("small.log", summary["retainedDiagnosticFiles"])

        # Compaction is idempotent and can tighten an older compacted capsule.
        self.write(run / "late-diagnostic" / "payload.bin", b"late-payload")
        self.run_clean("--compact-profile-failure", run_id)
        self.assertFalse((run / "late-diagnostic").exists())

    def test_explicit_failed_profile_compaction_recovers_after_summary_commit(self) -> None:
        run_id = "mac-memory-profile-20260713-000000-00000001"
        run, trace = self.profile_run(run_id)
        self.profile_marker(
            run,
            trace,
            platform="macos",
            kind="memory",
            status="failed",
            policy="failedCompactionPending",
            capture_time="2026-07-13T00:00:00Z",
        )
        marker_path = run / "profile-retention.json"
        summary_path = run / "profile-failure-summary.json"
        marker = json.loads(marker_path.read_text())
        marker["retentionPolicy"] = "failedCompactionPending"
        marker["rawTraceRetained"] = True
        self.write(marker_path, json.dumps(marker))
        summary = json.loads(summary_path.read_text())
        summary["retentionPolicy"] = "failedCompacted"
        summary["rawTraceRetained"] = False
        self.write(summary_path, json.dumps(summary))
        shutil.rmtree(trace)
        self.write(run / "trace-toc.xml", "<trace-toc/>\n")
        self.write(run / "late-diagnostic" / "payload.bin", b"late-payload")

        self.run_clean("--compact-profile-failure", run_id)

        self.assertFalse((run / "late-diagnostic").exists())
        completed_marker = json.loads(marker_path.read_text())
        completed_summary = json.loads(summary_path.read_text())
        self.assertEqual(completed_marker["retentionPolicy"], "failedCompacted")
        self.assertFalse(completed_marker["rawTraceRetained"])
        self.assertEqual(completed_summary["retentionPolicy"], "failedCompacted")
        self.assertFalse(completed_summary["rawTraceRetained"])

    def test_models_removes_only_debug_store(self) -> None:
        debug = self.write(
            self.home / "Library" / "Application Support" / "QwenVoice-Debug" / "models" / "model"
        )
        shipped = self.write(
            self.home / "Library" / "Application Support" / "QwenVoice" / "models" / "model"
        )
        cache = self.write(self.root / "build" / "cache" / "xcode" / "macos" / "cache")
        self.run_clean("--models")
        self.assertFalse(debug.exists())
        self.assertTrue(shipped.exists())
        self.assertTrue(cache.exists())

    def test_clobber_requires_confirmation_and_refuses_tracked_generated_state(self) -> None:
        generated = self.write(self.root / "build" / "cache" / "payload")
        self.run_clean("--clobber", expected=2)
        self.assertTrue(generated.exists())
        tracked = self.write(self.root / "build" / "tracked.txt")
        self.track(tracked)
        result = self.run_clean("--clobber", "--yes", expected=1)
        self.assertIn("tracked files", result.stderr)
        self.assertTrue(tracked.exists())

    def test_external_xcode_removal_requires_exact_project_info_and_confirmation(self) -> None:
        derived = self.home / "Library" / "Developer" / "Xcode" / "DerivedData"
        matching = derived / "QwenVoice-abc"
        unrelated = derived / "Other-def"
        self.write(matching / "payload")
        self.write(unrelated / "payload")
        with (matching / "info.plist").open("wb") as stream:
            plistlib.dump({"WorkspacePath": str(self.root / "QwenVoice.xcodeproj")}, stream)
        with (unrelated / "info.plist").open("wb") as stream:
            plistlib.dump({"WorkspacePath": "/tmp/Other.xcodeproj"}, stream)
        self.run_clean("--external-xcode", expected=2)
        self.run_clean("--external-xcode", "--yes")
        self.assertFalse(matching.exists())
        self.assertTrue(unrelated.exists())

    @property
    def analysis_cache(self) -> Path:
        return self.root / "build" / "cache" / "delivery-analysis"

    @staticmethod
    def shown(path: Path) -> str:
        """A path as the cleanup prints it (its checkout resolved, the last component kept)."""
        return str(path.parent.resolve() / path.name)

    @staticmethod
    def age(path: Path, hours: float) -> None:
        stamp = time.time() - hours * 3600
        for parent, directories, files in os.walk(path, topdown=False):
            for name in (*files, *directories):
                os.utime(Path(parent) / name, (stamp, stamp), follow_symlinks=False)
        os.utime(path, (stamp, stamp))

    def confirmation_fixture(self) -> dict[str, Path]:
        cache = self.analysis_cache
        paths = {
            "audio": self.write(cache / "audio" / "ab" / "canonical.pcm", b"pcm"),
            "layers": self.write(cache / "layers" / "ab" / "l1.json", "{}"),
            "models": self.write(cache / "external-models" / "judge" / "weights.bin", b"weights"),
            "old": self.write(cache / "confirmation" / "cohort" / "layers" / "cd" / "l2.json", "{}").parents[2],
            "fresh": self.write(cache / "confirmation" / "positives" / "audio" / "x.pcm", b"pcm").parents[1],
            "stray": self.write(cache / "confirmation" / "notes.txt", "not a cache root"),
        }
        self.write(paths["old"] / "audio" / "ef" / "canonical.pcm", b"pcm")
        self.age(paths["old"], 48)
        return paths

    def hold_analysis_lock(self) -> Any:
        root = self.home / "Library" / "Caches" / "Vocello" / "delivery-analysis-lock"
        root.mkdir(parents=True, exist_ok=True)
        handle = (root / "delivery-analysis-supervisor.lock").open("a+b")
        self.addCleanup(handle.close)
        # Shared, as an orchestrator run (and every worker it launches) holds it.
        fcntl.flock(handle.fileno(), fcntl.LOCK_SH | fcntl.LOCK_NB)
        return handle

    def test_confirmation_prune_removes_only_idle_roots_under_the_confirmation_directory(self) -> None:
        paths = self.confirmation_fixture()
        inventory = self.run_clean()
        self.assertIn("confirmation-cache: name=cohort", inventory.stdout)
        self.assertIn("confirmation-cache: name=positives", inventory.stdout)

        preview = self.run_clean("--prune-confirmation-caches", "--dry-run")
        self.assertIn("would-remove: bytes=", preview.stdout)
        self.assertIn(f"path={self.shown(paths['old'])} reason=idle-confirmation-cache", preview.stdout)
        self.assertIn(
            f"path={self.shown(paths['fresh'])} idleHours=0.0 minimumIdleHours=24 reason=recently-modified",
            preview.stdout,
        )
        self.assertTrue(paths["old"].exists())

        result = self.run_clean("--prune-confirmation-caches")
        self.assertIn("removed: bytes=", result.stdout)
        self.assertFalse(paths["old"].exists())
        self.assertIn(f"path={self.shown(paths['stray'])} reason=not-a-cache-root", result.stdout)
        for name in ("fresh", "stray", "audio", "layers", "models"):
            self.assertTrue(paths[name].exists(), name)

        self.run_clean("--prune-confirmation-caches", "--older-than-hours", "0")
        self.assertFalse(paths["fresh"].exists())
        for name in ("stray", "audio", "layers", "models"):
            self.assertTrue(paths[name].exists(), name)
        # No confirmation directory at all is a no-op, not an error.
        shutil.rmtree(self.analysis_cache / "confirmation")
        self.assertIn("confirmation-cache: none", self.run_clean("--prune-confirmation-caches").stdout)

    def test_confirmation_prune_refuses_while_an_orchestrator_holds_the_host_analysis_lock(self) -> None:
        paths = self.confirmation_fixture()
        self.hold_analysis_lock()
        for arguments in (("--prune-confirmation-caches",), ("--prune-confirmation-caches", "--dry-run")):
            result = self.run_clean(*arguments, expected=1)
            self.assertIn("holds the host analysis lock", result.stderr)
        self.assertTrue(paths["old"].exists())

    @unittest.skipIf(shutil.which("lsof") is None, "lsof is not installed")
    def test_confirmation_prune_keeps_a_root_with_an_open_file(self) -> None:
        paths = self.confirmation_fixture()
        handle = (paths["old"] / "audio" / "ef" / "canonical.pcm").open("rb")
        self.addCleanup(handle.close)
        self.age(paths["old"], 48)
        result = self.run_clean("--prune-confirmation-caches")
        self.assertIn(f"path={self.shown(paths['old'])} reason=in-use", result.stdout)
        self.assertTrue(paths["old"].exists())

    @unittest.skipIf(shutil.which("lsof") is None, "lsof is not installed")
    def test_selective_cache_cleanup_refuses_a_cache_with_an_open_file(self) -> None:
        # lsof may exit 1 after a partial error even when it lists the holder: its output decides.
        cache = self.write(self.root / "build" / "cache" / "xcode" / "ios-device" / "cache")
        handle = cache.open("rb")
        self.addCleanup(handle.close)
        result = self.run_clean("--cache", "ios", expected=1)
        self.assertIn("appears to be in use", result.stderr)
        self.assertTrue(cache.exists())

    def test_confirmation_prune_never_follows_a_symlink(self) -> None:
        paths = self.confirmation_fixture()
        linked = self.analysis_cache / "confirmation" / "linked"
        linked.symlink_to(self.analysis_cache / "layers", target_is_directory=True)
        result = self.run_clean("--prune-confirmation-caches", "--older-than-hours", "0")
        self.assertIn(f"path={self.shown(linked)} reason=not-a-cache-root", result.stdout)
        self.assertTrue(paths["layers"].exists())
        shutil.rmtree(self.analysis_cache / "confirmation")
        (self.analysis_cache / "confirmation").symlink_to(self.analysis_cache / "layers", target_is_directory=True)
        result = self.run_clean("--prune-confirmation-caches", "--older-than-hours", "0", expected=1)
        self.assertIn("through a symlink", result.stderr)
        self.assertTrue(paths["layers"].exists())

    def test_confirmation_prune_is_its_own_mode_with_a_bounded_age(self) -> None:
        paths = self.confirmation_fixture()
        for arguments in (("--prune-confirmation-caches", "--routine"),
                          ("--older-than-hours", "1"),
                          ("--prune-confirmation-caches", "--older-than-hours", "-1"),
                          ("--prune-confirmation-caches", "--older-than-hours", "nan")):
            self.run_clean(*arguments, expected=2)
        # Routine and aggressive-free cleanup leave confirmation roots to their own mode.
        self.run_clean("--routine")
        self.assertTrue(paths["old"].exists())

    # --qc-v1: the one-time removal of the retired v1 audio QC data (qcV1Cleanup).

    BEFORE_CUTOFF = time.mktime((2026, 9, 20, 12, 0, 0, 0, 0, -1))

    @staticmethod
    def stamp(path: Path, epoch: float) -> None:
        for parent, directories, files in os.walk(path, topdown=False):
            for name in (*files, *directories):
                os.utime(Path(parent) / name, (epoch, epoch), follow_symlinks=False)
        os.utime(path, (epoch, epoch), follow_symlinks=False)

    def qc_v1_fixture(self) -> dict[str, Path]:
        build = self.root / "build"
        models = self.analysis_cache / "external-models"
        corpora = build / "cache" / "audio-qc-corpora"
        runs = build / "artifacts" / "macos" / "audio-qc"
        diagnostics = build / "artifacts" / "diagnostics"
        qc = build / "cache" / "qc"
        paths = {
            "seeded": self.write(models / "qwen3-asr" / "model.safetensors", b"weights"),
            "old-judge": self.write(models / "old-judge" / "model.bin", b"judge").parent,
            "interpreter": self.write(models / "audio-qc-python-3.14.4" / "bin" / "python3", b"py").parents[1],
            "venv-home": self.write(models / "runtime-py314" / "bin" / "python3", b"py").parents[1],
            "audio": self.write(self.analysis_cache / "audio" / "ab" / "canonical.pcm", b"pcm").parents[1],
            "layers": self.write(self.analysis_cache / "layers" / "ab" / "l1.json", "{}").parents[1],
            "confirmation": self.write(self.analysis_cache / "confirmation" / "cohort" / "l2.json", "{}").parents[1],
            "adapter-config": self.write(self.analysis_cache / "whisper-small-mlx.json", "{}"),
            "fleurs": self.write(corpora / "fleurs" / "rev" / "corpora-fetch-receipt.json", "{}").parents[1],
            "libritts": self.write(corpora / "libritts-r" / "rev" / "corpora-fetch-receipt.json", "{}").parents[1],
            "cohorts": self.write(corpora / "speaker-cohorts" / "id" / "share-0.5" / "x.wav", b"wav").parents[2],
            "registry-receipt": self.write(corpora / "registry-receipt.json", "{}"),
            "qc-n2": self.write(runs / "qc-n2-mac-qc-n2-20260930-1" / "takes" / "a.wav", b"wav").parents[1],
            "acquire-log": self.write(runs / "acquire-all.log", "log"),
            "qc-takes": self.write(runs / "qc-takes-mac-qc-takes-20260930-2" / "wav" / "a.wav", b"wav").parents[1],
            "variation": self.write(runs / "variation-experiment-20261001" / "a.wav", b"wav").parent,
            "today": self.write(runs / "fresh-run" / "a.wav", b"wav").parent,
            "ladders": self.write(diagnostics / "audio-qc-oracle-ladders" / "report.json", "{}").parent,
            "ios-logs": self.write(diagnostics / "ios" / "logs" / "device.log", "log").parent,
            "python-copy": self.write(qc / "runtimes" / "python" / "bin" / "python3", b"py"),
        }
        # QC v2 seeded this model by hard link, and one venv's home is a v1 runtime.
        paths["v2-link"] = qc / "models" / "asr.qwen3-asr-1.7b" / "model.safetensors"
        paths["v2-link"].parent.mkdir(parents=True)
        os.link(paths["seeded"], paths["v2-link"])
        self.write(qc / "runtimes" / "mlx" / "pyvenv.cfg", f"home = {paths['venv-home'] / 'bin'}\n")
        # A link is listed, never followed.
        outside = self.write(Path(self.temporary.name) / "outside" / "weights.bin", b"outside").parent
        paths["outside"] = outside
        paths["symlinked"] = models / "linked-judge"
        paths["symlinked"].symlink_to(outside, target_is_directory=True)
        for name in ("qc-n2", "acquire-log", "qc-takes", "ladders"):
            self.stamp(paths[name], self.BEFORE_CUTOFF)
        return paths

    def test_qc_v1_needs_a_dry_run_or_yes_and_is_its_own_mode(self) -> None:
        for arguments in (("--qc-v1",), ("--qc-v1", "--routine", "--dry-run"), ("--yes",)):
            self.run_clean(*arguments, expected=2)
        # The checked-in contract loads, and a tree without v1 data plans nothing.
        result = self.run_clean("--qc-v1", "--dry-run")
        self.assertIn("state=absent", result.stdout)
        self.assertIn("plannedReclaimBytes=0", result.stdout)

    def test_qc_v1_removes_v1_data_and_keeps_what_qc_v2_and_the_take_generator_use(self) -> None:
        paths = self.qc_v1_fixture()
        removed = ("old-judge", "interpreter", "audio", "layers", "confirmation", "fleurs",
                   "qc-n2", "acquire-log", "ladders")
        kept = {
            "seeded": None,
            "venv-home": "qc-v2-links-into-it",
            "libritts": "kept-by-name",
            "cohorts": "kept-by-name",
            "registry-receipt": "kept-file",
            "qc-takes": "kept-by-prefix",
            "variation": "kept-by-prefix",
            "today": "created-on-or-after-cutoff",
            "symlinked": "symlink-not-followed",
        }

        preview = self.run_clean("--qc-v1", "--dry-run")
        self.assertIn("would-remove: bytes=", preview.stdout)
        for name in removed:
            self.assertIn(f"path={self.shown(paths[name])} reason=qc-v1-", preview.stdout, name)
            self.assertTrue(paths[name].exists(), name)
        for name, reason in kept.items():
            if reason is not None:
                self.assertIn(f"path={self.shown(paths[name])} reason={reason}", preview.stdout, name)
        self.assertIn(
            f"path={self.shown(paths['seeded'].parent)} reason=qc-v2-hard-links:1", preview.stdout
        )
        self.assertIn("qc-v1-target: id=judge-models", preview.stdout)
        self.assertIn("dryRun=true", preview.stdout)

        result = self.run_clean("--qc-v1", "--yes")
        self.assertIn("removed: bytes=", result.stdout)
        for name in removed:
            self.assertFalse(paths[name].exists(), name)
        for name in (*kept, "adapter-config", "ios-logs", "python-copy", "outside"):
            self.assertTrue(paths[name].exists() or paths[name].is_symlink(), name)
        self.assertEqual(paths["v2-link"].read_bytes(), b"weights")
        self.assertTrue((paths["outside"] / "weights.bin").exists())

    def test_qc_v1_keeps_the_pinned_interpreter_until_qc_v2_has_its_copy(self) -> None:
        paths = self.qc_v1_fixture()
        shutil.rmtree(self.root / "build" / "cache" / "qc" / "runtimes" / "python")
        result = self.run_clean("--qc-v1", "--yes")
        self.assertIn(
            f"path={self.shown(paths['interpreter'])} "
            "reason=kept-until-present:build/cache/qc/runtimes/python",
            result.stdout,
        )
        self.assertTrue(paths["interpreter"].exists())
        self.assertFalse(paths["old-judge"].exists())

    def test_qc_v1_lists_bytes_another_hard_link_keeps_allocated(self) -> None:
        paths = self.qc_v1_fixture()
        elsewhere = self.root / "build" / "scratch" / "transient" / "model.bin"
        elsewhere.parent.mkdir(parents=True)
        os.link(paths["old-judge"] / "model.bin", elsewhere)
        result = self.run_clean("--qc-v1", "--dry-run")
        self.assertIn("qc-v1-shared: sharedBytes=", result.stdout)
        self.assertIn(f"path={self.shown(paths['old-judge'])}\n", result.stdout)
        # The summary counts a hard-linked file only when every link goes with the removal.
        summary = re.search(r"qc-v1-summary: allocatedBytes=(\d+) reclaimableBytes=(\d+)", result.stdout)
        self.assertIsNotNone(summary)
        allocated, reclaimable = int(summary.group(1)), int(summary.group(2))
        self.assertEqual(allocated - reclaimable, (paths["old-judge"] / "model.bin").lstat().st_blocks * 512)

    def test_qc_v1_refuses_while_a_qc_run_or_a_v1_analyzer_holds_its_lock(self) -> None:
        paths = self.qc_v1_fixture()
        run_lock = self.root / "build" / "cache" / "qc" / "run.lock"
        handle = run_lock.open("a+b")
        self.addCleanup(handle.close)
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        for arguments in (("--qc-v1", "--dry-run"), ("--qc-v1", "--yes")):
            result = self.run_clean(*arguments, expected=1)
            self.assertIn("a qc.py run holds build/cache/qc/run.lock", result.stderr)
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

        self.hold_analysis_lock()
        for arguments in (("--qc-v1", "--dry-run"), ("--qc-v1", "--yes")):
            result = self.run_clean(*arguments, expected=1)
            self.assertIn("holds the host analysis lock", result.stderr)
        for name in ("old-judge", "audio", "fleurs", "qc-n2", "ladders"):
            self.assertTrue(paths[name].exists(), name)

    def test_qc_v1_refuses_a_symlinked_root_before_removing_anything(self) -> None:
        paths = self.qc_v1_fixture()
        runs = self.root / "build" / "artifacts" / "macos" / "audio-qc"
        outside = Path(self.temporary.name) / "outside-runs"
        shutil.move(str(runs), str(outside))
        runs.symlink_to(outside, target_is_directory=True)
        result = self.run_clean("--qc-v1", "--yes", expected=1)
        self.assertIn("through a symlink: build/artifacts/macos/audio-qc", result.stderr)
        self.assertTrue((outside / "acquire-all.log").exists())
        self.assertTrue(paths["old-judge"].exists())
        # A registered entry that is itself a link fails the policy before any mode runs.
        runs.unlink()
        corpora = self.root / "build" / "cache" / "audio-qc-corpora"
        shutil.move(str(corpora), str(outside / "corpora"))
        corpora.symlink_to(outside / "corpora", target_is_directory=True)
        self.run_clean("--qc-v1", "--yes", expected=1)
        self.assertTrue((outside / "corpora" / "fleurs").exists())

    @unittest.skipIf(shutil.which("lsof") is None, "lsof is not installed")
    def test_qc_v1_keeps_a_child_with_an_open_file(self) -> None:
        paths = self.qc_v1_fixture()
        handle = (paths["old-judge"] / "model.bin").open("rb")
        self.addCleanup(handle.close)
        result = self.run_clean("--qc-v1", "--yes")
        self.assertIn(f"path={self.shown(paths['old-judge'])} reason=in-use", result.stdout)
        self.assertTrue(paths["old-judge"].exists())
        self.assertFalse(paths["audio"].exists())

    def test_symlinked_build_root_cannot_escape_repository(self) -> None:
        outside = Path(self.temporary.name) / "outside"
        self.write(outside / "scratch" / "derived-data" / "foundation" / "payload")
        (self.root / "build").symlink_to(outside, target_is_directory=True)
        result = self.run_clean("--routine", expected=1)
        self.assertIn("escapes", result.stderr)
        self.assertTrue((outside / "scratch" / "derived-data" / "foundation" / "payload").exists())


if __name__ == "__main__":
    unittest.main()
