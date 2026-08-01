import Foundation
@testable import QwenVoiceCore
import XCTest

final class GenerationQualityCompositionTests: XCTestCase {
    private static func cleanAudioQC(durationSeconds: Double) -> AudioQCReport {
        AudioQCReport(
            instabilityVerdict: .pass,
            writtenOutputVerdict: .pass,
            verdict: .pass,
            flags: [],
            rmsDBFS: -19.5,
            dcOffset: 0.0004,
            peak: 0.71,
            clippedSamples: 0,
            hotSamples: 0,
            nonFiniteSamples: 0,
            clickEvents: 0,
            longestSilenceMS: 120,
            durationSeconds: durationSeconds
        )
    }

    private func gate(
        passed: Bool,
        flags: [String] = [],
        metrics: [String: Double] = [:]
    ) -> GenerationQualityComposition.ProsodySidecarGate {
        GenerationQualityComposition.ProsodySidecarGate(
            passed: passed,
            flags: flags,
            analyzerAlgorithmVersion: 4,
            metrics: metrics
        )
    }

    func testCleanGateMapsToPassWithTypedMeasurements() {
        let evidence = GenerationQualityComposition.prosodyEvidence(
            gate: gate(
                passed: true,
                metrics: [
                    "pitch_range_semitones": 7.5,
                    "boundary_discontinuity": 0.02,
                    "syllable_rate_hz": 4.1,
                ]
            ),
            evidenceDigest: String(repeating: "a", count: 64)
        )
        XCTAssertEqual(evidence.outcome, .pass)
        XCTAssertEqual(evidence.algorithmVersion, 4)
        XCTAssertEqual(
            evidence.measurements.map(\.key),
            [.boundaryDiscontinuity, .pitchRangeSemitones].sorted { $0.rawValue < $1.rawValue }
        )
    }

    func testQualityFlagsMapToWarning() {
        let evidence = GenerationQualityComposition.prosodyEvidence(
            gate: gate(passed: false, flags: ["monotone", "long_pause"])
        )
        XCTAssertEqual(evidence.outcome, .warning)
    }

    func testAnalysisFailureFlagsMapToUnavailable() {
        for flag in ["metrics_incomplete", "analysis_failed"] {
            let evidence = GenerationQualityComposition.prosodyEvidence(
                gate: gate(passed: false, flags: [flag])
            )
            XCTAssertEqual(evidence.outcome, .unavailable, flag)
        }
    }

    func testComposedStandardReportPassesRegistryWithProsodyEvidence() throws {
        let audioQC = Self.cleanAudioQC(durationSeconds: 4.2)
        let digest = String(repeating: "b", count: 64)
        let report = GenerationQualityReportProducer.deepReport(
            generationID: UUID(),
            policy: GenerationQualityReportProducer.standardPolicy(requiresLanguageASR: false),
            finishReason: .eos,
            hitTokenCap: false,
            audioQC: audioQC,
            wavDigest: digest,
            usedStreaming: true,
            chunkCount: 6,
            audioChannel: nil,
            deepEvidence: [
                .prosody: GenerationQualityComposition.prosodyEvidence(
                    gate: gate(passed: true, metrics: ["pitch_range_semitones": 6.1]),
                    evidenceDigest: digest
                ),
            ]
        )
        let verdict = try QualityGateRegistry.evaluate(report)
        XCTAssertEqual(verdict.outcome, GenerationQualityOutcome.pass)
        XCTAssertTrue(verdict.requiredGates.contains(GenerationQualityGateID.prosody))
        XCTAssertTrue(verdict.issues.isEmpty)
    }

    func testComposedStandardReportWarnsOnProsodyFlags() throws {
        let digest = String(repeating: "c", count: 64)
        let report = GenerationQualityReportProducer.deepReport(
            generationID: UUID(),
            policy: GenerationQualityReportProducer.standardPolicy(requiresLanguageASR: false),
            finishReason: .eos,
            hitTokenCap: false,
            audioQC: Self.cleanAudioQC(durationSeconds: 3.0),
            wavDigest: digest,
            usedStreaming: true,
            chunkCount: 4,
            audioChannel: nil,
            deepEvidence: [
                .prosody: GenerationQualityComposition.prosodyEvidence(
                    gate: gate(passed: false, flags: ["flat"]),
                    evidenceDigest: digest
                ),
            ]
        )
        let verdict = try QualityGateRegistry.evaluate(report)
        XCTAssertEqual(verdict.outcome, GenerationQualityOutcome.warning)
        XCTAssertEqual(verdict.issues, ["quality_gate_warning.prosody"])
    }

    func testMissingProsodyEvidenceFailsClosed() throws {
        let report = GenerationQualityReportProducer.deepReport(
            generationID: UUID(),
            policy: GenerationQualityReportProducer.standardPolicy(requiresLanguageASR: false),
            finishReason: .eos,
            hitTokenCap: false,
            audioQC: nil,
            wavDigest: nil,
            usedStreaming: true,
            chunkCount: 3,
            audioChannel: nil,
            deepEvidence: [:]
        )
        let verdict = try QualityGateRegistry.evaluate(report)
        XCTAssertEqual(verdict.outcome, GenerationQualityOutcome.fail)
        XCTAssertTrue(verdict.issues.contains("quality_gate_unavailable.prosody"))
    }

    func testSidecarGateDecodesFromScriptShape() throws {
        let json = """
        {
          "clip": "custom_model_medium_warm_d-calm.subtle_0.wav",
          "analyzerAlgorithmVersion": 4,
          "passed": false,
          "flags": ["monotone"],
          "reason": "monotone",
          "metrics": {"f0_std_hz": 8.2, "pitch_range_semitones": 2.4}
        }
        """
        let gate = try JSONDecoder().decode(
            GenerationQualityComposition.ProsodySidecarGate.self,
            from: Data(json.utf8)
        )
        XCTAssertFalse(gate.passed)
        XCTAssertEqual(gate.flags, ["monotone"])
        let evidence = GenerationQualityComposition.prosodyEvidence(gate: gate)
        XCTAssertEqual(evidence.outcome, .warning)
        XCTAssertEqual(evidence.measurements.map(\.key), [.pitchRangeSemitones])
    }

    func testRankOrderingGuardsFastConsistency() {
        XCTAssertLessThan(
            GenerationQualityComposition.rank(of: .pass),
            GenerationQualityComposition.rank(of: .warning)
        )
        XCTAssertLessThan(
            GenerationQualityComposition.rank(of: .warning),
            GenerationQualityComposition.rank(of: .fail)
        )
    }
}
