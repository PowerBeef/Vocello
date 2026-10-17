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
            XCTAssertFalse(button("studio_inlinePlayer_playPause").exists, "A failed attempt must not publish a result")
            XCTAssertFalse(button("textInput_generateButton").exists, "An idle failure has one retry action, matching iOS")
            XCTAssertFalse(button("textInput_cancelButton").exists)
            assertStudioSizeMatrix("\(mode.rawValue)-write-error", failed: true)
            replaceScript(with: "")
            XCTAssertFalse(error.isEnabled, "Retry follows the same empty-input rule as Generate")
            replaceScript(with: script)
            XCTAssertTrue(error.isEnabled)
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
        openSavedVoices(settlingOn: "voices_emptyState")
        try assertSavedVoicesStateFitsWindow("voices_emptyState", named: "empty")

        let failing = URL(fileURLWithPath: artifacts).appendingPathComponent("saved-voices-error-profile")
        try FileManager.default.createDirectory(at: failing, withIntermediateDirectories: true)
        try Data("saved voices store failure fixture".utf8)
            .write(to: failing.appendingPathComponent("voice-candidates"))
        relaunchApp(additionalEnvironment: ["QWENVOICE_APP_SUPPORT_DIR": failing.path])
        openSavedVoices(settlingOn: "voices_errorState")
        try assertSavedVoicesStateFitsWindow("voices_errorState", named: "error")
        let retry = button("voices_retryButton")
        VocelloUILayoutAssert.assertFullyWithinWindow(retry, of: app)
        XCTAssertTrue(retry.isHittable, "Retry must be reachable at the minimum window")
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: retry, timeout: 20))
        XCTAssertTrue(VocelloUIWait.condition("Retry to meet the same store failure", timeout: 30) {
            self.element("voices_errorState").exists && !self.element("voices_loadingState").exists
        })
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

    /// Opens Saved Voices once the engine has started and waits for the screen
    /// to settle on `identifier`. While the engine starts, the screen shows its
    /// starting card under the empty state's identifier, and every load passes
    /// through the loading state; neither is the state under test (BKL-15).
    private func openSavedVoices(settlingOn identifier: String) {
        XCTAssertTrue(VocelloUIWait.condition("the engine to finish starting", timeout: 60) {
            !self.element("sidebar_backendStatus_starting").exists
        })
        navigate(to: .voices)
        XCTAssertTrue(VocelloUIWait.condition("Saved Voices to settle on \(identifier)", timeout: 30) {
            self.element(identifier).exists && !self.element("voices_loadingState").exists
        })
    }

    /// The window the state opened keeps a height a display can show (F-16's
    /// failure was a window thousands of points tall), and pinned to the
    /// minimum window, which that failure cannot reach, the state sits inside
    /// it (BKL-15).
    private func assertSavedVoicesStateFitsWindow(_ identifier: String, named name: String) throws {
        let opened = app.windows.firstMatch.frame
        let displayHeights = NSScreen.screens.map { $0.frame.height }
        let tallestDisplay = try XCTUnwrap(displayHeights.max(), "No display to measure the window against")
        XCTAssertLessThanOrEqual(
            opened.height, tallestDisplay,
            "Saved Voices laid the window out \(Int(opened.height)) pt tall, taller than any display"
        )
        VocelloUIScreenshot.attach(app.windows.firstMatch, named: "mac-voices-\(name)-opened")
        pinToNarrowestWindow()
        VocelloUILayoutAssert.assertFullyWithinWindow(element(identifier), of: app)
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
                openSettingsCategory(category)
                VocelloUIScreenshot.attach(app.windows.firstMatch, named: "mac-settings-\(category)-\(name)")
            }
        }
    }
}
