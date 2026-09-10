import XCTest

/// Inspect a previously observed row without generation, pinning, deletion, or
/// seed adoption. A successful observation is not a speech-quality verdict.
@MainActor
final class VocelloiOSHistoryObservationUITests: VocelloiOSUITestCase {
    override func tearDown() {
        endSession()
        super.tearDown()
    }

    func testRetainedHistoryTranscript() throws {
        let environment = ProcessInfo.processInfo.environment
        let rowID = try XCTUnwrap(environment["QVOICE_IOS_HISTORY_OBSERVATION_ROW_ID"])
        let runID = try XCTUnwrap(environment["QVOICE_IOS_SMOKE_RUN_ID"])
        XCTAssertNotNil(rowID.range(of: "^generation-[0-9]+$", options: .regularExpression))
        beginSession()
        replaceHistorySearch(with: "An evening by the harbor.")
        dismissHistorySearchKeyboardIfNeeded()
        let row = try XCTUnwrap(revealHistoryRow(rowID))
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: row, timeout: 20))
        let transcript = element("iosPlayer_transcript")
        XCTAssertTrue(VocelloUIWait.exists(transcript, timeout: 20))
        let observed = try XCTUnwrap(transcript.value as? String)
        let data = try JSONSerialization.data(withJSONObject: [
            "schemaVersion": 1, "runID": runID, "rowID": rowID,
            "observedTranscript": observed,
        ], options: [.sortedKeys])
        let attachment = XCTAttachment(data: data, uniformTypeIdentifier: "public.json")
        attachment.name = "history-transcript-observation"
        attachment.lifetime = .keepAlways
        add(attachment)
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: element("iosPlayer_close"), timeout: 20))
        XCTAssertTrue(VocelloUIWait.disappears(transcript, timeout: 20))
        replaceHistorySearch(with: "")
        dismissHistorySearchKeyboardIfNeeded()
        select(tab: .studio)
    }
}

/// Explicit operator cleanup, isolated from every Vocello acceptance journey.
/// No product launch environment or hidden app UI participates in this action.
@MainActor
final class VocelloiOSScreenProtectionUITests: XCTestCase {
    override func tearDown() {
        // XCTest assertion failures can abort before a Swift defer executes.
        XCUIDevice.shared.press(.home)
        super.tearDown()
    }

    func testConfiguredAutoLockAction() throws {
        continueAfterFailure = false
        let action = ProcessInfo.processInfo.environment["QVOICE_IOS_SCREEN_PROTECTION_ACTION"]
        guard action == "inspect" || action == "enable" else {
            XCTFail("Use the explicit screen-protection lane; authorization is missing")
            return
        }
        let settings = XCUIApplication(bundleIdentifier: "com.apple.Preferences")
        settings.launch()
        defer { XCUIDevice.shared.press(.home) }
        XCTAssertTrue(VocelloUIWait.condition("Settings foreground", timeout: 20) {
            settings.state == .runningForeground
        })

        func cell(_ names: [String]) -> XCUIElement {
            // iOS 26 Settings places the accessible name on a Button inside an
            // anonymous Cell. Match the actual named control, not its wrapper.
            let labels = names.map { name in
                NSPredicate(format: "label == %@ OR label BEGINSWITH %@", name, name + ",")
            }
            return settings.descendants(matching: .any).matching(NSCompoundPredicate(
                orPredicateWithSubpredicates: [NSPredicate(format: "identifier IN %@", names)] + labels
            )).firstMatch
        }
        func tap(_ control: XCUIElement) {
            XCTAssertTrue(VocelloUIPrimaryAction.perform(on: control, timeout: 15))
        }
        let display = cell(["DISPLAY", "Display & Brightness", "Luminosité et affichage", "Affichage et luminosité"])
        let autoLock = cell(["AUTOLOCK", "Auto-Lock", "Verrouillage automatique"])
        // The observed French picker uses a nonbreaking space and a seconds ID.
        let threeMinutes = cell(["180", "3 minutes", "3\u{00A0}minutes", "3 Minutes", "3 min"])
        func onAutoLockPage() -> Bool {
            settings.navigationBars["Auto-Lock"].exists
                || settings.navigationBars["Verrouillage automatique"].exists
                || settings.navigationBars["Verrouillage auto."].exists
        }

        // Settings can reopen an unrelated subpage. Only navigate back or scroll;
        // never touch another setting to reach Display & Brightness.
        var rootRewound = false
        for _ in 0..<12 {
            if autoLock.exists || onAutoLockPage() { break }
            if display.exists && display.isHittable {
                tap(display)
                XCTAssertTrue(VocelloUIWait.exists(autoLock, timeout: 15))
                break
            }
            let atRoot = settings.navigationBars["Settings"].exists
                || settings.navigationBars["Réglages"].exists
            if atRoot {
                if !rootRewound {
                    for _ in 0..<4 { settings.swipeDown() }
                    rootRewound = true
                } else {
                    settings.swipeUp()
                }
            } else {
                let back = settings.navigationBars.buttons.firstMatch
                XCTAssertTrue(VocelloUIWait.exists(back, timeout: 10))
                tap(back)
            }
        }
        if !onAutoLockPage() {
            for _ in 0..<6 {
                if autoLock.exists && autoLock.isHittable { break }
                settings.swipeUp()
            }
            XCTAssertTrue(VocelloUIWait.exists(autoLock, timeout: 15))
            tap(autoLock)
        }
        XCTAssertTrue(VocelloUIWait.condition("Auto-Lock settings page", timeout: 15) {
            onAutoLockPage()
        })
        XCTAssertTrue(VocelloUIWait.exists(threeMinutes, timeout: 15))
        XCTAssertTrue(threeMinutes.isEnabled, "Three-minute Auto-Lock is restricted or unavailable")
        VocelloUIScreenshot.attach(settings, named: "ios-auto-lock-before-\(action!)")

        if action == "enable" {
            tap(threeMinutes)
        }
        // Read back the parent row after leaving the picker: a tap alone never
        // proves the setting persisted. Inspect follows the same read-only path.
        tap(settings.navigationBars.buttons.firstMatch)
        XCTAssertTrue(VocelloUIWait.exists(autoLock, timeout: 15))
        if action == "enable" {
            XCTAssertTrue(VocelloUIWait.condition("three-minute Auto-Lock readback", timeout: 15) {
                let value = String(describing: autoLock.value ?? "")
                    .split(whereSeparator: \.isWhitespace).joined(separator: " ").lowercased()
                return value == "3 minutes" || value == "3 min"
                    || autoLock.staticTexts["3 minutes"].exists
                    || autoLock.staticTexts["3\u{00A0}minutes"].exists
            })
        }
        let evidence: [String: Any] = [
            "schemaVersion": 1,
            "action": action!,
            "autoLockValue": String(describing: autoLock.value ?? ""),
            "threeMinuteOptionAvailable": true,
            "threeMinutesVerified": action == "enable",
        ]
        let attachment = XCTAttachment(
            data: try JSONSerialization.data(withJSONObject: evidence, options: [.sortedKeys]),
            uniformTypeIdentifier: "public.json"
        )
        attachment.name = "screen-protection.json"
        attachment.lifetime = .keepAlways
        add(attachment)
        VocelloUIScreenshot.attach(settings, named: "ios-auto-lock-readback-\(action!)")
    }
}

/// One explicit physical-device journey. It exercises visible production UI
/// in a single app session, cancels one active streamed Custom generation,
/// and then completes exactly one Custom generation.
@MainActor
final class VocelloiOSSmokeUITests: VocelloiOSUITestCase {
    func testSettingsAccessibilityLayoutWalk() {
        defer {
            if session != nil { endSession() }
        }
        let categories: [(name: String, arguments: [String])] = [
            (
                name: "Default",
                arguments: ["-UIPreferredContentSizeCategoryName", "UICTContentSizeCategoryL"]
            ),
            (
                name: "French-Default",
                arguments: ["-AppleLanguages", "(fr)", "-AppleLocale", "fr_FR",
                            "-UIPreferredContentSizeCategoryName", "UICTContentSizeCategoryL"]
            ),
            (
                name: "AX-L",
                arguments: [
                    "-UIPreferredContentSizeCategoryName", "UICTContentSizeCategoryAccessibilityL",
                ]
            ),
            (
                name: "AX-XXXL",
                arguments: [
                    "-UIPreferredContentSizeCategoryName", "UICTContentSizeCategoryAccessibilityXXXL",
                ]
            ),
            (
                name: "Pseudo-AX-XXXL",
                arguments: [
                    "-UIPreferredContentSizeCategoryName", "UICTContentSizeCategoryAccessibilityXXXL",
                    "-NSDoubleLocalizedStrings", "YES",
                    "-NSShowNonLocalizedStrings", "YES",
                ]
            ),
        ]

        for category in categories {
            beginSession(additionalArguments: category.arguments)

            select(tab: .settings)
            let settings = element("screen_settings")
            openSettingsRoot()
            XCTAssertTrue(VocelloUIWait.exists(settings, timeout: 20))
            XCTAssertTrue(VocelloUIWait.exists(element("iosSettings_title"), timeout: 20))
            if category.name == "French-Default" {
                XCTAssertEqual(element("iosSettings_title").label, "Réglages")
                for (id, title) in [
                    ("rootTab_studio", "Studio"), ("rootTab_voices", "Voix"),
                    ("rootTab_history", "Historique"), ("rootTab_settings", "Réglages"),
                ] {
                    XCTAssertEqual(element(id).label, title,
                                   "The genuine dock must display French without changing its identifiers")
                }
            }
            openSettingsPage(for: "iosSettings_autoPlayToggle")
            let autoplay = element("iosSettings_autoPlayToggle")
            XCTAssertTrue(VocelloUIWait.exists(autoplay, timeout: 20))
            assertAboveTabDock(autoplay, named: "Play generated audio", category: category.name)
            assertAccessibilityControl(autoplay, named: "Play generated audio", category: category.name)
            VocelloUIScreenshot.attach(app, named: "ios-settings-\(category.name)-autoplay")
            openSettingsPage(for: "iosSettings_variationRow")
            let variation = element("iosSettings_variationRow")
            XCTAssertTrue(VocelloUIWait.exists(element("screen_settings_audio"), timeout: 20))
            XCTAssertTrue(VocelloUIWait.exists(autoplay, timeout: 20))
            XCTAssertTrue(VocelloUIWait.exists(variation, timeout: 20))
            assertAboveTabDock(variation, named: "Take variation", category: category.name)
            assertAccessibilityControl(variation, named: "Take variation", category: category.name)
            if category.name == "French-Default" {
                XCTAssertTrue(["Expressif", "Équilibré", "Cohérent"].contains(variation.value as? String ?? ""),
                              "Variation must expose its French display name without changing the saved value")
            }
            VocelloUIScreenshot.attach(app, named: "ios-settings-\(category.name)-landing")

            openSettingsPage(for: "iosSettings_versionLabel")
            let version = element("iosSettings_versionLabel")
            XCTAssertTrue(VocelloUIWait.exists(version, timeout: 20))
            XCTAssertFalse((version.value as? String ?? "").isEmpty, "About must expose the installed version and build")
            XCTAssertTrue(revealSettingsElement(version, swipingUp: true))
            assertAboveTabDock(version, named: "Version", category: category.name)
            VocelloUIScreenshot.attach(app, named: "ios-settings-\(category.name)-about")

            openVoiceModels()
            XCTAssertTrue(VocelloUIWait.exists(element("iosSettings_storageRow"), timeout: 20))
            let back = element("iosSettings_voiceModelsBackButton")
            assertAccessibilityControl(back, named: "Voice Models Back", category: category.name)

            let cloneStatus = element("iosModelStatus_pro_clone")
            XCTAssertTrue(VocelloUIWait.exists(cloneStatus, timeout: 60))
            XCTAssertTrue(revealSettingsElement(cloneStatus, swipingUp: true))
            assertAboveTabDock(cloneStatus, named: "Voice Cloning status", category: category.name)
            VocelloUIScreenshot.attach(app, named: "ios-settings-\(category.name)-voice-models")

            endSession()
        }
    }

    func testPhysicalDeviceSmokeJourney() {
        let runnerEnvironment = ProcessInfo.processInfo.environment
        // Xcode forwards inherited TEST_RUNNER_* variables to the remote test
        // runner after removing that transport prefix.
        guard let runID = runnerEnvironment["QVOICE_IOS_SMOKE_RUN_ID"],
              !runID.isEmpty else {
            XCTFail("Physical-device smoke requires a run-scoped diagnostics identity")
            return
        }
        let diagnosticsEnvironment = [
            "QVOICE_IOS_DEVICE_RUN_ID": runID,
            "QVOICE_MAC_BENCH_RUN_ID": runID,
        ]
        beginSession(additionalEnvironment: diagnosticsEnvironment)
        defer { endSession() }

        XCTAssertTrue(VocelloUIWait.exists(element("generateSection_custom"), timeout: 20))
        XCTAssertTrue(VocelloUIWait.exists(element("textInput_textEditor"), timeout: 20))

        for mode in VocelloUIBenchMatrix.Mode.allCases {
            select(mode: mode)
        }

        for tab in VocelloiOSTab.allCases {
            select(tab: tab)
        }

        assertSettingsLandingArchitecture()
        assertVisibleModelReadiness()
        ensureCloneConsentEnabled()
        VocelloUIScreenshot.attach(app, named: "ios-smoke-models-ready")

        _ = assertRequiredCloneVoice()
        VocelloUIScreenshot.attach(app, named: "ios-smoke-clone-voice-ready")

        _ = ensureAutoplayEnabled()
        prepare(mode: .custom)
        let nonce = String(
            UUID().uuidString.replacingOccurrences(of: "-", with: "").prefix(8)
        ).lowercased()
        let cancellationToken = "cancel\(nonce)"
        let memoryCancellationToken = "memory\(nonce)"
        let completionToken = "complete\(nonce)"
        let cancellationPrefix = "Cancellation \(cancellationToken). "
        let cancellationPrompt = cancellationPrefix + String(
            VocelloUIBenchMatrix.text(for: .long)
                .prefix(150 - cancellationPrefix.count)
        )
        let completionPrompt = "Completion \(completionToken). The train left the station at dawn."

        replaceScript(with: cancellationPrompt)
        startGenerationAndWaitForLivePreview()
        VocelloUIScreenshot.attach(app, named: "ios-smoke-cancellation-active")
        cancelActiveGenerationAndAssertTerminalUI()
        VocelloUIScreenshot.attach(app, named: "ios-smoke-cancellation-terminal")

        // Relaunch once with the registered one-shot debug policy. The visible
        // UI starts a normal production generation; the app's real memory guard
        // must cancel it, await terminal ownership, unload, and remain reusable.
        launchApp(
            additionalEnvironment: diagnosticsEnvironment.merging([
                "QVOICE_IOS_MEMORY_GUARD_FORCE_CRITICAL_ONCE": "1",
            ]) { _, override in override }
        )
        prepare(mode: .custom)
        let memoryPrefix = "Memory \(memoryCancellationToken). "
        let memoryPrompt = memoryPrefix + String(
            VocelloUIBenchMatrix.text(for: .long)
                .prefix(150 - memoryPrefix.count)
        )
        replaceScript(with: memoryPrompt)
        startGenerationAndWaitForAutomaticMemoryPressureTerminal()
        VocelloUIScreenshot.attach(app, named: "ios-smoke-memory-pressure-terminal")

        replaceScript(with: completionPrompt)
        _ = generateAndWaitForCompletedPlayer(timeout: 240)
        VocelloUIScreenshot.attach(app, named: "ios-smoke-custom-complete")

        replaceHistorySearch(with: completionToken)
        XCTAssertTrue(
            VocelloUIWait.condition("completed generation to appear exactly once in History", timeout: 30) {
                self.historyRows().count == 1
            },
            "The completed Custom take must appear exactly once in History"
        )

        replaceHistorySearch(with: cancellationToken)
        XCTAssertTrue(VocelloUIWait.exists(element("history_noMatchesState"), timeout: 30))
        XCTAssertEqual(historyRows().count, 0, "A cancelled take must never be committed to History")

        replaceHistorySearch(with: memoryCancellationToken)
        XCTAssertTrue(VocelloUIWait.exists(element("history_noMatchesState"), timeout: 30))
        XCTAssertEqual(
            historyRows().count,
            0,
            "A memory-pressure-cancelled take must never be committed to History"
        )
        VocelloUIScreenshot.attach(app, named: "ios-smoke-history")
    }

    private func assertAccessibilityControl(
        _ control: XCUIElement,
        named name: String,
        category: String
    ) {
        XCTAssertGreaterThanOrEqual(
            control.frame.height + 0.01,
            44,
            "\(name) must retain a 44-point target at \(category)"
        )
        XCTAssertGreaterThanOrEqual(control.frame.minX, app.frame.minX)
        XCTAssertLessThanOrEqual(control.frame.maxX, app.frame.maxX)
    }

    private func assertAboveTabDock(
        _ element: XCUIElement,
        named name: String,
        category: String
    ) {
        XCTAssertTrue(VocelloUISettingsReveal.perform(element, in: app, swipingUp: true,
                                                      requirement: .fullVisibility))
        guard let visible = VocelloUISettingsReveal.viewport(in: app) else {
            XCTFail("Missing whole-dock viewport at \(category)"); return
        }
        XCTAssertTrue(VocelloUIRevealRequirement.fullVisibility.satisfied(by: element.frame, visible: visible),
                      "\(name) must be fully visible above the whole tab dock at \(category)")
        XCTAssertGreaterThanOrEqual(element.frame.minX, app.frame.minX)
        XCTAssertLessThanOrEqual(element.frame.maxX, app.frame.maxX)
    }

    /// Long-form project journey: a script above the 900-character single-take
    /// limit routes to the sequential-streaming project path — planner
    /// segments, per-segment takes, joined output, and a grouped History
    /// project with a working per-segment disclosure. Mirrors the macOS
    /// `test06_LongFormProjectJourney` acceptance semantics on the paired
    /// physical iPhone.
    func testZLongFormProjectJourney() {
        let runnerEnvironment = ProcessInfo.processInfo.environment
        guard let runID = runnerEnvironment["QVOICE_IOS_SMOKE_RUN_ID"],
              !runID.isEmpty else {
            XCTFail("Physical-device smoke requires a run-scoped diagnostics identity")
            return
        }
        beginSession(additionalEnvironment: [
            "QVOICE_IOS_DEVICE_RUN_ID": runID,
            "QVOICE_MAC_BENCH_RUN_ID": runID,
        ])
        defer { endSession() }

        assertVisibleModelReadiness()
        prepare(mode: .custom)

        // Natural, deterministic speech. Ownership comes from a before/after
        // census of persisted IDs, never from a random token spoken by the model.
        let searchTitle = "An evening by the harbor."
        let paragraph = "The evening ferry crossed the quiet harbor while gulls circled the "
            + "breakwater and the lighthouse began its slow rotation over the bay. Along the "
            + "promenade the vendors folded their awnings, stacked crates of oranges, and "
            + "compared notes about the tide. Farther up the hill the windows brightened one "
            + "by one, and the smell of bread and woodsmoke drifted through narrow streets "
            + "that remembered a century of similar evenings. "
        var script = searchTitle + " "
        while script.count < 2_000 {
            script += paragraph
        }
        // The planner drops trailing whitespace. Use canonical fixture input so
        // exact History equality tests content preservation, not a trailing space.
        script = script.trimmingCharacters(in: .whitespacesAndNewlines)

        guard let beforeTitleIDs = historyRowCensus(expectedScript: searchTitle),
              let beforeJoinedIDs = historyRowCensus(expectedScript: script) else { return }
        select(tab: .studio)
        replaceScript(with: script)
        let generationID = generateAndWaitForCompletedPlayer(timeout: 900)
        guard !generationID.isEmpty else { return }
        VocelloUIScreenshot.attach(app, named: "ios-longform-complete")

        guard let afterJoinedIDs = historyRowCensus(expectedScript: script),
              let afterTitleIDs = historyRowCensus(expectedScript: searchTitle) else { return }
        let addedJoined = Set(afterJoinedIDs).subtracting(beforeJoinedIDs)
        let addedTitle = Set(afterTitleIDs).subtracting(beforeTitleIDs)
        guard Set(beforeJoinedIDs).isSubset(of: Set(afterJoinedIDs)),
              Set(beforeTitleIDs).isSubset(of: Set(afterTitleIDs)),
              addedJoined.count == 1, addedTitle.count == 2,
              let joinedID = addedJoined.first, addedTitle.contains(joinedID),
              let firstSegmentID = addedTitle.subtracting(addedJoined).first else {
            XCTFail("Long-form must add its joined output and first segment without changing prior History")
            return
        }
        replaceHistorySearch(with: script)
        dismissHistorySearchKeyboardIfNeeded()
        guard verifyHistoryTranscript(rowID: joinedID, expectedScript: script) else { return }

        // Without search, the project groups: one joined row plus a per-segment
        // disclosure that expands to the project's segment rows. Clear via the
        // genuine conditional button; an empty native field may expose a placeholder.
        replaceHistorySearch(with: "")
        let searchField = app.textFields["historySearchField"].firstMatch
        dismissHistorySearchKeyboardIfNeeded()
        guard revealHistoryRow(joinedID) != nil else { return }
        let segmentsToggle = app.descendants(matching: .any)
            .matching(NSPredicate(format: "identifier BEGINSWITH %@", "history_longFormSegmentsToggle_"))
            .firstMatch
        XCTAssertTrue(
            VocelloUIWait.exists(segmentsToggle, timeout: 30),
            "The grouped project row must expose its per-segment disclosure"
        )
        // Observe the exact newly persisted row, not text matches or total lazy-list count.
        let firstSegmentRow = element("historyRowTap_\(firstSegmentID)")
        XCTAssertFalse(firstSegmentRow.exists, "New project's segments must initially be collapsed")
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: segmentsToggle, timeout: 20))
        XCTAssertTrue(
            VocelloUIWait.condition("per-segment map to expand", timeout: 20) {
                firstSegmentRow.exists
            },
            "Expanding the newest project must reveal its exact first segment"
        )
        VocelloUIScreenshot.attach(app, named: "ios-longform-history-project")

        // Single-segment regeneration acceptance (manifest-v4 replacement
        // lineage on iOS): the retained completed project exposes the
        // in-session segments menu in the studio setup row; regenerating the
        // first segment runs one ordinary streaming take with a fresh
        // recorded seed, reassembles the joined output, and leaves the studio
        // clean with the project still regenerable. Mirrors the macOS
        // replacement-flow acceptance.
        //
        // The History search keyboard obscures the tab bar; Return on a search
        // field is a semantic dismissal, not a coordinate tap.
        if app.keyboards.firstMatch.exists {
            searchField.typeText("\n")
            XCTAssertTrue(
                VocelloUIWait.condition("history search keyboard to dismiss", timeout: 15) {
                    !self.app.keyboards.firstMatch.exists
                }
            )
        }
        prepare(mode: .custom)
        let segmentsChip = element("iosLongForm_segmentsChip")
        XCTAssertTrue(
            VocelloUIWait.exists(segmentsChip, timeout: 30),
            "The retained completed project must expose the segments menu chip"
        )
        XCTAssertTrue(VocelloUIWait.enabled(segmentsChip, timeout: 30))
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: segmentsChip, timeout: 20))
        // Dialog buttons occasionally drop identifiers in the on-device tree;
        // match the genuine visible label as the equal-priority fallback.
        let firstSegmentItem = app.buttons.matching(
            NSPredicate(
                format: "identifier == %@ OR label BEGINSWITH %@",
                "iosLongForm_regenerateSegment_0", "Segment 1:"
            )
        ).firstMatch
        XCTAssertTrue(
            VocelloUIWait.exists(firstSegmentItem, timeout: 20),
            "The segments dialog must list the project's first segment"
        )
        let completedPlayer = element("studio_inlinePlayer_playPause")
        let generationError = element("textInput_generationError")
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: firstSegmentItem, timeout: 20))
        // The chip leaves the tree while the replacement runs (isProcessing
        // hides it), so this wait must stay existence-only — a property query
        // on a vanished element throws instead of returning false.
        XCTAssertTrue(
            VocelloUIWait.condition("segment regeneration to visibly start", timeout: 60) {
                !segmentsChip.exists || !completedPlayer.exists
            },
            "Choosing a segment must visibly start the replacement generation"
        )
        XCTAssertTrue(
            VocelloUIWait.condition("regenerated project to reassemble", timeout: 600) {
                completedPlayer.exists || generationError.exists
            }
        )
        XCTAssertFalse(
            generationError.exists,
            "Segment regeneration must not surface the visible error control"
        )
        XCTAssertTrue(
            VocelloUIWait.condition("segments chip to return after reassembly", timeout: 60) {
                segmentsChip.exists
            },
            "The replaced project must remain regenerable in-session"
        )
        XCTAssertTrue(VocelloUIWait.enabled(segmentsChip, timeout: 60))
        // RF-04 retains the old accepted joined output when publishing a replacement.
        guard let regeneratedJoinedIDs = historyRowCensus(expectedScript: script) else { return }
        let replacementIDs = Set(regeneratedJoinedIDs).subtracting(afterJoinedIDs)
        guard Set(afterJoinedIDs).isSubset(of: Set(regeneratedJoinedIDs)),
              replacementIDs.count == 1, let replacementID = replacementIDs.first,
              verifyHistoryTranscript(rowID: replacementID, expectedScript: script) else {
            XCTFail("Replacement must preserve prior joined History and add one transcript-verified output")
            return
        }
        VocelloUIScreenshot.attach(app, named: "ios-longform-regenerated")
    }
}
