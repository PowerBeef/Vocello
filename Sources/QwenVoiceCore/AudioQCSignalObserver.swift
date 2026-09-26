import Accelerate
import Foundation

/// Stage 0 observational signal measures (AQ-04, audit 2026-09-25, AQ-F08 to
/// AQ-F12 and AQ-F49). The persisted-WAV Fast QC pass feeds this observer the
/// exact samples it verifies; `finish()` yields `AudioQCReport.signal`.
///
/// Observational: no flag, verdict or Fast QC version reads these measures.
/// They join QC v8 additively (decision 8(a): the M6 gate baseline binds v8),
/// and one gates only after a qualified record under the threshold-change
/// authority. Every constant is pinned to
/// `config/audio-qc-stage0-observations.json` by
/// `AudioQCSignalObservationTests`, and the float64 mirror
/// `scripts/lib/audio_qc_observations.py` scores the same shared fixtures.
///
/// Bounded and deterministic: fixed scratch per observer, per-block
/// temporaries, and one scalar per 10 ms frame, 100 ms loudness sub-block and
/// 40 ms feature frame (16 bands), so a two-minute take holds well under
/// 1 MB. The FFT, K-weighting and true-peak filters run through Accelerate;
/// every other loop walks unsafe pointers so the unoptimized development build
/// stays inside the Stage 0 budget.
final class AudioQCSignalObserver {
    enum Constants {
        static let algorithmVersion = AudioQCSignalObservations.currentAlgorithmVersion
        // BS.1770-4 K-weighting from its analog prototype (libebur128's design).
        static let shelfFrequencyHz = 1681.974450955533
        static let shelfGainDB = 3.999843853973347
        static let shelfQ = 0.7071752369554196
        static let shelfBandwidthExponent = 0.4996667741545416
        static let highPassFrequencyHz = 38.13547087602444
        static let highPassQ = 0.5003270373238773
        // BS.1770-4 gating and EBU Tech 3342 loudness range.
        static let loudnessOffsetLU = -0.691
        static let loudnessSubBlocksPerSecond = 10
        static let loudnessBlockSubBlocks = 4
        static let shortTermSubBlocks = 30
        static let rangeHopSubBlocks = 10
        static let absoluteGateLUFS = -70.0
        static let relativeGateLU = -10.0
        static let rangeRelativeGateLU = -20.0
        static let rangeLowQuantile = 0.10
        static let rangeHighQuantile = 0.95
        // 4x true peak: a 49-tap Hann-windowed sinc (libebur128's design).
        static let truePeakOversampling = 4
        static let truePeakTaps = 49
        static let truePeakCoefficientFloor = 1e-6
        // 10 ms analysis frames, the noise floor and WADA-SNR.
        static let framesPerSecond = 100
        static let noiseFloorQuantileTenths = 1
        static let noiseFloorLevelFloorDBFS = -120.0
        static let wadaMagnitudeGridSteps = 32_768
        // STFT: periodic Hann, one frame per 10 ms.
        static let fftSize = 512
        static let fftSizeAboveRate = 1_024
        static let fftSizeRateLimit = 25_600
        static let minimumSpectralSampleRate = 16_000
        static let spectralPowerFloor = 1e-10
        static let activeMeanSquare = 1e-6
        static let fluxEventThresholdDB = 10.0
        static let fluxClusterGapFrames = 5
        static let bandwidthThresholdDB = 50.0
        static let bandwidthLTASFloor = 1e-20
        // The tokenizer's 12.5 Hz frame rate is one period every 8 frames.
        static let modulationFrequencyHz = 12.5
        static let modulationPeriodFrames = 8
        static let seamHalfWindowFrames = 1
        static let seamSigmaFloor = 1.0 / 32_768.0
        // Self-similarity repetition stripe over 40 ms frames of 16 log bands.
        static let repetitionPoolFrames = 4
        static let repetitionBandEdgesAt512 = [2, 3, 4, 5, 7, 9, 12, 17, 23, 31, 41, 56, 76, 103, 140, 189, 257]
        static let repetitionCosineThreshold = 0.95
        static let repetitionMinimumLagFrames = 5
        static let repetitionMaximumLagFrames = 375
        static let repetitionMinimumStripeFrames = 15
        static let repetitionMinimumChangingFrames = 2
        static let repetitionFeatureNormFloor = 1e-6
        static let roundingDecimals = 4
        /// G(SNR) of Kim and Stern's WADA model (Gamma alpha 0.4) at -20...100 dB,
        /// derived by quadrature (`wada_gamma_table` in the Python mirror).
        static let wadaGammaSNRDB: [Double] = (-20 ... 100).map { Double($0) }
        static let wadaGammaG: [Double] = [
            0.4094347, 0.409459496, 0.409497617, 0.409555847, 0.409644126, 0.409776799,
            0.409974221, 0.410264737, 0.410686999, 0.411292521, 0.412148283, 0.413339099,
            0.41496936, 0.417163742, 0.420066442, 0.423838601, 0.42865372, 0.434691104,
            0.442127643, 0.451128493, 0.46183744, 0.474367868, 0.488795204, 0.505151617,
            0.523423454, 0.543551597, 0.565434569, 0.588933952, 0.613881462, 0.640086948,
            0.667346607, 0.6954508, 0.724191011, 0.753365655, 0.782784622, 0.812272543,
            0.84167088, 0.870839006, 0.899654447, 0.928012487, 0.955825296, 0.983020751,
            1.009541065, 1.035341331, 1.060388054, 1.084657721, 1.108135456, 1.130813771,
            1.152691435, 1.173772454, 1.194065173, 1.213581479, 1.232336122, 1.25034611,
            1.267630205, 1.284208488, 1.300101986, 1.31533237, 1.329921687, 1.343892154,
            1.357265974, 1.370065193, 1.382311582, 1.394026546, 1.405231043, 1.415945535,
            1.426189936, 1.435983585, 1.445345224, 1.454292981, 1.462844368, 1.471016274,
            1.478824971, 1.486286121, 1.49341478, 1.500225419, 1.506731927, 1.512947635,
            1.518885326, 1.524557252, 1.529975155, 1.535150281, 1.540093396, 1.544814807,
            1.549324376, 1.553631541, 1.557745328, 1.561674368, 1.565426917, 1.569010866,
            1.57243376, 1.575702811, 1.578824911, 1.581806647, 1.584654313, 1.587373924,
            1.589971227, 1.592451713, 1.594820627, 1.59708298, 1.599243561, 1.601306941,
            1.60327749, 1.60515938, 1.606956597, 1.608672948, 1.61031207, 1.611877434,
            1.61337236, 1.614800014, 1.616163423, 1.617465478, 1.618708937, 1.619896437,
            1.621030496, 1.622113519, 1.623147801, 1.624135536, 1.625078819, 1.625979649,
            1.626839937,
        ]
    }

    /// 12.5 Hz at 100 frames per second: the eight phases of one period, exact.
    private static let halfRootTwo = 0.7071067811865476
    private static let modulationCosine: [Double] = [
        1, halfRootTwo, 0, -halfRootTwo, -1, -halfRootTwo, 0, halfRootTwo,
    ]
    private static let modulationSine: [Double] = [
        0, halfRootTwo, 1, halfRootTwo, 0, -halfRootTwo, -1, -halfRootTwo,
    ]

    private let sampleRate: Int
    private var processedSamples = 0
    private var samplePeak = 0.0
    private var magnitudeHistogram: [Int]

    // Loudness.
    private let subBlockLength: Int
    private var biquadSetup: vDSP_biquad_SetupD?
    private var biquadDelay = [Double](repeating: 0, count: 6)
    private var subBlockSum = 0.0
    private var subBlockFill = 0
    private var subBlockMeanSquares: [Double] = []

    // True peak: per phase, the 13 taps reversed for correlation, and the 12
    // samples before the current block.
    private let truePeakFilters: [[Double]]
    private var truePeakHistory: [Double]
    private var truePeakMaximum = 0.0

    // 10 ms frames.
    private let hop: Int
    private var frameSum = 0.0
    private var frameFill = 0
    private var frameRMS: [Double] = []

    // STFT.
    private let fftSize: Int
    private let log2FFTSize: vDSP_Length
    private var fftSetup: FFTSetupD?
    private let window: [Double]
    private let windowEnergy: Double
    private let bandEdges: [Int]
    private var pending: [Double] = []
    private var stftFrameIndex = 0
    private var windowed: [Double]
    private var realParts: [Double]
    private var imaginaryParts: [Double]
    private var power: [Double]
    private var logInput: [Double]
    private var logOutput: [Double]
    private var previousLog: [Double]
    private var hasPreviousLog = false
    private var fluxEventCount = 0
    private var lastFluxFrame: Int?
    private var ltas: [Double]
    private var ltasFrames = 0
    private var bandAccumulator: [Double]
    private var pooledSquare = 0.0
    private var poolFill = 0
    private var featuresByBand: [[Double]]
    private var featureActive: [Bool] = []

    // Streaming seams: sorted unique sample offsets and their window sums.
    private let seams: [Int]
    private let seamHalfWindow: Int
    private var seamSum: [Double]
    private var seamSquares: [Double]
    private var seamNeighbours: [Int]
    private var seamCenter: [Double]
    private var seamHasCenter: [Bool]
    private var firstOpenSeam = 0
    private var lastSample = 0.0

    init(sampleRate: Int, seamFrameOffsets: [Int] = []) {
        let rate = max(0, sampleRate)
        self.sampleRate = rate
        magnitudeHistogram = [Int](repeating: 0, count: Constants.wadaMagnitudeGridSteps + 1)

        let subBlock = rate > 0 && rate % Constants.loudnessSubBlocksPerSecond == 0
            ? rate / Constants.loudnessSubBlocksPerSecond
            : 0
        subBlockLength = subBlock
        biquadSetup = subBlock > 0
            ? vDSP_biquad_CreateSetupD(AudioQCSignalObserver.kWeightingSections(sampleRate: rate), 2)
            : nil
        let filters = AudioQCSignalObserver.reversedTruePeakTaps()
        truePeakFilters = filters
        truePeakHistory = [Double](repeating: 0, count: max(0, (filters.first?.count ?? 1) - 1))

        let frameHop = rate > 0 && rate % Constants.framesPerSecond == 0 ? rate / Constants.framesPerSecond : 0
        hop = frameHop
        let spectral = frameHop > 0 && rate >= Constants.minimumSpectralSampleRate
        let size = spectral
            ? (rate <= Constants.fftSizeRateLimit ? Constants.fftSize : Constants.fftSizeAboveRate)
            : 0
        fftSize = size
        let half = size / 2
        let log2n = size > 0 ? vDSP_Length(Int(log2(Double(size)).rounded())) : 0
        log2FFTSize = log2n
        fftSetup = size > 0 ? vDSP_create_fftsetupD(log2n, FFTRadix(kFFTRadix2)) : nil
        let periodicHann = (0 ..< size).map { 0.5 - 0.5 * cos(2 * Double.pi * Double($0) / Double(size)) }
        window = periodicHann
        windowEnergy = periodicHann.reduce(0.0) { $0 + $1 * $1 }
        let scale = max(1, size / 512)
        // Bin edges scale with the FFT; the last band always ends past the Nyquist bin.
        bandEdges = Constants.repetitionBandEdgesAt512.dropLast().map { $0 * scale } + [half + 1]
        windowed = [Double](repeating: 0, count: size)
        realParts = [Double](repeating: 0, count: half)
        imaginaryParts = [Double](repeating: 0, count: half)
        power = [Double](repeating: 0, count: size > 0 ? half + 1 : 0)
        logInput = [Double](repeating: 0, count: max(0, half - 1))
        logOutput = [Double](repeating: 0, count: max(0, half - 1))
        previousLog = [Double](repeating: 0, count: max(0, half - 1))
        ltas = [Double](repeating: 0, count: size > 0 ? half + 1 : 0)
        let bands = Constants.repetitionBandEdgesAt512.count - 1
        bandAccumulator = [Double](repeating: 0, count: bands)
        featuresByBand = [[Double]](repeating: [], count: bands)

        let sortedSeams = Array(Set(seamFrameOffsets.filter { $0 >= 1 })).sorted()
        seams = sortedSeams
        seamHalfWindow = frameHop * Constants.seamHalfWindowFrames
        seamSum = [Double](repeating: 0, count: sortedSeams.count)
        seamSquares = [Double](repeating: 0, count: sortedSeams.count)
        seamNeighbours = [Int](repeating: 0, count: sortedSeams.count)
        seamCenter = [Double](repeating: 0, count: sortedSeams.count)
        seamHasCenter = [Bool](repeating: false, count: sortedSeams.count)
    }

    deinit {
        if let biquadSetup {
            vDSP_biquad_DestroySetupD(biquadSetup)
        }
        if let fftSetup {
            vDSP_destroy_fftsetupD(fftSetup)
        }
    }

    /// (b0, b1, b2, a1, a2) of the K-weighting shelf, then its high-pass, at this rate.
    static func kWeightingSections(sampleRate: Int) -> [Double] {
        let rate = Double(sampleRate)
        var k = tan(Double.pi * Constants.shelfFrequencyHz / rate)
        var q = Constants.shelfQ
        let vh = pow(10.0, Constants.shelfGainDB / 20.0)
        let vb = pow(vh, Constants.shelfBandwidthExponent)
        let a0 = 1.0 + k / q + k * k
        let shelf = [
            (vh + vb * k / q + k * k) / a0,
            2.0 * (k * k - vh) / a0,
            (vh - vb * k / q + k * k) / a0,
            2.0 * (k * k - 1.0) / a0,
            (1.0 - k / q + k * k) / a0,
        ]
        k = tan(Double.pi * Constants.highPassFrequencyHz / rate)
        q = Constants.highPassQ
        let d = 1.0 + k / q + k * k
        let highPass = [1.0, -2.0, 1.0, 2.0 * (k * k - 1.0) / d, (1.0 - k / q + k * k) / d]
        return shelf + highPass
    }

    /// Per-phase interpolator taps h[phase][delay], delay 0...12. Phase 0 is the
    /// input delayed by six samples; the coefficient floor drops sinc zeros.
    static func truePeakTaps() -> [[Double]] {
        let taps = Constants.truePeakTaps
        let factor = Constants.truePeakOversampling
        let center = Double(taps - 1) / 2
        let delays = (taps + factor - 1) / factor
        var phases = [[Double]](repeating: [Double](repeating: 0, count: delays), count: factor)
        for j in 0 ..< taps {
            let m = Double(j) - center
            var c = m == 0 ? 1.0 : sin(m * Double.pi / Double(factor)) / (m * Double.pi / Double(factor))
            c *= 0.5 * (1.0 - cos(2.0 * Double.pi * Double(j) / Double(taps - 1)))
            if abs(c) > Constants.truePeakCoefficientFloor {
                phases[j % factor][j / factor] = c
            }
        }
        return phases
    }

    /// The taps reversed, as `vDSP_convD` correlates.
    private static func reversedTruePeakTaps() -> [[Double]] {
        truePeakTaps().map { Array($0.reversed()) }
    }

    /// Feed the next persisted block, in order. Non-finite values count as zero.
    func append(_ samples: [Float]) {
        let count = samples.count
        guard count > 0 else { return }
        var input = [Double](repeating: 0, count: count)
        samples.withUnsafeBufferPointer { source in
            input.withUnsafeMutableBufferPointer { destination in
                var index = 0
                while index < count {
                    let value = source[index]
                    destination[index] = value.isFinite ? Double(value) : 0
                    index += 1
                }
            }
        }
        input.withUnsafeBufferPointer { block in
            observeMagnitudes(block)
            observeLoudness(block)
            observeTruePeak(block)
            observeFrames(block)
            observeSeams(block)
            observeSpectrum(block)
        }
        processedSamples += count
        lastSample = input[count - 1]
    }

    private func observeMagnitudes(_ block: UnsafeBufferPointer<Double>) {
        let steps = Double(Constants.wadaMagnitudeGridSteps)
        let cap = Constants.wadaMagnitudeGridSteps
        var peak = samplePeak
        magnitudeHistogram.withUnsafeMutableBufferPointer { histogram in
            var index = 0
            while index < block.count {
                let magnitude = abs(block[index])
                if magnitude > peak { peak = magnitude }
                // Full scale and above share the top bin; the cap also keeps the
                // conversion to Int in range for any finite input.
                let bin = magnitude >= 1 ? cap : Int((magnitude * steps + 0.5).rounded(.down))
                histogram[bin] += 1
                index += 1
            }
        }
        samplePeak = peak
    }

    private func observeLoudness(_ block: UnsafeBufferPointer<Double>) {
        guard let setup = biquadSetup, subBlockLength > 0, let base = block.baseAddress else { return }
        var weighted = [Double](repeating: 0, count: block.count)
        weighted.withUnsafeMutableBufferPointer { output in
            biquadDelay.withUnsafeMutableBufferPointer { delay in
                vDSP_biquadD(setup, delay.baseAddress!, base, 1, output.baseAddress!, 1, vDSP_Length(block.count))
            }
        }
        var sum = subBlockSum
        var fill = subBlockFill
        let length = subBlockLength
        weighted.withUnsafeBufferPointer { output in
            var index = 0
            while index < output.count {
                let value = output[index]
                sum += value * value
                fill += 1
                if fill == length {
                    subBlockMeanSquares.append(sum / Double(length))
                    sum = 0
                    fill = 0
                }
                index += 1
            }
        }
        subBlockSum = sum
        subBlockFill = fill
    }

    private func observeTruePeak(_ block: UnsafeBufferPointer<Double>) {
        let historyLength = truePeakHistory.count
        let count = block.count
        var extended = truePeakHistory
        extended.append(contentsOf: block)
        var output = [Double](repeating: 0, count: count)
        var maximum = truePeakMaximum
        extended.withUnsafeBufferPointer { signal in
            output.withUnsafeMutableBufferPointer { result in
                for filter in truePeakFilters {
                    filter.withUnsafeBufferPointer { taps in
                        vDSP_convD(
                            signal.baseAddress!, 1,
                            taps.baseAddress!, 1,
                            result.baseAddress!, 1,
                            vDSP_Length(count), vDSP_Length(taps.count)
                        )
                    }
                    var magnitude = 0.0
                    vDSP_maxmgvD(result.baseAddress!, 1, &magnitude, vDSP_Length(count))
                    if magnitude > maximum { maximum = magnitude }
                }
            }
        }
        truePeakMaximum = maximum
        truePeakHistory = Array(extended[(extended.count - historyLength)...])
    }

    private func observeFrames(_ block: UnsafeBufferPointer<Double>) {
        guard hop > 0 else { return }
        var sum = frameSum
        var fill = frameFill
        var index = 0
        while index < block.count {
            let value = block[index]
            sum += value * value
            fill += 1
            if fill == hop {
                frameRMS.append((sum / Double(hop)).squareRoot())
                sum = 0
                fill = 0
            }
            index += 1
        }
        frameSum = sum
        frameFill = fill
    }

    private func observeSeams(_ block: UnsafeBufferPointer<Double>) {
        guard seamHalfWindow > 0, !seams.isEmpty else { return }
        let blockStart = processedSamples
        let blockEnd = blockStart + block.count
        while firstOpenSeam < seams.count, seams[firstOpenSeam] + seamHalfWindow < blockStart {
            firstOpenSeam += 1
        }
        var seamIndex = firstOpenSeam
        while seamIndex < seams.count {
            let seam = seams[seamIndex]
            let low = max(1, seam - seamHalfWindow)
            if low >= blockEnd { break }
            let high = seam + seamHalfWindow
            var position = max(low, blockStart)
            let last = min(high, blockEnd - 1)
            while position <= last {
                let current = block[position - blockStart]
                let previous = position == blockStart ? lastSample : block[position - blockStart - 1]
                let step = abs(current - previous)
                if position == seam {
                    seamCenter[seamIndex] = step
                    seamHasCenter[seamIndex] = true
                } else {
                    seamSum[seamIndex] += step
                    seamSquares[seamIndex] += step * step
                    seamNeighbours[seamIndex] += 1
                }
                position += 1
            }
            seamIndex += 1
        }
    }

    private func observeSpectrum(_ block: UnsafeBufferPointer<Double>) {
        guard fftSize > 0, fftSetup != nil else { return }
        pending.append(contentsOf: block)
        var start = 0
        while pending.count - start >= fftSize {
            pending.withUnsafeBufferPointer { samples in
                analyzeFrame(samples.baseAddress! + start)
            }
            start += hop
        }
        if start > 0 {
            pending.removeFirst(start)
        }
    }

    private func analyzeFrame(_ frame: UnsafePointer<Double>) {
        guard let setup = fftSetup else { return }
        let size = fftSize
        let half = size / 2
        var squares = 0.0
        windowed.withUnsafeMutableBufferPointer { output in
            window.withUnsafeBufferPointer { taper in
                var index = 0
                while index < size {
                    let value = frame[index] * taper[index]
                    output[index] = value
                    squares += value * value
                    index += 1
                }
            }
        }
        let meanSquare = squares / windowEnergy
        let energy = windowEnergy

        // Forward real FFT; vDSP returns twice the DFT and packs the Nyquist
        // term into the imaginary part of bin 0.
        windowed.withUnsafeBufferPointer { input in
            realParts.withUnsafeMutableBufferPointer { real in
                imaginaryParts.withUnsafeMutableBufferPointer { imaginary in
                    var index = 0
                    while index < half {
                        real[index] = input[2 * index]
                        imaginary[index] = input[2 * index + 1]
                        index += 1
                    }
                    var split = DSPDoubleSplitComplex(realp: real.baseAddress!, imagp: imaginary.baseAddress!)
                    vDSP_fft_zripD(setup, &split, 1, log2FFTSize, FFTDirection(kFFTDirection_Forward))
                    power.withUnsafeMutableBufferPointer { spectrum in
                        let dc = real[0] * 0.5
                        let nyquist = imaginary[0] * 0.5
                        spectrum[0] = dc * dc / energy
                        spectrum[half] = nyquist * nyquist / energy
                        var bin = 1
                        while bin < half {
                            let re = real[bin] * 0.5
                            let im = imaginary[bin] * 0.5
                            spectrum[bin] = (re * re + im * im) / energy
                            bin += 1
                        }
                    }
                }
            }
        }

        observeFlux(frameIndex: stftFrameIndex)
        if meanSquare >= Constants.activeMeanSquare {
            power.withUnsafeBufferPointer { spectrum in
                ltas.withUnsafeMutableBufferPointer { average in
                    var bin = 0
                    while bin <= half {
                        average[bin] += spectrum[bin]
                        bin += 1
                    }
                }
            }
            ltasFrames += 1
        }
        observeFeatures(meanSquare: meanSquare)
        stftFrameIndex += 1
    }

    private func observeFlux(frameIndex: Int) {
        let bins = logInput.count
        guard bins > 0 else { return }
        power.withUnsafeBufferPointer { spectrum in
            logInput.withUnsafeMutableBufferPointer { input in
                var index = 0
                while index < bins {
                    input[index] = max(spectrum[index + 1], Constants.spectralPowerFloor)
                    index += 1
                }
            }
        }
        var count = Int32(bins)
        logInput.withUnsafeBufferPointer { input in
            logOutput.withUnsafeMutableBufferPointer { output in
                vvlog10(output.baseAddress!, input.baseAddress!, &count)
            }
        }
        var rise = 0.0
        let hadPrevious = hasPreviousLog
        logOutput.withUnsafeBufferPointer { current in
            previousLog.withUnsafeMutableBufferPointer { previous in
                var index = 0
                while index < bins {
                    let difference = current[index] - previous[index]
                    if difference > 0 { rise += difference }
                    previous[index] = current[index]
                    index += 1
                }
            }
        }
        hasPreviousLog = true
        guard hadPrevious else { return }
        let flux = 10.0 * rise / Double(bins)
        guard flux >= Constants.fluxEventThresholdDB else { return }
        // A rising frame within the cluster gap of the last one continues its event.
        let continuesEvent = lastFluxFrame.map { frameIndex - $0 <= Constants.fluxClusterGapFrames } ?? false
        if !continuesEvent {
            fluxEventCount += 1
        }
        lastFluxFrame = frameIndex
    }

    private func observeFeatures(meanSquare: Double) {
        let bands = bandAccumulator.count
        power.withUnsafeBufferPointer { spectrum in
            bandEdges.withUnsafeBufferPointer { edges in
                bandAccumulator.withUnsafeMutableBufferPointer { accumulator in
                    var band = 0
                    while band < bands {
                        var sum = 0.0
                        var bin = edges[band]
                        while bin < edges[band + 1] {
                            sum += spectrum[bin]
                            bin += 1
                        }
                        accumulator[band] += sum / Double(edges[band + 1] - edges[band])
                        band += 1
                    }
                }
            }
        }
        pooledSquare += meanSquare
        poolFill += 1
        guard poolFill == Constants.repetitionPoolFrames else { return }

        let pool = Double(Constants.repetitionPoolFrames)
        var levels = [Double](repeating: 0, count: bands)
        var levelSum = 0.0
        for band in 0 ..< bands {
            let level = 10.0 * log10(max(bandAccumulator[band] / pool, Constants.spectralPowerFloor))
            levels[band] = level
            levelSum += level
        }
        let mean = levelSum / Double(bands)
        var normSquared = 0.0
        for band in 0 ..< bands {
            levels[band] -= mean
            normSquared += levels[band] * levels[band]
        }
        let norm = normSquared.squareRoot()
        let active = pooledSquare / pool >= Constants.activeMeanSquare
            && norm >= Constants.repetitionFeatureNormFloor
        for band in 0 ..< bands {
            featuresByBand[band].append(active ? levels[band] / norm : 0)
            bandAccumulator[band] = 0
        }
        featureActive.append(active)
        pooledSquare = 0
        poolFill = 0
    }

    /// The observations for every sample appended so far.
    func finish() -> AudioQCSignalObservations {
        let loudness = loudnessMeasures()
        let truePeak = max(samplePeak, truePeakMaximum)
        let frameMeasures = frameLevelMeasures()
        let spectral = spectralMeasures()
        let seam = seamMeasures()
        return AudioQCSignalObservations(
            algorithmVersion: Constants.algorithmVersion,
            integratedLoudnessLUFS: Self.rounded(loudness.integrated),
            shortTermLoudnessMaxLUFS: Self.rounded(loudness.shortTermMaximum),
            loudnessRangeLU: Self.rounded(loudness.range),
            truePeakDBTP: Self.rounded(truePeak > 0 ? 20 * log10(truePeak) : nil),
            noiseFloorDBFS: Self.rounded(frameMeasures.noiseFloor),
            wadaSNRDB: Self.rounded(wadaSNR()),
            effectiveBandwidthHz: Self.rounded(spectral.bandwidth),
            spectralFluxEventCount: spectral.enabled ? fluxEventCount : nil,
            spectralFluxEventsPerSecond: Self.rounded(spectral.enabled ? spectral.eventsPerSecond : nil),
            codecFrameModulationIndex: Self.rounded(frameMeasures.modulation),
            seamCount: seam.count,
            seamDiscontinuityMaxZ: Self.rounded(seam.maximumZ),
            seamDiscontinuityMaxZStartMS: seam.startMS,
            repetitionStripeLongestMS: spectral.stripeLongestMS,
            repetitionStripeLagMS: spectral.stripeLagMS,
            repetitionStripeCount: spectral.stripeCount
        )
    }

    /// Half away from zero to four decimals, as the Python mirror rounds; never -0.
    static func rounded(_ value: Double?) -> Double? {
        guard let value, value.isFinite else { return nil }
        let scale = pow(10.0, Double(Constants.roundingDecimals))
        let magnitude = (abs(value) * scale + 0.5).rounded(.down) / scale
        return value < 0 && magnitude != 0 ? -magnitude : magnitude
    }

    private func loudnessMeasures() -> (integrated: Double?, shortTermMaximum: Double?, range: Double?) {
        let sub = subBlockMeanSquares
        let count = sub.count
        guard count > 0 else { return (nil, nil, nil) }
        func loudness(_ energy: Double) -> Double {
            energy > 0 ? Constants.loudnessOffsetLU + 10 * log10(energy) : -Double.infinity
        }
        func window(_ start: Int, _ size: Int) -> Double {
            var total = 0.0
            var index = start
            while index < start + size {
                total += sub[index]
                index += 1
            }
            return total / Double(size)
        }
        func mean(_ values: [Double]) -> Double {
            var total = 0.0
            for value in values { total += value }
            return total / Double(values.count)
        }

        var integrated: Double?
        let block = Constants.loudnessBlockSubBlocks
        if count >= block {
            let blocks = (0 ... (count - block)).map { window($0, block) }
            let gated = blocks.filter { loudness($0) > Constants.absoluteGateLUFS }
            if !gated.isEmpty {
                let relative = loudness(mean(gated)) + Constants.relativeGateLU
                let kept = gated.filter { loudness($0) > relative }
                if !kept.isEmpty {
                    integrated = loudness(mean(kept))
                }
            }
        }

        var shortTermMaximum: Double?
        var range: Double?
        let short = Constants.shortTermSubBlocks
        if count >= short {
            for start in 0 ... (count - short) {
                let level = loudness(window(start, short))
                if level.isFinite, level > (shortTermMaximum ?? -Double.infinity) {
                    shortTermMaximum = level
                }
            }
            let windows = stride(from: 0, through: count - short, by: Constants.rangeHopSubBlocks)
                .map { window($0, short) }
            let absolute = windows.filter { loudness($0) > Constants.absoluteGateLUFS }
            if !absolute.isEmpty {
                let threshold = loudness(mean(absolute)) + Constants.rangeRelativeGateLU
                let levels = absolute.map(loudness).filter { $0 > threshold }.sorted()
                if !levels.isEmpty {
                    let size = Double(levels.count - 1)
                    let low = levels[Int(size * Constants.rangeLowQuantile + 0.5)]
                    let high = levels[Int(size * Constants.rangeHighQuantile + 0.5)]
                    range = high - low
                }
            }
        }
        return (integrated, shortTermMaximum, range)
    }

    /// WADA-SNR over the nonzero samples of the PCM16 magnitude histogram, summed
    /// in ascending magnitude (the mirror's order); nil without any.
    private func wadaSNR() -> Double? {
        let steps = Constants.wadaMagnitudeGridSteps
        var nonzero = 0
        var total = 0.0
        var logs = 0.0
        for k in 1 ... steps {
            let entries = magnitudeHistogram[k]
            if entries == 0 { continue }
            let magnitude = Double(k) / Double(steps)
            nonzero += entries
            total += Double(entries) * magnitude
            logs += Double(entries) * log(magnitude)
        }
        guard nonzero > 0 else { return nil }
        let statistic = log(total / Double(nonzero)) - logs / Double(nonzero)
        return Self.wadaLookup(statistic)
    }

    static func wadaLookup(_ value: Double) -> Double {
        let snr = Constants.wadaGammaSNRDB
        let g = Constants.wadaGammaG
        var index = -1
        for position in 0 ..< g.count where g[position] < value {
            index = position
        }
        if index < 0 { return snr[0] }
        if index == g.count - 1 { return snr[g.count - 1] }
        return snr[index] + (value - g[index]) / (g[index + 1] - g[index]) * (snr[index + 1] - snr[index])
    }

    private func frameLevelMeasures() -> (noiseFloor: Double?, modulation: Double?) {
        let frames = frameRMS.count
        guard frames > 0 else { return (nil, nil) }
        let levelFloor = pow(10.0, Constants.noiseFloorLevelFloorDBFS / 20.0)
        let levels = frameRMS.map { 20.0 * log10(max($0, levelFloor)) }.sorted()
        let rank = max(0, (frames * Constants.noiseFloorQuantileTenths + 9) / 10 - 1)
        let noiseFloor = levels[min(rank, frames - 1)]

        let period = Constants.modulationPeriodFrames
        let whole = frames - frames % period
        var modulation: Double?
        if whole > 0 {
            var real = 0.0
            var imaginary = 0.0
            var total = 0.0
            for index in 0 ..< whole {
                let value = frameRMS[index]
                real += value * Self.modulationCosine[index % period]
                imaginary += value * Self.modulationSine[index % period]
                total += value
            }
            if total > 0 {
                modulation = 2.0 * (real * real + imaginary * imaginary).squareRoot() / total
            }
        }
        return (noiseFloor, modulation)
    }

    private func spectralMeasures() -> (
        enabled: Bool, bandwidth: Double?, eventsPerSecond: Double?,
        stripeLongestMS: Int?, stripeLagMS: Int?, stripeCount: Int?
    ) {
        guard fftSize > 0, fftSetup != nil else { return (false, nil, nil, nil, nil, nil) }
        let duration = sampleRate > 0 ? Double(processedSamples) / Double(sampleRate) : 0
        let eventsPerSecond: Double? = duration > 0 ? Double(fluxEventCount) / duration : nil

        var bandwidth: Double?
        if ltasFrames > 0 {
            let half = fftSize / 2
            var levels = [Double](repeating: 0, count: half)
            var peak = -Double.infinity
            for bin in 1 ... half {
                let level = 10.0 * log10(max(ltas[bin] / Double(ltasFrames), Constants.bandwidthLTASFloor))
                levels[bin - 1] = level
                if level > peak { peak = level }
            }
            let threshold = peak - Constants.bandwidthThresholdDB
            var highest = 0
            for bin in 1 ... half where levels[bin - 1] >= threshold {
                highest = bin
            }
            bandwidth = Double(highest) * Double(sampleRate) / Double(fftSize)
        }

        let stripe = repetitionStripe()
        return (true, bandwidth, eventsPerSecond, stripe.longestMS, stripe.lagMS, stripe.count)
    }

    private func repetitionStripe() -> (longestMS: Int, lagMS: Int?, count: Int) {
        let pooled = featureActive.count
        let bands = featuresByBand.count
        let threshold = Constants.repetitionCosineThreshold
        var changingPrefix = [Int](repeating: 0, count: pooled + 1)
        for frame in 0 ..< pooled {
            var changes = 0
            if frame >= 1, featureActive[frame], featureActive[frame - 1] {
                var dot = 0.0
                for band in 0 ..< bands {
                    dot += featuresByBand[band][frame] * featuresByBand[band][frame - 1]
                }
                changes = dot < threshold ? 1 : 0
            }
            changingPrefix[frame + 1] = changingPrefix[frame] + changes
        }

        var bestLength = 0
        var bestLag = 0
        var stripes = 0
        let upper = min(Constants.repetitionMaximumLagFrames, pooled - 1)
        if upper >= Constants.repetitionMinimumLagFrames {
            var dots = [Double](repeating: 0, count: pooled)
            for lag in Constants.repetitionMinimumLagFrames ... upper {
                let span = pooled - lag
                dots.withUnsafeMutableBufferPointer { sums in
                    vDSP_vclrD(sums.baseAddress!, 1, vDSP_Length(span))
                    for band in 0 ..< bands {
                        featuresByBand[band].withUnsafeBufferPointer { feature in
                            vDSP_vmaD(
                                feature.baseAddress!, 1,
                                feature.baseAddress! + lag, 1,
                                sums.baseAddress!, 1,
                                sums.baseAddress!, 1,
                                vDSP_Length(span)
                            )
                        }
                    }
                }
                featureActive.withUnsafeBufferPointer { active in
                    dots.withUnsafeBufferPointer { sums in
                        changingPrefix.withUnsafeBufferPointer { prefix in
                            var start = -1
                            var frame = 0
                            while frame <= span {
                                if frame < span, active[frame], active[frame + lag], sums[frame] >= threshold {
                                    if start < 0 { start = frame }
                                    frame += 1
                                    continue
                                }
                                if start >= 0 {
                                    let end = frame - 1
                                    let length = end - start + 1
                                    if prefix[end + 1] - prefix[start + 1] >= Constants.repetitionMinimumChangingFrames {
                                        if length > bestLength {
                                            bestLength = length
                                            bestLag = lag
                                        }
                                        if length >= Constants.repetitionMinimumStripeFrames {
                                            stripes += 1
                                        }
                                    }
                                    start = -1
                                }
                                frame += 1
                            }
                        }
                    }
                }
            }
        }
        let frameMS = Constants.repetitionPoolFrames * hop * 1_000 / max(1, sampleRate)
        return (bestLength * frameMS, bestLength > 0 ? bestLag * frameMS : nil, stripes)
    }

    private func seamMeasures() -> (count: Int, maximumZ: Double?, startMS: Int?) {
        var evaluated = 0
        var best: Double?
        var bestStart: Int?
        for index in seams.indices where seamHasCenter[index] && seamNeighbours[index] > 0 {
            evaluated += 1
            let neighbours = Double(seamNeighbours[index])
            let mean = seamSum[index] / neighbours
            let sigma = max(seamSquares[index] / neighbours - mean * mean, 0).squareRoot()
            let z = (seamCenter[index] - mean) / max(sigma, Constants.seamSigmaFloor)
            if z > (best ?? -Double.infinity) {
                best = z
                bestStart = Int(Double(seams[index]) * 1_000 / Double(sampleRate))
            }
        }
        return (evaluated, best, bestStart)
    }
}
