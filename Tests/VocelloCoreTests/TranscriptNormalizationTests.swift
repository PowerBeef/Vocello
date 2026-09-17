import XCTest

/// The clone transcript is conditioning, not prose. Its field became
/// multi-line so a user can actually read it against the reference clip, which
/// means Return now inserts a newline rather than committing — so this is what
/// stands between a stray line break and the model.
final class TranscriptNormalizationTests: XCTestCase {
    func testInteriorNewlinesCollapseToSingleSpaces() {
        XCTAssertEqual(
            TranscriptNormalization.conditioningLine(
                "The morning train\nslipped quietly\n\nout of the station."
            ),
            "The morning train slipped quietly out of the station."
        )
    }

    func testTabsAndRunsOfSpacesCollapseAndEndsAreTrimmed() {
        XCTAssertEqual(
            TranscriptNormalization.conditioningLine("  The\tmorning   train  "),
            "The morning train"
        )
    }

    func testWhitespaceOnlyIsNilRatherThanEmpty() {
        XCTAssertNil(TranscriptNormalization.conditioningLine("   \n\t  "))
        XCTAssertNil(TranscriptNormalization.conditioningLine(""))
    }

    func testAnOrdinarySingleLineTranscriptIsUnchanged() {
        let line = "The morning train slipped quietly out of the station."
        XCTAssertEqual(TranscriptNormalization.conditioningLine(line), line)
    }
}
