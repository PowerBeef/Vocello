import Foundation
import QwenVoiceCore
import XCTest

final class IOSReferenceTranscriptionReviewStateTests: XCTestCase {
    func testSupportedImportTypesShareOnePolicy() throws {
        XCTAssertEqual(
            IOSReferenceAudioImportPolicy.supportedExtensions,
            ["wav", "mp3", "aiff", "aif", "m4a"]
        )
        XCTAssertEqual(IOSReferenceAudioImportPolicy.allowedContentTypes.count, 4)
        XCTAssertThrowsError(
            try IOSReferenceAudioImportPolicy.validatedSourceURL(
                URL(fileURLWithPath: "/tmp/reference.txt")
            )
        )
        XCTAssertNoThrow(
            try IOSReferenceAudioImportPolicy.validatedSourceURL(URL(fileURLWithPath: "/tmp/reference.AIF")),
            "The AIFF type's other extension is accepted"
        )
    }

    /// IOS-23: Files offers Vocello only for the formats the import accepts.
    func testTheDocumentTypesListTheImportFormats() throws {
        let infoPlist = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
            .appendingPathComponent("Sources/iOS/Info.plist")
        guard FileManager.default.fileExists(atPath: infoPlist.path) else {
            throw XCTSkip("The repository sources are not on this host")
        }
        let plist = try XCTUnwrap(
            PropertyListSerialization.propertyList(from: Data(contentsOf: infoPlist), format: nil) as? [String: Any]
        )
        let documentTypes = try XCTUnwrap(plist["CFBundleDocumentTypes"] as? [[String: Any]])
        let declared = documentTypes.flatMap { $0["LSItemContentTypes"] as? [String] ?? [] }
        XCTAssertEqual(declared, IOSReferenceAudioImportPolicy.allowedContentTypes.map(\.identifier))
        XCTAssertFalse(declared.contains("public.audio"))
    }

    /// CORE-16: the copy runs off the main actor and refuses a file larger
    /// than audio preparation accepts before copying it.
    func testAnOversizedImportIsRefusedWithInterfaceCopy() async throws {
        let root = FileManager.default.temporaryDirectory
            .appendingPathComponent("IOSReferenceImport-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: root) }
        let source = root.appendingPathComponent("long.wav")
        XCTAssertTrue(FileManager.default.createFile(atPath: source.path, contents: nil))
        let handle = try FileHandle(forWritingTo: source)
        // Sparse: the size is logical, no bytes are written.
        try handle.truncate(atOffset: UInt64(AudioPreparationLimits.defaults.maxInputFileSizeBytes + 1))
        try handle.close()
        let destination = root.appendingPathComponent("imported", isDirectory: true)

        do {
            _ = try await IOSReferenceAudioImportPolicy.importReference(from: source, into: destination)
            XCTFail("An oversized reference must be refused")
        } catch {
            guard case .referenceTooLarge? = error as? DocumentIOError else {
                return XCTFail("Unexpected \(error)")
            }
            let presentation = VocelloPresentationText()
            XCTAssertEqual(
                IOSReferenceAudioImportPolicy.failureMessage(for: error, presentation: presentation),
                presentation.generationFailureMessage(.referenceAudioTooLong)
            )
        }
        XCTAssertFalse(FileManager.default.fileExists(atPath: destination.path), "Nothing is copied")
    }

    func testImportFailuresReachTheAlertInTheInterfaceLanguage() {
        let presentation = VocelloPresentationText()
        XCTAssertEqual(
            IOSReferenceAudioImportPolicy.failureMessage(
                for: IOSReferenceAudioImportPolicy.ValidationError.unsupportedType,
                presentation: presentation
            ),
            presentation.importReferenceAudioDetail
        )
        XCTAssertNil(
            IOSReferenceAudioImportPolicy.failureMessage(
                for: DocumentIOError.failedToCopy("/private/path/voice.wav"),
                presentation: presentation
            ),
            "A copy failure shows the alert's generic detail, never a path"
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
