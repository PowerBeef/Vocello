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
}

/// A page of History: the Mac app's listing (a long-form project's segments
/// follow their joined row unless a search lists matches flat).
public struct DesktopHistoryPage: Encodable, Sendable {
    public let items: [DesktopHistoryItem]
    public let hasMore: Bool
    /// Every row in History, whatever the filter.
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
    /// The store was written by a newer Vocello: these migrations are unknown here.
    case schemaNewer
    /// The store predates migrations this build expects; the app upgrades it on launch.
    case schemaOlder
    /// The store is busy or mid-recovery (a hot journal a read-only reader cannot roll back).
    case busy

    public var errorDescription: String? {
        switch self {
        case .schemaNewer:
            return "History was written by a newer Vocello; update the CLI to read it"
        case .schemaOlder:
            return "History has not been upgraded yet; open Vocello once to upgrade it"
        case .busy:
            return "History is busy; retry in a moment"
        }
    }
}

/// Reads the History the Mac app owns, without ever writing it: a read-only
/// connection, no migration, no path rebase and no recovery reconcile (those
/// stay the app's). It refuses a schema it does not know. Each call opens, reads
/// in one short transaction and closes, so the app's writer waits at most for
/// that read.
public struct DesktopHistoryReader: Sendable {
    public let root: URL

    public init(root: URL) {
        self.root = root
    }

    public var databaseURL: URL { root.appendingPathComponent("history.sqlite", isDirectory: false) }

    public var exists: Bool { FileManager.default.fileExists(atPath: databaseURL.path) }

    /// A pending long-form recovery journal: the app reconciles it on its next read.
    public var longFormRecoveryPending: Bool {
        let journal = root.appendingPathComponent("history-outbox/long-form", isDirectory: true)
        let entries = (try? FileManager.default.contentsOfDirectory(atPath: journal.path)) ?? []
        return entries.contains { !$0.hasPrefix(".") }
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
        let page = try read { db in
            try GenerationHistoryPageQuery.fetch(request, includesLongFormProjects: !pending, in: db)
        }
        return DesktopHistoryPage(
            items: page.rows.map(Self.item), hasMore: page.hasMore, totalCount: page.archiveCount,
            longFormRecoveryPending: pending
        )
    }

    /// The row with this id, or nil.
    public func detail(id: Int64) throws -> DesktopHistoryDetail? {
        guard exists else { return nil }
        let row = try read { db in try Generation.fetchOne(db, key: id) }
        return row.map { DesktopHistoryDetail(item: Self.item($0), completionReceipt: $0.completionReceipt) }
    }

    private func read<T>(_ body: (Database) throws -> T) throws -> T {
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
        } catch let error as DatabaseError where error.resultCode == .SQLITE_BUSY || error.resultCode == .SQLITE_LOCKED {
            throw DesktopHistoryError.busy
        }
    }

    static func item(_ row: Generation) -> DesktopHistoryItem {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        formatter.timeZone = TimeZone(identifier: "UTC")
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
            seed: row.samplingSeed.map { String($0) }
        )
    }
}

/// Copies a History take to a destination the caller chose, the way the Mac
/// app's Save As does: the bytes land beside the destination and replace it
/// only once complete; a failure never removes an existing destination.
public enum DesktopHistoryExport {
    public enum Outcome: String, Encodable, Sendable { case copied, sameFile = "same_file" }

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
