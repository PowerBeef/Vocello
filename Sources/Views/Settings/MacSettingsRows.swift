import SwiftUI

/// The iOS Settings row language (`IOSSettingsViews`) on the desktop: flat
/// grouped sections on the canvas, a 28-point tinted glyph slot, a semibold
/// title over a footnote, native switches and menus on the trailing edge,
/// and capsule action buttons. No glass: Settings is a quiet surface.
struct MacSettingsSection<Content: View>: View {
    let title: String?
    let accent: Color?
    let content: Content

    init(title: String? = nil, accent: Color? = nil, @ViewBuilder content: () -> Content) {
        self.title = title
        self.accent = accent
        self.content = content()
    }

    var body: some View {
        let shape = VocelloShape.card()
        VStack(alignment: .leading, spacing: 0) {
            if let title {
                Text(title)
                    .textCase(.uppercase)
                    .macType(.eyebrow)
                    .foregroundStyle(MacTheme.Text.secondary)
                    .lineLimit(1)
                    .accessibilityAddTraits(.isHeader)
                    .padding(.horizontal, MacTheme.Spacing.xs)
                    .padding(.bottom, MacTheme.Spacing.tight)
            }

            VStack(alignment: .leading, spacing: 0) {
                content
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(accent?.opacity(0.07) ?? Color.white.opacity(0.04))
            .clipShape(shape)
            .overlay { shape.strokeBorder(accent?.opacity(0.25) ?? MacTheme.Surface.panelStroke, lineWidth: VocelloTheme.Stroke.hairline) }
        }
    }
}

struct MacSettingsDivider: View {
    var body: some View {
        Rectangle()
            .fill(MacTheme.Surface.hairline)
            .frame(height: VocelloTheme.Stroke.hairline)
            // Starts where the title does: row inset, glyph slot, glyph gap.
            .padding(.leading, MacTheme.Spacing.md + MacControl.icon.height + MacTheme.Spacing.snug)
    }
}

struct MacSettingsIcon: View {
    let symbol: String
    var tint: Color = MacTheme.Brand.silver

    var body: some View {
        Image(systemName: symbol)
            .font(.system(size: MacControl.field.glyph, weight: .medium))
            .foregroundStyle(tint)
            .macControlSquare(.icon)
            .accessibilityHidden(true)
    }
}

/// One row: glyph, title and detail on the leading side, controls trailing.
struct MacSettingsRow<Detail: View, Trailing: View>: View {
    let symbol: String
    let title: String
    let tint: Color
    let detail: Detail
    let trailing: Trailing

    init(
        symbol: String,
        title: String,
        tint: Color = MacTheme.Brand.silver,
        @ViewBuilder detail: () -> Detail,
        @ViewBuilder trailing: () -> Trailing
    ) {
        self.symbol = symbol
        self.title = title
        self.tint = tint
        self.detail = detail()
        self.trailing = trailing()
    }

    var body: some View {
        HStack(alignment: .center, spacing: MacTheme.Spacing.md) {
            HStack(alignment: .top, spacing: MacTheme.Spacing.snug) {
                MacSettingsIcon(symbol: symbol, tint: tint)

                VStack(alignment: .leading, spacing: MacTheme.Spacing.xs) {
                    Text(title)
                        .macType(.rowTitle)
                        .foregroundStyle(MacTheme.Text.primary)
                        .fixedSize(horizontal: false, vertical: true)
                    detail
                }
                .frame(maxWidth: .infinity, alignment: .leading)
            }
            .frame(maxWidth: .infinity, alignment: .leading)

            HStack(spacing: MacTheme.Spacing.sm) {
                trailing
            }
            .fixedSize(horizontal: true, vertical: false)
        }
        .padding(.horizontal, MacTheme.Spacing.md)
        .padding(.vertical, MacTheme.Spacing.snug)
        .frame(minHeight: 52)
    }
}

/// Footnote line under a row title (the iOS subtitle).
struct MacSettingsDetailText: View {
    let text: String
    var color: Color = MacTheme.Text.secondary

    init(_ text: String, color: Color = MacTheme.Text.secondary) {
        self.text = text
        self.color = color
    }

    var body: some View {
        Text(text)
            .macType(.rowMeta)
            .foregroundStyle(color)
            .fixedSize(horizontal: false, vertical: true)
    }
}

/// A native switch on the trailing edge. The identifier sits on the switch
/// itself so the lanes read its 0/1 value and click it directly.
struct MacSettingsToggleRow: View {
    let symbol: String
    let title: String
    let subtitle: String?
    var footnote: String? = nil
    let accessibilityIdentifier: String
    @Binding var isOn: Bool
    var tint: Color = MacTheme.accent

    var body: some View {
        MacSettingsRow(symbol: symbol, title: title, tint: tint) {
            if let subtitle {
                MacSettingsDetailText(subtitle)
            }
            if let footnote {
                MacSettingsDetailText(footnote, color: MacTheme.Text.tertiary)
            }
        } trailing: {
            Toggle(title, isOn: $isOn)
                .toggleStyle(.switch)
                .labelsHidden()
                .tint(tint)
                .accessibilityIdentifier(accessibilityIdentifier)
                .accessibilityLabel(title)
        }
    }
}

enum MacSettingsActionProminence {
    case primary
    case secondary
    case destructive
}

/// Capsule action chrome (the iOS `IOSSettingsActionButtonStyle`) with the
/// desktop's hover lift. A fixed `width` keeps package actions aligned
/// across rows; row buttons size to their label.
struct MacSettingsActionButtonStyle: ButtonStyle {
    let tint: Color
    var prominence: MacSettingsActionProminence = .secondary
    var width: CGFloat? = nil

    func makeBody(configuration: Configuration) -> some View {
        MacSettingsActionButtonBody(
            configuration: configuration,
            tint: tint,
            prominence: prominence,
            width: width
        )
    }
}

private struct MacSettingsActionButtonBody: View {
    let configuration: ButtonStyleConfiguration
    let tint: Color
    let prominence: MacSettingsActionProminence
    let width: CGFloat?

    @State private var isHovering = false

    var body: some View {
        configuration.label
            .macType(.buttonLabel)
            .lineLimit(1)
            .foregroundStyle(foregroundColor)
            // `.icon` rather than `.field`: a settings list's action buttons
            // are secondary, and a Mac list is denser than a phone's. Ten
            // points on every package line also pushes the clone-consent
            // toggle — the last row on the screen — past the scroll budget the
            // smoke lane reveals it with.
            .padding(.horizontal, MacControl.icon.horizontalPadding)
            .frame(width: width, height: MacControl.icon.height)
            .frame(minWidth: 64)
            .background { VocelloShape.pill().fill(backgroundColor) }
            .overlay { VocelloShape.pill().stroke(strokeColor, lineWidth: VocelloTheme.Stroke.hairline) }
            .contentShape(VocelloShape.pill())
            .brightness(isHovering ? 0.08 : 0)
            .opacity(configuration.isPressed ? 0.82 : 1)
            .onHover { hovering in
                AppLaunchConfiguration.performAnimated(MacTheme.Motion.stateChange) {
                    isHovering = hovering
                }
            }
    }

    private var foregroundColor: Color {
        switch prominence {
        case .primary: MacTheme.Text.onAccent
        case .secondary: tint
        case .destructive: MacTheme.Status.critical
        }
    }

    private var backgroundColor: Color {
        switch prominence {
        case .primary: tint.opacity(configuration.isPressed ? 0.72 : 0.92)
        case .secondary, .destructive: MacTheme.Surface.inline
        }
    }

    private var strokeColor: Color {
        let opacity = configuration.isPressed ? 0.68 : 0.42
        return switch prominence {
        case .primary: Color.white.opacity(configuration.isPressed ? 0.12 : 0.18)
        case .secondary: tint.opacity(opacity)
        case .destructive: MacTheme.Status.critical.opacity(opacity)
        }
    }
}

/// Fixed-geometry transfer bar (the iOS `IOSModelTransferProgressBar`): the
/// rendered fill and the accessibility value share one exact fraction, and
/// no parent transition may animate the fill from its minimum capsule.
struct MacSettingsProgressBar: View {
    let fraction: Double
    let tint: Color
    let accessibilityLabel: String
    let accessibilityValue: String
    let accessibilityIdentifier: String

    var body: some View {
        GeometryReader { proxy in
            let clamped = min(max(fraction, 0), 1)
            ZStack(alignment: .leading) {
                VocelloShape.pill()
                    .fill(MacTheme.Surface.inline)
                VocelloShape.pill()
                    .fill(tint)
                    .frame(width: max(clamped > 0 ? 6 : 0, proxy.size.width * clamped))
            }
        }
        .frame(height: 6)
        .transaction { transaction in
            transaction.animation = nil
            transaction.disablesAnimations = true
        }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(accessibilityLabel)
        .accessibilityValue(accessibilityValue)
        .accessibilityIdentifier(accessibilityIdentifier)
    }
}
