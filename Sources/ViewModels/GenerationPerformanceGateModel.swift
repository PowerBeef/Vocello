import Combine
import QwenVoiceNative

/// Scopes the §K generation performance gate to its own tiny observable
/// (2026-08 UI review, W1-D). The root shell previously read
/// `hasActiveGeneration`/`hasSustainedPerformanceActivity` straight off the
/// whole `TTSEngineStore` in `ContentView.body`, so every engine tick
/// re-diffed the entire `NavigationSplitView` during the most contended
/// windows (measured 158 ms/s hitch while generating with glass already
/// off). This model republishes only the boolean *flips*: the shell now
/// invalidates at generation start/stop instead of per event.
final class GenerationPerformanceGateModel: ObservableObject {
    @Published private(set) var isActive = false

    @MainActor
    init(store: TTSEngineStore) {
        isActive = store.hasActiveGeneration || store.hasSustainedPerformanceActivity
        store.performanceActivityUpdates
            .removeDuplicates()
            .assign(to: &$isActive)
    }
}
