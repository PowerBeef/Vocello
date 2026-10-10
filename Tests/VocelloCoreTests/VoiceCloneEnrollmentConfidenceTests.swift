import Foundation
import QwenVoiceCore
import XCTest

/// Locale selection runs over finalized, injected passes. Awaiting the result
/// joins every selected pass; the actor records call order without scheduler
/// assumptions, Speech authorization, audio assets or OS language-model scores.
@MainActor
final class VoiceCloneEnrollmentConfidenceTests: XCTestCase {
    func testZeroConfidenceFirstLocaleDoesNotHideALaterConfidentLocale() async {
        let fixture = EnrollmentRecognitionFixture(confidences: [0, 0.91])
        let result = await select(fixture)
        let calls = await fixture.calls

        XCTAssertEqual(calls, [0, 1], "Zero confidence must not end locale search")
        XCTAssertEqual(result.evidence.outcome, .success)
        XCTAssertEqual(result.language, .french)
        XCTAssertEqual(result.text, "Second locale words.")
        XCTAssertEqual(result.evidence.attempts.map(\.averageConfidence), [0, 0.91])
        XCTAssertEqual(result.evidence.bestTranscriptConfidence, 0.91)
        XCTAssertEqual(result.evidence.algorithmVersion, "apple-speech-enrollment-v2")
    }

    func testAllZeroConfidencePassesProduceNoAutomaticTranscript() async {
        let fixture = EnrollmentRecognitionFixture(confidences: [0, 0])
        let result = await select(fixture)
        let calls = await fixture.calls

        XCTAssertEqual(calls, [0, 1])
        XCTAssertEqual(result.evidence.outcome, .lowConfidence)
        XCTAssertEqual(result.evidence.bestTranscriptConfidence, 0)
        XCTAssertNil(result.text)
        XCTAssertEqual(result.language, .auto)
    }

    func testConfidentSecondLocaleOutranksFluentFirstLocale() async {
        let fixture = EnrollmentRecognitionFixture(confidences: [0.42, 0.91])
        let result = await select(fixture)
        let calls = await fixture.calls

        XCTAssertEqual(calls, [0, 1])
        XCTAssertEqual(result.language, .french)
        XCTAssertEqual(result.text, "Second locale words.")
    }

    func testHighLanguageAndRecognitionConfidenceEndsSearch() async {
        let fixture = EnrollmentRecognitionFixture(confidences: [0.93, 0.99])
        let result = await select(fixture)
        let calls = await fixture.calls

        XCTAssertEqual(calls, [0], "A qualified first pass needs no second recognition")
        XCTAssertEqual(result.evidence.outcome, .success)
        XCTAssertEqual(result.language, .english)
        XCTAssertEqual(result.text, "First locale words.")
    }

    func testLanguageGateRejectsAConfidentPassInTheWrongLanguage() async {
        let fixture = EnrollmentRecognitionFixture(confidences: [0.6, 0.99])
        let result = await select(fixture, scoreLanguage: { _, language in
            language == .english ? 0.95 : 0.1
        })
        let calls = await fixture.calls

        XCTAssertEqual(calls, [0, 1])
        XCTAssertEqual(result.evidence.outcome, .success)
        XCTAssertEqual(result.language, .english)
        XCTAssertEqual(result.evidence.bestTranscriptConfidence, 0.6)
    }

    func testHighRecognitionConfidenceCannotBypassTheLanguageFloor() async {
        let fixture = EnrollmentRecognitionFixture(confidences: [0.95, 0.99])
        let result = await select(fixture, scoreLanguage: { _, _ in 0.1 })

        XCTAssertEqual(result.evidence.outcome, .lowConfidence)
        XCTAssertNil(result.text)
        XCTAssertEqual(result.language, .auto)
    }

    func testWinnerBelowRecognitionConfidenceFloorIsNotUsed() async {
        let fixture = EnrollmentRecognitionFixture(confidences: [0.12, 0.2])
        let result = await select(fixture)
        let calls = await fixture.calls

        XCTAssertEqual(calls, [0, 1])
        XCTAssertEqual(result.evidence.outcome, .lowConfidence)
        XCTAssertEqual(result.evidence.bestTranscriptConfidence, 0.2)
        XCTAssertNil(result.text)
    }

    func testEqualRecognitionConfidenceUsesLanguageScoreToBreakTheTie() async {
        let fixture = EnrollmentRecognitionFixture(confidences: [0.6, 0.6])
        let result = await select(fixture, scoreLanguage: { _, language in
            language == .english ? 0.7 : 0.95
        })

        XCTAssertEqual(result.evidence.outcome, .success)
        XCTAssertEqual(result.language, .french)
    }

    func testTrulyMissingConfidenceKeepsBestEffortLanguageFallback() async {
        let fixture = EnrollmentRecognitionFixture(confidences: [nil, 0.9])
        let result = await select(fixture)
        let calls = await fixture.calls

        XCTAssertEqual(calls, [0], "Only absence retains the historical fallback")
        XCTAssertEqual(result.evidence.outcome, .success)
        XCTAssertEqual(result.language, .english)
        XCTAssertNil(result.evidence.bestTranscriptConfidence)
    }

    func testInvalidReportedConfidenceDoesNotBecomeTheMissingSignalFallback() async throws {
        for invalid in [Double.nan, .infinity, -0.1, 1.1] {
            let fixture = EnrollmentRecognitionFixture(confidences: [invalid, 0.91])
            let result = await select(fixture)
            let calls = await fixture.calls

            XCTAssertEqual(calls, [0, 1])
            XCTAssertEqual(result.evidence.outcome, .success)
            XCTAssertEqual(result.language, .french)
            XCTAssertEqual(result.evidence.attempts.first?.averageConfidence, 0)
            XCTAssertNoThrow(try JSONEncoder().encode(result.evidence))
        }
        XCTAssertEqual(VoiceClipTranscriber.reportedConfidence(0), 0)
        XCTAssertNil(VoiceClipTranscriber.reportedConfidence(nil))
    }

    func testRecognitionFailureCannotWinWithPlausibleTextAndConfidence() async {
        let fixture = EnrollmentRecognitionFixture(
            confidences: [0.99, 0.91], firstStatus: .recognitionError
        )
        let result = await select(fixture)
        let calls = await fixture.calls

        XCTAssertEqual(calls, [0, 1])
        XCTAssertEqual(result.evidence.outcome, .success)
        XCTAssertEqual(result.language, .french)
        XCTAssertEqual(result.evidence.attempts.first?.status, .recognitionError)
    }

    private func select(
        _ fixture: EnrollmentRecognitionFixture,
        scoreLanguage: @Sendable (String, Qwen3SupportedLanguage) -> Double = { _, _ in 0.95 }
    ) async -> VoiceClipTranscriber.EnrollmentResult {
        await VoiceClipTranscriber.enrollmentResult(
            candidates: [
                .init(localeIdentifier: "en-US", language: .english),
                .init(localeIdentifier: "fr-FR", language: .french),
            ],
            authorization: .authorized,
            scoreLanguage: scoreLanguage,
            recognize: { await fixture.recognize($0) }
        )
    }
}

private actor EnrollmentRecognitionFixture {
    let confidences: [Double?]
    let firstStatus: VoiceClipTranscriber.RecognitionFinalStatus
    private(set) var calls: [Int] = []

    init(
        confidences: [Double?],
        firstStatus: VoiceClipTranscriber.RecognitionFinalStatus = .finalResult
    ) {
        self.confidences = confidences
        self.firstStatus = firstStatus
    }

    func recognize(_ index: Int) -> VoiceClipTranscriber.RecognitionPass {
        calls.append(index)
        return VoiceClipTranscriber.RecognitionPass(
            passIndex: index + 1,
            localeIdentifier: index == 0 ? "en-US" : "fr-FR",
            authorizationStatus: .authorized,
            recognizerAvailable: true,
            supportsOnDeviceRecognition: true,
            finalResultStatus: index == 0 ? firstStatus : .finalResult,
            recognitionDurationSeconds: 0.5,
            transcript: index == 0 ? "First locale words." : "Second locale words.",
            segmentCount: 3,
            segmentStartSeconds: 0,
            segmentEndSeconds: 1,
            timingCoverageSeconds: 1,
            averageConfidence: confidences[index],
            minimumConfidence: confidences[index],
            errorDomain: nil,
            errorCode: nil
        )
    }
}
