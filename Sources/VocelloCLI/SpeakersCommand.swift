import Foundation
import QwenVoiceCore

/// `vocello speakers` — list the Built-in Voice speakers from the contract,
/// so users don't have to guess `--speaker` ids. Read-only: uses the lightweight
/// registry bootstrap (no engine boot, returns instantly).
enum SpeakersCommand {
    struct SpeakerJSON: Encodable {
        let id: String
        let group: String
        let displayName: String
        let language: String?
        let description: String?
        let isDefault: Bool
    }

    @MainActor
    static func run(_ argv: [String]) async throws {
        var argv = argv
        let action = argv.first?.lowercased() ?? "list"
        if action == "help" || action == "--help" { printHelp(); return }
        if !argv.isEmpty, action == "list" || action == "ls" { argv.removeFirst() }

        let args = Args(argv)
        CLIOutput.configure(args)
        let ctx = try CLIRuntime.bootstrapRegistryOnly(
            dataDirectory: CLIPaths.dataDirectory(override: args.string("data-dir")),
            manifestOverride: args.string("manifest").map { URL(fileURLWithPath: ($0 as NSString).expandingTildeInPath) })

        let defaultID = ctx.registry.defaultSpeaker.id
        let speakers = ctx.registry.allSpeakers

        if args.flag("json") {
            emitJSON(speakers.map { s in
                SpeakerJSON(id: s.id, group: s.group, displayName: s.displayName,
                            language: s.nativeLanguage, description: s.shortDescription,
                            isDefault: s.id == defaultID)
            })
            return
        }

        guard !speakers.isEmpty else { print("(no speakers in contract)"); return }
        for s in speakers {
            let star = s.id == defaultID ? "  (default)" : ""
            let lang = s.nativeLanguage.map { " · \($0)" } ?? ""
            print("\(s.group)\t\(s.id)\t\(s.displayName)\(lang)\(star)")
        }
    }

    static func printHelp() {
        print("""
        vocello speakers — list Built-in Voice speakers

        Usage:
          vocello speakers list [--json]

        Options:
          --json       emit JSON instead of a table
          --data-dir   runtime dir (default ~/Library/Application Support/QwenVoice[-Debug])
          --manifest   override path to qwenvoice_contract.json
        """)
    }
}
