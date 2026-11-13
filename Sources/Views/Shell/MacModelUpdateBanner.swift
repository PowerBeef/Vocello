import QwenVoiceCore
import SwiftUI

/// RF-59: the model update that follows an app update from an earlier Vocello, above every
/// destination. It reports the update while it runs (Settings > Models carries the per-model
/// rows), offers it when it has not started or was stopped, and says how much space the earlier
/// models freed once every mode is updated. Identifiers are the UI lane's contract.
struct MacModelUpdateBanner: View {
    @Environment(ModelManagerViewModel.self) private var modelManager
    let appModel: MacAppModel

    var body: some View {
        if let state = modelManager.modelUpdateBanner {
            card(for: state)
                .padding(.horizontal, MacTheme.Spacing.lg)
                .padding(.top, MacTheme.Spacing.sm)
                .transition(.opacity)
        }
    }

    private func card(for state: ModelManagerViewModel.ModelUpdateBanner) -> some View {
        HStack(alignment: .top, spacing: MacTheme.Spacing.snug) {
            Image(systemName: symbol(for: state))
                .macType(.rowTitle)
                .foregroundStyle(tint(for: state))
                .accessibilityHidden(true)
            VStack(alignment: .leading, spacing: MacTheme.Spacing.xs) {
                Text(title(for: state))
                    .macType(.rowTitle)
                    .foregroundStyle(MacTheme.Text.primary)
                if let message = message(for: state) {
                    Text(message)
                        .macType(.caption)
                        .foregroundStyle(MacTheme.Text.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
                if case .updating(_, _, let fraction) = state {
                    ProgressView(value: fraction)
                        .tint(MacTheme.accent)
                        .accessibilityLabel(MacInterfaceText.modelUpdateTitle)
                        .accessibilityValue(
                            fraction.formatted(.percent.precision(.fractionLength(0)).locale(MacInterfaceLanguage.current.locale))
                        )
                        .accessibilityIdentifier("macModelUpdateBanner_progress")
                }
            }
            Spacer(minLength: MacTheme.Spacing.sm)
            actions(for: state)
        }
        .padding(MacTheme.Spacing.md)
        // A minimum width bounds the message's fixed height in the window's minimum-size pass.
        .frame(minWidth: MacShellMetrics.libraryMessageMinWidth, maxWidth: .infinity, alignment: .leading)
        .background(MacTheme.Surface.panel, in: VocelloShape.card())
        .overlay {
            VocelloShape.card()
                .stroke(tint(for: state).opacity(0.30), lineWidth: VocelloTheme.Stroke.hairline)
        }
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("macModelUpdateBanner")
    }

    @ViewBuilder
    private func actions(for state: ModelManagerViewModel.ModelUpdateBanner) -> some View {
        HStack(spacing: MacTheme.Spacing.sm) {
            switch state {
            case .needed:
                Button(MacInterfaceText.modelUpdateUpdateNow) {
                    Task { await modelManager.startModelUpdate() }
                }
                .buttonStyle(.borderedProminent)
                .accessibilityIdentifier("macModelUpdateBanner_update")
                Button(MacInterfaceText.modelUpdateNotNow) {
                    Task { await modelManager.postponeModelUpdate() }
                }
                .accessibilityIdentifier("macModelUpdateBanner_notNow")
            case .updating:
                showInSettingsButton
            case .done:
                Button(MacInterfaceText.done) {
                    modelManager.dismissModelUpdateCompletion()
                }
                .accessibilityIdentifier("macModelUpdateBanner_dismiss")
            }
        }
        .buttonStyle(.bordered)
        .controlSize(.small)
        .tint(MacTheme.accent)
    }

    private var showInSettingsButton: some View {
        Button(MacInterfaceText.modelUpdateShowInSettings) {
            appModel.pendingHighlightedMode = modelManager.updatePlan.modes.first
            appModel.selectedItem = .settings
        }
        .accessibilityIdentifier("macModelUpdateBanner_showInSettings")
    }

    private func symbol(for state: ModelManagerViewModel.ModelUpdateBanner) -> String {
        switch state {
        case .updating, .needed: "arrow.triangle.2.circlepath.circle.fill"
        case .done: "checkmark.circle.fill"
        }
    }

    private func tint(for state: ModelManagerViewModel.ModelUpdateBanner) -> Color {
        switch state {
        case .updating, .needed: MacTheme.accent
        case .done: MacTheme.Status.healthy
        }
    }

    private func title(for state: ModelManagerViewModel.ModelUpdateBanner) -> String {
        switch state {
        case .updating: MacInterfaceText.modelUpdateTitle
        case .needed: MacInterfaceText.modelUpdateNeededTitle
        case .done: MacInterfaceText.modelUpdateDoneTitle
        }
    }

    private func message(for state: ModelManagerViewModel.ModelUpdateBanner) -> String? {
        switch state {
        case .updating, .needed:
            return MacInterfaceText.modelUpdateMessage
        case .done(let freedBytes):
            guard freedBytes > 0 else { return nil }
            return MacInterfaceText.modelUpdateDoneMessage(MacInterfaceLanguage.current.fileSize(freedBytes))
        }
    }
}
