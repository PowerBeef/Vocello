import CoreGraphics
import Foundation
@preconcurrency import XCTest

enum VocelloMacScreen: String, CaseIterable {
    case customVoice
    case voiceDesign
    case voiceCloning
    case history
    case voices
    case settings

    var sidebarID: String { "sidebar_\(rawValue)" }

    var screenID: String { "screen_\(rawValue)" }
}

@MainActor
class VocelloMacUITestCase: XCTestCase {
    private(set) var session: VocelloUIApplicationSession!
    private var pendingAutoplayPreferenceRestore: Bool?

    var app: XCUIApplication { session.app }

    var additionalLaunchEnvironment: [String: String] { [:] }

    func beginSession(additionalArguments: [String] = []) {
        continueAfterFailure = false
        session = VocelloUIApplicationSession()
        VocelloUIInterruptionSentinel.install(on: self)
        launchApp(
            additionalEnvironment: additionalLaunchEnvironment,
            additionalArguments: additionalArguments
        )
    }

    func endSession() {
        cleanUpPerTest()
        session?.terminate()
        session = nil
    }

    func cleanUpPerTest() {
        restorePendingAutoplayPreference()
    }

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
            VocelloUIWait.exists(app.windows.firstMatch, timeout: 30),
            "Vocello must expose one host-app window after launch"
        )
        // Fail fast, with a desktop screenshot, when a system permission
        // dialog or foreign window is covering the app — otherwise every
        // later interaction times out with a cryptic "not hittable" error.
        VocelloUIWait.assertForegroundUnobstructed(
            app,
            probe: button(VocelloMacScreen.customVoice.sidebarID)
        )
        navigate(to: .customVoice)
    }

    func relaunchApp(additionalEnvironment: [String: String]) {
        session.terminate()
        launchApp(additionalEnvironment: additionalEnvironment)
    }

    func element(
        _ id: String,
        type: XCUIElement.ElementType = .any,
        in scope: XCUIElement? = nil
    ) -> XCUIElement {
        VocelloUIWait.element(app, id: id, type: type, in: scope)
    }

    /// Typed button lookup — prunes the accessibility-tree walk versus an
    /// unscoped `.any` query. Use for every control that is a genuine button.
    func button(_ id: String, in scope: XCUIElement? = nil) -> XCUIElement {
        element(id, type: .button, in: scope)
    }

    func navigate(to screen: VocelloMacScreen) {
        let sidebar = button(screen.sidebarID)
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: sidebar, timeout: 20))
        XCTAssertTrue(VocelloUIWait.exists(element(screen.screenID), timeout: 20))
        XCTAssertTrue(
            VocelloUIWait.condition("sidebar destination to become selected", timeout: 10) {
                guard let value = sidebar.value as? String else { return false }
                return value == "selected" || value.hasPrefix("selected, ")
            }
        )
    }

    /// Requires the three visible Speed package rows to report Ready. This is
    /// deliberately not replaced by a headless inventory check.
    func assertVisibleSpeedModelReadiness() {
        navigate(to: .settings)
        XCTAssertTrue(
            VocelloUIWait.exists(element("settings_modelDownloadsSummary"), timeout: 60)
        )
        for id in [
            "settings_packageStatus_pro_custom_speed",
            "settings_packageStatus_pro_design_speed",
            "settings_packageStatus_pro_clone_speed",
        ] {
            XCTAssertTrue(VocelloUIWait.value(element(id), contains: "Ready", timeout: 60))
        }
    }

    /// Benchmarks require one genuine player scheduling event. Use the visible
    /// production preference and restore the user's original value afterward;
    /// telemetry must never synthesize this milestone.
    @discardableResult
    func ensureAutoplayEnabled() -> Bool {
        navigate(to: .settings)
        let toggle = element("preferences_autoPlayToggle")
        XCTAssertTrue(VocelloUIWait.exists(toggle, timeout: 20))
        guard let wasEnabled = VocelloUIToggle.state(of: toggle) else {
            XCTFail("Could not read the visible Auto-play toggle state")
            return true
        }
        if !wasEnabled {
            pendingAutoplayPreferenceRestore = false
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
        pendingAutoplayPreferenceRestore = false
        restorePendingAutoplayPreference()
    }

    /// Diagnostic counterpart of `ensureAutoplayEnabled`: drives the same
    /// visible Settings toggle OFF so a benchmark run can isolate the cost
    /// of live-preview playback/UI during generation. Returns the original
    /// state so the caller can restore it.
    @discardableResult
    func ensureAutoplayDisabled() -> Bool {
        navigate(to: .settings)
        let toggle = element("preferences_autoPlayToggle")
        XCTAssertTrue(VocelloUIWait.exists(toggle, timeout: 20))
        guard let wasEnabled = VocelloUIToggle.state(of: toggle) else {
            XCTFail("Could not read the visible Auto-play toggle state")
            return true
        }
        if wasEnabled {
            scrollSettingsIfNeeded(toReveal: toggle)
            XCTAssertTrue(VocelloUIPrimaryAction.perform(on: toggle, timeout: 20))
            XCTAssertTrue(
                VocelloUIWait.condition("Auto-play toggle to become disabled", timeout: 15) {
                    VocelloUIToggle.state(of: toggle) == false
                }
            )
        }
        return wasEnabled
    }

    /// The Settings pane can leave lower rows outside the visible region, and
    /// the primary-action helper deliberately never scrolls. Nudge the visible
    /// scroll area until the element reports hittable (bounded attempts).
    private func scrollSettingsIfNeeded(toReveal element: XCUIElement) {
        guard !element.isHittable else { return }
        // Settings is a sidebar destination in the main window, so the
        // content scroll view is not necessarily `scrollViews.firstMatch`
        // (the sidebar exposes one too). Nudge every visible scroll view.
        let scrollViews = app.scrollViews.allElementsBoundByIndex
        for delta in [-400.0, -400.0, -400.0, 1600.0, -400.0, -400.0] {
            for scrollView in scrollViews where scrollView.exists {
                scrollView.scroll(byDeltaX: 0, deltaY: CGFloat(delta))
                if element.isHittable { return }
            }
            if element.isHittable { return }
        }
    }

    func restoreAutoplayAfterDiagnostic(originallyEnabled: Bool) {
        guard originallyEnabled else { return }
        navigate(to: .settings)
        let toggle = element("preferences_autoPlayToggle")
        guard VocelloUIWait.exists(toggle, timeout: 20),
              VocelloUIToggle.state(of: toggle) == false else { return }
        _ = VocelloUIPrimaryAction.perform(on: toggle, timeout: 20)
    }

    /// Establish the persistent Clone consent through the same visible
    /// Settings control users operate. This is deliberately not a launch
    /// environment shortcut or seeded application state.
    func ensureCloneConsentEnabled() {
        navigate(to: .settings)
        let consent = element("voiceCloning_consentAcknowledgment")
        XCTAssertTrue(VocelloUIWait.exists(consent, timeout: 20))
        // The consent section deliberately sits last in Settings; scroll it
        // into view before any read/click at the test window height.
        _ = VocelloUIScroll.intoView(consent, in: element("screen_settings"))
        guard let consentState = VocelloUIToggle.state(of: consent) else {
            XCTFail("Could not read the visible Clone consent state")
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

    private func restorePendingAutoplayPreference() {
        guard pendingAutoplayPreferenceRestore == false, session != nil else { return }
        navigate(to: .settings)
        let toggle = element("preferences_autoPlayToggle")
        XCTAssertTrue(VocelloUIWait.exists(toggle, timeout: 20))
        if VocelloUIToggle.state(of: toggle) != false {
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

    func assertSavedCloneVoice() {
        navigate(to: .voices)
        XCTAssertTrue(
            VocelloUIWait.exists(
                element("voicesRow_\(VocelloUIBenchMatrix.cloneVoiceID)"),
                timeout: 20
            ),
            "The benchmark clone voice must be visibly present in Saved Voices"
        )
        XCTAssertTrue(
            VocelloUIWait.exists(
                element("voicesRow_use_\(VocelloUIBenchMatrix.cloneVoiceID)"),
                timeout: 20
            )
        )
    }

    func prepare(mode: VocelloUIBenchMatrix.Mode) {
        switch mode {
        case .custom:
            navigate(to: .customVoice)
        case .design:
            navigate(to: .voiceDesign)
            let brief = element("voiceDesign_voiceDescriptionField")
            if (brief.value as? String) != VocelloUIBenchMatrix.voiceDesignBrief {
                XCTAssertTrue(
                    VocelloUITextEntry.replace(
                        in: brief,
                        with: VocelloUIBenchMatrix.voiceDesignBrief,
                        timeout: 20
                    )
                )
            }
            XCTAssertTrue(
                VocelloUIWait.value(
                    brief,
                    contains: VocelloUIBenchMatrix.voiceDesignBrief,
                    timeout: 10
                )
            )
        case .clone:
            navigate(to: .voices)
            let useButton = element("voicesRow_use_\(VocelloUIBenchMatrix.cloneVoiceID)")
            XCTAssertTrue(VocelloUIPrimaryAction.perform(on: useButton, timeout: 20))
            XCTAssertTrue(VocelloUIWait.exists(element("screen_voiceCloning"), timeout: 20))
            XCTAssertTrue(VocelloUIWait.exists(element("voiceCloning_activeReference"), timeout: 20))
        }
    }

    func replaceScript(with text: String) {
        let editor = element("textInput_textEditor")
        if (editor.value as? String) != text {
            XCTAssertTrue(VocelloUITextEntry.replace(in: editor, with: text, timeout: 20))
        }
        XCTAssertTrue(
            VocelloUIWait.value(
                element("textInput_charCount"),
                contains: "\(text.count) characters",
                timeout: 10
            )
        )
    }

    func assertReadyToGenerate(mode: VocelloUIBenchMatrix.Mode) {
        let readinessID: String
        switch mode {
        case .custom: readinessID = "customVoice_readiness"
        case .design: readinessID = "voiceDesign_readiness"
        case .clone: readinessID = "voiceCloning_readiness"
        }
        XCTAssertTrue(
            // The readiness note's accessibilityValue is human-readable for
            // VoiceOver: "Ready" when generation can start, "Waiting"
            // otherwise (capital R distinguishes the states).
            VocelloUIWait.value(element(readinessID), contains: "Ready", timeout: 60)
        )
        XCTAssertTrue(VocelloUIWait.enabled(button("textInput_generateButton"), timeout: 60))
    }

    /// Starts a generation and waits until the visible Cancel control owns the
    /// run — the precondition for mid-generation cancellation coverage.
    func startGenerationAndAwaitCancelControl(mode: VocelloUIBenchMatrix.Mode) {
        assertReadyToGenerate(mode: mode)
        XCTAssertTrue(
            VocelloUIPrimaryAction.perform(on: button("textInput_generateButton"), timeout: 30)
        )
        XCTAssertTrue(
            VocelloUIWait.exists(button("textInput_cancelButton"), timeout: 30),
            "the visible Cancel control must appear once generation starts"
        )
    }

    /// Clicks the visible mid-generation Cancel and asserts the engine resets
    /// cleanly: Generate re-enabled, Cancel gone, and no visible backend error
    /// or crash badge — user cancellation is not a failure.
    func cancelActiveGenerationAndAssertCleanReset() {
        let generate = button("textInput_generateButton")
        let cancel = button("textInput_cancelButton")
        let backendError = element("sidebar_backendStatus_error")
        let backendCrash = element("sidebar_backendStatus_crashed")
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: cancel, timeout: 10))
        XCTAssertTrue(
            VocelloUIWait.condition(
                "cancelled generation to reset to a reusable Generate control",
                timeout: 60
            ) {
                generate.exists && generate.isEnabled && !cancel.exists
            }
        )
        XCTAssertFalse(backendError.exists, "User cancellation must never surface a backend error")
        XCTAssertFalse(backendCrash.exists, "User cancellation must never surface a backend crash")
    }

    /// Filters History by `text` and asserts the visible generation-row count
    /// converges to `expected` (0 means the shared empty/no-results state).
    /// The identifier lives on a genuine NSSearchField; an unscoped `.any`
    /// lookup resolves its representable wrapper first and typed text lands
    /// nowhere, so this queries the search field itself and asserts the text
    /// landed. The row predicate excludes per-row action controls, whose
    /// identifiers also start with `historyRow_`.
    func assertHistoryRows(matching text: String, expected: Int) {
        navigate(to: .history)
        let search = element("history_searchField", type: .searchField)
        XCTAssertTrue(VocelloUITextEntry.replace(in: search, with: text, timeout: 20))
        XCTAssertTrue(
            VocelloUIWait.value(search, contains: text, timeout: 10),
            "typed history filter text must land in the search field"
        )
        let rowPredicate = NSPredicate(
            format: "identifier BEGINSWITH 'historyRow_' AND NOT ("
                + "identifier CONTAINS '_saveVoice_' OR identifier CONTAINS '_saveAs_' "
                + "OR identifier CONTAINS '_delete_' OR identifier CONTAINS '_play_')"
        )
        let rows = app.descendants(matching: .any).matching(rowPredicate)
        // SwiftUI propagates each row's identifier onto every child element
        // (play button, text fields, trailing group), so the raw match count
        // is a multiple of the visible rows. Count unique identifiers — one
        // per logical row. The zero case needs no empty-state probe: the
        // "No results found" unavailable view exposes no row identifiers.
        XCTAssertTrue(
            VocelloUIWait.condition(
                "history to show exactly \(expected) row(s) for '\(text)'",
                timeout: 30
            ) {
                Set(rows.allElementsBoundByIndex.map { $0.identifier }).count == expected
            }
        )
    }

    /// Player visibility is first-chunk proof; the re-enabled Generate control
    /// is the visible completion condition.
    func generateAndWaitForCompletion(
        mode: VocelloUIBenchMatrix.Mode,
        timeout: TimeInterval
    ) {
        assertReadyToGenerate(mode: mode)
        let generate = button("textInput_generateButton")
        let cancel = button("textInput_cancelButton")
        let player = element("sidebarPlayer_bar")
        let backendError = element("sidebar_backendStatus_error")
        let backendCrash = element("sidebar_backendStatus_crashed")

        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: generate, timeout: 30))
        XCTAssertTrue(
            VocelloUIWait.condition("generation to visibly start", timeout: 30) {
                cancel.exists || !generate.exists || !generate.isEnabled
            }
        )
        // Diagnostic: hide the app (the genuine ⌘H user action) for the take
        // so its window stops compositing, isolating window-compositing cost
        // from the engine's GPU work. AX queries keep working while hidden;
        // the app is reactivated before the visible completion assertions.
        let hideDuringTake = ProcessInfo.processInfo
            .environment["QVOICE_MAC_BENCH_HIDE_DURING_TAKE"] == "1"
        if hideDuringTake {
            app.typeKey("h", modifierFlags: .command)
        }
        // Diagnostic (§K): after clicking Generate the pointer rests on the
        // control it just clicked, and Liquid Glass hover effects animate at
        // display refresh under the cursor for the whole take. Parking the
        // pointer at the screen corner removes the hover surface without
        // touching the app, isolating hover-animation compositor cost.
        if ProcessInfo.processInfo.environment["QVOICE_MAC_BENCH_PARK_CURSOR"] == "1" {
            CGEvent(
                mouseEventSource: nil,
                mouseType: .mouseMoved,
                mouseCursorPosition: CGPoint(x: 2, y: 2),
                mouseButton: .left
            )?.post(tap: .cghidEventTap)
        }
        XCTAssertTrue(
            VocelloUIWait.condition(
                "generation to complete with Generate enabled and the player visible",
                timeout: timeout
            ) {
                generate.exists
                    && generate.isEnabled
                    && !cancel.exists
                    && player.exists
                    && !backendError.exists
                    && !backendCrash.exists
            }
        )
        if hideDuringTake {
            app.activate()
            _ = VocelloUIWait.condition("app to return to the foreground", timeout: 15) {
                self.app.state == .runningForeground && generate.isHittable
            }
        }
        XCTAssertFalse(backendError.exists, "Generation must not expose a backend error")
        XCTAssertFalse(backendCrash.exists, "Generation must not expose a backend crash")
    }

    func timeout(for take: VocelloUIBenchMatrix.Take) -> TimeInterval {
        switch take.length {
        case .long: return take.warmState == .cold ? 360 : 300
        case .medium: return take.warmState == .cold ? 240 : 180
        case .short: return take.warmState == .cold ? 180 : 120
        }
    }
}
