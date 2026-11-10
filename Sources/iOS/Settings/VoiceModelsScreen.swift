import SwiftUI
import QwenVoiceCore

/// Pushed Settings destination for the three on-device model lifecycles.
/// The app-wide navigation bar stays hidden; this screen owns a compact 44-point Back control.
struct VoiceModelsScreen: View {
    @Environment(\.iosDockHeight) private var dockHeight
    @Environment(AppModel.self) private var appModel
    @Environment(ModelManagerViewModel.self) private var modelManager
    @Environment(IOSModelInstallerViewModel.self) private var modelInstaller
    @Environment(\.dismiss) private var dismiss

    @State private var modelPendingCancel: TTSModel?
    /// Install, Update and Studio's install button ask first (RF-41, Guideline 4.2.3(ii)).
    @State private var modelPendingDownload: TTSModel?
    /// Kept apart from `modelPendingDownload` so the title does not empty while the alert closes.
    @State private var downloadPromptTitle = ""
    @AppStorage(IOSAppDefaults.cellularModelDownloadsKey) private var cellularDownloadsAllowed = false

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

                    // IOS-08 and RF-35: say which networks a download may use before one starts.
                    Label(
                        cellularDownloadsAllowed
                            ? IOSSettingsText.cellularDownloadsAllowed
                            : IOSSettingsText.downloadsNeedWiFi,
                        systemImage: cellularDownloadsAllowed ? "antenna.radiowaves.left.and.right" : "wifi"
                    )
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

                    IOSSettingsSection {
                        IOSSettingsToggleRow(
                            symbol: "antenna.radiowaves.left.and.right",
                            title: IOSSettingsText.cellularDownloads,
                            subtitle: IOSSettingsText.cellularDownloadsDetail,
                            accessibilityIdentifier: "iosSettings_cellularDownloadsToggle",
                            isOn: $cellularDownloadsAllowed
                        )
                    }

                    IOSSettingsSection(title: IOSSettingsText.studioModels) {
                        ForEach(TTSModel.all) { model in
                            IOSModelRow(
                                model: model,
                                status: effectiveStatus(for: model),
                                operationState: modelInstaller.state(for: model),
                                onInstall: { modelInstaller.install(model) },
                                onRequestDownload: { presentDownloadConfirmation(for: model) },
                                onRequestCancelOptions: { requestCancelOptions(for: model) },
                                onDelete: { modelInstaller.delete(model) },
                                cellularDownloadsAllowed: cellularDownloadsAllowed
                            )

                            if model.id != TTSModel.all.last?.id {
                                IOSSettingsDivider()
                            }
                        }
                    }
                    // An alert, not a confirmation dialog: iOS presents a dialog as a popover
                    // without its Cancel button, and this decision should show both choices.
                    .alert(
                        downloadPromptTitle,
                        isPresented: Binding(
                            get: { modelPendingDownload != nil },
                            set: { if !$0 { modelPendingDownload = nil } }
                        ),
                        presenting: modelPendingDownload
                    ) { model in
                        Button(IOSInterfaceText.download) {
                            modelPendingDownload = nil
                            modelInstaller.install(model)
                        }
                        .accessibilityIdentifier("iosModelDownloadConfirmButton")
                        Button(IOSSettingsText.cancel, role: .cancel) {
                            modelPendingDownload = nil
                        }
                        .accessibilityIdentifier("iosModelDownloadDismissButton")
                    } message: { model in
                        Text(downloadDetail(for: model))
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
        // A Studio install request arrives here as a confirmation, never as a download. A model
        // already transferring, or offering Repair or Retry, just shows its row.
        .onChange(of: appModel.settingsModelNavigation.downloadAwaitingConfirmation, initial: true) {
            if let model = appModel.settingsModelNavigation.takeDownloadAwaitingConfirmation(),
               startsNewDownload(model) {
                presentDownloadConfirmation(for: model)
            }
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
        // A5-01: a removal the busy engine refused kept the model's files.
        .alert(
            IOSSettingsText.removeModelBusyTitle,
            isPresented: Binding(
                get: { modelInstaller.blockedDeletionModelID != nil },
                set: { if !$0 { modelInstaller.dismissBlockedDeletion() } }
            ),
            presenting: modelInstaller.blockedDeletionModelID
        ) { modelID in
            Button(IOSInterfaceText.ok, role: .cancel) {}
                .accessibilityIdentifier("iosModelRemoveBusyDismiss_\(modelID)")
        } message: { _ in
            Text(IOSSettingsText.removeModelBusyMessage)
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

    private func presentDownloadConfirmation(for model: TTSModel) {
        downloadPromptTitle = IOSSettingsText.downloadModelTitle(IOSSettingsText.modeName(model.mode))
        modelPendingDownload = model
    }

    /// The states whose row offers Install or Update, the two actions that ask first.
    private func startsNewDownload(_ model: TTSModel) -> Bool {
        switch modelInstaller.state(for: model) {
        case .available:
            return true
        case .idle:
            switch effectiveStatus(for: model) {
            case .notInstalled, .updateAvailable:
                return true
            case .checking, .installed, .incomplete, .error:
                return false
            }
        default:
            return false
        }
    }

    private func downloadDetail(for model: TTSModel) -> String {
        let size = model.estimatedDownloadBytes.map(IOSSettingsFormatters.fileSize) ?? IOSSettingsText.severalGB
        return cellularDownloadsAllowed
            ? IOSSettingsText.downloadModelDetailCellular(size)
            : IOSSettingsText.downloadModelDetailWiFi(size)
    }

    private func requestCancelOptions(for model: TTSModel) {
        IOSHaptics.selection()
        modelPendingCancel = model
    }
}
