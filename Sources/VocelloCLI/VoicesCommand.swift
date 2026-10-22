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
        /// The voice has a transcript file that could not be read.
        let transcriptUnreadable: Bool
        /// The reference language recorded at enrollment (nil: Auto or unrecorded).
        let referenceLanguage: String?
        let transcriptSource: String?
        let generatedSourceMode: String?
        let enrollmentRecordUnreadable: Bool
    }

    /// `enroll`, `replace` and `save-take`: what became of the candidate.
    struct Enrolled: Encodable, Sendable {
        /// saved or discarded.
        let outcome: String
        /// The saved voice; null when the candidate was discarded.
        let voice: VoiceJSON?
        let name: String
        let qualityWarnings: [String]
        /// Where the saved transcript came from: manual, automatic, audio_only, …
        let transcriptSource: String
        let referenceLanguage: String
        /// The on-device recognition's outcome, when it ran.
        let automaticTranscription: String?
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
        if ["enroll", "replace", "save-take"].contains(action) {
            try consent.admit(.enrollment)
        }
        if ["enroll", "replace", "save-take", "delete"].contains(action) {
            try await runWrite(action: action, args, consent: consent)
            return
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
            let transcriptUnreadable = voice.hasTranscript && transcript == nil
            let metadata = voice.enrollmentMetadata
            let shown = Shown(
                voice: json(voice), transcript: transcript, transcriptUnreadable: transcriptUnreadable,
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
                print("transcript: \(transcript ?? (transcriptUnreadable ? "(unreadable)" : "(none: audio-only conditioning)"))")
            }
        default:
            // The parser resolves only the declared subcommands.
            throw CLIError(.internalError, "no handler for voices \(action)")
        }
    }

    /// The saved-voice writes, through the hosted engine as the app makes them
    /// (`DesktopVoiceEnrollment`); each tells a running app.
    @MainActor
    static func runWrite(action: String, _ args: Args, consent: VoiceCloningConsentPolicy) async throws {
        let dataDirectory = CLIPaths.dataDirectory(override: args.string("data-dir"))
        var request: DesktopVoiceEnrollment.Request?
        switch action {
        case "enroll":
            request = try enrollmentRequest(args, audio: try args.require("audio", "path to the reference clip"))
        case "replace":
            let id = args.positionals.first ?? ""
            var replacing = try enrollmentRequest(args, audio: try args.require("audio", "path to the new reference clip"))
            replacing.replacingVoiceID = id
            request = replacing
        case "save-take":
            request = try takeRequest(args, dataDirectory: dataDirectory)
        default:
            break
        }
        let runtime = try await CLIRuntime.bootstrap(
            dataDirectory: dataDirectory,
            manifestOverride: args.string("manifest").map { URL(fileURLWithPath: ($0 as NSString).expandingTildeInPath) },
            // Saved-voice writes load no model, so they take no engine lease.
            voiceCloningConsent: consent, hostedLikeTheApp: true, takesEngineLease: false
        )
        guard let host = runtime.host else { throw CLIError(.internalError, "the engine did not start") }

        guard let request else {
            // delete
            let id = try args.require("id", "the saved voice id (see `vocello voices list`)")
            guard try await host.listVoices().contains(where: { $0.id == id }) else {
                throw CLIError(.voiceNotFound, "no saved voice with id '\(id)'", hint: "see `vocello voices list` for the ids")
            }
            try await host.deleteVoice(id: id)
            DesktopChangeNotice.savedVoices.post()
            if CLIPresenter.isMachine {
                CLIPresenter.succeed(Deleted(deleted: id))
            } else {
                print("deleted \(id)")
            }
            return
        }

        let result: DesktopVoiceEnrollment.Result
        do {
            result = try await host.enrollVoice(request)
        } catch let failure as DesktopVoiceEnrollment.Failure {
            throw cliError(for: failure)
        }
        if result.outcome == .saved { DesktopChangeNotice.savedVoices.post() }
        for warning in result.qualityWarnings {
            CLIPresenter.warn("voice_quality", warning)
        }
        if CLIPresenter.isMachine {
            CLIPresenter.succeed(Enrolled(
                outcome: result.outcome.rawValue, voice: result.voice.map(json), name: result.name,
                qualityWarnings: result.qualityWarnings, transcriptSource: result.transcriptSource,
                referenceLanguage: result.referenceLanguage, automaticTranscription: result.automaticTranscription
            ))
        } else if let voice = result.voice {
            print("\(action == "replace" ? "replaced" : "saved") \(voice.name) [\(voice.id)]")
        } else {
            print("discarded \(result.name): \(result.qualityWarnings.joined(separator: ", "))")
        }
    }

    /// `enroll` and `replace`: the clip and the caller's decisions.
    static func enrollmentRequest(_ args: Args, audio: String) throws -> DesktopVoiceEnrollment.Request {
        let audioPath = URL(fileURLWithPath: (audio as NSString).expandingTildeInPath).standardizedFileURL.path
        guard FileManager.default.fileExists(atPath: audioPath) else {
            throw CLIError(.inputFileNotFound, "audio not found: \(audioPath)")
        }
        return DesktopVoiceEnrollment.Request(
            name: args.string("name"), audioPath: audioPath, transcript: args.string("transcript"),
            audioOnly: try audioOnly(args), transcription: transcription(args), language: try language(args),
            onWarnings: onWarnings(args)
        )
    }

    /// `save-take <history id>`: a Design or Clone take from History becomes a
    /// voice, as the app's History "Save to Saved Voices" does.
    static func takeRequest(_ args: Args, dataDirectory: URL) throws -> DesktopVoiceEnrollment.Request {
        let id = try HistoryCommand.itemID(args)
        let detail: DesktopHistoryDetail?
        do {
            detail = try DesktopHistoryReader(root: dataDirectory).detail(id: id)
        } catch let error as DesktopHistoryError {
            throw HistoryCommand.cliError(for: error)
        }
        guard let item = detail?.item else {
            throw CLIError(.historyItemNotFound, "no History item \(id)", hint: "see `vocello history list`")
        }
        guard item.audioExists else {
            throw CLIError(.inputFileNotFound, "History item \(id) has no audio left")
        }
        let source: DesktopVoiceEnrollment.Source
        switch item.mode {
        case GenerationMode.clone.rawValue:
            source = .cloneTake(text: item.text, voice: item.voice)
        case GenerationMode.design.rawValue:
            source = .designTake(text: item.text, voiceDescription: item.voice ?? "")
        default:
            throw CLIError(
                .invalidInput, "History item \(id) is a \(item.mode) take; only Design and Clone takes become saved voices"
            )
        }
        return DesktopVoiceEnrollment.Request(
            name: args.string("name"), audioPath: item.audioPath, transcript: args.string("transcript"),
            audioOnly: try audioOnly(args), transcription: transcription(args), language: try language(args),
            onWarnings: onWarnings(args), source: source
        )
    }

    private static func audioOnly(_ args: Args) throws -> Bool {
        let audioOnly = args.flag("audio-only")
        if audioOnly, args.string("transcript") != nil {
            throw CLIError(.usageError, "--audio-only saves no transcript: drop --transcript or --audio-only")
        }
        return audioOnly
    }

    private static func transcription(_ args: Args) -> DesktopVoiceEnrollment.Transcription {
        // The parser refuses any other value.
        args.string("transcribe").flatMap(DesktopVoiceEnrollment.Transcription.init(rawValue:)) ?? .auto
    }

    private static func onWarnings(_ args: Args) -> DesktopVoiceEnrollment.OnWarnings {
        args.string("on-warnings").flatMap(DesktopVoiceEnrollment.OnWarnings.init(rawValue:)) ?? .fail
    }

    private static func language(_ args: Args) throws -> Qwen3SupportedLanguage? {
        let language = try GenerateCommand.parseLanguage(args)
        return language == .auto ? nil : language
    }

    static func cliError(for failure: DesktopVoiceEnrollment.Failure) -> CLIError {
        switch failure {
        case .nameMissing:
            CLIError(.usageError, "the voice needs a name", hint: "pass --name")
        case .nameNeedsCharacters:
            CLIError(.invalidInput, "the name needs a letter, digit or underscore")
        case .nameExists(let storeID):
            CLIError(
                .invalidInput, "a saved voice named '\(storeID)' already exists",
                hint: "pick another --name, or `vocello voices replace \(storeID)` to give it a new reference"
            )
        case .voiceNotFound(let id):
            CLIError(.voiceNotFound, "no saved voice with id '\(id)'", hint: "see `vocello voices list` for the ids")
        case .transcriptNeeded(let reason):
            CLIError(
                .invalidInput, "the reference has no transcript: \(reason)",
                hint: "pass --transcript \"…\" with its words, --audio-only, or --transcribe always"
            )
        case .languageNeeded:
            CLIError(.invalidInput, "the transcript's language could not be detected", hint: "pass --language")
        case .qualityRefused(let warnings, let hardBlocking):
            CLIError(
                .qcRejected, "the reference has quality warnings (\(warnings.joined(separator: ", "))); it was not saved",
                hint: hardBlocking ? "use another reference clip" : "pass --on-warnings keep to save it anyway",
                detail: ["warnings": .array(warnings.map { .string($0) }), "hardBlocking": .bool(hardBlocking)]
            )
        }
    }
}
