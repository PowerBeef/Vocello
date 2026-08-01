import XCTest

/// One explicit physical-device journey. It exercises visible production UI
/// in a single app session, cancels one active streamed Custom generation,
/// and then completes exactly one Custom generation.
@MainActor
final class VocelloiOSSmokeUITests: VocelloiOSUITestCase {
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

        // Pronounceable nonce (hex nonces read as spelled letters and perturb
        // the QC pause budget — macOS acceptance lesson).
        let nonce = String((0..<8).map { _ in "abcdefghijklmnopqrstuvwxyz".randomElement()! })
        let paragraph = "The evening ferry crossed the quiet harbor while gulls circled the "
            + "breakwater and the lighthouse began its slow rotation over the bay. Along the "
            + "promenade the vendors folded their awnings, stacked crates of oranges, and "
            + "compared notes about the tide. Farther up the hill the windows brightened one "
            + "by one, and the smell of bread and woodsmoke drifted through narrow streets "
            + "that remembered a century of similar evenings. "
        var script = "Project \(nonce). "
        while script.count < 2_000 {
            script += paragraph
        }

        replaceScript(with: script)
        _ = generateAndWaitForCompletedPlayer(timeout: 900)
        VocelloUIScreenshot.attach(app, named: "ios-longform-complete")

        // Search flattens: the nonce lands in the first segment and the joined
        // transcript — exactly two flat rows.
        replaceHistorySearch(with: nonce)
        XCTAssertTrue(
            VocelloUIWait.condition("first segment + joined output to appear in History search", timeout: 30) {
                self.historyRows().count == 2
            },
            "Search must surface exactly the first segment and the joined output"
        )

        // Without search, the project groups: one joined row plus a per-segment
        // disclosure that expands to the project's segment rows. Clear the
        // field directly and wait on the grouped outcome — an empty
        // UITextField reports its placeholder as `value`, so the helper's
        // value-echo assertion cannot confirm an empty query.
        let searchField = app.textFields["historySearchField"].firstMatch
        XCTAssertTrue(VocelloUIWait.exists(searchField, timeout: 30))
        XCTAssertTrue(VocelloUITextEntry.replace(in: searchField, with: "", timeout: 20))
        let segmentsToggle = app.descendants(matching: .any)
            .matching(NSPredicate(format: "identifier BEGINSWITH %@", "history_longFormSegmentsToggle_"))
            .firstMatch
        XCTAssertTrue(
            VocelloUIWait.exists(segmentsToggle, timeout: 30),
            "The grouped project row must expose its per-segment disclosure"
        )
        // Count nonce-bearing rows, not total rows: the lazy list drops older
        // rows out of the instantiated window as segment rows appear, so a
        // total-count delta is not stable. The nonce rows (joined + first
        // segment) sit at the top of the newest project and are always
        // instantiated: collapsed shows one, expanded shows both.
        let nonceRows = app.descendants(matching: .any).matching(
            NSPredicate(
                format: "identifier BEGINSWITH %@ AND label CONTAINS %@",
                "historyRowTap_", nonce
            )
        )
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: segmentsToggle, timeout: 20))
        XCTAssertTrue(
            VocelloUIWait.condition("per-segment map to expand", timeout: 20) {
                nonceRows.count == 2
            },
            "Expanding the newest project must reveal the nonce-bearing first segment beside the joined row"
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
        // No data loss: the nonce still surfaces both the joined output and a
        // first-segment row in History search.
        replaceHistorySearch(with: nonce)
        XCTAssertTrue(
            VocelloUIWait.condition("nonce rows to survive the replacement", timeout: 30) {
                self.historyRows().count >= 2
            },
            "Replacement must keep the joined output and segment history searchable"
        )
        VocelloUIScreenshot.attach(app, named: "ios-longform-regenerated")
    }
}
