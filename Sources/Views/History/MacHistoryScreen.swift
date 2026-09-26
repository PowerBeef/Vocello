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
        self.formattedDate = generation.formattedDate(in: MacInterfaceLanguage.current)
        self.searchKey = GenerationHistoryPageQuery.lowercasedSearchKey(text: generation.text, voice: generation.voice)
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
            return MacInterfaceText.historySuggestedVoiceName(voice)
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
/// without stat-ing files or re-deriving row data, and the page they came from.
@MainActor private enum MacHistorySessionCache {
    static var items: [MacHistoryListItem] = []
    static var pageLimit = GenerationHistoryPageRequest.pageSize
    static var loadedRequest: GenerationHistoryPageRequest?
    static var hasMoreItems = false
    static var archiveCount = 0
}

private extension HistorySortOrder {
    var pageOrder: GenerationHistoryPageRequest.Order {
        switch self {
        case .newest: .newest
        case .oldest: .oldest
        case .longestDuration: .longest
        case .shortestDuration: .shortest
        case .mode: .mode
        }
    }
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
    /// Bounded pages (AUD-05), as on iPhone: `items` holds the first
    /// `pageLimit` entries `loadedRequest` asked for; Show More asks for one
    /// more page. `archiveCount` counts every row, whatever the filter.
    @State private var pageLimit = MacHistorySessionCache.pageLimit
    @State private var loadedRequest: GenerationHistoryPageRequest? = MacHistorySessionCache.loadedRequest
    @State private var hasMoreItems = MacHistorySessionCache.hasMoreItems
    @State private var archiveCount = MacHistorySessionCache.archiveCount
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

    /// No row at all, as opposed to no row matching the filter or search.
    private var archiveIsEmpty: Bool {
        items.isEmpty && archiveCount == 0
    }

    /// The loaded rows are the complete, unfiltered archive.
    private var holdsWholeArchive: Bool {
        guard let loadedRequest, !hasMoreItems else { return false }
        return loadedRequest.isUnfiltered
    }

    var body: some View {
        VStack(spacing: 0) {
            VStack(alignment: .leading, spacing: VocelloTheme.Spacing.md) {
                if recoverySnapshot.needsAttention {
                    MacHistoryRecoveryBanner(
                        title: recoveryTitle,
                        message: recoveryMessage,
                        canReveal: recoverySnapshot.availableAudioCount > 0
                            || recoverySnapshot.pendingAudioRemovalCount > 0
                            || recoverySnapshot.unreadableAudioRemovalCount > 0,
                        canExport: !recoveryAudioURLs.isEmpty,
                        onRetry: { retryRecovery() },
                        onReveal: { MacHistoryFileActions.revealRecoveryAudio(recoveryAudioURLs) },
                        onExport: exportPendingAudio
                    )
                }

                MacFilterChipRow(
                    options: HistoryModeFilter.allCases,
                    selection: $modeFilter,
                    label: \.title,
                    leading: { filter in AnyView(VocelloModeDot(tint: filter.dotColor)) },
                    accessibilityIdentifier: \.accessibilityID
                )
                .accessibilityElement(children: .contain)
                .accessibilityLabel(MacInterfaceText.historyFilterAccessibility)
                .frame(maxWidth: .infinity, alignment: .leading)
                .accessibilityIdentifier("history_modeFilter")
            }
            .padding(.horizontal, VocelloTheme.Spacing.xl)
            .padding(.top, VocelloTheme.Spacing.lg)
            .padding(.bottom, VocelloTheme.Spacing.xs)
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
        .onChange(of: sortOrder) { _, _ in pageInputsChanged() }
        .onChange(of: modeFilter) { _, _ in pageInputsChanged() }
        .onChange(of: expandedProjects) { _, _ in recomputeSections() }
        .onChange(of: searchText) { _, _ in
            searchDebounceTask?.cancel()
            searchDebounceTask = Task {
                try? await Task.sleep(for: .milliseconds(200))
                guard !Task.isCancelled else { return }
                pageInputsChanged()
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
                    Task { await confirmDelete(item) }
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
                    title: archiveIsEmpty ? MacInterfaceText.historyNoTakesTitle : MacInterfaceText.historyNoMatchesTitle,
                    message: archiveIsEmpty ? MacInterfaceText.historyNoTakesDetail : MacInterfaceText.historyNoMatchesDetail,
                    symbolName: archiveIsEmpty ? "clock.arrow.circlepath" : "line.3.horizontal.decrease.circle",
                    tint: MacTheme.historyTint,
                    maxWidth: MacShellMetrics.emptyStateCardMaxWidth,
                    symbolIsDecorative: true
                )
            }
        } else {
            List {
                ForEach(sections) { section in
                    if let bucket = section.bucket {
                        // Plain rows avoid the native pinned-header material and rule.
                        VocelloSectionHeading(
                            bucket.title,
                            titleFontSize: MacType.style(.eyebrow).size,
                            topPadding: VocelloTheme.Spacing.xl,
                            titleLineLimit: 1,
                            expandsWidth: true,
                            horizontalInset: MacShellMetrics.libraryRowHorizontalInset
                        )
                        .accessibilityIdentifier("history_sectionHeading_\(section.id)")
                        .listRowInsets(EdgeInsets())
                        .listRowSeparator(.hidden)
                        .listRowBackground(Color.clear)
                    }
                    ForEach(section.entries) { entry in
                        rowView(for: entry)
                            .listRowInsets(EdgeInsets(
                                top: 0,
                                leading: MacShellMetrics.libraryRowHorizontalInset,
                                bottom: 0,
                                trailing: MacShellMetrics.libraryRowHorizontalInset
                            ))
                            .listRowSeparator(.hidden)
                            .listRowBackground(Color.clear)
                    }
                }
                if hasMoreItems {
                    Button(MacInterfaceText.historyShowMore) {
                        pageLimit += GenerationHistoryPageRequest.pageSize
                        reloadHistory(reconciling: false)
                    }
                    .buttonStyle(.bordered)
                    .tint(MacTheme.historyTint)
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, VocelloTheme.Spacing.md)
                    .accessibilityIdentifier("history_showMoreButton")
                    .listRowInsets(EdgeInsets())
                    .listRowSeparator(.hidden)
                    .listRowBackground(Color.clear)
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
                    audioPlayer.playFile(item.generation.audioPath, title: item.textPreview,
                                         generationMode: GenerationMode(rawValue: item.generation.mode))
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
        .padding(.leading, entry.isSegment ? VocelloTheme.Spacing.xxl : 0)
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
            HStack(spacing: VocelloTheme.Spacing.tight) {
                Image(systemName: "rectangle.stack")
                Text(
                    segmentCount == 1
                        ? MacInterfaceText.historySegmentsOne
                        : MacInterfaceText.historySegmentsMany(String(segmentCount))
                )
                Image(systemName: isExpanded ? "chevron.up" : "chevron.down")
            }
            .macType(.captionEmphasis)
            .foregroundStyle(MacTheme.Text.secondary)
            .padding(.vertical, VocelloTheme.Spacing.tight)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .padding(.leading, MacHistoryItemCard.contentLeadingInset)
        .accessibilityValue(isExpanded ? MacInterfaceText.historySegmentsExpanded : MacInterfaceText.historySegmentsCollapsed)
        .accessibilityIdentifier("history_longFormSegmentsToggle_\(String(projectID.prefix(8)))")
    }

    private var recoveryTitle: String {
        switch recoverySnapshot.notice {
        case .clearPending:
            return MacInterfaceText.presentation.historyClearPendingTitle
        case .audioRemovals, .unreadableAudioRemovals:
            return MacInterfaceText.historyAudioRemovalTitle
        default:
            return MacInterfaceText.historyFinishedAudioWaiting
        }
    }

    /// One state per notice, chosen by the snapshot (PA-30): a pending clear has
    /// its own copy and no count is ever zero.
    private var recoveryMessage: String {
        switch recoverySnapshot.notice {
        case .longFormRecovery:
            return VocelloPresentationText.longFormRecoveryDetail
        case .unqueued:
            return VocelloPresentationText.historyUnqueuedDetail
        case .unverifiedRecord:
            return MacInterfaceText.historyRecoveryUnverified
        case .clearPending:
            return MacInterfaceText.presentation.historyClearPendingDetail
        case .queuedTakes(let count):
            return count == 1
                ? MacInterfaceText.historyRecoveryQueuedOne
                : MacInterfaceText.historyRecoveryQueuedMany(String(count))
        case .unreadableAudioRemovals:
            return MacInterfaceText.presentation.historyUnreadableAudioRemovals
        case .audioRemovals(let count):
            return count == 1
                ? MacInterfaceText.historyAudioRemovalOne
                : MacInterfaceText.historyAudioRemovalMany(String(count))
        case nil:
            return ""
        }
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
            archiveCount += 1
            MacHistorySessionCache.archiveCount = archiveCount
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
        guard archiveCount > 0 || !items.isEmpty else {
            presentActionAlert(title: MacInterfaceText.historyEmptyTitle, message: MacInterfaceText.historyEmptyMessage)
            return
        }
        switch request.scope {
        case .keepFiles:
            actionAlert = MacHistoryActionAlert(
                title: MacInterfaceText.historyClearTitle,
                message: MacInterfaceText.historyClearMessage(max(archiveCount, items.count)),
                confirmTitle: MacInterfaceText.historyClearConfirm,
                onConfirm: { performClearAll(deleteAudio: false) }
            )
        case .deleteFiles:
            actionAlert = MacHistoryActionAlert(
                title: MacInterfaceText.historyClearDeleteTitle,
                message: MacInterfaceText.historyClearDeleteMessage(max(archiveCount, items.count)),
                confirmTitle: MacInterfaceText.historyDeleteEverything,
                onConfirm: { performClearAll(deleteAudio: true) }
            )
        }
    }

    /// A sort, filter or search change. While the whole archive is loaded it is
    /// sorted and filtered in memory, as before paging; otherwise the database
    /// answers from the first page, so no match hides beyond the loaded rows.
    func pageInputsChanged() {
        recomputeFilteredItems()
        guard !holdsWholeArchive else { return }
        pageLimit = GenerationHistoryPageRequest.pageSize
        reloadHistory(reconciling: false)
    }

    /// The page the current sort, filter and search ask for; the search uses
    /// this list's own predicate (`MacHistoryListItem.searchKey`).
    func currentPageRequest() -> GenerationHistoryPageRequest {
        GenerationHistoryPageRequest(
            mode: modeFilter.generationMode?.rawValue,
            query: searchText,
            searchStyle: .lowercasedTranscriptAndVoice,
            order: sortOrder.pageOrder,
            limit: pageLimit
        )
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
        VStack(alignment: .leading, spacing: VocelloTheme.Spacing.md) {
            content()
        }
        .padding(VocelloTheme.Spacing.xl)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier(identifier)
    }

    /// Reads the current page off the main actor. A full reload reconciles
    /// pending History first; a sort, filter, search or Show More only reads.
    /// A reload asked for during another coalesces into one full reload.
    func reloadHistory(reopenFailedStore: Bool = false, reconciling: Bool = true) {
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
        let request = currentPageRequest()

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
                let (loadedItems, hasMore, count) = try await Task.detached(priority: .userInitiated) {
                    if reopenFailedStore {
                        try DatabaseService.shared.reopenIfNeeded()
                    }
                    if reconciling {
                        _ = await GenerationHistoryRecovery.reconcile()
                    }
                    let page = try DatabaseService.shared.fetchGenerationPage(request)
                    return (page.rows.map(MacHistoryListItem.init), page.hasMore, page.archiveCount)
                }.value

                guard !Task.isCancelled else { return }
                await MainActor.run {
                    items = loadedItems
                    loadedRequest = request
                    hasMoreItems = hasMore
                    archiveCount = count
                    itemsRevision &+= 1
                    MacHistorySessionCache.items = loadedItems
                    MacHistorySessionCache.pageLimit = request.limit
                    MacHistorySessionCache.loadedRequest = request
                    MacHistorySessionCache.hasMoreItems = hasMore
                    MacHistorySessionCache.archiveCount = count
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

    /// Retry from the recovery banner. It also dismisses the notice about
    /// removal lists that could not be read, which the user has now seen; the
    /// audio those lists named is not deleted (PA-30).
    func retryRecovery() {
        let discardsUnreadableLists = recoverySnapshot.notice == .unreadableAudioRemovals
        Task {
            if discardsUnreadableLists {
                await GenerationHistoryRecovery.discardUnreadableAudioRemovals()
            }
            reloadHistory(reopenFailedStore: true)
        }
    }

    func confirmDelete(_ item: MacHistoryListItem) async {
        switch await deleteItem(item) {
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

    /// Off the main actor, because the work behind this is a synchronous SQLite
    /// write followed by a file removal, and both were running on the thread
    /// drawing the list. The engine stays pure and synchronous -- its rules are
    /// tested in `QwenVoiceCore` and are worth keeping that way -- so the hop
    /// happens here, at the one place that knows it is on the main actor.
    /// Audio that could not be removed is kept for a later reconcile (AUD-05).
    func deleteItem(_ item: MacHistoryListItem) async -> HistoryDeletionEngine.SingleOutcome {
        let engine = GenerationHistoryRecovery.deletionEngine
        let recordID = item.generation.id
        let audioPath = item.generation.audioPath
        let outcome = await Task.detached(priority: .userInitiated) {
            engine.deleteSingle(recordID: recordID, audioPath: audioPath)
        }.value

        if case .databaseFailure = outcome {
            databaseUnavailable = true
            return outcome
        }
        databaseUnavailable = false
        if case .audioCleanupFailure = outcome {
            _ = await GenerationHistoryRecovery.retainAudioRemoval(audioPath)
            refreshRecoveryState()
        }

        items.removeAll { $0.id == item.id }
        archiveCount = max(0, archiveCount - 1)
        itemsRevision &+= 1
        MacHistorySessionCache.items = items
        MacHistorySessionCache.archiveCount = archiveCount
        return outcome
    }

    /// Clears the whole history. With `deleteAudio` false (GitHub #48), only
    /// the database rows and session cache go; the WAVs stay on disk. The
    /// durable clear transaction captures database and pending-outbox paths
    /// with the highest row id, deletes the rows up to it first, then clears
    /// recovery entries and files.
    func performClearAll(deleteAudio: Bool) {
        Task { @concurrent in
            let outcome: GenerationHistoryClearOutcome
            do {
                outcome = try await GenerationHistoryRecovery.clearAll(deleteAudio: deleteAudio)
            } catch {
                await MainActor.run {
                    // The same localized message as iOS for every refusal or
                    // failure; the typed outbox errors are English-only (PA-30).
                    presentActionAlert(
                        title: MacInterfaceText.historyClearError,
                        message: MacInterfaceText.presentation.historyClearFailedDetail
                    )
                    // A pending clear may have finished before this request
                    // failed, and the read decides whether the database itself
                    // is unavailable (AUD-05).
                    reloadHistory(reconciling: false)
                }
                return
            }

            let failures = outcome.failedFileRemovals
            await MainActor.run {
                databaseUnavailable = false
                items = []
                hasMoreItems = false
                archiveCount = 0
                itemsRevision &+= 1
                MacHistorySessionCache.items = []
                MacHistorySessionCache.hasMoreItems = false
                MacHistorySessionCache.archiveCount = 0
                // The clear is bounded: a take saved while it ran survives,
                // so read what remains rather than assuming nothing (AUD-05).
                reloadHistory()

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
