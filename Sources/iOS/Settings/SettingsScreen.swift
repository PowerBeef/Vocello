import SwiftUI
import UIKit
import QwenVoiceCore

/// Typed Settings copy shared by the hub and its destinations.
@MainActor enum IOSSettingsText {
    static var appLanguage: String {
        IOSAppLanguage.shared.localized(localized: "vocello.settings.appLanguage", defaultValue: "App Language",
            comment: "Language of the interface, not generated speech.")
    }
    static var appLanguageDetail: String {
        IOSAppLanguage.shared.localized(localized: "vocello.settings.appLanguageDetail",
            defaultValue: "Changes the app interface, not the language of generated speech.",
            comment: "Explains the separate interface language preference.")
    }
    static var systemLanguage: String {
        IOSAppLanguage.shared.localized(localized: "vocello.settings.systemLanguage", defaultValue: "System Default",
            comment: "Follow the operating system's preferred app language.")
    }
    static var builtIn: String {
        IOSAppLanguage.shared.localized(localized: "vocello.settings.polish.builtIn", defaultValue: "Built-in Voice",
               comment: "Settings and model management presentation; no change to stored identities.")
    }
    static var design: String {
        IOSAppLanguage.shared.localized(localized: "vocello.settings.polish.design", defaultValue: "Voice Design",
               comment: "Settings and model management presentation; no change to stored identities.")
    }
    static var clone: String {
        IOSAppLanguage.shared.localized(localized: "vocello.settings.polish.clone", defaultValue: "Voice Cloning",
               comment: "Settings and model management presentation; no change to stored identities.")
    }
    static var overview: String {
        IOSAppLanguage.shared.localized(localized: "vocello.settings.polish.overview", defaultValue: "Overview",
               comment: "Settings and model management presentation; no change to stored identities.")
    }
    static var studioModels: String {
        IOSAppLanguage.shared.localized(localized: "vocello.settings.polish.studioModels", defaultValue: "Studio Models",
               comment: "Settings and model management presentation; no change to stored identities.")
    }
    static var modelsDetail: String {
        IOSAppLanguage.shared.localized(localized: "vocello.settings.polish.modelsDetail", defaultValue: "One private, on-device model powers each Studio mode. Install only the modes you use.",
               comment: "Settings and model management presentation; no change to stored identities.")
    }
    static var noModelFiles: String {
        IOSAppLanguage.shared.localized(localized: "vocello.settings.polish.noModelFiles", defaultValue: "No model files",
               comment: "Settings and model management presentation; no change to stored identities.")
    }
    static var install: String {
        IOSAppLanguage.shared.localized(localized: "vocello.settings.polish.install", defaultValue: "Install",
               comment: "Settings and model management presentation; no change to stored identities.")
    }
    static var remove: String {
        IOSAppLanguage.shared.localized(localized: "vocello.settings.polish.remove", defaultValue: "Remove",
               comment: "Settings and model management presentation; no change to stored identities.")
    }
    static var update: String {
        IOSAppLanguage.shared.localized(localized: "vocello.settings.polish.update", defaultValue: "Update",
               comment: "Settings and model management presentation; no change to stored identities.")
    }
    static var repair: String {
        IOSAppLanguage.shared.localized(localized: "vocello.settings.polish.repair", defaultValue: "Repair",
               comment: "Settings and model management presentation; no change to stored identities.")
    }
    static var retry: String {
        IOSAppLanguage.shared.localized(localized: "vocello.settings.polish.retry", defaultValue: "Retry",
               comment: "Settings and model management presentation; no change to stored identities.")
    }
    static var cancel: String {
        IOSAppLanguage.shared.localized(localized: "vocello.settings.polish.cancel", defaultValue: "Cancel",
               comment: "Settings and model management presentation; no change to stored identities.")
    }
    static var cancelDownload: String {
        IOSAppLanguage.shared.localized(localized: "vocello.settings.polish.cancelDownload", defaultValue: "Cancel download",
               comment: "Settings and model management presentation; no change to stored identities.")
    }
    static var cancelDownloadTitle: String {
        IOSAppLanguage.shared.localized(localized: "vocello.settings.polish.cancelDownloadTitle", defaultValue: "Cancel download?",
               comment: "Settings and model management presentation; no change to stored identities.")
    }
    static var cancelDownloadConfirm: String {
        IOSAppLanguage.shared.localized(localized: "vocello.settings.polish.cancelDownloadConfirm", defaultValue: "Cancel Download",
               comment: "Settings and model management presentation; no change to stored identities.")
    }
    static var keepDownload: String {
        IOSAppLanguage.shared.localized(localized: "vocello.settings.polish.keepDownload", defaultValue: "Keep Download",
               comment: "Settings and model management presentation; no change to stored identities.")
    }
    static var cancelDownloadDetail: String {
        IOSAppLanguage.shared.localized(localized: "vocello.settings.polish.cancelDownloadDetail", defaultValue: "Canceling removes the downloaded data. You can download it again from scratch.",
               comment: "Settings and model management presentation; no change to stored identities.")
    }
    static var checking: String {
        IOSAppLanguage.shared.localized(localized: "vocello.settings.polish.checking", defaultValue: "Checking…",
               comment: "Settings and model management presentation; no change to stored identities.")
    }
    static var notInstalled: String {
        IOSAppLanguage.shared.localized(localized: "vocello.settings.polish.notInstalled", defaultValue: "Not Installed",
               comment: "Settings and model management presentation; no change to stored identities.")
    }
    static var updateAvailable: String {
        IOSAppLanguage.shared.localized(localized: "vocello.settings.polish.updateAvailable", defaultValue: "Update Available",
               comment: "Settings and model management presentation; no change to stored identities.")
    }
    static var repairNeeded: String {
        IOSAppLanguage.shared.localized(localized: "vocello.settings.polish.repairNeeded", defaultValue: "Repair Needed",
               comment: "Settings and model management presentation; no change to stored identities.")
    }
    static var retryNeeded: String {
        IOSAppLanguage.shared.localized(localized: "vocello.settings.polish.retryNeeded", defaultValue: "Retry Needed",
               comment: "Settings and model management presentation; no change to stored identities.")
    }
    static var queued: String {
        IOSAppLanguage.shared.localized(localized: "vocello.settings.polish.queued", defaultValue: "Queued",
               comment: "Settings and model management presentation; no change to stored identities.")
    }
    static var waitingForNetwork: String {
        IOSAppLanguage.shared.localized(localized: "vocello.settings.polish.waitingForNetwork", defaultValue: "Waiting for Network",
               comment: "Settings and model management presentation; no change to stored identities.")
    }
    static var finishing: String {
        IOSAppLanguage.shared.localized(localized: "vocello.settings.polish.finishing", defaultValue: "Finishing",
               comment: "Settings and model management presentation; no change to stored identities.")
    }
    static var downloading: String {
        IOSAppLanguage.shared.localized(localized: "vocello.settings.polish.downloading", defaultValue: "Downloading",
               comment: "Settings and model management presentation; no change to stored identities.")
    }
    static var retrying: String {
        IOSAppLanguage.shared.localized(localized: "vocello.settings.polish.retrying", defaultValue: "Retrying",
               comment: "Settings and model management presentation; no change to stored identities.")
    }
    static var verifying: String {
        IOSAppLanguage.shared.localized(localized: "vocello.settings.polish.verifying", defaultValue: "Verifying",
               comment: "Settings and model management presentation; no change to stored identities.")
    }
    static var installing: String {
        IOSAppLanguage.shared.localized(localized: "vocello.settings.polish.installing", defaultValue: "Installing",
               comment: "Settings and model management presentation; no change to stored identities.")
    }
    static var cancelling: String {
        IOSAppLanguage.shared.localized(localized: "vocello.settings.polish.cancelling", defaultValue: "Cancelling",
               comment: "Settings and model management presentation; no change to stored identities.")
    }
    static var removing: String {
        IOSAppLanguage.shared.localized(localized: "vocello.settings.polish.removing", defaultValue: "Removing",
               comment: "Settings and model management presentation; no change to stored identities.")
    }
    static var severalGB: String {
        IOSAppLanguage.shared.localized(localized: "vocello.settings.polish.severalGB", defaultValue: "several GB",
               comment: "Settings and model management presentation; no change to stored identities.")
    }
    static var onDeviceModel: String {
        IOSAppLanguage.shared.localized(localized: "vocello.settings.polish.onDeviceModel", defaultValue: "On-device model",
               comment: "Settings and model management presentation; no change to stored identities.")
    }
    static var on: String {
        IOSAppLanguage.shared.localized(localized: "vocello.settings.polish.on", defaultValue: "On",
               comment: "Settings and model management presentation; no change to stored identities.")
    }
    static var off: String {
        IOSAppLanguage.shared.localized(localized: "vocello.settings.polish.off", defaultValue: "Off",
               comment: "Settings and model management presentation; no change to stored identities.")
    }
    static func storageUsed(_ value: String) -> String {
        IOSAppLanguage.shared.format(IOSAppLanguage.shared.localized(localized: "vocello.settings.polish.storageUsed",
            defaultValue: "%@ used", comment: "Settings formatted presentation; preserve all substitutions."), value)
    }
    static func modelStatus(_ value: String) -> String {
        IOSAppLanguage.shared.format(IOSAppLanguage.shared.localized(localized: "vocello.settings.polish.modelStatus",
            defaultValue: "%@ model status", comment: "Settings formatted presentation; preserve all substitutions."), value)
    }
    static func modelAction(_ first: String, _ second: String) -> String {
        IOSAppLanguage.shared.format(IOSAppLanguage.shared.localized(localized: "vocello.settings.polish.modelAction",
            defaultValue: "%1$@ %2$@ model", comment: "Settings formatted presentation; preserve all substitutions."), first, second)
    }
    static func modelProgress(_ value: String) -> String {
        IOSAppLanguage.shared.format(IOSAppLanguage.shared.localized(localized: "vocello.settings.polish.modelProgress",
            defaultValue: "%@ model download progress", comment: "Settings formatted presentation; preserve all substitutions."), value)
    }
    static func modelSetup(_ value: String) -> String {
        IOSAppLanguage.shared.format(IOSAppLanguage.shared.localized(localized: "vocello.settings.polish.modelSetup",
            defaultValue: "%@ model setup in progress", comment: "Settings formatted presentation; preserve all substitutions."), value)
    }
    static func modeName(_ mode: GenerationMode) -> String {
        switch mode {
        case .custom: builtIn
        case .design: design
        case .clone: clone
        }
    }

    static var title: String { IOSAppLanguage.shared.localized(localized: "vocello.settings.polish.title", defaultValue: "Settings") }
    static var modelsIntro: String { IOSAppLanguage.shared.localized(localized: "vocello.settings.polish.modelsIntro", defaultValue: "Manage your voice models and where finished audio is saved.") }
    static var accessibilityIntro: String { IOSAppLanguage.shared.localized(localized: "vocello.settings.polish.accessibilityIntro", defaultValue: "Adapt Vocello’s interface to your accessibility preferences.") }
    static var tagline: String { IOSAppLanguage.shared.localized(localized: "vocello.settings.polish.tagline", defaultValue: "Your voice, locally.") }
    static func versionIdentity(_ version: String, build: String) -> String {
        IOSAppLanguage.shared.format(IOSAppLanguage.shared.localized(localized: "vocello.settings.polish.versionIdentity",
            defaultValue: "Version %1$@ (%2$@)", comment: "Installed app version and build; never hardcode release numbers."), version, build)
    }

    static func variationName(_ variation: Qwen3SamplingVariation) -> String {
        switch variation {
        case .expressive: IOSAppLanguage.shared.localized(localized: "vocello.settings.polish.expressive", defaultValue: "Expressive")
        case .balanced: IOSAppLanguage.shared.localized(localized: "vocello.settings.polish.balanced", defaultValue: "Balanced")
        case .consistent: IOSAppLanguage.shared.localized(localized: "vocello.settings.polish.consistent", defaultValue: "Consistent")
        }
    }
    static var audio: String {
        IOSAppLanguage.shared.localized(localized: "vocello.settings.refinement.audio", defaultValue: "Audio",
               comment: "Settings audio; preserve product and consent meaning.")
    }
    static var audioSummary: String {
        IOSAppLanguage.shared.localized(localized: "vocello.settings.refinement.audioSummary", defaultValue: "Playback and take variation",
               comment: "Settings audioSummary; preserve product and consent meaning.")
    }
    static var modelsFiles: String {
        IOSAppLanguage.shared.localized(localized: "vocello.settings.refinement.modelsFiles", defaultValue: "Models & Files",
               comment: "Settings modelsFiles; preserve product and consent meaning.")
    }
    static var modelsFilesSummary: String {
        IOSAppLanguage.shared.localized(localized: "vocello.settings.refinement.modelsFilesSummary", defaultValue: "Voice models and saved outputs",
               comment: "Settings modelsFilesSummary; preserve product and consent meaning.")
    }
    static var privacyPermissions: String {
        IOSAppLanguage.shared.localized(localized: "vocello.settings.refinement.privacyPermissions", defaultValue: "Privacy & Permissions",
               comment: "Settings privacyPermissions; preserve product and consent meaning.")
    }
    static var privacyPermissionsSummary: String {
        IOSAppLanguage.shared.localized(localized: "vocello.settings.refinement.privacyPermissionsSummary", defaultValue: "Voice consent and permissions",
               comment: "Settings privacyPermissionsSummary; preserve product and consent meaning.")
    }
    static var accessibility: String {
        IOSAppLanguage.shared.localized(localized: "vocello.settings.refinement.accessibility", defaultValue: "Accessibility",
               comment: "Settings accessibility; preserve product and consent meaning.")
    }
    static var accessibilitySummary: String {
        IOSAppLanguage.shared.localized(localized: "vocello.settings.refinement.accessibilitySummary", defaultValue: "Motion and transparency",
               comment: "Settings accessibilitySummary; preserve product and consent meaning.")
    }
    static var about: String {
        IOSAppLanguage.shared.localized(localized: "vocello.settings.refinement.about", defaultValue: "About",
               comment: "Settings about; preserve product and consent meaning.")
    }
    static var aboutSummary: String {
        IOSAppLanguage.shared.localized(localized: "vocello.settings.refinement.aboutSummary", defaultValue: "Support and app information",
               comment: "Settings aboutSummary; preserve product and consent meaning.")
    }
    static var back: String {
        IOSAppLanguage.shared.localized(localized: "vocello.settings.refinement.back", defaultValue: "Back to Settings",
               comment: "Settings back; preserve product and consent meaning.")
    }
    static var backModelsFiles: String {
        IOSAppLanguage.shared.localized(localized: "vocello.settings.refinement.backModelsFiles", defaultValue: "Back to Models & Files",
               comment: "Settings backModelsFiles; preserve product and consent meaning.")
    }
    static var backAbout: String {
        IOSAppLanguage.shared.localized(localized: "vocello.settings.refinement.backAbout", defaultValue: "Back to About",
               comment: "Settings backAbout; preserve product and consent meaning.")
    }
    static var historyOnly: String {
        IOSAppLanguage.shared.localized(localized: "vocello.settings.refinement.historyOnly", defaultValue: "History only",
               comment: "Settings historyOnly; preserve product and consent meaning.")
    }
    static var autoPlay: String {
        IOSAppLanguage.shared.localized(localized: "vocello.settings.refinement.autoPlay", defaultValue: "Play generated audio",
               comment: "Settings autoPlay; preserve product and consent meaning.")
    }
    static var autoPlayDetail: String {
        IOSAppLanguage.shared.localized(localized: "vocello.settings.refinement.autoPlayDetail", defaultValue: "Automatically play each finished take.",
               comment: "Settings autoPlayDetail; preserve product and consent meaning.")
    }
    static var voiceModels: String {
        IOSAppLanguage.shared.localized(localized: "vocello.settings.refinement.voiceModels", defaultValue: "Voice Models",
               comment: "Settings voiceModels; preserve product and consent meaning.")
    }
    static var voiceModelsDetail: String {
        IOSAppLanguage.shared.localized(localized: "vocello.settings.refinement.voiceModelsDetail", defaultValue: "One private model per Studio mode.",
               comment: "Settings voiceModelsDetail; preserve product and consent meaning.")
    }
    static var voiceModelsHint: String {
        IOSAppLanguage.shared.localized(localized: "vocello.settings.refinement.voiceModelsHint", defaultValue: "Opens Voice Models",
               comment: "Settings voiceModelsHint; preserve product and consent meaning.")
    }
    static var savedOutputs: String {
        IOSAppLanguage.shared.localized(localized: "vocello.settings.refinement.savedOutputs", defaultValue: "Saved outputs",
               comment: "Settings savedOutputs; preserve product and consent meaning.")
    }
    static var savedOutputsDetail: String {
        IOSAppLanguage.shared.localized(localized: "vocello.settings.refinement.savedOutputsDetail", defaultValue: "History or a folder in Files.",
               comment: "Settings savedOutputsDetail; preserve product and consent meaning.")
    }
    static var savedOutputsHint: String {
        IOSAppLanguage.shared.localized(localized: "vocello.settings.refinement.savedOutputsHint", defaultValue: "Opens saved output options",
               comment: "Settings savedOutputsHint; preserve product and consent meaning.")
    }
    static var keepInHistory: String {
        IOSAppLanguage.shared.localized(localized: "vocello.settings.refinement.keepInHistory", defaultValue: "Keep in History",
               comment: "Settings keepInHistory; preserve product and consent meaning.")
    }
    static var chooseFolder: String {
        IOSAppLanguage.shared.localized(localized: "vocello.settings.refinement.chooseFolder", defaultValue: "Choose Files folder…",
               comment: "Settings chooseFolder; preserve product and consent meaning.")
    }
    static var reduceMotion: String {
        IOSAppLanguage.shared.localized(localized: "vocello.settings.refinement.reduceMotion", defaultValue: "Reduce Motion",
               comment: "Settings reduceMotion; preserve product and consent meaning.")
    }
    static var reduceMotionDetail: String {
        IOSAppLanguage.shared.localized(localized: "vocello.settings.refinement.reduceMotionDetail", defaultValue: "Use simpler transitions and movement.",
               comment: "Settings reduceMotionDetail; preserve product and consent meaning.")
    }
    static var reduceTransparency: String {
        IOSAppLanguage.shared.localized(localized: "vocello.settings.refinement.reduceTransparency", defaultValue: "Reduce Transparency",
               comment: "Settings reduceTransparency; preserve product and consent meaning.")
    }
    static var reduceTransparencyDetail: String {
        IOSAppLanguage.shared.localized(localized: "vocello.settings.refinement.reduceTransparencyDetail", defaultValue: "Use more opaque navigation surfaces.",
               comment: "Settings reduceTransparencyDetail; preserve product and consent meaning.")
    }
    static var cloneConsent: String {
        IOSAppLanguage.shared.localized(localized: "vocello.settings.refinement.cloneConsent", defaultValue: "I own or have permission to clone the voices I use",
               comment: "Settings cloneConsent; preserve product and consent meaning.")
    }
    static var cloneConsentDetail: String {
        IOSAppLanguage.shared.localized(localized: "vocello.settings.refinement.cloneConsentDetail", defaultValue: "Required for Voice Cloning.",
               comment: "Settings cloneConsentDetail; preserve product and consent meaning.")
    }
    static var cloneDisclosure: String {
        IOSAppLanguage.shared.localized(localized: "vocello.settings.refinement.cloneDisclosure", defaultValue: "If you publish audio of a cloned real voice, disclose that it is AI-generated. EU law may require this.",
               comment: "Settings cloneDisclosure; preserve product and consent meaning.")
    }
    static var cloneDisclosureHint: String {
        IOSAppLanguage.shared.localized(localized: "vocello.settings.refinement.cloneDisclosureHint", defaultValue: "AI-generated audio disclosure. If you publish audio of a cloned real voice, disclose that it is AI-generated. EU law may require this.",
               comment: "Settings cloneDisclosureHint; preserve product and consent meaning.")
    }
    static var privacyHint: String {
        IOSAppLanguage.shared.localized(localized: "vocello.settings.refinement.privacyHint", defaultValue: "Opens the Vocello Privacy Policy",
               comment: "Settings privacyHint; preserve product and consent meaning.")
    }
    static var permissions: String {
        IOSAppLanguage.shared.localized(localized: "vocello.settings.refinement.permissions", defaultValue: "Permissions",
               comment: "Settings permissions; preserve product and consent meaning.")
    }
    static var permissionsDetail: String {
        IOSAppLanguage.shared.localized(localized: "vocello.settings.refinement.permissionsDetail", defaultValue: "Microphone and speech recognition.",
               comment: "Settings permissionsDetail; preserve product and consent meaning.")
    }
    static var systemSettings: String {
        IOSAppLanguage.shared.localized(localized: "vocello.settings.refinement.systemSettings", defaultValue: "iOS Settings",
               comment: "Settings systemSettings; preserve product and consent meaning.")
    }
    static var permissionsHint: String {
        IOSAppLanguage.shared.localized(localized: "vocello.settings.refinement.permissionsHint", defaultValue: "Leaves Vocello and opens iOS Settings",
               comment: "Settings permissionsHint; preserve product and consent meaning.")
    }
    static var variation: String {
        IOSAppLanguage.shared.localized(localized: "vocello.settings.refinement.variation", defaultValue: "Take variation",
               comment: "Settings variation; preserve product and consent meaning.")
    }
    static var variationDetail: String {
        IOSAppLanguage.shared.localized(localized: "vocello.settings.refinement.variationDetail", defaultValue: "Choose how much finished takes vary.",
               comment: "Settings variationDetail; preserve product and consent meaning.")
    }
    static var variationHint: String {
        IOSAppLanguage.shared.localized(localized: "vocello.settings.refinement.variationHint", defaultValue: "Choose Expressive, Balanced, or Consistent",
               comment: "Settings variationHint; preserve product and consent meaning.")
    }
    static var version: String {
        IOSAppLanguage.shared.localized(localized: "vocello.settings.refinement.version", defaultValue: "Version",
               comment: "Settings version; preserve product and consent meaning.")
    }
    static func modelsReady(_ ready: Int, total: Int) -> String {
        IOSAppLanguage.shared.format(IOSAppLanguage.shared.localized(localized: "vocello.settings.refinement.modelsReady",
            defaultValue: "%d of %d ready", comment: "Installed model count out of total available models."), ready, total)
    }
}

@MainActor enum IOSSettingsCategory: String, CaseIterable {
    case audio, appLanguage, modelsFiles, privacyPermissions, accessibility, about
    var title: String {
        switch self {
        case .audio: IOSSettingsText.audio
        case .appLanguage: IOSSettingsText.appLanguage
        case .modelsFiles: IOSSettingsText.modelsFiles
        case .privacyPermissions: IOSSettingsText.privacyPermissions
        case .accessibility: IOSSettingsText.accessibility
        case .about: IOSSettingsText.about
        }
    }
    var subtitle: String {
        switch self {
        case .audio: IOSSettingsText.audioSummary
        case .appLanguage: IOSSettingsText.appLanguageDetail
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
        case .appLanguage: "globe"
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
    @Environment(\.iosDockHeight) private var dockHeight
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
                                .background(Theme.Surface.panelMuted, in: Circle())
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
                .padding(.bottom, max(IOSStudioShellMetrics.dockFadeHeight, dockHeight) + Theme.Spacing.lg)
            }
        }
        .toolbar(.hidden, for: .navigationBar)
    }
}


/// Compact Settings hub using the existing tab shell and grouped destinations.
struct SettingsScreen: View {
    @Environment(\.iosDockHeight) private var dockHeight
    @Environment(\.dynamicTypeSize) private var dynamicTypeSize
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
                    Text(IOSSettingsText.title)
                        .font(.headline)
                        .foregroundStyle(Theme.Text.primary)
                        .accessibilityAddTraits(.isHeader)
                        .accessibilityIdentifier("iosSettings_title")
                    IOSSettingsSection {
                        categoryLink(.audio) { audioSection }
                        IOSSettingsDivider()
                        categoryLink(.appLanguage) { appLanguageSection }
                        IOSSettingsDivider()
                        NavigationLink(value: IOSSettingsModelNavigation.Destination.modelsAndFiles) {
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
                .padding(.bottom, max(IOSStudioShellMetrics.dockFadeHeight, dockHeight) + Theme.Spacing.lg)
            }
        }
        .toolbar(.hidden, for: .navigationBar)
        .sheet(isPresented: $isExportPurchasePresented) { IOSExportPurchaseSheet() }
        .navigationDestination(for: IOSSettingsModelNavigation.Destination.self) { destination in
            switch destination {
            case .modelsAndFiles: modelsAndFilesDestination
            case .voiceModels: VoiceModelsScreen()
            }
        }
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
                                 subtitle: category.subtitle,
                                 value: category == .appLanguage ? selectedLanguageName : "")
    }

    private var selectedLanguageName: String {
        IOSUILanguage(rawValue: IOSAppLanguage.shared.selection)?.nativeName ?? IOSSettingsText.systemLanguage
    }

    private var appLanguageSection: some View {
        IOSSettingsSection {
            appLanguageOption(IOSAppLanguage.system, name: IOSSettingsText.systemLanguage)
            ForEach(IOSAppLanguage.shared.availableLanguages, id: \.rawValue) { language in
                IOSSettingsDivider()
                appLanguageOption(language.rawValue, name: language.nativeName)
            }
        }
    }

    private func appLanguageOption(_ identifier: String, name: String) -> some View {
        let selected = IOSAppLanguage.shared.selection == identifier
        let layout = dynamicTypeSize.isAccessibilitySize
            ? AnyLayout(VStackLayout(alignment: .leading, spacing: 6))
            : AnyLayout(HStackLayout())
        return Button { IOSAppLanguage.shared.select(identifier) } label: {
            layout {
                Text(verbatim: name)
                    .fixedSize(horizontal: false, vertical: true)
                Spacer(minLength: Theme.Spacing.sm)
                if selected { Image(systemName: "checkmark").accessibilityHidden(true) }
            }
            .font(.body)
            .foregroundStyle(Theme.Text.primary)
            .frame(maxWidth: .infinity, minHeight: 44, alignment: .leading)
            .contentShape(Rectangle())
            .padding(Theme.Spacing.md)
        }
        .buttonStyle(.plain)
        .accessibilityLabel(name)
        .accessibilityAddTraits(selected ? [.isSelected] : [])
        .accessibilityIdentifier("iosSettings_appLanguageOption_\(identifier)")
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
            Text(IOSAppLanguage.shared.presentation.exportFolderDetail)
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
                title: IOSAppLanguage.shared.presentation.exportUnlockTitle,
                subtitle: exportSummary,
                value: "",
                tint: Theme.Brand.gold
                )
            }
            .buttonStyle(.plain)
            .accessibilityIdentifier("iosSettings_exportPurchaseRow")
            .accessibilityLabel(IOSAppLanguage.shared.presentation.exportUnlockTitle)
            .accessibilityValue(exportSummary)
            .accessibilityHint(IOSAppLanguage.shared.presentation.exportOptionsHint)
        }
    }

    private var exportSummary: String {
        switch IOSExportCommerce.shared.access {
        case .unlocked: IOSAppLanguage.shared.presentation.exportUnlocked
        case .checking: IOSAppLanguage.shared.presentation.exportChecking
        case .locked: IOSAppLanguage.shared.presentation.exportRootSummary
        }
    }

    private var modelsAndFilesSection: some View {
        VStack(alignment: .leading, spacing: Theme.Spacing.md) {
            contextNote(IOSSettingsText.modelsIntro)
            IOSSettingsSection {
                NavigationLink(value: IOSSettingsModelNavigation.Destination.voiceModels) {
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
    }

    private var accessibilitySection: some View {
        VStack(alignment: .leading, spacing: Theme.Spacing.md) {
            contextNote(IOSSettingsText.accessibilityIntro)
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
    }

    private var privacySection: some View {
        VStack(alignment: .leading, spacing: Theme.Spacing.md) {
            IOSSettingsSection {
                IOSSettingsToggleRow(
                    symbol: "hand.raised.fill",
                    title: IOSSettingsText.cloneConsent,
                    subtitle: IOSSettingsText.cloneConsentDetail,
                    accessibilityIdentifier: "voiceCloning_consentAcknowledgment",
                    isOn: $cloneConsentAcknowledged,
                    tint: Theme.Brand.modeClone
                )
            }

            contextNote(IOSSettingsText.cloneDisclosure)
                .accessibilityLabel(IOSSettingsText.cloneDisclosureHint)

            IOSSettingsSection {
                IOSSettingsValueRow(
                    symbol: "hand.raised.fill",
                    title: IOSAppLanguage.shared.presentation.exportPrivacy,
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
    }

    private var aboutSection: some View {
        VStack(alignment: .leading, spacing: Theme.Spacing.lg) {
            VStack(alignment: .leading, spacing: Theme.Spacing.xs) {
                Text(Theme.Branding.productName)
                    .font(.title3.weight(.semibold))
                    .foregroundStyle(Theme.Text.primary)
                    .accessibilityAddTraits(.isHeader)
                contextNote(IOSSettingsText.tagline)
                IOSSettingsVersionRow()
            }
            IOSSettingsSection {
                IOSSettingsValueRow(
                    symbol: "questionmark.circle.fill",
                    title: IOSAppLanguage.shared.localized(localized: "vocello.settings.help_support"),
                    subtitle: IOSAppLanguage.shared.localized(localized: "vocello.settings.help_support.subtitle"),
                    accessibilityIdentifier: "iosSettings_supportRow",
                    value: "",
                    accessibilityHint: IOSAppLanguage.shared.localized(localized: "vocello.settings.help_support.hint"),
                    action: { open("https://vocello.vercel.app/support/") }
                )

                IOSSettingsDivider()
                NavigationLink {
                    OpenSourceLicensesScreen()
                } label: {
                    IOSSettingsNavigationRow(
                        symbol: "chevron.left.forwardslash.chevron.right",
                        title: IOSAppLanguage.shared.localized(localized: "vocello.settings.open_source_licenses"),
                        subtitle: nil,
                        value: ""
                    )
                }
                .buttonStyle(.plain)
                .accessibilityIdentifier("iosSettings_openSourceRow")
                .accessibilityLabel(IOSAppLanguage.shared.localized(localized: "vocello.settings.open_source_licenses"))
                .accessibilityValue(IOSAppLanguage.shared.localized(localized: "vocello.settings.on_device"))
                .accessibilityHint(IOSAppLanguage.shared.localized(localized: "vocello.settings.open_source_licenses.hint"))

                IOSSettingsDivider()
                IOSSettingsValueRow(
                    symbol: "chevron.left.forwardslash.chevron.right",
                    title: IOSAppLanguage.shared.localized(localized: "vocello.settings.source_code"),
                    subtitle: nil,
                    accessibilityIdentifier: "iosSettings_sourceCodeRow",
                    value: "",
                    accessibilityHint: IOSAppLanguage.shared.localized(localized: "vocello.settings.source_code.hint"),
                    action: { open("https://github.com/PowerBeef/Vocello") }
                )

            }
        }
    }

    private func contextNote(_ text: String) -> some View {
        Text(text)
            .font(.footnote)
            .foregroundStyle(Theme.Text.secondary)
            .fixedSize(horizontal: false, vertical: true)
    }

    private func effectiveStatus(for model: TTSModel) -> ModelManagerViewModel.ModelStatus {
        modelManager.statuses[model.id] ?? .checking
    }

    private func open(_ urlString: String) {
        guard let url = URL(string: urlString) else { return }
        openURL(url)
    }
}
