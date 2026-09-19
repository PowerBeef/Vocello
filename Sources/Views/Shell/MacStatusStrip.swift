import SwiftUI

/// The engine status under the sidebar player, in the iOS status-strip
/// language (`IOSStatusStrip`): one glyph, a title, an optional message, a
/// determinate bar while a fraction is known. Glyphs are static on purpose:
/// this strip is visible for entire generations, and an animating element
/// over glass contends with the engine for the compositor (OPTIMIZATION.md
/// §K). The `sidebar_backendStatus_*` identifiers are the lane contract.
struct MacStatusStrip: View {
    let status: MacShellStatus
    let clearError: @MainActor () -> Void

    private struct Descriptor {
        let stateKey: String
        let symbol: String
        let tint: Color
        let title: String
        let message: String?
        let fraction: Double?
        let dismissible: Bool
    }

    private var descriptor: Descriptor {
        switch status {
        case .idle:
            Descriptor(
                stateKey: "idle", symbol: "checkmark.circle.fill", tint: MacTheme.Status.healthy,
                title: MacInterfaceText.statusReady, message: nil, fraction: nil, dismissible: false
            )
        case .standby:
            Descriptor(
                stateKey: "standby", symbol: "moon.zzz.fill", tint: MacTheme.Brand.silver,
                title: MacInterfaceText.statusStandby, message: nil, fraction: nil, dismissible: false
            )
        case .starting:
            Descriptor(
                stateKey: "starting", symbol: "bolt.horizontal.fill", tint: MacTheme.accent,
                title: MacInterfaceText.statusStarting, message: nil, fraction: nil, dismissible: false
            )
        case .running(let activity):
            Descriptor(
                stateKey: "active", symbol: "waveform", tint: MacTheme.accent,
                title: activity.label, message: nil,
                fraction: activity.fraction.map { min(max($0, 0), 1) }, dismissible: false
            )
        case .error(let message):
            Descriptor(
                stateKey: "error", symbol: "exclamationmark.triangle.fill", tint: MacTheme.Status.guarded,
                title: MacInterfaceText.statusError, message: message, fraction: nil, dismissible: true
            )
        case .crashed(let message):
            Descriptor(
                stateKey: "crashed", symbol: "bolt.slash.fill", tint: MacTheme.Status.critical,
                title: message.localizedCaseInsensitiveContains("unavailable")
                    ? MacInterfaceText.shellEngineUnavailable
                    : MacInterfaceText.shellEngineStopped,
                message: message.isEmpty ? MacInterfaceText.shellRestartToContinue : message,
                fraction: nil, dismissible: false
            )
        }
    }

    var body: some View {
        let descriptor = descriptor
        VStack(alignment: .leading, spacing: 0) {
            strip(descriptor)
                .accessibilityElement(children: .contain)
                .accessibilityIdentifier("sidebar_backendStatus")
        }
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("sidebar_generationStatus")
        .appAnimation(MacTheme.Motion.easeOut, value: descriptor.stateKey)
    }

    private func strip(_ descriptor: Descriptor) -> some View {
        let shape = VocelloShape.card()
        let percent = descriptor.fraction.map { Int(($0 * 100).rounded()) }

        return HStack(alignment: .top, spacing: MacTheme.Spacing.sm) {
            Image(systemName: descriptor.symbol)
                .font(.system(size: MacControl.badge.glyph, weight: .semibold))
                .foregroundStyle(descriptor.tint)
                .macControlSquare(.badge)
                .accessibilityHidden(true)

            VStack(alignment: .leading, spacing: MacTheme.Spacing.xs) {
                Text(descriptor.title)
                    .macType(.rowTitle)
                    .foregroundStyle(MacTheme.Text.primary)
                    .lineLimit(2)
                    .fixedSize(horizontal: false, vertical: true)
                    .frame(minHeight: MacControl.badge.height, alignment: .leading)

                if let message = descriptor.message, !message.isEmpty {
                    Text(message)
                        .macType(.caption)
                        .foregroundStyle(MacTheme.Text.secondary)
                        .lineLimit(3)
                        .fixedSize(horizontal: false, vertical: true)
                }

                if let fraction = descriptor.fraction, let percent {
                    HStack(spacing: MacTheme.Spacing.sm) {
                        ProgressView(value: fraction, total: 1.0)
                            .tint(descriptor.tint)
                            .scaleEffect(y: 0.6, anchor: .center)
                        Text(verbatim: "\(percent)%")
                            .macType(.counter)
                            .foregroundStyle(MacTheme.Text.tertiary)
                    }
                    .padding(.top, 2)
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)

            if descriptor.dismissible {
                Button(action: clearError) {
                    Image(systemName: "xmark.circle.fill")
                        .font(.system(size: MacControl.icon.glyph, weight: .semibold))
                        .foregroundStyle(MacTheme.Text.tertiary)
                }
                .buttonStyle(.plain)
                .accessibilityLabel(MacInterfaceText.playerClose)
                .accessibilityIdentifier("sidebar_backendStatus_dismiss")
            }
        }
        .padding(.horizontal, MacTheme.Spacing.md)
        .padding(.vertical, MacTheme.Spacing.sm)
        .background {
            // Ready/standby are supporting text, not action-shaped panels.
            if descriptor.message != nil || descriptor.fraction != nil {
                Color.clear.macSubtleGlassSurface(
                    in: shape,
                    tint: descriptor.tint,
                    fill: MacTheme.Surface.glassSurfaceMuted,
                    strokeOpacity: 0.16
                )
            }
        }
        .accessibilityIdentifier("sidebar_backendStatus_\(descriptor.stateKey)")
        .accessibilityValue(percent.map { "\($0)%" } ?? descriptor.title)
    }
}
