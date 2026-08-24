import Foundation
import XCTest

/// Physical-device proof that the visible Built-in Voice request reaches the
/// engine unchanged. Script bytes live only in the UI-test process and are
/// entered through the genuine composer; the app receives no seeded UI state.
@MainActor
final class VocelloiOSStartupParityUITests: VocelloiOSUITestCase {
    func testVivianCalmStrongEnglishRequestReceiptParity() throws {
        let environment = ProcessInfo.processInfo.environment
        let runID = try XCTUnwrap(
            environment["QVOICE_IOS_STARTUP_PARITY_RUN_ID"].flatMap { $0.isEmpty ? nil : $0 }
        )
        let script = try XCTUnwrap(
            environment["QVOICE_IOS_STARTUP_PARITY_SCRIPT"].flatMap { $0.isEmpty ? nil : $0 }
        )

        beginSession(
            additionalEnvironment: ["QVOICE_IOS_DEVICE_RUN_ID": runID],
            additionalArguments: [
                "-outputDirectory", "~/Library/Caches/Vocello/diagnostics/\(runID)/outputs",
            ]
        )
        defer { endSession() }

        assertBuiltInModelReady()
        let originalVariation = selectBalancedVariationThroughVisibleSettings()
        defer { restoreVariationThroughVisibleSettings(originalVariation) }
        prepare(mode: .custom)
        selectVivian()
        selectCalmStrong()
        selectEnglish()

        assertChip("studioChip_voice", contains: "Vivian")
        assertChip("studioChip_delivery", contains: "Calm")
        assertChip("studioChip_language", contains: "English")
        replaceScript(with: script)
        let generationID = generateAndWaitForCompletedPlayer(timeout: 360)
        VocelloUIScreenshot.attach(app, named: "ios-startup-parity-vivian-calm-strong-english")
        print(
            "VOCELLO-STARTUP-PARITY-UI-MANIFEST "
                + "runID=\(runID) generationID=\(generationID) "
                + "speakerID=vivian deliveryID=calm.strong language=english "
                + "variation=balanced streaming=true seedSource=generated"
        )
    }

    private func assertBuiltInModelReady() {
        openVoiceModels()
        let status = element("iosModelStatus_pro_custom")
        XCTAssertTrue(VocelloUIWait.exists(status, timeout: 60))
        XCTAssertTrue(VocelloUIWait.value(status, contains: "Ready", timeout: 20))
        XCTAssertTrue(VocelloUIWait.exists(element("iosModelDelete_pro_custom"), timeout: 60))
        leaveVoiceModels()
    }

    private func selectBalancedVariationThroughVisibleSettings() -> String {
        select(tab: .settings)
        let picker = element("iosSettings_variationRow")
        XCTAssertTrue(VocelloUIWait.exists(picker, timeout: 20))
        let original = (picker.value as? String) ?? "Expressive"
        if !original.localizedCaseInsensitiveContains("Balanced") {
            chooseVariation(rawValue: "balanced", displayName: "Balanced")
        }
        XCTAssertTrue(VocelloUIWait.value(picker, contains: "Balanced", timeout: 20))
        select(tab: .studio)
        return original
    }

    private func restoreVariationThroughVisibleSettings(_ original: String) {
        guard app.state == .runningForeground else { return }
        let choices = [
            (rawValue: "expressive", displayName: "Expressive"),
            (rawValue: "balanced", displayName: "Balanced"),
            (rawValue: "consistent", displayName: "Consistent"),
        ]
        guard let choice = choices.first(where: {
            original.localizedCaseInsensitiveContains($0.displayName)
        }), choice.rawValue != "balanced" else { return }
        select(tab: .settings)
        chooseVariation(rawValue: choice.rawValue, displayName: choice.displayName)
    }

    private func chooseVariation(rawValue: String, displayName: String) {
        let picker = element("iosSettings_variationRow")
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: picker, timeout: 20))
        let identifiedOption = element("iosSettings_variationOption_\(rawValue)")
        let labelledOption = app.buttons[displayName]
        XCTAssertTrue(
            VocelloUIWait.condition("\(displayName) variation option", timeout: 20) {
                (identifiedOption.exists && identifiedOption.isHittable)
                    || (labelledOption.exists && labelledOption.isHittable)
            }
        )
        let option = identifiedOption.exists ? identifiedOption : labelledOption
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: option, timeout: 20))
        XCTAssertTrue(VocelloUIWait.value(picker, contains: displayName, timeout: 20))
    }

    private func selectVivian() {
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: element("studioChip_voice"), timeout: 20))
        let row = reveal("voicePickerRow_vivian")
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: row, timeout: 20))
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: element("voicePicker_confirm"), timeout: 20))
        XCTAssertTrue(VocelloUIWait.disappears(element("voicePicker_confirm"), timeout: 20))
    }

    private func selectCalmStrong() {
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: element("studioChip_delivery"), timeout: 20))
        let calm = reveal("deliveryPickerPreset_calm")
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: calm, timeout: 20))
        // The intensity row is deliberately retired: each visible preset now
        // resolves to its measured strong instruction. Selecting Calm therefore
        // produces the canonical `calm.strong` delivery cell without a second
        // UI interaction.
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: element("deliveryPicker_confirm"), timeout: 20))
        XCTAssertTrue(VocelloUIWait.disappears(element("deliveryPicker_confirm"), timeout: 20))
    }

    private func selectEnglish() {
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: element("studioChip_language"), timeout: 20))
        let english = reveal("languagePicker_english")
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: english, timeout: 20))
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: element("languagePicker_confirm"), timeout: 20))
        XCTAssertTrue(VocelloUIWait.disappears(element("languagePicker_confirm"), timeout: 20))
    }

    private func reveal(_ identifier: String) -> XCUIElement {
        let target = element(identifier)
        for _ in 0..<12 {
            if target.exists && target.isHittable { return target }
            app.swipeUp()
        }
        XCTAssertTrue(target.exists && target.isHittable, "Could not reveal \(identifier)")
        return target
    }

    private func assertChip(_ identifier: String, contains value: String) {
        let chip = element(identifier)
        XCTAssertTrue(VocelloUIWait.exists(chip, timeout: 20))
        XCTAssertTrue(
            VocelloUIWait.condition("\(identifier) to expose \(value)", timeout: 20) {
                let accessibilityValue = (chip.value as? String) ?? ""
                return chip.label.localizedCaseInsensitiveContains(value)
                    || accessibilityValue.localizedCaseInsensitiveContains(value)
            }
        )
    }
}
