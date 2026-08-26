import Foundation

/// Live adapter binding the shared outbox/coordinator to each platform's
/// app-support root and DatabaseService implementation.
enum GenerationHistoryRecovery {
    static let outboxStore = GenerationHistoryOutboxStore(
        rootURL: AppPaths.appSupportDir.appendingPathComponent("history-outbox", isDirectory: true)
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
        }
    )

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
        await coordinator.reconcile()
    }

    static func snapshot() async -> GenerationHistoryRecoverySnapshot {
        await coordinator.snapshot()
    }

    static func pendingAudioURLs() async -> [URL] {
        await coordinator.pendingAudioURLs()
    }

    static func clearAll(deleteAudio: Bool) async throws -> GenerationHistoryClearOutcome {
        try await coordinator.clearAll(deleteAudio: deleteAudio)
    }
}
