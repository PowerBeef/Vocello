import XCTest

/// Marketing screenshot captures for the website and README.
///
/// Not part of any acceptance lane and never run by `scripts/ui_test.sh`:
/// invoke explicitly with
/// `-only-testing:VocelloMacUITests/VocelloMacMarketingCaptureUITests`.
/// The journey drives only genuine visible controls (the same identifiers the
/// smoke lane observes), attaches captures for asset export, and publishes
/// nothing. Script copy must follow website/PRODUCT.md rules: local not
/// offline, no em dashes, current preset names only.
final class VocelloMacMarketingCaptureUITests: VocelloMacUITestCase {
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
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: useButton, timeout: 20))
        XCTAssertTrue(VocelloUIWait.exists(element("screen_voiceCloning"), timeout: 20))
        XCTAssertTrue(VocelloUIWait.exists(element("voiceCloning_activeReference"), timeout: 20))
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
}
