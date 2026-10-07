import XCTest
import QwenVoiceCore

/// The automatic "Saved outputs" folder copy is an outward export surface: it
/// must consult the export policy with the saved row's mode and never move a
/// locked Design/Clone clip out of the app.
@MainActor
final class IOSSavedOutputsDestinationTests: XCTestCase {
    private var root: URL!
    private var folder: URL!

    override func setUp() async throws {
        root = FileManager.default.temporaryDirectory
            .appendingPathComponent("saved-outputs-\(UUID().uuidString)", isDirectory: true)
        folder = root.appendingPathComponent("Saved", isDirectory: true)
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        IOSSavedOutputsDestination.clearFolder()
    }

    override func tearDown() async throws {
        IOSSavedOutputsDestination.clearFolder()
        try? FileManager.default.removeItem(at: root)
    }

    private func clip(_ name: String) throws -> URL {
        let url = root.appendingPathComponent(name)
        try Data(repeating: 0x42, count: 512).write(to: url)
        return url
    }

    func testLockedPremiumClipStaysInsideTheAppAndPermittedClipsAreCopied() async throws {
        try IOSSavedOutputsDestination.setFolder(folder)
        XCTAssertTrue(IOSSavedOutputsDestination.hasExternalFolder)
        let design = try clip("design_take.wav")
        let locked = IOSSavedOutputsDestination.exportIfConfigured(
            internalAudioPath: design.path, generationMode: "design"
        ) { IOSExportAccessPolicy.permits([$0], unlocked: false) }
        XCTAssertNil(locked, "a locked Design clip must not start a copy")
        XCTAssertFalse(FileManager.default.fileExists(atPath: folder.appendingPathComponent("design_take.wav").path))

        let builtIn = try clip("custom_take.wav")
        let free = IOSSavedOutputsDestination.exportIfConfigured(
            internalAudioPath: builtIn.path, generationMode: "custom"
        ) { IOSExportAccessPolicy.permits([$0], unlocked: false) }
        let freeTask = try XCTUnwrap(free, "a Built-in clip copies without the unlock")
        let freeCopied = await freeTask.value
        XCTAssertTrue(freeCopied)
        XCTAssertTrue(FileManager.default.fileExists(atPath: folder.appendingPathComponent("custom_take.wav").path))

        let unlocked = IOSSavedOutputsDestination.exportIfConfigured(
            internalAudioPath: design.path, generationMode: "design"
        ) { IOSExportAccessPolicy.permits([$0], unlocked: true) }
        let unlockedTask = try XCTUnwrap(unlocked, "an unlocked Design clip copies")
        let unlockedCopied = await unlockedTask.value
        XCTAssertTrue(unlockedCopied)
        XCTAssertTrue(FileManager.default.fileExists(atPath: folder.appendingPathComponent("design_take.wav").path))
    }

    func testNoFolderMeansNoCopyEvenWhenPermitted() throws {
        XCTAssertFalse(IOSSavedOutputsDestination.hasExternalFolder)
        let builtIn = try clip("custom_take.wav")
        XCTAssertNil(IOSSavedOutputsDestination.exportIfConfigured(
            internalAudioPath: builtIn.path, generationMode: "custom"
        ) { _ in true })
    }

    /// IOS-25: a copy that cannot land is recorded for the Settings row
    /// instead of disappearing, and the next copy that lands clears it, as
    /// choosing or clearing the folder does.
    func testAFailedCopyIsRecordedUntilACopyLandsOrTheFolderChanges() async throws {
        try IOSSavedOutputsDestination.setFolder(folder)
        XCTAssertNil(IOSSavedOutputsDestination.exportIssue)
        let take = try clip("custom_take.wav")

        try FileManager.default.setAttributes([.posixPermissions: 0o555], ofItemAtPath: folder.path)
        let refused = try XCTUnwrap(IOSSavedOutputsDestination.exportIfConfigured(
            internalAudioPath: take.path, generationMode: "custom"
        ) { _ in true })
        let refusedCopied = await refused.value
        try FileManager.default.setAttributes([.posixPermissions: 0o755], ofItemAtPath: folder.path)
        XCTAssertFalse(refusedCopied)
        XCTAssertEqual(IOSSavedOutputsDestination.exportIssue, .copyFailed)

        let landed = try XCTUnwrap(IOSSavedOutputsDestination.exportIfConfigured(
            internalAudioPath: take.path, generationMode: "custom"
        ) { _ in true })
        let landedCopied = await landed.value
        XCTAssertTrue(landedCopied)
        XCTAssertNil(IOSSavedOutputsDestination.exportIssue, "a copy that lands clears the issue")

        try FileManager.default.setAttributes([.posixPermissions: 0o555], ofItemAtPath: folder.path)
        let refusedAgain = try XCTUnwrap(IOSSavedOutputsDestination.exportIfConfigured(
            internalAudioPath: take.path, generationMode: "custom"
        ) { _ in true })
        _ = await refusedAgain.value
        try FileManager.default.setAttributes([.posixPermissions: 0o755], ofItemAtPath: folder.path)
        XCTAssertEqual(IOSSavedOutputsDestination.exportIssue, .copyFailed)
        try IOSSavedOutputsDestination.setFolder(folder)
        XCTAssertNil(IOSSavedOutputsDestination.exportIssue, "choosing the folder again clears the issue")
    }

    /// A copy still in flight when the folder is cleared reports into the
    /// folder it resolved, not onto the new choice: its failure is dropped.
    func testALateFailureDoesNotLandAfterTheFolderChanges() async throws {
        try IOSSavedOutputsDestination.setFolder(folder)
        let take = try clip("custom_late.wav")
        try FileManager.default.setAttributes([.posixPermissions: 0o555], ofItemAtPath: folder.path)
        let refused = try XCTUnwrap(IOSSavedOutputsDestination.exportIfConfigured(
            internalAudioPath: take.path, generationMode: "custom"
        ) { _ in true })
        // The outcome is recorded on the main actor, which this test holds
        // until it awaits, so the folder change always comes first.
        IOSSavedOutputsDestination.clearFolder()
        let copied = await refused.value
        try FileManager.default.setAttributes([.posixPermissions: 0o755], ofItemAtPath: folder.path)
        XCTAssertFalse(copied)
        XCTAssertNil(IOSSavedOutputsDestination.exportIssue)
    }

    /// IOS-25: a folder that went away is reported, not skipped in silence;
    /// clearing the folder ends the report.
    func testAFolderThatWentAwayIsRecorded() async throws {
        try IOSSavedOutputsDestination.setFolder(folder)
        try FileManager.default.removeItem(at: folder)
        let take = try clip("custom_take.wav")
        let copy = IOSSavedOutputsDestination.exportIfConfigured(
            internalAudioPath: take.path, generationMode: "custom"
        ) { _ in true }
        if let copy {
            // The bookmark still resolved to the old place; the copy cannot land there.
            let copied = await copy.value
            XCTAssertFalse(copied)
            XCTAssertEqual(IOSSavedOutputsDestination.exportIssue, .copyFailed)
        } else {
            XCTAssertEqual(IOSSavedOutputsDestination.exportIssue, .folderUnavailable)
        }
        IOSSavedOutputsDestination.clearFolder()
        XCTAssertNil(IOSSavedOutputsDestination.exportIssue)
    }

    /// A3-01: a copy that cannot land never costs the user a same-named file
    /// already in their folder, and a copy that lands replaces it whole,
    /// leaving no staging file behind.
    func testAFailedCopyKeepsTheSameNamedFileAlreadyInTheFolder() async throws {
        try IOSSavedOutputsDestination.setFolder(folder)
        let existing = folder.appendingPathComponent("custom_take.wav")
        let usersFile = Data("the user's own file".utf8)
        try usersFile.write(to: existing)
        // The internal take is gone, so no copy can be made.
        let missing = root.appendingPathComponent("custom_take.wav")
        let failed = try XCTUnwrap(IOSSavedOutputsDestination.exportIfConfigured(
            internalAudioPath: missing.path, generationMode: "custom"
        ) { _ in true })
        let failedCopied = await failed.value
        XCTAssertFalse(failedCopied)
        XCTAssertEqual(IOSSavedOutputsDestination.exportIssue, .copyFailed)
        XCTAssertEqual(try Data(contentsOf: existing), usersFile)

        let take = try clip("custom_take.wav")
        let landed = try XCTUnwrap(IOSSavedOutputsDestination.exportIfConfigured(
            internalAudioPath: take.path, generationMode: "custom"
        ) { _ in true })
        let landedCopied = await landed.value
        XCTAssertTrue(landedCopied)
        XCTAssertEqual(try Data(contentsOf: existing), try Data(contentsOf: take))
        XCTAssertEqual(try FileManager.default.contentsOfDirectory(atPath: folder.path), ["custom_take.wav"])
    }

    /// A4-01: a Design take that finishes while the launch entitlement scan is
    /// still running is reported on the Settings row instead of being skipped
    /// in silence, and is copied once the scan verifies the unlock. Nothing
    /// here buys or restores.
    func testAPaidTakeFinishedWhileAccessIsCheckedIsReportedThenCopiedOnceVerified() async throws {
        try IOSSavedOutputsDestination.setFolder(folder)
        let client = FolderCopyExportClient()
        client.entitlements = [IOSExportTransaction(id: 1, productID: IOSExportAccessPolicy.productID,
                                                    verified: true, nonConsumable: true, revoked: false)]
        let purchases = IOSExportPurchaseState(client: client)
        XCTAssertEqual(purchases.access, .checking)
        let entered = expectation(description: "entitlement scan running")
        client.scanEntered = { entered.fulfill() }
        let take = try clip("design_take.wav")
        let destination = folder.appendingPathComponent("design_take.wav")

        let copy = try XCTUnwrap(IOSSavedOutputsDestination.exportIfConfigured(
            internalAudioPath: take.path, generationMode: "design", purchases: purchases
        ), "the copy waits for the scan instead of being dropped")
        XCTAssertEqual(IOSSavedOutputsDestination.exportIssue, .accessUnverified)
        await fulfillment(of: [entered], timeout: 2)
        XCTAssertFalse(FileManager.default.fileExists(atPath: destination.path))

        client.settleScan()
        let copied = await copy.value
        XCTAssertTrue(copied)
        XCTAssertTrue(FileManager.default.fileExists(atPath: destination.path))
        XCTAssertNil(IOSSavedOutputsDestination.exportIssue, "the landed copy ends the report")
        XCTAssertEqual(client.purchaseCount, 0)
        XCTAssertEqual(client.syncCount, 0)
    }

    /// A4-01: a scan that finds no unlock leaves the take in History, as any
    /// locked Design or Clone take stays, and ends the report. A Built-in take
    /// never waits for the scan.
    func testAPaidTakeStaysInHistoryWhenTheScanFindsNoUnlock() async throws {
        try IOSSavedOutputsDestination.setFolder(folder)
        let client = FolderCopyExportClient()
        let purchases = IOSExportPurchaseState(client: client)
        let entered = expectation(description: "entitlement scan running")
        client.scanEntered = { entered.fulfill() }

        let builtIn = try clip("custom_take.wav")
        let free = try XCTUnwrap(IOSSavedOutputsDestination.exportIfConfigured(
            internalAudioPath: builtIn.path, generationMode: "custom", purchases: purchases
        ))
        let freeCopied = await free.value
        XCTAssertTrue(freeCopied)
        XCTAssertEqual(client.scanCount, 0, "a free take copies without waiting for access")
        XCTAssertNil(IOSSavedOutputsDestination.exportIssue)

        let take = try clip("clone_take.wav")
        let copy = try XCTUnwrap(IOSSavedOutputsDestination.exportIfConfigured(
            internalAudioPath: take.path, generationMode: "clone", purchases: purchases
        ))
        XCTAssertEqual(IOSSavedOutputsDestination.exportIssue, .accessUnverified)
        await fulfillment(of: [entered], timeout: 2)
        client.settleScan()
        let copied = await copy.value
        XCTAssertFalse(copied)
        XCTAssertEqual(purchases.access, .locked)
        XCTAssertFalse(FileManager.default.fileExists(atPath: folder.appendingPathComponent("clone_take.wav").path))
        XCTAssertNil(IOSSavedOutputsDestination.exportIssue, "a verified lock is the documented History-only outcome")
        XCTAssertEqual(client.purchaseCount, 0)
    }

    /// A failure already on the Settings row is not replaced by the waiting
    /// report, so a scan that finds no unlock cannot clear it unseen.
    func testAnEarlierFailureStaysReportedWhileAccessIsChecked() async throws {
        try IOSSavedOutputsDestination.setFolder(folder)
        try FileManager.default.setAttributes([.posixPermissions: 0o555], ofItemAtPath: folder.path)
        let refused = try XCTUnwrap(IOSSavedOutputsDestination.exportIfConfigured(
            internalAudioPath: try clip("custom_take.wav").path, generationMode: "custom"
        ) { _ in true })
        _ = await refused.value
        try FileManager.default.setAttributes([.posixPermissions: 0o755], ofItemAtPath: folder.path)
        XCTAssertEqual(IOSSavedOutputsDestination.exportIssue, .copyFailed)

        let client = FolderCopyExportClient()
        let purchases = IOSExportPurchaseState(client: client)
        let entered = expectation(description: "entitlement scan running")
        client.scanEntered = { entered.fulfill() }
        let copy = try XCTUnwrap(IOSSavedOutputsDestination.exportIfConfigured(
            internalAudioPath: try clip("design_take.wav").path, generationMode: "design", purchases: purchases
        ))
        XCTAssertEqual(IOSSavedOutputsDestination.exportIssue, .copyFailed)
        await fulfillment(of: [entered], timeout: 2)
        client.settleScan()
        let copied = await copy.value
        XCTAssertFalse(copied)
        XCTAssertEqual(purchases.access, .locked)
        XCTAssertEqual(IOSSavedOutputsDestination.exportIssue, .copyFailed)
    }

    /// P10-09: a Built-in copy that refreshes a stale bookmark rewrites the
    /// stored bookmark for the same folder. A paid take waiting on the access
    /// check is still copied once access verifies; only choosing or clearing
    /// the folder ends its wait.
    func testAWaitingPaidTakeStillCopiesWhenABookmarkRefreshRewritesTheSameFolder() async throws {
        try IOSSavedOutputsDestination.setFolder(folder)
        let client = FolderCopyExportClient()
        client.entitlements = [IOSExportTransaction(id: 1, productID: IOSExportAccessPolicy.productID,
                                                    verified: true, nonConsumable: true, revoked: false)]
        let purchases = IOSExportPurchaseState(client: client)
        let entered = expectation(description: "entitlement scan running")
        client.scanEntered = { entered.fulfill() }
        let destination = folder.appendingPathComponent("design_take.wav")

        let copy = try XCTUnwrap(IOSSavedOutputsDestination.exportIfConfigured(
            internalAudioPath: try clip("design_take.wav").path, generationMode: "design", purchases: purchases
        ))
        await fulfillment(of: [entered], timeout: 2)

        // What the refresh stores: other bookmark bytes that resolve to the same folder.
        let original = try folder.bookmarkData(options: [], includingResourceValuesForKeys: nil, relativeTo: nil)
        let refreshed = try folder.bookmarkData(
            options: [],
            includingResourceValuesForKeys: [.localizedNameKey, .isHiddenKey, .creationDateKey, .contentModificationDateKey],
            relativeTo: nil
        )
        XCTAssertNotEqual(refreshed, original, "the refresh must change the stored bytes for this test to hold")
        let choice = IOSSavedOutputsDestination.folderChoice
        IOSSavedOutputsDestination.storeRefreshedBookmark(refreshed)
        XCTAssertEqual(IOSSavedOutputsDestination.folderChoice, choice, "a refresh is not a new folder choice")
        let free = try XCTUnwrap(IOSSavedOutputsDestination.exportIfConfigured(
            internalAudioPath: try clip("custom_take.wav").path, generationMode: "custom", purchases: purchases
        ))
        let freeCopied = await free.value
        XCTAssertTrue(freeCopied)

        client.settleScan()
        let copied = await copy.value
        XCTAssertTrue(copied, "the waiting copy belongs to the same folder choice")
        XCTAssertTrue(FileManager.default.fileExists(atPath: destination.path))
        XCTAssertNil(IOSSavedOutputsDestination.exportIssue)
    }

    /// Choosing a folder again while a paid take waits ends that take's wait:
    /// its copy never lands on the new choice.
    func testAWaitingPaidTakeIsDroppedWhenTheFolderIsChosenAgain() async throws {
        try IOSSavedOutputsDestination.setFolder(folder)
        let client = FolderCopyExportClient()
        client.entitlements = [IOSExportTransaction(id: 1, productID: IOSExportAccessPolicy.productID,
                                                    verified: true, nonConsumable: true, revoked: false)]
        let purchases = IOSExportPurchaseState(client: client)
        let entered = expectation(description: "entitlement scan running")
        client.scanEntered = { entered.fulfill() }
        let copy = try XCTUnwrap(IOSSavedOutputsDestination.exportIfConfigured(
            internalAudioPath: try clip("clone_take.wav").path, generationMode: "clone", purchases: purchases
        ))
        await fulfillment(of: [entered], timeout: 2)

        let other = root.appendingPathComponent("Other", isDirectory: true)
        try FileManager.default.createDirectory(at: other, withIntermediateDirectories: true)
        try IOSSavedOutputsDestination.setFolder(other)
        client.settleScan()
        let copied = await copy.value
        XCTAssertFalse(copied)
        XCTAssertFalse(FileManager.default.fileExists(atPath: other.appendingPathComponent("clone_take.wav").path))
        XCTAssertFalse(FileManager.default.fileExists(atPath: folder.appendingPathComponent("clone_take.wav").path))
    }

    func testPolicySeesTheSavedRowsModeNotAnyCurrentSelection() throws {
        try IOSSavedOutputsDestination.setFolder(folder)
        var seen: [IOSExportProvenance] = []
        for (mode, expected) in [("custom", IOSExportProvenance.builtIn), ("clone", .generatedPremium),
                                 ("Design", .generatedPremium), ("weird", .unknown)] {
            let clip = try clip("\(mode).wav")
            _ = IOSSavedOutputsDestination.exportIfConfigured(internalAudioPath: clip.path, generationMode: mode) {
                seen.append($0)
                return false
            }
            XCTAssertEqual(seen.last, expected, mode)
        }
        XCTAssertEqual(seen.count, 4)
    }
}

/// A StoreKit boundary whose launch entitlement scan the test settles.
@MainActor
private final class FolderCopyExportClient: IOSExportPurchaseClient {
    var entitlements: [IOSExportTransaction] = []
    var scanEntered: (() -> Void)?
    private(set) var scanCount = 0
    private(set) var purchaseCount = 0
    private(set) var syncCount = 0
    private var pendingScan: CheckedContinuation<[IOSExportTransaction], Never>?

    func product() async throws -> IOSExportProduct? { nil }
    func currentEntitlements() async -> [IOSExportTransaction] {
        scanCount += 1
        return await withCheckedContinuation { pendingScan = $0; scanEntered?() }
    }
    func settleScan() {
        pendingScan?.resume(returning: entitlements)
        pendingScan = nil
    }
    func purchase() async throws -> IOSExportPurchaseResult { purchaseCount += 1; return .cancelled }
    func sync() async throws -> IOSExportSyncResult { syncCount += 1; return .synced }
    func finish(_ transaction: IOSExportTransaction) async {}
    func observe(_ receive: @escaping @MainActor (IOSExportTransaction) async -> Void) async {}
}
