import AppKit
import QwenVoiceCore
import SwiftUI

/// Built-in Voice on the iOS Studio canvas (`IOSCustomVoiceView`): the
/// composer, the Voice / Delivery / Language chips (menus on the desktop),
/// the pinned-seed and batch chips, the readiness line, and the dock with the
/// Generate CTA, the generating bar or the player card. Generation runs on
/// the shared pipeline: `StudioGenerationCoordinator` (owned by
/// `MacAppModel`), a request from `MacStudioGenerationRequestFactory`, and
/// `IOSSingleTakeGenerationExecutor` with the macOS hooks. Long scripts and
/// the Batch chip open the batch sheet, as before. Every `customVoice_*`,
/// `textInput_*` and `delivery_*` identifier is the lane contract.
struct MacCustomVoiceScreen: View {
    @EnvironmentObject private var ttsEngineStore: TTSEngineStore
    @EnvironmentObject private var audioPlayer: AudioPlayerViewModel
    @Environment(ModelManagerViewModel.self) private var modelManager
    @Environment(MacAppModel.self) private var appModel

    @Binding var draft: CustomVoiceDraft

    @State private var detectedPromptLanguage: Qwen3SupportedLanguage = .auto
    @State private var presentedSheet: CustomVoicePresentedSheet?
    @State private var deliverySelection = MacDeliverySelection()

    private let tint = MacTheme.Brand.modeCustom

    private var coordinator: StudioGenerationCoordinator { appModel.customCoordinator }

    // MARK: - Derived state

    private var activeModel: TTSModel? {
        modelManager.generationActiveVariant(for: .custom)
    }

    private var isModelAvailable: Bool {
        guard let activeModel else { return false }
        return modelManager.isAvailable(activeModel)
    }

    private var modelDisplayName: String {
        activeModel.map { modelManager.generationVariantDisplayName(for: $0) } ?? MacInterfaceText.workflowNoModel
    }

    private var supportsDeliveryControl: Bool {
        activeModel?.supportsInstructionControl ?? false
    }

    private var speakerDisplayName: String {
        TTSModel.speakerDescriptor(id: draft.selectedSpeaker)?.displayName ?? draft.selectedSpeaker.capitalized
    }

    private var speakerNativeLanguage: Qwen3SupportedLanguage {
        TTSModel.qwenLanguage(forSpeaker: draft.selectedSpeaker)
    }

    private var effectiveLanguage: Qwen3SupportedLanguage {
        LanguageSelectionPresentation.effective(selected: draft.selectedLanguage, detected: detectedPromptLanguage)
    }

    private var languageHintMessage: String? {
        // Judge the effective language (the detected one while the selector
        // follows Auto) so the native-speaker hint fires before any manual pick.
        guard effectiveLanguage != .auto, effectiveLanguage != speakerNativeLanguage else { return nil }
        return MacInterfaceText.customSpeakerNativeLanguageHint(
            speakerDisplayName, speakerNativeLanguage.displayName, effectiveLanguage.displayName
        )
    }

    private var isGenerationActive: Bool {
        coordinator.isGenerating || ttsEngineStore.hasActiveGeneration
    }

    private var studioGenState: MacStudioGenState {
        if coordinator.isGenerating {
            // The live card appears once the shared player is actually
            // streaming audible audio; the compact bar covers prepare/buffering.
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

    private var readinessPresentation: CustomVoiceReadinessPresentation {
        CustomVoiceReadinessPresentation.resolve(
            snapshot: ttsEngineStore.snapshot,
            activeModelID: activeModel?.id,
            isModelAvailable: isModelAvailable,
            hasText: draft.hasText,
            isGenerating: isGenerationActive,
            modelDisplayName: modelDisplayName
        )
    }

    private var canGenerate: Bool {
        GenerationEnginePresentation.allowsGenerationStart(
            snapshot: ttsEngineStore.snapshot,
            activeModelID: activeModel?.id,
            isModelAvailable: isModelAvailable,
            hasScriptContent: draft.hasText,
            isUserGenerating: coordinator.isGenerating,
            hasActiveGeneration: ttsEngineStore.hasActiveGeneration
        )
    }

    private var canRunBatch: Bool {
        ttsEngineStore.isReady && isModelAvailable && !ttsEngineStore.hasActiveGeneration
    }

    private var modeMetaLabel: String {
        var parts = [MacInterfaceText.modeName(.custom)]
        if let activeModel {
            parts.append(modelManager.generationVariantDisplayName(for: activeModel))
        }
        return parts.joined(separator: " · ")
    }

    // MARK: - Body

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            header
            MacStudioCanvas(
                mode: .custom,
                accessibilityPrefix: "customVoice",
                script: $draft.text,
                placeholder: MacInterfaceText.textInputPlaceholder,
                modeMetaLabel: modeMetaLabel,
                tint: tint,
                genState: studioGenState,
                errorMessage: coordinator.errorMessage,
                canGenerate: canGenerate,
                modelInstalled: isModelAvailable,
                setupChips: { setupChips },
                footer: { chipFooter },
                onGenerate: generate,
                onCancel: cancelGeneration,
                onInstallModel: openSettingsForModel,
                onPlayerDismiss: { coordinator.dismissInlinePlayer() }
            )
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
        .background(MacTheme.canvasGradient.ignoresSafeArea())
        .accessibilityIdentifier("screen_customVoice")
        .onAppear {
            reconcileGenerationVariantSelection()
            deliverySelection = MacDeliverySelection.synced(from: draft.emotion)
        }
        .task(id: draft.text) {
            // Debounced: the detector loads a language recognizer per call, so it
            // never runs per keystroke.
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
            }
        }
    }

    private var header: some View {
        HStack(alignment: .center, spacing: 12) {
            Image(systemName: MacTheme.modeGlyph(for: .custom))
                .font(.system(size: 15, weight: .semibold))
                .foregroundStyle(tint)
                .frame(width: MacShellMetrics.sidebarGlyphTile, height: MacShellMetrics.sidebarGlyphTile)
                .background {
                    RoundedRectangle(cornerRadius: MacShellMetrics.sidebarGlyphTileRadius, style: .continuous)
                        .fill(tint.opacity(0.16))
                }
                .accessibilityHidden(true)

            Text(MacInterfaceText.menuBuiltInVoice)
                .font(.title3.weight(.semibold))
                .foregroundStyle(MacTheme.Text.primary)
                .lineLimit(1)

            Spacer(minLength: 12)

            MacGenerationVariantSelector(
                mode: .custom,
                tint: tint,
                accessibilityPrefix: "customVoice",
                isDisabled: isGenerationActive
            )
        }
        .padding(.horizontal, MacStudioMetrics.horizontalInset)
        .padding(.top, 16)
        .padding(.bottom, 4)
        .frame(maxWidth: MacStudioMetrics.contentMaxWidth)
        .frame(maxWidth: .infinity)
        // Keeps the variant selector's identifiers under the screen identifier.
        .accessibilityElement(children: .contain)
    }

    // MARK: - Chips

    @ViewBuilder
    private var setupChips: some View {
        MacStudioChipContainer(accessibilityIdentifier: "customVoice_voiceSetup") { speakerChip }
        if supportsDeliveryControl {
            MacStudioChipContainer(accessibilityIdentifier: "customVoice_toneSpeed") {
                MacStudioDeliveryChip(
                    selection: $deliverySelection,
                    emotion: $draft.emotion,
                    tint: tint
                )
            }
        }
        MacStudioChipContainer(accessibilityIdentifier: "customVoice_languageSetup") {
            MacStudioLanguageChip(
                selectedLanguage: $draft.selectedLanguage,
                detectedLanguage: detectedPromptLanguage,
                tint: tint,
                accessibilityIdentifier: "customVoice_languagePicker"
            )
        }
        MacSeedPinChip(pinnedSeed: $draft.pinnedSeed, tint: tint)
        MacStudioBatchChip(tint: tint, isEnabled: canRunBatch) {
            presentedSheet = .batch(.custom(draft: draft, model: activeModel))
        }
    }

    private var recommendedSpeakers: [String] {
        guard detectedPromptLanguage != .auto else { return [] }
        return TTSModel.allSpeakers.filter { TTSModel.qwenLanguage(forSpeaker: $0) == detectedPromptLanguage }
    }

    private var speakerChip: some View {
        MacStudioSetupChip(
            eyebrow: MacInterfaceText.customSpeaker,
            value: speakerDisplayName,
            leadingSymbol: "person.wave.2.fill",
            tint: tint,
            accessibilityIdentifier: "customVoice_speakerPicker",
            accessibilityValue: TTSModel.speakerPickerLabel(for: draft.selectedSpeaker)
        ) {
            if !recommendedSpeakers.isEmpty {
                Section(MacInterfaceText.recommendedForScript) {
                    ForEach(recommendedSpeakers, id: \.self) { speaker in
                        speakerRow(speaker)
                    }
                }
                Section(MacInterfaceText.customAllSpeakers) {
                    ForEach(TTSModel.allSpeakers.filter { !recommendedSpeakers.contains($0) }, id: \.self) { speaker in
                        speakerRow(speaker)
                    }
                }
            } else {
                ForEach(TTSModel.allSpeakers, id: \.self) { speaker in
                    speakerRow(speaker)
                }
            }
        }
    }

    /// One checkable menu row; macOS renders Menu `Toggle`s as checkmarked
    /// items and the setter only ever selects.
    private func speakerRow(_ speaker: String) -> some View {
        Toggle(
            TTSModel.speakerPickerLabel(for: speaker),
            isOn: Binding(
                get: { draft.selectedSpeaker == speaker },
                set: { _ in draft.selectedSpeaker = speaker }
            )
        )
    }

    // MARK: - Footer rows under the chips

    @ViewBuilder
    private var chipFooter: some View {
        if supportsDeliveryControl {
            MacStudioDeliveryFooter(
                selection: $deliverySelection,
                emotion: $draft.emotion,
                tint: tint
            )
        } else {
            Label(MacInterfaceText.customDeliveryUnsupported, systemImage: "slider.horizontal.3")
                .font(.caption2)
                .foregroundStyle(MacTheme.Text.secondary)
                .accessibilityIdentifier("customVoice_deliveryUnsupported")
        }
        if let languageHintMessage {
            Label(languageHintMessage, systemImage: "globe")
                .font(.caption2)
                .foregroundStyle(MacTheme.Text.secondary)
                .fixedSize(horizontal: false, vertical: true)
                .accessibilityIdentifier("customVoice_languageHint")
        }
        HStack(alignment: .top, spacing: 12) {
            MacStudioReadinessNote(
                isReady: readinessPresentation.isReady,
                title: readinessPresentation.title,
                detail: readinessPresentation.detail,
                tint: tint,
                isBusy: readinessPresentation.isBusy,
                accessibilityIdentifier: "customVoice_readiness"
            )
        }
    }

    // MARK: - Actions

    private func reconcileGenerationVariantSelection() {
        modelManager.reconcileGenerationVariantSelectionIfNeeded(for: .custom)
    }

    private func openSettingsForModel() {
        appModel.pendingHighlightedMode = .custom
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
        guard draft.hasText, ttsEngineStore.isReady, !ttsEngineStore.hasActiveGeneration else { return }
        guard !coordinator.isGenerating else { return }
        guard let model = activeModel else { return }
        guard isModelAvailable else {
            coordinator.rejectStart(modelManager.recoveryDetail(for: model))
            return
        }
        if LongTextGenerationRouter.shouldRouteToLongFormBatch(draft.text) {
            presentedSheet = .batch(.custom(draft: draft, model: model, initialText: draft.text, initialSegmentationMode: .longForm))
            return
        }

        let text = draft.text
        let speaker = draft.selectedSpeaker
        let voiceName = speakerDisplayName
        let modeLabel = MacInterfaceText.modeName(.custom)
        // Same seed for the live and final card so the decorative waveform keeps its shape.
        let waveformSeed = MacStableVisualHash.int(text)
        guard let attempt = coordinator.start(live: IOSStudioLivePreviewItem(
            voiceName: voiceName,
            modeLabel: modeLabel,
            mode: .custom,
            transcript: text,
            waveformSeed: waveformSeed,
            estimatedAudioDuration: LivePreviewEstimate(text: text)?.estimatedAudioDuration ?? 0
        )) else { return }

        let request = MacStudioGenerationRequestFactory.customVoice(
            modelID: model.id,
            text: text,
            outputPath: makeOutputPath(subfolder: model.outputSubfolder, text: text),
            language: draft.selectedLanguage,
            speakerID: speaker,
            deliveryStyle: model.supportsInstructionControl ? draft.emotion : nil,
            deliveryInstructionCellID: draft.resolvedDeliveryProfile.instructionCellID,
            seed: draft.pinnedSeed,
            variation: GenerationVariationPreference.requestValue()
        )
        let historyEmotion = model.supportsInstructionControl ? draft.emotion : nil
        let hooks = MacStudioSingleTakeGenerationHooks(engine: ttsEngineStore, audioPlayer: audioPlayer)
        let coordinator = coordinator
        let task = Task { @MainActor in
            defer { coordinator.finish(attempt: attempt) }
            do {
                let plan = try IOSSingleTakeGenerationPlan(
                    request: request,
                    modelTier: model.tier,
                    historyVoice: speaker,
                    historyEmotion: historyEmotion,
                    displayVoiceName: voiceName,
                    modeLabel: modeLabel,
                    waveformSeed: waveformSeed,
                    persistenceCaller: "MacCustomVoiceScreen"
                )
                let result = try await IOSSingleTakeGenerationExecutor.run(plan: plan, hooks: hooks)
                coordinator.complete(hooks.inlinePlayerItem(for: result, plan: plan), attempt: attempt)
            } catch is CancellationError {
                // The shared executor owns cancellation cleanup and telemetry.
            } catch {
                coordinator.fail(error.localizedDescription, attempt: attempt)
            }
        }
        coordinator.installGenerationTask(task, for: attempt)
    }
}

/// Readiness copy of the Built-in Voice screen, resolved from the engine
/// snapshot, the active package and the draft (unchanged from the legacy screen).
struct CustomVoiceReadinessPresentation: Equatable {
    let isReady: Bool
    let title: String
    let detail: String
    let trailingText: String?
    let isBusy: Bool

    static func resolve(
        snapshot: TTSEngineSnapshot,
        activeModelID: String?,
        isModelAvailable: Bool,
        hasText: Bool,
        isGenerating: Bool,
        modelDisplayName: String
    ) -> CustomVoiceReadinessPresentation {
        if isGenerating {
            return CustomVoiceReadinessPresentation(
                isReady: false,
                title: MacInterfaceText.customGeneratingFinalAudio,
                detail: MacInterfaceText.customGeneratingFinalAudioDetail,
                trailingText: MacInterfaceText.statusGenerating,
                isBusy: true
            )
        }

        guard snapshot.isReady else {
            return CustomVoiceReadinessPresentation(
                isReady: false,
                title: MacInterfaceText.readinessEngineStarting,
                detail: MacInterfaceText.readinessEngineStartingDetail,
                trailingText: nil,
                isBusy: snapshot.loadState == .starting
            )
        }

        guard isModelAvailable else {
            return CustomVoiceReadinessPresentation(
                isReady: false,
                title: MacInterfaceText.readinessInstallActiveModel,
                detail: MacInterfaceText.readinessInstallActiveModelDetail(modelDisplayName),
                trailingText: nil,
                isBusy: false
            )
        }

        guard hasText else {
            return CustomVoiceReadinessPresentation(
                isReady: false,
                title: MacInterfaceText.readinessAddScript,
                detail: MacInterfaceText.customAddScriptDetail,
                trailingText: nil,
                isBusy: false
            )
        }

        switch GenerationEnginePresentation.modelWarmPath(snapshot: snapshot, activeModelID: activeModelID) {
        case .modelReady:
            return CustomVoiceReadinessPresentation(
                isReady: true,
                title: MacInterfaceText.readinessReadyToGenerate,
                detail: MacInterfaceText.customReadyDetail,
                trailingText: MacInterfaceText.statusReady,
                isBusy: false
            )
        case .modelCold:
            return CustomVoiceReadinessPresentation(
                isReady: true,
                title: MacInterfaceText.readinessReadyToGenerate,
                detail: GenerationEnginePresentation.coldStartDetail(),
                trailingText: MacInterfaceText.statusReady,
                isBusy: false
            )
        case .modelWarming, .modelActivePrep:
            return CustomVoiceReadinessPresentation(
                isReady: true,
                title: MacInterfaceText.customPreparing,
                detail: MacInterfaceText.customPreparingDetail,
                trailingText: MacInterfaceText.statusPreparing,
                isBusy: true
            )
        case .engineBusy:
            return CustomVoiceReadinessPresentation(
                isReady: false,
                title: MacInterfaceText.customEngineBusy,
                detail: MacInterfaceText.customEngineBusyDetail,
                trailingText: nil,
                isBusy: true
            )
        case .modelMismatch:
            return CustomVoiceReadinessPresentation(
                isReady: true,
                title: MacInterfaceText.readinessReadyToGenerate,
                detail: MacInterfaceText.customModelMismatchDetail,
                trailingText: MacInterfaceText.statusReady,
                isBusy: false
            )
        case .failed(let message):
            return CustomVoiceReadinessPresentation(
                isReady: false,
                title: MacInterfaceText.customEngineNeedsAttention,
                detail: message,
                trailingText: nil,
                isBusy: false
            )
        case .engineUnavailable:
            return CustomVoiceReadinessPresentation(
                isReady: false,
                title: MacInterfaceText.readinessEngineStarting,
                detail: MacInterfaceText.readinessEngineStartingDetail,
                trailingText: nil,
                isBusy: snapshot.loadState == .starting
            )
        }
    }
}
