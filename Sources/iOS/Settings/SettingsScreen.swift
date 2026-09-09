import SwiftUI
import UIKit
import QwenVoiceCore

/// Typed Settings copy shared by the hub and its destinations.
enum IOSSettingsText {
    static var audio: String {
        String(localized: "vocello.settings.refinement.audio", defaultValue: "Audio",
               comment: "Settings audio; preserve product and consent meaning.")
    }
    static var audioSummary: String {
        String(localized: "vocello.settings.refinement.audioSummary", defaultValue: "Playback and take variation",
               comment: "Settings audioSummary; preserve product and consent meaning.")
    }
    static var modelsFiles: String {
        String(localized: "vocello.settings.refinement.modelsFiles", defaultValue: "Models & Files",
               comment: "Settings modelsFiles; preserve product and consent meaning.")
    }
    static var modelsFilesSummary: String {
        String(localized: "vocello.settings.refinement.modelsFilesSummary", defaultValue: "Voice models and saved outputs",
               comment: "Settings modelsFilesSummary; preserve product and consent meaning.")
    }
    static var privacyPermissions: String {
        String(localized: "vocello.settings.refinement.privacyPermissions", defaultValue: "Privacy & Permissions",
               comment: "Settings privacyPermissions; preserve product and consent meaning.")
    }
    static var privacyPermissionsSummary: String {
        String(localized: "vocello.settings.refinement.privacyPermissionsSummary", defaultValue: "Voice consent and permissions",
               comment: "Settings privacyPermissionsSummary; preserve product and consent meaning.")
    }
    static var accessibility: String {
        String(localized: "vocello.settings.refinement.accessibility", defaultValue: "Accessibility",
               comment: "Settings accessibility; preserve product and consent meaning.")
    }
    static var accessibilitySummary: String {
        String(localized: "vocello.settings.refinement.accessibilitySummary", defaultValue: "Motion and transparency",
               comment: "Settings accessibilitySummary; preserve product and consent meaning.")
    }
    static var about: String {
        String(localized: "vocello.settings.refinement.about", defaultValue: "About",
               comment: "Settings about; preserve product and consent meaning.")
    }
    static var aboutSummary: String {
        String(localized: "vocello.settings.refinement.aboutSummary", defaultValue: "Support and app information",
               comment: "Settings aboutSummary; preserve product and consent meaning.")
    }
    static var back: String {
        String(localized: "vocello.settings.refinement.back", defaultValue: "Back to Settings",
               comment: "Settings back; preserve product and consent meaning.")
    }
    static var backModelsFiles: String {
        String(localized: "vocello.settings.refinement.backModelsFiles", defaultValue: "Back to Models & Files",
               comment: "Settings backModelsFiles; preserve product and consent meaning.")
    }
    static var backAbout: String {
        String(localized: "vocello.settings.refinement.backAbout", defaultValue: "Back to About",
               comment: "Settings backAbout; preserve product and consent meaning.")
    }
    static var historyOnly: String {
        String(localized: "vocello.settings.refinement.historyOnly", defaultValue: "History only",
               comment: "Settings historyOnly; preserve product and consent meaning.")
    }
    static var autoPlay: String {
        String(localized: "vocello.settings.refinement.autoPlay", defaultValue: "Play generated audio",
               comment: "Settings autoPlay; preserve product and consent meaning.")
    }
    static var autoPlayDetail: String {
        String(localized: "vocello.settings.refinement.autoPlayDetail", defaultValue: "Automatically play each finished take.",
               comment: "Settings autoPlayDetail; preserve product and consent meaning.")
    }
    static var voiceModels: String {
        String(localized: "vocello.settings.refinement.voiceModels", defaultValue: "Voice Models",
               comment: "Settings voiceModels; preserve product and consent meaning.")
    }
    static var voiceModelsDetail: String {
        String(localized: "vocello.settings.refinement.voiceModelsDetail", defaultValue: "One private model per Studio mode.",
               comment: "Settings voiceModelsDetail; preserve product and consent meaning.")
    }
    static var voiceModelsHint: String {
        String(localized: "vocello.settings.refinement.voiceModelsHint", defaultValue: "Opens Voice Models",
               comment: "Settings voiceModelsHint; preserve product and consent meaning.")
    }
    static var savedOutputs: String {
        String(localized: "vocello.settings.refinement.savedOutputs", defaultValue: "Saved outputs",
               comment: "Settings savedOutputs; preserve product and consent meaning.")
    }
    static var savedOutputsDetail: String {
        String(localized: "vocello.settings.refinement.savedOutputsDetail", defaultValue: "History or a folder in Files.",
               comment: "Settings savedOutputsDetail; preserve product and consent meaning.")
    }
    static var savedOutputsHint: String {
        String(localized: "vocello.settings.refinement.savedOutputsHint", defaultValue: "Opens saved output options",
               comment: "Settings savedOutputsHint; preserve product and consent meaning.")
    }
    static var keepInHistory: String {
        String(localized: "vocello.settings.refinement.keepInHistory", defaultValue: "Keep in History",
               comment: "Settings keepInHistory; preserve product and consent meaning.")
    }
    static var chooseFolder: String {
        String(localized: "vocello.settings.refinement.chooseFolder", defaultValue: "Choose Files folder…",
               comment: "Settings chooseFolder; preserve product and consent meaning.")
    }
    static var reduceMotion: String {
        String(localized: "vocello.settings.refinement.reduceMotion", defaultValue: "Reduce Motion",
               comment: "Settings reduceMotion; preserve product and consent meaning.")
    }
    static var reduceMotionDetail: String {
        String(localized: "vocello.settings.refinement.reduceMotionDetail", defaultValue: "Use simpler transitions and movement.",
               comment: "Settings reduceMotionDetail; preserve product and consent meaning.")
    }
    static var reduceTransparency: String {
        String(localized: "vocello.settings.refinement.reduceTransparency", defaultValue: "Reduce Transparency",
               comment: "Settings reduceTransparency; preserve product and consent meaning.")
    }
    static var reduceTransparencyDetail: String {
        String(localized: "vocello.settings.refinement.reduceTransparencyDetail", defaultValue: "Use more opaque navigation surfaces.",
               comment: "Settings reduceTransparencyDetail; preserve product and consent meaning.")
    }
    static var cloneConsent: String {
        String(localized: "vocello.settings.refinement.cloneConsent", defaultValue: "I own or have permission to clone the voices I use",
               comment: "Settings cloneConsent; preserve product and consent meaning.")
    }
    static var cloneConsentDetail: String {
        String(localized: "vocello.settings.refinement.cloneConsentDetail", defaultValue: "Required for Voice Cloning.",
               comment: "Settings cloneConsentDetail; preserve product and consent meaning.")
    }
    static var cloneDisclosure: String {
        String(localized: "vocello.settings.refinement.cloneDisclosure", defaultValue: "If you publish audio of a cloned real voice, disclose that it is AI-generated. EU law may require this.",
               comment: "Settings cloneDisclosure; preserve product and consent meaning.")
    }
    static var cloneDisclosureHint: String {
        String(localized: "vocello.settings.refinement.cloneDisclosureHint", defaultValue: "AI-generated audio disclosure. If you publish audio of a cloned real voice, disclose that it is AI-generated. EU law may require this.",
               comment: "Settings cloneDisclosureHint; preserve product and consent meaning.")
    }
    static var privacyHint: String {
        String(localized: "vocello.settings.refinement.privacyHint", defaultValue: "Opens the Vocello Privacy Policy",
               comment: "Settings privacyHint; preserve product and consent meaning.")
    }
    static var permissions: String {
        String(localized: "vocello.settings.refinement.permissions", defaultValue: "Permissions",
               comment: "Settings permissions; preserve product and consent meaning.")
    }
    static var permissionsDetail: String {
        String(localized: "vocello.settings.refinement.permissionsDetail", defaultValue: "Microphone and speech recognition.",
               comment: "Settings permissionsDetail; preserve product and consent meaning.")
    }
    static var systemSettings: String {
        String(localized: "vocello.settings.refinement.systemSettings", defaultValue: "iOS Settings",
               comment: "Settings systemSettings; preserve product and consent meaning.")
    }
    static var permissionsHint: String {
        String(localized: "vocello.settings.refinement.permissionsHint", defaultValue: "Leaves Vocello and opens iOS Settings",
               comment: "Settings permissionsHint; preserve product and consent meaning.")
    }
    static var variation: String {
        String(localized: "vocello.settings.refinement.variation", defaultValue: "Take variation",
               comment: "Settings variation; preserve product and consent meaning.")
    }
    static var variationDetail: String {
        String(localized: "vocello.settings.refinement.variationDetail", defaultValue: "Choose how much finished takes vary.",
               comment: "Settings variationDetail; preserve product and consent meaning.")
    }
    static var variationHint: String {
        String(localized: "vocello.settings.refinement.variationHint", defaultValue: "Choose Expressive, Balanced, or Consistent",
               comment: "Settings variationHint; preserve product and consent meaning.")
    }
    static var version: String {
        String(localized: "vocello.settings.refinement.version", defaultValue: "Version",
               comment: "Settings version; preserve product and consent meaning.")
    }
    static func modelsReady(_ ready: Int, total: Int) -> String {
        String.localizedStringWithFormat(String(localized: "vocello.settings.refinement.modelsReady",
            defaultValue: "%d of %d ready", comment: "Installed model count out of total available models."), ready, total)
    }
}

enum IOSSettingsCategory: String, CaseIterable {
    case audio, modelsFiles, privacyPermissions, accessibility, about
    var title: String {
        switch self {
        case .audio: IOSSettingsText.audio
        case .modelsFiles: IOSSettingsText.modelsFiles
        case .privacyPermissions: IOSSettingsText.privacyPermissions
        case .accessibility: IOSSettingsText.accessibility
        case .about: IOSSettingsText.about
        }
    }
    var subtitle: String {
        switch self {
        case .audio: IOSSettingsText.audioSummary
        case .modelsFiles: IOSSettingsText.modelsFilesSummary
        case .privacyPermissions: IOSSettingsText.privacyPermissionsSummary
        case .accessibility: IOSSettingsText.accessibilitySummary
        case .about: IOSSettingsText.aboutSummary
        }
    }
    var hint: String { subtitle }
    var symbol: String {
        switch self {
        case .audio: "waveform"
        case .modelsFiles: "internaldrive"
        case .privacyPermissions: "hand.raised"
        case .accessibility: "accessibility"
        case .about: "info.circle"
        }
    }
    var linkID: String { "iosSettings_\(rawValue)Row" }
    var screenID: String { "screen_settings_\(rawValue)" }
    var backID: String { "iosSettings_\(rawValue)BackButton" }
}

/// Pushed into the Settings tab's existing stack; never creates another navigation shell.
private struct IOSSettingsDetailPage<Content: View>: View {
    @Environment(AppModel.self) private var appModel
    @Environment(\.dismiss) private var dismiss
    let category: IOSSettingsCategory
    @ViewBuilder let content: Content

    var body: some View {
        @Bindable var appModel = appModel
        IOSStudioShellScreen(selectedTab: $appModel.tab, activeTab: .settings,
                             tint: IOSAppTab.settings.dockAccent(studioMode: .custom)) {
            IOSScrollView {
                VStack(alignment: .leading, spacing: Theme.Spacing.lg) {
                    HStack(spacing: 8) {
                        Button { dismiss() } label: {
                            Image(systemName: "chevron.left")
                                .font(.system(size: 17, weight: .semibold))
                                .foregroundStyle(Theme.Text.primary)
                                .frame(width: 44, height: 44)
                                .background(Theme.Surface.inline, in: Circle())
                                .contentShape(Circle())
                        }
                        .buttonStyle(.plain)
                        .accessibilityLabel(IOSSettingsText.back)
                        .accessibilityIdentifier(category.backID)
                        Text(category.title)
                            .font(.headline)
                            .foregroundStyle(Theme.Text.primary)
                            .fixedSize(horizontal: false, vertical: true)
                            .accessibilityAddTraits(.isHeader)
                            .accessibilityIdentifier(category.screenID)
                        Spacer(minLength: 0)
                    }
                    content
                }
                .padding(.horizontal, Theme.Spacing.lg)
                .padding(.top, Theme.Spacing.md)
                .padding(.bottom, IOSStudioShellMetrics.dockFadeHeight + Theme.Spacing.lg)
            }
        }
        .toolbar(.hidden, for: .navigationBar)
    }
}


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
    @State private var isExportPurchasePresented = false

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
        IOSSettingsText.modelsReady(readyModelCount, total: TTSModel.all.count)
    }

    private var savedOutputsSummary: String {
        savedOutputsName.isEmpty ? IOSSettingsText.historyOnly : savedOutputsName
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
                    IOSSettingsSection {
                        categoryLink(.audio) { audioSection }
                        IOSSettingsDivider()
                        NavigationLink { modelsAndFilesDestination } label: {
                            categoryLabel(.modelsFiles)
                        }
                        .buttonStyle(.plain)
                        .accessibilityIdentifier("iosSettings_modelsFilesRow")
                        .accessibilityLabel(IOSSettingsCategory.modelsFiles.title)
                        .accessibilityHint(IOSSettingsCategory.modelsFiles.hint)
                    }
                    exportPurchaseSection
                    IOSSettingsSection {
                        categoryLink(.privacyPermissions) { privacySection }
                        IOSSettingsDivider()
                        categoryLink(.accessibility) { accessibilitySection }
                        IOSSettingsDivider()
                        categoryLink(.about) { aboutSection }
                    }
                }
                .accessibilityElement(children: .contain)
                .accessibilityIdentifier("screen_settings")
                .padding(.horizontal, Theme.Spacing.lg)
                .padding(.top, Theme.Spacing.md)
                .padding(.bottom, IOSStudioShellMetrics.dockFadeHeight + Theme.Spacing.lg)
            }
        }
        .toolbar(.hidden, for: .navigationBar)
        .sheet(isPresented: $isExportPurchasePresented) { IOSExportPurchaseSheet() }
        .task(id: isTabActive) {
            guard isTabActive else { return }
            await modelManager.refresh()
        }
    }

    private func categoryLink<Content: View>(
        _ category: IOSSettingsCategory, @ViewBuilder content: () -> Content
    ) -> some View {
        NavigationLink {
            IOSSettingsDetailPage(category: category, content: content)
        } label: {
            categoryLabel(category)
        }
        .buttonStyle(.plain)
        .accessibilityIdentifier(category.linkID)
        .accessibilityLabel(category.title)
        .accessibilityHint(category.hint)
    }

    private func categoryLabel(_ category: IOSSettingsCategory) -> some View {
        IOSSettingsNavigationRow(symbol: category.symbol, title: category.title,
                                 subtitle: category.subtitle, value: "")
    }

    private var modelsAndFilesDestination: some View {
        IOSSettingsDetailPage(category: .modelsFiles) { modelsAndFilesSection }
        .confirmationDialog(
            IOSSettingsText.savedOutputs,
            isPresented: $isSavedOutputsDialogPresented,
            titleVisibility: .visible
        ) {
            Button(IOSSettingsText.keepInHistory) { IOSSavedOutputsDestination.clearFolder() }
            Button(IOSSettingsText.chooseFolder) { isFolderPickerPresented = true }
        } message: {
            Text(VocelloPresentationText.exportFolderDetail)
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
        IOSSettingsSection {
            IOSSettingsToggleRow(
                symbol: "play.fill",
                title: IOSSettingsText.autoPlay,
                subtitle: IOSSettingsText.autoPlayDetail,
                accessibilityIdentifier: "iosSettings_autoPlayToggle",
                isOn: $autoPlay
            )

            IOSSettingsDivider()
            IOSSettingsPickerRow(selection: $generationVariation)
        }
    }

    private var exportPurchaseSection: some View {
        IOSSettingsSection(accent: Theme.Brand.gold) {
            Button { isExportPurchasePresented = true } label: {
                IOSSettingsNavigationRow(
                symbol: IOSExportCommerce.shared.access == .unlocked ? "checkmark.circle" : "square.and.arrow.up",
                title: VocelloPresentationText.exportUnlockTitle,
                subtitle: exportSummary,
                value: "",
                tint: Theme.Brand.gold
                )
            }
            .buttonStyle(.plain)
            .accessibilityIdentifier("iosSettings_exportPurchaseRow")
            .accessibilityLabel(VocelloPresentationText.exportUnlockTitle)
            .accessibilityValue(exportSummary)
            .accessibilityHint(VocelloPresentationText.exportOptionsHint)
        }
    }

    private var exportSummary: String {
        switch IOSExportCommerce.shared.access {
        case .unlocked: VocelloPresentationText.exportUnlocked
        case .checking: VocelloPresentationText.exportChecking
        case .locked: VocelloPresentationText.exportRootSummary
        }
    }

    private var modelsAndFilesSection: some View {
        IOSSettingsSection {
            NavigationLink {
                VoiceModelsScreen()
            } label: {
                IOSSettingsNavigationRow(
                    symbol: "internaldrive",
                    title: IOSSettingsText.voiceModels,
                    subtitle: IOSSettingsText.voiceModelsDetail,
                    value: modelReadinessSummary
                )
            }
            .buttonStyle(.plain)
            .accessibilityIdentifier("iosSettings_voiceModelsRow")
            .accessibilityLabel(IOSSettingsText.voiceModels)
            .accessibilityValue(modelReadinessSummary)
            .accessibilityHint(IOSSettingsText.voiceModelsHint)

            IOSSettingsDivider()
            IOSSettingsValueRow(
                symbol: "bookmark",
                title: IOSSettingsText.savedOutputs,
                subtitle: IOSSettingsText.savedOutputsDetail,
                accessibilityIdentifier: "iosSettings_savedOutputsRow",
                value: savedOutputsSummary,
                accessibilityHint: IOSSettingsText.savedOutputsHint,
                action: { isSavedOutputsDialogPresented = true }
            )
        }
    }

    private var accessibilitySection: some View {
        IOSSettingsSection {
            IOSSettingsToggleRow(
                symbol: "figure.walk.motion",
                title: IOSSettingsText.reduceMotion,
                subtitle: IOSSettingsText.reduceMotionDetail,
                accessibilityIdentifier: "iosSettings_reduceMotionToggle",
                isOn: $reduceMotionEnabled
            )

            IOSSettingsDivider()
            IOSSettingsToggleRow(
                symbol: "rectangle.fill.on.rectangle.fill",
                title: IOSSettingsText.reduceTransparency,
                subtitle: IOSSettingsText.reduceTransparencyDetail,
                accessibilityIdentifier: "iosSettings_reduceTransparencyToggle",
                isOn: $reduceTransparencyEnabled
            )
        }
    }

    private var privacySection: some View {
        IOSSettingsSection {
            IOSSettingsToggleRow(
                symbol: "hand.raised.fill",
                title: IOSSettingsText.cloneConsent,
                subtitle: IOSSettingsText.cloneConsentDetail,
                accessibilityIdentifier: "voiceCloning_consentAcknowledgment",
                isOn: $cloneConsentAcknowledged,
                tint: Theme.Brand.modeClone
            )

            Text(IOSSettingsText.cloneDisclosure)
                .font(.footnote)
                .foregroundStyle(Theme.Text.secondary)
                .fixedSize(horizontal: false, vertical: true)
                .padding(.horizontal, 14)
                .padding(.bottom, 12)
                .accessibilityLabel(IOSSettingsText.cloneDisclosureHint)

            IOSSettingsDivider()
            IOSSettingsValueRow(
                symbol: "hand.raised.fill",
                title: VocelloPresentationText.exportPrivacy,
                subtitle: nil,
                accessibilityIdentifier: "iosSettings_privacyPolicyRow",
                value: "",
                accessibilityHint: IOSSettingsText.privacyHint,
                action: { open("https://vocello.vercel.app/privacy") }
            )

            IOSSettingsDivider()
            IOSSettingsValueRow(
                symbol: "gearshape.fill",
                title: IOSSettingsText.permissions,
                subtitle: IOSSettingsText.permissionsDetail,
                accessibilityIdentifier: "iosSettings_openIOSSettingsRow",
                value: IOSSettingsText.systemSettings,
                accessibilityHint: IOSSettingsText.permissionsHint,
                action: { open(UIApplication.openSettingsURLString) }
            )
        }
    }

    private var aboutSection: some View {
        IOSSettingsSection {
            IOSSettingsValueRow(
                symbol: "questionmark.circle.fill",
                title: String(localized: "vocello.settings.help_support"),
                subtitle: String(localized: "vocello.settings.help_support.subtitle"),
                accessibilityIdentifier: "iosSettings_supportRow",
                value: "",
                accessibilityHint: String(localized: "vocello.settings.help_support.hint"),
                action: { open("https://vocello.vercel.app/support/") }
            )

            IOSSettingsDivider()
            NavigationLink {
                OpenSourceLicensesScreen()
            } label: {
                IOSSettingsNavigationRow(
                    symbol: "chevron.left.forwardslash.chevron.right",
                    title: String(localized: "vocello.settings.open_source_licenses"),
                    subtitle: nil,
                    value: ""
                )
            }
            .buttonStyle(.plain)
            .accessibilityIdentifier("iosSettings_openSourceRow")
            .accessibilityLabel(String(localized: "vocello.settings.open_source_licenses"))
            .accessibilityValue(String(localized: "vocello.settings.on_device"))
            .accessibilityHint(String(localized: "vocello.settings.open_source_licenses.hint"))

            IOSSettingsDivider()
            IOSSettingsValueRow(
                symbol: "chevron.left.forwardslash.chevron.right",
                title: String(localized: "vocello.settings.source_code"),
                subtitle: nil,
                accessibilityIdentifier: "iosSettings_sourceCodeRow",
                value: "",
                accessibilityHint: String(localized: "vocello.settings.source_code.hint"),
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
