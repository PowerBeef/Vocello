import CryptoKit
import Foundation
import System

/// Idempotency for agent requests (`--client-request-id`, a request's
/// `clientRequestID`). The first request with an id runs and, when it
/// succeeds, its result is kept; the same id with the same request replays that
/// result instead of running again; the same id with a different request is a
/// conflict; the same id while another process runs it is in progress. A
/// failed request keeps nothing, so a retry runs again. Entries live under
/// `<data>/cli/requests`, named by the id's digest, each with a lock file held
/// (flock) for as long as its request runs. A ledger-wide lock serializes
/// claims and pruning, so a prune never removes what a claim is about to use.
public struct CLIRequestLedger: Sendable {
    public enum Claim: Sendable {
        case fresh(Reservation)
        case replay(CLIJSONValue)
        case conflict
        case inProgress
    }

    /// A claim as a command acts on it.
    public enum Start: Sendable {
        case replay(CLIJSONValue)
        case run(Reservation)
    }

    /// A request this process is running: its lock is held until `complete` or `abandon`.
    public final class Reservation: Sendable {
        let key: String
        let requestDigest: String
        let lock: FileDescriptor

        init(key: String, requestDigest: String, lock: FileDescriptor) {
            self.key = key
            self.requestDigest = requestDigest
            self.lock = lock
        }
    }

    struct Entry: Codable {
        let schemaVersion: Int
        let requestDigest: String
        let completedAt: String
        let result: CLIJSONValue
    }

    /// Completed entries are kept this long, then pruned.
    public static let retention: TimeInterval = 7 * 24 * 3600

    public let directory: URL

    public init(dataDirectory: URL) {
        directory = dataDirectory.appendingPathComponent("cli/requests", isDirectory: true)
    }

    /// The contract's request-id shape (`envelope.schema.json`).
    public static func validate(id: String) throws {
        let allowed = CharacterSet.alphanumerics.union(CharacterSet(charactersIn: "._:-"))
        guard (1 ... 128).contains(id.unicodeScalars.count),
              let first = id.unicodeScalars.first, CharacterSet.alphanumerics.contains(first), first.isASCII,
              id.unicodeScalars.allSatisfy({ $0.isASCII && allowed.contains($0) }) else {
            throw CLIError(
                .usageError, "invalid client request id '\(id)'",
                hint: "1-128 ASCII letters, digits, '.', '_', ':' or '-', starting with a letter or digit"
            )
        }
    }

    /// The digest that identifies a request: its canonical JSON (sorted keys).
    public static func digest(of request: CLIJSONValue) throws -> String {
        let data: Data
        do {
            data = try CLIJSONEncoding.encoder().encode(request)
        } catch {
            throw CLIError(.internalError, "the request has no canonical form")
        }
        return hex(SHA256.hash(data: data))
    }

    /// Pruning runs at most this often, so a completion rarely reads the whole ledger.
    static let pruneInterval: TimeInterval = 3600

    private static func hex(_ digest: SHA256.Digest) -> String {
        digest.map { unsafe String(format: "%02x", $0) }.joined()
    }

    /// `claim` as a command acts on it: a conflict or a request running elsewhere
    /// fails, and a stored take whose file is gone fails rather than claim a path
    /// with nothing behind it (CM-7).
    public func start(id: String, request: CLIJSONValue) throws -> Start {
        switch try claim(id: id, request: request) {
        case .fresh(let reservation):
            return .run(reservation)
        case .conflict:
            throw CLIError(
                .idempotencyConflict, "client request id '\(id)' was used for a different request",
                hint: "use a new id for a new request"
            )
        case .inProgress:
            throw CLIError(.requestInProgress, "client request id '\(id)' is running in another process")
        case .replay(let stored):
            if let path = Self.audioPaths(of: stored).first(where: { !FileManager.default.fileExists(atPath: $0) }) {
                throw CLIError(
                    .outputMissing, "the take kept for client request id '\(id)' no longer exists at \(path)",
                    hint: "use a new id to generate it again"
                )
            }
            return .replay(stored)
        }
    }

    /// The audio a result names: its `audioPath`, or each of its `items`' (a line batch).
    public static func audioPaths(of result: CLIJSONValue) -> [String] {
        guard case .object(let fields) = result else { return [] }
        if case .string(let path)? = fields["audioPath"] { return [path] }
        guard case .array(let items)? = fields["items"] else { return [] }
        return items.compactMap { item in
            guard case .object(let itemFields) = item, case .string(let path)? = itemFields["audioPath"] else { return nil }
            return path
        }
    }

    public func claim(id: String, request: CLIJSONValue, now: Date = Date()) throws -> Claim {
        try Self.validate(id: id)
        let key = Self.hex(SHA256.hash(data: Data(id.utf8)))
        let requestDigest = try Self.digest(of: request)
        do {
            try FileManager.default.createDirectory(
                at: directory, withIntermediateDirectories: true, attributes: [.posixPermissions: 0o700]
            )
        } catch {
            throw CLIError(.ioError, "could not create the request ledger: \(error.localizedDescription)")
        }
        return try withLedgerLock {
            let lock = try openLock(key: key)
            guard flock(lock.rawValue, LOCK_EX | LOCK_NB) == 0 else {
                let failure = Errno(rawValue: errno)
                try? lock.close()
                // Only a lock another process holds means in progress; anything else
                // (a filesystem without locks) would otherwise retry forever.
                if failure == .wouldBlock { return .inProgress }
                throw CLIError(.ioError, "could not lock the request ledger entry: \(failure)")
            }
            let entry: Entry?
            do {
                entry = try readEntry(key: key)
            } catch {
                release(lock)
                throw error
            }
            if let entry, !isExpired(entry, now: now) {
                release(lock)
                return entry.requestDigest == requestDigest ? .replay(entry.result) : .conflict
            }
            return .fresh(Reservation(key: key, requestDigest: requestDigest, lock: lock))
        }
    }

    /// Keeps a successful request's result and releases its lock. False when the
    /// result could not be kept, so a retry would run the request again.
    @discardableResult
    public func complete(_ reservation: Reservation, result: CLIJSONValue, now: Date = Date()) -> Bool {
        defer { release(reservation.lock) }
        let entry = Entry(
            schemaVersion: 1, requestDigest: reservation.requestDigest,
            completedAt: ISO8601DateFormatter().string(from: now), result: result
        )
        let kept: Bool
        do {
            try writePrivately(try CLIJSONEncoding.encoder().encode(entry), to: entryURL(key: reservation.key))
            kept = true
        } catch {
            kept = false
        }
        prune(now: now)
        return kept
    }

    /// Releases a failed request's lock and keeps nothing, so a retry runs again.
    public func abandon(_ reservation: Reservation) {
        release(reservation.lock)
    }

    /// Removes entries completed before the retention window and the lock files
    /// of ids that kept nothing (abandoned) for as long, skipping any id a process
    /// holds; at most once per `pruneInterval` unless `force`.
    func prune(now: Date, force: Bool = false) {
        _ = try? withLedgerLock {
            let marker = directory.appendingPathComponent("ledger.pruned")
            if !force, let last = Self.modified(marker), last <= now, now.timeIntervalSince(last) < Self.pruneInterval {
                return
            }
            FileManager.default.createFile(atPath: marker.path, contents: nil)
            try? FileManager.default.setAttributes([.modificationDate: now], ofItemAtPath: marker.path)
            let urls = (try? FileManager.default.contentsOfDirectory(
                at: directory, includingPropertiesForKeys: [.contentModificationDateKey]
            )) ?? []
            let names = Set(urls.map(\.lastPathComponent))
            for url in urls {
                let age = now.timeIntervalSince(Self.modified(url) ?? now)
                switch url.pathExtension {
                case "tmp":
                    // A write that never reached its rename.
                    if age > 3600 { try? FileManager.default.removeItem(at: url) }
                case "json":
                    let key = url.deletingPathExtension().lastPathComponent
                    // A damaged entry, which no claim can use, ages out by its file date.
                    let expired = if let entry = try? readEntry(key: key) {
                        isExpired(entry, now: now)
                    } else {
                        age > Self.retention
                    }
                    if expired { removeIdle(key: key, entry: url) }
                case "lock" where url.lastPathComponent != "ledger.lock":
                    let key = url.deletingPathExtension().lastPathComponent
                    if !names.contains("\(key).json"), age > Self.retention { removeIdle(key: key, entry: nil) }
                default:
                    continue
                }
            }
        }
    }

    /// Removes an id's entry and lock file unless a process holds it. Claims open
    /// lock files only under the ledger lock, which the caller holds, so this
    /// never races a claim.
    private func removeIdle(key: String, entry: URL?) {
        guard let lock = try? openLock(key: key) else { return }
        guard flock(lock.rawValue, LOCK_EX | LOCK_NB) == 0 else {
            try? lock.close()
            return
        }
        if let entry { try? FileManager.default.removeItem(at: entry) }
        try? FileManager.default.removeItem(at: lockURL(key: key))
        release(lock)
    }

    private static func modified(_ url: URL) -> Date? {
        (try? url.resourceValues(forKeys: [.contentModificationDateKey]))?.contentModificationDate
    }

    // MARK: - Files

    private func entryURL(key: String) -> URL { directory.appendingPathComponent("\(key).json") }
    private func lockURL(key: String) -> URL { directory.appendingPathComponent("\(key).lock") }

    private func openLock(key: String) throws -> FileDescriptor {
        try openLockFile(at: lockURL(key: key))
    }

    private func openLockFile(at url: URL) throws -> FileDescriptor {
        do {
            return try FileDescriptor.open(
                FilePath(url.path), .readWrite, options: [.create, .closeOnExec], permissions: [.ownerReadWrite]
            )
        } catch {
            throw CLIError(.ioError, "could not open the request ledger: \(error)")
        }
    }

    /// Runs `body` holding the ledger-wide lock.
    private func withLedgerLock<T>(_ body: () throws -> T) throws -> T {
        let lock = try openLockFile(at: directory.appendingPathComponent("ledger.lock"))
        defer { release(lock) }
        while flock(lock.rawValue, LOCK_EX) != 0 {
            let failure = Errno(rawValue: errno)
            guard failure == .interrupted else {
                throw CLIError(.ioError, "could not lock the request ledger: \(failure)")
            }
        }
        return try body()
    }

    private func release(_ lock: FileDescriptor) {
        _ = flock(lock.rawValue, LOCK_UN)
        try? lock.close()
    }

    /// The entry for `key`, nil when there is none. An entry that exists but
    /// cannot be read fails, rather than run a completed request again.
    private func readEntry(key: String) throws -> Entry? {
        let url = entryURL(key: key)
        guard FileManager.default.fileExists(atPath: url.path) else { return nil }
        let data: Data
        do {
            data = try Data(contentsOf: url)
        } catch {
            throw CLIError(.ioError, "could not read the request ledger entry: \(error.localizedDescription)")
        }
        do {
            return try JSONDecoder().decode(Entry.self, from: data)
        } catch {
            throw CLIError(.ioError, "a request ledger entry is damaged", hint: "use a new client request id")
        }
    }

    private func isExpired(_ entry: Entry, now: Date) -> Bool {
        guard let completed = ISO8601DateFormatter().date(from: entry.completedAt) else { return false }
        return now.timeIntervalSince(completed) > Self.retention
    }

    /// Private from its creation, like its 0700 folder (a result names the take's
    /// output path), and published whole by a rename.
    private func writePrivately(_ data: Data, to url: URL) throws {
        let temporary = directory.appendingPathComponent(".\(url.lastPathComponent).\(UUID().uuidString).tmp")
        do {
            let descriptor = try FileDescriptor.open(
                FilePath(temporary.path), .writeOnly,
                options: [.create, .exclusiveCreate, .closeOnExec], permissions: [.ownerReadWrite]
            )
            try descriptor.closeAfter {
                _ = try descriptor.writeAll(data)
                guard fsync(descriptor.rawValue) == 0 else { throw Errno(rawValue: errno) }
            }
            guard unsafe rename(temporary.path, url.path) == 0 else { throw Errno(rawValue: errno) }
            // The rename survives a crash once the folder is synced. Best effort:
            // the entry is already visible, so a failed sync is not a lost result.
            if let folder = try? FileDescriptor.open(FilePath(directory.path), .readOnly, options: [.closeOnExec]) {
                _ = fsync(folder.rawValue)
                try? folder.close()
            }
        } catch {
            try? FileManager.default.removeItem(at: temporary)
            throw error
        }
    }
}
