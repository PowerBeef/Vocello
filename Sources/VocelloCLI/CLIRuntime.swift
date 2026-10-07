import Foundation
import QwenVoiceCore

/// In-process engine for the CLI. Mirrors `MacEngineBootstrap`'s runtime wiring
/// (manifest → platform-expanded registry → `NativeRuntimeFactory.make` →
/// `engine.initialize`) — the CLI links `QwenVoiceCore` and drives
/// `MLXTTSEngine` directly.
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
    /// PA-17: the invocation's recorded voice-cloning consent (`--confirm-consent`).
    /// Generation, clone-reference priming and enrollment go through `generate(_:)`,
    /// `primeCloneReference` and `enrollPreparedVoice` below, never straight to
    /// `engine`, so the core policy refuses them first.
    let voiceCloningConsent: VoiceCloningConsentPolicy

    static func bootstrap(
        dataDirectory: URL,
        manifestOverride: URL?,
        voiceCloningConsent: VoiceCloningConsentPolicy = CLIVoiceCloningConsent.notConfirmed
    ) async throws -> CLIRuntime {
        let manifestURL = try manifestOverride ?? locateManifestURL()
        let deviceClass = NativeMemoryPolicyResolver.deviceClass()
        let registry = try ContractBackedModelRegistry(manifestURL: manifestURL)
            .expandedForPlatform(.macOS, deviceClass: deviceClass, includeBaseAliases: true)
        let runtime = try NativeRuntimeFactory.make(
            registry: registry,
            paths: .rooted(at: dataDirectory),
            storeVersionSeed: storeVersionSeed(),
            customPrewarmPolicy: customPrewarmPolicy(for: deviceClass)
        )
        try await runtime.engine.initialize(appSupportDirectory: dataDirectory)
        return CLIRuntime(
            engine: runtime.engine,
            registry: registry,
            dataDirectory: dataDirectory,
            voiceCloningConsent: voiceCloningConsent
        )
    }

    /// Same tiered prewarm policy as the macOS app: defer the dedicated custom
    /// prewarm on the 8 GB floor tier (the work folds into the first generation).
    static func customPrewarmPolicy(for deviceClass: NativeDeviceMemoryClass) -> NativeCustomPrewarmPolicy {
        deviceClass == .floor8GBMac ? .skipDedicatedCustomPrewarm : .eager
    }

    /// Every CLI generation: clone requests are refused without recorded consent,
    /// and a take the engine cancelled while no signal reached the command throws
    /// `CLIEngineCancellation` instead of the operator's `CancellationError` (P15-02).
    func generate(_ request: GenerationRequest) async throws -> GenerationResult {
        try voiceCloningConsent.admitGeneration(request)
        do {
            return try await engine.generate(request)
        } catch {
            throw CLIEngineCancellation.classify(error, commandCancelled: Task.isCancelled)
        }
    }

    /// Clone-reference priming conditions the engine on a reference voice, so it is
    /// refused like clone generation without recorded consent (as the apps'
    /// `AnyTTSEngineBackend` refuses it).
    func primeCloneReference(modelID: String, reference: CloneReference) async throws {
        try voiceCloningConsent.admit(.generation)
        try await engine.ensureCloneReferencePrimed(modelID: modelID, reference: reference)
    }

    /// Every CLI saved-voice enrollment: refused without recorded consent.
    func enrollPreparedVoice(name: String, audioPath: String, transcript: String?) async throws -> PreparedVoice {
        try voiceCloningConsent.admit(.enrollment)
        return try await engine.enrollPreparedVoice(name: name, audioPath: audioPath, transcript: transcript)
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
        guard let url = locateTrustAnchor(named: "qwenvoice_contract") else {
            throw CLIError("Could not locate qwenvoice_contract.json. Pass --manifest <path>.")
        }
        return url
    }

    static func locateProductionCatalogURL() throws -> URL {
        guard let url = locateTrustAnchor(named: "qwenvoice_production_model_catalog") else {
            throw CLIError("Could not locate authenticated production model catalog.")
        }
        return url
    }

    /// The sealed CLI payload's inventory, staged next to the executable by
    /// `scripts/cli_package.py`; its presence marks a distributed build.
    nonisolated static let sealedPayloadManifestName = "package-manifest.json"

    private static func locateTrustAnchor(named resourceName: String) -> URL? {
        let bundles = [Bundle.main] + Bundle.allBundles + Bundle.allFrameworks
        let bundled = bundles.lazy
            .compactMap { $0.url(forResource: resourceName, withExtension: "json") }
            .first
        // Resolved, so a sealed payload run through a symlink still finds its
        // own folder (and its manifest) rather than the link's.
        let executableDirectory = (Bundle.main.executableURL ?? Bundle.main.bundleURL)
            .resolvingSymlinksInPath()
            .deletingLastPathComponent()
        let fileManager = FileManager.default
        return resolveTrustAnchor(
            fileName: "\(resourceName).json",
            bundledURL: bundled,
            executableDirectory: executableDirectory,
            currentDirectory: fileManager.currentDirectoryPath,
            fileExists: { fileManager.fileExists(atPath: $0) }
        )
    }

    /// Where a trust anchor (the contract, the production catalog) comes from, in
    /// order (SEC-09):
    /// 1. the resource bundled with the CLI;
    /// 2. the file next to the executable;
    /// 3. only outside a sealed payload (no `package-manifest.json` next to the
    ///    executable), the repository copy under the working directory or one of its
    ///    parents, so development runs from any repository folder keep working.
    /// A distributed CLI therefore never reads an anchor from the folder it runs in,
    /// which could otherwise redirect installs into the store the app shares.
    nonisolated static func resolveTrustAnchor(
        fileName: String,
        bundledURL: URL?,
        executableDirectory: URL,
        currentDirectory: String,
        fileExists: (String) -> Bool
    ) -> URL? {
        if let bundledURL { return bundledURL }
        let besideExecutable = executableDirectory.appendingPathComponent(fileName)
        if fileExists(besideExecutable.path) { return besideExecutable }
        let sealedManifest = executableDirectory.appendingPathComponent(sealedPayloadManifestName)
        guard !fileExists(sealedManifest.path) else { return nil }
        return findUpwards(
            relativePath: "Sources/Resources/\(fileName)",
            from: currentDirectory,
            fileExists: fileExists
        )
    }

    /// Walk up parent directories from `start`, returning the first existing
    /// `<dir>/<relativePath>` (stops at the filesystem root). Lets the CLI find
    /// repo-relative dev assets (the contract, the summarizer script) regardless
    /// of which subdirectory it's launched from.
    nonisolated static func findUpwards(
        relativePath: String,
        from start: String,
        fileExists: (String) -> Bool = { FileManager.default.fileExists(atPath: $0) }
    ) -> URL? {
        var dir = URL(fileURLWithPath: start, isDirectory: true).standardizedFileURL
        while true {
            let candidate = dir.appendingPathComponent(relativePath)
            if fileExists(candidate.path) { return candidate }
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
