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

    // MARK: - Per-process folders and the leftover sweep

    private var recordings: URL {
        root.appendingPathComponent("vocello-reference-recordings", isDirectory: true)
    }

    /// A process folder as the recorder and the stash fill it.
    @discardableResult
    private func makeFolder(of owner: ReferenceClipRecordingOwner) throws -> URL {
        let folder = recordings.appendingPathComponent(owner.folderName, isDirectory: true)
        let capture = folder.appendingPathComponent("voice-clone-references", isDirectory: true)
        try FileManager.default.createDirectory(at: capture, withIntermediateDirectories: true)
        try Data("capture".utf8).write(to: capture.appendingPathComponent("reference.wav"))
        let enroll = folder.appendingPathComponent("voice-enroll", isDirectory: true)
        _ = try XCTUnwrap(ReferenceClipRecordingStash.copyToStableTemp(try source(), in: enroll))
        return folder
    }

    /// The identifier of a process that has exited (and been reaped).
    private func endedProcessIdentifier() throws -> Int32 {
        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/usr/bin/true")
        try process.run()
        process.waitUntilExit()
        return process.processIdentifier
    }

    private func exists(_ url: URL) -> Bool {
        FileManager.default.fileExists(atPath: url.path)
    }

    func testTheStashAndTheCaptureLiveInThisProcessFolder() {
        let owner = ReferenceClipRecordingOwner.current
        XCTAssertEqual(owner.processIdentifier, ProcessInfo.processInfo.processIdentifier)
        XCTAssertNotEqual(owner.startTime, 0, "The kernel reports this process's start time")
        XCTAssertEqual(ReferenceClipRecordingStash.processDirectory.lastPathComponent, owner.folderName)
        XCTAssertEqual(
            ReferenceClipRecordingStash.directory.deletingLastPathComponent().standardizedFileURL,
            ReferenceClipRecordingStash.processDirectory.standardizedFileURL
        )
        XCTAssertEqual(
            ReferenceClipRecordingStash.captureDirectory.deletingLastPathComponent().standardizedFileURL,
            ReferenceClipRecordingStash.processDirectory.standardizedFileURL
        )
        XCTAssertFalse(
            ReferenceClipRecordingStash.legacyDirectories.contains(ReferenceClipRecordingStash.recordingsRoot),
            "An earlier build's sweep of its flat folders never reaches the new layout"
        )
    }

    func testAFolderNameReadsBackAndRejectsWhatItDidNotName() {
        let owner = ReferenceClipRecordingOwner(
            bundleIdentifier: "com.qwenvoice.app",
            processIdentifier: 4242,
            startTime: 1_790_431_387_250_000
        )
        XCTAssertEqual(owner.folderName, "com.qwenvoice.app_4242_1790431387250000")
        XCTAssertEqual(ReferenceClipRecordingOwner(folderName: owner.folderName), owner)

        let odd = ReferenceClipRecordingOwner(bundleIdentifier: "com.example_app x", processIdentifier: 7, startTime: 9)
        XCTAssertEqual(odd.bundleIdentifier, "com.example-app-x", "An underscore never splits the name")
        XCTAssertEqual(ReferenceClipRecordingOwner(folderName: odd.folderName), odd)

        for name in ["voice-enroll", "notes", "a_b", "a_0_1", "a_-3_1", "a_1_x", "_1_2", "a_b_1_2", "a b_1_2"] {
            XCTAssertNil(ReferenceClipRecordingOwner(folderName: name), name)
        }
    }

    func testTheSweepKeepsALiveProcessFolderAndRemovesDeadOnes() throws {
        // The sweeping copy is another process; this test process stands in
        // for a running copy whose capture is in flight.
        let live = ReferenceClipRecordingOwner.current
        guard live.startTime > 1_000_000 else {
            return XCTFail("The kernel reports this process's start time")
        }
        let dead = ReferenceClipRecordingOwner(
            bundleIdentifier: "com.qwenvoice.app",
            processIdentifier: try endedProcessIdentifier(),
            startTime: live.startTime
        )
        // The folder's owner started a second before the process that now
        // holds its identifier.
        let reused = ReferenceClipRecordingOwner(
            bundleIdentifier: "com.qwenvoice.app",
            processIdentifier: live.processIdentifier,
            startTime: live.startTime - 1_000_000
        )
        let sweeper = ReferenceClipRecordingOwner(bundleIdentifier: "com.qwenvoice.app", processIdentifier: 1, startTime: 1)
        XCTAssertFalse(live.hasEnded)
        XCTAssertTrue(dead.hasEnded, "No process has the identifier any more")
        XCTAssertTrue(reused.hasEnded, "A later process reuses the identifier")

        let liveFolder = try makeFolder(of: live)
        let deadFolder = try makeFolder(of: dead)
        let reusedFolder = try makeFolder(of: reused)
        let unknown = recordings.appendingPathComponent("notes", isDirectory: true)
        try FileManager.default.createDirectory(at: unknown, withIntermediateDirectories: true)

        ReferenceClipRecordingStash.removeLeftoverRecordings(
            anotherCopyIsRunning: true,
            root: recordings,
            currentOwner: sweeper,
            legacyDirectories: []
        )

        XCTAssertTrue(exists(liveFolder.appendingPathComponent("voice-clone-references/reference.wav")),
                      "A running copy's live capture survives another copy's launch or quit")
        XCTAssertEqual(
            try FileManager.default.contentsOfDirectory(atPath: liveFolder.appendingPathComponent("voice-enroll").path).count,
            1,
            "A running copy's stash survives too"
        )
        XCTAssertFalse(exists(deadFolder))
        XCTAssertFalse(exists(reusedFolder))
        XCTAssertTrue(exists(unknown), "An entry this layout did not name is never removed")
    }

    func testTheSweepRemovesThisProcessOwnFolder() throws {
        let own = try makeFolder(of: .current)

        ReferenceClipRecordingStash.removeLeftoverRecordings(
            anotherCopyIsRunning: true,
            root: recordings,
            currentOwner: .current,
            legacyDirectories: []
        )

        XCTAssertFalse(exists(own), "At quit, this process's clips do not outlive it")
    }

    func testAnEarlierBuildFlatFoldersGoOnlyWhenNoOtherCopyRuns() throws {
        let legacyStash = root.appendingPathComponent("voice-enroll", isDirectory: true)
        let legacyCapture = root.appendingPathComponent("voice-clone-references", isDirectory: true)
        _ = try XCTUnwrap(ReferenceClipRecordingStash.copyToStableTemp(try source(), in: legacyStash))
        try FileManager.default.createDirectory(at: legacyCapture, withIntermediateDirectories: true)
        try Data("capture".utf8).write(to: legacyCapture.appendingPathComponent("reference-2026-09-26T14-03-07Z.wav"))
        let live = try makeFolder(of: .current)
        let later = Date().addingTimeInterval(2 * ReferenceClipRecordingStash.legacyRecordingMinimumAge)

        ReferenceClipRecordingStash.removeLeftoverRecordings(
            anotherCopyIsRunning: true,
            root: recordings,
            currentOwner: ReferenceClipRecordingOwner(bundleIdentifier: "com.qwenvoice.app", processIdentifier: 1, startTime: 1),
            legacyDirectories: [legacyStash, legacyCapture],
            now: later
        )
        XCTAssertTrue(exists(legacyStash), "A running copy of the earlier build may still use them")
        XCTAssertTrue(exists(legacyCapture))

        ReferenceClipRecordingStash.removeLeftoverRecordings(
            anotherCopyIsRunning: false,
            root: recordings,
            currentOwner: ReferenceClipRecordingOwner(bundleIdentifier: "com.qwenvoice.app", processIdentifier: 1, startTime: 1),
            legacyDirectories: [legacyStash, legacyCapture],
            now: later
        )
        XCTAssertFalse(exists(legacyStash))
        XCTAssertFalse(exists(legacyCapture))
        XCTAssertTrue(exists(live), "The legacy sweep never reaches a process folder")
    }

    /// B3 review: the flat folders have generic names in the per-user
    /// temporary directory every unsandboxed Mac app shares.
    func testTheLegacySweepRemovesOnlyTheClipsAnEarlierBuildWrote() throws {
        let legacyStash = root.appendingPathComponent("voice-enroll", isDirectory: true)
        let stashCopy = try XCTUnwrap(ReferenceClipRecordingStash.copyToStableTemp(try source(), in: legacyStash))
        let recent = try XCTUnwrap(ReferenceClipRecordingStash.copyToStableTemp(try source(), in: legacyStash))
        let foreign = legacyStash.appendingPathComponent("take.wav")
        try Data("another app".utf8).write(to: foreign)
        let foreignFolder = legacyStash.appendingPathComponent("\(UUID().uuidString).wav", isDirectory: true)
        try FileManager.default.createDirectory(at: foreignFolder, withIntermediateDirectories: true)
        let old = Date().addingTimeInterval(-2 * ReferenceClipRecordingStash.legacyRecordingMinimumAge)
        for url in [stashCopy, foreign] {
            try FileManager.default.setAttributes([.modificationDate: old], ofItemAtPath: url.path)
        }

        ReferenceClipRecordingStash.removeLegacyRecordings(in: legacyStash)

        XCTAssertFalse(exists(stashCopy), "An earlier build's stale stash copy goes")
        XCTAssertTrue(exists(recent), "A clip touched within the hour may still be in use")
        XCTAssertTrue(exists(foreign), "A file the earlier build did not name is never removed")
        XCTAssertTrue(exists(foreignFolder), "Only regular files are removed")
        XCTAssertTrue(exists(legacyStash), "A folder that still holds anything stays")

        try FileManager.default.removeItem(at: recent)
        try FileManager.default.removeItem(at: foreign)
        try FileManager.default.removeItem(at: foreignFolder)
        ReferenceClipRecordingStash.removeLegacyRecordings(in: legacyStash)
        XCTAssertFalse(exists(legacyStash), "An emptied folder goes")
    }

    func testTheLegacySweepNeverFollowsALinkInPlaceOfTheFolder() throws {
        let elsewhere = root.appendingPathComponent("elsewhere", isDirectory: true)
        try FileManager.default.createDirectory(at: elsewhere, withIntermediateDirectories: true)
        let target = elsewhere.appendingPathComponent("\(UUID().uuidString).wav")
        try Data("clip".utf8).write(to: target)
        try FileManager.default.setAttributes(
            [.modificationDate: Date().addingTimeInterval(-2 * ReferenceClipRecordingStash.legacyRecordingMinimumAge)],
            ofItemAtPath: target.path
        )
        let link = root.appendingPathComponent("voice-enroll", isDirectory: true)
        try FileManager.default.createSymbolicLink(at: link, withDestinationURL: elsewhere)

        ReferenceClipRecordingStash.removeLegacyRecordings(in: link)

        XCTAssertTrue(exists(target))
        XCTAssertTrue(exists(elsewhere))
    }

    func testLegacyClipNamesAreTheOnesEarlierBuildsWrote() {
        for name in ["\(UUID().uuidString).wav", "reference-2026-09-26T14-03-07Z.wav"] {
            XCTAssertTrue(ReferenceClipRecordingStash.isLegacyRecordingName(name), name)
        }
        for name in ["take.wav", "reference.wav", "reference-2026-09-26T14:03:07Z.wav", "reference-2026-09-26.wav",
                     "\(UUID().uuidString).m4a", "notes.txt", "reference-2026-09-26T14-03-07Z.wav.part"] {
            XCTAssertFalse(ReferenceClipRecordingStash.isLegacyRecordingName(name), name)
        }
    }

    /// The iPhone clears every earlier launch's folder: its sandbox need not
    /// report another process identifier, which would keep them all.
    func testTheIPhoneSweepRemovesEveryEarlierLaunchFolder() throws {
        let earlier = ReferenceClipRecordingOwner(bundleIdentifier: "com.patricedery.vocello", processIdentifier: 4242, startTime: 7)
        let earlierFolder = try makeFolder(of: earlier)

        ReferenceClipRecordingStash.removeLeftoverRecordings(
            anotherCopyIsRunning: false,
            root: recordings,
            currentOwner: .current,
            legacyDirectories: [],
            ownerHasEnded: { _ in true }
        )

        XCTAssertFalse(exists(earlierFolder))
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
