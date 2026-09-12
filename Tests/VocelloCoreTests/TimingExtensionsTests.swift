import Foundation
@testable import QwenVoiceCore
import XCTest

/// The monotonic-clock helpers feed every wall figure the harness publishes
/// (`wallSeconds`, `firstChunkMS`, the operator `rtf=` line). Between
/// 2026-09-11 and 2026-09-12 `Duration.seconds` divided the attosecond
/// component by 1e15 instead of 1e18, so a 3.8 s take printed as 821 s.
final class TimingExtensionsTests: XCTestCase {
    func testDurationSecondsKeepsTheFractionalPartInSeconds() {
        XCTAssertEqual(Duration.milliseconds(846).seconds, 0.846, accuracy: 1e-9)
        XCTAssertEqual((Duration.seconds(3) + .milliseconds(818)).seconds, 3.818, accuracy: 1e-9)
        XCTAssertEqual(Duration.seconds(0).seconds, 0)
        XCTAssertEqual(Duration.microseconds(1).seconds, 1e-6, accuracy: 1e-12)
    }

    func testRoundedMillisecondsAgreesWithSeconds() {
        let duration = Duration.seconds(1) + .milliseconds(499) + .microseconds(600)
        XCTAssertEqual(duration.roundedMilliseconds, 1500)
        XCTAssertEqual(duration.seconds * 1_000, 1499.6, accuracy: 1e-6)
    }

    func testElapsedSecondsMeasuresAShortWaitInSeconds() async throws {
        let started = ContinuousClock.now
        try await Task.sleep(for: .milliseconds(20))
        let elapsed = started.elapsedSeconds
        XCTAssertGreaterThanOrEqual(elapsed, 0.02)
        XCTAssertLessThan(elapsed, 2, "a 20 ms wait must not read as \(elapsed) s")
        XCTAssertEqual(Double(started.elapsedMilliseconds) / 1_000, started.elapsedSeconds, accuracy: 0.05)
    }
}
