import Foundation
@preconcurrency import XCTest

/// Explicit physical-device acceptance for F-01 and ICI-4. This test begins in
/// Studio Clone, imports a deliberately throwaway reference through the visible
/// Files picker, waits for automatic on-device transcription, commits it as a
/// permanent saved voice, completes one Clone take, previews the saved row, and
/// removes exactly that row through the production confirmation flow. It is
/// selected only by `scripts/ui_test.sh ios saved-voice-lifecycle`.
@MainActor
final class VocelloiOSSavedVoiceLifecycleUITests: VocelloiOSUITestCase {
    private let voiceName = "ICI Direct Clone Import"

    func testImportPreviewHandoffAndDeleteSavedVoice() {
        beginSession()
        defer { endSession() }

        select(tab: .voices)
        deleteThrowawayVoiceIfPresent()

        ensureCloneConsentEnabled()
        select(mode: .clone)
        let referenceChip = element("studioChip_reference")
        XCTAssertTrue(VocelloUIWait.exists(referenceChip, timeout: 20))
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: referenceChip, timeout: 20))

        let importButton = element("referenceClip_importAudioFile")
        XCTAssertTrue(VocelloUIWait.exists(importButton, timeout: 20))
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: importButton, timeout: 20))

        let pickerItem = app.cells.matching(
            NSPredicate(format: "label CONTAINS %@ AND isEnabled == 1", voiceName)
        ).firstMatch
        XCTAssertTrue(
            VocelloUIWait.exists(pickerItem, timeout: 30),
            "Stage \(voiceName).wav without a matching .txt sidecar in the app Documents directory first"
        )
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: pickerItem, timeout: 20))

        let nameField = element("saveVoice_nameField")
        XCTAssertTrue(VocelloUIWait.exists(nameField, timeout: 30))
        XCTAssertEqual(nameField.value as? String, voiceName)

        let transcriptionStatus = element("saveVoice_transcriptionStatus")
        let transcriptEditor = element("saveVoice_transcriptEditor")
        let saveButton = element("saveVoice_saveButton")
        XCTAssertTrue(VocelloUIWait.exists(transcriptionStatus, timeout: 30))
        XCTAssertTrue(VocelloUIWait.exists(transcriptEditor, timeout: 20))
        XCTAssertTrue(
            VocelloUIWait.condition("automatic transcript to become editable and nonempty", timeout: 180) {
                guard let value = transcriptEditor.value as? String else { return false }
                return !value.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                    && saveButton.exists
                    && saveButton.isEnabled
            }
        )
        XCTAssertTrue(
            VocelloUIWait.label(transcriptionStatus, contains: "Automatic transcript ready", timeout: 20),
            "A no-sidecar import must finish through the existing automatic on-device transcriber"
        )
        VocelloUIScreenshot.attach(app, named: "ios-clone-import-transcript-ready")
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: saveButton, timeout: 20))

        // A soft QC warning is a review decision, never a pre-committed voice.
        let keepDespiteWarning = element("recordVoice_keepDespiteWarning")
        if keepDespiteWarning.waitForExistence(timeout: 5) {
            XCTAssertTrue(VocelloUIPrimaryAction.perform(on: keepDespiteWarning, timeout: 20))
        }

        XCTAssertTrue(
            VocelloUIWait.condition("saved import to return to Studio Clone", timeout: 60) {
                let clone = self.element("generateSection_clone")
                return clone.exists && clone.isSelected
            }
        )
        XCTAssertTrue(VocelloUIWait.label(referenceChip, contains: voiceName, timeout: 30))

        replaceScript(with: "This imported reference now powers a private voice clone on this iPhone.")
        _ = generateAndWaitForCompletedPlayer(timeout: 300)
        VocelloUIScreenshot.attach(app, named: "ios-clone-import-generated")

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

        // The ordinary row handoff must still select this exact committed reference.
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: savedRow, timeout: 20))
        XCTAssertTrue(
            VocelloUIWait.condition("throwaway voice to hand off to Studio Clone", timeout: 30) {
                let clone = self.element("generateSection_clone")
                return clone.exists && clone.isSelected
            }
        )
        XCTAssertTrue(VocelloUIWait.label(referenceChip, contains: voiceName, timeout: 20))

        select(tab: .voices)
        deleteThrowawayVoiceIfPresent()
        XCTAssertTrue(VocelloUIWait.disappears(savedRow, timeout: 60))

        select(tab: .studio)
        select(mode: .clone)
        XCTAssertFalse(
            referenceChip.label.localizedCaseInsensitiveContains(voiceName),
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
