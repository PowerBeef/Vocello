import Foundation
import QwenVoiceCore

/// Model install state the way the Mac app judges it, and full-content
/// verification against the authenticated catalog.
public enum DesktopModelInventory {
    /// Complete as the app's `ModelManagerViewModel.localModelInfo` decides:
    /// every required file present and the install's integrity manifest
    /// agreeing on their sizes (a manifest the store cannot read fails nothing,
    /// as in the app).
    public static func isComplete(_ descriptor: ModelDescriptor, modelsDirectory: URL) -> Bool {
        let folder = descriptor.installDirectory(in: modelsDirectory)
        let fileManager = FileManager.default
        guard fileManager.fileExists(atPath: folder.path),
              descriptor.requiredRelativePaths.allSatisfy({
                  fileManager.fileExists(atPath: folder.appendingPathComponent($0).path)
              }) else { return false }
        let asset = ModelAssetDescriptor(
            model: descriptor, version: "status",
            artifacts: descriptor.requiredRelativePaths.map { ModelAssetArtifact(relativePath: $0, scope: .modelSpecific) }
        )
        let store = LocalModelAssetStore(rootDirectory: modelsDirectory, descriptors: [asset], storeVersionSeed: "status")
        if case .failed = store.deepIntegrity(for: asset, depth: .manifestSizes) { return false }
        return true
    }

    /// One file the catalog expects, by its exact size and SHA-256.
    public struct ExpectedFile: Sendable, Equatable {
        public let relativePath: String
        public let sizeBytes: Int64
        public let sha256: String

        public init(relativePath: String, sizeBytes: Int64, sha256: String) {
            self.relativePath = relativePath
            self.sizeBytes = sizeBytes
            self.sha256 = sha256
        }
    }

    public struct Verification: Sendable, Equatable {
        public var missingPaths: [String] = []
        /// Present, but a different size or digest, or not a regular file.
        public var mismatchedPaths: [String] = []
        /// Present but unreadable (permissions or an I/O error).
        public var unreadablePaths: [String] = []
        public var verifiedBytes: Int64 = 0

        public var passed: Bool { missingPaths.isEmpty && mismatchedPaths.isEmpty && unreadablePaths.isEmpty }
    }

    /// Hashes every file under `folder` against `files`, off the caller's actor
    /// and cancellable between files. `progress` gets the count of files checked.
    @concurrent public static func verify(
        _ files: [ExpectedFile],
        in folder: URL,
        progress: @Sendable (Int) -> Void = { _ in }
    ) async throws -> Verification {
        var result = Verification()
        for (position, file) in files.enumerated() {
            try Task.checkCancellation()
            let url = folder.appendingPathComponent(file.relativePath, isDirectory: false)
            let attributes = try? FileManager.default.attributesOfItem(atPath: url.path)
            if attributes == nil, (try? FileManager.default.destinationOfSymbolicLink(atPath: url.path)) == nil {
                result.missingPaths.append(file.relativePath)
            } else {
                do {
                    let actual = try SharedComponentFileIdentity.verify(relativePath: file.relativePath, fileURL: url)
                    if actual.byteCount == file.sizeBytes, actual.sha256 == file.sha256 {
                        result.verifiedBytes += actual.byteCount
                    } else {
                        result.mismatchedPaths.append(file.relativePath)
                    }
                } catch let error as SharedModelComponentStoreError {
                    if case .nonRegularFile = error {
                        result.mismatchedPaths.append(file.relativePath)
                    } else {
                        result.unreadablePaths.append(file.relativePath)
                    }
                } catch {
                    result.unreadablePaths.append(file.relativePath)
                }
            }
            progress(position + 1)
        }
        result.missingPaths.sort()
        result.mismatchedPaths.sort()
        result.unreadablePaths.sort()
        return result
    }
}
