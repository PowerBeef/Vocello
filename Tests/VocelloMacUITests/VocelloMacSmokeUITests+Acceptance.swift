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
                selectDeliveryOption("delivery_preset_calm")
                XCTAssertTrue(VocelloUIWait.value(element("delivery_tonePicker"), contains: calm, timeout: 10))
                selectDeliveryOption("delivery_customOption")
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

    private func selectSpeechLanguage(_ language: String, picker: String) {
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: element(picker), timeout: 20))
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: element("studio_languageOption_\(language)", type: .menuItem), timeout: 10))
    }

    private func selectDeliveryOption(_ identifier: String) {
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: element("delivery_tonePicker"), timeout: 20))
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: element(identifier, type: .menuItem), timeout: 10))
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
