import Foundation
@testable import QwenVoiceCore
import VocelloQwen3Core
import XCTest

/// AQ-04 (audit 2026-09-25, AQ-F08 to AQ-F12 and AQ-F49): the Stage 0
/// observational signal measures. The constants equal the record
/// `config/audio-qc-stage0-observations.json`, and every field of every shared
/// fixture in `scripts/tests/fixtures/audio_qc_stage0_observations.json` matches
/// the float64 mirror `scripts/lib/audio_qc_observations.py`: integers exactly,
/// reals within one four-decimal rounding step. The measures move no flag,
/// verdict or Fast QC version.
final class AudioQCSignalObservationTests: XCTestCase {
    private typealias Constants = AudioQCSignalObserver.Constants
    private static let rate = 24_000
    private static let realTolerance = 1.5e-4
    private static let integerFields: Set<String> = [
        "algorithmVersion", "spectralFluxEventCount", "seamCount", "seamDiscontinuityMaxZStartMS",
        "repetitionStripeLongestMS", "repetitionStripeLagMS", "repetitionStripeCount",
    ]

    private static var repositoryRoot: URL {
        URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .deletingLastPathComponent()
    }

    private func json(_ relativePath: String) throws -> [String: Any] {
        let data = try Data(contentsOf: Self.repositoryRoot.appendingPathComponent(relativePath))
        return try XCTUnwrap(JSONSerialization.jsonObject(with: data) as? [String: Any], relativePath)
    }

    private func double(_ key: String, in table: [String: Any]) throws -> Double {
        try XCTUnwrap(table[key] as? NSNumber, key).doubleValue
    }

    /// Record reals against Swift literals within Float64 rounding, as the
    /// calibration-record test compares them.
    private func assertClose(_ key: String, in table: [String: Any], _ expected: Double) throws {
        XCTAssertEqual(try double(key, in: table), expected, accuracy: 1e-12 * max(1, abs(expected)), key)
    }

    private func integer(_ key: String, in table: [String: Any]) throws -> Int {
        try XCTUnwrap(table[key] as? NSNumber, key).intValue
    }

    private func table(_ key: String, in parent: [String: Any]) throws -> [String: Any] {
        try XCTUnwrap(parent[key] as? [String: Any], key)
    }

    // MARK: - Fixture synthesis (the recipe `synthesize_fixture` writes in Python)

    static func synthesize(_ segments: [[String: Any]], sampleRate: Int) throws -> [Int16] {
        func number(_ segment: [String: Any], _ key: String) throws -> Double {
            try XCTUnwrap(segment[key] as? NSNumber, key).doubleValue
        }
        var values: [Double] = []
        let rate = Double(sampleRate)
        for segment in segments {
            let kind = try XCTUnwrap(segment["kind"] as? String)
            let count = (segment["samples"] as? NSNumber)?.intValue ?? 0
            switch kind {
            case "silence":
                values.append(contentsOf: repeatElement(0.0, count: count))
            case "sine":
                let frequency = try number(segment, "frequencyHz")
                let amplitude = try number(segment, "amplitude")
                let phase = (segment["phase"] as? NSNumber)?.doubleValue ?? 0
                for i in 0 ..< count {
                    values.append(amplitude * sin(2.0 * Double.pi * frequency * Double(i) / rate + phase))
                }
            case "am":
                let frequency = try number(segment, "frequencyHz")
                let amplitude = try number(segment, "amplitude")
                let modulation = try number(segment, "modulationHz")
                let depth = try number(segment, "depth")
                for i in 0 ..< count {
                    values.append(
                        amplitude * (1.0 + depth * cos(2.0 * Double.pi * modulation * Double(i) / rate))
                            * sin(2.0 * Double.pi * frequency * Double(i) / rate)
                    )
                }
            case "chirp":
                let start = try number(segment, "startHz")
                let end = try number(segment, "endHz")
                let amplitude = try number(segment, "amplitude")
                let span = Double(count)
                for i in 0 ..< count {
                    let t = Double(i)
                    values.append(
                        amplitude * sin(2.0 * Double.pi * (start * t / rate + (end - start) * t * t / (2.0 * span * rate)))
                    )
                }
            case "noise":
                let amplitude = try number(segment, "amplitude")
                let seed = try XCTUnwrap(segment["seed"] as? NSNumber).intValue
                var state = UInt64(seed) % 4_294_967_296
                for _ in 0 ..< count {
                    state = (state * 1_664_525 + 1_013_904_223) % 4_294_967_296
                    values.append(amplitude * (2.0 * Double(state) / 4_294_967_296.0 - 1.0))
                }
            case "copy":
                let start = try XCTUnwrap(segment["start"] as? NSNumber).intValue
                values.append(contentsOf: values[start ..< (start + count)])
            case "impulses":
                let amplitude = try number(segment, "amplitude")
                for position in try XCTUnwrap(segment["positions"] as? [NSNumber]) {
                    values[position.intValue] += amplitude
                }
            default:
                XCTFail("unknown fixture segment kind \(kind)")
            }
        }
        return values.map { value in
            let magnitude = min(32_767.0, (abs(value) * 32_767.0 + 0.5).rounded(.down))
            return Int16(value < 0 ? -magnitude : magnitude)
        }
    }

    /// Feeds the persisted-read view of the samples (k / 32768) in uneven blocks,
    /// so every measure has to carry its state across block boundaries.
    static func observe(_ pcm: [Int16], seams: [Int] = [], block: Int = 7_001) -> AudioQCSignalObservations {
        let observer = AudioQCSignalObserver(sampleRate: rate, seamFrameOffsets: seams)
        let samples = pcm.map { Float($0) / 32_768 }
        var start = 0
        while start < samples.count {
            let end = min(samples.count, start + block)
            observer.append(Array(samples[start ..< end]))
            start = end
        }
        return observer.finish()
    }

    private func encoded(_ observations: AudioQCSignalObservations) throws -> [String: Any] {
        try XCTUnwrap(
            JSONSerialization.jsonObject(with: JSONEncoder().encode(observations)) as? [String: Any]
        )
    }

    private func assertMatches(
        _ observations: AudioQCSignalObservations,
        _ expected: [String: Any],
        _ fixture: String
    ) throws {
        let actual = try encoded(observations)
        XCTAssertTrue(Set(actual.keys).isSubset(of: Set(expected.keys)), "\(fixture): \(actual.keys)")
        for (key, value) in expected {
            if value is NSNull {
                XCTAssertNil(actual[key], "\(fixture).\(key)")
                continue
            }
            let expectedNumber = try XCTUnwrap(value as? NSNumber, "\(fixture).\(key)")
            let actualNumber = try XCTUnwrap(actual[key] as? NSNumber, "\(fixture).\(key) is missing")
            if Self.integerFields.contains(key) {
                XCTAssertEqual(actualNumber.intValue, expectedNumber.intValue, "\(fixture).\(key)")
            } else {
                XCTAssertEqual(
                    actualNumber.doubleValue, expectedNumber.doubleValue,
                    accuracy: Self.realTolerance, "\(fixture).\(key)"
                )
            }
        }
    }

    // MARK: - Record

    func testConstantsEqualTheRecord() throws {
        let record = try json("config/audio-qc-stage0-observations.json")
        XCTAssertEqual(record["algorithmVersion"] as? Int, AudioQCSignalObservations.currentAlgorithmVersion)
        XCTAssertEqual(record["fastQCAlgorithmVersion"] as? Int, AudioQCReport.currentAlgorithmVersion)
        XCTAssertEqual(record["status"] as? String, "observational")
        let constants = try table("constants", in: record)

        let kWeighting = try table("kWeighting", in: constants)
        try assertClose("shelfFrequencyHz", in: kWeighting, Constants.shelfFrequencyHz)
        try assertClose("shelfGainDB", in: kWeighting, Constants.shelfGainDB)
        try assertClose("shelfQ", in: kWeighting, Constants.shelfQ)
        try assertClose("shelfBandwidthExponent", in: kWeighting, Constants.shelfBandwidthExponent)
        try assertClose("highPassFrequencyHz", in: kWeighting, Constants.highPassFrequencyHz)
        try assertClose("highPassQ", in: kWeighting, Constants.highPassQ)

        let loudness = try table("loudness", in: constants)
        try assertClose("offsetLU", in: loudness, Constants.loudnessOffsetLU)
        XCTAssertEqual(try integer("subBlocksPerSecond", in: loudness), Constants.loudnessSubBlocksPerSecond)
        XCTAssertEqual(try integer("blockSubBlocks", in: loudness), Constants.loudnessBlockSubBlocks)
        XCTAssertEqual(try integer("shortTermSubBlocks", in: loudness), Constants.shortTermSubBlocks)
        XCTAssertEqual(try integer("rangeHopSubBlocks", in: loudness), Constants.rangeHopSubBlocks)
        try assertClose("absoluteGateLUFS", in: loudness, Constants.absoluteGateLUFS)
        try assertClose("relativeGateLU", in: loudness, Constants.relativeGateLU)
        try assertClose("rangeRelativeGateLU", in: loudness, Constants.rangeRelativeGateLU)
        try assertClose("rangeLowQuantile", in: loudness, Constants.rangeLowQuantile)
        try assertClose("rangeHighQuantile", in: loudness, Constants.rangeHighQuantile)

        let truePeak = try table("truePeak", in: constants)
        XCTAssertEqual(try integer("oversampling", in: truePeak), Constants.truePeakOversampling)
        XCTAssertEqual(try integer("taps", in: truePeak), Constants.truePeakTaps)
        try assertClose("coefficientFloor", in: truePeak, Constants.truePeakCoefficientFloor)

        XCTAssertEqual(try integer("framesPerSecond", in: constants), Constants.framesPerSecond)
        let noiseFloor = try table("noiseFloor", in: constants)
        XCTAssertEqual(try integer("quantileTenths", in: noiseFloor), Constants.noiseFloorQuantileTenths)
        try assertClose("levelFloorDBFS", in: noiseFloor, Constants.noiseFloorLevelFloorDBFS)
        XCTAssertEqual(
            try integer("magnitudeGridSteps", in: try table("wada", in: constants)),
            Constants.wadaMagnitudeGridSteps
        )

        let spectrum = try table("spectrum", in: constants)
        XCTAssertEqual(try integer("fftSize", in: spectrum), Constants.fftSize)
        XCTAssertEqual(try integer("fftSizeAboveRate", in: spectrum), Constants.fftSizeAboveRate)
        XCTAssertEqual(try integer("fftSizeRateLimit", in: spectrum), Constants.fftSizeRateLimit)
        XCTAssertEqual(try integer("minimumSampleRate", in: spectrum), Constants.minimumSpectralSampleRate)
        try assertClose("powerFloor", in: spectrum, Constants.spectralPowerFloor)
        try assertClose("activeMeanSquare", in: spectrum, Constants.activeMeanSquare)

        let flux = try table("spectralFlux", in: constants)
        try assertClose("eventThresholdDB", in: flux, Constants.fluxEventThresholdDB)
        XCTAssertEqual(try integer("clusterGapFrames", in: flux), Constants.fluxClusterGapFrames)
        let bandwidth = try table("bandwidth", in: constants)
        try assertClose("thresholdDB", in: bandwidth, Constants.bandwidthThresholdDB)
        try assertClose("ltasFloor", in: bandwidth, Constants.bandwidthLTASFloor)
        let modulation = try table("modulation", in: constants)
        try assertClose("frequencyHz", in: modulation, Constants.modulationFrequencyHz)
        XCTAssertEqual(try integer("periodFrames", in: modulation), Constants.modulationPeriodFrames)
        XCTAssertEqual(
            Double(Constants.framesPerSecond) / Double(Constants.modulationPeriodFrames),
            Constants.modulationFrequencyHz,
            "one tokenizer frame period is a whole number of analysis frames"
        )
        let seam = try table("seam", in: constants)
        XCTAssertEqual(try integer("halfWindowFrames", in: seam), Constants.seamHalfWindowFrames)
        try assertClose("sigmaFloor", in: seam, Constants.seamSigmaFloor)

        let repetition = try table("repetition", in: constants)
        XCTAssertEqual(try integer("poolFrames", in: repetition), Constants.repetitionPoolFrames)
        XCTAssertEqual(
            (repetition["bandEdgesAt512"] as? [NSNumber])?.map(\.intValue),
            Constants.repetitionBandEdgesAt512
        )
        try assertClose("cosineThreshold", in: repetition, Constants.repetitionCosineThreshold)
        XCTAssertEqual(try integer("minimumLagFrames", in: repetition), Constants.repetitionMinimumLagFrames)
        XCTAssertEqual(try integer("maximumLagFrames", in: repetition), Constants.repetitionMaximumLagFrames)
        XCTAssertEqual(try integer("minimumStripeFrames", in: repetition), Constants.repetitionMinimumStripeFrames)
        XCTAssertEqual(try integer("minimumChangingFrames", in: repetition), Constants.repetitionMinimumChangingFrames)
        try assertClose("featureNormFloor", in: repetition, Constants.repetitionFeatureNormFloor)
        XCTAssertEqual(try integer("roundingDecimals", in: constants), Constants.roundingDecimals)

        let wada = try table("wadaGammaTable", in: record)
        XCTAssertEqual((wada["snrDB"] as? [NSNumber])?.map(\.intValue), Constants.wadaGammaSNRDB.map { Int($0) })
        let g = try XCTUnwrap((wada["g"] as? [NSNumber])?.map(\.doubleValue))
        XCTAssertEqual(g.count, Constants.wadaGammaG.count)
        for (recorded, value) in zip(g, Constants.wadaGammaG) {
            XCTAssertEqual(recorded, value, accuracy: 1e-12)
        }
    }

    func testKWeightingAt48kHzIsTheBS1770Filter() {
        let sections = AudioQCSignalObserver.kWeightingSections(sampleRate: 48_000)
        let published = [
            1.53512485958697, -2.69169618940638, 1.19839281085285, -1.69065929318241, 0.73248077421585,
            1.0, -2.0, 1.0, -1.99004745483398, 0.99007225036621,
        ]
        XCTAssertEqual(sections.count, published.count)
        for (value, expected) in zip(sections, published) {
            XCTAssertEqual(value, expected, accuracy: 1e-12)
        }
        let phases = AudioQCSignalObserver.truePeakTaps()
        XCTAssertEqual(phases.map(\.count), [13, 13, 13, 13])
        XCTAssertEqual(phases[0], [0, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0], "phase 0 is the input itself")
    }

    // MARK: - Shared fixtures

    func testSharedSignalFixturesMatchThePythonMirror() throws {
        let fixtures = try json("scripts/tests/fixtures/audio_qc_stage0_observations.json")
        XCTAssertEqual(fixtures["algorithmVersion"] as? Int, AudioQCSignalObservations.currentAlgorithmVersion)
        let sampleRate = try XCTUnwrap(fixtures["sampleRate"] as? Int)
        XCTAssertEqual(sampleRate, Self.rate)
        let signalFixtures = try XCTUnwrap(fixtures["signalFixtures"] as? [[String: Any]])
        XCTAssertGreaterThanOrEqual(signalFixtures.count, 10)
        for fixture in signalFixtures {
            let identifier = try XCTUnwrap(fixture["id"] as? String)
            let segments = try XCTUnwrap(fixture["segments"] as? [[String: Any]])
            let pcm = try Self.synthesize(segments, sampleRate: sampleRate)
            XCTAssertEqual(pcm.count, fixture["sampleCount"] as? Int, identifier)
            let seams = (fixture["seams"] as? [NSNumber])?.map(\.intValue) ?? []
            let expected = try XCTUnwrap(fixture["expected"] as? [String: Any])
            try assertMatches(Self.observe(pcm, seams: seams), expected, identifier)
            // The block size moves no value beyond Accelerate's summation order.
            try assertMatches(
                Self.observe(pcm, seams: seams, block: 1_000),
                try encoded(Self.observe(pcm, seams: seams, block: 16_384)),
                "\(identifier) in 1 000-sample blocks"
            )
        }
    }

    // MARK: - Known references

    func testAMinus20DBFS997HzToneReadsMinus23LUFS() throws {
        // BS.1770's -0.691 offset cancels the K-weighting gain at 997 Hz: a mono sine
        // of amplitude A reads 20 log10(A) - 3.01 LUFS (the 24 kHz filter is 0.03 LU off).
        let pcm = try Self.synthesize(
            [["kind": "sine", "samples": 96_000, "frequencyHz": 997.0, "amplitude": 0.1]],
            sampleRate: Self.rate
        )
        let result = Self.observe(pcm)
        XCTAssertEqual(try XCTUnwrap(result.integratedLoudnessLUFS), -23.0103, accuracy: 0.05)
        XCTAssertEqual(result.loudnessRangeLU, 0)
        XCTAssertEqual(try XCTUnwrap(result.truePeakDBTP), -20, accuracy: 0.01)
        XCTAssertEqual(result.codecFrameModulationIndex, 0)
        XCTAssertEqual(result.repetitionStripeLongestMS, 0, "a steady tone repeats no content")
        XCTAssertEqual(result.wadaSNRDB, -20, "a pure tone looks nothing like speech to WADA")
    }

    func testTruePeakFindsThePeakBetweenSamples() throws {
        // fs/4 at 45 degrees: every sample sits at A / sqrt(2), 3.01 dB under the waveform.
        let pcm = try Self.synthesize(
            [["kind": "sine", "samples": 24_000, "frequencyHz": 6_000.0, "amplitude": 0.5, "phase": Double.pi / 4]],
            sampleRate: Self.rate
        )
        let truePeak = try XCTUnwrap(Self.observe(pcm).truePeakDBTP)
        XCTAssertEqual(truePeak, 20 * log10(0.5), accuracy: 0.15)
        XCTAssertGreaterThan(truePeak - 20 * log10(0.5 / 2.0.squareRoot()), 2.9)
    }

    func testClicksSeamsAndRepeatsAreFound() throws {
        let clicks = try Self.synthesize([
            ["kind": "silence", "samples": 48_000],
            ["kind": "impulses", "amplitude": 0.5, "positions": (0 ..< 8).map { 3_000 + 6_000 * $0 }],
        ], sampleRate: Self.rate)
        let clicked = Self.observe(clicks)
        XCTAssertEqual(clicked.spectralFluxEventCount, 8)
        XCTAssertEqual(clicked.spectralFluxEventsPerSecond, 4)
        XCTAssertEqual(clicked.noiseFloorDBFS, -120)

        let tone: [String: Any] = ["kind": "sine", "samples": 24_000, "frequencyHz": 440.0, "amplitude": 0.3]
        var jumped = tone
        jumped["phase"] = Double.pi / 2
        let seamPCM = try Self.synthesize([tone, jumped], sampleRate: Self.rate)
        let seams = Self.observe(seamPCM, seams: [24_000, 36_000])
        XCTAssertEqual(seams.seamCount, 2)
        XCTAssertGreaterThan(try XCTUnwrap(seams.seamDiscontinuityMaxZ), 10)
        XCTAssertEqual(seams.seamDiscontinuityMaxZStartMS, 1_000)
        XCTAssertLessThan(try XCTUnwrap(Self.observe(seamPCM, seams: [36_000]).seamDiscontinuityMaxZ), 3)

        let repeated = try Self.synthesize([
            ["kind": "silence", "samples": 4_800],
            ["kind": "noise", "samples": 19_200, "amplitude": 0.3, "seed": 12_345],
            ["kind": "copy", "start": 4_800, "samples": 19_200],
            ["kind": "silence", "samples": 4_800],
        ], sampleRate: Self.rate)
        let stripe = Self.observe(repeated)
        XCTAssertEqual(stripe.repetitionStripeLagMS, 800)
        XCTAssertGreaterThanOrEqual(try XCTUnwrap(stripe.repetitionStripeLongestMS), 600)
        XCTAssertEqual(stripe.repetitionStripeCount, 1)
    }

    // MARK: - Persisted WAV and records

    func testPersistedWAVCarriesTheObservationsWithoutMovingTheVerdict() throws {
        let tone: [String: Any] = ["kind": "sine", "samples": 24_000, "frequencyHz": 440.0, "amplitude": 0.3]
        var jumped = tone
        jumped["phase"] = Double.pi / 2
        let pcm = try Self.synthesize([tone, jumped], sampleRate: Self.rate)
        let directory = FileManager.default.temporaryDirectory
            .appendingPathComponent("AudioQCSignalObservationTests-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: directory) }
        let url = directory.appendingPathComponent("take.wav")
        try AtomicPCM16WAVWriter.write(pcmSamples: pcm, sampleRate: Self.rate, outputURL: url)

        let report = try PersistedWAVAudioQCAnalyzer.evaluate(url: url, seamFrameOffsets: [24_000, 36_000])
        XCTAssertEqual(report.algorithmVersion, 8, "the observations leave the Fast QC version")
        let signal = try XCTUnwrap(report.signal)
        try assertMatches(signal, try encoded(Self.observe(pcm, seams: [24_000, 36_000])), "persisted WAV")
        let bare = try PersistedWAVAudioQCAnalyzer.evaluate(url: url)
        XCTAssertEqual(bare.signal?.seamCount, 0)
        XCTAssertNil(bare.signal?.seamDiscontinuityMaxZ)
        XCTAssertEqual(bare.signal?.integratedLoudnessLUFS, signal.integratedLoudnessLUFS)
        // No flag or verdict reads the block.
        XCTAssertEqual(report.flags, bare.flags)
        XCTAssertEqual(report.verdict, bare.verdict)
        XCTAssertEqual(report.instabilityVerdict, bare.instabilityVerdict)
        XCTAssertEqual(report.writtenOutputVerdict, bare.writtenOutputVerdict)
    }

    func testReportsDecodeWithAndWithoutTheSignalBlock() throws {
        let legacy = """
        {"algorithmVersion":8,"verdict":"pass","flags":[],"rmsDBFS":-20,"peak":0.5,"clippedSamples":0,
         "hotSamples":0,"nonFiniteSamples":0,"clickEvents":0,"longestSilenceMS":0,"durationSeconds":1.0}
        """
        let report = try JSONDecoder().decode(AudioQCReport.self, from: Data(legacy.utf8))
        XCTAssertNil(report.signal)
        let legacyObject = try XCTUnwrap(
            JSONSerialization.jsonObject(with: JSONEncoder().encode(report)) as? [String: Any]
        )
        XCTAssertNil(legacyObject["signal"], "a report without observations encodes none")

        let silent = Self.observe([Int16](repeating: 0, count: 24_000))
        let withSignal = StreamingExecutionContext.makeAudioQCReport(
            metrics: PCM16StreamLimiter.Metrics(), sampleRate: Self.rate, durationSeconds: 1,
            expectedPauseCount: 0, signal: silent
        )
        let decoded = try JSONDecoder().decode(AudioQCReport.self, from: JSONEncoder().encode(withSignal))
        XCTAssertEqual(decoded.signal, silent)
        XCTAssertNil(silent.integratedLoudnessLUFS)
        XCTAssertNil(try encoded(silent)["integratedLoudnessLUFS"], "nil measures are omitted, not null")
        let minimal = try JSONDecoder().decode(
            AudioQCSignalObservations.self, from: Data(#"{"algorithmVersion":1}"#.utf8)
        )
        XCTAssertEqual(minimal.seamCount, 0)
    }

    func testEngineIntrospectionTravelsFromTheFacadeIntoTheTelemetryRow() throws {
        let facade = """
        {"algorithmVersion":1,"codecFrameCount":32,"longestRepeatedTokenRunFrames":1,"tokenCyclePeriod":8,
         "tokenCycleSpanFrames":24,"tokenCycleRepeats":3,"tokenCycleStartFrame":4,"observedStepCount":33,
         "entropyMeanNats":2.8523,"entropyP95Nats":4.78125,"longestHighEntropyRunSteps":3,
         "eosProbabilityFinal":0.875,"eosProbabilityMax":0.875,"eosProbabilityMaxStep":32,
         "eosFirstLikelyStep":3,"eosLikelyStepsWithoutStop":3,"seamCodecFrames":[25]}
        """
        let summary = try JSONDecoder().decode(VocelloQwen3GenerationIntrospection.self, from: Data(facade.utf8))
        let introspection = GenerationEngineIntrospection(summary)
        XCTAssertEqual(introspection.tokenCyclePeriod, 8)
        XCTAssertEqual(introspection.tokenCycleRepeats, 3)
        XCTAssertEqual(introspection.seamCodecFrames, [25])
        let row = GenerationTelemetryRecord(
            generationID: UUID().uuidString,
            layer: .engine,
            recordedAt: "2026-09-26T00:00:00Z",
            engineIntrospection: introspection
        )
        let decoded = try JSONDecoder().decode(GenerationTelemetryRecord.self, from: JSONEncoder().encode(row))
        XCTAssertEqual(decoded.engineIntrospection, introspection)
        XCTAssertEqual(decoded.schemaVersion, GenerationTelemetryRecord.currentSchemaVersion)
        let bare = GenerationTelemetryRecord(generationID: "x", layer: .engine, recordedAt: "2026-09-26T00:00:00Z")
        let bareObject = try XCTUnwrap(
            JSONSerialization.jsonObject(with: JSONEncoder().encode(bare)) as? [String: Any]
        )
        XCTAssertNil(bareObject["engineIntrospection"], "rows without introspection keep their shape")
    }
}
