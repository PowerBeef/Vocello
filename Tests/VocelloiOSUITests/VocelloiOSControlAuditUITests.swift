import Foundation
@preconcurrency import XCTest

private struct IOSControlAuditTake: Codable {
    let takeID: String
    let mode: String
    let warmState: String
    let speaker: String?
    let brief: String?
    let reference: String?
    let delivery: String?
    let language: String
    let variation: String
    let length: String
    let script: String
    let scriptDigest: String
    let searchToken: String
    let rowDigest: String
}

private struct IOSControlAuditPlan: Codable {
    let schemaVersion: Int
    let sourceIdentity: String
    let planDigest: String
    let takes: [IOSControlAuditTake]
}

private enum IOSControlAuditDeliverySelection {
    case preset(String)
    case custom(String)
}

private struct IOSControlAuditStudioSnapshot {
    let scripts: [String: String]
    let customSpeakerID: String
    let customDelivery: IOSControlAuditDeliverySelection
    let customLanguageID: String
    let designBrief: String
    let designDelivery: IOSControlAuditDeliverySelection
    let designLanguageID: String
    let cloneReferenceID: String?
    let cloneLanguageID: String
}

private struct IOSControlAuditObservation: Codable {
    let schemaVersion: Int
    let runID: String
    let sourceIdentity: String
    let scenario: String
    let controlID: String
    let classification: String
    let expected: String
    let actual: String
    let evidence: String?
    let takeID: String?
    let generationID: String?
    let mode: String?
    let speaker: String?
    let reference: String?
    let delivery: String?
    let language: String?
    let variation: String?
    let seed: UInt64?
    let warmState: String?
    let scriptDigest: String?
    let capturedAtEpochMS: Int64
}

@MainActor
private final class IOSControlAuditRecorder {
    // These are the machine-readable contract families owned by this test.
    // scripts/ios_control_audit.py rejects drift in either direction.
    static let ownedControlFamilies = [
        "root-tabs", "studio-modes", "composer", "speaker-options", "speaker-previews",
        "delivery-options", "delivery-editor", "language-options", "variation-options",
        "studio-chips", "reference-actions", "voice-enrollment", "voices-surface",
        "saved-voice-rows", "history-surface", "history-rows", "settings-preferences",
        "settings-links", "model-rows", "player-controls", "recording-controls",
        "attribution-controls", "onboarding-controls", "sheet-navigation",
    ]

    let runID: String
    let sourceIdentity: String
    private(set) var observations: [IOSControlAuditObservation] = []

    init(runID: String, sourceIdentity: String) {
        self.runID = runID
        self.sourceIdentity = sourceIdentity
    }

    func record(
        scenario: String,
        controlID: String,
        classification: String = "PASS",
        expected: String,
        actual: String,
        evidence: String? = nil,
        take: IOSControlAuditTake? = nil,
        generationID: String? = nil,
        observedSeed: UInt64? = nil
    ) {
        observations.append(
            IOSControlAuditObservation(
                schemaVersion: 1,
                runID: runID,
                sourceIdentity: sourceIdentity,
                scenario: scenario,
                controlID: controlID,
                classification: classification,
                expected: expected,
                actual: actual,
                evidence: evidence,
                takeID: take?.takeID,
                generationID: generationID,
                mode: take?.mode,
                speaker: take?.speaker,
                reference: take?.reference,
                delivery: take?.delivery,
                language: take?.language,
                variation: take?.variation,
                seed: observedSeed,
                warmState: take?.warmState,
                scriptDigest: take?.scriptDigest,
                capturedAtEpochMS: Int64(Date().timeIntervalSince1970 * 1_000)
            )
        )
    }

    func attach(to testCase: XCTestCase) {
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.sortedKeys]
        let lines = observations.compactMap { observation -> String? in
            guard let data = try? encoder.encode(observation) else { return nil }
            return String(data: data, encoding: .utf8)
        }
        let attachment = XCTAttachment(string: lines.joined(separator: "\n") + "\n")
        attachment.name = "control-observations.jsonl"
        attachment.lifetime = .keepAlways
        testCase.add(attachment)
    }
}

/// Explicit physical-iPhone audit. It uses only production controls, restores
/// reversible preferences through those controls, and deletes only rows whose
/// unique seed token comes from the immutable run plan.
@MainActor
final class VocelloiOSControlAuditUITests: VocelloiOSUITestCase {
    private var recorder: IOSControlAuditRecorder!
    private let stagedImportFileName = "ICI Direct Clone Import"
    private var cloneConsentWasEnabledBeforeAudit: Bool?
    private var generationAuditVoiceName: String?

    private var directImportVoiceName: String {
        generationAuditVoiceName ?? "ICA \(recorder.runID.suffix(8))"
    }

    func testConfiguredControlAuditScenario() throws {
        let environment = ProcessInfo.processInfo.environment
        let runID = try XCTUnwrap(environment["QVOICE_IOS_CONTROL_AUDIT_RUN_ID"])
        let sourceIdentity = try XCTUnwrap(environment["QVOICE_IOS_CONTROL_AUDIT_SOURCE_ID"])
        let scenario = try XCTUnwrap(environment["QVOICE_IOS_CONTROL_AUDIT_SCENARIO"])
        recorder = IOSControlAuditRecorder(runID: runID, sourceIdentity: sourceIdentity)
        defer { recorder.attach(to: self) }

        switch scenario {
        case "inventory":
            runInventoryAudit()
        case "stateful":
            runStatefulAudit()
        case "external":
            runExternalAudit()
        case "accessibility":
            try runAccessibilityAudit()
        case "generation":
            let plan = try decodePlan(from: environment)
            XCTAssertEqual(plan.sourceIdentity, sourceIdentity)
            runGenerationAudit(plan: plan)
        case "all":
            runInventoryAudit()
            runStatefulAudit()
            runExternalAudit()
            try runAccessibilityAudit()
            let plan = try decodePlan(from: environment)
            XCTAssertEqual(plan.sourceIdentity, sourceIdentity)
            runGenerationAudit(plan: plan)
        default:
            XCTFail("Unsupported control-audit scenario: \(scenario)")
        }
    }

    private func runInventoryAudit() {
        beginAuditSession()
        defer { endSession() }

        let originalMode = selectedMode()
        for tab in VocelloiOSTab.allCases {
            select(tab: tab)
        }
        recorder.record(
            scenario: "inventory", controlID: "root-tabs",
            expected: "Every tab becomes selected", actual: "All four tabs selected through rootTab identifiers"
        )

        // The tab loop intentionally ends on Settings. Return to the owning
        // Studio surface before querying or exercising mode-only controls.
        select(tab: .studio)
        for mode in VocelloUIBenchMatrix.Mode.allCases {
            select(mode: mode)
        }
        if let originalMode { select(mode: originalMode) }
        recorder.record(
            scenario: "inventory", controlID: "studio-modes",
            expected: "Every generation mode becomes selected", actual: "Built-in, Design, and Clone selected and original mode restored"
        )
        recorder.record(
            scenario: "inventory", controlID: "studio-chips",
            expected: "Every mode exposes its setup chip", actual: "Mode-specific visible-control assertions passed"
        )

        select(mode: .custom)
        auditSpeakerOptions()
        auditDeliveryOptions()
        auditLanguageOptions()
        auditCustomDeliveryEditor()
        recorder.record(
            scenario: "inventory", controlID: "sheet-navigation",
            expected: "Selector confirmations and dismissal return to Studio", actual: "Every selector returned without a stale modal"
        )
        recorder.record(
            scenario: "inventory", controlID: "onboarding-controls",
            classification: element("onboarding_skip").exists ? "HARNESS_FAIL" : "NOT_APPLICABLE",
            expected: "Onboarding is either completed visibly or explicitly unavailable",
            actual: "Existing installation had no onboarding after visible launch normalization"
        )
        VocelloUIScreenshot.attach(app, named: "ios-control-audit-inventory")
    }

    private func runStatefulAudit() {
        beginAuditSession()
        defer { endSession() }

        select(tab: .settings)
        let toggleIDs = [
            "iosSettings_autoPlayToggle",
            "iosSettings_reduceMotionToggle",
            "iosSettings_reduceTransparencyToggle",
            "voiceCloning_consentAcknowledgment",
        ]
        for identifier in toggleIDs {
            mutateAndRestoreToggle(identifier)
        }
        auditVariationOptions()
        recorder.record(
            scenario: "stateful", controlID: "settings-preferences",
            expected: "Every reversible setting changes once and returns to its original value",
            actual: "All visible toggle states restored through production controls"
        )

        openVoiceModels()
        for modelID in ["pro_custom", "pro_design", "pro_clone"] {
            let status = element("iosModelStatus_\(modelID)")
            XCTAssertTrue(VocelloUIWait.exists(status, timeout: 60))
            let value = (status.value as? String) ?? status.label
            recorder.record(
                scenario: "stateful", controlID: "model-rows:\(modelID)",
                expected: "Model exposes one textual status and its valid action set",
                actual: value,
                evidence: "ios-control-audit-model-\(modelID)"
            )
            VocelloUIScreenshot.attach(element("iosModelRow_\(modelID)"), named: "ios-control-audit-model-\(modelID)")
        }
        leaveVoiceModels()

        select(tab: .history)
        let clearMenu = element("historyClearMenu")
        if clearMenu.exists && clearMenu.isHittable {
            XCTAssertTrue(VocelloUIPrimaryAction.perform(on: clearMenu, timeout: 20))
            let keepAudioAction = app.buttons["Clear History (Keep Audio Files)…"].firstMatch
            XCTAssertTrue(VocelloUIWait.exists(keepAudioAction, timeout: 20))
            XCTAssertTrue(VocelloUIPrimaryAction.perform(on: keepAudioAction, timeout: 20))
            let cancel = app.buttons["Cancel"].firstMatch
            XCTAssertTrue(VocelloUIWait.exists(cancel, timeout: 20))
            XCTAssertTrue(VocelloUIPrimaryAction.perform(on: cancel, timeout: 20))
            XCTAssertTrue(VocelloUIWait.disappears(cancel, timeout: 20))
            select(tab: .settings)
        }
        recorder.record(
            scenario: "stateful", controlID: "history-surface",
            classification: "BLOCKED_PRESERVATION_POLICY",
            expected: "Global destructive controls expose choices but never mutate unrelated History",
            actual: "Menu presentation was inspected and dismissed without confirmation"
        )
        recorder.record(
            scenario: "stateful", controlID: "voices-surface",
            classification: "BLOCKED_PREREQUISITE",
            expected: "Run-owned enrollment and deletion are covered by saved-voice-lifecycle",
            actual: "No run-owned voice was created by the stateful phase"
        )
        recorder.record(
            scenario: "stateful", controlID: "saved-voice-rows",
            classification: "BLOCKED_PREREQUISITE",
            expected: "Only a run-owned saved voice may be previewed and deleted",
            actual: "Delegated to the explicit saved-voice-lifecycle phase"
        )
        recorder.record(
            scenario: "stateful", controlID: "voice-enrollment",
            classification: "BLOCKED_PREREQUISITE",
            expected: "Enrollment requires a staged test-owned reference",
            actual: "Delegated to the explicit saved-voice-lifecycle phase"
        )
    }

    private func runExternalAudit() {
        beginAuditSession()
        defer { endSession() }

        select(tab: .settings)
        let attribution = element("iosSettings_openSourceRow")
        XCTAssertTrue(VocelloUIWait.exists(attribution, timeout: 20))
        XCTAssertTrue(revealSettingsElement(attribution, swipingUp: true))
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: attribution, timeout: 20))
        XCTAssertTrue(VocelloUIWait.exists(element("screen_openSourceLicenses"), timeout: 20))
        XCTAssertTrue(VocelloUIWait.exists(element("iosAttributionRow_vocello"), timeout: 20))
        recorder.record(
            scenario: "external", controlID: "attribution-controls",
            expected: "Bundled attributions open without a load error",
            actual: "Vocello attribution row visible; no attribution error"
        )
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: element("iosSettings_openSourceBackButton"), timeout: 20))

        for identifier in ["iosSettings_privacyPolicyRow", "iosSettings_supportRow", "iosSettings_sourceCodeRow"] {
            verifyExternalHandoff(identifier: identifier, expectedApplication: nil)
        }
        verifyExternalHandoff(identifier: "iosSettings_openIOSSettingsRow", expectedApplication: "com.apple.Preferences")
        recorder.record(
            scenario: "external", controlID: "settings-links",
            expected: "Source-bound destination opens externally and Vocello returns unchanged",
            actual: "Each external control backgrounded Vocello and returned to Settings"
        )

        select(mode: .clone)
        let reference = element("studioChip_reference")
        if reference.exists && reference.isHittable {
            XCTAssertTrue(VocelloUIPrimaryAction.perform(on: reference, timeout: 20))
            let importButton = reveal("referenceClip_importAudioFile")
            XCTAssertTrue(VocelloUIPrimaryAction.perform(on: importButton, timeout: 20))
            let cancel = app.buttons["Cancel"].firstMatch
            if cancel.waitForExistence(timeout: 20) {
                XCTAssertTrue(VocelloUIPrimaryAction.perform(on: cancel, timeout: 20))
            } else {
                app.activate()
            }
            recorder.record(
                scenario: "external", controlID: "reference-actions",
                expected: "Files opens and cancellation preserves the Clone draft",
                actual: "Files presentation cancelled without selecting a reference"
            )
        } else {
            recorder.record(
                scenario: "external", controlID: "reference-actions",
                classification: "BLOCKED_PREREQUISITE",
                expected: "Clone reference controls require the Clone model surface",
                actual: "Reference chip was unavailable"
            )
        }
        recorder.record(
            scenario: "external", controlID: "recording-controls",
            classification: "BLOCKED_PRESERVATION_POLICY",
            expected: "Permission state is changed only when autonomous restoration is proven",
            actual: "Microphone and speech permission mutation intentionally refused"
        )
    }

    private func runAccessibilityAudit() throws {
        let categories: [(String, [String])] = [
            ("Default", ["-UIPreferredContentSizeCategoryName", "UICTContentSizeCategoryL"]),
            ("AX-L", ["-UIPreferredContentSizeCategoryName", "UICTContentSizeCategoryAccessibilityL"]),
            ("AX-XXXL", ["-UIPreferredContentSizeCategoryName", "UICTContentSizeCategoryAccessibilityXXXL"]),
            ("Pseudo-AX-XXXL", [
                "-UIPreferredContentSizeCategoryName", "UICTContentSizeCategoryAccessibilityXXXL",
                "-NSDoubleLocalizedStrings", "YES", "-NSShowNonLocalizedStrings", "YES",
            ]),
        ]
        for (name, arguments) in categories {
            beginAuditSession(arguments: arguments)
            for identifier in [
                "rootTab_studio", "rootTab_voices", "rootTab_history", "rootTab_settings",
                "generateSection_custom", "generateSection_design", "generateSection_clone",
            ] {
                assertAccessibleTarget(element(identifier), category: name)
            }
            select(tab: .settings)
            for identifier in ["iosSettings_autoPlayToggle", "iosSettings_variationRow"] {
                assertAccessibleTarget(element(identifier), category: name)
            }
            VocelloUIScreenshot.attach(app, named: "ios-control-audit-accessibility-\(name)")
            endSession()
        }

        // A forced UIPreferredContentSizeCategoryName intentionally pins the app to one layout
        // category, so XCTest's own Dynamic Type audit cannot vary it and reports every Text as
        // unsupported. Run the unfiltered system audit in a distinct launch without that override;
        // the four deterministic launches above remain the geometry/reflow authority.
        beginAuditSession()
        try app.performAccessibilityAudit()
        endSession()
        recorder.record(
            scenario: "accessibility", controlID: "root-tabs",
            expected: "Named 44-point controls at four layout configurations",
            actual: "Targets, labels, and an unforced stable major-surface audit passed"
        )
        recorder.record(
            scenario: "accessibility", controlID: "settings-preferences",
            expected: "Settings reflow without clipping or inaccessible controls",
            actual: "Default, AX-L, AX-XXXL, and pseudo AX-XXXL assertions passed"
        )
    }

    private func runGenerationAudit(plan: IOSControlAuditPlan) {
        beginAuditSession()
        defer { endSession() }
        let originalVariation = selectedVariationID()
        let originalMode = selectedMode()
        let originalStudio = captureStudioSnapshot()
        let environment = ProcessInfo.processInfo.environment
        let start = Int(environment["QVOICE_IOS_CONTROL_AUDIT_TAKE_START"] ?? "0") ?? 0
        let limit = Int(environment["QVOICE_IOS_CONTROL_AUDIT_TAKE_LIMIT"] ?? "0") ?? 0
        let selected = Array(plan.takes.dropFirst(start).prefix(limit > 0 ? limit : Int.max))
        XCTAssertFalse(selected.isEmpty, "Generation audit shard must contain at least one take")
        var frozenSeeds: [String: UInt64] = [:]
        var retainedSeedCarriers: [String: String] = [:]
        var modesPinnedByAudit = Set<String>()
        for mode in VocelloUIBenchMatrix.Mode.allCases {
            select(mode: mode)
            if start > 0,
               let carrier = restoreRetainedAuditSeed(
                in: mode,
                from: Array(plan.takes.prefix(start))
               ) {
                frozenSeeds[mode.rawValue] = carrier.seed
                retainedSeedCarriers[mode.rawValue] = carrier.searchToken
                modesPinnedByAudit.insert(mode.rawValue)
            } else if let seed = visiblePinnedSeed() {
                frozenSeeds[mode.rawValue] = seed
            }
        }
        var completedShard = false
        defer {
            // A terminal product failure ends this shard without retrying the
            // failed request. Retain one run-owned History row per mode so a
            // source/plan-bound resume can visibly restore the exact seed. Only
            // the shard that reaches the end removes those carriers and pins.
            if completedShard && (testRun?.failureCount ?? 0) == 0 {
                for searchToken in retainedSeedCarriers.values.sorted() {
                    deleteRunOwnedHistoryRow(searchToken: searchToken)
                }
                for modeID in modesPinnedByAudit.sorted() {
                    if let mode = VocelloUIBenchMatrix.Mode(rawValue: modeID) {
                        unpinAuditSeed(in: mode)
                    }
                }
            }
            restoreVariation(originalVariation)
            if let originalMode {
                select(mode: originalMode)
            }
        }
        let needsDirectImport = selected.contains {
            $0.mode == "clone" && $0.reference == "direct-import"
        }
        let needsRestorationVoice = originalStudio.cloneReferenceID == nil
            && selected.contains { $0.mode == "clone" }
        let createsAuditVoice = needsDirectImport || needsRestorationVoice
        if createsAuditVoice {
            generationAuditVoiceName = "ICA \(plan.planDigest.prefix(8))"
            ensureDirectImportVoice(reuseExisting: start > 0)
        }
        defer {
            if createsAuditVoice {
                if completedShard && (testRun?.failureCount ?? 0) == 0 {
                    deleteAuditVoiceIfPresent()
                }
                restoreCloneConsentIfNeeded()
            }
            restoreStudioSnapshot(originalStudio)
        }

        for take in selected {
            let mode = VocelloUIBenchMatrix.Mode(rawValue: take.mode)!
            var frozenSeed = frozenSeeds[take.mode]
            deleteStaleAuditHistoryRows(
                searchToken: take.searchToken,
                expectedScript: take.script
            )
            if mode == .clone && take.reference == "transcript-backed" && !benchmarkCloneVoiceExists() {
                recorder.record(
                    scenario: "generation", controlID: "generation:\(take.takeID)",
                    classification: "BLOCKED_PREREQUISITE",
                    expected: "Clone reference exists", actual: "Canonical benchmark clone voice unavailable",
                    take: take,
                    observedSeed: frozenSeed
                )
                continue
            }

            prepare(take: take, mode: mode)
            selectVariation(take.variation)
            if let speaker = take.speaker { selectSpeaker(speaker) }
            if let delivery = take.delivery, element("studioChip_delivery").exists {
                selectDelivery(delivery)
            }
            if element("studioChip_language").exists { selectLanguage(take.language) }
            replaceScript(with: take.script)
            if let frozenSeed {
                XCTAssertEqual(
                    visiblePinnedSeed(), frozenSeed,
                    "Every post-sentinel take must use the one visibly pinned seed"
                )
            }
            let generationID = generateAndWaitForCompletedPlayer(
                timeout: take.length == "long" ? 360 : 300,
                failTestOnVisibleError: false,
                onVisibleError: { [weak self] visibleError in
                    guard let self else { return }
                    self.recorder.record(
                        scenario: "generation", controlID: "generation:\(take.takeID)",
                        classification: "PRODUCT_FAIL",
                        expected: "Generation reaches decoded and published terminal audio",
                        actual: visibleError,
                        evidence: "ios-generation-visible-error",
                        take: take,
                        observedSeed: frozenSeed
                    )
                }
            )
            // The production failure surface has a single visible Retry action.
            // Ending this shard is the only way to preserve the failed request
            // without retrying it. `prepare-resume` advances to the next row.
            guard !generationID.isEmpty else { return }
            exerciseCompletedPlayer()
            dismissCompletedPlayerAndAssertGenerateReady()
            if retainedSeedCarriers[take.mode] == nil {
                if frozenSeed == nil {
                    frozenSeed = pinSeedFromRunOwnedHistoryRow(searchToken: take.searchToken)
                    frozenSeeds[take.mode] = frozenSeed
                    modesPinnedByAudit.insert(take.mode)
                }
                retainedSeedCarriers[take.mode] = take.searchToken
            } else {
                deleteRunOwnedHistoryRow(searchToken: take.searchToken)
            }
            let observedSeed = frozenSeed
            XCTAssertNotNil(observedSeed, "The cold sentinel must expose a seed that can be frozen visibly")
            recorder.record(
                scenario: "generation", controlID: "generation:\(take.takeID)",
                expected: "Visible request, engine receipt, QC, History, playback, and cleanup agree",
                actual: retainedSeedCarriers[take.mode] == take.searchToken
                    ? "Completed generation \(generationID); run-owned History row retained as the resume seed carrier"
                    : "Completed generation \(generationID); run-owned History row removed",
                evidence: "generation-\(take.takeID)",
                take: take,
                generationID: generationID,
                observedSeed: observedSeed
            )
        }
        recorder.record(
            scenario: "generation", controlID: "composer",
            expected: "Every planned safe take reaches a represented terminal result",
            actual: "Generation shard completed without automatic retry or seed substitution"
        )
        recorder.record(
            scenario: "generation", controlID: "history-rows",
            expected: "Run-owned rows open and are removed individually",
            actual: "Unique plan search tokens isolated History cleanup and the visible seed pin was restored"
        )
        recorder.record(
            scenario: "generation", controlID: "player-controls",
            expected: "Completed output remains playable and adjustable",
            actual: "Inline player controls were exercised before row cleanup"
        )
        completedShard = true
    }

    private func beginAuditSession(arguments: [String] = []) {
        beginSession(
            additionalEnvironment: ["QVOICE_IOS_DEVICE_RUN_ID": recorder.runID],
            additionalArguments: arguments
        )
    }

    private func prepare(take: IOSControlAuditTake, mode: VocelloUIBenchMatrix.Mode) {
        switch mode {
        case .custom:
            prepare(mode: .custom)
        case .design:
            select(mode: .design)
            XCTAssertTrue(VocelloUIPrimaryAction.perform(on: element("studioChip_voiceBrief"), timeout: 20))
            if take.brief == "starter" {
                XCTAssertTrue(VocelloUIPrimaryAction.perform(on: reveal("voiceBrief_starter_0"), timeout: 20))
            } else {
                let editor = element("voiceBrief_editor")
                XCTAssertTrue(VocelloUIWait.exists(editor, timeout: 20))
                XCTAssertTrue(
                    VocelloUITextEntry.replace(
                        in: editor,
                        with: "A clear adult narrator with a warm timbre and precise diction.",
                        timeout: 20
                    )
                )
                XCTAssertTrue(VocelloUIPrimaryAction.perform(on: element("voiceBrief_confirm"), timeout: 20))
            }
            XCTAssertTrue(VocelloUIWait.disappears(element("voiceBrief_confirm"), timeout: 20))
        case .clone:
            let voiceID = take.reference == "direct-import"
                ? directImportVoiceName
                : VocelloUIBenchMatrix.cloneVoiceID
            select(tab: .voices)
            let row = element("voicesRow_saved_\(voiceID)")
            XCTAssertTrue(VocelloUIWait.exists(row, timeout: 60))
            XCTAssertTrue(VocelloUIPrimaryAction.perform(on: row, timeout: 20))
            XCTAssertTrue(
                VocelloUIWait.condition("selected Clone reference \(voiceID)", timeout: 30) {
                    let clone = self.element("generateSection_clone")
                    return clone.exists && clone.isSelected
                        && self.element("studioChip_reference").label.localizedCaseInsensitiveContains(voiceID)
                }
            )
        }
        XCTAssertFalse(element("textInput_installModelButton").exists)
    }

    private func ensureDirectImportVoice(reuseExisting: Bool = false) {
        select(tab: .voices)
        if reuseExisting,
           VocelloUIWait.exists(element("voicesRow_saved_\(directImportVoiceName)"), timeout: 20) {
            select(tab: .studio)
            return
        }
        deleteAuditVoiceIfPresent()
        select(tab: .settings)
        let consent = element("voiceCloning_consentAcknowledgment")
        XCTAssertTrue(VocelloUIWait.exists(consent, timeout: 20))
        XCTAssertTrue(revealSettingsElement(consent, swipingUp: true))
        cloneConsentWasEnabledBeforeAudit = VocelloUIToggle.state(of: consent)
        XCTAssertNotNil(cloneConsentWasEnabledBeforeAudit, "Clone consent must expose a restorable state")
        ensureCloneConsentEnabled()
        select(mode: .clone)
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: element("studioChip_reference"), timeout: 20))
        XCTAssertTrue(
            VocelloUIPrimaryAction.perform(on: element("referenceClip_importAudioFile"), timeout: 20)
        )
        let pickerItem = app.cells.matching(
            NSPredicate(format: "label CONTAINS %@ AND isEnabled == 1", stagedImportFileName)
        ).firstMatch
        XCTAssertTrue(
            VocelloUIWait.exists(pickerItem, timeout: 30),
            "Stage \(stagedImportFileName).wav without a neighboring sidecar before generation audit"
        )
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: pickerItem, timeout: 20))
        let nameField = element("saveVoice_nameField")
        XCTAssertTrue(VocelloUIWait.exists(nameField, timeout: 30))
        XCTAssertTrue(VocelloUITextEntry.replace(in: nameField, with: directImportVoiceName, timeout: 20))
        if app.keyboards.firstMatch.exists {
            nameField.typeText("\n")
            XCTAssertTrue(
                VocelloUIWait.condition("save-voice keyboard to dismiss", timeout: 15) {
                    !self.app.keyboards.firstMatch.exists
                }
            )
        }
        let transcriptEditor = element("saveVoice_transcriptEditor")
        let saveButton = element("saveVoice_saveButton")
        XCTAssertTrue(
            VocelloUIWait.condition("audit import transcript to become saveable", timeout: 180) {
                guard let transcript = transcriptEditor.value as? String else { return false }
                return !transcript.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                    && saveButton.exists && saveButton.isEnabled
            }
        )
        let revealedSaveButton = reveal("saveVoice_saveButton")
        XCTAssertTrue(revealedSaveButton.isEnabled)
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: revealedSaveButton, timeout: 20))
        let keepDespiteWarning = element("recordVoice_keepDespiteWarning")
        if keepDespiteWarning.waitForExistence(timeout: 5) {
            XCTAssertTrue(VocelloUIPrimaryAction.perform(on: keepDespiteWarning, timeout: 20))
        }
        XCTAssertTrue(
            VocelloUIWait.label(
                element("studioChip_reference"),
                contains: directImportVoiceName,
                timeout: 60
            )
        )
    }

    private func deleteAuditVoiceIfPresent() {
        select(tab: .voices)
        let row = element("voicesRow_saved_\(directImportVoiceName)")
        guard row.waitForExistence(timeout: 5) else { return }
        // Make the run-owned voice the active Clone reference before deleting
        // it. The production deletion path then clears the draft, giving the
        // snapshot restorer an honest way to restore an originally empty
        // reference without a hidden test hook.
        select(mode: .clone)
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: element("studioChip_reference"), timeout: 20))
        XCTAssertTrue(
            VocelloUIPrimaryAction.perform(
                on: reveal("referenceClipRow_\(directImportVoiceName)"),
                timeout: 20
            )
        )
        select(tab: .voices)
        let selectedRow = element("voicesRow_saved_\(directImportVoiceName)")
        XCTAssertTrue(VocelloUIWait.exists(selectedRow, timeout: 20))
        XCTAssertTrue(
            VocelloUIPrimaryAction.perform(
                on: element("voicesRowMenu_\(directImportVoiceName)"),
                timeout: 20
            )
        )
        XCTAssertTrue(
            VocelloUIPrimaryAction.perform(
                on: element("voicesDelete_\(directImportVoiceName)"),
                timeout: 20
            )
        )
        XCTAssertTrue(
            VocelloUIPrimaryAction.perform(
                on: element("voicesDeleteConfirm_\(directImportVoiceName)"),
                timeout: 20
            )
        )
        XCTAssertTrue(VocelloUIWait.disappears(selectedRow, timeout: 60))
    }

    private func restoreCloneConsentIfNeeded() {
        guard cloneConsentWasEnabledBeforeAudit == false else { return }
        select(tab: .settings)
        let consent = element("voiceCloning_consentAcknowledgment")
        XCTAssertTrue(VocelloUIWait.exists(consent, timeout: 20))
        XCTAssertTrue(revealSettingsElement(consent, swipingUp: true))
        if VocelloUIToggle.state(of: consent) == true {
            XCTAssertTrue(VocelloUIPrimaryAction.perform(on: consent, timeout: 20))
            XCTAssertTrue(
                VocelloUIWait.condition("Clone consent to restore disabled", timeout: 15) {
                    VocelloUIToggle.state(of: consent) == false
                }
            )
        }
    }

    private func selectedMode() -> VocelloUIBenchMatrix.Mode? {
        VocelloUIBenchMatrix.Mode.allCases.first { element("generateSection_\($0.rawValue)").isSelected }
    }

    private func captureStudioSnapshot() -> IOSControlAuditStudioSnapshot {
        var scripts: [String: String] = [:]
        for mode in VocelloUIBenchMatrix.Mode.allCases {
            select(mode: mode)
            let editor = element("textInput_textEditor")
            XCTAssertTrue(VocelloUIWait.exists(editor, timeout: 20))
            scripts[mode.rawValue] = (editor.value as? String) ?? ""
        }

        select(mode: .custom)
        let customSpeaker = captureSelectedID(
            chipID: "studioChip_voice",
            rowPrefix: "voicePickerRow_",
            candidates: speakerIDs,
            confirmationID: "voicePicker_confirm"
        )
        let customDelivery = captureDeliverySelection()
        let customLanguage = captureLanguageSelection()

        select(mode: .design)
        let designBrief = captureDesignBrief()
        let designDelivery = captureDeliverySelection()
        let designLanguage = captureLanguageSelection()

        select(mode: .clone)
        let cloneReference = captureCloneReferenceSelection()
        let cloneLanguage = captureLanguageSelection()

        return IOSControlAuditStudioSnapshot(
            scripts: scripts,
            customSpeakerID: customSpeaker,
            customDelivery: customDelivery,
            customLanguageID: customLanguage,
            designBrief: designBrief,
            designDelivery: designDelivery,
            designLanguageID: designLanguage,
            cloneReferenceID: cloneReference,
            cloneLanguageID: cloneLanguage
        )
    }

    private func restoreStudioSnapshot(_ snapshot: IOSControlAuditStudioSnapshot) {
        guard app.state == .runningForeground else {
            XCTFail("Studio snapshot could not be restored because Vocello is not foregrounded")
            return
        }

        select(mode: .custom)
        restoreScript(snapshot.scripts["custom"] ?? "")
        selectSpeaker(snapshot.customSpeakerID)
        restoreDeliverySelection(snapshot.customDelivery)
        selectLanguage(snapshot.customLanguageID)

        select(mode: .design)
        restoreScript(snapshot.scripts["design"] ?? "")
        restoreDesignBrief(snapshot.designBrief)
        restoreDeliverySelection(snapshot.designDelivery)
        selectLanguage(snapshot.designLanguageID)

        select(mode: .clone)
        restoreScript(snapshot.scripts["clone"] ?? "")
        selectLanguage(snapshot.cloneLanguageID)
        if let referenceID = snapshot.cloneReferenceID {
            XCTAssertTrue(VocelloUIPrimaryAction.perform(on: element("studioChip_reference"), timeout: 20))
            XCTAssertTrue(
                VocelloUIPrimaryAction.perform(
                    on: reveal("referenceClipRow_\(referenceID)"),
                    timeout: 20
                )
            )
        }
    }

    private var speakerIDs: [String] {
        ["aiden", "ryan", "vivian", "serena", "uncle_fu", "dylan", "eric", "ono_anna", "sohee"]
    }

    private var deliveryIDs: [String] {
        ["neutral", "happy", "sad", "angry", "fearful", "surprised", "calm", "whisper"]
    }

    private var languageIDs: [String] {
        ["chinese", "english", "japanese", "korean", "german", "french", "russian", "portuguese", "spanish", "italian"]
    }

    private var selectableLanguageIDs: [String] {
        ["auto"] + languageIDs
    }

    private func captureSelectedID(
        chipID: String,
        rowPrefix: String,
        candidates: [String],
        confirmationID: String
    ) -> String {
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: element(chipID), timeout: 20))
        let selected = findSelectedID(rowPrefix: rowPrefix, candidates: candidates)
        XCTAssertNotNil(selected, "\(chipID) must expose one selected row")
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: element(confirmationID), timeout: 20))
        XCTAssertTrue(VocelloUIWait.disappears(element(confirmationID), timeout: 20))
        return selected ?? candidates[0]
    }

    private func captureLanguageSelection() -> String {
        captureSelectedID(
            chipID: "studioChip_language",
            rowPrefix: "languagePicker_",
            candidates: selectableLanguageIDs,
            confirmationID: "languagePicker_confirm"
        )
    }

    private func captureDeliverySelection() -> IOSControlAuditDeliverySelection {
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: element("studioChip_delivery"), timeout: 20))
        if let preset = findSelectedID(
            rowPrefix: "deliveryPickerPreset_",
            candidates: deliveryIDs
        ) {
            XCTAssertTrue(VocelloUIPrimaryAction.perform(on: element("deliveryPicker_confirm"), timeout: 20))
            XCTAssertTrue(VocelloUIWait.disappears(element("deliveryPicker_confirm"), timeout: 20))
            return .preset(preset)
        }

        XCTAssertTrue(
            VocelloUIPrimaryAction.perform(on: reveal("deliveryPickerSheet_customTone"), timeout: 20)
        )
        let editor = element("deliveryPickerSheet_customTone_editor")
        XCTAssertTrue(VocelloUIWait.exists(editor, timeout: 20))
        let text = (editor.value as? String) ?? ""
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: element("deliveryPickerSheet_customTone_back"), timeout: 20))
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: element("deliveryPicker_confirm"), timeout: 20))
        XCTAssertTrue(VocelloUIWait.disappears(element("deliveryPicker_confirm"), timeout: 20))
        return .custom(text)
    }

    private func captureDesignBrief() -> String {
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: element("studioChip_voiceBrief"), timeout: 20))
        let editor = element("voiceBrief_editor")
        XCTAssertTrue(VocelloUIWait.exists(editor, timeout: 20))
        let brief = (editor.value as? String) ?? ""
        dismissVoiceBriefSheet()
        return brief
    }

    private func dismissVoiceBriefSheet() {
        let confirm = element("voiceBrief_confirm")
        if confirm.exists && confirm.isEnabled {
            XCTAssertTrue(VocelloUIPrimaryAction.perform(on: confirm, timeout: 20))
        } else {
            // An empty brief disables Confirm and this custom edge panel has
            // no close button while a trailing header control is present.
            // Anchor the production drag-to-dismiss gesture to that visible
            // header element instead of using coordinates or mutating text.
            XCTAssertTrue(confirm.exists)
            confirm.swipeDown()
        }
        XCTAssertTrue(VocelloUIWait.disappears(element("voiceBrief_editor"), timeout: 20))
    }

    private func captureCloneReferenceSelection() -> String? {
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: element("studioChip_reference"), timeout: 20))
        var selected: String?
        for _ in 0..<16 where selected == nil {
            let rows = app.descendants(matching: .any)
                .matching(NSPredicate(format: "identifier BEGINSWITH %@", "referenceClipRow_"))
                .allElementsBoundByIndex
            selected = rows.first(where: \.isSelected)?.identifier
                .replacingOccurrences(of: "referenceClipRow_", with: "")
            if selected == nil { app.swipeUp() }
        }
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: element("bottomSheet_close"), timeout: 20))
        return selected
    }

    private func findSelectedID(rowPrefix: String, candidates: [String]) -> String? {
        for _ in 0..<16 {
            for candidate in candidates {
                let row = element("\(rowPrefix)\(candidate)")
                if row.exists && row.isSelected { return candidate }
            }
            app.swipeUp()
        }
        return nil
    }

    private func restoreScript(_ script: String) {
        let editor = element("textInput_textEditor")
        XCTAssertTrue(VocelloUIWait.exists(editor, timeout: 20))
        if (editor.value as? String) != script {
            replaceScript(with: script)
        }
    }

    private func restoreDeliverySelection(_ selection: IOSControlAuditDeliverySelection) {
        switch selection {
        case .preset(let preset):
            selectDelivery(preset)
        case .custom(let text):
            XCTAssertTrue(VocelloUIPrimaryAction.perform(on: element("studioChip_delivery"), timeout: 20))
            XCTAssertTrue(
                VocelloUIPrimaryAction.perform(on: reveal("deliveryPickerSheet_customTone"), timeout: 20)
            )
            let editor = element("deliveryPickerSheet_customTone_editor")
            XCTAssertTrue(VocelloUIWait.exists(editor, timeout: 20))
            XCTAssertTrue(VocelloUITextEntry.replace(in: editor, with: text, timeout: 20))
            XCTAssertTrue(VocelloUIPrimaryAction.perform(on: element("deliveryPicker_confirm"), timeout: 20))
        }
    }

    private func restoreDesignBrief(_ brief: String) {
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: element("studioChip_voiceBrief"), timeout: 20))
        let editor = element("voiceBrief_editor")
        XCTAssertTrue(VocelloUIWait.exists(editor, timeout: 20))
        XCTAssertTrue(VocelloUITextEntry.replace(in: editor, with: brief, timeout: 20))
        // The production binding updates while editing. An empty original
        // brief disables Confirm, so use the real system-sheet dismissal in
        // that state instead of inventing a test-only escape hatch.
        dismissVoiceBriefSheet()
    }

    private func auditSpeakerOptions() {
        for speaker in speakerIDs {
            selectSpeaker(speaker)
            recorder.record(
                scenario: "inventory", controlID: "speaker-options:\(speaker)",
                expected: "Speaker becomes selected", actual: "Selected through voicePickerRow_\(speaker)"
            )
            XCTAssertTrue(VocelloUIPrimaryAction.perform(on: element("studioChip_voice"), timeout: 20))
            let preview = reveal("voicePickerPreview_\(speaker)")
            XCTAssertTrue(VocelloUIPrimaryAction.perform(on: preview, timeout: 20))
            XCTAssertTrue(VocelloUIPrimaryAction.perform(on: preview, timeout: 20))
            XCTAssertTrue(VocelloUIPrimaryAction.perform(on: element("voicePicker_confirm"), timeout: 20))
            XCTAssertTrue(VocelloUIWait.disappears(element("voicePicker_confirm"), timeout: 20))
            recorder.record(
                scenario: "inventory", controlID: "speaker-previews:\(speaker)",
                expected: "Preview starts and stops for the selected speaker",
                actual: "Preview accepted its play and stop actions before the visible selection was confirmed"
            )
        }
        selectSpeaker("aiden")
    }

    private func auditDeliveryOptions() {
        for value in deliveryIDs {
            selectDelivery(value)
            recorder.record(
                scenario: "inventory", controlID: "delivery-options:\(value)",
                expected: "Delivery becomes selected", actual: "Selected through deliveryPickerPreset_\(value)"
            )
        }
        selectDelivery("neutral")
    }

    private func auditLanguageOptions() {
        for value in languageIDs {
            selectLanguage(value)
            recorder.record(
                scenario: "inventory", controlID: "language-options:\(value)",
                expected: "Language becomes selected", actual: "Selected through languagePicker_\(value)"
            )
        }
        selectLanguage("english")
    }

    private func auditVariationOptions() {
        select(tab: .settings)
        let picker = element("iosSettings_variationRow")
        XCTAssertTrue(VocelloUIWait.exists(picker, timeout: 20))
        let original = (picker.value as? String) ?? "Expressive"
        for value in ["expressive", "balanced", "consistent"] {
            selectVariation(value)
            recorder.record(
                scenario: "stateful", controlID: "variation-options:\(value)",
                expected: "Variation becomes selected", actual: "Selected \(value) through Settings"
            )
        }
        let originalValue = original.lowercased().contains("balanced") ? "balanced"
            : original.lowercased().contains("consistent") ? "consistent" : "expressive"
        selectVariation(originalValue)
        select(tab: .studio)
    }

    private func auditCustomDeliveryEditor() {
        select(mode: .custom)
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: element("studioChip_delivery"), timeout: 20))
        let custom = reveal("deliveryPickerSheet_customTone")
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: custom, timeout: 20))
        XCTAssertTrue(VocelloUIWait.exists(element("deliveryPickerSheet_customTone_charCount"), timeout: 20))
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: element("deliveryPickerSheet_customTone_back"), timeout: 20))
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: element("deliveryPicker_confirm"), timeout: 20))
        XCTAssertTrue(VocelloUIWait.disappears(element("deliveryPicker_confirm"), timeout: 20))
        recorder.record(
            scenario: "inventory", controlID: "delivery-editor",
            expected: "Custom tone editor opens and returns without changing delivery",
            actual: "Editor, count, back, and delivery confirmation controls worked"
        )
    }

    private func selectSpeaker(_ id: String) {
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: element("studioChip_voice"), timeout: 20))
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: reveal("voicePickerRow_\(id)"), timeout: 20))
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: element("voicePicker_confirm"), timeout: 20))
        XCTAssertTrue(VocelloUIWait.disappears(element("voicePicker_confirm"), timeout: 20))
    }

    private func selectDelivery(_ id: String) {
        select(tab: .studio)
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: element("studioChip_delivery"), timeout: 20))
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: reveal("deliveryPickerPreset_\(id)"), timeout: 20))
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: element("deliveryPicker_confirm"), timeout: 20))
        XCTAssertTrue(VocelloUIWait.disappears(element("deliveryPicker_confirm"), timeout: 20))
    }

    private func selectLanguage(_ id: String) {
        select(tab: .studio)
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: element("studioChip_language"), timeout: 20))
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: reveal("languagePicker_\(id)"), timeout: 20))
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: element("languagePicker_confirm"), timeout: 20))
        XCTAssertTrue(VocelloUIWait.disappears(element("languagePicker_confirm"), timeout: 20))
    }

    private func selectVariation(_ id: String) {
        select(tab: .settings)
        let picker = element("iosSettings_variationRow")
        XCTAssertTrue(VocelloUIWait.exists(picker, timeout: 20))
        XCTAssertTrue(revealSettingsElement(picker, swipingUp: false))
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: picker, timeout: 20))
        let option = element("iosSettings_variationOption_\(id)")
        XCTAssertTrue(VocelloUIWait.exists(option, timeout: 20))
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: option, timeout: 20))
        select(tab: .studio)
    }

    private func selectedVariationID() -> String {
        select(tab: .settings)
        let picker = element("iosSettings_variationRow")
        XCTAssertTrue(VocelloUIWait.exists(picker, timeout: 20))
        let value = ((picker.value as? String) ?? picker.label).lowercased()
        select(tab: .studio)
        if value.contains("balanced") { return "balanced" }
        if value.contains("consistent") { return "consistent" }
        return "expressive"
    }

    private func restoreVariation(_ id: String) {
        guard app.state == .runningForeground else { return }
        if selectedVariationID() != id {
            selectVariation(id)
        }
    }

    private func mutateAndRestoreToggle(_ identifier: String) {
        select(tab: .settings)
        let toggle = element(identifier)
        XCTAssertTrue(VocelloUIWait.exists(toggle, timeout: 20))
        XCTAssertTrue(revealSettingsElement(toggle, swipingUp: true))
        guard let original = VocelloUIToggle.state(of: toggle) else {
            XCTFail("Unknown toggle state for \(identifier); refusing mutation")
            return
        }
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: toggle, timeout: 20))
        let changed = VocelloUIWait.condition("\(identifier) changes", timeout: 15) {
            VocelloUIToggle.state(of: toggle) == !original
        }
        guard changed else {
            restoreToggle(toggle, identifier: identifier, to: original)
            return
        }
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: toggle, timeout: 20))
        XCTAssertTrue(VocelloUIWait.condition("\(identifier) restores", timeout: 15) {
            VocelloUIToggle.state(of: toggle) == original
        })
    }

    private func restoreToggle(_ toggle: XCUIElement, identifier: String, to original: Bool) {
        guard let current = VocelloUIToggle.state(of: toggle) else {
            XCTFail("Unknown toggle state while restoring \(identifier)")
            return
        }
        guard current != original else { return }
        XCTAssertTrue(revealSettingsElement(toggle, swipingUp: true))
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: toggle, timeout: 20))
        XCTAssertTrue(VocelloUIWait.condition("\(identifier) fail-safe restore", timeout: 15) {
            VocelloUIToggle.state(of: toggle) == original
        })
    }

    private func verifyExternalHandoff(identifier: String, expectedApplication: String?) {
        select(tab: .settings)
        let control = element(identifier)
        XCTAssertTrue(VocelloUIWait.exists(control, timeout: 20))
        XCTAssertTrue(revealSettingsElement(control, swipingUp: true))
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: control, timeout: 20))
        XCTAssertTrue(VocelloUIWait.condition("Vocello to yield to external destination", timeout: 30) {
            self.app.state != .runningForeground
        })
        if let expectedApplication {
            let external = XCUIApplication(bundleIdentifier: expectedApplication)
            XCTAssertTrue(VocelloUIWait.condition("expected external application", timeout: 20) {
                external.state == .runningForeground
            })
        }
        app.activate()
        XCTAssertTrue(VocelloUIWait.condition("Vocello to return", timeout: 30) {
            self.app.state == .runningForeground
        })
        XCTAssertTrue(VocelloUIWait.exists(element("screen_settings"), timeout: 20))
    }

    private func assertAccessibleTarget(_ target: XCUIElement, category: String) {
        XCTAssertTrue(VocelloUIWait.exists(target, timeout: 20))
        XCTAssertFalse(target.label.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
        XCTAssertGreaterThanOrEqual(target.frame.width + 0.01, 44, "\(target.identifier) width at \(category)")
        XCTAssertGreaterThanOrEqual(target.frame.height + 0.01, 44, "\(target.identifier) height at \(category)")
        XCTAssertGreaterThanOrEqual(target.frame.minX, app.frame.minX)
        XCTAssertLessThanOrEqual(target.frame.maxX, app.frame.maxX)
    }

    private func reveal(_ identifier: String) -> XCUIElement {
        let target = element(identifier)
        for _ in 0..<16 {
            if target.exists && target.isHittable { return target }
            app.swipeUp()
        }
        XCTAssertTrue(target.exists && target.isHittable, "Could not reveal \(identifier)")
        return target
    }

    private func decodePlan(from environment: [String: String]) throws -> IOSControlAuditPlan {
        let encoded = try XCTUnwrap(environment["QVOICE_IOS_CONTROL_AUDIT_PLAN_B64"])
        let compressed = try XCTUnwrap(Data(base64Encoded: encoded))
        let data = try (compressed as NSData).decompressed(using: .zlib) as Data
        let plan = try JSONDecoder().decode(IOSControlAuditPlan.self, from: data)
        XCTAssertEqual(plan.schemaVersion, 1)
        return plan
    }

    private func benchmarkCloneVoiceExists() -> Bool {
        select(tab: .voices)
        let voice = element("voicesRow_saved_\(VocelloUIBenchMatrix.cloneVoiceID)")
        let exists = voice.waitForExistence(timeout: 20)
        select(tab: .studio)
        return exists
    }

    private func exerciseCompletedPlayer() {
        let playPause = element("studio_inlinePlayer_playPause")
        XCTAssertTrue(VocelloUIWait.exists(playPause, timeout: 20))
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: playPause, timeout: 20))
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: playPause, timeout: 20))
        let scrubber = element("studio_inlinePlayer_scrubber")
        if scrubber.exists && scrubber.isHittable {
            let priorValue = scrubber.value as? String
            // The waveform is a custom adjustable Button, not UISlider.
            // Exercise its production DragGesture through an element-anchored
            // swipe; coordinate automation and slider-only XCTest APIs are
            // both inappropriate for this accessibility surface.
            scrubber.swipeRight()
            XCTAssertTrue(
                VocelloUIWait.condition("inline player scrubber value to change", timeout: 15) {
                    (scrubber.value as? String) != priorValue
                }
            )
        }
    }

    private func deleteRunOwnedHistoryRow(searchToken: String) {
        replaceHistorySearch(with: searchToken)
        XCTAssertTrue(VocelloUIWait.condition("one run-owned History row", timeout: 30) {
            self.historyRows().count == 1
        })
        let row = historyRows().firstMatch
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: row, timeout: 20))
        XCTAssertTrue(VocelloUIWait.exists(element("iosPlayer_playPause"), timeout: 20))
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: element("iosPlayer_close"), timeout: 20))
        let menu = app.descendants(matching: .any)
            .matching(NSPredicate(format: "identifier BEGINSWITH %@", "historyRowMenu_"))
            .firstMatch
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: menu, timeout: 20))
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: app.buttons["Delete"].firstMatch, timeout: 20))
        let confirm = app.descendants(matching: .any)
            .matching(NSPredicate(format: "identifier BEGINSWITH %@", "historyRowDeleteConfirm_"))
            .firstMatch
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: confirm, timeout: 20))
        XCTAssertTrue(VocelloUIWait.exists(element("history_noMatchesState"), timeout: 30))
        dismissHistorySearchKeyboardIfNeeded()
        select(tab: .studio)
    }

    private func deleteStaleAuditHistoryRows(searchToken: String, expectedScript: String) {
        replaceHistorySearch(with: searchToken)
        dismissHistorySearchKeyboardIfNeeded()

        for _ in 0..<32 {
            let count = historyRows().count
            guard count > 0 else {
                select(tab: .studio)
                return
            }
            let matchingScripts = app.staticTexts.matching(
                NSPredicate(format: "label == %@", expectedScript)
            ).count
            XCTAssertEqual(
                matchingScripts, count,
                "Reserved token \(searchToken) matched a non-audit History row"
            )
            let menu = app.descendants(matching: .any)
                .matching(NSPredicate(format: "identifier BEGINSWITH %@", "historyRowMenu_"))
                .firstMatch
            XCTAssertTrue(VocelloUIPrimaryAction.perform(on: menu, timeout: 20))
            XCTAssertTrue(VocelloUIPrimaryAction.perform(on: app.buttons["Delete"].firstMatch, timeout: 20))
            let confirm = app.descendants(matching: .any)
                .matching(NSPredicate(format: "identifier BEGINSWITH %@", "historyRowDeleteConfirm_"))
                .firstMatch
            XCTAssertTrue(VocelloUIPrimaryAction.perform(on: confirm, timeout: 20))
            XCTAssertTrue(
                VocelloUIWait.condition("stale audit History row count to decrease", timeout: 30) {
                    self.historyRows().count < count
                }
            )
        }
        XCTFail("More than 32 stale audit rows matched reserved token \(searchToken)")
        select(tab: .studio)
    }

    private func dismissHistorySearchKeyboardIfNeeded() {
        guard app.keyboards.firstMatch.exists else { return }
        let searchField = app.textFields["historySearchField"].firstMatch
        XCTAssertTrue(searchField.exists)
        searchField.typeText("\n")
        XCTAssertTrue(
            VocelloUIWait.condition("History search keyboard to dismiss", timeout: 15) {
                !self.app.keyboards.firstMatch.exists
            }
        )
    }

    private func visiblePinnedSeed() -> UInt64? {
        let chip = element("studioChip_seedPin")
        guard chip.exists else { return nil }
        return extractSeed(from: [chip.label, chip.value as? String].compactMap { $0 }.joined(separator: " "))
    }

    private func pinSeedFromRunOwnedHistoryRow(searchToken: String) -> UInt64 {
        replaceHistorySearch(with: searchToken)
        XCTAssertTrue(VocelloUIWait.condition("one run-owned History row", timeout: 30) {
            self.historyRows().count == 1
        })
        let menu = app.descendants(matching: .any)
            .matching(NSPredicate(format: "identifier BEGINSWITH %@", "historyRowMenu_"))
            .firstMatch
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: menu, timeout: 20))
        let pin = app.buttons.matching(
            NSPredicate(format: "label BEGINSWITH[c] %@", "Pin seed ")
        ).firstMatch
        XCTAssertTrue(VocelloUIWait.exists(pin, timeout: 20))
        let seed = extractSeed(from: pin.label)
        XCTAssertNotNil(seed, "History Pin seed action must expose its exact numeric seed")
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: pin, timeout: 20))
        dismissHistorySearchKeyboardIfNeeded()
        select(tab: .studio)
        XCTAssertTrue(VocelloUIWait.condition("History seed to become visibly pinned", timeout: 20) {
            self.visiblePinnedSeed() == seed
        })
        return seed ?? 0
    }

    private func restoreRetainedAuditSeed(
        in mode: VocelloUIBenchMatrix.Mode,
        from priorTakes: [IOSControlAuditTake]
    ) -> (seed: UInt64, searchToken: String)? {
        for take in priorTakes where take.mode == mode.rawValue {
            replaceHistorySearch(with: take.searchToken)
            dismissHistorySearchKeyboardIfNeeded()
            let rows = historyRows()
            guard rows.count > 0 else { continue }
            XCTAssertEqual(rows.count, 1, "A retained seed token must identify exactly one audit row")
            let matchingRowActions = app.descendants(matching: .any).matching(
                NSPredicate(
                    format: "identifier BEGINSWITH %@ AND label CONTAINS %@",
                    "historyRowTap_", take.script
                )
            )
            XCTAssertEqual(
                matchingRowActions.count, 1,
                "A retained seed carrier must expose the immutable audit script on its labeled row action"
            )
            let seed = pinSeedFromRunOwnedHistoryRow(searchToken: take.searchToken)
            return (seed, take.searchToken)
        }
        select(tab: .studio)
        return nil
    }

    private func unpinAuditSeed(in mode: VocelloUIBenchMatrix.Mode) {
        select(mode: mode)
        let chip = element("studioChip_seedPin")
        guard chip.exists else { return }
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: chip, timeout: 20))
        XCTAssertTrue(
            VocelloUIPrimaryAction.perform(on: app.buttons["Unpin — new seed each take"].firstMatch, timeout: 20)
        )
        XCTAssertTrue(VocelloUIWait.disappears(chip, timeout: 20))
    }

    private func extractSeed(from text: String) -> UInt64? {
        text.split(whereSeparator: { !$0.isNumber }).compactMap { UInt64($0) }.first
    }
}
