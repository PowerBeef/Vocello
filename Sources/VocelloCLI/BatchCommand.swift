import Foundation
import QwenVoiceCore
import VocelloCLICore
import VocelloDesktopCore

/// `vocello batch` — synthesize many clips that share one voice/mode/variant,
/// reusing one process and loaded model with per-item terminal receipts. The headline
/// throughput win over repeated `generate` calls (which reboot + reload the model
/// every time).
enum BatchCommand {
    struct ItemJSON: Encodable, Sendable {
        let index: Int
        let text: String
        let audioPath: String
        let durationSeconds: Double
        let finishReason: String?
    }
    struct BatchJSON: Encodable, Sendable {
        let mode: String
        let variant: String
        let modelID: String
        let count: Int
        let wallSeconds: Double
        let items: [ItemJSON]
    }
    struct FailedBatchJSON: Encodable, Sendable {
        let schemaVersion = 2
        let mode: String
        let variant: String
        let modelID: String
        let plannedCount: Int
        let completedCount: Int
        let wallSeconds: Double
        let items: [CLIBatchExecution.Row]
    }

    // MARK: - Long-form projects (`--long-form`)

    /// One planned segment of a long-form project and the engine's take of it.
    /// No text: the project's line is the item's. `index` counts from 0.
    struct LongFormSegmentJSON: Encodable, Sendable {
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
    struct LongFormItemJSON: Encodable, Sendable {
        let index: Int
        let text: String
        let audioPath: String
        let durationSeconds: Double
        let finishReason: String?
        let longFormBaseSeed: String
        let longFormPlanDigest: String
        let longFormSegments: [LongFormSegmentJSON]
        let longFormAssembly: LongFormAssemblyEvidence
    }
    struct LongFormBatchJSON: Encodable, Sendable {
        let longForm = true
        let mode: String
        let variant: String
        let modelID: String
        let count: Int
        let wallSeconds: Double
        let items: [LongFormItemJSON]
    }
    /// A project's terminal row: `generationID` names the segment take that
    /// failed (or the last one), so the engine's recorded failure binds to it;
    /// it is nil when the join, not a take, failed or was cancelled, and unset
    /// when the project stopped before its first take was submitted. A stopped
    /// project keeps the segment takes it completed.
    struct LongFormRow: Encodable, Sendable {
        let index: Int
        var generationID: UUID?
        var status: CLIBatchExecution.Status = .notAttempted
        var audioPath: String?
        var durationSeconds: Double?
        var finishReason: String?
        var errorCode: String?
        var cancellationRequested: Bool?
        var longFormBaseSeed: String?
        var longFormPlanDigest: String?
        var longFormSegments: [LongFormSegmentJSON]?
        var longFormAssembly: LongFormAssemblyEvidence?
    }
    struct FailedLongFormBatchJSON: Encodable, Sendable {
        let schemaVersion = 2
        let longForm = true
        let mode: String
        let variant: String
        let modelID: String
        let plannedCount: Int
        let completedCount: Int
        let wallSeconds: Double
        let items: [LongFormRow]
    }

    @MainActor
    static func run(_ args: Args) async throws {
        // The parser refuses --language, --stream and --out (batch uses per-text
        // Auto language and non-streaming output) and a value on a bare flag.
        let appDelivery = try GenerateCommand.parseAppDelivery(args)
        let captureCodecTrace = args.flag("capture-codec-trace")
        if captureCodecTrace {
            // The engine persists each take's trace only for a registered run
            // identity with telemetry on; refuse rather than silently keep none.
            guard RuntimeDebugGate.isEnabled(), TelemetryGate.resolvedEnabled else {
                throw CLIError(
                    .usageError,
                    "--capture-codec-trace requires an internal-diagnostics build, QWENVOICE_DEBUG=1 "
                        + "and telemetry that is not explicitly off."
                )
            }
            guard StartupReliabilityDiagnosticEvidence.captureRunID(
                environment: ProcessInfo.processInfo.environment,
                telemetryEnabled: TelemetryGate.resolvedEnabled
            ) != nil else {
                throw CLIError(.usageError, "--capture-codec-trace requires a registered bench run id (QVOICE_MAC_BENCH_RUN_ID).")
            }
            guard !args.flag("long-form") else {
                throw CLIError(.usageError, "--capture-codec-trace applies to short-form batches only (not --long-form)")
            }
        }

        let mode = try GenerateCommand.resolveMode(args)
        let explicitQuality = try GenerateCommand.parseVariantFlag(args)
        // PA-17: clone needs this invocation's recorded consent; refuse before boot.
        let consent = try CLIVoiceCloningConsent.policy(from: args)
        try consent.admitGeneration(mode: mode)
        try GenerateCommand.validatePayloadOptions(args, mode: mode)

        let lines = try readLines(args)
        guard !lines.isEmpty else {
            throw CLIError(.usageError, "no input lines — pass --file <path> (one clip per line), or --file - to read stdin")
        }
        // A short-form line is one take: the same single-take rule as
        // `generate`, checked for every line before the engine boots, so a
        // line with nothing to speak or past the budget never stops the batch
        // partway (U01, U29). A long-form line is a project the planner splits.
        if !args.flag("long-form") {
            try CLIBatchExecution.validateShortFormLines(lines)
        }

        let dataDir = CLIPaths.dataDirectory(override: args.string("data-dir"))
        let manifestOverride = args.string("manifest").map { URL(fileURLWithPath: ($0 as NSString).expandingTildeInPath) }

        note("booting engine (data: \(dataDir.path))")
        CLIPresenter.event(.engineBooting)
        let runtime = try await CLIRuntime.bootstrap(
            dataDirectory: dataDir, manifestOverride: manifestOverride, voiceCloningConsent: consent)
        CLIPresenter.event(.engineReady)
        let settings = DesktopAppSettings()
        let quality = GenerateCommand.resolveVariant(
            explicitQuality: explicitQuality, mode: mode, registry: runtime.registry,
            modelsDirectory: dataDir.appendingPathComponent("models", isDirectory: true), settings: settings
        ).quality
        let modelID = try runtime.modelID(mode: mode, quality: quality)
        // One shared payload keeps the loaded model/session reusable while the
        // command owns each item's result, cancellation, and retained receipt.
        let built = try await GenerateCommand.buildPayload(args, mode: mode, runtime: runtime)
        let payload = appDelivery ? CLIBatchExecution.applyingAppDefaultDelivery(to: built) : built
        let deliveryInstructionCellID = try GenerateCommand.resolveDeliveryInstructionCellID(
            args,
            mode: mode
        )

        let outDir = resolveOutDir(args, dataDir: dataDir)
        try FileManager.default.createDirectory(at: outDir, withIntermediateDirectories: true)

        let fmt = DateFormatter()
        fmt.dateFormat = "yyyyMMdd_HHmmss"
        fmt.locale = Locale(identifier: "en_US_POSIX")
        let stamp = fmt.string(from: Date()) + "_" + UUID().uuidString.lowercased()

        // --seed applies the SAME seed to every item: each item's sampling
        // stream is then deterministic for its text, and re-running the batch
        // reproduces it (community testing also reports a fixed seed reduces
        // cross-segment timbre drift; GitHub #30/#47).
        let seed = try GenerateCommand.parseSeed(args)
        let variation = try GenerateCommand.parseVariation(args) ?? GenerateCommand.appVariation(settings)
        if args.flag("long-form") {
            try await runLongForm(
                args: args, lines: lines, mode: mode, modelID: modelID, quality: quality,
                runtime: runtime, payload: payload, deliveryInstructionCellID: deliveryInstructionCellID,
                outDir: outDir, filenamePrefix: stamp, seed: seed, variation: variation
            )
            return
        }
        let requests = CLIBatchExecution.makeRequests(
            lines: lines, mode: mode, modelID: modelID, outputDirectory: outDir,
            filenamePrefix: stamp, payload: payload, seed: seed, variation: variation,
            deliveryInstructionCellID: deliveryInstructionCellID, captureCodecTrace: captureCodecTrace
        )

        note("loading \(modelID)…")
        note("generating \(requests.count) clip(s), one model load…")
        let wallStart = ContinuousClock.now
        let outcome = await CLIBatchExecution.run(requests, progress: { index, total in
            noteVerbose("item \(index + 1)/\(total)")
            CLIPresenter.event(.generationStarted, generationID: requests[index].generationID, data: [
                "index": .integer(index), "total": .integer(total), "mode": .string(mode.rawValue),
                "modelID": .string(modelID),
            ])
        }, finished: { index, row in
            Self.reportRow(row, generationID: requests[index].generationID)
        }) { request in
            return try await runtime.generate(request)
        }
        let results = outcome.results
        let wall = wallStart.elapsedSeconds
        if !outcome.passed {
            if CLIPresenter.isMachine {
                CLIPresenter.recordPartialResult(FailedBatchJSON(mode: mode.rawValue, variant: quality ? "quality" : "speed",
                    modelID: modelID, plannedCount: requests.count, completedCount: results.count,
                    wallSeconds: wall, items: outcome.rows))
            } else {
                for result in results { print(result.audioPath) }
                for row in outcome.rows {
                    let code = row.status == .failed ? row.errorCode.map { " (\($0))" } ?? "" : ""
                    let signalled = row.cancellationRequested == true ? " (cancellation requested)" : ""
                    note("item \(row.index): \(row.status.rawValue)\(code)\(signalled)")
                }
            }
            if outcome.cancelled { throw CancellationError() }
            if let engineCancellation = outcome.engineCancellation { throw engineCancellation }
            throw CLIError(
                .batchIncomplete, "batch stopped; completed outputs retained, remaining rows not attempted",
                detail: ["completedCount": .integer(results.count), "plannedCount": .integer(requests.count)]
            )
        }

        var machineResult: BatchJSON?
        if CLIPresenter.isMachine {
            let items = (0..<results.count).map { i in
                ItemJSON(index: i, text: lines[i], audioPath: results[i].audioPath,
                         durationSeconds: results[i].durationSeconds,
                         finishReason: results[i].finishReason?.rawValue)
            }
            machineResult = BatchJSON(mode: mode.rawValue, variant: quality ? "quality" : "speed",
                                      modelID: modelID, count: results.count, wallSeconds: wall, items: items)
        } else {
            for r in results { print(r.audioPath) }
        }
        let totalAudio = results.reduce(0.0) { $0 + $1.durationSeconds }
        note(unsafe "✓ \(results.count) clip(s) · \(String(format: "%.1f", totalAudio))s audio in \(String(format: "%.1f", wall))s")

        if args.flag("play") { try await CLIPlayback.play(results.map(\.audioPath)) }
        if let machineResult { CLIPresenter.succeed(machineResult) }
    }

    /// The apps refuse a long-form plan of more segments (`IOSLongFormCoordinator.maxSegments`).
    static let longFormMaximumSegments = CLILimits.longFormMaximumSegments

    /// A batch row's terminal event (ndjson only).
    static func reportRow(_ row: CLIBatchExecution.Row, generationID: UUID?) {
        switch row.status {
        case .completed:
            if let path = row.audioPath {
                CLIPresenter.event(.outputPublished, generationID: generationID, data: ["audioPath": .string(path)])
            }
            CLIPresenter.event(.generationCompleted, generationID: generationID, data: [
                "index": .integer(row.index),
                "durationSeconds": row.durationSeconds.map { .number($0) } ?? .null,
            ])
        case .failed:
            CLIPresenter.event(.generationFailed, generationID: generationID, data: [
                "index": .integer(row.index), "code": row.errorCode.map { .string($0) } ?? .null,
            ])
        case .cancelled:
            CLIPresenter.event(.generationCancelled, generationID: generationID, data: ["index": .integer(row.index)])
        case .notAttempted:
            break
        }
    }

    /// `--long-form`: each line is one long-form project, run the way the apps'
    /// long-form runner runs one (`IOSLongFormProjectRequest`): the shipping
    /// planner splits the line (base seed `--seed` for every project, else a
    /// random one per project as the apps draw; each segment samples with its
    /// derived subseed), each segment is one streaming take at the app cadence,
    /// and the bounded assembler joins them. The apps' runner sends the Neutral
    /// delivery instruction when nobody styled the draft: pass --app-delivery
    /// for that (without it the segments are uninstructed, like any programmatic
    /// request). Only the engine's own Fast QC runs,
    /// per segment: the apps' joined-output quality gate, manifest and History
    /// acceptance are not part of it. Every project is planned before any model
    /// work; the batch stops at its first failed segment, keeping the completed
    /// projects.
    @MainActor
    private static func runLongForm(
        args: Args, lines: [String], mode: GenerationMode, modelID: String, quality: Bool,
        runtime: CLIRuntime, payload: GenerationRequest.Payload, deliveryInstructionCellID: String?,
        outDir: URL, filenamePrefix: String, seed: UInt64?, variation: Qwen3SamplingVariation?
    ) async throws {
        var plans: [LongFormPlan] = []
        for (lineIndex, line) in lines.enumerated() {
            let plan: LongFormPlan
            do {
                let spokenPlan = try SpokenTextPlanner.plan(originalText: line)
                plan = try LongFormPlanner.plan(
                    spokenTextPlan: spokenPlan,
                    configuration: LongFormPlanningConfiguration(
                        runtimeTokenLimit: LongFormPlanningConfiguration.shippingRuntimeTokenLimit,
                        baseSeed: seed ?? UInt64.random(in: UInt64.min ... UInt64.max)
                    )
                )
            } catch {
                // The planner's errors carry no text, so the line number says which project failed.
                throw CLIError(.invalidInput, "line \(lineIndex + 1): the long-form planner refused the project (\(error))")
            }
            guard plan.segments.count <= longFormMaximumSegments else {
                throw CLIError(
                    .textTooLong,
                    "line \(lineIndex + 1): the project plans \(plan.segments.count) segments, "
                        + "more than the \(longFormMaximumSegments) the apps accept"
                )
            }
            plans.append(plan)
        }
        let segmentCount = plans.reduce(0) { $0 + $1.segments.count }
        note("loading \(modelID)…")
        note("generating \(plans.count) long-form project(s), \(segmentCount) segment(s), one model load…")
        var rows = plans.indices.map { LongFormRow(index: $0) }
        var items: [LongFormItemJSON] = []
        var stopped = false
        var cancelled = false
        var engineCancellation: CLIEngineCancellation?
        let started = ContinuousClock.now
        projects: for (index, plan) in plans.enumerated() {
            let name = unsafe "\(filenamePrefix)_\(mode.rawValue)_\(String(format: "%03d", index))"
            let joinedURL = outDir.appendingPathComponent("\(name).wav")
            rows[index].longFormBaseSeed = String(plan.configuration.baseSeed)
            rows[index].longFormPlanDigest = plan.evidence.planDigest
            var segments: [LongFormSegmentJSON] = []
            var sources: [LongFormAssemblySegmentSource] = []
            // The planner numbers its segments from 1 (`evidence.index`); the JSON counts from 0.
            for (position, segment) in plan.segments.enumerated() {
                let generationID = UUID()
                let request = CLIBatchExecution.makeLongFormSegmentRequest(
                    mode: mode, modelID: modelID, text: segment.spokenTextForGeneration,
                    outputPath: outDir.appendingPathComponent(
                        unsafe "\(name)_segment_\(String(format: "%03d", position)).wav"
                    ).path,
                    payload: payload, generationID: generationID, subseed: segment.evidence.effectiveSubseed,
                    variation: variation, deliveryInstructionCellID: deliveryInstructionCellID
                )
                do {
                    try Task.checkCancellation()
                    // Named once submitted: a project cancelled first names no take the engine never saw.
                    rows[index].generationID = generationID
                    noteVerbose("project \(index + 1)/\(plans.count), segment \(position + 1)/\(plan.segments.count)")
                    CLIPresenter.event(.generationStarted, generationID: generationID, data: [
                        "index": .integer(index), "segment": .integer(position),
                        "segments": .integer(plan.segments.count), "mode": .string(mode.rawValue),
                        "modelID": .string(modelID),
                    ])
                    let (result, _, _, _) = try await GenerateCommand.generateObservingFirstChunk(runtime, request)
                    guard FileManager.default.fileExists(atPath: result.audioPath) else {
                        rows[index].status = .failed
                        rows[index].errorCode = VocelloErrorCode.outputMissing.rawValue
                        if Task.isCancelled { rows[index].cancellationRequested = true }
                        stopped = true
                        break projects
                    }
                    segments.append(LongFormSegmentJSON(
                        index: position, segmentID: segment.segmentID,
                        boundary: segment.evidence.boundary.rawValue,
                        intendedPauseMilliseconds: segment.evidence.intendedPauseMilliseconds,
                        effectiveSeed: String(segment.evidence.effectiveSubseed),
                        generationID: generationID.uuidString, audioPath: result.audioPath,
                        durationSeconds: result.durationSeconds, finishReason: result.finishReason?.rawValue
                    ))
                    // A stopped project keeps the segment takes it completed.
                    rows[index].longFormSegments = segments
                    CLIPresenter.event(.generationCompleted, generationID: generationID, data: [
                        "index": .integer(index), "segment": .integer(position),
                        "durationSeconds": .number(result.durationSeconds),
                    ])
                    sources.append(LongFormAssemblySegmentSource(
                        segmentID: segment.segmentID, lineage: segment.evidence.lineage,
                        audioURL: URL(fileURLWithPath: result.audioPath), boundary: segment.evidence.boundary,
                        intendedPauseMilliseconds: segment.evidence.intendedPauseMilliseconds
                    ))
                } catch let engineStop as CLIEngineCancellation {
                    // The engine stopped the segment on its own (P15-02): a failure, not an interrupt.
                    rows[index].status = .failed
                    rows[index].errorCode = engineStop.errorCode
                    engineCancellation = engineStop
                    stopped = true
                    break projects
                } catch is CancellationError {
                    rows[index].status = .cancelled
                    rows[index].errorCode = "cancelled"
                    cancelled = true
                    stopped = true
                    break projects
                } catch {
                    // Typed: a genuine failure that coincides with a signal stays failed.
                    rows[index].status = .failed
                    rows[index].errorCode = CLIFailure.rowCode(for: error).rawValue
                    if Task.isCancelled { rows[index].cancellationRequested = true }
                    stopped = true
                    break projects
                }
            }
            let assembly: LongFormAssemblyEvidence
            do {
                assembly = try await BoundedLongFormAssembler.assemble(
                    segments: sources,
                    outputURL: joinedURL,
                    provenanceModelID: modelID,
                    provenanceMode: mode.rawValue
                )
            } catch is CancellationError {
                // The segments were generated: the stop is the join's, not a generation's.
                try? FileManager.default.removeItem(at: joinedURL)
                rows[index].generationID = nil
                rows[index].status = .cancelled
                rows[index].errorCode = "cancelled"
                cancelled = true
                stopped = true
                break projects
            } catch {
                // The assembler can publish and then fail its read-back; the apps remove that file too.
                try? FileManager.default.removeItem(at: joinedURL)
                rows[index].generationID = nil
                rows[index].status = .failed
                rows[index].errorCode = VocelloErrorCode.assemblyFailed.rawValue
                if Task.isCancelled { rows[index].cancellationRequested = true }
                stopped = true
                break projects
            }
            let joinedPath = joinedURL.path
            let duration = Double(assembly.outputFrameCount) / Double(assembly.sampleRate)
            // A truncated middle segment is the project's finish reason, never hidden behind the last one's eos.
            let truncated = segments.contains { $0.finishReason == GenerationFinishReason.maxTokens.rawValue }
            let finishReason = truncated ? GenerationFinishReason.maxTokens.rawValue : segments.last?.finishReason
            rows[index].status = .completed
            CLIPresenter.event(.outputPublished, data: ["index": .integer(index), "audioPath": .string(joinedPath)])
            rows[index].audioPath = joinedPath
            rows[index].durationSeconds = duration
            rows[index].finishReason = finishReason
            rows[index].longFormAssembly = assembly
            items.append(LongFormItemJSON(
                index: index, text: lines[index], audioPath: joinedPath, durationSeconds: duration,
                finishReason: finishReason, longFormBaseSeed: String(plan.configuration.baseSeed),
                longFormPlanDigest: plan.evidence.planDigest, longFormSegments: segments,
                longFormAssembly: assembly
            ))
        }
        let wall = started.elapsedSeconds
        let variant = quality ? "quality" : "speed"
        if stopped {
            if CLIPresenter.isMachine {
                CLIPresenter.recordPartialResult(FailedLongFormBatchJSON(
                    mode: mode.rawValue, variant: variant, modelID: modelID, plannedCount: plans.count,
                    completedCount: items.count, wallSeconds: wall, items: rows
                ))
            } else {
                for item in items { print(item.audioPath) }
                for row in rows where row.status != .completed {
                    let code = row.status == .failed ? row.errorCode.map { " (\($0))" } ?? "" : ""
                    let signalled = row.cancellationRequested == true ? " (cancellation requested)" : ""
                    note("project \(row.index): \(row.status.rawValue)\(code)\(signalled)")
                }
            }
            if cancelled { throw CancellationError() }
            if let engineCancellation { throw engineCancellation }
            throw CLIError(
                .batchIncomplete, "long-form batch stopped; completed projects retained, remaining projects not attempted",
                detail: ["completedCount": .integer(items.count), "plannedCount": .integer(plans.count)]
            )
        }
        var machineResult: LongFormBatchJSON?
        if CLIPresenter.isMachine {
            machineResult = LongFormBatchJSON(
                mode: mode.rawValue, variant: variant, modelID: modelID, count: items.count,
                wallSeconds: wall, items: items
            )
        } else {
            for item in items { print(item.audioPath) }
        }
        let totalAudio = items.reduce(0.0) { $0 + $1.durationSeconds }
        note(unsafe "✓ \(items.count) long-form project(s), \(segmentCount) segment(s) · \(String(format: "%.1f", totalAudio))s audio in \(String(format: "%.1f", wall))s")

        if args.flag("play") { try await CLIPlayback.play(items.map(\.audioPath)) }
        if let machineResult { CLIPresenter.succeed(machineResult) }
    }

    private static func readLines(_ args: Args) throws -> [String] {
        let raw: String
        if let f = args.string("file") {
            if f == "-" { raw = readStdinText() ?? "" }
            else {
                let path = (f as NSString).expandingTildeInPath
                do { raw = try String(contentsOfFile: path, encoding: .utf8) }
                catch {
                    let code: VocelloErrorCode = FileManager.default.fileExists(atPath: path) ? .ioError : .inputFileNotFound
                    throw CLIError(code, "could not read --file \(path): \(error.localizedDescription)")
                }
            }
        } else {
            raw = readImplicitStdinText() ?? ""
        }
        return raw.split(whereSeparator: { $0.isNewline })
            .map { $0.trimmingCharacters(in: .whitespaces) }
            .filter { !$0.isEmpty }
    }

    private static func resolveOutDir(_ args: Args, dataDir: URL) -> URL {
        if let d = args.string("out-dir") {
            return URL(fileURLWithPath: (d as NSString).expandingTildeInPath, isDirectory: true)
        }
        return dataDir.appendingPathComponent("outputs/cli/batch", isDirectory: true)
    }
}
