import CryptoKit
import Foundation
@testable import QwenVoiceCore
import XCTest

final class FileStreamIOTests: XCTestCase {
    private var directory: URL!

    override func setUpWithError() throws {
        directory = FileManager.default.temporaryDirectory
            .appendingPathComponent("FileStreamIOTests-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
    }

    override func tearDownWithError() throws {
        if let directory {
            try? FileManager.default.removeItem(at: directory)
        }
    }

    // MARK: - Digest

    func testDigestOfEmptyFileMatchesKnownSHA256() throws {
        let url = try makeFile(named: "empty.bin", contents: Data())
        XCTAssertEqual(
            try FileStreamIO.sha256Hex(of: url),
            "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        )
    }

    func testDigestOfSmallFileMatchesKnownSHA256() throws {
        let url = try makeFile(named: "abc.bin", contents: Data("abc".utf8))
        XCTAssertEqual(
            try FileStreamIO.sha256Hex(of: url),
            "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
        )
    }

    func testDigestAcrossManySmallChunksMatchesKnownSHA256() throws {
        let url = try makeFile(
            named: "fox.bin",
            contents: Data("The quick brown fox jumps over the lazy dog".utf8)
        )
        // A 4-byte chunk forces eleven reads with a short final chunk.
        XCTAssertEqual(
            try FileStreamIO.sha256Hex(of: url, chunkSize: 4),
            "d7a8fbb307d7809469ca9abcb0082e4f8d5651e46d3cdb762d02d0bf37c9e592"
        )
    }

    func testDigestOfMultiChunkFileMatchesOneShotSHA256AndEveryCallSite() throws {
        // 2.5 MiB spans two full default chunks plus a partial third.
        let contents = patternedData(count: FileStreamIO.defaultChunkSize * 5 / 2)
        let url = try makeFile(named: "multi.bin", contents: contents)
        let expected = SHA256.hash(data: contents).map { String(format: "%02x", $0) }.joined()

        XCTAssertEqual(try FileStreamIO.sha256Hex(of: url), expected)
        XCTAssertEqual(try HuggingFaceDownloader.sha256Hex(for: url), expected)
        XCTAssertEqual(try SamplingTakeEvidence.sha256FileDigest(at: url), expected)
    }

    func testDigestOfMissingFileThrows() {
        let url = directory.appendingPathComponent("missing.bin")
        XCTAssertThrowsError(try FileStreamIO.sha256Hex(of: url))
    }

    func testDigestFromWriteOnlyHandleThrowsInsteadOfRaising() throws {
        let url = try makeFile(named: "write-only.bin", contents: Data("abc".utf8))
        let handle = try FileHandle(forWritingTo: url)
        defer { try? handle.close() }
        XCTAssertThrowsError(try FileStreamIO.sha256Hex(reading: handle))
    }

    // MARK: - Copy and append

    func testCopyIsByteIdenticalAcrossChunks() throws {
        let contents = patternedData(count: FileStreamIO.defaultChunkSize * 2 + 12_345)
        let source = try makeFile(named: "source.bin", contents: contents)
        let destination = try makeFile(named: "destination.bin", contents: Data())

        let handle = try FileHandle(forWritingTo: destination)
        let copied = try FileStreamIO.copy(contentsOf: source, to: handle)
        try handle.close()

        XCTAssertEqual(copied, Int64(contents.count))
        XCTAssertEqual(try Data(contentsOf: destination), contents)
    }

    func testCopyWritesAtTheDestinationOffset() throws {
        let source = try makeFile(named: "chunk.bin", contents: Data("WXYZ".utf8))
        let destination = try makeFile(named: "partial.bin", contents: Data("abcdefghij".utf8))

        let handle = try FileHandle(forWritingTo: destination)
        try handle.seek(toOffset: 3)
        let copied = try FileStreamIO.copy(contentsOf: source, to: handle, chunkSize: 3)
        try handle.close()

        XCTAssertEqual(copied, 4)
        XCTAssertEqual(try Data(contentsOf: destination), Data("abcWXYZhij".utf8))
    }

    func testAppendKeepsExistingPrefix() throws {
        let prefix = patternedData(count: 1_000, seed: 7)
        let suffix = patternedData(count: FileStreamIO.defaultChunkSize + 1, seed: 11)
        let source = try makeFile(named: "suffix.bin", contents: suffix)
        let destination = try makeFile(named: "prefix.bin", contents: prefix)

        let handle = try FileHandle(forWritingTo: destination)
        let appended = try FileStreamIO.append(contentsOf: source, to: handle)
        try handle.close()

        XCTAssertEqual(appended, Int64(suffix.count))
        XCTAssertEqual(try Data(contentsOf: destination), prefix + suffix)
    }

    func testWriteToUnwritableHandleThrowsInsteadOfRaising() throws {
        let source = try makeFile(named: "payload.bin", contents: Data("payload".utf8))
        let target = try makeFile(named: "read-only-handle.bin", contents: Data())
        // A handle opened for reading rejects writes with EBADF; the legacy
        // `write(_:)` would raise an Objective-C exception and abort the process.
        let readOnly = try FileHandle(forReadingFrom: target)
        defer { try? readOnly.close() }

        XCTAssertThrowsError(try FileStreamIO.copy(contentsOf: source, to: readOnly))
        XCTAssertThrowsError(try FileStreamIO.append(contentsOf: source, to: readOnly))
        XCTAssertEqual(try Data(contentsOf: target), Data())
    }

    func testCopyFromMissingSourceThrows() throws {
        let destination = try makeFile(named: "destination.bin", contents: Data())
        let handle = try FileHandle(forWritingTo: destination)
        defer { try? handle.close() }
        XCTAssertThrowsError(
            try FileStreamIO.copy(contentsOf: directory.appendingPathComponent("missing.bin"), to: handle)
        )
    }

    // MARK: - Helpers

    private func makeFile(named name: String, contents: Data) throws -> URL {
        let url = directory.appendingPathComponent(name)
        try contents.write(to: url)
        return url
    }

    private func patternedData(count: Int, seed: UInt32 = 1) -> Data {
        var state = seed
        var bytes = [UInt8](repeating: 0, count: count)
        for index in bytes.indices {
            state = state &* 1_664_525 &+ 1_013_904_223
            bytes[index] = UInt8(truncatingIfNeeded: state >> 24)
        }
        return Data(bytes)
    }
}
