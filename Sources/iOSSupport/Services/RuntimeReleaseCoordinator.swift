import Foundation
import Observation
import QwenVoiceCore

public enum RuntimeReleaseAction: Equatable, Sendable {
    case none
    case deferred(reason: String)
    case execute(reason: String, wasDeferred: Bool)
}

/// Severity signaled alongside a cache-relief request. `warning` may be
/// deferred while a generation is active; `critical` must run immediately
/// because the generation itself may be the source of the pressure.
public enum MemoryPressureSeverity: Equatable, Sendable {
    case warning
    case critical
}

public enum MemoryPressureReliefAction: Equatable, Sendable {
    case none
    case deferred(reason: String)
    case execute(reason: String, cancelActiveGeneration: Bool)
}

public enum CriticalMemoryReliefOutcome: Equatable, Sendable {
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
public enum CriticalMemoryReliefExecutor {
    public static func execute(
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
public enum CriticalMemoryFullUnloadSequence {
    public static func execute(
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
@Observable
public final class RuntimeReleaseCoordinator {
    public private(set) var pendingReason: String?
    public private(set) var pendingCacheReliefReason: String?
    public private(set) var isReleaseInFlight = false

    public init() {}

    public func requestRelease(reason: String, hasActiveGeneration: Bool) -> RuntimeReleaseAction {
        if hasActiveGeneration || isReleaseInFlight {
            pendingReason = reason
            return .deferred(reason: reason)
        }

        isReleaseInFlight = true
        return .execute(reason: reason, wasDeferred: false)
    }

    public func executeDeferredReleaseIfReady(hasActiveGeneration: Bool) -> RuntimeReleaseAction {
        guard !hasActiveGeneration, !isReleaseInFlight, let pendingReason else {
            return .none
        }

        self.pendingReason = nil
        isReleaseInFlight = true
        return .execute(reason: pendingReason, wasDeferred: true)
    }

    public func completeRelease(hasActiveGeneration: Bool) -> RuntimeReleaseAction {
        isReleaseInFlight = false
        return executeDeferredReleaseIfReady(hasActiveGeneration: hasActiveGeneration)
    }

    /// Drops a deferred release requested for `reason` so it can never fire later
    /// (the app returned to the foreground before the generation terminated).
    /// A release already in flight, or one pending for another reason, is kept.
    @discardableResult
    public func cancelPendingRelease(reason: String) -> Bool {
        guard pendingReason == reason else { return false }
        pendingReason = nil
        return true
    }

    public func requestCacheRelief(
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

    public func executeDeferredCacheReliefIfReady(
        hasActiveGeneration: Bool
    ) -> MemoryPressureReliefAction {
        guard !hasActiveGeneration, let pendingCacheReliefReason else {
            return .none
        }

        self.pendingCacheReliefReason = nil
        return .execute(reason: pendingCacheReliefReason, cancelActiveGeneration: false)
    }
}
