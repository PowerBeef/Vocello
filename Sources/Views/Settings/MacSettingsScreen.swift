import AppKit
import QwenVoiceCore
import SwiftUI

/// Shared Settings overview with desktop-owned detail controls. Both the sidebar and
/// Cmd+, scene host this view; Studio installation links still target the exact model row.
struct MacSettingsScreen: View {
    @Environment(ModelManagerViewModel.self) private var viewModel
    /// Mode-keyed deep-link target: when the sidebar redirects to Settings
    /// because a mode's model is missing, the shell sets this so the models
    /// section scrolls to and flashes that mode's row.
    @Binding var highlightedMode: GenerationMode?
    private let showsNavigationTitle: Bool

    @AppStorage("autoPlay", store: AppDefaults.store) private var autoPlay = true
    @AppStorage("vocello.voiceCloningConsent.v1", store: AppDefaults.store)
    private var cloneConsentAcknowledged = false
    @AppStorage("outputDirectory", store: AppDefaults.store) private var outputDirectory = ""
    @AppStorage(GenerationVariationPreference.key, store: AppDefaults.store)
    private var generationVariation = GenerationVariationPreference.defaultValue

    private enum Category: String {
        case audio, appLanguage, modelsFiles, cloning
    }

    @State private var selectedCategory: Category?
    private var settingsText: VocelloPresentationText {
        VocelloPresentationText(localization: MacInterfaceLanguage.current)
    }

    @State private var flashedMode: GenerationMode?
    @State private var flashResetTask: Task<Void, Never>?
    @State private var modelToDelete: TTSModel?
    @State private var showDeleteConfirmation = false
    /// Non-nil when the configured output folder is missing or unwritable
    /// (`AudioService` falls back to the default outputs folder).
    @State private var outputDirectoryIssue: String?

    private let contentMaxWidth: CGFloat = 680

    init(highlightedMode: Binding<GenerationMode?>, showsNavigationTitle: Bool = true) {
        _highlightedMode = highlightedMode
        self.showsNavigationTitle = showsNavigationTitle
        _selectedCategory = State(initialValue: highlightedMode.wrappedValue == nil ? nil : .modelsFiles)
    }

    var body: some View {
        ScrollViewReader { proxy in
            ScrollView {
                VStack(alignment: .leading, spacing: MacTheme.Spacing.xl) {
                    if let selectedCategory {
                        detailHeader(selectedCategory)
                        switch selectedCategory {
                        case .audio:
                            playbackSection
                            generationSection
                        case .appLanguage:
                            interfaceSection
                        case .modelsFiles:
                            performanceSection
                            modelsSection.onAppear { focusHighlighted(using: proxy) }
                            storageSection
                        case .cloning:
                            cloningSection
                        }
                    } else {
                        overview
                    }
                }
                .frame(maxWidth: contentMaxWidth)
                .frame(maxWidth: .infinity)
                .padding(.horizontal, MacTheme.Spacing.xl)
                .padding(.vertical, MacTheme.Spacing.xl)
            }
            .id(selectedCategory)
            .settingsNavigationTitle(showsNavigationTitle)
            .accessibilityIdentifier("screen_settings")
            .task {
                outputDirectoryIssue = AudioService.configuredOutputDirectoryIssue()
                await viewModel.refresh()
                focusHighlighted(using: proxy)
            }
            .onChange(of: highlightedMode) { _, mode in
                guard mode != nil else { return }
                if selectedCategory == .modelsFiles {
                    focusHighlighted(using: proxy)
                } else {
                    selectedCategory = .modelsFiles
                }
            }
            .onChange(of: outputDirectory) { _, _ in
                outputDirectoryIssue = AudioService.configuredOutputDirectoryIssue()
            }
            .onReceive(NotificationCenter.default.publisher(for: NSApplication.didBecomeActiveNotification)) { _ in
                // The folder may have been deleted or restored while the user was away.
                outputDirectoryIssue = AudioService.configuredOutputDirectoryIssue()
            }
            .onDisappear {
                flashResetTask?.cancel()
                flashResetTask = nil
            }
        }
        .alert(MacInterfaceText.settingsDeleteModelTitle, isPresented: $showDeleteConfirmation) {
            Button(MacInterfaceText.cancel, role: .cancel) { modelToDelete = nil }
            Button(MacInterfaceText.delete, role: .destructive) {
                if let model = modelToDelete {
                    Task { await viewModel.delete(model) }
                }
                modelToDelete = nil
            }
        } message: {
            if let model = modelToDelete {
                Text(deleteMessage(for: model))
            }
        }
    }

    private var overview: some View {
        VStack(alignment: .leading, spacing: MacTheme.Spacing.lg) {
            MacSettingsSection {
                categoryButton(.audio, symbol: "waveform", subtitle: settingsText.settingsAudioSummary)
                MacSettingsDivider()
                categoryButton(.appLanguage, symbol: "globe", subtitle: selectedLanguageName)
                MacSettingsDivider()
                categoryButton(.modelsFiles, symbol: "internaldrive", subtitle: viewModel.modelSetupSummary().text)
            }
            MacSettingsSection {
                categoryButton(.cloning, symbol: "waveform.badge.mic", subtitle: MacInterfaceText.settingsCloneConsentDetail)
            }
            Text(appVersion)
                .macType(.caption)
                .foregroundStyle(MacTheme.Text.tertiary)
        }
    }

    private var selectedLanguageName: String {
        IOSUILanguage(rawValue: MacInterfaceLanguage.selection)?.nativeName ?? MacInterfaceText.settingsSystemLanguage
    }

    private func categoryTitle(_ category: Category) -> String {
        switch category {
        case .audio: settingsText.settingsAudio
        case .appLanguage: MacInterfaceText.settingsAppLanguage
        case .modelsFiles: settingsText.settingsModelsFiles
        case .cloning: MacInterfaceText.settingsVoiceCloning
        }
    }

    private func categoryButton(_ category: Category, symbol: String, subtitle: String) -> some View {
        Button { selectedCategory = category } label: {
            VocelloSettingsNavigationRow(
                symbol: symbol, title: categoryTitle(category), subtitle: subtitle,
                titleFont: .system(size: MacType.style(.rowTitle).size, weight: .semibold),
                detailFont: .system(size: MacType.style(.rowMeta).size), verticalInset: 10
            )
        }
        .buttonStyle(.plain)
        .accessibilityIdentifier("settings_category_\(category.rawValue)")
        .accessibilityLabel(categoryTitle(category))
        .accessibilityValue(subtitle)
    }

    private func detailHeader(_ category: Category) -> some View {
        HStack(spacing: MacTheme.Spacing.sm) {
            Button { selectedCategory = nil } label: {
                Image(systemName: "chevron.left")
                    .macType(.buttonLabel)
                    .frame(width: 30, height: 30)
                    .background(MacTheme.Surface.panelMuted, in: Circle())
            }
            .buttonStyle(.plain)
            .accessibilityLabel(settingsText.settingsBack)
            .accessibilityIdentifier("settings_backButton")
            Text(categoryTitle(category))
                .macType(.screenTitle)
                .accessibilityAddTraits(.isHeader)
                .accessibilityIdentifier("settings_detail_\(category.rawValue)")
        }
    }

    // MARK: - Sections

    private var modelsSection: some View {
        MacSettingsSection(title: MacInterfaceText.settingsModelDownloads) {
            MacModelSetupSummaryRow()

            ForEach(GenerationMode.allCases, id: \.self) { mode in
                MacSettingsDivider()
                MacModelModeRow(
                    mode: mode,
                    isFlashed: flashedMode == mode,
                    onDelete: { model in request(delete: model) }
                )
                .id(mode.rawValue)
            }
        }
    }

    private var interfaceSection: some View {
        MacSettingsSection(title: MacInterfaceText.settingsInterface) {
            MacSettingsRow(symbol: "globe", title: MacInterfaceText.settingsAppLanguage) {
                MacSettingsDetailText(MacInterfaceText.settingsAppLanguageDetail)
            } trailing: {
                Picker(MacInterfaceText.settingsAppLanguage, selection: appLanguageSelection) {
                    Text(MacInterfaceText.settingsSystemLanguage)
                        .tag(IOSAppLanguage.system)
                        .accessibilityIdentifier("settings_appLanguageOption_system")
                    ForEach(MacInterfaceLanguage.availableLanguages, id: \.rawValue) { language in
                        Text(language.nativeName)
                            .tag(language.rawValue)
                            .accessibilityIdentifier("settings_appLanguageOption_\(language.rawValue)")
                    }
                }
                .pickerStyle(.menu)
                .labelsHidden()
                .frame(width: 200)
                .accessibilityIdentifier("settings_appLanguage")
            }
        }
    }

    private var appLanguageSelection: Binding<String> {
        Binding(
            get: { MacInterfaceLanguage.selection },
            set: { MacInterfaceLanguage.select($0) }
        )
    }

    private var playbackSection: some View {
        MacSettingsSection(title: MacInterfaceText.settingsPlayback) {
            MacSettingsToggleRow(
                symbol: "play.circle",
                title: MacInterfaceText.settingsAutoPlay,
                subtitle: MacInterfaceText.settingsAutoPlayDetail,
                accessibilityIdentifier: "preferences_autoPlayToggle",
                isOn: $autoPlay
            )
        }
    }

    private var generationSection: some View {
        MacSettingsSection(title: MacInterfaceText.settingsGeneration) {
            MacSettingsRow(symbol: "dial.medium", title: MacInterfaceText.settingsVariation) {
                MacSettingsDetailText(MacInterfaceText.settingsVariationHelp)

                Picker(MacInterfaceText.settingsVariation, selection: $generationVariation) {
                    ForEach(Qwen3SamplingVariation.allCases, id: \.rawValue) { variation in
                        Text(MacInterfaceText.settingsVariationName(variation)).tag(variation.rawValue)
                    }
                }
                .pickerStyle(.segmented)
                .labelsHidden()
                .tint(MacTheme.accent)
                .frame(maxWidth: 360)
                .padding(.top, MacTheme.Spacing.xs)
                .accessibilityIdentifier("settings_generationVariation")
                .accessibilityLabel(MacInterfaceText.settingsVariation)
            } trailing: {
                EmptyView()
            }
        }
    }

    /// When on, a generation mode without an explicit package choice uses its
    /// Speed package; `ModelManagerViewModel` owns the preference and the
    /// resolution order.
    private var prefersLowerMemoryModels: Binding<Bool> {
        Binding(
            get: { viewModel.prefersLowerMemoryModels },
            set: { viewModel.setPrefersLowerMemoryModels($0) }
        )
    }

    private var performanceSection: some View {
        MacSettingsSection(title: MacInterfaceText.settingsPerformance) {
            MacSettingsToggleRow(
                symbol: "memorychip",
                title: MacInterfaceText.settingsPreferLowerMemory,
                subtitle: MacInterfaceText.settingsPreferLowerMemoryDetail,
                accessibilityIdentifier: "settings_preferSpeedEverywhere",
                isOn: prefersLowerMemoryModels
            )
        }
    }

    private var storageSection: some View {
        MacSettingsSection(title: MacInterfaceText.settingsStorage) {
            MacSettingsRow(symbol: "folder", title: MacInterfaceText.settingsOutputDirectory) {
                HStack(spacing: MacTheme.Spacing.tight) {
                    if outputDirectoryIssue != nil {
                        Image(systemName: "exclamationmark.triangle.fill")
                            .macType(.rowMeta)
                            .foregroundStyle(MacTheme.Status.guarded)
                            .help(outputDirectoryIssue ?? "")
                            .accessibilityIdentifier("preferences_outputDirectoryWarning")
                    }
                    Text(outputDirectorySummary)
                        .macType(.rowMeta)
                        .foregroundStyle(MacTheme.Text.secondary)
                        .lineLimit(1)
                        .truncationMode(.middle)
                        .accessibilityIdentifier("preferences_outputDirectory")
                }
                if let outputDirectoryIssue {
                    MacSettingsDetailText(outputDirectoryIssue, color: MacTheme.Status.guarded)
                        .accessibilityIdentifier("preferences_outputDirectoryIssue")
                }
            } trailing: {
                Button(MacInterfaceText.settingsChoose) { browseForOutputDirectory() }
                    .buttonStyle(MacSettingsActionButtonStyle(tint: MacTheme.accent))
                    .accessibilityIdentifier("preferences_browseButton")
                if !outputDirectory.isEmpty {
                    Button(MacInterfaceText.settingsReset) { outputDirectory = "" }
                        .buttonStyle(MacSettingsActionButtonStyle(tint: MacTheme.Brand.silver))
                        .accessibilityIdentifier("preferences_outputResetButton")
                }
            }

            MacSettingsDivider()

            // The version caption lives here; the About box (Vocello →
            // About Vocello) covers full version detail in the standard spot.
            MacSettingsRow(symbol: "internaldrive", title: MacInterfaceText.settingsApplicationData) {
                Text(appVersion)
                    .macType(.counter)
                    .foregroundStyle(MacTheme.Text.secondary)
            } trailing: {
                Button(MacInterfaceText.revealInFinder) {
                    NSWorkspace.shared.open(QwenVoiceApp.appSupportDir)
                }
                .buttonStyle(MacSettingsActionButtonStyle(tint: MacTheme.accent))
                .accessibilityIdentifier("preferences_openFinderButton")
            }
        }
    }

    /// Last, not first: the persistent record of the one-time acknowledgment
    /// (also offered inline in the cloning flow), a policy row.
    private var cloningSection: some View {
        MacSettingsSection(title: MacInterfaceText.settingsVoiceCloning, accent: MacTheme.Brand.modeClone) {
            MacSettingsToggleRow(
                symbol: MacTheme.modeGlyph(for: .clone),
                title: MacInterfaceText.settingsCloneConsent,
                subtitle: MacInterfaceText.settingsCloneConsentDetail,
                // CP-1 option D: the users' own EU AI Act Article 50(4)
                // disclosure duty, beside the rights gate.
                footnote: MacInterfaceText.settingsCloneDisclosure,
                accessibilityIdentifier: "voiceCloning_consentAcknowledgment",
                isOn: $cloneConsentAcknowledged,
                tint: MacTheme.Brand.modeClone
            )
        }
    }

    // MARK: - Actions

    private func request(delete model: TTSModel) {
        modelToDelete = model
        showDeleteConfirmation = true
    }

    private func deleteMessage(for model: TTSModel) -> String {
        let variant = viewModel.activeVariantLabel(for: model)
        let status = viewModel.statuses[model.id]
        let sizeText: String = {
            switch status {
            case .downloaded(let sizeBytes), .updateAvailable(let sizeBytes, _):
                guard sizeBytes > 0 else { return "" }
                let size = ByteCountFormatter.string(fromByteCount: Int64(sizeBytes), countStyle: .file)
                return " (\(size))"
            default:
                return ""
            }
        }()
        return MacInterfaceText.settingsDeleteModelMessage(MacInterfaceText.modeName(model.mode), variant, sizeText)
    }

    private var outputDirectorySummary: String {
        if outputDirectory.isEmpty { return MacInterfaceText.settingsOutputDefault }
        return outputDirectory
    }

    private func browseForOutputDirectory() {
        let panel = NSOpenPanel()
        panel.canChooseDirectories = true
        panel.canChooseFiles = false
        if panel.runModal() == .OK, let url = panel.url {
            outputDirectory = url.path
        }
    }

    private var appVersion: String {
        let dict = Bundle.main.infoDictionary ?? [:]
        let version = dict["CFBundleShortVersionString"] as? String ?? "?"
        let build = dict["CFBundleVersion"] as? String ?? "?"
        return "\(version) (\(build))"
    }

    private func focusHighlighted(using proxy: ScrollViewProxy) {
        guard let mode = highlightedMode else { return }
        AppLaunchConfiguration.performAnimated(MacTheme.Motion.easeOut) {
            proxy.scrollTo(mode.rawValue, anchor: .center)
        }
        flashedMode = mode
        highlightedMode = nil

        flashResetTask?.cancel()
        flashResetTask = Task {
            try? await Task.sleep(for: .seconds(2))
            guard !Task.isCancelled else { return }
            if flashedMode == mode { flashedMode = nil }
        }
    }
}

private extension View {
    @ViewBuilder
    func settingsNavigationTitle(_ isVisible: Bool) -> some View {
        if isVisible {
            navigationTitle(MacInterfaceText.settingsTitle)
        } else {
            self
        }
    }
}
