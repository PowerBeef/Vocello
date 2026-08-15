import QwenVoiceCore
import QwenVoiceNative
import SwiftUI

struct VoiceDesignView: View {
    @Binding private var draft: VoiceDesignDraft
    @State private var coordinator = VoiceDesignCoordinator()
    /// Language detected from the typed script; floats the matching language
    /// to a "Recommended" section in the language picker.
    @State private var detectedPromptLanguage: Qwen3SupportedLanguage = .auto

    private let ttsEngineStore: TTSEngineStore
    private var modelManager: ModelManagerViewModel
    private let audioPlayer: AudioPlayerViewModel
    private let savedVoicesViewModel: SavedVoicesViewModel

    private var activeMode: GenerationMode {
        .design
    }

    private var activeModel: TTSModel? {
        modelManager.generationActiveVariant(for: activeMode)
    }

    private var isModelAvailable: Bool {
        guard let activeModel else { return false }
        return modelManager.isAvailable(activeModel)
    }

    private var modelDisplayName: String {
        activeModel.map(modelManager.generationVariantDisplayName) ?? "Unknown"
    }

    private var canGenerate: Bool {
        GenerationEnginePresentation.allowsGenerationStart(
            snapshot: ttsEngineStore.snapshot,
            activeModelID: activeModel?.id,
            isModelAvailable: isModelAvailable,
            hasScriptContent: draft.hasText && draft.hasVoiceDescription,
            isUserGenerating: coordinator.isGenerating,
            hasActiveGeneration: ttsEngineStore.hasActiveGeneration
        )
    }

    private var canRunBatch: Bool {
        ttsEngineStore.isReady
            && isModelAvailable
            && draft.hasVoiceDescription
            && !ttsEngineStore.hasActiveGeneration
    }

    private var isGenerationActive: Bool {
        coordinator.isGenerating || ttsEngineStore.hasActiveGeneration
    }

    private var currentSavedVoiceCandidate: VoiceDesignSavedVoiceCandidate? {
        coordinator.currentSavedVoiceCandidate(for: draft)
    }

    init(
        draft: Binding<VoiceDesignDraft>,
        ttsEngineStore: TTSEngineStore,
        audioPlayer: AudioPlayerViewModel,
        modelManager: ModelManagerViewModel,
        savedVoicesViewModel: SavedVoicesViewModel
    ) {
        _draft = draft
        self.ttsEngineStore = ttsEngineStore
        self.modelManager = modelManager
        self.audioPlayer = audioPlayer
        self.savedVoicesViewModel = savedVoicesViewModel
    }

    var body: some View {
        PageScaffold(
            accessibilityIdentifier: "screen_voiceDesign",
            fillsViewportHeight: true,
            contentSpacing: LayoutConstants.generationSectionSpacing,
            contentMaxWidth: LayoutConstants.generationContentMaxWidth,
            topPadding: LayoutConstants.generationPageTopPadding,
            bottomPadding: LayoutConstants.generationPageBottomPadding
        ) {
            configurationPanel
            composerPanel
                .layoutPriority(1)
        }
        .modeGlassTint(AppTheme.voiceDesign)
        .modeCanvasBackdrop(AppTheme.voiceDesign)
        .onAppear(perform: reconcileGenerationVariantSelection)
        .onAppear { detectedPromptLanguage = PromptLanguageDetector.detect(draft.text) }
        .onChange(of: draft.text) { _, newText in
            let detected = PromptLanguageDetector.detect(newText)
            if detected != detectedPromptLanguage {
                detectedPromptLanguage = detected
            }
        }
        .onChange(of: modelManager.statuses) { _, _ in reconcileGenerationVariantSelection() }
        .onChange(of: modelManager.activeVariantRevision) { _, _ in reconcileGenerationVariantSelection() }
        .sheet(item: $coordinator.presentedSheet) { presentedSheet in
            switch presentedSheet {
            case .batch(let configuration):
                BatchGenerationSheet(
                    mode: configuration.mode,
                    voice: configuration.voice,
                    emotion: configuration.emotion,
                    languageHint: draft.selectedLanguage.rawValue,
                    voiceDescription: configuration.voiceDescription,
                    refAudio: configuration.refAudio,
                    refText: configuration.refText,
                    initialText: configuration.initialText,
                    initialSegmentationMode: configuration.initialSegmentationMode
                )
                .environment(ttsEngineStore)
                .environmentObject(audioPlayer)
            case .saveVoice(let configuration):
                SavedVoiceSheet(configuration: configuration) { voice in
                    coordinator.handleSavedVoice(
                        voice,
                        draft: draft,
                        savedVoicesViewModel: savedVoicesViewModel,
                        ttsEngineStore: ttsEngineStore
                    )
                }
                .environment(ttsEngineStore)
            }
        }
        .alert(item: $coordinator.actionAlert) { alert in
            Alert(
                title: Text(alert.title),
                message: Text(alert.message),
                dismissButton: .default(Text("OK"))
            )
        }
    }

    func reconcileGenerationVariantSelection() {
        modelManager.reconcileGenerationVariantSelectionIfNeeded(for: activeMode)
    }
}

// MARK: - Subviews

private extension VoiceDesignView {
    var configurationPanel: some View {
        CompactConfigurationSection(
            title: "Configuration",
            iconName: "slider.horizontal.3",
            accentColor: AppTheme.voiceDesign,
            trailingText: nil,
            trailingAccessory: AnyView(variantSelector),
            rowSpacing: LayoutConstants.generationConfigurationRowSpacing,
            panelPadding: LayoutConstants.generationConfigurationPanelPadding
        ) {
            VStack(alignment: .leading, spacing: 0) {
                briefSettings
                languageAndDeliverySettings
            }
        }
        .fixedSize(horizontal: false, vertical: true)
    }

    var variantSelector: some View {
        GenerationVariantSelector(
            mode: activeMode,
            modelManager: modelManager,
            accentColor: AppTheme.voiceDesign,
            accessibilityPrefix: "voiceDesign",
            isDisabled: isGenerationActive
        )
    }

    var composerPanel: some View {
        StudioSectionCard(
            title: "Script",
            iconName: "text.alignleft",
            accentColor: AppTheme.voiceDesign,
            trailingText: isGenerationActive ? "Generating" : (canGenerate ? "Ready" : nil),
            fillsAvailableHeight: true,
            accessibilityIdentifier: "voiceDesign_script"
        ) {
            VStack(alignment: .leading, spacing: LayoutConstants.generationConfigurationRowSpacing) {
                TextInputView(
                    text: $draft.text,
                    isGenerating: isGenerationActive,
                    placeholder: "Type or paste your script",
                    buttonColor: AppTheme.voiceDesign,
                    batchAction: { coordinator.presentBatch(draft: draft) },
                    batchDisabled: !canRunBatch,
                    generateDisabled: !ttsEngineStore.isReady
                        || !isModelAvailable
                        || !draft.hasVoiceDescription
                        || ttsEngineStore.hasActiveGeneration,
                    isEmbedded: true,
                    usesFlexibleEmbeddedHeight: true,
                    onGenerate: {
                        coordinator.generate(
                            draft: draft,
                            activeModel: activeModel,
                            isModelAvailable: isModelAvailable,
                            ttsEngineStore: ttsEngineStore,
                            audioPlayer: audioPlayer,
                            modelManager: modelManager
                        )
                    },
                    onCancel: {
                        coordinator.cancelGeneration(
                            ttsEngineStore: ttsEngineStore,
                            audioPlayer: audioPlayer
                        )
                    },
                    pinnedSeed: $draft.pinnedSeed
                )

                composerFooter
            }
            .frame(maxHeight: .infinity, alignment: .topLeading)
        }
        .frame(maxHeight: .infinity, alignment: .topLeading)
        .accessibilityElement(children: .contain)
    }

    var briefSettings: some View {
        VoiceDesignBriefSettings(voiceDescription: $draft.voiceDescription)
    }

    /// One merged line: Language + Delivery + Intensity columns share the
    /// row (Custom tone spans full width below, inside the delivery
    /// controls) — mirrors the Built-in Voice panel.
    var languageAndDeliverySettings: some View {
        // Empty-label setup row: joins the same left rail as the Voice brief
        // control instead of hugging the card edge (same grid fix as the
        // Built-in Voice panel).
        GenerationSetupRow(
            label: "",
            accessibilityIdentifier: "voiceDesign_toneSpeed"
        ) {
            DeliveryControlsView(
                emotion: $draft.emotion,
                accentColor: AppTheme.voiceDesign,
                isCompact: true,
                showsLabel: false,
                usesColumnLabels: true,
                leadingColumns: AnyView(languageColumn)
            )
        }
    }

    var languageColumn: some View {
        ConfigurationColumn(
            label: "Language",
            detail: LanguageSelectionPresentation.isFollowingDetection(
                selected: draft.selectedLanguage,
                detected: detectedPromptLanguage
            ) ? "· Auto" : nil
        ) {
            QwenLanguagePicker(
                selectedLanguage: $draft.selectedLanguage,
                accentColor: AppTheme.voiceDesign,
                accessibilityPrefix: "voiceDesign",
                recommended: detectedPromptLanguage
            )
        }
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("voiceDesign_languageSetup")
    }

    var generationReadiness: some View {
        WorkflowReadinessNote(
            isReady: canGenerate && !isGenerationActive,
            title: isGenerationActive ? "Generating final audio" : (canGenerate ? "Ready to generate" : readinessTitle),
            detail: isGenerationActive ? "Rendering the complete take. The file lands in the player when ready." : readinessDetail,
            accentColor: AppTheme.voiceDesign,
            isBusy: isGenerationActive,
            accessibilityIdentifier: "voiceDesign_readiness"
        )
    }

    var readinessTitle: String {
        if !ttsEngineStore.isReady {
            return "Engine starting"
        }
        if !isModelAvailable {
            return "Install the active model"
        }
        if !draft.hasVoiceDescription {
            return "Add a voice brief"
        }
        if !draft.hasText {
            return "Add a script"
        }
        return "Review the take"
    }

    var readinessDetail: String {
        if !ttsEngineStore.isReady {
            return "The engine is still preparing."
        }
        if !isModelAvailable {
            return "Install \(modelDisplayName) in Models to enable generation."
        }
        if !draft.hasVoiceDescription {
            return "Describe the voice before writing the final line."
        }
        if !draft.hasText {
            return "The generated voice uses this brief and delivery once a line is written."
        }
        switch GenerationEnginePresentation.modelWarmPath(
            snapshot: ttsEngineStore.snapshot,
            activeModelID: activeModel?.id
        ) {
        case .modelCold:
            return GenerationEnginePresentation.coldStartDetail()
        case .modelWarming, .modelActivePrep:
            return "Preparing Voice Design. You can generate now; preparation finishes in the background."
        default:
            return "Ready to generate and save."
        }
    }

    var composerFooter: some View {
        VStack(alignment: .leading, spacing: LayoutConstants.compactGap) {
            generationReadiness
            saveVoiceAction

            if let errorMessage = coordinator.errorMessage {
                Label(errorMessage, systemImage: "exclamationmark.triangle")
                    .foregroundColor(.red)
                    .font(.callout)
            }
        }
        .frame(
            maxWidth: .infinity,
            minHeight: LayoutConstants.generationComposerFooterMinHeight,
            alignment: .topLeading
        )
    }

    @ViewBuilder
    var saveVoiceAction: some View {
        if let candidate = currentSavedVoiceCandidate {
            if candidate.isSaved {
                Label("Saved to Saved Voices", systemImage: "checkmark.circle.fill")
                    .font(.callout.weight(.medium))
                    .foregroundStyle(.secondary)
                    .accessibilityIdentifier("voiceDesign_saveVoiceCompleted")
                    .accessibilityValue(candidate.savedVoiceName ?? "")
            } else {
                Button {
                    coordinator.presentSavedVoiceSheet(for: draft)
                } label: {
                    Label("Save to Saved Voices", systemImage: "person.crop.circle.badge.plus")
                }
                .buttonStyle(.bordered)
                .controlSize(.small)
                .accessibilityIdentifier("voiceDesign_saveVoiceButton")
            }
        }
    }
}

// MARK: - Voice Design Brief Settings

private struct VoiceDesignBriefSettings: View {
    @Binding var voiceDescription: String

    var body: some View {
        GenerationSetupRow(
            label: "Voice brief",
            accessibilityIdentifier: "voiceDesign_voiceSetup"
        ) {
            VoiceBriefEditor(
                text: $voiceDescription,
                accentColor: AppTheme.voiceDesign,
                accessibilityIdentifier: "voiceDesign_voiceDescriptionField"
            )
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .accessibilityValue(voiceDescription)
    }
}
