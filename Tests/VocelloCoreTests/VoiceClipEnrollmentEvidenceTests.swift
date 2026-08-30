import Foundation
import QwenVoiceCore
import XCTest

final class VoiceClipEnrollmentEvidenceTests: XCTestCase {
    func testEnrollmentEvidenceContainsNoTranscriptOrPath() throws {
        let evidence = VoiceClipTranscriber.EnrollmentEvidence(
            schemaVersion: VoiceClipTranscriber.EnrollmentEvidence.currentSchemaVersion,
            algorithmVersion: VoiceClipTranscriber.EnrollmentEvidence.currentAlgorithmVersion,
            authorizationStatus: .authorized,
            outcome: .success,
            attempts: [attempt(status: .finalResult, digest: String(repeating: "a", count: 64))],
            bestLanguage: "french",
            bestLanguageScore: 0.91,
            bestTranscriptConfidence: 0.82
        )

        let encoded = try XCTUnwrap(String(data: JSONEncoder().encode(evidence), encoding: .utf8))
        XCTAssertFalse(encoded.contains("private transcript"))
        XCTAssertFalse(encoded.contains("/Users/"))
        XCTAssertTrue(encoded.contains(String(repeating: "a", count: 64)))
    }

    func testEnrollmentFailureClassificationIsTyped() {
        XCTAssertEqual(
            VoiceClipTranscriber.enrollmentFailureOutcome([
                attempt(status: .recognizerUnavailable),
                attempt(status: .onDeviceRecognitionUnsupported),
            ]),
            .onDeviceRecognitionUnsupported
        )
        XCTAssertEqual(
            VoiceClipTranscriber.enrollmentFailureOutcome([
                attempt(status: .emptyTranscript),
            ]),
            .emptyResult
        )
        XCTAssertEqual(
            VoiceClipTranscriber.enrollmentFailureOutcome([
                attempt(status: .recognitionError),
                attempt(status: .timedOut),
            ]),
            .recognitionTimedOut
        )
    }

    private func attempt(
        status: VoiceClipTranscriber.RecognitionFinalStatus,
        digest: String? = nil
    ) -> VoiceClipTranscriber.EnrollmentLocaleAttempt {
        VoiceClipTranscriber.EnrollmentLocaleAttempt(
            order: 1,
            localeIdentifier: "fr_FR",
            language: "french",
            recognizerAvailable: status != .recognizerUnavailable,
            supportsOnDeviceRecognition: status != .onDeviceRecognitionUnsupported,
            status: status,
            transcriptDigest: digest,
            transcriptCharacters: digest == nil ? 0 : 12,
            languageScore: digest == nil ? nil : 0.91,
            averageConfidence: digest == nil ? nil : 0.82
        )
    }
}
