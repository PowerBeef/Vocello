import SwiftUI
import QwenVoiceCore

/// Pushed Settings destination for the three on-device model lifecycles.
/// The app-wide navigation bar stays hidden; this screen owns a compact 44-point Back control.
struct VoiceModelsScreen: View {
    @Environment(\.iosDockHeight) private var dockHeight
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
        managedModelBytes > 0 ? IOSSettingsText.storageUsed(IOSSettingsFormatters.fileSize(managedModelBytes)) : IOSSettingsText.noModelFiles
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

    var body: some View {
        @Bindable var appModel = appModel

        IOSStudioShellScreen(
            selectedTab: $appModel.tab,
            activeTab: .settings,
            tint: IOSAppTab.settings.dockAccent(studioMode: .custom)
        ) {
            IOSScrollView {
                VStack(alignment: .leading, spacing: Theme.Spacing.md) {
                    compactHeader

                    Text(IOSSettingsText.modelsDetail)
                        .font(.caption)
                        .foregroundStyle(Theme.Text.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                        .padding(.horizontal, 4)

                    IOSSettingsSection(title: IOSSettingsText.overview) {
                        IOSSettingsValueRow(
                            symbol: readyModelCount == TTSModel.all.count
                                ? "checkmark.circle.fill"
                                : "internaldrive",
                            title: IOSSettingsText.modelsReady(readyModelCount, total: TTSModel.all.count),
                            subtitle: nil,
                            accessibilityIdentifier: "iosSettings_storageRow",
                            value: storageSummary
                        )
                    }

                    IOSSettingsSection(title: IOSSettingsText.studioModels) {
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
                .padding(.bottom, max(IOSStudioShellMetrics.dockFadeHeight, dockHeight) + Theme.Spacing.lg)
            }
        }
        .toolbar(.hidden, for: .navigationBar)
        .task {
            await modelManager.refresh()
        }
        .confirmationDialog(
            IOSSettingsText.cancelDownloadTitle,
            isPresented: Binding(
                get: { modelPendingCancel != nil },
                set: { if !$0 { modelPendingCancel = nil } }
            ),
            titleVisibility: .visible
        ) {
            if let model = modelPendingCancel {
                Button(IOSSettingsText.cancelDownloadConfirm, role: .destructive) {
                    modelInstaller.cancel(model)
                    modelPendingCancel = nil
                }
                .accessibilityIdentifier("iosModelCancelDownloadConfirmButton")
                Button(IOSSettingsText.keepDownload, role: .cancel) {
                    modelPendingCancel = nil
                }
            }
        } message: {
            Text(IOSSettingsText.cancelDownloadDetail)
        }
    }

    private var compactHeader: some View {
        HStack(spacing: 8) {
            Button {
                dismiss()
            } label: {
                Image(systemName: "chevron.left")
                            .font(.system(size: 17, weight: .semibold))
                    .foregroundStyle(Theme.Text.primary)
                    .frame(width: 44, height: 44)
                    .background(Theme.Surface.panelMuted, in: Circle())
                    .overlay {
                        Circle()
                            .stroke(Theme.Surface.panelStroke, lineWidth: 0.5)
                    }
                    .contentShape(Circle())
            }
            .buttonStyle(.plain)
            .accessibilityLabel(IOSSettingsText.backModelsFiles)
            .accessibilityIdentifier("iosSettings_voiceModelsBackButton")

            Text(IOSSettingsText.voiceModels)
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
