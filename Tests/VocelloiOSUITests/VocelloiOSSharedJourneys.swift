import Foundation
import XCTest

/// Journeys that both the development smoke lane and the RF-15 candidate lane
/// run, so a TestFlight build is held to the same visible-UI acceptance.
extension VocelloiOSUITestCase {
    /// `ReferenceClipRecorder.minDuration`, which the app target owns.
    static let recorderMinimumSeconds: TimeInterval = 10

    /// AUD-02 record-then-play; `testRecordThenPlayReviewsTheClip` documents it.
    func recordThenPlayReview() {
        // Clone's reference chip opens the recorder whatever Saved Voices holds;
        // the Voices card can sit below a long list.
        select(mode: .clone)
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: element("studioChip_reference"), timeout: 20))
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: element("referenceClip_recordNewClip"), timeout: 20))
        XCTAssertTrue(
            VocelloUIPrimaryAction.perform(on: element("iosRecord_start"), timeout: 90),
            "the recorder must offer Record (a first run waits for the microphone prompt)"
        )
        // Typed: the level meter redraws while recording, and an untyped query can
        // time out on its snapshots.
        let stop = VocelloUIWait.element(app, id: "iosRecord_stop", type: .button)
        XCTAssertTrue(VocelloUIWait.exists(stop, timeout: 20), "recording must start")
        let recordingStarted = Date()
        XCTAssertTrue(
            VocelloUIWait.condition("the clip to pass the recorder's minimum", timeout: 30) {
                Date().timeIntervalSince(recordingStarted) >= Self.recorderMinimumSeconds + 1
            }
        )
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: stop, timeout: 20))
        VocelloUIScreenshot.attach(app, named: "ios-smoke-record-review")

        let play = element("saveVoice_playClip")
        XCTAssertTrue(VocelloUIWait.exists(play, timeout: 30), "the save sheet reviews the recorded clip")
        let idleLabel = play.label
        XCTAssertTrue(
            VocelloUIPrimaryAction.perform(on: play, timeout: 90),
            "the review must offer Play (a first run waits for the speech prompt)"
        )
        XCTAssertTrue(
            VocelloUIWait.condition("the recorded clip to start playing", timeout: 15) {
                play.exists && play.label != idleLabel
            },
            "playback after a recording must start"
        )
        XCTAssertTrue(
            VocelloUIWait.condition("the recorded clip to play to its end", timeout: 45) {
                play.exists && play.label == idleLabel
            },
            "playback after a recording must reach the clip's end"
        )

        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: element("bottomSheet_close"), timeout: 20))
        XCTAssertTrue(
            VocelloUIWait.exists(element("studioChip_reference"), timeout: 20),
            "closing the review returns to the Studio without saving"
        )
    }

    /// Long-form project and single-segment regeneration; `testZLongFormProjectJourney`
    /// documents it.
    func runLongFormProjectJourney() {
        assertVisibleModelReadiness()
        // RF-18 C-03: Take variation is a persisted setting, and both failing
        // October smokes inherited Consistent. Pin Expressive, the default, so
        // the journey measures the default path; the session restores the
        // original. Consistent's long-form stalls are a 3.0 known limitation.
        pinVariationForSession("expressive")
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

        // History is searched by the script's title token, which both the joined output
        // and its first segment carry, never by the 2,000-character script: typing that
        // into the search field cost about 37 s a time, three times a journey.
        guard let beforeTitleIDs = historyRowCensus(expectedScript: searchTitle) else { return }
        select(tab: .studio)
        replaceScript(with: script)
        XCTAssertTrue(VocelloUIWait.exists(element("textInput_longFormIndicator"), timeout: 15))
        let generationID = generateAndWaitForCompletedPlayer(timeout: 900)
        guard !generationID.isEmpty else { return }
        VocelloUIScreenshot.attach(app, named: "ios-longform-complete")

        guard let afterTitleIDs = historyRowCensus(expectedScript: searchTitle) else { return }
        let addedTitle = Set(afterTitleIDs).subtracting(beforeTitleIDs)
        guard Set(beforeTitleIDs).isSubset(of: Set(afterTitleIDs)), addedTitle.count == 2 else {
            XCTFail("Long-form must add its joined output and first segment without changing prior History")
            return
        }
        // The joined output is the new row whose full transcript is the whole script; the
        // other new row is its first segment, a shorter non-empty part of it.
        var transcripts: [String: String] = [:]
        for rowID in addedTitle.sorted() {
            guard let transcript = historyTranscript(rowID: rowID) else { return }
            transcripts[rowID] = transcript
        }
        let joinedIDs = transcripts.filter { $0.value == script }.map(\.key)
        guard joinedIDs.count == 1, let joinedID = joinedIDs.first,
              let firstSegmentID = addedTitle.subtracting([joinedID]).first,
              let segmentTranscript = transcripts[firstSegmentID],
              segmentTranscript.count < script.count, script.hasPrefix(segmentTranscript),
              segmentTranscript.hasPrefix(searchTitle) else {
            let attachment = XCTAttachment(string: transcripts.sorted { $0.key < $1.key }
                .map { "\($0.key): \($0.value.count) characters" }.joined(separator: "\n"))
            attachment.name = "long-form-new-rows.txt"
            attachment.lifetime = .keepAlways
            add(attachment)
            XCTFail("Exactly one new row must carry the whole script, and the other its first segment")
            return
        }

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
        let liveCancel = element("studio_livePreview_cancel")
        XCTAssertTrue(
            VocelloUIWait.progressing(
                "regenerated project to reassemble", timeout: 600, stallBudget: 180,
                progress: {
                    "live=\(liveCancel.exists) chip=\(segmentsChip.exists ? segmentsChip.label : "-") player=\(completedPlayer.exists)"
                }
            ) {
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
        guard let regeneratedTitleIDs = historyRowCensus(expectedScript: searchTitle) else { return }
        guard Set(afterTitleIDs).isSubset(of: Set(regeneratedTitleIDs)) else {
            XCTFail("Replacement must preserve prior joined History")
            return
        }
        // Acceptance adds the replacement first segment and a new joined output.
        let regeneratedIDs = Set(regeneratedTitleIDs).subtracting(afterTitleIDs)
        var replacementIDs: [String] = []
        var segmentReplacements = 0
        for rowID in regeneratedIDs.sorted() {
            guard let transcript = historyTranscript(rowID: rowID) else { return }
            if transcript == script {
                replacementIDs.append(rowID)
            } else if transcript.count < script.count, script.hasPrefix(transcript), transcript.hasPrefix(searchTitle) {
                segmentReplacements += 1
            }
        }
        guard regeneratedIDs.count == 2, replacementIDs.count == 1, segmentReplacements == 1 else {
            XCTFail("Replacement must add exactly one transcript-verified joined output and its first segment")
            return
        }
        VocelloUIScreenshot.attach(app, named: "ios-longform-regenerated")
    }
}
