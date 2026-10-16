import XCTest

/// RF-19 (E-01): installs and starts claim their slot synchronously, before the awaited
/// catalog and delivery plan (which hashes the 682 MB shared component), so two quick taps can
/// neither run two transfers on the one shared downloader nor prepare one model twice.
final class IOSModelDownloadAdmissionTests: XCTestCase {
    /// Two starts interleaved across the first one's awaited delivery plan: the second stays
    /// queued while the first prepares and while it runs, and starts once it has ended.
    func testTwoInterleavedStartsLeaveTheSecondQueued() {
        var admission = IOSModelDownloadAdmission(maxConcurrentModels: 1)

        XCTAssertTrue(admission.claimStart(of: "pro_custom", runningCount: 0))
        // `pro_custom` now awaits its catalog and delivery plan; nothing is running yet.
        XCTAssertFalse(
            admission.claimStart(of: "pro_design", runningCount: 0),
            "the claim fills the slot before any await"
        )

        // `pro_custom` is recorded as running, then its claim ends.
        admission.releaseStart(of: "pro_custom")
        XCTAssertFalse(
            admission.claimStart(of: "pro_design", runningCount: 1),
            "the running transfer fills the slot"
        )

        // `pro_custom` ended, installed or failed: the queued model starts.
        XCTAssertTrue(admission.claimStart(of: "pro_design", runningCount: 0))
        XCTAssertEqual(admission.startingModelIDs, ["pro_design"])
    }

    /// A start that fails before its transfer runs (a catalog mismatch, too little free space)
    /// releases the slot for the next queued model.
    func testAFailedStartReleasesTheClaim() {
        var admission = IOSModelDownloadAdmission(maxConcurrentModels: 1)
        XCTAssertTrue(admission.claimStart(of: "pro_custom", runningCount: 0))

        admission.releaseStart(of: "pro_custom")

        XCTAssertFalse(admission.isClaimed("pro_custom"))
        XCTAssertTrue(admission.claimStart(of: "pro_design", runningCount: 0))
    }

    /// Install's duplicate guard sees a model that is starting: it is neither queued nor
    /// running yet, but a second Install must not prepare it again.
    func testTheDuplicateGuardSeesAStartingModel() {
        var admission = IOSModelDownloadAdmission(maxConcurrentModels: 1)
        XCTAssertTrue(admission.claimStart(of: "pro_custom", runningCount: 0))

        XCTAssertTrue(admission.isClaimed("pro_custom"))
        XCTAssertFalse(admission.claimPreparation(of: "pro_custom", hasDownload: false))
        XCTAssertEqual(admission.preparingModelIDs, [])
    }

    /// Two quick taps on one model: the second is ignored while the first prepares; once the
    /// request is queued, the queue refuses it; after the transfer ends, Install or Retry is
    /// admitted again.
    func testTwoQuickTapsOnOneModelPrepareItOnce() {
        var admission = IOSModelDownloadAdmission(maxConcurrentModels: 1)
        XCTAssertTrue(admission.claimPreparation(of: "pro_custom", hasDownload: false))
        XCTAssertFalse(
            admission.claimPreparation(of: "pro_custom", hasDownload: false),
            "the second tap is ignored"
        )

        admission.releasePreparation(of: "pro_custom")
        XCTAssertFalse(admission.claimPreparation(of: "pro_custom", hasDownload: true), "queued or running")
        XCTAssertTrue(admission.claimPreparation(of: "pro_custom", hasDownload: false), "ended")
    }

    /// A failed preparation (no catalog entry, too little free space) releases its claim, so
    /// the row's Retry is admitted.
    func testAFailedPreparationReleasesTheClaim() {
        var admission = IOSModelDownloadAdmission(maxConcurrentModels: 1)
        XCTAssertTrue(admission.claimPreparation(of: "pro_custom", hasDownload: false))

        admission.releasePreparation(of: "pro_custom")

        XCTAssertFalse(admission.isClaimed("pro_custom"))
        XCTAssertTrue(admission.claimPreparation(of: "pro_custom", hasDownload: false))
    }

    /// Preparing installs of other models never takes the start slot: each joins the queue,
    /// and the queue starts one model at a time.
    func testPreparationsDoNotTakeTheStartSlot() {
        var admission = IOSModelDownloadAdmission(maxConcurrentModels: 1)
        XCTAssertTrue(admission.claimPreparation(of: "pro_design", hasDownload: false))
        XCTAssertTrue(admission.claimPreparation(of: "pro_clone", hasDownload: false))

        XCTAssertTrue(admission.claimStart(of: "pro_custom", runningCount: 0))
        XCTAssertFalse(admission.claimStart(of: "pro_design", runningCount: 0))
    }

    func testTheLimitIsAtLeastOne() {
        XCTAssertEqual(IOSModelDownloadAdmission(maxConcurrentModels: 0).maxConcurrentModels, 1)
    }
}
