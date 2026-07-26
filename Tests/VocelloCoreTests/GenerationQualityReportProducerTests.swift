import Foundation
@testable import QwenVoiceCore
import XCTest

/// Phase 12: the fast-depth producer must satisfy the registry's required
/// gates from real finalization evidence, fold the persisted-WAV Fast QC
/// verdict into the typed gate, and fail closed when mandatory evidence is
/// missing.
final class GenerationQualityReportProducerTests: XCTestCase {
    private func makeQC(
        verdict: AudioQCReport.Verdict,
        flags: [String] = [],
        longestSilenceMS: Int = 120
    ) -> AudioQCReport {
        AudioQCReport(
            verdict: verdict,
            flags: flags,
            rmsDBFS: -21.5,
            dcOffset: 0.0004,
            peak: 0.82,
            clippedSamples: 0,
            hotSamples: 2,
            nonFiniteSamples: 0,
            clickEvents: 1,
            longestSilenceMS: longestSilenceMS,
            durationSeconds: 6.4
        )
    }

    private func makeReport(
        qc: AudioQCReport?,
        hitTokenCap: Bool = false,
        usedStreaming: Bool = true,
        chunkCount: Int = 9
    ) -> GenerationQualityReport {
        GenerationQualityReportProducer.fastReport(
            generationID: UUID(),
            finishReason: .eos,
            hitTokenCap: hitTokenCap,
            audioQC: qc,
            wavDigest: String(repeating: "a", count: 64),
            usedStreaming: usedStreaming,
            chunkCount: chunkCount,
            audioChannel: nil
        )
    }

    private func makeDeepReport(
        policy: QualityReviewPolicy,
        deepEvidence: [GenerationQualityGateID: GenerationQualityReportProducer.DeepGateEvidence]
    ) -> GenerationQualityReport {
        GenerationQualityReportProducer.deepReport(
            generationID: UUID(),
            policy: policy,
            finishReason: .eos,
            hitTokenCap: false,
            audioQC: makeQC(verdict: .pass),
            wavDigest: String(repeating: "a", count: 64),
            usedStreaming: true,
            chunkCount: 9,
            audioChannel: nil,
            deepEvidence: deepEvidence
        )
    }

    func testCanonicalLongFormReportComposesDeepGatesAndPasses() throws {
        let policy = GenerationQualityReportProducer.canonicalPolicy(
            requiresLanguageASR: false,
            isLongForm: true
        )
        let report = makeDeepReport(policy: policy, deepEvidence: [
            .prosody: .init(
                outcome: .pass,
                algorithmVersion: 2,
                measurements: [
                    .init(key: .medianPitchSemitones, value: 3.1),
                    .init(key: .pitchRangeSemitones, value: 7.4),
                ]
            ),
            .delivery: .init(outcome: .pass, algorithmVersion: 2),
            .longFormContinuity: .init(
                outcome: .pass,
                algorithmVersion: 1,
                measurements: [.init(key: .boundaryDiscontinuity, value: 0.021)]
            ),
        ])
        let verdict = try QualityGateRegistry.evaluate(report)
        XCTAssertEqual(verdict.outcome, .pass)
        XCTAssertTrue(verdict.requiredGates.contains(.longFormContinuity))
        let continuity = report.results.first { $0.gate == .longFormContinuity }
        XCTAssertEqual(
            continuity?.measurements.first?.key,
            .boundaryDiscontinuity
        )
    }

    func testMissingDeepAnalyzerEvidenceFailsClosed() throws {
        let policy = GenerationQualityReportProducer.standardPolicy(requiresLanguageASR: false)
        let report = makeDeepReport(policy: policy, deepEvidence: [:])
        let verdict = try QualityGateRegistry.evaluate(report)
        XCTAssertEqual(verdict.outcome, .fail)
        XCTAssertTrue(verdict.issues.contains("quality_gate_unavailable.prosody"))
    }

    func testLanguageASRGateEnforcesThreePassConsensus() throws {
        let policy = GenerationQualityReportProducer.standardPolicy(requiresLanguageASR: true)
        func report(passCount: Double) -> GenerationQualityReport {
            makeDeepReport(policy: policy, deepEvidence: [
                .prosody: .init(outcome: .pass, algorithmVersion: 2),
                .languageASR: .init(
                    outcome: .pass,
                    algorithmVersion: 1,
                    measurements: [
                        .init(key: .consensusPassCount, value: passCount),
                        .init(key: .wordErrorRate, value: 0.0),
                    ]
                ),
            ])
        }
        XCTAssertEqual(try QualityGateRegistry.evaluate(report(passCount: 3)).outcome, .pass)
        XCTAssertThrowsError(try QualityGateRegistry.evaluate(report(passCount: 2))) { error in
            XCTAssertEqual(
                error as? QualityGateRegistryIssue,
                .insufficientASRConsensus
            )
        }
    }

    func testCleanTakeSatisfiesTheRegistryWithAllFastGates() throws {
        let report = makeReport(qc: makeQC(verdict: .pass))
        let verdict = try QualityGateRegistry.evaluate(report)

        XCTAssertEqual(verdict.outcome, .pass)
        XCTAssertEqual(
            verdict.requiredGates,
            QualityGateRegistry.requiredGates(for: report.policy)
        )
        XCTAssertTrue(verdict.issues.isEmpty)

        let persisted = try XCTUnwrap(
            report.results.first { $0.gate == .persistedWAV }
        )
        XCTAssertEqual(persisted.algorithmVersion, AudioQCReport.currentAlgorithmVersion)
        XCTAssertEqual(persisted.evidenceDigest, String(repeating: "a", count: 64))
        let keys = Set(persisted.measurements.map(\.key))
        for expected: GenerationQualityMeasurementKey in [
            .durationSeconds, .peak, .clippingCount, .clickCount,
            .dropoutMilliseconds, .rmsDBFS, .dcOffset,
        ] {
            XCTAssertTrue(keys.contains(expected), "missing \(expected)")
        }
    }

    func testQCWarningAndTokenCapSurfaceAsRegistryWarnings() throws {
        let warned = makeReport(qc: makeQC(verdict: .warn), hitTokenCap: true)
        let verdict = try QualityGateRegistry.evaluate(warned)

        XCTAssertEqual(verdict.outcome, .warning)
        XCTAssertTrue(verdict.issues.contains("quality_gate_warning.persisted_wav"))
        XCTAssertTrue(verdict.issues.contains("quality_gate_warning.token_cap"))
    }

    func testQCFailureFailsTheRegistry() throws {
        let failed = makeReport(qc: makeQC(verdict: .fail, flags: ["dropout:1337ms"]))
        let verdict = try QualityGateRegistry.evaluate(failed)
        XCTAssertEqual(verdict.outcome, .fail)
        XCTAssertTrue(verdict.issues.contains("quality_gate_failed.persisted_wav"))
    }

    func testMissingFastQCFailsClosed() throws {
        let missing = makeReport(qc: nil)
        let verdict = try QualityGateRegistry.evaluate(missing)
        XCTAssertEqual(verdict.outcome, .fail)
        XCTAssertTrue(verdict.issues.contains("quality_gate_unavailable.persisted_wav"))
    }

    func testStreamingWithoutChunksFailsCodecBehavior() throws {
        let silent = makeReport(qc: makeQC(verdict: .pass), chunkCount: 0)
        let verdict = try QualityGateRegistry.evaluate(silent)
        XCTAssertEqual(verdict.outcome, .fail)
        XCTAssertTrue(verdict.issues.contains("quality_gate_failed.codec_behavior"))

        let oneShot = makeReport(qc: makeQC(verdict: .pass), usedStreaming: false, chunkCount: 0)
        XCTAssertEqual(try QualityGateRegistry.evaluate(oneShot).outcome, .pass)
    }

    func testTelemetryNotesCarryVerdictAndSchedule() {
        let notes = GenerationQualityReportProducer.telemetryNotes(
            for: makeReport(qc: makeQC(verdict: .pass))
        )
        XCTAssertEqual(notes["quality_registry_outcome"], "pass")
        XCTAssertEqual(notes["quality_schedule_stages"], "synthesis,fast_analysis")
        XCTAssertEqual(
            notes["quality_registry_required_gates"],
            "codec_behavior,persisted_wav,streaming_continuity,terminal,token_cap"
        )
        XCTAssertNil(notes["quality_registry_issues"])
    }
}
