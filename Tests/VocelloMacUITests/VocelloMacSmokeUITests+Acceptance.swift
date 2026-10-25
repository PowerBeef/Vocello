import AppKit
import Foundation
import XCTest

@MainActor
extension VocelloMacSmokeUITests {
    /// A genuine filesystem failure, limited to this run's disposable output
    /// folders. No model, engine response or UI state is substituted.
    func test11_GenerationErrorAndRecovery() throws {
        beginSession()
        let artifacts = try XCTUnwrap(ProcessInfo.processInfo.environment["QVOICE_MAC_BENCH_CAPTURE_DIR"])
        let root = URL(fileURLWithPath: artifacts).appendingPathComponent("output-permission-acceptance")
        let folders = ["CustomVoice", "VoiceDesign", "Clones"].map { root.appendingPathComponent($0) }
        for folder in folders {
            try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        }
        openSettingsCategory("modelsFiles")
        let original = button("preferences_outputResetButton").exists
            ? element("preferences_outputDirectory", type: .staticText).value as? String : nil
        // Base teardown calls the smoke cleanup even on stop-on-failure exits.
        acceptanceOutputRestore = (original, folders)
        chooseOutputFolder(root.path)
        ensureCloneConsentEnabled()

        for (index, mode) in [VocelloUIBenchMatrix.Mode.custom, .design, .clone].enumerated() {
            prepare(mode: mode)
            let script = "A quiet morning by the harbor. Permission check \(Self.pronounceableNonce())."
            replaceScript(with: script)
            assertReadyToGenerate(mode: mode)
            try FileManager.default.setAttributes([.posixPermissions: 0o555], ofItemAtPath: folders[index].path)
            XCTAssertTrue(VocelloUIPrimaryAction.perform(on: button("textInput_generateButton"), timeout: 20))
            let error = button("textInput_generationError")
            XCTAssertTrue(VocelloUIWait.exists(error, timeout: 180), "An unwritable destination must expose a retryable error")
            assertStaysAbsent(button("studio_inlinePlayer_playPause"), "A failed attempt must not publish a result",
                              settle: 1.5)
            assertStaysAbsent(button("textInput_generateButton"), "An idle failure has one retry action, matching iOS")
            assertStaysAbsent(button("textInput_cancelButton"), "A failed attempt leaves no Cancel control")
            assertStudioSizeMatrix("\(mode.rawValue)-write-error", failed: true)
            replaceScript(with: "")
            XCTAssertTrue(VocelloUIWait.condition("Retry to disable on empty input", timeout: 10) {
                !error.isEnabled
            }, "Retry follows the same empty-input rule as Generate")
            replaceScript(with: script)
            XCTAssertTrue(VocelloUIWait.enabled(error, timeout: 10))
            assertHistoryRows(matching: script, expected: 0)
            let screen: VocelloMacScreen = mode == .custom ? .customVoice : mode == .design ? .voiceDesign : .voiceCloning
            navigate(to: screen)
            XCTAssertTrue(error.exists, "Leaving Studio must preserve the error and draft")
            try FileManager.default.setAttributes([.posixPermissions: 0o755], ofItemAtPath: folders[index].path)
            XCTAssertTrue(VocelloUIPrimaryAction.perform(on: error, timeout: 20))
            XCTAssertTrue(VocelloUIWait.exists(button("studio_inlinePlayer_playPause"), timeout: 300))
            XCTAssertFalse(error.exists, "Retry must clear the failed attempt")
            assertStudioSizeMatrix("\(mode.rawValue)-recovered", completed: true)
            assertHistoryRows(matching: script, expected: 1)
        }
    }

    /// F-16: History's recovery path for a long-form journal Retry cannot
    /// resolve. It runs on an isolated empty profile, the registered storage
    /// isolation test10 uses, so the user's History is never touched. The banner
    /// offers Retry, Export and Discard; after Retry the notice stays and the
    /// journal is still in place (best effort: Retry's pass is not observable);
    /// a confirmed Discard ends the notice and sets the journal aside on disk,
    /// renamed and unchanged, never deleted.
    func test13_LongFormRecoveryDiscard() throws {
        beginSession()
        defer { endSession() }
        let artifacts = try XCTUnwrap(ProcessInfo.processInfo.environment["QVOICE_MAC_BENCH_CAPTURE_DIR"])
        let profile = URL(fileURLWithPath: artifacts).appendingPathComponent("long-form-recovery-profile")
        let journals = profile.appendingPathComponent("history-outbox/long-form", isDirectory: true)
        try FileManager.default.createDirectory(at: journals, withIntermediateDirectories: true)
        let damaged = Data("damaged long-form recovery fixture".utf8)
        try damaged.write(to: journals.appendingPathComponent(String(repeating: "0", count: 64) + ".json"))
        relaunchApp(additionalEnvironment: ["QWENVOICE_APP_SUPPORT_DIR": profile.path])

        navigate(to: .history)
        // The banner's container identifier is not exposed on macOS; its Retry is the notice.
        let retry = button("historyRecovery_retry")
        XCTAssertTrue(VocelloUIWait.exists(retry, timeout: 30), "An unreadable long-form journal must surface the recovery notice")
        XCTAssertTrue(VocelloUIWait.condition("the journal to be offered for export", timeout: 20) {
            self.button("historyRecovery_export").isEnabled
        })
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: retry, timeout: 20))
        let discard = button("historyRecovery_discard")
        XCTAssertTrue(VocelloUIWait.exists(discard, timeout: 20), "Retry cannot resolve it, so the notice and Discard stay")
        let pending = journals.appendingPathComponent(String(repeating: "0", count: 64) + ".json")
        XCTAssertEqual(try Data(contentsOf: pending), damaged, "Retry leaves the journal in place")
        VocelloUIScreenshot.attach(app.windows.firstMatch, named: "mac-long-form-recovery-notice")

        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: discard, timeout: 20))
        // The confirmation is a destructive alert, shown as a sheet; the interface is English.
        let confirm = app.sheets.firstMatch.buttons["Discard"]
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: confirm, timeout: 20))
        XCTAssertTrue(VocelloUIWait.disappears(retry, timeout: 30), "A confirmed Discard ends the notice")

        let kept = try FileManager.default.contentsOfDirectory(at: journals, includingPropertiesForKeys: nil)
        XCTAssertEqual(kept.map(\.pathExtension), ["unreadable"], "The journal is set aside, never deleted")
        XCTAssertEqual(try Data(contentsOf: XCTUnwrap(kept.first)), damaged, "The set-aside journal is unchanged")
        VocelloUIScreenshot.attach(app.windows.firstMatch, named: "mac-long-form-recovery-discarded")
    }

    /// BKL-15: Saved Voices' empty and error states lay out inside the window,
    /// as History's do since F-16, whose minimum-size pass had laid an empty
    /// History out about 3,900 pt tall and off screen. Both run on isolated
    /// profiles, the registered storage isolation test10 and test13 use, so the
    /// user's voices are never touched. The empty profile is new; the error is a
    /// genuine store failure, a plain file where the store keeps its review
    /// candidates, which fails every listing, Retry's included.
    func test14_SavedVoicesEmptyAndErrorStates() throws {
        beginSession()
        defer { endSession() }
        let artifacts = try XCTUnwrap(ProcessInfo.processInfo.environment["QVOICE_MAC_BENCH_CAPTURE_DIR"])
        let empty = URL(fileURLWithPath: artifacts).appendingPathComponent("saved-voices-empty-profile")
        relaunchApp(additionalEnvironment: ["QWENVOICE_APP_SUPPORT_DIR": empty.path])
        openSavedVoices(showingError: false)
        try assertSavedVoicesStateFitsWindow(named: "empty")

        let failing = URL(fileURLWithPath: artifacts).appendingPathComponent("saved-voices-error-profile")
        try FileManager.default.createDirectory(at: failing, withIntermediateDirectories: true)
        try Data("saved voices store failure fixture".utf8)
            .write(to: failing.appendingPathComponent("voice-candidates"))
        relaunchApp(additionalEnvironment: ["QWENVOICE_APP_SUPPORT_DIR": failing.path])
        openSavedVoices(showingError: true)
        try assertSavedVoicesStateFitsWindow(named: "error")
        let retry = button("voices_retryButton")
        VocelloUILayoutAssert.assertFullyWithinWindow(retry, of: app)
        XCTAssertTrue(retry.isHittable, "Retry must be reachable at the minimum window")
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: retry, timeout: 20))
        // Retry's own listing passes too quickly to observe; the store still fails, so
        // the screen must settle on the error again and hold it, not merely still show
        // the error it had before the click.
        XCTAssertTrue(VocelloUIWait.condition("Saved Voices to settle on its error after Retry", timeout: 30) {
            self.savedVoicesSettled(showingError: true)
        })
        XCTAssertFalse(VocelloUIWait.settles("Saved Voices to leave its error after Retry", timeout: 2) {
            !self.savedVoicesSettled(showingError: true)
        }, "After Retry the failing store must keep showing its error")
        VocelloUIScreenshot.attach(app.windows.firstMatch, named: "mac-voices-error-retried")
    }

    /// Presentation follows speech language; user-authored instructions survive
    /// both speech-language and interface-language changes without translation.
    func test12_CrossLanguageStudioContent() {
        beginSession()
        defer { endSession() }
        let cases = [("en", "french", "Calme", "Un narrateur"),
                     ("fr", "english", "Calm", "A deep, low-pitched male narrator")]
        for (interface, speech, calm, starterPrefix) in cases {
            selectInterfaceLanguage(interface)
            navigate(to: .voiceDesign)
            replaceScript(with: "The harbor is quiet. Le port est tranquille.")
            selectSpeechLanguage(speech, picker: "voiceDesign_languagePicker")
            XCTAssertTrue(VocelloUIPrimaryAction.perform(on: button("studioChip_voiceBrief"), timeout: 20))
            XCTAssertTrue(VocelloUIPrimaryAction.perform(on: element("voiceDesign_briefStarters"), timeout: 20))
            XCTAssertTrue(VocelloUIPrimaryAction.perform(on: element("voiceDesign_briefStarter_0", type: .menuItem), timeout: 10))
            let brief = element("voiceDesign_voiceDescriptionField")
            XCTAssertTrue(VocelloUIWait.value(brief, contains: starterPrefix, timeout: 10))
            let authoredBrief = "Une voix grave et posée; keep this exact custom brief."
            XCTAssertTrue(VocelloUITextEntry.replace(in: brief, with: authoredBrief, timeout: 20))
            XCTAssertTrue(VocelloUIPrimaryAction.perform(on: button("voiceBrief_confirm"), timeout: 20))
            for (screen, picker) in [(VocelloMacScreen.customVoice, "customVoice_languagePicker"),
                                     (.voiceDesign, "voiceDesign_languagePicker")] {
                navigate(to: screen)
                selectSpeechLanguage(speech, picker: picker)
                selectStudioMenuItem(startingWith: [calm], picker: "delivery_tonePicker")
                XCTAssertTrue(VocelloUIWait.value(element("delivery_tonePicker"), contains: calm, timeout: 10))
                selectStudioMenuItem(startingWith: [interface == "en" ? "Custom" : "Personnalisé"], picker: "delivery_tonePicker")
                let custom = "Speak gently. Garder cette consigne personnelle."
                let field = element("delivery_toneField", type: .textField)
                XCTAssertTrue(VocelloUITextEntry.replace(in: field, with: custom, timeout: 20))
                selectSpeechLanguage(speech == "french" ? "english" : "french", picker: picker)
                XCTAssertEqual(field.value as? String, custom)
                selectInterfaceLanguage(interface == "en" ? "fr" : "en")
                navigate(to: screen)
                XCTAssertEqual(field.value as? String, custom)
                VocelloUIScreenshot.attach(app.windows.firstMatch, named: "mac-\(interface)-\(speech)-\(screen.rawValue)-custom")
                selectInterfaceLanguage(interface)
            }
            navigate(to: .voiceDesign)
            XCTAssertTrue(VocelloUIPrimaryAction.perform(on: button("studioChip_voiceBrief"), timeout: 20))
            XCTAssertEqual(brief.value as? String, authoredBrief)
            VocelloUIScreenshot.attach(app.windows.firstMatch, named: "mac-\(interface)-\(speech)-preserved-brief")
            XCTAssertTrue(VocelloUIPrimaryAction.perform(on: button("voiceBrief_confirm"), timeout: 20))
        }
    }

    /// Opens Saved Voices once the engine is ready and waits for its listing
    /// to settle on the empty or the error state. A state card is then the
    /// whole screen, which SwiftUI exposes under `screen_voices`, so the state
    /// card's own identifier does not resolve: readiness comes from the status
    /// strip, a finished listing from the loading card's progress indicator
    /// having gone, and the error from its Retry button (BKL-15).
    private func openSavedVoices(showingError: Bool) {
        XCTAssertTrue(VocelloUIWait.condition("the engine to be ready", timeout: 90) {
            self.element("sidebar_backendStatus_standby").exists || self.element("sidebar_backendStatus_idle").exists
        })
        navigate(to: .voices)
        XCTAssertTrue(VocelloUIWait.condition("Saved Voices to settle", timeout: 30) {
            self.savedVoicesSettled(showingError: showingError)
        })
    }

    private func savedVoicesSettled(showingError: Bool) -> Bool {
        let screen = element("screen_voices")
        return screen.exists
            && !screen.progressIndicators.firstMatch.exists
            && element("voices_retryButton").exists == showingError
    }

    /// The window the state opened keeps a height a display can show (F-16's
    /// failure was a window thousands of points tall), and pinned to the
    /// minimum window, which that failure cannot reach, the state card sits
    /// inside it (BKL-15).
    private func assertSavedVoicesStateFitsWindow(named name: String) throws {
        // The screenshot comes first, so a regression's oversized window is kept.
        VocelloUIScreenshot.attach(app.windows.firstMatch, named: "mac-voices-\(name)-opened")
        let opened = app.windows.firstMatch.frame
        let displayHeights = NSScreen.screens.map { $0.frame.height }
        let tallestDisplay = try XCTUnwrap(displayHeights.max(), "No display to measure the window against")
        XCTAssertLessThanOrEqual(
            opened.height, tallestDisplay,
            "Saved Voices laid the window out \(Int(opened.height)) pt tall, taller than any display"
        )
        pinToNarrowestWindow()
        VocelloUILayoutAssert.assertFullyWithinWindow(element("screen_voices"), of: app)
        VocelloUIScreenshot.attach(app.windows.firstMatch, named: "mac-voices-\(name)-minimum")
    }

    private func selectSpeechLanguage(_ language: String, picker: String) {
        let titles = language == "french" ? ["French", "Français"] : ["English", "Anglais"]
        selectStudioMenuItem(startingWith: titles, picker: picker)
    }

    private func selectStudioMenuItem(startingWith titles: [String], picker: String) {
        let control = element(picker)
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: control, timeout: 20))
        // AppKit's SwiftUI Menu bridge exposes the visible title but replaces
        // row accessibility identifiers with its shared menuAction: selector.
        let choice = control.descendants(matching: .menuItem).matching(
            NSCompoundPredicate(orPredicateWithSubpredicates: titles.map {
                NSPredicate(format: "title BEGINSWITH %@", $0)
            })
        ).firstMatch
        XCTAssertTrue(VocelloUIWait.exists(choice, timeout: 10))
        let menu = control.descendants(matching: .menu).firstMatch
        if !choice.isHittable, menu.exists {
            let direction: XCUIKeyboardKey = choice.frame.midY < menu.frame.midY ? .upArrow : .downArrow
            for _ in 0..<20 {
                if choice.isHittable { break }
                app.typeKey(direction, modifierFlags: [])
            }
        }
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: choice, timeout: 10))
    }

    private func chooseOutputFolder(_ path: String) {
        openSettingsCategory("modelsFiles")
        XCTAssertTrue(VocelloUIScroll.intoView(button("preferences_browseButton"), in: element("screen_settings")))
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: button("preferences_browseButton"), timeout: 20))
        app.typeKey("g", modifierFlags: [.command, .shift])
        let pathField = app.dialogs.textFields.firstMatch
        XCTAssertTrue(VocelloUITextEntry.replace(in: pathField, with: path, timeout: 20))
        app.typeKey(.return, modifierFlags: [])
        let open = app.dialogs["open-panel"].buttons["Open"].firstMatch
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: open, timeout: 20))
        XCTAssertTrue(VocelloUIWait.condition("chosen output directory", timeout: 10) {
            self.element("preferences_outputDirectory", type: .staticText).value as? String == path
        })
    }

    func restoreOutputFolder(_ original: String?) {
        // A failed selection can leave Go to Folder above the open panel.
        // Dismiss only this test-owned picker before restoring Settings.
        for _ in 0..<2 {
            guard app.dialogs["open-panel"].exists else { break }
            app.typeKey(.escape, modifierFlags: [])
        }
        XCTAssertTrue(VocelloUIWait.disappears(app.dialogs["open-panel"], timeout: 10))
        if let original {
            chooseOutputFolder(original)
        } else {
            openSettingsCategory("modelsFiles")
            let reset = button("preferences_outputResetButton")
            if reset.exists {
                XCTAssertTrue(VocelloUIScroll.intoView(reset, in: element("screen_settings")))
                XCTAssertTrue(VocelloUIPrimaryAction.perform(on: reset, timeout: 20))
            }
            XCTAssertFalse(reset.exists)
        }
    }

    func assertLibrarySizeMatrix() {
        for (name, width, height) in [("minimum", CGFloat(780), CGFloat(560)),
                                      ("default", 1040, 680), ("wide", 4000, 680)] {
            if name == "minimum" {
                pinToNarrowestWindow()
            } else {
                let available = VocelloUIWindowFrame.availableFrame(for: app)
                let outerHeight = height + windowChromeHeight()
                let frame = VocelloUIWindowFrame.require(app, width: width, height: outerHeight)
                XCTAssertEqual(frame.width, min(width, available.width), accuracy: 6)
                XCTAssertEqual(frame.height, min(outerHeight, available.height), accuracy: 6)
            }
            assertSavedVoicesLayoutIntact()
            VocelloUIScreenshot.attach(app.windows.firstMatch, named: "mac-voices-\(name)")
            assertHistoryRows(matching: "uiperf-seed-0000", expected: 1)
            assertHistoryRowsLayoutIntact(filteredTo: "uiperf-seed-0000")
            VocelloUIScreenshot.attach(app.windows.firstMatch, named: "mac-history-\(name)")
            for category in ["audio", "appLanguage", "modelsFiles", "cloning"] {
                openSettingsOverview()
                VocelloUILayoutAssert.assertFullyWithinWindow(button("settings_category_\(category)"), of: app)
                // Straight from the overview just checked, not through a second overview trip.
                XCTAssertTrue(VocelloUIPrimaryAction.perform(on: button("settings_category_\(category)"), timeout: 20))
                XCTAssertTrue(VocelloUIWait.exists(element("settings_detail_\(category)"), timeout: 20))
                VocelloUIScreenshot.attach(app.windows.firstMatch, named: "mac-settings-\(category)-\(name)")
            }
        }
    }
}

/// Studio's Auto and manual language reach the engine (`scripts/ui_test.sh macos
/// auto-language`). Each mode starts on Auto. An Auto take types a tracked sentence and
/// waits for the language chip to follow detection ("French, Auto"); a manual take first
/// picks its language from the chip's menu on an empty script, checks that the chip keeps
/// it ("French") once the sentence is typed, and returns the mode to Auto after the take.
/// Every take then reads the chip's menu without choosing anything, generates, and prints
/// a manifest without the script that `scripts/auto_language_check.py` joins to the
/// engine's request receipt. It saves no voice and records nothing (BKL-19).
@MainActor
final class VocelloMacAutoLanguageUITests: VocelloMacUITestCase {
    override class var keepsClickAndTypePaths: Bool { true }

    private struct Plan: Decodable {
        let planDigest: String
        let takes: [Take]
    }

    private struct Take: Decodable {
        let takeID: String
        let mode: String
        let selection: String
        let selectionTitle: String?
        let script: String
        let expectedChipValue: String
        let expectedRecommendedTitle: String?
        let requireAudioPass: Bool
    }

    private struct Generation {
        let generationID: String?
        let visibleError: Bool
        let timedOut: Bool
    }

    private static let completedCardPrefix = "studio_inlinePlayer_generation_"

    private var runID: String {
        ProcessInfo.processInfo.environment["QVOICE_MAC_AUTO_LANGUAGE_RUN_ID"] ?? ""
    }

    /// The registered QVOICE_MAC_BENCH_RUN_ID knob only stamps `notes.benchRunID` on the
    /// engine rows, which is how the checker finds this run's receipts.
    override var additionalLaunchEnvironment: [String: String] {
        ["QVOICE_MAC_BENCH_RUN_ID": runID]
    }

    func testAutoLanguageReachesTheEngine() throws {
        let encoded = try XCTUnwrap(
            ProcessInfo.processInfo.environment["QVOICE_MAC_AUTO_LANGUAGE_PLAN_B64"],
            "Use scripts/ui_test.sh macos auto-language; the plan is missing"
        )
        XCTAssertFalse(runID.isEmpty, "Use scripts/ui_test.sh macos auto-language; the run ID is missing")
        let plan = try JSONDecoder().decode(Plan.self, from: try XCTUnwrap(Data(base64Encoded: encoded)))
        // Process-scoped argument-domain defaults, like -AppleLanguages: typed words
        // must reach the composer exactly as planned.
        beginSession(additionalArguments: [
            "-NSAutomaticSpellingCorrectionEnabled", "NO",
            "-NSAutomaticTextCompletionEnabled", "NO",
            "-NSAutomaticCapitalizationEnabled", "NO",
        ])
        defer { endSession() }
        assertVisibleSpeedModelReadiness()
        selectVisibleSpeedVariant(for: [.custom, .design, .clone])
        assertSavedCloneVoice()
        ensureCloneConsentEnabled()

        var problems: [String] = []
        var preparedMode: VocelloUIBenchMatrix.Mode?
        for take in plan.takes {
            let mode = try XCTUnwrap(VocelloUIBenchMatrix.Mode(rawValue: take.mode))
            let chip = element(Self.languagePickerID(for: mode))
            if preparedMode != mode {
                prepare(mode: mode)
                replaceScript(with: "")
                // With an empty script the chip reads "Auto" only while Auto is the
                // stored selection; a mode on another language fails closed.
                let start = stableValue(of: chip, equalTo: "Auto")
                guard start.stable else {
                    VocelloUIScreenshot.attach(app.windows.firstMatch, named: "auto-language-\(take.mode)-not-auto")
                    XCTFail("\(take.mode) language is not on Auto (the chip reads \(start.value ?? "nothing"))")
                    return
                }
                preparedMode = mode
            }
            // Reset first, so the previous take's chip cannot pass for this one.
            replaceScript(with: "")
            _ = stableValue(of: chip, equalTo: "Auto")
            if let title = take.selectionTitle {
                // Picked on an empty script, where every row carries its plain name.
                let picked = chooseLanguage(titled: title, on: chip)
                if !picked || !stableValue(of: chip, equalTo: title).stable {
                    problems.append("\(take.takeID): could not select \(title) from the language menu")
                }
            }
            replaceScript(with: take.script)
            let chipObservation = stableValue(of: chip, equalTo: take.expectedChipValue)
            let menu = inspectLanguageMenu(
                of: chip,
                recommendedTitle: take.expectedRecommendedTitle,
                valueBefore: chipObservation.value
            )
            VocelloUIScreenshot.attach(app.windows.firstMatch, named: "auto-language-\(take.takeID)")
            let generation = generate(mode: mode)
            try emit([
                "schemaVersion": 1,
                "runID": runID,
                "planDigest": plan.planDigest,
                "takeID": take.takeID,
                "mode": take.mode,
                "chip": [
                    "expectedValue": take.expectedChipValue,
                    "observedValue": chipObservation.value as Any? ?? NSNull(),
                    "stable": chipObservation.stable,
                ] as [String: Any],
                "menu": menu,
                "generationID": generation.generationID as Any? ?? NSNull(),
                "visibleErrorShown": generation.visibleError,
            ])

            if !chipObservation.stable || chipObservation.value != take.expectedChipValue {
                problems.append("\(take.takeID): chip read \(chipObservation.value ?? "nothing"), expected \(take.expectedChipValue)")
            }
            if menu["valueUnchanged"] as? Bool != true || menu["autoItemSeen"] as? Bool != true
                || (take.expectedRecommendedTitle != nil && menu["recommendedSeen"] as? Bool != true) {
                problems.append("\(take.takeID): language menu \(menu)")
            }
            if generation.timedOut {
                problems.append("\(take.takeID): the take neither completed nor showed an error")
            } else if generation.visibleError && take.requireAudioPass {
                problems.append("\(take.takeID): the take showed a generation error")
            }
            if take.selectionTitle != nil {
                // Back to Auto, so the next take starts as the plan assumes.
                replaceScript(with: "")
                let restored = chooseLanguage(titled: "Auto", on: chip)
                guard restored, stableValue(of: chip, equalTo: "Auto").stable else {
                    VocelloUIScreenshot.attach(app.windows.firstMatch, named: "auto-language-\(take.takeID)-not-restored")
                    XCTFail((problems + ["\(take.takeID): could not return \(take.mode) to Auto"]).joined(separator: "\n"))
                    return
                }
            }
        }
        if !problems.isEmpty {
            XCTFail(problems.joined(separator: "\n"))
        }
    }

    private static func languagePickerID(for mode: VocelloUIBenchMatrix.Mode) -> String {
        switch mode {
        case .custom: "customVoice_languagePicker"
        case .design: "voiceDesign_languagePicker"
        case .clone: "voiceCloning_languagePicker"
        }
    }

    /// The chip's accessibility value once it has held `expected` for 1.5 s, longer than
    /// the 350 ms detection debounce, so a stale value cannot pass. It never fails the
    /// test itself; the caller records what it saw.
    private func stableValue(
        of chip: XCUIElement,
        equalTo expected: String,
        timeout: TimeInterval = 20
    ) -> (value: String?, stable: Bool) {
        let clock = ProcessInfo.processInfo
        let deadline = clock.systemUptime + timeout
        var last: String?
        var since = clock.systemUptime
        repeat {
            let value = chip.exists ? chip.value as? String : nil
            let now = clock.systemUptime
            if value != last {
                last = value
                since = now
            }
            if value == expected, now - since >= 1.5 { return (value, true) }
            _ = XCTWaiter.wait(for: [XCTestExpectation(description: "language chip settles")], timeout: 0.25)
        } while clock.systemUptime < deadline
        return (last, false)
    }

    /// Picks a row of the chip's menu by its visible title (AppKit drops the rows'
    /// identifiers), moving through the open menu with the arrow keys when needed.
    private func chooseLanguage(titled title: String, on chip: XCUIElement) -> Bool {
        guard VocelloUIPrimaryAction.perform(on: chip, timeout: 20) else { return false }
        let item = chip.descendants(matching: .menuItem)
            .matching(NSPredicate(format: "title == %@", title)).firstMatch
        guard item.waitForExistence(timeout: 10) else {
            app.typeKey(.escape, modifierFlags: [])
            return false
        }
        let menu = chip.descendants(matching: .menu).firstMatch
        if !item.isHittable, menu.exists {
            let direction: XCUIKeyboardKey = item.frame.midY < menu.frame.midY ? .upArrow : .downArrow
            for _ in 0..<20 where !item.isHittable {
                app.typeKey(direction, modifierFlags: [])
            }
        }
        return VocelloUIPrimaryAction.perform(on: item, timeout: 10)
    }

    /// Opens the chip's menu, notes the Auto row and the detected row, and closes it with
    /// Escape without choosing anything; the chip must read the same afterwards.
    private func inspectLanguageMenu(
        of chip: XCUIElement,
        recommendedTitle: String?,
        valueBefore: String?
    ) -> [String: Any] {
        guard VocelloUIPrimaryAction.perform(on: chip, timeout: 20) else {
            return [
                "opened": false, "autoItemSeen": false, "valueUnchanged": false,
                "recommendedSeen": recommendedTitle == nil ? NSNull() as Any : false as Any,
            ]
        }
        let items = chip.descendants(matching: .menuItem)
        let auto = items.matching(NSPredicate(format: "title == %@", "Auto")).firstMatch
        let autoItemSeen = auto.waitForExistence(timeout: 10)
        var recommendedSeen: Any = NSNull()
        if let recommendedTitle {
            recommendedSeen = items.matching(NSPredicate(format: "title == %@", recommendedTitle))
                .firstMatch.waitForExistence(timeout: 5)
        }
        app.typeKey(.escape, modifierFlags: [])
        _ = XCTWaiter.wait(
            for: [XCTNSPredicateExpectation(predicate: NSPredicate(format: "isHittable == false"), object: auto)],
            timeout: 10
        )
        let after = stableValue(of: chip, equalTo: valueBefore ?? "", timeout: 10)
        return [
            "opened": autoItemSeen,
            "autoItemSeen": autoItemSeen,
            "recommendedSeen": recommendedSeen,
            "valueUnchanged": after.stable && after.value == valueBefore,
        ]
    }

    /// Generates the current script and waits, without failing the test, for a new
    /// completed card (its generation ID), a visible generation error or a backend error.
    private func generate(mode: VocelloUIBenchMatrix.Mode) -> Generation {
        let visibleError = element("textInput_generationError")
        if visibleError.exists {
            // After a rejected take the Studio's one action is the error's Retry, which
            // generates the current script; readiness reads "Engine needs attention" until then.
            XCTAssertTrue(VocelloUIWait.enabled(visibleError, timeout: 60))
        } else {
            assertReadyToGenerate(mode: mode)
        }
        let cards = app.descendants(matching: .any).matching(
            NSPredicate(format: "identifier BEGINSWITH %@", Self.completedCardPrefix)
        )
        let cardsBefore = Set(cards.allElementsBoundByIndex.map(\.identifier))
        let cancel = button("textInput_cancelButton")
        let backendFailures = [element("sidebar_backendStatus_error"), element("sidebar_backendStatus_crashed")]
        let errorBefore = visibleError.exists
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: generationAction, timeout: 30))
        let clock = ProcessInfo.processInfo
        let deadline = clock.systemUptime + 300
        var started = false
        repeat {
            started = started || cancel.exists
            let fresh = Set(cards.allElementsBoundByIndex.map(\.identifier)).subtracting(cardsBefore)
            if let card = fresh.first, !cancel.exists {
                return Generation(
                    generationID: String(card.dropFirst(Self.completedCardPrefix.count)).lowercased(),
                    visibleError: false,
                    timedOut: false
                )
            }
            if visibleError.exists, !cancel.exists, started || !errorBefore {
                return Generation(generationID: nil, visibleError: true, timedOut: false)
            }
            if backendFailures.contains(where: \.exists) {
                return Generation(generationID: nil, visibleError: true, timedOut: false)
            }
            _ = XCTWaiter.wait(for: [XCTestExpectation(description: "take completes")], timeout: 0.5)
        } while clock.systemUptime < deadline
        return Generation(generationID: nil, visibleError: false, timedOut: true)
    }

    /// One manifest line per take on the runner's output, plus a kept attachment.
    private func emit(_ record: [String: Any]) throws {
        let data = try JSONSerialization.data(withJSONObject: record, options: [.sortedKeys])
        print("VOCELLO_AUTO_LANGUAGE_TAKE=" + data.base64EncodedString())
        let attachment = XCTAttachment(data: data, uniformTypeIdentifier: "public.json")
        attachment.name = "auto-language-take-\(record["takeID"] as? String ?? "unknown")"
        attachment.lifetime = .keepAlways
        add(attachment)
    }
}
