import Foundation
import XCTest

/// Delivery-consistency diagnostic: N identical Custom-mode takes through the
/// production UI with the default Neutral delivery preset, so the cohort
/// measures exactly what a user hears when they generate with Neutral selected.
/// Diagnostic-only — the lane never publishes benchmark history.
///
/// WAVs are routed to the pullable caches diagnostics mirror via the production
/// `outputDirectory` preference (the shared-container outputs root is not
/// readable by `devicectl`); `scripts/ios_device.sh pull` retrieves them.
@MainActor
final class VocelloiOSDeliveryCohortUITests: VocelloiOSUITestCase {
    func testNeutralCustomDeliveryCohort() throws {
        let environment = ProcessInfo.processInfo.environment
        let runID = try XCTUnwrap(
            environment["QVOICE_IOS_COHORT_RUN_ID"].flatMap { $0.isEmpty ? nil : $0 },
            "Delivery cohort requires runner environment value QVOICE_IOS_COHORT_RUN_ID"
        )
        let text = try XCTUnwrap(
            environment["QVOICE_IOS_COHORT_TEXT"].flatMap { $0.isEmpty ? nil : $0 },
            "Delivery cohort requires runner environment value QVOICE_IOS_COHORT_TEXT"
        )
        let takes = try XCTUnwrap(
            Int(environment["QVOICE_IOS_COHORT_TAKES"] ?? ""),
            "Delivery cohort requires runner environment value QVOICE_IOS_COHORT_TAKES"
        )
        XCTAssertTrue((1...60).contains(takes), "QVOICE_IOS_COHORT_TAKES must be 1...60")

        beginSession(
            additionalEnvironment: ["QVOICE_IOS_DEVICE_RUN_ID": runID],
            additionalArguments: [
                "-outputDirectory",
                "~/Library/Caches/Vocello/diagnostics/\(runID)/outputs",
            ]
        )
        defer { endSession() }

        assertVisibleModelReadiness()
        let autoplayWasEnabled = ensureAutoplayEnabled()
        defer { restoreAutoplayPreference(originallyEnabled: autoplayWasEnabled) }

        prepare(mode: .custom)

        // The cohort is only meaningful against the shipped Neutral preset;
        // a fresh launch defaults to it, and the visible chip proves it.
        let deliveryChip = element("studioChip_delivery")
        XCTAssertTrue(VocelloUIWait.exists(deliveryChip, timeout: 20))
        XCTAssertTrue(
            VocelloUIWait.condition("delivery chip to show the Neutral preset", timeout: 15) {
                let value = (deliveryChip.value as? String) ?? ""
                return value.localizedCaseInsensitiveContains("Neutral")
                    || deliveryChip.label.localizedCaseInsensitiveContains("Neutral")
            }
        )

        for takeNumber in 1...takes {
            print("[ios-xcui-cohort] begin \(takeNumber)/\(takes)")
            XCTContext.runActivity(named: "Neutral take \(takeNumber)/\(takes)") { _ in
                replaceScript(with: text)
                let generationID = generateAndWaitForCompletedPlayer(timeout: 300)
                print("[ios-xcui-cohort] complete \(takeNumber)/\(takes) generationID=\(generationID)")
                dismissCompletedPlayerAndAssertGenerateReady()
            }
        }
        print("VOCELLO-COHORT-UI-MANIFEST ran=\(takes) runID=\(runID)")
    }
}
