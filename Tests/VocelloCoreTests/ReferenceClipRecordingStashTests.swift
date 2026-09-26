import XCTest

/// MAC-25: recorded reference clips do not outlive their use.
final class ReferenceClipRecordingStashTests: XCTestCase {
    private var root: URL!
    private var stash: URL!

    override func setUpWithError() throws {
        root = FileManager.default.temporaryDirectory
            .appendingPathComponent("ReferenceClipRecordingStashTests-\(UUID().uuidString)", isDirectory: true)
        stash = root.appendingPathComponent("voice-enroll", isDirectory: true)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
    }

    override func tearDownWithError() throws {
        try? FileManager.default.removeItem(at: root)
    }

    private func source() throws -> URL {
        let url = root.appendingPathComponent("capture-\(UUID().uuidString).wav")
        try Data("clip".utf8).write(to: url)
        return url
    }

    func testDiscardRemovesOnlyStashCopies() throws {
        let copy = try XCTUnwrap(ReferenceClipRecordingStash.copyToStableTemp(try source(), in: stash))
        let imported = try source()

        ReferenceClipRecordingStash.discard(imported.path, in: stash)
        XCTAssertTrue(FileManager.default.fileExists(atPath: imported.path), "an imported reference is never deleted")

        ReferenceClipRecordingStash.discard(copy.path, in: stash)
        XCTAssertFalse(FileManager.default.fileExists(atPath: copy.path))
    }

    func testRemovingLeftoversDeletesBothFolders() throws {
        let capture = root.appendingPathComponent("voice-clone-references", isDirectory: true)
        try FileManager.default.createDirectory(at: capture, withIntermediateDirectories: true)
        _ = try XCTUnwrap(ReferenceClipRecordingStash.copyToStableTemp(try source(), in: stash))

        ReferenceClipRecordingStash.removeLeftoverRecordings(directories: [stash, capture])
        XCTAssertFalse(FileManager.default.fileExists(atPath: stash.path))
        XCTAssertFalse(FileManager.default.fileExists(atPath: capture.path))
    }

    @MainActor
    func testTheTrackerRemovesClipsWhenTheSheetCloses() {
        var removed: [String] = []
        let tracker = ReferenceClipStashTracker { removed.append($0) }
        tracker.record("/stash/a.wav")
        tracker.record("/stash/b.wav")
        XCTAssertEqual(removed, [])

        tracker.close()
        XCTAssertEqual(removed, ["/stash/a.wav", "/stash/b.wav"])
    }

    @MainActor
    func testASaveStillReadingAClipDefersRemovalUntilItEnds() {
        var removed: [String] = []
        let tracker = ReferenceClipStashTracker { removed.append($0) }
        tracker.record("/stash/a.wav")
        tracker.beginUse()

        tracker.close()
        XCTAssertEqual(removed, [], "Cancel must not delete the clip a save is still copying")

        tracker.endUse()
        XCTAssertEqual(removed, ["/stash/a.wav"])

        tracker.endUse()
        tracker.close()
        XCTAssertEqual(removed, ["/stash/a.wav"], "each clip is removed once")
    }

    @MainActor
    func testAClipRecordedAfterCloseIsRemovedAtOnce() {
        var removed: [String] = []
        let tracker = ReferenceClipStashTracker { removed.append($0) }
        tracker.close()
        tracker.record("/stash/late.wav")
        XCTAssertEqual(removed, ["/stash/late.wav"])
    }
}
