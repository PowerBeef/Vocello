import AppKit
import SwiftUI

/// Shown instead of the shell when the bundled contract or the in-process
/// engine could not be built: the same canvas, lockup and surface card the
/// shell uses, so a broken launch still looks like Vocello.
struct MacStartupDiagnosticsView: View {
    let snapshot: AppLaunchDiagnosticsSnapshot
    let onRetry: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: MacTheme.Spacing.xl) {
            VStack(alignment: .leading, spacing: MacTheme.Spacing.sm) {
                VocelloProductTitleLockup(title: MacInterfaceText.brandName)

                Text(snapshot.issue.summary)
                    .macType(.screenTitle)
                    .foregroundStyle(MacTheme.Text.primary)
                    .fixedSize(horizontal: false, vertical: true)

                Text(MacInterfaceText.startupCannotContinue)
                    .macType(.body)
                    .foregroundStyle(MacTheme.Text.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }

            VocelloSurfaceCard {
                diagnosticsRow(MacInterfaceText.startupManifestPath, snapshot.manifestPath)
                diagnosticsRow(MacInterfaceText.startupBundlePath, snapshot.bundlePath)
                diagnosticsRow(MacInterfaceText.startupResourcesPath, snapshot.resourcesPath)

                Rectangle()
                    .fill(MacTheme.Surface.hairline)
                    .frame(height: VocelloTheme.Stroke.standard)
                    .padding(.vertical, 2)

                diagnosticsRow(MacInterfaceText.startupUnderlyingError, snapshot.underlyingError)
            }

            HStack(spacing: MacTheme.Spacing.md) {
                Button(MacInterfaceText.retry, action: onRetry)
                    .buttonStyle(.borderedProminent)
                    .tint(MacTheme.accent)
                    .accessibilityIdentifier("startupDiagnostics_retryButton")

                Button(MacInterfaceText.startupCopyDiagnostics) {
                    NSPasteboard.general.clearContents()
                    NSPasteboard.general.setString(snapshot.diagnosticsText, forType: .string)
                }
                .buttonStyle(.bordered)
                .accessibilityIdentifier("startupDiagnostics_copyButton")
            }
        }
        .frame(maxWidth: 640, alignment: .topLeading)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .padding(MacTheme.Spacing.xl)
        .background(MacTheme.canvasGradient.ignoresSafeArea())
        .accessibilityIdentifier("startupDiagnostics_view")
    }

    private func diagnosticsRow(_ label: String, _ value: String?) -> some View {
        VStack(alignment: .leading, spacing: MacTheme.Spacing.xs) {
            Text(label)
                .macType(.rowTitle)
                .foregroundStyle(MacTheme.Text.primary)
            Text(value ?? MacInterfaceText.startupNotFound)
                .macType(.rowMeta)
                .foregroundStyle(MacTheme.Text.secondary)
                .textSelection(.enabled)
                .fixedSize(horizontal: false, vertical: true)
        }
    }
}
