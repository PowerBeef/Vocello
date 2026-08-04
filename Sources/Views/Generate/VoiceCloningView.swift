import QwenVoiceCore
import QwenVoiceNative
import SwiftUI
import UniformTypeIdentifiers

enum VoiceCloningReferenceAudioSupport {
    static let allowedFileExtensions: Set<String> = [
        "wav", "mp3", "aiff", "aif", "m4a", "flac", "ogg", "webm",
    ]

    static let supportedFormatDescription = "WAV, MP3, AIFF, M4A, FLAC, OGG, or WebM"

    static let webMType = UTType(filenameExtension: "webm")
        ?? UTType(mimeType: "audio/webm")
        ?? UTType(mimeType: "video/webm")

    static let openPanelContentTypes: [UTType] = {
        var seen = Set<String>()
        var types: [UTType] = []

        func append(_ type: UTType) {
            if seen.insert(type.identifier).inserted {
                types.append(type)
            }
        }

        append(.audio)

        for ext in allowedFileExtensions.sorted() where ext != "webm" {
            if let type = UTType(filenameExtension: ext) {
                append(type)
            }
        }

        if let webMType {
            append(webMType)
        }

        return types
    }()
}

struct VoiceCloningView: View {
    @AppStorage("vocello.voiceCloningConsent.v1", store: AppDefaults.store)
    private var cloneConsentAcknowledged = false
    @Binding private var draft: VoiceCloningDraft
    @Binding private var pendingSavedVoiceHandoff: PendingVoiceCloningHandoff?
    @State private var coordinator = VoiceCloningCoordinator()

    @ObservedObject private var ttsEngineStore: TTSEngineStore
    private var modelManager: ModelManagerViewModel
    private let audioPlayer: AudioPlayerViewModel
    private let savedVoicesViewModel: SavedVoicesViewModel

    private var cloneModel: TTSModel? {
        modelManager.generationActiveVariant(for: .clone)
    }

    private var isModelAvailable: Bool {
        guard let cloneModel else { return false }
        return modelManager.isAvailable(cloneModel)
    }

    private var modelDisplayName: String {
        cloneModel.map(modelManager.generationVariantDisplayName) ?? "Unknown"
    }

    private var canRunBatch: Bool {
        ttsEngineStore.isReady
            && cloneConsentAcknowledged
            && draft.referenceAudioPath != nil
            && isModelAvailable
            && !ttsEngineStore.hasActiveGeneration
    }

    private var isGenerationActive: Bool {
        coordinator.isGenerating || ttsEngineStore.hasActiveGeneration
    }

    private var clonePrimingRequestKey: String? {
        guard let model = cloneModel,
              ttsEngineStore.isReady,
              isModelAvailable,
              let referenceAudioPath = draft.referenceAudioPath else {
            return nil
        }
        if let selectedSavedVoiceID = draft.selectedSavedVoiceID,
           coordinator.hydratedSavedVoiceID != selectedSavedVoiceID,
           coordinator.transcriptLoadError == nil {
            return nil
        }
        return GenerationSemantics.clonePreparationKey(
            modelID: model.id,
            reference: CloneReference(
                audioPath: referenceAudioPath,
                transcript: draft.trimmedReferenceTranscript,
                preparedVoiceID: draft.selectedSavedVoiceID
            )
        )
    }

    private var clonePrimingTaskID: String {
        clonePrimingRequestKey ?? "clone-priming-idle"
    }

    private var cloneContextStatus: VoiceCloningContextStatus? {
        VoiceCloningContextStatus(
            CloneReferenceContextResolver.resolve(
                hasReference: draft.referenceAudioPath != nil,
                selectedSavedVoiceID: draft.selectedSavedVoiceID,
                hydratedSavedVoiceID: coordinator.hydratedSavedVoiceID,
                transcriptLoadError: coordinator.transcriptLoadError,
                expectedPreparationKey: clonePrimingRequestKey,
                preparationState: ttsEngineStore.clonePreparationState
            )
        )
    }

    private var readinessDescriptor: VoiceCloningReadinessDescriptor {
        VoiceCloningReadiness.describe(
            engineReady: ttsEngineStore.isReady,
            isModelAvailable: isModelAvailable,
            modelDisplayName: modelDisplayName,
            cloneConsentAcknowledged: cloneConsentAcknowledged,
            referenceAudioPath: draft.referenceAudioPath,
            hasReferenceTranscript: draft.trimmedReferenceTranscript != nil,
            text: draft.text,
            contextStatus: cloneContextStatus
        )
    }

    private var savedVoicesLoadTaskID: String {
        "\(ttsEngineStore.isReady)-\(draft.selectedSavedVoiceID ?? "none")"
    }

    private var savedVoices: [Voice] {
        savedVoicesViewModel.voices
    }

    private var selectedVoice: Voice? {
        guard let selectedSavedVoiceID = draft.selectedSavedVoiceID else { return nil }
        return savedVoices.first(where: { $0.id == selectedSavedVoiceID })
    }

    private var savedVoicesLoadError: String? {
        guard let loadError = savedVoicesViewModel.loadError else { return nil }
        return "Couldn't load saved voices right now. You can still clone from a file. \(loadError)"
    }

    private var selectedSavedVoiceID: Binding<String?> {
        Binding(
            get: { draft.selectedSavedVoiceID },
            set: { newID in
                guard let newID else {
                    if draft.referenceAudioPath != nil || draft.selectedSavedVoiceID != nil {
                        coordinator.clearReference(draft: $draft)
                    }
                    return
                }

                guard let voice = savedVoices.first(where: { $0.id == newID }) else { return }
                coordinator.selectSavedVoice(voice, draft: $draft)
            }
        )
    }

    private var isDragOverBinding: Binding<Bool> {
        Binding(
            get: { coordinator.isDragOver },
            set: { coordinator.isDragOver = $0 }
        )
    }

    init(
        draft: Binding<VoiceCloningDraft>,
        pendingSavedVoiceHandoff: Binding<PendingVoiceCloningHandoff?>,
        ttsEngineStore: TTSEngineStore,
        audioPlayer: AudioPlayerViewModel,
        modelManager: ModelManagerViewModel,
        savedVoicesViewModel: SavedVoicesViewModel
    ) {
        _draft = draft
        _pendingSavedVoiceHandoff = pendingSavedVoiceHandoff
        _ttsEngineStore = ObservedObject(wrappedValue: ttsEngineStore)
        self.modelManager = modelManager
        self.audioPlayer = audioPlayer
        self.savedVoicesViewModel = savedVoicesViewModel
    }

    static func shouldStartDeferredClonePrewarm(
        clonePreparationState: ClonePreparationState,
        expectedKey: String?,
        isGenerating: Bool
    ) -> Bool {
        clonePreparationState.isPrimed
            && clonePreparationState.key == expectedKey
            && !isGenerating
    }

    @State private var isRecordSheetPresented = false
    /// Language detected from the typed script; floats the matching language
    /// to a "Recommended" section in the language picker.
    @State private var detectedPromptLanguage: Qwen3SupportedLanguage = .auto

    var body: some View {
        PageScaffold(
            accessibilityIdentifier: "screen_voiceCloning",
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
        .modeGlassTint(AppTheme.voiceCloning)
        .modeCanvasBackdrop(AppTheme.voiceCloning)
        .onDrop(of: [.fileURL], isTargeted: isDragOverBinding) { providers in
            coordinator.handleDrop(providers, draft: $draft)
        }
        .overlay(
            coordinator.isDragOver
                ? RoundedRectangle(cornerRadius: 18, style: .continuous)
                    .stroke(AppTheme.voiceCloning.opacity(0.5), lineWidth: 2)
                    .padding(8)
                : nil
        )
        .task(id: savedVoicesLoadTaskID) {
            guard ttsEngineStore.isReady else { return }

            if draft.selectedSavedVoiceID != nil {
                await savedVoicesViewModel.refresh(using: ttsEngineStore)
            } else {
                await savedVoicesViewModel.ensureLoaded(using: ttsEngineStore)
            }

            coordinator.syncSavedVoiceSelectionState(
                draft: $draft,
                selectedVoice: selectedVoice,
                savedVoicesViewModel: savedVoicesViewModel
            )
        }
        .onChange(of: savedVoicesViewModel.voices) { _, _ in
            coordinator.syncSavedVoiceSelectionState(
                draft: $draft,
                selectedVoice: selectedVoice,
                savedVoicesViewModel: savedVoicesViewModel
            )
        }
        .task(id: clonePrimingTaskID) {
            await coordinator.syncCloneReferencePriming(
                draft: draft,
                cloneModel: cloneModel,
                isModelAvailable: isModelAvailable,
                clonePrimingRequestKey: clonePrimingRequestKey,
                ttsEngineStore: ttsEngineStore
            )
        }
        .onAppear(perform: handleAppear)
        .onAppear { detectedPromptLanguage = PromptLanguageDetector.detect(draft.text) }
        .onChange(of: draft.text) { _, newText in
            let detected = PromptLanguageDetector.detect(newText)
            if detected != detectedPromptLanguage {
                detectedPromptLanguage = detected
            }
        }
        .onChange(of: modelManager.statuses) { _, _ in reconcileGenerationVariantSelection() }
        .onChange(of: modelManager.activeVariantRevision) { _, _ in reconcileGenerationVariantSelection() }
        .onChange(of: pendingSavedVoiceHandoff) { _, _ in
            coordinator.consumePendingSavedVoiceHandoffIfNeeded(
                draft: $draft,
                pendingSavedVoiceHandoff: $pendingSavedVoiceHandoff
            )
        }
        .onReceive(NotificationCenter.default.publisher(for: NSApplication.didBecomeActiveNotification)) { _ in
            // The user may have just granted speech recognition in System
            // Settings — clear the hint and retry the transcript auto-fill.
            coordinator.refreshTranscriptionAvailability(draft: $draft)
        }
        .onDisappear {
            coordinator.cancelPendingTranscription()
        }
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
                .environmentObject(ttsEngineStore)
                .environmentObject(audioPlayer)
            }
        }
        .sheet(isPresented: $isRecordSheetPresented) {
            RecordReferenceClipSheet { url in
                coordinator.replaceReference(with: url.path, draft: $draft)
            }
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

// MARK: - Panel Layout

private extension VoiceCloningView {
    var configurationPanel: some View {
        CompactConfigurationSection(
            title: "Reference",
            iconName: "slider.horizontal.3",
            accentColor: AppTheme.voiceCloning,
            trailingText: nil,
            trailingAccessory: AnyView(variantSelector),
            rowSpacing: LayoutConstants.generationConfigurationRowSpacing,
            panelPadding: LayoutConstants.generationConfigurationPanelPadding
        ) {
            VStack(alignment: .leading, spacing: 0) {
                VoiceCloningReferenceSettings(
                    savedVoices: savedVoices,
                    selectedSavedVoiceID: selectedSavedVoiceID,
                    referenceAudioPath: draft.referenceAudioPath,
                    selectedVoice: selectedVoice,
                    savedVoicesLoadError: savedVoicesLoadError,
                    transcriptLoadError: coordinator.transcriptLoadError,
                    browseForAudio: { coordinator.browseForAudio(draft: $draft) },
                    recordReference: { isRecordSheetPresented = true },
                    clearReference: { coordinator.clearReference(draft: $draft) },
                    retrySavedVoices: { Task { await savedVoicesViewModel.refresh(using: ttsEngineStore) } }
                )
                VoiceCloningTranscriptSettings(referenceTranscript: $draft.referenceTranscript)
                if let unavailableMessage = coordinator.transcriptionUnavailableMessage {
                    GenerationSetupHint(
                        message: unavailableMessage,
                        accessibilityIdentifier: "voiceCloning_transcriptionUnavailable"
                    )
                }
                languageSettings
            }
        }
        .fixedSize(horizontal: false, vertical: true)
    }

    var variantSelector: some View {
        GenerationVariantSelector(
            mode: .clone,
            modelManager: modelManager,
            accentColor: AppTheme.voiceCloning,
            accessibilityPrefix: "voiceCloning",
            isDisabled: isGenerationActive
        )
    }

    var composerPanel: some View {
        StudioSectionCard(
            title: "Script",
            iconName: "text.alignleft",
            accentColor: AppTheme.voiceCloning,
            trailingText: isGenerationActive ? "Generating" : readinessDescriptor.trailingText,
            fillsAvailableHeight: true,
            accessibilityIdentifier: "voiceCloning_script"
        ) {
            VStack(alignment: .leading, spacing: LayoutConstants.generationConfigurationRowSpacing) {
                TextInputView(
                    text: $draft.text,
                    isGenerating: isGenerationActive,
                    placeholder: "Type the line for the cloned voice",
                    buttonColor: AppTheme.voiceCloning,
                    batchAction: { coordinator.presentBatch(draft: draft) },
                    batchDisabled: !canRunBatch,
                    generateDisabled: !ttsEngineStore.isReady
                        || !cloneConsentAcknowledged
                        || !isModelAvailable
                        || draft.referenceAudioPath == nil
                        || !draft.hasText
                        || ttsEngineStore.hasActiveGeneration,
                    isEmbedded: true,
                    usesFlexibleEmbeddedHeight: true,
                    onGenerate: {
                        guard cloneConsentAcknowledged else { return }
                        coordinator.generate(
                            draft: $draft,
                            cloneModel: cloneModel,
                            isModelAvailable: isModelAvailable,
                            clonePrimingRequestKey: clonePrimingRequestKey,
                            selectedVoice: selectedVoice,
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

                VoiceCloningComposerFooter(
                    isReadyForFastGenerate: readinessDescriptor.noteIsReady,
                    readinessTitle: readinessDescriptor.title,
                    readinessDetail: readinessDescriptor.detail,
                    isGenerating: isGenerationActive,
                    errorMessage: coordinator.errorMessage
                )
            }
            .frame(maxHeight: .infinity, alignment: .topLeading)
        }
        .frame(maxHeight: .infinity, alignment: .topLeading)
        .accessibilityElement(children: .contain)
    }

    var languageSettings: some View {
        // The side-label row's 92pt caption column can't fit a "· Auto"
        // suffix (the caption-above columns carry it elsewhere), so while
        // the selector follows detection the auto state rides the hint slot.
        QwenLanguagePickerRow(
            selectedLanguage: $draft.selectedLanguage,
            accentColor: AppTheme.voiceCloning,
            accessibilityPrefix: "voiceCloning",
            hint: LanguageSelectionPresentation.isFollowingDetection(
                selected: draft.selectedLanguage,
                detected: detectedPromptLanguage
            ) ? "Auto · detected from your script." : nil,
            showsDefaultHelp: false,
            recommended: detectedPromptLanguage
        )
    }
}

private extension VoiceCloningView {
    func handleAppear() {
        reconcileGenerationVariantSelection()
        coordinator.handleAppear(
            draft: $draft,
            pendingSavedVoiceHandoff: $pendingSavedVoiceHandoff
        )
    }

    func reconcileGenerationVariantSelection() {
        modelManager.reconcileGenerationVariantSelectionIfNeeded(for: .clone)
    }
}

// MARK: - Reference Settings

private struct VoiceCloningReferenceSettings: View {
    let savedVoices: [Voice]
    @Binding var selectedSavedVoiceID: String?
    let referenceAudioPath: String?
    let selectedVoice: Voice?
    let savedVoicesLoadError: String?
    let transcriptLoadError: String?
    let browseForAudio: () -> Void
    let recordReference: () -> Void
    let clearReference: () -> Void
    let retrySavedVoices: () -> Void

    var body: some View {
        GenerationSetupRow(
            label: "Source",
            accessibilityIdentifier: "voiceCloning_voiceSetup"
        ) {
            CloneSourceRow(
                savedVoices: savedVoices,
                selectedSavedVoiceID: $selectedSavedVoiceID,
                browseForAudio: browseForAudio,
                recordReference: recordReference,
                referenceAudioPath: referenceAudioPath
            )
        } supporting: {
            GenerationSetupHint(
                message: "Use permitted clips only.",
                accessibilityIdentifier: "voiceCloning_consentNotice"
            )
            CloneReferenceStatus(
                referenceAudioPath: referenceAudioPath,
                selectedVoice: selectedVoice,
                clearReference: clearReference,
                accentColor: AppTheme.voiceCloning
            )

            if let savedVoicesLoadError {
                CloneWarningCard(
                    message: savedVoicesLoadError,
                    actionLabel: "Retry",
                    action: retrySavedVoices,
                    accentColor: AppTheme.voiceCloning,
                    accessibilityIdentifier: "voiceCloning_savedVoicesWarning",
                    actionAccessibilityIdentifier: "voiceCloning_savedVoicesRetry"
                )
            }

            if let transcriptLoadError {
                CloneWarningCard(
                    message: transcriptLoadError,
                    actionLabel: nil,
                    action: nil,
                    accentColor: AppTheme.voiceCloning,
                    accessibilityIdentifier: "voiceCloning_transcriptWarning",
                    actionAccessibilityIdentifier: nil
                )
            }
        }
    }
}

// MARK: - Transcript Settings

private struct VoiceCloningTranscriptSettings: View {
    @Binding var referenceTranscript: String

    var body: some View {
        GenerationSetupRow(
            label: "Transcript",
            accessibilityIdentifier: "voiceCloning_transcriptField"
        ) {
            TextField(
                "What does the reference audio say? (optional)",
                text: $referenceTranscript
            )
            .textFieldStyle(.plain)
            .focusEffectDisabled()
            .padding(.horizontal, 8)
            .padding(.vertical, 6)
            .frame(maxWidth: .infinity, alignment: .leading)
            .glassTextField(radius: 10)
            .accessibilityLabel("Transcript")
            .accessibilityIdentifier("voiceCloning_transcriptInput")
        }
        .help("Best quality uses reference audio plus an accurate transcript. Audio-only cloning remains available as a lower-guidance fallback.")
    }
}

// MARK: - Composer Footer

private struct VoiceCloningComposerFooter: View {
    let isReadyForFastGenerate: Bool
    let readinessTitle: String
    let readinessDetail: String
    let isGenerating: Bool
    let errorMessage: String?

    var body: some View {
        VStack(alignment: .leading, spacing: LayoutConstants.compactGap) {
            WorkflowReadinessNote(
                isReady: isReadyForFastGenerate && !isGenerating,
                title: isGenerating ? "Generating final audio" : readinessTitle,
                detail: isGenerating ? "Rendering the complete take. The file lands in the player when ready." : readinessDetail,
                accentColor: AppTheme.voiceCloning,
                isBusy: isGenerating,
                accessibilityIdentifier: "voiceCloning_readiness"
            )

            if let errorMessage {
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
}

// MARK: - Reference Status

private struct CloneReferenceStatus: View {
    let referenceAudioPath: String?
    let selectedVoice: Voice?
    let clearReference: () -> Void
    let accentColor: Color

    @State private var showsWarningDetails = false

    var body: some View {
        if let path = referenceAudioPath {
            HStack(spacing: 8) {
                Image(systemName: "checkmark.circle.fill")
                    .font(.system(size: 14, weight: .semibold))
                    .foregroundStyle(accentColor)

                VStack(alignment: .leading, spacing: 3) {
                    Text(URL(fileURLWithPath: path).lastPathComponent)
                        .font(.system(size: 12, weight: .semibold))
                        .lineLimit(1)

                    if let token = selectedVoice?.qualityWarnings.first,
                       let shortLabel = PreparedVoiceQualityWarning.shortLabel(for: token) {
                        warningChip(token: token, shortLabel: shortLabel)
                    } else {
                        Text(referenceDetail)
                            .font(.system(size: 10, weight: .medium))
                            .foregroundStyle(.secondary)
                    }
                }

                Spacer(minLength: 0)

                Button("Clear") {
                    AppLaunchConfiguration.performAnimated(.default) {
                        clearReference()
                    }
                }
                .buttonStyle(.bordered)
                .controlSize(.small)
            }
            .inlinePanel(padding: 8, radius: 10)
            .accessibilityIdentifier("voiceCloning_activeReference")
        } else {
            HStack(spacing: 6) {
                Image(systemName: "waveform.badge.exclamationmark")
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(.secondary)
                Text("No reference selected.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            .padding(.vertical, 1)
        }
    }

    private var referenceDetail: String {
        guard let selectedVoice else {
            return "Imported file ready"
        }
        return selectedVoice.hasTranscript
            ? "Transcript-backed saved voice"
            : "Audio-only saved voice"
    }

    @ViewBuilder
    private func warningChip(token: String, shortLabel: String) -> some View {
        // Inline (no-capsule) variant of the saved-voices warning chip
        // — the capsule background + stroke + 3 pt vertical padding
        // would make this row ~6-10 pt taller than the 10 pt "Saved
        // voice ready" Text it replaces, which would shift every
        // element below it (Transcript label, Transcript field) down.
        // Keeping the row height identical to the no-warning state
        // means the saved-voice panel renders at a constant total
        // height regardless of warning presence, so the Transcript
        // position is invariant.
        Button {
            showsWarningDetails = true
        } label: {
            HStack(spacing: 4) {
                Image(systemName: "exclamationmark.triangle.fill")
                    .font(.system(size: 9))
                Text(shortLabel)
                    .font(.system(size: 10, weight: .medium))
                Image(systemName: "chevron.right")
                    .font(.system(size: 7, weight: .semibold))
                    .opacity(0.7)
            }
            .foregroundStyle(.orange)
        }
        .buttonStyle(.plain)
        .accessibilityIdentifier("voiceCloning_referenceWarning")
        .accessibilityHint(selectedVoice?.qualityHeadline ?? shortLabel)
        .popover(isPresented: $showsWarningDetails, arrowEdge: .top) {
            warningDetailsPopover(warnings: selectedVoice?.qualityWarnings ?? [token])
        }
    }

    @ViewBuilder
    private func warningDetailsPopover(warnings: [String]) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            Label("Reference outside recommended range",
                  systemImage: "exclamationmark.triangle.fill")
                .font(.headline)
                .foregroundStyle(.orange)
            Text(PreparedVoiceQualityWarning.summary(for: warnings))
                .font(.callout)
                .fixedSize(horizontal: false, vertical: true)
        }
        .padding(16)
        .frame(maxWidth: 340)
    }
}

// MARK: - Source Row

private struct CloneSourceRow: View {
    let savedVoices: [Voice]
    @Binding var selectedSavedVoiceID: String?
    let browseForAudio: () -> Void
    let recordReference: () -> Void
    let referenceAudioPath: String?

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            ViewThatFits(in: .horizontal) {
                HStack(alignment: .center, spacing: 8) {
                    if !savedVoices.isEmpty {
                        savedVoicePicker
                    }

                    importButton
                    recordButton

                    Spacer(minLength: 0)
                }

                VStack(alignment: .leading, spacing: 6) {
                    if !savedVoices.isEmpty {
                        savedVoicePicker
                    }

                    importButton
                    recordButton
                }
            }

            bankDeliveryPicker
        }
        .help("Choose a saved voice, import a reference clip, or record one with your microphone. Use clips you own or have permission to clone.")
    }

    /// Emotion reference banks group by naming convention alone
    /// ("<Persona>" + "<Persona> (<Emotion>)"); the picker shows one row per
    /// persona and a delivery selector picks the concrete member voice, so
    /// selection always flows through the ordinary saved-voice path.
    private var bankCatalog: VoiceBankCatalog {
        VoiceBankCatalog.build(voices: savedVoices.map { (id: $0.id, name: $0.name) })
    }

    private struct SourceEntry: Identifiable {
        let id: String
        let label: String
    }

    /// One entry per standalone voice plus one per persona, in library order.
    /// A persona row is tagged with the currently selected member (falling
    /// back to its base), so the menu selection always matches a live tag
    /// while the delivery picker moves between members.
    private var sourceEntries: [SourceEntry] {
        let catalog = bankCatalog
        var representedPersonas = Set<String>()
        var entries: [SourceEntry] = []
        for voice in savedVoices {
            if let persona = catalog.persona(containing: voice.id) {
                guard representedPersonas.insert(persona.baseVoiceID).inserted else { continue }
                let tag: String
                if let selectedSavedVoiceID, persona.contains(voiceID: selectedSavedVoiceID) {
                    tag = selectedSavedVoiceID
                } else {
                    tag = persona.baseVoiceID
                }
                entries.append(SourceEntry(id: tag, label: "\(persona.name) · voice bank"))
            } else {
                entries.append(SourceEntry(
                    id: voice.id,
                    label: voice.hasTranscript ? "\(voice.name) · transcript" : "\(voice.name) · audio only"
                ))
            }
        }
        return entries
    }

    @ViewBuilder
    private var savedVoicePicker: some View {
        if !savedVoices.isEmpty {
            Picker("Saved voice", selection: $selectedSavedVoiceID) {
                Text("Choose a saved voice")
                    .tag(Optional<String>.none)

                ForEach(sourceEntries) { entry in
                    Text(entry.label)
                        .tag(Optional(entry.id))
                }
            }
            .labelsHidden()
            .pickerStyle(.menu)
            .focusEffectDisabled()
            .frame(minWidth: LayoutConstants.configurationControlMinWidth, maxWidth: 180, alignment: .leading)
            .accessibilityValue(savedVoices.first(where: { $0.id == selectedSavedVoiceID })?.name ?? "")
            .accessibilityIdentifier("voiceCloning_savedVoicePicker")
        }
    }

    @ViewBuilder
    private var bankDeliveryPicker: some View {
        if let selectedSavedVoiceID,
           let persona = bankCatalog.persona(containing: selectedSavedVoiceID) {
            HStack(alignment: .center, spacing: 8) {
                Text("Delivery")
                    .font(.footnote.weight(.semibold))
                    .foregroundStyle(.secondary)

                Picker("Delivery", selection: $selectedSavedVoiceID) {
                    Text("Neutral")
                        .tag(Optional(persona.baseVoiceID))

                    ForEach(persona.orderedVariants, id: \.voiceID) { variant in
                        Text(EmotionPreset.preset(id: variant.presetID)?.label ?? variant.presetID.capitalized)
                            .tag(Optional(variant.voiceID))
                    }
                }
                .labelsHidden()
                .pickerStyle(.menu)
                .focusEffectDisabled()
                .frame(minWidth: 110, maxWidth: 160, alignment: .leading)
                .accessibilityValue(persona.presetID(for: selectedSavedVoiceID).flatMap { EmotionPreset.preset(id: $0)?.label } ?? "Neutral")
                .accessibilityIdentifier("voiceCloning_bankDeliveryPicker")
            }
        }
    }

    private var importButton: some View {
        Button {
            browseForAudio()
        } label: {
            Label(referenceAudioPath == nil ? "Import" : "Replace", systemImage: "waveform.badge.plus")
                .font(.system(size: 12, weight: .semibold))
        }
        .buttonStyle(.bordered)
        .tint(AppTheme.voiceCloning)
        .controlSize(.small)
        .accessibilityIdentifier("voiceCloning_importButton")
    }

    private var recordButton: some View {
        Button {
            recordReference()
        } label: {
            Label("Record", systemImage: "mic.fill")
                .font(.system(size: 12, weight: .semibold))
        }
        .buttonStyle(.bordered)
        .tint(AppTheme.voiceCloning)
        .controlSize(.small)
        .accessibilityIdentifier("voiceCloning_recordReferenceButton")
    }
}

// MARK: - Warning Card

private struct CloneWarningCard: View {
    let message: String
    let actionLabel: String?
    let action: (() -> Void)?
    let accentColor: Color
    let accessibilityIdentifier: String
    let actionAccessibilityIdentifier: String?

    var body: some View {
        HStack(alignment: .top, spacing: 10) {
            Image(systemName: "exclamationmark.triangle.fill")
                .foregroundStyle(.orange)
                .font(.subheadline.weight(.semibold))

            VStack(alignment: .leading, spacing: 6) {
                Text(message)
                    .font(.callout)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)

                if let actionLabel, let action {
                    Button(actionLabel) {
                        action()
                    }
                    .buttonStyle(.bordered)
                    .tint(accentColor)
                    .controlSize(.small)
                    .accessibilityIdentifier(actionAccessibilityIdentifier ?? "")
                }
            }

            Spacer(minLength: 0)
        }
        .inlinePanel(padding: 12, radius: 12)
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier(accessibilityIdentifier)
    }
}
