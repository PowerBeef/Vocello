import AppKit
import QwenVoiceCore
import SwiftUI

struct SavedVoiceCloneHandoffPlan: Equatable {
    let handoff: PendingVoiceCloningHandoff
    let cloneModelID: String?
}

/// The macOS window: the sidebar (`SidebarView`) beside the selected screen,
/// the destination-specific window toolbar, and the shell state in
/// `MacAppModel`. Screens are hosted one per sidebar item; the legacy screens
/// remain until each is replaced by its iOS-derived successor (CONV-12 to
/// CONV-17).
@MainActor
struct ContentView: View {
    @Environment(ModelManagerViewModel.self) private var modelManager
    /// Plain reference, deliberately NOT `@EnvironmentObject` (W1-D): the
    /// root shell must not subscribe to the whole engine store; every use
    /// below is imperative, and the only body-relevant signal is the gate,
    /// which `gateModel` republishes flip-scoped. Descendant screens keep
    /// their own environment-object injection.
    private let ttsEngineStore: TTSEngineStore
    @StateObject private var gateModel: GenerationPerformanceGateModel
    @Environment(SavedVoicesViewModel.self) private var savedVoicesViewModel
    @EnvironmentObject private var appCommandRouter: AppCommandRouter

    @State private var appModel: MacAppModel
    @State private var customVoiceDraft = CustomVoiceDraft()
    @State private var voiceDesignDraft = VoiceDesignDraft()
    @State private var voiceCloningDraft = VoiceCloningDraft()
    @State private var pendingVoiceCloningHandoff: PendingVoiceCloningHandoff?
    @State private var didCompleteInitialAvailabilityRefresh = false
    @StateObject private var generationWarmupCoordinator = MacGenerationWarmupCoordinator()

    private var disabledSidebarItems: Set<SidebarItem> {
        Set(SidebarItem.generationItems.filter { !$0.isAvailable(using: modelManager) })
    }

    private var canUseSavedVoicesInVoiceCloning: Bool {
        modelManager.hasInstalledVariant(for: .clone)
    }

    private var sidebarSelectionBinding: Binding<SidebarItem?> {
        Binding(
            get: { appModel.selectedItem },
            set: { newValue in
                guard let newValue else { return }
                selectSidebarItemIfEnabled(newValue)
            }
        )
    }

    init(ttsEngineStore: TTSEngineStore) {
        self.ttsEngineStore = ttsEngineStore
        _gateModel = StateObject(
            wrappedValue: GenerationPerformanceGateModel(store: ttsEngineStore)
        )
        let appModel = MacAppModel()
        var initialDraft = VoiceCloningDraft()
        if let storedVoiceID = appModel.restoredVoiceCloningSavedVoiceID {
            initialDraft.selectedSavedVoiceID = storedVoiceID
        }
        _appModel = State(initialValue: appModel)
        _voiceCloningDraft = State(initialValue: initialDraft)
    }

    static func savedVoiceCloneHandoffPlan(
        for voice: Voice,
        cloneModelID: String?,
        transcriptLoader: (Voice) throws -> String = { voice in
            try SavedVoiceCloneHydration.loadTranscript(for: voice)
        }
    ) -> SavedVoiceCloneHandoffPlan {
        let handoff: PendingVoiceCloningHandoff
        do {
            let transcript = try transcriptLoader(voice)
            handoff = PendingVoiceCloningHandoff(
                savedVoiceID: voice.id,
                wavPath: voice.wavPath,
                transcript: transcript,
                transcriptLoadError: nil
            )
        } catch {
            handoff = PendingVoiceCloningHandoff(
                savedVoiceID: voice.id,
                wavPath: voice.wavPath,
                transcript: "",
                transcriptLoadError: "Couldn't load the saved transcript for \"\(voice.name)\". You can still clone from the audio file alone."
            )
        }

        return SavedVoiceCloneHandoffPlan(
            handoff: handoff,
            cloneModelID: cloneModelID?.trimmingCharacters(in: .whitespacesAndNewlines)
        )
    }

    var body: some View {
        @Bindable var appModel = appModel
        NavigationSplitView {
            SidebarView(
                selection: sidebarSelectionBinding,
                disabledItems: disabledSidebarItems
            )
            .navigationSplitViewColumnWidth(
                min: MacShellMetrics.sidebarMinWidth,
                ideal: MacShellMetrics.sidebarIdealWidth,
                max: MacShellMetrics.sidebarMaxWidth
            )
        } detail: {
            detailContent
        }
        .toolbar {
            MacWindowToolbar(
                selectedItem: appModel.selectedItem,
                historySortOrder: $appModel.historySortOrder,
                historySearchText: $appModel.historySearchText,
                historyClearRequest: $appModel.historyClearRequest,
                voicesEnrollRequestID: $appModel.voicesEnrollRequestID
            )
        }
        .navigationSplitViewStyle(.balanced)
        .environment(appModel)
        // Generation performance gate (OPTIMIZATION.md §K): while the engine
        // generates, glass surfaces fall back to the solid-fill design so the
        // material's continuous compositor work stops competing with MLX for
        // the GPU (measured 1.37 with glass vs 1.84 solid on the 8 GB tier).
        // Read through the flip-scoped gate model (W1-D), never the store.
        .environment(\.generationPerformanceGate, gateModel.isActive)
        .task { await handleInitialLoad() }
        .onChange(of: appModel.selectedItem) { _, newValue in handleSelectionChange(newValue) }
        .onChange(of: customVoiceDraft) { _, _ in handleGenerationDraftChange() }
        .onChange(of: voiceDesignDraft) { _, _ in handleGenerationDraftChange() }
        .onChange(of: voiceCloningDraft) { _, _ in handleGenerationDraftChange() }
        .onChange(of: voiceCloningDraft.selectedSavedVoiceID) { _, newValue in
            appModel.persistVoiceCloningSavedVoiceID(newValue)
        }
        .onChange(of: modelManager.statuses) { _, _ in handleStatusesChange() }
        .onChange(of: modelManager.activeVariantRevision) { _, _ in handleActiveVariantChange() }
        // `onReceive`, not `onChange`: `onChange(of:)` would need the
        // snapshot read in body, which would track the store (W1-D/W2-A).
        // The store's explicit bridge fires only on applied changes.
        .onReceive(ttsEngineStore.snapshotChanges) { newSnapshot in
            handleEngineSnapshotChange(newSnapshot)
        }
        .onReceive(appCommandRouter.sidebarSelection) { item in
            selectSidebarItemIfEnabled(item)
        }
    }

    @ViewBuilder
    private var detailContent: some View {
        Group {
            if let selectedItem = appModel.selectedItem {
                screenView(for: selectedItem)
                    .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
            } else {
                Color.clear
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .profileBackground(Color(nsColor: .windowBackgroundColor))
    }

    @ViewBuilder
    private func screenView(for item: SidebarItem) -> some View {
        @Bindable var appModel = appModel
        switch item {
        case .customVoice:
            CustomVoiceScreenHost(draft: $customVoiceDraft)
        case .voiceDesign:
            VoiceDesignScreenHost(draft: $voiceDesignDraft)
        case .voiceCloning:
            VoiceCloningScreenHost(
                draft: $voiceCloningDraft,
                pendingSavedVoiceHandoff: $pendingVoiceCloningHandoff
            )
        case .history:
            MacHistoryScreen(
                ttsEngineStore: ttsEngineStore,
                searchText: $appModel.historySearchText,
                sortOrder: $appModel.historySortOrder,
                clearRequest: $appModel.historyClearRequest,
                onPinSeed: { generation in
                    guard let seedValue = generation.samplingSeed else { return }
                    // Pin into the take's own mode and surface that mode so
                    // the composer chip makes the new state visible.
                    switch generation.mode {
                    case GenerationMode.custom.rawValue:
                        customVoiceDraft.pinnedSeed = seedValue
                        selectSidebarItemIfEnabled(.customVoice)
                    case GenerationMode.design.rawValue:
                        voiceDesignDraft.pinnedSeed = seedValue
                        selectSidebarItemIfEnabled(.voiceDesign)
                    case GenerationMode.clone.rawValue:
                        voiceCloningDraft.pinnedSeed = seedValue
                        selectSidebarItemIfEnabled(.voiceCloning)
                    default:
                        break
                    }
                }
            )
        case .voices:
            VoicesView(
                enrollRequestID: appModel.voicesEnrollRequestID,
                canUseInVoiceCloning: canUseSavedVoicesInVoiceCloning,
                onUseInVoiceCloning: { voice in
                    let cloneModel = modelManager.generationActiveVariant(for: .clone)
                    let plan = Self.savedVoiceCloneHandoffPlan(
                        for: voice,
                        cloneModelID: cloneModel.flatMap { model in
                            modelManager.isAvailable(model) ? model.id : nil
                        }
                    )
                    startSavedVoiceCloningHandoff(plan)
                }
            )
        case .settings:
            SettingsView(
                highlightedMode: $appModel.pendingHighlightedMode,
                showsNavigationTitle: false
            )
        }
    }

    // MARK: - Inline closure methods

    private func startSavedVoiceCloningHandoff(_ plan: SavedVoiceCloneHandoffPlan) {
        pendingVoiceCloningHandoff = plan.handoff
        Task {
            await Self.beginSavedVoiceClonePreloadIfPossible(
                plan: plan,
                engineStore: ttsEngineStore
            )
        }
        selectSidebarItemIfEnabled(
            .voiceCloning,
            bypassDisabledCheck: true
        )
    }

    static func beginSavedVoiceClonePreloadIfPossible(
        plan: SavedVoiceCloneHandoffPlan,
        engineStore: TTSEngineStore
    ) async {
        // Benchmark cold-start accuracy: skip proactive saved-voice clone preload when
        // warmup is suppressed (the cold generation records its own load instead).
        guard !MacGenerationWarmupCoordinator.isSuppressed else { return }
        guard let cloneModelID = plan.cloneModelID?
            .trimmingCharacters(in: .whitespacesAndNewlines),
            !cloneModelID.isEmpty else {
            return
        }
        let trimmedTranscript = plan.handoff.transcript.trimmingCharacters(in: .whitespacesAndNewlines)
        let reference = CloneReference(
            audioPath: plan.handoff.wavPath,
            transcript: trimmedTranscript.isEmpty ? nil : trimmedTranscript,
            preparedVoiceID: plan.handoff.savedVoiceID
        )
        try? await engineStore.ensureCloneReferencePrimed(
            modelID: cloneModelID,
            reference: reference
        )
    }

    private func handleInitialLoad() async {
        await modelManager.refresh()
        didCompleteInitialAvailabilityRefresh = true
        reconcileSelectionWithAvailability()
        scheduleGenerationWarmupIfNeeded(for: appModel.selectedItem, allowClonePrime: false)
    }

    private func handleSelectionChange(_ newValue: SidebarItem?) {
        scheduleGenerationWarmupIfNeeded(for: newValue)
    }

    private func handleStatusesChange() {
        guard didCompleteInitialAvailabilityRefresh else { return }
        reconcileSelectionWithAvailability()
        scheduleGenerationWarmupIfNeeded(for: appModel.selectedItem)
    }

    private func handleActiveVariantChange() {
        guard didCompleteInitialAvailabilityRefresh else { return }
        reconcileSelectionWithAvailability()
        scheduleGenerationWarmupIfNeeded(for: appModel.selectedItem)
    }

    private func handleEngineSnapshotChange(_ newSnapshot: TTSEngineSnapshot) {
        generationWarmupCoordinator.observe(snapshot: newSnapshot)
    }

    private func handleGenerationDraftChange() {
        guard didCompleteInitialAvailabilityRefresh else { return }
        scheduleGenerationWarmupIfNeeded(for: appModel.selectedItem)
    }

    // MARK: - Helper methods

    private func selectSidebarItemIfEnabled(_ item: SidebarItem, bypassDisabledCheck: Bool = false) {
        guard bypassDisabledCheck || !disabledSidebarItems.contains(item) else { return }
        AppPerformanceSignposts.emit("Sidebar Selection")
        if appModel.selectedItem == item {
            return
        }
        appModel.selectedItem = item
    }

    private func reconcileSelectionWithAvailability() {
        guard let selectedItem = appModel.selectedItem, disabledSidebarItems.contains(selectedItem) else {
            return
        }

        if let mode = selectedItem.generationMode {
            appModel.pendingHighlightedMode = mode
        }

        appModel.selectedItem = .settings
    }

    private func scheduleGenerationWarmupIfNeeded(
        for item: SidebarItem?,
        allowClonePrime: Bool = true
    ) {
        let context = warmupContext(for: item, allowClonePrime: allowClonePrime)
        generationWarmupCoordinator.scheduleWarmupIfNeeded(
            context: context,
            snapshot: ttsEngineStore.snapshot,
            ttsEngineStore: ttsEngineStore
        )
    }

    private func warmupContext(
        for item: SidebarItem?,
        allowClonePrime: Bool
    ) -> MacGenerationWarmupCoordinator.WarmupContext? {
        guard let item,
              let mode = item.generationMode,
              let model = modelManager.generationActiveVariant(for: mode) else {
            return nil
        }

        let identity: MacGenerationWarmupCoordinator.WarmupIdentity
        let reference: CloneReference?
        switch mode {
        case .custom:
            identity = .custom(
                speakerID: customVoiceDraft.selectedSpeaker,
                deliveryStyle: model.supportsInstructionControl ? customVoiceDraft.emotion : nil,
                deliveryInstructionCellID: model.supportsInstructionControl
                    ? customVoiceDraft.deliveryProfile?.instructionCellID
                    : nil,
                languageHint: customVoiceDraft.selectedLanguage.rawValue
            )
            reference = nil
        case .design:
            identity = .design(
                brief: voiceDesignDraft.voiceDescription,
                deliveryStyle: voiceDesignDraft.emotion,
                bucket: GenerationSemantics.designWarmBucket(for: voiceDesignDraft.text),
                languageHint: voiceDesignDraft.selectedLanguage.rawValue
            )
            reference = nil
        case .clone:
            if allowClonePrime,
               let referenceAudioPath = voiceCloningDraft.referenceAudioPath?
                .trimmingCharacters(in: .whitespacesAndNewlines),
               !referenceAudioPath.isEmpty {
                let cloneReference = CloneReference(
                    audioPath: referenceAudioPath,
                    transcript: voiceCloningDraft.trimmedReferenceTranscript,
                    preparedVoiceID: voiceCloningDraft.selectedSavedVoiceID
                )
                reference = cloneReference
                identity = .clone(
                    referenceKey: GenerationSemantics.clonePreparationKey(
                        modelID: model.id,
                        reference: cloneReference
                    ),
                    preparedVoiceID: voiceCloningDraft.selectedSavedVoiceID
                )
            } else {
                reference = nil
                identity = .modelOnly
            }
        }

        return MacGenerationWarmupCoordinator.WarmupContext(
            mode: mode,
            modelID: model.id,
            isModelAvailable: modelManager.isAvailable(model),
            identity: identity,
            purpose: .finalGenerationReadiness,
            deviceClass: modelManager.deviceClass,
            cloneReference: reference
        )
    }
}

private struct CustomVoiceScreenHost: View {
    @Binding var draft: CustomVoiceDraft

    @EnvironmentObject private var ttsEngineStore: TTSEngineStore
    @EnvironmentObject private var audioPlayer: AudioPlayerViewModel
    @Environment(ModelManagerViewModel.self) private var modelManager

    var body: some View {
        CustomVoiceView(
            draft: $draft,
            ttsEngineStore: ttsEngineStore,
            audioPlayer: audioPlayer,
            modelManager: modelManager
        )
    }
}

private struct VoiceDesignScreenHost: View {
    @Binding var draft: VoiceDesignDraft

    @EnvironmentObject private var ttsEngineStore: TTSEngineStore
    @EnvironmentObject private var audioPlayer: AudioPlayerViewModel
    @Environment(ModelManagerViewModel.self) private var modelManager
    @Environment(SavedVoicesViewModel.self) private var savedVoicesViewModel

    var body: some View {
        VoiceDesignView(
            draft: $draft,
            ttsEngineStore: ttsEngineStore,
            audioPlayer: audioPlayer,
            modelManager: modelManager,
            savedVoicesViewModel: savedVoicesViewModel
        )
    }
}

private struct VoiceCloningScreenHost: View {
    @Binding var draft: VoiceCloningDraft
    @Binding var pendingSavedVoiceHandoff: PendingVoiceCloningHandoff?

    @EnvironmentObject private var ttsEngineStore: TTSEngineStore
    @EnvironmentObject private var audioPlayer: AudioPlayerViewModel
    @Environment(ModelManagerViewModel.self) private var modelManager
    @Environment(SavedVoicesViewModel.self) private var savedVoicesViewModel

    var body: some View {
        VoiceCloningView(
            draft: $draft,
            pendingSavedVoiceHandoff: $pendingSavedVoiceHandoff,
            ttsEngineStore: ttsEngineStore,
            audioPlayer: audioPlayer,
            modelManager: modelManager,
            savedVoicesViewModel: savedVoicesViewModel
        )
    }
}
