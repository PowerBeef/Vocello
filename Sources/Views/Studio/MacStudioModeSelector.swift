import SwiftUI

/// The iOS selector, with desktop labels and the existing mode-control IDs.
struct MacStudioModeSelector: View {
    @Binding var selection: SidebarItem?
    @EnvironmentObject private var engine: TTSEngineStore
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    private var modeSelection: Binding<SidebarItem> {
        Binding(
            get: { selection ?? .customVoice },
            set: { selection = $0 }
        )
    }

    var body: some View {
        VocelloCapsuleSelector(
            items: SidebarItem.generationItems,
            selection: modeSelection,
            title: \.studioTitle,
            selectedTint: { MacTheme.tint(for: $0) },
            isSelectionDisabled: engine.hasActiveGeneration,
            controlAccessibilityIdentifier: "studio_modePicker",
            itemAccessibilityIdentifier: \.accessibilityID,
            fillsSegmentWidth: true,
            labelFont: MacType.font(.chipLabel),
            reduceMotion: reduceMotion || !AppLaunchConfiguration.current.animationsEnabled
        )
    }
}
