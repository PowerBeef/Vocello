import XCTest
import os
@testable import QwenVoiceCore
import VocelloQwen3Core

private final class TestLockedValue<Value: Sendable>: Sendable {
    private let storage = OSAllocatedUnfairLock<Value?>(initialState: nil)

    var value: Value? { storage.withLock { $0 } }

    func store(_ value: Value) {
        storage.withLock { $0 = value }
    }
}

private actor TestGenerationGate {
    private var isOpen = false
    private var waiters: [CheckedContinuation<Void, Never>] = []

    func wait() async {
        guard !isOpen else { return }
        await withCheckedContinuation { continuation in
            waiters.append(continuation)
        }
    }

    func open() {
        isOpen = true
        let pending = waiters
        waiters.removeAll()
        pending.forEach { $0.resume() }
    }
}

private enum TestMemoryPressureAction: Equatable, Sendable {
    case admissionClosed
    case observed(NativeMemoryTrimLevel)
    case cancellationRequested(GenerationCancellationReason)
    case workerTerminated
    case terminalBarrierPassed
    case modelOperationBarrierStarted
    case modelOperationsQuiesced
    case trimmed(NativeMemoryTrimLevel, String)
    case reliefPublished
    case operationAttempted(String)
    case operationEntered(String)
}

private actor TestMemoryPressureActionLog {
    private struct Waiter {
        let minimumCount: Int
        let continuation: CheckedContinuation<Void, Never>
    }

    private var actions: [TestMemoryPressureAction] = []
    private var waiters: [Waiter] = []

    func append(_ action: TestMemoryPressureAction) {
        actions.append(action)
        let ready = waiters.filter { actions.count >= $0.minimumCount }
        waiters.removeAll { actions.count >= $0.minimumCount }
        ready.forEach { $0.continuation.resume() }
    }

    func waitForCount(_ minimumCount: Int) async {
        guard actions.count < minimumCount else { return }
        await withCheckedContinuation { continuation in
            waiters.append(Waiter(minimumCount: minimumCount, continuation: continuation))
        }
    }

    func snapshot() -> [TestMemoryPressureAction] {
        actions
    }
}

final class ActiveGenerationCoordinatorTests: XCTestCase {
    func testCancellationIngressReplaysTypedReasonInstalledAfterRequest() throws {
        let ingress = GenerationCancellationIngress()
        let observed = TestLockedValue<GenerationCancellationReason>()

        XCTAssertTrue(ingress.request(.memoryPressure))
        XCTAssertFalse(ingress.request(.shutdown))
        ingress.install { reason in observed.store(reason) }

        XCTAssertEqual(ingress.reason, .memoryPressure)
        XCTAssertEqual(observed.value, .memoryPressure)
        XCTAssertThrowsError(try ingress.checkCancellation()) { error in
            XCTAssertTrue(error is CancellationError)
        }
    }

    func testCancellationIngressDeliversTypedReasonToInstalledHandler() {
        let ingress = GenerationCancellationIngress()
        let observed = TestLockedValue<GenerationCancellationReason>()
        ingress.install { reason in observed.store(reason) }

        XCTAssertTrue(ingress.request(.superseded))
        XCTAssertEqual(observed.value, .superseded)
    }

    func testCancellationRetainsOwnershipUntilTaskTerminates() async throws {
        let coordinator = ActiveGenerationCoordinator()
        let terminalGate = TestGenerationGate()
        let worker = Task {
            await terminalGate.wait()
        }
        let registration = try await coordinator.register(
            cancel: { _ in worker.cancel() },
            waitForTermination: { _ = await worker.result }
        )

        let cancellation = Task {
            await coordinator.cancelCurrent(reason: .memoryPressure)
        }

        for _ in 0..<100 {
            if await coordinator.currentCancellationReason != nil { break }
            await Task.yield()
        }
        let cancellationReason = await coordinator.currentCancellationReason
        let isActiveWhileCancelling = await coordinator.hasActiveGeneration
        XCTAssertEqual(cancellationReason, .memoryPressure)
        XCTAssertTrue(isActiveWhileCancelling)

        await terminalGate.open()
        await cancellation.value

        let isActiveAfterCancellation = await coordinator.hasActiveGeneration
        let reasonAfterCancellation = await coordinator.currentCancellationReason
        XCTAssertFalse(isActiveAfterCancellation)
        XCTAssertNil(reasonAfterCancellation)

        let terminalReason = await coordinator.finish(registration)
        XCTAssertEqual(terminalReason, .memoryPressure)
        let isActiveAfterFinish = await coordinator.hasActiveGeneration
        let reasonAfterFinish = await coordinator.currentCancellationReason
        XCTAssertFalse(isActiveAfterFinish)
        XCTAssertNil(reasonAfterFinish)
    }

    func testFinishPreservesEveryTypedReasonAcrossEarlyCancellation() async throws {
        let reasons: [GenerationCancellationReason] = [
            .memoryPressure,
            .superseded,
            .shutdown,
        ]

        for expectedReason in reasons {
            let coordinator = ActiveGenerationCoordinator()
            let terminalGate = TestGenerationGate()
            let worker = Task {
                await terminalGate.wait()
                try Task.checkCancellation()
            }
            let registration = try await coordinator.register(
                cancel: { _ in worker.cancel() },
                waitForTermination: { _ = await worker.result }
            )

            let cancellation = Task {
                await coordinator.cancelCurrent(reason: expectedReason)
            }
            for _ in 0..<100 {
                if await coordinator.currentCancellationReason != nil { break }
                await Task.yield()
            }

            await terminalGate.open()
            await cancellation.value

            let preservedReason = await coordinator.finish(registration)
            XCTAssertEqual(preservedReason, expectedReason)
            let reasonAfterFinish = await coordinator.currentCancellationReason
            XCTAssertNil(reasonAfterFinish)
        }
    }

    func testSecondGenerationIsRejectedWhileFirstOwnsEngine() async throws {
        let coordinator = ActiveGenerationCoordinator()
        let terminalGate = TestGenerationGate()
        let worker = Task {
            await terminalGate.wait()
        }
        let registration = try await coordinator.register(
            cancel: { _ in worker.cancel() },
            waitForTermination: { _ = await worker.result }
        )

        do {
            _ = try await coordinator.register(cancel: { _ in }, waitForTermination: {})
            XCTFail("A second generation must not acquire the engine")
        } catch let error as TTSEngineError {
            guard case .generationFailed = error else {
                return XCTFail("Unexpected error: \(error)")
            }
        }

        await terminalGate.open()
        _ = await worker.result
        await coordinator.finish(registration)
        let isActiveAfterFinish = await coordinator.hasActiveGeneration
        XCTAssertFalse(isActiveAfterFinish)
    }

    func testCriticalKernelPressureWaitsForTypedCancellationBarrierBeforeHardTrim() async throws {
        let coordinator = ActiveGenerationCoordinator()
        let terminalGate = TestGenerationGate()
        let actions = TestMemoryPressureActionLog()
        let worker = Task {
            await terminalGate.wait()
            await actions.append(.workerTerminated)
        }
        let registration = try await coordinator.register(
            cancel: { _ in worker.cancel() },
            waitForTermination: { _ = await worker.result }
        )
        let executor = NativeMemoryPressureResponseExecutor(
            recordObservation: { level in
                await actions.append(.observed(level))
            },
            cancelActiveGeneration: { reason in
                await actions.append(.cancellationRequested(reason))
                await coordinator.cancelCurrent(reason: reason)
                await actions.append(.terminalBarrierPassed)
            },
            trim: { level, reason in
                await actions.append(.trimmed(level, reason))
            },
            closeAdmissionForCriticalRelief: {
                await actions.append(.admissionClosed)
            },
            awaitModelOperationsQuiesced: {
                await actions.append(.modelOperationsQuiesced)
            },
            publishCriticalReliefCompletion: {
                await actions.append(.reliefPublished)
            }
        )

        let response = Task {
            await executor.execute(
                level: .hardTrim,
                reason: "test_kernel_pressure_hardTrim"
            )
        }

        await actions.waitForCount(3)
        let beforeTerminal = await actions.snapshot()
        XCTAssertEqual(
            beforeTerminal,
            [
                .admissionClosed,
                .observed(.hardTrim),
                .cancellationRequested(.memoryPressure),
            ]
        )
        XCTAssertFalse(
            beforeTerminal.contains {
                if case .trimmed(_, _) = $0 { return true }
                return false
            },
            "Hard trim must not run before the generation terminal barrier"
        )
        let activeBeforeTerminal = await coordinator.hasActiveGeneration
        XCTAssertTrue(activeBeforeTerminal)

        await terminalGate.open()
        await response.value

        let afterTerminal = await actions.snapshot()
        XCTAssertEqual(
            afterTerminal,
            [
                .admissionClosed,
                .observed(.hardTrim),
                .cancellationRequested(.memoryPressure),
                .workerTerminated,
                .terminalBarrierPassed,
                .modelOperationsQuiesced,
                .trimmed(.hardTrim, "test_kernel_pressure_hardTrim"),
                .reliefPublished,
            ]
        )
        let terminalReason = await coordinator.finish(registration)
        XCTAssertEqual(terminalReason, .memoryPressure)
    }

    func testFirstCancellationReasonWinsAcrossConcurrentRequests() async throws {
        let coordinator = ActiveGenerationCoordinator()
        let terminalGate = TestGenerationGate()
        let worker = Task {
            await terminalGate.wait()
            try Task.checkCancellation()
        }
        let registration = try await coordinator.register(
            cancel: { _ in worker.cancel() },
            waitForTermination: { _ = await worker.result }
        )

        let criticalCancellation = Task {
            await coordinator.cancelCurrent(reason: .memoryPressure)
        }
        for _ in 0..<100 {
            if await coordinator.currentCancellationReason == .memoryPressure { break }
            await Task.yield()
        }
        let firstReason = await coordinator.currentCancellationReason
        XCTAssertEqual(firstReason, .memoryPressure)

        let laterCancellation = Task {
            await coordinator.cancelCurrent(reason: .shutdown)
        }
        await Task.yield()
        let reasonAfterLaterRequest = await coordinator.currentCancellationReason
        XCTAssertEqual(
            reasonAfterLaterRequest,
            .memoryPressure,
            "A later cancellation request must not replace the first typed reason"
        )

        await terminalGate.open()
        await criticalCancellation.value
        await laterCancellation.value
        let terminalReason = await coordinator.finish(registration)
        XCTAssertEqual(terminalReason, .memoryPressure)
    }

    @MainActor
    func testCriticalReliefBlocksLoadPrewarmAndGenerationUntilPublication() async throws {
        let admission = CriticalMemoryReliefAdmission()
        let quiescenceGate = TestGenerationGate()
        let actions = TestMemoryPressureActionLog()
        let executor = NativeMemoryPressureResponseExecutor(
            recordObservation: { level in
                await actions.append(.observed(level))
            },
            cancelActiveGeneration: { reason in
                await actions.append(.cancellationRequested(reason))
            },
            trim: { level, reason in
                await actions.append(.trimmed(level, reason))
            },
            closeAdmissionForCriticalRelief: {
                await admission.close()
                await actions.append(.admissionClosed)
            },
            awaitModelOperationsQuiesced: {
                await actions.append(.modelOperationBarrierStarted)
                await quiescenceGate.wait()
                await actions.append(.modelOperationsQuiesced)
            },
            publishCriticalReliefCompletion: {
                await actions.append(.reliefPublished)
                await admission.reopen()
            }
        )

        let response = Task {
            await executor.execute(
                level: .hardTrim,
                reason: "test_continuous_critical_relief"
            )
        }
        await actions.waitForCount(4)

        let load = Task { @MainActor in
            await actions.append(.operationAttempted("load"))
            try await admission.waitUntilOpen()
            await actions.append(.operationEntered("load"))
        }
        let generation = Task { @MainActor in
            await actions.append(.operationAttempted("generation"))
            try await admission.waitUntilOpen()
            await actions.append(.operationEntered("generation"))
        }
        await actions.append(.operationAttempted("prewarm"))
        if admission.allowsProactiveOperation {
            await actions.append(.operationEntered("prewarm"))
        }

        await actions.waitForCount(7)
        let whileSuspended = await actions.snapshot()
        XCTAssertFalse(whileSuspended.contains(.operationEntered("load")))
        XCTAssertFalse(whileSuspended.contains(.operationEntered("generation")))
        XCTAssertFalse(whileSuspended.contains(.operationEntered("prewarm")))
        XCTAssertFalse(
            whileSuspended.contains {
                if case .trimmed = $0 { return true }
                return false
            }
        )

        await quiescenceGate.open()
        await response.value
        try await load.value
        try await generation.value

        let completed = await actions.snapshot()
        let publicationIndex = try XCTUnwrap(
            completed.firstIndex(of: .reliefPublished)
        )
        let loadIndex = try XCTUnwrap(
            completed.firstIndex(of: .operationEntered("load"))
        )
        let generationIndex = try XCTUnwrap(
            completed.firstIndex(of: .operationEntered("generation"))
        )
        XCTAssertLessThan(publicationIndex, loadIndex)
        XCTAssertLessThan(publicationIndex, generationIndex)
        XCTAssertFalse(completed.contains(.operationEntered("prewarm")))
    }

    func testPressureSnapshotSupportsConcurrentReadsAndTransitions() async {
        let state = NativeMemoryPressureSnapshotState()

        await withTaskGroup(of: Void.self) { group in
            for writer in 0..<8 {
                group.addTask {
                    for iteration in 0..<2_000 {
                        let value: NativeMemoryTrimLevel? = switch (writer + iteration) % 3 {
                        case 0: .softTrim
                        case 1: .hardTrim
                        default: nil
                        }
                        state.transition(to: value)
                    }
                }
            }
            for _ in 0..<8 {
                group.addTask {
                    for _ in 0..<4_000 {
                        _ = state.currentLevel
                    }
                }
            }
        }

        state.transition(to: .hardTrim)
        XCTAssertEqual(state.currentLevel, .hardTrim)
        XCTAssertEqual(state.transition(to: nil), .hardTrim)
        XCTAssertNil(state.currentLevel)
    }

    func testWarningKernelPressureSoftTrimsWithoutCancellingGeneration() async {
        let actions = TestMemoryPressureActionLog()
        let executor = NativeMemoryPressureResponseExecutor(
            recordObservation: { level in
                await actions.append(.observed(level))
            },
            cancelActiveGeneration: { reason in
                await actions.append(.cancellationRequested(reason))
            },
            trim: { level, reason in
                await actions.append(.trimmed(level, reason))
            },
            closeAdmissionForCriticalRelief: {
                await actions.append(.admissionClosed)
            },
            awaitModelOperationsQuiesced: {
                await actions.append(.modelOperationsQuiesced)
            },
            publishCriticalReliefCompletion: {
                await actions.append(.reliefPublished)
            }
        )

        await executor.execute(
            level: .softTrim,
            reason: "test_kernel_pressure_softTrim"
        )

        let recorded = await actions.snapshot()
        XCTAssertEqual(
            recorded,
            [
                .observed(.softTrim),
                .trimmed(.softTrim, "test_kernel_pressure_softTrim"),
            ]
        )
    }

    /// PA-22 / CORE-06: reliefs can overlap (a caller's full unload during a
    /// kernel critical trim). Admission resumes only when the last holder
    /// reopens, so one relief finishing never readmits work under another.
    @MainActor
    func testReliefAdmissionReopensOnlyAfterEveryHolderReleases() async throws {
        let admission = CriticalMemoryReliefAdmission()
        admission.close()
        admission.close()
        let entered = TestLockedValue<Bool>()
        let waiter = Task { @MainActor in
            try await admission.waitUntilOpen()
            entered.store(true)
        }
        for _ in 0..<20 { await Task.yield() }

        admission.reopen()
        for _ in 0..<20 { await Task.yield() }
        XCTAssertTrue(admission.isClosed)
        XCTAssertFalse(admission.allowsProactiveOperation)
        XCTAssertNil(entered.value)

        admission.reopen()
        try await waiter.value
        XCTAssertFalse(admission.isClosed)
        XCTAssertEqual(entered.value, true)

        // An unpaired reopen cannot drive the count below zero.
        admission.reopen()
        admission.close()
        XCTAssertTrue(admission.isClosed)
        admission.reopen()
        XCTAssertFalse(admission.isClosed)
    }

    /// PA-22 / CORE-06: a caller's full unload (iOS memory policy) used to run
    /// while a proactive load was suspended in the model loader; the load then
    /// published its model after the unload. The trim now closes admission and
    /// waits out the in-flight operation before it unloads.
    @MainActor
    func testCallerFullUnloadWaitsForInFlightProactiveLoad() async throws {
        let root = FileManager.default.temporaryDirectory
            .appendingPathComponent("vocello-relief-gate-\(UUID().uuidString)", isDirectory: true)
        defer { try? FileManager.default.removeItem(at: root) }
        let repositoryRoot = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .deletingLastPathComponent()
        let registry = try ContractBackedModelRegistry(
            manifestURL: repositoryRoot.appendingPathComponent("Sources/Resources/qwenvoice_contract.json")
        )
        let coordinator = SuspendingLoadCoordinator()
        let engine = MLXTTSEngine(
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
                fatalError("This test never starts a generation.")
            }
        )

        let load = Task { @MainActor in
            await engine.ensureModelLoadedIfNeeded(id: "relief-fixture-model")
        }
        await coordinator.waitUntilLoadBegins()
        let trim = Task { @MainActor in
            await engine.trimMemory(level: .fullUnload, reason: "test_caller_full_unload")
        }
        for _ in 0..<50 { await Task.yield() }
        try await Task.sleep(nanoseconds: 50_000_000)
        let whileLoading = await coordinator.events
        XCTAssertEqual(whileLoading, ["load-begin"], "a full unload must not run under a suspended load")

        await coordinator.releaseLoad()
        await load.value
        await trim.value

        let events = await coordinator.events
        let loadEnd = try XCTUnwrap(events.firstIndex(of: "load-end"))
        let firstUnload = try XCTUnwrap(events.firstIndex(of: "unload"))
        XCTAssertLessThan(loadEnd, firstUnload)
        XCTAssertEqual(events.last, "unload")
        XCTAssertEqual(engine.loadState, .idle)
    }

    func testModelLoadEpochAdvancesOnEveryUnload() {
        var epoch = ModelLoadEpoch()
        let started = epoch
        XCTAssertEqual(epoch, started)
        epoch.advance()
        XCTAssertNotEqual(epoch, started, "a load that started before an unload must not publish")
        let restarted = epoch
        epoch.advance()
        XCTAssertNotEqual(epoch, restarted)
    }

    /// PA-22 / CORE-06: closing admission for a caller's hard trim cancels the
    /// pending idle unload, and `generate` schedules idle unload before the
    /// store's post-generation hard trim, so the model stayed resident for good.
    /// A relief that leaves the model loaded now schedules its idle unload again.
    @MainActor
    func testIdleUnloadSurvivesACallerHardTrim() async throws {
        let root = FileManager.default.temporaryDirectory
            .appendingPathComponent("vocello-idle-after-trim-\(UUID().uuidString)", isDirectory: true)
        defer { try? FileManager.default.removeItem(at: root) }
        let registry = try Self.contractRegistry()
        let model = try XCTUnwrap(registry.models.first)
        guard NativeMemoryPolicyResolver.policy(mode: model.mode, isBatch: false)
            .unloadAfterIdleSeconds != nil else {
            throw XCTSkip("This host's memory tier never idle-unloads a model.")
        }
        let coordinator = ResidentLoadCoordinator()
        let engine = Self.makeFixtureEngine(
            root: root,
            registry: registry,
            coordinator: coordinator,
            idleUnloadDelay: 0.5
        )

        await engine.ensureModelLoadedIfNeeded(id: model.id)
        XCTAssertEqual(engine.loadState, .loaded(modelID: model.id))
        await engine.trimMemory(level: .hardTrim, reason: "test_post_generation_hard_trim")
        XCTAssertEqual(engine.loadState, .loaded(modelID: model.id), "a hard trim keeps the model")

        let deadline = ContinuousClock.now + .seconds(10)
        while engine.loadState != .idle, ContinuousClock.now < deadline {
            try await Task.sleep(nanoseconds: 50_000_000)
        }
        XCTAssertEqual(engine.loadState, .idle, "idle unload must still run after the hard trim")
        let events = await coordinator.events
        XCTAssertEqual(events.filter { $0 == "unload" }.count, 1)
    }

    /// PA-22 / CORE-06: a load an unload superseded throws a raw cancellation
    /// from the coordinator (the load epoch), which the runtime wraps. The engine
    /// used to surface that as a failed load; it now settles quietly.
    @MainActor
    func testEpochCancelledLoadSettlesWithoutAVisibleFailure() async throws {
        let wrapped = NativeRuntimeError.wrapping(
            CancellationError(),
            stage: .upstreamModelLoad,
            message: "The native runtime could not load model 'fixture'"
        )
        XCTAssertTrue(MLXTTSEngine.isModelOperationCancellation(wrapped))
        XCTAssertTrue(MLXTTSEngine.isModelOperationCancellation(CancellationError()))
        XCTAssertFalse(MLXTTSEngine.isModelOperationCancellation(
            NativeRuntimeError.wrapping(
                CocoaError(.fileReadCorruptFile),
                stage: .upstreamModelLoad,
                message: "fixture"
            )
        ))

        let root = FileManager.default.temporaryDirectory
            .appendingPathComponent("vocello-epoch-cancel-\(UUID().uuidString)", isDirectory: true)
        defer { try? FileManager.default.removeItem(at: root) }
        let engine = Self.makeFixtureEngine(
            root: root,
            registry: try Self.contractRegistry(),
            coordinator: SupersededLoadCoordinator(),
            idleUnloadDelay: nil
        )

        await engine.ensureModelLoadedIfNeeded(id: "superseded-fixture-model")
        XCTAssertEqual(engine.loadState, .idle)
        XCTAssertNil(engine.visibleErrorMessage)
    }

    private static func contractRegistry() throws -> ContractBackedModelRegistry {
        let repositoryRoot = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .deletingLastPathComponent()
        return try ContractBackedModelRegistry(
            manifestURL: repositoryRoot.appendingPathComponent("Sources/Resources/qwenvoice_contract.json")
        )
    }

    @MainActor
    private static func makeFixtureEngine(
        root: URL,
        registry: ContractBackedModelRegistry,
        coordinator: any MLXModelCoordinating,
        idleUnloadDelay: Double?
    ) -> MLXTTSEngine {
        MLXTTSEngine(
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
                fatalError("This test never starts a generation.")
            },
            idleUnloadDelayOverride: idleUnloadDelay,
            // Stay off MLX: this bundle runs under the ThreadSanitizer lane.
            allocatorControl: .inert
        )
    }
}

/// A model coordinator whose load always ends the way a load an unload
/// superseded ends: the coordinator's epoch guard throws a raw cancellation.
private actor SupersededLoadCoordinator: MLXModelCoordinating {
    func qwen3Capabilities(for id: String) async throws -> Qwen3TTSModelCapabilities {
        throw CancellationError()
    }

    func loadModel(
        id: String,
        capabilityProfile: NativeLoadCapabilityProfile
    ) async throws -> NativeModelLoadResult {
        throw CancellationError()
    }

    func unloadModel() async {}
    func isPrewarmed(identityKey: String) async -> Bool { false }
    func markPrewarmed(identityKey: String) async {}
    func clearPrewarmState() async {}
    func setTelemetryRecorder(_ recorder: NativeTelemetryRecorder?) async {}
    func requiresUnloadAfterRuntimeFailure() async -> Bool { false }
}

/// A model coordinator whose load succeeds with an unloaded runtime actor, so
/// the engine's resident-model lifecycle (idle unload, trims) is observable
/// without MLX weights. The model is never used to generate.
private actor ResidentLoadCoordinator: MLXModelCoordinating {
    private(set) var events: [String] = []

    func qwen3Capabilities(for id: String) async throws -> Qwen3TTSModelCapabilities {
        Self.capabilities
    }

    func loadModel(
        id: String,
        capabilityProfile: NativeLoadCapabilityProfile
    ) async throws -> NativeModelLoadResult {
        events.append("load")
        let facts = VocelloQwen3LoadedModelFacts(
            identity: VocelloQwen3ModelIdentity(
                modelID: id,
                repositoryID: "fixture/repository",
                revision: "fixture",
                artifactVersion: "fixture"
            ),
            sampleRate: 24_000,
            capabilities: VocelloQwen3CapabilitySet([VocelloQwen3Capability]()),
            loadDiagnostics: VocelloQwen3RuntimeDiagnosticsSnapshot()
        )
        return NativeModelLoadResult(
            model: UnsafeSpeechGenerationModel(engine: VocelloQwen3Engine(), facts: facts),
            modelRuntimeIdentity: ModelRuntimeIdentity(resolvedModelID: id),
            didLoad: true,
            capabilityProfile: capabilityProfile,
            qwen3Capabilities: Self.capabilities,
            timingsMS: [:],
            booleanFlags: [:],
            stringFlags: [:]
        )
    }

    func unloadModel() async {
        events.append("unload")
    }

    func isPrewarmed(identityKey: String) async -> Bool { false }
    func markPrewarmed(identityKey: String) async {}
    func clearPrewarmState() async {}
    func setTelemetryRecorder(_ recorder: NativeTelemetryRecorder?) async {}
    func requiresUnloadAfterRuntimeFailure() async -> Bool { false }

    private static let capabilities = Qwen3TTSModelCapabilities(
        modelSize: .pro1b7,
        familyType: .customVoice,
        supportsInstructionControl: true,
        supportsVoiceClone: false,
        supportsXVectorOnlyClone: false,
        requiresSpeakerEncoder: false,
        tokenizerProfile: Qwen3TTSTokenizerProfile(
            name: "qwen3",
            sampleRateHz: 24_000,
            frameRateHz: 12.5,
            decoderQuantizers: 16,
            encoderValidQuantizers: 8,
            encoderConfiguredQuantizers: 8,
            codebookSize: 2_048,
            semanticCodebookSize: 4_096
        ),
        generationDefaults: Qwen3TTSGenerationDefaultsProfile(
            checkpointMaxNewTokens: nil,
            wrapperFallbackMaxNewTokens: 2_048,
            appPolicyMaxNewTokens: 2_048,
            temperature: 0.9,
            topP: 1,
            topK: 50,
            doSample: true,
            repetitionPenalty: 1.05,
            source: .appPolicy
        ),
        artifactAvailability: .publicArtifact
    )
}

/// A model coordinator whose load suspends until the test releases it, then
/// fails, so the relief ordering is observable without MLX weights.
private actor SuspendingLoadCoordinator: MLXModelCoordinating {
    private struct FixtureLoadError: Error {}

    private(set) var events: [String] = []
    private let loadGate = TestGenerationGate()
    private var loadBeganWaiters: [CheckedContinuation<Void, Never>] = []

    func waitUntilLoadBegins() async {
        guard !events.contains("load-begin") else { return }
        await withCheckedContinuation { continuation in
            loadBeganWaiters.append(continuation)
        }
    }

    func releaseLoad() async {
        await loadGate.open()
    }

    func qwen3Capabilities(for id: String) async throws -> Qwen3TTSModelCapabilities {
        throw FixtureLoadError()
    }

    func loadModel(
        id: String,
        capabilityProfile: NativeLoadCapabilityProfile
    ) async throws -> NativeModelLoadResult {
        events.append("load-begin")
        let waiters = loadBeganWaiters
        loadBeganWaiters.removeAll()
        waiters.forEach { $0.resume() }
        await loadGate.wait()
        events.append("load-end")
        throw FixtureLoadError()
    }

    func unloadModel() async {
        events.append("unload")
    }

    func isPrewarmed(identityKey: String) async -> Bool { false }
    func markPrewarmed(identityKey: String) async {}
    func clearPrewarmState() async {}
    func setTelemetryRecorder(_ recorder: NativeTelemetryRecorder?) async {}
    func requiresUnloadAfterRuntimeFailure() async -> Bool { false }
}
