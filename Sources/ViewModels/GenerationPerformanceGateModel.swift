import Combine
import Observation
import QwenVoiceCore

/// Scopes the §K generation performance gate to its own tiny observable
/// (2026-08 UI review, W1-D). The root shell previously read
/// `hasActiveGeneration`/`hasSustainedPerformanceActivity` straight off the
/// whole `TTSEngineStore` in `ContentView.body`, so every engine tick
/// re-diffed the entire `NavigationSplitView` during the most contended
/// windows (measured 158 ms/s hitch while generating with glass already
/// off). This model republishes only the boolean *flips*: the shell now
/// invalidates at generation start/stop instead of per event. The app creates
/// it once with the store, so a re-created shell never resubscribes.
@MainActor
@Observable
final class GenerationPerformanceGateModel {
    private(set) var isActive = false
    @ObservationIgnored private var activityUpdates: AnyCancellable?

    init(store: TTSEngineStore) {
        isActive = store.hasActiveGeneration || store.hasSustainedPerformanceActivity
        activityUpdates = store.performanceActivityUpdates
            .removeDuplicates()
            .sink { [weak self] isActive in self?.isActive = isActive }
    }
}
