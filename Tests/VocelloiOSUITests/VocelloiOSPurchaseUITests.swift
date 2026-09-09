import CryptoKit
import StoreKit
import StoreKitTest
import XCTest

/// Explicit opt-in, local Apple StoreKit service only. Never a live purchase lane.
/// One serial method owns the session and all its transactions; no app unlock hooks.
@MainActor
final class VocelloiOSPurchaseUITests: XCTestCase {
    private let app = XCUIApplication()
    private let productID = "com.patricedery.vocello.design_clone_export"
    private var phases: [String] = []
    private var historyRows: [String: String] = [:]
    private var originalHistoryFilter: String?

    func testLocalPurchaseLifecycle() async throws {
        continueAfterFailure = true // Throw on failure so cleanup always runs.
        let env = ProcessInfo.processInfo.environment
        let exportChecks = env["QVOICE_IOS_PURCHASE_SCENARIO"] == "exports"
        guard let runID = env["QVOICE_IOS_PURCHASE_RUN_ID"], !runID.isEmpty,
              let expectedDigest = env["QVOICE_IOS_PURCHASE_FIXTURE_SHA256"] else {
            throw XCTSkip("Requires explicit scripts/ui_test.sh ios purchase invocation")
        }
        let fixture = try XCTUnwrap(Bundle(for: Self.self).url(forResource: "VocelloExports", withExtension: "storekit"))
        let digest = SHA256.hash(data: try Data(contentsOf: fixture)).map { String(format: "%02x", $0) }.joined()
        XCTAssertEqual(digest, expectedDigest)
        guard digest == expectedDigest else { throw Failure.observation }
        let store = try SKTestSession(contentsOf: fixture)
        // Refuse to erase any prior local test session. This API never reads live purchases.
        guard store.allTransactions().isEmpty else { throw Failure.preexistingLocalTransactions }
        store.resetToDefaultState()
        store.disableDialogs = true
        store.storefront = "USA"
        store.locale = Locale(identifier: "en_US")
        var originalTab: String?
        var appLaunched = false
        var complete = false
        defer {
            var restoration = VocelloUIPurchaseRestoration()
            var transactionsDeleted = true
            // Only transactions created after the verified empty baseline are owned here.
            for transaction in store.allTransactions() {
                do { try store.deleteTransaction(identifier: transaction.identifier) }
                catch { transactionsDeleted = false }
            }
            store.resetToDefaultState()
            restoration.transactionsCleared = transactionsDeleted && store.allTransactions().isEmpty
            if appLaunched {
                restoration.tab = originalTab == nil ? .baselineMissing : .skippedBackground
            }
            if originalHistoryFilter != nil { restoration.historyFilter = .skippedBackground }
            // Do not bring Vocello over another app after an interruption. Preserve
            // the failed attempt and report exactly which restoration was skipped.
            if app.state == .runningForeground, let originalTab {
                restoration.tab = .failed
                if originalHistoryFilter != nil { restoration.historyFilter = .failed }
                var presentationRestored = false
                do {
                    if app.otherElements["ActivityListView"].exists { try dismissShareSheet() }
                    if element("exportPurchase_close").exists { try tap("exportPurchase_close") }
                    if element("iosPlayer_close").exists { try tap("iosPlayer_close") }
                    presentationRestored = true
                    if let originalHistoryFilter {
                        restoration.historyFilter = .failed
                        try tap("rootTab_history")
                        try selectHistoryFilter(originalHistoryFilter)
                        restoration.historyFilter = .restored
                    }
                } catch { /* Independent tab restoration must still be attempted. */ }
                do {
                    try tap(originalTab)
                    try require("original tab restored") { self.element(originalTab).isSelected }
                    if presentationRestored { restoration.tab = .restored }
                } catch { restoration.tab = .failed }
            }
            app.terminate()
            XCUIDevice.shared.press(.home)
            restoration.appStopped = app.state == .notRunning
            let cleaned = restoration.complete
            XCTAssertTrue(cleaned, "Local transaction/app cleanup must succeed")
            emit(["schemaVersion": 3, "scenario": exportChecks ? "exports" : "lifecycle",
                  "runID": runID, "fixtureSHA256": digest,
                  "environment": "Xcode", "phases": phases,
                  "restoration": ["transactionsCleared": restoration.transactionsCleared,
                                  "tab": restoration.tab.rawValue,
                                  "historyFilter": restoration.historyFilter.rawValue,
                                  "appStopped": restoration.appStopped],
                  "cleanup": cleaned, "complete": complete && cleaned])
        }

        // Native transaction provenance is checked before any app purchase control.
        let probe = try await store.buyProduct(identifier: productID)
        guard probe.environment == .xcode, probe.productID == productID else { throw Failure.notLocal }
        for transaction in store.allTransactions() { try store.deleteTransaction(identifier: transaction.identifier) }
        guard store.allTransactions().isEmpty else { throw Failure.observation }
        record("local_environment")

        // Process-local standard Apple locale arguments, not saved preferences.
        app.launchArguments = ["-AppleLanguages", "(en)", "-AppleLocale", "en_US"]
        appLaunched = true
        app.launch()
        VocelloUIFailureEvidence.observedApp = app
        try require("root tabs") { self.element("rootTab_settings").exists }
        originalTab = ["studio", "voices", "history", "settings"].map { "rootTab_\($0)" }
            .first { element($0).isSelected }
        guard originalTab != nil else { throw Failure.observation }
        try openPurchase()
        try locked()
        record("initial_locked")

        try tap("exportPurchase_restore")
        try notice("No export purchase was found")
        try locked()
        record("restore_not_owned")

        try await store.setSimulatedError(.generic(.userCancelled), forAPI: .purchase)
        try tap("exportPurchase_buy")
        try notice("Purchase cancelled")
        try locked()
        try await store.setSimulatedError(nil, forAPI: .purchase)
        let clearedError = await store.simulatedError(forAPI: .purchase)
        XCTAssertNil(clearedError, "Cancellation injection must be cleared before positive purchase")
        guard clearedError == nil else { throw Failure.observation }
        record("cancelled")

        // Keep the positive transaction independent of the fault-injection arm.
        // Read back the cleared error above, then reset Apple's other session options.
        store.resetToDefaultState()
        store.disableDialogs = true
        store.storefront = "USA"
        store.locale = Locale(identifier: "en_US")

        try tap("exportPurchase_buy")
        try unlocked()
        let purchased = try XCTUnwrap(store.allTransactions().first { $0.productIdentifier == productID && $0.state == .purchased })
        record("purchased")

        app.terminate()
        app.launch()
        try openPurchase()
        try unlocked()
        record("relaunch_entitlement")
        try tap("exportPurchase_restore")
        try notice("has been restored")
        try unlocked()
        record("restored")

        try store.refundTransaction(identifier: purchased.identifier)
        try locked()
        record("revoked")

        store.askToBuyEnabled = true
        try tap("exportPurchase_buy")
        try notice("Purchase pending approval")
        try locked()
        let pending = try XCTUnwrap(store.allTransactions().first { $0.pendingAskToBuyConfirmation })
        record("pending")
        try store.approveAskToBuyTransaction(identifier: pending.identifier)
        try unlocked()
        record("approved")
        if exportChecks {
            // Exercise Apple's fault injection, not a product override or global radio change.
            try await store.setSimulatedError(.generic(.networkError(URLError(.notConnectedToInternet))),
                                              forAPI: .loadProducts)
            app.terminate()
            app.launch()
            try openPurchase()
            try unlocked()
            try notice("Your export unlock is still active")
            XCTAssertFalse(element("exportPurchase_status").label.contains("Your audio stays in Vocello"))
            XCTAssertFalse(element("exportPurchase_reload").exists)
            record("owned_product_unavailable")
            try await store.setSimulatedError(nil, forAPI: .loadProducts)
            store.resetToDefaultState()
            store.disableDialogs = true
            store.storefront = "USA"
            store.locale = Locale(identifier: "en_US")
            try tap("exportPurchase_close")
            try checkHistoryExports(unlocked: true)

            try openPurchase()
            try store.refundTransaction(identifier: pending.identifier)
            try locked()
            try tap("exportPurchase_close")
            try checkHistoryExports(unlocked: false)
        }
        complete = true
    }

    /// Read-only existing History selection; never creates, pins, saves or deletes user clips.
    /// Each mode's exact row is retained for the revoked comparison. System sharing is cancelled.
    private func checkHistoryExports(unlocked: Bool) throws {
        try tap("rootTab_history")
        if originalHistoryFilter == nil {
            let selected = app.buttons.matching(NSPredicate(
                format: "identifier == %@ AND selected == true", "historyModeFilter"))
            try require("unique original History filter") { selected.count == 1 }
            let label = selected.firstMatch.label
            guard ["All", "Built-in", "Design", "Clone"].contains(label) else { throw Failure.observation }
            originalHistoryFilter = label
        }
        for (mode, label) in [("custom", "Built-in"), ("design", "Design"), ("clone", "Clone")] {
            try selectHistoryFilter(label)
            let row: XCUIElement
            if let id = historyRows[mode] {
                row = element(id)
            } else {
                row = app.buttons.matching(NSPredicate(format: "identifier BEGINSWITH %@", "historyRowTap_")).firstMatch
            }
            try require("existing \(mode) History row with visible provenance") {
                row.exists && row.isHittable && row.label.contains(label)
            }
            let id = row.identifier
            historyRows[mode] = id
            let suffix = String(id.dropFirst("historyRowTap_".count))
            try tap("historyRowMenu_\(suffix)")
            try tap("historyRowExport_\(suffix)")
            try checkExportPresentation(allowed: unlocked || mode == "custom")
            record("\(unlocked ? "owned" : "revoked")_\(mode)_history")

            try tap(id)
            let player = element("iosPlayer_playPause")
            try require("internal playback stays available") { player.isEnabled && player.label == "Pause" }
            try tap("iosPlayer_playPause")
            try require("playback paused") { player.label == "Play" }
            try tap("iosPlayer_download")
            try checkExportPresentation(allowed: unlocked || mode == "custom")
            try tap("iosPlayer_close")
            record("\(unlocked ? "owned" : "revoked")_\(mode)_player")
        }
        if let originalHistoryFilter { try selectHistoryFilter(originalHistoryFilter) }
    }

    private func selectHistoryFilter(_ label: String) throws {
        // Retained physical AX evidence: SwiftUI's container ID reaches each
        // button. Match the genuine English label as well, never the first ID match.
        let matches = app.buttons.matching(NSPredicate(
            format: "identifier == %@ AND label == %@", "historyModeFilter", label))
        try require("unique History filter") { matches.count == 1 && matches.firstMatch.isHittable }
        matches.firstMatch.tap()
        try require("selected History filter") { matches.firstMatch.isSelected }
    }

    private func checkExportPresentation(allowed: Bool) throws {
        if allowed {
            let close = app.buttons["header.closeButton"].firstMatch
            try require("system share sheet, no paywall") {
                close.exists && close.isHittable && !self.element("exportPurchase_close").exists
                    && self.app.otherElements["ActivityListView"].exists
            }
            try dismissShareSheet()
        } else {
            try locked()
            try tap("exportPurchase_close")
            try require("paywall dismissed") { !self.element("exportPurchase_close").exists }
        }
    }

    private func dismissShareSheet() throws {
        // UIKit's French system sheet retains this identifier even with English app text.
        try tap("header.closeButton")
        try require("system share dismissed") { !self.app.otherElements["ActivityListView"].exists }
    }

    private func element(_ id: String) -> XCUIElement { VocelloUIWait.element(app, id: id) }
    private func require(_ name: String, _ condition: @escaping () -> Bool) throws {
        guard VocelloUIWait.condition(name, timeout: 30, evaluate: condition) else { throw Failure.observation }
    }
    private func tap(_ id: String) throws {
        guard VocelloUIPrimaryAction.perform(on: element(id)) else { throw Failure.observation }
    }
    private func openPurchase() throws {
        try tap("rootTab_settings")
        for _ in 0..<3 {
            let ids = ["iosAttributionDetailBackButton", "iosSettings_voiceModelsBackButton", "iosSettings_openSourceBackButton"]
                + ["audio", "modelsFiles", "privacyPermissions", "accessibility", "about"].map { "iosSettings_\($0)BackButton" }
            guard let back = ids.map({ element($0) }).first(where: { $0.exists }) else { break }
            guard VocelloUISettingsReveal.perform(back, in: app, swipingUp: false),
                  VocelloUIPrimaryAction.perform(on: back), VocelloUIWait.disappears(back, timeout: 20) else {
                throw Failure.observation
            }
        }
        let row = element("iosSettings_exportPurchaseRow")
        guard VocelloUISettingsReveal.perform(row, in: app, swipingUp: true) else { throw Failure.observation }
        try tap("iosSettings_exportPurchaseRow")
        try require("purchase sheet loaded") {
            self.element("exportPurchase_unlocked").exists || self.element("exportPurchase_buy").exists
        }
    }
    private func locked() throws {
        try require("locked, local fixture price, idle") {
            let buy = self.element("exportPurchase_buy")
            // The live product is $19.99. Fail closed before Buy if app routing is not local.
            let digits = buy.label.filter(\.isNumber)
            return buy.exists && buy.isEnabled && digits == "099"
                && !self.element("exportPurchase_unlocked").exists
        }
    }
    private func unlocked() throws {
        try require("verified entitlement visible") {
            self.element("exportPurchase_unlocked").exists && !self.element("exportPurchase_buy").exists
        }
    }
    private func notice(_ text: String) throws {
        try require("purchase outcome: \(text)") {
            self.element("exportPurchase_status").label.contains(text)
                && !self.element("exportPurchase_progress").exists
        }
    }
    private func record(_ phase: String) {
        phases.append(phase)
        guard app.state == .runningForeground else { return }
        let attachment = XCTAttachment(screenshot: app.screenshot())
        attachment.name = "purchase-\(phase)"
        attachment.lifetime = .keepAlways
        add(attachment)
    }
    private func emit(_ evidence: [String: Any]) {
        do {
            let data = try JSONSerialization.data(withJSONObject: evidence, options: [.sortedKeys])
            let attachment = XCTAttachment(data: data, uniformTypeIdentifier: "public.json")
            attachment.name = "local-purchase-result"
            attachment.lifetime = .keepAlways
            add(attachment)
            print("VOCELLO_LOCAL_PURCHASE_RESULT=\(data.base64EncodedString())")
        } catch { XCTFail("Could not serialize purchase evidence") }
    }
    private enum Failure: Error { case observation, notLocal, preexistingLocalTransactions }
}
