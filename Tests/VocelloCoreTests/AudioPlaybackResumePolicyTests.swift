import XCTest

final class AudioPlaybackResumePolicyTests: XCTestCase {
    func testExplicitPlayResumesHeardPositionRatherThanBufferedPreviewEnd() {
        // Physical regression: the complete 17.36-second preview was buffered;
        // the user paused at 15 seconds. Automatic completion returned false.
        let decision = AudioPlaybackResumePolicy.explicitPlay(currentTime: 15, duration: 17.36)
        XCTAssertEqual(decision.position, 15)
        XCTAssertTrue(decision.shouldPlay)
    }

    func testExplicitPlayAtOrBeyondEndRestartsWithoutASecondTap() {
        for position in [17.36, 18, 100] {
            let decision = AudioPlaybackResumePolicy.explicitPlay(currentTime: position, duration: 17.36)
            XCTAssertEqual(decision.position, 0)
            XCTAssertTrue(decision.shouldPlay)
        }
    }

    func testExplicitPlayPreservesNearEndPositionAndDoesNotApplyAutoplayThreshold() {
        let decision = AudioPlaybackResumePolicy.explicitPlay(currentTime: 17.30, duration: 17.36)
        XCTAssertEqual(decision.position, 17.30)
        XCTAssertTrue(decision.shouldPlay)
    }

    func testExplicitPlayClampsUnusablePositionWithoutFabricatingDuration() {
        let positions: [Double] = [-1, .nan, .infinity, -.infinity]
        for position in positions {
            let decision = AudioPlaybackResumePolicy.explicitPlay(currentTime: position, duration: 10)
            XCTAssertEqual(decision.position, 0)
            XCTAssertTrue(decision.shouldPlay)
        }
        let durations: [Double] = [0, -1, .nan, .infinity, -.infinity]
        for duration in durations {
            let decision = AudioPlaybackResumePolicy.explicitPlay(currentTime: 1, duration: duration)
            XCTAssertEqual(decision.position, 0)
            XCTAssertFalse(decision.shouldPlay)
        }
    }
}

final class GenerationPlaybackOwnershipTests: XCTestCase {
    func testInternalSegmentCleanupPreservesFinalPlaybackWithoutAcceptingLateChunks() {
        var owner = GenerationPlaybackOwnership()
        let operation = UUID(), stream = UUID()
        owner.begin(operation)
        XCTAssertTrue(owner.claimStream(stream, operationID: operation))
        owner.finishStream(operationID: operation)
        XCTAssertFalse(owner.acceptsChunk(stream))
        XCTAssertTrue(owner.owns(operation))
        owner.revoke()
        owner.finishStream(operationID: operation)
        XCTAssertFalse(owner.owns(operation))
    }

    func testDismissBeforeFirstChunkRejectsBothStreamAndCompletion() {
        var owner = GenerationPlaybackOwnership()
        let operation = UUID(), stream = UUID()
        owner.begin(operation)
        XCTAssertTrue(owner.claimStream(stream, operationID: operation))
        owner.revoke()
        XCTAssertFalse(owner.acceptsChunk(stream))
        XCTAssertFalse(owner.owns(operation))
    }

    func testSelectingLibraryAudioCannotBeUndoneByTheNextBatchLine() {
        var owner = GenerationPlaybackOwnership()
        let operation = UUID(), first = UUID(), next = UUID()
        owner.begin(operation)
        XCTAssertTrue(owner.claimStream(first, operationID: operation))
        owner.revoke()
        XCTAssertFalse(owner.claimStream(next, operationID: operation))
        XCTAssertFalse(owner.acceptsChunk(first))
        XCTAssertFalse(owner.acceptsChunk(next))
        XCTAssertFalse(owner.owns(operation))
    }

    func testLongFormSegmentsShareOwnershipButRejectOldChunks() {
        var owner = GenerationPlaybackOwnership()
        let operation = UUID(), first = UUID(), next = UUID()
        owner.begin(operation)
        XCTAssertTrue(owner.claimStream(first, operationID: operation))
        XCTAssertTrue(owner.acceptsChunk(first))
        XCTAssertTrue(owner.claimStream(next, operationID: operation))
        XCTAssertFalse(owner.acceptsChunk(first))
        XCTAssertTrue(owner.acceptsChunk(next))
        XCTAssertTrue(owner.owns(operation), "The joined output retains the same operation")
    }

    func testNewExplicitGenerationCanPlayWithoutReauthorizingOldResults() {
        var owner = GenerationPlaybackOwnership()
        let old = UUID(), new = UUID(), oldStream = UUID(), newStream = UUID()
        owner.begin(old)
        XCTAssertTrue(owner.claimStream(oldStream, operationID: old))
        owner.revoke()
        owner.begin(new)
        XCTAssertFalse(owner.acceptsChunk(oldStream))
        XCTAssertFalse(owner.claimStream(oldStream, operationID: old))
        XCTAssertFalse(owner.owns(old))
        XCTAssertTrue(owner.claimStream(newStream, operationID: new))
        XCTAssertTrue(owner.acceptsChunk(newStream))
        XCTAssertTrue(owner.owns(new))
    }

    func testUnregisteredChunksNeverTakeOverThePlayer() {
        var owner = GenerationPlaybackOwnership()
        XCTAssertFalse(owner.acceptsChunk(nil))
        XCTAssertFalse(owner.acceptsChunk(UUID()))
        owner.begin(UUID())
        XCTAssertFalse(owner.acceptsChunk(nil))
        XCTAssertFalse(owner.acceptsChunk(UUID()))
    }
}

final class PlaybackTransportPlacementTests: XCTestCase {
    func testActiveStudioTakeAlwaysHasExactlyOneInlineTransport() {
        for sidebar in [false, true] {
            XCTAssertEqual(PlaybackTransportPlacement.resolve(
                hasAudio: true, studioOwnsAudio: true, sidebarVisible: sidebar), .studio)
        }
    }

    func testLibraryOrDifferentStudioTakeFollowsSidebarVisibility() {
        XCTAssertEqual(PlaybackTransportPlacement.resolve(
            hasAudio: true, studioOwnsAudio: false, sidebarVisible: true), .sidebar)
        XCTAssertEqual(PlaybackTransportPlacement.resolve(
            hasAudio: true, studioOwnsAudio: false, sidebarVisible: false), .detail)
    }

    func testDismissedAudioLeavesNoGlobalTransport() {
        for sidebar in [false, true] {
            XCTAssertEqual(PlaybackTransportPlacement.resolve(
                hasAudio: false, studioOwnsAudio: false, sidebarVisible: sidebar), .none)
        }
    }
}

/// U04/U06: a user or system pause holds the live preview until Play; an
/// underrun does not. Each test drives the same start, completion and handoff
/// decisions the shared player makes, from the autoplay state it keeps.
final class LivePreviewAutoplayStateTests: XCTestCase {
    private let estimate = LivePreviewEstimate(text: String(repeating: "word ", count: 60))

    private func chunkStartsPlayback(
        _ state: LivePreviewAutoplayState, queued: TimeInterval
    ) -> LivePreviewStartPolicy.Decision {
        LivePreviewStartPolicy.decide(
            autoplayEnabled: state.allowsAutomaticPlayback,
            queuedChunks: 40,
            queuedDuration: queued,
            prebufferThreshold: 3,
            minimumBufferedDuration: 3.25,
            finalFileAvailable: false,
            estimate: estimate
        )
    }

    func testUserPauseIsNotUndoneByLaterChunksOrTheFinalHandoff() {
        var state = LivePreviewAutoplayState()
        state.beginSession(operationID: nil, autoplayPreference: true)
        XCTAssertEqual(chunkStartsPlayback(state, queued: 12), .start)

        state.hold()
        for queued in [8.0, 12, 20, 40] {
            XCTAssertEqual(chunkStartsPlayback(state, queued: queued), .rejectAutoplay,
                           "a chunk past the prebuffer must not resume a paused preview")
        }
        XCTAssertEqual(LivePreviewStartPolicy.decide(
            autoplayEnabled: state.allowsAutomaticPlayback, queuedChunks: 40, queuedDuration: 12,
            prebufferThreshold: 3, minimumBufferedDuration: 3.25, finalFileAvailable: true, estimate: estimate
        ), .rejectAutoplay, "a late chunk after completion must not hand off to the file either")
        XCTAssertEqual(LivePreviewCompletionPolicy.decide(
            previewStarted: true, queuedBuffers: 30, isPlaying: false,
            allowsAutomaticPlayback: state.allowsAutomaticPlayback, previewDisabled: false
        ), .awaitDrain, "completion leaves a held preview where the listener paused it")
        XCTAssertFalse(LivePreviewFinalHandoff.resolve(
            heardLivePreview: false, currentTime: 0, duration: 4,
            autoPlayEnabled: state.allowsAutomaticPlayback
        ).shouldAutoPlay, "a held take that never started does not autoplay its file")
    }

    func testUnderrunKeepsAutomaticResume() {
        var state = LivePreviewAutoplayState()
        state.beginSession(operationID: nil, autoplayPreference: true)
        // The underrun pauses the node directly; the state is untouched.
        XCTAssertTrue(state.allowsAutomaticPlayback)
        XCTAssertEqual(chunkStartsPlayback(state, queued: 1), .rejectBuffer)
        XCTAssertEqual(chunkStartsPlayback(state, queued: 12), .start)
    }

    func testExplicitPlayReleasesTheHold() {
        var state = LivePreviewAutoplayState()
        state.beginSession(operationID: nil, autoplayPreference: true)
        state.hold()
        state.play()
        XCTAssertTrue(state.allowsAutomaticPlayback)
        XCTAssertFalse(state.isHeld)
        XCTAssertEqual(chunkStartsPlayback(state, queued: 12), .start)
    }

    func testExplicitPlayWithAutoplayOffLetsUnderrunsResume() {
        var state = LivePreviewAutoplayState()
        state.beginSession(operationID: nil, autoplayPreference: false)
        XCTAssertFalse(state.allowsAutomaticPlayback)
        state.play()
        XCTAssertTrue(state.allowsAutomaticPlayback)
    }

    func testOperationHoldCarriesToItsNextTakeAndJoinedOutput() {
        let operation = UUID()
        var state = LivePreviewAutoplayState()
        state.beginSession(operationID: operation, autoplayPreference: true)
        state.hold()
        state.endSession()
        XCTAssertFalse(state.allowsAutomaticFinalPlayback(operationID: operation, autoplayPreference: true),
                       "the operation's joined output respects the hold after the session is gone")
        state.beginSession(operationID: operation, autoplayPreference: true)
        XCTAssertTrue(state.isHeld)
        XCTAssertFalse(state.allowsAutomaticPlayback, "the next segment or line does not start on its own")

        state.play()
        state.endSession()
        state.beginSession(operationID: operation, autoplayPreference: false)
        XCTAssertTrue(state.allowsAutomaticPlayback, "an explicit Play carries through the operation")
    }

    func testAnotherOperationOrLoneTakeStartsFromThePreference() {
        var state = LivePreviewAutoplayState()
        state.beginSession(operationID: UUID(), autoplayPreference: true)
        state.hold()
        state.endSession()
        state.beginSession(operationID: UUID(), autoplayPreference: true)
        XCTAssertTrue(state.allowsAutomaticPlayback)

        state.beginSession(operationID: nil, autoplayPreference: true)
        state.hold()
        state.endSession()
        XCTAssertFalse(state.isHeld, "a lone take's hold ends with it")
        state.beginSession(operationID: nil, autoplayPreference: true)
        XCTAssertTrue(state.allowsAutomaticPlayback)
        XCTAssertTrue(state.allowsAutomaticFinalPlayback(operationID: nil, autoplayPreference: true))
        XCTAssertFalse(state.allowsAutomaticFinalPlayback(operationID: nil, autoplayPreference: false))
    }

    func testOtherPlaybackBeforeTheFirstChunkHoldsTheSubmittedTake() {
        var state = LivePreviewAutoplayState()
        state.holdUpcomingSession()
        XCTAssertFalse(state.allowsAutomaticFinalPlayback(operationID: nil, autoplayPreference: true),
                       "a result that did not stream does not autoplay either")
        state.beginSession(operationID: nil, autoplayPreference: true)
        XCTAssertFalse(state.allowsAutomaticPlayback)
        XCTAssertFalse(state.holdsUpcomingSession)
        state.play()
        XCTAssertTrue(state.allowsAutomaticPlayback)

        var next = LivePreviewAutoplayState()
        next.holdUpcomingSession()
        next.clearUpcomingHold()
        next.beginSession(operationID: nil, autoplayPreference: true)
        XCTAssertTrue(next.allowsAutomaticPlayback, "a newly submitted take is not held by an earlier one")
    }

    func testPauseWhileTheLastTakePlaysHoldsTheTakeSubmittedAfterIt() {
        // S4: take A plays, take B is submitted (no session yet), the
        // listener pauses A; B's start tears A down, which ends A's own hold.
        var state = LivePreviewAutoplayState()
        state.beginSession(operationID: nil, autoplayPreference: true)
        state.hold()
        state.holdUpcomingSession()
        state.endSession()
        XCTAssertFalse(state.isHeld)
        state.beginSession(operationID: nil, autoplayPreference: true)
        XCTAssertFalse(state.allowsAutomaticPlayback, "B waits for Play")

        var resumed = LivePreviewAutoplayState()
        resumed.beginSession(operationID: nil, autoplayPreference: true)
        resumed.hold()
        resumed.holdUpcomingSession()
        resumed.play()
        XCTAssertFalse(resumed.holdsUpcomingSession, "Play on the shared player resumes the narration")
    }

    func testLoadingOtherAudioForgetsTheOperation() {
        let operation = UUID()
        var state = LivePreviewAutoplayState()
        state.beginSession(operationID: operation, autoplayPreference: true)
        state.hold()
        state.reset()
        XCTAssertNil(state.operationID)
        XCTAssertFalse(state.allowsAutomaticPlayback, "no session, nothing plays on its own")
        state.beginSession(operationID: operation, autoplayPreference: true)
        XCTAssertTrue(state.allowsAutomaticPlayback)
    }
}

/// U05: after an underrun, the tail generated before completion is played out
/// even when it is shorter than the prebuffer the resume waits for.
final class LivePreviewCompletionPolicyTests: XCTestCase {
    func testSubPrebufferTailAfterAnUnderrunPlaysOutAtCompletion() {
        // A ~4 s take: the preview started early, underran, and the remaining
        // ~2.9 s stays below the 3.25 s the resume needs.
        let estimate = LivePreviewEstimate(text: "one two three four five six seven eight nine ten")
        XCTAssertEqual(LivePreviewStartPolicy.decide(
            autoplayEnabled: true, queuedChunks: 9, queuedDuration: 2.9,
            prebufferThreshold: 3, minimumBufferedDuration: 3.25, finalFileAvailable: false,
            underrunCount: 1, estimate: estimate
        ), .rejectBuffer, "the stall: no further chunk will arrive to fill the prebuffer")
        XCTAssertEqual(LivePreviewCompletionPolicy.decide(
            previewStarted: true, queuedBuffers: 9, isPlaying: false,
            allowsAutomaticPlayback: true, previewDisabled: false
        ), .playOutQueuedTail)
    }

    func testDrainedOrUnstartedPreviewHandsOffAtOnce() {
        XCTAssertEqual(LivePreviewCompletionPolicy.decide(
            previewStarted: false, queuedBuffers: 5, isPlaying: false,
            allowsAutomaticPlayback: true, previewDisabled: false
        ), .handOffNow)
        XCTAssertEqual(LivePreviewCompletionPolicy.decide(
            previewStarted: true, queuedBuffers: 0, isPlaying: false,
            allowsAutomaticPlayback: true, previewDisabled: false
        ), .handOffNow)
    }

    func testPlayingHeldOrDisabledPreviewWaitsForItsDrain() {
        XCTAssertEqual(LivePreviewCompletionPolicy.decide(
            previewStarted: true, queuedBuffers: 5, isPlaying: true,
            allowsAutomaticPlayback: true, previewDisabled: false
        ), .awaitDrain)
        XCTAssertEqual(LivePreviewCompletionPolicy.decide(
            previewStarted: true, queuedBuffers: 5, isPlaying: false,
            allowsAutomaticPlayback: false, previewDisabled: false
        ), .awaitDrain)
        XCTAssertEqual(LivePreviewCompletionPolicy.decide(
            previewStarted: true, queuedBuffers: 5, isPlaying: false,
            allowsAutomaticPlayback: true, previewDisabled: true
        ), .awaitDrain)
    }
}

final class LivePreviewStartPolicyTests: XCTestCase {
    func testEstimatePrebufferAndFinalFile() {
        let estimate = LivePreviewEstimate(text: String(repeating: "word ", count: 60))
        XCTAssertEqual(LivePreviewStartPolicy.decide(
            autoplayEnabled: true, queuedChunks: 1, queuedDuration: 3,
            prebufferThreshold: 3, minimumBufferedDuration: 3.25, finalFileAvailable: false, estimate: estimate
        ), .rejectBuffer)
        XCTAssertEqual(LivePreviewStartPolicy.decide(
            autoplayEnabled: true, queuedChunks: 1, queuedDuration: 9,
            prebufferThreshold: 3, minimumBufferedDuration: 3.25, finalFileAvailable: false, estimate: estimate
        ), .start)
        XCTAssertEqual(LivePreviewStartPolicy.decide(
            autoplayEnabled: true, queuedChunks: 0, queuedDuration: 0,
            prebufferThreshold: 3, minimumBufferedDuration: 3.25, finalFileAvailable: true, estimate: estimate
        ), .start)
    }

    func testAdaptiveFallbackGrowsWithUnderruns() {
        XCTAssertEqual(LivePreviewStartPolicy.decide(
            autoplayEnabled: true, queuedChunks: 3, queuedDuration: 3.25,
            prebufferThreshold: 3, minimumBufferedDuration: 3.25, finalFileAvailable: false
        ), .start)
        XCTAssertEqual(LivePreviewStartPolicy.decide(
            autoplayEnabled: true, queuedChunks: 5, queuedDuration: 6,
            prebufferThreshold: 3, minimumBufferedDuration: 3.25, finalFileAvailable: false, underrunCount: 1
        ), .rejectBuffer)
        XCTAssertEqual(LivePreviewStartPolicy.decide(
            autoplayEnabled: true, queuedChunks: 6, queuedDuration: 5.6875,
            prebufferThreshold: 3, minimumBufferedDuration: 3.25, finalFileAvailable: false, underrunCount: 1
        ), .start)
    }
}

final class LivePreviewFinalHandoffTests: XCTestCase {
    func testUnheardPreviewStartsTheFileFromZeroWhenAllowed() {
        XCTAssertEqual(
            LivePreviewFinalHandoff.resolve(heardLivePreview: false, currentTime: 2, duration: 4, autoPlayEnabled: true),
            LivePreviewFinalHandoff(preserveCurrentTime: 0, shouldAutoPlay: true)
        )
    }

    func testFullyHeardPreviewLoadsTheFileWithoutReplaying() {
        XCTAssertEqual(
            LivePreviewFinalHandoff.resolve(
                heardLivePreview: true, currentTime: 3, previewDuration: 10, duration: 10, autoPlayEnabled: true
            ),
            LivePreviewFinalHandoff(preserveCurrentTime: 0, shouldAutoPlay: false)
        )
    }

    func testHeldPreviewKeepsItsPositionWithoutPlaying() {
        // S3: a held take's file loads where the listener stopped.
        XCTAssertEqual(
            LivePreviewFinalHandoff.resolve(
                heardLivePreview: true, currentTime: 4, previewDuration: 4, duration: 10, autoPlayEnabled: false
            ),
            LivePreviewFinalHandoff(preserveCurrentTime: 4, shouldAutoPlay: false)
        )
        XCTAssertEqual(
            LivePreviewFinalHandoff.resolve(
                heardLivePreview: true, currentTime: 9.95, previewDuration: 9.95, duration: 10, autoPlayEnabled: false
            ),
            LivePreviewFinalHandoff(preserveCurrentTime: 0, shouldAutoPlay: false),
            "a take held at its end starts over on Play"
        )
    }

    func testInterruptedPreviewContinuesAtTheHeardPosition() {
        XCTAssertEqual(
            LivePreviewFinalHandoff.resolve(
                heardLivePreview: true, currentTime: 4, previewDuration: 4, duration: 10, autoPlayEnabled: true
            ),
            LivePreviewFinalHandoff(preserveCurrentTime: 4, shouldAutoPlay: true)
        )
    }
}

/// U07: within one operation the next take waits for the take still playing.
final class LivePreviewSuccessionPolicyTests: XCTestCase {
    func testNextTakeOfTheOperationWaitsForTheTakeThatPlays() {
        let operation = UUID()
        XCTAssertEqual(LivePreviewSuccessionPolicy.decide(
            incomingOperationID: operation, previousOperationID: operation, previous: .playing
        ), .queue)
        XCTAssertEqual(LivePreviewSuccessionPolicy.decide(
            incomingOperationID: operation, previousOperationID: operation, previous: .unplayedTail
        ), .releaseTailThenQueue, "a segment's sub-prebuffer tail plays before the next segment")
    }

    func testPauseHoldsTheWholeNarration() {
        let operation = UUID()
        XCTAssertEqual(LivePreviewSuccessionPolicy.decide(
            incomingOperationID: operation, previousOperationID: operation, previous: .held
        ), .queue, "S5: the next take waits behind a held take; Play resumes it, then the queue")
    }

    func testSilentPreviousTakeGivesWayAtOnce() {
        let operation = UUID()
        XCTAssertEqual(LivePreviewSuccessionPolicy.decide(
            incomingOperationID: operation, previousOperationID: operation, previous: .silent
        ), .startNow)
    }

    func testAnotherOperationOrALoneTakeReplacesWhatPlays() {
        XCTAssertEqual(LivePreviewSuccessionPolicy.decide(
            incomingOperationID: UUID(), previousOperationID: UUID(), previous: .playing
        ), .startNow)
        XCTAssertEqual(LivePreviewSuccessionPolicy.decide(
            incomingOperationID: nil, previousOperationID: nil, previous: .held
        ), .startNow)
        XCTAssertEqual(LivePreviewSuccessionPolicy.decide(
            incomingOperationID: UUID(), previousOperationID: nil, previous: .playing
        ), .startNow)
    }
}

/// S2: a promoted take whose stream has ended plays what it has.
final class LivePreviewPromotionPolicyTests: XCTestCase {
    func testShortSegmentWithASuccessorPlaysWithoutItsPrebuffer() {
        XCTAssertEqual(LivePreviewPromotionPolicy.decide(
            streamEnded: true, queuedBuffers: 4, isPlaying: false, allowsAutomaticPlayback: true
        ), .play)
    }

    func testEndedTakeWithNothingQueuedGivesWayToTheNext() {
        XCTAssertEqual(LivePreviewPromotionPolicy.decide(
            streamEnded: true, queuedBuffers: 0, isPlaying: false, allowsAutomaticPlayback: true
        ), .skipToNext)
    }

    func testStreamingPlayingOrHeldTakeWaits() {
        XCTAssertEqual(LivePreviewPromotionPolicy.decide(
            streamEnded: false, queuedBuffers: 4, isPlaying: false, allowsAutomaticPlayback: true
        ), .wait, "a take still streaming fills its prebuffer as usual")
        XCTAssertEqual(LivePreviewPromotionPolicy.decide(
            streamEnded: true, queuedBuffers: 4, isPlaying: true, allowsAutomaticPlayback: true
        ), .wait)
        XCTAssertEqual(LivePreviewPromotionPolicy.decide(
            streamEnded: true, queuedBuffers: 4, isPlaying: false, allowsAutomaticPlayback: false
        ), .wait)
    }
}

/// S6, N1, N2: the waiting takes' order and bookkeeping.
final class LivePreviewTakeQueueTests: XCTestCase {
    private typealias Queue = LivePreviewTakeQueue<Int, String, String>

    private func admit(
        _ queue: inout Queue,
        sessionID: String?,
        operationID: UUID? = nil,
        pending: inout LivePreviewEstimate?,
        currentBacklog: TimeInterval = 0
    ) {
        queue.admit(
            sessionID: sessionID,
            operationID: operationID,
            details: sessionID ?? "unnamed",
            sessionDirectory: nil,
            pendingEstimate: &pending,
            fallbackEstimate: LivePreviewEstimate(text: "fallback"),
            currentBacklogSeconds: currentBacklog
        )
    }

    @discardableResult
    private func route(
        _ queue: inout Queue,
        _ chunk: Int,
        to sessionID: String,
        isCurrent: Bool = false,
        cumulative: TimeInterval? = nil,
        seconds: TimeInterval = 1,
        currentBacklog: TimeInterval = 0
    ) -> Queue.Routing {
        queue.route(
            chunk,
            sessionID: sessionID,
            isCurrentSession: isCurrent,
            sessionDirectory: nil,
            chunkSeconds: seconds,
            cumulativeDuration: cumulative,
            currentBacklogSeconds: currentBacklog
        )
    }

    func testAdmissionConsumesThePendingEstimate() {
        var queue = Queue()
        let submitted = LivePreviewEstimate(text: String(repeating: "word ", count: 20))
        var pending = submitted
        admit(&queue, sessionID: "line-2", pending: &pending)
        XCTAssertNil(pending, "the next submission sets the estimate of the take after it")
        XCTAssertEqual(queue.takes.first?.estimate, submitted)
        admit(&queue, sessionID: "line-3", pending: &pending)
        XCTAssertEqual(queue.takes.last?.estimate, LivePreviewEstimate(text: "fallback"))
    }

    func testChunksFollowTheirStreamAndAnUnnamedTakeAdoptsANewStream() {
        var queue = Queue()
        var pending: LivePreviewEstimate?
        admit(&queue, sessionID: "segment-2", pending: &pending)
        admit(&queue, sessionID: nil, pending: &pending)
        XCTAssertEqual(route(&queue, 1, to: "segment-2"), .stored(firstAudio: true))
        XCTAssertEqual(route(&queue, 2, to: "segment-2"), .stored(firstAudio: false))
        XCTAssertEqual(route(&queue, 9, to: "current", isCurrent: true), .notQueued,
                       "the playing take's own chunk is not adopted")
        XCTAssertEqual(route(&queue, 3, to: "segment-3"), .stored(firstAudio: true))
        XCTAssertEqual(queue.takes.map(\.sessionID), ["segment-2", "segment-3"])
        XCTAssertEqual(queue.takes.map(\.chunks), [[1, 2], [3]])
        XCTAssertEqual(route(&queue, 4, to: "segment-4"), .notQueued, "no waiting take is unnamed any more")
    }

    func testResultsBelongToTheNewestTakeInOrder() {
        var queue = Queue()
        XCTAssertFalse(queue.attach("orphan", details: "none"), "with no waiting take the player applies it")
        var pending: LivePreviewEstimate?
        let operation = UUID()
        admit(&queue, sessionID: "line-2", operationID: operation, pending: &pending)
        XCTAssertTrue(queue.attach("result-2", details: "line-2"))
        XCTAssertTrue(queue.attach("result-3", details: "line-3"))
        XCTAssertEqual(queue.takes.map(\.completion), ["result-2", "result-3"])
        let streamedNothing = queue.takes.last
        XCTAssertNil(streamedNothing?.sessionID)
        XCTAssertEqual(streamedNothing?.operationID, operation)
        XCTAssertEqual(streamedNothing?.acceptsUnnamedChunks, false, "a completed take adopts no stream")
        XCTAssertEqual(route(&queue, 1, to: "line-4"), .notQueued)
    }

    func testBacklogCountsCumulativeAudio() {
        var queue = Queue()
        var pending: LivePreviewEstimate?
        admit(&queue, sessionID: "a", pending: &pending)
        route(&queue, 1, to: "a", cumulative: 0.32)
        route(&queue, 2, to: "a", cumulative: 0.64)
        admit(&queue, sessionID: "b", pending: &pending)
        route(&queue, 3, to: "b", cumulative: nil, seconds: 0.5)
        XCTAssertEqual(queue.backlogSeconds, 1.14, accuracy: 1e-9)
    }

    func testPastTheBoundTheNewcomerKeepsItsResultButNotItsPreview() {
        let bound = Queue.maximumBacklogSeconds
        var queue = Queue()
        var pending: LivePreviewEstimate?
        admit(&queue, sessionID: "a", pending: &pending, currentBacklog: 10)
        XCTAssertEqual(route(&queue, 1, to: "a", seconds: bound - 20, currentBacklog: 10), .stored(firstAudio: true))
        XCTAssertEqual(route(&queue, 2, to: "a", seconds: 20, currentBacklog: 10), .dropped,
                       "N1: the bound holds on every chunk, not only at admission")
        XCTAssertTrue(queue.takes[0].isPreviewTruncated)
        XCTAssertEqual(route(&queue, 3, to: "a", seconds: 0.1, currentBacklog: 0), .dropped,
                       "a truncated preview stays truncated")

        admit(&queue, sessionID: "b", pending: &pending, currentBacklog: 30)
        XCTAssertTrue(queue.takes[1].isPreviewTruncated, "N2: the newcomer gives up its preview")
        XCTAssertEqual(route(&queue, 4, to: "b"), .dropped)
        XCTAssertTrue(queue.attach("result-b", details: "b"), "its result still waits for its turn")
        XCTAssertEqual(queue.takes[1].completion, "result-b")
        XCTAssertEqual(queue.takes.map(\.chunks), [[1], []])
    }

    func testOrderAndRemovalOfAnotherOperationsTakes() {
        var queue = Queue()
        var pending: LivePreviewEstimate?
        let old = UUID(), current = UUID()
        admit(&queue, sessionID: "old", operationID: old, pending: &pending)
        admit(&queue, sessionID: "kept", operationID: current, pending: &pending)
        let removed = queue.removeAll { $0.operationID == old }
        XCTAssertEqual(removed.map(\.sessionID), ["old"])
        XCTAssertEqual(queue.popFirst()?.sessionID, "kept")
        XCTAssertNil(queue.popFirst())
        XCTAssertTrue(queue.isEmpty)
    }
}

/// U08: a completed card mirrors the shared player only while it holds the card's file.
final class SharedPlayerAdoptionTests: XCTestCase {
    func testCardForAnotherTakeIsIdleAtItsStart() {
        let adoption = SharedPlayerAdoption.resolve(
            cardFilePath: "/outputs/take-a.wav", sharedFilePath: "/outputs/take-b.wav",
            sharedIsPlaying: true, sharedCurrentTime: 7.5, sharedDuration: 12
        )
        XCTAssertFalse(adoption.mirrorsSharedPlayer)
        XCTAssertFalse(adoption.isPlaying)
        XCTAssertEqual(adoption.currentTime, 0)
        XCTAssertNil(adoption.duration, "the length comes from the card's own file")

        let cleared = SharedPlayerAdoption.resolve(
            cardFilePath: "/outputs/take-a.wav", sharedFilePath: nil,
            sharedIsPlaying: false, sharedCurrentTime: 3, sharedDuration: 9
        )
        XCTAssertFalse(cleared.mirrorsSharedPlayer)
        XCTAssertEqual(cleared.currentTime, 0)
    }

    func testCardForTheSharedTakeMirrorsIt() {
        let adoption = SharedPlayerAdoption.resolve(
            cardFilePath: "/outputs/take-a.wav", sharedFilePath: "/outputs/take-a.wav",
            sharedIsPlaying: true, sharedCurrentTime: 2.25, sharedDuration: 6
        )
        XCTAssertEqual(adoption, SharedPlayerAdoption(
            mirrorsSharedPlayer: true, isPlaying: true, currentTime: 2.25, duration: 6
        ))
        XCTAssertNil(SharedPlayerAdoption.resolve(
            cardFilePath: "/outputs/take-a.wav", sharedFilePath: "/outputs/take-a.wav",
            sharedIsPlaying: false, sharedCurrentTime: 0, sharedDuration: 0
        ).duration)
    }
}

/// P08-07: Chinese, Japanese and Korean are timed per character; other text is unchanged.
final class LivePreviewEstimateTests: XCTestCase {
    private func estimate(_ text: String) throws -> TimeInterval {
        try XCTUnwrap(LivePreviewEstimate(text: text)).estimatedAudioDuration
    }

    func testAlphabeticEstimateIsUnchanged() throws {
        // 6 words at 2.45/s beat 26 characters at 16/s, plus two pauses.
        XCTAssertEqual(try estimate("Hello there, how are you today?"), 6 / 2.45 + 2 * 0.08, accuracy: 1e-9)
        XCTAssertEqual(try estimate("Hi"), 0.8, accuracy: 1e-9)
        XCTAssertNil(LivePreviewEstimate(text: "   "))
    }

    func testChineseIsTimedPerCharacter() throws {
        XCTAssertEqual(try estimate(String(repeating: "天", count: 50)), 13, accuracy: 1e-9)
        // 12 Han characters and two full-width stops (pauses, and 16/s characters).
        XCTAssertEqual(try estimate("今天天气很好。我们去公园吧。"), 12 * 0.26 + 2.0 / 16 + 2 * 0.08, accuracy: 1e-9)
        let prebuffer = try XCTUnwrap(LivePreviewEstimate(text: String(repeating: "天", count: 50)))
            .requiredBufferDuration(minimumBufferedDuration: 3.25)
        XCTAssertEqual(prebuffer, 13 * 0.35, accuracy: 1e-9, "a 50-character script buffers 35 % of ~13 s")
    }

    func testJapaneseAndKoreanAreTimedPerCharacter() throws {
        // Five kana and two Han read as Japanese, one ideographic comma.
        XCTAssertEqual(try estimate("こんにちは、世界"), 7 * 0.22 + 1.0 / 16 + 0.08, accuracy: 1e-9)
        XCTAssertEqual(try estimate("안녕하세요 반갑습니다"), 10 * 0.22, accuracy: 1e-9)
    }

    func testMixedScriptAddsBothParts() throws {
        XCTAssertEqual(try estimate("第3章"), 2 * 0.26 + 1 / 2.45, accuracy: 1e-9)
    }
}
