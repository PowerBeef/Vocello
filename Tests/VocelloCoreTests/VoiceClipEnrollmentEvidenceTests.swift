import Foundation
import QwenVoiceCore
import XCTest

final class VoiceClipEnrollmentEvidenceTests: XCTestCase {
    @concurrent func testStableRecognitionRejectsSamePathContentReplacement() async throws {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: directory) }
        let source = directory.appendingPathComponent("voice.wav")
        try Data("original bytes".utf8).write(to: source)
        let fixture = Self.recognitionFixture()
        let result = await VoiceClipTranscriber.stableEnrollmentResult(url: source) { @concurrent snapshot in
            XCTAssertEqual(try? Data(contentsOf: snapshot), Data("original bytes".utf8))
            try? Data("replacement bytes".utf8).write(to: source)
            return fixture
        }
        XCTAssertNil(result, "A completed recognition cannot describe replaced reference contents")
    }

    @concurrent func testStableRecognitionUsesPrivateSnapshotAcrossAtoBtoAReplacementAndCleansIt() async throws {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: directory) }
        let source = directory.appendingPathComponent("voice.wav")
        let original = Data("original bytes".utf8)
        try original.write(to: source)
        let fixture = Self.recognitionFixture()
        let result = await VoiceClipTranscriber.stableEnrollmentResult(url: source) { @concurrent snapshot in
            XCTAssertNotEqual(snapshot, source)
            try? Data("temporary replacement".utf8).write(to: source)
            XCTAssertEqual(try? Data(contentsOf: snapshot), original)
            try? original.write(to: source)
            return fixture
        }
        XCTAssertEqual(result, fixture)
        XCTAssertEqual(try Data(contentsOf: source), original)
        // A second fake returns its snapshot URL in memory; the service's defer
        // must delete that private copy before delivering the result.
        let cleanupResult = await VoiceClipTranscriber.stableEnrollmentResult(url: source) { @concurrent snapshot in
            var response = fixture
            response.text = snapshot.path
            return response
        }
        let removedPath = try XCTUnwrap(cleanupResult?.text)
        XCTAssertFalse(FileManager.default.fileExists(atPath: removedPath))
    }

    @concurrent func testMissingReferenceCannotInvokeRecognition() async {
        let result = await VoiceClipTranscriber.stableEnrollmentResult(
            url: FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        ) { @concurrent _ in
            XCTFail("Missing audio must not request speech recognition")
            return VoiceClipEnrollmentEvidenceTests.recognitionFixture()
        }
        XCTAssertNil(result)
    }

    private static func recognitionFixture() -> VoiceClipTranscriber.EnrollmentResult {
        VoiceClipTranscriber.EnrollmentResult(text: "Bonjour", language: .french, evidence: .init(
            schemaVersion: VoiceClipTranscriber.EnrollmentEvidence.currentSchemaVersion,
            algorithmVersion: VoiceClipTranscriber.EnrollmentEvidence.currentAlgorithmVersion,
            authorizationStatus: .authorized, outcome: .success, attempts: [], bestLanguage: "french",
            bestLanguageScore: 1, bestTranscriptConfidence: 1
        ))
    }

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

    /// A8-02: a generated Design take saved as a voice goes through the shared
    /// builder like every other enrollment. Its script is an existing transcript
    /// (no new recognition evidence, so its source is unknown, as on the Mac),
    /// an edit is manual, an emptied one needs the audio-only confirmation, and
    /// the design source survives for the iOS export provenance.
    func testAGeneratedDesignTakeKeepsItsReviewProvenanceAndItsSourceMode() throws {
        let script = "A quiet morning by the harbor."
        var review = ReferenceTranscriptionReviewState(initialTranscript: script, readySource: .existing)
        XCTAssertTrue(review.allowsSave(transcript: script))
        let untouched = try VoiceClipTranscriber.preparedVoiceEnrollmentMetadata(
            referenceLanguage: .english,
            reviewState: review,
            evidence: nil,
            generatedSourceMode: GenerationMode.design.rawValue
        )
        XCTAssertEqual(untouched.transcriptSource, .unknown)
        XCTAssertEqual(untouched.generatedSourceMode, "design")
        XCTAssertEqual(untouched.referenceLanguage, .english)

        review.userEditedTranscript("")
        XCTAssertFalse(review.allowsSave(transcript: ""), "An emptied transcript is not saved silently")
        XCTAssertTrue(review.offersAudioOnlyConfirmation)
        review.confirmAudioOnly()
        XCTAssertTrue(review.allowsSave(transcript: ""))
        let audioOnly = try VoiceClipTranscriber.preparedVoiceEnrollmentMetadata(
            referenceLanguage: .auto,
            reviewState: review,
            evidence: nil,
            generatedSourceMode: GenerationMode.design.rawValue
        )
        XCTAssertEqual(audioOnly.transcriptSource, .audioOnly)
        XCTAssertEqual(audioOnly.generatedSourceMode, "design")

        let personal = try VoiceClipTranscriber.preparedVoiceEnrollmentMetadata(
            referenceLanguage: .english,
            reviewState: ReferenceTranscriptionReviewState(initialTranscript: script),
            evidence: nil
        )
        XCTAssertNil(personal.generatedSourceMode, "A recorded or imported reference has no generated source")
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
