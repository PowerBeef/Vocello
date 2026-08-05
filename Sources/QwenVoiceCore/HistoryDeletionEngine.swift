import Foundation

/// Pure sequencing logic for History's irreversible delete paths (W2-B,
/// 2026-08 UI review): the 2026-08 architecture audit flagged these as
/// logic-in-view with no test seam. The engine owns the ordering rules and
/// failure semantics; every side effect is an injected closure, so the
/// deterministic core tests exercise the sequencing with stubs while the
/// app injects its database- and file-manager-backed implementations.
///
/// Rules encoded here (previously implicit in `HistoryView`):
/// - Single delete removes the database row FIRST; a database failure
///   aborts with nothing else touched. A subsequent audio-file removal
///   failure is a warning outcome, never a rollback — the row is gone and
///   the audio stays on disk.
/// - Clear-all sweeps audio files from a fresh database fetch (not the
///   loaded list) so rows written by other sessions are covered; per-file
///   failures are counted, never abort; the row wipe runs after the sweep.
public struct HistoryDeletionEngine: Sendable {
    public enum SingleOutcome: Equatable, Sendable {
        case deleted
        case databaseFailure(String)
        case audioCleanupFailure(String)
    }

    public struct ClearAllOutcome: Equatable, Sendable {
        public let failedFileRemovals: Int

        public init(failedFileRemovals: Int) {
            self.failedFileRemovals = failedFileRemovals
        }
    }

    public enum ClearAllError: Error, Equatable, Sendable {
        case database(String)
    }

    public var deleteRecord: @Sendable (Int64) throws -> Void
    public var deleteAllRecords: @Sendable () throws -> Void
    /// Audio paths of every persisted generation — the database is the
    /// source of truth for the clear-all sweep.
    public var audioPathsForAllRecords: @Sendable () throws -> [String]
    public var removeFile: @Sendable (String) throws -> Void
    public var fileExists: @Sendable (String) -> Bool

    public init(
        deleteRecord: @escaping @Sendable (Int64) throws -> Void,
        deleteAllRecords: @escaping @Sendable () throws -> Void,
        audioPathsForAllRecords: @escaping @Sendable () throws -> [String],
        removeFile: @escaping @Sendable (String) throws -> Void,
        fileExists: @escaping @Sendable (String) -> Bool
    ) {
        self.deleteRecord = deleteRecord
        self.deleteAllRecords = deleteAllRecords
        self.audioPathsForAllRecords = audioPathsForAllRecords
        self.removeFile = removeFile
        self.fileExists = fileExists
    }

    public func deleteSingle(recordID: Int64?, audioPath: String) -> SingleOutcome {
        guard let recordID else {
            return .databaseFailure("Missing generation identifier.")
        }
        do {
            try deleteRecord(recordID)
        } catch {
            return .databaseFailure(error.localizedDescription)
        }
        guard fileExists(audioPath) else {
            return .deleted
        }
        do {
            try removeFile(audioPath)
            return .deleted
        } catch {
            return .audioCleanupFailure(error.localizedDescription)
        }
    }

    public func clearAll(deleteAudio: Bool) throws -> ClearAllOutcome {
        var failures = 0
        do {
            if deleteAudio {
                for path in try audioPathsForAllRecords() where fileExists(path) {
                    do {
                        try removeFile(path)
                    } catch {
                        failures += 1
                    }
                }
            }
            try deleteAllRecords()
        } catch {
            throw ClearAllError.database(error.localizedDescription)
        }
        return ClearAllOutcome(failedFileRemovals: failures)
    }
}
