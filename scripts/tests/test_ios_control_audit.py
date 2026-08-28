from __future__ import annotations

import copy
import base64
import importlib.util
import json
import pathlib
import tempfile
import unittest
from unittest import mock
import zlib


ROOT = pathlib.Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "ios_control_audit", ROOT / "scripts/ios_control_audit.py"
)
assert SPEC and SPEC.loader
audit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit)


class IOSControlAuditContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.contract = audit.load_contract()
        self.source_identity = "a" * 64

    def test_repository_contract_is_source_and_test_bound(self) -> None:
        report = audit.validate_contract(self.contract)
        self.assertEqual(report["errors"], [])
        self.assertEqual(report["result"], "passed")
        self.assertGreaterEqual(report["interactiveOccurrenceCount"], 70)
        self.assertGreaterEqual(report["expandedControlCount"], 50)

    def test_new_interactive_source_fails_closed(self) -> None:
        hits = audit.interactive_sources()
        hits["Sources/iOS/NewUnownedControl.swift"] = [12]
        with mock.patch.object(audit, "interactive_sources", return_value=hits):
            report = audit.validate_contract(self.contract)
        self.assertTrue(
            any("NewUnownedControl.swift" in error for error in report["errors"])
        )

    def test_required_family_without_source_token_fails(self) -> None:
        contract = copy.deepcopy(self.contract)
        contract["controlFamilies"][0]["sourceToken"] = "definitely_missing_control_token"
        report = audit.validate_contract(contract)
        self.assertTrue(any("sourceToken does not resolve" in error for error in report["errors"]))

    def test_required_family_without_test_owner_fails(self) -> None:
        contract = copy.deepcopy(self.contract)
        duplicate = copy.deepcopy(contract["controlFamilies"][0])
        duplicate["id"] = "new-unowned-family"
        contract["controlFamilies"].append(duplicate)
        report = audit.validate_contract(contract)
        self.assertTrue(any("new-unowned-family" in error for error in report["errors"]))

    def test_pairwise_plan_is_deterministic_and_complete(self) -> None:
        first = audit.generate_plan(self.contract, self.source_identity)
        second = audit.generate_plan(self.contract, self.source_identity)
        self.assertEqual(first, second)
        self.assertEqual(first["takeCount"], 201)
        self.assertLessEqual(first["takeCount"], self.contract["generationMatrix"]["maxRows"])

        resolved = audit.catalogs()
        by_mode: dict[str, list[dict]] = {}
        for row in first["takes"]:
            by_mode.setdefault(row["mode"], []).append(row)
            self.assertEqual(len(row["searchToken"]), 8)
            self.assertIn(row["searchToken"], row["script"])

        for mode, mode_contract in self.contract["generationMatrix"]["modes"].items():
            dimensions = audit._expand_dimensions(mode_contract["dimensions"], resolved)
            expected = audit._pair_requirements(dimensions)
            actual = set()
            names = list(dimensions)
            for row in by_mode[mode]:
                actual.update(audit._row_pairs(row, names))
            self.assertEqual(expected - actual, set(), mode)
            for name, values in dimensions.items():
                self.assertEqual({row[name] for row in by_mode[mode]}, set(values))
            self.assertEqual(by_mode[mode][0]["warmState"], "cold")
            self.assertTrue(all(row["warmState"] == "warm" for row in by_mode[mode][1:]))

    def test_corpus_matches_every_selectable_language(self) -> None:
        plan = audit.generate_plan(self.contract, self.source_identity)
        languages = set(audit.catalogs()["languages"])
        self.assertEqual({row["language"] for row in plan["takes"]}, languages)
        self.assertTrue(all(row["scriptDigest"] for row in plan["takes"]))

    def test_compressed_transport_round_trips_the_exact_plan(self) -> None:
        plan = audit.generate_plan(self.contract, self.source_identity)
        encoded = audit.encode_plan(self.contract, plan)
        decoded = json.loads(zlib.decompress(base64.b64decode(encoded)))
        self.assertEqual(decoded, plan)
        self.assertLess(len(encoded), 64_000)

    def test_plan_tamper_and_row_substitution_fail_closed(self) -> None:
        plan = audit.generate_plan(self.contract, self.source_identity)
        plan["takes"][0]["searchToken"] = "99999999"
        with self.assertRaises(audit.AuditError):
            audit.validate_plan(self.contract, plan)


class IOSControlAuditCompositionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.contract = audit.load_contract()
        self.source_identity = "b" * 64
        self.plan = audit.generate_plan(self.contract, self.source_identity)
        self.metadata = {
            "runID": "ios-xcui-control-audit-fixture",
            "treeFingerprint": self.source_identity,
        }

    def observation(self, control_id: str, classification: str = "PASS") -> dict:
        return {
            "schemaVersion": 1,
            "runID": self.metadata["runID"],
            "sourceIdentity": self.source_identity,
            "scenario": "inventory",
            "controlID": control_id,
            "classification": classification,
            "expected": "expected",
            "actual": "actual",
        }

    def test_missing_rows_are_never_counted_as_pass(self) -> None:
        summary = audit.compose(
            self.contract, self.metadata, self.plan, [self.observation("root-tabs")]
        )
        self.assertEqual(summary["result"], "failed")
        self.assertEqual(summary["counts"]["PASS"], 1)
        self.assertGreater(summary["counts"]["SKIPPED_AFTER_FAILURE"], 0)

    def test_blocked_preservation_policy_is_retained(self) -> None:
        summary = audit.compose(
            self.contract,
            self.metadata,
            self.plan,
            [self.observation("history-surface", "BLOCKED_PRESERVATION_POLICY")],
        )
        self.assertEqual(summary["counts"]["BLOCKED_PRESERVATION_POLICY"], 1)
        self.assertEqual(summary["result"], "failed")

    def test_cross_run_and_cross_source_observations_fail_closed(self) -> None:
        wrong_run = self.observation("root-tabs")
        wrong_run["runID"] = "other"
        with self.assertRaises(audit.AuditError):
            audit.compose(self.contract, self.metadata, self.plan, [wrong_run])

        wrong_source = self.observation("root-tabs")
        wrong_source["sourceIdentity"] = "c" * 64
        with self.assertRaises(audit.AuditError):
            audit.compose(self.contract, self.metadata, self.plan, [wrong_source])

    def test_authenticated_resume_run_is_accepted_but_cannot_overwrite_a_take(self) -> None:
        metadata = dict(
            self.metadata,
            controlAuditScenario="generation",
            resumeRunIDs=["ios-xcui-control-audit-prior"],
        )
        first = self.plan["takes"][0]
        prior = self.observation(f"generation:{first['takeID']}")
        prior.update(
            {
                "runID": "ios-xcui-control-audit-prior",
                "scenario": "generation",
            }
        )
        summary = audit.compose(self.contract, metadata, self.plan, [prior])
        first_row = next(
            row for row in summary["rows"] if row["controlID"] == prior["controlID"]
        )
        self.assertEqual(first_row["classification"], "PASS")

        repeated = dict(prior, runID=self.metadata["runID"])
        with self.assertRaises(audit.AuditError):
            audit.compose(self.contract, metadata, self.plan, [prior, repeated])

    def test_unknown_classification_fails_closed(self) -> None:
        with self.assertRaises(audit.AuditError):
            audit.compose(
                self.contract,
                self.metadata,
                self.plan,
                [self.observation("root-tabs", "MAYBE")],
            )

    def test_plan_source_must_match_run_source(self) -> None:
        plan = copy.deepcopy(self.plan)
        plan["sourceIdentity"] = "d" * 64
        with self.assertRaises(audit.AuditError):
            audit.compose(self.contract, self.metadata, plan, [])

    def test_generation_summary_accounts_for_every_planned_take(self) -> None:
        metadata = dict(self.metadata, controlAuditScenario="generation")
        first = self.plan["takes"][0]
        observation = self.observation(f"generation:{first['takeID']}")
        observation["scenario"] = "generation"
        summary = audit.compose(self.contract, metadata, self.plan, [observation])
        generation_rows = [
            row for row in summary["rows"] if row["controlID"].startswith("generation:")
        ]
        self.assertEqual(len(generation_rows), self.plan["takeCount"])
        self.assertEqual(generation_rows[0]["classification"], "PASS")
        self.assertTrue(
            all(row["classification"] == "SKIPPED_AFTER_FAILURE" for row in generation_rows[1:])
        )

    def test_unknown_observation_control_fails_closed(self) -> None:
        with self.assertRaises(audit.AuditError):
            audit.compose(
                self.contract,
                self.metadata,
                self.plan,
                [self.observation("not-a-production-control")],
            )

    def test_device_correlation_rejects_receipt_drift(self) -> None:
        take = self.plan["takes"][0]
        generation_id = "00000000-0000-4000-8000-000000000001"
        observation = self.observation(f"generation:{take['takeID']}")
        observation.update(
            {
                "scenario": "generation",
                "takeID": take["takeID"],
                "generationID": generation_id,
                "seed": 28400099,
            }
        )
        row = {
            "schemaVersion": 9,
            "layer": "engine",
            "generationID": generation_id,
            "mode": take["mode"],
            "finishReason": "eos",
            "requestReceipt": {
                "retryAttempt": 0,
                "modelID": "pro_custom",
                "speakerID": take["speaker"],
                "deliveryID": f"{take['delivery']}.normal",
                "language": take["language"],
                "variation": take["variation"],
                "seed": 28400100,
                "warmState": take["warmState"],
                "streaming": True,
            },
            "stageMarks": [
                {"stage": "startup.first_decoded_audio_frame"},
                {"stage": "startup.first_published_stream_chunk"},
            ],
            "notes": {
                "promptDigest": take["scriptDigest"],
                "quality_registry_outcome": "pass",
            },
            "audioQC": {"verdict": "pass"},
        }
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            (root / "engine").mkdir()
            (root / "engine/generations.jsonl").write_text(json.dumps(row) + "\n")
            report = audit.validate_device_evidence(
                self.contract, self.plan, [observation], root
            )
        self.assertEqual(report["result"], "failed")
        self.assertIn("receipt_seed_mismatch", report["rows"][0]["issues"])


if __name__ == "__main__":
    unittest.main()
