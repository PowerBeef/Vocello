import XCTest

/// RF-59: the iPhone asks once before the model update downloads (Guideline 4.2.3(ii)), then
/// resumes it on its own; it never restarts what the user stopped or a failure waiting for Retry.
final class IOSModelUpdateAutoStartPolicyTests: XCTestCase {
    private typealias Policy = IOSModelUpdateAutoStartPolicy
    private let gigabyte: Int64 = 1_000_000_000

    private func candidate(
        _ id: String, bytes: Int64 = 2_000_000_000, paused: Bool = false, active: Bool = false, failed: Bool = false
    ) -> Policy.Candidate {
        Policy.Candidate(modelID: id, estimatedBytes: bytes, paused: paused, active: active, failed: failed)
    }

    private func decide(
        _ candidates: [Policy.Candidate], consented: Bool = false, lowDataMode: Bool = false,
        available: Int64? = 100_000_000_000, earlier: Bool = true
    ) -> Policy.Decision {
        Policy.decide(
            candidates: candidates, consented: consented, lowDataMode: lowDataMode,
            availableBytes: available, holdsEarlierModels: earlier
        )
    }

    func testTheFirstLaunchAsksOnceForEveryModelWithTheirTotalSize() {
        XCTAssertEqual(
            decide([candidate("pro_custom"), candidate("pro_clone", bytes: 2_200_000_000)]),
            .ask(modelIDs: ["pro_custom", "pro_clone"], totalBytes: 4_200_000_000, makesRoomFirst: false)
        )
    }

    func testAfterConsentALaunchResumesWithoutAsking() {
        XCTAssertEqual(
            decide([candidate("pro_custom"), candidate("pro_design")], consented: true),
            .start(modelIDs: ["pro_custom", "pro_design"])
        )
    }

    func testStoppedFailedAndRunningModelsAreLeftAlone() {
        let candidates = [
            candidate("pro_custom", paused: true),
            candidate("pro_design", failed: true),
            candidate("pro_clone", active: true),
        ]
        XCTAssertEqual(decide(candidates), .none)
        XCTAssertEqual(decide(candidates, consented: true), .none)
        XCTAssertEqual(
            decide(candidates + [candidate("pro_extra")], consented: true), .start(modelIDs: ["pro_extra"])
        )
    }

    func testNothingStartsUnderLowDataModeOrWithNothingToUpdate() {
        XCTAssertEqual(decide([candidate("pro_custom")], consented: true, lowDataMode: true), .none)
        XCTAssertEqual(decide([candidate("pro_custom")], lowDataMode: true), .none)
        XCTAssertEqual(decide([]), .none)
    }

    /// The first download needs room for itself twice over; when the phone lacks it and earlier
    /// models are still on disk, the prompt says they go first.
    func testANearlyFullPhoneMakesRoomFirstOnlyWhenEarlierModelsCanFreeIt() {
        let model = candidate("pro_custom", bytes: 2 * gigabyte)
        let needed = IOSModelDeliverySupport.minimumFreeBytes(forFetching: 2 * gigabyte)
        XCTAssertEqual(needed, 4 * gigabyte)
        XCTAssertEqual(
            decide([model], available: needed - 1),
            .ask(modelIDs: ["pro_custom"], totalBytes: 2 * gigabyte, makesRoomFirst: true)
        )
        XCTAssertEqual(
            decide([model], available: needed),
            .ask(modelIDs: ["pro_custom"], totalBytes: 2 * gigabyte, makesRoomFirst: false)
        )
        XCTAssertEqual(
            decide([model], available: needed - 1, earlier: false),
            .ask(modelIDs: ["pro_custom"], totalBytes: 2 * gigabyte, makesRoomFirst: false),
            "nothing to remove: the delivery's own space check speaks"
        )
        XCTAssertEqual(
            decide([model], available: nil),
            .ask(modelIDs: ["pro_custom"], totalBytes: 2 * gigabyte, makesRoomFirst: false)
        )
    }
}
