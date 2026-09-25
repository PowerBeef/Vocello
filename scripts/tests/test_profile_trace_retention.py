from __future__ import annotations

import json
import hashlib
from pathlib import Path
import subprocess
import tempfile
import unittest


REPO = Path(__file__).resolve().parents[2]
HELPER = REPO / "scripts" / "lib" / "profile_trace_retention.py"


class ProfileTraceRetentionTests(unittest.TestCase):
    def run_helper(
        self, root: Path, *arguments: str, expected: int = 0
    ) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            ["python3", str(HELPER), *arguments, "--root", str(root)],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, expected, result.stderr)
        return result

    def profile_artifacts(
        self, root: Path, platform: str, run_id: str
    ) -> tuple[Path, Path]:
        policy = root / "config" / "build-output-policy.json"
        if not policy.exists():
            policy.parent.mkdir(parents=True, exist_ok=True)
            policy.write_text(
                json.dumps(
                    {
                        "schemaVersion": 1,
                        "childRetention": {
                            "schemaVersion": 1,
                            "profiles": {
                                "entries": ["artifacts-macos", "artifacts-ios"],
                                "markerFilename": "profile-retention.json",
                                "pinFilename": "retention-pin.json",
                                "keepFailedPerPlatformKind": 1,
                                "maximumCompactedDiagnosticBytes": 8 * 1024 * 1024,
                                "maximumDiagnosticLogBytes": 1024 * 1024,
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
        artifacts = root / "build" / "artifacts" / platform / "profiles" / run_id
        trace = artifacts / f"{run_id}.trace"
        trace.mkdir(parents=True)
        (trace / "event.data").write_bytes(b"trace-data")
        return artifacts, trace

    def publication_proof(
        self, root: Path, artifacts: Path, trace: Path, policy: str
    ) -> tuple[Path, Path]:
        run_id = artifacts.name
        original = trace.relative_to(root).as_posix()
        summary = artifacts / "profile-summary.json"
        trace_manifest = [
            [
                path.relative_to(trace).as_posix(),
                hashlib.sha256(path.read_bytes()).hexdigest(),
            ]
            for path in sorted(trace.rglob("*"))
            if path.is_file()
        ]
        trace_digest = hashlib.sha256(
            json.dumps(
                trace_manifest,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
                allow_nan=False,
            ).encode("utf-8")
        ).hexdigest()
        summary.write_text(
            json.dumps(
                {
                    "schemaVersion": 1,
                    "runID": run_id,
                    "traceDigest": trace_digest,
                    "originalEphemeralPath": original,
                    "retentionPolicy": policy,
                    "rawTraceRetained": policy in {"keptExplicitly", "keptByDefault"},
                },
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        summary_digest = hashlib.sha256(summary.read_bytes()).hexdigest()
        trace_record = {
            "digest": trace_digest,
            "originalEphemeralPath": original,
            "summaryArtifact": {
                "path": summary.relative_to(root).as_posix(),
                "digest": summary_digest,
            },
            "rawTraceRetained": policy in {"keptExplicitly", "keptByDefault"},
            "retentionPolicy": policy,
            "captureSettingsDigest": "b" * 64,
        }
        frozen = {"run": {"id": run_id}, "evidence": {"trace": trace_record}}
        (artifacts / "benchmark-evidence.json").write_text(
            json.dumps({"historyRecord": frozen}), encoding="utf-8"
        )
        history = root / "benchmarks" / "runs" / "instrument-profile" / f"{run_id}.json"
        history.parent.mkdir(parents=True, exist_ok=True)
        history.write_text(json.dumps(frozen), encoding="utf-8")
        return summary, history

    def test_low_space_preflight_fails_with_exact_routine_cleanup_guidance(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for kind, threshold in (("cpu", 5), ("memory", 15)):
                with self.subTest(kind=kind):
                    result = self.run_helper(
                        root,
                        "preflight",
                        "--kind",
                        kind,
                        "--available-bytes",
                        "1",
                        expected=2,
                    )
                    self.assertIn(f"{threshold} GiB required", result.stderr)
                    self.assertIn("scripts/clean_build_caches.sh --routine", result.stderr)
                    self.assertIn("before launching the target or Instruments", result.stderr)

    def test_summary_only_refuses_deletion_until_publication_proof_exists(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            run_id = "mac-memory-profile-20260713-000000-deadbeef"
            artifacts, trace = self.profile_artifacts(root, "macos", run_id)
            summary, history = self.publication_proof(
                root, artifacts, trace, "summaryOnly"
            )
            (artifacts / "benchmark-evidence.json").unlink()

            result = self.run_helper(
                root,
                "finalize-success",
                "--platform",
                "macos",
                "--kind",
                "memory",
                "--artifact-dir",
                str(artifacts),
                "--trace",
                str(trace),
                "--policy",
                "summaryOnly",
                "--summary-artifact",
                str(summary),
                "--history-record",
                str(history),
                expected=1,
            )
            self.assertIn("benchmark evidence is missing", result.stderr)
            self.assertTrue(trace.is_dir())

            self.publication_proof(root, artifacts, trace, "summaryOnly")
            self.run_helper(
                root,
                "finalize-success",
                "--platform",
                "macos",
                "--kind",
                "memory",
                "--artifact-dir",
                str(artifacts),
                "--trace",
                str(trace),
                "--policy",
                "summaryOnly",
                "--summary-artifact",
                str(summary),
                "--history-record",
                str(history),
            )
            self.assertFalse(trace.exists())
            marker = json.loads((artifacts / "profile-retention.json").read_text())
            self.assertEqual(marker["status"], "published")
            self.assertEqual(marker["retentionPolicy"], "summaryOnly")
            self.assertFalse(marker["rawTraceRetained"])

    def test_keep_trace_preserves_raw_trace_after_publication(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            run_id = "ios-cpu-profile-20260713-000000-cafebabe"
            artifacts, trace = self.profile_artifacts(root, "ios", run_id)
            summary, history = self.publication_proof(
                root, artifacts, trace, "keptExplicitly"
            )
            self.run_helper(
                root,
                "finalize-success",
                "--platform",
                "ios",
                "--kind",
                "cpu",
                "--artifact-dir",
                str(artifacts),
                "--trace",
                str(trace),
                "--policy",
                "keptExplicitly",
                "--summary-artifact",
                str(summary),
                "--history-record",
                str(history),
            )
            self.assertTrue(trace.is_dir())
            marker = json.loads((artifacts / "profile-retention.json").read_text())
            self.assertEqual(marker["retentionPolicy"], "keptExplicitly")
            self.assertTrue(marker["rawTraceRetained"])

    def test_memory_profile_keeps_its_trace_by_default_and_only_memory_may(self) -> None:
        # xctrace cannot export a memory profile's allocation and VM tables, so
        # its trace is kept by default (audit #69); a CPU profile never is.
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for platform, run_id, kind, expected in (
                ("macos", "mac-memory-profile-20260925-000000-0badcafe", "memory", 0),
                ("ios", "ios-cpu-profile-20260925-000000-0badf00d", "cpu", 1),
            ):
                with self.subTest(kind=kind):
                    artifacts, trace = self.profile_artifacts(root, platform, run_id)
                    summary, history = self.publication_proof(
                        root, artifacts, trace, "keptByDefault"
                    )
                    self.run_helper(
                        root, "finalize-success", "--platform", platform, "--kind", kind,
                        "--artifact-dir", str(artifacts), "--trace", str(trace),
                        "--policy", "keptByDefault", "--summary-artifact", str(summary),
                        "--history-record", str(history), expected=expected,
                    )
                    self.assertTrue(trace.is_dir())
                    marker_path = artifacts / "profile-retention.json"
                    if kind == "memory":
                        marker = json.loads(marker_path.read_text())
                        self.assertEqual(marker["retentionPolicy"], "keptByDefault")
                        self.assertTrue(marker["rawTraceRetained"])
                    else:
                        self.assertFalse(marker_path.exists())

    def test_stale_summary_digest_cannot_authorize_trace_deletion(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            run_id = "mac-cpu-profile-20260713-000000-12345678"
            artifacts, trace = self.profile_artifacts(root, "macos", run_id)
            summary, history = self.publication_proof(
                root, artifacts, trace, "summaryOnly"
            )
            summary.write_text(summary.read_text() + "\n", encoding="utf-8")
            result = self.run_helper(
                root,
                "finalize-success",
                "--platform",
                "macos",
                "--kind",
                "cpu",
                "--artifact-dir",
                str(artifacts),
                "--trace",
                str(trace),
                "--policy",
                "summaryOnly",
                "--summary-artifact",
                str(summary),
                "--history-record",
                str(history),
                expected=1,
            )
            self.assertIn("summary digest does not match", result.stderr)
            self.assertTrue(trace.is_dir())

    def test_trace_mutation_after_publication_cannot_authorize_deletion(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            run_id = "mac-memory-profile-20260713-000000-87654321"
            artifacts, trace = self.profile_artifacts(root, "macos", run_id)
            summary, history = self.publication_proof(
                root, artifacts, trace, "summaryOnly"
            )
            (trace / "event.data").write_bytes(b"trace-data-mutated-after-publication")
            result = self.run_helper(
                root,
                "finalize-success",
                "--platform",
                "macos",
                "--kind",
                "memory",
                "--artifact-dir",
                str(artifacts),
                "--trace",
                str(trace),
                "--policy",
                "summaryOnly",
                "--summary-artifact",
                str(summary),
                "--history-record",
                str(history),
                expected=1,
            )
            self.assertIn("raw trace digest changed after publication", result.stderr)
            self.assertTrue(trace.is_dir())
            self.assertTrue((trace / "event.data").is_file())

    def test_repeated_failures_retain_only_newest_raw_trace_per_platform_and_kind(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first_id = "mac-memory-profile-20260713-000000-00000001"
            second_id = "mac-memory-profile-20260713-000001-00000002"
            first_artifacts, first_trace = self.profile_artifacts(root, "macos", first_id)
            self.run_helper(
                root,
                "mark-failure",
                "--platform",
                "macos",
                "--kind",
                "memory",
                "--artifact-dir",
                str(first_artifacts),
                "--trace",
                str(first_trace),
                "--phase",
                "trace-export",
                "--exit-code",
                "1",
            )
            (first_artifacts / "device-diagnostics" / "nested").mkdir(parents=True)
            (first_artifacts / "device-diagnostics" / "nested" / "payload.bin").write_bytes(
                b"diagnostic-payload"
            )
            (first_artifacts / "small.log").write_text("useful failure context\n")
            (first_artifacts / "oversized.log").write_bytes(b"x" * (1024 * 1024 + 1))
            second_artifacts, second_trace = self.profile_artifacts(root, "macos", second_id)
            self.run_helper(
                root,
                "mark-failure",
                "--platform",
                "macos",
                "--kind",
                "memory",
                "--artifact-dir",
                str(second_artifacts),
                "--trace",
                str(second_trace),
                "--phase",
                "history-publication",
                "--exit-code",
                "1",
            )
            self.assertFalse(first_trace.exists())
            self.assertTrue(second_trace.is_dir())
            first_marker = json.loads(
                (first_artifacts / "profile-retention.json").read_text()
            )
            second_marker = json.loads(
                (second_artifacts / "profile-retention.json").read_text()
            )
            self.assertEqual(first_marker["retentionPolicy"], "failedCompacted")
            self.assertFalse(first_marker["rawTraceRetained"])
            self.assertEqual(second_marker["retentionPolicy"], "failedLatest")
            self.assertTrue(second_marker["rawTraceRetained"])
            compact = json.loads(
                (first_artifacts / "profile-failure-summary.json").read_text()
            )
            self.assertEqual(compact["failurePhase"], "trace-export")
            self.assertFalse(compact["rawTraceRetained"])
            self.assertFalse((first_artifacts / "device-diagnostics").exists())
            self.assertFalse((first_artifacts / "oversized.log").exists())
            self.assertTrue((first_artifacts / "small.log").is_file())
            self.assertIn("small.log", compact["retainedDiagnosticFiles"])
            self.assertNotIn("oversized.log", compact["retainedDiagnosticFiles"])

    def test_out_of_order_failure_marking_keeps_newest_capture_not_newest_marker(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            newer_id = "mac-memory-profile-20260713-000010-00000002"
            older_id = "mac-memory-profile-20260713-000001-00000001"
            newer_artifacts, newer_trace = self.profile_artifacts(root, "macos", newer_id)
            self.run_helper(
                root, "mark-failure", "--platform", "macos", "--kind", "memory",
                "--artifact-dir", str(newer_artifacts), "--trace", str(newer_trace),
                "--phase", "trace-export", "--exit-code", "1",
            )
            older_artifacts, older_trace = self.profile_artifacts(root, "macos", older_id)
            self.run_helper(
                root, "mark-failure", "--platform", "macos", "--kind", "memory",
                "--artifact-dir", str(older_artifacts), "--trace", str(older_trace),
                "--phase", "legacy-migration", "--exit-code", "1",
            )
            self.assertTrue(newer_trace.is_dir())
            self.assertFalse(older_trace.exists())
            older_marker = json.loads(
                (older_artifacts / "profile-retention.json").read_text()
            )
            self.assertEqual(older_marker["retentionPolicy"], "failedCompacted")
            self.assertEqual(older_marker["captureTime"], "2026-07-13T00:00:01Z")

    def test_interrupted_pending_compaction_is_resumed_before_new_retention_work(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            pending_id = "mac-memory-profile-20260713-000000-00000001"
            current_id = "mac-memory-profile-20260713-000001-00000002"
            pending_artifacts, pending_trace = self.profile_artifacts(
                root, "macos", pending_id
            )
            self.run_helper(
                root, "mark-failure", "--platform", "macos", "--kind", "memory",
                "--artifact-dir", str(pending_artifacts), "--trace", str(pending_trace),
                "--phase", "trace-export", "--exit-code", "1",
            )

            marker_path = pending_artifacts / "profile-retention.json"
            summary_path = pending_artifacts / "profile-failure-summary.json"
            marker = json.loads(marker_path.read_text())
            summary = json.loads(summary_path.read_text())
            marker.update(
                {
                    "retentionPolicy": "failedCompactionPending",
                    "rawTraceRetained": True,
                    "compactionStartedAt": "2026-07-13T00:00:30Z",
                }
            )
            summary.update(
                {
                    "retentionPolicy": "failedCompactionPending",
                    "rawTraceRetained": True,
                    "compactionStartedAt": "2026-07-13T00:00:30Z",
                }
            )
            marker_path.write_text(json.dumps(marker), encoding="utf-8")
            summary_path.write_text(json.dumps(summary), encoding="utf-8")
            (pending_artifacts / "late-payload.bin").write_bytes(b"partial-compaction")

            current_artifacts, current_trace = self.profile_artifacts(
                root, "macos", current_id
            )
            self.run_helper(
                root, "mark-failure", "--platform", "macos", "--kind", "memory",
                "--artifact-dir", str(current_artifacts), "--trace", str(current_trace),
                "--phase", "target-launch", "--exit-code", "1",
            )

            self.assertFalse(pending_trace.exists())
            self.assertFalse((pending_artifacts / "late-payload.bin").exists())
            completed_marker = json.loads(marker_path.read_text())
            completed_summary = json.loads(summary_path.read_text())
            self.assertEqual(completed_marker["retentionPolicy"], "failedCompacted")
            self.assertFalse(completed_marker["rawTraceRetained"])
            self.assertEqual(completed_summary["retentionPolicy"], "failedCompacted")
            self.assertFalse(completed_summary["rawTraceRetained"])
            self.assertTrue(current_trace.is_dir())

    def test_explicitly_pinned_failure_is_never_compacted_by_a_new_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first_id = "mac-memory-profile-20260713-000000-00000001"
            second_id = "mac-memory-profile-20260713-000001-00000002"
            first_artifacts, first_trace = self.profile_artifacts(root, "macos", first_id)
            (first_artifacts / "retention-pin.json").write_text(
                json.dumps({"schemaVersion": 1, "pinned": True}),
                encoding="utf-8",
            )
            self.run_helper(
                root, "mark-failure", "--platform", "macos", "--kind", "memory",
                "--artifact-dir", str(first_artifacts), "--trace", str(first_trace),
                "--phase", "trace-export", "--exit-code", "1",
            )
            second_artifacts, second_trace = self.profile_artifacts(root, "macos", second_id)
            self.run_helper(
                root, "mark-failure", "--platform", "macos", "--kind", "memory",
                "--artifact-dir", str(second_artifacts), "--trace", str(second_trace),
                "--phase", "target-launch", "--exit-code", "1",
            )

            self.assertTrue(first_trace.is_dir())
            self.assertTrue(second_trace.is_dir())
            first_marker = json.loads(
                (first_artifacts / "profile-retention.json").read_text()
            )
            self.assertEqual(first_marker["retentionPolicy"], "failedLatest")

    def test_legacy_cpu_run_id_can_be_marked_for_cleanup_migration(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            run_id = "ios-profile-20260712-211534-85ae97f5"
            artifacts, trace = self.profile_artifacts(root, "ios", run_id)
            self.run_helper(
                root, "mark-failure", "--platform", "ios", "--kind", "cpu",
                "--artifact-dir", str(artifacts), "--trace", str(trace),
                "--phase", "legacy-migration", "--exit-code", "1",
            )
            marker = json.loads((artifacts / "profile-retention.json").read_text())
            self.assertEqual(marker["captureTime"], "2026-07-12T21:15:34Z")
            self.assertTrue(marker["rawTraceRetained"])

    def test_symlinked_build_ancestor_cannot_escape_repository(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root = base / "repo"
            outside = base / "outside"
            root.mkdir()
            (outside / "artifacts" / "macos" / "profiles").mkdir(parents=True)
            (root / "build").symlink_to(outside, target_is_directory=True)
            run_id = "mac-cpu-profile-20260713-000000-feedface"
            artifacts = root / "build" / "artifacts" / "macos" / "profiles" / run_id
            trace = artifacts / f"{run_id}.trace"
            trace.mkdir(parents=True)
            (trace / "event.data").write_bytes(b"outside-repository")
            result = self.run_helper(
                root, "mark-failure", "--platform", "macos", "--kind", "cpu",
                "--artifact-dir", str(artifacts), "--trace", str(trace),
                "--phase", "trace-export", "--exit-code", "1", expected=1,
            )
            self.assertIn("real non-symlink directory", result.stderr)
            self.assertTrue(trace.is_dir())
            self.assertFalse((artifacts / "profile-retention.json").exists())

    def test_invalid_retention_contract_never_compacts_an_older_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first_id = "mac-memory-profile-20260713-000000-00000001"
            second_id = "mac-memory-profile-20260713-000001-00000002"
            first_artifacts, first_trace = self.profile_artifacts(root, "macos", first_id)
            self.run_helper(
                root, "mark-failure", "--platform", "macos", "--kind", "memory",
                "--artifact-dir", str(first_artifacts), "--trace", str(first_trace),
                "--phase", "trace-export", "--exit-code", "1",
            )
            second_artifacts, second_trace = self.profile_artifacts(root, "macos", second_id)
            (root / "config" / "build-output-policy.json").write_text(
                "{\"childRetention\":{\"profiles\":{}}}\n", encoding="utf-8"
            )

            result = self.run_helper(
                root, "mark-failure", "--platform", "macos", "--kind", "memory",
                "--artifact-dir", str(second_artifacts), "--trace", str(second_trace),
                "--phase", "target-launch", "--exit-code", "1", expected=1,
            )

            self.assertIn("invalid profile retention contract", result.stderr)
            self.assertTrue(first_trace.is_dir())
            self.assertTrue(second_trace.is_dir())


if __name__ == "__main__":
    unittest.main()
