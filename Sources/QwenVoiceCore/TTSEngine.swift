import Combine
import Foundation

public struct TTSEngineFrontendState: Equatable, Sendable {
    public let isReady: Bool
    public let lifecycleState: EngineLifecycleState
    public let loadState: EngineLoadState
    public let clonePreparationState: ClonePreparationState
    public let latestEvent: GenerationEvent?
    public let visibleErrorMessage: String?

    public init(
        isReady: Bool,
        lifecycleState: EngineLifecycleState,
        loadState: EngineLoadState,
        clonePreparationState: ClonePreparationState,
        latestEvent: GenerationEvent?,
        visibleErrorMessage: String?
    ) {
        self.isReady = isReady
        self.lifecycleState = lifecycleState
        self.loadState = loadState
        self.clonePreparationState = clonePreparationState
        self.latestEvent = latestEvent
        self.visibleErrorMessage = visibleErrorMessage
    }

    public init(
        snapshot: TTSEngineSnapshot,
        latestEvent: GenerationEvent? = nil,
        lifecycleState: EngineLifecycleState? = nil
    ) {
        let resolvedLifecycleState = lifecycleState
            ?? Self.defaultLifecycleState(
                isReady: snapshot.isReady,
                loadState: snapshot.loadState,
                visibleErrorMessage: snapshot.visibleErrorMessage
            )
        self.init(
            isReady: snapshot.isReady,
            lifecycleState: resolvedLifecycleState,
            loadState: snapshot.loadState,
            clonePreparationState: snapshot.clonePreparationState,
            latestEvent: latestEvent,
            visibleErrorMessage: snapshot.visibleErrorMessage
        )
    }

    public func updating(
        latestEvent: GenerationEvent? = nil,
        lifecycleState: EngineLifecycleState? = nil
    ) -> TTSEngineFrontendState {
        TTSEngineFrontendState(
            isReady: isReady,
            lifecycleState: lifecycleState ?? self.lifecycleState,
            loadState: loadState,
            clonePreparationState: clonePreparationState,
            latestEvent: latestEvent ?? self.latestEvent,
            visibleErrorMessage: visibleErrorMessage
        )
    }

    public func withoutPreviewAudioPayload() -> TTSEngineFrontendState {
        TTSEngineFrontendState(
            isReady: isReady,
            lifecycleState: lifecycleState,
            loadState: loadState,
            clonePreparationState: clonePreparationState,
            latestEvent: latestEvent?.withoutPreviewAudioPayload(),
            visibleErrorMessage: visibleErrorMessage
        )
    }

    private static func defaultLifecycleState(
        isReady: Bool,
        loadState: EngineLoadState,
        visibleErrorMessage: String?
    ) -> EngineLifecycleState {
        if isReady {
            return .connected
        }
        if case .starting = loadState {
            if let visibleErrorMessage,
               !visibleErrorMessage.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                return .recovering
            }
            return .launching
        }
        if let visibleErrorMessage,
           !visibleErrorMessage.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            return .failed
        }
        return .idle
    }
}

@MainActor
public protocol TTSEngine: ObservableObject {
    var modelRegistry: any ModelRegistry { get }
    var loadState: EngineLoadState { get }
    var clonePreparationState: ClonePreparationState { get }
    var latestEvent: GenerationEvent? { get }
    var isReady: Bool { get }
    var visibleErrorMessage: String? { get }

    func supportDecision(for request: GenerationRequest) -> GenerationSupportDecision
    func start()
    func stop()
    func initialize(appSupportDirectory: URL) async throws
    func ping() async throws -> Bool
    func loadModel(id: String) async throws
    func unloadModel() async throws
    func prepareAudio(_ request: AudioPreparationRequest) async throws -> AudioNormalizationResult
    func ensureModelLoadedIfNeeded(id: String) async
    func prewarmModelIfNeeded(for request: GenerationRequest) async
    func ensureCloneReferencePrimed(modelID: String, reference: CloneReference) async throws
    func cancelClonePreparationIfNeeded() async
    func generate(_ request: GenerationRequest) async throws -> GenerationResult
    func listPreparedVoices() async throws -> [PreparedVoice]
    func preparePreparedVoiceCandidate(
        name: String,
        audioPath: String,
        transcript: String?,
        replacingVoiceID: String?
    ) async throws -> PreparedVoiceCandidate
    func preparePreparedVoiceCandidate(
        name: String,
        audioPath: String,
        transcript: String?,
        replacingVoiceID: String?,
        enrollmentMetadata: PreparedVoiceEnrollmentMetadata?
    ) async throws -> PreparedVoiceCandidate
    func commitPreparedVoiceCandidate(id: UUID) async throws -> PreparedVoice
    func discardPreparedVoiceCandidate(id: UUID) async throws
    func enrollPreparedVoice(name: String, audioPath: String, transcript: String?) async throws -> PreparedVoice
    func deletePreparedVoice(id: String) async throws
    func importReferenceAudio(from sourceURL: URL) throws -> ImportedReferenceAudio
    func exportGeneratedAudio(from sourceURL: URL, to destinationURL: URL) throws -> ExportedDocument
    func clearGenerationActivity()
    func clearVisibleError()
}

/// Engines that expose the full, ordered `GenerationEvent` stream — with each chunk's
/// preview PCM payload **intact** (the `latestEvent` snapshot strips it, and coalescing
/// drops intermediate chunks). In-process transport consumers (the iOS app) drain this to
/// play streamed audio live during generation. Out-of-process (macOS XPC) consumes the same
/// stream inside the engine service. A subscribed generation always closes with exactly one
/// `.completed`, `.cancelled`, or `.failed` event, including preflight/admission failures.
public protocol TTSEngineEventStreaming: AnyObject {
    func events(for generationID: UUID) -> AsyncStream<GenerationEvent>
}

public extension TTSEngine {
    func preparePreparedVoiceCandidate(
        name: String,
        audioPath: String,
        transcript: String?,
        replacingVoiceID: String?,
        enrollmentMetadata: PreparedVoiceEnrollmentMetadata?
    ) async throws -> PreparedVoiceCandidate {
        try await preparePreparedVoiceCandidate(
            name: name,
            audioPath: audioPath,
            transcript: transcript,
            replacingVoiceID: replacingVoiceID
        )
    }
}

public struct StartupReliabilityCodecFrameRange: Codable, Hashable, Sendable {
    public let start: Int
    public let endExclusive: Int

    public init(start: Int, endExclusive: Int) {
        self.start = start
        self.endExclusive = endExclusive
    }
}

public struct StartupReliabilityCodecReplayResult: Sendable {
    public let incrementalAudio: [Float]
    public let fullAudio: [Float]
    public let sampleRate: Int

    public init(incrementalAudio: [Float], fullAudio: [Float], sampleRate: Int) {
        self.incrementalAudio = incrementalAudio
        self.fullAudio = fullAudio
        self.sampleRate = sampleRate
    }
}

public struct StartupReliabilityRuntimeOwnershipSnapshot: Hashable, Codable, Sendable {
    public let modelOperationInFlight: Bool
    public let generationReservationInFlight: Bool

    public init(modelOperationInFlight: Bool, generationReservationInFlight: Bool) {
        self.modelOperationInFlight = modelOperationInFlight
        self.generationReservationInFlight = generationReservationInFlight
    }
}

/// Diagnostics-only runtime ownership probe. It exposes only booleans and does
/// not grant access to the operation, reservation, model, or MLX state.
@MainActor
public protocol StartupReliabilityRuntimeOwnershipReporting: AnyObject {
    func startupReliabilityRuntimeOwnershipSnapshot()
        async -> StartupReliabilityRuntimeOwnershipSnapshot
}

/// Diagnostics-only capability implemented by the in-process native engine.
/// It is intentionally separate from `TTSEngine`: replay is not a product
/// feature and must never become an ordinary engine requirement.
@MainActor
public protocol StartupReliabilityCodecReplaying: AnyObject {
    func replayStartupReliabilityCodecTrace(
        request: GenerationRequest,
        frames: [[Int32]],
        incrementalRanges: [StartupReliabilityCodecFrameRange]
    ) async throws -> StartupReliabilityCodecReplayResult
}

@MainActor
public protocol TTSEngineRuntimeControlling: TTSEngine {
    func prefetchInteractiveReadinessIfNeeded(
        for request: GenerationRequest
    ) async -> InteractivePrefetchDiagnostics?
    func setVisibleError(_ message: String?)
    func setAllowsProactiveWarmOperations(_ allow: Bool)
    func recordApplicationMemoryWarning(reason: String) async
    func recordMemoryBudgetTransition(
        from previousBand: IOSMemoryPressureBand,
        to currentBand: IOSMemoryPressureBand,
        reason: String
    ) async
    func trimMemory(level: NativeMemoryTrimLevel, reason: String) async
}

@MainActor
public protocol NativeMemoryReporting: AnyObject {
    func captureMemorySnapshot(role: IOSMemoryProcessRole) async -> IOSMemorySnapshot?
}

@MainActor
public protocol ActiveGenerationCancellable: AnyObject {
    func cancelActiveGeneration(reason: GenerationCancellationReason) async throws
}

public extension ActiveGenerationCancellable {
    func cancelActiveGeneration() async throws {
        try await cancelActiveGeneration(reason: .user)
    }
}
