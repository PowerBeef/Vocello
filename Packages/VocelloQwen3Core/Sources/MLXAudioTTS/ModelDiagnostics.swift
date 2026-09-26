import Foundation

public protocol SpeechGenerationModelDiagnosticsProvider: AnyObject {
    var loadTimingsMS: [String: Int] { get }
    var loadBooleanFlags: [String: Bool] { get }
    var latestPreparationTimingsMS: [String: Int] { get }
    var latestPreparationBooleanFlags: [String: Bool] { get }
    var latestPreparationStringFlags: [String: String] { get }
    /// The engine introspection summary of the latest generation (AQ-04), nil
    /// before one runs or when the model does not produce it.
    var latestGenerationIntrospection: Qwen3GenerationIntrospectionSummary? { get }
    func resetPreparationDiagnostics()
}

public extension SpeechGenerationModelDiagnosticsProvider {
    var latestPreparationStringFlags: [String: String] {
        [:]
    }

    var latestGenerationIntrospection: Qwen3GenerationIntrospectionSummary? {
        nil
    }
}

/// What the talker's own signals said about one generation (AQ-04, audit
/// 2026-09-25, AQ-F09 and AQ-F49): codebook-0 token cycles, the per-step entropy
/// and EOS probability of the talker distribution, and the streaming seams.
/// Observational: no gate reads it. `scripts/lib/audio_qc_observations.py`
/// (`introspection_summary`) mirrors it on the shared fixtures, and every
/// constant is pinned to `config/audio-qc-stage0-observations.json`.
public struct Qwen3GenerationIntrospectionSummary: Sendable, Equatable {
    public static let algorithmVersion = 1

    /// Codebook-0 codec tokens observed (the EOS step is not a codec token).
    public let codecFrameCount: Int
    /// Longest run of one repeated token, in frames (1 once a frame exists).
    public let longestRepeatedTokenRunFrames: Int
    /// The longest exact cycle of period 2...32 (an n-gram said at least twice
    /// in a row): its period, the frames it covers, whole repeats and first frame.
    public let tokenCyclePeriod: Int?
    public let tokenCycleSpanFrames: Int?
    public let tokenCycleRepeats: Int?
    public let tokenCycleStartFrame: Int?
    /// Steps with a finite entropy; the mean, the 95th percentile (the upper edge
    /// of its 1/32-nat histogram bin) and the longest run at or above 4 nats.
    public let observedStepCount: Int
    public let entropyMeanNats: Double?
    public let entropyP95Nats: Double?
    public let longestHighEntropyRunSteps: Int
    /// EOS probability at the last step, its maximum and first step there, the
    /// first step at or above 0.5, and the steps at or above 0.5 that did not stop.
    public let eosProbabilityFinal: Double?
    public let eosProbabilityMax: Double?
    public let eosProbabilityMaxStep: Int?
    public let eosFirstLikelyStep: Int?
    public let eosLikelyStepsWithoutStop: Int
    /// Codec frames where a streamed chunk ended and the next began.
    public let seamCodecFrames: [Int]
}

/// Fixed-state accumulator behind `Qwen3GenerationIntrospectionSummary`.
///
/// The generate loop calls it once per step with values it already holds: the
/// sampled token id and two scalars evaluated with the step's own graph (a
/// graph compiled once per generation, so the step's GPU work grows by a few
/// fused kernels). Every host buffer here is allocated once at init (a
/// 32-token ring, 33 run counters, a 256-bin histogram, 256 seam slots), so an
/// observation allocates nothing, takes no lock and formats no string.
struct Qwen3GenerationIntrospector {
    static let maximumCyclePeriod = 32
    static let entropyHistogramBinsPerNat = 32
    static let entropyHistogramBins = 256
    static let highEntropyNats = 4.0
    static let likelyEOSProbability = 0.5
    static let maximumSeams = 256

    private var history: [Int32]
    private var historyHead = 0
    private var historyCount = 0
    private var runs: [Int32]
    private var codecFrameCount = 0
    private var longestConstantRun = 0
    private var cycleSpan = 0
    private var cyclePeriod = 0
    private var cycleStart = 0

    private var histogram: [Int32]
    private var entropySum = 0.0
    private var observedEntropies = 0
    private var highRun = 0
    private var longestHighRun = 0

    private var stepCount = 0
    private var eosFinal: Double?
    private var eosMaximum: Double?
    private var eosMaximumStep: Int?
    private var eosFirstLikelyStep: Int?
    private var eosLikelyWithoutStop = 0

    private var seamFrames: [Int]

    init() {
        history = [Int32](repeating: 0, count: Self.maximumCyclePeriod)
        runs = [Int32](repeating: 0, count: Self.maximumCyclePeriod + 1)
        histogram = [Int32](repeating: 0, count: Self.entropyHistogramBins)
        seamFrames = []
        seamFrames.reserveCapacity(Self.maximumSeams)
    }

    /// One codebook-0 codec token, in generation order. For each period p the
    /// run counts consecutive frames equal to the frame p earlier; the dominant
    /// cycle is the one covering the most frames (ties to the shortest period),
    /// so a stuck token counts as a run and never as a longer cycle.
    mutating func observeCodecToken(_ token: Int) {
        let value = Int32(truncatingIfNeeded: token)
        let limit = Self.maximumCyclePeriod
        var dominant = 0
        var dominantSpan = 0
        var period = 1
        while period <= limit {
            if historyCount >= period, history[(historyHead - period + limit) % limit] == value {
                runs[period] += 1
            } else {
                runs[period] = 0
            }
            let run = Int(runs[period])
            if run >= period, run + period > dominantSpan {
                dominant = period
                dominantSpan = run + period
            }
            period += 1
        }
        history[historyHead] = value
        historyHead = (historyHead + 1) % limit
        if historyCount < limit {
            historyCount += 1
        }
        if codecFrameCount == 0 {
            longestConstantRun = 1
        }
        if dominant == 1 {
            longestConstantRun = max(longestConstantRun, dominantSpan)
        } else if dominant >= 2, dominantSpan > cycleSpan {
            cycleSpan = dominantSpan
            cyclePeriod = dominant
            cycleStart = codecFrameCount - dominantSpan + 1
        }
        codecFrameCount += 1
    }

    /// One talker step: its entropy in nats and EOS probability, and whether the
    /// step sampled EOS.
    mutating func observeStep(entropy: Float, eosProbability: Float, stopped: Bool) {
        let nats = Double(entropy)
        if nats.isFinite {
            observedEntropies += 1
            entropySum += nats
            let scaled = (nats * Double(Self.entropyHistogramBinsPerNat)).rounded(.down)
            let bin = Int(min(Double(Self.entropyHistogramBins - 1), max(0, scaled)))
            histogram[bin] += 1
            highRun = nats >= Self.highEntropyNats ? highRun + 1 : 0
            longestHighRun = max(longestHighRun, highRun)
        } else {
            highRun = 0
        }
        let probability = Double(eosProbability)
        if probability.isFinite {
            eosFinal = probability
            if probability > (eosMaximum ?? -Double.infinity) {
                eosMaximum = probability
                eosMaximumStep = stepCount
            }
            if probability >= Self.likelyEOSProbability {
                if eosFirstLikelyStep == nil {
                    eosFirstLikelyStep = stepCount
                }
                if !stopped {
                    eosLikelyWithoutStop += 1
                }
            }
        }
        stepCount += 1
    }

    /// A streamed chunk ended after this many codec frames.
    mutating func recordSeam(codecFrame: Int) {
        guard seamFrames.count < Self.maximumSeams else { return }
        seamFrames.append(codecFrame)
    }

    func summary() -> Qwen3GenerationIntrospectionSummary {
        var p95: Double?
        if observedEntropies > 0 {
            let rank = (observedEntropies * 95 + 99) / 100
            var cumulative = 0
            for bin in 0 ..< Self.entropyHistogramBins {
                cumulative += Int(histogram[bin])
                if cumulative >= rank {
                    p95 = Double(bin + 1) / Double(Self.entropyHistogramBinsPerNat)
                    break
                }
            }
        }
        let seams = Array(Set(seamFrames.filter { $0 > 0 && $0 < codecFrameCount }))
            .sorted()
            .prefix(Self.maximumSeams)
        let hasCycle = cyclePeriod >= 2
        return Qwen3GenerationIntrospectionSummary(
            codecFrameCount: codecFrameCount,
            longestRepeatedTokenRunFrames: longestConstantRun,
            tokenCyclePeriod: hasCycle ? cyclePeriod : nil,
            tokenCycleSpanFrames: hasCycle ? cycleSpan : nil,
            tokenCycleRepeats: hasCycle ? cycleSpan / cyclePeriod : nil,
            tokenCycleStartFrame: hasCycle ? cycleStart : nil,
            observedStepCount: observedEntropies,
            entropyMeanNats: Self.rounded(observedEntropies > 0 ? entropySum / Double(observedEntropies) : nil),
            entropyP95Nats: p95,
            longestHighEntropyRunSteps: longestHighRun,
            eosProbabilityFinal: Self.rounded(eosFinal),
            eosProbabilityMax: Self.rounded(eosMaximum),
            eosProbabilityMaxStep: eosMaximumStep,
            eosFirstLikelyStep: eosFirstLikelyStep,
            eosLikelyStepsWithoutStop: eosLikelyWithoutStop,
            seamCodecFrames: Array(seams)
        )
    }

    /// Half away from zero to four decimals, as the Python mirror rounds; never -0.
    static func rounded(_ value: Double?) -> Double? {
        guard let value, value.isFinite else { return nil }
        let magnitude = (abs(value) * 10_000 + 0.5).rounded(.down) / 10_000
        return value < 0 && magnitude != 0 ? -magnitude : magnitude
    }
}
