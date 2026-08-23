#!/usr/bin/env python3
"""Pinned compact-model candidate contract tests."""

from __future__ import annotations

import copy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from prepare_delivery_compact_model_config import (  # noqa: E402
    PreparationError,
    validate_candidate_contract,
)


class PrepareDeliveryCompactModelConfigTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        root = Path(__file__).resolve().parents[2]
        cls.contract = json.loads(
            (root / "config/delivery-evaluator-v2-candidates.json").read_text(encoding="utf-8")
        )

    def test_tracked_candidate_contract_is_complete_and_research_only(self) -> None:
        self.assertIs(validate_candidate_contract(self.contract), self.contract)
        self.assertFalse(self.contract["normalCIPrerequisite"])
        self.assertFalse(self.contract["promotionAuthority"])

    def test_digest_runtime_and_adoption_drift_fail_closed(self) -> None:
        digest_drift = copy.deepcopy(self.contract)
        digest_drift["candidates"]["distilhubert"]["weightsSHA256"] = "0" * 63
        with self.assertRaisesRegex(PreparationError, "SHA-256"):
            validate_candidate_contract(digest_drift)
        runtime_drift = copy.deepcopy(self.contract)
        runtime_drift["candidates"]["distilhubert"]["runtimeDependencies"].pop("torch")
        with self.assertRaisesRegex(PreparationError, "dependency pins"):
            validate_candidate_contract(runtime_drift)
        gate_drift = copy.deepcopy(self.contract)
        gate_drift["adoptionRequirements"].remove("untouched-human-holdout-gain")
        with self.assertRaisesRegex(PreparationError, "adoption requirements"):
            validate_candidate_contract(gate_drift)


if __name__ == "__main__":
    unittest.main()
