import Combine
import Foundation
import QwenVoiceCore
import XCTest
import os

/// Thrown by `StoreFixtureEngine` when a test makes its cancellation barrier fail.
private struct StoreFixtureCancellationFailure: Error {}

/// Thrown by `StoreFixtureEngine` for work these tests never route to the engine.
private struct StoreFixtureUnexpectedCall: Error {}

/// App-memory headroom reported by the store's injected snapshot provider, in MiB.
/// With `IOSMemoryBudgetPolicy.iPhoneShippingDefault`, 768 MiB or more is healthy,
/// 384..<768 MiB guarded and less than 384 MiB critical.
private final class MemoryHeadroomDial: Sendable {
    static let healthy: UInt64 = 4_096
    static let guarded: UInt64 = 512
    static let critical: UInt64 = 128

    private let megabytes: OSAllocatedUnfairLock<UInt64>

    init(megabytes: UInt64) {
        self.megabytes = OSAllocatedUnfairLock(initialState: megabytes)
    }

    func set(_ value: UInt64) {
        megabytes.withLock { $0 = value }
    }

    func snapshot() -> IOSMemorySnapshot {
        let headroom = megabytes.withLock { $0 }
        return IOSMemorySnapshot(
            processRole: .app,
            totalDeviceRAMBytes: 8 * 1_073_741_824,
            availableHeadroomBytes: headroom * 1_048_576,
            residentBytes: nil,
            physFootprintBytes: nil,
            compressedBytes: nil,
            gpuAllocatedBytes: nil,
            gpuRecommendedWorkingSetBytes: nil,
            hasUnifiedMemory: true
        )
    }
}

/// A fake engine host behind the real `AnyTTSEngineBackend` and `TTSEngineStore`.
/// It records every call that reaches it and can hold a generation open until the
/// test releases or cancels it, so the store's ownership is observable mid-take.
@MainActor
private class StoreFixtureEngine: TTSEngineRuntimeControlling, ActiveGenerationCancellable {
    struct BandTransition: Equatable {
        let from: IOSMemoryPressureBand
        let to: IOSMemoryPressureBand
    }

    let modelRegistry: any ModelRegistry
    @Published var loadState: EngineLoadState = .idle
    @Published var clonePreparationState: ClonePreparationState = .idle
    @Published var latestEvent: GenerationEvent?
    @Published var isReady = true
    @Published var visibleErrorMessage: String?

    var unsupportedModes: Set<GenerationMode> = []
    var holdsGeneration = false
    var failsCancellation = false
    private(set) var generateRequests: [GenerationRequest] = []
    private(set) var loadedModelIDs: [String] = []
    private(set) var cancellationReasons: [GenerationCancellationReason] = []
    private(set) var trimLevels: [NativeMemoryTrimLevel] = []
    private(set) var proactiveWarmAllowances: [Bool] = []
    private(set) var bandTransitions: [BandTransition] = []
    private(set) var prewarmCount = 0
    private(set) var prefetchCount = 0
    private(set) var ensureLoadedCount = 0
    private(set) var clearGenerationActivityCount = 0
    private var pendingGeneration: CheckedContinuation<GenerationResult, any Error>?
    private var pendingRequest: GenerationRequest?
    /// A prefetch that loads the model as the real engine does: `.starting`
    /// while it runs, `.loaded` when it ends.
    var prefetchLoadsModel = false
    /// Holds a prefetch open until `releasePrefetch()`.
    var holdsPrefetch = false
    private var pendingPrefetch: CheckedContinuation<Void, Never>?
    /// Whether the calling task was cancelled when each prefetch ended.
    private(set) var prefetchSawCancellation: [Bool] = []

    var isHoldingPrefetch: Bool { pendingPrefetch != nil }

    func releasePrefetch() {
        let pending = pendingPrefetch
        pendingPrefetch = nil
        pending?.resume()
    }

    init(modelRegistry: any ModelRegistry) {
        self.modelRegistry = modelRegistry
    }

    static func unsupportedReason(for mode: GenerationMode) -> String {
        "fixture refuses \(mode.rawValue)"
    }

    /// Completes the held generation with its successful result.
    func releaseGeneration() {
        guard let pendingGeneration, let pendingRequest else { return }
        self.pendingGeneration = nil
        self.pendingRequest = nil
        pendingGeneration.resume(returning: Self.result(for: pendingRequest))
    }

    private static func result(for request: GenerationRequest) -> GenerationResult {
        GenerationResult(
            audioPath: request.outputPath,
            durationSeconds: 1,
            streamSessionDirectory: nil,
            usedStreaming: false
        )
    }

    func supportDecision(for request: GenerationRequest) -> GenerationSupportDecision {
        unsupportedModes.contains(request.mode)
            ? .unsupported(reason: Self.unsupportedReason(for: request.mode))
            : .supported(.nativeMLX)
    }

    func start() {}
    func stop() {}
    func initialize(appSupportDirectory: URL) async throws {}
    func ping() async throws -> Bool { true }

    func loadModel(id: String) async throws {
        loadedModelIDs.append(id)
    }

    /// Holds an unload open until `releaseUnload()`.
    var holdsUnload = false
    private var pendingUnload: CheckedContinuation<Void, Never>?
    private(set) var unloadCount = 0

    var isHoldingUnload: Bool { pendingUnload != nil }

    func releaseUnload() {
        let pending = pendingUnload
        pendingUnload = nil
        pending?.resume()
    }

    func unloadModel() async throws {
        unloadCount += 1
        if holdsUnload {
            await withCheckedContinuation { pendingUnload = $0 }
        }
        loadState = .idle
    }

    func prepareAudio(_ request: AudioPreparationRequest) async throws -> AudioNormalizationResult {
        throw StoreFixtureUnexpectedCall()
    }

    func ensureModelLoadedIfNeeded(id: String) async { ensureLoadedCount += 1 }
    func prewarmModelIfNeeded(for request: GenerationRequest) async { prewarmCount += 1 }
    func ensureCloneReferencePrimed(modelID: String, reference: CloneReference) async throws {}
    func cancelClonePreparationIfNeeded() async {}

    func generate(_ request: GenerationRequest) async throws -> GenerationResult {
        generateRequests.append(request)
        guard holdsGeneration else { return Self.result(for: request) }
        pendingRequest = request
        return try await withCheckedThrowingContinuation { continuation in
            pendingGeneration = continuation
        }
    }

    func cancelActiveGeneration(reason: GenerationCancellationReason) async throws {
        cancellationReasons.append(reason)
        if failsCancellation {
            throw StoreFixtureCancellationFailure()
        }
        if let pendingGeneration {
            self.pendingGeneration = nil
            pendingRequest = nil
            pendingGeneration.resume(throwing: CancellationError())
        }
    }

    func listPreparedVoices() async throws -> [PreparedVoice] { [] }

    func preparePreparedVoiceCandidate(
        name: String,
        audioPath: String,
        transcript: String?,
        replacingVoiceID: String?
    ) async throws -> PreparedVoiceCandidate {
        throw StoreFixtureUnexpectedCall()
    }

    func commitPreparedVoiceCandidate(id: UUID) async throws -> PreparedVoice {
        throw StoreFixtureUnexpectedCall()
    }

    func discardPreparedVoiceCandidate(id: UUID) async throws {}

    func enrollPreparedVoice(name: String, audioPath: String, transcript: String?) async throws -> PreparedVoice {
        throw StoreFixtureUnexpectedCall()
    }

    func deletePreparedVoice(id: String) async throws {}

    func importReferenceAudio(from sourceURL: URL) throws -> ImportedReferenceAudio {
        throw StoreFixtureUnexpectedCall()
    }

    func exportGeneratedAudio(from sourceURL: URL, to destinationURL: URL) throws -> ExportedDocument {
        throw StoreFixtureUnexpectedCall()
    }

    func clearGenerationActivity() { clearGenerationActivityCount += 1 }
    func clearVisibleError() { visibleErrorMessage = nil }

    func prefetchInteractiveReadinessIfNeeded(
        for request: GenerationRequest
    ) async -> InteractivePrefetchDiagnostics? {
        prefetchCount += 1
        if prefetchLoadsModel {
            loadState = .starting
        }
        if holdsPrefetch {
            await withCheckedContinuation { pendingPrefetch = $0 }
        }
        let cancelled = Task.isCancelled
        prefetchSawCancellation.append(cancelled)
        if prefetchLoadsModel {
            // As MLXTTSEngine does when the runtime holds no weights, a cold
            // load cancelled from .starting reports .idle.
            loadState = cancelled ? .idle : .loaded(modelID: request.modelID)
        }
        return nil
    }

    func setVisibleError(_ message: String?) { visibleErrorMessage = message }

    func setAllowsProactiveWarmOperations(_ allow: Bool) {
        proactiveWarmAllowances.append(allow)
    }

    func recordApplicationMemoryWarning(reason: String) async {}

    func recordMemoryBudgetTransition(
        from previousBand: IOSMemoryPressureBand,
        to currentBand: IOSMemoryPressureBand,
        reason: String
    ) async {
        bandTransitions.append(BandTransition(from: previousBand, to: currentBand))
    }

    func trimMemory(level: NativeMemoryTrimLevel, reason: String) async {
        trimLevels.append(level)
    }
}

/// The streaming shape of every production engine (`MLXTTSEngine`): the store
/// skips its snapshot chunk forwarding for it.
@MainActor
private final class StreamingStoreFixtureEngine: StoreFixtureEngine, TTSEngineEventStreaming {
    nonisolated func events(for generationID: UUID) -> AsyncStream<GenerationEvent> {
        AsyncStream { $0.finish() }
    }
}

@MainActor
private final class SnapshotRecorder {
    var snapshots: [TTSEngineFrontendState] = []
}

/// PA-19: the shared engine store both apps host, driven through the real
/// `AnyTTSEngineBackend` over a fake engine. Covers generation ownership and
/// admission, typed cancellation through the engine barrier, memory admission and
/// post-generation trim, proactive-warm gating, critical-pressure relief and the
/// frontend state the shells read.
@MainActor
final class TTSEngineStoreTests: XCTestCase {
    private var contractURL: URL {
        URL(fileURLWithPath: #filePath).deletingLastPathComponent()
            .deletingLastPathComponent().deletingLastPathComponent()
            .appendingPathComponent("Sources/Resources/qwenvoice_contract.json")
    }

    private func makeEngine() throws -> StoreFixtureEngine {
        StoreFixtureEngine(modelRegistry: try ContractBackedModelRegistry(manifestURL: contractURL))
    }

    private func makeStore(engine: StoreFixtureEngine, dial: MemoryHeadroomDial) -> TTSEngineStore {
        let backend = AnyTTSEngineBackend(
            engine: engine,
            supportsSavedVoiceMutation: true,
            supportsModelManagementMutation: true,
            supportedModes: [.custom, .design, .clone],
            voiceCloningConsent: { VoiceCloningConsentPolicy(isConsentRecorded: true) }
        )
        return TTSEngineStore(
            backend: backend,
            memoryBudgetPolicy: .iPhoneShippingDefault,
            memorySnapshotProvider: { dial.snapshot() }
        )
    }

    private func request(_ mode: GenerationMode = .custom) -> GenerationRequest {
        let payload: GenerationRequest.Payload
        switch mode {
        case .custom:
            payload = .custom(speakerID: "aiden", deliveryStyle: nil)
        case .design:
            payload = .design(voiceDescription: "A clear narrator.", deliveryStyle: nil)
        case .clone:
            payload = .clone(reference: CloneReference(audioPath: "/nonexistent/pa19-reference.wav", transcript: "Hello."))
        }
        return GenerationRequest(
            mode: mode,
            modelID: "pro_\(mode.rawValue)",
            text: "Engine store fixture.",
            outputPath: "/nonexistent/pa19-\(UUID().uuidString).wav",
            shouldStream: false,
            payload: payload
        )
    }

    /// Lets the main actor run the store's queued state syncs and task continuations.
    private func waitUntil(
        _ description: String,
        timeout: Duration = .seconds(2),
        file: StaticString = #filePath,
        line: UInt = #line,
        _ condition: () -> Bool
    ) async {
        let clock = ContinuousClock()
        let deadline = clock.now.advanced(by: timeout)
        while !condition() {
            guard clock.now < deadline else {
                XCTFail("Timed out waiting for \(description)", file: file, line: line)
                return
            }
            await Task.yield()
            try? await Task.sleep(nanoseconds: 1_000_000)
        }
    }

    private func assertGenerationRefused(
        by store: TTSEngineStore,
        _ request: GenerationRequest,
        file: StaticString = #filePath,
        line: UInt = #line,
        where matches: (TTSEngineError) -> Bool
    ) async {
        do {
            _ = try await store.generate(request)
            XCTFail("Expected the store to refuse the generation", file: file, line: line)
        } catch let error as TTSEngineError {
            XCTAssertTrue(matches(error), "Unexpected refusal \(error)", file: file, line: line)
        } catch {
            XCTFail("Unexpected error \(error)", file: file, line: line)
        }
    }

    private static func isGenerationFailure(_ error: TTSEngineError) -> Bool {
        if case .generationFailed = error { return true }
        return false
    }

    private static func isInsufficientMemory(_ error: TTSEngineError) -> Bool {
        if case .insufficientMemory = error { return true }
        return false
    }

    // MARK: - Generation ownership

    func testGenerationHoldsOwnershipUntilTheEngineReturnsAndRefusesAnOverlappingTake() async throws {
        let engine = try makeEngine()
        let store = makeStore(engine: engine, dial: MemoryHeadroomDial(megabytes: MemoryHeadroomDial.healthy))
        engine.holdsGeneration = true
        XCTAssertFalse(store.hasActiveGeneration)

        let first = request()
        let generation = Task { try await store.generate(first) }
        await waitUntil("the engine to receive the take") { engine.generateRequests.count == 1 }

        XCTAssertTrue(store.hasActiveGeneration)
        // The store mints the generation identity the engine events are keyed by.
        XCTAssertNotNil(engine.generateRequests.first?.generationID)
        await assertGenerationRefused(by: store, request(), where: Self.isGenerationFailure)
        XCTAssertEqual(engine.generateRequests.count, 1, "An overlapping take never reaches the engine")

        engine.releaseGeneration()
        let result = try await generation.value
        XCTAssertEqual(result.audioPath, first.outputPath)
        XCTAssertFalse(store.hasActiveGeneration)
        // A healthy band needs no post-generation trim.
        XCTAssertEqual(engine.trimLevels, [])

        engine.holdsGeneration = false
        _ = try await store.generate(request())
        XCTAssertEqual(engine.generateRequests.count, 2, "Admission reopens once the take returned")
    }

    func testUnsupportedRequestIsRefusedBeforeTheEngineOrAnyOwnership() async throws {
        let engine = try makeEngine()
        engine.unsupportedModes = [.design]
        let store = makeStore(engine: engine, dial: MemoryHeadroomDial(megabytes: MemoryHeadroomDial.healthy))

        XCTAssertEqual(
            store.supportDecision(for: request(.design)),
            .unsupported(reason: StoreFixtureEngine.unsupportedReason(for: .design))
        )
        await assertGenerationRefused(by: store, request(.design)) { error in
            error == .unsupportedRequest(StoreFixtureEngine.unsupportedReason(for: .design))
        }
        XCTAssertTrue(engine.generateRequests.isEmpty)
        XCTAssertFalse(store.hasActiveGeneration)
    }

    func testBackendActivityClosesAdmissionExceptWhilePreparingAVoiceReference() async throws {
        let engine = try makeEngine()
        let store = makeStore(engine: engine, dial: MemoryHeadroomDial(megabytes: MemoryHeadroomDial.healthy))

        engine.loadState = .running(modelID: "pro_custom", label: "Generating", fraction: nil)
        await waitUntil("the store to mirror backend activity") { store.hasActiveGeneration }
        await assertGenerationRefused(by: store, request(), where: Self.isGenerationFailure)
        XCTAssertTrue(engine.generateRequests.isEmpty)

        engine.loadState = .running(
            modelID: "pro_clone",
            label: EngineActivityLabels.preparingVoiceReference,
            fraction: nil
        )
        await waitUntil("reference preparation to leave admission open") { !store.hasActiveGeneration }
        _ = try await store.generate(request())
        XCTAssertEqual(engine.generateRequests.count, 1)
    }

    // MARK: - Cancellation barrier

    func testCancellationBarrierReleasesOwnershipAndCarriesTheTypedReason() async throws {
        let engine = try makeEngine()
        let store = makeStore(engine: engine, dial: MemoryHeadroomDial(megabytes: MemoryHeadroomDial.healthy))
        engine.holdsGeneration = true

        let take = request()
        let generation = Task { try await store.generate(take) }
        await waitUntil("the engine to receive the take") { engine.generateRequests.count == 1 }

        try await store.cancelActiveGeneration(reason: .shutdown)
        XCTAssertEqual(engine.cancellationReasons, [.shutdown])
        XCTAssertFalse(store.hasActiveGeneration, "The returned barrier releases ownership")

        do {
            _ = try await generation.value
            XCTFail("A cancelled take must not produce a result")
        } catch is CancellationError {
            // The engine's typed cancellation reaches the caller unchanged.
        }
        XCTAssertFalse(store.hasActiveGeneration)
        XCTAssertEqual(engine.trimLevels, [])
    }

    func testFailedCancellationBarrierKeepsOwnershipAndAdmissionClosed() async throws {
        let engine = try makeEngine()
        let store = makeStore(engine: engine, dial: MemoryHeadroomDial(megabytes: MemoryHeadroomDial.healthy))
        engine.holdsGeneration = true
        engine.failsCancellation = true

        let take = request()
        let generation = Task { try await store.generate(take) }
        await waitUntil("the engine to receive the take") { engine.generateRequests.count == 1 }

        do {
            try await store.cancelActiveGeneration()
            XCTFail("The failing barrier must surface its error")
        } catch is StoreFixtureCancellationFailure {
            // Termination was not proven.
        }
        XCTAssertEqual(engine.cancellationReasons, [.user])
        XCTAssertTrue(store.hasActiveGeneration, "Ownership stays until termination is proven")
        await assertGenerationRefused(by: store, request(), where: Self.isGenerationFailure)

        engine.releaseGeneration()
        _ = try await generation.value
        XCTAssertFalse(store.hasActiveGeneration)
    }

    // MARK: - Memory admission, trim and proactive warm

    func testCriticalMemoryRefusesModelLoadAndGenerationBeforeTheEngine() async throws {
        let engine = try makeEngine()
        let dial = MemoryHeadroomDial(megabytes: MemoryHeadroomDial.critical)
        let store = makeStore(engine: engine, dial: dial)
        XCTAssertEqual(store.currentMemoryContext().pressureBand, .critical)
        XCTAssertEqual(engine.proactiveWarmAllowances.last, false)

        do {
            try await store.loadModel(id: "pro_custom")
            XCTFail("A critical band must refuse model admission")
        } catch let error as TTSEngineError {
            XCTAssertTrue(Self.isInsufficientMemory(error), "\(error)")
        }
        XCTAssertEqual(engine.loadedModelIDs, [])
        await assertGenerationRefused(by: store, request(), where: Self.isInsufficientMemory)
        XCTAssertTrue(engine.generateRequests.isEmpty)
        XCTAssertFalse(store.hasActiveGeneration)

        dial.set(MemoryHeadroomDial.healthy)
        _ = try await store.generate(request())
        XCTAssertEqual(engine.generateRequests.count, 1)
        XCTAssertTrue(
            engine.bandTransitions.contains(.init(from: .critical, to: .healthy)),
            "The engine hears about the band change"
        )
        XCTAssertEqual(store.currentMemoryContext().pressureBand, .healthy)
    }

    func testGuardedMemoryAdmitsTheTakeHardTrimsAfterItAndBlocksProactiveWarm() async throws {
        let engine = try makeEngine()
        let store = makeStore(engine: engine, dial: MemoryHeadroomDial(megabytes: MemoryHeadroomDial.guarded))
        XCTAssertEqual(store.currentMemoryContext().pressureBand, .guarded)

        _ = try await store.generate(request())
        XCTAssertEqual(engine.generateRequests.count, 1, "Guarded pressure still admits generation")
        XCTAssertEqual(engine.trimLevels, [.hardTrim])
        XCTAssertFalse(store.hasActiveGeneration)

        await store.prewarmModelIfNeeded(for: request())
        let prefetched = await store.prefetchInteractiveReadinessIfNeeded(for: request())
        await store.ensureModelLoadedIfNeeded(id: "pro_custom")
        XCTAssertNil(prefetched)
        XCTAssertEqual(engine.prewarmCount, 0)
        XCTAssertEqual(engine.prefetchCount, 0)
        XCTAssertEqual(engine.ensureLoadedCount, 0)
        XCTAssertEqual(engine.proactiveWarmAllowances.last, false)
    }

    /// The store's thermal gate blocks proactive warm on a throttled host.
    private func skipIfThermalGateBlocksProactiveWarm() throws {
        let thermal = ProcessInfo.processInfo.thermalState
        try XCTSkipIf(
            thermal == .serious || thermal == .critical,
            "The store's thermal gate blocks proactive warm on a throttled host"
        )
    }

    func testHealthyMemoryLetsProactiveWarmReachTheEngine() async throws {
        try skipIfThermalGateBlocksProactiveWarm()
        let engine = try makeEngine()
        let store = makeStore(engine: engine, dial: MemoryHeadroomDial(megabytes: MemoryHeadroomDial.healthy))

        await store.prewarmModelIfNeeded(for: request())
        _ = await store.prefetchInteractiveReadinessIfNeeded(for: request())
        await store.ensureModelLoadedIfNeeded(id: "pro_custom")
        XCTAssertEqual(engine.prewarmCount, 1)
        XCTAssertEqual(engine.prefetchCount, 1)
        XCTAssertEqual(engine.ensureLoadedCount, 1)
        XCTAssertEqual(engine.proactiveWarmAllowances.last, true)
    }

    // MARK: - Critical-pressure relief

    func testCriticalReliefWithoutAGenerationFullyUnloadsOnce() async throws {
        let engine = try makeEngine()
        let store = makeStore(engine: engine, dial: MemoryHeadroomDial(megabytes: MemoryHeadroomDial.healthy))

        let outcome = await store.performCriticalMemoryPressureRelief(reason: "pa19_app_pressure")
        XCTAssertEqual(outcome, .completed)
        XCTAssertEqual(engine.cancellationReasons, [], "Nothing to cancel")
        XCTAssertEqual(engine.trimLevels, [.fullUnload])
        XCTAssertEqual(engine.clearGenerationActivityCount, 1)
        XCTAssertFalse(store.hasActiveGeneration)
    }

    func testCriticalReliefDuringATakeCancelsThroughTheBarrierBeforeUnloading() async throws {
        let engine = try makeEngine()
        let store = makeStore(engine: engine, dial: MemoryHeadroomDial(megabytes: MemoryHeadroomDial.healthy))
        engine.holdsGeneration = true

        let take = request()
        let generation = Task { try await store.generate(take) }
        await waitUntil("the engine to receive the take") { engine.generateRequests.count == 1 }

        let outcome = await store.performCriticalMemoryPressureRelief(reason: "pa19_app_pressure")
        XCTAssertEqual(outcome, .completed)
        XCTAssertEqual(engine.cancellationReasons, [.memoryPressure])
        XCTAssertEqual(engine.trimLevels, [.fullUnload])
        XCTAssertFalse(store.hasActiveGeneration, "Ownership returns only after the awaited unload")

        do {
            _ = try await generation.value
            XCTFail("The relieved take must not produce a result")
        } catch is CancellationError {
            // Cancelled for memory pressure.
        }
        XCTAssertEqual(engine.trimLevels, [.fullUnload], "A cancelled take is not trimmed again")
    }

    func testCriticalReliefNeverUnloadsWhenTheBarrierFails() async throws {
        let engine = try makeEngine()
        let store = makeStore(engine: engine, dial: MemoryHeadroomDial(megabytes: MemoryHeadroomDial.healthy))
        engine.holdsGeneration = true
        engine.failsCancellation = true

        let take = request()
        let generation = Task { try await store.generate(take) }
        await waitUntil("the engine to receive the take") { engine.generateRequests.count == 1 }

        let outcome = await store.performCriticalMemoryPressureRelief(reason: "pa19_app_pressure")
        XCTAssertEqual(outcome, .cancellationFailed)
        XCTAssertEqual(engine.trimLevels, [], "No unload may race compute that was not proven stopped")
        XCTAssertTrue(store.hasActiveGeneration)

        engine.releaseGeneration()
        _ = try await generation.value
        XCTAssertFalse(store.hasActiveGeneration)
    }

    // MARK: - Frontend state

    func testSustainedPerformanceActivityIsReferenceCounted() throws {
        let store = makeStore(engine: try makeEngine(), dial: MemoryHeadroomDial(megabytes: MemoryHeadroomDial.healthy))
        XCTAssertFalse(store.hasSustainedPerformanceActivity)

        store.beginSustainedPerformanceActivity()
        store.beginSustainedPerformanceActivity()
        store.endSustainedPerformanceActivity()
        XCTAssertTrue(store.hasSustainedPerformanceActivity, "One holder remains")
        store.endSustainedPerformanceActivity()
        XCTAssertFalse(store.hasSustainedPerformanceActivity)
        store.endSustainedPerformanceActivity()
        XCTAssertFalse(store.hasSustainedPerformanceActivity, "An unmatched end cannot go negative")
        store.beginSustainedPerformanceActivity()
        XCTAssertTrue(store.hasSustainedPerformanceActivity)
    }

    func testBackendStateChangesReachThePublishedFrontendState() async throws {
        let engine = try makeEngine()
        let store = makeStore(engine: engine, dial: MemoryHeadroomDial(megabytes: MemoryHeadroomDial.healthy))
        XCTAssertEqual(store.engineLifecycleState, .connected)

        engine.loadState = .loaded(modelID: "pro_custom")
        await waitUntil("the loaded model to reach the store") {
            store.loadState == .loaded(modelID: "pro_custom")
        }
        XCTAssertTrue(store.isReady)

        engine.isReady = false
        engine.visibleErrorMessage = "The fixture engine failed."
        await waitUntil("the failure to reach the store") {
            store.visibleErrorMessage == "The fixture engine failed."
        }
        XCTAssertFalse(store.isReady)
        XCTAssertEqual(store.engineLifecycleState, .failed)

        store.clearVisibleError()
        XCTAssertNil(store.visibleErrorMessage)
        XCTAssertEqual(store.engineLifecycleState, .idle)
    }

    /// The documented contract of `snapshotUpdates` ("fires once per applied
    /// frontend-state change"), which the macOS root shell's warmup coordinator
    /// relies on to see busy, idle, loaded and failed transitions. The send
    /// used to sit after the chunk-forwarding guards, so it never fired for an
    /// ordinary state change or for the streaming `MLXTTSEngine` (PA-31).
    func testSnapshotUpdatesFireForAnAppliedFrontendChange() async throws {
        let engine = try makeEngine()
        let store = makeStore(engine: engine, dial: MemoryHeadroomDial(megabytes: MemoryHeadroomDial.healthy))
        let recorder = SnapshotRecorder()
        let subscription = store.snapshotUpdates.sink { recorder.snapshots.append($0) }
        defer { subscription.cancel() }

        engine.loadState = .loaded(modelID: "pro_design")
        await waitUntil("the loaded model to reach the store") {
            store.loadState == .loaded(modelID: "pro_design")
        }

        await waitUntil("the snapshot bridge to report the change", timeout: .milliseconds(300)) {
            !recorder.snapshots.isEmpty
        }
        XCTAssertEqual(recorder.snapshots.last?.loadState, .loaded(modelID: "pro_design"))
    }

    /// The same contract with the streaming engine every app runs, whose store
    /// returns before the snapshot chunk forwarding (PA-31).
    func testSnapshotUpdatesFireForTheStreamingEngine() async throws {
        let engine = StreamingStoreFixtureEngine(
            modelRegistry: try ContractBackedModelRegistry(manifestURL: contractURL)
        )
        let store = makeStore(engine: engine, dial: MemoryHeadroomDial(megabytes: MemoryHeadroomDial.healthy))
        let recorder = SnapshotRecorder()
        let subscription = store.snapshotUpdates.sink { recorder.snapshots.append($0) }
        defer { subscription.cancel() }

        engine.loadState = .loaded(modelID: "pro_design")
        await waitUntil("the snapshot bridge to report the change") {
            recorder.snapshots.last?.loadState == .loaded(modelID: "pro_design")
        }
    }

    // MARK: - macOS warmup coordinator over the store's snapshot bridge (PA-31)

    private func warmupCoordinator(_ deviceClass: NativeDeviceMemoryClass) -> MacGenerationWarmupCoordinator {
        MacGenerationWarmupCoordinator(
            debounce: .milliseconds(1),
            customVoiceDebounce: .milliseconds(1),
            designDebounce: .milliseconds(1),
            cloneDebounce: .milliseconds(1),
            modeTransitionDebounce: .milliseconds(1),
            admissionPolicy: MacWarmupAdmissionPolicy(mode: .off, deviceClass: deviceClass)
        )
    }

    private func customWarmContext(
        _ deviceClass: NativeDeviceMemoryClass,
        speaker: String = "aiden"
    ) -> MacGenerationWarmupCoordinator.WarmupContext {
        MacGenerationWarmupCoordinator.WarmupContext(
            mode: .custom,
            modelID: "pro_custom",
            isModelAvailable: true,
            identity: .custom(
                speakerID: speaker,
                deliveryStyle: nil,
                deliveryInstructionCellID: nil,
                languageHint: "en"
            ),
            deviceClass: deviceClass
        )
    }

    /// A cold warm publishes `.starting`; the coordinator, which now sees every
    /// snapshot, must not cancel its own dispatched warm for it, and the
    /// finished warm counts as complete.
    func testAWarmKeepsRunningThroughTheBusyStateItPublishes() async throws {
        try skipIfThermalGateBlocksProactiveWarm()
        let engine = try makeEngine()
        engine.prefetchLoadsModel = true
        engine.holdsPrefetch = true
        let store = makeStore(engine: engine, dial: MemoryHeadroomDial(megabytes: MemoryHeadroomDial.healthy))
        let coordinator = warmupCoordinator(.mid16GBMac)
        let subscription = store.snapshotChanges.sink { coordinator.observe(snapshot: $0) }
        defer { subscription.cancel() }
        let context = customWarmContext(.mid16GBMac)

        coordinator.scheduleWarmupIfNeeded(context: context, snapshot: store.snapshot, ttsEngineStore: store)
        await waitUntil("the warm to reach the engine") { engine.isHoldingPrefetch }
        await waitUntil("the store to publish the cold load") { store.loadState == .starting }
        engine.releasePrefetch()
        await waitUntil("the warm to end") { engine.prefetchSawCancellation.count == 1 }

        XCTAssertEqual(engine.prefetchSawCancellation, [false])
        await waitUntil("the model to load") { store.loadState == .loaded(modelID: "pro_custom") }
        coordinator.scheduleWarmupIfNeeded(context: context, snapshot: store.snapshot, ttsEngineStore: store)
        try await Task.sleep(for: .milliseconds(30))
        XCTAssertEqual(engine.prefetchCount, 1, "A completed warm is not repeated for the same intent")
    }

    /// A keystroke that leaves the warm context unchanged keeps the running warm.
    func testTheSameIntentKeepsTheRunningWarm() async throws {
        try skipIfThermalGateBlocksProactiveWarm()
        let engine = try makeEngine()
        engine.prefetchLoadsModel = true
        engine.holdsPrefetch = true
        let store = makeStore(engine: engine, dial: MemoryHeadroomDial(megabytes: MemoryHeadroomDial.healthy))
        let coordinator = warmupCoordinator(.mid16GBMac)
        let subscription = store.snapshotChanges.sink { coordinator.observe(snapshot: $0) }
        defer { subscription.cancel() }
        let context = customWarmContext(.mid16GBMac)

        coordinator.scheduleWarmupIfNeeded(context: context, snapshot: store.snapshot, ttsEngineStore: store)
        await waitUntil("the warm to reach the engine") { engine.isHoldingPrefetch }
        coordinator.scheduleWarmupIfNeeded(context: context, snapshot: store.snapshot, ttsEngineStore: store)
        engine.releasePrefetch()
        await waitUntil("the warm to end") { engine.prefetchSawCancellation.count == 1 }
        try await Task.sleep(for: .milliseconds(30))

        XCTAssertEqual(engine.prefetchSawCancellation, [false])
        XCTAssertEqual(engine.prefetchCount, 1)
    }

    /// An intent that flips away and back while a warm runs (A, B, A, or a
    /// trip out of Studio and back) still ends warm for A.
    func testAnIntentThatFlipsBackDuringAWarmStillEndsWarm() async throws {
        try skipIfThermalGateBlocksProactiveWarm()
        let engine = try makeEngine()
        engine.prefetchLoadsModel = true
        engine.holdsPrefetch = true
        let store = makeStore(engine: engine, dial: MemoryHeadroomDial(megabytes: MemoryHeadroomDial.healthy))
        let coordinator = warmupCoordinator(.mid16GBMac)
        let subscription = store.snapshotChanges.sink { coordinator.observe(snapshot: $0) }
        defer { subscription.cancel() }
        let context = customWarmContext(.mid16GBMac)

        coordinator.scheduleWarmupIfNeeded(context: context, snapshot: store.snapshot, ttsEngineStore: store)
        await waitUntil("the warm to reach the engine") { engine.isHoldingPrefetch }
        coordinator.scheduleWarmupIfNeeded(
            context: customWarmContext(.mid16GBMac, speaker: "serena"),
            snapshot: store.snapshot,
            ttsEngineStore: store
        )
        coordinator.scheduleWarmupIfNeeded(context: context, snapshot: store.snapshot, ttsEngineStore: store)
        engine.holdsPrefetch = false
        engine.releasePrefetch()

        await waitUntil("the flipped-back intent to warm again") { engine.prefetchSawCancellation.count == 2 }
        try await Task.sleep(for: .milliseconds(30))
        XCTAssertEqual(engine.prefetchSawCancellation, [true, false])
        XCTAssertEqual(engine.prefetchCount, 2)
    }

    /// Leaving Studio while a cold warm runs keeps it (no intent is not a
    /// different warm intent), and nothing warms afterwards.
    func testLeavingStudioDuringAWarmKeepsItAndWarmsNothingElse() async throws {
        try skipIfThermalGateBlocksProactiveWarm()
        let engine = try makeEngine()
        engine.prefetchLoadsModel = true
        engine.holdsPrefetch = true
        let store = makeStore(engine: engine, dial: MemoryHeadroomDial(megabytes: MemoryHeadroomDial.healthy))
        let coordinator = warmupCoordinator(.mid16GBMac)
        let subscription = store.snapshotChanges.sink { coordinator.observe(snapshot: $0) }
        defer { subscription.cancel() }

        coordinator.scheduleWarmupIfNeeded(
            context: customWarmContext(.mid16GBMac),
            snapshot: store.snapshot,
            ttsEngineStore: store
        )
        await waitUntil("the warm to reach the engine") { engine.isHoldingPrefetch }
        coordinator.scheduleWarmupIfNeeded(context: nil, snapshot: store.snapshot, ttsEngineStore: store)
        engine.releasePrefetch()

        await waitUntil("the warm to end") { engine.prefetchSawCancellation.count == 1 }
        try await Task.sleep(for: .milliseconds(30))
        XCTAssertEqual(engine.prefetchSawCancellation, [false])
        XCTAssertEqual(engine.prefetchCount, 1)
    }

    /// A change of intent cancels the stale warm, which does not count as
    /// complete, and the new intent warms as soon as it ends.
    func testAChangeOfIntentCancelsTheStaleWarmAndWarmsTheNewIntent() async throws {
        try skipIfThermalGateBlocksProactiveWarm()
        let engine = try makeEngine()
        engine.prefetchLoadsModel = true
        engine.holdsPrefetch = true
        let store = makeStore(engine: engine, dial: MemoryHeadroomDial(megabytes: MemoryHeadroomDial.healthy))
        let coordinator = warmupCoordinator(.mid16GBMac)
        let subscription = store.snapshotChanges.sink { coordinator.observe(snapshot: $0) }
        defer { subscription.cancel() }
        let context = customWarmContext(.mid16GBMac)

        coordinator.scheduleWarmupIfNeeded(context: context, snapshot: store.snapshot, ttsEngineStore: store)
        await waitUntil("the warm to reach the engine") { engine.isHoldingPrefetch }
        let newIntent = customWarmContext(.mid16GBMac, speaker: "serena")
        coordinator.scheduleWarmupIfNeeded(context: newIntent, snapshot: store.snapshot, ttsEngineStore: store)
        engine.holdsPrefetch = false
        engine.releasePrefetch()

        await waitUntil("the new intent to warm without another request") {
            engine.prefetchSawCancellation.count == 2
        }
        XCTAssertEqual(engine.prefetchSawCancellation, [true, false])
        await waitUntil("the model to load") { store.loadState == .loaded(modelID: "pro_custom") }
        coordinator.scheduleWarmupIfNeeded(context: newIntent, snapshot: store.snapshot, ttsEngineStore: store)
        try await Task.sleep(for: .milliseconds(30))
        XCTAssertEqual(engine.prefetchCount, 2, "The new intent's warm completed")
    }

    /// A transition unloads the other model, then warms this one; the same
    /// intent arriving during the unload (a keystroke, a download progress
    /// tick) must not abort the second half.
    func testTheSameIntentDuringATransitionStillWarmsTheNewModel() async throws {
        try skipIfThermalGateBlocksProactiveWarm()
        let engine = try makeEngine()
        engine.prefetchLoadsModel = true
        engine.holdsUnload = true
        engine.loadState = .loaded(modelID: "pro_design")
        let store = makeStore(engine: engine, dial: MemoryHeadroomDial(megabytes: MemoryHeadroomDial.healthy))
        await waitUntil("the other model to reach the store") { store.loadState == .loaded(modelID: "pro_design") }
        let coordinator = warmupCoordinator(.mid16GBMac)
        let subscription = store.snapshotChanges.sink { coordinator.observe(snapshot: $0) }
        defer { subscription.cancel() }
        let context = customWarmContext(.mid16GBMac)

        coordinator.scheduleWarmupIfNeeded(context: context, snapshot: store.snapshot, ttsEngineStore: store)
        await waitUntil("the transition to unload the other model") { engine.isHoldingUnload }
        coordinator.scheduleWarmupIfNeeded(context: context, snapshot: store.snapshot, ttsEngineStore: store)
        engine.releaseUnload()

        await waitUntil("the new model to warm") { engine.prefetchSawCancellation.count == 1 }
        try await Task.sleep(for: .milliseconds(30))
        XCTAssertEqual(engine.prefetchSawCancellation, [false])
        XCTAssertEqual(engine.unloadCount, 1)
        XCTAssertEqual(engine.prefetchCount, 1)
    }

    /// On every tier a take and the idle unload after it keep the completed
    /// warm, so an unchanged composer (or a download progress tick) does not
    /// reload the model: the unload sticks.
    func testACompletedWarmSurvivesATakeAndAnIdleUnload() async throws {
        try skipIfThermalGateBlocksProactiveWarm()
        for deviceClass in [NativeDeviceMemoryClass.floor8GBMac, .mid16GBMac, .highMemoryMac] {
            try await assertCompletedWarmSurvivesATakeAndAnIdleUnload(deviceClass)
        }
    }

    private func assertCompletedWarmSurvivesATakeAndAnIdleUnload(_ deviceClass: NativeDeviceMemoryClass) async throws {
        let engine = try makeEngine()
        engine.prefetchLoadsModel = true
        let store = makeStore(engine: engine, dial: MemoryHeadroomDial(megabytes: MemoryHeadroomDial.healthy))
        let coordinator = warmupCoordinator(deviceClass)
        let subscription = store.snapshotChanges.sink { coordinator.observe(snapshot: $0) }
        defer { subscription.cancel() }
        let context = customWarmContext(deviceClass)

        coordinator.scheduleWarmupIfNeeded(context: context, snapshot: store.snapshot, ttsEngineStore: store)
        await waitUntil("the warm to end") { engine.prefetchSawCancellation.count == 1 }
        await waitUntil("the model to load") { store.loadState == .loaded(modelID: "pro_custom") }

        engine.loadState = .running(modelID: "pro_custom", label: "Generating", fraction: nil)
        await waitUntil("the take to reach the store") { store.hasActiveGeneration }
        engine.loadState = .idle
        await waitUntil("the idle unload to reach the store") { store.loadState == .idle }

        coordinator.scheduleWarmupIfNeeded(context: context, snapshot: store.snapshot, ttsEngineStore: store)
        try await Task.sleep(for: .milliseconds(30))
        XCTAssertEqual(engine.prefetchCount, 1, "The unload sticks on \(deviceClass)")
    }

    /// AUD-10: browsing History, Saved Voices or Settings carries no warm
    /// intent (the shell passes no context there), so on every Mac tier it
    /// neither warms a cold engine nor reloads weights an idle unload
    /// released. Entering Studio is the intent that warms.
    func testNavigationWithoutAStudioIntentNeverWarms() async throws {
        try skipIfThermalGateBlocksProactiveWarm()
        for deviceClass in [NativeDeviceMemoryClass.floor8GBMac, .mid16GBMac, .highMemoryMac] {
            try await assertNavigationWithoutAStudioIntentNeverWarms(deviceClass)
        }
    }

    private func assertNavigationWithoutAStudioIntentNeverWarms(_ deviceClass: NativeDeviceMemoryClass) async throws {
        let engine = try makeEngine()
        engine.prefetchLoadsModel = true
        let store = makeStore(engine: engine, dial: MemoryHeadroomDial(megabytes: MemoryHeadroomDial.healthy))
        let coordinator = warmupCoordinator(deviceClass)
        let subscription = store.snapshotChanges.sink { coordinator.observe(snapshot: $0) }
        defer { subscription.cancel() }

        browseOutsideStudio(coordinator, store: store)
        try await Task.sleep(for: .milliseconds(30))
        XCTAssertEqual(engine.prefetchCount, 0, "Browsing a cold engine warms nothing on \(deviceClass)")
        XCTAssertEqual(engine.ensureLoadedCount, 0)
        XCTAssertEqual(store.loadState, .idle)

        coordinator.scheduleWarmupIfNeeded(
            context: customWarmContext(deviceClass),
            snapshot: store.snapshot,
            ttsEngineStore: store
        )
        await waitUntil("entering Studio to warm") { engine.prefetchSawCancellation.count == 1 }
        await waitUntil("the model to load") { store.loadState == .loaded(modelID: "pro_custom") }

        engine.loadState = .idle
        await waitUntil("the idle unload to reach the store") { store.loadState == .idle }
        browseOutsideStudio(coordinator, store: store)
        try await Task.sleep(for: .milliseconds(30))
        XCTAssertEqual(engine.prefetchCount, 1, "Browsing does not reload the released weights on \(deviceClass)")
        XCTAssertEqual(engine.ensureLoadedCount, 0)
    }

    /// A destination change, a download progress tick or a variant change
    /// outside Studio each schedule with no context.
    private func browseOutsideStudio(_ coordinator: MacGenerationWarmupCoordinator, store: TTSEngineStore) {
        for _ in 0..<3 {
            coordinator.scheduleWarmupIfNeeded(context: nil, snapshot: store.snapshot, ttsEngineStore: store)
        }
    }
}
