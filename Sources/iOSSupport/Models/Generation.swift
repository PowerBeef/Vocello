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

    /// The voice as Studio named it. A Built-in Voice take stores its
    /// speaker's ID (`aiden`), which reads as the speaker's display name
    /// (`Aiden`), falling back as Studio does to the capitalized ID when the
    /// registry does not know it; a saved voice or a voice description reads
    /// as stored (BKL-37). `speakerName` looks a speaker ID up in the
    /// platform's registry, which the desktop core does not compile.
    func voiceDisplayName(speakerName: (String) -> String?) -> String? {
        guard let voice = voice?.trimmingCharacters(in: .whitespacesAndNewlines), !voice.isEmpty else {
            return nil
        }
        guard mode == GenerationMode.custom.rawValue else { return voice }
        return speakerName(voice) ?? voice.capitalized
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
        self.init(rowWithoutReceipt: row)
        completionReceipt = try Self.storedReceipt(in: row)
    }

    /// Every column but the completion receipt.
    private init(rowWithoutReceipt row: Row) {
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
    }

    /// The row's stored receipt. GRDB's Codable record encoder stores nested
    /// Codable values as JSON. A malformed stored receipt fails the read
    /// instead of disappearing.
    private static func storedReceipt(in row: Row) throws -> GenerationCompletionReceipt? {
        let receiptJSON: String? = row[Columns.completionReceipt]
        return try receiptJSON.map {
            try databaseJSONDecoder(for: Columns.completionReceipt.rawValue)
                .decode(GenerationCompletionReceipt.self, from: Data($0.utf8))
        }
    }

    /// `row` for a read-only listing (the CLI's History), which shows the takes
    /// it can and owns no recovery: a stored receipt this build cannot decode
    /// (malformed, or a shape it does not know) leaves the row without one and
    /// says so, instead of failing the read. The apps' own reads stay strict
    /// (`init(row:)`).
    static func keepingUnreadableReceipt(_ row: Row) -> (generation: Generation, receiptUnreadable: Bool) {
        var generation = Generation(rowWithoutReceipt: row)
        do {
            generation.completionReceipt = try storedReceipt(in: row)
            return (generation, false)
        } catch {
            return (generation, true)
        }
    }

    mutating func didInsert(_ inserted: InsertionSuccess) {
        id = inserted.rowID
    }
}
