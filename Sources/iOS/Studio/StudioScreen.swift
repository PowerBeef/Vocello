import SwiftUI
import QwenVoiceCore

/// Unified Studio screen.
///
/// Replaces the legacy `IOSGenerateContainerView` as the entry point
/// for the `.studio` tab. Reads everything from the injected
/// `AppModel`; renders the design's flat Studio layout from
/// `design_references/Vocello iOS/studio.jsx`:
///
///   ┌─────────────────────────────┐
///   │ ModeSegmented               │
///   │ per-mode body (IOSStudioCanvas)
///   │   composer                  │
///   │   setup chips               │
///   │   dock area (CTA / gen / player)
///   └─────────────────────────────┘
///
/// Phase 3 (complete as designed) — the per-mode views
/// (`IOSCustomVoiceView`, `IOSVoiceDesignView`, `IOSVoiceCloningView`)
/// render `IOSStudioCanvas` internally with the right chip
/// configuration. Their UI-visible generation lifecycle state lives on
/// `AppModel`'s per-mode `StudioGenerationCoordinator`s (Phase 3b); the
/// engine-call assembly deliberately stays in the per-mode views
/// because each builds a mode-specific payload from its draft plus
/// environment-owned stores. Collapsing them into a single `StudioBody`
/// was evaluated and rejected — it would trade three straightforward
/// views for one view with three-way branching everywhere.
///
/// The prefetch coordinator and engine signposts continue to live in
/// the existing per-mode bodies. `RootView` owns the bottom chrome,
/// including the global TabDock, engine toast, and now-playing rail.
struct StudioScreen: View {
    @Environment(AppModel.self) private var appModel

    var body: some View {
        @Bindable var appModel = appModel

        IOSGenerateContainerView(
            selectedTab: $appModel.tab,
            selectedSection: $appModel.studioMode,
            customVoiceDraft: $appModel.customVoiceDraft,
            voiceDesignDraft: $appModel.voiceDesignDraft,
            voiceCloningDraft: $appModel.voiceCloningDraft,
            pendingVoiceCloningHandoff: $appModel.pendingVoiceCloningHandoff
        )
    }
}
