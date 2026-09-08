import XCTest
import QwenVoiceCore

@MainActor
final class IOSExportPurchaseTests: XCTestCase {
    func testProvenanceComesFromOutputModeNotCurrentSelection() {
        for mode in ["custom", "CUSTOM"] {
            XCTAssertTrue(IOSExportAccessPolicy.permits([.init(generationMode: mode)], unlocked: false))
        }
        for mode in ["design", "clone", "unknown", "", " custom "] {
            XCTAssertFalse(IOSExportAccessPolicy.permits([.init(generationMode: mode)], unlocked: false))
        }
        XCTAssertFalse(IOSExportAccessPolicy.permits([.init(generationMode: nil)], unlocked: false))
        XCTAssertTrue(IOSExportAccessPolicy.permits([.originalReference, .recoveryRecord], unlocked: false))
        XCTAssertFalse(IOSExportAccessPolicy.permits([.builtIn, .generatedPremium], unlocked: false))
        XCTAssertTrue(IOSExportAccessPolicy.permits([.builtIn, .generatedPremium], unlocked: true))
        XCTAssertFalse(IOSExportAccessPolicy.permits([], unlocked: true))
    }

    func testInitialCheckingDoesNotBlockFreeExportOrGrantPaidExport() {
        let store = IOSExportPurchaseState(client: FakeExportClient())
        XCTAssertEqual(store.access, .checking)
        XCTAssertTrue(store.permits([.builtIn]))
        XCTAssertFalse(store.permits([.generatedPremium]))
    }

    func testVerifiedCachedEntitlementRestoresOnRelaunchWithoutSyncOrProductNetwork() async {
        let client = FakeExportClient()
        client.entitlements = [transaction()]
        client.failProduct = true
        let store = IOSExportPurchaseState(client: client)
        await store.refresh()
        await store.loadProduct()
        XCTAssertEqual(store.access, .unlocked)
        XCTAssertTrue(store.permits([.generatedPremium]))
        XCTAssertNil(store.product)
        XCTAssertEqual(client.syncCount, 0)
        XCTAssertEqual(client.purchaseCount, 0)
    }

    func testUnverifiedRevokedWrongProductAndWrongTypeNeverGrant() async {
        for receipt in [transaction(verified: false), transaction(revoked: true),
                        transaction(productID: "other"), transaction(nonConsumable: false)] {
            let client = FakeExportClient()
            client.entitlements = [receipt]
            let store = IOSExportPurchaseState(client: client)
            await store.refresh()
            XCTAssertEqual(store.access, .locked)
        }
    }

    func testSuccessfulPurchaseGrantsBeforeFinishingAndKeepsLocalizedPrice() async {
        let client = FakeExportClient()
        let store = IOSExportPurchaseState(client: client)
        client.beforeFinish = { XCTAssertEqual(store.access, .unlocked) }
        await store.loadProduct()
        XCTAssertEqual(store.product?.displayPrice, "1,23 €")
        await store.purchase()
        XCTAssertEqual(store.access, .unlocked)
        XCTAssertEqual(client.finished, [1])
        XCTAssertEqual(store.operation, .idle)
    }

    func testCancelledPendingFailedAndUnverifiedPurchaseDoNotUnlock() async {
        for result in [IOSExportPurchaseResult.cancelled, .pending, .success(transaction(verified: false))] {
            let client = FakeExportClient()
            client.result = result
            let store = IOSExportPurchaseState(client: client)
            await store.refresh()
            await store.loadProduct()
            await store.purchase()
            XCTAssertEqual(store.access, .locked)
            XCTAssertTrue(client.finished.isEmpty)
            XCTAssertNotNil(store.notice)
        }
        let client = FakeExportClient()
        client.failPurchase = true
        let store = IOSExportPurchaseState(client: client)
        await store.loadProduct()
        await store.purchase()
        XCTAssertFalse(store.permits([.generatedPremium]))
        XCTAssertEqual(store.notice, .failed)
    }

    func testMissingOrWrongProductRefusesPurchase() async {
        for product in [nil, IOSExportProduct(id: "wrong", displayPrice: "1")] {
            let client = FakeExportClient()
            client.offeredProduct = product
            let store = IOSExportPurchaseState(client: client)
            await store.loadProduct()
            await store.purchase()
            XCTAssertEqual(client.purchaseCount, 0)
            XCTAssertEqual(store.notice, .unavailable)
        }
    }

    func testRestoreExplicitlySyncsAndReportsNoPurchaseOrFailureWithoutErasingOwnedAccess() async {
        let client = FakeExportClient()
        let store = IOSExportPurchaseState(client: client)
        await store.refresh()
        XCTAssertEqual(client.syncCount, 0)
        await store.restore()
        XCTAssertEqual(store.notice, .notOwned)
        client.entitlements = [transaction()]
        await store.restore()
        XCTAssertEqual(store.notice, .restored)
        XCTAssertEqual(store.access, .unlocked)
        client.failSync = true
        await store.restore()
        XCTAssertEqual(store.notice, .failed)
        XCTAssertEqual(store.access, .unlocked)
    }

    func testPendingApprovalAndRefundArriveThroughSingleListener() async {
        let client = FakeExportClient()
        let store = IOSExportPurchaseState(client: client)
        store.start()
        store.start()
        await store.refresh()
        await client.emit(transaction())
        XCTAssertEqual(store.access, .unlocked)
        await client.emit(transaction(revoked: true))
        XCTAssertEqual(store.access, .locked)
        XCTAssertTrue(store.permits([.originalReference]))
        XCTAssertEqual(client.observerCount, 1)
    }

    func testOlderSnapshotCannotUndoARefund() async {
        let client = FakeExportClient()
        let store = IOSExportPurchaseState(client: client)
        await store.refresh()
        await client.emit(transaction())
        let entered = expectation(description: "entitlement scan suspended")
        client.scanEntered = { entered.fulfill() }
        client.suspendScan = true
        let scan = Task { await store.refresh() }
        await fulfillment(of: [entered], timeout: 2)
        await client.emit(transaction(revoked: true))
        client.resumeScan(with: [transaction()])
        await scan.value
        XCTAssertEqual(store.access, .locked)
    }

    func testLateSuccessCannotUndoRefundAndOldRefundCannotRevokeNewPurchase() async {
        let client = FakeExportClient()
        let store = IOSExportPurchaseState(client: client)
        await store.refresh()
        await client.emit(transaction(revoked: true))
        await client.emit(transaction())
        XCTAssertEqual(store.access, .locked)
        await client.emit(IOSExportTransaction(id: 2, productID: IOSExportAccessPolicy.productID,
            verified: true, nonConsumable: true, revoked: false))
        await client.emit(transaction(revoked: true))
        XCTAssertEqual(store.access, .unlocked)
    }

    func testOverlappingRestoreOrPurchaseIsRefused() async {
        let client = FakeExportClient()
        let store = IOSExportPurchaseState(client: client)
        await store.loadProduct()
        let entered = expectation(description: "purchase suspended")
        client.purchaseEntered = { entered.fulfill() }
        client.suspendPurchase = true
        let purchase = Task { await store.purchase() }
        await fulfillment(of: [entered], timeout: 2)
        await store.purchase()
        await store.restore()
        XCTAssertEqual(client.purchaseCount, 1)
        XCTAssertEqual(client.syncCount, 0)
        client.resumePurchase()
        await purchase.value
        XCTAssertEqual(store.access, .unlocked)
    }

    func testEnrollmentProvenanceRoundTripsAndOldMetadataStillDecodes() throws {
        let original = PreparedVoiceEnrollmentMetadata(referenceLanguage: .french, transcriptSource: .manual)
        let encodedOld = try JSONEncoder().encode(original)
        XCTAssertNil(try JSONDecoder().decode(PreparedVoiceEnrollmentMetadata.self, from: encodedOld).generatedSourceMode)
        let legacy = Data(#"{"schemaVersion":1,"transcriptSource":"manual"}"#.utf8)
        XCTAssertNil(try JSONDecoder().decode(PreparedVoiceEnrollmentMetadata.self, from: legacy).generatedSourceMode)
        let generated = PreparedVoiceEnrollmentMetadata(referenceLanguage: .french,
            transcriptSource: .manual, generatedSourceMode: "design")
        XCTAssertEqual(try JSONDecoder().decode(PreparedVoiceEnrollmentMetadata.self,
            from: JSONEncoder().encode(generated)), generated)
    }

    private func transaction(productID: String = IOSExportAccessPolicy.productID,
                             verified: Bool = true, nonConsumable: Bool = true,
                             revoked: Bool = false) -> IOSExportTransaction {
        IOSExportTransaction(id: 1, productID: productID, verified: verified,
                             nonConsumable: nonConsumable, revoked: revoked)
    }
}

@MainActor
private final class FakeExportClient: IOSExportPurchaseClient {
    var entitlements: [IOSExportTransaction] = []
    var offeredProduct: IOSExportProduct? = .init(id: IOSExportAccessPolicy.productID, displayPrice: "1,23 €")
    var result: IOSExportPurchaseResult = .success(.init(id: 1, productID: IOSExportAccessPolicy.productID,
                                                       verified: true, nonConsumable: true, revoked: false))
    var failProduct = false
    var failPurchase = false
    var failSync = false
    var suspendScan = false
    var suspendPurchase = false
    var scanEntered: (() -> Void)?
    var purchaseEntered: (() -> Void)?
    var beforeFinish: (() -> Void)?
    var finished: [UInt64] = []
    var syncCount = 0
    var purchaseCount = 0
    var observerCount = 0
    private var scanContinuation: CheckedContinuation<[IOSExportTransaction], Never>?
    private var purchaseContinuation: CheckedContinuation<Void, Never>?
    private var delivered: CheckedContinuation<Void, Never>?
    private let stream: AsyncStream<IOSExportTransaction>
    private let continuation: AsyncStream<IOSExportTransaction>.Continuation

    init() { (stream, continuation) = AsyncStream.makeStream() }
    func product() async throws -> IOSExportProduct? {
        if failProduct { throw Failure.expected }
        return offeredProduct
    }
    func currentEntitlements() async -> [IOSExportTransaction] {
        if suspendScan {
            return await withCheckedContinuation { scanContinuation = $0; scanEntered?() }
        }
        return entitlements
    }
    func resumeScan(with value: [IOSExportTransaction]) {
        scanContinuation?.resume(returning: value); scanContinuation = nil
    }
    func purchase() async throws -> IOSExportPurchaseResult {
        purchaseCount += 1
        if suspendPurchase {
            await withCheckedContinuation { purchaseContinuation = $0; purchaseEntered?() }
        }
        if failPurchase { throw Failure.expected }
        return result
    }
    func resumePurchase() { purchaseContinuation?.resume(); purchaseContinuation = nil }
    func sync() async throws { syncCount += 1; if failSync { throw Failure.expected } }
    func finish(_ transaction: IOSExportTransaction) async {
        beforeFinish?(); finished.append(transaction.id)
    }
    func observe(_ receive: @escaping @MainActor (IOSExportTransaction) async -> Void) async {
        observerCount += 1
        for await value in stream {
            await receive(value)
            delivered?.resume(); delivered = nil
        }
    }
    func emit(_ value: IOSExportTransaction) async {
        await withCheckedContinuation { delivered = $0; continuation.yield(value) }
    }
    private enum Failure: Error { case expected }
}
