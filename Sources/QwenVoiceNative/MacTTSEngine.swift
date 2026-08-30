@_exported import QwenVoiceEngineSupport
import Combine
import Foundation
import QwenVoiceCore

public protocol MacTTSEngine: AnyObject, Sendable {
    var snapshot: TTSEngineSnapshot { get }
    var snapshotPublisher: AnyPublisher<TTSEngineSnapshot, Never> { get }

    func initialize(appSupportDirectory: URL) async throws
    func ping() async throws -> Bool
    func loadModel(id: String) async throws
    func unloadModel() async throws
    func ensureModelLoadedIfNeeded(id: String) async
    func prewarmModelIfNeeded(for request: GenerationRequest) async
    func prefetchInteractiveReadinessIfNeeded(for request: GenerationRequest) async -> InteractivePrefetchDiagnostics?
    func ensureCloneReferencePrimed(modelID: String, reference: CloneReference) async throws
    func cancelClonePreparationIfNeeded() async
    func generate(_ request: GenerationRequest) async throws -> GenerationResult
    func cancelActiveGeneration() async throws
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
    func clearGenerationActivity()
    func clearVisibleError()

    /// Optional capability — retire the engine's backing process while idle
    /// so the OS reclaims memory model unload can't (MLX fragmentation,
    /// Metal shader caches). Only meaningful for out-of-process engines;
    /// the default is a no-op that reports "not retired".
    func retireServiceIfIdle() async -> Bool
}

public extension MacTTSEngine {
    func retireServiceIfIdle() async -> Bool { false }

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
