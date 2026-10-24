import Foundation
import XCTest

/// RF-15 rows on the installed distribution candidate (the processed TestFlight
/// build), selected by `scripts/ui_test.sh ios smoke --preinstalled-candidate
/// <verified-release-dir> --scenario <row>`. Black-box: no diagnostics, telemetry
/// or container access, so each row proves only what its visible UI shows. The
/// benchmark clone voice is a fixture the phone already holds; nothing here creates it.
@MainActor
final class VocelloiOSCandidateJourneyUITests: VocelloiOSUITestCase {
    /// A take in each mode in English and in French, each language chosen with
    /// Studio's own picker. Every mode's original language is read before anything
    /// changes and put back on every exit path.
    func testTakesInEachModeAndLanguage() throws {
        try beginCandidateSession()
        defer { endSession() }
        assertVisibleModelReadiness()
        ensureCloneConsentEnabled()
        for mode in VocelloUIBenchMatrix.Mode.allCases {
            select(mode: mode)
            let original = try XCTUnwrap(selectedStudioLanguage(), "Studio \(mode.rawValue) must show one selected language")
            registerSessionRestore { [unowned self] in
                self.select(mode: mode)
                self.chooseStudioLanguage(original)
            }
        }
        let scripts = [
            ("english", "The morning train crossed the valley while the fog lifted slowly over the river."),
            ("french", "Le train du matin traversait la vallée pendant que le brouillard se levait sur la rivière."),
        ]
        for mode in VocelloUIBenchMatrix.Mode.allCases {
            prepare(mode: mode)
            for (language, script) in scripts {
                chooseStudioLanguage(language)
                replaceScript(with: script)
                XCTAssertFalse(generateAndWaitForCompletedPlayer(timeout: 300).isEmpty)
                VocelloUIScreenshot.attach(app, named: "candidate-take-\(mode.rawValue)-\(language)")
                dismissCompletedPlayerAndAssertGenerateReady()
            }
        }
    }

    /// F-01: a voice saved from a Design take, then deleted from Voices. The fixed
    /// throwaway name lets a later run remove what a failed one left behind.
    func testDesignedVoiceSaveAndDelete() throws {
        try beginCandidateSession()
        defer { endSession() }
        ensureCloneConsentEnabled()
        deleteThrowawayVoiceIfPresent()
        prepare(mode: .design)
        replaceScript(with: "A calm voice for a quick candidate check, saved and then removed.")
        XCTAssertFalse(generateAndWaitForCompletedPlayer(timeout: 300).isEmpty)
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: element("studio_inlinePlayer_saveAsVoice"), timeout: 20))

        let nameField = element("saveVoice_nameField")
        XCTAssertTrue(VocelloUIWait.exists(nameField, timeout: 30))
        XCTAssertTrue(VocelloUITextEntry.replace(in: nameField, with: Self.throwawayVoiceName, timeout: 20))
        XCTAssertTrue(VocelloUIWait.condition("the voice name to read exactly", timeout: 15) {
            (nameField.value as? String) == Self.throwawayVoiceName
        })
        // The keyboard covers the sheet's last control, Save.
        if app.keyboards.firstMatch.exists {
            nameField.typeText("\n")
            XCTAssertTrue(VocelloUIWait.condition("save-voice keyboard to dismiss", timeout: 15) {
                !self.app.keyboards.firstMatch.exists
            })
        }
        // Save waits for on-device recognition; a clip it cannot transcribe is
        // saved audio-only through the sheet's own choice.
        let save = element("saveVoice_saveButton")
        let audioOnly = element("saveVoice_useAudioOnlyButton")
        XCTAssertTrue(VocelloUIWait.condition("recognition to resolve", timeout: 180) {
            (save.exists && save.isEnabled) || audioOnly.exists
        })
        if !save.isEnabled, audioOnly.exists {
            VocelloUIScroll.reveal(audioOnly, in: app)
            XCTAssertTrue(VocelloUIPrimaryAction.perform(on: audioOnly, timeout: 20))
        }
        VocelloUIScroll.reveal(save, in: app)
        XCTAssertTrue(VocelloUIWait.enabled(save, timeout: 20))
        registerSessionRestore { [unowned self] in self.deleteThrowawayVoiceIfPresent() }
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: save, timeout: 20))
        // A reference outside the recommended range asks Keep or Discard once the
        // candidate is prepared, which can take a while.
        let keep = element("voicesEnroll_keepDespiteWarning")
        XCTAssertTrue(VocelloUIWait.condition("the save to finish or ask about the reference", timeout: 60) {
            !nameField.exists || keep.exists
        })
        if keep.exists {
            XCTAssertTrue(VocelloUIPrimaryAction.perform(on: keep, timeout: 20))
        }
        XCTAssertTrue(VocelloUIWait.disappears(nameField, timeout: 60))

        guard revealSavedVoiceControls(named: Self.throwawayVoiceName, timeout: 60) != nil else {
            XCTFail("The saved designed voice did not expose an activatable row and menu")
            return
        }
        VocelloUIScreenshot.attach(app, named: "candidate-designed-voice-saved")
        clearVoicesSearch()
        XCTAssertTrue(deleteThrowawayVoiceIfPresent(), "The saved voice must delete through its menu")
        select(tab: .studio)
    }

    private static let throwawayVoiceName = "RF15 Candidate Voice"

    @discardableResult
    private func deleteThrowawayVoiceIfPresent() -> Bool {
        let name = Self.throwawayVoiceName
        guard let controls = revealSavedVoiceControls(named: name, timeout: 10) else { return false }
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: controls.menu, timeout: 20))
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: element("voicesDelete_\(name)"), timeout: 20))
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: element("voicesDeleteConfirm_\(name)"), timeout: 20))
        let deleted = VocelloUIWait.disappears(controls.row, timeout: 60)
        XCTAssertTrue(deleted)
        clearVoicesSearch()
        return deleted
    }

    /// DA-04 (E4-01): a one-token script completes in every mode.
    func testOneWordScript() throws {
        try beginCandidateSession()
        defer { endSession() }
        ensureCloneConsentEnabled()
        for mode in VocelloUIBenchMatrix.Mode.allCases {
            prepare(mode: mode)
            replaceScript(with: "Hi")
            XCTAssertFalse(generateAndWaitForCompletedPlayer(timeout: 300).isEmpty)
            VocelloUIScreenshot.attach(app, named: "candidate-one-word-\(mode.rawValue)")
            dismissCompletedPlayerAndAssertGenerateReady()
        }
    }

    /// AUD-02: a clip recorded from Clone's reference plays to its end.
    func testRecordThenPlay() throws {
        try beginCandidateSession()
        defer { endSession() }
        recordThenPlayReview()
    }

    func testLongFormAndSegmentRegeneration() throws {
        try beginCandidateSession()
        defer { endSession() }
        runLongFormProjectJourney()
    }

    /// XCTest's accessibility audit on Studio, Settings and the purchase sheet, then
    /// Studio and Settings at the largest accessibility text size. Every issue is
    /// collected before the row fails, so one run lists them all. The hand VoiceOver
    /// pass stays a maintainer row (RF-15, 2026-10-24).
    func testAccessibilityAuditsAndLargestText() throws {
        var issues: [String] = []
        try beginCandidateSession()
        select(tab: .studio)
        issues += try accessibilityIssues(on: "studio")
        openSettingsRoot()
        issues += try accessibilityIssues(on: "settings")
        let purchaseRow = element("iosSettings_exportPurchaseRow")
        XCTAssertTrue(revealSettingsElement(purchaseRow, swipingUp: true))
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: purchaseRow, timeout: 20))
        let close = element("exportPurchase_close")
        XCTAssertTrue(VocelloUIWait.exists(close, timeout: 30))
        VocelloUIScreenshot.attach(app, named: "candidate-purchase-sheet")
        issues += try accessibilityIssues(on: "purchase-sheet")
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: close, timeout: 20))
        XCTAssertTrue(VocelloUIWait.disappears(close, timeout: 20))
        endSession()

        // A pinned size is a single layout, so XCTest's Dynamic Type audit, which
        // varies it, would flag every label; check clipping at the size instead.
        try beginCandidateSession(additionalArguments: [
            "-UIPreferredContentSizeCategoryName", "UICTContentSizeCategoryAccessibilityXXXL",
        ])
        defer { endSession() }
        for mode in VocelloUIBenchMatrix.Mode.allCases {
            select(mode: mode)
            XCTAssertTrue(VocelloUIWait.exists(element("textInput_generateButton"), timeout: 20))
            VocelloUIScreenshot.attach(app, named: "candidate-ax-xxxl-studio-\(mode.rawValue)")
            issues += try accessibilityIssues(on: "studio-\(mode.rawValue)-ax-xxxl", for: .textClipped)
        }
        openSettingsRoot()
        VocelloUIScreenshot.attach(app, named: "candidate-ax-xxxl-settings")
        issues += try accessibilityIssues(on: "settings-ax-xxxl", for: .textClipped)
        openSettingsPage(for: "iosSettings_autoPlayToggle")
        let autoplay = element("iosSettings_autoPlayToggle")
        XCTAssertTrue(revealSettingsElement(autoplay, swipingUp: false))
        XCTAssertGreaterThanOrEqual(autoplay.frame.height + 0.01, 44)
        VocelloUIScreenshot.attach(app, named: "candidate-ax-xxxl-settings-audio")
        issues += try accessibilityIssues(on: "settings-audio-ax-xxxl", for: .textClipped)

        let report = XCTAttachment(string: issues.isEmpty ? "No issues" : issues.joined(separator: "\n"))
        report.name = "candidate-accessibility-issues.txt"
        report.lifetime = .keepAlways
        add(report)
        XCTAssertTrue(issues.isEmpty, "Accessibility audit issues:\n" + issues.joined(separator: "\n"))
    }

    private func accessibilityIssues(
        on surface: String,
        for types: XCUIAccessibilityAuditType = .all
    ) throws -> [String] {
        var found: [String] = []
        try app.performAccessibilityAudit(for: types) { issue in
            let identifier = issue.element?.identifier ?? ""
            found.append("\(surface): \(issue.compactDescription) [\(identifier.isEmpty ? "-" : identifier)]")
            return true
        }
        return found
    }

    /// The language Studio's picker shows selected for the current mode. The picker
    /// is an in-app panel whose list scrolls both ways (only its grabber and header
    /// drag it closed), and a detected language is repeated above "All languages",
    /// so every row is read top to bottom and exactly one language must be selected.
    private func selectedStudioLanguage() -> String? {
        openLanguagePicker()
        scrollLanguagePickerToTop()
        var selected = Set<String>()
        var lastSignature = ""
        for _ in 0..<12 {
            let rows = visibleLanguageRows()
            selected.formUnion(rows.filter(\.isSelected).map(\.identifier))
            let signature = rows.map(\.identifier).joined(separator: ",")
            if signature == lastSignature { break }
            lastSignature = signature
            rows.last?.swipeUp()
        }
        closeLanguagePicker()
        guard selected.count == 1, let row = selected.first else { return nil }
        return String(row.dropFirst("languagePicker_".count))
    }

    /// Chooses the take language through Studio's chip and picker.
    private func chooseStudioLanguage(_ language: String) {
        openLanguagePicker()
        scrollLanguagePickerToTop()
        let option = element("languagePicker_\(language)")
        for _ in 0..<12 where !(option.exists && option.isHittable) {
            visibleLanguageRows().last?.swipeUp()
        }
        XCTAssertTrue(option.exists && option.isHittable, "The picker must list \(language)")
        if !option.isSelected {
            XCTAssertTrue(VocelloUIPrimaryAction.perform(on: option, timeout: 20))
        }
        XCTAssertTrue(VocelloUIWait.condition("language \(language) to be selected", timeout: 10) {
            option.exists && option.isSelected
        })
        closeLanguagePicker()
    }

    private func visibleLanguageRows() -> [XCUIElement] {
        app.buttons.matching(NSPredicate(
            format: "identifier BEGINSWITH %@ AND identifier != %@", "languagePicker_", "languagePicker_confirm"
        )).allElementsBoundByIndex.filter { $0.exists && $0.isHittable }
    }

    private func scrollLanguagePickerToTop() {
        var lastSignature = ""
        for _ in 0..<12 {
            let rows = visibleLanguageRows()
            let signature = rows.map(\.identifier).joined(separator: ",")
            if signature == lastSignature { return }
            lastSignature = signature
            rows.first?.swipeDown()
        }
    }

    private func openLanguagePicker() {
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: element("studioChip_language"), timeout: 20))
        XCTAssertTrue(VocelloUIWait.exists(element("languagePicker_confirm"), timeout: 20))
    }

    private func closeLanguagePicker() {
        let confirm = element("languagePicker_confirm")
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: confirm, timeout: 20))
        XCTAssertTrue(VocelloUIWait.disappears(confirm, timeout: 20))
    }
}
