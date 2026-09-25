import Darwin
import Foundation

enum HistoryPersistenceOperation: String, Equatable, Sendable {
    case initialize
    case migrate
    case read
    case write
    case delete
}

enum HistoryPersistenceFailure: String, Equatable, Sendable {
    case unavailable
    case corrupt
    case locked
    case permissionDenied
    case storageFull
    case migrationFailed
}

/// Privacy-safe, typed history-storage failure shared by the macOS and iOS apps.
/// Raw SQLite/GRDB messages can contain absolute paths, so they are classified at
/// the persistence boundary and never surfaced directly to the UI.
struct HistoryPersistenceError: LocalizedError, Equatable, Sendable {
    let operation: HistoryPersistenceOperation
    let failure: HistoryPersistenceFailure

    var errorDescription: String? {
        switch failure {
        case .corrupt:
            return "Generation History couldn't be read because its database appears damaged. Your existing files were not deleted. Retry, then use recovery or export tools before making changes."
        case .locked:
            return "Generation History is temporarily busy. Your existing history was not changed. Wait for other Vocello operations to finish, then retry."
        case .permissionDenied:
            return "Generation History is unavailable because Vocello can't access its database. Your existing history was not changed. Check storage permissions, then retry."
        case .storageFull:
            return "Generation History couldn't be updated because storage is full. Free some space, then retry. Your existing history was not changed."
        case .migrationFailed:
            return "Generation History couldn't be upgraded safely. The existing database was preserved. Retry before changing or deleting history."
        case .unavailable:
            return "Generation History is unavailable. The existing database was preserved. Retry before changing or deleting history."
        }
    }

    func replacingOperation(_ operation: HistoryPersistenceOperation) -> HistoryPersistenceError {
        HistoryPersistenceError(operation: operation, failure: failure)
    }

    static func classify(
        _ error: Error,
        operation: HistoryPersistenceOperation
    ) -> HistoryPersistenceError {
        if let typed = error as? HistoryPersistenceError {
            return typed.replacingOperation(operation)
        }

        let nsError = error as NSError
        // IOS-11: a suspended History database refuses new locks with
        // SQLITE_ABORT and interrupts a running statement with SQLITE_INTERRUPT;
        // SQLite has rolled the transaction back. That is transient, never damage
        // or a failed upgrade: nothing changed, and a retry after resume succeeds
        // (an interrupted append stays in the outbox until it does).
        if isInterruption(nsError) {
            return HistoryPersistenceError(operation: operation, failure: .locked)
        }

        if operation == .migrate {
            return HistoryPersistenceError(operation: operation, failure: .migrationFailed)
        }

        if nsError.domain == NSCocoaErrorDomain {
            switch CocoaError.Code(rawValue: nsError.code) {
            case .fileWriteOutOfSpace:
                return HistoryPersistenceError(operation: operation, failure: .storageFull)
            case .fileReadNoPermission, .fileWriteNoPermission, .fileWriteVolumeReadOnly:
                return HistoryPersistenceError(operation: operation, failure: .permissionDenied)
            case .fileReadCorruptFile:
                return HistoryPersistenceError(operation: operation, failure: .corrupt)
            default:
                break
            }
        }

        if nsError.domain == NSPOSIXErrorDomain {
            switch nsError.code {
            case Int(ENOSPC):
                return HistoryPersistenceError(operation: operation, failure: .storageFull)
            case Int(EACCES), Int(EPERM), Int(EROFS):
                return HistoryPersistenceError(operation: operation, failure: .permissionDenied)
            case Int(EBUSY):
                return HistoryPersistenceError(operation: operation, failure: .locked)
            default:
                break
            }
        }

        // GRDB wraps SQLite result codes, but this shared layer intentionally has no
        // GRDB dependency. Classification uses only keywords and discards the source
        // message immediately; no path-bearing text crosses this boundary.
        let diagnostic = error.localizedDescription.lowercased()
        if diagnostic.contains("database disk image is malformed")
            || diagnostic.contains("database corruption")
            || diagnostic.contains("not a database") {
            return HistoryPersistenceError(operation: operation, failure: .corrupt)
        }
        if diagnostic.contains("database is locked") || diagnostic.contains("database is busy") {
            return HistoryPersistenceError(operation: operation, failure: .locked)
        }
        if diagnostic.contains("disk is full") || diagnostic.contains("out of space") {
            return HistoryPersistenceError(operation: operation, failure: .storageFull)
        }
        if diagnostic.contains("read-only")
            || diagnostic.contains("permission denied")
            || diagnostic.contains("not authorized") {
            return HistoryPersistenceError(operation: operation, failure: .permissionDenied)
        }
        return HistoryPersistenceError(operation: operation, failure: .unavailable)
    }

    /// IOS-11: `error` is the suspended History database refusing or
    /// interrupting a statement. SQLite rolled the transaction back, nothing
    /// changed, and the same work succeeds once History resumes. A cancelled
    /// task sees `CancellationError` instead, never this.
    static func isSuspensionInterruption(_ error: Error) -> Bool {
        isInterruption(error as NSError)
    }

    /// GRDB's `DatabaseError` bridges to this domain with the extended SQLite
    /// result code, whose low byte is the primary code.
    static let sqliteErrorDomain = "GRDB.DatabaseError"
    private static let sqliteAbort = 4
    private static let sqliteInterrupt = 9

    private static func isInterruption(_ error: NSError) -> Bool {
        guard error.domain == sqliteErrorDomain else { return false }
        let primary = error.code & 0xFF
        return primary == sqliteAbort || primary == sqliteInterrupt
    }
}
