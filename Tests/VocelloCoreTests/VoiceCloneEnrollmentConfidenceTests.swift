import AVFoundation
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

    /// G-01: the recognized words must reach both ends of the audible clip.
    func testCoverageComparesTheRecognizedSpanWithTheAudibleClip() {
        let audible = VoiceClipTranscriber.AudibleSpan(startSeconds: 0.4, endSeconds: 10.4)
        func coverage(_ start: Double?, _ end: Double?,
                      _ span: VoiceClipTranscriber.AudibleSpan?) -> VoiceClipTranscriber.TranscriptCoverage {
            VoiceClipTranscriber.transcriptCoverage(segmentStartSeconds: start, segmentEndSeconds: end, audibleSpan: span)
        }
        // Ten audible seconds allow 1.5 s at each edge.
        XCTAssertEqual(coverage(0.5, 10.2, audible), .whole)
        XCTAssertEqual(coverage(1.8, 9.0, audible), .whole, "Inside the allowance at both edges")
        XCTAssertEqual(coverage(4.5, 10.2, audible), .partial, "The first sentence was not recognized")
        XCTAssertEqual(coverage(0.5, 6.0, audible), .partial, "The reported case: text for 6 s of a 10 s clip")
        XCTAssertEqual(coverage(nil, 10.2, audible), .unknown)
        XCTAssertEqual(coverage(0.5, .nan, audible), .unknown)
        XCTAssertEqual(coverage(0.5, 10.2, nil), .unknown)
        // The audible span is the measure, not the file: five silent seconds
        // after the speech do not move it, so the same words still cover it.
        XCTAssertEqual(coverage(0.5, 10.2, audible), .whole)
        XCTAssertEqual(coverage(0.5, 10.2, VoiceClipTranscriber.AudibleSpan(startSeconds: 0.4, endSeconds: 15.4)), .partial,
                       "Had the silence counted as audible, the same words would fall short")
        // A long clip stops at the 2.5 s cap: 15% of 40 s would allow 6 s.
        let long = VoiceClipTranscriber.AudibleSpan(startSeconds: 0, endSeconds: 40)
        XCTAssertEqual(coverage(2.4, 37.6, long), .whole)
        XCTAssertEqual(coverage(3.0, 40, long), .partial)
        XCTAssertEqual(coverage(0, 37.0, long), .partial)
        // A short clip keeps the one-second floor of the allowance.
        let short = VoiceClipTranscriber.AudibleSpan(startSeconds: 0, endSeconds: 3)
        XCTAssertEqual(coverage(0.9, 2.1, short), .whole)
        XCTAssertEqual(coverage(1.2, 3.0, short), .partial)
    }

    func testTheAudibleSpanIgnoresSilenceAndRoomNoiseAtTheEdges() throws {
        // 20 ms windows: 1 s of faint noise, 2 s of speech, 3 s of faint noise.
        let noise = 1e-7, speech = 1e-2
        let energies = Array(repeating: noise, count: 50) + Array(repeating: speech, count: 100)
            + Array(repeating: noise, count: 150)
        let span = try XCTUnwrap(VoiceClipTranscriber.audibleSpan(
            windowEnergies: energies, windowSeconds: 0.02, clipSeconds: 6))
        XCTAssertEqual(span.startSeconds, 1.0, accuracy: 1e-9)
        XCTAssertEqual(span.endSeconds, 3.0, accuracy: 1e-9)
        XCTAssertNil(VoiceClipTranscriber.audibleSpan(windowEnergies: [0, 0, 0], windowSeconds: 0.02, clipSeconds: 1))
        XCTAssertNil(VoiceClipTranscriber.audibleSpan(windowEnergies: [], windowSeconds: 0.02, clipSeconds: 0))
        // Quiet speech within 30 dB of the loudest window still counts.
        let quietTail = Array(repeating: speech, count: 10) + Array(repeating: speech / 500, count: 10)
        XCTAssertEqual(try XCTUnwrap(VoiceClipTranscriber.audibleSpan(
            windowEnergies: quietTail, windowSeconds: 0.02, clipSeconds: 0.4)).endSeconds, 0.4, accuracy: 1e-9)
    }

    /// Stereo and longer than one read buffer (5.12 s at 24 kHz), so the
    /// window carried across reads and the channel loop both run.
    func testTheAudibleSpanIsMeasuredFromAFile() throws {
        let url = FileManager.default.temporaryDirectory.appendingPathComponent("g01-\(UUID().uuidString).wav")
        defer { try? FileManager.default.removeItem(at: url) }
        let format = try XCTUnwrap(AVAudioFormat(standardFormatWithSampleRate: 24_000, channels: 2))
        let frames = AVAudioFrameCount(24_000 * 14)
        let buffer = try XCTUnwrap(AVAudioPCMBuffer(pcmFormat: format, frameCapacity: frames))
        buffer.frameLength = frames
        guard let channels = unsafe buffer.floatChannelData else { return XCTFail("No channel data") }
        for frame in 0..<Int(frames) {
            // A tone from 3 s to 11.5 s, crossing two read boundaries; the
            // right channel alone carries it, so both channels must be read.
            let audible = frame >= 72_000 && frame < 276_000
            unsafe channels[0][frame] = 0
            unsafe channels[1][frame] = audible ? Float(sin(Double(frame) * 0.2) * 0.3) : 0
        }
        do {
            let file = try AVAudioFile(forWriting: url, settings: format.settings)
            try file.write(from: buffer)
        }
        let span = try XCTUnwrap(VoiceClipTranscriber.audibleSpan(url: url))
        XCTAssertEqual(span.startSeconds, 3.0, accuracy: 0.03)
        XCTAssertEqual(span.endSeconds, 11.5, accuracy: 0.03)

        // A file that cannot be read gives no span, which reads as unknown coverage.
        let missing = FileManager.default.temporaryDirectory.appendingPathComponent("g01-missing-\(UUID().uuidString).wav")
        XCTAssertNil(VoiceClipTranscriber.audibleSpan(url: missing))
        XCTAssertEqual(
            VoiceClipTranscriber.transcriptCoverage(segmentStartSeconds: 0, segmentEndSeconds: 5, audibleSpan: nil),
            .unknown)
    }

    /// The coverage reported is the chosen pass's, whichever pass that is.
    func testTheEnrollmentResultCarriesTheChosenPassesCoverage() async {
        typealias Coverage = VoiceClipTranscriber.TranscriptCoverage
        func result(
            confidences: [Double?],
            scoreLanguage: @escaping @Sendable (String, Qwen3SupportedLanguage) -> Double = { _, _ in 0.95 },
            coverage: @escaping @Sendable (VoiceClipTranscriber.RecognitionPass) -> Coverage
        ) async -> (VoiceClipTranscriber.EnrollmentResult, [Int]) {
            let fixture = EnrollmentRecognitionFixture(confidences: confidences)
            let result = await VoiceClipTranscriber.enrollmentResult(
                candidates: [
                    .init(localeIdentifier: "en-US", language: .english),
                    .init(localeIdentifier: "fr-FR", language: .french),
                ],
                authorization: .authorized,
                scoreLanguage: scoreLanguage,
                coverage: coverage,
                recognize: { @concurrent in await fixture.recognize($0) }
            )
            return (result, await fixture.calls)
        }
        let firstPartial: @Sendable (VoiceClipTranscriber.RecognitionPass) -> Coverage = {
            $0.localeIdentifier == "en-US" ? .partial : .whole
        }
        let secondPartial: @Sendable (VoiceClipTranscriber.RecognitionPass) -> Coverage = {
            $0.localeIdentifier == "fr-FR" ? .partial : .whole
        }

        // A later pass wins on confidence: its coverage is reported.
        let (laterWins, laterCalls) = await result(confidences: [0.4, 0.95], coverage: secondPartial)
        XCTAssertEqual(laterCalls, [0, 1])
        XCTAssertEqual(laterWins.language, .french)
        XCTAssertEqual(laterWins.coverage, .partial)

        // The first pass stays best though a later one ran: the first pass's
        // coverage is reported, not the last pass's.
        let (firstStays, firstCalls) = await result(confidences: [0.7, 0.4], coverage: firstPartial)
        XCTAssertEqual(firstCalls, [0, 1], "0.7 does not end the search, so the second pass runs")
        XCTAssertEqual(firstStays.language, .english)
        XCTAssertEqual(firstStays.coverage, .partial)
        let (firstStaysWhole, _) = await result(confidences: [0.7, 0.4], coverage: secondPartial)
        XCTAssertEqual(firstStaysWhole.coverage, .whole)

        // A pass that fails the language gate is displaced by one that passes
        // it, even at lower confidence: the gated pass's coverage is reported.
        let (gatedWins, _) = await result(
            confidences: [0.9, 0.7],
            scoreLanguage: { text, _ in text.hasPrefix("First") ? 0.1 : 0.95 },
            coverage: secondPartial)
        XCTAssertEqual(gatedWins.language, .french)
        XCTAssertEqual(gatedWins.coverage, .partial)

        // A confident first pass ends the search: nothing after it is judged.
        let (endsEarly, earlyCalls) = await result(confidences: [0.99, 0.99], coverage: firstPartial)
        XCTAssertEqual(earlyCalls, [0])
        XCTAssertEqual(endsEarly.coverage, .partial)
    }

    /// A result with no accepted text carries no judgement to mistake for "whole".
    func testAResultWithoutTextReportsUnknownCoverage() async {
        let fixture = EnrollmentRecognitionFixture(confidences: [0.1, 0.1])
        let result = await VoiceClipTranscriber.enrollmentResult(
            candidates: [.init(localeIdentifier: "en-US", language: .english)],
            authorization: .authorized,
            scoreLanguage: { _, _ in 0.95 },
            coverage: { _ in .whole },
            recognize: { @concurrent in await fixture.recognize($0) }
        )
        XCTAssertNil(result.text)
        XCTAssertEqual(result.coverage, .unknown)
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
            coverage: { _ in .whole },
            recognize: { @concurrent in await fixture.recognize($0) }
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
