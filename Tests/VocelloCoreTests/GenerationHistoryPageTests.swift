import Foundation
import GRDB
import XCTest

/// AUD-05: History reads a bounded page at a time, and the mode filter and the
/// search still reach every row of the archive.
final class GenerationHistoryPageTests: XCTestCase {
    func testPagesAreBoundedAndTheNextPageReachesTheRestOfTheArchive() throws {
        let queue = try makeQueue()
        try insert((0..<7).map { row("take \($0)", at: Double($0)) }, into: queue)

        let first = try page(GenerationHistoryPageRequest(limit: 3), in: queue)
        XCTAssertEqual(first.rows.map(\.text), ["take 6", "take 5", "take 4"])
        XCTAssertTrue(first.hasMore)
        XCTAssertEqual(first.archiveCount, 7)

        let second = try page(GenerationHistoryPageRequest(limit: 6), in: queue)
        XCTAssertEqual(second.rows.count, 6)
        XCTAssertTrue(second.hasMore)

        let complete = try page(GenerationHistoryPageRequest(limit: 7), in: queue)
        XCTAssertEqual(complete.rows.map(\.text), (0..<7).reversed().map { "take \($0)" })
        XCTAssertFalse(complete.hasMore)
    }

    func testSearchAndFilterReachRowsBeyondTheLoadedPage() throws {
        let queue = try makeQueue()
        var rows = (1...9).map { row("recent take \($0)", at: Double($0)) }
        rows.append(row("Oldest ÉTÉ line", mode: "clone", voice: "Narrator", at: 0))
        try insert(rows, into: queue)

        XCTAssertFalse(
            try page(GenerationHistoryPageRequest(limit: 2), in: queue).rows.contains { $0.text.hasPrefix("Oldest") },
            "The oldest row is beyond the first page"
        )
        // Unicode case folding, as the list's localizedCaseInsensitiveContains.
        let search = try page(GenerationHistoryPageRequest(query: "  été ", limit: 2), in: queue)
        XCTAssertEqual(search.rows.map(\.text), ["Oldest ÉTÉ line"])
        XCTAssertFalse(search.hasMore)
        XCTAssertEqual(search.archiveCount, 10, "The archive count ignores the search")

        XCTAssertEqual(try page(GenerationHistoryPageRequest(query: "narr", limit: 2), in: queue).rows.count, 1)
        XCTAssertEqual(
            try page(GenerationHistoryPageRequest(query: "CLONE", limit: 2), in: queue).rows.map(\.mode),
            ["clone"],
            "Search matches the mode, as the list does"
        )
        let filtered = try page(GenerationHistoryPageRequest(mode: "Clone", limit: 2), in: queue)
        XCTAssertEqual(filtered.rows.map(\.text), ["Oldest ÉTÉ line"])
        XCTAssertFalse(filtered.hasMore)
        XCTAssertTrue(try page(GenerationHistoryPageRequest(mode: "design"), in: queue).rows.isEmpty)
    }

    func testLongFormProjectPagesAsOneEntryWithEverySegment() throws {
        let queue = try makeQueue()
        try insert([
            row("segment 1", at: 1, projectID: "project", role: "segment"),
            row("standalone old", at: 2),
            row("segment 2", at: 3, projectID: "project", role: "segment"),
            row("segment 3", at: 4, projectID: "project", role: "segment"),
            row("earlier join", at: 5, projectID: "project", role: "superseded"),
            row("orphan segment", at: 6, projectID: "unjoined", role: "segment"),
            row("joined", at: 7, projectID: "project", role: "joined"),
            row("standalone new", at: 8),
        ], into: queue)

        let first = try page(GenerationHistoryPageRequest(limit: 2), in: queue)
        XCTAssertEqual(
            first.rows.map(\.text),
            ["standalone new", "joined", "segment 1", "segment 2", "segment 3"],
            "The project counts as one entry and brings every segment, even from later pages"
        )
        XCTAssertTrue(first.hasMore)

        let all = try page(GenerationHistoryPageRequest(limit: 10), in: queue)
        XCTAssertEqual(all.rows.count, 8, "Collapsed segments never page again as their own rows")
        XCTAssertEqual(Set(all.rows.compactMap(\.id)).count, 8)
        XCTAssertFalse(all.hasMore)
        XCTAssertTrue(all.rows.contains { $0.text == "orphan segment" }, "A segment without a joined row pages in place")
        XCTAssertTrue(all.rows.contains { $0.text == "earlier join" }, "A superseded output pages as an ordinary row")
        XCTAssertEqual(all.archiveCount, 8)

        let search = try page(GenerationHistoryPageRequest(query: "segment 2", limit: 1), in: queue)
        XCTAssertEqual(search.rows.map(\.text), ["segment 2"], "A search lists a matching segment flat")
    }

    func testModeFilterKeepsProjectsWholeAndRecoveryWithholdsProjectRows() throws {
        let queue = try makeQueue()
        try insert([
            row("clone segment", mode: "clone", at: 1, projectID: "project", role: "segment"),
            row("clone joined", mode: "clone", at: 2, projectID: "project", role: "joined"),
            row("custom take", at: 3),
        ], into: queue)

        XCTAssertEqual(
            try page(GenerationHistoryPageRequest(mode: "clone", limit: 1), in: queue).rows.map(\.text),
            ["clone joined", "clone segment"]
        )
        XCTAssertEqual(
            try page(GenerationHistoryPageRequest(mode: "custom"), in: queue).rows.map(\.text),
            ["custom take"]
        )

        let withheld = try queue.read { db in
            try GenerationHistoryPageQuery.fetch(
                GenerationHistoryPageRequest(),
                includesLongFormProjects: false,
                in: db
            )
        }
        XCTAssertEqual(withheld.rows.map(\.text), ["custom take"])
        XCTAssertEqual(withheld.archiveCount, 1)
    }

    func testSortOrdersPickTheirOwnFirstPageAndEachScreenKeepsItsSearch() throws {
        let queue = try makeQueue()
        try insert([
            row("alpha", mode: "design", duration: 5, at: 1),
            row("beta", duration: 1, at: 2),
            row("gamma", voice: "Vivian", duration: 3, at: 3),
            row("delta", mode: "clone", duration: nil, at: 4),
        ], into: queue)

        func first(_ order: GenerationHistoryPageRequest.Order, limit: Int) throws -> [String] {
            try page(GenerationHistoryPageRequest(order: order, limit: limit), in: queue).rows.map(\.text)
        }
        XCTAssertEqual(try first(.newest, limit: 2), ["delta", "gamma"])
        XCTAssertEqual(try first(.oldest, limit: 2), ["alpha", "beta"])
        XCTAssertEqual(try first(.longest, limit: 1), ["alpha"])
        XCTAssertEqual(try first(.shortest, limit: 1), ["delta"], "A missing duration sorts as zero, as the Mac list does")
        XCTAssertEqual(try first(.mode, limit: 2), ["delta", "gamma"])

        let mac = GenerationHistoryPageRequest.SearchStyle.lowercasedTranscriptAndVoice
        XCTAssertEqual(
            try page(GenerationHistoryPageRequest(query: " VIV ", searchStyle: mac, limit: 1), in: queue).rows.map(\.text),
            ["gamma"]
        )
        XCTAssertTrue(
            try page(GenerationHistoryPageRequest(query: "design", searchStyle: mac), in: queue).rows.isEmpty,
            "The Mac list searches transcript and voice only"
        )
        XCTAssertEqual(
            try page(GenerationHistoryPageRequest(query: "design"), in: queue).rows.map(\.text),
            ["alpha"],
            "The iPhone list also matches the mode"
        )
        XCTAssertEqual(GenerationHistoryPageQuery.lowercasedSearchKey(text: "Hello", voice: nil), "hello\n")
    }

    func testUnfilteredRequestsAreRecognizedWhateverTheirOrder() {
        XCTAssertTrue(GenerationHistoryPageRequest(query: "  ", order: .longest).isUnfiltered)
        XCTAssertFalse(GenerationHistoryPageRequest(mode: "clone").isUnfiltered)
        XCTAssertFalse(GenerationHistoryPageRequest(query: "take").isUnfiltered)
    }

    // MARK: - Reload coalescing (P10-07)

    /// A take saved while a page read is in flight is appended in place, but
    /// the read may have queried the archive before the row existed and its
    /// page replaces the list: one more read must follow it.
    func testATakeAppendedDuringAReadIsFollowedByOneMoreRead() throws {
        var coalescer = GenerationHistoryReloadCoalescer()
        let read = try XCTUnwrap(coalescer.beginRead())
        coalescer.noteRowChangedInPlace()

        XCTAssertTrue(coalescer.finishRead(read), "The page that may predate the row is read again")
        let followUp = try XCTUnwrap(coalescer.beginRead())
        XCTAssertFalse(coalescer.finishRead(followUp), "Nothing changed during the follow-up")
        XCTAssertFalse(coalescer.isReading)
    }

    func testATakeAppendedWithNoReadInFlightNeedsNoRead() throws {
        var coalescer = GenerationHistoryReloadCoalescer()
        coalescer.noteRowChangedInPlace()
        XCTAssertFalse(coalescer.followUpPending)

        let read = try XCTUnwrap(coalescer.beginRead())
        XCTAssertFalse(coalescer.finishRead(read))
    }

    func testReloadsAskedForDuringAReadCoalesceIntoOne() throws {
        var coalescer = GenerationHistoryReloadCoalescer()
        let read = try XCTUnwrap(coalescer.beginRead())
        XCTAssertNil(coalescer.beginRead())
        XCTAssertNil(coalescer.beginRead())
        coalescer.noteRowChangedInPlace()

        XCTAssertTrue(coalescer.finishRead(read))
        let followUp = try XCTUnwrap(coalescer.beginRead())
        XCTAssertFalse(coalescer.finishRead(followUp), "One follow-up answers every request")
    }

    /// A Retry that reopens a failed store, asked for while a read is in
    /// flight, is not lost: the follow-up carries the strongest request it
    /// answers, and an in-place change (an append or a delete) reconciles.
    func testAFollowUpCarriesTheStrongestRequestItAnswers() throws {
        var coalescer = GenerationHistoryReloadCoalescer()
        let read = try XCTUnwrap(coalescer.beginRead(reopenFailedStore: false, reconciling: false))
        XCTAssertNil(coalescer.beginRead(reopenFailedStore: true, reconciling: false))
        XCTAssertEqual(coalescer.finishReadWithFollowUp(read),
                       .init(reopenFailedStore: true, reconciling: false))

        let next = try XCTUnwrap(coalescer.beginRead(reopenFailedStore: false, reconciling: false))
        coalescer.noteRowChangedInPlace()
        XCTAssertEqual(coalescer.finishReadWithFollowUp(next),
                       .init(reopenFailedStore: false, reconciling: true))
        let last = try XCTUnwrap(coalescer.beginRead())
        XCTAssertNil(coalescer.finishReadWithFollowUp(last))
    }

    /// The screen went away mid-read and came back: the abandoned read's late
    /// end must not end, or follow up, the read the returning screen started.
    func testAReadAbandonedWithItsScreenCannotEndTheNextRead() throws {
        var coalescer = GenerationHistoryReloadCoalescer()
        let abandoned = try XCTUnwrap(coalescer.beginRead())
        coalescer.noteRowChangedInPlace()
        coalescer.abandonRead()
        XCTAssertFalse(coalescer.isReading)
        XCTAssertFalse(coalescer.followUpPending)

        let current = try XCTUnwrap(coalescer.beginRead())
        XCTAssertNotEqual(abandoned, current)
        XCTAssertFalse(coalescer.finishRead(abandoned))
        coalescer.cancelRead(abandoned)
        XCTAssertTrue(coalescer.isCurrentRead(current))

        coalescer.cancelRead(current)
        XCTAssertFalse(coalescer.isReading)
        XCTAssertFalse(coalescer.finishRead(current), "A cancelled read has nothing to follow up")
    }

    // MARK: - Fixture

    private func makeQueue() throws -> DatabaseQueue {
        let queue = try DatabaseQueue()
        try GenerationMigrations.makeMigrator().migrate(queue)
        return queue
    }

    private func insert(_ rows: [Generation], into queue: DatabaseQueue) throws {
        try queue.write { db in
            for var row in rows {
                try row.insert(db)
            }
        }
    }

    private func page(_ request: GenerationHistoryPageRequest, in queue: DatabaseQueue) throws -> GenerationHistoryPage {
        try queue.read { db in
            try GenerationHistoryPageQuery.fetch(request, includesLongFormProjects: true, in: db)
        }
    }

    private func row(
        _ text: String,
        mode: String = "custom",
        voice: String? = nil,
        duration: Double? = 1,
        at seconds: TimeInterval,
        projectID: String? = nil,
        role: String? = nil
    ) -> Generation {
        Generation(
            id: nil,
            text: text,
            mode: mode,
            modelTier: "lite",
            voice: voice,
            emotion: nil,
            speed: nil,
            audioPath: "fixture-\(UUID().uuidString).wav",
            duration: duration,
            createdAt: Date(timeIntervalSince1970: 1_700_000_000 + seconds),
            longFormProjectID: projectID,
            longFormRole: role,
            seed: nil
        )
    }
}
