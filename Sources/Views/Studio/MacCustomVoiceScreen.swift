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
    @State private var isCustomToneMode = false
    @State private var customToneText = ""

    private let tint = MacTheme.Brand.modeCustom
    private let customToneCharacterLimit = GenerationTextLimitPolicy.deliveryInstructionLimit

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

    private var isFollowingDetection: Bool {
        LanguageSelectionPresentation.isFollowingDetection(selected: draft.selectedLanguage, detected: detectedPromptLanguage)
    }

    private var selectedPreset: EmotionPreset? {
        guard !isCustomToneMode else { return nil }
        return EmotionPreset.matchInstruction(draft.emotion.trimmingCharacters(in: .whitespacesAndNewlines))?.preset
            ?? (DeliveryProfile.isNeutralInstruction(draft.emotion) ? EmotionPreset.all.first : nil)
    }

    private var deliveryChipValue: String {
        if isCustomToneMode {
            let trimmed = customToneText.trimmingCharacters(in: .whitespacesAndNewlines)
            return trimmed.isEmpty ? MacInterfaceText.emotionCustom : trimmed
        }
        return selectedPreset?.label ?? draft.emotion
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
            syncDeliveryModeFromDraft()
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
                BatchGenerationSheet(
                    mode: configuration.mode,
                    voice: configuration.voice,
                    emotion: configuration.emotion,
                    languageHint: draft.selectedLanguage.rawValue,
                    deliveryProfile: configuration.deliveryProfile,
                    voiceDescription: configuration.voiceDescription,
                    refAudio: configuration.refAudio,
                    refText: configuration.refText,
                    initialText: configuration.initialText,
                    initialSegmentationMode: configuration.initialSegmentationMode
                )
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
        chipContainer("customVoice_voiceSetup") { speakerChip }
        if supportsDeliveryControl {
            chipContainer("customVoice_toneSpeed") { deliveryChip }
        }
        chipContainer("customVoice_languageSetup") { languageChip }
        MacSeedPinChip(pinnedSeed: $draft.pinnedSeed, tint: tint)
        MacStudioActionChip(
            eyebrow: MacInterfaceText.studioChipBatch,
            value: MacInterfaceText.textInputBatch,
            leadingSymbol: "list.bullet.rectangle",
            tint: tint,
            isEnabled: canRunBatch,
            accessibilityIdentifier: "textInput_batchButton",
            action: { presentedSheet = .batch(.custom(draft: draft)) }
        )
        .frame(maxWidth: 160)
    }

    /// The legacy container identifiers stay on a genuine parent of the chip,
    /// never on the chip's own node, so the picker identifier keeps resolving.
    private func chipContainer<Chip: View>(_ identifier: String, @ViewBuilder chip: () -> Chip) -> some View {
        HStack(spacing: 0) {
            chip()
        }
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier(identifier)
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

    private var deliveryChip: some View {
        MacStudioSetupChip(
            eyebrow: MacInterfaceText.delivery,
            value: deliveryChipValue,
            leadingSymbol: "theatermasks.fill",
            tint: MacTheme.emotionColor(for: selectedPreset?.id, fallback: tint),
            accessibilityIdentifier: "delivery_tonePicker",
            accessibilityValue: draft.emotion
        ) {
            // The measured split (DP-12): distinct deliveries first, directional
            // hints second, so the menu tells the truth about what each half can promise.
            Section(MacInterfaceText.emotionDistinctDeliveries) {
                ForEach(EmotionPreset.all.filter { !$0.isDirectionalHint }) { preset in
                    presetRow(preset)
                }
            }
            Section(MacInterfaceText.emotionDirectionalHints) {
                ForEach(EmotionPreset.all.filter(\.isDirectionalHint)) { preset in
                    presetRow(preset)
                }
            }
            Section {
                Toggle(
                    MacInterfaceText.emotionCustom,
                    isOn: Binding(get: { isCustomToneMode }, set: { _ in enterCustomToneMode() })
                )
            }
        }
    }

    private func presetRow(_ preset: EmotionPreset) -> some View {
        Toggle(
            preset.label,
            isOn: Binding(
                get: { !isCustomToneMode && selectedPreset?.id == preset.id },
                set: { _ in selectPreset(preset) }
            )
        )
    }

    private var languageChip: some View {
        let options = Qwen3SupportedLanguage.allCases
        let recommended: Qwen3SupportedLanguage? = detectedPromptLanguage == .auto ? nil : detectedPromptLanguage
        let label = LanguageSelectionPresentation.buttonLabel(selected: draft.selectedLanguage, detected: detectedPromptLanguage)
        return MacStudioSetupChip(
            eyebrow: isFollowingDetection ? MacInterfaceText.languageAutoDetail : MacInterfaceText.sectionLanguage,
            value: label,
            leadingSymbol: "globe",
            tint: tint,
            accessibilityIdentifier: "customVoice_languagePicker",
            accessibilityValue: isFollowingDetection ? "\(label), auto" : label
        ) {
            if let recommended {
                Section(MacInterfaceText.recommendedForScript) {
                    languageRow(recommended, title: MacInterfaceText.workflowDetectedLanguage(recommended.displayName))
                }
                Section(MacInterfaceText.workflowAllLanguages) {
                    ForEach(options.filter { $0 != recommended }, id: \.self) { language in
                        languageRow(language)
                    }
                }
            } else {
                ForEach(options, id: \.self) { language in
                    languageRow(language)
                }
            }
        }
    }

    private func languageRow(_ language: Qwen3SupportedLanguage, title: String? = nil) -> some View {
        Toggle(
            title ?? language.displayName,
            isOn: Binding(
                get: { draft.selectedLanguage == language },
                set: { _ in draft.selectedLanguage = language }
            )
        )
    }

    // MARK: - Footer rows under the chips

    @ViewBuilder
    private var chipFooter: some View {
        if isCustomToneMode, supportsDeliveryControl {
            customToneField
        }
        if !isCustomToneMode, supportsDeliveryControl, selectedPreset?.isDirectionalHint == true {
            Label(EmotionPreset.directionalHintAdvisory, systemImage: "wand.and.sparkles")
                .font(.caption2)
                .foregroundStyle(MacTheme.Text.secondary)
                .accessibilityIdentifier("delivery_hintAdvisory")
        }
        if !supportsDeliveryControl {
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

    private var customToneField: some View {
        VStack(alignment: .leading, spacing: 6) {
            TextField(MacInterfaceText.emotionCustomTonePlaceholder, text: $customToneText)
                .textFieldStyle(.plain)
                .font(.callout)
                .foregroundStyle(MacTheme.Text.primary)
                .vocelloFocusRing(tint, radius: 10)
                .padding(.horizontal, 12)
                .padding(.vertical, 8)
                .background {
                    RoundedRectangle(cornerRadius: MacTheme.Radius.input, style: .continuous)
                        .fill(MacTheme.Surface.field)
                }
                .overlay {
                    RoundedRectangle(cornerRadius: MacTheme.Radius.input, style: .continuous)
                        .stroke(MacTheme.Surface.fieldStroke, lineWidth: 0.5)
                }
                .accessibilityLabel(MacInterfaceText.emotionCustomTone)
                .accessibilityIdentifier("delivery_toneField")
                .onChange(of: customToneText) { _, newValue in
                    if newValue.count > customToneCharacterLimit {
                        customToneText = String(newValue.prefix(customToneCharacterLimit))
                    }
                    applyCustomTone()
                }

            if DeliveryInstructionAdvisor.hasDurationDirective(customToneText) {
                Label(DeliveryInstructionAdvisor.advisoryMessage, systemImage: "exclamationmark.triangle")
                    .font(.caption2)
                    .foregroundStyle(MacTheme.Status.guarded)
                    .accessibilityIdentifier("delivery_durationAdvisory")
            }
        }
    }

    // MARK: - Delivery state

    /// The draft stores the instruction and the profile; the chip derives its
    /// preset from them, and Custom keeps its own text so an empty custom
    /// field stays neutral in the request.
    private func syncDeliveryModeFromDraft() {
        let trimmed = draft.emotion.trimmingCharacters(in: .whitespacesAndNewlines)
        if EmotionPreset.matchInstruction(trimmed) != nil || DeliveryProfile.isNeutralInstruction(trimmed) {
            isCustomToneMode = false
            customToneText = ""
        } else {
            isCustomToneMode = true
            customToneText = trimmed
        }
    }

    private func selectPreset(_ preset: EmotionPreset) {
        // A new selection always ships the preset's shipped tier (the DP-8
        // strong anchor; happy/angry ship normal, DP-22 branch (a)).
        isCustomToneMode = false
        customToneText = ""
        let profile = DeliveryProfile.preset(preset, intensity: preset.shippedIntensity)
        draft.emotion = profile.finalInstruction
        draft.deliveryProfile = profile
    }

    private func enterCustomToneMode() {
        isCustomToneMode = true
        applyCustomTone()
    }

    private func applyCustomTone() {
        let profile = DeliveryProfile.custom(customToneText)
        draft.emotion = profile.finalInstruction
        draft.deliveryProfile = profile
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
            presentedSheet = .batch(.custom(draft: draft, initialText: draft.text, initialSegmentationMode: .longForm))
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
            deliveryInstructionCellID: draft.deliveryProfile?.instructionCellID,
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
