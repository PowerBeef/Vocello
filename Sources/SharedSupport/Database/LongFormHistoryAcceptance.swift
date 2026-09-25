import CryptoKit
import Foundation
import GRDB
import QwenVoiceCore

enum LongFormAcceptanceError: LocalizedError, Equatable {
    case invalidCandidate
    case recoveryRequired
    /// A suspended History interrupted the acceptance (IOS-11) and the caller
    /// stopped waiting for it to resume. The acceptance is recorded as
    /// resumable: the first reconcile after resume completes it (PA-30).
    case interrupted

    var errorDescription: String? {
        switch self {
        case .invalidCandidate:
            return VocelloPresentationText.longFormSaveFailed
        case .recoveryRequired:
            return VocelloPresentationText.longFormRecoveryRequired
        case .interrupted:
            return VocelloPresentationText.longFormAcceptanceInterrupted
        }
    }

    /// The candidate audio now belongs to pending recovery, which keeps or
    /// completes it: the caller must never delete it (PA-30).
    var leavesCandidateToRecovery: Bool {
        self != .invalidCandidate
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
/// No actor reentrancy, second database, or schema migration occurs inside the
/// filesystem/SQLite commit boundary. A suspended History (IOS-11) can
/// interrupt it; that acceptance is completed after resume, never rolled back.
struct LongFormHistoryAcceptanceStore: Sendable {
    let rootURL: URL
    /// How often an acceptance a suspended History interrupted retries.
    var suspensionRetryInterval: Duration = .milliseconds(500)
    static let maximumJournalBytes = 8 * 1_024 * 1_024
    static let maximumPendingTransactions = 64
    /// Retries while History stays suspended; about a minute of awake time,
    /// since a suspended app is frozen and wakes after its database resumes.
    static let maximumSuspensionRetries = 120

    func commit(_ input: LongFormHistoryAcceptance, using queue: DatabaseQueue) async throws -> Generation {
        try Task.checkCancellation()
        var resumable = false
        var suspensionRetries = 0
        while true {
            do {
                let saved = try await queue.write { db in try accept(input, in: db) }
                try await queue.write { db in try reconcile(in: db) }
                return saved
            } catch {
                guard HistoryPersistenceError.isSuspensionInterruption(error) else {
                    if error is CancellationError {
                        if resumable { throw LongFormAcceptanceError.interrupted }
                        // Cancelled before anything was prepared: nothing to
                        // recover, and the caller discards its candidate.
                        if !hasJournal(for: input) { throw error }
                    }
                    return try await recover(input, using: queue, resumable: resumable)
                }
                // IOS-11: History was suspended. SQLite rolled back, and nothing
                // is rolled back or discarded on top of that: a prepared
                // acceptance is marked resumable, so any reconcile after resume
                // completes it and its audio is kept, even across a relaunch
                // (PA-30). This call retries until History resumes.
                do {
                    resumable = try markResumable(input) || resumable
                } catch {
                    throw LongFormAcceptanceError.recoveryRequired
                }
                suspensionRetries += 1
                guard suspensionRetries <= Self.maximumSuspensionRetries else {
                    if resumable { throw LongFormAcceptanceError.interrupted }
                    // Nothing was prepared: the acceptance never started, and
                    // the caller may discard its candidate.
                    throw HistoryPersistenceError(operation: .write, failure: .locked)
                }
                do {
                    try await Task.sleep(for: suspensionRetryInterval)
                } catch {
                    if resumable { throw LongFormAcceptanceError.interrupted }
                    throw error
                }
            }
        }
    }

    /// One acceptance attempt in one transaction. A retry finds an acceptance
    /// that committed before a suspension, or that the reconcile has just
    /// completed, and returns it instead of preparing it again.
    private func accept(_ input: LongFormHistoryAcceptance, in db: Database) throws -> Generation {
        try reconcile(in: db)
        if let committed = try committedRecord(for: input, in: db) {
            return committed
        }
        try prepare(input, in: db)
        return try saveRows(input, in: db)
    }

    /// A failure that is not a suspension. GRDB has ended/rolled back the write
    /// before this runs. If final housekeeping failed after COMMIT, the witness
    /// preserves that success; never erase committed audio because cleanup threw.
    /// A resumable acceptance is never reported as an invalid candidate: its
    /// audio belongs to the reconcile that completes it.
    private func recover(
        _ input: LongFormHistoryAcceptance,
        using queue: DatabaseQueue,
        resumable: Bool
    ) async throws -> Generation {
        do {
            let committed = try await queue.write { db in
                try reconcile(in: db)
                return try committedRecord(for: input, in: db)
            }
            if let committed { return committed }
        } catch { throw LongFormAcceptanceError.recoveryRequired }
        if resumable { throw LongFormAcceptanceError.recoveryRequired }
        throw LongFormAcceptanceError.invalidCandidate
    }

    private func committedRecord(for input: LongFormHistoryAcceptance, in db: Database) throws -> Generation? {
        guard let record = try Generation.filter(Generation.Columns.audioPath == input.joined.audioPath).fetchOne(db),
              Self.matchesCommit(record, input.joined),
              try readManifestIfPresent(input.manifestURL) == input.manifest.canonicalJSONData()
        else { return nil }
        return record
    }

    /// Whether this acceptance was prepared; only it writes this journal.
    private func hasJournal(for input: LongFormHistoryAcceptance) -> Bool {
        FileManager.default.fileExists(atPath: journalURL(forJoinedAudioPath: input.joined.audioPath).path)
    }

    /// Records that a suspended History interrupted the prepared acceptance of
    /// `input` (PA-30). `false` when nothing was prepared. A journal that cannot
    /// be verified throws and stays as it is.
    func markResumable(_ input: LongFormHistoryAcceptance) throws -> Bool {
        guard hasJournal(for: input) else { return false }
        let url = journalURL(forJoinedAudioPath: input.joined.audioPath)
        var journal = try readJournal(at: url)
        guard journal.resumableSegments == nil else { return true }
        journal.resumableSegments = input.segments
        try encodeJournal(journal).write(to: url, options: .atomic)
        return true
    }

    private struct Journal: Codable {
        let version: Int
        let manifestURL: URL
        let candidate: Data
        let previous: Data?
        let joined: Generation
        let ownedAudioURLs: [URL]
        /// Present only once a suspended History interrupted this acceptance:
        /// the segment rows it saves. A reconcile then completes the acceptance
        /// with them instead of rolling it back (PA-30). Absent in every
        /// journal written before it existed.
        var resumableSegments: [Generation]?
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
        let envelope = try encodeJournal(journal)
        try FileManager.default.createDirectory(at: rootURL, withIntermediateDirectories: true)
        guard try journalURLs().count < Self.maximumPendingTransactions else {
            throw LongFormAcceptanceError.recoveryRequired
        }
        let destination = journalURL(forJoinedAudioPath: input.joined.audioPath)
        guard !FileManager.default.fileExists(atPath: destination.path) else {
            throw LongFormAcceptanceError.recoveryRequired
        }
        try envelope.write(to: destination, options: .atomic)
        try data.write(to: input.manifestURL, options: .atomic)
    }

    /// SQLite performs the segment additions and joined-row replacement in one
    /// transaction. Unchanged and superseded segment rows remain valid History;
    /// accepted/referenced audio is never deleted as transaction cleanup.
    func saveRows(_ input: LongFormHistoryAcceptance, in db: Database) throws -> Generation {
        try saveRows(segments: input.segments, joined: input.joined, in: db)
    }

    private func saveRows(segments: [Generation], joined: Generation, in db: Database) throws -> Generation {
        for var segment in segments {
            if let existing = try Generation.filter(Generation.Columns.audioPath == segment.audioPath).fetchOne(db) {
                guard Self.matchesCommit(existing, segment) else { throw LongFormAcceptanceError.invalidCandidate }
            } else {
                try segment.insert(db)
            }
        }
        try db.execute(sql: "UPDATE generations SET longFormRole = 'superseded' WHERE longFormProjectID = ? AND longFormRole = 'joined'",
                       arguments: [joined.longFormProjectID])
        var joined = joined
        try joined.insert(db)
        return joined
    }

    /// Invoke before every History write, and before every read while a journal
    /// is pending (`hasPendingRecovery`), not merely at app launch. A failed
    /// commit cannot be exposed as an accepted project or bypassed by clear-all.
    /// A read with no journal pending needs no writer: SQLite shows it only
    /// committed rows, and a committed row is the acceptance witness (AUD-05).
    func reconcile(in db: Database) throws {
        for url in try journalURLs() {
            do {
                let journal = try readJournal(at: url)
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
                } else if let segments = journal.resumableSegments {
                    // A suspended History interrupted this acceptance; nothing
                    // failed (PA-30). Its rows are saved in this write, which may
                    // itself roll back later, so the journal stays until a later
                    // reconcile sees them committed and finishes it above.
                    do {
                        try resume(journal, segments: segments, in: db)
                        continue
                    } catch LongFormAcceptanceError.invalidCandidate {
                        // The acceptance's own verdict: it would have refused
                        // this candidate without the suspension, so it rolls
                        // back as it would have then.
                        try rollBack(journal, current: current, in: db)
                    }
                } else {
                    try rollBack(journal, current: current, in: db)
                }
                try FileManager.default.removeItem(at: url)
            } catch {
                // A suspended History is not damage: the caller sees the
                // transient failure and retries after resume (IOS-11).
                if HistoryPersistenceError.isSuspensionInterruption(error) { throw error }
                // Corrupt/unrecoverable journals remain bounded and visible via
                // History's existing degraded-state/Retry flow. No raw path leaks.
                throw LongFormAcceptanceError.recoveryRequired
            }
        }
    }

    /// Restores the previous manifest and removes the audio only this failed
    /// acceptance produced.
    private func rollBack(_ journal: Journal, current: Data?, in db: Database) throws {
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

    /// Completes an acceptance a suspended History interrupted, with the checks
    /// the acceptance itself made, in a savepoint: a read that goes on after a
    /// failed recovery never commits part of a project. Anything that no longer
    /// holds fails closed, and the journal and every file stay for Retry or
    /// export (PA-30); only the row check, which the acceptance itself would
    /// have failed, throws `invalidCandidate`.
    private func resume(_ journal: Journal, segments: [Generation], in db: Database) throws {
        let joined = journal.joined
        guard joined.longFormRole == "joined",
              let projectID = joined.longFormProjectID,
              !segments.isEmpty,
              segments.allSatisfy({ $0.longFormProjectID == projectID && $0.longFormRole == "segment" }),
              Set((segments + [joined]).map(\.audioPath)).count == segments.count + 1,
              Set(journal.ownedAudioURLs.map(\.path)).isSubset(of: Set((segments + [joined]).map(\.audioPath)))
        else { throw LongFormAcceptanceError.recoveryRequired }
        for record in segments + [joined] {
            do {
                try requireRegularFile(URL(fileURLWithPath: record.audioPath))
            } catch {
                throw LongFormAcceptanceError.recoveryRequired
            }
        }
        try db.inSavepoint {
            _ = try saveRows(segments: segments, joined: joined, in: db)
            return .commit
        }
    }

    private func journalURL(forJoinedAudioPath audioPath: String) -> URL {
        rootURL.appendingPathComponent(Self.digest(Data(audioPath.utf8)) + ".json")
    }

    private func readJournal(at url: URL) throws -> Journal {
        try requireRegularFile(url)
        let size = try url.resourceValues(forKeys: [.fileSizeKey]).fileSize ?? 0
        guard size <= Self.maximumJournalBytes else { throw LongFormAcceptanceError.recoveryRequired }
        let envelope = try JSONDecoder().decode(Envelope.self, from: Data(contentsOf: url))
        guard envelope.digest == Self.digest(envelope.payload) else { throw LongFormAcceptanceError.recoveryRequired }
        let journal = try JSONDecoder().decode(Journal.self, from: envelope.payload)
        guard journal.version == 1,
              url.lastPathComponent == journalURL(forJoinedAudioPath: journal.joined.audioPath).lastPathComponent
        else { throw LongFormAcceptanceError.recoveryRequired }
        return journal
    }

    private func encodeJournal(_ journal: Journal) throws -> Data {
        let payload = try JSONEncoder().encode(journal)
        let envelope = try JSONEncoder().encode(Envelope(payload: payload, digest: Self.digest(payload)))
        guard envelope.count <= Self.maximumJournalBytes else { throw LongFormAcceptanceError.invalidCandidate }
        return envelope
    }

    /// A damaged project must not hide unrelated standalone recordings. Project
    /// rows remain withheld and all mutations still require successful recovery.
    func readableHistory(in db: Database) throws -> [Generation] {
        guard try reconcileBeforeReading(in: db) else {
            return try Generation
                .filter(Generation.Columns.longFormProjectID == nil && Generation.Columns.longFormRole == nil)
                .order(Generation.Columns.createdAt.desc).fetchAll(db)
        }
        return try Generation.order(Generation.Columns.createdAt.desc).fetchAll(db)
    }

    /// Reconciles ahead of a read on the writer. `false` when recovery is
    /// required: the read must then withhold every long-form project row.
    func reconcileBeforeReading(in db: Database) throws -> Bool {
        do {
            try reconcile(in: db)
            return true
        } catch LongFormAcceptanceError.recoveryRequired {
            return false
        }
    }

    var hasPendingRecovery: Bool {
        do { return try !journalURLs().isEmpty }
        catch { return true }
    }

    /// Explicit, user-controlled local export only. Never follow paths decoded
    /// from an untrusted journal, erase it, or pretend exporting repairs it.
    /// The UI warns that these private records contain text and local paths.
    func recoveryExportURLs() throws -> [URL] {
        try journalURLs().map { url in
            try requireRegularFile(url)
            guard (try url.resourceValues(forKeys: [.fileSizeKey]).fileSize ?? 0) <= Self.maximumJournalBytes else {
                throw LongFormAcceptanceError.recoveryRequired
            }
            return url
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
