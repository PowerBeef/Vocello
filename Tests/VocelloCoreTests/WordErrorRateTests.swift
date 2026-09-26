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

    /// Parity fixtures with `scripts/tests/test_language_metrics.py` (audit #84): the run follows
    /// the tie-broken alignment the counts come from.
    func testLongestDeletionRunFollowsTheAlignment() {
        let skipped = VoiceClipTranscriber.wordErrorMetrics(
            reference: "The quiet garden is open today",
            hypothesis: "The is open today"
        )
        XCTAssertEqual(skipped.deletions, 2)
        XCTAssertEqual(skipped.longestDeletionRun, 2)

        let scattered = VoiceClipTranscriber.wordErrorMetrics(
            reference: "a b c d e",
            hypothesis: "a c e"
        )
        XCTAssertEqual(scattered.deletions, 2)
        XCTAssertEqual(scattered.longestDeletionRun, 1)

        let merged = VoiceClipTranscriber.wordErrorMetrics(
            reference: "vor Mittag kommt er",
            hypothesis: "Vormittag kommt er"
        )
        XCTAssertEqual(merged.substitutions, 1)
        XCTAssertEqual(merged.deletions, 1)
        XCTAssertEqual(merged.longestDeletionRun, 1)

        let substituted = VoiceClipTranscriber.characterErrorMetrics(
            reference: "kitten",
            hypothesis: "sitting"
        )
        XCTAssertEqual(substituted.longestDeletionRun, 0)
        XCTAssertEqual(
            VoiceClipTranscriber.wordErrorMetrics(reference: "a b c", hypothesis: "").longestDeletionRun,
            3
        )
    }

    /// WER v2 parity fixtures with `scripts/tests/test_language_metrics.py` (audit #43): a
    /// merge, split or moved boundary of up to four words per side costs nothing; any other
    /// edit keeps its plain cost.
    func testSegmentationAwareWordMetricsCreditOnlyBoundaryEdits() {
        let cases: [(String, String, Int, Int, Double)] = [
            ("Er kommt vor Mittag an und bleibt bis zum Abend",
             "Er kommt Vormittag an und bleibt biszum Abend", 0, 4, 0),
            ("Das Donaudampfschiff fährt", "Das Donau dampf schiff fährt", 0, 3, 0),
            ("ab c", "a bc", 0, 2, 0),
            ("the quiet garden", "the quite garden", 1, 0, 1.0 / 3.0),
            ("vor Mittag kommt er", "Vormittag kam er", 1, 2, 0.25),
            ("a b c d e", "abcde", 5, 0, 1),
            ("a b c d", "abcd", 0, 4, 0),
            ("", "x", 1, 0, 1),
            ("x", "", 1, 0, 1)
        ]
        for (reference, hypothesis, distance, credited, rate) in cases {
            let metrics = VoiceClipTranscriber.segmentationAwareWordMetrics(
                reference: reference,
                hypothesis: hypothesis
            )
            XCTAssertEqual(metrics.editDistance, distance, "\(reference) / \(hypothesis)")
            XCTAssertEqual(metrics.wordBoundaryOnlyEdits, credited, "\(reference) / \(hypothesis)")
            XCTAssertEqual(metrics.errorRate, rate, accuracy: 1e-12, "\(reference) / \(hypothesis)")
        }
        XCTAssertEqual(VoiceClipTranscriber.wordBoundarySpanLimit, 4)
    }

    func testVerifierGatesTheSegmentationAwareRateAndKeepsTheV1Rate() throws {
        let script = "Er kommt vor Mittag an und bleibt bis zum Abend"
        let transcript = "Er kommt Vormittag an und bleibt biszum Abend"
        let passes = (1 ... 3).map { pass(index: $0, transcript: transcript, localeIdentifier: "de-DE") }
        let result = GenerationOutputVerifier.evaluate(
            recognition: evidence(
                authorization: .authorized,
                consensus: .consistent,
                repetitions: passes,
                transcript: transcript,
                expectedLanguage: .german
            ),
            expectedScript: script,
            expectedLanguage: .german
        )
        XCTAssertEqual(result.accuracyMetricVersion, "normalization-v2-edit-rate-v3")
        XCTAssertEqual(try XCTUnwrap(result.wordErrorRate), 0.4, accuracy: 1e-12)
        XCTAssertEqual(try XCTUnwrap(result.segmentationAwareWordErrorRate), 0, accuracy: 1e-12)
        XCTAssertEqual(result.wordBoundaryOnlyEdits, 4)
        XCTAssertEqual(try XCTUnwrap(result.accuracyValue), 0, accuracy: 1e-12)
        XCTAssertEqual(result.accuracyPass, true)
    }

    /// Normalization v2 parity (AQ-02 P2a): every case of the fixtures shared with
    /// `scripts/tests/test_language_metrics.py` scores to the same tokens, character units and
    /// edit counts here. P2b cases pin today's scores as well; their `expectedAfterP2b` belongs
    /// to the package steps P2b adds.
    func testNormalizationV2ParityFixtures() throws {
        let repositoryRoot = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .deletingLastPathComponent()
        let data = try Data(contentsOf: repositoryRoot.appendingPathComponent(
            "scripts/tests/fixtures/language_normalization_v2.json"
        ))
        let fixtures = try JSONDecoder().decode(NormalizationFixtures.self, from: data)
        XCTAssertEqual(fixtures.normalizationVersion, VoiceClipTranscriber.textNormalizationVersion)
        XCTAssertEqual(
            fixtures.accuracyMetricVersion,
            GenerationOutputVerifier.Result.currentAccuracyMetricVersion
        )
        let covered = Set(fixtures.cases.filter { $0.phase == "P2a" }.map(\.language))
        XCTAssertTrue(Set(Qwen3SupportedLanguage.selectableCases.map(\.rawValue)).isSubset(of: covered))

        for fixture in fixtures.cases {
            let language = try XCTUnwrap(Qwen3SupportedLanguage(rawValue: fixture.language), fixture.id)
            let expected = fixture.expected
            XCTAssertEqual(
                VoiceClipTranscriber.normalizedWordTokens(fixture.reference, language: language),
                expected.referenceTokens,
                fixture.id
            )
            XCTAssertEqual(
                VoiceClipTranscriber.normalizedWordTokens(fixture.hypothesis, language: language),
                expected.hypothesisTokens,
                fixture.id
            )
            XCTAssertEqual(
                scalarString(VoiceClipTranscriber.normalizedCharacterUnits(fixture.reference, language: language)),
                expected.referenceCharacters,
                fixture.id
            )
            XCTAssertEqual(
                scalarString(VoiceClipTranscriber.normalizedCharacterUnits(fixture.hypothesis, language: language)),
                expected.hypothesisCharacters,
                fixture.id
            )
            let word = VoiceClipTranscriber.wordErrorMetrics(
                reference: fixture.reference,
                hypothesis: fixture.hypothesis,
                expectedLanguage: language
            )
            assertCounts(word, expected.word, fixture.id + " word")
            let aware = VoiceClipTranscriber.segmentationAwareWordMetrics(
                reference: fixture.reference,
                hypothesis: fixture.hypothesis,
                expectedLanguage: language
            )
            XCTAssertEqual(aware.editDistance, expected.segmentationAwareEditDistance, fixture.id)
            XCTAssertEqual(aware.wordBoundaryOnlyEdits, expected.wordBoundaryOnlyEdits, fixture.id)
            let character = VoiceClipTranscriber.characterErrorMetrics(
                reference: fixture.reference,
                hypothesis: fixture.hypothesis,
                expectedLanguage: language
            )
            assertCounts(character, expected.character, fixture.id + " character")
            let metric = GenerationOutputVerifier.accuracyMetric(for: language)
            XCTAssertEqual(metric.rawValue, expected.primaryMetric, fixture.id)
            let primaryErrors = metric == .characterErrorRate ? character.editDistance : aware.editDistance
            XCTAssertEqual(primaryErrors, expected.primaryErrors, fixture.id)
        }
    }

    /// AQ-F21: Korean gates its space-free syllable rate, so eojeol spacing costs nothing and
    /// Hangul is never split into NFKD jamo; the word rate stays published beside it.
    func testKoreanGatesItsSyllableCharacterRate() throws {
        let script = "기차는 조용한 역을 제시간에 떠났습니다"
        let transcript = "기차는 조용한역을 제 시간에 떠났습니다"
        let passes = (1 ... 3).map { pass(index: $0, transcript: transcript, localeIdentifier: "ko-KR") }
        let result = GenerationOutputVerifier.evaluate(
            recognition: evidence(
                authorization: .authorized,
                consensus: .consistent,
                repetitions: passes,
                transcript: transcript,
                expectedLanguage: .korean
            ),
            expectedScript: script,
            expectedLanguage: .korean
        )
        XCTAssertNil(result.skipReason)
        XCTAssertEqual(result.accuracyMetric, .characterErrorRate)
        XCTAssertEqual(result.referenceCharacterCount, 17)
        XCTAssertEqual(try XCTUnwrap(result.characterErrorRate), 0, accuracy: 1e-12)
        XCTAssertEqual(try XCTUnwrap(result.wordErrorRate), 0.6, accuracy: 1e-12)
        XCTAssertEqual(try XCTUnwrap(result.accuracyValue), 0, accuracy: 1e-12)
        XCTAssertEqual(result.accuracyPass, true)
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
        XCTAssertEqual(deletion.longestDeletionRun, 3)

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
        XCTAssertEqual(result.accuracyMetricVersion, "normalization-v2-edit-rate-v3")
        XCTAssertEqual(result.accuracyMetric, .wordErrorRate)
        XCTAssertEqual(result.accuracyThreshold, 0.30, accuracy: 0.001)
        XCTAssertEqual(try XCTUnwrap(result.accuracyValue), 0.25, accuracy: 0.001)
        XCTAssertEqual(try XCTUnwrap(result.segmentationAwareWordErrorRate), 0.25, accuracy: 0.001)
        XCTAssertEqual(result.wordBoundaryOnlyEdits, 0)
        XCTAssertEqual(result.longestDeletionRun, 0)
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
            VoiceClipTranscriber.hasAudioEdgeCoverage(
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
            VoiceClipTranscriber.hasAudioEdgeCoverage(
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
            VoiceClipTranscriber.hasAudioEdgeCoverage(
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

    func testVerifierReportsTheDeletionRunAndDecodesEvidenceWithoutIt() throws {
        let transcript = "The is open today"
        let recognition = evidence(
            authorization: .authorized,
            consensus: .consistent,
            repetitions: (1 ... 3).map { pass(index: $0, transcript: transcript) },
            transcript: transcript
        )
        let result = GenerationOutputVerifier.evaluate(
            recognition: recognition,
            expectedScript: "The quiet garden is open today",
            expectedLanguage: .english,
            maxWordErrorRate: 0.5
        )
        // Warn-only: the skipped phrase is reported, the verdict is the edit rate's alone.
        XCTAssertEqual(result.longestDeletionRun, 2)
        XCTAssertEqual(result.accuracyPass, true)

        var object = try XCTUnwrap(
            JSONSerialization.jsonObject(with: JSONEncoder().encode(result)) as? [String: Any]
        )
        object.removeValue(forKey: "longestDeletionRun")
        let earlier = try JSONDecoder().decode(
            GenerationOutputVerifier.Result.self,
            from: JSONSerialization.data(withJSONObject: object)
        )
        XCTAssertNil(earlier.longestDeletionRun)
        XCTAssertEqual(earlier.deletions, 2)
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

    private func scalarString(_ scalars: [Unicode.Scalar]) -> String {
        var view = String.UnicodeScalarView()
        view.append(contentsOf: scalars)
        return String(view)
    }

    private func assertCounts(
        _ metrics: VoiceClipTranscriber.EditMetrics,
        _ expected: NormalizationFixtures.EditCounts,
        _ message: String,
        file: StaticString = #filePath,
        line: UInt = #line
    ) {
        XCTAssertEqual(metrics.substitutions, expected.substitutions, message, file: file, line: line)
        XCTAssertEqual(metrics.insertions, expected.insertions, message, file: file, line: line)
        XCTAssertEqual(metrics.deletions, expected.deletions, message, file: file, line: line)
        XCTAssertEqual(metrics.longestDeletionRun, expected.longestDeletionRun, message, file: file, line: line)
    }

    /// `scripts/tests/fixtures/language_normalization_v2.json`; Python-only diagnostics and the
    /// P2b expectations are ignored here.
    private struct NormalizationFixtures: Decodable {
        struct EditCounts: Decodable {
            var substitutions: Int
            var insertions: Int
            var deletions: Int
            var longestDeletionRun: Int
        }

        struct Expected: Decodable {
            var referenceTokens: [String]
            var hypothesisTokens: [String]
            var referenceCharacters: String
            var hypothesisCharacters: String
            var word: EditCounts
            var segmentationAwareEditDistance: Int
            var wordBoundaryOnlyEdits: Int
            var character: EditCounts
            var primaryMetric: String
            var primaryErrors: Int
        }

        struct FixtureCase: Decodable {
            var id: String
            var language: String
            var reference: String
            var hypothesis: String
            var phase: String
            var expected: Expected
        }

        var normalizationVersion: String
        var accuracyMetricVersion: String
        var cases: [FixtureCase]
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
        XCTAssertEqual(gate.algorithmVersion, 6)
        XCTAssertEqual(gate.evidenceDigest, digest)
        XCTAssertEqual(
            gate.measurements.first { $0.key == .consensusPassCount }?.value,
            3
        )
        XCTAssertEqual(
            gate.measurements.first { $0.key == .wordErrorRate }?.value,
            0
        )

        // Since gate v5 the gate reports the rate its outcome reads: a word-boundary merge the
        // v1 rate charges (0.4) is not what a passing WER v2 gate measured.
        var merged = passing
        merged.wordErrorRate = 0.4
        merged.accuracyValue = 0.05
        let mergedGate = merged.languageASRGateResult()
        XCTAssertEqual(mergedGate.outcome, .pass)
        XCTAssertEqual(
            mergedGate.measurements.first { $0.key == .wordErrorRate }?.value,
            0.05
        )
        // Chinese, Japanese and Korean gate on the character rate, under its own key.
        var characters = passing
        characters.accuracyMetric = .characterErrorRate
        characters.accuracyValue = 0.08
        let characterGate = characters.languageASRGateResult()
        XCTAssertEqual(
            characterGate.measurements.first { $0.key == .characterErrorRate }?.value,
            0.08
        )
        XCTAssertNil(characterGate.measurements.first { $0.key == .wordErrorRate })

        // Inconsistent recognition is unavailable evidence, not a measured speech defect.
        var failing = passing
        failing.pass = false
        failing.skipReason = "speech_recognition_inconsistent"
        failing.recognition.consensusStatus = .inconsistent
        let failingGate = failing.languageASRGateResult()
        XCTAssertEqual(failingGate.outcome, .unavailable)
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

    func testUnavailableASREvidenceStaysBlockingWithoutClaimingMeasuredFailure() throws {
        let script = "Hello world"
        let recognition = evidence(authorization: .authorized, consensus: .consistent,
            repetitions: (1 ... 3).map { pass(index: $0, transcript: script) }, transcript: script)
        let original = GenerationOutputVerifier.evaluate(recognition: recognition,
            expectedScript: script, expectedLanguage: .english)
        let policy = QualityReviewPolicy(depth: .standard, requiresLanguageASR: true)
        for reason in [
            "speech_recognition_inconsistent", "speech_recognition_incomplete",
            "speech_recognition_incomplete_temporal_coverage", "speech_recognition_evidence_invalid",
            "speech_recognition_timed_out", "speech_recognition_error", "transcription_failed",
            "accuracy_threshold_invalid", "source_audio_duration_invalid", "future_unknown_reason",
        ] {
            var result = original
            result.pass = false
            result.skipReason = reason
            let gate = result.languageASRGateResult()
            XCTAssertEqual(gate.outcome, .unavailable, reason)
            let gates = QualityGateRegistry.requiredGates(for: policy).map { id in
                id == .languageASR ? gate : GenerationQualityGateResult(
                    gate: id, outcome: .pass, algorithmVersion: 1)
            }
            let verdict = try QualityGateRegistry.evaluate(GenerationQualityReport(
                generationID: UUID(), policy: policy, results: gates))
            XCTAssertEqual(verdict.outcome, .fail, reason)
            XCTAssertEqual(verdict.issues, ["quality_gate_unavailable.language_asr"], reason)
        }
        // Actual full-consensus text errors still fail; no threshold or transcript is changed.
        let measured = GenerationOutputVerifier.evaluate(recognition: recognition,
            expectedScript: "The train arrived late at the station", expectedLanguage: .english)
        XCTAssertNil(measured.skipReason)
        XCTAssertEqual(measured.accuracyPass, false)
        XCTAssertEqual(measured.languageASRGateResult().outcome, .fail)
    }
}
