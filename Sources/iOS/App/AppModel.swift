import Foundation
import Observation
import SwiftUI
import QwenVoiceCore

struct IOSDeleteModelSheetPresentation: Identifiable {
    let id = UUID()
    let modelName: String
    let sizeLabel: String
    let onConfirm: @MainActor () -> Void
}

struct IOSBottomPanelPresentation: Identifiable {
    let id: String
    let content: @MainActor (_ bottomSafeAreaInset: CGFloat, _ availableHeight: CGFloat, _ dismiss: @escaping @MainActor () -> Void) -> AnyView

    init(
        id: String = UUID().uuidString,
        content: @escaping @MainActor (_ bottomSafeAreaInset: CGFloat, _ availableHeight: CGFloat, _ dismiss: @escaping @MainActor () -> Void) -> AnyView
    ) {
        self.id = id
        self.content = content
    }
}

/// Root state model for the iOS app, replacing the bag of `@State`
/// properties that lived inside `QVoiceiOSRootView`. Conformant to
/// `Observable` so views read state via `@Environment(AppModel.self)`
/// or `@Bindable` rather than the legacy `@StateObject` /
/// `@ObservableObject` / `@Published` triplet.
///
/// Per `references/state-management.md`: prefer `@Observable` over
/// `ObservableObject` on iOS 17+, and pair with `@Bindable` when a child
/// view needs to write back. Anything passed by value stays a `let`.
///
/// Migration status (all phases complete, 2026-07):
/// - Phase 2: tab, studioMode, drafts, onboarding gate, player sheet
///   item live here; screens read `@Environment(AppModel.self)`.
/// - Phase 3b: per-mode generation lifecycle state lives in the three
///   `StudioGenerationCoordinator` instances below. The engine call
///   (`ttsEngine.generate`) intentionally stays in the per-mode views —
///   see the coordinator section comment. Complete as designed.
/// - Phase 5: presentation state is centralized on this model as three
///   typed surfaces rather than one `presentedSheet` enum:
///   `playerSheetItem` (system sheet), `deleteModelSheetItem` and
///   `bottomPanelItem` (edge-to-edge overlays hosted by `RootView` at
///   fixed z-order). Every custom overlay presents/dismisses through
///   the `present…`/`dismiss…` methods below so the focus-backdrop flag
///   can never desync from the item. A single enum was rejected: the
///   payloads and hosting differ per surface, so merging them would
///   churn call sites without removing any dismiss/race path.
///   System-modal presentations (fileImporter, alerts, confirmation
///   dialogs, the save-voice sheet, recorder fullScreenCovers) stay as
///   local `@State` in their owning views — SwiftUI presents them
///   modally above the app, so they cannot race the AppModel overlays.
///   Complete as designed.
@MainActor
@Observable
final class AppModel {
    // MARK: - Routing

    /// The bottom-tab destination currently visible. Defaults to Studio.
    /// Persisted for state restoration (didSet fires only on post-init changes).
    var tab: IOSAppTab = .studio {
        didSet { IOSAppDefaults.lastTabRawValue = tab.rawValue }
    }

    /// Which mode the unified Studio screen is currently editing.
    /// Cold launch always starts on `.custom`; mode persists only for the
    /// current session (background/foreground). Explicit handoffs (Voices →
    /// Clone, etc.) still set this in-session.
    var studioMode: IOSGenerationSection = .custom

    // MARK: - Drafts

    /// Built-in-speaker generation draft (Custom mode).
    var customVoiceDraft: CustomVoiceDraft

    /// Brief-driven generation draft (Voice Design mode).
    var voiceDesignDraft = VoiceDesignDraft()

    /// Reference-clip clone draft (Voice Cloning mode).
    var voiceCloningDraft = VoiceCloningDraft()

    /// Pending hand-off from Voices tap → Studio Clone mode. The
    /// existing IOSVoiceCloningView consumes this via a binding.
    var pendingVoiceCloningHandoff: PendingVoiceCloningHandoff?

    // MARK: - Onboarding

    /// True until the user dismisses the first-run flow. Initialized
    /// from the persisted `IOSAppDefaults.hasCompletedOnboarding` flag.
    var isOnboardingPresented: Bool

    // MARK: - Global Player sheet

    /// When set, the root view presents the full-screen Player sheet.
    /// History row taps, Voices preview, and Studio inline-player
    /// expansion all set this.
    var playerSheetItem: IOSPlayerSheetItem?

    /// Edge-to-edge model-delete confirmation, hosted by `RootView` so it
    /// can fill the screen bottom instead of inheriting system sheet insets.
    var deleteModelSheetItem: IOSDeleteModelSheetPresentation?

    /// Edge-to-edge bottom panel used by Studio and Settings sheets that
    /// need the reference backdrop + liquid-glass bottom surface.
    var bottomPanelItem: IOSBottomPanelPresentation?

    /// Studio Clone → Record reference clip. Hosted by `RootView` at app
    /// chrome level so the recorder does not race the bottom-panel overlay.
    /// Presents `IOSRecordVoiceSheet` (same enroll flow as the Voices tab).
    var isCloneReferenceRecorderPresented = false

    /// Studio Clone → Files. Root ownership prevents the system document picker from racing the
    /// custom reference panel and routes the selected file into permanent voice enrollment.
    var isCloneReferenceImporterPresented = false

    private var cloneReferenceRecordingPresentationTask: Task<Void, Never>?
    private var cloneReferenceImportPresentationTask: Task<Void, Never>?

    // MARK: - Modal backdrop

    /// True while a native bottom sheet wants the app chrome behind it
    /// blurred/dimmed, matching the reference backdrop-filter focus layer.
    var isFocusBackdropPresented: Bool = false

    // MARK: - Studio generation coordinators (Phase 3b — complete as designed)

    /// Per-mode generation lifecycle. Per-mode views read state via
    /// `appModel.coordinator(for: .custom)` instead of holding their
    /// own scattered `@State` for `isGenerating`, `errorMessage`, and
    /// `lastCompletedOutput`. The actual engine call (`ttsEngine.generate`)
    /// deliberately stays in the per-mode views: it assembles
    /// mode-specific payloads from the drafts plus environment-owned
    /// stores (`TTSEngineStore`, `AudioPlayerViewModel`,
    /// `ModelManagerViewModel`, `SavedVoicesViewModel`) that exist only
    /// in the SwiftUI environment. Hoisting it into the coordinators
    /// would mean injecting those app-lifetime objects into `AppModel`
    /// (constructed before the environment exists) for no behavioral
    /// gain; the shared cancel path already lives in
    /// `IOSStudioGenerationActions`.
    let customCoordinator = StudioGenerationCoordinator(mode: .custom)
    let designCoordinator = StudioGenerationCoordinator(mode: .design)
    let cloneCoordinator = StudioGenerationCoordinator(mode: .clone)

    /// One app-wide long-form project coordinator (the engine admits one
    /// generation at a time); scripts above the single-take limit route here.
    let longForm = IOSLongFormCoordinator()

    func coordinator(for mode: GenerationMode) -> StudioGenerationCoordinator {
        switch mode {
        case .custom: return customCoordinator
        case .design: return designCoordinator
        case .clone: return cloneCoordinator
        }
    }

    func presentDeleteModelSheet(_ item: IOSDeleteModelSheetPresentation) {
        isFocusBackdropPresented = true
        deleteModelSheetItem = item
    }

    func dismissDeleteModelSheet() {
        deleteModelSheetItem = nil
        isFocusBackdropPresented = false
    }

    func presentBottomPanel(
        id: String = UUID().uuidString,
        content: @escaping @MainActor (_ bottomSafeAreaInset: CGFloat, _ availableHeight: CGFloat, _ dismiss: @escaping @MainActor () -> Void) -> AnyView
    ) {
        isFocusBackdropPresented = true
        bottomPanelItem = IOSBottomPanelPresentation(id: id, content: content)
    }

    func dismissBottomPanel() {
        bottomPanelItem = nil
        isFocusBackdropPresented = false
    }

    /// Dismiss the reference picker, then present the recorder from `RootView`
    /// after the bottom-panel overlay tears down (avoids nested presentation races).
    func requestCloneReferenceRecording(afterDismiss dismiss: @escaping @MainActor () -> Void) {
        cloneReferenceRecordingPresentationTask?.cancel()
        dismiss()
        cloneReferenceRecordingPresentationTask = Task { @MainActor in
            try? await Task.sleep(for: .milliseconds(150))
            guard !Task.isCancelled else { return }
            isCloneReferenceRecorderPresented = true
        }
    }

    func cancelCloneReferenceRecording() {
        cloneReferenceRecordingPresentationTask?.cancel()
        isCloneReferenceRecorderPresented = false
    }

    /// Dismiss the reference picker, then present Files after the bottom-panel overlay tears down.
    func requestCloneReferenceImport(afterDismiss dismiss: @escaping @MainActor () -> Void) {
        cloneReferenceImportPresentationTask?.cancel()
        dismiss()
        cloneReferenceImportPresentationTask = Task { @MainActor in
            try? await Task.sleep(for: .milliseconds(150))
            guard !Task.isCancelled else { return }
            isCloneReferenceImporterPresented = true
        }
    }

    func cancelCloneReferenceImport() {
        cloneReferenceImportPresentationTask?.cancel()
        isCloneReferenceImporterPresented = false
    }

    // MARK: - Init

    init(modelRegistry: ContractBackedModelRegistry) {
        self.customVoiceDraft = CustomVoiceDraft(selectedSpeaker: modelRegistry.defaultSpeaker.id)
        self.isOnboardingPresented = !IOSAppDefaults.hasCompletedOnboarding

        // State restoration: return to the last tab (Studio mode always cold-starts on Custom).
        if let raw = IOSAppDefaults.lastTabRawValue, let restored = IOSAppTab(rawValue: raw) {
            self.tab = restored
        }
    }
}

// Injection: `RootView(ttsEngine:).environment(appModel)` inside
// `QVoiceiOSRootView`. Consumers read with `@Environment(AppModel.self)
// private var appModel` — no key-path environment value needed.
