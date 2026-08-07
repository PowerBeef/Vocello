import Foundation
import XCTest

@testable import QwenVoiceCore

/// The Article 50 publication marker (CP-2 piece 3): staged-WAV marking must
/// rewrite exactly the data chunk through an injected transform, append the
/// provenance chunk, honor the registered debug override, and refuse formats
/// it cannot mark. The live AudioSeal transform is integration-proven by the
/// owned-package parity tests plus the QC-neutrality and peak-equality
/// evidence lanes; these tests own the seam mechanics.
final class AudioPublicationMarkingTests: XCTestCase {
    private func makeWAV(samples: [Int16]) throws -> URL {
        let url = FileManager.default.temporaryDirectory
            .appendingPathComponent("marking-\(UUID().uuidString).wav")
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

    private var configuration: AudioMarkingConfiguration {
        AudioMarkingConfiguration(
            weightsURL: URL(fileURLWithPath: "/nonexistent/for-transform-tests"),
            modelID: "pro_custom_speed",
            mode: "custom"
        )
    }

    func testMarksDataChunkThroughTransformAndAppendsProvenance() throws {
        let samples: [Int16] = (0 ..< 4_800).map { Int16(truncatingIfNeeded: $0 &* 7) }
        let url = try makeWAV(samples: samples)
        defer { try? FileManager.default.removeItem(at: url) }

        let marked = try AudioPublicationMarker.markStagedWAV(
            at: url,
            configuration: configuration,
            environment: [:],
            transform: { pcm in pcm.map { $0 * 0.5 } }
        )
        XCTAssertTrue(marked)

        let layout = try WAVDataLayout(contentsOf: url)
        XCTAssertEqual(layout.sampleCount, samples.count, "sample count must be preserved")
        let rewritten = try layout.readSamples(from: url)
        for (index, original) in samples.enumerated() where index % 977 == 0 {
            XCTAssertEqual(
                rewritten[index],
                Float(Int16((Float(original) / 32768.0 * 0.5 * 32767.0).rounded())) / 32768.0,
                accuracy: 1.0 / 32768.0,
                "transform must land in the data chunk"
            )
        }

        let fields = try WAVProvenanceChunk.readInfoFields(fromWAVAt: url)
        XCTAssertEqual(fields["ISFT"], "Vocello")
        let comment = try XCTUnwrap(fields["ICMT"])
        XCTAssertTrue(comment.hasPrefix("AI-generated audio"), comment)
        XCTAssertTrue(comment.contains("model=pro_custom_speed"), comment)
        XCTAssertTrue(comment.contains("mode=custom"), comment)
        XCTAssertTrue(comment.contains("marking=AudioSeal:0x56C0"), comment)

        // RIFF size covers the appended chunk.
        let bytes = try Data(contentsOf: url)
        let riffSize = UInt32(bytes[4]) | UInt32(bytes[5]) << 8
            | UInt32(bytes[6]) << 16 | UInt32(bytes[7]) << 24
        XCTAssertEqual(Int(riffSize), bytes.count - 8)
    }

    func testRegisteredOverrideDisablesBothMarks() throws {
        let samples = [Int16](repeating: 1_000, count: 2_400)
        let url = try makeWAV(samples: samples)
        defer { try? FileManager.default.removeItem(at: url) }
        let before = try Data(contentsOf: url)

        let marked = try AudioPublicationMarker.markStagedWAV(
            at: url,
            configuration: configuration,
            environment: ["QWENVOICE_DEBUG": "1", "QWENVOICE_MARKING": "off"],
            transform: { _ in XCTFail("transform must not run when disabled"); return [] }
        )
        XCTAssertFalse(marked)
        XCTAssertEqual(try Data(contentsOf: url), before, "disabled marking must not touch the file")
    }

    func testOverrideIsInertWithoutTheMasterGate() throws {
        // QWENVOICE_MARKING without QWENVOICE_DEBUG must not disable marking.
        let samples = [Int16](repeating: 500, count: 2_400)
        let url = try makeWAV(samples: samples)
        defer { try? FileManager.default.removeItem(at: url) }

        let marked = try AudioPublicationMarker.markStagedWAV(
            at: url,
            configuration: configuration,
            environment: ["QWENVOICE_MARKING": "off"],
            transform: { $0 }
        )
        XCTAssertTrue(marked, "the override is master-gated and inert on its own")
        XCTAssertTrue(try WAVProvenanceChunk.readInfoFields(fromWAVAt: url).keys.contains("ICMT"))
    }

    func testRefusesNonPCM16Targets() throws {
        let url = FileManager.default.temporaryDirectory
            .appendingPathComponent("marking-\(UUID().uuidString).bin")
        try Data("definitely not RIFF".utf8).write(to: url)
        defer { try? FileManager.default.removeItem(at: url) }
        XCTAssertThrowsError(
            try AudioPublicationMarker.markStagedWAV(
                at: url,
                configuration: configuration,
                environment: [:],
                transform: { $0 }
            )
        )
    }

    func testSampleCountChangeFailsClosed() throws {
        let url = try makeWAV(samples: [Int16](repeating: 100, count: 2_400))
        defer { try? FileManager.default.removeItem(at: url) }
        XCTAssertThrowsError(
            try AudioPublicationMarker.markStagedWAV(
                at: url,
                configuration: configuration,
                environment: [:],
                transform: { pcm in Array(pcm.dropLast()) }
            )
        )
    }
}
