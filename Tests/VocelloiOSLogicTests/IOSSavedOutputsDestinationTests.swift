import XCTest
import QwenVoiceCore

/// The automatic "Saved outputs" folder copy is an outward export surface: it
/// must consult the export policy with the saved row's mode and never move a
/// locked Design/Clone clip out of the app.
@MainActor
final class IOSSavedOutputsDestinationTests: XCTestCase {
    private var root: URL!
    private var folder: URL!

    override func setUp() async throws {
        root = FileManager.default.temporaryDirectory
            .appendingPathComponent("saved-outputs-\(UUID().uuidString)", isDirectory: true)
        folder = root.appendingPathComponent("Saved", isDirectory: true)
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        IOSSavedOutputsDestination.clearFolder()
    }

    override func tearDown() async throws {
        IOSSavedOutputsDestination.clearFolder()
        try? FileManager.default.removeItem(at: root)
    }

    private func clip(_ name: String) throws -> URL {
        let url = root.appendingPathComponent(name)
        try Data(repeating: 0x42, count: 512).write(to: url)
        return url
    }

    func testLockedPremiumClipStaysInsideTheAppAndPermittedClipsAreCopied() async throws {
        try IOSSavedOutputsDestination.setFolder(folder)
        XCTAssertTrue(IOSSavedOutputsDestination.hasExternalFolder)
        let design = try clip("design_take.wav")
        let locked = IOSSavedOutputsDestination.exportIfConfigured(
            internalAudioPath: design.path, generationMode: "design"
        ) { IOSExportAccessPolicy.permits([$0], unlocked: false) }
        XCTAssertNil(locked, "a locked Design clip must not start a copy")
        XCTAssertFalse(FileManager.default.fileExists(atPath: folder.appendingPathComponent("design_take.wav").path))

        let builtIn = try clip("custom_take.wav")
        let free = IOSSavedOutputsDestination.exportIfConfigured(
            internalAudioPath: builtIn.path, generationMode: "custom"
        ) { IOSExportAccessPolicy.permits([$0], unlocked: false) }
        let freeTask = try XCTUnwrap(free, "a Built-in clip copies without the unlock")
        let freeCopied = await freeTask.value
        XCTAssertTrue(freeCopied)
        XCTAssertTrue(FileManager.default.fileExists(atPath: folder.appendingPathComponent("custom_take.wav").path))

        let unlocked = IOSSavedOutputsDestination.exportIfConfigured(
            internalAudioPath: design.path, generationMode: "design"
        ) { IOSExportAccessPolicy.permits([$0], unlocked: true) }
        let unlockedTask = try XCTUnwrap(unlocked, "an unlocked Design clip copies")
        let unlockedCopied = await unlockedTask.value
        XCTAssertTrue(unlockedCopied)
        XCTAssertTrue(FileManager.default.fileExists(atPath: folder.appendingPathComponent("design_take.wav").path))
    }

    func testNoFolderMeansNoCopyEvenWhenPermitted() throws {
        XCTAssertFalse(IOSSavedOutputsDestination.hasExternalFolder)
        let builtIn = try clip("custom_take.wav")
        XCTAssertNil(IOSSavedOutputsDestination.exportIfConfigured(
            internalAudioPath: builtIn.path, generationMode: "custom"
        ) { _ in true })
    }

    /// IOS-25: a copy that cannot land is recorded for the Settings row
    /// instead of disappearing, and the next copy that lands clears it, as
    /// choosing or clearing the folder does.
    func testAFailedCopyIsRecordedUntilACopyLandsOrTheFolderChanges() async throws {
        try IOSSavedOutputsDestination.setFolder(folder)
        XCTAssertNil(IOSSavedOutputsDestination.exportIssue)
        let take = try clip("custom_take.wav")

        try FileManager.default.setAttributes([.posixPermissions: 0o555], ofItemAtPath: folder.path)
        let refused = try XCTUnwrap(IOSSavedOutputsDestination.exportIfConfigured(
            internalAudioPath: take.path, generationMode: "custom"
        ) { _ in true })
        let refusedCopied = await refused.value
        try FileManager.default.setAttributes([.posixPermissions: 0o755], ofItemAtPath: folder.path)
        XCTAssertFalse(refusedCopied)
        XCTAssertEqual(IOSSavedOutputsDestination.exportIssue, .copyFailed)

        let landed = try XCTUnwrap(IOSSavedOutputsDestination.exportIfConfigured(
            internalAudioPath: take.path, generationMode: "custom"
        ) { _ in true })
        let landedCopied = await landed.value
        XCTAssertTrue(landedCopied)
        XCTAssertNil(IOSSavedOutputsDestination.exportIssue, "a copy that lands clears the issue")

        try FileManager.default.setAttributes([.posixPermissions: 0o555], ofItemAtPath: folder.path)
        let refusedAgain = try XCTUnwrap(IOSSavedOutputsDestination.exportIfConfigured(
            internalAudioPath: take.path, generationMode: "custom"
        ) { _ in true })
        _ = await refusedAgain.value
        try FileManager.default.setAttributes([.posixPermissions: 0o755], ofItemAtPath: folder.path)
        XCTAssertEqual(IOSSavedOutputsDestination.exportIssue, .copyFailed)
        try IOSSavedOutputsDestination.setFolder(folder)
        XCTAssertNil(IOSSavedOutputsDestination.exportIssue, "choosing the folder again clears the issue")
    }

    /// IOS-25: a folder that went away is reported, not skipped in silence;
    /// clearing the folder ends the report.
    func testAFolderThatWentAwayIsRecorded() async throws {
        try IOSSavedOutputsDestination.setFolder(folder)
        try FileManager.default.removeItem(at: folder)
        let take = try clip("custom_take.wav")
        let copy = IOSSavedOutputsDestination.exportIfConfigured(
            internalAudioPath: take.path, generationMode: "custom"
        ) { _ in true }
        if let copy {
            // The bookmark still resolved to the old place; the copy cannot land there.
            let copied = await copy.value
            XCTAssertFalse(copied)
            XCTAssertEqual(IOSSavedOutputsDestination.exportIssue, .copyFailed)
        } else {
            XCTAssertEqual(IOSSavedOutputsDestination.exportIssue, .folderUnavailable)
        }
        IOSSavedOutputsDestination.clearFolder()
        XCTAssertNil(IOSSavedOutputsDestination.exportIssue)
    }

    func testPolicySeesTheSavedRowsModeNotAnyCurrentSelection() throws {
        try IOSSavedOutputsDestination.setFolder(folder)
        var seen: [IOSExportProvenance] = []
        for (mode, expected) in [("custom", IOSExportProvenance.builtIn), ("clone", .generatedPremium),
                                 ("Design", .generatedPremium), ("weird", .unknown)] {
            let clip = try clip("\(mode).wav")
            _ = IOSSavedOutputsDestination.exportIfConfigured(internalAudioPath: clip.path, generationMode: mode) {
                seen.append($0)
                return false
            }
            XCTAssertEqual(seen.last, expected, mode)
        }
        XCTAssertEqual(seen.count, 4)
    }
}
