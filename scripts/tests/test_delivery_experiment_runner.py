#!/usr/bin/env python3
"""Tests for the serial, resumable delivery experiment runner."""

from __future__ import annotations

import copy
import fcntl
import json
from pathlib import Path
import stat
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from delivery_experiment import EXPECTED_PRESETS, digest  # noqa: E402
from delivery_experiment_runner import (  # noqa: E402
    REPO,
    RunnerError,
    analyze_execution,
    classify_cli_failure,
    create_execution_plan,
    execution_verdict,
    run_execution_plan,
    summarize_screen,
    validate_execution_plan,
)


FAKE_BINARY = r'''#!/usr/bin/env python3
import hashlib
import json
import math
import os
from pathlib import Path
import struct
import sys
import wave

PRESETS = ("neutral", "happy", "sad", "angry", "fearful", "surprised", "calm", "whisper")
args = sys.argv[1:]
if args[0] == "deliveries":
    print(json.dumps([
        {"preset": preset, "instruction": f"Production {preset}.",
         "intensity": "normal" if preset in {"happy", "angry"} else "strong"}
        for preset in PRESETS
    ]))
    raise SystemExit(0)
if args[0] != "generate":
    raise SystemExit(2)
def value(flag):
    return args[args.index(flag) + 1]
out = Path(value("--out"))
out.parent.mkdir(parents=True, exist_ok=True)
with wave.open(str(out), "wb") as wav:
    wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(24000)
    samples = [int(8000 * math.sin(2 * math.pi * 180 * i / 24000)) for i in range(24000)]
    wav.writeframes(b"".join(struct.pack("<h", sample) for sample in samples))
instruction = value("--delivery").strip()
counter = Path(os.environ["FAKE_CALL_COUNTER"])
count = int(counter.read_text() or "0") if counter.exists() else 0
counter.write_text(str(count + 1))
print(json.dumps({
    "generationID": hashlib.sha256(out.name.encode()).hexdigest()[:32],
    "audioPath": str(out), "durationSeconds": 1.0, "wallSeconds": 0.1,
    "finishReason": "eos",
    "deliveryInstructionChars": len(instruction),
    "deliveryInstructionDigest": hashlib.sha256(instruction.encode()).hexdigest(),
}))
'''


class DeliveryExperimentRunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.binary = self.root / "vocello-fake"
        self.binary.write_text(FAKE_BINARY, encoding="utf-8")
        self.binary.chmod(self.binary.stat().st_mode | stat.S_IXUSR)
        self.counter = self.root / "calls.txt"
        self.previous_counter = __import__("os").environ.get("FAKE_CALL_COUNTER")
        __import__("os").environ["FAKE_CALL_COUNTER"] = str(self.counter)

    def tearDown(self) -> None:
        environment = __import__("os").environ
        if self.previous_counter is None:
            environment.pop("FAKE_CALL_COUNTER", None)
        else:
            environment["FAKE_CALL_COUNTER"] = self.previous_counter
        self.temporary.cleanup()

    def _single_row_plan(self) -> dict:
        plan = create_execution_plan(
            binary=self.binary, data_dir=None, split="development",
            arm="emotion-acoustic", instruction_language="english",
            variant="speed", sampling_combination="official-official", seeds=[32000007],
        )
        plan["rows"] = plan["rows"][:1]
        plan["planDigest"] = digest({
            key: value for key, value in plan.items()
            if key not in {"planDigest", "executionIdentity", "executionPlanDigest"}
        })
        plan["executionPlanDigest"] = digest({
            key: value for key, value in plan.items() if key != "executionPlanDigest"
        })
        return plan

    def test_plan_is_binary_bound_and_contains_cross_language_cells(self) -> None:
        plan = create_execution_plan(
            binary=self.binary, data_dir=None, split="development", arm="current",
            instruction_language="english", variant="speed",
            sampling_combination="balanced-matched", seeds=[32000003],
        )
        self.assertEqual(len(plan["rows"]), 13 * 8 * 3 * 3)
        self.assertEqual(validate_execution_plan(plan, self.binary), plan)
        changed = copy.deepcopy(plan)
        changed["rows"][0]["seed"] = 99
        with self.assertRaisesRegex(RunnerError, "digest mismatch"):
            validate_execution_plan(changed, self.binary)

    def test_development_screen_filters_exact_cells_and_factors(self) -> None:
        plan = create_execution_plan(
            binary=self.binary, data_dir=None, split="development", arm="current",
            instruction_language="english", variant="speed",
            sampling_combination="balanced-matched", seeds=[32000003],
            screen_label="prompt-screen-pilot",
            cells=(("aiden", "English"), ("vivian", "English")),
            presets=("happy", "angry"), lengths=("medium",),
            conditions=("neutral",),
        )
        self.assertEqual(len(plan["rows"]), 4)
        self.assertEqual(plan["screeningSelection"]["scope"], "screened-development")
        self.assertEqual(
            {(row["speakerID"], row["outputLanguage"]) for row in plan["rows"]},
            {("aiden", "English"), ("vivian", "English")},
        )
        self.assertEqual({row["preset"] for row in plan["rows"]}, {"happy", "angry"})
        self.assertEqual(validate_execution_plan(plan, self.binary), plan)

    def test_balanced_calibration_rotation_is_compact_and_covers_every_factor(self) -> None:
        cells = (
            ("aiden", "English"), ("ryan", "English"),
            ("vivian", "Chinese"), ("serena", "Chinese"),
            ("uncle_fu", "Chinese"), ("dylan", "Chinese"),
            ("eric", "Chinese"), ("ono_anna", "Japanese"),
        )
        plan = create_execution_plan(
            binary=self.binary, data_dir=None, split="calibration", arm="current",
            instruction_language="english", variant="speed",
            sampling_combination="official-official",
            seeds=[31000003, 31000004, 31000005, 31000006],
            screen_label="compact-listener-calibration", cells=cells,
            presets=tuple(EXPECTED_PRESETS), lengths=("short", "medium", "long"),
            conditions=("neutral",), balanced_script_rotation=True,
        )
        self.assertEqual(len(plan["rows"]), 64)
        self.assertEqual(len({row["speakerID"] for row in plan["rows"]}), 8)
        self.assertEqual({row["preset"] for row in plan["rows"]}, set(EXPECTED_PRESETS))
        self.assertEqual({row["script"]["length"] for row in plan["rows"]}, {"short", "medium", "long"})
        self.assertEqual(len({row["seed"] for row in plan["rows"]}), 4)
        for cell in cells:
            cell_rows = [
                row for row in plan["rows"]
                if (row["speakerID"], row["outputLanguage"]) == cell
            ]
            self.assertEqual(len({row["seed"] for row in cell_rows}), 1)
            self.assertEqual(len({row["script"]["scriptID"] for row in cell_rows}), 1)
        self.assertEqual(plan["screeningSelection"]["scope"], "screened-calibration")
        self.assertTrue(plan["screeningSelection"]["balancedScriptRotation"])
        self.assertTrue(plan["screeningSelection"]["balancedSeedRotation"])
        self.assertEqual(validate_execution_plan(plan, self.binary), plan)

    def test_screen_requires_label_and_cannot_partially_open_confirmation(self) -> None:
        common = dict(
            binary=self.binary, data_dir=None, arm="current",
            instruction_language="english", variant="speed",
            sampling_combination="official-official",
        )
        with self.assertRaisesRegex(RunnerError, "require --screen-label"):
            create_execution_plan(
                **common, split="development", seeds=[32000003],
                presets=("happy",),
            )
        with self.assertRaisesRegex(RunnerError, "untouched holdout"):
            create_execution_plan(
                **common, split="confirmation", seeds=[33000003],
                screen_label="forbidden", presets=("happy",),
            )

    def test_run_is_resumable_and_instruction_receipt_is_exact(self) -> None:
        plan = self._single_row_plan()
        run_dir = self.root / "run"
        first = run_execution_plan(
            plan=plan, binary=self.binary, data_dir=None, run_dir=run_dir
        )
        self.assertEqual(first["counts"]["complete"], 1)
        self.assertEqual(self.counter.read_text(), "2")
        second = run_execution_plan(
            plan=plan, binary=self.binary, data_dir=None, run_dir=run_dir
        )
        self.assertEqual(second["counts"]["complete"], 1)
        self.assertEqual(self.counter.read_text(), "2")
        take = next(iter(second["takes"].values()))
        self.assertEqual(take["status"], "complete")
        self.assertFalse(Path(take["audio"]).is_absolute())

    def test_retry_retains_the_failed_attempt(self) -> None:
        plan = self._single_row_plan()
        run_dir = self.root / "retry-run"
        first = run_execution_plan(
            plan=plan, binary=self.binary, data_dir=None, run_dir=run_dir,
            lock_root=self.root / "retry-lock",
        )
        take_id = next(iter(first["takes"]))
        first["takes"][take_id] = {
            "status": "failed", "returnCode": 1,
            "failureCategory": "audio-quality-rejected",
        }
        (run_dir / "execution-state.json").write_text(json.dumps(first), encoding="utf-8")
        retried = run_execution_plan(
            plan=plan, binary=self.binary, data_dir=None, run_dir=run_dir,
            retry_failures=True, lock_root=self.root / "retry-lock",
        )
        take = retried["takes"][take_id]
        self.assertEqual(take["status"], "complete")
        self.assertEqual(take["attempts"][0]["failureCategory"], "audio-quality-rejected")
        self.assertEqual(retried["counts"]["retryAttempts"], 1)
        self.assertEqual(retried["counts"]["historicalFailures"], 1)

    def test_generator_and_heavy_analyzer_share_one_fail_closed_lock(self) -> None:
        lock_root = self.root / "shared-lock"
        lock_root.mkdir()
        lock_path = lock_root / "delivery-analysis-supervisor.lock"
        with lock_path.open("a+b") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaisesRegex(RunnerError, "already active"):
                run_execution_plan(
                    plan=self._single_row_plan(), binary=self.binary,
                    data_dir=None, run_dir=self.root / "blocked-run",
                    lock_root=lock_root,
                )

    def test_paired_analyzer_emits_evaluator_compatible_rows(self) -> None:
        plan = self._single_row_plan()
        run_dir = self.root / "run"
        run_execution_plan(plan=plan, binary=self.binary, data_dir=None, run_dir=run_dir)
        report = analyze_execution(plan, run_dir)
        self.assertEqual(report["kind"], "paired-acoustic-delta")
        self.assertEqual(len(report["rows"]), 1)
        self.assertEqual(set(report["rows"][0]["features"]), set(report["featureNames"]))
        self.assertIn("deliveryVerdict", report["rows"][0])
        self.assertIn("derivedFeatures", report["rows"][0])
        self.assertEqual(report["rows"][0]["deliveryVerdict"]["deliveryID"], "neutral.strong")
        self.assertTrue((run_dir / "acoustic-layer.json").is_file())

    def test_generate_json_source_exposes_exact_receipt_fields(self) -> None:
        source = (REPO / "Sources/VocelloCLI/GenerateCommand.swift").read_text(encoding="utf-8")
        self.assertIn("let generationID: String", source)
        self.assertIn("let deliveryInstructionChars: Int?", source)
        self.assertIn("let deliveryInstructionDigest: String?", source)
        self.assertIn("payload.deliveryInstructionText", source)

    def test_execution_verdict_rejects_retained_or_blocked_failures(self) -> None:
        passed = execution_verdict({
            "counts": {"complete": 1, "failedOrBlocked": 0, "planned": 2}
        })
        self.assertEqual(passed["status"], "PASS")
        failed = execution_verdict({
            "counts": {"complete": 1, "failedOrBlocked": 1, "planned": 2}
        })
        self.assertEqual(failed["status"], "FAIL")
        self.assertIn("failed-or-blocked-rows", failed["failures"])
        empty = execution_verdict({
            "counts": {"complete": 0, "failedOrBlocked": 0, "planned": 2}
        })
        self.assertIn("no-complete-row", empty["failures"])

    def test_cli_failure_classification_is_allowlisted_and_redacted(self) -> None:
        self.assertEqual(
            classify_cli_failure("error: audio quality check rejected <redacted>/file.wav"),
            "audio-quality-rejected",
        )
        self.assertEqual(
            classify_cli_failure("an unfamiliar private diagnostic"),
            "unclassified-cli-error",
        )

    def test_screen_summary_requires_one_factor_and_keeps_failures_in_denominator(self) -> None:
        runs = {}
        for label, arm in (("baseline", "current"), ("candidate", "emotion-acoustic")):
            plan = create_execution_plan(
                binary=self.binary, data_dir=None, split="development", arm=arm,
                instruction_language="english", variant="speed",
                sampling_combination="official-official", seeds=[32000003],
                screen_label="prompt-screen", cells=(("aiden", "English"),),
                presets=("happy", "angry"), lengths=("medium",),
                conditions=("neutral",),
            )
            run_dir = self.root / label
            run_execution_plan(plan=plan, binary=self.binary, data_dir=None, run_dir=run_dir)
            analyze_execution(plan, run_dir)
            runs[label] = run_dir
        report = summarize_screen(runs, baseline_label="baseline")
        self.assertEqual(report["controlledFactor"], "arm")
        self.assertEqual(report["comparisonCellCount"], 2)
        self.assertFalse(report["promotionAuthority"])
        self.assertEqual(len(report["ranking"]), 2)
        paired = report["pairedComparisons"]["candidate"]["overall"]
        self.assertEqual(paired["cellCount"], 2)
        self.assertEqual(
            paired["improved"] + paired["regressed"]
            + paired["bothPassed"] + paired["bothFailed"],
            2,
        )
        self.assertGreaterEqual(paired["twoSidedExactP"], 0.0)
        self.assertLessEqual(paired["twoSidedExactP"], 1.0)


if __name__ == "__main__":
    unittest.main()
