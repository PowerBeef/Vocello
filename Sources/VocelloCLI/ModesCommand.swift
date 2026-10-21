import Foundation
import QwenVoiceCore

/// `vocello modes` — list the generation modes and what each needs, so users can
/// discover how to select one. Static + instant (no engine/registry boot).
public enum ModesCommand {
    struct ModeJSON: Encodable, Sendable {
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

    struct Rows: Encodable, Sendable {
        let modes: [ModeJSON]
    }

    @MainActor
    public static func run(_ args: Args) async throws {
        let rows = GenerationMode.allCases.map { m -> ModeJSON in
            let i = info(for: m)
            return ModeJSON(mode: m.rawValue, summary: i.summary, needs: i.needs)
        }

        if CLIPresenter.isMachine {
            CLIPresenter.succeed(Rows(modes: rows))
            return
        }
        for r in rows {
            print("\(r.mode)\t\(r.summary)\t\(r.needs)")
        }
        note("select with `vocello <mode> …`, `generate --mode <mode>`, or the interactive picker")
    }
}
