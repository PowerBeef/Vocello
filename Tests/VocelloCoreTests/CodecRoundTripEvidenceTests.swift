import CryptoKit
import Foundation
@testable import QwenVoiceCore
import VocelloQwen3Core
import XCTest

/// The pure pieces of `vocello bench --codec-roundtrip` (audio QC population
/// N2): job and WAV validation, the codes binary and the PCM16 output. No model
/// runs here; the facade's trim and encoder refusal are covered by the owned
/// runtime's facade tests.
final class CodecRoundTripEvidenceTests: XCTestCase {
    private typealias Evidence = CodecRoundTripEvidence

    func testJobDecodesBoundedSafeUniqueItems() throws {
        let items = try Evidence.decodeJob(job([item("take-1", "inputs/take-1.wav")]))
        XCTAssertEqual(items, [Evidence.Item(id: "take-1", wavPath: "inputs/take-1.wav", wavSHA256: digest)])

        let refused: [(Data, Evidence.EvidenceError)] = [
            (job([item("a", "a.wav")], kind: "audio-qc-n3"), .invalidJob),
            (job([item("a", "a.wav")], schemaVersion: 2), .invalidJob),
            (job([item("a", "a.wav")], sampleRate: 16_000), .invalidJob),
            (job([]), .invalidJob),
            (Data("not json".utf8), .invalidJob),
            (job([item(".hidden", "a.wav")]), .invalidItem),
            (job([item("a/b", "a.wav")]), .invalidItem),
            (job([item(String(repeating: "a", count: 97), "a.wav")]), .invalidItem),
            (job([item("a", "/abs/a.wav")]), .invalidItem),
            (job([item("a", "../a.wav")]), .invalidItem),
            (job([item("a", "inputs//a.wav")]), .invalidItem),
            (job([item("a", "a.wav", sha256: String(repeating: "A", count: 64))]), .invalidItem),
            (job([item("a", "a.wav", sha256: "abc")]), .invalidItem),
            (job([item("Take", "a.wav"), item("take", "b.wav")]), .duplicateItem),
            (job((0 ... Evidence.maximumItems).map { item("t\($0)", "t\($0).wav") }), .invalidJob),
            (Data(count: Evidence.maximumJobBytes + 1), .inputOutOfBounds),
        ]
        for (data, expected) in refused {
            XCTAssertThrowsError(try Evidence.decodeJob(data)) {
                XCTAssertEqual($0 as? Evidence.EvidenceError, expected)
            }
        }
    }

    func testInputPathStaysUnderTheJobDirectory() throws {
        let root = try temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: root) }
        let jobDirectory = root.appendingPathComponent("job", isDirectory: true)
        try FileManager.default.createDirectory(
            at: jobDirectory.appendingPathComponent("inputs"), withIntermediateDirectories: true
        )
        let inside = jobDirectory.appendingPathComponent("inputs/a.wav")
        try Data("x".utf8).write(to: inside)
        let resolved = try Evidence.inputURL(
            for: Evidence.Item(id: "a", wavPath: "inputs/a.wav", wavSHA256: digest), jobDirectory: jobDirectory
        )
        XCTAssertEqual(try Data(contentsOf: resolved), Data("x".utf8))

        let outside = root.appendingPathComponent("outside.wav")
        try Data("y".utf8).write(to: outside)
        try FileManager.default.createSymbolicLink(
            at: jobDirectory.appendingPathComponent("inputs/link.wav"), withDestinationURL: outside
        )
        XCTAssertThrowsError(try Evidence.inputURL(
            for: Evidence.Item(id: "b", wavPath: "inputs/link.wav", wavSHA256: digest), jobDirectory: jobDirectory
        )) {
            XCTAssertEqual($0 as? Evidence.EvidenceError, .invalidItem)
        }
    }

    func testOnlyStrictMonoPCM16At24kHzIsAccepted() throws {
        let pcm: [Int16] = [0, 1, -1, .max, .min]
        XCTAssertEqual(try Evidence.monoPCM16Samples(wav: wav(pcm)), pcm)
        // An unknown chunk (odd-sized, so padded) is skipped.
        XCTAssertEqual(try Evidence.monoPCM16Samples(wav: wav(pcm, extraChunk: Data([1, 2, 3]))), pcm)

        let refused: [(Data, Evidence.EvidenceError)] = [
            (wav(pcm, channels: 2), .unsupportedWAV),
            (wav(pcm, sampleRate: 16_000), .unsupportedWAV),
            (wav(pcm, bitsPerSample: 8), .unsupportedWAV),
            (wav(pcm, format: 3), .unsupportedWAV),
            (wav([]), .unsupportedWAV),
            (wav(pcm, dataBeforeFormat: true), .unsupportedWAV),
            (wav(pcm).dropLast(), .unsupportedWAV),
            (wav(pcm) + Data([0, 0]), .unsupportedWAV),
            (Data("RIFF".utf8), .unsupportedWAV),
            (wav([Int16](repeating: 1, count: Evidence.maximumInputSamples + 1)), .inputOutOfBounds),
        ]
        for (data, expected) in refused {
            XCTAssertThrowsError(try Evidence.monoPCM16Samples(wav: Data(data))) {
                XCTAssertEqual($0 as? Evidence.EvidenceError, expected)
            }
        }
    }

    func testInputBytesBindToTheirDigestBeforeTheyAreScaled() throws {
        let data = wav([.min, 16_384, 0])
        let samples = try Evidence.verifiedInputSamples(data, expectedSHA256: sha256(data))
        XCTAssertEqual(samples, [-1, 0.5, 0])
        XCTAssertThrowsError(try Evidence.verifiedInputSamples(data, expectedSHA256: digest)) {
            XCTAssertEqual($0 as? Evidence.EvidenceError, .digestMismatch)
        }
    }

    func testCodesUseTheReplayTraceEncodingOnlyWhenComplete() throws {
        let codes: [[Int32]] = [
            [4_095] + [Int32](repeating: 2_047, count: 15),
            [Int32](repeating: 0, count: 16),
        ]
        let data = try Evidence.codesData(codes)
        let trace = try StartupReliabilityDiagnosticEvidence.decode(data)
        XCTAssertEqual(trace.frames, codes)
        XCTAssertEqual(trace.droppedFrameCount, 0)

        let refused: [[[Int32]]] = [
            [],
            [[Int32](repeating: 0, count: 15)],
            [[-1] + [Int32](repeating: 0, count: 15)],
            [[0, 2_048] + [Int32](repeating: 0, count: 14)],
            [[4_096] + [Int32](repeating: 0, count: 15)],
        ]
        for value in refused {
            XCTAssertThrowsError(try Evidence.codesData(value)) {
                XCTAssertEqual($0 as? Evidence.EvidenceError, .invalidCodes)
            }
        }
    }

    func testOutputIsPlainPCM16WithoutTheLimiterAndCountsClamps() throws {
        let (pcm, clamped) = try Evidence.pcm16([0.5, -0.5, 1.5, -2, 0.99])
        XCTAssertEqual(pcm, [16_384, -16_384, Int16.max, -Int16.max, 32_439])
        XCTAssertEqual(clamped, 2)
        XCTAssertThrowsError(try Evidence.pcm16([0.1, .nan])) {
            XCTAssertEqual($0 as? Evidence.EvidenceError, .invalidOutput)
        }
        XCTAssertThrowsError(try Evidence.pcm16([])) {
            XCTAssertEqual($0 as? Evidence.EvidenceError, .invalidOutput)
        }

        let root = try temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: root) }
        let url = root.appendingPathComponent("take.wav")
        // 0.99 stays 0.99: the production limiter would have pulled it under its ceiling.
        let written = try Evidence.writeOutputWAV(samples: [0.99, -0.25, 0], sampleRate: 24_000, to: url)
        let data = try Data(contentsOf: url)
        XCTAssertEqual(written.sha256, sha256(data))
        XCTAssertEqual(written.byteCount, data.count)
        XCTAssertEqual(written.sampleCount, 3)
        XCTAssertEqual(written.clampedSampleCount, 0)
        XCTAssertEqual(try Evidence.monoPCM16Samples(wav: data), [32_439, -8_192, 0])
        XCTAssertThrowsError(try Evidence.writeOutputWAV(samples: [0.1], sampleRate: 16_000, to: url)) {
            XCTAssertEqual($0 as? Evidence.EvidenceError, .invalidOutput)
        }
    }

    // MARK: - Fixtures

    private let digest = String(repeating: "a", count: 64)

    private func item(_ id: String, _ path: String, sha256: String? = nil) -> [String: Any] {
        ["id": id, "wavPath": path, "wavSHA256": sha256 ?? digest]
    }

    private func job(
        _ items: [[String: Any]],
        kind: String = CodecRoundTripEvidence.jobKind,
        schemaVersion: Int = 1,
        sampleRate: Int = 24_000
    ) -> Data {
        let value: [String: Any] = [
            "schemaVersion": schemaVersion, "kind": kind, "sampleRate": sampleRate, "items": items,
        ]
        return (try? JSONSerialization.data(withJSONObject: value, options: [.sortedKeys])) ?? Data()
    }

    private func wav(
        _ pcm: [Int16],
        channels: UInt16 = 1,
        sampleRate: UInt32 = 24_000,
        bitsPerSample: UInt16 = 16,
        format: UInt16 = 1,
        extraChunk: Data? = nil,
        dataBeforeFormat: Bool = false
    ) -> Data {
        func le<T: FixedWidthInteger>(_ value: T) -> Data {
            withUnsafeBytes(of: value.littleEndian) { Data($0) }
        }
        let blockAlign = channels * bitsPerSample / 8
        var formatChunk = Data("fmt ".utf8) + le(UInt32(16))
        formatChunk += le(format) + le(channels) + le(sampleRate)
        formatChunk += le(sampleRate * UInt32(blockAlign)) + le(blockAlign) + le(bitsPerSample)
        let body = pcm.map(\.littleEndian).withUnsafeBufferPointer { Data(buffer: $0) }
        let dataChunk = Data("data".utf8) + le(UInt32(body.count)) + body
        var chunks = dataBeforeFormat ? dataChunk + formatChunk : formatChunk + dataChunk
        if let extraChunk {
            chunks += Data("LIST".utf8) + le(UInt32(extraChunk.count)) + extraChunk
            if extraChunk.count % 2 == 1 { chunks += Data([0]) }
        }
        return Data("RIFF".utf8) + le(UInt32(4 + chunks.count)) + Data("WAVE".utf8) + chunks
    }

    private func sha256(_ data: Data) -> String {
        SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
    }

    private func temporaryDirectory() throws -> URL {
        let url = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString, isDirectory: true)
        try FileManager.default.createDirectory(at: url, withIntermediateDirectories: true)
        return url
    }
}
