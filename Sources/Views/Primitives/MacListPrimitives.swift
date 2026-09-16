import SwiftUI

/// The shared circular icon chrome (`VocelloIconButtonChrome`) inside a
/// desktop button: help tag, label, identifier and the disabled dim, at the
/// `MacControl.icon` step and its glyph size.
struct MacIconButton: View {
    let symbol: String
    let label: String
    let accessibilityIdentifier: String
    var isEnabled = true
    var size: CGFloat = MacControl.icon.height
    var symbolSize: CGFloat = MacControl.icon.glyph
    var help: String? = nil
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            VocelloIconButtonChrome(symbol: symbol, size: size, symbolSize: symbolSize)
                .contentShape(Circle())
        }
        .buttonStyle(.plain)
        .disabled(!isEnabled)
        .opacity(isEnabled ? 1 : VocelloTheme.Opacity.disabled)
        .help(help ?? label)
        .accessibilityLabel(label)
        .accessibilityIdentifier(accessibilityIdentifier)
    }
}

/// Single-select capsule chips (the iOS `IOSFilterChipRow`). Selection is
/// brightness plus the selected trait, never color alone.
struct MacFilterChipRow<Option: Hashable & Identifiable>: View {
    let options: [Option]
    @Binding var selection: Option
    let label: (Option) -> String
    let leading: ((Option) -> AnyView)?
    let accessibilityIdentifier: (Option) -> String

    var body: some View {
        HStack(spacing: MacTheme.Spacing.sm) {
            ForEach(options) { option in
                chip(for: option)
            }
        }
    }

    private func chip(for option: Option) -> some View {
        let isSelected = option == selection
        return Button {
            AppLaunchConfiguration.performAnimated(MacTheme.Motion.stateChange) {
                selection = option
            }
        } label: {
            HStack(spacing: MacTheme.Spacing.tight) {
                if let leading {
                    leading(option)
                }
                Text(label(option))
                    .macType(.chipLabel)
                    .lineLimit(1)
            }
            .foregroundStyle(isSelected ? MacTheme.Text.primary : MacTheme.Text.secondary)
            .frame(minHeight: MacControl.icon.height)
            .padding(.horizontal, MacTheme.Spacing.md)
            .background {
                VocelloShape.pill()
                    .fill(isSelected ? Color.white.opacity(0.10) : Color.white.opacity(0.03))
            }
            .overlay {
                VocelloShape.pill()
                    .stroke(
                        isSelected ? Color.white.opacity(0.18) : Color.white.opacity(0.10),
                        lineWidth: VocelloTheme.Stroke.hairline
                    )
            }
            .contentShape(VocelloShape.pill())
        }
        .buttonStyle(.plain)
        .accessibilityIdentifier(accessibilityIdentifier(option))
        .accessibilityAddTraits(isSelected ? .isSelected : [])
    }
}
