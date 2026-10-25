import Foundation
import XCTest

/// RF-15 rows on the installed distribution candidate (the processed TestFlight
/// build), selected by `scripts/ui_test.sh ios smoke --preinstalled-candidate
/// <verified-release-dir> --scenario <row>`. Black-box: no diagnostics, telemetry
/// or container access, so each row proves only what its visible UI shows. The
/// benchmark clone voice is a fixture the phone already holds; only the clone-voice
/// row creates it, from a Voice Design take, after a fresh install.
@MainActor
final class VocelloiOSCandidateJourneyUITests: VocelloiOSUITestCase {
    /// RF-15 first launch (`--scenario first-launch`, run before the other rows on a fresh
    /// install): onboarding through its own pages, then the three shipping models installed
    /// from Voice Models. Nothing here raises a permission prompt, so it runs unattended.
    /// Everything goes through visible controls and nothing is staged in the app's container.
    /// On a phone already set up it confirms each step instead of repeating it, and the kept
    /// `first-launch-outcome` attachment records which, so only a run that walked onboarding
    /// counts as first-launch evidence.
    func testFirstLaunchOnboardingAndModels() throws {
        try beginCandidateSession(firstLaunch: true)
        defer { endSession() }
        let walkedOnboarding = didWalkFirstLaunch
        VocelloUIScreenshot.attach(app, named: walkedOnboarding
            ? "candidate-first-launch-studio" : "candidate-first-launch-already-set-up")
        let started = installMissingShippingModels()
        assertVisibleModelReadiness()
        let downloaded = started.map { "\"\($0)\"" }.joined(separator: ", ")
        let outcome = XCTAttachment(
            string: "{\"walkedOnboarding\": \(walkedOnboarding), \"modelsDownloaded\": [\(downloaded)]}"
        )
        outcome.name = "first-launch-outcome"
        outcome.lifetime = .keepAlways
        add(outcome)
    }

    /// RF-15 clone voice (`--scenario clone-voice`, after first-launch): the benchmark clone
    /// voice saved from a Voice Design take of its own brief, then handed to Clone as its
    /// reference. Save as Voice transcribes the take, so on a fresh install iOS asks for
    /// Speech Recognition here, and the maintainer answers that prompt: the row never does.
    /// With the voice already saved it only confirms the handoff.
    func testBenchmarkCloneVoiceFromDesignTake() throws {
        try beginCandidateSession()
        defer { endSession() }
        ensureCloneConsentEnabled()
        let voiceName = VocelloUIBenchMatrix.cloneVoiceID
        // Search, not a raw lookup: Saved Voices is a lazy list.
        if revealSavedVoiceControls(named: voiceName, timeout: 10) != nil {
            clearVoicesSearch()
        } else {
            select(tab: .studio)
            prepare(mode: .design)
            replaceScript(with: "The harbor was quiet at dawn, and the old boats rocked gently while "
                + "the fishermen talked about the weather and the long season ahead.")
            XCTAssertFalse(generateAndWaitForCompletedPlayer(timeout: 300).isEmpty)
            saveCompletedTakeAsVoice(named: voiceName)
            VocelloUIScreenshot.attach(app, named: "candidate-clone-voice-saved")
        }
        // The saved voice must hand off to Clone as the benchmark reference.
        prepare(mode: .clone)
        VocelloUIScreenshot.attach(app, named: "candidate-clone-voice-ready")
    }

    /// Starts every missing shipping model from its own Voice Models row, then waits for each
    /// to reach Ready, and returns the models it started. A transfer that ends on Retry,
    /// Repair or Download fails the row.
    private func installMissingShippingModels() -> [String] {
        openVoiceModels()
        let models = ["pro_custom", "pro_design", "pro_clone"]
        var started: [String] = []
        for modelID in models {
            let status = app.staticTexts["iosModelStatus_\(modelID)"].firstMatch
            XCTAssertTrue(VocelloUIWait.exists(status, timeout: 60))
            XCTAssertTrue(revealSettingsElement(status, swipingUp: modelID == "pro_clone"))
            // Download for a model never fetched; Retry for one whose transfer was cut
            // off, such as when an earlier run's teardown force-quit the app mid-download.
            let start = ["Download", "Retry"].map { element("iosModel\($0)_\(modelID)") }.first { $0.exists }
            guard let start else { continue }
            started.append(modelID)
            XCTAssertTrue(VocelloUIPrimaryAction.perform(on: start, timeout: 20))
            XCTAssertTrue(VocelloUIWait.condition("\(modelID) to start or queue", timeout: 120) {
                self.element("iosModelProgress_\(modelID)").exists
                    || self.element("iosModelPhaseActivity_\(modelID)").exists
                    || self.element("iosModelCancel_\(modelID)").exists
                    || self.element("iosModelDelete_\(modelID)").exists
            })
        }
        for modelID in models {
            let status = app.staticTexts["iosModelStatus_\(modelID)"].firstMatch
            XCTAssertTrue(revealSettingsElement(status, swipingUp: modelID == "pro_clone"))
            var stoppedAt: String?
            XCTAssertTrue(VocelloUIWait.condition("\(modelID) to finish installing", timeout: 3_600) {
                if self.element("iosModelDelete_\(modelID)").exists { return true }
                for action in ["Retry", "Repair", "Download"] where self.element("iosModel\(action)_\(modelID)").exists {
                    stoppedAt = action
                    return true
                }
                return false
            })
            XCTAssertNil(stoppedAt, "\(modelID) stopped at \(stoppedAt ?? "") before Ready")
        }
        VocelloUIScreenshot.attach(app, named: "candidate-first-launch-models-ready")
        leaveVoiceModels()
        return started
    }

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
        saveCompletedTakeAsVoice(named: Self.throwawayVoiceName) { [unowned self] in
            self.registerSessionRestore { [unowned self] in self.deleteThrowawayVoiceIfPresent() }
        }

        guard revealSavedVoiceControls(named: Self.throwawayVoiceName, timeout: 60) != nil else {
            XCTFail("The saved designed voice did not expose an activatable row and menu")
            return
        }
        VocelloUIScreenshot.attach(app, named: "candidate-designed-voice-saved")
        clearVoicesSearch()
        XCTAssertTrue(deleteThrowawayVoiceIfPresent(), "The saved voice must delete through its menu")
        select(tab: .studio)
    }

    /// Saves the completed take as a voice through the player's Save as Voice sheet.
    /// `beforeSave` runs once the sheet is ready, before the voice exists.
    private func saveCompletedTakeAsVoice(named name: String, beforeSave: () -> Void = {}) {
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: element("studio_inlinePlayer_saveAsVoice"), timeout: 20))

        let nameField = element("saveVoice_nameField")
        XCTAssertTrue(VocelloUIWait.exists(nameField, timeout: 30))
        XCTAssertTrue(VocelloUITextEntry.replace(in: nameField, with: name, timeout: 20))
        XCTAssertTrue(VocelloUIWait.condition("the voice name to read exactly", timeout: 15) {
            (nameField.value as? String) == name
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
        if !(save.exists && save.isEnabled), audioOnly.exists {
            VocelloUIScroll.reveal(audioOnly, in: app)
            XCTAssertTrue(VocelloUIPrimaryAction.perform(on: audioOnly, timeout: 20))
        }
        VocelloUIScroll.reveal(save, in: app)
        XCTAssertTrue(VocelloUIWait.enabled(save, timeout: 20))
        beforeSave()
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
    /// drag it closed), and a detected language moves above "All languages", so every
    /// row is read top to bottom and exactly one language must be selected.
    private func selectedStudioLanguage() -> String? {
        openLanguagePicker()
        scrollLanguagePickerToTop()
        var selected = Set<String>()
        var lastSignature = ""
        for _ in 0..<12 {
            let visible = visibleLanguageRows()
            selected.formUnion(visible.selected)
            let signature = visible.rows.map(\.identifier).joined(separator: ",")
            if signature == lastSignature { break }
            lastSignature = signature
            swipeTarget(visible.rows, last: true)?.swipeUp()
        }
        closeLanguagePicker()
        guard selected.count == 1, let row = selected.first else { return nil }
        return String(row.dropFirst("languagePicker_".count))
    }

    /// Chooses the take language through Studio's chip and picker.
    private func chooseStudioLanguage(_ language: String) {
        openLanguagePicker()
        let option = element("languagePicker_\(language)")
        // The picker opens at its top, where most languages already show: scroll only
        // when the row is out of view.
        if !(option.exists && option.isHittable) {
            scrollLanguagePickerToTop()
            for _ in 0..<12 where !(option.exists && option.isHittable) {
                swipeTarget(visibleLanguageRows().rows, last: true)?.swipeUp()
            }
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

    /// The picker's language rows in view, top to bottom, from one snapshot: those wholly
    /// inside the window below the panel's header. Querying `exists` and `isHittable`
    /// row by row cost dozens of queries, several seconds, per look. `selected` reads every
    /// row the list has realized, in view or not, so a swipe cannot carry the selected
    /// row past a look.
    private func visibleLanguageRows() -> (rows: [ElementSnapshot], selected: Set<String>) {
        let snapshots = elementSnapshots { $0.elementType == .button && $0.identifier.hasPrefix("languagePicker_") }
        guard let header = snapshots.first(where: { $0.identifier == "languagePicker_confirm" })?.frame else { return ([], []) }
        let languages = snapshots.filter { $0.identifier != "languagePicker_confirm" }
        let window = app.windows.firstMatch.frame
        let rows = languages
            .filter { !$0.frame.isEmpty && $0.frame.minY >= header.maxY && window.contains($0.frame) }
            .sorted { $0.frame.minY < $1.frame.minY }
        return (rows, Set(languages.filter(\.isSelected).map(\.identifier)))
    }

    /// The row in view nearest the requested end, to swipe the list by.
    private func swipeTarget(_ rows: [ElementSnapshot], last: Bool) -> XCUIElement? {
        (last ? rows.last : rows.first).map { app.buttons[$0.identifier].firstMatch }
    }

    private func scrollLanguagePickerToTop() {
        var lastSignature = ""
        for _ in 0..<12 {
            let visible = visibleLanguageRows()
            let signature = visible.rows.map(\.identifier).joined(separator: ",")
            if signature == lastSignature { return }
            lastSignature = signature
            swipeTarget(visible.rows, last: false)?.swipeDown()
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
