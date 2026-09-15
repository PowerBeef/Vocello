import AppKit
import SwiftUI

struct StartupDiagnosticsView: View {
    let snapshot: AppLaunchDiagnosticsSnapshot
    let onRetry: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 20) {
            VStack(alignment: .leading, spacing: 8) {
                Label(MacInterfaceText.brandName, systemImage: "waveform")
                    .font(.title.weight(.semibold))

                Text(snapshot.issue.summary)
                    .font(.title3.weight(.semibold))

                Text(MacInterfaceText.startupCannotContinue)
                    .font(.body)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }

            GroupBox {
                VStack(alignment: .leading, spacing: 10) {
                    diagnosticsRow(MacInterfaceText.startupManifestPath, snapshot.manifestPath)
                    diagnosticsRow(MacInterfaceText.startupBundlePath, snapshot.bundlePath)
                    diagnosticsRow(MacInterfaceText.startupResourcesPath, snapshot.resourcesPath)

                    Divider()

                    Text(MacInterfaceText.startupUnderlyingError)
                        .font(.subheadline.weight(.semibold))

                    Text(snapshot.underlyingError)
                        .font(.callout)
                        .foregroundStyle(.secondary)
                        .textSelection(.enabled)
                        .fixedSize(horizontal: false, vertical: true)
                }
                .frame(maxWidth: .infinity, alignment: .leading)
            }
            .profileGroupBoxStyle()

            HStack(spacing: 12) {
                Button(MacInterfaceText.retry, action: onRetry)
                    .buttonStyle(.borderedProminent)
                    .tint(AppTheme.accent)
                    .accessibilityIdentifier("startupDiagnostics_retryButton")

                Button(MacInterfaceText.startupCopyDiagnostics) {
                    NSPasteboard.general.clearContents()
                    NSPasteboard.general.setString(snapshot.diagnosticsText, forType: .string)
                }
                .buttonStyle(.bordered)
                .accessibilityIdentifier("startupDiagnostics_copyButton")
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .padding(24)
        .profileBackground(AppTheme.canvasBackground)
        .accessibilityIdentifier("startupDiagnostics_view")
    }

    private func diagnosticsRow(_ label: String, _ value: String?) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(label)
                .font(.subheadline.weight(.semibold))
            Text(value ?? "Not found")
                .font(.callout)
                .foregroundStyle(.secondary)
                .textSelection(.enabled)
        }
    }
}
