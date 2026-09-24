import Foundation
import XCTest

/// PA-21 / IOS-09: Studio drafts survive termination in the background.
final class IOSStudioDraftPersistenceTests: XCTestCase {
    private func delivery(_ customText: String = "") -> IOSStudioDraftSnapshot.Delivery {
        .init(mode: customText.isEmpty ? "preset" : "custom", presetID: "neutral", intensity: 2, customText: customText)
    }

    private func snapshot(
        cloneVoiceID: String? = "saved-voice",
        clonePath: String? = "/voices/saved-voice.wav"
    ) -> IOSStudioDraftSnapshot {
        IOSStudioDraftSnapshot(
            custom: .init(
                speakerID: "aiden",
                language: "english",
                pinnedSeed: UInt64.max,
                delivery: delivery("warm, unhurried"),
                text: String(repeating: "A long script line. ", count: 1_500)
            ),
            design: .init(
                voiceDescription: "A calm narrator",
                language: "auto",
                pinnedSeed: nil,
                delivery: delivery(),
                text: "Design script"
            ),
            clone: .init(
                savedVoiceID: cloneVoiceID,
                referenceAudioPath: clonePath,
                referenceTranscript: "Reference words",
                language: "french",
                pinnedSeed: 42,
                text: "Clone script"
            )
        )
    }

    func testDraftsRoundTripThroughPreferencesIncludingLongScriptsAndFullSeeds() throws {
        let suite = "vocello.tests.studioDrafts.\(UUID().uuidString)"
        let defaults = try XCTUnwrap(UserDefaults(suiteName: suite))
        defer { defaults.removePersistentDomain(forName: suite) }
        let original = snapshot()

        IOSStudioDraftPersistence.save(original, to: defaults)

        XCTAssertEqual(IOSStudioDraftPersistence.load(from: defaults), original)
        XCTAssertEqual(original.custom.text.count, 30_000)
        XCTAssertEqual(IOSStudioDraftPersistence.load(from: defaults)?.custom.pinnedSeed, UInt64.max)
    }

    func testMissingCorruptOrOtherVersionSnapshotsStartEmpty() throws {
        let suite = "vocello.tests.studioDrafts.\(UUID().uuidString)"
        let defaults = try XCTUnwrap(UserDefaults(suiteName: suite))
        defer { defaults.removePersistentDomain(forName: suite) }
        XCTAssertNil(IOSStudioDraftPersistence.load(from: defaults))

        defaults.set(Data("not json".utf8), forKey: IOSStudioDraftPersistence.defaultsKey)
        XCTAssertNil(IOSStudioDraftPersistence.load(from: defaults))

        var future = snapshot()
        future.version = IOSStudioDraftSnapshot.currentVersion + 1
        XCTAssertNil(IOSStudioDraftPersistence.decode(IOSStudioDraftPersistence.encode(future)))
    }

    func testOnlyASavedVoiceReferenceIsKept() {
        let unsaved = snapshot(cloneVoiceID: nil, clonePath: "/cache/imported.wav")

        XCTAssertNil(unsaved.clone.referenceAudioPath)
        XCTAssertEqual(unsaved.clone.referenceTranscript, "")
        XCTAssertEqual(unsaved.clone.text, "Clone script", "the script itself is still kept")

        let saved = snapshot()
        XCTAssertEqual(saved.clone.savedVoiceID, "saved-voice")
        XCTAssertEqual(saved.clone.referenceAudioPath, "/voices/saved-voice.wav")
        XCTAssertEqual(saved.clone.referenceTranscript, "Reference words")
    }
}
