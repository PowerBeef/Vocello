import Foundation

public enum VocelloQwen3RuntimeOperationKind: String, Codable, Hashable, Sendable {
    case load
    case prewarm
    case generation
    case memoryRelief = "memory_relief"
    case unload
}

public enum VocelloQwen3OperationPhase: String, Codable, Hashable, Sendable {
    case unloaded
    case loading
    case ready
    case prewarming
    case reservedGeneration = "reserved_generation"
    case generating
    case awaitingProductFinalization = "awaiting_product_finalization"
    case relievingMemory = "relieving_memory"
    case unloading
    case failed
}

public struct VocelloQwen3RuntimeOperationLease: Codable, Hashable, Sendable {
    public let id: UUID
    public let kind: VocelloQwen3RuntimeOperationKind
    public let generationID: UUID?
    public let modelEpoch: UInt64

    fileprivate init(
        id: UUID = UUID(),
        kind: VocelloQwen3RuntimeOperationKind,
        generationID: UUID?,
        modelEpoch: UInt64
    ) {
        self.id = id
        self.kind = kind
        self.generationID = generationID
        self.modelEpoch = modelEpoch
    }
}

public enum VocelloQwen3MemoryPressureLevel: String, Codable, Hashable, Sendable {
    case normal
    case warning
    case critical
}

/// The amount of actor-owned runtime state released by a memory-relief pass.
public enum VocelloQwen3MemoryReliefAction: String, Codable, Hashable, Sendable {
    case cacheTrim = "cache_trim"
    case fullUnload = "full_unload"
}

public struct VocelloQwen3MemoryPressureSnapshot: Codable, Hashable, Sendable {
    public let level: VocelloQwen3MemoryPressureLevel
    public let sequence: UInt64
    public let admissionClosed: Bool

    public init(
        level: VocelloQwen3MemoryPressureLevel = .normal,
        sequence: UInt64 = 0,
        admissionClosed: Bool = false
    ) {
        self.level = level
        self.sequence = sequence
        self.admissionClosed = admissionClosed
    }
}

public struct VocelloQwen3EngineSnapshot: Codable, Hashable, Sendable {
    public let loadedModel: VocelloQwen3ModelIdentity?
    public let modelEpoch: UInt64
    public let phase: VocelloQwen3OperationPhase
    public let activeOperation: VocelloQwen3RuntimeOperationLease?
    public let pressure: VocelloQwen3MemoryPressureSnapshot

    public init(
        loadedModel: VocelloQwen3ModelIdentity?,
        modelEpoch: UInt64,
        phase: VocelloQwen3OperationPhase,
        activeOperation: VocelloQwen3RuntimeOperationLease?,
        pressure: VocelloQwen3MemoryPressureSnapshot
    ) {
        self.loadedModel = loadedModel
        self.modelEpoch = modelEpoch
        self.phase = phase
        self.activeOperation = activeOperation
        self.pressure = pressure
    }
}

/// Bounded local-diagnostics channel for prepared-model loading. Actions and
/// details are package-defined load-stage breadcrumbs and may contain local
/// filesystem paths; hosts must confine them to untracked local diagnostics
/// and never publish them in tracked artifacts, telemetry history, or logs
/// that leave the machine. Stable telemetry uses `VocelloQwen3DiagnosticSink`.
public typealias VocelloQwen3VerboseLoadDiagnosticSink =
    @Sendable (_ action: String, _ details: [String: String]) async -> Void

/// Immutable diagnostics snapshot exposed by the actor without granting model
/// access. Values mirror the owned runtime's load/preparation instrumentation.
public struct VocelloQwen3RuntimeDiagnosticsSnapshot: Sendable {
    public let timingsMilliseconds: [String: Int]
    public let booleanFlags: [String: Bool]
    public let stringFlags: [String: String]

    public init(
        timingsMilliseconds: [String: Int] = [:],
        booleanFlags: [String: Bool] = [:],
        stringFlags: [String: String] = [:]
    ) {
        self.timingsMilliseconds = timingsMilliseconds
        self.booleanFlags = booleanFlags
        self.stringFlags = stringFlags
    }

    init(_ diagnostics: VocelloQwen3CompatibilityDiagnostics) {
        self.timingsMilliseconds = diagnostics.timingsMilliseconds
        self.booleanFlags = diagnostics.booleanFlags
        self.stringFlags = diagnostics.stringFlags
    }
}

/// Post-load facts about the actor-owned model: identity, audio format, and
/// capability inventory plus the immutable load diagnostics. This is the
/// supported metadata surface; the loaded model itself never escapes the actor.
public struct VocelloQwen3LoadedModelFacts: Sendable {
    public let identity: VocelloQwen3ModelIdentity
    public let sampleRate: Int
    public let capabilities: VocelloQwen3CapabilitySet
    public let loadDiagnostics: VocelloQwen3RuntimeDiagnosticsSnapshot

    public init(
        identity: VocelloQwen3ModelIdentity,
        sampleRate: Int,
        capabilities: VocelloQwen3CapabilitySet,
        loadDiagnostics: VocelloQwen3RuntimeDiagnosticsSnapshot
    ) {
        self.identity = identity
        self.sampleRate = sampleRate
        self.capabilities = capabilities
        self.loadDiagnostics = loadDiagnostics
    }
}

/// Result of a bounded actor-owned priming generation. Audio is discarded
/// inside the actor; only counts cross the boundary.
public struct VocelloQwen3PrimeResult: Sendable {
    public let audioFrameCount: Int
    public let sampleRate: Int

    public init(audioFrameCount: Int, sampleRate: Int) {
        self.audioFrameCount = audioFrameCount
        self.sampleRate = sampleRate
    }
}

public enum VocelloQwen3EngineError: Error, Equatable, Sendable {
    case operationInProgress(VocelloQwen3RuntimeOperationKind)
    case noLoadedModel
    case staleOperation
    case invalidReservation
    case reservationAlreadyOpen
    case audioConsumerNotClaimed
    case modelHasNotTerminated
    case admissionClosedForMemoryRelief
    case finalizationAlreadyReleased
    case invalidCloneHandle
    case invalidConditioningDigest
    case cloneConditioningIdentityMismatch
}

public enum VocelloQwen3CloneHandleCapability: String, Codable, Hashable, Sendable {
    case decoderOnly = "decoder_only"
    case encoderAndDecoder = "encoder_and_decoder"
}

/// Epoch-bound identity for actor-owned clone conditioning.
///
/// The handle intentionally exposes no tensor storage and is never a portable
/// artifact identifier. Loading another model or unloading this engine
/// invalidates it even when a caller retains the value.
public struct VocelloQwen3CloneHandle: Hashable, Sendable {
    fileprivate let id: UUID
    public let model: VocelloQwen3ModelIdentity
    public let modelEpoch: UInt64
    public let capability: VocelloQwen3CloneHandleCapability
    public let conditioningDigest: String

    fileprivate init(
        id: UUID = UUID(),
        model: VocelloQwen3ModelIdentity,
        modelEpoch: UInt64,
        capability: VocelloQwen3CloneHandleCapability,
        conditioningDigest: String
    ) {
        self.id = id
        self.model = model
        self.modelEpoch = modelEpoch
        self.capability = capability
        self.conditioningDigest = conditioningDigest
    }
}

public struct VocelloQwen3GenerationReservation: Sendable {
    public let id: UUID
    public let lease: VocelloQwen3RuntimeOperationLease
    public let session: VocelloQwen3ClassifiedGenerationSession
    public let executionStyle: VocelloQwen3ExecutionStyle

    fileprivate init(
        id: UUID,
        lease: VocelloQwen3RuntimeOperationLease,
        session: VocelloQwen3ClassifiedGenerationSession,
        executionStyle: VocelloQwen3ExecutionStyle
    ) {
        self.id = id
        self.lease = lease
        self.session = session
        self.executionStyle = executionStyle
    }
}

/// The converged owner for all public MLX-mutating runtime operations.
///
/// All shipping generation modes reserve and execute through this actor. The
/// temporary compatibility adoption seam reuses the product's already-loaded
/// model while load/prewarm/trim ownership finishes converging; it never runs
/// a shadow generation or loads a second weight set. The inner Qwen generation
/// gate remains active as defense-in-depth during that migration.
public actor VocelloQwen3Engine {
    private enum GenerationLifecycle: Sendable, Equatable {
        case reserved
        case generating
        case aborting
    }

    private struct CloneRecord {
        let handle: VocelloQwen3CloneHandle
        let prompt: VocelloQwen3ClonePrompt
    }

    private struct PendingGeneration {
        let reservationID: UUID
        let lease: VocelloQwen3RuntimeOperationLease
        let request: VocelloQwen3SynthesisRequest
        let clonePrompt: VocelloQwen3ClonePrompt?
        /// Privacy-safe binding between the product request and the actor-owned
        /// prompt. This is the conditioning digest, never transcript/audio.
        let cloneConditioningDigest: String?
        let audioCapacityFrames: Int
        let session: VocelloQwen3ClassifiedGenerationSession
        let abortCompletion = VocelloQwen3AbortCompletionBarrier()
        var lifecycle: GenerationLifecycle = .reserved
        var finalizationReliefAction: VocelloQwen3MemoryReliefAction?
        var task: Task<Void, Never>?
        var generatedTokenCount = 0
        var emittedAudioFrameCount = 0
        var nextAudioSequence = 0
        var pendingChunkTimings: VocelloQwen3ChunkTimings?
        var generationInfo: VocelloQwen3GenerationInfo?
        var firstModelTokenAndAudioCodeMS: Int?
        var firstDecodedAudioFrameMS: Int?
    }

    private struct LastFinalization {
        let generationID: UUID
        let leaseID: UUID
        let token: VocelloQwen3ProductFinalizationToken
        let disposition: VocelloQwen3ProductFinalizationDisposition
        let completedReliefAction: VocelloQwen3MemoryReliefAction?
    }

    private var loadedModel: VocelloQwen3LoadedModel?
    private var modelEpoch: UInt64 = 0
    private var phase: VocelloQwen3OperationPhase = .unloaded
    private var activeOperation: VocelloQwen3RuntimeOperationLease?
    private var pendingGeneration: PendingGeneration?
    private var lastFinalization: LastFinalization?
    private var pressure = VocelloQwen3MemoryPressureSnapshot()
    private var cloneRecords: [UUID: CloneRecord] = [:]
    private var cloneRecordUseOrder: [UUID] = []
    private let cloneHandleCapacity: Int
    private let abortLifecycleHook: @Sendable (VocelloQwen3EngineAbortHookEvent) async -> Void
    private let memoryReliefHook: @Sendable (VocelloQwen3MemoryReliefAction) async -> Void
    private let finalizationReliefClaimHook: @Sendable () async -> Void
    private let finalizationReliefRollbackHook: @Sendable () async -> Void

    public init() {
        cloneHandleCapacity = 1
        abortLifecycleHook = { _ in }
        memoryReliefHook = { _ in }
        finalizationReliefClaimHook = {}
        finalizationReliefRollbackHook = {}
    }

    public init(cloneHandleCapacity: Int) {
        self.cloneHandleCapacity = max(1, cloneHandleCapacity)
        abortLifecycleHook = { _ in }
        memoryReliefHook = { _ in }
        finalizationReliefClaimHook = {}
        finalizationReliefRollbackHook = {}
    }

    /// Transitional shipping seam for the Phase 4 mode cutover. The actor
    /// adopts the exact already-loaded model instance so product integration
    /// cannot double-load weights. The SPI disappears when loading itself is
    /// fully actor-owned.
    init(adoptingCompatibilityModel loadedModel: VocelloQwen3LoadedModel) {
        self.loadedModel = loadedModel
        modelEpoch = 1
        cloneHandleCapacity = 1
        abortLifecycleHook = { _ in }
        memoryReliefHook = { _ in }
        finalizationReliefClaimHook = {}
        finalizationReliefRollbackHook = {}
        phase = .ready
    }

    /// Deterministic package-test seam. Production always starts unloaded and
    /// reaches this state through `load(_:behavior:cachePolicy:)`.
    init(
        loadedModel: VocelloQwen3LoadedModel,
        modelEpoch: UInt64 = 1,
        cloneHandleCapacity: Int = 1,
        abortLifecycleHook: @escaping @Sendable (
            VocelloQwen3EngineAbortHookEvent
        ) async -> Void = { _ in },
        memoryReliefHook: @escaping @Sendable (
            VocelloQwen3MemoryReliefAction
        ) async -> Void = { _ in },
        finalizationReliefClaimHook: @escaping @Sendable () async -> Void = {},
        finalizationReliefRollbackHook: @escaping @Sendable () async -> Void = {}
    ) {
        self.loadedModel = loadedModel
        self.modelEpoch = modelEpoch
        self.cloneHandleCapacity = max(1, cloneHandleCapacity)
        self.abortLifecycleHook = abortLifecycleHook
        self.memoryReliefHook = memoryReliefHook
        self.finalizationReliefClaimHook = finalizationReliefClaimHook
        self.finalizationReliefRollbackHook = finalizationReliefRollbackHook
        phase = .ready
    }

    public func snapshot() -> VocelloQwen3EngineSnapshot {
        VocelloQwen3EngineSnapshot(
            loadedModel: loadedModel?.identity,
            modelEpoch: modelEpoch,
            phase: phase,
            activeOperation: activeOperation,
            pressure: pressure
        )
    }

    /// Records pressure ingress without exposing an admission-reopen switch.
    /// Critical pressure is monotonic until this actor completes the matching
    /// relief operation; warning/normal observations cannot reopen it.
    /// Post-load metadata for the actor-owned model, or `nil` when unloaded.
    public func loadedModelFacts() -> VocelloQwen3LoadedModelFacts? {
        guard let model = loadedModel else { return nil }
        return VocelloQwen3LoadedModelFacts(
            identity: model.identity,
            sampleRate: model.sampleRate,
            capabilities: model.capabilities,
            loadDiagnostics: VocelloQwen3RuntimeDiagnosticsSnapshot(model.loadDiagnostics)
        )
    }

    /// Latest prewarm/prime instrumentation from the owned runtime, or `nil`
    /// when no model is loaded.
    public func preparationDiagnostics() -> VocelloQwen3RuntimeDiagnosticsSnapshot? {
        guard let model = loadedModel else { return nil }
        return VocelloQwen3RuntimeDiagnosticsSnapshot(model.latestPreparationDiagnostics)
    }

    /// Clears the owned runtime's preparation instrumentation so a following
    /// prewarm/prime window reports only its own work.
    public func resetPreparationDiagnostics() {
        loadedModel?.resetPreparationDiagnostics()
    }

    public func observeMemoryPressure(_ level: VocelloQwen3MemoryPressureLevel) {
        if pressure.admissionClosed, level != .critical {
            return
        }
        let closesAdmission = pressure.admissionClosed || level == .critical
        pressure = VocelloQwen3MemoryPressureSnapshot(
            level: level,
            sequence: pressure.sequence &+ 1,
            admissionClosed: closesAdmission
        )
        if level == .critical, let pendingGeneration {
            pendingGeneration.session.cancellation.request(.memoryPressure)
        }
    }

    @discardableResult
    public func load(
        _ bundle: VocelloQwen3PreparedModelBundle,
        behavior: VocelloQwen3LoadBehavior? = nil,
        cachePolicy: VocelloQwen3CachePolicy = .systemDefault,
        diagnosticSink: VocelloQwen3DiagnosticSink? = nil,
        verboseDiagnosticSink: VocelloQwen3VerboseLoadDiagnosticSink? = nil
    ) async throws -> VocelloQwen3ModelIdentity {
        let lease = try beginOperation(kind: .load, generationID: nil, phase: .loading)
        do {
            let model = try await VocelloQwen3Runtime.loadPreparedModel(
                bundle,
                loadBehavior: behavior,
                cachePolicy: cachePolicy,
                diagnosticSink: diagnosticSink,
                verboseDiagnosticSink: verboseDiagnosticSink,
                isolation: self
            )
            try revalidate(lease)
            // Once the loader has returned, the multi-second load is complete
            // and committing it is the only non-wasteful outcome. A late task
            // cancellation (for example a SwiftUI priming task restarted by an
            // identity change mid-load) must not discard the finished model;
            // cancellation before or during the load still aborts through the
            // loader's own cooperative checkpoints, and cancelled callers
            // observe cancellation at their next checkpoint with the model
            // committed. Only the lease revalidation above may veto commit.
            loadedModel = model
            modelEpoch &+= 1
            invalidateCloneHandles()
            activeOperation = nil
            phase = .ready
            return model.identity
        } catch {
            failOperationIfCurrent(lease)
            throw error
        }
    }

    /// Builds clone conditioning inside the actor and returns only an
    /// epoch-bound opaque handle to product code.
    public func makeCloneHandle(
        referenceSamples: [Float],
        referenceText: String?,
        xVectorOnlyMode: Bool,
        conditioningDigest: String
    ) throws -> VocelloQwen3CloneHandle {
        guard let model = loadedModel else {
            throw VocelloQwen3EngineError.noLoadedModel
        }
        guard model.capabilities.contains(.voiceClone) else {
            throw VocelloQwen3ContractError.unsupportedMode(.voiceClone)
        }
        guard !conditioningDigest.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
            throw VocelloQwen3EngineError.invalidConditioningDigest
        }
        let lease = try beginOperation(
            kind: .prewarm,
            generationID: nil,
            phase: .prewarming
        )
        do {
            try Task.checkCancellation()
            let prompt = try model.makeClonePrompt(
                referenceSamples: referenceSamples,
                referenceText: referenceText,
                xVectorOnlyMode: xVectorOnlyMode
            )
            guard prompt.xVectorOnlyMode == xVectorOnlyMode,
                  prompt.inContextLearningMode == !xVectorOnlyMode else {
                throw VocelloQwen3EngineError.cloneConditioningIdentityMismatch
            }
            try revalidate(lease)
            try Task.checkCancellation()
            let handle = VocelloQwen3CloneHandle(
                model: model.identity,
                modelEpoch: modelEpoch,
                capability: xVectorOnlyMode ? .decoderOnly : .encoderAndDecoder,
                conditioningDigest: conditioningDigest
            )
            insertCloneRecord(CloneRecord(handle: handle, prompt: prompt))
            activeOperation = nil
            phase = .ready
            return handle
        } catch {
            failOperationIfCurrent(lease)
            throw error
        }
    }

    /// Adopts a prompt already validated by the schema-3 artifact reader. The
    /// compatibility bridge exposes only an epoch-bound handle; prompt tensors
    /// remain actor-owned and cannot be serialized through the handle.
    func adoptValidatedClonePrompt(
        _ prompt: VocelloQwen3ClonePrompt,
        capability: VocelloQwen3CloneHandleCapability,
        conditioningDigest: String
    ) throws -> VocelloQwen3CloneHandle {
        guard let model = loadedModel else {
            throw VocelloQwen3EngineError.noLoadedModel
        }
        guard model.capabilities.contains(.voiceClone) else {
            throw VocelloQwen3ContractError.unsupportedMode(.voiceClone)
        }
        let expectedCapability: VocelloQwen3CloneHandleCapability =
            prompt.xVectorOnlyMode ? .decoderOnly : .encoderAndDecoder
        guard capability == expectedCapability else {
            throw VocelloQwen3EngineError.invalidCloneHandle
        }
        let digest = conditioningDigest.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !digest.isEmpty else {
            throw VocelloQwen3EngineError.invalidConditioningDigest
        }
        if let metadata = prompt.artifactMetadata {
            guard metadata.modelID == nil || metadata.modelID == model.identity.modelID,
                  metadata.modelRepository == nil
                    || metadata.modelRepository == model.identity.repositoryID,
                  metadata.modelRevision == nil
                    || metadata.modelRevision == model.identity.revision,
                  metadata.modelArtifactVersion == nil
                    || metadata.modelArtifactVersion == model.identity.artifactVersion,
                  metadata.xVectorOnlyMode == nil
                    || metadata.xVectorOnlyMode == prompt.xVectorOnlyMode else {
                throw VocelloQwen3EngineError.invalidCloneHandle
            }
        }
        let handle = VocelloQwen3CloneHandle(
            model: model.identity,
            modelEpoch: modelEpoch,
            capability: capability,
            conditioningDigest: digest
        )
        insertCloneRecord(CloneRecord(handle: handle, prompt: prompt))
        return handle
    }

    /// Releases an opaque conditioning handle without exposing its tensors.
    /// A prompt already retained by an active reservation remains valid for
    /// that reservation, while future lookups fail closed.
    @discardableResult
    public func releaseCloneHandle(_ handle: VocelloQwen3CloneHandle) -> Bool {
        guard handle.modelEpoch == modelEpoch,
              handle.model == loadedModel?.identity,
              cloneRecords[handle.id]?.handle == handle else {
            return false
        }
        cloneRecords.removeValue(forKey: handle.id)
        cloneRecordUseOrder.removeAll { $0 == handle.id }
        return true
    }

    /// Reports whether `handle` still resolves to an actor-held clone record
    /// for the current model epoch. Host-side handle caches use this to drop
    /// entries invalidated by reload, critical trim, or full unload.
    public func isCloneHandleValid(_ handle: VocelloQwen3CloneHandle) -> Bool {
        validCloneRecord(for: handle) != nil
    }

    /// Persists the actor-held clone conditioning for `handle` as a schema-3
    /// artifact. Prompt tensors are serialized directly from the actor's
    /// record; the caller never observes them.
    public func persistCloneArtifact(
        _ handle: VocelloQwen3CloneHandle,
        to directory: URL,
        metadata: VocelloQwen3CloneArtifactMetadata
    ) throws {
        guard let record = validCloneRecord(for: handle) else {
            throw VocelloQwen3EngineError.invalidCloneHandle
        }
        try record.prompt.withArtifactMetadata(metadata).writeAtomically(to: directory)
    }

    /// Loads and validates a persisted schema-3 clone artifact inside the
    /// actor and returns only an epoch-bound handle. This replaces host-side
    /// prompt loading: tensors never cross the actor boundary.
    public func adoptCloneArtifact(
        from directory: URL,
        expectedMetadata: VocelloQwen3CloneArtifactMetadata,
        conditioningDigest: String
    ) throws -> VocelloQwen3CloneHandle {
        let prompt = try VocelloQwen3ClonePrompt.load(
            from: directory,
            expectedMetadata: expectedMetadata
        )
        return try adoptValidatedClonePrompt(
            prompt,
            capability: prompt.xVectorOnlyMode ? .decoderOnly : .encoderAndDecoder,
            conditioningDigest: conditioningDigest
        )
    }

    /// Prepares the currently loaded model without exposing its mutable facade.
    public func prewarm(
        request: VocelloQwen3SynthesisRequest,
        cloneHandle: VocelloQwen3CloneHandle? = nil,
        customDepth: String? = nil
    ) async throws {
        guard let model = loadedModel else {
            throw VocelloQwen3EngineError.noLoadedModel
        }
        _ = try request.validated(for: model.capabilities)
        let lease = try beginOperation(kind: .prewarm, generationID: nil, phase: .prewarming)
        do {
            switch request.input {
            case .customVoice(let speakerID, let instruction):
                try await model.prewarmCustomVoice(
                    text: request.text,
                    language: request.language,
                    speaker: speakerID,
                    instruction: instruction,
                    sampling: request.sampling,
                    memory: request.memory,
                    depth: customDepth,
                    isolation: self
                )
            case .voiceDesign(let description):
                try await model.prewarmVoiceDesign(
                    text: request.text,
                    language: request.language,
                    description: description,
                    sampling: request.sampling,
                    memory: request.memory,
                    isolation: self
                )
            case .voiceClone:
                guard let cloneHandle,
                      let record = validCloneRecord(for: cloneHandle) else {
                    throw VocelloQwen3EngineError.invalidCloneHandle
                }
                try await model.prewarmVoiceClone(
                    text: request.text,
                    language: request.language,
                    prompt: record.prompt,
                    sampling: request.sampling,
                    memory: request.memory,
                    isolation: self
                )
            }
            try revalidate(lease)
            try Task.checkCancellation()
            activeOperation = nil
            phase = .ready
        } catch {
            failOperationIfCurrent(lease)
            throw error
        }
    }

    /// Runs one bounded actor-owned priming generation and discards the audio
    /// inside the actor. Hosts use this to warm conditioning paths beyond
    /// prewarm depth (for example first-generation Clone priming) without a
    /// model handle; only frame counts cross the boundary.
    public func prime(
        request: VocelloQwen3SynthesisRequest,
        cloneHandle: VocelloQwen3CloneHandle? = nil
    ) async throws -> VocelloQwen3PrimeResult {
        guard let model = loadedModel else {
            throw VocelloQwen3EngineError.noLoadedModel
        }
        _ = try request.validated(for: model.capabilities)
        let lease = try beginOperation(kind: .prewarm, generationID: nil, phase: .prewarming)
        do {
            let completion: VocelloQwen3GenerationCompletion
            switch request.input {
            case .customVoice(let speakerID, let instruction):
                completion = try await model.generateCustomVoice(
                    text: request.text,
                    language: request.language,
                    speaker: speakerID,
                    instruction: instruction,
                    sampling: request.sampling,
                    memory: request.memory
                )
            case .voiceDesign(let description):
                completion = try await model.generateVoiceDesign(
                    text: request.text,
                    language: request.language,
                    description: description,
                    sampling: request.sampling,
                    memory: request.memory
                )
            case .voiceClone:
                guard let cloneHandle,
                      let record = validCloneRecord(for: cloneHandle) else {
                    throw VocelloQwen3EngineError.invalidCloneHandle
                }
                completion = try await model.generateVoiceClone(
                    text: request.text,
                    language: request.language,
                    prompt: record.prompt,
                    sampling: request.sampling,
                    memory: request.memory
                )
            }
            try revalidate(lease)
            try Task.checkCancellation()
            activeOperation = nil
            phase = .ready
            return VocelloQwen3PrimeResult(
                audioFrameCount: completion.audio.count,
                sampleRate: model.sampleRate
            )
        } catch {
            failOperationIfCurrent(lease)
            throw error
        }
    }

    public func reserveGeneration(
        request: VocelloQwen3SynthesisRequest,
        cloneHandle: VocelloQwen3CloneHandle? = nil,
        audioCapacityFrames: Int,
        diagnosticCapacity: Int = 128
    ) async throws -> VocelloQwen3GenerationReservation {
        let prompt: VocelloQwen3ClonePrompt?
        let cloneConditioningDigest: String?
        if case .voiceClone(let referenceID) = request.input {
            guard let cloneHandle,
                  let record = validCloneRecord(for: cloneHandle) else {
                throw VocelloQwen3EngineError.invalidCloneHandle
            }
            try validateCloneConditioningIdentity(
                requestReferenceID: referenceID,
                conditioningDigest: record.handle.conditioningDigest
            )
            prompt = record.prompt
            cloneConditioningDigest = record.handle.conditioningDigest
        } else {
            prompt = nil
            cloneConditioningDigest = nil
        }
        return try await reserveGeneration(
            request: request,
            clonePrompt: prompt,
            cloneConditioningDigest: cloneConditioningDigest,
            audioCapacityFrames: audioCapacityFrames,
            diagnosticCapacity: diagnosticCapacity
        )
    }

    private func reserveGeneration(
        request: VocelloQwen3SynthesisRequest,
        clonePrompt: VocelloQwen3ClonePrompt? = nil,
        cloneConditioningDigest: String? = nil,
        audioCapacityFrames: Int,
        diagnosticCapacity: Int = 128
    ) async throws -> VocelloQwen3GenerationReservation {
        guard !pressure.admissionClosed else {
            throw VocelloQwen3EngineError.admissionClosedForMemoryRelief
        }
        guard let model = loadedModel else {
            throw VocelloQwen3EngineError.noLoadedModel
        }
        _ = try request.validated(for: model.capabilities)
        if case .voiceClone(let referenceID) = request.input {
            guard clonePrompt != nil else {
                throw VocelloQwen3ContractError.missingClonePrompt
            }
            guard let cloneConditioningDigest else {
                throw VocelloQwen3EngineError.cloneConditioningIdentityMismatch
            }
            try validateCloneConditioningIdentity(
                requestReferenceID: referenceID,
                conditioningDigest: cloneConditioningDigest
            )
        }

        let boundedAudioCapacityFrames = max(1, audioCapacityFrames)
        let lease = try beginOperation(
            kind: .generation,
            generationID: request.generationID,
            phase: .reservedGeneration
        )
        let reservationID = UUID()
        let session = VocelloQwen3ClassifiedGenerationSession(
            generationID: request.generationID,
            leaseID: lease.id,
            audioCapacityFrames: boundedAudioCapacityFrames,
            diagnosticCapacity: diagnosticCapacity
        )
        pendingGeneration = PendingGeneration(
            reservationID: reservationID,
            lease: lease,
            request: request,
            clonePrompt: clonePrompt,
            cloneConditioningDigest: cloneConditioningDigest,
            audioCapacityFrames: boundedAudioCapacityFrames,
            session: session
        )
        return VocelloQwen3GenerationReservation(
            id: reservationID,
            lease: lease,
            session: session,
            executionStyle: request.executionStyle
        )
    }

    /// Opens generation only after the product output adapter has claimed the
    /// session's mandatory audio consumer.
    public func open(_ reservationID: UUID) async throws {
        guard let pending = pendingGeneration,
              pending.reservationID == reservationID else {
            throw VocelloQwen3EngineError.invalidReservation
        }
        switch pending.lifecycle {
        case .reserved:
            break
        case .generating:
            throw VocelloQwen3EngineError.reservationAlreadyOpen
        case .aborting:
            throw VocelloQwen3EngineError.invalidReservation
        }
        guard await pending.session.hasClaimedAudioConsumer() else {
            throw VocelloQwen3EngineError.audioConsumerNotClaimed
        }

        // The consumer query suspends outside this actor. Re-fetch both the
        // reservation and its lifecycle before allowing model work to start.
        guard var current = pendingGeneration,
              current.reservationID == reservationID else {
            throw VocelloQwen3EngineError.invalidReservation
        }
        switch current.lifecycle {
        case .reserved:
            break
        case .generating:
            throw VocelloQwen3EngineError.reservationAlreadyOpen
        case .aborting:
            throw VocelloQwen3EngineError.invalidReservation
        }
        try revalidate(current.lease)
        guard !pressure.admissionClosed else {
            throw VocelloQwen3EngineError.admissionClosedForMemoryRelief
        }
        if case .voiceClone(let referenceID) = current.request.input {
            guard let cloneConditioningDigest = current.cloneConditioningDigest else {
                throw VocelloQwen3EngineError.cloneConditioningIdentityMismatch
            }
            try validateCloneConditioningIdentity(
                requestReferenceID: referenceID,
                conditioningDigest: cloneConditioningDigest
            )
        }

        current.lifecycle = .generating
        phase = .generating
        let task = Task { [self] in
            await runGeneration(reservationID: reservationID)
        }
        current.task = task
        current.session.cancellation.installCancelAction { task.cancel() }
        pendingGeneration = current
    }

    /// Aborts an inert reservation. No model task or preparation can have
    /// started because opened reservations use the normal cancellation path.
    /// A reason already recorded by critical-pressure ingress wins over a
    /// later host cleanup reason.
    public func abortReservation(
        _ reservationID: UUID,
        reason: VocelloQwen3CancellationReason = .shutdown
    ) async throws {
        guard var pending = pendingGeneration,
              pending.reservationID == reservationID else {
            throw VocelloQwen3EngineError.invalidReservation
        }
        switch pending.lifecycle {
        case .reserved:
            pending.lifecycle = .aborting
            pendingGeneration = pending
            phase = .awaitingProductFinalization
            await abortLifecycleHook(.owner)
            try revalidateAbortingReservation(pending)
        case .aborting:
            await abortLifecycleHook(.joiner)
            await pending.abortCompletion.wait()
            return
        case .generating:
            throw VocelloQwen3EngineError.invalidReservation
        }

        let effectiveReason: VocelloQwen3CancellationReason
        if let recordedReason = pending.session.cancellation.reason {
            effectiveReason = recordedReason
        } else {
            pending.session.cancellation.request(reason)
            effectiveReason = pending.session.cancellation.reason ?? reason
        }
        let terminal = VocelloQwen3TerminalEvent(
            generationID: pending.request.generationID,
            outcome: .cancelled(effectiveReason),
            generatedTokenCount: 0,
            emittedAudioFrameCount: 0,
            elapsedMilliseconds: 0
        )
        await pending.session.cancelModelTerminal(terminal, reason: effectiveReason)
        try revalidateAbortingReservation(pending)
        _ = try await pending.session.acknowledgeProductFinalization(
            generationID: pending.request.generationID,
            leaseID: pending.lease.id,
            token: pending.session.finalizationToken,
            disposition: .aborted(.runtime)
        )
        guard let current = pendingGeneration,
              current.reservationID == pending.reservationID,
              current.lifecycle == .aborting,
              activeOperation == pending.lease else {
            _ = try acknowledgeAgainstLastFinalization(
                generationID: pending.request.generationID,
                leaseID: pending.lease.id,
                token: pending.session.finalizationToken,
                disposition: .aborted(.runtime)
            )
            return
        }
        await releaseGeneration(current, disposition: .aborted(.runtime))
    }

    /// Cancels either lifecycle state. An inert reservation is finalized and
    /// released synchronously; an opened producer receives the first reason
    /// through the lock-backed controller and completes its normal barrier.
    public func cancelGeneration(
        _ reservationID: UUID,
        reason: VocelloQwen3CancellationReason
    ) async throws {
        guard let pending = pendingGeneration,
              pending.reservationID == reservationID else {
            throw VocelloQwen3EngineError.invalidReservation
        }
        switch pending.lifecycle {
        case .reserved, .aborting:
            try await abortReservation(reservationID, reason: reason)
        case .generating:
            pending.session.cancellation.request(reason)
        }
    }

    public func acknowledgeProductFinalization(
        generationID: UUID,
        leaseID: UUID,
        token: VocelloQwen3ProductFinalizationToken,
        disposition: VocelloQwen3ProductFinalizationDisposition
    ) async throws -> VocelloQwen3FinalizationAcknowledgeResult {
        guard let pending = pendingGeneration else {
            return try acknowledgeAgainstLastFinalization(
                generationID: generationID,
                leaseID: leaseID,
                token: token,
                disposition: disposition
            )
        }
        guard phase == .awaitingProductFinalization else {
            throw VocelloQwen3EngineError.modelHasNotTerminated
        }
        guard pending.lifecycle != .aborting else {
            throw VocelloQwen3EngineError.modelHasNotTerminated
        }
        try revalidate(pending.lease)
        let result = try await pending.session.acknowledgeProductFinalization(
            generationID: generationID,
            leaseID: leaseID,
            token: token,
            disposition: disposition
        )

        guard let current = pendingGeneration,
              current.reservationID == pending.reservationID,
              activeOperation == pending.lease else {
            return try acknowledgeAgainstLastFinalization(
                generationID: generationID,
                leaseID: leaseID,
                token: token,
                disposition: disposition
            )
        }
        // A concurrent atomic-relief acknowledgement owns the generation
        // lease transfer. This acknowledgement may validate the same product
        // result, but must not release that lease in between finalization and
        // cache/model relief.
        if current.finalizationReliefAction != nil {
            return result
        }
        await releaseGeneration(current, disposition: disposition)
        return result
    }

    /// Atomically converts the completed generation lease into the critical
    /// relief lease. Admission remains closed throughout; no newer operation
    /// can appear between product cleanup and cache release.
    public func acknowledgeProductFinalizationAndRelieveMemory(
        generationID: UUID,
        leaseID: UUID,
        token: VocelloQwen3ProductFinalizationToken,
        disposition: VocelloQwen3ProductFinalizationDisposition
    ) async throws -> VocelloQwen3FinalizationAcknowledgeResult {
        try await acknowledgeProductFinalizationAndRelieveMemory(
            generationID: generationID,
            leaseID: leaseID,
            token: token,
            disposition: disposition,
            action: .cacheTrim
        )
    }

    /// Acknowledges product finalization and transfers the existing generation
    /// lease directly into the selected relief action. No admission window is
    /// opened between product cleanup and cache trim or full model unload.
    public func acknowledgeProductFinalizationAndRelieveMemory(
        generationID: UUID,
        leaseID: UUID,
        token: VocelloQwen3ProductFinalizationToken,
        disposition: VocelloQwen3ProductFinalizationDisposition,
        action: VocelloQwen3MemoryReliefAction
    ) async throws -> VocelloQwen3FinalizationAcknowledgeResult {
        guard var pending = pendingGeneration else {
            if activeOperation?.kind == .memoryRelief {
                throw VocelloQwen3EngineError.operationInProgress(.memoryRelief)
            }
            let result = try acknowledgeAgainstLastFinalization(
                generationID: generationID,
                leaseID: leaseID,
                token: token,
                disposition: disposition
            )
            guard lastFinalization?.completedReliefAction == action else {
                throw VocelloQwen3EngineError.finalizationAlreadyReleased
            }
            return result
        }
        guard phase == .awaitingProductFinalization else {
            throw VocelloQwen3EngineError.modelHasNotTerminated
        }
        guard pending.lifecycle != .aborting else {
            throw VocelloQwen3EngineError.modelHasNotTerminated
        }
        try revalidate(pending.lease)
        if pending.finalizationReliefAction != nil {
            throw VocelloQwen3EngineError.operationInProgress(.memoryRelief)
        }
        pending.finalizationReliefAction = action
        pendingGeneration = pending
        await finalizationReliefClaimHook()
        let result: VocelloQwen3FinalizationAcknowledgeResult
        do {
            result = try await pending.session.acknowledgeProductFinalization(
                generationID: generationID,
                leaseID: leaseID,
                token: token,
                disposition: disposition
            )
        } catch {
            // Claiming relief happens before the acknowledgement suspension so
            // no concurrent finalizer can release this generation lease. A
            // rejected identity or disposition must relinquish only that same
            // claim; otherwise one bad acknowledgement would permanently
            // strand the actor in awaiting-product-finalization.
            var clearedClaim = false
            if var current = pendingGeneration,
               current.reservationID == pending.reservationID,
               current.finalizationReliefAction == action,
               activeOperation == pending.lease {
                // Clear this exact claim before crossing another actor. An
                // ordinary finalizer arriving after this point now owns its
                // normal release path instead of observing stale relief
                // ownership and returning early.
                current.finalizationReliefAction = nil
                pendingGeneration = current
                clearedClaim = true
            }
            if clearedClaim {
                await finalizationReliefRollbackHook()
            }
            let acceptedDisposition = await pending.session
                .acceptedProductFinalizationDisposition()
            if let acceptedDisposition,
               let current = pendingGeneration,
               current.reservationID == pending.reservationID,
               current.finalizationReliefAction == nil,
               activeOperation == pending.lease {
                // A valid finalizer may already have crossed the session
                // barrier while this rejected claim was visible. If it did,
                // finish that accepted acknowledgement unless another atomic
                // claimant has since taken ownership.
                await releaseGeneration(
                    current,
                    disposition: acceptedDisposition
                )
            }
            throw error
        }
        guard let current = pendingGeneration,
              current.reservationID == pending.reservationID,
              current.finalizationReliefAction == action,
              activeOperation == pending.lease else {
            return try acknowledgeAgainstLastFinalization(
                generationID: generationID,
                leaseID: leaseID,
                token: token,
                disposition: disposition
            )
        }
        try revalidate(current.lease)

        lastFinalization = LastFinalization(
            generationID: generationID,
            leaseID: leaseID,
            token: token,
            disposition: disposition,
            completedReliefAction: nil
        )
        let reliefLease = VocelloQwen3RuntimeOperationLease(
            id: pending.lease.id,
            kind: .memoryRelief,
            generationID: nil,
            modelEpoch: pending.lease.modelEpoch
        )
        pendingGeneration = nil
        activeOperation = reliefLease
        phase = .relievingMemory
        do {
            try await performMemoryRelief(action, lease: reliefLease)
            lastFinalization = LastFinalization(
                generationID: generationID,
                leaseID: leaseID,
                token: token,
                disposition: disposition,
                completedReliefAction: action
            )
            return result
        } catch {
            failOperationIfCurrent(reliefLease)
            throw error
        }
    }

    /// Clears prepared and decoder caches only when no product operation owns
    /// the runtime. Critical-pressure continuity is coordinated by the product
    /// gate until its cutover to this actor.
    public func relieveMemory() async throws {
        try await relieveMemory(.cacheTrim)
    }

    /// Performs a typed standalone relief action. Both actions are admitted
    /// while critical pressure is closed and reopen admission only after the
    /// selected release has completed.
    public func relieveMemory(_ action: VocelloQwen3MemoryReliefAction) async throws {
        let lease = try beginOperation(
            kind: .memoryRelief,
            generationID: nil,
            phase: .relievingMemory,
            permitsClosedAdmission: true
        )
        do {
            try await performMemoryRelief(action, lease: lease)
        } catch {
            failOperationIfCurrent(lease)
            throw error
        }
    }

    public func unload() async throws {
        let lease = try beginOperation(
            kind: .unload,
            generationID: nil,
            phase: .unloading,
            permitsClosedAdmission: true
        )
        do {
            try await performMemoryRelief(.fullUnload, lease: lease)
        } catch {
            failOperationIfCurrent(lease)
            throw error
        }
    }

    private func runGeneration(reservationID: UUID) async {
        guard let pending = pendingGeneration,
              pending.reservationID == reservationID,
              pending.lifecycle == .generating,
              let model = loadedModel else {
            return
        }

        let startedAt = ContinuousClock.now
        do {
            try revalidate(pending.lease)
            try pending.session.cancellation.checkCancellation()

            let sink: @Sendable (VocelloQwen3GenerationSignal) async throws -> Void = {
                [self] signal in
                try await consumeGenerationSignal(
                    signal,
                    reservationID: reservationID,
                    modelIdentity: model.identity,
                    sampleRate: model.sampleRate,
                    startedAt: startedAt
                )
            }
            let finishReason: VocelloQwen3GenerationFinishReason
            switch pending.request.executionStyle {
            case .streaming:
                finishReason = try await model.produce(
                    request: pending.request,
                    clonePrompt: pending.clonePrompt,
                    sink: sink,
                    isolation: self
                )
            case .qualityFirst:
                finishReason = try await model.produceQualityFirst(
                    request: pending.request,
                    clonePrompt: pending.clonePrompt,
                    sink: sink,
                    isolation: self
                )
            }
            try revalidate(pending.lease)
            guard let completed = pendingGeneration,
                  completed.reservationID == reservationID else {
                throw VocelloQwen3EngineError.staleOperation
            }
            let outcome: VocelloQwen3TerminalOutcome
            if let cancellationReason = pending.session.cancellation.reason {
                outcome = .cancelled(cancellationReason)
            } else {
                switch finishReason {
                case .endOfSequence:
                    guard completed.emittedAudioFrameCount > 0 else {
                        throw VocelloQwen3EngineRuntimeFailure()
                    }
                    outcome = .completed(.endOfSequence)
                case .maximumTokens:
                    guard completed.emittedAudioFrameCount > 0 else {
                        throw VocelloQwen3EngineRuntimeFailure()
                    }
                    outcome = .completed(.maximumTokens)
                case .cancelled:
                    pending.session.cancellation.request(.user)
                    outcome = .cancelled(pending.session.cancellation.reason ?? .user)
                case .failed:
                    outcome = .failed(.runtime)
                }
            }
            let terminal = VocelloQwen3TerminalEvent(
                generationID: pending.request.generationID,
                outcome: outcome,
                generatedTokenCount: completed.generatedTokenCount,
                emittedAudioFrameCount: completed.emittedAudioFrameCount,
                elapsedMilliseconds: startedAt.elapsedMilliseconds,
                generationInfo: completed.generationInfo,
                diagnostics: model.finalizedGenerationDiagnostics
            )
            try revalidate(pending.lease)
            phase = .awaitingProductFinalization
            switch outcome {
            case .completed:
                await pending.session.resolveModelTerminal(terminal)
            case .cancelled(let reason):
                await pending.session.cancelModelTerminal(terminal, reason: reason)
            case .failed:
                await pending.session.failModelTerminal(
                    terminal,
                    error: VocelloQwen3EngineRuntimeFailure()
                )
            }
        } catch {
            guard activeOperation == pending.lease else { return }
            let current = pendingGeneration?.reservationID == reservationID
                ? pendingGeneration
                : nil
            let tokenCount = current?.generatedTokenCount ?? 0
            let frameCount = current?.emittedAudioFrameCount ?? 0
            // Publish the phase before resolving the model terminal. Terminal
            // resolution resumes the product adapter and therefore creates an
            // actor-reentrancy point where finalization may be acknowledged.
            // A fast adapter must never observe a completed model while the
            // engine still claims to be generating.
            phase = .awaitingProductFinalization
            if pending.session.cancellation.isCancelled || error is CancellationError {
                let reason = pending.session.cancellation.reason ?? .user
                let terminal = VocelloQwen3TerminalEvent(
                    generationID: pending.request.generationID,
                    outcome: .cancelled(reason),
                    generatedTokenCount: tokenCount,
                    emittedAudioFrameCount: frameCount,
                    elapsedMilliseconds: startedAt.elapsedMilliseconds,
                    generationInfo: current?.generationInfo,
                    diagnostics: model.finalizedGenerationDiagnostics
                )
                await pending.session.cancelModelTerminal(terminal, reason: reason)
            } else {
                let terminal = VocelloQwen3TerminalEvent(
                    generationID: pending.request.generationID,
                    outcome: .failed(.runtime),
                    generatedTokenCount: tokenCount,
                    emittedAudioFrameCount: frameCount,
                    elapsedMilliseconds: startedAt.elapsedMilliseconds,
                    generationInfo: current?.generationInfo,
                    diagnostics: model.finalizedGenerationDiagnostics
                )
                await pending.session.failModelTerminal(
                    terminal,
                    error: VocelloQwen3EngineRuntimeFailure()
                )
            }
        }
    }

    /// Handles one materialized event while preserving the generation lease
    /// across every suspension. The producer awaits this method, so a full
    /// audio channel directly backpressures the Qwen token/decode loop.
    private func consumeGenerationSignal(
        _ signal: VocelloQwen3GenerationSignal,
        reservationID: UUID,
        modelIdentity: VocelloQwen3ModelIdentity,
        sampleRate: Int,
        startedAt: ContinuousClock.Instant
    ) async throws {
        guard var pending = pendingGeneration,
              pending.reservationID == reservationID,
              pending.lifecycle == .generating else {
            throw VocelloQwen3EngineError.staleOperation
        }
        try revalidate(pending.lease)
        try pending.session.cancellation.checkCancellation()

        switch signal {
        case .prepared:
            await pending.session.publishPrepared(VocelloQwen3PreparedEvent(
                generationID: pending.request.generationID,
                model: modelIdentity,
                mode: pending.request.mode,
                elapsedMilliseconds: startedAt.elapsedMilliseconds
            ))
            try revalidate(pending.lease)
            try pending.session.cancellation.checkCancellation()
        case .token:
            if pending.firstModelTokenAndAudioCodeMS == nil {
                pending.firstModelTokenAndAudioCodeMS = startedAt.elapsedMilliseconds
            }
            pending.generatedTokenCount += 1
            pendingGeneration = pending
        case .info(let info):
            pending.generatedTokenCount = max(
                pending.generatedTokenCount,
                info.generationTokenCount
            )
            pending.generationInfo = info
            pendingGeneration = pending
        case .chunkTimings(let timings):
            pending.pendingChunkTimings = timings
            pendingGeneration = pending
            await pending.session.recordDiagnostic(VocelloQwen3DiagnosticEvent(
                generationID: pending.request.generationID,
                phase: .decode,
                disposition: .observed,
                generatedTokenCount: pending.generatedTokenCount,
                audioFrameCount: pending.emittedAudioFrameCount
            ))
            try revalidate(pending.lease)
            try pending.session.cancellation.checkCancellation()
        case .audio(let samples):
            if pending.firstDecodedAudioFrameMS == nil {
                pending.firstDecodedAudioFrameMS = startedAt.elapsedMilliseconds
            }
            // Quality-first generation materializes the whole waveform at
            // once. Keep product output lossless while respecting the exact
            // frame capacity that governs the classified audio channel.
            let maximumFrames = pending.request.executionStyle == .qualityFirst
                ? pending.audioCapacityFrames
                : samples.count
            var lowerBound = 0
            while lowerBound < samples.count {
                let upperBound = min(samples.count, lowerBound + maximumFrames)
                let boundedSamples = Array(samples[lowerBound ..< upperBound])
                let startupObservations: VocelloQwen3StartupObservations? = pending.nextAudioSequence == 0
                    ? VocelloQwen3StartupObservations(
                        firstModelTokenAndAudioCodeMilliseconds: pending.firstModelTokenAndAudioCodeMS,
                        firstDecodedAudioFrameMilliseconds: pending.firstDecodedAudioFrameMS
                            ?? startedAt.elapsedMilliseconds
                    )
                    : nil
                let chunk = VocelloQwen3AudioChunkEvent(
                    generationID: pending.request.generationID,
                    sequence: pending.nextAudioSequence,
                    samples: boundedSamples,
                    sampleRate: sampleRate,
                    timings: pending.pendingChunkTimings,
                    codecStartFrame: pending.pendingChunkTimings?.codecStartFrame,
                    codecEndFrameExclusive: pending.pendingChunkTimings?.codecEndFrameExclusive,
                    startupObservations: startupObservations
                )
                try await pending.session.publishAudio(chunk)
                guard var current = pendingGeneration,
                      current.reservationID == reservationID else {
                    throw VocelloQwen3EngineError.staleOperation
                }
                try revalidate(current.lease)
                try current.session.cancellation.checkCancellation()
                current.emittedAudioFrameCount += chunk.frameCount
                current.nextAudioSequence += 1
                current.pendingChunkTimings = nil
                pendingGeneration = current
                pending = current
                lowerBound = upperBound
            }
        }

        guard let current = pendingGeneration,
              current.reservationID == reservationID else {
            throw VocelloQwen3EngineError.staleOperation
        }
        try revalidate(current.lease)
        await current.session.publishProgress(VocelloQwen3ProgressEvent(
            generationID: current.request.generationID,
            generatedTokenCount: current.generatedTokenCount,
            emittedAudioFrameCount: current.emittedAudioFrameCount,
            elapsedMilliseconds: startedAt.elapsedMilliseconds
        ))
        try revalidate(current.lease)
        try current.session.cancellation.checkCancellation()
    }

    private func beginOperation(
        kind: VocelloQwen3RuntimeOperationKind,
        generationID: UUID?,
        phase nextPhase: VocelloQwen3OperationPhase,
        permitsClosedAdmission: Bool = false
    ) throws -> VocelloQwen3RuntimeOperationLease {
        if pressure.admissionClosed, !permitsClosedAdmission {
            throw VocelloQwen3EngineError.admissionClosedForMemoryRelief
        }
        if let activeOperation {
            throw VocelloQwen3EngineError.operationInProgress(activeOperation.kind)
        }
        let lease = VocelloQwen3RuntimeOperationLease(
            kind: kind,
            generationID: generationID,
            modelEpoch: modelEpoch
        )
        activeOperation = lease
        phase = nextPhase
        return lease
    }

    private func performMemoryRelief(
        _ action: VocelloQwen3MemoryReliefAction,
        lease: VocelloQwen3RuntimeOperationLease
    ) async throws {
        await memoryReliefHook(action)
        try revalidate(lease)
        // Clone prompts own MLX tensors independently of runtime caches. Hard
        // relief drops those references before clearing caches; a benign
        // noncritical trim preserves product conditioning handles.
        let beganAsHardRelief = action == .fullUnload || pressure.admissionClosed
        if beganAsHardRelief {
            invalidateCloneHandles()
        }
        await VocelloQwen3Runtime.clearRuntimeCaches(isolation: self)
        try revalidate(lease)

        // Critical pressure may arrive while cache clearing is suspended.
        if !beganAsHardRelief, pressure.admissionClosed {
            invalidateCloneHandles()
        }

        if action == .fullUnload {
            loadedModel = nil
            modelEpoch &+= 1
        }
        activeOperation = nil
        phase = action == .fullUnload || loadedModel == nil ? .unloaded : .ready
        completePressureReliefIfNeeded()
    }

    private func validCloneRecord(
        for handle: VocelloQwen3CloneHandle
    ) -> CloneRecord? {
        guard handle.modelEpoch == modelEpoch,
              handle.model == loadedModel?.identity,
              let record = cloneRecords[handle.id],
              record.handle == handle else {
            return nil
        }
        touchCloneRecord(handle.id)
        return record
    }

    /// `voiceClone.referenceID` is defined as the privacy-safe conditioning
    /// digest minted by the product's validated clone-conditioning resolver.
    /// It must match the selected actor handle exactly; no transcript, audio,
    /// path, or portable handle UUID participates in this binding.
    private func validateCloneConditioningIdentity(
        requestReferenceID: String,
        conditioningDigest: String
    ) throws {
        guard !requestReferenceID.isEmpty,
              requestReferenceID == conditioningDigest else {
            throw VocelloQwen3EngineError.cloneConditioningIdentityMismatch
        }
    }

    private func insertCloneRecord(_ record: CloneRecord) {
        cloneRecords[record.handle.id] = record
        touchCloneRecord(record.handle.id)
        while cloneRecordUseOrder.count > cloneHandleCapacity {
            let evictedID = cloneRecordUseOrder.removeFirst()
            cloneRecords.removeValue(forKey: evictedID)
        }
    }

    private func touchCloneRecord(_ id: UUID) {
        cloneRecordUseOrder.removeAll { $0 == id }
        cloneRecordUseOrder.append(id)
    }

    private func invalidateCloneHandles() {
        cloneRecords.removeAll(keepingCapacity: false)
        cloneRecordUseOrder.removeAll(keepingCapacity: false)
    }

    private func revalidateAbortingReservation(
        _ pending: PendingGeneration
    ) throws {
        try revalidate(pending.lease)
        guard let current = pendingGeneration,
              current.reservationID == pending.reservationID,
              current.lifecycle == .aborting else {
            throw VocelloQwen3EngineError.staleOperation
        }
    }

    private func revalidate(_ lease: VocelloQwen3RuntimeOperationLease) throws {
        guard activeOperation == lease,
              lease.modelEpoch == modelEpoch else {
            throw VocelloQwen3EngineError.staleOperation
        }
        if let generationID = lease.generationID,
           pendingGeneration?.request.generationID != generationID {
            throw VocelloQwen3EngineError.staleOperation
        }
    }

    private func failOperationIfCurrent(_ lease: VocelloQwen3RuntimeOperationLease) {
        guard activeOperation == lease else { return }
        activeOperation = nil
        phase = .failed
    }

    private func releaseGeneration(
        _ pending: PendingGeneration,
        disposition: VocelloQwen3ProductFinalizationDisposition
    ) async {
        lastFinalization = LastFinalization(
            generationID: pending.request.generationID,
            leaseID: pending.lease.id,
            token: pending.session.finalizationToken,
            disposition: disposition,
            completedReliefAction: nil
        )
        pendingGeneration = nil
        activeOperation = nil
        phase = loadedModel == nil ? .unloaded : .ready
        await pending.abortCompletion.resolve()
    }

    /// The sole admission-reopen transition. It is called only after a
    /// successfully revalidated memory-relief lease has completed.
    private func completePressureReliefIfNeeded() {
        guard pressure.admissionClosed else { return }
        pressure = VocelloQwen3MemoryPressureSnapshot(
            level: .normal,
            sequence: pressure.sequence &+ 1,
            admissionClosed: false
        )
    }

    private func acknowledgeAgainstLastFinalization(
        generationID: UUID,
        leaseID: UUID,
        token: VocelloQwen3ProductFinalizationToken,
        disposition: VocelloQwen3ProductFinalizationDisposition
    ) throws -> VocelloQwen3FinalizationAcknowledgeResult {
        guard let lastFinalization,
              lastFinalization.generationID == generationID,
              lastFinalization.leaseID == leaseID,
              lastFinalization.token == token else {
            throw VocelloQwen3SessionError.invalidFinalizationIdentity
        }
        guard lastFinalization.disposition == disposition else {
            throw VocelloQwen3SessionError.conflictingFinalizationAcknowledgement
        }
        return .alreadyAcknowledged
    }
}

enum VocelloQwen3EngineAbortHookEvent: Sendable {
    case owner
    case joiner
}

private actor VocelloQwen3AbortCompletionBarrier {
    private var completed = false
    private var waiters: [CheckedContinuation<Void, Never>] = []

    func wait() async {
        if completed { return }
        await withCheckedContinuation { waiters.append($0) }
    }

    func resolve() {
        guard !completed else { return }
        completed = true
        let pending = waiters
        waiters.removeAll(keepingCapacity: false)
        for waiter in pending { waiter.resume() }
    }
}

private struct VocelloQwen3EngineRuntimeFailure: Error, Sendable {}

private extension ContinuousClock.Instant {
    var elapsedMilliseconds: Int {
        let duration = duration(to: .now)
        return max(0, Int((Double(duration.components.seconds) * 1_000)
            + (Double(duration.components.attoseconds) / 1e15)))
    }
}
