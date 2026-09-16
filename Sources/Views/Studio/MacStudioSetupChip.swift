import QwenVoiceCore
import SwiftUI

/// The iOS setup-chip pill (`IOSSetupChipPill`): the tinted capsule with a
/// glyph, one line of value and a chevron. The one desktop liberty is the
/// label — a Mac window has the width the phone lacks, so the value is
/// written out ("Aiden") where the phone shows a two-letter code ("AI").
/// On macOS the chip *is* the picker: a `Menu` anchored to the pill, so the
/// lanes' `delivery_tonePicker` and the other picker identifiers stay on the
/// trigger and its rows stay real menu items.
enum MacStudioChipMetrics {
    /// The iOS pill height (`IOSSetupChipPill`), which is the app's `pill`
    /// control step. The chips share the row equally and span exactly the
    /// Generate button's width, so a chip never hugs its label and the row
    /// never wraps at a usual window size.
    static let pillHeight: CGFloat = MacControl.pill.height
    /// The floor below which `MacChipFlow` wraps the row. Sized so the value
    /// still reads after the glyph, the chevron and the padding take their
    /// share: below this a four-chip row on a 720 pt window truncated
    /// "Aiden" to "Aid…".
    static let minWidth: CGFloat = 132
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
        .vocelloFocusRing(tint, radius: MacStudioChipMetrics.pillHeight / 2)
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
        .opacity(isEnabled ? 1 : VocelloTheme.Opacity.disabled)
        .vocelloFocusRing(tint, radius: MacStudioChipMetrics.pillHeight / 2)
        .accessibilityLabel(spokenLabel)
        .accessibilityIdentifier(accessibilityIdentifier)
    }

    private var spokenLabel: String { "\(eyebrow): \(value)" }
}

/// The shared setup-chip chrome (`VocelloSetupChipPill`, UIF-02) with the
/// desktop's label: one line, the value written out in full ("Aiden") where
/// the phone shows a two-letter code, inset 12 pt and floored at
/// `MacStudioChipMetrics.minWidth`. The eyebrow the desktop used to stack
/// above the value survives as the spoken label, because a Mac window has
/// room for the value written out in full and a two-line pill reads as a
/// different control.
struct MacStudioSetupChipPill: View {
    let symbol: String
    let eyebrow: String
    let value: String
    let tint: Color
    var isPlaceholder = false
    var showsChevron = true

    @Environment(\.accessibilityReduceTransparency) private var reduceTransparency

    var body: some View {
        VocelloSetupChipPill(
            symbol: symbol,
            tint: tint,
            height: MacStudioChipMetrics.pillHeight,
            horizontalPadding: MacControl.pill.horizontalPadding,
            minWidth: MacStudioChipMetrics.minWidth,
            showsChevron: showsChevron,
            reduceTransparency: reduceTransparency
        ) {
            Text(value)
                .macType(.chipLabel)
                .foregroundStyle(isPlaceholder ? MacTheme.Text.secondary : MacTheme.Text.primary)
                .lineLimit(1)
                .truncationMode(.tail)
        }
        .opacity(isPlaceholder ? VocelloTheme.Opacity.placeholder : 1)
        .contentShape(VocelloShape.pill())
        // One accessibility element per chip: the menu's identifier and value
        // land on a single control the size of the pill, not on each glyph.
        .accessibilityElement(children: .ignore)
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
