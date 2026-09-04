import AppKit
import QwenVoiceCore
import QwenVoiceNative
import SwiftUI
import UniformTypeIdentifiers

private struct HistoryListItem: Identifiable, Sendable {
    let generation: Generation
    let audioFileExists: Bool
    let textPreview: String
    let formattedDate: String
    let searchKey: String
    /// Cached `SavedVoiceSheetConfiguration` for the "Save to Saved
    /// Voices" action, derived once at construction time. Previously
    /// `saveVoiceConfiguration(for: item)` was recomputed for every
    /// visible row on every body invalidation; now the per-row work
    /// happens once during item init (off-main, in `reloadHistory`).
    /// Nil for non-clone/design modes (the action is unavailable).
    let saveVoiceConfiguration: SavedVoiceSheetConfiguration?

    var id: String {
        if let generationID = generation.id {
            return "generation-\(generationID)"
        }
        return "generation-\(generation.audioPath)-\(generation.createdAt.timeIntervalSince1970)"
    }

    init(generation: Generation) {
        self.generation = generation
        self.audioFileExists = FileManager.default.fileExists(atPath: generation.audioPath)
        self.textPreview = generation.textPreview
        self.formattedDate = Self.formattedDate(for: generation.createdAt)
        self.searchKey = "\(generation.text)\n\(generation.voice ?? "")".lowercased()
        self.saveVoiceConfiguration = Self.makeSaveVoiceConfiguration(for: generation)
    }

    private static func formattedDate(for date: Date) -> String {
        date.formatted(date: .abbreviated, time: .shortened)
    }

    private static func makeSaveVoiceConfiguration(for generation: Generation) -> SavedVoiceSheetConfiguration? {
        switch generation.mode {
        case GenerationMode.clone.rawValue:
            return .cloneResult(
                suggestedName: suggestedSavedVoiceName(for: generation),
                audioPath: generation.audioPath,
                transcript: generation.text
            )
        case GenerationMode.design.rawValue:
            return .designResult(
                voiceDescription: generation.voice ?? "",
                audioPath: generation.audioPath,
                transcript: generation.text
            )
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

/// One rendered row of the History list after long-form grouping. Segments of
/// a project with a joined row collapse under it; searching renders flat.
private struct HistoryDisplayEntry: Identifiable {
    let item: HistoryListItem
    let isSegment: Bool
    /// Present on a long-form joined ("project") row: toggling reveals its
    /// segment map beneath.
    let projectToggle: (projectID: String, segmentCount: Int)?

    var id: String { item.id }

    static func entries(
        from items: [HistoryListItem],
        searchActive: Bool,
        expandedProjects: Set<String>
    ) -> [HistoryDisplayEntry] {
        guard !searchActive else {
            return items.map { HistoryDisplayEntry(item: $0, isSegment: false, projectToggle: nil) }
        }
        var segmentsByProject: [String: [HistoryListItem]] = [:]
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

        var entries: [HistoryDisplayEntry] = []
        for item in items {
            let projectID = item.generation.longFormProjectID
            switch item.generation.longFormRole {
            case "segment":
                // Collapsed under the joined row; orphaned segments (no joined
                // row yet) stay visible in place.
                if let projectID, projectsWithJoinedRow.contains(projectID) {
                    continue
                }
                entries.append(HistoryDisplayEntry(item: item, isSegment: false, projectToggle: nil))
            case "joined":
                let segments = projectID.flatMap { segmentsByProject[$0] } ?? []
                entries.append(
                    HistoryDisplayEntry(
                        item: item,
                        isSegment: false,
                        projectToggle: projectID.map { ($0, segments.count) }
                    )
                )
                if let projectID, expandedProjects.contains(projectID) {
                    // Segment map in generation order (oldest first).
                    for segment in segments.sorted(by: { $0.generation.createdAt < $1.generation.createdAt }) {
                        entries.append(HistoryDisplayEntry(item: segment, isSegment: true, projectToggle: nil))
                    }
                }
            default:
                entries.append(HistoryDisplayEntry(item: item, isSegment: false, projectToggle: nil))
            }
        }
        return entries
    }
}

private struct HistoryActionAlert: Identifiable {
    let id = UUID()
    let title: String
    let message: String
    /// When set, the alert renders as a destructive confirm/cancel pair
    /// instead of a single OK (used by the clear-history flow, which rides
    /// this proven presentation slot).
    var confirmTitle: String? = nil
    var onConfirm: (() -> Void)? = nil
}

@MainActor private enum HistorySessionCache {
    static var generations: [Generation] = []
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

enum HistorySortOrder: String, CaseIterable, Identifiable {
    case newest
    case oldest
    case longestDuration
    case shortestDuration
    case mode

    var id: String { rawValue }

    var label: String {
        switch self {
        case .newest:
            return "Newest"
        case .oldest:
            return "Oldest"
        case .longestDuration:
            return "Longest"
        case .shortestDuration:
            return "Shortest"
        case .mode:
            return "Mode"
        }
    }
}

/// Toolbar→view bridge for the clear-history actions (mirrors the Voices
/// screen's enroll-request pattern): the window toolbar bumps the request,
/// HistoryView confirms and performs it. `keepFiles` answers GitHub #48 —
/// purge the history list without touching the generated audio on disk.
struct HistoryClearRequest: Equatable {
    enum Scope: Equatable {
        case keepFiles
        case deleteFiles
    }

    let scope: Scope
    let id: UUID

    init(scope: Scope) {
        self.scope = scope
        self.id = UUID()
    }
}

struct HistoryView: View {
    @EnvironmentObject private var audioPlayer: AudioPlayerViewModel
    @Environment(SavedVoicesViewModel.self) private var savedVoicesViewModel
    @EnvironmentObject private var generationLibraryEvents: GenerationLibraryEvents
    /// Plain reference, not `@EnvironmentObject` (W1-D): History uses the
    /// store only to forward into the saved-voice sheet and for one
    /// imperative refresh — subscribing re-rendered every row on every
    /// engine tick for nothing.
    let ttsEngineStore: TTSEngineStore
    @Binding var searchText: String
    @Binding var sortOrder: HistorySortOrder
    @Binding var clearRequest: HistoryClearRequest?
    /// DP-15: routes a row's recorded sampling seed into the matching mode's
    /// draft as the pinned seed. Nil hides the action (e.g. no host wiring).
    var onPinSeed: ((Generation) -> Void)? = nil

    @State private var items: [HistoryListItem] = HistorySessionCache.generations.map(HistoryListItem.init)
    @State private var isLoading = false
    @State private var loadTask: Task<Void, Never>?
    @State private var loadError: String?
    @State private var showDeleteConfirmation = false
    @State private var itemToDelete: HistoryListItem?
    @State private var actionAlert: HistoryActionAlert?
    @State private var savedVoiceSheetConfiguration: SavedVoiceSheetConfiguration?
    @State private var pendingReloadAfterCurrentLoad = false
    @State private var filteredItems: [HistoryListItem] = []
    /// Cached grouped list (W1-D). This used to be a computed property that
    /// rebuilt the whole dictionary + per-project segment sorts on EVERY
    /// body evaluation — the single worst measured surface in the 2026-08
    /// UI review (312 ms/s hitch, 2.9 s scroll stalls). It now recomputes
    /// only when its actual inputs change: `filteredItems`, the search
    /// activity flag, and `expandedProjects`.
    @State private var displayEntries: [HistoryDisplayEntry] = []
    @State private var expandedProjects: Set<String> = []
    @State private var itemsRevision = 0
    @State private var searchDebounceTask: Task<Void, Never>?
    @State private var databaseUnavailable = false
    @State private var recoverySnapshot: GenerationHistoryRecoverySnapshot = .empty
    @State private var recoveryAudioURLs: [URL] = []

    var body: some View {
        VStack(spacing: 0) {
            if recoverySnapshot.needsAttention {
                historyRecoveryBanner
            }
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
            .onChange(of: expandedProjects) { _, _ in recomputeDisplayEntries() }
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
                // Defer the binding reset — writing the parent's state back
                // to nil synchronously inside this view's update can drop
                // the whole change.
                Task { @MainActor in clearRequest = nil }
                guard !databaseUnavailable else {
                    presentActionAlert(
                        title: "History Unavailable",
                        message: "Retry loading History before deleting any entries. Your existing database was preserved."
                    )
                    return
                }
                guard !items.isEmpty else {
                    presentActionAlert(title: "History Is Empty", message: "There are no history entries to clear.")
                    return
                }
                switch request.scope {
                case .keepFiles:
                    actionAlert = HistoryActionAlert(
                        title: "Clear History?",
                        message: "This removes all \(items.count) history entries. The generated audio files stay on disk in your outputs folder.",
                        confirmTitle: "Clear History",
                        onConfirm: { performClearAll(deleteAudio: false) }
                    )
                case .deleteFiles:
                    actionAlert = HistoryActionAlert(
                        title: "Clear History and Delete Audio?",
                        message: "This permanently deletes all \(items.count) history entries and their audio files.",
                        confirmTitle: "Delete Everything",
                        onConfirm: { performClearAll(deleteAudio: true) }
                    )
                }
            }
            .alert("Delete Generation?", isPresented: $showDeleteConfirmation) {
                Button("Cancel", role: .cancel) {
                    itemToDelete = nil
                }
                Button("Delete", role: .destructive) {
                    if let item = itemToDelete {
                        confirmDelete(item)
                    }
                    itemToDelete = nil
                }
            } message: {
                Text("This will permanently delete the generation and its audio file.")
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
                        dismissButton: .default(Text("OK"))
                    )
                }
            }
            .sheet(item: $savedVoiceSheetConfiguration) { configuration in
                SavedVoiceSheet(configuration: configuration) { voice in
                    handleSavedVoice(voice)
                }
                .environment(ttsEngineStore)
            }
    }

    @ViewBuilder
    private var content: some View {
        if let loadError, items.isEmpty, !isLoading {
            historyStateContainer(identifier: "history_errorState") {
                VStack(spacing: 12) {
                    ContentUnavailableView(
                        "Couldn't load history",
                        systemImage: "exclamationmark.triangle",
                        description: Text(loadError)
                    )
                    Button("Retry") {
                        reloadHistory(reopenFailedStore: true)
                    }
                    .accessibilityIdentifier("historyRetryButton")
                }
            }
        } else if isLoading && items.isEmpty {
            historyStateContainer(identifier: "history_loadingState") {
                VStack(spacing: 12) {
                    ProgressView("Loading history...")
                }
            }
        } else if filteredItems.isEmpty {
            historyStateContainer(identifier: "history_emptyState") {
                ContentUnavailableView(
                    items.isEmpty ? "No generations yet" : "No results found",
                    systemImage: "clock.arrow.circlepath",
                    description: Text(
                        items.isEmpty
                        ? "Generate some audio to see it here."
                        : "Try a different search term or clear the search."
                    )
                )
            }
        } else {
            List(displayEntries) { entry in
                let item = entry.item
                VStack(alignment: .leading, spacing: 0) {
                HistoryRow(
                    item: item,
                    onPlay: {
                        audioPlayer.playFile(item.generation.audioPath, title: item.textPreview)
                    },
                    onSaveToSavedVoices: item.saveVoiceConfiguration.map { configuration in
                        {
                            savedVoiceSheetConfiguration = configuration
                        }
                    },
                    onSaveAs: {
                        exportGeneration(item)
                    },
                    allowsDeletion: !databaseUnavailable,
                    onDelete: {
                        itemToDelete = item
                        showDeleteConfirmation = true
                    }
                )
                .contextMenu {
                    Button {
                        NSWorkspace.shared.selectFile(item.generation.audioPath, inFileViewerRootedAtPath: "")
                    } label: {
                        Label("Reveal in Finder", systemImage: "folder")
                    }
                    .disabled(!item.audioFileExists)

                    if let onPinSeed, let seedValue = item.generation.samplingSeed {
                        Button {
                            onPinSeed(item.generation)
                        } label: {
                            Label("Pin seed \(String(seedValue)) for new takes", systemImage: "pin")
                        }
                        .accessibilityIdentifier("history_pinSeedButton")
                    }
                }
                if let toggle = entry.projectToggle, toggle.segmentCount > 0 {
                        HStack {
                            Button {
                                if expandedProjects.contains(toggle.projectID) {
                                    expandedProjects.remove(toggle.projectID)
                                } else {
                                    expandedProjects.insert(toggle.projectID)
                                }
                            } label: {
                                Label(
                                    expandedProjects.contains(toggle.projectID)
                                        ? "Hide \(toggle.segmentCount) segments"
                                        : "Show \(toggle.segmentCount) segments",
                                    systemImage: expandedProjects.contains(toggle.projectID)
                                        ? "chevron.down"
                                        : "chevron.right"
                                )
                                .font(.caption)
                            }
                            .buttonStyle(.borderless)
                            .accessibilityIdentifier(
                                "history_longFormSegmentsToggle_\(String(toggle.projectID.prefix(8)))"
                            )
                            Spacer()
                        }
                        .padding(.top, 2)
                }
                }
                .padding(.leading, entry.isSegment ? 24 : 0)
                .listRowInsets(EdgeInsets(top: 4, leading: 0, bottom: 4, trailing: 0))
            }
            .listStyle(.inset)
            .scrollContentBackground(.hidden)
            // Match the generation screens' content column: uncapped rows
            // tear apart on wide displays (title far left, actions far
            // right on a 43" panel).
            .frame(maxWidth: LayoutConstants.contentMaxWidth)
            .frame(maxWidth: .infinity)
        }
    }

    private var historyRecoveryBanner: some View {
        HStack(spacing: 12) {
            Image(systemName: "arrow.clockwise.icloud")
                .foregroundStyle(.orange)
            VStack(alignment: .leading, spacing: 2) {
                Text("Finished audio is waiting for History")
                    .font(.headline)
                Text(recoveryMessage)
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            Spacer(minLength: 8)
            Button("Retry") { reloadHistory(reopenFailedStore: true) }
                .accessibilityIdentifier("historyRecovery_retry")
            Button("Reveal Audio") { NSWorkspace.shared.open(AppPaths.outputsDir) }
                .disabled(recoverySnapshot.availableAudioCount == 0)
                .accessibilityIdentifier("historyRecovery_reveal")
            Button("Export Audio…") { exportPendingAudio() }
                .disabled(recoveryAudioURLs.isEmpty)
                .accessibilityIdentifier("historyRecovery_export")
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 10)
        .background(.orange.opacity(0.10))
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("historyRecovery_banner")
    }

    private var recoveryMessage: String {
        if recoverySnapshot.unqueuedCount > 0 {
            return VocelloPresentationText.historyUnqueuedDetail
        }
        if recoverySnapshot.issueCount > 0 {
            return "Vocello preserved the recovery record but could not verify or commit it. Retry before clearing History."
        }
        let count = recoverySnapshot.pendingCount
        return "\(count) take\(count == 1 ? "" : "s") remain safely queued. You can retry, reveal, or export the audio."
    }

}

private extension HistoryView {
    func handleAppear() {
        reloadHistory()
        refreshRecoveryState()
    }

    /// Append-in-place handler for the new `generationAppended` publisher.
    /// Avoids the full SQLite re-fetch that the previous
    /// `generationSaved` (Void) handler did. The HistoryListItem
    /// constructor still does a `FileManager.fileExists` check, but
    /// only once per appended generation — not once per existing row.
    func handleGenerationAppended(_ generation: Generation) {
        if generation.longFormRole == "joined" {
            // Project acceptance atomically adds segments and replaces the old
            // joined row. An append-only update would leave stale accepted rows
            // visible and omit the new segment children.
            reloadHistory()
            return
        }
        databaseUnavailable = false
        if let existingIndex = items.firstIndex(where: { $0.generation.id == generation.id && generation.id != nil }) {
            items[existingIndex] = HistoryListItem(generation: generation)
        } else {
            items.append(HistoryListItem(generation: generation))
        }
        itemsRevision &+= 1
        HistorySessionCache.generations = items.map(\.generation)
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
            title: "Saved Voice Added",
            message: "\"\(voice.name)\" is ready in Saved Voices."
        )
    }

    func recomputeFilteredItems() {
        let query = searchText.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        var result = query.isEmpty ? items : items.filter { $0.searchKey.contains(query) }

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
        recomputeDisplayEntries()
    }

    func recomputeDisplayEntries() {
        displayEntries = HistoryDisplayEntry.entries(
            from: filteredItems,
            searchActive: !searchText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
            expandedProjects: expandedProjects
        )
    }

    @ViewBuilder
    func historyStateContainer<Content: View>(
        identifier: String,
        @ViewBuilder content: () -> Content
    ) -> some View {
        VStack {
            content()
        }
        .padding(24)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
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
                    return generations.map(HistoryListItem.init)
                }.value

                guard !Task.isCancelled else { return }
                await MainActor.run {
                    items = loadedItems
                    itemsRevision &+= 1
                    HistorySessionCache.generations = loadedItems.map(\.generation)
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
                            title: "Couldn't refresh history",
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
            print("[Performance][HistoryView] reload_wall_ms=\(elapsedMs)")
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

    func exportGeneration(_ item: HistoryListItem) {
        let panel = NSSavePanel()
        panel.nameFieldStringValue = URL(fileURLWithPath: item.generation.audioPath).lastPathComponent
        panel.allowedContentTypes = [.wav]
        panel.canCreateDirectories = true
        if panel.runModal() == .OK, let url = panel.url {
            let sourceURL = URL(fileURLWithPath: item.generation.audioPath)
            let fileManager = FileManager.default
            do {
                // NSSavePanel only stages the destination URL after the
                // user confirms the overwrite prompt; it doesn't remove
                // the existing file. `copyItem` then throws
                // `NSFileWriteFileExistsError` on overwrite. Remove the
                // pre-existing destination first so confirmed overwrites
                // succeed. We can't use `replaceItemAt` here because
                // that moves the source onto the destination — the
                // history file must remain in place.
                if fileManager.fileExists(atPath: url.path) {
                    try fileManager.removeItem(at: url)
                }
                try fileManager.copyItem(at: sourceURL, to: url)
            } catch {
                presentActionAlert(
                    title: "Export Error",
                    message: "The file could not be exported: \(error.localizedDescription) Choose another destination and try again."
                )
            }
        }
    }

    func exportPendingAudio() {
        guard !recoveryAudioURLs.isEmpty else { return }
        let panel = NSOpenPanel()
        panel.canChooseDirectories = true
        panel.canChooseFiles = false
        panel.canCreateDirectories = true
        panel.allowsMultipleSelection = false
        panel.prompt = "Export"
        guard panel.runModal() == .OK, let destination = panel.url else { return }

        var failures = 0
        for source in recoveryAudioURLs {
            var target = destination.appendingPathComponent(source.lastPathComponent)
            if FileManager.default.fileExists(atPath: target.path) {
                target = destination.appendingPathComponent(
                    "\(source.deletingPathExtension().lastPathComponent)-\(UUID().uuidString.prefix(8)).wav"
                )
            }
            do {
                try FileManager.default.copyItem(at: source, to: target)
            } catch {
                failures += 1
            }
        }
        if failures > 0 {
            presentActionAlert(
                title: "Export Warning",
                message: "\(failures) pending audio file\(failures == 1 ? "" : "s") could not be exported."
            )
        }
    }

    func refreshRecoveryState() {
        Task {
            let snapshot = await GenerationHistoryRecovery.snapshot()
            let urls = await GenerationHistoryRecovery.pendingAudioURLs()
            guard !Task.isCancelled else { return }
            recoverySnapshot = snapshot
            recoveryAudioURLs = urls
        }
    }

    func confirmDelete(_ item: HistoryListItem) {
        switch deleteItem(item) {
        case .deleted:
            break
        case .databaseFailure(let message):
            presentActionAlert(
                title: "Delete Error",
                message: "The generation could not be removed from History: \(message) Try again after closing anything using the file."
            )
        case .audioCleanupFailure(let message):
            presentActionAlert(
                title: "Delete Warning",
                message: "Generation removed from history, but the audio file could not be deleted: \(message)"
            )
        }
    }

    func deleteItem(_ item: HistoryListItem) -> HistoryDeletionEngine.SingleOutcome {
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
        HistorySessionCache.generations.removeAll { generation in
            guard let generationID = generation.id, let itemID = item.generation.id else {
                return generation.audioPath == item.generation.audioPath
            }
            return generationID == itemID
        }
        return outcome
    }

    /// Clears the whole history. With `deleteAudio` false (GitHub #48), only
    /// the database rows and session cache go — the WAVs stay on disk. The
    /// durable clear transaction captures database and pending-outbox paths,
    /// deletes database rows first, then clears recovery entries and files.
    /// The work runs off the main thread; state updates hop back to MainActor.
    func performClearAll(deleteAudio: Bool) {
        Task { @concurrent in
            let outcome: GenerationHistoryClearOutcome
            do {
                outcome = try await GenerationHistoryRecovery.clearAll(deleteAudio: deleteAudio)
            } catch {
                await MainActor.run {
                    databaseUnavailable = true
                    presentActionAlert(
                        title: "Clear History Error",
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
                HistorySessionCache.generations = []

                if failures > 0 {
                    presentActionAlert(
                        title: "Clear History Warning",
                        message: "History cleared, but \(failures) audio file\(failures == 1 ? "" : "s") could not be deleted."
                    )
                }
                NotificationCenter.default.post(name: .generationHistoryRecoveryChanged, object: nil)
            }
        }
    }

    func presentActionAlert(title: String, message: String) {
        actionAlert = HistoryActionAlert(title: title, message: message)
    }
}

private struct HistoryRowMetadata: View {
    let mode: String
    let voice: String?
    let formattedDate: String
    let modeColor: Color

    var body: some View {
        HStack(spacing: 8) {
            Text(mode.capitalized)
                .font(.caption.weight(.semibold))
                .padding(.horizontal, 7)
                .padding(.vertical, 3)
                #if QW_UI_LIQUID
                .glassBadge(tint: modeColor)
                #else
                .background(
                    Capsule()
                        .fill(modeColor.opacity(0.15))
                )
                #endif

            if let voice, !voice.isEmpty {
                Text(voice)
                    .font(.callout)
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
            }

            Text(formattedDate)
                .font(.callout)
                .foregroundStyle(.secondary)
        }
    }
}

private struct HistoryRowActions: View {
    let audioFileExists: Bool
    let onSaveToSavedVoices: (() -> Void)?
    let onSaveAs: () -> Void
    let allowsDeletion: Bool
    let onDelete: () -> Void
    let itemID: String

    var body: some View {
        ControlGroup {
            if let onSaveToSavedVoices {
                Button(action: onSaveToSavedVoices) {
                    Image(systemName: "person.crop.circle.badge.plus")
                }
                .buttonStyle(.bordered)
                .controlSize(.small)
                .disabled(!audioFileExists)
                .accessibilityLabel("Save to Saved Voices")
                .accessibilityIdentifier("historyRow_saveVoice_\(itemID)")
            }

            Button(action: onSaveAs) {
                Image(systemName: "square.and.arrow.down")
            }
            .buttonStyle(.bordered)
            .controlSize(.small)
            .disabled(!audioFileExists)
            .accessibilityIdentifier("historyRow_saveAs_\(itemID)")

            Button(role: .destructive, action: onDelete) {
                Image(systemName: "trash")
            }
            .buttonStyle(.bordered)
            .controlSize(.small)
            .disabled(!allowsDeletion)
            .help(allowsDeletion ? "Delete generation" : "Reload History before deleting entries")
            .accessibilityIdentifier("historyRow_delete_\(itemID)")
        }
    }
}

private struct HistoryRow: View {
    let item: HistoryListItem
    let onPlay: () -> Void
    let onSaveToSavedVoices: (() -> Void)?
    let onSaveAs: () -> Void
    let allowsDeletion: Bool
    let onDelete: () -> Void

    @State private var isHovered = false

    private var modeColor: Color {
        AppTheme.modeColor(for: item.generation.mode)
    }

    var body: some View {
        HStack(alignment: .center, spacing: 12) {
            Button(action: onPlay) {
                Label(
                    item.audioFileExists ? "Play" : "Audio unavailable",
                    systemImage: item.audioFileExists ? "play.fill" : "exclamationmark.triangle.fill"
                )
            }
            .labelStyle(.iconOnly)
            .buttonStyle(.bordered)
            .controlSize(.small)
            .disabled(!item.audioFileExists)
            .accessibilityLabel(item.audioFileExists ? "Play generation" : "Audio unavailable")
            .accessibilityIdentifier("historyRow_play_\(item.id)")
            .accessibilityRepresentation {
                Button(item.audioFileExists ? "Play generation" : "Audio unavailable", action: onPlay)
                    .disabled(!item.audioFileExists)
                    .accessibilityIdentifier("historyRow_play_\(item.id)")
            }

            VStack(alignment: .leading, spacing: 6) {
                Text(item.textPreview)
                    .font(.body.weight(.semibold))
                    .lineLimit(1)

                HistoryRowMetadata(
                    mode: item.generation.mode,
                    voice: item.generation.voice,
                    formattedDate: item.formattedDate,
                    modeColor: modeColor
                )
            }

            Spacer()

            Text(durationText)
                .font(.footnote.monospacedDigit())
                .foregroundStyle(.secondary)

            HistoryRowActions(
                audioFileExists: item.audioFileExists,
                onSaveToSavedVoices: onSaveToSavedVoices,
                onSaveAs: onSaveAs,
                allowsDeletion: allowsDeletion,
                onDelete: onDelete,
                itemID: item.id
            )
        }
        .padding(.vertical, 6)
        .padding(.horizontal, 6)
        // Audit Batch 8: subtle border-tint on hover signals "this row
        // is content-bearing." No background fill, no motion — just an
        // edge so the user knows the row is part of the interactive
        // chrome. The play / save / delete buttons remain the actual
        // affordances.
        .background(
            RoundedRectangle(cornerRadius: 8, style: .continuous)
                .stroke(
                    isHovered ? AppTheme.cardStroke.opacity(0.3) : .clear,
                    lineWidth: 1.0
                )
        )
        .contentShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
        .onHover { hovering in
            isHovered = hovering
        }
        .appAnimation(.easeOut(duration: 0.12), value: isHovered)
        .accessibilityIdentifier("historyRow_\(item.id)")
        .accessibilityElement(children: .contain)
    }

    private var durationText: String {
        if let duration = item.generation.duration, duration > 0 {
            return String(format: "%.1fs", duration)
        }
        return "–"
    }
}
