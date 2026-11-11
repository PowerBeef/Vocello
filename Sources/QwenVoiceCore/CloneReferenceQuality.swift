import AVFoundation
import Foundation

/// What Vocello can tell about a clone reference before it conditions a take
/// (RF-51, G-08 to G-11).
///
/// One implementation serves enrollment, the saved-voice list, a one-off
/// reference in the Studio and the engine's own check, so the four cannot
/// disagree about a clip. Every check reads the reference as the user gave
/// it: audio preparation resamples to 24 kHz mono, so a check of the prepared
/// file can no longer see a narrow-band source.
///
/// The tokens are the `clone_reference_warnings` vocabulary;
/// `PreparedVoiceQualityWarning` owns their wording and which of them block.
public enum CloneReferenceQuality {
    public static let shortDurationToken = "reference_duration_short"
    public static let longDurationToken = "reference_duration_long"
    public static let excessiveDurationToken = "reference_duration_excessive"
    public static let unreadableToken = "reference_quality_unreadable"
    public static let nearSilenceToken = "reference_near_silence"
    public static let sourceRateLowToken = "reference_source_rate_low"
    public static let possibleClippingToken = "reference_possible_clipping"

    /// Duration tiers. They come from the hosted Qwen-TTS service's guidance,
    /// not from a documented limit of the open model: under 10 s is short,
    /// 30 to 60 s is long, and over 60 s is refused.
    public static let recommendedMinimumSeconds: Double = 10
    public static let recommendedMaximumSeconds: Double = 30
    public static let maximumSeconds: Double = 60

    /// A source sampled below 16 kHz carries less than 8 kHz of bandwidth
    /// (telephone audio is sampled at 8 kHz), and resampling to the model's
    /// 24 kHz cannot restore what was never recorded.
    public static let minimumSourceSampleRate: Double = 16_000

    /// -66 dBFS over the analyzed span: digital silence or a muted input. A
    /// quiet room alone measures well above it.
    static let nearSilenceRMS: Float = 0.0005

    /// A flat top: the signal held at the clip's own peak for 125 microseconds
    /// (three samples at 24 kHz, six at 48 kHz, never fewer than three), so
    /// the rule means the same at every sample rate. Relative to the peak, so
    /// a clip that was overdriven and then turned down still reads as
    /// clipped, and a loud clean clip does not.
    static let clippedRunSeconds: Double = 0.000_125
    static let minimumClippedRunLength = 3
    static let clippedRunPeakShare: Float = 0.999
    /// Calibrated on 476 licensed speech clips (16, 24 and 44.1 kHz, and the
    /// same clips resampled to 48 kHz): no clean clip reaches 0.5 flat tops
    /// per second (the highest is 0.43), while 89% of the same clips
    /// overdriven by 3 dB and 99% by 6 dB do. Two limits: a lossy re-encode
    /// smooths the flat tops, so clipping baked into an AAC or MP3 file is
    /// not detected, and a steady low tone touches its peak every cycle and
    /// reads as clipped, which speech does not do.
    static let clippedRunsPerSecond: Double = 0.5
    static let minimumClippedRuns = 3

    static func clippedRunLength(sampleRate: Double) -> Int {
        max(minimumClippedRunLength, Int((sampleRate * clippedRunSeconds).rounded()))
    }

    /// Only the opening of a long clip is analyzed; the engine refuses a
    /// reference longer than `maximumSeconds` whatever its signal.
    static let analyzedSeconds: Double = 30

    public struct Signal: Equatable, Sendable {
        public let peak: Float
        public let rms: Float
        public let clippedRuns: Int
        public let analyzedSeconds: Double

        public init(peak: Float, rms: Float, clippedRuns: Int, analyzedSeconds: Double) {
            self.peak = peak
            self.rms = rms
            self.clippedRuns = clippedRuns
            self.analyzedSeconds = analyzedSeconds
        }

        var isNearSilent: Bool { rms < CloneReferenceQuality.nearSilenceRMS }

        var isLikelyClipped: Bool {
            guard analyzedSeconds > 0, clippedRuns >= CloneReferenceQuality.minimumClippedRuns else {
                return false
            }
            return Double(clippedRuns) / analyzedSeconds >= CloneReferenceQuality.clippedRunsPerSecond
        }
    }

    /// The engine's refusal of a one-off reference that carries a blocking
    /// token. Path-free, like every description that can reach the CLI.
    public struct Rejection: LocalizedError, Equatable, Sendable {
        public let tokens: [String]

        public init(tokens: [String]) {
            self.tokens = tokens
        }

        public var errorDescription: String? {
            let reasons = tokens.compactMap(PreparedVoiceQualityWarning.headline(for:))
            return reasons.isEmpty ? "The reference clip cannot be used for cloning." : reasons.joined(separator: " ")
        }
    }

    public enum Depth: Sendable {
        /// The file's header only: duration and source sample rate. Cheap
        /// enough to run for every saved voice each time the list loads.
        case header
        /// The header and the signal of the clip's opening.
        case full
    }

    /// Warnings for the reference at `url`, blocking tokens first. Every
    /// surface measures this one rendering, the clip as the user gave it, so
    /// none of them can disagree with another about it.
    public static func warnings(forReferenceAt url: URL, depth: Depth = .full) -> [String] {
        guard let file = try? AVAudioFile(forReading: url) else { return [unreadableToken] }
        let sampleRate = file.fileFormat.sampleRate
        guard sampleRate > 0 else { return [unreadableToken] }
        var measured: Signal?
        if depth == .full {
            guard let signal = try? signal(of: file) else { return [unreadableToken] }
            measured = signal
        }
        return warnings(
            durationSeconds: Double(file.length) / sampleRate,
            sourceSampleRate: sampleRate,
            signal: measured
        )
    }

    /// The full check off the caller's actor, for a view that shows a
    /// one-off reference's warnings as soon as the clip is chosen.
    @concurrent
    public static func measuredWarnings(forReferenceAt url: URL) async -> [String] {
        warnings(forReferenceAt: url)
    }

    /// The rule itself, over measurements. `sourceSampleRate` is nil when the
    /// source's own rate is not known, and `signal` is nil when it was not
    /// measured; neither then contributes a warning.
    public static func warnings(
        durationSeconds: Double,
        sourceSampleRate: Double?,
        signal: Signal?
    ) -> [String] {
        var blocking: [String] = []
        var advisory: [String] = []
        if durationSeconds > maximumSeconds {
            blocking.append(excessiveDurationToken)
        } else if durationSeconds > recommendedMaximumSeconds {
            advisory.append(longDurationToken)
        } else if durationSeconds < recommendedMinimumSeconds {
            advisory.append(shortDurationToken)
        }
        if let signal, signal.isNearSilent {
            blocking.append(nearSilenceToken)
        }
        if let sourceSampleRate, sourceSampleRate < minimumSourceSampleRate {
            advisory.append(sourceRateLowToken)
        }
        // A silent clip has no peak to flatten against.
        if let signal, !signal.isNearSilent, signal.isLikelyClipped {
            advisory.append(possibleClippingToken)
        }
        return blocking + advisory
    }

    // MARK: - Signal

    static func signal(at url: URL) throws -> Signal {
        try signal(of: AVAudioFile(forReading: url))
    }

    /// Two bounded passes over the clip's opening: the first finds each
    /// channel's peak and the level, the second counts flat tops against that
    /// peak. Memory stays one chunk whatever the file's rate or length.
    static func signal(of file: AVAudioFile) throws -> Signal {
        let format = file.processingFormat
        let sampleRate = format.sampleRate
        let channels = Int(format.channelCount)
        guard sampleRate > 0, channels > 0 else {
            return Signal(peak: 0, rms: 0, clippedRuns: 0, analyzedSeconds: 0)
        }
        let frameLimit = min(file.length, AVAudioFramePosition(sampleRate * analyzedSeconds))
        guard frameLimit > 0 else {
            return Signal(peak: 0, rms: 0, clippedRuns: 0, analyzedSeconds: 0)
        }

        var level = LevelMeter(channelCount: channels)
        let measuredFrames = try forEachChunk(of: file, frameLimit: frameLimit) { channel, samples in
            level.measure(channel: channel, samples: samples)
        }
        var flatTops = FlatTopCounter(
            channelPeaks: level.peaks,
            runLength: clippedRunLength(sampleRate: sampleRate)
        )
        _ = try forEachChunk(of: file, frameLimit: frameLimit) { channel, samples in
            flatTops.count(channel: channel, samples: samples)
        }
        return Signal(
            peak: level.peak,
            rms: level.rms,
            clippedRuns: flatTops.runs,
            analyzedSeconds: Double(measuredFrames) / sampleRate
        )
    }

    private static let chunkFrames: AVAudioFrameCount = 32_768

    /// Reads `frameLimit` frames from the start in chunks, handing each
    /// channel's samples to `body`. Returns the frames actually read.
    private static func forEachChunk(
        of file: AVAudioFile,
        frameLimit: AVAudioFramePosition,
        _ body: (_ channel: Int, _ samples: [Float]) -> Void
    ) throws -> AVAudioFramePosition {
        guard let buffer = AVAudioPCMBuffer(pcmFormat: file.processingFormat, frameCapacity: chunkFrames) else {
            throw AudioPreparationError.conversionFailed("Could not create an analysis buffer for the clone reference.")
        }
        file.framePosition = 0
        var framesRead: AVAudioFramePosition = 0
        while framesRead < frameLimit {
            let wanted = AVAudioFrameCount(min(AVAudioFramePosition(chunkFrames), frameLimit - framesRead))
            buffer.frameLength = 0
            do {
                try file.read(into: buffer, frameCount: wanted)
            } catch {
                // A compressed file's length is an estimate: its decoder can
                // end a little early. That is the end of the clip, not a clip
                // that cannot be read, once anything was read at all.
                guard framesRead > 0 else { throw error }
                break
            }
            let frames = Int(buffer.frameLength)
            guard frames > 0 else { break }
            for channel in 0..<Int(buffer.format.channelCount) {
                guard let samples = unsafe buffer.floatChannelData?[channel] else { continue }
                body(channel, unsafe Array(UnsafeBufferPointer(start: samples, count: frames)))
            }
            framesRead += AVAudioFramePosition(frames)
        }
        return framesRead
    }

    /// Peak per channel and the level across all of them.
    struct LevelMeter {
        private(set) var peaks: [Float]
        private var sumOfSquares: Double = 0
        private var sampleCount = 0

        init(channelCount: Int) {
            peaks = Array(repeating: 0, count: channelCount)
        }

        var peak: Float { peaks.max() ?? 0 }

        var rms: Float {
            sampleCount > 0 ? Float((sumOfSquares / Double(sampleCount)).squareRoot()) : 0
        }

        mutating func measure(channel: Int, samples: [Float]) {
            guard peaks.indices.contains(channel) else { return }
            var peak = peaks[channel]
            var sum: Double = 0
            for value in samples {
                peak = max(peak, abs(value))
                sum += Double(value) * Double(value)
            }
            peaks[channel] = peak
            sumOfSquares += sum
            sampleCount += samples.count
        }
    }

    /// Counts runs of consecutive samples at a channel's peak. A run that
    /// spans two chunks is one run: the length in progress carries over.
    struct FlatTopCounter {
        private let thresholds: [Float?]
        private let runLength: Int
        private var runLengths: [Int]
        private(set) var runs = 0

        init(channelPeaks: [Float], runLength: Int) {
            self.runLength = runLength
            // A channel with no signal has no peak to flatten against.
            thresholds = channelPeaks.map {
                $0 > CloneReferenceQuality.nearSilenceRMS ? $0 * CloneReferenceQuality.clippedRunPeakShare : nil
            }
            runLengths = Array(repeating: 0, count: channelPeaks.count)
        }

        mutating func count(channel: Int, samples: [Float]) {
            guard thresholds.indices.contains(channel), let threshold = thresholds[channel] else { return }
            var length = runLengths[channel]
            for value in samples {
                if abs(value) >= threshold {
                    length += 1
                    // Counted once, when the run first reaches the length.
                    if length == runLength { runs += 1 }
                } else {
                    length = 0
                }
            }
            runLengths[channel] = length
        }
    }
}
