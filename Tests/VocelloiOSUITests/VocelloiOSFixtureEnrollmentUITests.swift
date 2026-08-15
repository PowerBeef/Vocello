import Foundation
@preconcurrency import XCTest

/// Explicit, opt-in enrollment of the benchmark clone voice through the genuine visible
/// Files-import flow. This method is selected directly by
/// `scripts/ui_test.sh ios enroll-clone-fixture`; smoke, benchmarks, CI, and release never
/// execute it. The reference WAV and its transcript sidecar must already sit in the app's
/// Documents directory (devicectl appDataContainer copy) — the import picker opens there,
/// the naming sheet prefills the name from the filename and the transcript from the
/// sidecar, and enrollment lands in the canonical saved-voice store. Idempotent: passes
/// immediately when the exact voice is already enrolled.
@MainActor
final class VocelloiOSFixtureEnrollmentUITests: VocelloiOSUITestCase {
    func testEnrollBenchmarkCloneFixtureFromDocuments() {
        beginSession()
        defer { endSession() }

        let voiceName = VocelloUIBenchMatrix.cloneVoiceID
        select(tab: .voices)
        let savedVoice = element("voicesRow_saved_\(voiceName)")
        // Idempotency probe: the shared waits record a failure on timeout, so an
        // absent voice (the normal starting state) must use the raw non-asserting wait.
        if savedVoice.waitForExistence(timeout: 10) {
            VocelloUIScreenshot.attach(app, named: "ios-clone-fixture-already-enrolled")
            return
        }

        let importButton = element("voices_importAudioFile")
        XCTAssertTrue(VocelloUIWait.exists(importButton, timeout: 20))
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: importButton, timeout: 20))

        // The system document picker opens in the app's own Documents directory
        // (`fileDialogDefaultDirectory`). System UI exposes no app-owned identifiers,
        // so the staged reference is matched by its visible file name. The transcript
        // sidecar shares the same display name but is greyed out by the audio content
        // filter, so only an enabled item may be tapped.
        let pickerItem = app.cells.matching(
            NSPredicate(format: "label CONTAINS %@ AND isEnabled == 1", voiceName)
        ).firstMatch
        XCTAssertTrue(
            VocelloUIWait.exists(pickerItem, timeout: 30),
            "Staged reference \(voiceName).wav must be selectable in the document picker; push it with devicectl first"
        )
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: pickerItem, timeout: 20))

        // Import routes into the naming sheet with the name prefilled from the file
        // name and the transcript prefilled from the .txt sidecar.
        let nameField = element("saveVoice_nameField")
        XCTAssertTrue(VocelloUIWait.exists(nameField, timeout: 30))
        XCTAssertEqual(
            nameField.value as? String,
            voiceName,
            "The naming sheet must prefill the exact benchmark voice name from the imported file"
        )
        let transcriptEditor = element("saveVoice_transcriptEditor")
        XCTAssertTrue(VocelloUIWait.exists(transcriptEditor, timeout: 10))
        let transcriptValue = (transcriptEditor.value as? String) ?? ""
        XCTAssertFalse(
            transcriptValue.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
            "The transcript sidecar must prefill transcript-backed conditioning; audio-only x-vector would change the benchmark identity"
        )
        VocelloUIScreenshot.attach(app, named: "ios-clone-fixture-naming-sheet")

        let saveButton = element("saveVoice_saveButton")
        XCTAssertTrue(VocelloUIWait.exists(saveButton, timeout: 10))
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: saveButton, timeout: 20))

        // The canonical Voice Design reference passes QC on macOS; if the iOS QC
        // path surfaces its keep/discard warning, keeping is the fixture intent.
        // Non-asserting wait: no warning is the expected happy path.
        let keepDespiteWarning = element("recordVoice_keepDespiteWarning")
        if keepDespiteWarning.waitForExistence(timeout: 5) {
            XCTAssertTrue(VocelloUIPrimaryAction.perform(on: keepDespiteWarning, timeout: 20))
        }

        // Enrollment hands off to Studio Clone; the durable proof is the saved row.
        select(tab: .voices)
        XCTAssertTrue(
            VocelloUIWait.exists(savedVoice, timeout: 60),
            "The enrolled benchmark clone voice must appear in Saved Voices"
        )
        VocelloUIScreenshot.attach(app, named: "ios-clone-fixture-enrolled")
    }
}
