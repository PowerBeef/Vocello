import AppKit
import QwenVoiceCore
import SwiftUI

private struct VoiceDesignActionAlert: Identifiable {
    let id = UUID()
    let title: String
    let message: String
}

/// Voice Design on the iOS Studio canvas (`IOSVoiceDesignView`): the brief
/// editor behind a setup chip, the Delivery and Language chips, the pinned-seed and
/// line-by-line toggle, the readiness line, the save-as-voice action for the last
/// take, and the dock. Generation runs on the shared pipeline: the Design
/// request from `MacStudioGenerationRequestFactory` goes to
/// `MacStudioGenerationActions` as an immutable plan. Every
/// `voiceDesign_*`, `textInput_*` and `delivery_*` identifier is the lane
/// contract.
struct MacVoiceDesignScreen: View {
    @EnvironmentObject private var ttsEngineStore: TTSEngineStore
    @EnvironmentObject private var audioPlayer: AudioPlayerViewModel
    @EnvironmentObject private var savedVoicesViewModel: SavedVoicesViewModel
    @Environment(ModelManagerViewModel.self) private var modelManager
    @Environment(MacAppModel.self) private var appModel

    @Binding var draft: VoiceDesignDraft

    @State private var lineByLine = false
    @State private var detectedPromptLanguage: Qwen3SupportedLanguage = .auto
    @State private var presentedSheet: VoiceDesignPresentedSheet?
    private var promptContentLanguage: Qwen3SupportedLanguage {
        StudioPromptContent.language(
            selected: draft.selectedLanguage,
            detected: detectedPromptLanguage,
            interfaceLanguage: MacInterfaceLanguage.current.language ?? "en"
        )
    }

    @State private var deliverySelection = MacDeliverySelection()
    @State private var actionAlert: VoiceDesignActionAlert?
    @State private var isBriefPresented = false

    private let tint = MacTheme.Brand.modeDesign

    private var coordinator: StudioGenerationCoordinator { appModel.designCoordinator }

    // MARK: - Derived state

    private var activeModel: TTSModel? {
        modelManager.generationActiveVariant(for: .design)
    }

    private var isModelAvailable: Bool {
        guard let activeModel else { return false }
        return modelManager.isAvailable(activeModel)
    }

    private var modelDisplayName: String {
        activeModel.map { modelManager.generationVariantDisplayName(for: $0) } ?? MacInterfaceText.workflowNoModel
    }

    private var isGenerationActive: Bool {
        coordinator.isGenerating || ttsEngineStore.hasActiveGeneration
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
        ttsEngineStore.isReady && isModelAvailable && draft.hasVoiceDescription && !ttsEngineStore.hasActiveGeneration
    }

    /// Held beside the coordinator on the shell model so the take and its
    /// save affordance survive leaving and returning to the screen together.
    private var currentSavedVoiceCandidate: VoiceDesignSavedVoiceCandidate? {
        guard let candidate = appModel.designSavedVoiceCandidate, candidate.matches(draft: draft) else { return nil }
        return candidate
    }

    private var saveVoiceHandler: (() -> Void)? {
        guard let candidate = currentSavedVoiceCandidate, !candidate.isSaved else { return nil }
        return { presentSavedVoiceSheet(for: candidate) }
    }

    private var briefDisplayName: String {
        let trimmed = draft.voiceDescription.trimmingCharacters(in: .whitespacesAndNewlines)
        return trimmed.isEmpty ? MacInterfaceText.designVoiceBriefLabel : trimmed
    }

    private var studioGenState: MacStudioGenState {
        if coordinator.isGenerating {
            if audioPlayer.isLiveStream,
               audioPlayer.activeGeneratePreviewVisibilityState == .ready,
               let live = coordinator.liveItem {
                return .live(live)
            }
            return .generating
        }
        if let output = coordinator.lastCompletedOutput { return .complete(output) }
        return .idle
    }

    /// The phone's meta line names the mode and nothing else; the package is
    /// the toolbar's Speed/Quality switch, and the readiness caption follows.
    private var modeMetaLabel: String {
        MacInterfaceText.modeName(.design)
    }

    // MARK: - Readiness

    private var readinessIsReady: Bool { canGenerate && !isGenerationActive }

    private var readinessTitle: String {
        if isGenerationActive { return MacInterfaceText.customGeneratingFinalAudio }
        if canGenerate { return MacInterfaceText.readinessReadyToGenerate }
        if !ttsEngineStore.isReady { return MacInterfaceText.readinessEngineStarting }
        if !isModelAvailable { return MacInterfaceText.readinessInstallActiveModel }
        if !draft.hasVoiceDescription { return MacInterfaceText.designAddVoiceBrief }
        if !draft.hasText { return MacInterfaceText.readinessAddScript }
        return MacInterfaceText.designReviewTake
    }

    private var readinessDetail: String {
        if isGenerationActive { return MacInterfaceText.customGeneratingFinalAudioDetail }
        if !ttsEngineStore.isReady { return MacInterfaceText.readinessEngineStartingDetail }
        if !isModelAvailable { return MacInterfaceText.readinessInstallActiveModelDetail(modelDisplayName) }
        if !draft.hasVoiceDescription { return MacInterfaceText.designDescribeVoiceDetail }
        if !draft.hasText { return MacInterfaceText.designBriefUsedDetail }
        switch GenerationEnginePresentation.modelWarmPath(snapshot: ttsEngineStore.snapshot, activeModelID: activeModel?.id) {
        case .modelCold:
            return GenerationEnginePresentation.coldStartDetail()
        case .modelWarming, .modelActivePrep:
            return MacInterfaceText.designPreparingDetail
        default:
            return MacInterfaceText.readinessReadyToGenerateAndSave
        }
    }

    // MARK: - Body

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            MacStudioCanvas(
                mode: .design,
                accessibilityPrefix: "voiceDesign",
                script: $draft.text,
                placeholder: MacInterfaceText.textInputPlaceholder,
                modeMetaLabel: modeMetaLabel,
                readiness: MacStudioReadinessState(
                    isReady: readinessIsReady,
                    title: readinessTitle,
                    detail: readinessDetail,
                    accessibilityIdentifier: "voiceDesign_readiness"
                ),
                tint: tint,
                genState: studioGenState,
                errorMessage: coordinator.errorMessage,
                canGenerate: canGenerate,
                canRunBatch: canRunBatch,
                lineByLine: $lineByLine,
                modelInstalled: isModelAvailable,
                setupChips: { setupChips },
                footer: { chipFooter },
                onGenerate: generate,
                onCancel: cancelGeneration,
                onInstallModel: openSettingsForModel,
                onPlayerDismiss: { coordinator.dismissInlinePlayer() },
                onSaveAsVoice: saveVoiceHandler
            )
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
        .accessibilityIdentifier("screen_voiceDesign")
        .onAppear {
            reconcileGenerationVariantSelection()
            deliverySelection = MacDeliverySelection.synced(from: draft.emotion)
        }
        .task(id: draft.text) {
            try? await Task.sleep(for: .milliseconds(350))
            guard !Task.isCancelled else { return }
            let detected = PromptLanguageDetector.detect(draft.text)
            if detected != detectedPromptLanguage {
                detectedPromptLanguage = detected
            }
        }
        .onChange(of: modelManager.statuses) { _, _ in reconcileGenerationVariantSelection() }
        .onChange(of: modelManager.activeVariantRevision) { _, _ in reconcileGenerationVariantSelection() }
        .sheet(item: $presentedSheet) { presentedSheet in
            switch presentedSheet {
            case .batch(let configuration):
                MacBatchGenerationSheet(configuration: configuration)
                .environmentObject(ttsEngineStore)
                .environmentObject(audioPlayer)
            case .saveVoice(let configuration):
                MacSavedVoiceSheet(configuration: configuration) { voice in
                    handleSavedVoice(voice)
                }
                .environmentObject(ttsEngineStore)
            }
        }
        .alert(item: $actionAlert) { alert in
            Alert(
                title: Text(alert.title),
                message: Text(alert.message),
                dismissButton: .default(Text(MacInterfaceText.ok))
            )
        }
    }


    private var briefChip: some View {
        Button { isBriefPresented = true } label: {
            MacStudioSetupChipPill(
                symbol: "text.bubble.fill",
                eyebrow: MacInterfaceText.designVoiceBriefLabel,
                value: briefDisplayName,
                tint: tint,
                isPlaceholder: !draft.hasVoiceDescription
            )
        }
        .buttonStyle(.plain)
        .vocelloFocusRing(tint, radius: MacStudioChipMetrics.pillHeight / 2)
        .accessibilityLabel(MacInterfaceText.designVoiceBriefLabel)
        .accessibilityValue(draft.voiceDescription)
        .accessibilityIdentifier("studioChip_voiceBrief")
        .popover(isPresented: $isBriefPresented) {
            VStack(alignment: .leading, spacing: MacTheme.Spacing.lg) {
                MacVoiceBriefEditor(text: $draft.voiceDescription, tint: tint, contentLanguage: promptContentLanguage)
                HStack {
                    Spacer()
                    Button(MacInterfaceText.done) { isBriefPresented = false }
                        .keyboardShortcut(.defaultAction)
                        .disabled(!draft.hasVoiceDescription)
                        .accessibilityIdentifier("voiceBrief_confirm")
                }
            }
            .padding(MacTheme.Spacing.xl)
            .frame(width: 480)
            .tint(tint)
            .onExitCommand { isBriefPresented = false }
            .accessibilityElement(children: .contain)
            .accessibilityIdentifier("voiceDesign_voiceSetup")
        }
    }

    // MARK: - Chips

    @ViewBuilder
    private var setupChips: some View {
        briefChip
        MacStudioChipContainer(accessibilityIdentifier: "voiceDesign_toneSpeed") {
            MacStudioDeliveryChip(
                selection: $deliverySelection, emotion: $draft.emotion, tint: tint,
                contentLanguage: promptContentLanguage
            )
        }
        MacStudioChipContainer(accessibilityIdentifier: "voiceDesign_languageSetup") {
            MacStudioLanguageChip(
                selectedLanguage: $draft.selectedLanguage,
                detectedLanguage: detectedPromptLanguage,
                tint: tint,
                accessibilityIdentifier: "voiceDesign_languagePicker"
            )
        }
        MacSeedPinChip(pinnedSeed: $draft.pinnedSeed, tint: tint)
    }

    @ViewBuilder
    private var chipFooter: some View {
        MacStudioDeliveryFooter(
            selection: $deliverySelection, emotion: $draft.emotion, tint: tint,
            contentLanguage: promptContentLanguage
        )
        saveVoiceAction
    }

    @ViewBuilder
    private var saveVoiceAction: some View {
        if let candidate = currentSavedVoiceCandidate {
            if candidate.isSaved {
                Label(MacInterfaceText.designSavedToSavedVoices, systemImage: "checkmark.circle.fill")
                    .macType(.captionEmphasis)
                    .foregroundStyle(MacTheme.Text.secondary)
                    .lineLimit(1)
                    .accessibilityIdentifier("voiceDesign_saveVoiceCompleted")
                    .accessibilityValue(candidate.savedVoiceName ?? "")
            }
        }
    }

    // MARK: - Saved voice

    private func presentSavedVoiceSheet(for candidate: VoiceDesignSavedVoiceCandidate) {
        presentedSheet = .saveVoice(
            .designResult(
                voiceDescription: candidate.voiceDescription,
                audioPath: candidate.audioPath,
                transcript: candidate.transcript
            )
        )
    }

    private func handleSavedVoice(_ voice: Voice) {
        if var candidate = appModel.designSavedVoiceCandidate, candidate.matches(draft: draft) {
            candidate.markSaved(as: voice.name)
            appModel.designSavedVoiceCandidate = candidate
        }
        savedVoicesViewModel.insertOrReplace(voice)
        let store = ttsEngineStore
        let viewModel = savedVoicesViewModel
        Task { @MainActor in
            await viewModel.refresh(using: store)
        }
        actionAlert = VoiceDesignActionAlert(
            title: MacInterfaceText.savedVoiceAddedTitle,
            message: MacInterfaceText.savedVoiceAddedMessage(voice.name)
        )
    }

    // MARK: - Actions

    private func reconcileGenerationVariantSelection() {
        modelManager.reconcileGenerationVariantSelectionIfNeeded(for: .design)
    }

    private func openSettingsForModel() {
        appModel.pendingHighlightedMode = .design
        appModel.selectedItem = .settings
    }

    private func cancelGeneration() {
        MacStudioGenerationActions.cancelGeneration(
            coordinator: coordinator,
            ttsEngine: ttsEngineStore,
            audioPlayer: audioPlayer
        )
    }

    private func generate() {
        guard draft.hasText, draft.hasVoiceDescription, ttsEngineStore.isReady, !ttsEngineStore.hasActiveGeneration else { return }
        guard !coordinator.isGenerating else { return }
        guard let model = activeModel else { return }
        guard isModelAvailable else {
            coordinator.rejectStart(modelManager.recoveryDetail(for: model))
            return
        }
        if let batchMode = LongTextGenerationRouter.batchMode(for: draft.text, lineByLine: lineByLine) {
            presentedSheet = .batch(.design(draft: draft, initialText: draft.text, initialSegmentationMode: batchMode))
            return
        }

        // Capture the whole request before anything suspends: the brief, the
        // delivery and the script the candidate will be matched against.
        let text = draft.text
        let voiceDescription = draft.voiceDescription
        let emotion = draft.emotion
        let request = MacStudioGenerationRequestFactory.voiceDesign(
            modelID: model.id,
            text: text,
            outputPath: makeOutputPath(subfolder: model.outputSubfolder, text: text),
            language: draft.selectedLanguage,
            voiceDescription: voiceDescription,
            deliveryStyle: emotion,
            seed: draft.pinnedSeed,
            variation: GenerationVariationPreference.requestValue()
        )
        let plan: IOSSingleTakeGenerationPlan
        do {
            plan = try IOSSingleTakeGenerationPlan(
                request: request,
                modelTier: model.tier,
                historyVoice: voiceDescription,
                historyEmotion: emotion,
                displayVoiceName: briefDisplayName,
                modeLabel: MacInterfaceText.modeName(.design),
                waveformSeed: VocelloStableVisualHash.int(text),
                persistenceCaller: "MacVoiceDesignScreen"
            )
        } catch {
            coordinator.rejectStart(error.localizedDescription)
            return
        }
        let appModel = appModel
        let started = MacStudioGenerationActions.startSingleTake(
            plan,
            coordinator: coordinator,
            ttsEngine: ttsEngineStore,
            audioPlayer: audioPlayer,
            onCompleted: { result in
                appModel.designSavedVoiceCandidate = VoiceDesignSavedVoiceCandidate(
                    audioPath: result.audioPath,
                    transcript: text,
                    voiceDescription: voiceDescription,
                    emotion: emotion,
                    text: text
                )
            }
        )
        // The task cannot run before this returns, so a new take always
        // replaces the previous candidate before it can publish its own.
        if started {
            appModel.designSavedVoiceCandidate = nil
        }
    }
}
