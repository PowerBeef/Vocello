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
/// (flock) for as long as its request runs.
public struct CLIRequestLedger: Sendable {
    public enum Claim: Sendable {
        case fresh(Reservation)
        case replay(CLIJSONValue)
        case conflict
        case inProgress
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
    public static func digest(of request: CLIJSONValue) -> String {
        let data = (try? CLIJSONEncoding.encoder().encode(request)) ?? Data()
        return SHA256.hash(data: data).map { unsafe String(format: "%02x", $0) }.joined()
    }

    public func claim(id: String, request: CLIJSONValue) throws -> Claim {
        try Self.validate(id: id)
        let key = SHA256.hash(data: Data(id.utf8)).map { unsafe String(format: "%02x", $0) }.joined()
        let requestDigest = Self.digest(of: request)
        do {
            try FileManager.default.createDirectory(
                at: directory, withIntermediateDirectories: true, attributes: [.posixPermissions: 0o700]
            )
        } catch {
            throw CLIError(.ioError, "could not create the request ledger: \(error.localizedDescription)")
        }
        let lock: FileDescriptor
        do {
            lock = try FileDescriptor.open(
                FilePath(directory.appendingPathComponent("\(key).lock").path), .readWrite,
                options: [.create, .closeOnExec], permissions: [.ownerReadWrite]
            )
        } catch {
            throw CLIError(.ioError, "could not open the request ledger: \(error)")
        }
        guard flock(lock.rawValue, LOCK_EX | LOCK_NB) == 0 else {
            try? lock.close()
            return .inProgress
        }
        let entryURL = directory.appendingPathComponent("\(key).json")
        if let data = try? Data(contentsOf: entryURL),
           let entry = try? JSONDecoder().decode(Entry.self, from: data) {
            release(lock)
            return entry.requestDigest == requestDigest ? .replay(entry.result) : .conflict
        }
        return .fresh(Reservation(key: key, requestDigest: requestDigest, lock: lock))
    }

    /// Keeps a successful request's result and releases its lock.
    public func complete(_ reservation: Reservation, result: CLIJSONValue, now: Date = Date()) {
        defer { release(reservation.lock) }
        let formatter = ISO8601DateFormatter()
        let entry = Entry(
            schemaVersion: 1, requestDigest: reservation.requestDigest, completedAt: formatter.string(from: now),
            result: result
        )
        guard let data = try? CLIJSONEncoding.encoder().encode(entry) else { return }
        // Private like its 0700 folder: a result names the take's output path.
        let url = directory.appendingPathComponent("\(reservation.key).json")
        guard (try? data.write(to: url, options: .atomic)) != nil else { return }
        try? FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: url.path)
        prune(now: now)
    }

    /// Releases a failed request's lock and keeps nothing, so a retry runs again.
    public func abandon(_ reservation: Reservation) {
        release(reservation.lock)
    }

    private func release(_ lock: FileDescriptor) {
        _ = flock(lock.rawValue, LOCK_UN)
        try? lock.close()
    }

    /// Removes entries completed before the retention window.
    func prune(now: Date) {
        let formatter = ISO8601DateFormatter()
        let entries = (try? FileManager.default.contentsOfDirectory(at: directory, includingPropertiesForKeys: nil)) ?? []
        for url in entries where url.pathExtension == "json" {
            guard let data = try? Data(contentsOf: url),
                  let entry = try? JSONDecoder().decode(Entry.self, from: data),
                  let completed = formatter.date(from: entry.completedAt),
                  now.timeIntervalSince(completed) > Self.retention else { continue }
            // The lock file stays: another process may be about to claim the same id.
            try? FileManager.default.removeItem(at: url)
        }
    }
}
