import Foundation
import GRDB

/// One bounded History read (AUD-05). History grows without limit, so a
/// screen loads a page at a time instead of every row. The mode filter and
/// the search run in SQL over the whole table, so a page never hides a
/// matching row just because it was not loaded yet, and `hasMore` says the
/// archive holds more matches than the page.
struct GenerationHistoryPageRequest: Equatable, Sendable {
    /// Entries per page; each "Show More" asks for one more page.
    static let pageSize = 500

    enum Order: Equatable, Sendable {
        case newest
        case oldest
        case longest
        case shortest
        case mode
    }

    /// Each screen's own search predicate, so SQL and the list never disagree.
    enum SearchStyle: Equatable, Sendable {
        /// iPhone: transcript, voice or mode, `localizedCaseInsensitiveContains`.
        case transcriptVoiceOrMode
        /// Mac: the lowercased transcript and voice joined by a newline
        /// contain the lowercased query.
        case lowercasedTranscriptAndVoice
    }

    /// `Generation.mode` to keep, compared case-insensitively; nil keeps every mode.
    var mode: String?
    /// Empty keeps every row.
    var query: String
    var searchStyle: SearchStyle
    var order: Order
    /// Entries to return: a take, or a long-form project counted once.
    var limit: Int

    init(
        mode: String? = nil,
        query: String = "",
        searchStyle: SearchStyle = .transcriptVoiceOrMode,
        order: Order = .newest,
        limit: Int = GenerationHistoryPageRequest.pageSize
    ) {
        self.mode = mode
        self.query = query
        self.searchStyle = searchStyle
        self.order = order
        self.limit = limit
    }

    /// Neither a filter nor a search narrows the page.
    var isUnfiltered: Bool {
        mode == nil && query.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }

    /// The query as the screen matches it.
    var normalizedQuery: String {
        switch searchStyle {
        case .transcriptVoiceOrMode:
            return query.trimmingCharacters(in: .whitespacesAndNewlines)
        case .lowercasedTranscriptAndVoice:
            return query.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        }
    }
}

struct GenerationHistoryPage: Equatable, Sendable {
    static let empty = GenerationHistoryPage(rows: [], hasMore: false, archiveCount: 0)

    /// The page's entries in the requested order, then every segment of each
    /// long-form project whose joined row is on the page (oldest first), so a
    /// project is always complete. Screens group segments under their joined row.
    let rows: [Generation]
    /// More entries match beyond this page.
    let hasMore: Bool
    /// Every row History can show, before the filter and the search.
    let archiveCount: Int
}

enum GenerationHistoryPageQuery {
    /// `includesLongFormProjects` is false while a long-form journal needs
    /// recovery: project rows stay withheld, as `readableHistory` does.
    static func fetch(
        _ request: GenerationHistoryPageRequest,
        includesLongFormProjects: Bool,
        in db: Database
    ) throws -> GenerationHistoryPage {
        let query = request.normalizedQuery
        let mode = request.mode?.lowercased()
        let limit = max(1, request.limit)

        var conditions: [String] = []
        var arguments: [(any DatabaseValueConvertible)?] = []
        if !includesLongFormProjects {
            conditions.append(standaloneCondition)
        }
        if let mode {
            conditions.append("LOWER(mode) = ?")
            arguments.append(mode)
        }
        if query.isEmpty {
            // Without a search, a segment whose project has a joined row under
            // the same filter collapses under that row instead of paging on its
            // own; a search lists every match flat, as the lists do. `IS` keeps
            // standalone rows (NULL role) out of SQL's NULL logic.
            let joinedModeCondition = mode == nil ? "" : " AND LOWER(joined.mode) = ?"
            conditions.append(
                "NOT (longFormRole IS 'segment' AND longFormProjectID IS NOT NULL AND longFormProjectID IN ("
                    + "SELECT joined.longFormProjectID FROM generations AS joined "
                    + "WHERE joined.longFormRole IS 'joined' AND joined.longFormProjectID IS NOT NULL"
                    + joinedModeCondition + "))"
            )
            if let mode {
                arguments.append(mode)
            }
        } else {
            let function = matchFunction(for: request.searchStyle)
            db.add(function: function)
            conditions.append("\(function.name)(text, voice, mode, ?)")
            arguments.append(query)
        }
        arguments.append(limit + 1)
        let whereClause = conditions.isEmpty ? "" : "WHERE " + conditions.joined(separator: " AND ")
        var entries = try Generation.fetchAll(
            db,
            sql: "SELECT * FROM generations \(whereClause) ORDER BY \(orderClause(request.order)) LIMIT ?",
            arguments: StatementArguments(arguments)
        )
        let hasMore = entries.count > limit
        if hasMore {
            entries.removeLast(entries.count - limit)
        }

        var rows = entries
        if query.isEmpty {
            let projectIDs = Array(Set(entries.compactMap { entry in
                entry.longFormRole == "joined" ? entry.longFormProjectID : nil
            })).sorted()
            if !projectIDs.isEmpty {
                var segmentArguments: [(any DatabaseValueConvertible)?] = projectIDs.map { $0 }
                var modeCondition = ""
                if let mode {
                    modeCondition = " AND LOWER(mode) = ?"
                    segmentArguments.append(mode)
                }
                let segments = try Generation.fetchAll(
                    db,
                    sql: """
                        SELECT * FROM generations
                        WHERE longFormRole IS 'segment'
                        AND longFormProjectID IN (\(databaseQuestionMarks(count: projectIDs.count)))\(modeCondition)
                        ORDER BY createdAt ASC, id ASC
                        """,
                    arguments: StatementArguments(segmentArguments)
                )
                rows += segments
            }
        }

        let archiveCount = try Int.fetchOne(
            db,
            sql: "SELECT COUNT(*) FROM generations" + (includesLongFormProjects ? "" : " WHERE \(standaloneCondition)")
        ) ?? 0
        return GenerationHistoryPage(rows: rows, hasMore: hasMore, archiveCount: archiveCount)
    }

    /// The iPhone list's predicate (`HistoryScreen`), shared with SQL.
    static func matchesTranscriptVoiceOrMode(text: String, voice: String?, mode: String, query: String) -> Bool {
        guard !query.isEmpty else { return true }
        if text.localizedCaseInsensitiveContains(query) { return true }
        if let voice, voice.localizedCaseInsensitiveContains(query) { return true }
        return mode.localizedCaseInsensitiveContains(query)
    }

    /// The Mac list's predicate (`MacHistoryListItem.searchKey`), shared with SQL.
    static func lowercasedSearchKey(text: String, voice: String?) -> String {
        "\(text)\n\(voice ?? "")".lowercased()
    }

    private static let standaloneCondition = "longFormProjectID IS NULL AND longFormRole IS NULL"

    /// A tie never reorders rows between two reads of the same page.
    private static func orderClause(_ order: GenerationHistoryPageRequest.Order) -> String {
        switch order {
        case .newest: return "createdAt DESC, id DESC"
        case .oldest: return "createdAt ASC, id ASC"
        case .longest: return "IFNULL(duration, 0) DESC, createdAt DESC, id DESC"
        case .shortest: return "IFNULL(duration, 0) ASC, createdAt DESC, id DESC"
        case .mode: return "mode ASC, createdAt DESC, id DESC"
        }
    }

    private static func matchFunction(for style: GenerationHistoryPageRequest.SearchStyle) -> DatabaseFunction {
        switch style {
        case .transcriptVoiceOrMode: return transcriptVoiceOrModeFunction
        case .lowercasedTranscriptAndVoice: return lowercasedTranscriptAndVoiceFunction
        }
    }

    private static let transcriptVoiceOrModeFunction = DatabaseFunction(
        "vocello_history_matches_list",
        argumentCount: 4
    ) { values in
        GenerationHistoryPageQuery.matchesTranscriptVoiceOrMode(
            text: String.fromDatabaseValue(values[0]) ?? "",
            voice: String.fromDatabaseValue(values[1]),
            mode: String.fromDatabaseValue(values[2]) ?? "",
            query: String.fromDatabaseValue(values[3]) ?? ""
        )
    }

    private static let lowercasedTranscriptAndVoiceFunction = DatabaseFunction(
        "vocello_history_matches_mac",
        argumentCount: 4
    ) { values in
        let query = String.fromDatabaseValue(values[3]) ?? ""
        guard !query.isEmpty else { return true }
        return GenerationHistoryPageQuery.lowercasedSearchKey(
            text: String.fromDatabaseValue(values[0]) ?? "",
            voice: String.fromDatabaseValue(values[1])
        ).contains(query)
    }
}
