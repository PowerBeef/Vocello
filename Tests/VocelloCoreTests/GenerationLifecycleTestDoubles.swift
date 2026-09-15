import Foundation
import QwenVoiceCore

// Test-target-only collaborators for the production `GenerationLifecycleExecutor`
// (compiled into this bundle by path). They deliberately do not implement
// playback, generation, persistence, or saved-voice acceptance. They lived in
// the Design coordinator's test until that coordinator retired on 2026-09-15.
@MainActor final class TTSEngineStore {
    var hasActiveGeneration = false
    var isReady = true
    var lastRequest: GenerationRequest?
    var generation: ((GenerationRequest) async throws -> GenerationResult)?
    var cancelCount = 0
    private var waiter: CheckedContinuation<GenerationRequest, Never>?
    func generate(_ request: GenerationRequest) async throws -> GenerationResult {
        lastRequest = request
        waiter?.resume(returning: request); waiter = nil
        if let generation { return try await generation(request) }
        throw CancellationError()
    }
    func capturedRequest() async -> GenerationRequest {
        if let lastRequest { return lastRequest }
        return await withCheckedContinuation { waiter = $0 }
    }
    func cancelActiveGeneration() async throws { cancelCount += 1 }
}
@MainActor final class AudioPlayerViewModel {
    var estimate: LivePreviewEstimate?
    var abortCount = 0
    func setLivePreviewEstimate(_ value: LivePreviewEstimate?) { estimate = value }
    func abortLivePreviewIfNeeded() { abortCount += 1 }
}
struct LivePreviewEstimate { let text: String }
@MainActor enum GenerationPersistence {
    static var handler: (() async -> Void)?
    static var autoplayCount = 0
    static func persistAndAutoplay(_ generation: Generation, result: GenerationResult, text: String, audioPlayer: AudioPlayerViewModel, caller: String) async { autoplayCount += 1; await handler?() }
    static func persist(_ generation: Generation, caller: String) async { await handler?() }
}
@MainActor final class AppGenerationTimeline {
    static let shared = AppGenerationTimeline()
    func recordSubmitted(id: UUID?, mode: String?) async {}
    func recordFailed(id: UUID?, finishReason: GenerationTerminalReason = .failed) async {}
    func recordCompleted(id: UUID?, mode: String?, usedStreaming: Bool, finishReason: String?, summary: TelemetrySummary?) async {}
}
enum GenerationTelemetryMerger { static func scheduleMerge(generationID: UUID?) {} }
