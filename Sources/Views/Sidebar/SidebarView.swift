import QwenVoiceCore
import SwiftUI

/// The phone's four destinations, presented as a desktop sidebar. Studio modes
/// live in the shared capsule selector in the detail column.
struct SidebarView: View {
    @Binding var selection: SidebarItem?
    @Environment(MacAppModel.self) private var appModel

    private var destination: Binding<SidebarItem?> {
        Binding(
            get: { selection?.generationMode != nil ? .customVoice : selection },
            set: { selection = $0 == .customVoice ? appModel.lastStudioItem : $0 }
        )
    }

    var body: some View {
        List(selection: destination) {
            ForEach([SidebarItem.customVoice, .voices, .history, .settings]) { item in
                MacSidebarRow(item: item, selection: destination)
                    .tag(item as SidebarItem?)
                    .listRowInsets(
                        EdgeInsets(top: 2, leading: MacShellMetrics.sidebarInset, bottom: 2, trailing: MacShellMetrics.sidebarInset)
                    )
                    .listRowSeparator(.hidden)
                    .listRowBackground(Color.clear)
            }
        }
        .listStyle(.sidebar)
        .scrollContentBackground(.hidden)
        .safeAreaInset(edge: .top, spacing: 0) {
            MacSidebarBrandHeader()
        }
        .safeAreaInset(edge: .bottom, spacing: 0) {
            MacPlaybackFooter(isSidebar: true)
        }
        // The column's own material would sit over any window background, so
        // the sidebar paints its slice of the window-wide mode wash.
        //
        // After the insets, not before them. Attached to the List it was
        // painted behind the List alone, and the brand header and the footer
        // are safe-area insets that sit outside it — so the slice began below
        // the lockup while the detail column's began at the window's top edge.
        // Two halves of one gradient, one of them starting sixty points lower:
        // the seam that made the panels look like different surfaces.
        .background {
            MacModeBackdrop(tint: MacTheme.tint(for: selection ?? .customVoice), column: .sidebar)
                .ignoresSafeArea()
                .appAnimation(MacTheme.Motion.modeCrossfade, value: selection)
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

// MARK: - Row

private struct MacSidebarRow: View {
    @Environment(MacAppModel.self) private var appModel
    let item: SidebarItem
    @Binding var selection: SidebarItem?
    @State private var isHovered = false

    /// The chip's glyph size, not the icon step's. A sidebar row and a Studio
    /// chip are the same 40 pt control with the same 13 pt label, so their
    /// glyphs are the same too.
    @ScaledMetric(relativeTo: .body) private var glyphSize: CGFloat = MacControl.pill.glyph
    @ScaledMetric(relativeTo: .body) private var glyphColumnWidth: CGFloat = MacShellMetrics.sidebarGlyphColumn

    private var isSelected: Bool { selection == item }
    private var title: String {
        switch item {
        case .customVoice: MacInterfaceText.shellSectionStudio
        case .voices: MacInterfaceText.tabVoices
        default: item.title
        }
    }
    private var symbol: String { item == .customVoice ? "waveform" : item.iconName }
    private var identifier: String { item == .customVoice ? "sidebar_studio" : item.accessibilityID }
    private var tint: Color {
        MacTheme.tint(for: item == .customVoice ? appModel.lastStudioItem : item)
    }

    var body: some View {
        // A Button so VoiceOver announces the row as a button, keyboard
        // activation works without a second, invisible navigation control.
        Button {
            selection = item
        } label: {
            HStack(spacing: MacTheme.Spacing.snug) {
                glyphColumn

                VStack(alignment: .leading, spacing: MacTheme.Spacing.xs) {
                    Text(title)
                        // The same step and weight as a Studio chip's label,
                        // which is the point: these rows and those chips are
                        // the two halves of the window and they are now the
                        // same control drawn at the same size. 15 pt was tried
                        // and was too much -- the panel stopped reading as
                        // navigation and started competing with the canvas.
                        //
                        // It used to set its own font so selection could carry
                        // a weight change. Selection already changes the row's
                        // pill and the glyph's colour; weight was a third
                        // signal doing the least work, and paying for it meant
                        // every unselected row sat a step lighter than
                        // everything else on screen.
                        .macType(.rowTitle)
                        .foregroundStyle(MacTheme.Text.primary)
                        .lineLimit(1)
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
        .onHover { isHovered = $0 }
        .appAnimation(MacTheme.Motion.stateChange, value: isHovered)
        .appAnimation(MacTheme.Motion.stateChange, value: isSelected)
        .accessibilityLabel(title)
        // The trait, not a string. VoiceOver synthesises "selected" in the
        // user's own language from this; the words it replaces were English
        // on an app that ships in French, and "disabled" was a second copy of
        // what `.disabled` already tells the accessibility layer.
        .accessibilityAddTraits(isSelected ? [.isSelected] : [])
        .accessibilityIdentifier(identifier)
    }

    /// The glyph, at the size and strength a Studio chip's glyph has, in a
    /// fixed column so the icons line up down the panel.
    ///
    /// It used to sit in a filled, stroked tile. That tile was the one thing in
    /// the sidebar with no counterpart anywhere in the Studio -- a container
    /// inside a row, which on a selected row meant a tinted tile inside a
    /// tinted pill, two rounded shapes at two radii saying the same thing. The
    /// frame stays because it is what aligns icons of different intrinsic
    /// widths; only the chrome goes.
    private var glyphColumn: some View {
        Image(systemName: symbol)
            .font(.system(size: glyphSize, weight: .semibold))
            // Full strength when unselected, not secondary: dimmed as well as
            // small left the icons reading as decoration beside a chip whose
            // own glyph is at full strength. The tint still marks the selected
            // one, as it does on the chip.
            .foregroundStyle(isSelected ? tint : MacTheme.Text.primary)
            .frame(width: glyphColumnWidth, height: glyphColumnWidth)
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
