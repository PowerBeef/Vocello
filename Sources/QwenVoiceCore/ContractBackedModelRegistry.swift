import Foundation

private struct ContractManifest: Decodable {
    let defaultSpeaker: String
    let speakers: [String: [String]]
    let speakerMetadata: [String: SpeakerMetadata]?
    let models: [ModelDescriptor]
}

/// Three-state availability summary for a registry-resolved model. The
/// `unavailable` case carries the resolved descriptor and the relative paths
/// that are missing under the install directory so callers can surface a
/// precise download/repair prompt without re-running the file walk.
///
/// Apple-platform availability surface for contract-backed model descriptors.
public enum ModelAvailability: Equatable, Sendable {
    case unknown
    case unavailable(descriptor: ModelDescriptor, missingRequiredPaths: [String])
    case available(descriptor: ModelDescriptor)
}

public struct ContractBackedModelRegistry: ModelRegistry, Hashable, Sendable {
    public enum Error: LocalizedError, Equatable {
        case missingModels
        case missingSpeakers
        case defaultSpeakerNotFound(String)
        case duplicateModelIDs([String])
        case duplicateModes([String])
        case invalidSpeaker(id: String, reason: String)
        case invalidModel(id: String, reason: String)

        public var errorDescription: String? {
            switch self {
            case .missingModels:
                return "Manifest must define at least one model."
            case .missingSpeakers:
                return "Manifest must define at least one speaker group."
            case .defaultSpeakerNotFound(let id):
                return "Default speaker '\(id)' is not present in the manifest speaker list."
            case .duplicateModelIDs(let ids):
                return "Manifest contains duplicate model ids: \(ids.joined(separator: ", "))."
            case .duplicateModes(let modes):
                return "Manifest contains duplicate model modes: \(modes.joined(separator: ", "))."
            case .invalidSpeaker(let id, let reason):
                return "Speaker '\(id)' is invalid: \(reason)"
            case .invalidModel(let id, let reason):
                return "Model '\(id)' is invalid: \(reason)"
            }
        }
    }

    public let manifestURL: URL
    public let models: [ModelDescriptor]
    public let defaultSpeaker: SpeakerDescriptor
    public let groupedSpeakers: [String: [SpeakerDescriptor]]

    public init(manifestURL: URL) throws {
        let data = try Data(contentsOf: manifestURL)
        let manifest = try JSONDecoder().decode(ContractManifest.self, from: data)
        try Self.validate(manifest)

        self.manifestURL = manifestURL
        self.models = manifest.models

        var grouped: [String: [SpeakerDescriptor]] = [:]
        let metadata = manifest.speakerMetadata ?? [:]
        for group in manifest.speakers.keys.sorted() {
            let speakers = manifest.speakers[group] ?? []
            grouped[group] = speakers.map { speakerID in
                SpeakerDescriptor(
                    group: group,
                    id: speakerID,
                    metadata: metadata[speakerID]
                )
            }
        }
        self.groupedSpeakers = grouped
        self.defaultSpeaker = grouped
            .values
            .flatMap { $0 }
            .first(where: { $0.id == manifest.defaultSpeaker })!
    }

    private init(
        manifestURL: URL,
        models: [ModelDescriptor],
        defaultSpeaker: SpeakerDescriptor,
        groupedSpeakers: [String: [SpeakerDescriptor]]
    ) {
        self.manifestURL = manifestURL
        self.models = models
        self.defaultSpeaker = defaultSpeaker
        self.groupedSpeakers = groupedSpeakers
    }

    public var allSpeakers: [SpeakerDescriptor] {
        groupedSpeakers.keys.sorted().flatMap { groupedSpeakers[$0] ?? [] }
    }

    public func model(for mode: GenerationMode) -> ModelDescriptor? {
        models.first { $0.mode == mode }
    }

    public func model(id: String) -> ModelDescriptor? {
        models.first { $0.id == id }
    }

    /// Idiomatic alias for `model(id:)`. Used by iOS model-delivery and
    /// model-management call sites that prefer `descriptor(id:)` naming
    /// over `model(id:)`.
    public func descriptor(id: String) -> ModelDescriptor? {
        model(id: id)
    }

    /// Three-state availability summary: returns `.unknown` when the model
    /// id isn't in the manifest, `.unavailable(descriptor, missing)` when one
    /// or more required relative paths are missing under the install
    /// directory, otherwise `.available(descriptor)`.
    public func availability(
        forModelID modelID: String,
        in modelsDirectory: URL,
        fileManager: FileManager = .default
    ) -> ModelAvailability {
        guard let descriptor = descriptor(id: modelID) else {
            return .unknown
        }

        let installDirectory = descriptor.installDirectory(in: modelsDirectory)
        let missingRequiredPaths = descriptor.requiredRelativePaths.filter { relativePath in
            !fileManager.fileExists(
                atPath: installDirectory.appendingPathComponent(relativePath).path
            )
        }

        if missingRequiredPaths.isEmpty {
            return .available(descriptor: descriptor)
        }

        return .unavailable(
            descriptor: descriptor,
            missingRequiredPaths: missingRequiredPaths.sorted()
        )
    }

    public func resolvedForPlatform(_ platform: ModelArtifactPlatform) -> ContractBackedModelRegistry {
        resolvedForPlatform(platform, deviceClass: nil)
    }

    public func resolvedForPlatform(
        _ platform: ModelArtifactPlatform,
        deviceClass: NativeDeviceMemoryClass?
    ) -> ContractBackedModelRegistry {
        ContractBackedModelRegistry(
            manifestURL: manifestURL,
            models: models.map { $0.resolvedForPlatform(platform, deviceClass: deviceClass) },
            defaultSpeaker: defaultSpeaker,
            groupedSpeakers: groupedSpeakers
        )
    }

    public func expandedForPlatform(
        _ platform: ModelArtifactPlatform,
        deviceClass: NativeDeviceMemoryClass?,
        includeBaseAliases: Bool
    ) -> ContractBackedModelRegistry {
        let expandedModels = models.flatMap { model -> [ModelDescriptor] in
            let variants = model.platformVariants(for: platform)
            guard !variants.isEmpty else { return [model] }

            var descriptors: [ModelDescriptor] = []
            if includeBaseAliases {
                descriptors.append(model.resolvedForPlatform(platform, deviceClass: deviceClass))
            }
            descriptors.append(contentsOf: variants.map { variant in
                model.resolved(with: variant, id: model.variantScopedID(for: variant))
            })
            return descriptors
        }

        return ContractBackedModelRegistry(
            manifestURL: manifestURL,
            models: expandedModels,
            defaultSpeaker: defaultSpeaker,
            groupedSpeakers: groupedSpeakers
        )
    }

    /// RF-59: the retired install folders that may be deleted now. A model's `retiredFolders` are
    /// reclaimable once `isVerified` says the model's current artifact is installed and verified, so
    /// a user is never left without a model for a mode. `isVerified` must mean verified against
    /// the catalog's receipts, not only present. Only folders present under `modelsDirectory`, or
    /// with a download still staged for them, are returned, each once, sorted.
    public func retiredFoldersToReclaim(
        in modelsDirectory: URL,
        isVerified: (ModelDescriptor) -> Bool
    ) -> [String] {
        RetiredModelReclamation.folders(of: models, in: modelsDirectory, isVerified: isVerified)
    }

    /// RF-59: removes the retired folders `retiredFoldersToReclaim` returns, through the shared
    /// component store. Synchronous and possibly slow: call it off the main actor.
    public func reclaimRetiredFolders(
        in modelsDirectory: URL,
        isVerified: (ModelDescriptor) -> Bool
    ) -> RetiredModelReclamation {
        let folders = retiredFoldersToReclaim(in: modelsDirectory, isVerified: isVerified)
        guard !folders.isEmpty else { return RetiredModelReclamation(removed: [], failed: [:]) }
        return SharedModelComponentStore(modelsRoot: modelsDirectory).reclaimRetiredFolders(folders)
    }

    /// Lists required model files that the manifest declares but cannot be
    /// found under the supplied root. Callers use this to surface missing
    /// assets at app launch instead of discovering the gap deep inside a
    /// later model-load (Tier 6). Non-fatal: returns an empty list when all
    /// required files resolve.
    public func missingRequiredFiles(installedUnder root: URL) -> [String] {
        var missing: [String] = []
        for model in models {
            let modelRoot = root.appendingPathComponent(model.folder, isDirectory: true)
            for relativePath in model.requiredRelativePaths {
                let candidate = modelRoot.appendingPathComponent(relativePath)
                if !FileManager.default.fileExists(atPath: candidate.path) {
                    missing.append("\(model.id)/\(relativePath)")
                }
            }
        }
        return missing
    }

    private static func validate(_ manifest: ContractManifest) throws {
        guard !manifest.models.isEmpty else {
            throw Error.missingModels
        }

        guard !manifest.speakers.isEmpty else {
            throw Error.missingSpeakers
        }

        let allSpeakers = manifest.speakers.keys.sorted().flatMap { manifest.speakers[$0] ?? [] }
        guard allSpeakers.contains(manifest.defaultSpeaker) else {
            throw Error.defaultSpeakerNotFound(manifest.defaultSpeaker)
        }
        try validateSpeakers(allSpeakers: allSpeakers, metadata: manifest.speakerMetadata)

        let duplicateModelIDs = duplicateValues(in: manifest.models.map(\.id))
        guard duplicateModelIDs.isEmpty else {
            throw Error.duplicateModelIDs(duplicateModelIDs)
        }

        let duplicateModes = duplicateValues(in: manifest.models.map(\.mode.rawValue))
        guard duplicateModes.isEmpty else {
            throw Error.duplicateModes(duplicateModes)
        }

        for model in manifest.models {
            try validate(model: model, context: model.id)
        }
        try validateRetiredFolders(manifest.models)
    }

    /// RF-59: a retired folder is a name the store's removal accepts (`ModelInstallFolderName`),
    /// listed once, and never a folder any model or variant of this contract installs into, so its
    /// reclamation can only remove what the contract no longer ships. Names compare without case,
    /// as the Mac's volume does.
    private static func validateRetiredFolders(_ models: [ModelDescriptor]) throws {
        let current = Set(models.flatMap { model in [model.folder] + model.variants.map(\.folder) }.map { $0.lowercased() })
        var seen = Set<String>()
        for model in models {
            for folder in model.retiredFolders {
                guard ModelInstallFolderName.isSafe(folder) else {
                    throw Error.invalidModel(id: model.id, reason: "retired folder '\(folder)' is not a model install folder name")
                }
                guard seen.insert(folder.lowercased()).inserted else {
                    throw Error.invalidModel(id: model.id, reason: "retired folder '\(folder)' is listed twice")
                }
                guard !current.contains(folder.lowercased()) else {
                    throw Error.invalidModel(id: model.id, reason: "retired folder '\(folder)' is a current install folder")
                }
            }
        }
    }

    private static func validateSpeakers(
        allSpeakers: [String],
        metadata: [String: SpeakerMetadata]?
    ) throws {
        let duplicateSpeakerIDs = duplicateValues(in: allSpeakers)
        guard duplicateSpeakerIDs.isEmpty else {
            throw Error.invalidSpeaker(
                id: duplicateSpeakerIDs.joined(separator: ", "),
                reason: "duplicate speaker id"
            )
        }

        guard let metadata else {
            return
        }

        let speakerSet = Set(allSpeakers)
        for speakerID in allSpeakers {
            guard metadata[speakerID] != nil else {
                throw Error.invalidSpeaker(id: speakerID, reason: "missing speakerMetadata entry")
            }
        }

        for (speakerID, speakerMetadata) in metadata {
            guard speakerSet.contains(speakerID) else {
                throw Error.invalidSpeaker(id: speakerID, reason: "metadata is not referenced by speakers")
            }
            guard !speakerMetadata.displayName.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
                throw Error.invalidSpeaker(id: speakerID, reason: "missing displayName")
            }
            guard !speakerMetadata.nativeLanguage.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
                throw Error.invalidSpeaker(id: speakerID, reason: "missing nativeLanguage")
            }
            guard !speakerMetadata.shortDescription.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
                throw Error.invalidSpeaker(id: speakerID, reason: "missing shortDescription")
            }
        }
    }

    private static func validate(model: ModelDescriptor, context: String) throws {
        guard !model.tier.isEmpty else {
            throw Error.invalidModel(id: context, reason: "missing tier")
        }
        guard !model.artifactVersion.isEmpty else {
            throw Error.invalidModel(id: context, reason: "missing artifactVersion")
        }
        try validateHuggingFaceRevision(model.huggingFaceRevision, context: context)
        guard !model.outputSubfolder.isEmpty else {
            throw Error.invalidModel(id: context, reason: "missing outputSubfolder")
        }
        guard !model.requiredRelativePaths.isEmpty else {
            throw Error.invalidModel(id: context, reason: "missing requiredRelativePaths")
        }
        if let estimatedDownloadBytes = model.estimatedDownloadBytes,
           estimatedDownloadBytes < 0 {
            throw Error.invalidModel(id: context, reason: "estimatedDownloadBytes must be non-negative")
        }

        for variant in model.variants {
            guard !variant.artifactVersion.isEmpty else {
                throw Error.invalidModel(id: context, reason: "variant '\(variant.id)' missing artifactVersion")
            }
            try validateHuggingFaceRevision(
                variant.huggingFaceRevision,
                context: "\(context) variant '\(variant.id)'"
            )
            guard !variant.requiredRelativePaths.isEmpty else {
                throw Error.invalidModel(id: context, reason: "variant '\(variant.id)' missing requiredRelativePaths")
            }
            if let estimatedDownloadBytes = variant.estimatedDownloadBytes,
               estimatedDownloadBytes < 0 {
                throw Error.invalidModel(id: context, reason: "variant '\(variant.id)' estimatedDownloadBytes must be non-negative")
            }
        }
    }

    private static func validateHuggingFaceRevision(_ revision: String?, context: String) throws {
        guard let revision,
              !revision.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
            throw Error.invalidModel(id: context, reason: "missing huggingFaceRevision")
        }
        let lowercaseHex = CharacterSet(charactersIn: "0123456789abcdef")
        guard revision.count == 40,
              revision.unicodeScalars.allSatisfy({ lowercaseHex.contains($0) }) else {
            throw Error.invalidModel(id: context, reason: "huggingFaceRevision must be a 40-character lowercase hex commit SHA")
        }
    }

    private static func duplicateValues(in values: [String]) -> [String] {
        var seen = Set<String>()
        var duplicates = Set<String>()

        for value in values {
            if !seen.insert(value).inserted {
                duplicates.insert(value)
            }
        }

        return duplicates.sorted()
    }
}
