import Foundation
import QwenVoiceCore

/// In-process engine for the CLI. Mirrors `EngineServiceHost`'s runtime wiring
/// (manifest → platform-expanded registry → `NativeRuntimeFactory.make` →
/// `engine.initialize`) but without XPC — the CLI links `QwenVoiceCore` and
/// drives `MLXTTSEngine` directly.
/// Read-only runtime context (registry + model asset store) for commands that
/// don't generate audio.
@MainActor
struct CLIRegistryContext {
    let registry: ContractBackedModelRegistry
    let modelAssetStore: LocalModelAssetStore
    let modelsDirectory: URL
}

@MainActor
struct CLIRuntime {
    let engine: MLXTTSEngine
    let registry: ContractBackedModelRegistry
    let dataDirectory: URL

    static func bootstrap(dataDirectory: URL, manifestOverride: URL?) async throws -> CLIRuntime {
        let manifestURL = try manifestOverride ?? locateManifestURL()
        let deviceClass = NativeMemoryPolicyResolver.deviceClass()
        let registry = try ContractBackedModelRegistry(manifestURL: manifestURL)
            .expandedForPlatform(.macOS, deviceClass: deviceClass, includeBaseAliases: true)
        // Same tiered prewarm policy as the XPC host: defer the dedicated custom
        // prewarm on the 8 GB floor tier (the work folds into the first generation).
        let customPrewarmPolicy: NativeCustomPrewarmPolicy =
            deviceClass == .floor8GBMac ? .skipDedicatedCustomPrewarm : .eager
        let runtime = try NativeRuntimeFactory.make(
            registry: registry,
            paths: .rooted(at: dataDirectory),
            storeVersionSeed: storeVersionSeed(),
            customPrewarmPolicy: customPrewarmPolicy
        )
        try await runtime.engine.initialize(appSupportDirectory: dataDirectory)
        return CLIRuntime(engine: runtime.engine, registry: registry, dataDirectory: dataDirectory)
    }

    /// Read-only context for discoverability commands (`speakers`, `models`):
    /// the platform-expanded registry + model asset store, **without** booting
    /// the engine (`initialize` loads no model but we skip it anyway to keep
    /// these commands instant). Reuses the same manifest → registry →
    /// `NativeRuntimeFactory.make` prefix as the full bootstrap.
    static func bootstrapRegistryOnly(
        dataDirectory: URL, manifestOverride: URL?
    ) throws -> CLIRegistryContext {
        let manifestURL = try manifestOverride ?? locateManifestURL()
        let deviceClass = NativeMemoryPolicyResolver.deviceClass()
        let registry = try ContractBackedModelRegistry(manifestURL: manifestURL)
            .expandedForPlatform(.macOS, deviceClass: deviceClass, includeBaseAliases: true)
        let components = try NativeRuntimeFactory.make(
            registry: registry,
            paths: .rooted(at: dataDirectory),
            storeVersionSeed: storeVersionSeed())
        return CLIRegistryContext(
            registry: components.modelRegistry,
            modelAssetStore: components.modelAssetStore,
            modelsDirectory: dataDirectory.appendingPathComponent("models", isDirectory: true))
    }

    /// Resolve a (mode, variant) to the variant-scoped model id the engine loads
    /// (e.g. `pro_custom_speed` / `pro_custom_quality`).
    func modelID(mode: GenerationMode, quality: Bool) throws -> String {
        guard let base = registry.model(for: mode) else {
            throw CLIError("No model for mode '\(mode.rawValue)' in the manifest.")
        }
        let variants = base.platformVariants(for: .macOS)
        guard !variants.isEmpty else {
            throw CLIError("No macOS variants for mode '\(mode.rawValue)'.")
        }
        let wanted: ModelVariantKind = quality ? .quality : .speed
        guard let variant = variants.first(where: { $0.kind == wanted }) else {
            let available = variants.map { $0.kind.rawValue }.joined(separator: ", ")
            throw CLIError("No \(quality ? "Quality" : "Speed") variant for '\(mode.rawValue)' (have: \(available)).")
        }
        return base.variantScopedID(for: variant)
    }

    /// Default Built-in Voice speaker id from the contract (e.g. Aiden).
    var defaultSpeakerID: String { registry.defaultSpeaker.id }

    // MARK: - Manifest / version

    static func locateManifestURL() throws -> URL {
        // 1) Bundled resource (shipped CLI). 2) repo-relative when run from the
        // repo root (dev + benchmarks). 3) next to the executable.
        let bundles = [Bundle.main] + Bundle.allBundles + Bundle.allFrameworks
        for bundle in bundles {
            if let url = bundle.url(forResource: "qwenvoice_contract", withExtension: "json") {
                return url
            }
        }
        let fm = FileManager.default
        let exeDir = Bundle.main.bundleURL.deletingLastPathComponent().path
        // Direct candidates: next to the executable, or cwd == repo root.
        let candidates = [
            exeDir + "/qwenvoice_contract.json",
            fm.currentDirectoryPath + "/Sources/Resources/qwenvoice_contract.json",
        ]
        for path in candidates where fm.fileExists(atPath: path) {
            return URL(fileURLWithPath: path)
        }
        // 3) Walk up from cwd so the CLI also resolves the contract when run from
        // any subdirectory of the repo (dev convenience).
        if let found = findUpwards(relativePath: "Sources/Resources/qwenvoice_contract.json",
                                   from: fm.currentDirectoryPath) {
            return found
        }
        throw CLIError("Could not locate qwenvoice_contract.json. Pass --manifest <path>.")
    }

    static func locateProductionCatalogURL() throws -> URL {
        let resourceName = "qwenvoice_production_model_catalog"
        let bundles = [Bundle.main] + Bundle.allBundles + Bundle.allFrameworks
        for bundle in bundles {
            if let url = bundle.url(forResource: resourceName, withExtension: "json") {
                return url
            }
        }
        let fm = FileManager.default
        let exeDir = Bundle.main.bundleURL.deletingLastPathComponent().path
        let relativePath = "Sources/Resources/\(resourceName).json"
        let candidates = [
            exeDir + "/\(resourceName).json",
            fm.currentDirectoryPath + "/\(relativePath)",
        ]
        for path in candidates where fm.fileExists(atPath: path) {
            return URL(fileURLWithPath: path)
        }
        if let found = findUpwards(relativePath: relativePath, from: fm.currentDirectoryPath) {
            return found
        }
        throw CLIError("Could not locate authenticated production model catalog.")
    }

    /// Walk up parent directories from `start`, returning the first existing
    /// `<dir>/<relativePath>` (stops at the filesystem root). Lets the CLI find
    /// repo-relative dev assets (the contract, the summarizer script) regardless
    /// of which subdirectory it's launched from.
    nonisolated static func findUpwards(relativePath: String, from start: String) -> URL? {
        let fm = FileManager.default
        var dir = URL(fileURLWithPath: start, isDirectory: true).standardizedFileURL
        while true {
            let candidate = dir.appendingPathComponent(relativePath)
            if fm.fileExists(atPath: candidate.path) { return candidate }
            let parent = dir.deletingLastPathComponent()
            if parent.path == dir.path { return nil }  // reached filesystem root
            dir = parent
        }
    }

    static func storeVersionSeed(bundle: Bundle = .main) -> String {
        let id = bundle.bundleIdentifier ?? "com.qwenvoice.cli"
        let marketing = bundle.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? vocelloCLIVersion
        let build = bundle.object(forInfoDictionaryKey: kCFBundleVersionKey as String) as? String ?? "0"
        return "\(id)|\(marketing)|\(build)"
    }
}
