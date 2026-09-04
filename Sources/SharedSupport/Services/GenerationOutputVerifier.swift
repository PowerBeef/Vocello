import AVFoundation
import Foundation
import QwenVoiceCore

/// Post-generation output verification for benchmark/device-diagnostics lanes. The same immutable
/// WAV is transcribed three times with one pinned, on-device Speech locale. Scores are emitted only
/// when every pass returns the same transcript, preventing retry-until-pass behavior.
enum GenerationOutputVerifier {
    enum AccuracyMetric: String, Codable, Sendable, Equatable {
        case wordErrorRate
        case characterErrorRate
    }

    struct Result: Codable, Sendable, Equatable {
        /// Typed `languageASR` gate result for the quality registry (Stage 3).
        /// `consensusPassCount` counts recognition passes only when the
        /// three-pass consensus is `consistent`; the registry enforces the
        /// three-pass rule on any passing gate. A skipped verification maps to
        /// `.unavailable` so a required gate can never silently disappear.
        /// The gate's integer algorithm version tracks this result's
        /// `schemaVersion` (v3 ↔ `language-output-verifier-v3`).
        func languageASRGateResult(evidenceDigest: String? = nil) -> GenerationQualityGateResult {
            let consensusPasses = recognition.consensusStatus == .consistent
                ? recognition.repetitions.count
                : 0
            var measurements: [GenerationQualityMeasurement] = [
                GenerationQualityMeasurement(
                    key: .consensusPassCount,
                    value: Double(consensusPasses)
                ),
            ]
            if let wordErrorRate, wordErrorRate.isFinite {
                measurements.append(GenerationQualityMeasurement(
                    key: .wordErrorRate,
                    value: wordErrorRate
                ))
            }
            // `skipReason` carries every non-passing reason. Only the reasons
            // that mean "recognition could not run at all" map to
            // `.unavailable`; a verification that ran and did not verify is a
            // plain `.fail`. Both fail a required gate — the split is
            // diagnostic.
            let couldNotRunReasons: Set<String> = [
                "speech_recognition_unavailable",
                "speech_recognition_unauthorized",
                "speech_authorization_timed_out",
            ]
            let outcome: GenerationQualityOutcome
            if pass {
                outcome = .pass
            } else if let skipReason, couldNotRunReasons.contains(skipReason) {
                outcome = .unavailable
            } else {
                outcome = .fail
            }
            return GenerationQualityGateResult(
                gate: .languageASR,
                outcome: outcome,
                algorithmVersion: schemaVersion,
                evidenceDigest: evidenceDigest,
                measurements: measurements
            )
        }

        static let currentSchemaVersion = 3
        static let currentAlgorithmVersion = "language-output-verifier-v3"
        static let currentAccuracyMetricVersion = "normalized-edit-rate-v1"

        var schemaVersion: Int
        var algorithmVersion: String
        var transcript: String
        var detectedLanguage: String
        var expectedLanguage: String
        var languageMatchScore: Double
        var wordErrorRate: Double?
        var characterErrorRate: Double?
        var accuracyMetricVersion: String
        var accuracyMetric: AccuracyMetric
        var accuracyThreshold: Double
        var accuracyValue: Double?
        var referenceTokenCount: Int?
        var hypothesisTokenCount: Int?
        var referenceCharacterCount: Int?
        var hypothesisCharacterCount: Int?
        var substitutions: Int?
        var insertions: Int?
        var deletions: Int?
        var characterSubstitutions: Int?
        var characterInsertions: Int?
        var characterDeletions: Int?
        /// Added compatibly in schema v3. Historical v3 records decode with `nil`; current live
        /// verification always binds the Speech timing evidence to the immutable WAV duration.
        var sourceAudioDurationSeconds: Double?
        var languagePass: Bool
        var accuracyPass: Bool?
        var pass: Bool
        var skipReason: String?
        var recognition: VoiceClipTranscriber.VerificationEvidence
    }

    static func verify(
        audioURL: URL,
        expectedScript: String,
        expectedLanguage: Qwen3SupportedLanguage,
        maxWordErrorRate: Double = VoiceClipTranscriber.outputVerificationDefaultMaxWordErrorRate
    ) async -> Result {
        let sourceAudioDurationSeconds: Double? = try? {
            let file = try AVAudioFile(forReading: audioURL)
            guard file.fileFormat.sampleRate > 0, file.length > 0 else { return nil }
            return Double(file.length) / file.fileFormat.sampleRate
        }()
        let recognition = await VoiceClipTranscriber.verificationEvidence(
            url: audioURL,
            expectedLanguage: expectedLanguage
        )

        return evaluate(
            recognition: recognition,
            expectedScript: expectedScript,
            expectedLanguage: expectedLanguage,
            sourceAudioDurationSeconds: sourceAudioDurationSeconds,
            maxWordErrorRate: maxWordErrorRate
        )
    }

    /// Pure evaluation seam for deterministic tests and offline evidence revalidation. It performs
    /// no Speech or file-system operation; the retained recognition evidence is the sole input.
    static func evaluate(
        recognition: VoiceClipTranscriber.VerificationEvidence,
        expectedScript: String,
        expectedLanguage: Qwen3SupportedLanguage,
        sourceAudioDurationSeconds: Double? = nil,
        maxWordErrorRate: Double = VoiceClipTranscriber.outputVerificationDefaultMaxWordErrorRate
    ) -> Result {
        let expectedToken = expectedLanguage.rawValue
        let accuracyMetric = accuracyMetric(for: expectedLanguage)
        let accuracyThreshold = maxWordErrorRate

        guard accuracyThreshold.isFinite, (0 ... 1).contains(accuracyThreshold) else {
            return failed(
                expectedLanguage: expectedLanguage,
                recognition: recognition,
                accuracyMetric: accuracyMetric,
                accuracyThreshold: accuracyThreshold.isFinite ? accuracyThreshold : -1,
                sourceAudioDurationSeconds: sourceAudioDurationSeconds,
                reason: "accuracy_threshold_invalid"
            )
        }
        if let sourceAudioDurationSeconds,
           (!sourceAudioDurationSeconds.isFinite || sourceAudioDurationSeconds <= 0) {
            return failed(
                expectedLanguage: expectedLanguage,
                recognition: recognition,
                accuracyMetric: accuracyMetric,
                accuracyThreshold: accuracyThreshold,
                sourceAudioDurationSeconds: nil,
                reason: "source_audio_duration_invalid"
            )
        }
        if recognition.consensusStatus == .consistent {
            guard VoiceClipTranscriber.isValidConsistentEvidence(
                recognition,
                expectedLanguage: expectedLanguage
            ) else {
                return failed(
                    expectedLanguage: expectedLanguage,
                    recognition: recognition,
                    accuracyMetric: accuracyMetric,
                    accuracyThreshold: accuracyThreshold,
                    sourceAudioDurationSeconds: sourceAudioDurationSeconds,
                    reason: "speech_recognition_evidence_invalid"
                )
            }
            if let sourceAudioDurationSeconds,
               !VoiceClipTranscriber.hasCompleteTemporalCoverage(
                   recognition,
                   sourceAudioDurationSeconds: sourceAudioDurationSeconds
               ) {
                return failed(
                    expectedLanguage: expectedLanguage,
                    recognition: recognition,
                    accuracyMetric: accuracyMetric,
                    accuracyThreshold: accuracyThreshold,
                    sourceAudioDurationSeconds: sourceAudioDurationSeconds,
                    reason: "speech_recognition_incomplete_temporal_coverage"
                )
            }
        }

        guard recognition.consensusStatus == .consistent,
              recognition.evidenceConsistency,
              let transcript = recognition.transcript else {
            return failed(
                expectedLanguage: expectedLanguage,
                recognition: recognition,
                accuracyMetric: accuracyMetric,
                accuracyThreshold: accuracyThreshold,
                sourceAudioDurationSeconds: sourceAudioDurationSeconds,
                reason: failureReason(for: recognition)
            )
        }

        // Exact transcript consensus also guarantees identical deterministic edit metrics for all
        // repetitions. Compute them once only after the conservative consensus gate.
        let detected = PromptLanguageDetector.detect(transcript)
        let languageScore = VoiceClipTranscriber.languageMatchScore(
            text: transcript,
            expected: expectedLanguage
        )
        let languagePass = languageScore >= VoiceClipTranscriber.outputVerificationLanguagePassScore
        let wordMetrics = VoiceClipTranscriber.wordErrorMetrics(
            reference: expectedScript,
            hypothesis: transcript
        )
        let characterMetrics = VoiceClipTranscriber.characterErrorMetrics(
            reference: expectedScript,
            hypothesis: transcript,
            expectedLanguage: expectedLanguage
        )
        let accuracyValue = switch accuracyMetric {
        case .wordErrorRate: wordMetrics.errorRate
        case .characterErrorRate: characterMetrics.errorRate
        }
        let accuracyPass = accuracyValue <= accuracyThreshold

        return Result(
            schemaVersion: Result.currentSchemaVersion,
            algorithmVersion: Result.currentAlgorithmVersion,
            transcript: transcript,
            detectedLanguage: detected.rawValue,
            expectedLanguage: expectedToken,
            languageMatchScore: languageScore,
            wordErrorRate: wordMetrics.errorRate,
            characterErrorRate: characterMetrics.errorRate,
            accuracyMetricVersion: Result.currentAccuracyMetricVersion,
            accuracyMetric: accuracyMetric,
            accuracyThreshold: accuracyThreshold,
            accuracyValue: accuracyValue,
            referenceTokenCount: wordMetrics.referenceCount,
            hypothesisTokenCount: wordMetrics.hypothesisCount,
            referenceCharacterCount: characterMetrics.referenceCount,
            hypothesisCharacterCount: characterMetrics.hypothesisCount,
            substitutions: wordMetrics.substitutions,
            insertions: wordMetrics.insertions,
            deletions: wordMetrics.deletions,
            characterSubstitutions: characterMetrics.substitutions,
            characterInsertions: characterMetrics.insertions,
            characterDeletions: characterMetrics.deletions,
            sourceAudioDurationSeconds: sourceAudioDurationSeconds,
            languagePass: languagePass,
            accuracyPass: accuracyPass,
            pass: languagePass && accuracyPass,
            skipReason: nil,
            recognition: recognition
        )
    }

    private static func failed(
        expectedLanguage: Qwen3SupportedLanguage,
        recognition: VoiceClipTranscriber.VerificationEvidence,
        accuracyMetric: AccuracyMetric,
        accuracyThreshold: Double,
        sourceAudioDurationSeconds: Double?,
        reason: String
    ) -> Result {
        Result(
            schemaVersion: Result.currentSchemaVersion,
            algorithmVersion: Result.currentAlgorithmVersion,
            transcript: "",
            detectedLanguage: Qwen3SupportedLanguage.auto.rawValue,
            expectedLanguage: expectedLanguage.rawValue,
            languageMatchScore: 0,
            wordErrorRate: nil,
            characterErrorRate: nil,
            accuracyMetricVersion: Result.currentAccuracyMetricVersion,
            accuracyMetric: accuracyMetric,
            accuracyThreshold: accuracyThreshold,
            accuracyValue: nil,
            referenceTokenCount: nil,
            hypothesisTokenCount: nil,
            referenceCharacterCount: nil,
            hypothesisCharacterCount: nil,
            substitutions: nil,
            insertions: nil,
            deletions: nil,
            characterSubstitutions: nil,
            characterInsertions: nil,
            characterDeletions: nil,
            sourceAudioDurationSeconds: sourceAudioDurationSeconds,
            languagePass: false,
            accuracyPass: nil,
            pass: false,
            skipReason: reason,
            recognition: recognition
        )
    }

    static func accuracyMetric(for language: Qwen3SupportedLanguage) -> AccuracyMetric {
        switch language {
        case .chinese, .japanese:
            return .characterErrorRate
        case .auto, .english, .korean, .german, .french, .russian, .portuguese, .spanish, .italian:
            return .wordErrorRate
        }
    }

    private static func failureReason(
        for evidence: VoiceClipTranscriber.VerificationEvidence
    ) -> String {
        switch evidence.consensusStatus {
        case .inconsistent:
            return "speech_recognition_inconsistent"
        case .incomplete:
            return "speech_recognition_incomplete"
        case .unavailable:
            return "speech_recognition_unavailable"
        case .failed:
            if evidence.authorizationStatus == .timedOut {
                return "speech_authorization_timed_out"
            }
            if evidence.authorizationStatus != .authorized {
                return "speech_recognition_unauthorized"
            }
            if evidence.repetitions.contains(where: { $0.finalResultStatus == .timedOut }) {
                return "speech_recognition_timed_out"
            }
            if evidence.repetitions.contains(where: { $0.finalResultStatus == .recognitionError }) {
                return "speech_recognition_error"
            }
            return "transcription_failed"
        case .consistent:
            return "transcription_failed"
        }
    }
}
