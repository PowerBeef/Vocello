@testable import QwenVoiceCore
import XCTest

final class GenerationQualityReportTests: XCTestCase {
    func testFastReviewRequiresPersistedOutputAndContinuity() throws {
        let policy = QualityReviewPolicy(
            depth: .fast,
            requiresLanguageASR: false
        )
        let report = GenerationQualityReport(
            generationID: UUID(),
            policy: policy,
            results: passingResults(for: policy)
        )

        let verdict = try QualityGateRegistry.evaluate(report)

        XCTAssertEqual(verdict.outcome, .pass)
        XCTAssertEqual(
            Set(verdict.requiredGates),
            [.terminal, .tokenCap, .codecBehavior, .persistedWAV, .streamingContinuity]
        )
    }

    func testOnePassASRCannotProducePromotionPass() throws {
        let policy = QualityReviewPolicy(
            depth: .standard,
            requiresLanguageASR: true
        )
        var results = passingResults(for: policy)
        let index = try XCTUnwrap(results.firstIndex(where: { $0.gate == .languageASR }))
        results[index] = GenerationQualityGateResult(
            gate: .languageASR,
            outcome: .pass,
            algorithmVersion: 1,
            measurements: [
                GenerationQualityMeasurement(key: .consensusPassCount, value: 1),
            ]
        )

        XCTAssertThrowsError(try QualityGateRegistry.evaluate(
            GenerationQualityReport(
                generationID: UUID(),
                policy: policy,
                results: results
            )
        )) { error in
            XCTAssertEqual(
                error as? QualityGateRegistryIssue,
                .insufficientASRConsensus
            )
        }
    }

    func testEvidenceDigestAndMeasurementKeysAreFailClosed() throws {
        let policy = QualityReviewPolicy(
            depth: .fast,
            requiresLanguageASR: false
        )
        var invalidDigest = passingResults(for: policy)
        invalidDigest[0] = GenerationQualityGateResult(
            gate: invalidDigest[0].gate,
            outcome: .pass,
            algorithmVersion: 1,
            evidenceDigest: "NOT-A-DIGEST"
        )
        XCTAssertThrowsError(try QualityGateRegistry.evaluate(
            GenerationQualityReport(
                generationID: UUID(),
                policy: policy,
                results: invalidDigest
            )
        )) { error in
            XCTAssertEqual(
                error as? QualityGateRegistryIssue,
                .invalidEvidenceDigest(invalidDigest[0].gate)
            )
        }

        var duplicateMeasurement = passingResults(for: policy)
        duplicateMeasurement[0] = GenerationQualityGateResult(
            gate: duplicateMeasurement[0].gate,
            outcome: .pass,
            algorithmVersion: 1,
            evidenceDigest: String(repeating: "a", count: 64),
            measurements: [
                GenerationQualityMeasurement(key: .durationSeconds, value: 1),
                GenerationQualityMeasurement(key: .durationSeconds, value: 2),
            ]
        )
        XCTAssertThrowsError(try QualityGateRegistry.evaluate(
            GenerationQualityReport(
                generationID: UUID(),
                policy: policy,
                results: duplicateMeasurement
            )
        )) { error in
            XCTAssertEqual(
                error as? QualityGateRegistryIssue,
                .duplicateMeasurement(
                    duplicateMeasurement[0].gate,
                    .durationSeconds
                )
            )
        }
    }

    func testConstrainedScheduleReleasesTTSBeforeHeavyReview() {
        let schedule = QualityResourceSchedule(
            policy: QualityReviewPolicy(
                depth: .canonical,
                requiresLanguageASR: true
            ),
            constrainedMemory: true
        )

        XCTAssertEqual(schedule.stages, [
            .synthesis,
            .fastAnalysis,
            .releaseTTSResources,
            .speechRecognition,
            .advancedAnalysis,
        ])
        XCTAssertFalse(schedule.permitsConcurrentHeavyReviewerAndSynthesis)
    }

    func testAudioQualityGateReportFromAudioQCPreservesVerdictFlagsAndMetrics() throws {
        let passed = AudioQualityGate.report(
            from: AudioQCReport(
                verdict: .pass,
                flags: [],
                rmsDBFS: -19.2,
                dcOffset: 0.001,
                peak: 0.65,
                clippedSamples: 0,
                hotSamples: 0,
                nonFiniteSamples: 0,
                clickEvents: 0,
                longestSilenceMS: 120,
                durationSeconds: 3.25
            )
        )
        XCTAssertTrue(passed.passed)
        XCTAssertTrue(passed.requiredFailures.isEmpty)
        XCTAssertTrue(passed.warnings.isEmpty)
        XCTAssertEqual(passed.metrics["algorithm_version"], Double(AudioQCReport.currentAlgorithmVersion))
        XCTAssertEqual(passed.metrics["duration_seconds"], 3.25)
        XCTAssertEqual(passed.metrics["rms_dbfs"], -19.2)
        XCTAssertEqual(passed.metrics["dc_offset"], 0.001)
        let passedCheck = try XCTUnwrap(passed.checks.first)
        XCTAssertEqual(passedCheck.name, "persisted_wav_qc_v\(AudioQCReport.currentAlgorithmVersion)")
        XCTAssertTrue(passedCheck.passed)
        XCTAssertNil(passedCheck.message)

        let warned = AudioQualityGate.report(
            from: AudioQCReport(
                verdict: .warn,
                flags: ["speaking_rate_slow", "onset_step_burst"],
                rmsDBFS: nil,
                dcOffset: nil,
                peak: 0.8,
                clippedSamples: 0,
                hotSamples: 4,
                nonFiniteSamples: 0,
                clickEvents: 1,
                longestSilenceMS: 350,
                durationSeconds: 9.5,
                speakingRateTextUnits: 42,
                secondsPerTextUnit: 0.226
            )
        )
        XCTAssertTrue(warned.passed)
        XCTAssertTrue(warned.requiredFailures.isEmpty)
        XCTAssertEqual(warned.warnings, ["speaking_rate_slow, onset_step_burst"])
        XCTAssertEqual(warned.metrics["rms_dbfs"], -160)
        XCTAssertEqual(warned.metrics["dc_offset"], 0)
        let warnedCheck = try XCTUnwrap(warned.checks.first)
        XCTAssertFalse(warnedCheck.passed)
        XCTAssertEqual(warnedCheck.severity, .warning)

        let failed = AudioQualityGate.report(
            from: AudioQCReport(
                verdict: .fail,
                flags: ["speaking_rate_fast"],
                rmsDBFS: -16.0,
                dcOffset: 0,
                peak: 0.5,
                clippedSamples: 0,
                hotSamples: 0,
                nonFiniteSamples: 0,
                clickEvents: 0,
                longestSilenceMS: 0,
                durationSeconds: 0.4
            )
        )
        XCTAssertFalse(failed.passed)
        XCTAssertEqual(failed.requiredFailures, ["persisted_wav_qc_v\(AudioQCReport.currentAlgorithmVersion)"])
        XCTAssertTrue(failed.warnings.isEmpty)
        let failedCheck = try XCTUnwrap(failed.checks.first)
        XCTAssertFalse(failedCheck.passed)
        XCTAssertEqual(failedCheck.severity, .error)
        XCTAssertEqual(failedCheck.message, "speaking_rate_fast")
    }

    private func passingResults(
        for policy: QualityReviewPolicy
    ) -> [GenerationQualityGateResult] {
        QualityGateRegistry.requiredGates(for: policy).map { gate in
            GenerationQualityGateResult(
                gate: gate,
                outcome: .pass,
                algorithmVersion: 1,
                evidenceDigest: String(repeating: "a", count: 64),
                measurements: gate == .languageASR
                    ? [GenerationQualityMeasurement(key: .consensusPassCount, value: 3)]
                    : []
            )
        }
    }
}
