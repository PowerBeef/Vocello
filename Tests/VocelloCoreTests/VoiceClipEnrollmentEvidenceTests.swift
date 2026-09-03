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

    func testPreparedVoiceMetadataBindsReviewedSourceLanguageAndStableEvidence() throws {
        var review = ReferenceTranscriptionReviewState(initialTranscript: "")
        let generation = review.beginAutomaticTranscription()
        XCTAssertTrue(
            review.acceptAutomaticTranscript(
                "Recognized words",
                generation: generation,
                currentTranscript: ""
            )
        )
        let evidence = VoiceClipTranscriber.EnrollmentEvidence(
            schemaVersion: VoiceClipTranscriber.EnrollmentEvidence.currentSchemaVersion,
            algorithmVersion: VoiceClipTranscriber.EnrollmentEvidence.currentAlgorithmVersion,
            authorizationStatus: .authorized,
            outcome: .success,
            attempts: [attempt(status: .finalResult, digest: String(repeating: "b", count: 64))],
            bestLanguage: "english",
            bestLanguageScore: 0.94,
            bestTranscriptConfidence: 0.88
        )

        let first = try VoiceClipTranscriber.preparedVoiceEnrollmentMetadata(
            referenceLanguage: .english,
            reviewState: review,
            evidence: evidence
        )
        let second = try VoiceClipTranscriber.preparedVoiceEnrollmentMetadata(
            referenceLanguage: .english,
            reviewState: review,
            evidence: evidence
        )

        XCTAssertEqual(first.referenceLanguage, .english)
        XCTAssertEqual(first.transcriptSource, .automatic)
        XCTAssertEqual(first.automaticTranscriptionOutcome, "success")
        XCTAssertEqual(first.transcriptionEvidenceDigest, second.transcriptionEvidenceDigest)
        XCTAssertEqual(first.transcriptionEvidenceDigest?.count, 64)
    }

    func testManualAndAudioOnlyMetadataRemainExplicitWithoutEvidence() throws {
        var manual = ReferenceTranscriptionReviewState(initialTranscript: "")
        manual.userEditedTranscript("Reviewed text")
        let manualMetadata = try VoiceClipTranscriber.preparedVoiceEnrollmentMetadata(
            referenceLanguage: .french,
            reviewState: manual,
            evidence: nil
        )
        XCTAssertEqual(manualMetadata.referenceLanguage, .french)
        XCTAssertEqual(manualMetadata.transcriptSource, .manual)
        XCTAssertNil(manualMetadata.automaticTranscriptionOutcome)
        XCTAssertNil(manualMetadata.transcriptionEvidenceDigest)

        var audioOnly = ReferenceTranscriptionReviewState(initialTranscript: "")
        audioOnly.confirmAudioOnly()
        let audioOnlyMetadata = try VoiceClipTranscriber.preparedVoiceEnrollmentMetadata(
            referenceLanguage: .auto,
            reviewState: audioOnly,
            evidence: nil
        )
        XCTAssertEqual(audioOnlyMetadata.transcriptSource, .audioOnly)
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
