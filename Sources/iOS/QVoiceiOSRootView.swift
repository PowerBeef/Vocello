import SwiftUI
import QwenVoiceCore

/// Thin shell that owns the `AppModel` lifetime and injects it into the
/// environment. The real tab routing + screen content lives in
/// `Sources/iOS/App/RootView.swift`. Kept under this filename so the
/// existing app entry point + Xcode scheme don't need renaming.
///
/// iOS is compile-safe only on `main` (see CLAUDE.md "What this is").
struct QVoiceiOSRootView: View {
    let modelRegistry: ContractBackedModelRegistry
    /// Passed through to `RootView` as a deliberately non-observing reference
    /// (IUI-5 P2); this shell must not subscribe to the store either.
    let ttsEngine: TTSEngineStore

    @State private var appModel: AppModel

    init(modelRegistry: ContractBackedModelRegistry, ttsEngine: TTSEngineStore) {
        self.modelRegistry = modelRegistry
        self.ttsEngine = ttsEngine
        _appModel = State(initialValue: AppModel(modelRegistry: modelRegistry))
    }

    var body: some View {
        RootView(ttsEngine: ttsEngine)
            .environment(appModel)
    }
}
