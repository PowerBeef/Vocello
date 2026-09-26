import Accelerate
import AVFoundation
import Foundation

/// Waveform bars for a take: the RMS level of `targetCount` equal spans of the
/// file, normalized to [0, 1].
///
/// MAC-17 / REPO-03: one copy for both apps (it was duplicated byte for byte in
/// the macOS and iOS service folders). The file is read in blocks of
/// `readBlockFrames`, so an hour-long take no longer loads hundreds of
/// megabytes at once, and every channel counts toward a span's level, so a
/// stereo file draws instead of failing to read into a mono buffer.
enum WaveformService {
    static let readBlockFrames: AVAudioFrameCount = 65_536

    static func extractSamples(from url: URL, targetCount: Int = 120) -> [Float] {
        guard targetCount > 0, let file = try? AVAudioFile(forReading: url) else { return [] }
        return extractSamples(from: file, targetCount: targetCount)
    }

    static func extractSamples(from file: AVAudioFile, targetCount: Int) -> [Float] {
        let totalFrames = file.length
        guard targetCount > 0, totalFrames > 0 else { return [] }
        // The processing format is deinterleaved Float32 with the file's own
        // channel count, whatever the file stores.
        let format = file.processingFormat
        let channelCount = Int(format.channelCount)
        guard channelCount > 0,
              let buffer = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: readBlockFrames) else {
            return []
        }

        let binCount = Int(min(Int64(targetCount), totalFrames))
        let bins = Int64(binCount)
        var sumOfSquares = [Double](repeating: 0, count: binCount)
        var frameCounts = [Int64](repeating: 0, count: binCount)
        var position: Int64 = 0
        file.framePosition = 0

        while position < totalFrames {
            do {
                try file.read(into: buffer, frameCount: readBlockFrames)
            } catch {
                return []
            }
            let frames = Int(buffer.frameLength)
            guard frames > 0, let channels = buffer.floatChannelData else { break }

            var offset = 0
            while offset < frames {
                let frame = position + Int64(offset)
                // Frame `f` belongs to bin `f * bins / totalFrames`; the bin ends
                // at the first frame of the next one.
                let bin = Int(min(frame * bins / totalFrames, bins - 1))
                let nextBinStart = (Int64(bin + 1) * totalFrames + bins - 1) / bins
                let span = max(1, Int(min(Int64(frames - offset), nextBinStart - frame)))
                var spanSquares: Float = 0
                for channel in 0..<channelCount {
                    var channelSquares: Float = 0
                    vDSP_svesq(channels[channel].advanced(by: offset), 1, &channelSquares, vDSP_Length(span))
                    spanSquares += channelSquares
                }
                sumOfSquares[bin] += Double(spanSquares) / Double(channelCount)
                frameCounts[bin] += Int64(span)
                offset += span
            }
            position += Int64(frames)
        }

        let levels = (0..<binCount).map { index -> Float in
            frameCounts[index] > 0 ? Float((sumOfSquares[index] / Double(frameCounts[index])).squareRoot()) : 0
        }
        let peak = levels.max() ?? 0
        return peak > 0 ? levels.map { $0 / peak } : levels
    }
}
