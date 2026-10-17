import XCTest

/// MAC-16 / IOS-16 / SEC-1: take file names, the names of their exported
/// copies and the iPhone's output-folder override.
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

    /// SEC-1: a take's name is the timestamp and the app's name, never the
    /// script, because the share sheet, AirDrop, Files and the Mac's output
    /// folder all show it.
    func testTheNameJoinsTheTimestampAndTheAppName() {
        let name = GenerationOutputFileName.make(date: date, timeZone: utc)
        XCTAssertEqual(name, "20260926_14-03-07-250_Vocello.wav")
        XCTAssertTrue(name.allSatisfy { $0.isASCII })
    }

    /// SEC-1: takes an earlier build named after their script keep that name
    /// on disk; their saved and exported copies take the neutral name of the
    /// same moment, whatever the script's language or length.
    func testAnEarlierBuildsTakeExportsUnderTheNeutralName() {
        let neutral = GenerationOutputFileName.make(date: date, timeZone: utc)
        for legacy in [
            "20260926_14-03-07-250_Hello_world.wav",
            "20260926_14-03-07-250_こんにちは_世界.wav",
            "20260926_14-03-07-250_नमस्ते_दुनिया.wav",
            "20260926_14-03-07-250_audio.wav",
            // A long-form segment: `segment_<n>_<line>`, then a UUID.
            "20260926_14-03-07-250_segment_0001_Tell_Ma_0A1B2C3D-4E5F-4A6B-8C7D-9E0F1A2B3C4D.wav",
        ] {
            XCTAssertEqual(GenerationOutputFileName.exportName(forTakeNamed: legacy), neutral, legacy)
        }
    }

    func testACurrentTakeAndItsLongFormSegmentsExportUnderTheTakeName() {
        let name = GenerationOutputFileName.make(date: date, timeZone: utc)
        XCTAssertEqual(GenerationOutputFileName.exportName(forTakeNamed: name), name)
        let segment = LongFormHistoryAcceptance.uniqueAudioURL(
            basedOn: URL(fileURLWithPath: "/outputs/CustomVoice").appendingPathComponent(name)
        )
        XCTAssertNotEqual(segment.lastPathComponent, name, "a segment adds its UUID")
        XCTAssertEqual(GenerationOutputFileName.exportName(forTakeNamed: segment.lastPathComponent), name)
    }

    func testTheExportNameKeepsTheExtension() {
        XCTAssertEqual(
            GenerationOutputFileName.exportName(forTakeNamed: "20260926_14-03-07-250_Hello.WAV"),
            "20260926_14-03-07-250_Vocello.WAV"
        )
        XCTAssertEqual(
            GenerationOutputFileName.exportName(forTakeNamed: "20260926_14-03-07-250_Hello"),
            "20260926_14-03-07-250_Vocello"
        )
    }

    /// Names that do not begin with a take timestamp carry no script and are
    /// exported as they are: a joined long-form project, a recovery journal,
    /// a near miss of the timestamp.
    func testANameWithoutATakeTimestampIsExportedUnchanged() {
        for name in [
            "long_form_joined_0123abcd_0A1B2C3D-4E5F-4A6B-8C7D-9E0F1A2B3C4D.wav",
            "0A1B2C3D-4E5F-4A6B-8C7D-9E0F1A2B3C4D.json",
            "custom_take.wav",
            "20260926_14-03-07-250.wav",
            "2026092_14-03-07-250_Hello.wav",
            "x20260926_14-03-07-250_Hello.wav",
            "\u{0662}\u{0660}\u{0662}\u{0666}\u{0660}\u{0669}\u{0662}\u{0666}_14-03-07-250_Hello.wav",
            "",
        ] {
            XCTAssertEqual(GenerationOutputFileName.exportName(forTakeNamed: name), name, name)
        }
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
