import SwiftUI
import AppKit
import QwenVoiceCore
import QwenVoiceNative

struct SavedVoiceCloneHandoffPlan: Equatable {
    let handoff: PendingVoiceCloningHandoff
    let cloneModelID: String?
}

enum SidebarItem: String, CaseIterable, Identifiable {
    case customVoice = "Custom Voice"
    case voiceDesign = "Voice Design"
    case voiceCloning = "Voice Cloning"
    case history = "History"
    case voices = "Saved Voices"
    /// Renamed from `.models` (May 2026 redesign): the Models tab
    /// merged with the Cmd+, Preferences window into one unified
    /// Settings surface that hosts model downloads, playback,
    /// storage, and about. The enum case stays internal for code
    /// clarity; the rawValue drives the sidebar label.
    case settings = "Settings"

    var id: String { rawValue }

    var accessibilityID: String { "sidebar_\(String(describing: self))" }

    var screenAccessibilityID: String {
        switch self {
        case .customVoice:
            return "screen_customVoice"
        case .voiceDesign:
            return "screen_voiceDesign"
        case .voiceCloning:
            return "screen_voiceCloning"
        case .history:
            return "screen_history"
        case .voices:
            return "screen_voices"
        case .settings:
            return "screen_settings"
        }
    }

    var generationMode: GenerationMode? {
        switch self {
        case .customVoice:
            return .custom
        case .voiceDesign:
            return .design
        case .voiceCloning:
            return .clone
        case .history, .voices, .settings:
            return nil
        }
    }

    var requiredModel: TTSModel? {
        generationMode.flatMap(TTSModel.model(for:))
    }

    var iconName: String {
        switch self {
        // Generation modes use the canonical per-mode glyphs so the sidebar
        // and Settings model rows stay matched.
        case .customVoice: return AppTheme.modeGlyph(for: .custom)
        case .voiceDesign: return AppTheme.modeGlyph(for: .design)
        case .voiceCloning: return AppTheme.modeGlyph(for: .clone)
        case .history: return "clock.arrow.circlepath"
        case .voices: return "person.2.wave.2"
        case .settings: return "gearshape"
        }
    }

    enum Section: String, CaseIterable {
        case generate = "Generate"
        case library = "Library"
        case settings = "Settings"

        var accessibilityID: String {
            "sidebarSection_\(String(describing: self))"
        }

        var items: [SidebarItem] {
            switch self {
            case .generate:
                return [.customVoice, .voiceDesign, .voiceCloning]
            case .library:
                return [.history, .voices]
            case .settings:
                return [.settings]
            }
        }
    }

    static var generationItems: [SidebarItem] {
        [.customVoice, .voiceDesign, .voiceCloning]
    }

    @MainActor
    func isAvailable(using modelManager: ModelManagerViewModel) -> Bool {
        guard let generationMode else { return true }
        return modelManager.hasInstalledVariant(for: generationMode)
    }

    @MainActor static func defaultInitialSelection() -> SidebarItem {
        return .customVoice
    }
}

@MainActor
struct ContentView: View {
    @Environment(ModelManagerViewModel.self) private var modelManager
    /// Plain reference, deliberately NOT `@EnvironmentObject` (W1-D): the
    /// root shell must not subscribe to the whole engine store — every use
    /// below is imperative, and the only body-relevant signal is the gate,
    /// which `gateModel` republishes flip-scoped. Descendant screens keep
    /// their own environment-object injection.
    private let ttsEngineStore: TTSEngineStore
    @StateObject private var gateModel: GenerationPerformanceGateModel
    @Environment(SavedVoicesViewModel.self) private var savedVoicesViewModel
    @EnvironmentObject private var appCommandRouter: AppCommandRouter

    static let lastSidebarItemKey = "QwenVoice.LastSelectedSidebarItem"
    static let lastVoiceCloningSavedVoiceIDKey = "QwenVoice.LastVoiceCloningSavedVoiceID"

    @AppStorage(ContentView.lastSidebarItemKey, store: AppDefaults.store)
    private var persistedSidebarItem: SidebarItem = .customVoice

    @AppStorage(ContentView.lastVoiceCloningSavedVoiceIDKey, store: AppDefaults.store)
    private var persistedVoiceCloningSavedVoiceID: String = ""

    @State private var selectedItem: SidebarItem?
    /// When the user clicks a disabled generation tab, the
    /// sidebar redirects to Settings and asks the Models page to
    /// flash that mode's row. Keyed by `GenerationMode` (not
    /// model id) because the row is mode-keyed and the missing
    /// variant might not be the currently active one.
    @State private var pendingHighlightedMode: GenerationMode?
    @State private var historySearchText = ""
    @State private var historySortOrder: HistorySortOrder = .newest
    @State private var historyClearRequest: HistoryClearRequest?
    @State private var voicesEnrollRequestID: UUID?
    @State private var customVoiceDraft = CustomVoiceDraft()
    @State private var voiceDesignDraft = VoiceDesignDraft()
    @State private var voiceCloningDraft = VoiceCloningDraft()
    @State private var pendingVoiceCloningHandoff: PendingVoiceCloningHandoff?
    @State private var didCompleteInitialAvailabilityRefresh = false
    @StateObject private var generationWarmupCoordinator = MacGenerationWarmupCoordinator()
    /// Retires the idle XPC engine service on pressured 8 GB Macs (full
    /// memory reclaim); plain @State — it publishes nothing.
    @State private var engineLifecycleCoordinator = MacEngineServiceLifecycleCoordinator()

    private var disabledSidebarItems: Set<SidebarItem> {
        Set(SidebarItem.generationItems.filter { !$0.isAvailable(using: modelManager) })
    }

    private var canUseSavedVoicesInVoiceCloning: Bool {
        modelManager.hasInstalledVariant(for: .clone)
    }

    private var sidebarSelectionBinding: Binding<SidebarItem?> {
        Binding(
            get: { selectedItem },
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
        // Read through AppDefaults because @AppStorage is not materialized in init yet.
        let storedSidebar = AppDefaults.store
            .string(forKey: ContentView.lastSidebarItemKey)
            .flatMap(SidebarItem.init(rawValue:))
        let initialSelection = storedSidebar ?? SidebarItem.defaultInitialSelection()
        var initialDraft = VoiceCloningDraft()
        let storedVoiceID = AppDefaults.store
            .string(forKey: ContentView.lastVoiceCloningSavedVoiceIDKey)
        if let storedVoiceID, !storedVoiceID.isEmpty {
            initialDraft.selectedSavedVoiceID = storedVoiceID
        }

        _selectedItem = State(initialValue: initialSelection)
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
        NavigationSplitView {
            SidebarView(
                selection: sidebarSelectionBinding,
                disabledItems: disabledSidebarItems
            )
                .navigationSplitViewColumnWidth(min: 220, ideal: 250, max: 300)
        } detail: {
            detailContent
        }
        .toolbar {
            MainWindowToolbar(
                selectedItem: selectedItem,
                historySortOrder: $historySortOrder,
                historySearchText: $historySearchText,
                historyClearRequest: $historyClearRequest,
                voicesEnrollRequestID: $voicesEnrollRequestID
            )
        }
        .navigationSplitViewStyle(.balanced)
        // Generation performance gate (OPTIMIZATION.md §K): while the engine
        // generates, glass surfaces fall back to the solid-fill design so the
        // material's continuous compositor work stops competing with MLX for
        // the GPU (measured 1.37 with glass vs 1.84 solid on the 8 GB tier).
        // Read through the flip-scoped gate model (W1-D), never the store.
        .environment(\.generationPerformanceGate, gateModel.isActive)
        .onAppear(perform: handleAppear)
        .task { await handleInitialLoad() }
        .onChange(of: selectedItem) { _, newValue in handleSelectionChange(newValue) }
        .onChange(of: customVoiceDraft) { _, _ in handleGenerationDraftChange() }
        .onChange(of: voiceDesignDraft) { _, _ in handleGenerationDraftChange() }
        .onChange(of: voiceCloningDraft) { _, _ in handleGenerationDraftChange() }
        .onChange(of: voiceCloningDraft.selectedSavedVoiceID) { _, newValue in
            handleVoiceCloningSavedVoiceIDChange(newValue)
        }
        .onChange(of: modelManager.statuses) { _, _ in handleStatusesChange() }
        .onChange(of: modelManager.activeVariantRevision) { _, _ in handleActiveVariantChange() }
        // `onReceive`, not `onChange`: `onChange(of:)` would need the
        // snapshot read in body, which would track the store (W1-D/W2-A).
        // The store's explicit bridge fires only on applied changes.
        .onReceive(ttsEngineStore.snapshotUpdates) { newSnapshot in
            handleEngineSnapshotChange(newSnapshot)
        }
        .onReceive(appCommandRouter.sidebarSelection) { item in
            selectSidebarItemIfEnabled(item)
        }
    }

    @ViewBuilder
    private var detailContent: some View {
        Group {
            if let selectedItem {
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
            HistoryView(
                ttsEngineStore: ttsEngineStore,
                searchText: $historySearchText,
                sortOrder: $historySortOrder,
                clearRequest: $historyClearRequest,
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
                enrollRequestID: voicesEnrollRequestID,
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
                highlightedMode: $pendingHighlightedMode,
                showsNavigationTitle: false
            )
        }
    }

    // MARK: - Inline closure methods

    private func handleAppear() {
    }

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
        scheduleGenerationWarmupIfNeeded(for: selectedItem, allowClonePrime: false)
    }

    private func handleSelectionChange(_ newValue: SidebarItem?) {
        // Persist the selection so the next cold launch restores the last sidebar item.
        if let newValue {
            persistedSidebarItem = newValue
        }
        scheduleGenerationWarmupIfNeeded(for: newValue)
    }

    private func handleStatusesChange() {
        guard didCompleteInitialAvailabilityRefresh else { return }
        reconcileSelectionWithAvailability()
        scheduleGenerationWarmupIfNeeded(for: selectedItem)
    }

    private func handleActiveVariantChange() {
        guard didCompleteInitialAvailabilityRefresh else { return }
        reconcileSelectionWithAvailability()
        scheduleGenerationWarmupIfNeeded(for: selectedItem)
    }

    private func handleEngineSnapshotChange(_ newSnapshot: TTSEngineSnapshot) {
        generationWarmupCoordinator.observe(snapshot: newSnapshot)
        engineLifecycleCoordinator.observe(
            snapshot: newSnapshot,
            hasActiveGeneration: ttsEngineStore.hasActiveGeneration,
            ttsEngineStore: ttsEngineStore,
            warmupCoordinator: generationWarmupCoordinator
        )
    }

    private func handleGenerationDraftChange() {
        guard didCompleteInitialAvailabilityRefresh else { return }
        scheduleGenerationWarmupIfNeeded(for: selectedItem)
    }

    private func handleVoiceCloningSavedVoiceIDChange(_ newValue: String?) {
        // Persist the last picked Voice Cloning saved voice so the dropdown
        // restores it on next launch. The existing `syncSavedVoiceSelectionState`
        // hydration path will reload `wavPath` + transcript from disk, or clear
        // the draft if the voice was deleted between launches.
        persistedVoiceCloningSavedVoiceID = newValue ?? ""
    }

    // MARK: - Helper methods

    private func selectSidebarItemIfEnabled(_ item: SidebarItem, bypassDisabledCheck: Bool = false) {
        guard bypassDisabledCheck || !disabledSidebarItems.contains(item) else { return }
        AppPerformanceSignposts.emit("Sidebar Selection")
        if selectedItem == item {
            return
        }
        selectedItem = item
    }

    private func reconcileSelectionWithAvailability() {
        guard let selectedItem, disabledSidebarItems.contains(selectedItem) else {
            return
        }

        if let mode = selectedItem.generationMode {
            pendingHighlightedMode = mode
        }

        self.selectedItem = .settings
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

    @Environment(TTSEngineStore.self) private var ttsEngineStore
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

    @Environment(TTSEngineStore.self) private var ttsEngineStore
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

    @Environment(TTSEngineStore.self) private var ttsEngineStore
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

// MARK: - MainWindowToolbar

private struct MainWindowToolbar: ToolbarContent {
    let selectedItem: SidebarItem?
    @Binding var historySortOrder: HistorySortOrder
    @Binding var historySearchText: String
    @Binding var historyClearRequest: HistoryClearRequest?
    @Binding var voicesEnrollRequestID: UUID?

    var body: some ToolbarContent {
        // One ToolbarItem (HStack) — separate items pick up enough inter-item
        // padding that the search field overflows at the default 720pt window
        // (regressing the smoke test's `history_searchField` assertion). The
        // combined group fits like the pre-clear-menu layout did, with the
        // search slimmed to make room for the trash menu.
        if selectedItem == .history {
            ToolbarItem {
                HStack(spacing: 10) {
                    Menu {
                        Picker("Sort", selection: $historySortOrder) {
                            ForEach(HistorySortOrder.allCases) { order in
                                Text(order.label).tag(order)
                            }
                        }
                    } label: {
                        Image(systemName: "arrow.up.arrow.down.circle")
                    }
                    .accessibilityLabel("Sort history")
                    .accessibilityIdentifier("history_sortPicker")

                    Menu {
                        Button("Clear History (Keep Audio Files)…") {
                            historyClearRequest = HistoryClearRequest(scope: .keepFiles)
                        }
                        .accessibilityIdentifier("history_clearKeepFiles")
                        Button("Clear History and Delete Audio…", role: .destructive) {
                            historyClearRequest = HistoryClearRequest(scope: .deleteFiles)
                        }
                        .accessibilityIdentifier("history_clearDeleteFiles")
                    } label: {
                        Image(systemName: "trash.circle")
                    }
                    .accessibilityLabel("Clear history")
                    .accessibilityIdentifier("history_clearMenu")

                    ToolbarSearchField(
                        text: $historySearchText,
                        placeholder: "Search history",
                        accessibilityIdentifier: "history_searchField"
                    )
                    // Fixed width on purpose: flexible or generous frames
                    // push the trailing toolbar group into the overflow
                    // chevron at compact window widths (smoke-verified
                    // 2026-08-06, twice). 170 is just enough to unclip the
                    // "Search history" placeholder the old 150 cut off.
                    .frame(width: 170)
                }
            }
        }

        if selectedItem == .voices {
            ToolbarItem {
                Button("Add Voice Sample") {
                    voicesEnrollRequestID = UUID()
                }
                .buttonStyle(.borderedProminent)
                .tint(AppTheme.accent)
                .accessibilityIdentifier("voices_enrollButton")
            }
        }
    }
}

// MARK: - ToolbarSearchField

private struct ToolbarSearchField: NSViewRepresentable {
    @Binding var text: String
    let placeholder: String
    let accessibilityIdentifier: String

    func makeCoordinator() -> Coordinator {
        Coordinator(text: $text)
    }

    func makeNSView(context: Context) -> NSSearchField {
        let field = NSSearchField(frame: .zero)
        field.target = context.coordinator
        field.action = #selector(Coordinator.didActivateSearch(_:))
        field.delegate = context.coordinator
        field.sendsSearchStringImmediately = true
        field.sendsWholeSearchString = false
        configure(field)
        return field
    }

    func updateNSView(_ nsView: NSSearchField, context: Context) {
        context.coordinator.text = $text
        if nsView.stringValue != text {
            nsView.stringValue = text
        }
        configure(nsView)
    }

    private func configure(_ field: NSSearchField) {
        field.placeholderString = placeholder
        field.identifier = NSUserInterfaceItemIdentifier(accessibilityIdentifier)
        field.setAccessibilityIdentifier(accessibilityIdentifier)
        field.setAccessibilityLabel(placeholder)
    }

    @MainActor final class Coordinator: NSObject, NSSearchFieldDelegate {
        var text: Binding<String>

        init(text: Binding<String>) {
            self.text = text
        }

        @objc
        func didActivateSearch(_ sender: NSSearchField) {
            text.wrappedValue = sender.stringValue
        }

        func controlTextDidChange(_ notification: Notification) {
            guard let field = notification.object as? NSSearchField else { return }
            text.wrappedValue = field.stringValue
        }
    }
}
