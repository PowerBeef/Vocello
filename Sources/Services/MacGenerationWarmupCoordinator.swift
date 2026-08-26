import Combine
import Foundation
import QwenVoiceCore
import QwenVoiceNative

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
    private var pendingTask: Task<Void, Never>?
    private var pendingPlan: WarmupPlan?
    private var dispatchedContext: WarmupContext?
    private var completedContext: WarmupContext?
    private var revision: UInt64 = 0
    /// Warm-admission gate for constrained tiers (defers proactive warms
    /// under kernel memory pressure). Constructed eagerly so its pressure
    /// monitor is already listening before the first pressure transition —
    /// DispatchSource pressure events don't replay the in-progress level to
    /// a late starter. (On highMemoryMac / gate=off it starts no monitor.)
    private let admissionPolicy = MacWarmupAdmissionPolicy()

    init(
        debounce: Duration = .milliseconds(300),
        customVoiceDebounce: Duration = .milliseconds(100),
        designDebounce: Duration = .milliseconds(800),
        cloneDebounce: Duration = .milliseconds(500),
        modeTransitionDebounce: Duration = .milliseconds(900)
    ) {
        self.debounce = debounce
        self.customVoiceDebounce = customVoiceDebounce
        self.designDebounce = designDebounce
        self.cloneDebounce = cloneDebounce
        self.modeTransitionDebounce = modeTransitionDebounce
    }

    func scheduleWarmupIfNeeded(
        mode: GenerationMode?,
        modelID: String?,
        isModelAvailable: Bool,
        snapshot: TTSEngineSnapshot,
        ttsEngineStore: TTSEngineStore
    ) {
        if Self.isSuppressed {
            cancelPendingWarmup()
            return
        }
        guard let mode,
              let modelID,
              !modelID.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
            cancelPendingWarmup()
            return
        }

        let identity: WarmupIdentity
        switch mode {
        case .custom:
            identity = .custom(
                speakerID: GenerationSemantics.canonicalCustomWarmSpeaker,
                deliveryStyle: GenerationSemantics.canonicalCustomWarmInstruction(),
                deliveryInstructionCellID: nil,
                languageHint: Qwen3SupportedLanguage.english.rawValue
            )
        case .design, .clone:
            identity = .modelOnly
        }

        let context = WarmupContext(
            mode: mode,
            modelID: modelID,
            isModelAvailable: isModelAvailable,
            identity: identity,
            purpose: .livePreviewReadiness,
            deviceClass: NativeMemoryPolicyResolver.deviceClass()
        )
        scheduleWarmupIfNeeded(
            context: context,
            snapshot: snapshot,
            ttsEngineStore: ttsEngineStore
        )
    }

    func scheduleWarmupIfNeeded(
        context: WarmupContext?,
        snapshot: TTSEngineSnapshot,
        ttsEngineStore: TTSEngineStore
    ) {
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
        guard dispatchedContext == nil else {
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
            guard let self,
                  let ttsEngineStore,
                  !Task.isCancelled,
                  self.revision == scheduledRevision,
                  self.pendingPlan == plan,
                  self.dispatchedContext == nil,
                  ttsEngineStore.snapshot.isReady,
                  self.warmupAction(
                    snapshot: ttsEngineStore.snapshot,
                    context: plan.context
                  ) == plan.action else {
                return
            }

            // Warm-admission gate (constrained Macs): defer proactive warms
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
            defer {
                if self.dispatchedContext == plan.context {
                    self.dispatchedContext = nil
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
                guard !Task.isCancelled,
                      self.revision == scheduledRevision,
                      self.pendingPlan == nil,
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

            if case .loaded(let loadedModelID) = ttsEngineStore.snapshot.loadState,
               loadedModelID == plan.context.modelID {
                self.completedContext = plan.context
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
        if !shouldAllowAnyNavigationWarmup(snapshot: snapshot) {
            cancelPendingWarmup()
        }

        switch snapshot.loadState {
        case .idle:
            dispatchedContext = nil
            // On the floor tier, an idle transition is almost always the
            // engine's own idle-unload relieving memory. Clearing
            // completedContext here made the coordinator immediately re-warm
            // the ~2.3 GB model, so an 8 GB Mac churned unload→reload forever
            // and the unload never actually relieved anything. Keep the
            // context: the unload sticks, the next generation pays the
            // documented floor-tier cold start, and fresh user intent
            // (navigation to a different mode / model change) still creates
            // a different context that warms normally.
            if NativeMemoryPolicyResolver.deviceClass() != .floor8GBMac {
                completedContext = nil
            }
        case .loaded(let modelID):
            dispatchedContext = nil
            if completedContext?.modelID != modelID {
                completedContext = nil
            }
        case .failed:
            dispatchedContext = nil
            completedContext = nil
        case .starting, .running:
            completedContext = nil
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
