import SwiftUI
import QwenVoiceCore

/// Top-level History tab entry point. Reads/writes `AppModel` directly
/// so RootView doesn't need binding plumbing.
///
/// Mirrors `design_references/Vocello iOS/screens.jsx` History section:
/// date-bucketed rows with mini-waveform thumbnails, search field, mode
/// filter chips, and a three-dot menu (Play / Save audio / Delete) on
/// each row. Tap on the row body presents the full-screen Player sheet
/// via the `\.presentIOSPlayerSheet` environment closure.
///
/// Phase 6: this screen owns the History body directly. The legacy
/// `IOSLibraryContainerView` indirection (which also carried a dead
/// Voices section — the Voices tab has been `IOSVoicesView` since the
/// 4-tab IA landed) is gone.
/// One visible row in the History list: an ordinary take, or a long-form
/// project (its joined output plus the collapsed per-segment map).
enum IOSHistoryEntry: Identifiable {
    case single(Generation)
    case project(joined: Generation, segments: [Generation])

    var id: String {
        switch self {
        case .single(let item):
            return "single-\(item.historyAccessibilityID)"
        case .project(let joined, _):
            return "project-\(joined.longFormProjectID ?? joined.historyAccessibilityID)"
        }
    }

    /// Date used for bucket placement; a project sits where its joined output landed.
    var anchorDate: Date {
        switch self {
        case .single(let item):
            return item.createdAt
        case .project(let joined, _):
            return joined.createdAt
        }
    }
}

struct HistoryScreen: View {
    @Environment(AppModel.self) private var appModel

    var body: some View {
        @Bindable var appModel = appModel

        IOSStudioShellScreen(
            selectedTab: $appModel.tab,
            activeTab: .history,
            tint: IOSAppTab.history.dockAccent(studioMode: .custom)
        ) {
            VStack(alignment: .leading, spacing: 14) {
                IOSHistoryLibrarySection()
                    .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        }
    }
}

private struct IOSHistoryFilterChips: View {
    @Binding var selection: IOSHistoryModeFilter

    var body: some View {
        IOSFilterChipRow(
            options: IOSHistoryModeFilter.allCases,
            selection: $selection,
            tint: IOSBrandTheme.library,
            label: \.title,
            leading: { filter in
                AnyView(IOSModeDot(tint: filter.dotColor, diameter: 7))
            },
            accessibilityIdentifier: { "historyModeFilter_\($0.rawValue)" }
        )
        .accessibilityIdentifier("historyModeFilter")
    }
}

enum IOSHistoryModeFilter: String, CaseIterable, Identifiable, Hashable {
    case all
    case custom
    case design
    case clone

    var id: String { rawValue }

    var title: String {
        switch self {
        case .all: return "All"
        case .custom: return "Custom"
        case .design: return "Design"
        case .clone: return "Clone"
        }
    }

    var tint: Color {
        switch self {
        case .all: return IOSBrandTheme.library
        case .custom: return IOSBrandTheme.custom
        case .design: return IOSBrandTheme.design
        case .clone: return IOSBrandTheme.clone
        }
    }

    var dotColor: Color {
        switch self {
        case .all: return Color.white.opacity(0.40)
        case .custom, .design, .clone: return tint
        }
    }

    func matches(_ item: Generation) -> Bool {
        switch self {
        case .all: return true
        case .custom: return item.mode.lowercased() == "custom"
        case .design: return item.mode.lowercased() == "design"
        case .clone: return item.mode.lowercased() == "clone"
        }
    }
}

private enum IOSHistoryBucket: Int, CaseIterable, Identifiable {
    case today
    case yesterday
    case previous7
    case previous30
    case earlier

    var id: Int { rawValue }

    var title: String {
        switch self {
        case .today: return "Today"
        case .yesterday: return "Yesterday"
        case .previous7: return "Previous 7 Days"
        case .previous30: return "Previous 30 Days"
        case .earlier: return "Earlier"
        }
    }

    static func bucket(for date: Date, reference: Date = Date(), calendar: Calendar = .current) -> IOSHistoryBucket {
        if calendar.isDateInToday(date) { return .today }
        if calendar.isDateInYesterday(date) { return .yesterday }
        guard let days = calendar.dateComponents([.day], from: calendar.startOfDay(for: date), to: calendar.startOfDay(for: reference)).day else {
            return .earlier
        }
        if days <= 7 { return .previous7 }
        if days <= 30 { return .previous30 }
        return .earlier
    }
}

/// Identifiable wrapper driving the clear-history confirmation alert.
/// `keepFiles` answers GitHub #48 — purge the list, keep the audio on disk.
private struct IOSHistoryClearConfirmation: Identifiable {
    let deleteAudio: Bool
    var id: String { deleteAudio ? "deleteFiles" : "keepFiles" }
}

private struct IOSHistoryLibrarySection: View {
    @Environment(AppModel.self) private var appModel
    @State private var items: [Generation] = []
    @State private var errorMessage: String?
    @State private var modeFilter: IOSHistoryModeFilter = .all
    @State private var searchQuery: String = ""
    @State private var debouncedQuery: String = ""
    @State private var groupedItems: [(bucket: IOSHistoryBucket, items: [IOSHistoryEntry])] = []
    @State private var filteredItemCount = 0
    /// Long-form projects whose per-segment map is disclosed (keyed by project ID).
    @State private var expandedProjects: Set<String> = []
    @State private var reloadTask: Task<Void, Never>?
    @State private var clearConfirmation: IOSHistoryClearConfirmation?
    @State private var databaseUnavailable = false

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack(spacing: 10) {
                IOSSearchField(text: $searchQuery, placeholder: "Search transcript or voice")
                    .accessibilityIdentifier("historySearchField")

                Menu {
                    Button("Clear History (Keep Audio Files)…") {
                        clearConfirmation = IOSHistoryClearConfirmation(deleteAudio: false)
                    }
                    .accessibilityIdentifier("historyClearKeepFiles")
                    Button("Clear History and Delete Audio…", role: .destructive) {
                        clearConfirmation = IOSHistoryClearConfirmation(deleteAudio: true)
                    }
                    .accessibilityIdentifier("historyClearDeleteFiles")
                } label: {
                    Image(systemName: "trash.circle")
                        .font(.system(size: 20, weight: .medium))
                        .foregroundStyle(items.isEmpty ? IOSAppTheme.textTertiary : IOSAppTheme.textSecondary)
                        .frame(width: 34, height: 34)
                }
                .disabled(items.isEmpty || databaseUnavailable)
                .accessibilityLabel("Clear history")
                .accessibilityIdentifier("historyClearMenu")
            }
            .padding(.horizontal, 20)
            .padding(.bottom, 10)

            IOSHistoryFilterChips(selection: $modeFilter)
                .padding(.bottom, 0)

            IOSScrollView {
                LazyVStack(alignment: .leading, spacing: 0) {
                    if errorMessage != nil, items.isEmpty {
                        IOSEmptyStateCard(
                            title: "Couldn't load history",
                            message: "Something went wrong reading your history. Pull to retry.",
                            symbolName: "exclamationmark.triangle",
                            tint: .orange
                        )
                        .padding(.horizontal, 20)
                        .padding(.top, 16)
                        Button("Retry") {
                            reload(reopenFailedStore: true)
                        }
                            .iosAdaptiveUtilityButtonStyle(tint: IOSBrandTheme.library)
                            .padding(.horizontal, 20)
                            .accessibilityIdentifier("historyRetryButton")
                    } else if items.isEmpty {
                        IOSEmptyStateCard(
                            title: "No takes yet",
                            message: "Generated audio shows up here once you create a voice or line.",
                            symbolName: "clock.arrow.circlepath",
                            tint: IOSBrandTheme.library
                        )
                        .padding(.horizontal, 20)
                        .padding(.top, 16)
                    } else if filteredItemCount == 0 {
                        IOSEmptyStateCard(
                            title: "No matches",
                            message: "Nothing matches this filter or search. Try widening it.",
                            symbolName: "line.3.horizontal.decrease.circle",
                            tint: IOSBrandTheme.library
                        )
                        .padding(.horizontal, 20)
                        .padding(.top, 16)
                        .accessibilityIdentifier("history_noMatchesState")
                    } else {
                        ForEach(groupedItems, id: \.bucket.id) { group in
                            IOSSectionHeading(group.bucket.title)
                            ForEach(group.items) { entry in
                                switch entry {
                                case .single(let item):
                                    historyCard(for: item)
                                case .project(let joined, let segments):
                                    historyCard(for: joined)
                                    longFormSegmentsDisclosure(joined: joined, segments: segments)
                                }
                            }
                        }
                    }
                }
                .padding(.bottom, 8)
            }
        }
        .onAppear { reload() }
        .onReceive(NotificationCenter.default.publisher(for: .generationSaved)) { _ in
            reload()
        }
        .onDisappear {
            reloadTask?.cancel()
            reloadTask = nil
        }
        .onChange(of: modeFilter) { _, _ in
            recomputePresentation()
        }
        .onChange(of: debouncedQuery) { _, _ in
            recomputePresentation()
        }
        .task(id: searchQuery) {
            try? await Task.sleep(for: .milliseconds(150))
            guard !Task.isCancelled else { return }
            debouncedQuery = searchQuery
        }
        .alert(item: $clearConfirmation) { confirmation in
            if confirmation.deleteAudio {
                Alert(
                    title: Text("Clear History and Delete Audio?"),
                    message: Text("This permanently deletes all \(items.count) history entries and their audio files."),
                    primaryButton: .destructive(Text("Delete Everything")) {
                        performClearAll(deleteAudio: true)
                    },
                    secondaryButton: .cancel()
                )
            } else {
                Alert(
                    title: Text("Clear History?"),
                    message: Text("This removes all \(items.count) history entries. The generated audio files stay on the device."),
                    primaryButton: .destructive(Text("Clear History")) {
                        performClearAll(deleteAudio: false)
                    },
                    secondaryButton: .cancel()
                )
            }
        }
    }

    /// Clears the whole history; with `deleteAudio` false the WAVs stay on
    /// disk (GitHub #48). The database is the source of truth for the file
    /// sweep so rows beyond the loaded list are covered too. The fetch +
    /// file sweep + delete run off the main thread (a large history's worth
    /// of synchronous removeItem calls would stall the UI — 2026-06-12
    /// release-QA audit); state updates hop back to the MainActor.
    private func performClearAll(deleteAudio: Bool) {
        Task.detached(priority: .userInitiated) {
            do {
                if deleteAudio {
                    let allGenerations = try DatabaseService.shared.fetchAllGenerations()
                    let fileManager = FileManager.default
                    for generation in allGenerations where fileManager.fileExists(atPath: generation.audioPath) {
                        try? fileManager.removeItem(atPath: generation.audioPath)
                    }
                }
                try DatabaseService.shared.deleteAllGenerations()
                await MainActor.run { reload() }
            } catch {
                let message = error.localizedDescription
                await MainActor.run {
                    databaseUnavailable = true
                    errorMessage = message
                }
            }
        }
    }

    private func reload(reopenFailedStore: Bool = false) {
        reloadTask?.cancel()
        reloadTask = Task {
            do {
                let loadedItems = try await Task.detached(priority: .userInitiated) {
                    if reopenFailedStore {
                        try DatabaseService.shared.reopenIfNeeded()
                    }
                    return try DatabaseService.shared.fetchAllGenerations()
                }.value
                guard !Task.isCancelled else { return }
                items = loadedItems
                databaseUnavailable = false
                errorMessage = nil
                recomputePresentation()
            } catch {
                guard !Task.isCancelled else { return }
                items = []
                groupedItems = []
                filteredItemCount = 0
                databaseUnavailable = true
                errorMessage = error.localizedDescription
            }
            reloadTask = nil
        }
    }

    private func recomputePresentation() {
        let grouped = Self.makeGroupedItems(
            items: items,
            modeFilter: modeFilter,
            query: debouncedQuery
        )
        groupedItems = grouped
        filteredItemCount = grouped.reduce(0) { $0 + $1.items.count }
    }

    private static func makeGroupedItems(
        items: [Generation],
        modeFilter: IOSHistoryModeFilter,
        query: String
    ) -> [(bucket: IOSHistoryBucket, items: [IOSHistoryEntry])] {
        let trimmed = query.trimmingCharacters(in: .whitespacesAndNewlines)
        let filteredItems = items.filter { item in
            guard modeFilter.matches(item) else { return false }
            guard !trimmed.isEmpty else { return true }
            if item.text.localizedCaseInsensitiveContains(trimmed) { return true }
            if let voice = item.voice, voice.localizedCaseInsensitiveContains(trimmed) { return true }
            if item.mode.localizedCaseInsensitiveContains(trimmed) { return true }
            return false
        }

        // Long-form grouping (mirrors macOS History semantics): a project's
        // joined row carries its segment map behind a disclosure; segments
        // whose project has a visible joined row collapse under it. Search
        // flattens everything, and orphan segments (no joined row yet) stay
        // visible as ordinary rows.
        var entries: [IOSHistoryEntry] = []
        if trimmed.isEmpty {
            let joinedProjectIDs = Set(
                filteredItems.compactMap { item -> String? in
                    guard item.longFormRole == "joined" else { return nil }
                    return item.longFormProjectID
                }
            )
            var segmentsByProject: [String: [Generation]] = [:]
            for item in filteredItems
            where item.longFormRole == "segment" && item.longFormProjectID.map(joinedProjectIDs.contains) == true {
                segmentsByProject[item.longFormProjectID!, default: []].append(item)
            }
            for item in filteredItems {
                if item.longFormRole == "joined", let projectID = item.longFormProjectID {
                    entries.append(
                        .project(
                            joined: item,
                            segments: (segmentsByProject[projectID] ?? [])
                                .sorted { $0.createdAt < $1.createdAt }
                        )
                    )
                } else if item.longFormRole == "segment",
                          let projectID = item.longFormProjectID,
                          joinedProjectIDs.contains(projectID) {
                    continue
                } else {
                    entries.append(.single(item))
                }
            }
        } else {
            entries = filteredItems.map(IOSHistoryEntry.single)
        }

        let reference = Date()
        let calendar = Calendar.current
        var map: [IOSHistoryBucket: [IOSHistoryEntry]] = [:]
        for entry in entries {
            let bucket = IOSHistoryBucket.bucket(
                for: entry.anchorDate,
                reference: reference,
                calendar: calendar
            )
            map[bucket, default: []].append(entry)
        }
        return IOSHistoryBucket.allCases.compactMap { bucket in
            guard let rows = map[bucket], !rows.isEmpty else { return nil }
            return (bucket, rows)
        }
    }

    @ViewBuilder
    private func historyCard(for item: Generation) -> some View {
        IOSHistoryItemCard(
            item: item,
            allowsDeletion: !databaseUnavailable,
            onDelete: { delete(item) },
            onPinSeed: item.samplingSeed.map { seedValue in
                { pinSeed(seedValue, mode: item.mode) }
            }
        )
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("historyRow_\(item.historyAccessibilityID)")
    }

    @ViewBuilder
    private func longFormSegmentsDisclosure(joined: Generation, segments: [Generation]) -> some View {
        if let projectID = joined.longFormProjectID, !segments.isEmpty {
            let digestPrefix = String(projectID.prefix(8))
            let isExpanded = expandedProjects.contains(projectID)
            Button {
                if isExpanded {
                    expandedProjects.remove(projectID)
                } else {
                    expandedProjects.insert(projectID)
                }
            } label: {
                HStack(spacing: 6) {
                    Image(systemName: "rectangle.stack")
                    Text("\(segments.count) segments")
                    Image(systemName: isExpanded ? "chevron.up" : "chevron.down")
                }
                .font(.footnote.weight(.medium))
                .foregroundStyle(IOSAppTheme.textSecondary)
            }
            .buttonStyle(.plain)
            .padding(.horizontal, 28)
            .accessibilityIdentifier("history_longFormSegmentsToggle_\(digestPrefix)")
            if isExpanded {
                ForEach(segments) { segment in
                    historyCard(for: segment)
                        .padding(.leading, 16)
                }
            }
        }
    }

    /// DP-15: pin the take's recorded seed into its mode's draft and land the
    /// user in that studio mode so the seed chip makes the state visible.
    private func pinSeed(_ seedValue: UInt64, mode: String) {
        switch mode.lowercased() {
        case GenerationMode.custom.rawValue:
            appModel.customVoiceDraft.pinnedSeed = seedValue
            appModel.studioMode = .custom
        case GenerationMode.design.rawValue:
            appModel.voiceDesignDraft.pinnedSeed = seedValue
            appModel.studioMode = .design
        case GenerationMode.clone.rawValue:
            appModel.voiceCloningDraft.pinnedSeed = seedValue
            appModel.studioMode = .clone
        default:
            return
        }
        IOSHaptics.selection()
        appModel.tab = .studio
    }

    private func delete(_ item: Generation) {
        do {
            if let id = item.id {
                try DatabaseService.shared.deleteGeneration(id: id)
            }
            if FileManager.default.fileExists(atPath: item.audioPath) {
                try? FileManager.default.removeItem(atPath: item.audioPath)
            }
            reload()
        } catch {
            databaseUnavailable = true
            errorMessage = error.localizedDescription
        }
    }
}

private struct IOSHistoryItemCard: View {
    let item: Generation
    let allowsDeletion: Bool
    let onDelete: () -> Void
    /// DP-15: pins this take's recorded sampling seed into its mode's draft.
    /// Nil (or a seedless pre-v6 row) hides the action.
    var onPinSeed: (() -> Void)? = nil

    @State private var isConfirmingDelete = false
    @Environment(\.presentIOSPlayerSheet) private var presentPlayerSheet

    private var modeText: String {
        switch item.mode.lowercased() {
        case "custom":
            return "Custom"
        case "design":
            return "Design"
        case "clone":
            return "Clone"
        default:
            return item.mode.capitalized
        }
    }

    private var modeTint: Color {
        switch item.mode.lowercased() {
        case "custom":
            return IOSBrandTheme.custom
        case "design":
            return IOSBrandTheme.design
        case "clone":
            return IOSBrandTheme.clone
        default:
            return IOSBrandTheme.library
        }
    }

    private var durationText: String? {
        guard let duration = item.duration else { return nil }
        return String(format: "%.1fs", duration)
    }

    private var thumbnailSeed: Int {
        // Deterministic waveform: same row renders the same bars across
        // launches. Use the database row id when present, fall back to a
        // stable hash of the audio path.
        if let id = item.id { return Int(truncatingIfNeeded: id) }
        return IOSStableVisualHash.int(item.audioPath)
    }

    var body: some View {
        HStack(alignment: .center, spacing: 12) {
            Button(action: openPlayerSheet) {
                HStack(alignment: .center, spacing: 12) {
                    ZStack {
                        RoundedRectangle(cornerRadius: 12, style: .continuous)
                            .fill(modeTint.opacity(0.14))
                            .background {
                                RoundedRectangle(cornerRadius: 12, style: .continuous)
                                    .fill(Color.white.opacity(0.02))
                            }
                            .frame(width: 48, height: 48)
                        IOSStaticWaveformThumbnail(
                            seed: thumbnailSeed,
                            barCount: 14,
                            tint: modeTint
                        )
                        .frame(width: 34, height: 22)
                    }

                    VStack(alignment: .leading, spacing: 2) {
                        Text(item.textPreview)
                            .iosScaledFont(size: 15, weight: .medium)
                            .tracking(-0.15)
                            .foregroundStyle(IOSAppTheme.textPrimary)
                            .lineLimit(2)
                            .fixedSize(horizontal: false, vertical: true)
                            .multilineTextAlignment(.leading)

                        HStack(spacing: 6) {
                            IOSModeDot(tint: modeTint)
                            if let voice = item.voice, !voice.isEmpty {
                                Text(voice)
                            } else {
                                Text(modeText)
                            }
                            Text("·")
                            Text(item.formattedDate)
                            if let durationText {
                                Text("·")
                                Text(durationText)
                                    .monospacedDigit()
                            }
                        }
                        .iosScaledFont(size: 12, relativeTo: .caption)
                        .foregroundStyle(IOSAppTheme.textSecondary)
                        .lineLimit(1)
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                }
            }
            .buttonStyle(.plain)
            .accessibilityIdentifier("historyRowTap_\(item.historyAccessibilityID)")

            Menu {
                Button {
                    openPlayerSheet()
                } label: {
                    Label("Play", systemImage: "play.fill")
                }
                if FileManager.default.fileExists(atPath: item.audioPath) {
                    ShareLink(item: URL(fileURLWithPath: item.audioPath)) {
                        Label("Save audio", systemImage: "square.and.arrow.down")
                    }
                }
                if let onPinSeed, let seedValue = item.samplingSeed {
                    Button {
                        onPinSeed()
                    } label: {
                        Label("Pin seed \(String(seedValue)) for new takes", systemImage: "pin")
                    }
                }
                Divider()
                Button("Delete", role: .destructive) {
                    isConfirmingDelete = true
                }
                .disabled(!allowsDeletion)
            } label: {
                Image(systemName: "ellipsis")
                    .font(.system(size: 16, weight: .semibold))
                    .foregroundStyle(IOSAppTheme.textPrimary)
                    .frame(width: 32, height: 32)
                    .background {
                        Circle().fill(Color.white.opacity(0.06))
                    }
                    .overlay {
                        Circle().stroke(Color.white.opacity(0.10), lineWidth: 0.5)
                    }
                    // 32pt visual, 44pt hit target (HIG minimum) — this menu is the
                    // only Play/Save/Delete path on the row.
                    .frame(width: 44, height: 44)
                    .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .accessibilityLabel("More actions")
            .accessibilityIdentifier("historyRowMenu_\(item.historyAccessibilityID)")
        }
        .padding(.horizontal, 20)
        .padding(.vertical, 10)
        .overlay(alignment: .bottom) {
            Rectangle()
                .fill(Color.white.opacity(0.06))
                .frame(height: 0.5)
                .padding(.leading, 76)
                .padding(.trailing, 20)
        }
        .confirmationDialog(
            "Delete this take?",
            isPresented: $isConfirmingDelete,
            titleVisibility: .visible
        ) {
            Button("Delete", role: .destructive) {
                guard allowsDeletion else { return }
                IOSHaptics.warning()
                onDelete()
            }
            .disabled(!allowsDeletion)
            .accessibilityIdentifier("historyRowDeleteConfirm_\(item.historyAccessibilityID)")
            Button("Cancel", role: .cancel) {}
        } message: {
            Text("This permanently removes the generated audio and its history entry.")
        }
    }

    private func openPlayerSheet() {
        let playerItem = IOSPlayerSheetItem.from(history: item)
        IOSHaptics.selection()
        presentPlayerSheet(playerItem)
    }

    private var historyMetadata: String {
        let parts = [modeText, durationText, item.formattedDate].compactMap { $0 }
        return parts.joined(separator: " • ")
    }
}
