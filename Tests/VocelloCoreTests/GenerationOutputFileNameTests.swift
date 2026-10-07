import XCTest

/// MAC-16 / IOS-16: take file names and the iPhone's output-folder override.
final class GenerationOutputFileNameTests: XCTestCase {
    private let utc = TimeZone(identifier: "UTC")!
    /// 2026-09-26 14:03:07.250 UTC. A quarter second is exact in binary, so the
    /// millisecond field cannot round down to the previous value.
    private let date = Date(timeIntervalSince1970: 1_790_431_387.25)

    func testTheTimestampIsGregorianWithASCIIDigits() {
        let stamp = GenerationOutputFileName.timestamp(for: date, timeZone: utc)
        XCTAssertEqual(stamp, "20260926_14-03-07-250")
        XCTAssertTrue(stamp.allSatisfy { $0.isASCII })
    }

    func testTheNameJoinsTheTimestampAndTheSnippet() {
        XCTAssertEqual(
            GenerationOutputFileName.make(text: "Hello, world!", date: date, timeZone: utc),
            "20260926_14-03-07-250_Hello_world.wav"
        )
    }

    func testWhitespaceRunsIncludingNewlinesAndTabsBecomeOneUnderscore() {
        XCTAssertEqual(GenerationOutputFileName.snippet(from: "Line one\n\tline two"), "Line_one_line_two")
        XCTAssertEqual(GenerationOutputFileName.snippet(from: "  padded   words  "), "padded_words")
        XCTAssertFalse(GenerationOutputFileName.snippet(from: "a\r\nb\u{2028}c").contains { $0.isWhitespace })
    }

    func testTheSnippetIsBoundedAndNeverEndsWithAnUnderscore() {
        let snippet = GenerationOutputFileName.snippet(from: "The quick brown fox jumps over the lazy dog")
        XCTAssertLessThanOrEqual(snippet.count, GenerationOutputFileName.snippetLength)
        XCTAssertFalse(snippet.hasSuffix("_"))
        XCTAssertEqual(GenerationOutputFileName.snippet(from: "abcdefghijklmnopqrs tuvw"), "abcdefghijklmnopqrs")
    }

    func testPunctuationOnlyTextFallsBack() {
        XCTAssertEqual(GenerationOutputFileName.snippet(from: "?!…\n\t"), GenerationOutputFileName.fallbackSnippet)
        XCTAssertEqual(GenerationOutputFileName.snippet(from: ""), GenerationOutputFileName.fallbackSnippet)
    }

    func testNonLatinLettersAreKept() {
        XCTAssertEqual(GenerationOutputFileName.snippet(from: "こんにちは 世界"), "こんにちは_世界")
        XCTAssertEqual(GenerationOutputFileName.snippet(from: "नमस्ते दुनिया"), "नमस्ते_दुनिया", "a letter keeps its marks")
    }

    /// P09-03: the emoji the snippet strips leave their variation selectors and
    /// joiners behind, and stacked marks make one letter of any size; neither
    /// may push the staging or long-form segment name past the 255-character
    /// file-name limit, which would fail every take of that script.
    func testNoScriptPushesTheTakeNamePastTheFileNameLimit() {
        let hearts = String(repeating: "\u{2764}\u{FE0F}", count: 200) + " hi"
        let flags = String(repeating: "\u{1F3F3}\u{FE0F}\u{200D}\u{1F308}", count: 100)
        let zalgo = String(repeating: "a" + String(repeating: "\u{0301}", count: 12), count: 20)
        let stagingAndSegmentSuffixes = 42 + 37
        for text in [hearts, flags, zalgo] {
            let name = GenerationOutputFileName.make(text: text, date: date, timeZone: utc)
            XCTAssertLessThanOrEqual(name.utf8.count + stagingAndSegmentSuffixes, 255)
            let snippet = GenerationOutputFileName.snippet(from: text)
            XCTAssertLessThanOrEqual(snippet.utf8.count, GenerationOutputFileName.snippetUTF8Budget)
            for character in snippet {
                XCTAssertLessThanOrEqual(character.unicodeScalars.count, GenerationOutputFileName.maximumScalarsPerCharacter)
                let first = character.unicodeScalars.first!
                XCTAssertFalse(first.properties.isGraphemeExtend || first.value == 0x200D, "no lone extender")
            }
        }
        XCTAssertEqual(GenerationOutputFileName.snippet(from: hearts), "hi")
        XCTAssertEqual(GenerationOutputFileName.snippet(from: flags), GenerationOutputFileName.fallbackSnippet)
        XCTAssertTrue(GenerationOutputFileName.snippet(from: zalgo).hasPrefix("a\u{0301}\u{0301}\u{0301}"))
    }

    // MARK: - IOS-16 output root

    private var allowedRoot: URL {
        FileManager.default.temporaryDirectory
            .appendingPathComponent("GenerationOutputRootOverrideTests", isDirectory: true)
            .appendingPathComponent("Library/Caches/Vocello/diagnostics", isDirectory: true)
    }

    func testALaneRunFolderUnderTheDiagnosticsRootIsAccepted() {
        let runFolder = allowedRoot.appendingPathComponent("run-1/outputs", isDirectory: true)
        let accepted = GenerationOutputRootOverride.acceptedRoot(configuredPath: runFolder.path, allowedRoot: allowedRoot)
        XCTAssertEqual(accepted?.path, runFolder.standardizedFileURL.path)
    }

    func testThePrivateAliasOfVarMatchesTheRoot() {
        let root = URL(fileURLWithPath: "/var/mobile/Containers/Data/Application/A/Library/Caches/Vocello/diagnostics")
        let configured = "/private" + root.path + "/run-1/outputs"
        XCTAssertNotNil(GenerationOutputRootOverride.acceptedRoot(configuredPath: configured, allowedRoot: root))
    }

    func testAFolderOutsideTheDiagnosticsRootIsIgnored() {
        let documents = allowedRoot
            .deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
            .deletingLastPathComponent()
            .appendingPathComponent("Documents", isDirectory: true)
        XCTAssertNil(GenerationOutputRootOverride.acceptedRoot(configuredPath: documents.path, allowedRoot: allowedRoot))
    }

    func testDotDotCannotEscapeTheDiagnosticsRoot() {
        let escape = allowedRoot.path + "/run-1/../../../../Documents"
        XCTAssertNil(GenerationOutputRootOverride.acceptedRoot(configuredPath: escape, allowedRoot: allowedRoot))
    }

    func testTheRootItselfASiblingPrefixAndEmptyValuesAreIgnored() {
        XCTAssertNil(GenerationOutputRootOverride.acceptedRoot(configuredPath: allowedRoot.path, allowedRoot: allowedRoot))
        XCTAssertNil(GenerationOutputRootOverride.acceptedRoot(configuredPath: allowedRoot.path + "-other/x", allowedRoot: allowedRoot))
        XCTAssertNil(GenerationOutputRootOverride.acceptedRoot(configuredPath: "   ", allowedRoot: allowedRoot))
        XCTAssertNil(GenerationOutputRootOverride.acceptedRoot(configuredPath: "relative/outputs", allowedRoot: allowedRoot))
        XCTAssertNil(GenerationOutputRootOverride.acceptedRoot(configuredPath: allowedRoot.path + "/run", allowedRoot: nil))
    }
}
