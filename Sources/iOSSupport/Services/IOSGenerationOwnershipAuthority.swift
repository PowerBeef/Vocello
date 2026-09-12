import Foundation

/// Pure ownership authority for the in-process iOS engine runtime.
///
/// `TTSEngineStore` owns one generation scope, counted by `activeGenerationDepth`, that keeps
/// UI admission closed while audio is produced. A critical-memory action claims that same scope
/// so that, between its cancellation barrier and its awaited full unload, nothing can observe the
/// runtime as idle, admit a second generation, or let the finishing generation hand the scope
/// back early.
///
/// The store mirrors the scope into its published `hasActiveGeneration` at the same statements
/// it always did. That published flag additionally folds in the backend's own activity snapshot
/// (`syncFromSnapshot`), which is why `admitsGeneration` takes it as an input instead of deriving
/// it here.
struct IOSGenerationOwnershipAuthority: Equatable, Sendable {
    /// What the owner must do when a generation body finishes.
    enum GenerationCompletion: Equatable, Sendable {
        /// The scope was returned: stop the memory guard and publish idle.
        case released
        /// A critical-memory action holds the scope until its awaited full unload completes.
        /// The owner must neither stop the memory guard nor clear generation ownership.
        case retainedByCriticalMemoryAction
    }

    private(set) var activeGenerationDepth = 0
    private(set) var criticalMemoryActionInFlight = false

    /// True while at least one generation scope is held (by a generation or a critical action).
    var ownsGenerationScope: Bool { activeGenerationDepth > 0 }

    /// Admission predicate evaluated both before and after the asynchronous admission snapshot.
    /// - Parameter hasActiveGeneration: the store's published flag (held scope OR backend
    ///   activity). A critical action that claimed the runtime while the snapshot was in flight
    ///   closes admission through `criticalMemoryActionInFlight`.
    func admitsGeneration(hasActiveGeneration: Bool) -> Bool {
        !hasActiveGeneration && !criticalMemoryActionInFlight
    }

    /// A generation body claims one scope.
    mutating func enterGeneration() {
        activeGenerationDepth += 1
    }

    /// A generation body finished (returned, threw, or was cancelled). While a critical-memory
    /// action is in flight the scope stays claimed and nothing changes.
    mutating func completeGeneration() -> GenerationCompletion {
        guard !criticalMemoryActionInFlight else { return .retainedByCriticalMemoryAction }
        activeGenerationDepth = max(activeGenerationDepth - 1, 0)
        return .released
    }

    /// Called after the backend's terminal cancellation barrier returned without throwing.
    /// Returns `false`, changing nothing, while a critical-memory action still holds the scope.
    mutating func releaseGenerationAfterCancellationBarrier() -> Bool {
        guard !criticalMemoryActionInFlight else { return false }
        activeGenerationDepth = 0
        return true
    }

    /// Claims the critical-memory action and exactly one generation scope, so a backend
    /// cancellation terminal racing the MainActor task cannot make the runtime look idle while
    /// the full unload is awaited. Fails when an action is already in flight.
    mutating func beginCriticalMemoryAction() -> Bool {
        guard !criticalMemoryActionInFlight else { return false }
        criticalMemoryActionInFlight = true
        activeGenerationDepth = max(activeGenerationDepth, 1)
        return true
    }

    /// The awaited full unload completed: return every generation scope while the action claim
    /// still closes admission. The owner publishes its idle flag between this call and
    /// `completeCriticalMemoryAction()`, so a synchronous observer of that publish can neither
    /// admit a generation nor begin a second critical action. Without a held claim nothing
    /// changes and `false` is returned: only the claim holder may return a live generation scope.
    @discardableResult
    mutating func releaseGenerationScopeAfterCriticalUnload() -> Bool {
        guard criticalMemoryActionInFlight else { return false }
        activeGenerationDepth = 0
        return true
    }

    /// Releases the action claim once the owner has published idle. Any scope still held is
    /// returned too, so the authority is idle afterwards whatever the caller did in between.
    /// Without a held claim nothing changes and `false` is returned.
    @discardableResult
    mutating func completeCriticalMemoryAction() -> Bool {
        guard criticalMemoryActionInFlight else { return false }
        activeGenerationDepth = 0
        criticalMemoryActionInFlight = false
        return true
    }

    /// Termination could not be proven: drop the action claim so the still-running guard can
    /// retry, but keep generation ownership so no observer trims live MLX state.
    mutating func abandonCriticalMemoryActionAfterCancellationFailure() {
        criticalMemoryActionInFlight = false
    }
}
