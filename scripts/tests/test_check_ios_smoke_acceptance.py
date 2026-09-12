#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
CHECKER = ROOT / "scripts" / "check_ios_smoke_acceptance.py"
RUN_ID = "ios-xcui-smoke-fixture"


def memory_row(
    event: str,
    index: int,
    *,
    reason: str = "active_generation_sample_debug_force_critical_once",
    trim_level: str | None = None,
) -> dict:
    return {
        "event": event,
        "recordedAt": f"2026-07-15T12:00:0{index}Z",
        "processUptimeSeconds": 100.0 + index,
        "runID": RUN_ID,
        "reason": reason,
        "trimLevel": trim_level,
    }


def valid_memory_rows() -> list[dict]:
    return [
        memory_row("debug_force_critical_once", 1),
        memory_row("critical_memory_action", 2),
        memory_row("critical_generation_cancel", 3, reason="memory_pressure"),
        memory_row("critical_full_unload", 4, trim_level="fullUnload"),
    ]


def app_row(
    generation_id: str,
    second: int,
    *,
    finish_reason: str = "eos",
    run_id: str = RUN_ID,
) -> dict:
    return {
        "schemaVersion": 8,
        "generationID": generation_id,
        "layer": "app",
        "recordedAt": f"2026-07-15T12:00:{second:02d}Z",
        "finishReason": finish_reason,
        "notes": {"benchRunID": run_id},
    }


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


class IOSSmokeAcceptanceTests(unittest.TestCase):

    def test_read_only_history_observation_is_bound_and_not_audio_acceptance(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            item = {"suggestedHumanReadableName": "history-transcript-observation_0_AAAA.json",
                    "exportedFileName": "value.json"}
            row = {"schemaVersion": 1, "runID": RUN_ID, "rowID": "generation-7",
                   "observedTranscript": "A retained fixture."}
            def check(items, observed):
                (root / "manifest.json").write_text(json.dumps([{"attachments": items}]))
                (root / "value.json").write_text(json.dumps(observed))
                return subprocess.run([sys.executable, str(CHECKER), str(root),
                    "--run-id", RUN_ID, "--history-row-id", "generation-7"],
                    capture_output=True, text=True)
            result = check([item], row)
            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads(result.stdout)
            self.assertEqual(report["status"], "observed")
            self.assertNotIn(row["observedTranscript"], result.stdout)
            for changes in ({"runID": "another-run"}, {"rowID": "generation-8"},
                            {"observedTranscript": None}, {"observedTranscript": ""}):
                self.assertNotEqual(check([item], row | changes).returncode, 0)
            self.assertNotEqual(check([], row).returncode, 0)
            self.assertNotEqual(check([item, item], row).returncode, 0)
            self.assertNotEqual(check([item | {"exportedFileName": "../value.json"}], row).returncode, 0)
            for malformed in ([], None, "private fixture", row | {"schemaVersion": True},
                              row | {"observedTranscript": "\ud800"}):
                result = check([item], malformed)
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn("Traceback", result.stderr)
                self.assertNotIn("private fixture", result.stderr)
            self.assertNotEqual(check([item], row | {"observedTranscript": "x" * (256 * 1024)}).returncode, 0)

    def test_history_observation_cli_rejects_unsafe_or_ambiguous_routes(self) -> None:
        for args in (
            ["macos", "smoke", "--scenario", "history-transcript", "--history-row-id", "generation-7"],
            ["ios", "smoke", "--scenario", "history-transcript"],
            ["ios", "smoke", "--history-row-id", "generation-7"],
            ["ios", "smoke", "--scenario", "history-transcript", "--history-row-id", "../private"],
        ):
            result = subprocess.run(["bash", str(ROOT / "scripts/ui_test.sh"), *args],
                                    capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn("xcodebuild completed", result.stderr)

    def run_checker(self, root: Path, run_id: str = RUN_ID) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(CHECKER), str(root), "--run-id", run_id],
            text=True,
            capture_output=True,
            check=False,
        )

    def make_valid_fixture(self, root: Path, *, duplicate_mirrors: bool = False) -> None:
        memory = valid_memory_rows()
        app = [
            app_row("user-cancelled-generation", 0, finish_reason="cancelled"),
            app_row("memory-cancelled-generation", 3, finish_reason="cancelled"),
            app_row("reused-generation", 8),
            app_row("unrelated-generation", 9, run_id="another-run"),
        ]
        write_jsonl(root / "pull" / RUN_ID / "memory-contexts.jsonl", memory)
        write_jsonl(root / "pull" / "app" / "generations.jsonl", app)
        if duplicate_mirrors:
            write_jsonl(root / "mirror" / RUN_ID / "memory-contexts.jsonl", memory)
            write_jsonl(root / "mirror" / "app" / "generations.jsonl", app)

    def test_accepts_identical_mirrors_and_proves_post_pressure_reuse(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.make_valid_fixture(root, duplicate_mirrors=True)
            completed = self.run_checker(root)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = json.loads(completed.stdout)
        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["memoryMirrorCount"], 2)
        self.assertEqual(result["appMirrorCount"], 2)
        self.assertEqual(result["cancellationReason"], "memory_pressure")
        self.assertEqual(result["trimLevel"], "fullUnload")
        self.assertEqual(result["cancelledGenerationCount"], 2)
        self.assertEqual(result["postPressureGenerationID"], "reused-generation")
        self.assertNotIn(directory, completed.stdout)

    def test_rejects_missing_duplicate_or_out_of_order_events(self) -> None:
        mutations = {
            "missing": lambda rows: rows.pop(1),
            "duplicate": lambda rows: rows.insert(2, dict(rows[1])),
            "out of order": lambda rows: rows.__setitem__(slice(1, 3), [rows[2], rows[1]]),
        }
        for label, mutate in mutations.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                self.make_valid_fixture(root)
                rows = valid_memory_rows()
                mutate(rows)
                write_jsonl(root / "pull" / RUN_ID / "memory-contexts.jsonl", rows)
                completed = self.run_checker(root)
                self.assertNotEqual(completed.returncode, 0)

    def test_scoped_collection_preserves_acceptance_without_historical_contamination(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.make_valid_fixture(root)
            before = self.run_checker(root / "pull")
            scoped = root / "pull" / RUN_ID
            (scoped / "app").mkdir()
            (root / "pull" / "app" / "generations.jsonl").rename(
                scoped / "app" / "generations.jsonl"
            )
            historical = root / "pull" / "old-run" / "app" / "generations.jsonl"
            historical.parent.mkdir(parents=True)
            historical.write_text("interrupted historical JSON", encoding="utf-8")
            after = self.run_checker(scoped)
            contaminated = self.run_checker(root / "pull")
        self.assertEqual(before.returncode, 0, before.stderr)
        self.assertEqual(after.returncode, 0, after.stderr)
        self.assertEqual(json.loads(before.stdout), json.loads(after.stdout))
        self.assertNotEqual(contaminated.returncode, 0)
        self.assertIn("invalid JSON", contaminated.stderr)

    def test_rejects_wrong_cancellation_reason_and_trim_level(self) -> None:
        for field, value in (("reason", "active_generation_sample"), ("trimLevel", "hardTrim")):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                self.make_valid_fixture(root)
                rows = valid_memory_rows()
                target = rows[2] if field == "reason" else rows[3]
                target[field] = value
                write_jsonl(root / "pull" / RUN_ID / "memory-contexts.jsonl", rows)
                completed = self.run_checker(root)
                self.assertNotEqual(completed.returncode, 0)

    def test_cancel_failed_is_suite_fatal(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.make_valid_fixture(root)
            rows = valid_memory_rows()
            rows.insert(3, memory_row("critical_generation_cancel_failed", 3))
            write_jsonl(root / "pull" / RUN_ID / "memory-contexts.jsonl", rows)
            completed = self.run_checker(root)
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("cancel_failed", completed.stderr)

    def test_rejects_divergent_memory_and_app_mirrors(self) -> None:
        for evidence in ("memory", "app"):
            with self.subTest(evidence=evidence), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                self.make_valid_fixture(root, duplicate_mirrors=True)
                if evidence == "memory":
                    rows = valid_memory_rows()
                    rows[0]["source"] = "divergent"
                    write_jsonl(root / "mirror" / RUN_ID / "memory-contexts.jsonl", rows)
                else:
                    write_jsonl(
                        root / "mirror" / "app" / "generations.jsonl",
                        [app_row("different-generation", 9)],
                    )
                completed = self.run_checker(root)
                self.assertNotEqual(completed.returncode, 0)
                self.assertIn("diverge", completed.stderr)

    def test_rejects_mixed_run_identity_in_run_scoped_memory_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.make_valid_fixture(root)
            rows = valid_memory_rows()
            rows[1]["runID"] = "another-run"
            write_jsonl(root / "pull" / RUN_ID / "memory-contexts.jsonl", rows)
            completed = self.run_checker(root)
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("mixes run identities", completed.stderr)

    def test_requires_successful_app_completion_after_full_unload(self) -> None:
        variants = {
            "only before": [
                app_row("user-cancel", 0, finish_reason="cancelled"),
                app_row("memory-cancel", 3, finish_reason="cancelled"),
            ],
            "failed after": [
                app_row("user-cancel", 0, finish_reason="cancelled"),
                app_row("memory-cancel", 3, finish_reason="cancelled"),
                app_row("failed-after", 8, finish_reason="failed"),
            ],
        }
        for label, rows in variants.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                self.make_valid_fixture(root)
                write_jsonl(root / "pull" / "app" / "generations.jsonl", rows)
                completed = self.run_checker(root)
                self.assertNotEqual(completed.returncode, 0)
                self.assertIn("after the critical full unload", completed.stderr)

    def test_requires_distinct_user_and_memory_cancellations(self) -> None:
        variants = {
            "missing user": [
                app_row("memory-cancel", 3, finish_reason="cancelled"),
                app_row("reused", 8),
            ],
            "missing memory": [
                app_row("user-cancel", 0, finish_reason="cancelled"),
                app_row("reused", 8),
            ],
            "duplicate memory": [
                app_row("user-cancel", 0, finish_reason="cancelled"),
                app_row("memory-cancel-1", 2, finish_reason="cancelled"),
                app_row("memory-cancel-2", 3, finish_reason="cancelled"),
                app_row("reused", 8),
            ],
        }
        for label, rows in variants.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                self.make_valid_fixture(root)
                write_jsonl(root / "pull" / "app" / "generations.jsonl", rows)
                completed = self.run_checker(root)
                self.assertNotEqual(completed.returncode, 0)
                self.assertIn("cancellation", completed.stderr)

    def test_errors_do_not_disclose_the_local_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            completed = self.run_checker(root)
        self.assertNotEqual(completed.returncode, 0)
        self.assertNotIn(directory, completed.stderr)


if __name__ == "__main__":
    unittest.main()
