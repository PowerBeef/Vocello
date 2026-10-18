import XCTest

/// SEC-1 invariants of take and export names over many moments and time zones: every
/// name is ASCII, keeps the timestamp shape, names the app and never the script, and
/// exporting a neutral name is the identity. XCTest, not Swift Testing: the raw
/// `xcrun xctest` runner the deterministic lane uses never runs Swift Testing tests
/// (workflow audit P1-6, verified 2026-10-18), so they would pass without running.
final class GenerationOutputFileNameInvariantTests: XCTestCase {
    private let timeZones = ["UTC", "America/Toronto", "Asia/Kolkata", "Pacific/Chatham", "Asia/Tokyo"]
    /// Seconds since 1970: the epoch, a leap day, Toronto's 2026 fall-back instant, 2026-09-26 and a
    /// far-future date.
    private let moments: [TimeInterval] = [0, 1_709_164_800.5, 1_793_512_800.125, 1_790_431_387.25, 4_102_444_799.999]
    private let takeName = #/^[0-9]{8}_[0-9]{2}-[0-9]{2}-[0-9]{2}-[0-9]{3}_Vocello\.wav$/#

    private func eachMoment(_ check: (String, String) throws -> Void) throws {
        for zone in timeZones {
            let timeZone = try XCTUnwrap(TimeZone(identifier: zone))
            for seconds in moments {
                let name = GenerationOutputFileName.make(date: Date(timeIntervalSince1970: seconds), timeZone: timeZone)
                try check(name, "\(zone) @ \(seconds)")
            }
        }
    }

    func testATakeNameIsAnASCIITimestampFollowedByTheAppsName() throws {
        try eachMoment { name, moment in
            XCTAssertNotNil(name.wholeMatch(of: takeName), "\(moment): \(name)")
            XCTAssertTrue(name.allSatisfy { $0.isASCII }, "\(moment): \(name)")
        }
    }

    func testExportingANeutralTakeNameKeepsIt() throws {
        try eachMoment { name, moment in
            XCTAssertEqual(GenerationOutputFileName.exportName(forTakeNamed: name), name, moment)
        }
    }

    func testAnEarlierBuildsScriptNamedTakeExportsUnderTheNeutralName() throws {
        let utc = try XCTUnwrap(TimeZone(identifier: "UTC"))
        let date = Date(timeIntervalSince1970: 1_790_431_387.25)
        let stamp = GenerationOutputFileName.timestamp(for: date, timeZone: utc)
        for script in ["Hello world", "Bonjour à tous, ceci est un long script", "你好世界", "a/b\\c: d"] {
            XCTAssertEqual(GenerationOutputFileName.exportName(forTakeNamed: "\(stamp)_\(script).wav"),
                           GenerationOutputFileName.make(date: date, timeZone: utc), script)
        }
    }
}
