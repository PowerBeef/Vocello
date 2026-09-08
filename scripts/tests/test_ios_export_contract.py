"""Producer/consumer wiring for the iOS-only export purchase boundary.

Behavior/state tests execute in IOSExportPurchaseTests. These assertions catch
routes bypassing that tested policy, not payment success or device acceptance.
"""
import json
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[2]


class IOSExportContractTests(unittest.TestCase):
    def read(self, path):
        return (ROOT / path).read_text()

    def test_fixture_is_one_non_consumable_and_not_bundled_or_active_in_release(self):
        config = json.loads(self.read("Tests/Fixtures/VocelloExports.storekit"))
        self.assertEqual(len(config["products"]), 1)
        product = config["products"][0]
        self.assertEqual(product["type"], "NonConsumable")
        # Apple rejects hyphens even though they are valid in bundle IDs.
        self.assertRegex(product["productID"], r"\A[A-Za-z0-9_.]+\Z")
        policy = self.read("Sources/iOSSupport/Services/IOSExportAccessPolicy.swift")
        self.assertIn('static let productID = "' + product["productID"] + '"', policy)
        self.assertIn("TEST", product["localizations"][0]["displayName"])
        self.assertNotIn("VocelloExports.storekit", self.read("project.yml"))
        for scheme in (ROOT / "QwenVoice.xcodeproj/xcshareddata/xcschemes").glob("*.xcscheme"):
            self.assertNotIn("VocelloExports.storekit", scheme.read_text())

    def test_storekit_has_one_owner_and_no_persisted_paid_flag(self):
        client = self.read("Sources/iOS/Commerce/IOSStoreKitClient.swift")
        state = self.read("Sources/iOSSupport/Services/IOSExportPurchaseState.swift")
        self.assertIn("StoreKit.Transaction.currentEntitlements", client)
        self.assertIn("StoreKit.Transaction.updates", client)
        self.assertIn("case .verified(let transaction)", client)
        self.assertIn("transaction.productType == .nonConsumable", client)
        self.assertIn("transaction.revocationDate != nil", client)
        self.assertIn("await native.finish()", client)
        self.assertNotIn("UserDefaults", client + state)
        self.assertNotIn("RuntimeDebugGate", client + state)
        self.assertEqual(client.count("AppStore.sync()"), 1)
        self.assertEqual(state.count("try await client.sync()"), 1)

    def test_generated_exports_do_not_use_ungated_sharelinks_or_activity_controllers(self):
        paths = list((ROOT / "Sources/iOS").rglob("*.swift"))
        owners = [p.relative_to(ROOT).as_posix() for p in paths
                  if "UIActivityViewController(" in p.read_text()]
        self.assertEqual(owners, ["Sources/iOS/Commerce/IOSExportGate.swift"])
        self.assertFalse([str(p) for p in paths if "ShareLink(" in p.read_text()])
        for path in ["Sources/iOS/Sheets/IOSPlayerSheet.swift",
                     "Sources/iOS/Studio/IOSStudioInlinePlayerCard.swift",
                     "Sources/iOS/History/HistoryScreen.swift"]:
            text = self.read(path)
            self.assertIn(".iosExportPresentation(", text)
            self.assertIn("exportGate.share(", text)

    def test_automatic_exports_supply_actual_request_or_committed_history_mode(self):
        hooks = self.read("Sources/iOS/Studio/IOSSingleTakeGenerationExecutionHooks.swift")
        self.assertIn("generationMode: plan.request.mode.rawValue", hooks)
        long_form = self.read("Sources/iOS/Studio/IOSLongFormProject.swift")
        self.assertEqual(long_form.count("generationMode: saved.mode"), 2)
        destination = self.read("Sources/iOSSupport/Services/IOSSavedOutputsDestination.swift")
        self.assertLess(destination.index("guard IOSExportCommerce.shared.permits"),
                        destination.index("let source = URL"))
        self.assertNotIn("purchase()", destination)

    def test_player_provenance_survives_history_enrollment_and_studio_expansion(self):
        player = self.read("Sources/iOS/Sheets/IOSPlayerSheet.swift")
        self.assertIn("exportProvenance: IOSExportProvenance(generationMode: history.mode)", player)
        self.assertIn("voice.enrollmentMetadata?.generatedSourceMode", player)
        self.assertIn("?? .originalReference", player)
        self.assertIn('generatedSourceMode: "design"', self.read("Sources/iOS/IOSGenerationModeViews.swift"))
        self.assertIn("exportProvenance: IOSExportProvenance(generationMode: mode.rawValue)",
                      self.read("Sources/iOS/IOSStudioCanvas.swift"))

    def test_mac_and_cli_exports_remain_unrestricted(self):
        shared = self.read("Sources/SharedSupport/Views/GenerationHistoryEnqueueWarning.swift")
        self.assertRegex(shared, r"(?s)#else\s+ShareLink\(items: state.availableAudioURLs\)")
        for directory in ["Sources/VocelloCLI", "Sources/Views", "Sources/Services"]:
            for path in (ROOT / directory).rglob("*.swift"):
                self.assertNotIn("IOSExportCommerce", path.read_text())
        paths = self.read("Sources/iOSSupport/Services/AppPaths.swift")
        self.assertIn("sharedContainerDir ?? managedAppSupportDir", paths)
        self.assertNotIn(".documentDirectory", paths)

    def test_storage_failure_recovery_does_not_demand_payment(self):
        for path in ["Sources/iOS/History/HistoryScreen.swift",
                     "Sources/SharedSupport/Views/GenerationHistoryEnqueueWarning.swift"]:
            self.assertIn("_ in .recoveryRecord", self.read(path))
        for path in ["Sources/iOS/Sheets/IOSPlayerSheet.swift",
                     "Sources/iOS/Studio/IOSStudioInlinePlayerCard.swift",
                     "Sources/iOSSupport/Services/IOSSavedOutputsDestination.swift"]:
            self.assertNotIn(".recoveryRecord", self.read(path))

    def test_all_purchase_copy_uses_catalog_entries(self):
        text = self.read("Sources/iOS/Commerce/IOSCommercePresentationText.swift")
        strings = json.loads(self.read("Sources/Resources/Localizable.xcstrings"))["strings"]
        for key in re.findall(r'String\(localized: "([^"]+)"', text):
            self.assertIn(key, strings)
            self.assertIn("en", strings[key]["localizations"])


if __name__ == "__main__":
    unittest.main()
