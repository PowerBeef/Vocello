import XCTest

/// Marketing screenshot captures for the README and website (iOS studio).
///
/// Not part of any acceptance lane and never run by `scripts/ui_test.sh`:
/// invoke explicitly with
/// `-only-testing:VocelloiOSUITests/VocelloiOSMarketingCaptureUITests`.
/// Drives only genuine visible controls (the same identifiers the smoke lane
/// observes), attaches captures for asset export, and publishes nothing.
/// Script copy must follow website/PRODUCT.md rules: local not offline, no em
/// dashes, current preset names only.
final class VocelloiOSMarketingCaptureUITests: VocelloiOSUITestCase {
    func test01_StudioCapture() {
        beginSession()
        defer { endSession() }

        assertVisibleModelReadiness()
        prepare(mode: .custom)
        replaceScript(with: "Vocello is now in your pocket.")

        // Setup state: script + ready chips + Generate enabled.
        let generate = element("textInput_generateButton")
        XCTAssertTrue(VocelloUIWait.enabled(generate, timeout: 60))
        let setupShot = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        setupShot.name = "marketing-ios-studio-setup"
        setupShot.lifetime = .keepAlways
        add(setupShot)

        // Completed state: the inline player over the same script shows the
        // app alive rather than an empty studio.
        _ = generateAndWaitForCompletedPlayer(timeout: 300)
        let playerShot = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        playerShot.name = "marketing-ios-studio-player"
        playerShot.lifetime = .keepAlways
        add(playerShot)
    }
}
