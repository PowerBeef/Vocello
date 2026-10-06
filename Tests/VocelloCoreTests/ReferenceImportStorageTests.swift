@preconcurrency import AVFoundation
import Foundation
@testable import QwenVoiceCore
import XCTest

/// PA-26 B2: importing a reference (CORE-16, CORE-17) and storing a saved voice
/// whose format the store does not name (MAC-09).
final class ReferenceImportStorageTests: XCTestCase {
    private var root: URL!

    override func setUpWithError() throws {
        root = FileManager.default.temporaryDirectory
            .appendingPathComponent("ReferenceImportStorageTests-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
    }

    override func tearDownWithError() throws {
        try? FileManager.default.removeItem(at: root)
    }

    private func exists(_ url: URL) -> Bool {
        FileManager.default.fileExists(atPath: url.path)
    }

    // MARK: - LocalDocumentIO

    /// A conversion failure reaches the enrollment UI as its typed, path-free
    /// copy, never as English text carrying the user's source path.
    func testASavedVoiceConversionFailureShowsNoPath() {
        let path = "/Users/example/Private Folder/reference.flac"
        let presentation = VocelloPresentationText()
        for error in [
            AudioPreparationError.failedToReadAudio(path),
            AudioPreparationError.missingInputFile(path),
            AudioPreparationError.inputFileTooLarge(path: path, maxBytes: 1, actualBytes: 2),
        ] {
            let message = presentation.savedVoiceErrorMessage(error)
            XCTAssertFalse(message.contains("Private Folder"), message)
            XCTAssertEqual(message, presentation.generationFailureMessage(error))
        }
        XCTAssertEqual(
            presentation.savedVoiceErrorMessage(TTSEngineError.savedVoiceStoreBusy),
            presentation.savedVoicesStoreBusy
        )
    }

    func testTheDefaultCapIsWhatAudioPreparationAccepts() {
        XCTAssertEqual(
            LocalDocumentIO(importedReferenceDirectory: root).maximumReferenceBytes,
            AudioPreparationLimits.defaults.maxInputFileSizeBytes
        )
    }

    func testAnOversizedReferenceIsRefusedBeforeAnythingIsCopied() throws {
        let source = root.appendingPathComponent("long.wav")
        try Data(count: 2_048).write(to: source)
        let imported = root.appendingPathComponent("imported", isDirectory: true)
        let documentIO = LocalDocumentIO(importedReferenceDirectory: imported, maximumReferenceBytes: 1_024)

        XCTAssertThrowsError(try documentIO.importReferenceAudio(from: source)) { error in
            XCTAssertEqual(error as? DocumentIOError, .referenceTooLarge(maxBytes: 1_024, actualBytes: 2_048))
            XCTAssertEqual(
                GenerationFailurePresentationReason(error),
                .referenceAudioTooLong,
                "The interface names the limit, not a storage failure"
            )
        }
        XCTAssertFalse(exists(imported), "Nothing is copied")
    }

    func testAReadableSidecarIsImportedWithTheAudio() throws {
        let source = root.appendingPathComponent("voice.wav")
        try Data("audio".utf8).write(to: source)
        try "Hello there.".write(to: root.appendingPathComponent("voice.txt"), atomically: true, encoding: .utf8)

        let imported = try LocalDocumentIO(importedReferenceDirectory: root.appendingPathComponent("imported"))
            .importReferenceAudio(from: source)

        let sidecar = try XCTUnwrap(imported.transcriptSidecarURL)
        XCTAssertEqual(try String(contentsOf: sidecar, encoding: .utf8), "Hello there.")
    }

    /// CORE-17: a Files picker grants the chosen audio alone, so a sibling
    /// transcript can be listed but not read.
    func testAnUnreadableSidecarNeitherFailsTheImportNorLeavesAStaleCopy() throws {
        try XCTSkipIf(getuid() == 0, "The superuser reads any file")
        let source = root.appendingPathComponent("voice.wav")
        try Data("audio".utf8).write(to: source)
        let sourceSidecar = root.appendingPathComponent("voice.txt")
        try "Hello there.".write(to: sourceSidecar, atomically: true, encoding: .utf8)
        let documentIO = LocalDocumentIO(importedReferenceDirectory: root.appendingPathComponent("imported"))
        let first = try documentIO.importReferenceAudio(from: source)
        let copiedSidecar = try XCTUnwrap(first.transcriptSidecarURL)

        try FileManager.default.setAttributes([.posixPermissions: 0], ofItemAtPath: sourceSidecar.path)
        defer { try? FileManager.default.setAttributes([.posixPermissions: 0o644], ofItemAtPath: sourceSidecar.path) }
        let second = try documentIO.importReferenceAudio(from: source)

        XCTAssertEqual(second.materializedURL, first.materializedURL)
        XCTAssertTrue(exists(second.materializedURL), "The audio still imports")
        XCTAssertNil(second.transcriptSidecarPath)
        XCTAssertFalse(exists(copiedSidecar), "An earlier copy of the sidecar is not presented as this import's")
    }

    /// A3-02: re-importing the same unchanged file maps to the same
    /// materialized name, which a review may still be reading. A copy that
    /// fails keeps the earlier materialization and leaves no staging file.
    func testAFailedReimportKeepsTheEarlierMaterialization() throws {
        try XCTSkipIf(getuid() == 0, "The superuser reads any file")
        let source = root.appendingPathComponent("voice.m4a")
        try Data("audio".utf8).write(to: source)
        let imported = root.appendingPathComponent("imported", isDirectory: true)
        let documentIO = LocalDocumentIO(importedReferenceDirectory: imported)
        let first = try documentIO.importReferenceAudio(from: source)

        // Permissions change the inode's change time, not the fingerprinted
        // size or modification time, so the re-import targets the same name.
        try FileManager.default.setAttributes([.posixPermissions: 0], ofItemAtPath: source.path)
        defer { try? FileManager.default.setAttributes([.posixPermissions: 0o644], ofItemAtPath: source.path) }
        XCTAssertThrowsError(try documentIO.importReferenceAudio(from: source)) { error in
            XCTAssertEqual(error as? DocumentIOError, .failedToCopy(first.materializedPath))
        }

        XCTAssertEqual(try Data(contentsOf: first.materializedURL), Data("audio".utf8))
        XCTAssertEqual(
            try FileManager.default.contentsOfDirectory(atPath: imported.path),
            [first.materializedURL.lastPathComponent]
        )
    }

    /// A3-02: an export whose copy fails leaves an existing destination as it
    /// was; one that succeeds replaces it whole.
    func testAFailedExportKeepsTheExistingDestination() throws {
        try XCTSkipIf(getuid() == 0, "The superuser reads any file")
        let source = root.appendingPathComponent("take.wav")
        try Data("new take".utf8).write(to: source)
        let exports = root.appendingPathComponent("exports", isDirectory: true)
        try FileManager.default.createDirectory(at: exports, withIntermediateDirectories: true)
        let destination = exports.appendingPathComponent("take.wav")
        try Data("earlier export".utf8).write(to: destination)
        let documentIO = LocalDocumentIO(importedReferenceDirectory: root.appendingPathComponent("imported"))

        try FileManager.default.setAttributes([.posixPermissions: 0], ofItemAtPath: source.path)
        XCTAssertThrowsError(try documentIO.exportGeneratedAudio(from: source, to: destination))
        try FileManager.default.setAttributes([.posixPermissions: 0o644], ofItemAtPath: source.path)
        XCTAssertEqual(try Data(contentsOf: destination), Data("earlier export".utf8))

        _ = try documentIO.exportGeneratedAudio(from: source, to: destination)
        XCTAssertEqual(try Data(contentsOf: destination), Data("new take".utf8))
        XCTAssertEqual(try FileManager.default.contentsOfDirectory(atPath: exports.path), ["take.wav"])
    }

    // MARK: - Saved voices in formats the store does not name (MAC-09)

    func testOnlyFormatsTheStoreDoesNotNameAreConverted() {
        let directory = root.appendingPathComponent("normalized", isDirectory: true)
        for name in ["voice.wav", "voice.MP3", "voice.aiff", "voice.m4a"] {
            XCTAssertNil(MLXTTSEngine.savedVoiceConversionURL(for: root.appendingPathComponent(name), in: directory), name)
        }
        for name in ["voice.flac", "voice.ogg", "voice.aif", "voice.caf", "voice"] {
            let target = MLXTTSEngine.savedVoiceConversionURL(for: root.appendingPathComponent(name), in: directory)
            XCTAssertEqual(target?.pathExtension, "wav", name)
            XCTAssertEqual(target?.deletingLastPathComponent().standardizedFileURL, directory.standardizedFileURL, name)
            XCTAssertTrue(MLXTTSEngine.isSavedVoiceConversionName(target?.lastPathComponent ?? ""), name)
        }
    }

    @MainActor
    func testANonWAVEnrollmentIsStoredAsRealWAV() async throws {
        let engine = try makeEngine()
        defer { engine.stop() }
        try await engine.initialize(appSupportDirectory: root)
        let source = root.appendingPathComponent("Reference.caf")
        try Self.writeTone(to: source, sampleRate: 44_100, seconds: 11)

        let candidate = try await engine.preparePreparedVoiceCandidate(
            name: "CafVoice",
            audioPath: source.path,
            transcript: nil,
            replacingVoiceID: nil
        )
        XCTAssertEqual(candidate.qualityWarnings, [], "The converted clip reads as an 11 s reference")
        let voice = try await engine.commitPreparedVoiceCandidate(id: candidate.id)

        XCTAssertEqual(voice.audioURL.pathExtension, "wav")
        let bytes = try Data(contentsOf: voice.audioURL)
        XCTAssertEqual(String(decoding: bytes.prefix(4), as: UTF8.self), "RIFF", "WAV bytes, not CAF, under the .wav name")
        XCTAssertEqual(String(decoding: bytes.dropFirst(8).prefix(4), as: UTF8.self), "WAVE")
        XCTAssertTrue(exists(source), "The chosen file is left as it was")
        let conversions = try FileManager.default
            .contentsOfDirectory(atPath: MLXTTSEngine.normalizedCloneReferenceDirectory(in: root).path)
            .filter(MLXTTSEngine.isSavedVoiceConversionName)
        XCTAssertEqual(conversions, [], "The transient conversion is removed once the candidate holds its copy")

        let listed = try await engine.listPreparedVoices()
        XCTAssertEqual(listed.map(\.name), ["CafVoice"])
        XCTAssertEqual(listed.first?.qualityWarnings, [])
    }

    // MARK: - Fixtures

    @MainActor
    private func makeEngine() throws -> MLXTTSEngine {
        let repositoryRoot = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
        return MLXTTSEngine(
            modelRegistry: try ContractBackedModelRegistry(
                manifestURL: repositoryRoot.appendingPathComponent("Sources/Resources/qwenvoice_contract.json")
            ),
            modelAssetStore: LocalModelAssetStore(
                rootDirectory: root.appendingPathComponent("models", isDirectory: true),
                descriptors: []
            ),
            audioPreparationService: NativeAudioPreparationService(),
            documentIO: LocalDocumentIO(
                importedReferenceDirectory: root.appendingPathComponent("imported", isDirectory: true)
            ),
            streamSessionsDirectory: root.appendingPathComponent("streams", isDirectory: true),
            loadCoordinator: ResidentLoadCoordinator(),
            streamingSessionFactory: { _, _, _, _, _, _, _, _, _, _, _, _, _, _, _, _, _, _, _, _, _ in
                fatalError("This test never starts a generation.")
            },
            idleUnloadDelayOverride: nil,
            // Stay off MLX: this bundle runs under the ThreadSanitizer lane.
            allocatorControl: .inert
        )
    }

    private static func writeTone(to url: URL, sampleRate: Double, seconds: Double) throws {
        let settings: [String: Any] = [
            AVFormatIDKey: Int(kAudioFormatLinearPCM),
            AVSampleRateKey: sampleRate,
            AVNumberOfChannelsKey: 1,
            AVLinearPCMBitDepthKey: 16,
            AVLinearPCMIsBigEndianKey: false,
            AVLinearPCMIsFloatKey: false,
        ]
        let file = try AVAudioFile(forWriting: url, settings: settings)
        let frames = AVAudioFrameCount(sampleRate * seconds)
        guard let buffer = AVAudioPCMBuffer(pcmFormat: file.processingFormat, frameCapacity: frames),
              let channel = buffer.floatChannelData?.pointee else {
            throw CocoaError(.fileWriteUnknown)
        }
        buffer.frameLength = frames
        for index in 0..<Int(frames) {
            channel[index] = Float(0.2 * sin(2.0 * .pi * 220.0 * Double(index) / sampleRate))
        }
        try file.write(from: buffer)
    }
}
