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
        coordinator.generate(
            draft: draft, activeModel: model, isModelAvailable: true,
            ttsEngineStore: TTSEngineStore(), audioPlayer: AudioPlayerViewModel(),
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
        let captured = await GenerationLifecycleExecutor.capturePreparedTake()
        let prepared = try XCTUnwrap(captured)
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
        coordinator.generate(
            draft: VoiceDesignDraft(voiceDescription: "Narrator", text: "Bonjour à tous."),
            activeModel: model, isModelAvailable: true, ttsEngineStore: TTSEngineStore(),
            audioPlayer: AudioPlayerViewModel(), modelManager: ModelManagerViewModel()
        )
        let captured = await GenerationLifecycleExecutor.capturePreparedTake()
        let prepared = try XCTUnwrap(captured)
        XCTAssertEqual(prepared.request.languageHint, "auto")
        XCTAssertNil(prepared.request.seed)
        XCTAssertNil(prepared.request.variation)
        XCTAssertEqual(GenerationSemantics.qwenLanguageHint(for: prepared.request), "french")
        XCTAssertTrue(prepared.request.shouldStream)
    }

    func testMissingModelDoesNotProduceARequest() async throws {
        let coordinator = VoiceDesignCoordinator()
        coordinator.generate(
            draft: VoiceDesignDraft(voiceDescription: "Narrator", text: "Hello."),
            activeModel: nil, isModelAvailable: true, ttsEngineStore: TTSEngineStore(),
            audioPlayer: AudioPlayerViewModel(), modelManager: ModelManagerViewModel()
        )
        let prepared = await GenerationLifecycleExecutor.capturePreparedTake()
        XCTAssertNil(prepared)
        XCTAssertEqual(coordinator.errorMessage, "Model configuration not found")
    }

    private var model: TTSModel { TTSModel(id: "design", outputSubfolder: "design", mode: .design, tier: "pro") }
}

// Test-target-only collaborators for the production coordinator. They deliberately
// do not implement playback, generation, persistence, or saved-voice acceptance.
struct TTSModel { let id: String; let outputSubfolder: String; let mode: GenerationMode; let tier: String }
struct Voice { let name: String }
@MainActor final class TTSEngineStore { var hasActiveGeneration = false; var isReady = true }
@MainActor final class AudioPlayerViewModel {}
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
@MainActor enum GenerationLifecycleExecutor {
    struct PreparedTake {
        let request: GenerationRequest
        let text: String
        let persistCaller: String
        let makeGeneration: @MainActor (GenerationResult) -> Generation
        var onSuccess: (@MainActor (Generation, GenerationResult) -> Void)?
    }
    private static var preparation: (@MainActor () async throws -> PreparedTake?)?
    private static var finish: (@MainActor () -> Void)?
    static func run(
        ttsEngineStore: TTSEngineStore, audioPlayer: AudioPlayerViewModel,
        setErrorMessage: @escaping @MainActor (String?) -> Void,
        onFinish: @escaping @MainActor () -> Void,
        prepare: @escaping @MainActor () async throws -> PreparedTake?
    ) -> Task<Void, Never> {
        preparation = prepare
        finish = onFinish
        return Task {}
    }
    static func capturePreparedTake() async -> PreparedTake? {
        let prepare = preparation
        preparation = nil
        defer { finish?(); finish = nil }
        do { return try await prepare?() }
        catch { XCTFail("Unexpected preparation failure: \(error)"); return nil }
    }
    static func cancelActiveWork(generationTask: inout Task<Void, Never>?, isGenerating: inout Bool,
                                 errorMessage: inout String?, ttsEngineStore: TTSEngineStore,
                                 audioPlayer: AudioPlayerViewModel) {
        generationTask?.cancel()
    }
}
