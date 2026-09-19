import SwiftUI
import QwenVoiceCore

struct IOSGenerateContainerView: View {
    @Environment(AppModel.self) private var appModel
    @Environment(\.dynamicTypeSize) private var dynamicTypeSize
    @EnvironmentObject private var audioPlayer: AudioPlayerViewModel
    @EnvironmentObject private var ttsEngine: TTSEngineStore
    @EnvironmentObject private var modelManager: ModelManagerViewModel
    private var selectorRailHeight: CGFloat {
        dynamicTypeSize.isAccessibilitySize ? 136 : 44
    }

    @Binding var selectedTab: IOSAppTab
    @Environment(\.iosTabIsActive) private var isTabActive
    @Binding var selectedSection: IOSGenerationSection
    @Binding var customVoiceDraft: CustomVoiceDraft
    @Binding var voiceDesignDraft: VoiceDesignDraft
    @Binding var voiceCloningDraft: VoiceCloningDraft
    @Binding var pendingVoiceCloningHandoff: PendingVoiceCloningHandoff?

    private var hasAnyInstalledModel: Bool {
        modelManager.statuses.values.contains { status in
            if case .installed = status { return true }
            if case .updateAvailable = status { return true }
            return false
        }
    }

    var body: some View {
        IOSStudioShellScreen(
            selectedTab: $selectedTab,
            activeTab: .studio,
            tint: selectedSection.primaryActionTint
        ) {
            // Studio's CTA / generating waveform / inline player live INSIDE
            // each per-mode view via IOSStudioCanvas, per
            // design_references/Vocello iOS/studio.jsx (vc-dock-area).
            //
            // R2 (2026-05-21): the body was previously wrapped in a
            // ScrollView, which sized content to its natural height and
            // killed the canvas's Spacer-based layout (composer
            // sticking to top, chips + dock pinned to bottom). Per the
            // design Studio doesn't scroll — composer fills, chips and
            // dock sit against the safe-area bottom inset above the
            // tab dock. Plain VStack reinstates that flow.
            VStack(alignment: .leading, spacing: 0) {
                IOSGenerationModeSelector(selectedSection: $selectedSection)
                    .frame(height: selectorRailHeight)
                    .padding(.horizontal, 16)
                    .padding(.top, 6)
                    .padding(.bottom, 10)

                IOSGenerateModeViewport(selection: selectedSection) {
                    IOSCustomVoiceView(
                        isActive: selectedSection == .custom,
                        selectedTab: $selectedTab,
                        draft: $customVoiceDraft
                    )
                } design: {
                    IOSVoiceDesignView(
                        isActive: selectedSection == .design,
                        selectedTab: $selectedTab,
                        draft: $voiceDesignDraft
                    )
                } clone: {
                    IOSVoiceCloningView(
                        isActive: selectedSection == .clone,
                        selectedTab: $selectedTab,
                        draft: $voiceCloningDraft,
                        pendingSavedVoiceHandoff: $pendingVoiceCloningHandoff
                    )
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        }
        .task(id: isTabActive) {
            // Model availability refresh, re-homed from the deleted prefetch
            // coordinator (IUI-4 P8): the proactive-prefetch policy has been
            // hard-disabled since it shipped, but its coordinator kept ten
            // onChange handlers and two whole-store subscriptions wired, so
            // every composer keystroke and every engine progress publish
            // re-ran dead diffing. Keyed on the tab-active flag (IUI-5 P4):
            // the stable-identity container no longer remounts this screen per
            // visit, so re-fire the refresh on each return to the tab instead.
            guard isTabActive else { return }
            await modelManager.refresh()
        }
    }
}

struct IOSGenerationModeSelector: View {
    @Binding var selectedSection: IOSGenerationSection
    @EnvironmentObject private var ttsEngine: TTSEngineStore

    var body: some View {
        IOSCapsuleSelector(
            items: IOSGenerationSection.allCases,
            selection: $selectedSection,
            title: \.compactTitle,
            selectedTint: \.primaryActionTint,
            isSelectionDisabled: ttsEngine.hasActiveGeneration,
            controlAccessibilityIdentifier: "generateSectionPicker",
            itemAccessibilityIdentifier: { "generateSection_\($0.rawValue)" }
        )
    }
}

/// Platform adapter: the selector body is shared; iOS owns Dynamic Type, motion and haptics.
struct IOSCapsuleSelector<Item: Identifiable & Hashable>: View {
    @Environment(\.dynamicTypeSize) private var dynamicTypeSize
    @Environment(\.iosReduceMotionEnabled) private var reduceMotion
    let items: [Item]
    @Binding var selection: Item
    let title: KeyPath<Item, String>
    let selectedTint: (Item) -> Color
    var isSelectionDisabled = false
    let controlAccessibilityIdentifier: String
    let itemAccessibilityIdentifier: (Item) -> String

    var body: some View {
        VocelloCapsuleSelector(
            items: items,
            selection: $selection,
            title: title,
            selectedTint: selectedTint,
            isSelectionDisabled: isSelectionDisabled,
            controlAccessibilityIdentifier: controlAccessibilityIdentifier,
            itemAccessibilityIdentifier: itemAccessibilityIdentifier,
            stacksVertically: dynamicTypeSize.isAccessibilitySize,
            reduceMotion: reduceMotion
        )
        .sensoryFeedback(.selection, trigger: selection)
    }
}

extension IOSGenerationSection {
    var primaryActionSystemImage: String {
        switch self {
        case .custom:
            return "waveform.and.mic"
        case .design:
            return "paintbrush.pointed"
        case .clone:
            return "waveform.path.ecg"
        }
    }

    var primaryActionTint: Color {
        Theme.Brand.modeColor(mode)
    }
}
