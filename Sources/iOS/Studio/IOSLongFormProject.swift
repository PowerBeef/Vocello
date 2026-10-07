import AVFoundation
import Foundation
import Observation
import QwenVoiceCore

/// iOS long-form v4: scripts above the single-take limit run as a planned
/// project of ordinary sequential streaming takes — the same shipping design
/// the retired macOS `BatchGenerationRunner` proved (planner segmentation, per-segment
/// engine + app QC, bounded assembly into one joined WAV, fail-closed manifest
/// v4, one joined History row per project). Everything model-free is shared
/// QwenVoiceCore machinery; this file owns only the execution shell. The
/// platform-specific side effects (sampling variation preference, waveform
/// seed, diagnostics mirror, export, haptics, presentation copy) go through
/// `IOSLongFormPlatformHooks`, so the macOS app compiles this file by path
/// with its own adapter (`MacStudioLongFormPlatformHooks`) and the iOS adapter
/// (`IOSStudioLongFormPlatformHooks`) keeps the iOS behavior unchanged. The
/// shared player and the collaborators both apps share (timeline, History,
/// output location) go through `IOSLongFormAudioPlayback` and
/// `IOSLongFormProjectServices`, so `VocelloCoreTests` compiles this file by
/// path and runs it over a fake engine (PA-19).
///
/// Scope note: in-session resume reuses saved takes, and single-segment
/// regeneration mirrors the macOS replacement lineage: revision >= 2 with a
/// fresh recorded seed, per-segment QC that leaves the prior take untouched on
/// failure, reassembly around the accepted take, and fail-closed manifest
/// `replacements`. Regeneration is in-session only — the retained plan is the
/// identity authority, exactly like resume. Sampling is seed-deterministic, so
/// resume gives a segment whose take failed a fresh seed derived from the
/// failed one (`StudioRetakeSeed`) and records the seed it used (U10); a
/// pinned Studio seed is the plan's base seed (U11); and Auto resolves one
/// language for the whole script (`StudioScriptLanguage`, U03).

// MARK: - Platform hooks

/// Platform side effects of the long-form runner, the long-form twin of
/// `IOSSingleTakeGenerationExecutionHooks`. The iOS adapter calls exactly what
/// the runner used to call inline; the macOS adapter substitutes the desktop
/// equivalents (Settings variation, `MacStableVisualHash`, telemetry merge,
/// History library events) and no-ops the haptics.
@MainActor
protocol IOSLongFormPlatformHooks: AnyObject {
    /// Copy for progress and failure messages, resolved by the platform's
    /// interface-language owner.
    var presentation: VocelloPresentationText { get }
    /// Sampling variation stamped on every segment request.
    func requestVariation() -> Qwen3SamplingVariation?
    /// Decorative waveform seed for the live and joined cards.
    func waveformSeed(for text: String) -> Int
    /// Live card and streaming title of one segment (`index` is zero-based).
    func segmentTitle(index: Int, total: Int) -> String
    /// Mode label of the live and joined cards.
    var longFormModeLabel: String { get }
    /// Voice name of the joined card.
    var longFormProjectTitle: String { get }
    /// After a segment's timeline terminal (completed, cancelled or failed).
    func segmentTelemetryFinalized(generationID: UUID, publishedAudioURL: URL?)
    /// After the joined project row is accepted into History.
    func projectAccepted(_ saved: Generation, joinedAudioPath: String)
    func notifySuccess()
    func notifyWarning()
}

// MARK: - Playback and shared services

/// The shared audio player calls the runner and its coordinator make: live
/// narration per segment and the joined-output handoff. `AudioPlayerViewModel`
/// conforms in both apps; unit tests substitute a recorder (PA-19).
@MainActor
protocol IOSLongFormAudioPlayback: AnyObject, Sendable {
    func beginGenerationPlayback(operationID: UUID, mode: GenerationMode)
    func setLivePreviewEstimate(_ estimate: LivePreviewEstimate?)
    func prepareStreamingPreview(
        title: String,
        shouldAutoPlay: Bool,
        generationID: UUID?,
        playbackOperationID: UUID?
    )
    func completeStreamingPreview(
        result: GenerationResult,
        title: String,
        shouldAutoPlay: Bool,
        playbackOperationID: UUID?
    )
    func abortLivePreviewIfNeeded()
    func finishGenerationPreview(playbackOperationID: UUID)
}

/// The runner's collaborators that are the same on both platforms: the output
/// location and auto-play preference (`AudioService`), the app-layer timeline
/// (`AppGenerationTimeline`), the per-segment History write
/// (`GenerationPersistence`) and History acceptance of the joined project
/// (`DatabaseService`). `IOSLongFormProductionServices` makes exactly the calls
/// the runner made inline before this seam; unit tests substitute a fake over
/// a private History (PA-19).
@MainActor
protocol IOSLongFormProjectServices: AnyObject, Sendable {
    var shouldAutoPlay: Bool { get }
    func segmentOutputPath(subfolder: String, text: String) -> String
    func recordSubmitted(id: UUID, mode: String) async
    func recordCompleted(
        id: UUID,
        mode: String,
        usedStreaming: Bool,
        finishReason: String?,
        summary: TelemetrySummary?
    ) async
    func recordFailed(id: UUID, finishReason: GenerationTerminalReason) async
    func persistSegment(_ record: Generation, caller: String) async -> GenerationHistoryPersistenceOutcome
    func acceptLongFormProject(_ candidate: LongFormHistoryAcceptance) async throws -> Generation
}

// MARK: - Segment state

struct IOSLongFormSegmentState: Identifiable, Equatable {
    enum Status: Equatable {
        case pending
        case running
        case saved(audioPath: String)
        case failed(message: String)
        case cancelled
    }

    let id = UUID()
    let index: Int
    let line: String
    var status: Status
    var historyRecord: Generation?
    var qualityReport: AudioQualityGate.Report?
    var generationID: UUID?
    /// The seed of this segment's take when it is not the plan's sub-seed: a
    /// resumed segment whose take failed, or a regenerated one. Nil means the
    /// planned sub-seed. Kept across a cancelled attempt, so a resume repeats
    /// the take it stopped rather than drawing another one.
    var seedOverride: UInt64?

    var audioPath: String? {
        if case .saved(let audioPath) = status { return audioPath }
        return nil
    }

    var isSaved: Bool {
        if case .saved = status { return true }
        return false
    }

    var isFailed: Bool {
        if case .failed = status { return true }
        return false
    }
}

// MARK: - Retake seeds and script language

/// Seeds of the takes that replace a failed one. Sampling is seed-deterministic
/// (the same request and seed reproduce the same take), so a take that failed
/// on a seed — rejected by QC, or cut off at its generation limit — fails the
/// same way on it again (U10). A retake derives a fresh seed from the failed
/// one instead of drawing a random one: a chain of retakes from a pinned seed
/// still reproduces, and every take records the seed it used. One SplitMix64
/// step: well mixed, so a retake's seed bears no relation to the failed one.
enum StudioRetakeSeed {
    static func after(_ seed: UInt64) -> UInt64 {
        var mixed = seed &+ 0x9E37_79B9_7F4A_7C15
        mixed = (mixed ^ (mixed >> 30)) &* 0xBF58_476D_1CE4_E5B9
        mixed = (mixed ^ (mixed >> 27)) &* 0x94D0_49BB_1331_11EB
        return mixed ^ (mixed >> 31)
    }
}

/// One language for a script that runs as several takes: a long-form project
/// on both apps and a macOS line batch (U03). Under Auto the engine detects
/// each take's own text, and a short take of a longer script is misread: a
/// kanji-only Japanese heading is spoken as Chinese, a three-letter German
/// "Ja." in English. Auto therefore resolves once, over the whole script,
/// through the engine's own resolver (`GenerationSemantics.qwenLanguageHint`),
/// and every take carries that language. An explicit selection is kept as it
/// is, and a script the resolver cannot place stays Auto, so each take keeps
/// its own detection.
enum StudioScriptLanguage {
    static func resolved(selection: String?, script: String) -> String? {
        guard Qwen3SupportedLanguage.normalized(selection) == .auto else { return selection }
        // A Clone probe: its Auto falls back to no language, never to English,
        // so an undetected script is told apart from a detected English one.
        let probe = GenerationRequest(
            mode: .clone,
            modelID: "",
            text: script,
            outputPath: "",
            shouldStream: false,
            languageHint: Qwen3SupportedLanguage.auto.rawValue,
            payload: .clone(reference: CloneReference(audioPath: "", transcript: nil, preparedVoiceID: nil))
        )
        let language = Qwen3SupportedLanguage.normalized(GenerationSemantics.qwenLanguageHint(for: probe))
        return language == .auto ? selection : language.rawValue
    }
}

// MARK: - Progress

struct IOSLongFormProgressSnapshot: Equatable {
    var completedCount = 0
    var totalCount = 0
    var activeSegmentIndex: Int?
    var statusMessage = ""

    /// Helper-line text while a project is running; empty when idle.
    var helperText: String {
        guard totalCount > 0 else { return "" }
        return statusMessage
    }

    var fraction: Double {
        guard totalCount > 0 else { return 0 }
        return min(max(Double(completedCount) / Double(totalCount), 0), 1)
    }
}

// MARK: - Outcome

enum IOSLongFormOutcome: Equatable {
    case completed(
        segments: [IOSLongFormSegmentState],
        joinedAudioPath: String,
        joinedDurationSeconds: Double
    )
    case cancelled(segments: [IOSLongFormSegmentState])
    case failed(segments: [IOSLongFormSegmentState], message: String)

    var segments: [IOSLongFormSegmentState] {
        switch self {
        case .completed(let segments, _, _), .cancelled(let segments):
            return segments
        case .failed(let segments, _):
            return segments
        }
    }
}

// MARK: - Project request

struct IOSLongFormProjectRequest {
    let mode: GenerationMode
    let model: TTSModel
    let plan: LongFormPlan
    let voice: String?
    let emotion: String?
    let deliveryInstructionCellID: String?
    /// The language every segment request carries: the Studio selection, or
    /// under Auto the whole script's language, resolved once here (U03). The
    /// retained request keeps it for resume and regeneration.
    let languageHint: String?
    let voiceDescription: String?
    let refAudio: String?
    let refText: String?
    let preparedVoiceID: String?

    /// `languageHint` is the Studio selection; Auto resolves over the script.
    init(
        mode: GenerationMode,
        model: TTSModel,
        plan: LongFormPlan,
        voice: String?,
        emotion: String?,
        deliveryInstructionCellID: String?,
        languageHint: String?,
        voiceDescription: String?,
        refAudio: String?,
        refText: String?,
        preparedVoiceID: String?
    ) {
        self.mode = mode
        self.model = model
        self.plan = plan
        self.voice = voice
        self.emotion = emotion
        self.deliveryInstructionCellID = deliveryInstructionCellID
        self.languageHint = StudioScriptLanguage.resolved(
            selection: languageHint,
            script: plan.segments.map(\.spokenTextForGeneration).joined(separator: "\n")
        )
        self.voiceDescription = voiceDescription
        self.refAudio = refAudio
        self.refText = refText
        self.preparedVoiceID = preparedVoiceID
    }

    var lines: [String] { plan.segments.map(\.spokenTextForGeneration) }

    var projectDigestPrefix: String { String(plan.evidence.planDigest.prefix(8)) }

    /// Pause budget for the assembled output: the whole script's punctuation
    /// plus the assembler's own inserted boundary pauses.
    var joinedOutputPauseBudget: Int {
        lines.reduce(0) { $0 + PersistedWAVAudioQCAnalyzer.expectedPauseCount(in: $1) }
            + max(0, lines.count - 1)
    }

    func outputText(forSegment index: Int) -> String {
        String(format: "segment_%04d_%@", index + 1, String(lines[index].prefix(40)))
    }

    /// The planned sub-seed of a segment, the seed of its first take.
    func plannedSeed(forSegment index: Int) -> UInt64 {
        plan.segments[index].evidence.effectiveSubseed
    }

    func makeGenerationRequest(
        segmentIndex: Int,
        outputPath: String,
        generationID: UUID,
        variation: Qwen3SamplingVariation?,
        seedOverride: UInt64? = nil
    ) -> GenerationRequest {
        let line = lines[segmentIndex]
        let seed = seedOverride ?? plannedSeed(forSegment: segmentIndex)
        let payload: GenerationRequest.Payload
        switch mode {
        case .custom:
            payload = .custom(
                speakerID: voice ?? TTSModel.defaultSpeaker,
                deliveryStyle: model.supportsInstructionControl ? emotion : nil
            )
        case .design:
            payload = .design(
                voiceDescription: voiceDescription ?? "",
                deliveryStyle: emotion ?? EmotionPreset.neutralPresetInstruction
            )
        case .clone:
            payload = .clone(
                reference: CloneReference(
                    audioPath: refAudio ?? "",
                    transcript: refText,
                    preparedVoiceID: preparedVoiceID
                )
            )
        }
        return GenerationRequest(
            mode: mode,
            modelID: model.id,
            text: line,
            outputPath: outputPath,
            shouldStream: true,
            streamingInterval: GenerationSemantics.appStreamingInterval,
            languageHint: languageHint,
            payload: payload,
            generationID: generationID,
            seed: seed,
            variation: variation,
            deliveryInstructionCellID: mode == .custom ? deliveryInstructionCellID : nil
        )
    }

    private var voiceName: String? {
        switch mode {
        case .custom:
            return voice
        case .design:
            return voiceDescription
        case .clone:
            if let voice { return voice }
            if let refAudio {
                return URL(fileURLWithPath: refAudio).deletingPathExtension().lastPathComponent
            }
            return nil
        }
    }

    func makeSegmentHistoryRecord(forSegment index: Int, audioPath: String, duration: Double?) -> Generation {
        Generation(
            text: lines[index],
            mode: model.mode.rawValue,
            modelTier: model.tier,
            voice: voiceName,
            emotion: emotion,
            speed: nil,
            audioPath: audioPath,
            duration: duration,
            createdAt: Date(),
            longFormProjectID: plan.evidence.planDigest,
            longFormRole: "segment"
        )
    }

    func makeJoinedHistoryRecord(assembly: LongFormAssemblyEvidence, outputURL: URL) -> Generation {
        Generation(
            text: lines.joined(separator: " "),
            mode: model.mode.rawValue,
            modelTier: model.tier,
            voice: voiceName,
            emotion: emotion,
            speed: nil,
            audioPath: outputURL.path,
            duration: Double(assembly.outputFrameCount) / Double(assembly.sampleRate),
            createdAt: Date(),
            longFormProjectID: plan.evidence.planDigest,
            longFormRole: "joined"
        )
    }
}

// MARK: - Coordinator

/// One app-wide long-form run at a time (the engine admits one generation
/// anyway). Owns the run task, retained plan identity for in-session resume,
/// and the published progress the mode views render.
@MainActor
@Observable
final class IOSLongFormCoordinator {
    static let maxSegments = 100

    @ObservationIgnored private let hooks: any IOSLongFormPlatformHooks
    @ObservationIgnored private let services: any IOSLongFormProjectServices

    /// The apps use `init(hooks:)`, which passes `IOSLongFormProductionServices`.
    init(hooks: any IOSLongFormPlatformHooks, services: any IOSLongFormProjectServices) {
        self.hooks = hooks
        self.services = services
    }

    private(set) var isProcessing = false
    /// True while the running operation regenerates one segment of a completed
    /// project (cancelling it keeps the completed project; there is no Resume).
    private(set) var isRegeneratingSegment = false
    private(set) var progress = IOSLongFormProgressSnapshot()
    private(set) var segments: [IOSLongFormSegmentState] = []
    private(set) var outcome: IOSLongFormOutcome?
    /// Mode that started the current/last project; gates which mode view shows
    /// progress and the resume affordance.
    private(set) var lastMode: GenerationMode?
    /// Retained for in-session resume; the plan inside is the identity authority.
    private var lastRequest: IOSLongFormProjectRequest?
    private var runTask: Task<Void, Never>?
    private var cancellationState = IOSLongFormCancellationState()

    /// Accepted-replacement lineage for the retained project (revision >= 2,
    /// strictly increasing per segment, recorded seeds). Reset when a new plan
    /// identity begins; preserved across resume and further regenerations.
    private(set) var replacements: [LongFormSegmentReplacementEvidence] = []

    /// A stopped run can resume missing segments or retry assembly/acceptance
    /// when every segment is already materialized, without regenerating them.
    var canResume: Bool {
        guard !isProcessing, lastRequest != nil, let outcome else { return false }
        if case .completed = outcome { return false }
        return true
    }

    /// A completed project with retained plan identity can regenerate any
    /// single segment; the joined output is reassembled around the new take.
    /// So can a project that stopped with every segment saved (its joined
    /// output failed QC or History refused it): a Resume would rebuild the
    /// same join from the same takes, so replacing a take is the way out (U10).
    var canRegenerateSegments: Bool {
        guard !isProcessing, lastRequest != nil, let outcome else { return false }
        switch outcome {
        case .completed:
            return true
        case .failed(let segments, _):
            return !segments.isEmpty && segments.allSatisfy(\.isSaved)
        case .cancelled:
            return false
        }
    }

    /// `baseSeed` is the pinned Studio seed, if any (U11): the same script and
    /// seed plan the same segments on the same sub-seeds, as the CLI's
    /// `--seed` does. Without one, every project draws its own.
    static func plan(originalText: String, baseSeed: UInt64? = nil) throws -> LongFormPlan {
        let spokenPlan = try SpokenTextPlanner.plan(originalText: originalText)
        return try LongFormPlanner.plan(
            spokenTextPlan: spokenPlan,
            configuration: LongFormPlanningConfiguration(
                runtimeTokenLimit: LongFormPlanningConfiguration.shippingRuntimeTokenLimit,
                baseSeed: baseSeed ?? UInt64.random(in: UInt64.min ... UInt64.max)
            )
        )
    }

    func start(
        request: IOSLongFormProjectRequest,
        ttsEngine: TTSEngineStore,
        audioPlayer: any IOSLongFormAudioPlayback,
        studioCoordinator: StudioGenerationCoordinator
    ) {
        begin(
            request: request,
            reusing: nil,
            ttsEngine: ttsEngine,
            audioPlayer: audioPlayer,
            studioCoordinator: studioCoordinator
        )
    }

    func resume(
        ttsEngine: TTSEngineStore,
        audioPlayer: any IOSLongFormAudioPlayback,
        studioCoordinator: StudioGenerationCoordinator
    ) {
        guard canResume, let request = lastRequest, let prior = outcome?.segments else { return }
        begin(
            request: request,
            reusing: prior,
            ttsEngine: ttsEngine,
            audioPlayer: audioPlayer,
            studioCoordinator: studioCoordinator
        )
    }

    /// Regenerates one segment of the retained completed project with a fresh
    /// recorded seed, then reassembles the joined output around the accepted
    /// take. QC failure leaves the previous take and joined output unchanged.
    func regenerateSegment(
        index: Int,
        ttsEngine: TTSEngineStore,
        audioPlayer: any IOSLongFormAudioPlayback,
        studioCoordinator: StudioGenerationCoordinator
    ) {
        guard canRegenerateSegments, !ttsEngine.hasActiveGeneration,
              let request = lastRequest,
              let priorSegments = outcome?.segments,
              index >= 0, index < priorSegments.count else { return }
        guard let attempt = studioCoordinator.start(live: nil) else { return }
        #if os(macOS)
        audioPlayer.beginGenerationPlayback(operationID: attempt.rawValue, mode: request.mode)
        #endif
        let acceptedOutcome = outcome
        isProcessing = true
        isRegeneratingSegment = true
        // A new operation owns a new cancellation token. An asynchronously
        // scheduled reset could otherwise erase an immediately requested cancel.
        cancellationState = IOSLongFormCancellationState()
        let runner = IOSLongFormProjectRunner(
            ttsEngine: ttsEngine,
            audioPlayer: audioPlayer,
            cancellationState: cancellationState,
            hooks: hooks,
            services: services
        )
        segments = priorSegments
        progress = IOSLongFormProgressSnapshot(
            completedCount: priorSegments.count(where: \.isSaved),
            totalCount: priorSegments.count,
            activeSegmentIndex: index,
            statusMessage: hooks.presentation.regeneratingSegment(index + 1, total: priorSegments.count)
        )
        runTask = Task { [weak self] in
            guard let self else { return }
            let result = await runner.regenerateSegment(
                request: request,
                priorSegments: priorSegments,
                segmentIndex: index,
                priorReplacements: replacements,
                onProgress: { [weak self] snapshot in self?.progress = snapshot },
                onSegmentsUpdated: { [weak self] segments in self?.segments = segments },
                studioCoordinator: studioCoordinator,
                studioAttempt: attempt
            )
            self.isProcessing = false
            self.isRegeneratingSegment = false
            self.runTask = nil
            self.replacements = result.replacements
            if case .completed = result.outcome {
                self.outcome = result.outcome
            } else {
                // A failed replacement does not revoke the previous project
                // or remove its explicit regenerate action for another attempt.
                self.outcome = acceptedOutcome
            }
            self.progress = IOSLongFormProgressSnapshot()
            self.finish(
                outcome: result.outcome,
                request: request,
                audioPlayer: audioPlayer,
                studioCoordinator: studioCoordinator,
                studioAttempt: attempt
            )
        }
    }

    /// Returns whether the cancellation was accepted by the attempt authority
    /// (false while idle or when a cancellation is already pending). Completed
    /// segments stay saved, so a cancelled project remains resumable. `reason`
    /// is `.shutdown` when the app leaves the foreground (PA-15).
    @discardableResult
    func cancel(
        ttsEngine: TTSEngineStore,
        audioPlayer: any IOSLongFormAudioPlayback,
        studioCoordinator: StudioGenerationCoordinator,
        reason: GenerationCancellationReason = .user
    ) -> Bool {
        startCancellation(
            ttsEngine: ttsEngine,
            audioPlayer: audioPlayer,
            studioCoordinator: studioCoordinator,
            reason: reason
        ) != nil
    }

    /// Starts the cancellation and returns its barrier task, which finishes once
    /// the attempt is terminal; `nil` when it was not accepted. A typed non-user
    /// reason reaches the engine barrier before the run task is cancelled
    /// (`IOSStudioCancellationOrder`), so the engine records that reason.
    func startCancellation(
        ttsEngine: TTSEngineStore,
        audioPlayer: any IOSLongFormAudioPlayback,
        studioCoordinator: StudioGenerationCoordinator,
        reason: GenerationCancellationReason
    ) -> Task<Void, Never>? {
        guard isProcessing else { return nil }
        let order = IOSStudioCancellationOrder.forReason(reason)
        guard let attempt = studioCoordinator.requestCancellation(
            cancelsTask: order == .taskThenBarrier
        ) else { return nil }
        let state = cancellationState
        let runTask = self.runTask
        if order == .taskThenBarrier {
            runTask?.cancel()
        }
        audioPlayer.abortLivePreviewIfNeeded()
        return Task {
            await state.request()
            do {
                try await ttsEngine.cancelActiveGeneration(reason: reason)
                runTask?.cancel()
                studioCoordinator.completeCancellation(attempt: attempt)
            } catch {
                runTask?.cancel()
                if studioCoordinator.failCancellation(error, attempt: attempt) {
                    hooks.notifyWarning()
                }
            }
        }
    }

    private func begin(
        request: IOSLongFormProjectRequest,
        reusing prior: [IOSLongFormSegmentState]?,
        ttsEngine: TTSEngineStore,
        audioPlayer: any IOSLongFormAudioPlayback,
        studioCoordinator: StudioGenerationCoordinator
    ) {
        guard !isProcessing, !ttsEngine.hasActiveGeneration else { return }
        // A new project starts its own lineage even on the same plan identity
        // (the same script and pinned seed): only a resume continues one.
        if prior == nil || lastRequest?.plan.evidence.planDigest != request.plan.evidence.planDigest {
            replacements = []
        }
        guard let attempt = studioCoordinator.start(live: nil) else { return }
        #if os(macOS)
        audioPlayer.beginGenerationPlayback(operationID: attempt.rawValue, mode: request.mode)
        #endif
        lastRequest = request
        lastMode = request.mode
        outcome = nil
        isProcessing = true
        isRegeneratingSegment = false
        cancellationState = IOSLongFormCancellationState()
        let runner = IOSLongFormProjectRunner(
            ttsEngine: ttsEngine,
            audioPlayer: audioPlayer,
            cancellationState: cancellationState,
            hooks: hooks,
            services: services
        )
        segments = request.lines.enumerated().map { index, line in
            var segment = IOSLongFormSegmentState(index: index, line: line, status: .pending)
            guard let prior, index < prior.count, prior[index].line == line else { return segment }
            if prior[index].isSaved { return prior[index] }
            // The same seed would reproduce the failed take, so the retake
            // derives a fresh one from it (U10); a stopped take keeps its seed.
            segment.seedOverride = prior[index].isFailed
                ? StudioRetakeSeed.after(prior[index].seedOverride ?? request.plannedSeed(forSegment: index))
                : prior[index].seedOverride
            return segment
        }
        progress = IOSLongFormProgressSnapshot(
            completedCount: segments.count(where: \.isSaved),
            totalCount: segments.count,
            activeSegmentIndex: nil,
            statusMessage: hooks.presentation.preparingLongForm
        )
        runTask = Task { [weak self] in
            guard let self else { return }
            let outcome = await runner.run(
                request: request,
                initialSegments: segments,
                priorReplacements: replacements,
                onProgress: { [weak self] snapshot in self?.progress = snapshot },
                onSegmentsUpdated: { [weak self] segments in self?.segments = segments },
                studioCoordinator: studioCoordinator,
                studioAttempt: attempt
            )
            self.isProcessing = false
            self.runTask = nil
            self.outcome = outcome
            self.progress = IOSLongFormProgressSnapshot()
            self.finish(
                outcome: outcome,
                request: request,
                audioPlayer: audioPlayer,
                studioCoordinator: studioCoordinator,
                studioAttempt: attempt
            )
        }
    }

    /// Terminal studio-lifecycle glue: hand the joined output to the shared
    /// player (auto-play-gated) and surface the inline card, or clear/fail the
    /// dock state — mirroring what the single-take flows do per take.
    private func finish(
        outcome: IOSLongFormOutcome,
        request: IOSLongFormProjectRequest,
        audioPlayer: any IOSLongFormAudioPlayback,
        studioCoordinator: StudioGenerationCoordinator,
        studioAttempt: StudioGenerationAttemptToken
    ) {
        switch outcome {
        case .completed(_, let joinedAudioPath, let joinedDurationSeconds):
            let shouldAutoPlay = services.shouldAutoPlay
            let transcript = request.lines.joined(separator: " ")
            // The attempt finalized before History accepted the project, so
            // this is accepted; the player takes the joined output only then,
            // never for an attempt a Stop already ended (U24).
            let accepted = studioCoordinator.complete(
                IOSStudioInlinePlayerItem(
                    generationID: UUID(),
                    audioURL: URL(fileURLWithPath: joinedAudioPath),
                    voiceName: hooks.longFormProjectTitle,
                    modeLabel: hooks.longFormModeLabel,
                    mode: request.mode,
                    transcript: transcript,
                    waveformSeed: hooks.waveformSeed(for: transcript),
                    autoplay: false,
                    ownedBySharedPlayer: shouldAutoPlay
                ),
                attempt: studioAttempt
            )
            guard accepted else { return }
            audioPlayer.completeStreamingPreview(
                result: GenerationResult(
                    audioPath: joinedAudioPath,
                    durationSeconds: joinedDurationSeconds,
                    streamSessionDirectory: nil,
                    usedStreaming: false
                ),
                title: String(transcript.prefix(40)),
                shouldAutoPlay: shouldAutoPlay,
                playbackOperationID: studioAttempt.rawValue
            )
            hooks.notifySuccess()
        case .cancelled:
            studioCoordinator.finish(attempt: studioAttempt)
        case .failed(_, let message):
            if studioCoordinator.fail(message, attempt: studioAttempt) {
                hooks.notifyWarning()
            }
        }
    }
}

actor IOSLongFormCancellationState {
    private var isRequested = false
    func request() { isRequested = true }
    func wasRequested() -> Bool { isRequested }
}

// MARK: - Runner

@MainActor
final class IOSLongFormProjectRunner {
    private let ttsEngine: TTSEngineStore
    private let audioPlayer: any IOSLongFormAudioPlayback
    private let cancellationState: IOSLongFormCancellationState
    private let hooks: any IOSLongFormPlatformHooks
    private let services: any IOSLongFormProjectServices

    init(
        ttsEngine: TTSEngineStore,
        audioPlayer: any IOSLongFormAudioPlayback,
        cancellationState: IOSLongFormCancellationState,
        hooks: any IOSLongFormPlatformHooks,
        services: any IOSLongFormProjectServices
    ) {
        self.ttsEngine = ttsEngine
        self.audioPlayer = audioPlayer
        self.cancellationState = cancellationState
        self.hooks = hooks
        self.services = services
    }

    private func evaluateQC(path: String, expectedPauseCount: Int) async -> AudioQualityGate.Report {
        await Task.detached(priority: .utility) {
            AudioQualityGate.evaluate(
                url: URL(fileURLWithPath: path),
                expectedPauseCount: expectedPauseCount
            )
        }.value
    }

    func run(
        request: IOSLongFormProjectRequest,
        initialSegments: [IOSLongFormSegmentState],
        priorReplacements: [LongFormSegmentReplacementEvidence],
        onProgress: @escaping @MainActor (IOSLongFormProgressSnapshot) -> Void,
        onSegmentsUpdated: @escaping @MainActor ([IOSLongFormSegmentState]) -> Void,
        studioCoordinator: StudioGenerationCoordinator,
        studioAttempt: StudioGenerationAttemptToken
    ) async -> IOSLongFormOutcome {
        // Hold the fixed-refresh performance gate across the whole run —
        // segments, QC, History saves, and assembly — instead of flickering
        // per segment.
        ttsEngine.beginSustainedPerformanceActivity()
        defer { ttsEngine.endSustainedPerformanceActivity() }

        var segments = initialSegments
        let total = segments.count
        var qualityReports: [AudioQualityGate.Report?] = []

        func publish(active: Int?, message: String) {
            onProgress(
                IOSLongFormProgressSnapshot(
                    completedCount: segments.count(where: \.isSaved),
                    totalCount: total,
                    activeSegmentIndex: active,
                    statusMessage: message
                )
            )
            onSegmentsUpdated(segments)
        }

        func markCancelled(startingAt index: Int) {
            for i in index..<segments.count where !segments[i].isSaved {
                segments[i].status = .cancelled
            }
            onSegmentsUpdated(segments)
        }

        for index in segments.indices {
            let line = segments[index].line
            if await cancellationState.wasRequested() {
                markCancelled(startingAt: index)
                return .cancelled(segments: segments)
            }

            if segments[index].isSaved, let reusedPath = segments[index].audioPath {
                // Resume: re-verify the retained take instead of regenerating.
                let report = await evaluateQC(
                    path: reusedPath,
                    expectedPauseCount: PersistedWAVAudioQCAnalyzer.expectedPauseCount(in: line)
                )
                qualityReports.append(report)
                segments[index].qualityReport = report
                guard report.passed else {
                    segments[index].status = .failed(message: hooks.presentation.oldSegmentQC)
                    onSegmentsUpdated(segments)
                    return .failed(
                        segments: segments,
                        message: hooks.presentation.oldSegmentQC
                    )
                }
                publish(active: index, message: hooks.presentation.reusingSegment(index + 1, total: total))
                continue
            }

            segments[index].status = .running
            publish(active: index, message: hooks.presentation.generatingSegment(index + 1, total: total))

            let seed = segments[index].seedOverride ?? request.plannedSeed(forSegment: index)
            let generationID = UUID()
            let outputPath = LongFormHistoryAcceptance.uniqueAudioURL(basedOn: URL(fileURLWithPath: services.segmentOutputPath(
                subfolder: request.model.outputSubfolder,
                text: request.outputText(forSegment: index)
            ))).path
            do {
                // Live narration per segment (playback gated by the user's
                // auto-play preference; publication always on).
                audioPlayer.setLivePreviewEstimate(LivePreviewEstimate(text: line))
                audioPlayer.prepareStreamingPreview(
                    title: hooks.segmentTitle(index: index, total: total),
                    shouldAutoPlay: services.shouldAutoPlay,
                    generationID: generationID, playbackOperationID: studioAttempt.rawValue
                )
                studioCoordinator.updateLiveItem(IOSStudioLivePreviewItem(
                    voiceName: hooks.segmentTitle(index: index, total: total),
                    modeLabel: hooks.longFormModeLabel,
                    mode: request.mode,
                    transcript: line,
                    waveformSeed: hooks.waveformSeed(for: line),
                    estimatedAudioDuration: LivePreviewEstimate(text: line)?.estimatedAudioDuration ?? 0
                ), attempt: studioAttempt)
                await services.recordSubmitted(
                    id: generationID,
                    mode: request.mode.rawValue
                )
                let result = try await ttsEngine.generate(
                    request.makeGenerationRequest(
                        segmentIndex: index,
                        outputPath: outputPath,
                        generationID: generationID,
                        variation: hooks.requestVariation(),
                        seedOverride: seed
                    )
                )
                let cancellationRequestedAfterTake = await cancellationState.wasRequested()
                if Task.isCancelled || cancellationRequestedAfterTake {
                    await services.recordFailed(id: generationID, finishReason: .cancelled)
                    hooks.segmentTelemetryFinalized(generationID: generationID, publishedAudioURL: nil)
                    try? FileManager.default.removeItem(atPath: result.audioPath)
                    audioPlayer.abortLivePreviewIfNeeded()
                    markCancelled(startingAt: index)
                    return .cancelled(segments: segments)
                }
                await services.recordCompleted(
                    id: generationID,
                    mode: request.mode.rawValue,
                    usedStreaming: true,
                    finishReason: result.finishReason?.rawValue,
                    summary: result.telemetrySummary
                )
                hooks.segmentTelemetryFinalized(generationID: generationID, publishedAudioURL: nil)

                let report = await evaluateQC(
                    path: result.audioPath,
                    expectedPauseCount: PersistedWAVAudioQCAnalyzer.expectedPauseCount(in: line)
                )
                qualityReports.append(report)
                segments[index].qualityReport = report
                guard report.passed else {
                    let message = hooks.presentation.segmentQCRejected(index + 1)
                    segments[index].status = .failed(message: message)
                    try? FileManager.default.removeItem(atPath: result.audioPath)
                    audioPlayer.abortLivePreviewIfNeeded()
                    onSegmentsUpdated(segments)
                    return .failed(segments: segments, message: message)
                }

                // A Stop accepted while QC ran wins: nothing is queued for
                // History yet, so the take is discarded like one that finished
                // after the request, and Resume generates it again (U24).
                let cancellationRequestedAfterQC = await cancellationState.wasRequested()
                if Task.isCancelled || cancellationRequestedAfterQC {
                    try? FileManager.default.removeItem(atPath: result.audioPath)
                    audioPlayer.abortLivePreviewIfNeeded()
                    markCancelled(startingAt: index)
                    return .cancelled(segments: segments)
                }

                var record = request.makeSegmentHistoryRecord(
                    forSegment: index,
                    audioPath: result.audioPath,
                    duration: result.durationSeconds
                )
                record.seed = Int64(bitPattern: seed)
                segments[index].historyRecord = record
                segments[index].generationID = generationID
                let persistence = await services.persistSegment(record, caller: "IOSLongFormSegment")
                if persistence == .queuedForRecovery {
                    // The durable outbox holds the row and commits it on its
                    // next reconcile, so the take belongs to the project: a
                    // Resume reuses it instead of saving the segment twice. A
                    // Stop that cancelled the History write lands here (U24).
                    segments[index].status = .saved(audioPath: result.audioPath)
                    audioPlayer.abortLivePreviewIfNeeded()
                    let cancellationRequested = await cancellationState.wasRequested()
                    if Task.isCancelled || cancellationRequested {
                        markCancelled(startingAt: index + 1)
                        return .cancelled(segments: segments)
                    }
                    onSegmentsUpdated(segments)
                    return .failed(segments: segments, message: hooks.presentation.longFormSegmentHistoryFailed)
                }
                try persistence.requireSavedLongFormSegment()
                segments[index].status = .saved(audioPath: result.audioPath)
                publish(active: index, message: hooks.presentation.generatedSegmentPending(index + 1, total: total))
            } catch {
                audioPlayer.abortLivePreviewIfNeeded()
                let cancellationRequested = await cancellationState.wasRequested()
                await services.recordFailed(
                    id: generationID,
                    finishReason: (error is CancellationError || cancellationRequested) ? .cancelled : .failed
                )
                hooks.segmentTelemetryFinalized(generationID: generationID, publishedAudioURL: nil)
                if error is CancellationError || Task.isCancelled || cancellationRequested {
                    markCancelled(startingAt: index)
                    return .cancelled(segments: segments)
                }
                let message = failureMessage(for: error, afterGeneration: false)
                segments[index].status = .failed(message: message)
                onSegmentsUpdated(segments)
                return .failed(segments: segments, message: message)
            }
        }

        if await cancellationState.wasRequested() {
            markCancelled(startingAt: 0)
            return .cancelled(segments: segments)
        }

        // Close the final segment's live session deterministically before the
        // join so the completed-project handoff never overlaps a draining
        // live tail.
        audioPlayer.finishGenerationPreview(playbackOperationID: studioAttempt.rawValue)
        publish(active: nil, message: hooks.presentation.joiningSegments(total))
        var candidateJoinedURL: URL?
        defer { if let candidateJoinedURL { try? FileManager.default.removeItem(at: candidateJoinedURL) } }
        do {
            let joined = try await assemble(request: request, segments: segments)
            candidateJoinedURL = joined.outputURL
            let joinedReport = await evaluateQC(
                path: joined.outputURL.path,
                expectedPauseCount: request.joinedOutputPauseBudget
            )
            guard joinedReport.passed else {
                return .failed(segments: segments, message: hooks.presentation.joinedQCRejected)
            }
            let joinedRecord = request.makeJoinedHistoryRecord(
                assembly: joined.evidence,
                outputURL: joined.outputURL
            )
            let candidate = try await makeAcceptance(
                request: request, segments: segments, qualityReports: qualityReports,
                assembly: joined.evidence, replacements: priorReplacements,
                joined: joinedRecord, joinedQCPassed: joinedReport.passed, ownedAudioURLs: [joined.outputURL]
            )
            if await cancellationState.wasRequested() { throw CancellationError() }
            // The Stop-during-save rule of a single take (A1-01): from here the
            // attempt refuses a Stop, so the History acceptance runs to its end
            // and a project that lands in History is never reported stopped or
            // failed. A Stop accepted first wins, and nothing is saved (U24).
            guard studioCoordinator.beginFinalization(attempt: studioAttempt) else { throw CancellationError() }
            let saved = try await services.acceptLongFormProject(candidate)
            candidateJoinedURL = nil
            hooks.projectAccepted(saved, joinedAudioPath: joined.outputURL.path)
            publish(active: nil, message: hooks.presentation.done)
            return .completed(
                segments: segments,
                joinedAudioPath: joined.outputURL.path,
                joinedDurationSeconds: saved.duration
                    ?? Double(joined.evidence.outputFrameCount) / Double(joined.evidence.sampleRate)
            )
        } catch {
            let acceptanceError = error as? LongFormAcceptanceError
            // Recovery keeps, or completes after resume, what it owns (PA-30).
            if acceptanceError?.leavesCandidateToRecovery == true { candidateJoinedURL = nil }
            if error is CancellationError { return .cancelled(segments: segments) }
            return .failed(segments: segments, message: failureMessage(for: error, afterGeneration: true))
        }
    }

    /// Interface-language copy for a failed segment, join or acceptance
    /// (L14-05): typed generation failures through their catalog reason, the
    /// long-form storage errors through their own copy, and an untyped join
    /// failure as an actionable line, never an English error description
    /// that may quote a file name. An untyped engine failure keeps its own
    /// description, as for a single take.
    private func failureMessage(for error: Error, afterGeneration: Bool) -> String {
        switch error {
        case let acceptance as LongFormAcceptanceError:
            switch acceptance {
            case .invalidCandidate: return hooks.presentation.longFormSaveFailed
            case .recoveryRequired: return hooks.presentation.longFormRecoveryRequired
            case .interrupted: return hooks.presentation.longFormAcceptanceInterrupted
            }
        case is LongFormSegmentHistoryError:
            return hooks.presentation.longFormSegmentHistoryFailed
        case let runError as RunError:
            return runError.localizedDescription
        default:
            if afterGeneration, GenerationFailurePresentationReason(error) == nil {
                return hooks.presentation.longFormJoinFailed
            }
            return hooks.presentation.generationFailureMessage(error)
        }
    }

    /// The replacement semantics the retired macOS runner established, on the
    /// shared sequential runner: one fresh-seeded take for the chosen
    /// segment, per-segment QC that leaves the prior take untouched on
    /// failure, replacement lineage (revision >= 2, recorded seed), and
    /// reassembly of the joined output around the accepted take.
    func regenerateSegment(
        request: IOSLongFormProjectRequest,
        priorSegments: [IOSLongFormSegmentState],
        segmentIndex: Int,
        priorReplacements: [LongFormSegmentReplacementEvidence],
        onProgress: @escaping @MainActor (IOSLongFormProgressSnapshot) -> Void,
        onSegmentsUpdated: @escaping @MainActor ([IOSLongFormSegmentState]) -> Void,
        studioCoordinator: StudioGenerationCoordinator,
        studioAttempt: StudioGenerationAttemptToken
    ) async -> (outcome: IOSLongFormOutcome, replacements: [LongFormSegmentReplacementEvidence]) {
        ttsEngine.beginSustainedPerformanceActivity()
        defer { ttsEngine.endSustainedPerformanceActivity() }

        var segments = priorSegments
        let total = segments.count
        guard segmentIndex >= 0, segmentIndex < total,
              segmentIndex < request.plan.segments.count,
              segments.allSatisfy(\.isSaved) else {
            return (
                .failed(
                    segments: segments,
                    message: hooks.presentation.segmentNotInProject
                ),
                priorReplacements
            )
        }
        let line = segments[segmentIndex].line
        let segmentID = request.plan.segments[segmentIndex].segmentID
        let revision = 2 + priorReplacements.count(where: { $0.segmentID == segmentID })
        let replacementSeed = UInt64.random(in: UInt64.min ... UInt64.max)
        let priorSegment = segments[segmentIndex]

        func publish(active: Int?, message: String) {
            onProgress(
                IOSLongFormProgressSnapshot(
                    completedCount: segments.count(where: \.isSaved),
                    totalCount: total,
                    activeSegmentIndex: active,
                    statusMessage: message
                )
            )
            onSegmentsUpdated(segments)
        }

        segments[segmentIndex].status = .running
        publish(active: segmentIndex, message: hooks.presentation.regeneratingSegment(segmentIndex + 1, total: total))

        let generationID = UUID()
        let outputPath = LongFormHistoryAcceptance.uniqueAudioURL(basedOn: URL(fileURLWithPath: services.segmentOutputPath(
            subfolder: request.model.outputSubfolder,
            text: request.outputText(forSegment: segmentIndex)
        ))).path
        var candidateAudioURLs: [URL] = []
        var generationCompleted = false
        defer { for url in candidateAudioURLs { try? FileManager.default.removeItem(at: url) } }
        do {
            audioPlayer.setLivePreviewEstimate(LivePreviewEstimate(text: line))
            audioPlayer.prepareStreamingPreview(
                title: hooks.segmentTitle(index: segmentIndex, total: total),
                shouldAutoPlay: services.shouldAutoPlay,
                generationID: generationID, playbackOperationID: studioAttempt.rawValue
            )
            studioCoordinator.updateLiveItem(IOSStudioLivePreviewItem(
                voiceName: hooks.segmentTitle(index: segmentIndex, total: total),
                modeLabel: hooks.longFormModeLabel,
                mode: request.mode,
                transcript: line,
                waveformSeed: hooks.waveformSeed(for: line),
                estimatedAudioDuration: LivePreviewEstimate(text: line)?.estimatedAudioDuration ?? 0
            ), attempt: studioAttempt)
            await services.recordSubmitted(
                id: generationID,
                mode: request.mode.rawValue
            )
            let result = try await ttsEngine.generate(
                request.makeGenerationRequest(
                    segmentIndex: segmentIndex,
                    outputPath: outputPath,
                    generationID: generationID,
                    variation: hooks.requestVariation(),
                    seedOverride: replacementSeed
                )
            )
            let cancellationRequestedAfterTake = await cancellationState.wasRequested()
            candidateAudioURLs.append(URL(fileURLWithPath: result.audioPath))
            if Task.isCancelled || cancellationRequestedAfterTake {
                await services.recordFailed(id: generationID, finishReason: .cancelled)
                hooks.segmentTelemetryFinalized(generationID: generationID, publishedAudioURL: nil)
                try? FileManager.default.removeItem(atPath: result.audioPath)
                audioPlayer.abortLivePreviewIfNeeded()
                segments[segmentIndex] = priorSegment
                onSegmentsUpdated(segments)
                return (.cancelled(segments: segments), priorReplacements)
            }
            await services.recordCompleted(
                id: generationID,
                mode: request.mode.rawValue,
                usedStreaming: true,
                finishReason: result.finishReason?.rawValue,
                summary: result.telemetrySummary
            )
            generationCompleted = true
            hooks.segmentTelemetryFinalized(generationID: generationID, publishedAudioURL: nil)

            let report = await evaluateQC(
                path: result.audioPath,
                expectedPauseCount: PersistedWAVAudioQCAnalyzer.expectedPauseCount(in: line)
            )
            guard report.passed else {
                // The rejected candidate's live preview stops with it (U09).
                audioPlayer.abortLivePreviewIfNeeded()
                segments[segmentIndex] = priorSegment
                onSegmentsUpdated(segments)
                return (
                    .failed(segments: segments, message: hooks.presentation.regeneratedQCRejected),
                    priorReplacements
                )
            }

            var record = request.makeSegmentHistoryRecord(
                forSegment: segmentIndex,
                audioPath: result.audioPath,
                duration: result.durationSeconds
            )
            record.seed = Int64(bitPattern: replacementSeed)
            segments[segmentIndex].historyRecord = record
            segments[segmentIndex].qualityReport = report
            segments[segmentIndex].generationID = generationID
            segments[segmentIndex].seedOverride = replacementSeed
            segments[segmentIndex].status = .saved(audioPath: result.audioPath)

            var replacements = priorReplacements
            replacements.append(
                LongFormSegmentReplacementEvidence(
                    segmentID: segmentID,
                    revision: revision,
                    effectiveSeed: replacementSeed,
                    generatedAtUTC: ISO8601DateFormatter().string(from: Date()),
                    qcPassed: true,
                    qcWarnings: report.warnings
                )
            )

            audioPlayer.finishGenerationPreview(playbackOperationID: studioAttempt.rawValue)
            // Keep the accepted visible segments until the whole replacement
            // transaction succeeds; the candidate is local to this operation.
            onProgress(IOSLongFormProgressSnapshot(totalCount: total, statusMessage: hooks.presentation.joiningSegments(total)))
            let qualityReports = segments.map(\.qualityReport)
            let joined = try await assemble(request: request, segments: segments)
            candidateAudioURLs.append(joined.outputURL)
            let joinedReport = await evaluateQC(
                path: joined.outputURL.path,
                expectedPauseCount: request.joinedOutputPauseBudget
            )
            guard joinedReport.passed else {
                onSegmentsUpdated(priorSegments)
                return (
                    .failed(segments: priorSegments, message: hooks.presentation.regeneratedJoinedQCRejected),
                    priorReplacements
                )
            }
            let joinedRecord = request.makeJoinedHistoryRecord(
                assembly: joined.evidence,
                outputURL: joined.outputURL
            )
            let candidate = try await makeAcceptance(
                request: request, segments: segments, qualityReports: qualityReports,
                assembly: joined.evidence, replacements: replacements,
                joined: joinedRecord, joinedQCPassed: joinedReport.passed, ownedAudioURLs: candidateAudioURLs
            )
            if await cancellationState.wasRequested() { throw CancellationError() }
            // As in `run`: a Stop is refused once History accepts the
            // replacement, and one accepted first discards it (U24).
            guard studioCoordinator.beginFinalization(attempt: studioAttempt) else { throw CancellationError() }
            let saved = try await services.acceptLongFormProject(candidate)
            candidateAudioURLs.removeAll()
            hooks.projectAccepted(saved, joinedAudioPath: joined.outputURL.path)
            publish(active: nil, message: hooks.presentation.done)
            return (
                .completed(
                    segments: segments,
                    joinedAudioPath: joined.outputURL.path,
                    joinedDurationSeconds: saved.duration
                        ?? Double(joined.evidence.outputFrameCount) / Double(joined.evidence.sampleRate)
                ),
                replacements
            )
        } catch {
            let acceptanceError = error as? LongFormAcceptanceError
            // Recovery keeps, or completes after resume, what it owns (PA-30).
            if acceptanceError?.leavesCandidateToRecovery == true { candidateAudioURLs.removeAll() }
            audioPlayer.abortLivePreviewIfNeeded()
            let cancellationRequested = await cancellationState.wasRequested()
            // Assembly or History acceptance can fail after successful synthesis.
            // Do not overwrite the engine's completed boundary with a storage failure.
            if !generationCompleted {
                await services.recordFailed(
                    id: generationID,
                    finishReason: (error is CancellationError || cancellationRequested) ? .cancelled : .failed
                )
            }
            hooks.segmentTelemetryFinalized(generationID: generationID, publishedAudioURL: nil)
            segments[segmentIndex] = priorSegment
            onSegmentsUpdated(segments)
            if error is CancellationError || Task.isCancelled || cancellationRequested {
                return (.cancelled(segments: segments), priorReplacements)
            }
            let message = failureMessage(for: error, afterGeneration: generationCompleted)
            return (.failed(segments: segments, message: message), priorReplacements)
        }
    }

    private enum RunError: LocalizedError {
        case missingSegmentAudio(index: Int, text: VocelloPresentationText)

        var errorDescription: String? {
            switch self {
            case .missingSegmentAudio(let index, let text):
                return text.segmentMissing(index + 1)
            }
        }
    }

    private func assemble(
        request: IOSLongFormProjectRequest,
        segments: [IOSLongFormSegmentState]
    ) async throws -> (evidence: LongFormAssemblyEvidence, outputURL: URL) {
        var sources: [LongFormAssemblySegmentSource] = []
        for (index, segment) in request.plan.segments.enumerated() {
            guard index < segments.count, let path = segments[index].audioPath else {
                throw RunError.missingSegmentAudio(index: index, text: hooks.presentation)
            }
            sources.append(
                LongFormAssemblySegmentSource(
                    segmentID: segment.segmentID,
                    lineage: segment.evidence.lineage,
                    audioURL: URL(fileURLWithPath: path),
                    boundary: segment.evidence.boundary,
                    intendedPauseMilliseconds: segment.evidence.intendedPauseMilliseconds
                )
            )
        }
        guard let firstPath = segments.compactMap(\.audioPath).first else {
            throw RunError.missingSegmentAudio(index: 0, text: hooks.presentation)
        }
        let outputURL = URL(fileURLWithPath: firstPath)
            .deletingLastPathComponent()
            .appendingPathComponent(
                "long_form_joined_\(request.projectDigestPrefix)_\(UUID().uuidString).wav",
                isDirectory: false
            )
        do {
        let evidence = try await BoundedLongFormAssembler.assemble(
            segments: sources,
            outputURL: outputURL,
            provenanceModelID: request.model.id,
            provenanceMode: request.model.mode.rawValue
        )
        return (evidence, outputURL)
        } catch {
            try? FileManager.default.removeItem(at: outputURL)
            throw error
        }
    }

    private func makeAcceptance(
        request: IOSLongFormProjectRequest,
        segments: [IOSLongFormSegmentState],
        qualityReports: [AudioQualityGate.Report?],
        assembly: LongFormAssemblyEvidence,
        replacements: [LongFormSegmentReplacementEvidence],
        joined: Generation,
        joinedQCPassed: Bool,
        ownedAudioURLs: [URL]
    ) async throws -> LongFormHistoryAcceptance {
        let plan = request.plan
        let audioPaths: [String?] = plan.evidence.segments.indices.map { index in
            index < segments.count ? segments[index].audioPath : nil
        }
        let durations: [Double?] = await Task.detached(priority: .utility) {
            audioPaths.map { path -> Double? in
                guard let path,
                      let audioFile = try? AVAudioFile(forReading: URL(fileURLWithPath: path)),
                      audioFile.processingFormat.sampleRate > 0 else { return nil }
                return Double(audioFile.length) / audioFile.processingFormat.sampleRate
            }
        }.value
        var segmentEvidence: [LongFormSegmentExecutionEvidence] = []
        for (index, segment) in plan.evidence.segments.enumerated() {
            let report = index < qualityReports.count ? qualityReports[index] : nil
            segmentEvidence.append(
                LongFormSegmentExecutionEvidence(
                    index: segment.index,
                    segmentID: segment.segmentID,
                    generated: audioPaths[index] != nil,
                    audioDurationSeconds: durations[index],
                    qcPassed: report?.passed,
                    qcRequiredFailures: report?.requiredFailures ?? [],
                    qcWarnings: report?.warnings ?? [],
                    generationID: index < segments.count ? segments[index].generationID : nil,
                    effectiveSeed: index < segments.count ? segments[index].historyRecord?.seed.map { UInt64(bitPattern: $0) } : nil
                )
            )
        }
        let manifest = LongFormManifestV4(
            plan: plan.evidence,
            execution: LongFormExecutionEvidence(
                generatedAtUTC: Date().formatted(.iso8601),
                streamingExecution: true,
                segments: segmentEvidence
            ),
            assembly: assembly,
            replacements: replacements
        )
        guard let firstAudioPath = segments.compactMap(\.audioPath).first else { throw RunError.missingSegmentAudio(index: 0, text: hooks.presentation) }
        let directory = URL(fileURLWithPath: firstAudioPath).deletingLastPathComponent()
        let manifestURL = directory.appendingPathComponent(
            "long_form_manifest_\(request.projectDigestPrefix).json",
            isDirectory: false
        )
        _ = try manifest.canonicalJSONData()
        return LongFormHistoryAcceptance(manifestURL: manifestURL, manifest: manifest,
                                         segments: segments.compactMap(\.historyRecord), joined: joined,
                                         joinedQCPassed: joinedQCPassed,
                                         ownedAudioURLs: ownedAudioURLs)
    }
}
