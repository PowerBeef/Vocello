import XCTest
@testable import QwenVoiceCore

@MainActor
final class AllocationRetryAnnotationTests: XCTestCase {
    func testRetryAnnotationPreservesResultAndRecordsAttempt() throws {
        let audioQC = AudioQCReport(
            verdict: .warn,
            flags: ["cadence:excess1(2/1)"],
            rmsDBFS: -18,
            peak: 0.4,
            clippedSamples: 0,
            hotSamples: 0,
            nonFiniteSamples: 0,
            clickEvents: 0,
            longestSilenceMS: 600,
            durationSeconds: 4
        )
        let original = GenerationResult(
            audioPath: "fixture.wav",
            durationSeconds: 1.25,
            streamSessionDirectory: nil,
            usedStreaming: true,
            diagnosticTimingsMS: ["existing": 4],
            diagnosticBooleanFlags: ["existing": true],
            diagnosticStringFlags: ["identity": "fixture"],
            audioQC: audioQC
        )

        let annotated = MLXTTSEngine.annotatingAllocationRetry(
            original,
            streamingUsed: true,
            attempted: true,
            succeeded: true,
            cleanupMS: 17
        )

        XCTAssertEqual(annotated.audioPath, original.audioPath)
        XCTAssertEqual(annotated.diagnosticTimingsMS["existing"], 4)
        XCTAssertEqual(annotated.diagnosticTimingsMS["allocationRetryCleanupMS"], 17)
        XCTAssertEqual(annotated.diagnosticBooleanFlags["existing"], true)
        XCTAssertEqual(annotated.diagnosticBooleanFlags["allocationRetryAttempted"], true)
        XCTAssertEqual(annotated.diagnosticBooleanFlags["allocationRetrySucceeded"], true)
        XCTAssertEqual(annotated.diagnosticBooleanFlags["allocationRetryStreamingUsed"], true)
        XCTAssertEqual(annotated.diagnosticStringFlags["identity"], "fixture")
        XCTAssertEqual(annotated.audioQC, audioQC)
        let decoded = try JSONDecoder().decode(
            GenerationResult.self,
            from: JSONEncoder().encode(annotated)
        )
        XCTAssertEqual(decoded.audioQC, audioQC)
    }

    func testNoRetryIsExplicitRatherThanSilentlyUnannotated() {
        let annotated = MLXTTSEngine.annotatingAllocationRetry(
            GenerationResult(
                audioPath: "fixture.wav",
                durationSeconds: 1,
                streamSessionDirectory: nil,
                usedStreaming: false
            ),
            streamingUsed: false,
            attempted: false,
            succeeded: false,
            cleanupMS: nil
        )

        XCTAssertEqual(annotated.diagnosticBooleanFlags["allocationRetryAttempted"], false)
        XCTAssertEqual(annotated.diagnosticBooleanFlags["allocationRetrySucceeded"], false)
        XCTAssertNil(annotated.diagnosticTimingsMS["allocationRetryCleanupMS"])
    }
}
