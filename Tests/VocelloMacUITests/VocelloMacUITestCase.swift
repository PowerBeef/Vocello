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
    private var pendingInterfaceLanguageRestore: String?
    private static let interfaceLanguageNames = [
        "system": "System Default", "en": "English", "fr": "Français", "es": "Español",
        "de": "Deutsch", "it": "Italiano", "pt-BR": "Português (Brasil)", "zh-Hans": "简体中文",
        "ja": "日本語", "ko": "한국어", "ru": "Русский",
    ]

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

    /// XCTest's stop-on-failure abort bypasses Swift `defer`, which is how most
    /// journeys end their session. Releasing it here (idempotent) restores the
    /// visible Auto-play preference and terminates the app on every exit path.
    override func tearDown() async throws {
        endSession()
        try await super.tearDown()
    }

    func cleanUpPerTest() {
        if let original = pendingInterfaceLanguageRestore, session != nil {
            pendingInterfaceLanguageRestore = nil
            selectInterfaceLanguage(original)
        }
        restorePendingAutoplayPreference()
    }

    /// Selects a genuine menu item by its stable identifier, then reads its visible value.
    func selectInterfaceLanguage(_ identifier: String) {
        openSettingsCategory("appLanguage")
        let picker = element("settings_appLanguage")
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: picker, timeout: 20))
        let choice = element("settings_appLanguageOption_\(identifier)", type: .menuItem)
        XCTAssertTrue(VocelloUIWait.exists(choice, timeout: 10))
        // AppKit aligns a popup with its selected row. Earlier choices can be
        // above the display when Russian is selected; keyboard navigation scrolls
        // the genuine menu until the target is visible, without coordinate clicks.
        let menu = picker.descendants(matching: .menu).firstMatch
        if !choice.isHittable, menu.exists {
            let direction: XCUIKeyboardKey = choice.frame.midY < menu.frame.midY ? .upArrow : .downArrow
            for _ in 0..<Self.interfaceLanguageNames.count {
                if choice.isHittable { break }
                app.typeKey(direction, modifierFlags: [])
            }
        }
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: choice, timeout: 10))
        XCTAssertTrue(VocelloUIWait.value(picker, contains: Self.interfaceLanguageNames[identifier]!, timeout: 10))
    }

    func preserveInterfaceLanguage() {
        openSettingsCategory("appLanguage")
        let picker = element("settings_appLanguage")
        guard let value = picker.value as? String,
              let identifier = Self.interfaceLanguageNames.first(where: { $0.value == value })?.key else {
            XCTFail("Cannot preserve the visible interface-language selection")
            return
        }
        pendingInterfaceLanguageRestore = identifier
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

        // The journeys read a few English values ("Ready", "N characters"), and
        // since 2026-09-14 the catalog carries French, so a French-system host
        // would otherwise render the app in French. Pin the process language
        // through the argument domain (never persisted; `-AppleLanguages` here is
        // Foundation's launch override, not an app-side mutation) so every lane
        // sees the same English strings regardless of the host's settings.
        session.launch(
            environment: environment,
            arguments: Self.englishLaunchArguments + additionalArguments
        )
        XCTAssertTrue(
            VocelloUIWait.exists(app.windows.firstMatch, timeout: 30),
            "Vocello must expose one host-app window after launch"
        )
        // Fail fast, with a desktop screenshot, when a system permission
        // dialog or foreign window is covering the app — otherwise every
        // later interaction times out with a cryptic "not hittable" error.
        VocelloUIWait.assertForegroundUnobstructed(
            app,
            probe: button("sidebar_studio")
        )
        navigate(to: .customVoice)
    }

    static let englishLaunchArguments = ["-AppleLanguages", "(en)", "-AppleLocale", "en_US"]

    func relaunchApp(additionalEnvironment: [String: String], additionalArguments: [String] = []) {
        session.terminate()
        launchApp(additionalEnvironment: additionalEnvironment, additionalArguments: additionalArguments)
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

    /// A live query across the dock transition, preserving both production IDs.
    /// On Built-in Voice, the completed card's Retry replaces idle Generate.
    var generationAction: XCUIElement {
        app.buttons.matching(NSPredicate(
            format: "identifier IN %@",
            ["textInput_generateButton", "studio_inlinePlayer_retry"]
        )).firstMatch
    }

    func navigate(to screen: VocelloMacScreen) {
        if [.customVoice, .voiceDesign, .voiceCloning].contains(screen) {
            XCTAssertTrue(VocelloUIPrimaryAction.perform(on: button("sidebar_studio"), timeout: 20))
        }
        let sidebar = button(screen.sidebarID)
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: sidebar, timeout: 20))
        XCTAssertTrue(VocelloUIWait.exists(element(screen.screenID), timeout: 20))
        XCTAssertTrue(
            // The trait, which the app now sets instead of spelling the word
            // out in an accessibility value a French user would hear in
            // English. XCUITest reads the same attribute VoiceOver does.
            VocelloUIWait.condition("sidebar destination to become selected", timeout: 10) {
                sidebar.isSelected
            }
        )
    }

    func openSettingsOverview() {
        navigate(to: .settings)
        if button("settings_backButton").exists {
            XCTAssertTrue(VocelloUIPrimaryAction.perform(on: button("settings_backButton"), timeout: 20))
        }
        XCTAssertTrue(VocelloUIWait.exists(button("settings_category_audio"), timeout: 20))
    }

    func openSettingsCategory(_ category: String) {
        openSettingsOverview()
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: button("settings_category_\(category)"), timeout: 20))
        XCTAssertTrue(VocelloUIWait.exists(element("settings_detail_\(category)"), timeout: 20))
    }

    /// Requires the three visible Speed package rows to report Ready. This is
    /// deliberately not replaced by a headless inventory check.
    func assertVisibleSpeedModelReadiness() {
        openSettingsCategory("modelsFiles")
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
        openSettingsCategory("audio")
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

    /// Establish the persistent Clone consent through the same visible
    /// Settings control users operate. This is deliberately not a launch
    /// environment shortcut or seeded application state.
    func ensureCloneConsentEnabled() {
        openSettingsCategory("cloning")
        let consent = element("voiceCloning_consentAcknowledgment")
        XCTAssertTrue(VocelloUIWait.exists(consent, timeout: 20))
        // The focused consent page retains the full disclosure and can scroll
        // with longer localized text.
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
        openSettingsCategory("audio")
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

    /// Every visible Saved Voices row keeps a single-line name, status chip and
    /// warning pill, and its action buttons stay inside the window. Under the
    /// pseudo-localized launch this is the check that catches a collapsed row
    /// (2026-09-13: a chip rendered one character per line at 30 × 340 pt).
    func assertSavedVoicesLayoutIntact(minimumStatusWidth: CGFloat? = 60) {
        navigate(to: .voices)
        let window = app.windows.firstMatch.frame
        let excluded = ["_use_", "_play_", "_delete_", "_more_", "_transcriptStatus", "_qualityWarning", "_replaceReference"]
        let predicate = NSCompoundPredicate(andPredicateWithSubpredicates: [
            NSPredicate(format: "identifier BEGINSWITH %@", "voicesRow_"),
            NSCompoundPredicate(notPredicateWithSubpredicate: NSCompoundPredicate(
                orPredicateWithSubpredicates: excluded.map { NSPredicate(format: "identifier CONTAINS %@", $0) }
            )),
        ])
        let names = app.staticTexts.matching(predicate).allElementsBoundByIndex
        var checked = 0
        for name in names {
            let identifier = name.identifier
            guard identifier.hasPrefix("voicesRow_"), name.frame.intersects(window) else { continue }
            let voiceID = String(identifier.dropFirst("voicesRow_".count))
            checked += 1
            VocelloUILayoutAssert.assertSingleLine(name, maxHeight: 30, minWidth: 40)
            let status = element("\(identifier)_transcriptStatus", type: .staticText)
            VocelloUILayoutAssert.assertSingleLine(
                status, maxHeight: 30, minWidth: minimumStatusWidth ?? status.frame.height
            )
            let warning = button("\(identifier)_qualityWarning")
            if warning.exists {
                VocelloUILayoutAssert.assertSingleLine(warning, maxHeight: 30, minWidth: 24)
            }
            for action in ["voicesRow_use_\(voiceID)", "voicesRow_play_\(voiceID)"] {
                VocelloUILayoutAssert.assertWithinWindow(button(action), of: app)
            }
            VocelloUILayoutAssert.assertWithinWindow(
                element("voicesRow_more_\(voiceID)", type: .menuButton), of: app
            )
        }
        XCTAssertGreaterThan(checked, 0, "no visible Saved Voices row was checked; the query cannot pass vacuously")
    }

    /// The three Speed package rows keep single-line status and badge labels and
    /// their action slot inside the window.
    func assertSettingsPackageRowsLayoutIntact(minimumStatusWidth: CGFloat? = 30) {
        openSettingsCategory("modelsFiles")
        for id in ["pro_custom_speed", "pro_design_speed", "pro_clone_speed"] {
            XCTAssertTrue(VocelloUIScroll.intoView(
                element("settings_packageStatus_\(id)"), in: element("screen_settings")
            ))
            let status = element("settings_packageStatus_\(id)")
            VocelloUILayoutAssert.assertSingleLine(
                status, maxHeight: 24, minWidth: minimumStatusWidth ?? status.frame.height
            )
            let badge = element("settings_packageBadge_\(id)", type: .staticText)
            if badge.exists {
                VocelloUILayoutAssert.assertSingleLine(
                    badge, maxHeight: 24, minWidth: minimumStatusWidth ?? badge.frame.height
                )
            }
            let manage = button("settings_manage_\(id)")
            if manage.exists {
                VocelloUILayoutAssert.assertWithinWindow(manage, of: app)
            }
        }
    }

    /// Layout assertions belong at the size where layout fails. They used to run
    /// at whatever size the scene restored to, which is why every narrow-window
    /// defect of the UI-fidelity plan was found by eye and none by a test.
    ///
    /// Call this once per journey, not once per assertion: on an untrusted
    /// runner each call is two edge drags worth roughly a minute, and three
    /// separately-pinned assertions buy nothing a single pin does not.
    ///
    /// Returns the frame actually reached, which on a machine that cannot size
    /// the window is not the one asked for. Every assertion below it is true at
    /// whatever size it got; the activity records which size that was, so a
    /// reader can tell a run that measured the minimum from one that did not.
    @discardableResult
    func pinToNarrowestWindow() -> CGRect {
        let frame = VocelloUIWindowFrame.require(
            app,
            width: VocelloUIWindowFrame.Width.minimum,
            height: VocelloUIWindowFrame.Height.minimum
        )
        let reached = abs(frame.width - VocelloUIWindowFrame.Width.minimum) <= 6
            && abs(frame.height - VocelloUIWindowFrame.Height.minimum) <= 6
        let verdict = reached
            ? "reached"
            : "NOT reached (\(VocelloUIWindowFrame.shrinkDiagnosis(app, from: frame)))"
        XCTContext.runActivity(
            named: "Window pinned to \(Int(frame.width))x\(Int(frame.height)) pt; "
                + "declared minimum is \(Int(VocelloUIWindowFrame.Width.minimum))x"
                + "\(Int(VocelloUIWindowFrame.Height.minimum)) — \(verdict)"
        ) { _ in }
        return frame
    }

    /// Nothing in the Studio column scrolls. The composer flexes and everything
    /// under it — the chip rows, the mode footer, the dock — is fixed, so when
    /// the column needs more height than the window has, the dock is what falls
    /// off the bottom, and a control off the bottom of a column that does not
    /// scroll is not below the fold, it is gone.
    ///
    /// An audit found exactly that: at the 560 pt height the app declares as its
    /// minimum, Voice Design's column needs about 633 pt and Voice Cloning about
    /// 603 once a take has finished. Nothing caught it because no assertion had
    /// ever measured the dock, and none had ever run at the minimum.
    func assertStudioDockFitsAtMinimumWindow() {
        for screen in [VocelloMacScreen.customVoice, .voiceDesign, .voiceCloning] {
            navigate(to: screen)
            VocelloUILayoutAssert.assertFullyWithinWindow(
                generationAction, of: app
            )
        }
    }

    /// History's first geometry assertion. It had none of any kind — and
    /// `assertHistoryRows` counts rows, it does not measure them — so the
    /// densest surface in the app, the one whose metadata line carries four
    /// facts on one line, was the only library screen nothing watched.
    ///
    /// The row title is allowed two lines; the metadata beneath it is not,
    /// because that is where the duration lives and a wrapped date pushes it
    /// out of view.
    ///
    /// It measures a **filtered** History, and the filter is not a convenience:
    /// History renders every generation the machine has ever produced, and each
    /// `MacHistoryItemCard` carries `.accessibilityElement(children: .contain)`,
    /// so the card's identifier reaches every child and the accessibility tree
    /// is a large multiple of a row count that only ever grows. The first
    /// version of this walked that tree with `descendants(matching: .any)` and
    /// hung a lane for eighty-two minutes; the second used a typed query and
    /// still timed out resolving it, because the tree, not the predicate, is
    /// what is unbounded. `assertHistoryRows` has always filtered first, and
    /// this is the same discipline: narrow the list, then measure it.
    ///
    /// (That History loads and renders an unbounded row set is a product
    /// finding, not a test one. It is recorded against the History persistence
    /// work rather than worked around further here.)
    ///
    /// The labels are matched on their own identifiers because the row's does
    /// not reach them. `.accessibilityElement(children: .contain)` keeps a
    /// child's identity rather than lending it the container's -- which is the
    /// opposite of what the untyped query's behaviour suggested, and the
    /// reason `historyRow_title_<id>` and `historyRow_meta_<id>` exist.
    func assertHistoryRowsLayoutIntact(filteredTo text: String) {
        navigate(to: .history)
        let search = element("history_searchField", type: .searchField)
        XCTAssertTrue(VocelloUITextEntry.replace(in: search, with: text, timeout: 20))
        XCTAssertTrue(
            VocelloUIWait.value(search, contains: text, timeout: 10),
            "typed history filter text must land in the search field"
        )

        let playButtons = app.buttons.matching(
            NSPredicate(format: "identifier BEGINSWITH %@", "historyRow_play_")
        )
        // Rows load asynchronously after `screen_history` exists, so an
        // immediate query measures an empty list. A non-failing wait, because
        // a filter that matches nothing is a legitimate state, not a layout
        // failure.
        _ = VocelloUIWait.settles("History rows to load", timeout: 20) {
            playButtons.firstMatch.exists
        }

        let window = app.windows.firstMatch.frame
        // Only the rows on screen. History scrolls, so a row below the fold is
        // a legitimate state and its geometry is not meaningful to measure.
        let visibleRowIDs = playButtons.allElementsBoundByIndex
            .filter { $0.frame.intersects(window) }
            .map(\.identifier)
            .filter { $0.hasPrefix("historyRow_play_") }
            .map { String($0.dropFirst("historyRow_play_".count)) }

        var checked = 0
        var unmeasured: [String] = []
        for rowID in visibleRowIDs {
            // Matched on the identifier alone, not on an element type. The
            // metadata line is `.accessibilityElement(children: .ignore)`, so
            // what the tree exposes for it is a combined element rather than
            // the `staticText` the words suggest, and guessing that type wrong
            // is a silent empty match. Bounded because the list is filtered:
            // an exact-identifier lookup over one row resolves immediately.
            let title = element("historyRow_title_\(rowID)")
            let metadata = element("historyRow_meta_\(rowID)")
            guard title.exists, metadata.exists else {
                // Say which one is missing. A bare row id sends the next
                // reader back to the app to find out, and this assertion has
                // already cost two lane runs to answers that were one word.
                unmeasured.append("\(rowID)(title=\(title.exists) meta=\(metadata.exists))")
                continue
            }
            checked += 1

            // The metadata line is `lineLimit(1)` at 12 pt: it must truncate
            // under a doubled string, never wrap. That is where the duration
            // lives, and a wrapped date pushes it out of view.
            VocelloUILayoutAssert.assertSingleLine(metadata, maxHeight: 24, minWidth: 40)
            // The title above it is `lineLimit(2)` at 13 pt.
            VocelloUILayoutAssert.assertSingleLine(title, maxHeight: 44, minWidth: 40)
            for control in [title, metadata, button("historyRow_play_\(rowID)")] {
                VocelloUILayoutAssert.assertWithinWindow(control, of: app)
            }
        }

        // An empty History is legitimate and must not fail. A visible row whose
        // labels this could not find is not: that is the vacuous pass this
        // guards against, the failure mode that looks exactly like success.
        // It has already earned its keep once -- the first version of this
        // assumed the card's identifier reached its labels, found nothing, and
        // would have reported a clean pass over zero measurements.
        XCTAssertTrue(
            unmeasured.isEmpty,
            "\(unmeasured.count) of \(visibleRowIDs.count) visible History row(s) exposed no "
            + "measurable text: \(unmeasured). historyRow_title_<id> and historyRow_meta_<id> "
            + "must exist in MacHistoryItemCard, or this is watching nothing."
        )
        XCTContext.runActivity(
            named: "History rows measured: \(checked) of \(visibleRowIDs.count) visible"
        ) { _ in }
    }

    func prepare(mode: VocelloUIBenchMatrix.Mode) {
        switch mode {
        case .custom:
            navigate(to: .customVoice)
        case .design:
            navigate(to: .voiceDesign)
            XCTAssertTrue(VocelloUIPrimaryAction.perform(on: button("studioChip_voiceBrief"), timeout: 20))
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
            XCTAssertTrue(VocelloUIPrimaryAction.perform(on: button("voiceBrief_confirm"), timeout: 20))
        case .clone:
            navigate(to: .voices)
            let useButton = element("voicesRow_use_\(VocelloUIBenchMatrix.cloneVoiceID)")
            XCTAssertTrue(VocelloUIPrimaryAction.perform(on: useButton, timeout: 20))
            XCTAssertTrue(VocelloUIWait.exists(element("screen_voiceCloning"), timeout: 20))
            XCTAssertTrue(VocelloUIPrimaryAction.perform(on: button("studioChip_reference"), timeout: 20))
            XCTAssertTrue(VocelloUIWait.exists(element("voiceCloning_activeReference"), timeout: 20))
            XCTAssertTrue(VocelloUIPrimaryAction.perform(on: button("cloneReference_confirm"), timeout: 20))
        }
    }

    func replaceScript(with text: String) {
        let editor = element("textInput_textEditor")
        if (editor.value as? String) != text {
            XCTAssertTrue(VocelloUITextEntry.replace(in: editor, with: text, timeout: 20))
        }
        XCTAssertTrue(
            VocelloUIWait.value(
                editor,
                contains: text,
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
        XCTAssertTrue(VocelloUIWait.enabled(generationAction, timeout: 60))
    }

    /// Starts a generation and waits until the visible Cancel control owns the
    /// run — the precondition for mid-generation cancellation coverage.
    func startGenerationAndAwaitCancelControl(mode: VocelloUIBenchMatrix.Mode) {
        assertReadyToGenerate(mode: mode)
        XCTAssertTrue(
            VocelloUIPrimaryAction.perform(on: generationAction, timeout: 30)
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
        let generate = generationAction
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
                + "OR identifier CONTAINS '_delete_' OR identifier CONTAINS '_play_' "
                + "OR identifier CONTAINS '_title_' OR identifier CONTAINS '_meta_')"
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
        timeout: TimeInterval,
        onBeforeGenerate: (() -> Void)? = nil,
        onAfterGenerateClick: (() -> Void)? = nil
    ) {
        assertReadyToGenerate(mode: mode)
        let generate = generationAction
        let cancel = button("textInput_cancelButton")
        let player = button("studio_inlinePlayer_playPause")
        let backendError = element("sidebar_backendStatus_error")
        let backendCrash = element("sidebar_backendStatus_crashed")

        // The played-audio capture stamps its submit time here, right before the
        // genuine click, so first-audible latency is measured on one clock.
        onBeforeGenerate?()
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: generate, timeout: 30))
        // ...and again once the click call returned: the app's submit lies between.
        onAfterGenerateClick?()
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

    /// Waits until the visible Studio or sidebar player stops playing. The control
    /// is labelled with the action it will perform, so "Play" means playback
    /// is not running. The label is read rather than a value because the state
    /// words the app used to publish were hardcoded English; every lane pins
    /// `-AppleLanguages (en)`, so the label here is deterministic.
    func waitForPlaybackToFinish(timeout: TimeInterval) -> Bool {
        let inline = button("studio_inlinePlayer_playPause")
        let control = inline.exists ? inline : button("sidebarPlayer_playPause")
        return VocelloUIWait.condition("playback to finish", timeout: timeout) {
            !control.exists || control.label == "Play"
        }
    }

    func timeout(for take: VocelloUIBenchMatrix.Take) -> TimeInterval {
        switch take.length {
        case .long: return take.warmState == .cold ? 360 : 300
        case .medium: return take.warmState == .cold ? 240 : 180
        case .short: return take.warmState == .cold ? 180 : 120
        }
    }
}
