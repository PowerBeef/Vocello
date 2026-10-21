import Foundation
import QwenVoiceCore
import VocelloCLICore
import VocelloDesktopCore

/// `vocello history`: the Mac app's History, read-only (RF-26). Every read is
/// one short read-only transaction on the app's store; nothing here migrates,
/// reconciles or writes it.
enum HistoryCommand {
    struct Shown: Encodable, Sendable {
        let item: DesktopHistoryItem
        let completionReceipt: GenerationCompletionReceipt?
    }

    struct Exported: Encodable, Sendable {
        let id: String
        let destination: String
        let outcome: DesktopHistoryExport.Outcome
        let bytes: Int64
    }

    @MainActor
    static func run(action: String, _ args: Args) async throws {
        let reader = DesktopHistoryReader(root: CLIPaths.dataDirectory(override: args.string("data-dir")))
        do {
            switch action {
            case "list", "search":
                try list(reader, args, query: action == "search" ? args.positionals.first ?? "" : "")
            case "show":
                try show(reader, id: try itemID(args))
            case "export":
                try export(reader, id: try itemID(args), args)
            default:
                throw CLIError(.internalError, "no handler for history \(action)")
            }
        } catch let error as DesktopHistoryError {
            switch error {
            case .schemaNewer:
                throw CLIError(.historySchemaNewer, error.errorDescription ?? "", hint: "update the CLI to the app's version")
            case .schemaOlder:
                throw CLIError(.configError, error.errorDescription ?? "", hint: "open Vocello once, then retry")
            case .busy:
                throw CLIError(.storeBusy, error.errorDescription ?? "", hint: "the app is writing History; retry")
            case .appRunning:
                throw CLIError(
                    .storeBusy, error.errorDescription ?? "",
                    hint: "quit Vocello and retry; a shared History lock (RF-30) will lift this"
                )
            case .damaged:
                throw CLIError(.ioError, error.errorDescription ?? "", hint: "open Vocello, which recovers History")
            }
        }
    }

    static func itemID(_ args: Args) throws -> Int64 {
        let raw = args.positionals.first ?? ""
        guard let id = Int64(raw), id > 0 else {
            throw CLIError(.invalidInput, "invalid History id '\(raw)'", hint: "ids are the `id` values `vocello history list` prints")
        }
        return id
    }

    static func limit(_ args: Args) throws -> Int {
        guard let raw = args.string("limit") else { return 50 }
        guard let value = Int(raw), (1 ... 500).contains(value) else {
            throw CLIError(.invalidInput, "invalid --limit '\(raw)' (use 1 to 500)")
        }
        return value
    }

    static func list(_ reader: DesktopHistoryReader, _ args: Args, query: String) throws {
        let order = try args.string("order").map { raw -> DesktopHistoryOrder in
            guard let order = DesktopHistoryOrder(rawValue: raw.lowercased()) else {
                throw CLIError(.invalidInput, "invalid --order '\(raw)' (use \(DesktopHistoryOrder.allCases.map(\.rawValue).joined(separator: " | ")))")
            }
            return order
        } ?? .newest
        let mode = try args.string("mode").map { try GenerateCommand.parseModeString($0).rawValue }
        let page = try reader.page(mode: mode, query: query, order: order, limit: try limit(args))
        if page.longFormRecoveryPending {
            CLIPresenter.warn(
                "long_form_recovery_pending",
                "a long-form project awaits recovery in the app; project rows are withheld until it reconciles"
            )
        }
        if CLIPresenter.isMachine {
            CLIPresenter.succeed(page)
            return
        }
        guard !page.items.isEmpty else {
            print(reader.exists ? "(no matching History)" : "(no History yet)")
            return
        }
        let localTime = DateFormatter()
        localTime.dateFormat = "yyyy-MM-dd HH:mm"
        let parser = ISO8601DateFormatter()
        parser.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        for item in page.items {
            let when = parser.date(from: item.createdAt).map(localTime.string(from:)) ?? item.createdAt
            let duration = item.durationSeconds.map { unsafe String(format: "%.1fs", $0) } ?? "-"
            let indent = item.longFormRole == "segment" ? "  " : ""
            let preview = item.text.count > 60 ? String(item.text.prefix(60)) + "…" : item.text
            let missing = item.audioExists ? "" : "  (audio missing)"
            print("\(indent)\(item.id)\t\(when)\t\(item.mode)\t\(duration)\t\(preview)\(missing)")
        }
        if page.hasMore {
            note("more rows: raise --limit (at most 500) or narrow with --mode or a search")
        }
    }

    static func show(_ reader: DesktopHistoryReader, id: Int64) throws {
        guard let detail = try reader.detail(id: id) else {
            throw CLIError(.historyItemNotFound, "no History item \(id)", hint: "see `vocello history list`")
        }
        if CLIPresenter.isMachine {
            CLIPresenter.succeed(Shown(item: detail.item, completionReceipt: detail.completionReceipt))
            return
        }
        let item = detail.item
        print("\(item.id)\t\(item.createdAt)\t\(item.mode)")
        if let voice = item.voice { print("voice: \(voice)") }
        if let delivery = item.delivery { print("delivery: \(delivery)") }
        if let seed = item.seed { print("seed: \(seed)") }
        if let role = item.longFormRole { print("long-form: \(role) of \(item.longFormProjectID ?? "?")") }
        print("audio: \(item.audioPath)\(item.audioExists ? "" : " (missing)")")
        print("text: \(item.text)")
    }

    static func export(_ reader: DesktopHistoryReader, id: Int64, _ args: Args) throws {
        guard let detail = try reader.detail(id: id) else {
            throw CLIError(.historyItemNotFound, "no History item \(id)", hint: "see `vocello history list`")
        }
        let source = URL(fileURLWithPath: detail.item.audioPath)
        guard detail.item.audioExists else {
            throw CLIError(.inputFileNotFound, "History item \(id)'s audio file is gone")
        }
        let out = try args.require("out", "a .wav file path to copy the take to")
        let destination = URL(fileURLWithPath: (out as NSString).expandingTildeInPath).standardizedFileURL
        do {
            try DesktopHistoryExport.check(
                destination: destination, source: source, replace: args.flag("replace"), isTakeAudio: reader.isTakeAudio
            )
        } catch let refusal as DesktopHistoryExport.Refusal {
            switch refusal {
            case .notWAV:
                throw CLIError(.invalidInput, "--out must name a .wav file (got \(out))")
            case .missingFolder:
                throw CLIError(.outputUnavailable, "the folder \(destination.deletingLastPathComponent().path) does not exist")
            case .isFolder:
                throw CLIError(.outputUnavailable, "\(destination.path) is a folder; pass a .wav file path inside it")
            case .exists:
                throw CLIError(.outputUnavailable, "\(destination.path) exists", hint: "pass --replace to overwrite it")
            case .anotherTake:
                throw CLIError(.outputUnavailable, "\(destination.path) is another take in History and is never overwritten")
            }
        }
        let outcome = try DesktopHistoryExport.copy(from: source, to: destination)
        let bytes = ((try? FileManager.default.attributesOfItem(atPath: destination.path))?[.size] as? NSNumber)?.int64Value ?? 0
        if CLIPresenter.isMachine {
            CLIPresenter.succeed(Exported(id: String(id), destination: destination.path, outcome: outcome, bytes: bytes))
        } else {
            print(destination.path)
        }
    }
}

/// `vocello settings`: the Mac app's settings, read-only here (RF-26).
enum SettingsCommand {
    struct Rows: Encodable, Sendable {
        let domain: String
        let settings: [DesktopAppSettings.Entry]
    }

    struct One: Encodable, Sendable {
        let setting: DesktopAppSettings.Entry
    }

    @MainActor
    static func run(action: String, _ args: Args) async throws {
        let settings = DesktopAppSettings()
        switch action {
        case "get":
            let name = args.positionals.first ?? ""
            guard let entry = settings.entry(name) else {
                throw CLIError(
                    .invalidInput, "unknown setting '\(name)'",
                    hint: "one of: \(DesktopAppSettings.names.joined(separator: ", "))"
                )
            }
            if CLIPresenter.isMachine {
                CLIPresenter.succeed(One(setting: entry))
            } else {
                print(entry.value)
            }
        default:
            let entries = settings.all()
            if CLIPresenter.isMachine {
                CLIPresenter.succeed(Rows(domain: settings.domain, settings: entries))
                return
            }
            for entry in entries {
                print("\(entry.name)\t\(entry.value)\(entry.isDefault ? "  (default)" : "")")
            }
        }
    }
}

/// `vocello briefs`: Voice Design's starting briefs, by position (RF-26).
enum BriefsCommand {
    struct Rows: Encodable, Sendable {
        let language: String
        let descriptionLimit: Int
        let briefs: [DesktopBriefCatalog.Brief]
    }

    @MainActor
    static func run(_ args: Args) async throws {
        let language = try GenerateCommand.parseLanguage(args) ?? .english
        let briefs = DesktopBriefCatalog.briefs(in: language)
        if CLIPresenter.isMachine {
            CLIPresenter.succeed(Rows(
                language: language.rawValue, descriptionLimit: DesktopBriefCatalog.descriptionLimit, briefs: briefs
            ))
            return
        }
        for brief in briefs { print("\(brief.index)\t\(brief.text)") }
        note("pass one as --voice-brief \"…\" (at most \(DesktopBriefCatalog.descriptionLimit) characters)")
    }
}
