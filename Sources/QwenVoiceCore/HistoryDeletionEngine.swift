import Foundation

/// Pure sequencing logic for History's irreversible delete paths (W2-B,
/// 2026-08 UI review): the 2026-08 architecture audit flagged these as
/// logic-in-view with no test seam. The engine owns the ordering rules and
/// failure semantics; every side effect is an injected closure, so the
/// deterministic core tests exercise the sequencing with stubs while the
/// app injects its database- and file-manager-backed implementations.
///
/// Rules encoded here (previously implicit in `HistoryView`):
/// - Single delete records the audio removal durably FIRST (A2-04), as a
///   clear records its intent before deleting anything: a process that dies
///   once the row is gone still leaves the path for a later retry. A removal
///   that cannot be recorded aborts with nothing else touched.
/// - Then the database row; a database failure aborts with nothing else
///   touched, and the recorded removal is withdrawn. A subsequent audio-file
///   removal failure is a warning outcome, never a rollback — the row is gone,
///   the audio stays on disk, and its removal stays recorded for a retry. A
///   removed file's record is withdrawn.
/// Clear-all is not here: it runs only through the durable, bounded
/// `GenerationHistoryRecoveryCoordinator` transaction (AUD-05).
public struct HistoryDeletionEngine: Sendable {
    public enum SingleOutcome: Equatable, Sendable {
        case deleted
        case databaseFailure(String)
        /// The audio removal could not be recorded, so nothing was deleted;
        /// the database itself is fine.
        case removalUnrecorded
        case audioCleanupFailure(String)
    }

    public var deleteRecord: @Sendable (Int64) throws -> Void
    public var removeFile: @Sendable (String) throws -> Void
    public var fileExists: @Sendable (String) -> Bool
    /// Durably lists an audio path for removal before its row goes (A2-04).
    public var recordAudioRemoval: @Sendable (String) throws -> Void
    /// Drops a listed path once its file is gone, or when its row stayed.
    public var withdrawAudioRemoval: @Sendable (String) -> Void

    public init(
        deleteRecord: @escaping @Sendable (Int64) throws -> Void,
        removeFile: @escaping @Sendable (String) throws -> Void,
        fileExists: @escaping @Sendable (String) -> Bool,
        recordAudioRemoval: @escaping @Sendable (String) throws -> Void = { _ in },
        withdrawAudioRemoval: @escaping @Sendable (String) -> Void = { _ in }
    ) {
        self.deleteRecord = deleteRecord
        self.removeFile = removeFile
        self.fileExists = fileExists
        self.recordAudioRemoval = recordAudioRemoval
        self.withdrawAudioRemoval = withdrawAudioRemoval
    }

    /// `describe` turns a failure into the text a screen shows; the apps pass
    /// their interface-language mapping, the default is the error's own text.
    public func deleteSingle(
        recordID: Int64?,
        audioPath: String,
        describe: (any Error) -> String = { $0.localizedDescription }
    ) -> SingleOutcome {
        guard let recordID else {
            return .databaseFailure("Missing generation identifier.")
        }
        let hasAudio = fileExists(audioPath)
        if hasAudio {
            do {
                try recordAudioRemoval(audioPath)
            } catch {
                return .removalUnrecorded
            }
        }
        do {
            try deleteRecord(recordID)
        } catch {
            if hasAudio { withdrawAudioRemoval(audioPath) }
            return .databaseFailure(describe(error))
        }
        guard hasAudio else {
            return .deleted
        }
        do {
            try removeFile(audioPath)
        } catch {
            return .audioCleanupFailure(describe(error))
        }
        withdrawAudioRemoval(audioPath)
        return .deleted
    }
}
