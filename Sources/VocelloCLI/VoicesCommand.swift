import Foundation
import QwenVoiceCore

/// `vocello voices` — manage saved (enrolled) clone voices.
enum VoicesCommand {
    struct VoiceJSON: Encodable {
        let id: String
        let name: String
        let audioPath: String
        let hasTranscript: Bool
        let qualityWarnings: [String]
    }

    @MainActor
    static func run(_ argv: [String]) async throws {
        var argv = argv
        // Leading non-flag token is the action; default to `list`.
        let action: String
        if let first = argv.first?.lowercased(), !first.hasPrefix("--") {
            action = first; argv.removeFirst()
        } else {
            action = "list"
        }
        if action == "help" { printHelp(); return }

        let args = Args(argv)
        CLIOutput.configure(args)
        if args.flag("help") { printHelp(); return }
        // PA-17: enrollment needs this invocation's recorded consent; refuse before boot.
        let consent = CLIVoiceCloningConsent.policy(confirmed: args.flag(CLIVoiceCloningConsent.flagName))
        if action == "enroll" || action == "add" {
            try consent.admit(.enrollment)
        }
        let runtime = try await CLIRuntime.bootstrap(
            dataDirectory: CLIPaths.dataDirectory(override: args.string("data-dir")),
            manifestOverride: args.string("manifest").map { URL(fileURLWithPath: ($0 as NSString).expandingTildeInPath) },
            voiceCloningConsent: consent)

        switch action {
        case "list", "ls":
            let voices = try await runtime.engine.listPreparedVoices()
            if args.flag("json") {
                emitJSON(voices.map { VoiceJSON(id: $0.id, name: $0.name, audioPath: $0.audioPath,
                                                hasTranscript: $0.hasTranscript, qualityWarnings: $0.qualityWarnings) })
                return
            }
            if voices.isEmpty {
                print("(no saved voices)")
                return
            }
            for v in voices {
                let warn = v.qualityWarnings.isEmpty ? "" : "  ⚠ \(v.qualityWarnings.joined(separator: ","))"
                print("\(v.name)\t[\(v.id)]\ttranscript=\(v.hasTranscript)\(warn)")
            }
        case "enroll", "add":
            let name = try args.require("name", "a name for the voice")
            let audio = try args.require("audio", "path to the reference .wav")
            let audioPath = (audio as NSString).expandingTildeInPath
            guard FileManager.default.fileExists(atPath: audioPath) else {
                throw CLIError("audio not found: \(audioPath)")
            }
            let voice = try await runtime.enrollPreparedVoice(
                name: name, audioPath: audioPath, transcript: args.string("transcript"))
            print("enrolled \(voice.name) [\(voice.id)]")
            if !voice.qualityWarnings.isEmpty {
                FileHandle.standardError.write(Data("⚠ \(voice.qualityWarnings.joined(separator: ", "))\n".utf8))
            }
        case "delete", "rm":
            let id = try args.require("id", "the saved voice id (see `voices list`)")
            try await runtime.engine.deletePreparedVoice(id: id)
            print("deleted \(id)")
        default:
            throw CLIError("unknown voices action '\(action)' (use list | enroll | delete)")
        }
    }

    static func printHelp() {
        print("""
        vocello voices — manage saved clone voices

        Usage:
          vocello voices list [--json]
          vocello voices enroll --name <name> --audio <wav> [--transcript "…"] --confirm-consent
          vocello voices delete --id <id>

        Options:
          --json       (list) emit JSON instead of a table
          --confirm-consent  (enroll) required: confirms you own or have permission
                       to clone this voice
          --data-dir   runtime dir (default ~/Library/Application Support/QwenVoice[-Debug])
          --manifest   override path to qwenvoice_contract.json
        """)
    }
}
