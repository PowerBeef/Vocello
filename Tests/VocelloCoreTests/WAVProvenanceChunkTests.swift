import Foundation
import XCTest

@testable import QwenVoiceCore

/// The Article 50 provenance chunk (CP-2 piece 2): appended LIST/INFO must
/// keep the WAV well-formed, carry the machine-readable statement, and be
/// readable back field-for-field. Applied by both publication paths since
/// CP-2 piece 3; these tests own the utility's contract.
final class WAVProvenanceChunkTests: XCTestCase {
    private func makeBareWAV(samples: [Int16] = Array(repeating: 0, count: 2_400)) throws -> URL {
        let url = FileManager.default.temporaryDirectory
            .appendingPathComponent("provenance-\(UUID().uuidString).wav")
        var data = Data()
        data.append(contentsOf: "RIFF".utf8)
        withUnsafeBytes(of: UInt32(36 + samples.count * 2).littleEndian) { data.append(contentsOf: $0) }
        data.append(contentsOf: "WAVE".utf8)
        data.append(contentsOf: "fmt ".utf8)
        withUnsafeBytes(of: UInt32(16).littleEndian) { data.append(contentsOf: $0) }
        withUnsafeBytes(of: UInt16(1).littleEndian) { data.append(contentsOf: $0) }
        withUnsafeBytes(of: UInt16(1).littleEndian) { data.append(contentsOf: $0) }
        withUnsafeBytes(of: UInt32(24_000).littleEndian) { data.append(contentsOf: $0) }
        withUnsafeBytes(of: UInt32(48_000).littleEndian) { data.append(contentsOf: $0) }
        withUnsafeBytes(of: UInt16(2).littleEndian) { data.append(contentsOf: $0) }
        withUnsafeBytes(of: UInt16(16).littleEndian) { data.append(contentsOf: $0) }
        data.append(contentsOf: "data".utf8)
        withUnsafeBytes(of: UInt32(samples.count * 2).littleEndian) { data.append(contentsOf: $0) }
        samples.withUnsafeBufferPointer { data.append(Data(buffer: $0)) }
        try data.write(to: url)
        return url
    }

    func testAppendedChunkRoundTripsAndPatchesRIFFSize() throws {
        let url = try makeBareWAV()
        defer { try? FileManager.default.removeItem(at: url) }
        let comment = WAVProvenanceChunk.comment(
            modelID: "pro_custom_speed", mode: "custom",
            createdAt: Date(timeIntervalSince1970: 1_786_000_000),
            watermarkPayload: 0x56C0, generatorVersion: "9.9.9")
        try WAVProvenanceChunk.append(toWAVAt: url, software: "Vocello test", comment: comment)

        let fields = try WAVProvenanceChunk.readInfoFields(fromWAVAt: url)
        XCTAssertEqual(fields["ISFT"], "Vocello test")
        XCTAssertEqual(fields["ICMT"], comment)
        XCTAssertTrue(comment.hasPrefix("AI-generated audio"), comment)
        XCTAssertTrue(comment.contains("marking=AudioSeal:0x56C0"), comment)

        // RIFF size must equal file length - 8 after the append.
        let bytes = try Data(contentsOf: url)
        let riffSize = UInt32(bytes[4]) | UInt32(bytes[5]) << 8
            | UInt32(bytes[6]) << 16 | UInt32(bytes[7]) << 24
        XCTAssertEqual(Int(riffSize), bytes.count - 8)
    }

    func testPCMBytesAreUntouchedByTheAppend() throws {
        let samples: [Int16] = (0 ..< 4_800).map { Int16(truncatingIfNeeded: $0 &* 13) }
        let url = try makeBareWAV(samples: samples)
        defer { try? FileManager.default.removeItem(at: url) }
        let before = try Data(contentsOf: url)
        try WAVProvenanceChunk.append(toWAVAt: url, software: "Vocello", comment: "AI-generated audio")
        let after = try Data(contentsOf: url)
        XCTAssertEqual(after[12 ..< before.count], before[12 ..< before.count],
                       "everything after the RIFF header preamble must be byte-identical")
    }

    func testRefusesNonRIFFTargets() throws {
        let url = FileManager.default.temporaryDirectory
            .appendingPathComponent("provenance-\(UUID().uuidString).bin")
        try Data("not a wav at all".utf8).write(to: url)
        defer { try? FileManager.default.removeItem(at: url) }
        XCTAssertThrowsError(
            try WAVProvenanceChunk.append(toWAVAt: url, software: "V", comment: "c"))
    }

    func testCommentOmitsMarkingFieldWithoutPayload() {
        let comment = WAVProvenanceChunk.comment(
            modelID: "m", mode: "design", createdAt: Date(timeIntervalSince1970: 0),
            watermarkPayload: nil, generatorVersion: nil)
        XCTAssertFalse(comment.contains("marking="), comment)
        XCTAssertTrue(comment.contains("mode=design"), comment)
    }

    func testCommentCarriesGeneratorVersionAfterGeneratorField() {
        let comment = WAVProvenanceChunk.comment(
            modelID: "m", mode: "clone", createdAt: Date(timeIntervalSince1970: 0),
            watermarkPayload: 0x56C0, generatorVersion: "9.9.9")
        XCTAssertTrue(comment.contains("generator=Vocello; version=9.9.9; engine=Qwen3-TTS"), comment)
    }

    func testCommentOmitsVersionFieldWhenUnresolvable() {
        let comment = WAVProvenanceChunk.comment(
            modelID: "m", mode: "custom", createdAt: Date(timeIntervalSince1970: 0),
            watermarkPayload: nil, generatorVersion: nil)
        XCTAssertFalse(comment.contains("version="), comment)
    }

    func testGeneratorSoftwareFormatsVersion() {
        XCTAssertEqual(WAVProvenanceChunk.generatorSoftware(version: "9.9.9"), "Vocello 9.9.9")
        XCTAssertEqual(WAVProvenanceChunk.generatorSoftware(version: nil), "Vocello")
    }
}
