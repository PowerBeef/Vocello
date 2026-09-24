import SwiftUI
import QwenVoiceCore

/// Thin shell that owns the `AppModel` lifetime and injects it into the
/// environment. The real tab routing + screen content lives in
/// `Sources/iOS/App/RootView.swift`. Kept under this filename so the
/// existing app entry point + Xcode scheme don't need renaming.
///
/// iOS is compile-safe only on `main` (see CLAUDE.md "Product and authority").
struct QVoiceiOSRootView: View {
    let modelRegistry: ContractBackedModelRegistry
    /// Passed through to `RootView` as a deliberately non-observing reference
    /// (IUI-5 P2); this shell must not subscribe to the store either.
    let ttsEngine: TTSEngineStore
    /// App-owned foreground-exit handler (PA-15); it reaches the Studio through
    /// the installed `AppModel`.
    let backgroundGeneration: IOSBackgroundGenerationController

    @State private var appModel: AppModel
    @Environment(\.scenePhase) private var scenePhase

    init(
        modelRegistry: ContractBackedModelRegistry,
        ttsEngine: TTSEngineStore,
        backgroundGeneration: IOSBackgroundGenerationController
    ) {
        self.modelRegistry = modelRegistry
        self.ttsEngine = ttsEngine
        self.backgroundGeneration = backgroundGeneration
        _appModel = State(initialValue: AppModel(modelRegistry: modelRegistry))
    }

    var body: some View {
        RootView(ttsEngine: ttsEngine)
            .environment(appModel)
            .onAppear { backgroundGeneration.attach(appModel) }
            // PA-21 (IOS-09): iOS may terminate the app once it is backgrounded,
            // so the drafts are saved every time the scene leaves the foreground.
            .onChange(of: scenePhase) { _, newPhase in
                if newPhase != .active {
                    appModel.persistDrafts()
                }
            }
    }
}
