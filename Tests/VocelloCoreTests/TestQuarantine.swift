import Foundation
import XCTest

/// Opt-in quarantine for a test that has proven flaky.
///
/// List the test in `config/test-quarantine.json` (`Suite/testMethod`, the date and a note)
/// and call `try TestQuarantine.skipIfListed(self)` at the top of the test. Push CI sets
/// `VOCELLO_QUARANTINE=1` and skips listed tests; nightly leaves it unset, so a quarantined
/// test keeps running and reporting there. `scripts/repo_invariants.sh` fails once an entry
/// is older than 30 days: quarantine buys time to fix a test, never a way to forget it.
enum TestQuarantine {
    private static let repositoryRoot = URL(fileURLWithPath: #filePath)
        .deletingLastPathComponent()  // TestQuarantine.swift
        .deletingLastPathComponent()  // VocelloCoreTests
        .deletingLastPathComponent()  // Tests

    private static let listed: Set<String> = {
        let url = repositoryRoot.appendingPathComponent("config/test-quarantine.json")
        guard let data = try? Data(contentsOf: url),
              let document = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let entries = document["entries"] as? [[String: Any]]
        else { return [] }
        return Set(entries.compactMap { $0["id"] as? String })
    }()

    /// Identifier in the quarantine file's form: `Suite/testMethod`.
    static func identifier(for testCase: XCTestCase) -> String {
        // XCTest names a case "-[Suite testMethod]".
        let trimmed = testCase.name.trimmingCharacters(in: CharacterSet(charactersIn: "-[]"))
        let parts = trimmed.split(separator: " ", maxSplits: 1).map(String.init)
        return parts.count == 2 ? "\(parts[0])/\(parts[1])" : trimmed
    }

    static func skipIfListed(_ testCase: XCTestCase, file: StaticString = #filePath, line: UInt = #line) throws {
        guard ProcessInfo.processInfo.environment["VOCELLO_QUARANTINE"] == "1" else { return }
        let id = identifier(for: testCase)
        if listed.contains(id) {
            throw XCTSkip("quarantined in config/test-quarantine.json: \(id)", file: file, line: line)
        }
    }
}
