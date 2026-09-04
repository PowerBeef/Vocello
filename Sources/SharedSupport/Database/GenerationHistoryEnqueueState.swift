import Foundation
import Observation

enum GenerationHistoryPersistenceOutcome: Equatable, Sendable {
    case saved
    case queuedForRecovery
    case unableToQueue

    func requireSavedLongFormSegment() throws {
        guard self == .saved else { throw LongFormSegmentHistoryError.recoveryRequired }
    }
}

enum LongFormSegmentHistoryError: LocalizedError {
    case recoveryRequired
    var errorDescription: String? {
        VocelloPresentationText.longFormSegmentHistoryFailed
    }
}

/// Only the failure to create a durable outbox record is retained here. This
/// app-session memory is explicitly NOT crash recovery; the WAV stays on disk
/// and the UI must offer export before quitting. Database failures still use
/// the existing durable outbox, not a second persistence system.
@MainActor
@Observable
final class GenerationHistoryEnqueueState {
    private(set) var records: [String: Generation] = [:]

    var availableAudioURLs: [URL] {
        records.keys.sorted().filter { FileManager.default.fileExists(atPath: $0) }
            .map { URL(fileURLWithPath: $0) }
    }

    func enqueue(
        _ generation: Generation,
        using write: (Generation) throws -> GenerationHistoryOutboxEntry
    ) -> (GenerationHistoryPersistenceOutcome, GenerationHistoryOutboxEntry?) {
        do {
            let entry = try write(generation)
            records.removeValue(forKey: generation.audioPath)
            return (.queuedForRecovery, entry)
        } catch {
            // Repeated attempts keep the original identity/transcript/seed.
            if records[generation.audioPath] == nil { records[generation.audioPath] = generation }
            return (.unableToQueue, nil)
        }
    }

    /// Called by an explicit recovery action / History reconciliation. This
    /// retries storage only; it never invokes synthesis or changes the seed.
    func retry(using write: (Generation) throws -> GenerationHistoryOutboxEntry) {
        for record in records.values.sorted(by: { $0.audioPath < $1.audioPath }) {
            _ = enqueue(record, using: write)
        }
    }

    func persist(
        _ generation: Generation,
        enqueue write: (Generation) throws -> GenerationHistoryOutboxEntry,
        commit: (GenerationHistoryOutboxEntry) async throws -> Generation,
        onSaved: (Generation) -> Void
    ) async -> GenerationHistoryPersistenceOutcome {
        let (outcome, entry) = enqueue(generation, using: write)
        guard let entry else { return outcome }
        do {
            let saved = try await commit(entry)
            onSaved(saved)
            return .saved
        } catch {
            return .queuedForRecovery
        }
    }
}
