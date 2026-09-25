import Foundation
@testable import QwenVoiceCore
import XCTest

/// The 2026-09-13 clone-onset report: a 20 ms burst of quarter-scale steps
/// passed every whole-clip statistic and the slew-clamp click counter. The
/// limiter now measures the densest such cluster so the record carries it.
final class AudioQCStepBurstTests: XCTestCase {
    func testSmoothSpeechLikeSignalHasNoStepBurst() throws {
        var limiter = PCM16StreamLimiter()
        var output: [Int16] = []
        // 300 Hz tone at -6 dBFS: per-sample steps stay far below a quarter scale.
        let tone = (0 ..< 24_000).map { Float(0.5 * sin(2 * Double.pi * 300 * Double($0) / 24_000)) }
        limiter.append(tone, into: &output)
        XCTAssertEqual(limiter.metrics.stepBurstPeakCount, 0)
        XCTAssertNil(limiter.metrics.stepBurstPeakStartSample)
        let report = StreamingExecutionContext.makeAudioQCReport(
            metrics: limiter.metrics, sampleRate: 24_000, durationSeconds: 1, expectedPauseCount: 0
        )
        XCTAssertEqual(report.stepBurstPeakCount, 0)
        XCTAssertNil(report.stepBurstPeakStartMS)
    }

    func testAnOnsetBurstIsCountedAndLocatedAcrossChunkBoundaries() throws {
        var limiter = PCM16StreamLimiter()
        var output: [Int16] = []
        // Silence, then 30 alternating ±0.2 samples starting at sample 4000: the 29
        // interior steps are 0.4 (large, below the 0.42 slew clamp); the 0→0.2 and
        // 0.2→0 edges are 0.2 and do not count.
        var signal = [Float](repeating: 0, count: 4_000)
        signal += (0 ..< 30).map { $0.isMultiple(of: 2) ? Float(0.2) : Float(-0.2) }
        signal += [Float](repeating: 0, count: 20_000)
        // Split the burst across two appends so the window state must survive
        // the chunk boundary the streaming writer produces.
        limiter.append(Array(signal[0 ..< 4_010]), into: &output)
        limiter.append(Array(signal[4_010...]), into: &output)
        XCTAssertEqual(limiter.metrics.stepBurstPeakCount, 29)
        XCTAssertEqual(limiter.metrics.stepBurstPeakStartSample, 4_001)
        // The click counter never saw it: no step exceeded the slew clamp.
        XCTAssertEqual(limiter.metrics.slewLimitedSamples, 0)
        let report = StreamingExecutionContext.makeAudioQCReport(
            metrics: limiter.metrics, sampleRate: 24_000,
            durationSeconds: Double(signal.count) / 24_000, expectedPauseCount: 0
        )
        XCTAssertEqual(report.stepBurstPeakCount, 29)
        XCTAssertEqual(report.stepBurstPeakStartMS, 166)
        XCTAssertEqual(report.clickEvents, 0)
        // Two clusters 40 ms apart never merge into one window.
        var second = PCM16StreamLimiter()
        var out2: [Int16] = []
        var two = [Float](repeating: 0, count: 1_000)
        two += (0 ..< 10).map { $0.isMultiple(of: 2) ? Float(0.2) : Float(-0.2) }
        two += [Float](repeating: 0, count: 960)
        two += (0 ..< 12).map { $0.isMultiple(of: 2) ? Float(0.2) : Float(-0.2) }
        two += [Float](repeating: 0, count: 1_000)
        second.append(two, into: &out2)
        XCTAssertEqual(second.metrics.stepBurstPeakCount, 11)
        XCTAssertEqual(second.metrics.stepBurstPeakStartSample, 1_971)
    }

    func testABurstThatOpensTheTakeWarnsAndALaterOneDoesNot() throws {
        func report(burstAtSample offset: Int) -> AudioQCReport {
            var limiter = PCM16StreamLimiter()
            var output: [Int16] = []
            var signal = [Float](repeating: 0, count: offset)
            signal += (0 ..< 12).map { $0.isMultiple(of: 2) ? Float(0.2) : Float(-0.2) }
            signal += (0 ..< 24_000).map { Float(0.3 * sin(2 * Double.pi * 220 * Double($0) / 24_000)) }
            limiter.append(signal, into: &output)
            return StreamingExecutionContext.makeAudioQCReport(
                metrics: limiter.metrics, sampleRate: 24_000,
                durationSeconds: Double(signal.count) / 24_000, expectedPauseCount: 0
            )
        }
        // 11 steps 2 ms in: the fp16 first-chunk signature.
        let opening = report(burstAtSample: 48)
        XCTAssertEqual(opening.stepBurstPeakCount, 11)
        XCTAssertEqual(opening.stepBurstPeakStartMS, 2)
        XCTAssertTrue(opening.flags.contains("onset_step_burst"), "\(opening.flags)")
        XCTAssertEqual(opening.instabilityVerdict, .warn)
        XCTAssertEqual(opening.algorithmVersion, 8)
        // The same cluster at the plosive onset (150 ms) is recorded, not judged.
        let later = report(burstAtSample: 3_600)
        XCTAssertEqual(later.stepBurstPeakCount, 11)
        XCTAssertEqual(later.stepBurstPeakStartMS, 150)
        XCTAssertFalse(later.flags.contains("onset_step_burst"), "\(later.flags)")
        XCTAssertEqual(later.instabilityVerdict, .pass)
    }

    func testOlderRowsDecodeWithoutTheBurstFields() throws {
        let json = """
        {"algorithmVersion":6,"verdict":"pass","flags":[],"rmsDBFS":-20,"peak":0.5,"clippedSamples":0,
         "hotSamples":0,"nonFiniteSamples":0,"clickEvents":0,"longestSilenceMS":0,"durationSeconds":1.0}
        """
        let report = try JSONDecoder().decode(AudioQCReport.self, from: Data(json.utf8))
        XCTAssertEqual(report.stepBurstPeakCount, 0)
        XCTAssertNil(report.stepBurstPeakStartMS)
        let encoded = try JSONSerialization.jsonObject(with: JSONEncoder().encode(report)) as? [String: Any]
        XCTAssertEqual(encoded?["stepBurstPeakCount"] as? Int, 0)
        // Pre-v8 rows carry no speaking-rate evidence, and none is encoded back.
        XCTAssertNil(report.speakingRateTextUnits)
        XCTAssertNil(report.secondsPerTextUnit)
        XCTAssertNil(encoded?["secondsPerTextUnit"])
    }
}

/// v8 (audit #10): every other Fast QC measure is amplitude-based, so the
/// 2026 canonical run-ons (a 14.96 s and a 15.12 s take of the medium script,
/// normally about 6.5 s) passed. The speaking-rate check relates the take's
/// length to its spoken text and warns.
final class AudioQCSpeakingRateTests: XCTestCase {
    private static let mediumScript =
        "The morning train slipped quietly out of the station, carrying a handful of sleepy travelers toward the coast."
    private static let chineseScript = "今天天气很好，红色的火车离开安静的车站，准时开往远处的城市。"
    private static let japaneseScript = "今日は天気がよく、赤い列車が静かな駅を出発して、遠くの町へ向かいます。"

    private func report(seconds: Double, text: String?) -> AudioQCReport {
        var limiter = PCM16StreamLimiter()
        var output: [Int16] = []
        let tone = (0 ..< Int(seconds * 24_000)).map {
            Float(0.3 * sin(2 * Double.pi * 220 * Double($0) / 24_000))
        }
        limiter.append(tone, into: &output)
        return StreamingExecutionContext.makeAudioQCReport(
            metrics: limiter.metrics,
            sampleRate: 24_000,
            durationSeconds: seconds,
            expectedPauseCount: 0,
            speakingRateText: text
        )
    }

    func testTextUnitsAreLettersAndDigitsAndTheScriptPicksTheClass() {
        XCTAssertEqual(
            AudioSpeakingRateQC.measure(Self.mediumScript),
            AudioSpeakingRateQC.Measurement(textUnits: 91, scriptClass: .alphabetic)
        )
        XCTAssertEqual(
            AudioSpeakingRateQC.measure(Self.chineseScript),
            AudioSpeakingRateQC.Measurement(textUnits: 27, scriptClass: .chinese)
        )
        XCTAssertEqual(
            AudioSpeakingRateQC.measure(Self.japaneseScript),
            AudioSpeakingRateQC.Measurement(textUnits: 32, scriptClass: .japanese)
        )
        XCTAssertEqual(
            AudioSpeakingRateQC.measure("안녕하세요 반갑습니다"),
            AudioSpeakingRateQC.Measurement(textUnits: 10, scriptClass: .korean)
        )
        // Accented letters count once; digits count; punctuation never does.
        XCTAssertEqual(
            AudioSpeakingRateQC.measure("Café 3.0!"),
            AudioSpeakingRateQC.Measurement(textUnits: 6, scriptClass: .alphabetic)
        )
        // A few CJK characters inside Latin text do not switch the class.
        XCTAssertEqual(AudioSpeakingRateQC.measure("Vocello 声")?.scriptClass, .alphabetic)
        XCTAssertNil(AudioSpeakingRateQC.measure(""))
        XCTAssertNil(AudioSpeakingRateQC.measure("…!? —"))
    }

    func testAnOrdinaryTakeReportsItsRateWithoutAFlag() throws {
        let qc = report(seconds: 6.5, text: Self.mediumScript)
        XCTAssertEqual(qc.algorithmVersion, 8)
        XCTAssertEqual(qc.speakingRateTextUnits, 91)
        XCTAssertEqual(try XCTUnwrap(qc.secondsPerTextUnit), 6.5 / 91, accuracy: 1e-12)
        XCTAssertFalse(qc.flags.contains("speaking_rate_slow"), "\(qc.flags)")
        XCTAssertEqual(qc.verdict, .pass)
    }

    func testTheCanonicalRunOnsWarnButNeverFail() {
        for seconds in [14.96, 15.12] {
            let qc = report(seconds: seconds, text: Self.mediumScript)
            XCTAssertTrue(qc.flags.contains("speaking_rate_slow"), "\(seconds): \(qc.flags)")
            XCTAssertEqual(qc.instabilityVerdict, .warn)
            XCTAssertEqual(qc.writtenOutputVerdict, .pass)
            XCTAssertEqual(qc.verdict, .warn)
        }
        // The Chinese run-on (17.28 s of a 27-character script) against a normal take.
        XCTAssertTrue(report(seconds: 17.28, text: Self.chineseScript).flags.contains("speaking_rate_slow"))
        XCTAssertFalse(report(seconds: 7.1, text: Self.chineseScript).flags.contains("speaking_rate_slow"))
        // A slow Japanese delivery below twice its median stays unflagged.
        XCTAssertFalse(report(seconds: 11.5, text: Self.japaneseScript).flags.contains("speaking_rate_slow"))
    }

    func testVeryShortTextIsReportedButNotJudged() throws {
        let qc = report(seconds: 3, text: "Hello there.")
        XCTAssertEqual(qc.speakingRateTextUnits, 10)
        XCTAssertEqual(try XCTUnwrap(qc.secondsPerTextUnit), 0.3, accuracy: 1e-12)
        XCTAssertFalse(qc.flags.contains("speaking_rate_slow"), "\(qc.flags)")
        XCTAssertEqual(qc.verdict, .pass)
    }

    func testWithoutRequestTextTheRateIsAbsent() throws {
        let qc = report(seconds: 20, text: nil)
        XCTAssertNil(qc.speakingRateTextUnits)
        XCTAssertNil(qc.secondsPerTextUnit)
        XCTAssertFalse(qc.flags.contains("speaking_rate_slow"))
        let encoded = try JSONSerialization.jsonObject(with: JSONEncoder().encode(qc)) as? [String: Any]
        XCTAssertNil(encoded?["speakingRateTextUnits"])
        // With text, both fields reach the telemetry JSON and round-trip.
        let measured = report(seconds: 6.5, text: Self.mediumScript)
        let decoded = try JSONDecoder().decode(AudioQCReport.self, from: JSONEncoder().encode(measured))
        XCTAssertEqual(decoded.speakingRateTextUnits, 91)
        XCTAssertEqual(decoded.secondsPerTextUnit, measured.secondsPerTextUnit)
    }
}
