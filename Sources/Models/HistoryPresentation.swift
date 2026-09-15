import Foundation
import QwenVoiceCore
import SwiftUI

/// Window-toolbar sort order of the History screen (desktop-only; iOS keeps
/// newest first). The rawValue is an internal identity.
enum HistorySortOrder: String, CaseIterable, Identifiable {
    case newest
    case oldest
    case longestDuration
    case shortestDuration
    case mode

    var id: String { rawValue }

    var label: String {
        switch self {
        case .newest: MacInterfaceText.historySortNewest
        case .oldest: MacInterfaceText.historySortOldest
        case .longestDuration: MacInterfaceText.historySortLongest
        case .shortestDuration: MacInterfaceText.historySortShortest
        case .mode: MacInterfaceText.historySortMode
        }
    }

    /// Date buckets read naturally only in chronological order; the other
    /// sorts render one flat section.
    var groupsByDate: Bool {
        self == .newest
    }
}

/// Toolbar-to-screen bridge for the clear-history actions (mirrors the Saved
/// Voices enroll request): the window toolbar bumps the request, the screen
/// confirms and performs it. `keepFiles` answers GitHub #48: purge the list
/// without touching the generated audio on disk.
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

/// The iOS History mode filter on the desktop: one chip per generation mode
/// plus "All". Color pairs with the label, never alone.
enum HistoryModeFilter: String, CaseIterable, Identifiable {
    case all
    case custom
    case design
    case clone

    var id: String { rawValue }

    var generationMode: GenerationMode? {
        switch self {
        case .all: nil
        case .custom: .custom
        case .design: .design
        case .clone: .clone
        }
    }

    var title: String {
        generationMode.map(MacInterfaceText.modeName) ?? MacInterfaceText.historyFilterAll
    }

    var tint: Color {
        generationMode.map(MacTheme.Brand.modeColor) ?? MacTheme.historyTint
    }

    var dotColor: Color {
        generationMode == nil ? Color.white.opacity(0.40) : tint
    }

    var accessibilityID: String { "history_modeFilter_\(rawValue)" }

    func matches(mode: String) -> Bool {
        guard let generationMode else { return true }
        return mode.lowercased() == generationMode.rawValue
    }
}

/// The iOS History date buckets.
enum HistoryDateBucket: Int, CaseIterable, Identifiable {
    case today
    case yesterday
    case previous7
    case previous30
    case earlier

    var id: Int { rawValue }

    var title: String {
        switch self {
        case .today: MacInterfaceText.historyBucketToday
        case .yesterday: MacInterfaceText.historyBucketYesterday
        case .previous7: MacInterfaceText.historyBucketPrevious7
        case .previous30: MacInterfaceText.historyBucketPrevious30
        case .earlier: MacInterfaceText.historyBucketEarlier
        }
    }

    static func bucket(for date: Date, reference: Date = Date(), calendar: Calendar = .current) -> HistoryDateBucket {
        if calendar.isDateInToday(date) { return .today }
        if calendar.isDateInYesterday(date) { return .yesterday }
        guard let days = calendar.dateComponents(
            [.day],
            from: calendar.startOfDay(for: date),
            to: calendar.startOfDay(for: reference)
        ).day else {
            return .earlier
        }
        if days <= 7 { return .previous7 }
        if days <= 30 { return .previous30 }
        return .earlier
    }
}
