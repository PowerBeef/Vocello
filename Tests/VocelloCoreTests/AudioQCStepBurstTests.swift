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
        XCTAssertEqual(opening.algorithmVersion, 7)
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
    }
}
