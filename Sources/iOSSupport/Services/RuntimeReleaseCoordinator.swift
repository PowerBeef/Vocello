import Combine
import Foundation
import QwenVoiceCore

@MainActor
enum RuntimeReleaseAction: Equatable {
    case none
    case deferred(reason: String)
    case execute(reason: String, wasDeferred: Bool)
}

/// Severity signaled alongside a cache-relief request. `warning` may be
/// deferred while a generation is active; `critical` must run immediately
/// because the generation itself may be the source of the pressure.
@MainActor
enum MemoryPressureSeverity: Equatable {
    case warning
    case critical
}

@MainActor
enum MemoryPressureReliefAction: Equatable {
    case none
    case deferred(reason: String)
    case execute(reason: String, cancelActiveGeneration: Bool)
}

@MainActor
enum CriticalMemoryReliefOutcome: Equatable {
    case completed
    case cancellationFailed
    case alreadyInFlight
}

/// Orders critical-pressure relief behind the engine's typed terminal
/// cancellation barrier, then releases runtime ownership only after the relief
/// closure returns. Neither later phase runs when termination cannot be
/// proven, which keeps a full unload from racing live MLX compute and keeps UI
/// admission closed until that unload has completed.
@MainActor
enum CriticalMemoryReliefExecutor {
    static func execute(
        cancel: (GenerationCancellationReason) async throws -> Void,
        applyRelief: () async -> Void,
        releaseOwnership: () async -> Void
    ) async -> CriticalMemoryReliefOutcome {
        do {
            try await cancel(.memoryPressure)
        } catch {
            return .cancellationFailed
        }

        await applyRelief()
        await releaseOwnership()
        return .completed
    }
}

/// Orders a critical full unload so its diagnostics event is a completion boundary: the event
/// is recorded only after the awaited unload returned, and backend generation activity is
/// cleared exactly once, after that record. `@MainActor` for the same reason as
/// `CriticalMemoryReliefExecutor`: `TTSEngineStore` passes MainActor-bound closures.
@MainActor
enum CriticalMemoryFullUnloadSequence {
    static func execute(
        unload: () async -> Void,
        recordUnloadCompleted: () -> Void,
        clearGenerationActivity: () -> Void
    ) async {
        await unload()
        recordUnloadCompleted()
        clearGenerationActivity()
    }
}

@MainActor
final class RuntimeReleaseCoordinator: ObservableObject {
    @Published private(set) var pendingReason: String?
    @Published private(set) var pendingCacheReliefReason: String?
    @Published private(set) var isReleaseInFlight = false

    func requestRelease(reason: String, hasActiveGeneration: Bool) -> RuntimeReleaseAction {
        if hasActiveGeneration || isReleaseInFlight {
            pendingReason = reason
            return .deferred(reason: reason)
        }

        isReleaseInFlight = true
        return .execute(reason: reason, wasDeferred: false)
    }

    func executeDeferredReleaseIfReady(hasActiveGeneration: Bool) -> RuntimeReleaseAction {
        guard !hasActiveGeneration, !isReleaseInFlight, let pendingReason else {
            return .none
        }

        self.pendingReason = nil
        isReleaseInFlight = true
        return .execute(reason: pendingReason, wasDeferred: true)
    }

    func completeRelease(hasActiveGeneration: Bool) -> RuntimeReleaseAction {
        isReleaseInFlight = false
        return executeDeferredReleaseIfReady(hasActiveGeneration: hasActiveGeneration)
    }

    func requestCacheRelief(
        reason: String,
        severity: MemoryPressureSeverity = .warning,
        hasActiveGeneration: Bool
    ) -> MemoryPressureReliefAction {
        switch severity {
        case .critical:
            // Critical pressure cannot wait for generation to finish — the
            // generation is frequently the cause. Clear any pending deferred
            // relief and run the trim path immediately, requesting that the
            // active generation be cancelled in the same step (Tier 1.6).
            pendingCacheReliefReason = nil
            return .execute(
                reason: reason,
                cancelActiveGeneration: hasActiveGeneration
            )
        case .warning:
            if hasActiveGeneration {
                pendingCacheReliefReason = reason
                return .deferred(reason: reason)
            }
            return .execute(reason: reason, cancelActiveGeneration: false)
        }
    }

    func executeDeferredCacheReliefIfReady(
        hasActiveGeneration: Bool
    ) -> MemoryPressureReliefAction {
        guard !hasActiveGeneration, let pendingCacheReliefReason else {
            return .none
        }

        self.pendingCacheReliefReason = nil
        return .execute(reason: pendingCacheReliefReason, cancelActiveGeneration: false)
    }
}
