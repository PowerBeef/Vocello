import SwiftUI
import UIKit
import QwenVoiceCore

/// Top-level Settings tab entry point. Reads/writes `AppModel`
/// directly so RootView doesn't need binding plumbing.
///
/// Mirrors `design_references/Vocello iOS/screens.jsx` Settings
/// section: per-model rows with install/delete inline buttons,
/// autoplay toggle, storage row, Reduce Motion / Reduce Transparency
/// rows linking to iOS Settings, version footer.
///
/// Phase 6: this screen owns the Settings body directly; the legacy
/// `IOSSettingsContainerView` / `IOSSettingsView` indirection is gone.
/// The reusable row/section primitives (`IOSSettingsReferenceSection`,
/// `IOSModelRow`, …) live in `IOSSettingsViews.swift`.
struct SettingsScreen: View {
    @Environment(AppModel.self) private var appModel
    @EnvironmentObject private var modelManager: ModelManagerViewModel
    @EnvironmentObject private var modelInstaller: IOSModelInstallerViewModel
    @Environment(\.openURL) private var openURL
    @Environment(\.iosTabIsActive) private var isTabActive

    @AppStorage("autoPlay") private var autoPlay = true
    @AppStorage("vocello.voiceCloningConsent.v1") private var cloneConsentAcknowledged = false
    @AppStorage(IOSGenerationVariationPreference.key) private var generationVariation = IOSGenerationVariationPreference.defaultValue
    @AppStorage(IOSAppDefaults.reduceMotionEnabledKey) private var reduceMotionEnabled = false
    @AppStorage(IOSAppDefaults.reduceTransparencyEnabledKey) private var reduceTransparencyEnabled = false
    // Drives the "Saved outputs" row value reactively (empty == internal "Keep in app (History)").
    @AppStorage(IOSSavedOutputsDestination.displayNameKey) private var savedOutputsName = ""
    @State private var isSavedOutputsDialogPresented = false
    @State private var isFolderPickerPresented = false
    @State private var modelPendingCancel: TTSModel? = nil

    private var installedModelBytes: Int64 {
        TTSModel.all.reduce(0) { total, model in
            guard case let .installed(bytes) = effectiveStatus(for: model) else {
                return total
            }
            return total + Int64(bytes)
        }
    }

    private var storageSummaryText: String {
        installedModelBytes > 0
            ? "\(IOSSettingsFormatters.fileSize(installedModelBytes)) used"
            : "0 GB used"
    }

    var body: some View {
        @Bindable var appModel = appModel

        IOSStudioShellScreen(
            selectedTab: $appModel.tab,
            activeTab: .settings,
            tint: IOSAppTab.settings.dockAccent(studioMode: .custom)
        ) {
            IOSScrollView {
                VStack(alignment: .leading, spacing: 0) {
                    IOSSettingsReferenceSection(title: "Voice cloning") {
                        IOSSettingsReferenceToggleRow(
                            symbol: "hand.raised.fill",
                            title: "I own or have permission to clone the voices I use",
                            accessibilityIdentifier: "voiceCloning_consentAcknowledgment",
                            isOn: $cloneConsentAcknowledged,
                            tint: IOSBrandTheme.clone
                        )

                        // CP-1 option D: the users' own EU AI Act Article
                        // 50(4) disclosure duty, beside the rights gate.
                        Text("If you publish audio of a cloned real voice, disclose that it is AI-generated. EU law may require this.")
                            .iosScaledFont(size: 12, relativeTo: .caption)
                            .foregroundStyle(IOSAppTheme.textSecondary)
                            .fixedSize(horizontal: false, vertical: true)
                            .padding(.horizontal, 16)
                            .padding(.bottom, 12)
                    }

                    IOSSettingsReferenceSection(title: "Voice models") {
                        ForEach(TTSModel.all) { model in
                            IOSModelRow(
                                model: model,
                                status: effectiveStatus(for: model),
                                operationState: effectiveOperationState(for: model),
                                onInstall: { install(model) },
                                onRequestCancelOptions: { requestCancelOptions(for: model) },
                                onDirectCancel: { cancel(model) },
                                onDelete: { delete(model) }
                            )

                            if model.id != TTSModel.all.last?.id {
                                IOSSettingsReferenceDivider()
                            }
                        }
                    }

                    IOSSettingsReferenceSection(title: "Settings") {
                        IOSSettingsReferenceToggleRow(
                            symbol: "play.fill",
                            title: "Autoplay after generate",
                            accessibilityIdentifier: "iosSettings_autoPlayToggle",
                            isOn: $autoPlay,
                            tint: IOSBrandTheme.accent
                        )

                        IOSSettingsReferenceDivider()

                        IOSSettingsVariationRow(selection: $generationVariation)

                        IOSSettingsReferenceDivider()

                        IOSSettingsReferenceValueRow(
                            symbol: "bookmark",
                            title: "Saved outputs",
                            accessibilityIdentifier: "iosSettings_savedOutputsRow",
                            value: savedOutputsName.isEmpty ? "Keep in app (History)" : savedOutputsName,
                            showsChevron: true,
                            action: { isSavedOutputsDialogPresented = true }
                        )

                        IOSSettingsReferenceDivider()

                        IOSSettingsReferenceValueRow(
                            symbol: "arrow.down.to.line",
                            title: "Storage",
                            accessibilityIdentifier: "iosSettings_storageRow",
                            value: storageSummaryText,
                            showsChevron: false
                        )

                        IOSSettingsReferenceDivider()

                        IOSSettingsReferenceToggleRow(
                            symbol: "sparkles",
                            title: "Reduce Motion",
                            accessibilityIdentifier: "iosSettings_reduceMotionToggle",
                            isOn: $reduceMotionEnabled,
                            tint: IOSBrandTheme.accent
                        )

                        IOSSettingsReferenceDivider()

                        IOSSettingsReferenceToggleRow(
                            symbol: "lock.fill",
                            title: "Reduce Transparency",
                            accessibilityIdentifier: "iosSettings_reduceTransparencyToggle",
                            isOn: $reduceTransparencyEnabled,
                            tint: IOSBrandTheme.accent
                        )
                    }

                    IOSSettingsReferenceSection(title: "About") {
                        IOSSettingsReferenceValueRow(
                            symbol: "hand.raised.fill",
                            title: "Privacy Policy",
                            accessibilityIdentifier: "iosSettings_privacyPolicyRow",
                            value: "",
                            showsChevron: true,
                            action: { open("https://vocello.vercel.app/privacy") }
                        )

                        IOSSettingsReferenceDivider()

                        IOSSettingsReferenceValueRow(
                            symbol: "chevron.left.forwardslash.chevron.right",
                            title: "Open source & licenses",
                            accessibilityIdentifier: "iosSettings_openSourceRow",
                            value: "",
                            showsChevron: true,
                            action: { open("https://github.com/PowerBeef/Vocello") }
                        )

                        IOSSettingsReferenceDivider()

                        // Permission recovery: mic / speech access is requested in-flow;
                        // if denied, this is the path back without leaving the app guessing.
                        IOSSettingsReferenceValueRow(
                            symbol: "gearshape.fill",
                            title: "Open iOS Settings",
                            accessibilityIdentifier: "iosSettings_openIOSSettingsRow",
                            value: "Permissions",
                            showsChevron: true,
                            action: { open(UIApplication.openSettingsURLString) }
                        )
                    }

                    IOSSettingsBrandFooter()
                }
                // Extra bottom padding so the bottom-most section clears
                // the TabDock's gradient fade in RootView.
                .padding(.bottom, 90)
            }
        }
        .toolbar(.hidden, for: .navigationBar)
        // Keyed on the tab-active flag (IUI-5 P4): the stable-identity tab
        // container no longer remounts Settings per visit, so re-fire the
        // model refresh on each return — the visible readiness rows here are
        // the state the device lanes assert before generation.
        .task(id: isTabActive) {
            guard isTabActive else { return }
            await modelManager.refresh()
        }
        .confirmationDialog(
            "Saved outputs",
            isPresented: $isSavedOutputsDialogPresented,
            titleVisibility: .visible
        ) {
            Button("Keep in app (History)") { IOSSavedOutputsDestination.clearFolder() }
            Button("Choose a Folder…") { isFolderPickerPresented = true }
        } message: {
            Text("Generated clips are always kept on this iPhone for History. Optionally also copy each new clip to a folder you choose — Files or iCloud Drive.")
        }
        .confirmationDialog(
            "Cancel download?",
            isPresented: Binding(
                get: { modelPendingCancel != nil },
                set: { isPresented in
                    if !isPresented { modelPendingCancel = nil }
                }
            ),
            titleVisibility: .visible
        ) {
            if let model = modelPendingCancel {
                Button("Cancel Download", role: .destructive) {
                    cancel(model)
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
        .fileImporter(
            isPresented: $isFolderPickerPresented,
            allowedContentTypes: [.folder],
            allowsMultipleSelection: false
        ) { result in
            guard case let .success(urls) = result, let url = urls.first else { return }
            try? IOSSavedOutputsDestination.setFolder(url)
        }
    }

    private func effectiveOperationState(for model: TTSModel) -> IOSModelInstallerViewModel.OperationState {
        return modelInstaller.state(for: model)
    }

    private func effectiveStatus(for model: TTSModel) -> ModelManagerViewModel.ModelStatus {
        modelManager.statuses[model.id]
            ?? .checking
    }

    private func open(_ urlString: String) {
        guard let url = URL(string: urlString) else { return }
        openURL(url)
    }

    private func install(_ model: TTSModel) {
        modelInstaller.install(model)
    }

    private func requestCancelOptions(for model: TTSModel) {
        IOSHaptics.selection()
        modelPendingCancel = model
    }

    private func cancel(_ model: TTSModel) {
        modelInstaller.cancel(model)
    }

    private func delete(_ model: TTSModel) {
        modelInstaller.delete(model)
    }
}
