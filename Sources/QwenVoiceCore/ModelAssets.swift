import CryptoKit
import Foundation

public enum ModelAssetScope: String, Codable, Hashable, Sendable {
    case shared
    case modelSpecific
}

public struct ModelAssetArtifact: Hashable, Codable, Sendable {
    public let relativePath: String
    public let scope: ModelAssetScope

    public init(relativePath: String, scope: ModelAssetScope) {
        self.relativePath = relativePath
        self.scope = scope
    }
}

public struct ModelAssetDescriptor: Identifiable, Hashable, Codable, Sendable {
    public let model: ModelDescriptor
    public let version: String
    public let artifacts: [ModelAssetArtifact]

    public init(model: ModelDescriptor, version: String, artifacts: [ModelAssetArtifact]) {
        self.model = model
        self.version = version
        self.artifacts = artifacts
    }

    public var id: String {
        model.id
    }

    public var name: String {
        model.name
    }

    public var installFolder: String {
        model.folder
    }
}

public struct AssetIntegrity: Hashable, Codable, Sendable {
    public enum Status: String, Codable, Hashable, Sendable {
        case missing
        case incomplete
        case verified
    }

    public let status: Status
    public let localRootPath: String
    public let missingRelativePaths: [String]
    public let presentRelativePaths: [String]
    public let sizeBytes: Int64

    public init(
        status: Status,
        localRootPath: String,
        missingRelativePaths: [String],
        presentRelativePaths: [String],
        sizeBytes: Int64
    ) {
        self.status = status
        self.localRootPath = localRootPath
        self.missingRelativePaths = missingRelativePaths
        self.presentRelativePaths = presentRelativePaths
        self.sizeBytes = sizeBytes
    }

    public var isComplete: Bool {
        status == .verified
    }

    public var localRootURL: URL {
        URL(fileURLWithPath: localRootPath, isDirectory: true)
    }
}

public struct ModelAssetIntegrityManifest: Hashable, Codable, Sendable {
    public static let filename = ".qwenvoice-model-integrity.json"
    public static let currentSchemaVersion = 2
    public static let supportedSchemaVersions: Set<Int> = [1, 2]

    public let schemaVersion: Int
    public let repo: String
    public let revision: String
    public let targetFolder: String
    public let createdAtUTC: String
    public let files: [FileEntry]
    public let sharedComponentContentIdentity: SharedComponentContentIdentity?
    public let sharedComponentCompatibilityIdentity: SharedComponentCompatibilityIdentity?

    enum CodingKeys: String, CodingKey {
        case schemaVersion = "schema_version"
        case repo
        case revision
        case targetFolder = "target_folder"
        case createdAtUTC = "created_at_utc"
        case files
        case sharedComponentContentIdentity = "shared_component_content_identity"
        case sharedComponentCompatibilityIdentity = "shared_component_compatibility_identity"
    }

    public init(
        schemaVersion: Int = Self.currentSchemaVersion,
        repo: String,
        revision: String,
        targetFolder: String,
        createdAtUTC: String,
        files: [FileEntry],
        sharedComponentContentIdentity: SharedComponentContentIdentity? = nil,
        sharedComponentCompatibilityIdentity: SharedComponentCompatibilityIdentity? = nil
    ) {
        self.schemaVersion = schemaVersion
        self.repo = repo
        self.revision = revision
        self.targetFolder = targetFolder
        self.createdAtUTC = createdAtUTC
        self.files = files
        self.sharedComponentContentIdentity = sharedComponentContentIdentity
        self.sharedComponentCompatibilityIdentity = sharedComponentCompatibilityIdentity
    }

    public init(from decoder: any Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        let schemaVersion = try values.decode(Int.self, forKey: .schemaVersion)
        guard Self.supportedSchemaVersions.contains(schemaVersion) else {
            throw DecodingError.dataCorruptedError(
                forKey: .schemaVersion,
                in: values,
                debugDescription: "Unsupported model integrity manifest schema"
            )
        }
        let content = try values.decodeIfPresent(
            SharedComponentContentIdentity.self,
            forKey: .sharedComponentContentIdentity
        )
        let compatibility = try values.decodeIfPresent(
            SharedComponentCompatibilityIdentity.self,
            forKey: .sharedComponentCompatibilityIdentity
        )
        guard (content == nil) == (compatibility == nil),
              compatibility?.contentDigest == content?.digest else {
            throw DecodingError.dataCorruptedError(
                forKey: .sharedComponentCompatibilityIdentity,
                in: values,
                debugDescription: "Incomplete or mismatched shared component identity"
            )
        }
        self.schemaVersion = schemaVersion
        repo = try values.decode(String.self, forKey: .repo)
        revision = try values.decode(String.self, forKey: .revision)
        targetFolder = try values.decode(String.self, forKey: .targetFolder)
        createdAtUTC = try values.decode(String.self, forKey: .createdAtUTC)
        files = try values.decode([FileEntry].self, forKey: .files)
        sharedComponentContentIdentity = content
        sharedComponentCompatibilityIdentity = compatibility
    }

    public struct FileEntry: Hashable, Codable, Sendable {
        public let path: String
        public let size: Int64
        public let sha256: String?

        public init(path: String, size: Int64, sha256: String?) {
            self.path = path
            self.size = size
            self.sha256 = sha256
        }
    }
}

/// How deep `LocalModelAssetStore.deepIntegrity` looks. `.manifestSizes` checks the
/// integrity manifest, the shared-component identity, that each file is a regular file
/// and its size, and never reads file contents, so it is safe on the main actor.
/// `.contentDigest` also verifies each file's SHA-256 (cached per path, size and
/// modification date), which reads gigabytes and belongs off the main actor.
public enum ModelAssetIntegrityDepth: Sendable {
    case manifestSizes
    case contentDigest
}

public enum ModelAssetDeepIntegrity: Hashable, Codable, Sendable {
    case unavailable(reason: String)
    case verified(checkedFiles: Int)
    case failed(message: String, failedRelativePaths: [String])

    public var isVerified: Bool {
        if case .verified = self {
            return true
        }
        return false
    }

    public var repairMessage: String? {
        switch self {
        case .unavailable:
            return nil
        case .verified:
            return nil
        case .failed(let message, _):
            return message
        }
    }
}

public enum ModelAssetState: Hashable, Codable, Sendable {
    case notInstalled
    case available(AssetIntegrity)
    case incomplete(AssetIntegrity)
    case downloading(downloadedBytes: Int64, totalBytes: Int64?)
    case deleting
    case failed(message: String)

    public var integrity: AssetIntegrity? {
        switch self {
        case .available(let integrity), .incomplete(let integrity):
            return integrity
        case .notInstalled, .downloading, .deleting, .failed:
            return nil
        }
    }
}

public protocol ModelAssetStore: Sendable {
    var rootDirectory: URL { get }
    var descriptors: [ModelAssetDescriptor] { get }

    func descriptor(id: String) -> ModelAssetDescriptor?
    func localRoot(for descriptor: ModelAssetDescriptor) -> URL
    func localURL(for descriptor: ModelAssetDescriptor, artifact: ModelAssetArtifact) -> URL
    func integrity(for descriptor: ModelAssetDescriptor) -> AssetIntegrity
    func state(for descriptor: ModelAssetDescriptor) -> ModelAssetState
}

public struct LocalModelAssetStore: ModelAssetStore, Hashable, Sendable {
    static let legacyInstallFolderNames: Set<String> = [
        "Qwen3-TTS-12Hz-1.7B-CustomVoice-8bit",
        "Qwen3-TTS-12Hz-1.7B-VoiceDesign-8bit",
        "Qwen3-TTS-12Hz-1.7B-Base-8bit",
    ]

    public let rootDirectory: URL
    public let descriptors: [ModelAssetDescriptor]
    public let storeVersionSeed: String

    /// Process-lifetime cache of verified SHA-256 digests so `deepIntegrity` doesn't
    /// re-hash multi-GB model files on every status refresh.
    private static let integrityHashCache = IntegrityHashCache()

    public init(
        modelRegistry: any ModelRegistry,
        rootDirectory: URL,
        storeVersionSeed: String
    ) {
        self.rootDirectory = rootDirectory
        self.storeVersionSeed = storeVersionSeed
        self.descriptors = modelRegistry.models.map { model in
            ModelAssetDescriptor(
                model: model,
                version: Self.makeVersion(seed: storeVersionSeed, model: model),
                artifacts: model.requiredRelativePaths.map {
                    ModelAssetArtifact(relativePath: $0, scope: .modelSpecific)
                }
            )
        }
        Self.cleanupLegacyInstallFolders(
            at: rootDirectory,
            activeInstallFolders: Set(descriptors.map(\.installFolder))
        )
    }

    public init(
        rootDirectory: URL,
        descriptors: [ModelAssetDescriptor],
        storeVersionSeed: String = "manual"
    ) {
        self.rootDirectory = rootDirectory
        self.storeVersionSeed = storeVersionSeed
        self.descriptors = descriptors
    }

    public func descriptor(id: String) -> ModelAssetDescriptor? {
        descriptors.first { $0.id == id }
    }

    public func localRoot(for descriptor: ModelAssetDescriptor) -> URL {
        rootDirectory.appendingPathComponent(descriptor.installFolder, isDirectory: true)
    }

    public func localURL(for descriptor: ModelAssetDescriptor, artifact: ModelAssetArtifact) -> URL {
        localRoot(for: descriptor).appendingPathComponent(artifact.relativePath)
    }

    public func integrity(for descriptor: ModelAssetDescriptor) -> AssetIntegrity {
        // Inventory check only: downloads verify size and SHA-256 from
        // Hugging Face metadata before files land here. This store answers
        // whether the required installed files are present, not whether a
        // local directory is cryptographically trustworthy after mutation.
        let fileManager = FileManager.default
        let root = localRoot(for: descriptor)
        var present: [String] = []
        var missing: [String] = []

        for artifact in descriptor.artifacts {
            let url = localURL(for: descriptor, artifact: artifact)
            if fileManager.fileExists(atPath: url.path) {
                present.append(artifact.relativePath)
            } else {
                missing.append(artifact.relativePath)
            }
        }

        let status: AssetIntegrity.Status
        if present.isEmpty {
            status = .missing
        } else if missing.isEmpty {
            status = .verified
        } else {
            status = .incomplete
        }

        return AssetIntegrity(
            status: status,
            localRootPath: root.path,
            missingRelativePaths: missing.sorted(),
            presentRelativePaths: present.sorted(),
            sizeBytes: Self.directorySize(at: root)
        )
    }

    /// The depth is explicit so no main-actor caller can hash model files by accident.
    public func deepIntegrity(
        for descriptor: ModelAssetDescriptor,
        depth: ModelAssetIntegrityDepth
    ) -> ModelAssetDeepIntegrity {
        let root = localRoot(for: descriptor)
        let manifestURL = root.appendingPathComponent(ModelAssetIntegrityManifest.filename, isDirectory: false)
        guard let manifestData = try? Data(contentsOf: manifestURL) else {
            return .unavailable(reason: "manifest unavailable")
        }
        guard let manifest = try? JSONDecoder().decode(ModelAssetIntegrityManifest.self, from: manifestData) else {
            return .unavailable(reason: "manifest unreadable")
        }
        guard ModelAssetIntegrityManifest.supportedSchemaVersions.contains(manifest.schemaVersion) else {
            return .unavailable(reason: "manifest schema unsupported")
        }
        guard manifest.targetFolder == descriptor.installFolder else {
            return .unavailable(reason: "manifest target mismatch")
        }

        let requiredPaths = Set(descriptor.artifacts.map(\.relativePath))
        let entries = manifest.files.filter { requiredPaths.contains($0.path) }
        guard Set(entries.map(\.path)) == requiredPaths else {
            return .unavailable(reason: "manifest has no required file entries")
        }

        if let content = manifest.sharedComponentContentIdentity,
           let compatibility = manifest.sharedComponentCompatibilityIdentity {
            let sharedManifestURL = root.appendingPathComponent(
                SharedComponentInstalledModelManifest.filename,
                isDirectory: false
            )
            guard let sharedData = try? Data(contentsOf: sharedManifestURL),
                  let shared = try? JSONDecoder().decode(
                      SharedComponentInstalledModelManifest.self,
                      from: sharedData
                  ),
                  shared.contentIdentity == content,
                  shared.compatibilityIdentity == compatibility else {
                return .failed(
                    message: "The installed shared-component identity is missing or inconsistent.",
                    failedRelativePaths: content.files.map(\.relativePath).sorted()
                )
            }
        }

        var failures: [String] = []
        for entry in entries {
            let url = root.appendingPathComponent(entry.path, isDirectory: false)
            guard FileManager.default.fileExists(atPath: url.path),
                  let values = try? url.resourceValues(
                      forKeys: [.isRegularFileKey, .isSymbolicLinkKey]
                  ),
                  values.isRegularFile == true,
                  values.isSymbolicLink != true else {
                failures.append(entry.path)
                continue
            }
            if let actualSize = Self.fileSize(at: url), actualSize != entry.size {
                failures.append(entry.path)
                continue
            }
            if depth == .contentDigest, let expectedHash = Self.normalizedSHA256(entry.sha256) {
                guard let actualHash = Self.integrityHashCache.cachedSHA256(for: url),
                      actualHash == expectedHash else {
                    failures.append(entry.path)
                    continue
                }
            }
        }

        guard failures.isEmpty else {
            let message = failures.count == 1
                ? "One installed model file failed deep integrity verification."
                : "\(failures.count) installed model files failed deep integrity verification."
            return .failed(message: message, failedRelativePaths: failures.sorted())
        }
        return .verified(checkedFiles: entries.count)
    }

    public func state(for descriptor: ModelAssetDescriptor) -> ModelAssetState {
        let integrity = integrity(for: descriptor)
        switch integrity.status {
        case .missing:
            return .notInstalled
        case .verified:
            return .available(integrity)
        case .incomplete:
            return .incomplete(integrity)
        }
    }

    private static func makeVersion(seed: String, model: ModelDescriptor) -> String {
        let digest = SHA256.hash(
            data: Data(
                "\(seed)|\(model.id)|\(model.folder)|\(model.artifactVersion)|\(model.huggingFaceRepo)|\(model.huggingFaceRevision ?? "")".utf8
            )
        )
        return "store-\(digest.prefix(8).map { String(format: "%02x", $0) }.joined())"
    }

    private static func directorySize(at url: URL) -> Int64 {
        let fileManager = FileManager.default
        guard let enumerator = fileManager.enumerator(
            at: url,
            includingPropertiesForKeys: [.fileSizeKey],
            options: [.skipsHiddenFiles]
        ) else {
            return 0
        }

        var total: Int64 = 0
        for case let fileURL as URL in enumerator {
            if let size = try? fileURL.resourceValues(forKeys: [.fileSizeKey]).fileSize {
                total += Int64(size)
            }
        }
        return total
    }

    private static func fileSize(at url: URL) -> Int64? {
        guard let size = try? url.resourceValues(forKeys: [.fileSizeKey]).fileSize else {
            return nil
        }
        return Int64(size)
    }

    private static func normalizedSHA256(_ value: String?) -> String? {
        guard let value else { return nil }
        var normalized = value.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        if normalized.hasPrefix("sha256:") {
            normalized.removeFirst("sha256:".count)
        }
        guard normalized.range(of: #"^[0-9a-f]{64}$"#, options: .regularExpression) != nil else {
            return nil
        }
        return normalized
    }

    private static func sha256Hex(for url: URL) throws -> String {
        try FileStreamIO.sha256Hex(of: url)
    }

    /// Seeds the digest cache with a SHA-256 this process already verified while
    /// downloading (a same-process receipt), so the first content pass does not hash a
    /// freshly installed file again. Recorded only while the installed file is still the
    /// verified one: same size, modification time and, when known, file identifier.
    @discardableResult
    static func recordVerifiedDigest(for url: URL, receipt: VerifiedArtifactReceipt) -> Bool {
        guard let expected = normalizedSHA256(receipt.expectedSHA256) else { return false }
        return integrityHashCache.record(
            sha256: expected,
            for: url,
            size: receipt.fileSize,
            modificationTimeNanoseconds: receipt.modificationTimeNanoseconds,
            fileIdentifier: receipt.fileIdentifier
        )
    }

    private static func cleanupLegacyInstallFolders(
        at rootDirectory: URL,
        activeInstallFolders: Set<String>,
        fileManager: FileManager = .default
    ) {
        let managedRoot = rootDirectory.standardizedFileURL
        let obsoleteFolders = legacyInstallFolderNames.subtracting(activeInstallFolders)
        guard !obsoleteFolders.isEmpty else { return }

        for folder in obsoleteFolders {
            let folderURL = managedRoot.appendingPathComponent(folder, isDirectory: true)
            guard folderURL.deletingLastPathComponent() == managedRoot else {
                continue
            }
            guard fileManager.fileExists(atPath: folderURL.path) else {
                continue
            }
            try? fileManager.removeItem(at: folderURL)
        }
    }

    /// Thread-safe, process-lifetime cache of verified file SHA-256 digests, keyed by
    /// path + size + modification date. Keeps `deepIntegrity` from re-hashing multi-GB
    /// model files on every status refresh once a file has been verified.
    private final class IntegrityHashCache: @unchecked Sendable {
        private struct Entry {
            let size: Int64
            let modificationDate: Date
            let sha256: String
        }

        private var entries: [String: Entry] = [:]
        private let lock = NSLock()

        /// Returns the cached SHA-256 for `url` when its size + modification date match a
        /// prior computation; otherwise hashes the file (once) and caches the result.
        /// Returns nil if the file can't be stat'd or hashed. A size/mtime change (a
        /// reinstall) invalidates the entry automatically.
        func cachedSHA256(for url: URL) -> String? {
            guard let values = try? url.resourceValues(forKeys: [.fileSizeKey, .contentModificationDateKey]),
                  let fileSize = values.fileSize else {
                return nil
            }
            let size = Int64(fileSize)
            let modificationDate = values.contentModificationDate ?? .distantPast
            let key = url.path

            lock.lock()
            if let entry = entries[key], entry.size == size, entry.modificationDate == modificationDate {
                let cached = entry.sha256
                lock.unlock()
                return cached
            }
            lock.unlock()

            // Hash outside the lock — this is the expensive multi-GB read.
            guard let computed = try? LocalModelAssetStore.sha256Hex(for: url) else {
                return nil
            }

            lock.lock()
            entries[key] = Entry(size: size, modificationDate: modificationDate, sha256: computed)
            lock.unlock()
            return computed
        }

        /// Stores an already-verified digest when the file on disk still matches the
        /// verified size, modification time and file identifier; otherwise leaves the
        /// cache alone so the next content pass hashes the file.
        func record(
            sha256: String,
            for url: URL,
            size: Int64,
            modificationTimeNanoseconds: Int64,
            fileIdentifier: UInt64?
        ) -> Bool {
            guard let attributes = try? FileManager.default.attributesOfItem(atPath: url.path),
                  let currentSize = (attributes[.size] as? NSNumber)?.int64Value,
                  let modificationDate = attributes[.modificationDate] as? Date,
                  currentSize == size,
                  Int64(modificationDate.timeIntervalSince1970 * 1_000_000_000) == modificationTimeNanoseconds
            else {
                return false
            }
            if let fileIdentifier,
               (attributes[.systemFileNumber] as? NSNumber)?.uint64Value != fileIdentifier {
                return false
            }
            // The lookup side keys on resource values; store the same representation,
            // and re-check the attributes so a file replaced between the two reads is
            // never stored under the new file's metadata.
            guard let values = try? url.resourceValues(forKeys: [.fileSizeKey, .contentModificationDateKey]),
                  let fileSize = values.fileSize,
                  let recheck = try? FileManager.default.attributesOfItem(atPath: url.path),
                  (recheck[.size] as? NSNumber)?.int64Value == size,
                  (recheck[.modificationDate] as? Date) == modificationDate,
                  (recheck[.systemFileNumber] as? NSNumber)?.uint64Value
                      == (attributes[.systemFileNumber] as? NSNumber)?.uint64Value else {
                return false
            }
            lock.lock()
            entries[url.path] = Entry(
                size: Int64(fileSize),
                modificationDate: values.contentModificationDate ?? .distantPast,
                sha256: sha256
            )
            lock.unlock()
            return true
        }
    }
}
