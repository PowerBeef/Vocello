import AVFoundation
import Foundation
@testable import QwenVoiceCore
import XCTest

final class AtomicWAVPublicationTests: XCTestCase {
    func testOneShotWriterPublishesReadableFrameAccurateWAV() throws {
        let directory = FileManager.default.temporaryDirectory
            .appendingPathComponent("vocello-atomic-wav-\(UUID().uuidString)", isDirectory: true)
        let output = directory.appendingPathComponent("take.wav")
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: directory) }
        let samples = (0..<480).map { Int16(($0 % 31) * 100) }

        try AtomicPCM16WAVWriter.write(pcmSamples: samples, sampleRate: 24_000, outputURL: output)

        let audio = try AVAudioFile(forReading: output)
        XCTAssertEqual(audio.length, AVAudioFramePosition(samples.count))
        XCTAssertEqual(audio.fileFormat.sampleRate, 24_000)
        try assertRIFFWAVE(output)
        XCTAssertEqual(try FileManager.default.contentsOfDirectory(atPath: directory.path), ["take.wav"])
    }

    func testStreamingWriterKeepsPartialOutputHiddenUntilTerminalBarrier() throws {
        let directory = FileManager.default.temporaryDirectory
            .appendingPathComponent("vocello-stream-wav-\(UUID().uuidString)", isDirectory: true)
        let output = directory.appendingPathComponent("take.wav")
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: directory) }
        let first = Array(repeating: Int16(200), count: 240)
        let second = Array(repeating: Int16(-200), count: 240)

        let writer = try IncrementalPCM16WAVFileWriter(sampleRate: 24_000, outputURL: output)
        try writer.append(pcmSamples: first)
        try writer.append(pcmSamples: second)
        XCTAssertFalse(FileManager.default.fileExists(atPath: output.path))

        try writer.finish()

        let audio = try AVAudioFile(forReading: output)
        XCTAssertEqual(audio.length, 480)
        XCTAssertEqual(audio.fileFormat.sampleRate, 24_000)
        try assertRIFFWAVE(output)
        XCTAssertEqual(try FileManager.default.contentsOfDirectory(atPath: directory.path), ["take.wav"])
    }

    func testStreamingWriterCanValidateStagingBeforeAtomicPublication() throws {
        let directory = FileManager.default.temporaryDirectory
            .appendingPathComponent("vocello-staged-wav-\(UUID().uuidString)", isDirectory: true)
        let output = directory.appendingPathComponent("take.wav")
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: directory) }
        let writer = try IncrementalPCM16WAVFileWriter(sampleRate: 24_000, outputURL: output)
        try writer.append(pcmSamples: Array(repeating: Int16(500), count: 480))

        let stagingURL = try writer.finishStaging()
        XCTAssertFalse(FileManager.default.fileExists(atPath: output.path))
        XCTAssertTrue(FileManager.default.fileExists(atPath: stagingURL.path))
        XCTAssertEqual(try AVAudioFile(forReading: stagingURL).length, 480)

        try writer.publish()
        XCTAssertTrue(FileManager.default.fileExists(atPath: output.path))
        XCTAssertFalse(FileManager.default.fileExists(atPath: stagingURL.path))
    }

    func testPersistedWAVQCReadsWrittenFramesAndRetainsPreWriteInstability() throws {
        let directory = FileManager.default.temporaryDirectory
            .appendingPathComponent("vocello-persisted-qc-\(UUID().uuidString)", isDirectory: true)
        let output = directory.appendingPathComponent("take.wav")
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: directory) }

        let samples = (0..<24_000).map { index -> Int16 in
            let value = sin(2 * Double.pi * 440 * Double(index) / 24_000) * 0.1
            return Int16((value * Double(Int16.max)).rounded())
        }
        try AtomicPCM16WAVWriter.write(
            pcmSamples: samples,
            sampleRate: 24_000,
            outputURL: output
        )

        let persistedOnly = try PersistedWAVAudioQCAnalyzer.evaluate(url: output)
        XCTAssertEqual(persistedOnly.algorithmVersion, 5)
        XCTAssertEqual(persistedOnly.writtenOutputVerdict, .pass)

        var unstable = PCM16StreamLimiter()
        var discarded: [Int16] = []
        unstable.append([0.2, .nan, 1.2, -1.2, 0.2], into: &discarded)
        let combined = try StreamingExecutionContext.makePersistedWAVAudioQCReport(
            at: output,
            preWriteMetrics: unstable.metrics,
            expectedPauseCount: 0
        )
        XCTAssertEqual(combined.instabilityVerdict, .fail)
        XCTAssertEqual(combined.writtenOutputVerdict, .pass)
        XCTAssertEqual(combined.nonFiniteSamples, 1)
        XCTAssertEqual(combined.durationSeconds, 1, accuracy: 0.001)
    }

    func testPersistedWAVQCDerivesDCOffsetFromFile() throws {
        let directory = FileManager.default.temporaryDirectory
            .appendingPathComponent("vocello-persisted-dc-\(UUID().uuidString)", isDirectory: true)
        let output = directory.appendingPathComponent("take.wav")
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: directory) }

        try AtomicPCM16WAVWriter.write(
            pcmSamples: Array(repeating: Int16(3_200), count: 24_000),
            sampleRate: 24_000,
            outputURL: output
        )
        let report = try PersistedWAVAudioQCAnalyzer.evaluate(url: output)
        XCTAssertEqual(report.writtenOutputVerdict, .warn)
        XCTAssertGreaterThan(try XCTUnwrap(report.dcOffset), 0.09)
    }

    func testPersistedWAVQCKeepsSilenceRunAcrossBoundedReadBlocks() throws {
        let directory = FileManager.default.temporaryDirectory
            .appendingPathComponent("vocello-persisted-block-qc-\(UUID().uuidString)", isDirectory: true)
        let output = directory.appendingPathComponent("take.wav")
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: directory) }
        let audible = Array(repeating: Int16(4_000), count: 5_000)
        let silence = Array(repeating: Int16(0), count: 20_000)
        try AtomicPCM16WAVWriter.write(
            pcmSamples: audible + silence + audible,
            sampleRate: 24_000,
            outputURL: output
        )

        let report = try PersistedWAVAudioQCAnalyzer.evaluate(url: output)

        XCTAssertEqual(report.longestSilenceMS, 833, accuracy: 1)
        XCTAssertEqual(try XCTUnwrap(report.longestSilenceStartMS), 208, accuracy: 1)
        XCTAssertEqual(report.writtenOutputVerdict, .warn)
    }

    private func assertRIFFWAVE(_ url: URL) throws {
        let data = try Data(contentsOf: url, options: .mappedIfSafe)
        XCTAssertGreaterThanOrEqual(data.count, 12)
        XCTAssertEqual(String(decoding: data.prefix(4), as: UTF8.self), "RIFF")
        XCTAssertEqual(String(decoding: data.dropFirst(8).prefix(4), as: UTF8.self), "WAVE")
    }
}
