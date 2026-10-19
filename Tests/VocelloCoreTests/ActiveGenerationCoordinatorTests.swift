import Combine
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

private final class TestCallLog: Sendable {
    private let storage = OSAllocatedUnfairLock<[String]>(initialState: [])

    var entries: [String] { storage.withLock { $0 } }

    func append(_ entry: String) {
        storage.withLock { $0.append(entry) }
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

private extension GenerationTaskStartGate {
    /// The acknowledgement and wait share the gate actor, so a later read of
    /// pendingWaiterCount observes the waiter after it suspended at the barrier.
    func wait(entered: XCTestExpectation) async {
        entered.fulfill()
        await wait()
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
        let cancellationRequested = expectation(description: "typed cancellation reached the worker")
        let worker = Task {
            await terminalGate.wait()
        }
        let registration = try await coordinator.register(
            cancel: { _ in
                worker.cancel()
                cancellationRequested.fulfill()
            },
            waitForTermination: { _ = await worker.result }
        )

        let cancellation = Task {
            await coordinator.cancelCurrent(reason: .memoryPressure)
        }

        await fulfillment(of: [cancellationRequested], timeout: 5)
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
            let cancellationRequested = expectation(description: "worker received \(expectedReason)")
            let worker = Task {
                await terminalGate.wait()
                try Task.checkCancellation()
            }
            let registration = try await coordinator.register(
                cancel: { _ in
                    worker.cancel()
                    cancellationRequested.fulfill()
                },
                waitForTermination: { _ = await worker.result }
            )

            let cancellation = Task {
                await coordinator.cancelCurrent(reason: expectedReason)
            }
            await fulfillment(of: [cancellationRequested], timeout: 5)

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
        let cancellationRequested = expectation(description: "first cancellation reached the worker")
        let terminalWaitsEntered = expectation(description: "both cancellation requests joined termination")
        terminalWaitsEntered.expectedFulfillmentCount = 2
        let worker = Task {
            await terminalGate.wait()
            try Task.checkCancellation()
        }
        let registration = try await coordinator.register(
            cancel: { _ in
                worker.cancel()
                cancellationRequested.fulfill()
            },
            waitForTermination: {
                terminalWaitsEntered.fulfill()
                _ = await worker.result
            }
        )

        let criticalCancellation = Task {
            await coordinator.cancelCurrent(reason: .memoryPressure)
        }
        await fulfillment(of: [cancellationRequested], timeout: 5)
        let firstReason = await coordinator.currentCancellationReason
        XCTAssertEqual(firstReason, .memoryPressure)

        let laterCancellation = Task {
            await coordinator.cancelCurrent(reason: .shutdown)
        }
        await fulfillment(of: [terminalWaitsEntered], timeout: 5)
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

    /// DA-09: the kernel monitor maps each callback to one trim level, lets
    /// critical win over warning, emits only on a change, never emits for
    /// relief, and `stop()` finishes the stream the engine iterates.
    func testKernelPressureCallbacksEmitTrimLevelsOnlyOnChange() async {
        let monitor = NativeMemoryPressureMonitor(label: "test.memory-pressure")
        monitor.handle(event: [.warning, .critical])
        XCTAssertEqual(monitor.currentLevel, .hardTrim, "critical wins in a combined callback")
        monitor.handle(event: .critical)
        monitor.handle(event: .normal)
        XCTAssertNil(monitor.currentLevel, "relief clears the level")
        monitor.handle(event: .critical)
        monitor.handle(event: .warning)
        XCTAssertEqual(monitor.currentLevel, .softTrim)
        monitor.stop()

        var emitted: [NativeMemoryTrimLevel] = []
        for await level in monitor.events {
            emitted.append(level)
        }
        XCTAssertEqual(emitted, [.hardTrim, .hardTrim, .softTrim])
    }

    /// DA-09: the runtime's caller trims, observed through a recording
    /// allocator: a soft trim clears the buffer cache only, a hard trim also
    /// drops prewarm state, and a full unload releases through the coordinator.
    /// The runtime's default clone-conditioning cache clears through the same
    /// allocator, so each level records the cache's clear before its own.
    func testRuntimeTrimLevelsDriveTheAllocatorAndTheModelCoordinator() async {
        let allocator = TestCallLog()
        let coordinator = TrimRecordingCoordinator()
        let runtime = NativeEngineRuntime(
            loadCoordinator: coordinator,
            audioPreparationService: NativeAudioPreparationService(),
            lightweightWarmupText: "Hi.",
            allocatorControl: NativeMLXAllocatorControl(
                applyPolicy: { _ in allocator.append("applyPolicy") },
                clearCache: { allocator.append("clearCache") }
            )
        )

        await runtime.trimMemory(level: .softTrim, reason: "test_soft_trim")
        XCTAssertEqual(allocator.entries.count, 2, "the cache's soft trim, then the runtime's clear")
        XCTAssertEqual(Set(allocator.entries), ["clearCache"], "a trim never applies a policy")
        let afterSoftTrim = await coordinator.events
        XCTAssertEqual(afterSoftTrim, [], "a soft trim keeps prewarm state and the model")

        await runtime.trimMemory(level: .hardTrim, reason: "test_hard_trim")
        XCTAssertEqual(allocator.entries.count, 4, "the cache's full clear, then the runtime's clear")
        let afterHardTrim = await coordinator.events
        XCTAssertEqual(afterHardTrim, ["clearPrewarmState"], "a hard trim keeps the model")

        await runtime.trimMemory(level: .fullUnload, reason: "test_full_unload")
        XCTAssertEqual(allocator.entries.count, 5, "the unload clears the clone state, and so the cache, once")
        XCTAssertEqual(Set(allocator.entries), ["clearCache"])
        let afterFullUnload = await coordinator.events
        XCTAssertEqual(afterFullUnload, ["clearPrewarmState", "unload"])
        let loadedModelID = await runtime.loadedModelID()
        XCTAssertNil(loadedModelID)
    }

    /// DA-09: `MLXTTSEngine.generate` holds its task behind this gate until
    /// the coordinator has registered it; no waiter may pass a closed gate.
    func testGenerationTaskStartGateHoldsEveryWaiterUntilOpened() async {
        let gate = GenerationTaskStartGate()
        let passed = TestCallLog()
        let firstEntered = expectation(description: "first task entered the start gate")
        let secondEntered = expectation(description: "second task entered the start gate")
        let first = Task {
            await gate.wait(entered: firstEntered)
            passed.append("first")
        }
        let second = Task {
            await gate.wait(entered: secondEntered)
            passed.append("second")
        }
        await fulfillment(of: [firstEntered, secondEntered], timeout: 5)
        let blocked = await gate.pendingWaiterCount
        XCTAssertEqual(blocked, 2, "both tasks reached and remain suspended at the closed barrier")
        XCTAssertEqual(passed.entries, [], "no waiter passes a closed gate")

        await gate.open()
        await first.value
        await second.value
        XCTAssertEqual(Set(passed.entries), ["first", "second"])
        let settled = await gate.pendingWaiterCount
        XCTAssertEqual(settled, 0)

        // Opening again is harmless, and an open gate admits at once.
        await gate.open()
        await gate.wait()
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
        let waiterEntered = expectation(description: "waiter entered relief admission")
        let waiter = Task { @MainActor in
            waiterEntered.fulfill()
            try await admission.waitUntilOpen()
            entered.store(true)
        }
        await fulfillment(of: [waiterEntered], timeout: 5)
        XCTAssertEqual(admission.pendingWaiterCount, 1)

        admission.reopen()
        XCTAssertEqual(admission.pendingWaiterCount, 1, "one relief holder still owns the blocked waiter")
        XCTAssertTrue(admission.isClosed)
        XCTAssertFalse(admission.allowsProactiveOperation)
        XCTAssertNil(entered.value)

        admission.reopen()
        try await waiter.value
        XCTAssertFalse(admission.isClosed)
        XCTAssertEqual(admission.pendingWaiterCount, 0)
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
        let trimEntered = expectation(description: "full unload entered the relief barrier")
        let trim = Task { @MainActor in
            trimEntered.fulfill()
            await engine.trimMemory(level: .fullUnload, reason: "test_caller_full_unload")
        }
        await fulfillment(of: [trimEntered], timeout: 5)
        XCTAssertEqual(engine.pendingModelOperationReliefCount, 1, "the trim is blocked on the in-flight load")
        let whileLoading = await coordinator.events
        XCTAssertEqual(whileLoading, ["load-begin"], "a full unload must not run under a suspended load")

        await coordinator.releaseLoad()
        await load.value
        await trim.value
        XCTAssertEqual(engine.pendingModelOperationReliefCount, 0)

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
        let afterTrim = await coordinator.events
        XCTAssertEqual(afterTrim, ["load"], "the hard trim unloaded nothing")

        try await Self.assertIdleUnloadRuns(engine: engine, coordinator: coordinator, after: afterTrim)
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

    /// AUD-10: every tier idle-unloads a resident model, the high-memory Mac
    /// included, so weights a warm left behind never outlive browsing. The
    /// roomier the tier, the longer it keeps them for the next take.
    func testEveryMemoryTierIdleUnloadsAResidentModel() {
        let expected: [(NativeDeviceMemoryClass, Double)] = [
            (.floor8GBMac, 120),
            (.mid16GBMac, 600),
            (.highMemoryMac, 1_800),
            (.iPhonePro, 30),
        ]
        for (deviceClass, seconds) in expected {
            for mode in [GenerationMode.custom, .design, .clone] {
                for isBatch in [false, true] {
                    XCTAssertEqual(
                        NativeMemoryPolicyResolver.policy(
                            deviceClass: deviceClass,
                            mode: mode,
                            isBatch: isBatch
                        ).unloadAfterIdleSeconds,
                        seconds,
                        "\(deviceClass.rawValue) \(mode.rawValue) batch=\(isBatch)"
                    )
                }
            }
        }
    }

    /// AUD-10 (PA-31 review): a warm prefetch whose intent changed settles
    /// through the runtime. The model still resident publishes `.loaded` and
    /// gets back the idle unload the warm cancelled; a cold warm used to
    /// publish `.idle` over resident weights, and a warm one kept `.loaded`
    /// with no idle unload armed. DW-03: the warm is cancelled inside its
    /// body, after its descriptor lookup and while its load is in flight, so
    /// the runtime's own cancellation check ends it, and the coordinator's
    /// log shows it unloaded nothing before the idle window did.
    @MainActor
    func testACancelledWarmPrefetchReArmsIdleUnload() async throws {
        // Cold: another model is resident, so the warm publishes `.starting`.
        try await assertCancelledWarmPrefetchReArmsIdleUnload(resident: "pro_design")
        // Warm: the warmed model is the resident one.
        try await assertCancelledWarmPrefetchReArmsIdleUnload(resident: "pro_custom")
    }

    @MainActor
    private func assertCancelledWarmPrefetchReArmsIdleUnload(
        resident: String,
        file: StaticString = #filePath,
        line: UInt = #line
    ) async throws {
        try await withResidentEngine(resident: resident, warmRequests: .holdBodyLoad) { engine, coordinator, published in
            let request = Self.customWarmRequest()
            let warm = Task { @MainActor () -> Bool in
                await engine.prefetchInteractiveReadinessIfNeeded(for: request) == nil
            }
            await waitUntilBodyLoadIsHeld(by: coordinator)
            warm.cancel()
            await coordinator.releaseHeldLoad()
            let reportedNoDiagnostics = await warm.value
            XCTAssertTrue(reportedNoDiagnostics, "a cancelled warm reports nothing", file: file, line: line)

            let atCancellation = await coordinator.events
            XCTAssertEqual(
                atCancellation,
                ["load", "capabilities", "load"],
                "the warm looked up and loaded pro_custom, then ended at its prewarm slot; nothing unloaded",
                file: file,
                line: line
            )
            XCTAssertEqual(
                engine.loadState,
                .loaded(modelID: "pro_custom"),
                "the runtime holds the model the warm loaded",
                file: file,
                line: line
            )
            XCTAssertNil(engine.visibleErrorMessage, file: file, line: line)
            try await Self.assertIdleUnloadRuns(
                engine: engine,
                coordinator: coordinator,
                after: atCancellation,
                file: file,
                line: line
            )
            XCTAssertFalse(published.includesAFailure, "a cancelled warm is not a failure", file: file, line: line)
        }
    }

    /// AUD-10 (PA-31 review): a cancelled clone prime settles through the
    /// runtime too, whether it primes the resident model or another one, so
    /// the model it leaves resident keeps its idle unload. DW-03: leaving
    /// Clone cancels the prime's token while its load is in flight; the
    /// token check after the load ends it, outside any unloading catch.
    @MainActor
    func testACancelledClonePrimeReArmsIdleUnload() async throws {
        for resident in ["pro_clone", "pro_custom"] {
            try await withResidentEngine(resident: resident, warmRequests: .holdBodyLoad) { engine, coordinator, published in
                let prime = Task { @MainActor () -> (any Error)? in
                    do {
                        try await engine.ensureCloneReferencePrimed(
                            modelID: "pro_clone",
                            reference: CloneReference(
                                audioPath: "/nonexistent/aud10-reference.wav",
                                transcript: "Hello."
                            )
                        )
                        return nil
                    } catch {
                        return error
                    }
                }
                await waitUntilBodyLoadIsHeld(by: coordinator)
                await engine.cancelClonePreparationIfNeeded()
                await coordinator.releaseHeldLoad()
                let outcome = await prime.value
                XCTAssertNotNil(
                    outcome as? CancellationError,
                    "resident \(resident): the prime must end cancelled, not \(String(describing: outcome))"
                )

                let atCancellation = await coordinator.events
                XCTAssertEqual(
                    atCancellation,
                    ["load", "capabilities", "load"],
                    "resident \(resident): the prime looked up and loaded pro_clone, then its token check ended it; nothing unloaded"
                )
                XCTAssertEqual(engine.clonePreparationState, .idle)
                XCTAssertEqual(
                    engine.loadState,
                    .loaded(modelID: "pro_clone"),
                    "resident \(resident): the runtime holds the model the prime loaded"
                )
                XCTAssertNil(engine.visibleErrorMessage)
                try await Self.assertIdleUnloadRuns(engine: engine, coordinator: coordinator, after: atCancellation)
                XCTAssertFalse(published.includesAFailure, "resident \(resident): a cancelled prime is not a failure")
            }
        }
    }

    /// DW-03: a prewarm that ends inside its body, after its descriptor
    /// lookup. The runtime releases the model at the step that ended it (its
    /// load step's catch, or its warm catch), and the engine settles from
    /// what the runtime still holds: a load an unload superseded publishes
    /// `.idle` and no failure; a failed load or prewarm step publishes its
    /// failure.
    @MainActor
    func testAPrewarmThatEndsInsideItsBodySettlesFromWhatTheRuntimeHolds() async throws {
        let endings: [(ResidentLoadCoordinator.WarmRequests, [String], Bool)] = [
            (.cancelBodyLoad, ["load", "capabilities", "load", "unload"], false),
            (.failBodyLoad, ["load", "capabilities", "load", "unload"], true),
            (.failPrewarmStep, ["load", "capabilities", "load", "capabilities", "unload"], true),
        ]
        for (warmRequests, expectedEvents, fails) in endings {
            try await withResidentEngine(resident: "pro_custom", warmRequests: warmRequests) { engine, coordinator, published in
                await engine.prewarmModelIfNeeded(for: Self.customWarmRequest())

                let events = await coordinator.events
                XCTAssertEqual(events, expectedEvents, "\(warmRequests): the body ran to the step that ended it")
                if fails {
                    if case .failed = engine.loadState {} else {
                        XCTFail("\(warmRequests): the failure is published, not \(engine.loadState)")
                    }
                    XCTAssertNotNil(engine.visibleErrorMessage, "\(warmRequests)")
                } else {
                    XCTAssertEqual(engine.loadState, .idle, "\(warmRequests): the runtime holds nothing")
                    XCTAssertNil(engine.visibleErrorMessage, "\(warmRequests)")
                    XCTAssertFalse(published.includesAFailure, "\(warmRequests): a superseded load is not a failure")
                }
            }
        }
    }

    /// B-02 (engine audit, open): a prewarm cancelled at its own prewarm
    /// step is not a failure and should keep the model it loaded. Every warm
    /// catch in `NativeEngineRuntime` unloads on any error, cancellation
    /// included, so today the step releases the weights (the engine then
    /// truthfully publishes `.idle`) and the next take reloads them.
    @MainActor
    func testAPrewarmCancelledAtItsPrewarmStepKeepsItsModel() async throws {
        try await withResidentEngine(resident: "pro_custom", warmRequests: .cancelPrewarmStep) { engine, coordinator, published in
            await engine.prewarmModelIfNeeded(for: Self.customWarmRequest())

            let events = await coordinator.events
            XCTAssertEqual(
                Array(events.prefix(4)),
                ["load", "capabilities", "load", "capabilities"],
                "the prewarm ran its body to its prewarm step"
            )
            XCTAssertNil(engine.visibleErrorMessage, "a cancelled prewarm is not a failure")
            XCTAssertFalse(published.includesAFailure, "a cancelled prewarm is not a failure")
            let settled = engine.loadState
            // One strict block per assertion, so a partial B-02 fix cannot stay green.
            XCTExpectFailure("B-02: a cancelled warm still unloads the model; remove this wrapper once B-02 lands") {
                XCTAssertEqual(
                    events,
                    ["load", "capabilities", "load", "capabilities"],
                    "a cancelled prewarm step unloads nothing"
                )
            }
            XCTExpectFailure("B-02: a cancelled warm still unloads the model; remove this wrapper once B-02 lands") {
                XCTAssertEqual(settled, .loaded(modelID: "pro_custom"), "the warmed model stays resident")
            }
        }
    }

    /// Returns once `coordinator` holds the operation's load; fails, rather
    /// than hangs, when the operation never reaches it.
    @MainActor
    private func waitUntilBodyLoadIsHeld(by coordinator: ResidentLoadCoordinator) async {
        let held = expectation(description: "the operation's load is held")
        Task {
            await coordinator.waitUntilBodyLoadIsHeld()
            held.fulfill()
        }
        await fulfillment(of: [held], timeout: 10)
    }

    /// The canonical Built-in Voice warm the Mac shell sends for `pro_custom`.
    private static func customWarmRequest() -> GenerationRequest {
        GenerationRequest(
            mode: .custom,
            modelID: "pro_custom",
            text: GenerationSemantics.canonicalCustomWarmText,
            outputPath: "",
            shouldStream: false,
            payload: .custom(
                speakerID: GenerationSemantics.canonicalCustomWarmSpeaker,
                deliveryStyle: nil
            )
        )
    }

    /// An initialized fixture engine with `resident` loaded through the
    /// runtime, a short idle unload and a coordinator that ends warm and
    /// prime requests as `warmRequests` says. `published` logs every load
    /// state the engine publishes from then on. `body` starts with no
    /// suspension after the load, and every operation under test cancels the
    /// load's own idle unload as it begins, so that unload cannot fire first.
    @MainActor
    private func withResidentEngine(
        resident: String,
        warmRequests: ResidentLoadCoordinator.WarmRequests,
        _ body: @MainActor (MLXTTSEngine, ResidentLoadCoordinator, PublishedLoadStates) async throws -> Void
    ) async throws {
        let root = FileManager.default.temporaryDirectory
            .appendingPathComponent("vocello-cancelled-warm-\(UUID().uuidString)", isDirectory: true)
        defer { try? FileManager.default.removeItem(at: root) }
        let coordinator = ResidentLoadCoordinator(warmRequests: warmRequests)
        let engine = Self.makeFixtureEngine(
            root: root,
            registry: try Self.contractRegistry(),
            coordinator: coordinator,
            // Long enough that the resident load's own idle unload cannot fire before the
            // operation under test runs (TTSEngineStoreTests.residentIdleWindow), even under TSan.
            idleUnloadDelay: 1.0
        )
        defer { engine.stop() }
        try await engine.initialize(appSupportDirectory: root)
        await engine.ensureModelLoadedIfNeeded(id: resident)
        XCTAssertEqual(engine.loadState, .loaded(modelID: resident))
        let published = PublishedLoadStates()
        let subscription = engine.$loadState.sink { published.append($0) }
        defer { subscription.cancel() }
        try await body(engine, coordinator, published)
    }

    /// Waits out the idle window until the engine publishes `.idle`, then
    /// checks the coordinator logged exactly one event since `before`: the
    /// idle unload, not one an earlier step left behind.
    @MainActor
    private static func assertIdleUnloadRuns(
        engine: MLXTTSEngine,
        coordinator: ResidentLoadCoordinator,
        after before: [String],
        file: StaticString = #filePath,
        line: UInt = #line
    ) async throws {
        let deadline = ContinuousClock.now + .seconds(10)
        while engine.loadState != .idle, ContinuousClock.now < deadline {
            try await Task.sleep(nanoseconds: 50_000_000)
        }
        XCTAssertEqual(engine.loadState, .idle, "the idle unload must run", file: file, line: line)
        let events = await coordinator.events
        XCTAssertEqual(events, before + ["unload"], "only the idle window unloaded the model", file: file, line: line)
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
/// the engine's resident-model lifecycle (idle unload, trims, warms and
/// primes) is observable without MLX weights. The model is never used to
/// generate. `events` is the ordered log of what the runtime asked of it.
///
/// A warm prefetch, prewarm or clone prime opens with a descriptor lookup,
/// then runs its body: the load, then (a Built-in Voice or Voice Design warm)
/// its prewarm step's own lookup, before it would reach MLX. `warmRequests`
/// says where that body ends, while an earlier load stays resident. Shared
/// with `TTSEngineStoreTests` and `ReferenceImportStorageTests`.
actor ResidentLoadCoordinator: MLXModelCoordinating {
    enum WarmRequests {
        /// Every lookup and load answers, so the body runs on: a Built-in
        /// Voice prewarm then fails at the unloaded runtime actor, and a
        /// clone prime of a missing reference fails at clone conditioning.
        case proceed
        /// Every descriptor lookup fails, before the runtime loads or warms
        /// anything, so the weights an earlier load left stay resident
        /// behind the failure (PA-32).
        case failDescriptorLookup
        /// The first load after a lookup suspends until `releaseHeldLoad()`,
        /// then returns: a test cancels the warm's task or the prime's token
        /// meanwhile, and the runtime's own check after the load ends it.
        case holdBodyLoad
        /// Every load after a lookup throws a raw cancellation, as a load an
        /// unload superseded does (the real coordinator's load epoch).
        case cancelBodyLoad
        /// Every load after a lookup fails.
        case failBodyLoad
        /// The second lookup, a warm's prewarm step after its load, throws a
        /// raw cancellation, as a warm whose intent changed there ends.
        case cancelPrewarmStep
        /// The second lookup, a warm's prewarm step, fails.
        case failPrewarmStep
    }

    /// The failure the `fail…` modes end with.
    struct WarmRequestFailure: Error {}

    /// "capabilities" per descriptor lookup, "load" and "unload", in order.
    private(set) var events: [String] = []
    private let warmRequests: WarmRequests
    private var lookups = 0
    private var hasHeldALoad = false
    private var heldLoad: CheckedContinuation<Void, Never>?
    private var heldLoadWaiters: [CheckedContinuation<Void, Never>] = []
    /// A release before any load is held (a wait that timed out) is kept, so a load
    /// that arrives afterwards passes instead of parking forever and hanging the suite.
    private var releasedBeforeHold = false

    init(warmRequests: WarmRequests = .proceed) {
        self.warmRequests = warmRequests
    }

    /// Returns once a `.holdBodyLoad` load is suspended.
    func waitUntilBodyLoadIsHeld() async {
        guard heldLoad == nil else { return }
        await withCheckedContinuation { continuation in
            heldLoadWaiters.append(continuation)
        }
    }

    /// Lets the held load return.
    func releaseHeldLoad() {
        guard let held = heldLoad else {
            releasedBeforeHold = true
            return
        }
        heldLoad = nil
        held.resume()
    }

    func qwen3Capabilities(for id: String) async throws -> Qwen3TTSModelCapabilities {
        events.append("capabilities")
        lookups += 1
        switch (warmRequests, lookups) {
        case (.failDescriptorLookup, _):
            throw WarmRequestFailure()
        case (.cancelPrewarmStep, 2):
            throw CancellationError()
        case (.failPrewarmStep, 2):
            throw WarmRequestFailure()
        default:
            return Self.capabilities(for: id)
        }
    }

    func loadModel(
        id: String,
        capabilityProfile: NativeLoadCapabilityProfile
    ) async throws -> NativeModelLoadResult {
        events.append("load")
        // A load before any lookup is the resident one a test starts from.
        if lookups > 0 {
            switch warmRequests {
            case .holdBodyLoad where !hasHeldALoad:
                hasHeldALoad = true
                if releasedBeforeHold {
                    let waiters = heldLoadWaiters
                    heldLoadWaiters.removeAll()
                    waiters.forEach { $0.resume() }
                } else {
                    await withCheckedContinuation { continuation in
                        heldLoad = continuation
                        let waiters = heldLoadWaiters
                        heldLoadWaiters.removeAll()
                        waiters.forEach { $0.resume() }
                    }
                }
            case .cancelBodyLoad:
                throw CancellationError()
            case .failBodyLoad:
                throw WarmRequestFailure()
            default:
                break
            }
        }
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
            qwen3Capabilities: Self.capabilities(for: id),
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

    /// The clone model declares Voice Cloning, so a prime passes the
    /// runtime's capability check and runs its body.
    private static func capabilities(for id: String) -> Qwen3TTSModelCapabilities {
        let isClone = id.hasSuffix("_clone")
        return Qwen3TTSModelCapabilities(
            modelSize: .pro1b7,
            familyType: isClone ? .baseClone : .customVoice,
            supportsInstructionControl: !isClone,
            supportsVoiceClone: isClone,
            supportsXVectorOnlyClone: isClone,
            requiresSpeakerEncoder: isClone,
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
}

/// Every load state an engine published, in order.
@MainActor
private final class PublishedLoadStates {
    private(set) var states: [EngineLoadState] = []

    func append(_ state: EngineLoadState) {
        states.append(state)
    }

    var includesAFailure: Bool {
        states.contains { state in
            if case .failed = state { return true }
            return false
        }
    }
}

/// A model coordinator that records the prewarm-state resets and unloads a
/// caller trim asks of it; no model is ever loaded.
private actor TrimRecordingCoordinator: MLXModelCoordinating {
    private(set) var events: [String] = []

    func qwen3Capabilities(for id: String) async throws -> Qwen3TTSModelCapabilities {
        throw CancellationError()
    }

    func loadModel(
        id: String,
        capabilityProfile: NativeLoadCapabilityProfile
    ) async throws -> NativeModelLoadResult {
        throw CancellationError()
    }

    func unloadModel() async {
        events.append("unload")
    }

    func isPrewarmed(identityKey: String) async -> Bool { false }
    func markPrewarmed(identityKey: String) async {}

    func clearPrewarmState() async {
        events.append("clearPrewarmState")
    }

    func setTelemetryRecorder(_ recorder: NativeTelemetryRecorder?) async {}
    func requiresUnloadAfterRuntimeFailure() async -> Bool { false }
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
