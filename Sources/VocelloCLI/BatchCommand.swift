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
    typealias LongFormSegmentJSON = CLILongFormProject.Segment
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
        /// The language every segment carried: Auto resolved over the project's script.
        let longFormLanguage: String?
        /// The manifest v4 in the project's `_segments` folder.
        let longFormManifestPath: String?
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
        var longFormLanguage: String?
        var longFormManifestPath: String?
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
            dataDirectory: dataDir, manifestOverride: manifestOverride, voiceCloningConsent: consent,
            hostedLikeTheApp: true, concurrency: CLIEngineConcurrency(args))
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
            CLIBatchExecution.reportRow(row, generationID: requests[index].generationID)
            if row.status == .completed {
                CLIPresenter.event(.progress, data: ["items": .integer(requests.count), "finished": .integer(index + 1)])
            }
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

    /// `--long-form`: each line is one long-form project, run by the apps' own
    /// long-form runner (`CLILongFormProject`): the shipping planner splits the
    /// line (base seed `--seed` for every project, else a random one per project
    /// as the apps draw; each segment samples with its derived subseed), Auto
    /// resolves one language over the line, each segment is one streaming take
    /// at the app cadence that must pass the engine's and the apps' QC, and the
    /// joined output must pass the apps' QC too. Segments and the manifest v4
    /// stay in `<project>_segments/`; the joined output is `<project>.wav`.
    /// Custom segments are uninstructed unless --delivery or --app-delivery
    /// names a delivery; a Design project without one gets the Neutral delivery,
    /// as the apps' runner sends it. No History rows until RF-30. Every project
    /// is planned before any model work; the batch stops at its first failed
    /// project, keeping the completed ones.
    @MainActor
    private static func runLongForm(
        args: Args, lines: [String], mode: GenerationMode, modelID: String, quality: Bool,
        runtime: CLIRuntime, payload: GenerationRequest.Payload, deliveryInstructionCellID: String?,
        outDir: URL, filenamePrefix: String, seed: UInt64?, variation: Qwen3SamplingVariation?
    ) async throws {
        var plans: [LongFormPlan] = []
        for (lineIndex, line) in lines.enumerated() {
            do {
                plans.append(try CLILongFormProject.plan(line, seed: seed))
            } catch let refusal as CLIError {
                // The planner's errors carry no text, so the line number says which project failed.
                throw CLIError(
                    refusal.code, "line \(lineIndex + 1): \(refusal.description)", hint: refusal.hint, detail: refusal.detail
                )
            }
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
            let projectFolder: URL
            do {
                projectFolder = try CLILongFormProject.makeProjectFolder(
                    beside: outDir.appendingPathComponent("\(name).wav"), attempt: UUID()
                )
            } catch {
                rows[index].status = .failed
                rows[index].errorCode = VocelloErrorCode.outputUnavailable.rawValue
                stopped = true
                break projects
            }
            let outcome = await CLILongFormProject.run(
                plan, mode: mode, modelID: modelID, runtime: runtime, payload: payload,
                deliveryInstructionCellID: deliveryInstructionCellID, variation: variation,
                // Batch has no --language: Auto, resolved over each project's script as the apps do.
                languageHint: nil, directory: projectFolder,
                projectIndex: index, projectCount: plans.count
            )
            rows[index].longFormBaseSeed = String(outcome.baseSeed)
            rows[index].longFormPlanDigest = outcome.planDigest
            rows[index].generationID = outcome.generationID
            // A stopped project keeps the segment takes it completed.
            if !outcome.segments.isEmpty { rows[index].longFormSegments = outcome.segments }
            if outcome.stop != nil, outcome.segments.isEmpty {
                // Nothing this attempt made is worth keeping.
                try? FileManager.default.removeItem(at: projectFolder)
            }
            switch outcome.stop {
            case .failed(_, let code, let cancellationRequested)?:
                rows[index].status = .failed
                rows[index].errorCode = code.rawValue
                if cancellationRequested { rows[index].cancellationRequested = true }
                stopped = true
                break projects
            case .cancelled?:
                rows[index].status = .cancelled
                rows[index].errorCode = "cancelled"
                cancelled = true
                stopped = true
                break projects
            case .engine(let engineStop)?:
                // The engine stopped the segment on its own (P15-02): a failure, not an interrupt.
                rows[index].status = .failed
                rows[index].errorCode = engineStop.errorCode
                engineCancellation = engineStop
                stopped = true
                break projects
            case nil:
                break
            }
            guard let duration = outcome.durationSeconds, let assembly = outcome.assembly else {
                throw CLIError(.internalError, "a completed long-form project has no joined output")
            }
            let joinedPath = outDir.appendingPathComponent("\(name).wav").path
            do {
                try CLILongFormProject.publishJoined(
                    outcome, to: URL(fileURLWithPath: joinedPath), signalled: Task.isCancelled
                )
            } catch {
                rows[index].generationID = nil
                if error is CancellationError {
                    rows[index].status = .cancelled
                    rows[index].errorCode = "cancelled"
                    cancelled = true
                } else {
                    rows[index].status = .failed
                    rows[index].errorCode = VocelloErrorCode.outputUnavailable.rawValue
                }
                stopped = true
                break projects
            }
            rows[index].longFormManifestPath = outcome.manifestPath
            rows[index].longFormLanguage = outcome.language
            rows[index].status = .completed
            CLIPresenter.event(.outputPublished, data: ["index": .integer(index), "audioPath": .string(joinedPath)])
            rows[index].audioPath = joinedPath
            rows[index].durationSeconds = duration
            rows[index].finishReason = outcome.finishReason
            rows[index].longFormAssembly = assembly
            items.append(LongFormItemJSON(
                index: index, text: lines[index], audioPath: joinedPath, durationSeconds: duration,
                finishReason: outcome.finishReason, longFormBaseSeed: String(outcome.baseSeed),
                longFormPlanDigest: outcome.planDigest, longFormSegments: outcome.segments,
                longFormAssembly: assembly, longFormLanguage: outcome.language,
                longFormManifestPath: outcome.manifestPath
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
