import Foundation
import QwenVoiceCore
import XCTest

/// AUD-03: the macOS Studio start and cancel path (`MacStudioSingleTakeRunner`)
/// on the real attempt-scoped `StudioGenerationCoordinator` with a fake engine.
/// The runner owns the take's task and the coordinator retains it; only the
/// engine barrier makes a cancelled attempt terminal; a cancelled take never
/// completes, including one whose cancellation was accepted before its Swift
/// task was cancelled (PA-15).
@MainActor
final class MacStudioSingleTakeRunnerTests: XCTestCase {
    private enum TestError: LocalizedError {
        case engine
        case barrier

        var errorDescription: String? {
            switch self {
            case .engine: "engine write failed"
            case .barrier: "barrier did not finish"
            }
        }
    }

    // MARK: - Start

    func testStartOwnsTheTaskAndPublishesTheCompletedTake() async throws {
        let coordinator = StudioGenerationCoordinator(mode: .custom)
        let engine = FakeEngine()
        let plan = try makePlan()

        XCTAssertTrue(startTake(plan, on: coordinator, engine: engine))
        XCTAssertTrue(coordinator.isGenerating)
        let task = try XCTUnwrap(coordinator.generationTask, "The coordinator retains the take's task")
        XCTAssertEqual(coordinator.liveItem, IOSStudioLivePreviewItem(
            voiceName: "Aiden",
            modeLabel: "Built-in",
            mode: .custom,
            transcript: plan.request.text,
            waveformSeed: 41,
            estimatedAudioDuration: 4
        ), "The live card carries the plan's identity so the final card keeps its shape")

        engine.finishGeneration(.success(engine.result))
        await task.value

        XCTAssertEqual(engine.requests, [plan.request], "The immutable request reaches the engine unchanged")
        XCTAssertEqual(engine.events, [.submitted, .generated, .completed])
        XCTAssertFalse(coordinator.isGenerating)
        XCTAssertNil(coordinator.generationTask)
        XCTAssertNil(coordinator.liveItem)
        XCTAssertNil(coordinator.errorMessage)
        XCTAssertEqual(coordinator.lastCompletedOutput?.generationID, plan.generationID)
        XCTAssertEqual(coordinator.lastCompletedOutput?.audioURL.path, engine.result.audioPath)
        XCTAssertEqual(engine.completedResults, [engine.result])
    }

    func testAStartWhileAnAttemptRunsIsRefusedAndStartsNothing() async throws {
        let coordinator = StudioGenerationCoordinator(mode: .custom)
        let first = FakeEngine()
        let second = FakeEngine()

        let plan = try makePlan()
        XCTAssertTrue(startTake(plan, on: coordinator, engine: first))
        let task = try XCTUnwrap(coordinator.generationTask)
        let attempt = try XCTUnwrap(coordinator.activeAttempt)
        XCTAssertFalse(startTake(plan, on: coordinator, engine: second))
        XCTAssertEqual(coordinator.activeAttempt, attempt)
        XCTAssertEqual(coordinator.generationTask, task)

        first.finishGeneration(.success(first.result))
        await task.value

        XCTAssertTrue(second.events.isEmpty)
        XCTAssertTrue(second.requests.isEmpty)
        XCTAssertEqual(first.completedResults, [first.result])
    }

    func testPrepareRunsInsideTheAttemptBeforeTheTakeIsSubmitted() async throws {
        let coordinator = StudioGenerationCoordinator(mode: .clone)
        let engine = FakeEngine()

        let plan = try makePlan()
        let started = MacStudioSingleTakeRunner.start(
            plan: plan,
            estimatedAudioDuration: 4,
            coordinator: coordinator,
            hooks: engine,
            prepare: {
                XCTAssertTrue(coordinator.isAttemptRunning, "Priming belongs to the running attempt")
                engine.events.append(.prepared)
            }
        )
        XCTAssertTrue(started)
        let task = try XCTUnwrap(coordinator.generationTask)
        engine.finishGeneration(.success(engine.result))
        await task.value

        XCTAssertEqual(engine.events, [.prepared, .submitted, .generated, .completed])
    }

    func testEngineFailureSurfacesThroughTheCoordinator() async throws {
        let coordinator = StudioGenerationCoordinator(mode: .design)
        let engine = FakeEngine()

        let plan = try makePlan()
        XCTAssertTrue(startTake(plan, on: coordinator, engine: engine))
        let task = try XCTUnwrap(coordinator.generationTask)
        engine.finishGeneration(.failure(TestError.engine))
        await task.value

        XCTAssertEqual(engine.events, [.submitted, .generated, .failed])
        XCTAssertFalse(coordinator.isGenerating)
        XCTAssertEqual(coordinator.errorMessage, "engine write failed")
        XCTAssertNil(coordinator.lastCompletedOutput)
        XCTAssertTrue(engine.completedResults.isEmpty)
    }

    // MARK: - Cancel

    func testUserCancellationStaysNonterminalUntilTheEngineBarrierReports() async throws {
        let coordinator = StudioGenerationCoordinator(mode: .custom)
        let engine = FakeEngine()
        let barrier = FakeBarrier()

        let plan = try makePlan()
        XCTAssertTrue(startTake(plan, on: coordinator, engine: engine))
        let task = try XCTUnwrap(coordinator.generationTask)
        let attempt = try XCTUnwrap(coordinator.activeAttempt)
        await engine.waitUntilGenerating()

        var previewStops = 0
        let cancellation = MacStudioSingleTakeRunner.cancel(
            coordinator: coordinator,
            stopLivePreview: { previewStops += 1 },
            barrier: { try await barrier.run() }
        )
        let barrierTask = try XCTUnwrap(cancellation)
        XCTAssertEqual(previewStops, 1, "Audible preview stops at once")
        XCTAssertTrue(coordinator.isCancellationRequested(for: attempt))
        let duplicate = MacStudioSingleTakeRunner.cancel(
            coordinator: coordinator,
            stopLivePreview: { previewStops += 1 },
            barrier: { try await barrier.run() }
        )
        XCTAssertNil(duplicate, "A duplicate cancellation joins the pending barrier")
        XCTAssertEqual(previewStops, 1)

        // The engine still returns a take after the user cancelled: it is discarded.
        engine.finishGeneration(.success(engine.result))
        await task.value
        XCTAssertEqual(engine.events, [.submitted, .generated, .cancelled(materialized: true)])
        XCTAssertTrue(coordinator.isGenerating, "Only the engine barrier makes a cancelled attempt terminal")
        XCTAssertNil(coordinator.lastCompletedOutput)

        barrier.finish(.success(()))
        await barrierTask.value
        XCTAssertEqual(barrier.callCount, 1)
        XCTAssertFalse(coordinator.isGenerating)
        XCTAssertNil(coordinator.activeAttempt)
        XCTAssertNil(coordinator.errorMessage)
        XCTAssertNil(coordinator.lastCompletedOutput)
        XCTAssertTrue(engine.completedResults.isEmpty)
    }

    func testCancellationAcceptedBeforeTheTaskIsCancelledDiscardsTheTake() async throws {
        let coordinator = StudioGenerationCoordinator(mode: .custom)
        let engine = FakeEngine()

        let plan = try makePlan()
        XCTAssertTrue(startTake(plan, on: coordinator, engine: engine))
        let task = try XCTUnwrap(coordinator.generationTask)
        await engine.waitUntilGenerating()
        // PA-15 order: the typed reason reaches the engine barrier before the
        // Swift task is cancelled, so only the accepted cancellation is visible.
        let attempt = try XCTUnwrap(coordinator.requestCancellation(cancelsTask: false))
        engine.finishGeneration(.success(engine.result))
        await task.value

        XCTAssertFalse(task.isCancelled)
        XCTAssertEqual(engine.events, [.submitted, .generated, .cancelled(materialized: true)])
        XCTAssertNil(coordinator.lastCompletedOutput)
        XCTAssertTrue(engine.completedResults.isEmpty)
        XCTAssertTrue(coordinator.isGenerating)
        XCTAssertTrue(coordinator.completeCancellation(attempt: attempt))
        XCTAssertFalse(coordinator.isGenerating)
    }

    func testAFailedCancellationBarrierEndsTheAttemptWithItsError() async throws {
        let coordinator = StudioGenerationCoordinator(mode: .clone)
        let engine = FakeEngine()
        let barrier = FakeBarrier()

        let plan = try makePlan()
        XCTAssertTrue(startTake(plan, on: coordinator, engine: engine))
        let task = try XCTUnwrap(coordinator.generationTask)
        await engine.waitUntilGenerating()
        barrier.finish(.failure(TestError.barrier))
        let cancellation = MacStudioSingleTakeRunner.cancel(
            coordinator: coordinator,
            stopLivePreview: {},
            barrier: { try await barrier.run() }
        )
        let barrierTask = try XCTUnwrap(cancellation)
        await barrierTask.value

        XCTAssertFalse(coordinator.isGenerating)
        XCTAssertEqual(coordinator.errorMessage?.contains("barrier did not finish"), true)

        // The engine's late answer can neither replace the barrier error nor publish a take.
        engine.finishGeneration(.failure(CancellationError()))
        await task.value
        XCTAssertEqual(engine.events, [.submitted, .generated, .cancelled(materialized: false)])
        XCTAssertEqual(coordinator.errorMessage?.contains("barrier did not finish"), true)
        XCTAssertNil(coordinator.lastCompletedOutput)
        XCTAssertTrue(engine.completedResults.isEmpty)
    }

    func testCancelWithoutARunningAttemptTouchesNothing() {
        let coordinator = StudioGenerationCoordinator(mode: .custom)
        var previewStops = 0

        let cancellation = MacStudioSingleTakeRunner.cancel(
            coordinator: coordinator,
            stopLivePreview: { previewStops += 1 },
            barrier: { XCTFail("No barrier runs without an attempt") }
        )
        XCTAssertNil(cancellation)
        XCTAssertEqual(previewStops, 0)
        XCTAssertNil(coordinator.errorMessage)
    }

    // MARK: - Clone priming

    func testOnDemandClonePrimingIsSkippedOnlyForTheExpectedPrimedReference() {
        let priming = MacStudioClonePriming(
            modelID: "clone-model",
            reference: CloneReference(audioPath: "/tmp/reference.wav", transcript: "Hello", preparedVoiceID: nil),
            expectedKey: "reference-a"
        )

        XCTAssertTrue(priming.isSatisfied(by: .primed(key: "reference-a")))
        XCTAssertFalse(priming.isSatisfied(by: .primed(key: "reference-b")))
        XCTAssertFalse(priming.isSatisfied(by: .preparing(key: "reference-a")))
        XCTAssertFalse(priming.isSatisfied(by: .failed(key: "reference-a", message: "busy")))
        XCTAssertFalse(priming.isSatisfied(by: .idle))
    }

    // MARK: - Fixtures

    private func startTake(
        _ plan: IOSSingleTakeGenerationPlan,
        on coordinator: StudioGenerationCoordinator,
        engine: FakeEngine
    ) -> Bool {
        MacStudioSingleTakeRunner.start(
            plan: plan,
            estimatedAudioDuration: 4,
            coordinator: coordinator,
            hooks: engine,
            onCompleted: { engine.completedResults.append($0) }
        )
    }

    private func makePlan() throws -> IOSSingleTakeGenerationPlan {
        try IOSSingleTakeGenerationPlan(
            request: MacStudioGenerationRequestFactory.customVoice(
                modelID: "custom-speed",
                text: "A quiet morning by the harbor.",
                outputPath: "/tmp/vocello-studio-runner-test.wav",
                language: .auto,
                speakerID: "aiden",
                deliveryStyle: nil,
                deliveryInstructionCellID: nil,
                seed: 41,
                variation: nil
            ),
            modelTier: "speed",
            historyVoice: "aiden",
            historyEmotion: nil,
            displayVoiceName: "Aiden",
            modeLabel: "Built-in",
            waveformSeed: 41,
            persistenceCaller: "MacStudioSingleTakeRunnerTests"
        )
    }

    /// The engine side of one take. `generate` suspends until the test
    /// finishes it (or returns an outcome finished before it was entered), and
    /// never observes task cancellation itself, so every ordering is explicit.
    @MainActor
    private final class FakeEngine: MacStudioSingleTakeHooks {
        enum Event: Equatable {
            case prepared
            case submitted
            case generated
            case completed
            case cancelled(materialized: Bool)
            case failed
        }

        let result = GenerationResult(
            audioPath: "/tmp/vocello-studio-runner-test.wav",
            durationSeconds: 1,
            streamSessionDirectory: nil,
            usedStreaming: true
        )
        var events: [Event] = []
        var completedResults: [GenerationResult] = []
        private(set) var requests: [GenerationRequest] = []
        private var isGenerating = false
        private var generatingWaiters: [CheckedContinuation<Void, Never>] = []
        private var generation: CheckedContinuation<GenerationResult, any Error>?
        private var finishedEarly: Result<GenerationResult, any Error>?

        func waitUntilGenerating() async {
            guard !isGenerating else { return }
            await withCheckedContinuation { generatingWaiters.append($0) }
        }

        func finishGeneration(_ outcome: Result<GenerationResult, any Error>) {
            if let generation {
                self.generation = nil
                generation.resume(with: outcome)
            } else {
                finishedEarly = outcome
            }
        }

        func generationSubmitted(_ plan: IOSSingleTakeGenerationPlan) async {
            events.append(.submitted)
        }

        func generate(_ request: GenerationRequest) async throws -> GenerationResult {
            requests.append(request)
            events.append(.generated)
            isGenerating = true
            let waiters = generatingWaiters
            generatingWaiters = []
            for waiter in waiters {
                waiter.resume()
            }
            if let finishedEarly {
                self.finishedEarly = nil
                return try finishedEarly.get()
            }
            return try await withCheckedThrowingContinuation { generation = $0 }
        }

        func generationCompleted(_ result: GenerationResult, plan: IOSSingleTakeGenerationPlan) async {
            events.append(.completed)
        }

        func generationCancelled(materializedResult: GenerationResult?, plan: IOSSingleTakeGenerationPlan) async {
            events.append(.cancelled(materialized: materializedResult != nil))
        }

        func generationFailed(_ plan: IOSSingleTakeGenerationPlan) async {
            events.append(.failed)
        }

        func inlinePlayerItem(for result: GenerationResult, plan: IOSSingleTakeGenerationPlan) -> IOSStudioInlinePlayerItem {
            IOSStudioInlinePlayerItem(
                generationID: plan.generationID,
                audioURL: URL(fileURLWithPath: result.audioPath),
                voiceName: plan.displayVoiceName,
                modeLabel: plan.modeLabel,
                mode: plan.request.mode,
                transcript: plan.request.text,
                waveformSeed: plan.waveformSeed,
                autoplay: false,
                ownedBySharedPlayer: true
            )
        }
    }

    /// The engine's cancellation barrier, finished by the test in either order.
    @MainActor
    private final class FakeBarrier {
        private(set) var callCount = 0
        private var waiter: CheckedContinuation<Void, any Error>?
        private var finishedEarly: Result<Void, any Error>?

        func run() async throws {
            callCount += 1
            if let finishedEarly {
                self.finishedEarly = nil
                return try finishedEarly.get()
            }
            try await withCheckedThrowingContinuation { waiter = $0 }
        }

        func finish(_ outcome: Result<Void, any Error>) {
            if let waiter {
                self.waiter = nil
                waiter.resume(with: outcome)
            } else {
                finishedEarly = outcome
            }
        }
    }
}
