import Foundation
import XCTest

/// A StoreKit boundary whose entitlement scan the test controls.
@MainActor
private final class GateFixtureExportClient: IOSExportPurchaseClient {
    var entitlements: [IOSExportTransaction] = []
    var suspendsScan = false
    private(set) var startedScans = 0
    private(set) var purchaseCount = 0
    private var pendingScan: CheckedContinuation<[IOSExportTransaction], Never>?

    func product() async throws -> IOSExportProduct? { nil }

    func currentEntitlements() async -> [IOSExportTransaction] {
        startedScans += 1
        guard suspendsScan else { return entitlements }
        return await withCheckedContinuation { pendingScan = $0 }
    }

    func resumeScan() {
        pendingScan?.resume(returning: entitlements)
        pendingScan = nil
    }

    func purchase() async throws -> IOSExportPurchaseResult {
        purchaseCount += 1
        return .cancelled
    }

    func sync() async throws {}
    func finish(_ transaction: IOSExportTransaction) async {}
    func observe(_ receive: @escaping @MainActor (IOSExportTransaction) async -> Void) async {}
}

@MainActor
private final class ExportActionLog {
    var count = 0
}

/// PA-19: the one iOS export boundary. Free provenance exports at once; paid
/// provenance consults verified StoreKit entitlements and otherwise offers the
/// purchase sheet; a newer request supersedes an older pending check; nothing is
/// exported silently after a purchase.
@MainActor
final class IOSExportGateTests: XCTestCase {
    private var premiumReceipt: IOSExportTransaction {
        IOSExportTransaction(
            id: 7,
            productID: IOSExportAccessPolicy.productID,
            verified: true,
            nonConsumable: true,
            revoked: false
        )
    }

    private func makeGate(client: GateFixtureExportClient) -> (IOSExportGate, IOSExportPurchaseState) {
        let store = IOSExportPurchaseState(client: client)
        return (IOSExportGate(commerce: { store }), store)
    }

    private func waitUntil(
        _ description: String,
        file: StaticString = #filePath,
        line: UInt = #line,
        _ condition: () -> Bool
    ) async {
        let clock = ContinuousClock()
        let deadline = clock.now.advanced(by: .seconds(2))
        while !condition() {
            guard clock.now < deadline else {
                XCTFail("Timed out waiting for \(description)", file: file, line: line)
                return
            }
            await Task.yield()
            try? await Task.sleep(nanoseconds: 1_000_000)
        }
    }

    func testFreeProvenanceExportsAtOnceWithoutConsultingTheStore() {
        let client = GateFixtureExportClient()
        let (gate, _) = makeGate(client: client)
        let log = ExportActionLog()

        gate.perform(provenance: [.builtIn, .originalReference, .recoveryRecord]) { log.count += 1 }
        XCTAssertEqual(log.count, 1)

        let urls = [URL(fileURLWithPath: "/nonexistent/pa19-built-in.wav")]
        gate.share(urls: urls, provenance: [.builtIn])
        XCTAssertEqual(gate.presentation?.urls, urls, "Free audio opens the share sheet directly")
        XCTAssertEqual(client.startedScans, 0, "Free export never waits on StoreKit")
    }

    func testLockedPaidProvenanceOffersThePurchaseSheetInsteadOfExporting() async {
        let client = GateFixtureExportClient()
        let (gate, store) = makeGate(client: client)
        let log = ExportActionLog()

        gate.perform(provenance: [.builtIn, .generatedPremium]) { log.count += 1 }
        XCTAssertEqual(log.count, 0, "Paid provenance waits for verified entitlements")
        await waitUntil("the purchase sheet") { gate.presentation != nil }

        XCTAssertNotNil(gate.presentation)
        XCTAssertNil(gate.presentation?.urls, "nil URLs present the purchase sheet")
        XCTAssertEqual(log.count, 0)
        XCTAssertEqual(store.access, .locked)
        XCTAssertEqual(client.startedScans, 1)
        XCTAssertEqual(client.purchaseCount, 0, "The gate never purchases on its own")
    }

    func testVerifiedEntitlementExportsPaidProvenance() async {
        let client = GateFixtureExportClient()
        client.entitlements = [premiumReceipt]
        let (gate, store) = makeGate(client: client)
        let log = ExportActionLog()

        gate.perform(provenance: [.generatedPremium]) { log.count += 1 }
        await waitUntil("the entitled export") { log.count == 1 }
        XCTAssertNil(gate.presentation)
        XCTAssertEqual(store.access, .unlocked)

        let urls = [URL(fileURLWithPath: "/nonexistent/pa19-design.wav")]
        gate.share(urls: urls, provenance: [.generatedPremium])
        await waitUntil("the entitled share sheet") { gate.presentation != nil }
        XCTAssertEqual(gate.presentation?.urls, urls)
    }

    func testUnknownProvenanceIsTreatedAsPaid() async {
        let client = GateFixtureExportClient()
        let (gate, _) = makeGate(client: client)
        let log = ExportActionLog()

        gate.perform(provenance: [IOSExportProvenance(generationMode: nil)]) { log.count += 1 }
        await waitUntil("the purchase sheet") { gate.presentation != nil }
        XCTAssertEqual(log.count, 0)
    }

    func testMalformedRequestsDoNothing() {
        let client = GateFixtureExportClient()
        let (gate, _) = makeGate(client: client)
        let log = ExportActionLog()
        let url = URL(fileURLWithPath: "/nonexistent/pa19.wav")

        gate.perform(provenance: []) { log.count += 1 }
        gate.share(urls: [], provenance: [])
        gate.share(urls: [url, url], provenance: [.builtIn])
        XCTAssertEqual(log.count, 0)
        XCTAssertNil(gate.presentation)
        XCTAssertEqual(client.startedScans, 0)
    }

    func testANewerRequestSupersedesAPendingEntitlementCheck() async {
        let client = GateFixtureExportClient()
        client.suspendsScan = true
        let (gate, store) = makeGate(client: client)
        let premium = ExportActionLog()
        let free = ExportActionLog()

        gate.perform(provenance: [.generatedPremium]) { premium.count += 1 }
        await waitUntil("the entitlement scan to start") { client.startedScans == 1 }

        gate.perform(provenance: [.builtIn]) { free.count += 1 }
        XCTAssertEqual(free.count, 1)

        client.resumeScan()
        await waitUntil("the stale check to finish") { store.access == .locked }
        for _ in 0..<5 { await Task.yield() }
        XCTAssertNil(gate.presentation, "A superseded check never presents the purchase sheet")
        XCTAssertEqual(premium.count, 0)
    }
}
