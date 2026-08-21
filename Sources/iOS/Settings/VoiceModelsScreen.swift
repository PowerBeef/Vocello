import SwiftUI
import QwenVoiceCore

/// Pushed Settings destination for the three on-device model lifecycles.
/// The app-wide navigation bar stays hidden; this screen owns a compact 44-point Back control.
struct VoiceModelsScreen: View {
    @Environment(AppModel.self) private var appModel
    @EnvironmentObject private var modelManager: ModelManagerViewModel
    @EnvironmentObject private var modelInstaller: IOSModelInstallerViewModel
    @Environment(\.dismiss) private var dismiss

    @State private var modelPendingCancel: TTSModel?

    private var managedModelBytes: Int64 {
        TTSModel.all.reduce(into: 0) { total, model in
            switch effectiveStatus(for: model) {
            case .installed(let bytes), .updateAvailable(let bytes, _), .incomplete(_, let bytes):
                total += Int64(bytes)
            case .checking, .notInstalled, .error:
                break
            }
        }
    }

    private var storageSummary: String {
        managedModelBytes > 0 ? "\(IOSSettingsFormatters.fileSize(managedModelBytes)) used" : "No model files"
    }

    private var readyModelCount: Int {
        TTSModel.all.reduce(into: 0) { count, model in
            switch effectiveStatus(for: model) {
            case .installed, .updateAvailable:
                count += 1
            case .checking, .notInstalled, .incomplete, .error:
                break
            }
        }
    }

    private var overviewSubtitle: String {
        readyModelCount == TTSModel.all.count
            ? "Every Studio mode is available offline."
            : "Install a model to enable its Studio mode."
    }

    var body: some View {
        @Bindable var appModel = appModel

        IOSStudioShellScreen(
            selectedTab: $appModel.tab,
            activeTab: .settings,
            tint: IOSAppTab.settings.dockAccent(studioMode: .custom)
        ) {
            IOSScrollView {
                VStack(alignment: .leading, spacing: Theme.Spacing.lg) {
                    compactHeader

                    Text("One private, on-device model powers each Studio mode. Install only the modes you use.")
                        .font(.caption)
                        .foregroundStyle(Theme.Text.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                        .padding(.horizontal, 4)

                    IOSSettingsSection(title: "Overview") {
                        IOSSettingsValueRow(
                            symbol: readyModelCount == TTSModel.all.count
                                ? "checkmark.circle.fill"
                                : "internaldrive",
                            title: "\(readyModelCount) of \(TTSModel.all.count) ready",
                            subtitle: overviewSubtitle,
                            accessibilityIdentifier: "iosSettings_storageRow",
                            value: storageSummary
                        )
                    }

                    IOSSettingsSection(title: "Studio Models") {
                        ForEach(TTSModel.all) { model in
                            IOSModelRow(
                                model: model,
                                status: effectiveStatus(for: model),
                                operationState: modelInstaller.state(for: model),
                                onInstall: { modelInstaller.install(model) },
                                onRequestCancelOptions: { requestCancelOptions(for: model) },
                                onDelete: { modelInstaller.delete(model) }
                            )

                            if model.id != TTSModel.all.last?.id {
                                IOSSettingsDivider()
                            }
                        }
                    }
                }
                .padding(.horizontal, Theme.Spacing.lg)
                .padding(.top, Theme.Spacing.sm)
                .padding(.bottom, IOSStudioShellMetrics.dockFadeHeight + Theme.Spacing.lg)
            }
        }
        .toolbar(.hidden, for: .navigationBar)
        .task {
            await modelManager.refresh()
        }
        .confirmationDialog(
            "Cancel download?",
            isPresented: Binding(
                get: { modelPendingCancel != nil },
                set: { if !$0 { modelPendingCancel = nil } }
            ),
            titleVisibility: .visible
        ) {
            if let model = modelPendingCancel {
                Button("Cancel Download", role: .destructive) {
                    modelInstaller.cancel(model)
                    modelPendingCancel = nil
                }
                .accessibilityIdentifier("iosModelCancelDownloadConfirmButton")
                Button("Keep Download", role: .cancel) {
                    modelPendingCancel = nil
                }
            }
        } message: {
            Text("Canceling removes the downloaded data. You can download it again from scratch.")
        }
    }

    private var compactHeader: some View {
        HStack(spacing: 8) {
            Button {
                dismiss()
            } label: {
                Image(systemName: "chevron.left")
                    .font(.body.weight(.semibold))
                    .foregroundStyle(Theme.Text.primary)
                    .frame(width: 44, height: 44)
                    .background(Theme.Surface.inline, in: Circle())
                    .overlay {
                        Circle()
                            .stroke(Theme.Surface.panelStroke, lineWidth: 0.5)
                    }
                    .contentShape(Circle())
            }
            .buttonStyle(.plain)
            .accessibilityLabel("Back to Settings")
            .accessibilityHint("Returns to the Settings tab")
            .accessibilityIdentifier("iosSettings_voiceModelsBackButton")

            Text("Voice Models")
                .font(.headline)
                .foregroundStyle(Theme.Text.primary)
                .accessibilityAddTraits(.isHeader)
                .accessibilityIdentifier("screen_voiceModels")

            Spacer(minLength: 0)
        }
        .frame(minHeight: 44)
    }

    private func effectiveStatus(for model: TTSModel) -> ModelManagerViewModel.ModelStatus {
        modelManager.statuses[model.id] ?? .checking
    }

    private func requestCancelOptions(for model: TTSModel) {
        IOSHaptics.selection()
        modelPendingCancel = model
    }
}
