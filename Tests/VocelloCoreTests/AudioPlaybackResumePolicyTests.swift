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
