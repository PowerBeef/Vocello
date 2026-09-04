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

    init(
        id: UUID = UUID(),
        deleteAudio: Bool,
        audioPaths: [String],
        pendingEntryIDs: [UUID],
        createdAt: Date = Date()
    ) {
        self.schemaVersion = Self.schemaVersion
        self.id = id
        self.deleteAudio = deleteAudio
        self.audioPaths = Array(Set(audioPaths)).sorted()
        self.pendingEntryIDs = Array(Set(pendingEntryIDs)).sorted { $0.uuidString < $1.uuidString }
        self.createdAt = createdAt
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

    var needsAttention: Bool {
        pendingCount > 0 || unqueuedCount > 0 || issueCount > 0 || clearRecoveryPending
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
            try atomicWrite(encode(entry), to: entryURL(for: entry.id))
            return entry
        } catch let error as GenerationHistoryOutboxError {
            throw error
        } catch {
            throw GenerationHistoryOutboxError.unavailable
        }
    }

    func scan() -> GenerationHistoryOutboxScan {
        do {
            try ensureRoot()
            let urls = try FileManager.default.contentsOfDirectory(
                at: rootURL,
                includingPropertiesForKeys: nil,
                options: [.skipsHiddenFiles]
            )
            var entries: [GenerationHistoryOutboxEntry] = []
            var issues = 0
            for url in urls.sorted(by: { $0.lastPathComponent < $1.lastPathComponent }) {
                if url.lastPathComponent == clearTransactionWritingURL.lastPathComponent
                    || url.lastPathComponent == clearTransactionURL.lastPathComponent {
                    continue
                }
                if url.pathExtension == "writing" {
                    do {
                        let entry: GenerationHistoryOutboxEntry = try decode(url)
                        try validate(entry, filenameID: writingFileID(url))
                        let finalURL = entryURL(for: entry.id)
                        if FileManager.default.fileExists(atPath: finalURL.path) {
                            try FileManager.default.removeItem(at: url)
                        } else {
                            try FileManager.default.moveItem(at: url, to: finalURL)
                        }
                        entries.append(entry)
                    } catch {
                        issues += 1
                    }
                } else if url.pathExtension == "json", url != clearTransactionURL {
                    do {
                        let entry: GenerationHistoryOutboxEntry = try decode(url)
                        try validate(entry, filenameID: UUID(uuidString: url.deletingPathExtension().lastPathComponent))
                        entries.append(entry)
                    } catch {
                        issues += 1
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
        if !fileManager.fileExists(atPath: clearTransactionURL.path),
           fileManager.fileExists(atPath: clearTransactionWritingURL.path) {
            do {
                let interrupted: GenerationHistoryClearTransaction = try decode(clearTransactionWritingURL)
                guard interrupted.schemaVersion == GenerationHistoryClearTransaction.schemaVersion else {
                    throw GenerationHistoryOutboxError.corruptEntry
                }
                try fileManager.moveItem(at: clearTransactionWritingURL, to: clearTransactionURL)
            } catch {
                throw GenerationHistoryOutboxError.clearUnavailable
            }
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

    private func atomicWrite(_ data: Data, to finalURL: URL) throws {
        guard let id = UUID(uuidString: finalURL.deletingPathExtension().lastPathComponent) else {
            throw GenerationHistoryOutboxError.invalidEntryIdentity
        }
        try atomicWrite(data, to: finalURL, writingURL: writingURL(for: id))
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

/// Serializes pending commits, replay, and clear-all so a clear cannot race a
/// background save. Database writes remain idempotent through the injected
/// audio-identity-aware commit operation.
actor GenerationHistoryRecoveryCoordinator {
    typealias Commit = @Sendable (GenerationHistoryOutboxOperation, Generation) async throws -> Generation
    typealias FetchAll = @Sendable () async throws -> [Generation]
    typealias DeleteAll = @Sendable () async throws -> Void

    private let store: GenerationHistoryOutboxStore
    private let commitGeneration: Commit
    private let fetchAllGenerations: FetchAll
    private let deleteAllGenerations: DeleteAll

    init(
        store: GenerationHistoryOutboxStore,
        commitGeneration: @escaping Commit,
        fetchAllGenerations: @escaping FetchAll,
        deleteAllGenerations: @escaping DeleteAll
    ) {
        self.store = store
        self.commitGeneration = commitGeneration
        self.fetchAllGenerations = fetchAllGenerations
        self.deleteAllGenerations = deleteAllGenerations
    }

    func commit(_ entry: GenerationHistoryOutboxEntry) async throws -> Generation {
        guard FileManager.default.fileExists(atPath: entry.generation.audioPath) else {
            throw GenerationHistoryOutboxError.missingAudio
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
        if (try? store.loadClearTransaction()) != nil {
            do {
                _ = try await resumeClearTransactionIfNeeded()
            } catch {
                return GenerationHistoryReconciliationResult(
                    committed: [],
                    snapshot: snapshot()
                )
            }
        }
        let scan = store.scan()
        var committed: [Generation] = []
        for entry in scan.entries {
            if let saved = try? await commit(entry) {
                committed.append(saved)
            }
        }
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
        return GenerationHistoryRecoverySnapshot(
            pendingCount: scan.entries.count,
            availableAudioCount: available,
            issueCount: scan.issueCount + missing + clearIssueCount,
            clearRecoveryPending: clearPending
        )
    }

    func pendingAudioURLs() -> [URL] {
        store.scan().entries.compactMap { entry in
            guard FileManager.default.fileExists(atPath: entry.generation.audioPath) else { return nil }
            return URL(fileURLWithPath: entry.generation.audioPath)
        }
    }

    func clearAll(deleteAudio: Bool) async throws -> GenerationHistoryClearOutcome {
        if try store.loadClearTransaction() != nil {
            let failures = try await resumeClearTransactionIfNeeded()
            return GenerationHistoryClearOutcome(
                failedFileRemovals: failures,
                snapshot: snapshot()
            )
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
        let transaction = GenerationHistoryClearTransaction(
            deleteAudio: deleteAudio,
            audioPaths: databaseRows.map(\.audioPath) + scan.entries.map(\.generation.audioPath),
            pendingEntryIDs: scan.entries.map(\.id)
        )
        try store.writeClearTransaction(transaction)
        let failures = try await completeClearTransaction(transaction)
        return GenerationHistoryClearOutcome(failedFileRemovals: failures, snapshot: snapshot())
    }

    @discardableResult
    private func resumeClearTransactionIfNeeded() async throws -> Int {
        guard let transaction = try store.loadClearTransaction() else { return 0 }
        return try await completeClearTransaction(transaction)
    }

    private func completeClearTransaction(_ transaction: GenerationHistoryClearTransaction) async throws -> Int {
        do {
            try await deleteAllGenerations()
        } catch {
            throw GenerationHistoryOutboxError.clearUnavailable
        }
        for id in transaction.pendingEntryIDs {
            try store.removeEntry(id: id)
        }

        var failures = 0
        if transaction.deleteAudio {
            let fileManager = FileManager.default
            for path in transaction.audioPaths where fileManager.fileExists(atPath: path) {
                do {
                    try fileManager.removeItem(atPath: path)
                } catch {
                    failures += 1
                }
            }
        }
        if failures == 0 {
            try store.removeClearTransaction()
        }
        return failures
    }
}
