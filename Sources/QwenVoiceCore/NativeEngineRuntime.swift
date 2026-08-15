import CryptoKit
import Foundation
import MLX
@preconcurrency import VocelloQwen3Core
import OSLog

enum NativeRuntimeStage: String, Codable, Sendable {
    case preparedCacheValidation
    case preparedCacheRebuild
    case tokenizerPreparation
    case upstreamModelLoad
    case prewarm
    case clonePreparation
    case streamStartup
    case firstChunk
    case streamGenerationEnded
    case streamCompleted
    case streamFailed
    case unload

    var description: String {
        switch self {
        case .preparedCacheValidation:
            return "prepared cache validation"
        case .preparedCacheRebuild:
            return "prepared cache rebuild"
        case .tokenizerPreparation:
            return "tokenizer preparation"
        case .upstreamModelLoad:
            return "native model load"
        case .prewarm:
            return "model warm-up"
        case .clonePreparation:
            return "clone preparation"
        case .streamStartup:
            return "generation startup"
        case .firstChunk:
            return "first stream chunk"
        case .streamGenerationEnded:
            return "stream generation ended"
        case .streamCompleted:
            return "generation completion"
        case .streamFailed:
            return "generation failure"
        case .unload:
            return "runtime unload"
        }
    }
}

struct NativeRuntimeError: LocalizedError, Sendable {
    let stage: NativeRuntimeStage
    let message: String
    let underlyingDescription: String?

    init(
        stage: NativeRuntimeStage,
        message: String,
        underlying: Error? = nil
    ) {
        self.stage = stage
        self.message = message
        self.underlyingDescription = underlying.map { String(reflecting: $0) }
    }

    var errorDescription: String? {
        message
    }

    static func wrapping(
        _ error: Error,
        stage: NativeRuntimeStage,
        message: String
    ) -> NativeRuntimeError {
        if let runtimeError = error as? NativeRuntimeError {
            return runtimeError
        }
        return NativeRuntimeError(
            stage: stage,
            message: "\(message) (\(stage.description)). \(error.localizedDescription)",
            underlying: error
        )
    }
}

/// Controls whether an attempt owns the durable terminal engine row. The first
/// attempt in allocation recovery defers only a retryable allocation failure;
/// the retry (or any non-retryable terminal) publishes normally. This prevents
/// two contradictory engine rows from sharing one public generation UUID.
enum NativeTelemetryTerminalPolicy: Sendable {
    case publish
    case deferRetryableAllocationFailure
}

enum NativeGenerationTerminalClassifier {
    static func reason(for error: Error) -> GenerationTerminalReason {
        if error is CancellationError { return .cancelled }
        let description = [error.localizedDescription, String(reflecting: error)]
            .joined(separator: "\n")
            .lowercased()
        if description.contains("cancellationerror")
            || description.contains("cancelled")
            || description.contains("canceled") {
            return .cancelled
        }
        return .failed
    }

    static func isRetryableAllocationFailure(_ error: Error) -> Bool {
        guard reason(for: error) != .cancelled else { return false }
        let lowercased = [
            error.localizedDescription,
            String(reflecting: error),
        ]
            .joined(separator: "\n")
            .lowercased()

        if lowercased.contains("out of memory")
            || lowercased.contains("resource exhausted")
            || lowercased.contains("failed to allocate") {
            return true
        }

        let allocationLike = lowercased.contains("allocation")
            || lowercased.contains("allocate")
            || lowercased.contains("memory")
        let mlxOrMetal = lowercased.contains("mlx")
            || lowercased.contains("metal")
            || lowercased.contains("mps")
            || lowercased.contains("gpu")
        return allocationLike && mlxOrMetal
    }

    static func shouldPublish(
        error: Error,
        policy: NativeTelemetryTerminalPolicy
    ) -> Bool {
        switch policy {
        case .publish:
            return true
        case .deferRetryableAllocationFailure:
            return !isRetryableAllocationFailure(error)
        }
    }
}

struct NativePreparedGeneration: Sendable {
    let generationID: UUID
    let requestID: Int
    let model: UnsafeSpeechGenerationModel
    let actorRequest: VocelloQwen3SynthesisRequest
    let cloneHandle: VocelloQwen3CloneHandle?
    let warmState: EngineWarmState
    let timingOverridesMS: [String: Int]
    let booleanFlags: [String: Bool]
    let stringFlags: [String: String]
    let cloneConditioning: ResolvedCloneConditioning?
    let wasPrimed: Bool
    let loadCapabilityProfile: NativeLoadCapabilityProfile
    let qwen3Capabilities: Qwen3TTSModelCapabilities
    let memoryPolicy: NativeMemoryPolicy
    let mlxMemorySnapshots: [String: NativeMLXMemorySnapshot]
    /// The per-generation telemetry recorder (nil when telemetry is gated off).
    /// Carried to the streaming session so its sampler shares the same start clock
    /// and its stage marks join the model-load/prewarm marks recorded here.
    let telemetryRecorder: NativeTelemetryRecorder?
    /// Prestarted before model load so memory/resource sampling covers cold load,
    /// conditioning, prewarm, synthesis, finalization, and trim on one clock.
    let telemetrySampler: NativeTelemetrySampler?
    let telemetryTerminalPolicy: NativeTelemetryTerminalPolicy
}

public struct InteractivePrefetchDiagnostics: Codable, Equatable, Sendable {
    public let timingsMS: [String: Int]
    public let booleanFlags: [String: Bool]
    public let requestKey: String?

    public init(
        timingsMS: [String: Int],
        booleanFlags: [String: Bool],
        requestKey: String?
    ) {
        self.timingsMS = timingsMS
        self.booleanFlags = booleanFlags
        self.requestKey = requestKey
    }
}

struct NativeClonePrimeResult: Sendable {
    let uiIdentityKey: String
}

actor NativeEngineRuntime {
    private static let signposter = OSSignposter(
        subsystem: "com.qwenvoice.engine",
        category: "runtime"
    )
    private static let logger = Logger(
        subsystem: "com.qwenvoice.engine",
        category: "runtime"
    )

    private enum DesignConditioningWarmSource: String, Sendable {
        case prefetch
        case generation
    }

    private let loadCoordinator: any MLXModelCoordinating
    private let audioPreparationService: any AudioPreparationService
    private let preparedCloneConditioningCache: NativePreparedCloneConditioningCache
    private let lightweightWarmupText: String
    /// Swapped per generation in `prepareGeneration` so stage marks land on a fresh
    /// recorder whose start clock matches the session's memory sampler.
    private var telemetryRecorder: NativeTelemetryRecorder?
    /// Retained so asynchronous pressure/warning/trim events can force a
    /// same-clock memory boundary sample while a generation is active.
    private var activeTelemetrySampler: NativeTelemetrySampler?
    private let customPrewarmPolicy: NativeCustomPrewarmPolicy
    private let diagnosticEventSink: (@Sendable (String, [String: String]) async -> Void)?
    private let diagnosticAppSupportBox: DiagnosticAppSupportBox?

    private var normalizedCloneReferenceDirectory: URL?
    private var voicesDirectory: URL?
    private var activeModelID: String?
    private var primedCloneReferenceKeys: Set<GenerationSemantics.CloneReferenceIdentity> = []
    private var clonePrimeTimingOverridesMS: [GenerationSemantics.CloneReferenceIdentity: [String: Int]] = [:]
    private var activeClonePrimeToken: UUID?
    private var activeDesignConditioningWarmIdentity: GenerationSemantics.DesignConditioningIdentity?
    private var activeDesignConditioningWarmSource: DesignConditioningWarmSource?
    private var activeDesignStreamStepWarmIdentity: GenerationSemantics.DesignConditioningIdentity?
    private var activeDesignStreamStepWarmSource: DesignConditioningWarmSource?
    private var activeCloneConditioningIdentity: GenerationSemantics.CloneReferenceIdentity?
    private var nextRequestID = 1

    /// Monitor-style gate that serializes Voice Design / Custom prewarm
    /// work across actor suspension points. The actor mutex alone
    /// doesn't suffice because the prewarm body does
    /// `try await model.prewarm{Custom,VoiceDesign}(...)`, which
    /// releases exclusive actor access while the upstream MLX call
    /// runs. Without this gate, two callers (e.g.,
    /// `prefetchInteractiveReadinessIfNeeded` from the UI's fire-and-
    /// forget warm-up and `prepareGeneration` from a user submit) can
    /// both reach MLX's KV cache slice updates simultaneously — the
    /// cache isn't thread-safe and trips an MLX assertion. See crash
    /// report `~/Library/Logs/DiagnosticReports/QwenVoiceEngineService-2026-05-15-162429.ips`
    /// for the failing call stacks.
    private struct PrewarmWaiter {
        let id: UUID
        let continuation: CheckedContinuation<Void, Error>
    }

    private var prewarmInFlight = false
    private var prewarmWaiters: [PrewarmWaiter] = []

    init(
        loadCoordinator: any MLXModelCoordinating,
        audioPreparationService: any AudioPreparationService,
        preparedCloneConditioningCache: NativePreparedCloneConditioningCache = NativePreparedCloneConditioningCache(),
        lightweightWarmupText: String,
        telemetryRecorder: NativeTelemetryRecorder? = nil,
        customPrewarmPolicy: NativeCustomPrewarmPolicy = .eager,
        diagnosticAppSupportBox: DiagnosticAppSupportBox? = nil,
        diagnosticEventSink: (@Sendable (String, [String: String]) async -> Void)? = nil
    ) {
        self.loadCoordinator = loadCoordinator
        self.audioPreparationService = audioPreparationService
        self.preparedCloneConditioningCache = preparedCloneConditioningCache
        self.lightweightWarmupText = lightweightWarmupText
        self.telemetryRecorder = telemetryRecorder
        self.customPrewarmPolicy = customPrewarmPolicy
        self.diagnosticAppSupportBox = diagnosticAppSupportBox
        self.diagnosticEventSink = diagnosticEventSink
    }

    func configure(normalizedCloneReferenceDirectory: URL?, voicesDirectory: URL? = nil) {
        self.normalizedCloneReferenceDirectory = normalizedCloneReferenceDirectory
        self.voicesDirectory = voicesDirectory
    }

    func stop() async {
        activeClonePrimeToken = nil
        await loadCoordinator.unloadModel()
        activeModelID = nil
        await clearCloneState()
        await clearQwen3MemoryCachesIfNeeded()
        await telemetryRecorder?.mark(stage: .unload)
    }

    func loadModel(id: String) async throws -> NativeModelLoadResult {
        try await loadModel(id: id, preserveActiveClonePrimeToken: false)
    }

    func unloadModel() async {
        await loadCoordinator.unloadModel()
        activeModelID = nil
        await clearCloneState()
        await clearQwen3MemoryCachesIfNeeded()
        await telemetryRecorder?.mark(stage: .unload)
        await activeTelemetrySampler?.captureBoundary("memory_unload")
        await telemetryRecorder?.mark(
            metadata: MemoryUnloadMetadata(reason: "runtime_unload", source: .runtime)
        )
    }

    /// Stamp the raw kernel memory-pressure signal onto the active generation's
    /// timeline. Distinct from `trimMemory`'s `memory_trim` mark, which records the
    /// trim *action* — and which is skipped when `acquirePrewarmSlot()` throws on a
    /// contended slot. This is a pure stage mark (no slot acquisition, no cache
    /// mutation), so a pressure moment is captured even when the resulting trim
    /// defers. No-op when no per-generation recorder is active.
    func recordMemoryPressureObserved(level: NativeMemoryTrimLevel) async {
        await activeTelemetrySampler?.captureBoundary("memory_pressure_signal")
        await telemetryRecorder?.mark(
            metadata: MemoryPressureMetadata(level: level, source: .kernel)
        )
    }

    func recordApplicationMemoryWarning(reason: String) async {
        await activeTelemetrySampler?.captureBoundary("application_memory_warning")
        await telemetryRecorder?.mark(
            metadata: MemoryWarningMetadata(reason: reason, source: .uiApplication)
        )
    }

    func recordMemoryBudgetTransition(
        from previousBand: IOSMemoryPressureBand,
        to currentBand: IOSMemoryPressureBand,
        reason: String
    ) async {
        guard previousBand != currentBand else { return }
        await activeTelemetrySampler?.captureBoundary("memory_budget_transition")
        await telemetryRecorder?.mark(
            metadata: MemoryBudgetTransitionMetadata(
                previousBand: previousBand,
                currentBand: currentBand,
                reason: reason,
                source: .runtime
            )
        )
    }

    func trimMemory(level: NativeMemoryTrimLevel, reason: String) async {
        // Serialize trims with in-flight MLX prewarm bodies so a kernel
        // pressure event cannot clear prepared-component caches while a
        // suspended `await model.prewarm*` is still running. Only register
        // the release when the slot was actually acquired: on a throw
        // (cancellation) `acquirePrewarmSlot()` does NOT hold the slot, so an
        // unconditional `defer { releasePrewarmSlot() }` would release a slot
        // owned by another task — flipping `prewarmInFlight` or waking a
        // waiter while a real holder is still inside MLX prewarm, which
        // reintroduces the concurrent KV-cache assertion crash this gate
        // exists to prevent.
        do {
            _ = try await acquirePrewarmSlot()
        } catch {
            return
        }
        defer { releasePrewarmSlot() }

        await activeTelemetrySampler?.captureBoundary("before_memory_trim")
        let eventSource: NativeMemoryEventSource = {
            if reason.contains("memory_warning") { return .uiApplication }
            if reason.contains("memory_pressure") { return .kernel }
            if reason.contains("post_generation") { return .postGeneration }
            return .runtime
        }()
        await telemetryRecorder?.mark(
            metadata: MemoryTrimMetadata(level: level, reason: reason, source: eventSource)
        )

        switch level {
        case .softTrim:
            await preparedCloneConditioningCache.softTrim(retainingMostRecent: 1)
            Memory.clearCache()
        case .hardTrim:
            await preparedCloneConditioningCache.clear()
            await loadCoordinator.clearPrewarmState()
            activeDesignConditioningWarmIdentity = nil
            activeDesignConditioningWarmSource = nil
            activeDesignStreamStepWarmIdentity = nil
            activeDesignStreamStepWarmSource = nil
            activeCloneConditioningIdentity = nil
            primedCloneReferenceKeys.removeAll()
            clonePrimeTimingOverridesMS.removeAll()
            Memory.clearCache()
            await clearQwen3MemoryCachesIfNeeded()
        case .fullUnload:
            await unloadModel()
        }
        await activeTelemetrySampler?.captureBoundary("after_memory_trim")
    }

    func prepareInteractiveReadiness(
        for request: GenerationRequest,
        customPrewarmDepth: String? = nil
    ) async throws -> InteractivePrefetchDiagnostics {
        try GenerationSemantics.validateQwenPromptContract(for: request)
        let descriptorCapabilities = try await loadCoordinator.qwen3Capabilities(for: request.modelID)
        try Self.validateCloneConditioningCapability(
            for: request,
            capabilities: descriptorCapabilities
        )
        let memoryPolicy = NativeMemoryPolicyResolver.policy(
            mode: request.mode,
            isBatch: false
        )
        NativeMemoryPolicyResolver.apply(memoryPolicy)
        let requestMemory = NativeMemoryPolicyResolver.memoryConfiguration(for: memoryPolicy)
        let prefetchStartedAt = ContinuousClock.now
        let identity = runtimePrewarmIdentity(for: request)
        let loadResult = try await loadModel(
            id: request.modelID,
            capabilityProfile: NativeLoadCapabilityProfile(for: request),
            preserveActiveClonePrimeToken: false
        )
        let model = loadResult.model.bound(
            to: Qwen3TalkerSamplingOverride.samplingConfiguration(
                requestedSeed: request.seed,
                variation: request.variation
            ),
            memory: requestMemory
        )
        await model.resetPreparationDiagnostics()
        var booleanFlags = loadResult.booleanFlags
        var timingsMS: [String: Int] = [
            "interactive_prefetch_load_model_ms": loadResult.didLoad ? prefetchStartedAt.elapsedMilliseconds : 0
        ]
        var conditioningPrepareMS = 0
        var requestKey: String?

        switch request.payload {
        case .custom:
            if shouldSkipDedicatedCustomPrewarm(for: request, model: model) {
                booleanFlags["custom_dedicated_prewarm_skipped"] = true
            } else {
                let genericWarmReady: Bool
                if let identity, activeModelID == request.modelID {
                    genericWarmReady = await loadCoordinator.isPrewarmed(identityKey: identity.cacheKey)
                } else {
                    genericWarmReady = false
                }
                if !genericWarmReady {
                    _ = try await ensureWarmStateIfNeeded(
                        for: request,
                        model: model,
                        customPrewarmDepth: customPrewarmDepth
                    )
                    booleanFlags.merge(await model.latestPreparationBooleanFlags()) { _, rhs in rhs }
                }
                requestKey = identity?.cacheKey
                timingsMS.merge(await model.latestPreparationTimingsMS()) { _, rhs in rhs }
            }
        case .design:
            let conditioningStartedAt = ContinuousClock.now
            let warmState = try await ensureDesignConditioningWarmStateIfNeeded(
                for: request,
                model: model,
                source: .prefetch
            )
            conditioningPrepareMS = warmState.prewarmed ? conditioningStartedAt.elapsedMilliseconds : 0
            requestKey = warmState.requestKey.isEmpty ? nil : warmState.requestKey
            booleanFlags.merge(await model.latestPreparationBooleanFlags()) { _, rhs in rhs }
            booleanFlags["design_conditioning_reused"] = warmState.reused
            booleanFlags["design_conditioning_prefetch_hit"] = warmState.prefetchHit
            booleanFlags["interactive_design_prefetch_hit"] = warmState.prefetchHit
            booleanFlags["design_conditioning_prewarmed"] = warmState.prewarmed
            booleanFlags["design_stream_step_prewarmed"] = warmState.streamStepPrewarmed
            booleanFlags["design_stream_step_prefetch_hit"] = warmState.streamStepPrefetchHit
            timingsMS["prewarm_slot_wait_ms"] = warmState.prewarmSlotWaitMS
            if let streamStepWarmMS = await model.latestPreparationTimingsMS()["design_stream_step_warm_ms"] {
                timingsMS["design_stream_step_warm_ms"] = streamStepWarmMS
            }
        case .clone:
            break
        }

        timingsMS["interactive_prefetch_conditioning_prepare_ms"] = conditioningPrepareMS
        timingsMS["interactive_prefetch_total_ms"] = prefetchStartedAt.elapsedMilliseconds
        return InteractivePrefetchDiagnostics(
            timingsMS: timingsMS,
            booleanFlags: booleanFlags,
            requestKey: requestKey
        )
    }

    func prepareGeneration(
        for request: GenerationRequest,
        telemetryTerminalPolicy: NativeTelemetryTerminalPolicy = .publish
    ) async throws -> NativePreparedGeneration {
        try GenerationSemantics.validateQwenPromptContract(for: request)
        let generationID = request.generationID ?? UUID()
        // Resolve a complete immutable policy once at the host boundary. The
        // effective seed is always present and the package owns a fresh MLX
        // random state for the request; no process-global RNG or variation
        // override is mutated here.
        let samplingConfiguration = Qwen3TalkerSamplingOverride.samplingConfiguration(
            requestedSeed: request.seed,
            variation: request.variation
        )
        // Fresh per-generation stage recorder, started at prepare entry (before model
        // load / prewarm) so the full backend timeline is measured from one origin.
        // Propagate to the load coordinator so its cache/tokenizer/model-load marks
        // share this recorder, and carry it to the session (same start clock as its
        // memory sampler). Nil — and therefore zero overhead — when telemetry is off.
        let telemetryRecorder: NativeTelemetryRecorder? = TelemetryGate.resolvedEnabled
            ? NativeTelemetryRecorder(clock: NativeTelemetryClock())
            : nil
        self.telemetryRecorder = telemetryRecorder
        await loadCoordinator.setTelemetryRecorder(telemetryRecorder)
        let memoryPolicy = NativeMemoryPolicyResolver.policy(
            mode: request.mode,
            isBatch: request.batchTotal != nil
        )
        NativeMemoryPolicyResolver.apply(memoryPolicy)
        let requestMemory = NativeMemoryPolicyResolver.memoryConfiguration(for: memoryPolicy)
        NativeMemoryPolicyResolver.resetPeakMemory()
        let telemetrySampler: NativeTelemetrySampler? = {
            guard let telemetryRecorder,
                  let sampleIntervalMS = NativeTelemetryMode.current().sampleIntervalMS(
                      for: memoryPolicy.deviceClass
                  ) else { return nil }
            return NativeTelemetrySampler(
                clock: telemetryRecorder.clock,
                sampleIntervalMS: sampleIntervalMS,
                processRole: .engine,
                boundaryRequirements: TelemetryBoundaryRequirement.engineGeneration
            )
        }()
        activeTelemetrySampler = telemetrySampler
        await telemetrySampler?.start()
        await telemetrySampler?.captureBoundary("before_preparation")
        do {
        let benchNotes = BenchRunContext.telemetryNotes()
        let benchRunID = benchNotes["benchRunID"] ?? "not-bench"
        let benchTakeIndex = benchNotes["benchTakeIndex"] ?? "not-bench"
        let benchCell = benchNotes["benchCell"] ?? "not-bench"
        let prepareSignpostID = Self.signposter.makeSignpostID()
        let prepareSignpost = Self.signposter.beginInterval(
            "Native Prepare Generation",
            id: prepareSignpostID,
            "runID=\(benchRunID, privacy: .public) generationID=\(generationID.uuidString, privacy: .public) takeIndex=\(benchTakeIndex, privacy: .public) cell=\(benchCell, privacy: .public)"
        )
        let prepareStartedAt = ContinuousClock.now
        defer {
            Self.signposter.endInterval(
                "Native Prepare Generation",
                prepareSignpost,
                "runID=\(benchRunID, privacy: .public) generationID=\(generationID.uuidString, privacy: .public) takeIndex=\(benchTakeIndex, privacy: .public) cell=\(benchCell, privacy: .public)"
            )
        }
        let descriptorCapabilities = try await loadCoordinator.qwen3Capabilities(for: request.modelID)
        try Self.validateCloneConditioningCapability(
            for: request,
            capabilities: descriptorCapabilities
        )
        await recordDiagnosticEvent(
            "runtime-prepare-before-load-model",
            request: request,
            capabilities: descriptorCapabilities
        )
        let loadStartedAt = ContinuousClock.now
        let loadCapabilityProfile = NativeLoadCapabilityProfile(for: request)
        await telemetrySampler?.captureBoundary("before_model_load")

        var mlxMemorySnapshots: [String: NativeMLXMemorySnapshot] = [
            "before_load": NativeMemoryPolicyResolver.snapshot()
        ]
        let loadResult = try await loadModel(
            id: request.modelID,
            capabilityProfile: loadCapabilityProfile,
            preserveActiveClonePrimeToken: false,
            signpostGenerationID: generationID
        )
        await telemetrySampler?.captureBoundary("after_model_load")
        mlxMemorySnapshots["after_load"] = NativeMemoryPolicyResolver.snapshot()
        await recordDiagnosticEvent(
            "runtime-prepare-after-load-model",
            request: request,
            capabilities: loadResult.qwen3Capabilities,
            extra: [
                "didLoad": loadResult.didLoad ? "true" : "false",
                "nativeLoadCapabilityProfile": loadCapabilityProfile.rawValue,
                "memoryPolicy": memoryPolicy.name,
            ]
        )
        let model = loadResult.model.bound(
            to: samplingConfiguration,
            memory: requestMemory
        )
        await model.resetPreparationDiagnostics()
        await recordDiagnosticEvent(
            "runtime-prepare-after-reset-preparation-diagnostics",
            request: request,
            capabilities: loadResult.qwen3Capabilities
        )
        var timingOverridesMS = loadResult.timingsMS
        var booleanFlags = loadResult.booleanFlags
        var stringFlags = loadResult.stringFlags
        stringFlags["sampling_algorithm_version"] = String(samplingConfiguration.algorithmVersion)
        stringFlags["sampling_effective_seed"] = String(samplingConfiguration.effectiveSeed)
        stringFlags["sampling_talker_top_k"] = String(samplingConfiguration.talker.topK)
        stringFlags["sampling_subtalker_top_k"] = String(samplingConfiguration.subtalker.topK)

        if loadResult.didLoad {
            timingOverridesMS["load_model"] = loadStartedAt.elapsedMilliseconds
        }

        let cloneConditioning: ResolvedCloneConditioning?
        let wasPrimed: Bool
        await telemetrySampler?.captureBoundary("before_mode_preparation")
        switch request.payload {
        case .clone(let reference):
            var conditioning = try await resolveCloneConditioning(
                modelID: request.modelID,
                reference: reference,
                sampleRate: model.sampleRate,
                signpostGenerationID: generationID
            )
            let cloneLanguage = GenerationSemantics.qwenLanguageHint(
                for: request,
                resolvedCloneTranscript: conditioning.resolvedTranscript
            )
            conditioning = try await preparedCloneConditioningCache.resolveVoiceClonePrompt(
                for: conditioning,
                modelID: request.modelID,
                model: model,
                voicesDirectory: voicesDirectory,
                language: cloneLanguage,
                modelRuntimeIdentity: loadResult.modelRuntimeIdentity
            )
            cloneConditioning = conditioning
            mlxMemorySnapshots["after_clone_conditioning"] = NativeMemoryPolicyResolver.snapshot()
            wasPrimed = primedCloneReferenceKeys.contains(conditioning.internalIdentity)
            timingOverridesMS.merge(conditioning.timingsMS) { current, _ in current }
            booleanFlags["clone_prompt_artifact_hit"] = conditioning.timingsMS["clone_prompt_artifact_load"] != nil
            booleanFlags["clone_prompt_memory_hit"] = conditioning.clonePromptCacheHit == true
                && conditioning.timingsMS["clone_prompt_artifact_load"] == nil
            booleanFlags["clone_prompt_built"] = conditioning.timingsMS["clone_prompt_build"] != nil
            booleanFlags["clone_transcript_backed"] = conditioning.conditioningMode.usesTranscript
            booleanFlags["clone_x_vector_only"] = conditioning.conditioningMode.isXVectorOnly
            booleanFlags["clone_reference_was_primed"] = wasPrimed
            stringFlags["clone_transcript_mode"] = conditioning.transcriptMode.rawValue
            stringFlags["clone_conditioning_mode"] = conditioning.conditioningMode.identifier
            stringFlags["qwen3_supports_x_vector_only_clone"] = loadResult.qwen3Capabilities
                .supportsXVectorOnlyClone ? "true" : "false"
            stringFlags["clone_prompt_artifact_scope"] = conditioning.preparedVoiceID == nil
                ? "transient_reference"
                : "saved_voice"
            let cloneConditioningReused = conditioning.cloneConditioningReused
                || activeCloneConditioningIdentity == conditioning.internalIdentity
            booleanFlags["clone_conditioning_reused"] = cloneConditioningReused
            activeCloneConditioningIdentity = conditioning.internalIdentity
            if wasPrimed,
               let primeTimings = clonePrimeTimingOverridesMS[conditioning.internalIdentity] {
                await telemetrySampler?.captureBoundary("prewarm_skipped")
                timingOverridesMS.merge(primeTimings) { current, _ in current }
            } else {
                await telemetrySampler?.captureBoundary("before_prewarm")
                let prewarmTimings = try await ensureWarmStateIfNeeded(
                    for: request,
                    model: model,
                    cloneConditioning: conditioning
                )
                await telemetrySampler?.captureBoundary("after_prewarm")
                timingOverridesMS.merge(prewarmTimings) { _, rhs in rhs }
                booleanFlags.merge(await model.latestPreparationBooleanFlags()) { _, rhs in rhs }
            }
            mlxMemorySnapshots["after_prewarm"] = NativeMemoryPolicyResolver.snapshot()
            booleanFlags["clone_optimized_handler_used"] = model.supportsOptimizedVoiceClone
        case .custom:
            await recordDiagnosticEvent(
                "runtime-prepare-custom-entered",
                request: request,
                capabilities: loadResult.qwen3Capabilities,
                extra: [
                    "supportsDedicatedCustomVoice": model.supportsDedicatedCustomVoice ? "true" : "false",
                    "customPrewarmPolicy": customPrewarmPolicyLabel,
                ]
            )
            cloneConditioning = nil
            wasPrimed = false
            if shouldSkipDedicatedCustomPrewarm(for: request, model: model) {
                booleanFlags["custom_dedicated_prewarm_skipped"] = true
                await telemetrySampler?.captureBoundary("prewarm_skipped")
                await recordDiagnosticEvent(
                    "runtime-prepare-custom-skip-dedicated-prewarm",
                    request: request,
                    capabilities: loadResult.qwen3Capabilities
                )
            } else {
                // For short Built-in Voice prompts (~one sentence or less),
                // skip the decoder-bucket precompile inside prewarm. The
                // vendor exposes three depths — `.full`,
                // `.skipDecoderBucket`, `.skipStreamStep` — and the
                // bucket precompile is the largest cost in the prewarm
                // pass. For long prompts it's worth doing up front (we
                // amortize it across many tokens); for short prompts the
                // decoder compiles on first decode without measurable
                // user-visible delay. Same audio output either way —
                // only WHERE the compile cost lands changes. Threshold
                // is the warm-short bucket cutoff (~30 chars) so it
                // matches the bench harness's warm-short cell.
                let customPrewarmDepth = Self.customPrewarmDepth(for: request)
                await telemetrySampler?.captureBoundary("before_prewarm")
                let prewarmTimings = try await ensureWarmStateIfNeeded(
                    for: request,
                    model: model,
                    customPrewarmDepth: customPrewarmDepth
                )
                await telemetrySampler?.captureBoundary("after_prewarm")
                timingOverridesMS.merge(prewarmTimings) { _, rhs in rhs }
                booleanFlags.merge(await model.latestPreparationBooleanFlags()) { _, rhs in rhs }
            }
            mlxMemorySnapshots["after_prewarm"] = NativeMemoryPolicyResolver.snapshot()
            booleanFlags["custom_dedicated_handler_used"] = model.supportsDedicatedCustomVoice
        case .design:
            cloneConditioning = nil
            wasPrimed = false
            await telemetrySampler?.captureBoundary("before_prewarm")
            let warmState = try await ensureDesignConditioningWarmStateIfNeeded(
                for: request,
                model: model,
                source: .generation
            )
            await telemetrySampler?.captureBoundary("after_prewarm")
            timingOverridesMS.merge(await model.latestPreparationTimingsMS()) { _, rhs in rhs }
            timingOverridesMS["prewarm_slot_wait_ms"] = warmState.prewarmSlotWaitMS
            booleanFlags.merge(await model.latestPreparationBooleanFlags()) { _, rhs in rhs }
            let warmBucket = warmState.bucket
            booleanFlags["design_conditioning_reused"] = warmState.reused
            booleanFlags["design_conditioning_prefetch_hit"] = warmState.prefetchHit
            booleanFlags["interactive_design_prefetch_hit"] = warmState.prefetchHit
            booleanFlags["design_conditioning_prewarmed"] = warmState.prewarmed
            booleanFlags["design_stream_step_prewarmed"] = warmState.streamStepPrewarmed
            booleanFlags["design_stream_step_prefetch_hit"] = warmState.streamStepPrefetchHit
            booleanFlags["design_warm_bucket_short"] = warmBucket == .short
            booleanFlags["design_warm_bucket_long"] = warmBucket == .long
            booleanFlags["design_optimized_handler_used"] = model.supportsOptimizedVoiceDesign
            stringFlags["design_conditioning_request_key"] = warmState.requestKey
            mlxMemorySnapshots["after_prewarm"] = NativeMemoryPolicyResolver.snapshot()
        }
        await telemetrySampler?.captureBoundary("after_mode_preparation")

        if cloneConditioning?.cloneCacheHit != nil {
            booleanFlags["prepared_clone_cache_hit"] = cloneConditioning?.cloneCacheHit ?? false
        }
        if let referenceWarnings = cloneConditioning?.referenceQualityWarnings,
           !referenceWarnings.isEmpty {
            stringFlags["clone_reference_warnings"] = referenceWarnings.joined(separator: ",")
        }

        await recordDiagnosticEvent(
            "runtime-prepare-before-return",
            request: request,
            capabilities: loadResult.qwen3Capabilities,
            extra: [
                "customDedicatedHandlerUsed": booleanFlags["custom_dedicated_handler_used"] == true ? "true" : "false",
                "customDedicatedPrewarmSkipped": booleanFlags["custom_dedicated_prewarm_skipped"] == true ? "true" : "false",
                "designOptimizedHandlerUsed": booleanFlags["design_optimized_handler_used"] == true ? "true" : "false",
                "cloneOptimizedHandlerUsed": booleanFlags["clone_optimized_handler_used"] == true ? "true" : "false",
            ]
        )

        timingOverridesMS["native_prepare_generation_ms"] = prepareStartedAt.elapsedMilliseconds
        Self.recordGenerationPlanShadow(
            request: request,
            generationID: generationID,
            modelRuntimeIdentity: loadResult.modelRuntimeIdentity,
            qwen3Capabilities: loadResult.qwen3Capabilities,
            memoryPolicy: memoryPolicy,
            samplingConfiguration: samplingConfiguration,
            cloneConditioning: cloneConditioning,
            booleanFlags: &booleanFlags,
            stringFlags: &stringFlags
        )
        let actorRequest = try Self.makeActorRequest(
            request: request,
            generationID: generationID,
            capabilities: loadResult.qwen3Capabilities,
            memoryPolicy: memoryPolicy,
            samplingConfiguration: samplingConfiguration,
            requestMemory: requestMemory,
            cloneConditioning: cloneConditioning
        )
        let cloneHandle: VocelloQwen3CloneHandle?
        if case .voiceClone = actorRequest.input {
            guard let cloneConditioning,
                  let resolvedHandle = cloneConditioning.cloneHandle else {
                throw MLXTTSEngineError.unsupportedRequest(
                    "Voice Cloning requires validated schema-3 conditioning before generation."
                )
            }
            cloneHandle = resolvedHandle
        } else {
            cloneHandle = nil
        }
        await telemetrySampler?.captureBoundary("after_preparation")
        return NativePreparedGeneration(
            // Reuse the app-minted ID so app/middle/engine telemetry rows correlate;
            // fall back to a fresh UUID for callers (e.g. internal batch) passing nil.
            generationID: generationID,
            requestID: takeNextRequestID(),
            model: model,
            actorRequest: actorRequest,
            cloneHandle: cloneHandle,
            warmState: loadResult.didLoad ? .cold : .warm,
            timingOverridesMS: timingOverridesMS,
            booleanFlags: booleanFlags,
            stringFlags: stringFlags,
            cloneConditioning: cloneConditioning,
            wasPrimed: wasPrimed,
            loadCapabilityProfile: loadResult.capabilityProfile,
            qwen3Capabilities: loadResult.qwen3Capabilities,
            memoryPolicy: memoryPolicy,
            mlxMemorySnapshots: mlxMemorySnapshots,
            telemetryRecorder: telemetryRecorder,
            telemetrySampler: telemetrySampler,
            telemetryTerminalPolicy: telemetryTerminalPolicy
        )
        } catch {
            await telemetrySampler?.captureBoundary("preparation_failed")
            await telemetryRecorder?.mark(
                metadata: StreamFailureMessageMetadata(message: error.localizedDescription)
            )
            let stageMarks = await telemetryRecorder?.snapshot() ?? []
            let stopped = await telemetrySampler?.stop(stageMarks: stageMarks)
            let summary = stopped?.summary ?? TelemetrySummary.empty(stageMarks: stageMarks)
            if NativeGenerationTerminalClassifier.shouldPublish(
                error: error,
                policy: telemetryTerminalPolicy
            ), TelemetryGate.resolvedEnabled,
               let appSupportDirectory = diagnosticAppSupportBox?.url {
                var failureNotes = GenerationTelemetryPrivacy.failureNotes(
                    message: error.localizedDescription
                ).merging(BenchRunContext.telemetryNotes()) { current, _ in current }
                failureNotes["samplingVariation"] = (request.variation ?? .expressive).rawValue
                failureNotes["samplingAlgorithmVersion"] = String(
                    samplingConfiguration.algorithmVersion
                )
                failureNotes["samplingSeed"] = String(samplingConfiguration.effectiveSeed)
                failureNotes["samplingSeedSource"] = request.seed == nil ? "generated" : "requested"
                let record = GenerationTelemetryRecord(
                    generationID: generationID.uuidString,
                    layer: .engine,
                    recordedAt: ISO8601DateFormatter().string(from: Date()),
                    mode: request.modeIdentifier,
                    modelID: request.modelID,
                    finishReason: NativeGenerationTerminalClassifier.reason(for: error).rawValue,
                    stageMarks: stageMarks,
                    summary: summary,
                    thermalState: summary.thermalState,
                    notes: failureNotes
                )
                await GenerationTelemetryJSONLSink.shared.write(
                    record: record,
                    appSupportDirectory: appSupportDirectory,
                    subdirectory: "engine"
                )
                if NativeTelemetryMode.current().persistsRawSamples,
                   let samples = stopped?.samples,
                   !samples.isEmpty {
                    await GenerationTelemetryJSONLSink.shared.writeRawSamples(
                        samples,
                        generationID: generationID.uuidString,
                        appSupportDirectory: appSupportDirectory,
                        subdirectory: "engine"
                    )
                }
            }
            throw error
        }
    }

    private static func makeActorRequest(
        request: GenerationRequest,
        generationID: UUID,
        capabilities: Qwen3TTSModelCapabilities,
        memoryPolicy: NativeMemoryPolicy,
        samplingConfiguration: VocelloQwen3SamplingConfiguration,
        requestMemory: VocelloQwen3MemoryConfiguration,
        cloneConditioning: ResolvedCloneConditioning?
    ) throws -> VocelloQwen3SynthesisRequest {
        let effectiveInterval = NativeMemoryPolicyResolver.effectiveStreamingInterval(
            requested: request.streamingInterval,
            request: request,
            policy: memoryPolicy
        )
        let chunkPolicy = StreamChunkPolicy.currentShippingDefault(
            for: request.mode,
            effectiveStreamingInterval: effectiveInterval
        )
        // Phase 10 close-out: every take speaks the same conservatively
        // normalized text long-form segments already receive. The planner is
        // deterministic and idempotent, so text normalized upstream (long-form
        // segments, batch lines) passes through unchanged, and the fixed bench
        // corpus is normalization-invariant by contract (core-tested).
        let spokenText: String
        do {
            spokenText = try SpokenTextPlanner.plan(originalText: request.text).spokenText
        } catch {
            throw MLXTTSEngineError.unsupportedRequest(
                "Spoken-text planning rejected the script: \(error)"
            )
        }
        let prompt = GenerationSemantics.qwen3PromptAssembly(
            for: request,
            capabilities: capabilities,
            resolvedCloneTranscript: cloneConditioning?.resolvedTranscript,
            spokenText: spokenText
        )
        let input: VocelloQwen3SynthesisInput
        switch request.payload {
        case .custom:
            input = .customVoice(
                speakerID: prompt.speakerID ?? GenerationSemantics.canonicalCustomWarmSpeaker,
                deliveryInstruction: prompt.instruct
            )
        case .design:
            input = .voiceDesign(description: prompt.instruct ?? "")
        case .clone:
            guard let conditioningDigest = cloneConditioning?.internalIdentity.digest else {
                throw MLXTTSEngineError.unsupportedRequest(
                    "Voice Cloning needs a validated conditioning identity."
                )
            }
            input = .voiceClone(referenceID: conditioningDigest)
        }
        return VocelloQwen3SynthesisRequest(
            generationID: generationID,
            text: spokenText,
            language: prompt.language,
            input: input,
            sampling: samplingConfiguration,
            memory: requestMemory,
            chunking: VocelloQwen3StreamChunkConfiguration(
                firstCodecFrames: chunkPolicy.firstCodecFrames,
                laterCodecFrames: chunkPolicy.laterCodecFrames,
                pendingFrameLimit: chunkPolicy.pendingFrameLimit,
                materializationLeadSteps: chunkPolicy.materializationLeadSteps
            ),
            executionStyle: request.shouldStream ? .streaming : .qualityFirst
        )
    }

    func primeCloneReference(
        modelID: String,
        reference: CloneReference
    ) async throws -> NativeClonePrimeResult {
        let capabilities = try await loadCoordinator.qwen3Capabilities(for: modelID)
        try Self.validateCloneConditioningCapability(
            reference: reference,
            capabilities: capabilities
        )
        let memoryPolicy = NativeMemoryPolicyResolver.policy(
            mode: .clone,
            isBatch: false
        )
        NativeMemoryPolicyResolver.apply(memoryPolicy)
        let token = UUID()
        activeClonePrimeToken = token
        defer {
            if activeClonePrimeToken == token {
                activeClonePrimeToken = nil
            }
        }

        let loadStartedAt = ContinuousClock.now
        let loadResult = try await loadModel(
            id: modelID,
            capabilityProfile: .cloneOnly,
            preserveActiveClonePrimeToken: true
        )
        // Priming must run under the same request-scoped memory configuration
        // as a real generation. The unbound wrapper falls back to
        // `.compatibilityDefault`, whose unbounded token-loop accumulation
        // spiked an iPhone prime from ~2.0 GB to ~5.1 GB resident and tripped
        // the memory-warning full unload of the just-loaded model.
        let model = loadResult.model.bound(
            to: loadResult.model.samplingConfiguration,
            memory: NativeMemoryPolicyResolver.memoryConfiguration(for: memoryPolicy)
        )
        try ensureActiveClonePrimeToken(token)

        let conditioning = try await resolveCloneConditioning(
            modelID: modelID,
            reference: reference,
            sampleRate: model.sampleRate
        )
        let cloneLanguage = GenerationSemantics.qwenLanguageHint(
            for: GenerationRequest(
                mode: .clone,
                modelID: modelID,
                text: lightweightWarmupText,
                outputPath: "",
                shouldStream: false,
                payload: .clone(reference: reference)
            ),
            resolvedCloneTranscript: conditioning.resolvedTranscript
        )
        let resolvedConditioning = try await preparedCloneConditioningCache.resolveVoiceClonePrompt(
            for: conditioning,
            modelID: modelID,
            model: model,
            voicesDirectory: voicesDirectory,
            language: cloneLanguage,
            modelRuntimeIdentity: loadResult.modelRuntimeIdentity
        )
        try ensureActiveClonePrimeToken(token)

        if primedCloneReferenceKeys.contains(resolvedConditioning.internalIdentity) {
            return NativeClonePrimeResult(uiIdentityKey: resolvedConditioning.uiIdentityKey)
        }

        activeCloneConditioningIdentity = resolvedConditioning.internalIdentity

        var timingOverrides = loadResult.timingsMS
        timingOverrides.merge(resolvedConditioning.timingsMS) { _, rhs in rhs }
        if loadResult.didLoad {
            timingOverrides["load_model"] = loadStartedAt.elapsedMilliseconds
        }

        let primeTimings = try await primeCloneConditioning(
            model: model,
            conditioning: resolvedConditioning,
            language: cloneLanguage,
            token: token
        )
        timingOverrides.merge(primeTimings) { _, rhs in rhs }
        clonePrimeTimingOverridesMS[resolvedConditioning.internalIdentity] = timingOverrides
        primedCloneReferenceKeys.insert(resolvedConditioning.internalIdentity)
        return NativeClonePrimeResult(uiIdentityKey: resolvedConditioning.uiIdentityKey)
    }

    func cancelClonePreparation() {
        activeClonePrimeToken = nil
    }

    func prebuildSavedVoiceClonePrompt(
        modelID: String,
        reference: CloneReference
    ) async {
        guard reference.preparedVoiceID != nil else { return }
        if let activeModelID, activeModelID != modelID {
            return
        }

        do {
            let capabilities = try await loadCoordinator.qwen3Capabilities(for: modelID)
            try Self.validateCloneConditioningCapability(
                reference: reference,
                capabilities: capabilities
            )
            let loadResult = try await loadModel(
                id: modelID,
                capabilityProfile: .cloneOnly,
                preserveActiveClonePrimeToken: true
            )
            let conditioning = try await resolveCloneConditioning(
                modelID: modelID,
                reference: reference,
                sampleRate: loadResult.model.sampleRate
            )
            _ = try await preparedCloneConditioningCache.resolveVoiceClonePrompt(
                for: conditioning,
                modelID: modelID,
                model: loadResult.model,
                voicesDirectory: voicesDirectory,
                language: GenerationSemantics.qwenLanguageHint(
                    for: GenerationRequest(
                        mode: .clone,
                        modelID: modelID,
                        text: lightweightWarmupText,
                        outputPath: "",
                        shouldStream: false,
                        payload: .clone(reference: reference)
                    ),
                    resolvedCloneTranscript: conditioning.resolvedTranscript
                ),
                modelRuntimeIdentity: loadResult.modelRuntimeIdentity
            )
        } catch {
            return
        }
    }

    private func loadModel(
        id: String,
        capabilityProfile: NativeLoadCapabilityProfile = .fullCapabilities,
        preserveActiveClonePrimeToken: Bool,
        signpostGenerationID: UUID? = nil
    ) async throws -> NativeModelLoadResult {
        let benchNotes = BenchRunContext.telemetryNotes()
        let runID = benchNotes["benchRunID"] ?? "not-bench"
        let takeIndex = benchNotes["benchTakeIndex"] ?? "not-bench"
        let cell = benchNotes["benchCell"] ?? "not-bench"
        let generationID = signpostGenerationID?.uuidString ?? "not-generation"
        let loadSignpost = Self.signposter.beginInterval(
            "Native Model Load",
            "runID=\(runID, privacy: .public) generationID=\(generationID, privacy: .public) takeIndex=\(takeIndex, privacy: .public) cell=\(cell, privacy: .public)"
        )
        let loadStartedAt = ContinuousClock.now
        defer {
            Self.signposter.endInterval(
                "Native Model Load",
                loadSignpost,
                "runID=\(runID, privacy: .public) generationID=\(generationID, privacy: .public) takeIndex=\(takeIndex, privacy: .public) cell=\(cell, privacy: .public)"
            )
        }
        do {
#if os(iOS)
            if let previousModelID = activeModelID, previousModelID != id {
                Self.logger.notice(
                    "Clearing iOS model-switch caches before load; from=\(previousModelID, privacy: .public), to=\(id, privacy: .public), profile=\(capabilityProfile.rawValue, privacy: .public)"
                )
                await telemetryRecorder?.mark(
                    metadata: ModelSwitchCacheClearMetadata(
                        fromModelID: previousModelID,
                        toModelID: id,
                        capabilityProfile: capabilityProfile
                    )
                )
                await loadCoordinator.unloadModel()
                activeModelID = nil
                await clearCloneState(preserveActiveClonePrimeToken: preserveActiveClonePrimeToken)
                await clearQwen3MemoryCachesIfNeeded()
                Memory.clearCache()
                await recordDiagnosticEvent(
                    "runtime-load-model-preswitch-cache-clear",
                    extra: [
                        "fromModelID": previousModelID,
                        "toModelID": id,
                        "nativeLoadCapabilityProfile": capabilityProfile.rawValue,
                    ]
                )
            }
#endif
            let loadResult = try await loadCoordinator.loadModel(
                id: id,
                capabilityProfile: capabilityProfile
            )
            if loadResult.didLoad {
                activeModelID = id
                await clearCloneState(preserveActiveClonePrimeToken: preserveActiveClonePrimeToken)
            }
            var mutableLoadResult = loadResult
            mutableLoadResult.timingsMS["native_model_load_ms"] = loadStartedAt.elapsedMilliseconds
            return mutableLoadResult
        } catch {
            await loadCoordinator.unloadModel()
            activeModelID = nil
            await clearCloneState(preserveActiveClonePrimeToken: preserveActiveClonePrimeToken)
            await clearQwen3MemoryCachesIfNeeded()
            throw NativeRuntimeError.wrapping(
                error,
                stage: .upstreamModelLoad,
                message: "The native runtime could not load model '\(id)'"
            )
        }
    }

    private func resolveCloneConditioning(
        modelID: String,
        reference: CloneReference,
        sampleRate: Int,
        signpostGenerationID: UUID? = nil
    ) async throws -> ResolvedCloneConditioning {
        let benchNotes = BenchRunContext.telemetryNotes()
        let runID = benchNotes["benchRunID"] ?? "not-bench"
        let takeIndex = benchNotes["benchTakeIndex"] ?? "not-bench"
        let cell = benchNotes["benchCell"] ?? "not-bench"
        let generationID = signpostGenerationID?.uuidString ?? "not-generation"
        let conditioningSignpost = Self.signposter.beginInterval(
            "Native Clone Conditioning",
            "runID=\(runID, privacy: .public) generationID=\(generationID, privacy: .public) takeIndex=\(takeIndex, privacy: .public) cell=\(cell, privacy: .public)"
        )
        let conditioningStartedAt = ContinuousClock.now
        defer {
            Self.signposter.endInterval(
                "Native Clone Conditioning",
                conditioningSignpost,
                "runID=\(runID, privacy: .public) generationID=\(generationID, privacy: .public) takeIndex=\(takeIndex, privacy: .public) cell=\(cell, privacy: .public)"
            )
        }
        do {
            await telemetryRecorder?.mark(stage: .clonePreparation)
            var conditioning = try await preparedCloneConditioningCache.resolve(
                modelID: modelID,
                reference: reference,
                sampleRate: sampleRate,
                audioPreparationService: audioPreparationService,
                normalizedCloneReferenceDirectory: try requireNormalizedCloneReferenceDirectory()
            )
            conditioning.timingsMS["native_clone_conditioning_ms"] = conditioningStartedAt.elapsedMilliseconds
            return conditioning
        } catch {
            throw NativeRuntimeError.wrapping(
                error,
                stage: .clonePreparation,
                message: "The native runtime could not prepare the clone reference"
            )
        }
    }

    private func ensureWarmStateIfNeeded(
        for request: GenerationRequest,
        model: UnsafeSpeechGenerationModel,
        cloneConditioning: ResolvedCloneConditioning? = nil,
        customPrewarmDepth: String? = nil
    ) async throws -> [String: Int] {
        if shouldSkipDedicatedCustomPrewarm(for: request, model: model) {
            return [:]
        }
        // Serialize with any concurrent prewarm in flight. See
        // `acquirePrewarmSlot` for the rationale. The slot covers the
        // entire body including the `try await model.prewarm*(...)`
        // suspension — that's what makes it safe against actor
        // reentrancy.
        let prewarmSlotWaitMS = try await acquirePrewarmSlot()
        defer { releasePrewarmSlot() }
        try Task.checkCancellation()

        let benchNotes = BenchRunContext.telemetryNotes()
        let runID = benchNotes["benchRunID"] ?? "not-bench"
        let takeIndex = benchNotes["benchTakeIndex"] ?? "not-bench"
        let cell = benchNotes["benchCell"] ?? "not-bench"
        let generationID = request.generationID?.uuidString ?? "not-generation"
        let prewarmSignpost = Self.signposter.beginInterval(
            "Native Explicit Prewarm",
            "runID=\(runID, privacy: .public) generationID=\(generationID, privacy: .public) takeIndex=\(takeIndex, privacy: .public) cell=\(cell, privacy: .public)"
        )
        let explicitPrewarmStartedAt = ContinuousClock.now
        defer {
            Self.signposter.endInterval(
                "Native Explicit Prewarm",
                prewarmSignpost,
                "runID=\(runID, privacy: .public) generationID=\(generationID, privacy: .public) takeIndex=\(takeIndex, privacy: .public) cell=\(cell, privacy: .public)"
            )
        }

        let identity: GenerationSemantics.PrewarmIdentity
        switch request.payload {
        case .custom, .design:
            guard let requestIdentity = runtimePrewarmIdentity(for: request) else {
                return [
                    "prewarm_slot_wait_ms": prewarmSlotWaitMS,
                    "native_explicit_prewarm_ms": explicitPrewarmStartedAt.elapsedMilliseconds,
                ]
            }
            identity = requestIdentity
        case .clone:
            guard let cloneConditioning else {
                throw NativeRuntimeError(
                    stage: .clonePreparation,
                    message: "Clone generation needs resolved native clone conditioning."
                )
            }
            identity = .clone(cloneConditioning.internalIdentity)
        }
        let identityKey = identity.cacheKey

        guard !(await loadCoordinator.isPrewarmed(identityKey: identityKey)) else {
            // Already prewarmed — record the hit so bench traces can
            // distinguish "warm cell really skipped prewarm" from "warm
            // cell paid a fast prewarm." Pairs with the analogous event
            // in `ensureDesignConditioningWarmStateIfNeeded`.
            Self.signposter.emitEvent(
                "Native Prewarm Cache Hit",
                "runID=\(runID, privacy: .public) generationID=\(generationID, privacy: .public) takeIndex=\(takeIndex, privacy: .public) cell=\(cell, privacy: .public)"
            )
            return [
                "prewarm_slot_wait_ms": prewarmSlotWaitMS,
                "native_explicit_prewarm_ms": explicitPrewarmStartedAt.elapsedMilliseconds,
            ]
        }

        let prewarmStartedAt = ContinuousClock.now
        do {
            await telemetryRecorder?.mark(stage: .prewarm)
            switch request.payload {
            case .custom:
                let capabilities = try await loadCoordinator.qwen3Capabilities(for: request.modelID)
                let prompt = GenerationSemantics.qwen3PromptAssembly(
                    for: request,
                    capabilities: capabilities
                )
                try await model.prewarmCustomVoice(
                    text: lightweightWarmupText,
                    language: prompt.language,
                    speaker: prompt.speakerID ?? GenerationSemantics.canonicalCustomWarmSpeaker,
                    instruct: prompt.instruct,
                    customPrewarmDepth: customPrewarmDepth
                )
            case .design:
                let language = GenerationSemantics.qwenLanguageHint(for: request)
                try await model.prewarmVoiceDesign(
                    text: lightweightWarmupText,
                    language: language,
                    voiceDescription: GenerationSemantics.canonicalDesignWarmInstruction()
                )
            case .clone:
                guard let cloneConditioning else {
                    throw NativeRuntimeError(
                        stage: .clonePreparation,
                        message: "Clone generation needs resolved native clone conditioning."
                    )
                }
                guard let cloneHandle = cloneConditioning.cloneHandle else {
                    throw NativeRuntimeError(
                        stage: .clonePreparation,
                        message: "Clone generation needs optimized Qwen3 clone conditioning."
                    )
                }
                let language = GenerationSemantics.qwenLanguageHint(
                    for: request,
                    resolvedCloneTranscript: cloneConditioning.resolvedTranscript
                )
                try await model.prewarmVoiceClone(
                    text: lightweightWarmupText,
                    language: language,
                    cloneHandle: cloneHandle
                )
            }
            await loadCoordinator.markPrewarmed(identityKey: identityKey)
            var timings = await model.latestPreparationTimingsMS()
            timings["prewarm_model"] = prewarmStartedAt.elapsedMilliseconds
            timings["prewarm_slot_wait_ms"] = prewarmSlotWaitMS
            timings["native_explicit_prewarm_ms"] = explicitPrewarmStartedAt.elapsedMilliseconds
            return timings
        } catch {
            await loadCoordinator.unloadModel()
            activeModelID = nil
            await clearCloneState()
            await clearQwen3MemoryCachesIfNeeded()
            throw NativeRuntimeError.wrapping(
                error,
                stage: .prewarm,
                message: "The native runtime could not warm model '\(request.modelID)'"
            )
        }
    }

    /// Wait until no other prewarm body is running, then mark the slot
    /// taken. Pair with `releasePrewarmSlot()` — typically via `defer`
    /// at the top of the prewarm body.
    ///
    /// The actor mutex by itself isn't enough: prewarm bodies suspend
    /// while waiting on `model.prewarm*(...)` (which calls into MLX
    /// on a cooperative executor) and the actor is free to dispatch
    /// another message during that window. Without this gate, two
    /// callers can both end up inside MLX's KV cache slice updates and
    /// trip the C++-side assertion that crashed the bench cycle at
    /// sample #38 (Voice Design / Quality cold 3).
    /// Wait until no other prewarm body is running, then mark the slot
    /// taken. Returns the time (ms) spent queued behind an in-flight
    /// prewarm, or `0` when the slot was free immediately. Pair with
    /// `releasePrewarmSlot()` — typically via `defer` at the top of the
    /// prewarm body.
    private func acquirePrewarmSlot() async throws -> Int {
        try Task.checkCancellation()
        let waitStartedAt = ContinuousClock.now

        guard prewarmInFlight else {
            prewarmInFlight = true
            return 0
        }

        let waiterID = UUID()
        var slotAcquired = false
        do {
            try await withTaskCancellationHandler {
                try await withCheckedThrowingContinuation { (continuation: CheckedContinuation<Void, Error>) in
                    guard !Task.isCancelled else {
                        continuation.resume(throwing: CancellationError())
                        return
                    }
                    prewarmWaiters.append(PrewarmWaiter(id: waiterID, continuation: continuation))
                }
                // If we reach this point the continuation was resumed normally by
                // releasePrewarmSlot(), so the slot has been transferred to us.
                slotAcquired = true
            } onCancel: {
                Task { await self.cancelPrewarmWaiter(id: waiterID) }
            }
        } catch {
            // Only release the slot if it was actually transferred to us. If we
            // were cancelled while still queued, cancelPrewarmWaiter removed us
            // and the slot is still owned by the current prewarm body.
            if slotAcquired {
                releasePrewarmSlot()
            }
            throw error
        }

        try Task.checkCancellation()
        return waitStartedAt.elapsedMilliseconds
    }

    private func cancelPrewarmWaiter(id: UUID) {
        guard let index = prewarmWaiters.firstIndex(where: { $0.id == id }) else {
            return
        }
        let waiter = prewarmWaiters.remove(at: index)
        waiter.continuation.resume(throwing: CancellationError())
    }

    /// Release the prewarm slot and wake exactly one queued waiter. When a
    /// waiter is resumed, the slot remains logically held by that task so no
    /// second caller can enter MLX prewarm work during actor reentrancy.
    private func releasePrewarmSlot() {
        if prewarmWaiters.isEmpty {
            prewarmInFlight = false
        } else {
            let waiter = prewarmWaiters.removeFirst()
            prewarmInFlight = true
            waiter.continuation.resume()
        }
    }

    private func shouldSkipDedicatedCustomPrewarm(
        for request: GenerationRequest,
        model: UnsafeSpeechGenerationModel
    ) -> Bool {
        guard case .custom = request.payload else {
            return false
        }
        guard model.supportsDedicatedCustomVoice else {
            return false
        }
        return customPrewarmPolicy == .skipDedicatedCustomPrewarm
    }

    /// Picks a prewarm depth based on prompt length. The vendor's
    /// `Qwen3CustomVoicePrewarmDepth` enum has three options
    /// (`.full`, `.skipDecoderBucket`, `.skipStreamStep`) and accepts
    /// the raw string. `nil` resolves to `.full` (the default — used
    /// for medium / long prompts that benefit from the decoder bucket
    /// precompile being done up front).
    ///
    /// For short prompts (≤ shortPromptCharacterThreshold), return
    /// `"skip-decoder-bucket"` — the decoder will compile on first
    /// decode instead. Output is identical; only the latency
    /// distribution changes. Worth doing for short prompts because
    /// the prewarm cost matters more relative to the total generation
    /// time at that scale (warm-short bench cell has ~0.9 s of
    /// fixed overhead per the May 2026 baseline).
    ///
    /// Only Built-in Voice today; Voice Design and Voice Cloning use a
    /// different prewarm entry point that doesn't surface this depth
    /// parameter to the public API.
    private static func customPrewarmDepth(for request: GenerationRequest) -> String? {
        guard case .custom = request.payload else { return nil }
        let trimmed = request.text.trimmingCharacters(in: .whitespacesAndNewlines)
        if trimmed.count <= shortPromptCharacterThreshold {
            return "skip-decoder-bucket"
        }
        return nil
    }

    /// Roughly the warm-short bucket cutoff used in the bench
    /// runbooks. Prompts at or below this length are eligible for
    /// the lighter prewarm depth.
    private static let shortPromptCharacterThreshold = 30

    private var customPrewarmPolicyLabel: String {
        switch customPrewarmPolicy {
        case .eager:
            return "eager"
        case .skipDedicatedCustomPrewarm:
            return "skipDedicatedCustomPrewarm"
        }
    }

    private static func validateCloneConditioningCapability(
        for request: GenerationRequest,
        capabilities: Qwen3TTSModelCapabilities
    ) throws {
        guard case .clone(let reference) = request.payload else { return }
        try validateCloneConditioningCapability(
            reference: reference,
            capabilities: capabilities
        )
    }

    private static func validateCloneConditioningCapability(
        reference: CloneReference,
        capabilities: Qwen3TTSModelCapabilities
    ) throws {
        guard capabilities.supportsVoiceClone else {
            throw Qwen3TTSRuntimeProfileError.unsupportedCapability(
                "The selected model does not declare Voice Cloning support."
            )
        }
        let conditioningMode = NativePreparedCloneConditioningCache
            .anticipatedConditioningMode(for: reference)
        if conditioningMode.isXVectorOnly,
           !capabilities.supportsXVectorOnlyClone {
            throw Qwen3TTSRuntimeProfileError.unsupportedCapability(
                "The selected model does not declare audio-only x-vector clone conditioning support."
            )
        }
    }

    private func recordDiagnosticEvent(
        _ action: String,
        extra: [String: String]
    ) async {
        guard let diagnosticEventSink else {
            return
        }
        await diagnosticEventSink(action, extra)
    }

    private func recordDiagnosticEvent(
        _ action: String,
        request: GenerationRequest,
        capabilities: Qwen3TTSModelCapabilities,
        extra: [String: String] = [:]
    ) async {
        guard let diagnosticEventSink else {
            return
        }

        var details: [String: String] = [
            "mode": request.mode.rawValue,
            "modelID": request.modelID,
            "textLength": String(request.text.count),
        ]
        let prompt = GenerationSemantics.qwen3PromptAssembly(
            for: request,
            capabilities: capabilities
        )
        details["qwen3_prompt_mode"] = prompt.mode.rawValue
        details["qwen3_prompt_language"] = prompt.language
        details["qwen3_uses_instruction_control"] = prompt.usesInstructionControl ? "true" : "false"
        details["qwen3_clone_uses_transcript"] = prompt.cloneUsesTranscript ? "true" : "false"

        switch request.payload {
        case .custom(let speakerID, let deliveryStyle):
            details["speaker"] = speakerID
            if let deliveryStyle {
                details.merge(Self.privateTextMetadata(deliveryStyle, prefix: "deliveryStyle")) { _, rhs in rhs }
            }
        case .design(let voiceDescription, let deliveryStyle):
            details["voiceDescriptionLength"] = String(voiceDescription.count)
            if let deliveryStyle {
                details.merge(Self.privateTextMetadata(deliveryStyle, prefix: "deliveryStyle")) { _, rhs in rhs }
            }
        case .clone:
            break
        }

        details.merge(extra) { _, rhs in rhs }
        await diagnosticEventSink(action, details)
    }

    private static func privateTextMetadata(
        _ value: String,
        prefix: String
    ) -> [String: String] {
        let digest = SHA256.hash(data: Data(value.utf8))
            .map { String(format: "%02x", $0) }
            .joined()
        return [
            "\(prefix)Length": String(value.count),
            "\(prefix)Digest": digest,
        ]
    }

    private func primeCloneConditioning(
        model: UnsafeSpeechGenerationModel,
        conditioning: ResolvedCloneConditioning,
        language: String,
        token: UUID
    ) async throws -> [String: Int] {
        let startedAt = ContinuousClock.now
        guard let cloneHandle = conditioning.cloneHandle else {
            throw NativeRuntimeError(
                stage: .clonePreparation,
                message: "Clone priming needs optimized Qwen3 clone conditioning."
            )
        }
        // Priming warms the clone path with the exact same actor prewarm the
        // in-take warm path uses (`ensureWarmStateIfNeeded` → `prewarmVoiceClone`).
        // Phase 14a's bounded completion generation (`primeVoiceClone`) was
        // measured on iPhone spiking resident memory from ~2.0 GB to ~5.1 GB
        // during the warmup — enough to trip the memory-warning full unload of
        // the model it had just loaded — while the prewarm route stays within
        // the ordinary generation envelope (~300 ms, no spike).
        try ensureActiveClonePrimeToken(token)
        try await model.prewarmVoiceClone(
            text: lightweightWarmupText,
            language: language,
            cloneHandle: cloneHandle
        )
        try ensureActiveClonePrimeToken(token)
        await loadCoordinator.markPrewarmed(
            identityKey: GenerationSemantics.PrewarmIdentity.clone(
                conditioning.internalIdentity
            ).cacheKey
        )

        var timings = await model.latestPreparationTimingsMS()
        timings["prime_clone_reference"] = startedAt.elapsedMilliseconds
        return timings
    }

    private struct DesignConditioningWarmState: Sendable {
        let bucket: GenerationSemantics.DesignWarmBucket
        let requestKey: String
        let reused: Bool
        let prefetchHit: Bool
        let prewarmed: Bool
        let streamStepPrewarmed: Bool
        let streamStepPrefetchHit: Bool
        /// Time (ms) spent waiting for the serialized prewarm slot before
        /// any design-conditioning work ran. Captured here because this path
        /// is contended between prefetch and generation.
        let prewarmSlotWaitMS: Int
    }

    private func ensureDesignConditioningWarmStateIfNeeded(
        for request: GenerationRequest,
        model: UnsafeSpeechGenerationModel,
        source: DesignConditioningWarmSource
    ) async throws -> DesignConditioningWarmState {
        // Acquire the prewarm slot before any model state inspection.
        // Two paths reach this method concurrently
        // (`prefetchInteractiveReadinessIfNeeded` and
        // `prepareGeneration`) and without the slot they race on
        // MLX's KV cache during `model.prewarmVoiceDesign(...)`. After
        // we release, the second caller acquires and re-inspects
        // `activeDesignConditioningWarmIdentity` — which we'll have set
        // if we did real prewarm work — so the second caller takes
        // the cache-hit `reused` path instead of re-running prewarm.
        let prewarmSlotWaitMS = try await acquirePrewarmSlot()
        defer { releasePrewarmSlot() }
        try Task.checkCancellation()

        guard case .design(let voiceDescription, let deliveryStyle) = request.payload else {
            return DesignConditioningWarmState(
                bucket: .short,
                requestKey: "",
                reused: false,
                prefetchHit: false,
                prewarmed: false,
                streamStepPrewarmed: false,
                streamStepPrefetchHit: false,
                prewarmSlotWaitMS: prewarmSlotWaitMS
            )
        }

        let trimmedVoiceDescription = voiceDescription.trimmingCharacters(in: .whitespacesAndNewlines)
        let warmBucket = GenerationSemantics.designWarmBucket(for: request.text)
        guard !trimmedVoiceDescription.isEmpty else {
            return DesignConditioningWarmState(
                bucket: warmBucket,
                requestKey: "",
                reused: false,
                prefetchHit: false,
                prewarmed: false,
                streamStepPrewarmed: false,
                streamStepPrefetchHit: false,
                prewarmSlotWaitMS: prewarmSlotWaitMS
            )
        }

        let capabilities = try await loadCoordinator.qwen3Capabilities(for: request.modelID)
        let prompt = GenerationSemantics.qwen3PromptAssembly(
            for: request,
            capabilities: capabilities
        )
        let language = prompt.language
        guard let conditioningWarmIdentity = GenerationSemantics.designConditioningIdentity(for: request) else {
            return DesignConditioningWarmState(
                bucket: warmBucket,
                requestKey: "",
                reused: false,
                prefetchHit: false,
                prewarmed: false,
                streamStepPrewarmed: false,
                streamStepPrefetchHit: false,
                prewarmSlotWaitMS: prewarmSlotWaitMS
            )
        }
        let reused = activeDesignConditioningWarmIdentity == conditioningWarmIdentity
        if reused {
            // Cache hit — the active design conditioning matches what
            // this request needs. Emit a signpost so bench traces can
            // count hits vs misses, and skip the prewarm work below.
            let notes = BenchRunContext.telemetryNotes()
            let runID = notes["benchRunID"] ?? "not-bench"
            let takeIndex = notes["benchTakeIndex"] ?? "not-bench"
            let cell = notes["benchCell"] ?? "not-bench"
            let generationID = request.generationID?.uuidString ?? "not-generation"
            Self.signposter.emitEvent(
                "Native Design Conditioning Reuse",
                "runID=\(runID, privacy: .public) generationID=\(generationID, privacy: .public) takeIndex=\(takeIndex, privacy: .public) cell=\(cell, privacy: .public)"
            )
            await markDesignWarmSatisfied(
                for: request,
                conditioningWarmIdentity: conditioningWarmIdentity
            )
            return DesignConditioningWarmState(
                bucket: warmBucket,
                requestKey: conditioningWarmIdentity.cacheKey,
                reused: true,
                prefetchHit: activeDesignConditioningWarmSource == .prefetch,
                prewarmed: false,
                streamStepPrewarmed: false,
                streamStepPrefetchHit: activeDesignStreamStepWarmIdentity == conditioningWarmIdentity
                    && activeDesignStreamStepWarmSource == .prefetch,
                prewarmSlotWaitMS: prewarmSlotWaitMS
            )
        }

        // The incoming voice description doesn't match the active warm
        // key. Before re-prewarming for the new key, release the old
        // conditioning state explicitly so MLX can free its tensors.
        // Without this clear, the old design tensors stay resident
        // alongside the new ones during the prewarm window — peak RSS
        // briefly holds both. On `floor8GBMac` that overhead can push
        // the runtime into pressure. The actual MLX free still happens
        // when `clearCacheAfterGeneration` fires post-generation, but
        // *also* doing it here narrows the high-water window.
        if activeDesignConditioningWarmIdentity != nil {
            activeDesignConditioningWarmIdentity = nil
            activeDesignConditioningWarmSource = nil
            activeDesignStreamStepWarmIdentity = nil
            activeDesignStreamStepWarmSource = nil
            Memory.clearCache()
        }

        let warmText = GenerationSemantics.canonicalDesignWarmText(for: warmBucket)
        let warmInstruction = prompt.instruct
            ?? GenerationSemantics.designInstruction(
                voiceDescription: voiceDescription,
                emotion: deliveryStyle ?? ""
            )
        do {
            try await model.prewarmVoiceDesign(
                text: warmText,
                language: language,
                voiceDescription: warmInstruction
            )
            activeDesignConditioningWarmIdentity = conditioningWarmIdentity
            activeDesignConditioningWarmSource = source
            let streamStepPrewarmed = await model.latestPreparationBooleanFlags()["design_stream_step_prewarmed"] == true
            if streamStepPrewarmed {
                activeDesignStreamStepWarmIdentity = conditioningWarmIdentity
                activeDesignStreamStepWarmSource = source
            } else {
                activeDesignStreamStepWarmIdentity = nil
                activeDesignStreamStepWarmSource = nil
            }
            await markDesignWarmSatisfied(
                for: request,
                conditioningWarmIdentity: conditioningWarmIdentity
            )
            return DesignConditioningWarmState(
                bucket: warmBucket,
                requestKey: conditioningWarmIdentity.cacheKey,
                reused: false,
                prefetchHit: false,
                prewarmed: true,
                streamStepPrewarmed: streamStepPrewarmed,
                streamStepPrefetchHit: false,
                prewarmSlotWaitMS: prewarmSlotWaitMS
            )
        } catch {
            await loadCoordinator.unloadModel()
            activeModelID = nil
            await clearCloneState()
            await clearQwen3MemoryCachesIfNeeded()
            throw NativeRuntimeError.wrapping(
                error,
                stage: .prewarm,
                message: "The native runtime could not warm the design conditioning for '\(request.modelID)'"
            )
        }
    }

    private func markDesignWarmSatisfied(
        for request: GenerationRequest,
        conditioningWarmIdentity: GenerationSemantics.DesignConditioningIdentity
    ) async {
        await loadCoordinator.markPrewarmed(identityKey: conditioningWarmIdentity.cacheKey)
        if let identity = runtimePrewarmIdentity(for: request) {
            await loadCoordinator.markPrewarmed(identityKey: identity.cacheKey)
        }
    }

    private func runtimePrewarmIdentity(
        for request: GenerationRequest
    ) -> GenerationSemantics.PrewarmIdentity? {
        switch request.payload {
        case .custom:
            return GenerationSemantics.prewarmIdentity(
                modelID: request.modelID,
                mode: request.mode
            )
        case .design:
            return GenerationSemantics.prewarmIdentity(
                modelID: request.modelID,
                mode: request.mode
            )
        case .clone:
            return nil
        }
    }

    private func clearCloneState(
        preserveActiveClonePrimeToken: Bool = false
    ) async {
        await preparedCloneConditioningCache.clear()
        activeDesignConditioningWarmIdentity = nil
        activeDesignConditioningWarmSource = nil
        activeDesignStreamStepWarmIdentity = nil
        activeDesignStreamStepWarmSource = nil
        activeCloneConditioningIdentity = nil
        primedCloneReferenceKeys.removeAll()
        clonePrimeTimingOverridesMS.removeAll()
        if !preserveActiveClonePrimeToken {
            activeClonePrimeToken = nil
        }
    }

    private func clearQwen3MemoryCachesIfNeeded() async {
        // macOS intentionally preserves Qwen3 prepared/conditioning/decoder
        // cache warmth across unload, idle-unload, and trim so warm-after-idle
        // generations stay fast. Only iPhone clears these caches to stay under
        // the Jetsam ceiling. (The iOS-only model-switch path below the
        // `#if os(iOS)` guard clears explicitly and is unaffected by this.)
        guard NativeMemoryPolicyResolver.deviceClass() == .iPhonePro else { return }
        await VocelloQwen3Runtime.clearRuntimeCaches()
    }

    private func ensureActiveClonePrimeToken(_ token: UUID) throws {
        if Task.isCancelled || activeClonePrimeToken != token {
            throw CancellationError()
        }
    }

    private func requireNormalizedCloneReferenceDirectory() throws -> URL {
        guard let normalizedCloneReferenceDirectory else {
            throw MLXTTSEngineError.notInitialized
        }
        return normalizedCloneReferenceDirectory
    }

    private func takeNextRequestID() -> Int {
        defer { nextRequestID += 1 }
        return nextRequestID
    }

    /// Build the immutable generation plan in shadow mode from values already
    /// resolved by the shipping path. Failure is diagnostic-only: it never
    /// starts model work and cannot reject an otherwise valid generation.
    private static func recordGenerationPlanShadow(
        request: GenerationRequest,
        generationID: UUID,
        modelRuntimeIdentity: ModelRuntimeIdentity,
        qwen3Capabilities: Qwen3TTSModelCapabilities,
        memoryPolicy: NativeMemoryPolicy,
        samplingConfiguration: VocelloQwen3SamplingConfiguration,
        cloneConditioning: ResolvedCloneConditioning?,
        booleanFlags: inout [String: Bool],
        stringFlags: inout [String: String]
    ) {
        guard let repository = modelRuntimeIdentity.modelRepository,
              let revision = modelRuntimeIdentity.huggingFaceRevision,
              let artifactVersion = modelRuntimeIdentity.artifactVersion,
              let integrityDigest = modelRuntimeIdentity.integrityManifestDigest,
              let runtimeProfile = modelRuntimeIdentity.runtimeProfileSignature else {
            booleanFlags["generation_plan_shadow_match"] = false
            stringFlags["generation_plan_shadow_status"] = "unavailable_model_identity"
            return
        }

        let effectiveInterval = NativeMemoryPolicyResolver.effectiveStreamingInterval(
            requested: request.streamingInterval,
            request: request,
            policy: memoryPolicy
        )
        let talker = SamplingStage(
            temperature: Double(samplingConfiguration.talker.temperature),
            topP: Double(samplingConfiguration.talker.topP),
            topK: samplingConfiguration.talker.topK,
            minP: Double(samplingConfiguration.talker.minP)
        )
        let subtalker = SamplingStage(
            temperature: Double(samplingConfiguration.subtalker.temperature),
            topP: Double(samplingConfiguration.subtalker.topP),
            topK: samplingConfiguration.subtalker.topK,
            minP: Double(samplingConfiguration.subtalker.minP)
        )

        do {
            let talkerKVWindow = NativeMemoryPolicyResolver
                .resolvedTalkerKVGeneratedWindow()
            let chunkPolicy = StreamChunkPolicy.currentShippingDefault(
                for: request.mode,
                effectiveStreamingInterval: effectiveInterval
            )
            let samplingPolicy = Qwen3SamplingPolicy(
                algorithmVersion: samplingConfiguration.algorithmVersion,
                effectiveSeed: samplingConfiguration.effectiveSeed,
                talker: talker,
                subtalker: subtalker,
                repetitionPenalty: Double(samplingConfiguration.repetitionPenalty),
                maximumCodecTokens: samplingConfiguration.maxNewTokens
            )
            let outputPolicy = ProductOutputPlan(
                destinationPath: request.outputPath,
                shouldStream: request.shouldStream,
                batchIndex: request.batchIndex,
                batchTotal: request.batchTotal,
                publicationPolicyVersion: 1
            )
            let qualityPolicy = ProductQualityPolicy(
                reviewPolicyID: "fast",
                algorithmVersion: AudioQCReport.currentAlgorithmVersion
            )
            let shadowMemoryPolicy = RuntimeMemoryPolicy(
                tier: memoryPolicy.deviceClass,
                clearCacheOnStreamChunk: memoryPolicy.clearMLXCacheOnStreamChunkEmit,
                clearCacheAfterGeneration: memoryPolicy.clearCacheAfterGeneration,
                tokenMemoryClearCadence: memoryPolicy.mlxTokenMemoryClearCadence,
                talkerKVGeneratedWindow: talkerKVWindow,
                retentionPolicy: memoryPolicy.unloadAfterIdleSeconds == nil
                    ? .retainUntilPressure
                    : .retainUntilIdle
            )
            // Resolve the values used by the shipping runtime independently
            // from the shadow mapper. The mapper may evolve, but it cannot
            // validate itself by producing both sides of this comparison.
            let shippingPrompt = GenerationSemantics.qwen3PromptAssembly(
                for: request,
                capabilities: qwen3Capabilities,
                resolvedCloneTranscript: cloneConditioning?.resolvedTranscript
            )
            let shippingConditioning: CoreConditioningPlan
            switch request.payload {
            case .custom:
                guard let speakerID = shippingPrompt.speakerID else {
                    throw GenerationPlanShadowMappingError.missingResolvedConditioning(.custom)
                }
                shippingConditioning = .custom(
                    speakerID: speakerID,
                    deliveryInstruction: shippingPrompt.instruct
                )
            case .design:
                guard let instruction = shippingPrompt.instruct else {
                    throw GenerationPlanShadowMappingError.missingResolvedConditioning(.design)
                }
                shippingConditioning = .design(voiceDescription: instruction)
            case .clone:
                guard let digest = cloneConditioning?.internalIdentity.digest else {
                    throw GenerationPlanShadowMappingError.missingCloneConditioningDigest
                }
                shippingConditioning = .clone(conditioningDigest: digest)
            }
            let modelIdentity = CoreModelIdentity(
                modelID: modelRuntimeIdentity.resolvedModelID,
                repository: repository,
                revision: revision,
                artifactVersion: artifactVersion,
                integrityManifestDigest: integrityDigest,
                runtimeProfileSignature: runtimeProfile
            )
            let projection = try GenerationPlanShadowMapper.project(
                GenerationPlanShadowInputs(
                    request: request,
                    resolvedGenerationID: generationID,
                    modelIdentity: modelIdentity,
                    modelCapabilities: qwen3Capabilities,
                    nativeMemoryPolicy: memoryPolicy,
                    talkerKVGeneratedWindow: talkerKVWindow,
                    chunkPolicy: chunkPolicy,
                    samplingPolicy: samplingPolicy,
                    outputPolicy: outputPolicy,
                    qualityPolicy: qualityPolicy,
                    cloneConditioningDigest: cloneConditioning?.internalIdentity.digest,
                    resolvedCloneTranscript: cloneConditioning?.resolvedTranscript
                ),
                shipping: GenerationShippingResolutionSnapshot(
                    originalText: request.text,
                    spokenText: request.text,
                    generationID: generationID,
                    mode: request.mode,
                    modelFacingText: shippingPrompt.text,
                    language: shippingPrompt.language,
                    model: modelIdentity,
                    conditioning: shippingConditioning,
                    sampling: samplingPolicy,
                    chunking: chunkPolicy,
                    memory: shadowMemoryPolicy,
                    output: outputPolicy,
                    quality: qualityPolicy
                )
            )
            let identities = projection.plan.dependencyIdentities
            booleanFlags["generation_plan_shadow_match"] = projection.comparison.matches
            stringFlags["generation_plan_shadow_status"] = projection.comparison.matches
                ? "match"
                : "drift"
            stringFlags["generation_plan_shadow_drift_codes"] = projection.comparison
                .diagnosticCodes.joined(separator: ",")
            stringFlags["generation_plan_shadow_complete_digest"] = identities.complete
            stringFlags["generation_plan_shadow_sampling_digest"] = identities.sampling
            stringFlags["generation_plan_shadow_chunking_digest"] = identities.chunking
            stringFlags["generation_plan_shadow_memory_digest"] = identities.memory
            stringFlags["generation_plan_shadow_output_digest"] = identities.output
            stringFlags["generation_plan_shadow_quality_digest"] = identities.quality
            stringFlags["generation_plan_shadow_evidence_digest"] = try projection.plan
                .evidenceIdentity.canonicalDigest()
        } catch let error as GenerationPlanShadowMappingError {
            booleanFlags["generation_plan_shadow_match"] = false
            stringFlags["generation_plan_shadow_status"] = "mapping_error"
            switch error {
            case .missingCloneConditioningDigest:
                stringFlags["generation_plan_shadow_error_code"] = "missing_clone_digest"
            case .unexpectedCloneConditioningDigest:
                stringFlags["generation_plan_shadow_error_code"] = "unexpected_clone_digest"
            case .missingResolvedConditioning(let mode):
                stringFlags["generation_plan_shadow_error_code"] =
                    "missing_\(mode.rawValue)_conditioning"
            }
        } catch {
            booleanFlags["generation_plan_shadow_match"] = false
            stringFlags["generation_plan_shadow_status"] = "unavailable"
            stringFlags["generation_plan_shadow_error_code"] = "contract_validation"
        }
    }

}
