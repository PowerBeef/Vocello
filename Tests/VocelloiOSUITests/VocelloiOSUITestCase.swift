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
    private var pendingInterfaceLanguageRestore: String?

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
        // A persisted in-app override wins over AppleLanguages. Use the genuine picker,
        // recording its original choice before mutation, so existing locale fixtures remain honest.
        selectInterfaceLanguageForTest("system")
        select(tab: .studio)
    }

    /// XCTest's stop-on-failure abort bypasses Swift `defer`, which is how most
    /// journeys end their session. Releasing it here (idempotent) restores the
    /// Auto-play and interface-language preferences on every exit path.
    override func tearDown() async throws {
        endSession()
        try await super.tearDown()
    }

    func endSession() {
        defer {
            session?.terminate()
            session = nil
            pendingAutoplayPreferenceRestore = nil
            pendingInterfaceLanguageRestore = nil
        }
        restorePendingAutoplayPreference()
        if let original = pendingInterfaceLanguageRestore, session != nil {
            let previousTab = VocelloiOSTab.allCases.first { element($0.identifier).isSelected }
            selectInterfaceLanguageForTest(original)
            if let previousTab { select(tab: previousTab) }
        }
    }

    func openAppLanguageSettings() {
        openSettingsRoot()
        let row = element("iosSettings_appLanguageRow")
        XCTAssertTrue(revealSettingsElement(row, swipingUp: true))
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: row, timeout: 20))
        XCTAssertTrue(VocelloUIWait.exists(element("screen_settings_appLanguage"), timeout: 20))
    }

    func selectInterfaceLanguageForTest(_ language: String) {
        openAppLanguageSettings()
        let identifiers = ["system", "en", "fr", "es", "de", "it", "pt-BR", "zh-Hans", "ja", "ko", "ru"]
        let selected = identifiers.filter {
            let option = element("iosSettings_appLanguageOption_\($0)")
            return option.exists && option.isSelected
        }
        XCTAssertEqual(selected.count, 1, "Must observe exactly one original interface language before mutation")
        guard let original = selected.first else { return }
        if pendingInterfaceLanguageRestore == nil {
            pendingInterfaceLanguageRestore = original
            let attachment = XCTAttachment(string: "Original App Language: \(original)")
            attachment.name = "interface-language-restoration-baseline"
            attachment.lifetime = .keepAlways
            add(attachment)
        }
        let option = element("iosSettings_appLanguageOption_\(language)")
        XCTAssertTrue(VocelloUIWait.exists(option, timeout: 20))
        if !option.isSelected {
            XCTAssertTrue(revealSettingsElement(option, swipingUp: true))
            XCTAssertTrue(VocelloUIPrimaryAction.perform(on: option, timeout: 20))
        }
        XCTAssertTrue(VocelloUIWait.condition("interface language selected", timeout: 10) {
            option.exists && option.isSelected
        })
        let back = element("iosSettings_appLanguageBackButton")
        XCTAssertTrue(revealSettingsElement(back, swipingUp: false))
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: back, timeout: 20))
        XCTAssertTrue(VocelloUIWait.disappears(element("screen_settings_appLanguage"), timeout: 20))
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

        // Existing lifecycle assertions use English status copy. Pin only this process's
        // language instead of depending on the phone language; localization walks opt in
        // to another language explicitly. NSArgumentDomain does not persist this choice.
        let arguments = additionalArguments.contains("-AppleLanguages")
            ? additionalArguments
            : ["-AppleLanguages", "(en)", "-AppleLocale", "en_US"] + additionalArguments
        session.launch(environment: environment, arguments: arguments)
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

    /// Follow genuine Settings navigation, including the tab's retained destination.
    func openSettingsRoot() {
        select(tab: .settings)
        for _ in 0..<3 {
            let backIDs = ["iosAttributionDetailBackButton", "iosSettings_voiceModelsBackButton", "iosSettings_openSourceBackButton"]
                + ["audio", "appLanguage", "modelsFiles", "privacyPermissions", "accessibility", "about"].map { "iosSettings_\($0)BackButton" }
            guard let back = backIDs.map({ element($0) }).first(where: { $0.exists }) else { break }
            XCTAssertTrue(revealSettingsElement(back, swipingUp: false))
            XCTAssertTrue(VocelloUIPrimaryAction.perform(on: back, timeout: 20))
            XCTAssertTrue(VocelloUIWait.disappears(back, timeout: 20))
        }
        XCTAssertTrue(VocelloUIWait.exists(element("screen_settings"), timeout: 20))
    }

    func openSettingsPage(for identifier: String) {
        let category: String
        switch identifier {
        case "iosSettings_autoPlayToggle", "iosSettings_variationRow": category = "audio"
        case "iosSettings_voiceModelsRow", "iosSettings_savedOutputsRow": category = "modelsFiles"
        case "voiceCloning_consentAcknowledgment", "iosSettings_privacyPolicyRow", "iosSettings_openIOSSettingsRow": category = "privacyPermissions"
        case "iosSettings_reduceMotionToggle", "iosSettings_reduceTransparencyToggle": category = "accessibility"
        case "iosSettings_supportRow", "iosSettings_openSourceRow", "iosSettings_sourceCodeRow", "iosSettings_versionLabel": category = "about"
        default: openSettingsRoot(); return
        }
        select(tab: .settings)
        if element("screen_settings_\(category)").exists { return }
        openSettingsRoot()
        let row = element("iosSettings_\(category)Row")
        XCTAssertTrue(VocelloUISettingsReveal.perform(row, in: app, swipingUp: true, requirement: .navigation))
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: row, timeout: 20))
        XCTAssertTrue(VocelloUIWait.exists(element("screen_settings_\(category)"), timeout: 20))
    }

    func openVoiceModels() {
        select(tab: .settings)
        if element("screen_voiceModels").exists { return }

        openSettingsPage(for: "iosSettings_voiceModelsRow")
        let row = element("iosSettings_voiceModelsRow")
        XCTAssertTrue(VocelloUIWait.exists(row, timeout: 20))
        XCTAssertTrue(VocelloUISettingsReveal.perform(row, in: app, swipingUp: false, requirement: .navigation))
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: row, timeout: 20))
        XCTAssertTrue(VocelloUIWait.exists(element("screen_voiceModels"), timeout: 20))
        XCTAssertTrue(VocelloUIWait.exists(element("iosSettings_voiceModelsBackButton"), timeout: 20))
    }

    func leaveVoiceModels() {
        guard element("screen_voiceModels").exists else { return }
        let back = element("iosSettings_voiceModelsBackButton")
        XCTAssertTrue(VocelloUIWait.exists(back, timeout: 20))
        XCTAssertTrue(revealSettingsElement(back, swipingUp: false))
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: back, timeout: 20))
        XCTAssertTrue(VocelloUIWait.exists(element("screen_settings_modelsFiles"), timeout: 20))
        XCTAssertTrue(VocelloUIWait.exists(element("iosSettings_voiceModelsRow"), timeout: 20))
    }

    func assertSettingsLandingArchitecture() {
        openSettingsRoot()
        XCTAssertTrue(VocelloUIWait.exists(element("screen_settings"), timeout: 20))

        for category in ["audio", "appLanguage", "modelsFiles", "privacyPermissions", "accessibility", "about"] {
            let row = element("iosSettings_\(category)Row")
            XCTAssertTrue(revealSettingsElement(row, swipingUp: true))
            XCTAssertTrue(VocelloUIPrimaryAction.perform(on: row, timeout: 20))
            XCTAssertTrue(VocelloUIWait.exists(element("screen_settings_\(category)"), timeout: 20))
            let back = element("iosSettings_\(category)BackButton")
            XCTAssertTrue(VocelloUIWait.exists(back, timeout: 20))
            XCTAssertGreaterThanOrEqual(back.frame.height, 44)
            VocelloUIScreenshot.attach(app, named: "ios-settings-\(category)")
            openSettingsRoot()
        }
        XCTAssertTrue(revealSettingsElement(element("iosSettings_exportPurchaseRow"), swipingUp: true))

        for identifier in [
            "iosSettings_autoPlayToggle",
            "iosSettings_variationRow",
            "iosSettings_voiceModelsRow",
            "iosSettings_savedOutputsRow",
            "iosSettings_reduceMotionToggle",
            "iosSettings_reduceTransparencyToggle",
        ] {
            openSettingsPage(for: identifier)
            XCTAssertTrue(VocelloUIWait.exists(element(identifier), timeout: 20))
        }
        VocelloUIScreenshot.attach(app, named: "ios-settings-landing-audio-models")

        openSettingsPage(for: "voiceCloning_consentAcknowledgment")
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
            openSettingsPage(for: identifier)
            XCTAssertTrue(VocelloUIWait.exists(element(identifier), timeout: 20))
        }
        VocelloUIScreenshot.attach(app, named: "ios-settings-landing-privacy-about")

        openSettingsPage(for: "iosSettings_openSourceRow")
        let attributions = element("iosSettings_openSourceRow")
        XCTAssertTrue(revealSettingsElement(attributions, swipingUp: true))
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: attributions, timeout: 20))
        XCTAssertTrue(VocelloUIWait.exists(element("screen_openSourceLicenses"), timeout: 20))
        XCTAssertFalse(element("iosAttributionLoadError").exists)
        XCTAssertTrue(VocelloUIWait.exists(element("iosAttributionRow_vocello"), timeout: 20))
        VocelloUIScreenshot.attach(app, named: "ios-settings-open-source-licenses")
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: element("iosSettings_openSourceBackButton"), timeout: 20))
        XCTAssertTrue(VocelloUIWait.exists(element("screen_settings_about"), timeout: 20))

        openSettingsPage(for: "iosSettings_autoPlayToggle")
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
        openSettingsPage(for: "iosSettings_autoPlayToggle")
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
        openSettingsPage(for: "voiceCloning_consentAcknowledgment")
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
        openSettingsPage(for: "iosSettings_autoPlayToggle")
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
        VocelloUISettingsReveal.perform(target, in: app, swipingUp: swipingUp)
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
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: searchField, timeout: 20))
        XCTAssertTrue(VocelloUIWait.condition("History keyboard ready", timeout: 15) {
            searchField.isHittable && self.app.keyboards.firstMatch.exists
        })
        // A tap can put the caret in the middle of the existing query. Counting
        // backspaces from there leaves a suffix, especially before a long query.
        // Use the production search-only Clear button (not History's delete menu)
        // and prove empty state before one non-retried replacement.
        let clear = app.buttons["historySearchField"].firstMatch
        if clear.exists {
            XCTAssertTrue(VocelloUIPrimaryAction.perform(on: clear, timeout: 20))
        }
        // IOSSearchField exposes Clear exactly when its bound text is nonempty.
        // An empty native field can report nil, an empty string or a placeholder;
        // the actual production button's disappearance is the empty-state proof.
        XCTAssertTrue(VocelloUIWait.condition("History search to clear", timeout: 15) {
            searchField.isHittable && self.app.keyboards.firstMatch.exists && !clear.exists
        })
        // Empty queries are proven by the conditional Clear control, not a
        // native accessibility value that may instead contain a placeholder.
        guard !query.isEmpty else { return }
        searchField.typeText(query)
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
        if app.keyboards.firstMatch.exists {
            // The floating tab dock is fully covered by the software keyboard.
            // Submit the genuine search field and prove the keyboard is gone
            // before a caller attempts a tab transition.
            searchField.typeText("\n")
            XCTAssertTrue(
                VocelloUIWait.condition("Voices search keyboard to dismiss", timeout: 15) {
                    !self.app.keyboards.firstMatch.exists
                }
            )
        }
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

    /// Read-only census of the filtered production list, including lazy rows.
    /// The search term narrows results but NEVER grants mutation authority.
    func historyRowCensus(expectedScript: String) -> [String]? {
        select(tab: .history)
        let search = app.textFields["historySearchField"].firstMatch
        guard VocelloUIWait.exists(search, timeout: 20) else { return nil }
        if (search.value as? String) != expectedScript {
            replaceHistorySearch(with: expectedScript)
        }
        dismissHistorySearchKeyboardIfNeeded()
        // History debounces search. Poll for a stable visible result, rather
        // than sleeping or treating the editor's value as completed filtering.
        var lastSignature = ""
        var stableSince = ProcessInfo.processInfo.systemUptime
        guard VocelloUIWait.condition("History search results to settle", timeout: 15, evaluate: {
            let signature = self.historyViewportSignature()
            if signature != lastSignature {
                lastSignature = signature
                stableSince = ProcessInfo.processInfo.systemUptime
            }
            return ProcessInfo.processInfo.systemUptime - stableSince >= 0.75
        }) else { return nil }

        let scroll = app.scrollViews.firstMatch
        guard VocelloUIWait.exists(scroll, timeout: 10) else { return nil }
        // Establish the leading edge first, even after a previous census left
        // the lazy list at its end. Exhaustion is an observed viewport condition.
        var reachedTop = false
        for _ in 0..<64 {
            let before = historyViewportSignature()
            scroll.swipeDown()
            if historyViewportSignature() == before { reachedTop = true; break }
        }
        guard reachedTop else {
            XCTFail("History census could not establish the top within its safety bound")
            return nil
        }
        var identifiers = Set<String>()
        for _ in 0..<64 {
            let visible = historyRows().allElementsBoundByIndex
            let rowPrefix = "historyRow_"
            let ids = visible.map { String($0.identifier.dropFirst(rowPrefix.count)) }
            guard Set(ids).count == ids.count,
                  ids.allSatisfy({ $0.range(of: #"^generation-[1-9][0-9]*$"#, options: .regularExpression) != nil }) else {
                XCTFail("History census contains duplicate or non-persisted row identities")
                return nil
            }
            identifiers.formUnion(ids)
            let before = historyViewportSignature()
            guard ids.isEmpty || !before.isEmpty else {
                XCTFail("History rows exist but no row action is visible; census cannot prove exhaustion")
                return nil
            }
            scroll.swipeUp()
            if historyViewportSignature() == before { return identifiers.sorted() }
        }
        XCTFail("History census exceeded its bound; no History mutation is authorized")
        return nil
    }

    func historyViewportSignature() -> String {
        app.descendants(matching: .any).matching(
            NSPredicate(format: "identifier BEGINSWITH %@", "historyRowTap_")
        ).allElementsBoundByIndex.filter { $0.isHittable }.map {
            "\($0.identifier):\(Int($0.frame.minY)):\(Int($0.frame.height))"
        }.joined(separator: "|")
    }

    func revealHistoryRow(_ rowID: String) -> XCUIElement? {
        let row = element("historyRowTap_\(rowID)")
        let scroll = app.scrollViews.firstMatch
        for _ in 0..<64 {
            if row.exists && row.isHittable { return row }
            let before = historyViewportSignature()
            scroll.swipeDown()
            if historyViewportSignature() == before { break }
        }
        XCTFail("The exact observed History row is not reachable")
        return nil
    }

    /// Verify the genuine full-player transcript before any menu mutation.
    func verifyHistoryTranscript(rowID: String, expectedScript: String) -> Bool {
        guard let rowAction = revealHistoryRow(rowID),
              VocelloUIPrimaryAction.perform(on: rowAction, timeout: 20) else { return false }
        let transcript = element("iosPlayer_transcript")
        guard VocelloUIWait.exists(transcript, timeout: 20) else { return false }
        let observed = transcript.value as? String
        let matches = observed == expectedScript
        if !matches {
            // Capture before dismissing: failure teardown cannot recover a value
            // that has already left the accessibility tree. Attachments stay private.
            let attachment = XCTAttachment(string: observed ?? "<missing String value>")
            attachment.name = "history-transcript-mismatch-\(rowID).txt"
            attachment.lifetime = .keepAlways
            add(attachment)
        }
        guard VocelloUIPrimaryAction.perform(on: element("iosPlayer_close"), timeout: 20),
              VocelloUIWait.disappears(transcript, timeout: 20) else { return false }
        guard matches else {
            XCTFail("Observed History row full transcript differs from the frozen plan")
            return false
        }
        return true
    }

    func dismissHistorySearchKeyboardIfNeeded() {
        guard app.keyboards.firstMatch.exists else { return }
        let searchField = app.textFields["historySearchField"].firstMatch
        XCTAssertTrue(searchField.exists)
        searchField.typeText("\n")
        XCTAssertTrue(
            VocelloUIWait.condition("History search keyboard to dismiss", timeout: 15) {
                !self.app.keyboards.firstMatch.exists
            }
        )
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
