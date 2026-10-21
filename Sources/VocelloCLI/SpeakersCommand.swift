import Foundation
import QwenVoiceCore
import VocelloCLICore

/// `vocello speakers` — list the Built-in Voice speakers from the contract,
/// so users don't have to guess `--speaker` ids. Read-only: uses the lightweight
/// registry bootstrap (no engine boot, returns instantly).
enum SpeakersCommand {
    struct SpeakerJSON: Encodable, Sendable {
        let id: String
        let group: String
        let displayName: String
        let language: String?
        let description: String?
        let isDefault: Bool
    }

    struct Rows: Encodable, Sendable {
        let speakers: [SpeakerJSON]
    }

    @MainActor
    static func run(_ args: Args) async throws {
        let ctx = try CLIRuntime.bootstrapRegistryOnly(
            dataDirectory: CLIPaths.dataDirectory(override: args.string("data-dir")),
            manifestOverride: args.string("manifest").map { URL(fileURLWithPath: ($0 as NSString).expandingTildeInPath) })

        let defaultID = ctx.registry.defaultSpeaker.id
        let speakers = ctx.registry.allSpeakers

        if CLIPresenter.isMachine {
            CLIPresenter.succeed(Rows(speakers: speakers.map { s in
                SpeakerJSON(id: s.id, group: s.group, displayName: s.displayName,
                            language: s.nativeLanguage, description: s.shortDescription,
                            isDefault: s.id == defaultID)
            }))
            return
        }

        guard !speakers.isEmpty else { print("(no speakers in contract)"); return }
        for s in speakers {
            let star = s.id == defaultID ? "  (default)" : ""
            let lang = s.nativeLanguage.map { " · \($0)" } ?? ""
            print("\(s.group)\t\(s.id)\t\(s.displayName)\(lang)\(star)")
        }
    }
}
