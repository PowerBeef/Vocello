import Foundation
import QwenVoiceCore

private struct TTSContractManifest: Decodable {
    let defaultSpeaker: String
    let speakers: [String: [String]]
    let speakerDescriptors: [String: [SpeakerDescriptor]]
    let models: [TTSModel]

    static let empty = TTSContractManifest(
        defaultSpeaker: "",
        speakers: [:],
        speakerDescriptors: [:],
        models: []
    )
}

struct ContractLoadError: LocalizedError, Equatable, Sendable {
    let summary: String
    let details: String
    let manifestPath: String?

    var errorDescription: String? {
        details
    }
}

private struct TTSContractLoadState {
    let manifest: TTSContractManifest
    let manifestURL: URL?
    let loadError: ContractLoadError?
}

private final class TTSContractBundleLocator: NSObject { }

enum TTSContract {
    static var manifestURL: URL? {
        loadState.manifestURL
    }

    static var loadError: ContractLoadError? {
        loadState.loadError
    }

    static var models: [TTSModel] {
        loadState.manifest.models
    }

    static var defaultSpeaker: String {
        loadState.manifest.defaultSpeaker
    }

    static var groupedSpeakers: [String: [String]] {
        loadState.manifest.speakers
    }

    static var groupedSpeakerDescriptors: [String: [SpeakerDescriptor]] {
        loadState.manifest.speakerDescriptors
    }

    static var allSpeakers: [String] {
        loadState.manifest.speakers.keys.sorted().flatMap { loadState.manifest.speakers[$0] ?? [] }
    }

    static var allSpeakerDescriptors: [SpeakerDescriptor] {
        loadState.manifest.speakerDescriptors.keys.sorted().flatMap {
            loadState.manifest.speakerDescriptors[$0] ?? []
        }
    }

    static func speakerDescriptor(id: String) -> SpeakerDescriptor? {
        allSpeakerDescriptors.first { $0.id == id }
    }

    static func model(id: String) -> TTSModel? {
        if let exact = loadState.manifest.models.first(where: { $0.id == id }) {
            return exact
        }
        return loadState.manifest.models.first {
            $0.baseModelID == id && $0.isHardwareRecommended
        }
    }

    private static let loadState: TTSContractLoadState = loadManifestState()

    private static func loadManifestState() -> TTSContractLoadState {
        var locatedManifestURL: URL?
        do {
            let url = try locateManifestURL()
            locatedManifestURL = url
            let decoded = try resolvedManifest(
                from: url,
                deviceClass: NativeMemoryPolicyResolver.deviceClass()
            )
            try validate(decoded)
            return TTSContractLoadState(
                manifest: decoded,
                manifestURL: url,
                loadError: nil
            )
        } catch let error as ContractLoadError {
            return handleLoadFailure(error)
        } catch {
            let failure = ContractLoadError(
                summary: "Failed to load qwenvoice_contract.json",
                details: error.localizedDescription,
                manifestPath: locatedManifestURL?.path
            )
            return handleLoadFailure(failure)
        }
    }

    private static func resolvedManifest(
        from url: URL,
        deviceClass: NativeDeviceMemoryClass
    ) throws -> TTSContractManifest {
        let registry = try ContractBackedModelRegistry(manifestURL: url)
        let models = try registry.models.flatMap { descriptor -> [TTSModel] in
            let variants = descriptor.platformVariants(for: .macOS)
            guard !variants.isEmpty else {
                return [
                    try makeModel(
                        from: descriptor,
                        baseModelID: descriptor.id,
                        variantID: nil,
                        variantKind: nil,
                        isHardwareRecommended: true
                    ),
                ]
            }

            let recommendedVariant = descriptor.preferredVariant(
                for: .macOS,
                deviceClass: deviceClass
            )
            return try variants.map { variant in
                try makeModel(
                    from: descriptor.resolved(
                        with: variant,
                        id: descriptor.variantScopedID(for: variant)
                    ),
                    baseModelID: descriptor.id,
                    variantID: variant.id,
                    variantKind: TTSModelVariantKind(coreKind: variant.kind),
                    isHardwareRecommended: variant.id == recommendedVariant?.id
                )
            }
        }

        return TTSContractManifest(
            defaultSpeaker: registry.defaultSpeaker.id,
            speakers: registry.groupedSpeakers.mapValues { speakers in
                speakers.map(\.id)
            },
            speakerDescriptors: registry.groupedSpeakers,
            models: models
        )
    }

    private static func makeModel(
        from descriptor: ModelDescriptor,
        baseModelID: String,
        variantID: String?,
        variantKind: TTSModelVariantKind?,
        isHardwareRecommended: Bool
    ) throws -> TTSModel {
        guard let mode = GenerationMode(rawValue: descriptor.mode.rawValue) else {
            throw ValidationError("Model '\(descriptor.id)' declares unsupported mode '\(descriptor.mode.rawValue)'.")
        }
        return TTSModel(
            id: descriptor.id,
            name: descriptor.name,
            tier: descriptor.tier,
            folder: descriptor.folder,
            mode: mode,
            huggingFaceRepo: descriptor.huggingFaceRepo,
            huggingFaceRevision: descriptor.huggingFaceRevision,
            artifactVersion: descriptor.artifactVersion,
            outputSubfolder: descriptor.outputSubfolder,
            requiredRelativePaths: descriptor.requiredRelativePaths,
            baseModelID: baseModelID,
            variantID: variantID,
            variantKind: variantKind,
            estimatedDownloadBytes: descriptor.estimatedDownloadBytes,
            isHardwareRecommended: isHardwareRecommended,
            qwen3Capabilities: descriptor.qwen3Capabilities
        )
    }

    private static func handleLoadFailure(_ error: ContractLoadError) -> TTSContractLoadState {
        let manifestURL = error.manifestPath.map { URL(fileURLWithPath: $0) }
        return TTSContractLoadState(
            manifest: .empty,
            manifestURL: manifestURL,
            loadError: error
        )
    }

    private static func validate(_ manifest: TTSContractManifest) throws {
        guard !manifest.models.isEmpty else {
            throw ValidationError("Manifest must define at least one model.")
        }

        guard !manifest.speakers.isEmpty else {
            throw ValidationError("Manifest must define at least one speaker group.")
        }

        let allSpeakers = manifest.speakers.keys.sorted().flatMap { manifest.speakers[$0] ?? [] }
        guard allSpeakers.contains(manifest.defaultSpeaker) else {
            throw ValidationError("Default speaker '\(manifest.defaultSpeaker)' is not present in the manifest speaker list.")
        }

        let duplicateModelIDs = duplicateValues(in: manifest.models.map(\.id))
        guard duplicateModelIDs.isEmpty else {
            throw ValidationError("Manifest contains duplicate model ids: \(duplicateModelIDs.joined(separator: ", ")).")
        }

        let missingModes = GenerationMode.allCases.filter { mode in
            !manifest.models.contains { $0.mode == mode }
        }
        guard missingModes.isEmpty else {
            throw ValidationError("Manifest is missing models for modes: \(missingModes.map(\.rawValue).joined(separator: ", ")).")
        }

        for mode in GenerationMode.allCases {
            let recommendedCount = manifest.models.filter {
                $0.mode == mode && $0.isHardwareRecommended
            }.count
            guard recommendedCount == 1 else {
                throw ValidationError("Manifest must define one recommended model for mode '\(mode.rawValue)'.")
            }
        }

        for model in manifest.models {
            guard !model.tier.isEmpty else {
                throw ValidationError("Model '\(model.id)' must define a tier.")
            }
            guard !model.outputSubfolder.isEmpty else {
                throw ValidationError("Model '\(model.id)' must define an output subfolder.")
            }
            guard !model.requiredRelativePaths.isEmpty else {
                throw ValidationError("Model '\(model.id)' must define required files.")
            }
        }
    }

    private static func locateManifestURL() throws -> URL {
        let bundles = [Bundle.main, Bundle(for: TTSContractBundleLocator.self)] + Bundle.allBundles + Bundle.allFrameworks

        for bundle in bundles {
            if let url = bundle.url(forResource: "qwenvoice_contract", withExtension: "json") {
                return url
            }
        }

        let searchedBundles = bundles
            .map(\.bundlePath)
            .joined(separator: "\n")
        throw ContractLoadError(
            summary: "Could not locate bundled qwenvoice_contract.json",
            details: "Searched bundles:\n\(searchedBundles)",
            manifestPath: nil
        )
    }

    /// Resolve exact production download evidence for a macOS model variant. This intentionally
    /// reloads the small bundled document for each requested model so a catalog read failure is
    /// surfaced at the action boundary rather than cached as a process-global fallback.
    static func productionDownloadPlan(
        for model: TTSModel
    ) throws -> (catalog: ProductionModelCatalog, artifact: ProductionModelCatalog.Artifact) {
        guard let variantID = model.variantID else {
            throw ProductionModelCatalog.Error.descriptorMismatch(
                identity: model.id,
                reason: "variant identity is missing"
            )
        }
        let catalog = try ProductionModelCatalog(contentsOf: locateProductionCatalogURL())
        let artifact = try catalog.artifact(
            modelID: model.baseModelID,
            variantID: variantID,
            folder: model.folder,
            repo: model.huggingFaceRepo,
            revision: model.huggingFaceRevision,
            artifactVersion: model.artifactVersion,
            estimatedDownloadBytes: model.estimatedDownloadBytes,
            requiredRelativePaths: model.requiredRelativePaths
        )
        return (catalog, artifact)
    }

    private static func locateProductionCatalogURL() throws -> URL {
        let bundles = [Bundle.main, Bundle(for: TTSContractBundleLocator.self)]
            + Bundle.allBundles + Bundle.allFrameworks
        for bundle in bundles {
            if let url = bundle.url(
                forResource: "qwenvoice_production_model_catalog",
                withExtension: "json"
            ) {
                return url
            }
        }
        throw ProductionModelCatalog.Error.unreadable(
            "Could not locate bundled qwenvoice_production_model_catalog.json"
        )
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

private extension TTSModelVariantKind {
    init(coreKind: ModelVariantKind) {
        switch coreKind {
        case .compactSpeed:
            self = .compactSpeed
        case .compactQuality:
            self = .compactQuality
        case .speed:
            self = .speed
        case .quality:
            self = .quality
        }
    }
}

private struct ValidationError: LocalizedError {
    let message: String

    init(_ message: String) {
        self.message = message
    }

    var errorDescription: String? {
        message
    }
}
