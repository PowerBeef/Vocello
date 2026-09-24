import CryptoKit
import Darwin
import Foundation

/// A privacy-safe identity for one immutable file in a shared model component.
///
/// The relative path is part of the identity: two identical byte streams used at different
/// component paths are not silently interchangeable. Absolute paths never enter persisted state.
public struct SharedComponentFileIdentity: Codable, Hashable, Sendable {
    public let relativePath: String
    public let byteCount: Int64
    public let sha256: String

    public init(relativePath: String, byteCount: Int64, sha256: String) throws {
        guard SharedComponentIdentityValidation.isSafeRelativePath(relativePath) else {
            throw SharedModelComponentStoreError.invalidRelativePath
        }
        guard byteCount > 0 else {
            throw SharedModelComponentStoreError.invalidByteCount(relativePath: relativePath)
        }
        let digest = sha256.lowercased()
        guard SharedComponentIdentityValidation.isSHA256(digest) else {
            throw SharedModelComponentStoreError.invalidDigest(relativePath: relativePath)
        }
        self.relativePath = relativePath
        self.byteCount = byteCount
        self.sha256 = digest
    }

    public static func verify(relativePath: String, fileURL: URL) throws -> Self {
        guard SharedComponentFileSystem.isRegularFileWithoutSymlink(fileURL) else {
            throw SharedModelComponentStoreError.nonRegularFile(relativePath: relativePath)
        }
        let byteCount = try SharedComponentFileSystem.fileSize(fileURL, relativePath: relativePath)
        let digest = try SharedComponentFileSystem.sha256(fileURL, relativePath: relativePath)
        return try Self(relativePath: relativePath, byteCount: byteCount, sha256: digest)
    }

    public func verify(fileURL: URL) throws {
        let actual = try Self.verify(relativePath: relativePath, fileURL: fileURL)
        guard actual.byteCount == byteCount else {
            throw SharedModelComponentStoreError.sizeMismatch(relativePath: relativePath)
        }
        guard actual.sha256 == sha256 else {
            throw SharedModelComponentStoreError.digestMismatch(relativePath: relativePath)
        }
    }

    private enum CodingKeys: String, CodingKey {
        case relativePath
        case byteCount
        case sha256
    }

    public init(from decoder: any Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        try self.init(
            relativePath: values.decode(String.self, forKey: .relativePath),
            byteCount: values.decode(Int64.self, forKey: .byteCount),
            sha256: values.decode(String.self, forKey: .sha256)
        )
    }
}

/// Content identity is derived only from ordered component paths, sizes, and hashes.
/// Runtime compatibility is deliberately represented by a different type below.
public struct SharedComponentContentIdentity: Codable, Hashable, Sendable {
    public static let currentSchemaVersion = 1

    public let schemaVersion: Int
    public let digest: String
    public let files: [SharedComponentFileIdentity]

    public init(files: [SharedComponentFileIdentity]) throws {
        guard !files.isEmpty else {
            throw SharedModelComponentStoreError.emptyContentIdentity
        }
        let ordered = files.sorted { $0.relativePath < $1.relativePath }
        guard Set(ordered.map(\.relativePath)).count == ordered.count else {
            throw SharedModelComponentStoreError.duplicateRelativePath
        }
        self.schemaVersion = Self.currentSchemaVersion
        self.files = ordered
        self.digest = SharedComponentIdentityValidation.canonicalDigest(
            domain: "vocello.shared-component.content.v1",
            fields: ordered.flatMap { [$0.relativePath, String($0.byteCount), $0.sha256] }
        )
    }

    private enum CodingKeys: String, CodingKey {
        case schemaVersion
        case digest
        case files
    }

    public init(from decoder: any Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        let schemaVersion = try values.decode(Int.self, forKey: .schemaVersion)
        guard schemaVersion == Self.currentSchemaVersion else {
            throw SharedModelComponentStoreError.unsupportedSchema
        }
        let files = try values.decode([SharedComponentFileIdentity].self, forKey: .files)
        let decodedDigest = try values.decode(String.self, forKey: .digest).lowercased()
        let rebuilt = try Self(files: files)
        guard decodedDigest == rebuilt.digest else {
            throw SharedModelComponentStoreError.contentIdentityMismatch
        }
        self = rebuilt
    }
}

public enum SharedComponentEncoderCapability: String, Codable, Hashable, Sendable {
    case decoderOnly
    case encoderAndDecoder

    fileprivate func satisfies(_ required: Self) -> Bool {
        switch (self, required) {
        case (.encoderAndDecoder, _), (.decoderOnly, .decoderOnly):
            return true
        case (.decoderOnly, .encoderAndDecoder):
            return false
        }
    }
}

/// Compatibility identity is independent from byte identity. Equal content is reusable only when
/// its schema, loader ABI, runtime profile, and encoder capability satisfy the requesting model.
public struct SharedComponentCompatibilityIdentity: Codable, Hashable, Sendable {
    public static let currentSchemaVersion = 1

    public let schemaVersion: Int
    public let digest: String
    public let contentDigest: String
    public let componentSchemaVersion: Int
    public let loaderABI: String
    public let runtimeProfileSignature: String
    public let encoderCapability: SharedComponentEncoderCapability

    public init(
        contentDigest: String,
        componentSchemaVersion: Int,
        loaderABI: String,
        runtimeProfileSignature: String,
        encoderCapability: SharedComponentEncoderCapability
    ) throws {
        let normalizedContentDigest = contentDigest.lowercased()
        guard SharedComponentIdentityValidation.isSHA256(normalizedContentDigest) else {
            throw SharedModelComponentStoreError.invalidContentDigest
        }
        guard componentSchemaVersion > 0,
              SharedComponentIdentityValidation.isSafeToken(loaderABI),
              SharedComponentIdentityValidation.isSafeToken(runtimeProfileSignature) else {
            throw SharedModelComponentStoreError.invalidCompatibilityIdentity
        }
        self.schemaVersion = Self.currentSchemaVersion
        self.contentDigest = normalizedContentDigest
        self.componentSchemaVersion = componentSchemaVersion
        self.loaderABI = loaderABI
        self.runtimeProfileSignature = runtimeProfileSignature
        self.encoderCapability = encoderCapability
        self.digest = SharedComponentIdentityValidation.canonicalDigest(
            domain: "vocello.shared-component.compatibility.v1",
            fields: [
                normalizedContentDigest,
                String(componentSchemaVersion),
                loaderABI,
                runtimeProfileSignature,
                encoderCapability.rawValue,
            ]
        )
    }

    public func satisfies(_ required: Self) -> Bool {
        contentDigest == required.contentDigest
            && componentSchemaVersion == required.componentSchemaVersion
            && loaderABI == required.loaderABI
            && runtimeProfileSignature == required.runtimeProfileSignature
            && encoderCapability.satisfies(required.encoderCapability)
    }

    private enum CodingKeys: String, CodingKey {
        case schemaVersion
        case digest
        case contentDigest
        case componentSchemaVersion
        case loaderABI
        case runtimeProfileSignature
        case encoderCapability
    }

    public init(from decoder: any Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        guard try values.decode(Int.self, forKey: .schemaVersion) == Self.currentSchemaVersion else {
            throw SharedModelComponentStoreError.unsupportedSchema
        }
        let rebuilt = try Self(
            contentDigest: values.decode(String.self, forKey: .contentDigest),
            componentSchemaVersion: values.decode(Int.self, forKey: .componentSchemaVersion),
            loaderABI: values.decode(String.self, forKey: .loaderABI),
            runtimeProfileSignature: values.decode(String.self, forKey: .runtimeProfileSignature),
            encoderCapability: values.decode(SharedComponentEncoderCapability.self, forKey: .encoderCapability)
        )
        guard try values.decode(String.self, forKey: .digest).lowercased() == rebuilt.digest else {
            throw SharedModelComponentStoreError.compatibilityIdentityMismatch
        }
        self = rebuilt
    }
}

/// Model-local manifest. It stores no absolute path, reference count, device identity, or user data.
public struct SharedComponentInstalledModelManifest: Codable, Hashable, Sendable {
    public static let filename = ".qwenvoice-shared-components.json"
    public static let currentSchemaVersion = 1

    public let schemaVersion: Int
    public let modelIdentity: String
    public let contentIdentity: SharedComponentContentIdentity
    public let compatibilityIdentity: SharedComponentCompatibilityIdentity

    public init(
        modelIdentity: String,
        contentIdentity: SharedComponentContentIdentity,
        compatibilityIdentity: SharedComponentCompatibilityIdentity
    ) throws {
        guard SharedComponentIdentityValidation.isSafeToken(modelIdentity) else {
            throw SharedModelComponentStoreError.invalidModelIdentity
        }
        guard compatibilityIdentity.contentDigest == contentIdentity.digest else {
            throw SharedModelComponentStoreError.compatibilityIdentityMismatch
        }
        self.schemaVersion = Self.currentSchemaVersion
        self.modelIdentity = modelIdentity
        self.contentIdentity = contentIdentity
        self.compatibilityIdentity = compatibilityIdentity
    }

    private enum CodingKeys: String, CodingKey {
        case schemaVersion
        case modelIdentity
        case contentIdentity
        case compatibilityIdentity
    }

    public init(from decoder: any Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        guard try values.decode(Int.self, forKey: .schemaVersion) == Self.currentSchemaVersion else {
            throw SharedModelComponentStoreError.unsupportedSchema
        }
        try self.init(
            modelIdentity: values.decode(String.self, forKey: .modelIdentity),
            contentIdentity: values.decode(SharedComponentContentIdentity.self, forKey: .contentIdentity),
            compatibilityIdentity: values.decode(SharedComponentCompatibilityIdentity.self, forKey: .compatibilityIdentity)
        )
    }
}

public struct SharedComponentMigrationPlan: Hashable, Sendable {
    public let modelFolder: String
    public let manifest: SharedComponentInstalledModelManifest

    public init(modelFolder: String, manifest: SharedComponentInstalledModelManifest) throws {
        guard SharedComponentIdentityValidation.isSafeFolder(modelFolder) else {
            throw SharedModelComponentStoreError.invalidModelFolder
        }
        self.modelFolder = modelFolder
        self.manifest = manifest
    }
}

public struct SharedComponentPublicationResult: Equatable, Sendable {
    public let contentDigest: String
    public let publishedDigests: [String]
    public let reusedDigests: [String]
}

public struct SharedComponentMigrationResult: Equatable, Sendable {
    public let modelIdentity: String
    public let contentDigest: String
    public let linkedFileCount: Int
}

public struct SharedComponentLiveness: Equatable, Sendable {
    public let modelIdentities: [String]
    public let liveBlobDigests: [String]
}

public enum SharedComponentModelAuditState: String, Codable, Sendable {
    case unmanaged
    case healthy
    case repairable
    case corruptStore
}

public struct SharedComponentModelAudit: Equatable, Sendable {
    public let state: SharedComponentModelAuditState
    public let modelIdentity: String?
    public let missingRelativePaths: [String]
    public let copiedRelativePaths: [String]
    public let corruptBlobDigests: [String]
}

public struct SharedComponentPruneResult: Equatable, Sendable {
    public let removedDigests: [String]
    public let preservedDigests: [String]
}

public enum SharedModelComponentStoreError: Error, Equatable, LocalizedError, Sendable {
    case invalidRelativePath
    case invalidByteCount(relativePath: String)
    case invalidDigest(relativePath: String)
    case invalidContentDigest
    case duplicateRelativePath
    case emptyContentIdentity
    case invalidCompatibilityIdentity
    case invalidModelIdentity
    case invalidModelFolder
    case unsupportedSchema
    case contentIdentityMismatch
    case compatibilityIdentityMismatch
    case missingFile(relativePath: String)
    case nonRegularFile(relativePath: String)
    case sizeMismatch(relativePath: String)
    case digestMismatch(relativePath: String)
    case corruptManifest
    case corruptStoreLayout
    case componentUnavailable(digest: String)
    case modelNotFound
    case concurrentModelMutation
    case validationFailed
    case rollbackFailed
    case lockFailed(code: Int32)
    case filesystemFailure(operation: String, code: Int32)

    public var errorDescription: String? {
        switch self {
        case .invalidRelativePath: "A shared component path is invalid."
        case .invalidByteCount: "A shared component byte count is invalid."
        case .invalidDigest, .invalidContentDigest: "A shared component digest is invalid."
        case .duplicateRelativePath: "The shared component contains duplicate paths."
        case .emptyContentIdentity: "The shared component file set is empty."
        case .invalidCompatibilityIdentity: "The shared component compatibility identity is invalid."
        case .invalidModelIdentity, .invalidModelFolder: "The shared component model identity is invalid."
        case .unsupportedSchema: "The shared component schema is unsupported."
        case .contentIdentityMismatch, .compatibilityIdentityMismatch:
            "The shared component identity does not match its contents."
        case .missingFile: "A shared component file is missing."
        case .nonRegularFile: "A shared component file is not an ordinary regular file."
        case .sizeMismatch: "A shared component file has the wrong size."
        case .digestMismatch: "A shared component file failed integrity verification."
        case .corruptManifest: "An installed shared-component manifest is invalid."
        case .corruptStoreLayout: "The shared-component store layout is invalid."
        case .componentUnavailable: "A required shared component is unavailable."
        case .modelNotFound: "The model selected for shared-component migration is missing."
        case .concurrentModelMutation: "The model changed while shared components were prepared."
        case .validationFailed: "The migrated model failed post-publication validation and was rolled back."
        case .rollbackFailed: "The migrated model failed validation and could not be rolled back."
        case .lockFailed: "The shared-component publication lock could not be acquired."
        case .filesystemFailure: "A shared-component filesystem operation failed."
        }
    }
}

/// Deterministic content-addressed model component storage.
///
/// Hashing, replica construction, and post-migration validation happen outside the cross-process
/// lock. The lock covers only synchronous publication, model exchange, tombstoning, and prune
/// renames. Component blobs and model-visible component paths are regular hard links, never links
/// by pathname.
public struct SharedModelComponentStore: Sendable {
    public static let storeFolderName = ".qwenvoice-components-v1"

    public let modelsRoot: URL
    public let storeRoot: URL

    private var blobsRoot: URL { storeRoot.appendingPathComponent("blobs/sha256", isDirectory: true) }
    private var stagingRoot: URL { storeRoot.appendingPathComponent("staging", isDirectory: true) }
    private var trashRoot: URL { storeRoot.appendingPathComponent("trash", isDirectory: true) }
    private var lockURL: URL { storeRoot.appendingPathComponent("publication.lock", isDirectory: false) }

    public init(modelsRoot: URL) {
        self.modelsRoot = modelsRoot.standardizedFileURL
        self.storeRoot = modelsRoot.standardizedFileURL
            .appendingPathComponent(Self.storeFolderName, isDirectory: true)
    }

    public func blobURL(for digest: String) throws -> URL {
        let digest = digest.lowercased()
        guard SharedComponentIdentityValidation.isSHA256(digest) else {
            throw SharedModelComponentStoreError.invalidContentDigest
        }
        return blobsRoot
            .appendingPathComponent(String(digest.prefix(2)), isDirectory: true)
            .appendingPathComponent(digest, isDirectory: false)
    }

    /// Returns true only when every content-addressed blob exists as an ordinary file and passes
    /// its full size/SHA-256 identity. Missing or corrupt blobs are a cache miss, never authority
    /// to skip a catalog download.
    public func containsVerified(_ content: SharedComponentContentIdentity) throws -> Bool {
        for file in content.files {
            let blob = try blobURL(for: file.sha256)
            guard FileManager.default.fileExists(atPath: blob.path) else { return false }
            do {
                try file.verify(fileURL: blob)
            } catch SharedModelComponentStoreError.digestMismatch,
                    SharedModelComponentStoreError.sizeMismatch,
                    SharedModelComponentStoreError.nonRegularFile,
                    SharedModelComponentStoreError.missingFile {
                return false
            }
        }
        return true
    }

    @discardableResult
    public func publish(
        content: SharedComponentContentIdentity,
        from sourceRoot: URL
    ) throws -> SharedComponentPublicationResult {
        try prepareStoreDirectories()
        let sourceRoot = sourceRoot.standardizedFileURL
        var published: [String] = []
        var reused: [String] = []

        for file in content.files {
            let source = try SharedComponentFileSystem.containedURL(
                root: sourceRoot,
                relativePath: file.relativePath
            )
            try file.verify(fileURL: source)
            let destination = try blobURL(for: file.sha256)

            if try verifiedBlobSnapshot(destination, identity: file) != nil {
                reused.append(file.sha256)
                continue
            }

            let stageDirectory = stagingRoot.appendingPathComponent(UUID().uuidString, isDirectory: true)
            let staged = stageDirectory.appendingPathComponent(file.sha256, isDirectory: false)
            try FileManager.default.createDirectory(at: stageDirectory, withIntermediateDirectories: true)
            do {
                try FileManager.default.copyItem(at: source, to: staged)
                try file.verify(fileURL: staged)
                try FileManager.default.setAttributes(
                    [.posixPermissions: NSNumber(value: Int16(0o444))],
                    ofItemAtPath: staged.path
                )
                let disposition = try publishBlob(staged, identity: file, destination: destination)
                switch disposition {
                case .published: published.append(file.sha256)
                case .reused: reused.append(file.sha256)
                }
            } catch {
                try? FileManager.default.removeItem(at: stageDirectory)
                throw error
            }
            try? FileManager.default.removeItem(at: stageDirectory)
        }

        return SharedComponentPublicationResult(
            contentDigest: content.digest,
            publishedDigests: published.sorted(),
            reusedDigests: reused.sorted()
        )
    }

    /// Deep-verifies source component files, publishes immutable blobs, exchanges a hard-linked
    /// model replica atomically, then validates the complete installed model outside the lock.
    /// Validation failure swaps the original directory back before any backup is removed.
    public func migrate(
        _ plan: SharedComponentMigrationPlan,
        validateInstalledModel: @Sendable (URL) throws -> Void
    ) throws -> SharedComponentMigrationResult {
        let modelURL = modelsRoot.appendingPathComponent(plan.modelFolder, isDirectory: true)
        guard FileManager.default.fileExists(atPath: modelURL.path) else {
            throw SharedModelComponentStoreError.modelNotFound
        }

        _ = try publish(content: plan.manifest.contentIdentity, from: modelURL)
        return try replaceModelWithSharedLinks(
            modelURL: modelURL,
            manifest: plan.manifest,
            validateInstalledModel: validateInstalledModel
        )
    }

    /// Reconciles one already-installed model with its authenticated component plan.
    ///
    /// An unmanaged legacy directory is migrated only after the caller has authenticated the
    /// complete artifact. A model with the same manifest is left alone when healthy, or repaired
    /// from verified blobs when its visible component links were damaged. Any other manifest is
    /// rebuilt from the authenticated installed bytes through the regular atomic migration path.
    /// This makes reconciliation idempotent without allowing a damaged model path to repair a
    /// store blob.
    public func reconcileInstalledModel(
        _ plan: SharedComponentMigrationPlan,
        validateInstalledModel: @Sendable (URL) throws -> Void
    ) throws -> SharedComponentMigrationResult? {
        let modelURL = modelsRoot.appendingPathComponent(plan.modelFolder, isDirectory: true)
        guard FileManager.default.fileExists(atPath: modelURL.path) else {
            return nil
        }

        let manifestURL = modelURL.appendingPathComponent(
            SharedComponentInstalledModelManifest.filename,
            isDirectory: false
        )
        if FileManager.default.fileExists(atPath: manifestURL.path),
           let manifest = try? readManifest(modelURL: modelURL),
           manifest == plan.manifest {
            switch try audit(modelFolder: plan.modelFolder).state {
            case .healthy:
                return nil
            case .repairable:
                return try repair(
                    modelFolder: plan.modelFolder,
                    validateInstalledModel: validateInstalledModel
                )
            case .corruptStore:
                // `repair` verifies each blob before constructing a replica, so a corrupt
                // content-addressed store remains fail-closed.
                return try repair(
                    modelFolder: plan.modelFolder,
                    validateInstalledModel: validateInstalledModel
                )
            case .unmanaged:
                break
            }
        }

        return try migrate(plan, validateInstalledModel: validateInstalledModel)
    }

    /// Authenticates an existing model directory before it may supply component bytes for an
    /// automatic migration. All file paths are resolved beneath the model root with symlinked
    /// ancestors rejected, and every file is checked against its exact catalog identity.
    public func validateInstalledModelFiles(
        modelFolder: String,
        expectedFiles: [SharedComponentFileIdentity]
    ) throws {
        guard SharedComponentIdentityValidation.isSafeFolder(modelFolder) else {
            throw SharedModelComponentStoreError.invalidModelFolder
        }
        let modelURL = modelsRoot.appendingPathComponent(modelFolder, isDirectory: true)
        guard FileManager.default.fileExists(atPath: modelURL.path) else {
            throw SharedModelComponentStoreError.modelNotFound
        }
        try validateModelFiles(at: modelURL, expectedFiles: expectedFiles)
    }

    /// Validates a model candidate directory used by migration or staged installation. This uses
    /// the same containment checks as model-folder validation but intentionally accepts an atomic
    /// replacement directory whose temporary name is not a user-visible model folder.
    public func validateModelFiles(
        at modelURL: URL,
        expectedFiles: [SharedComponentFileIdentity]
    ) throws {
        let values = try modelURL.resourceValues(forKeys: [.isDirectoryKey, .isSymbolicLinkKey])
        guard values.isDirectory == true, values.isSymbolicLink != true else {
            throw SharedModelComponentStoreError.modelNotFound
        }
        for file in expectedFiles {
            let url = try SharedComponentFileSystem.containedURL(
                root: modelURL,
                relativePath: file.relativePath
            )
            try file.verify(fileURL: url)
        }
    }

    /// Builds and atomically publishes a complete installed model from downloader staging.
    ///
    /// Component files may either be present in staging (freshly downloaded) or absent when a
    /// previously verified store blob is being reused. The complete staged replica is validated
    /// before publication. The final model exchange and component-liveness publication happen
    /// under the same cross-process lock, so pruning cannot race through the installation gap.
    public func installStagedModel(
        _ plan: SharedComponentMigrationPlan,
        stagedModelURL: URL,
        validateInstalledModel: @Sendable (URL) throws -> Void
    ) throws -> SharedComponentMigrationResult {
        try prepareStoreDirectories()
        let stagedModelURL = stagedModelURL.standardizedFileURL
        guard FileManager.default.fileExists(atPath: stagedModelURL.path) else {
            throw SharedModelComponentStoreError.modelNotFound
        }

        // Publish freshly downloaded component files. A missing staged file is eligible only
        // when the content-addressed store already contains the exact verified blob.
        for file in plan.manifest.contentIdentity.files {
            let source = try SharedComponentFileSystem.containedURL(
                root: stagedModelURL,
                relativePath: file.relativePath
            )
            if FileManager.default.fileExists(atPath: source.path) {
                try file.verify(fileURL: source)
                _ = try publish(
                    content: SharedComponentContentIdentity(files: [file]),
                    from: stagedModelURL
                )
            } else {
                let blob = try blobURL(for: file.sha256)
                try file.verify(fileURL: blob)
            }
        }

        let target = modelsRoot.appendingPathComponent(plan.modelFolder, isDirectory: true)
        let replica = modelsRoot.appendingPathComponent(
            ".\(plan.modelFolder).component-install.\(UUID().uuidString)",
            isDirectory: true
        )
        let stagedSnapshot: SharedComponentFileSystem.DirectorySnapshot
        do {
            stagedSnapshot = try SharedComponentFileSystem.hardLinkedReplica(
                source: stagedModelURL,
                destination: replica
            )
            for file in plan.manifest.contentIdentity.files {
                let blob = try blobURL(for: file.sha256)
                try file.verify(fileURL: blob)
                let visible = try SharedComponentFileSystem.containedURL(
                    root: replica,
                    relativePath: file.relativePath
                )
                if FileManager.default.fileExists(atPath: visible.path) {
                    try FileManager.default.removeItem(at: visible)
                }
                try FileManager.default.createDirectory(
                    at: visible.deletingLastPathComponent(),
                    withIntermediateDirectories: true
                )
                try FileManager.default.linkItem(at: blob, to: visible)
            }
            try SharedComponentFileSystem.canonicalJSON(plan.manifest).write(
                to: replica.appendingPathComponent(
                    SharedComponentInstalledModelManifest.filename,
                    isDirectory: false
                ),
                options: .atomic
            )
            try validateInstalledModel(replica)
        } catch {
            try? FileManager.default.removeItem(at: replica)
            throw error
        }

        // Hashing and full-model validation stay outside the lock. Snapshot equality and inode
        // checks make the short publication decision stale-safe.
        let blobSnapshots = try Dictionary(uniqueKeysWithValues: plan.manifest.contentIdentity.files.map {
            let blob = try blobURL(for: $0.sha256)
            return ($0.sha256, try SharedComponentFileSystem.snapshot(blob))
        })
        do {
            try withPublicationLock {
                guard try SharedComponentFileSystem.directoryMatches(stagedModelURL, stagedSnapshot) else {
                    throw SharedModelComponentStoreError.concurrentModelMutation
                }
                for file in plan.manifest.contentIdentity.files {
                    let blob = try blobURL(for: file.sha256)
                    let visible = try SharedComponentFileSystem.containedURL(
                        root: replica,
                        relativePath: file.relativePath
                    )
                    guard try SharedComponentFileSystem.snapshot(blob) == blobSnapshots[file.sha256],
                          SharedComponentFileSystem.isRegularFileWithoutSymlink(visible),
                          try SharedComponentFileSystem.sameFile(blob, visible) else {
                        throw SharedModelComponentStoreError.componentUnavailable(digest: file.sha256)
                    }
                }
                if FileManager.default.fileExists(atPath: target.path) {
                    try SharedComponentFileSystem.atomicSwap(target, replica)
                } else {
                    try SharedComponentFileSystem.move(replica, to: target, operation: "install-model")
                }
            }
        } catch {
            try? FileManager.default.removeItem(at: replica)
            throw error
        }

        // After an exchange, `replica` contains the superseded target. New installs moved the
        // replica itself, so this is a no-op.
        try? FileManager.default.removeItem(at: replica)
        return SharedComponentMigrationResult(
            modelIdentity: plan.manifest.modelIdentity,
            contentDigest: plan.manifest.contentIdentity.digest,
            linkedFileCount: plan.manifest.contentIdentity.files.count
        )
    }

    /// Repairs copied or missing component paths from already verified store blobs. A corrupt or
    /// missing store blob fails closed; repair never derives content from the damaged model path.
    public func repair(
        modelFolder: String,
        validateInstalledModel: @Sendable (URL) throws -> Void
    ) throws -> SharedComponentMigrationResult {
        guard SharedComponentIdentityValidation.isSafeFolder(modelFolder) else {
            throw SharedModelComponentStoreError.invalidModelFolder
        }
        let modelURL = modelsRoot.appendingPathComponent(modelFolder, isDirectory: true)
        let manifest = try readManifest(modelURL: modelURL)
        for file in manifest.contentIdentity.files {
            let blob = try blobURL(for: file.sha256)
            try file.verify(fileURL: blob)
        }
        return try replaceModelWithSharedLinks(
            modelURL: modelURL,
            manifest: manifest,
            validateInstalledModel: validateInstalledModel
        )
    }

    public func audit(modelFolder: String, deepVerifyBlobs: Bool = true) throws -> SharedComponentModelAudit {
        guard SharedComponentIdentityValidation.isSafeFolder(modelFolder) else {
            throw SharedModelComponentStoreError.invalidModelFolder
        }
        let modelURL = modelsRoot.appendingPathComponent(modelFolder, isDirectory: true)
        let manifestURL = modelURL.appendingPathComponent(
            SharedComponentInstalledModelManifest.filename,
            isDirectory: false
        )
        guard FileManager.default.fileExists(atPath: manifestURL.path) else {
            return SharedComponentModelAudit(
                state: .unmanaged,
                modelIdentity: nil,
                missingRelativePaths: [],
                copiedRelativePaths: [],
                corruptBlobDigests: []
            )
        }
        let manifest = try readManifest(modelURL: modelURL)
        var missing: [String] = []
        var copied: [String] = []
        var corrupt: [String] = []
        for file in manifest.contentIdentity.files {
            let blob = try blobURL(for: file.sha256)
            if deepVerifyBlobs {
                do { try file.verify(fileURL: blob) } catch { corrupt.append(file.sha256); continue }
            } else if !SharedComponentFileSystem.isRegularFileWithoutSymlink(blob) {
                corrupt.append(file.sha256)
                continue
            }
            let visible = try SharedComponentFileSystem.containedURL(
                root: modelURL,
                relativePath: file.relativePath
            )
            guard FileManager.default.fileExists(atPath: visible.path) else {
                missing.append(file.relativePath)
                continue
            }
            guard SharedComponentFileSystem.isRegularFileWithoutSymlink(visible),
                  try SharedComponentFileSystem.sameFile(blob, visible) else {
                copied.append(file.relativePath)
                continue
            }
        }
        let state: SharedComponentModelAuditState
        if !corrupt.isEmpty {
            state = .corruptStore
        } else if !missing.isEmpty || !copied.isEmpty {
            state = .repairable
        } else {
            state = .healthy
        }
        return SharedComponentModelAudit(
            state: state,
            modelIdentity: manifest.modelIdentity,
            missingRelativePaths: missing.sorted(),
            copiedRelativePaths: copied.sorted(),
            corruptBlobDigests: Array(Set(corrupt)).sorted()
        )
    }

    /// How long automatic reclamation leaves a freshly published blob, or a fresh `trash/` or
    /// `staging/` entry, alone. Publication and installation are separate steps (a blob is
    /// published, then hard-linked into the replica that becomes the model), and another process
    /// may be between them; the grace period, together with the hard-link check, keeps an
    /// in-flight install's components from being reclaimed under it.
    public static let automaticReclaimGracePeriod: TimeInterval = 15 * 60

    /// Atomically removes one model directory, then reclaims what no installed model still
    /// references: shared blobs no strict installed manifest lists (so another model's links stay
    /// valid) and leftover `trash/` and `staging/` entries. The model removal is the operation's
    /// result; reclamation is best effort and its failure never fails the delete.
    public func deleteModel(
        modelFolder: String,
        componentGracePeriod: TimeInterval = SharedModelComponentStore.automaticReclaimGracePeriod
    ) throws {
        guard SharedComponentIdentityValidation.isSafeFolder(modelFolder) else {
            throw SharedModelComponentStoreError.invalidModelFolder
        }
        try prepareStoreDirectories()
        let modelURL = modelsRoot.appendingPathComponent(modelFolder, isDirectory: true)
        guard FileManager.default.fileExists(atPath: modelURL.path) else { return }
        let tombstone = trashRoot.appendingPathComponent("model-\(UUID().uuidString)", isDirectory: true)
        try withPublicationLock {
            guard FileManager.default.fileExists(atPath: modelURL.path) else { return }
            try SharedComponentFileSystem.move(modelURL, to: tombstone, operation: "tombstone-model")
        }
        try Self.removeTombstone(tombstone)
        _ = try? reclaimUnreferencedComponents(gracePeriod: componentGracePeriod)
    }

    /// Automatic reclamation, run after every model delete and once per engine start. Unlike the
    /// exact `pruneUnreferencedComponents()`, it also sweeps `trash/` and `staging/` leftovers
    /// from interrupted operations and protects what may belong to an operation in flight: a blob
    /// with another hard link (an install or migration replica holds it) or one published within
    /// the grace period, and trash or staging entries younger than it. A store that does not exist
    /// yet is left uncreated.
    @discardableResult
    public func reclaimUnreferencedComponents(
        gracePeriod: TimeInterval = SharedModelComponentStore.automaticReclaimGracePeriod
    ) throws -> SharedComponentPruneResult {
        guard FileManager.default.fileExists(atPath: storeRoot.path) else {
            return SharedComponentPruneResult(removedDigests: [], preservedDigests: [])
        }
        let cutoff = Date().addingTimeInterval(-max(gracePeriod, 0))
        for root in [trashRoot, stagingRoot] {
            let entries = (try? FileManager.default.contentsOfDirectory(
                at: root,
                includingPropertiesForKeys: nil,
                options: []
            )) ?? []
            for entry in entries {
                guard let status = SharedComponentFileSystem.linkStatus(entry),
                      status.changedAt < cutoff else { continue }
                try? Self.removeTombstone(entry)
            }
        }
        return try pruneUnreferencedComponents { blob in
            guard let status = SharedComponentFileSystem.linkStatus(blob) else { return true }
            return status.linkCount > 1 || status.changedAt >= cutoff
        }
    }

    /// Computes component liveness exclusively from strict installed manifests. There is no
    /// mutable reference-count database to become stale after interruption or rollback.
    public func liveness() throws -> SharedComponentLiveness {
        try livenessUnlocked()
    }

    /// Moves unreferenced blobs to private trash while holding the publication lock, then removes
    /// them after releasing it. A malformed manifest or missing live blob makes pruning fail closed.
    public func pruneUnreferencedComponents() throws -> SharedComponentPruneResult {
        try pruneUnreferencedComponents { _ in false }
    }

    private func pruneUnreferencedComponents(
        isProtected: (URL) -> Bool
    ) throws -> SharedComponentPruneResult {
        try prepareStoreDirectories()
        var removed: [String] = []
        var preserved: [String] = []
        var tombstones: [URL] = []
        try withPublicationLock {
            let live = Set(try livenessUnlocked().liveBlobDigests)
            for (digest, url) in try allStoredBlobs() {
                if live.contains(digest) || isProtected(url) {
                    preserved.append(digest)
                } else {
                    let tombstone = trashRoot.appendingPathComponent("blob-\(UUID().uuidString)")
                    try SharedComponentFileSystem.move(url, to: tombstone, operation: "tombstone-blob")
                    tombstones.append(tombstone)
                    removed.append(digest)
                }
            }
        }
        for tombstone in tombstones {
            try Self.removeTombstone(tombstone)
        }
        return SharedComponentPruneResult(
            removedDigests: removed.sorted(),
            preservedDigests: preserved.sorted()
        )
    }

    private enum BlobPublicationDisposition { case published, reused }

    private func publishBlob(
        _ staged: URL,
        identity: SharedComponentFileIdentity,
        destination: URL
    ) throws -> BlobPublicationDisposition {
        while true {
            let observed = try SharedComponentFileSystem.snapshotIfPresent(destination)
            let verifiedObserved: SharedComponentFileSystem.FileSnapshot?
            if observed != nil {
                verifiedObserved = try verifiedBlobSnapshot(destination, identity: identity)
            } else {
                verifiedObserved = nil
            }

            enum Decision { case published, reused, retry }
            let decision: Decision = try withPublicationLock {
                let current = try SharedComponentFileSystem.snapshotIfPresent(destination)
                guard current == observed else { return .retry }
                try FileManager.default.createDirectory(
                    at: destination.deletingLastPathComponent(),
                    withIntermediateDirectories: true
                )
                if verifiedObserved != nil {
                    return .reused
                }
                if current == nil {
                    try SharedComponentFileSystem.move(staged, to: destination, operation: "publish-blob")
                } else {
                    try SharedComponentFileSystem.atomicSwap(staged, destination)
                }
                return .published
            }
            switch decision {
            case .published:
                if FileManager.default.fileExists(atPath: staged.path) {
                    try FileManager.default.removeItem(at: staged)
                }
                return .published
            case .reused:
                try FileManager.default.removeItem(at: staged)
                return .reused
            case .retry:
                continue
            }
        }
    }

    private func verifiedBlobSnapshot(
        _ url: URL,
        identity: SharedComponentFileIdentity
    ) throws -> SharedComponentFileSystem.FileSnapshot? {
        guard FileManager.default.fileExists(atPath: url.path) else { return nil }
        do {
            try identity.verify(fileURL: url)
            return try SharedComponentFileSystem.snapshot(url)
        } catch SharedModelComponentStoreError.digestMismatch,
                SharedModelComponentStoreError.sizeMismatch,
                SharedModelComponentStoreError.nonRegularFile {
            return nil
        }
    }

    private func replaceModelWithSharedLinks(
        modelURL: URL,
        manifest: SharedComponentInstalledModelManifest,
        validateInstalledModel: @Sendable (URL) throws -> Void
    ) throws -> SharedComponentMigrationResult {
        try prepareStoreDirectories()
        guard FileManager.default.fileExists(atPath: modelURL.path) else {
            throw SharedModelComponentStoreError.modelNotFound
        }
        // A model loaded by a build before PA-22 carries the engine's rebuildable overlay of
        // absolute symlinks inside its folder. The replica accepts only regular files, so without
        // this every migrate or repair of such a model failed and fell back to a full re-download.
        // The overlay is cache the engine now rebuilds outside the model folder.
        PreparedModelOverlay.removeLegacyOverlay(in: modelURL)
        let replica = modelsRoot.appendingPathComponent(
            ".\(modelURL.lastPathComponent).component-migration.\(UUID().uuidString)",
            isDirectory: true
        )
        var originalSnapshot: SharedComponentFileSystem.DirectorySnapshot?
        do {
            originalSnapshot = try SharedComponentFileSystem.hardLinkedReplica(
                source: modelURL,
                destination: replica
            )
            for file in manifest.contentIdentity.files {
                let blob = try blobURL(for: file.sha256)
                try file.verify(fileURL: blob)
                let visible = try SharedComponentFileSystem.containedURL(
                    root: replica,
                    relativePath: file.relativePath
                )
                if FileManager.default.fileExists(atPath: visible.path) {
                    try FileManager.default.removeItem(at: visible)
                }
                try FileManager.default.createDirectory(
                    at: visible.deletingLastPathComponent(),
                    withIntermediateDirectories: true
                )
                try FileManager.default.linkItem(at: blob, to: visible)
            }
            let manifestData = try SharedComponentFileSystem.canonicalJSON(manifest)
            try manifestData.write(
                to: replica.appendingPathComponent(
                    SharedComponentInstalledModelManifest.filename,
                    isDirectory: false
                ),
                options: .atomic
            )
        } catch {
            try? FileManager.default.removeItem(at: replica)
            throw error
        }

        do {
            try withPublicationLock {
                guard let originalSnapshot,
                      try SharedComponentFileSystem.directoryMatches(modelURL, originalSnapshot) else {
                    throw SharedModelComponentStoreError.concurrentModelMutation
                }
                for file in manifest.contentIdentity.files {
                    let blob = try blobURL(for: file.sha256)
                    let replicaFile = try SharedComponentFileSystem.containedURL(
                        root: replica,
                        relativePath: file.relativePath
                    )
                    guard SharedComponentFileSystem.isRegularFileWithoutSymlink(blob),
                          try SharedComponentFileSystem.sameFile(blob, replicaFile) else {
                        throw SharedModelComponentStoreError.componentUnavailable(digest: file.sha256)
                    }
                }
                try SharedComponentFileSystem.atomicSwap(modelURL, replica)
            }
        } catch {
            try? FileManager.default.removeItem(at: replica)
            throw error
        }

        do {
            try validateInstalledModel(modelURL)
        } catch {
            do {
                try withPublicationLock {
                    try SharedComponentFileSystem.atomicSwap(modelURL, replica)
                }
                try? FileManager.default.removeItem(at: replica)
                throw SharedModelComponentStoreError.validationFailed
            } catch let rollback as SharedModelComponentStoreError where rollback == .validationFailed {
                throw rollback
            } catch {
                throw SharedModelComponentStoreError.rollbackFailed
            }
        }

        try FileManager.default.removeItem(at: replica)
        return SharedComponentMigrationResult(
            modelIdentity: manifest.modelIdentity,
            contentDigest: manifest.contentIdentity.digest,
            linkedFileCount: manifest.contentIdentity.files.count
        )
    }

    private func readManifest(modelURL: URL) throws -> SharedComponentInstalledModelManifest {
        guard FileManager.default.fileExists(atPath: modelURL.path) else {
            throw SharedModelComponentStoreError.modelNotFound
        }
        do {
            return try JSONDecoder().decode(
                SharedComponentInstalledModelManifest.self,
                from: Data(contentsOf: modelURL.appendingPathComponent(
                    SharedComponentInstalledModelManifest.filename,
                    isDirectory: false
                ))
            )
        } catch let error as SharedModelComponentStoreError {
            throw error
        } catch {
            throw SharedModelComponentStoreError.corruptManifest
        }
    }

    private func livenessUnlocked() throws -> SharedComponentLiveness {
        guard FileManager.default.fileExists(atPath: modelsRoot.path) else {
            return SharedComponentLiveness(modelIdentities: [], liveBlobDigests: [])
        }
        let entries = try FileManager.default.contentsOfDirectory(
            at: modelsRoot,
            includingPropertiesForKeys: [.isDirectoryKey, .isSymbolicLinkKey],
            options: []
        )
        var models: [String] = []
        var live = Set<String>()
        for entry in entries where entry.lastPathComponent != Self.storeFolderName
            && !entry.lastPathComponent.hasPrefix(".") {
            let values = try entry.resourceValues(forKeys: [.isDirectoryKey, .isSymbolicLinkKey])
            guard values.isDirectory == true, values.isSymbolicLink != true else { continue }
            let manifestURL = entry.appendingPathComponent(
                SharedComponentInstalledModelManifest.filename,
                isDirectory: false
            )
            guard FileManager.default.fileExists(atPath: manifestURL.path) else { continue }
            let manifest = try readManifest(modelURL: entry)
            models.append(manifest.modelIdentity)
            for file in manifest.contentIdentity.files {
                let blob = try blobURL(for: file.sha256)
                guard SharedComponentFileSystem.isRegularFileWithoutSymlink(blob) else {
                    throw SharedModelComponentStoreError.componentUnavailable(digest: file.sha256)
                }
                live.insert(file.sha256)
            }
        }
        return SharedComponentLiveness(
            modelIdentities: models.sorted(),
            liveBlobDigests: live.sorted()
        )
    }

    private func allStoredBlobs() throws -> [(String, URL)] {
        guard FileManager.default.fileExists(atPath: blobsRoot.path) else { return [] }
        guard let enumerator = FileManager.default.enumerator(
            at: blobsRoot,
            includingPropertiesForKeys: [.isRegularFileKey, .isSymbolicLinkKey],
            options: [.skipsHiddenFiles]
        ) else {
            throw SharedModelComponentStoreError.corruptStoreLayout
        }
        var result: [(String, URL)] = []
        for case let url as URL in enumerator {
            let values = try url.resourceValues(forKeys: [.isRegularFileKey, .isSymbolicLinkKey])
            if values.isRegularFile == true {
                let digest = url.lastPathComponent.lowercased()
                guard values.isSymbolicLink != true,
                      SharedComponentIdentityValidation.isSHA256(digest),
                      url.deletingLastPathComponent().lastPathComponent == String(digest.prefix(2)) else {
                    throw SharedModelComponentStoreError.corruptStoreLayout
                }
                result.append((digest, url))
            }
        }
        return result
    }

    /// Removes a private tombstone. Another process's reclamation sweep may already have removed
    /// it, which is success rather than a failure of this operation.
    private static func removeTombstone(_ tombstone: URL) throws {
        do {
            try FileManager.default.removeItem(at: tombstone)
        } catch {
            guard FileManager.default.fileExists(atPath: tombstone.path) else { return }
            throw error
        }
    }

    private func prepareStoreDirectories() throws {
        for directory in [modelsRoot, blobsRoot, stagingRoot, trashRoot] {
            try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        }
    }

    private func withPublicationLock<T>(_ body: () throws -> T) throws -> T {
        try prepareStoreDirectories()
        let descriptor = lockURL.withUnsafeFileSystemRepresentation { path in
            guard let path else { return Int32(-1) }
            // Create and open the lock file in one kernel operation. A separate existence check
            // plus FileManager.createFile can race on the store's first concurrent publication,
            // leaving contenders flocking different inodes and both reporting `.published`.
            return Darwin.open(path, O_RDWR | O_CREAT | O_CLOEXEC | O_NOFOLLOW, mode_t(0o600))
        }
        guard descriptor >= 0 else {
            throw SharedModelComponentStoreError.lockFailed(code: errno)
        }
        defer { close(descriptor) }
        guard flock(descriptor, LOCK_EX) == 0 else {
            throw SharedModelComponentStoreError.lockFailed(code: errno)
        }
        defer { flock(descriptor, LOCK_UN) }
        return try body()
    }
}

/// Optional async ownership boundary for callers that want one in-process operation queue. The
/// underlying store remains cross-process safe, so synchronous CLI and actor-based app callers use
/// the same publication and rollback implementation.
public actor SharedModelComponentStoreCoordinator {
    private let store: SharedModelComponentStore

    public init(modelsRoot: URL) {
        self.store = SharedModelComponentStore(modelsRoot: modelsRoot)
    }

    public func publish(
        content: SharedComponentContentIdentity,
        from sourceRoot: URL
    ) throws -> SharedComponentPublicationResult {
        try store.publish(content: content, from: sourceRoot)
    }

    public func containsVerified(_ content: SharedComponentContentIdentity) throws -> Bool {
        try store.containsVerified(content)
    }

    public func migrate(
        _ plan: SharedComponentMigrationPlan,
        validateInstalledModel: @Sendable (URL) throws -> Void
    ) throws -> SharedComponentMigrationResult {
        try store.migrate(plan, validateInstalledModel: validateInstalledModel)
    }

    public func installStagedModel(
        _ plan: SharedComponentMigrationPlan,
        stagedModelURL: URL,
        validateInstalledModel: @Sendable (URL) throws -> Void
    ) throws -> SharedComponentMigrationResult {
        try store.installStagedModel(
            plan,
            stagedModelURL: stagedModelURL,
            validateInstalledModel: validateInstalledModel
        )
    }

    public func repair(
        modelFolder: String,
        validateInstalledModel: @Sendable (URL) throws -> Void
    ) throws -> SharedComponentMigrationResult {
        try store.repair(modelFolder: modelFolder, validateInstalledModel: validateInstalledModel)
    }

    public func deleteModel(modelFolder: String) throws {
        try store.deleteModel(modelFolder: modelFolder)
    }

    @discardableResult
    public func reclaimUnreferencedComponents() throws -> SharedComponentPruneResult {
        try store.reclaimUnreferencedComponents()
    }

    public func liveness() throws -> SharedComponentLiveness {
        try store.liveness()
    }

    public func pruneUnreferencedComponents() throws -> SharedComponentPruneResult {
        try store.pruneUnreferencedComponents()
    }
}

private enum SharedComponentIdentityValidation {
    static func isSHA256(_ value: String) -> Bool {
        value.range(of: #"^[0-9a-f]{64}$"#, options: .regularExpression) != nil
    }

    static func isSafeRelativePath(_ value: String) -> Bool {
        guard !value.isEmpty, !value.hasPrefix("/"), !value.contains("\\"),
              !value.contains("://"), value == value.trimmingCharacters(in: .whitespacesAndNewlines) else {
            return false
        }
        let components = value.split(separator: "/", omittingEmptySubsequences: false)
        return !components.isEmpty && components.allSatisfy { component in
            !component.isEmpty && component != "." && component != ".."
                && !component.contains("\0")
        }
    }

    static func isSafeFolder(_ value: String) -> Bool {
        value != "." && value != ".."
            && value.range(of: #"^[A-Za-z0-9][A-Za-z0-9._-]*$"#, options: .regularExpression) != nil
    }

    static func isSafeToken(_ value: String) -> Bool {
        guard (1...160).contains(value.utf8.count), !value.contains("://") else { return false }
        return value.range(of: #"^[A-Za-z0-9][A-Za-z0-9._:-]*$"#, options: .regularExpression) != nil
    }

    static func canonicalDigest(domain: String, fields: [String]) -> String {
        var hasher = SHA256()
        for field in [domain] + fields {
            let data = Data(field.utf8)
            var length = UInt64(data.count).bigEndian
            withUnsafeBytes(of: &length) { hasher.update(bufferPointer: $0) }
            hasher.update(data: data)
        }
        return hasher.finalize().map { String(format: "%02x", $0) }.joined()
    }
}

private enum SharedComponentFileSystem {
    struct FileSnapshot: Equatable {
        let device: UInt64
        let inode: UInt64
        let size: Int64
        let modificationNanoseconds: Int64
    }

    struct DirectorySnapshot {
        enum Entry: Equatable {
            case directory
            case file(FileSnapshot)
        }

        let entries: [String: Entry]
    }

    static func containedURL(root: URL, relativePath: String) throws -> URL {
        guard SharedComponentIdentityValidation.isSafeRelativePath(relativePath) else {
            throw SharedModelComponentStoreError.invalidRelativePath
        }
        let root = root.standardizedFileURL
        try rejectSymlinkedAncestors(root: root, relativePath: relativePath)
        let candidate = root.appendingPathComponent(relativePath, isDirectory: false).standardizedFileURL
        guard candidate.path.hasPrefix(root.path + "/") else {
            throw SharedModelComponentStoreError.invalidRelativePath
        }
        return candidate
    }

    /// Rejects an existing symbolic-link root or intermediate directory before
    /// any open, hash, copy, or hard-link operation. Standardized path strings
    /// alone do not prevent a hostile `component/` directory from redirecting
    /// traversal outside the governed model/staging root.
    private static func rejectSymlinkedAncestors(
        root: URL,
        relativePath: String
    ) throws {
        let manager = FileManager.default
        if manager.fileExists(atPath: root.path) {
            let values = try root.resourceValues(forKeys: [.isSymbolicLinkKey])
            guard values.isSymbolicLink != true else {
                throw SharedModelComponentStoreError.invalidRelativePath
            }
        }

        let components = relativePath.split(separator: "/").dropLast()
        var current = root
        for component in components {
            current.appendPathComponent(String(component), isDirectory: true)
            guard manager.fileExists(atPath: current.path) else { continue }
            let values = try current.resourceValues(
                forKeys: [.isDirectoryKey, .isSymbolicLinkKey]
            )
            guard values.isSymbolicLink != true, values.isDirectory == true else {
                throw SharedModelComponentStoreError.invalidRelativePath
            }
        }
    }

    static func isRegularFileWithoutSymlink(_ url: URL) -> Bool {
        guard let values = try? url.resourceValues(forKeys: [.isRegularFileKey, .isSymbolicLinkKey]) else {
            return false
        }
        return values.isRegularFile == true && values.isSymbolicLink != true
    }

    static func fileSize(_ url: URL, relativePath: String) throws -> Int64 {
        guard let size = try url.resourceValues(forKeys: [.fileSizeKey]).fileSize else {
            throw SharedModelComponentStoreError.missingFile(relativePath: relativePath)
        }
        return Int64(size)
    }

    static func sha256(_ url: URL, relativePath: String) throws -> String {
        guard let handle = try? FileHandle(forReadingFrom: url) else {
            throw SharedModelComponentStoreError.missingFile(relativePath: relativePath)
        }
        defer { try? handle.close() }
        return try FileStreamIO.sha256Hex(reading: handle)
    }

    static func snapshotIfPresent(_ url: URL) throws -> FileSnapshot? {
        guard FileManager.default.fileExists(atPath: url.path) else { return nil }
        return try snapshot(url)
    }

    static func snapshot(_ url: URL) throws -> FileSnapshot {
        let attributes = try FileManager.default.attributesOfItem(atPath: url.path)
        guard attributes[.type] as? FileAttributeType == .typeRegular,
              let device = (attributes[.systemNumber] as? NSNumber)?.uint64Value,
              let inode = (attributes[.systemFileNumber] as? NSNumber)?.uint64Value,
              let size = (attributes[.size] as? NSNumber)?.int64Value else {
            throw SharedModelComponentStoreError.corruptStoreLayout
        }
        let modification = (attributes[.modificationDate] as? Date) ?? .distantPast
        return FileSnapshot(
            device: device,
            inode: inode,
            size: size,
            modificationNanoseconds: Int64(modification.timeIntervalSince1970 * 1_000_000_000)
        )
    }

    /// Hard-link count and status-change time (ctime: set by publication's rename and chmod, and
    /// by every link or unlink), read without following a symlink. `nil` when the entry cannot be
    /// read; reclamation treats that as protected.
    static func linkStatus(_ url: URL) -> (linkCount: UInt64, changedAt: Date)? {
        var info = stat()
        let result = url.withUnsafeFileSystemRepresentation { path -> Int32 in
            guard let path else { return -1 }
            return lstat(path, &info)
        }
        guard result == 0 else { return nil }
        let changedAt = Date(
            timeIntervalSince1970: TimeInterval(info.st_ctimespec.tv_sec)
                + TimeInterval(info.st_ctimespec.tv_nsec) / 1_000_000_000
        )
        return (UInt64(info.st_nlink), changedAt)
    }

    static func sameFile(_ first: URL, _ second: URL) throws -> Bool {
        let lhs = try snapshot(first)
        let rhs = try snapshot(second)
        return lhs.device == rhs.device && lhs.inode == rhs.inode
    }

    static func hardLinkedReplica(source: URL, destination: URL) throws -> DirectorySnapshot {
        guard !FileManager.default.fileExists(atPath: destination.path) else {
            throw SharedModelComponentStoreError.corruptStoreLayout
        }
        try FileManager.default.createDirectory(at: destination, withIntermediateDirectories: true)
        guard let enumerator = FileManager.default.enumerator(
            at: source,
            includingPropertiesForKeys: [.isDirectoryKey, .isRegularFileKey, .isSymbolicLinkKey],
            options: []
        ) else {
            throw SharedModelComponentStoreError.modelNotFound
        }
        var entries: [String: DirectorySnapshot.Entry] = [:]
        for case let item as URL in enumerator {
            let relative = try relativePath(of: item, under: source)
            let values = try item.resourceValues(
                forKeys: [.isDirectoryKey, .isRegularFileKey, .isSymbolicLinkKey]
            )
            guard values.isSymbolicLink != true else {
                throw SharedModelComponentStoreError.nonRegularFile(relativePath: relative)
            }
            let destinationItem = try containedURL(root: destination, relativePath: relative)
            if values.isDirectory == true {
                try FileManager.default.createDirectory(at: destinationItem, withIntermediateDirectories: true)
                entries[relative] = .directory
            } else if values.isRegularFile == true {
                try FileManager.default.createDirectory(
                    at: destinationItem.deletingLastPathComponent(),
                    withIntermediateDirectories: true
                )
                try FileManager.default.linkItem(at: item, to: destinationItem)
                entries[relative] = .file(try snapshot(item))
            } else {
                throw SharedModelComponentStoreError.nonRegularFile(relativePath: relative)
            }
        }
        return DirectorySnapshot(entries: entries)
    }

    static func directoryMatches(_ root: URL, _ expected: DirectorySnapshot) throws -> Bool {
        guard let enumerator = FileManager.default.enumerator(
            at: root,
            includingPropertiesForKeys: [.isDirectoryKey, .isRegularFileKey, .isSymbolicLinkKey],
            options: []
        ) else { return false }
        var actualPaths = Set<String>()
        for case let item as URL in enumerator {
            let relative = try relativePath(of: item, under: root)
            actualPaths.insert(relative)
            guard let expectedValue = expected.entries[relative] else { return false }
            let values = try item.resourceValues(
                forKeys: [.isDirectoryKey, .isRegularFileKey, .isSymbolicLinkKey]
            )
            guard values.isSymbolicLink != true else { return false }
            switch expectedValue {
            case .file(let expectedFile):
                guard values.isRegularFile == true, try snapshot(item) == expectedFile else { return false }
            case .directory:
                guard values.isDirectory == true else { return false }
            }
        }
        return actualPaths == Set(expected.entries.keys)
    }

    static func relativePath(of item: URL, under root: URL) throws -> String {
        let resolvedRoot = root.resolvingSymlinksInPath().standardizedFileURL.path
        let resolvedItem = item.resolvingSymlinksInPath().standardizedFileURL.path
        guard resolvedItem.hasPrefix(resolvedRoot + "/") else {
            throw SharedModelComponentStoreError.invalidRelativePath
        }
        let relative = String(resolvedItem.dropFirst(resolvedRoot.count + 1))
        guard SharedComponentIdentityValidation.isSafeRelativePath(relative) else {
            throw SharedModelComponentStoreError.invalidRelativePath
        }
        return relative
    }

    static func atomicSwap(_ first: URL, _ second: URL) throws {
        let result = first.withUnsafeFileSystemRepresentation { firstPath in
            second.withUnsafeFileSystemRepresentation { secondPath in
                renameatx_np(AT_FDCWD, firstPath, AT_FDCWD, secondPath, UInt32(RENAME_SWAP))
            }
        }
        guard result == 0 else {
            throw SharedModelComponentStoreError.filesystemFailure(
                operation: "atomic-swap",
                code: errno
            )
        }
    }

    static func move(_ source: URL, to destination: URL, operation: String) throws {
        let result = source.withUnsafeFileSystemRepresentation { sourcePath in
            destination.withUnsafeFileSystemRepresentation { destinationPath in
                rename(sourcePath, destinationPath)
            }
        }
        guard result == 0 else {
            throw SharedModelComponentStoreError.filesystemFailure(operation: operation, code: errno)
        }
    }

    static func canonicalJSON<T: Encodable>(_ value: T) throws -> Data {
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.sortedKeys]
        return try encoder.encode(value)
    }
}
