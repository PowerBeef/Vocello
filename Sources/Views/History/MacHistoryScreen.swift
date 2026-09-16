import AppKit
import QwenVoiceCore
import SwiftUI

/// One loaded History row with everything a card needs precomputed once, off
/// the main thread, in `reloadHistory`. Nothing here may be expensive: the
/// screen's `@State` initial value copies the session cache on every
/// `ContentView` body evaluation, which typing in the toolbar search field
/// triggers per keystroke. The saved-voice sheet configuration is built on
/// demand because its reference-language detection runs an on-device
/// language model (about a tenth of a second per row on the main thread);
/// building it here for every clone and design row made each keystroke a
/// one-second hang (2026-09-15, Time Profiler on smoke test02).
private struct MacHistoryListItem: Identifiable, Sendable {
    /// What "Save to Saved Voices" enrolls; nil for modes whose take cannot
    /// become a saved voice.
    enum SaveVoiceSource: Sendable {
        case cloneResult(suggestedName: String)
        case designResult(voiceDescription: String)
    }

    let generation: Generation
    let audioFileExists: Bool
    let textPreview: String
    let formattedDate: String
    let searchKey: String
    let waveformSeed: Int
    let saveVoiceSource: SaveVoiceSource?

    var id: String { generation.historyAccessibilityID }

    init(generation: Generation) {
        self.generation = generation
        self.audioFileExists = FileManager.default.fileExists(atPath: generation.audioPath)
        self.textPreview = generation.textPreview
        self.formattedDate = generation.createdAt.formatted(date: .abbreviated, time: .shortened)
        self.searchKey = "\(generation.text)\n\(generation.voice ?? "")".lowercased()
        self.waveformSeed = generation.id.map { Int(truncatingIfNeeded: $0) }
            ?? VocelloStableVisualHash.int(generation.audioPath)
        self.saveVoiceSource = Self.makeSaveVoiceSource(for: generation)
    }

    /// The sheet configuration, built when the user asks for it: this is the
    /// only place the reference-language detector runs for a History row.
    func makeSaveVoiceConfiguration() -> SavedVoiceSheetConfiguration? {
        switch saveVoiceSource {
        case .cloneResult(let suggestedName):
            return .cloneResult(
                suggestedName: suggestedName,
                audioPath: generation.audioPath,
                transcript: generation.text
            )
        case .designResult(let voiceDescription):
            return .designResult(
                voiceDescription: voiceDescription,
                audioPath: generation.audioPath,
                transcript: generation.text
            )
        case nil:
            return nil
        }
    }

    private static func makeSaveVoiceSource(for generation: Generation) -> SaveVoiceSource? {
        switch generation.mode {
        case GenerationMode.clone.rawValue:
            return .cloneResult(suggestedName: suggestedSavedVoiceName(for: generation))
        case GenerationMode.design.rawValue:
            return .designResult(voiceDescription: generation.voice ?? "")
        default:
            return nil
        }
    }

    private static func suggestedSavedVoiceName(for generation: Generation) -> String {
        if let voice = generation.voice?.trimmingCharacters(in: .whitespacesAndNewlines),
           !voice.isEmpty {
            return "\(voice) Sample"
        }
        return URL(fileURLWithPath: generation.audioPath)
            .deletingPathExtension()
            .lastPathComponent
    }
}

/// One rendered row after long-form grouping. Segments of a project with a
/// joined row collapse under it; searching renders flat.
private struct MacHistoryDisplayEntry: Identifiable {
    let item: MacHistoryListItem
    let isSegment: Bool
    /// Present on a long-form joined ("project") row: toggling reveals its
    /// segment map beneath.
    let projectToggle: (projectID: String, segmentCount: Int)?

    var id: String { item.id }

    static func entries(
        from items: [MacHistoryListItem],
        searchActive: Bool,
        expandedProjects: Set<String>
    ) -> [MacHistoryDisplayEntry] {
        guard !searchActive else {
            return items.map { MacHistoryDisplayEntry(item: $0, isSegment: false, projectToggle: nil) }
        }
        var segmentsByProject: [String: [MacHistoryListItem]] = [:]
        var projectsWithJoinedRow: Set<String> = []
        for item in items {
            guard let projectID = item.generation.longFormProjectID else { continue }
            switch item.generation.longFormRole {
            case "segment":
                segmentsByProject[projectID, default: []].append(item)
            case "joined":
                projectsWithJoinedRow.insert(projectID)
            default:
                break
            }
        }

        var entries: [MacHistoryDisplayEntry] = []
        for item in items {
            let projectID = item.generation.longFormProjectID
            switch item.generation.longFormRole {
            case "segment":
                // Collapsed under the joined row; orphaned segments (no joined
                // row yet) stay visible in place.
                if let projectID, projectsWithJoinedRow.contains(projectID) {
                    continue
                }
                entries.append(MacHistoryDisplayEntry(item: item, isSegment: false, projectToggle: nil))
            case "joined":
                let segments = projectID.flatMap { segmentsByProject[$0] } ?? []
                entries.append(
                    MacHistoryDisplayEntry(
                        item: item,
                        isSegment: false,
                        projectToggle: projectID.map { ($0, segments.count) }
                    )
                )
                if let projectID, expandedProjects.contains(projectID) {
                    for segment in segments.sorted(by: { $0.generation.createdAt < $1.generation.createdAt }) {
                        entries.append(MacHistoryDisplayEntry(item: segment, isSegment: true, projectToggle: nil))
                    }
                }
            default:
                entries.append(MacHistoryDisplayEntry(item: item, isSegment: false, projectToggle: nil))
            }
        }
        return entries
    }
}

/// Entries under one date heading (nil when the sort order is not
/// chronological). Segments follow their project's bucket.
private struct MacHistorySection: Identifiable {
    let bucket: HistoryDateBucket?
    let entries: [MacHistoryDisplayEntry]

    var id: Int { bucket?.rawValue ?? -1 }

    static func sections(from entries: [MacHistoryDisplayEntry], groupByDate: Bool) -> [MacHistorySection] {
        guard groupByDate, !entries.isEmpty else {
            return entries.isEmpty ? [] : [MacHistorySection(bucket: nil, entries: entries)]
        }
        let reference = Date()
        let calendar = Calendar.current
        var grouped: [HistoryDateBucket: [MacHistoryDisplayEntry]] = [:]
        var currentBucket: HistoryDateBucket = .today
        for entry in entries {
            if !entry.isSegment {
                currentBucket = HistoryDateBucket.bucket(
                    for: entry.item.generation.createdAt,
                    reference: reference,
                    calendar: calendar
                )
            }
            grouped[currentBucket, default: []].append(entry)
        }
        return HistoryDateBucket.allCases.compactMap { bucket in
            guard let rows = grouped[bucket], !rows.isEmpty else { return nil }
            return MacHistorySection(bucket: bucket, entries: rows)
        }
    }
}

private struct MacHistoryActionAlert: Identifiable {
    let id = UUID()
    let title: String
    let message: String
    /// When set, the alert renders as a destructive confirm/cancel pair
    /// instead of a single OK (the clear-history flow).
    var confirmTitle: String? = nil
    var onConfirm: (() -> Void)? = nil
}

/// Built rows of the last load, so a re-created screen starts from them
/// without stat-ing files or re-deriving row data.
@MainActor private enum MacHistorySessionCache {
    static var items: [MacHistoryListItem] = []
}

/// Database- and file-manager-backed effects for the pure sequencing engine
/// (W2-B). The rules live tested in `QwenVoiceCore.HistoryDeletionEngine`;
/// this wiring is the only untested residue.
extension HistoryDeletionEngine {
    static let databaseBacked = HistoryDeletionEngine(
        deleteRecord: { try DatabaseService.shared.deleteGeneration(id: $0) },
        deleteAllRecords: { try DatabaseService.shared.deleteAllGenerations() },
        audioPathsForAllRecords: { try DatabaseService.shared.fetchAllGenerations().map(\.audioPath) },
        removeFile: { try FileManager.default.removeItem(atPath: $0) },
        fileExists: { FileManager.default.fileExists(atPath: $0) }
    )
}

/// History in the iOS design over the shared `Generation` and
/// `DatabaseService`: date-bucketed rows with mode-tinted thumbnails, the
/// mode filter chips, the pending-recovery card, and the desktop's toolbar
/// sort, search and clear, Save As, Reveal in Finder and pinned seed.
struct MacHistoryScreen: View {
    @EnvironmentObject private var audioPlayer: AudioPlayerViewModel
    @EnvironmentObject private var savedVoicesViewModel: SavedVoicesViewModel
    @EnvironmentObject private var generationLibraryEvents: GenerationLibraryEvents
    /// Plain reference, not `@EnvironmentObject` (W1-D): History uses the
    /// store only to forward into the saved-voice sheet and for one
    /// imperative refresh; subscribing re-rendered every row on every engine
    /// tick for nothing.
    let ttsEngineStore: TTSEngineStore
    @Binding var searchText: String
    @Binding var sortOrder: HistorySortOrder
    @Binding var clearRequest: HistoryClearRequest?
    /// DP-15: routes a row's recorded sampling seed into the matching mode's
    /// draft as the pinned seed. Nil hides the action.
    var onPinSeed: ((Generation) -> Void)? = nil

    @State private var items: [MacHistoryListItem] = MacHistorySessionCache.items
    @State private var isLoading = false
    @State private var loadTask: Task<Void, Never>?
    @State private var loadError: String?
    @State private var showDeleteConfirmation = false
    @State private var itemToDelete: MacHistoryListItem?
    @State private var actionAlert: MacHistoryActionAlert?
    @State private var savedVoiceSheetConfiguration: SavedVoiceSheetConfiguration?
    @State private var pendingReloadAfterCurrentLoad = false
    @State private var modeFilter: HistoryModeFilter = .all
    @State private var filteredItems: [MacHistoryListItem] = []
    /// Cached grouped list (W1-D): recomputed only when its inputs change,
    /// never in body.
    @State private var sections: [MacHistorySection] = []
    @State private var expandedProjects: Set<String> = []
    @State private var itemsRevision = 0
    @State private var searchDebounceTask: Task<Void, Never>?
    @State private var databaseUnavailable = false
    @State private var recoverySnapshot: GenerationHistoryRecoverySnapshot = .empty
    @State private var recoveryAudioURLs: [URL] = []

    private var searchActive: Bool {
        !searchText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }

    var body: some View {
        VStack(spacing: 0) {
            VStack(alignment: .leading, spacing: 12) {
                if recoverySnapshot.needsAttention {
                    MacHistoryRecoveryBanner(
                        message: recoveryMessage,
                        canReveal: recoverySnapshot.availableAudioCount > 0,
                        canExport: !recoveryAudioURLs.isEmpty,
                        onRetry: { reloadHistory(reopenFailedStore: true) },
                        onReveal: { MacHistoryFileActions.openOutputsFolder() },
                        onExport: exportPendingAudio
                    )
                }

                MacFilterChipRow(
                    options: HistoryModeFilter.allCases,
                    selection: $modeFilter,
                    label: \.title,
                    leading: { filter in AnyView(VocelloModeDot(tint: filter.dotColor, diameter: 7)) },
                    accessibilityIdentifier: \.accessibilityID
                )
                .accessibilityElement(children: .contain)
                .accessibilityLabel(MacInterfaceText.historyFilterAccessibility)
                .accessibilityIdentifier("history_modeFilter")
            }
            .padding(.horizontal, 20)
            .padding(.top, 14)
            .padding(.bottom, 4)
            .frame(maxWidth: MacShellMetrics.libraryContentMaxWidth)
            .frame(maxWidth: .infinity)

            content
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .accessibilityIdentifier("screen_history")
        .onAppear(perform: handleAppear)
        .onReceive(generationLibraryEvents.generationAppended) { generation in handleGenerationAppended(generation) }
        .onReceive(NotificationCenter.default.publisher(for: .generationHistoryRecoveryChanged)) { _ in
            refreshRecoveryState()
        }
        .onChange(of: itemsRevision) { _, _ in recomputeFilteredItems() }
        .onChange(of: sortOrder) { _, _ in recomputeFilteredItems() }
        .onChange(of: modeFilter) { _, _ in recomputeFilteredItems() }
        .onChange(of: expandedProjects) { _, _ in recomputeSections() }
        .onChange(of: searchText) { _, _ in
            searchDebounceTask?.cancel()
            searchDebounceTask = Task {
                try? await Task.sleep(for: .milliseconds(200))
                guard !Task.isCancelled else { return }
                recomputeFilteredItems()
            }
        }
        .onDisappear(perform: handleDisappear)
        .onChange(of: clearRequest) { _, request in
            guard let request else { return }
            // Defer the binding reset: writing the parent's state back to
            // nil synchronously inside this view's update can drop the change.
            Task { @MainActor in clearRequest = nil }
            handleClearRequest(request)
        }
        .alert(MacInterfaceText.historyDeleteTitle, isPresented: $showDeleteConfirmation) {
            Button(MacInterfaceText.cancel, role: .cancel) {
                itemToDelete = nil
            }
            Button(MacInterfaceText.delete, role: .destructive) {
                if let item = itemToDelete {
                    confirmDelete(item)
                }
                itemToDelete = nil
            }
        } message: {
            Text(MacInterfaceText.historyDeleteDetail)
        }
        .alert(item: $actionAlert) { alert in
            if let confirmTitle = alert.confirmTitle, let onConfirm = alert.onConfirm {
                Alert(
                    title: Text(alert.title),
                    message: Text(alert.message),
                    primaryButton: .destructive(Text(confirmTitle), action: onConfirm),
                    secondaryButton: .cancel()
                )
            } else {
                Alert(
                    title: Text(alert.title),
                    message: Text(alert.message),
                    dismissButton: .default(Text(MacInterfaceText.ok))
                )
            }
        }
        .sheet(item: $savedVoiceSheetConfiguration) { configuration in
            MacSavedVoiceSheet(configuration: configuration) { voice in
                handleSavedVoice(voice)
            }
            .environmentObject(ttsEngineStore)
        }
    }

    @ViewBuilder
    private var content: some View {
        if let loadError, items.isEmpty, !isLoading {
            historyStateContainer(identifier: "history_errorState") {
                VocelloEmptyStateCard(
                    title: MacInterfaceText.historyLoadFailedTitle,
                    message: "\(MacInterfaceText.historyLoadFailedDetail)\n\(loadError)",
                    symbolName: "exclamationmark.triangle",
                    tint: MacTheme.Status.guarded,
                    maxWidth: MacShellMetrics.emptyStateCardMaxWidth,
                    symbolIsDecorative: true
                )
                Button(MacInterfaceText.retry) {
                    reloadHistory(reopenFailedStore: true)
                }
                .buttonStyle(.bordered)
                .tint(MacTheme.historyTint)
                .accessibilityIdentifier("historyRetryButton")
            }
        } else if isLoading && items.isEmpty {
            historyStateContainer(identifier: "history_loadingState") {
                ProgressView(MacInterfaceText.historyLoading)
                    .tint(MacTheme.historyTint)
            }
        } else if filteredItems.isEmpty {
            historyStateContainer(identifier: "history_emptyState") {
                VocelloEmptyStateCard(
                    title: items.isEmpty ? MacInterfaceText.historyNoTakesTitle : MacInterfaceText.historyNoMatchesTitle,
                    message: items.isEmpty ? MacInterfaceText.historyNoTakesDetail : MacInterfaceText.historyNoMatchesDetail,
                    symbolName: items.isEmpty ? "clock.arrow.circlepath" : "line.3.horizontal.decrease.circle",
                    tint: MacTheme.historyTint,
                    maxWidth: MacShellMetrics.emptyStateCardMaxWidth,
                    symbolIsDecorative: true
                )
            }
        } else {
            List {
                ForEach(sections) { section in
                    Section {
                        ForEach(section.entries) { entry in
                            rowView(for: entry)
                                .listRowInsets(EdgeInsets(top: 0, leading: 8, bottom: 0, trailing: 8))
                                .listRowSeparator(.hidden)
                                .listRowBackground(Color.clear)
                        }
                    } header: {
                        if let bucket = section.bucket {
                            VocelloSectionHeading(bucket.title, titleFontSize: 11, topPadding: 18, titleLineLimit: 1, expandsWidth: true)
                        }
                    }
                }
            }
            .listStyle(.plain)
            .scrollContentBackground(.hidden)
            // Match the generation screens' content column: uncapped rows
            // tear apart on wide displays.
            .frame(maxWidth: MacShellMetrics.libraryContentMaxWidth)
            .frame(maxWidth: .infinity)
        }
    }

    @ViewBuilder
    private func rowView(for entry: MacHistoryDisplayEntry) -> some View {
        let item = entry.item
        VStack(alignment: .leading, spacing: 0) {
            MacHistoryItemCard(
                generation: item.generation,
                rowID: item.id,
                textPreview: item.textPreview,
                formattedDate: item.formattedDate,
                audioFileExists: item.audioFileExists,
                waveformSeed: item.waveformSeed,
                allowsDeletion: !databaseUnavailable,
                onPlay: {
                    audioPlayer.playFile(item.generation.audioPath, title: item.textPreview)
                },
                onSaveToSavedVoices: item.saveVoiceSource == nil ? nil : {
                    savedVoiceSheetConfiguration = item.makeSaveVoiceConfiguration()
                },
                onSaveAs: { exportGeneration(item) },
                onDelete: {
                    itemToDelete = item
                    showDeleteConfirmation = true
                }
            )
            .contextMenu {
                Button {
                    MacHistoryFileActions.revealInFinder(item.generation.audioPath)
                } label: {
                    Label(MacInterfaceText.historyRevealInFinder, systemImage: "folder")
                }
                .disabled(!item.audioFileExists)

                if let onPinSeed, let seedValue = item.generation.samplingSeed {
                    Button {
                        onPinSeed(item.generation)
                    } label: {
                        Label(MacInterfaceText.historyPinSeed(String(seedValue)), systemImage: "pin")
                    }
                    .accessibilityIdentifier("history_pinSeedButton")
                }
            }

            if let toggle = entry.projectToggle, toggle.segmentCount > 0 {
                segmentsToggle(projectID: toggle.projectID, segmentCount: toggle.segmentCount)
            }
        }
        .padding(.leading, entry.isSegment ? 24 : 0)
    }

    private func segmentsToggle(projectID: String, segmentCount: Int) -> some View {
        let isExpanded = expandedProjects.contains(projectID)
        return Button {
            AppLaunchConfiguration.performAnimated(MacTheme.Motion.disclosure) {
                if isExpanded {
                    expandedProjects.remove(projectID)
                } else {
                    expandedProjects.insert(projectID)
                }
            }
        } label: {
            HStack(spacing: 6) {
                Image(systemName: "rectangle.stack")
                Text(
                    segmentCount == 1
                        ? MacInterfaceText.historySegmentsOne
                        : MacInterfaceText.historySegmentsMany(String(segmentCount))
                )
                Image(systemName: isExpanded ? "chevron.up" : "chevron.down")
            }
            .font(.footnote.weight(.medium))
            .foregroundStyle(MacTheme.Text.secondary)
            .padding(.vertical, 6)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .padding(.leading, 72)
        .accessibilityValue(isExpanded ? MacInterfaceText.historySegmentsExpanded : MacInterfaceText.historySegmentsCollapsed)
        .accessibilityIdentifier("history_longFormSegmentsToggle_\(String(projectID.prefix(8)))")
    }

    private var recoveryMessage: String {
        if recoverySnapshot.longFormRecoveryPending {
            return VocelloPresentationText.longFormRecoveryDetail
        }
        if recoverySnapshot.unqueuedCount > 0 {
            return VocelloPresentationText.historyUnqueuedDetail
        }
        if recoverySnapshot.issueCount > 0 {
            return MacInterfaceText.historyRecoveryUnverified
        }
        let count = recoverySnapshot.pendingCount
        return count == 1
            ? MacInterfaceText.historyRecoveryQueuedOne
            : MacInterfaceText.historyRecoveryQueuedMany(String(count))
    }
}

private extension MacHistoryScreen {
    func handleAppear() {
        reloadHistory()
        refreshRecoveryState()
    }

    /// Append-in-place handler for the `generationAppended` publisher; avoids
    /// the full SQLite re-fetch and stats only the appended row's file.
    func handleGenerationAppended(_ generation: Generation) {
        if generation.longFormRole == "joined" {
            // Project acceptance atomically adds segments and replaces the old
            // joined row; an append-only update would leave stale rows.
            reloadHistory()
            return
        }
        databaseUnavailable = false
        if let existingIndex = items.firstIndex(where: { $0.generation.id == generation.id && generation.id != nil }) {
            items[existingIndex] = MacHistoryListItem(generation: generation)
        } else {
            items.append(MacHistoryListItem(generation: generation))
        }
        itemsRevision &+= 1
        MacHistorySessionCache.items = items
    }

    func handleDisappear() {
        loadTask?.cancel()
        loadTask = nil
        searchDebounceTask?.cancel()
    }

    func handleSavedVoice(_ voice: Voice) {
        savedVoicesViewModel.insertOrReplace(voice)
        Task { await savedVoicesViewModel.refresh(using: ttsEngineStore) }
        presentActionAlert(
            title: MacInterfaceText.savedVoiceAddedTitle,
            message: MacInterfaceText.savedVoiceAddedMessage(voice.name)
        )
    }

    func handleClearRequest(_ request: HistoryClearRequest) {
        guard !databaseUnavailable else {
            presentActionAlert(
                title: MacInterfaceText.historyUnavailableTitle,
                message: MacInterfaceText.historyUnavailableMessage
            )
            return
        }
        guard !items.isEmpty else {
            presentActionAlert(title: MacInterfaceText.historyEmptyTitle, message: MacInterfaceText.historyEmptyMessage)
            return
        }
        switch request.scope {
        case .keepFiles:
            actionAlert = MacHistoryActionAlert(
                title: MacInterfaceText.historyClearTitle,
                message: MacInterfaceText.historyClearMessage(String(items.count)),
                confirmTitle: MacInterfaceText.historyClearConfirm,
                onConfirm: { performClearAll(deleteAudio: false) }
            )
        case .deleteFiles:
            actionAlert = MacHistoryActionAlert(
                title: MacInterfaceText.historyClearDeleteTitle,
                message: MacInterfaceText.historyClearDeleteMessage(String(items.count)),
                confirmTitle: MacInterfaceText.historyDeleteEverything,
                onConfirm: { performClearAll(deleteAudio: true) }
            )
        }
    }

    func recomputeFilteredItems() {
        let query = searchText.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        var result = items.filter { modeFilter.matches(mode: $0.generation.mode) }
        if !query.isEmpty {
            result = result.filter { $0.searchKey.contains(query) }
        }

        switch sortOrder {
        case .newest:
            result.sort { $0.generation.createdAt > $1.generation.createdAt }
        case .oldest:
            result.sort { $0.generation.createdAt < $1.generation.createdAt }
        case .longestDuration:
            result.sort { ($0.generation.duration ?? 0) > ($1.generation.duration ?? 0) }
        case .shortestDuration:
            result.sort { ($0.generation.duration ?? 0) < ($1.generation.duration ?? 0) }
        case .mode:
            result.sort { $0.generation.mode < $1.generation.mode }
        }

        filteredItems = result
        recomputeSections()
    }

    func recomputeSections() {
        let entries = MacHistoryDisplayEntry.entries(
            from: filteredItems,
            searchActive: searchActive,
            expandedProjects: expandedProjects
        )
        sections = MacHistorySection.sections(
            from: entries,
            groupByDate: sortOrder.groupsByDate && !searchActive
        )
    }

    @ViewBuilder
    func historyStateContainer<Content: View>(
        identifier: String,
        @ViewBuilder content: () -> Content
    ) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            content()
        }
        .padding(24)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier(identifier)
    }

    func reloadHistory(reopenFailedStore: Bool = false) {
        if loadTask != nil {
            pendingReloadAfterCurrentLoad = true
            return
        }

        let hasExistingItems = !items.isEmpty
        if !hasExistingItems {
            isLoading = true
            loadError = nil
        }

        let interval = AppPerformanceSignposts.begin("History Reload")
        let wallStart = DispatchTime.now().uptimeNanoseconds

        loadTask = Task {
            var didFinishReload = false
            defer {
                if !didFinishReload {
                    Task { @MainActor in
                        cancelReload(interval: interval)
                    }
                }
            }

            do {
                let loadedItems = try await Task.detached(priority: .userInitiated) {
                    if reopenFailedStore {
                        try DatabaseService.shared.reopenIfNeeded()
                    }
                    _ = await GenerationHistoryRecovery.reconcile()
                    let generations = try DatabaseService.shared.fetchAllGenerations()
                    return generations.map(MacHistoryListItem.init)
                }.value

                guard !Task.isCancelled else { return }
                await MainActor.run {
                    items = loadedItems
                    itemsRevision &+= 1
                    MacHistorySessionCache.items = loadedItems
                    loadError = nil
                    databaseUnavailable = false
                    isLoading = false
                    finishReload(wallStart: wallStart, interval: interval)
                    refreshRecoveryState()
                }
                didFinishReload = true
            } catch {
                guard !Task.isCancelled else { return }
                await MainActor.run {
                    databaseUnavailable = true
                    if hasExistingItems {
                        presentActionAlert(
                            title: MacInterfaceText.historyRefreshFailed,
                            message: error.localizedDescription
                        )
                    } else {
                        loadError = error.localizedDescription
                    }
                    isLoading = false
                    finishReload(wallStart: wallStart, interval: interval)
                }
                didFinishReload = true
            }
        }
    }

    func finishReload(wallStart: UInt64, interval: AppPerformanceSignposts.Interval) {
        AppPerformanceSignposts.end(interval)
        if DebugMode.isEnabled {
            let elapsedMs = Int((DispatchTime.now().uptimeNanoseconds - wallStart) / 1_000_000)
            print("[Performance][MacHistoryScreen] reload_wall_ms=\(elapsedMs)")
        }

        loadTask = nil

        if pendingReloadAfterCurrentLoad {
            pendingReloadAfterCurrentLoad = false
            reloadHistory()
        }
    }

    func cancelReload(interval: AppPerformanceSignposts.Interval) {
        AppPerformanceSignposts.end(interval)
        isLoading = false
        loadTask = nil
        pendingReloadAfterCurrentLoad = false
    }

    func exportGeneration(_ item: MacHistoryListItem) {
        if let failure = MacHistoryFileActions.saveCopy(of: item.generation.audioPath) {
            presentActionAlert(
                title: MacInterfaceText.historyExportError,
                message: MacInterfaceText.historyExportErrorMessage(failure)
            )
        }
    }

    func exportPendingAudio() {
        guard let failures = MacHistoryFileActions.exportPendingAudio(recoveryAudioURLs), failures > 0 else { return }
        presentActionAlert(
            title: MacInterfaceText.historyExportWarning,
            message: VocelloPresentationText.recoveryExportFailure(failures)
        )
    }

    func refreshRecoveryState() {
        Task {
            let snapshot = await GenerationHistoryRecovery.snapshot()
            let urls = await GenerationHistoryRecovery.recoveryExportURLs()
            guard !Task.isCancelled else { return }
            recoverySnapshot = snapshot
            recoveryAudioURLs = urls
        }
    }

    func confirmDelete(_ item: MacHistoryListItem) {
        switch deleteItem(item) {
        case .deleted:
            break
        case .databaseFailure(let message):
            presentActionAlert(
                title: MacInterfaceText.historyDeleteError,
                message: MacInterfaceText.historyDeleteErrorMessage(message)
            )
        case .audioCleanupFailure(let message):
            presentActionAlert(
                title: MacInterfaceText.historyDeleteWarning,
                message: MacInterfaceText.historyDeleteWarningMessage(message)
            )
        }
    }

    func deleteItem(_ item: MacHistoryListItem) -> HistoryDeletionEngine.SingleOutcome {
        let outcome = HistoryDeletionEngine.databaseBacked.deleteSingle(
            recordID: item.generation.id,
            audioPath: item.generation.audioPath
        )

        if case .databaseFailure = outcome {
            databaseUnavailable = true
            return outcome
        }
        databaseUnavailable = false

        items.removeAll { $0.id == item.id }
        itemsRevision &+= 1
        MacHistorySessionCache.items = items
        return outcome
    }

    /// Clears the whole history. With `deleteAudio` false (GitHub #48), only
    /// the database rows and session cache go; the WAVs stay on disk. The
    /// durable clear transaction captures database and pending-outbox paths,
    /// deletes database rows first, then clears recovery entries and files.
    func performClearAll(deleteAudio: Bool) {
        Task { @concurrent in
            let outcome: GenerationHistoryClearOutcome
            do {
                outcome = try await GenerationHistoryRecovery.clearAll(deleteAudio: deleteAudio)
            } catch {
                await MainActor.run {
                    databaseUnavailable = true
                    presentActionAlert(
                        title: MacInterfaceText.historyClearError,
                        message: error.localizedDescription
                    )
                }
                return
            }

            let failures = outcome.failedFileRemovals
            await MainActor.run {
                databaseUnavailable = false
                items = []
                itemsRevision &+= 1
                MacHistorySessionCache.items = []

                if failures > 0 {
                    presentActionAlert(
                        title: MacInterfaceText.historyClearWarning,
                        message: failures == 1
                            ? MacInterfaceText.historyClearWarningOne
                            : MacInterfaceText.historyClearWarningMany(String(failures))
                    )
                }
                NotificationCenter.default.post(name: .generationHistoryRecoveryChanged, object: nil)
            }
        }
    }

    func presentActionAlert(title: String, message: String) {
        actionAlert = MacHistoryActionAlert(title: title, message: message)
    }
}
