import Combine
import Foundation
import QwenVoiceCore

@MainActor
final class MacGenerationWarmupCoordinator: ObservableObject {
    /// Benchmark hook: when `QWENVOICE_SUPPRESS_WARMUP` is set (`1`/`true`/`on`/`yes`),
    /// all proactive warmup/prefetch is skipped, so a cold benchmark generation does —
    /// and records — its own model load instead of being silently pre-warmed. Resolved
    /// once per process; off in normal use (no behavior change).
    static let isSuppressed: Bool = {
        let value = RuntimeDebugGate.value(for: "QWENVOICE_SUPPRESS_WARMUP")?
            .trimmingCharacters(in: .whitespacesAndNewlines)
            .lowercased()
        guard let value else { return false }
        return ["1", "true", "on", "yes"].contains(value)
    }()

    enum WarmupPurpose: String, Equatable, Sendable {
        case finalGenerationReadiness
        case livePreviewReadiness
    }

    enum WarmupAggressiveness: String, Equatable, Sendable {
        case disabled
        case modelOnly
        case modelAndLightConditioning
        case fullInteractiveReadiness
    }

    enum WarmupIdentity: Equatable, Sendable {
        case modelOnly
        case custom(
            speakerID: String,
            deliveryStyle: String?,
            deliveryInstructionCellID: String?,
            languageHint: String?
        )
        case design(
            brief: String,
            deliveryStyle: String?,
            bucket: GenerationSemantics.DesignWarmBucket,
            languageHint: String?
        )
        case clone(referenceKey: String, preparedVoiceID: String?)
    }

    struct WarmupContext: Equatable, Sendable {
        let mode: GenerationMode
        let modelID: String
        let isModelAvailable: Bool
        let identity: WarmupIdentity
        let purpose: WarmupPurpose
        let deviceClass: NativeDeviceMemoryClass
        let cloneReference: CloneReference?

        init(
            mode: GenerationMode,
            modelID: String,
            isModelAvailable: Bool,
            identity: WarmupIdentity,
            purpose: WarmupPurpose = .finalGenerationReadiness,
            deviceClass: NativeDeviceMemoryClass = NativeMemoryPolicyResolver.deviceClass(),
            cloneReference: CloneReference? = nil
        ) {
            self.mode = mode
            self.modelID = modelID.trimmingCharacters(in: .whitespacesAndNewlines)
            self.isModelAvailable = isModelAvailable
            self.identity = identity
            self.purpose = purpose
            self.deviceClass = deviceClass
            self.cloneReference = cloneReference
        }
    }

    enum WarmupDecision: Equatable, Sendable {
        case skip(reason: String)
        case ensureModelLoaded(modelID: String)
        case prefetchInteractiveReadiness(GenerationRequest)
        case primeCloneReference(modelID: String, reference: CloneReference)

        var isModelOnly: Bool {
            if case .ensureModelLoaded = self {
                return true
            }
            return false
        }
    }

    private enum WarmupAction: Equatable {
        case warm(WarmupDecision)
        case transitionFromLoadedModel(WarmupDecision)
    }

    private struct WarmupPlan: Equatable {
        let context: WarmupContext
        let action: WarmupAction
    }

    private let debounce: Duration
    private let customVoiceDebounce: Duration
    private let designDebounce: Duration
    private let cloneDebounce: Duration
    private let modeTransitionDebounce: Duration
    /// The debounce of a plan not yet dispatched. `cancelPendingWarmup()`
    /// cancels only this: a dispatched warm moves to `dispatchedTask`.
    private var pendingTask: Task<Void, Never>?
    private var pendingPlan: WarmupPlan?
    /// The warm running now. Its task owns `dispatchedContext` and
    /// `completedContext` until it ends; only a change of intent cancels it.
    private var dispatchedTask: Task<Void, Never>?
    private var dispatchedContext: WarmupContext?
    /// The latest intent asked for while a warm was dispatched; scheduled when
    /// that warm ends if it differs from the warm's own context.
    private var intentWhileDispatched: DeferredIntent?
    private var completedContext: WarmupContext?
    private var revision: UInt64 = 0

    private struct DeferredIntent {
        let context: WarmupContext?
    }
    /// Warm-admission gate for every Mac tier (defers proactive warms
    /// under kernel memory pressure). Constructed eagerly so its pressure
    /// monitor is already listening before the first pressure transition —
    /// DispatchSource pressure events don't replay the in-progress level to
    /// a late starter. (With gate=off it starts no monitor.)
    private let admissionPolicy: MacWarmupAdmissionPolicy

    init(
        debounce: Duration = .milliseconds(300),
        customVoiceDebounce: Duration = .milliseconds(100),
        designDebounce: Duration = .milliseconds(800),
        cloneDebounce: Duration = .milliseconds(500),
        modeTransitionDebounce: Duration = .milliseconds(900),
        admissionPolicy: MacWarmupAdmissionPolicy = MacWarmupAdmissionPolicy()
    ) {
        self.debounce = debounce
        self.customVoiceDebounce = customVoiceDebounce
        self.designDebounce = designDebounce
        self.cloneDebounce = cloneDebounce
        self.modeTransitionDebounce = modeTransitionDebounce
        self.admissionPolicy = admissionPolicy
    }

    func scheduleWarmupIfNeeded(
        context: WarmupContext?,
        snapshot: TTSEngineSnapshot,
        ttsEngineStore: TTSEngineStore
    ) {
        // While a warm runs, a different warm intent makes it stale; the same
        // intent (a keystroke that leaves the context unchanged) keeps it, and
        // so does leaving Studio (no intent: a cancelled cold load would still
        // finish loading, and idle unload relieves memory later). Either way
        // the latest intent is scheduled when the warm ends (PA-31).
        if let dispatchedContext {
            if let context, context != dispatchedContext {
                dispatchedTask?.cancel()
            }
            intentWhileDispatched = DeferredIntent(context: context)
            return
        }
        if Self.isSuppressed {
            cancelPendingWarmup()
            return
        }
        guard let context,
              !context.modelID.isEmpty,
              context.isModelAvailable,
              snapshot.isReady else {
            cancelPendingWarmup()
            return
        }

        guard let action = warmupAction(snapshot: snapshot, context: context) else {
            cancelPendingWarmup()
            return
        }
        guard completedContext != context else {
            cancelPendingWarmup()
            return
        }
        let plan = WarmupPlan(context: context, action: action)
        guard pendingPlan != plan else { return }

        revision += 1
        let scheduledRevision = revision
        let debounce = debounce(for: plan)
        pendingPlan = plan
        pendingTask?.cancel()
        pendingTask = Task { @MainActor [weak self, weak ttsEngineStore] in
            do {
                try await Task.sleep(for: debounce)
            } catch {
                return
            }
            guard let self, let ttsEngineStore else { return }
            guard !Task.isCancelled,
                  self.revision == scheduledRevision,
                  self.pendingPlan == plan,
                  self.dispatchedContext == nil,
                  ttsEngineStore.snapshot.isReady,
                  self.warmupAction(
                    snapshot: ttsEngineStore.snapshot,
                    context: plan.context
                  ) == plan.action else {
                // A plan that no newer one replaced leaves, so the same intent
                // can schedule again once the engine is ready for it.
                if self.revision == scheduledRevision {
                    self.pendingPlan = nil
                    self.pendingTask = nil
                }
                return
            }

            // Warm-admission gate (every Mac tier, AUD-10): defer proactive warms
            // while the system is under memory pressure — checked at dispatch
            // time (after the debounce) so the freshest pressure level wins.
            // Clearing pendingPlan lets the next snapshot/draft change
            // reschedule once pressure releases. User generations are never
            // routed through this coordinator and stay ungated.
            if case .deferred = self.admissionPolicy.admit(
                contextDescription: "\(plan.context.mode.rawValue)/\(plan.context.purpose)"
            ) {
                self.pendingPlan = nil
                return
            }

            self.pendingPlan = nil
            self.dispatchedContext = plan.context
            // From here this task is the dispatched warm, which only a change
            // of intent cancels; the engine's busy states it publishes (a cold
            // load's .starting, a clone prime's .running) must not (PA-31).
            self.dispatchedTask = self.pendingTask
            self.pendingTask = nil
            // Every exit reconciles: only a warm that ran to the end with its
            // model loaded is complete (a cancelled one skipped its prewarm or
            // prime even when the weights loaded), and an intent that changed
            // meanwhile is scheduled now.
            var warmCompleted = false
            defer {
                if self.dispatchedContext == plan.context {
                    self.dispatchedContext = nil
                    self.dispatchedTask = nil
                    self.completedContext = warmCompleted ? plan.context : nil
                    let deferred = self.intentWhileDispatched
                    self.intentWhileDispatched = nil
                    // Also after a cancelled warm: an intent that flipped away
                    // and back (A, B, A) is this warm's own context, which
                    // the cancellation left cold. Only a change of intent
                    // cancels, so this retries once per recorded intent.
                    if let deferred, deferred.context != plan.context || Task.isCancelled {
                        self.scheduleWarmupIfNeeded(
                            context: deferred.context,
                            snapshot: ttsEngineStore.snapshot,
                            ttsEngineStore: ttsEngineStore
                        )
                    }
                }
            }

            switch plan.action {
            case .warm(let decision):
                await self.performWarmup(
                    decision,
                    ttsEngineStore: ttsEngineStore
                )
            case .transitionFromLoadedModel(let decision):
                do {
                    try await ttsEngineStore.unloadModel()
                } catch {
                    return
                }
                // A change of intent cancels this task; nothing else aborts
                // the second half of the transition.
                guard !Task.isCancelled,
                      ttsEngineStore.snapshot.isReady,
                      self.warmupAction(
                        snapshot: ttsEngineStore.snapshot,
                        context: plan.context
                      ) == .warm(decision) else {
                    return
                }
                await self.performWarmup(
                    decision,
                    ttsEngineStore: ttsEngineStore
                )
            }

            if !Task.isCancelled,
               case .loaded(let loadedModelID) = ttsEngineStore.snapshot.loadState,
               loadedModelID == plan.context.modelID {
                warmCompleted = true
            }
        }
    }

    func cancelPendingWarmup() {
        revision += 1
        pendingTask?.cancel()
        pendingTask = nil
        pendingPlan = nil
    }

    func observe(snapshot: TTSEngineSnapshot) {
        // While a dispatched warm runs, the busy and idle states are mostly
        // its own (a cold load, a clone prime, a transition's unload), the
        // engine serializes a user take behind it, and its task owns both
        // contexts until it ends (PA-31).
        guard dispatchedContext == nil else { return }
        if !shouldAllowAnyNavigationWarmup(snapshot: snapshot) {
            cancelPendingWarmup()
        }

        switch snapshot.loadState {
        case .loaded(let modelID):
            if completedContext?.modelID != modelID {
                completedContext = nil
            }
        case .failed:
            completedContext = nil
        case .idle, .starting, .running:
            // Only a different model or a failure invalidates a completed
            // warm, on every tier. An idle transition is almost always the
            // engine's own idle unload or pressure relief, and clearing the
            // context made the coordinator re-warm with no user intent (a
            // download progress tick is enough), churning unload→reload so the
            // unload never relieved anything; a take leaves its warm in the
            // prewarm cache. The unload sticks, the next generation pays the
            // cold start, and fresh intent (a different draft, mode or model)
            // is a different context that warms normally.
            break
        }
    }

    func aggressiveness(for context: WarmupContext) -> WarmupAggressiveness {
        switch context.deviceClass {
        case .floor8GBMac:
            switch context.mode {
            case .custom, .design:
                return .modelAndLightConditioning
            case .clone:
                return context.cloneReference == nil ? .modelOnly : .fullInteractiveReadiness
            }
        case .mid16GBMac, .highMemoryMac:
            return .fullInteractiveReadiness
        case .iPhonePro:
            return .modelOnly
        }
    }

    func warmupDecision(for context: WarmupContext) -> WarmupDecision {
        guard !context.modelID.isEmpty else {
            return .skip(reason: "missing-model-id")
        }
        guard context.isModelAvailable else {
            return .skip(reason: "model-unavailable")
        }

        switch aggressiveness(for: context) {
        case .disabled:
            return .skip(reason: "warmup-disabled")
        case .modelOnly:
            return .ensureModelLoaded(modelID: context.modelID)
        case .modelAndLightConditioning, .fullInteractiveReadiness:
            switch context.identity {
            case .custom:
                guard let request = interactivePrewarmRequest(for: context) else {
                    return .ensureModelLoaded(modelID: context.modelID)
                }
                return .prefetchInteractiveReadiness(request)
            case .design(let brief, _, _, _):
                guard !brief.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
                      let request = interactivePrewarmRequest(for: context) else {
                    return .ensureModelLoaded(modelID: context.modelID)
                }
                return .prefetchInteractiveReadiness(request)
            case .clone:
                guard let reference = context.cloneReference,
                      aggressiveness(for: context) == .fullInteractiveReadiness else {
                    return .ensureModelLoaded(modelID: context.modelID)
                }
                return .primeCloneReference(
                    modelID: context.modelID,
                    reference: reference
                )
            case .modelOnly:
                return .ensureModelLoaded(modelID: context.modelID)
            }
        }
    }

    private func warmupAction(
        snapshot: TTSEngineSnapshot,
        context: WarmupContext
    ) -> WarmupAction? {
        let decision = warmupDecision(for: context)
        if case .skip = decision {
            return nil
        }
        switch snapshot.loadState {
        case .idle:
            return .warm(decision)
        case .loaded(let modelID):
            if modelID == context.modelID {
                return decision.isModelOnly ? nil : .warm(decision)
            }
            return .transitionFromLoadedModel(decision)
        case .failed, .running, .starting:
            return nil
        }
    }

    private func shouldAllowAnyNavigationWarmup(snapshot: TTSEngineSnapshot) -> Bool {
        switch snapshot.loadState {
        case .idle, .loaded:
            return true
        case .failed, .running, .starting:
            return false
        }
    }

    private func debounce(for plan: WarmupPlan) -> Duration {
        switch plan.action {
        case .transitionFromLoadedModel:
            return modeTransitionDebounce
        case .warm:
            switch plan.context.mode {
            case .custom:
                return customVoiceDebounce
            case .design:
                if case .modelOnly = plan.context.identity {
                    return debounce
                }
                return designDebounce
            case .clone:
                if case .modelOnly = plan.context.identity {
                    return debounce
                }
                return cloneDebounce
            }
        }
    }

    private func performWarmup(
        _ decision: WarmupDecision,
        ttsEngineStore: TTSEngineStore
    ) async {
        switch decision {
        case .skip:
            return
        case .ensureModelLoaded(let modelID):
            await ttsEngineStore.ensureModelLoadedIfNeeded(id: modelID)
        case .prefetchInteractiveReadiness(let request):
            _ = await ttsEngineStore.prefetchInteractiveReadinessIfNeeded(for: request)
        case .primeCloneReference(let modelID, let reference):
            try? await ttsEngineStore.ensureCloneReferencePrimed(
                modelID: modelID,
                reference: reference
            )
        }
    }

    private func interactivePrewarmRequest(for context: WarmupContext) -> GenerationRequest? {
        let shouldStream = context.purpose == .livePreviewReadiness
        switch context.identity {
        case .custom(
            let speakerID,
            let deliveryStyle,
            let deliveryInstructionCellID,
            let languageHint
        ):
            let speaker = speakerID.trimmingCharacters(in: .whitespacesAndNewlines)
            return GenerationRequest(
                modelID: context.modelID,
                text: GenerationSemantics.canonicalCustomWarmText,
                outputPath: "",
                shouldStream: shouldStream,
                streamingInterval: GenerationSemantics.appStreamingInterval,
                languageHint: languageHint,
                payload: .custom(
                    speakerID: speaker.isEmpty ? GenerationSemantics.canonicalCustomWarmSpeaker : speaker,
                    deliveryStyle: deliveryStyle
                ),
                deliveryInstructionCellID: deliveryInstructionCellID
            )
        case .design(let brief, let deliveryStyle, let bucket, let languageHint):
            let trimmedBrief = brief.trimmingCharacters(in: .whitespacesAndNewlines)
            guard !trimmedBrief.isEmpty else { return nil }
            return GenerationRequest(
                modelID: context.modelID,
                text: GenerationSemantics.canonicalDesignWarmText(for: bucket),
                outputPath: "",
                shouldStream: shouldStream,
                streamingInterval: GenerationSemantics.appStreamingInterval,
                languageHint: languageHint,
                payload: .design(
                    voiceDescription: trimmedBrief,
                    deliveryStyle: deliveryStyle
                )
            )
        case .clone, .modelOnly:
            return nil
        }
    }
}
