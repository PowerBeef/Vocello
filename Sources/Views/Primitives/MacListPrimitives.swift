import SwiftUI

/// The shared circular icon chrome (`VocelloIconButtonChrome`) inside a
/// desktop button: help tag, label, identifier and the disabled dim, at
/// the Mac's 28 / 12 pt.
struct MacIconButton: View {
    let symbol: String
    let label: String
    let accessibilityIdentifier: String
    var isEnabled = true
    var size: CGFloat = 28
    var symbolSize: CGFloat = 12
    var help: String? = nil
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            VocelloIconButtonChrome(symbol: symbol, size: size, symbolSize: symbolSize)
                .contentShape(Circle())
        }
        .buttonStyle(.plain)
        .disabled(!isEnabled)
        .opacity(isEnabled ? 1 : 0.45)
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
        HStack(spacing: 8) {
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
            HStack(spacing: 6) {
                if let leading {
                    leading(option)
                }
                Text(label(option))
                    .font(.system(size: 12, weight: .semibold))
                    .lineLimit(1)
            }
            .foregroundStyle(isSelected ? MacTheme.Text.primary : MacTheme.Text.secondary)
            .frame(minHeight: 28)
            .padding(.horizontal, 12)
            .background {
                Capsule(style: .continuous)
                    .fill(isSelected ? Color.white.opacity(0.10) : Color.white.opacity(0.03))
            }
            .overlay {
                Capsule(style: .continuous)
                    .stroke(isSelected ? Color.white.opacity(0.18) : Color.white.opacity(0.10), lineWidth: 0.5)
            }
            .contentShape(Capsule(style: .continuous))
        }
        .buttonStyle(.plain)
        .accessibilityIdentifier(accessibilityIdentifier(option))
        .accessibilityAddTraits(isSelected ? .isSelected : [])
    }
}
