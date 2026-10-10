import Foundation
import XCTest
@testable import QwenVoiceCore
import VocelloQwen3Core

/// PA-15 / DA-09 (E7-03): the foreground exit's `.shutdown` must reach the
/// engine's terminal cancellation summary. These tests drive a real
/// `MLXTTSEngine.generate`: the take registers with the engine's
/// `ActiveGenerationCoordinator`, then waits behind a proactive load that a
/// fixture coordinator holds. Cancelling it exercises the engine's own wiring
/// (the registered cancel closure, the caller's cancellation handler,
/// `ingress.reason ?? coordinatorReason` and the terminal emission) without
/// loading weights or touching MLX. The adapter's share of the same wiring
/// (the task's `.user` loses to a typed reason recorded first) is pinned by
/// `GenerationOutputAdapterChoreographyTests`.
final class IOSShutdownCancellationReasonTests: XCTestCase {
    @MainActor
    func testEveryTypedBarrierReasonReachesTheTerminalSummary() async throws {
        for reason: GenerationCancellationReason in [.shutdown, .memoryPressure, .superseded] {
            let outcome = try await runHeldTake { engine, _ in
                try await engine.cancelActiveGeneration(reason: reason)
            }
            XCTAssertTrue(outcome.error is CancellationError, "\(reason): \(String(describing: outcome.error))")
            XCTAssertEqual(outcome.terminal, outcome.cancelled(reason), "\(reason)")
        }
    }

    @MainActor
    func testShutdownReachesTheTerminalReasonWhenTheBarrierRunsFirst() async throws {
        let order = IOSStudioCancellationOrder.forReason(.shutdown)
        XCTAssertEqual(order, .barrierThenTask)
        let outcome = try await runHeldTake { engine, take in
            try await Self.cancel(engine, take: take, order: order, reason: .shutdown)
        }
        XCTAssertTrue(outcome.error is CancellationError)
        XCTAssertEqual(outcome.terminal, outcome.cancelled(.shutdown))
    }

    @MainActor
    func testSettledCallerCancellationKeepsUserWhenShutdownArrivesLater() async throws {
        // Registration can precede installation of the caller's cancellation
        // handler. Join the cancelled take to prove .user was processed before
        // issuing shutdown; task scheduling alone cannot establish that order.
        let outcome = try await runHeldTake { engine, take in
            take.cancel()
            _ = await take.value
            try await engine.cancelActiveGeneration(reason: .shutdown)
        }
        XCTAssertTrue(outcome.error is CancellationError)
        XCTAssertEqual(outcome.terminal, outcome.cancelled(.user))
    }

    @MainActor
    func testUserStopStillReportsUser() async throws {
        let order = IOSStudioCancellationOrder.forReason(.user)
        XCTAssertEqual(order, .taskThenBarrier)
        let outcome = try await runHeldTake { engine, take in
            try await Self.cancel(engine, take: take, order: order, reason: .user)
        }
        XCTAssertEqual(outcome.terminal, outcome.cancelled(.user))
    }

    @MainActor
    func testCancellingOnlyTheCallerFallsBackToUser() async throws {
        let outcome = try await runHeldTake { _, take in
            take.cancel()
        }
        XCTAssertTrue(outcome.error is CancellationError)
        XCTAssertEqual(outcome.terminal, outcome.cancelled(.user))
    }

    /// A take refused at admission (another take owns the engine) still ends
    /// its own event stream with exactly one `.failed` terminal.
    @MainActor
    func testASecondTakeIsRefusedWithAFailedTerminal() async throws {
        let outcome = try await runHeldTake { engine, take in
            let secondID = UUID()
            let secondTerminal = Self.firstTerminal(of: engine.events(for: secondID))
            do {
                _ = try await engine.generate(Self.request(secondID))
                XCTFail("A second take must be refused while the first owns the engine")
            } catch let error as TTSEngineError {
                guard case .generationFailed = error else {
                    return XCTFail("Unexpected refusal: \(error)")
                }
            }
            let refused = await secondTerminal.value
            guard case .failed = refused else {
                return XCTFail("The refused take must end with .failed, got \(String(describing: refused))")
            }
            take.cancel()
        }
        XCTAssertEqual(outcome.terminal, outcome.cancelled(.user), "the first take is unaffected")
    }

    /// A non-cancellation failure before the runtime yields any event takes
    /// the outer terminal path: one `.failed`, never `.cancelled`.
    @MainActor
    func testATakeOnAnUninitializedEngineEndsWithOneFailedTerminal() async throws {
        let root = Self.temporaryRoot()
        defer { try? FileManager.default.removeItem(at: root) }
        let engine = try Self.makeEngine(root: root, coordinator: HeldLoadCoordinator())
        defer { engine.stop() }
        let generationID = UUID()
        let terminal = Self.firstTerminal(of: engine.events(for: generationID))

        do {
            _ = try await engine.generate(Self.request(generationID))
            XCTFail("An uninitialized engine must refuse the take")
        } catch let error as MLXTTSEngineError {
            guard case .notInitialized = error else {
                return XCTFail("Unexpected error: \(error)")
            }
        }

        let event = await terminal.value
        guard case .failed = event else {
            return XCTFail("Expected one .failed terminal, got \(String(describing: event))")
        }
        XCTAssertEqual(engine.loadState, .idle)
    }

    // MARK: - Harness

    private struct HeldTakeOutcome {
        let generationID: UUID
        let error: (any Error)?
        let terminal: GenerationEvent?

        func cancelled(_ reason: GenerationCancellationReason) -> GenerationEvent {
            .cancelled(GenerationCancellationSummary(generationID: generationID, reason: reason))
        }
    }

    /// Starts one take that registers and then waits behind a held proactive
    /// load, applies `cancel`, and returns how the take ended.
    @MainActor
    private func runHeldTake(
        _ cancel: @MainActor (MLXTTSEngine, Task<(any Error)?, Never>) async throws -> Void
    ) async throws -> HeldTakeOutcome {
        let root = Self.temporaryRoot()
        defer { try? FileManager.default.removeItem(at: root) }
        let coordinator = HeldLoadCoordinator()
        let engine = try Self.makeEngine(root: root, coordinator: coordinator)
        defer { engine.stop() }

        let load = Task { @MainActor in
            await engine.ensureModelLoadedIfNeeded(id: "held-fixture-model")
        }
        await coordinator.waitUntilLoadBegins()

        let generationID = UUID()
        let terminal = Self.firstTerminal(of: engine.events(for: generationID))
        let take = Task { @MainActor () -> (any Error)? in
            do {
                _ = try await engine.generate(Self.request(generationID))
                return nil
            } catch {
                return error
            }
        }
        try await Self.waitUntilRegistered(engine)
        try await cancel(engine, take)
        let error = await take.value
        let event = await terminal.value

        await coordinator.releaseLoad()
        await load.value
        return HeldTakeOutcome(generationID: generationID, error: error, terminal: event)
    }

    /// The store's two cancellation orders (`IOSStudioCancellationOrder`).
    @MainActor
    private static func cancel(
        _ engine: MLXTTSEngine,
        take: Task<(any Error)?, Never>,
        order: IOSStudioCancellationOrder,
        reason: GenerationCancellationReason
    ) async throws {
        switch order {
        case .taskThenBarrier:
            take.cancel()
            try await engine.cancelActiveGeneration(reason: reason)
        case .barrierThenTask:
            try await engine.cancelActiveGeneration(reason: reason)
            take.cancel()
        }
    }

    @MainActor
    private static func waitUntilRegistered(_ engine: MLXTTSEngine) async throws {
        let deadline = ContinuousClock.now + .seconds(10)
        while ContinuousClock.now < deadline {
            if await engine.startupReliabilityRuntimeOwnershipSnapshot().generationReservationInFlight {
                return
            }
            await Task.yield()
        }
        XCTFail("The take never registered with the engine")
    }

    private static func firstTerminal(
        of events: AsyncStream<GenerationEvent>
    ) -> Task<GenerationEvent?, Never> {
        Task {
            for await event in events {
                switch event {
                case .completed, .cancelled, .failed:
                    return event
                case .progress, .chunk:
                    continue
                }
            }
            return nil
        }
    }

    private static func request(_ generationID: UUID) -> GenerationRequest {
        GenerationRequest(
            mode: .custom,
            modelID: "pro_custom",
            text: "Hello.",
            outputPath: "",
            shouldStream: false,
            payload: .custom(
                speakerID: GenerationSemantics.canonicalCustomWarmSpeaker,
                deliveryStyle: nil
            )
        ).withGenerationID(generationID)
    }

    private static func temporaryRoot() -> URL {
        FileManager.default.temporaryDirectory
            .appendingPathComponent("vocello-pa15-\(UUID().uuidString)", isDirectory: true)
    }

    @MainActor
    private static func makeEngine(
        root: URL,
        coordinator: any MLXModelCoordinating
    ) throws -> MLXTTSEngine {
        let repositoryRoot = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .deletingLastPathComponent()
        let registry = try ContractBackedModelRegistry(
            manifestURL: repositoryRoot.appendingPathComponent("Sources/Resources/qwenvoice_contract.json")
        )
        return MLXTTSEngine(
            modelRegistry: registry,
            modelAssetStore: LocalModelAssetStore(
                rootDirectory: root.appendingPathComponent("models", isDirectory: true),
                descriptors: []
            ),
            audioPreparationService: NativeAudioPreparationService(),
            documentIO: LocalDocumentIO(
                importedReferenceDirectory: root.appendingPathComponent("imported", isDirectory: true)
            ),
            streamSessionsDirectory: root.appendingPathComponent("streams", isDirectory: true),
            loadCoordinator: coordinator,
            streamingSessionFactory: { _, _, _, _, _, _, _, _, _, _, _, _, _, _, _, _, _, _, _, _, _ in
                fatalError("These takes end before the runtime prepares them.")
            },
            // Stay off MLX: this bundle runs under the ThreadSanitizer lane.
            allocatorControl: .inert
        )
    }
}

/// A model coordinator whose load suspends until the test releases it and
/// then ends as a load an unload superseded does, so the proactive load owns
/// the engine's model operation for as long as a test needs it.
private actor HeldLoadCoordinator: MLXModelCoordinating {
    private var loadBegan = false
    private var loadBeganWaiters: [CheckedContinuation<Void, Never>] = []
    private var released = false
    private var releaseWaiters: [CheckedContinuation<Void, Never>] = []

    func waitUntilLoadBegins() async {
        guard !loadBegan else { return }
        await withCheckedContinuation { continuation in
            loadBeganWaiters.append(continuation)
        }
    }

    func releaseLoad() {
        released = true
        let waiters = releaseWaiters
        releaseWaiters.removeAll()
        waiters.forEach { $0.resume() }
    }

    func qwen3Capabilities(for id: String) async throws -> Qwen3TTSModelCapabilities {
        throw CancellationError()
    }

    func loadModel(
        id: String,
        capabilityProfile: NativeLoadCapabilityProfile
    ) async throws -> NativeModelLoadResult {
        loadBegan = true
        let waiters = loadBeganWaiters
        loadBeganWaiters.removeAll()
        waiters.forEach { $0.resume() }
        if !released {
            await withCheckedContinuation { continuation in
                releaseWaiters.append(continuation)
            }
        }
        throw CancellationError()
    }

    func unloadModel() async {}
    func isPrewarmed(identityKey: String) async -> Bool { false }
    func markPrewarmed(identityKey: String) async {}
    func clearPrewarmState() async {}
    func setTelemetryRecorder(_ recorder: NativeTelemetryRecorder?) async {}
    func requiresUnloadAfterRuntimeFailure() async -> Bool { false }
}
