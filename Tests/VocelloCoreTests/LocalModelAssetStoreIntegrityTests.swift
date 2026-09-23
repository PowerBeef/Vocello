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
    private func install(bytes: Data, manifestSize: Int64? = nil, manifestSHA: String)
        throws -> (LocalModelAssetStore, ModelAssetDescriptor, URL) {
        let folder = "model-\(UUID().uuidString.prefix(8))"
        let model = ModelDescriptor(
            id: folder, name: folder, tier: "speed", folder: folder, mode: .custom,
            huggingFaceRepo: "org/model", artifactVersion: "1", iosDownloadEligible: false,
            estimatedDownloadBytes: nil, outputSubfolder: "out", requiredRelativePaths: ["weights.bin"]
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
