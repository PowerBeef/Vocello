import SwiftUI
import QwenVoiceNative

private struct NavigationSectionHeader: View {
    let title: String
    let accessibilityID: String

    var body: some View {
        Text(title)
            .font(.caption.weight(.semibold))
            .foregroundStyle(.secondary)
            .textCase(nil)
            .frame(maxWidth: .infinity, alignment: .leading)
            .accessibilityElement(children: .combine)
            .accessibilityLabel(title)
            .accessibilityIdentifier(accessibilityID)
    }
}

/// Compact Vocello brand lockup pinned to the top of the sidebar via
/// `safeAreaInset(edge: .top)`. Stays out of the List's scroll region so
/// the brand anchor remains visible as the user scrolls through sections.
///
/// Three-tier typography:
///   • V glyph (22pt image)            — the colored brand anchor.
///   • "AI·TTS" preamble (caption,
///      medium, secondary)             — quiet category qualifier; SF Pro
///                                        default for a slightly technical
///                                        feel that contrasts the wordmark's
///                                        rounded warmth.
///   • "Vocello" wordmark (18pt SF
///      Rounded semibold, primary)     — the spoken-aloud name.
///
/// Intentionally NOT a stylized display face: PRODUCT.md asks the brand
/// to defer to the output, so the lockup sits in the same visual tier
/// as the section headers instead of competing with them.
private struct SidebarBrandHeader: View {
    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: 8) {
            Image("VocelloHeaderMark")
                .resizable()
                .scaledToFit()
                .frame(height: 22)
                .alignmentGuide(.firstTextBaseline) { dimension in
                    dimension[.bottom] - 2
                }

            Text("Vocello")
                .font(.system(size: 18, weight: .semibold, design: .rounded))
                .foregroundStyle(.primary)

            Text("AI·TTS")
                .font(.caption.weight(.medium))
                .foregroundStyle(.secondary)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.horizontal, 14)
        // Audit Batch 7b: symmetric top/bottom padding so the brand
        // lockup sits centered in its slot. Previous (.top 14, .bottom 8)
        // looked off-balance at small window heights.
        .padding(.top, 14)
        .padding(.bottom, 14)
        .accessibilityElement(children: .combine)
        .accessibilityLabel("Vocello, AI text to speech")
    }
}

private struct SidebarRow: View {
    @Environment(\.generationPerformanceGate) private var performanceGate
    @Environment(\.accessibilityReduceTransparency) private var reduceTransparency
    let item: SidebarItem
    @Binding var selection: SidebarItem?
    let isDisabled: Bool
    @State private var isHovered = false

    // W1-E: the sidebar's 17/14 pt fonts and 22 pt icon slot were fixed
    // and ignored the system text-size setting.
    @ScaledMetric(relativeTo: .body) private var iconSize: CGFloat = 17
    @ScaledMetric(relativeTo: .body) private var labelSize: CGFloat = 14
    @ScaledMetric(relativeTo: .body) private var iconSlotWidth: CGFloat = 22

    private var isSelected: Bool {
        selection == item
    }

    @ViewBuilder
    private var rowBackground: some View {
        #if QW_UI_LIQUID
        if #available(macOS 26, *), !reduceTransparency, !performanceGate {
            if isSelected {
                RoundedRectangle(cornerRadius: 8, style: .continuous)
                    .fill(AppTheme.sidebarSelectionFill)
                    .overlay(
                        RoundedRectangle(cornerRadius: 8, style: .continuous)
                            .strokeBorder(
                                // Per-mode selection edge — golden for
                                // Custom Voice / Library, lavender for
                                // Voice Design, terracotta for Voice
                                // Cloning. Matches the non-liquid
                                // fallback in `borderColor`.
                                AppTheme.sidebarColor(for: item).opacity(0.55),
                                lineWidth: AppTheme.surfaceStrokeWidth
                            )
                    )
                    .glassEffect(.regular.tint(AppTheme.smokedGlassTint).interactive(), in: .rect(cornerRadius: 8))
                    .glass3DDepth(radius: 8, intensity: 0.5)
            } else if isHovered {
                RoundedRectangle(cornerRadius: 8, style: .continuous)
                    .fill(AppTheme.sidebarHoverFill)
                    .overlay(
                        RoundedRectangle(cornerRadius: 8, style: .continuous)
                            .strokeBorder(
                                AppTheme.sidebarHoverStroke,
                                lineWidth: AppTheme.surfaceStrokeWidth
                            )
                    )
                    .glassEffect(.regular.tint(AppTheme.smokedGlassTint).interactive(), in: .rect(cornerRadius: 8))
                    .glass3DDepth(radius: 8, intensity: 0.25)
            } else {
                Color.clear
            }
        } else {
            legacyRowBackground
        }
        #else
        legacyRowBackground
        #endif
    }

    private var legacyRowBackground: some View {
        RoundedRectangle(cornerRadius: 8, style: .continuous)
            .fill(backgroundColor)
            .overlay {
                RoundedRectangle(cornerRadius: 8, style: .continuous)
                    .strokeBorder(borderColor, lineWidth: isSelected || isHovered ? 1 : 0)
            }
    }

    private var backgroundColor: Color {
        if isDisabled {
            return isSelected ? Color.secondary.opacity(0.06) : .clear
        }

        if isSelected {
            return AppTheme.sidebarSelectionFill
        }

        if isHovered {
            return AppTheme.sidebarHoverFill
        }

        return .clear
    }

    private var borderColor: Color {
        if isDisabled {
            return isSelected ? Color.secondary.opacity(0.16) : .clear
        }

        if isSelected {
            // Per-mode edge accent — the stroke picks up the item's
            // Vocello palette color so selecting Voice Design shows a
            // lavender edge, Voice Cloning terracotta, etc. Library
            // and Settings rows still resolve to accent (golden) via
            // AppTheme.sidebarColor(for:).
            return AppTheme.sidebarColor(for: item).opacity(0.32)
        }

        if isHovered {
            return AppTheme.sidebarHoverStroke
        }

        return .clear
    }

    private var iconColor: Color {
        if isDisabled {
            return Color.secondary.opacity(isSelected ? 0.8 : 0.65)
        }

        return isSelected ? AppTheme.sidebarColor(for: item) : Color.primary
    }

    private var textColor: Color {
        if isDisabled {
            return Color.secondary.opacity(isSelected ? 0.88 : 0.72)
        }

        return Color.primary
    }

    private var selectionIndicatorColor: Color {
        if !isSelected {
            return .clear
        }

        return isDisabled ? Color.secondary.opacity(0.6) : AppTheme.sidebarColor(for: item)
    }

    private var accessibilityStateValue: String {
        var states: [String] = []

        if isSelected {
            states.append("selected")
        } else {
            states.append("not selected")
        }

        if isDisabled {
            states.append("disabled")
        }

        return states.joined(separator: ", ")
    }

    var body: some View {
        // Wrap the row content in a Button so VoiceOver announces the row
        // as a button (not just static text), keyboard activation (Space /
        // Return) works, and AppKit's focus ring lands correctly. The
        // visual modifiers (background, animation, hover) stay on the
        // button's label so the look is unchanged. `.disabled(isDisabled)`
        // gates both activation and accessibility traits via Button's
        // built-in handling, which is stronger than the prior gesture
        // gate.
        Button {
            selection = item
        } label: {
            HStack(spacing: 8) {
                Capsule()
                    .fill(selectionIndicatorColor)
                    .frame(width: 3, height: 16)

                Image(systemName: item.iconName)
                    .font(.system(size: iconSize, weight: isSelected ? .semibold : .regular))
                    .foregroundStyle(iconColor)
                    .frame(width: iconSlotWidth, alignment: .center)

                Text(item.rawValue)
                    .font(.system(size: labelSize, weight: isSelected ? .semibold : .regular))
                    .foregroundStyle(textColor)
                    .lineLimit(1)

                Spacer(minLength: 0)
            }
                .padding(.horizontal, 8)
                .padding(.vertical, 6)
                .frame(maxWidth: .infinity, alignment: .leading)
                .frame(height: 34)
                .background(rowBackground)
                .contentShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
        }
            .buttonStyle(.plain)
            .onHover { hovering in
                isHovered = isDisabled ? false : hovering
            }
            .onChange(of: isDisabled) { _, disabled in
                if disabled {
                    isHovered = false
                }
            }
            .appAnimation(AppTheme.Motion.state, value: isHovered)
            .appAnimation(AppTheme.Motion.state, value: isSelected)
            .disabled(isDisabled)
            .accessibilityLabel(item.rawValue)
            .accessibilityValue(accessibilityStateValue)
            .accessibilityIdentifier(item.accessibilityID)
    }
}

struct SidebarView: View {
    @Binding var selection: SidebarItem?
    let disabledItems: Set<SidebarItem>

    private var usesNativeListSelection: Bool {
        guard let selection else { return true }
        return !disabledItems.contains(selection)
    }

    var body: some View {
        Group {
            if usesNativeListSelection {
                List(selection: $selection) {
                    sidebarListContent
                }
            } else {
                List {
                    sidebarListContent
                }
            }
        }
        .listStyle(.sidebar)
        .scrollContentBackground(.hidden)
        .background(AppTheme.railBackground)
        .safeAreaInset(edge: .top, spacing: 0) {
            SidebarBrandHeader()
        }
        .safeAreaInset(edge: .bottom) {
            SidebarFooterRegion()
        }
    }

    @ViewBuilder
    private var sidebarListContent: some View {
        ForEach(SidebarItem.Section.allCases, id: \.self) { section in
            Section {
                ForEach(section.items) { item in
                    SidebarRow(
                        item: item,
                        selection: $selection,
                        isDisabled: disabledItems.contains(item)
                    )
                        .tag(item as SidebarItem?)
                        .listRowInsets(EdgeInsets(top: 2, leading: 8, bottom: 2, trailing: 8))
                        .listRowBackground(Color.clear)
                }
            } header: {
                NavigationSectionHeader(
                    title: section.rawValue,
                    accessibilityID: section.accessibilityID
                )
            }
        }
    }
}

private struct SidebarFooterRegion: View {
    @EnvironmentObject private var audioPlayer: AudioPlayerViewModel
    @EnvironmentObject private var ttsEngineStore: TTSEngineStore

    private let appEngineSelection = AppEngineSelection.current()

    private var resolvedSidebarStatus: SidebarStatus {
        appEngineSelection.resolveSidebarStatus(
            ttsEngineSnapshot: ttsEngineStore.snapshot,
            prefersInlinePresentation: audioPlayer.isLiveStream
        )
    }

    private var footerPresentation: SidebarFooterPresentation {
        SidebarFooterPresentation.resolve(
            sidebarStatus: resolvedSidebarStatus,
            isLiveStream: audioPlayer.isLiveStream
        )
    }

    var body: some View {
        VStack(spacing: 0) {
            Rectangle()
                .fill(AppTheme.railStroke.opacity(0.9))
                .frame(height: 1)

            VStack(alignment: .leading, spacing: 10) {
                if audioPlayer.hasAudio {
                    SidebarPlayerView(inlinePlayerActivity: footerPresentation.inlinePlayerActivity)

                    if footerPresentation.showsStandaloneStatus {
                        Rectangle()
                            .fill(AppTheme.railStroke.opacity(0.65))
                            .frame(height: 1)
                    }
                }

                if footerPresentation.showsStandaloneStatus {
                    SidebarStatusView(
                        sidebarStatus: resolvedSidebarStatus,
                        clearError: {
                            appEngineSelection.clearSidebarError(
                                ttsEngineStore: ttsEngineStore
                            )
                        }
                    )
                }
            }
            .padding(.horizontal, LayoutConstants.shellPadding)
            .padding(.top, LayoutConstants.generationSectionSpacing)
            .padding(.bottom, LayoutConstants.shellPadding)
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .background(AppTheme.railBackground)
    }
}
