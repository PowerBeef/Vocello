import Foundation
import QwenVoiceCore

/// `vocello modes` — list the generation modes and what each needs, so users can
/// discover how to select one. Static + instant (no engine/registry boot).
public enum ModesCommand {
    struct ModeJSON: Encodable {
        let mode: String
        let summary: String
        let needs: String
    }

    /// What each mode requires, keyed by `GenerationMode.rawValue`.
    static func info(for mode: GenerationMode) -> (summary: String, needs: String) {
        switch mode {
        case .custom: return ("built-in speaker preset", "--speaker <id> (see `vocello speakers list`)")
        case .design: return ("describe a voice in words", "--voice-brief \"…\"")
        case .clone:  return ("a saved or reference voice", "--voice <name> | --reference <wav>")
        }
    }

    @MainActor
    public static func run(_ argv: [String]) async throws {
        var argv = argv
        if let first = argv.first?.lowercased(), first == "list" || first == "ls" { argv.removeFirst() }
        let args = Args(argv)
        if args.flag("help") { printHelp(); return }
        CLIOutput.configure(args)

        let rows = GenerationMode.allCases.map { m -> ModeJSON in
            let i = info(for: m)
            return ModeJSON(mode: m.rawValue, summary: i.summary, needs: i.needs)
        }

        if args.flag("json") { emitJSON(rows); return }
        for r in rows {
            print("\(r.mode)\t\(r.summary)\t\(r.needs)")
        }
        note("select with `vocello <mode> …`, `generate --mode <mode>`, or the interactive picker")
    }

    static func printHelp() {
        print("""
        vocello modes — list the generation modes and what each needs

        Usage:
          vocello modes [--json]

        Select a mode any of these ways:
          vocello custom|design|clone …      # mode subcommand shortcut
          vocello generate --mode <mode> …   # explicit flag
          vocello generate …                 # interactive picker (terminal only)

        Options:
          --json   emit JSON instead of a table
        """)
    }
}
