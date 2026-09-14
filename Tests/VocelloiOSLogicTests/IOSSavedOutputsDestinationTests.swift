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
