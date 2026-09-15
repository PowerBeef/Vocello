import SwiftUI

/// Pending-history recovery card above the list (the iOS recovery banner
/// with the desktop's Reveal action). Identifiers are the lane contract.
struct MacHistoryRecoveryBanner: View {
    let message: String
    let canReveal: Bool
    let canExport: Bool
    let onRetry: () -> Void
    let onReveal: () -> Void
    let onExport: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Label(MacInterfaceText.historyFinishedAudioWaiting, systemImage: "arrow.clockwise.icloud")
                .font(.subheadline.weight(.semibold))
                .foregroundStyle(MacTheme.Text.primary)
            Text(message)
                .font(.caption)
                .foregroundStyle(MacTheme.Text.secondary)
                .fixedSize(horizontal: false, vertical: true)
            HStack(spacing: 10) {
                Button(MacInterfaceText.retry, action: onRetry)
                    .accessibilityIdentifier("historyRecovery_retry")
                Button(MacInterfaceText.historyRevealAudio, action: onReveal)
                    .disabled(!canReveal)
                    .accessibilityIdentifier("historyRecovery_reveal")
                Button(VocelloPresentationText.exportRecoveryFiles, action: onExport)
                    .disabled(!canExport)
                    .accessibilityIdentifier("historyRecovery_export")
            }
            .buttonStyle(.bordered)
            .controlSize(.small)
            .tint(MacTheme.historyTint)
        }
        .padding(14)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(
            MacTheme.Surface.panel,
            in: RoundedRectangle(cornerRadius: 18, style: .continuous)
        )
        .overlay {
            RoundedRectangle(cornerRadius: 18, style: .continuous)
                .stroke(MacTheme.Status.guarded.opacity(0.30), lineWidth: 0.5)
        }
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("historyRecovery_banner")
    }
}
