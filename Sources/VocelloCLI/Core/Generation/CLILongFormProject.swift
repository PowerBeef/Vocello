import Foundation
import QwenVoiceCore
import VocelloDesktopCore

/// One long-form project, run by the apps' own runner (`IOSLongFormProjectRunner`
/// through `DesktopEngineHost.runLongForm`): the shipping planner splits the
/// script (base seed given or drawn at random, each segment sampling with its
/// derived subseed), Auto resolves one language for the whole script, each
/// segment is one streaming take at the app cadence that must pass the engine's
/// Fast QC and the apps' audio QC, the bounded assembler joins them, the joined
/// output must pass the apps' QC too, and the manifest v4 is written beside the
/// segments. Shared by `batch --long-form` (a project per line) and `generate`
/// (a script past one take). No History rows until RF-30's History lock.
public enum CLILongFormProject {
    /// One kept segment take. No text: the project's is the item's.
    public struct Segment: Encodable, Sendable {
        let index: Int
        let segmentID: String
        let boundary: String
        let intendedPauseMilliseconds: Int
        /// A decimal string, as every 64-bit value in the machine contract.
        let effectiveSeed: String
        let generationID: String
        let audioPath: String
        let durationSeconds: Double
        let finishReason: String?
        /// The apps' audio QC warnings on the take (it passed).
        let qcWarnings: [String]
    }

    /// Why a project stopped before its joined output.
    public enum Stop: Sendable {
        /// A segment, the join or a QC check failed with `error` (its row code
        /// `code`), possibly while a signal arrived.
        case failed(any Error, code: VocelloErrorCode, cancellationRequested: Bool)
        /// A signal stopped it.
        case cancelled
        /// The engine stopped a segment on its own (memory pressure).
        case engine(CLIEngineCancellation)
    }

    public struct Outcome: Sendable {
        public let baseSeed: UInt64
        public let planDigest: String
        /// The completed segment takes, kept even when the project stopped.
        public internal(set) var segments: [Segment] = []
        /// The language every segment carried (the selection, or Auto resolved over the script).
        public internal(set) var language: String?
        public internal(set) var assembly: LongFormAssemblyEvidence?
        /// The joined output, in the project's folder until the caller moves it.
        public internal(set) var audioPath: String?
        public internal(set) var manifestPath: String?
        public internal(set) var durationSeconds: Double?
        public internal(set) var finishReason: String?
        /// The segment take that failed (or the last submitted); nil when the join, not a take,
        /// stopped it or nothing was submitted.
        public internal(set) var generationID: UUID?
        public internal(set) var stop: Stop?

        public var completed: Bool { stop == nil && audioPath != nil }
    }

    /// Plans `text` as one project; refuses one the apps would refuse.
    public static func plan(_ text: String, seed: UInt64?) throws -> LongFormPlan {
        let plan: LongFormPlan
        do {
            let spokenPlan = try SpokenTextPlanner.plan(originalText: text)
            plan = try LongFormPlanner.plan(
                spokenTextPlan: spokenPlan,
                configuration: LongFormPlanningConfiguration(
                    runtimeTokenLimit: LongFormPlanningConfiguration.shippingRuntimeTokenLimit,
                    baseSeed: seed ?? UInt64.random(in: UInt64.min ... UInt64.max)
                )
            )
        } catch {
            // The planner's errors carry no text.
            throw CLIError(.invalidInput, "the long-form planner refused the project (\(error))")
        }
        try admit(segmentCount: plan.segments.count)
        return plan
    }

    /// The apps refuse a plan of more segments than `CLILimits.longFormMaximumSegments`.
    static func admit(segmentCount: Int) throws {
        guard segmentCount <= CLILimits.longFormMaximumSegments else {
            throw CLIError(
                .textTooLong,
                "the project plans \(segmentCount) segments, more than the \(CLILimits.longFormMaximumSegments) the apps accept"
            )
        }
    }

    /// The project's own folder beside `output`: `<stem>_segments`, or, when that
    /// already exists (an earlier run's, or anyone's), `<stem>_segments-<attempt>`.
    /// Created here and never reused, so a stop removes only what this attempt
    /// made and two runs never mix their segments. Being a new subfolder of the
    /// output's folder, it lies on the output's volume, so the joined output
    /// moves onto `output` by an atomic rename.
    public static func makeProjectFolder(beside output: URL, attempt: UUID) throws -> URL {
        let parent = output.deletingLastPathComponent()
        let stem = output.deletingPathExtension().lastPathComponent
        let attemptTag = String(attempt.uuidString.lowercased().prefix(8))
        for name in ["\(stem)_segments", "\(stem)_segments-\(attemptTag)"] {
            let folder = parent.appendingPathComponent(name, isDirectory: true)
            do {
                try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: false)
                return folder
            } catch CocoaError.fileWriteFileExists {
                continue
            } catch {
                throw CLIError(.outputUnavailable, "could not create \(folder.path): \(error.localizedDescription)")
            }
        }
        throw CLIError(
            .outputUnavailable, "the segment folders for \(output.path) already exist",
            hint: "choose another --out, or move the existing segment folders away"
        )
    }

    /// A clone project never replaces its reference audio: the engine refuses that
    /// for each take, but the joined output reaches `--out` by the CLI's own
    /// rename. Lexical, symlink and hard-link aliases all count, as in the engine.
    static func refuseReferenceAlias(output: String, payload: GenerationRequest.Payload) throws {
        guard case .clone(let reference) = payload else { return }
        let outputURL = URL(fileURLWithPath: output).resolvingSymlinksInPath().standardizedFileURL
        let referenceURL = URL(fileURLWithPath: reference.audioPath).resolvingSymlinksInPath().standardizedFileURL
        let outputAttributes = try? FileManager.default.attributesOfItem(atPath: outputURL.path)
        let referenceAttributes = try? FileManager.default.attributesOfItem(atPath: referenceURL.path)
        let outputFile = outputAttributes?[.systemFileNumber] as? NSNumber
        let sameFile = outputFile != nil
            && outputFile == referenceAttributes?[.systemFileNumber] as? NSNumber
            && outputAttributes?[.systemNumber] as? NSNumber == referenceAttributes?[.systemNumber] as? NSNumber
        guard outputURL != referenceURL, !sameFile else {
            throw CLIError(
                .invalidInput, "the output must not replace the clone reference audio",
                hint: "choose a different --out"
            )
        }
    }

    /// Runs `plan` with its segments, joined output and manifest in `directory`,
    /// a folder the caller created for this attempt (`makeProjectFolder`).
    /// `projectIndex` tags events when one batch runs several projects. The caller
    /// moves the joined output into place and publishes it (`output_published`).
    @MainActor
    public static func run(
        _ plan: LongFormPlan, mode: GenerationMode, modelID: String, runtime: CLIRuntime,
        payload: GenerationRequest.Payload, deliveryInstructionCellID: String?, variation: Qwen3SamplingVariation?,
        languageHint: String?, directory: URL, projectIndex: Int = 0, projectCount: Int = 1
    ) async -> Outcome {
        var outcome = Outcome(baseSeed: plan.configuration.baseSeed, planDigest: plan.evidence.planDigest)
        guard let host = runtime.host else {
            outcome.stop = .failed(
                CLIError(.internalError, "a long-form project needs the hosted engine"), code: .internalError,
                cancellationRequested: false
            )
            return outcome
        }
        let submissions = Submissions()
        let result = await host.runLongForm(
            DesktopLongFormRequest(
                mode: mode, modelID: modelID, plan: plan, payload: payload,
                deliveryInstructionCellID: deliveryInstructionCellID, languageHint: languageHint,
                variation: variation, directory: directory
            ),
            defaultSpeakerID: runtime.defaultSpeakerID
        ) { event in
            switch event {
            case .segmentStarted(let index, let total, let generationID):
                submissions.last = generationID
                noteVerbose("project \(projectIndex + 1)/\(projectCount), segment \(index + 1)/\(total)")
                CLIPresenter.event(.generationStarted, generationID: generationID, data: [
                    "index": .integer(projectIndex), "segment": .integer(index), "segments": .integer(total),
                    "mode": .string(mode.rawValue), "modelID": .string(modelID),
                ])
            case .segmentSaved(let index, let generationID, let durationSeconds):
                CLIPresenter.event(.generationCompleted, generationID: generationID, data: [
                    "index": .integer(projectIndex), "segment": .integer(index),
                    "durationSeconds": durationSeconds.map { .number($0) } ?? .null,
                ])
            case .segmentFailed(let index, let generationID, let qcRejected):
                CLIPresenter.event(.generationFailed, generationID: generationID, data: [
                    "index": .integer(projectIndex), "segment": .integer(index),
                    "code": qcRejected ? .string(VocelloErrorCode.qcRejected.rawValue) : .null,
                ])
            case .segmentCancelled(let index, let generationID):
                CLIPresenter.event(.generationCancelled, generationID: generationID, data: [
                    "index": .integer(projectIndex), "segment": .integer(index),
                ])
            }
        }
        return report(result, into: outcome, lastSubmitted: submissions.last, signalled: Task.isCancelled)
    }

    /// The take the runner submitted last.
    @MainActor
    private final class Submissions {
        var last: UUID?
    }

    /// The runner's outcome as the CLI reports it. `signalled`: whether a signal
    /// cancelled the command, the one thing that tells an interrupt from the
    /// engine's own stop (the runner ends both as cancelled).
    static func report(
        _ result: DesktopLongFormOutcome, into outcome: Outcome, lastSubmitted: UUID?, signalled: Bool
    ) -> Outcome {
        var outcome = outcome
        outcome.language = result.languageHint
        outcome.segments = result.segments.compactMap { segment in
            guard segment.status == .saved, let audioPath = segment.audioPath, let generationID = segment.generationID
            else { return nil }
            return Segment(
                index: segment.index, segmentID: segment.segmentID, boundary: segment.boundary,
                intendedPauseMilliseconds: segment.intendedPauseMilliseconds, effectiveSeed: String(segment.seed),
                generationID: generationID.uuidString.lowercased(), audioPath: audioPath,
                durationSeconds: segment.durationSeconds ?? 0, finishReason: segment.finishReason,
                qcWarnings: segment.qcWarnings
            )
        }
        let failing = result.segments.first { $0.status == .failed }
        outcome.generationID = failing?.generationID ?? lastSubmitted
        switch result.status {
        case .completed:
            // A truncated middle segment is the project's finish reason, never hidden behind the last one's eos.
            let truncated = outcome.segments.contains { $0.finishReason == GenerationFinishReason.maxTokens.rawValue }
            outcome.finishReason = truncated ? GenerationFinishReason.maxTokens.rawValue : outcome.segments.last?.finishReason
            outcome.audioPath = result.joinedPath
            outcome.durationSeconds = result.durationSeconds
            outcome.manifestPath = result.manifestPath
            outcome.assembly = result.assembly
        case .cancelled:
            outcome.stop = signalled ? .cancelled : .engine(CLIEngineCancellation(reason: .memoryPressure))
        case .failed:
            let (code, detail) = classify(result.failure, failing: failing)
            // The join, not a take, failed: no take is named.
            if result.failure == .joinedQCRejected || result.failure == .assembly { outcome.generationID = nil }
            outcome.stop = .failed(
                CLIError(code, result.message ?? "the long-form project failed", detail: detail),
                code: code, cancellationRequested: signalled
            )
        }
        return outcome
    }

    /// The contract code and detail of a failed project.
    static func classify(
        _ failure: DesktopLongFormOutcome.Failure?, failing: DesktopLongFormSegment?
    ) -> (VocelloErrorCode, [String: CLIJSONValue]?) {
        let segmentDetail: [String: CLIJSONValue]? = failing.map { segment in
            [
                "segment": .integer(segment.index),
                "qcRequiredFailures": .array(segment.qcRequiredFailures.map { .string($0) }),
            ]
        }
        switch failure {
        case .segmentQCRejected?:
            return (.qcRejected, segmentDetail)
        case .joinedQCRejected?:
            return (.qcRejected, ["stage": .string("joined")])
        case .generation(let reason)?:
            return (reason.map(CLIFailure.code(for:)) ?? .generationFailed, segmentDetail)
        case .assembly?:
            return (.assemblyFailed, nil)
        case .other?, nil:
            return (.generationFailed, segmentDetail)
        }
    }
}
