import AVFoundation
import Foundation
import Observation
import QwenVoiceCore

/// iOS long-form v4: scripts above the single-take limit run as a planned
/// project of ordinary sequential streaming takes — the same shipping design
/// the macOS `BatchGenerationRunner` proved (planner segmentation, per-segment
/// engine + app QC, bounded assembly into one joined WAV, fail-closed manifest
/// v4, one joined History row per project). Everything model-free is shared
/// QwenVoiceCore machinery; this file owns only the iOS execution shell.
///
/// Scope note: in-session resume reuses saved takes, and single-segment
/// regeneration mirrors the macOS replacement lineage: revision >= 2 with a
/// fresh recorded seed, per-segment QC that leaves the prior take untouched on
/// failure, reassembly around the accepted take, and fail-closed manifest
/// `replacements`. Regeneration is in-session only — the retained plan is the
/// identity authority, exactly like resume.

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

    var audioPath: String? {
        if case .saved(let audioPath) = status { return audioPath }
        return nil
    }

    var isSaved: Bool {
        if case .saved = status { return true }
        return false
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
    let languageHint: String?
    let voiceDescription: String?
    let refAudio: String?
    let refText: String?
    let preparedVoiceID: String?

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

    func makeGenerationRequest(
        segmentIndex: Int,
        outputPath: String,
        generationID: UUID,
        seedOverride: UInt64? = nil
    ) -> GenerationRequest {
        let line = lines[segmentIndex]
        let seed = seedOverride ?? plan.segments[segmentIndex].evidence.effectiveSubseed
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
            variation: IOSGenerationVariationPreference.requestValue(),
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

    private(set) var isProcessing = false
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
    var canRegenerateSegments: Bool {
        guard !isProcessing, lastRequest != nil, let outcome else { return false }
        if case .completed = outcome { return true }
        return false
    }

    static func plan(originalText: String) throws -> LongFormPlan {
        let spokenPlan = try SpokenTextPlanner.plan(originalText: originalText)
        return try LongFormPlanner.plan(
            spokenTextPlan: spokenPlan,
            configuration: LongFormPlanningConfiguration(
                runtimeTokenLimit: LongFormPlanningConfiguration.shippingRuntimeTokenLimit,
                baseSeed: UInt64.random(in: UInt64.min ... UInt64.max)
            )
        )
    }

    func start(
        request: IOSLongFormProjectRequest,
        ttsEngine: TTSEngineStore,
        audioPlayer: AudioPlayerViewModel,
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
        audioPlayer: AudioPlayerViewModel,
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
        audioPlayer: AudioPlayerViewModel,
        studioCoordinator: StudioGenerationCoordinator
    ) {
        guard canRegenerateSegments, !ttsEngine.hasActiveGeneration,
              let request = lastRequest,
              let priorSegments = outcome?.segments,
              index >= 0, index < priorSegments.count else { return }
        guard let attempt = studioCoordinator.start(live: nil) else { return }
        let acceptedOutcome = outcome
        isProcessing = true
        // A new operation owns a new cancellation token. An asynchronously
        // scheduled reset could otherwise erase an immediately requested cancel.
        cancellationState = IOSLongFormCancellationState()
        let runner = IOSLongFormProjectRunner(
            ttsEngine: ttsEngine,
            audioPlayer: audioPlayer,
            cancellationState: cancellationState
        )
        segments = priorSegments
        progress = IOSLongFormProgressSnapshot(
            completedCount: priorSegments.count(where: \.isSaved),
            totalCount: priorSegments.count,
            activeSegmentIndex: index,
            statusMessage: "Regenerating segment \(index + 1) of \(priorSegments.count)…"
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

    func cancel(
        ttsEngine: TTSEngineStore,
        audioPlayer: AudioPlayerViewModel,
        studioCoordinator: StudioGenerationCoordinator
    ) {
        guard isProcessing else { return }
        guard let attempt = studioCoordinator.requestCancellation() else { return }
        let state = cancellationState
        runTask?.cancel()
        audioPlayer.abortLivePreviewIfNeeded()
        Task {
            await state.request()
            do {
                try await ttsEngine.cancelActiveGeneration()
                studioCoordinator.completeCancellation(attempt: attempt)
            } catch {
                if studioCoordinator.failCancellation(error, attempt: attempt) {
                    IOSHaptics.warning()
                }
            }
        }
    }

    private func begin(
        request: IOSLongFormProjectRequest,
        reusing prior: [IOSLongFormSegmentState]?,
        ttsEngine: TTSEngineStore,
        audioPlayer: AudioPlayerViewModel,
        studioCoordinator: StudioGenerationCoordinator
    ) {
        guard !isProcessing, !ttsEngine.hasActiveGeneration else { return }
        if lastRequest?.plan.evidence.planDigest != request.plan.evidence.planDigest {
            replacements = []
        }
        guard let attempt = studioCoordinator.start(live: nil) else { return }
        lastRequest = request
        lastMode = request.mode
        outcome = nil
        isProcessing = true
        cancellationState = IOSLongFormCancellationState()
        let runner = IOSLongFormProjectRunner(
            ttsEngine: ttsEngine,
            audioPlayer: audioPlayer,
            cancellationState: cancellationState
        )
        segments = request.lines.enumerated().map { index, line in
            if let prior, index < prior.count, prior[index].isSaved, prior[index].line == line {
                return prior[index]
            }
            return IOSLongFormSegmentState(index: index, line: line, status: .pending)
        }
        progress = IOSLongFormProgressSnapshot(
            completedCount: segments.count(where: \.isSaved),
            totalCount: segments.count,
            activeSegmentIndex: nil,
            statusMessage: "Preparing long-form project…"
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
        audioPlayer: AudioPlayerViewModel,
        studioCoordinator: StudioGenerationCoordinator,
        studioAttempt: StudioGenerationAttemptToken
    ) {
        switch outcome {
        case .completed(_, let joinedAudioPath, let joinedDurationSeconds):
            let shouldAutoPlay = AudioService.shouldAutoPlay
            audioPlayer.completeStreamingPreview(
                result: GenerationResult(
                    audioPath: joinedAudioPath,
                    durationSeconds: joinedDurationSeconds,
                    streamSessionDirectory: nil,
                    usedStreaming: false
                ),
                title: String(request.lines.joined(separator: " ").prefix(40)),
                shouldAutoPlay: shouldAutoPlay
            )
            let transcript = request.lines.joined(separator: " ")
            let accepted = studioCoordinator.complete(
                IOSStudioInlinePlayerItem(
                    generationID: UUID(),
                    audioURL: URL(fileURLWithPath: joinedAudioPath),
                    voiceName: "Long-form project",
                    modeLabel: "Long-form",
                    mode: request.mode,
                    transcript: transcript,
                    waveformSeed: IOSStableVisualHash.int(transcript),
                    autoplay: false,
                    ownedBySharedPlayer: shouldAutoPlay
                ),
                attempt: studioAttempt
            )
            if accepted { IOSHaptics.success() }
        case .cancelled:
            studioCoordinator.finish(attempt: studioAttempt)
        case .failed(_, let message):
            if studioCoordinator.fail(message, attempt: studioAttempt) {
                IOSHaptics.warning()
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
    private let audioPlayer: AudioPlayerViewModel
    private let cancellationState: IOSLongFormCancellationState

    init(
        ttsEngine: TTSEngineStore,
        audioPlayer: AudioPlayerViewModel,
        cancellationState: IOSLongFormCancellationState
    ) {
        self.ttsEngine = ttsEngine
        self.audioPlayer = audioPlayer
        self.cancellationState = cancellationState
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
                    segments[index].status = .failed(message: report.failureSummary)
                    onSegmentsUpdated(segments)
                    return .failed(
                        segments: segments,
                        message: "A previously generated segment no longer passes audio quality checks."
                    )
                }
                publish(active: index, message: "Reusing segment \(index + 1) of \(total)…")
                continue
            }

            segments[index].status = .running
            publish(active: index, message: "Generating segment \(index + 1) of \(total)…")

            let generationID = UUID()
            let outputPath = LongFormHistoryAcceptance.uniqueAudioURL(basedOn: URL(fileURLWithPath: makeOutputPath(
                subfolder: request.model.outputSubfolder,
                text: request.outputText(forSegment: index)
            ))).path
            do {
                // Live narration per segment (playback gated by the user's
                // auto-play preference; publication always on).
                audioPlayer.setLivePreviewEstimate(LivePreviewEstimate(text: line))
                audioPlayer.prepareStreamingPreview(
                    title: "Segment \(index + 1) of \(total)",
                    shouldAutoPlay: AudioService.shouldAutoPlay
                )
                studioCoordinator.updateLiveItem(IOSStudioLivePreviewItem(
                    voiceName: "Segment \(index + 1) of \(total)",
                    modeLabel: "Long-form",
                    mode: request.mode,
                    transcript: line,
                    waveformSeed: IOSStableVisualHash.int(line),
                    estimatedAudioDuration: LivePreviewEstimate(text: line)?.estimatedAudioDuration ?? 0
                ), attempt: studioAttempt)
                await AppGenerationTimeline.shared.recordSubmitted(
                    id: generationID,
                    mode: request.mode.rawValue
                )
                let result = try await ttsEngine.generate(
                    request.makeGenerationRequest(
                        segmentIndex: index,
                        outputPath: outputPath,
                        generationID: generationID
                    )
                )
                let cancellationRequestedAfterTake = await cancellationState.wasRequested()
                if Task.isCancelled || cancellationRequestedAfterTake {
                    await AppGenerationTimeline.shared.recordFailed(id: generationID, finishReason: .cancelled)
                    IOSPullableDiagnosticsMirror.syncGenerationTelemetryIfEnabled(generationID: generationID)
                    try? FileManager.default.removeItem(atPath: result.audioPath)
                    audioPlayer.abortLivePreviewIfNeeded()
                    markCancelled(startingAt: index)
                    return .cancelled(segments: segments)
                }
                await AppGenerationTimeline.shared.recordCompleted(
                    id: generationID,
                    mode: request.mode.rawValue,
                    usedStreaming: true,
                    finishReason: result.finishReason?.rawValue,
                    summary: result.telemetrySummary
                )
                IOSPullableDiagnosticsMirror.syncGenerationTelemetryIfEnabled(generationID: generationID)

                let report = await evaluateQC(
                    path: result.audioPath,
                    expectedPauseCount: PersistedWAVAudioQCAnalyzer.expectedPauseCount(in: line)
                )
                qualityReports.append(report)
                segments[index].qualityReport = report
                guard report.passed else {
                    segments[index].status = .failed(message: report.failureSummary)
                    try? FileManager.default.removeItem(atPath: result.audioPath)
                    audioPlayer.abortLivePreviewIfNeeded()
                    onSegmentsUpdated(segments)
                    return .failed(
                        segments: segments,
                        message: "Segment \(index + 1) failed audio quality checks. \(report.failureSummary)"
                    )
                }

                var record = request.makeSegmentHistoryRecord(
                    forSegment: index,
                    audioPath: result.audioPath,
                    duration: result.durationSeconds
                )
                record.seed = Int64(bitPattern: request.plan.segments[index].evidence.effectiveSubseed)
                segments[index].historyRecord = record
                segments[index].generationID = generationID
                let persistence = await GenerationPersistence.persist(record, caller: "IOSLongFormSegment")
                try persistence.requireSavedLongFormSegment()
                segments[index].status = .saved(audioPath: result.audioPath)
                publish(active: index, message: "Generated segment \(index + 1) of \(total); project not yet saved")
            } catch {
                audioPlayer.abortLivePreviewIfNeeded()
                let cancellationRequested = await cancellationState.wasRequested()
                await AppGenerationTimeline.shared.recordFailed(
                    id: generationID,
                    finishReason: (error is CancellationError || cancellationRequested) ? .cancelled : .failed
                )
                IOSPullableDiagnosticsMirror.syncGenerationTelemetryIfEnabled(generationID: generationID)
                if error is CancellationError || Task.isCancelled || cancellationRequested {
                    markCancelled(startingAt: index)
                    return .cancelled(segments: segments)
                }
                segments[index].status = .failed(message: error.localizedDescription)
                onSegmentsUpdated(segments)
                return .failed(segments: segments, message: error.localizedDescription)
            }
        }

        if await cancellationState.wasRequested() {
            markCancelled(startingAt: 0)
            return .cancelled(segments: segments)
        }

        // Close the final segment's live session deterministically before the
        // join so the completed-project handoff never overlaps a draining
        // live tail.
        audioPlayer.abortLivePreviewIfNeeded()
        publish(active: nil, message: "Joining \(total) segments…")
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
                return .failed(
                    segments: segments,
                    message: "The joined long-form output failed audio quality checks: \(joinedReport.failureSummary)"
                )
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
            let saved = try await DatabaseService.shared.acceptLongFormProject(candidate)
            candidateJoinedURL = nil
            NotificationCenter.default.post(name: .generationSaved, object: nil)
            IOSSavedOutputsDestination.exportIfConfigured(internalAudioPath: joined.outputURL.path)
            publish(active: nil, message: "Done")
            return .completed(
                segments: segments,
                joinedAudioPath: joined.outputURL.path,
                joinedDurationSeconds: saved.duration
                    ?? Double(joined.evidence.outputFrameCount) / Double(joined.evidence.sampleRate)
            )
        } catch {
            if error as? LongFormAcceptanceError == .recoveryRequired { candidateJoinedURL = nil }
            if error is CancellationError { return .cancelled(segments: segments) }
            return .failed(
                segments: segments,
                message: "Long-form assembly failed: \(error.localizedDescription)"
            )
        }
    }

    /// Mirrors the macOS `BatchGenerationRunner.regenerateSegment` semantics
    /// on the iOS sequential runner: one fresh-seeded take for the chosen
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
                    message: "The segment to regenerate is not part of this completed project."
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
        publish(active: segmentIndex, message: "Regenerating segment \(segmentIndex + 1) of \(total)…")

        let generationID = UUID()
        let outputPath = LongFormHistoryAcceptance.uniqueAudioURL(basedOn: URL(fileURLWithPath: makeOutputPath(
            subfolder: request.model.outputSubfolder,
            text: request.outputText(forSegment: segmentIndex)
        ))).path
        var candidateAudioURLs: [URL] = []
        var generationCompleted = false
        defer { for url in candidateAudioURLs { try? FileManager.default.removeItem(at: url) } }
        do {
            audioPlayer.setLivePreviewEstimate(LivePreviewEstimate(text: line))
            audioPlayer.prepareStreamingPreview(
                title: "Segment \(segmentIndex + 1) of \(total)",
                shouldAutoPlay: AudioService.shouldAutoPlay
            )
            studioCoordinator.updateLiveItem(IOSStudioLivePreviewItem(
                voiceName: "Segment \(segmentIndex + 1) of \(total)",
                modeLabel: "Long-form",
                mode: request.mode,
                transcript: line,
                waveformSeed: IOSStableVisualHash.int(line),
                estimatedAudioDuration: LivePreviewEstimate(text: line)?.estimatedAudioDuration ?? 0
            ), attempt: studioAttempt)
            await AppGenerationTimeline.shared.recordSubmitted(
                id: generationID,
                mode: request.mode.rawValue
            )
            let result = try await ttsEngine.generate(
                request.makeGenerationRequest(
                    segmentIndex: segmentIndex,
                    outputPath: outputPath,
                    generationID: generationID,
                    seedOverride: replacementSeed
                )
            )
            let cancellationRequestedAfterTake = await cancellationState.wasRequested()
            candidateAudioURLs.append(URL(fileURLWithPath: result.audioPath))
            if Task.isCancelled || cancellationRequestedAfterTake {
                await AppGenerationTimeline.shared.recordFailed(id: generationID, finishReason: .cancelled)
                IOSPullableDiagnosticsMirror.syncGenerationTelemetryIfEnabled(generationID: generationID)
                try? FileManager.default.removeItem(atPath: result.audioPath)
                audioPlayer.abortLivePreviewIfNeeded()
                segments[segmentIndex] = priorSegment
                onSegmentsUpdated(segments)
                return (.cancelled(segments: segments), priorReplacements)
            }
            await AppGenerationTimeline.shared.recordCompleted(
                id: generationID,
                mode: request.mode.rawValue,
                usedStreaming: true,
                finishReason: result.finishReason?.rawValue,
                summary: result.telemetrySummary
            )
            generationCompleted = true
            IOSPullableDiagnosticsMirror.syncGenerationTelemetryIfEnabled(generationID: generationID)

            let report = await evaluateQC(
                path: result.audioPath,
                expectedPauseCount: PersistedWAVAudioQCAnalyzer.expectedPauseCount(in: line)
            )
            guard report.passed else {
                segments[segmentIndex] = priorSegment
                onSegmentsUpdated(segments)
                return (
                    .failed(
                        segments: segments,
                        message: "The regenerated take failed audio quality checks; the previous take is unchanged. \(report.failureSummary)"
                    ),
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

            audioPlayer.abortLivePreviewIfNeeded()
            // Keep the accepted visible segments until the whole replacement
            // transaction succeeds; the candidate is local to this operation.
            onProgress(IOSLongFormProgressSnapshot(totalCount: total, statusMessage: "Joining \(total) segments…"))
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
                    .failed(
                        segments: priorSegments,
                        message: "The joined long-form output failed audio quality checks after regeneration: \(joinedReport.failureSummary)"
                    ),
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
            let saved = try await DatabaseService.shared.acceptLongFormProject(candidate)
            candidateAudioURLs.removeAll()
            NotificationCenter.default.post(name: .generationSaved, object: nil)
            IOSSavedOutputsDestination.exportIfConfigured(internalAudioPath: joined.outputURL.path)
            publish(active: nil, message: "Done")
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
            if error as? LongFormAcceptanceError == .recoveryRequired { candidateAudioURLs.removeAll() }
            audioPlayer.abortLivePreviewIfNeeded()
            let cancellationRequested = await cancellationState.wasRequested()
            // Assembly or History acceptance can fail after successful synthesis.
            // Do not overwrite the engine's completed boundary with a storage failure.
            if !generationCompleted {
                await AppGenerationTimeline.shared.recordFailed(
                    id: generationID,
                    finishReason: (error is CancellationError || cancellationRequested) ? .cancelled : .failed
                )
            }
            IOSPullableDiagnosticsMirror.syncGenerationTelemetryIfEnabled(generationID: generationID)
            segments[segmentIndex] = priorSegment
            onSegmentsUpdated(segments)
            if error is CancellationError || Task.isCancelled || cancellationRequested {
                return (.cancelled(segments: segments), priorReplacements)
            }
            return (
                .failed(segments: segments, message: error.localizedDescription),
                priorReplacements
            )
        }
    }

    private enum RunError: LocalizedError {
        case missingSegmentAudio(index: Int)

        var errorDescription: String? {
            switch self {
            case .missingSegmentAudio(let index):
                return "Segment \(index + 1) has no generated audio to join."
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
                throw RunError.missingSegmentAudio(index: index)
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
            throw RunError.missingSegmentAudio(index: 0)
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
        guard let firstAudioPath = segments.compactMap(\.audioPath).first else { throw RunError.missingSegmentAudio(index: 0) }
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
