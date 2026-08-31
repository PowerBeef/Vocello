import XCTest
@testable import QwenVoiceCore

final class GenerationTerminalDiagnosticEvidenceTests: XCTestCase {
    private let digestA = String(repeating: "a", count: 64)
    private let digestB = String(repeating: "b", count: 64)

    func testFailedAudioQCIsOnePostGenerationRootWithBoundArtifacts() {
        let evidence = GenerationTerminalDiagnosticEvidence(
            requestReceipt: nil,
            audioQC: failingAudioQC(),
            notes: [
                "nativeRuntimeFailureCode": "audio_quality_rejected",
                "codecTraceSHA256": digestA,
                "codecTraceByteCount": "2048",
                "codecTraceFrameCount": "12",
                "codecTraceCodeGroupsMinimum": "0",
                "codecTraceCodeGroupsMaximum": "31",
                "codecTraceComplete": "true",
                "codecTraceChunkRanges": "0:4,4:12",
                "rejectedAudioSHA256": digestB,
                "rejectedAudioByteCount": "96044",
                "rejectedAudioDurationSeconds": "2.0",
            ],
            stageNames: [
                GenerationStartupBoundary.firstDecodedAudioFrame.telemetryStage,
                GenerationStartupBoundary.firstPublishedStreamChunk.telemetryStage,
            ]
        )

        XCTAssertEqual(evidence.classification, .postGenerationQC)
        XCTAssertEqual(evidence.failureCode, "audio_quality_rejected")
        XCTAssertEqual(evidence.diagnosticArtifacts.map(\.kind), [.codecTrace, .rejectedAudio])
        XCTAssertEqual(
            evidence.diagnosticArtifacts.first?.codecChunkRanges,
            [
                StartupReliabilityCodecFrameRange(start: 0, endExclusive: 4),
                StartupReliabilityCodecFrameRange(start: 4, endExclusive: 12),
            ]
        )
    }

    func testMalformedArtifactNotesFailClosedWithoutLosingRootClassification() {
        let evidence = GenerationTerminalDiagnosticEvidence(
            requestReceipt: nil,
            audioQC: failingAudioQC(),
            notes: [
                "nativeRuntimeFailureCode": "contains private text!",
                "codecTraceSHA256": "not-a-digest",
                "codecTraceByteCount": "-1",
                "codecTraceFrameCount": "12",
                "codecTraceCodeGroupsMinimum": "0",
                "codecTraceCodeGroupsMaximum": "31",
                "codecTraceComplete": "yes",
                "codecTraceChunkRanges": "0:13",
            ],
            stageNames: []
        )

        XCTAssertEqual(evidence.classification, .postGenerationQC)
        XCTAssertNil(evidence.failureCode)
        XCTAssertTrue(evidence.diagnosticArtifacts.isEmpty)
    }

    func testDecodedAudioWithoutQCFailureIsPostGenerationFailure() {
        let evidence = GenerationTerminalDiagnosticEvidence(
            requestReceipt: nil,
            audioQC: nil,
            notes: ["nativeRuntimeFailureCode": "writer_failed"],
            stageNames: [GenerationStartupBoundary.firstDecodedAudioFrame.telemetryStage]
        )

        XCTAssertEqual(evidence.classification, .postGenerationFailure)
        XCTAssertEqual(evidence.failureCode, "writer_failed")
    }

    func testStartupAndUnknownBoundariesRemainDistinct() {
        let startup = GenerationTerminalDiagnosticEvidence(
            requestReceipt: nil,
            audioQC: nil,
            notes: [:],
            stageNames: [GenerationStartupBoundary.modelLoaded.telemetryStage]
        )
        let unknown = GenerationTerminalDiagnosticEvidence(
            requestReceipt: nil,
            audioQC: nil,
            notes: [:],
            stageNames: []
        )

        XCTAssertEqual(startup.classification, .preAudioStartup)
        XCTAssertEqual(unknown.classification, .unmaterializedUnknown)
    }

    func testSnapshotChoosesLatestTerminalRowWithinTheSameAttempt() {
        let earlier = GenerationTelemetryRecord(
            generationID: "generation",
            layer: .engine,
            recordedAt: "2026-08-31T12:00:00Z",
            notes: ["nativeRuntimeFailureCode": "early_failure"]
        )
        let later = GenerationTelemetryRecord(
            generationID: "generation",
            layer: .engine,
            recordedAt: "2026-08-31T12:00:01Z",
            notes: ["nativeRuntimeFailureCode": "audio_quality_rejected"],
            audioQC: failingAudioQC()
        )

        let snapshot = GenerationTerminalDiagnosticEvidence.snapshot(from: [earlier, later])

        XCTAssertEqual(snapshot?.classification, .postGenerationQC)
        XCTAssertEqual(snapshot?.failureCode, "audio_quality_rejected")
    }

    private func failingAudioQC() -> AudioQCReport {
        AudioQCReport(
            instabilityVerdict: .pass,
            writtenOutputVerdict: .fail,
            verdict: .fail,
            flags: ["dropout:2725ms"],
            rmsDBFS: -24,
            peak: 0.62,
            clippedSamples: 0,
            hotSamples: 0,
            nonFiniteSamples: 0,
            clickEvents: 0,
            longestSilenceMS: 2_725,
            durationSeconds: 9.4,
            longestSilenceStartMS: 3_100
        )
    }
}
