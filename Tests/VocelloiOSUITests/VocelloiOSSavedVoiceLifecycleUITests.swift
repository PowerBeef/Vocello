import Foundation
@preconcurrency import XCTest

/// Explicit physical-device acceptance for F-01. This test imports a
/// deliberately throwaway reference through the visible Files picker, proves
/// the committed row can preview and hand off to Clone, then removes exactly
/// that row through the production confirmation flow. It is selected only by
/// `scripts/ui_test.sh ios saved-voice-lifecycle`.
@MainActor
final class VocelloiOSSavedVoiceLifecycleUITests: VocelloiOSUITestCase {
    private let voiceName = "F01 Saved Voice Lifecycle"

    func testImportPreviewHandoffAndDeleteSavedVoice() {
        beginSession()
        defer { endSession() }

        select(tab: .voices)
        deleteThrowawayVoiceIfPresent()

        let importButton = element("voices_importAudioFile")
        XCTAssertTrue(VocelloUIWait.exists(importButton, timeout: 20))
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: importButton, timeout: 20))

        let pickerItem = app.cells.matching(
            NSPredicate(format: "label CONTAINS %@ AND isEnabled == 1", voiceName)
        ).firstMatch
        XCTAssertTrue(
            VocelloUIWait.exists(pickerItem, timeout: 30),
            "Stage \(voiceName).wav and its optional .txt sidecar in the app Documents directory first"
        )
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: pickerItem, timeout: 20))

        let nameField = element("saveVoice_nameField")
        XCTAssertTrue(VocelloUIWait.exists(nameField, timeout: 30))
        XCTAssertEqual(nameField.value as? String, voiceName)
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: element("saveVoice_saveButton"), timeout: 20))

        // A soft QC warning is a review decision, never a pre-committed voice.
        let keepDespiteWarning = element("recordVoice_keepDespiteWarning")
        if keepDespiteWarning.waitForExistence(timeout: 5) {
            XCTAssertTrue(VocelloUIPrimaryAction.perform(on: keepDespiteWarning, timeout: 20))
        }

        select(tab: .voices)
        let savedRow = element("voicesRow_saved_\(voiceName)")
        XCTAssertTrue(VocelloUIWait.exists(savedRow, timeout: 60))

        let preview = element("voicesPreview_saved_\(voiceName)")
        XCTAssertTrue(VocelloUIWait.exists(preview, timeout: 20))
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: preview, timeout: 20))
        let closePlayer = element("iosPlayer_close")
        XCTAssertTrue(VocelloUIWait.exists(closePlayer, timeout: 30))
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: closePlayer, timeout: 20))
        XCTAssertTrue(VocelloUIWait.disappears(closePlayer, timeout: 20))

        // The ordinary row handoff must select this exact committed reference.
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: savedRow, timeout: 20))
        XCTAssertTrue(
            VocelloUIWait.condition("throwaway voice to hand off to Studio Clone", timeout: 30) {
                let clone = self.element("generateSection_clone")
                return clone.exists && clone.isSelected
            }
        )
        XCTAssertTrue(VocelloUIWait.label(element("studioChip_reference"), contains: voiceName, timeout: 20))

        select(tab: .voices)
        deleteThrowawayVoiceIfPresent()
        XCTAssertTrue(VocelloUIWait.disappears(savedRow, timeout: 60))

        select(tab: .studio)
        select(mode: .clone)
        XCTAssertFalse(
            element("studioChip_reference").label.localizedCaseInsensitiveContains(voiceName),
            "Deleting the selected voice must clear the matching Studio handoff and draft"
        )
        VocelloUIScreenshot.attach(app, named: "ios-saved-voice-lifecycle-complete")
    }

    private func deleteThrowawayVoiceIfPresent() {
        let row = element("voicesRow_saved_\(voiceName)")
        guard row.waitForExistence(timeout: 5) else { return }

        let menu = element("voicesRowMenu_\(voiceName)")
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: menu, timeout: 20))
        let delete = element("voicesDelete_\(voiceName)")
        XCTAssertTrue(VocelloUIWait.exists(delete, timeout: 20))
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: delete, timeout: 20))

        let confirm = element("voicesDeleteConfirm_\(voiceName)")
        XCTAssertTrue(VocelloUIWait.exists(confirm, timeout: 20))
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: confirm, timeout: 20))
        XCTAssertTrue(VocelloUIWait.disappears(row, timeout: 60))
    }
}
