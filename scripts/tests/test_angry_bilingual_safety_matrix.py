#!/usr/bin/env python3
from __future__ import annotations

import copy
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest


REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))

from angry_bilingual_safety_matrix import (  # noqa: E402
    CELL_ID,
    FIXED_SEEDS,
    SafetyMatrixError,
    build_plan,
    validate_observations,
)


def passing_observations(plan: dict) -> list[dict]:
    return [
        {
            "rowID": row["rowID"],
            "status": "passed",
            "durationSeconds": 2.5,
            "instructionLanguage": row["expectedInstructionLanguage"],
            "instructionDigest": row["expectedInstructionDigest"],
            "deliveryCellID": CELL_ID,
            "audioDigest": "a" * 64,
        }
        for row in plan["rows"]
    ]


class AngryBilingualSafetyMatrixTests(unittest.TestCase):
    def test_plan_is_complete_source_bound_and_privacy_safe(self) -> None:
        plan, texts = build_plan()
        self.assertEqual(plan["fixedSeeds"], list(FIXED_SEEDS))
        self.assertEqual(len(plan["rows"]), 36)
        self.assertEqual(len({row["rowID"] for row in plan["rows"]}), 36)
        self.assertEqual(
            {row["speakerID"] for row in plan["rows"] if row["case"] == "native-chinese"},
            {"vivian", "serena", "uncle_fu", "dylan", "eric"},
        )
        self.assertEqual(
            {row["seed"] for row in plan["rows"] if row["speakerID"] == "vivian"},
            set(FIXED_SEEDS),
        )
        serialized = json.dumps(plan, ensure_ascii=False)
        for text in texts.values():
            self.assertNotIn(text, serialized)
        self.assertNotIn(str(REPO), serialized)

    def test_exact_dual_match_and_fallback_expectations(self) -> None:
        plan, _ = build_plan()
        rows = plan["rows"]
        for row in rows:
            if row["case"] == "native-chinese":
                self.assertEqual(row["expectedInstructionLanguage"], "mandarin")
            else:
                self.assertEqual(row["expectedInstructionLanguage"], "english")
        aiden_chinese = next(
            row for row in rows
            if row["speakerID"] == "aiden" and row["outputLanguage"] == "chinese"
        )
        vivian_english = next(
            row for row in rows
            if row["speakerID"] == "vivian" and row["outputLanguage"] == "english"
        )
        self.assertNotEqual(
            aiden_chinese["expectedInstructionDigest"],
            vivian_english["expectedInstructionDigest"],
            "English output alone receives the existing diction reinforcement",
        )

    def test_complete_pass_is_accepted(self) -> None:
        plan, _ = build_plan()
        summary = validate_observations(plan, passing_observations(plan))
        self.assertEqual(summary["status"], "passed")
        self.assertEqual(summary["takeCount"], 36)
        self.assertEqual(summary["hardFailureCount"], 0)

    def test_any_hard_failure_blocks_without_retrying_or_dropping_the_row(self) -> None:
        plan, _ = build_plan()
        observations = passing_observations(plan)
        target = next(
            row for row in observations
            if "vivian__chinese__32060828" in row["rowID"]
        )
        target.clear()
        target.update({
            "rowID": next(
                row["rowID"] for row in plan["rows"]
                if "vivian__chinese__32060828" in row["rowID"]
            ),
            "status": "hard-failure",
            "exitCode": 1,
            "errorDigest": "b" * 64,
        })
        summary = validate_observations(plan, observations)
        self.assertEqual(summary["status"], "blocked")
        self.assertEqual(summary["hardFailureCount"], 1)
        self.assertIn("32060828", summary["blockingRows"][0]["rowID"])

    def test_missing_duplicate_and_receipt_mismatch_fail_closed(self) -> None:
        plan, _ = build_plan()
        observations = passing_observations(plan)
        with self.assertRaisesRegex(SafetyMatrixError, "coverage mismatch"):
            validate_observations(plan, observations[:-1])
        with self.assertRaisesRegex(SafetyMatrixError, "duplicate"):
            validate_observations(plan, observations + [copy.deepcopy(observations[0])])
        observations[0]["instructionLanguage"] = "english"
        with self.assertRaisesRegex(SafetyMatrixError, "instructionLanguage mismatch"):
            validate_observations(plan, observations)

    def test_unregistered_or_duplicated_speaker_metadata_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            resources = root / "Sources/Resources"
            config = root / "config"
            resources.mkdir(parents=True)
            config.mkdir()
            shutil.copy2(
                REPO / "Sources/Resources/qwenvoice_contract.json",
                resources / "qwenvoice_contract.json",
            )
            shutil.copy2(
                REPO / "config/delivery-evaluation-corpus.json",
                config / "delivery-evaluation-corpus.json",
            )
            contract_path = resources / "qwenvoice_contract.json"
            contract = json.loads(contract_path.read_text(encoding="utf-8"))
            contract["speakerMetadata"].pop("eric")
            contract_path.write_text(json.dumps(contract), encoding="utf-8")
            with self.assertRaisesRegex(SafetyMatrixError, "exactly one metadata"):
                build_plan(root)


if __name__ == "__main__":
    unittest.main()
