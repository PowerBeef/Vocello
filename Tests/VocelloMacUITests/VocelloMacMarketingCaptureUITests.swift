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

        // Then select Calm from the open menu and Subtle intensity.
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: calm, timeout: 10))
        let intensity = element("delivery_intensityPicker")
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: intensity, timeout: 20))
        let subtle = app.menuItems["Subtle"].firstMatch
        XCTAssertTrue(VocelloUIWait.exists(subtle, timeout: 10))
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: subtle, timeout: 10))

        assertReadyToGenerate(mode: .custom)

        // Window capture for the hero asset.
        let windowShot = XCTAttachment(screenshot: window.screenshot())
        windowShot.name = "marketing-custom-voice"
        windowShot.lifetime = .keepAlways
        add(windowShot)
    }
}
