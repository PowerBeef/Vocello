import Foundation

enum GenerationHistoryOutboxOperation: String, Codable, Sendable {
    case append
    case replaceLongFormJoined
}

struct GenerationHistoryOutboxEntry: Codable, Equatable, Sendable {
    static let schemaVersion = 1

    let schemaVersion: Int
    let id: UUID
    let operation: GenerationHistoryOutboxOperation
    let generation: Generation
    let createdAt: Date

    init(
        id: UUID = UUID(),
        operation: GenerationHistoryOutboxOperation,
        generation: Generation,
        createdAt: Date = Date()
    ) {
        self.schemaVersion = Self.schemaVersion
        self.id = id
        self.operation = operation
        self.generation = generation
        self.createdAt = createdAt
    }
}

struct GenerationHistoryClearTransaction: Codable, Equatable, Sendable {
    static let schemaVersion = 1

    let schemaVersion: Int
    let id: UUID
    let deleteAudio: Bool
    let audioPaths: [String]
    let pendingEntryIDs: [UUID]
    let createdAt: Date
    /// The History rows are gone. A resumed transaction in this phase never
    /// deletes rows again: by then History may hold takes saved after the
    /// clear (AUD-05). Absent, and so `false`, in older transactions.
    let rowsDeleted: Bool
    /// The highest History row id the clear covers. Row ids auto-increment and
    /// are never reused, so a take saved after the clear started always has a
    /// larger id and survives any resume of it (AUD-05). Absent (nil) only in
    /// transactions written before the bound existed; those are never resumed.
    let maxRowID: Int64?

    private enum CodingKeys: String, CodingKey {
        case schemaVersion, id, deleteAudio, audioPaths, pendingEntryIDs, createdAt, rowsDeleted, maxRowID
    }

    init(
        id: UUID = UUID(),
        deleteAudio: Bool,
        audioPaths: [String],
        pendingEntryIDs: [UUID],
        createdAt: Date = Date(),
        rowsDeleted: Bool = false,
        maxRowID: Int64?
    ) {
        self.schemaVersion = Self.schemaVersion
        self.id = id
        self.deleteAudio = deleteAudio
        self.audioPaths = Array(Set(audioPaths)).sorted()
        self.pendingEntryIDs = Array(Set(pendingEntryIDs)).sorted { $0.uuidString < $1.uuidString }
        self.createdAt = createdAt
        self.rowsDeleted = rowsDeleted
        self.maxRowID = maxRowID
    }

    init(from decoder: any Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        schemaVersion = try container.decode(Int.self, forKey: .schemaVersion)
        id = try container.decode(UUID.self, forKey: .id)
        deleteAudio = try container.decode(Bool.self, forKey: .deleteAudio)
        audioPaths = try container.decode([String].self, forKey: .audioPaths)
        pendingEntryIDs = try container.decode([UUID].self, forKey: .pendingEntryIDs)
        createdAt = try container.decode(Date.self, forKey: .createdAt)
        rowsDeleted = try container.decodeIfPresent(Bool.self, forKey: .rowsDeleted) ?? false
        maxRowID = try container.decodeIfPresent(Int64.self, forKey: .maxRowID)
    }

    /// The same transaction, past its row deletion, also naming the audio of
    /// the rows the bounded delete actually removed.
    func markingRowsDeleted(addingAudioPaths deleted: [String] = []) -> GenerationHistoryClearTransaction {
        GenerationHistoryClearTransaction(
            id: id,
            deleteAudio: deleteAudio,
            audioPaths: audioPaths + deleted,
            pendingEntryIDs: pendingEntryIDs,
            createdAt: createdAt,
            rowsDeleted: true,
            maxRowID: maxRowID
        )
    }

    /// The same transaction, never deleting audio unless both it and the
    /// resuming request do: a keep-files clear never escalates (AUD-05).
    func keepingAudio(unless requested: Bool) -> GenerationHistoryClearTransaction {
        GenerationHistoryClearTransaction(
            id: id,
            deleteAudio: deleteAudio && requested,
            audioPaths: audioPaths,
            pendingEntryIDs: pendingEntryIDs,
            createdAt: createdAt,
            rowsDeleted: rowsDeleted,
            maxRowID: maxRowID
        )
    }
}

/// Audio whose History rows are already gone (a clear, or a single delete) but
/// whose file could not be removed. The list outlives the operation so a later
/// reconcile retries the removal; in the app's private storage the file is
/// otherwise unreachable once its row is gone (AUD-05).
struct GenerationHistoryPendingAudioRemovals: Codable, Equatable, Sendable {
    static let schemaVersion = 1

    let schemaVersion: Int
    let audioPaths: [String]

    init(audioPaths: [String]) {
        self.schemaVersion = Self.schemaVersion
        self.audioPaths = Array(Set(audioPaths)).sorted()
    }
}

struct GenerationHistoryOutboxScan: Sendable {
    let entries: [GenerationHistoryOutboxEntry]
    let issueCount: Int
}

enum GenerationHistoryOutboxError: LocalizedError, Equatable, Sendable {
    case unavailable
    case corruptEntry
    case invalidEntryIdentity
    case missingAudio
    case databaseUnavailable
    case clearUnavailable

    var errorDescription: String? {
        switch self {
        case .unavailable:
            return "The finished take could not be queued for History. Its audio remains in the outputs folder."
        case .corruptEntry, .invalidEntryIdentity:
            return "A pending History recovery record could not be verified. Its audio was not deleted."
        case .missingAudio:
            return "A pending History item no longer has an available audio file."
        case .databaseUnavailable:
            return "The finished take is waiting to be added to History. Retry from History when storage is available."
        case .clearUnavailable:
            return "History could not be cleared safely. Existing rows and pending recovery records were preserved."
        }
    }
}

struct GenerationHistoryRecoverySnapshot: Equatable, Sendable {
    static let empty = GenerationHistoryRecoverySnapshot(
        pendingCount: 0,
        availableAudioCount: 0,
        issueCount: 0,
        clearRecoveryPending: false
    )

    let pendingCount: Int
    let availableAudioCount: Int
    let issueCount: Int
    let clearRecoveryPending: Bool
    var unqueuedCount: Int = 0
    var longFormRecoveryPending: Bool = false
    /// Audio of deleted takes that could not be removed yet; Retry removes it.
    var pendingAudioRemovalCount: Int = 0

    var needsAttention: Bool {
        pendingCount > 0 || unqueuedCount > 0 || issueCount > 0 || clearRecoveryPending || longFormRecoveryPending
            || pendingAudioRemovalCount > 0
    }

    /// Only audio of deleted takes is waiting: nothing is queued for History.
    var onlyAudioRemovalsPending: Bool {
        pendingAudioRemovalCount > 0 && pendingCount == 0 && unqueuedCount == 0 && issueCount == 0
            && !clearRecoveryPending && !longFormRecoveryPending
    }
}

struct GenerationHistoryReconciliationResult: Sendable {
    let committed: [Generation]
    let snapshot: GenerationHistoryRecoverySnapshot
}

struct GenerationHistoryClearOutcome: Equatable, Sendable {
    let failedFileRemovals: Int
    let snapshot: GenerationHistoryRecoverySnapshot
}

/// File-backed, app-support-local persistence intent store. Final `.json` entries
/// appear only after an atomic same-directory rename. A valid interrupted
/// `.writing` file is promoted on the next scan; corrupt or identity-mismatched
/// files remain in place and are counted instead of being silently discarded.
struct GenerationHistoryOutboxStore: Sendable {
    let rootURL: URL

    private var clearTransactionURL: URL {
        rootURL.appendingPathComponent("clear-transaction.json", isDirectory: false)
    }

    private var clearTransactionWritingURL: URL {
        rootURL.appendingPathComponent("clear-transaction.writing", isDirectory: false)
    }

    private var audioRemovalsURL: URL {
        rootURL.appendingPathComponent("audio-removals.json", isDirectory: false)
    }

    private var audioRemovalsWritingURL: URL {
        rootURL.appendingPathComponent("audio-removals.writing", isDirectory: false)
    }

    /// Store-owned files that are not outbox entries.
    private var reservedFileNames: Set<String> {
        [
            clearTransactionURL.lastPathComponent,
            clearTransactionWritingURL.lastPathComponent,
            audioRemovalsURL.lastPathComponent,
            audioRemovalsWritingURL.lastPathComponent,
        ]
    }

    func enqueue(
        _ generation: Generation,
        operation: GenerationHistoryOutboxOperation
    ) throws -> GenerationHistoryOutboxEntry {
        guard FileManager.default.fileExists(atPath: generation.audioPath) else {
            throw GenerationHistoryOutboxError.missingAudio
        }
        let entry = GenerationHistoryOutboxEntry(operation: operation, generation: generation)
        do {
            try ensureRoot()
            try publishNewEntry(encode(entry), id: entry.id)
            return entry
        } catch let error as GenerationHistoryOutboxError {
            throw error
        } catch {
            throw GenerationHistoryOutboxError.unavailable
        }
    }

    /// Whether the entry is still queued (a clear may have removed it).
    func containsEntry(id: UUID) -> Bool {
        FileManager.default.fileExists(atPath: entryURL(for: id).path)
    }

    /// Reads every entry. By default a valid interrupted `.writing` file is
    /// promoted; `promotingWrites: false` only reads, for a check that runs
    /// off the coordinator and must not race its promotion (AUD-05).
    func scan(promotingWrites: Bool = true) -> GenerationHistoryOutboxScan {
        do {
            try ensureRoot()
            let urls = try FileManager.default.contentsOfDirectory(
                at: rootURL,
                includingPropertiesForKeys: nil,
                options: [.skipsHiddenFiles]
            )
            var entries: [GenerationHistoryOutboxEntry] = []
            var issues = 0
            let reserved = reservedFileNames
            for url in urls.sorted(by: { $0.lastPathComponent < $1.lastPathComponent }) {
                if reserved.contains(url.lastPathComponent) {
                    continue
                }
                if url.pathExtension == "writing" {
                    do {
                        let entry: GenerationHistoryOutboxEntry = try decode(url)
                        try validate(entry, filenameID: writingFileID(url))
                        // Unpromoted, a final file for the same id may be read
                        // too; the duplicate only repeats its audio path.
                        if promotingWrites {
                            let finalURL = entryURL(for: entry.id)
                            if FileManager.default.fileExists(atPath: finalURL.path) {
                                try FileManager.default.removeItem(at: url)
                            } else {
                                try FileManager.default.moveItem(at: url, to: finalURL)
                            }
                        }
                        entries.append(entry)
                    } catch {
                        // The scan can lose the race with a promotion made
                        // meanwhile (an off-actor enqueue renames its own
                        // `.writing`); the promoted file is then the entry.
                        if !FileManager.default.fileExists(atPath: url.path),
                           let id = writingFileID(url),
                           let promoted: GenerationHistoryOutboxEntry = try? decode(entryURL(for: id)),
                           (try? validate(promoted, filenameID: id)) != nil {
                            entries.append(promoted)
                        } else {
                            issues += 1
                        }
                    }
                } else if url.pathExtension == "json", url != clearTransactionURL {
                    do {
                        let entry: GenerationHistoryOutboxEntry = try decode(url)
                        try validate(entry, filenameID: UUID(uuidString: url.deletingPathExtension().lastPathComponent))
                        entries.append(entry)
                    } catch {
                        // An entry committed and removed since the listing is
                        // gone, not damaged.
                        if FileManager.default.fileExists(atPath: url.path) {
                            issues += 1
                        }
                    }
                }
            }
            entries.sort {
                if $0.createdAt != $1.createdAt { return $0.createdAt < $1.createdAt }
                return $0.id.uuidString < $1.id.uuidString
            }
            return GenerationHistoryOutboxScan(entries: entries, issueCount: issues)
        } catch {
            return GenerationHistoryOutboxScan(entries: [], issueCount: 1)
        }
    }

    func removeEntry(id: UUID) throws {
        let fileManager = FileManager.default
        for url in [entryURL(for: id), writingURL(for: id)] where fileManager.fileExists(atPath: url.path) {
            do {
                try fileManager.removeItem(at: url)
            } catch {
                throw GenerationHistoryOutboxError.unavailable
            }
        }
    }

    func writeClearTransaction(_ transaction: GenerationHistoryClearTransaction) throws {
        do {
            try ensureRoot()
            try atomicWrite(
                encode(transaction),
                to: clearTransactionURL,
                writingURL: clearTransactionWritingURL
            )
        } catch {
            throw GenerationHistoryOutboxError.clearUnavailable
        }
    }

    func loadClearTransaction() throws -> GenerationHistoryClearTransaction? {
        let fileManager = FileManager.default
        // `atomicWrite` completes the `.writing` file before it touches the
        // final one, so a decodable `.writing` is always the newer state: it
        // wins over a stale final file left by an interrupted rewrite (AUD-05).
        if fileManager.fileExists(atPath: clearTransactionWritingURL.path),
           let interrupted: GenerationHistoryClearTransaction = try? decode(clearTransactionWritingURL),
           interrupted.schemaVersion == GenerationHistoryClearTransaction.schemaVersion {
            do {
                if fileManager.fileExists(atPath: clearTransactionURL.path) {
                    try fileManager.removeItem(at: clearTransactionURL)
                }
                try fileManager.moveItem(at: clearTransactionWritingURL, to: clearTransactionURL)
            } catch {
                throw GenerationHistoryOutboxError.clearUnavailable
            }
        } else if !fileManager.fileExists(atPath: clearTransactionURL.path),
                  fileManager.fileExists(atPath: clearTransactionWritingURL.path) {
            throw GenerationHistoryOutboxError.clearUnavailable
        }
        guard fileManager.fileExists(atPath: clearTransactionURL.path) else { return nil }
        do {
            let transaction: GenerationHistoryClearTransaction = try decode(clearTransactionURL)
            guard transaction.schemaVersion == GenerationHistoryClearTransaction.schemaVersion else {
                throw GenerationHistoryOutboxError.corruptEntry
            }
            if fileManager.fileExists(atPath: clearTransactionWritingURL.path) {
                try fileManager.removeItem(at: clearTransactionWritingURL)
            }
            return transaction
        } catch {
            throw GenerationHistoryOutboxError.clearUnavailable
        }
    }

    func removeClearTransaction() throws {
        do {
            let fileManager = FileManager.default
            for url in [clearTransactionURL, clearTransactionWritingURL]
            where fileManager.fileExists(atPath: url.path) {
                try fileManager.removeItem(at: url)
            }
        } catch {
            throw GenerationHistoryOutboxError.clearUnavailable
        }
    }

    /// Audio paths waiting for removal. An interrupted rewrite is promoted like
    /// the clear marker; an unreadable list throws and deletes nothing.
    func loadPendingAudioRemovals() throws -> [String] {
        let fileManager = FileManager.default
        // A decodable `.writing` is always the newer list (see `loadClearTransaction`).
        if fileManager.fileExists(atPath: audioRemovalsWritingURL.path),
           let interrupted: GenerationHistoryPendingAudioRemovals = try? decode(audioRemovalsWritingURL),
           interrupted.schemaVersion == GenerationHistoryPendingAudioRemovals.schemaVersion {
            do {
                if fileManager.fileExists(atPath: audioRemovalsURL.path) {
                    try fileManager.removeItem(at: audioRemovalsURL)
                }
                try fileManager.moveItem(at: audioRemovalsWritingURL, to: audioRemovalsURL)
            } catch {
                throw GenerationHistoryOutboxError.unavailable
            }
        } else if !fileManager.fileExists(atPath: audioRemovalsURL.path),
                  fileManager.fileExists(atPath: audioRemovalsWritingURL.path) {
            throw GenerationHistoryOutboxError.unavailable
        }
        guard fileManager.fileExists(atPath: audioRemovalsURL.path) else { return [] }
        do {
            let removals: GenerationHistoryPendingAudioRemovals = try decode(audioRemovalsURL)
            guard removals.schemaVersion == GenerationHistoryPendingAudioRemovals.schemaVersion else {
                throw GenerationHistoryOutboxError.corruptEntry
            }
            if fileManager.fileExists(atPath: audioRemovalsWritingURL.path) {
                try fileManager.removeItem(at: audioRemovalsWritingURL)
            }
            return removals.audioPaths
        } catch {
            throw GenerationHistoryOutboxError.unavailable
        }
    }

    /// Adds paths to the pending list. A list that cannot be read is set aside
    /// (`unreadableAudioRemovalCount()` reports it as a recovery issue) and a
    /// fresh list starts: the paths it held stay unknown, so nothing they name
    /// is deleted, but a damaged list never blocks the clear or the delete that
    /// has to record new paths (AUD-05).
    func appendPendingAudioRemovals(_ audioPaths: [String]) throws {
        let existing: [String]
        do {
            existing = try loadPendingAudioRemovals()
        } catch {
            try setAsideUnreadableAudioRemovals()
            existing = []
        }
        try writePendingAudioRemovals(existing + audioPaths)
    }

    /// Removal lists set aside because they could not be read. They are kept,
    /// never parsed again, and never deleted by the app.
    func unreadableAudioRemovalCount() -> Int {
        let urls = (try? FileManager.default.contentsOfDirectory(
            at: rootURL,
            includingPropertiesForKeys: nil,
            options: [.skipsHiddenFiles]
        )) ?? []
        return urls.count { $0.pathExtension == Self.unreadableExtension }
    }

    /// `scan()` reads only `.json` and `.writing` files, so a set-aside list is
    /// never mistaken for an outbox entry.
    private static let unreadableExtension = "unreadable"

    private func setAsideUnreadableAudioRemovals() throws {
        let fileManager = FileManager.default
        let stamp = UUID().uuidString.lowercased()
        do {
            for url in [audioRemovalsURL, audioRemovalsWritingURL] where fileManager.fileExists(atPath: url.path) {
                let asideURL = rootURL.appendingPathComponent(
                    "audio-removals-\(stamp).\(url.pathExtension).\(Self.unreadableExtension)",
                    isDirectory: false
                )
                try fileManager.moveItem(at: url, to: asideURL)
            }
        } catch {
            throw GenerationHistoryOutboxError.unavailable
        }
    }

    /// Replaces the pending list; an empty list removes it.
    func writePendingAudioRemovals(_ audioPaths: [String]) throws {
        do {
            if audioPaths.isEmpty {
                let fileManager = FileManager.default
                for url in [audioRemovalsURL, audioRemovalsWritingURL]
                where fileManager.fileExists(atPath: url.path) {
                    try fileManager.removeItem(at: url)
                }
                return
            }
            try ensureRoot()
            try atomicWrite(
                encode(GenerationHistoryPendingAudioRemovals(audioPaths: audioPaths)),
                to: audioRemovalsURL,
                writingURL: audioRemovalsWritingURL
            )
        } catch {
            throw GenerationHistoryOutboxError.unavailable
        }
    }

    private func validate(_ entry: GenerationHistoryOutboxEntry, filenameID: UUID?) throws {
        guard entry.schemaVersion == GenerationHistoryOutboxEntry.schemaVersion else {
            throw GenerationHistoryOutboxError.corruptEntry
        }
        guard filenameID == entry.id else {
            throw GenerationHistoryOutboxError.invalidEntryIdentity
        }
    }

    private func ensureRoot() throws {
        try FileManager.default.createDirectory(at: rootURL, withIntermediateDirectories: true)
    }

    private func entryURL(for id: UUID) -> URL {
        rootURL.appendingPathComponent("\(id.uuidString.lowercased()).json", isDirectory: false)
    }

    private func writingURL(for id: UUID) -> URL {
        rootURL.appendingPathComponent("\(id.uuidString.lowercased()).writing", isDirectory: false)
    }

    private func writingFileID(_ url: URL) -> UUID? {
        UUID(uuidString: url.deletingPathExtension().lastPathComponent)
    }

    private func encode<T: Encodable>(_ value: T) throws -> Data {
        let encoder = JSONEncoder()
        encoder.dateEncodingStrategy = .millisecondsSince1970
        encoder.outputFormatting = [.sortedKeys]
        return try encoder.encode(value)
    }

    private func decode<T: Decodable>(_ url: URL) throws -> T {
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .millisecondsSince1970
        return try decoder.decode(T.self, from: Data(contentsOf: url))
    }

    /// A fresh entry's id is new, so no final file of its own predates it and
    /// none is ever replaced. Enqueue runs off the coordinator, whose scan may
    /// promote this `.writing` first: that is the same publication, so the
    /// entry is in place either way (AUD-05).
    private func publishNewEntry(_ data: Data, id: UUID) throws {
        let fileManager = FileManager.default
        let writing = writingURL(for: id)
        let final = entryURL(for: id)
        do {
            try data.write(to: writing, options: [.atomic])
            try fileManager.moveItem(at: writing, to: final)
        } catch {
            if !fileManager.fileExists(atPath: writing.path), fileManager.fileExists(atPath: final.path) {
                return
            }
            throw GenerationHistoryOutboxError.unavailable
        }
    }

    private func atomicWrite(_ data: Data, to finalURL: URL, writingURL: URL) throws {
        let fileManager = FileManager.default
        if fileManager.fileExists(atPath: writingURL.path) {
            try fileManager.removeItem(at: writingURL)
        }
        do {
            try data.write(to: writingURL, options: [.atomic])
            if fileManager.fileExists(atPath: finalURL.path) {
                try fileManager.removeItem(at: finalURL)
            }
            try fileManager.moveItem(at: writingURL, to: finalURL)
        } catch {
            throw GenerationHistoryOutboxError.unavailable
        }
    }
}

/// Serializes pending commits, replay, and clear-all. Its database closures
/// suspend the actor, so a save can still land while a clear runs; the clear
/// is therefore bounded by the highest row id it captured, and a later take
/// (always a larger id) is never deleted by it (AUD-05). Database writes remain
/// idempotent through the injected audio-identity-aware commit operation.
actor GenerationHistoryRecoveryCoordinator {
    typealias Commit = @Sendable (GenerationHistoryOutboxOperation, Generation) async throws -> Generation
    /// Every History row, or a throw. A read that would withhold rows (a
    /// long-form journal awaiting recovery) must fail instead: the clear's
    /// bound must never cover a row it did not capture (AUD-05).
    typealias FetchAll = @Sendable () async throws -> [Generation]
    /// Deletes the History rows whose id is at most the bound and returns
    /// their audio paths, in one database write.
    typealias DeleteThrough = @Sendable (Int64) async throws -> [String]
    /// The subset of the given audio paths that History rows still reference.
    typealias ReferencedAudioPaths = @Sendable ([String]) async throws -> Set<String>

    private let store: GenerationHistoryOutboxStore
    private let commitGeneration: Commit
    private let fetchAllGenerations: FetchAll
    private let deleteGenerationsThrough: DeleteThrough
    private let referencedAudioPaths: ReferencedAudioPaths
    /// Audio of takes whose commit is awaiting the database. The entry may be
    /// gone already (a clear removed it) while the row is not yet visible, so
    /// the guarded removal treats these paths as in use (AUD-05).
    private var committingAudioPaths: [String: Int] = [:]
    /// Clear completions run one at a time. Each writes back and retires the
    /// marker it loaded, so two interleaved at an await could restore an
    /// intent another request changed or retire a marker the other has not
    /// finished (AUD-05).
    private var clearInProgress = false
    private var clearWaiters: [CheckedContinuation<Void, Never>] = []

    init(
        store: GenerationHistoryOutboxStore,
        commitGeneration: @escaping Commit,
        fetchAllGenerations: @escaping FetchAll,
        deleteGenerationsThrough: @escaping DeleteThrough,
        referencedAudioPaths: @escaping ReferencedAudioPaths
    ) {
        self.store = store
        self.commitGeneration = commitGeneration
        self.fetchAllGenerations = fetchAllGenerations
        self.deleteGenerationsThrough = deleteGenerationsThrough
        self.referencedAudioPaths = referencedAudioPaths
    }

    func commit(_ entry: GenerationHistoryOutboxEntry) async throws -> Generation {
        let audioPath = entry.generation.audioPath
        guard FileManager.default.fileExists(atPath: audioPath) else {
            throw GenerationHistoryOutboxError.missingAudio
        }
        committingAudioPaths[audioPath, default: 0] += 1
        defer {
            if let count = committingAudioPaths[audioPath], count > 1 {
                committingAudioPaths[audioPath] = count - 1
            } else {
                committingAudioPaths[audioPath] = nil
            }
        }
        do {
            let saved = try await commitGeneration(entry.operation, entry.generation)
            try store.removeEntry(id: entry.id)
            return saved
        } catch let error as GenerationHistoryOutboxError {
            throw error
        } catch {
            throw GenerationHistoryOutboxError.databaseUnavailable
        }
    }

    func reconcile() async -> GenerationHistoryReconciliationResult {
        // A marker that cannot be read fails closed: committing now could
        // bring back takes the interrupted clear removes (AUD-05).
        do {
            _ = try await resumeClearTransactionIfNeeded()
        } catch {
            return GenerationHistoryReconciliationResult(
                committed: [],
                snapshot: snapshot()
            )
        }
        let scan = store.scan()
        var committed: [Generation] = []
        // A clear may remove an entry while an earlier commit awaits: skip it
        // rather than bring back a take the user cleared.
        for entry in scan.entries where store.containsEntry(id: entry.id) {
            if let saved = try? await commit(entry) {
                committed.append(saved)
            }
        }
        // After the commits, so audio that just became a row is recognized as
        // referenced. A failure leaves the list for the next reconcile.
        _ = try? await removePendingAudio()
        return GenerationHistoryReconciliationResult(
            committed: committed,
            snapshot: snapshot()
        )
    }

    func snapshot() -> GenerationHistoryRecoverySnapshot {
        let scan = store.scan()
        let available = scan.entries.count {
            FileManager.default.fileExists(atPath: $0.generation.audioPath)
        }
        let missing = scan.entries.count - available
        let clearPending: Bool
        let clearIssueCount: Int
        do {
            clearPending = try store.loadClearTransaction() != nil
            clearIssueCount = 0
        } catch {
            clearPending = true
            clearIssueCount = 1
        }
        let removalCount: Int
        var removalIssueCount = store.unreadableAudioRemovalCount()
        do {
            removalCount = try store.loadPendingAudioRemovals().count
        } catch {
            removalCount = 0
            removalIssueCount += 1
        }
        return GenerationHistoryRecoverySnapshot(
            pendingCount: scan.entries.count,
            availableAudioCount: available,
            issueCount: scan.issueCount + missing + clearIssueCount + removalIssueCount,
            clearRecoveryPending: clearPending,
            pendingAudioRemovalCount: removalCount
        )
    }

    func pendingAudioURLs() -> [URL] {
        store.scan().entries.compactMap { entry in
            guard FileManager.default.fileExists(atPath: entry.generation.audioPath) else { return nil }
            return URL(fileURLWithPath: entry.generation.audioPath)
        }
    }

    func clearAll(deleteAudio: Bool) async throws -> GenerationHistoryClearOutcome {
        // A keep-files request downgrades a pending clear at once, before any
        // await: a crash, a later resume, and a completion already running
        // (it reads the stored intent after its row deletion) all keep the
        // audio. Nothing ever escalates to deleting it (AUD-05).
        if !deleteAudio {
            try keepAudioOfPendingClear()
        }
        await acquireClear()
        defer { releaseClear() }
        var failures = 0
        if let pending = try store.loadClearTransaction() {
            // An interrupted clear finishes first under its own bound. Takes
            // saved since then are this request's: it captures a fresh bound
            // below instead of reporting the old clear as its own.
            failures = try await completeClearTransaction(pending)
        }
        let scan = store.scan()
        guard scan.issueCount == 0 else {
            throw GenerationHistoryOutboxError.clearUnavailable
        }
        let databaseRows: [Generation]
        do {
            databaseRows = try await fetchAllGenerations()
        } catch {
            throw GenerationHistoryOutboxError.clearUnavailable
        }
        // The bound comes from the same read as the paths, which fails rather
        // than withholding rows, so every row at or below it was captured.
        let transaction = GenerationHistoryClearTransaction(
            deleteAudio: deleteAudio,
            audioPaths: databaseRows.map(\.audioPath) + scan.entries.map(\.generation.audioPath),
            pendingEntryIDs: scan.entries.map(\.id),
            maxRowID: databaseRows.compactMap(\.id).max() ?? 0
        )
        try store.writeClearTransaction(transaction)
        failures += try await completeClearTransaction(transaction)
        return GenerationHistoryClearOutcome(failedFileRemovals: failures, snapshot: snapshot())
    }

    /// Records a keep-files request on a pending delete-audio clear, even when
    /// the request itself is then refused (AUD-05).
    func keepAudioOfPendingClear() throws {
        guard let pending = try store.loadClearTransaction(), pending.deleteAudio else { return }
        do {
            try store.writeClearTransaction(pending.keepingAudio(unless: false))
        } catch {
            throw GenerationHistoryOutboxError.clearUnavailable
        }
    }

    @discardableResult
    private func resumeClearTransactionIfNeeded() async throws -> Int {
        await acquireClear()
        defer { releaseClear() }
        guard let transaction = try store.loadClearTransaction() else { return 0 }
        return try await completeClearTransaction(transaction)
    }

    private func acquireClear() async {
        guard clearInProgress else {
            clearInProgress = true
            return
        }
        await withCheckedContinuation { clearWaiters.append($0) }
    }

    private func releaseClear() {
        if clearWaiters.isEmpty {
            clearInProgress = false
        } else {
            clearWaiters.removeFirst().resume()
        }
    }

    private func completeClearTransaction(_ transaction: GenerationHistoryClearTransaction) async throws -> Int {
        var transaction = transaction
        if !transaction.rowsDeleted {
            guard let bound = transaction.maxRowID else {
                try abandonUnboundedClear(transaction)
                return 0
            }
            let deletedAudioPaths: [String]
            do {
                deletedAudioPaths = try await deleteGenerationsThrough(bound)
            } catch {
                throw GenerationHistoryOutboxError.clearUnavailable
            }
            // A keep-files request may have downgraded the stored intent while
            // the delete ran; it wins.
            // An intent that cannot be read keeps the audio. Under the clear
            // lock no one else finishes this marker, so a missing or foreign
            // one is damage: fail closed rather than report a finished clear.
            let stored: GenerationHistoryClearTransaction?
            do {
                stored = try store.loadClearTransaction()
            } catch {
                stored = transaction.keepingAudio(unless: false)
            }
            guard let stored, stored.id == transaction.id else {
                throw GenerationHistoryOutboxError.clearUnavailable
            }
            // Record the phase before any later step can fail. A repeat of the
            // bounded delete would be harmless (those rows are gone and later
            // takes have larger ids), but the phase also keeps the audio list.
            transaction = transaction
                .keepingAudio(unless: stored.deleteAudio)
                .markingRowsDeleted(addingAudioPaths: deletedAudioPaths)
            try? store.writeClearTransaction(transaction)
        }
        for id in transaction.pendingEntryIDs {
            try store.removeEntry(id: id)
        }
        guard transaction.deleteAudio else {
            try store.removeClearTransaction()
            return 0
        }

        // The rows are gone. Their audio moves to the durable removal list
        // before the transaction retires, so a file that cannot be removed now
        // is retried by a later reconcile rather than by resuming the clear
        // (AUD-05).
        do {
            try store.appendPendingAudioRemovals(transaction.audioPaths)
        } catch {
            throw GenerationHistoryOutboxError.clearUnavailable
        }
        try store.removeClearTransaction()
        // Only a failed removal counts. Audio kept because a surviving row or
        // a queued take uses it, or waiting on a commit in flight, is none.
        let failed: Set<String>
        do {
            failed = try await removePendingAudio()
        } catch {
            let fileManager = FileManager.default
            return transaction.audioPaths.count { fileManager.fileExists(atPath: $0) }
        }
        return transaction.audioPaths.count { failed.contains($0) }
    }

    /// A marker written before the bound existed. An unbounded resume could
    /// delete takes saved since, so the clear is abandoned: rows still there
    /// stay, and the user can clear again. The rows of an interrupted old clear
    /// may already be gone, so a delete-audio clear queues its audio for the
    /// guarded removal. Much of that audio may still belong to live rows; it
    /// is safe only because that removal skips any path a row or a queued take
    /// still uses.
    private func abandonUnboundedClear(_ transaction: GenerationHistoryClearTransaction) throws {
        do {
            if transaction.deleteAudio {
                try store.appendPendingAudioRemovals(transaction.audioPaths)
            }
            try store.removeClearTransaction()
        } catch {
            throw GenerationHistoryOutboxError.clearUnavailable
        }
    }

    /// A single delete removed the row but not its audio file: keep the path so
    /// a later reconcile retries the removal instead of leaving the file behind
    /// silently (AUD-05).
    func retainAudioRemoval(_ audioPath: String) throws {
        try store.appendPendingAudioRemovals([audioPath])
    }

    /// Retries the pending audio removals. Audio a History row or a queued take
    /// still points at is never removed (it only leaves the list), and neither
    /// is anything but a regular file. Audio only a commit in flight uses stays
    /// listed, for a pass after that commit to decide: if the commit fails
    /// after a clear removed its entry, nothing else would ever remove it.
    /// Returns the paths whose removal failed.
    @discardableResult
    private func removePendingAudio() async throws -> Set<String> {
        let pending = try store.loadPendingAudioRemovals()
        guard !pending.isEmpty else { return [] }
        // The outbox is read before the rows. A commit inserts its row before
        // it removes its entry, so a take this scan misses is one the row read
        // below sees. An outbox that cannot be read fully may hide a queued
        // take that uses one of these paths: remove nothing until it can.
        let scan = store.scan()
        guard scan.issueCount == 0 else { return Set(pending) }
        let queued = Set(scan.entries.map(\.generation.audioPath))
        var committing = Set(committingAudioPaths.keys)
        let referenced = try await referencedAudioPaths(pending)
        // The await lets other work on this actor run: a commit may have
        // started (its entry possibly already removed by a clear), and
        // `retainAudioRemoval(_:)` may have added a path. So in-flight commits
        // are read again, and only the paths this pass resolved leave the
        // list, which is read again below; a list rebuilt from `pending` would
        // drop the new path silently.
        committing.formUnion(committingAudioPaths.keys)
        var resolved: Set<String> = []
        var failed: Set<String> = []
        for path in pending {
            if queued.contains(path) || referenced.contains(path) {
                resolved.insert(path)
                continue
            }
            if committing.contains(path) {
                continue // Stays listed until that commit has landed or failed.
            }
            switch GenerationHistoryAudioFile.removeRegularFile(atPath: path) {
            case .removed, .absentOrNotRegular:
                resolved.insert(path)
            case .failed:
                failed.insert(path) // Stays listed for the next reconcile.
            }
        }
        let remaining = try store.loadPendingAudioRemovals().filter { !resolved.contains($0) }
        try store.writePendingAudioRemovals(remaining)
        return failed
    }
}

/// Removal of History audio: only a regular file, never through a symbolic
/// link and never recursively (AUD-05).
enum GenerationHistoryAudioFile {
    enum RemovalResult: Equatable {
        case removed
        case absentOrNotRegular
        case failed(POSIXErrorCode)
    }

    /// A deleted row's audio is removed only when no other History row and no
    /// queued take still uses the path, and only a regular file. The outbox is
    /// read first: a commit inserts its row before it removes its entry, so a
    /// take the scan misses is one the row check sees. An outbox that cannot be
    /// read fully keeps the file: the error makes the screen retain it for a
    /// later, guarded retry. The scan only reads, since this runs off the
    /// coordinator and must not race its promotion.
    static func removeUnreferenced(
        atPath path: String,
        outbox: GenerationHistoryOutboxStore,
        referencedAudioPaths: ([String]) throws -> Set<String>
    ) throws {
        let scan = outbox.scan(promotingWrites: false)
        guard scan.issueCount == 0 else { throw GenerationHistoryOutboxError.corruptEntry }
        guard !scan.entries.contains(where: { $0.generation.audioPath == path }) else { return }
        guard try referencedAudioPaths([path]).isEmpty else { return }
        if case .failed(let code) = removeRegularFile(atPath: path) {
            throw POSIXError(code)
        }
    }

    static func removeRegularFile(atPath path: String) -> RemovalResult {
        var info = stat()
        guard lstat(path, &info) == 0 else {
            // Only a missing file is absent. Any other failure (EACCES, EIO)
            // keeps the path listed for a later retry.
            let code = errno
            return code == ENOENT || code == ENOTDIR ? .absentOrNotRegular : .failed(posixCode(code))
        }
        guard (info.st_mode & S_IFMT) == S_IFREG else { return .absentOrNotRegular }
        if unlink(path) == 0 { return .removed }
        let code = errno
        return code == ENOENT ? .removed : .failed(posixCode(code))
    }

    private static func posixCode(_ code: Int32) -> POSIXErrorCode {
        POSIXErrorCode(rawValue: code) ?? .EIO
    }
}
