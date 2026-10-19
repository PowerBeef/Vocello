import XCTest
import os
@testable import QwenVoiceCore
import VocelloQwen3Core

/// Seam tests for `NativeEngineRuntime` (DW-03, audit P2-5). The runtime runs
/// over a recording model coordinator and a recording allocator control that
/// write one ordered log, so each assertion reads what the runtime asked of its
/// collaborators, in order, rather than the state it publishes. Nothing here
/// touches MLX or Metal: the coordinator hands back an unloaded runtime actor,
/// the allocator only records, and no test reaches generation or a prewarm
/// body. The host is macOS, so a model switch takes the non-iOS path.
final class NativeEngineRuntimeSeamTests: XCTestCase {
    // MARK: - Lifecycle

    /// A load that brought weights in clears the clone state; a load of the
    /// resident model clears nothing. `unloadModel()` and `stop()` each release
    /// the weights through the coordinator's unload, never through
    /// `clearPrewarmState()`, and leave no active model.
    func testLoadUnloadAndStopReachTheCoordinatorInOrder() async throws {
        let fixture = RuntimeSeamFixture()
        let runtime = fixture.runtime

        let first = try await runtime.loadModel(id: RuntimeSeam.modelA)
        XCTAssertTrue(first.didLoad)
        XCTAssertNotNil(first.timingsMS["native_model_load_ms"], "the runtime times its own load")
        let afterLoad = await runtime.loadedModelID()
        XCTAssertEqual(afterLoad, RuntimeSeam.modelA)

        let resident = try await runtime.loadModel(id: RuntimeSeam.modelA)
        XCTAssertFalse(resident.didLoad)
        let afterResidentLoad = await runtime.loadedModelID()
        XCTAssertEqual(afterResidentLoad, RuntimeSeam.modelA)

        await runtime.unloadModel()
        let afterUnload = await runtime.loadedModelID()
        XCTAssertNil(afterUnload)

        _ = try await runtime.loadModel(id: RuntimeSeam.modelA)
        await runtime.stop()
        let afterStop = await runtime.loadedModelID()
        XCTAssertNil(afterStop)

        XCTAssertEqual(fixture.log.entries, [
            "load:\(RuntimeSeam.modelA)", RuntimeSeam.clearCache,
            "load:\(RuntimeSeam.modelA)",
            "unload", RuntimeSeam.clearCache,
            "load:\(RuntimeSeam.modelA)", RuntimeSeam.clearCache,
            "unload", RuntimeSeam.clearCache,
        ])
        let profiles = await fixture.coordinator.loadProfiles
        XCTAssertEqual(profiles, [.fullCapabilities, .fullCapabilities, .fullCapabilities])
    }

    // MARK: - Model switch

    /// On macOS a switch is the coordinator's load alone: the runtime unloads
    /// nothing first (that block is iOS-only), applies no allocator policy and
    /// leaves the coordinator's prewarm marks alone. It clears the clone state
    /// once the new weights are in.
    func testAModelSwitchLoadsOverTheResidentModelAndClearsOnlyCloneState() async throws {
        let fixture = RuntimeSeamFixture()
        _ = try await fixture.runtime.loadModel(id: RuntimeSeam.modelA)
        let switched = try await fixture.runtime.loadModel(
            id: RuntimeSeam.modelB,
            capabilityProfile: .designOnly
        )
        XCTAssertTrue(switched.didLoad)
        let loaded = await fixture.runtime.loadedModelID()
        XCTAssertEqual(loaded, RuntimeSeam.modelB)
        XCTAssertEqual(
            fixture.log.entries,
            [
                "load:\(RuntimeSeam.modelA)", RuntimeSeam.clearCache,
                "load:\(RuntimeSeam.modelB)", RuntimeSeam.clearCache,
            ],
            "a macOS switch neither unloads first, applies a policy nor resets prewarm state"
        )
        let profiles = await fixture.coordinator.loadProfiles
        XCTAssertEqual(profiles, [.fullCapabilities, .designOnly])
    }

    /// A caller's switch clears the clone-prime token with the rest of the
    /// clone state, so a prime whose load was in flight ends cancelled once its
    /// load lands, before any clone preparation.
    func testAModelSwitchDuringAPrimeLoadCancelsThePrime() async throws {
        let fixture = RuntimeSeamFixture()
        let runtime = fixture.runtime
        await fixture.coordinator.hold(.load)
        let prime = Task { await RuntimeSeam.primeError(runtime, modelID: RuntimeSeam.cloneModel) }
        await waitForEntries(fixture.log, prefix: "load:\(RuntimeSeam.cloneModel)")

        _ = try await runtime.loadModel(id: RuntimeSeam.modelB)
        await fixture.coordinator.release(.load)
        let primeError = await prime.value
        XCTAssertTrue(
            primeError is CancellationError,
            "the switch must cancel the prime, not \(String(describing: primeError))"
        )
        XCTAssertEqual(fixture.log.entries, [
            "capabilities", RuntimeSeam.applyPolicy(mode: .clone), "load:\(RuntimeSeam.cloneModel)",
            "load:\(RuntimeSeam.modelB)", RuntimeSeam.clearCache,
            RuntimeSeam.clearCache,
        ])
        let profiles = await fixture.coordinator.loadProfiles
        XCTAssertEqual(profiles, [.cloneOnly, .fullCapabilities])
    }

    /// The saved-voice prebuild loads while keeping the clone-prime token, so a
    /// prime whose load it overtook still runs on to clone preparation. With no
    /// clone-reference directory configured the prebuild stops there quietly,
    /// the prime fails there with a typed error, and neither unloads.
    func testASavedVoicePrebuildDuringAPrimeLoadKeepsThePrimeAlive() async throws {
        let fixture = RuntimeSeamFixture()
        let runtime = fixture.runtime
        await fixture.coordinator.hold(.load)
        let prime = Task { await RuntimeSeam.primeError(runtime, modelID: RuntimeSeam.cloneModel) }
        await waitForEntries(fixture.log, prefix: "load:\(RuntimeSeam.cloneModel)")

        await runtime.prebuildSavedVoiceClonePrompt(
            modelID: RuntimeSeam.cloneModel,
            reference: RuntimeSeam.savedVoiceReference
        )
        let expected = [
            "capabilities", RuntimeSeam.applyPolicy(mode: .clone), "load:\(RuntimeSeam.cloneModel)",
            "capabilities", "load:\(RuntimeSeam.cloneModel)", RuntimeSeam.clearCache,
        ]
        XCTAssertEqual(fixture.log.entries, expected)
        let afterPrebuild = await runtime.loadedModelID()
        XCTAssertEqual(afterPrebuild, RuntimeSeam.cloneModel)

        await fixture.coordinator.release(.load)
        let primeError = await prime.value
        let runtimeError = try XCTUnwrap(
            primeError as? NativeRuntimeError,
            "the prebuild must keep the prime's token, not \(String(describing: primeError))"
        )
        XCTAssertEqual(runtimeError.stage, .clonePreparation)
        XCTAssertEqual(fixture.log.entries, expected, "the prime's load found its model resident")
        let profiles = await fixture.coordinator.loadProfiles
        XCTAssertEqual(profiles, [.cloneOnly, .cloneOnly])
    }

    /// The prebuild skips a reference that is not a saved voice, and a model
    /// other than the active one, before it asks the coordinator anything.
    func testAPrebuildSkipsATransientReferenceAndAnotherActiveModel() async throws {
        let fixture = RuntimeSeamFixture()
        await fixture.runtime.prebuildSavedVoiceClonePrompt(
            modelID: RuntimeSeam.cloneModel,
            reference: RuntimeSeam.transientReference
        )
        XCTAssertEqual(fixture.log.entries, [], "only a saved voice is prebuilt")

        _ = try await fixture.runtime.loadModel(id: RuntimeSeam.modelA)
        await fixture.runtime.prebuildSavedVoiceClonePrompt(
            modelID: RuntimeSeam.cloneModel,
            reference: RuntimeSeam.savedVoiceReference
        )
        XCTAssertEqual(
            fixture.log.entries,
            ["load:\(RuntimeSeam.modelA)", RuntimeSeam.clearCache],
            "a background prebuild must not switch away from the active model"
        )
        let loaded = await fixture.runtime.loadedModelID()
        XCTAssertEqual(loaded, RuntimeSeam.modelA)
    }

    /// A prime asks for capabilities first and applies the clone policy only
    /// once they pass, before its load: a refused prime applies no policy and
    /// loads nothing. Its own load keeps its token, so with no reference
    /// directory configured it fails at clone preparation, not cancelled.
    func testAClonePrimeAppliesItsPolicyBetweenCapabilitiesAndItsLoad() async throws {
        let fixture = RuntimeSeamFixture()
        await fixture.coordinator.failCapabilities(true)
        let refused = await RuntimeSeam.primeError(fixture.runtime, modelID: RuntimeSeam.cloneModel)
        XCTAssertTrue(refused is RuntimeSeamCoordinator.CapabilitiesFailure, String(describing: refused))
        XCTAssertEqual(fixture.log.entries, ["capabilities"], "a refused prime applies no policy")

        await fixture.coordinator.failCapabilities(false)
        let primeError = await RuntimeSeam.primeError(fixture.runtime, modelID: RuntimeSeam.cloneModel)
        let runtimeError = try XCTUnwrap(primeError as? NativeRuntimeError, String(describing: primeError))
        XCTAssertEqual(runtimeError.stage, .clonePreparation)
        XCTAssertEqual(fixture.log.entries, [
            "capabilities",
            "capabilities", RuntimeSeam.applyPolicy(mode: .clone),
            "load:\(RuntimeSeam.cloneModel)", RuntimeSeam.clearCache,
        ])
        let profiles = await fixture.coordinator.loadProfiles
        XCTAssertEqual(profiles, [.cloneOnly])
        let loaded = await fixture.runtime.loadedModelID()
        XCTAssertEqual(loaded, RuntimeSeam.cloneModel, "a clone-preparation failure keeps the model")
    }

    // MARK: - Failed load

    /// A load the coordinator fails is unloaded through the coordinator, leaves
    /// no active model (the earlier one included), clears the clone state and
    /// reaches the caller as a `NativeRuntimeError` at the model-load stage that
    /// keeps the cause's type.
    func testAFailedLoadUnloadsDropsTheActiveModelAndWrapsTheError() async throws {
        let fixture = RuntimeSeamFixture()
        let runtime = fixture.runtime
        _ = try await runtime.loadModel(id: RuntimeSeam.modelA)
        await fixture.coordinator.failNextLoad()
        do {
            _ = try await runtime.loadModel(id: RuntimeSeam.modelB)
            XCTFail("the coordinator's load failure must reach the caller")
        } catch {
            let runtimeError = try XCTUnwrap(error as? NativeRuntimeError, String(describing: error))
            XCTAssertEqual(runtimeError.stage, .upstreamModelLoad)
            XCTAssertEqual(runtimeError.underlyingDisposition, .failure)
            XCTAssertTrue(runtimeError.message.contains(RuntimeSeam.modelB), runtimeError.message)
            XCTAssertEqual(runtimeError.underlyingDescription?.contains("LoadFailure"), true)
        }
        XCTAssertEqual(fixture.log.entries, [
            "load:\(RuntimeSeam.modelA)", RuntimeSeam.clearCache,
            "load:\(RuntimeSeam.modelB)", "unload", RuntimeSeam.clearCache,
        ])
        let loaded = await runtime.loadedModelID()
        XCTAssertNil(loaded)
    }

    // MARK: - Interleavings

    /// An unload or a stop that lands while a load is suspended in the
    /// coordinator runs at once (the runtime holds no lock across the load),
    /// and supersedes it: the coordinator ends the load cancelled, as its load
    /// epoch does in production, and the runtime unloads again, keeps no active
    /// model and types the error as a cancellation so callers settle quietly.
    func testAnUnloadOrStopDuringASuspendedLoadSupersedesIt() async throws {
        try await assertTeardownSupersedesASuspendedLoad { await $0.unloadModel() }
        try await assertTeardownSupersedesASuspendedLoad { await $0.stop() }
    }

    // MARK: - Prewarm slot

    /// A hard trim holds the prewarm slot for its whole body, across its
    /// suspension in the coordinator, so a Built-in Voice warm that arrived
    /// meanwhile makes its in-slot prewarm query only after the trim cleared
    /// the allocator and left. The slot is private; the log is the evidence.
    func testAHardTrimHoldsThePrewarmSlotAgainstAWarm() async throws {
        let fixture = RuntimeSeamFixture()
        _ = try await fixture.runtime.loadModel(id: RuntimeSeam.customModel)
        let holder = await startHoldingHardTrim(fixture)
        let warm = await startContendingWarm(fixture)
        XCTAssertEqual(
            RuntimeSeam.count(of: "isPrewarmed:", in: fixture.log.entries),
            1,
            "the warm must wait on the slot the trim holds"
        )

        await fixture.coordinator.release(.clearPrewarm)
        await holder.value
        let diagnostics = try await warm.value.get()
        let entries = fixture.log.entries
        let query = try XCTUnwrap(entries.first(where: { $0.hasPrefix("isPrewarmed:") }))
        XCTAssertEqual(entries, [
            "load:\(RuntimeSeam.customModel)", RuntimeSeam.clearCache,
            RuntimeSeam.clearCache, "clearPrewarm",
            "capabilities", RuntimeSeam.applyPolicy(mode: .custom), "load:\(RuntimeSeam.customModel)", query,
            RuntimeSeam.clearCache,
            query,
        ])
        XCTAssertEqual(diagnostics.requestKey.map { "isPrewarmed:\($0)" }, query)
        let profiles = await fixture.coordinator.loadProfiles
        XCTAssertEqual(profiles, [.fullCapabilities, .customOnly])
        await assertPrewarmSlotIsFree(fixture.runtime)
    }

    /// A trim cancelled before it holds the slot returns without clearing a
    /// cache, reaching the coordinator or releasing the slot another trim
    /// holds: a warm that arrives afterwards still waits for the holder.
    func testACancelledTrimNeitherEntersNorFreesTheHeldSlot() async throws {
        let fixture = RuntimeSeamFixture()
        let runtime = fixture.runtime
        _ = try await runtime.loadModel(id: RuntimeSeam.customModel)
        let holder = await startHoldingHardTrim(fixture)
        let whileHeld = fixture.log.entries

        let cancelled = Task {
            withUnsafeCurrentTask { $0?.cancel() }
            await runtime.trimMemory(level: .hardTrim, reason: "seam_cancelled_trim")
        }
        await cancelled.value
        XCTAssertEqual(fixture.log.entries, whileHeld, "a cancelled trim must not run its body")

        let warm = await startContendingWarm(fixture)
        XCTAssertEqual(
            RuntimeSeam.count(of: "isPrewarmed:", in: fixture.log.entries),
            1,
            "the cancelled trim must not free the slot the holder owns"
        )

        await fixture.coordinator.release(.clearPrewarm)
        await holder.value
        _ = try await warm.value.get()
        let entries = fixture.log.entries
        XCTAssertEqual(RuntimeSeam.count(of: "clearPrewarm", in: entries), 1)
        XCTAssertEqual(entries.suffix(2).first, RuntimeSeam.clearCache, "the holder finishes before the warm's in-slot query")
        await assertPrewarmSlotIsFree(runtime)
    }

    // MARK: - Runtime-failure query

    /// The runtime returns the coordinator's verdict unchanged, and asking
    /// neither unloads nor clears anything.
    func testRequiresUnloadAfterRuntimeFailurePassesTheCoordinatorsAnswerThrough() async throws {
        let fixture = RuntimeSeamFixture()
        let runtime = fixture.runtime
        _ = try await runtime.loadModel(id: RuntimeSeam.modelA)
        let clean = await runtime.requiresUnloadAfterRuntimeFailure()
        XCTAssertFalse(clean)
        await fixture.coordinator.observeRuntimeFailure(true)
        let failed = await runtime.requiresUnloadAfterRuntimeFailure()
        XCTAssertTrue(failed)
        XCTAssertEqual(fixture.log.entries, [
            "load:\(RuntimeSeam.modelA)", RuntimeSeam.clearCache, "requiresUnload", "requiresUnload",
        ])
        let loaded = await runtime.loadedModelID()
        XCTAssertEqual(loaded, RuntimeSeam.modelA)
    }

    // MARK: - Helpers

    private func assertTeardownSupersedesASuspendedLoad(
        _ teardown: @escaping @Sendable (NativeEngineRuntime) async -> Void,
        file: StaticString = #filePath,
        line: UInt = #line
    ) async throws {
        let fixture = RuntimeSeamFixture()
        let runtime = fixture.runtime
        await fixture.coordinator.hold(.load)
        let load = Task { () -> (any Error)? in
            do {
                _ = try await runtime.loadModel(id: RuntimeSeam.modelA)
                return nil
            } catch {
                return error
            }
        }
        await waitForEntries(fixture.log, prefix: "load:\(RuntimeSeam.modelA)")

        // A timeout here fails the test instead of hanging it; the release
        // below then unwinds a teardown that waited for the load.
        let tornDown = expectation(description: "the teardown ran while the load was suspended")
        let teardownTask = Task {
            await teardown(runtime)
            tornDown.fulfill()
        }
        await fulfillment(of: [tornDown], timeout: 10)
        XCTAssertEqual(
            fixture.log.entries,
            ["load:\(RuntimeSeam.modelA)", "unload", RuntimeSeam.clearCache],
            "the teardown must not wait for the suspended load",
            file: file,
            line: line
        )

        await fixture.coordinator.release(.load)
        let loadError = await load.value
        await teardownTask.value
        let runtimeError = try XCTUnwrap(
            loadError as? NativeRuntimeError,
            "the superseded load must end with a typed error, not \(String(describing: loadError))",
            file: file,
            line: line
        )
        XCTAssertEqual(runtimeError.stage, .upstreamModelLoad, file: file, line: line)
        XCTAssertEqual(runtimeError.underlyingDisposition, .cancellation, file: file, line: line)
        XCTAssertEqual(
            fixture.log.entries,
            ["load:\(RuntimeSeam.modelA)", "unload", RuntimeSeam.clearCache, "unload", RuntimeSeam.clearCache],
            "the superseded load unloads and clears the clone state again",
            file: file,
            line: line
        )
        let loaded = await runtime.loadedModelID()
        XCTAssertNil(loaded, "a superseded load leaves no active model", file: file, line: line)
    }

    /// Returns once `log` holds `count` entries starting with `prefix`; a
    /// timeout fails the test rather than hanging it.
    private func waitForEntries(_ log: RuntimeSeamLog, prefix: String, count: Int = 1) async {
        let reached = expectation(description: "\(count) log entries starting with \(prefix)")
        Task {
            await log.waitForEntries(withPrefix: prefix, count: count)
            reached.fulfill()
        }
        await fulfillment(of: [reached], timeout: 10)
    }

    /// A hard trim that holds the prewarm slot, suspended inside the
    /// coordinator's `clearPrewarmState()` until the test releases it.
    private func startHoldingHardTrim(_ fixture: RuntimeSeamFixture) async -> Task<Void, Never> {
        await fixture.coordinator.hold(.clearPrewarm)
        let runtime = fixture.runtime
        let holder = Task { await runtime.trimMemory(level: .hardTrim, reason: "seam_holder_trim") }
        await waitForEntries(fixture.log, prefix: "clearPrewarm")
        return holder
    }

    /// A Built-in Voice warm of the resident `customModel`, returned once it
    /// waits on the prewarm slot or, when nothing holds the slot, has made its
    /// in-slot prewarm query. Its query before the slot answers "not warm" and
    /// the one inside it "warm", so the warm never reaches MLX.
    private func startContendingWarm(_ fixture: RuntimeSeamFixture) async -> RuntimeSeamWarmTask {
        await fixture.coordinator.answerIsPrewarmed([false, true])
        let runtime = fixture.runtime
        let request = RuntimeSeam.warmRequest(modelID: RuntimeSeam.customModel)
        let warm = Task { () -> Result<InteractivePrefetchDiagnostics, any Error> in
            do {
                return .success(try await runtime.prepareInteractiveReadiness(for: request))
            } catch {
                return .failure(error)
            }
        }
        await waitForEntries(fixture.log, prefix: "isPrewarmed:")
        await RuntimeSeam.settle(runtime, fixture.coordinator)
        return warm
    }

    /// A later trim takes the prewarm slot; a leaked slot fails the test after
    /// the timeout instead of hanging the suite.
    private func assertPrewarmSlotIsFree(_ runtime: NativeEngineRuntime) async {
        let trimmed = expectation(description: "a later trim takes the free prewarm slot")
        Task {
            await runtime.trimMemory(level: .softTrim, reason: "seam_free_slot_trim")
            trimmed.fulfill()
        }
        await fulfillment(of: [trimmed], timeout: 10)
    }
}

private typealias RuntimeSeamWarmTask = Task<Result<InteractivePrefetchDiagnostics, any Error>, Never>

/// A runtime over the recording coordinator and a recording allocator control,
/// both writing `log`. The runtime builds its default clone-conditioning cache
/// from the same control, so the cache's clears are logged too.
private struct RuntimeSeamFixture {
    let log: RuntimeSeamLog
    let coordinator: RuntimeSeamCoordinator
    let runtime: NativeEngineRuntime

    init() {
        let log = RuntimeSeamLog()
        let coordinator = RuntimeSeamCoordinator(log: log)
        self.log = log
        self.coordinator = coordinator
        runtime = NativeEngineRuntime(
            loadCoordinator: coordinator,
            audioPreparationService: NativeAudioPreparationService(),
            lightweightWarmupText: "Hi.",
            allocatorControl: NativeMLXAllocatorControl(
                applyPolicy: { log.append("allocator.applyPolicy:\($0.name)") },
                clearCache: { log.append(RuntimeSeam.clearCache) }
            )
        )
    }
}

private enum RuntimeSeam {
    static let modelA = "seam-model-a"
    static let modelB = "seam-model-b"
    static let cloneModel = "seam-clone-model"
    static let customModel = "seam-custom-model"
    static let clearCache = "allocator.clearCache"

    static let savedVoiceReference = CloneReference(
        audioPath: "/nonexistent/seam-saved-voice.wav",
        transcript: "A synthetic seam transcript.",
        preparedVoiceID: "seam-saved-voice"
    )

    static let transientReference = CloneReference(
        audioPath: "/nonexistent/seam-transient-reference.wav",
        transcript: "A synthetic seam transcript."
    )

    static func applyPolicy(mode: GenerationMode) -> String {
        "allocator.applyPolicy:\(NativeMemoryPolicyResolver.policy(mode: mode, isBatch: false).name)"
    }

    static func count(of prefix: String, in entries: [String]) -> Int {
        entries.filter { $0.hasPrefix(prefix) }.count
    }

    static func warmRequest(modelID: String) -> GenerationRequest {
        GenerationRequest(
            mode: .custom,
            modelID: modelID,
            text: GenerationSemantics.canonicalCustomWarmText,
            outputPath: "",
            shouldStream: false,
            payload: .custom(
                speakerID: GenerationSemantics.canonicalCustomWarmSpeaker,
                deliveryStyle: nil
            )
        )
    }

    /// The error a prime of `savedVoiceReference` ends with, or nil.
    static func primeError(_ runtime: NativeEngineRuntime, modelID: String) async -> (any Error)? {
        do {
            _ = try await runtime.primeCloneReference(modelID: modelID, reference: savedVoiceReference)
            return nil
        } catch {
            return error
        }
    }

    /// Queues the caller behind a contender that has just made a coordinator
    /// call: a round trip through the coordinator, one through the runtime,
    /// then one through the coordinator again. Each actor runs equal-priority
    /// jobs in arrival order, so on return the contender has run on the runtime
    /// up to its next suspension (the prewarm slot) and, had it gone on to the
    /// coordinator instead, has logged that call.
    static func settle(_ runtime: NativeEngineRuntime, _ coordinator: RuntimeSeamCoordinator) async {
        await coordinator.roundTrip()
        _ = await runtime.loadedModelID()
        await coordinator.roundTrip()
    }
}

/// One ordered record of what the runtime asked of its coordinator and of the
/// MLX allocator, written from both under a lock, with continuation waits.
private final class RuntimeSeamLog: Sendable {
    private struct Waiter: Sendable {
        let prefix: String
        let count: Int
        let continuation: CheckedContinuation<Void, Never>
    }

    private struct State: Sendable {
        var entries: [String] = []
        var waiters: [Waiter] = []
    }

    private let storage = OSAllocatedUnfairLock(initialState: State())

    var entries: [String] { storage.withLock { $0.entries } }

    func append(_ entry: String) {
        let ready = storage.withLock { state -> [CheckedContinuation<Void, Never>] in
            state.entries.append(entry)
            var satisfied: [CheckedContinuation<Void, Never>] = []
            var waiting: [Waiter] = []
            for waiter in state.waiters {
                if RuntimeSeam.count(of: waiter.prefix, in: state.entries) >= waiter.count {
                    satisfied.append(waiter.continuation)
                } else {
                    waiting.append(waiter)
                }
            }
            state.waiters = waiting
            return satisfied
        }
        ready.forEach { $0.resume() }
    }

    func waitForEntries(withPrefix prefix: String, count: Int) async {
        await withCheckedContinuation { (continuation: CheckedContinuation<Void, Never>) in
            let reached = storage.withLock { state -> Bool in
                guard RuntimeSeam.count(of: prefix, in: state.entries) < count else { return true }
                state.waiters.append(Waiter(prefix: prefix, count: count, continuation: continuation))
                return false
            }
            if reached { continuation.resume() }
        }
    }
}

/// A model coordinator that logs every call the runtime makes ("capabilities",
/// "load:<id>", "unload", "isPrewarmed:<key>", "markPrewarmed:<key>",
/// "clearPrewarm", "requiresUnload") and can hold chosen calls on a
/// continuation until the test releases them. Like the production coordinator,
/// a load of the resident model reports `didLoad == false`, and an unload that
/// lands while a load is held supersedes it: the load then ends with a raw
/// `CancellationError`, as the production load epoch does. Each load hands back
/// an unloaded runtime actor, never used to generate.
private actor RuntimeSeamCoordinator: MLXModelCoordinating {
    enum Call: Hashable, Sendable {
        case load
        case clearPrewarm
    }

    struct LoadFailure: Error {}
    struct CapabilitiesFailure: Error {}

    private(set) var loadProfiles: [NativeLoadCapabilityProfile] = []
    private let log: RuntimeSeamLog
    private var armedHolds: [Call: Int] = [:]
    private var heldCalls: [Call: [CheckedContinuation<Void, Never>]] = [:]
    private var residentModelID: String?
    private var unloadCount = 0
    private var failsNextLoad = false
    private var failsCapabilities = false
    private var isPrewarmedAnswers: [Bool] = []
    private var observedRuntimeFailure = false

    init(log: RuntimeSeamLog) {
        self.log = log
    }

    /// Holds the next `call` after it logs, until `release(call)`.
    func hold(_ call: Call) {
        armedHolds[call, default: 0] += 1
    }

    /// Resumes the oldest held `call`, or disarms a hold that has not fired.
    func release(_ call: Call) {
        if var waiting = heldCalls[call], !waiting.isEmpty {
            let next = waiting.removeFirst()
            heldCalls[call] = waiting
            next.resume()
        } else if let armed = armedHolds[call], armed > 0 {
            armedHolds[call] = armed - 1
        }
    }

    func failNextLoad() {
        failsNextLoad = true
    }

    func failCapabilities(_ fails: Bool) {
        failsCapabilities = fails
    }

    /// Answers for the next `isPrewarmed` queries, in order; `false` after.
    func answerIsPrewarmed(_ answers: [Bool]) {
        isPrewarmedAnswers = answers
    }

    func observeRuntimeFailure(_ observed: Bool) {
        observedRuntimeFailure = observed
    }

    /// An empty job, for ordering the test behind work queued on this actor.
    func roundTrip() {}

    func qwen3Capabilities(for id: String) async throws -> Qwen3TTSModelCapabilities {
        log.append("capabilities")
        if failsCapabilities {
            throw CapabilitiesFailure()
        }
        return Self.capabilities
    }

    func loadModel(
        id: String,
        capabilityProfile: NativeLoadCapabilityProfile
    ) async throws -> NativeModelLoadResult {
        log.append("load:\(id)")
        loadProfiles.append(capabilityProfile)
        let unloadsAtStart = unloadCount
        await pauseIfHeld(.load)
        if failsNextLoad {
            failsNextLoad = false
            throw LoadFailure()
        }
        guard unloadCount == unloadsAtStart else {
            throw CancellationError()
        }
        let didLoad = residentModelID != id
        residentModelID = id
        return Self.loadResult(id: id, didLoad: didLoad, capabilityProfile: capabilityProfile)
    }

    func unloadModel() async {
        log.append("unload")
        unloadCount += 1
        residentModelID = nil
    }

    func isPrewarmed(identityKey: String) async -> Bool {
        log.append("isPrewarmed:\(identityKey)")
        return isPrewarmedAnswers.isEmpty ? false : isPrewarmedAnswers.removeFirst()
    }

    func markPrewarmed(identityKey: String) async {
        log.append("markPrewarmed:\(identityKey)")
    }

    func clearPrewarmState() async {
        log.append("clearPrewarm")
        await pauseIfHeld(.clearPrewarm)
    }

    func setTelemetryRecorder(_ recorder: NativeTelemetryRecorder?) async {}

    func requiresUnloadAfterRuntimeFailure() async -> Bool {
        log.append("requiresUnload")
        return observedRuntimeFailure
    }

    private func pauseIfHeld(_ call: Call) async {
        guard let armed = armedHolds[call], armed > 0 else { return }
        armedHolds[call] = armed - 1
        await withCheckedContinuation { (continuation: CheckedContinuation<Void, Never>) in
            heldCalls[call, default: []].append(continuation)
        }
    }

    private static func loadResult(
        id: String,
        didLoad: Bool,
        capabilityProfile: NativeLoadCapabilityProfile
    ) -> NativeModelLoadResult {
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
            didLoad: didLoad,
            capabilityProfile: capabilityProfile,
            qwen3Capabilities: capabilities,
            timingsMS: [:],
            booleanFlags: [:],
            stringFlags: [:]
        )
    }

    /// A Base model that serves every mode, so clone validation passes.
    private static let capabilities = Qwen3TTSModelCapabilities(
        modelSize: .pro1b7,
        familyType: .baseClone,
        supportsInstructionControl: true,
        supportsVoiceClone: true,
        supportsXVectorOnlyClone: true,
        requiresSpeakerEncoder: true,
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
