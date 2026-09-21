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
