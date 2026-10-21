import Foundation
import QwenVoiceCore
import Synchronization

/// One long-form project the way the apps run one: the shared
/// `IOSLongFormProjectRunner` over this host's store, so every segment and the
/// joined output pass the apps' audio QC, Auto resolves one language for the
/// whole script, and the fail-closed manifest v4 is written. Headless: no
/// player, no Studio surface, and no History rows (the interim policy until
/// RF-30's History lock): segments, the joined output and the manifest stay in
/// the request's folder.
public struct DesktopLongFormRequest: Sendable {
    public let mode: GenerationMode
    public let modelID: String
    public let plan: LongFormPlan
    /// The take's payload, as for a single take: the speaker or brief and its
    /// delivery, or the clone reference.
    public let payload: GenerationRequest.Payload
    public let deliveryInstructionCellID: String?
    /// The language selection; nil or Auto resolves over the whole script.
    public let languageHint: String?
    public let variation: Qwen3SamplingVariation?
    /// Where segment takes, the joined output and the manifest are written.
    public let directory: URL

    public init(
        mode: GenerationMode, modelID: String, plan: LongFormPlan, payload: GenerationRequest.Payload,
        deliveryInstructionCellID: String?, languageHint: String?, variation: Qwen3SamplingVariation?,
        directory: URL
    ) {
        self.mode = mode
        self.modelID = modelID
        self.plan = plan
        self.payload = payload
        self.deliveryInstructionCellID = deliveryInstructionCellID
        self.languageHint = languageHint
        self.variation = variation
        self.directory = directory
    }
}

/// What a running project reports: a segment's take starting and its verdict.
public enum DesktopLongFormEvent: Sendable {
    case segmentStarted(index: Int, total: Int, generationID: UUID)
    /// The take passed the engine's and the apps' QC and is kept.
    case segmentSaved(index: Int, generationID: UUID, durationSeconds: Double?)
    /// The take failed, or the apps' QC rejected it.
    case segmentFailed(index: Int, generationID: UUID, qcRejected: Bool)
    case segmentCancelled(index: Int, generationID: UUID)
}

public struct DesktopLongFormSegment: Sendable {
    public enum Status: String, Sendable {
        case saved, failed, cancelled, pending
    }

    public let index: Int
    public let segmentID: String
    public let boundary: String
    public let intendedPauseMilliseconds: Int
    /// The seed of the segment's take: its planned sub-seed.
    public let seed: UInt64
    public let status: Status
    public let generationID: UUID?
    public let audioPath: String?
    public let durationSeconds: Double?
    public let finishReason: String?
    /// The apps' audio QC verdict; nil when the take never reached it.
    public let qcPassed: Bool?
    public let qcRequiredFailures: [String]
    public let qcWarnings: [String]

    public init(
        index: Int, segmentID: String, boundary: String, intendedPauseMilliseconds: Int, seed: UInt64,
        status: Status, generationID: UUID?, audioPath: String?, durationSeconds: Double?, finishReason: String?,
        qcPassed: Bool?, qcRequiredFailures: [String], qcWarnings: [String]
    ) {
        self.index = index
        self.segmentID = segmentID
        self.boundary = boundary
        self.intendedPauseMilliseconds = intendedPauseMilliseconds
        self.seed = seed
        self.status = status
        self.generationID = generationID
        self.audioPath = audioPath
        self.durationSeconds = durationSeconds
        self.finishReason = finishReason
        self.qcPassed = qcPassed
        self.qcRequiredFailures = qcRequiredFailures
        self.qcWarnings = qcWarnings
    }
}

public struct DesktopLongFormOutcome: Sendable {
    public enum Status: Sendable {
        case completed, cancelled, failed
    }

    /// Why a project failed, typed for the caller's error codes.
    public enum Failure: Sendable, Equatable {
        case segmentQCRejected(index: Int)
        case joinedQCRejected
        /// An engine or store failure, with its typed reason when it has one.
        case generation(GenerationFailurePresentationReason?)
        case assembly
        case other
    }

    public let status: Status
    public let failure: Failure?
    /// The apps' message for a failure (English).
    public let message: String?
    public let segments: [DesktopLongFormSegment]
    /// The language every segment carried: the selection, or Auto resolved over the script.
    public let languageHint: String?
    public let joinedPath: String?
    public let durationSeconds: Double?
    public let manifestPath: String?
    public let assembly: LongFormAssemblyEvidence?

    public init(
        status: Status, failure: Failure?, message: String?, segments: [DesktopLongFormSegment],
        languageHint: String?, joinedPath: String?, durationSeconds: Double?, manifestPath: String?,
        assembly: LongFormAssemblyEvidence?
    ) {
        self.status = status
        self.failure = failure
        self.message = message
        self.segments = segments
        self.languageHint = languageHint
        self.joinedPath = joinedPath
        self.durationSeconds = durationSeconds
        self.manifestPath = manifestPath
        self.assembly = assembly
    }
}

extension DesktopLongFormOutcome.Failure {
    /// The apps' English message for a failure `reason`, as a failed project reports it.
    public static func message(for reason: GenerationFailurePresentationReason) -> String {
        VocelloPresentationText().generationFailureMessage(reason)
    }

    /// A failed project's failure, read back from its segments and from the
    /// message's catalog entry: the runner reports a failure as the apps'
    /// message only (English here, with no interface language).
    public init(message: String, segments: [DesktopLongFormSegment]) {
        let presentation = VocelloPresentationText()
        if let rejected = segments.first(where: { $0.status == .failed && $0.qcPassed == false }) {
            self = .segmentQCRejected(index: rejected.index)
        } else if message == presentation.joinedQCRejected {
            self = .joinedQCRejected
        } else if message == presentation.longFormJoinFailed {
            self = .assembly
        } else if let reason = GenerationFailurePresentationReason.allCases.first(where: {
            presentation.generationFailureMessage($0) == message
        }) {
            self = .generation(reason)
        } else {
            self = segments.contains(where: { $0.status == .failed }) ? .generation(nil) : .other
        }
    }
}

extension DesktopEngineHost {
    /// Runs `request` to its outcome. A signal reaches it as task cancellation; a
    /// project the engine stopped on its own ends `cancelled` with the task not
    /// cancelled.
    public func runLongForm(
        _ request: DesktopLongFormRequest,
        defaultSpeakerID: String,
        events: @escaping @MainActor (DesktopLongFormEvent) -> Void
    ) async -> DesktopLongFormOutcome {
        DesktopSpeakerDefault.id.withLock { $0 = defaultSpeakerID }
        let presentation = VocelloPresentationText()
        guard let model = store.modelRegistry.model(id: request.modelID) else {
            return DesktopLongFormOutcome(
                status: .failed, failure: .generation(.modelUnavailable),
                message: presentation.generationFailureMessage(.modelUnavailable), segments: [],
                languageHint: request.languageHint, joinedPath: nil, durationSeconds: nil, manifestPath: nil,
                assembly: nil
            )
        }
        let projectRequest = IOSLongFormProjectRequest(
            mode: request.mode, model: model, plan: request.plan,
            voice: request.payload.speakerID, emotion: request.payload.deliveryInstructionText,
            deliveryInstructionCellID: request.deliveryInstructionCellID, languageHint: request.languageHint,
            voiceDescription: request.payload.voiceDescription,
            refAudio: request.payload.cloneReference?.audioPath,
            refText: request.payload.cloneReference?.transcript,
            preparedVoiceID: request.payload.cloneReference?.preparedVoiceID
        )
        let hooks = HeadlessLongFormHooks(presentation: presentation, variation: request.variation)
        let services = HeadlessLongFormServices(directory: request.directory, total: request.plan.segments.count, events: events)
        let studio = StudioGenerationCoordinator(mode: request.mode, presentation: { presentation }, announce: { _ in })
        // A fresh coordinator has no attempt running, so it always starts one.
        guard let attempt = studio.start() else {
            preconditionFailure("a new Studio coordinator refused its first attempt")
        }
        let cancellationState = IOSLongFormCancellationState()
        let runner = IOSLongFormProjectRunner(
            ttsEngine: store, audioPlayer: HeadlessLongFormPlayback(),
            cancellationState: cancellationState, hooks: hooks, services: services
        )
        let initial = projectRequest.lines.enumerated().map { IOSLongFormSegmentState(index: $0, line: $1, status: .pending) }
        // A signal cancels this task; the runner also honours the Stop the apps
        // request, which closes the window between the join and its acceptance
        // (finalization refuses once a Stop is accepted, A1-01, U24).
        let outcome = await withTaskCancellationHandler {
            await runner.run(
                request: projectRequest, initialSegments: initial, priorReplacements: [],
                onProgress: { _ in },
                onSegmentsUpdated: { services.observe($0) },
                studioCoordinator: studio, studioAttempt: attempt
            )
        } onCancel: {
            Task { @MainActor in
                _ = studio.requestCancellation(cancelsTask: false)
                await cancellationState.request()
            }
        }
        return Self.report(outcome, request: projectRequest, accepted: services.accepted)
    }

    private static func report(
        _ outcome: IOSLongFormOutcome, request: IOSLongFormProjectRequest,
        accepted: (acceptance: LongFormHistoryAcceptance, manifestPath: String)?
    ) -> DesktopLongFormOutcome {
        let states = outcome.segments
        let segments = request.plan.segments.enumerated().map { index, planned in
            let state = index < states.count ? states[index] : nil
            let status: DesktopLongFormSegment.Status
            switch state?.status {
            case .saved: status = .saved
            case .failed: status = .failed
            case .cancelled: status = .cancelled
            case .pending, .running, nil: status = .pending
            }
            return DesktopLongFormSegment(
                index: index, segmentID: planned.segmentID, boundary: planned.evidence.boundary.rawValue,
                intendedPauseMilliseconds: planned.evidence.intendedPauseMilliseconds,
                seed: state?.historyRecord?.samplingSeed ?? request.plannedSeed(forSegment: index),
                status: status, generationID: state?.generationID, audioPath: state?.audioPath,
                durationSeconds: state?.historyRecord?.duration,
                finishReason: state?.historyRecord?.completionReceipt?.finishReason?.rawValue,
                qcPassed: state?.qualityReport?.passed,
                qcRequiredFailures: state?.qualityReport?.requiredFailures ?? [],
                qcWarnings: state?.qualityReport?.warnings ?? []
            )
        }
        switch outcome {
        case .completed(_, let joinedAudioPath, let joinedDurationSeconds):
            return DesktopLongFormOutcome(
                status: .completed, failure: nil, message: nil, segments: segments,
                languageHint: request.languageHint, joinedPath: joinedAudioPath,
                durationSeconds: joinedDurationSeconds, manifestPath: accepted?.manifestPath,
                assembly: accepted?.acceptance.manifest.assembly
            )
        case .cancelled:
            return DesktopLongFormOutcome(
                status: .cancelled, failure: nil, message: nil, segments: segments,
                languageHint: request.languageHint, joinedPath: nil, durationSeconds: nil, manifestPath: nil,
                assembly: nil
            )
        case .failed(_, let message):
            return DesktopLongFormOutcome(
                status: .failed, failure: DesktopLongFormOutcome.Failure(message: message, segments: segments),
                message: message, segments: segments, languageHint: request.languageHint, joinedPath: nil,
                durationSeconds: nil, manifestPath: nil, assembly: nil
            )
        }
    }
}

// MARK: - Headless collaborators

/// No interface: the CLI reports through its own events.
@MainActor
private final class HeadlessLongFormHooks: IOSLongFormPlatformHooks {
    let presentation: VocelloPresentationText
    private let variation: Qwen3SamplingVariation?

    init(presentation: VocelloPresentationText, variation: Qwen3SamplingVariation?) {
        self.presentation = presentation
        self.variation = variation
    }

    func requestVariation() -> Qwen3SamplingVariation? { variation }
    func waveformSeed(for text: String) -> Int { 0 }
    func segmentTitle(index: Int, total: Int) -> String { "Segment \(index + 1) of \(total)" }
    var longFormModeLabel: String { "" }
    var longFormProjectTitle: String { "" }
    func segmentTelemetryFinalized(generationID: UUID, publishedAudioURL: URL?) {}
    func projectAccepted(_ saved: Generation, joinedAudioPath: String) {}
    func notifySuccess() {}
    func notifyWarning() {}
}

/// No player: nothing narrates live or plays the joined output.
@MainActor
private final class HeadlessLongFormPlayback: IOSLongFormAudioPlayback {
    func beginGenerationPlayback(operationID: UUID, mode: GenerationMode) {}
    func setLivePreviewEstimate(_ estimate: LivePreviewEstimate?) {}
    func prepareStreamingPreview(title: String, shouldAutoPlay: Bool, generationID: UUID?, playbackOperationID: UUID?) {}
    func completeStreamingPreview(
        result: GenerationResult, title: String, shouldAutoPlay: Bool, playbackOperationID: UUID?
    ) {}
    func abortLivePreviewIfNeeded() {}
    func finishGenerationPreview(playbackOperationID: UUID) {}
}

/// Segment takes in the request's folder, events for the CLI, no History: a
/// segment counts as kept on disk, and accepting the project writes its manifest.
@MainActor
private final class HeadlessLongFormServices: IOSLongFormProjectServices {
    private let directory: URL
    private let total: Int
    private let events: @MainActor (DesktopLongFormEvent) -> Void
    private var submitted: [UUID: Int] = [:]
    private var reported: Set<UUID> = []
    private(set) var accepted: (acceptance: LongFormHistoryAcceptance, manifestPath: String)?

    init(directory: URL, total: Int, events: @escaping @MainActor (DesktopLongFormEvent) -> Void) {
        self.directory = directory
        self.total = total
        self.events = events
    }

    var shouldAutoPlay: Bool { false }

    /// The runner asks once per take, in segment order, and adds a unique suffix.
    func segmentOutputPath(subfolder: String) -> String {
        directory.appendingPathComponent(unsafe String(format: "segment_%03d.wav", submitted.count)).path
    }

    func recordSubmitted(id: UUID, mode: String) async {
        let index = submitted.count
        submitted[id] = index
        events(.segmentStarted(index: index, total: total, generationID: id))
    }

    func recordCompleted(
        id: UUID, mode: String, usedStreaming: Bool, finishReason: String?, summary: TelemetrySummary?
    ) async {}

    func recordFailed(id: UUID, finishReason: GenerationTerminalReason) async {
        guard let index = submitted[id], reported.insert(id).inserted else { return }
        events(finishReason == .cancelled
            ? .segmentCancelled(index: index, generationID: id)
            : .segmentFailed(index: index, generationID: id, qcRejected: false))
    }

    /// A take's verdict after the apps' QC: kept, or rejected.
    func observe(_ segments: [IOSLongFormSegmentState]) {
        for segment in segments {
            guard let id = segment.generationID ?? submitted.first(where: { $0.value == segment.index })?.key,
                  !reported.contains(id) else { continue }
            switch segment.status {
            case .saved:
                reported.insert(id)
                events(.segmentSaved(index: segment.index, generationID: id, durationSeconds: segment.historyRecord?.duration))
            case .failed where segment.qualityReport?.passed == false:
                reported.insert(id)
                events(.segmentFailed(index: segment.index, generationID: id, qcRejected: true))
            case .cancelled where submitted[id] != nil:
                // A take stopped after the engine finished it (during its QC) has
                // no `recordFailed`; its terminal is reported here.
                reported.insert(id)
                events(.segmentCancelled(index: segment.index, generationID: id))
            default:
                continue
            }
        }
    }

    func persistSegment(_ record: Generation, caller: String) async -> GenerationHistoryPersistenceOutcome {
        .saved
    }

    func acceptLongFormProject(_ candidate: LongFormHistoryAcceptance) async throws -> Generation {
        let data = try candidate.manifest.canonicalJSONData()
        try data.write(to: candidate.manifestURL, options: .atomic)
        accepted = (candidate, candidate.manifestURL.path)
        return candidate.joined
    }
}

private extension GenerationRequest.Payload {
    var speakerID: String? {
        if case .custom(let speakerID, _) = self { return speakerID }
        return nil
    }

    var voiceDescription: String? {
        if case .design(let voiceDescription, _) = self { return voiceDescription }
        return nil
    }

    var cloneReference: CloneReference? {
        if case .clone(let reference) = self { return reference }
        return nil
    }
}
