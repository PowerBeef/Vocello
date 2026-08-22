import CryptoKit
import Foundation
import QwenVoiceCore

/// `vocello generate` — synthesize one clip headlessly via the in-process engine.
enum GenerateCommand {
    /// Machine-readable result emitted under `--json`.
    struct GenerateJSON: Encodable {
        let generationID: String
        let audioPath: String
        let durationSeconds: Double
        let wallSeconds: Double
        let realtimeFactor: Double
        let finishReason: String?
        let mode: String
        let variant: String
        let modelID: String
        let deliveryInstructionChars: Int?
        let deliveryInstructionDigest: String?
        let firstChunkMS: Double?
        let chunks: Int?
    }

    /// What a `--stream` run observes off `engine.events`.
    struct StreamObservation: Sendable {
        let firstChunkMS: Double?
        let chunkCount: Int
    }

    /// Run a request, and when it's streaming, drain `engine.events` on a side task
    /// to record the engine first-chunk latency (TTFC, ms) and chunk count. Consumes
    /// through the terminal event so the bounded macOS stream isn't left with buffered
    /// events; does NOT render chunks (no live playback). Shared by `generate --stream`
    /// and the `bench --ttfc` probe.
    @MainActor
    static func generateObservingFirstChunk(
        _ runtime: CLIRuntime, _ request: GenerationRequest
    ) async throws -> (result: GenerationResult, firstChunkMS: Double?, chunkCount: Int?) {
        let submitWall = Date()
        let wantedID = request.generationID
        let streamTask: Task<StreamObservation, Never>? = request.shouldStream && wantedID != nil ? {
            let events = runtime.engine.events(for: wantedID!)
            return Task.detached(priority: .utility) {
                var firstChunkMS: Double?
                var count = 0
                for await event in events {
                    switch event {
                    case .chunk(let chunk):
                        if firstChunkMS == nil { firstChunkMS = Date().timeIntervalSince(submitWall) * 1000 }
                        count += 1
                    case .completed, .cancelled, .failed:
                        return StreamObservation(firstChunkMS: firstChunkMS, chunkCount: count)
                    default:
                        continue
                    }
                }
                return StreamObservation(firstChunkMS: firstChunkMS, chunkCount: count)
            }
        }() : nil

        let result: GenerationResult
        do {
            result = try await runtime.engine.generate(request)
        } catch {
            if let streamTask { _ = await streamTask.value }
            throw error
        }
        var firstChunkMS: Double?
        var chunkCount: Int?
        if let streamTask {
            let obs = await streamTask.value
            firstChunkMS = obs.firstChunkMS
            chunkCount = obs.chunkCount
        }
        return (result, firstChunkMS, chunkCount)
    }

    @MainActor
    static func run(_ argv: [String]) async throws {
        let args = Args(argv)
        if args.flag("help") { printHelp(); return }
        CLIOutput.configure(args)

        let quality = try resolveQuality(args)
        let streaming = !args.flag("no-stream")

        // Resolve text first so a missing-text run fails fast (before any prompt).
        let text = try resolveText(args)
        guard !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
            throw CLIError("empty text — pass --text \"…\", --text-file <path>, or pipe text on stdin")
        }

        // Mode: explicit --mode wins; else prompt interactively at a terminal; else
        // default to custom (keeps scripted/piped runs unchanged).
        let mode = try resolveModeInteractive(args)

        let dataDir = CLIPaths.dataDirectory(override: args.string("data-dir"))
        let manifestOverride = args.string("manifest").map {
            URL(fileURLWithPath: ($0 as NSString).expandingTildeInPath)
        }

        note("booting engine (data: \(dataDir.path))")
        let runtime = try await CLIRuntime.bootstrap(dataDirectory: dataDir, manifestOverride: manifestOverride)
        let modelID = try runtime.modelID(mode: mode, quality: quality)
        let payload = try await buildPayload(args, mode: mode, runtime: runtime)

        let outputPath = resolveOutputPath(args, dataDir: dataDir, mode: mode)
        ensureParentDirectory(of: outputPath)

        note("loading \(modelID)…")
        try await runtime.engine.loadModel(id: modelID)

        let generationID = UUID()
        let request = GenerationRequest(
            mode: mode, modelID: modelID, text: text, outputPath: outputPath,
            shouldStream: streaming,
            // Match the app's interactive streaming cadence so --stream exercises
            // the same engine chunk path the UI uses (CustomVoiceCoordinator et al.).
            streamingInterval: streaming ? GenerationSemantics.appStreamingInterval : nil,
            languageHint: args.string("language"),
            payload: payload, generationID: generationID,
            seed: try parseSeed(args),
            variation: try parseVariation(args))

        note("generating (\(text.count) chars)\(streaming ? ", streaming" : "")…")
        let t0 = Date()
        let (result, firstChunkMS, chunkCount) = try await generateObservingFirstChunk(runtime, request)
        let wall = Date().timeIntervalSince(t0)

        // Fail closed on the CM-7 shape: success must never be claimed for a
        // path with no file behind it. The engine publishing contract is
        // verified here at the product boundary, not trusted.
        guard FileManager.default.fileExists(atPath: result.audioPath) else {
            throw CLIError(
                "engine reported success but no audio file exists at \(result.audioPath); refusing to claim success (CM-7 guard)"
            )
        }

        let rtf = wall > 0 ? result.durationSeconds / wall : 0
        if args.flag("json") {
            let deliveryInstruction = payload.deliveryInstructionText?
                .trimmingCharacters(in: .whitespacesAndNewlines)
            let deliveryInstructionChars = deliveryInstruction.flatMap { $0.isEmpty ? nil : $0.count }
            let deliveryInstructionDigest = deliveryInstruction.flatMap { instruction in
                instruction.isEmpty ? nil : Self.sha256(Data(instruction.utf8))
            }
            emitJSON(GenerateJSON(
                generationID: generationID.uuidString.lowercased(),
                audioPath: result.audioPath, durationSeconds: result.durationSeconds,
                wallSeconds: wall, realtimeFactor: rtf,
                finishReason: result.finishReason?.rawValue,
                mode: mode.rawValue, variant: quality ? "quality" : "speed",
                modelID: modelID,
                deliveryInstructionChars: deliveryInstructionChars,
                deliveryInstructionDigest: deliveryInstructionDigest,
                firstChunkMS: firstChunkMS, chunks: chunkCount))
        } else {
            // stdout = machine-readable (the path). stderr = human notes.
            print(result.audioPath)
        }
        let ttfc = firstChunkMS.map { " · ttfc=\(String(format: "%.0f", $0))ms" } ?? ""
        let chunks = chunkCount.map { " · chunks=\($0)" } ?? ""
        note("✓ \(String(format: "%.2f", result.durationSeconds))s audio · rtf=\(String(format: "%.2f", rtf))\(ttfc)\(chunks) · finish=\(result.finishReason?.rawValue ?? "?")")

        if args.flag("play") {
            let p = Process()
            p.executableURL = URL(fileURLWithPath: "/usr/bin/afplay")
            p.arguments = [result.audioPath]
            try? p.run(); p.waitUntilExit()
        }
    }

    private static func sha256(_ data: Data) -> String {
        SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
    }

    // MARK: - Reusable request building (shared with `batch`)

    /// `--seed N` — deterministic sampling: the same request + seed
    /// reproduces the same take (GitHub #47/#30).
    static func parseSeed(_ args: Args) throws -> UInt64? {
        guard let raw = args.string("seed") else { return nil }
        guard let seed = UInt64(raw) else {
            throw CLIError("invalid --seed '\(raw)' (use an unsigned integer)")
        }
        return seed
    }

    /// `--variation expressive|balanced|consistent` — talker sampling
    /// shaping (default expressive = official checkpoint sampling).
    static func parseVariation(_ args: Args) throws -> Qwen3SamplingVariation? {
        guard let raw = args.string("variation") else { return nil }
        guard let variation = Qwen3SamplingVariation(rawValue: raw.lowercased()) else {
            throw CLIError("invalid --variation '\(raw)' (use expressive | balanced | consistent)")
        }
        return variation
    }

    /// Validate a mode string into a `GenerationMode`.
    static func parseModeString(_ s: String) throws -> GenerationMode {
        guard let mode = GenerationMode(rawValue: s.lowercased()) else {
            throw CLIError("invalid --mode '\(s)' (use custom | design | clone)")
        }
        return mode
    }

    /// Mode for non-interactive callers (`batch`, the subcommand path): the `--mode`
    /// flag or the `custom` default — never prompts.
    static func resolveMode(_ args: Args) throws -> GenerationMode {
        try parseModeString(args.string("mode") ?? "custom")
    }

    /// Mode for `generate`: an explicit `--mode` wins; otherwise prompt interactively
    /// when stdin is a terminal; otherwise default to `custom` (scripted/piped runs).
    static func resolveModeInteractive(_ args: Args) throws -> GenerationMode {
        if let explicit = args.string("mode") { return try parseModeString(explicit) }
        if isInteractiveStdin() { return promptForMode() }
        return .custom
    }

    /// Numbered menu on stderr; reads a choice (number or name) from stdin. Falls
    /// back to `custom` on EOF/blank after a few tries.
    static func promptForMode() -> GenerationMode {
        let modes = GenerationMode.allCases
        for _ in 0..<3 {
            FileHandle.standardError.write(Data("Select a mode:\n".utf8))
            for (i, m) in modes.enumerated() {
                FileHandle.standardError.write(Data("  \(i + 1)) \(m.rawValue)\t\(ModesCommand.info(for: m).summary)\n".utf8))
            }
            FileHandle.standardError.write(Data("> ".utf8))
            guard let line = readLine(strippingNewline: true)?.trimmingCharacters(in: .whitespaces),
                  !line.isEmpty else { break }
            if let n = Int(line), n >= 1, n <= modes.count { return modes[n - 1] }
            if let m = GenerationMode(rawValue: line.lowercased()) { return m }
            FileHandle.standardError.write(Data("  ? not a valid choice\n".utf8))
        }
        FileHandle.standardError.write(Data("• defaulting to custom\n".utf8))
        return .custom
    }

    static func resolveQuality(_ args: Args) throws -> Bool {
        switch (args.string("variant") ?? "speed").lowercased() {
        case "speed", "fast": return false
        case "quality", "hq": return true
        case let other: throw CLIError("invalid --variant '\(other)' (use speed | quality)")
        }
    }

    /// Build the payload for a (mode, args) pair. For clone this resolves the
    /// reference once; `batch` reuses it across all of its requests.
    @MainActor
    static func buildPayload(_ args: Args, mode: GenerationMode, runtime: CLIRuntime) async throws -> GenerationRequest.Payload {
        switch mode {
        case .custom:
            return .custom(speakerID: args.string("speaker") ?? runtime.defaultSpeakerID,
                           deliveryStyle: args.string("delivery"))
        case .design:
            return .design(voiceDescription: try args.require("voice-brief", "a voice description for Voice Design"),
                           deliveryStyle: args.string("delivery"))
        case .clone:
            return .clone(reference: try await resolveCloneReference(args, runtime: runtime))
        }
    }

    /// Build the clone reference from either a saved voice (--voice <name|id>)
    /// or a raw reference clip (--reference <wav> [--transcript "…"]).
    @MainActor
    static func resolveCloneReference(_ args: Args, runtime: CLIRuntime) async throws -> CloneReference {
        if let ref = args.string("reference") {
            let path = (ref as NSString).expandingTildeInPath
            guard FileManager.default.fileExists(atPath: path) else {
                throw CLIError("reference audio not found: \(path)")
            }
            return CloneReference(audioPath: path, transcript: args.string("transcript"), preparedVoiceID: nil)
        }
        let name = try args.require("voice", "a saved voice name/id, or --reference <wav>")
        let voices = try await runtime.engine.listPreparedVoices()
        guard let voice = voices.first(where: { $0.name == name || $0.id == name }) else {
            let avail = voices.map(\.name).joined(separator: ", ")
            throw CLIError("no saved voice '\(name)' (have: \(avail.isEmpty ? "none" : avail))")
        }
        return CloneReference(audioPath: voice.audioPath, transcript: nil, preparedVoiceID: voice.id)
    }

    /// Resolve script text from --text, --text-file, or piped stdin (`-` forces stdin).
    static func resolveText(_ args: Args) throws -> String {
        if let t = args.string("text") {
            return t == "-" ? (readStdinText() ?? "") : t
        }
        if let f = args.string("text-file") {
            if f == "-" { return readStdinText() ?? "" }
            let path = (f as NSString).expandingTildeInPath
            do { return try String(contentsOfFile: path, encoding: .utf8) }
            catch { throw CLIError("could not read --text-file \(path): \(error.localizedDescription)") }
        }
        if let piped = readStdinText() { return piped }
        throw CLIError("missing text — pass --text \"…\", --text-file <path>, or pipe text on stdin")
    }

    /// Create the parent directory of an output path when it has one (a bare
    /// filename writes into the cwd — nothing to create).
    static func ensureParentDirectory(of outputPath: String) {
        let parent = URL(fileURLWithPath: outputPath).deletingLastPathComponent()
        if !parent.path.isEmpty, parent.path != "." {
            try? FileManager.default.createDirectory(at: parent, withIntermediateDirectories: true)
        }
    }

    private static func resolveOutputPath(_ args: Args, dataDir: URL, mode: GenerationMode) -> String {
        if let out = args.string("out") { return (out as NSString).expandingTildeInPath }
        let fmt = DateFormatter()
        fmt.dateFormat = "yyyyMMdd_HHmmss"
        fmt.locale = Locale(identifier: "en_US_POSIX")
        return dataDir
            .appendingPathComponent("outputs/cli", isDirectory: true)
            .appendingPathComponent("\(fmt.string(from: Date()))_\(mode.rawValue).wav").path
    }

    static func printHelp() {
        print("""
        vocello generate — synthesize a clip headlessly

        Usage:
          vocello generate --mode custom|design|clone --variant speed|quality \\
                           (--text "…" | --text-file <path> | piped stdin) [--out <path>] [options]

        Selecting a mode: `vocello custom|design|clone …` (shortcut), `--mode <mode>`,
        or omit it at a terminal for an interactive picker. See `vocello modes`.

        Options:
          --mode         custom | design | clone (default custom; prompts at a TTY if omitted)
          --variant      speed (default) | quality
          --text         inline script text ("-" reads stdin)
          --text-file    read script text from a file ("-" reads stdin)
          --speaker      (custom) speaker id; default = contract default (see `vocello speakers list`)
          --voice-brief  (design) voice description
          --voice        (clone) saved voice name or id
          --reference    (clone) path to a reference .wav (alternative to --voice)
          --transcript   (clone) transcript of the --reference clip
          --delivery     optional delivery style
          --language     Qwen3 language hint (english, french, auto, …); omitted = Auto
          --seed         deterministic sampling seed — same request + seed
                         reproduces the same take
          --variation    expressive (default, official) | balanced | consistent
          --out          output .wav path; default → <data>/outputs/cli/
          --stream       streaming synthesis at the app's 320ms cadence; reports
                         first-chunk latency (TTFC) + chunk count (no live playback).
                         This is the default; use --no-stream to disable it.
          --no-stream    accumulate the full result before decoding (non-streaming)
          --play         play the result with afplay when done
          --json         emit a JSON result object on stdout instead of the bare path
          --quiet|--verbose   suppress / expand stderr progress notes
          --data-dir     runtime dir (default ~/Library/Application Support/QwenVoice[-Debug])
          --manifest     override path to qwenvoice_contract.json

        Prints the output WAV path on stdout (or a JSON object with --json).
        """)
    }
}
