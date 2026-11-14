import QwenVoiceCore
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

    /// Review of 2026-11-14, item 7: the launch reads a failure the ledger kept from an earlier
    /// launch, so that update does not restart; the user's Retry resumes the mode in the ledger,
    /// and the next launch starts it again.
    func testAKeptFailureDoesNotRestartAtLaunchButRetryDoes() {
        func plan(failure: String?, paused: Bool = false) -> ModelUpdatePlan {
            ModelUpdatePlan(entries: [
                .clone: .init(
                    mode: .clone, retiredFolders: ["Qwen3-TTS-12Hz-1.7B-Base-4bit"], detectedAtUTC: "2026-11-14T00:00:00Z",
                    paused: paused, lastFailure: failure
                ),
            ])
        }
        func launch(
            _ plan: ModelUpdatePlan, pausedThisSession: Bool = false, transferring: Bool = false,
            failedThisSession: Bool = false
        ) -> Policy.Decision {
            decide([
                Policy.Candidate(
                    modelID: "pro_clone", estimatedBytes: 2 * gigabyte, mode: .clone, plan: plan,
                    pausedThisSession: pausedThisSession, transferring: transferring, failedThisSession: failedThisSession
                ),
            ], consented: true)
        }
        let kept = plan(failure: ModelUpdateFailure.network.rawValue)
        XCTAssertEqual(launch(kept), .none, "a failure from an earlier launch waits for Retry")
        XCTAssertEqual(kept.changeBeforeUpdating(.clone), .resume(.clone), "Retry resumes it first")
        XCTAssertEqual(launch(plan(failure: nil)), .start(modelIDs: ["pro_clone"]), "after Retry, a launch starts it")
        XCTAssertEqual(launch(plan(failure: nil), failedThisSession: true), .none)
        XCTAssertEqual(launch(plan(failure: nil, paused: true)), .none)
        XCTAssertEqual(launch(plan(failure: nil), pausedThisSession: true), .none)
        XCTAssertEqual(launch(plan(failure: nil), transferring: true), .none)
        XCTAssertEqual(
            plan(failure: nil).changeAfterFailure(.clone, .space), .recordFailure(.clone, .space),
            "a failed transfer is recorded for the next launch"
        )
    }

    /// A download that failed for want of space would fail again on Retry while the earlier models
    /// stay: the next launch asks to remove them first, even after consent; Later stops it.
    func testASpaceFailureAsksToMakeRoomFirst() {
        func candidate(failure: ModelUpdateFailure?, paused: Bool = false) -> Policy.Candidate {
            let plan = ModelUpdatePlan(entries: [
                .clone: .init(
                    mode: .clone, retiredFolders: ["Qwen3-TTS-12Hz-1.7B-Base-4bit"], detectedAtUTC: "2026-11-14T00:00:00Z",
                    paused: paused, lastFailure: failure?.rawValue
                ),
            ])
            return Policy.Candidate(
                modelID: "pro_clone", estimatedBytes: 2 * gigabyte, mode: .clone, plan: plan,
                pausedThisSession: false, transferring: false, failedThisSession: false
            )
        }
        let makeRoom = Policy.Decision.ask(modelIDs: ["pro_clone"], totalBytes: 2 * gigabyte, makesRoomFirst: true)
        XCTAssertEqual(decide([candidate(failure: .space)], consented: true), makeRoom)
        XCTAssertEqual(decide([candidate(failure: .space)]), makeRoom)
        XCTAssertEqual(
            decide([candidate(failure: .space), self.candidate("pro_custom")], consented: true),
            .ask(modelIDs: ["pro_custom", "pro_clone"], totalBytes: 4 * gigabyte, makesRoomFirst: true)
        )
        XCTAssertEqual(decide([candidate(failure: .space)], earlier: false), .none, "nothing left to remove")
        XCTAssertEqual(decide([candidate(failure: .space, paused: true)]), .none, "Later stopped it")
        XCTAssertEqual(decide([candidate(failure: .space)], lowDataMode: true), .none)
        XCTAssertEqual(decide([candidate(failure: .network)], consented: true), .none, "another failure waits for Retry")
    }
}
