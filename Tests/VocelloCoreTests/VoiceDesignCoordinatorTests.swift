import Foundation
import QwenVoiceCore
import XCTest

/// Executes the production coordinator and production draft. Only its UI/engine
/// collaborators are test doubles: no app host, network, model, or device is used.
@MainActor
final class VoiceDesignCoordinatorTests: XCTestCase {
    func testExplicitFrenchAndPinnedSeedSurviveDelayedPreparation() async throws {
        var draft = VoiceDesignDraft(
            voiceDescription: "A warm narrator.", pinnedSeed: UInt64.max - 7,
            selectedLanguage: .french, emotion: "Speak calmly.", text: "Bonjour tout le monde."
        )
        let original = draft
        GenerationVariationPreference.value = .consistent
        defer { GenerationVariationPreference.value = nil }
        let coordinator = VoiceDesignCoordinator()
        let store = TTSEngineStore()
        coordinator.generate(
            draft: draft, activeModel: model, isModelAvailable: true,
            ttsEngineStore: store, audioPlayer: AudioPlayerViewModel(),
            modelManager: ModelManagerViewModel()
        )
        // The executor has not run prepare yet. Mutating the editor or Settings
        // during this boundary must not change the already requested take.
        draft.selectedLanguage = .english
        draft.pinnedSeed = 3
        draft.voiceDescription = "Changed description"
        draft.emotion = "Changed delivery"
        draft.text = "Changed text"
        GenerationVariationPreference.value = .balanced
        let request = await store.capturedRequest()
        let prepared = (request: request, text: request.text)
        XCTAssertEqual(prepared.request.languageHint, "french")
        XCTAssertEqual(prepared.request.seed, original.pinnedSeed)
        XCTAssertEqual(prepared.request.variation, .consistent)
        XCTAssertEqual(prepared.request.text, original.text)
        XCTAssertEqual(prepared.text, original.text)
        guard case let .design(description, delivery) = prepared.request.payload else {
            return XCTFail("Expected Design request")
        }
        XCTAssertEqual(description, original.voiceDescription)
        XCTAssertEqual(delivery, original.emotion)
    }

    func testAutoAndFreshSeedRemainUnspecifiedAtEngineBoundary() async throws {
        GenerationVariationPreference.value = nil
        let coordinator = VoiceDesignCoordinator()
        let store = TTSEngineStore()
        coordinator.generate(
            draft: VoiceDesignDraft(voiceDescription: "Narrator", text: "Bonjour à tous."),
            activeModel: model, isModelAvailable: true, ttsEngineStore: store,
            audioPlayer: AudioPlayerViewModel(), modelManager: ModelManagerViewModel()
        )
        let request = await store.capturedRequest()
        let prepared = (request: request, text: request.text)
        XCTAssertEqual(prepared.request.languageHint, "auto")
        XCTAssertNil(prepared.request.seed)
        XCTAssertNil(prepared.request.variation)
        XCTAssertEqual(GenerationSemantics.qwenLanguageHint(for: prepared.request), "french")
        XCTAssertTrue(prepared.request.shouldStream)
    }

    func testMissingModelDoesNotProduceARequest() async throws {
        let coordinator = VoiceDesignCoordinator()
        let store = TTSEngineStore()
        coordinator.generate(
            draft: VoiceDesignDraft(voiceDescription: "Narrator", text: "Hello."),
            activeModel: nil, isModelAvailable: true, ttsEngineStore: store,
            audioPlayer: AudioPlayerViewModel(), modelManager: ModelManagerViewModel()
        )
        let deadline = ContinuousClock.now.advanced(by: .seconds(2))
        while coordinator.isGenerating && ContinuousClock.now < deadline { await Task.yield() }
        XCTAssertFalse(coordinator.isGenerating)
        XCTAssertNil(store.lastRequest)
        XCTAssertEqual(coordinator.errorMessage, "Model configuration not found")
    }

    private var model: TTSModel { TTSModel(id: "design", outputSubfolder: "design", mode: .design, tier: "pro") }
}

// Test-target-only collaborators for the production coordinator. They deliberately
// do not implement playback, generation, persistence, or saved-voice acceptance.
struct TTSModel { let id: String; let outputSubfolder: String; let mode: GenerationMode; let tier: String }
struct Voice { let name: String }
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
@MainActor final class ModelManagerViewModel { func recoveryDetail(for model: TTSModel) -> String { "Unavailable" } }
@MainActor final class SavedVoicesViewModel {
    func insertOrReplace(_ voice: Voice) {}
    func refresh(using store: TTSEngineStore) async {}
}
enum LongTextGenerationRouter { static func shouldRouteToLongFormBatch(_ text: String) -> Bool { false } }
enum SavedVoiceNameSuggestion { static func designResultName(from description: String) -> String { description } }
func makeOutputPath(subfolder: String, text: String) -> String { "/tmp/design-coordinator-fixture.wav" }
enum GenerationVariationPreference { @MainActor static var value: Qwen3SamplingVariation?
    @MainActor static func requestValue() -> Qwen3SamplingVariation? { value }
}
enum TestSegmentationMode { case longForm }
struct TestBatchConfiguration {
    static func design(draft: VoiceDesignDraft, initialText: String = "", initialSegmentationMode: TestSegmentationMode = .longForm) -> Self { Self() }
}
struct TestSavedVoiceConfiguration {
    static func designResult(voiceDescription: String, audioPath: String, transcript: String) -> Self { Self() }
}
enum VoiceDesignPresentedSheet { case batch(TestBatchConfiguration), saveVoice(TestSavedVoiceConfiguration) }
