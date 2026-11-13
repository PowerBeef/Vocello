import Foundation
import XCTest
@testable import QwenVoiceCore

/// PA-11: the main-actor status path must never hash model files, and a file the
/// downloader just verified must not be hashed a second time.
final class LocalModelAssetStoreIntegrityTests: XCTestCase {
    private var root: URL!

    override func setUpWithError() throws {
        root = FileManager.default.temporaryDirectory
            .appendingPathComponent("integrity-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
    }

    override func tearDownWithError() throws {
        try? FileManager.default.removeItem(at: root)
    }

    /// A model whose manifest records `manifestSHA` for `weights.bin`, while the file
    /// on disk has the right size but different bytes. Only a content pass can tell.
    private func install(bytes: Data, manifestSize: Int64? = nil, manifestSHA: String, retiredFolders: [String] = [])
        throws -> (LocalModelAssetStore, ModelAssetDescriptor, URL) {
        let folder = "model-\(UUID().uuidString.prefix(8))"
        let model = ModelDescriptor(
            id: folder, name: folder, tier: "speed", folder: folder, mode: .custom,
            huggingFaceRepo: "org/model", artifactVersion: "1", iosDownloadEligible: false,
            estimatedDownloadBytes: nil, outputSubfolder: "out", requiredRelativePaths: ["weights.bin"],
            retiredFolders: retiredFolders
        )
        let descriptor = ModelAssetDescriptor(
            model: model, version: "test",
            artifacts: [ModelAssetArtifact(relativePath: "weights.bin", scope: .modelSpecific)]
        )
        let installRoot = root.appendingPathComponent(folder, isDirectory: true)
        try FileManager.default.createDirectory(at: installRoot, withIntermediateDirectories: true)
        let fileURL = installRoot.appendingPathComponent("weights.bin")
        try bytes.write(to: fileURL)
        let manifest = ModelAssetIntegrityManifest(
            repo: "org/model", revision: "rev", targetFolder: folder, createdAtUTC: "2026-09-22T00:00:00Z",
            files: [.init(path: "weights.bin", size: manifestSize ?? Int64(bytes.count), sha256: manifestSHA)]
        )
        try JSONEncoder().encode(manifest)
            .write(to: installRoot.appendingPathComponent(ModelAssetIntegrityManifest.filename))
        let store = LocalModelAssetStore(rootDirectory: root, descriptors: [descriptor])
        return (store, descriptor, fileURL)
    }

    private let otherSHA = String(repeating: "ab", count: 32)

    /// RF-59: the iPhone's launch pass removes retired folders only once a model passes the
    /// manifest-and-size check (the depth it uses: contents are the Mac's digest pass); a model
    /// without a manifest, or with a file of the wrong size, keeps them.
    func testTheLaunchReclaimWaitsForTheModelToVerify() throws {
        let retired = "Old-Custom-4bit"
        let retiredURL = root.appendingPathComponent(retired, isDirectory: true)
        try FileManager.default.createDirectory(at: retiredURL, withIntermediateDirectories: true)
        try Data("old".utf8).write(to: retiredURL.appendingPathComponent("model.safetensors"))
        // A retired download that never finished: no folder, only its staging.
        let staged = "Old-Custom-8bit"
        let staging = root.appendingPathComponent(".qwenvoice-downloads/\(staged)", isDirectory: true)
        try FileManager.default.createDirectory(at: staging, withIntermediateDirectories: true)
        try Data("partial".utf8).write(to: staging.appendingPathComponent("model.safetensors.partial"))
        let retiring = [retired, staged]
        let bytes = Data("weights".utf8)
        let none = RetiredModelReclamation(removed: [], failed: [:])

        let (wrongSize, _, _) = try install(
            bytes: bytes, manifestSize: Int64(bytes.count + 1), manifestSHA: otherSHA, retiredFolders: retiring
        )
        XCTAssertEqual(wrongSize.reclaimRetiredFolders(), none)
        XCTAssertTrue(FileManager.default.fileExists(atPath: retiredURL.path))

        let (noManifest, _, weights) = try install(bytes: bytes, manifestSHA: otherSHA, retiredFolders: retiring)
        try FileManager.default.removeItem(
            at: weights.deletingLastPathComponent().appendingPathComponent(ModelAssetIntegrityManifest.filename)
        )
        XCTAssertEqual(noManifest.reclaimRetiredFolders(), none)
        XCTAssertTrue(FileManager.default.fileExists(atPath: retiredURL.path))
        XCTAssertTrue(FileManager.default.fileExists(atPath: staging.path))

        let (verified, _, _) = try install(bytes: bytes, manifestSHA: otherSHA, retiredFolders: retiring)
        let reclaimed = verified.reclaimRetiredFolders()
        XCTAssertEqual(reclaimed.removed, retiring.sorted())
        XCTAssertEqual(reclaimed.failed, [:])
        XCTAssertEqual(reclaimed.freedBytes, Int64("old".utf8.count + "partial".utf8.count), "the files each held alone")
        XCTAssertFalse(FileManager.default.fileExists(atPath: retiredURL.path))
        XCTAssertFalse(FileManager.default.fileExists(atPath: staging.path))
        XCTAssertEqual(verified.reclaimRetiredFolders(), none, "nothing left to reclaim")
    }

    /// RF-59 (maintainer decision 2026-11-13): one verified model frees every mode's retired
    /// folders, including those of a mode whose new model was never installed.
    func testOneVerifiedModelFreesEveryModesRetiredFolders() throws {
        let custom = "Old-Custom-4bit", design = "Old-Design-8bit"
        for folder in [custom, design] {
            try FileManager.default.createDirectory(
                at: root.appendingPathComponent(folder, isDirectory: true), withIntermediateDirectories: true
            )
        }
        let (_, installedDescriptor, _) = try install(
            bytes: Data("weights".utf8), manifestSHA: otherSHA, retiredFolders: [custom]
        )
        let absent = ModelDescriptor(
            id: "design-absent", name: "design-absent", tier: "speed", folder: "design-absent", mode: .design,
            huggingFaceRepo: "org/design", artifactVersion: "1", iosDownloadEligible: false,
            estimatedDownloadBytes: nil, outputSubfolder: "out", requiredRelativePaths: ["weights.bin"],
            retiredFolders: [design]
        )
        let absentDescriptor = ModelAssetDescriptor(
            model: absent, version: "test",
            artifacts: [ModelAssetArtifact(relativePath: "weights.bin", scope: .modelSpecific)]
        )
        let none = RetiredModelReclamation(removed: [], failed: [:])
        XCTAssertEqual(LocalModelAssetStore(rootDirectory: root, descriptors: [absentDescriptor]).reclaimRetiredFolders(),
                       none, "no model verified")
        let both = LocalModelAssetStore(rootDirectory: root, descriptors: [absentDescriptor, installedDescriptor])
        XCTAssertEqual(both.reclaimRetiredFolders().removed, [custom, design])
        for folder in [custom, design] {
            XCTAssertFalse(FileManager.default.fileExists(atPath: root.appendingPathComponent(folder).path), folder)
        }
    }

    /// RF-59: a legacy 8-bit folder the contract lists as retired is left for the verified
    /// reclamation; one it does not list is cleaned up when the store opens, as before.
    func testALegacyFolderListedAsRetiredWaitsForReclamation() throws {
        let legacy = "Qwen3-TTS-12Hz-1.7B-CustomVoice-8bit"
        let source = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent()
            .deletingLastPathComponent().appendingPathComponent("Sources/Resources/qwenvoice_contract.json")
        func store(retiring: [String]) throws {
            try FileManager.default.createDirectory(
                at: root.appendingPathComponent(legacy, isDirectory: true), withIntermediateDirectories: true
            )
            var contract = try XCTUnwrap(JSONSerialization.jsonObject(with: Data(contentsOf: source)) as? [String: Any])
            var models = try XCTUnwrap(contract["models"] as? [[String: Any]])
            for index in models.indices {
                // A contract that no longer installs into the legacy folder at all.
                models[index]["folder"] = "Current-\(index)"
                models[index]["variants"] = (models[index]["variants"] as? [[String: Any]] ?? [])
                    .filter { ($0["folder"] as? String) != legacy }
                models[index]["retiredFolders"] = index == 0 ? retiring : []
            }
            contract["models"] = models
            let url = root.appendingPathComponent("contract-\(UUID().uuidString).json")
            try JSONSerialization.data(withJSONObject: contract).write(to: url)
            let registry = try ContractBackedModelRegistry(manifestURL: url)
            _ = LocalModelAssetStore(modelRegistry: registry, rootDirectory: root, storeVersionSeed: "test")
        }
        try store(retiring: [legacy])
        XCTAssertTrue(FileManager.default.fileExists(atPath: root.appendingPathComponent(legacy).path))
        try store(retiring: [])
        XCTAssertFalse(FileManager.default.fileExists(atPath: root.appendingPathComponent(legacy).path))
    }

    func testManifestSizesDepthNeverReadsContents() throws {
        let (store, descriptor, _) = try install(bytes: Data("real bytes".utf8), manifestSHA: otherSHA)
        // Same size, wrong content: the shallow depth cannot see it, which proves it did not hash.
        XCTAssertEqual(store.deepIntegrity(for: descriptor, depth: .manifestSizes), .verified(checkedFiles: 1))
        XCTAssertEqual(
            store.deepIntegrity(for: descriptor, depth: .contentDigest),
            .failed(message: "One installed model file failed deep integrity verification.",
                    failedRelativePaths: ["weights.bin"])
        )
    }

    /// E5-03: a manifest entry without a usable digest must not read as verified content.
    func testContentDepthIsUnavailableWhenTheManifestHasNoUsableDigest() throws {
        let (store, descriptor, _) = try install(bytes: Data("real bytes".utf8), manifestSHA: "not-a-digest")
        XCTAssertEqual(store.deepIntegrity(for: descriptor, depth: .manifestSizes), .verified(checkedFiles: 1))
        XCTAssertEqual(
            store.deepIntegrity(for: descriptor, depth: .contentDigest),
            .unavailable(reason: "manifest has no usable digest for a required file")
        )

        // A missing digest never hides a file that fails the checks which need none.
        let (wrongSize, wrongSizeDescriptor, _) = try install(
            bytes: Data("real bytes".utf8), manifestSize: 999, manifestSHA: "not-a-digest"
        )
        XCTAssertEqual(
            wrongSize.deepIntegrity(for: wrongSizeDescriptor, depth: .contentDigest),
            .failed(message: "One installed model file failed deep integrity verification.",
                    failedRelativePaths: ["weights.bin"])
        )
    }

    func testManifestSizesDepthPassesEvenWhenTheFileCannotBeRead() throws {
        // Stronger than a digest mismatch: an unreadable file still passes the
        // shallow depth, so it never opens file contents at all.
        let (store, descriptor, fileURL) = try install(bytes: Data("locked bytes".utf8), manifestSHA: otherSHA)
        try FileManager.default.setAttributes([.posixPermissions: 0o000], ofItemAtPath: fileURL.path)
        defer { try? FileManager.default.setAttributes([.posixPermissions: 0o644], ofItemAtPath: fileURL.path) }
        XCTAssertEqual(store.deepIntegrity(for: descriptor, depth: .manifestSizes), .verified(checkedFiles: 1))
        XCTAssertFalse(store.deepIntegrity(for: descriptor, depth: .contentDigest).isVerified)
    }

    func testManifestSizesDepthStillCatchesSizeAndManifestProblems() throws {
        let (store, descriptor, fileURL) = try install(
            bytes: Data("real bytes".utf8), manifestSize: 999, manifestSHA: otherSHA
        )
        XCTAssertFalse(store.deepIntegrity(for: descriptor, depth: .manifestSizes).isVerified)
        try FileManager.default.removeItem(at: fileURL.deletingLastPathComponent()
            .appendingPathComponent(ModelAssetIntegrityManifest.filename))
        XCTAssertEqual(store.deepIntegrity(for: descriptor, depth: .manifestSizes),
                       .unavailable(reason: "manifest unavailable"))
    }

    private func receipt(for url: URL, sha: String, modificationOffset: Int64 = 0) throws -> VerifiedArtifactReceipt {
        let attributes = try FileManager.default.attributesOfItem(atPath: url.path)
        let size = (attributes[.size] as? NSNumber)?.int64Value ?? -1
        let modified = attributes[.modificationDate] as? Date ?? .distantPast
        return VerifiedArtifactReceipt(
            relativePath: "weights.bin", artifactVersion: "1", expectedSize: size, expectedSHA256: sha,
            fileSize: size,
            modificationTimeNanoseconds: Int64(modified.timeIntervalSince1970 * 1_000_000_000) + modificationOffset,
            fileIdentifier: (attributes[.systemFileNumber] as? NSNumber)?.uint64Value,
            verificationProcessGeneration: "test"
        )
    }

    func testADownloadReceiptSeedsTheDigestSoTheFirstContentPassDoesNotHash() throws {
        // The receipt carries the manifest digest although the bytes differ: a verified
        // result can only come from the seeded cache, never from hashing the file.
        let (store, descriptor, fileURL) = try install(bytes: Data("seeded bytes".utf8), manifestSHA: otherSHA)
        XCTAssertTrue(LocalModelAssetStore.recordVerifiedDigest(for: fileURL, receipt: try receipt(for: fileURL, sha: otherSHA)))
        XCTAssertEqual(store.deepIntegrity(for: descriptor, depth: .contentDigest), .verified(checkedFiles: 1))
    }

    func testAReplacedFileWithTheSameSizeAndTimeIsNotSeeded() throws {
        // A new inode with the size and modification time restored (a replace or a
        // hard-link swap) must not inherit the old file's verified digest.
        let (store, descriptor, fileURL) = try install(bytes: Data("original!!".utf8), manifestSHA: otherSHA)
        let original = try receipt(for: fileURL, sha: otherSHA)
        let attributes = try FileManager.default.attributesOfItem(atPath: fileURL.path)
        let replacement = fileURL.deletingLastPathComponent().appendingPathComponent("replacement.bin")
        try Data("replaced!!".utf8).write(to: replacement)
        _ = try FileManager.default.replaceItemAt(fileURL, withItemAt: replacement)
        try FileManager.default.setAttributes(
            [.modificationDate: attributes[.modificationDate] as Any], ofItemAtPath: fileURL.path
        )
        XCTAssertFalse(LocalModelAssetStore.recordVerifiedDigest(for: fileURL, receipt: original))
        XCTAssertFalse(store.deepIntegrity(for: descriptor, depth: .contentDigest).isVerified)
    }

    func testAStaleReceiptIsNotRecorded() throws {
        let (store, descriptor, fileURL) = try install(bytes: Data("changed bytes".utf8), manifestSHA: otherSHA)
        let stale = try receipt(for: fileURL, sha: otherSHA, modificationOffset: 1_000_000_000)
        XCTAssertFalse(LocalModelAssetStore.recordVerifiedDigest(for: fileURL, receipt: stale))
        XCTAssertFalse(store.deepIntegrity(for: descriptor, depth: .contentDigest).isVerified)
    }
}
