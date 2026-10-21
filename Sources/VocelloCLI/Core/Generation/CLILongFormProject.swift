import Foundation
import QwenVoiceCore

/// One long-form project, run the way the apps' long-form runner runs one
/// (`IOSLongFormProjectRequest`): the shipping planner splits the script (base
/// seed given or drawn at random, each segment sampling with its derived
/// subseed), each segment is one streaming take at the app cadence, and the
/// bounded assembler joins them. Shared by `batch --long-form` (a project per
/// line) and `generate` (a script past one take). Only the engine's own Fast QC
/// runs, per segment; the apps' joined-output gate, manifest and History
/// acceptance are not part of it.
public enum CLILongFormProject {
    /// One planned segment and the engine's take of it. No text: the project's is the item's.
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
    }

    /// Why a project stopped before its joined output.
    public enum Stop: Sendable {
        /// A segment or the join failed with `error` (its row code `code`),
        /// possibly while a signal arrived.
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
        public internal(set) var assembly: LongFormAssemblyEvidence?
        public internal(set) var audioPath: String?
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

    /// Runs `plan` and joins it into `joinedURL`; segment takes land at `segmentURL(position)`.
    /// `projectIndex` tags events when one batch runs several projects. The caller
    /// publishes the joined output (`output_published`).
    @MainActor
    public static func run(
        _ plan: LongFormPlan, mode: GenerationMode, modelID: String, runtime: CLIRuntime,
        payload: GenerationRequest.Payload, deliveryInstructionCellID: String?, variation: Qwen3SamplingVariation?,
        joinedURL: URL, segmentURL: (Int) -> URL, projectIndex: Int = 0, projectCount: Int = 1
    ) async -> Outcome {
        var outcome = Outcome(baseSeed: plan.configuration.baseSeed, planDigest: plan.evidence.planDigest)
        var sources: [LongFormAssemblySegmentSource] = []
        // The planner numbers its segments from 1 (`evidence.index`); the JSON counts from 0.
        for (position, segment) in plan.segments.enumerated() {
            let generationID = UUID()
            let request = CLIBatchExecution.makeLongFormSegmentRequest(
                mode: mode, modelID: modelID, text: segment.spokenTextForGeneration,
                outputPath: segmentURL(position).path,
                payload: payload, generationID: generationID, subseed: segment.evidence.effectiveSubseed,
                variation: variation, deliveryInstructionCellID: deliveryInstructionCellID
            )
            do {
                try Task.checkCancellation()
                // Named once submitted: a project cancelled first names no take the engine never saw.
                outcome.generationID = generationID
                noteVerbose("project \(projectIndex + 1)/\(projectCount), segment \(position + 1)/\(plan.segments.count)")
                CLIPresenter.event(.generationStarted, generationID: generationID, data: [
                    "index": .integer(projectIndex), "segment": .integer(position),
                    "segments": .integer(plan.segments.count), "mode": .string(mode.rawValue),
                    "modelID": .string(modelID),
                ])
                let (result, _, _, _) = try await GenerateCommand.generateObservingFirstChunk(runtime, request)
                guard FileManager.default.fileExists(atPath: result.audioPath) else {
                    outcome.stop = .failed(
                        CLIError(
                            .outputMissing,
                            "engine reported success but no audio file exists for segment \(position); refusing to claim success (CM-7 guard)"
                        ),
                        code: .outputMissing, cancellationRequested: Task.isCancelled
                    )
                    return outcome
                }
                outcome.segments.append(Segment(
                    index: position, segmentID: segment.segmentID,
                    boundary: segment.evidence.boundary.rawValue,
                    intendedPauseMilliseconds: segment.evidence.intendedPauseMilliseconds,
                    effectiveSeed: String(segment.evidence.effectiveSubseed),
                    generationID: generationID.uuidString, audioPath: result.audioPath,
                    durationSeconds: result.durationSeconds, finishReason: result.finishReason?.rawValue
                ))
                CLIPresenter.event(.generationCompleted, generationID: generationID, data: [
                    "index": .integer(projectIndex), "segment": .integer(position),
                    "durationSeconds": .number(result.durationSeconds),
                ])
                sources.append(LongFormAssemblySegmentSource(
                    segmentID: segment.segmentID, lineage: segment.evidence.lineage,
                    audioURL: URL(fileURLWithPath: result.audioPath), boundary: segment.evidence.boundary,
                    intendedPauseMilliseconds: segment.evidence.intendedPauseMilliseconds
                ))
            } catch let engineStop as CLIEngineCancellation {
                // The engine stopped the segment on its own (P15-02): a failure, not an interrupt.
                outcome.stop = .engine(engineStop)
                return outcome
            } catch is CancellationError {
                outcome.stop = .cancelled
                return outcome
            } catch {
                // Typed: a genuine failure that coincides with a signal stays failed.
                outcome.stop = .failed(error, code: CLIFailure.rowCode(for: error), cancellationRequested: Task.isCancelled)
                return outcome
            }
        }
        let assembly: LongFormAssemblyEvidence
        do {
            assembly = try await BoundedLongFormAssembler.assemble(
                segments: sources, outputURL: joinedURL, provenanceModelID: modelID, provenanceMode: mode.rawValue
            )
        } catch is CancellationError {
            // The segments were generated: the stop is the join's, not a generation's.
            try? FileManager.default.removeItem(at: joinedURL)
            outcome.generationID = nil
            outcome.stop = .cancelled
            return outcome
        } catch {
            // The assembler can publish and then fail its read-back; the apps remove that file too.
            try? FileManager.default.removeItem(at: joinedURL)
            outcome.generationID = nil
            outcome.stop = .failed(
                CLIError(.assemblyFailed, "the long-form segments could not be joined"),
                code: .assemblyFailed, cancellationRequested: Task.isCancelled
            )
            return outcome
        }
        // A truncated middle segment is the project's finish reason, never hidden behind the last one's eos.
        let truncated = outcome.segments.contains { $0.finishReason == GenerationFinishReason.maxTokens.rawValue }
        outcome.finishReason = truncated ? GenerationFinishReason.maxTokens.rawValue : outcome.segments.last?.finishReason
        outcome.audioPath = joinedURL.path
        outcome.durationSeconds = Double(assembly.outputFrameCount) / Double(assembly.sampleRate)
        outcome.assembly = assembly
        return outcome
    }
}
