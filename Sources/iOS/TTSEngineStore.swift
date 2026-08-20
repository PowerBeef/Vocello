import Combine
import Foundation
import OSLog
import QwenVoiceCore

extension Notification.Name {
    static let ttsEngineMemoryContextDidChange = Notification.Name("TTSEngineStoreMemoryContextDidChange")
}

enum IOSNativeDeviceFeatureGate {
    static func unsupportedReason(for mode: GenerationMode) -> String? {
        switch mode {
        case .custom, .design, .clone:
            return nil
        }
    }

    static func isModeSupported(
        _ mode: GenerationMode,
        declaredModes: Set<GenerationMode>
    ) -> Bool {
        declaredModes.contains(mode) && unsupportedReason(for: mode) == nil
    }

    static func unavailableMessage(for model: ModelDescriptor) -> String? {
        unsupportedReason(for: model.mode)
    }

    static func allowsModelDownloads(for model: ModelDescriptor) -> Bool {
        model.iosDownloadEligible && unavailableMessage(for: model) == nil
    }
}

@MainActor
final class TTSEngineStore: ObservableObject, TTSEngine {
    private static let memoryLogger = Logger(
        subsystem: "com.patricedery.vocello",
        category: "MemoryGuard"
    )

    @Published private(set) var loadState: EngineLoadState = .idle
    @Published private(set) var clonePreparationState: ClonePreparationState = .idle
    @Published private(set) var latestEvent: GenerationEvent?
    @Published private(set) var hasActiveGeneration = false
    /// Held across multi-take work (a long-form project run: segments, QC,
    /// assembly) so the fixed-refresh glass performance gate stays engaged for
    /// the whole run instead of flickering between segments. Mirrors the macOS
    /// `TTSEngineStore.hasSustainedPerformanceActivity` refcount.
    @Published private(set) var hasSustainedPerformanceActivity = false
    @Published private(set) var engineLifecycleState: EngineLifecycleState = .idle

    /// Combined performance-activity signal for the flip-scoped root-shell
    /// gate model (IUI-5 P2, mirroring the macOS `performanceActivityUpdates`).
    /// Emits the new value on every underlying publish; subscribers dedupe.
    var performanceActivityUpdates: AnyPublisher<Bool, Never> {
        $hasActiveGeneration
            .combineLatest($hasSustainedPerformanceActivity)
            .map { $0 || $1 }
            .eraseToAnyPublisher()
    }

    let modelRegistry: any ModelRegistry
    let supportsSavedVoiceMutation: Bool
    let supportsModelManagementMutation: Bool
    let supportedModes: Set<GenerationMode>

    var isReady: Bool { frontendState.isReady }
    var visibleErrorMessage: String? { frontendState.visibleErrorMessage }
    private(set) var frontendState: TTSEngineFrontendState

    private let backend: AnyTTSEngineBackend
    private let memoryBudgetPolicy: IOSMemoryBudgetPolicy
    private let memorySnapshotProvider: @Sendable () -> IOSMemorySnapshot
    private let diagnosticsRecorder: IOSDeviceDiagnosticsRecorder?
    private(set) var latestMemoryContext: IOSMemoryContext
    private var changeObserver: AnyCancellable?
    private var activeGenerationDepth = 0
    private var sustainedPerformanceDepth = 0
    private var lastForwardedChunkIdentity: GenerationChunkDeliveryIdentity?
    private var activeGenerationMemoryGuardTask: Task<Void, Never>?
    private var activeGenerationPeakMemoryContext: IOSMemoryContext?
    private var criticalMemoryActionInFlight = false
    private var lastLoggedMemoryBand: IOSMemoryPressureBand?
    private var debugForceCriticalOnceArmed = false
    /// Sustained-load thermal policy (roadmap P3): serious/critical thermal state
    /// gates PROACTIVE warm work (prewarm, clone priming) so the device can cool
    /// between takes. Generation itself is never thermally blocked — that would
    /// need a maintainer decision. `QVOICE_IOS_THERMAL_GATE=off` disables the gate.
    private var latestThermalState: ProcessInfo.ThermalState = ProcessInfo.processInfo.thermalState
    /// nonisolated(unsafe): written once during MainActor init, read only in deinit
    /// (when no other references remain) — satisfies strict concurrency for the
    /// non-Sendable NSObjectProtocol token.
    nonisolated(unsafe) private var thermalObserverToken: NSObjectProtocol?

    init(
        backend: AnyTTSEngineBackend,
        memoryBudgetPolicy: IOSMemoryBudgetPolicy = .iPhoneShippingDefault,
        memorySnapshotProvider: @escaping @Sendable () -> IOSMemorySnapshot = { IOSMemorySnapshot.capture(role: .app) }
    ) {
        self.backend = backend
        self.memoryBudgetPolicy = memoryBudgetPolicy
        self.memorySnapshotProvider = memorySnapshotProvider
        self.diagnosticsRecorder = IOSDeviceDiagnosticsRecorder.makeIfEnabled()
        // Runtime test knob (off unless QVOICE_IOS_MEMORY_GUARD_FORCE_CRITICAL_ONCE is set),
        // now available on the Release device build too (project rule: debug capabilities are
        // runtime-gated, not compiled out) so the memory guard can be exercised on hardware.
        self.debugForceCriticalOnceArmed = Self.debugForceCriticalOnceEnabled()
        let initialAppSnapshot = memorySnapshotProvider()
        self.latestMemoryContext = memoryBudgetPolicy.context(
            appSnapshot: initialAppSnapshot,
            reason: "init",
            source: "store"
        )
        self.modelRegistry = backend.modelRegistry
        self.supportsSavedVoiceMutation = backend.supportsSavedVoiceMutation
        self.supportsModelManagementMutation = backend.supportsModelManagementMutation
        self.supportedModes = backend.supportedModes
        let initialSnapshot = backend.snapshot()
        self.frontendState = initialSnapshot.withoutPreviewAudioPayload()
        syncFromSnapshot(initialSnapshot)
        applyMemoryPolicyContext(latestMemoryContext, notify: false)
        changeObserver = backend.stateDidChange
            .sink { [weak self] in
                Task { @MainActor [weak self] in
                    self?.syncFromBackend()
                }
            }
        startThermalObservation()
    }

    deinit {
        activeGenerationMemoryGuardTask?.cancel()
        if let thermalObserverToken {
            NotificationCenter.default.removeObserver(thermalObserverToken)
        }
    }

    /// Track `ProcessInfo.thermalState` transitions: record them to diagnostics
    /// (they explain sustained-load RTF sag in pulled telemetry) and feed the
    /// proactive-warm gate. Recording is diagnostics-gated; the gate is always on
    /// unless QVOICE_IOS_THERMAL_GATE=off.
    private func startThermalObservation() {
        thermalObserverToken = NotificationCenter.default.addObserver(
            forName: ProcessInfo.thermalStateDidChangeNotification,
            object: nil,
            queue: .main
        ) { [weak self] _ in
            MainActor.assumeIsolated {
                guard let self else { return }
                let state = ProcessInfo.processInfo.thermalState
                let previous = self.latestThermalState
                self.latestThermalState = state
                guard state != previous else { return }
                self.diagnosticsRecorder?.recordAction(
                    event: "thermal_state_changed",
                    reason: Self.thermalLabel(state),
                    context: self.latestMemoryContext,
                    message: "thermal \(Self.thermalLabel(previous)) → \(Self.thermalLabel(state))"
                )
            }
        }
    }

    private static func thermalLabel(_ state: ProcessInfo.ThermalState) -> String {
        switch state {
        case .nominal: return "nominal"
        case .fair: return "fair"
        case .serious: return "serious"
        case .critical: return "critical"
        @unknown default: return "unknown"
        }
    }

    private var thermalAllowsProactiveWarm: Bool {
        if RuntimeDebugGate.value(for: "QVOICE_IOS_THERMAL_GATE") == "off" {
            return true
        }
        switch latestThermalState {
        case .serious, .critical: return false
        default: return true
        }
    }

    /// Drain only the active generation's bounded stream. Per-generation
    /// subscriptions prevent stale chunks from a prior request from reaching
    /// live playback and let the engine account for every dropped event.
    private func chunkForwardingTask(for request: GenerationRequest) -> Task<Void, Never>? {
        guard let generationID = request.generationID,
              let events = backend.events(for: generationID) else {
            return nil
        }
        return Task { @MainActor [weak self] in
            for await event in events {
                guard let self else { return }
                guard case .chunk(let chunk) = event else { continue }
                guard chunk.previewAudio != nil || chunk.chunkPath != nil else { continue }
                NotificationCenter.default.post(
                    name: .generationChunkReceived,
                    object: self,
                    userInfo: [
                        "chunk": chunk,
                        "generationID": chunk.generationID as Any,
                        "requestID": chunk.requestID as Any,
                        "title": chunk.title,
                        "chunkPath": chunk.chunkPath as Any,
                        "streamSessionDirectory": chunk.streamSessionDirectory as Any,
                        "cumulativeDurationSeconds": chunk.cumulativeDurationSeconds as Any,
                    ]
                )
            }
        }
    }

    func supportsMode(_ mode: GenerationMode) -> Bool {
        IOSNativeDeviceFeatureGate.isModeSupported(mode, declaredModes: supportedModes)
    }

    func start() {
        backend.start()
        syncFromBackend()
    }

    func stop() {
        stopActiveGenerationMemoryGuard(reason: "store_stop")
        backend.stop()
        syncFromBackend()
    }

    func initialize(appSupportDirectory: URL) async throws {
        try await backend.initialize(appSupportDirectory)
        syncFromBackend()
        await refreshMemoryContext(reason: "initialize", source: "store")
        notifyMemoryContextDidChange()
    }

    func ping() async throws -> Bool {
        let result = try await backend.ping()
        syncFromBackend()
        return result
    }

    func supportDecision(for request: GenerationRequest) -> GenerationSupportDecision {
        if let reason = IOSNativeDeviceFeatureGate.unsupportedReason(for: request.mode) {
            return .unsupported(reason: reason)
        }
        return backend.supportDecision(for: request)
    }

    func loadModel(id: String) async throws {
        try await guardModelAdmission(shouldSurfaceError: false, reason: "load_model")
        try await backend.loadModel(id: id)
        syncFromBackend()
        await refreshMemoryContext(reason: "load_model_complete", source: "store")
        notifyMemoryContextDidChange()
    }

    func unloadModel() async throws {
        try await backend.unloadModel()
        diagnosticsRecorder?.recordAction(
            event: "unload_model",
            reason: "explicit_unload",
            context: latestMemoryContext
        )
        syncFromBackend()
        notifyMemoryContextDidChange()
    }

    func prepareAudio(_ request: AudioPreparationRequest) async throws -> AudioNormalizationResult {
        let result = try await backend.prepareAudio(request)
        syncFromBackend()
        return result
    }

    func ensureModelLoadedIfNeeded(id: String) async {
        guard await allowsProactiveWarmOperations(reason: "ensure_model_loaded") else { return }
        await backend.ensureModelLoadedIfNeeded(id: id)
        syncFromBackend()
        notifyMemoryContextDidChange()
    }

    func prewarmModelIfNeeded(for request: GenerationRequest) async {
        guard await allowsProactiveWarmOperations(reason: "prewarm_model") else { return }
        await backend.prewarmModelIfNeeded(for: request)
        syncFromBackend()
        notifyMemoryContextDidChange()
    }

    func prefetchInteractiveReadinessIfNeeded(
        for request: GenerationRequest
    ) async -> InteractivePrefetchDiagnostics? {
        guard await allowsProactiveWarmOperations(reason: "prefetch_interactive_readiness") else { return nil }
        let diagnostics = await backend.prefetchInteractiveReadinessIfNeeded(for: request)
        syncFromBackend()
        notifyMemoryContextDidChange()
        return diagnostics
    }

    func ensureCloneReferencePrimed(modelID: String, reference: CloneReference) async throws {
        guard await allowsProactiveWarmOperations(reason: "clone_reference_prime") else { return }
        try await backend.ensureCloneReferencePrimed(modelID: modelID, reference: reference)
        syncFromBackend()
        notifyMemoryContextDidChange()
    }

    func cancelClonePreparationIfNeeded() async {
        await backend.cancelClonePreparationIfNeeded()
        syncFromBackend()
        notifyMemoryContextDidChange()
    }

    func cancelActiveGeneration(reason: GenerationCancellationReason = .user) async throws {
        try await backend.cancelActiveGeneration(reason: reason)
        // The backend call is the terminal barrier. Keep ownership intact if
        // it throws so no observer can mistake a cancellation request for
        // proven compute termination and begin trimming live MLX state.
        // A store-owned critical-memory action also retains ownership after
        // this barrier until its awaited full unload completes.
        guard !criticalMemoryActionInFlight else {
            syncFromBackend()
            notifyMemoryContextDidChange()
            return
        }
        activeGenerationDepth = 0
        hasActiveGeneration = false
        syncFromBackend()
        notifyMemoryContextDidChange()
    }

    /// Handles an application-level critical-memory notification through the
    /// same store-owned terminal barrier used by the active-generation guard.
    /// Callers must not perform a second trim or release generation ownership.
    func performCriticalMemoryPressureRelief(reason: String) async -> CriticalMemoryReliefOutcome {
        let requiresCancellation = hasActiveGeneration
        guard beginCriticalMemoryAction() else { return .alreadyInFlight }
        let context = await refreshMemoryContext(reason: reason, source: "app_pressure")
        return await enforceCriticalMemoryContext(
            context,
            actionAlreadyClaimed: true,
            requiresCancellation: requiresCancellation
        )
    }

    func generate(_ request: GenerationRequest) async throws -> GenerationResult {
        if case .unsupported(let reason) = supportDecision(for: request) {
            throw MLXTTSEngineError.unsupportedRequest(reason)
        }
        guard !hasActiveGeneration, !criticalMemoryActionInFlight else {
            throw MLXTTSEngineError.generationFailed(
                "The engine is already generating audio or releasing memory. Wait for it to finish before starting another generation."
            )
        }
        try await guardModelAdmission(shouldSurfaceError: true, reason: "generation_admission")
        // Admission captures live memory asynchronously. Revalidate ownership
        // because a critical-pressure action may have claimed the runtime while
        // that snapshot was in flight.
        guard !hasActiveGeneration, !criticalMemoryActionInFlight else {
            throw MLXTTSEngineError.generationFailed(
                "The engine began releasing memory before generation could start. Wait for it to finish and try again."
            )
        }
        activeGenerationDepth += 1
        hasActiveGeneration = activeGenerationDepth > 0
        startActiveGenerationMemoryGuard(reason: "generation_active")
        defer {
            if criticalMemoryActionInFlight {
                // The memory-guard task owns this generation scope until its
                // cancellation barrier and awaited full unload both finish.
                // Cancelling that task here would make the UI appear idle
                // while MLX state is still being released.
                syncFromBackend()
            } else {
                stopActiveGenerationMemoryGuard(reason: "generation_finished")
                logActiveGenerationPeakMemoryContext()
                activeGenerationPeakMemoryContext = nil
                activeGenerationDepth = max(activeGenerationDepth - 1, 0)
                hasActiveGeneration = activeGenerationDepth > 0
                syncFromBackend()
            }
        }

        // The physical-device XCUITest benchmark uses the shared debug policy
        // to guarantee the first Custom and Design cells are genuinely cold.
        // Consume it immediately before generation so any earlier production
        // warm work cannot silently change the recorded matrix classification.
        if BenchForceColdPolicy.shouldUnloadBeforeGeneration {
            try await unloadModel()
        }

        let request = request.generationID == nil
            ? request.withGenerationID(UUID())
            : request
        let chunkForwardingTask = chunkForwardingTask(for: request)
        let result: GenerationResult
        do {
            result = try await backend.generate(request)
            await chunkForwardingTask?.value
        } catch {
            await chunkForwardingTask?.value
            throw error
        }
        let postGenerationContext = await refreshMemoryContext(reason: "post_generation", source: "store")
        let postGenerationBand = postGenerationContext.pressureBand
        if let trimLevel = memoryBudgetPolicy.postGenerationTrimLevel(for: postGenerationBand) {
            diagnosticsRecorder?.recordAction(
                event: "post_generation_trim",
                reason: "post_generation_\(postGenerationBand.rawValue)",
                context: postGenerationContext,
                trimLevel: trimLevel
            )
            await backend.trimMemory(
                level: trimLevel,
                reason: "post_generation_\(postGenerationBand.rawValue)"
            )
        }
        syncFromBackend()
        notifyMemoryContextDidChange()
        return result
    }

    func listPreparedVoices() async throws -> [PreparedVoice] {
        let voices = try await backend.listPreparedVoices()
        syncFromBackend()
        return voices
    }

    func preparePreparedVoiceCandidate(
        name: String,
        audioPath: String,
        transcript: String?,
        replacingVoiceID: String?
    ) async throws -> PreparedVoiceCandidate {
        let candidate = try await backend.preparePreparedVoiceCandidate(
            name: name,
            audioPath: audioPath,
            transcript: transcript,
            replacingVoiceID: replacingVoiceID
        )
        syncFromBackend()
        return candidate
    }

    func commitPreparedVoiceCandidate(id: UUID) async throws -> PreparedVoice {
        let voice = try await backend.commitPreparedVoiceCandidate(id: id)
        syncFromBackend()
        return voice
    }

    func discardPreparedVoiceCandidate(id: UUID) async throws {
        try await backend.discardPreparedVoiceCandidate(id: id)
        syncFromBackend()
    }

    func enrollPreparedVoice(name: String, audioPath: String, transcript: String?) async throws -> PreparedVoice {
        let voice = try await backend.enrollPreparedVoice(name: name, audioPath: audioPath, transcript: transcript)
        syncFromBackend()
        return voice
    }

    func deletePreparedVoice(id: String) async throws {
        try await backend.deletePreparedVoice(id: id)
        syncFromBackend()
    }

    // Protocol conformance only: the iPhone UI deliberately exposes no file-import
    // control (references come from the microphone or a saved Voice Design voice);
    // the headless fixture-enrollment diagnostics stage files directly instead.
    func importReferenceAudio(from sourceURL: URL) throws -> ImportedReferenceAudio {
        try backend.importReferenceAudio(from: sourceURL)
    }


    func exportGeneratedAudio(from sourceURL: URL, to destinationURL: URL) throws -> ExportedDocument {
        try backend.exportGeneratedAudio(from: sourceURL, to: destinationURL)
    }

    func beginSustainedPerformanceActivity() {
        sustainedPerformanceDepth += 1
        hasSustainedPerformanceActivity = true
    }

    func endSustainedPerformanceActivity() {
        sustainedPerformanceDepth = max(sustainedPerformanceDepth - 1, 0)
        hasSustainedPerformanceActivity = sustainedPerformanceDepth > 0
    }

    func clearGenerationActivity() {
        backend.clearGenerationActivity()
        syncFromBackend()
    }

    func clearVisibleError() {
        backend.clearVisibleError()
        syncFromBackend()
    }

    func setVisibleError(_ message: String?) {
        backend.setVisibleError(message)
        syncFromBackend()
    }

    nonisolated var memoryIndicatorBudgetPolicy: IOSMemoryBudgetPolicy {
        memoryBudgetPolicy
    }

    nonisolated var memoryIndicatorSnapshotProvider: @Sendable () -> IOSMemorySnapshot {
        memorySnapshotProvider
    }

    nonisolated func currentMemorySnapshot() -> IOSMemorySnapshot {
        memorySnapshotProvider()
    }

    func currentMemoryContext() -> IOSMemoryContext {
        latestMemoryContext
    }

    @discardableResult
    func refreshMemoryContext(reason: String, source: String = "store") async -> IOSMemoryContext {
        let previousBand = latestMemoryContext.pressureBand
        let appSnapshot = memorySnapshotProvider()
        // The engine runs IN-PROCESS (commit 7822a8a), so a context measures this single
        // app process. The old double-count failure mode — sampling the app twice (once as
        // the now-removed "engine extension") and tripping the aggregate-critical threshold
        // at ~2× the real footprint — is structurally gone.
        let context = memoryBudgetPolicy.context(
            appSnapshot: appSnapshot,
            reason: reason,
            source: source
        )
        let effectiveContext = contextApplyingDebugForcedBand(context)
        applyMemoryPolicyContext(effectiveContext)
        if previousBand != effectiveContext.pressureBand {
            await backend.recordMemoryBudgetTransition(
                from: previousBand,
                to: effectiveContext.pressureBand,
                reason: reason
            )
        }
        return effectiveContext
    }

    @discardableResult
    func refreshMemoryPolicy() -> IOSMemoryPressureBand {
        let context = memoryBudgetPolicy.context(
            appSnapshot: currentMemorySnapshot(),
            reason: "refresh_memory_policy",
            source: "store"
        )
        let effectiveContext = contextApplyingDebugForcedBand(context)
        applyMemoryPolicyContext(effectiveContext)
        return effectiveContext.pressureBand
    }

    func trimMemory(level: NativeMemoryTrimLevel, reason: String) async {
        await backend.trimMemory(level: level, reason: reason)
        diagnosticsRecorder?.recordAction(
            event: "trim_memory",
            reason: reason,
            context: latestMemoryContext,
            trimLevel: level
        )
        syncFromBackend()
        notifyMemoryContextDidChange()
    }

    func recordApplicationMemoryWarning(reason: String) async {
        await backend.recordApplicationMemoryWarning(reason: reason)
        diagnosticsRecorder?.recordAction(
            event: "application_memory_warning",
            reason: reason,
            context: latestMemoryContext
        )
    }

    private func notifyMemoryContextDidChange() {
        NotificationCenter.default.post(name: .ttsEngineMemoryContextDidChange, object: self)
    }

    private func syncFromBackend() {
        let snapshot = backend.snapshot()
        syncFromSnapshot(snapshot)
    }

    private func syncFromSnapshot(_ snapshot: TTSEngineFrontendState) {
        let rawLatestEvent = snapshot.latestEvent
        let retainedLatestEvent: GenerationEvent?
        if case .chunk = rawLatestEvent {
            // Streaming chunks are forwarded below through NotificationCenter
            // for playback. Publishing each one through this app-wide
            // ObservableObject invalidates every screen that observes engine
            // readiness, even when only the player needs the audio chunk.
            retainedLatestEvent = latestEvent
        } else {
            retainedLatestEvent = rawLatestEvent?.withoutPreviewAudioPayload()
        }
        let retainedSnapshot = TTSEngineFrontendState(
            isReady: snapshot.isReady,
            lifecycleState: snapshot.lifecycleState,
            loadState: snapshot.loadState,
            clonePreparationState: snapshot.clonePreparationState,
            latestEvent: retainedLatestEvent,
            visibleErrorMessage: snapshot.visibleErrorMessage
        )

        if frontendState != retainedSnapshot {
            frontendState = retainedSnapshot
        }
        if loadState != retainedSnapshot.loadState {
            loadState = retainedSnapshot.loadState
        }
        if clonePreparationState != retainedSnapshot.clonePreparationState {
            clonePreparationState = retainedSnapshot.clonePreparationState
        }
        if latestEvent != retainedLatestEvent {
            latestEvent = retainedLatestEvent
        }
        if engineLifecycleState != retainedSnapshot.lifecycleState {
            engineLifecycleState = retainedSnapshot.lifecycleState
        }
        let snapshotHasActiveGeneration: Bool
        if case .running(_, let label, _) = retainedSnapshot.loadState,
           label != EngineActivityLabels.preparingVoiceReference {
            snapshotHasActiveGeneration = true
        } else {
            snapshotHasActiveGeneration = false
        }
        let nextHasActiveGeneration = activeGenerationDepth > 0 || snapshotHasActiveGeneration
        if hasActiveGeneration != nextHasActiveGeneration {
            hasActiveGeneration = nextHasActiveGeneration
        }
        backend.setAllowsProactiveWarmOperations(
            memoryBudgetPolicy.allowsProactiveWarmOperations(for: latestMemoryContext.pressureBand)
        )

        // When the backend exposes its full event stream, a generation-scoped task forwards chunks
        // (with preview PCM intact); the snapshot's `latestEvent` is coalesced + preview-stripped,
        // so skip the lossy snapshot forward to avoid posting payload-less duplicates.
        guard !backend.supportsGenerationEventStreaming else { return }

        guard let latestEvent = rawLatestEvent,
              let chunkIdentity = latestEvent.chunkDeliveryIdentity,
              lastForwardedChunkIdentity != chunkIdentity else {
            return
        }
        lastForwardedChunkIdentity = chunkIdentity

        if case .chunk(let chunk) = latestEvent {
            guard chunk.previewAudio != nil || chunk.chunkPath != nil else { return }
            NotificationCenter.default.post(
                name: .generationChunkReceived,
                object: self,
                userInfo: [
                    "chunk": chunk,
                    "generationID": chunk.generationID as Any,
                    "requestID": chunk.requestID as Any,
                    "title": chunk.title,
                    "chunkPath": chunk.chunkPath as Any,
                    "streamSessionDirectory": chunk.streamSessionDirectory as Any,
                    "cumulativeDurationSeconds": chunk.cumulativeDurationSeconds as Any,
                ]
            )
        }
    }

    private func canAdmitModel(shouldSurfaceError: Bool, reason: String) async -> Bool {
        do {
            try await guardModelAdmission(shouldSurfaceError: shouldSurfaceError, reason: reason)
            return true
        } catch {
            return false
        }
    }

    private func guardModelAdmission(shouldSurfaceError: Bool, reason: String) async throws {
        let context = await refreshMemoryContext(reason: reason, source: "admission")
        diagnosticsRecorder?.recordMemoryContext(context, event: "model_admission_observed")
        guard memoryBudgetPolicy.allowsModelAdmission(for: context) else {
            diagnosticsRecorder?.recordAction(
                event: "model_admission_blocked",
                reason: reason,
                context: context
            )
            let message = memoryBudgetPolicy.modelAdmissionBlockMessage(
                for: context,
                perProcessAdmissionBand: context.pressureBand,
                allowsAggregateGuardedAdmission: false
            )
            throw TTSEngineError.insufficientMemory(message)
        }
    }

    private func allowsProactiveWarmOperations(reason: String) async -> Bool {
        // Proactive warm + clone-reference priming are gated ONLY by the live memory band
        // (the real safety — see `memoryBudgetPolicy.allowsProactiveWarmOperations`). The
        // former blanket "disabled on Release hardware" default was a pre-entitlement
        // caution that silently blocked clone priming (and prewarm); with the
        // increased-memory entitlement + the band guard, warm when the band is healthy on
        // all build configs. `QVOICE_IOS_DISABLE_PROACTIVE_PREFETCH=1` is an
        // optional escape hatch to force it off (A/B / battery testing).
        if RuntimeDebugGate.value(for: "QVOICE_IOS_DISABLE_PROACTIVE_PREFETCH") == "1" {
            diagnosticsRecorder?.recordAction(
                event: "proactive_warm_blocked",
                reason: "\(reason)_env_disabled",
                context: latestMemoryContext,
                message: "Proactive warm disabled via QVOICE_IOS_DISABLE_PROACTIVE_PREFETCH."
            )
            return false
        }
        // Sustained-load thermal gate (roadmap P3): don't add prewarm/priming heat
        // when the device is already serious/critical — generation still runs.
        if !thermalAllowsProactiveWarm {
            diagnosticsRecorder?.recordAction(
                event: "proactive_warm_blocked",
                reason: "\(reason)_thermal_\(Self.thermalLabel(latestThermalState))",
                context: latestMemoryContext,
                message: "Proactive warm blocked by thermal state \(Self.thermalLabel(latestThermalState))."
            )
            return false
        }
        let context = await refreshMemoryContext(reason: reason, source: "warm_gate")
        let allowed = memoryBudgetPolicy.allowsProactiveWarmOperations(for: context.pressureBand)
        if !allowed {
            diagnosticsRecorder?.recordAction(
                event: "proactive_warm_blocked",
                reason: reason,
                context: context
            )
        }
        return allowed
    }

    @discardableResult
    private func applyMemoryPolicyContext(
        _ context: IOSMemoryContext,
        notify: Bool = true
    ) -> IOSMemoryPressureBand {
        let band = context.pressureBand
        let previousBand = latestMemoryContext.pressureBand
        latestMemoryContext = context
        backend.setAllowsProactiveWarmOperations(
            memoryBudgetPolicy.allowsProactiveWarmOperations(for: band)
        )
        recordActiveGenerationPeakIfNeeded(context)
        diagnosticsRecorder?.recordMemoryContext(context, event: "memory_context")
        if previousBand != band {
            diagnosticsRecorder?.recordMemoryContext(
                context,
                event: "memory_band_transition",
                previousBand: previousBand
            )
        }
        logMemoryContextTransitionIfNeeded(context)
        if notify {
            notifyMemoryContextDidChange()
        }
        return band
    }

    private func startActiveGenerationMemoryGuard(reason: String) {
        stopActiveGenerationMemoryGuard(reason: "restart")
        activeGenerationPeakMemoryContext = nil
        activeGenerationMemoryGuardTask = Task { @MainActor [weak self] in
            guard let self else { return }
            let initialContext = await self.refreshMemoryContext(reason: reason, source: "active_generation_guard")
            if self.shouldEnforceCriticalMemoryContext(initialContext) {
                let outcome = await self.enforceCriticalMemoryContext(initialContext)
                if outcome == .completed {
                    return
                }
            }
            while !Task.isCancelled {
                try? await Task.sleep(nanoseconds: 1_000_000_000)
                guard !Task.isCancelled, self.hasActiveGeneration else { break }
                let sampledContext = await self.refreshMemoryContext(
                    reason: "active_generation_sample",
                    source: "active_generation_guard"
                )
                let context = self.contextApplyingDebugCriticalOnceIfNeeded(sampledContext)
                if self.shouldEnforceCriticalMemoryContext(context) {
                    let outcome = await self.enforceCriticalMemoryContext(context)
                    if outcome == .completed {
                        break
                    }
                }
            }
        }
    }

    private func stopActiveGenerationMemoryGuard(reason: String) {
        activeGenerationMemoryGuardTask?.cancel()
        activeGenerationMemoryGuardTask = nil
    }

    private func enforceCriticalMemoryContext(
        _ context: IOSMemoryContext,
        actionAlreadyClaimed: Bool = false,
        requiresCancellation: Bool = true
    ) async -> CriticalMemoryReliefOutcome {
        if !actionAlreadyClaimed {
            guard beginCriticalMemoryAction() else { return .alreadyInFlight }
        }
        Self.memoryLogger.fault(
            "Critical iOS memory context during \(context.reason, privacy: .public); aggregate=\(context.aggregatePressureBand.rawValue, privacy: .public), worst=\(context.worstProcessRole?.rawValue ?? "unknown", privacy: .public), headroomMB=\(context.minimumHeadroomBytes.map(Self.megabytesString) ?? "unknown", privacy: .public), combinedFootprintMB=\(context.combinedPhysFootprintBytes.map(Self.megabytesString) ?? "unknown", privacy: .public)"
        )
        diagnosticsRecorder?.recordAction(
            event: "critical_memory_action",
            reason: context.reason,
            context: context
        )

        if !requiresCancellation {
            await applyCriticalFullUnload(context)
            completeCriticalMemoryAction()
            return .completed
        }

        var cancellationFailureMessage: String?
        let outcome = await CriticalMemoryReliefExecutor.execute(
            cancel: { reason in
                do {
                    try await self.backend.cancelActiveGeneration(reason: reason)
                } catch {
                    cancellationFailureMessage = error.localizedDescription
                    throw error
                }
                self.diagnosticsRecorder?.recordAction(
                    event: "critical_generation_cancel",
                    reason: GenerationCancellationReason.memoryPressure.rawValue,
                    context: context
                )
            },
            applyRelief: {
                await self.applyCriticalFullUnload(context)
            },
            releaseOwnership: {
                self.completeCriticalMemoryAction()
            }
        )

        if outcome == .cancellationFailed {
            backend.setVisibleError(nil)
            diagnosticsRecorder?.recordAction(
                event: "critical_generation_cancel_failed",
                reason: context.reason,
                context: context,
                message: cancellationFailureMessage
            )
            // Never race a full unload against compute whose termination could
            // not be proven. Leave generation ownership intact, but release
            // the action claim so the still-running guard can retry later.
            criticalMemoryActionInFlight = false
            syncFromBackend()
            notifyMemoryContextDidChange()
        }

        return outcome
    }

    private func applyCriticalFullUnload(_ context: IOSMemoryContext) async {
        await backend.trimMemory(
            level: .fullUnload,
            reason: "critical_memory_context"
        )
        // This event is a completion boundary: it is written only after the
        // awaited full unload returns.
        diagnosticsRecorder?.recordAction(
            event: "critical_full_unload",
            reason: "critical_memory_context",
            context: context,
            trimLevel: .fullUnload
        )
        backend.clearGenerationActivity()
    }

    private func beginCriticalMemoryAction() -> Bool {
        guard !criticalMemoryActionInFlight else { return false }
        criticalMemoryActionInFlight = true
        // Preserve one store-owned generation scope even if the backend's
        // cancellation terminal races this MainActor task. `syncFromBackend`
        // therefore cannot re-enable generation while fullUnload is awaited.
        activeGenerationDepth = max(activeGenerationDepth, 1)
        hasActiveGeneration = true
        return true
    }

    private func completeCriticalMemoryAction() {
        logActiveGenerationPeakMemoryContext()
        activeGenerationPeakMemoryContext = nil
        activeGenerationDepth = 0
        hasActiveGeneration = false
        criticalMemoryActionInFlight = false
        syncFromBackend()
        notifyMemoryContextDidChange()
    }

    private func shouldEnforceCriticalMemoryContext(_ context: IOSMemoryContext) -> Bool {
        // Critical pressure during an active generation cancels the generation and fully
        // unloads the model. The env-forced test path is retained for diagnostics.
        if context.reason.contains("debug_force_critical_once") {
            return true
        }
        return context.pressureBand == .critical
    }

    private func recordActiveGenerationPeakIfNeeded(_ context: IOSMemoryContext) {
        guard hasActiveGeneration else { return }
        guard let currentPeak = activeGenerationPeakMemoryContext else {
            activeGenerationPeakMemoryContext = context
            return
        }
        if Self.isHigherPressure(context, than: currentPeak) {
            activeGenerationPeakMemoryContext = context
        }
    }

    private static func isHigherPressure(_ lhs: IOSMemoryContext, than rhs: IOSMemoryContext) -> Bool {
        if lhs.pressureBand.severityRank != rhs.pressureBand.severityRank {
            return lhs.pressureBand.severityRank > rhs.pressureBand.severityRank
        }
        let lhsFootprint = lhs.combinedPhysFootprintBytes ?? lhs.peakPhysFootprintBytes ?? lhs.peakResidentBytes ?? 0
        let rhsFootprint = rhs.combinedPhysFootprintBytes ?? rhs.peakPhysFootprintBytes ?? rhs.peakResidentBytes ?? 0
        return lhsFootprint > rhsFootprint
    }

    private func logMemoryContextTransitionIfNeeded(_ context: IOSMemoryContext) {
        guard lastLoggedMemoryBand != context.pressureBand else { return }
        lastLoggedMemoryBand = context.pressureBand
        Self.memoryLogger.notice(
            "iOS memory context \(context.pressureBand.rawValue, privacy: .public) from \(context.source, privacy: .public)/\(context.reason, privacy: .public); aggregate=\(context.aggregatePressureBand.rawValue, privacy: .public), worst=\(context.worstProcessRole?.rawValue ?? "unknown", privacy: .public), appFootprintMB=\(context.appSnapshot.physFootprintBytes.map(Self.megabytesString) ?? "unknown", privacy: .public), combinedFootprintMB=\(context.combinedPhysFootprintBytes.map(Self.megabytesString) ?? "unknown", privacy: .public), minHeadroomMB=\(context.minimumHeadroomBytes.map(Self.megabytesString) ?? "unknown", privacy: .public)"
        )
    }

    private func logActiveGenerationPeakMemoryContext() {
        guard let context = activeGenerationPeakMemoryContext else { return }
        diagnosticsRecorder?.recordMemoryContext(context, event: "active_generation_peak")
        Self.memoryLogger.notice(
            "iOS generation peak memory \(context.pressureBand.rawValue, privacy: .public); aggregate=\(context.aggregatePressureBand.rawValue, privacy: .public), worst=\(context.worstProcessRole?.rawValue ?? "unknown", privacy: .public), appFootprintMB=\(context.appSnapshot.physFootprintBytes.map(Self.megabytesString) ?? "unknown", privacy: .public), combinedFootprintMB=\(context.combinedPhysFootprintBytes.map(Self.megabytesString) ?? "unknown", privacy: .public), minHeadroomMB=\(context.minimumHeadroomBytes.map(Self.megabytesString) ?? "unknown", privacy: .public)"
        )
    }

    // Env-forced memory-band test knobs (below). Runtime-gated (no #if DEBUG) so they work
    // on the Release device build; both are inert unless their env var is set.
    private func contextApplyingDebugForcedBand(_ context: IOSMemoryContext) -> IOSMemoryContext {
        guard let forcedBand = Self.debugForcedMemoryBand(),
              forcedBand.severityRank > context.pressureBand.severityRank else {
            return context
        }
        return Self.context(
            context,
            overridingBand: forcedBand,
            reason: "\(context.reason)_debug_force_\(forcedBand.rawValue)"
        )
    }

    private func contextApplyingDebugCriticalOnceIfNeeded(_ context: IOSMemoryContext) -> IOSMemoryContext {
        guard debugForceCriticalOnceArmed else { return context }
        debugForceCriticalOnceArmed = false
        let forcedContext = Self.context(
            context,
            overridingBand: .critical,
            reason: "\(context.reason)_debug_force_critical_once"
        )
        applyMemoryPolicyContext(forcedContext)
        diagnosticsRecorder?.recordAction(
            event: "debug_force_critical_once",
            reason: forcedContext.reason,
            context: forcedContext
        )
        return forcedContext
    }

    private static func context(
        _ context: IOSMemoryContext,
        overridingBand band: IOSMemoryPressureBand,
        reason: String
    ) -> IOSMemoryContext {
        IOSMemoryContext(
            appSnapshot: context.appSnapshot,
            pressureBand: band,
            aggregatePressureBand: context.aggregatePressureBand,
            worstProcessRole: context.worstProcessRole ?? .app,
            reason: reason,
            source: context.source
        )
    }

    // Runtime diagnostics are inert unless the explicit repository debug mode is enabled.
    // This keeps the Release-only build topology without allowing an ambient environment
    // variable to alter production memory policy.
    private static func debugForcedMemoryBand(
        environment: [String: String] = ProcessInfo.processInfo.environment
    ) -> IOSMemoryPressureBand? {
        switch RuntimeDebugGate.value(
            for: "QVOICE_IOS_MEMORY_GUARD_FORCE_BAND",
            environment: environment
        )?
            .trimmingCharacters(in: .whitespacesAndNewlines)
            .lowercased() {
        case "guarded":
            return .guarded
        default:
            return nil
        }
    }

    private static func debugForceCriticalOnceEnabled(
        environment: [String: String] = ProcessInfo.processInfo.environment
    ) -> Bool {
        switch RuntimeDebugGate.value(
            for: "QVOICE_IOS_MEMORY_GUARD_FORCE_CRITICAL_ONCE",
            environment: environment
        )?
            .trimmingCharacters(in: .whitespacesAndNewlines)
            .lowercased() {
        case "1", "true", "yes", "on":
            return true
        default:
            return false
        }
    }

    private static func megabytesString(_ bytes: UInt64) -> String {
        String(format: "%.1f", Double(bytes) / 1_048_576)
    }

}

@MainActor
final class AnyTTSEngineBackend {
    let modelRegistry: any ModelRegistry
    let supportsSavedVoiceMutation: Bool
    let supportsModelManagementMutation: Bool
    let supportedModes: Set<GenerationMode>
    let stateDidChange: AnyPublisher<Void, Never>
    /// Full ordered per-generation stream with preview PCM intact.
    let supportsGenerationEventStreaming: Bool
    private let eventsBlock: (UUID) -> AsyncStream<GenerationEvent>?

    private let snapshotBlock: () -> TTSEngineFrontendState
    private let supportDecisionBlock: (GenerationRequest) -> GenerationSupportDecision
    private let startBlock: () -> Void
    private let stopBlock: () -> Void
    private let initializeBlock: (URL) async throws -> Void
    private let pingBlock: () async throws -> Bool
    private let loadModelBlock: (String) async throws -> Void
    private let unloadModelBlock: () async throws -> Void
    private let prepareAudioBlock: (AudioPreparationRequest) async throws -> AudioNormalizationResult
    private let ensureModelLoadedIfNeededBlock: (String) async -> Void
    private let prewarmModelIfNeededBlock: (GenerationRequest) async -> Void
    private let prefetchInteractiveReadinessIfNeededBlock: (GenerationRequest) async -> InteractivePrefetchDiagnostics?
    private let ensureCloneReferencePrimedBlock: (String, CloneReference) async throws -> Void
    private let cancelClonePreparationIfNeededBlock: () async -> Void
    private let cancelActiveGenerationBlock: (GenerationCancellationReason) async throws -> Void
    private let generateBlock: (GenerationRequest) async throws -> GenerationResult
    private let listPreparedVoicesBlock: () async throws -> [PreparedVoice]
    private let preparePreparedVoiceCandidateBlock: (String, String, String?, String?) async throws -> PreparedVoiceCandidate
    private let commitPreparedVoiceCandidateBlock: (UUID) async throws -> PreparedVoice
    private let discardPreparedVoiceCandidateBlock: (UUID) async throws -> Void
    private let enrollPreparedVoiceBlock: (String, String, String?) async throws -> PreparedVoice
    private let deletePreparedVoiceBlock: (String) async throws -> Void
    private let exportGeneratedAudioBlock: (URL, URL) throws -> ExportedDocument
    private let importReferenceAudioBlock: (URL) throws -> ImportedReferenceAudio
    private let clearGenerationActivityBlock: () -> Void
    private let clearVisibleErrorBlock: () -> Void
    private let setVisibleErrorBlock: (String?) -> Void
    private let setAllowsProactiveWarmOperationsBlock: (Bool) -> Void
    private let recordApplicationMemoryWarningBlock: (String) async -> Void
    private let recordMemoryBudgetTransitionBlock: (
        IOSMemoryPressureBand,
        IOSMemoryPressureBand,
        String
    ) async -> Void
    private let trimMemoryBlock: (NativeMemoryTrimLevel, String) async -> Void
    private let captureMemorySnapshotBlock: (IOSMemoryProcessRole) async -> IOSMemorySnapshot?
    private let engineLifecycleStateBlock: () -> EngineLifecycleState

    init<Engine: TTSEngine & AnyObject>(
        engine: Engine,
        supportsSavedVoiceMutation: Bool,
        supportsModelManagementMutation: Bool,
        supportedModes: Set<GenerationMode>
    ) {
        self.modelRegistry = engine.modelRegistry
        self.supportsSavedVoiceMutation = supportsSavedVoiceMutation
        self.supportsModelManagementMutation = supportsModelManagementMutation
        self.supportedModes = supportedModes
        self.stateDidChange = engine.objectWillChange
            .map { _ in () }
            .eraseToAnyPublisher()
        if let eventStreamingEngine = engine as? any TTSEngineEventStreaming {
            self.supportsGenerationEventStreaming = true
            self.eventsBlock = { generationID in
                eventStreamingEngine.events(for: generationID)
            }
        } else {
            self.supportsGenerationEventStreaming = false
            self.eventsBlock = { _ in nil }
        }
        self.snapshotBlock = {
            TTSEngineFrontendState(
                isReady: engine.isReady,
                lifecycleState: Self.frontendLifecycleState(for: engine),
                loadState: engine.loadState,
                clonePreparationState: engine.clonePreparationState,
                latestEvent: engine.latestEvent,
                visibleErrorMessage: engine.visibleErrorMessage
            )
        }
        self.supportDecisionBlock = { engine.supportDecision(for: $0) }
        self.startBlock = { engine.start() }
        self.stopBlock = { engine.stop() }
        self.initializeBlock = { try await engine.initialize(appSupportDirectory: $0) }
        self.pingBlock = { try await engine.ping() }
        self.loadModelBlock = { try await engine.loadModel(id: $0) }
        self.unloadModelBlock = { try await engine.unloadModel() }
        self.prepareAudioBlock = { try await engine.prepareAudio($0) }
        self.ensureModelLoadedIfNeededBlock = { await engine.ensureModelLoadedIfNeeded(id: $0) }
        self.prewarmModelIfNeededBlock = { await engine.prewarmModelIfNeeded(for: $0) }
        if let engine = engine as? any TTSEngineRuntimeControlling {
            self.prefetchInteractiveReadinessIfNeededBlock = { await engine.prefetchInteractiveReadinessIfNeeded(for: $0) }
        } else {
            self.prefetchInteractiveReadinessIfNeededBlock = { _ in nil }
        }
        self.ensureCloneReferencePrimedBlock = { try await engine.ensureCloneReferencePrimed(modelID: $0, reference: $1) }
        self.cancelClonePreparationIfNeededBlock = { await engine.cancelClonePreparationIfNeeded() }
        if let engine = engine as? any ActiveGenerationCancellable {
            self.cancelActiveGenerationBlock = { reason in
                try await engine.cancelActiveGeneration(reason: reason)
            }
        } else {
            self.cancelActiveGenerationBlock = { _ in
                throw TTSEngineError.unsupportedRequest(
                    "This engine host does not support active-generation cancellation."
                )
            }
        }
        self.generateBlock = { try await engine.generate($0) }
        self.listPreparedVoicesBlock = { try await engine.listPreparedVoices() }
        self.preparePreparedVoiceCandidateBlock = {
            try await engine.preparePreparedVoiceCandidate(
                name: $0,
                audioPath: $1,
                transcript: $2,
                replacingVoiceID: $3
            )
        }
        self.commitPreparedVoiceCandidateBlock = { try await engine.commitPreparedVoiceCandidate(id: $0) }
        self.discardPreparedVoiceCandidateBlock = { try await engine.discardPreparedVoiceCandidate(id: $0) }
        self.enrollPreparedVoiceBlock = { try await engine.enrollPreparedVoice(name: $0, audioPath: $1, transcript: $2) }
        self.deletePreparedVoiceBlock = { try await engine.deletePreparedVoice(id: $0) }
        self.exportGeneratedAudioBlock = { try engine.exportGeneratedAudio(from: $0, to: $1) }
        self.importReferenceAudioBlock = { try engine.importReferenceAudio(from: $0) }
        self.clearGenerationActivityBlock = { engine.clearGenerationActivity() }
        self.clearVisibleErrorBlock = { engine.clearVisibleError() }
        if let engine = engine as? any TTSEngineRuntimeControlling {
            self.setVisibleErrorBlock = { engine.setVisibleError($0) }
            self.setAllowsProactiveWarmOperationsBlock = { engine.setAllowsProactiveWarmOperations($0) }
            self.recordApplicationMemoryWarningBlock = { reason in
                await engine.recordApplicationMemoryWarning(reason: reason)
            }
            self.recordMemoryBudgetTransitionBlock = { previousBand, currentBand, reason in
                await engine.recordMemoryBudgetTransition(
                    from: previousBand,
                    to: currentBand,
                    reason: reason
                )
            }
            self.trimMemoryBlock = { level, reason in
                await engine.trimMemory(level: level, reason: reason)
            }
        } else {
            self.setVisibleErrorBlock = { _ in }
            self.setAllowsProactiveWarmOperationsBlock = { _ in }
            self.recordApplicationMemoryWarningBlock = { _ in }
            self.recordMemoryBudgetTransitionBlock = { _, _, _ in }
            self.trimMemoryBlock = { _, _ in }
        }
        if let engine = engine as? any NativeMemoryReporting {
            self.captureMemorySnapshotBlock = { role in
                await engine.captureMemorySnapshot(role: role)
            }
        } else {
            self.captureMemorySnapshotBlock = { _ in nil }
        }
        self.engineLifecycleStateBlock = {
            Self.frontendLifecycleState(for: engine)
        }
    }

    fileprivate func snapshot() -> TTSEngineFrontendState {
        let snapshot = snapshotBlock()
        return TTSEngineFrontendState(
            isReady: snapshot.isReady,
            lifecycleState: engineLifecycleStateBlock(),
            loadState: snapshot.loadState,
            clonePreparationState: snapshot.clonePreparationState,
            latestEvent: snapshot.latestEvent,
            visibleErrorMessage: snapshot.visibleErrorMessage
        )
    }
    func supportDecision(for request: GenerationRequest) -> GenerationSupportDecision { supportDecisionBlock(request) }
    func start() { startBlock() }
    func stop() { stopBlock() }
    func initialize(_ appSupportDirectory: URL) async throws { try await initializeBlock(appSupportDirectory) }
    func ping() async throws -> Bool { try await pingBlock() }
    func loadModel(id: String) async throws { try await loadModelBlock(id) }
    func unloadModel() async throws { try await unloadModelBlock() }
    func prepareAudio(_ request: AudioPreparationRequest) async throws -> AudioNormalizationResult { try await prepareAudioBlock(request) }
    func ensureModelLoadedIfNeeded(id: String) async { await ensureModelLoadedIfNeededBlock(id) }
    func prewarmModelIfNeeded(for request: GenerationRequest) async { await prewarmModelIfNeededBlock(request) }
    func prefetchInteractiveReadinessIfNeeded(for request: GenerationRequest) async -> InteractivePrefetchDiagnostics? {
        await prefetchInteractiveReadinessIfNeededBlock(request)
    }
    func ensureCloneReferencePrimed(modelID: String, reference: CloneReference) async throws {
        try await ensureCloneReferencePrimedBlock(modelID, reference)
    }
    func cancelClonePreparationIfNeeded() async { await cancelClonePreparationIfNeededBlock() }
    func cancelActiveGeneration(reason: GenerationCancellationReason = .user) async throws {
        try await cancelActiveGenerationBlock(reason)
    }
    func events(for generationID: UUID) -> AsyncStream<GenerationEvent>? {
        eventsBlock(generationID)
    }
    func generate(_ request: GenerationRequest) async throws -> GenerationResult { try await generateBlock(request) }
    func listPreparedVoices() async throws -> [PreparedVoice] { try await listPreparedVoicesBlock() }
    func preparePreparedVoiceCandidate(
        name: String,
        audioPath: String,
        transcript: String?,
        replacingVoiceID: String?
    ) async throws -> PreparedVoiceCandidate {
        try await preparePreparedVoiceCandidateBlock(name, audioPath, transcript, replacingVoiceID)
    }
    func commitPreparedVoiceCandidate(id: UUID) async throws -> PreparedVoice {
        try await commitPreparedVoiceCandidateBlock(id)
    }
    func discardPreparedVoiceCandidate(id: UUID) async throws {
        try await discardPreparedVoiceCandidateBlock(id)
    }
    func enrollPreparedVoice(name: String, audioPath: String, transcript: String?) async throws -> PreparedVoice {
        try await enrollPreparedVoiceBlock(name, audioPath, transcript)
    }
    func deletePreparedVoice(id: String) async throws { try await deletePreparedVoiceBlock(id) }
    func exportGeneratedAudio(from sourceURL: URL, to destinationURL: URL) throws -> ExportedDocument {
        try exportGeneratedAudioBlock(sourceURL, destinationURL)
    }
    func importReferenceAudio(from sourceURL: URL) throws -> ImportedReferenceAudio {
        try importReferenceAudioBlock(sourceURL)
    }
    func clearGenerationActivity() { clearGenerationActivityBlock() }
    func clearVisibleError() { clearVisibleErrorBlock() }
    func setVisibleError(_ message: String?) { setVisibleErrorBlock(message) }
    func setAllowsProactiveWarmOperations(_ allow: Bool) { setAllowsProactiveWarmOperationsBlock(allow) }
    func recordMemoryBudgetTransition(
        from previousBand: IOSMemoryPressureBand,
        to currentBand: IOSMemoryPressureBand,
        reason: String
    ) async {
        await recordMemoryBudgetTransitionBlock(previousBand, currentBand, reason)
    }
    func recordApplicationMemoryWarning(reason: String) async {
        await recordApplicationMemoryWarningBlock(reason)
    }
    func trimMemory(level: NativeMemoryTrimLevel, reason: String) async { await trimMemoryBlock(level, reason) }
    func captureMemorySnapshot(role: IOSMemoryProcessRole) async -> IOSMemorySnapshot? {
        await captureMemorySnapshotBlock(role)
    }

    // The iOS engine runs in-process (MLXTTSEngine); there is no
    // separate extension process with a real lifecycle, so synthesize a health state.
    private static func frontendLifecycleState<Engine: TTSEngine>(
        for engine: Engine
    ) -> EngineLifecycleState {
        if engine.isReady {
            return .connected
        }
        if let visibleErrorMessage = engine.visibleErrorMessage,
           !visibleErrorMessage.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            return .failed
        }
        return .idle
    }
}
