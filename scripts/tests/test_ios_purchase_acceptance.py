import base64
import copy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ios_purchase_acceptance as subject


class PurchaseAcceptanceTests(unittest.TestCase):
    def test_runner_storage_and_required_steps_are_registered(self):
        root = Path(__file__).resolve().parents[2]
        from build_output_policy import HEAVY_LANE_IDS
        policy = json.loads((root / "config/build-output-policy.json").read_text())
        self.assertEqual(set(policy["heavyLanePreflight"]["lanes"]), HEAVY_LANE_IDS)
        self.assertIn("purchase", policy["childRetention"]["uiResults"]["lanes"])
        workflows = json.loads((root / "config/orchestration-contract.json").read_text())["workflows"]
        self.assertIn("purchase-validation", workflows["ui-ios-purchase"]["requiredSteps"])

    def setUp(self):
        self.result = dict(schemaVersion=1, runID="test-owned-run", fixtureSHA256="a" * 64,
                           environment="Xcode", phases=subject.PHASES, cleanup=True, complete=True)

    def line(self, result):
        return subject.PREFIX + base64.b64encode(json.dumps(result).encode()).decode()

    def test_complete_local_result_never_claims_live_acceptance(self):
        result = subject.collect(self.line(self.result), "test-owned-run", "a" * 64)
        self.assertFalse(result["liveAcceptance"])
        self.assertEqual(result["scope"], "physical-device-local-storekit-only")
        self.assertFalse(result["restorationVerified"])

    def test_current_results_require_individual_restoration_observations(self):
        for scenario in ("lifecycle", "exports"):
            exported = "restored" if scenario == "exports" else "notRequired"
            result = {**self.result, "schemaVersion": 5, "scenario": scenario,
                      "phases": (subject.EXPORT_PHASES_V5 if scenario == "exports"
                                 else subject.LIFECYCLE_PHASES_V5),
                      "restoration": {"transactionsCleared": True, "tab": "restored",
                                      "historyFilter": exported, "studio": exported,
                                      "appStopped": True}}
            accepted = subject.collect(self.line(result), "test-owned-run", "a" * 64,
                                       scenario, require_restoration=True)
            self.assertTrue(accepted["restorationVerified"])
            for field, invalid in [("tab", "skippedBackground"), ("tab", "baselineMissing"),
                                   ("tab", "notRequired"), ("tab", "failed"),
                                   ("historyFilter", "skippedBackground"), ("historyFilter", "failed"),
                                   ("studio", "skippedBackground"), ("studio", "failed"),
                                   ("studio", "notRequired" if scenario == "exports" else "restored"),
                                   ("transactionsCleared", False), ("appStopped", False),
                                   ("appStopped", 1)]:
                changed = copy.deepcopy(result)
                changed["restoration"][field] = invalid
                with self.subTest(scenario=scenario, field=field, invalid=invalid), self.assertRaises(ValueError):
                    # Even forged aggregate success cannot hide skipped restoration.
                    subject.collect(self.line(changed), "test-owned-run", "a" * 64, scenario, True)
            for invalid in [None, {}, {**result["restoration"], "privatePath": "forbidden"}]:
                changed = {**result, "restoration": invalid}
                with self.assertRaises(ValueError):
                    subject.collect(self.line(changed), "test-owned-run", "a" * 64, scenario, True)
            with self.assertRaises(ValueError):
                subject.collect(self.line({**result, "scenario": "other"}), "test-owned-run", "a" * 64,
                                scenario, True)

    def test_schema_five_requires_the_unverified_purchase_phases(self):
        # AUD-07: the unverified purchase sits between the refund and Ask to Buy.
        self.assertEqual(subject.LIFECYCLE_PHASES_V5[7:11],
                         ["revoked", "unverified_locked", "unverified_restored", "unverified_revoked"])
        for scenario, current, previous in [("lifecycle", subject.LIFECYCLE_PHASES_V5, subject.PHASES),
                                            ("exports", subject.EXPORT_PHASES_V5, subject.EXPORT_PHASES)]:
            exported = "restored" if scenario == "exports" else "notRequired"
            restoration = {"transactionsCleared": True, "tab": "restored", "historyFilter": exported,
                           "studio": exported, "appStopped": True}
            result = {**self.result, "schemaVersion": 5, "scenario": scenario, "phases": previous,
                      "restoration": restoration}
            with self.subTest(scenario=scenario), self.assertRaises(ValueError):
                subject.collect(self.line(result), "test-owned-run", "a" * 64, scenario, True)
            # A schema 4 run stays readable but no longer qualifies the current runner.
            legacy = {**result, "schemaVersion": 4}
            self.assertTrue(subject.collect(self.line(legacy), "test-owned-run", "a" * 64,
                                            scenario)["restorationVerified"])
            with self.subTest(scenario=scenario), self.assertRaises(ValueError):
                subject.collect(self.line(legacy), "test-owned-run", "a" * 64, scenario, True)
            self.assertTrue(subject.collect(self.line({**result, "phases": current}), "test-owned-run",
                                            "a" * 64, scenario, True)["restorationVerified"])

    def test_legacy_results_are_readable_but_cannot_qualify_current_runner(self):
        for scenario, schema, phases in [("lifecycle", 1, subject.PHASES),
                                         ("exports", 2, subject.LEGACY_EXPORT_PHASES)]:
            result = {**self.result, "schemaVersion": schema, "phases": phases}
            self.assertFalse(subject.collect(self.line(result), "test-owned-run", "a" * 64,
                                             scenario)["restorationVerified"])
            with self.assertRaises(ValueError):
                subject.collect(self.line(result), "test-owned-run", "a" * 64, scenario, True)
        # Schema 3 restored what it touched but never reached the Studio inline card.
        result = {**self.result, "schemaVersion": 3, "scenario": "exports",
                  "phases": subject.LEGACY_EXPORT_PHASES,
                  "restoration": {"transactionsCleared": True, "tab": "restored",
                                  "historyFilter": "restored", "appStopped": True}}
        self.assertTrue(subject.collect(self.line(result), "test-owned-run", "a" * 64,
                                        "exports")["restorationVerified"])
        for changed in [result, {**result, "phases": subject.EXPORT_PHASES}]:
            with self.assertRaises(ValueError):
                subject.collect(self.line(changed), "test-owned-run", "a" * 64, "exports", True)

    def test_producer_requires_explicit_restoration(self):
        # The runner's half (scripts/ui_test.sh passing --require-restoration to this
        # collector) is an exact check in scripts/repo_invariants.sh: the lane needs a phone.
        root = Path(__file__).resolve().parents[2]
        source = (root / "Tests/VocelloiOSUITests/VocelloiOSPurchaseUITests.swift").read_text()
        self.assertIn('"schemaVersion": 5', source)
        self.assertIn('"studio": restoration.studio.rawValue', source)
        self.assertIn('"restoration":', source)
        self.assertIn('let cleaned = restoration.complete', source)
        self.assertIn('restoration.tab = originalTab == nil ? .baselineMissing : .skippedBackground', source)
        self.assertIn('try selectHistoryFilter(originalHistoryFilter)', source)
        self.assertNotIn('selectHistoryFilter("All")', source)

    def test_missing_duplicate_and_corrupt_results_fail(self):
        for value in ["", self.line(self.result) * 2, subject.PREFIX + "AAAA"]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                subject.collect(value, "test-owned-run", "a" * 64)

    def test_exports_require_new_schema_every_route_and_explicit_scenario(self):
        result = {**self.result, "schemaVersion": 2, "phases": subject.LEGACY_EXPORT_PHASES}
        qualified = subject.collect(self.line(result), "test-owned-run", "a" * 64, "exports")
        self.assertFalse(qualified["offlineAcceptance"])
        self.assertFalse(qualified["liveAcceptance"])
        for scenario, changed in [("lifecycle", result), ("exports", self.result),
                                   ("exports", {**result, "phases": subject.LEGACY_EXPORT_PHASES[:-1]}),
                                   ("exports", {**result, "phases": subject.EXPORT_PHASES}),
                                   ("other", result)]:
            with self.subTest(scenario=scenario), self.assertRaises(ValueError):
                subject.collect(self.line(changed), "test-owned-run", "a" * 64, scenario)

    def test_failures_scope_identity_and_omissions_fail(self):
        for key, value in [("runID", "other"), ("fixtureSHA256", "b" * 64),
                           ("environment", "Sandbox"), ("environment", "Production"),
                           ("complete", False), ("cleanup", False), ("cleanup", 1),
                           ("schemaVersion", True), ("phases", subject.PHASES[:-1]),
                           ("phases", subject.PHASES[::-1]), ("privatePath", "not-allowed")]:
            result = copy.deepcopy(self.result)
            result[key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                subject.collect(self.line(result), "test-owned-run", "a" * 64)


if __name__ == "__main__":
    unittest.main()
