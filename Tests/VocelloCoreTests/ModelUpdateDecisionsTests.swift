import Foundation
@testable import QwenVoiceCore
import XCTest

/// RF-59: the update's launch decision on the Mac, the banner both apps show, and the clean-up of
/// retired models' clone prompt caches (review of 2026-11-13, findings 4, 8 and 12).
final class ModelUpdateDecisionsTests: XCTestCase {
    private let gigabyte: Int64 = 1_000_000_000

    func testTheSpaceRuleIsTwiceTheBytesWithAMargin() {
        XCTAssertEqual(ModelDeliverySpace.minimumFreeBytes(forFetching: 2 * gigabyte), 4 * gigabyte)
        XCTAssertEqual(ModelDeliverySpace.minimumFreeBytes(forFetching: 1_000), 1_000 + 256 * 1_024 * 1_024)
    }

    private func candidate(
        _ id: String, paused: Bool = false, active: Bool = false, failed: Bool = false,
        failure: ModelUpdateFailure? = nil
    ) -> MacModelUpdateAutoStart.Candidate {
        .init(
            modelID: id, estimatedBytes: 2 * gigabyte, paused: paused, active: active,
            failure: failure ?? (failed ? .network : nil)
        )
    }

    func testTheMacStartsOnlyWhatTheUserHasNotStoppedAndWhatDidNotFail() {
        let decide = { (candidates: [MacModelUpdateAutoStart.Candidate]) in
            MacModelUpdateAutoStart.decide(
                candidates: candidates, networkAllowsAutomaticDownloads: true,
                availableBytes: 100 * self.gigabyte, holdsEarlierModels: true
            )
        }
        XCTAssertEqual(decide([candidate("a"), candidate("b")]), .start(modelIDs: ["a", "b"]))
        XCTAssertEqual(
            decide([candidate("a", paused: true), candidate("b", failed: true), candidate("c", active: true), candidate("d")]),
            .start(modelIDs: ["d"]), "a failed update waits for the user's Update; no launch restarts it"
        )
        XCTAssertEqual(decide([candidate("a", failed: true)]), .none)
        XCTAssertEqual(
            MacModelUpdateAutoStart.decide(
                candidates: [candidate("a")], networkAllowsAutomaticDownloads: false,
                availableBytes: 100 * gigabyte, holdsEarlierModels: true
            ),
            .none, "a costly or unknown network waits for the banner"
        )
    }

    func testAFullDiskOffersToRemoveTheEarlierModelsFirst() {
        func decide(available: Int64?, earlier: Bool) -> MacModelUpdateAutoStart.Decision {
            MacModelUpdateAutoStart.decide(
                candidates: [candidate("a")], networkAllowsAutomaticDownloads: true,
                availableBytes: available, holdsEarlierModels: earlier
            )
        }
        XCTAssertEqual(decide(available: 4 * gigabyte - 1, earlier: true), .needsRoom(modelIDs: ["a"]))
        XCTAssertEqual(decide(available: 4 * gigabyte, earlier: true), .start(modelIDs: ["a"]))
        XCTAssertEqual(decide(available: 4 * gigabyte - 1, earlier: false), .none, "nothing to remove: no doomed download")
        XCTAssertEqual(decide(available: nil, earlier: true), .start(modelIDs: ["a"]), "an unknown capacity does not block")
    }

    func testTheSpaceCheckCoversTheDownloadsThatRunAtOnce() {
        func decide(available: Int64) -> MacModelUpdateAutoStart.Decision {
            MacModelUpdateAutoStart.decide(
                candidates: [candidate("a"), candidate("b"), candidate("c")], networkAllowsAutomaticDownloads: true,
                availableBytes: available, holdsEarlierModels: true, concurrentDownloads: 2
            )
        }
        // Two 2 GB downloads at once need twice their 4 GB.
        XCTAssertEqual(decide(available: 8 * gigabyte - 1), .needsRoom(modelIDs: ["a", "b", "c"]))
        XCTAssertEqual(decide(available: 8 * gigabyte), .start(modelIDs: ["a", "b", "c"]))
    }

    func testADownloadThatFailedForWantOfSpaceOffersToMakeRoom() {
        func decide(
            _ candidates: [MacModelUpdateAutoStart.Candidate], earlier: Bool = true, userInitiated: Bool = false
        ) -> MacModelUpdateAutoStart.Decision {
            MacModelUpdateAutoStart.decide(
                candidates: candidates, userInitiated: userInitiated, networkAllowsAutomaticDownloads: true,
                availableBytes: 100 * gigabyte, holdsEarlierModels: earlier
            )
        }
        // The disk filled after the check passed: every later launch offers to make room, never a
        // download that fails again.
        XCTAssertEqual(decide([candidate("a", failure: .space)]), .needsRoom(modelIDs: ["a"]))
        XCTAssertEqual(
            decide([candidate("a", failure: .space), candidate("b")]), .needsRoom(modelIDs: ["a", "b"])
        )
        XCTAssertEqual(decide([candidate("a", failure: .space)], earlier: false), .none, "nothing left to remove")
        XCTAssertEqual(decide([candidate("a", paused: true, failure: .space)]), .none, "stopped by the user")
        XCTAssertEqual(decide([candidate("a", failure: .verification)]), .none, "another failure waits for Update")
        // The user's Update resumes the stopped and failed modes, but still makes room first.
        XCTAssertEqual(
            decide([candidate("a", paused: true, failure: .space)], userInitiated: true), .needsRoom(modelIDs: ["a"])
        )
    }

    func testTheUsersUpdateResumesStoppedAndFailedModesOnAnyNetwork() {
        func decide(available: Int64, earlier: Bool) -> MacModelUpdateAutoStart.Decision {
            MacModelUpdateAutoStart.decide(
                candidates: [candidate("a", paused: true), candidate("b", failed: true), candidate("c", active: true)],
                userInitiated: true, networkAllowsAutomaticDownloads: false,
                availableBytes: available, holdsEarlierModels: earlier
            )
        }
        XCTAssertEqual(decide(available: 100 * gigabyte, earlier: true), .start(modelIDs: ["a", "b"]))
        XCTAssertEqual(decide(available: gigabyte, earlier: true), .needsRoom(modelIDs: ["a", "b"]))
        XCTAssertEqual(
            decide(available: gigabyte, earlier: false), .start(modelIDs: ["a", "b"]),
            "nothing to remove: the user's Update still starts"
        )
    }

    /// The pins that keep the earlier models' shared blobs go only once neither the removal, nor a
    /// setup waiting to start the downloads, nor an update download runs.
    func testThePinsOutliveTheRemovalAndTheDownloadsAfterIt() {
        XCTAssertTrue(ModelUpdatePins.mayRelease(makingRoom: false, setupPending: false, updateDownloadActive: false))
        XCTAssertFalse(ModelUpdatePins.mayRelease(makingRoom: true, setupPending: false, updateDownloadActive: false))
        XCTAssertFalse(ModelUpdatePins.mayRelease(makingRoom: false, setupPending: true, updateDownloadActive: false))
        XCTAssertFalse(ModelUpdatePins.mayRelease(makingRoom: false, setupPending: false, updateDownloadActive: true))
    }

    func testTheBannerFollowsTheUpdate() {
        typealias Remaining = ModelUpdateBannerState.Remaining
        func derive(_ remaining: [Remaining], session: Int = 3, freed: Int64? = nil, room: Bool = false) -> ModelUpdateBannerState? {
            ModelUpdateBannerState.derive(
                remaining: remaining, sessionModeCount: session, completionFreedBytes: freed, needsRoom: room
            )
        }
        XCTAssertEqual(derive([], freed: 9), .done(freedBytes: 9), "the done note outlives the plan")
        XCTAssertNil(derive([]))
        XCTAssertEqual(derive([Remaining(paused: false, active: false, fraction: nil)]), .needed)
        XCTAssertNil(derive([Remaining(paused: true, active: false, fraction: nil)]), "stopped by the user: nothing asks")
        XCTAssertEqual(derive([Remaining(paused: false, active: false, fraction: nil)], room: true), .needsRoom)
        XCTAssertNil(
            derive([Remaining(paused: true, active: false, fraction: nil)], room: true),
            "Not Now while the disk is short: the banner goes"
        )
        // Three modes at launch; one is done, one downloads at half, one is stopped and not counted.
        XCTAssertEqual(
            derive([Remaining(paused: false, active: true, fraction: 0.5), Remaining(paused: true, active: false, fraction: nil)]),
            .updating(completed: 1, total: 2, fraction: 0.75)
        )
        XCTAssertEqual(
            derive([Remaining(paused: false, active: true, fraction: nil)], session: 1),
            .updating(completed: 0, total: 1, fraction: 0)
        )
    }

    func testOnlyRetiredModelsClonePromptCachesGo() throws {
        let voices = FileManager.default.temporaryDirectory
            .appendingPathComponent("clone-caches-\(UUID().uuidString)", isDirectory: true)
        defer { try? FileManager.default.removeItem(at: voices) }
        let root = voices.appendingPathComponent("Narrator.clone_prompt", isDirectory: true)
        for folder in ["pro_clone_quality", "pro_clone_speed", "pro_clone", "notes"] {
            try FileManager.default.createDirectory(
                at: root.appendingPathComponent(folder).appendingPathComponent("digest"), withIntermediateDirectories: true
            )
        }
        try Data("w".utf8).write(to: voices.appendingPathComponent("Narrator.wav"))
        XCTAssertEqual(
            RetiredClonePromptCaches.remove(in: voices, currentModelIDs: ["pro_clone_speed", "pro_clone"]),
            ["Narrator.clone_prompt/pro_clone_quality"]
        )
        XCTAssertEqual(
            try FileManager.default.contentsOfDirectory(atPath: root.path).sorted(),
            ["notes", "pro_clone", "pro_clone_speed"]
        )
        XCTAssertEqual(RetiredClonePromptCaches.remove(in: voices, currentModelIDs: ["pro_clone_speed", "pro_clone"]), [])
    }
}
