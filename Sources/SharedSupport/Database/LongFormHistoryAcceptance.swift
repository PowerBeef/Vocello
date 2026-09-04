import CryptoKit
import Foundation
import GRDB
import QwenVoiceCore

enum LongFormAcceptanceError: LocalizedError, Equatable {
    case invalidCandidate
    case recoveryRequired

    var errorDescription: String? {
        switch self {
        case .invalidCandidate:
            return VocelloPresentationText.longFormSaveFailed
        case .recoveryRequired:
            return VocelloPresentationText.longFormRecoveryRequired
        }
    }
}

/// Private app-local transaction input, never a telemetry/export record. Audio
/// has already passed segment and joined QC. Files have unique candidate names;
/// no accepted WAV may be overwritten while preparing this value.
struct LongFormHistoryAcceptance: Sendable {
    let manifestURL: URL
    let manifest: LongFormManifestV4
    let segments: [Generation]
    let joined: Generation
    let joinedQCPassed: Bool
    /// Only newly produced, discardable files (not retained in-session segments).
    let ownedAudioURLs: [URL]

    static func uniqueAudioURL(basedOn url: URL) -> URL {
        url.deletingLastPathComponent().appendingPathComponent(
            "\(url.deletingPathExtension().lastPathComponent)_\(UUID().uuidString).wav"
        )
    }
}

/// Called exclusively on the existing serial GRDB writer, including recovery.
/// The SQLite row at the unique joined audio path is the commit witness. The
/// journal is written before the manifest; it survives until a subsequent queue
/// operation observes the committed row or restores the previous manifest.
/// No suspension, actor reentrancy, second database, or schema migration occurs
/// inside the filesystem/SQLite commit boundary.
struct LongFormHistoryAcceptanceStore: Sendable {
    let rootURL: URL
    static let maximumJournalBytes = 8 * 1_024 * 1_024
    static let maximumPendingTransactions = 64

    func commit(_ input: LongFormHistoryAcceptance, using queue: DatabaseQueue) async throws -> Generation {
        try Task.checkCancellation()
        do {
            let saved = try await queue.write { db in
                try reconcile(in: db)
                try prepare(input, in: db)
                return try saveRows(input, in: db)
            }
            try await queue.write { db in try reconcile(in: db) }
            return saved
        } catch {
            // GRDB has ended/rolled back the write before this block executes.
            // If final housekeeping failed after COMMIT, the witness preserves
            // that success; never erase committed audio because cleanup threw.
            do {
                let committed = try await queue.write { db in
                    try reconcile(in: db)
                    guard let record = try Generation.filter(Generation.Columns.audioPath == input.joined.audioPath).fetchOne(db),
                          Self.matchesCommit(record, input.joined),
                          try readManifestIfPresent(input.manifestURL) == input.manifest.canonicalJSONData()
                    else { return Optional<Generation>.none }
                    return record
                }
                if let committed { return committed }
            } catch { throw LongFormAcceptanceError.recoveryRequired }
            throw LongFormAcceptanceError.invalidCandidate
        }
    }

    private struct Journal: Codable {
        let version: Int
        let manifestURL: URL
        let candidate: Data
        let previous: Data?
        let joined: Generation
        let ownedAudioURLs: [URL]
    }

    private struct Envelope: Codable {
        let payload: Data
        let digest: String
    }

    /// Must execute in the same SQLite transaction as all segment/joined writes.
    func prepare(_ input: LongFormHistoryAcceptance, in db: Database) throws {
        _ = try input.manifest.validated()
        guard let execution = input.manifest.execution,
              input.manifest.assembly?.outputReadable == true,
              input.joinedQCPassed,
              !execution.segments.isEmpty,
              execution.segments.allSatisfy({ $0.generated && $0.qcPassed == true }),
              input.segments.count == execution.segments.count,
              input.joined.longFormProjectID == input.manifest.plan.planDigest,
              input.joined.longFormRole == "joined",
              input.segments.allSatisfy({
                  $0.longFormProjectID == input.joined.longFormProjectID && $0.longFormRole == "segment"
              }),
              Set((input.segments + [input.joined]).map(\.audioPath)).count == input.segments.count + 1,
              try Generation.filter(Generation.Columns.audioPath == input.joined.audioPath).fetchCount(db) == 0
        else { throw LongFormAcceptanceError.invalidCandidate }
        for record in input.segments + [input.joined] {
            try requireRegularFile(URL(fileURLWithPath: record.audioPath))
        }
        let candidatePaths = Set((input.segments + [input.joined]).map(\.audioPath))
        for url in input.ownedAudioURLs {
            guard candidatePaths.contains(url.path),
                  try Generation.filter(Generation.Columns.audioPath == url.path).fetchCount(db) == 0
            else { throw LongFormAcceptanceError.invalidCandidate }
        }
        try requireLocalManifest(input.manifestURL)
        let data = try input.manifest.canonicalJSONData() // Encoding errors are never swallowed.
        let previous = try readManifestIfPresent(input.manifestURL)
        let journal = Journal(version: 1, manifestURL: input.manifestURL,
                              candidate: data, previous: previous, joined: input.joined,
                              ownedAudioURLs: input.ownedAudioURLs)
        let payload = try JSONEncoder().encode(journal)
        let envelope = try JSONEncoder().encode(Envelope(payload: payload, digest: Self.digest(payload)))
        guard envelope.count <= Self.maximumJournalBytes else { throw LongFormAcceptanceError.invalidCandidate }
        try FileManager.default.createDirectory(at: rootURL, withIntermediateDirectories: true)
        guard try journalURLs().count < Self.maximumPendingTransactions else {
            throw LongFormAcceptanceError.recoveryRequired
        }
        let journalURL = rootURL.appendingPathComponent(Self.digest(Data(input.joined.audioPath.utf8)) + ".json")
        guard !FileManager.default.fileExists(atPath: journalURL.path) else {
            throw LongFormAcceptanceError.recoveryRequired
        }
        try envelope.write(to: journalURL, options: .atomic)
        try data.write(to: input.manifestURL, options: .atomic)
    }

    /// SQLite performs the segment additions and joined-row replacement in one
    /// transaction. Unchanged and superseded segment rows remain valid History;
    /// accepted/referenced audio is never deleted as transaction cleanup.
    func saveRows(_ input: LongFormHistoryAcceptance, in db: Database) throws -> Generation {
        for var segment in input.segments {
            if let existing = try Generation.filter(Generation.Columns.audioPath == segment.audioPath).fetchOne(db) {
                guard Self.matchesCommit(existing, segment) else { throw LongFormAcceptanceError.invalidCandidate }
            } else {
                try segment.insert(db)
            }
        }
        try db.execute(sql: "DELETE FROM generations WHERE longFormProjectID = ? AND longFormRole = 'joined'",
                       arguments: [input.joined.longFormProjectID])
        var joined = input.joined
        try joined.insert(db)
        return joined
    }

    /// Invoke before every History read/write, not merely at app launch. A failed
    /// commit cannot be exposed as an accepted project or bypassed by clear-all.
    func reconcile(in db: Database) throws {
        for url in try journalURLs() {
            do {
                try requireRegularFile(url)
                let size = try url.resourceValues(forKeys: [.fileSizeKey]).fileSize ?? 0
                guard size <= Self.maximumJournalBytes else { throw LongFormAcceptanceError.recoveryRequired }
                let envelope = try JSONDecoder().decode(Envelope.self, from: Data(contentsOf: url))
                guard envelope.digest == Self.digest(envelope.payload) else { throw LongFormAcceptanceError.recoveryRequired }
                let journal = try JSONDecoder().decode(Journal.self, from: envelope.payload)
                guard journal.version == 1,
                      url.lastPathComponent == Self.digest(Data(journal.joined.audioPath.utf8)) + ".json"
                else { throw LongFormAcceptanceError.recoveryRequired }
                try requireLocalManifest(journal.manifestURL)
                let current = try readManifestIfPresent(journal.manifestURL)
                // Never overwrite an unrelated edit or silently accept corrupt state.
                guard current == journal.candidate || current == journal.previous else {
                    throw LongFormAcceptanceError.recoveryRequired
                }
                if let committed = try Generation.filter(Generation.Columns.audioPath == journal.joined.audioPath).fetchOne(db) {
                    guard Self.matchesCommit(committed, journal.joined) else { throw LongFormAcceptanceError.recoveryRequired }
                    try requireRegularFile(URL(fileURLWithPath: committed.audioPath))
                    if current != journal.candidate { try journal.candidate.write(to: journal.manifestURL, options: .atomic) }
                } else {
                    if let previous = journal.previous {
                        if current != previous { try previous.write(to: journal.manifestURL, options: .atomic) }
                    } else if current != nil {
                        try FileManager.default.removeItem(at: journal.manifestURL)
                    }
                    for audioURL in journal.ownedAudioURLs {
                        guard try Generation.filter(Generation.Columns.audioPath == audioURL.path).fetchCount(db) == 0 else { continue }
                        if FileManager.default.fileExists(atPath: audioURL.path) {
                            try requireRegularFile(audioURL)
                            try FileManager.default.removeItem(at: audioURL)
                        }
                    }
                }
                try FileManager.default.removeItem(at: url)
            } catch {
                // Corrupt/unrecoverable journals remain bounded and visible via
                // History's existing degraded-state/Retry flow. No raw path leaks.
                throw LongFormAcceptanceError.recoveryRequired
            }
        }
    }

    private func journalURLs() throws -> [URL] {
        guard FileManager.default.fileExists(atPath: rootURL.path) else { return [] }
        let urls = try FileManager.default.contentsOfDirectory(at: rootURL, includingPropertiesForKeys: nil)
            .filter { $0.pathExtension == "json" }.sorted { $0.lastPathComponent < $1.lastPathComponent }
        guard urls.count <= Self.maximumPendingTransactions else { throw LongFormAcceptanceError.recoveryRequired }
        return urls
    }

    private func readManifestIfPresent(_ url: URL) throws -> Data? {
        guard FileManager.default.fileExists(atPath: url.path) else { return nil }
        try requireRegularFile(url)
        guard (try url.resourceValues(forKeys: [.fileSizeKey]).fileSize ?? 0) <= Self.maximumJournalBytes else {
            throw LongFormAcceptanceError.recoveryRequired
        }
        return try Data(contentsOf: url)
    }

    private func requireLocalManifest(_ url: URL) throws {
        guard url.isFileURL, url.pathExtension == "json",
              try url.deletingLastPathComponent().resourceValues(forKeys: [.isSymbolicLinkKey]).isSymbolicLink != true
        else { throw LongFormAcceptanceError.invalidCandidate }
    }

    private func requireRegularFile(_ url: URL) throws {
        let values = try url.resourceValues(forKeys: [.isRegularFileKey, .isSymbolicLinkKey])
        guard url.isFileURL, values.isRegularFile == true, values.isSymbolicLink != true else {
            throw LongFormAcceptanceError.invalidCandidate
        }
    }

    private static func digest(_ data: Data) -> String {
        SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
    }

    private static func matchesCommit(_ committed: Generation, _ proposed: Generation) -> Bool {
        // SQLite/GRDB dates have millisecond precision; JSON retains finer
        // precision. Allow only that storage quantization; all other fields
        // except the database-assigned primary key must match exactly.
        guard abs(proposed.createdAt.timeIntervalSince(committed.createdAt)) < 0.001 else { return false }
        var expected = proposed
        expected.id = committed.id
        expected.createdAt = committed.createdAt
        return expected == committed
    }
}
