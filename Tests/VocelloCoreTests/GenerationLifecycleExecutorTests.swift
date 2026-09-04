import Foundation
import QwenVoiceCore
import XCTest

/// Executes the production executor with controlled collaborator suspensions.
@MainActor
final class GenerationLifecycleExecutorTests: XCTestCase {
    private enum LateFailure: Error { case injected }

    func testPublishedResultAfterCancellationIsPersistedWithoutStealingNewPlayback() async throws {
        let store = TTSEngineStore()
        let player = AudioPlayerViewModel()
        let authority = GenerationLifecycleExecutor.Authority()
        let aEntered = expectation(description: "A generating")
        let bEntered = expectation(description: "B generating")
        var releaseA: CheckedContinuation<Void, Never>?
        var releaseB: CheckedContinuation<Void, Never>?
        var persisted = 0
        var aSuccess = false
        store.generation = { request in
            if request.text == "A" {
                await withCheckedContinuation { releaseA = $0; aEntered.fulfill() }
            } else {
                await withCheckedContinuation { releaseB = $0; bEntered.fulfill() }
            }
            return GenerationResult(audioPath: "/tmp/lifecycle.wav", durationSeconds: 1, streamSessionDirectory: nil, usedStreaming: false)
        }
        GenerationPersistence.handler = { persisted += 1 }
        GenerationPersistence.autoplayCount = 0
        defer { GenerationPersistence.handler = nil; GenerationPersistence.autoplayCount = 0 }
        var a: Task<Void, Never>? = GenerationLifecycleExecutor.run(authority: authority,
            ttsEngineStore: store, audioPlayer: player, setErrorMessage: { _ in }, onFinish: {}) {
                self.take("A", onSuccess: { aSuccess = true })
            }
        await fulfillment(of: [aEntered], timeout: 2)
        let originalA = try XCTUnwrap(a)
        var generating = true
        var error: String?
        GenerationLifecycleExecutor.cancelActiveWork(authority: authority, generationTask: &a,
            isGenerating: &generating, errorMessage: &error, ttsEngineStore: store, audioPlayer: player)
        let b = GenerationLifecycleExecutor.run(authority: authority, ttsEngineStore: store,
            audioPlayer: player, setErrorMessage: { _ in }, onFinish: {}) { self.take("B") }
        await fulfillment(of: [bEntered], timeout: 2)
        releaseA?.resume() // A's publication won the race against cancellation.
        await originalA.value
        XCTAssertEqual(persisted, 1, "Published output must retain its History owner")
        XCTAssertEqual(GenerationPersistence.autoplayCount, 0)
        XCTAssertEqual(player.estimate?.text, "B")
        XCTAssertFalse(aSuccess)
        releaseB?.resume()
        await b.value
    }

    func testLatePreparationAndErrorCannotOverwriteTheNextAttempt() async throws {
        for throwsAfterPreparation in [false, true] {
            let store = TTSEngineStore()
            let player = AudioPlayerViewModel()
            let authority = GenerationLifecycleExecutor.Authority()
            let aEntered = expectation(description: "A preparing")
            let bEntered = expectation(description: "B generating")
            var releaseA: CheckedContinuation<Void, Never>?
            var releaseB: CheckedContinuation<Void, Never>?
            var submitted: [String] = []
            var oldFinishes = 0
            var errors: [String] = []
            store.generation = { request in
                submitted.append(request.text)
                await withCheckedContinuation { releaseB = $0; bEntered.fulfill() }
                return GenerationResult(audioPath: "/tmp/lifecycle.wav", durationSeconds: 1, streamSessionDirectory: nil, usedStreaming: false)
            }
            var a: Task<Void, Never>? = GenerationLifecycleExecutor.run(authority: authority,
                ttsEngineStore: store, audioPlayer: player,
                setErrorMessage: { if let value = $0 { errors.append(value) } }, onFinish: { oldFinishes += 1 }) {
                    await withCheckedContinuation { releaseA = $0; aEntered.fulfill() }
                    if throwsAfterPreparation { throw LateFailure.injected }
                    return self.take("A")
                }
            await fulfillment(of: [aEntered], timeout: 2)
            let oldTask = try XCTUnwrap(a)
            var generating = true
            var error: String?
            GenerationLifecycleExecutor.cancelActiveWork(authority: authority, generationTask: &a,
                isGenerating: &generating, errorMessage: &error, ttsEngineStore: store, audioPlayer: player)
            let b = GenerationLifecycleExecutor.run(authority: authority, ttsEngineStore: store,
                audioPlayer: player, setErrorMessage: { _ in }, onFinish: {}) { self.take("B") }
            await fulfillment(of: [bEntered], timeout: 2)
            releaseA?.resume()
            await oldTask.value
            XCTAssertEqual(submitted, ["B"])
            XCTAssertEqual(player.estimate?.text, "B")
            XCTAssertTrue(errors.isEmpty)
            XCTAssertEqual(oldFinishes, 0)
            releaseB?.resume()
            await b.value
        }
    }

    func testCancelledPersistenceCannotClearOrCancelNewTake() async throws {
        let store = TTSEngineStore()
        let player = AudioPlayerViewModel()
        let authority = GenerationLifecycleExecutor.Authority()
        let persistenceEntered = expectation(description: "A entered persistence")
        let generationBEntered = expectation(description: "B entered engine")
        var releaseA: CheckedContinuation<Void, Never>?
        var releaseB: CheckedContinuation<Void, Never>?
        var aSuccess = false
        var aFinishes = 0
        store.generation = { request in
            if request.text == "B" {
                await withCheckedContinuation { releaseB = $0; generationBEntered.fulfill() }
            }
            return GenerationResult(audioPath: "/tmp/lifecycle.wav", durationSeconds: 1, streamSessionDirectory: nil, usedStreaming: false)
        }
        GenerationPersistence.handler = {
            await withCheckedContinuation { releaseA = $0; persistenceEntered.fulfill() }
        }
        defer { GenerationPersistence.handler = nil }
        var a: Task<Void, Never>? = GenerationLifecycleExecutor.run(authority: authority, ttsEngineStore: store, audioPlayer: player,
            setErrorMessage: { _ in }, onFinish: { aFinishes += 1 }) {
                self.take("A", onSuccess: { aSuccess = true })
            }
        await fulfillment(of: [persistenceEntered], timeout: 2)
        let originalA = try XCTUnwrap(a)
        var generating = true
        var error: String?
        GenerationLifecycleExecutor.cancelActiveWork(authority: authority, generationTask: &a, isGenerating: &generating, errorMessage: &error, ttsEngineStore: store, audioPlayer: player)
        GenerationPersistence.handler = nil
        let b = GenerationLifecycleExecutor.run(authority: authority, ttsEngineStore: store, audioPlayer: player, setErrorMessage: { _ in }, onFinish: {}) { self.take("B") }
        await fulfillment(of: [generationBEntered], timeout: 2)
        releaseA?.resume()
        await originalA.value
        XCTAssertEqual(player.estimate?.text, "B")
        XCTAssertEqual(aFinishes, 0, "cancel already reset A; its late defer has no authority")
        XCTAssertFalse(aSuccess)
        XCTAssertEqual(store.cancelCount, 0, "task cancellation owns transport cancellation, not a delayed unscoped second call")
        releaseB?.resume()
        await b.value
    }

    private func take(_ text: String, onSuccess: @escaping () -> Void = {}) -> GenerationLifecycleExecutor.PreparedTake {
        GenerationLifecycleExecutor.PreparedTake(
            request: GenerationRequest(mode: .design, modelID: "test", text: text, outputPath: "/tmp/lifecycle.wav", shouldStream: false, payload: .design(voiceDescription: "test", deliveryStyle: nil), generationID: UUID()),
            text: text, persistCaller: "test",
            makeGeneration: { result in Generation(text: text, mode: "design", modelTier: "pro", audioPath: result.audioPath, createdAt: Date()) },
            onSuccess: { _, _ in onSuccess() }
        )
    }
}
