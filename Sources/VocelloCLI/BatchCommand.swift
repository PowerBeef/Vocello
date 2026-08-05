import Foundation
import QwenVoiceCore

/// `vocello batch` — synthesize many clips that share one voice/mode/variant,
/// reusing a single model load via `MLXTTSEngine.generateBatch`. The headline
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

    @MainActor
    static func run(_ argv: [String]) async throws {
        let args = Args(argv)
        if args.flag("help") { printHelp(); return }
        CLIOutput.configure(args)

        let mode = try GenerateCommand.resolveMode(args)
        let quality = try GenerateCommand.resolveQuality(args)

        let lines = try readLines(args)
        guard !lines.isEmpty else {
            throw CLIError("no input lines — pass --file <path> (one clip per line) or pipe text on stdin")
        }

        let dataDir = CLIPaths.dataDirectory(override: args.string("data-dir"))
        let manifestOverride = args.string("manifest").map { URL(fileURLWithPath: ($0 as NSString).expandingTildeInPath) }

        note("booting engine (data: \(dataDir.path))")
        let runtime = try await CLIRuntime.bootstrap(dataDirectory: dataDir, manifestOverride: manifestOverride)
        let modelID = try runtime.modelID(mode: mode, quality: quality)
        // One shared payload → all requests carry the same session key, satisfying
        // generateBatch's single-session requirement.
        let payload = try await GenerateCommand.buildPayload(args, mode: mode, runtime: runtime)

        let outDir = resolveOutDir(args, dataDir: dataDir)
        try FileManager.default.createDirectory(at: outDir, withIntermediateDirectories: true)

        let fmt = DateFormatter()
        fmt.dateFormat = "yyyyMMdd_HHmmss"
        fmt.locale = Locale(identifier: "en_US_POSIX")
        let stamp = fmt.string(from: Date())

        // --seed applies the SAME seed to every item: each item's sampling
        // stream is then deterministic for its text, and re-running the batch
        // reproduces it (community testing also reports a fixed seed reduces
        // cross-segment timbre drift; GitHub #30/#47).
        let seed = try GenerateCommand.parseSeed(args)
        let variation = try GenerateCommand.parseVariation(args)
        var requests: [GenerationRequest] = []
        requests.reserveCapacity(lines.count)
        for (i, line) in lines.enumerated() {
            let out = outDir.appendingPathComponent("\(stamp)_\(mode.rawValue)_\(String(format: "%03d", i)).wav").path
            requests.append(GenerationRequest(
                mode: mode, modelID: modelID, text: line, outputPath: out,
                shouldStream: false, payload: payload, generationID: UUID(),
                seed: seed, variation: variation))
        }

        note("loading \(modelID)…")
        try await runtime.engine.loadModel(id: modelID)

        note("generating \(requests.count) clip(s), one model load…")
        let wallStart = Date()
        let results = try await runtime.engine.generateBatch(requests) { fraction, label in
            if let fraction { noteVerbose("\(Int(fraction * 100))% — \(label)") }
            else { noteVerbose(label) }
        }
        let wall = Date().timeIntervalSince(wallStart)

        // Fail closed on the CM-7 shape: never print a path with no file
        // behind it as a successful batch item.
        for r in results where !FileManager.default.fileExists(atPath: r.audioPath) {
            throw CLIError(
                "engine reported success but no audio file exists at \(r.audioPath); refusing to claim success (CM-7 guard)"
            )
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

        if args.flag("play") {
            for r in results {
                let p = Process()
                p.executableURL = URL(fileURLWithPath: "/usr/bin/afplay")
                p.arguments = [r.audioPath]
                try? p.run(); p.waitUntilExit()
            }
        }
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
          --delivery     optional delivery style (applies to all clips)
          --out-dir      output directory; default → <data>/outputs/cli/batch/
          --seed         deterministic sampling seed, applied to every item
                         (re-running the batch reproduces it; steadier segments)
          --variation    expressive (default, official) | balanced | consistent
          --play         play each result with afplay when done
          --json         emit a JSON summary on stdout instead of one path per line
          --quiet|--verbose   suppress / expand stderr progress notes
          --data-dir     runtime dir (default ~/Library/Application Support/QwenVoice[-Debug])
          --manifest     override path to qwenvoice_contract.json

        Prints one output WAV path per line on stdout (or a JSON object with --json).
        """)
    }
}
