import AVFoundation
import CryptoKit
import Foundation
import NaturalLanguage
import QwenVoiceCore
import Speech
import Synchronization

/// Best-effort **on-device** transcription + language detection of a finished reference WAV, used
/// to pre-fill the editable transcript and propose separate reference-language metadata when
/// enrolling a recorded voice. It never selects the language of a future Clone output.
///
/// Enrollment remains intentionally best-effort and single-pass. Benchmark output verification uses
/// `verificationEvidence` instead: it pins one locale and requires three independent recognition
/// passes over the same immutable file, stopping early once consensus is impossible.
enum VoiceClipTranscriber {
    /// Why automatic transcription may currently be unavailable — drives the
    /// permission captions in the enrollment/clone UI instead of failing
    /// silently.
    enum TranscriptionAvailability: Equatable {
        case available
        case notDetermined
        case denied
        case siriDisabled
    }

    enum AuthorizationState: String, Codable, Sendable, Equatable {
        case authorized
        case notDetermined
        case denied
        case restricted
        case siriDisabled
        case timedOut
        case unknown
    }

    enum RecognitionFinalStatus: String, Codable, Sendable, Equatable {
        case finalResult
        case emptyTranscript
        case recognitionError
        case recognizerUnavailable
        case onDeviceRecognitionUnsupported
        case timedOut
    }

    enum VerificationConsensusStatus: String, Codable, Sendable, Equatable {
        case consistent
        case inconsistent
        case incomplete
        case unavailable
        case failed
    }

    struct RecognitionPass: Codable, Sendable, Equatable {
        var passIndex: Int
        var localeIdentifier: String
        var authorizationStatus: AuthorizationState
        var recognizerAvailable: Bool
        var supportsOnDeviceRecognition: Bool
        var finalResultStatus: RecognitionFinalStatus
        var recognitionDurationSeconds: Double
        var transcript: String?
        var segmentCount: Int
        var segmentStartSeconds: Double?
        var segmentEndSeconds: Double?
        var timingCoverageSeconds: Double?
        var averageConfidence: Double?
        var minimumConfidence: Double?
        var errorDomain: String?
        var errorCode: Int?
    }

    enum EnrollmentOutcome: String, Codable, Sendable, Equatable {
        case success
        case permissionDenied
        case authorizationTimedOut
        case noCandidateLocales
        case recognizerUnavailable
        case onDeviceRecognitionUnsupported
        case recognitionTimedOut
        case recognitionFailed
        case emptyResult
        case lowConfidence
    }

    /// Privacy-safe enrollment evidence. It deliberately retains no
    /// transcript text, local path, or raw framework error. The accompanying
    /// in-memory `EnrollmentResult` carries text only to the review UI.
    struct EnrollmentLocaleAttempt: Codable, Sendable, Equatable {
        var order: Int
        var localeIdentifier: String
        var language: String
        var recognizerAvailable: Bool
        var supportsOnDeviceRecognition: Bool
        var status: RecognitionFinalStatus
        var transcriptDigest: String?
        var transcriptCharacters: Int
        var languageScore: Double?
        var averageConfidence: Double?
    }

    struct EnrollmentEvidence: Codable, Sendable, Equatable {
        static let currentSchemaVersion = 1
        static let currentAlgorithmVersion = "apple-speech-enrollment-v1"

        var schemaVersion: Int
        var algorithmVersion: String
        var authorizationStatus: AuthorizationState
        var outcome: EnrollmentOutcome
        var attempts: [EnrollmentLocaleAttempt]
        var bestLanguage: String?
        var bestLanguageScore: Double?
        var bestTranscriptConfidence: Double?
    }

    struct EnrollmentResult: Sendable, Equatable {
        var text: String?
        var language: Qwen3SupportedLanguage
        var evidence: EnrollmentEvidence
    }

    struct VerificationEvidence: Codable, Sendable, Equatable {
        static let currentSchemaVersion = 2
        static let currentAlgorithmVersion = "apple-speech-file-consensus-v2"
        static let requiredPassCount = 3

        var schemaVersion: Int
        var algorithmVersion: String
        var expectedLanguage: String
        var selectedLocaleIdentifier: String?
        var authorizationStatus: AuthorizationState
        var recognizerAvailable: Bool
        var supportsOnDeviceRecognition: Bool
        var requiredPassCount: Int
        var recognitionDurationSeconds: Double
        var repetitions: [RecognitionPass]
        var evidenceConsistency: Bool
        var consensusStatus: VerificationConsensusStatus
        var transcript: String?
    }

    struct EditMetrics: Codable, Sendable, Equatable {
        var referenceCount: Int
        var hypothesisCount: Int
        var substitutions: Int
        var insertions: Int
        var deletions: Int
        var errorRate: Double

        var editDistance: Int { substitutions + insertions + deletions }
    }

    struct LocaleCapability: Sendable, Equatable {
        var identifier: String
        var language: Qwen3SupportedLanguage
        var isAvailable: Bool
        var supportsOnDeviceRecognition: Bool
    }

    struct LiveRecognizerObservation: Sendable, Equatable {
        var requestedIdentifier: String
        var recognizerIdentifier: String?
        var language: Qwen3SupportedLanguage
        var isAvailable: Bool
        var supportsOnDeviceRecognition: Bool
    }

    private struct CandidateLocale: Sendable, Equatable {
        var locale: Locale
        var language: Qwen3SupportedLanguage
        var isAvailable: Bool
        var supportsOnDeviceRecognition: Bool
    }

    private struct EditCell {
        var substitutions: Int
        var insertions: Int
        var deletions: Int
        var distance: Int { substitutions + insertions + deletions }
    }

    /// Cheap, prompt-free availability check for UI captions. (The expensive
    /// on-device-locale enumeration is NOT included — a missing model already
    /// degrades gracefully to "no transcript".)
    static func availability() -> TranscriptionAvailability {
        switch authorizationState() {
        case .authorized:
            return .available
        case .notDetermined:
            return .notDetermined
        case .siriDisabled:
            return .siriDisabled
        case .denied, .restricted, .timedOut, .unknown:
            return .denied
        }
    }

    #if os(macOS)
    /// On macOS, SFSpeechRecognizer authorization is auto-DENIED while Siri is
    /// off — an OS gate, no prompt is ever shown. Readable directly because the
    /// app is not sandboxed; defaults to true when unreadable so we never show
    /// a false warning.
    private static var isSiriEnabled: Bool {
        guard let value = UserDefaults(suiteName: "com.apple.assistant.support")?
            .object(forKey: "Assistant Enabled") as? NSNumber else { return true }
        return value.boolValue
    }
    #endif

    private static let confidentLanguageScore = 0.5
    static let outputVerificationLanguagePassScore = 0.5
    static let outputVerificationDefaultMaxWordErrorRate = 0.15
    private static let earlyExitScore = 0.85
    private static let minimumUsableScore = 0.2
    private static let authorizationTimeout: Duration = .seconds(30)
    private static let recognitionPassTimeout: Duration = .seconds(45)

    private static func sha256(_ value: String) -> String {
        SHA256.hash(data: Data(value.utf8))
            .map { String(format: "%02x", $0) }
            .joined()
    }

    /// Produces the privacy-safe enrollment metadata persisted beside a prepared voice.
    /// The evidence digest uses sorted JSON keys so identical typed evidence has one stable
    /// identity on macOS and iOS. The evidence itself remains transient and never stores the
    /// transcript, source path, or raw framework error.
    static func preparedVoiceEnrollmentMetadata(
        referenceLanguage: Qwen3SupportedLanguage,
        reviewState: ReferenceTranscriptionReviewState,
        evidence: EnrollmentEvidence?
    ) throws -> PreparedVoiceEnrollmentMetadata {
        let evidenceDigest: String?
        if let evidence {
            let encoder = JSONEncoder()
            encoder.outputFormatting = [.sortedKeys]
            let data = try encoder.encode(evidence)
            evidenceDigest = SHA256.hash(data: data)
                .map { String(format: "%02x", $0) }
                .joined()
        } else {
            evidenceDigest = nil
        }

        return PreparedVoiceEnrollmentMetadata(
            referenceLanguage: referenceLanguage,
            transcriptSource: reviewState.preparedVoiceTranscriptSource,
            automaticTranscriptionOutcome: evidence?.outcome.rawValue,
            transcriptionEvidenceDigest: evidenceDigest
        )
    }

    static func transcribe(url: URL) async -> (text: String, language: Qwen3SupportedLanguage)? {
        let result = await enrollmentResult(url: url)
        guard let text = result.text else { return nil }
        return (text, result.language)
    }

    static func enrollmentResult(url: URL) async -> EnrollmentResult {
        let authorization = await requestAuthorizationState()
        guard authorization == .authorized else {
            return EnrollmentResult(
                text: nil,
                language: .auto,
                evidence: EnrollmentEvidence(
                    schemaVersion: EnrollmentEvidence.currentSchemaVersion,
                    algorithmVersion: EnrollmentEvidence.currentAlgorithmVersion,
                    authorizationStatus: authorization,
                    outcome: authorization == .timedOut ? .authorizationTimedOut : .permissionDenied,
                    attempts: [],
                    bestLanguage: nil,
                    bestLanguageScore: nil,
                    bestTranscriptConfidence: nil
                )
            )
        }

        let candidates = candidateLocales()
        guard !candidates.isEmpty else {
            return EnrollmentResult(
                text: nil,
                language: .auto,
                evidence: EnrollmentEvidence(
                    schemaVersion: EnrollmentEvidence.currentSchemaVersion,
                    algorithmVersion: EnrollmentEvidence.currentAlgorithmVersion,
                    authorizationStatus: authorization,
                    outcome: .noCandidateLocales,
                    attempts: [],
                    bestLanguage: nil,
                    bestLanguageScore: nil,
                    bestTranscriptConfidence: nil
                )
            )
        }

        var attempts: [EnrollmentLocaleAttempt] = []
        var best: (text: String, language: Qwen3SupportedLanguage, score: Double, confidence: Double)?
        for (offset, candidate) in candidates.enumerated() {
            let pass = await recognizeDetailed(
                url: url,
                candidate: candidate,
                authorizationStatus: authorization,
                passIndex: offset + 1
            )
            let trimmed = pass.transcript?.trimmingCharacters(in: .whitespacesAndNewlines)
            let text = trimmed?.isEmpty == false ? trimmed : nil
            let score = text.map { languageMatchScore(text: $0, expected: candidate.language) }
            attempts.append(EnrollmentLocaleAttempt(
                order: offset + 1,
                localeIdentifier: candidate.locale.identifier,
                language: candidate.language.rawValue,
                recognizerAvailable: pass.recognizerAvailable,
                supportsOnDeviceRecognition: pass.supportsOnDeviceRecognition,
                status: pass.finalResultStatus,
                transcriptDigest: text.map(Self.sha256),
                transcriptCharacters: text?.count ?? 0,
                languageScore: score,
                averageConfidence: pass.averageConfidence
            ))
            if pass.finalResultStatus == .finalResult, let text, let score {
                let confidence = pass.averageConfidence ?? 0
                if best == nil
                    || score > best!.score
                    || (score == best!.score && confidence > best!.confidence) {
                    best = (text, candidate.language, score, confidence)
                }
                if score >= earlyExitScore { break }
            }
        }

        let outcome: EnrollmentOutcome
        if let best, best.score < minimumUsableScore {
            outcome = .lowConfidence
        } else if best != nil {
            outcome = .success
        } else {
            outcome = enrollmentFailureOutcome(attempts)
        }
        let accepted = outcome == .success ? best : nil
        let language = accepted.map {
            $0.score >= confidentLanguageScore ? $0.language : .auto
        } ?? .auto
        return EnrollmentResult(
            text: accepted?.text,
            language: language,
            evidence: EnrollmentEvidence(
                schemaVersion: EnrollmentEvidence.currentSchemaVersion,
                algorithmVersion: EnrollmentEvidence.currentAlgorithmVersion,
                authorizationStatus: authorization,
                outcome: outcome,
                attempts: attempts,
                bestLanguage: best?.language.rawValue,
                bestLanguageScore: best?.score,
                bestTranscriptConfidence: best?.confidence
            )
        )
    }

    static func enrollmentFailureOutcome(
        _ attempts: [EnrollmentLocaleAttempt]
    ) -> EnrollmentOutcome {
        let statuses = Set(attempts.map(\.status))
        if statuses.contains(.timedOut) { return .recognitionTimedOut }
        if statuses.contains(.recognitionError) { return .recognitionFailed }
        if statuses.contains(.emptyTranscript) { return .emptyResult }
        if statuses.contains(.onDeviceRecognitionUnsupported) {
            return .onDeviceRecognitionUnsupported
        }
        return .recognizerUnavailable
    }

    /// Compatibility surface for callers that need only a transcript. Unlike enrollment, output
    /// verification requires three consistent passes and never chooses the most favorable result.
    static func transcribeForVerification(
        url: URL,
        expectedLanguage: Qwen3SupportedLanguage
    ) async -> String? {
        await verificationEvidence(url: url, expectedLanguage: expectedLanguage).transcript
    }

    /// Captures deterministic, bounded ASR evidence for output verification. One locale is selected
    /// once, then the exact same URL and locale are used for up to three sequential passes. Success
    /// requires all three; a terminal failure or disagreement stops immediately.
    static func verificationEvidence(
        url: URL,
        expectedLanguage: Qwen3SupportedLanguage
    ) async -> VerificationEvidence {
        let candidates = candidateLocales().filter { $0.language == expectedLanguage }
        let selected = candidates.first
        let authorization = await requestAuthorizationState()
        let recognizerAvailable = selected?.isAvailable ?? false
        let supportsOnDeviceRecognition = selected?.supportsOnDeviceRecognition ?? false

        guard expectedLanguage != .auto,
              let selected,
              authorization == .authorized,
              recognizerAvailable,
              supportsOnDeviceRecognition else {
            let status: VerificationConsensusStatus = authorization == .authorized
                ? .unavailable
                : .failed
            return VerificationEvidence(
                schemaVersion: VerificationEvidence.currentSchemaVersion,
                algorithmVersion: VerificationEvidence.currentAlgorithmVersion,
                expectedLanguage: expectedLanguage.rawValue,
                selectedLocaleIdentifier: selected?.locale.identifier,
                authorizationStatus: authorization,
                recognizerAvailable: recognizerAvailable,
                supportsOnDeviceRecognition: supportsOnDeviceRecognition,
                requiredPassCount: VerificationEvidence.requiredPassCount,
                recognitionDurationSeconds: 0,
                repetitions: [],
                evidenceConsistency: false,
                consensusStatus: status,
                transcript: nil
            )
        }

        var repetitions: [RecognitionPass] = []
        repetitions.reserveCapacity(VerificationEvidence.requiredPassCount)
        for passIndex in 1 ... VerificationEvidence.requiredPassCount {
            let pass = await recognizeDetailed(
                url: url,
                candidate: selected,
                authorizationStatus: authorization,
                passIndex: passIndex
            )
            repetitions.append(pass)
            guard shouldContinueVerification(after: repetitions) else { break }
        }

        let consensus = consensus(for: repetitions, requiredPassCount: VerificationEvidence.requiredPassCount)
        return VerificationEvidence(
            schemaVersion: VerificationEvidence.currentSchemaVersion,
            algorithmVersion: VerificationEvidence.currentAlgorithmVersion,
            expectedLanguage: expectedLanguage.rawValue,
            selectedLocaleIdentifier: selected.locale.identifier,
            authorizationStatus: authorization,
            recognizerAvailable: recognizerAvailable,
            supportsOnDeviceRecognition: supportsOnDeviceRecognition,
            requiredPassCount: VerificationEvidence.requiredPassCount,
            recognitionDurationSeconds: repetitions.reduce(0) { $0 + $1.recognitionDurationSeconds },
            repetitions: repetitions,
            evidenceConsistency: consensus.status == .consistent,
            consensusStatus: consensus.status,
            transcript: consensus.transcript
        )
    }

    static func consensus(
        for passes: [RecognitionPass],
        requiredPassCount: Int = VerificationEvidence.requiredPassCount
    ) -> (status: VerificationConsensusStatus, transcript: String?) {
        guard passes.allSatisfy({ $0.finalResultStatus == .finalResult }) else {
            return (.failed, nil)
        }
        let transcripts = passes.compactMap(\.transcript)
        guard transcripts.count == passes.count, let first = transcripts.first else {
            return (.failed, nil)
        }
        guard transcripts.dropFirst().allSatisfy({ $0 == first }) else {
            return (.inconsistent, nil)
        }
        guard passes.count == requiredPassCount else { return (.incomplete, nil) }
        return (.consistent, first)
    }

    /// Stops deterministic repetition as soon as exact consensus has become impossible. A failed
    /// terminal pass or a transcript disagreement can never be repaired by a later pass.
    static func shouldContinueVerification(
        after passes: [RecognitionPass],
        requiredPassCount: Int = VerificationEvidence.requiredPassCount
    ) -> Bool {
        guard !passes.isEmpty else { return requiredPassCount > 0 }
        guard passes.count < requiredPassCount else { return false }
        guard passes.allSatisfy({ $0.finalResultStatus == .finalResult }) else { return false }
        let transcripts = passes.compactMap(\.transcript)
        guard transcripts.count == passes.count, let first = transcripts.first else { return false }
        return transcripts.dropFirst().allSatisfy { $0 == first }
    }

    /// Fail-closed structural validation for a claimed successful consensus. This does not consult
    /// live Speech state, so retained evidence can be revalidated deterministically offline.
    static func isValidConsistentEvidence(
        _ evidence: VerificationEvidence,
        expectedLanguage: Qwen3SupportedLanguage
    ) -> Bool {
        guard expectedLanguage != .auto,
              evidence.schemaVersion == VerificationEvidence.currentSchemaVersion,
              evidence.algorithmVersion == VerificationEvidence.currentAlgorithmVersion,
              evidence.expectedLanguage == expectedLanguage.rawValue,
              evidence.authorizationStatus == .authorized,
              evidence.recognizerAvailable,
              evidence.supportsOnDeviceRecognition,
              evidence.requiredPassCount == VerificationEvidence.requiredPassCount,
              evidence.repetitions.count == VerificationEvidence.requiredPassCount,
              evidence.repetitions.map(\.passIndex) == Array(1 ... VerificationEvidence.requiredPassCount),
              evidence.evidenceConsistency,
              evidence.consensusStatus == .consistent,
              let selectedLocale = evidence.selectedLocaleIdentifier?.trimmingCharacters(in: .whitespacesAndNewlines),
              !selectedLocale.isEmpty,
              selectedLocale.lowercased() != "auto",
              evidence.selectedLocaleIdentifier == selectedLocale,
              localeMatchesExpectedLanguage(
                  identifier: selectedLocale,
                  expected: expectedLanguage
              ),
              let transcript = evidence.transcript?.trimmingCharacters(in: .whitespacesAndNewlines),
              !transcript.isEmpty,
              evidence.transcript == transcript,
              isPositiveFinite(evidence.recognitionDurationSeconds) else {
            return false
        }

        let passDuration = evidence.repetitions.reduce(0) { $0 + $1.recognitionDurationSeconds }
        guard approximatelyEqual(passDuration, evidence.recognitionDurationSeconds) else {
            return false
        }

        for pass in evidence.repetitions {
            guard pass.localeIdentifier == selectedLocale,
                  pass.authorizationStatus == .authorized,
                  pass.recognizerAvailable,
                  pass.supportsOnDeviceRecognition,
                  pass.finalResultStatus == .finalResult,
                  pass.transcript == transcript,
                  isPositiveFinite(pass.recognitionDurationSeconds),
                  pass.segmentCount > 0,
                  let segmentStart = pass.segmentStartSeconds,
                  segmentStart.isFinite,
                  segmentStart >= 0,
                  let segmentEnd = pass.segmentEndSeconds,
                  segmentEnd.isFinite,
                  segmentEnd > segmentStart,
                  let coverage = pass.timingCoverageSeconds,
                  isPositiveFinite(coverage),
                  approximatelyEqual(coverage, segmentEnd - segmentStart),
                  let averageConfidence = pass.averageConfidence,
                  averageConfidence.isFinite,
                  (0 ... 1).contains(averageConfidence),
                  let minimumConfidence = pass.minimumConfidence,
                  minimumConfidence.isFinite,
                  (0 ... 1).contains(minimumConfidence),
                  minimumConfidence <= averageConfidence,
                  pass.errorDomain == nil,
                  pass.errorCode == nil else {
                return false
            }
        }

        let recomputed = consensus(
            for: evidence.repetitions,
            requiredPassCount: evidence.requiredPassCount
        )
        return recomputed.status == .consistent && recomputed.transcript == transcript
    }

    /// NaturalLanguage probability mass that the text is in `expected` (handles script/region
    /// variants like zh-Hans/zh-Hant, pt-BR/pt-PT by collapsing to the base language code).
    static func languageMatchScore(text: String, expected: Qwen3SupportedLanguage) -> Double {
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return 0 }
        let recognizer = NLLanguageRecognizer()
        recognizer.processString(trimmed)
        let hypotheses = recognizer.languageHypotheses(withMaximum: 5).map {
            (languageIdentifier: $0.key.rawValue, probability: $0.value)
        }
        return boundedLanguageMatchScore(hypotheses: hypotheses, expected: expected)
    }

    /// Aggregates region/script variants into one base-language probability while preserving the
    /// schema's [0, 1] range. `NLLanguageRecognizer` can report one variant at 1.0 plus a tiny
    /// positive probability for another variant, so the raw floating-point sum is not bounded.
    static func boundedLanguageMatchScore(
        hypotheses: [(languageIdentifier: String, probability: Double)],
        expected: Qwen3SupportedLanguage
    ) -> Double {
        guard expected != .auto else { return 0 }
        var score = 0.0
        for (languageIdentifier, probability) in hypotheses
        where probability.isFinite && probability > 0 {
            let code = Locale(identifier: languageIdentifier).language.languageCode?.identifier
                ?? languageIdentifier
            if Qwen3SupportedLanguage.normalized(code) == expected {
                score += probability
            }
        }
        return min(1, max(0, score))
    }

    static func localeMatchesExpectedLanguage(
        identifier: String,
        expected: Qwen3SupportedLanguage
    ) -> Bool {
        guard expected != .auto,
              let code = Locale(identifier: identifier).language.languageCode?.identifier else {
            return false
        }
        return Qwen3SupportedLanguage.normalized(code) == expected
    }

    static func wordErrorMetrics(reference: String, hypothesis: String) -> EditMetrics {
        editMetrics(lhs: normalizedWordTokens(reference), rhs: normalizedWordTokens(hypothesis))
    }

    static func characterErrorMetrics(
        reference: String,
        hypothesis: String,
        expectedLanguage: Qwen3SupportedLanguage = .auto
    ) -> EditMetrics {
        let preservesDiacritics = expectedLanguage == .chinese || expectedLanguage == .japanese
        return editMetrics(
            lhs: normalizedCharacterTokens(reference, preservesDiacritics: preservesDiacritics),
            rhs: normalizedCharacterTokens(hypothesis, preservesDiacritics: preservesDiacritics)
        )
    }

    static func wordErrorRate(reference: String, hypothesis: String) -> Double {
        wordErrorMetrics(reference: reference, hypothesis: hypothesis).errorRate
    }

    /// Pure deterministic selection seam used by tests. Availability is preferred before the user's
    /// language-region rank; identifier is the final stable tie-breaker.
    static func selectedCapabilities(
        from capabilities: [LocaleCapability],
        preferredLanguages: [String]
    ) -> [LocaleCapability] {
        func regionRank(_ identifier: String) -> Int {
            let locale = Locale(identifier: identifier)
            for (index, preferred) in preferredLanguages.enumerated()
            where preferred.caseInsensitiveCompare(identifier) == .orderedSame {
                return index
            }
            for (index, preferred) in preferredLanguages.enumerated()
            where Locale(identifier: preferred).language.languageCode?.identifier
                == locale.language.languageCode?.identifier {
                return 100 + index
            }
            return 1000
        }

        let eligible = capabilities
            .filter { $0.language != .auto && $0.supportsOnDeviceRecognition }
            .sorted { lhs, rhs in
                if lhs.language != rhs.language { return lhs.language.rawValue < rhs.language.rawValue }
                if lhs.isAvailable != rhs.isAvailable { return lhs.isAvailable && !rhs.isAvailable }
                let lhsRank = regionRank(lhs.identifier)
                let rhsRank = regionRank(rhs.identifier)
                if lhsRank != rhsRank { return lhsRank < rhsRank }
                return lhs.identifier < rhs.identifier
            }

        var seen: Set<Qwen3SupportedLanguage> = []
        return eligible.filter { seen.insert($0.language).inserted }
            .sorted { lhs, rhs in
                let lhsRank = regionRank(lhs.identifier)
                let rhsRank = regionRank(rhs.identifier)
                if lhsRank != rhsRank { return lhsRank < rhsRank }
                if lhs.language != rhs.language { return lhs.language.rawValue < rhs.language.rawValue }
                return lhs.identifier < rhs.identifier
            }
    }

    /// Reads the legacy Speech recognizer state for one exact locale. The iOS speech-asset
    /// bootstrap uses this after installing the modern `DictationTranscriber` assets so its
    /// report reflects the same `SFSpeechRecognizer.supportsOnDeviceRecognition` signal that
    /// Vocello's output verifier consumes.
    static func liveRecognizerObservation(for locale: Locale) -> LiveRecognizerObservation {
        let recognizer = SFSpeechRecognizer(locale: locale)
        return LiveRecognizerObservation(
            requestedIdentifier: locale.identifier,
            recognizerIdentifier: recognizer?.locale.identifier,
            language: Qwen3SupportedLanguage.normalized(
                locale.language.languageCode?.identifier
            ),
            isAvailable: recognizer?.isAvailable ?? false,
            supportsOnDeviceRecognition: recognizer?.supportsOnDeviceRecognition ?? false
        )
    }

    static func liveCapability(for locale: Locale) -> LocaleCapability {
        let observation = liveRecognizerObservation(for: locale)
        return LocaleCapability(
            // Preserve the identifier supplied by `supportedLocales()`. Region ranking and the
            // selected locale used for recognition must not change merely because a recognizer
            // reports a canonicalized identifier.
            identifier: locale.identifier,
            language: observation.language,
            isAvailable: observation.isAvailable,
            supportsOnDeviceRecognition: observation.supportsOnDeviceRecognition
        )
    }

    /// Re-evaluates the complete legacy locale inventory and applies Vocello's deterministic
    /// selection policy. This is intentionally a fresh read rather than cached capability data.
    static func liveSelectedCapabilities(
        preferredLanguages: [String] = Locale.preferredLanguages
    ) -> [LocaleCapability] {
        let capabilities = SFSpeechRecognizer.supportedLocales().map(liveCapability(for:))
        return selectedCapabilities(
            from: capabilities,
            preferredLanguages: preferredLanguages
        )
    }

    private static func normalizedWordTokens(_ text: String) -> [String] {
        text
            .folding(options: [.diacriticInsensitive, .widthInsensitive], locale: Locale(identifier: "en_US_POSIX"))
            .lowercased(with: Locale(identifier: "en_US_POSIX"))
            .components(separatedBy: CharacterSet.alphanumerics.inverted)
            .filter { !$0.isEmpty }
    }

    private static func normalizedCharacterTokens(
        _ text: String,
        preservesDiacritics: Bool
    ) -> [Character] {
        var options: String.CompareOptions = [.widthInsensitive]
        if !preservesDiacritics { options.insert(.diacriticInsensitive) }
        let folded = text
            .folding(options: options, locale: Locale(identifier: "en_US_POSIX"))
            .lowercased(with: Locale(identifier: "en_US_POSIX"))
        return Array(
            folded.unicodeScalars
                .filter { CharacterSet.alphanumerics.contains($0) }
                .map(String.init)
                .joined()
        )
    }

    private static func isPositiveFinite(_ value: Double) -> Bool {
        value.isFinite && value > 0
    }

    private static func approximatelyEqual(_ lhs: Double, _ rhs: Double) -> Bool {
        guard lhs.isFinite, rhs.isFinite else { return false }
        let scale = max(1, max(abs(lhs), abs(rhs)))
        return abs(lhs - rhs) <= scale * 1e-9
    }

    private static func editMetrics<T: Equatable>(lhs: [T], rhs: [T]) -> EditMetrics {
        var previous = (0 ... rhs.count).map {
            EditCell(substitutions: 0, insertions: $0, deletions: 0)
        }
        for (leftIndex, left) in lhs.enumerated() {
            var current = [EditCell(substitutions: 0, insertions: 0, deletions: leftIndex + 1)]
            current.reserveCapacity(rhs.count + 1)
            for (rightIndex, right) in rhs.enumerated() {
                var diagonal = previous[rightIndex]
                if left != right { diagonal.substitutions += 1 }
                var deletion = previous[rightIndex + 1]
                deletion.deletions += 1
                var insertion = current[rightIndex]
                insertion.insertions += 1

                // Stable tie policy: diagonal/substitution, then deletion, then insertion.
                var best = diagonal
                if deletion.distance < best.distance { best = deletion }
                if insertion.distance < best.distance { best = insertion }
                current.append(best)
            }
            previous = current
        }

        let final = previous[rhs.count]
        let rate: Double
        if lhs.isEmpty {
            rate = rhs.isEmpty ? 0 : 1
        } else {
            rate = Double(final.distance) / Double(lhs.count)
        }
        return EditMetrics(
            referenceCount: lhs.count,
            hypothesisCount: rhs.count,
            substitutions: final.substitutions,
            insertions: final.insertions,
            deletions: final.deletions,
            errorRate: rate
        )
    }

    /// One deterministic, available, on-device-capable locale per Qwen language.
    private static func candidateLocales() -> [CandidateLocale] {
        liveSelectedCapabilities()
            .map {
                CandidateLocale(
                    locale: Locale(identifier: $0.identifier),
                    language: $0.language,
                    isAvailable: $0.isAvailable,
                    supportsOnDeviceRecognition: $0.supportsOnDeviceRecognition
                )
            }
    }

    private static func recognizeForEnrollment(
        url: URL,
        candidate: CandidateLocale
    ) async -> (text: String, confidence: Float)? {
        let pass = await recognizeDetailed(
            url: url,
            candidate: candidate,
            authorizationStatus: .authorized,
            passIndex: 1
        )
        guard pass.finalResultStatus == .finalResult,
              let text = pass.transcript else { return nil }
        return (text, Float(pass.averageConfidence ?? 0))
    }

    private static func recognizeDetailed(
        url: URL,
        candidate: CandidateLocale,
        authorizationStatus: AuthorizationState,
        passIndex: Int
    ) async -> RecognitionPass {
        let start = ProcessInfo.processInfo.systemUptime
        guard let recognizer = SFSpeechRecognizer(locale: candidate.locale) else {
            return unavailablePass(
                passIndex: passIndex,
                candidate: candidate,
                authorizationStatus: authorizationStatus,
                status: .recognizerUnavailable,
                startedAt: start
            )
        }
        let isAvailable = recognizer.isAvailable
        let supportsOnDevice = recognizer.supportsOnDeviceRecognition
        guard isAvailable else {
            return unavailablePass(
                passIndex: passIndex,
                candidate: candidate,
                authorizationStatus: authorizationStatus,
                status: .recognizerUnavailable,
                startedAt: start
            )
        }
        guard supportsOnDevice else {
            return unavailablePass(
                passIndex: passIndex,
                candidate: candidate,
                authorizationStatus: authorizationStatus,
                status: .onDeviceRecognitionUnsupported,
                startedAt: start
            )
        }

        let request = SFSpeechURLRecognitionRequest(url: url)
        request.requiresOnDeviceRecognition = true
        request.shouldReportPartialResults = false
        let controller = SpeechRecognitionTaskController()

        return await withCheckedContinuation { (continuation: CheckedContinuation<RecognitionPass, Never>) in
            let timeoutTask = Task {
                do {
                    try await Task.sleep(for: recognitionPassTimeout)
                } catch {
                    return
                }
                guard controller.claimAndCancel() else { return }
                continuation.resume(returning: RecognitionPass(
                    passIndex: passIndex,
                    localeIdentifier: candidate.locale.identifier,
                    authorizationStatus: authorizationStatus,
                    recognizerAvailable: isAvailable,
                    supportsOnDeviceRecognition: supportsOnDevice,
                    finalResultStatus: .timedOut,
                    recognitionDurationSeconds: max(0, ProcessInfo.processInfo.systemUptime - start),
                    transcript: nil,
                    segmentCount: 0,
                    segmentStartSeconds: nil,
                    segmentEndSeconds: nil,
                    timingCoverageSeconds: nil,
                    averageConfidence: nil,
                    minimumConfidence: nil,
                    errorDomain: nil,
                    errorCode: nil
                ))
            }

            let recognitionTask = recognizer.recognitionTask(with: request) { result, error in
                if let error {
                    guard controller.claimCompletion() else { return }
                    timeoutTask.cancel()
                    let duration = max(0, ProcessInfo.processInfo.systemUptime - start)
                    let nsError = error as NSError
                    continuation.resume(returning: RecognitionPass(
                        passIndex: passIndex,
                        localeIdentifier: candidate.locale.identifier,
                        authorizationStatus: authorizationStatus,
                        recognizerAvailable: isAvailable,
                        supportsOnDeviceRecognition: supportsOnDevice,
                        finalResultStatus: .recognitionError,
                        recognitionDurationSeconds: duration,
                        transcript: nil,
                        segmentCount: 0,
                        segmentStartSeconds: nil,
                        segmentEndSeconds: nil,
                        timingCoverageSeconds: nil,
                        averageConfidence: nil,
                        minimumConfidence: nil,
                        errorDomain: boundedErrorDomain(nsError.domain),
                        errorCode: nsError.code
                    ))
                    return
                }
                guard let result, result.isFinal else {
                    // Partial callbacks are deliberately ignored. With partial results disabled,
                    // Speech eventually supplies either a final result or an error.
                    return
                }
                guard controller.claimCompletion() else { return }
                timeoutTask.cancel()
                let duration = max(0, ProcessInfo.processInfo.systemUptime - start)
                let transcription = result.bestTranscription
                let text = transcription.formattedString.trimmingCharacters(in: .whitespacesAndNewlines)
                let segments = transcription.segments
                let startTime = segments.map(\.timestamp).min()
                let endTime = segments.map { $0.timestamp + $0.duration }.max()
                let confidences = segments.map { Double($0.confidence) }
                let averageConfidence = confidences.isEmpty
                    ? nil
                    : confidences.reduce(0, +) / Double(confidences.count)
                let timingCoverage: Double? = if let startTime, let endTime {
                    max(0, endTime - startTime)
                } else {
                    nil
                }
                continuation.resume(returning: RecognitionPass(
                    passIndex: passIndex,
                    localeIdentifier: candidate.locale.identifier,
                    authorizationStatus: authorizationStatus,
                    recognizerAvailable: isAvailable,
                    supportsOnDeviceRecognition: supportsOnDevice,
                    finalResultStatus: text.isEmpty ? .emptyTranscript : .finalResult,
                    recognitionDurationSeconds: duration,
                    transcript: text.isEmpty ? nil : text,
                    segmentCount: segments.count,
                    segmentStartSeconds: startTime,
                    segmentEndSeconds: endTime,
                    timingCoverageSeconds: timingCoverage,
                    averageConfidence: averageConfidence,
                    minimumConfidence: confidences.min(),
                    errorDomain: nil,
                    errorCode: nil
                ))
            }
            controller.install(recognitionTask)
        }
    }

    private static func unavailablePass(
        passIndex: Int,
        candidate: CandidateLocale,
        authorizationStatus: AuthorizationState,
        status: RecognitionFinalStatus,
        startedAt: TimeInterval
    ) -> RecognitionPass {
        RecognitionPass(
            passIndex: passIndex,
            localeIdentifier: candidate.locale.identifier,
            authorizationStatus: authorizationStatus,
            recognizerAvailable: candidate.isAvailable,
            supportsOnDeviceRecognition: candidate.supportsOnDeviceRecognition,
            finalResultStatus: status,
            recognitionDurationSeconds: max(0, ProcessInfo.processInfo.systemUptime - startedAt),
            transcript: nil,
            segmentCount: 0,
            segmentStartSeconds: nil,
            segmentEndSeconds: nil,
            timingCoverageSeconds: nil,
            averageConfidence: nil,
            minimumConfidence: nil,
            errorDomain: nil,
            errorCode: nil
        )
    }

    private static func boundedErrorDomain(_ domain: String) -> String {
        let allowed = CharacterSet.alphanumerics.union(CharacterSet(charactersIn: "._-"))
        return String(domain.unicodeScalars.filter { allowed.contains($0) }.prefix(80))
    }

    private static func authorizationState(_ status: SFSpeechRecognizerAuthorizationStatus? = nil) -> AuthorizationState {
        let status = status ?? SFSpeechRecognizer.authorizationStatus()
        switch status {
        case .authorized:
            return .authorized
        case .notDetermined:
            #if os(macOS)
            if !isSiriEnabled { return .siriDisabled }
            #endif
            return .notDetermined
        case .denied:
            #if os(macOS)
            if !isSiriEnabled { return .siriDisabled }
            #endif
            return .denied
        case .restricted:
            return .restricted
        @unknown default:
            return .unknown
        }
    }

    private static func requestAuthorizationState() async -> AuthorizationState {
        let current = authorizationState()
        guard current == .notDetermined else { return current }
        let completion = CompletionClaim()
        return await withCheckedContinuation { continuation in
            let timeoutTask = Task {
                do {
                    try await Task.sleep(for: authorizationTimeout)
                } catch {
                    return
                }
                guard completion.claim() else { return }
                continuation.resume(returning: .timedOut)
            }
            SFSpeechRecognizer.requestAuthorization { status in
                guard completion.claim() else { return }
                timeoutTask.cancel()
                continuation.resume(returning: authorizationState(status))
            }
        }
    }
}

final class CompletionClaim: Sendable {
    private let completed = Mutex(false)

    func claim() -> Bool {
        completed.withLock { completed in
            guard !completed else { return false }
            completed = true
            return true
        }
    }
}

/// Owns the non-Sendable Speech task behind a typed mutex. Callback, timeout, and synchronous task
/// installation can race, but only one terminal path can claim completion. Cancellation occurs
/// outside the lock so no framework callback can re-enter the critical section.
private final class SpeechRecognitionTaskController: Sendable {
    private struct State {
        var didFinish = false
        var task: SpeechRecognitionTaskHandle?
    }

    private let state = Mutex(State())

    func install(_ task: SFSpeechRecognitionTask) {
        let handle = SpeechRecognitionTaskHandle(task)
        let shouldCancel = state.withLock { state in
            if state.didFinish { return true }
            state.task = handle
            return false
        }
        if shouldCancel { handle.cancel() }
    }

    func claimCompletion() -> Bool {
        state.withLock { state in
            guard !state.didFinish else { return false }
            state.didFinish = true
            state.task = nil
            return true
        }
    }

    func claimAndCancel() -> Bool {
        let outcome = state.withLock { state -> (claimed: Bool, task: SpeechRecognitionTaskHandle?) in
            guard !state.didFinish else { return (false, nil) }
            state.didFinish = true
            defer { state.task = nil }
            return (true, state.task)
        }
        guard outcome.claimed else { return false }
        outcome.task?.cancel()
        // A nil task is still a valid claim when the timeout wins before synchronous installation.
        return true
    }
}

/// `SFSpeechRecognitionTask` predates Swift concurrency annotations. Access is serialized by the
/// controller's mutex; this narrow wrapper is the only unchecked boundary around that framework
/// reference and exposes cancellation only.
private final class SpeechRecognitionTaskHandle: @unchecked Sendable {
    private let task: SFSpeechRecognitionTask

    init(_ task: SFSpeechRecognitionTask) {
        self.task = task
    }

    func cancel() {
        task.cancel()
    }
}
