import Foundation
import QwenVoiceCore
import VocelloCLICore
import VocelloDesktopCore

/// `vocello voices` — manage saved (enrolled) clone voices.
enum VoicesCommand {
    struct VoiceJSON: Encodable, Sendable {
        let id: String
        let name: String
        let audioPath: String
        let hasTranscript: Bool
        let qualityWarnings: [String]
    }

    struct Rows: Encodable, Sendable {
        let voices: [VoiceJSON]
    }

    struct Banks: Encodable, Sendable {
        let banks: [DesktopVoiceBanks.Bank]
    }

    struct Shown: Encodable, Sendable {
        let voice: VoiceJSON
        /// The words the reference says, as saved (nil when it has none).
        let transcript: String?
        /// The reference language recorded at enrollment (nil: Auto or unrecorded).
        let referenceLanguage: String?
        let transcriptSource: String?
        let generatedSourceMode: String?
        let enrollmentRecordUnreadable: Bool
    }

    struct Enrolled: Encodable, Sendable {
        let voice: VoiceJSON
    }

    struct Deleted: Encodable, Sendable {
        let deleted: String
    }

    static func json(_ voice: PreparedVoice) -> VoiceJSON {
        VoiceJSON(id: voice.id, name: voice.name, audioPath: voice.audioPath,
                  hasTranscript: voice.hasTranscript, qualityWarnings: voice.qualityWarnings)
    }

    /// `action` is the canonical subcommand the parser resolved: list, enroll or delete.
    @MainActor
    static func run(action: String, _ args: Args) async throws {
        // PA-17: enrollment needs this invocation's recorded consent; refuse before boot.
        let consent = try CLIVoiceCloningConsent.policy(from: args)
        if action == "enroll" {
            try consent.admit(.enrollment)
        }
        let runtime = try await CLIRuntime.bootstrap(
            dataDirectory: CLIPaths.dataDirectory(override: args.string("data-dir")),
            manifestOverride: args.string("manifest").map { URL(fileURLWithPath: ($0 as NSString).expandingTildeInPath) },
            voiceCloningConsent: consent)

        switch action {
        case "list":
            let voices = try await runtime.engine.listPreparedVoices()
            if CLIPresenter.isMachine {
                CLIPresenter.succeed(Rows(voices: voices.map(json)))
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
        case "banks":
            let voices = try await runtime.engine.listPreparedVoices()
            let banks = DesktopVoiceBanks.banks(voices: voices.map { (id: $0.id, name: $0.name) })
            if CLIPresenter.isMachine {
                CLIPresenter.succeed(Banks(banks: banks))
                return
            }
            if banks.isEmpty { print("(no delivery banks: save voices named <Name> and <Name> (<Preset>))") }
            for bank in banks {
                print("\(bank.name)\t[\(bank.baseVoiceID)]")
                for member in bank.members { print("  \(member.preset)\t\(member.voiceID)") }
            }
        case "show":
            let wanted = args.positionals.first ?? ""
            let voices = try await runtime.engine.listPreparedVoices()
            guard let voice = voices.first(where: { $0.id == wanted || $0.name == wanted }) else {
                throw CLIError(
                    .voiceNotFound, "no saved voice '\(wanted)'", hint: "see `vocello voices list` for the names and ids"
                )
            }
            let transcriptURL = URL(fileURLWithPath: voice.audioPath).deletingPathExtension().appendingPathExtension("txt")
            let transcript = voice.hasTranscript
                ? (try? String(contentsOf: transcriptURL, encoding: .utf8))?.trimmingCharacters(in: .whitespacesAndNewlines)
                : nil
            let metadata = voice.enrollmentMetadata
            let shown = Shown(
                voice: json(voice), transcript: transcript,
                referenceLanguage: metadata?.referenceLanguage?.rawValue,
                transcriptSource: metadata?.transcriptSource.rawValue,
                generatedSourceMode: metadata?.generatedSourceMode,
                enrollmentRecordUnreadable: voice.enrollmentMetadataUnreadable
            )
            if CLIPresenter.isMachine {
                CLIPresenter.succeed(shown)
            } else {
                print("\(voice.name)\t[\(voice.id)]")
                print("reference: \(voice.audioPath)")
                if let language = shown.referenceLanguage { print("language: \(language)") }
                if let source = shown.transcriptSource { print("transcript source: \(source)") }
                if !voice.qualityWarnings.isEmpty { print("warnings: \(voice.qualityWarnings.joined(separator: ", "))") }
                print("transcript: \(transcript ?? "(none: audio-only conditioning)")")
            }
        case "enroll":
            let name = try args.require("name", "a name for the voice")
            let audio = try args.require("audio", "path to the reference .wav")
            let audioPath = (audio as NSString).expandingTildeInPath
            guard FileManager.default.fileExists(atPath: audioPath) else {
                throw CLIError(.inputFileNotFound, "audio not found: \(audioPath)")
            }
            let voice = try await runtime.enrollPreparedVoice(
                name: name, audioPath: audioPath, transcript: args.string("transcript"))
            for warning in voice.qualityWarnings {
                CLIPresenter.warn("voice_quality", warning)
            }
            if CLIPresenter.isMachine {
                CLIPresenter.succeed(Enrolled(voice: json(voice)))
            } else {
                print("enrolled \(voice.name) [\(voice.id)]")
            }
        case "delete":
            let id = try args.require("id", "the saved voice id (see `voices list`)")
            guard try await runtime.engine.listPreparedVoices().contains(where: { $0.id == id }) else {
                throw CLIError(
                    .voiceNotFound, "no saved voice with id '\(id)'", hint: "see `vocello voices list` for the ids"
                )
            }
            try await runtime.engine.deletePreparedVoice(id: id)
            if CLIPresenter.isMachine {
                CLIPresenter.succeed(Deleted(deleted: id))
            } else {
                print("deleted \(id)")
            }
        default:
            // The parser resolves only the declared subcommands.
            throw CLIError(.internalError, "no handler for voices \(action)")
        }
    }
}
