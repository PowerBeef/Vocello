import QwenVoiceCore
import SwiftUI

/// The iOS setup-chip pill (`IOSSetupChipPill`) adapted to the desktop: the
/// tinted capsule with the glyph, and — because a Mac window has the width
/// a phone lacks — the eyebrow and the value written out instead of a
/// two-letter abbreviation. On macOS the chip *is* the picker: a `Menu`
/// anchored to the pill, so the lanes' `delivery_tonePicker` and the other
/// picker identifiers stay on the trigger and its rows stay real menu items.
enum MacStudioChipMetrics {
    static let pillHeight: CGFloat = 44
    static let minWidth: CGFloat = 120
}

struct MacStudioSetupChip<MenuContent: View>: View {
    let eyebrow: String
    let value: String
    let leadingSymbol: String
    let tint: Color
    var isPlaceholder = false
    let accessibilityIdentifier: String
    var accessibilityValue: String? = nil
    @ViewBuilder let menuContent: () -> MenuContent

    var body: some View {
        Menu {
            menuContent()
        } label: {
            MacStudioSetupChipPill(
                symbol: leadingSymbol,
                eyebrow: eyebrow,
                value: value,
                tint: tint,
                isPlaceholder: isPlaceholder
            )
        }
        .menuStyle(.button)
        .buttonStyle(.plain)
        .menuIndicator(.hidden)
        .tint(tint)
        .vocelloFocusRing(tint, radius: 22)
        .accessibilityLabel(spokenLabel)
        .accessibilityValue(accessibilityValue ?? value)
        .accessibilityIdentifier(accessibilityIdentifier)
    }

    private var spokenLabel: String { "\(eyebrow): \(value)" }
}

/// A chip that runs an action instead of opening a menu (the desktop batch
/// entry, the seed pin).
struct MacStudioActionChip: View {
    let eyebrow: String
    let value: String
    let leadingSymbol: String
    let tint: Color
    var isEnabled = true
    let accessibilityIdentifier: String
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            MacStudioSetupChipPill(
                symbol: leadingSymbol,
                eyebrow: eyebrow,
                value: value,
                tint: tint,
                showsChevron: false
            )
        }
        .buttonStyle(.plain)
        .disabled(!isEnabled)
        .opacity(isEnabled ? 1 : 0.45)
        .vocelloFocusRing(tint, radius: 22)
        .accessibilityLabel(spokenLabel)
        .accessibilityIdentifier(accessibilityIdentifier)
    }

    private var spokenLabel: String { "\(eyebrow): \(value)" }
}

struct MacStudioSetupChipPill: View {
    let symbol: String
    let eyebrow: String
    let value: String
    let tint: Color
    var isPlaceholder = false
    var showsChevron = true

    @Environment(\.accessibilityReduceTransparency) private var reduceTransparency

    var body: some View {
        HStack(spacing: 8) {
            Image(systemName: symbol)
                .font(.system(size: 15, weight: .semibold))
                .symbolRenderingMode(.hierarchical)
                .foregroundStyle(MacTheme.Text.primary)
                .frame(width: 18)

            VStack(alignment: .leading, spacing: 1) {
                Text(eyebrow)
                    .font(.system(size: 10, weight: .semibold))
                    .tracking(0.4)
                    .textCase(.uppercase)
                    .foregroundStyle(MacTheme.Text.tertiary)
                    .lineLimit(1)
                Text(value)
                    .font(.system(size: 12, weight: .semibold))
                    .foregroundStyle(isPlaceholder ? MacTheme.Text.secondary : MacTheme.Text.primary)
                    .lineLimit(1)
                    .truncationMode(.tail)
            }
            .frame(maxWidth: .infinity, alignment: .leading)

            if showsChevron {
                Image(systemName: "chevron.down")
                    .font(.system(size: 9, weight: .semibold))
                    .foregroundStyle(tint.opacity(0.6))
                    .accessibilityHidden(true)
            }
        }
        .padding(.horizontal, 12)
        .frame(minWidth: MacStudioChipMetrics.minWidth, maxWidth: .infinity)
        .frame(height: MacStudioChipMetrics.pillHeight)
        .background { Capsule(style: .continuous).fill(fillStyle) }
        .overlay { Capsule(style: .continuous).stroke(Color.white.opacity(0.12), lineWidth: 0.8) }
        .overlay {
            Capsule(style: .continuous)
                .inset(by: 0.65)
                .stroke(Color.white.opacity(0.04), lineWidth: 0.55)
        }
        .shadow(color: reduceTransparency ? .clear : tint.opacity(0.22), radius: 8, y: 1)
        .opacity(isPlaceholder ? 0.7 : 1)
        .contentShape(Capsule(style: .continuous))
    }

    private var fillStyle: AnyShapeStyle {
        if reduceTransparency {
            return AnyShapeStyle(tint.opacity(0.22))
        }
        return AnyShapeStyle(
            LinearGradient(
                colors: [tint.opacity(0.30), tint.opacity(0.14)],
                startPoint: .top,
                endPoint: .bottom
            )
        )
    }
}

/// Pinned-seed chip (the iOS `IOSSeedPinChip`): visible only while a seed is
/// pinned from History; the unpin confirmation returns to a fresh seed per
/// take. Keeps the desktop identifiers `textInput_seedPinChip` and
/// `textInput_seedUnpin`.
struct MacSeedPinChip: View {
    @Binding var pinnedSeed: UInt64?
    let tint: Color

    @State private var isConfirmingUnpin = false

    var body: some View {
        if let seedValue = pinnedSeed {
            MacStudioActionChip(
                eyebrow: MacInterfaceText.studioChipSeed,
                value: MacInterfaceText.textInputSeed(String(seedValue)),
                leadingSymbol: "pin.fill",
                tint: tint,
                accessibilityIdentifier: "textInput_seedPinChip",
                action: { isConfirmingUnpin = true }
            )
            .help(MacInterfaceText.textInputSeedPinnedHelp(String(seedValue)))
            .confirmationDialog(
                MacInterfaceText.textInputSeedPinnedHelp(String(seedValue)),
                isPresented: $isConfirmingUnpin,
                titleVisibility: .visible
            ) {
                Button(MacInterfaceText.textInputUnpinSeed) {
                    pinnedSeed = nil
                }
                .accessibilityIdentifier("textInput_seedUnpin")
                Button(MacInterfaceText.cancel, role: .cancel) {}
            }
        }
    }
}
