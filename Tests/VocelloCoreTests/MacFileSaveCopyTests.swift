import XCTest

final class MacFileSaveCopyTests: XCTestCase {
    private var root: URL!

    override func setUpWithError() throws {
        root = FileManager.default.temporaryDirectory
            .appendingPathComponent("MacFileSaveCopyTests-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
    }

    override func tearDownWithError() throws {
        try? FileManager.default.removeItem(at: root)
    }

    private func write(_ name: String, _ contents: String) throws -> URL {
        let url = root.appendingPathComponent(name)
        try Data(contents.utf8).write(to: url)
        return url
    }

    private func contents(_ url: URL) throws -> String {
        String(decoding: try Data(contentsOf: url), as: UTF8.self)
    }

    func testSavingATakeOntoItselfKeepsIt() throws {
        let take = try write("take.wav", "take-bytes")
        XCTAssertEqual(try MacFileSaveCopy.copy(from: take, to: take), .sameFile)
        XCTAssertEqual(try contents(take), "take-bytes")
    }

    func testAPathThroughASymlinkOrDotDotIsTheSameFile() throws {
        let take = try write("take.wav", "take-bytes")
        let alias = root.appendingPathComponent("alias", isDirectory: true)
        try FileManager.default.createSymbolicLink(at: alias, withDestinationURL: root)
        XCTAssertEqual(try MacFileSaveCopy.copy(from: take, to: alias.appendingPathComponent("take.wav")), .sameFile)
        let dotted = root.appendingPathComponent("sub/../take.wav")
        XCTAssertEqual(try MacFileSaveCopy.copy(from: take, to: dotted), .sameFile)
        XCTAssertEqual(try contents(take), "take-bytes")
    }

    func testAHardLinkToTheTakeIsTheSameFile() throws {
        let take = try write("take.wav", "take-bytes")
        let link = root.appendingPathComponent("link.wav")
        try FileManager.default.linkItem(at: take, to: link)
        XCTAssertEqual(try MacFileSaveCopy.copy(from: take, to: link), .sameFile)
        XCTAssertEqual(try contents(take), "take-bytes")
    }

    func testANewDestinationReceivesTheBytes() throws {
        let take = try write("take.wav", "take-bytes")
        let destination = root.appendingPathComponent("export.wav")
        XCTAssertEqual(try MacFileSaveCopy.copy(from: take, to: destination), .copied)
        XCTAssertEqual(try contents(destination), "take-bytes")
        XCTAssertEqual(try contents(take), "take-bytes")
    }

    func testAnExistingDifferentFileIsReplaced() throws {
        let take = try write("take.wav", "take-bytes")
        let destination = try write("export.wav", "old-bytes")
        XCTAssertEqual(try MacFileSaveCopy.copy(from: take, to: destination), .copied)
        XCTAssertEqual(try contents(destination), "take-bytes")
        XCTAssertEqual(try contents(take), "take-bytes")
    }

    func testAFailedCopyLeavesTheExistingDestinationAndNoStagingFile() throws {
        let missing = root.appendingPathComponent("missing.wav")
        let destination = try write("export.wav", "old-bytes")
        XCTAssertThrowsError(try MacFileSaveCopy.copy(from: missing, to: destination))
        XCTAssertEqual(try contents(destination), "old-bytes")
        let leftovers = try FileManager.default.contentsOfDirectory(atPath: root.path)
            .filter { $0.contains("vocello-save") }
        XCTAssertEqual(leftovers, [])
    }
}
