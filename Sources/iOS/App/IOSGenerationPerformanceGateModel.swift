import Combine

/// Scopes the fixed-refresh generation performance gate to its own tiny
/// observable (IUI-5 P2 — the direct port of the macOS
/// `GenerationPerformanceGateModel`, W1-D of the 2026-08 macOS UI review).
/// `RootView` previously read `hasActiveGeneration` /
/// `hasSustainedPerformanceActivity` straight off the whole `TTSEngineStore`,
/// so every engine publish re-diffed the entire root shell — all mounted
/// NavigationStacks, the dock chrome, and the overlay plumbing — during the
/// most contended windows. This model republishes only the boolean *flips*:
/// the shell now invalidates at generation start/stop instead of per event.
@MainActor
final class IOSGenerationPerformanceGateModel: ObservableObject {
    @Published private(set) var isActive = false

    init(store: TTSEngineStore) {
        isActive = store.hasActiveGeneration || store.hasSustainedPerformanceActivity
        store.performanceActivityUpdates
            .removeDuplicates()
            .assign(to: &$isActive)
    }
}
