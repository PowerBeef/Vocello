import AppKit
import QwenVoiceCore
import SwiftUI

struct SavedVoiceCloneHandoffPlan: Equatable {
    let handoff: PendingVoiceCloningHandoff
    let cloneModelID: String?
}

/// Four desktop destinations hosting the iOS-derived presentation. Studio mode
/// routes keep their stored identities and drafts; the sidebar and mode selector
/// both use the same selection owner.
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
    @EnvironmentObject private var savedVoicesViewModel: SavedVoicesViewModel
    @EnvironmentObject private var appCommandRouter: AppCommandRouter

    @State private var appModel: MacAppModel
    /// Tracks sidebar visibility while each Studio mode owns its inline transport.
    @State private var sidebarColumnVisibility: NavigationSplitViewVisibility = .all
    @State private var customVoiceDraft = CustomVoiceDraft()
    @State private var voiceDesignDraft = VoiceDesignDraft()
    @State private var voiceCloningDraft = VoiceCloningDraft()
    @State private var pendingVoiceCloningHandoff: PendingVoiceCloningHandoff?
    /// Content size of the window, for the split-view columns' shared backdrop.
    @State private var windowSize: CGSize?
    @State private var didCompleteInitialAvailabilityRefresh = false
    @AppStorage(VoiceCloningConsentPolicy.recordedConsentDefaultsKey, store: AppDefaults.store)
    private var cloneConsentAcknowledged = false
    @StateObject private var generationWarmupCoordinator = MacGenerationWarmupCoordinator()

    private var canUseSavedVoicesInVoiceCloning: Bool {
        modelManager.hasInstalledVariant(for: .clone)
    }

    private var sidebarSelectionBinding: Binding<SidebarItem?> {
        Binding(
            get: { appModel.selectedItem },
            set: { newValue in
                guard let newValue else { return }
                selectDestination(newValue)
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
                transcriptLoadError: MacInterfaceText.cloningTranscriptLoadFailed(voice.name)
            )
        }

        return SavedVoiceCloneHandoffPlan(
            handoff: handoff,
            cloneModelID: cloneModelID?.trimmingCharacters(in: .whitespacesAndNewlines)
        )
    }

    var body: some View {
        NavigationSplitView(columnVisibility: $sidebarColumnVisibility) {
            SidebarView(selection: sidebarSelectionBinding)
            // One hairline where the columns meet. The wash runs across both
            // of them without a seam, which is the point of painting it once --
            // and it left the two panels floating in the same field with
            // nothing saying where navigation ends and the canvas begins. The
            // same token and width the History and Settings rows use for their
            // own separators, so the app has one idea of what a dividing line
            // looks like. It ignores the safe area so it runs the full height
            // of the window, under a title bar that is deliberately
            // transparent.
            .overlay(alignment: .trailing) {
                Rectangle()
                    .fill(MacTheme.Surface.hairline)
                    .frame(width: VocelloTheme.Stroke.hairline)
                    .ignoresSafeArea()
                    .allowsHitTesting(false)
            }
            .navigationSplitViewColumnWidth(
                min: MacShellMetrics.sidebarMinWidth,
                ideal: MacShellMetrics.sidebarIdealWidth,
                max: MacShellMetrics.sidebarMaxWidth
            )
        } detail: {
            detailContent
                .safeAreaInset(edge: .bottom, spacing: 0) {
                    if sidebarColumnVisibility == .detailOnly {
                        MacPlaybackFooter(isSidebar: false)
                    }
                }
                .toolbar {
                    MacWindowToolbar(selectedItem: appModel.selectedItem)
                }
        }
        .navigationSplitViewStyle(.balanced)
        // One mode-tinted wash behind sidebar and canvas together, at the
        // phone's whisper intensity, tinted by the destination the way the
        // phone tints each tab: each column paints its slice from the window
        // size measured here. The toolbar is part of that surface: no band,
        // no title (the sidebar carries the lockup; the window title still
        // names the window for Mission Control and the Dock).
        .onGeometryChange(for: CGSize.self) { $0.size } action: { windowSize = $0 }
        .environment(\.vocelloWindowSize, windowSize)
        .environment(\.vocelloSidebarIsVisible, sidebarColumnVisibility != .detailOnly)
        .toolbarBackgroundVisibility(.hidden, for: .windowToolbar)
        .toolbar(removing: .title)
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
        // Recording consent changes the Clone warm target from model-only to primed.
        .onChange(of: cloneConsentAcknowledged) { _, _ in handleGenerationDraftChange() }
        .onChange(of: voiceCloningDraft.selectedSavedVoiceID) { _, newValue in
            appModel.persistVoiceCloningSavedVoiceID(newValue)
        }
        // Availability, not download progress (MAC-22): `statuses` changes ten
        // times a second during a download, which re-rendered the whole shell
        // and rescheduled the warmup on every tick.
        .onChange(of: modelManager.modelInfoByID) { _, _ in handleStatusesChange() }
        .onChange(of: modelManager.activeVariantRevision) { _, _ in handleActiveVariantChange() }
        // `onReceive`, not `onChange`: `onChange(of:)` would need the
        // snapshot read in body, which would track the store (W1-D/W2-A).
        // The store's explicit bridge fires only on applied changes.
        .onReceive(ttsEngineStore.snapshotChanges) { newSnapshot in
            handleEngineSnapshotChange(newSnapshot)
        }
        .onReceive(appCommandRouter.sidebarSelection) { item in
            selectDestination(item)
        }
        // MAC-23: Stop (⌘.) cancels the running take; Search History (⌘F)
        // opens History with its search field focused.
        .onReceive(appCommandRouter.generationCancelRequests) { audioPlayer in
            MacStudioGenerationActions.cancelActiveGeneration(
                appModel: appModel,
                ttsEngine: ttsEngineStore,
                audioPlayer: audioPlayer
            )
        }
        .onReceive(appCommandRouter.historySearchRequests) { _ in
            selectDestination(.history)
            appModel.historySearchFocusRequested = true
        }
        .onChange(of: isAnyGenerationActive, initial: true) { _, isActive in
            appCommandRouter.isGenerationActive = isActive
        }
    }

    /// A Studio take, line batch or long-form project is running: each
    /// installs its task in a mode coordinator.
    private var isAnyGenerationActive: Bool {
        GenerationMode.allCases.contains { appModel.coordinator(for: $0).isGenerating }
    }

    @ViewBuilder
    private var detailContent: some View {
        Group {
            if let selectedItem = appModel.selectedItem {
                VStack(spacing: 0) {
                    if selectedItem.generationMode != nil {
                        MacStudioModeSelector(selection: sidebarSelectionBinding)
                            .padding(.horizontal, MacStudioMetrics.horizontalInset)
                            .padding(.top, MacTheme.Spacing.tight)
                            .padding(.bottom, MacTheme.Spacing.snug)
                            .frame(maxWidth: MacStudioMetrics.composerMaxWidth)
                            .frame(maxWidth: .infinity)
                    }
                    screenView(for: selectedItem)
                        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
                }
            } else {
                Color.clear
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .background {
            MacModeBackdrop(tint: MacTheme.tint(for: appModel.selectedItem ?? .customVoice), column: .detail)
                .ignoresSafeArea()
                .appAnimation(MacTheme.Motion.modeCrossfade, value: appModel.selectedItem)
        }
    }

    @ViewBuilder
    private func screenView(for item: SidebarItem) -> some View {
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
            HistoryScreenHost(
                ttsEngineStore: ttsEngineStore,
                onPinSeed: { generation in
                    guard let seedValue = generation.samplingSeed else { return }
                    // Pin into the take's own mode and surface that mode so
                    // the composer chip makes the new state visible.
                    switch generation.mode {
                    case GenerationMode.custom.rawValue:
                        customVoiceDraft.pinnedSeed = seedValue
                        selectDestination(.customVoice)
                    case GenerationMode.design.rawValue:
                        voiceDesignDraft.pinnedSeed = seedValue
                        selectDestination(.voiceDesign)
                    case GenerationMode.clone.rawValue:
                        voiceCloningDraft.pinnedSeed = seedValue
                        selectDestination(.voiceCloning)
                    default:
                        break
                    }
                }
            )
        case .voices:
            MacVoicesScreen(
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
                },
                onVoiceDeleted: { voiceID in
                    // The staged handoff carries the voice's `wavPath`, and
                    // deleting the voice removes that file. Left in place it
                    // would stage Voice Cloning against a reference that is no
                    // longer there. `IOSVoicesView` has always cleared it.
                    if pendingVoiceCloningHandoff?.savedVoiceID == voiceID {
                        pendingVoiceCloningHandoff = nil
                    }
                }
            )
        case .settings:
            SettingsScreenHost()
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
        selectDestination(.voiceCloning)
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
        scheduleGenerationWarmupIfNeeded(for: appModel.selectedItem, allowClonePrime: false)
    }

    private func handleSelectionChange(_ newValue: SidebarItem?) {
        scheduleGenerationWarmupIfNeeded(for: newValue)
    }

    private func handleStatusesChange() {
        guard didCompleteInitialAvailabilityRefresh else { return }
        scheduleGenerationWarmupIfNeeded(for: appModel.selectedItem)
    }

    private func handleActiveVariantChange() {
        guard didCompleteInitialAvailabilityRefresh else { return }
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

    private func selectDestination(_ item: SidebarItem) {
        // Like iOS, a missing model leaves its Studio accessible with an Install
        // action. Only switching generation modes during a take is blocked.
        if item.generationMode != nil, item != appModel.lastStudioItem,
           ttsEngineStore.hasActiveGeneration { return }
        guard appModel.selectedItem != item else { return }
        AppPerformanceSignposts.emit("Sidebar Selection")
        appModel.selectedItem = item
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
                    ? customVoiceDraft.resolvedDeliveryProfile.instructionCellID
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
            // Without recorded consent the clone model is warmed but the
            // reference is never primed (the engine would refuse it).
            if allowClonePrime,
               cloneConsentAcknowledged,
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

/// Binds the History screen to the shell's toolbar state from the
/// environment, so a keystroke in the search field re-renders this host and
/// the screen, never `ContentView` (whose body would rebuild every hosted
/// screen value).
private struct HistoryScreenHost: View {
    let ttsEngineStore: TTSEngineStore
    let onPinSeed: (Generation) -> Void

    @Environment(MacAppModel.self) private var appModel

    var body: some View {
        @Bindable var appModel = appModel
        MacHistoryScreen(
            ttsEngineStore: ttsEngineStore,
            searchText: $appModel.historySearchText,
            sortOrder: $appModel.historySortOrder,
            clearRequest: $appModel.historyClearRequest,
            onPinSeed: onPinSeed
        )
    }
}

/// Settings binds the shell's pending highlight itself, so a redirect to
/// a missing model re-renders this host and the screen, never the shell.
private struct SettingsScreenHost: View {
    @Environment(MacAppModel.self) private var appModel

    var body: some View {
        @Bindable var appModel = appModel
        MacSettingsScreen(
            highlightedMode: $appModel.pendingHighlightedMode,
            showsNavigationTitle: false
        )
    }
}

private struct CustomVoiceScreenHost: View {
    @Binding var draft: CustomVoiceDraft

    var body: some View {
        MacCustomVoiceScreen(draft: $draft)
    }
}

private struct VoiceDesignScreenHost: View {
    @Binding var draft: VoiceDesignDraft

    var body: some View {
        MacVoiceDesignScreen(draft: $draft)
    }
}

private struct VoiceCloningScreenHost: View {
    @Binding var draft: VoiceCloningDraft
    @Binding var pendingSavedVoiceHandoff: PendingVoiceCloningHandoff?

    var body: some View {
        MacVoiceCloningScreen(draft: $draft, pendingSavedVoiceHandoff: $pendingSavedVoiceHandoff)
    }
}
