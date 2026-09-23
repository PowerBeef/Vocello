import CoreGraphics
import XCTest

/// Screenshot captures: the marketing assets for the website and README
/// (`test01`-`test03`), and the layout survey the design review reads
/// (`test04`-`test05`), which photographs every destination at each width the
/// app is designed against.
///
/// `scripts/ui_test.sh macos marketing` runs the current authored refresh.
/// Older captures and layout surveys remain explicit individual test selections.
/// Asset captures never count as acceptance or benchmark evidence.
/// The journey drives only genuine visible controls (the same identifiers the
/// smoke lane observes), attaches captures for asset export, and publishes
/// nothing. Script copy must follow website/PRODUCT.md rules: local not
/// offline, no em dashes, current preset names only.
final class VocelloMacMarketingCaptureUITests: VocelloMacUITestCase {
    /// A whole-bundle run must not turn asset captures into acceptance evidence.
    override func setUpWithError() throws {
        try super.setUpWithError()
        try XCTSkipUnless(
            ProcessInfo.processInfo.environment["QVOICE_MARKETING_CAPTURE"] == "1",
            "marketing captures run only with QVOICE_MARKETING_CAPTURE=1"
        )
    }

    /// Refresh the current Mac product assets without changing global keyboard
    /// accessibility settings. All content is entered through genuine controls;
    /// History is filtered to these public scripts, never a private-store export.
    func test00_WebsiteRefresh() throws {
        beginSession(additionalArguments: ["-AppleKeyboardUIMode", "0"])
        defer { endSession() }
        VocelloUIWindowFrame.require(app, width: 1040, height: 680)
        captureBuiltInRefresh()
        captureDesignRefresh()
        captureCloneRefresh()
        navigate(to: .history)
        let search = element("history_searchField", type: .searchField)
        XCTAssertTrue(VocelloUITextEntry.replace(in: search, with: "Made with Vocello", timeout: 20))
        XCTAssertTrue(VocelloUIWait.value(search, contains: "Made with Vocello", timeout: 10))
        app.typeKey(.tab, modifierFlags: [])
        captureRefresh("history")
        // A fresh app session clears the search field's keyboard traversal
        // focus before taking the Settings image, without changing host prefs.
        endSession()
        beginSession(additionalArguments: ["-AppleKeyboardUIMode", "0"])
        VocelloUIWindowFrame.require(app, width: 1040, height: 680)
        captureModelsRefresh()
    }

    func test06_ModelDownloadsRefresh() {
        beginSession(additionalArguments: ["-AppleKeyboardUIMode", "0"])
        defer { endSession() }
        VocelloUIWindowFrame.require(app, width: 1040, height: 680)
        captureModelsRefresh()
    }

    private func captureModelsRefresh() {
        openSettingsCategory("modelsFiles")
        let status = element("settings_packageStatus_pro_custom_speed")
        XCTAssertTrue(VocelloUIWait.exists(status, timeout: 20))
        // Move mouse focus into the visible content before capturing. Opening
        // Settings can leave keyboard focus on the toolbar's sidebar toggle.
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: status, timeout: 20))
        captureRefresh("model-downloads")
    }

    private func captureBuiltInRefresh() {
        prepare(mode: .custom)
        replaceScript(with: "Made with Vocello. Bring your words to life, with a voice that feels right. "
            + "Created locally on your Mac. Yours from the first word to the last.")
        navigate(to: .voices)
        navigate(to: .customVoice)
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: element("delivery_tonePicker"), timeout: 20))
        XCTAssertTrue(VocelloUIWait.exists(app.menuItems["Calm"].firstMatch, timeout: 10))
        captureRefresh("delivery-presets")
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: app.menuItems["Calm"].firstMatch, timeout: 10))
        generateAndWaitForCompletion(mode: .custom, timeout: 360)
        captureRefresh("custom-voice")
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: button("studio_inlinePlayer_dismiss"), timeout: 20))
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: button("studio_inlinePlayer_dismissConfirm"), timeout: 20))
    }

    private func captureDesignRefresh() {
        // Saving the designed voice below is an enrollment, which the engine store
        // refuses without the recorded Settings consent (PA-17).
        ensureCloneConsentEnabled()
        navigate(to: .voiceDesign)
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: button("studioChip_voiceBrief"), timeout: 20))
        let brief = element("voiceDesign_voiceDescriptionField")
        XCTAssertTrue(VocelloUITextEntry.replace(in: brief,
            with: "A warm, clear narrator with a gentle British accent and an unhurried, natural pace.", timeout: 20))
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: button("voiceBrief_confirm"), timeout: 20))
        replaceScript(with: "Made with Vocello. A little warmth, a touch of character, "
            + "and a story ready to be told.")
        navigate(to: .voices)
        navigate(to: .voiceDesign)
        assertReadyToGenerate(mode: .design)
        captureRefresh("voice-design")
        generateAndWaitForCompletion(mode: .design, timeout: 360)
        navigate(to: .voices)
        if savedVoiceRow(named: "Studio narrator", timeout: 10) != nil { return }
        navigate(to: .voiceDesign)
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: button("voiceDesign_saveVoiceButton"), timeout: 20))
        XCTAssertTrue(VocelloUITextEntry.replace(in: element("voicesEnroll_nameField"),
            with: "Studio narrator", timeout: 20))
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: button("voicesEnroll_confirmButton"), timeout: 60))
        XCTAssertTrue(VocelloUIWait.condition("designed voice to be saved", timeout: 60) {
            !self.element("voicesEnroll_confirmButton").exists
        })
        let confirmation = app.alerts.buttons["OK"].firstMatch
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: confirmation, timeout: 20))
    }

    private func captureCloneRefresh() {
        ensureCloneConsentEnabled()
        navigate(to: .voices)
        guard let name = savedVoiceRow(named: "Studio narrator", timeout: 20) else {
            XCTFail("The designed voice saved by the Design capture must be visible in Saved Voices")
            return
        }
        let voiceID = String(name.identifier.dropFirst("voicesRow_".count))
        let use = element("voicesRow_use_\(voiceID)")
        XCTAssertTrue(VocelloUIScroll.intoView(use, in: element("screen_voices")))
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: use, timeout: 20))
        replaceScript(with: "A familiar voice, a new story. Keep the character you created, "
            + "and give it something new to say.")
        navigate(to: .history)
        navigate(to: .voiceCloning)
        if button("sidebarPlayer_dismiss").exists {
            XCTAssertTrue(VocelloUIPrimaryAction.perform(on: button("sidebarPlayer_dismiss"), timeout: 20))
        }
        assertReadyToGenerate(mode: .clone)
        captureRefresh("voice-cloning")
    }

    /// The Saved Voices name row for the voice this journey enrolled, resolved
    /// through the stable `voicesRow_<id>` identifiers (the id is minted at
    /// enrollment, so the row is matched on the name the journey itself typed).
    /// Returns nil without recording a failure: a first run has no saved voice
    /// yet and enrolls it; a rerun on the same store reuses the existing one.
    private func savedVoiceRow(named voiceName: String, timeout: TimeInterval) -> XCUIElement? {
        let excluded = ["_use_", "_play_", "_delete_", "_more_", "_transcriptStatus", "_qualityWarning", "_replaceReference"]
        let rows = NSCompoundPredicate(andPredicateWithSubpredicates: [
            NSPredicate(format: "identifier BEGINSWITH %@", "voicesRow_"),
            NSCompoundPredicate(notPredicateWithSubpredicate: NSCompoundPredicate(
                orPredicateWithSubpredicates: excluded.map { NSPredicate(format: "identifier CONTAINS %@", $0) }
            )),
        ])
        func match() -> XCUIElement? {
            app.staticTexts.matching(rows).allElementsBoundByIndex.first { row in
                row.label == voiceName || (row.value as? String) == voiceName
            }
        }
        let found = NSPredicate { _, _ in match() != nil }
        _ = XCTWaiter.wait(for: [XCTNSPredicateExpectation(predicate: found, object: NSObject())], timeout: timeout)
        return match()
    }

    private func captureRefresh(_ name: String) {
        let shot = XCTAttachment(screenshot: app.windows.firstMatch.screenshot())
        shot.name = "refresh-\(name)"
        shot.lifetime = .keepAlways
        add(shot)
    }

    func test01_CustomVoiceCapture() throws {
        beginSession()
        defer { endSession() }

        let script = "Welcome to Vocello. Every word you hear was generated "
            + "right here on your Mac, private by design."
        prepare(mode: .custom)
        replaceScript(with: script)

        let window = app.windows.firstMatch

        // Delivery menu open for the presets asset, captured while Neutral is
        // still selected so the menu drops fully inside the window. The
        // floating menu renders in its own window, so capture the full screen
        // and print the app window frame (points; multiply by backing scale
        // for pixels) for lane-side cropping. The uncropped capture stays in
        // the untracked result bundle.
        let tone = element("delivery_tonePicker")
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: tone, timeout: 20))
        let calm = app.menuItems["Calm"].firstMatch
        XCTAssertTrue(VocelloUIWait.exists(calm, timeout: 10))
        let frame = window.frame
        print(
            "MARKETING_WINDOW_FRAME="
                + "\(Int(frame.minX)),\(Int(frame.minY)),\(Int(frame.width)),\(Int(frame.height))"
        )
        let fullShot = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        fullShot.name = "marketing-delivery-presets-fullscreen"
        fullShot.lifetime = .keepAlways
        add(fullShot)

        // Then select Calm from the open menu. The intensity control was retired
        // 2026-08-02 and every preset now ships its strong copy, so the capture
        // no longer selects a tier — it gets one by default.
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: calm, timeout: 10))

        assertReadyToGenerate(mode: .custom)

        // Window capture for the hero asset.
        let windowShot = XCTAttachment(screenshot: window.screenshot())
        windowShot.name = "marketing-custom-voice"
        windowShot.lifetime = .keepAlways
        add(windowShot)
    }

    /// Voice Cloning and History captures with authored content.
    ///
    /// Staging contract (operator-run before this test): the debug history
    /// store starts empty (back up and remove
    /// `QwenVoice-Debug/history.sqlite*`), and the human-named marketing clone
    /// voice below is enrolled through the genuine CLI surface:
    /// `QWENVOICE_DEBUG=1 build/vocello voices enroll --name "Warm storyteller"
    /// --audio <reference wav> --transcript "<the reference's real transcript>"
    /// --confirm-consent` (only for a voice you own or have permission to clone).
    /// The journey then generates real takes so History shows authored scripts,
    /// never leftover QA fixtures.
    func test02_CloneAndHistoryCapture() throws {
        let marketingVoice = "Warm storyteller"
        beginSession()
        defer { endSession() }

        ensureCloneConsentEnabled()

        // Voice Cloning capture: the marketing voice active with an authored
        // script, pre-take so the screen reads as a fresh session.
        navigate(to: .voices)
        let useButton = element("voicesRow_use_\(marketingVoice)")
        XCTAssertTrue(
            VocelloUIWait.exists(useButton, timeout: 20),
            "marketing clone voice must be enrolled before capture (vocello voices enroll)"
        )
        // The marketing voice sorts last; on the default window it sits below the
        // fold of the Saved Voices list, and a primary action never auto-scrolls.
        XCTAssertTrue(VocelloUIScroll.intoView(useButton, in: element("screen_voices")))
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: useButton, timeout: 20))
        XCTAssertTrue(VocelloUIWait.exists(element("screen_voiceCloning"), timeout: 20))
        XCTAssertTrue(VocelloUIWait.exists(button("studioChip_reference"), timeout: 20))
        let cloneScript = "Some stories are best told slowly, in a voice that remembers "
            + "where it has been."
        replaceScript(with: cloneScript)
        assertReadyToGenerate(mode: .clone)

        let window = app.windows.firstMatch
        let cloneShot = XCTAttachment(screenshot: window.screenshot())
        cloneShot.name = "marketing-voice-cloning"
        cloneShot.lifetime = .keepAlways
        add(cloneShot)

        // Three genuine takes give History authored rows across all modes.
        generateAndWaitForCompletion(mode: .clone, timeout: 360)

        prepare(mode: .custom)
        let customScript = "Welcome to Vocello. Every word you hear was generated "
            + "right here on your Mac, private by design."
        replaceScript(with: customScript)
        generateAndWaitForCompletion(mode: .custom, timeout: 360)

        prepare(mode: .design)
        let designScript = "The harbor opens at first light, and the town wakes slowly "
            + "to the sound of gulls."
        replaceScript(with: designScript)
        generateAndWaitForCompletion(mode: .design, timeout: 360)

        navigate(to: .history)
        // Capture the unfiltered list: assertHistoryRows drives the visible
        // search field, which would leave the shot filtered to one row, so the
        // capture happens first on a raw non-asserting wait for the newest row.
        let newestRow = app.staticTexts.matching(
            NSPredicate(format: "value CONTAINS %@ OR label CONTAINS %@",
                        "The harbor opens", "The harbor opens")
        ).firstMatch
        XCTAssertTrue(
            newestRow.waitForExistence(timeout: 30),
            "the newest authored take must be visible in the unfiltered History list"
        )
        let historyShot = XCTAttachment(screenshot: window.screenshot())
        historyShot.name = "marketing-history"
        historyShot.lifetime = .keepAlways
        add(historyShot)

        // Verification after the capture; these drive the search field.
        assertHistoryRows(matching: "Welcome to Vocello", expected: 1)
        assertHistoryRows(matching: "The harbor opens", expected: 1)
        assertHistoryRows(matching: "Some stories are best told", expected: 1)
    }

    /// Voice Design and Settings captures: an authored brief with its script,
    /// ready to generate, then the model packages in Settings. Both are
    /// window captures; no take is generated.
    func test03_DesignAndSettingsCapture() throws {
        beginSession()
        defer { endSession() }
        navigate(to: .voiceDesign)
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: button("studioChip_voiceBrief"), timeout: 20))
        let brief = element("voiceDesign_voiceDescriptionField")
        let marketingBrief = "A warm, unhurried narrator in her fifties with a soft Irish lilt, "
            + "gentle humor, and a clear, even pace."
        if (brief.value as? String) != marketingBrief {
            XCTAssertTrue(VocelloUITextEntry.replace(in: brief, with: marketingBrief, timeout: 20))
        }
        XCTAssertTrue(VocelloUIWait.value(brief, contains: marketingBrief, timeout: 10))
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: button("voiceBrief_confirm"), timeout: 20))
        let designScript = "The harbor opens at first light, and the town wakes slowly "
            + "to the sound of gulls."
        replaceScript(with: designScript)
        assertReadyToGenerate(mode: .design)
        let window = app.windows.firstMatch
        let designShot = XCTAttachment(screenshot: window.screenshot())
        designShot.name = "marketing-voice-design"
        designShot.lifetime = .keepAlways
        add(designShot)

        openSettingsCategory("modelsFiles")
        XCTAssertTrue(
            VocelloUIWait.exists(element("settings_packageStatus_pro_custom_speed"), timeout: 20)
        )
        let settingsShot = XCTAttachment(screenshot: window.screenshot())
        settingsShot.name = "marketing-model-downloads"
        settingsShot.lifetime = .keepAlways
        add(settingsShot)
    }

    // MARK: - Layout survey (design review evidence)

    /// Every destination at the three widths the app is designed against.
    ///
    /// This is a geometry survey, not a product journey: it generates no take,
    /// so it runs in a couple of minutes and can be repeated after any commit.
    /// It exists because the app had only ever been photographed at whatever
    /// width the scene restored to, which is why every narrow-window defect of
    /// the UI-fidelity plan was found by eye and none by a test.
    func test04_LayoutSurveyCapture() {
        beginSession()
        defer { endSession() }
        reportWindowSizingMechanism()

        // Widest first: an edge drag can only grow the window into space to
        // its right, so growing once and shrinking twice never fights the
        // screen edge.
        for width in [
            VocelloUIWindowFrame.Width.wide,
            VocelloUIWindowFrame.Width.standard,
            VocelloUIWindowFrame.Width.minimum,
        ] {
            captureEveryDestination(at: width, suffix: "")
        }

        captureSheets(at: VocelloUIWindowFrame.Width.standard)
    }

    /// The narrow window under pseudo-localization: the worst case macOS can be
    /// driven to, since it has no Dynamic Type and doubled strings are the only
    /// text-growth axis the platform offers.
    func test05_LayoutSurveyPseudoLocalizedCapture() {
        beginSession(additionalArguments: [
            "-NSDoubleLocalizedStrings", "YES",
            "-NSShowNonLocalizedStrings", "YES",
        ])
        defer { endSession() }
        reportWindowSizingMechanism()

        captureEveryDestination(at: VocelloUIWindowFrame.Width.minimum, suffix: "-pseudo")
    }

    /// Records how the window will be sized before anything is photographed.
    /// Accessibility is exact but needs a grant the runner does not always
    /// hold; the edge drag needs nothing and lands within a few points. Either
    /// is fine, because every capture is named after the width it reached --
    /// what would not be fine is not knowing which one ran.
    private func reportWindowSizingMechanism() {
        VocelloUIWindowFrame.requestTrustIfPermitted()
        print("WINDOW_FRAME diagnosis: \(VocelloUIWindowFrame.diagnosis())")
    }

    private func captureEveryDestination(at width: CGFloat, suffix: String) {
        let frame = VocelloUIWindowFrame.require(app, width: width)
        let window = app.windows.firstMatch
        for screen in VocelloMacScreen.allCases {
            navigate(to: screen)
            // Named for the width the window actually settled at, never the one
            // requested: a capture that misreports its own width is evidence
            // for the wrong question.
            VocelloUIScreenshot.attach(
                window,
                named: "layout-\(screen.rawValue)-\(Int(frame.width))\(suffix)"
            )
        }
    }

    /// The two sheets that open without a system permission prompt. The record
    /// clip sheet is deliberately absent: it asks for the microphone, and the
    /// interruption sentinel never answers a TCC dialog.
    private func captureSheets(at width: CGFloat) {
        let frame = VocelloUIWindowFrame.require(app, width: width)
        let window = app.windows.firstMatch

        navigate(to: .customVoice)
        replaceScript(with: "One line per take, and the batch runs them in order.")
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: element("textInput_batchButton"), timeout: 20))
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: element("textInput_generateButton"), timeout: 20))
        XCTAssertTrue(VocelloUIWait.exists(element("batch_cancelButton"), timeout: 20))
        VocelloUIScreenshot.attach(window, named: "layout-sheet-batch-\(Int(frame.width))")
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: element("batch_cancelButton"), timeout: 20))
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: element("textInput_batchButton"), timeout: 20))

        navigate(to: .voices)
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: element("voices_enrollButton"), timeout: 20))
        XCTAssertTrue(VocelloUIWait.exists(element("voicesEnroll_nameField"), timeout: 20))
        VocelloUIScreenshot.attach(window, named: "layout-sheet-enroll-\(Int(frame.width))")
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: element("voicesEnroll_cancelButton"), timeout: 20))
    }

    /// The state the brief calls the point of the product, and the one the
    /// layout survey could not reach: a finished take.
    ///
    /// Every other capture is a pre-generation empty state, so the two player
    /// cards -- the one in the Studio dock and the one in the sidebar footer --
    /// had no evidence at all, and neither did the space below the Generate
    /// button that a completed take is presumably meant to fill. This generates
    /// one real take through the genuine controls and photographs the result at
    /// the narrow and default widths.
    func test06_PostGenerationCapture() {
        beginSession()
        defer { endSession() }
        reportWindowSizingMechanism()

        prepare(mode: .custom)
        replaceScript(with: "Welcome to Vocello. Every word you hear was generated "
            + "right here on your Mac, private by design.")
        generateAndWaitForCompletion(mode: .custom, timeout: 360)

        for width in [
            VocelloUIWindowFrame.Width.standard,
            VocelloUIWindowFrame.Width.minimum,
        ] {
            let frame = VocelloUIWindowFrame.require(app, width: width)
            let window = app.windows.firstMatch
            VocelloUIScreenshot.attach(window, named: "layout-customVoice-take-\(Int(frame.width))")
            navigate(to: .history)
            VocelloUIScreenshot.attach(window, named: "layout-history-take-\(Int(frame.width))")
            navigate(to: .customVoice)
        }
    }
}
