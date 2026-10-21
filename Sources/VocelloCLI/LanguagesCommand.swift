import Foundation
import QwenVoiceCore
import VocelloCLICore

/// `vocello languages`: the generation languages `--language` accepts, with the
/// code each answers to. Static and instant (no engine or registry boot).
enum LanguagesCommand {
    struct LanguageJSON: Encodable, Sendable {
        /// The canonical name the apps send (`english`), or `auto`.
        let id: String
        let displayName: String
        /// The primary code `--language` also accepts (`en`); region subtags are ignored.
        let code: String
    }

    struct Rows: Encodable, Sendable {
        let languages: [LanguageJSON]
    }

    @MainActor
    static func run(_ args: Args) async throws {
        let rows = Qwen3SupportedLanguage.allCases.map {
            LanguageJSON(id: $0.rawValue, displayName: $0.displayName, code: CLILanguageCodes.code(for: $0))
        }
        if CLIPresenter.isMachine {
            CLIPresenter.succeed(Rows(languages: rows))
            return
        }
        for row in rows { print("\(row.id)\t\(row.code)\t\(row.displayName)") }
        note("pass a name or a code to --language (a region such as ja-JP is ignored); auto picks from the script")
    }
}
