import Foundation
@preconcurrency import XCTest

enum VocelloiOSTab: String, CaseIterable {
    case studio
    case voices
    case history
    case settings

    var identifier: String { "rootTab_\(rawValue)" }
}

/// Physical-device-only UI-test base. Every XCTest method receives its own
/// application session; no process, observer, or mutable fixture is shared
/// between tests.
@MainActor
class VocelloiOSUITestCase: XCTestCase {
    private(set) var session: VocelloUIApplicationSession!
    private var pendingAutoplayPreferenceRestore: Bool?

    var app: XCUIApplication { session.app }

    func beginSession(
        additionalEnvironment: [String: String] = [:],
        additionalArguments: [String] = []
    ) {
        continueAfterFailure = false
        assertToggleNormalizerContract()
        pendingAutoplayPreferenceRestore = nil
        session = VocelloUIApplicationSession()
        launchApp(
            additionalEnvironment: additionalEnvironment,
            additionalArguments: additionalArguments
        )
    }

    func endSession() {
        defer {
            session?.terminate()
            session = nil
            pendingAutoplayPreferenceRestore = nil
        }
        restorePendingAutoplayPreference()
    }

    /// Launches the production UI. First-run onboarding is completed through
    /// its visible Skip control; no onboarding bypass environment is injected.
    /// `additionalArguments` reach `UserDefaults` through the standard
    /// `NSArgumentDomain` (`-key value`), the same mechanism a user-typed
    /// `defaults` override uses; they configure production preferences only.
    func launchApp(
        additionalEnvironment: [String: String] = [:],
        additionalArguments: [String] = []
    ) {
        var environment = [
            "QWENVOICE_DEBUG": "1",
            "QWENVOICE_NATIVE_TELEMETRY_MODE": "verbose",
        ]
        for (key, value) in additionalEnvironment {
            environment[key] = value
        }

        session.launch(environment: environment, arguments: additionalArguments)
        XCTAssertTrue(
            VocelloUIWait.condition("Vocello to enter the foreground", timeout: 30) {
                self.app.state == .runningForeground
            }
        )
        completeVisibleOnboardingIfNeeded()
        XCTAssertTrue(VocelloUIWait.exists(element(VocelloiOSTab.studio.identifier), timeout: 30))
        // Fail fast, with a full-screen screenshot, when a system alert or
        // overlay is covering the app instead of surfacing later as cryptic
        // "not hittable" timeouts.
        VocelloUIWait.assertForegroundUnobstructed(
            app,
            probe: element(VocelloiOSTab.studio.identifier)
        )
        select(tab: .studio)
        XCTAssertTrue(VocelloUIWait.exists(element("generateSection_custom"), timeout: 30))
        XCTAssertTrue(VocelloUIWait.exists(element("textInput_textEditor"), timeout: 30))
    }

    func element(_ identifier: String) -> XCUIElement {
        VocelloUIWait.element(app, id: identifier)
    }

    func completeVisibleOnboardingIfNeeded() {
        let skip = element("onboarding_skip")
        let studio = element(VocelloiOSTab.studio.identifier)
        XCTAssertTrue(
            VocelloUIWait.condition("visible onboarding or the main tab dock", timeout: 30) {
                skip.exists || (studio.exists && studio.isHittable)
            }
        )
        guard skip.exists else { return }

        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: skip, timeout: 15))
        XCTAssertTrue(VocelloUIWait.disappears(element("onboarding_cta"), timeout: 20))
    }

    func select(tab: VocelloiOSTab) {
        let control = element(tab.identifier)
        XCTAssertTrue(VocelloUIWait.exists(control, timeout: 20))
        if !control.isSelected {
            XCTAssertTrue(VocelloUIPrimaryAction.perform(on: control, timeout: 20))
        }
        XCTAssertTrue(
            VocelloUIWait.condition("tab \(tab.rawValue) to become selected", timeout: 15) {
                control.exists && control.isSelected
            }
        )
    }

    func select(mode: VocelloUIBenchMatrix.Mode) {
        select(tab: .studio)
        let control = element("generateSection_\(mode.rawValue)")
        XCTAssertTrue(VocelloUIWait.exists(control, timeout: 20))
        if !control.isSelected {
            XCTAssertTrue(VocelloUIPrimaryAction.perform(on: control, timeout: 20))
        }
        XCTAssertTrue(
            VocelloUIWait.condition("Studio mode \(mode.rawValue) to become selected", timeout: 15) {
                control.exists && control.isSelected
            }
        )
        XCTAssertTrue(VocelloUIWait.exists(element(modeVisibleControlIdentifier(mode)), timeout: 20))
    }

    func openVoiceModels() {
        select(tab: .settings)
        if element("screen_voiceModels").exists { return }

        let row = element("iosSettings_voiceModelsRow")
        XCTAssertTrue(VocelloUIWait.exists(row, timeout: 20))
        XCTAssertTrue(revealSettingsElement(row, swipingUp: false))
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: row, timeout: 20))
        XCTAssertTrue(VocelloUIWait.exists(element("screen_voiceModels"), timeout: 20))
        XCTAssertTrue(VocelloUIWait.exists(element("iosSettings_voiceModelsBackButton"), timeout: 20))
    }

    func leaveVoiceModels() {
        guard element("screen_voiceModels").exists else { return }
        let back = element("iosSettings_voiceModelsBackButton")
        XCTAssertTrue(VocelloUIWait.exists(back, timeout: 20))
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: back, timeout: 20))
        XCTAssertTrue(VocelloUIWait.exists(element("screen_settings"), timeout: 20))
        XCTAssertTrue(VocelloUIWait.exists(element("iosSettings_voiceModelsRow"), timeout: 20))
    }

    func assertSettingsLandingArchitecture() {
        select(tab: .settings)
        XCTAssertTrue(VocelloUIWait.exists(element("screen_settings"), timeout: 20))

        for identifier in [
            "iosSettings_autoPlayToggle",
            "iosSettings_variationRow",
            "iosSettings_voiceModelsRow",
            "iosSettings_savedOutputsRow",
        ] {
            XCTAssertTrue(VocelloUIWait.exists(element(identifier), timeout: 20))
        }
        VocelloUIScreenshot.attach(app, named: "ios-settings-landing-audio-models")

        let consent = element("voiceCloning_consentAcknowledgment")
        XCTAssertTrue(VocelloUIWait.exists(consent, timeout: 20))
        XCTAssertTrue(revealSettingsElement(consent, swipingUp: true))
        for identifier in [
            "iosSettings_privacyPolicyRow",
            "iosSettings_openIOSSettingsRow",
            "iosSettings_supportRow",
            "iosSettings_openSourceRow",
            "iosSettings_sourceCodeRow",
            "iosSettings_versionLabel",
        ] {
            XCTAssertTrue(VocelloUIWait.exists(element(identifier), timeout: 20))
        }
        VocelloUIScreenshot.attach(app, named: "ios-settings-landing-privacy-about")

        let attributions = element("iosSettings_openSourceRow")
        XCTAssertTrue(revealSettingsElement(attributions, swipingUp: true))
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: attributions, timeout: 20))
        XCTAssertTrue(VocelloUIWait.exists(element("screen_openSourceLicenses"), timeout: 20))
        XCTAssertFalse(element("iosAttributionLoadError").exists)
        XCTAssertTrue(VocelloUIWait.exists(element("iosAttributionRow_vocello"), timeout: 20))
        VocelloUIScreenshot.attach(app, named: "ios-settings-open-source-licenses")
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: element("iosSettings_openSourceBackButton"), timeout: 20))
        XCTAssertTrue(VocelloUIWait.exists(element("screen_settings"), timeout: 20))

        XCTAssertTrue(revealSettingsElement(element("iosSettings_autoPlayToggle"), swipingUp: false))
    }

    /// Voice Models exposes each installed package with one non-color-dependent `Ready` status
    /// and a visible 44-point Remove action.
    func assertVisibleModelReadiness() {
        openVoiceModels()
        for modelID in ["pro_custom", "pro_design", "pro_clone"] {
            let status = element("iosModelStatus_\(modelID)")
            XCTAssertTrue(VocelloUIWait.exists(status, timeout: 60))
            XCTAssertTrue(VocelloUIWait.value(status, contains: "Ready", timeout: 20))

            let installedControl = element("iosModelDelete_\(modelID)")
            XCTAssertTrue(VocelloUIWait.exists(installedControl, timeout: 60))
            XCTAssertTrue(installedControl.isHittable)

            for unavailableState in ["Download", "Repair", "Cancel", "Retry"] {
                XCTAssertFalse(
                    self.element("iosModel\(unavailableState)_\(modelID)").exists,
                    "Installed model \(modelID) must not expose its \(unavailableState) control"
                )
            }
        }
        VocelloUIScreenshot.attach(app, named: "ios-settings-voice-models-ready")
        leaveVoiceModels()
    }

    /// Benchmarks require a real `play()` scheduling event so the typed
    /// frontend row can report playback latency and buffer health. Exercise
    /// the genuine visible Settings control and return the user's original
    /// preference so the caller can restore it after the matrix.
    @discardableResult
    func ensureAutoplayEnabled() -> Bool {
        select(tab: .settings)
        let toggle = element("iosSettings_autoPlayToggle")
        XCTAssertTrue(VocelloUIWait.exists(toggle, timeout: 20))
        XCTAssertTrue(revealSettingsElement(toggle, swipingUp: false))
        guard let wasEnabled = VocelloUIToggle.state(of: toggle) else {
            XCTFail("Auto-play toggle exposed an unknown value; refusing to mutate it")
            return true
        }
        if !wasEnabled {
            // Register the rollback before touching the production control.
            // If the tap or its assertion aborts, endSession still owns the
            // original preference and restores it through this same UI.
            pendingAutoplayPreferenceRestore = wasEnabled
            XCTAssertTrue(VocelloUIPrimaryAction.perform(on: toggle, timeout: 20))
            XCTAssertTrue(
                VocelloUIWait.condition("Auto-play toggle to become enabled", timeout: 15) {
                    VocelloUIToggle.state(of: toggle) == true
                }
            )
        }
        return wasEnabled
    }

    func restoreAutoplayPreference(originallyEnabled: Bool) {
        guard !originallyEnabled else { return }
        pendingAutoplayPreferenceRestore = originallyEnabled
        restorePendingAutoplayPreference()
    }

    /// Clone acceptance uses the same persistent preference as production.
    /// Establish it through the genuine visible Settings row before any
    /// relaunch so every benchmark session starts from an explicit consent
    /// state without a hidden launch override.
    func ensureCloneConsentEnabled() {
        select(tab: .settings)
        let consent = element("voiceCloning_consentAcknowledgment")
        XCTAssertTrue(VocelloUIWait.exists(consent, timeout: 20))
        XCTAssertTrue(revealSettingsElement(consent, swipingUp: true))
        guard let consentState = VocelloUIToggle.state(of: consent) else {
            XCTFail("Clone consent exposed an unknown value; refusing to mutate it")
            return
        }
        if !consentState {
            XCTAssertTrue(VocelloUIPrimaryAction.perform(on: consent, timeout: 20))
            XCTAssertTrue(
                VocelloUIWait.condition("Clone consent to become enabled", timeout: 15) {
                    VocelloUIToggle.state(of: consent) == true
                }
            )
        }
    }

    /// Idempotent visible-UI cleanup. The benchmark's explicit defer normally
    /// calls this first; endSession repeats it only when an earlier assertion
    /// prevented that defer from being registered or completed.
    private func restorePendingAutoplayPreference() {
        guard pendingAutoplayPreferenceRestore == false, session != nil else { return }
        select(tab: .settings)
        let toggle = element("iosSettings_autoPlayToggle")
        XCTAssertTrue(VocelloUIWait.exists(toggle, timeout: 20))
        XCTAssertTrue(revealSettingsElement(toggle, swipingUp: false))
        guard let currentState = VocelloUIToggle.state(of: toggle) else {
            XCTFail("Auto-play toggle exposed an unknown value; refusing to restore it blindly")
            return
        }
        if currentState {
            XCTAssertTrue(VocelloUIPrimaryAction.perform(on: toggle, timeout: 20))
            XCTAssertTrue(
                VocelloUIWait.condition("Auto-play toggle to restore disabled", timeout: 15) {
                    VocelloUIToggle.state(of: toggle) == false
                }
            )
        }
        if VocelloUIToggle.state(of: toggle) == false {
            pendingAutoplayPreferenceRestore = nil
        }
    }

    func revealSettingsElement(_ target: XCUIElement, swipingUp: Bool) -> Bool {
        // Accessibility sizes make Settings substantially taller than the
        // ordinary layout. Keep the bound finite while allowing the complete
        // AX-XXXL surface to move above the floating tab dock.
        for _ in 0..<20 {
            if settingsElementIsClearOfDock(target) { return true }
            if swipingUp {
                app.swipeUp()
            } else {
                app.swipeDown()
            }
        }
        return settingsElementIsClearOfDock(target)
    }

    private func settingsElementIsClearOfDock(_ target: XCUIElement) -> Bool {
        guard target.exists, target.isHittable else { return false }
        let dockAnchor = element("rootTab_settings")
        guard dockAnchor.exists else { return true }
        // XCTest can report a partially obscured row as hittable even when
        // its synthesized center tap lands inside the floating dock. Require
        // the complete target to clear the dock before acting on it.
        return target.frame.maxY <= dockAnchor.frame.minY - 4
    }

    @discardableResult
    func assertRequiredCloneVoice() -> XCUIElement {
        select(tab: .voices)
        let savedVoice = element("voicesRow_saved_\(VocelloUIBenchMatrix.cloneVoiceID)")
        XCTAssertTrue(
            VocelloUIWait.exists(savedVoice, timeout: 60),
            "The exact benchmark clone voice must be present in Saved Voices"
        )
        XCTAssertTrue(
            VocelloUIWait.condition("benchmark clone voice to be visible", timeout: 20) {
                savedVoice.exists && savedVoice.isHittable
            }
        )
        return savedVoice
    }

    func prepare(mode: VocelloUIBenchMatrix.Mode) {
        switch mode {
        case .custom:
            select(mode: .custom)
        case .design:
            select(mode: .design)
            setExactVoiceDesignBrief()
        case .clone:
            let savedVoice = assertRequiredCloneVoice()
            XCTAssertTrue(VocelloUIPrimaryAction.perform(on: savedVoice, timeout: 20))
            XCTAssertTrue(
                VocelloUIWait.condition("saved voice handoff to select Clone mode", timeout: 30) {
                    let clone = self.element("generateSection_clone")
                    return clone.exists && clone.isSelected
                }
            )
            let selectedReference = element("studioChip_reference")
            XCTAssertTrue(VocelloUIWait.exists(selectedReference, timeout: 30))
            // Proactive priming is a best-effort optimization. The production
            // Generate action performs required preparation on demand.
            XCTAssertTrue(
                VocelloUIWait.label(
                    selectedReference,
                    contains: VocelloUIBenchMatrix.cloneVoiceID,
                    timeout: 30
                ),
                "The visible Clone reference must match the exact benchmark voice"
            )
        }

        XCTAssertFalse(
            element("textInput_installModelButton").exists,
            "The selected mode must use its visibly installed model"
        )
    }

    func replaceScript(with text: String) {
        let editor = element("textInput_textEditor")
        XCTAssertTrue(VocelloUIWait.exists(editor, timeout: 20))
        let clear = element("textInput_clearButton")
        if text.isEmpty {
            if clear.exists {
                XCTAssertTrue(VocelloUIPrimaryAction.perform(on: clear, timeout: 20))
                XCTAssertTrue(
                    VocelloUIWait.condition("composer to clear through its visible control", timeout: 15) {
                        let value = editor.value as? String
                        return !clear.exists && (value == nil || value?.isEmpty == true)
                    }
                )
            }
        } else if (editor.value as? String) != text {
            if clear.exists {
                XCTAssertTrue(VocelloUIPrimaryAction.perform(on: clear, timeout: 20))
                XCTAssertTrue(
                    VocelloUIWait.condition("composer to clear through its visible control", timeout: 15) {
                        let value = editor.value as? String
                        return !clear.exists && (value == nil || value?.isEmpty == true)
                    }
                )
            }
            XCTAssertTrue(VocelloUITextEntry.replace(in: editor, with: text, timeout: 20))
        }

        let lengthCount = element("textInput_lengthCount")
        XCTAssertTrue(
            VocelloUIWait.condition("composer to contain the entered script", timeout: 15) {
                guard lengthCount.exists else { return false }
                if text.isEmpty {
                    return !clear.exists && lengthCount.label.hasPrefix("0 /")
                }
                return (editor.value as? String) == text
            }
        )

        // The production editor configures Return as Done, so this is a semantic
        // keyboard dismissal rather than a coordinate tap.
        if app.keyboards.firstMatch.exists {
            editor.typeText("\n")
        }
        XCTAssertTrue(
            VocelloUIWait.condition("software keyboard to dismiss", timeout: 15) {
                !self.app.keyboards.firstMatch.exists
            }
        )
    }

    /// Starts a real production generation and proves that streaming has
    /// reached both its visible live player and its genuine Cancel control.
    func startGenerationAndWaitForLivePreview() {
        let generate = element("textInput_generateButton")
        let liveCancel = element("studio_livePreview_cancel")
        let livePlayer = element("studio_livePreview_playPause")
        let completedPlayer = element("studio_inlinePlayer_playPause")
        let generationError = element("textInput_generationError")

        XCTAssertTrue(VocelloUIWait.enabled(generate, timeout: 60))
        XCTAssertFalse(completedPlayer.exists, "Cancellation proof must start without a completed player")
        XCTAssertFalse(generationError.exists, "Cancellation proof must not begin from an error state")
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: generate, timeout: 20))
        XCTAssertTrue(
            VocelloUIWait.condition("streaming generation to expose live player and Cancel", timeout: 120) {
                liveCancel.exists
                    && liveCancel.isHittable
                    && livePlayer.exists
                    && !generationError.exists
            }
        )
    }

    /// Cancels through the visible production control and proves the composer
    /// has reached a terminal, reusable state without retaining either player.
    func cancelActiveGenerationAndAssertTerminalUI() {
        let generate = element("textInput_generateButton")
        let liveCancel = element("studio_livePreview_cancel")
        let livePlayer = element("studio_livePreview_playPause")
        let completedPlayer = element("studio_inlinePlayer_playPause")
        let generationError = element("textInput_generationError")

        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: liveCancel, timeout: 20))
        XCTAssertTrue(
            VocelloUIWait.condition("cancelled generation to return to reusable terminal UI", timeout: 60) {
                !liveCancel.exists
                    && !livePlayer.exists
                    && !completedPlayer.exists
                    && generate.exists
                    && generate.isEnabled
                    && !generationError.exists
            }
        )
    }

    /// Starts a real production generation and waits for the runtime memory
    /// policy to cancel it. Typed cause and cancel-before-unload ordering are
    /// validated from pulled device diagnostics by `scripts/ui_test.sh`.
    func startGenerationAndWaitForAutomaticMemoryPressureTerminal() {
        let generate = element("textInput_generateButton")
        let cancel = element("textInput_cancelButton")
        let livePlayer = element("studio_livePreview_playPause")
        let completedPlayer = element("studio_inlinePlayer_playPause")
        let generationError = element("textInput_generationError")

        XCTAssertTrue(VocelloUIWait.enabled(generate, timeout: 60))
        XCTAssertFalse(completedPlayer.exists)
        XCTAssertFalse(generationError.exists)
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: generate, timeout: 20))

        // The one-shot guard may cancel and fully unload before XCUITest can
        // obtain its next accessibility snapshot. Do not require that brief
        // loading state to remain visible. The run-scoped diagnostics gate
        // proves the Generate tap produced the ordered critical signal,
        // typed cancellation, and full unload; the checks below prove the UI
        // returned cleanly and that the runtime can generate again afterward.
        XCTAssertTrue(
            VocelloUIWait.condition("memory-pressure generation to reach a terminal state", timeout: 120) {
                generationError.exists || (
                    !cancel.exists
                        && !livePlayer.exists
                        && !completedPlayer.exists
                        && generate.exists
                        && generate.isEnabled
                )
            }
        )
        XCTAssertFalse(generationError.exists, "Memory-pressure cancellation must be a clean terminal outcome")
        XCTAssertFalse(completedPlayer.exists, "Memory-pressure cancellation must not surface an output")
        XCTAssertTrue(VocelloUIWait.enabled(generate, timeout: 10))
    }

    func replaceHistorySearch(with query: String) {
        select(tab: .history)
        // SwiftUI propagates the container identifier to the decorative
        // magnifying-glass image as well as the underlying UITextField. Query
        // the genuine editable control explicitly so the image can never win
        // an `.any.firstMatch` lookup.
        let searchField = app.textFields["historySearchField"].firstMatch
        XCTAssertTrue(VocelloUIWait.exists(searchField, timeout: 30))
        XCTAssertTrue(VocelloUITextEntry.replace(in: searchField, with: query, timeout: 20))
        XCTAssertTrue(
            VocelloUIWait.condition("History search to match the requested token", timeout: 15) {
                (searchField.value as? String) == query
            }
        )
    }

    /// Reveals one exact saved voice through the production search field before
    /// returning its row and overflow menu. Saved rows live in a lazy stack, so
    /// `exists` alone is not activation evidence: an off-screen descendant can
    /// exist with an invalid hit point. The filtered row must expose finite,
    /// unobscured 44-point activation geometry before a destructive journey may
    /// continue.
    func revealSavedVoiceControls(
        named voiceName: String,
        timeout: TimeInterval = 30
    ) -> (row: XCUIElement, menu: XCUIElement)? {
        select(tab: .voices)
        let searchField = app.textFields["voicesSearchField"].firstMatch
        guard VocelloUIWait.exists(searchField, timeout: timeout) else { return nil }
        guard VocelloUITextEntry.replace(in: searchField, with: voiceName, timeout: 20) else {
            return nil
        }

        let row = element("voicesRow_saved_\(voiceName)")
        guard row.waitForExistence(timeout: 5) else {
            clearVoicesSearch()
            return nil
        }

        let menu = element("voicesRowMenu_\(voiceName)")
        guard VocelloUIWait.condition(
            "saved voice row and menu to expose valid activation geometry",
            timeout: timeout,
            evaluate: {
                let rowFrame = row.frame
                let menuFrame = menu.frame
                return row.exists
                    && menu.exists
                    && menu.isEnabled
                    && self.isValidActivationFrame(rowFrame)
                    && self.isValidActivationFrame(menuFrame)
                    && row.isHittable
                    && menu.isHittable
            }
        ) else {
            return nil
        }
        return (row, menu)
    }

    func clearVoicesSearch() {
        let searchField = app.textFields["voicesSearchField"].firstMatch
        guard searchField.exists else { return }
        XCTAssertTrue(VocelloUITextEntry.replace(in: searchField, with: "", timeout: 20))
    }

    private func isValidActivationFrame(_ frame: CGRect) -> Bool {
        !frame.isNull
            && !frame.isInfinite
            && frame.origin.x.isFinite
            && frame.origin.y.isFinite
            && frame.width.isFinite
            && frame.height.isFinite
            && frame.width >= 44
            && frame.height >= 44
    }

    func historyRows() -> XCUIElementQuery {
        app.descendants(matching: .any)
            .matching(NSPredicate(format: "identifier BEGINSWITH %@", "historyRow_"))
    }

    /// Uses only visible production state: enabled Generate before the action,
    /// the completed inline player after it, and no visible generation error.
    func generateAndWaitForCompletedPlayer(
        timeout: TimeInterval,
        failTestOnVisibleError: Bool = true,
        onVisibleError: ((String) -> Void)? = nil
    ) -> String {
        let generate = element("textInput_generateButton")
        let cancel = element("textInput_cancelButton")
        let livePlayer = element("studio_livePreview_playPause")
        let completedPlayer = element("studio_inlinePlayer_playPause")
        let generationError = element("textInput_generationError")
        let replacesCompletedPlayer = completedPlayer.exists

        XCTAssertTrue(VocelloUIWait.enabled(generate, timeout: 60))
        XCTAssertFalse(generationError.exists, "Generate must not begin from an error state")
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: generate, timeout: 20))
        XCTAssertTrue(
            VocelloUIWait.condition("generation to visibly start", timeout: 30) {
                cancel.exists || livePlayer.exists || !generate.exists || !generate.isEnabled
            }
        )
        if replacesCompletedPlayer {
            XCTAssertTrue(
                VocelloUIWait.condition("previous completed player to enter the next generation", timeout: 30) {
                    !completedPlayer.exists
                }
            )
        }
        XCTAssertTrue(
            VocelloUIWait.condition("generation to finish or expose an error", timeout: timeout) {
                completedPlayer.exists || generationError.exists
            }
        )
        if generationError.exists {
            // Preserve the genuine visible terminal state before the assertion
            // unwinds the test session. XCTest's automatic hierarchy snapshots
            // can otherwise stop at the preceding Generating frame.
            VocelloUIScreenshot.attach(app, named: "ios-generation-visible-error")
            let visibleError = [
                generationError.label,
                generationError.value as? String,
            ]
            .compactMap { $0 }
            .filter { !$0.isEmpty }
            .joined(separator: " | ")
            onVisibleError?(visibleError.isEmpty ? "Visible generation error" : visibleError)
            if failTestOnVisibleError {
                XCTFail("Generation exposed its visible error control: \(visibleError)")
            }
            return ""
        }
        XCTAssertTrue(VocelloUIWait.exists(completedPlayer, timeout: 5))
        XCTAssertTrue(
            VocelloUIWait.condition("completed player to replace live generation UI", timeout: 20) {
                completedPlayer.exists && !livePlayer.exists && !cancel.exists && !generationError.exists
            }
        )
        let prefix = "studio_inlinePlayer_generation_"
        let identifiedCard = app.descendants(matching: .any)
            .matching(NSPredicate(format: "identifier BEGINSWITH %@", prefix))
            .firstMatch
        XCTAssertTrue(VocelloUIWait.exists(identifiedCard, timeout: 10))
        let generationID = String(identifiedCard.identifier.dropFirst(prefix.count))
        XCTAssertNotNil(UUID(uuidString: generationID), "Completed player must expose its genuine generation UUID")
        return generationID
    }

    /// Clears a completed take through its visible production controls, then
    /// proves the Studio composer is ready for the next warm take.
    func dismissCompletedPlayerAndAssertGenerateReady() {
        let player = element("studio_inlinePlayer_playPause")
        let dismiss = element("studio_inlinePlayer_dismiss")
        let confirm = element("studio_inlinePlayer_dismissConfirm")
        XCTAssertTrue(VocelloUIWait.exists(player, timeout: 10))
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: dismiss, timeout: 15))
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: confirm, timeout: 15))
        XCTAssertTrue(VocelloUIWait.disappears(player, timeout: 20))
        XCTAssertTrue(VocelloUIWait.enabled(element("textInput_generateButton"), timeout: 30))
        XCTAssertFalse(element("textInput_generationError").exists)
    }

    func timeout(for take: VocelloUIBenchMatrix.Take) -> TimeInterval {
        switch take.length {
        case .long: return take.warmState == .cold ? 360 : 300
        case .medium: return take.warmState == .cold ? 300 : 240
        case .short: return take.warmState == .cold ? 240 : 180
        }
    }

    private func setExactVoiceDesignBrief() {
        XCTAssertTrue(
            VocelloUIPrimaryAction.perform(on: element("studioChip_voiceBrief"), timeout: 20)
        )
        let editor = element("voiceBrief_editor")
        XCTAssertTrue(VocelloUIWait.exists(editor, timeout: 20))
        XCTAssertTrue(
            VocelloUITextEntry.replace(
                in: editor,
                with: VocelloUIBenchMatrix.voiceDesignBrief,
                timeout: 20
            )
        )
        XCTAssertTrue(
            VocelloUIWait.condition("voice-design brief to match the benchmark fixture", timeout: 15) {
                (editor.value as? String) == VocelloUIBenchMatrix.voiceDesignBrief
            }
        )
        let confirm = element("voiceBrief_confirm")
        XCTAssertTrue(VocelloUIWait.enabled(confirm, timeout: 15))
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: confirm, timeout: 15))
        XCTAssertTrue(VocelloUIWait.disappears(confirm, timeout: 20))
    }

    private func modeVisibleControlIdentifier(_ mode: VocelloUIBenchMatrix.Mode) -> String {
        switch mode {
        case .custom: return "studioChip_voice"
        case .design: return "studioChip_voiceBrief"
        case .clone: return "studioChip_reference"
        }
    }

    /// These pure checks run inside every selected physical-device lane, so a
    /// platform bridging change cannot silently turn an unknown value into a tap.
    private func assertToggleNormalizerContract() {
        XCTAssertEqual(VocelloUIToggle.state(from: true), true)
        XCTAssertEqual(VocelloUIToggle.state(from: false), false)
        XCTAssertEqual(VocelloUIToggle.state(from: NSNumber(value: 1)), true)
        XCTAssertEqual(VocelloUIToggle.state(from: NSNumber(value: 0)), false)
        XCTAssertEqual(VocelloUIToggle.state(from: "1"), true)
        XCTAssertEqual(VocelloUIToggle.state(from: "0"), false)
        XCTAssertNil(VocelloUIToggle.state(from: "Activé"))
        XCTAssertNil(
            VocelloUIToggle.mutationRequired(currentValue: "Activé", desiredState: true),
            "An unknown localized value must never authorize a mutation"
        )
    }
}
