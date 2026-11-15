import Foundation
import GRDB
import QwenVoiceCore

/// The order of a History listing, as the Mac app's History sorts it.
public enum DesktopHistoryOrder: String, CaseIterable, Sendable {
    case newest, oldest, longest, shortest, mode

    var pageOrder: GenerationHistoryPageRequest.Order {
        switch self {
        case .newest: return .newest
        case .oldest: return .oldest
        case .longest: return .longest
        case .shortest: return .shortest
        case .mode: return .mode
        }
    }
}

/// One History row as the CLI reports it. 64-bit values are decimal strings.
public struct DesktopHistoryItem: Encodable, Sendable, Equatable {
    public let id: String
    public let text: String
    public let mode: String
    /// The speaker, voice description or saved voice the take used.
    public let voice: String?
    public let delivery: String?
    public let audioPath: String
    public let audioExists: Bool
    public let durationSeconds: Double?
    /// ISO 8601 with fractional seconds, in UTC.
    public let createdAt: String
    public let longFormProjectID: String?
    /// `segment` or `joined` within a long-form project; nil for a single take.
    public let longFormRole: String?
    /// The take's effective sampling seed; nil for rows recorded before seeds were kept.
    public let seed: String?
    /// True when the row holds a completion receipt this build cannot decode
    /// (malformed, or written in a shape it does not know): the row is listed
    /// without it. Absent otherwise.
    public let completionReceiptUnreadable: Bool?
}

/// A page of History: the Mac app's listing (a long-form project's segments
/// follow their joined row unless a search lists matches flat).
public struct DesktopHistoryPage: Encodable, Sendable {
    public let items: [DesktopHistoryItem]
    public let hasMore: Bool
    /// Every row in History, whatever the filter; project rows are left out
    /// while a long-form recovery is pending, as the app counts them.
    public let totalCount: Int
    /// A long-form project awaits recovery in the app, so project rows are withheld.
    public let longFormRecoveryPending: Bool
}

/// One History row with the engine's completion receipt, when it recorded one.
public struct DesktopHistoryDetail: Encodable, Sendable {
    public let item: DesktopHistoryItem
    public let completionReceipt: GenerationCompletionReceipt?
}

public enum DesktopHistoryError: Error, Equatable, LocalizedError {
    /// The store, or a record in it, was written by a newer Vocello.
    case schemaNewer
    /// The store predates migrations this build expects; the app upgrades it on launch.
    case schemaOlder
    /// The store is busy or mid-recovery (a hot journal a read-only reader cannot roll back).
    case busy
    /// The Vocello app is running on this store. Until History has a
    /// cross-process lock (RF-30), the app's writes fail outright when another
    /// process holds even a read, so the CLI reads History only while the app is closed.
    case appRunning
    /// The store is not a readable database.
    case damaged

    public var errorDescription: String? {
        switch self {
        case .schemaNewer:
            return "History was written by a newer Vocello; update the CLI to read it"
        case .schemaOlder:
            return "History has not been upgraded yet; open Vocello once to upgrade it"
        case .busy:
            return "History is busy or recovering from an interrupted write; retry in a moment"
        case .appRunning:
            return "the Vocello app is running and owns History; the CLI reads it only while the app is closed"
        case .damaged:
            return "History is not a readable database; open Vocello to recover it"
        }
    }
}

/// Reads the History the Mac app owns, without ever writing it: a read-only
/// connection, no migration, no path rebase and no recovery reconcile (those
/// stay the app's). It refuses a schema it does not know. Each call opens,
/// reads in one short transaction and closes.
///
/// The app opens History with SQLite's immediate-error busy mode, so while a
/// reader holds its shared lock the app's commit fails at once instead of
/// waiting. Until the app gains a busy timeout and the cross-process History
/// lock (RF-30, after the iPhone submission), every read is refused while the
/// app is running on the same data root (`appIsUsingRoot`).
public struct DesktopHistoryReader: Sendable {
    public let root: URL
    private let appIsUsingRoot: @Sendable (URL) -> Bool

    public init(
        root: URL,
        appIsUsingRoot: @escaping @Sendable (URL) -> Bool = {
            DesktopAppPresence.isAppDataRoot($0) && DesktopAppPresence.isAppRunning()
        }
    ) {
        self.root = root
        self.appIsUsingRoot = appIsUsingRoot
    }

    public var databaseURL: URL { root.appendingPathComponent("history.sqlite", isDirectory: false) }

    public var exists: Bool { FileManager.default.fileExists(atPath: databaseURL.path) }

    /// A pending long-form recovery journal, decided as the app decides it
    /// (`LongFormHistoryAcceptanceStore.hasPendingRecovery`): any `*.json`
    /// journal is pending, a discarded one (renamed `.unreadable`) is not, and a
    /// folder that cannot be read counts as pending.
    public var longFormRecoveryPending: Bool {
        let journal = root.appendingPathComponent("history-outbox/long-form", isDirectory: true)
        guard FileManager.default.fileExists(atPath: journal.path) else { return false }
        do {
            return try FileManager.default.contentsOfDirectory(at: journal, includingPropertiesForKeys: nil)
                .contains { $0.pathExtension == "json" }
        } catch {
            return true
        }
    }

    /// Whether some History take's audio is the file at `url` (an export or a
    /// take must not overwrite it). Paths match regardless of letter case, as
    /// the Mac's default volume names the same file.
    public func isTakeAudio(_ url: URL) throws -> Bool {
        guard exists else { return false }
        let path = url.standardizedFileURL.path
        return try read { db in
            try Bool.fetchOne(
                db, sql: "SELECT EXISTS(SELECT 1 FROM generations WHERE audioPath = ? COLLATE NOCASE)", arguments: [path]
            )
        } ?? false
    }

    public func page(
        mode: String? = nil,
        query: String = "",
        order: DesktopHistoryOrder = .newest,
        limit: Int = 50
    ) throws -> DesktopHistoryPage {
        guard exists else {
            return DesktopHistoryPage(items: [], hasMore: false, totalCount: 0, longFormRecoveryPending: false)
        }
        let pending = longFormRecoveryPending
        let request = GenerationHistoryPageRequest(
            mode: mode, query: query, searchStyle: .lowercasedTranscriptAndVoice,
            order: order.pageOrder, limit: max(1, limit)
        )
        // Each row decodes its own receipt, so one that cannot be read marks its
        // row instead of failing the page.
        let (page, unreadable) = try read { db -> (GenerationHistoryPage, Set<Int64>) in
            var unreadable: Set<Int64> = []
            let page = try GenerationHistoryPageQuery.fetch(
                request, includesLongFormProjects: !pending, in: db,
                decodingRowsWith: { row in
                    let kept = Generation.keepingUnreadableReceipt(row)
                    if kept.receiptUnreadable, let id = kept.generation.id { unreadable.insert(id) }
                    return kept.generation
                }
            )
            return (page, unreadable)
        }
        return DesktopHistoryPage(
            items: page.rows.map { row in
                Self.item(row, receiptUnreadable: row.id.map { unreadable.contains($0) } ?? false)
            },
            hasMore: page.hasMore, totalCount: page.archiveCount, longFormRecoveryPending: pending
        )
    }

    /// The row with this id, or nil. A receipt that cannot be decoded marks the
    /// row (`completionReceiptUnreadable`) and is left out.
    public func detail(id: Int64) throws -> DesktopHistoryDetail? {
        guard exists else { return nil }
        let kept = try read { db in
            try Row.fetchOne(db, sql: "SELECT * FROM generations WHERE id = ?", arguments: [id])
                .map(Generation.keepingUnreadableReceipt)
        }
        return kept.map {
            DesktopHistoryDetail(
                item: Self.item($0.generation, receiptUnreadable: $0.receiptUnreadable),
                completionReceipt: $0.generation.completionReceipt
            )
        }
    }

    private func read<T>(_ body: (Database) throws -> T) throws -> T {
        if appIsUsingRoot(root) {
            throw DesktopHistoryError.appRunning
        }
        var configuration = Configuration()
        configuration.readonly = true
        configuration.busyMode = .timeout(2)
        configuration.label = "vocello.cli.history"
        do {
            let queue = try DatabaseQueue(path: databaseURL.path, configuration: configuration)
            return try queue.read { db in
                let migrator = GenerationMigrations.makeMigrator()
                if try migrator.hasBeenSuperseded(db) { throw DesktopHistoryError.schemaNewer }
                if try !migrator.hasCompletedMigrations(db) { throw DesktopHistoryError.schemaOlder }
                return try body(db)
            }
        } catch let error as DatabaseError {
            switch error.resultCode {
            case .SQLITE_BUSY, .SQLITE_LOCKED:
                throw DesktopHistoryError.busy
            case .SQLITE_READONLY:
                // A hot journal (an interrupted write) a read-only reader cannot roll back.
                throw DesktopHistoryError.busy
            case .SQLITE_CORRUPT, .SQLITE_NOTADB:
                throw DesktopHistoryError.damaged
            default:
                throw error
            }
        } catch is DecodingError {
            // A record (such as a completion receipt) from a newer Vocello.
            throw DesktopHistoryError.schemaNewer
        }
    }

    static func item(_ row: Generation, receiptUnreadable: Bool = false) -> DesktopHistoryItem {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return DesktopHistoryItem(
            id: row.id.map { String($0) } ?? "",
            text: row.text,
            mode: row.mode,
            voice: row.voice,
            delivery: row.emotion,
            audioPath: row.audioPath,
            audioExists: row.audioFileExists,
            durationSeconds: row.duration,
            createdAt: formatter.string(from: row.createdAt),
            longFormProjectID: row.longFormProjectID,
            longFormRole: row.longFormRole,
            seed: row.samplingSeed.map { String($0) },
            completionReceiptUnreadable: receiptUnreadable ? true : nil
        )
    }
}

/// Copies a History take to a destination the caller chose, the way the Mac
/// app's Save As does: the bytes land beside the destination and replace it
/// only once complete; a failure never removes an existing destination.
public enum DesktopHistoryExport {
    public enum Outcome: String, Encodable, Sendable { case copied, sameFile = "same_file" }

    /// Why a destination cannot receive a take.
    public enum Refusal: Error, Equatable {
        case notWAV
        case missingFolder
        case isFolder
        case exists
        case anotherTake
    }

    /// Checks `destination` for `source`: a `.wav` file in an existing folder,
    /// never a folder, never another History take's audio, and an existing
    /// file only with `replace` (the take's own file is always fine: nothing is copied).
    public static func check(
        destination: URL, source: URL, replace: Bool, isTakeAudio: (URL) throws -> Bool
    ) throws {
        guard destination.pathExtension.lowercased() == "wav" else { throw Refusal.notWAV }
        if MacFileSaveCopy.isSameFile(source, destination) { return }
        var isDirectory: ObjCBool = false
        guard unsafe FileManager.default.fileExists(
            atPath: destination.deletingLastPathComponent().path, isDirectory: &isDirectory
        ), isDirectory.boolValue else { throw Refusal.missingFolder }
        if unsafe FileManager.default.fileExists(atPath: destination.path, isDirectory: &isDirectory) {
            guard !isDirectory.boolValue else { throw Refusal.isFolder }
            guard try !isTakeAudio(destination) else { throw Refusal.anotherTake }
            guard replace else { throw Refusal.exists }
        }
    }

    public static func copy(from source: URL, to destination: URL) throws -> Outcome {
        switch try MacFileSaveCopy.copy(from: source, to: destination) {
        case .copied: return .copied
        case .sameFile: return .sameFile
        }
    }

    /// The name the app suggests when exporting a take with this file name.
    public static func suggestedName(forTakeNamed name: String) -> String {
        GenerationOutputFileName.exportName(forTakeNamed: name)
    }
}
