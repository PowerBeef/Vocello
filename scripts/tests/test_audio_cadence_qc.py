#!/usr/bin/env python3
"""Tests for the privacy-safe Fast-QC cadence calibration contract."""

from __future__ import annotations

import hashlib
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from audio_cadence_qc import CadenceContractError, evaluate, load_contract  # noqa: E402


PRESETS = ("neutral", "happy", "sad", "angry", "fearful", "surprised", "calm", "whisper")
SPEAKERS = ("aiden", "ryan", "vivian", "serena", "uncle_fu", "ono_anna")
LANGUAGES = ("en", "zh", "ja", "ko")
LENGTHS = ("short", "medium", "long")
LABELS = ("acceptable", "unusual", "severe")


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def cadence(label: str) -> dict:
    classification = {
        "acceptable": "withinFastGate",
        "unusual": "unusual",
        "severe": "severe",
    }[label]
    pauses = {
        "acceptable": [120],
        "unusual": [420, 510],
        "severe": [950, 980],
    }[label]
    duration = 10_000
    cadence_total = sum(value for value in pauses if value >= 350)
    reasons = {
        "acceptable": [],
        "unusual": ["excess_cadence_pauses"],
        "severe": ["excess_cadence_pauses", "repeated_suspicious_pauses"],
    }[label]
    observed = sum(value >= 350 for value in pauses)
    expected = 1 if label != "severe" else 0
    return {
        "classification": classification,
        "reasons": reasons,
        "durationMS": duration,
        "expectedPauseCount": expected,
        "observedCadencePauseCount": observed,
        "excessCadencePauseCount": max(0, observed - expected),
        "suspiciousPauseCount": sum(value >= 900 for value in pauses),
        "recordedInteriorPausesMS": pauses,
        "totalInteriorSilenceMS": sum(pauses),
        "totalCadenceSilenceMS": cadence_total,
        "medianCadencePauseMS": sorted(pauses)[(len(pauses) - 1) // 2] if cadence_total else None,
        "p90CadencePauseMS": max(pauses) if cadence_total else None,
        "cadenceSilenceRatio": cadence_total / duration,
    }


def complete_fixture() -> dict:
    rows = []
    for split_index, split in enumerate(("calibration", "development", "confirmation")):
        for seed_index in range(8):
            for preset_index, preset in enumerate(PRESETS):
                identity = f"{split}-{seed_index}-{preset}"
                label = LABELS[(seed_index + preset_index) % len(LABELS)]
                rows.append({
                    "rowID": f"row-{identity}",
                    "runID": "cadence-fixture",
                    "generationID": f"generation-{identity}",
                    "audioDigest": digest(f"audio-{identity}"),
                    "requestReceiptDigest": digest(f"receipt-{identity}"),
                    "speakerID": SPEAKERS[(seed_index + preset_index) % len(SPEAKERS)],
                    "presetID": preset,
                    "outputLanguage": LANGUAGES[(seed_index + preset_index) % len(LANGUAGES)],
                    "scriptLength": LENGTHS[(seed_index + preset_index) % len(LENGTHS)],
                    "scriptGroupID": f"script-{split_index}-{seed_index}-{preset_index}",
                    "seed": 38_112_001 + seed_index,
                    "split": split,
                    "humanLabel": label,
                    "listenerCount": 3,
                    "labelAgreement": 1.0,
                    "cadence": cadence(label),
                })
    return {"schemaVersion": 1, "runID": "cadence-fixture", "rows": rows}


class AudioCadenceQCTests(unittest.TestCase):
    def test_contract_preserves_visible_warning_and_explicit_retry(self) -> None:
        contract = load_contract()
        self.assertEqual(contract["policy"]["unusual"], "publish-with-visible-review-notice")
        self.assertEqual(contract["policy"]["retry"], "explicit-user-controlled-visible-settings")
        self.assertFalse(contract["policy"]["automaticRetry"])
        self.assertFalse(contract["policy"]["seedMutation"])

    def test_complete_independent_holdout_is_ready_for_review(self) -> None:
        report = evaluate(complete_fixture())
        self.assertTrue(report["readyForThresholdReview"])
        self.assertEqual(report["confirmation"]["acceptableSevereFalseRejectRate"], 0.0)
        self.assertEqual(report["confirmation"]["severeRecall"], 1.0)
        self.assertFalse(report["semanticDeliveryAuthority"])

    def test_cross_run_identity_fails_closed(self) -> None:
        fixture = complete_fixture()
        fixture["rows"][0]["runID"] = "other-run"
        with self.assertRaisesRegex(CadenceContractError, "cross-run"):
            evaluate(fixture)

    def test_blocked_identity_cannot_leak_across_splits(self) -> None:
        fixture = complete_fixture()
        first = fixture["rows"][0]
        leaked = fixture["rows"][64]
        for field in ("speakerID", "scriptGroupID", "seed", "outputLanguage"):
            leaked[field] = first[field]
        with self.assertRaisesRegex(CadenceContractError, "leaks across splits"):
            evaluate(fixture)

    def test_privacy_forbidden_script_text_is_rejected(self) -> None:
        fixture = complete_fixture()
        fixture["rows"][0]["scriptText"] = "private words"
        with self.assertRaisesRegex(CadenceContractError, "privacy-forbidden"):
            evaluate(fixture)

    def test_inconsistent_bounded_pause_metrics_fail_closed(self) -> None:
        fixture = complete_fixture()
        fixture["rows"][0]["cadence"]["totalInteriorSilenceMS"] += 1
        with self.assertRaisesRegex(CadenceContractError, "disagrees with pauses"):
            evaluate(fixture)

    def test_acceptable_severe_false_reject_blocks_review(self) -> None:
        fixture = complete_fixture()
        row = next(
            value for value in fixture["rows"]
            if value["split"] == "confirmation" and value["humanLabel"] == "acceptable"
        )
        row["cadence"] = cadence("severe")
        report = evaluate(fixture)
        self.assertFalse(report["readyForThresholdReview"])
        self.assertIn("confirmation:acceptable-severe-false-reject-rate", report["failures"])

    def test_missing_language_coverage_remains_incomplete(self) -> None:
        fixture = complete_fixture()
        for row in fixture["rows"]:
            if row["split"] == "confirmation" and row["outputLanguage"] == "ko":
                row["outputLanguage"] = "en"
        report = evaluate(fixture)
        self.assertFalse(report["readyForThresholdReview"])
        self.assertIn("confirmation:insufficient-languages", report["failures"])


if __name__ == "__main__":
    unittest.main()
