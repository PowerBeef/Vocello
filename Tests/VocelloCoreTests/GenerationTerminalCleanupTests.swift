import Foundation
@testable import QwenVoiceCore
import XCTest

/// Pins the generation exit path's artifact-cleanup table. The regression
/// this protects: CM-7 (2026-08-04) — a completed non-streaming take had its
/// final WAV deleted by the session-retention defer, so the CLI printed a
/// success line and an output path with no file behind it.
final class GenerationTerminalCleanupTests: XCTestCase {
    func testCompletedNonStreamingTakeKeepsItsFinalOutput() {
        let cleanup = GenerationOutputAdapter.terminalCleanup(
            didCompleteProduct: true,
            usedStreaming: false
        )
        XCTAssertFalse(cleanup.removeOutput, "CM-7: a completed take must never lose its final WAV")
        XCTAssertTrue(cleanup.removeSession, "non-streaming takes retain no chunk session")
    }

    func testCompletedStreamingTakeKeepsOutputAndSession() {
        let cleanup = GenerationOutputAdapter.terminalCleanup(
            didCompleteProduct: true,
            usedStreaming: true
        )
        XCTAssertFalse(cleanup.removeOutput)
        XCTAssertFalse(cleanup.removeSession, "the player replays chunks from the session directory")
    }

    func testUnfinishedTakeCannotDeleteCallerDestination() {
        for streaming in [false, true] {
            let cleanup = GenerationOutputAdapter.terminalCleanup(
                didCompleteProduct: false,
                usedStreaming: streaming
            )
            XCTAssertFalse(cleanup.removeOutput, "only the writer owns private staging (streaming=\(streaming))")
            XCTAssertTrue(cleanup.removeSession, "partial session must not leak (streaming=\(streaming))")
        }
    }
}
