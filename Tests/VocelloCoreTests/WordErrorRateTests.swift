import Foundation
import QwenVoiceCore
import XCTest

final class WordErrorRateTests: XCTestCase {
    func testLiveUnreadableAudioFailsBeforeSpeechWithoutInventingDuration() async throws {
        let result = await GenerationOutputVerifier.verify(
            audioURL: URL(fileURLWithPath: "/missing/\(UUID()).wav"),
            expectedScript: "Hello there.", expectedLanguage: .english
        )
        XCTAssertFalse(result.pass)
        XCTAssertEqual(result.skipReason, "source_audio_duration_unavailable")
        XCTAssertNil(result.sourceAudioDurationSeconds)
        XCTAssertEqual(result.recognition.repetitions.count, 0)
        XCTAssertEqual(result.recognition.authorizationStatus, .unknown)
        XCTAssertEqual(result.languageASRGateResult().outcome, .unavailable)
    }

    func testIdenticalReferenceAndHypothesis() {
        let wer = VoiceClipTranscriber.wordErrorRate(
            reference: "The train left the station.",
            hypothesis: "The train left the station."
        )
        XCTAssertEqual(wer, 0, accuracy: 0.001)
    }

    func testNormalizedPunctuationAndCase() {
        let wer = VoiceClipTranscriber.wordErrorRate(
            reference: "Le train a quitté la gare.",
            hypothesis: "le train a quitte la gare"
        )
        XCTAssertEqual(wer, 0, accuracy: 0.001)
    }

    func testSingleSubstitution() {
        let metrics = VoiceClipTranscriber.wordErrorMetrics(
            reference: "one two three four",
            hypothesis: "one two four four"
        )
        XCTAssertEqual(metrics.errorRate, 0.25, accuracy: 0.001)
        XCTAssertEqual(metrics.referenceCount, 4)
        XCTAssertEqual(metrics.hypothesisCount, 4)
        XCTAssertEqual(metrics.substitutions, 1)
        XCTAssertEqual(metrics.insertions, 0)
        XCTAssertEqual(metrics.deletions, 0)
    }

    func testInsertionDeletionAndCharacterMetrics() {
        let insertion = VoiceClipTranscriber.wordErrorMetrics(
            reference: "one two three",
            hypothesis: "one bright two three"
        )
        XCTAssertEqual(insertion.insertions, 1)
        XCTAssertEqual(insertion.deletions, 0)
        XCTAssertEqual(insertion.errorRate, 1.0 / 3.0, accuracy: 0.001)

        let deletion = VoiceClipTranscriber.wordErrorMetrics(
            reference: "Le train arrive a l aube",
            hypothesis: "Le train arrive"
        )
        XCTAssertEqual(deletion.deletions, 3)
        XCTAssertEqual(deletion.insertions, 0)

        let characters = VoiceClipTranscriber.characterErrorMetrics(
            reference: "Café!",
            hypothesis: "cafe"
        )
        XCTAssertEqual(characters.errorRate, 0, accuracy: 0.001)
        XCTAssertEqual(characters.referenceCount, 4)
    }

    func testLocaleSelectionIsStableAndPrefersAvailablePreferredRegion() {
        let capabilities = [
            VoiceClipTranscriber.LocaleCapability(
                identifier: "fr-CA",
                language: .french,
                isAvailable: true,
                supportsOnDeviceRecognition: true
            ),
            VoiceClipTranscriber.LocaleCapability(
                identifier: "fr-FR",
                language: .french,
                isAvailable: true,
                supportsOnDeviceRecognition: true
            ),
            VoiceClipTranscriber.LocaleCapability(
                identifier: "en-US",
                language: .english,
                isAvailable: false,
                supportsOnDeviceRecognition: true
            ),
            VoiceClipTranscriber.LocaleCapability(
                identifier: "en-GB",
                language: .english,
                isAvailable: true,
                supportsOnDeviceRecognition: true
            )
        ]

        let selected = VoiceClipTranscriber.selectedCapabilities(
            from: Array(capabilities.reversed()),
            preferredLanguages: ["fr-CA", "en-US"]
        )
        XCTAssertEqual(selected.map(\.identifier), ["fr-CA", "en-GB"])
    }

    func testLanguageProbabilityMassIsBoundedAfterCollapsingScriptVariants() {
        let score = VoiceClipTranscriber.boundedLanguageMatchScore(
            hypotheses: [
                ("zh-Hans", 1.0),
                ("zh-Hant", 0.000_000_000_184_127_2),
                ("ja", 0.25),
                ("zh-CN", .nan),
                ("zh-TW", -0.1)
            ],
            expected: .chinese
        )

        XCTAssertEqual(score, 1)
        XCTAssertEqual(
            VoiceClipTranscriber.boundedLanguageMatchScore(
                hypotheses: [("en", 0.75), ("fr", 0.25)],
                expected: .french
            ),
            0.25,
            accuracy: 0.000_001
        )
        XCTAssertEqual(
            VoiceClipTranscriber.boundedLanguageMatchScore(
                hypotheses: [("en", 1.0)],
                expected: .auto
            ),
            0
        )
    }

    func testRecognizerLocaleMustMatchExpectedLanguage() {
        XCTAssertTrue(
            VoiceClipTranscriber.localeMatchesExpectedLanguage(
                identifier: "zh-Hans-CN",
                expected: .chinese
            )
        )
        XCTAssertTrue(
            VoiceClipTranscriber.localeMatchesExpectedLanguage(
                identifier: "fr_CA",
                expected: .french
            )
        )
        XCTAssertFalse(
            VoiceClipTranscriber.localeMatchesExpectedLanguage(
                identifier: "fr-FR",
                expected: .chinese
            )
        )
        XCTAssertFalse(
            VoiceClipTranscriber.localeMatchesExpectedLanguage(
                identifier: "auto",
                expected: .auto
            )
        )
    }

    func testThreePassConsensusRequiresExactAgreement() {
        let matching = (1 ... 3).map { pass(index: $0, transcript: "Bonjour le monde") }
        let consensus = VoiceClipTranscriber.consensus(for: matching)
        XCTAssertEqual(consensus.status, .consistent)
        XCTAssertEqual(consensus.transcript, "Bonjour le monde")

        var inconsistent = matching
        inconsistent[2].transcript = "Bonjour, le monde"
        let rejected = VoiceClipTranscriber.consensus(for: inconsistent)
        XCTAssertEqual(rejected.status, .inconsistent)
        XCTAssertNil(rejected.transcript)

        let incomplete = VoiceClipTranscriber.consensus(for: Array(matching.prefix(2)))
        XCTAssertEqual(incomplete.status, .incomplete)
        XCTAssertNil(incomplete.transcript)
    }

    func testRecognitionErrorPreventsConsensus() {
        var passes = (1 ... 3).map { pass(index: $0, transcript: "Hello") }
        passes[1].finalResultStatus = .recognitionError
        passes[1].transcript = nil
        XCTAssertEqual(VoiceClipTranscriber.consensus(for: passes).status, .failed)
    }

    func testVerificationStopsWhenConsensusBecomesImpossible() {
        let first = pass(index: 1, transcript: "Hello world")
        XCTAssertTrue(VoiceClipTranscriber.shouldContinueVerification(after: [first]))

        var failed = pass(index: 2, transcript: "Hello world")
        failed.finalResultStatus = .recognitionError
        failed.transcript = nil
        XCTAssertFalse(VoiceClipTranscriber.shouldContinueVerification(after: [first, failed]))
        XCTAssertEqual(VoiceClipTranscriber.consensus(for: [first, failed]).status, .failed)

        let disagreement = pass(index: 2, transcript: "Hello word")
        XCTAssertFalse(VoiceClipTranscriber.shouldContinueVerification(after: [first, disagreement]))
        XCTAssertEqual(VoiceClipTranscriber.consensus(for: [first, disagreement]).status, .inconsistent)

        let agreement = pass(index: 2, transcript: "Hello world")
        XCTAssertTrue(VoiceClipTranscriber.shouldContinueVerification(after: [first, agreement]))
    }

    func testAuthorizationCompletionClaimHasExactlyOneWinnerUnderContention() async {
        let completion = CompletionClaim()
        let winners = await withTaskGroup(of: Bool.self, returning: Int.self) { group in
            for _ in 0 ..< 100 {
                group.addTask { completion.claim() }
            }
            var count = 0
            for await won in group where won { count += 1 }
            return count
        }
        XCTAssertEqual(winners, 1)
        XCTAssertFalse(completion.claim())
    }

    func testVerifierRejectsUnauthorizedAndUnavailableEvidenceWithoutFabricatingRates() {
        let unauthorized = evidence(
            authorization: .denied,
            consensus: .failed,
            repetitions: [],
            transcript: nil
        )
        let unauthorizedResult = GenerationOutputVerifier.evaluate(
            recognition: unauthorized,
            expectedScript: "The train left the station",
            expectedLanguage: .english
        )
        XCTAssertEqual(unauthorizedResult.skipReason, "speech_recognition_unauthorized")
        XCTAssertNil(unauthorizedResult.wordErrorRate)
        XCTAssertNil(unauthorizedResult.characterErrorRate)
        XCTAssertNil(unauthorizedResult.accuracyPass)
        XCTAssertFalse(unauthorizedResult.pass)
        XCTAssertEqual(unauthorizedResult.accuracyMetric, .wordErrorRate)
        XCTAssertEqual(unauthorizedResult.accuracyThreshold, 0.15, accuracy: 0.001)

        var unavailable = unauthorized
        unavailable.authorizationStatus = .authorized
        unavailable.consensusStatus = .unavailable
        let unavailableResult = GenerationOutputVerifier.evaluate(
            recognition: unavailable,
            expectedScript: "The train left the station",
            expectedLanguage: .english
        )
        XCTAssertEqual(unavailableResult.skipReason, "speech_recognition_unavailable")
        XCTAssertNil(unavailableResult.wordErrorRate)
    }

    func testVerifierClassifiesErrorTimeoutAndInconsistentEvidence() {
        var errorPasses = (1 ... 3).map { pass(index: $0, transcript: "Hello world") }
        errorPasses[0].finalResultStatus = .recognitionError
        errorPasses[0].transcript = nil
        let errorResult = GenerationOutputVerifier.evaluate(
            recognition: evidence(
                authorization: .authorized,
                consensus: .failed,
                repetitions: errorPasses,
                transcript: nil
            ),
            expectedScript: "Hello world",
            expectedLanguage: .english
        )
        XCTAssertEqual(errorResult.skipReason, "speech_recognition_error")
        XCTAssertNil(errorResult.wordErrorRate)

        var timeoutPasses = (1 ... 3).map { pass(index: $0, transcript: "Hello world") }
        timeoutPasses[2].finalResultStatus = .timedOut
        timeoutPasses[2].transcript = nil
        let timeoutResult = GenerationOutputVerifier.evaluate(
            recognition: evidence(
                authorization: .authorized,
                consensus: .failed,
                repetitions: timeoutPasses,
                transcript: nil
            ),
            expectedScript: "Hello world",
            expectedLanguage: .english
        )
        XCTAssertEqual(timeoutResult.skipReason, "speech_recognition_timed_out")
        XCTAssertNil(timeoutResult.accuracyPass)

        let inconsistentPasses = [
            pass(index: 1, transcript: "Hello world"),
            pass(index: 2, transcript: "Hello word"),
            pass(index: 3, transcript: "Hello world")
        ]
        let inconsistentResult = GenerationOutputVerifier.evaluate(
            recognition: evidence(
                authorization: .authorized,
                consensus: .inconsistent,
                repetitions: inconsistentPasses,
                transcript: nil
            ),
            expectedScript: "Hello world",
            expectedLanguage: .english
        )
        XCTAssertEqual(inconsistentResult.skipReason, "speech_recognition_inconsistent")
        XCTAssertNil(inconsistentResult.wordErrorRate)
    }

    func testVerifierScoresOnlyConsistentEvidenceAndPreservesUncertainDetection() throws {
        let transcript = "1234 5678 9012 3456"
        let consistentPasses = (1 ... 3).map { pass(index: $0, transcript: transcript) }
        let result = GenerationOutputVerifier.evaluate(
            recognition: evidence(
                authorization: .authorized,
                consensus: .consistent,
                repetitions: consistentPasses,
                transcript: transcript
            ),
            expectedScript: "1234 5678 9012 9999",
            expectedLanguage: .english,
            maxWordErrorRate: 0.30
        )

        XCTAssertEqual(try XCTUnwrap(result.wordErrorRate), 0.25, accuracy: 0.001)
        XCTAssertEqual(result.referenceTokenCount, 4)
        XCTAssertEqual(result.hypothesisTokenCount, 4)
        XCTAssertEqual(result.substitutions, 1)
        XCTAssertEqual(result.insertions, 0)
        XCTAssertEqual(result.deletions, 0)
        XCTAssertEqual(result.detectedLanguage, Qwen3SupportedLanguage.auto.rawValue)
        XCTAssertEqual(result.accuracyPass, true)
        XCTAssertEqual(result.accuracyMetricVersion, "normalized-edit-rate-v1")
        XCTAssertEqual(result.accuracyMetric, .wordErrorRate)
        XCTAssertEqual(result.accuracyThreshold, 0.30, accuracy: 0.001)
        XCTAssertEqual(try XCTUnwrap(result.accuracyValue), 0.25, accuracy: 0.001)
        XCTAssertTrue(result.recognition.evidenceConsistency)
    }

    func testChineseAndJapaneseUseCharacterErrorRate() throws {
        let cases: [(Qwen3SupportedLanguage, String, String, String, Double)] = [
            (.chinese, "zh-CN", "今天天气非常适合散步", "今天天气非常适合跑步", 1),
            (.japanese, "ja-JP", "かきくけこさしすせそ", "がきくけこさしすせそ", 1)
        ]

        for (language, locale, reference, transcript, expectedWER) in cases {
            let passes = (1 ... 3).map {
                pass(index: $0, transcript: transcript, localeIdentifier: locale)
            }
            let result = GenerationOutputVerifier.evaluate(
                recognition: evidence(
                    authorization: .authorized,
                    consensus: .consistent,
                    repetitions: passes,
                    transcript: transcript,
                    expectedLanguage: language
                ),
                expectedScript: reference,
                expectedLanguage: language
            )

            XCTAssertEqual(result.accuracyMetric, .characterErrorRate)
            XCTAssertEqual(result.accuracyThreshold, 0.15, accuracy: 0.001)
            XCTAssertEqual(try XCTUnwrap(result.characterErrorRate), 0.10, accuracy: 0.001)
            XCTAssertEqual(try XCTUnwrap(result.wordErrorRate), expectedWER, accuracy: 0.001)
            XCTAssertEqual(try XCTUnwrap(result.accuracyValue), 0.10, accuracy: 0.001)
            XCTAssertEqual(result.characterSubstitutions, 1)
            XCTAssertEqual(result.characterInsertions, 0)
            XCTAssertEqual(result.characterDeletions, 0)
            XCTAssertEqual(result.accuracyPass, true)
        }
    }

    func testClaimedConsistentEvidenceFailsClosedWhenAnyInvariantIsMalformed() {
        let transcript = "The train left the station"
        let passes = (1 ... 3).map { pass(index: $0, transcript: transcript) }
        let valid = evidence(
            authorization: .authorized,
            consensus: .consistent,
            repetitions: passes,
            transcript: transcript
        )
        XCTAssertTrue(VoiceClipTranscriber.isValidConsistentEvidence(valid, expectedLanguage: .english))

        var malformed: [VoiceClipTranscriber.VerificationEvidence] = []

        var wrongSchema = valid
        wrongSchema.schemaVersion += 1
        malformed.append(wrongSchema)

        var wrongAlgorithm = valid
        wrongAlgorithm.algorithmVersion = "unknown"
        malformed.append(wrongAlgorithm)

        var unauthorized = valid
        unauthorized.authorizationStatus = .denied
        malformed.append(unauthorized)

        var unavailable = valid
        unavailable.recognizerAvailable = false
        malformed.append(unavailable)

        var unsupported = valid
        unsupported.supportsOnDeviceRecognition = false
        malformed.append(unsupported)

        var missingLocale = valid
        missingLocale.selectedLocaleIdentifier = nil
        malformed.append(missingLocale)

        var automaticLocale = valid
        automaticLocale.selectedLocaleIdentifier = "auto"
        automaticLocale.repetitions = automaticLocale.repetitions.map { repetition in
            var repetition = repetition
            repetition.localeIdentifier = "auto"
            return repetition
        }
        malformed.append(automaticLocale)

        var wrongDuration = valid
        wrongDuration.recognitionDurationSeconds += 1
        malformed.append(wrongDuration)

        var wrongIndex = valid
        wrongIndex.repetitions[1].passIndex = 7
        malformed.append(wrongIndex)

        var passUnauthorized = valid
        passUnauthorized.repetitions[1].authorizationStatus = .denied
        malformed.append(passUnauthorized)

        var passUnavailable = valid
        passUnavailable.repetitions[1].recognizerAvailable = false
        malformed.append(passUnavailable)

        var passUnsupported = valid
        passUnsupported.repetitions[1].supportsOnDeviceRecognition = false
        malformed.append(passUnsupported)

        var nonFinal = valid
        nonFinal.repetitions[1].finalResultStatus = .recognitionError
        malformed.append(nonFinal)

        var zeroDuration = valid
        zeroDuration.repetitions[1].recognitionDurationSeconds = 0
        malformed.append(zeroDuration)

        var noSegments = valid
        noSegments.repetitions[1].segmentCount = 0
        malformed.append(noSegments)

        var invalidTiming = valid
        invalidTiming.repetitions[1].timingCoverageSeconds = 2
        malformed.append(invalidTiming)

        var invalidConfidence = valid
        invalidConfidence.repetitions[1].averageConfidence = 1.1
        malformed.append(invalidConfidence)

        var embeddedError = valid
        embeddedError.repetitions[1].errorDomain = "SpeechError"
        embeddedError.repetitions[1].errorCode = 1
        malformed.append(embeddedError)

        var wrongLocale = valid
        wrongLocale.repetitions[1].localeIdentifier = "en-GB"
        malformed.append(wrongLocale)

        var wrongLanguageLocale = valid
        wrongLanguageLocale.selectedLocaleIdentifier = "fr-FR"
        wrongLanguageLocale.repetitions = wrongLanguageLocale.repetitions.map { repetition in
            var repetition = repetition
            repetition.localeIdentifier = "fr-FR"
            return repetition
        }
        malformed.append(wrongLanguageLocale)

        var wrongTranscript = valid
        wrongTranscript.repetitions[1].transcript = "The train left a station"
        malformed.append(wrongTranscript)

        for evidence in malformed {
            XCTAssertFalse(
                VoiceClipTranscriber.isValidConsistentEvidence(evidence, expectedLanguage: .english)
            )
            let result = GenerationOutputVerifier.evaluate(
                recognition: evidence,
                expectedScript: transcript,
                expectedLanguage: .english
            )
            XCTAssertEqual(result.skipReason, "speech_recognition_evidence_invalid")
            XCTAssertNil(result.wordErrorRate)
            XCTAssertNil(result.characterErrorRate)
            XCTAssertFalse(result.pass)
        }
    }

    func testVerifierRejectsConsistentTranscriptThatCoversOnlyOneUtterance() {
        let transcript = "Les voyageurs regardaient la rivière"
        let latePasses = (1 ... 3).map { index in
            var value = pass(
                index: index,
                transcript: transcript,
                localeIdentifier: "fr-CA"
            )
            value.segmentStartSeconds = 8.16
            value.segmentEndSeconds = 15.84
            value.timingCoverageSeconds = 7.68
            return value
        }
        let recognition = evidence(
            authorization: .authorized,
            consensus: .consistent,
            repetitions: latePasses,
            transcript: transcript,
            expectedLanguage: .french
        )

        XCTAssertFalse(
            VoiceClipTranscriber.hasCompleteTemporalCoverage(
                recognition,
                sourceAudioDurationSeconds: 16
            )
        )
        let result = GenerationOutputVerifier.evaluate(
            recognition: recognition,
            expectedScript: "Le train du matin a quitté la gare. Les voyageurs regardaient la rivière.",
            expectedLanguage: .french,
            sourceAudioDurationSeconds: 16
        )
        XCTAssertEqual(
            result.skipReason,
            "speech_recognition_incomplete_temporal_coverage"
        )
        XCTAssertEqual(result.sourceAudioDurationSeconds, 16)
        XCTAssertNil(result.wordErrorRate)
        XCTAssertNil(result.accuracyPass)
        XCTAssertFalse(result.pass)
    }

    func testVerifierAcceptsConsensusCoveringBothAudioEdges() {
        let transcript = "Le train du matin a quitté la gare"
        let completePasses = (1 ... 3).map { index in
            var value = pass(
                index: index,
                transcript: transcript,
                localeIdentifier: "fr-CA"
            )
            value.segmentStartSeconds = 0.32
            value.segmentEndSeconds = 15.4
            value.timingCoverageSeconds = 15.08
            return value
        }
        let recognition = evidence(
            authorization: .authorized,
            consensus: .consistent,
            repetitions: completePasses,
            transcript: transcript,
            expectedLanguage: .french
        )

        XCTAssertTrue(
            VoiceClipTranscriber.hasCompleteTemporalCoverage(
                recognition,
                sourceAudioDurationSeconds: 16
            )
        )
        let result = GenerationOutputVerifier.evaluate(
            recognition: recognition,
            expectedScript: transcript,
            expectedLanguage: .french,
            sourceAudioDurationSeconds: 16
        )
        XCTAssertTrue(result.pass)
        XCTAssertEqual(result.sourceAudioDurationSeconds, 16)

        let missingLiveDuration = GenerationOutputVerifier.evaluate(
            recognition: recognition, expectedScript: transcript, expectedLanguage: .french,
            requiresSourceAudioDuration: true
        )
        XCTAssertFalse(missingLiveDuration.pass)
        XCTAssertEqual(missingLiveDuration.skipReason, "source_audio_duration_unavailable")
        // Edge timestamps alone cannot establish interior speech coverage.
        // The same edge-valid transcript still fails when middle words are absent.
        let missingInterior = GenerationOutputVerifier.evaluate(
            recognition: recognition,
            expectedScript: "Le train du matin avec tous les voyageurs et leurs bagages a quitté la gare",
            expectedLanguage: .french, sourceAudioDurationSeconds: 16,
            requiresSourceAudioDuration: true
        )
        XCTAssertTrue(VoiceClipTranscriber.hasAudioEdgeCoverage(recognition, sourceAudioDurationSeconds: 16))
        XCTAssertFalse(missingInterior.pass)

        var trailingOnly = recognition
        trailingOnly.repetitions = trailingOnly.repetitions.map { repetition in
            var repetition = repetition
            repetition.segmentEndSeconds = 8
            repetition.timingCoverageSeconds = 7.68
            return repetition
        }
        XCTAssertFalse(
            VoiceClipTranscriber.hasCompleteTemporalCoverage(
                trailingOnly,
                sourceAudioDurationSeconds: 16
            )
        )
    }

    func testVerifierSchemaThreeDecodesWithoutAddedAudioDuration() throws {
        let transcript = "Hello world"
        let recognition = evidence(
            authorization: .authorized,
            consensus: .consistent,
            repetitions: (1 ... 3).map { pass(index: $0, transcript: transcript) },
            transcript: transcript
        )
        let original = GenerationOutputVerifier.evaluate(
            recognition: recognition,
            expectedScript: transcript,
            expectedLanguage: .english
        )
        let data = try JSONEncoder().encode(original)
        let decoded = try JSONDecoder().decode(
            GenerationOutputVerifier.Result.self,
            from: data
        )

        XCTAssertNil(decoded.sourceAudioDurationSeconds)
        XCTAssertEqual(decoded, original)
    }

    private func pass(
        index: Int,
        transcript: String,
        localeIdentifier: String = "en-US"
    ) -> VoiceClipTranscriber.RecognitionPass {
        VoiceClipTranscriber.RecognitionPass(
            passIndex: index,
            localeIdentifier: localeIdentifier,
            authorizationStatus: .authorized,
            recognizerAvailable: true,
            supportsOnDeviceRecognition: true,
            finalResultStatus: .finalResult,
            recognitionDurationSeconds: 0.5,
            transcript: transcript,
            segmentCount: 3,
            segmentStartSeconds: 0,
            segmentEndSeconds: 1,
            timingCoverageSeconds: 1,
            averageConfidence: 0.9,
            minimumConfidence: 0.8,
            errorDomain: nil,
            errorCode: nil
        )
    }

    private func evidence(
        authorization: VoiceClipTranscriber.AuthorizationState,
        consensus: VoiceClipTranscriber.VerificationConsensusStatus,
        repetitions: [VoiceClipTranscriber.RecognitionPass],
        transcript: String?,
        expectedLanguage: Qwen3SupportedLanguage = .english
    ) -> VoiceClipTranscriber.VerificationEvidence {
        VoiceClipTranscriber.VerificationEvidence(
            schemaVersion: VoiceClipTranscriber.VerificationEvidence.currentSchemaVersion,
            algorithmVersion: VoiceClipTranscriber.VerificationEvidence.currentAlgorithmVersion,
            expectedLanguage: expectedLanguage.rawValue,
            selectedLocaleIdentifier: repetitions.first?.localeIdentifier,
            authorizationStatus: authorization,
            recognizerAvailable: authorization == .authorized,
            supportsOnDeviceRecognition: authorization == .authorized,
            requiredPassCount: VoiceClipTranscriber.VerificationEvidence.requiredPassCount,
            recognitionDurationSeconds: repetitions.reduce(0) { $0 + $1.recognitionDurationSeconds },
            repetitions: repetitions,
            evidenceConsistency: consensus == .consistent,
            consensusStatus: consensus,
            transcript: transcript
        )
    }

    func testLanguageASRGateResultMapsVerifierOutcomeAndConsensus() throws {
        let script = "Hello world"
        let matching = (1 ... 3).map { pass(index: $0, transcript: script) }
        let consistent = evidence(
            authorization: .authorized,
            consensus: .consistent,
            repetitions: matching,
            transcript: script
        )
        var passing = GenerationOutputVerifier.evaluate(
            recognition: consistent,
            expectedScript: script,
            expectedLanguage: .english
        )
        passing.pass = true
        passing.skipReason = nil
        passing.wordErrorRate = 0
        let digest = String(repeating: "d", count: 64)
        let gate = passing.languageASRGateResult(evidenceDigest: digest)
        XCTAssertEqual(gate.gate, .languageASR)
        XCTAssertEqual(gate.outcome, .pass)
        XCTAssertEqual(gate.algorithmVersion, passing.schemaVersion)
        XCTAssertEqual(gate.evidenceDigest, digest)
        XCTAssertEqual(
            gate.measurements.first { $0.key == .consensusPassCount }?.value,
            3
        )
        XCTAssertEqual(
            gate.measurements.first { $0.key == .wordErrorRate }?.value,
            0
        )

        // Ran-but-did-not-verify is a plain fail.
        var failing = passing
        failing.pass = false
        failing.skipReason = "speech_recognition_inconsistent"
        failing.recognition.consensusStatus = .inconsistent
        let failingGate = failing.languageASRGateResult()
        XCTAssertEqual(failingGate.outcome, .fail)
        XCTAssertEqual(
            failingGate.measurements.first { $0.key == .consensusPassCount }?.value,
            0
        )

        // Recognition that could not run at all maps to unavailable
        // (registry still fails the required gate closed).
        var unavailable = passing
        unavailable.pass = false
        unavailable.skipReason = "speech_recognition_unauthorized"
        unavailable.recognition.consensusStatus = .failed
        XCTAssertEqual(unavailable.languageASRGateResult().outcome, .unavailable)
    }
}
