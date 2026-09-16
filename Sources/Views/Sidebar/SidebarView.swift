import QwenVoiceCore
import SwiftUI

/// The macOS sidebar in the iOS visual language (plan
/// `macos-ios-convergence-2026-09`, CONV-11): the brand lockup on top, the
/// Studio and Library sections plus Settings as rows with mode-tinted glyph
/// tiles, the selected row a quiet tint-glass pill (the iOS `TabDock`
/// selection recipe), disabled modes dimmed with the install hint, and the
/// inline player card and engine status strip pinned in the footer. Every
/// `sidebar_*`, `sidebarSection_*` and `sidebarPlayer_*` identifier is the
/// lane contract and stays.
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
        // The column's own material would sit over any window background,
        // so the sidebar paints its slice of the window-wide mode wash.
        .background {
            MacModeBackdrop(tint: MacTheme.tint(for: selection ?? .customVoice), column: .sidebar)
                .ignoresSafeArea()
                .appAnimation(MacTheme.Motion.modeCrossfade, value: selection)
        }
        .safeAreaInset(edge: .top, spacing: 0) {
            MacSidebarBrandHeader()
        }
        .safeAreaInset(edge: .bottom, spacing: 0) {
            SidebarFooterRegion()
        }
    }

    @ViewBuilder
    private var sidebarListContent: some View {
        ForEach(SidebarItem.Section.allCases, id: \.self) { section in
            Section {
                ForEach(section.items) { item in
                    MacSidebarRow(
                        item: item,
                        selection: $selection,
                        isDisabled: disabledItems.contains(item)
                    )
                    .tag(item as SidebarItem?)
                    .listRowInsets(
                        EdgeInsets(top: 2, leading: MacShellMetrics.sidebarInset, bottom: 2, trailing: MacShellMetrics.sidebarInset)
                    )
                    .listRowSeparator(.hidden)
                    .listRowBackground(Color.clear)
                }
            } header: {
                // The Settings section holds exactly the Settings row; a
                // header would restate the row directly beneath it.
                if section != .settings {
                    MacSidebarSectionHeader(
                        title: section.title,
                        accessibilityID: section.accessibilityID
                    )
                }
            }
        }
    }
}

// MARK: - Brand header

private struct MacSidebarBrandHeader: View {
    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: MacTheme.Spacing.sm) {
            VocelloProductTitleLockup(title: MacInterfaceText.brandName)

            Text(MacInterfaceText.brandTagline)
                .macType(.captionEmphasis)
                .foregroundStyle(MacTheme.Text.tertiary)
                .lineLimit(1)

            Spacer(minLength: 0)
        }
        .padding(.horizontal, MacShellMetrics.sidebarInset + MacTheme.Spacing.xs)
        .padding(.vertical, MacTheme.Spacing.lg)
        .accessibilityElement(children: .combine)
        .accessibilityLabel(MacInterfaceText.brandAccessibility)
    }
}

// MARK: - Section header

private struct MacSidebarSectionHeader: View {
    let title: String
    let accessibilityID: String

    var body: some View {
        Text(title.uppercased())
            .macType(.eyebrow)
            .foregroundStyle(MacTheme.Text.secondary)
            .lineLimit(1)
            .textCase(nil)
            .padding(.leading, MacTheme.Spacing.xs)
            .frame(maxWidth: .infinity, alignment: .leading)
            .accessibilityElement(children: .combine)
            .accessibilityLabel(title)
            .accessibilityIdentifier(accessibilityID)
    }
}

// MARK: - Row

private struct MacSidebarRow: View {
    let item: SidebarItem
    @Binding var selection: SidebarItem?
    let isDisabled: Bool
    @State private var isHovered = false

    @ScaledMetric(relativeTo: .body) private var glyphSize: CGFloat = MacControl.icon.glyph
    @ScaledMetric(relativeTo: .body) private var tileSize: CGFloat = MacShellMetrics.sidebarGlyphTile

    private var isSelected: Bool { selection == item }
    private var tint: Color { MacTheme.tint(for: item) }

    private var accessibilityStateValue: String {
        var states = [isSelected ? "selected" : "not selected"]
        if isDisabled {
            states.append("disabled")
        }
        return states.joined(separator: ", ")
    }

    var body: some View {
        // A Button so VoiceOver announces the row as a button, keyboard
        // activation works and `.disabled` gates activation and traits.
        Button {
            selection = item
        } label: {
            HStack(spacing: MacTheme.Spacing.snug) {
                glyphTile

                VStack(alignment: .leading, spacing: MacTheme.Spacing.xs) {
                    Text(item.title)
                        // The role sets the size; selection still sets the weight,
                // which is how a selected destination reads as selected.
                .font(.system(size: MacType.style(.rowTitle).size, weight: isSelected ? .semibold : .medium))
                        .foregroundStyle(MacTheme.Text.primary)
                        .lineLimit(1)

                    if isDisabled {
                        Text(MacInterfaceText.shellModelMissingHint)
                            .macType(.caption)
                            .foregroundStyle(MacTheme.Text.tertiary)
                            .lineLimit(1)
                    }
                }

                Spacer(minLength: 0)
            }
            .padding(.horizontal, MacTheme.Spacing.sm)
            .padding(.vertical, MacTheme.Spacing.tight)
            .frame(maxWidth: .infinity, alignment: .leading)
            .frame(minHeight: MacShellMetrics.sidebarRowMinHeight)
            .background(rowBackground)
            .contentShape(VocelloShape.row())
        }
        .buttonStyle(.plain)
        .opacity(isDisabled ? VocelloTheme.Opacity.disabled : 1)
        .onHover { hovering in
            isHovered = isDisabled ? false : hovering
        }
        .onChange(of: isDisabled) { _, disabled in
            if disabled {
                isHovered = false
            }
        }
        .appAnimation(MacTheme.Motion.stateChange, value: isHovered)
        .appAnimation(MacTheme.Motion.stateChange, value: isSelected)
        .disabled(isDisabled)
        .accessibilityLabel(item.title)
        .accessibilityValue(accessibilityStateValue)
        .accessibilityIdentifier(item.accessibilityID)
    }

    private var glyphTile: some View {
        let shape = VocelloShape.chip()
        return Image(systemName: item.iconName)
            .font(.system(size: glyphSize, weight: .semibold))
            .foregroundStyle(isSelected ? tint : MacTheme.Text.secondary)
            .frame(width: tileSize, height: tileSize)
            .background { shape.fill(isSelected ? tint.opacity(0.16) : Color.white.opacity(0.05)) }
            .overlay {
                shape.stroke(
                    isSelected ? tint.opacity(0.32) : Color.white.opacity(0.06),
                    lineWidth: VocelloTheme.Stroke.hairline
                )
            }
            .accessibilityHidden(true)
    }

    @ViewBuilder
    private var rowBackground: some View {
        let shape = VocelloShape.row()
        if isSelected {
            MacSidebarSelectionPill(tint: tint, shape: shape)
        } else if isHovered {
            shape.fill(Color.white.opacity(0.04))
        } else {
            Color.clear
        }
    }
}

/// The iOS `TabDockSelectionBackground` recipe: a 12% tint over a faint white
/// film, a 38% tint hairline, an inset top highlight, through the glass gate.
private struct MacSidebarSelectionPill: View {
    let tint: Color
    let shape: RoundedRectangle

    var body: some View {
        shape
            .fill(Color.white.opacity(0.02))
            .overlay { shape.fill(tint.opacity(0.12)) }
            .overlay { shape.stroke(tint.opacity(0.38), lineWidth: VocelloTheme.Stroke.hairline) }
            .overlay {
                shape
                    .stroke(Color.white.opacity(0.08), lineWidth: VocelloTheme.Stroke.hairline)
                    .mask(
                        LinearGradient(colors: [.white, .clear], startPoint: .top, endPoint: .center)
                    )
            }
            .macGatedGlass(tint: MacTheme.glassTint(tint, intensity: 0.9), in: shape, interactive: true)
    }
}

// MARK: - Footer

private struct SidebarFooterRegion: View {
    @EnvironmentObject private var audioPlayer: AudioPlayerViewModel
    @EnvironmentObject private var ttsEngineStore: TTSEngineStore

    private var status: MacShellStatus {
        MacShellStatusPresentation.resolve(
            snapshot: ttsEngineStore.snapshot,
            prefersInlinePresentation: audioPlayer.isLiveStream
        )
    }

    private var footerPresentation: MacShellFooterPresentation {
        MacShellFooterPresentation.resolve(
            status: status,
            isLiveStream: audioPlayer.isLiveStream
        )
    }

    var body: some View {
        VStack(alignment: .leading, spacing: MacTheme.Spacing.snug) {
            if audioPlayer.hasAudio {
                MacInlinePlayerCard(inlinePlayerActivity: footerPresentation.inlinePlayerActivity)
            }

            if footerPresentation.showsStandaloneStatus {
                MacStatusStrip(
                    status: status,
                    clearError: { ttsEngineStore.clearVisibleError() }
                )
            }
        }
        .padding(.horizontal, MacShellMetrics.sidebarInset)
        .padding(.top, MacTheme.Spacing.sm)
        .padding(.bottom, MacShellMetrics.sidebarInset)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(
            LinearGradient(
                colors: [MacTheme.Surface.canvasBottom.opacity(0), MacTheme.Surface.canvasBottom.opacity(0.9)],
                startPoint: .top,
                endPoint: .bottom
            )
            .ignoresSafeArea()
        )
    }
}
