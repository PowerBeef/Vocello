import CryptoKit
import Foundation
import QwenVoiceCore
import Synchronization
import VocelloDesktopCore

/// `vocello generate` — synthesize one clip headlessly via the in-process engine.
public enum GenerateCommand {
    /// Machine-readable result emitted under `--json`.
    public struct GenerateJSON: Encodable, Sendable {
        let generationID: String
        let audioPath: String
        let durationSeconds: Double
        let wallSeconds: Double
        /// Standard real-time factor: `wallSeconds ÷ durationSeconds`, lower is
        /// faster, below 1.0 is faster than real time.
        let realtimeFactor: Double
        /// Audio seconds produced per wall second (the inverse of `realtimeFactor`).
        let realtimeSpeedup: Double
        let finishReason: String?
        let mode: String
        let variant: String
        let modelID: String
        /// Where the variant came from: `flag` (--variant) or `app` (the package the
        /// Mac app would use for the mode).
        let variantSource: String
        /// The take's effective seed as a decimal string; passing it back as
        /// --seed reproduces the take. `completionReceipt` is the engine's own
        /// receipt and keeps its numeric fields.
        let seed: String?
        let deliveryInstructionChars: Int?
        let deliveryInstructionDigest: String?
        let deliveryInstructionLanguage: String?
        let modelFacingInstructionLanguage: String?
        let deliveryInstructionCellID: String?
        let requestReceiptSchemaVersion: Int?
        let storedLanguageSelection: String?
        let detectedTargetLanguage: String?
        let referenceTranscriptLanguage: String?
        let finalModelLanguage: String?
        let languageTokenMode: String?
        let conditioningMode: String?
        let targetTextDigest: String?
        let targetTextCharacters: Int?
        let referenceTranscriptDigest: String?
        let referenceTranscriptCharacters: Int?
        let referenceAudioDigest: String?
        let modelArtifactVersion: String?
        let modelIntegrityManifestDigest: String?
        let speechTokenizerDigest: String?
        let completionReceipt: GenerationCompletionReceipt?
        let audioQC: AudioQCReport?
        let firstChunkMS: Double?
        let chunks: Int?
    }

    /// What a `--stream` run observes off `engine.events`.
    struct StreamObservation: Sendable {
        let firstChunkMS: Double?
        /// The observer's mach uptime (`DispatchTime`) when it saw the first
        /// chunk: the clock the engine stamps the v9 chunk-0
        /// `transportPublishedAtNS` hand-off on (with or without preview PCM,
        /// which the bench turns off), so the publisher can measure this
        /// observer's lag behind the hand-off (`ttfcObserverLagMS`, audit #48).
        let firstChunkUptimeNS: UInt64?
        let chunkCount: Int
        /// The typed reason of a `.cancelled` terminal (P15-02).
        var cancellationReason: GenerationCancellationReason?
    }

    /// Run a request, and when it's streaming, drain `engine.events` on a side task
    /// to record the engine first-chunk latency (TTFC, ms) and chunk count. Consumes
    /// through the terminal event so the bounded macOS stream isn't left with buffered
    /// events; does NOT render chunks (no live playback). Shared by `generate --stream`
    /// and the `bench --ttfc` probe.
    @MainActor
    public static func generateObservingFirstChunk(
        _ runtime: CLIRuntime, _ request: GenerationRequest
    ) async throws -> (
        result: GenerationResult, firstChunkMS: Double?, chunkCount: Int?, firstChunkUptimeNS: UInt64?
    ) {
        // Refuse before subscribing: a refused request never reaches the engine, so
        // its event stream would never deliver the terminal event the drain awaits.
        try runtime.voiceCloningConsent.admitGeneration(request)
        let submitted = ContinuousClock.now
        let wantedID = request.generationID
        let streamTask: Task<StreamObservation, Never>? = request.shouldStream && wantedID != nil ? {
            let events = runtime.engine.events(for: wantedID!)
            return Task.detached(priority: .utility) { @concurrent in
                var firstChunkMS: Double?
                var firstChunkUptimeNS: UInt64?
                var count = 0
                for await event in events {
                    switch event {
                    case .chunk:
                        if firstChunkMS == nil {
                            // ttfcMS reads its clock first, so the added
                            // uptime read never lengthens it.
                            firstChunkMS = submitted.elapsedSeconds * 1000
                            firstChunkUptimeNS = DispatchTime.now().uptimeNanoseconds
                        }
                        count += 1
                        // Coalesced by the writer; never blocks the drain.
                        CLIPresenter.event(.chunk, generationID: wantedID, data: ["chunks": .integer(count)])
                    case .cancelled(let summary):
                        return StreamObservation(
                            firstChunkMS: firstChunkMS,
                            firstChunkUptimeNS: firstChunkUptimeNS,
                            chunkCount: count,
                            cancellationReason: summary.reason
                        )
                    case .completed, .failed:
                        return StreamObservation(
                            firstChunkMS: firstChunkMS,
                            firstChunkUptimeNS: firstChunkUptimeNS,
                            chunkCount: count
                        )
                    default:
                        continue
                    }
                }
                return StreamObservation(
                    firstChunkMS: firstChunkMS,
                    firstChunkUptimeNS: firstChunkUptimeNS,
                    chunkCount: count
                )
            }
        }() : nil

        let result: GenerationResult
        do {
            result = try await runtime.generate(request)
        } catch {
            let observation = await streamTask?.value
            // P15-02: the take's own `.cancelled` event names the engine's reason.
            let classified = CLIEngineCancellation.classify(
                error,
                commandCancelled: Task.isCancelled,
                observedReason: observation?.cancellationReason
            )
            if classified is CancellationError {
                CLIPresenter.event(.generationCancelled, generationID: wantedID)
            } else {
                CLIPresenter.event(.generationFailed, generationID: wantedID, data: [
                    "code": .string(CLIFailure.rowCode(for: classified).rawValue),
                ])
            }
            throw classified
        }
        var firstChunkMS: Double?
        var chunkCount: Int?
        var firstChunkUptimeNS: UInt64?
        if let streamTask {
            let obs = await streamTask.value
            firstChunkMS = obs.firstChunkMS
            chunkCount = obs.chunkCount
            firstChunkUptimeNS = obs.firstChunkUptimeNS
        }
        return (result, firstChunkMS, chunkCount, firstChunkUptimeNS)
    }

    /// The resolved plan of one take, reported by `--plan` without a model load.
    struct GeneratePlan: Encodable, Sendable {
        let mode: String
        let variant: String
        let variantSource: String
        let modelID: String
        let modelInstalled: Bool
        let language: String
        let seed: String?
        let variation: String
        let characters: Int
        let streaming: Bool
        let outputPath: String
    }

    /// One take, validated and resolved before any engine work: everything
    /// `--plan` reports and `execute` needs.
    public struct PreparedTake: Sendable {
        let args: Args
        let text: String
        let mode: GenerationMode
        public let consent: VoiceCloningConsentPolicy
        let language: Qwen3SupportedLanguage?
        let seed: UInt64?
        let variation: Qwen3SamplingVariation?
        let appDelivery: Bool
        let deliveryInstructionCellID: String?
        let variant: VariantChoice
        let generationID: UUID
        let output: OutputDestination
        let streaming: Bool
        public let dataDirectory: URL
        public let manifestOverride: URL?
        let registry: ContractBackedModelRegistry
        let modelsDirectory: URL

        var quality: Bool { variant.quality }
    }

    /// Validates `args` and resolves the take without an engine. `interactive`
    /// allows the mode picker (never for a request an agent sent).
    @MainActor
    public static func prepare(_ args: Args, interactive: Bool) async throws -> PreparedTake {
        let explicitQuality = try parseVariantFlag(args)
        let streaming = !args.flag("no-stream")

        // Resolve text first so a missing-text run fails fast (before any prompt).
        let text = try resolveText(args)
        try validateSingleTakeText(text)

        // Mode: explicit --mode wins; else prompt interactively at a terminal; else
        // default to custom (keeps scripted/piped runs unchanged).
        let mode = interactive ? try await resolveModeInteractive(args) : try resolveMode(args)
        // PA-17: clone needs this invocation's recorded consent; refuse before boot.
        let consent = try CLIVoiceCloningConsent.policy(from: args)
        try consent.admitGeneration(mode: mode)
        // Every option is checked before boot, so a bad value never costs a model load.
        let language = try parseLanguage(args)
        let seed = try parseSeed(args)
        let settings = DesktopAppSettings()
        let variation = try parseVariation(args) ?? appVariation(settings)
        let appDelivery = try parseAppDelivery(args)
        try validatePayloadOptions(args, mode: mode)
        let deliveryInstructionCellID = try resolveDeliveryInstructionCellID(args, mode: mode)

        let dataDir = CLIPaths.dataDirectory(override: args.string("data-dir"))
        let manifestOverride = args.string("manifest").map {
            URL(fileURLWithPath: ($0 as NSString).expandingTildeInPath)
        }
        let registryContext = try CLIRuntime.bootstrapRegistryOnly(dataDirectory: dataDir, manifestOverride: manifestOverride)
        let variant = resolveVariant(
            explicitQuality: explicitQuality, mode: mode, registry: registryContext.registry,
            modelsDirectory: registryContext.modelsDirectory, settings: settings
        )
        // The take's identity names its default output, so the path and the
        // JSON `generationID` agree and no two runs share a file (U28).
        let generationID = UUID()
        let output = try resolveOutputDestination(args, dataDir: dataDir, mode: mode, generationID: generationID)
        return PreparedTake(
            args: args, text: text, mode: mode, consent: consent, language: language, seed: seed,
            variation: variation, appDelivery: appDelivery, deliveryInstructionCellID: deliveryInstructionCellID,
            variant: variant, generationID: generationID, output: output, streaming: streaming,
            dataDirectory: dataDir, manifestOverride: manifestOverride, registry: registryContext.registry,
            modelsDirectory: registryContext.modelsDirectory
        )
    }

    /// What a request's identity leaves out: how it reports, not what it asks for.
    static let identityExclusions: Set<String> = [
        "client-request-id", "json", "ndjson", "output-format", "quiet", "verbose", "no-input", "play", "plan",
    ]

    /// What `--plan` reports for a prepared take.
    static func plan(_ take: PreparedTake) throws -> GeneratePlan {
        let modelID = try CLIRuntime.modelID(registry: take.registry, mode: take.mode, quality: take.quality)
        return GeneratePlan(
            mode: take.mode.rawValue, variant: take.quality ? "quality" : "speed", variantSource: take.variant.source,
            modelID: modelID,
            modelInstalled: take.registry.model(id: modelID)
                .map { DesktopModelInventory.isComplete($0, modelsDirectory: take.modelsDirectory) } ?? false,
            language: (take.language ?? .auto).rawValue, seed: take.seed.map { String($0) },
            variation: (take.variation ?? .expressive).rawValue, characters: take.text.count, streaming: take.streaming,
            outputPath: take.output.path
        )
    }

    @MainActor
    public static func run(_ args: Args) async throws {
        let take = try await prepare(args, interactive: true)
        if args.flag("plan") {
            let plan = try plan(take)
            if CLIPresenter.isMachine {
                CLIPresenter.succeed(plan)
            } else {
                print("\(plan.mode) · \(plan.modelID) (\(plan.variantSource)) · \(plan.language) · \(plan.variation)"
                    + " · \(plan.characters) characters\(plan.modelInstalled ? "" : " · model not installed")")
                print(plan.outputPath)
            }
            return
        }

        // Idempotency: a repeated client request id replays its stored result.
        var reservation: CLIRequestLedger.Reservation?
        let ledger = CLIRequestLedger(dataDirectory: take.dataDirectory)
        if let id = args.string("client-request-id") {
            let identity = args.canonicalForm(excluding: Self.identityExclusions)
            switch try ledger.claim(id: id, request: identity) {
            case .replay(let stored):
                CLIPresenter.markReplayed()
                if CLIPresenter.isMachine {
                    CLIPresenter.succeed(stored)
                } else if case .object(let fields) = stored, case .string(let path)? = fields["audioPath"] {
                    print(path)
                }
                return
            case .conflict:
                throw CLIError(
                    .idempotencyConflict, "client request id '\(id)' was used for a different request",
                    hint: "use a new id for a new request"
                )
            case .inProgress:
                throw CLIError(.requestInProgress, "client request id '\(id)' is running in another process")
            case .fresh(let held):
                reservation = held
            }
        }

        let result: GenerateJSON
        do {
            note("booting engine (data: \(take.dataDirectory.path))")
            CLIPresenter.event(.engineBooting)
            let runtime = try await CLIRuntime.bootstrap(
                dataDirectory: take.dataDirectory, manifestOverride: take.manifestOverride, voiceCloningConsent: take.consent, hostedLikeTheApp: true)
            CLIPresenter.event(.engineReady)
            result = try await execute(take, runtime: runtime)
        } catch {
            if let reservation { ledger.abandon(reservation) }
            throw error
        }
        if let reservation { ledger.complete(reservation, result: try CLIJSONValue(encoding: result)) }
        if !CLIPresenter.isMachine {
            // stdout = machine-readable (the path). stderr = human notes.
            print(result.audioPath)
        }
        if args.flag("play") { try await CLIPlayback.play([result.audioPath]) }
        // Reported after any playback, so an interrupted --play never follows a success.
        if CLIPresenter.isMachine { CLIPresenter.succeed(result) }
    }

    /// Runs one prepared take on `runtime`: payload, model load, generation, the
    /// CM-7 publication check and its events. Prints nothing on stdout.
    @MainActor
    public static func execute(_ take: PreparedTake, runtime: CLIRuntime) async throws -> GenerateJSON {
        let args = take.args
        let mode = take.mode
        let quality = take.quality
        let text = take.text
        let streaming = take.streaming
        let generationID = take.generationID
        let output = take.output
        try prepareOutputFolder(of: output.path)
        if output.replacesExistingFile {
            note("--out names an existing file: a successful take replaces it")
        }
        let runtime = runtime.withConsent(take.consent)
        let modelID = try runtime.modelID(mode: mode, quality: quality)
        let built = try await buildPayload(args, mode: mode, runtime: runtime)
        let payload = take.appDelivery ? CLIBatchExecution.applyingAppDefaultDelivery(to: built) : built

        note("loading \(modelID)…")
        CLIPresenter.event(.modelLoading, data: ["modelID": .string(modelID)])
        try await runtime.loadModel(id: modelID)
        CLIPresenter.event(.modelLoaded, data: ["modelID": .string(modelID)])

        let request = GenerationRequest(
            mode: mode, modelID: modelID, text: text, outputPath: output.path,
            shouldStream: streaming,
            // Match the app's interactive streaming cadence so --stream exercises
            // the same engine chunk path the UI uses (CustomVoiceCoordinator et al.).
            streamingInterval: streaming ? GenerationSemantics.appStreamingInterval : nil,
            languageHint: take.language?.rawValue,
            payload: payload, generationID: generationID,
            seed: take.seed,
            variation: take.variation,
            deliveryInstructionCellID: take.deliveryInstructionCellID)
        note("generating (\(text.count) chars)\(streaming ? ", streaming" : "")…")
        CLIPresenter.event(.generationStarted, generationID: generationID, data: [
            "mode": .string(mode.rawValue), "modelID": .string(modelID), "characters": .integer(text.count),
        ])
        let started = ContinuousClock.now
        let (result, firstChunkMS, chunkCount, _) = try await generateObservingFirstChunk(runtime, request)
        let wall = started.elapsedSeconds

        // Fail closed on the CM-7 shape: success must never be claimed for a
        // path with no file behind it. The engine publishing contract is
        // verified here at the product boundary, not trusted.
        guard FileManager.default.fileExists(atPath: result.audioPath) else {
            throw CLIError(
                .outputMissing,
                "engine reported success but no audio file exists at \(result.audioPath); refusing to claim success (CM-7 guard)"
            )
        }
        CLIPresenter.event(.outputPublished, generationID: generationID, data: ["audioPath": .string(result.audioPath)])
        CLIPresenter.event(.generationCompleted, generationID: generationID, data: [
            "durationSeconds": .number(result.durationSeconds),
            "finishReason": result.finishReason.map { .string($0.rawValue) } ?? .null,
        ])

        let rtf = result.durationSeconds > 0 ? wall / result.durationSeconds : 0
        let speedup = wall > 0 ? result.durationSeconds / wall : 0
        do {
            let deliveryInstruction = payload.deliveryInstructionText?
                .trimmingCharacters(in: .whitespacesAndNewlines)
            let deliveryInstructionChars = deliveryInstruction.flatMap { $0.isEmpty ? nil : $0.count }
            let fallbackDigest = deliveryInstruction.flatMap { instruction in
                instruction.isEmpty ? nil : Self.sha256(Data(instruction.utf8))
            }
            let deliveryInstructionDigest = result.diagnosticStringFlags[
                "delivery_instruction_digest"
            ] ?? fallbackDigest
            let report = GenerateJSON(
                generationID: generationID.uuidString.lowercased(),
                audioPath: result.audioPath, durationSeconds: result.durationSeconds,
                wallSeconds: wall, realtimeFactor: rtf, realtimeSpeedup: speedup,
                finishReason: result.finishReason?.rawValue,
                mode: mode.rawValue, variant: quality ? "quality" : "speed",
                modelID: modelID,
                variantSource: take.variant.source,
                seed: result.completionReceipt.map { String($0.request.seed) },
                deliveryInstructionChars: deliveryInstructionChars,
                deliveryInstructionDigest: deliveryInstructionDigest,
                deliveryInstructionLanguage: result.diagnosticStringFlags[
                    "delivery_instruction_language"
                ],
                modelFacingInstructionLanguage: result.diagnosticStringFlags[
                    "request_receipt_model_facing_instruction_language"
                ],
                deliveryInstructionCellID: result.diagnosticStringFlags[
                    "delivery_instruction_cell_id"
                ],
                requestReceiptSchemaVersion: result.diagnosticStringFlags[
                    "request_receipt_schema_version"
                ].flatMap(Int.init),
                storedLanguageSelection: result.diagnosticStringFlags[
                    "request_receipt_stored_language_selection"
                ],
                detectedTargetLanguage: result.diagnosticStringFlags[
                    "request_receipt_detected_target_language"
                ],
                referenceTranscriptLanguage: result.diagnosticStringFlags[
                    "request_receipt_reference_transcript_language"
                ],
                finalModelLanguage: result.diagnosticStringFlags[
                    "request_receipt_final_model_language"
                ],
                languageTokenMode: result.diagnosticStringFlags[
                    "request_receipt_language_token_mode"
                ],
                conditioningMode: result.diagnosticStringFlags[
                    "request_receipt_conditioning_mode"
                ],
                targetTextDigest: result.diagnosticStringFlags[
                    "request_receipt_target_text_digest"
                ],
                targetTextCharacters: result.diagnosticStringFlags[
                    "request_receipt_target_text_characters"
                ].flatMap(Int.init),
                referenceTranscriptDigest: result.diagnosticStringFlags[
                    "request_receipt_reference_transcript_digest"
                ],
                referenceTranscriptCharacters: result.diagnosticStringFlags[
                    "request_receipt_reference_transcript_characters"
                ].flatMap(Int.init),
                referenceAudioDigest: result.diagnosticStringFlags[
                    "request_receipt_reference_audio_digest"
                ],
                modelArtifactVersion: result.diagnosticStringFlags[
                    "request_receipt_model_artifact_version"
                ],
                modelIntegrityManifestDigest: result.diagnosticStringFlags[
                    "request_receipt_model_integrity_manifest_digest"
                ],
                speechTokenizerDigest: result.diagnosticStringFlags[
                    "request_receipt_speech_tokenizer_digest"
                ],
                completionReceipt: result.completionReceipt,
                audioQC: result.audioQC,
                firstChunkMS: firstChunkMS, chunks: chunkCount)
            let ttfc = firstChunkMS.map { unsafe " · ttfc=\(String(format: "%.0f", $0))ms" } ?? ""
            let chunks = chunkCount.map { " · chunks=\($0)" } ?? ""
            note(unsafe "✓ \(String(format: "%.2f", result.durationSeconds))s audio · rtf=\(String(format: "%.2f", rtf)) (\(String(format: "%.2f", speedup))× realtime)\(ttfc)\(chunks) · finish=\(result.finishReason?.rawValue ?? "?")")
            return report
        }
    }

    private static func sha256(_ data: Data) -> String {
        SHA256.hash(data: data).map { unsafe String(format: "%02x", $0) }.joined()
    }

    // MARK: - Reusable request building (shared with `batch`)

    /// `--seed N` — deterministic sampling: the same request + seed
    /// reproduces the same take (GitHub #47/#30).
    public static func parseSeed(_ args: Args) throws -> UInt64? {
        guard let raw = args.string("seed") else { return nil }
        guard let seed = UInt64(raw) else {
            throw CLIError(.invalidInput, "invalid --seed '\(raw)' (use an unsigned integer)")
        }
        return seed
    }

    /// `--variation expressive|balanced|consistent` — talker sampling
    /// shaping (default expressive = official checkpoint sampling).
    public static func parseVariation(_ args: Args) throws -> Qwen3SamplingVariation? {
        guard let raw = args.string("variation") else { return nil }
        guard let variation = Qwen3SamplingVariation(rawValue: raw.lowercased()) else {
            throw CLIError(.invalidInput, "invalid --variation '\(raw)' (use expressive | balanced | consistent)")
        }
        return variation
    }

    /// `--language` (P15-07, P02-09): a Qwen3 language name or code in any case,
    /// with a region or script subtag dropped (`ja-JP` is Japanese, `zh-Hant`
    /// Chinese), or `auto`. Anything else is refused before boot, because the
    /// engine would read it as Auto and pick a language from the script. `nil`
    /// when omitted (Auto); otherwise the canonical name the apps send.
    public static func parseLanguage(_ args: Args) throws -> Qwen3SupportedLanguage? {
        // The parser refuses a bare --language before this runs.
        guard let raw = args.string("language") else { return nil }
        guard let language = Self.language(named: raw.trimmingCharacters(in: .whitespacesAndNewlines)) else {
            throw invalidLanguage(raw)
        }
        return language
    }

    private static func language(named token: String) -> Qwen3SupportedLanguage? {
        let lowered = token.lowercased()
        if lowered == "auto" || lowered == "automatic" { return .auto }
        let normalized = Qwen3SupportedLanguage.normalized(token)
        if normalized != .auto { return normalized }
        let primary = lowered.split(whereSeparator: { $0 == "-" || $0 == "_" }).first.map(String.init) ?? ""
        guard !primary.isEmpty, primary != lowered else { return nil }
        let fromPrimary = Qwen3SupportedLanguage.normalized(primary)
        return fromPrimary == .auto ? nil : fromPrimary
    }

    private static func invalidLanguage(_ raw: String) -> CLIError {
        let accepted = Qwen3SupportedLanguage.allCases.map(\.rawValue).joined(separator: " | ")
        return CLIError(.invalidInput, "invalid --language '\(raw)' (use \(accepted), or a code such as en, fr or ja-JP)")
    }

    /// `--app-delivery` (P15-06): with no --delivery or --delivery-cell, send the
    /// apps' default delivery, as batch does. A bare flag; the parser refuses a value.
    public static func parseAppDelivery(_ args: Args) throws -> Bool {
        args.flag("app-delivery")
    }

    /// The payload options that need no engine, checked before boot by
    /// `generate` and again by `buildPayload` (which `batch` runs).
    public static func validatePayloadOptions(_ args: Args, mode: GenerationMode) throws {
        switch mode {
        case .custom:
            _ = try explicitSpeaker(args)
        case .design:
            break
        case .clone:
            // Clone has no instruction channel: a delivery would be dropped unseen.
            if args.string("delivery") != nil {
                throw CLIError(.invalidInput, "--delivery is not available in clone mode (the reference voice sets the delivery)")
            }
        }
    }

    /// `--speaker` (P15-08): `nil` when omitted (the contract default). An empty
    /// or blank value, such as an unset shell variable, is refused: sent as is,
    /// it would run the take with no speaker conditioning at all.
    static func explicitSpeaker(_ args: Args) throws -> String? {
        // The parser refuses a bare --speaker before this runs.
        guard let raw = args.string("speaker") else { return nil }
        let speaker = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !speaker.isEmpty else { throw emptySpeaker }
        return speaker
    }

    private static var emptySpeaker: CLIError {
        CLIError(.invalidInput, "empty --speaker: pass a speaker id (see `vocello speakers list`), or omit it for the default speaker")
    }

    /// Validate a mode string into a `GenerationMode`.
    public static func parseModeString(_ s: String) throws -> GenerationMode {
        guard let mode = GenerationMode(rawValue: s.lowercased()) else {
            throw CLIError(.invalidInput, "invalid --mode '\(s)' (use custom | design | clone)")
        }
        return mode
    }

    /// Mode for non-interactive callers (`batch`, the subcommand path): the `--mode`
    /// flag or the `custom` default — never prompts.
    public static func resolveMode(_ args: Args) throws -> GenerationMode {
        try parseModeString(args.string("mode") ?? "custom")
    }

    /// Mode for `generate`: an explicit `--mode` wins; otherwise prompt when a person
    /// is at a terminal (text output, no --no-input); otherwise default to `custom`.
    @concurrent static func resolveModeInteractive(_ args: Args) async throws -> GenerationMode {
        if let explicit = args.string("mode") { return try parseModeString(explicit) }
        if CLIOutput.promptsAllowed { return try await promptForMode() }
        return .custom
    }

    /// Numbered menu on stderr; reads a choice (number or name) from stdin. Falls
    /// back to `custom` on EOF/blank after a few tries. A Ctrl-C at the prompt
    /// ends the command at once (P15-10).
    @concurrent static func promptForMode(
        readLine read: @escaping @Sendable () -> String? = { Swift.readLine(strippingNewline: true) }
    ) async throws -> GenerationMode {
        let modes = GenerationMode.allCases
        for _ in 0..<3 {
            CLIStandardError.write("Select a mode:\n")
            for (i, m) in modes.enumerated() {
                CLIStandardError.write("  \(i + 1)) \(m.rawValue)\t\(ModesCommand.info(for: m).summary)\n")
            }
            CLIStandardError.write("> ")
            guard let line = try await readLineCancellably(read)?.trimmingCharacters(in: .whitespaces),
                  !line.isEmpty else { break }
            if let n = Int(line), n >= 1, n <= modes.count { return modes[n - 1] }
            if let m = GenerationMode(rawValue: line.lowercased()) { return m }
            CLIStandardError.write("  ? not a valid choice\n")
        }
        CLIStandardError.write("• defaulting to custom\n")
        return .custom
    }

    /// One line from `read`, raced against the command's cancellation (P15-10).
    /// Once the supervisor owns SIGINT the signal is ignored at the process level,
    /// so a blocking read on the main actor would hold a Ctrl-C until the 30 s
    /// forced exit. The read runs on its own thread instead; a cancellation ends
    /// the wait at once with `CancellationError`, and the abandoned thread ends
    /// with the process.
    @concurrent static func readLineCancellably(_ read: @escaping @Sendable () -> String?) async throws -> String? {
        let gate = CLICancellableLineRead()
        return try await withTaskCancellationHandler { @concurrent in
            try await withCheckedThrowingContinuation { (continuation: CheckedContinuation<String?, any Error>) in
                guard gate.install(continuation) else { return }
                Thread.detachNewThread { gate.deliver(read()) }
            }
        } onCancel: {
            gate.cancel()
        }
    }

    /// `--variant`: true for quality, false for speed, nil when the app's choice applies.
    public static func parseVariantFlag(_ args: Args) throws -> Bool? {
        guard let raw = args.string("variant") else { return nil }
        switch raw.lowercased() {
        case "speed", "fast": return false
        case "quality", "hq": return true
        case let other: throw CLIError(.invalidInput, "invalid --variant '\(other)' (use speed | quality)")
        }
    }

    /// The take's package: an explicit `--variant`, else the one the Mac app would
    /// use for the mode (its explicit choice, lower-memory preference or hardware
    /// recommendation, falling back to an installed package).
    public struct VariantChoice: Equatable, Sendable {
        public let quality: Bool
        /// `flag` or `app`.
        public let source: String
    }

    public static func resolveVariant(
        explicitQuality: Bool?, mode: GenerationMode, registry: ContractBackedModelRegistry,
        modelsDirectory: URL, settings: DesktopAppSettings,
        deviceClass: NativeDeviceMemoryClass = NativeMemoryPolicyResolver.deviceClass()
    ) -> VariantChoice {
        if let explicitQuality { return VariantChoice(quality: explicitQuality, source: "flag") }
        let choice = DesktopModelSelection.resolve(
            registry: registry,
            explicitVariantID: { settings.explicitVariantID(for: $0) },
            prefersLowerMemory: settings.prefersLowerMemory,
            deviceClass: deviceClass,
            isInstalled: { id in
                registry.model(id: id).map { DesktopModelInventory.isComplete($0, modelsDirectory: modelsDirectory) } ?? false
            }
        ).first { $0.mode == mode.rawValue }
        let variant = choice?.generationVariant ?? choice?.activeVariant
        return VariantChoice(quality: variant == ModelVariantKind.quality.rawValue, source: "app")
    }

    /// The app's variation setting as a request sends it: nil for expressive,
    /// exactly as the app's `GenerationVariationPreference.requestValue()`.
    public static func appVariation(_ settings: DesktopAppSettings) -> Qwen3SamplingVariation? {
        settings.variation == .expressive ? nil : settings.variation
    }

    /// Build the payload for a (mode, args) pair. For clone this resolves the
    /// reference once; `batch` reuses it across all of its requests.
    @MainActor
    public static func buildPayload(_ args: Args, mode: GenerationMode, runtime: CLIRuntime) async throws -> GenerationRequest.Payload {
        try validatePayloadOptions(args, mode: mode)
        switch mode {
        case .custom:
            let delivery: String?
            if let cellID = args.string("delivery-cell") {
                guard args.string("delivery") == nil else {
                    throw CLIError(.usageError, "use either --delivery-cell or --delivery, not both")
                }
                delivery = try DeliveryInstructionCell.resolveStrict(cellID).instruction
            } else {
                delivery = args.string("delivery")
            }
            return .custom(speakerID: try explicitSpeaker(args) ?? runtime.defaultSpeakerID,
                           deliveryStyle: delivery)
        case .design:
            return .design(voiceDescription: try args.require("voice-brief", "a voice description for Voice Design"),
                           deliveryStyle: args.string("delivery"))
        case .clone:
            return .clone(reference: try await resolveCloneReference(args, runtime: runtime))
        }
    }

    public static func resolveDeliveryInstructionCellID(
        _ args: Args,
        mode: GenerationMode
    ) throws -> String? {
        guard let raw = args.string("delivery-cell") else { return nil }
        guard mode == .custom else {
            throw CLIError(.invalidInput, "--delivery-cell is available only in custom mode")
        }
        return try DeliveryInstructionCell.resolveStrict(raw).id
    }

    /// Build the clone reference from either a saved voice (--voice <name|id>
    /// [--transcript "…"]) or a raw reference clip (--reference <wav>
    /// [--transcript "…"]).
    @MainActor
    static func resolveCloneReference(_ args: Args, runtime: CLIRuntime) async throws -> CloneReference {
        if let ref = args.string("reference") {
            let path = (ref as NSString).expandingTildeInPath
            guard FileManager.default.fileExists(atPath: path) else {
                throw CLIError(.inputFileNotFound, "reference audio not found: \(path)")
            }
            let reference = rawCloneReference(audioPath: path, transcript: args.string("transcript"))
            if let conditioningNote = rawReferenceConditioningNote(for: reference) {
                note(conditioningNote)
            }
            return reference
        }
        let name = try args.require("voice", "a saved voice name/id, or --reference <wav>")
        let voices = try await runtime.engine.listPreparedVoices()
        guard let voice = voices.first(where: { $0.name == name || $0.id == name }) else {
            let avail = voices.map(\.name).joined(separator: ", ")
            throw CLIError(.voiceNotFound, "no saved voice '\(name)' (have: \(avail.isEmpty ? "none" : avail))")
        }
        return savedVoiceCloneReference(voice, transcriptOverride: args.string("transcript"))
    }

    /// A raw `--reference` clip conditions on `--transcript` only (P15-05): the
    /// engine reads a same-stem `.txt` sidecar for saved voices alone, so a
    /// file that happens to sit beside the clip is never used silently.
    static func rawCloneReference(audioPath: String, transcript: String?) -> CloneReference {
        CloneReference(audioPath: audioPath, transcript: transcript, preparedVoiceID: nil)
    }

    /// The note a raw reference without a transcript prints: the take runs on
    /// the speaker embedding alone, while the app transcribes a fresh clip and
    /// conditions on its words, so the two differ for the same clip.
    static func rawReferenceConditioningNote(for reference: CloneReference) -> String? {
        guard reference.preparedVoiceID == nil, reference.conditioningMode.isXVectorOnly else { return nil }
        return "no --transcript: this clone uses audio-only (x-vector) conditioning; "
            + "pass --transcript with the clip's words for transcript-backed cloning"
    }

    /// A saved voice conditions on its stored transcript; `--transcript`
    /// overrides it for this take instead of being dropped (P15-05).
    static func savedVoiceCloneReference(_ voice: PreparedVoice, transcriptOverride: String?) -> CloneReference {
        CloneReference(audioPath: voice.audioPath, transcript: transcriptOverride, preparedVoiceID: voice.id)
    }

    /// Refuses, before the engine boots, a script one take cannot speak: empty,
    /// nothing to speak (only punctuation, symbols or emoji, which the model
    /// ends before any audio, U29), or past the apps' single-take limit (CJK
    /// characters count three, `SingleTakeScriptBudget`), which would spend
    /// minutes on a take that runs out of tokens (P15-03).
    static func validateSingleTakeText(_ text: String) throws {
        guard !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
            throw CLIError(.invalidInput, "empty text — pass --text \"…\", --text-file <path>, or --text - to read stdin")
        }
        let measure = SingleTakeScriptBudget.measure(text)
        guard measure.hasSpeakableContent else {
            throw CLIError(.invalidInput, "nothing to speak — the text has no letters or digits")
        }
        guard !measure.exceedsSingleTake else {
            throw CLIError(
                .textTooLong,
                "text is too long for one take (\(measure.characters) characters; one take holds "
                    + "\(SingleTakeScriptBudget.characterLimit), or about "
                    + "\(SingleTakeScriptBudget.characterLimit / SingleTakeScriptBudget.eastAsianCharacterWeight) "
                    + "Chinese, Japanese or Korean characters) — run it as a long-form project with "
                    + "vocello batch --long-form --file <path>, which reads each line as one project"
            )
        }
    }

    /// Resolve script text from --text, --text-file, or piped stdin (`-` forces stdin;
    /// unnamed stdin is read only in text mode without --no-input).
    static func resolveText(_ args: Args) throws -> String {
        if let t = args.string("text") {
            return t == "-" ? (readStdinText() ?? "") : t
        }
        if let f = args.string("text-file") {
            if f == "-" { return readStdinText() ?? "" }
            let path = (f as NSString).expandingTildeInPath
            do { return try String(contentsOfFile: path, encoding: .utf8) }
            catch {
                let code: VocelloErrorCode = FileManager.default.fileExists(atPath: path) ? .ioError : .inputFileNotFound
                throw CLIError(code, "could not read --text-file \(path): \(error.localizedDescription)")
            }
        }
        if let piped = readImplicitStdinText() { return piped }
        throw CLIError(
            .usageError, "missing text — pass --text \"…\", --text-file <path>, or --text - to read stdin"
        )
    }

    /// Where `generate` writes its take.
    struct OutputDestination: Equatable, Sendable {
        let path: String
        /// An explicit `--out` names an existing file, which a successful take
        /// replaces atomically (a failed one leaves it as it was).
        let replacesExistingFile: Bool
    }

    /// The take's destination, resolved and checked before the engine boots, so
    /// a path that cannot hold the take never costs a model load (P15-09, P09-02).
    /// The default name carries the take's generation id, so two runs, however
    /// close together, never share a file (U28). An explicit `--out` must name a
    /// `.wav` file (any case), not a folder.
    static func resolveOutputDestination(
        _ args: Args,
        dataDir: URL,
        mode: GenerationMode,
        generationID: UUID,
        now: Date = Date(),
        fileManager: FileManager = .default
    ) throws -> OutputDestination {
        guard let out = args.string("out") else {
            let name = "\(defaultOutputStamp(now))_\(mode.rawValue)_\(generationID.uuidString.lowercased()).wav"
            let path = dataDir.appendingPathComponent("outputs/cli", isDirectory: true)
                .appendingPathComponent(name).path
            return OutputDestination(path: path, replacesExistingFile: false)
        }
        guard !out.isEmpty else { throw CLIError(.invalidInput, "--out needs a .wav file path") }
        guard !out.hasSuffix("/") else {
            throw CLIError(.invalidInput, "--out \(out) names a folder; pass a .wav file path inside it")
        }
        let path = (out as NSString).expandingTildeInPath
        guard (path as NSString).pathExtension.lowercased() == "wav" else {
            throw CLIError(.invalidInput, "--out must name a .wav file (got \(out)); the take is always written as WAV")
        }
        var isDirectory: ObjCBool = false
        let exists = unsafe fileManager.fileExists(atPath: path, isDirectory: &isDirectory)
        guard !(exists && isDirectory.boolValue) else {
            throw CLIError(.invalidInput, "--out \(out) is an existing folder; pass a .wav file path inside it")
        }
        return OutputDestination(path: path, replacesExistingFile: exists)
    }

    /// `yyyyMMdd_HHmmss` in the POSIX locale and the Gregorian calendar.
    static func defaultOutputStamp(_ date: Date) -> String {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.calendar = Calendar(identifier: .gregorian)
        formatter.dateFormat = "yyyyMMdd_HHmmss"
        return formatter.string(from: date)
    }

    /// Creates the folder of `outputPath` when it is missing; refuses a folder
    /// that cannot be created or is a file, before any model work.
    static func prepareOutputFolder(of outputPath: String, fileManager: FileManager = .default) throws {
        let folder = URL(fileURLWithPath: outputPath).deletingLastPathComponent()
        var isDirectory: ObjCBool = false
        if unsafe fileManager.fileExists(atPath: folder.path, isDirectory: &isDirectory) {
            guard isDirectory.boolValue else {
                throw CLIError(.outputUnavailable, "the output folder \(folder.path) is a file")
            }
            return
        }
        do {
            try fileManager.createDirectory(at: folder, withIntermediateDirectories: true)
        } catch {
            throw CLIError(.outputUnavailable, "could not create the output folder \(folder.path): \(error.localizedDescription)")
        }
    }
}

/// The one-shot rendezvous of `GenerateCommand.readLineCancellably`: whichever
/// of the read and the cancellation comes first resumes the waiting command,
/// exactly once.
final class CLICancellableLineRead: Sendable {
    private enum State {
        case idle
        case waiting(CheckedContinuation<String?, any Error>)
        case cancelled
        case finished
    }

    private let state = Mutex(State.idle)

    /// Parks `continuation` until the read or a cancellation; returns false,
    /// having resumed it with `CancellationError`, when the command was already
    /// cancelled, so no read starts.
    func install(_ continuation: CheckedContinuation<String?, any Error>) -> Bool {
        let alreadyCancelled = state.withLock { state -> Bool in
            guard case .idle = state else { return true }
            state = .waiting(continuation)
            return false
        }
        if alreadyCancelled { continuation.resume(throwing: CancellationError()) }
        return !alreadyCancelled
    }

    func deliver(_ line: String?) {
        let waiting = state.withLock { state -> CheckedContinuation<String?, any Error>? in
            guard case .waiting(let continuation) = state else { return nil }
            state = .finished
            return continuation
        }
        waiting?.resume(returning: line)
    }

    func cancel() {
        let waiting = state.withLock { state -> CheckedContinuation<String?, any Error>? in
            switch state {
            case .idle:
                state = .cancelled
                return nil
            case .waiting(let continuation):
                state = .cancelled
                return continuation
            case .cancelled, .finished:
                return nil
            }
        }
        waiting?.resume(throwing: CancellationError())
    }
}
