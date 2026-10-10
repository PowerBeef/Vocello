import Foundation
import GRDB
import QwenVoiceCore

/// A record of a single TTS generation, stored in SQLite via GRDB.
struct Generation: Identifiable, Codable, Hashable, Sendable {
    var id: Int64?
    var text: String
    var mode: String            // "custom", "design", "clone"
    var modelTier: String       // "pro", "lite"
    var voice: String?          // speaker name or voice description
    var emotion: String?
    var speed: Double?
    var audioPath: String
    var duration: Double?
    var createdAt: Date
    /// Long-form project association: the owning plan digest, or nil for
    /// ordinary single takes.
    var longFormProjectID: String?
    /// "segment" or "joined" within a long-form project; nil otherwise.
    var longFormRole: String?
    /// The engine's effective sampling seed for this take (UInt64 stored as
    /// its Int64 bit pattern), or nil for rows recorded before v6 (DP-15).
    var seed: Int64?
    /// Versioned provenance stored with this row and its recovery journal.
    /// Legacy/assembled outputs have no single-request receipt.
    var completionReceipt: GenerationCompletionReceipt? = nil
    /// Display-friendly date string in the interface locale (PA-20: never the
    /// process locale, which ignores the in-app language).
    func formattedDate(in localization: VocelloLocalization) -> String {
        localization.dateTime(createdAt)
    }

    /// Short text preview (first 60 chars)
    var textPreview: String {
        if text.count <= 60 { return text }
        return String(text.prefix(60)) + "..."
    }

    /// The effective sampling seed as the engine reported it.
    var samplingSeed: UInt64? {
        seed.map { UInt64(bitPattern: $0) }
    }

    /// Whether the audio file still exists on disk
    var audioFileExists: Bool {
        FileManager.default.fileExists(atPath: audioPath)
    }

    /// Shared accessibility identifier used by history UIs across platforms.
    var historyAccessibilityID: String {
        if let generationID = id {
            return "generation-\(generationID)"
        }
        return "generation-\(audioPath)-\(createdAt.timeIntervalSince1970)"
    }
}

// MARK: - GRDB TableRecord + FetchableRecord + PersistableRecord

extension Generation: TableRecord, FetchableRecord, MutablePersistableRecord {
    static let databaseTableName = "generations"

    enum Columns: String, ColumnExpression {
        case id, text, mode, modelTier, voice, emotion, speed, audioPath, duration, createdAt
        case longFormProjectID, longFormRole, seed, completionReceipt
    }

    init(row: Row) throws {
        id = row[Columns.id]
        text = row[Columns.text]
        mode = row[Columns.mode]
        modelTier = row[Columns.modelTier]
        voice = row[Columns.voice]
        emotion = row[Columns.emotion]
        speed = row[Columns.speed]
        audioPath = row[Columns.audioPath]
        duration = row[Columns.duration]
        createdAt = row[Columns.createdAt]
        longFormProjectID = row[Columns.longFormProjectID]
        longFormRole = row[Columns.longFormRole]
        seed = row[Columns.seed]
        // GRDB's Codable record encoder stores nested Codable values as JSON.
        // A malformed stored receipt fails the read instead of disappearing.
        let receiptJSON: String? = row[Columns.completionReceipt]
        completionReceipt = try receiptJSON.map {
            try Self.databaseJSONDecoder(for: Columns.completionReceipt.rawValue)
                .decode(GenerationCompletionReceipt.self, from: Data($0.utf8))
        }
    }

    mutating func didInsert(_ inserted: InsertionSuccess) {
        id = inserted.rowID
    }
}
