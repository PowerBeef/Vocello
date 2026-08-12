import SwiftUI
import QwenVoiceCore

struct IOSGenerateContainerView: View {
    @Environment(AppModel.self) private var appModel
    @EnvironmentObject private var audioPlayer: AudioPlayerViewModel
    @EnvironmentObject private var ttsEngine: TTSEngineStore
    @EnvironmentObject private var modelManager: ModelManagerViewModel
    private let selectorRailHeight: CGFloat = 44

    @Binding var selectedTab: IOSAppTab
    let isTabActive: Bool
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
        .task {
            // Model availability refresh, re-homed from the deleted prefetch
            // coordinator (IUI-4 P8): the proactive-prefetch policy has been
            // hard-disabled since it shipped, but its coordinator kept ten
            // onChange handlers and two whole-store subscriptions wired, so
            // every composer keystroke and every engine progress publish
            // re-ran dead diffing.
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

/// Shared 3-way capsule selector used by `IOSGenerationModeSelector`
/// (Studio mode) and previously by Library / History filter rows.
///
/// R3 (2026-05-21): matches `design_references/Vocello iOS/app.css`
/// `.vc-mode-segmented` plus `chrome.jsx`'s active-mode inline style:
///
///   rail:  rgba(255,255,255,0.04) fill + 0.5pt rgba(255,255,255,0.08)
///          stroke. Neutral, not mode-tinted.
///   pill:  active tint @ 22 % fill + active tint @ 36 % stroke,
///          white inset top highlight, and 1pt black drop shadow.
struct IOSCapsuleSelector<Item: Identifiable & Hashable>: View {
    let items: [Item]
    @Binding var selection: Item
    let title: KeyPath<Item, String>
    let selectedTint: (Item) -> Color
    var isSelectionDisabled = false
    let controlAccessibilityIdentifier: String
    let itemAccessibilityIdentifier: (Item) -> String
    @Namespace private var selectionPillNamespace

    var body: some View {
        HStack(spacing: 4) {
            ForEach(items) { item in
                Button {
                    guard !isSelectionDisabled else { return }
                    guard item != selection else { return }
                    selection = item
                } label: {
                    Text(item[keyPath: title])
                        .font(.system(size: 15, weight: .semibold))
                        .lineLimit(1)
                        .minimumScaleFactor(0.85)
                        .foregroundStyle(
                            item == selection
                                ? IOSAppTheme.textPrimary
                                : IOSAppTheme.textSecondary
                        )
                        .frame(minHeight: 36)
                        .padding(.horizontal, 20)
                        .background {
                            if item == selection {
                                IOSCapsuleSelectorPill(tint: selectedTint(item))
                                    .matchedGeometryEffect(id: "selectionPill", in: selectionPillNamespace)
                            }
                        }
                }
                .buttonStyle(.plain)
                .disabled(isSelectionDisabled && item != selection)
                .opacity(isSelectionDisabled && item != selection ? 0.42 : 1)
                .iosAppAnimation(IOSSelectionMotion.selectorLabel, value: selection)
                .accessibilityIdentifier(itemAccessibilityIdentifier(item))
                .accessibilityAddTraits(item == selection ? .isSelected : [])
            }
        }
        .iosAppAnimation(IOSDesignMotion.modePillSlide, value: selection)
        .padding(4)
        .background {
            Capsule(style: .continuous)
                .fill(Color.white.opacity(0.04))
        }
        .overlay {
            Capsule(style: .continuous)
                .stroke(Color.white.opacity(0.08), lineWidth: 0.5)
        }
        .frame(height: 44)
        .fixedSize(horizontal: true, vertical: false)
        .frame(maxWidth: .infinity, alignment: .center)
        .sensoryFeedback(.selection, trigger: selection)
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier(controlAccessibilityIdentifier)
    }
}

/// The moving capsule pill behind the selected segment.
/// Tinted per `chrome.jsx`'s `color-mix(in oklch, activeColor 22%)`
/// override on `.vc-mode-pill`.
private struct IOSCapsuleSelectorPill: View {
    let tint: Color

    var body: some View {
        let shape = Capsule(style: .continuous)
        shape
            .fill(tint.opacity(0.22))
            .overlay {
                shape.stroke(tint.opacity(0.36), lineWidth: 0.5)
            }
            .overlay(alignment: .top) {
                // inset 0 1px 0 rgba(255,255,255,0.10) — top-edge highlight
                shape
                    .stroke(Color.white.opacity(0.10), lineWidth: 0.5)
                    .mask(
                        LinearGradient(
                            colors: [.white, .clear],
                            startPoint: .top,
                            endPoint: .center
                        )
                    )
            }
            .shadow(color: .black.opacity(0.15), radius: 1, x: 0, y: 1)
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
        IOSBrandTheme.modeColor(for: mode)
    }
}
