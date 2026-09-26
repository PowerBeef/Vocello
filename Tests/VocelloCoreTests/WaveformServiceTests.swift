import AVFoundation
import XCTest

/// MAC-17: waveform bars read in blocks, from mono and stereo files alike.
final class WaveformServiceTests: XCTestCase {
    private var root: URL!

    override func setUpWithError() throws {
        root = FileManager.default.temporaryDirectory
            .appendingPathComponent("WaveformServiceTests-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
    }

    override func tearDownWithError() throws {
        try? FileManager.default.removeItem(at: root)
    }

    /// Writes `frames` frames whose amplitude on every channel is
    /// `amplitude(frame, channel)`, as 16-bit PCM WAV.
    private func writeWAV(
        named name: String,
        channels: AVAudioChannelCount,
        frames: Int,
        amplitude: (Int, Int) -> Float
    ) throws -> URL {
        let url = root.appendingPathComponent(name)
        let settings: [String: Any] = [
            AVFormatIDKey: kAudioFormatLinearPCM,
            AVSampleRateKey: 24_000,
            AVNumberOfChannelsKey: channels,
            AVLinearPCMBitDepthKey: 16,
            AVLinearPCMIsFloatKey: false,
            AVLinearPCMIsBigEndianKey: false,
        ]
        let file = try AVAudioFile(forWriting: url, settings: settings)
        let format = file.processingFormat
        let buffer = try XCTUnwrap(AVAudioPCMBuffer(pcmFormat: format, frameCapacity: AVAudioFrameCount(frames)))
        buffer.frameLength = AVAudioFrameCount(frames)
        let data = try XCTUnwrap(buffer.floatChannelData)
        for channel in 0..<Int(channels) {
            for frame in 0..<frames {
                // A square wave at the given amplitude: its RMS is the amplitude.
                let sign: Float = frame.isMultiple(of: 2) ? 1 : -1
                data[channel][frame] = sign * amplitude(frame, channel)
            }
        }
        try file.write(from: buffer)
        return url
    }

    func testMonoRampRisesAndPeaksAtOne() throws {
        let frames = 24_000
        let url = try writeWAV(named: "ramp.wav", channels: 1, frames: frames) { frame, _ in
            Float(frame / 2_400 + 1) * 0.05
        }
        let bars = WaveformService.extractSamples(from: url, targetCount: 10)
        XCTAssertEqual(bars.count, 10)
        XCTAssertEqual(try XCTUnwrap(bars.last), 1, accuracy: 0.001)
        for (earlier, later) in zip(bars, bars.dropFirst()) {
            XCTAssertLessThan(earlier, later)
        }
    }

    func testStereoFilesDrawFromEveryChannel() throws {
        // Silent left channel, loud right channel: the old mono read failed on
        // stereo and returned no bars at all.
        let url = try writeWAV(named: "stereo.wav", channels: 2, frames: 12_000) { _, channel in
            channel == 1 ? 0.5 : 0
        }
        let bars = WaveformService.extractSamples(from: url, targetCount: 12)
        XCTAssertEqual(bars.count, 12)
        XCTAssertTrue(bars.allSatisfy { abs($0 - 1) < 0.001 })
    }

    func testAFileLongerThanOneReadBlockCoversEveryFrame() throws {
        // Two and a half read blocks, loud only in the final tenth: the last
        // bar must see it, so the read reached the end of the file.
        let frames = Int(WaveformService.readBlockFrames) * 5 / 2
        let url = try writeWAV(named: "long.wav", channels: 1, frames: frames) { frame, _ in
            frame >= frames * 9 / 10 ? 0.8 : 0.1
        }
        let bars = WaveformService.extractSamples(from: url, targetCount: 10)
        XCTAssertEqual(bars.count, 10)
        XCTAssertEqual(try XCTUnwrap(bars.last), 1, accuracy: 0.001)
        XCTAssertEqual(bars[0], 0.125, accuracy: 0.001)
    }

    func testAShortFileGivesOneBarPerFrameAndAnUnreadableFileNone() throws {
        let url = try writeWAV(named: "short.wav", channels: 1, frames: 4) { _, _ in 0.25 }
        XCTAssertEqual(WaveformService.extractSamples(from: url, targetCount: 120).count, 4)

        let text = root.appendingPathComponent("not-audio.wav")
        try Data("not audio".utf8).write(to: text)
        XCTAssertEqual(WaveformService.extractSamples(from: text), [])
    }
}
