import AppKit
import QwenVoiceCore
import SwiftUI
import UniformTypeIdentifiers

/// Session state of the reference the screen holds beside the draft: which
/// saved voice has been hydrated from disk, a transcript that could not be
/// read, why auto-transcription is unavailable, and the drag target flag.
/// Screen-scoped like the iOS twin; the draft itself lives in `ContentView`.
private struct CloneReferenceSessionState: Equatable {
    var transcriptLoadError: String?
    var hydratedSavedVoiceID: String?
    var transcriptionUnavailableMessage: String?
    var isDragOver = false
    /// A rejected drop (wrong file type); the dock error bar stays for takes.
    var dropError: String?
}

/// Voice Cloning on the iOS Studio canvas (`IOSVoiceCloningView`): the
/// reference chip (saved voices as a menu), the desktop's Import and Record
/// chips, the bank delivery chip for a persona, the Language, pinned-seed and
/// Batch chips, then the reference status, warnings, the transcript field,
/// the inline consent and the readiness line, and the dock. Drag-and-drop
/// import stays. Generation runs on the shared pipeline with the clone
/// request from `MacStudioGenerationRequestFactory`; the clone reference is
/// primed proactively and again on demand before the take. Every
/// `voiceCloning_*`, `textInput_*` and `recordClip_*` identifier is the lane
/// contract.
struct MacVoiceCloningScreen: View {
    @EnvironmentObject private var ttsEngineStore: TTSEngineStore
    @EnvironmentObject private var audioPlayer: AudioPlayerViewModel
    @EnvironmentObject private var savedVoicesViewModel: SavedVoicesViewModel
    @Environment(ModelManagerViewModel.self) private var modelManager
    @Environment(MacAppModel.self) private var appModel

    @AppStorage("vocello.voiceCloningConsent.v1", store: AppDefaults.store)
    private var cloneConsentAcknowledged = false

    @Binding var draft: VoiceCloningDraft
    @Binding var pendingSavedVoiceHandoff: PendingVoiceCloningHandoff?

    @State private var session = CloneReferenceSessionState()
    @State private var transcriptionTask: Task<Void, Never>?
    @State private var detectedPromptLanguage: Qwen3SupportedLanguage = .auto
    @State private var presentedSheet: VoiceCloningPresentedSheet?
    @State private var isRecordSheetPresented = false
    @State private var showsWarningDetails = false

    private let tint = MacTheme.Brand.modeClone

    private var coordinator: StudioGenerationCoordinator { appModel.cloneCoordinator }

    // MARK: - Derived state

    private var cloneModel: TTSModel? {
        modelManager.generationActiveVariant(for: .clone)
    }

    private var isModelAvailable: Bool {
        guard let cloneModel else { return false }
        return modelManager.isAvailable(cloneModel)
    }

    private var modelDisplayName: String {
        cloneModel.map { modelManager.generationVariantDisplayName(for: $0) } ?? MacInterfaceText.workflowNoModel
    }

    private var savedVoices: [Voice] { savedVoicesViewModel.voices }

    private var selectedVoice: Voice? {
        guard let selectedSavedVoiceID = draft.selectedSavedVoiceID else { return nil }
        return savedVoices.first(where: { $0.id == selectedSavedVoiceID })
    }

    private var savedVoicesLoadError: String? {
        guard let loadError = savedVoicesViewModel.loadError else { return nil }
        return MacInterfaceText.cloningSavedVoicesLoadError(loadError)
    }

    /// Emotion banks group by naming convention alone; the reference chip shows
    /// one row per persona and the delivery chip picks the member voice.
    private var bankCatalog: VoiceBankCatalog {
        MacVoiceBankCatalogCache.catalog(for: savedVoices.map { (id: $0.id, name: $0.name) })
    }

    private var selectedBankPersona: VoiceBankCatalog.Persona? {
        bankCatalog.persona(containing: draft.selectedSavedVoiceID)
    }

    private var isGenerationActive: Bool {
        coordinator.isGenerating || ttsEngineStore.hasActiveGeneration
    }

    private var canRunBatch: Bool {
        ttsEngineStore.isReady
            && cloneConsentAcknowledged
            && draft.referenceAudioPath != nil
            && isModelAvailable
            && !ttsEngineStore.hasActiveGeneration
    }

    private var canGenerate: Bool {
        ttsEngineStore.isReady
            && cloneConsentAcknowledged
            && isModelAvailable
            && draft.referenceAudioPath != nil
            && draft.hasText
            && !ttsEngineStore.hasActiveGeneration
            && !coordinator.isGenerating
    }

    private var clonePrimingRequestKey: String? {
        guard let model = cloneModel,
              ttsEngineStore.isReady,
              isModelAvailable,
              let referenceAudioPath = draft.referenceAudioPath else {
            return nil
        }
        if let selectedSavedVoiceID = draft.selectedSavedVoiceID,
           session.hydratedSavedVoiceID != selectedSavedVoiceID,
           session.transcriptLoadError == nil {
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
                hydratedSavedVoiceID: session.hydratedSavedVoiceID,
                transcriptLoadError: session.transcriptLoadError,
                expectedPreparationKey: clonePrimingRequestKey,
                preparationState: ttsEngineStore.clonePreparationState
            )
        )
    }

    private var readinessDescriptor: VoiceCloningReadinessDescriptor {
        MacVoiceCloningReadiness.describe(
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

    private var referenceChipValue: String {
        if let voice = selectedVoice {
            if let persona = bankCatalog.persona(containing: voice.id) { return persona.name }
            return voice.name
        }
        if let path = draft.referenceAudioPath {
            return URL(fileURLWithPath: path).deletingPathExtension().lastPathComponent
        }
        return MacInterfaceText.cloningChooseSavedVoice
    }

    private var modeMetaLabel: String {
        var parts = [MacInterfaceText.modeName(.clone)]
        if let cloneModel {
            parts.append(modelManager.generationVariantDisplayName(for: cloneModel))
        }
        return parts.joined(separator: " · ")
    }

    // MARK: - Body

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            MacStudioCanvas(
                mode: .clone,
                accessibilityPrefix: "voiceCloning",
                script: $draft.text,
                placeholder: MacInterfaceText.cloningScriptPlaceholder,
                modeMetaLabel: modeMetaLabel,
                readiness: MacStudioReadinessState(
                    isReady: readinessDescriptor.noteIsReady && !isGenerationActive,
                    title: isGenerationActive
                        ? MacInterfaceText.customGeneratingFinalAudio
                        : readinessDescriptor.title,
                    detail: isGenerationActive
                        ? MacInterfaceText.customGeneratingFinalAudioDetail
                        : readinessDescriptor.detail,
                    accessibilityIdentifier: "voiceCloning_readiness"
                ),
                tint: tint,
                genState: studioGenState,
                errorMessage: coordinator.errorMessage,
                canGenerate: canGenerate,
                canRunBatch: canRunBatch,
                modelInstalled: isModelAvailable,
                setupChips: { setupChips },
                footer: { chipFooter },
                onGenerate: generate,
                onBatch: { presentedSheet = .batch(.clone(draft: draft, voice: selectedVoice?.name)) },
                onCancel: cancelGeneration,
                onInstallModel: openSettingsForModel,
                onPlayerDismiss: { coordinator.dismissInlinePlayer() }
            )
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
        .overlay {
            if session.isDragOver {
                VocelloShape.card()
                    .stroke(tint.opacity(0.5), lineWidth: VocelloTheme.Stroke.focus)
                    .padding(MacTheme.Spacing.sm)
                    .allowsHitTesting(false)
            }
        }
        .onDrop(of: [.fileURL], isTargeted: $session.isDragOver) { providers in
            handleDrop(providers)
        }
        .accessibilityIdentifier("screen_voiceCloning")
        .onAppear {
            reconcileGenerationVariantSelection()
            consumePendingSavedVoiceHandoffIfNeeded()
        }
        .task(id: draft.text) {
            try? await Task.sleep(for: .milliseconds(350))
            guard !Task.isCancelled else { return }
            let detected = PromptLanguageDetector.detect(draft.text)
            if detected != detectedPromptLanguage {
                detectedPromptLanguage = detected
            }
        }
        .task(id: savedVoicesLoadTaskID) {
            guard ttsEngineStore.isReady else { return }
            if draft.selectedSavedVoiceID != nil {
                await savedVoicesViewModel.refresh(using: ttsEngineStore)
            } else {
                await savedVoicesViewModel.ensureLoaded(using: ttsEngineStore)
            }
            syncSavedVoiceSelectionState()
        }
        .onChange(of: savedVoicesViewModel.voices) { _, _ in syncSavedVoiceSelectionState() }
        .task(id: clonePrimingTaskID) {
            await syncCloneReferencePriming()
        }
        .onChange(of: modelManager.statuses) { _, _ in reconcileGenerationVariantSelection() }
        .onChange(of: modelManager.activeVariantRevision) { _, _ in reconcileGenerationVariantSelection() }
        .onChange(of: pendingSavedVoiceHandoff) { _, _ in consumePendingSavedVoiceHandoffIfNeeded() }
        .onReceive(NotificationCenter.default.publisher(for: NSApplication.didBecomeActiveNotification)) { _ in
            // The user may have just granted speech recognition in System
            // Settings: clear the hint and retry the transcript auto-fill.
            refreshTranscriptionAvailability()
        }
        .onDisappear {
            transcriptionTask?.cancel()
            transcriptionTask = nil
        }
        .sheet(item: $presentedSheet) { presentedSheet in
            switch presentedSheet {
            case .batch(let configuration):
                MacBatchGenerationSheet(configuration: configuration)
                .environmentObject(ttsEngineStore)
                .environmentObject(audioPlayer)
            }
        }
        .sheet(isPresented: $isRecordSheetPresented) {
            MacRecordVoiceSheet { url in
                replaceReference(with: url.path)
            }
        }
    }


    // MARK: - Chips (two rows: the reference and its sources, then the take)

    /// A flat list, like the other two Studio screens. It used to be a VStack
    /// of two nested `MacChipFlow`s, which broke: the canvas already lays these
    /// out in a `MacChipFlow`, and a flow measures its subviews at unspecified
    /// width. The outer flow therefore sized this one child for the two rows it
    /// reports unconstrained, while at 720 pt under doubled text it needed
    /// three — so the language chip drew outside the height reserved for it,
    /// on top of the permission caption and the reference clip card.
    @ViewBuilder
    private var setupChips: some View {
        MacStudioChipContainer(accessibilityIdentifier: "voiceCloning_voiceSetup") { referenceChip }
        MacStudioActionChip(
            eyebrow: MacInterfaceText.cloningReferenceSection,
            value: draft.referenceAudioPath == nil ? MacInterfaceText.cloningImport : MacInterfaceText.cloningReplace,
            leadingSymbol: "waveform.badge.plus",
            tint: tint,
            accessibilityIdentifier: "voiceCloning_importButton",
            action: browseForAudio
        )
        MacStudioActionChip(
            eyebrow: MacInterfaceText.cloningReferenceSection,
            value: MacInterfaceText.recordRecord,
            leadingSymbol: "mic.fill",
            tint: tint,
            accessibilityIdentifier: "voiceCloning_recordReferenceButton",
            action: { isRecordSheetPresented = true }
        )
        if let persona = selectedBankPersona {
            bankDeliveryChip(persona)
        }
        MacStudioChipContainer(accessibilityIdentifier: "voiceCloning_languageSetup") {
            MacStudioLanguageChip(
                selectedLanguage: $draft.selectedLanguage,
                detectedLanguage: detectedPromptLanguage,
                tint: tint,
                accessibilityIdentifier: "voiceCloning_languagePicker"
            )
        }
        MacSeedPinChip(pinnedSeed: $draft.pinnedSeed, tint: tint)
    }

    private struct SourceEntry: Identifiable {
        let id: String
        let label: String
    }

    /// One entry per standalone voice plus one per persona, in library order;
    /// a persona row carries the currently selected member (or its base).
    private var sourceEntries: [SourceEntry] {
        let catalog = bankCatalog
        var representedPersonas = Set<String>()
        var entries: [SourceEntry] = []
        for voice in savedVoices {
            if let persona = catalog.persona(containing: voice.id) {
                guard representedPersonas.insert(persona.baseVoiceID).inserted else { continue }
                let tag: String
                if let selectedSavedVoiceID = draft.selectedSavedVoiceID, persona.contains(voiceID: selectedSavedVoiceID) {
                    tag = selectedSavedVoiceID
                } else {
                    tag = persona.baseVoiceID
                }
                entries.append(SourceEntry(id: tag, label: MacInterfaceText.cloningVoiceBankEntry(persona.name)))
            } else {
                let name = voice.name.replacingOccurrences(of: "_", with: " ")
                entries.append(SourceEntry(
                    id: voice.id,
                    label: voice.hasTranscript
                        ? MacInterfaceText.cloningEntryTranscript(name)
                        : MacInterfaceText.cloningEntryAudioOnly(name)
                ))
            }
        }
        return entries
    }

    private var referenceChip: some View {
        MacStudioSetupChip(
            eyebrow: draft.selectedSavedVoiceID == nil ? MacInterfaceText.cloningReferenceSection : MacInterfaceText.cloningSavedVoice,
            value: referenceChipValue,
            leadingSymbol: "waveform",
            tint: tint,
            isPlaceholder: draft.referenceAudioPath == nil,
            accessibilityIdentifier: "voiceCloning_savedVoicePicker",
            accessibilityValue: selectedVoice?.name
        ) {
            if savedVoices.isEmpty {
                Text(MacInterfaceText.cloningNoReference)
            } else {
                ForEach(sourceEntries) { entry in
                    Toggle(
                        entry.label,
                        isOn: Binding(
                            get: { draft.selectedSavedVoiceID == entry.id },
                            set: { _ in selectSavedVoice(id: entry.id) }
                        )
                    )
                }
            }
            Divider()
            Button(MacInterfaceText.cloningImport, action: browseForAudio)
            Button(MacInterfaceText.recordRecord) { isRecordSheetPresented = true }
            if draft.referenceAudioPath != nil || draft.selectedSavedVoiceID != nil {
                Divider()
                Button(MacInterfaceText.clear, role: .destructive, action: clearReference)
            }
        }
    }

    private func bankDeliveryChip(_ persona: VoiceBankCatalog.Persona) -> some View {
        let selectedID = draft.selectedSavedVoiceID
        let label = selectedID.flatMap { persona.presetID(for: $0) }.flatMap { EmotionPreset.preset(id: $0)?.label }
            ?? MacInterfaceText.deliveryNeutral
        return MacStudioSetupChip(
            eyebrow: MacInterfaceText.delivery,
            value: label,
            leadingSymbol: "theatermasks",
            tint: tint,
            accessibilityIdentifier: "voiceCloning_bankDeliveryPicker",
            accessibilityValue: label
        ) {
            Toggle(
                MacInterfaceText.deliveryNeutral,
                isOn: Binding(
                    get: { selectedID == persona.baseVoiceID },
                    set: { _ in selectSavedVoice(id: persona.baseVoiceID) }
                )
            )
            ForEach(persona.orderedVariants, id: \.voiceID) { variant in
                Toggle(
                    EmotionPreset.preset(id: variant.presetID)?.label ?? variant.presetID.capitalized,
                    isOn: Binding(
                        get: { selectedID == variant.voiceID },
                        set: { _ in selectSavedVoice(id: variant.voiceID) }
                    )
                )
            }
        }
    }

    // MARK: - Footer rows under the chips

    @ViewBuilder
    private var chipFooter: some View {
        Label(MacInterfaceText.cloningPermittedClipsOnly, systemImage: "hand.raised")
            .macType(.caption)
            .foregroundStyle(MacTheme.Text.secondary)
            .accessibilityIdentifier("voiceCloning_consentNotice")

        referenceStatus

        if let savedVoicesLoadError {
            warningCard(
                message: savedVoicesLoadError,
                accessibilityIdentifier: "voiceCloning_savedVoicesWarning",
                actionLabel: MacInterfaceText.retry,
                actionAccessibilityIdentifier: "voiceCloning_savedVoicesRetry"
            ) {
                let store = ttsEngineStore
                let viewModel = savedVoicesViewModel
                Task { @MainActor in await viewModel.refresh(using: store) }
            }
        }

        if let transcriptLoadError = session.transcriptLoadError {
            warningCard(message: transcriptLoadError, accessibilityIdentifier: "voiceCloning_transcriptWarning")
        }

        if let dropError = session.dropError {
            warningCard(message: dropError, accessibilityIdentifier: "voiceCloning_dropWarning")
        }

        if draft.referenceAudioPath != nil {
            transcriptField
            if let unavailableMessage = session.transcriptionUnavailableMessage {
                Label(unavailableMessage, systemImage: "waveform.badge.mic")
                    .macType(.caption)
                    .foregroundStyle(MacTheme.Text.secondary)
                    .fixedSize(horizontal: false, vertical: true)
                    .accessibilityIdentifier("voiceCloning_transcriptionUnavailable")
            }
        }

        if !cloneConsentAcknowledged, !isGenerationActive {
            // Inline one-time consent: the Settings toggle stays the persistent
            // record; this writes the same stored key at the moment of first use.
            HStack(alignment: .center, spacing: MacTheme.Spacing.snug) {
                Button {
                    cloneConsentAcknowledged = true
                } label: {
                    Label(MacInterfaceText.settingsCloneConsent, systemImage: "checkmark.circle")
                }
                .buttonStyle(MacSettingsActionButtonStyle(tint: tint, prominence: .primary))
                .accessibilityIdentifier("voiceCloning_inlineConsent")
                Text(MacInterfaceText.cloningConsentOneTime)
                    .macType(.caption)
                    .foregroundStyle(MacTheme.Text.secondary)
                    .lineLimit(2)
            }
        }

    }

    @ViewBuilder
    private var referenceStatus: some View {
        if let path = draft.referenceAudioPath {
            HStack(spacing: MacTheme.Spacing.sm) {
                Image(systemName: "checkmark.circle.fill")
                    .macType(.rowTitle)
                    .foregroundStyle(tint)

                VStack(alignment: .leading, spacing: MacTheme.Spacing.xs) {
                    Text(URL(fileURLWithPath: path).lastPathComponent)
                        .macType(.rowTitle)
                        .foregroundStyle(MacTheme.Text.primary)
                        .lineLimit(1)

                    if let token = selectedVoice?.qualityWarnings.first,
                       let shortLabel = MacInterfaceText.qualityWarningShortLabel(token: token) {
                        warningChip(token: token, shortLabel: shortLabel)
                    } else {
                        Text(referenceDetail)
                            .macType(.rowMeta)
                            .foregroundStyle(MacTheme.Text.secondary)
                    }
                }

                Spacer(minLength: 0)

                Button(MacInterfaceText.clear) {
                    AppLaunchConfiguration.performAnimated(MacTheme.Motion.stateChange) {
                        clearReference()
                    }
                }
                .buttonStyle(MacSettingsActionButtonStyle(tint: tint))
            }
            .padding(.horizontal, MacTheme.Spacing.snug)
            .padding(.vertical, MacTheme.Spacing.sm)
            .background {
                VocelloShape.input()
                    .fill(Color.white.opacity(0.04))
            }
            .overlay {
                VocelloShape.input()
                    .stroke(MacTheme.Surface.hairline, lineWidth: VocelloTheme.Stroke.hairline)
            }
            .accessibilityElement(children: .contain)
            .accessibilityIdentifier("voiceCloning_activeReference")
        } else {
            Label(MacInterfaceText.cloningNoReference, systemImage: "waveform.badge.exclamationmark")
                .macType(.caption)
                .foregroundStyle(MacTheme.Text.secondary)
        }
    }

    private var referenceDetail: String {
        guard let selectedVoice else { return MacInterfaceText.cloningImportedFileReady }
        return selectedVoice.hasTranscript
            ? MacInterfaceText.cloningTranscriptBackedSavedVoice
            : MacInterfaceText.cloningAudioOnlySavedVoice
    }

    private func warningChip(token: String, shortLabel: String) -> some View {
        Button {
            showsWarningDetails = true
        } label: {
            HStack(spacing: MacTheme.Spacing.xs) {
                Image(systemName: "exclamationmark.triangle.fill")
                    .macType(.badge)
                Text(shortLabel)
                    .macType(.badge)
                Image(systemName: "chevron.right")
                    .font(.system(size: 7, weight: .semibold))
                    .opacity(0.7)
            }
            .foregroundStyle(MacTheme.Status.guarded)
        }
        .buttonStyle(.plain)
        .accessibilityIdentifier("voiceCloning_referenceWarning")
        .accessibilityHint(
            selectedVoice?.qualityWarnings.first.flatMap(PreparedVoiceQualityWarning.headline(for:)) ?? shortLabel
        )
        .popover(isPresented: $showsWarningDetails, arrowEdge: .top) {
            VStack(alignment: .leading, spacing: MacTheme.Spacing.snug) {
                Label(MacInterfaceText.voicesReferenceOutsideRange, systemImage: "exclamationmark.triangle.fill")
                    .macType(.screenTitle)
                    .foregroundStyle(MacTheme.Status.guarded)
                Text(PreparedVoiceQualityWarning.summary(for: selectedVoice?.qualityWarnings ?? [token]))
                    .macType(.body)
                    .fixedSize(horizontal: false, vertical: true)
            }
            .padding(MacTheme.Spacing.lg)
            .frame(maxWidth: 340)
        }
    }

    /// Wraps rather than truncates. This is the string that has to match the
    /// reference clip, and on one line it cut mid-word even at the widest
    /// window this display can show -- so the one field whose whole purpose is
    /// to be checked was the one field you could not read. Three lines, then it
    /// scrolls; the label holds the first baseline so it does not float beside
    /// a growing box.
    private var transcriptField: some View {
        HStack(alignment: .firstTextBaseline, spacing: MacTheme.Spacing.snug) {
            Text(MacInterfaceText.cloningTranscriptAccessibility)
                .macType(.caption)
                .foregroundStyle(MacTheme.Text.secondary)
            TextField(
                MacInterfaceText.cloningTranscriptPlaceholder,
                text: $draft.referenceTranscript,
                axis: .vertical
            )
                .lineLimit(1 ... 3)
                .textFieldStyle(.plain)
                .macType(.body)
                .foregroundStyle(MacTheme.Text.primary)
                .vocelloFocusRing(tint, radius: MacTheme.Radius.input)
                .padding(.horizontal, MacTheme.Spacing.md)
                .padding(.vertical, MacTheme.Spacing.sm)
                .background {
                    VocelloShape.input()
                        .fill(MacTheme.Surface.field)
                }
                .overlay {
                    VocelloShape.input()
                        .stroke(MacTheme.Surface.fieldStroke, lineWidth: VocelloTheme.Stroke.hairline)
                }
                .accessibilityLabel(MacInterfaceText.cloningTranscriptAccessibility)
                .accessibilityIdentifier("voiceCloning_transcriptInput")
        }
        .help(MacInterfaceText.cloningTranscriptHelp)
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("voiceCloning_transcriptField")
    }

    private func warningCard(
        message: String,
        accessibilityIdentifier: String,
        actionLabel: String? = nil,
        actionAccessibilityIdentifier: String? = nil,
        action: (() -> Void)? = nil
    ) -> some View {
        HStack(alignment: .top, spacing: MacTheme.Spacing.snug) {
            Image(systemName: "exclamationmark.triangle.fill")
                .foregroundStyle(MacTheme.Status.guarded)
                .macType(.captionEmphasis)
            VStack(alignment: .leading, spacing: MacTheme.Spacing.tight) {
                Text(message)
                    .macType(.caption)
                    .foregroundStyle(MacTheme.Text.secondary)
                    .fixedSize(horizontal: false, vertical: true)
                if let actionLabel, let action {
                    Button(actionLabel, action: action)
                        .buttonStyle(MacSettingsActionButtonStyle(tint: tint))
                        .accessibilityIdentifier(actionAccessibilityIdentifier ?? "")
                }
            }
            Spacer(minLength: 0)
        }
        .padding(MacTheme.Spacing.snug)
        .background {
            VocelloShape.input()
                .fill(MacTheme.Status.guarded.opacity(0.10))
        }
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier(accessibilityIdentifier)
    }

    // MARK: - Reference actions

    private func selectSavedVoice(id: String) {
        guard let voice = savedVoices.first(where: { $0.id == id }) else { return }
        applySavedVoice(voice)
    }

    private func applySavedVoice(_ voice: Voice) {
        do {
            let transcript = try SavedVoiceCloneHydration.loadTranscript(for: voice)
            draft.applySavedVoice(voice, transcript: transcript)
            session.transcriptLoadError = nil
        } catch {
            draft.applySavedVoice(voice, transcript: "")
            session.transcriptLoadError = MacInterfaceText.cloningTranscriptLoadFailed(voice.name)
        }
        session.hydratedSavedVoiceID = voice.id
    }

    private func ensureSelectedSavedVoiceHydratedIfNeeded() {
        guard let selectedVoice else { return }
        guard draft.selectedSavedVoiceID == selectedVoice.id else { return }
        guard session.hydratedSavedVoiceID != selectedVoice.id else { return }
        guard session.transcriptLoadError == nil else { return }
        applySavedVoice(selectedVoice)
    }

    private func clearReference() {
        draft.clearReference()
        session.transcriptLoadError = nil
        session.hydratedSavedVoiceID = nil
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
            hydratedVoiceID: session.hydratedSavedVoiceID,
            transcriptLoadError: session.transcriptLoadError
        ) {
        case .none:
            break
        case .acceptCurrentDraft:
            session.hydratedSavedVoiceID = selectedVoice?.id
        case .applyFromDisk:
            if let selectedVoice {
                applySavedVoice(selectedVoice)
            }
        case .clearStaleSelection:
            clearReference()
        }
    }

    private func consumePendingSavedVoiceHandoffIfNeeded() {
        guard let handoff = pendingSavedVoiceHandoff else { return }
        // A handoff is a path plus a promise that the file is there, and the
        // promise is made before this screen is ever shown: the user picks a
        // saved voice on another screen and this consumes it on appear. In
        // between, the voice can be deleted, the file can be moved, or the
        // volume holding it can go away. Applying it unchecked stages Clone
        // against a reference that is not there, and the failure surfaces
        // later as an unexplained generation error.
        guard FileManager.default.fileExists(atPath: handoff.wavPath) else {
            session.dropError = MacInterfaceText.cloningSavedVoiceUnavailable
            pendingSavedVoiceHandoff = nil
            return
        }
        draft.applySavedVoiceSelection(id: handoff.savedVoiceID, wavPath: handoff.wavPath, transcript: handoff.transcript)
        session.transcriptLoadError = handoff.transcriptLoadError
        session.hydratedSavedVoiceID = handoff.savedVoiceID
        pendingSavedVoiceHandoff = nil
    }

    private func browseForAudio() {
        let panel = NSOpenPanel()
        panel.allowedContentTypes = VoiceCloningReferenceAudioSupport.openPanelContentTypes
        panel.allowsMultipleSelection = false
        if panel.runModal() == .OK, let url = panel.url {
            replaceReference(with: url.path)
        }
    }

    /// The item provider resolves on its own queue, seconds later on a slow
    /// volume; the completion touches only the draft and session boxes, never
    /// the environment of a view value that may no longer be installed.
    private func handleDrop(_ providers: [NSItemProvider]) -> Bool {
        guard let provider = providers.first else { return false }
        let allowedExtensions = VoiceCloningReferenceAudioSupport.allowedFileExtensions
        let supportedFormats = VoiceCloningReferenceAudioSupport.supportedFormatDescription
        provider.loadItem(forTypeIdentifier: UTType.fileURL.identifier, options: nil) { data, _ in
            guard let data = data as? Data,
                  let url = URL(dataRepresentation: data, relativeTo: nil) else { return }
            let ext = url.pathExtension.lowercased()
            let path = url.path
            let rejection: String? = allowedExtensions.contains(ext)
                ? nil
                : MacInterfaceText.cloningUnsupportedFile(ext, supportedFormats)
            Task { @MainActor in
                session.dropError = rejection
                if rejection == nil { replaceReference(with: path) }
            }
        }
        return true
    }

    /// A transcript hydrated from a saved voice belongs to the old audio, so it
    /// clears with the selection; a hand-typed transcript is kept.
    private func replaceReference(with path: String) {
        if draft.selectedSavedVoiceID != nil {
            draft.referenceTranscript = ""
        }
        draft.referenceAudioPath = path
        draft.selectedSavedVoiceID = nil
        session.transcriptLoadError = nil
        session.hydratedSavedVoiceID = nil
        autoTranscribeReference(path: path)
    }

    /// Best-effort on-device transcription of a fresh reference clip (saved
    /// voices hydrate their sidecar instead). Fills the transcript only if it
    /// is still empty when the pass finishes; the reference language never
    /// selects the target language.
    private func autoTranscribeReference(path: String) {
        transcriptionTask?.cancel()
        guard draft.referenceTranscript.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { return }
        switch VoiceClipTranscriber.availability() {
        case .denied:
            session.transcriptionUnavailableMessage = MacInterfaceText.cloningSpeechRecognitionOff
            return
        case .siriDisabled:
            session.transcriptionUnavailableMessage = MacInterfaceText.cloningSiriRequired
            return
        case .available, .notDetermined:
            session.transcriptionUnavailableMessage = nil
        }
        transcriptionTask = Task { @MainActor in
            guard let result = await VoiceClipTranscriber.transcribe(url: URL(fileURLWithPath: path)) else { return }
            guard !Task.isCancelled else { return }
            guard draft.referenceAudioPath == path else { return }
            if draft.referenceTranscript.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                draft.referenceTranscript = result.text
            }
        }
    }

    private func refreshTranscriptionAvailability() {
        guard session.transcriptionUnavailableMessage != nil else { return }
        switch VoiceClipTranscriber.availability() {
        case .available, .notDetermined:
            session.transcriptionUnavailableMessage = nil
            if let path = draft.referenceAudioPath {
                autoTranscribeReference(path: path)
            }
        case .denied, .siriDisabled:
            break
        }
    }

    // MARK: - Priming

    private func syncCloneReferencePriming() async {
        // With proactive warmup suppressed (benchmarks), a cold Clone take
        // records its own model load and conditioning.
        guard !MacGenerationWarmupCoordinator.isSuppressed else { return }
        guard !coordinator.isGenerating, !ttsEngineStore.hasActiveGeneration else { return }
        guard let model = cloneModel,
              isModelAvailable,
              let refPath = draft.referenceAudioPath,
              clonePrimingRequestKey != nil else {
            await ttsEngineStore.cancelClonePreparationIfNeeded()
            return
        }
        if let selectedSavedVoiceID = draft.selectedSavedVoiceID,
           session.hydratedSavedVoiceID != selectedSavedVoiceID,
           session.transcriptLoadError == nil {
            await ttsEngineStore.cancelClonePreparationIfNeeded()
            return
        }
        do {
            try await ttsEngineStore.ensureCloneReferencePrimed(
                modelID: model.id,
                reference: CloneReference(
                    audioPath: refPath,
                    transcript: draft.trimmedReferenceTranscript,
                    preparedVoiceID: draft.selectedSavedVoiceID
                )
            )
        } catch {
            if DebugMode.isEnabled {
                print("[Performance][MacVoiceCloningScreen] clone priming failed: \(error.localizedDescription)")
            }
        }
    }

    // MARK: - Generation

    private func reconcileGenerationVariantSelection() {
        modelManager.reconcileGenerationVariantSelectionIfNeeded(for: .clone)
    }

    private func openSettingsForModel() {
        appModel.pendingHighlightedMode = .clone
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
        // Every precondition is checked before the attempt starts, so the
        // generating state never flickers on a rejected start.
        guard draft.hasText, ttsEngineStore.isReady, !ttsEngineStore.hasActiveGeneration else { return }
        guard !coordinator.isGenerating else { return }
        guard cloneConsentAcknowledged else {
            coordinator.rejectStart(MacInterfaceText.cloningConsentDetail)
            return
        }
        guard let model = cloneModel else { return }
        guard isModelAvailable else {
            coordinator.rejectStart(modelManager.recoveryDetail(for: model))
            return
        }

        ensureSelectedSavedVoiceHydratedIfNeeded()
        let currentDraft = draft
        guard let refPath = currentDraft.referenceAudioPath else {
            coordinator.rejectStart(MacInterfaceText.cloningReferenceRequired)
            return
        }
        if LongTextGenerationRouter.shouldRouteToLongFormBatch(currentDraft.text) {
            presentedSheet = .batch(.clone(
                draft: currentDraft, voice: selectedVoice?.name, initialText: currentDraft.text, initialSegmentationMode: .longForm
            ))
            return
        }

        let text = currentDraft.text
        let voiceName = selectedVoice?.name ?? URL(fileURLWithPath: refPath).deletingPathExtension().lastPathComponent
        let modeLabel = MacInterfaceText.modeName(.clone)
        let waveformSeed = VocelloStableVisualHash.int(text)
        let primingKey = clonePrimingRequestKey
        guard let attempt = coordinator.start(live: IOSStudioLivePreviewItem(
            voiceName: voiceName,
            modeLabel: modeLabel,
            mode: .clone,
            transcript: text,
            waveformSeed: waveformSeed,
            estimatedAudioDuration: LivePreviewEstimate(text: text)?.estimatedAudioDuration ?? 0
        )) else { return }

        let reference = CloneReference(
            audioPath: refPath,
            transcript: currentDraft.trimmedReferenceTranscript,
            preparedVoiceID: currentDraft.selectedSavedVoiceID
        )
        let request = MacStudioGenerationRequestFactory.voiceClone(
            modelID: model.id,
            text: text,
            outputPath: makeOutputPath(subfolder: model.outputSubfolder, text: text),
            language: currentDraft.selectedLanguage,
            referenceAudioPath: refPath,
            referenceTranscript: currentDraft.trimmedReferenceTranscript,
            preparedVoiceID: currentDraft.selectedSavedVoiceID,
            seed: currentDraft.pinnedSeed,
            variation: GenerationVariationPreference.requestValue()
        )
        let hooks = MacStudioSingleTakeGenerationHooks(engine: ttsEngineStore, audioPlayer: audioPlayer)
        let store = ttsEngineStore
        let coordinator = coordinator
        let task = Task { @MainActor in
            defer { coordinator.finish(attempt: attempt) }
            do {
                let primedReferenceMatches = store.clonePreparationState.isPrimed
                    && store.clonePreparationState.key == primingKey
                if !primedReferenceMatches {
                    do {
                        try await store.ensureCloneReferencePrimed(modelID: model.id, reference: reference)
                    } catch {
                        if DebugMode.isEnabled {
                            print("[Performance][MacVoiceCloningScreen] clone priming degraded: \(error.localizedDescription)")
                        }
                    }
                }
                guard let request else {
                    throw MacVoiceCloningScreenError.requestConstructionFailed
                }
                let plan = try IOSSingleTakeGenerationPlan(
                    request: request,
                    modelTier: model.tier,
                    historyVoice: voiceName,
                    historyEmotion: nil,
                    displayVoiceName: voiceName,
                    modeLabel: modeLabel,
                    waveformSeed: waveformSeed,
                    persistenceCaller: "MacVoiceCloningScreen"
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

/// Defensive error for an invariant the sync prefix already validated.
private enum MacVoiceCloningScreenError: LocalizedError {
    case requestConstructionFailed

    var errorDescription: String? {
        switch self {
        case .requestConstructionFailed: MacInterfaceText.cloningReferenceRequired
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
