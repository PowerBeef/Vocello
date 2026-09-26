import Foundation
@testable import QwenVoiceCore
import XCTest

/// CORE-15: what a crash or jetsam kill strands mid-write is swept at engine
/// start, once untouched for an hour; live work and finished files never are.
final class EngineStartupSweepTests: XCTestCase {
    private var root: URL!

    override func setUpWithError() throws {
        root = FileManager.default.temporaryDirectory
            .appendingPathComponent("EngineStartupSweepTests-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
    }

    override func tearDownWithError() throws {
        try? FileManager.default.removeItem(at: root)
    }

    private let stale = Date().addingTimeInterval(-2 * 3600)

    private func exists(_ url: URL) -> Bool {
        FileManager.default.fileExists(atPath: url.path)
    }

    @discardableResult
    private func file(_ url: URL, modified: Date? = nil) throws -> URL {
        try FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
        try Data("audio".utf8).write(to: url)
        if let modified {
            try FileManager.default.setAttributes([.modificationDate: modified], ofItemAtPath: url.path)
        }
        return url
    }

    // MARK: - Take staging files under outputs/

    func testStagingNamesAreTheOnesTheAtomicPublisherWrites() {
        let uuid = UUID().uuidString
        for name in [".take.\(uuid).tmp.wav", ".take.\(uuid).tmp", ".My take 2.\(uuid).tmp.wav"] {
            XCTAssertTrue(GenerationOutputStagingSweep.isStagingFileName(name), name)
        }
        for name in ["take.wav", ".take.wav", ".DS_Store", ".\(uuid).tmp.wav", ".take.not-a-uuid.tmp.wav",
                     "take.\(uuid).tmp.wav", ".take.\(uuid).tmp.wav.part", ".take.converting-\(uuid).wav"] {
            XCTAssertFalse(GenerationOutputStagingSweep.isStagingFileName(name), name)
        }
    }

    func testAbandonedStagingFilesGoAndEverythingElseStays() throws {
        let outputs = root.appendingPathComponent("outputs", isDirectory: true)
        let clones = outputs.appendingPathComponent("Clones", isDirectory: true)
        let abandoned = try file(clones.appendingPathComponent(".take.\(UUID().uuidString).tmp.wav"), modified: stale)
        let nested = try file(
            outputs.appendingPathComponent("long-form/project/.joined.\(UUID().uuidString).tmp.wav"),
            modified: stale
        )
        let live = try file(clones.appendingPathComponent(".next.\(UUID().uuidString).tmp.wav"))
        let finished = try file(clones.appendingPathComponent("take.wav"), modified: stale)
        let hidden = try file(clones.appendingPathComponent(".DS_Store"), modified: stale)

        GenerationOutputStagingSweep.removeAbandonedStagingFiles(under: outputs)

        XCTAssertFalse(exists(abandoned))
        XCTAssertFalse(exists(nested), "Staging deeper in the tree goes too")
        XCTAssertTrue(exists(live), "A writer still touching its staging file keeps it")
        XCTAssertTrue(exists(finished), "A published take is never swept")
        XCTAssertTrue(exists(hidden))
    }

    func testAMissingOutputsFolderIsNotAnError() {
        GenerationOutputStagingSweep.removeAbandonedStagingFiles(
            under: root.appendingPathComponent("outputs", isDirectory: true)
        )
    }

    // MARK: - Prepared-model overlay rebuilds

    func testInterruptedOverlayRebuildsGoAndOverlaysStay() throws {
        let models = root.appendingPathComponent("models", isDirectory: true)
        try FileManager.default.createDirectory(at: models, withIntermediateDirectories: true)
        let overlays = NativeRuntimePaths.rooted(at: root).hubCacheDirectory
            .appendingPathComponent(PreparedModelOverlay.cacheSubdirectoryName, isDirectory: true)
        let overlay = overlays.appendingPathComponent("Qwen3-TTS-Speed", isDirectory: true)
        let abandoned = overlays.appendingPathComponent("Qwen3-TTS-Speed.tmp.\(UUID().uuidString)", isDirectory: true)
        let live = overlays.appendingPathComponent("Qwen3-TTS-Quality.tmp.\(UUID().uuidString)", isDirectory: true)
        let target = try file(models.appendingPathComponent("Qwen3-TTS-Speed/model.safetensors"))
        for folder in [overlay, abandoned, live] {
            try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
            try FileManager.default.createSymbolicLink(
                at: folder.appendingPathComponent("model.safetensors"),
                withDestinationURL: target
            )
        }
        for folder in [overlay, abandoned] {
            try FileManager.default.setAttributes([.modificationDate: stale], ofItemAtPath: folder.path)
        }

        PreparedModelOverlay.removeAbandonedRebuilds(modelsRoot: models)

        XCTAssertFalse(exists(abandoned))
        XCTAssertTrue(exists(live), "A rebuild in progress is left alone")
        XCTAssertTrue(exists(overlay), "A completed overlay is never swept")
        XCTAssertTrue(exists(target), "The symlinks are unlinked, never followed")
    }

    func testRebuildNamesNeedAFolderAndAUUID() {
        XCTAssertTrue(PreparedModelOverlay.isRebuildName("Qwen3-TTS-Speed.tmp.\(UUID().uuidString)"))
        for name in ["Qwen3-TTS-Speed", ".tmp.\(UUID().uuidString)", "Qwen3-TTS-Speed.tmp.later", "Qwen3.tmp"] {
            XCTAssertFalse(PreparedModelOverlay.isRebuildName(name), name)
        }
    }

    // MARK: - Saved-voice enrollment conversions

    func testAnInterruptedSavedVoiceConversionIsSweptWithTheConversionTemporaries() throws {
        let directory = root.appendingPathComponent("normalized", isDirectory: true)
        let abandoned = try file(
            directory.appendingPathComponent("\(MLXTTSEngine.savedVoiceConversionPrefix)\(UUID().uuidString).wav"),
            modified: stale
        )
        let live = try file(
            directory.appendingPathComponent("\(MLXTTSEngine.savedVoiceConversionPrefix)\(UUID().uuidString).wav")
        )
        // A normalized reference whose source happened to carry the prefix.
        let reference = try file(
            directory.appendingPathComponent("\(MLXTTSEngine.savedVoiceConversionPrefix)\(UUID().uuidString)_0123abcd.wav"),
            modified: stale
        )

        MLXTTSEngine.sweepAbandonedConversionTemporaries(in: directory)

        XCTAssertFalse(exists(abandoned))
        XCTAssertTrue(exists(live))
        XCTAssertTrue(exists(reference), "A normalized reference is never swept")
    }
}
