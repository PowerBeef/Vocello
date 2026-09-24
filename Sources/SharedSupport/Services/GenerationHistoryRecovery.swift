import Foundation
import QwenVoiceCore

/// Live adapter binding the shared outbox/coordinator to each platform's
/// app-support root and DatabaseService implementation.
enum GenerationHistoryRecovery {
    @MainActor static let unqueued = GenerationHistoryEnqueueState()
    static let outboxStore = GenerationHistoryOutboxStore(
        rootURL: AppPaths.appSupportDir.appendingPathComponent("history-outbox", isDirectory: true)
    )
    static let longFormStore = LongFormHistoryAcceptanceStore(
        rootURL: AppPaths.appSupportDir.appendingPathComponent("history-outbox/long-form", isDirectory: true)
    )

    static let coordinator = GenerationHistoryRecoveryCoordinator(
        store: outboxStore,
        commitGeneration: { operation, generation in
            switch operation {
            case .append:
                return try await DatabaseService.shared.saveGenerationIfMissingAsync(generation)
            case .replaceLongFormJoined:
                return try await DatabaseService.shared.replaceLongFormJoinedGenerationIfMissingAsync(generation)
            }
        },
        fetchAllGenerations: {
            try DatabaseService.shared.fetchAllGenerations()
        },
        deleteAllGenerations: {
            try DatabaseService.shared.deleteAllGenerations()
        },
        referencedAudioPaths: { audioPaths in
            try DatabaseService.shared.referencedAudioPaths(among: audioPaths)
        }
    )

    /// Single-row delete for both History screens. The sequencing rules live
    /// tested in `QwenVoiceCore.HistoryDeletionEngine`: the row goes first, and
    /// an audio file that then cannot be removed is a warning outcome, which
    /// the screens report and hand to `retainAudioRemoval(_:)`.
    static let deletionEngine = HistoryDeletionEngine(
        deleteRecord: { try DatabaseService.shared.deleteGeneration(id: $0) },
        deleteAllRecords: { try DatabaseService.shared.deleteAllGenerations() },
        audioPathsForAllRecords: { try DatabaseService.shared.fetchAllGenerations().map(\.audioPath) },
        removeFile: { try FileManager.default.removeItem(atPath: $0) },
        fileExists: { FileManager.default.fileExists(atPath: $0) }
    )

    /// Keeps the audio of a deleted row for a later reconcile to remove (AUD-05).
    /// `false` when even the pending list could not be written.
    static func retainAudioRemoval(_ audioPath: String) async -> Bool {
        do {
            try await coordinator.retainAudioRemoval(audioPath)
            return true
        } catch {
            return false
        }
    }

    static func enqueue(
        _ generation: Generation,
        operation: GenerationHistoryOutboxOperation = .append
    ) throws -> GenerationHistoryOutboxEntry {
        try outboxStore.enqueue(generation, operation: operation)
    }

    static func persist(
        _ generation: Generation,
        operation: GenerationHistoryOutboxOperation = .append
    ) async throws -> Generation {
        let entry = try enqueue(generation, operation: operation)
        return try await coordinator.commit(entry)
    }

    static func reconcile() async -> GenerationHistoryReconciliationResult {
        await unqueued.retry { try enqueue($0) }
        let result = await coordinator.reconcile()
        return GenerationHistoryReconciliationResult(committed: result.committed, snapshot: await snapshot())
    }

    static func snapshot() async -> GenerationHistoryRecoverySnapshot {
        let durable = await coordinator.snapshot()
        let unqueuedCount = await unqueued.records.count
        let available = await unqueued.availableAudioURLs.count
        return GenerationHistoryRecoverySnapshot(pendingCount: durable.pendingCount,
            availableAudioCount: durable.availableAudioCount + available,
            issueCount: durable.issueCount, clearRecoveryPending: durable.clearRecoveryPending,
            unqueuedCount: unqueuedCount, longFormRecoveryPending: longFormStore.hasPendingRecovery,
            pendingAudioRemovalCount: durable.pendingAudioRemovalCount)
    }

    static func pendingAudioURLs() async -> [URL] {
        let durable = await coordinator.pendingAudioURLs()
        return Array(Set(durable + (await unqueued.availableAudioURLs))).sorted { $0.path < $1.path }
    }

    static func recoveryExportURLs() async -> [URL] {
        let audio = await pendingAudioURLs()
        // Failure leaves the banner visible and never exports an unbounded or
        // redirected file. Ordinary queued audio remains exportable.
        let journals = (try? longFormStore.recoveryExportURLs()) ?? []
        return audio + journals
    }

    static func clearAll(deleteAudio: Bool) async throws -> GenerationHistoryClearOutcome {
        // Never discard unqueued identity or silently exclude its audio from
        // the durable clear transaction. First retry saving or export it.
        guard await unqueued.records.isEmpty else { throw GenerationHistoryOutboxError.clearUnavailable }
        return try await coordinator.clearAll(deleteAudio: deleteAudio)
    }
}
