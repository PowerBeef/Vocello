import XCTest
@testable import QwenVoiceCore
import VocelloQwen3Core

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

    func testFinalizedFailureTimingsRetainModelTerminalDiagnostics() {
        let diagnostics = VocelloQwen3GenerationDiagnostics(
            timingsMilliseconds: [
                "custom_target_token_count": 11,
                "custom_effective_max_tokens": 73,
                "qwen_token_loop_total": 9_100,
            ]
        )

        let merged = StreamingExecutionContext.finalizedGenerationTimings(
            base: ["qwen_token_loop_total": 1, "load_model": 800],
            modelDiagnostics: diagnostics,
            signpost: ["native_generation_stream_ms": 9_250],
            includeModelDiagnostics: true
        )

        XCTAssertEqual(merged["custom_target_token_count"], 11)
        XCTAssertEqual(merged["custom_effective_max_tokens"], 73)
        XCTAssertEqual(merged["qwen_token_loop_total"], 9_100)
        XCTAssertEqual(merged["load_model"], 800)
        XCTAssertEqual(merged["native_generation_stream_ms"], 9_250)
    }

    func testModelTerminalNotesAreExplicitlyAllowlisted() {
        let notes = StreamingExecutionContext.modelTerminalDiagnosticNotes(
            booleanFlags: [
                "generation_ended_by_eos": true,
                "custom_generation_hit_token_cap": false,
                "future_unreviewed_flag": true,
            ],
            stringFlags: [
                "generation_end_reason": "eos",
                "custom_generation_end_reason": "eos",
                "design_generation_end_reason": "unexpected-value",
                "future_private_string": "/Users/example/reference.wav",
            ]
        )

        XCTAssertEqual(notes["generation_ended_by_eos"], "true")
        XCTAssertEqual(notes["custom_generation_hit_token_cap"], "false")
        XCTAssertEqual(notes["generation_end_reason"], "eos")
        XCTAssertEqual(notes["custom_generation_end_reason"], "eos")
        XCTAssertNil(notes["design_generation_end_reason"])
        XCTAssertNil(notes["future_unreviewed_flag"])
        XCTAssertFalse(notes.values.contains { $0.contains("/Users/") })
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
