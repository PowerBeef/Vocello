import Combine
import Foundation

/// Type-erased, `MainActor`-bound facade over any `TTSEngine` host, used by the
/// app-level `TTSEngineStore` on iOS and macOS. Both apps host `MLXTTSEngine`
/// in-process through `NativeRuntimeFactory`; the wrapper keeps the store
/// independent of the concrete engine class and of the optional capability
/// protocols (event streaming, runtime control, memory reporting, cancellation,
/// startup-reliability replay), which it probes once at construction.
///
/// PA-17: it is also the admission layer below both apps' views for voice-cloning
/// consent. Clone generation and saved-voice enrollment re-read the host's recorded
/// consent on every call and are refused with `VoiceCloningConsentRequiredError`
/// before the engine sees them, whichever screen, runner or coordinator asked.
@MainActor
public final class AnyTTSEngineBackend {
    public let modelRegistry: any ModelRegistry
    public let supportsSavedVoiceMutation: Bool
    public let supportsModelManagementMutation: Bool
    public let supportedModes: Set<GenerationMode>
    public let stateDidChange: AnyPublisher<Void, Never>
    /// Full ordered per-generation stream with preview PCM intact.
    public let supportsGenerationEventStreaming: Bool
    private let eventsBlock: (UUID) -> AsyncStream<GenerationEvent>?

    private let snapshotBlock: () -> TTSEngineFrontendState
    private let supportDecisionBlock: (GenerationRequest) -> GenerationSupportDecision
    private let startBlock: () -> Void
    private let stopBlock: () -> Void
    private let initializeBlock: (URL) async throws -> Void
    private let pingBlock: () async throws -> Bool
    private let loadModelBlock: (String) async throws -> Void
    private let unloadModelBlock: () async throws -> Void
    private let prepareAudioBlock: (AudioPreparationRequest) async throws -> AudioNormalizationResult
    private let ensureModelLoadedIfNeededBlock: (String) async -> Void
    private let prewarmModelIfNeededBlock: (GenerationRequest) async -> Void
    private let prefetchInteractiveReadinessIfNeededBlock: (GenerationRequest) async -> InteractivePrefetchDiagnostics?
    private let ensureCloneReferencePrimedBlock: (String, CloneReference) async throws -> Void
    private let cancelClonePreparationIfNeededBlock: () async -> Void
    private let cancelActiveGenerationBlock: (GenerationCancellationReason) async throws -> Void
    private let generateBlock: (GenerationRequest) async throws -> GenerationResult
    private let replayStartupReliabilityCodecTraceBlock: (
        GenerationRequest,
        [[Int32]],
        [StartupReliabilityCodecFrameRange]
    ) async throws -> StartupReliabilityCodecReplayResult
    private let startupReliabilityRuntimeOwnershipSnapshotBlock:
        () async -> StartupReliabilityRuntimeOwnershipSnapshot
    private let listPreparedVoicesBlock: () async throws -> [PreparedVoice]
    private let preparePreparedVoiceCandidateBlock: (
        String,
        String,
        String?,
        String?,
        PreparedVoiceEnrollmentMetadata?
    ) async throws -> PreparedVoiceCandidate
    private let commitPreparedVoiceCandidateBlock: (UUID) async throws -> PreparedVoice
    private let discardPreparedVoiceCandidateBlock: (UUID) async throws -> Void
    private let enrollPreparedVoiceBlock: (String, String, String?) async throws -> PreparedVoice
    private let deletePreparedVoiceBlock: (String) async throws -> Void
    private let exportGeneratedAudioBlock: (URL, URL) throws -> ExportedDocument
    private let importReferenceAudioBlock: (URL) throws -> ImportedReferenceAudio
    private let clearGenerationActivityBlock: () -> Void
    private let clearVisibleErrorBlock: () -> Void
    private let setVisibleErrorBlock: (String?) -> Void
    private let setAllowsProactiveWarmOperationsBlock: (Bool) -> Void
    private let recordApplicationMemoryWarningBlock: (String) async -> Void
    private let recordMemoryBudgetTransitionBlock: (
        IOSMemoryPressureBand,
        IOSMemoryPressureBand,
        String
    ) async -> Void
    private let trimMemoryBlock: (NativeMemoryTrimLevel, String) async -> Void
    private let captureMemorySnapshotBlock: (IOSMemoryProcessRole) async -> IOSMemorySnapshot?
    private let engineLifecycleStateBlock: () -> EngineLifecycleState
    private let voiceCloningConsentBlock: @MainActor () -> VoiceCloningConsentPolicy

    /// `voiceCloningConsent` is read at every clone generation and enrollment, so a
    /// Settings change applies to the next call; there is deliberately no default.
    public init<Engine: TTSEngine & AnyObject>(
        engine: Engine,
        supportsSavedVoiceMutation: Bool,
        supportsModelManagementMutation: Bool,
        supportedModes: Set<GenerationMode>,
        voiceCloningConsent: @escaping @MainActor () -> VoiceCloningConsentPolicy
    ) {
        self.voiceCloningConsentBlock = voiceCloningConsent
        self.modelRegistry = engine.modelRegistry
        self.supportsSavedVoiceMutation = supportsSavedVoiceMutation
        self.supportsModelManagementMutation = supportsModelManagementMutation
        self.supportedModes = supportedModes
        self.stateDidChange = engine.objectWillChange
            .map { _ in () }
            .eraseToAnyPublisher()
        if let eventStreamingEngine = engine as? any TTSEngineEventStreaming {
            self.supportsGenerationEventStreaming = true
            self.eventsBlock = { generationID in
                eventStreamingEngine.events(for: generationID)
            }
        } else {
            self.supportsGenerationEventStreaming = false
            self.eventsBlock = { _ in nil }
        }
        self.snapshotBlock = {
            TTSEngineFrontendState(
                isReady: engine.isReady,
                lifecycleState: Self.frontendLifecycleState(for: engine),
                loadState: engine.loadState,
                clonePreparationState: engine.clonePreparationState,
                latestEvent: engine.latestEvent,
                visibleErrorMessage: engine.visibleErrorMessage
            )
        }
        self.supportDecisionBlock = { engine.supportDecision(for: $0) }
        self.startBlock = { engine.start() }
        self.stopBlock = { engine.stop() }
        self.initializeBlock = { try await engine.initialize(appSupportDirectory: $0) }
        self.pingBlock = { try await engine.ping() }
        self.loadModelBlock = { try await engine.loadModel(id: $0) }
        self.unloadModelBlock = { try await engine.unloadModel() }
        self.prepareAudioBlock = { try await engine.prepareAudio($0) }
        self.ensureModelLoadedIfNeededBlock = { await engine.ensureModelLoadedIfNeeded(id: $0) }
        self.prewarmModelIfNeededBlock = { await engine.prewarmModelIfNeeded(for: $0) }
        if let engine = engine as? any TTSEngineRuntimeControlling {
            self.prefetchInteractiveReadinessIfNeededBlock = { await engine.prefetchInteractiveReadinessIfNeeded(for: $0) }
        } else {
            self.prefetchInteractiveReadinessIfNeededBlock = { _ in nil }
        }
        self.ensureCloneReferencePrimedBlock = { try await engine.ensureCloneReferencePrimed(modelID: $0, reference: $1) }
        self.cancelClonePreparationIfNeededBlock = { await engine.cancelClonePreparationIfNeeded() }
        if let engine = engine as? any ActiveGenerationCancellable {
            self.cancelActiveGenerationBlock = { reason in
                try await engine.cancelActiveGeneration(reason: reason)
            }
        } else {
            self.cancelActiveGenerationBlock = { _ in
                throw TTSEngineError.unsupportedRequest(
                    "This engine host does not support active-generation cancellation."
                )
            }
        }
        self.generateBlock = { try await engine.generate($0) }
        if let engine = engine as? any StartupReliabilityCodecReplaying {
            self.replayStartupReliabilityCodecTraceBlock = { request, frames, ranges in
                try await engine.replayStartupReliabilityCodecTrace(
                    request: request,
                    frames: frames,
                    incrementalRanges: ranges
                )
            }
        } else {
            self.replayStartupReliabilityCodecTraceBlock = { _, _, _ in
                throw TTSEngineError.unsupportedRequest(
                    "This engine host does not support startup-reliability codec replay."
                )
            }
        }
        if let engine = engine as? any StartupReliabilityRuntimeOwnershipReporting {
            self.startupReliabilityRuntimeOwnershipSnapshotBlock = {
                await engine.startupReliabilityRuntimeOwnershipSnapshot()
            }
        } else {
            self.startupReliabilityRuntimeOwnershipSnapshotBlock = {
                StartupReliabilityRuntimeOwnershipSnapshot(
                    modelOperationInFlight: false,
                    generationReservationInFlight: false
                )
            }
        }
        self.listPreparedVoicesBlock = { try await engine.listPreparedVoices() }
        self.preparePreparedVoiceCandidateBlock = {
            try await engine.preparePreparedVoiceCandidate(
                name: $0,
                audioPath: $1,
                transcript: $2,
                replacingVoiceID: $3,
                enrollmentMetadata: $4
            )
        }
        self.commitPreparedVoiceCandidateBlock = { try await engine.commitPreparedVoiceCandidate(id: $0) }
        self.discardPreparedVoiceCandidateBlock = { try await engine.discardPreparedVoiceCandidate(id: $0) }
        self.enrollPreparedVoiceBlock = { try await engine.enrollPreparedVoice(name: $0, audioPath: $1, transcript: $2) }
        self.deletePreparedVoiceBlock = { try await engine.deletePreparedVoice(id: $0) }
        self.exportGeneratedAudioBlock = { try engine.exportGeneratedAudio(from: $0, to: $1) }
        self.importReferenceAudioBlock = { try engine.importReferenceAudio(from: $0) }
        self.clearGenerationActivityBlock = { engine.clearGenerationActivity() }
        self.clearVisibleErrorBlock = { engine.clearVisibleError() }
        if let engine = engine as? any TTSEngineRuntimeControlling {
            self.setVisibleErrorBlock = { engine.setVisibleError($0) }
            self.setAllowsProactiveWarmOperationsBlock = { engine.setAllowsProactiveWarmOperations($0) }
            self.recordApplicationMemoryWarningBlock = { reason in
                await engine.recordApplicationMemoryWarning(reason: reason)
            }
            self.recordMemoryBudgetTransitionBlock = { previousBand, currentBand, reason in
                await engine.recordMemoryBudgetTransition(
                    from: previousBand,
                    to: currentBand,
                    reason: reason
                )
            }
            self.trimMemoryBlock = { level, reason in
                await engine.trimMemory(level: level, reason: reason)
            }
        } else {
            self.setVisibleErrorBlock = { _ in }
            self.setAllowsProactiveWarmOperationsBlock = { _ in }
            self.recordApplicationMemoryWarningBlock = { _ in }
            self.recordMemoryBudgetTransitionBlock = { _, _, _ in }
            self.trimMemoryBlock = { _, _ in }
        }
        if let engine = engine as? any NativeMemoryReporting {
            self.captureMemorySnapshotBlock = { role in
                await engine.captureMemorySnapshot(role: role)
            }
        } else {
            self.captureMemorySnapshotBlock = { _ in nil }
        }
        self.engineLifecycleStateBlock = {
            Self.frontendLifecycleState(for: engine)
        }
    }

    public func snapshot() -> TTSEngineFrontendState {
        let snapshot = snapshotBlock()
        return TTSEngineFrontendState(
            isReady: snapshot.isReady,
            lifecycleState: engineLifecycleStateBlock(),
            loadState: snapshot.loadState,
            clonePreparationState: snapshot.clonePreparationState,
            latestEvent: snapshot.latestEvent,
            visibleErrorMessage: snapshot.visibleErrorMessage
        )
    }
    public func supportDecision(for request: GenerationRequest) -> GenerationSupportDecision { supportDecisionBlock(request) }
    public func start() { startBlock() }
    public func stop() { stopBlock() }
    public func initialize(_ appSupportDirectory: URL) async throws { try await initializeBlock(appSupportDirectory) }
    public func ping() async throws -> Bool { try await pingBlock() }
    public func loadModel(id: String) async throws { try await loadModelBlock(id) }
    public func unloadModel() async throws { try await unloadModelBlock() }
    public func prepareAudio(_ request: AudioPreparationRequest) async throws -> AudioNormalizationResult { try await prepareAudioBlock(request) }
    public func ensureModelLoadedIfNeeded(id: String) async { await ensureModelLoadedIfNeededBlock(id) }
    /// Proactive warm-up of a request conditioned on a reference voice is skipped,
    /// not raised, while consent is missing: it is best-effort work no caller awaits
    /// a failure from, and the take itself is refused at `generate`.
    public func prewarmModelIfNeeded(for request: GenerationRequest) async {
        guard admitsProactiveVoiceCloningWork(for: request) else { return }
        await prewarmModelIfNeededBlock(request)
    }
    public func prefetchInteractiveReadinessIfNeeded(for request: GenerationRequest) async -> InteractivePrefetchDiagnostics? {
        guard admitsProactiveVoiceCloningWork(for: request) else { return nil }
        return await prefetchInteractiveReadinessIfNeededBlock(request)
    }
    /// Clone-reference priming conditions the engine on a reference voice, so it is
    /// refused like clone generation until consent is recorded.
    public func ensureCloneReferencePrimed(modelID: String, reference: CloneReference) async throws {
        try voiceCloningConsentBlock().admit(.generation)
        try await ensureCloneReferencePrimedBlock(modelID, reference)
    }
    public func cancelClonePreparationIfNeeded() async { await cancelClonePreparationIfNeededBlock() }
    public func cancelActiveGeneration(reason: GenerationCancellationReason = .user) async throws {
        try await cancelActiveGenerationBlock(reason)
    }
    public func events(for generationID: UUID) -> AsyncStream<GenerationEvent>? {
        eventsBlock(generationID)
    }
    /// Refuses a request conditioned on a reference voice unless consent is recorded.
    /// Built-in Voice and Voice Design requests always pass.
    public func admitVoiceCloning(for request: GenerationRequest) throws(VoiceCloningConsentRequiredError) {
        try voiceCloningConsentBlock().admitGeneration(request)
    }

    /// Refuses saved-voice enrollment unless consent is recorded.
    public func admitVoiceEnrollment() throws(VoiceCloningConsentRequiredError) {
        try voiceCloningConsentBlock().admit(.enrollment)
    }

    private func admitsProactiveVoiceCloningWork(for request: GenerationRequest) -> Bool {
        do {
            try admitVoiceCloning(for: request)
            return true
        } catch {
            return false
        }
    }

    public func generate(_ request: GenerationRequest) async throws -> GenerationResult {
        try admitVoiceCloning(for: request)
        return try await generateBlock(request)
    }
    public func replayStartupReliabilityCodecTrace(
        request: GenerationRequest,
        frames: [[Int32]],
        incrementalRanges: [StartupReliabilityCodecFrameRange]
    ) async throws -> StartupReliabilityCodecReplayResult {
        try await replayStartupReliabilityCodecTraceBlock(request, frames, incrementalRanges)
    }
    public func startupReliabilityRuntimeOwnershipSnapshot()
        async -> StartupReliabilityRuntimeOwnershipSnapshot {
        await startupReliabilityRuntimeOwnershipSnapshotBlock()
    }
    public func listPreparedVoices() async throws -> [PreparedVoice] { try await listPreparedVoicesBlock() }
    public func preparePreparedVoiceCandidate(
        name: String,
        audioPath: String,
        transcript: String?,
        replacingVoiceID: String?
    ) async throws -> PreparedVoiceCandidate {
        try admitVoiceEnrollment()
        return try await preparePreparedVoiceCandidateBlock(name, audioPath, transcript, replacingVoiceID, nil)
    }
    public func preparePreparedVoiceCandidate(
        name: String,
        audioPath: String,
        transcript: String?,
        replacingVoiceID: String?,
        enrollmentMetadata: PreparedVoiceEnrollmentMetadata?
    ) async throws -> PreparedVoiceCandidate {
        try admitVoiceEnrollment()
        return try await preparePreparedVoiceCandidateBlock(
            name,
            audioPath,
            transcript,
            replacingVoiceID,
            enrollmentMetadata
        )
    }
    /// Publishing a staged candidate is enrollment too, so consent withdrawn between
    /// preparation and Keep refuses it; discarding the private candidate stays allowed.
    public func commitPreparedVoiceCandidate(id: UUID) async throws -> PreparedVoice {
        try admitVoiceEnrollment()
        return try await commitPreparedVoiceCandidateBlock(id)
    }
    public func discardPreparedVoiceCandidate(id: UUID) async throws {
        try await discardPreparedVoiceCandidateBlock(id)
    }
    public func enrollPreparedVoice(name: String, audioPath: String, transcript: String?) async throws -> PreparedVoice {
        try admitVoiceEnrollment()
        return try await enrollPreparedVoiceBlock(name, audioPath, transcript)
    }
    public func deletePreparedVoice(id: String) async throws { try await deletePreparedVoiceBlock(id) }
    public func exportGeneratedAudio(from sourceURL: URL, to destinationURL: URL) throws -> ExportedDocument {
        try exportGeneratedAudioBlock(sourceURL, destinationURL)
    }
    public func importReferenceAudio(from sourceURL: URL) throws -> ImportedReferenceAudio {
        try importReferenceAudioBlock(sourceURL)
    }
    public func clearGenerationActivity() { clearGenerationActivityBlock() }
    public func clearVisibleError() { clearVisibleErrorBlock() }
    public func setVisibleError(_ message: String?) { setVisibleErrorBlock(message) }
    public func setAllowsProactiveWarmOperations(_ allow: Bool) { setAllowsProactiveWarmOperationsBlock(allow) }
    public func recordMemoryBudgetTransition(
        from previousBand: IOSMemoryPressureBand,
        to currentBand: IOSMemoryPressureBand,
        reason: String
    ) async {
        await recordMemoryBudgetTransitionBlock(previousBand, currentBand, reason)
    }
    public func recordApplicationMemoryWarning(reason: String) async {
        await recordApplicationMemoryWarningBlock(reason)
    }
    public func trimMemory(level: NativeMemoryTrimLevel, reason: String) async { await trimMemoryBlock(level, reason) }
    public func captureMemorySnapshot(role: IOSMemoryProcessRole) async -> IOSMemorySnapshot? {
        await captureMemorySnapshotBlock(role)
    }

    // The iOS engine runs in-process (MLXTTSEngine); there is no
    // separate extension process with a real lifecycle, so synthesize a health state.
    private static func frontendLifecycleState<Engine: TTSEngine>(
        for engine: Engine
    ) -> EngineLifecycleState {
        if engine.isReady {
            return .connected
        }
        if let visibleErrorMessage = engine.visibleErrorMessage,
           !visibleErrorMessage.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            return .failed
        }
        return .idle
    }
}
