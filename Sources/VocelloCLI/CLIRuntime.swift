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
    public internal(set) var host: DesktopEngineHost? = nil
    /// The hosted engine's lease: a one-shot command holds it for the process's
    /// life, and a warm engine's follows its model (`CLIWarmEngine`).
    var lease: EngineHostLease? = nil

    public static func bootstrap(
        dataDirectory: URL,
        manifestOverride: URL?,
        voiceCloningConsent: VoiceCloningConsentPolicy = CLIVoiceCloningConsent.notConfirmed,
        hostedLikeTheApp: Bool = false,
        concurrency: CLIEngineConcurrency = CLIEngineConcurrency(),
        takesEngineLease: Bool = true
    ) async throws -> CLIRuntime {
        // RF-29: under the MCP server, every command shares its one warm engine.
        if let warm = CLIEngineScope.warm {
            return try await warm.runtime(
                dataDirectory: dataDirectory, manifestOverride: manifestOverride, consent: voiceCloningConsent,
                hosted: hostedLikeTheApp, takesEngineLease: hostedLikeTheApp && takesEngineLease
            )
        }
        let manifestURL = try manifestOverride ?? locateManifestURL()
        let deviceClass = NativeMemoryPolicyResolver.deviceClass()
        // A host that loads a model holds a lease; one that never does (saved-voice writes) need not.
        let lease = hostedLikeTheApp && takesEngineLease
            ? try await admitEngineHost(deviceClass: deviceClass, concurrency: concurrency)
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

    /// Admits this process as an engine host beside the others on this Mac
    /// (`EngineHostAdmission`) and returns its lease. The lease is taken before
    /// the others are read, so two processes starting together see each other;
    /// a waiting one gives its lease back between tries and says so once
    /// (`queued`). A lease that cannot be written only warns: it is advisory.
    /// `appRunning`, `sleep` and `folder` are seams for tests.
    static func admitEngineHost(
        deviceClass: NativeDeviceMemoryClass, concurrency: CLIEngineConcurrency,
        appRunning: () -> Bool = DesktopAppPresence.isAppRunning,
        sleep: (Duration) async throws -> Void = { try await Task.sleep(for: $0) },
        folder: URL = EngineHostLease.sharedFolder
    ) async throws -> EngineHostLease? {
        var announcedWait = false
        while true {
            let lease: EngineHostLease?
            do {
                lease = try EngineHostLease.acquire(in: folder, kind: "cli")
            } catch {
                CLIPresenter.warn("engine_lease_unavailable", "could not record this engine for other Vocello processes: \(error)")
                lease = nil
            }
            let decision = EngineHostAdmission.decide(
                otherHosts: EngineHostLease.liveHosts(in: folder, excluding: lease),
                appRunning: appRunning(), deviceClass: deviceClass, allowConcurrent: concurrency.allow
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
                    CLIPresenter.event(.queued, data: ["reason": .string(message)])
                    announcedWait = true
                }
                // Jitter, so two waiters never keep seeing each other.
                try await sleep(.milliseconds(Int.random(in: 1500 ... 3000)))
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
            engine: engine, registry: registry, dataDirectory: dataDirectory, voiceCloningConsent: consent, host: host,
            lease: lease
        )
    }

    /// This runtime under a read's consent, leaving the shared host's as it is
    /// (RF-29: a read runs beside the request that set it).
    func reading(under consent: VoiceCloningConsentPolicy) -> CLIRuntime {
        CLIRuntime(
            engine: engine, registry: registry, dataDirectory: dataDirectory, voiceCloningConsent: consent, host: host,
            lease: lease
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
        // RF-29: the MCP server reads one context for its life.
        if let warm = CLIEngineScope.warm {
            return try warm.registryContext(dataDirectory: dataDirectory, manifestOverride: manifestOverride)
        }
        let registry = try contractRegistry(manifestOverride: manifestOverride)
        let components = try NativeRuntimeFactory.make(
            registry: registry,
            paths: .rooted(at: dataDirectory),
            storeVersionSeed: storeVersionSeed())
        return CLIRegistryContext(
            registry: components.modelRegistry,
            modelAssetStore: components.modelAssetStore,
            modelsDirectory: dataDirectory.appendingPathComponent("models", isDirectory: true))
    }

    /// The contract's registry for this Mac, as every bootstrap expands it, without the runtime:
    /// no data directory is touched, so a command reads it to validate its arguments first.
    public static func contractRegistry(manifestOverride: URL?) throws -> ContractBackedModelRegistry {
        try ContractBackedModelRegistry(manifestURL: manifestOverride ?? locateManifestURL())
            .expandedForPlatform(.macOS, deviceClass: NativeMemoryPolicyResolver.deviceClass(), includeBaseAliases: true)
    }

    /// RF-59: the variant kinds (`speed`, `quality`) `registry` offers every one of `modes` on this
    /// Mac, in that order: `vocello bench`'s default matrix. Throws when the modes share none.
    public nonisolated static func offeredVariantKinds(
        modes: [String], registry: ContractBackedModelRegistry
    ) throws -> [String] {
        let offered = ["speed", "quality"].filter { kind in
            modes.allSatisfy { raw in
                guard let mode = GenerationMode(rawValue: raw) else { return false }
                return (try? modelID(registry: registry, mode: mode, quality: kind == "quality")) != nil
            }
        }
        guard !offered.isEmpty else {
            throw CLIError(.configError, "the contract offers no package common to --modes \(modes.joined(separator: ","))")
        }
        return offered
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

    /// The contract a copy of this executable finds wherever it is started: the
    /// bundled one or the one beside it, never the repository copy a development
    /// run finds from its working folder (RF-29: an MCP client starts the server
    /// from a folder of its own).
    static func locateShippedManifestURL() -> URL? {
        locateTrustAnchor(named: "qwenvoice_contract", currentDirectory: "/")
    }

    private static func locateTrustAnchor(
        named resourceName: String, currentDirectory: String = FileManager.default.currentDirectoryPath
    ) -> URL? {
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
            currentDirectory: currentDirectory,
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


/// The engine a scope shares (RF-29): the MCP server runs each tool call under
/// its own warm engine.
public enum CLIEngineScope {
    @TaskLocal public static var warm: CLIWarmEngine?
}

/// The MCP server's one engine (RF-29). Under its scope every bootstrap returns
/// this engine instead of starting another, which a long-lived process would
/// otherwise accumulate: the first boots it (callers arriving meanwhile wait for
/// that boot). A hosted command takes it under its own consent, which becomes
/// the shared host's (the server runs those one at a time); a read takes it
/// under its own without touching the host's. The engine's own idle policy
/// unloads the model between requests.
///
/// Its lease follows the model (RF-61, `EngineHostLeaseKeeper`): a request that
/// loads a model is admitted as a fresh `vocello generate` is and takes the
/// lease, the engine's idle unload gives it back, and the next such request is
/// admitted again. A refused admission fails that request (`engine_busy`) and
/// the engine stays up for the next one. The server brackets each engine
/// request with `engineRequestBegan` and `engineRequestEnded`.
@MainActor
public final class CLIWarmEngine {
    /// What an admission reads, and how the engine boots; tests replace them.
    struct Seams {
        var deviceClass: @MainActor () -> NativeDeviceMemoryClass = { NativeMemoryPolicyResolver.deviceClass() }
        var appRunning: () -> Bool = DesktopAppPresence.isAppRunning
        var leaseFolder: URL = EngineHostLease.sharedFolder
        /// How long a published failure keeps the lease; nil is the tier's idle window.
        var failureWindow: Duration?
        var boot: (@MainActor () async throws -> CLIRuntime)?
    }

    public let dataDirectory: URL
    public let manifestOverride: URL?
    let concurrency: CLIEngineConcurrency
    private let seams: Seams
    private let leaseKeeper: EngineHostLeaseKeeper
    private var runtime: CLIRuntime?
    private var booting: Task<Result<CLIRuntime, any Error>, Never>?
    private var registry: CLIRegistryContext?

    public convenience init(dataDirectory: URL, manifestOverride: URL?, concurrency: CLIEngineConcurrency) {
        self.init(
            dataDirectory: dataDirectory, manifestOverride: manifestOverride, concurrency: concurrency, seams: Seams()
        )
    }

    init(dataDirectory: URL, manifestOverride: URL?, concurrency: CLIEngineConcurrency, seams: Seams) {
        self.dataDirectory = dataDirectory
        self.manifestOverride = manifestOverride
        self.concurrency = concurrency
        self.seams = seams
        leaseKeeper = EngineHostLeaseKeeper(
            kind: "cli", folder: seams.leaseFolder,
            failureWindow: seams.failureWindow ?? EngineHostLeaseKeeper.failureWindow(for: seams.deviceClass())
        )
    }

    public var isBooted: Bool { runtime != nil }
    public var holdsLease: Bool { leaseKeeper.holdsLease }
    /// What the engine last published about its model, as the lease reads it.
    var modelPresence: EngineHostModelPresence { leaseKeeper.presence }

    /// An engine request starts: until it ends, the lease stays whatever the
    /// engine publishes on the way to its load.
    public func engineRequestBegan() {
        leaseKeeper.requestBegan()
    }

    /// An engine request ended: one that loaded no model gives its lease back
    /// now, and a loaded model keeps it until the engine unloads.
    public func engineRequestEnded() {
        leaseKeeper.requestEnded()
    }

    func runtime(
        dataDirectory: URL, manifestOverride: URL?, consent: VoiceCloningConsentPolicy, hosted: Bool,
        takesEngineLease: Bool
    ) async throws -> CLIRuntime {
        try checkRoot(dataDirectory, manifestOverride)
        var current = try await booted()
        if takesEngineLease, !leaseKeeper.holdsLease {
            // The same admission as a fresh start, so a refusal is the same error.
            leaseKeeper.adopt(try await CLIRuntime.admitEngineHost(
                deviceClass: seams.deviceClass(), concurrency: concurrency, appRunning: seams.appRunning,
                folder: seams.leaseFolder
            ))
        }
        current.lease = leaseKeeper.lease
        return hosted ? current.withConsent(consent) : current.reading(under: consent)
    }

    func registryContext(dataDirectory: URL, manifestOverride: URL?) throws -> CLIRegistryContext {
        try checkRoot(dataDirectory, manifestOverride)
        if let registry { return registry }
        let context = try CLIEngineScope.$warm.withValue(nil) {
            try CLIRuntime.bootstrapRegistryOnly(dataDirectory: self.dataDirectory, manifestOverride: self.manifestOverride)
        }
        registry = context
        return context
    }

    private func checkRoot(_ dataDirectory: URL, _ manifestOverride: URL?) throws {
        guard dataDirectory.standardizedFileURL.path == self.dataDirectory.standardizedFileURL.path,
              manifestOverride?.standardizedFileURL.path == self.manifestOverride?.standardizedFileURL.path else {
            throw CLIError(.internalError, "a request named another data folder or contract than the server's")
        }
    }

    private func booted() async throws -> CLIRuntime {
        if let runtime { return runtime }
        let boot = booting ?? Task { @MainActor in
            // The boot outlives the call that started it: it keeps none of that call's scope.
            await CLIPresenter.$capture.withValue(nil) {
                await CLIEngineScope.$warm.withValue(nil) {
                    do {
                        return .success(try await self.bootRuntime())
                    } catch {
                        return .failure(error)
                    }
                }
            }
        }
        booting = boot
        let outcome = await boot.value
        // Only this boot's waiters clear it: a newer one may have started since.
        if booting == boot { booting = nil }
        if runtime == nil {
            let started = try outcome.get()
            // From here the lease follows what the engine publishes about its model.
            started.host?.observeEngineState { [leaseKeeper] loadState, clonePreparation in
                leaseKeeper.engineChanged(loadState: loadState, clonePreparation: clonePreparation)
            }
            runtime = started
        }
        guard let runtime else { throw CLIError(.internalError, "the engine did not start") }
        return runtime
    }

    private func bootRuntime() async throws -> CLIRuntime {
        if let boot = seams.boot { return try await boot() }
        return try await CLIRuntime.bootstrap(
            dataDirectory: dataDirectory, manifestOverride: manifestOverride,
            hostedLikeTheApp: true, concurrency: concurrency, takesEngineLease: false
        )
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
