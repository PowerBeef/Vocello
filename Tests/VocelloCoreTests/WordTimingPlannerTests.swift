import XCTest

final class WordTimingPlannerTests: XCTestCase {
    func testWordsShareTheDurationEvenlyAndWhitespaceKeepsTheSource() {
        let spans = WordTimingPlanner.plan(transcript: "one  two\nthree", audioDuration: 3)
        XCTAssertEqual(spans.map(\.text).joined(), "one  two\nthree")
        let words = spans.filter { !$0.isWhitespace }
        XCTAssertEqual(words.map(\.text), ["one", "two", "three"])
        XCTAssertEqual(words.map(\.start), [0, 1, 2])
        XCTAssertEqual(words.map(\.end), [1, 2, 3])
        // Whitespace inherits the previous word's end so the cursor never pauses on it.
        let gap = spans[1]
        XCTAssertTrue(gap.isWhitespace)
        XCTAssertEqual(gap.start, 1)
        XCTAssertEqual(gap.end, 1)
    }

    func testActiveIndexSelectsTheWordContainingTheTime() {
        let spans = WordTimingPlanner.plan(transcript: "a b c", audioDuration: 3)
        XCTAssertEqual(WordTimingPlanner.activeIndex(in: spans, at: 0.5), 0)
        XCTAssertEqual(WordTimingPlanner.activeIndex(in: spans, at: 1.5), 2)
        XCTAssertEqual(WordTimingPlanner.activeIndex(in: spans, at: 2.999), 4)
        XCTAssertNil(WordTimingPlanner.activeIndex(in: spans, at: 3))
    }

    func testDegenerateInputsYieldOneSpan() {
        XCTAssertEqual(WordTimingPlanner.plan(transcript: "", audioDuration: 2).count, 1)
        let zero = WordTimingPlanner.plan(transcript: "hello", audioDuration: 0)
        XCTAssertEqual(zero.count, 1)
        XCTAssertEqual(zero[0].end, 0)
        let blank = WordTimingPlanner.plan(transcript: "   ", audioDuration: 2)
        XCTAssertEqual(blank.count, 1)
        XCTAssertTrue(blank[0].isWhitespace)
        XCTAssertEqual(blank[0].end, 2)
    }
}
