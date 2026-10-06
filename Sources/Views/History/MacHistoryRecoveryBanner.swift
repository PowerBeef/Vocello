import SwiftUI

/// Pending-history recovery card above the list (the iOS recovery banner
/// with the desktop's Reveal action). Identifiers are the lane contract.
struct MacHistoryRecoveryBanner: View {
    let title: String
    let message: String
    let canReveal: Bool
    let canExport: Bool
    /// Records that cannot be verified may be set aside, after a confirmation
    /// (A2-02); the action shows only then.
    let canDiscard: Bool
    let onRetry: () -> Void
    let onReveal: () -> Void
    let onExport: () -> Void
    let onDiscard: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: VocelloTheme.Spacing.snug) {
            Label(title, systemImage: "arrow.clockwise.icloud")
                .macType(.screenTitle)
                .foregroundStyle(MacTheme.Text.primary)
            Text(message)
                .macType(.caption)
                .foregroundStyle(MacTheme.Text.secondary)
                .fixedSize(horizontal: false, vertical: true)
            HStack(spacing: VocelloTheme.Spacing.snug) {
                Button(MacInterfaceText.retry, action: onRetry)
                    .accessibilityIdentifier("historyRecovery_retry")
                Button(MacInterfaceText.historyRevealAudio, action: onReveal)
                    .disabled(!canReveal)
                    .accessibilityIdentifier("historyRecovery_reveal")
                Button(VocelloPresentationText.exportRecoveryFiles, action: onExport)
                    .disabled(!canExport)
                    .accessibilityIdentifier("historyRecovery_export")
                if canDiscard {
                    Button(MacInterfaceText.presentation.discardUnverifiableRecords, role: .destructive, action: onDiscard)
                        .accessibilityIdentifier("historyRecovery_discard")
                }
            }
            .buttonStyle(.bordered)
            .controlSize(.small)
            .tint(MacTheme.historyTint)
        }
        .padding(VocelloTheme.Spacing.lg)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(
            MacTheme.Surface.panel,
            in: VocelloShape.card()
        )
        .overlay {
            VocelloShape.card()
                .stroke(MacTheme.Status.guarded.opacity(0.30), lineWidth: VocelloTheme.Stroke.hairline)
        }
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("historyRecovery_banner")
    }
}
