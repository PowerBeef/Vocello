import Foundation
import XCTest

/// PA-21 / IOS-09: Studio drafts survive termination in the background.
final class IOSStudioDraftPersistenceTests: XCTestCase {
    private func delivery(_ customText: String = "") -> IOSStudioDraftSnapshot.Delivery {
        .init(mode: customText.isEmpty ? "preset" : "custom", presetID: "neutral", intensity: 2, customText: customText)
    }

    private func snapshot(cloneVoiceID: String? = "saved-voice") -> IOSStudioDraftSnapshot {
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
                language: "french",
                pinnedSeed: 42,
                text: "Clone script"
            )
        )
    }

    private func jsonObject(_ snapshot: IOSStudioDraftSnapshot) throws -> [String: Any] {
        let data = try XCTUnwrap(IOSStudioDraftPersistence.encode(snapshot))
        return try XCTUnwrap(JSONSerialization.jsonObject(with: data) as? [String: Any])
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

    /// PA-21 review: only the saved voice's ID is stored. Its App Group path
    /// would go stale after a backup restore and its transcript would outlive
    /// the voice; the Studio's hydration derives both from the library.
    func testOnlyTheSavedVoiceIDIsStored() throws {
        let clone = try XCTUnwrap(jsonObject(snapshot())["clone"] as? [String: Any])

        XCTAssertEqual(clone["savedVoiceID"] as? String, "saved-voice")
        XCTAssertEqual(Set(clone.keys), ["savedVoiceID", "language", "pinnedSeed", "text"])

        let unsaved = snapshot(cloneVoiceID: nil)
        XCTAssertNil(unsaved.clone.savedVoiceID)
        XCTAssertEqual(unsaved.clone.text, "Clone script", "the script itself is still kept")
    }

    /// A snapshot written by an earlier build still loads: its saved-voice path
    /// and transcript are ignored, and decoding takes the same normalization as
    /// building a snapshot.
    func testDecodingIgnoresLegacyReferenceFieldsAndNormalizes() throws {
        // A seed JSONSerialization carries exactly (it reads large integers as doubles).
        var base = snapshot()
        base.custom.pinnedSeed = 7
        var object = try jsonObject(base)
        var clone = try XCTUnwrap(object["clone"] as? [String: Any])
        clone["referenceAudioPath"] = "/voices/saved-voice.wav"
        clone["referenceTranscript"] = "Reference words"
        object["clone"] = clone
        let legacy = try JSONSerialization.data(withJSONObject: object)

        XCTAssertEqual(IOSStudioDraftPersistence.decode(legacy), base)

        clone["savedVoiceID"] = "  "
        object["clone"] = clone
        let blankID = try JSONSerialization.data(withJSONObject: object)
        let decoded = try XCTUnwrap(IOSStudioDraftPersistence.decode(blankID))
        XCTAssertNil(decoded.clone.savedVoiceID)
        XCTAssertNil(snapshot(cloneVoiceID: "").clone.savedVoiceID)
    }
}
