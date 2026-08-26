import QwenVoiceCore
import XCTest

@MainActor
final class IOSSingleTakeGenerationExecutorTests: XCTestCase {
    private enum TestError: Error {
        case failed
    }

    private final class Hooks: IOSSingleTakeGenerationExecutionHooks {
        enum Event: Equatable {
            case submitted
            case generated
            case completed
            case cancelled(materialized: Bool)
            case failed
        }

        var events: [Event] = []
        var result = GenerationResult(
            audioPath: "/tmp/vocello-executor-test.wav",
            durationSeconds: 1,
            streamSessionDirectory: nil,
            usedStreaming: true
        )
        var generationError: Error?

        func generationSubmitted(_ plan: IOSSingleTakeGenerationPlan) async {
            events.append(.submitted)
        }

        func generate(_ request: GenerationRequest) async throws -> GenerationResult {
            events.append(.generated)
            if let generationError { throw generationError }
            return result
        }

        func generationCompleted(
            _ result: GenerationResult,
            plan: IOSSingleTakeGenerationPlan
        ) async {
            events.append(.completed)
        }

        func generationCancelled(
            materializedResult: GenerationResult?,
            plan: IOSSingleTakeGenerationPlan
        ) async {
            events.append(.cancelled(materialized: materializedResult != nil))
        }

        func generationFailed(_ plan: IOSSingleTakeGenerationPlan) async {
            events.append(.failed)
        }
    }

    func testPlanRequiresAppMintedGenerationIdentity() {
        XCTAssertThrowsError(
            try makePlan(generationID: nil)
        ) { error in
            XCTAssertEqual(
                error as? IOSSingleTakeGenerationPlan.ValidationError,
                .missingGenerationID
            )
        }
    }

    func testSuccessfulExecutionPreservesPlanAndOrdering() async throws {
        let plan = try makePlan()
        let hooks = Hooks()

        let result = try await IOSSingleTakeGenerationExecutor.run(
            plan: plan,
            hooks: hooks
        )

        XCTAssertEqual(result, hooks.result)
        XCTAssertEqual(plan.generationID, plan.request.generationID)
        XCTAssertEqual(plan.request.mode, .custom)
        XCTAssertEqual(plan.modelTier, "speed")
        XCTAssertEqual(hooks.events, [.submitted, .generated, .completed])
    }

    func testCancellationAfterMaterializedResultOwnsCleanupOnce() async throws {
        let plan = try makePlan()
        let hooks = Hooks()
        let task = Task { @MainActor in
            try await IOSSingleTakeGenerationExecutor.run(plan: plan, hooks: hooks)
        }
        task.cancel()

        do {
            _ = try await task.value
            XCTFail("Expected cancellation")
        } catch is CancellationError {
            XCTAssertEqual(
                hooks.events,
                [.submitted, .generated, .cancelled(materialized: true)]
            )
        }
    }

    func testWrappedEngineFailureOnCancelledTaskBecomesCancellation() async throws {
        let plan = try makePlan()
        let hooks = Hooks()
        hooks.generationError = TestError.failed
        let task = Task { @MainActor in
            try await IOSSingleTakeGenerationExecutor.run(plan: plan, hooks: hooks)
        }
        task.cancel()

        do {
            _ = try await task.value
            XCTFail("Expected cancellation")
        } catch is CancellationError {
            XCTAssertEqual(
                hooks.events,
                [.submitted, .generated, .cancelled(materialized: false)]
            )
        }
    }

    func testOrdinaryFailureRecordsFailureAndPropagates() async throws {
        let plan = try makePlan()
        let hooks = Hooks()
        hooks.generationError = TestError.failed

        do {
            _ = try await IOSSingleTakeGenerationExecutor.run(plan: plan, hooks: hooks)
            XCTFail("Expected failure")
        } catch TestError.failed {
            XCTAssertEqual(hooks.events, [.submitted, .generated, .failed])
        }
    }

    private func makePlan(
        generationID: UUID? = UUID(uuidString: "00000000-0000-0000-0000-000000000041")
    ) throws -> IOSSingleTakeGenerationPlan {
        try IOSSingleTakeGenerationPlan(
            request: GenerationRequest(
                mode: .custom,
                modelID: "model",
                text: "Test",
                outputPath: "/tmp/vocello-executor-test.wav",
                shouldStream: true,
                payload: .custom(speakerID: "aiden", deliveryStyle: nil),
                generationID: generationID,
                seed: 41
            ),
            modelTier: "speed",
            historyVoice: "aiden",
            historyEmotion: nil,
            displayVoiceName: "Aiden",
            modeLabel: "Built-in",
            waveformSeed: 41,
            persistenceCaller: "ExecutorTests"
        )
    }
}
