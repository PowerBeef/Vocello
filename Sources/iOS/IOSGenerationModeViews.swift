import SwiftUI
import UniformTypeIdentifiers
import QwenVoiceCore

/// Two-letter UPPERCASE abbreviations for the Studio selector pills
/// (`IOSStudioSetupChip`). Voice/Delivery/brief use the first two letters of
/// the selected value; Language reuses the standard language-code tag
/// (`IOSVoicePickerLanguage.tag`, e.g. Chinese → "ZH"); unset slots show "—".
private enum IOSStudioChipAbbreviation {
    static let placeholder = "—"

    /// First two letters of a value, uppercased ("Aiden" → "AI", "Neutral" → "NE").
    static func prefix2(_ text: String) -> String {
        String(text.prefix(2)).uppercased()
    }

    /// Name initials: first letter of the first two words, else first two
    /// letters. Mirrors `IOSVoicePickerOption.initials`.
    static func initials(_ name: String) -> String {
        let words = name.split(separator: " ")
        if words.count >= 2 {
            return "\(words[0].prefix(1))\(words[1].prefix(1))".uppercased()
        }
        return prefix2(name)
    }

    /// Standard 2-letter language code (Chinese → "ZH", English → "EN"); falls
    /// back to the first two letters ("Auto" → "AU").
    static func language(_ displayName: String) -> String {
        let tag = IOSVoicePickerLanguage.tag(for: displayName) ?? displayName
        return String(tag.prefix(2)).uppercased()
    }
}

struct IOSCustomVoiceView: View {
    @EnvironmentObject private var ttsEngine: TTSEngineStore
    @EnvironmentObject private var audioPlayer: AudioPlayerViewModel
    @EnvironmentObject private var modelManager: ModelManagerViewModel
    @Environment(AppModel.self) private var appModel
    @Environment(\.presentIOSPlayerSheet) private var presentPlayerSheet

    let isActive: Bool
    @Binding var selectedTab: IOSAppTab
    @Binding var draft: CustomVoiceDraft
    @State private var isScriptFocused = false

    // Generation lifecycle state lives on AppModel.customCoordinator
    // (Phase 3b extraction). Keep these computed-property aliases so the
    // rest of the view body stays readable without churn.
    private var coordinator: StudioGenerationCoordinator { appModel.customCoordinator }
    private var isGenerating: Bool {
        get { coordinator.isGenerating }
    }
    private var errorMessage: String? {
        get { coordinator.errorMessage }
    }
    private var lastCompletedOutput: IOSStudioInlinePlayerItem? {
        get { coordinator.lastCompletedOutput }
    }

    private var studioGenState: IOSStudioGenState {
        if coordinator.isGenerating {
            // Show the live-preview card once the shared player is actually streaming
            // audible audio; keep the compact generating bar during prepare/buffering.
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

    private func expandInlinePlayer() {
        guard let output = coordinator.lastCompletedOutput else { return }
        presentPlayerSheet(output.playerSheetItem)
    }

    private var speakerDisplay: SpeakerDescriptor? {
        TTSContract.speakerDescriptor(id: draft.selectedSpeaker)
    }

    private var speakerDisplayName: String {
        speakerDisplay?.displayName ?? draft.selectedSpeaker.capitalized
    }

    private var deliveryChipLabel: String {
        if draft.delivery.mode == .custom {
            let trimmed = draft.delivery.customText.trimmingCharacters(in: .whitespacesAndNewlines)
            guard !trimmed.isEmpty else { return "Custom delivery" }
            let maxLength = 30
            if trimmed.count > maxLength {
                return String(trimmed.prefix(maxLength)) + "…"
            }
            return trimmed
        }
        return draft.delivery.selectedPresetLabel
    }

    private var activeModel: TTSModel? {
        TTSModel.model(for: .custom)
    }

    private var supportsDeliveryControl: Bool {
        activeModel?.supportsInstructionControl ?? false
    }

    private var allowsExecution: Bool {
        ttsEngine.supportsMode(.custom)
    }

    private var isModelAvailable: Bool {
        guard let activeModel else { return false }
        return modelManager.isAvailable(activeModel)
    }

    private var promptText: String {
        IOSGenerationTextLimitPolicy.clamped(draft.text, mode: .custom)
    }

    private var promptTextBinding: Binding<String> {
        Binding(
            get: { promptText },
            set: { draft.text = IOSGenerationTextLimitPolicy.clamped($0, mode: .custom) }
        )
    }

    private var scriptLimitState: IOSGenerationTextLimitPolicy.State {
        IOSGenerationTextLimitPolicy.state(for: promptText, mode: .custom)
    }

    private var canGenerate: Bool {
        allowsExecution
            && ttsEngine.isReady
            && isModelAvailable
            && !scriptLimitState.trimmedIsEmpty
            && !scriptLimitState.isOverLimit
            && !ttsEngine.hasActiveGeneration
            && !appModel.longForm.isProcessing
    }

    private var canGenerateInCurrentRuntime: Bool {
        canGenerate
    }

    private var chromeOpacity: Double {
        isGenerationActive ? 0.76 : 1
    }

    private var setupMessage: String? {
        if !isModelAvailable, let activeModel {
            return "Install \(activeModel.name) in Settings."
        }
        return nil
    }

    private var isLongFormActiveHere: Bool {
        appModel.longForm.isProcessing && appModel.longForm.lastMode == .custom
    }

    private var promptHelper: String? {
        if isLongFormActiveHere, !appModel.longForm.progress.helperText.isEmpty {
            return appModel.longForm.progress.helperText
        }
        if !isScriptFocused && promptText.isEmpty {
            return nil
        }
        return scriptLimitState.helperMessage
    }

    private var isGenerationActive: Bool {
        isGenerating || ttsEngine.hasActiveGeneration || isLongFormActiveHere
    }

    @State private var detectedPromptLanguage: Qwen3SupportedLanguage = .auto

    var body: some View {
        pageContent
            .task(id: promptText) {
                try? await Task.sleep(for: .milliseconds(350))
                guard !Task.isCancelled else { return }
                detectedPromptLanguage = PromptLanguageDetector.detect(promptText)
            }
    }

    @ViewBuilder
    private var pageContent: some View {
        IOSStudioCanvas(
            mode: .custom,
            script: promptTextBinding,
            placeholder: "Type or paste your script.",
            modeMetaLabel: "Built-in voice",
            charLimit: scriptLimitState.displayLimit,
            tint: IOSBrandTheme.custom,
            genState: studioGenState,
            errorMessage: coordinator.errorMessage,
            canGenerate: canGenerateInCurrentRuntime,
            modelInstalled: isModelAvailable,
            modelDisplayName: activeModel?.name ?? "Voice model",
            setupChips: { customModeChips },
            onGenerate: generate,
            onCancel: {
                if appModel.longForm.isProcessing {
                    appModel.longForm.cancel(ttsEngine: ttsEngine, audioPlayer: audioPlayer)
                } else {
                    IOSStudioGenerationActions.cancelGeneration(
                        coordinator: coordinator,
                        ttsEngine: ttsEngine,
                        audioPlayer: audioPlayer
                    )
                }
            },
            onInstallModel: { selectedTab = .settings },
            onPlayerDismiss: { coordinator.dismissInlinePlayer() },
            onPlayerExpand: expandInlinePlayer
        )
        .opacity(chromeOpacity)
        .iosAppAnimation(IOSSelectionMotion.modeCrossfade, value: isGenerationActive)
    }

    @ViewBuilder
    private var longFormResumeChip: some View {
        if appModel.longForm.canResume, appModel.longForm.lastMode == .custom {
            IOSStudioSetupChip(
                eyebrow: "Long-form",
                value: "Resume project",
                abbreviation: "LF",
                leadingSymbol: "arrow.clockwise",
                tint: IOSBrandTheme.custom,
                accessibilityID: "longform_resumeChip",
                action: {
                    appModel.longForm.resume(
                        ttsEngine: ttsEngine,
                        audioPlayer: audioPlayer,
                        studioCoordinator: coordinator
                    )
                }
            )
        }
    }

    private func startLongFormProject(model: TTSModel) {
        guard !appModel.longForm.isProcessing else { return }
        do {
            let plan = try IOSLongFormCoordinator.plan(originalText: promptText)
            guard plan.segments.count <= IOSLongFormCoordinator.maxSegments else {
                coordinator.fail(
                    "This script plans \(plan.segments.count) segments; the maximum is \(IOSLongFormCoordinator.maxSegments). Split the text and try again."
                )
                return
            }
            appModel.longForm.start(
                request: IOSLongFormProjectRequest(
                    mode: .custom,
                    model: model,
                    plan: plan,
                    voice: draft.selectedSpeaker,
                    emotion: model.supportsInstructionControl ? draft.resolvedDeliveryInstruction : nil,
                    languageHint: draft.selectedLanguage.rawValue,
                    voiceDescription: nil,
                    refAudio: nil,
                    refText: nil,
                    preparedVoiceID: nil
                ),
                ttsEngine: ttsEngine,
                audioPlayer: audioPlayer,
                studioCoordinator: coordinator
            )
        } catch {
            coordinator.fail("Long-form planning failed: \(error.localizedDescription)")
        }
    }

    @ViewBuilder
    private var customModeChips: some View {
        longFormResumeChip
        IOSLongFormSegmentsMenuChip(
            mode: .custom,
            tint: IOSBrandTheme.custom,
            appModel: appModel,
            ttsEngine: ttsEngine,
            audioPlayer: audioPlayer,
            studioCoordinator: coordinator
        )
        IOSStudioSetupChip(
            eyebrow: "Voice",
            value: speakerDisplayName,
            abbreviation: IOSStudioChipAbbreviation.prefix2(speakerDisplayName),
            // Mirrors the macOS per-mode glyph (QwenVoiceCore GenerationMode.iconName =
            // "person.wave.2"), .fill variant to match the iOS pills' filled styling.
            leadingSymbol: "person.wave.2.fill",
            tint: IOSBrandTheme.custom,
            accessibilityID: "studioChip_voice",
            action: presentVoicePicker
        )
        IOSStudioSetupChip(
            eyebrow: "Delivery",
            value: deliveryChipLabel,
            abbreviation: IOSStudioChipAbbreviation.prefix2(draft.delivery.selectedPresetLabel),
            leadingSymbol: "theatermasks.fill",
            tint: IOSEmotionPresetPalette.dotColor(forID: draft.delivery.selectedPresetID),
            accessibilityID: "studioChip_delivery",
            action: presentDeliveryPicker
        )
        .disabled(!supportsDeliveryControl)
        .opacity(supportsDeliveryControl ? 1 : 0.45)
        IOSStudioSetupChip(
            eyebrow: "Language",
            value: LanguageSelectionPresentation.buttonLabel(
                selected: draft.selectedLanguage,
                detected: detectedPromptLanguage
            ),
            abbreviation: IOSStudioChipAbbreviation.language(
                LanguageSelectionPresentation.effective(
                    selected: draft.selectedLanguage,
                    detected: detectedPromptLanguage
                ).displayName
            ),
            leadingSymbol: "globe",
            tint: IOSBrandTheme.custom,
            accessibilityID: "studioChip_language",
            action: presentLanguagePicker
        )
    }

    private func presentVoicePicker() {
        appModel.presentBottomPanel { bottomSafeAreaInset, availableHeight, dismiss in
            AnyView(
                IOSVoicePickerSheet(
                    speakers: voicePickerOptions,
                    selectedID: Binding(
                        get: { draft.selectedSpeaker },
                        set: { newSpeaker in
                            // Picking a speaker no longer pins the language —
                            // the language token describes the TEXT's language,
                            // which the selector follows via detection (Auto);
                            // mirrors the macOS behavior change.
                            draft.selectedSpeaker = newSpeaker
                        }
                    ),
                    tint: IOSBrandTheme.custom,
                    onDismiss: dismiss,
                    presentation: .edgeToEdge(
                        bottomSafeAreaInset: bottomSafeAreaInset,
                        height: IOSBottomSheetChrome.expandedHeight(forScreenHeight: availableHeight)
                    )
                )
            )
        }
    }

    private func presentLanguagePicker() {
        appModel.presentBottomPanel { bottomSafeAreaInset, availableHeight, dismiss in
            AnyView(
                IOSQwenLanguagePickerSheet(
                    selectedLanguage: $draft.selectedLanguage,
                    tint: IOSBrandTheme.custom,
                    recommended: detectedPromptLanguage,
                    onDismiss: dismiss,
                    presentation: .edgeToEdge(
                        bottomSafeAreaInset: bottomSafeAreaInset,
                        height: IOSBottomSheetChrome.expandedHeight(forScreenHeight: availableHeight)
                    )
                )
            )
        }
    }

    private func presentDeliveryPicker() {
        guard supportsDeliveryControl else { return }
        appModel.presentBottomPanel { bottomSafeAreaInset, availableHeight, dismiss in
            AnyView(
                IOSDeliveryPickerSheet(
                    selectedPresetID: Binding(
                        get: { draft.delivery.selectedPresetID },
                        set: { newID in
                            draft.delivery.mode = .preset
                            draft.delivery.selectedPresetID = newID
                        }
                    ),
                    intensity: $draft.delivery.selectedIntensity,
                    customText: $draft.delivery.customText,
                    tint: IOSBrandTheme.custom,
                    onUseCustomTone: { draft.delivery.mode = .custom },
                    onDismiss: dismiss,
                    presentation: .edgeToEdge(
                        bottomSafeAreaInset: bottomSafeAreaInset,
                        height: IOSBottomSheetChrome.expandedHeight(forScreenHeight: availableHeight)
                    )
                )
            )
        }
    }

    private var voicePickerOptions: [IOSVoicePickerOption] {
        TTSContract.allSpeakerDescriptors.map { spec in
            IOSVoicePickerOption(
                id: spec.id,
                name: spec.displayName,
                subtitle: spec.shortDescription ?? spec.nativeLanguage,
                languageTag: IOSVoicePickerLanguage.tag(for: spec.nativeLanguage),
                isRecommended: detectedPromptLanguage != .auto
                    && TTSModel.qwenLanguage(forSpeaker: spec.id) == detectedPromptLanguage
            )
        }
    }

    private func generate() {
        guard !scriptLimitState.trimmedIsEmpty, ttsEngine.isReady, !ttsEngine.hasActiveGeneration else { return }
        guard !scriptLimitState.isOverLimit else {
            coordinator.fail(scriptLimitState.warningMessage)
            return
        }
        guard let model = activeModel else { return }
        guard isModelAvailable else {
            coordinator.fail("Install \(model.name) in Settings to generate audio.")
            return
        }
        if scriptLimitState.routesToLongForm {
            startLongFormProject(model: model)
            return
        }

        // Same seed for the live + final card so the decorative waveform doesn't change shape.
        let seed = IOSStableVisualHash.int(promptText)
        coordinator.start(live: IOSStudioLivePreviewItem(
            voiceName: speakerDisplayName,
            modeLabel: "Custom",
            mode: .custom,
            transcript: promptText,
            waveformSeed: seed,
            estimatedAudioDuration: LivePreviewEstimate(text: promptText)?.estimatedAudioDuration ?? 0
        ))
        let generationID = UUID()

        coordinator.generationTask = Task {
            defer {
                Task { @MainActor in
                    if coordinator.isGenerating {
                        coordinator.finish()
                    }
                }
            }
            let outputPath = makeOutputPath(subfolder: model.outputSubfolder, text: promptText)
            do {
                // Live streaming playback: estimate the buffer up front, then let
                // AudioPlayerViewModel play chunks as they arrive (it already subscribes on
                // iOS) and seamlessly hand off to the final file at completion.
                audioPlayer.setLivePreviewEstimate(LivePreviewEstimate(text: promptText))
                await AppGenerationTimeline.shared.recordSubmitted(
                    id: generationID,
                    mode: GenerationMode.custom.rawValue
                )
                let result = try await ttsEngine.generate(
                    GenerationRequest(
                        mode: .custom,
                        modelID: model.id,
                        text: promptText,
                        outputPath: outputPath,
                        shouldStream: true,
                        streamingInterval: GenerationSemantics.appStreamingInterval,
                        languageHint: draft.selectedLanguage.rawValue,
                        payload: .custom(
                            speakerID: draft.selectedSpeaker,
                            deliveryStyle: model.supportsInstructionControl
                                ? draft.resolvedDeliveryInstruction
                                : nil
                        ),
                        generationID: generationID,
                        variation: IOSGenerationVariationPreference.requestValue()
                    )
                )
                // If the user cancelled while the take was generating, discard it: don't
                // play it, don't persist it as a clip, and remove the orphaned WAV. The
                // engine has already completed + cleaned up via its normal path here (this is
                // iOS-only — it does NOT alter engine lifecycle/loadState), so this just
                // suppresses surfacing an unwanted result. Keeps cancelled takes out of History.
                if Task.isCancelled {
                    await AppGenerationTimeline.shared.recordFailed(
                        id: generationID,
                        finishReason: .cancelled
                    )
                    IOSPullableDiagnosticsMirror.syncGenerationTelemetryIfEnabled(
                        generationID: generationID
                    )
                    try? FileManager.default.removeItem(atPath: result.audioPath)
                    audioPlayer.abortLivePreviewIfNeeded()
                    return
                }
                // Finalize or hand off playback while the frontend timeline is
                // still open. Short clips can reach final-file autoplay before
                // live playback starts, and that genuine scheduling event must
                // be recorded before the durable app telemetry row is written.
                audioPlayer.completeStreamingPreview(
                    result: result,
                    title: String(promptText.prefix(40)),
                    shouldAutoPlay: AudioService.shouldAutoPlay
                )
                await AppGenerationTimeline.shared.recordCompleted(
                    id: generationID,
                    mode: GenerationMode.custom.rawValue,
                    usedStreaming: true,
                    finishReason: result.finishReason?.rawValue,
                    summary: result.telemetrySummary
                )
                IOSPullableDiagnosticsMirror.syncGenerationTelemetryIfEnabled(
                    generationID: generationID
                )
                let generation = Generation(
                    text: promptText,
                    mode: model.mode.rawValue,
                    modelTier: model.tier,
                    voice: draft.selectedSpeaker,
                    emotion: model.supportsInstructionControl ? draft.resolvedDeliveryInstruction : nil,
                    speed: nil,
                    audioPath: result.audioPath,
                    duration: result.durationSeconds,
                    createdAt: Date()
                )
                GenerationPersistence.persist(
                    generation,
                    caller: "IOSCustomVoiceView"
                )
                IOSSavedOutputsDestination.exportIfConfigured(internalAudioPath: result.audioPath)
                await MainActor.run {
                    coordinator.complete(
                        IOSStudioInlinePlayerItem(
                            generationID: generationID,
                            audioURL: URL(fileURLWithPath: result.audioPath),
                            voiceName: speakerDisplayName,
                            modeLabel: "Custom",
                            mode: .custom,
                            transcript: promptText,
                            waveformSeed: seed,
                            autoplay: false,
                            ownedBySharedPlayer: true
                        )
                    )
                }
                IOSHaptics.success()
            } catch is CancellationError {
                await AppGenerationTimeline.shared.recordFailed(
                    id: generationID,
                    finishReason: .cancelled
                )
                IOSPullableDiagnosticsMirror.syncGenerationTelemetryIfEnabled(
                    generationID: generationID
                )
                audioPlayer.abortLivePreviewIfNeeded()
                await MainActor.run { coordinator.errorMessage = nil }
            } catch {
                await AppGenerationTimeline.shared.recordFailed(
                    id: generationID,
                    finishReason: Task.isCancelled ? .cancelled : .failed
                )
                IOSPullableDiagnosticsMirror.syncGenerationTelemetryIfEnabled(
                    generationID: generationID
                )
                audioPlayer.abortLivePreviewIfNeeded()
                if Task.isCancelled {
                    // A user cancel can surface as a wrapped engine error (not a bare
                    // CancellationError) — treat it as a clean cancel, not a failure banner.
                    // iOS-only: does not touch engine lifecycle/cleanup.
                    await MainActor.run { coordinator.errorMessage = nil }
                } else {
                    await MainActor.run { coordinator.fail(error.localizedDescription) }
                    IOSHaptics.warning()
                }
            }
        }
    }
}

/// A designed voice just saved from the Design result, carried by the "Use in Clone" confirmation.
private struct IOSDesignedVoiceSaveResult: Equatable {
    let voice: PreparedVoice
    let transcript: String
}

struct IOSVoiceDesignView: View {
    @EnvironmentObject private var ttsEngine: TTSEngineStore
    @EnvironmentObject private var audioPlayer: AudioPlayerViewModel
    @EnvironmentObject private var modelManager: ModelManagerViewModel
    @EnvironmentObject private var savedVoicesViewModel: SavedVoicesViewModel
    @Environment(AppModel.self) private var appModel
    @Environment(\.presentIOSPlayerSheet) private var presentPlayerSheet

    let isActive: Bool
    @Binding var selectedTab: IOSAppTab
    @Binding var draft: VoiceDesignDraft
    @State private var isScriptFocused = false
    @State private var saveSheetAudioPath: String?
    @State private var isSaveSheetPresented = false
    @State private var saveSheetSuggestedName = ""
    @State private var saveSheetTranscript = ""
    @State private var saveError: String?
    /// Voice that was just enrolled but has quality warnings; user is
    /// being asked whether to keep or discard. Mirrors the macOS
    /// SavedVoiceSheet flow.
    @State private var pendingVoiceForReview: PreparedVoice?
    /// A designed voice that was just saved → drives the "Saved ✓ · Use in Clone" confirmation banner.
    @State private var savedDesignedResult: IOSDesignedVoiceSaveResult?

    // Generation lifecycle moved to AppModel.designCoordinator (Phase 3b).
    private var coordinator: StudioGenerationCoordinator { appModel.designCoordinator }
    private var isGenerating: Bool { coordinator.isGenerating }
    private var errorMessage: String? { coordinator.errorMessage }
    private var lastCompletedOutput: IOSStudioInlinePlayerItem? { coordinator.lastCompletedOutput }

    private var studioGenState: IOSStudioGenState {
        if coordinator.isGenerating {
            // Show the live-preview card once the shared player is actually streaming
            // audible audio; keep the compact generating bar during prepare/buffering.
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

    private func expandInlinePlayer() {
        guard let output = coordinator.lastCompletedOutput else { return }
        presentPlayerSheet(output.playerSheetItem)
    }

    private var deliveryChipLabel: String {
        if draft.delivery.mode == .custom {
            let trimmed = draft.delivery.customText.trimmingCharacters(in: .whitespacesAndNewlines)
            return trimmed.isEmpty ? "Custom delivery" : trimmed
        }
        return draft.delivery.selectedPresetLabel
    }

    private var briefChipLabel: String {
        let trimmed = draft.voiceDescription.trimmingCharacters(in: .whitespacesAndNewlines)
        return trimmed.isEmpty ? "Describe the voice" : trimmed
    }

    private var briefChipAbbreviation: String {
        let trimmed = draft.voiceDescription.trimmingCharacters(in: .whitespacesAndNewlines)
        return trimmed.isEmpty
            ? IOSStudioChipAbbreviation.placeholder
            : IOSStudioChipAbbreviation.prefix2(trimmed)
    }

    private var activeModel: TTSModel? {
        TTSModel.model(for: .design)
    }

    private var allowsExecution: Bool {
        ttsEngine.supportsMode(.design)
    }

    private var isModelAvailable: Bool {
        guard let activeModel else { return false }
        return modelManager.isAvailable(activeModel)
    }

    private var promptText: String {
        IOSGenerationTextLimitPolicy.clamped(draft.text, mode: .design)
    }

    private var promptTextBinding: Binding<String> {
        Binding(
            get: { promptText },
            set: { draft.text = IOSGenerationTextLimitPolicy.clamped($0, mode: .design) }
        )
    }

    private var scriptLimitState: IOSGenerationTextLimitPolicy.State {
        IOSGenerationTextLimitPolicy.state(for: promptText, mode: .design)
    }

    private var canGenerate: Bool {
        allowsExecution
            && ttsEngine.isReady
            && isModelAvailable
            && !draft.voiceDescription.isEmpty
            && !scriptLimitState.trimmedIsEmpty
            && !scriptLimitState.isOverLimit
            && !ttsEngine.hasActiveGeneration
            && !appModel.longForm.isProcessing
    }

    private var canGenerateInCurrentRuntime: Bool {
        canGenerate
    }

    private var chromeOpacity: Double {
        isGenerationActive ? 0.76 : 1
    }

    private var setupMessage: String? {
        if !isModelAvailable, let activeModel {
            return "Install \(activeModel.name) in Settings."
        }
        return nil
    }

    private var isLongFormActiveHere: Bool {
        appModel.longForm.isProcessing && appModel.longForm.lastMode == .design
    }

    private var promptHelper: String? {
        if isLongFormActiveHere, !appModel.longForm.progress.helperText.isEmpty {
            return appModel.longForm.progress.helperText
        }
        if !isScriptFocused && promptText.isEmpty {
            return nil
        }
        return scriptLimitState.helperMessage
    }

    private var canSaveVoice: Bool {
        ttsEngine.supportsSavedVoiceMutation && saveSheetAudioPath != nil
    }

    private var isGenerationActive: Bool {
        isGenerating || ttsEngine.hasActiveGeneration || isLongFormActiveHere
    }

    @State private var detectedPromptLanguage: Qwen3SupportedLanguage = .auto

    var body: some View {
        pageContent
            .task(id: promptText) {
                try? await Task.sleep(for: .milliseconds(350))
                guard !Task.isCancelled else { return }
                detectedPromptLanguage = PromptLanguageDetector.detect(promptText)
            }
            .sheet(isPresented: Binding(
                get: { isSaveSheetPresented },
                set: { isPresented in
                    isSaveSheetPresented = isPresented
                    if !isPresented {
                        saveSheetSuggestedName = ""
                        saveSheetTranscript = ""
                        saveError = nil
                    }
                }
            )) {
                if let saveSheetAudioPath {
                    IOSSaveVoiceSheet(
                        title: "Save Generated Voice",
                        suggestedName: $saveSheetSuggestedName,
                        transcript: $saveSheetTranscript,
                        errorMessage: saveError,
                        clipAudioURL: URL(fileURLWithPath: saveSheetAudioPath),
                        onCancel: {
                            isSaveSheetPresented = false
                            saveSheetSuggestedName = ""
                            saveSheetTranscript = ""
                            saveError = nil
                        },
                        onSave: {
                            Task {
                                do {
                                    let voice = try await ttsEngine.enrollPreparedVoice(
                                        name: saveSheetSuggestedName,
                                        audioPath: saveSheetAudioPath,
                                        transcript: saveSheetTranscript.isEmpty ? nil : saveSheetTranscript
                                    )
                                    await MainActor.run {
                                        if voice.qualityWarnings.isEmpty {
                                            savedVoicesViewModel.insertOrReplace(voice)
                                            let usedTranscript = saveSheetTranscript
                                            isSaveSheetPresented = false
                                            saveSheetSuggestedName = ""
                                            saveSheetTranscript = ""
                                            saveError = nil
                                            savedDesignedResult = IOSDesignedVoiceSaveResult(
                                                voice: voice, transcript: usedTranscript
                                            )
                                        } else {
                                            // Soft warning: voice is on disk
                                            // but pending user confirmation.
                                            pendingVoiceForReview = voice
                                        }
                                    }
                                    if voice.qualityWarnings.isEmpty {
                                        await savedVoicesViewModel.refresh(using: ttsEngine)
                                    }
                                } catch {
                                    await MainActor.run {
                                        saveError = error.localizedDescription
                                    }
                                }
                            }
                        }
                    )
                }
            }
            .alert(
                "Reference outside recommended range",
                isPresented: Binding(
                    get: { pendingVoiceForReview != nil },
                    set: { if !$0 { pendingVoiceForReview = nil } }
                ),
                presenting: pendingVoiceForReview
            ) { voice in
                // Hard-block tier (>60 s) hides the "Keep voice" button
                // so the user has to discard or cancel; soft-warn tier
                // keeps all three buttons.
                if !PreparedVoiceQualityWarning.isHardBlocking(voice.qualityWarnings) {
                    Button("Keep voice") {
                        pendingVoiceForReview = nil
                        savedVoicesViewModel.insertOrReplace(voice)
                        let usedTranscript = saveSheetTranscript
                        isSaveSheetPresented = false
                        saveSheetSuggestedName = ""
                        saveSheetTranscript = ""
                        saveError = nil
                        Task { await savedVoicesViewModel.refresh(using: ttsEngine) }
                        savedDesignedResult = IOSDesignedVoiceSaveResult(voice: voice, transcript: usedTranscript)
                    }
                    .accessibilityIdentifier("voicesEnroll_keepDespiteWarning")
                }
                Button("Discard and re-record", role: .destructive) {
                    let voiceID = voice.id
                    pendingVoiceForReview = nil
                    Task {
                        try? await ttsEngine.deletePreparedVoice(id: voiceID)
                    }
                }
                .accessibilityIdentifier("voicesEnroll_discardOnWarning")
                Button("Cancel", role: .cancel) {
                    pendingVoiceForReview = nil
                }
                .accessibilityIdentifier("voicesEnroll_cancelOnWarning")
            } message: { voice in
                Text(PreparedVoiceQualityWarning.summary(for: voice.qualityWarnings))
            }
            .overlay(alignment: .top) {
                if let result = savedDesignedResult {
                    savedVoiceBanner(result)
                        .transition(.move(edge: .top).combined(with: .opacity))
                }
            }
            .iosAppAnimation(IOSSelectionMotion.miniPlayerSlide, value: savedDesignedResult)
            .task(id: savedDesignedResult) {
                guard savedDesignedResult != nil else { return }
                try? await Task.sleep(for: .seconds(6))
                guard !Task.isCancelled else { return }
                savedDesignedResult = nil
            }
    }

    // MARK: - Save designed voice → reuse in Clone

    /// Open the (existing) save-voice sheet for the just-generated designed clip, prefilled with a
    /// name suggestion from the brief + the script as the transcript.
    private func presentSaveDesignedVoice() {
        guard canSaveVoice else { return }
        if saveSheetSuggestedName.isEmpty {
            saveSheetSuggestedName = suggestedDesignedVoiceName()
        }
        if saveSheetTranscript.isEmpty {
            saveSheetTranscript = promptText
        }
        isSaveSheetPresented = true
    }

    private func suggestedDesignedVoiceName() -> String {
        let brief = draft.voiceDescription.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !brief.isEmpty else { return "Designed voice" }
        let words = brief.split(whereSeparator: { $0 == " " || $0.isNewline }).prefix(3)
        let joined = words.joined(separator: " ")
        guard !joined.isEmpty else { return "Designed voice" }
        return joined.prefix(1).uppercased() + joined.dropFirst()
    }

    /// Stage the saved designed voice as the Clone reference + jump to Clone (same handoff the
    /// record→enroll flow uses).
    private func useDesignedVoiceInClone(_ result: IOSDesignedVoiceSaveResult) {
        savedDesignedResult = nil
        appModel.pendingVoiceCloningHandoff = PendingVoiceCloningHandoff(
            savedVoiceID: result.voice.id,
            wavPath: result.voice.wavPath,
            transcript: result.transcript,
            transcriptLoadError: nil,
            language: PromptLanguageDetector.detect(result.transcript)
        )
        appModel.studioMode = .clone
        appModel.tab = .studio
    }

    private func savedVoiceBanner(_ result: IOSDesignedVoiceSaveResult) -> some View {
        HStack(spacing: 12) {
            Image(systemName: "checkmark.circle.fill")
                .font(.system(size: 18, weight: .semibold))
                .foregroundStyle(IOSBrandTheme.design)

            VStack(alignment: .leading, spacing: 1) {
                Text("Saved “\(result.voice.name)”")
                    .font(.subheadline.weight(.semibold))
                    .foregroundStyle(IOSAppTheme.textPrimary)
                    .lineLimit(1)
                Text("Now in your voices.")
                    .font(.caption)
                    .foregroundStyle(IOSAppTheme.textSecondary)
            }

            Spacer(minLength: 8)

            Button {
                IOSHaptics.selection()
                useDesignedVoiceInClone(result)
            } label: {
                Text("Use in Clone")
                    .font(.footnote.weight(.semibold))
                    .foregroundStyle(IOSBrandTheme.clone)
                    .padding(.horizontal, 12)
                    .padding(.vertical, 7)
                    .background { Capsule(style: .continuous).fill(IOSBrandTheme.clone.opacity(0.16)) }
                    .overlay { Capsule(style: .continuous).stroke(IOSBrandTheme.clone.opacity(0.32), lineWidth: 0.75) }
            }
            .buttonStyle(.plain)
            .accessibilityIdentifier("design_savedVoice_useInClone")
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 12)
        .background {
            RoundedRectangle(cornerRadius: IOSCornerRadius.card, style: .continuous)
                .fill(IOSBottomSheetChrome.background)
        }
        .overlay {
            RoundedRectangle(cornerRadius: IOSCornerRadius.card, style: .continuous)
                .stroke(Color.white.opacity(0.10), lineWidth: 0.5)
        }
        .shadow(color: Color.black.opacity(0.30), radius: 16, x: 0, y: 6)
        .padding(.horizontal, 16)
        .padding(.top, 8)
    }

    @ViewBuilder
    private var pageContent: some View {
        IOSStudioCanvas(
            mode: .design,
            script: promptTextBinding,
            placeholder: "Type the lines you want this designed voice to say.",
            modeMetaLabel: "Designed voice",
            charLimit: scriptLimitState.displayLimit,
            tint: IOSBrandTheme.design,
            genState: studioGenState,
            errorMessage: coordinator.errorMessage,
            canGenerate: canGenerateInCurrentRuntime,
            modelInstalled: isModelAvailable,
            modelDisplayName: activeModel?.name ?? "Voice Design model",
            setupChips: { designModeChips },
            onGenerate: generate,
            onCancel: {
                if appModel.longForm.isProcessing {
                    appModel.longForm.cancel(ttsEngine: ttsEngine, audioPlayer: audioPlayer)
                } else {
                    IOSStudioGenerationActions.cancelGeneration(
                        coordinator: coordinator,
                        ttsEngine: ttsEngine,
                        audioPlayer: audioPlayer
                    )
                }
            },
            onInstallModel: { selectedTab = .settings },
            onPlayerDismiss: { coordinator.dismissInlinePlayer() },
            onPlayerExpand: expandInlinePlayer,
            onSaveAsVoice: canSaveVoice ? { presentSaveDesignedVoice() } : nil
        )
        .opacity(chromeOpacity)
        .iosAppAnimation(IOSSelectionMotion.modeCrossfade, value: isGenerationActive)
    }

    @ViewBuilder
    private var longFormResumeChip: some View {
        if appModel.longForm.canResume, appModel.longForm.lastMode == .design {
            IOSStudioSetupChip(
                eyebrow: "Long-form",
                value: "Resume project",
                abbreviation: "LF",
                leadingSymbol: "arrow.clockwise",
                tint: IOSBrandTheme.design,
                accessibilityID: "longform_resumeChip",
                action: {
                    appModel.longForm.resume(
                        ttsEngine: ttsEngine,
                        audioPlayer: audioPlayer,
                        studioCoordinator: coordinator
                    )
                }
            )
        }
    }

    private func startLongFormProject(model: TTSModel) {
        guard !appModel.longForm.isProcessing else { return }
        do {
            let plan = try IOSLongFormCoordinator.plan(originalText: promptText)
            guard plan.segments.count <= IOSLongFormCoordinator.maxSegments else {
                coordinator.fail(
                    "This script plans \(plan.segments.count) segments; the maximum is \(IOSLongFormCoordinator.maxSegments). Split the text and try again."
                )
                return
            }
            appModel.longForm.start(
                request: IOSLongFormProjectRequest(
                    mode: .design,
                    model: model,
                    plan: plan,
                    voice: nil,
                    emotion: draft.resolvedDeliveryInstruction,
                    languageHint: draft.selectedLanguage.rawValue,
                    voiceDescription: draft.voiceDescription,
                    refAudio: nil,
                    refText: nil,
                    preparedVoiceID: nil
                ),
                ttsEngine: ttsEngine,
                audioPlayer: audioPlayer,
                studioCoordinator: coordinator
            )
        } catch {
            coordinator.fail("Long-form planning failed: \(error.localizedDescription)")
        }
    }

    @ViewBuilder
    private var designModeChips: some View {
        longFormResumeChip
        IOSLongFormSegmentsMenuChip(
            mode: .design,
            tint: IOSBrandTheme.design,
            appModel: appModel,
            ttsEngine: ttsEngine,
            audioPlayer: audioPlayer,
            studioCoordinator: coordinator
        )
        IOSStudioSetupChip(
            eyebrow: "Voice brief",
            value: briefChipLabel,
            abbreviation: briefChipAbbreviation,
            // Mirrors the macOS Voice Design glyph (GenerationMode.iconName = "text.bubble"),
            // .fill to match the iOS pills' filled styling — a text bubble reads as "describe it".
            leadingSymbol: "text.bubble.fill",
            tint: IOSBrandTheme.design,
            isPlaceholder: draft.voiceDescription.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
            accessibilityID: "studioChip_voiceBrief",
            action: presentBriefEditor
        )
        IOSStudioSetupChip(
            eyebrow: "Delivery",
            value: deliveryChipLabel,
            abbreviation: IOSStudioChipAbbreviation.prefix2(draft.delivery.selectedPresetLabel),
            leadingSymbol: "theatermasks.fill",
            tint: IOSEmotionPresetPalette.dotColor(forID: draft.delivery.selectedPresetID),
            accessibilityID: "studioChip_delivery",
            action: presentDesignDeliveryPicker
        )
        IOSStudioSetupChip(
            eyebrow: "Language",
            value: LanguageSelectionPresentation.buttonLabel(
                selected: draft.selectedLanguage,
                detected: detectedPromptLanguage
            ),
            abbreviation: IOSStudioChipAbbreviation.language(
                LanguageSelectionPresentation.effective(
                    selected: draft.selectedLanguage,
                    detected: detectedPromptLanguage
                ).displayName
            ),
            leadingSymbol: "globe",
            tint: IOSBrandTheme.design,
            accessibilityID: "studioChip_language",
            action: presentDesignLanguagePicker
        )
    }

    private func presentBriefEditor() {
        appModel.presentBottomPanel { bottomSafeAreaInset, availableHeight, dismiss in
            AnyView(
                IOSVoiceDesignBriefSheet(
                    voiceDescription: $draft.voiceDescription,
                    tint: IOSBrandTheme.design,
                    presentation: .edgeToEdge(
                        bottomSafeAreaInset: bottomSafeAreaInset,
                        height: IOSBottomSheetChrome.expandedHeight(forScreenHeight: availableHeight)
                    ),
                    onDismiss: dismiss
                )
            )
        }
    }

    private func presentDesignLanguagePicker() {
        appModel.presentBottomPanel { bottomSafeAreaInset, availableHeight, dismiss in
            AnyView(
                IOSQwenLanguagePickerSheet(
                    selectedLanguage: $draft.selectedLanguage,
                    tint: IOSBrandTheme.design,
                    recommended: detectedPromptLanguage,
                    onDismiss: dismiss,
                    presentation: .edgeToEdge(
                        bottomSafeAreaInset: bottomSafeAreaInset,
                        height: IOSBottomSheetChrome.expandedHeight(forScreenHeight: availableHeight)
                    )
                )
            )
        }
    }

    private func presentDesignDeliveryPicker() {
        appModel.presentBottomPanel { bottomSafeAreaInset, availableHeight, dismiss in
            AnyView(
                IOSDeliveryPickerSheet(
                    selectedPresetID: Binding(
                        get: { draft.delivery.selectedPresetID },
                        set: { newID in
                            draft.delivery.mode = .preset
                            draft.delivery.selectedPresetID = newID
                        }
                    ),
                    intensity: $draft.delivery.selectedIntensity,
                    customText: $draft.delivery.customText,
                    tint: IOSBrandTheme.design,
                    onUseCustomTone: { draft.delivery.mode = .custom },
                    onDismiss: dismiss,
                    presentation: .edgeToEdge(
                        bottomSafeAreaInset: bottomSafeAreaInset,
                        height: IOSBottomSheetChrome.expandedHeight(forScreenHeight: availableHeight)
                    )
                )
            )
        }
    }

    private var suggestedSavedVoiceName: String {
        let clipped = draft.voiceDescription
            .split(separator: " ")
            .prefix(3)
            .joined(separator: " ")
        return clipped.isEmpty ? "Designed Voice" : clipped
    }

    private func generate() {
        guard let model = activeModel else { return }
        guard canGenerate else {
            if !isModelAvailable {
                coordinator.fail("Install \(model.name) in Settings to generate audio.")
            } else if scriptLimitState.isOverLimit {
                coordinator.fail(scriptLimitState.warningMessage)
            }
            return
        }
        if scriptLimitState.routesToLongForm {
            startLongFormProject(model: model)
            return
        }

        // Same seed for the live + final card so the decorative waveform doesn't change shape.
        let seed = IOSStableVisualHash.int(promptText)
        coordinator.start(live: IOSStudioLivePreviewItem(
            voiceName: briefChipLabel,
            modeLabel: "Design",
            mode: .design,
            transcript: promptText,
            waveformSeed: seed,
            estimatedAudioDuration: LivePreviewEstimate(text: promptText)?.estimatedAudioDuration ?? 0
        ))
        let generationID = UUID()

        coordinator.generationTask = Task {
            defer {
                Task { @MainActor in
                    if coordinator.isGenerating {
                        coordinator.finish()
                    }
                }
            }
            let outputPath = makeOutputPath(subfolder: model.outputSubfolder, text: promptText)
            do {
                audioPlayer.setLivePreviewEstimate(LivePreviewEstimate(text: promptText))
                await AppGenerationTimeline.shared.recordSubmitted(
                    id: generationID,
                    mode: GenerationMode.design.rawValue
                )
                let result = try await ttsEngine.generate(
                    GenerationRequest(
                        mode: .design,
                        modelID: model.id,
                        text: promptText,
                        outputPath: outputPath,
                        shouldStream: true,
                        streamingInterval: GenerationSemantics.appStreamingInterval,
                        languageHint: draft.selectedLanguage.rawValue,
                        payload: .design(
                            voiceDescription: draft.voiceDescription,
                            deliveryStyle: draft.resolvedDeliveryInstruction
                        ),
                        generationID: generationID,
                        variation: IOSGenerationVariationPreference.requestValue()
                    )
                )
                // If the user cancelled while the take was generating, discard it: don't
                // play it, don't persist it as a clip, and remove the orphaned WAV. The
                // engine has already completed + cleaned up via its normal path here (this is
                // iOS-only — it does NOT alter engine lifecycle/loadState), so this just
                // suppresses surfacing an unwanted result. Keeps cancelled takes out of History.
                if Task.isCancelled {
                    await AppGenerationTimeline.shared.recordFailed(
                        id: generationID,
                        finishReason: .cancelled
                    )
                    IOSPullableDiagnosticsMirror.syncGenerationTelemetryIfEnabled(
                        generationID: generationID
                    )
                    try? FileManager.default.removeItem(atPath: result.audioPath)
                    audioPlayer.abortLivePreviewIfNeeded()
                    return
                }
                audioPlayer.completeStreamingPreview(
                    result: result,
                    title: String(promptText.prefix(40)),
                    shouldAutoPlay: AudioService.shouldAutoPlay
                )
                await AppGenerationTimeline.shared.recordCompleted(
                    id: generationID,
                    mode: GenerationMode.design.rawValue,
                    usedStreaming: true,
                    finishReason: result.finishReason?.rawValue,
                    summary: result.telemetrySummary
                )
                IOSPullableDiagnosticsMirror.syncGenerationTelemetryIfEnabled(
                    generationID: generationID
                )
                let generation = Generation(
                    text: promptText,
                    mode: model.mode.rawValue,
                    modelTier: model.tier,
                    voice: draft.voiceDescription,
                    emotion: draft.resolvedDeliveryInstruction,
                    speed: nil,
                    audioPath: result.audioPath,
                    duration: result.durationSeconds,
                    createdAt: Date()
                )
                GenerationPersistence.persist(
                    generation,
                    caller: "IOSVoiceDesignView"
                )
                IOSSavedOutputsDestination.exportIfConfigured(internalAudioPath: result.audioPath)
                saveSheetAudioPath = result.audioPath
                await MainActor.run {
                    coordinator.complete(
                        IOSStudioInlinePlayerItem(
                            generationID: generationID,
                            audioURL: URL(fileURLWithPath: result.audioPath),
                            voiceName: briefChipLabel,
                            modeLabel: "Design",
                            mode: .design,
                            transcript: promptText,
                            waveformSeed: seed,
                            autoplay: false,
                            ownedBySharedPlayer: true
                        )
                    )
                }
                IOSHaptics.success()
            } catch is CancellationError {
                await AppGenerationTimeline.shared.recordFailed(
                    id: generationID,
                    finishReason: .cancelled
                )
                IOSPullableDiagnosticsMirror.syncGenerationTelemetryIfEnabled(
                    generationID: generationID
                )
                audioPlayer.abortLivePreviewIfNeeded()
                await MainActor.run { coordinator.errorMessage = nil }
            } catch {
                await AppGenerationTimeline.shared.recordFailed(
                    id: generationID,
                    finishReason: Task.isCancelled ? .cancelled : .failed
                )
                IOSPullableDiagnosticsMirror.syncGenerationTelemetryIfEnabled(
                    generationID: generationID
                )
                audioPlayer.abortLivePreviewIfNeeded()
                if Task.isCancelled {
                    // A user cancel can surface as a wrapped engine error (not a bare
                    // CancellationError) — treat it as a clean cancel, not a failure banner.
                    // iOS-only: does not touch engine lifecycle/cleanup.
                    await MainActor.run { coordinator.errorMessage = nil }
                } else {
                    await MainActor.run { coordinator.fail(error.localizedDescription) }
                    IOSHaptics.warning()
                }
            }
        }
    }
}

struct IOSVoiceCloningView: View {
    @AppStorage("vocello.voiceCloningConsent.v1") private var cloneConsentAcknowledged = false
    @EnvironmentObject private var ttsEngine: TTSEngineStore
    @EnvironmentObject private var audioPlayer: AudioPlayerViewModel
    @EnvironmentObject private var modelManager: ModelManagerViewModel
    @EnvironmentObject private var savedVoicesViewModel: SavedVoicesViewModel
    @Environment(AppModel.self) private var appModel
    @Environment(\.presentIOSPlayerSheet) private var presentPlayerSheet

    let isActive: Bool
    @Binding var selectedTab: IOSAppTab
    @Binding var draft: VoiceCloningDraft
    @Binding var pendingSavedVoiceHandoff: PendingVoiceCloningHandoff?

    @State private var transcriptLoadError: String?
    @State private var hydratedSavedVoiceID: String?
    @State private var isTranscriptExpanded = false
    @State private var isScriptFocused = false

    // Generation lifecycle moved to AppModel.cloneCoordinator (Phase 3b).
    private var coordinator: StudioGenerationCoordinator { appModel.cloneCoordinator }
    private var isGenerating: Bool { coordinator.isGenerating }
    private var errorMessage: String? { coordinator.errorMessage }
    private var lastCompletedOutput: IOSStudioInlinePlayerItem? { coordinator.lastCompletedOutput }

    private var studioGenState: IOSStudioGenState {
        if coordinator.isGenerating {
            // Show the live-preview card once the shared player is actually streaming
            // audible audio; keep the compact generating bar during prepare/buffering.
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

    private func expandInlinePlayer() {
        guard let output = coordinator.lastCompletedOutput else { return }
        presentPlayerSheet(output.playerSheetItem)
    }

    private var referenceChipLabel: String {
        if let voice = selectedVoice { return voice.name }
        if draft.referenceAudioPath != nil { return "Recorded clip" }
        return "Choose reference"
    }

    private var referenceChipAbbreviation: String {
        if let voice = selectedVoice { return IOSStudioChipAbbreviation.initials(voice.name) }
        if draft.referenceAudioPath != nil { return "IM" }
        return IOSStudioChipAbbreviation.placeholder
    }

    private var cloneModel: TTSModel? {
        TTSModel.model(for: .clone)
    }

    private var isModelAvailable: Bool {
        guard let cloneModel else { return false }
        return modelManager.isAvailable(cloneModel)
    }

    private var savedVoices: [Voice] {
        savedVoicesViewModel.voices
    }

    private var selectedVoice: Voice? {
        guard let selectedSavedVoiceID = draft.selectedSavedVoiceID else { return nil }
        return savedVoices.first(where: { $0.id == selectedSavedVoiceID })
    }

    private var clonePrimingRequestKey: String? {
        guard let model = cloneModel,
              ttsEngine.isReady,
              isModelAvailable,
              let referenceAudioPath = draft.referenceAudioPath else {
            return nil
        }
        if let selectedSavedVoiceID = draft.selectedSavedVoiceID,
           hydratedSavedVoiceID != selectedSavedVoiceID,
           transcriptLoadError == nil {
            return nil
        }
        return GenerationSemantics.cloneReferenceIdentityKey(
            modelID: model.id,
            refAudio: referenceAudioPath,
            refText: draft.referenceTranscript.isEmpty ? nil : draft.referenceTranscript
        )
    }

    private var clonePrimingTaskID: String {
        "\(isActive)-\(clonePrimingRequestKey ?? "clone-priming-idle")"
    }

    private var promptText: String {
        IOSGenerationTextLimitPolicy.clamped(draft.text, mode: .clone)
    }

    private var promptTextBinding: Binding<String> {
        Binding(
            get: { promptText },
            set: { draft.text = IOSGenerationTextLimitPolicy.clamped($0, mode: .clone) }
        )
    }

    private var scriptLimitState: IOSGenerationTextLimitPolicy.State {
        IOSGenerationTextLimitPolicy.state(for: promptText, mode: .clone)
    }

    private var allowsExecution: Bool {
        ttsEngine.supportsMode(.clone)
    }

    private var cloneContextStatus: VoiceCloningContextStatus? {
        VoiceCloningContextStatus(
            CloneReferenceContextResolver.resolve(
                hasReference: draft.referenceAudioPath != nil,
                selectedSavedVoiceID: draft.selectedSavedVoiceID,
                hydratedSavedVoiceID: hydratedSavedVoiceID,
                transcriptLoadError: transcriptLoadError,
                expectedPreparationKey: clonePrimingRequestKey,
                preparationState: ttsEngine.clonePreparationState
            )
        )
    }

    private var canGenerate: Bool {
        ttsEngine.isReady
            && cloneConsentAcknowledged
            && allowsExecution
            && isModelAvailable
            && draft.referenceAudioPath != nil
            && !scriptLimitState.trimmedIsEmpty
            && !scriptLimitState.isOverLimit
            && !ttsEngine.hasActiveGeneration
            && !appModel.longForm.isProcessing
    }

    private var setupMessage: String? {
        if !cloneConsentAcknowledged {
            return "Enable voice-cloning consent in Settings before generating."
        }
        if !isModelAvailable, let cloneModel {
            return "Install \(cloneModel.name) in Settings."
        }
        if draft.referenceAudioPath == nil {
            return "Choose a saved voice or record a reference clip on this iPhone."
        }
        if let cloneContextStatus {
            switch cloneContextStatus {
            case .waitingForHydration:
                return "Loading the selected voice."
            case .preparing:
                return "Preparing the reference audio."
            case .primed:
                return nil
            case .fallback(let message):
                return message
            }
        }
        return nil
    }

    /// A compact, visible readiness state in the composer's existing metadata
    /// row. It gives users and XCUITest the same production signal without a
    /// hidden marker or making successful generation depend on proactive work.
    private var cloneModeMetaLabel: String {
        guard draft.referenceAudioPath != nil else { return "Voice cloning" }
        switch cloneContextStatus {
        case .waitingForHydration:
            return "Voice cloning · Loading voice"
        case .preparing:
            return "Voice cloning · Preparing reference"
        case .primed:
            return "Voice cloning · Reference ready"
        case .fallback:
            return "Voice cloning · Prepares on generate"
        case nil:
            return "Voice cloning · Reference selected"
        }
    }

    private var isLongFormActiveHere: Bool {
        appModel.longForm.isProcessing && appModel.longForm.lastMode == .clone
    }

    private var promptHelper: String? {
        if isLongFormActiveHere, !appModel.longForm.progress.helperText.isEmpty {
            return appModel.longForm.progress.helperText
        }
        if !isScriptFocused && promptText.isEmpty {
            return nil
        }
        return scriptLimitState.helperMessage
    }

    private var canGenerateInCurrentRuntime: Bool {
        canGenerate
    }

    private var isGenerationActive: Bool {
        isGenerating || ttsEngine.hasActiveGeneration || isLongFormActiveHere
    }

    @State private var detectedPromptLanguage: Qwen3SupportedLanguage = .auto
    @State private var savedVoiceLanguages: [String: Qwen3SupportedLanguage] = [:]

    var body: some View {
        pageContent
            .task(id: promptText) {
                try? await Task.sleep(for: .milliseconds(350))
                guard !Task.isCancelled else { return }
                detectedPromptLanguage = PromptLanguageDetector.detect(promptText)
            }
            .task(id: savedVoices) {
                await refreshSavedVoiceLanguages()
            }
            .task {
                guard isActive else { return }
                if ttsEngine.isReady {
                    await savedVoicesViewModel.ensureLoaded(using: ttsEngine)
                }
                consumePendingSavedVoiceHandoffIfNeeded()
                syncSavedVoiceSelectionState()
            }
            .task(id: clonePrimingTaskID) {
                guard isActive else {
                    await ttsEngine.cancelClonePreparationIfNeeded()
                    return
                }
                await syncCloneReferencePriming()
            }
            .onChange(of: isActive) { _, active in
                guard active else { return }
                consumePendingSavedVoiceHandoffIfNeeded()
                syncSavedVoiceSelectionState()
            }
            .onChange(of: pendingSavedVoiceHandoff) { _, _ in
                consumePendingSavedVoiceHandoffIfNeeded()
            }
            .onChange(of: savedVoicesViewModel.voices) { _, _ in
                guard isActive else { return }
                syncSavedVoiceSelectionState()
            }
    }

    @ViewBuilder
    private var pageContent: some View {
        VStack(alignment: .leading, spacing: 14) {
            IOSStudioCanvas(
                mode: .clone,
                script: promptTextBinding,
                placeholder: "Type the new text. The reference voice will speak it.",
                modeMetaLabel: cloneModeMetaLabel,
                charLimit: scriptLimitState.displayLimit,
                tint: IOSBrandTheme.clone,
                genState: studioGenState,
                errorMessage: coordinator.errorMessage,
                canGenerate: canGenerateInCurrentRuntime,
                modelInstalled: isModelAvailable,
                modelDisplayName: cloneModel?.name ?? "Voice Cloning model",
                setupChips: { cloneModeChips },
                onGenerate: generate,
                onCancel: {
                    if appModel.longForm.isProcessing {
                        appModel.longForm.cancel(ttsEngine: ttsEngine, audioPlayer: audioPlayer)
                    } else {
                        IOSStudioGenerationActions.cancelGeneration(
                            coordinator: coordinator,
                            ttsEngine: ttsEngine,
                            audioPlayer: audioPlayer
                        )
                    }
                },
                onInstallModel: { selectedTab = .settings },
                onPlayerDismiss: { coordinator.dismissInlinePlayer() },
                onPlayerExpand: expandInlinePlayer
            )
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
    }

    @ViewBuilder
    private var longFormResumeChip: some View {
        if appModel.longForm.canResume, appModel.longForm.lastMode == .clone {
            IOSStudioSetupChip(
                eyebrow: "Long-form",
                value: "Resume project",
                abbreviation: "LF",
                leadingSymbol: "arrow.clockwise",
                tint: IOSBrandTheme.clone,
                accessibilityID: "longform_resumeChip",
                action: {
                    appModel.longForm.resume(
                        ttsEngine: ttsEngine,
                        audioPlayer: audioPlayer,
                        studioCoordinator: coordinator
                    )
                }
            )
        }
    }

    private func startLongFormProject(model: TTSModel, refPath: String) {
        guard !appModel.longForm.isProcessing else { return }
        do {
            let plan = try IOSLongFormCoordinator.plan(originalText: promptText)
            guard plan.segments.count <= IOSLongFormCoordinator.maxSegments else {
                coordinator.fail(
                    "This script plans \(plan.segments.count) segments; the maximum is \(IOSLongFormCoordinator.maxSegments). Split the text and try again."
                )
                return
            }
            appModel.longForm.start(
                request: IOSLongFormProjectRequest(
                    mode: .clone,
                    model: model,
                    plan: plan,
                    voice: referenceChipLabel,
                    emotion: nil,
                    languageHint: draft.selectedLanguage.rawValue,
                    voiceDescription: nil,
                    refAudio: refPath,
                    refText: draft.referenceTranscript.isEmpty ? nil : draft.referenceTranscript,
                    preparedVoiceID: draft.selectedSavedVoiceID
                ),
                ttsEngine: ttsEngine,
                audioPlayer: audioPlayer,
                studioCoordinator: coordinator
            )
        } catch {
            coordinator.fail("Long-form planning failed: \(error.localizedDescription)")
        }
    }

    @ViewBuilder
    private var cloneModeChips: some View {
        longFormResumeChip
        IOSLongFormSegmentsMenuChip(
            mode: .clone,
            tint: IOSBrandTheme.clone,
            appModel: appModel,
            ttsEngine: ttsEngine,
            audioPlayer: audioPlayer,
            studioCoordinator: coordinator
        )
        IOSStudioSetupChip(
            eyebrow: draft.referenceAudioPath == nil ? "Reference" : "Voice",
            value: referenceChipLabel,
            abbreviation: referenceChipAbbreviation,
            // MacOS Voice Cloning glyph is "waveform.badge.plus"; we use plain "waveform" here so
            // the badge's "+" doesn't double up with the unset "+" placeholder (the placeholder is
            // the sole add cue). Constant across set/unset — the value slot conveys the state.
            leadingSymbol: "waveform",
            tint: IOSBrandTheme.clone,
            isPlaceholder: draft.referenceAudioPath == nil,
            accessibilityID: "studioChip_reference",
            action: presentReferencePicker
        )
        IOSStudioSetupChip(
            eyebrow: "Language",
            value: LanguageSelectionPresentation.buttonLabel(
                selected: draft.selectedLanguage,
                detected: detectedPromptLanguage
            ),
            abbreviation: IOSStudioChipAbbreviation.language(
                LanguageSelectionPresentation.effective(
                    selected: draft.selectedLanguage,
                    detected: detectedPromptLanguage
                ).displayName
            ),
            leadingSymbol: "globe",
            tint: IOSBrandTheme.clone,
            accessibilityID: "studioChip_language",
            action: presentCloneLanguagePicker
        )
    }

    private func presentReferencePicker() {
        appModel.presentBottomPanel { bottomSafeAreaInset, availableHeight, dismiss in
            AnyView(
                IOSReferenceClipSheet(
                    savedVoices: savedVoiceOptions,
                    selectedSavedVoiceID: Binding(
                        get: { draft.selectedSavedVoiceID },
                        set: { newValue in
                            guard let id = newValue,
                                  let voice = savedVoices.first(where: { $0.id == id })
                            else { return }
                            applySavedVoice(voice)
                            dismiss()
                        }
                    ),
                    onRequestRecord: {
                        appModel.requestCloneReferenceRecording(afterDismiss: dismiss)
                    },
                    onDismiss: dismiss,
                    presentation: .edgeToEdge(
                        bottomSafeAreaInset: bottomSafeAreaInset,
                        height: IOSBottomSheetChrome.expandedHeight(forScreenHeight: availableHeight)
                    )
                )
            )
        }
    }

    private func presentCloneLanguagePicker() {
        appModel.presentBottomPanel { bottomSafeAreaInset, availableHeight, dismiss in
            AnyView(
                IOSQwenLanguagePickerSheet(
                    selectedLanguage: $draft.selectedLanguage,
                    tint: IOSBrandTheme.clone,
                    recommended: detectedPromptLanguage,
                    onDismiss: dismiss,
                    presentation: .edgeToEdge(
                        bottomSafeAreaInset: bottomSafeAreaInset,
                        height: IOSBottomSheetChrome.expandedHeight(forScreenHeight: availableHeight)
                    )
                )
            )
        }
    }

    private var savedVoiceOptions: [IOSVoicePickerOption] {
        savedVoices.map { voice in
            IOSVoicePickerOption(
                id: voice.id,
                name: voice.name,
                subtitle: "Cloned reference",
                isRecommended: detectedPromptLanguage != .auto
                    && savedVoiceLanguages[voice.id] == detectedPromptLanguage
            )
        }
    }

    /// Infer each saved voice's language from its transcript sidecar (off the main thread), cached
    /// so the reference picker can recommend voices matching the typed prompt. Cheap (a handful of
    /// short text-only NL passes); recomputed only when the saved-voice list changes.
    private func refreshSavedVoiceLanguages() async {
        let entries = savedVoices.map { (id: $0.id, wavPath: $0.wavPath) }
        let map = await Task.detached(priority: .utility) { () -> [String: Qwen3SupportedLanguage] in
            var result: [String: Qwen3SupportedLanguage] = [:]
            for entry in entries {
                let txtURL = URL(fileURLWithPath: entry.wavPath)
                    .deletingPathExtension()
                    .appendingPathExtension("txt")
                guard let transcript = try? String(contentsOf: txtURL, encoding: .utf8) else { continue }
                let language = PromptLanguageDetector.detect(transcript)
                if language != .auto { result[entry.id] = language }
            }
            return result
        }.value
        savedVoiceLanguages = map
    }


    private func consumePendingSavedVoiceHandoffIfNeeded() {
        guard let pendingSavedVoiceHandoff else { return }
        defer { self.pendingSavedVoiceHandoff = nil }

        if let voice = savedVoices.first(where: { $0.id == pendingSavedVoiceHandoff.savedVoiceID }) {
            applySavedVoice(voice)
            let handoffTranscript = pendingSavedVoiceHandoff.transcript
                .trimmingCharacters(in: .whitespacesAndNewlines)
            if draft.referenceTranscript.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
               !handoffTranscript.isEmpty {
                draft.referenceTranscript = handoffTranscript
            }
        } else {
            draft.applySavedVoiceSelection(
                id: pendingSavedVoiceHandoff.savedVoiceID,
                wavPath: pendingSavedVoiceHandoff.wavPath,
                transcript: pendingSavedVoiceHandoff.transcript
            )
            hydratedSavedVoiceID = pendingSavedVoiceHandoff.savedVoiceID
        }

        if pendingSavedVoiceHandoff.language != .auto {
            draft.selectedLanguage = pendingSavedVoiceHandoff.language
        }
        transcriptLoadError = pendingSavedVoiceHandoff.transcriptLoadError
        autoTranscribeReferenceIfNeeded()
        // Covers the fallback branch above that bypasses applySavedVoice.
        primeSelectedCloneVoiceProactively()
    }

    /// Best-effort on-device transcription when the reference sidecar / handoff
    /// transcript is still empty (record→enroll before auto-transcribe finished).
    private func autoTranscribeReferenceIfNeeded() {
        let trimmed = draft.referenceTranscript.trimmingCharacters(in: .whitespacesAndNewlines)
        guard trimmed.isEmpty else { return }
        guard let path = draft.referenceAudioPath else { return }
        Task {
            guard let result = await VoiceClipTranscriber.transcribe(
                url: URL(fileURLWithPath: path)
            ) else { return }
            guard !Task.isCancelled else { return }
            guard draft.referenceAudioPath == path else { return }
            if draft.referenceTranscript.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                draft.referenceTranscript = result.text
            }
            if draft.selectedLanguage == .auto, result.language != .auto {
                draft.selectedLanguage = result.language
            }
        }
    }

    private func generate() {
        guard !scriptLimitState.trimmedIsEmpty, ttsEngine.isReady, !ttsEngine.hasActiveGeneration else { return }
        guard cloneConsentAcknowledged else {
            coordinator.fail("Enable voice-cloning consent in Settings before generating.")
            return
        }
        guard !scriptLimitState.isOverLimit else {
            coordinator.fail(scriptLimitState.warningMessage)
            return
        }
        guard let model = cloneModel else { return }
        guard isModelAvailable else {
            coordinator.fail("Install \(model.name) in Settings to generate audio.")
            return
        }
        if scriptLimitState.routesToLongForm {
            guard let refPath = draft.referenceAudioPath else {
                coordinator.fail("Select a reference audio file before generating.")
                return
            }
            startLongFormProject(model: model, refPath: refPath)
            return
        }
        // Same seed for the live + final card so the decorative waveform doesn't change shape.
        let seed = IOSStableVisualHash.int(promptText)
        coordinator.start(live: IOSStudioLivePreviewItem(
            voiceName: referenceChipLabel,
            modeLabel: "Clone",
            mode: .clone,
            transcript: promptText,
            waveformSeed: seed,
            estimatedAudioDuration: LivePreviewEstimate(text: promptText)?.estimatedAudioDuration ?? 0
        ))
        let generationID = UUID()

        coordinator.generationTask = Task {
            defer {
                Task { @MainActor in
                    if coordinator.isGenerating {
                        coordinator.finish()
                    }
                }
            }
            do {
                ensureSelectedSavedVoiceHydratedIfNeeded()
                guard let refPath = draft.referenceAudioPath else {
                    throw NSError(
                        domain: "QVoice.AppGeneration",
                        code: 4,
                        userInfo: [NSLocalizedDescriptionKey: "Select a reference audio file before generating."]
                    )
                }
                if ttsEngine.clonePreparationState.phase != .failed || ttsEngine.clonePreparationState.identityKey != clonePrimingRequestKey {
                    try? await ttsEngine.ensureCloneReferencePrimed(
                        modelID: model.id,
                        reference: CloneReference(
                            audioPath: refPath,
                            transcript: draft.referenceTranscript.isEmpty ? nil : draft.referenceTranscript,
                            preparedVoiceID: draft.selectedSavedVoiceID
                        )
                    )
                }

                let outputPath = makeOutputPath(subfolder: model.outputSubfolder, text: promptText)
                audioPlayer.setLivePreviewEstimate(LivePreviewEstimate(text: promptText))
                await AppGenerationTimeline.shared.recordSubmitted(
                    id: generationID,
                    mode: GenerationMode.clone.rawValue
                )
                let result = try await ttsEngine.generate(
                    GenerationRequest(
                        mode: .clone,
                        modelID: model.id,
                        text: promptText,
                        outputPath: outputPath,
                        shouldStream: true,
                        streamingInterval: GenerationSemantics.appStreamingInterval,
                        languageHint: draft.selectedLanguage.rawValue,
                        payload: .clone(
                            reference: CloneReference(
                                audioPath: refPath,
                                transcript: draft.referenceTranscript.isEmpty ? nil : draft.referenceTranscript,
                                preparedVoiceID: draft.selectedSavedVoiceID
                            )
                        ),
                        generationID: generationID,
                        variation: IOSGenerationVariationPreference.requestValue()
                    )
                )
                // If the user cancelled while the take was generating, discard it: don't
                // play it, don't persist it as a clip, and remove the orphaned WAV. The
                // engine has already completed + cleaned up via its normal path here (this is
                // iOS-only — it does NOT alter engine lifecycle/loadState), so this just
                // suppresses surfacing an unwanted result. Keeps cancelled takes out of History.
                if Task.isCancelled {
                    await AppGenerationTimeline.shared.recordFailed(
                        id: generationID,
                        finishReason: .cancelled
                    )
                    IOSPullableDiagnosticsMirror.syncGenerationTelemetryIfEnabled(
                        generationID: generationID
                    )
                    try? FileManager.default.removeItem(atPath: result.audioPath)
                    audioPlayer.abortLivePreviewIfNeeded()
                    return
                }
                audioPlayer.completeStreamingPreview(
                    result: result,
                    title: String(promptText.prefix(40)),
                    shouldAutoPlay: AudioService.shouldAutoPlay
                )
                await AppGenerationTimeline.shared.recordCompleted(
                    id: generationID,
                    mode: GenerationMode.clone.rawValue,
                    usedStreaming: true,
                    finishReason: result.finishReason?.rawValue,
                    summary: result.telemetrySummary
                )
                IOSPullableDiagnosticsMirror.syncGenerationTelemetryIfEnabled(
                    generationID: generationID
                )
                let voiceName = selectedVoice?.name ?? URL(fileURLWithPath: refPath).deletingPathExtension().lastPathComponent
                let generation = Generation(
                    text: promptText,
                    mode: model.mode.rawValue,
                    modelTier: model.tier,
                    voice: voiceName,
                    emotion: nil,
                    speed: nil,
                    audioPath: result.audioPath,
                    duration: result.durationSeconds,
                    createdAt: Date()
                )
                GenerationPersistence.persist(
                    generation,
                    caller: "IOSVoiceCloningView"
                )
                IOSSavedOutputsDestination.exportIfConfigured(internalAudioPath: result.audioPath)
                await MainActor.run {
                    coordinator.complete(
                        IOSStudioInlinePlayerItem(
                            generationID: generationID,
                            audioURL: URL(fileURLWithPath: result.audioPath),
                            voiceName: voiceName,
                            modeLabel: "Clone",
                            mode: .clone,
                            transcript: promptText,
                            waveformSeed: seed,
                            autoplay: false,
                            ownedBySharedPlayer: true
                        )
                    )
                }
                IOSHaptics.success()
            } catch is CancellationError {
                await AppGenerationTimeline.shared.recordFailed(
                    id: generationID,
                    finishReason: .cancelled
                )
                IOSPullableDiagnosticsMirror.syncGenerationTelemetryIfEnabled(
                    generationID: generationID
                )
                audioPlayer.abortLivePreviewIfNeeded()
                await MainActor.run { coordinator.errorMessage = nil }
            } catch {
                await AppGenerationTimeline.shared.recordFailed(
                    id: generationID,
                    finishReason: Task.isCancelled ? .cancelled : .failed
                )
                IOSPullableDiagnosticsMirror.syncGenerationTelemetryIfEnabled(
                    generationID: generationID
                )
                audioPlayer.abortLivePreviewIfNeeded()
                if Task.isCancelled {
                    // A user cancel can surface as a wrapped engine error (not a bare
                    // CancellationError) — treat it as a clean cancel, not a failure banner.
                    // iOS-only: does not touch engine lifecycle/cleanup.
                    await MainActor.run { coordinator.errorMessage = nil }
                } else {
                    await MainActor.run { coordinator.fail(error.localizedDescription) }
                    IOSHaptics.warning()
                }
            }
        }
    }

    private func syncCloneReferencePriming() async {
        guard !isGenerationActive else { return }
        guard allowsExecution else {
            await ttsEngine.cancelClonePreparationIfNeeded()
            return
        }
        guard let model = cloneModel,
              let refPath = draft.referenceAudioPath,
              clonePrimingRequestKey != nil else {
            await ttsEngine.cancelClonePreparationIfNeeded()
            return
        }

        if let selectedSavedVoiceID = draft.selectedSavedVoiceID,
           hydratedSavedVoiceID != selectedSavedVoiceID,
           transcriptLoadError == nil {
            await ttsEngine.cancelClonePreparationIfNeeded()
            return
        }

        do {
            try await ttsEngine.ensureCloneReferencePrimed(
                modelID: model.id,
                reference: CloneReference(
                    audioPath: refPath,
                    transcript: draft.referenceTranscript.isEmpty ? nil : draft.referenceTranscript,
                    preparedVoiceID: draft.selectedSavedVoiceID
                )
            )
        } catch {
            if TelemetryGate.resolvedEnabled {
                print("[IOSVoiceCloningView] clone priming failed: \(error.localizedDescription)")
            }
        }
    }

    private func applySavedVoice(_ voice: Voice) {
        do {
            let transcript = try SavedVoiceCloneHydration.loadTranscript(for: voice)
            draft.applySavedVoice(voice, transcript: transcript)
            transcriptLoadError = nil
        } catch {
            draft.applySavedVoice(voice, transcript: "")
            transcriptLoadError = "Couldn't load the saved transcript for \"\(voice.name)\". Cloning can still use the audio."
        }
        hydratedSavedVoiceID = voice.id
        primeSelectedCloneVoiceProactively()
    }

    /// Explicit voice selection is a strong generate-intent signal: ensure the
    /// clone model is resident and the reference prompt is primed while the
    /// user is still looking at the screen, so the first take after a voice
    /// handoff does not pay the model load in-take. Both store calls are
    /// memory-band and thermal gated; the generate task's own
    /// `ensureCloneReferencePrimed` remains the on-demand fallback.
    private func primeSelectedCloneVoiceProactively() {
        guard !ttsEngine.hasActiveGeneration else { return }
        guard let model = TTSModel.model(for: .clone), modelManager.isAvailable(model) else { return }
        let reference = draft.referenceAudioPath.map { path in
            CloneReference(
                audioPath: path,
                transcript: draft.referenceTranscript.isEmpty ? nil : draft.referenceTranscript,
                preparedVoiceID: draft.selectedSavedVoiceID
            )
        }
        Task {
            await ttsEngine.ensureModelLoadedIfNeeded(id: model.id)
            if let reference {
                try? await ttsEngine.ensureCloneReferencePrimed(
                    modelID: model.id,
                    reference: reference
                )
            }
        }
    }

    private func ensureSelectedSavedVoiceHydratedIfNeeded() {
        guard let selectedVoice else { return }
        guard draft.selectedSavedVoiceID == selectedVoice.id else { return }
        guard hydratedSavedVoiceID != selectedVoice.id else { return }
        guard transcriptLoadError == nil else { return }
        applySavedVoice(selectedVoice)
    }

    private func clearReference() {
        draft.clearReference()
        transcriptLoadError = nil
        hydratedSavedVoiceID = nil
    }

    private func syncSavedVoiceSelectionState() {
        if draft.selectedSavedVoiceID != nil,
           selectedVoice == nil,
           savedVoicesViewModel.isLoading || savedVoicesViewModel.loadError != nil {
            return
        }

        switch SavedVoiceCloneHydration.action(
            draft: draft,
            voice: selectedVoice,
            hydratedVoiceID: hydratedSavedVoiceID,
            transcriptLoadError: transcriptLoadError
        ) {
        case .none:
            break
        case .acceptCurrentDraft:
            hydratedSavedVoiceID = selectedVoice?.id
        case .applyFromDisk:
            if let selectedVoice {
                applySavedVoice(selectedVoice)
            }
        case .clearStaleSelection:
            clearReference()
        }
    }
}

private extension VoiceCloningContextStatus {
    init?(_ resolution: CloneReferenceContextResolution?) {
        guard let resolution else { return nil }
        switch resolution {
        case .waitingForHydration:
            self = .waitingForHydration
        case .preparing:
            self = .preparing
        case .primed:
            self = .primed
        case .usableWithoutPriming:
            return nil
        case .degraded(let message):
            self = .fallback(message)
        }
    }
}
