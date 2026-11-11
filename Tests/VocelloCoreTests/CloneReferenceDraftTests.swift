import Foundation
import QwenVoiceCore
import XCTest

final class CloneReferenceDraftTests: XCTestCase {
    func testReplacingAOneOffReferenceClearsTheTranscriptOfTheOldClip() {
        var draft = VoiceCloningDraft()
        draft.referenceAudioPath = "/tmp/u14-clip-a.wav"
        draft.referenceTranscript = "Words recognized for clip A."

        XCTAssertTrue(draft.replaceReferenceAudio(with: "/tmp/u14-clip-b.wav"))
        XCTAssertEqual(draft.referenceAudioPath, "/tmp/u14-clip-b.wav")
        XCTAssertEqual(draft.referenceTranscript, "", "clip B is recognized again, never sent with A's words")
        XCTAssertNil(draft.selectedSavedVoiceID)
    }

    /// G-11: the draft carries the one-off clip's check, so the Studio's
    /// controls, its priming and the shell's background warm all read one fact.
    func testAOneOffClipTheEngineWouldRefuseIsNeverReady() {
        var draft = VoiceCloningDraft()
        XCTAssertNil(draft.oneOffReferenceSelectionID)
        draft.replaceReferenceAudio(with: "/tmp/long.wav")
        draft.confirmAudioOnly()
        let selection = try? XCTUnwrap(draft.oneOffReferenceSelectionID)
        XCTAssertTrue(draft.isReferenceReady, "an unchecked clip is not held back: the engine refuses it if it must")

        draft.recordOneOffReferenceCheck(
            warnings: ["reference_duration_excessive", "reference_source_rate_low"], for: selection ?? "")
        XCTAssertEqual(draft.oneOffReferenceWarnings, ["reference_duration_excessive", "reference_source_rate_low"])
        XCTAssertEqual(draft.oneOffReferenceBlockingToken, "reference_duration_excessive")
        XCTAssertFalse(draft.isReferenceReady)

        // Advice alone never holds the clip back.
        draft.replaceReferenceAudio(with: "/tmp/phone.wav")
        draft.confirmAudioOnly()
        XCTAssertEqual(draft.oneOffReferenceWarnings, [], "a new clip starts unchecked")
        draft.recordOneOffReferenceCheck(
            warnings: ["reference_source_rate_low"], for: draft.oneOffReferenceSelectionID ?? "")
        XCTAssertTrue(draft.isReferenceReady)
        XCTAssertEqual(draft.oneOffReferenceWarnings, ["reference_source_rate_low"])
    }

    func testACheckForAnEarlierSelectionIsDroppedAndASavedVoiceHasNone() {
        var draft = VoiceCloningDraft()
        draft.replaceReferenceAudio(with: "/tmp/clip.wav")
        let first = draft.oneOffReferenceSelectionID ?? ""
        // The same path chosen again is a new selection: the file may have been replaced.
        draft.replaceReferenceAudio(with: "/tmp/clip.wav")
        XCTAssertNotEqual(draft.oneOffReferenceSelectionID, first)
        draft.recordOneOffReferenceCheck(warnings: ["reference_near_silence"], for: first)
        XCTAssertEqual(draft.oneOffReferenceWarnings, [], "a late result for the earlier selection is dropped")

        draft.recordOneOffReferenceCheck(
            warnings: ["reference_near_silence"], for: draft.oneOffReferenceSelectionID ?? "")
        XCTAssertEqual(draft.oneOffReferenceBlockingToken, "reference_near_silence")
        // A saved voice was checked when it was enrolled; the clip's result does not follow it.
        draft.applySavedVoiceSelection(id: "Voice", wavPath: "/tmp/Voice.wav", transcript: "Stored words")
        XCTAssertNil(draft.oneOffReferenceSelectionID)
        XCTAssertEqual(draft.oneOffReferenceWarnings, [])
        XCTAssertNil(draft.oneOffReferenceBlockingToken)
        XCTAssertTrue(draft.isReferenceReady)
        draft.clearReference()
        XCTAssertEqual(draft.oneOffReferenceWarnings, [])
    }

    func testChoosingTheSamePathAgainStartsANewReferenceReview() {
        var draft = VoiceCloningDraft()
        draft.referenceAudioPath = "/tmp/u14-clip-a.wav"
        draft.referenceTranscript = "Corrected by hand."

        XCTAssertTrue(draft.replaceReferenceAudio(with: "/tmp/u14-clip-a.wav"))
        XCTAssertEqual(draft.referenceTranscript, "")
        XCTAssertFalse(draft.isReferenceReady)
    }

    func testAOneOffClipReplacingASavedVoiceDropsItsHydratedTranscript() {
        var draft = VoiceCloningDraft()
        draft.applySavedVoiceSelection(id: "Alice", wavPath: "/tmp/u14/Alice.wav", transcript: "Alice's sidecar.")

        // Even the saved voice's own file, chosen as a one-off clip.
        XCTAssertTrue(draft.replaceReferenceAudio(with: "/tmp/u14/Alice.wav"))
        XCTAssertNil(draft.selectedSavedVoiceID)
        XCTAssertEqual(draft.referenceTranscript, "")
    }

    /// G-02: what the draft shows is what conditions the take. Clearing a
    /// saved voice's transcript and choosing audio only must reach the engine
    /// as audio only, not as a request that reads the stored transcript back.
    func testChoosingAudioOnlyForASavedVoiceReachesTheRequestAsAudioOnly() {
        var draft = VoiceCloningDraft()
        draft.applySavedVoiceSelection(id: "Alice", wavPath: "/tmp/g02/Alice.wav", transcript: "Alice's sidecar.")
        let hydrated = draft.cloneReference(audioPath: "/tmp/g02/Alice.wav")
        XCTAssertEqual(hydrated.transcript, "Alice's sidecar.")
        XCTAssertFalse(hydrated.bypassesStoredTranscript)

        draft.confirmAudioOnly()
        XCTAssertTrue(draft.isReferenceReady)
        let audioOnly = draft.cloneReference(audioPath: "/tmp/g02/Alice.wav")
        XCTAssertNil(audioOnly.transcript)
        XCTAssertEqual(audioOnly.preparedVoiceID, "Alice")
        XCTAssertTrue(audioOnly.bypassesStoredTranscript)
        XCTAssertNotEqual(
            GenerationSemantics.clonePreparationKey(modelID: "clone", reference: hydrated),
            GenerationSemantics.clonePreparationKey(modelID: "clone", reference: audioOnly))
    }

    func testAOneOffAudioOnlyReferenceKeepsTheKeyItAlwaysHad() {
        var draft = VoiceCloningDraft()
        draft.replaceReferenceAudio(with: "/tmp/g02/clip.wav")
        draft.confirmAudioOnly()
        let reference = draft.cloneReference(audioPath: "/tmp/g02/clip.wav")
        XCTAssertTrue(reference.isExplicitlyAudioOnly)
        XCTAssertFalse(reference.bypassesStoredTranscript)
        XCTAssertEqual(
            GenerationSemantics.clonePreparationKey(modelID: "clone", reference: reference),
            GenerationSemantics.clonePreparationKey(modelID: "clone", reference: CloneReference(audioPath: "/tmp/g02/clip.wav")))
    }

    /// G-01 in the Studio: a partial transcript is never ready on its own;
    /// the user's review or the audio-only choice resolves it.
    func testAPartialTranscriptIsNotReadyUntilTheUserReviewsIt() {
        var draft = VoiceCloningDraft()
        draft.replaceReferenceAudio(with: "/tmp/g01/clip.wav")
        let operation = draft.beginReferenceTranscription()
        draft.acceptReferenceTranscript("Only the second sentence.", generation: operation, coverage: .partial)
        XCTAssertEqual(draft.referenceTranscript, "Only the second sentence.")
        XCTAssertEqual(draft.referenceReview.phase, .ready(.automaticPartial))
        XCTAssertFalse(draft.isReferenceReady)

        var reviewed = draft
        reviewed.reviewReferenceTranscript()
        XCTAssertTrue(reviewed.isReferenceReady)
        XCTAssertEqual(reviewed.cloneReference(audioPath: "/tmp/g01/clip.wav").transcript, "Only the second sentence.")

        var audioOnly = draft
        audioOnly.confirmAudioOnly()
        XCTAssertTrue(audioOnly.isReferenceReady)
        XCTAssertTrue(audioOnly.cloneReference(audioPath: "/tmp/g01/clip.wav").isExplicitlyAudioOnly)
    }

    func testDeletingTheSelectedSavedVoiceClearsTheDraftLikeTheIPhone() {
        var draft = VoiceCloningDraft()
        draft.applySavedVoiceSelection(id: "Alice", wavPath: "/tmp/u14/Alice.wav", transcript: "Alice's sidecar.")
        draft.text = "The script stays."

        draft.savedVoiceWasDeleted(id: "Bob")
        XCTAssertEqual(draft.selectedSavedVoiceID, "Alice", "another voice's deletion leaves the draft alone")

        draft.savedVoiceWasDeleted(id: "Alice")
        XCTAssertNil(draft.selectedSavedVoiceID)
        XCTAssertNil(draft.referenceAudioPath)
        XCTAssertEqual(draft.referenceTranscript, "")
        XCTAssertEqual(draft.text, "The script stays.")
    }

    /// Replace reference keeps the voice's ID and, for the same extension, its
    /// path: the hydration used to accept the draft's old transcript. After
    /// the replacement event it applies the new clip's transcript from disk.
    func testAReferenceReplacedInPlaceIsHydratedFromDiskAgain() throws {
        let root = try temporaryDirectory("u14-replace")
        defer { try? FileManager.default.removeItem(at: root) }
        let audioURL = root.appendingPathComponent("Alice.wav")
        try Data([0x52, 0x49, 0x46, 0x46]).write(to: audioURL)
        try "The new clip's words.".write(
            to: root.appendingPathComponent("Alice.txt"),
            atomically: true,
            encoding: .utf8
        )
        let voice = PreparedVoice(id: "Alice", name: "Alice", audioPath: audioURL.path, hasTranscript: true)

        var draft = VoiceCloningDraft()
        draft.applySavedVoice(voice, transcript: "The old clip's words.")
        XCTAssertEqual(
            SavedVoiceCloneHydration.action(draft: draft, voice: voice, hydratedVoiceID: nil, transcriptLoadError: nil),
            .acceptCurrentDraft,
            "same ID and path: without the event the old transcript would be kept"
        )

        draft.savedVoiceReferenceWasReplaced(id: "Alice")
        XCTAssertEqual(
            SavedVoiceCloneHydration.action(draft: draft, voice: voice, hydratedVoiceID: nil, transcriptLoadError: nil),
            .applyFromDisk
        )
        XCTAssertEqual(try SavedVoiceCloneHydration.loadTranscript(for: voice), "The new clip's words.")

        // A replacement that saved no transcript stays audio-only.
        let audioOnly = PreparedVoice(id: "Alice", name: "Alice", audioPath: audioURL.path, hasTranscript: false)
        var audioOnlyDraft = VoiceCloningDraft()
        audioOnlyDraft.applySavedVoice(audioOnly, transcript: "The old clip's words.")
        audioOnlyDraft.savedVoiceReferenceWasReplaced(id: "Alice")
        XCTAssertEqual(
            SavedVoiceCloneHydration.action(
                draft: audioOnlyDraft,
                voice: audioOnly,
                hydratedVoiceID: nil,
                transcriptLoadError: nil
            ),
            .acceptCurrentDraft
        )
        XCTAssertEqual(audioOnlyDraft.referenceTranscript, "")
    }

    func testAutomaticTranscriptNeedsReviewBeforeCloning() {
        var draft = VoiceCloningDraft()
        draft.replaceReferenceAudio(with: "/tmp/a.wav")
        let operation = draft.beginReferenceTranscription()
        XCTAssertFalse(draft.isReferenceReady)
        draft.acceptReferenceTranscript("  Bonjour\n le monde.  ", generation: operation, coverage: .whole)
        XCTAssertEqual(draft.trimmedReferenceTranscript, "Bonjour le monde.")
        XCTAssertFalse(draft.isReferenceReady)
        draft.reviewReferenceTranscript()
        XCTAssertTrue(draft.isReferenceReady)
    }

    func testAudioOnlyDecisionRejectsLateAutomaticResult() {
        var draft = VoiceCloningDraft()
        draft.replaceReferenceAudio(with: "/tmp/a.wav")
        let operation = draft.beginReferenceTranscription()
        draft.confirmAudioOnly()
        draft.acceptReferenceTranscript("Late recognized words", generation: operation, coverage: .whole)
        XCTAssertNil(draft.trimmedReferenceTranscript)
        XCTAssertTrue(draft.isReferenceReady)
        XCTAssertEqual(draft.referenceReview.phase, .audioOnlyConfirmed)
    }

    func testAtoBtoASelectionRejectsTheFirstOperation() {
        var draft = VoiceCloningDraft()
        draft.replaceReferenceAudio(with: "/tmp/a.wav")
        let first = draft.beginReferenceTranscription()
        draft.replaceReferenceAudio(with: "/tmp/b.wav")
        draft.replaceReferenceAudio(with: "/tmp/a.wav")
        let current = draft.beginReferenceTranscription()
        draft.acceptReferenceTranscript("Stale A", generation: first, coverage: .whole)
        XCTAssertEqual(draft.referenceTranscript, "")
        draft.acceptReferenceTranscript("Current A", generation: current, coverage: .whole)
        XCTAssertEqual(draft.referenceTranscript, "Current A")
    }

    func testEditingThenClearingRejectsEarlierRecognition() {
        var draft = VoiceCloningDraft()
        draft.replaceReferenceAudio(with: "/tmp/a.wav")
        let operation = draft.beginReferenceTranscription()
        draft.referenceTranscript = "My words"
        draft.referenceTranscript = ""
        draft.acceptReferenceTranscript("Earlier words", generation: operation, coverage: .whole)
        XCTAssertEqual(draft.referenceTranscript, "")
        XCTAssertFalse(draft.isReferenceReady)
    }

    func testSavedAudioOnlyChoiceStaysReadyAndReviewedSidecarsNormalize() {
        var draft = VoiceCloningDraft()
        draft.applySavedVoiceSelection(id: "voice", wavPath: "/tmp/voice.wav", transcript: "")
        XCTAssertTrue(draft.isReferenceReady)
        XCTAssertEqual(draft.referenceReview.phase, .audioOnlyConfirmed)
        draft.applySavedVoiceSelection(id: "voice", wavPath: "/tmp/voice.wav", transcript: "  Bonjour\n monde  ")
        XCTAssertTrue(draft.isReferenceReady)
        XCTAssertEqual(draft.trimmedReferenceTranscript, "Bonjour monde")
    }

    func testSamePathReplacementAndClearRejectOldOperations() {
        var draft = VoiceCloningDraft()
        draft.replaceReferenceAudio(with: "/tmp/a.wav")
        let first = draft.beginReferenceTranscription()
        draft.replaceReferenceAudio(with: "/tmp/a.wav")
        draft.acceptReferenceTranscript("Old contents", generation: first, coverage: .whole)
        XCTAssertEqual(draft.referenceTranscript, "")
        let second = draft.beginReferenceTranscription()
        draft.clearReference()
        draft.acceptReferenceTranscript("After clearing", generation: second, coverage: .whole)
        XCTAssertFalse(draft.isReferenceReady)
        XCTAssertEqual(draft.referenceTranscript, "")
    }

    private func temporaryDirectory(_ label: String) throws -> URL {
        let root = FileManager.default.temporaryDirectory
            .appendingPathComponent("clone-draft-\(label)-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        return root
    }
}
