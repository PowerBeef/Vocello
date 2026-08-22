#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest


REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))

from custom_delivery_matrix import (  # noqa: E402
    MatrixError,
    adherence_outcomes,
    adherence_summary,
    compare_arms,
    exact_paired_binary_p,
    validate_complete_matrix,
    validate_sidecar,
    validate_unit_evidence,
    validate_unit_manifest,
)
from delivery_separability import records_from_sidecar  # noqa: E402


SPEAKERS = [{"id": "aiden"}, {"id": "vivian"}]
DELIVERIES = [
    {
        "id": "neutral.strong",
        "preset": "neutral",
        "instruction": "Speak steadily and neutrally.",
    },
    {
        "id": "happy.normal",
        "preset": "happy",
        "instruction": "Speak happily.",
    },
]


def row(speaker: str, seed: int, delivery: str, passed: bool = True) -> dict:
    preset, intensity = delivery.split(".")
    return {
        "speakerID": speaker,
        "seed": seed,
        "delivery": delivery,
        "generationID": f"{speaker}-{seed}-{delivery}",
        "neutralReferenceAccepted": True,
        "neutralReferenceQualityFlags": [],
        "profileDigest": "a" * 64,
        "deliveryMetrics": {"analyzerAlgorithmVersion": 3, "durationSec": 2.0},
        "neutralMetrics": {"analyzerAlgorithmVersion": 3, "durationSec": 2.1},
        "deliveryGate": {
            "preset": preset,
            "intensity": intensity,
            "passed": passed,
            "flags": [] if passed else ["wrong_direction"],
            "metrics": {"pitch_shift_semitones": 1.0},
        },
    }


def failure(speaker: str, seed: int, delivery: dict, index: int = 4) -> dict:
    return {
        "takeIndex": index,
        "generationID": f"failure-{speaker}-{seed}-{delivery['id']}",
        "cell": f"custom/pro_custom_speed/medium/warm#delivery-{delivery['id']}",
        "mode": "custom",
        "modelID": "pro_custom_speed",
        "variant": "speed",
        "length": "medium",
        "warmState": "warm",
        "repetition": 0,
        "delivery": delivery["id"],
        "deliveryInstructionDigest": hashlib.sha256(
            delivery["instruction"].encode("utf-8")
        ).hexdigest(),
        "reasonCode": "fast_qc_dropout",
        "qualityFlags": ["dropout:1500ms"],
        "errorDigest": "b" * 64,
        "rejectedOutputFileName": f"rejected_delivery_{delivery['id']}_attempt{index}.wav",
        "rejectedAnalysis": {
            "deliveryID": delivery["id"],
            "instructionDigest": hashlib.sha256(
                delivery["instruction"].encode("utf-8")
            ).hexdigest(),
            "neutralReferenceAccepted": True,
            "neutralReferenceQualityFlags": [],
            "deliveryMetrics": {"analyzerAlgorithmVersion": 3, "durationSec": 2.0},
            "neutralMetrics": {"analyzerAlgorithmVersion": 3, "durationSec": 2.1},
            "deliveryGate": {"passed": False, "metrics": {"pitch_shift_semitones": 0.0}},
        },
        "speakerID": speaker,
        "seed": seed,
    }


def manifest(speaker: str, seed: int, failed_delivery: dict | None = None) -> dict:
    takes = [
        {
            "takeIndex": 1,
            "generationID": f"{speaker}-{seed}-cold",
            "mode": "custom",
            "length": "medium",
            "warmState": "cold",
            "delivery": None,
        },
        {
            "takeIndex": 2,
            "generationID": f"{speaker}-{seed}-neutral-reference",
            "mode": "custom",
            "length": "medium",
            "warmState": "warm",
            "delivery": None,
        },
    ]
    failures = []
    index = 3
    for delivery in DELIVERIES:
        if failed_delivery == delivery:
            failed = failure(speaker, seed, delivery, index)
            failed.pop("speakerID")
            failed.pop("seed")
            failed.pop("rejectedAnalysis")
            failures.append(failed)
        else:
            takes.append({
                "takeIndex": index,
                "generationID": f"{speaker}-{seed}-{delivery['id']}",
                "mode": "custom",
                "length": "medium",
                "warmState": "warm",
                "delivery": delivery["id"],
                "deliveryInstruction": delivery["instruction"],
            })
        index += 1
    return {
        "schemaVersion": 1,
        "customSpeakerID": speaker,
        "seed": seed,
        "takes": takes,
        "referenceFailures": [],
        "deliveryFailures": failures,
    }


class CustomDeliveryMatrixTests(unittest.TestCase):
    def test_sidecar_accepts_a_valid_subset_but_rejects_duplicates(self) -> None:
        rows = [row("aiden", 7, DELIVERIES[0]["id"])]
        self.assertEqual(
            len(validate_sidecar(rows, speaker_id="aiden", seed=7, deliveries=DELIVERIES)),
            1,
        )
        duplicate = dict(rows[0])
        duplicate["generationID"] = "aiden-7-neutral-duplicate"
        with self.assertRaisesRegex(MatrixError, "duplicate delivery"):
            validate_sidecar(rows + [duplicate], speaker_id="aiden", seed=7, deliveries=DELIVERIES)

    def test_unit_evidence_requires_every_delivery_as_success_or_failure(self) -> None:
        rows = [row("aiden", 7, DELIVERIES[0]["id"])]
        failures = [failure("aiden", 7, DELIVERIES[1])]
        validated, retained, references = validate_unit_evidence(
            rows,
            failures,
            speaker_id="aiden",
            seed=7,
            deliveries=DELIVERIES,
        )
        self.assertEqual(len(validated), 1)
        self.assertEqual(retained[0]["reasonCode"], "fast_qc_dropout")
        self.assertEqual(references, [])
        with self.assertRaisesRegex(MatrixError, "coverage mismatch"):
            validate_unit_evidence(
                rows, [], speaker_id="aiden", seed=7, deliveries=DELIVERIES
            )

    def test_manifest_preserves_failed_cell_and_later_success(self) -> None:
        payload = manifest("aiden", 7, failed_delivery=DELIVERIES[0])
        failures, references = validate_unit_manifest(
            payload, speaker_id="aiden", seed=7, deliveries=DELIVERIES
        )
        self.assertEqual(references, [])
        self.assertEqual([entry["delivery"] for entry in failures], ["neutral.strong"])
        self.assertIn("happy.normal", [take.get("delivery") for take in payload["takes"]])
        payload["deliveryFailures"][0]["deliveryInstructionDigest"] = "0" * 64
        with self.assertRaisesRegex(MatrixError, "instruction digest mismatch"):
            validate_unit_manifest(
                payload, speaker_id="aiden", seed=7, deliveries=DELIVERIES
            )

    def test_manifest_preserves_failed_cold_reference_without_losing_warm_pair(self) -> None:
        payload = manifest("aiden", 7)
        cold = payload["takes"].pop(0)
        payload["referenceFailures"] = [{
            "takeIndex": cold["takeIndex"],
            "generationID": cold["generationID"],
            "cell": "custom/speed/medium/cold#0",
            "mode": "custom",
            "modelID": "pro_custom_speed",
            "variant": "speed",
            "length": "medium",
            "warmState": "cold",
            "repetition": 0,
            "reasonCode": "fast_qc_dropout",
            "qualityFlags": ["dropout:excess2(3/1)"],
            "errorDigest": "c" * 64,
            "rejectedOutputFileName": "rejected_reference_cold_attempt1.wav",
        }]
        failures, references = validate_unit_manifest(
            payload, speaker_id="aiden", seed=7, deliveries=DELIVERIES
        )
        self.assertEqual(failures, [])
        self.assertEqual(references[0]["warmState"], "cold")

    def test_sidecar_rejects_cross_speaker_or_nonfinite_output(self) -> None:
        rows = [row("aiden", 7, DELIVERIES[0]["id"])]
        rows[0]["speakerID"] = "vivian"
        with self.assertRaisesRegex(MatrixError, "speaker receipt"):
            validate_sidecar(rows, speaker_id="aiden", seed=7, deliveries=DELIVERIES)
        rows[0]["speakerID"] = "aiden"
        rows[0]["deliveryMetrics"]["durationSec"] = float("nan")
        with self.assertRaisesRegex(MatrixError, "non-finite"):
            validate_sidecar(rows, speaker_id="aiden", seed=7, deliveries=DELIVERIES)

    def test_complete_matrix_rejects_silent_unit_omission(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = []
            for speaker in SPEAKERS:
                unit = Path(directory, f"{speaker['id']}__7")
                unit.mkdir()
                rows = [row(speaker["id"], 7, delivery["id"]) for delivery in DELIVERIES]
                (unit / "bench-prosody.json").write_text(json.dumps(rows), encoding="utf-8")
                evidence = unit / "evidence.json"
                evidence.write_text(json.dumps({
                    "schemaVersion": 2,
                    "unit": f"{speaker['id']}__7",
                    "speakerID": speaker["id"],
                    "seed": 7,
                    "referenceFailures": [],
                    "deliveryFailures": [],
                }), encoding="utf-8")
                paths.append(evidence)
            all_rows, failures, references, units, sidecars = validate_complete_matrix(
                paths, SPEAKERS, DELIVERIES, [7]
            )
            self.assertEqual(len(all_rows), 4)
            self.assertEqual(failures, [])
            self.assertEqual(references, [])
            self.assertEqual(len(units), 2)
            self.assertEqual(len(sidecars), 2)
            with self.assertRaisesRegex(MatrixError, "coverage mismatch"):
                validate_complete_matrix(paths[:1], SPEAKERS, DELIVERIES, [7])

    def test_complete_matrix_rejects_unversioned_or_misplaced_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            unit = Path(directory, "aiden__7")
            unit.mkdir()
            (unit / "bench-prosody.json").write_text(
                json.dumps([row("aiden", 7, delivery["id"]) for delivery in DELIVERIES]),
                encoding="utf-8",
            )
            evidence = unit / "evidence.json"
            evidence.write_text(json.dumps({
                "unit": "aiden__7",
                "speakerID": "aiden",
                "seed": 7,
                "referenceFailures": [],
                "deliveryFailures": [],
            }), encoding="utf-8")
            with self.assertRaisesRegex(MatrixError, "invalid unit evidence schema"):
                validate_complete_matrix([evidence], [{"id": "aiden"}], DELIVERIES, [7])

    def test_adherence_counts_failures_instead_of_dropping_them(self) -> None:
        rows = [
            row("aiden", 7, "neutral.strong", True),
            row("aiden", 7, "happy.normal", False),
            row("vivian", 7, "neutral.strong", True),
            row("vivian", 7, "happy.normal", True),
        ]
        summary = adherence_summary(rows, SPEAKERS, DELIVERIES)
        self.assertEqual(summary["overall"]["passed"], 3)
        self.assertEqual(summary["overall"]["total"], 4)
        self.assertEqual(summary["byDelivery"]["happy.normal"]["flags"], {"wrong_direction": 1})

    def test_acoustic_adherence_separates_rejected_audio_from_product_failure(self) -> None:
        retained = failure("aiden", 7, DELIVERIES[1])
        retained["rejectedAnalysis"]["deliveryGate"]["passed"] = True
        retained["rejectedAnalysis"]["deliveryGate"]["flags"] = []
        product = adherence_outcomes([], [retained], include_rejected_audio=False)
        acoustic = adherence_outcomes([], [retained], include_rejected_audio=True)
        self.assertFalse(product[0]["deliveryGate"]["passed"])
        self.assertEqual(
            product[0]["deliveryGate"]["flags"],
            ["generation_failure:fast_qc_dropout"],
        )
        self.assertTrue(acoustic[0]["deliveryGate"]["passed"])

    def test_rejected_analysis_remains_usable_as_acoustic_evidence(self) -> None:
        retained = failure("aiden", 7, DELIVERIES[1])
        records = records_from_sidecar([{
            "speakerID": retained["speakerID"],
            "seed": retained["seed"],
            "generationID": retained["generationID"],
            "delivery": retained["delivery"],
            "deliveryGate": retained["rejectedAnalysis"]["deliveryGate"],
        }])
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["speakerID"], "aiden")
        self.assertEqual(records[0]["seed"], 7)
        self.assertEqual(records[0]["preset"], "happy")

    def test_exact_paired_binary_probability_is_two_sided(self) -> None:
        self.assertIsNone(exact_paired_binary_p(0, 0))
        self.assertEqual(exact_paired_binary_p(4, 0), 0.125)
        self.assertEqual(exact_paired_binary_p(3, 1), 0.625)

    def test_arm_comparison_is_paired_and_rejects_global_tradeoff(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            arms = []
            for name, instruction_set, happy_passed, uar in (
                ("baseline", "shipped", False, 0.4),
                ("candidate", "candidate-v2", True, 0.3),
            ):
                arm = root / name
                arm.mkdir()
                plan = {
                    "seeds": [7],
                    "speakers": SPEAKERS,
                    "deliveries": DELIVERIES,
                    "instructionSet": instruction_set,
                }
                (arm / "matrix-plan.json").write_text(json.dumps(plan), encoding="utf-8")
                for speaker in SPEAKERS:
                    unit = arm / "units" / f"{speaker['id']}__7"
                    unit.mkdir(parents=True)
                    rows = [
                        row(speaker["id"], 7, "neutral.strong", True),
                        row(speaker["id"], 7, "happy.normal", happy_passed),
                    ]
                    (unit / "bench-prosody.json").write_text(json.dumps(rows), encoding="utf-8")
                    (unit / "evidence.json").write_text(json.dumps({
                        "speakerID": speaker["id"],
                        "seed": 7,
                        "deliveryFailures": [],
                    }), encoding="utf-8")
                (arm / "custom-delivery-matrix-report.json").write_text(json.dumps({
                    "acousticAnalysis": {
                        "separabilityHeldOutSpeaker": {
                            "metrics": {"uar": uar},
                            "cells": {
                                "neutral": {"recall": 0.4},
                                "happy": {"recall": 0.4 if name == "baseline" else 0.5},
                            },
                        }
                    }
                }), encoding="utf-8")
                arms.append(arm)
            comparison = compare_arms(arms[0], arms[1])
            self.assertEqual(comparison["overall"]["acousticPassDelta"], 2)
            self.assertEqual(comparison["overall"]["heldSpeakerUARDelta"], -0.1)
            self.assertFalse(comparison["decision"]["promoteCandidateGlobally"])
            self.assertEqual(
                comparison["decision"]["eligibleForFreshHoldout"], ["happy.normal"]
            )


if __name__ == "__main__":
    unittest.main()
