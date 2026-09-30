import Foundation
import QwenVoiceCore

/// `vocello batch` — synthesize many clips that share one voice/mode/variant,
/// reusing one process and loaded model with per-item terminal receipts. The headline
/// throughput win over repeated `generate` calls (which reboot + reload the model
/// every time).
enum BatchCommand {
    struct ItemJSON: Encodable {
        let index: Int
        let text: String
        let audioPath: String
        let durationSeconds: Double
        let finishReason: String?
    }
    struct BatchJSON: Encodable {
        let mode: String
        let variant: String
        let modelID: String
        let count: Int
        let wallSeconds: Double
        let items: [ItemJSON]
    }
    struct FailedBatchJSON: Encodable {
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
    struct LongFormSegmentJSON: Encodable {
        let index: Int
        let segmentID: String
        let boundary: String
        let intendedPauseMilliseconds: Int
        let effectiveSeed: UInt64
        let generationID: String
        let audioPath: String
        let durationSeconds: Double
        let finishReason: String?
    }
    struct LongFormItemJSON: Encodable {
        let index: Int
        let text: String
        let audioPath: String
        let durationSeconds: Double
        let finishReason: String?
        let longFormBaseSeed: UInt64
        let longFormPlanDigest: String
        let longFormSegments: [LongFormSegmentJSON]
        let longFormAssembly: LongFormAssemblyEvidence
    }
    struct LongFormBatchJSON: Encodable {
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
    struct LongFormRow: Encodable {
        let index: Int
        var generationID: UUID?
        var status: CLIBatchExecution.Status = .notAttempted
        var audioPath: String?
        var durationSeconds: Double?
        var finishReason: String?
        var errorCode: String?
        var cancellationRequested: Bool?
        var longFormBaseSeed: UInt64?
        var longFormPlanDigest: String?
        var longFormSegments: [LongFormSegmentJSON]?
        var longFormAssembly: LongFormAssemblyEvidence?
    }
    struct FailedLongFormBatchJSON: Encodable {
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
    static func run(_ argv: [String]) async throws {
        let args = Args(argv)
        if args.flag("help") { printHelp(); return }
        CLIOutput.configure(args)
        for flag in ["language", "stream", "out"] where args.string(flag) != nil || args.flag(flag) {
            throw CLIError("--\(flag) is not supported by batch; use generate or omit it. Batch uses per-text Auto language and non-streaming output.")
        }
        if let value = args.string("long-form") {
            // A value would silently fall back to the short-form batch.
            throw CLIError("--long-form takes no value (got \"\(value)\"): pass the bare flag --long-form")
        }
        if let value = args.string("app-delivery") {
            throw CLIError("--app-delivery takes no value (got \"\(value)\"): pass the bare flag --app-delivery")
        }
        if let value = args.string("capture-codec-trace") {
            throw CLIError(
                "--capture-codec-trace takes no value (got \"\(value)\"): pass the bare flag --capture-codec-trace"
            )
        }
        let captureCodecTrace = args.flag("capture-codec-trace")
        if captureCodecTrace {
            // The engine persists each take's trace only for a registered run
            // identity with telemetry on; refuse rather than silently keep none.
            guard RuntimeDebugGate.isEnabled(), TelemetryGate.resolvedEnabled else {
                throw CLIError(
                    "--capture-codec-trace requires an internal-diagnostics build, QWENVOICE_DEBUG=1 "
                        + "and telemetry that is not explicitly off."
                )
            }
            guard !args.flag("long-form") else {
                throw CLIError("--capture-codec-trace applies to short-form batches only (not --long-form)")
            }
        }

        let mode = try GenerateCommand.resolveMode(args)
        let quality = try GenerateCommand.resolveQuality(args)
        // PA-17: clone needs this invocation's recorded consent; refuse before boot.
        let consent = try CLIVoiceCloningConsent.policy(from: args)
        try consent.admitGeneration(mode: mode)

        let lines = try readLines(args)
        guard !lines.isEmpty else {
            throw CLIError("no input lines — pass --file <path> (one clip per line) or pipe text on stdin")
        }

        let dataDir = CLIPaths.dataDirectory(override: args.string("data-dir"))
        let manifestOverride = args.string("manifest").map { URL(fileURLWithPath: ($0 as NSString).expandingTildeInPath) }

        note("booting engine (data: \(dataDir.path))")
        let runtime = try await CLIRuntime.bootstrap(
            dataDirectory: dataDir, manifestOverride: manifestOverride, voiceCloningConsent: consent)
        let modelID = try runtime.modelID(mode: mode, quality: quality)
        // One shared payload keeps the loaded model/session reusable while the
        // command owns each item's result, cancellation, and retained receipt.
        let built = try await GenerateCommand.buildPayload(args, mode: mode, runtime: runtime)
        let payload = args.flag("app-delivery") ? CLIBatchExecution.applyingAppDefaultDelivery(to: built) : built
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
        let variation = try GenerateCommand.parseVariation(args)
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
        let wallStart = Date()
        let outcome = await CLIBatchExecution.run(requests, progress: { index, total in
            noteVerbose("item \(index + 1)/\(total)")
        }) { request in
            return try await runtime.generate(request)
        }
        let results = outcome.results
        let wall = Date().timeIntervalSince(wallStart)
        if !outcome.passed {
            if args.flag("json") {
                emitJSON(FailedBatchJSON(mode: mode.rawValue, variant: quality ? "quality" : "speed",
                    modelID: modelID, plannedCount: requests.count, completedCount: results.count,
                    wallSeconds: wall, items: outcome.rows))
            } else {
                for result in results { print(result.audioPath) }
                for row in outcome.rows {
                    let signalled = row.cancellationRequested == true ? " (cancellation requested)" : ""
                    note("item \(row.index): \(row.status.rawValue)\(signalled)")
                }
            }
            if outcome.cancelled { throw CancellationError() }
            throw CLIError("batch stopped; completed outputs retained, remaining rows not attempted")
        }

        if args.flag("json") {
            let items = (0..<results.count).map { i in
                ItemJSON(index: i, text: lines[i], audioPath: results[i].audioPath,
                         durationSeconds: results[i].durationSeconds,
                         finishReason: results[i].finishReason?.rawValue)
            }
            emitJSON(BatchJSON(mode: mode.rawValue, variant: quality ? "quality" : "speed",
                               modelID: modelID, count: results.count, wallSeconds: wall, items: items))
        } else {
            for r in results { print(r.audioPath) }
        }
        let totalAudio = results.reduce(0.0) { $0 + $1.durationSeconds }
        note("✓ \(results.count) clip(s) · \(String(format: "%.1f", totalAudio))s audio in \(String(format: "%.1f", wall))s")

        if args.flag("play") { try await CLIPlayback.play(results.map(\.audioPath)) }
    }

    /// The apps refuse a long-form plan of more segments (`IOSLongFormCoordinator.maxSegments`).
    static let longFormMaximumSegments = 100

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
                throw CLIError("line \(lineIndex + 1): the long-form planner refused the project (\(error))")
            }
            guard plan.segments.count <= longFormMaximumSegments else {
                throw CLIError(
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
        let started = ContinuousClock.now
        projects: for (index, plan) in plans.enumerated() {
            let name = "\(filenamePrefix)_\(mode.rawValue)_\(String(format: "%03d", index))"
            let joinedURL = outDir.appendingPathComponent("\(name).wav")
            rows[index].longFormBaseSeed = plan.configuration.baseSeed
            rows[index].longFormPlanDigest = plan.evidence.planDigest
            var segments: [LongFormSegmentJSON] = []
            var sources: [LongFormAssemblySegmentSource] = []
            // The planner numbers its segments from 1 (`evidence.index`); the JSON counts from 0.
            for (position, segment) in plan.segments.enumerated() {
                let generationID = UUID()
                let request = CLIBatchExecution.makeLongFormSegmentRequest(
                    mode: mode, modelID: modelID, text: segment.spokenTextForGeneration,
                    outputPath: outDir.appendingPathComponent(
                        "\(name)_segment_\(String(format: "%03d", position)).wav"
                    ).path,
                    payload: payload, generationID: generationID, subseed: segment.evidence.effectiveSubseed,
                    variation: variation, deliveryInstructionCellID: deliveryInstructionCellID
                )
                do {
                    try Task.checkCancellation()
                    // Named once submitted: a project cancelled first names no take the engine never saw.
                    rows[index].generationID = generationID
                    noteVerbose("project \(index + 1)/\(plans.count), segment \(position + 1)/\(plan.segments.count)")
                    let (result, _, _, _) = try await GenerateCommand.generateObservingFirstChunk(runtime, request)
                    guard FileManager.default.fileExists(atPath: result.audioPath) else {
                        rows[index].status = .failed
                        rows[index].errorCode = "published_output_missing"
                        if Task.isCancelled { rows[index].cancellationRequested = true }
                        stopped = true
                        break projects
                    }
                    segments.append(LongFormSegmentJSON(
                        index: position, segmentID: segment.segmentID,
                        boundary: segment.evidence.boundary.rawValue,
                        intendedPauseMilliseconds: segment.evidence.intendedPauseMilliseconds,
                        effectiveSeed: segment.evidence.effectiveSubseed,
                        generationID: generationID.uuidString, audioPath: result.audioPath,
                        durationSeconds: result.durationSeconds, finishReason: result.finishReason?.rawValue
                    ))
                    // A stopped project keeps the segment takes it completed.
                    rows[index].longFormSegments = segments
                    sources.append(LongFormAssemblySegmentSource(
                        segmentID: segment.segmentID, lineage: segment.evidence.lineage,
                        audioURL: URL(fileURLWithPath: result.audioPath), boundary: segment.evidence.boundary,
                        intendedPauseMilliseconds: segment.evidence.intendedPauseMilliseconds
                    ))
                } catch is CancellationError {
                    rows[index].status = .cancelled
                    rows[index].errorCode = "cancelled"
                    cancelled = true
                    stopped = true
                    break projects
                } catch {
                    // Typed: a genuine failure that coincides with a signal stays failed.
                    rows[index].status = .failed
                    rows[index].errorCode = "generation_failed"
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
                rows[index].errorCode = "assembly_failed"
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
            rows[index].audioPath = joinedPath
            rows[index].durationSeconds = duration
            rows[index].finishReason = finishReason
            rows[index].longFormAssembly = assembly
            items.append(LongFormItemJSON(
                index: index, text: lines[index], audioPath: joinedPath, durationSeconds: duration,
                finishReason: finishReason, longFormBaseSeed: plan.configuration.baseSeed,
                longFormPlanDigest: plan.evidence.planDigest, longFormSegments: segments,
                longFormAssembly: assembly
            ))
        }
        let wall = started.elapsedSeconds
        let variant = quality ? "quality" : "speed"
        if stopped {
            if args.flag("json") {
                emitJSON(FailedLongFormBatchJSON(
                    mode: mode.rawValue, variant: variant, modelID: modelID, plannedCount: plans.count,
                    completedCount: items.count, wallSeconds: wall, items: rows
                ))
            } else {
                for item in items { print(item.audioPath) }
                for row in rows where row.status != .completed {
                    let signalled = row.cancellationRequested == true ? " (cancellation requested)" : ""
                    note("project \(row.index): \(row.status.rawValue)\(signalled)")
                }
            }
            if cancelled { throw CancellationError() }
            throw CLIError("long-form batch stopped; completed projects retained, remaining projects not attempted")
        }
        if args.flag("json") {
            emitJSON(LongFormBatchJSON(
                mode: mode.rawValue, variant: variant, modelID: modelID, count: items.count,
                wallSeconds: wall, items: items
            ))
        } else {
            for item in items { print(item.audioPath) }
        }
        let totalAudio = items.reduce(0.0) { $0 + $1.durationSeconds }
        note("✓ \(items.count) long-form project(s), \(segmentCount) segment(s) · \(String(format: "%.1f", totalAudio))s audio in \(String(format: "%.1f", wall))s")

        if args.flag("play") { try await CLIPlayback.play(items.map(\.audioPath)) }
    }

    private static func readLines(_ args: Args) throws -> [String] {
        let raw: String
        if let f = args.string("file") {
            if f == "-" { raw = readStdinText() ?? "" }
            else {
                let path = (f as NSString).expandingTildeInPath
                do { raw = try String(contentsOfFile: path, encoding: .utf8) }
                catch { throw CLIError("could not read --file \(path): \(error.localizedDescription)") }
            }
        } else {
            raw = readStdinText() ?? ""
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

    static func printHelp() {
        print("""
        vocello batch — synthesize many clips with a single model load

        Usage:
          vocello batch --file <path|-> --mode custom|design|clone --variant speed|quality \\
                        [--speaker <id> | --voice <name> | --voice-brief "…"] [options]

        One non-empty line per clip; all clips share the same voice/mode/variant
        (the engine batches them through one loaded model — far faster than repeated
        `generate` calls). Reads stdin when --file is omitted or "-".

        Options:
          --file         input file, one clip per line ("-" or omitted = stdin)
          --mode         custom (default) | design | clone
          --variant      speed (default) | quality
          --speaker      (custom) speaker id; default = contract default
          --voice-brief  (design) voice description
          --voice        (clone) saved voice name or id
          --reference    (clone) path to a reference .wav
          --transcript   (clone) transcript of the --reference clip
          --confirm-consent  (clone) required: confirms you own or have permission
                         to clone this voice (ignored by other modes)
          --delivery     optional delivery style (applies to all clips)
          --app-delivery with no --delivery/--delivery-cell, send the apps' default
                         delivery (the Neutral preset instruction) on Custom and
                         Design, as a new Studio draft does; otherwise uninstructed
          --out-dir      output directory; default → <data>/outputs/cli/batch/
          --seed         deterministic sampling seed, applied to every item
                         (re-running the batch reproduces it; steadier segments)
          --variation    expressive (default, official) | balanced | consistent
          --long-form    each line is one long-form project, run like the apps' long-form
                         path: planned into segments (--seed is every project's base
                         seed), each segment a streaming take, joined by the bounded
                         assembler; only the engine's per-segment Fast QC applies; the
                         JSON adds each project's segments and assembly evidence
          --capture-codec-trace  internal diagnostics only (QWENVOICE_DEBUG=1, telemetry
                         on, short-form): the engine keeps each take's codec trace
                         (codec-trace v1) beside its diagnostics when the run names a
                         bench run id (QVOICE_MAC_BENCH_RUN_ID); its engine row records
                         the trace digest. Sampling and output are unchanged.
          --play         play each result with afplay when done
          --json         emit a JSON summary on stdout instead of one path per line
          --quiet|--verbose   suppress / expand stderr progress notes
          --data-dir     runtime dir (default ~/Library/Application Support/QwenVoice[-Debug])
          --manifest     override path to qwenvoice_contract.json

        Prints one output WAV path per line on stdout (or a JSON object with --json).
        All-success JSON is unchanged. Partial failure/cancellation emits schemaVersion 2
        with every planned row and exits nonzero. No failed item is retried.
        Batch uses Auto language per text and non-streaming output (a --long-form segment
        streams, as the apps' long-form path does); --language/--stream/--out are rejected
        rather than silently ignored. Use generate for those controls.
        """)
    }
}
