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
            try DatabaseService.shared.fetchAllGenerationsForClear()
        },
        deleteGenerationsThrough: { maxRowID in
            try DatabaseService.shared.deleteGenerations(throughID: maxRowID)
        },
        referencedAudioPaths: { audioPaths in
            try DatabaseService.shared.referencedAudioPaths(among: audioPaths)
        }
    )

    /// The single-row delete's database and file side. The sequencing rules
    /// live tested in `QwenVoiceCore.HistoryDeletionEngine`; it runs only
    /// through `deleteSingle`, which records the audio removal first.
    private static let deletionEngine = HistoryDeletionEngine(
        deleteRecord: { try DatabaseService.shared.deleteGeneration(id: $0) },
        removeFile: { try removeUnreferencedAudio(atPath: $0) },
        fileExists: { FileManager.default.fileExists(atPath: $0) }
    )

    /// Single-row delete for both History screens, on the recovery coordinator
    /// (A2-04): the audio removal is listed before the row goes, so a process
    /// that dies in between leaves it for a later reconcile. An audio file that
    /// cannot be removed is a warning outcome, which the screens report and
    /// hand to `retainAudioRemoval(_:)`. Off the main actor: a synchronous
    /// SQLite write and a file removal.
    static func deleteSingle(recordID: Int64?, audioPath: String) async -> HistoryDeletionEngine.SingleOutcome {
        await coordinator.deleteSingle(recordID: recordID, audioPath: audioPath, using: deletionEngine)
    }

    /// A deleted row's audio, removed only when nothing else uses it
    /// (`GenerationHistoryAudioFile.removeUnreferenced`).
    static func removeUnreferencedAudio(atPath path: String) throws {
        try GenerationHistoryAudioFile.removeUnreferenced(
            atPath: path,
            outbox: outboxStore,
            referencedAudioPaths: { try DatabaseService.shared.referencedAudioPaths(among: $0) }
        )
    }

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
        // A long-form acceptance a suspended History interrupted completes here
        // after resume (PA-30); one that cannot stays visible as pending recovery.
        try? DatabaseService.shared.reconcileLongFormRecovery()
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
            pendingAudioRemovalCount: durable.pendingAudioRemovalCount,
            unreadableAudioRemovalCount: durable.unreadableAudioRemovalCount,
            unverifiableRecordCount: durable.unverifiableRecordCount)
    }

    /// Retry on the notice about removal lists that could not be read (PA-30):
    /// the user has seen it, so the lists are discarded. The audio they named
    /// is not deleted. A failure leaves the notice for another Retry.
    static func discardUnreadableAudioRemovals() async {
        try? await coordinator.discardUnreadableAudioRemovals()
    }

    /// The user confirmed discarding the queued records that cannot be read
    /// or verified (A2-02): they are set aside, never deleted, and no audio is
    /// touched. A failure leaves the notice and its Discard action in place.
    static func setAsideUnverifiableRecords() async {
        _ = try? await coordinator.setAsideUnverifiableRecords()
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
        // A keep-files request reaches a pending clear even when it is refused
        // below, so a later resume never deletes the audio (AUD-05).
        if !deleteAudio {
            try await coordinator.keepAudioOfPendingClear()
        }
        // Never discard unqueued identity or silently exclude its audio from
        // the durable clear transaction. First retry saving or export it.
        guard await unqueued.records.isEmpty else { throw GenerationHistoryOutboxError.clearUnavailable }
        return try await coordinator.clearAll(deleteAudio: deleteAudio)
    }
}
