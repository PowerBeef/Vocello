from __future__ import annotations

import copy
import base64
import importlib.util
import json
import hashlib
import pathlib
import struct
import tempfile
import unittest
from unittest import mock
import zlib
import wave


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
        self.assertEqual(first["schemaVersion"], 3)
        self.assertEqual(first["takeCount"], 201)
        self.assertLessEqual(first["takeCount"], self.contract["generationMatrix"]["maxRows"])

        resolved = audit.catalogs()
        by_mode: dict[str, list[dict]] = {}
        for row in first["takes"]:
            by_mode.setdefault(row["mode"], []).append(row)
            self.assertNotIn("searchToken", row)
            corpus = audit.load_json(ROOT / "config/ios-control-audit-corpus.json")
            self.assertEqual(row["script"], corpus["scripts"][row["language"]][row["length"]])

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
            self.assertTrue(all(row["warmState"] == "observed" for row in by_mode[mode][1:]))

    def test_search_tokens_are_source_bound_and_cross_run_disjoint(self) -> None:
        first = audit.generate_plan(self.contract, "a" * 64, schema_version=2)
        second = audit.generate_plan(self.contract, "b" * 64, schema_version=2)
        first_tokens = {row["searchToken"] for row in first["takes"]}
        second_tokens = {row["searchToken"] for row in second["takes"]}
        self.assertEqual(len(first_tokens), first["takeCount"])
        self.assertEqual(len(second_tokens), second["takeCount"])
        self.assertFalse(first_tokens & second_tokens)
        self.assertNotEqual(first["takes"][0]["script"], second["takes"][0]["script"])

    def test_schema_one_plan_remains_replayable_with_sequential_tokens(self) -> None:
        plan = audit.generate_plan(
            self.contract,
            self.source_identity,
            schema_version=1,
        )
        audit.validate_plan(self.contract, plan)
        base = self.contract["generationMatrix"]["searchTokenBase"]
        self.assertEqual(plan["schemaVersion"], 1)
        self.assertEqual(plan["takes"][0]["searchToken"], str(base))
        self.assertEqual(
            plan["takes"][-1]["searchToken"],
            str(base + plan["takeCount"] - 1),
        )

        historical = audit.generate_plan(
            self.contract,
            "32d406df2d2a8f5b237754ff906cf705a60543873a67d238af0748149169fc83",
            schema_version=1,
        )
        historical["contractDigest"] = next(iter(audit.LEGACY_PLAN_V1_CONTRACT_DIGESTS))
        seen_modes: set[str] = set()
        for row in historical["takes"]:
            if row["mode"] in seen_modes:
                row["warmState"] = "warm"
            else:
                seen_modes.add(row["mode"])
            row["rowDigest"] = audit.digest(
                {key: value for key, value in row.items() if key != "rowDigest"}
            )
        historical["planDigest"] = audit.digest(
            {key: value for key, value in historical.items() if key != "planDigest"}
        )
        self.assertIn(historical["planDigest"], audit.LEGACY_PLAN_V1_PLAN_DIGESTS)
        audit.validate_plan(self.contract, historical)

        historical["takes"][0]["scriptDigest"] = "0" * 64
        historical["takes"][0]["rowDigest"] = audit.digest(
            {
                key: value
                for key, value in historical["takes"][0].items()
                if key != "rowDigest"
            }
        )
        historical["planDigest"] = audit.digest(
            {key: value for key, value in historical.items() if key != "planDigest"}
        )
        with self.assertRaisesRegex(audit.AuditError, "deterministic source-bound plan"):
            audit.validate_plan(self.contract, historical)

    def test_original_numeric_dropout_is_preserved_as_exact_v2_regression(self) -> None:
        legacy = audit.load_json(audit.LEGACY_CONTRACT_PATH)
        self.assertEqual(audit.digest(legacy), audit.LEGACY_CONTRACT_DIGEST)
        plan = audit.generate_plan(legacy, "5a978f32c2bd62725784ab954ad903cd2fe1f0e84de28519c8b6ddaf34952397", schema_version=2)
        audit.validate_plan(self.contract, plan)
        self.assertEqual(plan["planDigest"], "668187234e95f732fdfe32c12605bdeb16d765e64400ec7dcb13f58471f9645e")
        row = next(row for row in plan["takes"] if row["takeID"] == "custom-005")
        self.assertEqual(row["scriptDigest"], "9b1afb9406b135f61cf312fa27314db98185a636cbfb3bba4673571b3cdbfa56")
        self.assertEqual(row["rowDigest"], "e611c724cd2bd83fde037627ac89d6e364ef1fd485c6b3146afaabb85b44f337")

    def test_retained_v2_v3_contract_cannot_authorize_rehashed_substitutions(self) -> None:
        legacy = audit.load_json(audit.LEGACY_CONTRACT_PATH)
        for version in (2, 3):
            plan = audit.generate_plan(legacy, "a" * 64, schema_version=version)
            audit.validate_plan(self.contract, plan)
            plan["takes"][0]["script"] += " altered"
            row = plan["takes"][0]
            row["scriptDigest"] = audit.hashlib.sha256(row["script"].encode()).hexdigest()
            row["rowDigest"] = audit.digest({k: v for k, v in row.items() if k != "rowDigest"})
            plan["planDigest"] = audit.digest({k: v for k, v in plan.items() if k != "planDigest"})
            with self.assertRaisesRegex(audit.AuditError, "deterministic source-bound plan"):
                audit.validate_plan(self.contract, plan)

    def test_historical_contract_corruption_fails_closed(self) -> None:
        legacy = audit.load_json(audit.LEGACY_CONTRACT_PATH)
        plan = audit.generate_plan(legacy, "a" * 64, schema_version=2)
        original_load = audit.load_json
        with mock.patch.object(audit, "load_json", side_effect=lambda path: (
            {**legacy, "tampered": True} if path == audit.LEGACY_CONTRACT_PATH else original_load(path)
        )):
            with self.assertRaisesRegex(audit.AuditError, "historical.*digest mismatch"):
                audit.validate_plan(self.contract, plan)

    def test_v3_source_changes_never_change_spoken_corpus(self) -> None:
        first = audit.generate_plan(self.contract, "a" * 64)
        second = audit.generate_plan(self.contract, "b" * 64)
        self.assertNotEqual(first["planDigest"], second["planDigest"])
        self.assertEqual(first["takes"], second["takes"])

    def test_corpus_matches_every_selectable_language(self) -> None:
        plan = audit.generate_plan(self.contract, self.source_identity)
        languages = set(audit.catalogs()["languages"])
        self.assertEqual({row["language"] for row in plan["takes"]}, languages)
        self.assertTrue(all(row["scriptDigest"] for row in plan["takes"]))

    def test_compressed_transport_round_trips_the_exact_plan(self) -> None:
        plan = audit.generate_plan(self.contract, self.source_identity)
        encoded = audit.encode_plan(self.contract, plan)
        compressed = base64.b64decode(encoded)
        decoded = json.loads(zlib.decompress(compressed, wbits=-zlib.MAX_WBITS))
        self.assertEqual(decoded, plan)
        self.assertLess(len(encoded), 64_000)

        with self.assertRaises(zlib.error):
            zlib.decompress(compressed)

    def test_plan_tamper_and_row_substitution_fail_closed(self) -> None:
        plan = audit.generate_plan(self.contract, self.source_identity)
        plan["takes"][0]["searchToken"] = "99999999"
        with self.assertRaises(audit.AuditError):
            audit.validate_plan(self.contract, plan)


class IOSControlAuditCompositionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.contract = audit.load_contract()
        self.source_identity = "b" * 64
        self.plan = audit.generate_plan(self.contract, self.source_identity, schema_version=2)
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

    def test_accessibility_scenario_requires_both_aggregate_observations(self) -> None:
        metadata = dict(self.metadata, controlAuditScenario="accessibility")
        root_tabs = self.observation("root-tabs")
        root_tabs["scenario"] = "accessibility"
        partial = audit.compose(self.contract, metadata, self.plan, [root_tabs])
        self.assertEqual(partial["result"], "failed")
        self.assertEqual(partial["counts"]["PASS"], 1)
        self.assertEqual(partial["counts"]["SKIPPED_AFTER_FAILURE"], 1)

        settings = self.observation("settings-preferences")
        settings["scenario"] = "accessibility"
        complete = audit.compose(
            self.contract, metadata, self.plan, [root_tabs, settings]
        )
        self.assertEqual(complete["result"], "passed")
        self.assertEqual(complete["counts"]["PASS"], 2)
        self.assertEqual(
            {row["scenario"] for row in complete["rows"]}, {"accessibility"}
        )

    def test_bootstrap_failure_is_run_level_infrastructure_evidence(self) -> None:
        bootstrap = {
            "status": "infrastructure_bootstrap_failure",
            "runID": self.metadata["runID"],
            "testCaseCount": 0,
            "xcodebuildLogSHA256": "1" * 64,
            "xcresultSummarySHA256": "2" * 64,
        }
        summary = audit.compose(
            self.contract, self.metadata, self.plan, [], bootstrap
        )
        self.assertEqual(summary["runClassification"], "INFRASTRUCTURE_FAIL")
        self.assertEqual(
            summary["infrastructureFailure"]["status"],
            "infrastructure_bootstrap_failure",
        )
        self.assertGreater(summary["counts"]["SKIPPED_AFTER_FAILURE"], 0)

    def test_bootstrap_failure_rejects_wrong_run_or_launched_observations(self) -> None:
        bootstrap = {
            "status": "infrastructure_bootstrap_failure",
            "runID": "different-run",
            "testCaseCount": 0,
        }
        with self.assertRaises(audit.AuditError):
            audit.compose(self.contract, self.metadata, self.plan, [], bootstrap)
        bootstrap["runID"] = self.metadata["runID"]
        with self.assertRaises(audit.AuditError):
            audit.compose(
                self.contract,
                self.metadata,
                self.plan,
                [self.observation("root-tabs")],
                bootstrap,
            )

    def test_external_notification_is_run_level_infrastructure_evidence(self) -> None:
        interruption = {
            "status": "infrastructure_external_interruption",
            "runID": self.metadata["runID"],
            "testCaseCount": 1,
            "notificationKind": "springboard_banner",
            "xcodebuildLogSHA256": "3" * 64,
            "xcresultSummarySHA256": "4" * 64,
        }
        summary = audit.compose(
            self.contract,
            self.metadata,
            self.plan,
            [],
            None,
            interruption,
        )
        self.assertEqual(summary["runClassification"], "INFRASTRUCTURE_FAIL")
        self.assertEqual(
            summary["infrastructureFailure"]["status"],
            "infrastructure_external_interruption",
        )
        self.assertEqual(
            summary["infrastructureFailure"]["notificationKind"],
            "springboard_banner",
        )

        failed = self.observation("root-tabs", "PRODUCT_FAIL")
        with self.assertRaisesRegex(audit.AuditError, "product or harness"):
            audit.compose(
                self.contract,
                self.metadata,
                self.plan,
                [failed],
                None,
                interruption,
            )

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

    def test_xcresult_suffixed_observation_attachment_is_collected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            attachment = root / "exported.txt"
            observation = self.observation("root-tabs")
            attachment.write_text(json.dumps(observation) + "\n", encoding="utf-8")
            manifest = root / "manifest.json"
            manifest.write_text(
                json.dumps(
                    [
                        {
                            "attachments": [
                                {
                                    "suggestedHumanReadableName": (
                                        "control-observations_0_"
                                        "CCE3DAAA-8AA7-47CF-86DC-2C474357FE4D.jsonl"
                                    ),
                                    "exportedFileName": attachment.name,
                                }
                            ]
                        }
                    ]
                ),
                encoding="utf-8",
            )
            output = root / "observations.jsonl"
            rows = audit.collect_observations(manifest, root, output)
            self.assertEqual(rows, [observation])
            self.assertEqual(audit._read_jsonl(output), [observation])

    def test_observation_collection_rejects_missing_or_unsafe_attachments(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            manifest = root / "manifest.json"
            manifest.write_text(json.dumps([{"attachments": []}]), encoding="utf-8")
            with self.assertRaises(audit.AuditError):
                audit.collect_observations(manifest, root, root / "output.jsonl")

            manifest.write_text(
                json.dumps(
                    [
                        {
                            "attachments": [
                                {
                                    "suggestedHumanReadableName": "control-observations.jsonl",
                                    "exportedFileName": "../escape.txt",
                                }
                            ]
                        }
                    ]
                ),
                encoding="utf-8",
            )
            with self.assertRaises(audit.AuditError):
                audit.collect_observations(manifest, root, root / "output.jsonl")

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
                "deliveryID": None,
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
        self.assertNotIn("receipt_delivery_mismatch", report["rows"][0]["issues"])

    def test_observed_rows_allow_real_cold_receipt_but_require_warm_coverage(self) -> None:
        takes = self.plan["takes"][1:3]
        self.assertTrue(all(take["mode"] == "custom" for take in takes))
        self.assertTrue(all(take["warmState"] == "observed" for take in takes))
        observations = []
        engine_rows = []
        for index, (take, warm_state) in enumerate(zip(takes, ("cold", "warm"))):
            generation_id = f"00000000-0000-4000-8000-{index + 10:012d}"
            observation = self.observation(f"generation:{take['takeID']}")
            observation.update(
                {
                    "scenario": "generation",
                    "takeID": take["takeID"],
                    "generationID": generation_id,
                    "seed": 28_400_099,
                    "mode": take["mode"],
                }
            )
            observations.append(observation)
            engine_rows.append(
                {
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
                        "seed": 28_400_099,
                        "warmState": warm_state,
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
            )
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            (root / "engine").mkdir()
            telemetry = root / "engine/generations.jsonl"
            telemetry.write_text(
                "\n".join(json.dumps(row) for row in engine_rows) + "\n",
                encoding="utf-8",
            )
            report = audit.validate_device_evidence(
                self.contract, self.plan, observations, root
            )
            self.assertEqual(report["result"], "passed")
            self.assertEqual(
                [row["observedWarmState"] for row in report["rows"]],
                ["cold", "warm"],
            )

            engine_rows[1]["requestReceipt"]["warmState"] = "cold"
            telemetry.write_text(
                "\n".join(json.dumps(row) for row in engine_rows) + "\n",
                encoding="utf-8",
            )
            report = audit.validate_device_evidence(
                self.contract, self.plan, observations, root
            )
        self.assertEqual(report["result"], "failed")
        self.assertTrue(
            all(
                "missing_observed_warm_coverage" in row["issues"]
                for row in report["rows"]
            )
        )


class IOSControlAuditIncrementalEvidenceTests(unittest.TestCase):
    setUp = IOSControlAuditCompositionTests.setUp
    observation = IOSControlAuditCompositionTests.observation
    def event(self, index: int, control: str, phase: str = "terminal", **fields) -> dict:
        return dict(self.observation(control), schemaVersion=2, sequence=index, phase=phase,
                    classification="PASS" if phase == "terminal" else "IN_PROGRESS", **fields)

    def shard_metadata(self) -> dict:
        return dict(self.metadata, controlAuditScenario="generation", controlObservationSchemaVersion=2,
                    controlTakeStart=0, controlTakeLimit=1)

    def completed_shard(self) -> list[dict]:
        take = self.plan["takes"][0]
        return [
            self.event(1, f"generation:{take['takeID']}", "request-prepared", takeID=take["takeID"]),
            self.event(2, f"generation:{take['takeID']}", "player-visible", takeID=take["takeID"]),
            self.event(3, f"generation:{take['takeID']}", takeID=take["takeID"]),
            self.event(4, "composer"), self.event(5, "history-rows"), self.event(6, "player-controls"),
            self.event(7, "audit-restoration", "restored"),
        ]

    def test_shard_pass_is_not_full_campaign_pass(self) -> None:
        summary = audit.compose(self.contract, self.shard_metadata(), self.plan, self.completed_shard())
        self.assertEqual(summary["shard"]["result"], "passed")
        self.assertEqual(summary["result"], "incomplete")
        self.assertEqual(summary["remainingTakeCount"], len(self.plan["takes"]) - 1)
        self.assertEqual(len(summary["rows"]), 4)

    def test_restoration_missing_cannot_qualify_shard(self) -> None:
        summary = audit.compose(self.contract, self.shard_metadata(), self.plan, self.completed_shard()[:-1])
        self.assertEqual(summary["shard"]["result"], "failed")
        self.assertFalse(summary["restorationObserved"])

    def test_stages_cannot_replace_missing_terminal_observation(self) -> None:
        rows = self.completed_shard()
        rows.pop(2)
        for i, row in enumerate(rows):
            row["sequence"] = i + 1
        summary = audit.compose(self.contract, self.shard_metadata(), self.plan, rows)
        self.assertEqual(summary["shard"]["result"], "failed")
        self.assertEqual(summary["counts"]["PASS"], 3)

    def test_out_of_shard_take_rejected(self) -> None:
        row = self.event(1, f"generation:{self.plan['takes'][1]['takeID']}")
        with self.assertRaisesRegex(audit.AuditError, "outside"):
            audit.compose(self.contract, self.shard_metadata(), self.plan, [row])

    def test_shard_bounds_fail_closed(self) -> None:
        for value in (0, -1, True, 202):
            with self.subTest(value=value), self.assertRaises(audit.AuditError):
                audit.generation_shard(dict(self.shard_metadata(), controlTakeLimit=value), self.plan)

    def test_stream_is_sorted_but_gaps_duplicates_and_cross_source_are_rejected(self) -> None:
        rows = self.completed_shard()
        self.assertEqual(audit.ordered_observations(list(reversed(rows))), rows)
        for bad in (rows[1:], rows + [rows[0]], [dict(rows[0], sourceIdentity="x")] + rows[1:]):
            with self.assertRaises(audit.AuditError):
                audit.ordered_observations(bad)

    def test_partial_collection_is_atomic_and_does_not_overwrite_prior_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            output = root / "out.jsonl"
            output.write_text("previous\n")
            (root / "first.txt").write_text(json.dumps(self.event(1, "root-tabs")))
            (root / "bad.txt").write_text("{broken")
            manifest = root / "manifest.json"
            manifest.write_text(json.dumps([{"attachments": [
                {"suggestedHumanReadableName": "control-observations.jsonl", "exportedFileName": name}
                for name in ("first.txt", "bad.txt")
            ]}]))
            with self.assertRaises(audit.AuditError):
                audit.collect_observations(manifest, root, output)
            self.assertEqual(output.read_text(), "previous\n")

    def test_missing_visible_selection_and_scrub_cannot_be_engine_pass(self) -> None:
        take = self.plan["takes"][0]
        row = self.event(1, f"generation:{take['takeID']}", takeID=take["takeID"],
                         generationID="00000000-0000-4000-8000-000000000001")
        with tempfile.TemporaryDirectory() as directory:
            report = audit.validate_device_evidence(self.contract, self.plan, [row], pathlib.Path(directory))
        self.assertIn("visible_language_mismatch", report["rows"][0]["issues"])
        self.assertIn("missing_paused_scrub_transition", report["rows"][0]["issues"])


class IOSControlAuditCorrelationV2Tests(unittest.TestCase):
    setUp = IOSControlAuditCompositionTests.setUp
    observation = IOSControlAuditCompositionTests.observation
    event = IOSControlAuditIncrementalEvidenceTests.event
    shard_metadata = IOSControlAuditIncrementalEvidenceTests.shard_metadata
    completed_shard = IOSControlAuditIncrementalEvidenceTests.completed_shard

    def proof(self, rows: list[dict], *, warm: str = "cold", quality: str = "pass", status: str = "PASS") -> dict:
        take = self.plan["takes"][0]
        rows[2].update(generationID="00000000-0000-4000-8000-000000000001")
        report = {"schemaVersion": 2, "runID": self.metadata["runID"], "sourceIdentity": self.source_identity,
                  "planDigest": self.plan["planDigest"], "observationDigest": audit.digest(rows),
                  "result": "passed" if status == "PASS" else "failed", "rows": [{
                      "takeID": take["takeID"], "generationID": rows[2]["generationID"],
                      "status": status, "issues": [] if status == "PASS" else ["missing_audio_artifact"],
                      "qualityVerdict": quality, "observedWarmState": warm}]}
        report["correlationDigest"] = audit.digest(report)
        return report

    def test_missing_correlation_fails_summary_and_shard_not_product(self) -> None:
        result = audit.compose(self.contract, dict(self.shard_metadata(), controlEvidenceVersion=2),
                               self.plan, self.completed_shard())
        self.assertEqual(result["result"], "failed")
        self.assertEqual(result["shard"]["result"], "failed")
        self.assertEqual(result["counts"]["HARNESS_FAIL"], 1)
        self.assertEqual(result["counts"]["PRODUCT_FAIL"], 0)

    def test_cold_shard_is_valid_but_campaign_warm_coverage_stays_pending(self) -> None:
        rows = self.completed_shard()
        proof = self.proof(rows)
        result = audit.compose(self.contract, dict(self.shard_metadata(), controlEvidenceVersion=2),
                               self.plan, rows, correlations=[proof])
        self.assertEqual(result["shard"]["result"], "passed")
        self.assertEqual(result["result"], "incomplete")
        self.assertTrue(all(row["status"] == "PENDING" for row in result["warmCoverage"]))
        self.assertFalse(result["promotionEligible"])

    def test_correlation_failure_overrides_ui_only_pass(self) -> None:
        rows = self.completed_shard()
        proof = self.proof(rows, status="HARNESS_FAIL")
        result = audit.compose(self.contract, dict(self.shard_metadata(), controlEvidenceVersion=2),
                               self.plan, rows, correlations=[proof])
        self.assertEqual(result["shard"]["result"], "failed")
        self.assertEqual(result["counts"]["HARNESS_FAIL"], 1)

    def test_warning_is_explicit_and_never_promotion_pass(self) -> None:
        rows = self.completed_shard()
        proof = self.proof(rows, quality="warning")
        result = audit.compose(self.contract, dict(self.shard_metadata(), controlEvidenceVersion=2),
                               self.plan, rows, correlations=[proof])
        self.assertEqual(result["shard"]["result"], "passedWithWarnings")
        self.assertEqual(result["qualityWarnings"], ["generation:custom-001"])
        self.assertFalse(result["promotionEligible"])

    def test_changed_observation_cross_run_or_corrupt_proof_is_rejected(self) -> None:
        rows = self.completed_shard()
        proof = self.proof(rows)
        for field, value in (("runID", "another-run"), ("sourceIdentity", "f" * 64),
                             ("observationDigest", "f" * 64), ("correlationDigest", "f" * 64)):
            with self.subTest(field=field), self.assertRaises(audit.AuditError):
                audit.compose(self.contract, dict(self.shard_metadata(), controlEvidenceVersion=2),
                              self.plan, rows, correlations=[dict(proof, **{field: value})])

    def test_warm_coverage_uses_receipt_and_final_campaign_cannot_hide_missing_modes(self) -> None:
        rows = self.completed_shard()
        proof = self.proof(rows, warm="warm")
        result = audit.compose(self.contract, dict(self.shard_metadata(), controlEvidenceVersion=2),
                               self.plan, rows, correlations=[proof])
        self.assertEqual(result["warmCoverage"][0]["status"], "PASS")
        metadata = dict(self.shard_metadata(), controlEvidenceVersion=2, controlTakeLimit=len(self.plan["takes"]))
        result = audit.compose(self.contract, metadata, self.plan, rows, correlations=[proof])
        self.assertEqual(result["result"], "failed")
        self.assertTrue(any(row["status"] == "FAIL" for row in result["warmCoverage"]))

    def test_generation_correlation_is_required_only_for_generation_workflow(self) -> None:
        contract = json.loads((ROOT / "config/orchestration-contract.json").read_text())
        workflows = contract["workflows"]
        self.assertIn("control-audit-device-correlation", workflows["ui-ios-control-audit-generation"]["requiredSteps"])
        self.assertNotIn("control-audit-device-correlation", workflows["ui-ios-control-audit"]["requiredSteps"])


class IOSControlAuditArtifactTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = pathlib.Path(self.temp.name)
        self.attachments = self.root / "attachments"
        self.diagnostics = self.root / "control-audit-diagnostics"
        self.attachments.mkdir()
        self.observation = {"takeID": "custom-001", "generationID": "00000000-0000-4000-8000-000000000001", "runID": "ios-xcui-control-audit-fixture"}
        def chunk(kind: bytes, data: bytes) -> bytes:
            return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
        self.png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 44, 44, 8, 6, 0, 0, 0)) + chunk(b"IDAT", zlib.compress((b"\0" + b"\xff" * 176) * 44)) + chunk(b"IEND", b"")
        self.manifest = [{"attachments": []}]
        for kind in ("request", "player", "controls"):
            filename = f"{kind}.png"
            (self.attachments / filename).write_bytes(self.png)
            self.manifest[0]["attachments"].append({"exportedFileName": filename, "suggestedHumanReadableName": f"generation-custom-001-{kind}_0_AAAAAAAA-0000-4000-8000-000000000001.png"})
        (self.attachments / "manifest.json").write_text(json.dumps(self.manifest))
        self.audio = self.diagnostics / self.observation["runID"] / "outputs" / f"{self.observation['generationID']}.wav"
        self.audio.parent.mkdir(parents=True)
        with wave.open(str(self.audio), "wb") as wav:
            wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(24000)
            wav.writeframes(b"\0\0" * 24000)
        self.terminal = {"notes": {"samplingWAVDigest": hashlib.sha256(self.audio.read_bytes()).hexdigest()}}

    def capture(self) -> list[dict]:
        return audit.generation_artifacts(self.attachments, self.diagnostics, self.observation, self.terminal)

    def test_real_png_and_wav_are_digest_bound_and_private_paths_absent(self) -> None:
        artifacts = self.capture()
        self.assertEqual(len(artifacts), 4)
        self.assertEqual(artifacts[-1]["durationSeconds"], 1)
        self.assertNotIn(str(self.root), json.dumps(artifacts))

    def test_missing_duplicate_corrupt_screenshots_fail_closed(self) -> None:
        for content in (b"", self.png[:-1], self.png[:35] + self.png[-12:]):
            with self.subTest(size=len(content)):
                (self.attachments / "player.png").write_bytes(content)
                with self.assertRaises(audit.AuditError): self.capture()
        (self.attachments / "player.png").write_bytes(self.png)
        self.manifest[0]["attachments"].append(self.manifest[0]["attachments"][0])
        (self.attachments / "manifest.json").write_text(json.dumps(self.manifest))
        with self.assertRaisesRegex(audit.AuditError, "duplicate"): self.capture()

    def test_changed_wav_and_cross_run_rejected(self) -> None:
        self.audio.write_bytes(self.audio.read_bytes() + b"drift")
        with self.assertRaisesRegex(audit.AuditError, "digest_mismatch"): self.capture()
        self.observation["runID"] = "other-run"
        with self.assertRaisesRegex(audit.AuditError, "missing_audio"): self.capture()

    def test_resume_requires_unchanged_artifact_bytes_and_correlated_report(self) -> None:
        proof = {"rows": [{"status": "PASS", "artifacts": self.capture()}]}
        proof["correlationDigest"] = audit.digest(proof)
        audit.verify_retained_artifacts(self.root, proof)
        self.audio.write_bytes(self.audio.read_bytes() + b"drift")
        with self.assertRaisesRegex(audit.AuditError, "digest mismatch"):
            audit.verify_retained_artifacts(self.root, proof)
        proof["rows"][0]["artifacts"].pop()
        with self.assertRaisesRegex(audit.AuditError, "corrupt retained"):
            audit.verify_retained_artifacts(self.root, proof)

    def test_missing_manifest_error_is_sanitized(self) -> None:
        (self.attachments / "manifest.json").unlink()
        with self.assertRaises(audit.AuditError) as caught: self.capture()
        self.assertNotIn(str(self.root), str(caught.exception))


class IOSControlAuditResumeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.contract = audit.load_contract()
        self.source_identity = "e" * 64
        self.plan = audit.generate_plan(self.contract, self.source_identity, schema_version=2)

    def _prepare(
        self,
        root: pathlib.Path,
        rows: list[dict],
        *,
        run_id: str = "ios-xcui-control-audit-resume-fixture",
        resume_run_ids: list[str] | None = None,
        prior_state: dict | None = None,
        correlation: dict | None = None,
        metadata: dict | None = None,
    ) -> dict:
        run_root = root / run_id
        run_root.mkdir()
        run = {
            "runID": run_id,
            "status": "failed",
            "treeFingerprint": self.source_identity,
            "controlAuditScenario": "generation",
        }
        run.update(metadata or {})
        if resume_run_ids is not None:
            run["resumeRunIDs"] = resume_run_ids
        (run_root / "run.json").write_text(json.dumps(run), encoding="utf-8")
        plan_text = json.dumps(self.plan)
        (run_root / "control-audit-plan.json").write_text(plan_text, encoding="utf-8")
        current_plan = root / "current-plan.json"
        current_plan.write_text(plan_text, encoding="utf-8")
        observations = run_root / "control-observations.jsonl"
        observations.write_text(
            "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8"
        )
        if any(row.get("classification") == "PASS" for row in rows):
            (run_root / "control-audit-generation-correlation.json").write_text(
                json.dumps(correlation or {"result": "passed"}), encoding="utf-8"
            )
        if prior_state is not None:
            (run_root / "control-resume-state.json").write_text(
                json.dumps(prior_state), encoding="utf-8"
            )
        return audit.prepare_resume(
            run_root / "run.json",
            run_root / "control-audit-plan.json",
            self.source_identity,
            current_plan,
            "generation",
            observations,
            run_root / "control-audit-generation-correlation.json",
            root / "resume-state.json",
            root / "prior-observations.jsonl",
        )

    def _row(self, run_id: str, index: int, classification: str) -> dict:
        take = self.plan["takes"][index]
        return {
            "schemaVersion": 1,
            "runID": run_id,
            "sourceIdentity": self.source_identity,
            "scenario": "generation",
            "controlID": f"generation:{take['takeID']}",
            "classification": classification,
        }

    def test_recorded_product_failure_resumes_at_first_unattempted_take(self) -> None:
        run_id = "ios-xcui-control-audit-recorded-failure"
        rows = [
            self._row(run_id, 0, "PASS"),
            self._row(run_id, 1, "PRODUCT_FAIL"),
        ]
        with tempfile.TemporaryDirectory() as directory:
            state = self._prepare(pathlib.Path(directory), rows, run_id=run_id)
        self.assertEqual(state["takeStart"], 2)

    def test_new_stream_refuses_resume_without_restoration_or_terminal_stage(self) -> None:
        run_id = "ios-xcui-control-audit-interrupted"
        rows = [dict(self._row(run_id, 0, "PASS"), schemaVersion=2, phase="terminal", sequence=1)]
        metadata = {"controlObservationSchemaVersion": 2, "controlTakeStart": 0, "controlTakeLimit": 1}
        with tempfile.TemporaryDirectory() as directory, self.assertRaisesRegex(audit.AuditError, "restoration"):
            self._prepare(pathlib.Path(directory), rows, run_id=run_id, metadata=metadata)

    def test_failed_finalization_at_clean_shard_boundary_never_skips_next_take(self) -> None:
        run_id = "ios-xcui-control-audit-clean-boundary"
        rows = [dict(self._row(run_id, 0, "PASS"), schemaVersion=2, phase="terminal", sequence=1)]
        rows.append(dict(rows[0], controlID="audit-restoration", classification="IN_PROGRESS", phase="restored", sequence=2))
        metadata = {"controlObservationSchemaVersion": 2, "controlTakeStart": 0, "controlTakeLimit": 1}
        with tempfile.TemporaryDirectory() as directory:
            state = self._prepare(pathlib.Path(directory), rows, run_id=run_id, metadata=metadata)
        self.assertEqual(state["takeStart"], 1)
        self.assertIsNone(state["skippedAfterFailure"])
        self.assertEqual(state["skippedAfterFailures"], [])

    def test_unobserved_failed_take_is_skipped_without_retry(self) -> None:
        run_id = "ios-xcui-control-audit-unobserved-failure"
        rows = [self._row(run_id, 0, "PASS")]
        with tempfile.TemporaryDirectory() as directory:
            state = self._prepare(pathlib.Path(directory), rows, run_id=run_id)
        self.assertEqual(state["takeStart"], 2)
        self.assertEqual(state["skippedAfterFailure"], "generation:custom-002")
        self.assertEqual(state["skippedAfterFailures"], ["generation:custom-002"])

    def test_version_one_skip_is_preserved_across_a_second_recorded_failure(self) -> None:
        run_id = "ios-xcui-control-audit-second-failure"
        rows = [
            self._row("ios-xcui-control-audit-first-failure", 0, "PASS"),
            self._row("ios-xcui-control-audit-first-failure", 1, "PRODUCT_FAIL"),
            self._row(run_id, 3, "PRODUCT_FAIL"),
        ]
        prior_state = {
            "schemaVersion": 1,
            "resumeRunIDs": ["ios-xcui-control-audit-first-failure"],
            "takeStart": 3,
            "representedTakeCount": 2,
            "skippedAfterFailure": "generation:custom-003",
        }
        with tempfile.TemporaryDirectory() as directory:
            state = self._prepare(
                pathlib.Path(directory),
                rows,
                run_id=run_id,
                resume_run_ids=["ios-xcui-control-audit-first-failure"],
                prior_state=prior_state,
            )
        self.assertEqual(state["takeStart"], 4)
        self.assertEqual(state["skippedAfterFailure"], None)
        self.assertEqual(state["skippedAfterFailures"], ["generation:custom-003"])


class IOSControlAuditHistoryOwnershipTests(unittest.TestCase):
    def setUp(self) -> None:
        self.contract = audit.load_contract()
        self.plan = audit.generate_plan(self.contract, "e" * 64)
        self.take = self.plan["takes"][0]
        self.observation = {
            "scriptDigest": self.take["scriptDigest"],
            "historyOwnership": {
                "schemaVersion": 1, "rowID": "generation-42",
                "beforeRowIDs": ["generation-41"],
                "afterRowIDs": ["generation-41", "generation-42"],
                "finalRowIDs": ["generation-41", "generation-42"],
                "transcriptMatched": True, "retainedAsSeedCarrier": True, "pinOwnedByAudit": False,
            },
        }

    def test_carrier_and_exact_deletion_preserve_identical_existing_text(self) -> None:
        audit.validate_history_ownership(self.take, self.observation)
        binding = self.observation["historyOwnership"]
        binding["retainedAsSeedCarrier"] = False
        binding["finalRowIDs"] = ["generation-41"]
        audit.validate_history_ownership(self.take, self.observation)

    def test_missing_or_ambiguous_ownership_fails_closed(self) -> None:
        mutations = [
            {"rowID": "generation-41"},  # preexisting matching speech
            {"afterRowIDs": ["generation-42"]},  # lost baseline
            {"afterRowIDs": ["generation-41", "generation-42", "generation-43"]},
            {"beforeRowIDs": ["generation-41", "generation-41"]},
            {"rowID": "unsaved-private-path"},
            {"transcriptMatched": False},
            {"retainedAsSeedCarrier": "true"},
            {"finalRowIDs": []},
            {"schemaVersion": 2},
            {"pinOwnedByAudit": "false"},
            {"unexpectedPrivateContent": "not permitted"},
        ]
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                observation = copy.deepcopy(self.observation)
                observation["historyOwnership"].update(mutation)
                with self.assertRaises(audit.AuditError):
                    audit.validate_history_ownership(self.take, observation)
        for observation in ({}, {**self.observation, "scriptDigest": "0" * 64}):
            with self.assertRaises(audit.AuditError):
                audit.validate_history_ownership(self.take, observation)

    def test_device_correlation_requires_ownership_before_reading_telemetry(self) -> None:
        observation = {"takeID": self.take["takeID"], "classification": "PASS",
                       "generationID": "00000000-0000-4000-8000-000000000001"}
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(audit.AuditError, "History ownership"):
                audit.validate_device_evidence(self.contract, self.plan, [observation], pathlib.Path(directory))

    def test_v3_resume_exact_binding_and_uint64_seed(self) -> None:
        helper = IOSControlAuditResumeTests()
        helper.setUp()
        helper.plan = self.plan
        run_id = "ios-xcui-control-audit-v3-resume"
        row = helper._row(run_id, 0, "PASS")
        row.update(self.observation)
        row.update(takeID=self.take["takeID"], mode=self.take["mode"],
                   seed=17323406037040967292, generationID="00000000-0000-4000-8000-000000000001")
        failure = helper._row(run_id, 1, "PRODUCT_FAIL")
        failure["takeID"] = self.plan["takes"][1]["takeID"]
        proof = {"result": "passed", "planDigest": self.plan["planDigest"], "rows": [{
            "takeID": row["takeID"], "generationID": row["generationID"], "status": "PASS",
            "historyOwnershipDigest": audit.digest(row["historyOwnership"]),
        }]}
        original_load = audit.load_json
        def load(path):
            return proof if path.name == "control-audit-generation-correlation.json" else original_load(path)
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(audit, "load_json", side_effect=load):
            state = helper._prepare(pathlib.Path(directory), [row, failure], run_id=run_id)
        self.assertEqual(state["takeStart"], 2)
        self.assertEqual(state["seedCarriers"][0]["rowID"], "generation-42")
        self.assertEqual(state["seedCarriers"][0]["seed"], 17323406037040967292)
        self.assertFalse(state["seedCarriers"][0]["pinOwnedByAudit"])
        for key, value in (("runID", "foreign-run"), ("sourceIdentity", "a" * 64),
                           ("seed", float(row["seed"])), ("generationID", "00000000-0000-4000-8000-000000000002")):
            bad = {**row, key: value}
            with self.subTest(key=key), tempfile.TemporaryDirectory() as directory, mock.patch.object(audit, "load_json", side_effect=load):
                with self.assertRaises(audit.AuditError):
                    helper._prepare(pathlib.Path(directory), [bad, failure], run_id=run_id)

    def test_v3_resume_refuses_zero_observations(self) -> None:
        helper = IOSControlAuditResumeTests()
        helper.setUp()
        helper.plan = self.plan
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(audit.AuditError, "zero-observation"):
                helper._prepare(pathlib.Path(directory), [])

    def test_v3_resume_uses_each_original_runs_correlation(self) -> None:
        helper = IOSControlAuditResumeTests()
        helper.setUp()
        helper.plan = self.plan
        first_id = "ios-xcui-control-audit-original"
        second_id = "ios-xcui-control-audit-next"
        first = {**helper._row(first_id, 0, "PASS"), **copy.deepcopy(self.observation),
                 "takeID": self.take["takeID"], "mode": self.take["mode"], "seed": 2**64 - 1,
                 "generationID": "00000000-0000-4000-8000-000000000001"}
        second = {**copy.deepcopy(first), **helper._row(second_id, 1, "PASS"),
                  "takeID": self.plan["takes"][1]["takeID"],
                  "scriptDigest": self.plan["takes"][1]["scriptDigest"],
                  "generationID": "00000000-0000-4000-8000-000000000002"}
        second["historyOwnership"].update(rowID="generation-43", afterRowIDs=["generation-41", "generation-43"],
                                          finalRowIDs=["generation-41"], retainedAsSeedCarrier=False)
        def proof(row):
            return {"result": "passed", "planDigest": self.plan["planDigest"], "rows": [{
                "takeID": row["takeID"], "generationID": row["generationID"], "status": "PASS",
                "historyOwnershipDigest": audit.digest(row["historyOwnership"]),
            }]}
        for corrupt in (False, True):
            with self.subTest(corrupt=corrupt), tempfile.TemporaryDirectory() as directory:
                root = pathlib.Path(directory)
                origin = root / first_id
                origin.mkdir()
                (origin / "run.json").write_text(json.dumps({"runID": first_id, "treeFingerprint": self.plan["sourceIdentity"]}))
                (origin / "control-audit-plan.json").write_text(json.dumps(self.plan))
                original_proof = proof(first)
                if corrupt:
                    original_proof["rows"][0]["historyOwnershipDigest"] = "0" * 64
                (origin / "control-audit-generation-correlation.json").write_text(json.dumps(original_proof))
                if corrupt:
                    with self.assertRaisesRegex(audit.AuditError, "exact correlated generation"):
                        helper._prepare(root, [first, second], run_id=second_id, resume_run_ids=[first_id], correlation=proof(second))
                else:
                    state = helper._prepare(root, [first, second], run_id=second_id, resume_run_ids=[first_id], correlation=proof(second))
                    self.assertEqual(state["seedCarriers"][0]["generationID"], first["generationID"])
                    self.assertEqual(state["seedCarriers"][0]["seed"], 2**64 - 1)


if __name__ == "__main__":
    unittest.main()
