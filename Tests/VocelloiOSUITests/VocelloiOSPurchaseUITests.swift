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
    /// What the exports scenario's own Studio take changed; nil once put back.
    private var studioBaseline: StudioBaseline?
    private var studioTouched = false

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
        var languageToRestore: String?
        var languageRestored = true
        var appLaunched = false
        var complete = false
        defer {
            var restoration = VocelloUIPurchaseRestoration()
            var transactionsDeleted = true
            // Only transactions created after the verified empty baseline are owned here.
            // Refund before deleting: an active purchase deleted unrefunded stayed entitled
            // in the app's StoreKit cache with an empty environment (October 13).
            for transaction in store.allTransactions()
            where transaction.state == .purchased && transaction.cancelDate == nil {
                do { try store.refundTransaction(identifier: transaction.identifier) }
                catch { transactionsDeleted = false }
            }
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
            if studioBaseline != nil { restoration.studio = .skippedBackground }
            else if studioTouched { restoration.studio = .restored }
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
                    // The brief panel and its keyboard cover the tab dock; restoreStudio
                    // rewrites whatever this commits.
                    if element("voiceBrief_editor").exists { try closeBriefPanel() }
                    presentationRestored = true
                    if let languageToRestore {
                        try selectInterfaceLanguage(languageToRestore)
                        languageRestored = true
                    }
                    if let originalHistoryFilter {
                        restoration.historyFilter = .failed
                        try tap("rootTab_history")
                        try selectHistoryFilter(originalHistoryFilter)
                        restoration.historyFilter = .restored
                    }
                } catch { /* Independent tab restoration must still be attempted. */ }
                if let studioBaseline {
                    restoration.studio = .failed
                    do {
                        try restoreStudio(studioBaseline)
                        restoration.studio = .restored
                    } catch { /* Reported as failed; the tab is still restored. */ }
                }
                do {
                    // A failed restore can leave the brief panel over the tab dock, where a
                    // dock query ends the runner before the result is emitted.
                    if element("voiceBrief_editor").exists { try closeBriefPanel() }
                    try tap(originalTab)
                    try require("original tab restored") { self.selected(self.element(originalTab)) }
                    if presentationRestored { restoration.tab = .restored }
                } catch { restoration.tab = .failed }
            }
            // Studio drafts save only when the scene leaves the foreground, so restored
            // ones are saved before the app stops; unrestored edits are dropped unsaved.
            if studioTouched, restoration.studio == .restored, app.state == .runningForeground {
                XCUIDevice.shared.press(.home)
                if !VocelloUIWait.condition("Vocello saves drafts in the background", timeout: 30, evaluate: {
                    self.app.state == .runningBackground || self.app.state == .runningBackgroundSuspended
                }) { restoration.studio = .failed }
            }
            app.terminate()
            XCUIDevice.shared.press(.home)
            restoration.appStopped = app.state == .notRunning
            let cleaned = restoration.complete && languageRestored
            let languageEvidence = XCTAttachment(string: "Interface language restored: \(languageRestored)")
            languageEvidence.name = "purchase-language-restoration"
            languageEvidence.lifetime = .keepAlways
            add(languageEvidence)
            XCTAssertTrue(cleaned, "Local transaction/app cleanup must succeed")
            emit(["schemaVersion": 4, "scenario": exportChecks ? "exports" : "lifecycle",
                  "runID": runID, "fixtureSHA256": digest,
                  "environment": "Xcode", "phases": phases,
                  "restoration": ["transactionsCleared": restoration.transactionsCleared,
                                  "tab": restoration.tab.rawValue,
                                  "historyFilter": restoration.historyFilter.rawValue,
                                  "studio": restoration.studio.rawValue,
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
        let observedLanguage = try currentInterfaceLanguage()
        languageToRestore = observedLanguage
        languageRestored = false
        let languageBaseline = XCTAttachment(string: "Original App Language: \(observedLanguage)")
        languageBaseline.name = "purchase-language-baseline"
        languageBaseline.lifetime = .keepAlways
        add(languageBaseline)
        try selectInterfaceLanguage("en")
        try openPurchase()
        try clearStaleEntitlementIfNeeded()
        try locked()
        record("initial_locked")

        try tap("exportPurchase_restore")
        try notice("No export purchase was found")
        try locked()
        record("restore_not_owned")

        // An injected purchase error reaches the app as StoreKitError.unknown on the
        // physical local StoreKit environment (observed 2026-09-24), whatever case the
        // runner injects, so this arm proves the failure path: the failure notice,
        // still locked, nothing finished. User cancellation (returned or thrown) is
        // proven by IOSExportPurchaseTests.
        try await store.setSimulatedError(.generic(.userCancelled), forAPI: .purchase)
        try tap("exportPurchase_buy")
        try notice("could not complete")
        try locked()
        XCTAssertTrue(store.allTransactions().isEmpty, "A failed purchase must leave no transaction")
        try await store.setSimulatedError(nil, forAPI: .purchase)
        let clearedError = await store.simulatedError(forAPI: .purchase)
        XCTAssertNil(clearedError, "Failure injection must be cleared before positive purchase")
        guard clearedError == nil else { throw Failure.observation }
        record("purchase_failed")

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
            // Offline as the app sees it, with the phone still connected to the Mac: every
            // network-backed StoreKit call it makes fails, and the verified entitlement comes
            // from the on-device cache. Apple's fault injection, not a product override or a
            // global radio change. The owned exports below all run offline.
            do {
                try await setStoreKitOffline(true, in: store)
                app.terminate()
                app.launch()
                try openPurchase()
                try unlocked()
                try notice("Your export unlock is still active")
                XCTAssertFalse(element("exportPurchase_status").label.contains("Your audio stays in Vocello"))
                XCTAssertFalse(element("exportPurchase_reload").exists)
                record("owned_offline_relaunch")
                try tap("exportPurchase_restore")
                try notice("could not complete")
                try unlocked()
                record("owned_offline_restore")
                try tap("exportPurchase_close")
                // The take comes first, so the History rows chosen below stay put for the
                // revoked comparison.
                try generateStudioDesignTake()
                try checkStudioInlineExport(allowed: true)
                record("owned_design_studio")
                try checkHistoryExports(unlocked: true)
                try await setStoreKitOffline(false, in: store)
            } catch {
                try? await setStoreKitOffline(false, in: store)
                throw error
            }
            store.resetToDefaultState()
            store.disableDialogs = true
            store.storefront = "USA"
            store.locale = Locale(identifier: "en_US")

            try openPurchase()
            try store.refundTransaction(identifier: pending.identifier)
            try locked()
            try tap("exportPurchase_close")
            try checkStudioInlineExport(allowed: false)
            record("revoked_design_studio")
            if let studioBaseline { try restoreStudio(studioBaseline) }
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
                row = try longestHistoryRow()
            }
            try require("existing \(mode) History row with visible provenance") {
                self.clearsDock(row) && row.label.contains(label)
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
            // Autoplay may already have finished a clip of about a second (observed
            // 2026-09-24), so playing or played-to-the-end both prove playback.
            try require("internal playback stays available") {
                player.exists && player.isEnabled && (player.label == "Pause" || player.label == "Play")
            }
            if player.label == "Pause" {
                try tap("iosPlayer_playPause")
                try require("playback paused") { player.exists && player.label == "Play" }
            }
            try tap("iosPlayer_download")
            try checkExportPresentation(allowed: unlocked || mode == "custom")
            try tap("iosPlayer_close")
            record("\(unlocked ? "owned" : "revoked")_\(mode)_player")
        }
        if let originalHistoryFilter { try selectHistoryFilter(originalHistoryFilter) }
    }

    /// Fails, or clears and reads back, every network-backed StoreKit call the app makes:
    /// product loading, purchase and App Store sync.
    private func setStoreKitOffline(_ offline: Bool, in store: SKTestSession) async throws {
        let error = StoreKitError.networkError(URLError(.notConnectedToInternet))
        try await store.setSimulatedError(offline ? .generic(error) : nil, forAPI: .loadProducts)
        try await store.setSimulatedError(offline ? .generic(error) : nil, forAPI: .purchase)
        try await store.setSimulatedError(offline ? .generic(error) : nil, forAPI: .appStoreSync)
        guard !offline else { return }
        let products = await store.simulatedError(forAPI: .loadProducts)
        let purchase = await store.simulatedError(forAPI: .purchase)
        let sync = await store.simulatedError(forAPI: .appStoreSync)
        guard products == nil, purchase == nil, sync == nil else { throw Failure.observation }
    }

    private struct StudioBaseline {
        let mode: String
        var brief: String?
        var script: String?
    }

    /// One short Design take for the Studio inline card, the only export surface with no
    /// History row to reuse. The take stays in History like any smoke take; Studio's
    /// mode, Design brief and Design script are put back by `restoreStudio`.
    private func generateStudioDesignTake() throws {
        try tap("rootTab_studio")
        let modes = ["custom", "design", "clone"]
        try require("Studio mode selector") { modes.contains { self.selected(self.element("generateSection_\($0)")) } }
        guard let mode = modes.first(where: { selected(element("generateSection_\($0)")) }) else {
            throw Failure.observation
        }
        studioBaseline = StudioBaseline(mode: mode)
        studioTouched = true
        if mode != "design" { try tap("generateSection_design") }
        try require("Design mode") {
            self.selected(self.element("generateSection_design")) && self.element("studioChip_voiceBrief").exists
        }
        try require("Design model installed") {
            self.element("textInput_textEditor").exists && !self.element("textInput_installModelButton").exists
        }
        studioBaseline?.script = (element("textInput_textEditor").value as? String) ?? ""
        try tap("studioChip_voiceBrief")
        try require("voice brief editor") { self.element("voiceBrief_editor").exists }
        studioBaseline?.brief = (element("voiceBrief_editor").value as? String) ?? ""
        try setBrief(VocelloUIBenchMatrix.voiceDesignBrief)
        try setScript("Vocello checks this export.")

        let generate = element("textInput_generateButton")
        let player = element("studio_inlinePlayer_playPause")
        let live = element("studio_livePreview_playPause")
        let error = element("textInput_generationError")
        // The app was relaunched, so no earlier take's card can satisfy the wait below.
        try require("Generate enabled, no card") {
            generate.exists && generate.isEnabled && !error.exists && !player.exists
        }
        try tap("textInput_generateButton")
        // The CTA is replaced, not disabled, when the take starts.
        try require("take started") { self.element("textInput_cancelButton").exists || live.exists || !generate.exists }
        guard VocelloUIWait.condition("Design take completes", timeout: 300, evaluate: {
            (player.exists && !live.exists) || error.exists
        }), !error.exists else { throw Failure.observation }
        if player.exists && player.label == "Pause" {
            try tap("studio_inlinePlayer_playPause")
            try require("take paused") { player.exists && player.label == "Play" }
        }
    }

    private func checkStudioInlineExport(allowed: Bool) throws {
        try tap("rootTab_studio")
        try require("completed Design take on the inline card") {
            self.selected(self.element("generateSection_design")) && self.element("studio_inlinePlayer_download").exists
        }
        try tap("studio_inlinePlayer_download")
        try checkExportPresentation(allowed: allowed)
    }

    /// Dismisses this test's take from the card (it stays in History), then puts back the
    /// Design script, the brief and the original mode, in that order.
    private func restoreStudio(_ baseline: StudioBaseline) throws {
        // A failure can leave the brief panel open over the tab dock.
        if element("voiceBrief_editor").exists { try closeBriefPanel() }
        try tap("rootTab_studio")
        if !selected(element("generateSection_design")) { try tap("generateSection_design") }
        // A take still running disables the setup chips.
        let cancel = element("textInput_cancelButton")
        if cancel.exists {
            try tap("textInput_cancelButton")
            try require("take cancelled") { !cancel.exists }
        }
        if element("studio_inlinePlayer_dismiss").exists {
            try tap("studio_inlinePlayer_dismiss")
            try tap("studio_inlinePlayer_dismissConfirm")
            try require("take dismissed") { !self.element("studio_inlinePlayer_playPause").exists }
        }
        if let script = baseline.script { try setScript(script) }
        if let brief = baseline.brief { try setBrief(brief) }
        try tap("generateSection_\(baseline.mode)")
        try require("original Studio mode") { self.selected(self.element("generateSection_\(baseline.mode)")) }
        studioBaseline = nil
    }

    /// The brief binding updates while editing, so it is observed before the panel closes;
    /// text the editor cannot reproduce (smart punctuation) fails rather than reads as restored.
    private func setBrief(_ text: String) throws {
        let editor = element("voiceBrief_editor")
        if !editor.exists { try tap("studioChip_voiceBrief") }
        try require("voice brief editor") { editor.exists }
        if ((editor.value as? String) ?? "") != text {
            guard VocelloUIPrimaryAction.perform(on: editor, timeout: 20) else { throw Failure.observation }
            // The tap leaves the caret at the start of an existing brief, where deletes remove
            // nothing (2026-10-16 physical run); a triple tap selects its paragraph instead.
            if !((editor.value as? String) ?? "").isEmpty {
                editor.tap(withNumberOfTaps: 3, numberOfTouches: 1)
                editor.typeText(XCUIKeyboardKey.delete.rawValue)
                try require("voice brief cleared") { editor.exists && ((editor.value as? String) ?? "").isEmpty }
            }
            if !text.isEmpty { editor.typeText(text) }
        }
        try require("voice brief entered") { editor.exists && ((editor.value as? String) ?? "") == text }
        try closeBriefPanel()
    }

    /// An empty brief disables Confirm, so the panel then closes with its drag-to-dismiss.
    private func closeBriefPanel() throws {
        let confirm = element("voiceBrief_confirm")
        guard confirm.exists else { throw Failure.observation }
        if confirm.isEnabled { try tap("voiceBrief_confirm") } else { confirm.swipeDown() }
        try require("voice brief closed") { !self.element("voiceBrief_editor").exists }
    }

    private func setScript(_ text: String) throws {
        let editor = element("textInput_textEditor")
        try require("script editor") { editor.exists }
        if ((editor.value as? String) ?? "") != text {
            let clear = element("textInput_clearButton")
            if clear.exists {
                try tap("textInput_clearButton")
                try require("script cleared") { !clear.exists }
            }
            if !text.isEmpty {
                guard VocelloUITextEntry.replace(in: editor, with: text, timeout: 20) else { throw Failure.observation }
            }
        }
        if app.keyboards.firstMatch.exists { editor.typeText("\n") }
        try require("script entered, keyboard closed") {
            ((editor.value as? String) ?? "") == text && !self.app.keyboards.firstMatch.exists
        }
    }

    /// The filtered list's longest visible row, so the player check sees real playback;
    /// row labels end with the clip duration (", 3.5s").
    private func longestHistoryRow() throws -> XCUIElement {
        let rows = app.buttons.matching(NSPredicate(format: "identifier BEGINSWITH %@", "historyRowTap_"))
        try require("History rows") { rows.firstMatch.exists }
        var best: (element: XCUIElement, seconds: Double)?
        for index in 0..<min(rows.count, 8) {
            let candidate = rows.element(boundBy: index)
            guard clearsDock(candidate) else { continue }
            let seconds = candidate.label.split(separator: ",").last
                .map { $0.trimmingCharacters(in: .whitespaces) }
                .flatMap { $0.hasSuffix("s") ? Double($0.dropLast()) : nil } ?? 0
            if best == nil || seconds > best!.seconds { best = (candidate, seconds) }
        }
        guard let best else { throw Failure.observation }
        return best.element
    }

    /// A row half under the tab dock reports hittable, yet its menu button misses the tap
    /// (2026-10-13 physical run: the row at y 845 of 874 pt never opened its menu).
    private func clearsDock(_ row: XCUIElement) -> Bool {
        guard row.exists, row.isHittable, let viewport = VocelloUISettingsReveal.viewport(in: app) else { return false }
        return viewport.contains(row.frame)
    }

    private func selectHistoryFilter(_ label: String) throws {
        // Retained physical AX evidence: SwiftUI's container ID reaches each
        // button. Match the genuine English label as well, never the first ID match.
        let matches = app.buttons.matching(NSPredicate(
            format: "identifier == %@ AND label == %@", "historyModeFilter", label))
        try require("unique History filter") { matches.count == 1 && matches.firstMatch.isHittable }
        matches.firstMatch.tap()
        try require("selected History filter") { self.selected(matches.firstMatch) }
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
    /// Waits read `label`, `isEnabled` and `isSelected` only once the element exists: on a
    /// missing element XCTest fails the query itself, which ended the runner before this
    /// test's cleanup (2026-10-13 physical run).
    private func selected(_ element: XCUIElement) -> Bool { element.exists && element.isSelected }
    private func require(_ name: String, _ condition: @escaping () -> Bool) throws {
        guard VocelloUIWait.condition(name, timeout: 30, evaluate: condition) else { throw Failure.observation }
    }
    private func tap(_ id: String) throws {
        guard VocelloUIPrimaryAction.perform(on: element(id)) else { throw Failure.observation }
    }
    private func openSettingsRoot() throws {
        try tap("rootTab_settings")
        for _ in 0..<3 {
            let ids = ["iosAttributionDetailBackButton", "iosSettings_voiceModelsBackButton", "iosSettings_openSourceBackButton"]
                + ["audio", "appLanguage", "modelsFiles", "privacyPermissions", "accessibility", "about"].map { "iosSettings_\($0)BackButton" }
            guard let back = ids.map({ element($0) }).first(where: { $0.exists }) else { break }
            guard VocelloUISettingsReveal.perform(back, in: app, swipingUp: false),
                  VocelloUIPrimaryAction.perform(on: back), VocelloUIWait.disappears(back, timeout: 20) else {
                throw Failure.observation
            }
        }
    }
    private let interfaceLanguages = ["system", "en", "fr", "es", "de", "it", "pt-BR", "zh-Hans", "ja", "ko", "ru"]
    private func currentInterfaceLanguage() throws -> String {
        try openSettingsRoot()
        let row = element("iosSettings_appLanguageRow")
        guard VocelloUISettingsReveal.perform(row, in: app, swipingUp: true, requirement: .navigation) else {
            throw Failure.observation
        }
        try tap("iosSettings_appLanguageRow")
        try require("interface language picker") { self.element("screen_settings_appLanguage").exists }
        let selected = interfaceLanguages.filter {
            let option = element("iosSettings_appLanguageOption_\($0)")
            return option.exists && option.isSelected
        }
        guard selected.count == 1, let selected = selected.first else { throw Failure.observation }
        return selected
    }
    private func selectInterfaceLanguage(_ language: String) throws {
        guard interfaceLanguages.contains(language) else { throw Failure.observation }
        let current = try currentInterfaceLanguage()
        if current != language {
            let option = element("iosSettings_appLanguageOption_\(language)")
            guard VocelloUISettingsReveal.perform(option, in: app, swipingUp: true) else { throw Failure.observation }
            try tap("iosSettings_appLanguageOption_\(language)")
        }
        try require("interface language selected") {
            self.selected(self.element("iosSettings_appLanguageOption_\(language)"))
        }
    }
    private func openPurchase() throws {
        try openSettingsRoot()
        let row = element("iosSettings_exportPurchaseRow")
        guard VocelloUISettingsReveal.perform(row, in: app, swipingUp: true) else { throw Failure.observation }
        try tap("iosSettings_exportPurchaseRow")
        try require("purchase sheet loaded") {
            self.element("exportPurchase_unlocked").exists || self.element("exportPurchase_buy").exists
        }
    }
    /// The environment is verified empty before launch, so an unlocked sheet here is the
    /// app's StoreKit cache still holding a deleted purchase (October 13, after a run ended
    /// while owned). Restore re-syncs it; the repair is attached, and initial_locked is
    /// still observed on a fresh launch.
    private func clearStaleEntitlementIfNeeded() throws {
        guard element("exportPurchase_unlocked").exists else { return }
        try tap("exportPurchase_restore")
        try notice("No export purchase was found")
        let evidence = XCTAttachment(string: "Unlocked before any purchase with no local transactions; Restore re-synced it")
        evidence.name = "purchase-stale-entitlement-cleared"
        evidence.lifetime = .keepAlways
        add(evidence)
        app.terminate()
        app.launch()
        try openPurchase()
    }
    private func locked() throws {
        try require("locked, local fixture price, idle") {
            let buy = self.element("exportPurchase_buy")
            guard buy.exists, buy.isEnabled else { return false }
            // The live product is $19.99. Fail closed before Buy if app routing is not local.
            return buy.label.filter(\.isNumber) == "099" && !self.element("exportPurchase_unlocked").exists
        }
    }
    private func unlocked() throws {
        try require("verified entitlement visible") {
            self.element("exportPurchase_unlocked").exists && !self.element("exportPurchase_buy").exists
        }
    }
    private func notice(_ text: String) throws {
        try require("purchase outcome: \(text)") {
            let status = self.element("exportPurchase_status")
            return status.exists && status.label.contains(text)
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
