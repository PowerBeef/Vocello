import Foundation
import QwenVoiceCore
import VocelloDesktopCore

/// Read-only runtime context (registry + model asset store) for commands that
/// don't generate audio.
@MainActor
public struct CLIRegistryContext {
    public let registry: ContractBackedModelRegistry
    let modelAssetStore: LocalModelAssetStore
    public let modelsDirectory: URL
}

/// In-process engine for the CLI. Mirrors `MacEngineBootstrap`'s runtime wiring
/// (manifest → platform-expanded registry → `NativeRuntimeFactory.make`). The
/// product commands (generate, batch, run) host the engine through
/// `DesktopEngineHost`, the shared `TTSEngineStore` with the Mac memory budget;
/// `bench` drives `MLXTTSEngine` directly.
@MainActor
public struct CLIRuntime {
    public let engine: MLXTTSEngine
    public let registry: ContractBackedModelRegistry
    let dataDirectory: URL
    /// PA-17: the invocation's recorded voice-cloning consent (`--confirm-consent`).
    /// Generation, clone-reference priming and enrollment go through `generate(_:)`,
    /// `primeCloneReference` and `enrollPreparedVoice` below, never straight to
    /// `engine`, so the core policy refuses them first.
    let voiceCloningConsent: VoiceCloningConsentPolicy
    /// RF-27: product commands (generate, batch, run) host the engine as the Mac
    /// app does, through the shared store; bench drives the raw engine (nil).
    var host: DesktopEngineHost? = nil
    /// The hosted engine's lease on the data root, held for the process's life.
    var lease: EngineHostLease? = nil

    public static func bootstrap(
        dataDirectory: URL,
        manifestOverride: URL?,
        voiceCloningConsent: VoiceCloningConsentPolicy = CLIVoiceCloningConsent.notConfirmed,
        hostedLikeTheApp: Bool = false,
        concurrency: CLIEngineConcurrency = CLIEngineConcurrency()
    ) async throws -> CLIRuntime {
        let manifestURL = try manifestOverride ?? locateManifestURL()
        let deviceClass = NativeMemoryPolicyResolver.deviceClass()
        let lease = hostedLikeTheApp
            ? try await admitEngineHost(dataDirectory: dataDirectory, deviceClass: deviceClass, concurrency: concurrency)
            : nil
        let registry = try ContractBackedModelRegistry(manifestURL: manifestURL)
            .expandedForPlatform(.macOS, deviceClass: deviceClass, includeBaseAliases: true)
        let runtime = try NativeRuntimeFactory.make(
            registry: registry,
            paths: .rooted(at: dataDirectory),
            storeVersionSeed: storeVersionSeed(),
            customPrewarmPolicy: customPrewarmPolicy(for: deviceClass)
        )
        DesktopDataRoot.configure(dataDirectory)
        var host: DesktopEngineHost?
        if hostedLikeTheApp {
            let hosted = DesktopEngineHost(engine: runtime.engine, consent: voiceCloningConsent, deviceClass: deviceClass)
            try await hosted.initialize(appSupportDirectory: dataDirectory)
            host = hosted
        } else {
            try await runtime.engine.initialize(appSupportDirectory: dataDirectory)
        }
        return CLIRuntime(
            engine: runtime.engine,
            registry: registry,
            dataDirectory: dataDirectory,
            voiceCloningConsent: voiceCloningConsent,
            host: host,
            lease: lease
        )
    }

    /// Admits this process as an engine host on `dataDirectory` beside the others
    /// (`EngineHostAdmission`) and returns its lease. The lease is taken before
    /// the others are read, so two processes starting together see each other;
    /// a waiting one gives its lease back between tries. A lease that cannot be
    /// written only warns: it is advisory.
    static func admitEngineHost(
        dataDirectory: URL, deviceClass: NativeDeviceMemoryClass, concurrency: CLIEngineConcurrency
    ) async throws -> EngineHostLease? {
        var announcedWait = false
        while true {
            let lease: EngineHostLease?
            do {
                lease = try EngineHostLease.acquire(dataDirectory: dataDirectory, kind: "cli")
            } catch {
                CLIPresenter.warn("engine_lease_unavailable", "could not record this engine on the data folder: \(error)")
                lease = nil
            }
            let decision = EngineHostAdmission.decide(
                otherHosts: EngineHostLease.liveHosts(dataDirectory: dataDirectory, excluding: lease),
                appRunning: DesktopAppPresence.isAppRunning() && DesktopAppPresence.isAppDataRoot(dataDirectory),
                deviceClass: deviceClass, allowConcurrent: concurrency.allow
            )
            switch decision {
            case .proceed:
                return lease
            case .warn(let message):
                CLIPresenter.warn("concurrent_engine", message)
                return lease
            case .refuse(let message):
                lease?.release()
                guard concurrency.wait else {
                    throw CLIError(
                        .engineBusy, message,
                        hint: "retry when it finishes, pass --wait-for-engine to wait, or --allow-concurrent-engine to run anyway"
                    )
                }
                if !announcedWait {
                    note("waiting: \(message)")
                    announcedWait = true
                }
                // Jitter, so two waiters never keep seeing each other.
                try await Task.sleep(for: .milliseconds(Int.random(in: 1500 ... 3000)))
            }
        }
    }


    /// Same tiered prewarm policy as the macOS app: defer the dedicated custom
    /// prewarm on the 8 GB floor tier (the work folds into the first generation).
    public static func customPrewarmPolicy(for deviceClass: NativeDeviceMemoryClass) -> NativeCustomPrewarmPolicy {
        deviceClass == .floor8GBMac ? .skipDedicatedCustomPrewarm : .eager
    }

    /// This runtime's engine under another request's recorded consent (one warm
    /// engine serves many requests, each with its own `confirmConsent`). The host
    /// is shared, so its consent becomes this request's: requests run one at a
    /// time, and `generate` also checks the returned runtime's own consent first.
    public func withConsent(_ consent: VoiceCloningConsentPolicy) -> CLIRuntime {
        host?.setConsent(consent)
        return CLIRuntime(
            engine: engine, registry: registry, dataDirectory: dataDirectory, voiceCloningConsent: consent, host: host
        )
    }

    /// Loads a model through the host's admission when hosted, else on the engine.
    public func loadModel(id: String) async throws {
        if let host { try await host.loadModel(id: id) } else { try await engine.loadModel(id: id) }
    }

    /// Every CLI generation: clone requests are refused without recorded consent,
    /// and a take the engine cancelled while no signal reached the command throws
    /// `CLIEngineCancellation` instead of the operator's `CancellationError` (P15-02).
    public func generate(_ request: GenerationRequest) async throws -> GenerationResult {
        try voiceCloningConsent.admitGeneration(request)
        do {
            if let host { return try await host.generate(request) }
            return try await engine.generate(request)
        } catch {
            throw CLIEngineCancellation.classify(error, commandCancelled: Task.isCancelled)
        }
    }

    /// Clone-reference priming conditions the engine on a reference voice, so it is
    /// refused like clone generation without recorded consent (as the apps'
    /// `AnyTTSEngineBackend` refuses it).
    public func primeCloneReference(modelID: String, reference: CloneReference) async throws {
        try voiceCloningConsent.admit(.generation)
        try await engine.ensureCloneReferencePrimed(modelID: modelID, reference: reference)
    }

    /// Every CLI saved-voice enrollment: refused without recorded consent.
    public func enrollPreparedVoice(name: String, audioPath: String, transcript: String?) async throws -> PreparedVoice {
        try voiceCloningConsent.admit(.enrollment)
        return try await engine.enrollPreparedVoice(name: name, audioPath: audioPath, transcript: transcript)
    }

    /// Read-only context for discoverability commands (`speakers`, `models`):
    /// the platform-expanded registry + model asset store, **without** booting
    /// the engine (`initialize` loads no model but we skip it anyway to keep
    /// these commands instant). Reuses the same manifest → registry →
    /// `NativeRuntimeFactory.make` prefix as the full bootstrap.
    public static func bootstrapRegistryOnly(
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
    public func modelID(mode: GenerationMode, quality: Bool) throws -> String {
        try Self.modelID(registry: registry, mode: mode, quality: quality)
    }

    /// The variant-scoped model id for (mode, variant) in `registry`, without an engine.
    public nonisolated static func modelID(
        registry: ContractBackedModelRegistry, mode: GenerationMode, quality: Bool
    ) throws -> String {
        guard let base = registry.model(for: mode) else {
            throw CLIError(.configError, "No model for mode '\(mode.rawValue)' in the manifest.")
        }
        let variants = base.platformVariants(for: .macOS)
        guard !variants.isEmpty else {
            throw CLIError(.configError, "No macOS variants for mode '\(mode.rawValue)'.")
        }
        let wanted: ModelVariantKind = quality ? .quality : .speed
        guard let variant = variants.first(where: { $0.kind == wanted }) else {
            let available = variants.map { $0.kind.rawValue }.joined(separator: ", ")
            throw CLIError(.configError, "No \(quality ? "Quality" : "Speed") variant for '\(mode.rawValue)' (have: \(available)).")
        }
        return base.variantScopedID(for: variant)
    }

    /// Default Built-in Voice speaker id from the contract (e.g. Aiden).
    public var defaultSpeakerID: String { registry.defaultSpeaker.id }

    // MARK: - Manifest / version

    static func locateManifestURL() throws -> URL {
        guard let url = locateTrustAnchor(named: "qwenvoice_contract") else {
            throw CLIError(.configError, "Could not locate qwenvoice_contract.json. Pass --manifest <path>.")
        }
        return url
    }

    public static func locateProductionCatalogURL() throws -> URL {
        guard let url = locateTrustAnchor(named: "qwenvoice_production_model_catalog") else {
            throw CLIError(.configError, "Could not locate authenticated production model catalog.")
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
    public nonisolated static func findUpwards(
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


/// `--allow-concurrent-engine` and `--wait-for-engine`: what a product command
/// does when another engine already runs on its data root.
public struct CLIEngineConcurrency: Sendable, Equatable {
    public let allow: Bool
    public let wait: Bool

    public init(allow: Bool = false, wait: Bool = false) {
        self.allow = allow
        self.wait = wait
    }

    public init(_ args: Args) {
        self.init(allow: args.flag("allow-concurrent-engine"), wait: args.flag("wait-for-engine"))
    }
}
