import Foundation

/// Immutable, cross-platform artifact catalog used by production model downloads.
///
/// The product contract chooses a model and variant. This catalog supplies the exact pinned
/// repository identity plus a size and SHA-256 for every required file. A missing, staged, or
/// descriptor-mismatched entry is a hard error: production callers must never fall back to the
/// live repository file listing, because that path cannot authenticate ordinary Git files.
public struct ProductionModelCatalog: Decodable, Sendable {
    public enum Error: LocalizedError, Equatable, Sendable {
        case unreadable(String)
        case incomplete([String])
        case malformed(String)
        case artifactNotFound(modelID: String, variantID: String)
        case descriptorMismatch(identity: String, reason: String)

        public var errorDescription: String? {
            switch self {
            case .unreadable(let reason):
                return "The production model catalog could not be read: \(reason)"
            case .incomplete(let missing):
                return "The production model catalog is incomplete: \(missing.joined(separator: ", "))."
            case .malformed(let reason):
                return "The production model catalog is invalid: \(reason)"
            case .artifactNotFound(let modelID, let variantID):
                return "No authenticated model artifact exists for \(modelID):\(variantID)."
            case .descriptorMismatch(let identity, let reason):
                return "Authenticated artifact \(identity) does not match the model contract: \(reason)"
            }
        }
    }

    public struct File: Decodable, Hashable, Sendable {
        public let relativePath: String
        public let sizeBytes: Int64
        public let sha256: String
    }

    public struct Artifact: Decodable, Hashable, Sendable {
        public let modelID: String
        public let variantID: String
        public let platforms: Set<ModelArtifactPlatform>
        public let folder: String
        public let repo: String
        public let revision: String
        public let artifactVersion: String
        public let baseURL: URL
        public let totalBytes: Int64
        public let files: [File]
        public let sharedComponentIDs: [String]

        public var identity: String { "\(modelID):\(variantID)" }

        /// Exact downloader inputs. Every URL remains pinned to the catalog's immutable revision.
        public var downloadFiles: [HuggingFaceDownloader.RepoFile] {
            files.map { file in
                var url = baseURL
                for component in file.relativePath.split(separator: "/") {
                    url.appendPathComponent(String(component), isDirectory: false)
                }
                return HuggingFaceDownloader.RepoFile(
                    path: file.relativePath,
                    size: file.sizeBytes,
                    sha256: file.sha256,
                    absoluteURL: url
                )
            }
        }

        private enum CodingKeys: String, CodingKey {
            case modelID, variantID, platforms, folder, repo, revision, artifactVersion
            case baseURL, totalBytes, files, sharedComponentIDs
        }

        public init(from decoder: any Decoder) throws {
            let values = try decoder.container(keyedBy: CodingKeys.self)
            modelID = try values.decode(String.self, forKey: .modelID)
            variantID = try values.decode(String.self, forKey: .variantID)
            platforms = try values.decode(Set<ModelArtifactPlatform>.self, forKey: .platforms)
            folder = try values.decode(String.self, forKey: .folder)
            repo = try values.decode(String.self, forKey: .repo)
            revision = try values.decode(String.self, forKey: .revision)
            artifactVersion = try values.decode(String.self, forKey: .artifactVersion)
            baseURL = try values.decode(URL.self, forKey: .baseURL)
            totalBytes = try values.decode(Int64.self, forKey: .totalBytes)
            files = try values.decode([File].self, forKey: .files)
            sharedComponentIDs = try values.decodeIfPresent(
                [String].self,
                forKey: .sharedComponentIDs
            ) ?? []
        }
    }

    public struct SharedComponent: Decodable, Hashable, Sendable {
        public let id: String
        public let relativeRoot: String
        public let contentIdentity: SharedComponentContentIdentity
        public let compatibilityIdentity: SharedComponentCompatibilityIdentity
        /// Ordered authenticated artifact identities that can supply these exact bytes.
        public let sourceArtifactIdentities: [String]
    }

    public struct ArtifactDeliveryPlan: Sendable {
        public let artifact: Artifact
        public let filesToDownload: [HuggingFaceDownloader.RepoFile]
        public let installedFiles: [HuggingFaceDownloader.RepoFile]
        public let sharedComponentPlan: SharedComponentMigrationPlan?
        public let reusedComponentBytes: Int64

        public var reusedVerifiedComponent: Bool { reusedComponentBytes > 0 }
    }

    public let schemaVersion: Int
    public let catalogSchema: String
    public let activationState: String
    public let allowedArtifactHosts: Set<String>
    public let allowedRedirectHostSuffixes: Set<String>
    public let sourceDigests: [String: String]
    public let artifacts: [Artifact]
    public let sharedComponents: [SharedComponent]
    public let missingArtifactIdentities: [String]

    private enum CodingKeys: String, CodingKey {
        case schemaVersion, catalogSchema, activationState, allowedArtifactHosts
        case allowedRedirectHostSuffixes, sourceDigests, artifacts, sharedComponents
        case missingArtifactIdentities
    }

    public init(from decoder: any Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        schemaVersion = try values.decode(Int.self, forKey: .schemaVersion)
        catalogSchema = try values.decode(String.self, forKey: .catalogSchema)
        activationState = try values.decode(String.self, forKey: .activationState)
        allowedArtifactHosts = try values.decode(Set<String>.self, forKey: .allowedArtifactHosts)
        allowedRedirectHostSuffixes = try values.decode(
            Set<String>.self,
            forKey: .allowedRedirectHostSuffixes
        )
        sourceDigests = try values.decode([String: String].self, forKey: .sourceDigests)
        artifacts = try values.decode([Artifact].self, forKey: .artifacts)
        sharedComponents = try values.decodeIfPresent(
            [SharedComponent].self,
            forKey: .sharedComponents
        ) ?? []
        missingArtifactIdentities = try values.decode(
            [String].self,
            forKey: .missingArtifactIdentities
        )
    }

    public init(contentsOf url: URL) throws {
        do {
            self = try JSONDecoder().decode(Self.self, from: Data(contentsOf: url))
        } catch {
            throw Error.unreadable(error.localizedDescription)
        }
        try validate()
    }

    public var downloadURLPolicy: ModelArtifactURLPolicy {
        ModelArtifactURLPolicy(
            allowedInitialHosts: allowedArtifactHosts,
            allowedRedirectHostSuffixes: allowedRedirectHostSuffixes
        )
    }

    /// Resolve whether an artifact may omit shared bytes from the network. Store reuse is granted
    /// only after every blob passes its exact catalog size/SHA-256 identity. Regardless of reuse,
    /// schema-v2 artifacts receive a component installation plan so freshly downloaded bytes are
    /// published and the installed model is atomically hard-linked.
    public func deliveryPlan(
        for artifact: Artifact,
        modelsRoot: URL
    ) throws -> ArtifactDeliveryPlan {
        guard artifact.sharedComponentIDs.count <= 1 else {
            throw Error.malformed("artifact \(artifact.identity) has unsupported overlapping components")
        }
        guard let componentID = artifact.sharedComponentIDs.first else {
            return ArtifactDeliveryPlan(
                artifact: artifact,
                filesToDownload: artifact.downloadFiles,
                installedFiles: artifact.downloadFiles,
                sharedComponentPlan: nil,
                reusedComponentBytes: 0
            )
        }
        guard let component = sharedComponents.first(where: { $0.id == componentID }) else {
            throw Error.malformed("artifact \(artifact.identity) references an unknown shared component")
        }
        let manifest = try SharedComponentInstalledModelManifest(
            modelIdentity: artifact.identity,
            contentIdentity: component.contentIdentity,
            compatibilityIdentity: component.compatibilityIdentity
        )
        let componentPlan = try SharedComponentMigrationPlan(
            modelFolder: artifact.folder,
            manifest: manifest
        )
        let store = SharedModelComponentStore(modelsRoot: modelsRoot)
        do {
            _ = try reconcileInstalledArtifact(
                artifact,
                componentPlan: componentPlan,
                store: store
            )
        } catch {
            // A legacy directory that cannot pass catalog authentication contributes no bytes
            // to migration or reuse. Keep the error local to the reconciliation attempt so the
            // ordinary authenticated downloader can repair it from the network.
        }
        let canReuse = try store.containsVerified(component.contentIdentity)
        let componentPaths = Set(component.contentIdentity.files.map(\.relativePath))
        let filesToDownload = canReuse
            ? artifact.downloadFiles.filter { !componentPaths.contains($0.path) }
            : artifact.downloadFiles
        return ArtifactDeliveryPlan(
            artifact: artifact,
            filesToDownload: filesToDownload,
            installedFiles: artifact.downloadFiles,
            sharedComponentPlan: componentPlan,
            reusedComponentBytes: canReuse
                ? component.contentIdentity.files.reduce(0) { $0 + $1.byteCount }
                : 0
        )
    }

    /// Reconciles an already-installed schema-v2 artifact before a delivery plan decides whether
    /// shared bytes may be reused. This is entirely local: a legacy model is allowed to publish
    /// component blobs only after every catalog file has passed its exact size/SHA-256 check. A
    /// failed check leaves both the model directory and the shared store untouched.
    @discardableResult
    public func reconcileInstalledArtifact(
        _ artifact: Artifact,
        modelsRoot: URL
    ) throws -> SharedComponentMigrationResult? {
        guard artifact.sharedComponentIDs.count <= 1 else {
            throw Error.malformed("artifact \(artifact.identity) has unsupported overlapping components")
        }
        guard let componentID = artifact.sharedComponentIDs.first else {
            return nil
        }
        guard let component = sharedComponents.first(where: { $0.id == componentID }) else {
            throw Error.malformed("artifact \(artifact.identity) references an unknown shared component")
        }
        let manifest = try SharedComponentInstalledModelManifest(
            modelIdentity: artifact.identity,
            contentIdentity: component.contentIdentity,
            compatibilityIdentity: component.compatibilityIdentity
        )
        let componentPlan = try SharedComponentMigrationPlan(
            modelFolder: artifact.folder,
            manifest: manifest
        )
        return try reconcileInstalledArtifact(
            artifact,
            componentPlan: componentPlan,
            store: SharedModelComponentStore(modelsRoot: modelsRoot)
        )
    }

    /// Byte-count staleness probe for an installed artifact folder: the relative paths of
    /// catalog files that exist on disk with a different exact size than the current catalog
    /// identity. Detection only — a stale artifact is repaired through the ordinary
    /// authenticated delivery plan, which re-verifies every digest before install. Missing
    /// files are not reported here; path presence remains the availability check's domain.
    public func installedFileSizeMismatches(
        for artifact: Artifact,
        modelsRoot: URL,
        fileManager: FileManager = .default
    ) -> [String] {
        let folderURL = modelsRoot.appendingPathComponent(artifact.folder, isDirectory: true)
        return artifact.files.compactMap { file -> String? in
            let path = folderURL.appendingPathComponent(file.relativePath, isDirectory: false).path
            guard let attributes = try? fileManager.attributesOfItem(atPath: path),
                  let byteCount = (attributes[.size] as? NSNumber)?.int64Value else {
                return nil
            }
            return byteCount == file.sizeBytes ? nil : file.relativePath
        }.sorted()
    }

    private func reconcileInstalledArtifact(
        _ artifact: Artifact,
        componentPlan: SharedComponentMigrationPlan,
        store: SharedModelComponentStore
    ) throws -> SharedComponentMigrationResult? {
        let modelURL = store.modelsRoot.appendingPathComponent(artifact.folder, isDirectory: true)
        guard FileManager.default.fileExists(atPath: modelURL.path) else {
            return nil
        }
        let expectedFiles = try artifact.files.map {
            try SharedComponentFileIdentity(
                relativePath: $0.relativePath,
                byteCount: $0.sizeBytes,
                sha256: $0.sha256
            )
        }
        try store.validateInstalledModelFiles(
            modelFolder: artifact.folder,
            expectedFiles: expectedFiles
        )
        return try store.reconcileInstalledModel(componentPlan) { candidate in
            try store.validateModelFiles(
                at: candidate,
                expectedFiles: expectedFiles
            )
        }
    }

    /// Resolve one macOS production artifact and prove that every catalog field still agrees with
    /// the selected product descriptor before the downloader creates any task.
    public func artifact(
        modelID: String,
        variantID: String,
        folder: String,
        repo: String,
        revision: String?,
        artifactVersion: String,
        estimatedDownloadBytes: Int64?,
        requiredRelativePaths: [String]
    ) throws -> Artifact {
        try artifact(
            modelID: modelID,
            variantID: variantID,
            platform: .macOS,
            folder: folder,
            repo: repo,
            revision: revision,
            artifactVersion: artifactVersion,
            estimatedDownloadBytes: estimatedDownloadBytes,
            requiredRelativePaths: requiredRelativePaths
        )
    }

    public func artifact(
        modelID: String,
        variantID: String,
        platform: ModelArtifactPlatform,
        folder: String,
        repo: String,
        revision: String?,
        artifactVersion: String,
        estimatedDownloadBytes: Int64?,
        requiredRelativePaths: [String]
    ) throws -> Artifact {
        guard let artifact = artifacts.first(where: {
            $0.modelID == modelID && $0.variantID == variantID
        }) else {
            throw Error.artifactNotFound(modelID: modelID, variantID: variantID)
        }
        guard artifact.platforms.contains(platform) else {
            throw Error.descriptorMismatch(
                identity: artifact.identity,
                reason: "\(platform.rawValue) is not an allowed platform"
            )
        }
        let expectations: [(Bool, String)] = [
            (artifact.folder == folder, "folder differs"),
            (artifact.repo == repo, "repository differs"),
            (artifact.revision == revision, "revision differs"),
            (artifact.artifactVersion == artifactVersion, "artifact version differs"),
            (artifact.totalBytes == estimatedDownloadBytes, "payload size differs"),
            (Set(artifact.files.map(\.relativePath)) == Set(requiredRelativePaths), "required file set differs"),
        ]
        if let mismatch = expectations.first(where: { !$0.0 }) {
            throw Error.descriptorMismatch(identity: artifact.identity, reason: mismatch.1)
        }
        return artifact
    }

    /// Resolve an expanded registry descriptor (used by the CLI) without deriving a base model
    /// identity from its variant-scoped id. The immutable repository/folder/version tuple must
    /// identify exactly one catalog entry, after which the same full descriptor validation runs.
    public func artifactMatchingMacOSDescriptor(
        folder: String,
        repo: String,
        revision: String?,
        artifactVersion: String,
        estimatedDownloadBytes: Int64?,
        requiredRelativePaths: [String]
    ) throws -> Artifact {
        try artifactMatchingDescriptor(
            platform: .macOS,
            folder: folder,
            repo: repo,
            revision: revision,
            artifactVersion: artifactVersion,
            estimatedDownloadBytes: estimatedDownloadBytes,
            requiredRelativePaths: requiredRelativePaths
        )
    }

    public func artifactMatchingDescriptor(
        platform: ModelArtifactPlatform,
        folder: String,
        repo: String,
        revision: String?,
        artifactVersion: String,
        estimatedDownloadBytes: Int64?,
        requiredRelativePaths: [String]
    ) throws -> Artifact {
        let matches = artifacts.filter {
            $0.folder == folder && $0.repo == repo && $0.revision == revision
                && $0.artifactVersion == artifactVersion
        }
        guard matches.count == 1, let match = matches.first else {
            throw Error.descriptorMismatch(
                identity: repo,
                reason: "descriptor resolves to \(matches.count) catalog artifacts"
            )
        }
        return try artifact(
            modelID: match.modelID,
            variantID: match.variantID,
            platform: platform,
            folder: folder,
            repo: repo,
            revision: revision,
            artifactVersion: artifactVersion,
            estimatedDownloadBytes: estimatedDownloadBytes,
            requiredRelativePaths: requiredRelativePaths
        )
    }

    private func validate() throws {
        let supportedSchema = (schemaVersion == 1
            && catalogSchema == "config/model-catalog-schema-v1.json")
            || (schemaVersion == 2
                && catalogSchema == "config/model-catalog-schema-v2.json")
        guard supportedSchema else {
            throw Error.malformed("unsupported schema")
        }
        guard activationState == "complete", missingArtifactIdentities.isEmpty else {
            throw Error.incomplete(missingArtifactIdentities)
        }
        guard !allowedArtifactHosts.isEmpty, !allowedRedirectHostSuffixes.isEmpty else {
            throw Error.malformed("URL host policy is empty")
        }
        guard !artifacts.isEmpty else {
            throw Error.malformed("artifact list is empty")
        }

        var identities = Set<String>()
        for artifact in artifacts {
            guard identities.insert(artifact.identity).inserted else {
                throw Error.malformed("duplicate artifact \(artifact.identity)")
            }
            guard Self.isSafeIdentity(artifact.modelID), Self.isSafeIdentity(artifact.variantID),
                  Self.isSafeIdentity(artifact.artifactVersion), Self.isSafeFolder(artifact.folder),
                  Self.isPinnedRevision(artifact.revision), Self.isRepo(artifact.repo) else {
                throw Error.malformed("unsafe identity for \(artifact.identity)")
            }
            guard artifact.totalBytes > 0, !artifact.files.isEmpty,
                  artifact.totalBytes == artifact.files.reduce(Int64(0), { $0 + $1.sizeBytes }) else {
                throw Error.malformed("incorrect total size for \(artifact.identity)")
            }
            guard let components = URLComponents(url: artifact.baseURL, resolvingAgainstBaseURL: false),
                  components.scheme == "https", components.user == nil, components.password == nil,
                  components.port == nil || components.port == 443,
                  let host = components.host?.lowercased(), allowedArtifactHosts.contains(host),
                  components.query == nil, components.fragment == nil,
                  components.percentEncodedPath == "/\(artifact.repo)/resolve/\(artifact.revision)" else {
                throw Error.malformed("unpinned or untrusted base URL for \(artifact.identity)")
            }

            var paths = Set<String>()
            for file in artifact.files {
                guard paths.insert(file.relativePath).inserted,
                      Self.isSafeRelativePath(file.relativePath), file.sizeBytes > 0,
                      Self.isSHA256(file.sha256) else {
                    throw Error.malformed("invalid file identity for \(artifact.identity)")
                }
            }
            guard artifact.sharedComponentIDs.count == Set(artifact.sharedComponentIDs).count else {
                throw Error.malformed("duplicate shared component for \(artifact.identity)")
            }
        }

        if schemaVersion == 1 {
            guard sharedComponents.isEmpty,
                  artifacts.allSatisfy({ $0.sharedComponentIDs.isEmpty }) else {
                throw Error.malformed("schema-v1 catalog contains shared-component metadata")
            }
            return
        }

        guard !sharedComponents.isEmpty else {
            throw Error.malformed("schema-v2 catalog has no shared components")
        }
        var componentIDs = Set<String>()
        for component in sharedComponents {
            guard Self.isSafeIdentity(component.id), componentIDs.insert(component.id).inserted,
                  Self.isSafeRelativePath(component.relativeRoot),
                  component.compatibilityIdentity.contentDigest == component.contentIdentity.digest,
                  !component.sourceArtifactIdentities.isEmpty,
                  component.sourceArtifactIdentities.count == Set(component.sourceArtifactIdentities).count else {
                throw Error.malformed("invalid shared component \(component.id)")
            }
            guard component.contentIdentity.files.allSatisfy({
                $0.relativePath.hasPrefix(component.relativeRoot + "/")
            }) else {
                throw Error.malformed("shared component \(component.id) escapes its relative root")
            }
            for sourceIdentity in component.sourceArtifactIdentities {
                guard let source = artifacts.first(where: { $0.identity == sourceIdentity }) else {
                    throw Error.malformed("shared component \(component.id) has unknown source")
                }
                try Self.validate(component: component, against: source)
            }
        }
        for artifact in artifacts {
            guard artifact.sharedComponentIDs.count == 1,
                  let component = sharedComponents.first(where: {
                      $0.id == artifact.sharedComponentIDs[0]
                  }) else {
                throw Error.malformed("artifact \(artifact.identity) lacks shared component identity")
            }
            try Self.validate(component: component, against: artifact)
        }
    }

    private static func validate(component: SharedComponent, against artifact: Artifact) throws {
        let filesByPath = Dictionary(uniqueKeysWithValues: artifact.files.map { ($0.relativePath, $0) })
        for componentFile in component.contentIdentity.files {
            guard let artifactFile = filesByPath[componentFile.relativePath],
                  artifactFile.sizeBytes == componentFile.byteCount,
                  artifactFile.sha256 == componentFile.sha256 else {
                throw Error.malformed(
                    "shared component \(component.id) differs in \(artifact.identity)"
                )
            }
        }
    }

    private static func isSafeIdentity(_ value: String) -> Bool {
        !value.isEmpty && value == value.trimmingCharacters(in: .whitespacesAndNewlines)
            && !value.contains("/") && !value.contains("\\") && !value.contains("://")
    }

    private static func isSafeFolder(_ value: String) -> Bool {
        isSafeIdentity(value) && value != "." && value != ".."
    }

    private static func isRepo(_ value: String) -> Bool {
        let components = value.split(separator: "/", omittingEmptySubsequences: false)
        return components.count == 2 && components.allSatisfy { !$0.isEmpty && $0 != "." && $0 != ".." }
    }

    private static func isPinnedRevision(_ value: String) -> Bool {
        value.count == 40 && value.unicodeScalars.allSatisfy {
            CharacterSet(charactersIn: "0123456789abcdef").contains($0)
        }
    }

    private static func isSHA256(_ value: String) -> Bool {
        value.count == 64 && value.unicodeScalars.allSatisfy {
            CharacterSet(charactersIn: "0123456789abcdef").contains($0)
        }
    }

    private static func isSafeRelativePath(_ value: String) -> Bool {
        guard !value.isEmpty, !value.hasPrefix("/"), !value.contains("\\"),
              value.removingPercentEncoding == value else { return false }
        let components = value.split(separator: "/", omittingEmptySubsequences: false)
        return !components.isEmpty && components.allSatisfy { !$0.isEmpty && $0 != "." && $0 != ".." }
    }
}
