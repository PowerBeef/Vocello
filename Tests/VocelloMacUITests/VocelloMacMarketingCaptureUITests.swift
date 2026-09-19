import CoreGraphics
import XCTest

/// Screenshot captures: the marketing assets for the website and README
/// (`test01`-`test03`), and the layout survey the design review reads
/// (`test04`-`test05`), which photographs every destination at each width the
/// app is designed against.
///
/// Not part of any acceptance lane and never run by `scripts/ui_test.sh`:
/// invoke explicitly with
/// `-only-testing:VocelloMacUITests/VocelloMacMarketingCaptureUITests`.
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
    /// --audio <reference wav> --transcript "<the reference's real transcript>"`.
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
