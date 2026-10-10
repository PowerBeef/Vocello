import Foundation
import QwenVoiceCore
import XCTest

final class SavedVoiceSheetConfigurationTests: XCTestCase {
    func testReplaceReferenceNamesTheVoiceByItsStoreID() {
        let configuration = SavedVoiceSheetConfiguration.replaceReference(
            voiceID: "Grandma Rose",
            name: "Grandma Rose",
            transcript: "The old clip's words.",
            referenceLanguage: .english
        )
        XCTAssertEqual(configuration.replacingVoiceID, "Grandma Rose")
        XCTAssertEqual(configuration.initialAudioPath, "")
        XCTAssertEqual(configuration.initialTranscriptClip, .replacedReference)
    }

    func testEachSheetFlowBindsItsTranscriptToTheRightClip() {
        XCTAssertEqual(SavedVoiceSheetConfiguration.manualAdd.initialTranscriptClip, .unbound)
        XCTAssertEqual(
            SavedVoiceSheetConfiguration.cloneResult(
                suggestedName: "Take",
                audioPath: "/tmp/u15-take.wav",
                transcript: "The script of the take."
            ).initialTranscriptClip,
            .clip("/tmp/u15-take.wav")
        )
        XCTAssertEqual(
            SavedVoiceSheetConfiguration.replaceReference(voiceID: "Anna", name: "Anna", transcript: "")
                .initialTranscriptClip,
            .unbound
        )
    }

    /// The sheet checks names as the store normalizes them: spaces and
    /// apostrophes stay, so "Grandma Rose" is its own ID, a duplicate is found
    /// before saving, and the voice being replaced is not a collision.
    func testTheSheetNameCheckUsesTheStoreNormalization() {
        let existing: Set<String> = ["Grandma Rose", "Anna"]
        XCTAssertNil(SavedVoiceSheetConfiguration.nameIssue(
            for: "Grandma Rose",
            existingVoiceIDs: existing,
            replacingVoiceID: "Grandma Rose"
        ))
        XCTAssertEqual(
            SavedVoiceSheetConfiguration.nameIssue(for: "Grandma Rose", existingVoiceIDs: existing, replacingVoiceID: nil),
            .exists("Grandma Rose")
        )
        XCTAssertEqual(
            SavedVoiceSheetConfiguration.nameIssue(for: "anna", existingVoiceIDs: existing, replacingVoiceID: nil),
            .exists("anna"),
            "the store's file check is case-insensitive"
        )
        XCTAssertNil(SavedVoiceSheetConfiguration.nameIssue(
            for: "Rose's Voice",
            existingVoiceIDs: existing,
            replacingVoiceID: nil
        ))
        XCTAssertEqual(
            SavedVoiceSheetConfiguration.nameIssue(for: "!!!", existingVoiceIDs: [], replacingVoiceID: nil),
            .needsCharacters
        )
        XCTAssertEqual(
            SavedVoiceSheetConfiguration.nameIssue(for: "///", existingVoiceIDs: [], replacingVoiceID: nil),
            .needsCharacters
        )
        XCTAssertNil(SavedVoiceSheetConfiguration.nameIssue(for: "", existingVoiceIDs: existing, replacingVoiceID: nil))
    }
}
