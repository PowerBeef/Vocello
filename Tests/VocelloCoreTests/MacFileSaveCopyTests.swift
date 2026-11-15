import XCTest

final class MacFileSaveCopyTests: XCTestCase {
    private var root: URL!

    override func setUpWithError() throws {
        root = FileManager.default.temporaryDirectory
            .appendingPathComponent("MacFileSaveCopyTests-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
    }

    override func tearDownWithError() throws {
        try? FileManager.default.removeItem(at: root)
    }

    private func write(_ name: String, _ contents: String) throws -> URL {
        let url = root.appendingPathComponent(name)
        try Data(contents.utf8).write(to: url)
        return url
    }

    private func contents(_ url: URL) throws -> String {
        String(decoding: try Data(contentsOf: url), as: UTF8.self)
    }

    func testSavingATakeOntoItselfKeepsIt() throws {
        let take = try write("take.wav", "take-bytes")
        XCTAssertEqual(try MacFileSaveCopy.copy(from: take, to: take), .sameFile)
        XCTAssertEqual(try contents(take), "take-bytes")
    }

    func testAPathThroughASymlinkOrDotDotIsTheSameFile() throws {
        let take = try write("take.wav", "take-bytes")
        let alias = root.appendingPathComponent("alias", isDirectory: true)
        try FileManager.default.createSymbolicLink(at: alias, withDestinationURL: root)
        XCTAssertEqual(try MacFileSaveCopy.copy(from: take, to: alias.appendingPathComponent("take.wav")), .sameFile)
        let dotted = root.appendingPathComponent("sub/../take.wav")
        XCTAssertEqual(try MacFileSaveCopy.copy(from: take, to: dotted), .sameFile)
        XCTAssertEqual(try contents(take), "take-bytes")
    }

    func testAHardLinkToTheTakeIsTheSameFile() throws {
        let take = try write("take.wav", "take-bytes")
        let link = root.appendingPathComponent("link.wav")
        try FileManager.default.linkItem(at: take, to: link)
        XCTAssertEqual(try MacFileSaveCopy.copy(from: take, to: link), .sameFile)
        XCTAssertEqual(try contents(take), "take-bytes")
    }

    func testANewDestinationReceivesTheBytes() throws {
        let take = try write("take.wav", "take-bytes")
        let destination = root.appendingPathComponent("export.wav")
        XCTAssertEqual(try MacFileSaveCopy.copy(from: take, to: destination), .copied)
        XCTAssertEqual(try contents(destination), "take-bytes")
        XCTAssertEqual(try contents(take), "take-bytes")
    }

    func testAnExistingDifferentFileIsReplaced() throws {
        let take = try write("take.wav", "take-bytes")
        let destination = try write("export.wav", "old-bytes")
        XCTAssertEqual(try MacFileSaveCopy.copy(from: take, to: destination), .copied)
        XCTAssertEqual(try contents(destination), "take-bytes")
        XCTAssertEqual(try contents(take), "take-bytes")
    }

    func testAFailedCopyLeavesTheExistingDestinationAndNoStagingFile() throws {
        let missing = root.appendingPathComponent("missing.wav")
        let destination = try write("export.wav", "old-bytes")
        XCTAssertThrowsError(try MacFileSaveCopy.copy(from: missing, to: destination))
        XCTAssertEqual(try contents(destination), "old-bytes")
        let leftovers = try FileManager.default.contentsOfDirectory(atPath: root.path)
            .filter { $0.contains("vocello-save") }
        XCTAssertEqual(leftovers, [])
    }

    // MARK: - Recovery export

    private func makeFolder(_ name: String) throws -> URL {
        let url = root.appendingPathComponent(name, isDirectory: true)
        try FileManager.default.createDirectory(at: url, withIntermediateDirectories: true)
        return url
    }

    func testTheRecoveryExportCountsTheFilesItCouldNotCopy() throws {
        let sources = try makeFolder("pending")
        let destination = try makeFolder("exported")
        let first = sources.appendingPathComponent("first.wav")
        let second = sources.appendingPathComponent("second.wav")
        try Data("first-bytes".utf8).write(to: first)
        try Data("second-bytes".utf8).write(to: second)
        let missing = sources.appendingPathComponent("missing.wav")
        let alsoMissing = sources.appendingPathComponent("also-missing.wav")

        XCTAssertEqual(MacRecoveryAudioExport.copy([first, missing, second, alsoMissing], into: destination), 2)
        XCTAssertEqual(try contents(destination.appendingPathComponent("first.wav")), "first-bytes")
        XCTAssertEqual(try contents(destination.appendingPathComponent("second.wav")), "second-bytes")
        XCTAssertEqual(try FileManager.default.contentsOfDirectory(atPath: destination.path).sorted(), [
            "first.wav", "second.wav",
        ])

        XCTAssertEqual(MacRecoveryAudioExport.copy([], into: destination), 0)
        XCTAssertEqual(
            MacRecoveryAudioExport.copy([first], into: root.appendingPathComponent("no-such-folder")), 1,
            "A folder that is gone fails every copy"
        )
    }

    /// A name the folder already holds is kept; the new copy lands beside it.
    /// That is why two exports running at once doubled every file, and why
    /// the app runs one at a time (`MacFileCopyActivity`).
    func testTheRecoveryExportNeverOverwritesAFileTheFolderHolds() throws {
        let sources = try makeFolder("pending")
        let destination = try makeFolder("exported")
        let take = sources.appendingPathComponent("take.wav")
        try Data("new-bytes".utf8).write(to: take)
        let existing = destination.appendingPathComponent("take.wav")
        try Data("old-bytes".utf8).write(to: existing)

        XCTAssertEqual(MacRecoveryAudioExport.copy([take], into: destination), 0)

        XCTAssertEqual(try contents(existing), "old-bytes")
        let names = try FileManager.default.contentsOfDirectory(atPath: destination.path).filter { $0 != "take.wav" }
        XCTAssertEqual(names.count, 1)
        let added = try XCTUnwrap(names.first)
        XCTAssertTrue(added.hasPrefix("take-") && added.hasSuffix(".wav"), added)
        XCTAssertEqual(try contents(destination.appendingPathComponent(added)), "new-bytes")
    }

    /// A take an earlier build named after its script is exported under the
    /// neutral name (SEC-1).
    func testTheRecoveryExportNamesACopyWithoutTheScriptSnippet() throws {
        let sources = try makeFolder("pending")
        let destination = try makeFolder("exported")
        let take = sources.appendingPathComponent("20260926_14-03-07-512_a-private-line.wav")
        try Data("take-bytes".utf8).write(to: take)

        XCTAssertEqual(MacRecoveryAudioExport.copy([take], into: destination), 0)

        XCTAssertEqual(
            try FileManager.default.contentsOfDirectory(atPath: destination.path),
            [GenerationOutputFileName.exportName(forTakeNamed: take.lastPathComponent)]
        )
        XCTAssertFalse(try FileManager.default.contentsOfDirectory(atPath: destination.path)[0].contains("private"))
    }

    // MARK: - One copy at a time

    func testASecondCopyCannotStartWhileOneIsInFlight() {
        var activity = MacFileCopyActivity()
        XCTAssertFalse(activity.isCopying)

        XCTAssertTrue(activity.begin(), "The first copy starts")
        XCTAssertTrue(activity.isCopying)
        XCTAssertFalse(activity.begin(), "A second is refused while the first runs")
        XCTAssertFalse(activity.begin(), "And refused again")
        XCTAssertTrue(activity.isCopying, "A refused start changes nothing")

        activity.finish(nil)
        XCTAssertFalse(activity.isCopying)
        XCTAssertNil(activity.failure, "A copy that succeeded, or a cancelled panel, reports nothing")
        XCTAssertTrue(activity.begin(), "The next copy starts once the first ended")
    }

    /// The failure outlives the copy: it stays until the user acknowledges
    /// it, wherever they are by then, and a later clean copy does not drop it.
    func testAFailedCopyKeepsItsFailureUntilItIsAcknowledged() {
        var activity = MacFileCopyActivity()
        XCTAssertTrue(activity.begin())
        activity.finish(.saveAs("disk full"))
        XCTAssertFalse(activity.isCopying)
        XCTAssertEqual(activity.failure, .saveAs("disk full"))

        XCTAssertTrue(activity.begin(), "A failure does not block the next copy")
        XCTAssertEqual(activity.failure, .saveAs("disk full"))
        activity.finish(nil)
        XCTAssertEqual(activity.failure, .saveAs("disk full"), "Still to be acknowledged")

        activity.acknowledgeFailure()
        XCTAssertNil(activity.failure)
        XCTAssertEqual(activity, MacFileCopyActivity())
    }

    /// The recovery export reports a failure only when a file was not copied,
    /// and carries the count its message names.
    func testTheRecoveryExportFailsOnlyWhenAFileWasNotCopied() {
        XCTAssertNil(MacFileCopyActivity.Failure.afterRecoveryExport(failures: 0))
        XCTAssertEqual(MacFileCopyActivity.Failure.afterRecoveryExport(failures: 1), .recoveryExport(failedCount: 1))
        XCTAssertEqual(MacFileCopyActivity.Failure.afterRecoveryExport(failures: 3), .recoveryExport(failedCount: 3))

        var activity = MacFileCopyActivity()
        XCTAssertTrue(activity.begin())
        activity.finish(MacFileCopyActivity.Failure.afterRecoveryExport(failures: 0))
        XCTAssertNil(activity.failure)
        XCTAssertTrue(activity.begin())
        activity.finish(MacFileCopyActivity.Failure.afterRecoveryExport(failures: 2))
        XCTAssertEqual(activity.failure, .recoveryExport(failedCount: 2))
    }
}
