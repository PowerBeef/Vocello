import Foundation
import XCTest

final class IOSReferenceTranscriptionReviewStateTests: XCTestCase {
    func testSupportedImportTypesShareOnePolicy() throws {
        XCTAssertEqual(
            IOSReferenceAudioImportPolicy.supportedExtensions,
            ["wav", "mp3", "aiff", "m4a"]
        )
        XCTAssertEqual(IOSReferenceAudioImportPolicy.allowedContentTypes.count, 4)
        XCTAssertThrowsError(
            try IOSReferenceAudioImportPolicy.validatedSourceURL(
                URL(fileURLWithPath: "/tmp/reference.txt")
            )
        )
    }

    func testValidatedImportPreservesOriginalURL() throws {
        let source = URL(fileURLWithPath: "/private/tmp/Reference Voice.WAV")
        let validated = try IOSReferenceAudioImportPolicy.validatedSourceURL(source)
        XCTAssertEqual(validated, source)
        XCTAssertEqual(validated.absoluteString, source.absoluteString)
    }

    func testPickerCancellationAndEmptySelectionProduceNoImport() throws {
        let cancellation: Result<[URL], Error> = .failure(CocoaError(.userCancelled))
        XCTAssertNil(try IOSReferenceAudioImportPolicy.selectedSourceURL(from: cancellation))
        XCTAssertNil(try IOSReferenceAudioImportPolicy.selectedSourceURL(from: .success([])))
    }

    func testPickerFailureRemainsTyped() {
        let failure: Result<[URL], Error> = .failure(
            IOSReferenceAudioImportPolicy.ValidationError.unsupportedType
        )
        XCTAssertThrowsError(try IOSReferenceAudioImportPolicy.selectedSourceURL(from: failure)) { error in
            XCTAssertEqual(
                error as? IOSReferenceAudioImportPolicy.ValidationError,
                .unsupportedType
            )
        }
    }

    func testSidecarTranscriptIsImmediatelyReady() {
        let state = ReferenceTranscriptionReviewState(initialTranscript: "Existing transcript")
        XCTAssertEqual(state.phase, .ready(.sidecar))
        XCTAssertTrue(state.allowsSave(transcript: "Existing transcript"))
    }

    func testSaveIsBlockedWhileTranscriptionIsUnresolved() {
        var state = ReferenceTranscriptionReviewState(initialTranscript: "")
        XCTAssertEqual(state.phase, .awaitingAudio)
        XCTAssertFalse(state.allowsSave(transcript: ""))

        _ = state.beginAutomaticTranscription()
        XCTAssertEqual(state.phase, .transcribing)
        XCTAssertFalse(state.allowsSave(transcript: ""))
    }

    func testClearingAudioReturnsToAwaitingStateAndInvalidatesOldResult() {
        var state = ReferenceTranscriptionReviewState(initialTranscript: "")
        let staleGeneration = state.beginAutomaticTranscription()
        state.awaitAudio()

        XCTAssertEqual(state.phase, .awaitingAudio)
        XCTAssertFalse(
            state.acceptAutomaticTranscript(
                "Stale words",
                generation: staleGeneration,
                currentTranscript: ""
            )
        )
    }

    func testAutomaticTranscriptBecomesEditableReadyState() {
        var state = ReferenceTranscriptionReviewState(initialTranscript: "")
        let generation = state.beginAutomaticTranscription()
        XCTAssertTrue(
            state.acceptAutomaticTranscript(
                "Recognized words",
                generation: generation,
                currentTranscript: ""
            )
        )
        XCTAssertEqual(state.phase, .ready(.automatic))
        XCTAssertTrue(state.allowsSave(transcript: "Recognized words"))
    }

    func testManualEditWinsOverDelayedRecognition() {
        var state = ReferenceTranscriptionReviewState(initialTranscript: "")
        let staleGeneration = state.beginAutomaticTranscription()
        state.userEditedTranscript("My corrected words")

        XCTAssertFalse(
            state.acceptAutomaticTranscript(
                "Delayed automatic words",
                generation: staleGeneration,
                currentTranscript: "My corrected words"
            )
        )
        XCTAssertEqual(state.phase, .ready(.manual))
        XCTAssertTrue(state.allowsSave(transcript: "My corrected words"))
    }

    func testCancelledAndStaleResultsCannotResolveNewReview() {
        var state = ReferenceTranscriptionReviewState(initialTranscript: "")
        let staleGeneration = state.beginAutomaticTranscription()
        state.invalidate()

        XCTAssertFalse(
            state.acceptAutomaticTranscript(
                "Stale words",
                generation: staleGeneration,
                currentTranscript: ""
            )
        )
        XCTAssertEqual(state.phase, .unavailable(.cancelled))
    }

    func testUnavailableRecognitionRequiresTextOrExplicitAudioOnly() {
        var state = ReferenceTranscriptionReviewState(initialTranscript: "")
        let generation = state.beginAutomaticTranscription()
        state.finishWithoutTranscript(
            reason: .permissionDenied,
            generation: generation,
            currentTranscript: ""
        )

        XCTAssertTrue(state.offersAudioOnlyConfirmation)
        XCTAssertFalse(state.allowsSave(transcript: ""))

        state.confirmAudioOnly()
        XCTAssertEqual(state.phase, .audioOnlyConfirmed)
        XCTAssertTrue(state.allowsSave(transcript: ""))
    }

    func testTypingAfterUnavailableRecognitionRestoresTranscriptBackedSave() {
        var state = ReferenceTranscriptionReviewState(initialTranscript: "")
        let generation = state.beginAutomaticTranscription()
        state.finishWithoutTranscript(
            reason: .emptyResult,
            generation: generation,
            currentTranscript: ""
        )
        state.userEditedTranscript("Manually entered words")

        XCTAssertEqual(state.phase, .ready(.manual))
        XCTAssertTrue(state.allowsSave(transcript: "Manually entered words"))
    }

    func testPendingCloneHandoffPreservesExactReviewedEnrollmentIdentity() {
        let handoff = PendingVoiceCloningHandoff(
            savedVoiceID: "voice-ici-3",
            wavPath: "/private/app-group/voices/voice-ici-3.wav",
            transcript: "Reviewed transcript",
            transcriptLoadError: nil,
            referenceLanguage: .english
        )

        XCTAssertEqual(handoff.savedVoiceID, "voice-ici-3")
        XCTAssertEqual(handoff.wavPath, "/private/app-group/voices/voice-ici-3.wav")
        XCTAssertEqual(handoff.transcript, "Reviewed transcript")
        XCTAssertNil(handoff.transcriptLoadError)
        XCTAssertEqual(handoff.referenceLanguage, .english)
    }
}
