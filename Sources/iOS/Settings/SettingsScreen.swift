import SwiftUI
import UIKit
import QwenVoiceCore

/// Title-free Settings landing page. The selected tab in the shared dock is the page indicator;
/// only pushed Settings destinations provide their own compact contextual header.
struct SettingsScreen: View {
    @Environment(AppModel.self) private var appModel
    @EnvironmentObject private var modelManager: ModelManagerViewModel
    @Environment(\.openURL) private var openURL
    @Environment(\.iosTabIsActive) private var isTabActive

    @AppStorage("autoPlay") private var autoPlay = true
    @AppStorage("vocello.voiceCloningConsent.v1") private var cloneConsentAcknowledged = false
    @AppStorage(IOSGenerationVariationPreference.key) private var generationVariation = IOSGenerationVariationPreference.defaultValue
    @AppStorage(IOSAppDefaults.reduceMotionEnabledKey) private var reduceMotionEnabled = false
    @AppStorage(IOSAppDefaults.reduceTransparencyEnabledKey) private var reduceTransparencyEnabled = false
    @AppStorage(IOSSavedOutputsDestination.displayNameKey) private var savedOutputsName = ""

    @State private var isSavedOutputsDialogPresented = false
    @State private var isFolderPickerPresented = false

    private var readyModelCount: Int {
        TTSModel.all.reduce(into: 0) { total, model in
            switch effectiveStatus(for: model) {
            case .installed, .updateAvailable:
                total += 1
            default:
                break
            }
        }
    }

    private var modelReadinessSummary: String {
        "\(readyModelCount) of \(TTSModel.all.count) ready"
    }

    private var savedOutputsSummary: String {
        savedOutputsName.isEmpty ? "History only" : savedOutputsName
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
                    audioSection
                    modelsAndFilesSection
                    accessibilitySection
                    privacySection
                    aboutSection
                }
                .padding(.horizontal, Theme.Spacing.lg)
                .padding(.top, Theme.Spacing.md)
                .padding(.bottom, IOSStudioShellMetrics.dockFadeHeight + Theme.Spacing.lg)
            }
        }
        .toolbar(.hidden, for: .navigationBar)
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
        .fileImporter(
            isPresented: $isFolderPickerPresented,
            allowedContentTypes: [.folder],
            allowsMultipleSelection: false
        ) { result in
            guard case let .success(urls) = result, let url = urls.first else { return }
            try? IOSSavedOutputsDestination.setFolder(url)
        }
    }

    private var audioSection: some View {
        IOSSettingsSection(title: "Audio", accessibilityIdentifier: "screen_settings") {
            IOSSettingsToggleRow(
                symbol: "play.fill",
                title: "Play generated audio",
                subtitle: "Automatically play each finished take.",
                accessibilityIdentifier: "iosSettings_autoPlayToggle",
                isOn: $autoPlay
            )

            IOSSettingsDivider()
            IOSSettingsPickerRow(selection: $generationVariation)
        }
    }

    private var modelsAndFilesSection: some View {
        IOSSettingsSection(title: "Models & Files") {
            NavigationLink {
                VoiceModelsScreen()
            } label: {
                IOSSettingsNavigationRow(
                    symbol: "internaldrive",
                    title: "Voice Models",
                    subtitle: "One private model per Studio mode.",
                    value: modelReadinessSummary
                )
            }
            .buttonStyle(.plain)
            .accessibilityIdentifier("iosSettings_voiceModelsRow")
            .accessibilityLabel("Voice Models")
            .accessibilityValue(modelReadinessSummary)
            .accessibilityHint("Opens Voice Models")

            IOSSettingsDivider()
            IOSSettingsValueRow(
                symbol: "bookmark",
                title: "Saved outputs",
                subtitle: "History or a folder in Files.",
                accessibilityIdentifier: "iosSettings_savedOutputsRow",
                value: savedOutputsSummary,
                accessibilityHint: "Opens saved output options",
                action: { isSavedOutputsDialogPresented = true }
            )
        }
    }

    private var accessibilitySection: some View {
        IOSSettingsSection(title: "Accessibility") {
            IOSSettingsToggleRow(
                symbol: "figure.walk.motion",
                title: "Reduce Motion",
                subtitle: "Use simpler transitions and movement.",
                accessibilityIdentifier: "iosSettings_reduceMotionToggle",
                isOn: $reduceMotionEnabled
            )

            IOSSettingsDivider()
            IOSSettingsToggleRow(
                symbol: "rectangle.fill.on.rectangle.fill",
                title: "Reduce Transparency",
                subtitle: "Use more opaque navigation surfaces.",
                accessibilityIdentifier: "iosSettings_reduceTransparencyToggle",
                isOn: $reduceTransparencyEnabled
            )
        }
    }

    private var privacySection: some View {
        IOSSettingsSection(title: "Privacy") {
            IOSSettingsToggleRow(
                symbol: "hand.raised.fill",
                title: "I own or have permission to clone the voices I use",
                subtitle: "Required for Voice Cloning.",
                accessibilityIdentifier: "voiceCloning_consentAcknowledgment",
                isOn: $cloneConsentAcknowledged,
                tint: Theme.Brand.modeClone
            )

            Text("If you publish audio of a cloned real voice, disclose that it is AI-generated. EU law may require this.")
                .font(.footnote)
                .foregroundStyle(Theme.Text.secondary)
                .fixedSize(horizontal: false, vertical: true)
                .padding(.horizontal, 14)
                .padding(.bottom, 12)
                .accessibilityLabel("AI-generated audio disclosure. If you publish audio of a cloned real voice, disclose that it is AI-generated. EU law may require this.")

            IOSSettingsDivider()
            IOSSettingsValueRow(
                symbol: "hand.raised.fill",
                title: "Privacy Policy",
                subtitle: nil,
                accessibilityIdentifier: "iosSettings_privacyPolicyRow",
                value: "Website",
                accessibilityHint: "Opens the Vocello Privacy Policy",
                action: { open("https://vocello.vercel.app/privacy") }
            )

            IOSSettingsDivider()
            IOSSettingsValueRow(
                symbol: "gearshape.fill",
                title: "Permissions",
                subtitle: "Microphone and speech recognition.",
                accessibilityIdentifier: "iosSettings_openIOSSettingsRow",
                value: "iOS Settings",
                accessibilityHint: "Leaves Vocello and opens iOS Settings",
                action: { open(UIApplication.openSettingsURLString) }
            )
        }
    }

    private var aboutSection: some View {
        IOSSettingsSection(title: "About") {
            IOSSettingsValueRow(
                symbol: "chevron.left.forwardslash.chevron.right",
                title: "Open Source & Licenses",
                subtitle: nil,
                accessibilityIdentifier: "iosSettings_openSourceRow",
                value: "GitHub",
                accessibilityHint: "Opens the Vocello source repository",
                action: { open("https://github.com/PowerBeef/Vocello") }
            )

            IOSSettingsDivider()
            IOSSettingsVersionRow()
        }
    }

    private func effectiveStatus(for model: TTSModel) -> ModelManagerViewModel.ModelStatus {
        modelManager.statuses[model.id] ?? .checking
    }

    private func open(_ urlString: String) {
        guard let url = URL(string: urlString) else { return }
        openURL(url)
    }
}
