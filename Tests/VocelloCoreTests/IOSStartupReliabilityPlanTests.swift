import CryptoKit
import Foundation
@testable import QwenVoiceCore
import XCTest

final class IOSStartupReliabilityPlanTests: XCTestCase {
    func testExactLaunchSpecValidatesStrictDeliveryAndScriptIdentity() throws {
        let spec = try IOSStartupReliabilityLaunchSpec.decodeAndValidate(makeRawSpec())
        XCTAssertEqual(spec.runID, "startup-run-1")
        XCTAssertEqual(spec.plan.takes.count, 2)
        XCTAssertEqual(try spec.plan.takes[0].deliveryCell.id, "calm.strong")
        XCTAssertEqual(try spec.plan.takes[0].resolvedLanguage, .english)
        XCTAssertEqual(try spec.plan.takes[0].resolvedVariation, .balanced)
    }

    func testDigestMismatchDuplicateTakeAndPredecessorDriftFailClosed() throws {
        var object = try XCTUnwrap(try JSONSerialization.jsonObject(with: Data(makeRawSpec().utf8)) as? [String: Any])
        var plan = try XCTUnwrap(object["plan"] as? [String: Any])
        plan["scriptSHA256"] = String(repeating: "0", count: 64)
        object["plan"] = plan
        XCTAssertThrowsError(try IOSStartupReliabilityLaunchSpec.decodeAndValidate(json(object))) {
            XCTAssertEqual($0 as? IOSStartupReliabilityPlanError, .scriptIdentityMismatch)
        }

        object = try XCTUnwrap(try JSONSerialization.jsonObject(with: Data(makeRawSpec().utf8)) as? [String: Any])
        plan = try XCTUnwrap(object["plan"] as? [String: Any])
        var takes = try XCTUnwrap(plan["takes"] as? [[String: Any]])
        takes[1]["takeID"] = takes[0]["takeID"]
        plan["takes"] = takes
        object["plan"] = plan
        XCTAssertThrowsError(try IOSStartupReliabilityLaunchSpec.decodeAndValidate(json(object)))

        object = try XCTUnwrap(try JSONSerialization.jsonObject(with: Data(makeRawSpec().utf8)) as? [String: Any])
        plan = try XCTUnwrap(object["plan"] as? [String: Any])
        takes = try XCTUnwrap(plan["takes"] as? [[String: Any]])
        takes[1]["predecessorTakeID"] = "wrong"
        plan["takes"] = takes
        object["plan"] = plan
        XCTAssertThrowsError(try IOSStartupReliabilityLaunchSpec.decodeAndValidate(json(object))) {
            XCTAssertEqual($0 as? IOSStartupReliabilityPlanError, .invalidPredecessor("warm-1"))
        }
    }

    func testBoundsInvalidIdentifiersAndCellsFailClosed() throws {
        var object = try XCTUnwrap(try JSONSerialization.jsonObject(with: Data(makeRawSpec().utf8)) as? [String: Any])
        var plan = try XCTUnwrap(object["plan"] as? [String: Any])
        var takes = try XCTUnwrap(plan["takes"] as? [[String: Any]])
        takes[0]["deliveryID"] = "calm"
        plan["takes"] = takes
        object["plan"] = plan
        XCTAssertThrowsError(try IOSStartupReliabilityLaunchSpec.decodeAndValidate(json(object)))

        object = try XCTUnwrap(try JSONSerialization.jsonObject(with: Data(makeRawSpec().utf8)) as? [String: Any])
        plan = try XCTUnwrap(object["plan"] as? [String: Any])
        takes = try XCTUnwrap(plan["takes"] as? [[String: Any]])
        takes[0]["takeID"] = "unsafe take"
        plan["takes"] = takes
        object["plan"] = plan
        XCTAssertThrowsError(try IOSStartupReliabilityLaunchSpec.decodeAndValidate(json(object)))

        object = try XCTUnwrap(try JSONSerialization.jsonObject(with: Data(makeRawSpec().utf8)) as? [String: Any])
        plan = try XCTUnwrap(object["plan"] as? [String: Any])
        plan["takes"] = Array(repeating: takes[0], count: 129)
        object["plan"] = plan
        XCTAssertThrowsError(try IOSStartupReliabilityLaunchSpec.decodeAndValidate(json(object)))
    }

    private func makeRawSpec() -> String {
        let script = "Exact private script."
        let digest = SHA256.hash(data: Data(script.utf8))
            .map { String(format: "%02x", $0) }.joined()
        return json([
            "schemaVersion": 1,
            "runID": "startup-run-1",
            "script": script,
            "plan": [
                "schemaVersion": 1,
                "scriptSHA256": digest,
                "scriptCharacters": script.count,
                "takes": [
                    [
                        "takeIndex": 1, "takeID": "cold-1", "speakerID": "vivian",
                        "deliveryID": "calm.strong", "language": "english",
                        "seed": 38_112_001, "variation": "balanced", "streaming": true,
                        "preparation": "full_runtime_unload",
                    ],
                    [
                        "takeIndex": 2, "takeID": "warm-1", "speakerID": "vivian",
                        "deliveryID": "calm.strong", "language": "english",
                        "seed": 38_112_001, "variation": "balanced", "streaming": false,
                        "preparation": "production", "predecessorTakeID": "cold-1",
                    ],
                ],
            ],
        ])
    }

    private func json(_ object: Any) -> String {
        String(data: try! JSONSerialization.data(withJSONObject: object, options: [.sortedKeys]), encoding: .utf8)!
    }
}
