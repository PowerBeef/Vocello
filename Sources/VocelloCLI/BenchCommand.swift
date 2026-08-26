import CryptoKit
import Darwin
import Foundation
import QwenVoiceCore

/// `vocello bench` — the deterministic benchmark/perf driver: drives the matrix
/// (mode × variant × length × cold/warm) in-process with telemetry on,
/// controlling cold/warm exactly via explicit load/unload (no UI waits, no
/// engine-busy races). Then runs the aggregator. Engine telemetry rows (RTF /
/// decode / memory / audioQC / promptChars) are written exactly as in the app.
/// With `--delivery`, it also runs a reference-free prosody analysis on the
/// paired neutral-vs-instructed WAVs and surfaces the deltas in the summary.
enum BenchCommand {
    private struct BenchTakeEnvironment: Codable {
        let loadAverage1Minute: Double?
        let freeStorageBytes: UInt64?
        let uptimeSeconds: Double
        let lowPowerModeEnabled: Bool
        let thermalState: String
    }

    private struct BenchTakeResult: Codable {
        let takeIndex: Int
        let generationID: String
        let cell: String
        let mode: String
        let modelID: String
        let variant: String
        let length: String
        let warmState: String
        let repetition: Int
        let delivery: String?
        /// The exact instruction string sent as `deliveryStyle` for a delivery
        /// cell; nil on plain takes. Provenance echo for the harness — the
        /// downstream prosody sidecar asserts it is non-empty and cross-checks
        /// the engine row's promptChars against the paired neutral take, so an
        /// instruction that silently failed to reach the request is detectable
        /// from the evidence alone (2026-08-04 audit, hardening item 2).
        let deliveryInstruction: String?
        let audioSeconds: Double
        let wallSeconds: Double
        let firstChunkMS: Double?
        let outputFileName: String
        let environment: BenchTakeEnvironment
    }

    /// One delivery attempt that reached generation but did not produce an
    /// analyzable WAV. This is intentionally allowlisted and digest-only: the
    /// autonomous roster lane needs to count the failure in its denominator
    /// without persisting model errors, prompts, or local paths.
    private struct BenchDeliveryFailure: Codable {
        let takeIndex: Int
        let generationID: String
        let cell: String
        let mode: String
        let modelID: String
        let variant: String
        let length: String
        let warmState: String
        let repetition: Int
        let delivery: String
        let deliveryInstructionDigest: String
        let reasonCode: String
        let qualityFlags: [String]
        let errorDigest: String
        let rejectedOutputFileName: String?
    }

    /// A plain neutral reference attempt that did not produce product-accepted
    /// audio. It is retained separately because it is not a delivery outcome
    /// and must never enter the preset adherence denominator.
    private struct BenchReferenceFailure: Codable {
        let takeIndex: Int
        let generationID: String
        let cell: String
        let mode: String
        let modelID: String
        let variant: String
        let length: String
        let warmState: String
        let repetition: Int
        let reasonCode: String
        let qualityFlags: [String]
        let errorDigest: String
        let rejectedOutputFileName: String?
    }

    /// Carries the request identity out of `take` without exposing the raw
    /// generation error in retained evidence.
    private struct BenchTakeExecutionFailure: Error, LocalizedError {
        let generationID: String
        let underlyingDescription: String

        var errorDescription: String? { underlyingDescription }
    }

    private struct BenchResultsManifest: Codable {
        let schemaVersion: Int
        let runID: String
        let label: String
        /// Exact Built-in Voice speaker selected for Custom rows. Historical
        /// schema-v1 manifests omitted this field and therefore cannot support
        /// speaker-generalization claims; the Python sidecar keeps them
        /// readable but the roster harness requires this receipt.
        let customSpeakerID: String?
        let startedAt: String
        let finishedAt: String
        let telemetryMode: String
        let seed: UInt64?
        let streaming: Bool
        let fixtureDigests: [String: String]
        let memoryQualification: BenchMemoryQualification?
        let takes: [BenchTakeResult]
        let referenceFailures: [BenchReferenceFailure]
        /// Present for new manifests. Non-empty values are permitted only for
        /// the explicit no-summary diagnostic continuation route.
        let deliveryFailures: [BenchDeliveryFailure]
    }

    /// Declares the exact retained-memory protocol selected by the caller. The
    /// Python validator still computes and gates the evidence from raw v8
    /// sidecars; this declaration prevents an ordinary benchmark matrix from
    /// being mislabeled as a memory qualification after generation.
    private struct BenchMemoryQualification: Codable {
        let policyID: String
        let modeOrder: [String]
        let variant: String
        let length: String
        let warmRepetitions: Int
        let expectedTakeCount: Int
    }

    /// Fixed corpus — shared with macOS XPC UI bench via `BenchMatrixSpec`.
    static var corpus: [(len: String, text: String)] { BenchMatrixSpec.corpus }
    static var defaultDesignBrief: String { BenchMatrixSpec.defaultDesignBrief }
    static var defaultCloneVoice: String { BenchMatrixSpec.defaultCloneVoice }

    /// Default delivery cells for `--delivery` (bare flag): one expressive, one
    /// calm, one whisper — the three preset families with distinct acoustic
    /// signatures, so QC + the prosody gate cover the delivery spectrum. All at
    /// the strong tier, which is what every product surface ships (DP-8);
    /// normal-tier cells remain addressable explicitly for experiments.
    static let defaultDeliverySet = ["happy.strong", "calm.strong", "whisper.strong"]

    /// Bucket a prompt char count into the short/medium/long labels used for
    /// filenames and the telemetry `lenBucket`. Mirrors the logic in
    /// `scripts/summarize_generation_telemetry.py`.
    static func lenBucket(_ chars: Int) -> String {
        BenchMatrixSpec.lenBucket(chars)
    }

    /// A resolved delivery cell: `id` is the stable `<preset>.<intensity>` token
    /// (stamped into the telemetry note + filename), `instruction` the preset's
    /// instruction string sent as `deliveryStyle`.
    typealias DeliveryItem = DeliveryInstructionCell

    /// Parse `--delivery` items (`<preset>[.<intensity>]`, intensity defaults to
    /// normal) against the shared EmotionPreset table. Fails loudly on unknown
    /// presets/intensities and on neutral (which sends no instruction — a plain
    /// warm take already covers it).
    static func resolveDeliveryItems(_ spec: String?) throws -> [DeliveryItem] {
        let tokens = parseList(spec) ?? defaultDeliverySet
        return try tokens.map { token in
            let explicit = token.contains(".") ? token : "\(token).strong"
            do {
                return try DeliveryInstructionCell.resolveStrict(explicit)
            } catch {
                throw CLIError(error.localizedDescription)
            }
        }
    }

    @MainActor
    static func run(_ argv: [String]) async throws {
        let args = Args(argv)
        if args.flag("help") { printHelp(); return }
        CLIOutput.configure(args)

        // Invariant: the filename length token is derived via the same lenBucket
        // the summarizer uses, so producer and consumer agree by construction.
        try BenchMatrixSpec.validateCorpus()

        let modes = try parseMatrixAxis(
            args.string("modes"),
            option: "modes",
            wasBareFlag: args.flag("modes"),
            defaults: GenerationMode.allCases.map(\.rawValue),
            allowed: GenerationMode.allCases.map(\.rawValue)
        )
        let variants = try parseMatrixAxis(
            args.string("variants"),
            option: "variants",
            wasBareFlag: args.flag("variants"),
            defaults: ["speed", "quality"],
            allowed: ["speed", "quality"]
        )
        let lengths = try parseMatrixAxis(
            args.string("lengths"),
            option: "lengths",
            wasBareFlag: args.flag("lengths"),
            defaults: ["short", "medium", "long"],
            allowed: corpus.map(\.len)
        )
        let noSummary = args.flag("no-summary")
        let label = try validatedBenchmarkLabel(args.string("label"))
        if args.flag("speaker") {
            throw CLIError("--speaker requires a speaker id")
        }
        let requestedCustomSpeakerID = args.string("speaker")
        if requestedCustomSpeakerID != nil, !modes.contains("custom") {
            throw CLIError("--speaker applies only when --modes includes custom")
        }

        // Published schema-v2 benchmarks require the exact raw sampler sidecars.
        // `--no-summary` diagnostic parents may still choose lightweight; a normal
        // history-producing run defaults to verbose and rejects incomplete capture
        // before model work begins.
        let telemetryRaw = (args.string("telemetry") ?? "verbose").lowercased()
        guard ["off", "lightweight", "verbose"].contains(telemetryRaw) else {
            throw CLIError("--telemetry must be off, lightweight, or verbose")
        }
        let telemetryOff = telemetryRaw == "off"
        let telemetryVerbose = telemetryRaw == "verbose"
        guard telemetryOff || telemetryVerbose || noSummary else {
            throw CLIError(
                "history-producing benchmarks require --telemetry verbose for schema-v2 memory evidence"
            )
        }
        if telemetryOff {
            setenv("QWENVOICE_NATIVE_TELEMETRY_MODE", "off", 1)
        } else {
            TelemetryGate.applyHandshakeMode(telemetryVerbose ? .verbose : .lightweight)
            if telemetryVerbose { setenv("QWENVOICE_NATIVE_TELEMETRY_MODE", "verbose", 1) }
            setenv("QWENVOICE_DEBUG", "1", 0)
        }

        // Bench isolates memory from inline preview PCM (no UI consumer) and must
        // drain the bounded macOS engine.events stream during streaming takes.
        try installRuntimeDebugOverride(
            key: "QWENVOICE_STREAMING_PREVIEW_DATA",
            value: "off"
        )

        let runID = args.string("run-id") ?? "macos-engine-\(Self.utcRunTimestamp())-\(UUID().uuidString.lowercased().prefix(8))"
        setenv("QVOICE_MAC_BENCH_RUN_ID", runID, 1)
        defer {
            unsetenv("QVOICE_MAC_BENCH_RUN_ID")
            BenchRunContext.clearCurrentTakeFile()
        }

        // --force-class: run constrained-tier code paths on any Mac. Must be set
        // before the device class is first resolved (i.e. before bootstrap).
        if let tier = args.string("force-class") {
            let canonical = try canonicalForceClass(tier)
            try installRuntimeDebugOverride(
                key: "QWENVOICE_FORCE_MEMORY_CLASS",
                value: canonical
            )
            note("forcing memory class: \(canonical)")
        }

        let warm: Int
        if let rawWarm = args.string("warm") {
            guard let parsedWarm = Int(rawWarm), parsedWarm >= 0 else {
                throw CLIError("--warm must be a non-negative whole number")
            }
            warm = parsedWarm
        } else {
            warm = 3
        }
        let designBrief = args.string("voice-brief") ?? defaultDesignBrief
        let cloneVoiceName = args.string("voice") ?? defaultCloneVoice
        let ttfc = args.flag("ttfc")
        let noStream = args.flag("no-stream")
        let seed = try GenerateCommand.parseSeed(args)
        // --delivery [list]: instruct-bearing cells on top of the plain matrix.
        // Value form picks the cells; the bare flag runs the default set.
        let deliveryItems: [DeliveryItem]
        if let deliverySpec = args.string("delivery") {
            deliveryItems = try resolveDeliveryItems(deliverySpec)
        } else if args.flag("delivery") {
            deliveryItems = try resolveDeliveryItems(nil)
        } else {
            deliveryItems = []
        }
        if warm == 0, modes.contains("clone") {
            throw CLIError("--warm 0 cannot be used with Clone because Clone has no separate cold cell")
        }
        if warm == 0, !deliveryItems.isEmpty {
            throw CLIError("--warm 0 cannot be used with --delivery because delivery analysis requires a neutral warm cell")
        }
        let continueDeliveryFailures = args.flag("continue-delivery-failures")
        if continueDeliveryFailures, deliveryItems.isEmpty {
            throw CLIError("--continue-delivery-failures requires --delivery")
        }
        if continueDeliveryFailures, !noSummary {
            throw CLIError("--continue-delivery-failures requires --no-summary")
        }
        let prosodyProfilePath = args.string("prosody-profile")
        let memoryQualification = try memoryQualificationDeclaration(
            rawPolicy: args.string("memory-qualification"),
            wasBareFlag: args.flag("memory-qualification"),
            modes: modes,
            variants: variants,
            lengths: lengths,
            warm: warm,
            seed: seed,
            telemetryVerbose: telemetryVerbose,
            noStream: noStream,
            hasDeliveryCells: !deliveryItems.isEmpty
        )
        if memoryQualification != nil, requestedCustomSpeakerID != nil {
            throw CLIError("--speaker cannot alter the fixed retained-memory qualification fixture")
        }

        // Bench path isolation is independent of telemetry. In particular,
        // `--telemetry off` must not resolve the default through production
        // `~/Library/Application Support/QwenVoice` and clear its diagnostics.
        let resolvedDataDir = LocalBenchmarkDataPolicy.resolvedDataDirectory(
            explicitOverride: args.string("data-dir"),
            applicationSupportBase: Self.applicationSupportBaseDirectory()
        )
        let manifestOverride = args.string("manifest").map {
            URL(fileURLWithPath: ($0 as NSString).expandingTildeInPath)
        }
        let registryContext = try CLIRuntime.bootstrapRegistryOnly(
            dataDirectory: resolvedDataDir,
            manifestOverride: manifestOverride
        )
        let customSpeakerID = requestedCustomSpeakerID ?? registryContext.registry.defaultSpeaker.id
        let knownCustomSpeakerIDs = Set(registryContext.registry.allSpeakers.map(\.id))
        guard knownCustomSpeakerIDs.contains(customSpeakerID) else {
            throw CLIError(
                "unknown --speaker '\(customSpeakerID)' (use `vocello speakers list`)"
            )
        }
        if !args.flag("keep") {
            try clearDiagnosticsIfSafe(dataDir: resolvedDataDir, force: args.flag("force"))
        }

        let diagDir = resolvedDataDir.appendingPathComponent("diagnostics", isDirectory: true)
        // Parent diagnostic lanes use --no-summary and own their artifact layout.
        // Standalone benches retain one immutable per-run manifest/snapshot so a
        // later run cannot overwrite the evidence needed for delayed recording.
        let historyArtifactDir = noSummary
            ? diagDir
            : diagDir
                .appendingPathComponent("benchmark-runs", isDirectory: true)
                .appendingPathComponent(runID, isDirectory: true)
        let historyPublisher = (!noSummary && !telemetryOff) ? locateHistoryPublisher() : nil
        let summarizerScript = (!noSummary && !telemetryOff) ? locateSummarizer() : nil
        if let historyPublisher {
            try captureHistorySourceSnapshot(publisher: historyPublisher, artifactDirectory: historyArtifactDir)
        } else if !noSummary, !telemetryOff {
            note("benchmark registry unavailable outside a Vocello checkout; local results will be retained")
        }
        if summarizerScript == nil, !noSummary, !telemetryOff {
            note("benchmark summarizer unavailable outside a Vocello checkout; local results will be retained")
        }

        note("bench • data: \(resolvedDataDir.path)")
        let runtime = try await CLIRuntime.bootstrap(
            dataDirectory: resolvedDataDir,
            manifestOverride: manifestOverride
        )

        let outDir = resolvedDataDir.appendingPathComponent("outputs/bench", isDirectory: true)
        try FileManager.default.createDirectory(at: outDir, withIntermediateDirectories: true)

        // --- Preflight (fail fast up front, not mid-matrix) ---
        // Clone needs a saved voice when clone is in --modes.
        var cloneReference: CloneReference?
        if modes.contains("clone") {
            let voices = try await runtime.engine.listPreparedVoices()
            let have = voices.map(\.name).joined(separator: ", ")
            if let v = voices.first(where: { $0.name == cloneVoiceName || $0.id == cloneVoiceName }) {
                cloneReference = CloneReference(audioPath: v.audioPath, transcript: nil, preparedVoiceID: v.id)
            } else {
                throw CLIError("clone bench needs saved voice '\(cloneVoiceName)' (have: \(have.isEmpty ? "none" : have))")
            }
        }
        var fixtureDigests = [
            "design": sha256(Data(designBrief.utf8)),
            "customSpeaker": sha256(Data(customSpeakerID.utf8)),
        ]
        if let audioPath = cloneReference?.audioPath,
           let audioData = try? Data(contentsOf: URL(fileURLWithPath: audioPath)) {
            fixtureDigests["clone"] = sha256(audioData)
        }
        // Every requested (mode × variant) model must be installed — fail fast.
        try preflightModels(runtime: runtime, modes: modes, variants: variants, dataDir: resolvedDataDir)

        let coldLen = lengths.contains("medium") ? "medium" : lengths.first
        var total = 0
        var takeResults: [BenchTakeResult] = []
        var referenceFailures: [BenchReferenceFailure] = []
        var deliveryFailures: [BenchDeliveryFailure] = []
        let started = Date()
        let startedAt = ISO8601DateFormatter().string(from: started)

        for modeStr in modes {
            guard let mode = GenerationMode(rawValue: modeStr) else {
                throw CLIError("invalid --modes value '\(modeStr)'")
            }
            for variantStr in variants {
                let quality = variantStr.lowercased() == "quality"
                let modelID = try runtime.modelID(mode: mode, quality: quality)

                let payload = try payload(for: mode, customSpeaker: customSpeakerID,
                                          designBrief: designBrief, cloneReference: cloneReference)

                // Force cold for this cell: unload whatever's loaded so the next
                // generate loads inside the call (records warmState=cold).
                try? await runtime.engine.unloadModel()

                // Cold sample (Custom/Design only — Clone is warm-by-design).
                if mode != .clone, let coldLen {
                    let coldText = try requiredText(for: coldLen)
                    total += 1
                    let cell = "\(mode.rawValue)/\(variantStr.lowercased())/\(coldLen)/cold#0"
                    try BenchRunContext.writeCurrentTakeFile(
                        takeIndex: total, cell: cell, intendedWarmState: "cold"
                    )
                    do {
                        takeResults.append(try await take(
                            runtime, mode: mode, modelID: modelID, payload: payload,
                            len: coldLen, text: coldText, state: "cold", n: 0, outDir: outDir,
                            takeIndex: total, cell: cell, shouldStream: !noStream, seed: seed
                        ))
                    } catch {
                        guard continueDeliveryFailures else { throw error }
                        let rejected = preserveRejectedWAV(
                            dataDir: resolvedDataDir,
                            outDir: outDir,
                            fileName: "rejected_reference_cold_attempt\(total).wav"
                        )
                        referenceFailures.append(referenceFailure(
                            error: error, takeIndex: total, cell: cell, mode: mode,
                            modelID: modelID, length: coldLen, warmState: "cold",
                            repetition: 0, rejectedOutputFileName: rejected
                        ))
                    }
                }
                // Warm samples per requested length.
                for len in lengths {
                    let t = try requiredText(for: len)
                    for n in 0..<warm {
                        total += 1
                        let repetition = memoryQualification == nil ? "warm#\(n)" : "retained#\(n)"
                        let cell = "\(mode.rawValue)/\(variantStr.lowercased())/\(len)/\(repetition)"
                        // Clone has no separate cold sample. The first retained take follows the
                        // forced unload above, so stamp the observed lifecycle truth instead of
                        // calling that model-loading take warm. The retained cell name remains
                        // stable because it identifies the qualification sequence, not cache state.
                        let retainedWarmState = memoryQualification != nil && mode == .clone && n == 0
                            ? "cold"
                            : "warm"
                        try BenchRunContext.writeCurrentTakeFile(
                            takeIndex: total, cell: cell, intendedWarmState: retainedWarmState
                        )
                        do {
                            takeResults.append(try await take(
                                runtime, mode: mode, modelID: modelID, payload: payload,
                                len: len, text: t, state: retainedWarmState, n: n, outDir: outDir,
                                takeIndex: total, cell: cell, shouldStream: !noStream, seed: seed
                            ))
                        } catch {
                            guard continueDeliveryFailures else { throw error }
                            let rejected = preserveRejectedWAV(
                                dataDir: resolvedDataDir,
                                outDir: outDir,
                                fileName: "rejected_reference_warm\(n)_attempt\(total).wav"
                            )
                            referenceFailures.append(referenceFailure(
                                error: error, takeIndex: total, cell: cell, mode: mode,
                                modelID: modelID, length: len, warmState: retainedWarmState,
                                repetition: n, rejectedOutputFileName: rejected
                            ))
                        }
                    }
                }

                // Delivery cells (--delivery): instruct-bearing warm takes on the
                // medium text, one per requested preset.intensity. Custom/Design
                // only — the clone checkpoints have no instruction control. The
                // plain warm takes above double as the neutral reference for the
                // deterministic prosody comparison; the summarizer segregates these rows via
                // the notes.delivery stamp so the headline matrix stays clean.
                if !deliveryItems.isEmpty, mode != .clone {
                    let deliveryText = try requiredText(for: "medium")
                    for item in deliveryItems {
                        // Prompt-echo provenance: a delivery cell whose
                        // instruction resolves empty would generate a silent
                        // neutral take labelled as instructed — the plumbing
                        // null the audit's H3 could never rule out. Refuse.
                        guard !item.instruction.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
                            throw CLIError("delivery cell \(item.id) resolved an empty instruction")
                        }
                        let deliveryPayload = try Self.payload(
                            for: mode, customSpeaker: customSpeakerID,
                            designBrief: designBrief, cloneReference: cloneReference,
                            deliveryStyle: item.instruction)
                        total += 1
                        let cell = "\(mode.rawValue)/\(variantStr.lowercased())/medium/warm#delivery-\(item.id)"
                        try BenchRunContext.writeCurrentTakeFile(
                            takeIndex: total, cell: cell, intendedWarmState: "warm"
                        )
                        do {
                            takeResults.append(try await take(
                                runtime, mode: mode, modelID: modelID, payload: deliveryPayload,
                                len: "medium", text: deliveryText, state: "warm", n: 0,
                                outDir: outDir, takeIndex: total, cell: cell, delivery: item.id,
                                deliveryInstruction: item.instruction,
                                shouldStream: !noStream, seed: seed
                            ))
                        } catch {
                            guard continueDeliveryFailures else { throw error }
                            let rejectedOutputFileName = preserveRejectedWAV(
                                dataDir: resolvedDataDir,
                                outDir: outDir,
                                fileName: "rejected_delivery_\(item.id)_attempt\(total).wav"
                            )
                            let captured = deliveryFailure(
                                error: error,
                                takeIndex: total,
                                cell: cell,
                                mode: mode,
                                modelID: modelID,
                                delivery: item,
                                rejectedOutputFileName: rejectedOutputFileName
                            )
                            deliveryFailures.append(captured)
                            note("  retained \(item.id) failure: \(captured.reasonCode)")
                        }
                    }
                }
            }
        }

        note("✓ \(takeResults.count)/\(total) analyzable takes in \(String(format: "%.0f", Date().timeIntervalSince(started)))s")

        try writeResultsManifest(
            BenchResultsManifest(
                schemaVersion: 1,
                runID: runID,
                label: label.isEmpty ? runID : label,
                customSpeakerID: modes.contains("custom") ? customSpeakerID : nil,
                startedAt: startedAt,
                finishedAt: ISO8601DateFormatter().string(from: Date()),
                telemetryMode: telemetryRaw,
                seed: seed,
                streaming: !noStream,
                fixtureDigests: fixtureDigests,
                memoryQualification: memoryQualification,
                takes: takeResults,
                referenceFailures: referenceFailures,
                deliveryFailures: deliveryFailures
            ),
            artifactDirectory: historyArtifactDir
        )
        if summarizerScript != nil {
            // Prosody must be generated from this run's immutable results manifest
            // before aggregation so the summary includes it and stale shared WAVs
            // can never enter the current run's evidence.
            if !deliveryItems.isEmpty {
                guard let prosodyScript = locateDeliveryProsodyAnalyzer() else {
                    throw CLIError("delivery prosody script not found from \(FileManager.default.currentDirectoryPath)")
                }
                try runDeliveryProsodyAnalysis(
                    script: prosodyScript,
                    diagnostics: diagDir,
                    resultsManifest: historyArtifactDir.appendingPathComponent("bench-results.json"),
                    profilePath: prosodyProfilePath
                )
                // Phase 12 close-out: consolidate the persisted-WAV analyses
                // (Fast QC + the sidecar prosody gate) into one composed
                // standard-depth registry verdict per delivery take. A missing
                // analyzer or a fail verdict fails the run (fail-closed).
                try composeDeliveryCanonicalQuality(
                    diagnostics: diagDir, outputs: outDir, runID: runID
                )
            } else {
                // A --keep run without delivery must not inherit an older sidecar.
                try? FileManager.default.removeItem(
                    at: diagDir.appendingPathComponent("bench-prosody.json")
                )
            }
        }
        // Evidence retention for delivery runs, independent of publication:
        // the live outputs directory keeps fixed per-cell filenames (and
        // therefore overwrite semantics), so without this archive an 18-seed
        // sweep destroys 17/18ths of its own audio evidence — which is
        // exactly what happened to DP-10 (2026-08-04 delivery-control audit).
        if !deliveryItems.isEmpty {
            try archiveDeliveryEvidence(
                dataDir: resolvedDataDir, outputs: outDir, diagnostics: diagDir,
                artifactDirectory: historyArtifactDir, takes: takeResults,
                referenceFailures: referenceFailures,
                deliveryFailures: deliveryFailures, runID: runID
            )
        }
        // Optional engine first-chunk-latency probe. Runs after the main matrix but
        // before final evidence publication. The immutable results manifest selects
        // only the matrix generations, so these probe rows cannot perturb its summary.
        // This is engine-side TTFC — not the app's through-XPC
        // submit-to-playback-scheduled latency.
        if ttfc {
            note("ttfc probe (warm streaming, after summary)…")
            var rows: [TTFCRow] = []
            for modeStr in modes {
                guard let mode = GenerationMode(rawValue: modeStr) else {
                    throw CLIError("invalid --modes value '\(modeStr)'")
                }
                for variantStr in variants {
                    let quality = variantStr.lowercased() == "quality"
                    let modelID = try runtime.modelID(mode: mode, quality: quality)
                    guard let probeLen = coldLen ?? lengths.first else {
                        throw CLIError("benchmark matrix has no lengths")
                    }
                    let probeText = try requiredText(for: probeLen)
                    let payload = try payload(for: mode, customSpeaker: customSpeakerID,
                                              designBrief: designBrief, cloneReference: cloneReference)
                    try await runtime.engine.loadModel(id: modelID)  // warm
                    let out = outDir.appendingPathComponent("\(mode.rawValue)_\(modelID)_ttfcprobe.wav").path
                    let request = GenerationRequest(
                        mode: mode, modelID: modelID, text: probeText, outputPath: out,
                        shouldStream: true, streamingInterval: GenerationSemantics.appStreamingInterval,
                        payload: payload, generationID: UUID(), seed: seed)
                    let (_, ms, _) = try await GenerateCommand.generateObservingFirstChunk(runtime, request)
                    rows.append(TTFCRow(mode: mode.rawValue, variant: quality ? "quality" : "speed",
                                        modelID: modelID, firstChunkMS: ms))
                    note("  ttfc \(mode.rawValue)/\(quality ? "Q" : "S"): \(ms.map { String(format: "%.0f", $0) } ?? "-")ms")
                }
            }
            reportTTFC(rows, diagnostics: diagDir)
        }

        // Publication is deliberately last: an optional TTFC probe is still part
        // of this command's success contract, so it must not be able to fail after
        // a tracked PASS record has already been created.
        if let historyPublisher {
            guard let summarizerScript else {
                throw CLIError("benchmark publisher is available but the telemetry summarizer is missing")
            }
            try prepareEngineHistoryEvidence(
                publisher: historyPublisher,
                artifactDirectory: historyArtifactDir,
                diagnostics: diagDir,
                outputs: outDir,
                runID: runID,
                label: label,
                publisherSubcommand: memoryQualification == nil
                    ? "engine"
                    : "memory-qualification"
            )
            try runSummarizer(
                script: summarizerScript,
                diagnostics: diagDir,
                evidenceManifest: historyArtifactDir.appendingPathComponent("benchmark-evidence.json"),
                runID: runID,
                label: label
            )
            try recordEngineHistory(
                historyScript: historyPublisher.deletingLastPathComponent()
                    .appendingPathComponent("benchmark_history.py"),
                artifactDirectory: historyArtifactDir
            )
        } else if telemetryOff {
            note("benchmark history skipped because telemetry is off")
        } else if noSummary {
            note("benchmark history skipped with --no-summary (parent diagnostic lane owns publication)")
        } else {
            note("benchmark history not published; local manifest → \(historyArtifactDir.appendingPathComponent("bench-results.json").path)")
        }

    }

    // MARK: - One take

    @MainActor
    private static func take(_ runtime: CLIRuntime, mode: GenerationMode, modelID: String,
                             payload: GenerationRequest.Payload, len: String, text: String,
                             state: String, n: Int, outDir: URL,
                             takeIndex: Int, cell: String, delivery: String? = nil,
                             deliveryInstruction: String? = nil,
                             shouldStream: Bool = true, seed: UInt64? = nil) async throws -> BenchTakeResult {
        // Bucket the char count with the SAME function the summarizer uses, so
        // the filename and the telemetry row agree by construction regardless of
        // the bucket thresholds.
        let lenToken = lenBucket(text.count)
        // Delivery takes extend the state token (`warm_d-<preset>.<intensity>`)
        // so the filename and the engine row's notes.delivery stamp agree.
        let stateToken = delivery.map { "\(state)_d-\($0)" } ?? state
        let out = outDir.appendingPathComponent("\(mode.rawValue)_\(modelID)_\(lenToken)_\(stateToken)_\(n).wav").path
        let generationID = UUID()
        let request = GenerationRequest(
            mode: mode, modelID: modelID, text: text, outputPath: out,
            shouldStream: shouldStream, payload: payload, generationID: generationID, seed: seed,
            deliveryInstructionCellID: mode == .custom ? delivery : nil)
        if let delivery { setenv("QWENVOICE_BENCH_DELIVERY", delivery, 1) }
        defer { if delivery != nil { unsetenv("QWENVOICE_BENCH_DELIVERY") } }
        let environment = captureEnvironment()
        let t0 = Date()
        let result: GenerationResult
        var firstChunkMS: Double?
        do {
            if shouldStream {
                // Drain engine.events so the bounded macOS stream does not retain preview/chunk
                // events across matrix takes (see GenerateCommand.generateObservingFirstChunk).
                let (genResult, observedFirstChunkMS, _) = try await GenerateCommand.generateObservingFirstChunk(runtime, request)
                result = genResult
                firstChunkMS = observedFirstChunkMS
            } else {
                result = try await runtime.engine.generate(request)
            }
        } catch {
            throw BenchTakeExecutionFailure(
                generationID: generationID.uuidString,
                underlyingDescription: String(describing: error)
            )
        }
        let wall = Date().timeIntervalSince(t0)
        let deliveryTag = delivery.map { "/\($0)" } ?? ""
        let ttfcTag = firstChunkMS.map { "  ttfc=\(String(format: "%.1f", $0))ms" } ?? ""
        FileHandle.standardError.write(Data(
            "  \(mode.rawValue)/\(modelID.hasSuffix("quality") ? "Q" : "S")/\(len)/\(state)\(deliveryTag)#\(n)  \(String(format: "%.2f", result.durationSeconds))s audio in \(String(format: "%.1f", wall))s\(ttfcTag)\n".utf8))
        return BenchTakeResult(
            takeIndex: takeIndex,
            generationID: generationID.uuidString,
            cell: cell,
            mode: mode.rawValue,
            modelID: modelID,
            variant: modelID.hasSuffix("quality") ? "quality" : "speed",
            length: len,
            warmState: state,
            repetition: n,
            delivery: delivery,
            deliveryInstruction: deliveryInstruction,
            audioSeconds: result.durationSeconds,
            wallSeconds: wall,
            firstChunkMS: firstChunkMS,
            outputFileName: URL(fileURLWithPath: out).lastPathComponent,
            environment: environment
        )
    }

    private static func captureEnvironment() -> BenchTakeEnvironment {
        var loads = [Double](repeating: 0, count: 3)
        let loadCount = loads.withUnsafeMutableBufferPointer { buffer -> Int in
            guard let baseAddress = buffer.baseAddress else { return 0 }
            return Int(getloadavg(baseAddress, Int32(buffer.count)))
        }
        let freeStorage = (
            try? FileManager.default.attributesOfFileSystem(forPath: NSHomeDirectory())
        )?[.systemFreeSize] as? NSNumber
        let processInfo = ProcessInfo.processInfo
        let thermal: String
        switch processInfo.thermalState {
        case .nominal: thermal = "nominal"
        case .fair: thermal = "fair"
        case .serious: thermal = "serious"
        case .critical: thermal = "critical"
        @unknown default: thermal = "unknown"
        }
        return BenchTakeEnvironment(
            loadAverage1Minute: loadCount > 0 ? loads[0] : nil,
            freeStorageBytes: freeStorage?.uint64Value,
            uptimeSeconds: processInfo.systemUptime,
            lowPowerModeEnabled: processInfo.isLowPowerModeEnabled,
            thermalState: thermal
        )
    }

    private static func writeResultsManifest(
        _ manifest: BenchResultsManifest,
        artifactDirectory: URL
    ) throws {
        try FileManager.default.createDirectory(at: artifactDirectory, withIntermediateDirectories: true)
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
        let data = try encoder.encode(manifest)
        try data.write(
            to: artifactDirectory.appendingPathComponent("bench-results.json"),
            options: .atomic
        )
    }

    private static func utcRunTimestamp() -> String {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.timeZone = TimeZone(secondsFromGMT: 0)
        formatter.dateFormat = "yyyyMMdd-HHmmss"
        return formatter.string(from: Date())
    }

    private static func sha256(_ data: Data) -> String {
        SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
    }

    private static func deliveryFailure(
        error: Error,
        takeIndex: Int,
        cell: String,
        mode: GenerationMode,
        modelID: String,
        delivery: DeliveryItem,
        rejectedOutputFileName: String?
    ) -> BenchDeliveryFailure {
        let classified = classifyGenerationFailure(error)
        return BenchDeliveryFailure(
            takeIndex: takeIndex,
            generationID: classified.generationID,
            cell: cell,
            mode: mode.rawValue,
            modelID: modelID,
            variant: modelID.hasSuffix("quality") ? "quality" : "speed",
            length: "medium",
            warmState: "warm",
            repetition: 0,
            delivery: delivery.id,
            deliveryInstructionDigest: sha256(Data(delivery.instruction.utf8)),
            reasonCode: classified.reasonCode,
            qualityFlags: classified.qualityFlags,
            errorDigest: classified.errorDigest,
            rejectedOutputFileName: rejectedOutputFileName
        )
    }

    private static func referenceFailure(
        error: Error,
        takeIndex: Int,
        cell: String,
        mode: GenerationMode,
        modelID: String,
        length: String,
        warmState: String,
        repetition: Int,
        rejectedOutputFileName: String?
    ) -> BenchReferenceFailure {
        let classified = classifyGenerationFailure(error)
        return BenchReferenceFailure(
            takeIndex: takeIndex,
            generationID: classified.generationID,
            cell: cell,
            mode: mode.rawValue,
            modelID: modelID,
            variant: modelID.hasSuffix("quality") ? "quality" : "speed",
            length: length,
            warmState: warmState,
            repetition: repetition,
            reasonCode: classified.reasonCode,
            qualityFlags: classified.qualityFlags,
            errorDigest: classified.errorDigest,
            rejectedOutputFileName: rejectedOutputFileName
        )
    }

    private static func classifyGenerationFailure(
        _ error: Error
    ) -> (generationID: String, reasonCode: String, qualityFlags: [String], errorDigest: String) {
        let execution = error as? BenchTakeExecutionFailure
        let description = execution?.underlyingDescription ?? String(describing: error)
        let normalized = description.lowercased()
        let reasonCode: String
        if normalized.contains("dropout:") {
            reasonCode = "fast_qc_dropout"
        } else if normalized.contains("mandatory fast audio qc") {
            reasonCode = "fast_qc_failure"
        } else if normalized.contains("cancel") {
            reasonCode = "cancelled"
        } else if normalized.contains("token") && normalized.contains("limit") {
            reasonCode = "generation_token_limit"
        } else {
            reasonCode = "generation_failed"
        }
        return (
            execution?.generationID ?? "unavailable",
            reasonCode,
            allowlistedQualityFlags(in: description),
            sha256(Data(description.utf8))
        )
    }

    private static func allowlistedQualityFlags(in description: String) -> [String] {
        let pattern = #"dropout:(?:[0-9]+ms|excess[0-9]+\([0-9]+/[0-9]+\))|nonfinite|empty|near_silent|low_level|silent|clipping|clicks|hot|dc_offset"#
        guard let expression = try? NSRegularExpression(pattern: pattern) else { return [] }
        let range = NSRange(description.startIndex..<description.endIndex, in: description)
        var observed: [String] = []
        for match in expression.matches(in: description, range: range) {
            guard let swiftRange = Range(match.range, in: description) else { continue }
            let flag = String(description[swiftRange])
            if !observed.contains(flag) { observed.append(flag) }
        }
        return observed
    }

    private static func preserveRejectedWAV(
        dataDir: URL,
        outDir: URL,
        fileName: String
    ) -> String? {
        let source = dataDir
            .appendingPathComponent("cache/stream_sessions/failed-audio-qc", isDirectory: true)
            .appendingPathComponent("failed-qc-latest.wav", isDirectory: false)
        let destination = outDir.appendingPathComponent(fileName, isDirectory: false)
        let fileManager = FileManager.default
        guard fileManager.fileExists(atPath: source.path) else { return nil }
        do {
            try? fileManager.removeItem(at: destination)
            try fileManager.copyItem(at: source, to: destination)
            return fileName
        } catch {
            return nil
        }
    }

    private static func payload(for mode: GenerationMode, customSpeaker: String, designBrief: String,
                                cloneReference: CloneReference?, deliveryStyle: String? = nil) throws -> GenerationRequest.Payload {
        switch mode {
        case .custom: return .custom(speakerID: customSpeaker, deliveryStyle: deliveryStyle)
        case .design: return .design(voiceDescription: designBrief, deliveryStyle: deliveryStyle)
        case .clone:
            guard let cloneReference else { throw CLIError("clone reference unavailable") }
            return .clone(reference: cloneReference)
        }
    }

    private static func text(for len: String) -> String? {
        corpus.first { $0.len == len }?.text
    }

    private static func requiredText(for length: String) throws -> String {
        guard let text = text(for: length) else {
            throw CLIError("benchmark corpus has no text for length '\(length)'")
        }
        return text
    }

    private static func runSummarizer(
        script: URL,
        diagnostics: URL,
        evidenceManifest: URL,
        runID: String,
        label: String
    ) throws {
        note("aggregating →")
        let p = Process()
        p.executableURL = URL(fileURLWithPath: "/usr/bin/env")
        var pargs = [
            "python3", script.path, diagnostics.path,
            "--run-id", runID,
            "--evidence-manifest", evidenceManifest.path,
            "--engine-only",
        ]
        if !label.isEmpty { pargs += ["--label", label] }
        p.arguments = pargs
        do { try p.run() } catch {
            throw CLIError("could not start telemetry summarizer: \(error.localizedDescription)")
        }
        p.waitUntilExit()
        guard p.terminationStatus == 0 else {
            throw CLIError("strict telemetry summarizer failed for runID=\(runID)")
        }
    }

    /// Resolve the repo-relative summarizer by walking up from cwd (mirrors
    /// manifest discovery), so bench works from any subdirectory of the repo.
    private static func locateSummarizer() -> URL? {
        let rel = "scripts/summarize_generation_telemetry.py"
        let cwd = FileManager.default.currentDirectoryPath
        if FileManager.default.fileExists(atPath: cwd + "/" + rel) { return URL(fileURLWithPath: cwd + "/" + rel) }
        return CLIRuntime.findUpwards(relativePath: rel, from: cwd)
    }

    private static func locateHistoryPublisher() -> URL? {
        let rel = "scripts/publish_benchmark_history.py"
        let cwd = FileManager.default.currentDirectoryPath
        if FileManager.default.fileExists(atPath: cwd + "/" + rel) {
            return URL(fileURLWithPath: cwd + "/" + rel)
        }
        return CLIRuntime.findUpwards(relativePath: rel, from: cwd)
    }

    private static func captureHistorySourceSnapshot(publisher: URL, artifactDirectory: URL) throws {
        try FileManager.default.createDirectory(at: artifactDirectory, withIntermediateDirectories: true)
        let snapshot = artifactDirectory.appendingPathComponent("benchmark-source.json")
        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/usr/bin/env")
        process.arguments = [
            "python3", publisher.path, "snapshot", "--output", snapshot.path,
            "--crash-scope", "macos",
        ]
        let errorPipe = Pipe()
        process.standardError = errorPipe
        do { try process.run() } catch {
            throw CLIError("could not start benchmark provenance capture: \(error.localizedDescription)")
        }
        process.waitUntilExit()
        guard process.terminationStatus == 0 else {
            let detail = String(data: errorPipe.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8)?
                .trimmingCharacters(in: .whitespacesAndNewlines) ?? "unknown failure"
            throw CLIError("benchmark provenance capture failed: \(detail)")
        }
    }

    private static func prepareEngineHistoryEvidence(
        publisher: URL,
        artifactDirectory: URL,
        diagnostics: URL,
        outputs: URL,
        runID: String,
        label: String,
        publisherSubcommand: String
    ) throws {
        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/usr/bin/env")
        var arguments = [
            "python3", publisher.path, publisherSubcommand,
            "--artifact-dir", artifactDirectory.path,
            "--snapshot", artifactDirectory.appendingPathComponent("benchmark-source.json").path,
            "--platform", "macos",
            "--run-id", runID,
            "--results", artifactDirectory.appendingPathComponent("bench-results.json").path,
            "--diagnostics", diagnostics.path,
            "--output-dir", outputs.path,
            "--defer-record",
        ]
        if !label.isEmpty { arguments += ["--label", label] }
        process.arguments = arguments
        let outputPipe = Pipe()
        let errorPipe = Pipe()
        process.standardOutput = outputPipe
        process.standardError = errorPipe
        do { try process.run() } catch {
            throw CLIError("could not start benchmark history publication: \(error.localizedDescription)")
        }
        process.waitUntilExit()
        guard process.terminationStatus == 0 else {
            let detail = String(data: errorPipe.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8)?
                .trimmingCharacters(in: .whitespacesAndNewlines) ?? "unknown failure"
            // The publisher writes benchmark-evidence.json before invoking the
            // registry. Its stderr therefore contains the safe delayed-repair
            // command, which records that frozen manifest without rebuilding it.
            throw CLIError("benchmark passed but evidence validation failed: \(detail)")
        }
        if let published = String(data: outputPipe.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8)?
            .trimmingCharacters(in: .whitespacesAndNewlines), !published.isEmpty {
            note("benchmark evidence → \(published)")
        }
    }

    private static func recordEngineHistory(
        historyScript: URL,
        artifactDirectory: URL
    ) throws {
        guard FileManager.default.fileExists(atPath: historyScript.path) else {
            throw CLIError("benchmark history recorder is missing at \(historyScript.path)")
        }
        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/usr/bin/env")
        process.arguments = [
            "python3", historyScript.path, "record",
            "--artifact-dir", artifactDirectory.path,
        ]
        let outputPipe = Pipe()
        let errorPipe = Pipe()
        process.standardOutput = outputPipe
        process.standardError = errorPipe
        do { try process.run() } catch {
            throw CLIError("could not start benchmark history recording: \(error.localizedDescription)")
        }
        process.waitUntilExit()
        guard process.terminationStatus == 0 else {
            let detail = String(data: errorPipe.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8)?
                .trimmingCharacters(in: .whitespacesAndNewlines) ?? "unknown failure"
            throw CLIError(
                "benchmark passed but history publication failed: \(detail); repair: "
                + "python3 scripts/benchmark_history.py record --artifact-dir '\(artifactDirectory.path)'"
            )
        }
        if let published = String(data: outputPipe.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8)?
            .trimmingCharacters(in: .whitespacesAndNewlines), !published.isEmpty {
            note("benchmark history → \(published)")
        }
    }

    /// Composed canonical-depth verdicts for the delivery takes: the fast
    /// finalization evidence is rebuilt from this run's typed engine telemetry
    /// rows, the `.prosody` and `.delivery` gates come from the sidecar the
    /// analysis step just wrote, and every verdict is checked against the
    /// take's stored fast verdict (a composed verdict can never be better
    /// than the fast one it finalized with). Fail-closed: a missing row,
    /// missing sidecar verdict, or fail outcome fails the bench run.
    private struct ComposeEngineRow: Decodable {
        struct AnyObjectElement: Decodable {}
        let generationID: String?
        let finishReason: String?
        let usedStreaming: Bool?
        let notes: [String: String]?
        let audioQC: AudioQCReport?
        let chunkTimeline: [AnyObjectElement]?
    }

    private struct ComposedTakeVerdict: Codable {
        let generationID: String
        let deliveryWav: String
        let outcome: String
        let issues: [String]
        let prosodyEvidenceDigest: String
    }

    private struct ComposedQualityFile: Codable {
        let schemaVersion: Int
        let runID: String
        let depth: String
        let requiredGates: [String]
        let takes: [ComposedTakeVerdict]
    }

    private static func composeDeliveryCanonicalQuality(
        diagnostics: URL, outputs: URL, runID: String
    ) throws {
        let sidecarURL = diagnostics.appendingPathComponent("bench-prosody.json")
        struct SidecarEntry: Decodable {
            let generationID: String
            let deliveryWav: String
            let qualityGate: GenerationQualityComposition.ProsodySidecarGate
            let deliveryGate: GenerationQualityComposition.DeliverySidecarGate
        }
        let entries = try JSONDecoder().decode(
            [SidecarEntry].self, from: Data(contentsOf: sidecarURL)
        )
        guard !entries.isEmpty else {
            throw CLIError("composed quality: prosody sidecar has no delivery takes")
        }

        let rowsURL = diagnostics
            .appendingPathComponent("engine", isDirectory: true)
            .appendingPathComponent("generations.jsonl")
        guard let rowData = try? Data(contentsOf: rowsURL),
              let rowText = String(data: rowData, encoding: .utf8) else {
            throw CLIError("composed quality: engine telemetry rows not found at \(rowsURL.path)")
        }
        let decoder = JSONDecoder()
        var rowsByID: [String: ComposeEngineRow] = [:]
        for line in rowText.split(separator: "\n") where !line.isEmpty {
            guard let row = try? decoder.decode(ComposeEngineRow.self, from: Data(line.utf8)),
                  row.notes?["benchRunID"] == runID,
                  let id = row.generationID else { continue }
            rowsByID[id] = row
        }

        let policy = GenerationQualityReportProducer.canonicalPolicy(requiresLanguageASR: false)
        var verdicts: [ComposedTakeVerdict] = []
        var failures: [String] = []
        for entry in entries {
            guard let row = rowsByID[entry.generationID] else {
                throw CLIError("composed quality: no engine row for generation \(entry.generationID)")
            }
            guard let reasonRaw = row.finishReason,
                  let finishReason = GenerationFinishReason(rawValue: reasonRaw) else {
                throw CLIError("composed quality: row \(entry.generationID) has no typed finish reason")
            }
            guard let chunkCount = row.chunkTimeline?.count else {
                throw CLIError("composed quality: row \(entry.generationID) has no chunk timeline")
            }
            let notes = row.notes ?? [:]
            let hitTokenCap = finishReason == .maxTokens || notes.contains { key, value in
                (key == "generation_end_reason" || key.hasSuffix("_generation_end_reason"))
                    && value == "token_cap"
            }
            let wavURL = outputs.appendingPathComponent(entry.deliveryWav)
            guard let wavData = try? Data(contentsOf: wavURL) else {
                throw CLIError("composed quality: delivery output missing: \(entry.deliveryWav)")
            }
            let wavDigest = sha256(wavData)
            guard let generationID = UUID(uuidString: entry.generationID) else {
                throw CLIError("composed quality: invalid generation ID \(entry.generationID)")
            }
            let report = GenerationQualityReportProducer.deepReport(
                generationID: generationID,
                policy: policy,
                finishReason: finishReason,
                hitTokenCap: hitTokenCap,
                audioQC: row.audioQC,
                wavDigest: wavDigest,
                usedStreaming: row.usedStreaming ?? true,
                chunkCount: chunkCount,
                audioChannel: nil,
                deepEvidence: [
                    .prosody: GenerationQualityComposition.prosodyEvidence(
                        gate: entry.qualityGate, evidenceDigest: wavDigest
                    ),
                    .delivery: GenerationQualityComposition.deliveryEvidence(
                        gate: entry.deliveryGate, evidenceDigest: wavDigest
                    ),
                ]
            )
            let verdict: QualityGateRegistryVerdict
            do { verdict = try QualityGateRegistry.evaluate(report) } catch {
                throw CLIError("composed quality: registry rejected \(entry.generationID): \(error)")
            }
            // Fast-consistency guard: the row already carries the fast verdict
            // this take finalized with; composing must never improve on it.
            if let fastRaw = notes["quality_registry_outcome"],
               let fastOutcome = GenerationQualityOutcome(rawValue: fastRaw),
               GenerationQualityComposition.rank(of: verdict.outcome)
                   < GenerationQualityComposition.rank(of: fastOutcome) {
                throw CLIError(
                    "composed quality: verdict for \(entry.generationID) (\(verdict.outcome.rawValue)) "
                        + "is better than its stored fast verdict (\(fastRaw)); evidence reconstruction drifted"
                )
            }
            if verdict.outcome == .fail {
                failures.append("\(entry.deliveryWav): \(verdict.issues.joined(separator: ","))")
            }
            verdicts.append(ComposedTakeVerdict(
                generationID: entry.generationID,
                deliveryWav: entry.deliveryWav,
                outcome: verdict.outcome.rawValue,
                issues: verdict.issues,
                prosodyEvidenceDigest: wavDigest
            ))
        }

        let payload = ComposedQualityFile(
            schemaVersion: 1,
            runID: runID,
            depth: "canonical",
            requiredGates: QualityGateRegistry.requiredGates(for: policy).map(\.rawValue),
            takes: verdicts.sorted { $0.deliveryWav < $1.deliveryWav }
        )
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
        try encoder.encode(payload).write(
            to: diagnostics.appendingPathComponent("bench-quality-composed.json"),
            options: .atomic
        )
        let warned = verdicts.filter { $0.outcome == "warning" }.count
        note("composed canonical quality: \(verdicts.count) delivery take(s), \(warned) warning(s) → bench-quality-composed.json")
        if !failures.isEmpty {
            throw CLIError("composed canonical quality FAILED: \(failures.joined(separator: "; "))")
        }
    }

    /// Copy this run's WAVs plus the immutable manifest and analysis sidecars
    /// into an untracked per-run archive under `outputs/bench-archive/<runID>`.
    /// WAV and manifest copies are fail-closed (evidence retention is part of
    /// the run's success contract); the analysis sidecars are copied when they
    /// exist, because `--no-summary` parent lanes own their own artifacts.
    private static func archiveDeliveryEvidence(
        dataDir: URL,
        outputs: URL,
        diagnostics: URL,
        artifactDirectory: URL,
        takes: [BenchTakeResult],
        referenceFailures: [BenchReferenceFailure],
        deliveryFailures: [BenchDeliveryFailure],
        runID: String
    ) throws {
        let archive = dataDir
            .appendingPathComponent("outputs/bench-archive", isDirectory: true)
            .appendingPathComponent(runID, isDirectory: true)
        let fileManager = FileManager.default
        try fileManager.createDirectory(at: archive, withIntermediateDirectories: true)

        func copy(_ source: URL, required: Bool) throws {
            guard fileManager.fileExists(atPath: source.path) else {
                if required {
                    throw CLIError("evidence archive: missing required file \(source.lastPathComponent)")
                }
                return
            }
            let destination = archive.appendingPathComponent(source.lastPathComponent)
            if fileManager.fileExists(atPath: destination.path) {
                try fileManager.removeItem(at: destination)
            }
            try fileManager.copyItem(at: source, to: destination)
        }

        for take in takes {
            try copy(outputs.appendingPathComponent(take.outputFileName), required: true)
        }
        for failure in referenceFailures {
            if let fileName = failure.rejectedOutputFileName {
                try copy(outputs.appendingPathComponent(fileName), required: true)
            }
        }
        for failure in deliveryFailures {
            if let fileName = failure.rejectedOutputFileName {
                try copy(outputs.appendingPathComponent(fileName), required: true)
            }
        }
        try copy(artifactDirectory.appendingPathComponent("bench-results.json"), required: true)
        try copy(diagnostics.appendingPathComponent("bench-prosody.json"), required: false)
        try copy(diagnostics.appendingPathComponent("bench-quality-composed.json"), required: false)
        note("delivery evidence archived → \(archive.path)")
    }

    private static func locateDeliveryProsodyAnalyzer() -> URL? {
        let rel = "scripts/bench_delivery_prosody.py"
        let cwd = FileManager.default.currentDirectoryPath
        if FileManager.default.fileExists(atPath: cwd + "/" + rel) {
            return URL(fileURLWithPath: cwd + "/" + rel)
        }
        return CLIRuntime.findUpwards(relativePath: rel, from: cwd)
    }

    private static func runDeliveryProsodyAnalysis(
        script: URL,
        diagnostics: URL,
        resultsManifest: URL,
        profilePath: String?
    ) throws {
        note("prosody analysis for delivery cells →")
        let p = Process()
        p.executableURL = URL(fileURLWithPath: "/usr/bin/env")
        var pargs = [
            "python3", script.path, diagnostics.path,
            "--results-manifest", resultsManifest.path,
        ]
        if let profilePath, !profilePath.isEmpty {
            pargs += ["--prosody-profile", profilePath]
        }
        p.arguments = pargs
        do { try p.run() } catch {
            throw CLIError("could not start delivery prosody analysis: \(error.localizedDescription)")
        }
        p.waitUntilExit()
        guard p.terminationStatus == 0 else {
            throw CLIError("delivery prosody analysis failed")
        }
    }

    private static func canonicalForceClass(_ raw: String) throws -> String {
        switch raw.lowercased() {
        case "floor_8gb_mac", "8gb", "8": return "floor_8gb_mac"
        case "mid_16gb_mac", "16gb", "16": return "mid_16gb_mac"
        case "high_memory_mac", "high": return "high_memory_mac"
        case "iphone_pro", "iphone": return "iphone_pro"
        default:
            throw CLIError("invalid --force-class '\(raw)' (use 8gb | 16gb | high | iphone, or the canonical *_mac names)")
        }
    }

    private static func validatedBenchmarkLabel(_ raw: String?) throws -> String {
        guard let raw, !raw.isEmpty else { return "" }
        let range = NSRange(raw.startIndex..<raw.endIndex, in: raw)
        let expression = try NSRegularExpression(pattern: #"^[A-Za-z0-9][A-Za-z0-9._-]{0,95}$"#)
        guard expression.firstMatch(in: raw, range: range)?.range == range else {
            throw CLIError(
                "--label must be an opaque 1-96 character ID using letters, digits, dot, underscore, or hyphen"
            )
        }
        return raw
    }

    private static func memoryQualificationDeclaration(
        rawPolicy: String?,
        wasBareFlag: Bool,
        modes: [String],
        variants: [String],
        lengths: [String],
        warm: Int,
        seed: UInt64?,
        telemetryVerbose: Bool,
        noStream: Bool,
        hasDeliveryCells: Bool
    ) throws -> BenchMemoryQualification? {
        if wasBareFlag {
            throw CLIError("--memory-qualification requires retained-memory-v1")
        }
        guard let rawPolicy else { return nil }
        guard rawPolicy == "retained-memory-v1" else {
            throw CLIError("unsupported --memory-qualification policy '\(rawPolicy)' (use retained-memory-v1)")
        }
        guard modes == ["custom", "design", "clone"],
              variants == ["speed"],
              lengths == ["medium"],
              warm == 3,
              seed == 19_790_615,
              telemetryVerbose,
              !noStream,
              !hasDeliveryCells else {
            throw CLIError(
                "retained-memory-v1 requires --modes custom,design,clone "
                + "--variants speed --lengths medium --warm 3 --telemetry verbose "
                + "--seed 19790615 with streaming enabled and no delivery cells"
            )
        }
        return BenchMemoryQualification(
            policyID: rawPolicy,
            modeOrder: modes,
            variant: "speed",
            length: "medium",
            warmRepetitions: warm,
            // Custom and Design each contribute one cold take plus three warm
            // takes; Clone is warm-only by product contract.
            expectedTakeCount: 11
        )
    }

    /// Debug-isolated Application Support folder (models + diagnostics) without
    /// lighting TelemetryGate via `QWENVOICE_DEBUG`.
    private static func applicationSupportBaseDirectory() -> URL {
        FileManager.default
            .urls(for: .applicationSupportDirectory, in: .userDomainMask).first
            ?? URL(fileURLWithPath: (NSHomeDirectory() as NSString)
                .appendingPathComponent("Library/Application Support"), isDirectory: true)
    }

    /// Install a benchmark-only production-affecting override through the
    /// same explicit master gate used by the app. Reading the value back
    /// through `RuntimeDebugGate` prevents a silently inert benchmark setup.
    private static func installRuntimeDebugOverride(
        key: String,
        value: String
    ) throws {
        guard setenv("QWENVOICE_DEBUG", "1", 1) == 0,
              setenv(key, value, 1) == 0,
              RuntimeDebugGate.value(for: key) == value else {
            throw CLIError("failed to install the requested benchmark runtime override")
        }
    }

    /// The shipped app's real (non-debug) data dir — never auto-cleared.
    private static func realAppDataDir() -> URL {
        applicationSupportBaseDirectory().appendingPathComponent("QwenVoice", isDirectory: true)
    }

    /// Clear this run's diagnostics, but refuse to wipe the shipped app's real
    /// data dir unless --force (bench forces QWENVOICE_DEBUG=1 so the default
    /// resolves to QwenVoice-Debug; this guards an explicit --data-dir <real>).
    private static func clearDiagnosticsIfSafe(dataDir: URL, force: Bool) throws {
        if !LocalBenchmarkDataPolicy.mayClearDiagnostics(
            in: dataDir,
            productionDataDirectory: realAppDataDir(),
            force: force
        ) {
            throw CLIError("refusing to clear diagnostics in the real app data dir (\(dataDir.path)); pass --keep to append or --force to override")
        }
        // Start clean so the aggregate reflects only this run.
        try? FileManager.default.removeItem(at: dataDir.appendingPathComponent("diagnostics", isDirectory: true))
    }

    struct TTFCRow: Encodable {
        let mode: String
        let variant: String
        let modelID: String
        let firstChunkMS: Double?
    }

    /// Fail fast if any requested (mode × variant) model isn't installed — so a
    /// missing model is reported up front, not after part of the matrix has run.
    @MainActor
    private static func preflightModels(runtime: CLIRuntime, modes: [String], variants: [String], dataDir: URL) throws {
        let modelsDir = dataDir.appendingPathComponent("models", isDirectory: true)
        var missing: [String] = []
        for modeStr in modes {
            guard let mode = GenerationMode(rawValue: modeStr) else {
                throw CLIError("invalid --modes value '\(modeStr)'")
            }
            for variantStr in variants {
                let quality = variantStr.lowercased() == "quality"
                let id = try runtime.modelID(mode: mode, quality: quality)
                if case .available = runtime.registry.availability(forModelID: id, in: modelsDir) { continue }
                missing.append(id)
            }
        }
        guard missing.isEmpty else {
            let uniq = Array(Set(missing)).sorted().joined(separator: ", ")
            throw CLIError("preflight: missing models — \(uniq). Install them in the app (Settings → Model downloads), or point --data-dir at a populated models dir.")
        }
    }

    /// Print the engine first-chunk-latency table (stderr) + write a sidecar JSON.
    private static func reportTTFC(_ rows: [TTFCRow], diagnostics: URL) {
        guard !rows.isEmpty else { return }
        FileHandle.standardError.write(Data(
            "\nEngine first-chunk latency (TTFC, ms) — warm streaming probe (engine-side, not app/XPC playback-scheduled latency)\n".utf8))
        for r in rows {
            let ms = r.firstChunkMS.map { String(format: "%.0f", $0) } ?? "-"
            FileHandle.standardError.write(Data("  \(r.mode)/\(r.variant)\t\(ms)\n".utf8))
        }
        let enc = JSONEncoder()
        enc.outputFormatting = [.prettyPrinted, .sortedKeys]
        if let data = try? enc.encode(rows) {
            try? FileManager.default.createDirectory(at: diagnostics, withIntermediateDirectories: true)
            let url = diagnostics.appendingPathComponent("bench-ttfc.json")
            try? data.write(to: url)
            note("wrote \(url.path)")
        }
    }

    private static func parseList(_ s: String?) -> [String]? {
        guard let s, !s.isEmpty else { return nil }
        return s.split(separator: ",").map { $0.trimmingCharacters(in: .whitespaces).lowercased() }.filter { !$0.isEmpty }
    }

    private static func parseMatrixAxis(
        _ raw: String?,
        option: String,
        wasBareFlag: Bool,
        defaults: [String],
        allowed: [String]
    ) throws -> [String] {
        guard !wasBareFlag else {
            throw CLIError("invalid --\(option): a comma-list value is required")
        }
        guard let raw else { return defaults }
        let values = raw
            .split(separator: ",", omittingEmptySubsequences: false)
            .map { $0.trimmingCharacters(in: .whitespacesAndNewlines).lowercased() }
        let allowedSet = Set(allowed)
        let invalid = values.filter { $0.isEmpty || !allowedSet.contains($0) }
        guard invalid.isEmpty else {
            let rendered = invalid.map { $0.isEmpty ? "<empty>" : $0 }.joined(separator: ", ")
            throw CLIError(
                "invalid --\(option) value(s): \(rendered) (use \(allowed.joined(separator: ",")))"
            )
        }
        guard Set(values).count == values.count else {
            throw CLIError("invalid --\(option): duplicate values are not allowed")
        }
        return values
    }

    static func printHelp() {
        print("""
        vocello bench — drive the perf/quality matrix headlessly + aggregate

        Usage:
          vocello bench [--modes custom,design,clone] [--variants speed,quality] \\
                        [--lengths short,medium,long] [--warm 3] [options]

        Per cell: 1 cold (medium) for Custom/Design + N warm per length; Voice
        Cloning is warm-only. Telemetry defaults to verbose so schema-v2 history
        can bind exact raw memory sidecars; use --telemetry off for engine-only
        WAV runs without instrumentation.
        Raw telemetry lands in <data>/diagnostics; each run's immutable manifest
        and publication evidence land in diagnostics/benchmark-runs/<runID>.
        Repository summary/history tools run unless telemetry is off or the CLI is
        outside a Vocello checkout; local WAVs and bench-results.json are retained.

        Measures engine truth — RTF / decode / memory / audioQC. It does NOT capture
        the app's end-to-end through-XPC submit-to-first-chunk or
        playback-scheduled latency, or the merged 3-layer row
        (use the app for those); --ttfc adds an engine-side first-chunk probe.
        Prerequisites: the requested models installed; saved clone voice
        '\(defaultCloneVoice)' when clone is in --modes.

        Options:
          --modes        strict comma list: custom,design,clone (default all)
          --variants     strict comma list: speed,quality (default both)
          --lengths      strict comma list: short,medium,long (default all)
                         Empty, unknown, and duplicate axis values fail.
          --warm         warm reps per (cell × length); default 3. Zero is
                         allowed for a Custom/Design cold-only diagnostic;
                         Clone and --delivery require at least one warm take.
          --voice        (clone) saved voice name; default \(defaultCloneVoice)
          --speaker      (custom) exact Built-in Voice speaker id; default contract speaker
                         (discover with `vocello speakers list`)
          --voice-brief  (design) brief; default the standard narrator brief
          --delivery [list]  add instruct-bearing cells (Custom/Design, warm, medium
                         text, 1 take each): comma list of <preset>[.<intensity>]
                         (e.g. happy.strong,calm.normal); bare flag runs the
                         default set (\(defaultDeliverySet.joined(separator: ","))).
                         Intensity values use normal | strong; a bare preset
                         defaults to strong.
                         Rows are stamped notes.delivery and summarized in their
                         own block so the headline matrix stays comparable; the
                         plain warm takes double as the neutral reference. Also
                         triggers a numpy-only prosody analysis (pitch dynamics,
                         rate variability, pauses, energy roughness) vs the paired
                         neutral take. Only WAVs in the current run manifest are
                         analyzed before aggregation, so results appear in the
                         final delivery table without stale --keep contamination.
                         Every delivery run's WAVs, manifest, and sidecars are
                         also archived under outputs/bench-archive/<runID> so a
                         multi-seed sweep can never overwrite its own evidence.
          --prosody-profile <path>
                         use a calibrated prosody profile for the delivery analysis
                         (default: built-in profile)
          --continue-delivery-failures
                         with --delivery and --no-summary, retain typed failed
                         neutral references and delivery cells, then continue;
                         diagnostic only, never eligible for history publication
          --label <id>   opaque 1-96 character run label using letters, digits, ._- only
          --force-class  run a constrained tier on any Mac: 8gb|16gb|high|iphone
          --telemetry    off | lightweight | verbose (default; raw memory sidecars)
          --memory-qualification retained-memory-v1
                         require the fixed 11-take Custom → Design → Clone Speed
                         retained-memory protocol and strict verbose evidence
          --seed         deterministic sampling seed applied to every take
          --no-stream    accumulate the full result before decoding (old bench behavior)
          --ttfc         add an engine first-chunk-latency probe per cell (warm
                         streaming) → table + diagnostics/bench-ttfc.json
          --data-dir     runtime dir; default the debug-isolated folder (full model set)
          --manifest     override path to qwenvoice_contract.json
          --keep         append to existing diagnostics (default: clear first)
          --force        allow clearing even the real (non-debug) app data dir
          --no-summary   skip the aggregator and registry; parent diagnostic lane owns publication
          --quiet|--verbose   suppress / expand stderr progress notes
        """)
    }
}
